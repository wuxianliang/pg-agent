"""Focused protocol-path contracts for Phase 0 gaps Q1/Q2/Q4/Q6/Q7/Q8/Q11.

The caller supplies the active test_core module as ``t`` so these checks reuse
its connection, DTO, state, fixture, and Fake-host helpers without importing it.
"""
from __future__ import annotations

import uuid
from psycopg2.extras import Json


def _eq(a, b):
    assert a == b, (a, b)


def _database_state(conn, t):
    names = ('runs','epochs','operations','effects','events','snapshots','wakes','requests','effect_pins')
    return {name: t.sql(conn, f"SELECT coalesce(jsonb_agg(j ORDER BY j::text),'[]') FROM (SELECT to_jsonb(r) AS j FROM v99_core.core_{name} r) q") for name in names}


def _poll_wait(db, t):
    c = db.connect()
    s = t.good(t.call(c, 'start', None, 'contract read only', 'contract-q1-start'))
    run = s['run_id']
    before = t.state(c, run)
    c.commit()
    c.set_session(readonly=True, autocommit=False)
    p = t.call(c, 'poll', None, run, 1)
    assert p['ok'] and p['run_id'] == run
    assert t.call(c, 'wait_check', None, run, 1, 1, 0)['reason'] == 'waiting'
    c.commit()
    c.set_session(readonly=False)
    _eq(t.state(c, run), before)
    _eq(t.call(c, 'poll', None, str(uuid.uuid4()), 1), {'schema_version':1,'ok':True,'reason':'expired'})
    _eq(t.call(c, 'poll', str(uuid.uuid4()), run, 1), {'schema_version':1,'ok':True,'reason':'expired'})
    _eq(t.state(c, run), before)

    # READ ONLY rejects even a write-capable control endpoint; failed statement
    # is rolled back before checking that all protocol state remains identical.
    c.commit()
    c.set_session(readonly=True, autocommit=False)
    try:
        t.call(c, 'steer', None, run, 'must not write', 'contract-q1-ro', 1)
    except Exception as exc:
        assert getattr(exc, 'pgcode', None) == '25006', (type(exc).__name__, exc)
        c.rollback()
    else:
        raise AssertionError('write-capable steer succeeded in READ ONLY transaction')
    c.set_session(readonly=False)
    _eq(t.state(c, run), before)
    c.commit()
    c.close()


