"""CDP6-R: claim / receipt / journal / dispatch / run_start crash recovery.

Run with: uv run python v24/cordis/dp6/test_recovery.py

Every crash boundary uses a real child process (SIGKILL or a named self-kill
after the production step) on one canonical-loaded database.  Fake handlers
only; no external adapter and no network.  The parent inspects committed DB
facts and restarts with empty process memory.
"""
from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import psycopg2
from psycopg2.extensions import TRANSACTION_STATUS_IDLE
from psycopg2.extras import Json

CORDIS = Path(__file__).resolve().parents[1]
DP1 = CORDIS / 'dp1'
DP2 = CORDIS / 'dp2'
DP3 = CORDIS / 'dp3'
DP4 = CORDIS / 'dp4'
DP5 = CORDIS / 'dp5'
DP6 = Path(__file__).resolve().parent
for path in (CORDIS, DP1, DP2, DP3, DP4, DP5, DP6):
    sys.path.insert(0, str(path))

from setup_db import Server, TestDB, TABLES, role_state  # noqa: E402
from test_support import (query, api, env, command, install_payload,  # noqa: E402
                          reconcile_payload, successor_key, derive, active_owner)
from test_ddl import snapshot  # noqa: E402
from test_activation import (declaration, install, commit_new, commit_child, p0,  # noqa: E402
                             phases, one, rows)
from test_teardown import (mutate, root_install, activate as activate_teardown,  # noqa: E402
                           enter_closing, p6_slot, next_slot, drain, applied)
from dp4_support import (provider, agent, prepare_run, claim, settle, model_body,  # noqa: E402
                         tool_body, tool_call, run_start_effect, run_row)
from test_dispatch import (HOST, RUN, listener, declaration_with,  # noqa: E402
                           create as dispatch_create, activate as activate_dispatch,
                           fresh_scope, drain_ready, dispatch_of, parent_result, children,
                           progress_events, root_fixture, settle_success)
import driver as drv  # noqa: E402

ZERO = uuid.UUID(int=0)
EXIT_CRASH = 23


# ----------------------------------------------------------------- fixtures

def owner_rows(db, statement, params=()):
    with contextlib.closing(db.connect('owner')) as conn:
        got = query(conn, statement, params)
        conn.rollback()
        return got


def owner_one(db, statement, params=()):
    return owner_rows(db, statement, params)[0][0]


def owner_do(db, statement, params=()):
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, statement, params)
        conn.commit()


def snap(db):
    with contextlib.closing(db.connect('owner')) as conn:
        got = snapshot(conn)
        conn.rollback()
        return got


def effect_row(db, effect):
    return owner_rows(db, 'SELECT status,attempt,fence,claim_owner,lease_until,outcome,'
                          'kind,request_actor FROM v24_cordis.effects WHERE id=%s', (effect,))[0]


def effect_status(db, effect):
    return effect_row(db, effect)[0]


def journal_files(path):
    return sorted(p.name for p in Path(path).glob('*.json'))


def wait_until(predicate, timeout=10.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError('condition did not become true')


def wait_backend_gone(db, login, timeout=10.0):
    def gone():
        return owner_one(db, 'SELECT count(*) FROM pg_stat_activity WHERE datname=%s '
                             'AND usename=%s', (db.name, login)) == 0
    return wait_until(gone, timeout)


class Provider:
    def __init__(self, db, actors):
        self.db = db
        self.actors = set(actors)

    def observer(self):
        return self.db.connect('observer')

    def actor(self, login):
        if login not in self.actors:
            raise drv.CredentialMissing(login)
        return self.db.server.connect(self.db.name, login)


class TrackingConnection:
    def __init__(self, conn, log):
        self._conn = conn
        self._log = log
        self._closed = False

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def commit(self):
        with self._conn.cursor() as cur:
            cur.execute('SHOW transaction_isolation')
            self._log.append(('isolation', cur.fetchone()[0]))
        self._conn.commit()
        self._log.append(('commit', self._conn.get_transaction_status()))

    def rollback(self):
        self._conn.rollback()
        self._log.append(('rollback', self._conn.get_transaction_status()))

    def close(self):
        if not self._closed:
            self._log.append(('close', self._conn.get_transaction_status()))
            self._conn.close()
            self._closed = True


class MappingProvider(Provider):
    def __init__(self, db, actors, mapping):
        super().__init__(db, actors)
        self.mapping = mapping

    def actor(self, login):
        if login not in self.actors:
            raise drv.CredentialMissing(login)
        return self.db.server.connect(self.db.name, self.mapping.get(login, login))


class TrackingProvider(Provider):
    def __init__(self, db, actors):
        super().__init__(db, actors)
        self.log = []
        self.opened = 0

    def _wrap(self, conn):
        self.opened += 1
        return TrackingConnection(conn, self.log)

    def observer(self):
        return self._wrap(super().observer())

    def actor(self, login):
        return self._wrap(super().actor(login))


class Handler:
    """In-process trusted Fake handler; records the transaction boundary."""

    def __init__(self, mode='model_final'):
        self.mode = mode
        self.calls = []

    def __call__(self, request):
        assert request['open_connections'] == 0, request
        self.calls.append({'kind': request['kind'], 'effect_id': request['effect_id'],
                           'attempt': request['attempt'], 'fence': request['fence'],
                           'run_start': request['run_start'], 'input': request['input']})
        if self.mode == 'unknown' or (self.mode == 'unknown_model'
                                      and request['kind'] == 'model_call'):
            return {'class': 'unknown', 'body': {}}
        if (self.mode == 'unknown_first_listener' and request['kind'] == 'listener_call'
                and request['input'].get('ordinal') == 0):
            return {'class': 'unknown', 'body': {}}
        if self.mode == 'failure':
            if request['kind'] == 'run_start':
                return {'class': 'failure', 'body': {'v': 1,
                        'error': {'code': 'start_failed'}}}
            if request['kind'] == 'model_call':
                return {'class': 'failure', 'body': {'kind': 'model_call',
                        'error': {'code': 'model_failed'}}}
            return {'class': 'failure', 'body': {'kind': request['kind'],
                    'error': {'code': 'listener_error'}}}
        if request['kind'] == 'run_start':
            return {'class': 'success'}
        if request['kind'] == 'model_call':
            return {'class': 'success', 'body': model_body(final=True)}
        if request['kind'] == 'tool_call':
            return {'class': 'success', 'body': tool_body()}
        if request['kind'] == 'listener_call':
            value = {'ordinal': request['input'].get('ordinal'),
                     'seen_acc': request['input'].get('acc')}
            if str(request['input'].get('listener_id', '')).endswith('bail'):
                value = {'bail': True, 'ordinal': request['input'].get('ordinal')}
            return {'class': 'success',
                    'body': {'kind': 'listener_call', 'result': {'value': value}}}
        raise AssertionError('unexpected kind ' + request['kind'])


def make_maintainer(db, handler, journal, source, *, actors=None, lease_ms=300,
                    fault=None, tracking=False):
    provider_obj = (TrackingProvider if tracking else Provider)(
        db, {db.roles['service']} if actors is None else actors)
    executor = drv.Executor(actor_connect=provider_obj.actor,
                            observer_connect=provider_obj.observer,
                            handler=handler, journal=journal,
                            run_requests=source, lease_ms=lease_ms, fault=fault)
    maintainer = drv.Maintainer(observer_connect=provider_obj.observer,
                                actor_connect=provider_obj.actor,
                                ensure_actor=db.roles['service'],
                                handler=handler, executor=executor, fault=fault)
    return maintainer, executor, provider_obj


def quiet_round(maintainer, report=None):
    report = report or maintainer.run_once()
    return report


# ------------------------------------------------------- run_start fixtures

def agent_with_run_contract(db, run_replay, *, digest='c' * 64, steps=3,
                            requires=('model',), request=None):
    root = active_owner(db)
    payload = install_payload(mode='existing', existing_scope=root['scope'],
                              owner=dict(fiber_id=str(root['fiber']),
                                         episode_id=str(root['episode'])))
    payload['manifest'] = dict(requires=list(requires), provides=[],
                               priority=0, check={})
    contract = dict(contract_version='1', handler_digest=digest)
    if run_replay is not None:
        contract['replay'] = dict(repeat=bool(run_replay[0]),
                                  concurrent=bool(run_replay[1]))
    payload['contracts'] = {'run_start': contract}
    payload['policy_ref'] = 'chat_tool'
    effect, result, _ = commit_new(db, 'command_install', payload)
    assert result.get('disposition') == 'committed', result
    fiber = uuid.UUID(payload['fiber_id'])
    parent, started, _ = p0(db, fiber)
    assert started.get('emitted'), started
    step, result = commit_child(db, parent, reconcile_payload(fiber, 'advance', 1))
    assert result.get('disposition') == 'committed', result
    step, result = commit_child(db, step, reconcile_payload(fiber, 'advance', 1))
    assert result.get('disposition') == 'committed', result
    run_start = run_start_effect(db, result)
    assert run_start is not None, result
    contract = payload['contracts']['run_start']
    return dict(payload=payload, fiber=fiber, run_start=run_start,
                contract={'contract_version': contract['contract_version'],
                          'handler_digest': contract['handler_digest']})


def chat_only_agent(db):
    provider(db, 'model_call', 'model')
    chat = agent(db, requires=('model',))
    return chat, run_start_effect(db, chat['p4_result'])


def source_for(effect, contract, *, steps=3, request=None, directory):
    source = drv.RunStartSource(directory)
    request = {'text': 'fixed-request'} if request is None else request
    source.provision(effect, contract, request, steps)
    return source


# ------------------------------------------------------- child process mode

def _child_connect(cfg, role):
    params = dict(cfg['params'])
    params.pop('dbname', None)
    params.pop('user', None)
    return psycopg2.connect(**params, dbname=cfg['dbname'], user=role)


class ChildHandler:
    def __init__(self, cfg):
        self.cfg = cfg
        self.calls = Path(cfg['calls']) if cfg.get('calls') else None
        self.marker = Path(cfg['marker']) if cfg.get('marker') else None
        self.mode = cfg.get('handler', 'model_final')

    def _record(self, request):
        if self.marker is not None:
            with open(self.marker, 'w') as handle:
                json.dump({'phase': 'handler', 'pid': os.getpid(),
                           'effect': request['effect_id'],
                           'open_connections': request['open_connections']}, handle)
                handle.flush()
                os.fsync(handle.fileno())
        if self.calls is not None:
            with open(self.calls, 'a') as handle:
                handle.write(json.dumps({
                    'kind': request['kind'], 'effect_id': request['effect_id'],
                    'attempt': request['attempt'], 'fence': request['fence'],
                    'run_start': request['run_start'],
                    'open_connections': request['open_connections']}) + '\n')
                handle.flush()
                os.fsync(handle.fileno())

    def __call__(self, request):
        assert request['open_connections'] == 0, request
        self._record(request)
        mode = self.mode
        if mode == 'sleep':
            time.sleep(120)
        if mode == 'unknown':
            return {'class': 'unknown', 'body': {}}
        if mode == 'failure':
            return {'class': 'failure', 'body': {'kind': request['kind'],
                    'error': {'code': 'adapter_failure'}}}
        if request['kind'] == 'run_start':
            return {'class': 'success'}
        if request['kind'] == 'model_call':
            return {'class': 'success', 'body': model_body(final=True)}
        if request['kind'] == 'tool_call':
            return {'class': 'success', 'body': tool_body()}
        if request['kind'] == 'listener_call':
            value = {'ordinal': request['input'].get('ordinal'),
                     'seen_acc': request['input'].get('acc')}
            if str(request['input'].get('listener_id', '')).endswith('bail'):
                value = {'bail': True, 'ordinal': request['input'].get('ordinal')}
            return {'class': 'success',
                    'body': {'kind': 'listener_call', 'result': {'value': value}}}
        raise AssertionError('unexpected kind ' + request['kind'])


def _child_fault(name, after, effect=None):
    state = {'count': 0}

    def fault(phase, **info):
        if phase != name:
            return
        if effect is not None and info.get('effect_id') != effect:
            return
        state['count'] += 1
        if state['count'] >= int(after):
            os._exit(EXIT_CRASH)
    return fault


def _child_recovery():
    cfg = json.loads(os.environ['DP6_RECOVERY_CHILD'])
    actors = set(cfg['actors'])

    def observer():
        return _child_connect(cfg, cfg['observer'])

    def actor(login):
        if login not in actors:
            raise drv.CredentialMissing(login)
        return _child_connect(cfg, login)

    journal = drv.ReceiptJournal(cfg['journal'])
    source = drv.RunStartSource(cfg['source']) if cfg.get('source') else None
    handler = ChildHandler(cfg)
    fault = None
    if cfg.get('fault'):
        fault = _child_fault(cfg['fault'], cfg.get('fault_after', 1),
                             cfg.get('fault_effect'))
    executor = drv.Executor(actor_connect=actor, observer_connect=observer,
                            handler=handler, journal=journal, run_requests=source,
                            lease_ms=cfg.get('lease_ms', 300), fault=fault)
    maintainer = drv.Maintainer(observer_connect=observer, actor_connect=actor,
                                ensure_actor=cfg['actors'][0], handler=handler,
                                executor=executor, fault=fault)
    mode = cfg.get('mode', 'scan')
    if mode == 'scan':
        actions = []
        for _ in range(cfg.get('rounds', 1)):
            report = maintainer.run_once()
            actions.extend({'topic': a['topic'], 'key': str(a['key']),
                            'disposition': a['disposition']} for a in report.actions)
        print('DP6CHILD ' + json.dumps({'actions': actions,
                                        'stats': executor.stats}), flush=True)
        return
    if mode == 'command':
        result = maintainer._advance(cfg['actor'], uuid.UUID(cfg['effect']),
                                     cfg['payload'], cfg['key'], cfg['kind'])
        print('DP6CHILD ' + json.dumps({'result': result, 'stats': executor.stats}),
              flush=True)
        return
    raise AssertionError('unknown child mode ' + mode)


def spawn_child(cfg, *, wait=True, timeout=60):
    body = dict(cfg)
    body.setdefault('params', dict(_server_params()))
    env = dict(os.environ, DP6_RECOVERY_CHILD=json.dumps(body))
    proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                             '--child-recovery'], env=env, cwd=str(CORDIS.parent),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, start_new_session=True)
    if not wait:
        return proc
    out, err = proc.communicate(timeout=timeout)
    return proc.returncode, out, err


