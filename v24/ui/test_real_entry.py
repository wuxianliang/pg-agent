#!/usr/bin/env python3
"""Offline M5 real-entry contracts; actual adapter, local transport, no sockets."""
from __future__ import annotations
import ast
import asyncio
import contextlib
import dataclasses
import io
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import uuid
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from v24.host.deepseek import DeepSeekAdapter, ENDPOINT, MODEL
from v24.ui import app, catalog, provider, real
from v24.ui.control import AgentRuntime, DEFAULT_BUDGET
from v24.ui.sessions import SessionStore


def require(value, message):
    if not value:
        raise AssertionError(message)


def output(call):
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        code = call()
    return code, stream.getvalue().strip()


def startup_contracts():
    absent = {k: v for k, v in os.environ.items() if not k.startswith(('DEEPSEEK_', 'OPENAI_'))}
    with patch.dict(os.environ, absent, clear=True), patch.object(provider, 'DeepSeekAdapter', side_effect=AssertionError('constructed without key')), patch.object(app, 'open_env', side_effect=AssertionError('opened env')), patch.object(app, 'acquire_lock', side_effect=AssertionError('locked')):
        require(output(lambda: real.main([])) == (0, 'not_requested'), 'no flag contract')
        require(output(lambda: real.main(['--real-provider-smoke'])) == (2, 'credentials_absent'), 'CLI missing key')
        with patch.dict(os.environ, V24_UI_MODE='real'):
            try:
                app.Backend(lambda *a: None)
            except RuntimeError as exc:
                require(str(exc) == 'credentials_absent', 'UI missing key reason')
            else:
                raise AssertionError('UI accepted missing key')
    for env, expected in [({'DEEPSEEK_API_KEY': 'synthetic-primary', 'OPENAI_API_KEY': 'synthetic-fallback'}, 'synthetic-primary'), ({'OPENAI_API_KEY': 'synthetic-fallback'}, 'synthetic-fallback')]:
        with patch.dict(os.environ, dict(absent, **env), clear=True):
            adapter = real.create_real_adapter(transport=object())
            require(type(adapter) is DeepSeekAdapter and adapter._api_key == expected, 'precedence/adapter')
            require(adapter.timeout_s == 120 and adapter.body_byte_ceiling == 16384, 'real adapter limits')
    with patch.dict(os.environ, DEEPSEEK_API_KEY='synthetic-primary', V24_UI_MODE='real'), patch.object(DeepSeekAdapter, 'preflight', return_value={'class': 'secret-arbitrary-payload'}), patch.object(real, '_run_live', side_effect=AssertionError('live entry reached')), patch.object(app, 'open_env', side_effect=AssertionError('opened env')), patch.object(app, 'acquire_lock', side_effect=AssertionError('locked')):
        require(output(lambda: real.main(['--real-provider-smoke'])) == (1, 'preflight_failed'), 'CLI preflight rejection')
        try:
            app.Backend(lambda *a: None)
        except RuntimeError as exc:
            require(str(exc) == 'preflight_failed', 'UI preflight rejection')
        else:
            raise AssertionError('UI accepted failed preflight')
    with scratch_directory('offline-invalid-toolset-') as directory:
        scratch = Path(directory).resolve()
        data = scratch / 'not-created'
        with patch.dict(os.environ, V24_UI_MODE='real', V24_UI_WORKSPACE_ROOT=str(scratch), V24_UI_TOOLSET='invalid'), \
             patch.object(provider, 'create_real_adapter', return_value=object()), \
             patch.object(app, 'open_env', side_effect=AssertionError('opened env')), \
             patch.object(app, 'acquire_lock', side_effect=AssertionError('locked')):
            try:
                app.Backend(lambda *a: None, env=SimpleNamespace(data_dir=data))
            except RuntimeError as exc:
                require(str(exc) == 'invalid_toolset', 'invalid toolset reason')
            else:
                raise AssertionError('invalid toolset accepted')
            require(not data.exists(), 'invalid toolset created data directory')
    # Freeze the verified default prompt bytes. This must not depend on what a
    # later HEAD contains, otherwise a commit turns the comparison into a no-op.
    prompt = catalog.build_system_prompt('skills', 'history')
    require(hashlib.sha256(prompt.encode('utf-8')).hexdigest()
            == '80706a339fc47427b78f2933e71e49f53254c4c89c46eef473e91cabcfbb037a', 'fake prompt bytes changed')
    require('256 tokens/reply' in catalog.build_system_prompt('skills', 'history', 256), 'prompt cap override')
    require('256 tokens/reply' in app.build_system_prompt('skills', 'history', 256), 'app prompt cap override')
    require('512 tokens/reply' in app.build_system_prompt('skills', 'history'), 'app default prompt cap')
    real_tree = ast.parse((ROOT / 'v24/ui/real.py').read_text())
    cap_calls = [n for n in ast.walk(real_tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and n.func.attr == 'build_system_prompt']
    require(any(len(n.args) >= 3 and isinstance(n.args[2], ast.Attribute)
                and n.args[2].attr == 'completion_cap' for n in cap_calls),
            'CLI prompt cap is not sourced from limits')
    require(catalog.MAX_SAFE_ARGS_BYTES == 128, 'safe args measurement changed')
    require(catalog.LEGACY_UI_LIMITS.body_byte_ceiling == 8000 and catalog.REAL_UI_LIMITS.body_byte_ceiling == 16384, 'profile body limits')
    require(dataclasses.replace(catalog.REAL_UI_LIMITS, body_byte_ceiling=8000) == catalog.LEGACY_UI_LIMITS, 'real profile changed frozen legacy limits')
    require(catalog.REAL_UI_LIMITS.completion_cap == catalog.LEGACY_UI_LIMITS.completion_cap == 512, 'completion cap changed')
    require(catalog.REAL_UI_LIMITS.timeout_s == catalog.LEGACY_UI_LIMITS.timeout_s == 120, 'timeout changed')
    require(catalog.REAL_UI_LIMITS.worker_lease_ms == catalog.LEGACY_UI_LIMITS.worker_lease_ms == 30000, 'lease changed')
    require(catalog.REAL_UI_LIMITS.run_budget() == DEFAULT_BUDGET, 'budget changed')
    copied = catalog.REAL_UI_LIMITS.run_budget(); copied['tokens'] = 0
    require(catalog.REAL_UI_LIMITS.run_budget()['tokens'] == 20000, 'mutable budget escaped')
    require('request body <= 8000 bytes' in prompt
            and 'tool-call args <= 128 bytes' in prompt, 'prompt limit contract')
    require('request body <= 1234 bytes' in catalog.build_system_prompt('skills', 'history', 256, 1234),
            'prompt ceiling parameter')
    require(catalog.limits_contract(completion_cap=256, body_byte_ceiling=1234)
            == '256 tokens/reply including reasoning; request body <= 1234 bytes; '
               'tool-call args <= 128 bytes', 'limit contract text')
    require('tool-call args <= 512 bytes' in catalog.limits_contract(max_safe_args_bytes=512),
            'measured safe args text')
    require('request body <= 1234 bytes' in app.build_system_prompt('skills', 'history', None, 1234),
            'app ceiling override')
    real_text = (ROOT / 'v24/ui/real.py').read_text()
    require(real_text.count('test "$(cat result.txt)" = WI2_EXEC_MARKER') == 1, 'exec11 command duplicated')
    require(real.EXEC11_COMMAND in real.EXEC11_PROMPT and 'verbatim' in real.EXEC11_PROMPT
            and 'no echo' in real.EXEC11_PROMPT and 'no chaining' in real.EXEC11_PROMPT,
            'exec11 prompt is not verbatim')
    for mutation in ({'body_byte_ceiling': 0}, {'completion_cap': 513},
                     {'timeout_s': 0}, {'timeout_s': 240}, {'worker_lease_ms': 29999},
                     {'budget_items': tuple((k, 0) if k == 'steps' else (k, v)
                                             for k, v in catalog.LEGACY_UI_LIMITS.budget_items)},
                     {'budget_items': catalog.LEGACY_UI_LIMITS.budget_items + (('steps', 1),)},
                     {'budget_items': (('steps',),) + catalog.LEGACY_UI_LIMITS.budget_items[1:]},
                     {'budget_items': (['steps', 24],) + catalog.LEGACY_UI_LIMITS.budget_items[1:]}):
        try:
            dataclasses.replace(catalog.LEGACY_UI_LIMITS, **mutation)
        except ValueError:
            pass
        else:
            raise AssertionError(('invalid limits accepted', mutation))
    from v24.ui import control
    env = SimpleNamespace(admin_dsn='admin-source', service_dsn='service-source')
    class Connection:
        closed = False
        def close(self):
            self.closed = True
    first = Connection()
    with patch.object(control, 'connect', side_effect=[first, RuntimeError('second connection fails')]):
        try:
            AgentRuntime(env)
        except RuntimeError:
            pass
        else:
            raise AssertionError('second connect failure ignored')
    require(first.closed, 'partial connection leaked')
    connections = [Connection(), Connection()]
    with patch.object(control, 'connect', side_effect=connections), patch.object(control, 'HostDB'), patch.object(control.HostJournal, 'open', side_effect=RuntimeError('journal fails')):
        env.journal_path = Path('/unused')
        try:
            AgentRuntime(env)
        except RuntimeError:
            pass
        else:
            raise AssertionError('journal failure ignored')
    require(all(c.closed for c in connections), 'journal startup failure leaked connections')
    print('[case] startup: opt-in/key/preflight before resources; precedence; sanitized errors; partial resources closed; baseline prompt/limits unchanged')


class LocalTransport:
    def __init__(self, *, finish='stop'):
        self.runtime = None
        self.finish = finish
        self.calls = []

    def post(self, url, body, headers, deadline):
        require(self.runtime is not None, 'transport has no runtime')
        self.runtime.db.assert_all_idle()
        request = json.loads(body)
        require(url == ENDPOINT and request['model'] == MODEL and request['stream'] is False, 'wire contract')
        require('tool_choice' not in request and request['max_tokens'] == 512, 'cap/tool choice')
        require(headers['Authorization'] == 'Bearer synthetic-entry-key', 'key not captured before helper sanitization')
        self.calls.append(request)
        reply = {'id': 'offline-reply', 'model': MODEL,
            'choices': [{'finish_reason': self.finish, 'message': {'role': 'assistant', 'content': 'offline done', 'reasoning_content': 'done'}}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 4}}
        return 200, json.dumps(reply).encode()


def scratch_directory(prefix):
    # Offline contracts must not pollute the retained evidence root.
    return tempfile.TemporaryDirectory(prefix=prefix)


def runtime_contracts():
    from v24.ui import control
    from v24.s1.setup_db import setup_db
    from v24.ui.env import UiEnv
    from psycopg2.extensions import parse_dsn
    with scratch_directory('offline-entry-') as directory:
        parent = Path(directory).resolve()
        for finish in ('stop', 'length'):
            transport = LocalTransport(finish=finish)
            adapter = real.create_real_adapter(catalog.LEGACY_UI_LIMITS, transport=transport)
            runtimes = []
            def runtime(*args, **kwargs):
                rt = AgentRuntime(*args, **kwargs)
                runtimes.append(rt)
                transport.runtime = rt
                require(not any(k.startswith(('PG', 'DEEPSEEK_', 'OPENAI_')) for k in os.environ), 'helper environment not sanitized')
                return rt
            args = SimpleNamespace(evidence_dir=parent, profile='legacy', scenario='short')
            with patch.object(control, 'AgentRuntime', side_effect=runtime), patch.object(app, 'FakeAppAdapter', side_effect=AssertionError('fake constructed')), patch('v24.ui.fake.ScriptedUiAdapter.build', side_effect=AssertionError('scripted build')):
                code, line = output(lambda: real._run_live(args, adapter, catalog.LEGACY_UI_LIMITS))
            require(code == (0 if finish == 'stop' else 1), ('CLI terminal exit', code, line))
            require(len(transport.calls) == 1, 'unexpected transport count')
            rt = runtimes[0]
            journal = rt.env.journal_path
            require(journal.is_file() and journal.stat().st_mode & 0o777 == 0o600, 'private journal not retained')
            require(rt.db.control.closed and rt.db.service.closed, 'CLI connections not closed')
            summary = json.loads((journal.parent / 'summary.json').read_text())
            require(summary['status'] == ('completed' if finish == 'stop' else 'blocked_unknown'), 'terminal summary')
            raw = journal.read_text()
            require('synthetic-entry-key' not in raw and 'Authorization' not in raw and 'Bearer ' not in raw, 'journal leaked key/header')
            records = [json.loads(line) for line in raw.splitlines()]
            finished = [r for r in records if r['event_type'] == 'dispatch_finished' and r.get('run_id') == summary['run_id']]
            require(len(finished) == 1, 'dispatch finish count')
            require(('finish_length' in json.dumps(finished[0]['payload']['mapping'])) == (finish == 'length'), 'length classification')
            print(f'[case] CLI {finish}: actual adapter/transport; both connections IDLE; one dispatch; private journal retained; sockets=0')
        require(os.environ.get('DEEPSEEK_API_KEY') == 'synthetic-entry-key', 'CLI environment not restored')
        # Use the exact Backend constructor against a separate disposable DB.
        private_ui_server = parent / 'ui-server'
        private_ui_server.mkdir(mode=0o700)
        transport = LocalTransport()
        adapter = real.create_real_adapter(transport=transport)
        events = []
        with real._private_fixture_server(private_ui_server), setup_db() as fixture:
            data = parent / 'ui'; data.mkdir(mode=0o700)
            for name in ('workspace', 'spawn', 'spill'):
                (data / name).mkdir()
            params = parse_dsn(fixture.role_dsn('admin'))
            env = UiEnv(repo_root=ROOT, data_dir=data, db_name=fixture.name,
                socket_dir=Path(params['host']), port=int(params['port']),
                maintenance_dsn=fixture.maintenance_dsn,
                admin_dsn=fixture.role_dsn('admin'), service_dsn=fixture.role_dsn('service'),
                journal_path=data/'journal.jsonl', spawn_dir=data/'spawn',
                workspace_root=data/'workspace', spill_root=data/'spill',
                skills_root=ROOT/'v24/ui/skills')
            nonempty = data / 'nonempty'; nonempty.mkdir()
            (nonempty / 'keep.txt').write_text('occupied')
            with patch.object(provider, 'create_real_adapter', return_value=adapter), \
                 patch.object(app, 'FakeAppAdapter', side_effect=AssertionError('fake constructed')), \
                 patch.object(app, 'open_env', side_effect=AssertionError('opened env')), \
                 patch.object(app, 'acquire_lock', side_effect=AssertionError('locked')):
                for value, reason in ((None, 'workspace_required'),
                                      (str(nonempty), 'workspace_not_empty'),
                                      (str(ROOT / 'v24/ui'), 'workspace_invalid')):
                    values = dict(V24_UI_MODE='real', V24_SPILL_ROOT=str(env.spill_root),
                                  V24_SKILLS_ROOT=str(env.skills_root))
                    if value is not None:
                        values['V24_UI_WORKSPACE_ROOT'] = value
                    with patch.dict(os.environ, values):
                        os.environ.pop('V24_UI_WORKSPACE_ROOT', None)
                        if value is not None:
                            os.environ['V24_UI_WORKSPACE_ROOT'] = value
                        os.environ.pop('V24_UI_TOOLSET', None)
                        try:
                            app.Backend(lambda *a: None, env=env, check_environment=False)
                        except RuntimeError as exc:
                            require(str(exc) == reason, ('real scratch reason', value, reason, str(exc)))
                        else:
                            raise AssertionError(('real scratch accepted', value))
            with patch.dict(os.environ, V24_UI_MODE='real', V24_UI_WORKSPACE_ROOT=str(env.workspace_root), V24_SPILL_ROOT=str(env.spill_root), V24_SKILLS_ROOT=str(env.skills_root)), patch.object(provider, 'create_real_adapter', return_value=adapter), patch.object(app, 'FakeAppAdapter', side_effect=AssertionError('fake constructed')):
                os.environ.pop('V24_UI_TOOLSET', None)
                backend = app.Backend(lambda sid, event: events.append(event), env=env, check_environment=False)
                transport.runtime = backend.rt
                require(backend.toolset == 'read' and backend.completion_cap == 512, 'real UI safe defaults')
                require(backend.rt.limits == catalog.REAL_UI_LIMITS, 'real UI runtime profile mismatch')
                require(backend.rt.adapter.body_byte_ceiling == catalog.REAL_UI_LIMITS.body_byte_ceiling, 'real UI adapter profile mismatch')
                try:
                    backend.new('real-ui', threading.Event())
                    row = backend.store.get(backend.states['real-ui'].conversation_id)
                    require(row['mode'] == 'real' and row['limits_digest'] == backend._limits_digest(), 'real conversation profile not persisted')
                    require(any(str(e.value).startswith('REAL · db=') for e in events), 'real footer')
                    require(any('max_out=512' in str(e.value) for e in events), 'real footer cap source')
                    require(any('request body <= 16384 bytes' in str(e.value)
                                and 'tool-call args <= 128 bytes' in str(e.value) for e in events),
                            'real footer limit contract')
                    backend.command('real-ui', 'short offline answer')
                    for _ in range(16):
                        if not backend.states['real-ui'].busy:
                            break
                        backend.tick()
                    state = backend.states['real-ui']
                    stored = SessionStore(data).get(state.conversation_id)
                    require(stored['mode'] == 'real' and stored['limits_digest'] == backend._limits_digest(), 'real stored profile')
                    require(all(b['mode'] == 'real' and b['limits_digest'] == backend._limits_digest()
                                for b in stored['bindings']), 'real binding profile not persisted')
                    require(backend.run(state.run_id)['status'] == 'completed' and len(transport.calls) == 1, 'UI real execution')
                    before = backend.rt.run_state(state.run_id)
                    backend.answer('real-ui', state.run_id, 'unreachable', 'answer')
                    require(backend.rt.run_state(state.run_id) == before, 'real respond sent')
                    backend.close_conversation(state)
                finally:
                    backend.close()
            require(env.journal_path.exists(), 'UI journal deleted')
    print('[case] UI: shared actual adapter; fake never constructed; real footer; respond disabled; journal retained')


class WorkflowTransport:
    """Provider-shaped replies through the unchanged actual adapter/runtime."""
    def __init__(self, scenario, expected, variant='normal'):
        self.scenario, self.expected, self.variant = scenario, expected, variant
        self.calls = []

    def post(self, url, body, headers, deadline):
        request = json.loads(body)
        self.calls.append(request)
        require(request['max_tokens'] == 512, 'actual per-cause cap (SQL carries start input)')
        require('tool_choice' not in request, 'forced tool choice')
        steps = []
        if self.scenario in ('write10', 'exec11', 'skill'):
            skill = 'repo-recon' if self.scenario == 'skill' else 'surgical-edit'
            steps.append(('read', {'path': f'.v24/skills/{skill}/SKILL.md'}))
        if self.expected:
            steps.append(('write', self.expected))
        if self.scenario == 'exec11':
            steps.append(('bash', {'command': 'test "$(cat result.txt)" = WI2_EXEC_MARKER'}))
        if self.scenario in ('write10', 'exec11'):
            steps.append(('read', {'path': 'result.txt'}))
        if self.variant == 'write_before_skill':
            steps[0], steps[1] = steps[1], steps[0]
        if self.variant == 'bash_after_read':
            steps[2], steps[3] = steps[3], steps[2]
        index = len(self.calls) - 1
        message = {'role': 'assistant', 'content': '', 'reasoning_content': ''}
        finish = 'stop'
        if self.variant == 'length':
            # Even parseable residual arguments must never execute on length.
            finish = 'length'
            steps = [('write', self.expected)]
        if index < len(steps):
            key, params = steps[index]
            if self.variant == 'target_missed':
                params = dict(params, content='wrong')
            if self.variant == 'guard' and key == 'write':
                params = dict(params, content='wrong')
            name = next(t['function']['name'] for t in request['tools'] if t['function']['name'].endswith(key))
            message['tool_calls'] = [{'id': f'offline-{index}', 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(params, ensure_ascii=False)}}]
            if finish != 'length': finish = 'tool_calls'
        else:
            message['content'] = 'done'
        reply = {'id': 'offline-workflow', 'model': MODEL, 'choices': [{'finish_reason': finish, 'message': message}],
                 'usage': {'prompt_tokens': 20, 'completion_tokens': 512 if finish == 'length' else 8}}
        return 200, json.dumps(reply).encode()