def _wait_contract(db, t):
    c = db.connect()
    s = t.good(t.call(c, 'start', None, 'wait fifo', 'contract-q2-start'))
    run = s['run_id']
    # poll and wait_check both serve from an explicit READ ONLY transaction.
    c.commit(); c.set_session(readonly=True, autocommit=False)
    _eq(t.call(c, 'poll', None, run, 1)['status'], 'running')
    assert t.call(c, 'wait_check', None, run, 1, 1, 0)['reason'] == 'waiting'
    c.commit(); c.set_session(readonly=False)
    # Multiple committed steering wakes are delivered in FIFO order. A waiter
    # can repeat the cursor and gets the same first event; advancing sees next.
    a = t.good(t.call(c, 'steer', None, run, 'first', 'contract-q2-steer-1', 1))
    b = t.good(t.call(c, 'steer', None, run, 'second', 'contract-q2-steer-2', 1))
    x = t.call(c, 'wait_check', None, run, 1, 1, 1)
    y = t.call(c, 'wait_check', None, run, 1, 1, 1)
    assert x['reason'] == y['reason'] == 'interrupted_by_steering'
    assert x['wake_id'] == y['wake_id'] and x['snapshot']['steering_message'] == y['snapshot']['steering_message'] == 'first'
    z = t.call(c, 'wait_check', None, run, 1, 1, x['wake_id'])
    assert z['reason'] == 'interrupted_by_steering' and z['snapshot']['steering_message'] == 'second' and z['wake_id'] > x['wake_id']
    assert a['epoch_ordinal'] == b['epoch_ordinal'] == 1
    # Registration mismatch is expired and strictly read-only.
    before = t.state(c, run)
    expired = t.call(c, 'wait_check', None, run, 2, 1, 0)
    assert expired['reason'] == 'expired'
    _eq(t.state(c, run), before)

    # Complete current driving turn, terminal-steer into epoch 2, then old
    # epoch waiter receives durable steering body despite its old epoch.
    lease = t.good(t.call(c, 'driver_acquire', run, 'contract-q2-driver', 60000))
    c.commit()
    for old in (s['execution_operation_id'], a['execution_operation_id']):
        oldtoken = t.good(t.call(c, 'claim_effect', run, old, 'contract-q2-driver', lease['driver_fence']))
        assert t.good(t.ce_accept(c, oldtoken, t.ce_receipt(oldtoken, {'schema_version':1,'text':'old','ce_status':'completed'}), 'contract-q2-driver'))['disposition'] == 'archived_stale'
    op = b['execution_operation_id']
    tok = t.good(t.call(c, 'claim_effect', run, op, 'contract-q2-driver', lease['driver_fence']))
    result = t.ce_receipt(tok, {'schema_version':1,'text':'done','ce_status':'completed'})
    t.good(t.ce_accept(c, tok, result, 'contract-q2-driver'))
    term = t.good(t.call(c, 'steer', None, run, 'new epoch', 'contract-q2-terminal', 1))
    assert term['epoch_ordinal'] == 2
    assert t.sql(c, 'SELECT registration_generation=1 AND continuity_generation=1 FROM v99_core.core_runs WHERE run_id=%s', (run,))
    assert t.sql(c, "SELECT array_agg(transition_kind ORDER BY ordinal) FROM v99_core.core_epochs WHERE run_id=%s", (run,)) == ['initial','steering']
    assert t.sql(c, 'SELECT bool_and(registration_generation=1 AND continuity_generation=1) FROM v99_core.core_epochs WHERE run_id=%s', (run,))
    cross = t.call(c, 'wait_check', None, run, 1, 1, z['wake_id'])
    assert cross['reason'] == 'interrupted_by_steering' and cross['snapshot']['steering_message'] == 'new epoch'
    assert cross['registration_generation'] == cross['continuity_generation'] == 1
    assert cross['snapshot']['turn_ordinal'] > z['snapshot']['turn_ordinal']
    # Consuming that steering wake on the old epoch then reports advancement.
    adv = t.call(c, 'wait_check', None, run, 1, 1, cross['wake_id'])
    assert adv['reason'] == 'epoch_advanced'
    future = t.call(c, 'wait_check', None, run, 1, 3, 0)
    assert future['reason'] == 'invalid_wait_args'
    # Unknown run / malformed registration remain expired/invalid and do not mutate.
    _eq(t.call(c, 'wait_check', None, str(uuid.uuid4()), 1, 1, 0)['reason'], 'expired')

    # A blocked unknown snapshot is actionable to waiters, not an infinite wait.
    us = t.good(t.call(c, 'start', None, 'unknown actionable', 'contract-q2-unknown-start'))
    urun, uop = us['run_id'], us['execution_operation_id']
    ul, ut = t.ce_acquire_claim(c, urun, uop, 'contract-q2-unknown-driver')
    unknown = t.ce_receipt(ut, {'schema_version':1,'error':{'code':'ambiguous','message':'unknown'}}, 'unknown')
    t.good(t.ce_accept(c, ut, unknown, 'contract-q2-unknown-driver'))
    actionable = t.call(c, 'wait_check', None, urun, 1, 1, 0)
    assert actionable['reason'] == 'actionable' and actionable['snapshot']['status'] == 'blocked_unknown'
    c.commit()
    c.close()


