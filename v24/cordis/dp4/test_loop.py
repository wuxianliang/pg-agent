"""CDP4-T: tool settlement, batch barrier, pin semantics and unknown siblings."""
from __future__ import annotations
import contextlib
import threading
import time
import uuid

from psycopg2.extras import Json
from dp4_support import (Server, TestDB, snapshot, query, api, env, claim, settle,
                         prepare_run, model_body, tool_call, tool_body, q1, rows, no_write)


def _snap(db):
    with contextlib.closing(db.connect('owner')) as conn:
        return snapshot(conn)


def _batch(db, run_id):
    return q1(db, 'SELECT state FROM v24_cordis.runs WHERE id=%s', (run_id,))


def _budget(db, run_id):
    return q1(db, 'SELECT remaining_steps FROM v24_cordis.runs WHERE id=%s', (run_id,))


def _tools(db, run_id):
    return rows(db, "SELECT id,ordinal,input FROM v24_cordis.effects WHERE run_id=%s "
                    "AND kind='tool_call' ORDER BY ordinal", (run_id,))


def _continuation(db, run_id):
    return rows(db, "SELECT id,parent_id,ordinal,input FROM v24_cordis.effects "
                    "WHERE run_id=%s AND kind='model_call' AND status='ready'", (run_id,))


def prepare_tools(db, n=2, steps=4):
    keys = ('tool', 'tool2') if n == 2 else ('tool',)
    x = prepare_run(db, steps, keys)
    c = claim(db, x['model_effect'])
    body = model_body([tool_call(f'c{i}', keys[i], {'i': i}) for i in range(n)])
    got = settle(db, x['model_effect'], body, c['claim'])
    assert got['disposition'] == 'committed', got
    tools = _tools(db, x['run_id'])
    assert len(tools) == n, tools
    assert _budget(db, x['run_id']) == steps - 1, _budget(db, x['run_id'])
    return x, tools


def test_t1_t2(db):
    x, tools = prepare_tools(db, 2, 4)
    t0, t1 = tools[0], tools[1]
    c0 = claim(db, t0[0])
    r0 = settle(db, t0[0], tool_body(), c0['claim'])
    assert r0['disposition'] == 'committed' and r0['emitted'] == [], r0
    st = _batch(db, x['run_id'])
    assert st['step'] == 2 and st['phase'] == 'tools' and len(st['batch']) == 2, st
    assert _budget(db, x['run_id']) == 2, _budget(db, x['run_id'])
    assert _continuation(db, x['run_id']) == []
    assert q1(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (t0[0],)) == 'succeeded'
    c1 = claim(db, t1[0])
    r1 = settle(db, t1[0], tool_body(output={'ok': True}), c1['claim'])
    assert r1['disposition'] == 'committed' and len(r1['emitted']) == 1, r1
    st = _batch(db, x['run_id'])
    assert st['step'] == 3 and st['phase'] == 'model' and st['batch'] == [], st
    assert _budget(db, x['run_id']) == 1, _budget(db, x['run_id'])
    cont = _continuation(db, x['run_id'])
    assert len(cont) == 1 and cont[0][1] == t1[0] and cont[0][2] == 0, cont
    assert cont[0][3]['key'] == 'model', cont
    assert cont[0][3]['pin_id'] == str(q1(
        db, "SELECT id FROM v24_cordis.pins WHERE consumer_run_id=%s AND key='model'",
        (x['run_id'],))), cont
    assert cont[0][3]['digests'] == q1(db, 'SELECT v24_cordis.run_digests(%s)',
                                       (x['run_id'],)), cont
    before = _snap(db)
    replay = settle(db, t1[0], tool_body(output={'ok': True}), c1['claim'])
    assert replay['disposition'] == 'replay' and replay['emitted'] == [], replay
    assert _continuation(db, x['run_id']) == cont
    assert _snap(db) == before
    print('[CDP4-T1/T2a] N tools serialize; only the last sibling emits one model continuation; replay is zero-write')