_SERVER = {}


def _server_params():
    server = _SERVER['server']
    params = dict(server.params)
    params.pop('dbname', None)
    params.pop('user', None)
    return params


def child_config(db, *, journal, source=None, handler='model_final', fault=None,
                 fault_after=1, fault_effect=None, rounds=1, lease_ms=300,
                 calls=None, marker=None):
    return dict(dbname=db.name, params=_server_params(), observer=db.roles['observer'],
                actors=[db.roles['service']], journal=str(journal),
                source=str(source) if source else None, handler=handler,
                fault=fault, fault_after=fault_after,
                fault_effect=str(fault_effect) if fault_effect else None,
                rounds=rounds, lease_ms=lease_ms,
                calls=str(calls) if calls else None,
                marker=str(marker) if marker else None)


def crash_child(cfg, *, expect=EXIT_CRASH, timeout=60):
    code, out, err = spawn_child(cfg, timeout=timeout)
    assert code == expect, (code, out, err)
    return out, err


# ------------------------------------------------------------------ tests

def test_run_start_and_model(db):
    with tempfile.TemporaryDirectory() as tmp:
        journal_dir = Path(tmp) / 'journal'
        source_dir = Path(tmp) / 'source'
        chat, run_start = chat_only_agent(db)
        contract = owner_one(db, "SELECT input->'contract' FROM v24_cordis.effects WHERE id=%s",
                             (run_start,))
        source = source_for(run_start, contract, steps=3, directory=source_dir)
        handler = Handler('model_final')
        m, ex, provider_obj = make_maintainer(db, handler, drv.ReceiptJournal(journal_dir),
                                              source, lease_ms=500)
        for _ in range(5):
            m.run_once()
        assert [c['kind'] for c in handler.calls] == ['run_start', 'model_call'], handler.calls
        assert effect_status(db, run_start) == 'succeeded'
        assert len(journal_files(journal_dir)) == 0
        run = one(db, 'SELECT v24_cordis.run_id_for(%s)', (run_start,))
        assert run_row(db, run)[2] is not None
        assert owner_one(db, 'SELECT remaining_steps FROM v24_cordis.runs WHERE id=%s',
                         (run,)) == 2
        assert ex.stats['handlers'] == 2 and ex.stats['confirmed'] == 2, ex.stats
        print('[CDP6-R1] production run_start source -> model_call -> final run settlement; '
              'claim IDLE before handler, receipt journal empty after confirmed COMMIT')


def test_claim_before_commit_rollback(db):
    with tempfile.TemporaryDirectory() as tmp:
        journal_dir = Path(tmp) / 'journal'
        source_dir = Path(tmp) / 'source'
        chat, run_start = chat_only_agent(db)
        contract = owner_one(db, "SELECT input->'contract' FROM v24_cordis.effects WHERE id=%s",
                             (run_start,))
        source = source_for(run_start, contract, steps=3, directory=source_dir)
        calls = Path(tmp) / 'calls.jsonl'
        cfg = child_config(db, journal=journal_dir, source=source_dir,
                           handler='model_final', fault='claim_before_commit',
                           calls=calls)
        crash_child(cfg)
        wait_backend_gone(db, db.roles['service'])
        row = effect_row(db, run_start)
        assert row[0] == 'ready' and row[1] == 0 and row[2] == 0, row
        assert not calls.exists() or calls.read_text() == ''
        handler = Handler('model_final')
        m, ex, _ = make_maintainer(db, handler, drv.ReceiptJournal(journal_dir),
                                   drv.RunStartSource(source_dir), lease_ms=500)
        for _ in range(5):
            m.run_once()
        assert [c['kind'] for c in handler.calls][:2] == ['run_start', 'model_call']
        assert effect_status(db, run_start) == 'succeeded'
        print('[CDP6-R2] claim transaction killed before COMMIT rolls back; effect stays ready '
              'at attempt/fence 0 and a fresh process claims it exactly once')


def test_claim_commit_lost_then_reclaim(db):
    with tempfile.TemporaryDirectory() as tmp:
        journal_dir = Path(tmp) / 'journal'
        source_dir = Path(tmp) / 'source'
        chat, run_start = chat_only_agent(db)
        contract = owner_one(db, "SELECT input->'contract' FROM v24_cordis.effects WHERE id=%s",
                             (run_start,))
        source_for(run_start, contract, steps=3, directory=source_dir)
        calls = Path(tmp) / 'calls.jsonl'
        cfg = child_config(db, journal=journal_dir, source=source_dir,
                           handler='model_final', fault='claim_after_commit',
                           calls=calls)
        crash_child(cfg)
        wait_backend_gone(db, db.roles['service'])
        row = effect_row(db, run_start)
        assert row[0] == 'claimed' and row[1] == 1 and row[2] == 1, row
        assert not calls.exists() or calls.read_text() == ''
        # The short lease has not expired yet: the fresh host must wait.
        handler = Handler('model_final')
        m, ex, _ = make_maintainer(db, handler, drv.ReceiptJournal(journal_dir),
                                   drv.RunStartSource(source_dir), lease_ms=250)
        m.run_once()
        assert effect_row(db, run_start)[1] == 1
        time.sleep(0.4)
        for _ in range(6):
            m.run_once()
        assert effect_status(db, run_start) == 'succeeded', effect_row(db, run_start)
        first = [c for c in handler.calls if c['kind'] == 'run_start']
        assert len(first) == 1 and first[0]['attempt'] == 2 and first[0]['fence'] == 2, first
        assert first[0]['run_start']['steps'] == 3
        print('[CDP6-R3] claim COMMIT then host death leaves one claimed token; restart waits, '
              'expiry with repeat+concurrent reclaims a new fence, original steps survive')


