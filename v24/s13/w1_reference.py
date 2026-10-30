"""Independent W1-only reference transformations. Never imported by the host."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

MAX_SAFE = 2**53 - 1


def _scalar(text: str) -> str:
    if any(0xD800 <= ord(ch) <= 0xDFFF for ch in text):
        raise ValueError('lone_surrogate')
    return text


def _integer(value: int) -> str:
    if abs(value) > MAX_SAFE:
        raise ValueError('unsafe_integer')
    return str(value)


def _quote(value: str) -> str:
    return json.dumps(_scalar(value), ensure_ascii=False)


def strict_loads(raw: str | bytes) -> Any:
    """Reject lexically invalid JSON before numeric/coalescing information is lost."""
    if isinstance(raw, bytes):
        raw = raw.decode('utf-8', 'strict')
    def pairs(items):
        obj = {}
        for key, value in items:
            if key in obj:
                raise ValueError('duplicate_key')
            obj[_scalar(key)] = value
        return obj
    def integer(token):
        if token == '-0':
            raise ValueError('negative_zero')
        value = int(token)
        _integer(value)
        return value
    def no_float(token):
        raise ValueError('non_integer_number')
    def no_constant(token):
        raise ValueError('non_json_constant')
    value = json.loads(raw, object_pairs_hook=pairs, parse_int=integer,
                       parse_float=no_float, parse_constant=no_constant)
    def visit(x):
        if isinstance(x, str):
            _scalar(x)
        elif isinstance(x, dict):
            for k, v in x.items():
                _scalar(k); visit(v)
        elif isinstance(x, list):
            for v in x:
                visit(v)
    visit(value)
    return value


def pg_canonical(value: Any) -> bytes:
    """PostgreSQL jsonb::text ordering and spacing, independent of host."""
    def encode(x):
        if isinstance(x, dict):
            keys = sorted(x, key=lambda k: (len(k.encode('utf-8')), k.encode('utf-8')))
            return '{' + ', '.join(_quote(k) + ': ' + encode(x[k]) for k in keys) + '}'
        if isinstance(x, list):
            return '[' + ', '.join(encode(v) for v in x) + ']'
        if isinstance(x, str):
            return _quote(x)
        if x is True: return 'true'
        if x is False: return 'false'
        if x is None: return 'null'
        if type(x) is int: return _integer(x)
        raise ValueError('unsupported_json_value')
    return encode(value).encode('utf-8')


def compact(value: Any) -> bytes:
    """W1 J: unsigned UTF-8 byte key ordering, compact, scalar-safe JSON."""
    def encode(x):
        if isinstance(x, dict):
            keys = sorted(x, key=lambda k: k.encode('utf-8'))
            return '{' + ','.join(_quote(k) + ':' + encode(x[k]) for k in keys) + '}'
        if isinstance(x, list):
            return '[' + ','.join(encode(v) for v in x) + ']'
        if isinstance(x, str): return _quote(x)
        if x is True: return 'true'
        if x is False: return 'false'
        if x is None: return 'null'
        if type(x) is int: return _integer(x)
        raise ValueError('unsupported_json_value')
    return encode(value).encode('utf-8')


def frame_request(operation: str, reservation: str, args: dict, tool: str | None = None) -> bytes:
    if operation not in ('invoke', 'prepare', 'release', 'inspect') or not isinstance(args, dict):
        raise ValueError('bad_request')
    frame = {'v': 2, 'operation': operation, 'reservation': reservation, 'args': args}
    if operation == 'invoke':
        if not isinstance(tool, str) or not re.fullmatch(r'[a-z][a-z0-9_.-]{0,127}', tool) or tool == 'agent.spawn':
            raise ValueError('bad_request')
        frame['tool'] = tool
    elif tool is not None:
        raise ValueError('bad_request')
    return compact(frame) + b'\n'


def classify_response(raw: bytes, operation: str = 'invoke', exit_code: int = 0) -> str:
    if not raw: return 'eof'
    try: text = raw.decode('utf-8', 'strict')
    except UnicodeDecodeError: return 'stdout_not_utf8'
    if raw.count(b'\n') > 1: return 'extra_frame'
    if not raw.endswith(b'\n') or raw.count(b'\n') != 1 or text.startswith('\ufeff'):
        return 'bad_frame'
    body = text[:-1].strip(' \t\r')
    try: obj = strict_loads(body)
    except (ValueError, json.JSONDecodeError): return 'bad_frame'
    if not isinstance(obj, dict): return 'bad_frame'
    if obj.get('v') != 2: return 'version_mismatch'
    if type(obj.get('ok')) is not bool: return 'bad_frame'
    if obj['ok']:
        if exit_code != 0 or set(obj) != {'ok','v','result'}: return 'bad_frame'
        result = obj['result']
        if not isinstance(result, dict): return 'bad_frame'
        if operation == 'invoke':
            if not {'value'} <= set(result) <= {'value','meta'}:
                return 'bad_frame'
            if 'meta' in result and not isinstance(result['meta'], dict): return 'bad_frame'
        else:
            expected = {'prepare': {'prepared': True}, 'release': {'released': True}}
            if operation == 'inspect':
                if set(result) != {'observed'} or result['observed'] not in ('known','absent'):
                    return 'bad_frame'
            elif (operation not in expected or set(result) != set(expected[operation])
                  or next(iter(result.values())) is not True): return 'bad_frame'
        return 'success'
    if exit_code != 3 or set(obj) != {'ok','v','error'}: return 'bad_frame'
    error = obj['error']
    if not isinstance(error, dict) or set(error) != {'code','message'}: return 'bad_frame'
    if not isinstance(error['code'], str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', error['code']):
        return 'bad_frame'
    if not isinstance(error['message'], str) or len(error['message'].encode('utf-8')) > 1024:
        return 'bad_frame'
    if any(x in error['message'] for x in ('\x00', 'Traceback (', 'stack trace', 'DEEPSEEK_API_KEY=', 'OPENAI_API_KEY=')) or re.search(r'(?:^|\s)(?:/\S*|[A-Za-z]:[\\/]|\\\\)', error['message']):
        return 'bad_frame'
    return 'known_error'


def render(kind: str, value: dict) -> tuple[list[dict], dict]:
    d = lambda n: 'null' if n is None else str(n)
    if kind == 'read':
        t = '[empty file]' if value['total_lines'] == 0 else value['text']
        if value['truncated']:
            t += '\n\n[Showing lines '+d(value['start_line'])+'-'+d(value['end_line'])+' of '+d(value['total_lines'])+'. Use offset='+d(value['next_offset'])+' to continue.]'
    elif kind == 'list':
        lines = []
        for entry in value['entries']:
            p = entry['path']
            lines.append(p+'/' if entry['kind']=='directory' else p+'@' if entry['kind']=='symlink' else p+' ('+d(entry['size'])+' B)')
        t = '\n'.join(lines) if lines else '[empty directory]'
        if value['truncated']:
            end = value['offset']+len(value['entries'])-1
            t += '\n\n[Showing '+d(value['offset'])+'-'+d(end)+' of '+d(value['total'])+'. Use offset='+d(value['next_offset'])+' to continue.]'
    elif kind == 'search':
        lines = []
        for hit in value['hits']:
            for context in hit.get('before', []):
                lines.append(hit['path']+'-'+d(context['line'])+'- '+context['text'])
            lines.append(hit['path']+':'+d(hit['line'])+':'+d(hit['column'])+': '+hit['text'])
            for context in hit.get('after', []):
                lines.append(hit['path']+'-'+d(context['line'])+'- '+context['text'])
        t = '\n'.join(lines) if lines else '[no matches]'
        n = len(value['hits'])
        a = d(value['offset']) if n else '0'
        b = d(value['offset']+n-1) if n else '0'
        total = d(value['total']) + ('' if value['complete'] else '+')
        skipped = sum(value['skipped'].values())
        t += '\n\n[hits '+a+'-'+b+' of '+total+'; scanned '+d(value['scanned_files'])+'; skipped '+d(skipped)+']'
        if value['truncated']: t += '\n[Use offset='+d(value['next_offset'])+' to continue.]'
    else: raise ValueError('unknown_renderer')
    return [{'type':'text','text':t}], {}


def escaped_payload_bytes(text: str) -> int:
    return len(_quote(text).encode('utf-8'))-2


def render_count(kind: str, v: dict) -> int:
    """Token-wise counter independent of the renderer's assembled text."""
    d = lambda x: 'null' if x is None else str(x)
    tokens = []
    if kind == 'read':
        tokens = ['[empty file]' if v['total_lines'] == 0 else v['text']]
        if v['truncated']:
            tokens += ['\n\n[Showing lines ',d(v['start_line']),'-',d(v['end_line']),' of ',d(v['total_lines']),'. Use offset=',d(v['next_offset']),' to continue.]']
    elif kind == 'list':
        for e in v['entries']:
            if tokens: tokens.append('\n')
            tokens += [e['path']]
            tokens += ['/'] if e['kind']=='directory' else ['@'] if e['kind']=='symlink' else [' (',d(e['size']),' B)']
        if not tokens: tokens=['[empty directory]']
        if v['truncated']:
            tokens += ['\n\n[Showing ',d(v['offset']),'-',d(v['offset']+len(v['entries'])-1),' of ',d(v['total']),'. Use offset=',d(v['next_offset']),' to continue.]']
    else:
        def line(parts):
            if tokens: tokens.append('\n')
            tokens.extend(parts)
        for h in v['hits']:
            for c in h.get('before',[]): line([h['path'],'-',d(c['line']),'- ',c['text']])
            line([h['path'],':',d(h['line']),':',d(h['column']),': ',h['text']])
            for c in h.get('after',[]): line([h['path'],'-',d(c['line']),'- ',c['text']])
        if not tokens: tokens=['[no matches]']
        n=len(v['hits'])
        tokens += ['\n\n[hits ',d(v['offset']) if n else '0','-',d(v['offset']+n-1) if n else '0',' of ',d(v['total']),'' if v['complete'] else '+','; scanned ',d(v['scanned_files']),'; skipped ',d(sum(v['skipped'].values())),']']
        if v['truncated']: tokens += ['\n[Use offset=',d(v['next_offset']),' to continue.]']
    # Scalar widths, not the JSON encoder or complete concatenated content.
    def width(ch):
        if ch in ('"','\\','\b','\f','\n','\r','\t'): return 2
        if ord(ch)<32: return 6
        return len(ch.encode('utf-8'))
    return 27+sum(width(ch) for token in tokens for ch in token)


