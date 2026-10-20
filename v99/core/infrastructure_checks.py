"""Additional Phase 0 infrastructure assertions; injected test module avoids cycles.

Call run_checks(db, test_core) inside the normal fixture. Call
run_group_lifecycle_checks(test_core) only AFTER that fixture has exited: setup
holds the fixed-group advisory lock for its entire lifetime.
"""
from __future__ import annotations

import ast
import contextlib
import inspect
import re
import uuid
from pathlib import Path

import psycopg2
from psycopg2 import sql as identifiers


CONTROL_TABLES = frozenset({
    'core_runs', 'core_epochs', 'core_operations', 'core_effects', 'core_events',
    'core_snapshots', 'core_wakes', 'core_effect_pins', 'core_requests',
    'core_tools', 'core_meta',
})
HISTORY_TYPES = frozenset({'user/message', 'llm/message', 'tool/call', 'tool/result', 'human/responded'})
HISTORY_KEYS = {'schema_version', 'ok', 'run_id', 'epoch_ordinal', 'context_revision', 'catalog_revision', 'events'}
EVENT_KEYS = {'seq', 'type', 'payload', 'epoch_ordinal', 'turn_ordinal'}


def _request(label):
    return 'infra-' + label + '-' + uuid.uuid4().hex


def _start(db, t, label):
    operator = db.connect('operator')
    started = t.good(t.ce_start(operator, label, _request(label)))
    operator.commit()
    return operator, started


def _next_token(service, t, run, driver, fence):
    item = t.good(t.call(service, 'discover', run, driver, fence))['next']
    assert item is not None
    token = t.good(t.call(service, 'claim_effect', run, item['operation_id'], driver, fence))
    service.commit()
    return token


def test_current_tool_failure_cancels_successors(db, t):
    """Q3: a middle tool fails; untouched successors cannot execute/continue."""
    operator, started = _start(db, t, 'failure-chain')
    run, driver = started['run_id'], 'infra-failure-driver'
    service, owner = db.connect('service'), db.connect('admin')
    lease = t.good(t.call(service, 'driver_acquire', run, driver, 60000))
    service.commit()
    fence = lease['driver_fence']
    token = _next_token(service, t, run, driver, fence)
    calls = [{'id': 'call-' + str(i), 'name': 'spawn_subsession', 'args': {'task': 'task-' + str(i)}} for i in range(3)]
    t.good(t.ce_accept(service, token, t.ce_receipt(token, {'schema_version': 1, 'tool_calls': calls}), driver))
    service.commit()
    first = _next_token(service, t, run, driver, fence)
    assert first['request']['params']['task'] == 'task-0'
    result = {'schema_version': 1, 'adapter': 'ce-fake-spawn', 'simulated': True, 'task': 'task-0'}
    t.good(t.ce_accept(service, first, t.ce_receipt(first, result), driver))
    service.commit()
    failed = _next_token(service, t, run, driver, fence)
    assert failed['request']['params']['task'] == 'task-1'
    error = {'schema_version': 1, 'error': {'code': 'fake_tool_failure', 'message': 'deterministic failure'}}
    accepted = t.good(t.ce_accept(service, failed, t.ce_receipt(failed, error, 'failed'), driver))
    assert accepted['status'] == 'failed'
    service.commit()
    rows = t.sql(owner, """SELECT jsonb_agg(jsonb_build_object('task',o.payload->'params'->>'task',
        'effect_status',e.status,'operation_status',o.status,'archive_reason',o.archive_reason,
        'attempt',e.attempt_no,'completed',o.completed_at IS NOT NULL) ORDER BY o.attempt_seq)
        FROM v99_core.core_operations o JOIN v99_core.core_effects e USING(operation_id)
        WHERE o.run_id=%s AND o.verb='admit_tool'""", (run,))
    assert rows == [
        {'task': 'task-0', 'effect_status': 'succeeded', 'operation_status': 'completed', 'archive_reason': None, 'attempt': 1, 'completed': True},
        {'task': 'task-1', 'effect_status': 'failed', 'operation_status': 'completed', 'archive_reason': None, 'attempt': 1, 'completed': True},
        {'task': 'task-2', 'effect_status': 'cancelled', 'operation_status': 'archived', 'archive_reason': 'upstream_failed', 'attempt': 0, 'completed': True},
    ], rows
    assert t.sql(owner, "SELECT count(*) FROM v99_core.core_operations WHERE run_id=%s AND verb='admit_turn'", (run,)) == 1
    assert t.sql(owner, "SELECT count(*) FROM v99_core.core_operations WHERE run_id=%s AND status='pending'", (run,)) == 0
    seal = t.sql(owner, "SELECT payload FROM v99_core.core_events WHERE run_id=%s AND type='run/closed'", (run,))
    assert seal['status'] == 'failed' and seal['unsettled_claim_ids'] == seal['unknown_effect_ids'] == []
    before = t.state(owner, run)
    t.refused(t.call(service, 'discover', run, driver, fence), 'run_not_running')
    service.commit()
    assert t.state(owner, run) == before
    owner.rollback()
    operator.close()
    service.close()
    owner.close()


