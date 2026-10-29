"""CDP5-B (W5): final layout, ACL, capacity, seed/closure, event bounds and frozen surfaces.

Run with: uv run python v24/cordis/dp5/test_boundaries.py

B1-B6 are the boundary contract in plan section 6.5. B7 (the complete serial
command record) belongs to the external closeout runner; this script does not
claim to have run the whole suite from inside itself.
"""
from __future__ import annotations
import contextlib
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
CORDIS = HERE.parent
ROOT = CORDIS.parents[1]
SQL = CORDIS / 'sql'
sys.path.insert(0, str(CORDIS / 'dp2'))
sys.path.insert(0, str(CORDIS / 'dp3'))
sys.path.insert(0, str(CORDIS / 'dp4'))
sys.path.insert(0, str(HERE))

import psycopg2  # noqa: E402
from psycopg2.extras import Json  # noqa: E402

from test_support import (Server, TestDB, TABLES, ERRORS, query, api, env,  # noqa: E402
                          snapshot, no_write, sqlstate, principal,
                          assert_helper_budget, prove_helper_budget_measurement)
from test_activation import one, rows, commit_new  # noqa: E402
from dp4_support import (prepare_run, model_body, tool_call, tool_body, claim,  # noqa: E402
                         settle)
from test_kernel import host_seed  # noqa: E402
from test_dispatch import (HOST, listener, declaration_with, create, fresh_scope,  # noqa: E402
                           root_fixture, settle_failure, settle_unknown)

HELPERS = ('40_advance.sql', '41_lifecycle.sql', '42_teardown.sql', '43_loop.sql',
           '44_events.sql')
DDL = ('10_installs.sql', '11_scopes.sql', '12_fibers.sql', '13_episodes.sql',
       '14_contributions.sql', '15_pins.sql', '16_runs.sql', '17_effects.sql',
       '20_relations.sql', '30_triggers.sql')
FROZEN = {
    '00_schema.sql': '05b6b47e0f71881e64fba3c55609c16608e4bc15c44f321ad5a87ede7979bc6d',
    '10_schema.sql': 'a365a235edefe49258038bef4b28a3cd5f8204ab22a71336e892efc706cbae76',
    '20_triggers.sql': '1c75ce97c79abdba9151bd8dfd22bb7b1167c10e256ed8fa54d4adf927da5af1',
    '30_advance.sql': '087a5bcdb4b9132e25b2d04bc0a31606d429fba5d5cfbb0a257f0a2440715870',
    '40_interpreters.sql': '2ebefff558f243891a613787a47ef68dcfb825b1bcc16b78f019e328f982c5f9',
    '45_capability.sql': 'f629ddd511754a4828da4b4dc4da278c1a4bfcb2359f15f00fd6634f9e4f332e',
    '46_cleanup.sql': 'bb32336bf6e262f62a55a78d55bf3ac7b649c06a50bdda9eda6263f96ed083ef',
    '47_verbs.sql': '5c5bdc611f33f5b37d1652f29aeda97323882487c27cf800ac53371a76ea0265',
    '48_loop.sql': 'f23a93cdd5c14966442bf30eb1339b6e110c3b1c279b95650704aa9e12870f30',
    '49_host_reads.sql': '242748a0fe29cbedc723df9d5de18dd1fba7e9767cfce56a3bc218d1a17ce6c4',
    '49_recovery.sql': 'b46abde9f5fc4259f9ea833440ca0c0815a4a14a578e058b861f59990d90af8d',
    '50_permissions.sql': '578cba9fefc0e0238d6ffd42e458b235bd59ae56a7fa6b1f84a2de36fddbdafe',
}
PURE = ('event_policy', 'listener_exec', 'listener_contract', 'listener_call_input',
        'listener_available', 'dispatch_fold')
FORBIDDEN = ('EXECUTE ', 'RAISE ', 'dblink', 'http://', 'https://', 'pg_read_file',
             'pg_write_file', 'lo_import', 'lo_export', 'COPY ')


def q1(db, statement, params=()):
    return one(db, statement, params)


def source():
    return '\n'.join((SQL / name).read_text() for name in sorted(p.name for p in SQL.glob('*.sql')))


def measured_helpers():
    return {name: len((SQL / name).read_text().splitlines()) for name in HELPERS}


def expect_value_error(call, label):
    try:
        call()
    except ValueError:
        return
    raise AssertionError(label + ' was admitted')


