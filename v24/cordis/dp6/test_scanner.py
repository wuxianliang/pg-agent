"""CDP6-S: single-host fair rediscovery/maintenance scanner.

Run with: uv run python v24/cordis/dp6/test_scanner.py
Fake handlers only; no network. The gate uses a real observer LOGIN for reads and
real admin/service/operator LOGINs for `advance`.
"""
from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import psycopg2
from psycopg2.extensions import TRANSACTION_STATUS_IDLE
from psycopg2.extras import Json

CORDIS = Path(__file__).resolve().parents[1]
DP1 = CORDIS / 'dp1'
DP2 = CORDIS / 'dp2'
sys.path.insert(0, str(CORDIS))
sys.path.insert(0, str(DP1))
sys.path.insert(0, str(DP2))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from setup_db import Server, TestDB, TABLES, role_state  # noqa: E402
from test_support import (install_payload, reconcile_payload, command, api,  # noqa: E402
                          successor_key, query, sqlstate)
from test_ddl import snapshot  # noqa: E402
import driver as drv  # noqa: E402

CONTRACT = dict(contract_version='1', handler_digest='a' * 64,
                replay=dict(repeat=True, concurrent=False))
LOW = uuid.UUID('00000000-0000-0000-0000-0000000000aa')
HIGH = uuid.UUID('ffffffff-ffff-ffff-ffff-ffffffffffff')
LOW_OVERFLOW = uuid.UUID('00000000-0000-0000-0000-0000000000a0')
LOW_DEFERRED = uuid.UUID('00000000-0000-0000-0000-0000000000a1')
LOW_BLOCKED = uuid.UUID('00000000-0000-0000-0000-0000000000a2')
LOW_GHOST = uuid.UUID('00000000-0000-0000-0000-0000000000a3')
LOW_DISPOSE = uuid.UUID('00000000-0000-0000-0000-0000000000a4')


# ---------------------------------------------------------------- fixtures

def rows(conn, statement, params=()):
    with conn.cursor() as cur:
        cur.execute(statement, params) if params else cur.execute(statement)
        return cur.fetchall() if cur.description else None


def owner_rows(db, statement, params=()):
    with contextlib.closing(db.connect('owner')) as conn:
        got = rows(conn, statement, params)
        conn.rollback()
        return got


def owner_one(db, statement, params=()):
    return owner_rows(db, statement, params)[0][0]


def owner_do(db, statement, params=()):
    with contextlib.closing(db.connect('owner')) as conn:
        rows(conn, statement, params)
        conn.commit()


def snap(db):
    with contextlib.closing(db.connect('owner')) as conn:
        got = snapshot(conn)
        conn.rollback()
        return got


def commit(db, alias, kind, payload, key=None, effect=None):
    with contextlib.closing(db.connect(alias)) as conn:
        effect, outcome = command(db, conn, alias, kind, payload, key=key, effect=effect)
        result = api(conn, effect, outcome)
        assert result.get('disposition') == 'committed', result
        conn.commit()
        return effect, result


def install_fiber(db, *, provides=(), requires=(), owner=None, mode='root', existing=None,
                  fiber_id=None, install_id=None):
    payload = install_payload(mode=mode, owner=owner, existing_scope=existing)
    if fiber_id is not None:
        payload['fiber_id'] = str(fiber_id)
    if install_id is not None:
        payload['install_id'] = str(install_id)
    payload['manifest'] = dict(
        requires=list(requires),
        provides=[dict(key=k, descriptor=dict(capability='cap'), contract_version='1')
                  for k in provides],
        priority=0, check={})
    payload['contracts'] = {'cap': CONTRACT} if provides else {}
    effect, result = commit(db, 'service', 'command_install', payload)
    return payload, effect, result


class Fixture:
    """One active root anchor; every other fixture fiber is a child of it."""

    def __init__(self, db):
        payload, _, _ = install_fiber(db, mode='root')
        fiber = uuid.UUID(payload['fiber_id'])
        activate(db, fiber)
        episode = owner_one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s',
                            (fiber,))
        self.db = db
        self.root = payload
        self.scope = payload['scope']['id']
        self.owner = {'fiber_id': payload['fiber_id'], 'episode_id': str(episode)}

    def install(self, **kwargs):
        kwargs.setdefault('owner', self.owner)
        kwargs.setdefault('mode', 'existing')
        kwargs.setdefault('existing', self.scope)
        return install_fiber(self.db, **kwargs)


def child_input(db, child):
    return owner_one(db, 'SELECT input FROM v24_cordis.effects WHERE id=%s', (child,))


def advance_child(db, parent, result, alias='service'):
    child = result['emitted'][0]
    return child, commit(db, alias, 'command_reconcile', child_input(db, child),
                         key=successor_key(parent), effect=child)[1]


def advance_raw(db, child, alias='service'):
    """Drive one ready continuation without asserting its disposition or committing."""
    with contextlib.closing(db.connect(alias)) as conn:
        parent = owner_one(db, 'SELECT parent_id FROM v24_cordis.effects WHERE id=%s', (child,))
        effect, outcome = command(db, conn, alias, 'command_reconcile', child_input(db, child),
                                  key=successor_key(parent), effect=child)
        result = api(conn, effect, outcome)
        conn.commit()
        return result


def activate(db, fiber, provides=()):
    effect, result = commit(db, 'service', 'command_reconcile',
                            reconcile_payload(fiber, 'on', 0))
    while result.get('emitted'):
        effect, result = advance_child(db, effect, result)
    assert result['emitted'] == [], result
    assert owner_one(db, 'SELECT state FROM v24_cordis.episodes WHERE fiber_id=%s '
                         'AND closed_at IS NULL', (fiber,)) == 'active'
    return effect, result


def closing(db, fiber, expected=1):
    effect, result = commit(db, 'service', 'command_reconcile',
                            reconcile_payload(fiber, 'off', expected))
    assert result['emitted'], result
    effect, result = advance_child(db, effect, result)
    assert result['emitted'] == [], result
    assert owner_one(db, 'SELECT state FROM v24_cordis.episodes WHERE fiber_id=%s '
                         'AND closed_at IS NULL', (fiber,)) == 'closing'
    return expected + 1


def closing_slot(db, fiber, expected=1):
    """Close-start a fiber, then use production ensure to leave its next continuation ready."""
    control = closing(db, fiber, expected)
    m, _ = _maintainer(db)
    work = m.ensure(fiber, control)
    assert work.get('disposition') == 'committed' and len(work['emitted']) == 1, work
    return control, uuid.UUID(work['emitted'][0])


def fiber_row(db, fiber):
    return owner_rows(db, 'SELECT want_on,control_seq,current_episode_id,failure,'
                          'retire_started_at,disposed_at FROM v24_cordis.fibers WHERE id=%s',
                      (fiber,))[0]


def expect_fault(fn, reason):
    try:
        fn()
    except psycopg2.Error as exc:
        assert exc.pgcode == '0A000', (exc.pgcode, str(exc))
        assert reason in str(exc), str(exc)
    else:
        raise AssertionError('expected invariant fault ' + reason)


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


class FakeHandler:
    def __init__(self):
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        raise AssertionError('W1 must not invoke an external handler')


class TrackingConnection:
    """Record the transaction status at every commit/rollback/close."""

    def __init__(self, conn, log):
        self._conn = conn
        self._log = log
        self._closed = False

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def commit(self):
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
    """Resolve a configured actor login to a different real LOGIN (no impersonation)."""

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


# ---------------------------------------------------------------- CDP6-S7 ACL