def _assert_history(owner, service, t, run, driver, fence, epoch):
    before = t.state(owner, run)
    history = t.good(t.call(service, 'worker_history', run, driver, fence))
    service.commit()
    assert set(history) == HISTORY_KEYS and history['schema_version'] == 1
    assert history['run_id'] == run and history['epoch_ordinal'] == epoch
    assert history['context_revision'] == t.sql(owner, 'SELECT context_revision FROM v99_core.core_runs WHERE run_id=%s', (run,))
    assert history['catalog_revision'] == t.sql(owner, 'SELECT catalog_revision FROM v99_core.core_meta WHERE singleton')
    events = history['events']
    assert all(set(event) == EVENT_KEYS and event['type'] in HISTORY_TYPES for event in events)
    seqs = [event['seq'] for event in events]
    assert seqs == sorted(set(seqs))
    expected = t.sql(owner, """SELECT coalesce(jsonb_agg(jsonb_build_object('seq',seq,'type',type,
        'payload',payload,'epoch_ordinal',epoch_ordinal,'turn_ordinal',turn_ordinal) ORDER BY seq),'[]')
        FROM v99_core.core_events WHERE run_id=%s AND type=ANY(%s)""", (run, list(HISTORY_TYPES)))
    assert events == expected, (events, expected)
    # Filtering must discard real audit rows, rather than pass vacuously on an empty log.
    assert t.sql(owner, 'SELECT count(*) FROM v99_core.core_events WHERE run_id=%s', (run,)) > len(events)
    assert t.state(owner, run) == before
    owner.rollback()
    return events


def test_history_projection_and_fake_consumption(db, t):
    """Q3: exact history, all five event kinds, epochs and actual LLM input."""
    operator, started = _start(db, t, 'history-chain')
    run = started['run_id']
    task = 'history-result-' + uuid.uuid4().hex
    interaction = {'id': str(uuid.uuid4()), 'kind': 'question', 'channel': 'human'}
    results = [
        {'schema_version': 1, 'tool_calls': [{'id': 'consume-result', 'name': 'spawn_subsession', 'args': {'task': task}}]},
        {'schema_version': 1, 'text': 'tool result consumed', 'ce_status': 'waiting_for_input', 'interaction': interaction},
        {'schema_version': 1, 'text': 'human result consumed', 'ce_status': 'completed'},
        {'schema_version': 1, 'text': 'cross epoch consumed', 'ce_status': 'completed'},
    ]

    class ConsumingLLM(t.FakeLLM):
        def complete(self, history):
            assert all(set(event) == EVENT_KEYS for event in history)
            assert [event['seq'] for event in history] == sorted({event['seq'] for event in history})
            if self.calls >= 1:
                tool_results = [event for event in history if event['type'] == 'tool/result']
                assert len(tool_results) == 1
                assert tool_results[0]['payload']['result'] == {
                    'schema_version': 1, 'adapter': 'ce-fake-spawn', 'simulated': True, 'task': task}
            if self.calls >= 2:
                human = [event for event in history if event['type'] == 'human/responded']
                assert len(human) == 1 and human[0]['payload']['response'] == {'schema_version': 1, 'response': 'history answer'}
            if self.calls == 3:
                assert {event['epoch_ordinal'] for event in history} == {1, 2}
                assert history[-1]['type'] == 'user/message' and history[-1]['epoch_ordinal'] == 2
            return super().complete(history)

    llm = ConsumingLLM(results)
    host = t.FakeHost(db, llm)
    host.start_driver(run)
    assert host.step(run)['status'] == 'running'
    assert host.step(run)['status'] == 'running'
    assert host.step(run)['status'] == 'waiting_for_input'
    owner = db.connect('admin')
    _assert_history(owner, host.conn, t, run, host.driver, host.fence, 1)
    t.good(t.call(operator, 'respond', None, run, interaction['id'], {'schema_version': 1, 'response': 'history answer'}, _request('history-response')))
    operator.commit()
    assert host.step(run)['status'] == 'completed'
    t.good(t.call(operator, 'steer', None, run, 'history epoch two', _request('history-steer'), 1))
    operator.commit()
    assert host.step(run)['status'] == 'completed'
    events = _assert_history(owner, host.conn, t, run, host.driver, host.fence, 2)
    assert {event['type'] for event in events} == HISTORY_TYPES
    assert {event['epoch_ordinal'] for event in events} == {1, 2}
    assert llm.calls == 4 and host.tool.calls == 1 and host.io_count == 5
    host.conn.close()
    operator.close()
    owner.close()


