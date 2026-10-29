"""CDP4-M: model settlement, reducer purity, digests and rollback injection."""
from __future__ import annotations
import contextlib
import json
import uuid

from psycopg2 import sql
from psycopg2.extras import Json
from dp4_support import (Server, TestDB, snapshot, query, api, env, no_write, claim, settle,
                         prepare_run, model_body, tool_call, q1, rows, replace_function)


def _plan(db, run_id):
    state = q1(db, 'SELECT state FROM v24_cordis.runs WHERE id=%s', (run_id,))
    budget = q1(db, 'SELECT remaining_steps FROM v24_cordis.runs WHERE id=%s', (run_id,))
    return state, budget


def _model_contract(db, run_id):
    return q1(db, "SELECT i.contracts->'model_call' FROM v24_cordis.pins p "
                  "JOIN v24_cordis.contributions c ON c.id=p.contribution_id "
                  "JOIN v24_cordis.fibers f ON f.id=c.fiber_id "
                  "JOIN v24_cordis.installs i ON i.id=f.install_id "
                  "WHERE p.consumer_run_id=%s AND p.key='model'", (run_id,))


def _insert_model(db, run_id, digests=None):
    run = rows(db, 'SELECT owner_fiber_id,owner_episode_id FROM v24_cordis.runs WHERE id=%s',
               (run_id,))[0]
    pin = q1(db, "SELECT id FROM v24_cordis.pins WHERE consumer_run_id=%s AND key='model'",
             (run_id,))
    contract = _model_contract(db, run_id)
    if digests is None:
        digests = q1(db, 'SELECT v24_cordis.run_digests(%s)', (run_id,))
    effect = uuid.uuid4()
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, "INSERT INTO v24_cordis.effects(id,kind,status,fiber_id,episode_id,run_id,"
                    "input,request_actor) VALUES(%s,'model_call','ready',%s,%s,%s,%s,%s)",
              (effect, run[0], run[1], run_id,
               Json({'v': 1, 'run_id': str(run_id), 'pin_id': str(pin), 'key': 'model',
                     'digests': digests,
                     'contract': {'contract_version': contract['contract_version'],
                                  'handler_digest': contract['handler_digest']}}),
               db.roles['service']))
        conn.commit()
    return effect


def test_m1(db):
    x = prepare_run(db, 3)
    c = claim(db, x['model_effect'])
    body = model_body([tool_call('c1', 'tool', {'x': 1})], usage={'input': 2, 'output': 3})
    got = settle(db, x['model_effect'], body, c['claim'])
    assert got['disposition'] == 'committed' and len(got['emitted']) == 1, got
    state, budget = _plan(db, x['run_id'])
    assert budget == 2, budget
    assert state['step'] == 1 and state['phase'] == 'tools', state
    assert state['batch'] == [{'ordinal': 0, 'key': 'tool', 'call_id': 'c1'}], state
    tool = rows(db, "SELECT parent_id,ordinal,status,input FROM v24_cordis.effects "
                    "WHERE run_id=%s AND kind='tool_call'", (x['run_id'],))[0]
    assert tool[0] == x['model_effect'] and tool[1] == 0 and tool[2] == 'ready', tool
    ti = tool[3]
    assert set(ti) == {'v', 'run_id', 'pin_id', 'key', 'descriptor_digest', 'call_id', 'args', 'contract'}, ti
    assert ti['key'] == 'tool' and ti['call_id'] == 'c1' and ti['args'] == {'x': 1}
    ev = q1(db, "SELECT payload FROM v24_cordis.events WHERE effect_id=%s AND event_kind='run_progress'",
            (x['model_effect'],))
    assert ev['step'] == 1 and ev['remaining_steps'] == 2 and ev['phase'] == 'tools' and not ev['sealed'], ev
    print('[CDP4-M1] e8 model success: budget 3->2, step=1/tools, one exact tool successor')


