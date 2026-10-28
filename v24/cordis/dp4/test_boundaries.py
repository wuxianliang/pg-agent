"""CDP4-X: seal, terminal states, budget edges and the e7-e13 lifecycle walk."""
from __future__ import annotations
import contextlib
import json
import uuid

import psycopg2
from psycopg2.extras import Json
from dp4_support import (Server, TestDB, snapshot, query, api, env, claim, settle,
                         prepare_run, model_body, tool_call, tool_body, q1, rows,
                         replace_function, provider, agent)
from test_support import reconcile_payload, no_write
from test_activation import commit_new, child_call


def _snap(db):
    with contextlib.closing(db.connect('owner')) as conn:
        return snapshot(conn)


def _run(db, run_id):
    return rows(db, 'SELECT state,remaining_steps,ended_at,result FROM v24_cordis.runs '
                    'WHERE id=%s', (run_id,))[0]


def _pins(db, run_id):
    return rows(db, 'SELECT id,key,contribution_id,provider_epoch,released_at '
                    'FROM v24_cordis.pins WHERE consumer_run_id=%s ORDER BY key', (run_id,))


def _event(db, effect):
    return q1(db, "SELECT payload FROM v24_cordis.events WHERE effect_id=%s "
                  "AND event_kind='run_progress'", (effect,))


def _applied(db, effect, outcome):
    with contextlib.closing(db.connect('service')) as conn:
        result = api(conn, effect, outcome)
        conn.commit()
    return result


def _insert_ready_model(db, x, pin, digests, contract):
    run = rows(db, 'SELECT owner_fiber_id,owner_episode_id FROM v24_cordis.runs WHERE id=%s',
               (x['run_id'],))[0]
    effect = uuid.uuid4()
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, "INSERT INTO v24_cordis.effects(id,kind,status,fiber_id,episode_id,run_id,"
                    "input,request_actor) VALUES(%s,'model_call','ready',%s,%s,%s,%s,%s)",
              (effect, run[0], run[1], x['run_id'],
               Json({'v': 1, 'run_id': str(x['run_id']), 'pin_id': str(pin), 'key': 'model',
                     'digests': digests,
                     'contract': {'contract_version': contract['contract_version'],
                                  'handler_digest': contract['handler_digest']}}),
               db.roles['service']))
        conn.commit()
    return effect


def test_x1_final(db):
    x = prepare_run(db, 1)
    model_pin = q1(db, "SELECT id FROM v24_cordis.pins WHERE consumer_run_id=%s AND key='model'",
                   (x['run_id'],))
    digests = q1(db, 'SELECT v24_cordis.run_digests(%s)', (x['run_id'],))
    contract = q1(db, "SELECT i.contracts->'model_call' FROM v24_cordis.pins p "
                      "JOIN v24_cordis.contributions c ON c.id=p.contribution_id "
                      "JOIN v24_cordis.fibers f ON f.id=c.fiber_id "
                      "JOIN v24_cordis.installs i ON i.id=f.install_id "
                      "WHERE p.id=%s", (model_pin,))
    c = claim(db, x['model_effect'])
    body = model_body(final=True, text='done', usage={'input': 1, 'output': 2})
    result = settle(db, x['model_effect'], body, c['claim'])
    assert result['disposition'] == 'committed' and result['emitted'] == [], result
    state, budget, ended, outcome = _run(db, x['run_id'])
    assert budget == 0 and ended is not None, (budget, ended)
    assert outcome == {'v': 1, 'reason': 'final', 'output': body['result'],
                       'dropped_tool_calls': 0}, outcome
    assert state['phase'] == 'sealed' and state['final'] is True and state['batch'] == [], state
    pins = _pins(db, x['run_id'])
    assert len(pins) == 2 and all(p[4] is not None for p in pins), pins
    event = _event(db, x['model_effect'])
    assert event['sealed'] is True and event['reason'] == 'final', event
    assert event['step'] == 1 and event['remaining_steps'] == 0 and event['phase'] == 'sealed', event
    before = _snap(db)
    replay = settle(db, x['model_effect'], body, c['claim'])
    assert replay['disposition'] == 'replay' and replay['emitted'] == [], replay
    assert _snap(db) == before
    conflict = settle(db, x['model_effect'], model_body(final=True, text='other'), c['claim'])
    assert conflict['error']['code'] == 'receipt_conflict', conflict
    assert _snap(db) == before
    extra = _insert_ready_model(db, x, model_pin, digests, contract)
    ec = claim(db, extra)
    assert ec.get('disposition') == 'claimed', ec
    before = _snap(db)
    terminal = settle(db, extra, model_body(final=True), ec['claim'])
    assert terminal['error']['code'] == 'already_terminal', terminal
    assert _snap(db) == before
    assert q1(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (extra,)) == 'claimed'
    reclaim = claim(db, x['model_effect'])
    assert reclaim['error']['code'] == 'receipt_conflict', reclaim
    try:
        with contextlib.closing(db.connect('owner')) as conn:
            query(conn, "UPDATE v24_cordis.effects SET status='ready',settled_at=NULL "
                        'WHERE id=%s', (x['model_effect'],))
    except psycopg2.Error as exc:
        assert exc.pgcode == '55000', exc.pgcode
    else:
        raise AssertionError('terminal effect was reopenable by DML')
    print('[CDP4-X1] final seals+releases; replay/conflict; already_terminal; DML reopen 55000')