def test_cached_discover_bound_claim(db, t):
    """Q12: another committed transaction consumes the cached FIFO head."""
    operator, started = _start(db, t, 'cached-head')
    run, driver = started['run_id'], 'infra-bound-driver'
    service, rival, owner = db.connect('service'), db.connect('service'), db.connect('admin')
    lease = t.good(t.call(service, 'driver_acquire', run, driver, 60000))
    fence = lease['driver_fence']
    cached = t.good(t.call(service, 'discover', run, driver, fence))['next']
    service.commit()
    t.good(t.call(operator, 'steer', None, run, 'new FIFO tail', _request('cached-steer'), 1))
    operator.commit()
    # The independent transaction settles the old driving head, making the tail ready.
    token = t.good(t.call(rival, 'claim_effect', run, cached['operation_id'], driver, fence))
    rival.commit()
    result = {'schema_version': 1, 'text': 'old head result', 'ce_status': 'completed'}
    assert t.good(t.ce_accept(rival, token, t.ce_receipt(token, result), driver))['disposition'] == 'archived_stale'
    rival.commit()
    new_head = t.good(t.call(rival, 'discover', run, driver, fence))['next']
    rival.commit()
    assert new_head['operation_id'] != cached['operation_id']
    before = t.state(owner, run)
    t.refused(t.call(service, 'claim_effect', run, cached['operation_id'], driver, fence), 'not_claimable')
    service.commit()
    assert t.state(owner, run) == before
    assert t.sql(owner, "SELECT status='ready' AND attempt_no=0 AND fence=0 FROM v99_core.core_effects WHERE effect_id=%s", (new_head['effect_id'],))
    assert t.sql(owner, 'SELECT count(*) FROM v99_core.core_effect_pins WHERE effect_id=%s', (new_head['effect_id'],)) == 0
    owner.rollback()
    assert t.good(t.call(service, 'claim_effect', run, new_head['operation_id'], driver, fence))['effect_id'] == new_head['effect_id']
    service.commit()
    t.good(t.call(operator, 'cancel', None, run, _request('cached-cleanup')))
    operator.commit()
    for conn in (operator, service, rival, owner):
        conn.close()