def test_io_during_kill(db):
    with tempfile.TemporaryDirectory() as tmp:
        journal_dir = Path(tmp) / 'journal'
        source_dir = Path(tmp) / 'source'
        chat, run_start = chat_only_agent(db)
        contract = owner_one(db, "SELECT input->'contract' FROM v24_cordis.effects WHERE id=%s",
                             (run_start,))
        source_for(run_start, contract, steps=4, directory=source_dir)
        calls = Path(tmp) / 'calls.jsonl'
        marker = Path(tmp) / 'marker.json'
        cfg = child_config(db, journal=journal_dir, source=source_dir,
                           handler='sleep', marker=marker, calls=calls, lease_ms=250)
        proc = spawn_child(cfg, wait=False)
        try:
            wait_until(lambda: marker.exists())
            os.killpg(proc.pid, signal.SIGKILL)
        finally:
            proc.wait(timeout=10)
        assert proc.returncode == -signal.SIGKILL
        wait_backend_gone(db, db.roles['service'])
        row = effect_row(db, run_start)
        assert row[0] == 'claimed' and row[1] == 1 and row[2] == 1, row
        assert journal_files(journal_dir) == []
        time.sleep(0.35)
        handler = Handler('model_final')
        m, ex, _ = make_maintainer(db, handler, drv.ReceiptJournal(journal_dir),
                                   drv.RunStartSource(source_dir), lease_ms=250)
        for _ in range(8):
            m.run_once()
        starts = [c for c in handler.calls if c['kind'] == 'run_start']
        assert len(starts) == 1 and starts[0]['fence'] == 2, starts
        assert effect_status(db, run_start) == 'succeeded'
        assert journal_files(journal_dir) == []
        print('[CDP6-R4] SIGKILL during the Fake adapter leaves no journal and one claimed token; '
              'only the explicit replay right reclaims; the new fence publishes once')


def test_journal_after_write_before_settle(db):
    with tempfile.TemporaryDirectory() as tmp:
        journal_dir = Path(tmp) / 'journal'
        source_dir = Path(tmp) / 'source'
        chat, run_start = chat_only_agent(db)
        contract = owner_one(db, "SELECT input->'contract' FROM v24_cordis.effects WHERE id=%s",
                             (run_start,))
        source_for(run_start, contract, steps=3, directory=source_dir)
        calls = Path(tmp) / 'calls.jsonl'
        cfg = child_config(db, journal=journal_dir, source=source_dir,
                           handler='model_final', fault='journal_after_write',
                           calls=calls)
        crash_child(cfg)
        wait_backend_gone(db, db.roles['service'])
        assert effect_row(db, run_start)[0] == 'claimed'
        entries = journal_files(journal_dir)
        assert len(entries) == 1, entries
        recorded = json.loads((journal_dir / entries[0]).read_text())
        assert recorded['effect_id'] == str(run_start)
        assert recorded['actor'] == db.roles['service']
        assert recorded['token']['attempt'] == 1
        assert recorded['outcome']['body']['steps'] == 3
        assert recorded['outcome']['body']['request'] == {'text': 'fixed-request'}
        assert recorded['digest'] == drv.sha256_hex(
            {key: recorded[key] for key in ('v', 'effect_id', 'actor', 'token', 'outcome')})
        handler = Handler('model_final')
        m, ex, _ = make_maintainer(db, handler, drv.ReceiptJournal(journal_dir),
                                   drv.RunStartSource(source_dir), lease_ms=500)
        m.run_once()
        assert effect_status(db, run_start) == 'succeeded'
        assert [c['kind'] for c in handler.calls] == ['model_call'], handler.calls
        assert journal_files(journal_dir) == []
        run = one(db, 'SELECT v24_cordis.run_id_for(%s)', (run_start,))
        assert run_row(db, run)[2] is not None
        assert ex.stats['journal_replays'] == 1 and ex.stats['handlers'] == 1, ex.stats
        print('[CDP6-R5] journal write+fsync before settlement survives death; restart replays '
              'the exact token/body, never calls the adapter and cleans only after COMMIT')


def test_settle_before_commit_journal_replay(db):
    with tempfile.TemporaryDirectory() as tmp:
        journal_dir = Path(tmp) / 'journal'
        source_dir = Path(tmp) / 'source'
        chat, run_start = chat_only_agent(db)
        contract = owner_one(db, "SELECT input->'contract' FROM v24_cordis.effects WHERE id=%s",
                             (run_start,))
        source_for(run_start, contract, steps=3, directory=source_dir)
        cfg = child_config(db, journal=journal_dir, source=source_dir,
                           handler='model_final', fault='settle_before_commit')
        crash_child(cfg)
        wait_backend_gone(db, db.roles['service'])
        assert effect_row(db, run_start)[0] == 'claimed'
        assert len(journal_files(journal_dir)) == 1
        assert owner_one(db, 'SELECT count(*) FROM v24_cordis.runs') == 0
        handler = Handler('model_final')
        m, ex, _ = make_maintainer(db, handler, drv.ReceiptJournal(journal_dir),
                                   drv.RunStartSource(source_dir), lease_ms=500)
        m.run_once()
        assert effect_status(db, run_start) == 'succeeded'
        assert owner_one(db, 'SELECT count(*) FROM v24_cordis.runs') == 1
        assert [c['kind'] for c in handler.calls] == ['model_call'], handler.calls
        assert journal_files(journal_dir) == []
        print('[CDP6-R6] settlement killed before COMMIT keeps the claimed effect and journal; '
              'restart commits the same receipt once without adapter work')


def test_settle_after_commit_response_lost(db):
    with tempfile.TemporaryDirectory() as tmp:
        journal_dir = Path(tmp) / 'journal'
        source_dir = Path(tmp) / 'source'
        chat, run_start = chat_only_agent(db)
        contract = owner_one(db, "SELECT input->'contract' FROM v24_cordis.effects WHERE id=%s",
                             (run_start,))
        source_for(run_start, contract, steps=3, directory=source_dir)
        cfg = child_config(db, journal=journal_dir, source=source_dir,
                           handler='model_final', fault='settle_after_commit')
        crash_child(cfg)
        wait_backend_gone(db, db.roles['service'])
        assert effect_status(db, run_start) == 'succeeded'
        before = snap(db)
        events = owner_one(db, 'SELECT count(*) FROM v24_cordis.events')
        assert len(journal_files(journal_dir)) == 1
        handler = Handler('model_final')
        m, ex, _ = make_maintainer(db, handler, drv.ReceiptJournal(journal_dir),
                                   drv.RunStartSource(source_dir), lease_ms=500)
        replayed = ex.reconcile_journal()
        assert handler.calls == []
        assert journal_files(journal_dir) == []
        assert snap(db) == before
        assert owner_one(db, 'SELECT count(*) FROM v24_cordis.events') == events
        assert any(x.get('driver') == 'receipt_replayed' for x in replayed), replayed
        assert ex.stats['journal_replays'] == 1 and ex.stats['handlers'] == 0, ex.stats
        m.run_once()
        assert [c['kind'] for c in handler.calls] == ['model_call'], handler.calls
        print('[CDP6-R7] settlement COMMIT with the response lost replays by identical receipt: '
              'no second reducer/event, no adapter call, zero table change')


def test_receipt_replay_and_conflict(db):
    with tempfile.TemporaryDirectory() as tmp:
        journal_dir = Path(tmp) / 'journal'
        source_dir = Path(tmp) / 'source'
        chat, run_start = chat_only_agent(db)
        contract = owner_one(db, "SELECT input->'contract' FROM v24_cordis.effects WHERE id=%s",
                             (run_start,))
        source_for(run_start, contract, steps=3, directory=source_dir)
        handler = Handler('model_final')
        m, ex, _ = make_maintainer(db, handler, drv.ReceiptJournal(journal_dir),
                                   drv.RunStartSource(source_dir), lease_ms=500)
        for _ in range(5):
            m.run_once()
        assert effect_status(db, run_start) == 'succeeded'
        outcome = effect_row(db, run_start)[5]
        assert outcome['class'] == 'success'
        token = {'attempt': outcome.get('claim', {}).get('attempt', 1),
                 'fence': outcome.get('claim', {}).get('fence', 1), 'owner': db.roles['service']}
        # Recover the exact receipt token and replay it directly.
        receipt = dict(v=1, **{'class': 'success'}, claim=token, body=outcome['body'])
        with contextlib.closing(db.connect('service')) as conn:
            replay = api(conn, run_start, receipt)
            conn.commit()
        assert replay.get('disposition') == 'replay', replay
        assert replay.get('emitted') == [], replay
        assert handler.calls and len(handler.calls) == 2
        conflict = dict(receipt)
        conflict['body'] = {'v': 1, 'request': {'text': 'different'}, 'steps': 9}
        with contextlib.closing(db.connect('owner')) as owner:
            before = snapshot(owner)
            owner.rollback()
        with contextlib.closing(db.connect('service')) as conn:
            refused = api(conn, run_start, conflict)
            conn.commit()
        assert refused.get('error', {}).get('code') == 'receipt_conflict', refused
        with contextlib.closing(db.connect('owner')) as owner:
            assert snapshot(owner) == before
            owner.rollback()
        print('[CDP6-R8] identical terminal receipt replays with no new work; conflicting bytes '
              'return receipt_conflict and write no table row')


def test_terminal_immutable(db):
    effect = uuid.uuid4()
    with contextlib.closing(db.connect('owner')) as owner:
        query(owner, "INSERT INTO v24_cordis.effects(id,kind,status,input,request_actor,outcome,"
                     "settled_at) VALUES(%s,'run_start','succeeded','{}',%s,'{\"v\":1}'::jsonb,now())",
              (effect, db.roles['service']))
        owner.commit()
        before = snapshot(owner)
        try:
            query(owner, "UPDATE v24_cordis.effects SET outcome='{\"v\":2}'::jsonb WHERE id=%s",
                  (effect,))
            owner.rollback()
        except psycopg2.Error as exc:
            assert exc.pgcode == '55000', exc.pgcode
            owner.rollback()
        else:
            raise AssertionError('terminal outcome was mutable')
        assert snapshot(owner) == before
        owner.rollback()
    print('[CDP6-R9] terminal outcome/attempt/fence replacement is still rejected by the '
          'immutable trigger; no recovery path rewrites history')


def external_row(db, effect):
    return owner_rows(db, "SELECT id,kind,status,fiber_id,episode_id,run_id,request_actor,input,"
                          "attempt,fence,claim_owner,lease_until FROM v24_cordis.effects "
                          'WHERE id=%s', (effect,))[0]


def settle_with(db, effect, token, body, cls='success'):
    with contextlib.closing(db.connect('service')) as conn:
        result = api(conn, effect, env(cls, body, token))
        conn.commit()
    return result