def budget_measures(args: dict, value: dict, content: list, meta: dict | None = None) -> dict:
    return {'args':len(compact(args)), 'value':len(compact(value)),
            'content':len(compact(content)), 'meta':len(compact({} if meta is None else meta)),
            'frame':len(compact({'ok':True,'v':2,'result':{'value':value}}))+1}


def manifest_digest(renderer_id: str, version: int, projection: int, cases: list[dict]) -> dict:
    ordered = sorted(cases, key=lambda c: c['id'].encode('utf-8'))
    golden = hashlib.sha256(compact(ordered)).hexdigest()
    manifest = {'id':renderer_id,'version':version,'projection':projection,'golden_digest':golden}
    return {'golden_digest':golden,'render_digest':hashlib.sha256(compact(manifest)).hexdigest()}


def select_prefix(kind: str, args: dict, values: list[dict], caps: dict) -> int | None:
    """Enumerate every finalized nonempty prefix; return the largest fitting k."""
    selected = None
    for k, value in enumerate(values, 1):
        content, meta = render(kind, value)
        measures = budget_measures(args, value, content, meta)
        if all(measures[name] <= caps[name] for name in ('value', 'content', 'meta', 'frame')):
            selected = k
    return selected


def page_decision(probe: dict) -> dict:
    """W1 snapshot adjudicator, with no filesystem/runtime behavior."""
    kind, args, values, caps = (probe[k] for k in ('kind', 'args', 'values', 'caps'))
    if probe.get('source_error'):
        return {'error': probe['source_error']}
    if any(page_error(kind, args, v) for v in values):
        return {'error': 'invalid_tool_output'}
    if not values:
        if probe.get('scan_end') == 'cutoff':
            return {'error': 'search_scope_too_large'}
        empty = probe.get('empty_value')
        if empty is None or args.get('offset', 1) != 1:
            return {'error': 'offset_out_of_range'}
        if page_error(kind, args, empty):
            return {'error': 'invalid_tool_output'}
        content, meta = render(kind, empty)
        m = budget_measures(args, empty, content, meta)
        return {'selected': 0} if all(m[n] <= caps[n] for n in caps) else {'error': 'output_too_large'}
    selected = select_prefix(kind, args, values, caps)
    if selected is None:
        return {'error': {'read':'line_too_long', 'list':'entry_too_large', 'search':'hit_too_large'}[kind]}
    if kind == 'search' and probe.get('scan_end') == 'cutoff':
        limit = args.get('limit', 200)
        if not (selected == len(values) == limit or selected < len(values)):
            return {'error': 'search_scope_too_large'}
    return {'selected': selected}


