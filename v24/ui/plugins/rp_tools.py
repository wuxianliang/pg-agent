#!/usr/bin/env python3
"""Standalone stdlib rp v2 tool family."""
from __future__ import annotations

import difflib
import errno
import fnmatch
import json
import os
import re
import selectors
import signal
import stat
import subprocess
import sys
import time
import unicodedata
import uuid
from pathlib import Path

FAMILY_IDENTITY = "v24.ui.rp_tools"
FAMILY_VERSION = "1"
TOOL_SPECS = ({'key': 'read_file',
  'description': 'Read verbatim with 1-based start_line, unlike read offset; -N tails, 0 or negative plus '
                 'limit invalid; head budgets with notice.',
  'parameters': {'type': 'object',
                 'additionalProperties': False,
                 'required': ['path'],
                 'properties': {'path': {'type': 'string'},
                                'start_line': {'type': 'integer'},
                                'limit': {'type': 'integer', 'minimum': 1, 'maximum': 2000}}},
  'output_schema': {'type': 'object',
                    'additionalProperties': False,
                    'required': ['text', 'truncated', 'spill_path'],
                    'properties': {'text': {'type': 'string'},
                                   'truncated': {'type': 'boolean'},
                                   'spill_path': {'type': 'string', 'maxLength': 128}}},
  'timeout_ms': 5000,
  'limits': {'timeout_ms': 5000,
             'max_args_bytes': 8192,
             'max_value_bytes': 40960,
             'max_content_bytes': 41984,
             'max_meta_bytes': 4096},
  'concurrency': 'parallel',
  'replay_class': 'read_only',
  'annotations': {'read_only': True, 'destructive': False, 'idempotent': True, 'open_world': False}},
 {'key': 'file_search',
  'description': 'Search grouped paths/content: mode auto/path/content/both, regex=true, whole_word, '
                 'context_lines, max_results=50, count_only, filter. Auto infers glob paths. Unlike grep '
                 'glob/literal. Binary skipped/count.',
  'parameters': {'type': 'object',
                 'additionalProperties': False,
                 'required': ['pattern'],
                 'properties': {'pattern': {'type': 'string', 'minLength': 1},
                                'mode': {'type': 'string', 'enum': ['auto', 'path', 'content', 'both']},
                                'regex': {'type': 'boolean'},
                                'whole_word': {'type': 'boolean'},
                                'context_lines': {'type': 'integer', 'minimum': 0, 'maximum': 100},
                                'max_results': {'type': 'integer', 'minimum': 1, 'maximum': 1000},
                                'count_only': {'type': 'boolean'},
                                'filter': {'type': 'object',
                                           'additionalProperties': False,
                                           'required': [],
                                           'properties': {'extensions': {'type': 'array',
                                                                         'items': {'type': 'string'}},
                                                          'paths': {'type': 'array',
                                                                    'items': {'type': 'string'}},
                                                          'exclude': {'type': 'array',
                                                                      'items': {'type': 'string'}}}}}},
  'output_schema': {'type': 'object',
                    'additionalProperties': False,
                    'required': ['text', 'truncated', 'spill_path'],
                    'properties': {'text': {'type': 'string'},
                                   'truncated': {'type': 'boolean'},
                                   'spill_path': {'type': 'string', 'maxLength': 128}}},
  'timeout_ms': 15000,
  'limits': {'timeout_ms': 15000,
             'max_args_bytes': 16384,
             'max_value_bytes': 40960,
             'max_content_bytes': 41984,
             'max_meta_bytes': 4096},
  'concurrency': 'parallel',
  'replay_class': 'read_only',
  'annotations': {'read_only': True, 'destructive': False, 'idempotent': True, 'open_world': False}},
 {'key': 'get_file_tree',
  'description': 'ASCII tree; auto depth 2, full/folders unlimited; selected=full with no-selection notice; '
                 'max_depth overrides.',
  'parameters': {'type': 'object',
                 'additionalProperties': False,
                 'required': [],
                 'properties': {'path': {'type': 'string'},
                                'max_depth': {'type': 'integer', 'minimum': 0},
                                'mode': {'type': 'string', 'enum': ['auto', 'full', 'folders', 'selected']}}},
  'output_schema': {'type': 'object',
                    'additionalProperties': False,
                    'required': ['text', 'truncated', 'spill_path'],
                    'properties': {'text': {'type': 'string'},
                                   'truncated': {'type': 'boolean'},
                                   'spill_path': {'type': 'string', 'maxLength': 128}}},
  'timeout_ms': 5000,
  'limits': {'timeout_ms': 5000,
             'max_args_bytes': 8192,
             'max_value_bytes': 40960,
             'max_content_bytes': 41984,
             'max_meta_bytes': 4096},
  'concurrency': 'parallel',
  'replay_class': 'read_only',
  'annotations': {'read_only': True, 'destructive': False, 'idempotent': True, 'open_world': False}},
 {'key': 'apply_edits',
  'description': 'Exactly one mode: rewrite, search+replace, or edits. on_missing only with rewrite. '
                 'Multiple modes: mode_conflict; absent/incomplete: invalid_mode. Status '
                 'success/partial/failed/no_change; exact original matches, unlike Pi fuzzy edit.',
  'parameters': {'type': 'object',
                 'additionalProperties': False,
                 'required': [],
                 'properties': {'path': {'type': 'string'},
                                'rewrite': {'type': 'string'},
                                'search': {'type': 'string'},
                                'replace': {'type': 'string'},
                                'edits': {'type': 'array',
                                          'items': {'type': 'object',
                                                    'additionalProperties': False,
                                                    'required': ['oldText', 'newText'],
                                                    'properties': {'oldText': {'type': 'string'},
                                                                   'newText': {'type': 'string'}}}},
                                'on_missing': {'type': 'string', 'enum': ['error', 'create']}}},
  'output_schema': {'type': 'object',
                    'additionalProperties': False,
                    'required': ['text', 'truncated', 'spill_path', 'status'],
                    'properties': {'text': {'type': 'string'},
                                   'truncated': {'type': 'boolean'},
                                   'spill_path': {'type': 'string', 'maxLength': 128},
                                   'status': {'type': 'string',
                                              'enum': ['success', 'partial', 'failed', 'no_change']}}},
  'timeout_ms': 5000,
  'limits': {'timeout_ms': 5000,
             'max_args_bytes': 65536,
             'max_value_bytes': 40960,
             'max_content_bytes': 41984,
             'max_meta_bytes': 4096},
  'concurrency': 'exclusive',
  'replay_class': 'mutating',
  'annotations': {'read_only': False, 'destructive': True, 'idempotent': False, 'open_world': False}})

