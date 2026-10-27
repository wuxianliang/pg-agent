"""CDP3-B: final boundary gate for the DP3 teardown contract.

Run with: uv run python v24/cordis/dp3/test_boundaries.py

Production installs, controls, P5/P6 cleanup and dispose all go through real
`advance`. Owner DML is limited to explicitly labelled fixtures: claimable
host_io rows, listener/unsupported inverse rows, run/pin/child drift targets,
history rows, fault-injection triggers and forged interpreter probes. Those
fixtures prove ledger or rejection boundaries only; they do not claim production
listener registration/dispatch, settlement, scanner recovery or child fan-out.
"""
from __future__ import annotations
import contextlib
import importlib.util
import queue
import re
import threading
import time
import uuid
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dp2'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dp1'))

import psycopg2
from psycopg2.extras import Json

from test_support import (Server, TestDB, snapshot, query, api, command, no_write, env,
                          reconcile_payload, dispose_payload, sqlstate, install_probe,
                          set_probe, replace_function, assert_helper_budget,
                          prove_helper_budget_boundary, seed_parent, seed_child, derive,
                          successor_key, delta, event)
from test_activation import (one, rows, install, phases, commit_new, child_call,
                             declaration, p0)
from test_kernel import host_seed
from test_teardown import (mutate, root_install, activate, owner_of, enter_closing,
                           p6_slot, applied, next_slot, event_payload)
from test_dispose import dispose_request, effect_events

CORDIS = Path(__file__).resolve().parents[1]
SQL = CORDIS / 'sql'
HELPERS = ('40_advance.sql', '41_lifecycle.sql', '42_teardown.sql')
DDL = ('10_installs.sql', '11_scopes.sql', '12_fibers.sql', '13_episodes.sql',
       '14_contributions.sql', '15_pins.sql', '16_runs.sql', '17_effects.sql',
       '20_relations.sql', '30_triggers.sql')


def snap(db):
    with contextlib.closing(db.connect('owner')) as conn:
        return snapshot(conn)


def source_sql():
    return '\n'.join((SQL / name).read_text() for name in
                     sorted(p.name for p in SQL.glob('*.sql')))


def domain_snapshot(db):
    """The seven lifecycle tables: a successor-only step may write effects/events/requests."""
    return {name: rows for name, rows in snap(db).items()
            if name not in ('effects', 'events', 'requests')}