def test_replay_matrix_and_fence(db):
    request = {'text': 'matrix-request'}
    for repeat, concurrent in ((True, True), (True, False), (False, True), (False, False)):
        with tempfile.TemporaryDirectory() as tmp:
            model_key = f'model-{repeat}-{concurrent}'
            provider(db, 'model_call', model_key)
            chat = agent_with_run_contract(db, (repeat, concurrent), requires=(model_key,))
            run_start, contract = chat['run_start'], chat['contract']
            source = drv.RunStartSource(Path(tmp) / 'source')
            source.provision(run_start, contract, request, 3)
            journal = drv.ReceiptJournal(Path(tmp) / 'journal')
            _, ex, _ = make_maintainer(db, Handler(), journal, source, lease_ms=250)
            first = ex._claim(db.roles['service'], run_start)
            assert first.get('disposition') == 'claimed', first
            token = first['claim']
            time.sleep(0.35)
            with contextlib.closing(db.connect('owner')) as owner:
                before = snapshot(owner)
                owner.rollback()
            second = ex._claim(db.roles['service'], run_start)
            if repeat and concurrent:
                assert second.get('disposition') == 'claimed', (repeat, concurrent, second)
                assert second['claim']['attempt'] == 2 and second['claim']['fence'] == 2, second
                with contextlib.closing(db.connect('owner')) as owner:
                    after_claim = snapshot(owner)
                    owner.rollback()
                old = settle_with(db, run_start, token,
                                  {'v': 1, 'request': request, 'steps': 3})
                assert old.get('error', {}).get('code') == 'stale_claim', old
                with contextlib.closing(db.connect('owner')) as owner:
                    assert snapshot(owner) == after_claim
                    owner.rollback()
                new = settle_with(db, run_start, second['claim'],
                                  {'v': 1, 'request': request, 'steps': 3})
                assert new.get('disposition') == 'committed', new
            else:
                assert second.get('error', {}).get('code') == 'blocked_unknown', \
                    (repeat, concurrent, second)
                with contextlib.closing(db.connect('owner')) as owner:
                    assert snapshot(owner) == before
                    owner.rollback()
                old = settle_with(db, run_start, token,
                                  {'v': 1, 'request': request, 'steps': 3})
                assert old.get('disposition') == 'committed', old
            assert effect_status(db, run_start) == 'succeeded'
            run = one(db, 'SELECT v24_cordis.run_id_for(%s)', (run_start,))
            assert owner_one(db, 'SELECT count(*) FROM v24_cordis.runs WHERE id=%s', (run,)) == 1
    print('[CDP6-R10] repeat/concurrent 2x2: only repeat=true AND concurrent=true reclaims; '
          'other combinations return blocked_unknown zero-write while the original token still '
          'settles after lease expiry; a new fence makes the old token stale_claim zero-write')