def _response_contract(db, t):
    """Q4/G1: public operator respond, complete oneof and lease independence."""
    admin, operator, service = db.connect(), db.connect('operator'), db.connect('service')
    bodies = ({'response':'yes'}, {'response':0}, {'response':False},
              {'response':1.25}, {'response':True}, {'answers':{'a':'b'}}, {'skip':True})
    for i, body in enumerate(bodies):
        started = t.good(t.call(operator, 'start', None, 'response contract', f'contract-q4-start-{i}'))
        run, op = started['run_id'], started['execution_operation_id']
        operator.commit()
        lease, token = t.ce_acquire_claim(service, run, op, f'contract-q4-builder-{i}')
        inter = {'id':str(uuid.uuid4()),'kind':'question','channel':'human'}
        result = {'schema_version':1,'text':'prompt','ce_status':'waiting_for_input','interaction':inter}
        t.good(t.ce_accept(service, token, t.ce_receipt(token,result), f'contract-q4-builder-{i}'))
        service.commit()
        mode = ('absent','other_live','expired')[i % 3]
        # Owner injection prepares lease states; the tested action uses a real
        # non-superuser operator connection.
        if mode == 'absent':
            t.sql(admin, 'UPDATE v99_core.core_runs SET driver_owner=NULL,driver_lease_until=NULL WHERE run_id=%s', (run,))
        elif mode == 'other_live':
            t.sql(admin, "UPDATE v99_core.core_runs SET driver_owner='other-contract-owner',driver_lease_until=clock_timestamp()+interval '1 minute' WHERE run_id=%s", (run,))
        else:
            t.sql(admin, "UPDATE v99_core.core_runs SET driver_owner='expired-contract-owner',driver_lease_until=clock_timestamp()-interval '1 second' WHERE run_id=%s", (run,))
        admin.commit()
        lease_sql = 'SELECT jsonb_build_array(driver_owner,driver_lease_until,driver_fence) FROM v99_core.core_runs WHERE run_id=%s'
        before = t.sql(admin, lease_sql, (run,))
        assert (before[0] is None and before[1] is None) if mode == 'absent' else before[0] == ('other-contract-owner' if mode == 'other_live' else 'expired-contract-owner')
        if mode != 'absent':
            assert t.sql(admin, 'SELECT driver_lease_until>clock_timestamp() FROM v99_core.core_runs WHERE run_id=%s', (run,)) == (mode == 'other_live')
        out = t.good(t.call(operator, 'respond', None, run, inter['id'], dict(body, schema_version=1), f'contract-q4-respond-{i}'))
        operator.commit()
        assert out['status'] == 'running'
        _eq(t.sql(admin, lease_sql, (run,)), before)
        assert t.sql(admin, "SELECT count(*) FROM v99_core.core_effect_pins p JOIN v99_core.core_effects e USING(effect_id) WHERE e.run_id=%s AND e.kind='human' AND p.driver_fence IS NULL", (run,)) == 1
        admin.commit()
    started = t.good(t.call(operator, 'start', None, 'invalid responses', 'contract-q4-invalid-start'))
    run = started['run_id']; operator.commit()
    lease, token = t.ce_acquire_claim(service, run, started['execution_operation_id'], 'contract-q4-invalid-driver')
    inter = {'id':str(uuid.uuid4()),'kind':'question','channel':'human'}
    t.good(t.ce_accept(service, token, t.ce_receipt(token, {'schema_version':1,'text':'prompt','ce_status':'waiting_for_input','interaction':inter}), 'contract-q4-invalid-driver'))
    service.commit()
    invalid = [None, [], 'answer', False, 0, {},
        {'response':None}, {'response':[]}, {'response':{}}, {'response':''},
        {'answers':{}}, {'answers':[]}, {'answers':None}, {'answers':'x'}, {'answers':False},
        {'skip':False}, {'skip':1}, {'skip':'true'}, {'skip':None},
        {'response':'x','answers':{'a':1}}, {'response':'x','skip':True}, {'answers':{'a':1},'skip':True},
        {'response':'x','answers':{'a':1},'skip':True}, {'response':'x','extra':1},
        {'schema_version':2,'response':'x'}, {'schema_version':'1','response':'x'},
        {'schema_version':True,'response':'x'}]
    for i, body in enumerate(invalid):
        payload = dict(body, schema_version=body.get('schema_version',1)) if isinstance(body,dict) else Json(body)
        before = t.state(admin, run)
        t.refused(t.call(operator, 'respond', None, run, inter['id'], payload, f'contract-q4-bad-{i}'), 'invalid_response')
        operator.commit()
        _eq(t.state(admin, run), before)
    admin.commit()
    admin.close(); operator.close(); service.close()