def test_b1_layout(db):
    names = sorted(p.name for p in SQL.glob('*.sql'))
    assert len(names) == 19, names
    spec = importlib.util.spec_from_file_location('cordis_dp5_loader', CORDIS / 'load.py')
    loader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)
    assert tuple(loader.SQL_LOAD_ORDER) == tuple(loader.CANONICAL_ORDER)
    assert len(loader.CANONICAL_ORDER) == 19, loader.CANONICAL_ORDER
    assert set(names) == set(loader.CANONICAL_ORDER), names
    order = loader.CANONICAL_ORDER
    assert order.index('43_loop.sql') < order.index('44_events.sql') < order.index(
        '50_permissions.sql')
    loader.self_check_manifest()

    # B2 loader negatives: missing 44, duplicate 44 and 50-before-44 must all refuse.
    with TemporaryDirectory(prefix='cordis-b2-') as raw:
        root = Path(raw)
        for name in order:
            (root / name).write_text('SELECT 1;')
        assert len(loader.validate_manifest(root)) == 19
        expect_value_error(lambda: loader.validate_manifest(
            root, [n for n in order if n != '44_events.sql']), 'missing 44 order')
        expect_value_error(lambda: loader.validate_manifest(root, list(order) + ['44_events.sql']),
                           'duplicate 44 order')
        swapped = list(order)
        a, b = swapped.index('44_events.sql'), swapped.index('50_permissions.sql')
        swapped[a], swapped[b] = swapped[b], swapped[a]
        expect_value_error(lambda: loader.validate_manifest(root, swapped), 'out-of-order 44/50')
        (root / '44_events.sql').unlink()
        expect_value_error(lambda: loader.validate_manifest(root), 'missing 44 file')
        (root / '44_events.sql').write_text('SELECT 1;')
        (root / '99_extra.sql').write_text('SELECT 1;')
        expect_value_error(lambda: loader.validate_manifest(root), 'unregistered SQL')
        (root / '99_extra.sql').unlink()

    # B2 measurement: the 2026-10-28 authorization removed the helper/43/DDL
    # numeric caps. Counts are still measured and reported; the surviving
    # required-file predicate is proved with a tree missing 44_events.sql.
    prove_helper_budget_measurement()
    total, counts = assert_helper_budget(SQL)
    assert counts == measured_helpers(), counts
    ddl = sum(len((SQL / name).read_text().splitlines()) for name in DDL)
    with TemporaryDirectory(prefix='cordis-b2-missing-') as raw:
        root = Path(raw)
        for name, lines in zip(('40_advance.sql', '41_lifecycle.sql', '42_teardown.sql',
                                '43_loop.sql'), (3, 1, 1, 1)):
            (root / name).write_text('x\n' * lines)
        try:
            assert_helper_budget(root)
        except AssertionError as exc:
            assert sorted(exc.args[0]) == ['44_events.sql'], exc
        else:
            raise AssertionError('budget admitted a helper tree missing 44_events.sql')

    text = source()
    assert re.search(r'\bCREATE\s+(OR\s+REPLACE\s+)?(MATERIALIZED\s+)?VIEW\b', text, re.I) is None
    assert re.search(r'\bCREATE\s+EXTENSION\b', text, re.I) is None
    with contextlib.closing(db.connect('owner')) as conn:
        tables = query(conn, "SELECT c.relname FROM pg_class c JOIN pg_namespace n "
                             "ON n.oid=c.relnamespace WHERE n.nspname='v24_cordis' "
                             "AND c.relkind='r' ORDER BY c.relname")
        assert {row[0] for row in tables} == TABLES, tables
        assert query(conn, "SELECT count(*) FROM pg_class c JOIN pg_namespace n "
                           "ON n.oid=c.relnamespace WHERE n.nspname='v24_cordis' "
                           "AND c.relkind IN ('v','m')")[0][0] == 0
        assert query(conn, "SELECT extname FROM pg_extension WHERE extname<>'plpgsql'") == []
        assert query(conn, "SELECT proname FROM pg_proc WHERE "
                           "pronamespace='v24_cordis'::regnamespace AND prosecdef") == [('advance',)]
        public_exec = query(conn, "SELECT count(*) FROM pg_proc p WHERE "
                                  "p.pronamespace='v24_cordis'::regnamespace AND "
                                  "EXISTS(SELECT 1 FROM aclexplode(coalesce(p.proacl,"
                                  "acldefault('f',p.proowner))) a WHERE a.grantee=0 AND "
                                  "a.privilege_type='EXECUTE')")[0][0]
        assert public_exec == 0, public_exec
        public_dml = query(conn, "SELECT count(*) FROM pg_class c CROSS JOIN LATERAL "
                                 "aclexplode(coalesce(c.relacl,acldefault('r',c.relowner))) a "
                                 "WHERE c.relnamespace='v24_cordis'::regnamespace AND "
                                 "c.relkind='r' AND a.grantee=0 AND a.privilege_type IN "
                                 "('INSERT','UPDATE','DELETE')")[0][0]
        assert public_dml == 0, public_dml
        assert query(conn, "SELECT has_schema_privilege('public','v24_cordis','USAGE')")[0][0] is False
        for alias in ('admin', 'service', 'operator'):
            allowed = query(conn, "SELECT p.proname FROM pg_proc p WHERE "
                                  "p.pronamespace='v24_cordis'::regnamespace AND "
                                  "has_function_privilege(%s,p.oid,'EXECUTE') "
                                  "ORDER BY p.proname", (db.roles[alias],))
            assert allowed == [('advance',)], (alias, allowed)
        # Exactly three command kinds survive; no fourth is admitted by the role gate.
        for alias in ('admin', 'service', 'operator'):
            for kind in ('command_install', 'command_reconcile', 'command_dispose'):
                assert query(conn, "SELECT v24_cordis.role_allowed(%s,'command',%s,"
                                   "'admit_and_apply')", (db.roles[alias], kind))[0][0] is True
            assert query(conn, "SELECT v24_cordis.role_allowed(%s,'command',"
                               "'command_unknown','admit_and_apply')",
                         (db.roles[alias],))[0][0] is False
        # Closed protocol error set: 24 codes, no 25th, unknown codes are 22023.
        assert len(ERRORS) == 24 and len(set(ERRORS)) == 24, ERRORS
        for code in ERRORS:
            assert query(conn, 'SELECT v24_cordis.error_v1(%s)', (code,))[0][0] == \
                {'v': 1, 'error': {'code': code, 'detail': {}}}, code
        sqlstate(conn, "SELECT v24_cordis.error_v1('not_a_code')", code='22023')
    print(f'[CDP5-B1] tables=10 manifest=19 definer=advance public_execute=0 '
          f'views/extensions=0 commands=3 protocol_errors=24')
    print('[CDP5-B2] helpers=' + ' '.join(f'{name[:2]}={counts[name]}' for name in HELPERS) +
          f' total={total} ddl={ddl}; line counts measured (no cap), missing-44 and loader '
          'missing/duplicate/order probes refused')