def test_concurrent_reclaim(db):
    import threading
    with tempfile.TemporaryDirectory() as tmp:
        provider(db, 'model_call', 'race-model')
        chat = agent_with_run_contract(db, (True, True), requires=('race-model',))
        run_start, contract = chat['run_start'], chat['contract']
        source = drv.RunStartSource(Path(tmp) / 'source')
        source.provision(run_start, contract, {'text': 'race'}, 3)
        journal = drv.ReceiptJournal(Path(tmp) / 'journal')
        _, ex, _ = make_maintainer(db, Handler(), journal, source, lease_ms=200)
        first = ex._claim(db.roles['service'], run_start)
        assert first['disposition'] == 'claimed'
        time.sleep(0.3)
        barrier = threading.Barrier(2)
        results = []

        def race():
            executor = drv.Executor(actor_connect=Provider(db, {db.roles['service']}).actor,
                                    observer_connect=Provider(db, {db.roles['service']}).observer,
                                    handler=Handler(), journal=journal,
                                    run_requests=source, lease_ms=200)
            barrier.wait()
            results.append(executor._claim(db.roles['service'], run_start))

        threads = [threading.Thread(target=race) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        claimed = [r for r in results if r.get('disposition') == 'claimed']
        busy = [r for r in results if r.get('error', {}).get('code') == 'stale_claim']
        assert len(claimed) == 1 and len(busy) == 1, results
        assert claimed[0]['claim']['attempt'] == 2 and claimed[0]['claim']['fence'] == 2
        row = effect_row(db, run_start)
        assert row[1] == 2 and row[2] == 2, row
        old = settle_with(db, run_start, first['claim'],
                          {'v': 1, 'request': {'text': 'race'}, 'steps': 3})
        assert old.get('error', {}).get('code') == 'stale_claim'
        new = settle_with(db, run_start, claimed[0]['claim'],
                          {'v': 1, 'request': {'text': 'race'}, 'steps': 3})
        assert new.get('disposition') == 'committed'
    print('[CDP6-R11] two concurrent post-expiry claims under G produce exactly one new fence; '
          'the loser is stale_claim and the old token can never publish after replacement')


def test_old_token_model_after_expiry(db):
    with tempfile.TemporaryDirectory() as tmp:
        chat, run_start = chat_only_agent(db)
        contract = owner_one(db, "SELECT input->'contract' FROM v24_cordis.effects WHERE id=%s",
                             (run_start,))
        source = source_for(run_start, contract, steps=5, directory=Path(tmp) / 'source')
        handler = Handler('model_final')
        m, ex, _ = make_maintainer(db, handler, drv.ReceiptJournal(Path(tmp) / 'journal'),
                                   source, lease_ms=250)
        m.run_once()
        assert [c['kind'] for c in handler.calls] == ['run_start']
        model = owner_one(db, "SELECT id FROM v24_cordis.effects WHERE kind='model_call' "
                              "AND fiber_id=%s AND status='ready'", (chat['fiber'],))
        claimed = ex._claim(db.roles['service'], model)
        assert claimed['disposition'] == 'claimed'
        time.sleep(0.35)
        receipt = settle_with(db, model, claimed['claim'], model_body(final=True))
        assert receipt.get('disposition') == 'committed', receipt
        run = one(db, 'SELECT v24_cordis.run_id_for(%s)', (run_start,))
        assert run_row(db, run)[2] is not None
        assert owner_one(db, 'SELECT remaining_steps FROM v24_cordis.runs WHERE id=%s',
                         (run,)) == 4
    print('[CDP6-R12] a credible original model token settles after lease expiry while the fence '
          'is unchanged; the run reducer consumes it exactly once')


def test_run_start_source_negatives(db):
    chat, run_start = chat_only_agent(db)
    contract = owner_one(db, "SELECT input->'contract' FROM v24_cordis.effects WHERE id=%s",
                         (run_start,))
    expected = {'text': 'source-request'}

    def run_case(source_dir, code, *, prepare):
        source = drv.RunStartSource(source_dir)
        prepare(source)
        handler = Handler('model_final')
        m, ex, _ = make_maintainer(db, handler, drv.ReceiptJournal(Path(source_dir) / 'j'),
                                   source, lease_ms=300)
        with contextlib.closing(db.connect('owner')) as owner:
            before = snapshot(owner)
            owner.rollback()
        report = m.run_once()
        with contextlib.closing(db.connect('owner')) as owner:
            assert snapshot(owner) == before, code
            owner.rollback()
        assert handler.calls == [], (code, handler.calls)
        assert effect_status(db, run_start) == 'ready'
        assert any(d.get('driver') == code for d in report.diagnostics), (code, report.diagnostics)
        assert owner_rows(db, 'SELECT status,attempt,fence FROM v24_cordis.effects WHERE id=%s',
                          (run_start,)) == [('ready', 0, 0)]

    with tempfile.TemporaryDirectory() as tmp:
        run_case(Path(tmp) / 'missing', 'run_start_request_pending', prepare=lambda src: None)

        def corrupt(src):
            src.provision(run_start, contract, expected, 3)
            path = next((Path(src.bindings)).glob('*.json'))
            body = json.loads(path.read_text())
            body['digest'] = '0' * 64
            path.write_text(json.dumps(body))
        run_case(Path(tmp) / 'corrupt', 'run_start_source_corrupt', prepare=corrupt)

        def duplicate(src):
            binding = src.provision(run_start, contract, expected, 3)
            path = Path(src.bindings) / (str(run_start) + '.json')
            (Path(src.bindings) / 'duplicate.json').write_text(path.read_text())
        run_case(Path(tmp) / 'duplicate', 'run_start_source_duplicate', prepare=duplicate)

        def mismatch(src):
            src.provision(run_start, {'contract_version': '2',
                                      'handler_digest': contract['handler_digest']}, expected, 3)
        run_case(Path(tmp) / 'mismatch', 'run_start_contract_mismatch', prepare=mismatch)

        def damaged(src):
            src.provision(run_start, contract, expected, 3)
            path = next((Path(src.bindings)).glob('*.json'))
            body = json.loads(path.read_text())
            body['request'] = {'text': 'tampered'}
            path.write_text(json.dumps(body))
        run_case(Path(tmp) / 'damaged', 'run_start_source_corrupt', prepare=damaged)

    with tempfile.TemporaryDirectory() as tmp:
        source_dir = Path(tmp) / 'source'
        source = drv.RunStartSource(source_dir)
        source.provision(run_start, contract, expected, 3)
        handler = Handler('model_final')
        m, ex, _ = make_maintainer(db, handler, drv.ReceiptJournal(Path(tmp) / 'journal'),
                                   source, lease_ms=250)
        claimed = ex._claim(db.roles['service'], run_start)
        assert claimed['disposition'] == 'claimed', claimed
        for path in (Path(source_dir) / 'bindings').glob('*.json'):
            path.unlink()
        time.sleep(0.3)
        with contextlib.closing(db.connect('owner')) as owner:
            before = snapshot(owner)
            owner.rollback()
        report = m.run_once()
        with contextlib.closing(db.connect('owner')) as owner:
            assert snapshot(owner) == before
            owner.rollback()
        assert handler.calls == []
        assert effect_status(db, run_start) == 'claimed'
        assert any(d.get('driver') == 'run_start_source_missing_claimed'
                   for d in report.diagnostics), report.diagnostics
    print('[CDP6-R13] missing run_start input waits without invention; corrupt/damaged digests, '
          'duplicate bindings and contract mismatch are explicit zero-write blocks with no claim; '
          'a source lost after the claim stays claimed rather than inventing new input')


def test_run_start_allocation_crash(db):
    with tempfile.TemporaryDirectory() as tmp:
        chat, run_start = chat_only_agent(db)
        contract = owner_one(db, "SELECT input->'contract' FROM v24_cordis.effects WHERE id=%s",
                             (run_start,))
        source_dir = Path(tmp) / 'source'
        source = drv.RunStartSource(source_dir)
        source.provision_inbox(run_start, contract, {'text': 'inbox-original'}, 4)
        calls = Path(tmp) / 'calls.jsonl'
        cfg = child_config(db, journal=Path(tmp) / 'journal', source=source_dir,
                           handler='model_final', fault='source_after_bind', calls=calls)
        crash_child(cfg)
        wait_backend_gone(db, db.roles['service'])
        assert effect_status(db, run_start) == 'ready'
        assert len(journal_files(source_dir / 'bindings')) == 1
        assert journal_files(source_dir / 'inbox') == []
        assert not calls.exists() or calls.read_text() == ''
        binding = json.loads(next((source_dir / 'bindings').glob('*.json')).read_text())
        assert binding['request'] == {'text': 'inbox-original'} and binding['steps'] == 4
        handler = Handler('model_final')
        m, ex, _ = make_maintainer(db, handler, drv.ReceiptJournal(Path(tmp) / 'journal'),
                                   drv.RunStartSource(source_dir), lease_ms=500)
        for _ in range(4):
            m.run_once()
        starts = [c for c in handler.calls if c['kind'] == 'run_start']
        assert len(starts) == 1, handler.calls
        assert starts[0]['run_start'] == {'request': {'text': 'inbox-original'}, 'steps': 4}
    print('[CDP6-R14] allocation kill before claim leaves the fsynced original request/steps; '
          'restart consumes the same binding and never re-derives input from events or defaults')


def test_l_iter_batch_rollback_and_commit(db):
    payload, _, _ = install(db, provides=[f'batch-{i:02d}' for i in range(33)])
    fiber = uuid.UUID(payload['fiber_id'])
    p0_effect, started, _ = p0(db, fiber, 0)
    assert started['emitted']
    first, first_result = commit_child(db, p0_effect, reconcile_payload(fiber, 'advance', 1))
    assert owner_one(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id=%s',
                     (fiber,)) == 0
    batch_effect = uuid.UUID(first_result['emitted'][0])
    batch_payload = reconcile_payload(fiber, 'advance', 1)
    batch_key = successor_key(first)
    with tempfile.TemporaryDirectory() as tmp:
        cfg = child_config(db, journal=Path(tmp) / 'journal', handler='model_final',
                           fault='command_before_commit')
        # command mode does not run the scanner; target the registered continuation.
        cfg.update(mode='command', actor=db.roles['service'], effect=str(batch_effect),
                   key=batch_key, kind='command_reconcile', payload=batch_payload)
        crash_child(cfg)
        wait_backend_gone(db, db.roles['service'])
        assert owner_one(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id=%s',
                         (fiber,)) == 0
        assert effect_status(db, batch_effect) == 'ready'
        assert owner_one(db, 'SELECT count(*) FROM v24_cordis.requests WHERE effect_id=%s',
                         (batch_effect,)) == 0
        m, ex, _ = make_maintainer(db, Handler(), drv.ReceiptJournal(Path(tmp) / 'journal'),
                                   None, lease_ms=300)
        for _ in range(8):
            m.run_once()
        assert owner_one(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id=%s',
                         (fiber,)) == 33
        assert owner_one(db, 'SELECT state FROM v24_cordis.episodes WHERE fiber_id=%s',
                         (fiber,)) == 'active'
        assert owner_one(db, "SELECT count(*) FROM v24_cordis.effects WHERE fiber_id=%s "
                             "AND kind='command_reconcile' AND status='ready'", (fiber,)) == 0
    print('[CDP6-R15] L-Iter batch killed before COMMIT rolls back all 32 contributions and the '
          'iterator; restart re-submits the same continuation and converges to 33/active')


def test_command_commit_lost_install(db):
    payload = install_payload(mode='root')
    key = 'cordis/dp6/test/install/' + payload['install_id'] + '/start'
    effect = derive(db.roles['service'], key, 'command_install')
    install_id = uuid.UUID(payload['install_id'])
    with tempfile.TemporaryDirectory() as tmp:
        cfg = child_config(db, journal=Path(tmp) / 'journal')
        cfg.update(mode='command', actor=db.roles['service'], effect=str(effect), key=key,
                   kind='command_install', payload=payload,
                   fault='command_after_commit')
        crash_child(cfg)
        wait_backend_gone(db, db.roles['service'])
        assert owner_one(db, 'SELECT count(*) FROM v24_cordis.installs WHERE id=%s',
                         (install_id,)) == 1
        assert owner_one(db, 'SELECT count(*) FROM v24_cordis.fibers WHERE install_id=%s',
                         (install_id,)) == 1
        with contextlib.closing(db.connect('service')) as conn:
            effect2, outcome = command(db, conn, 'service', 'command_install', payload,
                                       key=key, effect=effect)
            replay = api(conn, effect2, outcome)
            conn.commit()
            replay2 = api(conn, effect2, outcome)
            conn.commit()
        # A command request replay returns the original cached response; it is
        # not the external terminal-receipt `replay` disposition.
        assert replay == replay2, (replay, replay2)
        assert replay.get('effect_id') == str(effect), replay
        assert owner_one(db, 'SELECT count(*) FROM v24_cordis.installs WHERE id=%s',
                         (install_id,)) == 1
        assert owner_one(db, 'SELECT count(*) FROM v24_cordis.effects WHERE id=%s',
                         (effect,)) == 1
    print('[CDP6-R16] install COMMIT ack loss leaves complete rows; request replay returns the '
          'same cached response exactly once and creates no duplicate install/fiber')


def test_unknown_external_debt(db):
    with tempfile.TemporaryDirectory() as tmp:
        chat, run_start = chat_only_agent(db)
        contract = owner_one(db, "SELECT input->'contract' FROM v24_cordis.effects WHERE id=%s",
                             (run_start,))
        source = source_for(run_start, contract, steps=3, directory=Path(tmp) / 'source')
        handler = Handler('unknown_model')
        m, ex, _ = make_maintainer(db, handler, drv.ReceiptJournal(Path(tmp) / 'journal'),
                                   source, lease_ms=300)
        for _ in range(4):
            m.run_once()
        model = owner_one(db, "SELECT id FROM v24_cordis.effects WHERE kind='model_call' "
                              "AND fiber_id=%s", (chat['fiber'],))
        assert effect_status(db, model) == 'unknown'
        calls = len(handler.calls)
        assert calls == 2, handler.calls
        with contextlib.closing(db.connect('owner')) as owner:
            before = snapshot(owner)
            owner.rollback()
        for _ in range(3):
            m.run_once()
        with contextlib.closing(db.connect('owner')) as owner:
            assert snapshot(owner) == before
            owner.rollback()
        assert len(handler.calls) == calls, handler.calls
        assert effect_status(db, model) == 'unknown'
        run = one(db, 'SELECT v24_cordis.run_id_for(%s)', (run_start,))
        assert run_row(db, run)[2] is None
        with contextlib.closing(db.connect('owner')) as owner:
            stable = snapshot(owner)
            owner.rollback()
        with contextlib.closing(db.connect('service')) as conn:
            claim_result = api(conn, model, env('claim', {'lease_ms': 100}))
            conn.commit()
        assert claim_result.get('error', {}).get('code') == 'receipt_conflict', claim_result
        with contextlib.closing(db.connect('owner')) as owner:
            assert snapshot(owner) == stable
            owner.rollback()
        control = enter_closing(db, chat['fiber'])
        plan = one(db, 'SELECT v24_cordis.p6_plan(NULL,%s)', (chat['fiber'],))
        assert plan.get('kind') == 'blocked_unknown', plan
    print('[CDP6-R17] a model unknown receipt is terminal debt: no retry, no event/reducer replay, '
          'no seal, no new claim (receipt_conflict) and P6 stays blocked')


def test_external_missing_credentials(db):
    with tempfile.TemporaryDirectory() as tmp:
        chat, run_start = chat_only_agent(db)
        contract = owner_one(db, "SELECT input->'contract' FROM v24_cordis.effects WHERE id=%s",
                             (run_start,))
        source = source_for(run_start, contract, steps=3, directory=Path(tmp) / 'source')
        handler = Handler('model_final')
        m, ex, _ = make_maintainer(db, handler, drv.ReceiptJournal(Path(tmp) / 'journal'),
                                   source, actors=set(), lease_ms=300)
        with contextlib.closing(db.connect('owner')) as owner:
            before = snapshot(owner)
            owner.rollback()
        report = m.run_once()
        assert handler.calls == []
        assert any(d.get('driver') == 'blocked_actor_credential' for d in report.diagnostics)
        with contextlib.closing(db.connect('owner')) as owner:
            assert snapshot(owner) == before
            owner.rollback()
        assert effect_status(db, run_start) == 'ready'
        # A real but wrong LOGIN is rejected by session_user before advance.
        mapping = {db.roles['service']: db.roles['operator']}
        provider_obj = MappingProvider(db, {db.roles['service']}, mapping)
        executor = drv.Executor(actor_connect=provider_obj.actor,
                                observer_connect=provider_obj.observer,
                                handler=handler, journal=drv.ReceiptJournal(Path(tmp) / 'journal'),
                                run_requests=source, lease_ms=300)
        maintainer = drv.Maintainer(observer_connect=provider_obj.observer,
                                    actor_connect=provider_obj.actor,
                                    ensure_actor=db.roles['service'], executor=executor)
        report = maintainer.run_once()
        assert any(d.get('driver') == 'blocked_actor_credential' for d in report.diagnostics)
        assert effect_status(db, run_start) == 'ready'
        assert handler.calls == []
    print('[CDP6-R18] missing and wrong-real-LOGIN external credentials block before any claim; '
          'the ready effect and all ten tables stay unchanged')


def test_journal_corrupt_blocks(db):
    with tempfile.TemporaryDirectory() as tmp:
        chat, run_start = chat_only_agent(db)
        contract = owner_one(db, "SELECT input->'contract' FROM v24_cordis.effects WHERE id=%s",
                             (run_start,))
        source = source_for(run_start, contract, steps=3, directory=Path(tmp) / 'source')
        journal_dir = Path(tmp) / 'journal'
        journal = drv.ReceiptJournal(journal_dir)
        token = {'attempt': 1, 'fence': 1, 'owner': db.roles['service']}
        outcome = {'v': 1, 'class': 'success', 'claim': token,
                   'body': {'v': 1, 'request': {'text': 'x'}, 'steps': 3}}
        path = journal.record(run_start, db.roles['service'], token, outcome)
        body = json.loads(path.read_text())
        body['digest'] = 'f' * 64
        path.write_text(json.dumps(body))
        handler = Handler('model_final')
        m, ex, _ = make_maintainer(db, handler, journal, source, lease_ms=300)
        with contextlib.closing(db.connect('owner')) as owner:
            before = snapshot(owner)
            owner.rollback()
        report = m.run_once()
        assert any(d.get('driver') == 'journal_corrupt' for d in report.diagnostics)
        assert handler.calls == []
        with contextlib.closing(db.connect('owner')) as owner:
            assert snapshot(owner) == before
            owner.rollback()
        assert effect_status(db, run_start) == 'ready'
        # Conflicting duplicate journal entries for one token block instead of choosing.
        journal.confirm(path)
        valid = journal.record(run_start, db.roles['service'], token, outcome)
        alt = json.loads(valid.read_text())
        alt['outcome']['body']['steps'] = 9
        alt['digest'] = drv.sha256_hex({k: alt[k] for k in
                                        ('v', 'effect_id', 'actor', 'token', 'outcome')})
        dup = journal_dir / (str(run_start) + '.1.1.alt.json')
        dup.write_text(json.dumps(alt))
        report = m.run_once()
        assert any(d.get('driver') == 'journal_corrupt' for d in report.diagnostics)
        assert handler.calls == []
    print('[CDP6-R19] a torn/duplicate journal digest is an explicit block: no settlement, no '
          'handler, zero ten-table write; no receipt bytes are guessed')


def test_transaction_and_journal_discipline(db):
    with tempfile.TemporaryDirectory() as tmp:
        chat, run_start = chat_only_agent(db)
        contract = owner_one(db, "SELECT input->'contract' FROM v24_cordis.effects WHERE id=%s",
                             (run_start,))
        source = source_for(run_start, contract, steps=3, directory=Path(tmp) / 'source')
        handler = Handler('model_final')
        m, ex, provider_obj = make_maintainer(
            db, handler, drv.ReceiptJournal(Path(tmp) / 'journal'), source,
            lease_ms=500, tracking=True)
        for _ in range(3):
            m.run_once()
        assert handler.calls
        assert provider_obj.opened > 0
        closes = [entry for entry in provider_obj.log if entry[0] == 'close']
        assert len(closes) == provider_obj.opened, (len(closes), provider_obj.opened)
        assert all(entry[1] == TRANSACTION_STATUS_IDLE for entry in provider_obj.log
                   if entry[0] in ('commit', 'rollback', 'close')), provider_obj.log
        isolations = [entry[1] for entry in provider_obj.log if entry[0] == 'isolation']
        assert isolations and all(value == 'read committed' for value in isolations), isolations
        assert owner_one(db, 'SELECT count(*) FROM pg_stat_activity WHERE datname=%s '
                             'AND usename = ANY(%s)',
                         (db.name, [db.roles['observer'], db.roles['service']])) == 0
        assert owner_one(db, "SELECT count(*) FROM pg_stat_activity WHERE datname=%s "
                             "AND state LIKE 'idle in transaction%%'", (db.name,)) == 0
        binding_path = next((Path(tmp) / 'source' / 'bindings').glob('*.json'))
        assert oct(binding_path.stat().st_mode & 0o777) == '0o600'
        assert oct((Path(tmp) / 'source').stat().st_mode & 0o777) == '0o700'
        source_text = Path(drv.__file__).read_text().lower()
        for token in ('socket', 'threading', 'time.sleep'):
            assert token not in source_text, token
    print('[CDP6-R20] every claim/settle/replay connection closes IDLE, the handler sees zero open '
          'connections, no idle-in-transaction remains, journal/source files are 0600/0700 and '
          'the recovery driver opens no network or thread')


def dispatch_of_fiber(db, fiber):
    return owner_one(db, "SELECT id FROM v24_cordis.effects WHERE kind='dispatch' "
                          'AND fiber_id=%s', (fiber,))


def test_dispatch_half_complete_modes(db):
    root = root_fixture(db)
    for mode in ('emit', 'parallel', 'serial', 'bail', 'waterfall'):
        with tempfile.TemporaryDirectory() as tmp:
            scope, _ = fresh_scope(db, root)
            for i in range(3):
                listener_id = f'{mode}p{i}'
                if mode == 'bail' and i == 1:
                    listener_id = f'{mode}p{i}bail'
                _, _, result = dispatch_create(
                    db, scope, root['owner'],
                    listeners=[listener(listener_id, mode, 10 - i,
                                        {'type': 'host', 'capability': 'listener_call'})],
                    contracts={'listener_call': HOST})
                drain_ready(db, result)
            _, source_fiber, source_result = dispatch_create(db, scope, root['owner'])
            dispatch = dispatch_of_fiber(db, source_fiber)
            ready = [uuid.UUID(x['effect_id']) for x in source_result['ready_effects']]
            assert ready, (mode, source_result)
            first = ready[0]
            journal_dir = Path(tmp) / 'journal'
            calls = Path(tmp) / 'calls.jsonl'
            cfg = child_config(db, journal=journal_dir, handler='listener',
                               fault='settle_after_commit', fault_after=1,
                               fault_effect=first, calls=calls, lease_ms=500)
            crash_child(cfg)
            wait_backend_gone(db, db.roles['service'])
            assert effect_status(db, first) == 'succeeded', effect_row(db, first)
            assert len(journal_files(journal_dir)) == 1, journal_files(journal_dir)
            after_crash = {row[0]: row[1] for row in children(db, dispatch)}
            first_ordinal = owner_one(db, 'SELECT ordinal FROM v24_cordis.effects WHERE id=%s',
                                      (first,))
            assert after_crash[first_ordinal] == 'succeeded', after_crash
            handler = Handler('listener')
            m, ex, _ = make_maintainer(db, handler, drv.ReceiptJournal(journal_dir),
                                       None, lease_ms=500)
            for _ in range(12):
                m.run_once()
            rows_now = children(db, dispatch)
            expected_children = 2 if mode == 'bail' else 3
            assert len(rows_now) == expected_children, (mode, rows_now)
            assert all(row[1] == 'succeeded' for row in rows_now), (mode, rows_now)
            assert effect_status(db, dispatch) == 'succeeded', (mode, effect_row(db, dispatch))
            result = parent_result(db, dispatch)
            assert journal_files(journal_dir) == []
            if mode == 'emit':
                assert result['mode'] == 'emit' and len(result['generated']) == 3, result
            elif mode == 'parallel':
                assert result['joined'] == 3 and len(result['acc']) == 3, result
            elif mode == 'serial':
                assert result['joined'] == 3 and len(result['acc']) == 3, result
                assert result['bailed'] is False, result
            elif mode == 'bail':
                assert result['joined'] == 2 and result['bailed'] is True, result
            else:
                assert result['joined'] == 3, result
                assert result['acc']['seen_acc']['ordinal'] == 1, result
            first_calls = [json.loads(line) for line in calls.read_text().splitlines()]
            assert len(first_calls) == 1, first_calls
            assert all(call['open_connections'] == 0 for call in first_calls), first_calls
            assert len(handler.calls) == expected_children - 1, (mode, handler.calls)
    print('[CDP6-R21] all five dispatch modes are killed after the first committed child '
          'receipt; restart rebuilds progress only from child rows plus the journal, finds the '
          'next ready child (or the emit tail), seals once and never invents acc/next')


def test_dispatch_unknown_no_seal(db):
    with tempfile.TemporaryDirectory() as tmp:
        root = root_fixture(db)
        scope, _ = fresh_scope(db, root)
        for i in range(2):
            _, _, result = dispatch_create(
                db, scope, root['owner'],
                listeners=[listener(f'unknownp{i}', 'parallel', 10 - i,
                                    {'type': 'host', 'capability': 'listener_call'})],
                contracts={'listener_call': HOST})
            drain_ready(db, result)
        _, fiber, source_result = dispatch_create(db, scope, root['owner'])
        dispatch = dispatch_of_fiber(db, fiber)
        handler = Handler('unknown_first_listener')
        m, ex, _ = make_maintainer(db, handler, drv.ReceiptJournal(Path(tmp) / 'journal'),
                                   None, lease_ms=500)
        for _ in range(3):
            m.run_once()
        states = {row[0]: row[1] for row in children(db, dispatch)}
        assert states == {0: 'unknown', 1: 'succeeded'}, states
        assert parent_result(db, dispatch) is None
        assert effect_status(db, dispatch) == 'ready'
        assert len(progress_events(db, dispatch)) == 1
        calls = len(handler.calls)
        assert calls == 2, handler.calls
        with contextlib.closing(db.connect('owner')) as owner:
            before = snapshot(owner)
            owner.rollback()
        for _ in range(3):
            m.run_once()
        with contextlib.closing(db.connect('owner')) as owner:
            assert snapshot(owner) == before
            owner.rollback()
        assert len(handler.calls) == calls
        assert len(children(db, dispatch)) == 2
        assert parent_result(db, dispatch) is None
        control = enter_closing(db, fiber)
        plan = one(db, 'SELECT v24_cordis.p6_plan(NULL,%s)', (fiber,))
        assert plan.get('kind') == 'blocked_unknown', plan
    print('[CDP6-R22] an unknown listener child is not joined into acc and never causes a '
          'fabricated next child/seal; the dispatch stays ready as debt and P6 blocks')


def test_dispatch_settled_parent_invariant(db):
    fiber = uuid.uuid4()
    scope = uuid.uuid4()
    install_id = uuid.uuid4()
    dispatch = uuid.uuid4()
    owner_do(db, 'INSERT INTO v24_cordis.scopes(id) VALUES(%s)', (scope,))
    owner_do(db, "INSERT INTO v24_cordis.installs(id,scope_id,identity,version,manifest,"
                 "artifact_digest,contracts,state) VALUES(%s,%s,'inv','1',%s,%s,'{}','installed')",
             (install_id, scope, Json(dict(requires=[], provides=[], priority=0, check={})),
              'a' * 64))
    owner_do(db, 'SELECT pg_advisory_xact_lock(24,1)')
    owner_do(db, 'INSERT INTO v24_cordis.fibers(id,install_id,scope_id) VALUES(%s,%s,%s)',
             (fiber, install_id, scope))
    owner_do(db, "INSERT INTO v24_cordis.effects(id,kind,status,input,request_actor) "
                 "VALUES(%s,'dispatch','ready',%s,%s)",
             (dispatch, Json({'v': 1, 'listeners': [{'listener_id': 'a'},
                                                  {'listener_id': 'b'}]}),
              db.roles['service']))
    for ordinal in (0, 1):
        owner_do(db, "INSERT INTO v24_cordis.effects(id,parent_id,ordinal,kind,status,input,"
                     "request_actor,outcome,settled_at) VALUES(%s,%s,%s,'listener_call',"
                     "'succeeded','{}',%s,%s,now())",
                 (uuid.uuid4(), dispatch, ordinal, db.roles['service'],
                  Json({'v': 1, 'class': 'success', 'claim': None,
                        'body': {'kind': 'listener_call', 'result': {'value': {}}}})))
    handler = Handler('model_final')
    with tempfile.TemporaryDirectory() as tmp:
        m, ex, _ = make_maintainer(db, handler, drv.ReceiptJournal(Path(tmp) / 'journal'),
                                   None, lease_ms=300)
        with contextlib.closing(db.connect('owner')) as owner:
            before = snapshot(owner)
            owner.rollback()
        report = m.run_once()
        with contextlib.closing(db.connect('owner')) as owner:
            assert snapshot(owner) == before
            owner.rollback()
    assert handler.calls == []
    assert any(d.get('driver') == 'dispatch_unsettled_invariant' for d in report.diagnostics), \
        report.diagnostics
    assert effect_status(db, dispatch) == 'ready'
    assert parent_result(db, dispatch) is None
    print('[CDP6-R23] a dispatch whose trusted children are all terminal but whose parent is '
          'still ready is an invariant fault: zero write, no invented seal or acc')


def test_withdraw_drain_commit_lost(db):
    root = root_install(db)
    provider_payload = activate_teardown(db, root, provides=['drain-svc'])
    consumer_payload = activate_teardown(db, root, requires=['drain-svc'])
    pf = uuid.UUID(provider_payload['fiber_id'])
    cf = uuid.UUID(consumer_payload['fiber_id'])
    assert owner_one(db, 'SELECT count(*) FROM v24_cordis.pins WHERE consumer_fiber_id=%s',
                     (cf,)) == 1
    pcontrol = enter_closing(db, pf)
    peffect, pout, _ = p6_slot(db, pf, pcontrol)
    ccontrol = enter_closing(db, cf)
    ceffect, cout, _ = p6_slot(db, cf, ccontrol)
    parent = owner_one(db, 'SELECT parent_id FROM v24_cordis.effects WHERE id=%s', (ceffect,))
    payload = owner_one(db, 'SELECT input FROM v24_cordis.effects WHERE id=%s', (ceffect,))
    key = successor_key(parent)
    with tempfile.TemporaryDirectory() as tmp:
        cfg = child_config(db, journal=Path(tmp) / 'journal')
        cfg.update(mode='command', actor=db.roles['service'], effect=str(ceffect),
                   key=key, kind='command_reconcile', payload=payload,
                   fault='command_after_commit')
        crash_child(cfg)
        wait_backend_gone(db, db.roles['service'])
        assert effect_status(db, ceffect) == 'succeeded'
        assert owner_one(db, 'SELECT released_at IS NOT NULL FROM v24_cordis.pins '
                             'WHERE consumer_fiber_id=%s', (cf,)) is True
        assert owner_one(db, 'SELECT count(*) FROM v24_cordis.contributions c JOIN '
                             'v24_cordis.fibers f ON f.id=c.fiber_id WHERE f.id=%s '
                             'AND c.released_at IS NOT NULL', (pf,)) == 0
        assert effect_status(db, peffect) == 'ready'
        handler = Handler('model_final')
        m, ex, _ = make_maintainer(db, handler, drv.ReceiptJournal(Path(tmp) / 'journal'),
                                   None, lease_ms=300)
        for _ in range(14):
            m.run_once()
        assert owner_one(db, 'SELECT count(*) FROM v24_cordis.contributions c JOIN '
                             'v24_cordis.fibers f ON f.id=c.fiber_id WHERE f.id=%s '
                             'AND c.released_at IS NOT NULL', (pf,)) == 1
        assert owner_one(db, 'SELECT count(*) FROM v24_cordis.contributions c JOIN '
                             'v24_cordis.fibers f ON f.id=c.fiber_id WHERE f.id=%s '
                             'AND c.withdrawn_at IS NOT NULL AND c.released_at IS NOT NULL',
                         (pf,)) == 1
        assert owner_one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s',
                         (pf,)) is None
        assert owner_one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s',
                         (cf,)) is None
    print('[CDP6-R24] consumer pin release committed before the host saw the response; restart '
          'keeps the provider contribution until that pin fact is visible, then completes drain '
          'without early release or a second cleanup engine')