def test_t2_concurrent(db):
    x, tools = prepare_tools(db, 2, 4)
    c0, c1 = claim(db, tools[0][0]), claim(db, tools[1][0])
    barrier = threading.Barrier(2)
    out = []
    def work(effect, token):
        barrier.wait()
        try:
            out.append((effect, settle(db, effect, tool_body(), token)))
        except Exception as exc:
            out.append((effect, exc))
    threads = [threading.Thread(target=work, args=(tools[i][0], (c0, c1)[i]['claim']))
               for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(isinstance(r, dict) and r.get('disposition') == 'committed' for _, r in out), out
    emitting = [(effect, r) for effect, r in out if len(r['emitted']) == 1]
    quiet = [(effect, r) for effect, r in out if r['emitted'] == []]
    assert len(emitting) == 1 and len(quiet) == 1, out
    closer, closed = emitting[0]
    assert closed['disposition'] == 'committed', closed
    cont = _continuation(db, x['run_id'])
    assert len(cont) == 1 and cont[0][1] == closer, cont
    assert _batch(db, x['run_id'])['batch'] == []
    assert _budget(db, x['run_id']) == 1, _budget(db, x['run_id'])
    assert q1(db, "SELECT count(*) FROM v24_cordis.effects WHERE run_id=%s "
                  "AND kind='tool_call' AND status='succeeded'", (x['run_id'],)) == 2
    print('[CDP4-T2b] two connections settle two siblings; only the batch closer emits one continuation')


def test_t3_expired_lease(db):
    x, tools = prepare_tools(db, 2, 4)
    c0, c1 = claim(db, tools[0][0], 1), claim(db, tools[1][0], 1)
    time.sleep(0.02)
    assert q1(db, 'SELECT bool_and(lease_until<clock_timestamp()) FROM v24_cordis.effects '
                  'WHERE id IN (%s,%s)', (tools[0][0], tools[1][0])) is True
    r0 = settle(db, tools[0][0], tool_body(), c0['claim'])
    assert r0['emitted'] == [] and _continuation(db, x['run_id']) == [], r0
    assert _batch(db, x['run_id'])['step'] == 2, _batch(db, x['run_id'])
    assert _batch(db, x['run_id'])['batch'][0]['call_id'] == 'c0'
    assert _budget(db, x['run_id']) == 2, _budget(db, x['run_id'])
    r1 = settle(db, tools[1][0], tool_body(), c1['claim'])
    assert len(r1['emitted']) == 1 and len(_continuation(db, x['run_id'])) == 1, r1
    assert _batch(db, x['run_id'])['batch'] == []
    print('[CDP4-T3] an expired lease is still a live sibling; no early continuation')


def _tool_pin(db, run_id):
    return rows(db, "SELECT p.id,c.id,c.descriptor FROM v24_cordis.pins p "
                    "JOIN v24_cordis.contributions c ON c.id=p.contribution_id "
                    "WHERE p.consumer_run_id=%s AND p.key='tool'", (run_id,))[0]


def test_t4_withdrawn(db):
    x, tools = prepare_tools(db, 1, 3)
    pin, contrib, desc = _tool_pin(db, x['run_id'])
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'UPDATE v24_cordis.contributions SET withdrawn_at=now() WHERE id=%s', (contrib,))
        conn.commit()
    assert q1(db, 'SELECT withdrawn_at IS NOT NULL AND released_at IS NULL '
                  'FROM v24_cordis.contributions WHERE id=%s', (contrib,)) is True
    assert q1(db, 'SELECT released_at IS NULL FROM v24_cordis.pins WHERE id=%s', (pin,)) is True
    c = claim(db, tools[0][0])
    r = settle(db, tools[0][0], tool_body(), c['claim'])
    assert r['disposition'] == 'committed' and len(r['emitted']) == 1, r
    assert _budget(db, x['run_id']) == 1, _budget(db, x['run_id'])
    print('[CDP4-T4a] a withdrawn-but-unreleased provider pin still settles the old run')


def test_t4_released(db):
    x, tools = prepare_tools(db, 1, 3)
    pin, contrib, desc = _tool_pin(db, x['run_id'])
    c = claim(db, tools[0][0])
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'UPDATE v24_cordis.pins SET released_at=now() WHERE id=%s', (pin,))
        conn.commit()
    assert q1(db, 'SELECT released_at IS NOT NULL FROM v24_cordis.pins WHERE id=%s',
              (pin,)) is True
    before = _snap(db)
    r = settle(db, tools[0][0], tool_body(), c['claim'])
    assert r['error']['code'] == 'dependency_unresolved', r
    assert _snap(db) == before
    assert q1(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s',
              (tools[0][0],)) == 'claimed'
    print('[CDP4-T4b] a released pin is dependency_unresolved with zero write')


def test_t4_model_released(db):
    x = prepare_run(db, 3)
    c = claim(db, x['model_effect'])
    pin = q1(db, "SELECT id FROM v24_cordis.pins WHERE consumer_run_id=%s AND key='model'",
             (x['run_id'],))
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'UPDATE v24_cordis.pins SET released_at=now() WHERE id=%s', (pin,))
        conn.commit()
    before = _snap(db)
    r = settle(db, x['model_effect'], model_body(final=True), c['claim'])
    assert r['error']['code'] == 'dependency_unresolved', r
    assert _snap(db) == before
    assert q1(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s',
              (x['model_effect'],)) == 'claimed'
    print('[CDP4-T4b-model] a released model pin is dependency_unresolved with zero write')