def test_set_role_real_caller(db, t):
    """Q5: a non-superuser operator LOGIN really downgrades in the same session."""
    owner, operator = db.connect('admin'), db.connect('operator')
    login = db.roles['operator']
    # Temporarily expose a route to reader so its internal authorization is tested,
    # rather than mistaking an EXECUTE ACL denial for caller-role correctness.
    with owner.cursor() as cur:
        cur.execute(identifiers.SQL('GRANT v99_core_reader TO {}').format(identifiers.Identifier(login)))
        cur.execute('GRANT EXECUTE ON FUNCTION v99_core.v99_core_start(uuid,text,text), v99_core.v99_core_caller_role() TO v99_core_reader')
    owner.commit()
    try:
        assert t.sql(operator, 'SELECT session_user::text') == login
        assert t.sql(operator, "SELECT rolsuper FROM pg_roles WHERE rolname=current_user") is False
        t.sql(operator, 'SET ROLE v99_core_reader')
        assert t.sql(operator, 'SELECT session_user::text') == login
        assert t.sql(operator, 'SELECT current_user::text') == 'v99_core_reader'
        assert t.call(operator, 'caller_role') == 'v99_core_reader'
        t.refused(t.call(operator, 'start', None, 'downgraded caller', _request('downgraded')), 'unauthorized')
        operator.commit()
        t.sql(operator, 'RESET ROLE')
        started = t.good(t.ce_start(operator, 'restored operator', _request('restored')))
        operator.commit()
        t.good(t.call(operator, 'cancel', None, started['run_id'], _request('restored-cancel')))
        operator.commit()
    finally:
        operator.rollback()
        t.sql(operator, 'RESET ROLE')
        operator.commit()
        with owner.cursor() as cur:
            cur.execute('REVOKE EXECUTE ON FUNCTION v99_core.v99_core_start(uuid,text,text), v99_core.v99_core_caller_role() FROM v99_core_reader')
            cur.execute(identifiers.SQL('REVOKE v99_core_reader FROM {}').format(identifiers.Identifier(login)))
        owner.commit()
        operator.close()
        owner.close()


def test_same_session_shadowing(db, t):
    """Q5: public/temp shadows coexist in the very session invoking definer APIs."""
    operator, started = _start(db, t, 'shadowing')
    c = db.connect('admin')
    try:
        for table in sorted(CONTROL_TABLES):
            with c.cursor() as cur:
                cur.execute(identifiers.SQL('CREATE TEMP TABLE {} (shadow_marker integer)').format(identifiers.Identifier(table)))
                cur.execute(identifiers.SQL('CREATE TABLE public.{} (shadow_marker integer)').format(identifiers.Identifier(table)))
        for namespace in ('pg_temp', 'public'):
            for name, args, returns in (('v99_core_caller_role', '', 'name'), ('v99_core_has_role', 'text', 'boolean')):
                with c.cursor() as cur:
                    cur.execute(identifiers.SQL("CREATE FUNCTION {}.{}({}) RETURNS {} LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'shadow invoked'; END $$").format(
                        identifiers.Identifier(namespace), identifiers.Identifier(name), identifiers.SQL(args), identifiers.SQL(returns)))
        t.sql(c, 'SET LOCAL ROLE v99_core_operator')
        t.sql(c, 'SET LOCAL search_path=pg_temp,public,v99_core')
        assert t.sql(c, 'SELECT current_user::text') == 'v99_core_operator'
        assert t.sql(c, "SELECT rolsuper FROM pg_roles WHERE rolname=current_user") is False
        assert t.sql(c, "SELECT to_regclass('core_runs')::text") == 'core_runs'
        assert t.sql(c, "SELECT to_regclass('pg_temp.core_runs')=to_regclass('core_runs')") is True
        assert t.good(t.call(c, 'poll', None, started['run_id'], 1))['run_id'] == started['run_id']
        shadow_start = t.good(t.ce_start(c, 'fixed path survives shadows', _request('shadow-start')))
        assert t.good(t.call(c, 'poll', None, shadow_start['run_id'], 1))['status'] == 'running'
        # Remove temp objects so public shadows become the first actual match;
        # retaining both at once would only exercise the pg_temp precedence.
        t.sql(c, 'RESET ROLE')
        for table in sorted(CONTROL_TABLES):
            with c.cursor() as cur:
                cur.execute(identifiers.SQL('DROP TABLE pg_temp.{}').format(identifiers.Identifier(table)))
        for name, args in (('v99_core_caller_role', ''), ('v99_core_has_role', 'text')):
            with c.cursor() as cur:
                cur.execute(identifiers.SQL('DROP FUNCTION pg_temp.{}({})').format(identifiers.Identifier(name), identifiers.SQL(args)))
        t.sql(c, 'SET LOCAL ROLE v99_core_operator')
        assert t.sql(c, "SELECT to_regclass('public.core_runs')=to_regclass('core_runs')") is True
        assert t.good(t.call(c, 'poll', None, started['run_id'], 1))['run_id'] == started['run_id']
        assert t.good(t.ce_start(c, 'public-only shadows', _request('public-shadow')))['status'] == 'running'
    finally:
        c.rollback()  # Removes all shadows and the probe run atomically.
        c.close()
        operator.close()