def test_dispose_commit_ack_lost(db):
    root = root_install(db)
    key = 'cordis/dp6/test/dispose/' + str(root['install_id']) + '/start'
    effect = derive(db.roles['service'], key, 'command_dispose')
    payload = {'install_id': str(root['install_id'])}
    with tempfile.TemporaryDirectory() as tmp:
        cfg = child_config(db, journal=Path(tmp) / 'journal')
        cfg.update(mode='command', actor=db.roles['service'], effect=str(effect), key=key,
                   kind='command_dispose', payload=payload, fault='command_after_commit')
        crash_child(cfg)
        wait_backend_gone(db, db.roles['service'])
        assert effect_status(db, effect) == 'succeeded'
        assert owner_one(db, 'SELECT state FROM v24_cordis.installs WHERE id=%s',
                         (root['install_id'],)) == 'dispose_pending'
        handler = Handler('model_final')
        m, ex, _ = make_maintainer(db, handler, drv.ReceiptJournal(Path(tmp) / 'journal'),
                                   None, lease_ms=300)
        for _ in range(8):
            m.run_once()
        assert owner_one(db, 'SELECT state FROM v24_cordis.installs WHERE id=%s',
                         (root['install_id'],)) == 'disposed'
        assert owner_one(db, 'SELECT disposed_at IS NOT NULL FROM v24_cordis.fibers '
                             'WHERE id=%s', (root['fiber_id'],)) is True
        assert effect_status(db, effect) == 'succeeded'
        assert owner_one(db, 'SELECT count(*) FROM v24_cordis.requests WHERE effect_id=%s',
                         (effect,)) == 1
        assert owner_one(db, 'SELECT count(*) FROM v24_cordis.effects WHERE '
                             "kind='command_dispose' AND input->>'install_id'=%s "
                             "AND status IN ('ready','claimed')",
                         (str(root['install_id']),)) == 0
        assert owner_one(db, 'SELECT count(*) FROM v24_cordis.effects WHERE '
                             "kind='command_reconcile' AND status='ready'") == 0
    print('[CDP6-R25] dispose COMMIT ack loss leaves the tombstone and original receipt; restart '
          'converges from committed facts, never re-activates or duplicates the dispose command')