def page_error(kind: str, args: dict, v: dict) -> bool:
    """Relations in §5.6 only; input shape is frozen separately by schema cases."""
    def unsafe(x):
        if type(x) is int: return abs(x) > MAX_SAFE
        if isinstance(x, dict): return any(unsafe(y) for y in x.values())
        if isinstance(x, list): return any(unsafe(y) for y in x)
        return False
    if unsafe(v): return True
    offset = args.get('offset', 1)
    limit = args.get('limit', {'read':2000,'list':500,'search':200}[kind])
    if kind == 'read':
        total = v['total_lines']
        if total == 0:
            return v != dict(path=v['path'], text='', start_line=0, end_line=0, total_lines=0,
                             final_newline=False, truncated=False, truncated_by=None, next_offset=None)
        k = v['end_line']-v['start_line']+1
        if not (v['start_line'] == offset and 1 <= offset <= v['end_line'] <= total and 1 <= k <= limit): return True
        lines = v['text'].split('\n')
        if len(lines) != k or any(len(s.encode('utf-8')) > 16384 for s in lines): return True
        truncated = v['end_line'] < total
        if v['truncated_by'] != (('lines' if k == limit else 'bytes') if truncated else None): return True
    else:
        items = v['entries' if kind == 'list' else 'hits']; k = len(items); total = v['total']
        if v['offset'] != offset or k > limit: return True
        if k == 0:
            return not (offset == 1 and total == 0 and (kind != 'search' or v['complete']) and
                        not v['truncated'] and v['next_offset'] is None)
        if offset+k-1 > total: return True
        if kind == 'list' and any((e['kind']=='file') != (type(e['size']) is int) for e in items): return True
        truncated = offset+k-1 < total or (kind == 'search' and not v['complete'])
    cursor = offset+k if truncated else None
    return v['truncated'] != truncated or v['next_offset'] != cursor or (cursor is not None and cursor > MAX_SAFE)


def model_text(content: list[dict]) -> bytes:
    return '\n'.join(block['text'] for block in content).encode('utf-8')
