"""Complete independent W99 Core Phase 0 gate (Fake-only, local Unix socket).

No arguments runs the complete W2–W5 matrix. --w2-only/--w3-only remain
available for diagnosis and never represent the full gate.
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import inspect
import math
import os
import socket
import subprocess
import select
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from psycopg2.extras import Json
from psycopg2.extensions import TRANSACTION_STATUS_IDLE

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from v99.core.setup_db import setup_db, _assert_raises_sqlstate, server_helper_scope
from v99.core.catalog import assert_function_catalog
from v99.core import infrastructure_checks, contract_checks, review_checks


def sql(conn, statement, params=()):
    with conn.cursor() as cur:
        cur.execute(statement, params)
        return cur.fetchone()[0] if cur.description else None


def call(conn, name, *args):
    values = tuple(Json(v) if isinstance(v, (dict, list)) else v for v in args)
    return sql(conn, f"SELECT v99_core.v99_core_{name}({','.join(['%s'] * len(values))})", values)


def good(value):
    assert value.get('ok') is True, value
    return value


def refused(value, reason):
    assert value == {'schema_version': 1, 'ok': False, 'reason': reason}, value


def state(conn, run):
    # Stable whole-row evidence, including journals/pins/audits/projections.
    rows = {}
    for table in ('runs', 'epochs', 'operations', 'effects', 'events', 'snapshots', 'wakes', 'requests'):
        rows[table] = sql(conn, f"SELECT coalesce(jsonb_agg(j ORDER BY j::text),'[]') FROM (SELECT to_jsonb(t) j FROM v99_core.core_{table} t WHERE run_id=%s) q", (run,))
    rows['pins'] = sql(conn, "SELECT coalesce(jsonb_agg(j ORDER BY j::text),'[]') FROM (SELECT to_jsonb(p) j FROM v99_core.core_effect_pins p JOIN v99_core.core_effects e USING(effect_id) WHERE e.run_id=%s) q", (run,))
    return rows


def zero_write(conn, run, reason, name, *args):
    before = state(conn, run)
    refused(call(conn, name, *args), reason)
    assert state(conn, run) == before, (name, reason)


def operation(conn, run, verb='admit_turn', status='pending', payload=None):
    op = str(uuid.uuid4())
    sql(conn, """INSERT INTO v99_core.core_operations(operation_id,request_id,run_id,epoch_id,verb,turn_ordinal,attempt_seq,status,payload,payload_digest,completed_at)
        SELECT %s,%s,r.run_id,ep.epoch_id,%s,r.turn_ordinal,
          (SELECT coalesce(max(attempt_seq),0)+1 FROM v99_core.core_operations WHERE run_id=r.run_id),%s,%s,'owner-fixture',
          CASE WHEN %s='completed' THEN clock_timestamp() END
        FROM v99_core.core_runs r JOIN v99_core.core_epochs ep ON ep.run_id=r.run_id AND ep.ordinal=r.current_epoch_ordinal WHERE r.run_id=%s""",
        (op, 'owner-' + op, verb, status, Json(payload or {}), status, run))
    return op


def seed(conn):
    run, ep = str(uuid.uuid4()), str(uuid.uuid4())
    sql(conn, "INSERT INTO v99_core.core_runs(run_id,status) VALUES (%s,'running')", (run,))
    sql(conn, "INSERT INTO v99_core.core_epochs(epoch_id,run_id,ordinal,continuity_generation,registration_generation,transition_kind) VALUES (%s,%s,1,1,1,'initial')", (ep, run))
    op = operation(conn, run)
    sql(conn, "UPDATE v99_core.core_runs SET driving_operation_id=%s WHERE run_id=%s", (op, run))
    effect = good(call(conn, 'enqueue_effect', run, op, 'llm', {'message': 'fake input'}, 'owner:' + op))['effect_id']
    good(call(conn, 'write_snapshot', run, op, 'running', None, None, None, None, 'snapshot', None, True))
    return run, op, effect


def claim(conn, run, op, driver='d1', lease=60000):
    acquired = good(call(conn, 'driver_acquire', run, driver, lease))
    return good(call(conn, 'claim_effect', run, op, driver, acquired['driver_fence']))


def settle(conn, token, status='succeeded', result=None, **changes):
    fields = dict(run=token['run_id'], operation=token['operation_id'], effect=token['effect_id'],
                  driver='d1', driver_fence=token['driver_fence'], attempt=token['attempt_no'],
                  fence=token['fence'], context=token['context_revision'], catalog=token['catalog_revision'],
                  status=status, result=result or {'schema_version': 1, 'text': 'Fake result'})
    fields.update(changes)
    return call(conn, 'settle_effect', *fields.values())


def expire(conn, run):
    # Real clock expiry, bounded at two seconds. No SQL sleep or owner timestamp edit.
    deadline = time.monotonic() + 2
    while not sql(conn, "SELECT driver_lease_until<=clock_timestamp() FROM v99_core.core_runs WHERE run_id=%s", (run,)):
        assert time.monotonic() < deadline, 'lease expiry deadline'
        time.sleep(0.005)


def test_cas_pin(db):
    c = db.connect()
    run, op, effect = seed(c)
    token = claim(c, run, op)
    for changes, reason in (({'attempt': 2}, 'stale_claim'), ({'fence': 2}, 'stale_claim'),
                            ({'driver_fence': 2}, 'stale_claim'), ({'driver': 'other'}, 'driver_required'),
                            ({'context': 2}, 'stale_claim'), ({'catalog': 2}, 'stale_claim')):
        before = state(c, run)
        refused(settle(c, token, **changes), reason)
        assert state(c, run) == before
    for mutation in ("UPDATE v99_core.core_runs SET context_revision=context_revision+1 WHERE run_id=%s",
                     "UPDATE v99_core.core_effects SET request=request || '{\"tampered\":true}' WHERE run_id=%s",
                     "UPDATE v99_core.core_effects SET request_digest='tampered' WHERE run_id=%s"):
        sql(c, 'SAVEPOINT pin_probe')
        sql(c, mutation, (run,))
        before = state(c, run)
        refused(settle(c, token), 'stale_claim')
        assert state(c, run) == before
        sql(c, 'ROLLBACK TO SAVEPOINT pin_probe')
    sql(c, 'SAVEPOINT catalog_probe')
    sql(c, 'UPDATE v99_core.core_tools SET enabled=enabled')
    refused(settle(c, token), 'stale_claim')
    sql(c, 'ROLLBACK TO SAVEPOINT catalog_probe')
    _assert_raises_sqlstate(c, '23514', 'UPDATE v99_core.core_effect_pins SET fence=fence')
    before_revision = sql(c, 'SELECT revision FROM v99_core.core_runs WHERE run_id=%s', (run,))
    good(settle(c, token))
    assert sql(c, 'SELECT status FROM v99_core.core_effects WHERE effect_id=%s', (effect,)) == 'succeeded'
    assert sql(c, 'SELECT revision FROM v99_core.core_runs WHERE run_id=%s', (run,)) == before_revision
    before = state(c, run)
    refused(settle(c, token), 'stale_claim')
    assert state(c, run) == before
    sql(c, "UPDATE v99_core.core_operations SET status='completed',completed_at=clock_timestamp() WHERE operation_id=%s", (op,))
    closed = good(call(c, 'closeout', run, 'completed', op))
    assert closed['unsettled_claim_ids'] == closed['unknown_effect_ids'] == []
    assert sql(c, "SELECT count(*) FROM v99_core.core_wakes WHERE run_id=%s AND reason='terminal'", (run,)) == 1
    zero_write(c, run, 'already_terminal', 'closeout', run, 'completed', op)
    # Missing immutable pin: owner constructs a claimed row without a pin.
    missing_run, missing_op, missing_effect = seed(c)
    lease = good(call(c, 'driver_acquire', missing_run, 'd1', 60000))
    sql(c, "UPDATE v99_core.core_effects SET status='claimed',attempt_no=1,fence=1,claim_driver_fence=%s WHERE effect_id=%s", (lease['driver_fence'], missing_effect))
    missing = dict(token, run_id=missing_run, operation_id=missing_op, effect_id=missing_effect)
    before = state(c, missing_run)
    refused(settle(c, missing), 'stale_claim')
    assert state(c, missing_run) == before
    c.commit()
    print('[W2 CAS/pin] token/context/catalog/request/missing pin, immutable pins, one CAS, terminal seal')


def test_lease_fifo(db):
    a, b = db.connect(), db.connect()
    run, op, effect = seed(a)
    op2 = operation(a, run)
    good(call(a, 'enqueue_effect', run, op2, 'llm', {'message': 'queued'}, 'owner:' + op2))
    a.commit()
    for lease in (0, 60001, None):
        zero_write(a, run, 'invalid_args', 'driver_acquire', run, 'd1', lease)
    a.commit()
    barrier = Barrier(2)
    def acquire(conn, driver):
        barrier.wait(timeout=3)
        result = call(conn, 'driver_acquire', run, driver, 60000)
        conn.commit()
        return driver, result
    with ThreadPoolExecutor(2) as pool:
        fa, fb = pool.submit(acquire, a, 'd1'), pool.submit(acquire, b, 'd2')
        results = [fa.result(timeout=5), fb.result(timeout=5)]
    successes = [(d, r) for d, r in results if r['ok']]
    assert len(successes) == 1, results
    driver, lease = successes[0]
    refused(next(r for d, r in results if not r['ok']), 'driver_required')
    assert good(call(a, 'driver_acquire', run, driver, 60000))['driver_fence'] == lease['driver_fence']
    zero_write(a, run, 'not_claimable', 'claim_effect', run, op2, driver, lease['driver_fence'])
    token = good(call(a, 'claim_effect', run, op, driver, lease['driver_fence']))
    a.commit()
    assert sql(b, 'SELECT status FROM v99_core.core_effects WHERE effect_id=%s', (effect,)) == 'claimed'
    zero_write(b, run, 'not_claimable', 'claim_effect', run, op2, driver, lease['driver_fence'])
    b.commit()
    # Catalog maintenance waits on the claim's SHARE lock until T1 ends.
    run2, op3, _ = seed(a)
    claim(a, run2, op3)
    sql(b, "SET LOCAL lock_timeout='80ms'")
    _assert_raises_sqlstate(b, '55P03', 'UPDATE v99_core.core_tools SET enabled=enabled')
    b.rollback()
    a.commit()
    sql(b, 'UPDATE v99_core.core_tools SET enabled=enabled')
    b.commit()
    # Expiry alone cannot recover; reacquisition (even same owner) bumps fence.
    short = good(call(a, 'driver_acquire', run, driver, 1))
    a.commit()
    expire(a, run)
    zero_write(a, run, 'driver_expired', 'recover_unknown', run, driver, short['driver_fence'])
    zero_write(a, run, 'driver_expired', 'claim_effect', run, op2, driver, short['driver_fence'])
    before = state(a, run)
    refused(settle(a, token, driver=driver), 'driver_expired')
    assert state(a, run) == before
    newer = good(call(a, 'driver_acquire', run, driver, 60000))
    assert newer['driver_fence'] == short['driver_fence'] + 1
    before = state(a, run)
    refused(settle(a, token, driver=driver), 'stale_claim')
    assert state(a, run) == before
    zero_write(a, run, 'not_claimable', 'claim_effect', run, op2, driver, newer['driver_fence'])
    recovered = good(call(a, 'recover_unknown', run, driver, newer['driver_fence']))
    assert recovered['status'] == 'blocked_unknown' and recovered['unknown_effect_ids'] == [effect]
    zero_write(a, run, 'unknown_wall', 'claim_effect', run, op2, driver, newer['driver_fence'])
    before = state(a, run)
    assert good(call(a, 'recover_unknown', run, driver, newer['driver_fence']))['unknown_effect_ids'] == []
    assert state(a, run) == before
    assert not sql(a, "SELECT exists(SELECT 1 FROM information_schema.columns WHERE table_schema='v99_core' AND table_name='core_effects' AND column_name LIKE 'lease%%')")
    a.commit()
    print('[W2 lease/FIFO] two-driver race, renewal/expiry/reacquisition, bound FIFO, single claim, meta lock, recovery')


def test_unknown_cancel(db):
    c = db.connect()
    run, op, effect = seed(c)
    token = claim(c, run, op)
    error = {'schema_version': 1, 'error': {'code': 'ambiguous', 'message': 'Fake result unavailable'}}
    revision = sql(c, 'SELECT revision FROM v99_core.core_runs WHERE run_id=%s', (run,))
    good(settle(c, token, status='unknown', result=error))
    assert sql(c, 'SELECT status FROM v99_core.core_runs WHERE run_id=%s', (run,)) == 'blocked_unknown'
    assert sql(c, 'SELECT revision FROM v99_core.core_runs WHERE run_id=%s', (run,)) == revision + 1
    zero_write(c, run, 'unknown_wall', 'enqueue_effect', run, op, 'llm', {}, 'unknown-new')
    zero_write(c, run, 'unknown_wall', 'claim_effect', run, op, 'd1', token['driver_fence'])
    before = state(c, run)
    refused(settle(c, token), 'unknown_wall')
    assert state(c, run) == before
    # A genuine archived unknown must reject normal closeout directly.
    zero_write(c, run, 'unknown_wall', 'closeout', run, 'completed', op)
    # Nor can owner-injected operation completion cross the wall.
    sql(c, 'SAVEPOINT unknown_closeout')
    sql(c, "UPDATE v99_core.core_operations SET status='completed',completed_at=clock_timestamp() WHERE operation_id=%s", (op,))
    zero_write(c, run, 'unknown_wall', 'closeout', run, 'completed', op)
    sql(c, 'ROLLBACK TO SAVEPOINT unknown_closeout')
    cancel_op = operation(c, run, 'cancel', 'completed')
    result = good(call(c, 'closeout', run, 'cancelled', cancel_op))
    assert result['unknown_effect_ids'] == [effect] and result['unsettled_claim_ids'] == []
    # A separate cancellation has one claimed and one ready effect.
    run2, op2, effect2 = seed(c)
    token2 = claim(c, run2, op2)
    queued = operation(c, run2)
    ready = good(call(c, 'enqueue_effect', run2, queued, 'llm', {'message': 'queued'}, 'owner:' + queued))['effect_id']
    cancel2 = operation(c, run2, 'cancel', 'completed')
    result2 = good(call(c, 'closeout', run2, 'cancelled', cancel2))
    assert result2['unsettled_claim_ids'] == [effect2] and result2['cancelled_effect_ids'] == [ready] and result2['unknown_effect_ids'] == []
    assert sql(c, 'SELECT status FROM v99_core.core_operations WHERE operation_id=%s', (cancel2,)) == 'completed'
    assert sql(c, 'SELECT status FROM v99_core.core_effects WHERE effect_id=%s', (effect2,)) == 'claimed'
    assert sql(c, 'SELECT fence FROM v99_core.core_effects WHERE effect_id=%s', (effect2,)) == token2['fence'] + 1
    seal = sql(c, "SELECT payload FROM v99_core.core_events WHERE run_id=%s AND type='run/closed'", (run2,))
    assert set(seal) == {'schema_version','run_id','epoch_ordinal','status','cancelled_effect_ids','unsettled_claim_ids','unknown_effect_ids'}
    projection = state(c, run2)
    refused(settle(c, token2), 'stale_claim')
    assert state(c, run2)['snapshots'] == projection['snapshots'] and state(c, run2)['wakes'] == projection['wakes']
    good(call(c, 'driver_acquire', run2, 'd1', 1))
    c.commit()
    expire(c, run2)
    takeover = good(call(c, 'driver_acquire', run2, 'new-driver', 60000))
    recovery = good(call(c, 'recover_unknown', run2, 'new-driver', takeover['driver_fence']))
    assert recovery['status'] == 'cancelled' and recovery['unknown_effect_ids'] == [effect2]
    assert sql(c, "SELECT payload FROM v99_core.core_events WHERE run_id=%s AND type='run/closed'", (run2,)) == seal
    assert state(c, run2)['snapshots'] == projection['snapshots'] and state(c, run2)['wakes'] == projection['wakes']
    refused(settle(c, token2), 'unknown_wall')
    assert sql(c, "SELECT count(*) FROM v99_core.core_events WHERE run_id=%s AND type='receipt/late'", (run2,)) == 2
    before = state(c, run2)
    refused(settle(c, token2, operation=str(uuid.uuid4())), 'receipt_request_mismatch')
    after = state(c, run2)
    assert len(after['events']) == len(before['events']) + 1
    assert after['requests'] == before['requests'] == []
    c.commit()
    print('[W2 unknown/cancel] reported unknown, cancel-only wall, three seal arrays, late audits, cancelled recovery preserves seal/snapshot/wakes')


def test_human_atomic(db):
    a, b = db.connect(), db.connect()
    for lease_state in ('absent', 'valid', 'expired'):
        run, op, llm = seed(a)
        # Owner builds the post-LLM waiting fixture; W3 owns this transition.
        sql(a, "UPDATE v99_core.core_effects SET status='succeeded' WHERE effect_id=%s", (llm,))
        sql(a, "UPDATE v99_core.core_operations SET status='completed',completed_at=clock_timestamp() WHERE operation_id=%s", (op,))
        interaction = {'id': str(uuid.uuid4()), 'kind': 'instruction', 'channel': 'human'}
        human = good(call(a, 'enqueue_effect', run, op, 'human', interaction, 'human:' + op))['effect_id']
        good(call(a, 'write_snapshot', run, op, 'waiting_for_input', 'Fake question', interaction, None, human))
        if lease_state != 'absent':
            good(call(a, 'driver_acquire', run, 'unrelated-driver', 60000 if lease_state == 'valid' else 1))
        a.commit()
        if lease_state == 'expired':
            expire(a, run)
            a.commit()
        before = state(a, run)
        # Worker claim never consumes a human interaction.
        if lease_state == 'valid':
            driver_fence = sql(a, 'SELECT driver_fence FROM v99_core.core_runs WHERE run_id=%s', (run,))
            zero_write(a, run, 'run_not_running', 'claim_effect', run, op, 'unrelated-driver', driver_fence)
        lease_before = sql(a, "SELECT jsonb_build_array(driver_owner,driver_fence,driver_lease_until) FROM v99_core.core_runs WHERE run_id=%s", (run,))
        # Full rollback after the internal claim/CAS leaves no pin/event/state.
        good(call(a, 'settle_human', run, interaction['id'], {'schema_version': 1, 'response': False}))
        assert sql(b, 'SELECT status FROM v99_core.core_effects WHERE effect_id=%s', (human,)) == 'ready'
        assert sql(b, 'SELECT count(*) FROM v99_core.core_effect_pins WHERE effect_id=%s', (human,)) == 0
        b.commit()
        a.rollback()
        assert state(a, run) == before
        good(call(a, 'settle_human', run, interaction['id'], {'schema_version': 1, 'response': 0}))
        assert sql(a, 'SELECT status FROM v99_core.core_effects WHERE effect_id=%s', (human,)) == 'succeeded'
        assert sql(a, 'SELECT driver_fence IS NULL FROM v99_core.core_effect_pins WHERE effect_id=%s', (human,))
        assert sql(a, "SELECT jsonb_build_array(driver_owner,driver_fence,driver_lease_until) FROM v99_core.core_runs WHERE run_id=%s", (run,)) == lease_before
        # Run lock prevents concurrent consumption/cancel until the whole control
        # transaction commits; W3 adds control/admission/snapshot in this boundary.
        sql(b, "SET LOCAL lock_timeout='80ms'")
        _assert_raises_sqlstate(b, '55P03', 'SELECT v99_core.v99_core_settle_human(%s,%s,%s)', (run, interaction['id'], Json({'schema_version': 1, 'skip': True})))
        b.rollback()
        a.commit()
        zero_write(b, run, 'interaction_mismatch', 'settle_human', run, interaction['id'], {'schema_version': 1, 'skip': True})
        b.commit()
        event = sql(a, "SELECT payload FROM v99_core.core_events WHERE run_id=%s AND type='human/responded'", (run,))
        assert event['settlement_channel'] == 'operator_response' and event['caller_role'] == 'postgres'
        a.commit()
    print('[W2 human] absent/live/expired driver, atomic visibility/rollback, NULL driver pin, exclusive consumption, caller audit')


def test_closeout_wake(db):
    a, b = db.connect(), db.connect()
    sql(b, 'LISTEN v99_core_run_changed')
    b.commit()
    run, op, effect = seed(a)
    zero_write(a, run, 'pending_work', 'closeout', run, 'completed', op)
    sql(a, "UPDATE v99_core.core_operations SET status='completed',completed_at=clock_timestamp() WHERE operation_id=%s", (op,))
    zero_write(a, run, 'pending_work', 'closeout', run, 'completed', op)
    sql(a, "UPDATE v99_core.core_effects SET status='succeeded' WHERE effect_id=%s", (effect,))
    interaction = {'id': str(uuid.uuid4()), 'kind': 'question', 'channel': 'ce'}
    sql(a, 'UPDATE v99_core.core_runs SET interaction=%s WHERE run_id=%s', (Json(interaction), run))
    zero_write(a, run, 'closeout_blocked', 'closeout', run, 'completed', op)
    sql(a, 'UPDATE v99_core.core_runs SET interaction=NULL WHERE run_id=%s', (run,))
    good(call(a, 'closeout', run, 'failed', op, None, {'code': 'fake', 'message': 'Fake failure'}))
    assert sql(b, 'SELECT count(*) FROM v99_core.core_wakes WHERE run_id=%s', (run,)) == 0
    b.commit()
    b.poll()
    assert not b.notifies, b.notifies
    a.rollback()
    assert sql(b, 'SELECT count(*) FROM v99_core.core_wakes WHERE run_id=%s', (run,)) == 0
    b.commit()
    run, op, effect = seed(a)
    a.commit()
    deadline = time.monotonic() + 2
    while not b.notifies:
        b.poll()
        assert time.monotonic() < deadline, 'commit notification deadline'
        time.sleep(0.005)
    assert b.notifies.pop().payload == run + '|1'
    assert sql(b, 'SELECT count(*) FROM v99_core.core_wakes WHERE run_id=%s', (run,)) == 1
    b.commit()
    # An unlistened connection reads the same durable wake independently.
    sql(b, 'UNLISTEN *')
    b.commit()
    assert sql(b, 'SELECT count(*) FROM v99_core.core_wakes WHERE run_id=%s', (run,)) == 1
    b.commit()
    print('[W2 closeout/wake] terminal guards, one terminal wake, commit-only notification, rollback, durable wake without listener')


def ce_start(conn, message='start message', request='ce-start'):
    return sql(conn, 'SELECT v99_core.v99_core_start(%s,%s,%s)', (None, message, request))


def ce_acquire_claim(conn, run, op, driver='w3-driver'):
    lease = call(conn, 'driver_acquire', run, driver, 60000)
    good(lease)
    return lease, good(call(conn, 'claim_effect', run, op, driver, lease['driver_fence']))


def ce_receipt(token, result, status='succeeded'):
    return {'schema_version': 1, 'status': status, 'effect_id': token['effect_id'],
            'attempt_no': token['attempt_no'], 'fence': token['fence'],
            'context_revision': token['context_revision'], 'catalog_revision': token['catalog_revision'],
            'effect_result': result}


def ce_accept(conn, token, receipt, driver='w3-driver'):
    return call(conn, 'accept_receipt', token['operation_id'],
                'ce:' + token['operation_id'] + ':receipt', driver, token['driver_fence'], receipt)


def test_w3_control_fifo(db):
    c = db.connect()
    started = ce_start(c)
    assert set(started) == {'schema_version','ok','run_id','operation_id','execution_operation_id','effect_id',
        'registration_generation','epoch_ordinal','continuity_generation','revision','status'}
    assert started['operation_id'] != started['execution_operation_id'] and started['revision'] == 1
    run, old_op = started['run_id'], started['execution_operation_id']
    before = state(c, run)
    assert call(c, 'start', None, 'start message', 'ce-start') == started
    assert state(c, run) == before
    refused(call(c, 'start', None, 'other message', 'ce-start'), 'request_id_conflict')
    poll = call(c, 'poll', None, run, 1)
    assert set(poll) == {'schema_version','ok','run_id','registration_generation','epoch_ordinal','continuity_generation','revision','status','snapshot'}
    assert set(poll['snapshot']) == {'run_id','registration_generation','epoch_ordinal','turn_ordinal','revision','status','interaction',
        'assistant_text','failure_reason','last_operation_id','interaction_effect_id','updated_at','steering_message'}
    waiting = call(c, 'wait_check', None, run, 1, 1, 0)
    assert set(waiting) == {'schema_version','reason','snapshot','registration_generation','epoch_ordinal','continuity_generation','interaction','wake_id'}
    assert waiting['reason'] == 'waiting' and waiting['wake_id'] == 1
    assert call(c, 'wait_check', None, run, 1, 0, 0)['reason'] == 'invalid_wait_args'
    lease = good(call(c, 'driver_acquire', run, 'w3-driver', 60000))
    old_token = good(call(c, 'claim_effect', run, old_op, 'w3-driver', lease['driver_fence']))
    steered = call(c, 'steer', None, run, 'follow-up', 'steer-active', 1)
    good(steered)
    assert set(steered) == {'schema_version','ok','run_id','operation_id','execution_operation_id','epoch_ordinal','revision','status','queued'}
    assert steered['epoch_ordinal'] == 1 and steered['queued'] is True and steered['revision'] == 2
    wake = call(c, 'wait_check', None, run, 1, 1, 1)
    assert wake['reason'] == 'interrupted_by_steering' and wake['snapshot']['steering_message'] == 'follow-up'
    before_revision = sql(c, 'SELECT revision FROM v99_core.core_runs WHERE run_id=%s', (run,))
    stale = good(ce_accept(c, old_token, ce_receipt(old_token, {'schema_version':1,'text':'old','ce_status':'completed'})))
    assert stale['disposition'] == 'archived_stale'
    assert sql(c, 'SELECT revision FROM v99_core.core_runs WHERE run_id=%s', (run,)) == before_revision
    new_token = good(call(c, 'claim_effect', run, steered['execution_operation_id'], 'w3-driver', lease['driver_fence']))
    final = good(ce_accept(c, new_token, ce_receipt(new_token, {'schema_version':1,'text':'new','ce_status':'completed'})))
    assert final['status'] == 'completed'
    reopened = good(call(c, 'steer', None, run, 'new epoch', 'steer-terminal', 1))
    assert reopened['epoch_ordinal'] == 2 and reopened['queued'] is False
    assert sql(c, 'SELECT turn_ordinal FROM v99_core.core_runs WHERE run_id=%s', (run,)) == 3
    cancelled = good(call(c, 'cancel', None, run, 'cancel-reopened'))
    assert set(cancelled) == {'schema_version','ok','run_id','operation_id','revision','status','cancelled_effect_ids','unsettled_claim_ids','unknown_effect_ids'}
    refused(call(c, 'steer', None, run, 'resurrect', 'steer-cancelled', 2), 'already_terminal')
    assert good(call(c, 'poll', None, run, 1))['status'] == 'cancelled'
    c.commit()
    print('[W3 control/FIFO] closed DTOs, start replay/conflict, wait cursor, active old receipt, terminal epoch reopen, cancel-only terminal')


def test_w3_respond_and_unknown(db):
    c = db.connect()
    start = ce_start(c, 'human prompt', 'human-start')
    run, op = start['run_id'], start['execution_operation_id']
    lease, token = ce_acquire_claim(c, run, op)
    interaction = {'id': str(uuid.uuid4()), 'kind':'question', 'channel':'human'}
    answer = {'schema_version':1,'text':'Please answer'}
    completed = good(ce_accept(c, token, ce_receipt(token, {'schema_version':1,'text':'Please answer','ce_status':'waiting_for_input','interaction':interaction})))
    assert completed['status'] == 'waiting_for_input'
    eid = sql(c, 'SELECT interaction_effect_id FROM v99_core.core_snapshots WHERE run_id=%s', (run,))
    assert sql(c, 'SELECT kind FROM v99_core.core_effects WHERE effect_id=%s', (eid,)) == 'human'
    before = state(c, run)
    refused(call(c, 'respond', None, run, 'bad-uuid', {'schema_version':1,'skip':True}, 'bad-id'), 'invalid_args')
    refused(call(c, 'respond', None, run, interaction['id'], {'schema_version':1,'skip':True,'response':False}, 'bad-oneof'), 'invalid_response')
    refused(call(c, 'respond', None, run, interaction['id'], {'schema_version':1,'response':''}, 'bad-empty'), 'invalid_response')
    assert state(c, run) == before
    response = good(call(c, 'respond', None, run, interaction['id'], {'schema_version':1,'response':False}, 'human-response'))
    assert set(response) == {'schema_version','ok','run_id','operation_id','execution_operation_id','epoch_ordinal','revision','status'}
    assert response['status']=='running' and sql(c, 'SELECT status FROM v99_core.core_effects WHERE effect_id=%s',(eid,))=='succeeded'
    assert sql(c, 'SELECT driver_fence IS NULL FROM v99_core.core_effect_pins WHERE effect_id=%s ORDER BY attempt_no DESC LIMIT 1',(eid,))
    assert call(c, 'respond', None, run, interaction['id'], {'schema_version':1,'response':False}, 'human-response') == response
    assert sql(c, "SELECT count(*) FROM v99_core.core_effects WHERE run_id=%s AND kind='human'", (run,)) == 1
    ce = ce_start(c, 'CE prompt', 'ce-start-second')
    crun, cop = ce['run_id'], ce['execution_operation_id']
    cle, ctok = ce_acquire_claim(c, crun, cop)
    ci = {'id':str(uuid.uuid4()),'kind':'approval','channel':'ce'}
    good(ce_accept(c, ctok, ce_receipt(ctok, {'schema_version':1,'text':'Choose','ce_status':'waiting_for_input','interaction':ci})))
    assert sql(c, "SELECT count(*) FROM v99_core.core_effects WHERE run_id=%s AND kind='human'", (crun,)) == 0
    good(call(c, 'respond', None, crun, ci['id'], {'schema_version':1,'answers':{'choice':'yes'}}, 'ce-response'))
    # A valid reported unknown is journalled, creates the unknown wall, and replay survives cancel.
    us = ce_start(c, 'uncertain', 'unknown-start')
    urun, uop = us['run_id'], us['execution_operation_id']
    ul, ut = ce_acquire_claim(c, urun, uop)
    unknown_receipt = ce_receipt(ut, {'schema_version':1,'error':{'code':'ambiguous','message':'Fake result uncertain'}}, 'unknown')
    unknown = good(ce_accept(c, ut, unknown_receipt))
    assert unknown['disposition']=='unknown' and unknown['status']=='blocked_unknown'
    refused(call(c, 'steer', None, urun, 'no', 'unknown-steer', 1), 'unknown_wall')
    replay_before = state(c, urun)
    assert ce_accept(c, ut, unknown_receipt) == unknown and state(c, urun) == replay_before
    close = good(call(c, 'cancel', None, urun, 'unknown-cancel'))
    assert close['unknown_effect_ids']==[ut['effect_id']]
    assert ce_accept(c, ut, unknown_receipt) == unknown
    c.commit()
    print('[W3 respond/unknown] strict one-of, human/CE settlement, human pin, replay, unknown wall and cancel-only')


def test_w3_tool_and_atomic_replay(db):
    c = db.connect()
    start=ce_start(c,'tool please','tool-start'); run=start['run_id']; driver='tool-driver'
    lease=good(call(c,'driver_acquire',run,driver,60000)); op=start['execution_operation_id']
    token=good(call(c,'claim_effect',run,op,driver,lease['driver_fence']))
    result={'schema_version':1,'tool_calls':[{'id':'call-1','name':'spawn_subsession','args':{'task':'task one'}},
        {'id':'call-2','name':'spawn_subsession','args':{'task':'task two'}}]}
    valid=ce_receipt(token,result)
    for bad, reason in ((dict(valid,extra=True),'invalid_receipt'),(dict(valid,attempt_no=0),'invalid_receipt'),
        (dict(valid,effect_id='not-a-uuid'),'invalid_receipt'),(dict(valid,effect_result={'schema_version':1,'tool_calls':[{'id':'x','name':'missing','args':{}}]}),'invalid_tool')):
        zero_write(c,run,reason,'accept_receipt',op,'ce:'+op+':receipt',driver,lease['driver_fence'],bad)
    before_successor=state(c,run)
    sql(c,"CREATE FUNCTION v99_core.test_reject_tool() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.kind='tool' THEN PERFORM v99_core.v99_core_require(v99_core.v99_core_error('invalid_tool')); END IF; RETURN NEW; END $$")
    sql(c,'CREATE TRIGGER test_reject_tool BEFORE INSERT ON v99_core.core_effects FOR EACH ROW EXECUTE FUNCTION v99_core.test_reject_tool()')
    refused(ce_accept(c,token,valid,driver),'invalid_tool')
    assert state(c,run)==before_successor
    sql(c,'DROP TRIGGER test_reject_tool ON v99_core.core_effects')
    sql(c,'DROP FUNCTION v99_core.test_reject_tool()')
    first=good(ce_accept(c,token,valid,driver))
    assert first['status']=='running' and sql(c,"SELECT count(*) FROM v99_core.core_effects WHERE run_id=%s AND kind='tool'",(run,))==2
    hist=good(call(c,'worker_history',run,driver,lease['driver_fence']))
    assert [x['type'] for x in hist['events']].count('tool/call')==2
    for index, task in enumerate(('task one','task two')):
        discovered=good(call(c,'discover',run,driver,lease['driver_fence']))['next']
        assert discovered['kind']=='tool'
        tt=good(call(c,'claim_effect',run,discovered['operation_id'],driver,lease['driver_fence']))
        assert tt['request']['params']['task']==task
        tr={'schema_version':1,'adapter':'ce-fake-spawn','simulated':True,'task':task}
        got=good(ce_accept(c,tt,ce_receipt(tt,tr),driver))
        if index==0: assert got['status']=='running'
    next_item=good(call(c,'discover',run,driver,lease['driver_fence']))['next']
    assert next_item['kind']=='llm'
    nt=good(call(c,'claim_effect',run,next_item['operation_id'],driver,lease['driver_fence']))
    assert nt['request']['continuation_from']==op
    # Mid-T2 P0001 after effect settlement must escape and roll every write back.
    final_receipt=ce_receipt(nt,{'schema_version':1,'text':'after tools','ce_status':'completed'})
    before=state(c,run)
    sql(c,"CREATE FUNCTION v99_core.test_fail_snapshot() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected unknown failure' USING ERRCODE='P0001'; END $$")
    sql(c,'CREATE TRIGGER test_fail_snapshot BEFORE INSERT OR UPDATE ON v99_core.core_snapshots FOR EACH ROW EXECUTE FUNCTION v99_core.test_fail_snapshot()')
    sql(c,'SAVEPOINT injected_t2')
    try:
        ce_accept(c,nt,final_receipt,driver)
    except Exception as exc:
        assert getattr(exc,'pgcode',None)=='P0001', (type(exc).__name__,getattr(exc,'pgcode',None),exc)
    else:
        raise AssertionError('unknown P0001 was swallowed')
    sql(c,'ROLLBACK TO SAVEPOINT injected_t2')
    assert state(c,run)==before
    sql(c,'DROP TRIGGER test_fail_snapshot ON v99_core.core_snapshots')
    sql(c,'DROP FUNCTION v99_core.test_fail_snapshot()')
    # A registered publication business rejection is returned only after rolling back the full T2.
    sql(c,"CREATE FUNCTION v99_core.test_reject_snapshot() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM v99_core.v99_core_require(v99_core.v99_core_error('revision_conflict')); RETURN NEW; END $$")
    sql(c,'CREATE TRIGGER test_reject_snapshot BEFORE INSERT OR UPDATE ON v99_core.core_snapshots FOR EACH ROW EXECUTE FUNCTION v99_core.test_reject_snapshot()')
    refused(ce_accept(c,nt,final_receipt,driver),'revision_conflict')
    assert state(c,run)==before
    sql(c,'DROP TRIGGER test_reject_snapshot ON v99_core.core_snapshots')
    sql(c,'DROP FUNCTION v99_core.test_reject_snapshot()')
    committed=good(ce_accept(c,nt,final_receipt,driver)); c.commit()
    # Simulate lost COMMIT, then takeover/catalog change; exact journal replay bypasses new lease/pin/catalog checks.
    sql(c,"UPDATE v99_core.core_runs SET driver_lease_until=clock_timestamp()-interval '1 second' WHERE run_id=%s",(run,)); c.commit()
    takeover=good(call(c,'driver_acquire',run,'takeover-driver',60000)); assert takeover['driver_fence']==nt['driver_fence']+1
    sql(c,'UPDATE v99_core.core_tools SET enabled=enabled')
    c.commit()
    before=state(c,run)
    replay=ce_accept(c,nt,final_receipt,driver)
    assert replay==committed and state(c,run)==before
    print('[W3 tool/T2] ordered tools, unknown P0001/business rollback, lost-COMMIT replay after takeover/catalog change')


def test_w3_validation(db):
    c = db.connect()
    s = good(ce_start(c, 'validation', 'validation-start')); run=s['run_id']
    lease, token = ce_acquire_claim(c, run, s['execution_operation_id'])
    result={'schema_version':1,'text':'final','ce_status':'completed'}
    valid=ce_receipt(token,result); op=token['operation_id']; rid='ce:'+op+':receipt'
    bad_receipts=[]
    for key in valid:
        bad_receipts.append({k:v for k,v in valid.items() if k!=key})
    for key in ('attempt_no','fence','context_revision','catalog_revision'):
        for value in (None,True,'1',0,-1,1.5,2147483648 if key=='attempt_no' else 9223372036854775808):
            bad_receipts.append(dict(valid,**{key:value}))
    bad_receipts += [dict(valid,schema_version='1'),dict(valid,status='cancelled'),dict(valid,effect_result=[])]
    bad_results=[{}, {'schema_version':1}, dict(result,unknown=1),dict(result,text=''),dict(result,text=False),
        {'schema_version':1,'text':'x'},dict(result,interaction=None),dict(result,failure_reason=None),
        dict(result,tool_calls=[]),{'schema_version':1,'tool_calls':{}},
        {'schema_version':1,'text':'x','ce_status':'failed'},
        {'schema_version':1,'text':'x','ce_status':'waiting_for_input','interaction':None},
        {'schema_version':1,'tool_calls':[{'id':'x','name':'spawn_subsession','args':{'task':'x'},'extra':True}]},
        {'schema_version':1,'tool_calls':[{'id':'x','name':'spawn_subsession','args':{'task':'x'}}]*2}]
    for bad in bad_receipts+[dict(valid,effect_result=x) for x in bad_results]:
        zero_write(c,run,'invalid_receipt','accept_receipt',op,rid,'w3-driver',token['driver_fence'],bad)
    for status in ('failed','unknown'):
        for error in ({'code':'','message':'x'},{'code':'x','message':'x','extra':1},{'code':1,'message':'x'}):
            zero_write(c,run,'invalid_receipt','accept_receipt',op,rid,'w3-driver',token['driver_fence'],
                ce_receipt(token,{'schema_version':1,'error':error},status))
    for args in ({},{'task':''},{'task':'x','extra':1},{'task':False},{'task':'x'*1025}):
        bad=dict(valid,effect_result={'schema_version':1,'tool_calls':[{'id':'x','name':'spawn_subsession','args':args}]})
        zero_write(c,run,'invalid_tool_args','accept_receipt',op,rid,'w3-driver',token['driver_fence'],bad)
    # The actual JSONB UTF-8 size is authoritative, including multibyte text.
    for text in ('x'*1048576,'界'*349526):
        zero_write(c,run,'invalid_receipt','accept_receipt',op,rid,'w3-driver',token['driver_fence'],dict(valid,effect_result=dict(result,text=text)))
    for changes in ({'attempt_no':token['attempt_no']+1},{'fence':token['fence']+1},
                    {'context_revision':token['context_revision']+1},{'catalog_revision':token['catalog_revision']+1}):
        zero_write(c,run,'stale_claim','accept_receipt',op,rid,'w3-driver',token['driver_fence'],dict(valid,**changes))
    for statement in ('UPDATE v99_core.core_runs SET context_revision=context_revision+1 WHERE run_id=%s',
                      "UPDATE v99_core.core_effects SET request_digest='tampered' WHERE run_id=%s"):
        sql(c,'SAVEPOINT pin_validation'); sql(c,statement,(run,))
        zero_write(c,run,'stale_claim','accept_receipt',op,rid,'w3-driver',token['driver_fence'],valid)
        sql(c,'ROLLBACK TO SAVEPOINT pin_validation')
    before=state(c,run)
    refused(ce_accept(c,token,dict(valid,effect_id=str(uuid.uuid4()))),'receipt_request_mismatch')
    after=state(c,run)
    assert len(after['events'])==len(before['events'])+1 and after['requests']==before['requests']
    assert {k:v for k,v in after.items() if k!='events'}=={k:v for k,v in before.items() if k!='events'}
    # Same receipt ID remains available after binding rejection.
    accepted=good(ce_accept(c,token,valid))
    assert set(accepted)=={'schema_version','ok','run_id','operation_id','effect_id','disposition','revision','status'}
    before=state(c,run)
    refused(ce_accept(c,token,dict(valid,effect_result=dict(result,text='different'))),'receipt_conflict')
    assert state(c,run)==before
    expired={'schema_version':1,'ok':True,'reason':'expired'}
    assert call(c,'poll',None,run,2)==expired and call(c,'poll',str(uuid.uuid4()),run,1)==expired
    c.commit()
    print('[W3 validation] receipt/result/error/tool closed sets, numeric overflow, UTF-8 size, stale pins, mismatch audit and conflict')


def test_w3_instruction_and_old_tools(db):
    c=db.connect()
    for channel in ('human','ce'):
        s=good(ce_start(c,'instruction','instruction-'+channel)); run=s['run_id']; op=s['execution_operation_id']
        lease,t=ce_acquire_claim(c,run,op)
        interaction={'id':str(uuid.uuid4()),'kind':'instruction','channel':channel}
        good(ce_accept(c,t,ce_receipt(t,{'schema_version':1,'text':'What next?','ce_status':'waiting_for_input','interaction':interaction})))
        before=state(c,run)
        human=sql(c,'SELECT interaction_effect_id FROM v99_core.core_snapshots WHERE run_id=%s',(run,))
        if human:
            # Use another unjournalled execution ID so replay conflict does not hide human validation.
            bogus_op=operation(c,run)
            zero_write(c,run,'invalid_receipt','accept_receipt',bogus_op,'ce:'+bogus_op+':receipt','w3-driver',t['driver_fence'],
                ce_receipt(dict(t,effect_id=human),{'schema_version':1,'text':'human worker attempt','ce_status':'completed'}))
            sql(c,"UPDATE v99_core.core_operations SET status='archived',archive_reason='test-only',completed_at=clock_timestamp() WHERE operation_id=%s",(bogus_op,))
        steered=good(call(c,'steer',None,run,'new instruction','consume-'+channel,1))
        assert steered['epoch_ordinal']==1 and steered['queued']
        assert sql(c,'SELECT interaction IS NULL AND turn_ordinal=2 FROM v99_core.core_runs WHERE run_id=%s',(run,))
        if human: assert sql(c,'SELECT status FROM v99_core.core_effects WHERE effect_id=%s',(human,))=='succeeded'
        # A late different response cannot consume the instruction again.
        zero_write(c,run,'interaction_mismatch','respond',None,run,interaction['id'],{'schema_version':1,'response':0},'consumed-'+channel)
    # A non-instruction interaction directs steer to respond without a write.
    s=good(ce_start(c,'question','noninstruction')); run=s['run_id']; lease,t=ce_acquire_claim(c,run,s['execution_operation_id'])
    inter={'id':str(uuid.uuid4()),'kind':'question','channel':'ce'}
    good(ce_accept(c,t,ce_receipt(t,{'schema_version':1,'text':'Question','ce_status':'waiting_for_input','interaction':inter})))
    zero_write(c,run,'use_respond','steer',None,run,'wrong verb','use-respond',1)
    # Already admitted old tools keep FIFO and archive; none may spawn continuation.
    s=good(ce_start(c,'tools','old-tools')); run=s['run_id']; lease,t=ce_acquire_claim(c,run,s['execution_operation_id'])
    calls={'schema_version':1,'tool_calls':[{'id':str(i),'name':'spawn_subsession','args':{'task':str(i)}} for i in range(2)]}
    good(ce_accept(c,t,ce_receipt(t,calls)))
    head=good(call(c,'discover',run,'w3-driver',lease['driver_fence']))['next']
    oldt=good(call(c,'claim_effect',run,head['operation_id'],'w3-driver',lease['driver_fence']))
    steered=good(call(c,'steer',None,run,'new driving','old-tool-steer',1)); revision=steered['revision']
    for index in range(2):
        if index: oldt=good(call(c,'claim_effect',run,good(call(c,'discover',run,'w3-driver',lease['driver_fence']))['next']['operation_id'],'w3-driver',lease['driver_fence']))
        out=good(ce_accept(c,oldt,ce_receipt(oldt,{'schema_version':1,'adapter':'ce-fake-spawn','simulated':True,'task':str(index)})))
        assert out['disposition']=='archived_stale' and out['revision']==revision
    assert sql(c,"SELECT count(*) FROM v99_core.core_operations WHERE request_id=%s",('ce:'+t['operation_id']+':next_turn',))==0
    assert good(call(c,'discover',run,'w3-driver',lease['driver_fence']))['next']['operation_id']==steered['execution_operation_id']
    nt=good(call(c,'claim_effect',run,steered['execution_operation_id'],'w3-driver',lease['driver_fence']))
    failed=good(ce_accept(c,nt,ce_receipt(nt,{'schema_version':1,'error':{'code':'fake','message':'failed'}},'failed')))
    assert failed['status']=='failed'
    reopened=good(call(c,'steer',None,run,'retry','failed-reopen',1)); assert reopened['epoch_ordinal']==2
    c.commit()
    print('[W3 instruction/old-chain] human/CE instruction consume, use_respond, old tool FIFO without continuation, failed reopen')


def test_w4_acl(db):
    operator = db.connect('operator')
    reader = db.connect('reader')
    service = db.connect('service')
    started = call(operator, 'start', None, 'operator route test', 'operator-start')
    good(started)
    run = started['run_id']
    operator.commit()
    # Both LOGIN identities must actually call poll/wait; this catches missing operator GRANTs.
    assert good(call(operator, 'poll', None, run, 1))['run_id'] == run
    assert set(call(operator, 'wait_check', None, run, 1, 1, 0)) == {'schema_version','reason','snapshot','registration_generation','epoch_ordinal','continuity_generation','interaction','wake_id'}
    assert good(call(reader, 'poll', None, run, 1))['run_id'] == run
    assert call(reader, 'wait_check', None, run, 1, 1, 0)['reason'] == 'waiting'
    for conn, statement in ((operator, 'SELECT * FROM v99_core.core_runs'),
                            (reader, 'SELECT * FROM v99_core.core_runs'),
                            (service, 'SELECT * FROM v99_core.core_runs'),
                            (service, 'SELECT v99_core.v99_core_start(NULL,\'x\',\'x\')'),
                            (operator, 'SELECT v99_core.v99_core_driver_acquire(%s,\'x\',1000)')):
        _assert_raises_sqlstate(conn, '42501', statement, (run,) if '%s' in statement else ())
        conn.rollback()
    _assert_raises_sqlstate(operator, '42501', 'SET ROLE v99_core_service')
    operator.rollback()
    for conn in (operator, reader, service):
        conn.commit()
    # Owner's fixed search_path prevents temporary/public shadowing of relations.
    with db.connect('admin') as owner:
        with owner.cursor() as cur:
            cur.execute('CREATE TEMP TABLE core_runs(run_id uuid)')
        owner.commit()
    assert good(call(service, 'driver_acquire', run, 'acl-driver', 1000))['driver_fence'] == 1
    service.rollback()
    print('[W4 ACL] actual operator and reader LOGIN poll/wait routes, service routes, private/table/TEMP/SET ROLE denials')


def _idle(conn):
    assert conn.info.transaction_status == TRANSACTION_STATUS_IDLE, conn.info.transaction_status


class DefinitelyUnsent(Exception):
    """Fake transport proves no request bytes left the process."""


class AmbiguousFakeFailure(Exception):
    """Fake transport cannot establish whether a request was observed."""


class FakeLLM:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def complete(self, history):
        self.calls += 1
        if not self.results:
            raise AssertionError('unexpected FakeLLM call')
        value = self.results.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class FakeTool:
    def __init__(self):
        self.calls = 0

    def execute(self, request):
        self.calls += 1
        return {'schema_version': 1, 'adapter': 'ce-fake-spawn', 'simulated': True,
                'task': request['params']['task']}


class FakeHost:
    """Worker uses projections and accept only; all Fake IO runs while idle."""
    def __init__(self, db, llm, tool=None):
        self.db, self.llm, self.tool = db, llm, tool or FakeTool()
        self.driver = 'phase0-fake-host-' + uuid.uuid4().hex
        self.conn = db.connect('service')
        self.fence = None
        self.io_count = 0

    def start_driver(self, run):
        try:
            self.fence = good(call(self.conn, 'driver_acquire', run, self.driver, 60000))['driver_fence']
            self.conn.commit()
            _idle(self.conn)
            good(call(self.conn, 'recover_unknown', run, self.driver, self.fence))
            self.conn.commit()
            _idle(self.conn)
        except BaseException:
            self.conn.rollback()
            raise

    def step(self, run, *, fail_t2=False, lose_commit=False):
        next_item = good(call(self.conn, 'discover', run, self.driver, self.fence))['next']
        if next_item is None:
            self.conn.commit()
            return None
        token = good(call(self.conn, 'claim_effect', run, next_item['operation_id'], self.driver, self.fence))
        history = good(call(self.conn, 'worker_history', run, self.driver, self.fence))
        self.conn.commit()  # T1: the claim and immutable pin are durable before IO.
        _idle(self.conn)
        observer = self.db.connect('service')
        refused(call(observer, 'claim_effect', run, token['operation_id'], self.driver, self.fence), 'not_claimable')
        observer.rollback()
        observer.close()
        if token['kind'] == 'llm':
            result = None
            for attempt in range(2):
                self.io_count += 1
                _idle(self.conn)
                try:
                    result = self.llm.complete(history['events'])
                    _idle(self.conn)
                    break
                except DefinitelyUnsent:
                    _idle(self.conn)
                    if attempt == 1:
                        result = {'schema_version':1,'error':{'code':'definitely_unsent','message':'Fake request was not sent'}}
                        break
                except AmbiguousFakeFailure:
                    _idle(self.conn)
                    result = {'schema_version':1,'error':{'code':'ambiguous','message':'Fake outcome unknown'}}
                    break
            status = 'failed' if result.get('error', {}).get('code') == 'definitely_unsent' else ('unknown' if result.get('error', {}).get('code') == 'ambiguous' else 'succeeded')
        else:
            self.io_count += 1
            _idle(self.conn)
            result = self.tool.execute(token['request'])
            _idle(self.conn)
            status = 'failed' if 'error' in result else 'succeeded'
        receipt = ce_receipt(token, result, status)
        self.conn.rollback()
        _idle(self.conn)
        if fail_t2:
            with self.db.connect('admin') as owner:
                sql(owner, "CREATE FUNCTION v99_core.test_host_t2_fault() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'mid T2' USING ERRCODE='P0001'; END $$")
                sql(owner, 'CREATE TRIGGER test_host_t2_fault BEFORE UPDATE ON v99_core.core_snapshots FOR EACH ROW EXECUTE FUNCTION v99_core.test_host_t2_fault()')
                owner.commit()
            try:
                ce_accept(self.conn, token, receipt, self.driver)
            except Exception as exc:
                assert getattr(exc, 'pgcode', None) == 'P0001'
                self.conn.rollback()
            else:
                raise AssertionError('mid-T2 failure did not escape')
            with self.db.connect('admin') as owner:
                sql(owner, 'DROP TRIGGER test_host_t2_fault ON v99_core.core_snapshots')
                sql(owner, 'DROP FUNCTION v99_core.test_host_t2_fault()')
                owner.commit()
            refused(call(self.conn, 'claim_effect', run, token['operation_id'], self.driver, self.fence), 'not_claimable')
            self.conn.rollback()
        accepted = good(ce_accept(self.conn, token, receipt, self.driver))
        if lose_commit:
            self.conn.commit()
            self.conn.rollback()
            replay = ce_accept(self.conn, token, receipt, self.driver)
            assert replay == accepted
        self.conn.commit()
        _idle(self.conn)
        return accepted


def ce_wait(conn, actor, run, registration, epoch, after_wake_id, *, timeout, interval=0.05, listen=False, on_notification=None):
    """Short read transactions; notifications only shorten polling delay."""
    def valid_uuid(value):
        try:
            uuid.UUID(str(value))
            return True
        except (ValueError, TypeError, AttributeError):
            return False
    def positive_int(value, allow_zero=False):
        return isinstance(value, int) and not isinstance(value, bool) and (0 <= value <= 9223372036854775807 if allow_zero else 0 < value <= 9223372036854775807)
    valid_timeout = isinstance(timeout, (int, float)) and not isinstance(timeout, bool) and math.isfinite(timeout) and 0 <= timeout <= 3600
    valid_interval = isinstance(interval, (int, float)) and not isinstance(interval, bool) and math.isfinite(interval) and 0.01 <= interval <= 1
    if (conn.info.transaction_status != TRANSACTION_STATUS_IDLE or not valid_uuid(run)
            or (actor is not None and not valid_uuid(actor))
            or not positive_int(registration) or not positive_int(epoch)
            or not positive_int(after_wake_id, allow_zero=True)
            or not valid_timeout or not valid_interval or not isinstance(listen, bool)
            or (on_notification is not None and not callable(on_notification))):
        raise ValueError('invalid wait invocation')
    primary_error = None
    try:
        if listen:
            with conn.cursor() as cur:
                cur.execute('LISTEN v99_core_run_changed')
            conn.commit()
        deadline = time.monotonic() + timeout
        while True:
            value = call(conn, 'wait_check', actor, run, registration, epoch, after_wake_id)
            conn.commit()
            if value['reason'] != 'waiting':
                return value
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return dict(value, reason='timed_out')
            delay = min(interval, remaining)
            if listen:
                readable, _, _ = select.select([conn], [], [], delay)
                if readable:
                    conn.poll()
                    # Notification payloads are never authoritative; drain them
                    # and loop back to wait_check for the durable projection.
                    pending, conn.notifies[:] = list(conn.notifies), []
                    if on_notification is not None:
                        on_notification(pending)
            else:
                time.sleep(delay)
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        try:
            if not conn.closed:
                if conn.info.transaction_status != TRANSACTION_STATUS_IDLE:
                    conn.rollback()
                if listen:
                    with conn.cursor() as cur:
                        cur.execute('UNLISTEN v99_core_run_changed')
                    conn.commit()
                _idle(conn)
        except BaseException as cleanup_error:
            # A failed SQL statement leaves INERROR. Roll it back even when
            # UNLISTEN itself failed, without replacing the original failure.
            try:
                if not conn.closed:
                    conn.rollback()
            except BaseException as rollback_error:
                cleanup_error.add_note(f'wait rollback failed: {rollback_error!r}')
            if primary_error is None:
                raise
            primary_error.add_note(f'wait cleanup failed: {cleanup_error!r}')


def test_w5_fake_worker_and_wait(db):
    operator = db.connect('operator')
    started = good(call(operator, 'start', None, 'Fake worker prompt', 'fake-host-start'))
    run = started['run_id']
    operator.commit()
    host = FakeHost(db, FakeLLM([{'schema_version': 1, 'text': 'Fake final', 'ce_status': 'completed'}]))
    host.start_driver(run)
    assert host.step(run, fail_t2=True, lose_commit=True)['status'] == 'completed'
    assert host.io_count == host.llm.calls == 1
    assert good(call(operator, 'poll', None, run, 1))['status'] == 'completed'
    chain = good(call(operator, 'start', None, 'Fake tool chain', 'fake-chain-start')); operator.commit()
    chain_llm = FakeLLM([{'schema_version':1,'tool_calls':[{'id':'fake-call','name':'spawn_subsession','args':{'task':'fake task'}}]},
                         {'schema_version':1,'text':'tool result consumed','ce_status':'completed'}])
    chain_host = FakeHost(db, chain_llm)
    chain_host.start_driver(chain['run_id'])
    for _ in range(3):
        final = chain_host.step(chain['run_id'])
    assert final['status'] == 'completed' and chain_host.tool.calls == 1 and chain_llm.calls == 2
    chain_host.conn.close()
    operator.commit()
    _idle(operator)
    host.conn.close()
    # DefinitelyUnsent is retried at most once; ambiguous failure becomes unknown without retry.
    retry_start = good(call(operator, 'start', None, 'unsent retry', 'unsent-start'))
    operator.commit()
    retry_host = FakeHost(db, FakeLLM([DefinitelyUnsent('not sent'), {'schema_version':1,'text':'retried once','ce_status':'completed'}]))
    retry_host.start_driver(retry_start['run_id'])
    assert retry_host.step(retry_start['run_id'])['status'] == 'completed'
    assert retry_host.llm.calls == retry_host.io_count == 2
    retry_host.conn.close()
    exhausted_start = good(call(operator, 'start', None, 'unsent exhausted', 'unsent-exhausted-start'))
    operator.commit()
    exhausted_host = FakeHost(db, FakeLLM([DefinitelyUnsent('not sent'), DefinitelyUnsent('still not sent')]))
    exhausted_host.start_driver(exhausted_start['run_id'])
    assert exhausted_host.step(exhausted_start['run_id'])['status'] == 'failed'
    assert exhausted_host.llm.calls == exhausted_host.io_count == 2
    exhausted_host.conn.close()
    unknown_start = good(call(operator, 'start', None, 'ambiguous result', 'ambiguous-start'))
    operator.commit()
    ambiguous_host = FakeHost(db, FakeLLM([AmbiguousFakeFailure('unknown')]))
    ambiguous_host.start_driver(unknown_start['run_id'])
    assert ambiguous_host.step(unknown_start['run_id'])['status'] == 'blocked_unknown'
    assert ambiguous_host.llm.calls == ambiguous_host.io_count == 1
    ambiguous_host.conn.close()
    # Durable wake cursor works without LISTEN; timeout performs a final table re-read.
    s = good(call(operator, 'start', None, 'wait prompt', 'fake-wait-start')); wrun = s['run_id']; operator.commit()
    waiting = ce_wait(operator, None, wrun, 1, 1, 1, timeout=0, listen=False)
    assert waiting['reason'] == 'timed_out' and len(waiting) == 8
    second = db.connect('reader')
    assert ce_wait(second, None, wrun, 1, 1, 1, timeout=0.025, interval=0.01, listen=True)['reason'] == 'timed_out'
    # Every static argument error must be rejected before even LISTEN/SQL.
    original = globals()['call']
    globals()['call'] = lambda *a, **k: (_ for _ in ()).throw(AssertionError('invalid args issued SQL'))
    invalid_cases = [
        ((None, 'not-a-uuid', 1, 1, 0), {'timeout':1}),
        ((str(uuid.uuid4()), 'bad-actor', 1, 1, 0), {'timeout':1}),
        ((None, wrun, True, 1, 0), {'timeout':1}),
        ((None, wrun, 1.5, 1, 0), {'timeout':1}),
        ((None, wrun, 1, 0, 0), {'timeout':1}),
        ((None, wrun, 1, 1, -1), {'timeout':1}),
        ((None, wrun, 1, 1, True), {'timeout':1}),
    ]
    invalid_cases += [((None, wrun, 1, 1, 0), kwargs) for kwargs in
        ({'timeout':-1}, {'timeout':float('nan')}, {'timeout':True}, {'timeout':1,'interval':0.001},
         {'timeout':1,'interval':float('inf')}, {'timeout':1,'interval':True}, {'timeout':1,'listen':1},
         {'timeout':1,'on_notification':False}, {'timeout':-1,'listen':True})]
    class NoSQLConnection:
        info = operator.info
        def cursor(self, *args, **kwargs):
            raise AssertionError('invalid wait invocation opened cursor, including LISTEN')
        def commit(self):
            raise AssertionError('invalid wait invocation committed')
    no_sql = NoSQLConnection()
    invalid_cases += [((None, wrun, 9223372036854775808, 1, 0), {'timeout':1}),
                      ((None, wrun, 1, 9223372036854775808, 0), {'timeout':1}),
                      ((None, wrun, 1, 1, 9223372036854775808), {'timeout':1}),
                      (('bad-actor', wrun, 1, 1, 0), {'timeout':1}),
                      ((None, wrun, 1, 1, 0), {'timeout':3601}),
                      ((None, wrun, 1, 1, 0), {'timeout':1,'interval':1.01})]
    try:
        for args, kwargs in invalid_cases:
            for listening in (False, True):
                try:
                    ce_wait(no_sql, *args, **dict({'listen':listening}, **kwargs))
                except ValueError:
                    pass
                else:
                    raise AssertionError(('invalid wait args accepted', args, kwargs))
    finally:
        globals()['call'] = original
    assert second.info.transaction_status == TRANSACTION_STATUS_IDLE
    # Two independent waiters can read the same durable wake. A reversed/omitted
    # notification cannot hide the table state from either cursor.
    waiter_a, waiter_b = db.connect('reader'), db.connect('reader')
    observed_notifications = []
    with ThreadPoolExecutor(1) as pool:
        waiting_future = pool.submit(ce_wait, waiter_b, None, wrun, 1, 1, 1,
                                    timeout=0.5, interval=0.2, listen=True,
                                    on_notification=lambda notes: observed_notifications.extend(n.payload for n in notes))
        time.sleep(0.03)
        sql(operator, "SELECT pg_notify('v99_core_run_changed','not-the-run|999')")
        operator.commit()
        time.sleep(0.03)
        good(call(operator, 'steer', None, wrun, 'wake-one', 'wait-steer', 1))
        operator.commit()
        wake_b = waiting_future.result(timeout=2)
    # Out-of-order/unrelated notification data is only a hint. The LISTEN
    # waiter sees the matching durable projection after it arrives.
    assert 'not-the-run|999' in observed_notifications
    assert wake_b['reason'] == 'interrupted_by_steering' and wake_b['wake_id'] >= 2
    # A separate non-listening cursor still sees the same committed wake.
    wake_a = ce_wait(waiter_a, None, wrun, 1, 1, 1, timeout=0.2, listen=False)
    assert wake_a['reason'] == 'interrupted_by_steering' and wake_a['wake_id'] == wake_b['wake_id']
    waiter_a.close(); waiter_b.close()
    print('[W5 host/wait] T1 commit-visible claim, IDLE Fake IO, T2 rollback/replay without re-IO, lost-COMMIT receipt replay, eight-key timeout, LISTEN cleanup')


@contextlib.contextmanager
def unix_only_socket_guard():
    """Guard every Python-created socket during the complete independent gate."""
    original = socket.socket
    attempts = []
    def guarded(family=socket.AF_INET, *args, **kwargs):
        attempts.append(family)
        if family != socket.AF_UNIX:
            raise AssertionError(f'network socket family forbidden: {family}')
        return original(family, *args, **kwargs)
    socket.socket = guarded
    try:
        yield attempts
    finally:
        socket.socket = original


_BANNED_IMPORT_ROOTS = {
    'requests', 'httpx', 'openai', 'anthropic', 'cohere', 'mistralai', 'together',
    'groq', 'ollama', 'vertexai', 'google', 'boto3', 'botocore', 'transformers',
    'socket', 'subprocess', 'aiohttp', 'websockets', 'urllib', 'http', 'ftplib',
    'telnetlib', 'paramiko', 'fabric', 'grpc', 'zmq', 'smtplib',
}


def _network_violations(source):
    tree = ast.parse(source)
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            violations.extend(alias.name for alias in node.names if alias.name.split('.')[0] in _BANNED_IMPORT_ROOTS)
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.split('.')[0] in _BANNED_IMPORT_ROOTS:
            violations.append(node.module)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr in {'create_connection', 'urlopen'}:
                violations.append(ast.unparse(node.func))
            if isinstance(node.func, ast.Name) and node.func.id in {'__import__'}:
                if node.args and isinstance(node.args[0], ast.Constant) and str(node.args[0].value).split('.')[0] in _BANNED_IMPORT_ROOTS:
                    violations.append(str(node.args[0].value))
            if isinstance(node.func, ast.Attribute) and node.func.attr == 'import_module' and node.args:
                if isinstance(node.args[0], ast.Constant) and str(node.args[0].value).split('.')[0] in _BANNED_IMPORT_ROOTS:
                    violations.append(str(node.args[0].value))
    return violations


def _allowed_subprocess_command(argv):
    """Only the setup toolchain executables may be launched by a child process."""
    if not isinstance(argv, (list, tuple)) or not argv or not isinstance(argv[0], str):
        return False
    return Path(argv[0]).name in {'psql', 'uv'}


@contextlib.contextmanager
def subprocess_guard():
    """Popen backs run/call/check_*; reject shell/override and non-setup tools."""
    original = subprocess.Popen
    original_system, original_popen = os.system, os.popen
    signature = inspect.signature(original)
    def guarded(*args, **kwargs):
        invocation = signature.bind_partial(*args, **kwargs).arguments
        command = invocation.get('args')
        if (invocation.get('shell', False) or invocation.get('executable') is not None
                or not _allowed_subprocess_command(command)):
            raise AssertionError(f'subprocess forbidden by Phase 0 whitelist: {command!r}')
        return original(*args, **kwargs)
    def forbidden_shell(*args, **kwargs):
        raise AssertionError('shell entry point forbidden')
    subprocess.Popen = guarded
    os.system = os.popen = forbidden_shell
    try:
        yield
    finally:
        subprocess.Popen = original
        os.system, os.popen = original_system, original_popen


def _runtime_dependency_violations(sources=None):
    violations = []
    root = Path(__file__).resolve().parent
    if sources is None:
        sources = {path.name: path.read_text(encoding='utf-8') for path in sorted(root.rglob('*.py'))}
    for filename, source in sources.items():
        tree = ast.parse(source, filename=filename)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    base = alias.name.split('.')[0]
                    # Only these exact guard imports are exceptions. All other
                    # imports and every call in this same file are still scanned.
                    allowed_guard_import = ((filename == 'test_core.py' and alias.name in {'socket','subprocess'})
                                           or (filename == 'setup_db.py' and alias.name == 'subprocess'))
                    if base in _BANNED_IMPORT_ROOTS and not allowed_guard_import:
                        violations.append((filename, alias.name))
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split('.')[0] in _BANNED_IMPORT_ROOTS:
                    violations.append((filename, node.module))
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == '__import__':
                    violations.append((filename, 'dynamic import'))
                if isinstance(node.func, ast.Attribute):
                    name = ast.unparse(node.func)
                    if node.func.attr == 'import_module':
                        violations.append((filename, 'dynamic import'))
                    if (name.startswith('subprocess.') and node.func.attr in {'Popen','run','call','check_call','check_output','getoutput','getstatusoutput'}
                            or name in {'os.system','os.popen'}):
                        command = node.args[0] if node.args else None
                        shell = any(kw.arg == 'shell' and not (isinstance(kw.value, ast.Constant) and kw.value.value is False) for kw in node.keywords)
                        if shell or not isinstance(command, (ast.List, ast.Tuple)) or not all(isinstance(x, ast.Constant) for x in command.elts):
                            violations.append((filename, name, 'shell/nonliteral command'))
                        elif not _allowed_subprocess_command([x.value for x in command.elts]):
                            violations.append((filename, name, ast.unparse(command)))
    return violations


def test_w5_catalog_and_guards(db):
    source = inspect.getsource(FakeHost) + inspect.getsource(FakeLLM) + inspect.getsource(FakeTool)
    assert not _network_violations(source)
    assert not _runtime_dependency_violations(), _runtime_dependency_violations()
    for negative in ('import requests','import socket','import subprocess','from openai import OpenAI','import urllib.request',
                     'import cohere','import google.generativeai','__import__("anthropic")',
                     'importlib.import_module("mistralai")'):
        assert _network_violations(negative), negative
    assert _network_violations('import requests') and _network_violations('import socket') and _network_violations('import subprocess')
    assert _allowed_subprocess_command(['psql', '-X', 'postgres'])
    assert _allowed_subprocess_command(['/usr/bin/uv', 'run', 'python', 'x.py'])
    assert not _allowed_subprocess_command(['curl', 'https://example.invalid'])
    assert not _allowed_subprocess_command(['python', '-c', 'import socket'])
    for snippet in ('subprocess.Popen(["curl", "x"])', 'subprocess.run(["python", "x"])',
                    'subprocess.call(["sh", "-c", "x"])', 'os.system("x")',
                    'subprocess.run(["uv", "--version"], shell=True)', 'import openai'):
        # Same filename as the real guard proves its exceptions do not skip calls/imports.
        assert _runtime_dependency_violations({'test_core.py': snippet}), snippet
    for entry in ('Popen','run','call','check_call','check_output'):
        try:
            getattr(subprocess, entry)(['curl', 'https://example.invalid'])
        except AssertionError as exc:
            assert 'whitelist' in str(exc)
        else:
            raise AssertionError(('runtime subprocess guard bypassed', entry))
    try:
        getattr(subprocess, 'Popen')(['uv', '--version'], shell=True)
    except AssertionError as exc:
        assert 'whitelist' in str(exc)
    else:
        raise AssertionError('shell=True bypassed subprocess guard')
    # Safe local positive actually reaches Popen under the same installed guard.
    assert subprocess.run(['uv', '--version'], capture_output=True, check=True).returncode == 0
    assert 'core_runs' not in source and 'core_effects' not in source and 'pg_sleep' not in source and 'spawn_subsession(' not in source
    for snippet in ('socket.socket(socket.AF_INET, socket.SOCK_STREAM)', 'socket.socket(socket.AF_INET6, socket.SOCK_STREAM)'):
        family = ast.parse(snippet).body[0].value.args[0].attr
        assert family in {'AF_INET', 'AF_INET6'}  # negative examples for the family guard
    old_socket = socket.socket
    seen = []
    def unix_only(family, *args, **kwargs):
        seen.append(family)
        if family != socket.AF_UNIX:
            raise AssertionError('non-Unix socket attempted')
        return old_socket(family, *args, **kwargs)
    socket.socket = unix_only
    try:
        try:
            socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        except AssertionError:
            pass
        else:
            raise AssertionError('AF_INET guard did not reject')
    finally:
        socket.socket = old_socket
    assert seen == [socket.AF_INET]
    # AF_INET6 is rejected by the same runtime guard, while local DSN validation
    # remains the libpq locality proof.
    try:
        with unix_only_socket_guard():
            socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    except AssertionError:
        pass
    else:
        raise AssertionError('AF_INET6 guard did not reject')
    c = db.connect('admin')
    # Exact relation/function signatures, indexes, triggers and definer contract.
    rels = sql(c, "SELECT array_agg(relname ORDER BY relname) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='v99_core' AND c.relkind IN ('r','p')")
    assert set(rels) == {'core_runs','core_epochs','core_operations','core_effects','core_events','core_snapshots','core_wakes','core_effect_pins','core_requests','core_tools','core_meta'}
    assert_function_catalog(c)
    sql(c, 'SAVEPOINT overload_probe')
    sql(c, "CREATE FUNCTION v99_core.v99_core_start(integer) RETURNS integer LANGUAGE sql AS $$ SELECT $1 $$")
    try:
        assert_function_catalog(c)
    except AssertionError as exc:
        assert 'function ABI drift' in str(exc)
    else:
        raise AssertionError('same-name overload escaped fixed ABI allowlist')
    sql(c, 'ROLLBACK TO SAVEPOINT overload_probe')
    sql(c, 'RELEASE SAVEPOINT overload_probe')
    indexes = sql(c, "SELECT array_agg(relname ORDER BY relname) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='v99_core' AND c.relkind='i'")
    assert set(indexes) == {'v99_core_effects_claimed','v99_core_effects_human','v99_core_effects_pk','v99_core_effects_primary','v99_core_effects_run_id','v99_core_effects_run_key','v99_core_epochs_open','v99_core_epochs_pk','v99_core_epochs_run_id','v99_core_epochs_run_ordinal','v99_core_events_closed','v99_core_events_id','v99_core_events_pk','v99_core_meta_pk','v99_core_operations_pk','v99_core_operations_request_unique','v99_core_operations_run_attempt','v99_core_operations_run_id','v99_core_pins_pk','v99_core_requests_pk','v99_core_runs_pk','v99_core_snapshots_pk','v99_core_tools_pk','v99_core_wakes_cursor','v99_core_wakes_pk'}, indexes
    triggers = sql(c, "SELECT array_agg(t.tgname || ':' || cl.relname ORDER BY t.tgname,cl.relname) FROM pg_trigger t JOIN pg_class cl ON cl.oid=t.tgrelid JOIN pg_namespace n ON n.oid=cl.relnamespace WHERE n.nspname='v99_core' AND NOT t.tgisinternal")
    assert set(triggers) == {'v99_core_catalog_changed:core_tools','v99_core_effect_binding:core_effects','v99_core_events_immutable:core_events','v99_core_operation_binding:core_operations','v99_core_pin_binding:core_effect_pins','v99_core_pins_immutable:core_effect_pins','v99_core_requests_immutable:core_requests'}, triggers
    drift = sql(c, "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='v99_core' AND (p.proowner <> (SELECT oid FROM pg_roles WHERE rolname='postgres') OR (p.prosecdef AND NOT ('search_path=pg_catalog, v99_core'=ANY(coalesce(p.proconfig,ARRAY[]::text[])) OR 'search_path=pg_catalog,v99_core'=ANY(coalesce(p.proconfig,ARRAY[]::text[])))) OR EXISTS (SELECT 1 FROM aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a WHERE a.grantee=0 AND a.privilege_type='EXECUTE'))")
    assert drift == 0, drift
    default_acl = sql(c, "SELECT coalesce(array_agg(DISTINCT a.privilege_type ORDER BY a.privilege_type),'{}') FROM pg_default_acl d JOIN pg_namespace n ON n.oid=d.defaclnamespace CROSS JOIN LATERAL aclexplode(d.defaclacl) a WHERE n.nspname='v99_core' AND a.grantee=0")
    assert default_acl == [], default_acl
    assert sql(c, "SELECT has_schema_privilege('v99_core_operator','v99_core','CREATE') OR has_table_privilege('v99_core_operator','v99_core.core_runs','SELECT')") is False
    assert not any('lease_owner' in x or 'lease_until' in x for x in sql(c, "SELECT array_agg(column_name) FROM information_schema.columns WHERE table_schema='v99_core' AND table_name='core_effects'"))
    c.commit()
    print('[W5 guards/catalog] forbidden import positive/negative, AF_UNIX-only negative probe, exact table/function namespace, no effect lease')


def test_w5_utf8_limit(db):
    c = db.connect()
    started = good(ce_start(c, 'exact JSONB UTF8 size', 'size-start'))
    run, op = started['run_id'], started['execution_operation_id']
    lease = good(call(c, 'driver_acquire', run, 'size-driver', 60000))
    token = good(call(c, 'claim_effect', run, op, 'size-driver', lease['driver_fence']))
    def payload(text):
        return ce_receipt(token, {'schema_version':1,'text':text,'ce_status':'completed'})
    # Find a valid JSON string whose normalized JSONB text is exactly 1 MiB,
    # with a multi-byte prefix exercising a UTF-8 boundary.
    lo, hi = 0, 1048576
    while lo < hi:
        mid = (lo + hi + 1) // 2
        size = sql(c, 'SELECT octet_length(%s::jsonb::text)', (Json(payload('界' + 'x' * mid)),))
        if size <= 1048576: lo = mid
        else: hi = mid - 1
    value = payload('界' + 'x' * lo)
    exact = sql(c, 'SELECT octet_length(%s::jsonb::text)', (Json(value),))
    assert exact == 1048576, exact
    good(call(c, 'accept_receipt', op, 'ce:'+op+':receipt', 'size-driver', lease['driver_fence'], value))
    c.commit()
    print('[W5 UTF8] exact 1 MiB normalized JSONB receipt accepted at multibyte boundary')


def test_w5_concurrent_requests(db):
    barrier = Barrier(2)
    def start_once():
        conn = db.connect('operator')
        barrier.wait(timeout=3)
        result = call(conn, 'start', None, 'same concurrent request', 'same-concurrent-id')
        conn.commit()
        conn.close()
        return result
    with ThreadPoolExecutor(2) as pool:
        left = pool.submit(start_once); right = pool.submit(start_once)
        a, b = left.result(timeout=8), right.result(timeout=8)
    assert a == b and a['ok'] is True
    conn = db.connect('service'); run = a['run_id']
    lease = good(call(conn, 'driver_acquire', run, 'race-driver', 60000)); conn.commit()
    # Two human responses race for one interaction. Exactly one consumes it.
    token = good(call(conn, 'claim_effect', run, a['execution_operation_id'], 'race-driver', lease['driver_fence']))
    interaction = {'id':str(uuid.uuid4()),'kind':'question','channel':'human'}
    good(ce_accept(conn, token, ce_receipt(token, {'schema_version':1,'text':'question','ce_status':'waiting_for_input','interaction':interaction}), 'race-driver'))
    conn.commit()
    def answer(request):
        c = db.connect('operator'); barrier.wait(timeout=3)
        value = call(c, 'respond', None, run, interaction['id'], {'schema_version':1,'response':'yes'}, request)
        c.commit(); c.close(); return value
    with ThreadPoolExecutor(2) as pool:
        x = pool.submit(answer, 'answer-race-x'); y = pool.submit(answer, 'answer-race-y')
        replies = [x.result(timeout=8), y.result(timeout=8)]
    assert sum(bool(reply['ok']) for reply in replies) == 1, replies
    assert sorted(reply.get('reason') for reply in replies if not reply['ok']) == ['interaction_mismatch']

    # Three different control verbs compete for a fresh interaction. A response
    # or instruction steer may consume it; cancel may then seal the run, but no
    # serialized ordering can settle the same human effect twice.
    race_operator = db.connect('operator')
    race_start = good(call(race_operator, 'start', None, 'three-way race', 'three-way-start'))
    race_run = race_start['run_id']
    race_operator.commit()
    lease = good(call(conn, 'driver_acquire', race_run, 'race-driver-2', 60000)); conn.commit()
    token = good(call(conn, 'claim_effect', race_run, race_start['execution_operation_id'], 'race-driver-2', lease['driver_fence']))
    race_interaction = {'id':str(uuid.uuid4()),'kind':'instruction','channel':'human'}
    good(ce_accept(conn, token, ce_receipt(token, {'schema_version':1,'text':'continue','ce_status':'waiting_for_input','interaction':race_interaction}), 'race-driver-2'))
    conn.commit()
    race_barrier = Barrier(3)
    def compete(verb):
        c = db.connect('operator'); race_barrier.wait(timeout=4)
        if verb == 'respond':
            value = call(c, verb, None, race_run, race_interaction['id'], {'schema_version':1,'response':'go'}, 'three-way-respond')
        elif verb == 'steer':
            value = call(c, verb, None, race_run, 'go', 'three-way-steer', 1)
        else:
            value = call(c, verb, None, race_run, 'three-way-cancel')
        c.commit(); c.close(); return value
    with ThreadPoolExecutor(3) as pool:
        futures = [pool.submit(compete, verb) for verb in ('respond','steer','cancel')]
        race_results = [future.result(timeout=10) for future in futures]
    consuming = [r for r in race_results[:2] if r['ok']]
    assert len(consuming) <= 1, race_results
    owner = db.connect('admin')
    assert sql(owner, 'SELECT interaction IS NULL FROM v99_core.core_runs WHERE run_id=%s', (race_run,))
    assert sql(owner, "SELECT count(*) FROM v99_core.core_events WHERE run_id=%s AND type='human/responded'", (race_run,)) <= 1
    assert sql(owner, "SELECT count(*) FROM v99_core.core_effects WHERE run_id=%s AND kind='human'", (race_run,)) == 1
    owner.commit()
    race_operator.close()
    print('[W5 concurrency] request replay, response pair and respond/steer/cancel consume at most once')


def run_w2():
    with setup_db() as db:
        for test in (test_cas_pin, test_lease_fifo, test_unknown_cancel, test_human_atomic, test_closeout_wake):
            test(db)
    print('[passed] W2 owner ledger assertions')


def run_w3():
    with setup_db() as db:
        for test in (test_w3_control_fifo, test_w3_respond_and_unknown, test_w3_tool_and_atomic_replay,
                     test_w3_validation, test_w3_instruction_and_old_tools):
            test(db)
    print('[passed] W3 CE/T2 assertions')


def run_full():
    # The guards remain installed from the first setup call through all Fake
    # workers and fixture cleanup. pgembed startup runs through the explicitly
    # allowed uv setup helper; the parent verifies its real Unix endpoint.
    with unix_only_socket_guard(), subprocess_guard(), server_helper_scope():
        review_checks.test_helper_lifecycle()
        # W2/W3 groups each retain their clean-database assumptions; W4/W5 share
        # one fresh fixture for the final host/catalog/concurrency matrix.
        run_w2()
        run_w3()
        with setup_db() as db:
            for test in (test_w4_acl, test_w5_fake_worker_and_wait, test_w5_catalog_and_guards,
                         test_w5_utf8_limit, test_w5_concurrent_requests):
                test(db)
            infrastructure_checks.run_checks(db, sys.modules[__name__])
            contract_checks.run_checks(db, sys.modules[__name__])
            review_checks.run_checks(db, sys.modules[__name__])
        infrastructure_checks.run_group_lifecycle_checks(sys.modules[__name__])
    print('[passed] complete W2/W3/W4/W5 Phase 0 gate')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--w2-only', action='store_true', help='run the incremental owner-level ledger assertions only')
    group.add_argument('--w3-only', action='store_true', help='run the incremental CE/T2 assertions only')
    args = parser.parse_args()
    if args.w2_only:
        run_w2()
    elif args.w3_only:
        run_w3()
    else:
        run_full()


if __name__ == '__main__':
    main()