def _mismatch_effect(db, x, pin_id, key, call_id, ordinal, digest, contract):
    run = rows(db, 'SELECT owner_fiber_id,owner_episode_id FROM v24_cordis.runs WHERE id=%s',
               (x['run_id'],))[0]
    effect = uuid.uuid4()
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, "INSERT INTO v24_cordis.effects(id,parent_id,ordinal,fiber_id,episode_id,"
                    "run_id,kind,status,input,request_actor) "
                    "VALUES(%s,%s,%s,%s,%s,%s,'tool_call','ready',%s,%s)",
              (effect, x['model_effect'], ordinal, run[0], run[1], x['run_id'],
               Json({'v': 1, 'run_id': str(x['run_id']), 'pin_id': str(pin_id), 'key': key,
                     'descriptor_digest': digest, 'call_id': call_id, 'args': {},
                     'contract': {'contract_version': contract['contract_version'],
                                  'handler_digest': contract['handler_digest']}}),
               db.roles['service']))
        query(conn, "UPDATE v24_cordis.runs SET state=jsonb_set(state,'{batch}',"
                    "(state->'batch')||%s::jsonb) WHERE id=%s",
              (Json([{'ordinal': ordinal, 'key': key, 'call_id': call_id}]), x['run_id']))
        conn.commit()
    return effect


def test_t4_mismatch(db):
    x, tools = prepare_tools(db, 1, 4)
    model_pin = q1(db, "SELECT id FROM v24_cordis.pins WHERE consumer_run_id=%s AND key='model'",
                   (x['run_id'],))
    tool_pin, _, desc = _tool_pin(db, x['run_id'])
    tool_contract = q1(db, "SELECT i.contracts->'tool_call' FROM v24_cordis.pins p "
                           "JOIN v24_cordis.contributions c ON c.id=p.contribution_id "
                           "JOIN v24_cordis.fibers f ON f.id=c.fiber_id "
                           "JOIN v24_cordis.installs i ON i.id=f.install_id "
                           "WHERE p.id=%s", (tool_pin,))
    digest = q1(db, "SELECT encode(sha256(convert_to(%s::jsonb::text,'UTF8')),'hex')", (Json(desc),))
    for pin_name, key, ordinal in (('model', 'toolm', 1), ('tool', 'nope', 2), ('tool', 'model', 3)):
        pin_id = model_pin if pin_name == 'model' else tool_pin
        effect = _mismatch_effect(db, x, pin_id, key, f'x{ordinal}', ordinal, digest, tool_contract)
        if pin_name == 'model':
            # The claim contract cannot bind a model pin to a tool effect: advance refuses before settlement.
            with contextlib.closing(db.connect('service')) as conn:
                no_write(db, conn, effect, env('claim', {'lease_ms': 300000}), 'invalid_outcome')
            assert q1(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (effect,)) == 'ready'
        else:
            tc = claim(db, effect)
            assert tc.get('disposition') == 'claimed', tc
            before = _snap(db)
            with contextlib.closing(db.connect('service')) as conn:
                no_write(db, conn, effect, env('success', tool_body(), tc['claim']), 'invalid_outcome')
            assert _snap(db) == before
            assert q1(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (effect,)) == 'claimed'
    print('[CDP4-T4c] advance rejects model-pin/tool-key at claim and tool-pin/nope+model-key at '
          'settlement as invalid_outcome with zero write')