def test_io_after_before_journal(db):
    with tempfile.TemporaryDirectory() as tmp:
        chat, run_start = chat_only_agent(db)
        contract = owner_one(db, "SELECT input->'contract' FROM v24_cordis.effects WHERE id=%s",
                             (run_start,))
        source_dir = Path(tmp) / 'source'
        source_for(run_start, contract, steps=3, directory=source_dir)
        calls = Path(tmp) / 'calls.jsonl'
        cfg = child_config(db, journal=Path(tmp) / 'journal', source=source_dir,
                           handler='model_final', fault='journal_before_write', calls=calls)
        crash_child(cfg)
        wait_backend_gone(db, db.roles['service'])
        row = effect_row(db, run_start)
        assert row[0] == 'claimed' and row[1] == 1 and row[2] == 1, row
        assert journal_files(Path(tmp) / 'journal') == []
        recorded = [json.loads(line) for line in calls.read_text().splitlines()]
        assert len(recorded) == 1 and recorded[0]['kind'] == 'run_start', recorded
        time.sleep(0.35)
        handler = Handler('model_final')
        m, ex, _ = make_maintainer(db, handler, drv.ReceiptJournal(Path(tmp) / 'journal'),
                                   drv.RunStartSource(source_dir), lease_ms=250)
        for _ in range(6):
            m.run_once()
        starts = [c for c in handler.calls if c['kind'] == 'run_start']
        assert len(starts) == 1 and starts[0]['fence'] == 2, starts
        assert effect_status(db, run_start) == 'succeeded'
    with tempfile.TemporaryDirectory() as tmp:
        # No replay rights: the unjournaled result stays a claimed debt, never a
        # fabricated success/failure.
        provider(db, 'model_call', 'no-replay-model')
        chat = agent_with_run_contract(db, (False, False), requires=('no-replay-model',))
        run_start, contract = chat['run_start'], chat['contract']
        source_dir = Path(tmp) / 'source'
        source_for(run_start, contract, steps=3, directory=source_dir)
        cfg = child_config(db, journal=Path(tmp) / 'journal', source=source_dir,
                           handler='model_final', fault='journal_before_write')
        crash_child(cfg)
        wait_backend_gone(db, db.roles['service'])
        assert effect_status(db, run_start) == 'claimed'
        time.sleep(0.35)
        handler = Handler('model_final')
        m, ex, _ = make_maintainer(db, handler, drv.ReceiptJournal(Path(tmp) / 'journal'),
                                   drv.RunStartSource(source_dir), lease_ms=250)
        with contextlib.closing(db.connect('owner')) as owner:
            before = snapshot(owner)
            owner.rollback()
        report = m.run_once()
        with contextlib.closing(db.connect('owner')) as owner:
            assert snapshot(owner) == before
            owner.rollback()
        assert handler.calls == []
        assert effect_status(db, run_start) == 'claimed'
        assert owner_one(db, 'SELECT count(*) FROM v24_cordis.runs WHERE owner_fiber_id=%s',
                         (chat['fiber'],)) == 0
        assert any(a['key'] == run_start and a['disposition'] == 'blocked_unknown'
                   for a in report.actions), report.actions
    print('[CDP6-R26] death after the adapter returns but before the journal fsync is treated as '
          'an unknown result: an explicit replay right re-executes under a new fence, while no '
          'right leaves the claimed token as debt and invents neither success nor failure')