def test_x1b_custom_model_key(db):
    x = prepare_run(db, 3, ('tool',), model_key='brain')
    pins = _pins(db, x['run_id'])
    assert [(p[1], p[4]) for p in pins] == [('brain', None), ('tool', None)], pins
    brain_pin, tool_pin = pins[0][0], pins[1][0]
    mc = claim(db, x['model_effect'])
    assert mc['input']['key'] == 'brain', mc
    mr = settle(db, x['model_effect'], model_body([tool_call('c1')]), mc['claim'])
    assert mr['disposition'] == 'committed' and len(mr['emitted']) == 1, mr
    tool = rows(db, "SELECT id FROM v24_cordis.effects WHERE run_id=%s AND kind='tool_call'",
                (x['run_id'],))[0][0]
    tc = claim(db, tool)
    tool_out = env('success', tool_body(), tc['claim'])
    delta = q1(db, 'SELECT v24_cordis.run_delta(%s,%s)', (tool, Json(tool_out)))
    successor = delta['successors'][0]['input']
    assert successor['key'] == 'brain' and successor['pin_id'] == str(brain_pin), delta
    original = q1(db, "SELECT pg_get_functiondef('v24_cordis.run_delta(uuid,jsonb)'::regprocedure)")
    replace_function(db, """CREATE OR REPLACE FUNCTION v24_cordis.run_delta(p_effect_id uuid,p_outcome jsonb)
      RETURNS jsonb LANGUAGE sql STABLE AS $$ SELECT current_setting('dp4.forged')::jsonb $$""")
    try:
        for label, pin, key in (('key', brain_pin, 'tool'), ('capability', tool_pin, 'tool')):
            forged = json.loads(json.dumps(delta))
            forged['successors'][0]['input']['pin_id'] = str(pin)
            forged['successors'][0]['input']['key'] = key
            with contextlib.closing(db.connect('service')) as conn:
                query(conn, "SELECT set_config('dp4.forged',%s,false)", (json.dumps(forged),))
                no_write(db, conn, tool, tool_out, 'invalid_outcome')
        for label, mutate in (
                ('ordinal', lambda f: f['successors'][0].__setitem__('ordinal', 1)),
                ('contract_version', lambda f: f['successors'][0]['input']['contract'].__setitem__(
                    'contract_version', '2')),
                ('contract_digest', lambda f: f['successors'][0]['input']['contract'].__setitem__(
                    'handler_digest', 'd' * 64)),
                ('digests', lambda f: f['successors'][0]['input']['digests'].__setitem__(
                    'toolset', '0' * 64))):
            forged = json.loads(json.dumps(delta))
            mutate(forged)
            with contextlib.closing(db.connect('service')) as conn:
                query(conn, "SELECT set_config('dp4.forged',%s,false)", (json.dumps(forged),))
                no_write(db, conn, tool, tool_out, 'invalid_outcome',
                         detail={'reason': 'run_state_delta'})
    finally:
        replace_function(db, original)
    tr = settle(db, tool, tool_body(), tc['claim'])
    assert tr['disposition'] == 'committed' and len(tr['emitted']) == 1, tr
    cont = _continuation(db, x['run_id'])
    assert len(cont) == 1 and cont[0][3]['key'] == 'brain', cont
    assert cont[0][3]['pin_id'] == str(brain_pin), cont
    cc = claim(db, cont[0][0])
    final = model_body(final=True, text='brain-done')
    sealed = settle(db, cont[0][0], final, cc['claim'])
    assert sealed['disposition'] == 'committed' and sealed['emitted'] == [], sealed
    state, budget, ended, outcome = _run(db, x['run_id'])
    assert budget == 0 and ended is not None and state['phase'] == 'sealed', (budget, state)
    assert outcome['reason'] == 'final' and outcome['output'] == final['result'], outcome
    assert all(p[4] is not None for p in _pins(db, x['run_id']))
    print('[CDP4-X1b] brain key survives run_start->model->tool->continuation->final; advance rejects key/capability spoof')