def test_all_table_and_private_acl(db, t):
    """Q5: every table/private helper has effective ACL and real denied SQL."""
    owner = db.connect('admin')
    tables = t.sql(owner, "SELECT array_agg(c.relname ORDER BY c.relname) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='v99_core' AND c.relkind IN ('r','p')")
    assert set(tables) == CONTROL_TABLES
    # Every denied statement is savepoint-rolled back by the shared helper;
    # even an accidental grant cannot persist probe mutations.
    owner.commit()
    for alias in ('operator', 'service', 'reader'):
        c = db.connect(alias)
        for table in sorted(CONTROL_TABLES):
            column = {'core_meta': 'singleton', 'core_tools': 'name', 'core_effect_pins': 'effect_id',
                      'core_requests': 'request_id'}.get(table, 'run_id')
            for privilege in ('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'):
                assert t.sql(owner, 'SELECT has_table_privilege(%s,%s,%s)',
                             (db.roles[alias], 'v99_core.' + table, privilege)) is False, (alias, table, privilege)
            for statement in (f'SELECT * FROM v99_core.{table} LIMIT 0',
                              f'INSERT INTO v99_core.{table} DEFAULT VALUES',
                              f'UPDATE v99_core.{table} SET {column}={column} WHERE false',
                              f'DELETE FROM v99_core.{table} WHERE false', f'TRUNCATE v99_core.{table}'):
                t._assert_raises_sqlstate(c, '42501', statement)
        for namespace in ('v99_core', 'public'):
            t._assert_raises_sqlstate(c, '42501', f'CREATE TABLE {namespace}.infra_create_probe(x integer)')
            t._assert_raises_sqlstate(c, '42501', f'CREATE FUNCTION {namespace}.infra_create_probe() RETURNS integer LANGUAGE sql AS $$ SELECT 1 $$')
        t._assert_raises_sqlstate(c, '42501', 'CREATE TEMP TABLE infra_temp_probe(x integer)')
        t._assert_raises_sqlstate(c, '42501', 'CREATE SCHEMA infra_create_probe')
        c.rollback()
        c.close()
    routes = {
        'operator': {'start', 'poll', 'wait_check', 'cancel', 'steer', 'respond'},
        'reader': {'poll', 'wait_check'},
        'service': {'driver_acquire', 'discover', 'claim_effect', 'worker_history', 'accept_receipt', 'recover_unknown'},
    }
    with owner.cursor() as cur:
        cur.execute("""SELECT p.oid::bigint,p.proname,pg_catalog.oidvectortypes(p.proargtypes),
            EXISTS(SELECT 1 FROM aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a WHERE a.grantee=0 AND a.privilege_type='EXECUTE')
            FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname='v99_core' AND p.proname LIKE 'v99_core_%%'""")
        functions = cur.fetchall()
    for alias, allowed in routes.items():
        c = db.connect(alias)
        for oid, name, argument_types, public_execute in functions:
            assert public_execute is False, name
            allowed_route = name.removeprefix('v99_core_') in allowed
            assert t.sql(owner, 'SELECT has_function_privilege(%s,%s::oid,\'EXECUTE\')', (db.roles[alias], oid)) == allowed_route, (alias, name)
            if not any(name.removeprefix('v99_core_') in group for group in routes.values()):
                # STRICT functions may short-circuit NULL without invoking the
                # function/ACL check. Use non-NULL typed values for every arg.
                literals = {'uuid': "'00000000-0000-0000-0000-000000000001'::uuid", 'text': "'infra'::text",
                            'jsonb': "'{}'::jsonb", 'bigint': '1::bigint', 'integer': '1::integer',
                            'numeric': '1::numeric', 'boolean': 'false', 'text[]': "ARRAY['infra']::text[]"}
                arguments = ','.join(literals[datatype.strip()] for datatype in argument_types.split(',')) if argument_types else ''
                t._assert_raises_sqlstate(c, '42501', f'SELECT v99_core.{name}({arguments})')
        # Explicit publish call is load bearing: service must not split T2.
        if alias == 'service':
            t._assert_raises_sqlstate(c, '42501', 'SELECT v99_core.v99_core_publish_snapshot(NULL::uuid,NULL::text,NULL::text,NULL::bigint,NULL::bigint,NULL::jsonb)')
        c.rollback()
        c.close()
    owner.rollback()
    owner.close()