def test_missing_replay_rights_and_digest(db):
    with tempfile.TemporaryDirectory() as tmp:
        # Production install refuses a missing replay object.  This explicit
        # fixture inserts the frozen declaration directly to prove claim reclaim
        # still reads it rather than assuming replayability.
        scope, install_id, fiber = (uuid.uuid4() for _ in range(3))
        owner_do(db, 'INSERT INTO v24_cordis.scopes(id) VALUES(%s)', (scope,))
        owner_do(db, "INSERT INTO v24_cordis.installs(id,scope_id,identity,version,manifest,"
                     "artifact_digest,contracts,state) VALUES(%s,%s,'noreplay','1',%s,%s,%s,"
                     "'installed')",
                 (install_id, scope,
                  Json(dict(requires=[], provides=[], priority=0, check={})), 'a' * 64,
                  Json({'host_io': {'contract_version': '1',
                                    'handler_digest': 'a' * 64}})))
        owner_do(db, 'INSERT INTO v24_cordis.fibers(id,install_id,scope_id) VALUES(%s,%s,%s)',
                 (fiber, install_id, scope))
        key = 'cordis/dp6/test/host-io/noreplay'
        effect = derive(db.roles['service'], key, 'host_io')
        owner_do(db, "INSERT INTO v24_cordis.effects(id,kind,status,fiber_id,input,request_actor)"
                     " VALUES(%s,'host_io','ready',%s,%s,%s)",
                 (effect, fiber,
                  Json({'v': 1, 'contract': {'contract_version': '1',
                                            'handler_digest': 'a' * 64}}),
                  db.roles['service']))
        _, ex, _ = make_maintainer(db, Handler(), drv.ReceiptJournal(Path(tmp) / 'journal'),
                                   None, lease_ms=250)
        first = ex._claim(db.roles['service'], effect)
        assert first['disposition'] == 'claimed', first
        time.sleep(0.35)
        with contextlib.closing(db.connect('owner')) as owner:
            before = snapshot(owner)
            owner.rollback()
        second = ex._claim(db.roles['service'], effect)
        assert second.get('error', {}).get('code') == 'blocked_unknown', second
        with contextlib.closing(db.connect('owner')) as owner:
            assert snapshot(owner) == before
            owner.rollback()
    print('[CDP6-R27] a frozen contract without replay rights blocks reclaim as blocked_unknown '
          'with zero write; it is never assumed replayable')


def test_digest_and_install_negatives(db):
    root = active_owner(db)
    for contract in (
            {'contract_version': '1', 'handler_digest': 'c' * 64},
            {'contract_version': '1', 'handler_digest': 'c' * 64,
             'replay': {'repeat': 'yes', 'concurrent': True}}):
        payload = install_payload(mode='existing', existing_scope=root['scope'],
                                  owner=dict(fiber_id=str(root['fiber']),
                                             episode_id=str(root['episode'])))
        payload['contracts'] = {'run_start': contract}
        with contextlib.closing(db.connect('owner')) as owner:
            before = snapshot(owner)
            owner.rollback()
        with contextlib.closing(db.connect('service')) as conn:
            effect, outcome = command(db, conn, 'service', 'command_install', payload)
            refused = api(conn, effect, outcome)
            conn.commit()
        assert refused.get('error', {}).get('code') == 'invalid_args', refused
        with contextlib.closing(db.connect('owner')) as owner:
            assert snapshot(owner) == before
            owner.rollback()
    # A direct frozen-declaration fixture (immutability triggers prevent editing
    # the production rows) proves the claim binding digest is revalidated.
    with tempfile.TemporaryDirectory() as tmp:
        scope, install_id, fiber = (uuid.uuid4() for _ in range(3))
        owner_do(db, "INSERT INTO v24_cordis.installs(id,scope_id,owner_fiber_id,"
                     "owner_episode_id,identity,version,manifest,artifact_digest,contracts,"
                     "state) VALUES(%s,%s,%s,%s,'digest','1',%s,%s,%s,'installed')",
                 (install_id, root['scope'], root['fiber'], root['episode'],
                  Json(dict(requires=[], provides=[], priority=0, check={})), 'a' * 64,
                  Json({'host_io': {'contract_version': '1',
                                    'handler_digest': 'a' * 64,
                                    'replay': {'repeat': True, 'concurrent': True}}})))
        owner_do(db, 'INSERT INTO v24_cordis.fibers(id,install_id,owner_id,'
                     'owner_episode_id,scope_id) VALUES(%s,%s,%s,%s,%s)',
                 (fiber, install_id, root['fiber'], root['episode'], root['scope']))
        key = 'cordis/dp6/test/host-io/digest'
        effect = derive(db.roles['service'], key, 'host_io')
        owner_do(db, "INSERT INTO v24_cordis.effects(id,kind,status,fiber_id,input,request_actor)"
                     " VALUES(%s,'host_io','ready',%s,%s,%s)",
                 (effect, fiber,
                  Json({'v': 1, 'contract': {'contract_version': '1',
                                            'handler_digest': 'd' * 64}}),
                  db.roles['service']))
        _, ex, _ = make_maintainer(db, Handler(), drv.ReceiptJournal(Path(tmp) / 'journal'),
                                   None, lease_ms=300)
        with contextlib.closing(db.connect('owner')) as owner:
            before = snapshot(owner)
            owner.rollback()
        refused = ex._claim(db.roles['service'], effect)
        with contextlib.closing(db.connect('owner')) as owner:
            assert snapshot(owner) == before
            owner.rollback()
        assert refused.get('error', {}).get('code') == 'invalid_args', refused
        assert effect_status(db, effect) == 'ready'
    print('[CDP6-R27b] a handler_digest mismatch is invalid_args before any claim and a '
          'production install with a missing replay object is invalid_args; both zero-write')


def test_install_precommit_rollback(db):
    root = root_install(db)
    episode = owner_one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s',
                        (root['fiber_id'],))
    payload = install_payload(mode='existing', existing_scope=root['scope']['id'],
                              owner=dict(fiber_id=str(root['fiber_id']),
                                         episode_id=str(episode)))
    payload['manifest'] = dict(requires=[], provides=[], priority=0, check={})
    install_id = uuid.UUID(payload['install_id'])
    key = 'cordis/dp6/test/child-install/' + payload['install_id'] + '/start'
    effect = derive(db.roles['service'], key, 'command_install')
    with tempfile.TemporaryDirectory() as tmp:
        cfg = child_config(db, journal=Path(tmp) / 'journal')
        cfg.update(mode='command', actor=db.roles['service'], effect=str(effect), key=key,
                   kind='command_install', payload=payload, fault='command_before_commit')
        crash_child(cfg)
        wait_backend_gone(db, db.roles['service'])
        assert owner_one(db, 'SELECT count(*) FROM v24_cordis.installs WHERE id=%s',
                         (install_id,)) == 0
        assert owner_one(db, 'SELECT count(*) FROM v24_cordis.fibers WHERE install_id=%s',
                         (install_id,)) == 0
        with contextlib.closing(db.connect('service')) as conn:
            e, o = command(db, conn, 'service', 'command_install', payload, key=key,
                           effect=effect)
            result = api(conn, e, o)
            conn.commit()
        assert result.get('disposition') == 'committed', result
        assert owner_one(db, 'SELECT count(*) FROM v24_cordis.installs WHERE id=%s',
                         (install_id,)) == 1
        assert owner_one(db, 'SELECT count(*) FROM v24_cordis.fibers WHERE install_id=%s',
                         (install_id,)) == 1
    print('[CDP6-R28] install/activation pre-COMMIT rollback leaves no install/fiber/contribution; '
          'the original request re-applies once to complete rows')


def main():
    if '--child-recovery' in sys.argv[1:]:
        _child_recovery()
        return
    with Server() as server:
        _SERVER['server'] = server
        with TestDB(server) as db:
            test_run_start_and_model(db)
        with TestDB(server) as db:
            test_claim_before_commit_rollback(db)
        with TestDB(server) as db:
            test_claim_commit_lost_then_reclaim(db)
        with TestDB(server) as db:
            test_io_during_kill(db)
        with TestDB(server) as db:
            test_journal_after_write_before_settle(db)
        with TestDB(server) as db:
            test_settle_before_commit_journal_replay(db)
        with TestDB(server) as db:
            test_settle_after_commit_response_lost(db)
        with TestDB(server) as db:
            test_receipt_replay_and_conflict(db)
        with TestDB(server) as db:
            test_terminal_immutable(db)
        with TestDB(server) as db:
            test_replay_matrix_and_fence(db)
        with TestDB(server) as db:
            test_concurrent_reclaim(db)
        with TestDB(server) as db:
            test_old_token_model_after_expiry(db)
        with TestDB(server) as db:
            test_run_start_source_negatives(db)
        with TestDB(server) as db:
            test_run_start_allocation_crash(db)
        with TestDB(server) as db:
            test_l_iter_batch_rollback_and_commit(db)
        with TestDB(server) as db:
            test_command_commit_lost_install(db)
        with TestDB(server) as db:
            test_unknown_external_debt(db)
        with TestDB(server) as db:
            test_external_missing_credentials(db)
        with TestDB(server) as db:
            test_journal_corrupt_blocks(db)
        with TestDB(server) as db:
            test_transaction_and_journal_discipline(db)
        with TestDB(server) as db:
            test_dispatch_half_complete_modes(db)
        with TestDB(server) as db:
            test_dispatch_unknown_no_seal(db)
        with TestDB(server) as db:
            test_dispatch_settled_parent_invariant(db)
        with TestDB(server) as db:
            test_withdraw_drain_commit_lost(db)
        with TestDB(server) as db:
            test_dispose_commit_ack_lost(db)
        with TestDB(server) as db:
            test_io_after_before_journal(db)
        with TestDB(server) as db:
            test_missing_replay_rights_and_digest(db)
        with TestDB(server) as db:
            test_digest_and_install_negatives(db)
        with TestDB(server) as db:
            test_install_precommit_rollback(db)
    print('[passed] CDP6-R')


if __name__ == '__main__':
    main()