def test_b3_event_acl(db):
    root = root_fixture(db)
    scope, _ = fresh_scope(db, root)
    _, sf, sr = create(db, scope, root['owner'], listeners=[
        listener('b3h', 'parallel', 10, {'type': 'host', 'capability': 'listener_call'}),
        listener('b3i', 'parallel', 5, {'type': 'in_db', 'op': 'const', 'value': {}})],
        contracts={'listener_call': HOST})
    dispatch = q1(db, "SELECT id FROM v24_cordis.effects WHERE kind='dispatch' "
                      'AND fiber_id=%s', (sf,))
    host = uuid.UUID(sr['ready_effects'][0]['effect_id'])
    in_db = q1(db, "SELECT id FROM v24_cordis.effects WHERE parent_id=%s "
                   "AND input->>'listener_id'='b3i'", (dispatch,))
    with contextlib.closing(db.connect('service')) as conn:
        no_write(db, conn, dispatch, env('claim', {'lease_ms': 1000}), code='unauthorized')
    with contextlib.closing(db.connect('service')) as conn:
        no_write(db, conn, in_db, env('claim', {'lease_ms': 1000}), code='unauthorized')
    for alias in ('admin', 'operator'):
        with contextlib.closing(db.connect(alias)) as conn:
            no_write(db, conn, host, env('claim', {'lease_ms': 1000}), code='unauthorized')
    claimed = claim(db, host)
    assert claimed['disposition'] == 'claimed', claimed
    assert claimed['input']['descriptor']['exec']['type'] == 'host'

    # DP4 host_io keeps its six-state 0A000 settlement refusal.
    item = host_seed(db)
    hc = claim(db, item['effect'])
    assert hc['disposition'] == 'claimed', hc
    with contextlib.closing(db.connect('service')) as conn:
        sqlstate(conn, 'SELECT v24_cordis.advance(%s,%s)',
                 (item['effect'], Json(env('success', {}, hc['claim']))), code='0A000')

    # No recovery surface and the release delta remains read-only.
    with contextlib.closing(db.connect('owner')) as conn:
        assert query(conn, "SELECT proname FROM pg_proc WHERE "
                           "pronamespace='v24_cordis'::regnamespace AND "
                           "proname ~ '^(recover|scanner|sweep)'") == []
        body = query(conn, "SELECT pg_get_functiondef("
                           "'v24_cordis.run_pin_release_delta(uuid)'::regprocedure)")[0][0]
        assert re.search(r'\b(INSERT|UPDATE|DELETE)\b', body, re.I) is None

    # The DP4 run/model/tool lifecycle still commits through the same gate.
    x = prepare_run(db, 3)
    mc = claim(db, x['model_effect'])
    assert mc['disposition'] == 'claimed' and 'execution' not in mc, mc
    mr = settle(db, x['model_effect'], model_body([tool_call('b3c', 'tool')]), mc['claim'])
    assert mr['disposition'] == 'committed' and len(mr['emitted']) == 1, mr
    tool = uuid.UUID(mr['emitted'][0])
    tc = claim(db, tool)
    assert tc['disposition'] == 'claimed', tc
    tr = settle(db, tool, tool_body(), tc['claim'])
    assert tr['disposition'] == 'committed', tr
    run = rows(db, 'SELECT state,ended_at FROM v24_cordis.runs WHERE id=%s',
               (x['run_id'],))[0]
    assert run[1] is None, run
    print('[CDP5-B3] dispatch/in_db external claim is unauthorized; service claims host '
          'listener while admin/operator are unauthorized; host_io settlement 0A000; '
          'no scanner/sweep/recover; release delta read-only; DP4 run/model/tool commits')