def test_acl(db):
    observer = db.roles['observer']
    group = db.groups['observer']
    state = role_state(db.admin, observer)
    assert state[1:6] == (False, False, False, False, False), state
    assert state[6:] == (True, True), state
    gstate = role_state(db.admin, group)
    assert gstate[1:6] == (False, False, False, False, False), gstate
    assert gstate[6:] == (False, False), gstate
    update_column = {'fibers': 'want_on', 'episodes': 'state', 'effects': 'status',
                     'installs': 'state', 'requests': 'request_key', 'runs': 'ended_at',
                     'contributions': 'kind', 'pins': 'key', 'events': 'seq',
                     'scopes': 'closed_at'}
    with contextlib.closing(db.connect('owner')) as owner, owner.cursor() as cur:
        cur.execute('SELECT roleid FROM pg_auth_members WHERE member=%s', (state[0],))
        assert [r[0] for r in cur.fetchall()] == [gstate[0]]
        for table in TABLES:
            cur.execute('SELECT has_table_privilege(%s,%s,%s)',
                        (observer, 'v24_cordis.' + table, 'SELECT'))
            assert cur.fetchone()[0] is False, table
        cur.execute('SELECT has_column_privilege(%s,%s,%s,%s)',
                    (observer, 'v24_cordis.episodes', 'state', 'SELECT'))
        assert cur.fetchone()[0] is True
        cur.execute('SELECT has_column_privilege(%s,%s,%s,%s)',
                    (observer, 'v24_cordis.episodes', 'committed_view', 'SELECT'))
        assert cur.fetchone()[0] is False
        cur.execute('SELECT has_function_privilege(%s,%s,%s)',
                    (observer, 'v24_cordis.advance(uuid,jsonb)', 'EXECUTE'))
        assert cur.fetchone()[0] is False
        cur.execute("SELECT has_database_privilege(%s,current_database(),'TEMP')", (observer,))
        assert cur.fetchone()[0] is False
        for alias in ('owner', 'admin', 'service', 'operator'):
            cur.execute("SELECT has_database_privilege(%s,current_database(),'TEMP')",
                        (db.roles[alias],))
            assert cur.fetchone()[0] is True, alias
        cur.execute("SELECT count(*) FROM pg_proc WHERE pronamespace='v24_cordis'::regnamespace "
                    'AND prosecdef')
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT count(*) FROM pg_proc p WHERE p.pronamespace='v24_cordis'::regnamespace "
                    "AND EXISTS(SELECT 1 FROM aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a "
                    "WHERE a.grantee=0 AND a.privilege_type='EXECUTE')")
        assert cur.fetchone()[0] == 0
        for cls in ('command', 'claim', 'success', 'failure', 'unknown'):
            for kind in ('command_install', 'command_reconcile', 'command_dispose',
                         'host_io', 'run_start', 'model_call', 'tool_call', 'listener_call'):
                cur.execute('SELECT v24_cordis.role_allowed(%s,%s,%s,%s)',
                            (observer, cls, kind, 'admit_and_apply' if cls == 'command' else cls))
                assert cur.fetchone()[0] is False, (cls, kind)
    allow = {
        'fibers': 'id,install_id,owner_id,owner_episode_id,scope_id,want_on,control_seq,'
                  'current_episode_id,failure,retire_started_at,dispose_requested_at,disposed_at',
        'episodes': 'id,fiber_id,epoch,state,closed_at',
        'effects': 'id,parent_id,ordinal,fiber_id,episode_id,run_id,kind,status,input,'
                   'request_actor,attempt,fence,claim_owner,lease_until,outcome,settled_at',
        'installs': 'id,scope_id,owner_fiber_id,owner_episode_id,identity,version,'
                    'artifact_digest,state',
        'requests': 'principal_id,request_key,request_bytes,request_digest,effect_id,response',
        'runs': 'id,owner_fiber_id,owner_episode_id,ended_at',
        'contributions': 'id,fiber_id,episode_id,kind,realm,key,inverse,withdrawn_at,released_at',
        'pins': 'id,consumer_fiber_id,consumer_episode_id,consumer_run_id,contribution_id,released_at',
    }
    with contextlib.closing(db.connect('observer')) as conn:
        assert rows(conn, 'SELECT session_user')[0][0] == observer
        for table, cols in allow.items():
            rows(conn, f'SELECT {cols} FROM v24_cordis.{table} LIMIT 0')
        for table, col in (('episodes', 'committed_view'), ('installs', 'manifest'),
                           ('runs', 'scope_id'), ('contributions', 'descriptor'),
                           ('pins', 'key'), ('events', 'event_id')):
            sqlstate(conn, f'SELECT {col} FROM v24_cordis.{table} LIMIT 0', code='42501')
        for table in TABLES:
            sqlstate(conn, f'INSERT INTO v24_cordis.{table} DEFAULT VALUES', code='42501')
            sqlstate(conn, f'UPDATE v24_cordis.{table} SET {update_column[table]}='
                           f'{update_column[table]} WHERE false', code='42501')
            sqlstate(conn, f'DELETE FROM v24_cordis.{table} WHERE false', code='42501')
            sqlstate(conn, f'TRUNCATE v24_cordis.{table}', code='42501')
        sqlstate(conn, "SELECT v24_cordis.advance(gen_random_uuid(),'{}'::jsonb)", code='42501')
        sqlstate(conn, 'CREATE TEMP TABLE cordis_temp_probe(x int)', code='42501')
        sqlstate(conn, 'CREATE TABLE v24_cordis.cordis_probe(x int)', code='42501')
        sqlstate(conn, f'SET ROLE {db.groups["admin"]}', code='42501')
    print('[CDP6-S7] observer LOGIN: column-only SELECT, no table SELECT/DML/EXECUTE/TEMP/CREATE, '
          'single DEFINER and public EXECUTE 0')


# ------------------------------------------------------- fixture lifecycle

def test_fixture_lifecycle(server):
    with TestDB(server) as tmp:
        name, obs, group = tmp.name, tmp.roles['observer'], tmp.groups['observer']
        with contextlib.closing(tmp.connect('observer')) as conn:
            assert rows(conn, 'SELECT session_user')[0][0] == obs
    with contextlib.closing(server.connect()) as admin:
        assert rows(admin, 'SELECT rolname FROM pg_roles WHERE rolname=%s', (obs,)) == []
        assert rows(admin, 'SELECT rolname FROM pg_roles WHERE rolname=%s', (group,)) == []
        assert rows(admin, 'SELECT datname FROM pg_database WHERE datname=%s', (name,)) == []
    print('[CDP6-S1f] observer LOGIN/group and database are created and exactly removed by the fixture')


# ------------------------------------------------------- ensure semantics