def test_fresh_object_default_acl(db, t):
    """Q5: freshly created objects must actually inherit private defaults."""
    owner = db.connect('admin')
    # No explicit REVOKE on these probes: catalog inspection alone is insufficient.
    try:
        t.sql(owner, 'CREATE FUNCTION v99_core.infra_default_function() RETURNS integer LANGUAGE sql AS $$ SELECT 1 $$')
        t.sql(owner, 'CREATE TABLE v99_core.infra_default_table(x integer)')
        t.sql(owner, 'CREATE SEQUENCE v99_core.infra_default_sequence')
        owner.commit()
        private_default = t.sql(owner, """SELECT NOT EXISTS (SELECT 1 FROM pg_proc p,
            LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a
            WHERE p.oid='v99_core.infra_default_function()'::regprocedure AND a.grantee=0 AND a.privilege_type='EXECUTE')""")
        for alias in ('service', 'operator', 'reader'):
            c = db.connect(alias)
            for statement in ('SELECT v99_core.infra_default_function()',
                              'SELECT * FROM v99_core.infra_default_table',
                              "SELECT nextval('v99_core.infra_default_sequence')"):
                t._assert_raises_sqlstate(c, '42501', statement)
            c.rollback()
            c.close()
        assert private_default is True, 'fresh function has default PUBLIC EXECUTE'
    finally:
        owner.rollback()
        for kind, name in (('FUNCTION', 'infra_default_function()'), ('TABLE', 'infra_default_table'), ('SEQUENCE', 'infra_default_sequence')):
            t.sql(owner, f'DROP {kind} IF EXISTS v99_core.{name}')
        owner.commit()
        owner.close()


def historical_dependency_violations(sources):
    """Conservative source check, not a proof about arbitrary dynamic Python."""
    violations = []
    forbidden = re.compile(r'(?i)(?:\bv(?:8|13)(?:[./\\]|_\w+)|\bpgmq\b)')
    for name, source in sources.items():
        if name.endswith('.py'):
            tree = ast.parse(source, filename=name)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    candidates = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    candidates = [node.module or '']
                elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                    candidates = [node.value]
                else:
                    continue
                for candidate in candidates:
                    if forbidden.search(candidate):
                        violations.append((name, candidate))
        else:
            for match in forbidden.finditer(source):
                violations.append((name, match.group()))
    return violations


def host_control_table_violations(source):
    # Inspect Python SQL literals (also f-string constant pieces), covering every
    # control relation. Administrative CREATE/DROP TRIGGER fault injection is not
    # a host table read/write: UPDATE ON in a trigger DDL is deliberately distinct.
    pattern = re.compile(r'(?i)\b(?:FROM|JOIN|UPDATE|INTO|TRUNCATE(?:\s+TABLE)?)\s+'
                         r'(?:ONLY\s+)?(?:"?\w+"?\s*\.\s*)?"?('
                         + '|'.join(sorted(CONTROL_TABLES)) + r')\b')
    tree = ast.parse(source)
    strings = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    return sorted({match.group(1).lower() for value in strings for match in pattern.finditer(value)})