def test_x2_model_over(db):
    x = prepare_run(db, 3, ('tool', 'tool2', 'tool3'))
    c = claim(db, x['model_effect'])
    calls = [tool_call(f'c{i}', ('tool', 'tool2', 'tool3')[i]) for i in range(3)]
    result = settle(db, x['model_effect'], model_body(calls), c['claim'])
    assert result['disposition'] == 'committed' and result['emitted'] == [], result
    state, budget, ended, outcome = _run(db, x['run_id'])
    assert budget == 2 and ended is not None and state['phase'] == 'sealed', (budget, state)
    assert outcome['reason'] == 'budget_exhausted' and outcome['dropped_tool_calls'] == 3, outcome
    assert q1(db, "SELECT count(*) FROM v24_cordis.effects WHERE run_id=%s "
                  "AND kind='tool_call'", (x['run_id'],)) == 0
    print('[CDP4-X2a] model N>budget seals budget_exhausted, dropped=3, no partial tool batch')


def test_x2_tool_zero(db):
    y = prepare_run(db, 2)
    mc = claim(db, y['model_effect'])
    mr = settle(db, y['model_effect'], model_body([tool_call('c1')]), mc['claim'])
    assert mr['disposition'] == 'committed', mr
    tool = rows(db, "SELECT id FROM v24_cordis.effects WHERE run_id=%s AND kind='tool_call'",
                (y['run_id'],))[0][0]
    tc = claim(db, tool)
    tr = settle(db, tool, tool_body(), tc['claim'])
    assert tr['disposition'] == 'committed' and tr['emitted'] == [], tr
    state, budget, ended, outcome = _run(db, y['run_id'])
    assert budget == 0 and ended is not None and state['phase'] == 'sealed', (budget, state)
    assert outcome['reason'] == 'budget_exhausted' and outcome['dropped_tool_calls'] == 0, outcome
    print('[CDP4-X2b] tool settlement 1->0 seals budget_exhausted with dropped=0')


def test_x5_negative_budget(db):
    x = prepare_run(db, 3)
    c = claim(db, x['model_effect'])
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, 'UPDATE v24_cordis.runs SET remaining_steps=0 WHERE id=%s', (x['run_id'],))
        conn.commit()
    before = _snap(db)
    result = settle(db, x['model_effect'], model_body([tool_call('c1')]), c['claim'])
    assert result['error']['code'] == 'budget_exceeded', result
    assert _snap(db) == before
    assert q1(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s',
              (x['model_effect'],)) == 'claimed'
    print('[CDP4-X5] negative deduction guard is budget_exceeded with zero write')


def test_m6_model_failed(db):
    x = prepare_run(db, 3)
    c = claim(db, x['model_effect'])
    body = {'kind': 'model_call', 'error': {'code': 'provider_down', 'detail': {'why': 'io'}}}
    result = settle(db, x['model_effect'], body, c['claim'], 'failure')
    assert result['disposition'] == 'committed' and result['emitted'] == [], result
    state, budget, ended, outcome = _run(db, x['run_id'])
    assert budget == 2 and ended is not None and state['phase'] == 'sealed', (budget, state)
    assert state['final'] is False
    assert outcome == {'v': 1, 'reason': 'model_failed', 'output': body['error'],
                       'dropped_tool_calls': 0}, outcome
    assert q1(db, "SELECT count(*) FROM v24_cordis.effects WHERE run_id=%s "
                  "AND kind IN ('model_call','tool_call')", (x['run_id'],)) == 1
    assert all(p[4] is not None for p in _pins(db, x['run_id']))
    event = _event(db, x['model_effect'])
    assert event['sealed'] is True and event['reason'] == 'model_failed', event
    print('[CDP4-M6] model failure seals model_failed, releases pins and emits no successor')