def measurement_contracts():
    from v24.host.deepseek import AdapterFailure
    from v24.ui.audit_m5 import runtime_source_hashes
    require(runtime_source_hashes() == real._source_hashes(), 'audit runtime source globs diverged')
    for limits, accepted, rejected in ((catalog.LEGACY_UI_LIMITS, (8000,), (8001,)),
                                       (catalog.REAL_UI_LIMITS, (8000, 8001, 8048, 8192, 12000, 16384), (16385,))):
        adapter = real.create_real_adapter(limits, transport=object())
        base = len(real._json_bytes({'model': MODEL, 'messages': [{'role': 'user', 'content': ''}], 'stream': False}))
        def effect_for(size):
            return {'request': {'cause': 'start', 'reserve': {'tokens': 4096},
                                'input': {'max_output_tokens': 512, 'messages': [{'role': 'user', 'content': 'x' * (size - base)}]}}}
        for size in accepted:
            built = adapter.build(effect_for(size), [], [])
            require(len(real._json_bytes({key: value for key, value in built.body.items() if key != 'max_tokens'})) == size, ('canonical body size', size))
            require(built.max_tokens == 512 and built.reserve_tokens == 4096, 'body fallback changed cap/reserve')
        for size in rejected:
            try:
                adapter.build(effect_for(size), [], [])
            except AdapterFailure as exc:
                require(str(exc) == 'body_too_large', ('body rejection', size, str(exc)))
            else:
                raise AssertionError(('body accepted above profile ceiling', size))
    require(catalog.REAL_UI_LIMITS.body_byte_ceiling == 16384 and catalog.LEGACY_UI_LIMITS.body_byte_ceiling == 8000, 'profile admission changed')
    for family in ('ascii', 'cjk', 'escape'):
        for target in (64, 128, 256, 384, 512, 768, 1024, 1536, 2048, 3072, 4096):
            content = real._probe_content(target, family)
            require(len(real._json_bytes({'path': 'result.txt', 'content': content, 'append': False})) == target, 'target canonical bytes')
            if family == 'escape':
                require('\n' in content and not any(ch in content for ch in '"\\\t'),
                        'escape probe is not newline-only')
    for secret in ('synthetic-primary', 'synthetic-fallback'):
        try:
            real._assert_safe({'id': secret}, ('synthetic-primary', 'synthetic-fallback'))
        except RuntimeError as exc:
            require(str(exc) == 'receipt_privacy_failed', 'privacy reason')
        else:
            raise AssertionError('receipt key escaped')
    cases = [('probe', 'normal'), ('probe', 'target_missed'), ('probe', 'length'),
             ('probe', 'body'), ('write10', 'normal'), ('exec11', 'normal'), ('skill', 'normal'),
             ('write10', 'guard'), ('write10', 'write_before_skill'), ('exec11', 'bash_after_read'),
             ('write10', 'missing_parent')]
    with scratch_directory('offline-measurements-') as directory:
        parent = Path(directory).resolve()
        for scenario, variant in cases:
            target = 4096 if variant == 'body' else 128
            expected = None
            if scenario == 'probe':
                expected = {'path': 'result.txt', 'content': real._probe_content(target, 'escape'), 'append': False}
            elif scenario in ('write10', 'exec11'):
                expected = {'path': 'result.txt', 'content': 'WI2_WRITE_MARKER' if scenario == 'write10' else 'WI2_EXEC_MARKER'}
            transport = WorkflowTransport(scenario, expected, variant)
            # Workflows run on the current profile: five-to-six real rounds
            # exceed the legacy 8000 admission bound. The explicit body-refusal
            # case stays on legacy so the adapter refusal path is still proved.
            legacy = variant == 'body'
            limits = catalog.LEGACY_UI_LIMITS if legacy else catalog.REAL_UI_LIMITS
            adapter = real.create_real_adapter(limits, transport=transport)
            args = SimpleNamespace(evidence_dir=parent, profile='legacy' if legacy else 'current',
                                   scenario=scenario,
                                   target_args_bytes=target if scenario == 'probe' else None, content_class='escape')
            before = set(parent.iterdir())
            original_effects = real._effects
            def without_write_parent(rt, run_id):
                effects = original_effects(rt, run_id)
                return [dict(e, parent_effect_id=None) if e.get('request', {}).get('key') == 'write' else e
                        for e in effects]
            with contextlib.ExitStack() as stack:
                if variant == 'missing_parent':
                    stack.enter_context(patch.object(real, '_effects', side_effect=without_write_parent))
                code, line = output(lambda: real._run_live(args, adapter, limits))
            child, = set(parent.iterdir()) - before
            require((child/'summary.json').is_file(), ('missing receipt', scenario, variant, line, child.name))
            receipt = json.loads((child/'summary.json').read_text())
            require(receipt['source_unchanged'] and receipt['connections_idle'], 'source/idle')
            require(receipt['pin_count'] == (10 if scenario in ('probe', 'write10') else 11), 'full pins')
            require(all(m['sql_reserve_tokens'] == 4096 for m in receipt['models']), 'SQL reserve')
            require('synthetic-entry-key' not in (child/'journal.jsonl').read_text(), 'journal key leak')
            if variant == 'normal':
                require(code == 0 and receipt['contract_passed'], ('workflow contract', scenario, receipt['checks'], receipt['builds']))
                require(len(transport.calls) == (1 if scenario == 'probe' else {'write10': 4, 'exec11': 5, 'skill': 2}[scenario]), 'workflow send count')
                if scenario == 'probe':
                    require(receipt['status'] == 'cancelled' and receipt['measurement_reason'] == 'measurement_complete', 'controlled cancellation')
                    dispatched = [m for m in receipt['models'] if m['dispatch_count'] == 1]
                    require(len(dispatched) == 1 and dispatched[0]['durable_status'] == 'succeeded', 'probe dispatched model')
                    require(dispatched[0]['tool_args'][0]['actual_complete_args_bytes'] == target, 'actual complete args')
                    continuations = [m for m in receipt['models'] if m['dispatch_count'] == 0]
                    require(len(continuations) == 1 and continuations[0]['durable_status'] == 'cancelled'
                            and continuations[0]['tool_args'] == [], 'actual cancelled continuation receipt')
                    require(receipt['target_args_bytes'] == target and receipt['content_class'] == 'escape', 'probe dimensions missing')
                else:
                    require('target_args_bytes' not in receipt and 'content_class' not in receipt, 'probe dimensions leaked into workflow')
            elif variant == 'bash_after_read':
                require(code == 1 and not receipt['contract_passed'], 'bash after read accepted')
                require(receipt['checks']['bash_executed'] and receipt['checks']['durable_final'], 'negative bash workflow incomplete')
                require(not receipt['checks']['readback_after_bash'] and not receipt['checks']['durable_readback'],
                        'early read counted as post-bash proof')
            elif variant == 'missing_parent':
                require(code == 1 and not receipt['contract_passed'], 'missing write parent accepted')
                require(receipt['checks']['skill_before_write'] and receipt['checks']['durable_final'], 'missing parent workflow incomplete')
                require(not receipt['checks']['skill_continuation'], 'missing parent used fallback continuation')
            elif variant == 'target_missed':
                require(code == 1 and receipt['measurement_reason'] == 'target_missed' and not receipt['tools'][0]['dispatch_count'], 'target miss executed')
            elif variant == 'length':
                require(code == 1 and receipt['finish_length_contract'] is True and not receipt['tools'], 'residual args executed')
            elif variant == 'write_before_skill':
                require(code == 1 and not receipt['contract_passed'], 'write before skill accepted')
                require(receipt['checks']['full_skill_read'] and receipt['checks']['durable_final'], 'negative workflow incomplete')
                require(not receipt['checks']['skill_before_write'] and not receipt['checks']['skill_continuation'],
                        'late skill read counted as write prerequisite')
            elif variant == 'guard':
                require(code == 1 and receipt['measurement_reason'] == 'tool_failure' and receipt['guard_rejections'], 'guard not stopped')
                require(any(r['key'] == 'write' and r['predicate'] == 'content_mismatch'
                            and len(r['effect_id']) == 36 for r in receipt['guard_rejections']), 'guard predicate lost')
                require(any(t['error_code'] == 'measurement_guard_rejected' and t['durable_status'] == 'failed' for t in receipt['tools']), 'guard handler contract')
                require(receipt['actual_file_bytes'] is None and len(transport.calls) == 2, 'guard side effect/continuation')
            elif variant == 'body':
                require(code == 1 and not transport.calls and receipt['builds'][0]['failure'] == 'body_too_large', 'body rejection sent')
            print(f'[case] measurement {scenario}/{variant}: actual adapter/runtime; full pins; safe receipt; sends={len(transport.calls)}; sockets=0')