def _control_replay_rollback(db, t):
    c = db.connect()
    # Inject failure after start has begun constructing state. Entire transaction
    # must leave neither rows nor a consumed request id; same ID then succeeds.
    before_database = _database_state(c, t)
    t.sql(c, "CREATE FUNCTION v99_core.contract_fail_start() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'contract injected'; END $$")
    t.sql(c, "CREATE TRIGGER contract_fail_start BEFORE INSERT ON v99_core.core_events FOR EACH ROW EXECUTE FUNCTION v99_core.contract_fail_start()")
    try:
        try:
            t.call(c, 'start', None, 'mid-start rollback', 'contract-q6-failed-start')
        except Exception:
            c.rollback()
        else:
            raise AssertionError('injected start failure did not escape')
    finally:
        c.rollback()
        assert t.sql(c, "SELECT count(*) FROM v99_core.core_requests WHERE request_id='contract-q6-failed-start'") == 0
        assert t.sql(c, "SELECT count(*) FROM v99_core.core_operations WHERE request_id='contract-q6-failed-start'") == 0
        _eq(_database_state(c, t), before_database)
        t.sql(c, 'DROP TRIGGER IF EXISTS contract_fail_start ON v99_core.core_events')
        t.sql(c, 'DROP FUNCTION IF EXISTS v99_core.contract_fail_start()')
        c.commit()
    started = t.good(t.call(c, 'start', None, 'mid-start rollback', 'contract-q6-failed-start'))
    run = started['run_id']
    before = t.state(c, run)
    _eq(t.call(c, 'start', None, 'mid-start rollback', 'contract-q6-failed-start'), started)
    _eq(t.state(c, run), before)
    t.refused(t.call(c, 'start', None, 'different', 'contract-q6-failed-start'), 'request_id_conflict')
    _eq(t.state(c, run), before)
    # Every control verb is completed with completed_at; execution admissions only pending.
    # Exercise steer, respond and cancel replay/conflict on protocol paths.
    before = t.state(c, run)
    steer = t.good(t.call(c, 'steer', None, run, 'active', 'contract-q6-steer', 1))
    after_steer = t.state(c, run)
    _eq(t.call(c, 'steer', None, run, 'active', 'contract-q6-steer', 1), steer)
    _eq(t.state(c, run), after_steer)
    t.refused(t.call(c, 'steer', None, run, 'different', 'contract-q6-steer', 1), 'request_id_conflict')
    _eq(t.state(c, run), after_steer)
    # Create a human interaction through a valid receipt, then respond and replay.
    lease, oldtoken = t.ce_acquire_claim(c, run, started['execution_operation_id'], 'contract-q6-driver')
    t.good(t.ce_accept(c, oldtoken, t.ce_receipt(oldtoken, {'schema_version':1,'text':'old','ce_status':'completed'}), 'contract-q6-driver'))
    op = steer['execution_operation_id']
    tok = t.good(t.call(c, 'claim_effect', run, op, 'contract-q6-driver', lease['driver_fence']))
    inter = {'id':str(uuid.uuid4()),'kind':'question','channel':'human'}
    t.good(t.ce_accept(c, tok, t.ce_receipt(tok, {'schema_version':1,'text':'q','ce_status':'waiting_for_input','interaction':inter}), 'contract-q6-driver'))
    assert t.sql(c, "SELECT count(*) FROM v99_core.core_operations WHERE run_id=%s AND status='pending' AND verb='admit_turn'", (run,)) == 0
    response = {'schema_version':1,'response':'answer'}
    responded = t.good(t.call(c, 'respond', None, run, inter['id'], response, 'contract-q6-respond'))
    assert t.sql(c, "SELECT array_agg(DISTINCT verb) FROM v99_core.core_operations WHERE run_id=%s AND status='pending'", (run,)) == ['admit_turn']
    after_response = t.state(c, run)
    _eq(t.call(c, 'respond', None, run, inter['id'], response, 'contract-q6-respond'), responded)
    _eq(t.state(c, run), after_response)
    t.refused(t.call(c, 'respond', None, run, inter['id'], {'schema_version':1,'response':'other'}, 'contract-q6-respond'), 'request_id_conflict')
    _eq(t.state(c, run), after_response)
    cancel = t.good(t.call(c, 'cancel', None, run, 'contract-q6-cancel'))
    after_cancel = t.state(c, run)
    _eq(t.call(c, 'cancel', None, run, 'contract-q6-cancel'), cancel)
    _eq(t.state(c, run), after_cancel)
    second = t.good(t.call(c, 'start', None, 'second cancel target', 'contract-q6-second-start'))
    second_before = t.state(c, second['run_id'])
    t.refused(t.call(c, 'cancel', None, second['run_id'], 'contract-q6-cancel'), 'request_id_conflict')
    _eq(t.state(c, second['run_id']), second_before)
    assert t.sql(c, "SELECT array_agg(DISTINCT verb ORDER BY verb) FROM v99_core.core_operations WHERE run_id=%s AND verb IN ('start','steer','respond','cancel')", (run,)) == ['cancel','respond','start','steer']
    # Check all controls and execution verbs are constrained in stored rows.
    assert t.sql(c, "SELECT count(*) FROM v99_core.core_operations WHERE run_id=%s AND verb IN ('start','steer','respond','cancel') AND (status<>'completed' OR completed_at IS NULL)", (run,)) == 0
    assert t.sql(c, "SELECT count(*) FROM v99_core.core_operations WHERE run_id=%s AND ((verb IN ('admit_turn','admit_tool') AND status NOT IN ('pending','completed','archived','closed')) OR (verb NOT IN ('admit_turn','admit_tool') AND status='pending'))", (run,)) == 0
    c.commit()
    c.close()