def dp4_seed(db, effect):
    kind, run, episode = rows(db, 'SELECT kind,run_id,episode_id FROM v24_cordis.effects '
                                  'WHERE id=%s', (effect,))[0]
    items = {('effects', str(effect))}
    if kind == 'run_start':
        for b in q1(db, 'SELECT v24_cordis.run_bindings(%s)', (episode,)):
            items.add(('contributions', b['contribution_id']))
            items.add(('fibers', b['provider_fiber_id']))
            items.add(('episodes', b['provider_episode_id']))
    if kind in ('model_call', 'tool_call') and run is not None:
        items.add(('runs', str(run)))
        for pin, contrib, cep in rows(db, 'SELECT p.id,c.id,c.episode_id FROM '
                                          'v24_cordis.pins p JOIN v24_cordis.contributions c '
                                          'ON c.id=p.contribution_id WHERE '
                                          'p.consumer_run_id=%s AND p.released_at IS NULL',
                                      (run,)):
            items.add(('pins', str(pin)))
            items.add(('contributions', str(contrib)))
            items.add(('episodes', str(cep)))
    return [{'t': t, 'id': i} for t, i in sorted(items)]


def assert_dp4_seed(db, effect, label):
    got = q1(db, 'SELECT v24_cordis.settlement_seed(%s)', (effect,))
    want = dp4_seed(db, effect)
    assert got == want, (label, got, want)
    return got


def closure_boundary(db, seed, label):
    base = q1(db, 'SELECT v24_cordis.discover_closure(%s)', (Json(seed),))
    assert base is not None, label
    need = 512 - len(base)
    assert need >= 0, (label, len(base))
    ids = [uuid.uuid4() for _ in range(need + 1)]
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, 'INSERT INTO v24_cordis.scopes(id) SELECT unnest(%s::uuid[])', (ids,))
        conn.commit()
    exact = seed + [{'t': 'scopes', 'id': str(x)} for x in ids[:need]]
    over = seed + [{'t': 'scopes', 'id': str(x)} for x in ids]
    assert q1(db, 'SELECT jsonb_array_length(v24_cordis.discover_closure(%s))',
              (Json(exact),)) == 512, label
    assert q1(db, 'SELECT v24_cordis.discover_closure(%s)', (Json(over),)) is None, label


def changed_rows(before, after):
    changed = {}
    for table in before:
        old, new = set(before[table]), set(after[table])
        if old != new:
            changed[table] = (len(old - new), len(new - old))
    return changed


