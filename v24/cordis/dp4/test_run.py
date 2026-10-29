"""CDP4-R: production run_start, claim, binding, refusal and replay rights."""
from __future__ import annotations
import contextlib
import json
import uuid

from psycopg2.extras import Json
from dp4_support import (Server, TestDB, snapshot, query, api, env, no_write,
                         reconcile_payload, install_payload, commit_new, child_call,
                         p0, one, rows, function_defs, replace_function, active_owner)
from dp4_support import (provider, agent, claim, settle, claim_success, run_start_effect,
                         run_row, count, event_payload, q1)


def _run_id(db, effect):
    return q1(db, 'SELECT v24_cordis.run_id_for(%s)', (effect,))


def _state(db, run_id):
    return run_row(db, run_id)[0]


def _write_snapshot(db):
    with contextlib.closing(db.connect('owner')) as conn:
        return snapshot(conn)


def _assert_zero_write(db, fn):
    before = _write_snapshot(db)
    result = fn()
    conn = db.connect('owner')
    try:
        assert snapshot(conn) == before, ('changed rows', result)
    finally:
        conn.close()
    return result


def _prepared_p4(db, policy='chat_tool', keys=('model', 'tool')):
    provider(db, 'model_call', keys[0])
    provider(db, 'tool_call', keys[1])
    root = active_owner(db)
    payload = install_payload(mode='existing', existing_scope=root['scope'],
                              owner=dict(fiber_id=str(root['fiber']), episode_id=str(root['episode'])))
    payload['manifest'] = dict(requires=list(keys), provides=[], priority=0, check={})
    payload['contracts'] = {'run_start': dict(
        contract_version='1', handler_digest='c' * 64,
        replay=dict(repeat=True, concurrent=True))}
    payload['policy_ref'] = policy
    _, result, _ = commit_new(db, 'command_install', payload)
    assert result['disposition'] == 'committed', result
    fiber = uuid.UUID(payload['fiber_id'])
    parent, started, _ = p0(db, fiber)
    assert started['emitted'], started
    p1_effect, p1_outcome = child_call(db, parent, reconcile_payload(fiber, 'advance', 1))
    with contextlib.closing(db.connect('service')) as conn:
        p1_result = api(conn, p1_effect, p1_outcome)
        conn.commit()
    assert p1_result['disposition'] == 'committed' and p1_result['emitted'], p1_result
    p4_effect = uuid.UUID(p1_result['emitted'][0])
    p4_effect2, p4_outcome = child_call(db, p1_effect,
                                        reconcile_payload(fiber, 'advance', 1))
    assert p4_effect2 == p4_effect
    episode = q1(db, 'SELECT episode_id FROM v24_cordis.effects WHERE id=%s', (p4_effect,))
    return fiber, p4_effect, p4_outcome, payload, episode


def test_r1_production(db):
    provider(db, 'model_call', 'model')
    provider(db, 'tool_call', 'tool')
    chat = agent(db)
    assert chat['p4_result']['emitted'], chat['p4_result']
    rs = run_start_effect(db, chat['p4_result'])
    assert rs is not None
    assert q1(db, 'SELECT kind FROM v24_cordis.effects WHERE id=%s', (rs,)) == 'run_start'
    assert q1(db, 'SELECT ordinal FROM v24_cordis.effects WHERE id=%s', (rs,)) == 0
    assert q1(db, 'SELECT count(*) FROM v24_cordis.runs') == 0
    plain = agent(db, policy=None)
    assert plain['p4_result']['emitted'] == [], plain['p4_result']
    assert q1(db, 'SELECT count(*) FROM v24_cordis.runs') == 0
    print('[CDP4-R1] chat_tool P4 emits exactly one ordinal-0 run_start; non-chat_tool emits none')