def test_ensure_work_and_failure(db):
    fx = Fixture(db)
    payload, _, _ = fx.install()
    fiber = uuid.UUID(payload['fiber_id'])
    activate(db, fiber)
    control = closing(db, fiber, 1)
    provider = Provider(db, {db.roles['service']})
    m = drv.Maintainer(observer_connect=provider.observer, actor_connect=provider.actor,
                       ensure_actor=db.roles['service'])
    work = m.ensure(fiber, control)
    assert work.get('disposition') == 'committed' and len(work['emitted']) == 1, work
    assert owner_one(db, 'SELECT state FROM v24_cordis.episodes WHERE fiber_id=%s '
                         'AND closed_at IS NULL', (fiber,)) == 'closing'
    commit(db, 'service', 'command_reconcile', child_input(db, work['emitted'][0]),
           key=successor_key(work['effect_id']), effect=work['emitted'][0])
    closed = fiber_row(db, fiber)
    assert closed[2] is None and closed[4] is None, closed
    before = snap(db)
    quiet = m.ensure(fiber, closed[1])
    assert quiet['error']['code'] == 'stale_generation'
    assert quiet['error']['detail']['reason'] == 'ensure_no_work', quiet
    assert snap(db) == before
    before = snap(db)
    slot = m.ensure(fiber, control - 1)
    assert slot['error']['code'] == 'stale_generation'
    assert slot['error']['detail']['reason'] == 'reconcile_generation', slot
    assert snap(db) == before

    # Same-generation activation failure: a second provider for the same address.
    payload_a, _, _ = fx.install(provides=['dup'])
    fiber_a = uuid.UUID(payload_a['fiber_id'])
    activate(db, fiber_a, provides=['dup'])
    episode_a = owner_one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s',
                          (fiber_a,))
    payload_b, _, _ = fx.install(provides=['dup'], owner=dict(
        fiber_id=str(fiber_a), episode_id=str(episode_a)))
    fiber_b = uuid.UUID(payload_b['fiber_id'])
    effect, result = commit(db, 'service', 'command_reconcile', reconcile_payload(fiber_b, 'on', 0))
    while result.get('emitted'):
        effect, result = advance_child(db, effect, result)
    failed = fiber_row(db, fiber_b)
    assert failed[3] is not None and failed[3]['control_seq'] == failed[1], failed
    assert owner_one(db, 'SELECT state FROM v24_cordis.episodes WHERE fiber_id=%s '
                         'AND closed_at IS NULL', (fiber_b,)) == 'closing'
    # Failure must not suppress the already-started teardown.
    teardown = m.ensure(fiber_b, failed[1])
    assert teardown.get('disposition') == 'committed', teardown
    commit(db, 'service', 'command_reconcile', child_input(db, teardown['emitted'][0]),
           key=successor_key(teardown['effect_id']), effect=teardown['emitted'][0])
    closed_b = fiber_row(db, fiber_b)
    assert closed_b[2] is None and closed_b[4] is None, closed_b
    suppressed = m.ensure(fiber_b, closed_b[1])
    assert suppressed['error']['code'] == 'stale_generation'
    assert suppressed['error']['detail']['reason'] == 'ensure_failure_suppressed', suppressed
    assert owner_one(db, "SELECT count(*) FROM v24_cordis.effects WHERE fiber_id=%s "
                         "AND input->>'action'='ensure'", (fiber_b,)) == 1
    print('[CDP6-S2] ensure quiet/stale/work, teardown-before-failure and '
          'same-generation failure suppression')


def test_invariants(db):
    fx = Fixture(db)
    provider = Provider(db, {db.roles['service']})
    m = drv.Maintainer(observer_connect=provider.observer, actor_connect=provider.actor,
                       ensure_actor=db.roles['service'])

    payload, _, _ = fx.install()
    fiber = uuid.UUID(payload['fiber_id'])
    on_effect, on_result = commit(db, 'service', 'command_reconcile',
                                  reconcile_payload(fiber, 'on', 0))
    owner_do(db, 'DELETE FROM v24_cordis.effects WHERE id=%s', (on_result['emitted'][0],))
    before = snap(db)
    expect_fault(lambda: m.ensure(fiber, 1), 'missing_reconcile_successor')
    assert snap(db) == before

    payload, _, _ = fx.install()
    fiber = uuid.UUID(payload['fiber_id'])
    on_effect, on_result = commit(db, 'service', 'command_reconcile',
                                  reconcile_payload(fiber, 'on', 0))
    p1_effect, p1_result = advance_child(db, on_effect, on_result)
    owner_do(db, 'DELETE FROM v24_cordis.effects WHERE id=%s', (p1_result['emitted'][0],))
    before = snap(db)
    expect_fault(lambda: m.ensure(fiber, 1), 'missing_reconcile_successor')
    assert snap(db) == before

    payload, _, _ = fx.install(provides=['rel'])
    fiber = uuid.UUID(payload['fiber_id'])
    activate(db, fiber, provides=['rel'])
    control = closing(db, fiber, 1)
    work = m.ensure(fiber, control)
    assert work.get('disposition') == 'committed', work
    p6 = commit(db, 'service', 'command_reconcile', child_input(db, work['emitted'][0]),
                key=successor_key(work['effect_id']), effect=work['emitted'][0])[1]
    assert p6['emitted'], p6
    owner_do(db, 'DELETE FROM v24_cordis.effects WHERE id=%s', (p6['emitted'][0],))
    before = snap(db)
    expect_fault(lambda: m.ensure(fiber, control), 'missing_reconcile_successor')
    assert snap(db) == before

    payload, _, _ = fx.install()
    fiber = uuid.UUID(payload['fiber_id'])
    owner_do(db, 'UPDATE v24_cordis.fibers SET retire_started_at=clock_timestamp() '
                 'WHERE id=%s', (fiber,))
    before = snap(db)
    expect_fault(lambda: m.ensure(fiber, 0), 'phase_drift')
    assert snap(db) == before
    print('[CDP6-S3] emitted-missing, reloading-no-slot, closing-release and '
          'retire-without-episode are 0A000 faults with zero write')


def test_dispose_missing_successor(db):
    """The command_dispose half of the Oracle missing-successor invariant."""
    fx = Fixture(db)
    m, handler = _maintainer(db)

    # fiber_requested: a want_on fiber's dispose step emits a reconcile successor.
    payload, _, _ = fx.install()
    fiber_requested = uuid.UUID(payload['fiber_id'])
    activate(db, fiber_requested)
    install = uuid.UUID(payload['install_id'])
    commit(db, 'service', 'command_dispose', dict(install_id=str(install)))
    effect, result = commit(db, 'service', 'command_dispose', dict(install_id=str(install)))
    assert result.get('emitted'), result
    requested_child = uuid.UUID(result['emitted'][0])
    requested_seq = owner_one(db, 'SELECT control_seq FROM v24_cordis.fibers WHERE id=%s',
                              (fiber_requested,))
    phase = owner_one(db, "SELECT payload->>'phase' FROM v24_cordis.events "
                          "WHERE effect_id=%s AND event_kind='install_dispose_progress'", (effect,))
    assert phase == 'fiber_requested', phase
    owner_do(db, 'DELETE FROM v24_cordis.effects WHERE id=%s', (requested_child,))
    before = snap(db)
    expect_fault(lambda: m.ensure(fiber_requested, requested_seq), 'missing_reconcile_successor')
    assert snap(db) == before

    # work_scheduled: a closing fiber's dispose step emits the same successor obligation.
    payload, _, _ = fx.install()
    work_fiber = uuid.UUID(payload['fiber_id'])
    activate(db, work_fiber)
    closing(db, work_fiber, 1)
    install = uuid.UUID(payload['install_id'])
    commit(db, 'service', 'command_dispose', dict(install_id=str(install)))
    effect, result = commit(db, 'service', 'command_dispose', dict(install_id=str(install)))
    assert result.get('emitted'), result
    scheduled_child = uuid.UUID(result['emitted'][0])
    scheduled_seq = owner_one(db, 'SELECT control_seq FROM v24_cordis.fibers WHERE id=%s',
                              (work_fiber,))
    phase = owner_one(db, "SELECT payload->>'phase' FROM v24_cordis.events "
                          "WHERE effect_id=%s AND event_kind='install_dispose_progress'", (effect,))
    assert phase == 'work_scheduled', phase
    owner_do(db, 'DELETE FROM v24_cordis.effects WHERE id=%s', (scheduled_child,))
    before = snap(db)
    expect_fault(lambda: m.ensure(work_fiber, scheduled_seq), 'missing_reconcile_successor')
    assert snap(db) == before

    # Negative control 1: an intact dispose parent for a different fiber is not a fault.
    payload, _, _ = fx.install()
    intact = uuid.UUID(payload['fiber_id'])
    activate(db, intact)
    install = uuid.UUID(payload['install_id'])
    commit(db, 'service', 'command_dispose', dict(install_id=str(install)))
    effect, result = commit(db, 'service', 'command_dispose', dict(install_id=str(install)))
    assert result.get('emitted'), result
    intact_seq = owner_one(db, 'SELECT control_seq FROM v24_cordis.fibers WHERE id=%s', (intact,))
    before = snap(db)
    intact_result = m.ensure(intact, intact_seq)
    assert intact_result.get('error', {}).get('code') != 'missing_reconcile_successor', intact_result
    assert intact_result['error']['detail']['reason'] == 'ensure_slot_present', intact_result
    assert snap(db) == before

    # Negative control 2: an unrelated healthy fiber does not inherit either damaged
    # dispose parent's obligation and still returns a normal zero-write no-work result.
    payload, _, _ = fx.install()
    healthy = uuid.UUID(payload['fiber_id'])
    activate(db, healthy)
    before = snap(db)
    quiet = m.ensure(healthy, 1)
    assert quiet.get('error', {}).get('detail', {}).get('reason') == 'ensure_no_work', quiet
    assert snap(db) == before
    assert handler.calls == []
    print('[CDP6-S3b] command_dispose fiber_requested/work_scheduled missing successors are '
          '0A000 faults with zero write; unrelated dispatches do not false-positive')