def test_b4_seed_closure(db):
    root = root_fixture(db)
    scope, _ = fresh_scope(db, root)
    _, sf, sr = create(db, scope, root['owner'], listeners=[
        listener('b4h', 'parallel', 10, {'type': 'host', 'capability': 'listener_call'}),
        listener('b4i', 'parallel', 5, {'type': 'in_db', 'op': 'const', 'value': {}})],
        contracts={'listener_call': HOST})
    dispatch = q1(db, "SELECT id FROM v24_cordis.effects WHERE kind='dispatch' "
                      'AND fiber_id=%s', (sf,))
    p4 = q1(db, 'SELECT parent_id FROM v24_cordis.effects WHERE id=%s', (dispatch,))
    host = uuid.UUID(sr['ready_effects'][0]['effect_id'])
    command, command_result, _ = commit_new(
        db, 'command_install', declaration_with(scope, root['owner'], provides=['b4svc']))
    assert command_result['disposition'] == 'committed', command_result
    host_item = host_seed(db)

    # Non-event kinds retain the DP4 W5 seed branches byte-for-byte.
    assert assert_dp4_seed(db, host_item['effect'], 'host_io') == [
        {'t': 'effects', 'id': str(host_item['effect'])}]
    x = prepare_run(db, 3)
    assert_dp4_seed(db, x['run_start'], 'run_start')
    assert_dp4_seed(db, x['model_effect'], 'model_call')
    mc = claim(db, x['model_effect'])
    mr = settle(db, x['model_effect'], model_body([tool_call('b4c', 'tool')]), mc['claim'])
    assert mr['disposition'] == 'committed', mr
    assert_dp4_seed(db, uuid.UUID(mr['emitted'][0]), 'tool_call')
    assert_dp4_seed(db, p4, 'command_reconcile')
    assert_dp4_seed(db, command, 'command_install')

    # 600 historical effects in the same provider fiber must not enter an unrelated seed/closure.
    before = {'host': q1(db, 'SELECT v24_cordis.settlement_seed(%s)', (host,)),
              'p4': q1(db, 'SELECT v24_cordis.settlement_seed(%s)', (p4,)),
              'model': q1(db, 'SELECT v24_cordis.settlement_seed(%s)',
                          (x['model_effect'],))}
    before_closure = q1(db, 'SELECT v24_cordis.discover_closure(%s)', (Json(before['host']),))
    provider_fiber = q1(db, "SELECT input->>'provider_fiber_id' FROM v24_cordis.effects "
                            'WHERE id=%s', (host,))
    host_episode = q1(db, 'SELECT episode_id FROM v24_cordis.effects WHERE id=%s', (host,))
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, "INSERT INTO v24_cordis.effects(id,fiber_id,episode_id,kind,status,"
                    "input,request_actor,outcome,settled_at) SELECT gen_random_uuid(),%s,%s,"
                    "'tool_call','succeeded','{}',%s,'{}',now() FROM generate_series(1,600)",
              (uuid.UUID(provider_fiber), host_episode, db.roles['service']))
        conn.commit()
    after = {'host': q1(db, 'SELECT v24_cordis.settlement_seed(%s)', (host,)),
             'p4': q1(db, 'SELECT v24_cordis.settlement_seed(%s)', (p4,)),
             'model': q1(db, 'SELECT v24_cordis.settlement_seed(%s)',
                         (x['model_effect'],))}
    assert after == before, (after, before)
    assert q1(db, 'SELECT v24_cordis.discover_closure(%s)',
              (Json(after['host']),)) == before_closure

    # p4 command closure and host settlement participate in the 512/513 boundary.
    p4_payload = q1(db, 'SELECT input FROM v24_cordis.effects WHERE id=%s', (p4,))
    p4_seed = q1(db, "SELECT v24_cordis.command_seed('command_reconcile',%s)",
                 (Json(p4_payload),))
    assert p4_seed is not None and len(p4_seed) > 1, p4_seed
    assert q1(db, "SELECT v24_cordis.command_closure('command_reconcile',%s)",
              (Json(p4_payload),)) == q1(db, 'SELECT v24_cordis.discover_closure(%s)',
                                         (Json(p4_seed),))
    closure_boundary(db, p4_seed, 'p4')
    closure_boundary(db, before['host'], 'host')

    # The host seed read/write closure contains provider, install, parent and siblings,
    # and lock_closure really holds those rows against another transaction.
    snapshot_items = q1(db, "SELECT input->'listeners' FROM v24_cordis.effects WHERE id=%s",
                        (dispatch,))
    closure = q1(db, 'SELECT v24_cordis.discover_closure(%s)', (Json(before['host']),))
    targets = {(x['t'], x['id']) for x in closure}
    provider_targets = []
    for item in snapshot_items:
        provider_targets += [('contributions', item['contribution_id']),
                             ('fibers', item['provider_fiber_id']),
                             ('episodes', item['provider_episode_id'])]
    install_targets = []
    for item in snapshot_items:
        install = q1(db, 'SELECT install_id FROM v24_cordis.fibers WHERE id=%s',
                     (uuid.UUID(item['provider_fiber_id']),))
        install_targets.append(('installs', str(install)))
    siblings = rows(db, 'SELECT id FROM v24_cordis.effects WHERE parent_id=%s '
                        'AND kind=%s', (dispatch, 'listener_call'))
    assert ('effects', str(dispatch)) in targets
    assert all(('effects', str(s[0])) in targets for s in siblings), siblings
    assert all(t in targets for t in provider_targets + install_targets), \
        (provider_targets + install_targets, closure)
    with contextlib.closing(db.connect('owner')) as lock:
        assert query(lock, 'SELECT v24_cordis.lock_closure(%s)', (Json(closure),))[0][0] is True
        for table, ident in [('fibers', provider_targets[1][1]),
                             ('installs', install_targets[0][1]),
                             ('effects', str(siblings[0][0]))]:
            with contextlib.closing(db.connect('owner')) as probe:
                try:
                    query(probe, f'SELECT id FROM v24_cordis.{table} WHERE id=%s '
                                 'FOR UPDATE NOWAIT', (uuid.UUID(ident),))
                except psycopg2.Error as exc:
                    assert exc.pgcode == '55P03', (table, exc)
                    probe.rollback()
                else:
                    raise AssertionError(f'{table} closure row was not locked')
        lock.rollback()
    print('[CDP5-B4] non-event host_io/run_start/model/tool/command seeds match the DP4 W5 '
          'recomputation; p4 and host closure admit 512 and refuse 513; 600 unrelated '
          'effects are absent; provider/install/sibling rows are lock-held')