def test_r2_binding_and_replay(db):
    provider(db, 'model_call', 'model')
    provider(db, 'tool_call', 'tool')
    chat = agent(db)
    rs = run_start_effect(db, chat['p4_result'])
    c = claim(db, rs)
    assert set(c) == {'v', 'disposition', 'effect_id', 'emitted', 'revision', 'claim', 'input'}, c
    assert c['input']['fiber_id'] == str(chat['fiber']), c
    body = {'v': 1, 'request': {'messages': [{'role': 'user', 'content': 'hi'}]}, 'steps': 3}
    settled = settle(db, rs, body, c['claim'])
    assert settled['disposition'] == 'committed', settled
    assert settled.get('reason') is None, settled
    run_id = _run_id(db, rs)
    state, remaining, ended, result, owner, episode, scope = run_row(db, run_id)
    assert state == {'v': 1, 'origin': str(rs), 'step': 0, 'phase': 'model',
                     'batch': [], 'final': False}, state
    assert remaining == 3 and ended is None and result is None
    assert owner == chat['fiber']
    assert q1(db, 'SELECT count(*) FROM v24_cordis.runs') == 1
    assert q1(db, 'SELECT count(*) FROM v24_cordis.pins WHERE consumer_run_id=%s', (run_id,)) == 2
    keys = [x[0] for x in rows(db, 'SELECT key FROM v24_cordis.pins WHERE consumer_run_id=%s '
                                    'ORDER BY key', (run_id,))]
    assert keys == ['model', 'tool'], keys
    model_effect = uuid.UUID(settled['emitted'][0])
    assert q1(db, 'SELECT kind FROM v24_cordis.effects WHERE id=%s', (model_effect,)) == 'model_call'
    assert q1(db, 'SELECT run_id FROM v24_cordis.effects WHERE id=%s', (model_effect,)) == run_id
    model_input = q1(db, 'SELECT input FROM v24_cordis.effects WHERE id=%s', (model_effect,))
    assert set(model_input) == {'v', 'run_id', 'pin_id', 'key', 'digests', 'contract'}, model_input
    assert model_input['digests'] == q1(db, 'SELECT v24_cordis.run_digests(%s)', (run_id,))
    assert event_payload(db, rs)['step'] == 0
    assert q1(db, 'SELECT count(*) FROM v24_cordis.events WHERE effect_id=%s', (rs,)) == 1
    before = _write_snapshot(db)
    replay = settle(db, rs, body, c['claim'])
    assert replay['disposition'] == 'replay' and replay['emitted'] == [], replay
    assert _write_snapshot(db) == before
    with contextlib.closing(db.connect('service')) as conn:
        no_write(db, conn, rs, env('success', {'v': 1, 'request': {}, 'steps': 3}, c['claim']),
                 'receipt_conflict')
    print('[CDP4-R2/R3] claim carries input; run/pins/model successor are exact; replay is zero-write')


def _successor_for(db, fiber, episode):
    contract = q1(db, "SELECT i.contracts->'run_start' FROM v24_cordis.installs i "
                      "JOIN v24_cordis.fibers f ON f.install_id=i.id WHERE f.id=%s", (fiber,))
    return {'ordinal': 0, 'kind': 'run_start', 'input': {
        'v': 1, 'fiber_id': str(fiber), 'episode_id': str(episode),
        'contract': {'contract_version': contract['contract_version'],
                     'handler_digest': contract['handler_digest']}}}


def _command_interpreter(db):
    return q1(db, "SELECT pg_get_functiondef('v24_cordis.interpret_command(uuid,uuid,jsonb,jsonb)'::regprocedure)")