def test_live_change(db):
    fx = Fixture(db)
    provider_payload, _, _ = fx.install(provides=['live-svc'])
    provider_fiber = uuid.UUID(provider_payload['fiber_id'])
    activate(db, provider_fiber, provides=['live-svc'])
    consumer_payload, _, _ = fx.install(requires=['live-svc'])
    consumer = uuid.UUID(consumer_payload['fiber_id'])
    activate(db, consumer)
    m, handler = _maintainer(db)
    before = snap(db)
    quiet = m.ensure(consumer, 1)
    assert quiet['error']['detail']['reason'] == 'ensure_no_work', quiet
    assert snap(db) == before
    # Withdraw the provider at the consumer's unchanged control_seq.
    closing(db, provider_fiber, 1)
    work = m.ensure(consumer, 1)
    assert work.get('disposition') == 'committed', work
    commit(db, 'service', 'command_reconcile', child_input(db, work['emitted'][0]),
           key=successor_key(work['effect_id']), effect=work['emitted'][0])
    assert owner_one(db, 'SELECT state FROM v24_cordis.episodes WHERE fiber_id=%s '
                         'AND closed_at IS NULL', (consumer,)) == 'closing'
    for _ in range(8):
        if _closed(db, consumer):
            break
        m.run_once()
    assert _closed(db, consumer)
    for _ in range(6):
        if _closed(db, provider_fiber):
            break
        m.run_once()
    assert _closed(db, provider_fiber)
    for _ in range(3):
        before = snap(db)
        m.run_once()
        assert snap(db) == before
    assert handler.calls == []
    print('[CDP6-S11] provider withdrawal wakes the consumer at unchanged control_seq; '
          'repeated quiet scans are ten-table zero-growth')