def binding_profile_contracts():
    """Construct the real-mode Backend with no DB/provider, preserving legacy files."""
    from v24.ui.env import UiEnv
    with scratch_directory('offline-binding-profile-') as directory:
        parent = Path(directory).resolve()
        data, workspace = parent / 'data', parent / 'workspace'
        data.mkdir()
        workspace.mkdir()
        env = UiEnv(ROOT, data, 'unused', parent, 1, 'unused', 'unused', 'unused',
                    data / 'journal', data / 'spawn', workspace, data / 'spill', ROOT / 'v24/ui/skills')
        runtime = Mock()
        runtime.limits = catalog.REAL_UI_LIMITS
        runtime.discoveries = {}
        runtime.run_state.return_value = {'run': {'status': 'running'}}
        runtime.rehydrate.side_effect = AssertionError('incompatible binding reached runtime')
        events = []
        with patch.dict(os.environ, V24_UI_MODE='real', V24_UI_TOOLSET='read', V24_UI_WORKSPACE_ROOT=str(workspace)), \
             patch.object(provider, 'create_real_adapter', return_value=object()), \
             patch.object(app, '_real_scratch_workspace', return_value=workspace), \
             patch.object(app, 'AgentRuntime', return_value=runtime):
            backend = app.Backend(lambda sid, event: events.append(event), env=env, check_environment=False)
            try:
                for metadata in ({'mode': 'fake'}, {}, {'mode': 'real', 'limits_digest': '0' * 64}):
                    scope, run = str(uuid.uuid4()), str(uuid.uuid4())
                    row, token = backend.store.new_conversation()
                    binding = backend.store.bind(row['conversation_id'], scope, run, realm='test',
                        workspace_root=workspace, toolset='read', catalog_digest=backend.digest('test'), **metadata)
                    raw = backend.store.path.read_bytes()
                    loaded = SessionStore(data).get(row['conversation_id'])
                    require(loaded['bindings'][0] == binding and backend.store.path.read_bytes() == raw,
                            'loading rewrote legacy metadata')
                    try:
                        backend._rehydrate(binding)
                    except RuntimeError as exc:
                        require(str(exc) == 'catalog_changed', 'mode/profile rejection reason')
                    else:
                        raise AssertionError('real rehydrate accepted incompatible binding')
                    state = app.ThreadState('profile', '', '', '')
                    backend.resume(state, run + ' ' + token)
                    require(state.readonly and not state.busy, 'real resume activated incompatible binding')
                    require(any('catalog_changed; replay only' in str(e.value) for e in events), 'readonly warning missing')
                    runtime.rehydrate.assert_not_called()
                    runtime.adapter.send.assert_not_called()
                    # Fake permits absent legacy mode; explicit real mode is refused.
                    backend.mode = 'fake'
                    require(backend._binding_profile_matches({}), 'legacy fake binding rejected')
                    require(not backend._binding_profile_matches({'mode': 'real'}), 'real binding accepted as fake')
                    backend.mode = 'real'
                require(backend._binding_profile_matches({'mode': 'real', 'limits_digest': backend._limits_digest()}),
                        'matching real profile rejected')
                original = backend._limits_digest()
                runtime.limits = dataclasses.replace(catalog.REAL_UI_LIMITS, completion_cap=256)
                require(backend._limits_digest() != original, 'limits change did not change digest')
            finally:
                backend.close()
    print('[case] mode/profile bindings: real rejects fake/legacy/changed limits; fake legacy readable; no provider/DB')