def test_r4_forged_p4(db):
    fiber, effect, outcome, _, episode = _prepared_p4(db)
    with contextlib.closing(db.connect('owner')) as conn:
        principal = query(conn, 'SELECT v24_cordis.principal_id(session_user)')[0][0]
        real = query(conn, 'SELECT v24_cordis.interpret_command(%s,%s,%s,%s)',
                     (effect, principal, Json(outcome), Json([])))[0][0]['context']
        assert len(real['successors']) == 1, real
        succ = real['successors'][0]
        original = _command_interpreter(db)
    cases = []
    cases.append(('two', {**real, 'successors': [succ, {**succ, 'ordinal': 1}]}))
    cases.append(('ordinal', {**real, 'successors': [{**succ, 'ordinal': 1}]}))
    bad_input = {**succ, 'input': {**succ['input'], 'extra': True}}
    cases.append(('input', {**real, 'successors': [bad_input]}))
    # Legal successor shape, but the target is non-chat_tool (real producer returns []).
    other_fiber, other_effect, other_outcome, _, other_episode = _prepared_p4(db, policy=None, keys=('bmodel', 'btool'))
    with contextlib.closing(db.connect('owner')) as conn:
        other_real = query(conn, 'SELECT v24_cordis.interpret_command(%s,%s,%s,%s)',
                           (other_effect, principal, Json(other_outcome), Json([])))[0][0]['context']
    assert other_real['successors'] == [], other_real
    cases.append(('non_chat_tool', {**other_real,
                 'successors': [_successor_for(db, other_fiber, other_episode)]}))
    # Legal successor shape, but the target already has an open run (real producer returns []).
    run_fiber, run_effect, run_outcome, _, run_episode = _prepared_p4(db, keys=('cmodel', 'ctool'))
    scope = q1(db, 'SELECT scope_id FROM v24_cordis.fibers WHERE id=%s', (run_fiber,))
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, "INSERT INTO v24_cordis.runs(id,owner_fiber_id,owner_episode_id,scope_id,state,"
                    "remaining_steps) VALUES(%s,%s,%s,%s,%s,1)",
              (uuid.uuid4(), run_fiber, run_episode, scope,
               Json({'v': 1, 'origin': str(run_effect), 'step': 0, 'phase': 'model',
                     'batch': [], 'final': False})))
        conn.commit()
        run_real = query(conn, 'SELECT v24_cordis.interpret_command(%s,%s,%s,%s)',
                         (run_effect, principal, Json(run_outcome), Json([])))[0][0]['context']
    assert run_real['successors'] == [], run_real
    cases.append(('existing_run', {**run_real,
                     'successors': [_successor_for(db, run_fiber, run_episode)]}))

    replace_function(db, """CREATE OR REPLACE FUNCTION v24_cordis.interpret_command(
      p_effect_id uuid,p_principal uuid,p_outcome jsonb,p_closure jsonb) RETURNS jsonb
      LANGUAGE sql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp
      BEGIN ATOMIC SELECT current_setting('dp4.forged_command')::jsonb; END""")
    try:
        fixtures = {'two': effect, 'ordinal': effect, 'input': effect,
                    'non_chat_tool': other_effect, 'existing_run': run_effect}
        outcomes = {'two': outcome, 'ordinal': outcome, 'input': outcome,
                    'non_chat_tool': other_outcome, 'existing_run': run_outcome}
        for label, delta in cases:
            with contextlib.closing(db.connect('service')) as conn:
                query(conn, "SELECT set_config('dp4.forged_command',%s,false)", (json.dumps(delta),))
                no_write(db, conn, fixtures[label], outcomes[label], 'invalid_outcome')
    finally:
        replace_function(db, original)
    print('[CDP4-R4] advance rejects two/ordinal-1/bad-input/non-chat_tool/existing-run p4 '
          'successors as invalid_outcome with zero write')


def test_r5_owner_closing(db):
    provider(db, 'model_call', 'model')
    provider(db, 'tool_call', 'tool')
    chat = agent(db)
    rs = run_start_effect(db, chat['p4_result'])
    c = claim(db, rs)
    off, result, _ = commit_new(db, 'command_reconcile',
                                reconcile_payload(chat['fiber'], 'off', 1))
    assert result['disposition'] == 'committed', result
    settled = settle(db, rs, {'v': 1, 'request': {}, 'steps': 2}, c['claim'])
    assert settled['reason'] == 'owner_closing', settled
    assert settled['disposition'] == 'committed' and settled['emitted'] == [], settled
    assert q1(db, 'SELECT count(*) FROM v24_cordis.runs') == 0
    assert q1(db, 'SELECT count(*) FROM v24_cordis.pins WHERE consumer_run_id IS NOT NULL') == 0
    assert q1(db, "SELECT count(*) FROM v24_cordis.events WHERE effect_id=%s "
                  "AND event_kind='run_refused'", (rs,)) == 1

    chat2 = agent(db)
    rs2 = run_start_effect(db, chat2['p4_result'])
    c2 = claim(db, rs2)
    original = function_defs(db)
    replace_function(db, '''CREATE OR REPLACE FUNCTION v24_cordis.fiber_live_resolve_ok(
 p_fiber uuid,p_episode uuid) RETURNS boolean LANGUAGE plpgsql
 SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
BEGIN RAISE EXCEPTION 'P0401 probe' USING ERRCODE='P0401'; END $$;''')
    try:
        probe = settle(db, rs2, {'v': 1, 'request': {}, 'steps': 2}, c2['claim'])
        assert probe['error']['code'] == 'retry_with_closure', probe
        assert q1(db, 'SELECT count(*) FROM v24_cordis.runs') == 0
        assert q1(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (rs2,)) == 'claimed'
    finally:
        replace_function(db, original['fiber_live_resolve_ok'])
    print('[CDP4-R5] owner-closing settles without run; P0401 maps to retry_with_closure')