def test_validator(db):
    x = prepare_run(db, 3)
    c = claim(db, x['model_effect'])
    final_out = env('success', model_body(final=True, text='done'), c['claim'])
    tool_out = env('success', model_body([tool_call('c1')]), c['claim'])
    final_delta = q1(db, 'SELECT v24_cordis.run_delta(%s,%s)', (x['model_effect'], Json(final_out)))
    tool_delta = q1(db, 'SELECT v24_cordis.run_delta(%s,%s)', (x['model_effect'], Json(tool_out)))
    assert 'error' not in final_delta and 'error' not in tool_delta, (final_delta, tool_delta)
    original = q1(db, "SELECT pg_get_functiondef('v24_cordis.run_delta(uuid,jsonb)'::regprocedure)")
    replace_function(db, """CREATE OR REPLACE FUNCTION v24_cordis.run_delta(p_effect_id uuid,p_outcome jsonb)
      RETURNS jsonb LANGUAGE sql STABLE AS $$ SELECT current_setting('dp4.forged')::jsonb $$""")
    try:
        cases = []
        bad = json.loads(json.dumps(final_delta))
        bad['domain'][1]['remaining_steps'] = 63
        cases.append(('budget', bad, final_out))
        bad = json.loads(json.dumps(final_delta))
        bad['domain'][2]['effect_id'] = str(uuid.uuid4())
        cases.append(('seal', bad, final_out))
        bad = json.loads(json.dumps(final_delta))
        bad['domain'][3]['pin_ids'].pop()
        cases.append(('pins', bad, final_out))
        bad = json.loads(json.dumps(tool_delta))
        bad['successors'][0]['input']['pin_id'] = str(uuid.uuid4())
        cases.append(('successor', bad, tool_out))
        bad = json.loads(json.dumps(final_delta))
        bad['events'] = []
        cases.append(('event_missing', bad, final_out))
        for field, value in (('run_id', str(uuid.uuid4())), ('effect_id', str(uuid.uuid4())),
                             ('effect_kind', 'tool_call'), ('step', 0),
                             ('remaining_steps', 63), ('phase', 'tools'),
                             ('sealed', False), ('reason', 'budget_exhausted')):
            bad = json.loads(json.dumps(final_delta))
            bad['events'][0]['payload'][field] = value
            cases.append(('event_' + field, bad, final_out))
        bad = json.loads(json.dumps(tool_delta))
        bad['domain'][0]['state']['origin'] = str(uuid.uuid4())
        cases.append(('state_origin', bad, tool_out))
        bad = json.loads(json.dumps(tool_delta))
        bad['domain'][0]['state']['step'] = 2
        cases.append(('state_step', bad, tool_out))
        bad = json.loads(json.dumps(tool_delta))
        bad['domain'][0]['state']['batch'][0]['call_id'] = 'forged'
        cases.append(('state_batch', bad, tool_out))
        bad = json.loads(json.dumps(final_delta))
        bad['domain'][0]['state']['final'] = False
        cases.append(('state_final', bad, final_out))
        bad = json.loads(json.dumps(tool_delta))
        bad['events'][0]['payload']['sealed'] = True
        cases.append(('event_sealed_tools', bad, tool_out))
        bad = json.loads(json.dumps(tool_delta))
        bad['events'] = []
        cases.append(('event_missing_tools', bad, tool_out))
        bad = json.loads(json.dumps(tool_delta))
        bad['successors'].append(dict(bad['successors'][0], ordinal=1))
        cases.append(('successor_extra', bad, tool_out))
        bad = json.loads(json.dumps(final_delta))
        bad['domain'][2]['result']['output'] = {'forged': True}
        cases.append(('seal_output', bad, final_out))
        bad = json.loads(json.dumps(final_delta))
        bad['domain'][2]['result']['reason'] = 'budget_exhausted'
        cases.append(('seal_reason', bad, final_out))
        bad = json.loads(json.dumps(final_delta))
        bad['domain'][2]['result']['dropped_tool_calls'] = 1
        cases.append(('seal_dropped', bad, final_out))
        bad = json.loads(json.dumps(final_delta))
        bad['receipt']['status'] = 'failed'
        cases.append(('receipt_status', bad, final_out))
        for label, path, value in (
                ('contract_version', ('contract', 'contract_version'), '2'),
                ('contract_digest', ('contract', 'handler_digest'), 'd' * 64),
                ('descriptor', ('descriptor_digest',), '0' * 64),
                ('args', ('args',), {'forged': True}),
                ('call_id', ('call_id',), 'c-forged'),
                ('key', ('key',), 'tool2'),
                ('ordinal', ('ordinal',), 1)):
            bad = json.loads(json.dumps(tool_delta))
            if label == 'ordinal':
                bad['successors'][0]['ordinal'] = value
            else:
                node = bad['successors'][0]['input']
                for key in path[:-1]:
                    node = node[key]
                node[path[-1]] = value
            cases.append(('successor_' + label, bad, tool_out))
        proof = {'event_missing', 'event_run_id', 'event_effect_id', 'event_effect_kind',
                 'event_step', 'event_remaining', 'event_phase', 'event_sealed', 'event_reason',
                 'state_origin', 'state_step', 'state_batch', 'state_final',
                 'event_sealed_tools', 'event_missing_tools', 'seal_output', 'seal_reason',
                 'seal_dropped', 'successor_contract_version',
                 'successor_contract_digest', 'successor_descriptor', 'successor_args',
                 'successor_call_id', 'successor_key', 'successor_ordinal', 'successor_extra'}
        for label, forged, outcome in cases:
            with contextlib.closing(db.connect('service')) as conn:
                query(conn, "SELECT set_config('dp4.forged',%s,false)", (json.dumps(forged),))
                detail = {'reason': 'run_state_delta'} if label in proof else None
                try:
                    no_write(db, conn, x['model_effect'], outcome, 'invalid_outcome',
                             detail=detail)
                except AssertionError as exc:
                    raise AssertionError(f'{label}: {exc}') from exc
    finally:
        replace_function(db, original)
    print('[CDP4-X6] advance rejects forged budget/seal/pins/successor planners independently with zero write')