# ==== BEGIN SHARED CORE (v24-ui-family-v1) ====
# Keep this region byte-identical in both independently executable artifacts.
MAX_FILE_BYTES = 1024 * 1024
MAX_TEXT_LINES = 2000
MAX_TEXT_BYTES = 32768
MAX_VALUE_BYTES = 40960
MAX_CONTENT_BYTES = 41984
MAX_META_BYTES = 4096
MAX_SPILL_BYTES = 8 * 1024 * 1024
SPILL_RESERVE = 128
SPILL_NAMESPACE = '.v24/spill'
SKILLS_NAMESPACE = '.v24/skills'
_SAFE_INTEGER_MAX = 2**53 - 1
_SENSITIVE_PARTS = frozenset({'.git', '.uidata'})
_ERRORS = frozenset('root_unavailable invalid_arguments path_escape path_excluded symlink_denied not_found permission_denied not_a_file binary_file not_utf8 file_too_large line_too_long output_too_large io_error timeout spill_write_failed mode_conflict invalid_mode edit_not_found edit_ambiguous edit_overlap edit_noop edit_empty_old match_not_unique match_not_found'.split())
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def _json_quote(value):
    value.encode('utf-8', 'strict')
    return json.dumps(value, ensure_ascii=False)


def canonical_json(value):
    """Host compact J encoding, including UTF-8 key order and safe integers."""
    if isinstance(value, dict):
        if any(not isinstance(k, str) for k in value):
            raise ValueError('non_string_key')
        return '{' + ','.join(_json_quote(k) + ':' + canonical_json(value[k])
                              for k in sorted(value, key=lambda k: k.encode('utf-8'))) + '}'
    if isinstance(value, list):
        return '[' + ','.join(canonical_json(x) for x in value) + ']'
    if value is True: return 'true'
    if value is False: return 'false'
    if value is None: return 'null'
    if type(value) is int and abs(value) <= _SAFE_INTEGER_MAX: return str(value)
    if isinstance(value, str): return _json_quote(value)
    raise ValueError('unsupported_json_value')


frame = canonical_json


def _text(value, *, nonempty=False, nul_code='binary_file'):
    if not isinstance(value, str) or (nonempty and not value):
        raise ValueError('invalid_arguments')
    if '\x00' in value: raise ValueError(nul_code)
    try: value.encode('utf-8')
    except UnicodeEncodeError: raise ValueError('not_utf8') from None
    return value


def _args(args, allowed, required=()):
    if type(args) is not dict or set(args) - set(allowed) or set(required) - set(args):
        raise ValueError('invalid_arguments')


def _integer(value, low, high=None):
    if type(value) is not int or value < low or (high is not None and value > high):
        raise ValueError('invalid_arguments')
    return value


def _root(variable, error='root_unavailable'):
    raw = os.environ.get(variable)
    if not raw or not os.path.isabs(raw) or os.path.realpath(raw) != raw:
        raise ValueError(error)
    try:
        if not stat.S_ISDIR(os.lstat(raw).st_mode): raise ValueError(error)
    except OSError: raise ValueError(error) from None
    return Path(raw)


def _workspace_root(): return _root('V24_WORKSPACE_ROOT')


def _spill_root(): return _root('V24_SPILL_ROOT', 'spill_write_failed')


def _excluded(relative):
    return any(p.lower() in _SENSITIVE_PARTS or p.lower().startswith('.env')
               or p.lower().endswith('.pem') or p.lower().startswith('id_rsa')
               or p.lower().startswith('id_ed25519') for p in Path(relative).parts)


def _regular(path):
    try: return stat.S_ISREG(os.lstat(path).st_mode)
    except OSError: return False


def _os_error(exc):
    if isinstance(exc, FileNotFoundError): return 'not_found'
    if isinstance(exc, PermissionError): return 'permission_denied'
    if exc.errno == errno.ELOOP: return 'symlink_denied'
    return 'io_error'


def _classify_path(raw, *, write=False, discovery=False):
    _text(raw, nonempty=True, nul_code='invalid_arguments')
    if len(raw.encode('utf-8')) > 1024: raise ValueError('invalid_arguments')
    lexical = Path(raw)
    if '..' in lexical.parts: raise ValueError('path_escape')
    root = _workspace_root()
    if lexical.is_absolute():
        try: relative = lexical.relative_to(root)
        except ValueError: raise ValueError('path_escape') from None
    else: relative = lexical
    # Sensitive lexical components are rejected before any target existence probe.
    if _excluded(relative): raise ValueError('path_excluded')
    parts = relative.parts
    kind = 'workspace'
    if parts and parts[0].lower() == '.v24':
        if write or discovery: raise ValueError('path_excluded')
        if parts[:2] == ('.v24', 'spill'):
            root, parts, kind = _spill_root(), parts[2:], 'spill'
        elif parts[:2] == ('.v24', 'skills'):
            root, parts, kind = _root('V24_SKILLS_ROOT'), parts[2:], 'skills'
        else: raise ValueError('path_excluded')
    return kind, root, parts


def _path_parts(raw, *, write=False, discovery=False):
    _, root, parts = _classify_path(raw, write=write, discovery=discovery)
    return root, parts