def test_b5_bounds(db):
    root = root_fixture(db)
    manifest = lambda n: dict(requires=[], provides=[], priority=0, check={},
                              listeners=[listener(f'b5-{i}') for i in range(n)])
    assert q1(db, 'SELECT v24_cordis.manifest_shape_valid(%s,%s)',
              (Json(manifest(16)), Json({}))) is True
    assert q1(db, 'SELECT v24_cordis.manifest_shape_valid(%s,%s)',
              (Json(manifest(17)), Json({}))) is False

    scope, _ = fresh_scope(db, root)
    _, _, ok = create(db, scope, root['owner'],
                      listeners=[listener(f'b5a-{i}', 'emit', 0, {'type': 'in_db',
                                                                  'op': 'acc'})
                                 for i in range(15)])
    assert len(ok['emitted']) == 16, ok
    scope, _ = fresh_scope(db, root)
    _, rejected_fiber, rejected = create(db, scope, root['owner'],
                                         listeners=[listener(f'b5b-{i}', 'emit', 0,
                                                             {'type': 'in_db', 'op': 'acc'})
                                                    for i in range(16)])
    assert rejected.get('error', {}).get('code') == 'invalid_outcome', rejected
    assert q1(db, "SELECT count(*) FROM v24_cordis.effects WHERE kind='dispatch' "
                  'AND fiber_id=%s', (rejected_fiber,)) == 0

    # Exact dispatch/child input bytes and the host receipt shape.
    scope, _ = fresh_scope(db, root)
    _, sf, sr = create(db, scope, root['owner'], listeners=[
        listener('b5h', 'parallel', 10, {'type': 'host', 'capability': 'listener_call'}),
        listener('b5i', 'parallel', 5, {'type': 'in_db', 'op': 'const', 'value': {}})],
        contracts={'listener_call': HOST})
    dispatch = q1(db, "SELECT id FROM v24_cordis.effects WHERE kind='dispatch' "
                      'AND fiber_id=%s', (sf,))
    dinput = q1(db, 'SELECT input FROM v24_cordis.effects WHERE id=%s', (dispatch,))
    assert set(dinput) == {'v', 'dispatch_id', 'event', 'mode', 'params', 'bail', 'listeners'}
    assert dinput['dispatch_id'] == str(dispatch) and dinput['event'] == 'fiber.activated'
    assert isinstance(dinput['params'], dict) and dinput['mode'] == 'parallel'
    snap = dinput['listeners']
    assert [item['ordinal'] for item in snap] == list(range(len(snap)))
    for item in snap:
        assert set(item) == {'listener_id', 'contribution_id', 'provider_fiber_id',
                             'provider_episode_id', 'provider_epoch', 'descriptor_digest',
                             'ordinal'}, item
        assert isinstance(item['provider_epoch'], int)
        assert re.fullmatch(r'[0-9a-f]{64}', item['descriptor_digest']), item
    assert json.loads(q1(db, 'SELECT v24_cordis.canonical_json(%s)',
                         (Json(dinput),))) == dinput
    host = uuid.UUID(sr['ready_effects'][0]['effect_id'])
    cinput = q1(db, 'SELECT input FROM v24_cordis.effects WHERE id=%s', (host,))
    assert set(cinput) == {'v', 'dispatch_id', 'event', 'mode', 'ordinal', 'listener_id',
                           'contribution_id', 'provider_fiber_id', 'provider_episode_id',
                           'provider_epoch', 'descriptor', 'descriptor_digest', 'params', 'acc',
                           'contract'}, set(cinput)
    assert cinput['dispatch_id'] == str(dispatch) and cinput['listener_id'] == 'b5h'
    child_claim = claim(db, host)
    receipt = settle(db, host, {'kind': 'listener_call', 'result': {'value': {'x': 1}}},
                     child_claim['claim'])
    assert set(receipt) == {'v', 'disposition', 'effect_id', 'emitted', 'revision', 'claim',
                            'ready_effects'}, receipt
    assert receipt['disposition'] == 'committed' and receipt['emitted'] == []
    assert receipt['ready_effects'] == []
    # Legal failure and unknown are bounded writes, not zero writes and not event-free failures.
    scope, _ = fresh_scope(db, root)
    _, _, fr = create(db, scope, root['owner'], listeners=[
        listener(f'b5f{i}', 'parallel', 10 - i, {'type': 'host', 'capability': 'listener_call'})
        for i in range(3)], contracts={'listener_call': HOST})
    fchildren = [uuid.UUID(x['effect_id']) for x in fr['ready_effects']]
    with contextlib.closing(db.connect('owner')) as conn:
        before = snapshot(conn)
        conn.rollback()
    settle_failure(db, fchildren[0], 'b5_failure')
    with contextlib.closing(db.connect('owner')) as conn:
        after = snapshot(conn)
    changes = changed_rows(before, after)
    assert changes == {'effects': (1, 1), 'events': (0, 1)}, changes
    with contextlib.closing(db.connect('owner')) as conn:
        before = snapshot(conn)
        conn.rollback()
    settle_unknown(db, fchildren[1])
    with contextlib.closing(db.connect('owner')) as conn:
        after = snapshot(conn)
    changes = changed_rows(before, after)
    assert changes == {'effects': (1, 1)}, changes
    assert q1(db, "SELECT status FROM v24_cordis.effects WHERE id=%s", (fchildren[1],)) == 'unknown'

    # 200-key body boundary and the 24-code closed set.
    keys200 = {f'k{i}': i for i in range(200)}
    keys201 = {f'k{i}': i for i in range(201)}
    assert q1(db, 'SELECT v24_cordis.valid_body(%s)', (Json(keys200),)) is True
    assert q1(db, 'SELECT v24_cordis.valid_body(%s)', (Json(keys201),)) is False
    deep = {}
    for _ in range(31):
        deep = {'a': deep}
    assert q1(db, 'SELECT v24_cordis.valid_body(%s)', (Json(deep),)) is True
    deep = {'a': deep}
    assert q1(db, 'SELECT v24_cordis.valid_body(%s)', (Json(deep),)) is False
    assert sorted(ERRORS) == sorted(set(ERRORS)) and len(ERRORS) == 24
    print('[CDP5-B5] manifest listeners 16/17 and created 16/17; dispatch/child input and '
          'host receipt key sets exact; failure writes effects+event and unknown writes only '
          'the effect; 200/201 keys and 32/33 depth; 24 protocol errors')