def test_layout_and_acl(db):
    names = sorted(p.name for p in SQL.glob('*.sql'))
    assert len(names) == 17, names
    spec = importlib.util.spec_from_file_location('cordis_boundary_loader', CORDIS / 'load.py')
    loader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)
    assert tuple(loader.SQL_LOAD_ORDER) == tuple(loader.CANONICAL_ORDER)
    assert len(loader.CANONICAL_ORDER) == 17
    assert set(names) == set(loader.CANONICAL_ORDER)
    assert loader.CANONICAL_ORDER.index('42_teardown.sql') < loader.CANONICAL_ORDER.index(
        '50_permissions.sql')
    loader.self_check_manifest()
    prove_helper_budget_boundary()
    total, counts = assert_helper_budget(SQL)
    assert set(counts) == set(HELPERS), counts
    assert counts == {name: len((SQL / name).read_text().splitlines()) for name in HELPERS}
    assert total == sum(counts.values()) <= 5000
    ddl = sum(len((SQL / name).read_text().splitlines()) for name in DDL)
    assert ddl <= 900, ddl
    text = source_sql()
    assert re.search(r'\bCREATE\s+(OR\s+REPLACE\s+)?(MATERIALIZED\s+)?VIEW\b', text, re.I) is None
    assert re.search(r'\bCREATE\s+EXTENSION\b', text, re.I) is None
    assert re.search(r'\bload_stage\b|\bpsycopg2\b', text) is None
    with contextlib.closing(db.connect('owner')) as conn:
        assert query(conn, "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                           "WHERE n.nspname='v24_cordis' AND c.relkind='r'")[0][0] == 10
        assert query(conn, "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                           "WHERE n.nspname='v24_cordis' AND c.relkind IN ('v','m')")[0][0] == 0
        assert query(conn, "SELECT extname FROM pg_extension WHERE extname<>'plpgsql'") == []
        assert query(conn, "SELECT count(*) FROM pg_depend d WHERE d.deptype='e' AND ("
                           "(d.classid='pg_proc'::regclass AND d.objid IN "
                           "(SELECT oid FROM pg_proc WHERE pronamespace='v24_cordis'::regnamespace)) OR "
                           "(d.classid='pg_class'::regclass AND d.objid IN "
                           "(SELECT oid FROM pg_class WHERE relnamespace='v24_cordis'::regnamespace)))")[0][0] == 0
        assert query(conn, "SELECT proname FROM pg_proc WHERE pronamespace='v24_cordis'::regnamespace "
                           "AND prosecdef") == [('advance',)]
        public_exec = query(conn, "SELECT count(*) FROM pg_proc p WHERE p.pronamespace='v24_cordis'::regnamespace "
                                  "AND EXISTS(SELECT 1 FROM aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a "
                                  "WHERE a.grantee=0 AND a.privilege_type='EXECUTE')")[0][0]
        assert public_exec == 0, public_exec
        public_dml = query(conn, "SELECT count(*) FROM pg_class c CROSS JOIN LATERAL "
                                 "aclexplode(coalesce(c.relacl,acldefault('r',c.relowner))) a "
                                 "WHERE c.relnamespace='v24_cordis'::regnamespace AND c.relkind='r' "
                                 "AND a.grantee=0 AND a.privilege_type IN ('INSERT','UPDATE','DELETE')")[0][0]
        assert public_dml == 0, public_dml
        assert query(conn, "SELECT has_schema_privilege('public','v24_cordis','USAGE')")[0][0] is False
        for alias in ('admin', 'service', 'operator'):
            allowed = query(conn, "SELECT p.proname FROM pg_proc p "
                                  "WHERE p.pronamespace='v24_cordis'::regnamespace "
                                  "AND has_function_privilege(%s,p.oid,'EXECUTE') ORDER BY p.proname",
                            (db.roles[alias],))
            assert allowed == [('advance',)], (alias, allowed)
    print(f'[CDP3-B1] tables=10 manifest={len(names)} helpers={total} '
          f'40={counts["40_advance.sql"]} 41={counts["41_lifecycle.sql"]} '
          f'42={counts["42_teardown.sql"]} ddl={ddl} definer=advance public_execute=0, '
          'views/extensions=0, 5000/5001 boundary proven')


def test_service_child_production(db, root):
    parent = activate(db, root, provides=['boundary-svc'])
    child = activate(db, parent)
    pf, cf = uuid.UUID(parent['fiber_id']), uuid.UUID(child['fiber_id'])
    assert one(db, "SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id=%s "
                   "AND kind='service' AND key='boundary-svc' AND withdrawn_at IS NULL "
                   "AND released_at IS NULL", (pf,)) == 1
    assert one(db, "SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id=%s "
                   "AND kind='child' AND descriptor->>'child_fiber_id'=%s "
                   "AND released_at IS NULL", (pf, str(cf))) == 1
    assert one(db, 'SELECT state FROM v24_cordis.episodes WHERE id=(SELECT current_episode_id '
                   'FROM v24_cordis.fibers WHERE id=%s)', (cf,)) == 'active'
    assert one(db, 'SELECT state FROM v24_cordis.installs WHERE id=%s',
               (child['install_id'],)) == 'installed'
    assert one(db, 'SELECT count(*) FROM v24_cordis.resolve(%s,ARRAY[%s]) WHERE available',
               (root['scope']['id'], 'boundary-svc')) == 1
    print('[CDP3-B2] real service plus real child install activate and resolve; no fixture is used')


def test_listener_owner_fixture(db, root):
    # Owner fixture: DP3 has no production listener registrar or dispatcher.
    payload = activate(db, root)
    fiber = uuid.UUID(payload['fiber_id'])
    episode = owner_of(db, payload['fiber_id'])['episode_id']
    listener = uuid.uuid4()
    descriptor = {'event': 'boundary-evt', 'listener_id': 'owner-l1'}
    mutate(db, "INSERT INTO v24_cordis.contributions(id,fiber_id,episode_id,seq,kind,realm,key,"
               "descriptor,inverse,contract_version) VALUES(%s,%s,%s,0,'listener',NULL,NULL,"
               "%s,'{\"op\":\"delete_row\"}','1')", (listener, fiber, episode, Json(descriptor)))
    control = enter_closing(db, fiber)
    assert one(db, 'SELECT withdrawn_at IS NOT NULL FROM v24_cordis.contributions WHERE id=%s',
               (listener,)) is True
    effect, outcome, _ = p6_slot(db, fiber, control)
    applied(db, effect, outcome)
    row = one(db, 'SELECT to_jsonb(c) FROM v24_cordis.contributions c WHERE id=%s', (listener,))
    assert row['descriptor'] == descriptor and row['inverse'] == {'op': 'delete_row'}, row
    assert row['withdrawn_at'] is not None and row['released_at'] is not None, row
    assert one(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE id=%s', (listener,)) == 1
    successor, next_out = next_slot(db, effect, fiber, control)
    assert applied(db, successor, next_out)['emitted'] == []
    print('[CDP3-B3] listener owner fixture releases only the ledger row; registration/dispatch unclaimed')


def test_unsupported_inverse_rollback(db, root):
    for index, (kind, inverse) in enumerate((('cell', {'op': 'restore_prev'}),
                                             ('reservation', {'op': 'release_reservation'}))):
        payload = activate(db, root)
        fiber = uuid.UUID(payload['fiber_id'])
        episode = owner_of(db, payload['fiber_id'])['episode_id']
        # Owner fixture: the kind/op pair has no production registrar in DP3.
        mutate(db, "INSERT INTO v24_cordis.contributions(id,fiber_id,episode_id,seq,kind,descriptor,"
                   "inverse,contract_version) VALUES(%s,%s,%s,0,%s,'{}',%s,'1')",
               (uuid.uuid4(), fiber, episode, kind, Json(inverse)))
        control = enter_closing(db, fiber)
        effect, outcome, _ = p6_slot(db, fiber, control)
        before = snap(db)
        with contextlib.closing(db.connect('service')) as conn:
            sqlstate(conn, 'SELECT v24_cordis.advance(%s,%s)', (effect, Json(outcome)))
        assert snap(db) == before
        assert one(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (effect,)) == 'ready'

    payload = activate(db, root)
    fiber = uuid.UUID(payload['fiber_id'])
    episode = owner_of(db, payload['fiber_id'])['episode_id']
    debt = {'op': 'unknown', 'debt': {'reason': 'owner-fixture', 'resource': 'none'}}
    mutate(db, "INSERT INTO v24_cordis.contributions(id,fiber_id,episode_id,seq,kind,realm,key,"
               "descriptor,inverse,contract_version) VALUES(%s,%s,%s,0,'service','root',"
               "'boundary-unknown','{}',%s,'1')", (uuid.uuid4(), fiber, episode, Json(debt)))
    control = enter_closing(db, fiber)
    effect, outcome, _ = p6_slot(db, fiber, control)
    before = snap(db)
    with contextlib.closing(db.connect('service')) as conn:
        no_write(db, conn, effect, outcome, code='blocked_unknown')
    assert snap(db) == before
    assert one(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id=%s '
                   'AND inverse->>\'op\'=\'unknown\' AND released_at IS NULL', (fiber,)) == 1
    print('[CDP3-B4] real cell/reservation inverse is 0A000 with ten-table rollback; unknown is zero-write debt')


def test_barrier_fields_and_expiry(db, root):
    payload = activate(db, root)
    fiber = uuid.UUID(payload['fiber_id'])
    episode = owner_of(db, payload['fiber_id'])['episode_id']
    control = enter_closing(db, fiber)
    effect, outcome, _ = p6_slot(db, fiber, control)
    barrier = uuid.uuid4()
    # Owner fixture: a ready business effect proves the drain barrier only.
    mutate(db, "INSERT INTO v24_cordis.effects(id,fiber_id,episode_id,kind,status,input,request_actor) "
               "VALUES(%s,%s,%s,'dispatch','ready','{}','seed')", (barrier, fiber, episode))
    before = snap(db)
    with contextlib.closing(db.connect('service')) as conn:
        no_write(db, conn, effect, outcome, disposition='deferred')
    assert snap(db) == before
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, "SET LOCAL lock_timeout='2s'")
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        conn.rollback()
    assert rows(db, 'SELECT status,claim_owner,lease_until,attempt,fence FROM v24_cordis.effects '
                    'WHERE id=%s', (barrier,)) == [('ready', None, None, 0, 0)]
    mutate(db, "UPDATE v24_cordis.effects SET status='claimed',claim_owner='seed',"
               "lease_until=clock_timestamp()-interval '1 minute',attempt=1,fence=1 WHERE id=%s",
           (barrier,))
    before = snap(db)
    with contextlib.closing(db.connect('service')) as conn:
        no_write(db, conn, effect, outcome, disposition='deferred')
    assert snap(db) == before
    status, owner, lease, attempt, fence = rows(
        db, 'SELECT status,claim_owner,lease_until,attempt,fence FROM v24_cordis.effects '
            'WHERE id=%s', (barrier,))[0]
    assert status == 'claimed' and owner == 'seed' and lease is not None
    assert (attempt, fence) == (1, 1)
    assert one(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (barrier,)) not in (
        'cancelled', 'succeeded', 'failed')
    print('[CDP3-B5] ready/claimed lease facts survive an expired lease; expiry is not completion or cancellation')


def test_settlement_and_unwired(db, root):
    item = host_seed(db)
    with contextlib.closing(db.connect('service')) as conn:
        claim = api(conn, item['effect'], env('claim', {'lease_ms': 300000}))
        assert claim['disposition'] == 'claimed', claim
        conn.commit()
    before = snap(db)
    with contextlib.closing(db.connect('service')) as conn:
        sqlstate(conn, 'SELECT v24_cordis.advance(%s,%s)',
                 (item['effect'], Json(env('success', {}, claim['claim']))))
    assert snap(db) == before
    assert one(db, "SELECT status FROM v24_cordis.effects WHERE id=%s", (item['effect'],)) == 'claimed'

    intercepted = uuid.uuid4()
    mutate(db, 'INSERT INTO v24_cordis.scopes(id,intercept) VALUES(%s,%s)',
           (intercepted, Json({'boundary': {'v': 1}})))
    payload = declaration(mode='existing', existing=intercepted)
    before = snap(db)
    with contextlib.closing(db.connect('service')) as conn:
        effect, outcome = command(db, conn, 'service', 'command_install', payload)
        sqlstate(conn, 'SELECT v24_cordis.advance(%s,%s)', (effect, Json(outcome)))
    assert snap(db) == before

    payload = declaration(mode='existing', existing=root['scope']['id'])
    payload['overlay'] = {'boundary': {'v': 1}}
    before = snap(db)
    with contextlib.closing(db.connect('service')) as conn:
        effect, outcome = command(db, conn, 'service', 'command_install', payload)
        sqlstate(conn, 'SELECT v24_cordis.advance(%s,%s)', (effect, Json(outcome)))
    assert snap(db) == before

    for kind in ('dispatch', 'run_start'):
        payload = declaration(mode='existing', existing=root['scope']['id'])
        with contextlib.closing(db.connect('service')) as conn:
            effect, outcome = command(db, conn, 'service', kind, payload)
            no_write(db, conn, effect, outcome, code='invalid_args')

    text = source_sql()
    assert 'INSERT INTO v24_cordis.runs' not in text
    assert 'UPDATE v24_cordis.runs' not in text
    assert re.search(r'\b(recover|scanner|sweep)\w*\s*\(', text, re.I) is None
    with contextlib.closing(db.connect('owner')) as conn:
        body = query(conn, "SELECT pg_get_functiondef('v24_cordis.run_pin_release_delta(uuid)'::regprocedure)")[0][0]
        assert re.search(r'\b(INSERT|UPDATE|DELETE)\b', body, re.I) is None
    print('[CDP3-B6] settlement is 0A000; dispatch/intercept/overlay are unwired; no run_start writer or recovery')


def test_limits_history_and_batch(db, root):
    with contextlib.closing(db.connect('owner')) as conn:
        base = dict(domain=[], receipt=dict(status='succeeded'), events=[], successors=[])
        sixteen = [dict(ordinal=i, kind='host_io', input={}) for i in range(16)]
        assert query(conn, "SELECT v24_cordis.validate_delta(%s,'command',true)",
                     (Json(dict(base, successors=sixteen)),))[0][0] is None
        seventeen = sixteen + [dict(ordinal=16, kind='host_io', input={})]
        assert query(conn, "SELECT v24_cordis.validate_delta(%s,'command',true)",
                     (Json(dict(base, successors=seventeen)),))[0][0]['error']['code'] == 'invalid_outcome'
        duplicate = sixteen[:-1] + [dict(ordinal=0, kind='host_io', input={})]
        assert query(conn, "SELECT v24_cordis.validate_delta(%s,'command',true)",
                     (Json(dict(base, successors=duplicate)),))[0][0]['error']['code'] == 'invalid_outcome'
        closure512 = [dict(t='scopes', id=str(uuid.uuid4())) for _ in range(512)]
        assert query(conn, 'SELECT v24_cordis.delta_write_closure_ok(%s,%s)',
                     (Json(base), Json(closure512)))[0][0] is True
        assert query(conn, 'SELECT v24_cordis.delta_write_closure_ok(%s,%s)',
                     (Json(base), Json(closure512 + [dict(t='scopes', id=str(uuid.uuid4()))])))[0][0] is False
        conn.rollback()

    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        scopes = [uuid.uuid4() for _ in range(513)]
        query(conn, 'INSERT INTO v24_cordis.scopes(id) SELECT unnest(%s::uuid[])', (scopes,))
        seed = [dict(t='scopes', id=str(item)) for item in scopes]
        assert len(query(conn, 'SELECT v24_cordis.discover_closure(%s)', (Json(seed[:512]),))[0][0]) == 512
        assert query(conn, 'SELECT v24_cordis.discover_closure(%s)', (Json(seed),))[0][0] is None
        conn.rollback()

    small = activate(db, root)
    fiber = uuid.UUID(small['fiber_id'])
    episode = owner_of(db, small['fiber_id'])['episode_id']
    mutate(db, "INSERT INTO v24_cordis.episodes(id,fiber_id,epoch,state,committed_view,iterator,"
               "outcome,closed_at) SELECT gen_random_uuid(),%s,n,'closing','{}',%s,'retire',now() "
               'FROM generate_series(2,602) n', (fiber, Json(dict(
                   v=1, next_index=0, registered_through=-1, control_seq=1))))
    ancestor, _ = seed_parent(db, 'command_reconcile', reconcile_payload(fiber, 'on', 1),
                              fiber=fiber)
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        for _ in range(600):
            key = successor_key(ancestor)
            child = derive(db.roles['service'], key, 'command_reconcile')
            query(conn, "INSERT INTO v24_cordis.effects(id,parent_id,ordinal,fiber_id,kind,status,"
                        "input,request_actor,outcome,settled_at) VALUES(%s,%s,0,%s,"
                        "'command_reconcile','succeeded',%s,%s,'{}',now())",
                  (child, ancestor, fiber, Json(reconcile_payload(fiber, 'advance', 1)),
                   db.roles['service']))
            ancestor = child
        conn.commit()
    payload = reconcile_payload(fiber, 'advance', 1)
    effect, key = seed_child(db, ancestor, fiber, payload, episode=episode)
    with contextlib.closing(db.connect('owner')) as conn:
        closure = query(conn, 'SELECT v24_cordis.command_closure(%s,%s)',
                        ('command_reconcile', Json(payload)))[0][0]
        assert len(closure) < 50, len(closure)
    with contextlib.closing(db.connect('service')) as conn:
        _, outcome = command(db, conn, 'service', 'command_reconcile', payload,
                             key=key, effect=effect)
    assert applied(db, effect, outcome)['disposition'] == 'committed'

    payload = activate(db, root, provides=[f'batch-{i:02d}' for i in range(33)])
    fiber = uuid.UUID(payload['fiber_id'])
    control = enter_closing(db, fiber)
    effect, outcome, _ = p6_slot(db, fiber, control)
    first = applied(db, effect, outcome)
    event = event_payload(db, effect)
    assert len(first['emitted']) == 1 and len(event['contribution_ids']) == 32, event
    assert event['seq_from'] == 32 and event['seq_through'] == 1, event
    second, second_out = next_slot(db, effect, fiber, control)
    second_result = applied(db, second, second_out)
    assert len(second_result['emitted']) == 1, second_result
    event2 = event_payload(db, second)
    assert event2['seq_from'] == 0 and event2['seq_through'] == 0, event2
    third, third_out = next_slot(db, second, fiber, control)
    assert applied(db, third, third_out)['emitted'] == []
    print('[CDP3-B7] successor16/batch32/closure512 proven; 600 parents and 601 closed generations '
          'leave the current closure small; real 513 refuses')


def test_address_race_and_realms(db, root):
    owner = owner_of(db, root['fiber_id'])
    first, _, _ = install(db, owner=owner, mode='existing', existing=root['scope']['id'],
                          provides=['race-key'])
    second, _, _ = install(db, owner=owner, mode='existing', existing=root['scope']['id'],
                           provides=['race-key'])
    f1, f2 = uuid.UUID(first['fiber_id']), uuid.UUID(second['fiber_id'])
    p1, _, _ = p0(db, f1)
    p2, _, _ = p0(db, f2)
    e1, out1 = child_call(db, p1, reconcile_payload(f1, 'advance', 1))
    e2, out2 = child_call(db, p2, reconcile_payload(f2, 'advance', 1))
    assert len(applied(db, e1, out1)['emitted']) == 1
    assert len(applied(db, e2, out2)['emitted']) == 1
    e1, out1 = child_call(db, e1, reconcile_payload(f1, 'advance', 1))
    e2, out2 = child_call(db, e2, reconcile_payload(f2, 'advance', 1))
    barrier = threading.Barrier(2)
    results = [None, None]
    errors = []

    def run(index, effect, outcome):
        try:
            with contextlib.closing(db.connect('service')) as conn:
                barrier.wait(timeout=15)
                results[index] = api(conn, effect, outcome)
                conn.commit()
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append((index, exc))

    threads = [threading.Thread(target=run, args=(0, e1, out1)),
               threading.Thread(target=run, args=(1, e2, out2))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert not errors, errors
    assert all(result and result.get('disposition') == 'committed' for result in results), results
    assert one(db, "SELECT count(*) FROM v24_cordis.contributions WHERE kind='service' "
                   "AND key='race-key' AND released_at IS NULL") == 1
    losers = rows(db, 'SELECT id,failure FROM v24_cordis.fibers WHERE id IN (%s,%s) '
                      'AND failure IS NOT NULL', (f1, f2))
    assert len(losers) == 1, losers
    loser, failure = losers[0]
    assert failure['phase'] == 'p2' and failure['code'] == 'provide_conflict'
    assert failure['reason'] == 'address_conflict', failure
    assert one(db, "SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id=%s", (loser,)) == 0
    events = rows(db, 'SELECT event_kind,payload FROM v24_cordis.events WHERE effect_id IN (%s,%s) '
                      'ORDER BY event_id', (e1, e2))
    assert ('episode_closing',) == tuple(kind for kind, _ in events if kind == 'episode_closing')
    assert sum(1 for kind, _ in events if kind == 'episode_closing') == 1, events

    activate(db, root, provides=['realm-key'])
    alt, _, _ = install(db, owner=owner, mode='child', parent=root['scope']['id'],
                        overrides={'realm-key': 'alt'}, provides=['realm-key'])
    phases(db, uuid.UUID(alt['fiber_id']), 1)
    realms = rows(db, "SELECT realm,count(*) FROM v24_cordis.contributions WHERE kind='service' "
                      "AND key='realm-key' AND released_at IS NULL GROUP BY realm ORDER BY realm")
    assert realms == [('alt', 1), ('root', 1)], realms
    root_contribution = one(db, "SELECT id FROM v24_cordis.contributions WHERE kind='service' "
                                "AND key='realm-key' AND realm='root' AND released_at IS NULL")
    alt_contribution = one(db, "SELECT id FROM v24_cordis.contributions WHERE kind='service' "
                               "AND key='realm-key' AND realm='alt' AND released_at IS NULL")
    assert one(db, 'SELECT contribution_id FROM v24_cordis.resolve(%s,ARRAY[%s])',
               (root['scope']['id'], 'realm-key')) == root_contribution
    assert one(db, 'SELECT contribution_id FROM v24_cordis.resolve(%s,ARRAY[%s])',
               (alt['scope']['id'], 'realm-key')) == alt_contribution
    print('[CDP3-B8] concurrent same-realm/same-key admits exactly one; different realms admit both')


def post_lock_drift(db, effect, outcome, table, target, trigger, update_sql, update_params,
                    restore_sql, restore_params):
    """Owner-fixture drift: another session mutates a locked target after closure discovery."""
    mutate(db, f'ALTER TABLE v24_cordis.{table} DISABLE TRIGGER {trigger}')
    bconn = db.connect('owner')
    pid_ready = queue.Queue()
    go = threading.Event()
    box = {}

    def run():
        try:
            with contextlib.closing(db.connect('service')) as conn:
                pid = query(conn, 'SELECT pg_backend_pid()')[0][0]
                conn.commit()
                pid_ready.put(pid)
                go.wait(15)
                box['value'] = api(conn, effect, outcome)
                conn.commit()
        except BaseException as exc:  # pragma: no cover - surfaced below
            box['error'] = exc

    thread = threading.Thread(target=run)
    try:
        query(bconn, f'SELECT id FROM v24_cordis.{table} WHERE id=%s FOR UPDATE', (target,))
        thread.start()
        pid = pid_ready.get(timeout=15)
        go.set()
        deadline = time.monotonic() + 20
        with contextlib.closing(db.connect('owner')) as watch:
            while True:
                blocked = query(watch, 'SELECT count(*) FROM pg_locks WHERE pid=%s AND NOT granted',
                                (pid,))[0][0]
                watch.rollback()
                if blocked:
                    break
                if time.monotonic() > deadline:
                    raise AssertionError('advance never blocked on the drift target')
                time.sleep(0.01)
        query(bconn, update_sql, update_params)
        bconn.commit()
        after_commit = snap(db)
        thread.join(30)
        assert not thread.is_alive(), 'advance did not return after the drift commit'
        assert 'error' not in box, box['error']
        result = box['value']
        assert result['error']['code'] == 'retry_with_closure', result
        assert snap(db) == after_commit
        assert one(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (effect,)) == 'ready'
        assert one(db, 'SELECT count(*) FROM v24_cordis.events WHERE effect_id=%s', (effect,)) == 0
        assert one(db, 'SELECT count(*) FROM v24_cordis.requests WHERE effect_id=%s', (effect,)) == 0
    finally:
        if not bconn.closed:
            bconn.rollback()
            bconn.close()
        if thread.is_alive():
            thread.join(5)
        mutate(db, restore_sql, restore_params)
        mutate(db, f'ALTER TABLE v24_cordis.{table} ENABLE TRIGGER {trigger}')


def test_post_lock_drift(db, root):
    source = activate(db, root, provides=['drift-source'])
    alt = activate(db, root, provides=['drift-alt'])
    consumer = activate(db, root, requires=['drift-source'])
    activate(db, consumer)
    fiber = uuid.UUID(consumer['fiber_id'])
    control = enter_closing(db, fiber)
    episode = one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s', (fiber,))
    pin = one(db, 'SELECT id FROM v24_cordis.pins WHERE consumer_fiber_id=%s '
                  'AND consumer_episode_id=%s AND released_at IS NULL', (fiber, episode))
    source_fiber = uuid.UUID(source['fiber_id'])
    alt_fiber = uuid.UUID(alt['fiber_id'])
    alt_episode = one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s',
                      (alt_fiber,))
    source_contribution = one(db, "SELECT id FROM v24_cordis.contributions WHERE fiber_id=%s "
                                    "AND kind='service'", (source_fiber,))
    alt_contribution = one(db, "SELECT id FROM v24_cordis.contributions WHERE fiber_id=%s "
                                 "AND kind='service'", (alt_fiber,))
    child_contribution = one(db, "SELECT id FROM v24_cordis.contributions WHERE fiber_id=%s "
                                   "AND kind='child' AND released_at IS NULL", (fiber,))
    child_seq = one(db, 'SELECT seq FROM v24_cordis.contributions WHERE id=%s', (child_contribution,))
    # Owner fixture: an open run is a drain barrier and a closure member.
    run = uuid.uuid4()
    mutate(db, "INSERT INTO v24_cordis.runs(id,owner_fiber_id,owner_episode_id,scope_id,"
               "spawn_key,remaining_steps) VALUES(%s,%s,%s,%s,'drift-run',1)",
           (run, fiber, episode, root['scope']['id']))
    effect, outcome, _ = p6_slot(db, fiber, control)
    cases = (
        ('pins', 'pins_immutable', pin,
         'UPDATE v24_cordis.pins SET contribution_id=%s WHERE id=%s',
         (alt_contribution, pin),
         'UPDATE v24_cordis.pins SET contribution_id=%s WHERE id=%s',
         (source_contribution, pin)),
        ('runs', 'runs_immutable', run,
         'UPDATE v24_cordis.runs SET owner_fiber_id=%s,owner_episode_id=%s WHERE id=%s',
         (alt_fiber, alt_episode, run),
         'UPDATE v24_cordis.runs SET owner_fiber_id=%s,owner_episode_id=%s WHERE id=%s',
         (fiber, episode, run)),
        ('contributions', 'contributions_immutable', child_contribution,
         'UPDATE v24_cordis.contributions SET fiber_id=%s,episode_id=%s,seq=100 WHERE id=%s',
         (alt_fiber, alt_episode, child_contribution),
         'UPDATE v24_cordis.contributions SET fiber_id=%s,episode_id=%s,seq=%s WHERE id=%s',
         (fiber, episode, child_seq, child_contribution)),
    )
    for table, trigger, target, update_sql, update_params, restore_sql, restore_params in cases:
        post_lock_drift(db, effect, outcome, table, target, trigger, update_sql, update_params,
                        restore_sql, restore_params)
    print('[CDP3-B10b] reverse-pin/run/child collection drift after lock is retry_with_closure '
          'with no DML, request, event or successor')


def test_p5_exact_and_batch(db, root):
    payload = activate(db, root)
    fiber = uuid.UUID(payload['fiber_id'])
    episode = owner_of(db, payload['fiber_id'])['episode_id']
    mutate(db, "INSERT INTO v24_cordis.contributions(id,fiber_id,episode_id,seq,kind,realm,key,"
               "descriptor,inverse,contract_version) SELECT gen_random_uuid(),%s,%s,n,'service',"
               "'root','p5-256-'||n,'{}','{\"op\":\"delete_row\"}','1' FROM generate_series(0,255) n",
           (fiber, episode))
    mutate(db, "INSERT INTO v24_cordis.contributions(id,fiber_id,episode_id,seq,kind,descriptor,"
               "inverse,contract_version) VALUES(gen_random_uuid(),%s,%s,300,'reservation','{}',"
               "'{\"op\":\"release_reservation\"}','1'),(gen_random_uuid(),%s,%s,301,'child','{}',"
               "'{\"op\":\"dispose_child\"}','1')", (fiber, episode, fiber, episode))
    off, result, _ = commit_new(db, 'command_reconcile', reconcile_payload(fiber, 'off', 1))
    assert result.get('disposition') == 'committed', result
    effect, outcome = child_call(db, off, reconcile_payload(fiber, 'advance', 2))
    applied(db, effect, outcome)
    facts = rows(db, 'SELECT kind,withdrawn_at IS NOT NULL,released_at IS NOT NULL '
                     'FROM v24_cordis.contributions WHERE episode_id=%s', (episode,))
    assert facts.count(('service', True, False)) == 256, facts
    assert facts.count(('child', False, False)) == 1 and facts.count(('reservation', False, False)) == 1
    event = event_payload(db, effect)
    expected = [str(row[0]) for row in rows(
        db, "SELECT id FROM v24_cordis.contributions WHERE episode_id=%s AND kind='service' "
            'ORDER BY id::text', (episode,))]
    assert event['withdrawn_ids'] == expected, event

    payload = activate(db, root)
    fiber = uuid.UUID(payload['fiber_id'])
    episode = owner_of(db, payload['fiber_id'])['episode_id']
    mutate(db, "INSERT INTO v24_cordis.contributions(id,fiber_id,episode_id,seq,kind,realm,key,"
               "descriptor,inverse,contract_version) SELECT gen_random_uuid(),%s,%s,n,'service',"
               "'root','p5-257-'||n,'{}','{\"op\":\"delete_row\"}','1' FROM generate_series(0,255) n",
           (fiber, episode))
    mutate(db, "INSERT INTO v24_cordis.contributions(id,fiber_id,episode_id,seq,kind,descriptor,"
               "inverse,contract_version) VALUES(gen_random_uuid(),%s,%s,300,'reservation','{}',"
               "'{\"op\":\"release_reservation\"}','1'),(gen_random_uuid(),%s,%s,301,'child','{}',"
               "'{\"op\":\"dispose_child\"}','1'),(gen_random_uuid(),%s,%s,302,'cell','{}',"
               "'{\"op\":\"restore_prev\"}','1')",
           (fiber, episode, fiber, episode, fiber, episode))
    off, result, _ = commit_new(db, 'command_reconcile', reconcile_payload(fiber, 'off', 1))
    assert result.get('disposition') == 'committed', result
    effect, outcome = child_call(db, off, reconcile_payload(fiber, 'advance', 2))
    with contextlib.closing(db.connect('service')) as conn:
        no_write(db, conn, effect, outcome, code='retry_with_closure',
                 detail={'reason': 'withdraw_budget'})
    print('[CDP3-B9] P5 withdraws exactly 256 and refuses 257 before any write')


def test_apply_rollback_postconditions(db, root):
    payload = activate(db, root, provides=['rollback-inv'])
    fiber = uuid.UUID(payload['fiber_id'])
    control = enter_closing(db, fiber)
    effect, outcome, _ = p6_slot(db, fiber, control)
    replace_function(db, 'CREATE FUNCTION v24_cordis.boundary_suppress_contrib() RETURNS trigger '
                          'LANGUAGE plpgsql AS $$ BEGIN RETURN NULL; END $$')
    replace_function(db, 'CREATE TRIGGER boundary_suppress_contrib BEFORE UPDATE ON '
                          'v24_cordis.contributions FOR EACH ROW EXECUTE FUNCTION '
                          'v24_cordis.boundary_suppress_contrib()')
    try:
        before = snap(db)
        with contextlib.closing(db.connect('service')) as conn:
            sqlstate(conn, 'SELECT v24_cordis.advance(%s,%s)', (effect, Json(outcome)),
                     code='23514')
        assert snap(db) == before
        assert one(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (effect,)) == 'ready'
    finally:
        replace_function(db, 'DROP TRIGGER boundary_suppress_contrib ON v24_cordis.contributions')
        replace_function(db, 'DROP FUNCTION v24_cordis.boundary_suppress_contrib()')

    empty = activate(db, root)
    fiber = uuid.UUID(empty['fiber_id'])
    control = enter_closing(db, fiber)
    effect, outcome, _ = p6_slot(db, fiber, control)
    replace_function(db, 'CREATE FUNCTION v24_cordis.boundary_suppress_episode() RETURNS trigger '
                          'LANGUAGE plpgsql AS $$ BEGIN RETURN NULL; END $$')
    replace_function(db, 'CREATE TRIGGER boundary_suppress_episode BEFORE UPDATE ON '
                          'v24_cordis.episodes FOR EACH ROW EXECUTE FUNCTION '
                          'v24_cordis.boundary_suppress_episode()')
    try:
        before = snap(db)
        with contextlib.closing(db.connect('service')) as conn:
            sqlstate(conn, 'SELECT v24_cordis.advance(%s,%s)', (effect, Json(outcome)),
                     code='23514')
        assert snap(db) == before
        assert one(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (effect,)) == 'ready'
    finally:
        replace_function(db, 'DROP TRIGGER boundary_suppress_episode ON v24_cordis.episodes')
        replace_function(db, 'DROP FUNCTION v24_cordis.boundary_suppress_episode()')
    print('[CDP3-B10] inverse and close postcondition faults roll back the whole advance')


def test_event_cardinality(db, root):
    payload = activate(db, root, provides=['evt-svc'])
    effect1, result1, outcome1 = dispose_request(db, payload['install_id'])
    assert result1['disposition'] == 'committed', result1
    assert [(kind, body.get('phase')) for kind, body in effect_events(db, effect1)] == [
        ('install_dispose_progress', 'requested')]
    effect2, result2, outcome2 = dispose_request(db, payload['install_id'])
    assert result2['disposition'] == 'committed' and len(result2['emitted']) == 1, result2
    events2 = effect_events(db, effect2)
    assert [(kind, body.get('phase')) for kind, body in events2] == [
        ('install_dispose_progress', 'fiber_requested')], events2
    before = len(rows(db, 'SELECT event_id FROM v24_cordis.events'))
    effect3, result3, _ = dispose_request(db, payload['install_id'])
    assert result3['disposition'] == 'committed' and result3['emitted'] == [], result3
    assert effect_events(db, effect3) == []
    assert len(rows(db, 'SELECT event_id FROM v24_cordis.events')) == before
    with contextlib.closing(db.connect('service')) as conn:
        replay = api(conn, effect2, outcome2)
        conn.commit()
    assert replay == result2
    assert effect_events(db, effect2) == events2

    payload = activate(db, root, provides=['sched-svc'])
    fiber = uuid.UUID(payload['fiber_id'])
    control = one(db, 'SELECT control_seq FROM v24_cordis.fibers WHERE id=%s', (fiber,))
    off, result, _ = commit_new(db, 'command_reconcile', reconcile_payload(fiber, 'off', control))
    assert result.get('disposition') == 'committed' and result['emitted'], result
    leave, leave_out = child_call(db, off, reconcile_payload(fiber, 'advance', control + 1))
    applied(db, leave, leave_out)
    effect1, result1, _ = dispose_request(db, payload['install_id'])
    assert result1['disposition'] == 'committed', result1
    domain_before = domain_snapshot(db)
    effect2, result2, outcome2 = dispose_request(db, payload['install_id'])
    assert result2['disposition'] == 'committed' and len(result2['emitted']) == 1, result2
    assert domain_snapshot(db) == domain_before
    events2 = effect_events(db, effect2)
    assert [(kind, body.get('phase')) for kind, body in events2] == [
        ('install_dispose_progress', 'work_scheduled')], events2
    body = events2[0][1]
    assert body['scheduled_targets'] == [str(fiber)] and body['fiber_id'] == str(fiber), body
    before = len(rows(db, 'SELECT event_id FROM v24_cordis.events'))
    effect3, result3, _ = dispose_request(db, payload['install_id'])
    assert result3['disposition'] == 'committed' and result3['emitted'] == [], result3
    assert effect_events(db, effect3) == []
    with contextlib.closing(db.connect('service')) as conn:
        replay = api(conn, effect2, outcome2)
        conn.commit()
    assert replay == result2
    assert effect_events(db, effect2) == events2
    assert len(rows(db, 'SELECT event_id FROM v24_cordis.events')) == before
    print('[CDP3-B11] domain+schedule stays one event; successor-only is one work_scheduled; '
          'coalescing emits nothing and replay duplicates nothing')


def test_validator_does_not_trust_interpreter(db, root):
    original = install_probe(db)
    try:
        other = str(uuid.uuid4())
        requested = dict(phase='requested', fiber_id=None, child_install_id=None,
                         scheduled_targets=None)
        cases = [
            delta(domain=[dict(op='install_dispose_request', install_id=other)],
                  events=[event('install', root['install_id'], 'install_dispose_progress',
                                requested)]),
            delta(domain=[dict(op='install_dispose_request', install_id=root['install_id'])],
                  events=[event('install', root['install_id'], 'install_dispose_progress',
                                dict(requested, phase='completed'))]),
            delta(domain=[],
                  events=[event('install', root['install_id'], 'install_dispose_progress',
                                dict(requested, phase='work_scheduled',
                                     fiber_id=root['fiber_id'],
                                     scheduled_targets=[root['fiber_id']]))],
                  successors=[dict(ordinal=0, kind='command_reconcile',
                                   input=dict(fiber_id=root['fiber_id'], action='advance',
                                              expected_control_seq=0))]),
            delta(domain=[dict(op='install_dispose_request', install_id=root['install_id'])],
                  events=[event('install', root['install_id'], 'install_dispose_progress',
                                dict(requested, fiber_id=root['fiber_id']))]),
        ]
        for forged in cases:
            with contextlib.closing(db.connect('service')) as conn:
                effect, outcome = command(db, conn, 'service', 'command_dispose',
                                          dispose_payload(root['install_id']))
                set_probe(conn, forged)
                no_write(db, conn, effect, outcome, code='invalid_outcome')
        assert one(db, 'SELECT state FROM v24_cordis.installs WHERE id=%s',
                   (root['install_id'],)) == 'installed'
    finally:
        replace_function(db, original['interpret_command'])
    print('[CDP3-B12] validator independently recomputes target/phase/event/successor; '
          'forged interpreter output is zero-write invalid_outcome')


def test_iterator_loader_guards(db, root):
    payload = activate(db, root, provides=['guard-svc'])
    fiber = uuid.UUID(payload['fiber_id'])
    episode = owner_of(db, payload['fiber_id'])['episode_id']
    expected_keys = ['control_seq', 'next_index', 'registered_through', 'v']
    iterator_keys = lambda: one(
        db, 'SELECT array_agg(k ORDER BY k) FROM (SELECT jsonb_object_keys(iterator) k '
            'FROM v24_cordis.episodes WHERE id=%s) q', (episode,))
    assert iterator_keys() == expected_keys
    control = enter_closing(db, fiber)
    effect, outcome, _ = p6_slot(db, fiber, control)
    applied(db, effect, outcome)
    successor, next_out = next_slot(db, effect, fiber, control)
    assert applied(db, successor, next_out)['emitted'] == []
    assert iterator_keys() == expected_keys
    contribution = one(db, "SELECT id FROM v24_cordis.contributions WHERE fiber_id=%s "
                           "AND kind='service'", (fiber,))

    spec = importlib.util.spec_from_file_location('cordis_boundary_loader2', CORDIS / 'load.py')
    loader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)
    assert loader.SQL_LOAD_ORDER == loader.CANONICAL_ORDER and len(loader.SQL_LOAD_ORDER) == 17
    with contextlib.closing(db.connect('owner')) as conn:
        conn.autocommit = True
        try:
            loader.load_stage(conn)
        except ValueError:
            pass
        else:
            raise AssertionError('loader accepted an autocommit migration')
        finally:
            conn.autocommit = False

    guards = [
        ('UPDATE v24_cordis.fibers SET control_seq=control_seq-1 WHERE id=%s', (fiber,), '23514'),
        ("UPDATE v24_cordis.episodes SET state='active' WHERE id=%s", (episode,), '55000'),
        ('UPDATE v24_cordis.episodes SET closed_at=clock_timestamp() WHERE id=%s', (episode,), '55000'),
        ('UPDATE v24_cordis.contributions SET withdrawn_at=NULL WHERE id=%s', (contribution,), '55000'),
        ('UPDATE v24_cordis.contributions SET released_at=NULL WHERE id=%s', (contribution,), '55000'),
    ]
    for statement, params, code in guards:
        before = snap(db)
        with contextlib.closing(db.connect('owner')) as conn:
            sqlstate(conn, statement, params, code=code)
        assert snap(db) == before
    run = uuid.uuid4()
    mutate(db, 'INSERT INTO v24_cordis.runs(id,owner_fiber_id,owner_episode_id,scope_id,spawn_key,'
               'remaining_steps,ended_at) VALUES(%s,%s,%s,%s,%s,0,clock_timestamp())',
           (run, fiber, episode, root['scope']['id'], 'boundary-run'))
    before = snap(db)
    with contextlib.closing(db.connect('owner')) as conn:
        sqlstate(conn, 'UPDATE v24_cordis.runs SET ended_at=clock_timestamp()+interval \'1 second\' '
                       'WHERE id=%s', (run,), code='55000')
    assert snap(db) == before
    scope = uuid.uuid4()
    mutate(db, 'INSERT INTO v24_cordis.scopes(id,closed_at) VALUES(%s,clock_timestamp())', (scope,))
    before = snap(db)
    with contextlib.closing(db.connect('owner')) as conn:
        sqlstate(conn, 'UPDATE v24_cordis.scopes SET closed_at=clock_timestamp()+interval \'1 second\' '
                       'WHERE id=%s', (scope,), code='55000')
    assert snap(db) == before
    print('[CDP3-B13] iterator v1 keys stay exact; loader refuses online/autocommit use; '
          'forward-only guards reject every reversal')


def main():
    with Server() as server, TestDB(server) as db:
        test_layout_and_acl(db)
        root = root_install(db)
        test_service_child_production(db, root)
        test_listener_owner_fixture(db, root)
        test_unsupported_inverse_rollback(db, root)
        test_barrier_fields_and_expiry(db, root)
        test_settlement_and_unwired(db, root)
        test_limits_history_and_batch(db, root)
        test_address_race_and_realms(db, root)
        test_post_lock_drift(db, root)
        test_p5_exact_and_batch(db, root)
        test_apply_rollback_postconditions(db, root)
        test_event_cardinality(db, root)
        test_validator_does_not_trust_interpreter(db, root)
        test_iterator_loader_guards(db, root)
    print('[passed] CDP3-B')


if __name__ == '__main__':
    main()