def _open_root(root):
    """O_NOFOLLOW applies to every configured-root component, too."""
    fd = os.open(root.anchor, _DIR_FLAGS)
    try:
        for name in root.parts[1:]:
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode): raise ValueError('symlink_denied')
            if not stat.S_ISDIR(info.st_mode): raise ValueError('root_unavailable')
            child = os.open(name, _DIR_FLAGS, dir_fd=fd)
            if (info.st_dev, info.st_ino) != (os.fstat(child).st_dev, os.fstat(child).st_ino):
                os.close(child)
                raise ValueError('io_error')
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _open_parent(root, parts, *, create=False):
    """Traverse with directory descriptors; never follow a parent symlink."""
    fd = _open_root(root)
    try:
        for name in parts:
            try: info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                if not create: raise
                try: os.mkdir(name, mode=0o700, dir_fd=fd)
                except FileExistsError: pass
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode): raise ValueError('symlink_denied')
            if not stat.S_ISDIR(info.st_mode): raise ValueError('not_a_file')
            child = os.open(name, _DIR_FLAGS, dir_fd=fd)
            if _signature(info) != _signature(os.fstat(child)):
                os.close(child)
                raise ValueError('io_error')
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _signature(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _inspect_path(root, parts, *, missing=False, directory=None):
    fd = _open_parent(root, parts[:-1])
    try:
        try: info = os.stat(parts[-1] if parts else '.', dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            if missing: return None
            raise
        if stat.S_ISLNK(info.st_mode): raise ValueError('symlink_denied')
        if directory is True and not stat.S_ISDIR(info.st_mode): raise ValueError('not_a_file')
        if directory is False and not stat.S_ISREG(info.st_mode): raise ValueError('not_a_file')
        if directory is None and not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise ValueError('not_a_file')
        return info
    finally: os.close(fd)


def resolve_path(raw, *, write=False, directory=False):
    root, parts = _path_parts(raw, write=write)
    try: _inspect_path(root, parts, directory=directory)
    except OSError as exc: raise ValueError(_os_error(exc)) from None
    return root.joinpath(*parts)


def _search_root(raw):
    root, parts = _path_parts(raw, discovery=True)
    try: _inspect_path(root, parts)
    except OSError as exc: raise ValueError(_os_error(exc)) from None
    return root.joinpath(*parts)


def _location(path):
    """Map an already validated physical path back to its approved root."""
    candidates = [('V24_WORKSPACE_ROOT', 'root_unavailable'),
                  ('V24_SPILL_ROOT', 'spill_write_failed'), ('V24_SKILLS_ROOT', 'root_unavailable')]
    for variable, error in candidates:
        raw = os.environ.get(variable)
        if not raw: continue
        try: relative = path.relative_to(Path(raw))
        except ValueError: continue
        return _root(variable, error), relative.parts
    raise ValueError('path_escape')


def _read_at(root, parts):
    if not parts: raise ValueError('not_a_file')
    parent = fd = None
    try:
        parent = _open_parent(root, parts[:-1])
        before = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
        if stat.S_ISLNK(before.st_mode): raise ValueError('symlink_denied')
        if not stat.S_ISREG(before.st_mode): raise ValueError('not_a_file')
        if before.st_size > MAX_FILE_BYTES: raise ValueError('file_too_large')
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        opened = os.fstat(fd)
        if _signature(before) != _signature(opened): raise ValueError('io_error')
        chunks, size = [], 0
        while True:
            chunk = os.read(fd, min(65536, MAX_FILE_BYTES + 1 - size))
            if not chunk: break
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_FILE_BYTES: raise ValueError('file_too_large')
        after = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
        if _signature(opened) != _signature(os.fstat(fd)) or _signature(opened) != _signature(after):
            raise ValueError('io_error')
        data = b''.join(chunks)
        if b'\x00' in data: raise ValueError('binary_file')
        try:
            directory = os.fstat(parent)
            return data.decode('utf-8'), _signature(after), (directory.st_dev, directory.st_ino)
        except UnicodeDecodeError: raise ValueError('not_utf8') from None
    except OSError as exc: raise ValueError(_os_error(exc)) from None
    finally:
        if fd is not None: os.close(fd)
        if parent is not None: os.close(parent)


def _read_snapshot(path):
    text, signature, _ = _read_at(*_location(path))
    return text, signature


def read_utf8(path): return _read_snapshot(path)[0]


def read_source(raw):
    # Provenance comes from the same checked descriptor snapshot as the text.
    kind, root, parts = _classify_path(raw)
    text, signature, identity = _read_at(root, parts)
    managed = kind == 'spill' and len(parts) == 1 and re.fullmatch(r'[0-9a-f]{32}\.txt', parts[0])
    return text, (root, identity, parts[0], signature) if managed else None


def _confirm_source_spill(reference):
    root, identity, name, signature = reference
    parent = fd = None
    try:
        if _spill_root() != root: raise ValueError('io_error')
        parent = _open_root(root)
        current_root = os.fstat(parent)
        if (current_root.st_dev, current_root.st_ino) != identity: raise ValueError('io_error')
        before = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if stat.S_ISLNK(before.st_mode): raise ValueError('symlink_denied')
        if not stat.S_ISREG(before.st_mode) or _signature(before) != signature: raise ValueError('io_error')
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        if (_signature(os.fstat(fd)) != signature or
                _signature(os.stat(name, dir_fd=parent, follow_symlinks=False)) != signature):
            raise ValueError('io_error')
        return SPILL_NAMESPACE + '/' + name
    except OSError as exc: raise ValueError(_os_error(exc)) from None
    finally:
        if fd is not None: os.close(fd)
        if parent is not None: os.close(parent)


def _write_snapshot(raw, *, create=False):
    root, parts = _path_parts(raw, write=True)
    if not parts: raise ValueError('not_a_file')
    target = root.joinpath(*parts)
    try:
        _inspect_path(root, parts, directory=False)
    except (FileNotFoundError, ValueError) as exc:
        if isinstance(exc, ValueError) or not create: raise ValueError(str(exc) if isinstance(exc, ValueError) else 'not_found') from None
        return target, '', None
    except OSError as exc: raise ValueError(_os_error(exc)) from None
    text, signature = _read_snapshot(target)
    return target, text, signature


def _payload(text):
    _text(text)
    data = text.encode('utf-8')
    if len(data) > MAX_FILE_BYTES: raise ValueError('file_too_large')
    return data


class PostCommitError(Exception):
    """An effect or its cleanup is uncertain; the host must preserve unknown."""


def atomic_mutation(raw, text, expected):
    """All callers plan output first; commit one same-directory replacement."""
    data = _payload(text)
    root, parts = _path_parts(raw, write=True)
    if not parts: raise ValueError('not_a_file')
    parent = fd = None
    committed = False
    temporary = '.' + uuid.uuid4().hex + '.tmp'
    try:
        parent = _open_parent(root, parts[:-1], create=True)
        try: current = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError: current = None
        if current is not None and stat.S_ISLNK(current.st_mode): raise ValueError('symlink_denied')
        if current is not None and not stat.S_ISREG(current.st_mode): raise ValueError('not_a_file')
        if (None if current is None else _signature(current)) != expected: raise ValueError('io_error')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        mode = stat.S_IMODE(current.st_mode) if current is not None else 0o600
        with os.fdopen(fd, 'wb') as stream:
            fd = None
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        try: latest = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError: latest = None
        if (None if latest is None else _signature(latest)) != expected: raise ValueError('io_error')
        # The outer host deadline guards commit; no internal alarm may label
        # an already replaced target as a known, safely retryable failure.
        signal.setitimer(signal.ITIMER_REAL, 0)
        os.replace(temporary, parts[-1], src_dir_fd=parent, dst_dir_fd=parent)
        committed = True
        os.fsync(parent)
    except BaseException as exc:
        if committed: raise PostCommitError() from None
        if isinstance(exc, OSError): raise ValueError(_os_error(exc)) from None
        raise
    finally:
        if fd is not None: os.close(fd)
        if parent is not None:
            try: os.unlink(temporary, dir_fd=parent)
            except OSError: pass
            try: os.close(parent)
            except OSError:
                if committed: raise PostCommitError() from None
                raise


def _prune_spill(directory, keep):
    """Only UUID-named regular managed spills count toward the 50/8-MiB policy."""
    files = []
    try:
        with os.scandir(directory) as entries:
            for item in entries:
                if not re.fullmatch(r'[0-9a-f]{32}\.txt', item.name): continue
                info = item.stat(follow_symlinks=False)
                if stat.S_ISREG(info.st_mode): files.append((info.st_mtime_ns, item.name, info.st_size))
        files.sort()
        total, count = sum(x[2] for x in files), len(files)
        for _, name, size in files:
            if count <= 50 and total <= MAX_SPILL_BYTES: break
            if name == keep: continue
            try:
                if not stat.S_ISREG(os.stat(name, dir_fd=directory, follow_symlinks=False).st_mode): continue
                os.unlink(name, dir_fd=directory)
            except OSError: continue
            total -= size
            count -= 1
    except OSError: pass


def spill_write(text):
    _text(text)
    payload = text.encode('utf-8')
    if len(payload) > MAX_FILE_BYTES: raise ValueError('output_too_large')
    temporary = '.' + uuid.uuid4().hex + '.tmp'
    name = uuid.uuid4().hex + '.txt'
    directory = fd = None
    try:
        root = _spill_root()
        directory = _open_root(root)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        with os.fdopen(fd, 'wb') as stream:
            fd = None
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
        _prune_spill(directory, name)
        return SPILL_NAMESPACE + '/' + name
    except OSError: raise ValueError('spill_write_failed') from None
    finally:
        if fd is not None: os.close(fd)
        if directory is not None:
            try: os.unlink(temporary, dir_fd=directory)
            except OSError: pass
            os.close(directory)


def spill_read(path): return read_utf8(resolve_path(path))


def _fits(value):
    text = value['text']
    return (len(text.splitlines()) <= MAX_TEXT_LINES and len(text.encode('utf-8')) <= MAX_TEXT_BYTES
            and len(canonical_json(value).encode('utf-8')) <= MAX_VALUE_BYTES - SPILL_RESERVE)


def finish_text(text, *, spill=True, offset=1, limit=MAX_TEXT_LINES, coordinate='offset', extra=None, source_spill=None):
    """Whole-line head projection; notices use original source coordinates."""
    _text(text)
    if len(text.encode('utf-8')) > MAX_FILE_BYTES: raise ValueError('output_too_large')
    lines = text.splitlines(keepends=True)
    start = offset - 1
    selected = lines[start:start + limit]
    count = min(len(selected), MAX_TEXT_LINES)
    placeholder = SPILL_NAMESPACE + '/' + '0' * 32 + '.txt'
    for _ in range(64):
        shown = ''.join(selected[:count])
        truncated = start + count < len(lines)
        path = placeholder if truncated else ''
        notice = (f'[Showing lines {offset}-{start + count} of {len(lines)}. '
                  f'Use {coordinate}={start + count + 1} to continue. Full text: {path}]') if truncated else ''
        rendered = shown + ('' if not shown or shown.endswith(('\n', '\r', '\v', '\f', '\x1c', '\x1d', '\x1e', '\x85', '\u2028', '\u2029')) else '\n') + notice if notice else shown
        value = dict(text=rendered, truncated=truncated, spill_path=path, **(extra or {}))
        if _fits(value):
            if selected and count == 0: raise ValueError('line_too_long')
            if truncated:
                if source_spill is not None:
                    actual = _confirm_source_spill(source_spill)
                else:
                    if not spill: raise ValueError('spill_write_failed')
                    actual = spill_write(text)
                # Substitute only in our notice; source bytes may contain the placeholder.
                value['text'] = shown + ('' if not shown or shown.endswith(('\n', '\r', '\v', '\f', '\x1c', '\x1d', '\x1e', '\x85', '\u2028', '\u2029')) else '\n') + notice.replace(placeholder, actual)
                value['spill_path'] = actual
            if '\x00' in value['text']: raise ValueError('binary_file')
            return value
        if count <= 1: raise ValueError('line_too_long')
        ratio = min(MAX_TEXT_BYTES / max(1, len(rendered.encode('utf-8'))),
                    (MAX_VALUE_BYTES - SPILL_RESERVE) / len(canonical_json(value).encode('utf-8')),
                    MAX_TEXT_LINES / max(1, len(rendered.splitlines())))
        count = max(1, min(count - 1, int(count * ratio * 0.97)))
    raise ValueError('output_too_large')


def finish_command(text, exit_code):
    text = _text(text.replace('\x00', '\ufffd'))
    footer = f'Command exited with code {exit_code}' if exit_code else ''
    full = text.rstrip('\r\n') + ('\n\n' if text.rstrip('\r\n') else '') + footer if footer else text
    if len(full.encode('utf-8')) > MAX_FILE_BYTES: raise ValueError('output_too_large')
    # Only command tails may cut a source line. Work in code points to keep UTF-8 valid.
    lines = text.splitlines(keepends=True)
    shown = ''.join(lines[-MAX_TEXT_LINES:])
    shown = shown.encode('utf-8')[-MAX_TEXT_BYTES:].decode('utf-8', 'ignore')
    placeholder = SPILL_NAMESPACE + '/' + '0' * 32 + '.txt'
    for _ in range(64):
        truncated = shown != text
        notice = f'[Showing last output. Full text: {placeholder}]\n' if truncated else ''
        rendered = notice + shown.rstrip('\r\n') + ('\n\n' if shown.rstrip('\r\n') else '') + footer if footer else notice + shown
        value = dict(text=rendered, truncated=truncated, spill_path=placeholder if truncated else '', exit_code=exit_code)
        if _fits(value):
            if truncated:
                actual = spill_write(full)
                value['text'] = notice.replace(placeholder, actual) + shown.rstrip('\r\n') + ('\n\n' if shown.rstrip('\r\n') else '') + footer if footer else notice.replace(placeholder, actual) + shown
                value['spill_path'] = actual
            if '\x00' in value['text']: raise ValueError('binary_file')
            return value
        if not shown: raise ValueError('output_too_large')
        ratio = min(MAX_TEXT_BYTES / max(1, len(rendered.encode('utf-8'))),
                    (MAX_VALUE_BYTES - SPILL_RESERVE) / len(canonical_json(value).encode('utf-8')),
                    MAX_TEXT_LINES / max(1, len(rendered.splitlines())))
        remove = max(64, len(shown) - int(len(shown) * ratio * 0.97))
        shown = shown[min(remove, len(shown)):]
    raise ValueError('output_too_large')


def _glob_regex(pattern):
    """Scoped glob subset: * never crosses /, ** does, **/ includes zero dirs."""
    out, i = '', 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == '*':
            if pattern[i:i + 2] == '**':
                i += 2
                if i < len(pattern) and pattern[i] == '/': out += '(?:.*/)?'; i += 1
                else: out += '.*'
                continue
            out += '[^/]*'
        elif ch == '?': out += '[^/]'
        elif ch == '[':
            end = pattern.find(']', i + 1)
            if end < 0: out += r'\['
            else:
                chunk = pattern[i + 1:end]
                if chunk.startswith('!'): chunk = '^' + chunk[1:]
                elif chunk.startswith('^'): chunk = '\\' + chunk
                out += '[' + chunk.replace('\\', r'\\') + ']'
                i = end
        else: out += re.escape(ch)
        i += 1
    try: return re.compile('^' + out + '$')
    except re.error: raise ValueError('invalid_arguments') from None


def _glob_match(relative, pattern):
    anchored = pattern.startswith('/')
    pattern = pattern.lstrip('/')
    target = relative if anchored or '/' in pattern else relative.rsplit('/', 1)[-1]
    return bool(_glob_regex(pattern).fullmatch(target))


def _ignore_rules(directory, scope):
    rules = []
    for name in ('.gitignore', '.ignore', '.fdignore'):
        path = directory / name
        try:
            if not _regular(path): continue
            content = read_utf8(path)
        except ValueError as exc:
            if str(exc) in ('not_found', 'not_utf8', 'binary_file', 'file_too_large', 'io_error'): continue
            raise
        for line in content.splitlines():
            line = line.rstrip()
            if not line or line.startswith('#'): continue
            escaped = line.startswith(('\\#', '\\!'))
            if escaped: line = line[1:]
            negate = not escaped and line.startswith('!')
            if negate: line = line[1:]
            if not line: continue
            only_dir = line.endswith('/')
            line = line.rstrip('/')
            rules.append((scope, line, negate, only_dir))
    return rules


def _ignored(relative, directory, rules):
    ignored = False
    for scope, pattern, negate, only_dir in rules:
        if only_dir and not directory: continue
        prefix = scope + '/' if scope else ''
        if prefix and not relative.startswith(prefix): continue
        local = relative[len(prefix):]
        if _glob_match(local, pattern): ignored = not negate
    return ignored


def _entries(directory):
    root, parts = _location(directory)
    fd = None
    try:
        fd = _open_parent(root, parts)
        result = []
        with os.scandir(fd) as entries:
            for entry in entries:
                if entry.name.startswith('.') or _excluded(Path(entry.name)): continue
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode): continue
                if stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode):
                    result.append((directory / entry.name, stat.S_ISDIR(info.st_mode)))
        return sorted(result, key=lambda row: row[0].name)
    except OSError as exc: raise ValueError(_os_error(exc)) from None
    finally:
        if fd is not None: os.close(fd)