def test_replay_and_concurrency(db):
    fx = Fixture(db)
    payload, _, _ = fx.install()
    fiber = uuid.UUID(payload['fiber_id'])
    activate(db, fiber)
    control = closing(db, fiber, 1)
    provider = Provider(db, {db.roles['service']})
    m = drv.Maintainer(observer_connect=provider.observer, actor_connect=provider.actor,
                       ensure_actor=db.roles['service'])
    key = 'cordis/dp6/ensure/' + str(fiber) + '/fixed'
    first = m.ensure(fiber, control, key=key)
    assert first.get('disposition') == 'committed', first
    second = m.ensure(fiber, control, key=key)
    assert second == first, (second, first)
    assert owner_one(db, 'SELECT count(*) FROM v24_cordis.requests WHERE request_key=%s',
                     (key,)) == 1
    conflict = m.ensure(fiber, control + 1, key=key)
    assert conflict['error']['code'] == 'request_conflict', conflict

    payload, _, _ = fx.install()
    fiber2 = uuid.UUID(payload['fiber_id'])
    activate(db, fiber2)
    control2 = closing(db, fiber2, 1)
    barrier = threading.Barrier(2)
    results = []

    def race():
        barrier.wait()
        results.append(m.ensure(fiber2, control2))

    threads = [threading.Thread(target=race) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    dispositions = sorted(
        r.get('disposition', r.get('error', {}).get('detail', {}).get('reason'))
        for r in results)
    assert dispositions == ['committed', 'ensure_slot_present'], results
    assert owner_one(db, "SELECT count(*) FROM v24_cordis.effects WHERE fiber_id=%s "
                         "AND input->>'action'='ensure'", (fiber2,)) == 1
    print('[CDP6-S4] ensure replay-first, conflicting bytes, and concurrent unique slot')


# ------------------------------------------- raw row replay/revalidation

def test_raw_row_injection(db):
    """Deliver duplicate, out-of-order and stale observer rows to the item handlers."""
    fx = Fixture(db)
    m, handler = _maintainer(db, page=64)
    fibers = []
    continuations = []
    for _ in range(2):
        payload, _, _ = fx.install()
        fiber = uuid.UUID(payload['fiber_id'])
        activate(db, fiber)
        control = closing(db, fiber, 1)
        work = m.ensure(fiber, control)
        assert work.get('disposition') == 'committed', work
        fibers.append(fiber)
        continuations.append(uuid.UUID(work['emitted'][0]))
    sql = ("SELECT id,parent_id,ordinal,fiber_id,input,request_actor "
           "FROM v24_cordis.effects WHERE kind='command_reconcile' AND status='ready' "
           'AND id>%s ORDER BY id LIMIT %s')
    with contextlib.closing(db.connect('observer')) as conn:
        page = rows(conn, sql, (uuid.UUID(int=0), 64))
        conn.rollback()
    by_effect = {r[0]: r for r in page}
    first_row, second_row = by_effect[continuations[0]], by_effect[continuations[1]]

    # Out of order: the later key is advanced before the earlier one.
    later = m._command(second_row)
    earlier = m._command(first_row)
    assert later.get('disposition') == 'committed', later
    assert earlier.get('disposition') == 'committed', earlier
    for fiber in fibers:
        assert _closed(db, fiber), fiber

    # Duplicate delivery of the same stale raw row is replay-first: no new request/effect.
    before = snap(db)
    duplicate = m._command(first_row)
    assert duplicate == earlier, (duplicate, earlier)
    assert snap(db) == before
    assert owner_one(db, 'SELECT count(*) FROM v24_cordis.requests WHERE request_key=%s',
                     (successor_key(first_row[1], first_row[2]),)) == 1
    assert owner_one(db, 'SELECT count(*) FROM v24_cordis.effects WHERE id=%s',
                     (drv.successor_effect_id(db.roles['service'], first_row[1],
                                              first_row[2]),)) == 1

    # A stale row whose effect already succeeded replays the cached response, not a second apply.
    before = snap(db)
    stale = m._command(first_row)
    assert stale == earlier, (stale, earlier)
    assert snap(db) == before

    # Stale fiber row: advance re-checks expected_control_seq and writes nothing.
    payload, _, _ = fx.install()
    fiber = uuid.UUID(payload['fiber_id'])
    activate(db, fiber)
    stale_row = (fiber, 1)
    closing(db, fiber, 1)
    before = snap(db)
    stale_fiber = m._fiber(stale_row)
    assert stale_fiber['error']['code'] == 'stale_generation', stale_fiber
    assert stale_fiber['error']['detail']['reason'] == 'reconcile_generation', stale_fiber
    assert snap(db) == before
    assert handler.calls == []
    print('[CDP6-S12] duplicate/out-of-order/stale rows revalidate in advance; replay adds no '
          'request/effect and stale fiber state is zero-write')


# ------------------------------------------------------- scanner paging

def _maintainer(db, page=4):
    provider = Provider(db, {db.roles['service']})
    handler = FakeHandler()
    return drv.Maintainer(observer_connect=provider.observer, actor_connect=provider.actor,
                          ensure_actor=db.roles['service'], page_size=page,
                          handler=handler), handler


def _closed(db, fiber):
    return owner_one(db, 'SELECT count(*) FROM v24_cordis.episodes WHERE fiber_id=%s '
                         'AND closed_at IS NULL', (fiber,)) == 0


def test_scanner_paging_fibers(db):
    fx = Fixture(db)
    fibers = []
    for _ in range(6):
        payload, _, _ = fx.install()
        fiber = uuid.UUID(payload['fiber_id'])
        activate(db, fiber)
        closing(db, fiber, 1)
        fibers.append(fiber)
    m, handler = _maintainer(db, page=2)
    reports = []
    # Advance the per-topic keyset cursor past the first page before inserting keys
    # both before and after it; the next bounded wrap must discover both.
    for _ in range(2):
        reports.append(m.run_once())
    fiber_topic = next(t for t in m.topics if t.name == 'fibers')
    assert fiber_topic.cursor != uuid.UUID(int=0), 'cursor did not advance before insertion'
    fx.install(fiber_id=LOW)
    activate(db, LOW)
    closing(db, LOW, 1)
    fx.install(fiber_id=HIGH)
    activate(db, HIGH)
    closing(db, HIGH, 1)
    inserted = {LOW, HIGH}
    for _ in range(12):
        reports.append(m.run_once())
        if all(_closed(db, fiber) for fiber in list(fibers) + [LOW, HIGH]):
            break
    for fiber in list(fibers) + [LOW, HIGH]:
        assert _closed(db, fiber), fiber
    visited = {a['key'] for a in sum((r.actions for r in reports), []) if a['topic'] == 'fibers'}
    live = {r[0] for r in owner_rows(db, 'SELECT id FROM v24_cordis.fibers WHERE disposed_at IS NULL')}
    assert live <= visited, (live - visited)
    assert inserted <= visited, (inserted - visited)
    first_seen = {key: i for i, report in enumerate(reports)
                  for key in ({a['key'] for a in report.actions if a['topic'] == 'fibers'} & inserted)}
    assert all(first_seen[key] <= 8 for key in inserted), first_seen
    assert handler.calls == []
    print('[CDP6-S5a] >page closing fibers; keys inserted before and after the advanced cursor are '
          'rediscovered within bounded wraps')


def test_scanner_paging_commands(db):
    fx = Fixture(db)
    pending = []
    fibers = []
    for _ in range(6):
        payload, _, _ = fx.install()
        fiber = uuid.UUID(payload['fiber_id'])
        effect, result = commit(db, 'service', 'command_reconcile',
                                reconcile_payload(fiber, 'on', 0))
        assert result['emitted'], result
        pending.append(uuid.UUID(result['emitted'][0]))
        fibers.append(fiber)
    m, handler = _maintainer(db)
    handled = set()
    for _ in range(30):
        report = m.run_once()
        handled |= {a['key'] for a in report.actions if a['topic'] == 'commands'
                    and a['disposition'] == 'committed'}
        active = all(owner_one(db, "SELECT coalesce((SELECT state FROM v24_cordis.episodes "
                                     "WHERE fiber_id=%s AND closed_at IS NULL),'none')", (f,)) == 'active'
                     for f in fibers)
        if set(pending) <= handled and active:
            break
    assert set(pending) <= handled, (set(pending) - handled)
    for fiber in fibers:
        assert owner_one(db, "SELECT coalesce((SELECT state FROM v24_cordis.episodes "
                             "WHERE fiber_id=%s AND closed_at IS NULL),'none')", (fiber,)) == 'active', fiber
    assert handler.calls == []
    print('[CDP6-S5b] >page ready command continuations advanced fairly with no skip')


def test_scanner_paging_disposals(db):
    fx = Fixture(db)
    installs = []
    for _ in range(6):
        payload, _, _ = fx.install()
        commit(db, 'service', 'command_dispose', dict(install_id=payload['install_id']))
        installs.append(uuid.UUID(payload['install_id']))
    m, handler = _maintainer(db)
    for _ in range(20):
        if all(owner_one(db, 'SELECT state FROM v24_cordis.installs WHERE id=%s', (i,)) == 'disposed'
               for i in installs):
            break
        m.run_once()
    for install_id in installs:
        assert owner_one(db, 'SELECT state FROM v24_cordis.installs WHERE id=%s',
                         (install_id,)) == 'disposed', install_id
    assert handler.calls == []
    print('[CDP6-S5c] >page dispose_pending installs converge through the original dispose protocol')


def test_scanner_fairness(db):
    """Real deferred, blocked_unknown, closure-overflow and bad-actor first items."""
    fx = Fixture(db)
    m, handler = _maintainer(db, page=8)

    # 1. Lowest fiber key: a real >512 closure.  The three contributions seed
    #    exceed the command seed cap, so advance must return retry_with_closure.
    payload, _, _ = fx.install(fiber_id=LOW_OVERFLOW)
    activate(db, LOW_OVERFLOW)
    episode = owner_one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s',
                        (LOW_OVERFLOW,))
    owner_do(db, "INSERT INTO v24_cordis.contributions(id,fiber_id,episode_id,seq,kind,"
                 "descriptor,inverse,contract_version) SELECT gen_random_uuid(),%s,%s,g,'cell',"
                 "'{}'::jsonb,'{\"op\":\"delete_row\"}'::jsonb,'1' "
                 'FROM generate_series(0,512) g', (LOW_OVERFLOW, episode))
    assert owner_one(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id=%s',
                     (LOW_OVERFLOW,)) == 513

    # 2. Next low fiber: a ready external effect makes its P6 advance deferred.
    payload, _, _ = fx.install(fiber_id=LOW_DEFERRED)
    activate(db, LOW_DEFERRED)
    deferred_episode = owner_one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s',
                                 (LOW_DEFERRED,))
    deferred_effect = uuid.uuid4()
    owner_do(db, "INSERT INTO v24_cordis.effects(id,kind,status,fiber_id,episode_id,input,"
                 "request_actor) VALUES(%s,'model_call','ready',%s,%s,'{}'::jsonb,%s)",
             (deferred_effect, LOW_DEFERRED, deferred_episode, db.roles['service']))
    control = closing(db, LOW_DEFERRED, 1)
    work = m.ensure(LOW_DEFERRED, control)
    assert work.get('disposition') == 'committed', work
    deferred_successor = uuid.UUID(work['emitted'][0])

    # 3. Next low fiber: an unknown effect plus inverse-unknown debt blocks P6.
    payload, _, _ = fx.install(fiber_id=LOW_BLOCKED)
    activate(db, LOW_BLOCKED)
    blocked_episode = owner_one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s',
                                (LOW_BLOCKED,))
    unknown_effect = uuid.uuid4()
    owner_do(db, "INSERT INTO v24_cordis.effects(id,kind,status,fiber_id,episode_id,input,"
                 "request_actor,outcome,settled_at) VALUES(%s,'tool_call','unknown',%s,%s,"
                 "'{}'::jsonb,%s,'{\"v\":1}'::jsonb,clock_timestamp())",
             (unknown_effect, LOW_BLOCKED, blocked_episode, db.roles['service']))
    inverse_contribution = uuid.uuid4()
    owner_do(db, "INSERT INTO v24_cordis.contributions(id,fiber_id,episode_id,seq,kind,"
                 "descriptor,inverse,contract_version) VALUES(%s,%s,%s,0,'cell','{}'::jsonb,"
                 "'{\"op\":\"unknown\",\"debt\":{\"reason\":\"probe\"}}'::jsonb,'1')",
             (inverse_contribution, LOW_BLOCKED, blocked_episode))
    control = closing(db, LOW_BLOCKED, 1)
    work = m.ensure(LOW_BLOCKED, control)
    assert work.get('disposition') == 'committed', work
    blocked_successor = uuid.UUID(work['emitted'][0])

    # 4. Lowest command effect: a ready continuation whose real actor credential is absent.
    payload, install_effect, install_result = fx.install()
    ghost_fiber = uuid.UUID(payload['fiber_id'])
    assert install_result.get('emitted') == [], install_result
    owner_do(db, "INSERT INTO v24_cordis.effects(id,parent_id,ordinal,fiber_id,kind,status,"
                 "input,request_actor) VALUES(%s,%s,0,%s,'command_reconcile','ready',%s,%s)",
             (LOW_GHOST, install_effect, ghost_fiber,
              Json(reconcile_payload(ghost_fiber, 'advance', 0)), 'ghost_login'))

    # 5. Lowest dispose key: a ready effect in the subtree defers dispose.
    payload, _, _ = fx.install(install_id=LOW_DISPOSE)
    commit(db, 'service', 'command_dispose', dict(install_id=payload['install_id']))
    owner_do(db, "INSERT INTO v24_cordis.effects(id,kind,status,fiber_id,input,request_actor) "
                 "VALUES(%s,'model_call','ready',%s,'{}'::jsonb,%s)",
             (uuid.uuid4(), payload['fiber_id'], db.roles['service']))

    # 6. Healthy fibers and disposals at higher keys, with their ready successors
    #    pre-created so they share the first commands page with the blockers.
    healthy = []
    for _ in range(3):
        payload, _, _ = fx.install()
        fiber = uuid.UUID(payload['fiber_id'])
        activate(db, fiber)
        control = closing(db, fiber, 1)
        work = m.ensure(fiber, control)
        assert work.get('disposition') == 'committed', work
        healthy.append((fiber, uuid.UUID(work['emitted'][0])))
    healthy_disposes = []
    for _ in range(2):
        payload, _, _ = fx.install()
        commit(db, 'service', 'command_dispose', dict(install_id=payload['install_id']))
        healthy_disposes.append(uuid.UUID(payload['install_id']))

    reports = [m.run_once()]
    assert handler.calls == []
    first = reports[0]
    fiber_actions = [a['key'] for a in first.actions if a['topic'] == 'fibers']
    assert fiber_actions[:3] == [LOW_OVERFLOW, LOW_DEFERRED, LOW_BLOCKED], fiber_actions[:5]
    overflow = [a for a in first.actions if a['topic'] == 'fibers' and a['key'] == LOW_OVERFLOW]
    assert overflow and overflow[0]['disposition'] == 'retry_with_closure', overflow

    def action(driver_key, topic=None):
        found = [a for a in first.actions
                 if a['key'] == driver_key and (topic is None or a['topic'] == topic)]
        return found

    assert any(a['disposition'] == 'deferred' for a in action(deferred_successor, 'commands')), \
        first.actions
    assert any(a['disposition'] == 'blocked_unknown' for a in action(blocked_successor, 'commands')), \
        first.actions
    assert any(a['disposition'] == 'blocked_actor_credential' for a in action(LOW_GHOST, 'commands')), \
        first.actions
    assert any(a['disposition'] == 'deferred' for a in action(LOW_DISPOSE, 'disposes')), \
        first.actions
    # The same first commands page still committed every healthy successor after the blockers.
    committed = {a['key'] for a in first.actions
                 if a['topic'] == 'commands' and a['disposition'] == 'committed'}
    assert {key for _, key in healthy} <= committed, (committed, healthy)
    for fiber, _ in healthy:
        assert _closed(db, fiber), fiber

    for _ in range(3):
        reports.append(m.run_once())
        if all(owner_one(db, 'SELECT state FROM v24_cordis.installs WHERE id=%s', (i,)) == 'disposed'
               for i in healthy_disposes):
            break
    for install_id in healthy_disposes:
        assert owner_one(db, 'SELECT state FROM v24_cordis.installs WHERE id=%s',
                         (install_id,)) == 'disposed', install_id

    # No writes while blockers stay blocked; each blocker is attempted at most once per pass.
    before = snap(db)
    quiet = m.run(2)
    assert snap(db) == before
    for key in (LOW_OVERFLOW, deferred_successor, blocked_successor, LOW_GHOST, LOW_DISPOSE):
        attempts = [a for r in quiet for a in r.actions if a['key'] == key]
        assert 1 <= len(attempts) <= 2, (key, attempts)
    assert all(len([a for a in r.actions if a['key'] == key]) <= 1
               for r in quiet for key in (LOW_OVERFLOW, deferred_successor, blocked_successor,
                                          LOW_GHOST, LOW_DISPOSE)), \
        'an item was retried more than once in one fair pass'
    drivers = {d.get('driver') for r in reports for d in r.diagnostics}
    assert {'unknown_effect_debt', 'external_pending', 'inverse_unknown_debt'} <= drivers, drivers
    assert all(r.actions for r in quiet), 'quiet pass stopped processing topics'
    assert handler.calls == []
    print('[CDP6-S6] real >512 closure, deferred, blocked_unknown and bad-actor first items do '
          'not starve same-page healthy commands, other topics or debt diagnostics; repeated '
          'quiet passes are zero-write and do not tight-loop')