def test_run_start_forged(db):
    provider(db, 'model_call', 'model')
    provider(db, 'tool_call', 'tool')
    chat = agent(db)
    rs = uuid.UUID(chat['p4_result']['emitted'][0])
    tc = claim(db, rs)
    out = env('success', {'v': 1, 'request': {}, 'steps': 2}, tc['claim'])
    delta = q1(db, 'SELECT v24_cordis.run_delta(%s,%s)', (rs, Json(out)))
    assert 'error' not in delta, delta
    tool_pin = next(p['id'] for p in delta['domain'][1]['pins'] if p['key'] == 'tool')
    cases = []

    def case(label, mutate):
        forged = json.loads(json.dumps(delta))
        mutate(forged)
        cases.append((label, forged))

    case('state_phase', lambda d: d['domain'][0]['state'].__setitem__('phase', 'tools'))
    case('state_step', lambda d: d['domain'][0]['state'].__setitem__('step', 1))
    case('state_origin', lambda d: d['domain'][0]['state'].__setitem__('origin', str(uuid.uuid4())))
    case('budget', lambda d: d['domain'][0].__setitem__('remaining_steps', 3))
    case('pins_missing', lambda d: d['domain'][1]['pins'].pop())
    case('pins_contribution', lambda d: d['domain'][1]['pins'][1].__setitem__(
        'contribution_id', str(uuid.uuid4())))
    case('pins_epoch', lambda d: d['domain'][1]['pins'][0].__setitem__('provider_epoch', 99))
    case('pins_extra', lambda d: d['domain'][1]['pins'].append(dict(
        d['domain'][1]['pins'][0], key='zzz', id=str(uuid.uuid4()))))
    case('successor_ordinal', lambda d: d['successors'][0].__setitem__('ordinal', 1))
    case('successor_kind', lambda d: d['successors'][0].__setitem__('kind', 'tool_call'))
    case('successor_run', lambda d: d['successors'][0]['input'].__setitem__(
        'run_id', str(uuid.uuid4())))
    case('successor_pin', lambda d: d['successors'][0]['input'].__setitem__('pin_id', tool_pin))
    case('successor_key', lambda d: d['successors'][0]['input'].__setitem__('key', 'tool'))
    case('successor_digests', lambda d: d['successors'][0]['input']['digests'].__setitem__(
        'toolset', '0' * 64))
    case('successor_contract', lambda d: d['successors'][0]['input']['contract'].__setitem__(
        'handler_digest', 'd' * 64))
    case('successor_extra', lambda d: d['successors'].append(dict(
        d['successors'][0], ordinal=1)))
    case('event_missing', lambda d: d.__setitem__('events', []))
    case('event_run_id', lambda d: d['events'][0]['payload'].__setitem__(
        'run_id', str(uuid.uuid4())))
    case('event_effect_id', lambda d: d['events'][0]['payload'].__setitem__(
        'effect_id', str(uuid.uuid4())))
    case('event_effect_kind', lambda d: d['events'][0]['payload'].__setitem__(
        'effect_kind', 'tool_call'))
    case('event_step', lambda d: d['events'][0]['payload'].__setitem__('step', 1))
    case('event_remaining', lambda d: d['events'][0]['payload'].__setitem__(
        'remaining_steps', 3))
    case('event_phase', lambda d: d['events'][0]['payload'].__setitem__('phase', 'tools'))
    case('event_sealed', lambda d: d['events'][0]['payload'].__setitem__('sealed', True))
    case('event_reason', lambda d: d['events'][0]['payload'].__setitem__('reason', 'final'))
    case('receipt', lambda d: d['receipt'].__setitem__('status', 'failed'))
    for label in ('owner_closing', 'start_failed', 'replay_right_missing'):
        cases.append(('empty_' + label, {
            'domain': [], 'receipt': {'status': 'succeeded'},
            'events': [{'entity_type': 'run', 'entity_id': str(rs),
                        'event_kind': 'run_refused',
                        'payload': {'run_id': None, 'effect_id': str(rs), 'reason': label}}],
            'successors': []}))

    original = q1(db, "SELECT pg_get_functiondef('v24_cordis.run_delta(uuid,jsonb)'::regprocedure)")
    replace_function(db, """CREATE OR REPLACE FUNCTION v24_cordis.run_delta(p_effect_id uuid,p_outcome jsonb)
      RETURNS jsonb LANGUAGE sql STABLE AS $$ SELECT current_setting('dp4.forged')::jsonb $$""")
    try:
        proof = {'event_missing', 'event_run_id', 'event_effect_id', 'event_effect_kind',
                 'event_step', 'event_remaining', 'event_phase', 'event_sealed', 'event_reason'}
        for label, forged in cases:
            with contextlib.closing(db.connect('service')) as conn:
                query(conn, "SELECT set_config('dp4.forged',%s,false)", (json.dumps(forged),))
                detail = {'reason': 'run_start_delta'} if label in proof else None
                try:
                    no_write(db, conn, rs, out, 'invalid_outcome', detail=detail)
                except AssertionError as exc:
                    raise AssertionError(f'{label}: {exc}') from exc
        assert q1(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (rs,)) == 'claimed'
        assert q1(db, 'SELECT count(*) FROM v24_cordis.runs') == 0
        # A genuine off command closes the owner while run_start remains claimed.
        # The stale planner result must not force run creation after that transition.
        _enter_closing(db, chat['fiber'])
        with contextlib.closing(db.connect('service')) as conn:
            query(conn, "SELECT set_config('dp4.forged',%s,false)", (json.dumps(delta),))
            no_write(db, conn, rs, out, 'invalid_outcome')
        assert q1(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (rs,)) == 'claimed'
        assert q1(db, 'SELECT count(*) FROM v24_cordis.runs') == 0
        # A real failure refusal is still accepted: the validator recomputes start_failed,
        # so empty domain is not rejected wholesale.
        fail = env('failure', {'v': 1, 'error': {'code': 'boom'}}, tc['claim'])
        refusal = {'domain': [], 'receipt': {'status': 'failed'},
                   'events': [{'entity_type': 'run', 'entity_id': str(rs),
                               'event_kind': 'run_refused',
                               'payload': {'run_id': None, 'effect_id': str(rs),
                                           'reason': 'start_failed'}}],
                   'successors': []}
        with contextlib.closing(db.connect('service')) as conn:
            query(conn, "SELECT set_config('dp4.forged',%s,false)", (json.dumps(refusal),))
            done = api(conn, rs, fail)
            conn.commit()
        assert done['disposition'] == 'committed' and done['emitted'] == [], done
        assert done.get('reason') == 'start_failed', done
        assert q1(db, 'SELECT count(*) FROM v24_cordis.runs') == 0
        assert q1(db, 'SELECT count(*) FROM v24_cordis.pins WHERE consumer_run_id IS NOT NULL') == 0
        assert q1(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (rs,)) == 'failed'
        assert q1(db, "SELECT count(*) FROM v24_cordis.events WHERE effect_id=%s "
                      "AND event_kind='run_refused'", (rs,)) == 1
    finally:
        replace_function(db, original)
    print('[CDP4-X7] advance rejects forged run_start state/budget/pins/successor and empty-domain '
          'refusals plus forced creation after off/closing as invalid_outcome with zero write; '
          'a real failure refusal still commits')