def _walk(path, *, respect_ignore=False):
    """Iterative deterministic walk; immutable exclusions cannot be negated."""
    workspace = _workspace_root()
    rules = []
    if respect_ignore:
        parent_parts = path.relative_to(workspace).parts
        # Include ancestor rules when an explicit subdirectory is the search root.
        directory = workspace
        ancestors = parent_parts if path.is_file() else parent_parts[:-1]
        rules += _ignore_rules(directory, '')
        for part in ancestors:
            directory /= part
            rules += _ignore_rules(directory, directory.relative_to(workspace).as_posix())
    if _regular(path):
        if not respect_ignore or not _ignored(path.relative_to(workspace).as_posix(), False, rules): yield path
        return
    stack = [(path, rules, True)]
    while stack:
        directory, inherited, first = stack.pop()
        local = inherited
        if respect_ignore and not (first and directory == workspace):
            scope = directory.relative_to(workspace).as_posix()
            local = inherited + _ignore_rules(directory, '' if scope == '.' else scope)
        children = _entries(directory)
        pending = []
        for child, is_dir in children:
            relative = child.relative_to(workspace).as_posix()
            if respect_ignore and _ignored(relative, is_dir, local): continue
            if is_dir: pending.append((child, local, False))
            else: yield child
        stack.extend(reversed(pending))