# ------------------------------------------- independent process restart

def _child_config(server, db, *, rounds, page, pause=False):
    params = {k: v for k, v in server.params.items() if k not in ('dbname', 'user')}
    return dict(params=params, dbname=db.name, observer=db.roles['observer'],
                actors=[db.roles['service']], rounds=rounds, page=page, pause=pause)


def _run_child(server, db, *, rounds, page, pause=False):
    env = dict(os.environ, DP6_SCANNER_CHILD=json.dumps(_child_config(
        server, db, rounds=rounds, page=page, pause=pause)))
    proc = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), '--child-scan'],
        cwd=str(Path(__file__).resolve().parents[3]), env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    if pause:
        line = proc.stdout.readline()
        assert line.startswith('DP6CHILD '), line
        report = json.loads(line.split(' ', 1)[1])
        assert proc.stdout.readline().strip() == 'DP6CHILD_READY'
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=10)
        errors = proc.stderr.read()
        assert proc.returncode == -signal.SIGKILL, (proc.returncode, errors)
        return report, 'killed'
    out, errors = proc.communicate(timeout=120)
    assert proc.returncode == 0, (proc.returncode, out, errors)
    lines = [line for line in out.splitlines() if line.startswith('DP6CHILD ')]
    assert lines, out
    return json.loads(lines[-1].split(' ', 1)[1]), 'exited'