def test_t5_unknown(db):
    x, tools = prepare_tools(db, 2, 4)
    c0, c1 = claim(db, tools[0][0]), claim(db, tools[1][0])
    u = settle(db, tools[0][0], {'kind': 'tool_call'}, c0['claim'], 'unknown')
    assert u['disposition'] == 'committed' and u['emitted'] == [], u
    assert q1(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (tools[0][0],)) == 'unknown'
    st = _batch(db, x['run_id'])
    assert st['step'] == 1 and st['phase'] == 'tools' and len(st['batch']) == 2, st
    assert _budget(db, x['run_id']) == 3, _budget(db, x['run_id'])
    assert _continuation(db, x['run_id']) == []
    run = rows(db, 'SELECT owner_fiber_id,owner_episode_id FROM v24_cordis.runs WHERE id=%s',
               (x['run_id'],))[0]
    pin, contrib, desc = _tool_pin(db, x['run_id'])
    tool_contract = q1(db, "SELECT i.contracts->'tool_call' FROM v24_cordis.pins p "
                           "JOIN v24_cordis.contributions c ON c.id=p.contribution_id "
                           "JOIN v24_cordis.fibers f ON f.id=c.fiber_id "
                           "JOIN v24_cordis.installs i ON i.id=f.install_id "
                           "WHERE p.consumer_run_id=%s AND p.key='tool'", (x['run_id'],))
    digest = q1(db, "SELECT encode(sha256(convert_to(%s::jsonb::text,'UTF8')),'hex')",
                (Json(desc),))
    third = uuid.uuid4()
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, "INSERT INTO v24_cordis.effects(id,parent_id,ordinal,fiber_id,episode_id,"
                    "run_id,kind,status,input,request_actor) "
                    "VALUES(%s,%s,2,%s,%s,%s,'tool_call','ready',%s,%s)",
              (third, x['model_effect'], run[0], run[1], x['run_id'],
               Json({'v': 1, 'run_id': str(x['run_id']), 'pin_id': str(pin), 'key': 'tool',
                     'descriptor_digest': digest, 'call_id': 'c3', 'args': {},
                     'contract': {'contract_version': tool_contract['contract_version'],
                                  'handler_digest': tool_contract['handler_digest']}}),
               db.roles['service']))
        conn.commit()
    before = _snap(db)
    blocked = claim(db, third)
    assert blocked['error']['code'] == 'blocked_unknown', blocked
    assert _snap(db) == before
    assert q1(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (third,)) == 'ready'
    r1 = settle(db, tools[1][0], tool_body(), c1['claim'])
    assert r1['disposition'] == 'committed' and r1['emitted'] == [], r1
    st = _batch(db, x['run_id'])
    assert st['step'] == 2 and st['phase'] == 'tools' and len(st['batch']) == 2, st
    assert _budget(db, x['run_id']) == 2, _budget(db, x['run_id'])
    assert _continuation(db, x['run_id']) == []
    assert q1(db, 'SELECT released_at IS NULL FROM v24_cordis.pins WHERE id=%s', (pin,)) is True
    assert q1(db, 'SELECT ended_at IS NULL AND result IS NULL FROM v24_cordis.runs WHERE id=%s',
              (x['run_id'],)) is True
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, "UPDATE v24_cordis.episodes SET state='closing',outcome='retire' WHERE id=%s",
              (run[1],))
        query(conn, 'UPDATE v24_cordis.fibers SET retire_started_at=now() WHERE id=%s', (run[0],))
        conn.commit()
    plan = q1(db, 'SELECT v24_cordis.p6_plan(%s,%s)', (tools[1][0], run[0]))
    assert plan['kind'] == 'blocked_unknown', plan
    print('[CDP4-T5] unknown sibling: no continuation/seal/pin release; new claim and P6 blocked')


def test_t6_failure(db):
    x, tools = prepare_tools(db, 1, 3)
    c = claim(db, tools[0][0])
    r = settle(db, tools[0][0], tool_body('error', {'err': 'x'}), c['claim'], 'failure')
    assert r['disposition'] == 'committed' and len(r['emitted']) == 1, r
    st = _batch(db, x['run_id'])
    assert st['phase'] == 'model' and st['step'] == 2 and st['batch'] == [], st
    assert _budget(db, x['run_id']) == 1, _budget(db, x['run_id'])
    assert q1(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (tools[0][0],)) == 'failed'
    cont = _continuation(db, x['run_id'])
    assert len(cont) == 1 and cont[0][1] == tools[0][0] and cont[0][2] == 0, cont
    print('[CDP4-T6] a tool failure still closes the batch and emits one continuation')


def test_t7_replay(db):
    x, tools = prepare_tools(db, 1, 3)
    c = claim(db, tools[0][0], 1)
    time.sleep(0.02)
    r = settle(db, tools[0][0], tool_body(), c['claim'])
    assert r['disposition'] == 'committed' and len(r['emitted']) == 1, r
    assert q1(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (tools[0][0],)) == 'succeeded'
    assert len(_continuation(db, x['run_id'])) == 1
    before = _snap(db)
    d = settle(db, tools[0][0], tool_body(output={'different': True}), c['claim'])
    assert d['error']['code'] == 'receipt_conflict', d
    assert _snap(db) == before
    assert len(_continuation(db, x['run_id'])) == 1
    print('[CDP4-T7a] expired original receipt is accepted; conflicting bytes are receipt_conflict')