def _occurrences(text, needle):
    positions, start = [], 0
    while True:
        index = text.find(needle, start)
        if index < 0: return positions
        positions.append((index, index + len(needle)))
        start = index + 1


_QUOTES = str.maketrans({'\u2018': "'", '\u2019': "'", '\u201a': "'", '\u201b': "'",
                        '\u201c': '"', '\u201d': '"', '\u201e': '"', '\u201f': '"',
                        **{ch: '-' for ch in '\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe58\ufe63\uff0d'}})


def _normalized(text):
    """NFKC with source intervals: annotated NFKD reorder + NFC composition."""
    decomposed = []
    for index, ch in enumerate(text):
        for unit in unicodedata.normalize('NFKD', ch):
            decomposed.append((unit, index, index + 1))
    # Stable canonical ordering within each combining sequence.
    ordered = []
    for unit in decomposed:
        cc = unicodedata.combining(unit[0])
        position = len(ordered)
        if cc:
            while position and unicodedata.combining(ordered[position - 1][0]) > cc:
                position -= 1
        ordered.insert(position, unit)
    composed = []
    starter = None
    last_cc = 0
    for ch, lo, hi in ordered:
        cc = unicodedata.combining(ch)
        merged = None
        if starter is not None and (last_cc < cc or last_cc == 0):
            trial = unicodedata.normalize('NFC', composed[starter][0] + ch)
            if len(trial) == 1: merged = trial
        if merged is not None:
            old = composed[starter]
            composed[starter] = (merged, min(lo, old[1]), max(hi, old[2]))
        else:
            if cc == 0: starter = len(composed)
            composed.append((ch, lo, hi))
            last_cc = cc
    result, spans = [], []
    for ch, lo, hi in composed:
        ch = ch.translate(_QUOTES)
        if ch.isspace():
            if result and result[-1] == ' ':
                spans[-1] = (min(spans[-1][0], lo), max(spans[-1][1], hi))
                continue
            ch = ' '
        result.append(ch)
        spans.append((lo, hi))
    return ''.join(result), spans


