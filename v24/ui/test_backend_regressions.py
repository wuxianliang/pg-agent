#!/usr/bin/env python3
"""No-network backend restart/close and mocked frontend regressions.

Run: uv run python v24/ui/test_backend_regressions.py
Uses only an S1-owned disposable DB and temporary private session/journal files.
The close crash checkpoint is after durable fiber-off, before the first dispose;
recovery after disposal is deliberately not claimed by this test.
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import threading
import types
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from psycopg2 import connect
from v24.s1.setup_db import setup_db, server_helper_scope
from v24.ui import app, catalog
from v24.ui.env import UiEnv, acquire_lock, release_lock
from v24.ui.fake import ScriptedUiAdapter
from v24.host.canonical import compact_json

CRASH_EXIT = 73
EXPECTED_PIN_COUNTS = {'read': 7, 'exec': 11}


def require(value, message):
    if not value:
        raise AssertionError(message)


def save(path, value):
    raw = json.dumps(value, sort_keys=True).encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def environment(config, toolset):
    data = Path(config['data']).resolve()
    for path in (data, data / 'workspace', data / 'spawn', data / 'spill'):
        path.mkdir(mode=0o700, exist_ok=True)
    env = UiEnv(ROOT, data, config['db_name'], Path(config['socket_dir']), config['port'],
        config['maintenance_dsn'], config['admin_dsn'], config['service_dsn'], data / 'journal.jsonl',
        data / 'spawn', data / 'workspace', data / 'spill', ROOT / 'v24/ui/skills')
    os.environ.update(V24_UI_MODE='fake', V24_UI_TOOLSET=toolset,
        V24_SKILLS_ROOT=str(env.skills_root), V24_SPILL_ROOT=str(env.spill_root))
    for name in ('V24_UI_WORKSPACE_ROOT', 'DEEPSEEK_API_KEY', 'OPENAI_API_KEY', 'OPENAI_API_URI', 'OPENAI_MODEL'):
        os.environ.pop(name, None)
    return env


def pump(backend, state):
    for _ in range(32):
        if not state.busy:
            break
        backend.tick()
    require(not state.busy, 'backend did not reach a bounded stop')
    backend.rt.db.assert_all_idle()


def resources(backend, scope):
    page = backend.rt.db.host_scope_installs(scope, None, 64)
    require(not page.get('has_more') and len(page['items']) == 2, 'expected two complete family installs')
    result = []
    for row in page['items']:
        fibers = backend.rt.db.host_install_fibers(row['install_id'], None, 64)
        require(not fibers.get('has_more') and len(fibers['items']) == 1, 'fiber listing incomplete')
        result.append({'install': row, 'fiber': fibers['items'][0]})
    return sorted(result, key=lambda item: item['install']['identity'])


def immutable_identity(rows):
    return [(r['install']['install_id'], r['fiber']['fiber_id'], r['install']['manifest_digest'],
             r['install']['artifact_digest'], r['install']['adapter_digest']) for r in rows]


def scope_row(backend, scope):
    page = backend.rt.db.host_scopes(scope, None, 64)
    require(page['has_more'] is False and len(page['items']) == 1, 'scope listing incomplete')
    return page['items'][0]


def child(config_path, phase, toolset):
    config = json.loads(Path(config_path).read_text())
    env = environment(config, toolset)
    state_path = env.data_dir / 'restart-state.json'
    saved = json.loads(state_path.read_text()) if state_path.exists() else {}
    events = []
    # Exact real Backend constructor, with a supplied disposable environment.
    # S1 initialized this schema, so the persistent loaded.json startup check is
    # intentionally separate from these runtime tests.
    backend = app.Backend(lambda sid, event: events.append((sid, event)), env=env, check_environment=False)
    def new(sid):
        backend.new(sid, threading.Event())
        state = backend.states[sid]
        require(state.scope and not state.readonly, 'new session failed')
        row = backend.store.get(state.conversation_id)
        require(row['mode'] == 'fake' and row['limits_digest'] == backend._limits_digest(), 'fake conversation profile not persisted')
        messages = '\n'.join(str(e.value) for s, e in events if s == sid and e.kind == 'message')
        token = re.search(r'resume token: `([^`]+)`', messages)
        require(token is not None, 'resume token missing')
        return state, token.group(1)
    def checkpoint(state, token):
        stored = json.loads(backend.store.path.read_text())['conversations']
        row = next(r for r in stored if r['conversation_id'] == state.conversation_id)
        require(row['mode'] == 'fake' and row['limits_digest'] == backend._limits_digest(), 'fake stored profile')
        require(bool(row['bindings']) and all(b['mode'] == 'fake' and b['limits_digest'] == backend._limits_digest()
                                             for b in row['bindings']), 'fake binding profile not persisted')
        pins = backend.rt.db.host_run_pins(state.run_id, None, 64)
        require(not pins.get('has_more') and {p['key'] for p in pins['items']} == catalog._TOOLSETS[toolset], 'production pins changed')
        require(len(pins['items']) == EXPECTED_PIN_COUNTS[toolset], 'unexpected production pin count')
        return {'scope': state.scope, 'run': state.run_id, 'conversation': state.conversation_id,
                'realm': state.realm, 'token': token, 'resources': resources(backend, state.scope)}
    def resume(name):
        st, _ = new('resume-' + name)
        row = saved[name]
        before = len(backend.rt.adapter.calls)
        backend.command(st.sid, '/resume ' + row['run'] + ' ' + row['token'])
        require(st.scope == row['scope'] and st.run_id == row['run'], 'resume attachment changed identity')
        require(len(backend.rt.adapter.calls) == before, 'resume sent a model request')
        require(immutable_identity(resources(backend, st.scope)) == immutable_identity(row['resources']), 'rehydrate replaced install or digest')
        return st
    try:
        if phase == 1:
            for name in ('waiting', 'changed'):
                st, token = new(name)
                backend.command(st.sid, 'interaction please')
                pump(backend, st)
                require(backend.run(st.run_id)['status'] == 'waiting', 'waiting fixture failed')
                saved[name] = checkpoint(st, token)
            changed = backend.store.get(saved['changed']['conversation'])
            for binding in changed['bindings']:
                binding['catalog_digest'] = '0' * 64 if binding['catalog_digest'] != '0' * 64 else '1' * 64
            changed['active_binding'] = changed['bindings'][-1]
            backend.store.flush()
            st, token = new('running')
            backend.command(st.sid, 'Inspect README.md.')
            require(backend.run(st.run_id)['status'] == 'running', 'running fixture failed')
            saved['running'] = checkpoint(st, token)
            saved['pid1'] = os.getpid()
            save(state_path, saved)
            session_raw = (env.data_dir / 'sessions.json').read_text()
            require(all(row['token'] not in session_raw for row in (saved['waiting'], saved['changed'], saved['running'])), 'raw token persisted in session store')
        elif phase == 2:
            require(os.getpid() != saved['pid1'], 'restart did not use a new process')
            running = resume('running')
            require(running.busy and running.scope in backend.rt.caches, 'running not rehydrated')
            pump(backend, running)
            require(backend.run(running.run_id)['status'] == 'completed', 'running recovery failed')
            waiting = resume('waiting')
            require(not waiting.busy and not waiting.readonly, 'waiting activation changed')
            projection = backend.rt.run_state(waiting.run_id)
            interaction = projection['run']['interaction']['interaction_id']
            require(any(e.kind == 'ask' and e.run_id == waiting.run_id and e.interaction_id == interaction for _, e in events), 'waiting ask not projected')
            before_turns = (env.data_dir / 'turns.jsonl').read_bytes()
            before_events = list(events)
            before_calls = len(backend.rt.adapter.calls)
            with patch.object(backend.rt, 'respond', wraps=backend.rt.respond) as respond, patch.object(backend.rt, '_rpc', wraps=backend.rt._rpc) as rpc:
                for text in ('', ' ', '\n\t', None):
                    backend.answer(waiting.sid, waiting.run_id, interaction, text)
                backend.answer(waiting.sid, 'mismatched-run', interaction, '')
                respond.assert_not_called()
                rpc.assert_not_called()
            require(events == before_events and (env.data_dir / 'turns.jsonl').read_bytes() == before_turns, 'blank answer changed events or turns')
            require(backend.rt.run_state(waiting.run_id) == projection and len(backend.rt.adapter.calls) == before_calls, 'blank answer changed durable run')
            with patch.object(backend.rt, 'respond', wraps=backend.rt.respond) as respond:
                backend.answer(waiting.sid, waiting.run_id, interaction, 'ok')
                require(respond.call_count == 1, 'positive answer did not issue exactly one respond')
            pump(backend, waiting)
            require(backend.run(waiting.run_id)['result']['final_text'] == 'answered', 'answer positive control failed')
            same_scope, previous_run = waiting.scope, waiting.run_id
            backend.command(waiting.sid, 'subsequent turn')
            require(waiting.scope == same_scope and waiting.run_id != previous_run, 'resumed same-scope subsequent start failed')
            pump(backend, waiting)
            require(backend.run(waiting.run_id)['status'] == 'completed' and backend.run(waiting.run_id)['result']['final_text'] == 'echo: subsequent turn', 'subsequent turn did not complete')
            changed_resources = resources(backend, saved['changed']['scope'])
            changed_scope = scope_row(backend, saved['changed']['scope'])
            changed = resume('changed')
            require(changed.readonly and not changed.busy and changed.scope not in backend.rt.caches, 'changed binding not readonly')
            require(any(e.kind == 'message' and e.value == 'catalog_changed; replay only' for _, e in events), 'readonly notice missing')
            snapshot = backend.rt.run_state(changed.run_id)
            row_before = compact_json(backend.store.get(changed.conversation_id))
            effects_before = backend.rt.db.host_run_effects(changed.run_id, None, None, 64)
            with patch.object(backend.rt, 'respond', wraps=backend.rt.respond) as respond, patch.object(backend.rt.worker, 'run_once', wraps=backend.rt.worker.run_once) as worker:
                backend.command(changed.sid, 'must not continue')
                backend.command(changed.sid, '/cancel')
                backend.answer(changed.sid, changed.run_id, snapshot['run']['interaction']['interaction_id'], 'must not answer')
                backend.command(changed.sid, '/close')
                backend.tick()
                respond.assert_not_called()
                worker.assert_not_called()
            require(backend.rt.run_state(changed.run_id) == snapshot and backend.rt.db.host_run_effects(changed.run_id, None, None, 64) == effects_before, 'readonly mutated run/effects')
            require(compact_json(backend.store.get(changed.conversation_id)) == row_before, 'readonly rewrote old binding')
            require(resources(backend, changed.scope) == changed_resources and scope_row(backend, changed.scope) == changed_scope, 'readonly mutated resources or scope')
            require(not any(s == changed.sid and e.kind == 'ask' for s, e in events), 'readonly projected an answerable ask')
            steered, _ = new('busy-steer')
            backend.command(steered.sid, 'initial message')
            backend.command(steered.sid, '/steer latest instruction')
            pump(backend, steered)
            require(backend.run(steered.run_id)['status'] == 'completed' and backend.run(steered.run_id)['result']['final_text'] == 'steered: latest instruction', 'busy steer did not reach actual backend')
            require(any(s == steered.sid and e.kind == 'step' and e.value.name == 'run · steer queued' for s, e in events), 'steer queue step missing')
            cancelled, _ = new('busy-cancel')
            backend.command(cancelled.sid, 'cancel this run')
            sends = len(backend.rt.adapter.calls)
            backend.command(cancelled.sid, '/cancel')
            pump(backend, cancelled)
            require(backend.run(cancelled.run_id)['status'] == 'cancelled' and len(backend.rt.adapter.calls) == sends, 'busy cancel sent a model or failed cancellation')
            # Abrupt exit only after actual fiber-off commits, before any dispose.
            actual_rpc = backend.rt._rpc
            original_rows = saved['running']['resources']
            def interrupt(statement, params=(), **kwargs):
                if statement == 'SELECT v24.dispose(%s,%s)':
                    require(params[0] in {r['install']['install_id'] for r in original_rows}, 'wrong close target')
                    rows = resources(backend, running.scope)
                    require(scope_row(backend, running.scope)['closed_at'] is None, 'checkpoint scope already closed')
                    require(all(r['install']['state'] == 'installed' and r['install']['disposed_at'] is None and r['fiber']['disposed_at'] is None for r in rows), 'checkpoint passed disposal boundary')
                    target = next(r for r in rows if r['install']['install_id'] == params[0])
                    require(target['fiber']['want_on'] is False, 'fiber off not durable')
                    require(immutable_identity(rows) == immutable_identity(original_rows), 'checkpoint changed identities')
                    require(backend.run(running.run_id)['status'] == 'completed', 'close did not converge')
                    saved['pid2'] = os.getpid()
                    saved['checkpoint_install'] = params[0]
                    save(state_path, saved)
                    print(f'[checkpoint] {toolset}; pid={os.getpid()}; targeted_fiber_off_before_first_dispose=true; exit={CRASH_EXIT}', flush=True)
                    os._exit(CRASH_EXIT)
                return actual_rpc(statement, params, **kwargs)
            backend.rt._rpc = interrupt
            backend.command(running.sid, '/close')
            raise AssertionError('abrupt close checkpoint not reached')
        elif phase == 3:
            require(len({os.getpid(), saved['pid1'], saved['pid2']}) == 3, 'three distinct processes required')
            row = saved['running']
            require(scope_row(backend, row['scope'])['closed_at'] is None, 'pre-recovery scope changed')
            rows = resources(backend, row['scope'])
            require(immutable_identity(rows) == immutable_identity(row['resources']), 'restart identity changed')
            require(all(r['install']['disposed_at'] is None and r['fiber']['disposed_at'] is None for r in rows), 'unexpected disposal before restart')
            require(next(r for r in rows if r['install']['install_id'] == saved['checkpoint_install'])['fiber']['want_on'] is False, 'durable off lost')
            st = resume('running')
            require(st.scope not in backend.rt.caches, 'terminal resume drove rehydration')
            sends = len(backend.rt.adapter.calls)
            backend.command(st.sid, '/close')
            require(scope_row(backend, row['scope'])['closed_at'] is not None, 'recovered close lacks authoritative closed_at')
            require(not st.scope and not st.busy and backend.store.get(row['conversation']) is None, 'closed binding not removed')
            require(row['conversation'] not in (env.data_dir / 'sessions.json').read_text(), 'closed conversation persisted in sessions')
            require(not any(json.loads(line).get('conversation_id') == row['conversation'] for line in (env.data_dir / 'turns.jsonl').read_text().splitlines()), 'closed turns persisted')
            require(len(backend.rt.adapter.calls) == sends, 'close sent a model request')
            rows = resources(backend, row['scope'])
            require(all(r['install']['disposed_at'] is not None and r['fiber']['disposed_at'] is not None and not r['fiber']['want_on'] for r in rows), 'resources not disposed')
            require(any(e.kind == 'step' and e.value.name == 'scope · closed' for _, e in events), 'close step missing')
            require(not any(e.kind == 'message' and str(e.value).startswith('close_incomplete') for _, e in events), 'close failed')
            backend.rt.close_scope(row['scope'])
            require(scope_row(backend, row['scope'])['closed_at'] is not None, 'repeat close lost authority')
            backend.command(st.sid, '/close')
            require(events[-2][1].value == 'conversation_closed', 'repeat backend close not idempotent')
        backend.rt.db.assert_all_idle()
        require(not any(e.kind == 'message' and str(e.value).startswith('runtime_error') for _, e in events), 'runtime error event')
        print(f'[passed] backend phase={phase}; toolset={toolset}; pid={os.getpid()}; production_pins={len(catalog._TOOLSETS[toolset])}; provider=fake', flush=True)
    finally:
        backend.close()
        fd = acquire_lock(env.data_dir)
        release_lock(fd)


async def frontend():
    callbacks, submits, task_ends = {}, [], []
    sid = 'frontend-regression'
    replies = asyncio.Queue()
    ask_entered = asyncio.Queue()
    class Message:
        def __init__(self, **kwargs): pass
        async def send(self): pass
    class Step(Message): pass
    class Ask(Message):
        async def send(self):
            ask_entered.put_nowait(None)
            return await replies.get()
    async def task_end(): task_ends.append(True)
    cl = types.SimpleNamespace(Message=Message, Step=Step, AskUserMessage=Ask,
        user_session=types.SimpleNamespace(get=lambda name: sid),
        context=types.SimpleNamespace(emitter=types.SimpleNamespace(task_end=task_end)))
    for name in ('on_app_shutdown', 'on_chat_start', 'on_message', 'on_stop', 'on_chat_end'):
        def register(fn, name=name): callbacks[name] = fn; return fn
        setattr(cl, name, register)
    async def submit(method, *args): submits.append((method, args))
    async def reached(predicate):
        for _ in range(100):
            if predicate(): return
            await asyncio.sleep(0)
        raise AssertionError('frontend callback did not settle')
    with patch.dict(sys.modules, {'chainlit': cl}), patch.object(app, '_submit', side_effect=submit):
        app.register_chainlit()
        await callbacks['on_chat_start']()
        session = app.SESSIONS[sid]
        await reached(lambda: session.consuming)
        consumer = session.consumer_task
        await callbacks['on_message'](types.SimpleNamespace(content='first'))
        await callbacks['on_message'](types.SimpleNamespace(content='busy steer'))
        require(consumer is session.consumer_task and not consumer.done(), 'frontend replaced consumer')
        for response in ({'output': ''}, {'output': '  '}, None, {'output': 'ok'}):
            await replies.put(response)
            await session.queue.put(app.UiEvent('ask', 'Continue?', run_id='original-run', interaction_id='original-interaction'))
            expected = len(task_ends) + 1
            await asyncio.wait_for(ask_entered.get(), timeout=5)
            await reached(lambda: len(task_ends) == expected)
        await reached(lambda: sum(method == 'answer' for method, _ in submits) == 1)
        require([args for method, args in submits if method == 'answer'] == [(sid, 'original-run', 'original-interaction', 'ok')], 'blank or untagged frontend answer submitted')
        await session.queue.put(app.UiEvent('ask', 'Wait?', run_id='r', interaction_id='i'))
        await asyncio.wait_for(ask_entered.get(), timeout=5)
        waiting = session.ask_task
        await callbacks['on_stop']()
        require(session.stop.is_set(), 'stop did not set shared event')
        live = asyncio.create_task(asyncio.sleep(30))
        with patch.object(app, '_HUB_TASK', live):
            await callbacks['on_chat_end']()
        live.cancel()
        await asyncio.gather(live, waiting, consumer, return_exceptions=True)
        require(sid not in app.SESSIONS and waiting.cancelled() and consumer.cancelled(), 'frontend end did not cancel tasks')
        require(submits == [('new', (sid, session.stop)), ('command', (sid, 'first')), ('command', (sid, 'busy steer')), ('answer', (sid, 'original-run', 'original-interaction', 'ok')), ('detach', (sid,))], 'frontend submission wiring changed')
        require(len(task_ends) == 5, 'frontend cleanup did not balance ask')
    print('[passed] frontend callbacks; persistent_consumer=true; blank_answers=3; tagged_answer=true; stop_detach_cleanup=true; browser_acceptance=separate', flush=True)


def main():
    logging.getLogger('pgembed').setLevel(logging.WARNING)
    if len(sys.argv) > 1 and sys.argv[1] == '--child':
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')), patch.object(app.FakeAppAdapter, 'send', ScriptedUiAdapter.send):
            child(sys.argv[2], int(sys.argv[3]), sys.argv[4])
        return
    with patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')):
        asyncio.run(frontend())
        with tempfile.TemporaryDirectory(prefix='v24-backend-regression-') as directory:
            data = Path(directory).resolve()
            hook = data / 'python-hook'
            hook.mkdir(mode=0o700)
            (hook / 'sitecustomize.py').write_text(
                'import sys\nfrom pathlib import Path\nsys.path.insert(0, ' + repr(str(ROOT)) + ')\n'
                'import server\nserver.PGDATA = Path(' + repr(str(data / 'private-postgres')) + ')\n')
            with patch.dict(os.environ, {'PYTHONPATH': str(hook) + os.pathsep + str(ROOT)}), server_helper_scope(), setup_db() as db:
                require((data / 'private-postgres' / 'PG_VERSION').is_file(), 'private PGDATA not used')
                run_children(data, db)
    print('[passed] backend regressions; read7_exec11=three_processes_each; empty_answer=real_entry_zero_rpc; old_binding=readonly; same_scope_next_start=true; busy_steer_cancel=true; close_checkpoint=targeted_fiber_off_before_dispose; repeated_close=authoritative; python_connect_tripwire=true; db_transport=unix', flush=True)


def run_children(data, db):
    # Remove S1's fixture-only fake journal schema to retain the UI ten-table
    # catalog; this database is S1-owned and never the persistent UI environment.
    with connect(db.admin_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute('DROP SCHEMA IF EXISTS v24_fake CASCADE')
    from psycopg2.extensions import parse_dsn
    endpoint = parse_dsn(db.admin_dsn)
    require(Path(endpoint['host']).is_absolute(), 'DB transport must be a Unix socket')
    for toolset in ('read', 'exec'):
        (data / toolset).mkdir(mode=0o700)
        config = {'data': str(data / toolset), 'db_name': db.name, 'socket_dir': endpoint['host'], 'port': int(endpoint['port']),
            'maintenance_dsn': db.maintenance_dsn, 'admin_dsn': db.role_dsn('admin'), 'service_dsn': db.role_dsn('service')}
        config_path = data / (toolset + '.json')
        save(config_path, config)
        for phase in (1, 2, 3):
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--child', str(config_path), str(phase), toolset],
                cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120)
            # Child output contains only assertion diagnostics and public IDs,
            # never the private config or token-bearing UiEvent payloads.
            print(result.stdout, end='', flush=True)
            require(result.returncode == (CRASH_EXIT if phase == 2 else 0), f'backend child failed: {toolset}/{phase} exit={result.returncode}')
            if phase == 2:
                require('[checkpoint]' in result.stdout and 'targeted_fiber_off_before_first_dispose=true' in result.stdout, 'abrupt exit lacked checkpoint witness')


if __name__ == '__main__':
    main()