def test_r6_provider_contract(db):
    provider(db, 'model_call', 'model')
    tool = provider(db, 'tool_call', 'tool')
    chat = agent(db)
    rs = run_start_effect(db, chat['p4_result'])
    settled = settle(db, rs, {'v': 1, 'request': {}, 'steps': 3},
                     claim(db, rs)['claim'])
    assert settled['disposition'] == 'committed', settled
    model_effect = uuid.UUID(settled['emitted'][0])
    mc = claim(db, model_effect)
    assert mc['disposition'] == 'claimed', mc
    run_id = _run_id(db, rs)
    model_pin = q1(db, "SELECT id FROM v24_cordis.pins WHERE consumer_run_id=%s AND key='model'",
                   (run_id,))
    run = rows(db, 'SELECT owner_fiber_id,owner_episode_id FROM v24_cordis.runs WHERE id=%s',
               (run_id,))[0]
    forged = uuid.uuid4()
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, "INSERT INTO v24_cordis.effects(id,kind,status,fiber_id,episode_id,run_id,"
                    "input,request_actor) VALUES(%s,'tool_call','ready',%s,%s,%s,%s,%s)",
              (forged, run[0], run[1], run_id,
               Json({
                   'v': 1, 'run_id': str(run_id), 'pin_id': str(model_pin),
                   'key': 'tool', 'descriptor_digest': tool['payload']['artifact_digest'],
                   'call_id': 'x', 'args': {},
                   'contract': {'contract_version': '1', 'handler_digest': 'b' * 64}}),
               db.roles['service']))
        conn.commit()
    before = _write_snapshot(db)
    with contextlib.closing(db.connect('service')) as conn:
        bad = api(conn, forged, env('claim', {'lease_ms': 1000}))
        conn.commit()
    assert bad['error']['code'] == 'invalid_outcome', bad
    assert _write_snapshot(db) == before
    print('[CDP4-R6] provider contract is the claim subject; capability mismatch is zero-write')


def test_r7_replay_rights(db, replay):
    provider(db, 'model_call', 'model', replay=replay)
    provider(db, 'tool_call', 'tool', replay=(True, True))
    chat = agent(db)
    rs = run_start_effect(db, chat['p4_result'])
    c = claim(db, rs)
    body = {'v': 1, 'request': {}, 'steps': 2}
    refused = settle(db, rs, body, c['claim'])
    assert refused['reason'] == 'replay_right_missing', (replay, refused)
    assert refused['disposition'] == 'committed' and refused['emitted'] == [], refused
    assert q1(db, 'SELECT count(*) FROM v24_cordis.runs') == 0
    assert q1(db, 'SELECT count(*) FROM v24_cordis.pins WHERE consumer_run_id IS NOT NULL') == 0
    assert q1(db, "SELECT count(*) FROM v24_cordis.events WHERE effect_id=%s "
                  "AND event_kind='run_refused'", (rs,)) == 1
    replay_result = settle(db, rs, body, c['claim'])
    assert replay_result['disposition'] == 'replay', replay_result
    print(f'[CDP4-R7] replay={replay} refuses at run_start with one event')


def main():
    with Server() as server:
        with TestDB(server) as db:
            test_r1_production(db)
        with TestDB(server) as db:
            test_r2_binding_and_replay(db)
        with TestDB(server) as db:
            test_r4_forged_p4(db)
        with TestDB(server) as db:
            test_r5_owner_closing(db)
        with TestDB(server) as db:
            test_r6_provider_contract(db)
        with TestDB(server) as db:
            test_r7_replay_rights(db, (False, True))
        with TestDB(server) as db:
            test_r7_replay_rights(db, (True, False))
    print('[passed] CDP4-R')


if __name__ == '__main__':
    main()