def _fuzzy_occurrences(original, needle):
    normalized, spans = _normalized(original)
    target = _normalized(needle)[0]
    if not target: return []
    found = set()
    for low, high in _occurrences(normalized, target):
        a = min(x[0] for x in spans[low:high])
        b = max(x[1] for x in spans[low:high])
        if _normalized(original[a:b])[0] == target: found.add((a, b))
    return sorted(found)


def plan_edits(original, edits, *, fuzzy=False, allow_missing=False):
    if type(edits) is not list or not edits: raise ValueError('invalid_mode' if allow_missing else 'invalid_arguments')
    selected, missing, noops = [], 0, 0
    for edit in edits:
        _args(edit, ('oldText', 'newText'), ('oldText', 'newText'))
        old, new = _text(edit['oldText']), _text(edit['newText'])
        if not old: raise ValueError('edit_empty_old')
        matches = _occurrences(original, old)
        if not matches and fuzzy: matches = _fuzzy_occurrences(original, old)
        if not matches:
            if allow_missing: missing += 1; continue
            raise ValueError('edit_not_found')
        if len(matches) != 1: raise ValueError('edit_ambiguous')
        low, high = matches[0]
        if original[low:high] == new:
            if not allow_missing: raise ValueError('edit_noop')
            noops += 1
            # No-op matches still participate in overlap validation.
        selected.append((low, high, new))
    selected.sort()
    for left, right in zip(selected, selected[1:]):
        if left[1] > right[0]: raise ValueError('edit_overlap')
    changed = sum(original[a:b] != new for a, b, new in selected)
    result = original
    for low, high, new in reversed(selected): result = result[:low] + new + result[high:]
    _payload(result)
    return result, changed, missing, noops


def _diff(original, result, path):
    # Relative, public spellings only; never leak the absolute workspace root.
    root, parts = _path_parts(path, write=True)
    label = '/'.join(parts)
    return ''.join(difflib.unified_diff(original.splitlines(keepends=True), result.splitlines(keepends=True),
                                       fromfile=label, tofile=label))


def _alarm(signum, frame): raise ValueError('timeout')


def _spawn_log(path, operation):
    if path is None: return
    if not os.path.isabs(path) or '\x00' in path: raise ValueError('invalid_arguments')
    with open(path, 'a', encoding='utf-8') as stream:
        stream.write(f'{os.getpid()} {operation}\n')
        stream.flush()