def test_m2(db, tamper):
    x = prepare_run(db, 3)
    c = claim(db, x['model_effect'])
    got = settle(db, x['model_effect'], model_body([tool_call('c1')]), c['claim'])
    assert got['disposition'] == 'committed', got
    digests = q1(db, 'SELECT v24_cordis.run_digests(%s)', (x['run_id'],))
    digests[tamper] = '0' * 64
    bad = _insert_model(db, x['run_id'], digests)
    bc = claim(db, bad)
    assert bc['disposition'] == 'claimed', bc
    before = _snapshot(db)
    res = settle(db, bad, model_body([tool_call('c1')]), bc['claim'])
    assert res['error']['code'] == 'invalid_outcome', res
    assert _snapshot(db) == before
    print(f'[CDP4-M2:{tamper}] digest drift is invalid_outcome with zero write')


def _snapshot(db):
    with contextlib.closing(db.connect('owner')) as conn:
        return snapshot(conn)


def test_m3(db):
    x = prepare_run(db, 3)
    c = claim(db, x['model_effect'])
    good = model_body([tool_call('c1')])
    bad = []
    extra = json.loads(json.dumps(good)); extra['result']['extra'] = 1; bad.append(extra)
    inter = json.loads(json.dumps(good)); inter['result']['interaction'] = {}; bad.append(inter)
    final_tool = model_body([tool_call('c1')], final=True); bad.append(final_tool)
    many = model_body([tool_call(f'c{i}', 'tool' if i == 0 else f'nope{i}') for i in range(17)])
    bad.append(many)
    unknown_key = model_body([tool_call('c1', 'nope')]); bad.append(unknown_key)
    dup = model_body([tool_call('same', 'tool'), tool_call('same', 'tool')]); bad.append(dup)
    usage = model_body([tool_call('c1')], usage={'x': -1}); bad.append(usage)
    text = model_body([tool_call('c1')], text=123); bad.append(text)
    for body in bad:
        before = _snapshot(db)
        got = settle(db, x['model_effect'], body, c['claim'])
        assert got['error']['code'] == 'invalid_outcome', (body, got)
        assert _snapshot(db) == before
    print('[CDP4-M3] unknown key/interaction/final+N/N>16/key∉tools/duplicate/usage/text are zero-write')


def test_m4(db):
    oid = q1(db, "SELECT oid FROM pg_proc WHERE oid='v24_cordis.reduce_chat_tool(jsonb,jsonb)'::regprocedure")
    assert q1(db, 'SELECT provolatile FROM pg_proc WHERE oid=%s', (oid,)) == 'i'
    def closure(oid):
        return q1(db, '''WITH RECURSIVE d(classid,objid,refclassid,refobjid) AS (
            SELECT classid,objid,refclassid,refobjid FROM pg_depend
             WHERE classid='pg_proc'::regclass AND objid=%s
            UNION
            SELECT g.classid,g.objid,g.refclassid,g.refobjid FROM pg_depend g
             JOIN d ON g.classid=d.refclassid AND g.objid=d.refobjid
             WHERE d.refclassid='pg_proc'::regclass)
          SELECT jsonb_build_object(
            'relations',count(*) FILTER (WHERE d.refclassid='pg_class'::regclass),
            'functions',count(DISTINCT d.refobjid) FILTER (WHERE d.refclassid='pg_proc'::regclass
              AND p.pronamespace<>'pg_catalog'::regnamespace),
            'missing_sql_body',count(DISTINCT d.refobjid) FILTER (WHERE d.refclassid='pg_proc'::regclass
              AND p.pronamespace<>'pg_catalog'::regnamespace AND p.prosqlbody IS NULL))
          FROM d LEFT JOIN pg_proc p ON p.oid=d.refobjid''', (oid,))
    dep = closure(oid)
    assert dep['relations'] == 0, ('reducer has a relation dependency', dep)
    assert dep['functions'] >= 5, ('dependency chain stopped early', dep)
    assert dep['missing_sql_body'] == 0, ('non-catalog callee has no parsed body', dep)
    replace_function(db, '''CREATE OR REPLACE FUNCTION v24_cordis.dp4_probe_runs() RETURNS bigint
      LANGUAGE sql BEGIN ATOMIC SELECT count(*) FROM v24_cordis.runs; END''')
    try:
        poid = q1(db, "SELECT oid FROM pg_proc WHERE oid='v24_cordis.dp4_probe_runs()'::regprocedure")
        assert closure(poid)['relations'] > 0, 'BEGIN ATOMIC probe did not expose its table dependency'
    finally:
        with contextlib.closing(db.connect('owner')) as conn:
            query(conn, sql.SQL('SET ROLE {}').format(sql.Identifier(db.groups['owner'])))
            query(conn, 'DROP FUNCTION v24_cordis.dp4_probe_runs()')
            conn.commit()
    print('[CDP4-M4] reducer is IMMUTABLE; closure has parsed non-catalog bodies and no pg_class; a reading probe is detected')