def test_t7_reclaim(db):
    x, tools = prepare_tools(db, 1, 3)
    c = claim(db, tools[0][0], 1)
    time.sleep(0.02)
    c2 = claim(db, tools[0][0], 300000)
    assert c2['disposition'] == 'claimed' and c2['claim']['attempt'] == 2, c2
    assert c2['claim']['fence'] > c['claim']['fence'], (c, c2)
    before = _snap(db)
    old = settle(db, tools[0][0], tool_body(), c['claim'])
    assert old['error']['code'] == 'stale_claim', old
    assert _snap(db) == before
    assert q1(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (tools[0][0],)) == 'claimed'
    r = settle(db, tools[0][0], tool_body(), c2['claim'])
    assert r['disposition'] == 'committed' and len(r['emitted']) == 1, r
    assert _budget(db, x['run_id']) == 1, _budget(db, x['run_id'])
    print('[CDP4-T7b] reclaim advances attempt/fence; old token is stale; new token settles')


def test_t7_no_replay(db):
    x = prepare_run(db, 3)
    other = __import__('dp4_support').provider(db, 'model_call', 'other', replay=(True, False))
    contract = q1(db, "SELECT contracts->'model_call' FROM v24_cordis.installs i "
                      "JOIN v24_cordis.fibers f ON f.install_id=i.id WHERE f.id=%s", (other['fiber'],))
    assert contract['replay'] == {'repeat': True, 'concurrent': False}, contract
    run2 = uuid.uuid4()
    pin = uuid.uuid4()
    contrib = q1(db, "SELECT c.id FROM v24_cordis.contributions c JOIN v24_cordis.fibers f "
                     "ON f.id=c.fiber_id WHERE f.id=%s AND c.key='other' AND c.released_at IS NULL",
                 (other['fiber'],))
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, "INSERT INTO v24_cordis.runs(id,owner_fiber_id,owner_episode_id,scope_id,state,remaining_steps) "
                    "SELECT %s,owner_fiber_id,owner_episode_id,scope_id,%s,3 FROM v24_cordis.runs WHERE id=%s",
              (run2, Json({'v': 1, 'origin': str(x['run_start']), 'step': 0, 'phase': 'model',
                           'batch': [], 'final': False}), x['run_id']))
        query(conn, "INSERT INTO v24_cordis.pins(id,consumer_run_id,key,contribution_id,provider_epoch) "
                    "VALUES(%s,%s,'other',%s,1)", (pin, run2, contrib))
        conn.commit()
    digests = q1(db, 'SELECT v24_cordis.run_digests(%s)', (run2,))
    effect = uuid.uuid4()
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, "INSERT INTO v24_cordis.effects(id,kind,status,fiber_id,episode_id,run_id,"
                    "input,request_actor) SELECT %s,'model_call','ready',owner_fiber_id,owner_episode_id,%s,%s,%s "
                    "FROM v24_cordis.runs WHERE id=%s",
              (effect, run2,
               Json({'v': 1, 'run_id': str(run2), 'pin_id': str(pin), 'key': 'other',
                     'digests': digests,
                     'contract': {'contract_version': contract['contract_version'],
                                  'handler_digest': contract['handler_digest']}}),
               db.roles['service'], run2))
        conn.commit()
    first = claim(db, effect)
    assert first['disposition'] == 'claimed', first
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, "UPDATE v24_cordis.effects SET lease_until=clock_timestamp()-interval '1 second' "
                    "WHERE id=%s", (effect,))
        conn.commit()
    before = _snap(db)
    blocked = claim(db, effect)
    assert blocked['error']['code'] == 'blocked_unknown', blocked
    assert _snap(db) == before
    assert q1(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (effect,)) == 'claimed'
    assert q1(db, 'SELECT attempt FROM v24_cordis.effects WHERE id=%s', (effect,)) == 1
    print('[CDP4-T7c] provider without concurrent replay right is blocked on reclaim (owner fixture)')


def main():
    with Server() as server:
        with TestDB(server) as db: test_t1_t2(db)
        with TestDB(server) as db: test_t2_concurrent(db)
        with TestDB(server) as db: test_t3_expired_lease(db)
        with TestDB(server) as db: test_t4_withdrawn(db)
        with TestDB(server) as db: test_t4_released(db)
        with TestDB(server) as db: test_t4_model_released(db)
        with TestDB(server) as db: test_t4_mismatch(db)
        with TestDB(server) as db: test_t5_unknown(db)
        with TestDB(server) as db: test_t6_failure(db)
        with TestDB(server) as db: test_t7_replay(db)
        with TestDB(server) as db: test_t7_reclaim(db)
        with TestDB(server) as db: test_t7_no_replay(db)
    print('[passed] CDP4-T')


if __name__ == '__main__':
    main()