def main():
    response, code = None, 3
    try:
        argv = sys.argv[1:]
        if argv != ['serve'] and not (len(argv) == 3 and argv[:2] == ['serve', '--spawn-log']):
            raise ValueError('invalid_arguments')
        # One bounded request; extra stdin frames are never executed.
        line = sys.stdin.buffer.readline(131073)
        if len(line) > 131072 or not line.endswith(b'\n'): raise ValueError('invalid_arguments')
        try: request = json.loads(line.decode('utf-8'), parse_constant=lambda x: (_ for _ in ()).throw(ValueError('invalid_arguments')))
        except (UnicodeError, json.JSONDecodeError): raise ValueError('invalid_arguments') from None
        if (type(request) is not dict or type(request.get('v')) is not int or request['v'] != 2
                or request.get('operation') not in ('prepare', 'release', 'inspect', 'invoke')
                or not isinstance(request.get('reservation'), str) or not request['reservation']
                or type(request.get('args')) is not dict): raise ValueError('invalid_arguments')
        try: canonical_json(request)  # Reject values outside the safe JSON domain.
        except (ValueError, UnicodeError, TypeError): raise ValueError('invalid_arguments') from None
        operation = request['operation']
        _spawn_log(argv[2] if len(argv) == 3 else None, operation)
        if operation in ('prepare', 'invoke'): _workspace_root()
        if operation == 'prepare': result = {'prepared': True}
        elif operation == 'release': result = {'released': True}
        elif operation == 'inspect':
            args = request['args']
            target = args.get('target')
            reservation = request['reservation']
            if target not in ('host_prepare', 'host_release') or not isinstance(reservation, str):
                raise ValueError('invalid_arguments')
            result = {'observed': 'known' if reservation.startswith('v24:' + target + ':') else 'absent'}
        else:
            key = request.get('tool')
            handler = HANDLERS.get(key) if isinstance(key, str) else None
            if handler is None: raise ValueError('not_found')
            spec = next(item for item in TOOL_SPECS if item['key'] == key)
            if len(canonical_json(request['args']).encode('utf-8')) > spec['limits']['max_args_bytes']:
                raise ValueError('invalid_arguments')
            # bash owns a shorter command deadline and always cleans its group.
            if key != 'bash':
                signal.signal(signal.SIGALRM, _alarm)
                signal.setitimer(signal.ITIMER_REAL, max(0.1, spec['timeout_ms'] / 1000 - 0.5))
            value = handler(request['args'])
            signal.setitimer(signal.ITIMER_REAL, 0)
            result = {'value': value, 'meta': {}}
        response, code = {'ok': True, 'v': 2, 'result': result}, 0
    except PostCommitError:
        # Non-0/3 is abnormal_exit/unknown in the frozen line-JSON host.
        response, code = {'ok': False, 'v': 2, 'error': {'code': 'io_error', 'message': 'io_error'}}, 1
    except Exception as exc:
        reason = str(exc) if isinstance(exc, ValueError) and str(exc) in _ERRORS else _os_error(exc) if isinstance(exc, OSError) else 'io_error'
        response = {'ok': False, 'v': 2, 'error': {'code': reason, 'message': reason}}
    finally: signal.setitimer(signal.ITIMER_REAL, 0)
    sys.stdout.buffer.write((frame(response) + '\n').encode('utf-8'))
    sys.stdout.buffer.flush()
    return code
# ==== END SHARED CORE ====


def file_search(args):
    allowed = {"pattern", "mode", "regex", "whole_word", "context_lines", "max_results", "count_only", "filter"}
    if type(args) is not dict or set(args) - allowed or not isinstance(args.get("pattern"), str) or not args["pattern"] or "\x00" in args["pattern"]:
        raise ValueError("invalid_arguments")
    mode = args.get("mode", "auto")
    regex = args.get("regex", True)
    whole = args.get("whole_word", False)
    count_only = args.get("count_only", False)
    context = args.get("context_lines", 0)
    maximum = args.get("max_results", 50)
    filters = args.get("filter", {})
    if mode not in ("auto", "path", "content", "both") or any(type(x) is not bool for x in (regex, whole, count_only)) or type(context) is not int or not 0 <= context <= 100 or type(maximum) is not int or not 1 <= maximum <= 1000:
        raise ValueError("invalid_arguments")
    if type(filters) is not dict or set(filters) - {"extensions", "paths", "exclude"} or any(type(v) is not list or any(not isinstance(x, str) or "\x00" in x for x in v) for v in filters.values()):
        raise ValueError("invalid_arguments")
    pattern = args["pattern"]
    auto_glob = mode == "auto" and any(char in pattern for char in "*?[")
    if mode == "auto":
        mode = "path" if auto_glob or "/" in pattern else "content"
    path_glob = mode == "path" and (auto_glob or not regex)
    try:
        expression = pattern if regex else re.escape(pattern)
        matcher = None if path_glob else re.compile(r"\b(?:" + expression + r")\b" if whole else expression)
    except re.error:
        raise ValueError("invalid_arguments") from None
    roots = [_search_root(raw) for raw in filters.get("paths", ["."])]
    paths = sorted({path for root in roots for path in _walk(root)})
    groups = []
    matches = 0
    binary = 0
    extensions = filters.get("extensions", [])
    output_bytes = 0
    for path in paths:
        relative = path.relative_to(_workspace_root()).as_posix()
        if extensions and path.suffix not in extensions:
            continue
        if any(fnmatch.fnmatchcase(relative, pat) or fnmatch.fnmatchcase(path.name, pat) for pat in filters.get("exclude", [])):
            continue
        hits = []
        lines = []
        # In both mode a skipped content file contributes no pathname hit.
        # Check eligibility before admitting/counting any match.
        if mode in ("content", "both"):
            try:
                lines = read_utf8(resolve_path(relative)).splitlines()
            except ValueError as exc:
                if str(exc) == "binary_file":
                    binary += 1
                    continue
                if str(exc) in ("not_utf8", "file_too_large", "io_error"):
                    continue
                raise
        if mode in ("path", "both"):
            matched = fnmatch.fnmatchcase(relative, pattern) if path_glob or not regex else bool(matcher.search(relative))
            if matched and matches < maximum:
                hits.append("  [path]")
                matches += 1
        if mode in ("content", "both"):
            indexes = [i for i, line in enumerate(lines) if matcher.search(line)]
            visible = set()
            for index in indexes:
                if matches >= maximum:
                    break
                matches += 1
                visible.update(range(max(0, index - context), min(len(lines), index + context + 1)))
            hits.extend(("" if count_only else f"  {i + 1}: {lines[i]}") for i in sorted(visible))
        if hits:
            group = relative if count_only else relative + "\n" + "\n".join(hits)
            output_bytes += len(group.encode("utf-8")) + 2
            # Pi read loads the whole spill before paging and caps it at 1 MiB.
            # Reject before spill_write, reserving room for summary/framing.
            if not count_only and output_bytes > 1024 * 1024 - 4096:
                raise ValueError("output_too_large")
            groups.append(group)
        if matches >= maximum:
            break
    summary = f"matches={matches}; files={len(groups)}; skipped_binary={binary}; limit={maximum}; limit_reached={str(matches >= maximum).lower()}"
    text = summary if count_only else summary + ("\n\n" + "\n\n".join(groups) if groups else "")
    return finish_text(text)