def _wait_child_backends(db, timeout=10):
    deadline = time.monotonic() + timeout
    roles = [db.roles['observer'], db.roles['service']]
    while time.monotonic() < deadline:
        left = owner_one(db, 'SELECT count(*) FROM pg_stat_activity WHERE datname=%s '
                             'AND usename = ANY(%s)', (db.name, roles))
        if left == 0:
            return
        time.sleep(0.05)
    raise AssertionError('child database sessions did not end')


def test_subprocess_restart(db, server):
    fx = Fixture(db)
    m, handler = _maintainer(db, page=2)
    fibers = []
    for _ in range(7):
        payload, _, _ = fx.install()
        fiber = uuid.UUID(payload['fiber_id'])
        activate(db, fiber)
        control = closing(db, fiber, 1)
        work = m.ensure(fiber, control)
        assert work.get('disposition') == 'committed', work
        fibers.append(fiber)

    first, how_a = _run_child(server, db, rounds=1, page=2)
    assert how_a == 'exited'
    _wait_child_backends(db)
    closed_a = {fiber for fiber in fibers if _closed(db, fiber)}
    assert 0 < len(closed_a) < len(fibers), closed_a

    second, how_b = _run_child(server, db, rounds=1, page=2, pause=True)
    assert how_b == 'killed'
    _wait_child_backends(db)
    closed_b = {fiber for fiber in fibers if _closed(db, fiber)}
    assert len(closed_b) > len(closed_a), (closed_a, closed_b)

    third, how_c = _run_child(server, db, rounds=20, page=2)
    assert how_c == 'exited'
    _wait_child_backends(db)
    for fiber in fibers:
        assert _closed(db, fiber), fiber
    keys = lambda report: {a['key'] for a in report['actions'] if a['topic'] == 'commands'}
    assert keys(third) - (keys(first) | keys(second)), (keys(first), keys(second), keys(third))
    assert handler.calls == []
    print('[CDP6-S13] a separate driver process, a SIGKILLed driver and a third empty-memory '
          'process rediscover the same canonical DB and converge with no durable cursor')


# ------------------------------------------------------- diagnostics

def test_scanner_diagnostics(db):
    fx = Fixture(db)
    payload, _, _ = fx.install()
    fiber = uuid.UUID(payload['fiber_id'])
    activate(db, fiber)
    episode = owner_one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s',
                        (fiber,))
    service = db.roles['service']
    host_io = uuid.uuid4()
    model = uuid.uuid4()
    expired = uuid.uuid4()
    unknown = uuid.uuid4()
    owner_do(db, "INSERT INTO v24_cordis.effects(id,kind,status,fiber_id,input,request_actor) "
                 "VALUES(%s,'host_io','ready',%s,'{}'::jsonb,%s)", (host_io, fiber, service))
    owner_do(db, "INSERT INTO v24_cordis.effects(id,kind,status,fiber_id,input,request_actor) "
                 "VALUES(%s,'model_call','ready',%s,'{}'::jsonb,%s)", (model, fiber, service))
    owner_do(db, "INSERT INTO v24_cordis.effects(id,kind,status,fiber_id,input,request_actor,"
                 "claim_owner,attempt,fence,lease_until) VALUES(%s,'tool_call','claimed',%s,"
                 "'{}'::jsonb,%s,%s,1,1,'2020-01-01')", (expired, fiber, service, service))
    owner_do(db, "INSERT INTO v24_cordis.effects(id,kind,status,input,request_actor,outcome,"
                 "settled_at) VALUES(%s,'run_start','unknown','{}'::jsonb,%s,"
                 "'{\"v\":1}'::jsonb,clock_timestamp())", (unknown, service))
    contrib = uuid.uuid4()
    owner_do(db, "INSERT INTO v24_cordis.contributions(id,fiber_id,episode_id,seq,kind,descriptor,"
                 "inverse,contract_version) VALUES(%s,%s,%s,0,'cell','{}'::jsonb,"
                 "'{\"op\":\"unknown\",\"debt\":{\"reason\":\"probe\"}}'::jsonb,'1')",
             (contrib, fiber, episode))
    provider = Provider(db, {service})
    handler = FakeHandler()
    m = drv.Maintainer(observer_connect=provider.observer, actor_connect=provider.actor,
                       ensure_actor=service, handler=handler)
    before = snap(db)
    report = m.run_once()
    assert snap(db) == before, 'diagnostic-only scan wrote rows'
    dispositions = {d.get('driver') for d in report.diagnostics}
    assert {'unsupported_host_io', 'external_pending', 'expired_claim_pending',
            'unknown_effect_debt', 'inverse_unknown_debt'} <= dispositions, report.diagnostics
    assert handler.calls == []
    print('[CDP6-S8] host_io/unknown/expired/ready-external/inverse debt are diagnostics only; '
          'no handler, no claim, no write')


# ------------------------------------------------------- actor rule

def test_actor_rule(db):
    fx = Fixture(db)
    payload, install_effect, _ = fx.install()
    fiber = uuid.UUID(payload['fiber_id'])
    ghost = uuid.uuid4()
    owner_do(db, "INSERT INTO v24_cordis.effects(id,parent_id,ordinal,fiber_id,kind,status,input,"
                 "request_actor) VALUES(%s,%s,0,%s,'command_reconcile','ready',%s,%s)",
             (ghost, install_effect, fiber,
              Json(reconcile_payload(fiber, 'advance', 0)), 'ghost_login'))
    payload2, _, _ = fx.install()
    fiber2 = uuid.UUID(payload2['fiber_id'])
    on_effect, on_result = commit(db, 'service', 'command_reconcile',
                                  reconcile_payload(fiber2, 'on', 0))
    on_child = uuid.UUID(on_result['emitted'][0])
    provider = Provider(db, {db.roles['service']})
    handler = FakeHandler()
    m = drv.Maintainer(observer_connect=provider.observer, actor_connect=provider.actor,
                       ensure_actor=db.roles['service'], page_size=4, handler=handler)
    report = m.run_once()
    assert owner_one(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (ghost,)) == 'ready'
    assert owner_one(db, 'SELECT count(*) FROM v24_cordis.requests WHERE effect_id=%s',
                     (ghost,)) == 0
    blocked = [d for d in report.diagnostics if d.get('driver') == 'blocked_actor_credential']
    assert blocked and blocked[0].get('key') == ghost, report.diagnostics
    assert ghost in {a['key'] for a in report.actions
                     if a['disposition'] == 'blocked_actor_credential'}
    assert handler.calls == []
    handled = {a['key'] for a in report.actions if a['topic'] == 'commands'
               and a['disposition'] == 'committed'}
    assert on_child in handled, (on_child, handled)
    print('[CDP6-S9] missing request_actor credential is blocked locally; other items still advance')


# ------------------------------------------------------- transaction discipline