def _enter_closing(db, fiber):
    control = q1(db, 'SELECT control_seq FROM v24_cordis.fibers WHERE id=%s', (fiber,))
    off, result, _ = commit_new(db, 'command_reconcile', reconcile_payload(fiber, 'off', control))
    assert result['disposition'] == 'committed' and result['emitted'], result
    slot, outcome = child_call(db, off, reconcile_payload(fiber, 'advance', control + 1))
    done = _applied(db, slot, outcome)
    assert done['disposition'] == 'committed', done
    assert rows(db, 'SELECT state,outcome FROM v24_cordis.episodes WHERE id=(SELECT '
                    'current_episode_id FROM v24_cordis.fibers WHERE id=%s)',
                (fiber,)) == [('closing', 'retire')]
    return control + 1


def _p6_slot(db, fiber, control):
    off, result, _ = commit_new(db, 'command_reconcile', reconcile_payload(fiber, 'off', control))
    assert result['disposition'] == 'committed' and len(result['emitted']) == 1, result
    new_control = q1(db, 'SELECT control_seq FROM v24_cordis.fibers WHERE id=%s', (fiber,))
    effect, outcome = child_call(db, off, reconcile_payload(fiber, 'advance', new_control))
    assert effect == uuid.UUID(result['emitted'][0]), (effect, result)
    return effect, outcome, new_control