def test_b6_frozen(db):
    for name, want in FROZEN.items():
        got = hashlib.sha256((ROOT / 'v24' / 'sql' / name).read_bytes()).hexdigest()
        assert got == want, (name, got)
    assert subprocess.run(['git', 'diff', '--check'], cwd=ROOT).returncode == 0
    frozen_paths = ['v24/load.py', 'v24/sql'] + [f'v24/s{i}' for i in range(1, 13)]
    assert subprocess.run(['git', 'diff', '--exit-code', '57e2c1e', '--'] + frozen_paths,
                          cwd=ROOT).returncode == 0
    with contextlib.closing(db.connect('owner')) as conn:
        funcs = query(conn, 'SELECT proname,prosecdef,proconfig,pg_get_functiondef(oid) '
                            "FROM pg_proc WHERE pronamespace='v24_cordis'::regnamespace")
        helper_names = set(re.findall(r'CREATE FUNCTION v24_cordis\.([a-z0-9_]+)',
                                      ''.join((SQL / name).read_text() for name in HELPERS)))
        assert len(helper_names) == 164, len(helper_names)
        assert helper_names <= {name for name, _, _, _ in funcs}
        assert len(funcs) == 172, len(funcs)
        assert [name for name, definer, _, _ in funcs if definer] == ['advance']
        assert all('search_path=pg_catalog, v24_cordis, pg_temp' in (config or [])
                   for _, _, config, _ in funcs), 'function search_path drifted'
        public_exec = query(conn, "SELECT count(*) FROM pg_proc p WHERE "
                                  "p.pronamespace='v24_cordis'::regnamespace AND "
                                  "EXISTS(SELECT 1 FROM aclexplode(coalesce(p.proacl,"
                                  "acldefault('f',p.proowner))) a WHERE a.grantee=0 AND "
                                  "a.privilege_type='EXECUTE')")[0][0]
        assert public_exec == 0, public_exec
        definitions = {name: (vol, body) for name, vol, body in query(
            conn, "SELECT proname,provolatile,pg_get_functiondef(oid) FROM pg_proc "
                  "WHERE pronamespace='v24_cordis'::regnamespace AND proname=ANY(%s)",
            (list(PURE),))}
        assert set(definitions) == set(PURE), definitions
        assert all(vol == 'i' for vol, _ in definitions.values())
        for name, (_, body) in definitions.items():
            for token in FORBIDDEN:
                assert token not in body, (name, token)
        assert query(conn, 'SELECT count(*) FROM pg_proc WHERE '
                           "pronamespace='v24_cordis'::regnamespace AND "
                           "pronamespace='v24_cordis'::regnamespace AND prosecdef")[0][0] == 1

    # Same-LOGIN command replay wins from cache; another LOGIN cannot reuse the effect id.
    root = root_fixture(db)
    scope, _ = fresh_scope(db, root)
    payload = declaration_with(scope, root['owner'], provides=['b6svc'])
    effect, first, outcome = commit_new(db, 'command_install', payload)
    assert first['disposition'] == 'committed', first
    with contextlib.closing(db.connect('service')) as conn:
        replay = api(conn, effect, outcome)
        conn.commit()
    assert replay == first
    with contextlib.closing(db.connect('owner')) as conn:
        cached = query(conn, 'SELECT principal_id,response,count(*) OVER () FROM '
                             'v24_cordis.requests WHERE effect_id=%s', (effect,))[0]
        assert cached[0] == principal(db.roles['service']), cached
        assert cached[1] == first and cached[2] == 1, cached
        before = snapshot(conn)
        conn.rollback()
    with contextlib.closing(db.connect('admin')) as conn:
        foreign = api(conn, effect, outcome)
        conn.rollback()
    assert foreign.get('error', {}).get('code') == 'effect_id_conflict', foreign
    with contextlib.closing(db.connect('owner')) as conn:
        assert snapshot(conn) == before

    # Host receipt replay is checked before token validation: settlement cleared
    # claim_owner, yet the identical receipt still replays with empty arrays and no rewrite.
    _, sf, sr = create(db, scope, root['owner'], listeners=[
        listener('b6h', 'parallel', 10, {'type': 'host', 'capability': 'listener_call'})],
        contracts={'listener_call': HOST})
    host = uuid.UUID(sr['ready_effects'][0]['effect_id'])
    hc = claim(db, host)
    body = {'kind': 'listener_call', 'result': {'value': {'b6': 1}}}
    settled = settle(db, host, body, hc['claim'])
    assert settled['disposition'] == 'committed', settled
    with contextlib.closing(db.connect('service')) as conn:
        replay = api(conn, host, env('success', body, hc['claim']))
        conn.commit()
    assert replay['disposition'] == 'replay' and replay['emitted'] == [], replay
    assert replay['ready_effects'] == [], replay
    assert q1(db, "SELECT status FROM v24_cordis.effects WHERE id=%s", (host,)) == 'succeeded'
    print('[CDP5-B6] twelve frozen v24/sql hashes, frozen 57e2c1e diff and git diff --check '
          'hold; 164 private helpers with one DEFINER, no public EXECUTE, pure helpers '
          'immutable/token-free; same-LOGIN cache replay and terminal replay-first hold')


def main():
    with Server() as server:
        with TestDB(server) as db:
            test_b1_layout(db)
        with TestDB(server) as db:
            test_b3_event_acl(db)
        with TestDB(server) as db:
            test_b4_seed_closure(db)
        with TestDB(server) as db:
            test_b5_bounds(db)
        with TestDB(server) as db:
            test_b6_frozen(db)
    print('[passed] CDP5-B (W5: B1-B6 final layout, ACL, capacity, seed/closure, bounds, frozen)')


if __name__ == '__main__':
    main()