def test_m5(db):
    x = prepare_run(db, 3)
    c = claim(db, x['model_effect'])
    body = model_body([tool_call('c1')])
    replace_function(db, '''CREATE OR REPLACE FUNCTION v24_cordis.dp4_fail() RETURNS trigger
      LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'inject'; END $$''')
    before = _snapshot(db)
    for point, ddl in (
        ('receipt', 'CREATE TRIGGER dp4_fail BEFORE INSERT ON v24_cordis.events '
                    'FOR EACH ROW EXECUTE FUNCTION v24_cordis.dp4_fail()'),
        ('event', 'CREATE TRIGGER dp4_fail BEFORE INSERT ON v24_cordis.effects '
                  'FOR EACH ROW WHEN (NEW.parent_id IS NOT NULL) EXECUTE FUNCTION v24_cordis.dp4_fail()'),
        ('successor', 'CREATE TRIGGER dp4_fail AFTER INSERT ON v24_cordis.effects '
                      'FOR EACH ROW WHEN (NEW.parent_id IS NOT NULL) EXECUTE FUNCTION v24_cordis.dp4_fail()'),
    ):
        with contextlib.closing(db.connect('owner')) as conn:
            query(conn, sql.SQL('SET ROLE {}').format(sql.Identifier(db.groups['owner'])))
            query(conn, ddl); conn.commit()
        try:
            with contextlib.closing(db.connect('service')) as conn:
                try:
                    api(conn, x['model_effect'], env('success', body, c['claim']))
                except Exception:
                    conn.rollback()
                else:
                    raise AssertionError('injection did not fire: ' + point)
            assert _snapshot(db) == before, point
            assert q1(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s',
                      (x['model_effect'],)) == 'claimed'
        finally:
            with contextlib.closing(db.connect('owner')) as conn:
                query(conn, sql.SQL('SET ROLE {}').format(sql.Identifier(db.groups['owner'])))
                query(conn, 'DROP TRIGGER dp4_fail ON ' +
                            ('v24_cordis.events' if point == 'receipt' else 'v24_cordis.effects'))
                conn.commit()
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, sql.SQL('SET ROLE {}').format(sql.Identifier(db.groups['owner'])))
        query(conn, 'DROP FUNCTION v24_cordis.dp4_fail()')
        conn.commit()
    print('[CDP4-M5] failures after receipt, after event and after successor roll back the advance')


def main():
    with Server() as server:
        with TestDB(server) as db:
            test_m1(db)
        for tamper in ('policy', 'schema', 'toolset'):
            with TestDB(server) as db:
                test_m2(db, tamper)
        with TestDB(server) as db:
            test_m3(db)
        with TestDB(server) as db:
            test_m4(db)
        with TestDB(server) as db:
            test_m5(db)
    print('[passed] CDP4-M')


if __name__ == '__main__':
    main()
