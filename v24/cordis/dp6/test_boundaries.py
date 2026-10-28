"""CDP6-B (W5): final whole-boundary, compatibility and frozen-surface gate.

Run with: uv run python v24/cordis/dp6/test_boundaries.py

B1-B6 are the CDP6-B boundary contract in the DP6 plan section 6.6. They
re-assert the DP1-DP5 boundary semantics that must survive DP6, and add the
whole-DP6 layout/ACL/frozen closeout. The inherited ``dp2..dp5`` boundary
scripts remain separate required gates; this script does not replace them, it
proves the same load-bearing predicates against the current catalog.

Every semantic boundary is exercised through the real loader/catalog/protocol
with a disposable pgembed database and real LOGINs. No adapter, socket or
network call is used. Rejections are checked with a ten-table snapshot; a
legal failed command receipt is checked only where the contract permits its
bounded effect/request write.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
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

for _path in (CORDIS, CORDIS / 'dp2', CORDIS / 'dp1', CORDIS / 'dp5'):
    sys.path.insert(0, str(_path))

import psycopg2  # noqa: E402
from psycopg2 import sql as pgsql  # noqa: E402
from psycopg2.extras import Json  # noqa: E402

from setup_db import Server, TestDB, TABLES, role_state  # noqa: E402
from test_support import (ERRORS, api, assert_helper_budget, command,  # noqa: E402
                          no_write, prove_helper_budget_measurement, query,
                          reconcile_payload, dispose_payload, snapshot, sqlstate,
                          successor_key)
from test_activation import install, one, p0, phases, rows  # noqa: E402
from test_dispatch import create, fresh_scope, listener, root_fixture  # noqa: E402

HELPERS = ('40_advance.sql', '41_lifecycle.sql', '42_teardown.sql', '43_loop.sql',
           '44_events.sql')
DDL = ('10_installs.sql', '11_scopes.sql', '12_fibers.sql', '13_episodes.sql',
       '14_contributions.sql', '15_pins.sql', '16_runs.sql', '17_effects.sql',
       '20_relations.sql', '30_triggers.sql')
BOOK = ('18_events.sql', '19_requests.sql')

# Twelve frozen v24 baseline hashes: the same values as the DP5 W5 matrix.
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

# Exact observer column whitelist granted by 50_permissions.sql.
OBSERVER_COLUMNS = {
    'fibers': ('id', 'install_id', 'owner_id', 'owner_episode_id', 'scope_id', 'want_on',
               'control_seq', 'current_episode_id', 'failure', 'retire_started_at',
               'dispose_requested_at', 'disposed_at'),
    'episodes': ('id', 'fiber_id', 'epoch', 'state', 'closed_at'),
    'effects': ('id', 'parent_id', 'ordinal', 'fiber_id', 'episode_id', 'run_id', 'kind',
                'status', 'input', 'request_actor', 'attempt', 'fence', 'claim_owner',
                'lease_until', 'outcome', 'settled_at'),
    'installs': ('id', 'scope_id', 'owner_fiber_id', 'owner_episode_id', 'identity',
                 'version', 'artifact_digest', 'state'),
    'requests': ('principal_id', 'request_key', 'request_bytes', 'request_digest',
                 'effect_id', 'response'),
    'runs': ('id', 'owner_fiber_id', 'owner_episode_id', 'ended_at'),
    'contributions': ('id', 'fiber_id', 'episode_id', 'kind', 'realm', 'key', 'inverse',
                      'withdrawn_at', 'released_at'),
    'pins': ('id', 'consumer_fiber_id', 'consumer_episode_id', 'consumer_run_id',
             'contribution_id', 'released_at'),
}

# A non-granted column (or no column at all) for each of the ten tables.
OBSERVER_DENIED_COLUMN = {
    'installs': 'manifest',
    'episodes': 'committed_view',
    'runs': 'scope_id',
    'contributions': 'descriptor',
    'pins': 'key',
    'events': 'event_id',
    'scopes': 'parent_id',
}

INTERPRETERS = {
    'command_install': 'interpret_install',
    'command_reconcile': 'interpret_reconcile',
    'command_dispose': 'interpret_dispose',
}
PURE = ('event_policy', 'listener_exec', 'listener_contract', 'listener_call_input',
        'listener_available', 'dispatch_fold')
FORBIDDEN = ('EXECUTE ', 'RAISE ', 'dblink', 'http://', 'https://', 'pg_read_file',
             'pg_write_file', 'lo_import', 'lo_export', 'COPY ')


def snap(db):
    with contextlib.closing(db.connect('owner')) as conn:
        before = snapshot(conn)
        conn.rollback()
    return before


def expect_value_error(call, label):
    try:
        call()
    except ValueError:
        return
    raise AssertionError(label + ' was admitted')


def first_columns(conn):
    return {table: query(
        conn, 'SELECT a.attname FROM pg_attribute a WHERE a.attrelid=%s::regclass '
              'AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attnum LIMIT 1',
        ('v24_cordis.' + table,))[0][0] for table in sorted(TABLES)}


def allowed_columns(conn, login, table):
    return {row[0] for row in query(
        conn, 'SELECT a.attname FROM pg_attribute a WHERE a.attrelid=%s::regclass '
              "AND a.attnum>0 AND NOT a.attisdropped AND has_column_privilege(%s,%s,"
              "a.attname,'SELECT')", ('v24_cordis.' + table, login, 'v24_cordis.' + table))}


def measured_lines():
    counts = {name: len((SQL / name).read_text().splitlines()) for name in HELPERS}
    ddl = sum(len((SQL / name).read_text().splitlines()) for name in DDL)
    book = sum(len((SQL / name).read_text().splitlines()) for name in BOOK)
    return counts, ddl, book


# ---------------------------------------------------------------- CDP6-B1

def test_b1_layout(db):
    names = sorted(p.name for p in SQL.glob('*.sql'))
    assert len(names) == 19, names
    spec = importlib.util.spec_from_file_location('cordis_dp6_loader', CORDIS / 'load.py')
    loader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)
    order = loader.CANONICAL_ORDER
    assert tuple(loader.SQL_LOAD_ORDER) == tuple(order)
    assert len(order) == 19 and set(names) == set(order), names
    assert order.index('42_teardown.sql') < order.index('43_loop.sql') < order.index(
        '44_events.sql') < order.index('50_permissions.sql')
    loader.self_check_manifest()

    with TemporaryDirectory(prefix='cordis-b1-') as raw:
        root = Path(raw)
        for name in order:
            (root / name).write_text('SELECT 1;')
        assert len(loader.validate_manifest(root)) == 19
        expect_value_error(lambda: loader.validate_manifest(
            root, [name for name in order if name != '44_events.sql']), 'missing 44 order')
        expect_value_error(lambda: loader.validate_manifest(
            root, list(order) + ['44_events.sql']), 'duplicate 44 order')
        swapped = list(order)
        left, right = swapped.index('44_events.sql'), swapped.index('50_permissions.sql')
        swapped[left], swapped[right] = swapped[right], swapped[left]
        expect_value_error(lambda: loader.validate_manifest(root, swapped), 'out-of-order 44/50')
        (root / '44_events.sql').unlink()
        expect_value_error(lambda: loader.validate_manifest(root), 'missing 44 file')
        (root / '44_events.sql').write_text('SELECT 1;')
        (root / '99_extra.sql').write_text('SELECT 1;')
        expect_value_error(lambda: loader.validate_manifest(root), 'unregistered SQL')
        (root / '99_extra.sql').unlink()
        target = root / 'target'
        target.write_text('SELECT 1;')
        active = root / order[0]
        active.unlink()
        active.symlink_to(target)
        expect_value_error(lambda: loader.validate_manifest(root), 'symlinked active SQL')
        active.unlink()
        active.write_text('SELECT 1;')
        inactive = root / order[1]
        inactive.unlink()
        inactive.symlink_to(target)
        expect_value_error(lambda: loader.validate_manifest(root), 'symlinked inactive SQL')
        inactive.unlink()
        inactive.write_text('SELECT 1;')
        active.unlink()
        active.mkdir()
        expect_value_error(lambda: loader.validate_manifest(root), 'directory as active SQL')
        active.rmdir()
        active.write_text('SELECT 1;')
        assert len(loader.validate_manifest(root)) == 19

    prove_helper_budget_measurement()
    total, counts = assert_helper_budget(SQL)
    measured, ddl, book = measured_lines()
    assert counts == measured, (counts, measured)
    assert total == sum(measured.values()), (total, measured)
    with TemporaryDirectory(prefix='cordis-b1-missing-') as raw:
        root = Path(raw)
        for name, lines in zip(HELPERS[:4], (3, 1, 1, 1)):
            (root / name).write_text('x\n' * lines)
        try:
            assert_helper_budget(root)
        except AssertionError as exc:
            assert sorted(exc.args[0]) == ['44_events.sql'], exc
        else:
            raise AssertionError('budget admitted a helper tree missing 44_events.sql')

    text = '\n'.join((SQL / name).read_text() for name in names)
    assert re.search(r'\bCREATE\s+(OR\s+REPLACE\s+)?(MATERIALIZED\s+)?VIEW\b', text, re.I) is None
    assert re.search(r'\bCREATE\s+EXTENSION\b', text, re.I) is None
    assert text.count('pg_advisory_xact_lock(24,1)') == 1
    assert (SQL / '40_advance.sql').read_text().count('pg_advisory_xact_lock(24,1)') == 1

    with contextlib.closing(db.connect('owner')) as conn:
        tables = query(conn, "SELECT c.relname FROM pg_class c JOIN pg_namespace n "
                             'ON n.oid=c.relnamespace WHERE n.nspname=%s AND c.relkind=%s '
                             'ORDER BY c.relname', ('v24_cordis', 'r'))
        assert {row[0] for row in tables} == TABLES, tables
        assert query(conn, "SELECT count(*) FROM pg_class c JOIN pg_namespace n "
                           "ON n.oid=c.relnamespace WHERE n.nspname='v24_cordis' "
                           "AND c.relkind IN ('v','m')")[0][0] == 0
        assert query(conn, "SELECT extname FROM pg_extension WHERE extname<>'plpgsql'") == []
        assert query(conn, 'SELECT proname FROM pg_proc WHERE '
                           "pronamespace='v24_cordis'::regnamespace AND prosecdef") == \
            [('advance',)]
        public_exec = query(conn, 'SELECT count(*) FROM pg_proc p WHERE '
                                 "p.pronamespace='v24_cordis'::regnamespace AND "
                                 'EXISTS(SELECT 1 FROM aclexplode(coalesce(p.proacl,'
                                 "acldefault('f',p.proowner))) a WHERE a.grantee=0 AND "
                                 "a.privilege_type='EXECUTE')")[0][0]
        assert public_exec == 0, public_exec
        public_dml = query(conn, 'SELECT count(*) FROM pg_class c CROSS JOIN LATERAL '
                                 'aclexplode(coalesce(c.relacl,acldefault(\'r\',c.relowner))) a '
                                 "WHERE c.relnamespace='v24_cordis'::regnamespace AND "
                                 "c.relkind='r' AND a.grantee=0 AND a.privilege_type IN "
                                 "('INSERT','UPDATE','DELETE')")[0][0]
        assert public_dml == 0, public_dml
        assert query(conn, "SELECT has_schema_privilege('public','v24_cordis','USAGE')")[0][0] is False

        helpers = set(re.findall(r'CREATE FUNCTION v24_cordis\.([a-z0-9_]+)',
                                 ''.join((SQL / name).read_text() for name in HELPERS)))
        funcs = query(conn, 'SELECT proname,prosecdef,proconfig,pg_get_functiondef(oid) '
                            "FROM pg_proc WHERE pronamespace='v24_cordis'::regnamespace")
        assert len(helpers) == 164, len(helpers)
        assert len(funcs) == 172, len(funcs)
        assert helpers <= {name for name, _, _, _ in funcs}
        assert [name for name, definer, _, _ in funcs if definer] == ['advance']
        assert all('search_path=pg_catalog, v24_cordis, pg_temp' in (config or [])
                   for _, _, config, _ in funcs), 'function search_path drifted'
        assert query(conn, "SELECT proname FROM pg_proc WHERE "
                           "pronamespace='v24_cordis'::regnamespace AND "
                           "proname IN ('recover','scanner','sweep')") == []

        # Read-only helper purity: the six frozen IMMUTABLE helpers stay
        # immutable and contain no execute/RAISE/network/file/COPY token.
        definitions = {name: (volatility, body) for name, volatility, body in query(
            conn, 'SELECT proname,provolatile,pg_get_functiondef(oid) FROM pg_proc '
                  "WHERE pronamespace='v24_cordis'::regnamespace AND proname=ANY(%s)",
            (list(PURE),))}
        assert set(definitions) == set(PURE), definitions
        assert all(volatility == 'i' for volatility, _ in definitions.values())
        for name, (_, body) in definitions.items():
            for token in FORBIDDEN:
                assert token not in body, (name, token)

        interpreters = {row[0] for row in query(
            conn, "SELECT proname FROM pg_proc WHERE pronamespace='v24_cordis'::regnamespace "
                  "AND proname ~ '^interpret_'")}
        assert interpreters == {'interpret_command', 'interpret_settlement',
                                'interpret_install', 'interpret_reconcile',
                                'interpret_dispose'}, interpreters
        dispatcher = query(conn, "SELECT pg_get_functiondef("
                                 "'v24_cordis.interpret_command(uuid,uuid,jsonb,jsonb)'"
                                 '::regprocedure)')[0][0]
        for kind, function in INTERPRETERS.items():
            assert dispatcher.count(f"kind='{kind}'") == 1, (kind, dispatcher)
            assert dispatcher.count(function) == 1, (function, dispatcher)

        for alias in ('admin', 'service', 'operator'):
            allowed = query(conn, 'SELECT p.proname FROM pg_proc p WHERE '
                                  "p.pronamespace='v24_cordis'::regnamespace AND "
                                  "has_function_privilege(%s,p.oid,'EXECUTE') "
                                  'ORDER BY p.proname', (db.roles[alias],))
            assert allowed == [('advance',)], (alias, allowed)

        assert len(ERRORS) == 24 and len(set(ERRORS)) == 24, ERRORS
        for code in ERRORS:
            assert query(conn, 'SELECT v24_cordis.error_v1(%s)', (code,))[0][0] == \
                {'v': 1, 'error': {'code': code, 'detail': {}}}, code
        sqlstate(conn, "SELECT v24_cordis.error_v1('not_a_code')", code='22023')

    # The one G lock really serialises advance: hold it, prove the waiter is
    # cancelled before any target read, release it, and prove no write remains.
    with contextlib.closing(db.connect('service')) as conn:
        effect, outcome = command(db, conn, 'service', 'command_reconcile', {
            'fiber_id': str(uuid.uuid4()), 'action': 'ensure', 'expected_control_seq': 0})
        conn.rollback()
    before = snap(db)
    with contextlib.closing(db.connect('owner')) as lock:
        query(lock, 'SELECT pg_advisory_xact_lock(24,1)')
        with contextlib.closing(db.connect('service')) as conn:
            query(conn, 'SET statement_timeout=300')
            try:
                api(conn, effect, outcome)
            except psycopg2.Error as exc:
                assert exc.pgcode == '57014', (exc.pgcode, str(exc))
            else:
                raise AssertionError('advance did not wait on the one G lock')
            conn.rollback()
        lock.rollback()
    with contextlib.closing(db.connect('service')) as conn:
        result = api(conn, effect, outcome)
        conn.commit()
    assert result.get('error', {}).get('code') == 'not_found_or_denied', result
    assert snap(db) == before

    print(f'[CDP6-B1] manifest=19 tables=10 views/extensions=0 definer=advance '
          f'public_execute=0 commands=3 lifecycle_interpreters=3 protocol_errors=24 '
          f'one_G_lock=verified; pure_helpers=6; helpers={total} '
          f'40={counts["40_advance.sql"]} 41={counts["41_lifecycle.sql"]} '
          f'42={counts["42_teardown.sql"]} 43={counts["43_loop.sql"]} '
          f'44={counts["44_events.sql"]} ddl={ddl} bookkeeping={book} '
          '(report-only, no cap)')


# ---------------------------------------------------------------- CDP6-B2

def test_b2_acl(db):
    observer, group = db.roles['observer'], db.groups['observer']
    state = role_state(db.admin, observer)
    assert state[1:6] == (False, False, False, False, False), state
    assert state[6:] == (True, True), state
    gstate = role_state(db.admin, group)
    assert gstate[1:6] == (False, False, False, False, False), gstate
    assert gstate[6:] == (False, False), gstate

    before = snap(db)
    with contextlib.closing(db.connect('owner')) as conn:
        assert query(conn, 'SELECT roleid FROM pg_auth_members WHERE member=%s',
                     (state[0],)) == [(gstate[0],)]
        columns = first_columns(conn)
        for table in sorted(TABLES):
            assert query(conn, 'SELECT has_table_privilege(%s,%s,%s)',
                         (observer, 'v24_cordis.' + table, 'SELECT'))[0][0] is False
            for privilege in ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'):
                assert query(conn, 'SELECT has_table_privilege(%s,%s,%s)',
                             (observer, 'v24_cordis.' + table, privilege))[0][0] is False
            allowed = allowed_columns(conn, observer, table)
            assert allowed == set(OBSERVER_COLUMNS.get(table, ())), (table, allowed)
        for table, column in OBSERVER_DENIED_COLUMN.items():
            assert query(conn, 'SELECT has_column_privilege(%s,%s,%s,\'SELECT\')',
                         (observer, 'v24_cordis.' + table, column))[0][0] is False, table
        assert query(conn, 'SELECT has_function_privilege(%s,%s,%s)',
                     (observer, 'v24_cordis.advance(uuid,jsonb)', 'EXECUTE'))[0][0] is False
        assert query(conn, "SELECT has_database_privilege(%s,current_database(),'TEMP')",
                     (observer,))[0][0] is False
        assert query(conn, "SELECT has_schema_privilege(%s,'v24_cordis','CREATE')",
                     (observer,))[0][0] is False
        for cls in ('command', 'claim', 'success', 'failure', 'unknown'):
            for kind in tuple(INTERPRETERS) + ('command_unknown', 'host_io', 'run_start',
                                               'model_call', 'tool_call', 'listener_call'):
                assert query(conn, 'SELECT v24_cordis.role_allowed(%s,%s,%s,%s)',
                             (observer, cls, kind, 'admit_and_apply' if cls == 'command'
                              else cls))[0][0] is False, (cls, kind)

    with contextlib.closing(db.connect('observer')) as conn:
        assert query(conn, 'SELECT session_user')[0][0] == observer
        for table, cols in OBSERVER_COLUMNS.items():
            query(conn, f'SELECT {",".join(cols)} FROM v24_cordis.{table} LIMIT 0')
        # A table-level SELECT is absent. `SELECT *` therefore only works on
        # tables whose every column is in the whitelist; all partial tables
        # refuse at the first non-granted column.
        for table in ('installs', 'episodes', 'runs', 'contributions', 'pins', 'events',
                      'scopes', 'requests'):
            sqlstate(conn, f'SELECT * FROM v24_cordis.{table} LIMIT 0', code='42501')
        for table in ('fibers', 'effects'):
            query(conn, f'SELECT * FROM v24_cordis.{table} LIMIT 0')
        for table, column in OBSERVER_DENIED_COLUMN.items():
            sqlstate(conn, f'SELECT {column} FROM v24_cordis.{table} LIMIT 0', code='42501')
        columns = first_columns(db.connect('owner'))
        for table in sorted(TABLES):
            sqlstate(conn, f'INSERT INTO v24_cordis.{table} DEFAULT VALUES', code='42501')
        for table in sorted(TABLES):
            statement = pgsql.SQL('UPDATE v24_cordis.{} SET {}=({}) WHERE false').format(
                pgsql.Identifier(table), pgsql.Identifier(columns[table]),
                pgsql.Identifier(columns[table]))
            sqlstate(conn, statement, code='42501')
            sqlstate(conn, f'DELETE FROM v24_cordis.{table} WHERE false', code='42501')
            sqlstate(conn, f'TRUNCATE v24_cordis.{table}', code='42501')
        sqlstate(conn, "SELECT v24_cordis.advance(gen_random_uuid(),'{}'::jsonb)", code='42501')
        sqlstate(conn, 'CREATE TEMP TABLE cordis_b2_temp(x int)', code='42501')
        sqlstate(conn, 'CREATE TABLE v24_cordis.cordis_b2_probe(x int)', code='42501')
        sqlstate(conn, f'SET ROLE {db.groups["admin"]}', code='42501')

    # The three inherited protocol actors keep their original least privilege:
    # no table access at all, only advance EXECUTE, and no owner membership.
    with contextlib.closing(db.connect('owner')) as conn:
        for alias in ('admin', 'service', 'operator'):
            login = db.roles[alias]
            assert query(conn, 'SELECT roleid FROM pg_auth_members WHERE member=('
                               'SELECT oid FROM pg_roles WHERE rolname=%s)', (login,)) == \
                [(role_state(db.admin, db.groups[alias])[0],)]
            assert query(conn, "SELECT has_schema_privilege(%s,'v24_cordis','USAGE')",
                         (login,))[0][0] is True
            assert query(conn, "SELECT has_schema_privilege(%s,'v24_cordis','CREATE')",
                         (login,))[0][0] is False
            assert query(conn, "SELECT has_database_privilege(%s,current_database(),'CREATE')",
                         (login,))[0][0] is False
            for table in sorted(TABLES):
                assert query(conn, 'SELECT has_table_privilege(%s,%s,%s)',
                             (login, 'v24_cordis.' + table, 'SELECT'))[0][0] is False
                assert query(conn, 'SELECT has_any_column_privilege(%s,%s,%s)',
                             (login, 'v24_cordis.' + table, 'SELECT'))[0][0] is False
            for kind in tuple(INTERPRETERS) + ('command_unknown',):
                expected = kind in INTERPRETERS
                assert query(conn, 'SELECT v24_cordis.role_allowed(%s,%s,%s,%s)',
                             (login, 'command', kind, 'admit_and_apply'))[0][0] is expected, \
                    (alias, kind)

    for alias in ('admin', 'service', 'operator'):
        with contextlib.closing(db.connect(alias)) as conn:
            for table in sorted(TABLES):
                sqlstate(conn, f'INSERT INTO v24_cordis.{table} DEFAULT VALUES', code='42501')
                sqlstate(conn, f'SELECT * FROM v24_cordis.{table} LIMIT 0', code='42501')
            sqlstate(conn, "UPDATE v24_cordis.effects SET status='failed' WHERE false",
                     code='42501')
            sqlstate(conn, 'DELETE FROM v24_cordis.requests WHERE false', code='42501')
            sqlstate(conn, 'TRUNCATE v24_cordis.events', code='42501')
            sqlstate(conn, f'SET ROLE {db.groups["owner"]}', code='42501')
    assert snap(db) == before
    print('[CDP6-B2] observer: exact 8-table column whitelist, no table SELECT/DML/TEMP/'
          'CREATE/advance, no protocol role; admin/service/operator: no table or column '
          'privilege, only advance EXECUTE, no owner membership, all direct DML 42501 '
          'with ten-table zero write')


# ---------------------------------------------------------------- CDP6-B3

def test_b3_interpreters(db):
    payload, install_effect, install_result = install(db)
    assert install_result.get('disposition') == 'committed', install_result
    root = uuid.UUID(payload['fiber_id'])
    assert rows(db, 'SELECT kind,status FROM v24_cordis.effects WHERE id=%s',
                (install_effect,))[0] == ('command_install', 'succeeded')

    phases(db, root, 0)
    assert one(db, 'SELECT state FROM v24_cordis.episodes e JOIN v24_cordis.fibers f '
                   'ON f.current_episode_id=e.id WHERE f.id=%s', (root,)) == 'active'
    reconcile_effects = one(db, "SELECT count(*) FROM v24_cordis.effects WHERE kind="
                                "'command_reconcile' AND fiber_id=%s AND status='succeeded'",
                            (root,))
    assert reconcile_effects >= 3, reconcile_effects

    episode = one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s', (root,))
    child, _, _ = install(db, owner=dict(fiber_id=str(root), episode_id=str(episode)),
                          mode='existing', existing=payload['scope']['id'])
    steps = 0
    for _ in range(12):
        with contextlib.closing(db.connect('service')) as conn:
            effect, outcome = command(db, conn, 'service', 'command_dispose',
                                      dispose_payload(child['install_id']))
            result = api(conn, effect, outcome)
            conn.commit()
        assert result.get('disposition') == 'committed', result
        steps += 1
        if one(db, 'SELECT state FROM v24_cordis.installs WHERE id=%s',
               (child['install_id'],)) == 'disposed':
            break
    assert one(db, 'SELECT state FROM v24_cordis.installs WHERE id=%s',
               (child['install_id'],)) == 'disposed'
    assert steps >= 1, steps

    with contextlib.closing(db.connect('owner')) as conn:
        kinds = {row[0] for row in query(
            conn, 'SELECT DISTINCT kind FROM v24_cordis.effects WHERE kind LIKE '
                  "'command\\_%'")}
        counts = {row[0]: row[1] for row in query(
            conn, "SELECT kind,count(*) FROM v24_cordis.effects WHERE kind LIKE "
                  "'command\\_%' AND status='succeeded' GROUP BY kind")}
    assert kinds == set(INTERPRETERS), kinds
    assert all(counts.get(kind, 0) >= 1 for kind in INTERPRETERS), counts

    # A fourth command kind is refused before any domain write; the closed
    # three-kind set survives DP6.
    with contextlib.closing(db.connect('service')) as conn:
        effect, outcome = command(db, conn, 'service', 'command_unknown', {})
        no_write(db, conn, effect, outcome, code='invalid_args')
    print(f'[CDP6-B3] install/reconcile/dispose interpreters each committed '
          f'(reconcile={reconcile_effects}, dispose_steps={steps}); command kinds=3; a fourth '
          'kind is invalid_args with ten-table zero write')


# ---------------------------------------------------------------- CDP6-B4

def test_b4_terminal(db):
    payload, _, _ = install(db)
    fiber = uuid.UUID(payload['fiber_id'])
    parent, result, _ = p0(db, fiber, 0)
    successor = uuid.UUID(result['emitted'][0])
    assert rows(db, 'SELECT parent_id,ordinal,kind,status FROM v24_cordis.effects '
                    'WHERE id=%s', (successor,))[0] == \
        (parent, 0, 'command_reconcile', 'ready')
    sequence = one(db, 'SELECT control_seq FROM v24_cordis.fibers WHERE id=%s', (fiber,))

    # N=1: the persisted ready slot is unique. N+1: ensure on the open slot is
    # a stable stale_generation with no write.
    with contextlib.closing(db.connect('service')) as conn:
        effect, outcome = command(db, conn, 'service', 'command_reconcile', {
            'fiber_id': str(fiber), 'action': 'ensure', 'expected_control_seq': sequence})
        no_write(db, conn, effect, outcome, code='stale_generation',
                 detail={'reason': 'ensure_slot_present'})
    assert one(db, "SELECT count(*) FROM v24_cordis.effects WHERE fiber_id=%s AND kind="
                   "'command_reconcile' AND status IN ('ready','claimed')", (fiber,)) == 1

    key = successor_key(parent)
    with contextlib.closing(db.connect('service')) as conn:
        effect, outcome = command(db, conn, 'service', 'command_reconcile',
                                  reconcile_payload(fiber, 'advance', sequence),
                                  key=key, effect=successor)
        assert effect == successor
        settled = api(conn, effect, outcome)
        conn.commit()
    assert settled.get('disposition') == 'committed', settled

    # Replay-first: identical bytes return the cached response byte-for-byte
    # and add no request, effect, event or reducer row.
    before = snap(db)
    with contextlib.closing(db.connect('service')) as conn:
        replay = api(conn, effect, outcome)
        conn.commit()
    assert replay == settled, (replay, settled)
    assert snap(db) == before
    with contextlib.closing(db.connect('service')) as conn:
        conflict_effect, conflict_outcome = command(
            db, conn, 'service', 'command_reconcile',
            reconcile_payload(fiber, 'advance', sequence + 1), key=key, effect=successor)
        no_write(db, conn, conflict_effect, conflict_outcome, code='request_conflict')
    before = snap(db)
    with contextlib.closing(db.connect('admin')) as conn:
        foreign = api(conn, effect, outcome)
        conn.rollback()
    assert foreign.get('error', {}).get('code') == 'effect_id_conflict', foreign
    assert snap(db) == before

    # Terminal effect and request receipts are immutable; a second live
    # reconcile successor is refused by the unique slot index.
    before = snap(db)
    with contextlib.closing(db.connect('owner')) as conn:
        sqlstate(conn, "UPDATE v24_cordis.effects SET status='failed' WHERE id=%s",
                 (effect,), code='55000')
        sqlstate(conn, "UPDATE v24_cordis.requests SET response='{}'::jsonb "
                       'WHERE effect_id=%s', (effect,), code='55000')
    assert snap(db) == before
    with contextlib.closing(db.connect('owner')) as conn:
        sqlstate(conn, 'INSERT INTO v24_cordis.effects(id,fiber_id,kind,status,input,'
                       'request_actor) VALUES(gen_random_uuid(),%s,'
                       "'command_reconcile','ready','{}',%s)", (fiber, db.roles['service']),
                 code='23505')
    assert snap(db) == before
    print('[CDP6-B4] one ready successor; ensure on the open slot is '
          'stale_generation/ensure_slot_present zero-write; successor consume replays cached '
          'byte-identically; conflicting bytes and foreign actor are zero-write; terminal '
          'effect/request UPDATE is 55000; a second ready slot is 23505')


# ---------------------------------------------------------------- CDP6-B5

def test_b5_bounds(db):
    with contextlib.closing(db.connect('owner')) as conn:
        keys200 = {f'k{i}': i for i in range(200)}
        keys201 = {f'k{i}': i for i in range(201)}
        assert query(conn, 'SELECT v24_cordis.valid_body(%s)', (Json(keys200),))[0][0] is True
        assert query(conn, 'SELECT v24_cordis.valid_body(%s)', (Json(keys201),))[0][0] is False
        deep = {}
        for _ in range(31):
            deep = {'a': deep}
        assert query(conn, 'SELECT v24_cordis.valid_body(%s)', (Json(deep),))[0][0] is True
        deep = {'a': deep}
        assert query(conn, 'SELECT v24_cordis.valid_body(%s)', (Json(deep),))[0][0] is False

        base = dict(domain=[], receipt=dict(status='succeeded'), events=[], successors=[])
        sixteen = [dict(ordinal=i, kind='host_io', input={}) for i in range(16)]
        seventeen = sixteen + [dict(ordinal=16, kind='host_io', input={})]
        duplicate = sixteen[:-1] + [dict(ordinal=0, kind='host_io', input={})]
        assert query(conn, "SELECT v24_cordis.validate_delta(%s,'command',true)",
                     (Json(dict(base, successors=sixteen)),))[0][0] is None
        assert query(conn, "SELECT v24_cordis.validate_delta(%s,'command',true)",
                     (Json(dict(base, successors=seventeen)),))[0][0]['error']['code'] == \
            'invalid_outcome'
        assert query(conn, "SELECT v24_cordis.validate_delta(%s,'command',true)",
                     (Json(dict(base, successors=duplicate)),))[0][0]['error']['code'] == \
            'invalid_outcome'
        target512 = [dict(t='scopes', id=str(uuid.uuid4())) for _ in range(512)]
        assert query(conn, 'SELECT v24_cordis.delta_write_closure_ok(%s,%s)',
                     (Json(base), Json(target512)))[0][0] is True
        assert query(conn, 'SELECT v24_cordis.delta_write_closure_ok(%s,%s)',
                     (Json(base), Json(target512 + [dict(t='scopes', id=str(uuid.uuid4()))]))
                     )[0][0] is False
        conn.rollback()

    before = snap(db)
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        scopes = [uuid.uuid4() for _ in range(513)]
        query(conn, 'INSERT INTO v24_cordis.scopes(id) SELECT unnest(%s::uuid[])', (scopes,))
        seed = [dict(t='scopes', id=str(item)) for item in scopes]
        assert len(query(conn, 'SELECT v24_cordis.discover_closure(%s)',
                         (Json(seed[:512]),))[0][0]) == 512
        assert query(conn, 'SELECT v24_cordis.discover_closure(%s)', (Json(seed),))[0][0] is None
        conn.rollback()
    assert snap(db) == before

    root = root_fixture(db)
    execution = {'type': 'in_db', 'op': 'acc'}
    scope, _ = fresh_scope(db, root)
    _, fifteen_fiber, accepted = create(
        db, scope, root['owner'],
        listeners=[listener(f'b5-{i}', 'emit', 0, execution) for i in range(15)])
    assert accepted.get('disposition') == 'committed', accepted
    assert len(accepted['emitted']) == 16, accepted
    dispatch = one(db, "SELECT id FROM v24_cordis.effects WHERE kind='dispatch' "
                       'AND fiber_id=%s', (fifteen_fiber,))
    assert one(db, 'SELECT count(*) FROM v24_cordis.effects WHERE parent_id=%s '
                   "AND kind='listener_call'", (dispatch,)) == 15

    scope, _ = fresh_scope(db, root)
    _, sixteen_fiber, rejected = create(
        db, scope, root['owner'],
        listeners=[listener(f'b5b-{i}', 'emit', 0, execution) for i in range(16)])
    assert rejected.get('error', {}).get('code') == 'invalid_outcome', rejected
    assert rejected['error']['detail'] == {'reason': 'budget'}, rejected
    assert one(db, "SELECT count(*) FROM v24_cordis.effects WHERE kind IN "
                   "('dispatch','listener_call') AND fiber_id=%s", (sixteen_fiber,)) == 0
    print('[CDP6-B5] body keys 200/201 and depth 32/33; delta successors 16/17 and duplicate '
          'ordinal; closure 512/513 real and delta-write 512/513; 15 listeners commit 16 '
          'effects while 16 listeners/17 successors is invalid_outcome/budget with no '
          'dispatch or child row')


# ---------------------------------------------------------------- CDP6-B6

def test_b6_frozen():
    for name, want in FROZEN.items():
        got = hashlib.sha256((ROOT / 'v24' / 'sql' / name).read_bytes()).hexdigest()
        assert got == want, (name, got)
    assert subprocess.run(['git', 'diff', '--check'], cwd=ROOT).returncode == 0
    frozen_paths = ['v24/load.py', 'v24/sql'] + [f'v24/s{i}' for i in range(1, 13)]
    assert subprocess.run(['git', 'diff', '--exit-code', '57e2c1e', '--'] + frozen_paths,
                          cwd=ROOT).returncode == 0

    spec = importlib.util.spec_from_file_location('frozen_v24_loader', ROOT / 'v24' / 'load.py')
    loader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)
    assert tuple(loader.SQL_LOAD_ORDER) == tuple(loader.CANONICAL_ORDER)
    assert len(loader.CANONICAL_ORDER) == 12
    loader.self_check_manifest()

    counts, ddl, book = measured_lines()
    print(f'[CDP6-B6] twelve frozen v24/sql hashes, frozen v24/load.py + v24/s1-s12 vs '
          f'57e2c1e and git diff --check hold; v24 loader manifest=12 with its five refusal '
          f'probes; helpers={sum(counts.values())} ddl={ddl} bookkeeping={book} '
          '(report-only, no cap)')


def main():
    with Server() as server:
        for test in (test_b1_layout, test_b2_acl, test_b3_interpreters, test_b4_terminal,
                     test_b5_bounds):
            with TestDB(server) as db:
                test(db)
    test_b6_frozen()
    print('[passed] CDP6-B (W5: whole layout/ACL, three interpreters/terminal/replay/slot, '
          'closure/successor/protocol bounds, frozen surfaces)')


if __name__ == '__main__':
    main()