def test_historical_and_host_static_negatives(db, t):
    """Q10: prove scanners reject historical paths/imports/SQL and every table."""
    root = Path(__file__).resolve().parent
    sources = {name: (root / name).read_text(encoding='utf-8') for name in ('__init__.py', 'load.py', 'setup_db.py', 'catalog.py')}
    sources.update({path.name: path.read_text(encoding='utf-8') for path in (root / 'sql').glob('*.sql')})
    host_source = '\n'.join(inspect.getsource(cls) for cls in (t.FakeHost, t.FakeLLM, t.FakeTool))
    sources['fake_host.py'] = host_source
    assert historical_dependency_violations(sources) == []
    assert host_control_table_violations(host_source) == []
    for source in ('import v8.load', 'from v13.load import load_sql',
                   'from v13.loop_driver.driver import Driver', 'import v8.loop.worker',
                   'from pgmq import Queue', 'loader = "v13/load.py"',
                   'loader = "v8/load.py"', 'query = "SELECT public.v13_ce_start(NULL)"',
                   'query = "SELECT pgmq.read(\'old\', 1)"'):
        assert historical_dependency_violations({'negative.py': source}), source
    for source in ('SELECT * FROM pgmq.q_old', 'SELECT public.v13_ce_start(NULL)', '\\i v8/schema/schema.sql', '\\i v13/schema/v13_core.sql'):
        assert historical_dependency_violations({'negative.sql': source}), source
    for table in sorted(CONTROL_TABLES):
        for statement in (f'SELECT * FROM v99_core.{table}', f'INSERT INTO "v99_core"."{table}" DEFAULT VALUES',
                          f'UPDATE {table} SET x=1', f'DELETE FROM {table}', f'TRUNCATE {table}'):
            assert host_control_table_violations('query = ' + repr(statement)) == [table], statement
    # A projection-only call remains allowed; banning every SQL string would be vacuous.
    assert not host_control_table_violations('query = "SELECT v99_core.v99_core_worker_history(%s,%s,%s)"')
    assert not host_control_table_violations('query = "CREATE TRIGGER fault BEFORE UPDATE ON v99_core.core_snapshots EXECUTE FUNCTION fault()"')
    assert not historical_dependency_violations({'allowed.py': 'from v99.core.load import load_core'})


def run_checks(db, t):
    """Run Q3/Q5/Q10/Q12 under the caller's existing Unix-only fixture."""
    for check in (test_current_tool_failure_cancels_successors, test_history_projection_and_fake_consumption,
                  test_cached_discover_bound_claim, test_set_role_real_caller, test_same_session_shadowing,
                  test_all_table_and_private_acl, test_historical_and_host_static_negatives,
                  test_fresh_object_default_acl):
        check(db, t)
        print('[infrastructure passed]', check.__name__)


def _group_snapshot(conn, groups):
    with conn.cursor() as cur:
        cur.execute('SELECT to_jsonb(r) FROM pg_roles r WHERE rolname=ANY(%s) ORDER BY rolname', (list(groups),))
        roles = [row[0] for row in cur.fetchall()]
        cur.execute('SELECT to_jsonb(m) FROM pg_auth_members m WHERE roleid=ANY(SELECT oid FROM pg_roles WHERE rolname=ANY(%s)) ORDER BY roleid,member,grantor', (list(groups),))
        memberships = [row[0] for row in cur.fetchall()]
    return roles, memberships