def test_transaction_discipline(db):
    fx = Fixture(db)
    provider = TrackingProvider(db, {db.roles['service']})
    handler = FakeHandler()
    m = drv.Maintainer(observer_connect=provider.observer, actor_connect=provider.actor,
                       ensure_actor=db.roles['service'], page_size=2, handler=handler)
    for _ in range(2):
        payload, _, _ = fx.install()
        fiber = uuid.UUID(payload['fiber_id'])
        activate(db, fiber)
        closing(db, fiber, 1)
    m.run(3)
    assert handler.calls == []
    assert provider.opened > 0, 'no tracked connection was opened'
    closes = [entry for entry in provider.log if entry[0] == 'close']
    assert len(closes) == provider.opened, (len(closes), provider.opened)
    assert all(entry[1] == TRANSACTION_STATUS_IDLE for entry in provider.log), provider.log
    assert len([entry for entry in provider.log if entry[0] == 'commit']) >= 2, provider.log
    assert owner_one(db, 'SELECT count(*) FROM pg_stat_activity WHERE datname=%s '
                         'AND usename = ANY(%s)',
                     (db.name, [db.roles['observer'], db.roles['service']])) == 0
    assert owner_one(db, "SELECT count(*) FROM pg_stat_activity WHERE datname=%s "
                         "AND state LIKE 'idle in transaction%%'", (db.name,)) == 0
    print('[CDP6-S14] every observer read and advance transaction is committed/rolled back to '
          'IDLE before close; no child session or idle-in-transaction remains after the sweep')


def test_actor_session_user_check(db):
    """A valid LOGIN that is not the request_actor must be blocked, not used."""
    fx = Fixture(db)
    m_service, _ = _maintainer(db)
    payload, _, _ = fx.install()
    mismatched_fiber = uuid.UUID(payload['fiber_id'])
    activate(db, mismatched_fiber)
    control = closing(db, mismatched_fiber, 1)
    work = m_service.ensure(mismatched_fiber, control)
    assert work.get('disposition') == 'committed', work
    mismatched_child = uuid.UUID(work['emitted'][0])

    payload, _, _ = fx.install()
    healthy_fiber = uuid.UUID(payload['fiber_id'])
    activate(db, healthy_fiber)
    control = closing(db, healthy_fiber, 1)
    provider = Provider(db, {db.roles['operator']})
    m_operator = drv.Maintainer(observer_connect=provider.observer,
                                actor_connect=provider.actor,
                                ensure_actor=db.roles['operator'])
    work = m_operator.ensure(healthy_fiber, control)
    assert work.get('disposition') == 'committed', work
    healthy_child = uuid.UUID(work['emitted'][0])

    mapping = {db.roles['service']: db.roles['operator'],
               db.roles['operator']: db.roles['operator']}
    provider = MappingProvider(db, {db.roles['service'], db.roles['operator']}, mapping)
    m = drv.Maintainer(observer_connect=provider.observer, actor_connect=provider.actor,
                       ensure_actor=db.roles['operator'], page_size=8)
    sql = ("SELECT id,parent_id,ordinal,fiber_id,input,request_actor "
           "FROM v24_cordis.effects WHERE kind='command_reconcile' AND status='ready' "
           'AND id>%s ORDER BY id LIMIT %s')
    with contextlib.closing(db.connect('observer')) as conn:
        page = rows(conn, sql, (uuid.UUID(int=0), 64))
        conn.rollback()
    by_id = {row[0]: row for row in page}
    mismatched_row, healthy_row = by_id[mismatched_child], by_id[healthy_child]

    # Direct item: the connection's real session_user is operator, not the
    # continuation's request_actor service.  Nothing is written.
    before = snap(db)
    try:
        m._command(mismatched_row)
    except drv.WrongActor as exc:
        assert db.roles['service'] in str(exc) and db.roles['operator'] in str(exc), exc
    else:
        raise AssertionError('mismatched session_user was not rejected')
    assert snap(db) == before
    assert owner_one(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s',
                     (mismatched_child,)) == 'ready'
    assert owner_one(db, 'SELECT count(*) FROM v24_cordis.requests WHERE effect_id=%s',
                     (mismatched_child,)) == 0

    report = m.run_once()
    blocked = [d for d in report.diagnostics if d.get('key') == mismatched_child
               and d.get('driver') == 'blocked_actor_credential']
    assert blocked and 'session_user mismatch' in blocked[0].get('reason', ''), report.diagnostics
    assert any(a['key'] == mismatched_child and a['disposition'] == 'blocked_actor_credential'
               for a in report.actions), report.actions
    assert any(a['key'] == healthy_child and a['disposition'] == 'committed'
               for a in report.actions), report.actions
    assert _closed(db, healthy_fiber)
    assert owner_one(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s',
                     (mismatched_child,)) == 'ready'
    print('[CDP6-S9b] a real but wrong LOGIN is rejected by session_user verification; the '
          'ready effect stays unclaimed/zero-write and a correctly-bound sibling advances')


# ------------------------------------------------------- driver purity

def test_driver_purity():
    text = Path(drv.__file__).read_text()
    lowered = text.lower()
    for token in ('insert into', 'delete from', 'truncate ', 'update v24_cordis',
                  'drop table', 'alter table'):
        assert token not in lowered, token
    for token in ('time.sleep', 'socket', 'threading'):
        assert token not in text, token
    assert 'SELECT v24_cordis.advance' in text
    print('[CDP6-S10] driver source has no direct DML, sleep, socket or thread; the only writer '
          'call is advance')


# ------------------------------------------------------- child process mode

def _child_scan():
    cfg = json.loads(os.environ['DP6_SCANNER_CHILD'])
    params = dict(cfg['params'])
    params.pop('dbname', None)
    params.pop('user', None)

    def connect(role):
        return psycopg2.connect(**params, dbname=cfg['dbname'], user=role)

    actors = set(cfg['actors'])

    def observer_connect():
        return connect(cfg['observer'])

    def actor_connect(login):
        if login not in actors:
            raise drv.CredentialMissing(login)
        return connect(login)

    handler = FakeHandler()
    m = drv.Maintainer(observer_connect=observer_connect, actor_connect=actor_connect,
                       ensure_actor=cfg['actors'][0], page_size=cfg['page'], handler=handler)
    actions = []
    for _ in range(cfg['rounds']):
        report = m.run_once()
        actions.extend({'topic': a['topic'], 'key': str(a['key']),
                        'disposition': a['disposition']} for a in report.actions)
    assert handler.calls == []
    print('DP6CHILD ' + json.dumps({'actions': actions}), flush=True)
    if cfg.get('pause'):
        print('DP6CHILD_READY', flush=True)
        time.sleep(120)


def main():
    if '--child-scan' in sys.argv[1:]:
        _child_scan()
        return
    test_driver_purity()
    with Server() as server:
        with TestDB(server) as db:
            test_acl(db)
        test_fixture_lifecycle(server)
        with TestDB(server) as db:
            test_ensure_work_and_failure(db)
        with TestDB(server) as db:
            test_live_change(db)
        with TestDB(server) as db:
            test_replay_and_concurrency(db)
        with TestDB(server) as db:
            test_invariants(db)
        with TestDB(server) as db:
            test_dispose_missing_successor(db)
        with TestDB(server) as db:
            test_raw_row_injection(db)
        with TestDB(server) as db:
            test_scanner_paging_fibers(db)
        with TestDB(server) as db:
            test_scanner_paging_commands(db)
        with TestDB(server) as db:
            test_scanner_paging_disposals(db)
        with TestDB(server) as db:
            test_scanner_fairness(db)
        with TestDB(server) as db:
            test_scanner_diagnostics(db)
        with TestDB(server) as db:
            test_actor_rule(db)
        with TestDB(server) as db:
            test_actor_session_user_check(db)
        with TestDB(server) as db:
            test_transaction_discipline(db)
        with TestDB(server) as db:
            test_subprocess_restart(db, server)
    print('[passed] CDP6-S')


if __name__ == '__main__':
    main()