def read_file_tool(args):
    _args(args, ('path', 'start_line', 'limit'), ('path',))
    start = args.get('start_line', 1)
    if type(start) is not int or start == 0 or (start < 0 and 'limit' in args):
        raise ValueError('invalid_arguments')
    limit = _integer(args.get('limit', MAX_TEXT_LINES), 1, MAX_TEXT_LINES)
    text, source_spill = read_source(args['path'])
    if start < 0: start = max(1, len(text.splitlines()) + start + 1)
    return finish_text(text, offset=start, limit=limit, coordinate='start_line', source_spill=source_spill)


def get_file_tree_tool(args):
    _args(args, ('path', 'max_depth', 'mode'))
    mode = args.get('mode', 'auto')
    if mode not in ('auto', 'full', 'folders', 'selected'): raise ValueError('invalid_arguments')
    depth = args.get('max_depth', 2 if mode == 'auto' else None)
    if 'max_depth' in args: _integer(depth, 0)
    root = _search_root(args.get('path', '.'))
    workspace = _workspace_root()
    relative = root.relative_to(workspace).as_posix()
    label = '.' if relative == '.' else relative
    output = [label + ('/' if root.is_dir() else '')]
    if mode == 'selected': output.append('[No selection; showing full tree.]')
    size = sum(len(line.encode('utf-8')) + 1 for line in output)
    stack = [(root, '', 0)] if root.is_dir() else []
    while stack:
        path, prefix, level = stack.pop()
        if depth is not None and level >= depth: continue
        entries = [(child, directory) for child, directory in _entries(path) if directory or mode != 'folders']
        # Action stack preserves tree ordering without recursive Python calls.
        actions = []
        for index, (child, directory) in enumerate(entries):
            last = index == len(entries) - 1
            branch = '`-- ' if last else '|-- '
            record = prefix + branch + child.name + ('/' if directory else '')
            actions.append((record, child, directory, prefix + ('    ' if last else '|   ')))
        # Emit lazily so each directory's subtree follows its own label.
        if actions:
            stack.append(('__actions__', actions, level))
        while stack and stack[-1][0] == '__actions__':
            _, pending, parent_level = stack.pop()
            record, child, directory, child_prefix = pending.pop(0)
            if pending: stack.append(('__actions__', pending, parent_level))
            output.append(record)
            size += len(record.encode('utf-8')) + 1
            if size > MAX_FILE_BYTES - 4096: raise ValueError('output_too_large')
            if directory and (depth is None or parent_level + 1 < depth):
                stack.append((child, child_prefix, parent_level + 1))
                break
    return finish_text('\n'.join(output))


def apply_edits_tool(args):
    _args(args, ('path', 'rewrite', 'search', 'replace', 'edits', 'on_missing'))
    for key in ('path', 'rewrite', 'search', 'replace'):
        if key in args: _text(args[key])
    if 'on_missing' in args and args['on_missing'] not in ('error', 'create'):
        raise ValueError('invalid_arguments')
    if 'edits' in args:
        if type(args['edits']) is not list: raise ValueError('invalid_arguments')
        for edit in args['edits']:
            _args(edit, ('oldText', 'newText'), ('oldText', 'newText'))
            _text(edit['oldText']); _text(edit['newText'])
    rewrite = 'rewrite' in args
    search = 'search' in args or 'replace' in args
    edits = 'edits' in args
    if sum((rewrite, search, edits)) > 1: raise ValueError('mode_conflict')
    if (not any((rewrite, search, edits)) or search and not {'search', 'replace'} <= set(args)
            or edits and not args['edits'] or 'on_missing' in args and not rewrite):
        raise ValueError('invalid_mode')
    if not args.get('path'): raise ValueError('invalid_arguments')
    _, original, signature = _write_snapshot(args['path'], create=rewrite and args.get('on_missing') == 'create')
    missing = noops = 0
    if rewrite:
        result = args['rewrite']
        changed = int(result != original or signature is None)
        noops = int(not changed)
    elif search:
        needle = args['search']
        if not needle: raise ValueError('edit_empty_old')
        matches = _occurrences(original, needle)
        if len(matches) > 1: raise ValueError('match_not_unique')
        if not matches:
            result, changed, missing = original, 0, 1
        else:
            low, high = matches[0]
            result = original[:low] + args['replace'] + original[high:]
            changed = int(result != original)
            noops = int(not changed)
    else:
        result, changed, missing, noops = plan_edits(original, args['edits'], allow_missing=True)
    _payload(result)
    status = 'partial' if changed and missing else 'success' if changed else 'failed' if missing else 'no_change'
    summary = f'status={status}; applied={changed}; missing={missing}; no_op={noops}'
    diff = _diff(original, result, args['path']) if changed else ''
    output = finish_text(summary + ('\n' + diff if diff else ''), extra={'status': status})
    if changed: atomic_mutation(args['path'], result, signature)
    return output


HANDLERS = {'read_file': read_file_tool, 'file_search': file_search,
            'get_file_tree': get_file_tree_tool, 'apply_edits': apply_edits_tool}

if __name__ == '__main__':
    raise SystemExit(main())