def _continuation(db, run_id):
    return rows(db, "SELECT id,parent_id,ordinal,input FROM v24_cordis.effects "
                    "WHERE run_id=%s AND kind='model_call' AND status='ready'", (run_id,))


def test_x3_lifecycle(db):
    x = prepare_run(db, 3, ('tool',))
    owner, episode = rows(db, 'SELECT owner_fiber_id,owner_episode_id FROM v24_cordis.runs '
                              'WHERE id=%s', (x['run_id'],))[0]
    model_pin, model_epoch = rows(db, "SELECT p.id,p.provider_epoch FROM v24_cordis.pins p "
                                      "WHERE p.consumer_run_id=%s AND p.key='model'", (x['run_id'],))[0]
    model_fiber = q1(db, "SELECT c.fiber_id FROM v24_cordis.pins p "
                         "JOIN v24_cordis.contributions c ON c.id=p.contribution_id "
                         "WHERE p.id=%s", (model_pin,))
    model_contrib, model_ep, model_cepoch = rows(db, "SELECT c.id,c.episode_id,e.epoch "
                        "FROM v24_cordis.pins p JOIN v24_cordis.contributions c ON c.id=p.contribution_id "
                        "JOIN v24_cordis.episodes e ON e.id=c.episode_id WHERE p.id=%s", (model_pin,))[0]
    mc = claim(db, x['model_effect'])
    e8 = settle(db, x['model_effect'], model_body([tool_call('c1')]), mc['claim'])
    assert e8['disposition'] == 'committed' and len(e8['emitted']) == 1, e8
    tool = rows(db, "SELECT id FROM v24_cordis.effects WHERE run_id=%s AND kind='tool_call'",
                (x['run_id'],))[0][0]
    tc = claim(db, tool)
    e9 = settle(db, tool, tool_body(), tc['claim'])
    assert e9['disposition'] == 'committed' and len(e9['emitted']) == 1, e9
    assert _run(db, x['run_id'])[1] == 1
    cont = _continuation(db, x['run_id'])
    assert len(cont) == 1, cont
    mcontrol = _enter_closing(db, model_fiber)
    assert q1(db, 'SELECT retire_started_at IS NOT NULL FROM v24_cordis.fibers WHERE id=%s',
              (model_fiber,)) is True
    assert q1(db, 'SELECT withdrawn_at IS NOT NULL AND released_at IS NULL '
                  'FROM v24_cordis.contributions WHERE id=%s', (model_contrib,)) is True
    assert q1(db, 'SELECT v24_cordis.pin_readable(%s)', (model_pin,)) is True
    acontrol = _enter_closing(db, owner)
    a_p6, a_out, _ = _p6_slot(db, owner, acontrol)
    with contextlib.closing(db.connect('service')) as conn:
        deferred = no_write(db, conn, a_p6, a_out, disposition='deferred')
    assert deferred.get('disposition') == 'deferred', deferred
    assert q1(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (a_p6,)) == 'ready'
    m_p6, m_out, _ = _p6_slot(db, model_fiber, mcontrol)
    with contextlib.closing(db.connect('service')) as conn:
        mdeferred = no_write(db, conn, m_p6, m_out, disposition='deferred')
    assert mdeferred.get('disposition') == 'deferred', mdeferred
    assert q1(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (m_p6,)) == 'ready'
    pin_before = rows(db, 'SELECT id,contribution_id,provider_epoch FROM v24_cordis.pins '
                          'WHERE consumer_run_id=%s ORDER BY key', (x['run_id'],))
    assert all(p[2] == 1 for p in pin_before), pin_before
    assert model_epoch == 1 and model_cepoch == 1
    cc = claim(db, cont[0][0])
    final = model_body(final=True, text='e13')
    sealed = settle(db, cont[0][0], final, cc['claim'])
    assert sealed['disposition'] == 'committed' and sealed['emitted'] == [], sealed
    state, budget, ended, outcome = _run(db, x['run_id'])
    assert budget == 0 and ended is not None and state['phase'] == 'sealed', (budget, state)
    assert outcome == {'v': 1, 'reason': 'final', 'output': final['result'],
                       'dropped_tool_calls': 0}, outcome
    released = rows(db, 'SELECT contribution_id,provider_epoch,released_at FROM v24_cordis.pins '
                        'WHERE consumer_run_id=%s ORDER BY key', (x['run_id'],))
    assert all(p[2] is not None for p in released), released
    assert [(p[0], p[1]) for p in released] == [(p[1], p[2]) for p in pin_before], (released, pin_before)
    assert q1(db, 'SELECT count(*) FROM v24_cordis.pins WHERE consumer_fiber_id=%s '
                  'AND released_at IS NULL', (owner,)) > 0
    assert q1(db, 'SELECT v24_cordis.run_pin_release_delta(%s)', (x['run_id'],)) == []
    plan = q1(db, 'SELECT v24_cordis.p6_plan(%s,%s)', (a_p6, owner))
    assert not (plan['kind'] == 'deferred' and plan.get('reason') == 'run'), plan
    print('[CDP4-X3/X4] e7-e13: old pin/epoch settle after provider retire; e11c/e12 deferred zero-write; seal frees run pins, P6 unblocked')

def main():
    with Server() as server:
        with TestDB(server) as db: test_x1_final(db)
        with TestDB(server) as db: test_x1b_custom_model_key(db)
        with TestDB(server) as db: test_x2_model_over(db)
        with TestDB(server) as db: test_x2_tool_zero(db)
        with TestDB(server) as db: test_x5_negative_budget(db)
        with TestDB(server) as db: test_m6_model_failed(db)
        with TestDB(server) as db: test_x3_lifecycle(db)
        with TestDB(server) as db: test_validator(db)
        with TestDB(server) as db: test_run_start_forged(db)
    print('[passed] CDP4-X')


if __name__ == '__main__':
    main()