def run_group_lifecycle_checks(t):
    """Q9 integration hook: call OUTSIDE every live setup_db fixture.

    The maintenance lock protects preparation/inspection. It is released before
    calling setup_db(), which acquires its own lifecycle lock; no nested setup.
    Existing roles are never altered/dropped, and all probes clean up in finally.
    """
    from v99.core import setup_db as setup

    with contextlib.closing(psycopg2.connect(setup.local_dsn('postgres'))) as c:
        c.autocommit = True
        created = []
        member = 'infra_group_member_' + uuid.uuid4().hex
        locked = False
        member_created = False

        def lock():
            nonlocal locked
            t.sql(c, 'SELECT pg_advisory_lock(%s)', (setup._LOCK_KEY,))
            locked = True

        def unlock():
            nonlocal locked
            assert t.sql(c, 'SELECT pg_advisory_unlock(%s)', (setup._LOCK_KEY,)) is True
            locked = False

        try:
            lock()
            for group in setup.GROUPS:
                oid, was_created = setup._create_or_check_group(c, group)
                if was_created:
                    created.append((group, oid))
            with c.cursor() as cur:
                cur.execute(identifiers.SQL('CREATE ROLE {} NOLOGIN').format(identifiers.Identifier(member)))
                member_created = True
                for group in setup.GROUPS:
                    cur.execute(identifiers.SQL('GRANT {} TO {}').format(identifiers.Identifier(group), identifiers.Identifier(member)))
            before = _group_snapshot(c, setup.GROUPS)
            unlock()
            with setup.setup_db(load_sql=False) as db:
                assert db._created_groups == {}, db._created_groups
                during = _group_snapshot(c, setup.GROUPS)
                assert during[0] == before[0], 'preexisting group attributes/OIDs changed'
                assert all(membership in during[1] for membership in before[1]), 'preexisting membership changed'
                assert len(during[1]) == len(before[1]) + len(setup.GROUPS)
            lock()
            assert _group_snapshot(c, setup.GROUPS) == before, 'preexisting group removed or membership/attributes changed'
            # Only roles created by this probe may be made abnormal. For each
            # fixed group exercise setup's public failure/cleanup path.
            for group, oid in created:
                with c.cursor() as cur:
                    cur.execute(identifiers.SQL('ALTER ROLE {} LOGIN').format(identifiers.Identifier(group)))
                abnormal = _group_snapshot(c, setup.GROUPS)
                resources = t.sql(c, "SELECT jsonb_build_array((SELECT coalesce(jsonb_agg(to_jsonb(d) ORDER BY datname),'[]') FROM pg_database d WHERE datname LIKE 'v99_core_%%'),(SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY rolname),'[]') FROM pg_roles r WHERE rolname LIKE 'v99_core_%%'))")
                unlock()
                try:
                    fixture = setup.setup_db(load_sql=False)
                except RuntimeError as exc:
                    assert 'expected inert NOLOGIN fixture group' in str(exc), str(exc)
                else:
                    fixture.cleanup()
                    raise AssertionError('abnormal fixed group was accepted: ' + group)
                lock()
                assert _group_snapshot(c, setup.GROUPS) == abnormal
                assert t.sql(c, "SELECT jsonb_build_array((SELECT coalesce(jsonb_agg(to_jsonb(d) ORDER BY datname),'[]') FROM pg_database d WHERE datname LIKE 'v99_core_%%'),(SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY rolname),'[]') FROM pg_roles r WHERE rolname LIKE 'v99_core_%%'))") == resources
                with c.cursor() as cur:
                    cur.execute(identifiers.SQL('ALTER ROLE {} NOLOGIN').format(identifiers.Identifier(group)))
                assert setup._role_state(c, group)[0] == oid
            # If all fixed groups predate this probe, don't mutate them just to
            # inject a fault. The same validator is exercised on a fresh role.
            if not created:
                with c.cursor() as cur:
                    cur.execute(identifiers.SQL('ALTER ROLE {} LOGIN').format(identifiers.Identifier(member)))
                try:
                    setup._create_or_check_group(c, member)
                except RuntimeError as exc:
                    assert 'expected inert NOLOGIN fixture group' in str(exc)
                else:
                    raise AssertionError('abnormal existing group validator accepted LOGIN')
            assert _group_snapshot(c, setup.GROUPS) == before
            print('[infrastructure passed] run_group_lifecycle_checks (preexisting groups/OIDs/members preserved; abnormal group fail-closed)')
        finally:
            if not locked:
                lock()
            if member_created:
                with c.cursor() as cur:
                    cur.execute(identifiers.SQL('DROP ROLE {}').format(identifiers.Identifier(member)))
            for group, oid in reversed(created):
                assert setup._role_state(c, group)[0] == oid
                with c.cursor() as cur:
                    cur.execute(identifiers.SQL('DROP ROLE {}').format(identifiers.Identifier(group)))
            unlock()