async def banner_contract():
    with patch.dict(os.environ, {'V24_UI_MODE': 'real'}, clear=True):
        try:
            await app._submit('new', 'missing-key', threading.Event())
        except RuntimeError as exc:
            require(str(exc) == 'credentials_absent', 'page error lost reason')
        else:
            raise AssertionError('missing key accepted by hub')
        finally:
            await app.shutdown()
    print('[case] hub: credentials_absent page error survives startup; service shutdown clean')


def persistent_metadata():
    # Read-only: this catches subsequent accidental starts/stops or filesystem
    # writes. It cannot retrospectively establish pre-incident logical state.
    result = {}
    for name in ('.pgdata', '.uidata'):
        root = ROOT / name
        if root.exists():
            for path in (root, *root.rglob('*')):
                state = path.lstat()
                result[str(path)] = (state.st_size, state.st_mtime_ns, state.st_ino, state.st_mode)
    return result


def fail_closed_contracts():
    from v24.s1 import setup_db as fixtures
    actual_popen = subprocess.Popen
    launches = []
    def broken_bootstrap(command, **kwargs):
        launches.append(command)
        require('-I' in command and 'sitecustomize' not in ' '.join(command), 'helper depends on sitecustomize')
        require(not any(k.startswith(('PG', 'DEEPSEEK_', 'OPENAI_')) for k in os.environ), 'bootstrap inherited credentials/libpq')
        return actual_popen([sys.executable, '-I', '-c', "raise ImportError('injected_bootstrap_failure')"], **kwargs)
    with scratch_directory('offline-bootstrap-') as directory:
        parent = Path(directory).resolve()
        args = SimpleNamespace(evidence_dir=parent, scenario='short', profile='legacy')
        transport = LocalTransport()
        adapter = real.create_real_adapter(catalog.LEGACY_UI_LIMITS, transport=transport)
        with patch.object(real.subprocess, 'Popen', side_effect=broken_bootstrap), patch.object(fixtures, 'setup_db') as setup:
            code, line = output(lambda: real._run_live(args, adapter, catalog.LEGACY_UI_LIMITS))
        require(code == 1 and 'status=entry_failed' in line and 'journal=absent' in line, 'bootstrap failure did not fail closed')
        setup.assert_not_called()
        require(len(launches) == 1 and not transport.calls, 'bootstrap failure fell back or dispatched')
        require(fixtures._setup_process is None and fixtures._setup_endpoint is None, 'failed helper not reaped/unregistered')
        require(not list(parent.glob('*/pgdata')), 'failed bootstrap created a cluster')
        # A repository-internal evidence directory outside the ignored
        # prompt-exports root must fail before mkdir, helper, DB, or provider IO.
        bad = SimpleNamespace(evidence_dir=ROOT / 'v24/ui', scenario='short', profile='legacy')
        code, line = output(lambda: real._run_live(bad, adapter, catalog.LEGACY_UI_LIMITS))
        require(code == 1 and 'status=entry_failed' in line and 'evidence=absent' in line,
                ('non-ignored evidence dir accepted', line))
        require(not transport.calls and not (ROOT / 'v24/ui/entry-error.json').exists(),
                'non-ignored evidence dir wrote or dispatched')
        with patch.object(fixtures, '_setup_process', object()), patch.object(real.subprocess, 'Popen') as launch:
            try:
                with real._private_fixture_server(parent):
                    raise AssertionError('foreign helper accepted')
            except RuntimeError as exc:
                require(str(exc) == 'private_helper_conflict', 'wrong helper conflict')
            launch.assert_not_called()
        occupied = parent / 'pgdata'; occupied.mkdir()
        with patch('pgembed.get_server') as server:
            try:
                real._private_db_helper(occupied)
            except RuntimeError as exc:
                require(str(exc) == 'private_pgdata_invalid', 'wrong invalid path reason')
            else:
                raise AssertionError('existing pgdata accepted')
            server.assert_not_called()
    print('[case] bootstrap: real child import failure; one launch; no fallback/setup_db/provider; helper reaped; existing paths/helpers refused')


def main():
    before = persistent_metadata()
    with patch.dict(os.environ, DEEPSEEK_API_KEY='synthetic-entry-key', OPENAI_API_KEY=''), patch.object(socket, 'socket', side_effect=AssertionError('network socket forbidden')):
        startup_contracts()
        binding_profile_contracts()
        fail_closed_contracts()
        runtime_contracts()
        measurement_contracts()
    asyncio.run(banner_contract())
    require(persistent_metadata() == before, 'persistent PGDATA/UI metadata changed')
    print('[case] persistent state: read-only before/after metadata identical; no root PGDATA or UI files written')
    print('[passed] M5 real entry offline contracts; WI2=workflows/probes/receipts; sockets=0; capacity=measured:128')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