def _size_revision(db, t):
    c = db.connect()
    s = t.good(t.call(c, 'start', None, 'size boundary', 'contract-q7-start'))
    run, op = s['run_id'], s['execution_operation_id']
    lease, tok = t.ce_acquire_claim(c, run, op, 'contract-q7-driver')
    # Build a receipt whose canonical JSONB text is exactly 1 MiB + one byte.
    base = t.ce_receipt(tok, {'schema_version':1,'text':'x','ce_status':'completed'})
    valid_len = t.sql(c, 'SELECT octet_length(%s::jsonb::text)', (Json(base),))
    base['effect_result']['text'] = '界' * ((1048577-valid_len)//3) + 'x' * ((1048577-valid_len)%3)
    # Canonical formatting overhead is fixed for string contents; adjust ASCII length
    # to hit the exact byte target, then verify the measured SQL size before assertion.
    def receipt_size(): return t.sql(c, 'SELECT octet_length(%s::jsonb::text)', (Json(base),))
    delta = 1048577 - receipt_size()
    if delta > 0: base['effect_result']['text'] += 'x' * delta
    elif delta < 0: base['effect_result']['text'] = base['effect_result']['text'][:delta]
    assert receipt_size() == 1048577, receipt_size()
    t.zero_write(c, run, 'invalid_receipt', 'accept_receipt', op, 'ce:'+op+':receipt', 'contract-q7-driver', tok['driver_fence'], base)
    c.rollback()

    # T1 claims the current operation. An independent committed publication
    # advances revision while preserving driving_operation_id; T2 must publish
    # against the run row's locked revision rather than the T1 revision.
    s = t.good(t.call(c, 'start', None, 'locked revision', 'contract-q7-revision-start'))
    run, op = s['run_id'], s['execution_operation_id']
    lease, tok = t.ce_acquire_claim(c, run, op, 'contract-q7-revision-driver')
    c.commit()
    other = db.connect()
    t.good(t.call(other, 'write_snapshot', run, s['operation_id'], 'running', None, None, None, None, 'snapshot', None, False))
    other.commit(); other.close()
    assert t.sql(c, 'SELECT driving_operation_id::text FROM v99_core.core_runs WHERE run_id=%s', (run,)) == op
    revision_before = t.sql(c, 'SELECT revision FROM v99_core.core_runs WHERE run_id=%s', (run,))
    assert revision_before > 1 and revision_before == t.sql(c, 'SELECT revision FROM v99_core.core_snapshots WHERE run_id=%s', (run,))
    result = t.good(t.ce_accept(c, tok, t.ce_receipt(tok, {'schema_version':1,'text':'published','ce_status':'completed'}), 'contract-q7-revision-driver'))
    assert result['revision'] == revision_before + 1
    assert t.sql(c, 'SELECT revision FROM v99_core.core_snapshots WHERE run_id=%s', (run,)) == revision_before + 1
    c.commit()
    c.close()


def _unknown_wall(db, t):
    c = db.connect()
    s = t.good(t.call(c, 'start', None, 'unknown wall checks', 'contract-q8-start'))
    run, op = s['run_id'], s['execution_operation_id']
    lease, tok = t.ce_acquire_claim(c, run, op, 'contract-q8-driver')
    receipt = t.ce_receipt(tok, {'schema_version':1,'error':{'code':'ambiguous','message':'unknown'}}, 'unknown')
    # Before unknown wall, queue a second admission. The active steer changes
    # driving_operation_id, but the old claimed effect may still report unknown.
    queued = t.good(t.call(c, 'steer', None, run, 'queued before unknown', 'contract-q8-queued-steer', 1))
    first = t.good(t.ce_accept(c, tok, receipt, 'contract-q8-driver'))
    before = t.state(c, run)
    t.zero_write(c, run, 'unknown_wall', 'respond', None, run, str(uuid.uuid4()), {'schema_version':1,'response':'no'}, 'contract-q8-respond')
    t.zero_write(c, run, 'unknown_wall', 'steer', None, run, 'no', 'contract-q8-steer', 1)
    # Exact replay is journal lookup before unknown wall checks.
    _eq(t.ce_accept(c, tok, receipt, 'contract-q8-driver'), first)
    _eq(t.state(c, run), before)
    nextop = queued['execution_operation_id']
    effect = t.sql(c, 'SELECT effect_id FROM v99_core.core_effects WHERE operation_id=%s', (nextop,))
    fabricated = dict(tok, operation_id=nextop, effect_id=effect)
    for status in ('succeeded','failed','unknown'):
        payload = {'schema_version':1,'error':{'code':'blocked','message':'blocked'}} if status != 'succeeded' else {'schema_version':1,'text':'blocked','ce_status':'completed'}
        new_receipt = t.ce_receipt(fabricated, payload, status)
        t.zero_write(c, run, 'unknown_wall', 'accept_receipt', nextop, 'ce:'+nextop+':receipt', 'contract-q8-driver', tok['driver_fence'], new_receipt)
    _eq(t.state(c, run), before)
    altered = t.ce_receipt(tok, {'schema_version':1,'error':{'code':'other','message':'different'}}, 'unknown')
    t.zero_write(c, run, 'receipt_conflict', 'accept_receipt', op, 'ce:'+op+':receipt', 'contract-q8-driver', tok['driver_fence'], altered)
    c.commit()
    c.close()


def _public_accept_rejections(db, t):
    """G1: public T2 rejects stale owner/fence/lease without side effects."""
    operator, service, admin = db.connect('operator'), db.connect('service'), db.connect()
    for mode in ('wrong_owner','old_fence','expired'):
        start = t.good(t.call(operator, 'start', None, 'T2 rejection '+mode, 'contract-g1-start-'+mode))
        run, op = start['run_id'], start['execution_operation_id']
        operator.commit()
        lease, token = t.ce_acquire_claim(service, run, op, 'contract-g1-driver-'+mode)
        receipt = t.ce_receipt(token, {'schema_version':1,'text':'unused','ce_status':'completed'})
        service.commit()
        driver, fence, expected = 'contract-g1-driver-'+mode, lease['driver_fence'], 'driver_required'
        if mode == 'wrong_owner':
            driver = 'not-the-owner'
        elif mode == 'old_fence':
            fence = lease['driver_fence'] - 1
            expected = 'stale_claim'
        else:
            t.sql(admin, 'UPDATE v99_core.core_runs SET driver_lease_until=clock_timestamp()-interval \'1 second\' WHERE run_id=%s', (run,))
            admin.commit(); expected = 'driver_expired'
        before = t.state(admin, run)
        t.refused(t.call(service, 'accept_receipt', op, 'ce:'+op+':receipt', driver, fence, receipt), expected)
        service.commit()
        _eq(t.state(admin, run), before)
    admin.close(); operator.close(); service.close()


def _generation_attempts(db, t):
    c = db.connect()
    s = t.good(t.call(c, 'start', None, 'generation contract', 'contract-q11-start'))
    run, op = s['run_id'], s['execution_operation_id']
    assert t.sql(c, 'SELECT registration_generation=1 AND continuity_generation=1 AND current_epoch_ordinal=1 AND turn_ordinal=1 FROM v99_core.core_runs WHERE run_id=%s', (run,))
    token = t.good(t.call(c, 'driver_acquire', run, 'contract-q11-driver', 60000))
    llm = t.good(t.call(c, 'claim_effect', run, op, 'contract-q11-driver', token['driver_fence']))
    calls = {'schema_version':1,'tool_calls':[{'id':'q11-tool','name':'spawn_subsession','args':{'task':'one'}}]}
    t.good(t.ce_accept(c, llm, t.ce_receipt(llm, calls), 'contract-q11-driver'))
    toolop = t.good(t.call(c, 'discover', run, 'contract-q11-driver', token['driver_fence']))['next']['operation_id']
    tool = t.good(t.call(c, 'claim_effect', run, toolop, 'contract-q11-driver', token['driver_fence']))
    t.good(t.ce_accept(c, tool, t.ce_receipt(tool, {'schema_version':1,'adapter':'ce-fake-spawn','simulated':True,'task':'one'}), 'contract-q11-driver'))
    assert t.sql(c, 'SELECT turn_ordinal=1 FROM v99_core.core_operations WHERE operation_id=%s', (toolop,))
    assert t.sql(c, 'SELECT turn_ordinal=1 FROM v99_core.core_effects WHERE operation_id=%s', (toolop,))
    # Repeated admission creation uses per-run locked max+1 attempt_seq.
    # Run concurrent control admissions on independent connections; run locking
    # must allocate distinct attempt_seq values for every accepted operation.
    c.commit()
    barrier = t.Barrier(3)
    def admit(index):
        conn = db.connect('operator')
        barrier.wait(timeout=5)
        value = t.call(conn, 'steer', None, run, 'queue-'+str(index), 'contract-q11-steer-'+str(index), 1)
        conn.commit(); conn.close()
        return value
    with t.ThreadPoolExecutor(3) as pool:
        results = list(pool.map(admit, range(3)))
    assert all(value.get('ok') is True for value in results), results
    counts = t.sql(c, 'SELECT ARRAY[count(*),count(DISTINCT attempt_seq)] FROM v99_core.core_operations WHERE run_id=%s', (run,))
    assert counts[0] == counts[1] and counts[0] >= 10, counts
    assert t.sql(c, 'SELECT registration_generation=1 AND continuity_generation=1 FROM v99_core.core_runs WHERE run_id=%s', (run,))
    assert t.sql(c, 'SELECT bool_and(registration_generation=1 AND continuity_generation=1) FROM v99_core.core_epochs WHERE run_id=%s', (run,))
    # No inert lifecycle fields or unsupported transitions in the actual catalog.
    columns = t.sql(c, "SELECT coalesce(array_agg(column_name ORDER BY column_name),'{}') FROM information_schema.columns WHERE table_schema='v99_core' AND table_name IN ('core_runs','core_epochs','core_operations','core_effects','core_snapshots','core_wakes')")
    assert not any(name in {'generation','owner_generation','reason','origin','origin_operation_id','superseded_by'} or name.startswith(('origin_','superseded')) for name in columns), columns
    t._assert_raises_sqlstate(c, '23514', "UPDATE v99_core.core_epochs SET transition_kind='superseded' WHERE run_id=%s", (run,))
    transitions = t.sql(c, "SELECT coalesce(array_agg(DISTINCT transition_kind ORDER BY transition_kind),'{}') FROM v99_core.core_epochs")
    assert set(transitions) <= {'initial','steering'} and 'initial' in transitions
    c.commit()
    c.close()


def run_checks(db, t):
    """Run protocol-path contract groups Q1/Q2/Q4/Q6/Q7/Q8/Q11 on ``db``."""
    _poll_wait(db, t)
    _wait_contract(db, t)
    _response_contract(db, t)
    _control_replay_rollback(db, t)
    _size_revision(db, t)
    _public_accept_rejections(db, t)
    _unknown_wall(db, t)
    _generation_attempts(db, t)
    print('[Q1/Q2/Q4/Q6/Q7/Q8/Q11 contract checks] all protocol assertions passed')
