"""CDP5-D (W3): atomic event producer and five-mode execution closure.

Run with: uv run python v24/cordis/dp5/test_dispatch.py

The gate uses real command_install / command_reconcile / host claim+receipt
paths. Owner DML is limited to explicitly labelled fixtures for provider
release, forged planner deltas, rollback injection and the 512-scope closure
boundary. No network provider is constructed.
"""
from __future__ import annotations
import contextlib
import copy
import json
import sys
import threading
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dp2'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dp3'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dp4'))

import psycopg2  # noqa: E402
from psycopg2.extras import Json  # noqa: E402

from test_support import (Server, TestDB, query, api, env, snapshot, no_write,  # noqa: E402
                          function_defs, replace_function, reconcile_payload)
from test_activation import (declaration, install, commit_new, commit_child, p0,  # noqa: E402
                             child_call, one, rows)
from test_teardown import enter_closing, drain, p6_slot, applied  # noqa: E402
from dp4_support import claim, settle  # noqa: E402

HOST = dict(contract_version='host_v1', handler_digest='b' * 64,
            replay=dict(repeat=True, concurrent=True))
RUN = dict(contract_version='1', handler_digest='c' * 64,
           replay=dict(repeat=True, concurrent=True))
MODES = ('emit', 'parallel', 'serial', 'bail', 'waterfall')


def listener(listener_id, mode='emit', priority=0, exec=None, event='fiber.activated',
             filter=None, sync_reads=False):
    ex = dict(type='in_db', op='const', value={}) if exec is None else exec
    cv = 'in_db_v1' if ex['type'] == 'in_db' else 'host_v1'
    return dict(listener_id=listener_id, event=event, mode=mode, priority=priority,
                filter=filter, exec=ex, contract_version=cv, sync_reads=sync_reads)


def declaration_with(scope, owner, provides=(), listeners=None, contracts=None,
                     requires=(), policy=None):
    payload = declaration(mode='existing', existing=scope, owner=owner,
                          provides=list(provides), requires=list(requires))
    if listeners is not None:
        payload['manifest']['listeners'] = copy.deepcopy(listeners)
    if contracts:
        payload['contracts'].update(copy.deepcopy(contracts))
    payload['policy_ref'] = policy
    return payload


def activate(db, payload):
    fiber = uuid.UUID(payload['fiber_id'])
    parent, _, _ = p0(db, fiber, 0)
    parent, begun = commit_child(db, parent, reconcile_payload(fiber, 'advance', 1))
    assert begun.get('disposition') == 'committed', begun
    plan = one(db, 'SELECT v24_cordis.registration_plan(i) FROM v24_cordis.installs i '
                   'JOIN v24_cordis.fibers f ON f.install_id=i.id WHERE f.id=%s', (fiber,))
    left = len(plan)
    while left:
        parent, batch = commit_child(db, parent, reconcile_payload(fiber, 'advance', 1))
        assert batch.get('disposition') == 'committed', batch
        left -= min(32, left)
    parent, result = commit_child(db, parent, reconcile_payload(fiber, 'advance', 1))
    return result


def create(db, scope, owner, listeners=None, provides=(), contracts=None,
           requires=(), policy=None):
    payload = declaration_with(scope, owner, provides, listeners, contracts, requires, policy)
    effect, result, _ = commit_new(db, 'command_install', payload)
    assert result.get('disposition') == 'committed', result
    return payload, uuid.UUID(payload['fiber_id']), activate(db, payload)


def child_scope(db, parent, owner):
    payload = declaration(mode='child', parent=parent, owner=owner)
    effect, result, _ = commit_new(db, 'command_install', payload)
    assert result.get('disposition') == 'committed', result
    activate(db, payload)
    return uuid.UUID(payload['scope']['id'])


def fresh_scope(db, root):
    return child_scope(db, root['scope'], root['owner']), None


def settle_success(db, effect, value=None):
    c = claim(db, effect)
    assert c.get('disposition') == 'claimed', c
    result = settle(db, effect, {'kind': 'listener_call',
                                 'result': {'value': {} if value is None else value}}, c['claim'])
    assert result.get('disposition') == 'committed', result
    return result


def settle_failure(db, effect, code='listener_error'):
    c = claim(db, effect)
    assert c.get('disposition') == 'claimed', c
    return settle(db, effect, {'kind': 'listener_call', 'error': {'code': code}}, c['claim'], cls='failure')


def settle_unknown(db, effect):
    c = claim(db, effect)
    assert c.get('disposition') == 'claimed', c
    return settle(db, effect, {'kind': 'listener_call'}, c['claim'], cls='unknown')


def drain_ready(db, result):
    while result.get('ready_effects'):
        last = result
        for item in result['ready_effects']:
            last = settle_success(db, uuid.UUID(item['effect_id']))
        result = last
    return result


def dispatch_of(db, p4_effect):
    return one(db, "SELECT id FROM v24_cordis.effects WHERE parent_id=%s AND kind='dispatch' "
                   'ORDER BY ordinal', (p4_effect,))


def parent_result(db, dispatch):
    return one(db, "SELECT outcome->'body'->'result' FROM v24_cordis.effects WHERE id=%s", (dispatch,))


def children(db, dispatch):
    return rows(db, "SELECT ordinal,status,input->>'listener_id',outcome FROM v24_cordis.effects "
                    "WHERE parent_id=%s AND kind='listener_call' ORDER BY ordinal", (dispatch,))


def progress_events(db, dispatch):
    return rows(db, "SELECT payload FROM v24_cordis.events WHERE entity_type='effect' "
                    "AND entity_id=%s AND event_kind='dispatch_progress' ORDER BY seq", (dispatch,))


def root_fixture(db):
    payload, _, _ = install(db)
    fiber = uuid.UUID(payload['fiber_id'])
    result = activate(db, payload)
    assert result.get('disposition') == 'committed', result
    episode = one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s', (fiber,))
    return dict(payload=payload, fiber=fiber, scope=uuid.UUID(payload['scope']['id']),
                owner=dict(fiber_id=str(fiber), episode_id=str(episode)))


def test_d1_emit(db, root):
    scope, _ = fresh_scope(db, root)
    provider, pf, pr = create(db, scope, root['owner'],
                              listeners=[listener('d1p', 'emit', 10,
                                                  {'type': 'host', 'capability': 'listener_call'})],
                              contracts={'listener_call': HOST})
    drain_ready(db, pr)
    source, sf, sr = create(db, scope, root['owner'],
                            listeners=[listener('d1s', 'emit', 0,
                                                {'type': 'in_db', 'op': 'const', 'value': {'x': 1}})])
    # emitted[0] is the dispatch; emitted[1] is the ready provider child
    dispatch = one(db, "SELECT id FROM v24_cordis.effects WHERE kind='dispatch' AND fiber_id=%s", (sf,))
    result = parent_result(db, dispatch)
    assert result == {'v': 1, 'mode': 'emit', 'generated': ['d1p', 'd1s']}, result
    assert set(result) == {'v', 'mode', 'generated'}
    before = parent_result(db, dispatch)
    assert len(sr['ready_effects']) == 1, sr
    child = uuid.UUID(sr['ready_effects'][0]['effect_id'])
    assert child in {uuid.UUID(x) for x in sr['emitted']}
    # Source closes independently; the provider-host child keeps its own fence.
    control = enter_closing(db, sf)
    source_drain = drain(db, sf, control)
    assert one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s', (sf,)) is None
    control = enter_closing(db, pf)
    plan = one(db, 'SELECT v24_cordis.p6_plan(NULL,%s)', (pf,))
    assert plan.get('kind') == 'deferred', plan
    receipt = settle_success(db, child)
    assert receipt['emitted'] == [] and receipt['ready_effects'] == [], receipt
    assert parent_result(db, dispatch) == before
    assert one(db, "SELECT count(*) FROM v24_cordis.effects WHERE id=%s AND status='succeeded'",
               (child,)) == 1
    drain(db, pf, control)
    print('[CDP5-D1] emit generated all children, in_db ran in-advance, host stayed ready; '
          'source closed while the provider-owned child remained fenced; parent never changed')


def test_d2_parallel(db, root):
    scope, _ = fresh_scope(db, root)
    providers = []
    for i in range(3):
        _, fiber, result = create(db, scope, root['owner'],
                                  listeners=[listener(f'd2p{i}', 'parallel',
                                                      10 - i, {'type': 'host', 'capability': 'listener_call'})],
                                  contracts={'listener_call': HOST})
        drain_ready(db, result)
        providers.append(fiber)
    _, sf, sr = create(db, scope, root['owner'])
    dispatch = one(db, "SELECT id FROM v24_cordis.effects WHERE kind='dispatch' AND fiber_id=%s", (sf,))
    assert len(sr['ready_effects']) == 3, sr
    claimed = [(uuid.UUID(x['effect_id']), claim(db, uuid.UUID(x['effect_id']))) for x in sr['ready_effects']]
    for effect, c in claimed[:-1]:
        assert c['disposition'] == 'claimed', c
    receipts = []
    for effect, c in claimed[:-1]:
        ordinal = one(db, 'SELECT ordinal FROM v24_cordis.effects WHERE id=%s', (effect,))
        receipts.append(settle(db, effect, {'kind': 'listener_call',
                                            'result': {'value': {'i': ordinal}}}, c['claim']))
    assert parent_result(db, dispatch) is None
    last, last_claim = claimed[-1]
    last_ordinal = one(db, 'SELECT ordinal FROM v24_cordis.effects WHERE id=%s', (last,))
    barrier = threading.Barrier(2)
    raced = []

    def race():
        with contextlib.closing(db.connect('service')) as conn:
            barrier.wait()
            raced.append(api(conn, last, env('success', {'kind': 'listener_call',
                                                         'result': {'value': {'i': last_ordinal}}}, last_claim['claim'])))
            conn.commit()
    threads = [threading.Thread(target=race) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(x['disposition'] for x in raced) == ['committed', 'replay'], raced
    result = parent_result(db, dispatch)
    assert result['joined'] == 3 and result['called'] == ['d2p0', 'd2p1', 'd2p2'], result
    assert result['acc'] == [{'i': 0}, {'i': 1}, {'i': 2}], result
    assert result['bailed'] is False
    assert len(progress_events(db, dispatch)) == 3
    assert one(db, "SELECT count(*) FROM v24_cordis.effects WHERE id=%s AND status='succeeded'",
               (dispatch,)) == 1
    print('[CDP5-D2] parallel out-of-order receipts, concurrent last-receipt race, one seal; '
          'acc/joined/called match the ordinal fold and the virtual current receipt counted once')


def test_d3_serial(db, root):
    scope, _ = fresh_scope(db, root)
    # First success bail stops the chain.
    _, sf, sr = create(db, scope, root['owner'], listeners=[
        listener('d3a1', 'serial', 20, {'type': 'host', 'capability': 'listener_call'}),
        listener('d3a2', 'serial', 10, {'type': 'in_db', 'op': 'const', 'value': {'no': 1}}),
        listener('d3a3', 'serial', 0, {'type': 'host', 'capability': 'listener_call'})],
        contracts={'listener_call': HOST})
    dispatch = one(db, "SELECT id FROM v24_cordis.effects WHERE kind='dispatch' AND fiber_id=%s", (sf,))
    assert len(sr['ready_effects']) == 1, sr
    first = uuid.UUID(sr['ready_effects'][0]['effect_id'])
    settle_success(db, first, {'bail': True, 'hit': 1})
    result = parent_result(db, dispatch)
    assert result == {'v': 1, 'mode': 'serial', 'acc': [{'bail': True, 'hit': 1}], 'joined': 1,
                      'called': ['d3a1'], 'bailed': True}, result
    assert len(children(db, dispatch)) == 1

    # String true is not the JSON boolean predicate; the next in_db/host chain runs.
    scope, _ = fresh_scope(db, root)
    _, sf, sr = create(db, scope, root['owner'], listeners=[
        listener('d3b1', 'serial', 20, {'type': 'host', 'capability': 'listener_call'}),
        listener('d3b2', 'serial', 10, {'type': 'in_db', 'op': 'const', 'value': {'b': 2}}),
        listener('d3b3', 'serial', 0, {'type': 'host', 'capability': 'listener_call'})],
        contracts={'listener_call': HOST})
    dispatch = one(db, "SELECT id FROM v24_cordis.effects WHERE kind='dispatch' AND fiber_id=%s", (sf,))
    first = uuid.UUID(sr['ready_effects'][0]['effect_id'])
    second = settle_success(db, first, {'bail': 'true'})
    assert len(second['ready_effects']) == 1, second
    third = uuid.UUID(second['ready_effects'][0]['effect_id'])
    settle_success(db, third, {'b': 3})
    result = parent_result(db, dispatch)
    assert result['called'] == ['d3b1', 'd3b2', 'd3b3'] and result['joined'] == 3, result
    assert result['bailed'] is False and result['acc'] == [{'bail': 'true'}, {'b': 2}, {'b': 3}], result

    # A forged planner append with a skipped ordinal is rejected by the independent validator.
    scope, _ = fresh_scope(db, root)
    _, sf, sr = create(db, scope, root['owner'], listeners=[
        listener('d3c1', 'serial', 20, {'type': 'host', 'capability': 'listener_call'}),
        listener('d3c2', 'serial', 10, {'type': 'in_db', 'op': 'const', 'value': {}})],
        contracts={'listener_call': HOST})
    dispatch = one(db, "SELECT id FROM v24_cordis.effects WHERE kind='dispatch' AND fiber_id=%s", (sf,))
    effect = uuid.UUID(sr['ready_effects'][0]['effect_id'])
    c = claim(db, effect)
    forged = {'domain': [{'op': 'listener_append', 'dispatch_id': str(dispatch), 'ordinal': 5,
                          'input': {}}], 'receipt': {'status': 'succeeded'},
              'events': [], 'successors': []}
    original = function_defs(db)
    replace_function(db, '''CREATE OR REPLACE FUNCTION v24_cordis.event_delta(
     p_effect_id uuid,p_outcome jsonb) RETURNS jsonb
     LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
     BEGIN RETURN current_setting('cdp5d.delta')::jsonb; END $$;''')
    try:
        with contextlib.closing(db.connect('owner')) as owner:
            before = snapshot(owner); owner.rollback()
        with contextlib.closing(db.connect('service')) as conn:
            query(conn, 'SELECT set_config(%s,%s,false)', ('cdp5d.delta', json.dumps(forged)))
            got = api(conn, effect, env('success', {'kind': 'listener_call', 'result': {'value': {}}}, c['claim']))
            assert got.get('error', {}).get('code') == 'invalid_outcome', got
            conn.commit()
        with contextlib.closing(db.connect('owner')) as owner:
            assert snapshot(owner) == before
    finally:
        replace_function(db, original['event_delta'])
    print('[CDP5-D3] serial creates one active next; JSON true bails, string true does not; '
          'forged ordinal 5 is invalid_outcome with zero write')


def test_d3_unavailable(db, root):
    scope, _ = fresh_scope(db, root)
    _, pf, pr = create(db, scope, root['owner'], listeners=[
        listener('d3u-p', 'serial', 0, {'type': 'in_db', 'op': 'const', 'value': {'p': 1}})])
    drain_ready(db, pr)
    _, sf, sr = create(db, scope, root['owner'], listeners=[
        listener('d3u-s', 'serial', 10, {'type': 'host', 'capability': 'listener_call'})],
        contracts={'listener_call': HOST})
    dispatch = one(db, "SELECT id FROM v24_cordis.effects WHERE kind='dispatch' AND fiber_id=%s", (sf,))
    first = uuid.UUID(sr['ready_effects'][0]['effect_id'])
    control = enter_closing(db, pf)
    drain(db, pf, control)
    assert one(db, "SELECT released_at IS NOT NULL FROM v24_cordis.contributions "
                   "WHERE fiber_id=%s AND kind='listener'", (pf,)) is True
    receipt = settle_success(db, first, {'s': 1})
    result = parent_result(db, dispatch)
    assert result['called'] == ['d3u-s'] and result['joined'] == 2, result
    assert result['acc'][1] == {'error': {'code': 'listener_unavailable'}}, result
    child = children(db, dispatch)
    assert child[1][1:3] == ('failed', 'd3u-p'), child
    print('[CDP5-D3b] a not-yet-created serial snapshot item whose provider is released '
          'becomes a trusted listener_unavailable failure, without rebinding or host call')


def test_d4_bail(db, root):
    scope, _ = fresh_scope(db, root)
    def run(name, value, expect_bail, expect_acc):
        local, _ = fresh_scope(db, root)
        _, sf, sr = create(db, local, root['owner'], listeners=[
            listener(name + '1', 'bail', 20, {'type': 'host', 'capability': 'listener_call'}),
            listener(name + '2', 'bail', 10, {'type': 'in_db', 'op': 'const', 'value': {'second': 2}})],
            contracts={'listener_call': HOST})
        dispatch = one(db, "SELECT id FROM v24_cordis.effects WHERE kind='dispatch' AND fiber_id=%s", (sf,))
        first = uuid.UUID(sr['ready_effects'][0]['effect_id'])
        settle_success(db, first, value)
        result = parent_result(db, dispatch)
        assert result['bailed'] is expect_bail, result
        assert result['acc'] == expect_acc, result
        assert result['called'] == [name + '1'] if expect_bail else result['called'] == [name + '1', name + '2']
        return result
    run('d4a', {'bail': True, 'v': 1}, True, {'bail': True, 'v': 1})
    run('d4b', {'bail': False}, False, None)
    # Failure does not short-circuit.
    scope, _ = fresh_scope(db, root)
    _, sf, sr = create(db, scope, root['owner'], listeners=[
        listener('d4c1', 'bail', 20, {'type': 'host', 'capability': 'listener_call'}),
        listener('d4c2', 'bail', 10, {'type': 'in_db', 'op': 'const', 'value': {'second': 2}})],
        contracts={'listener_call': HOST})
    dispatch = one(db, "SELECT id FROM v24_cordis.effects WHERE kind='dispatch' AND fiber_id=%s", (sf,))
    settle_failure(db, uuid.UUID(sr['ready_effects'][0]['effect_id']), 'boom')
    result = parent_result(db, dispatch)
    assert result['bailed'] is False and result['called'] == ['d4c1', 'd4c2'], result
    print('[CDP5-D4] bail returns the first hit value, null without a hit, and does not '
          'short-circuit on failure or a non-boolean bail field')


def test_d5_waterfall(db, root):
    scope, _ = fresh_scope(db, root)
    def chain(name, listeners, expected_acc):
        local, _ = fresh_scope(db, root)
        _, sf, sr = create(db, local, root['owner'], listeners=listeners)
        dispatch = one(db, "SELECT id FROM v24_cordis.effects WHERE kind='dispatch' AND fiber_id=%s", (sf,))
        result = parent_result(db, dispatch)
        assert result['acc'] == expected_acc, (name, result)
        return result, children(db, dispatch)
    listeners = [listener('d5a1', 'waterfall', 30, {'type': 'in_db', 'op': 'const', 'value': [1]}),
                 listener('d5a2', 'waterfall', 20, {'type': 'in_db', 'op': 'append', 'value': 2}),
                 listener('d5a3', 'waterfall', 10, {'type': 'in_db', 'op': 'acc'})]
    result, _ = chain('acc', listeners, [1, 2])
    assert result['called'] == ['d5a1', 'd5a2', 'd5a3']
    # Failure is carried as an error projection and the chain continues.
    listeners = [listener('d5b1', 'waterfall', 30, {'type': 'in_db', 'op': 'const', 'value': [1]}),
                 listener('d5b2', 'waterfall', 20, {'type': 'in_db', 'op': 'fail', 'code': 'E1'}),
                 listener('d5b3', 'waterfall', 10, {'type': 'in_db', 'op': 'const', 'value': 'after'})]
    result, child = chain('fail', listeners, 'after')
    assert child[1][1] == 'failed', child
    # append on a non-array acc is a legal internal failure.
    listeners = [listener('d5c1', 'waterfall', 30, {'type': 'in_db', 'op': 'append', 'value': 2}),
                 listener('d5c2', 'waterfall', 20, {'type': 'in_db', 'op': 'const', 'value': 'x'})]
    result, child = chain('invalid', listeners, 'x')
    assert child[0][3]['body'] == {'kind': 'listener_call', 'error': {'code': 'invalid_acc'}}, child
    print('[CDP5-D5] waterfall folds params/const/append/acc and carries failure/invalid_acc '
          'as the next acc; no synchronous next control is claimed')


def test_d6_tamper(db, root):
    scope, _ = fresh_scope(db, root)
    _, sf, sr = create(db, scope, root['owner'], listeners=[
        listener('d6h', 'parallel', 10, {'type': 'host', 'capability': 'listener_call'})],
        contracts={'listener_call': HOST})
    dispatch = one(db, "SELECT id FROM v24_cordis.effects WHERE kind='dispatch' AND fiber_id=%s", (sf,))
    child = uuid.UUID(sr['ready_effects'][0]['effect_id'])
    # External dispatch settlement is unauthorized.
    with contextlib.closing(db.connect('service')) as conn:
        token = dict(attempt=1, fence=1, owner=db.roles['service'])
        no_write(db, conn, dispatch, env('success', {'kind': 'dispatch', 'result': {}}, token),
                 code='unauthorized')
    # Internal in_db settlement is unauthorized.
    scope, _ = fresh_scope(db, root)
    _, isf, isr = create(db, scope, root['owner'], listeners=[
        listener('d6i', 'parallel', 10, {'type': 'in_db', 'op': 'const', 'value': {}})])
    isdispatch = one(db, "SELECT id FROM v24_cordis.effects WHERE kind='dispatch' AND fiber_id=%s", (isf,))
    ichild = one(db, "SELECT id FROM v24_cordis.effects WHERE parent_id=%s AND kind='listener_call'", (isdispatch,))
    with contextlib.closing(db.connect('service')) as conn:
        no_write(db, conn, ichild, env('success', {'kind': 'listener_call', 'result': {'value': {}}},
                                       dict(attempt=0, fence=0, owner=db.roles['service'])),
                 code='unauthorized')
    # Forged receipt body is invalid_outcome with zero write.
    c = claim(db, child)
    with contextlib.closing(db.connect('service')) as conn:
        no_write(db, conn, child, env('success', {'kind': 'listener_call', 'result': {}}, c['claim']),
                 code='invalid_outcome')
    # Child id depends only on dispatch id and ordinal.
    assert child == one(db, 'SELECT v24_cordis.successor_effect_id(%s,%s,0,%s)',
                        (db.roles['service'], dispatch, 'listener_call'))
    # A forged provider release is a fixture; the created call then rejects with zero write.
    scope, _ = fresh_scope(db, root)
    _, pf, pr = create(db, scope, root['owner'], listeners=[
        listener('d6r', 'parallel', 10, {'type': 'host', 'capability': 'listener_call'})],
        contracts={'listener_call': HOST})
    drain_ready(db, pr)
    _, sf, sr = create(db, scope, root['owner'])
    dispatch = one(db, "SELECT id FROM v24_cordis.effects WHERE kind='dispatch' AND fiber_id=%s", (sf,))
    child = uuid.UUID(sr['ready_effects'][0]['effect_id'])
    c = claim(db, child)
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, 'UPDATE v24_cordis.contributions SET withdrawn_at=now(),released_at=now() '
                    "WHERE fiber_id=%s AND kind='listener'", (pf,))
        conn.commit()
    with contextlib.closing(db.connect('service')) as conn:
        no_write(db, conn, child, env('success', {'kind': 'listener_call', 'result': {'value': {}}},
                                      c['claim']), code='dependency_unresolved')
    print('[CDP5-D6] dispatch/in_db external settlement is unauthorized; forged receipt and '
          'released-provider drain are zero-write; child identity is dispatch+ordinal only')


def test_d7_unknown(db, root):
    scope, _ = fresh_scope(db, root)
    providers = []
    for i in range(2):
        _, pf, pr = create(db, scope, root['owner'], listeners=[
            listener(f'd7p{i}', 'parallel', 10 - i, {'type': 'host', 'capability': 'listener_call'})],
            contracts={'listener_call': HOST})
        drain_ready(db, pr)
        providers.append(pf)
    _, sf, sr = create(db, scope, root['owner'])
    dispatch = one(db, "SELECT id FROM v24_cordis.effects WHERE kind='dispatch' AND fiber_id=%s", (sf,))
    children_ids = [uuid.UUID(x['effect_id']) for x in sr['ready_effects']]
    first, second = children_ids
    before_events = len(progress_events(db, dispatch))
    first_claim = claim(db, first)
    replay = settle(db, first, {'kind': 'listener_call'}, first_claim['claim'], cls='unknown')
    assert replay['disposition'] == 'committed' and replay['emitted'] == [] and replay['ready_effects'] == [], replay
    assert one(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (first,)) == 'unknown'
    assert len(progress_events(db, dispatch)) == before_events
    assert one(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (dispatch,)) == 'ready'
    settle_success(db, second, {'ok': 1})
    assert one(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (dispatch,)) == 'ready'
    replay = settle(db, first, {'kind': 'listener_call'}, first_claim['claim'], cls='unknown')
    assert replay['disposition'] == 'replay' and replay['emitted'] == [] and replay['ready_effects'] == [], replay
    control = enter_closing(db, sf)
    assert one(db, 'SELECT v24_cordis.p6_plan(NULL,%s)', (sf,))['kind'] == 'blocked_unknown'
    unknown_provider = one(db, 'SELECT fiber_id FROM v24_cordis.effects WHERE id=%s', (first,))
    control = enter_closing(db, unknown_provider)
    assert one(db, 'SELECT v24_cordis.p6_plan(NULL,%s)', (unknown_provider,))['kind'] == 'blocked_unknown'
    print('[CDP5-D7] unknown is a legal receipt with no event/append/seal; ready siblings remain '
          'claimable, replay is empty, and source/provider P6 both report blocked_unknown')


def test_d8_replay_and_rollback(db, root):
    scope, _ = fresh_scope(db, root)
    # Keep the exact p4 command/effect/outcome so the command request cache can be replayed.
    payload = declaration_with(scope, root['owner'], listeners=[
        listener('d8h', 'parallel', 10, {'type': 'host', 'capability': 'listener_call'})],
        contracts={'listener_call': HOST})
    effect, result, _ = commit_new(db, 'command_install', payload)
    fiber = uuid.UUID(payload['fiber_id'])
    p0eff, _, _ = p0(db, fiber, 0)
    p1eff, begun = commit_child(db, p0eff, reconcile_payload(fiber, 'advance', 1))
    assert begun['disposition'] == 'committed'
    p2eff, registered = commit_child(db, p1eff, reconcile_payload(fiber, 'advance', 1))
    assert registered['disposition'] == 'committed'
    p4eff, p4outcome = child_call(db, p2eff, reconcile_payload(fiber, 'advance', 1))
    with contextlib.closing(db.connect('service')) as conn:
        first = api(conn, p4eff, p4outcome)
        conn.commit()
    assert first['disposition'] == 'committed' and first['emitted'] and first['ready_effects']
    child = uuid.UUID(first['ready_effects'][0]['effect_id'])
    before = one(db, 'SELECT count(*) FROM v24_cordis.requests')
    with contextlib.closing(db.connect('service')) as conn:
        replay = api(conn, p4eff, p4outcome)
        conn.commit()
    assert replay == first
    assert one(db, 'SELECT count(*) FROM v24_cordis.requests') == before
    c = claim(db, child)
    settled = settle(db, child, {'kind': 'listener_call', 'result': {'value': {'a': 1}}}, c['claim'])
    assert settled['disposition'] == 'committed' and settled['emitted'] == [] and settled['ready_effects'] == []
    replay = settle(db, child, {'kind': 'listener_call', 'result': {'value': {'a': 1}}}, c['claim'])
    assert replay['disposition'] == 'replay' and replay['emitted'] == [] and replay['ready_effects'] == [], replay
    # Inject a fault after the event phase; the whole advance must roll back, including the cache.
    scope, _ = fresh_scope(db, root)
    _, sf, sr = create(db, scope, root['owner'], listeners=[
        listener('d8r', 'parallel', 10, {'type': 'host', 'capability': 'listener_call'})],
        contracts={'listener_call': HOST})
    dispatch = one(db, "SELECT id FROM v24_cordis.effects WHERE kind='dispatch' AND fiber_id=%s", (sf,))
    victim = uuid.UUID(sr['ready_effects'][0]['effect_id'])
    c = claim(db, victim)
    original = function_defs(db)
    replace_function(db, '''CREATE OR REPLACE FUNCTION v24_cordis.event_apply_postconditions(p_delta jsonb)
     RETURNS void LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected' USING ERRCODE='U0003'; END $$;''')
    try:
        with contextlib.closing(db.connect('owner')) as owner:
            before = snapshot(owner); owner.rollback()
        with contextlib.closing(db.connect('service')) as conn:
            try:
                query(conn, 'SELECT v24_cordis.advance(%s,%s)',
                      (victim, Json(env('success', {'kind': 'listener_call',
                                                   'result': {'value': {}}}, c['claim']))))
            except psycopg2.Error as exc:
                assert exc.pgcode == 'U0003', (exc.pgcode, str(exc))
                conn.rollback()
            else:
                raise AssertionError('injected fault did not fire')
        with contextlib.closing(db.connect('owner')) as owner:
            assert snapshot(owner) == before
        assert one(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (victim,)) == 'claimed'
        assert one(db, 'SELECT count(*) FROM v24_cordis.requests WHERE effect_id=%s', (victim,)) == 0
    finally:
        replace_function(db, original['event_apply_postconditions'])
    print('[CDP5-D8] command replay is byte-identical with emitted/ready_effects; host replay '
          'has both arrays empty; a post-event fault rolls back rows, event and request cache')


def test_d9_emit_delayed(db, root):
    scope, _ = fresh_scope(db, root)
    _, pf, pr = create(db, scope, root['owner'], listeners=[
        listener('d9p', 'emit', 10, {'type': 'host', 'capability': 'listener_call'})],
        contracts={'listener_call': HOST})
    drain_ready(db, pr)
    _, sf, sr = create(db, scope, root['owner'])
    dispatch = one(db, "SELECT id FROM v24_cordis.effects WHERE kind='dispatch' AND fiber_id=%s", (sf,))
    result = parent_result(db, dispatch)
    assert set(result) == {'v', 'mode', 'generated'} and result['generated'] == ['d9p'], result
    child = uuid.UUID(sr['ready_effects'][0]['effect_id'])
    assert one(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (child,)) == 'ready'
    settle_success(db, child, {'late': 1})
    assert parent_result(db, dispatch) == result
    assert one(db, 'SELECT input->\'descriptor\'->\'sync_reads\' FROM v24_cordis.effects WHERE id=%s',
               (child,)) is False
    print('[CDP5-D9] emit generated does not mean called; a delayed host child is ready while '
          'the parent result stays byte-identical; sync_reads=false is a declaration only')


def test_d10_claim_drain(db, root):
    scope, _ = fresh_scope(db, root)
    _, pf, pr = create(db, scope, root['owner'], listeners=[
        listener('d10p', 'parallel', 10, {'type': 'host', 'capability': 'listener_call'})],
        contracts={'listener_call': HOST})
    drain_ready(db, pr)
    _, sf, sr = create(db, scope, root['owner'])
    dispatch = one(db, "SELECT id FROM v24_cordis.effects WHERE kind='dispatch' AND fiber_id=%s", (sf,))
    child = uuid.UUID(sr['ready_effects'][0]['effect_id'])
    c = claim(db, child)
    assert c['disposition'] == 'claimed' and set(c['execution']) == {'descriptor', 'descriptor_digest'}, c
    assert c['execution']['descriptor'] == c['input']['descriptor']
    assert c['execution']['descriptor_digest'] == c['input']['descriptor_digest']
    # A wrong token is stale_claim with no write; the correct token still settles afterwards.
    with contextlib.closing(db.connect('service')) as conn:
        bad = dict(c['claim']); bad['attempt'] -= 1
        no_write(db, conn, child, env('success', {'kind': 'listener_call', 'result': {'value': {}}}, bad),
                 code='stale_claim')
    # The provider closes while the created call drains with its frozen descriptor.
    control = enter_closing(db, pf)
    assert one(db, 'SELECT v24_cordis.p6_plan(NULL,%s)', (pf,))['kind'] == 'deferred'
    settled = settle(db, child, {'kind': 'listener_call', 'result': {'value': {'drained': 1}}}, c['claim'])
    assert settled['disposition'] == 'committed'
    drain(db, pf, control)
    assert one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s', (pf,)) is None
    assert one(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (dispatch,)) == 'succeeded'
    print('[CDP5-D10] claim COMMIT exposes execution descriptor/digest; wrong token is stale; '
          'the created host call drains after provider closing with the frozen snapshot')


def test_d11_scope_order(db, root):
    base, _ = fresh_scope(db, root)
    mid = child_scope(db, base, root['owner'])
    desc = child_scope(db, mid, root['owner'])
    sib = child_scope(db, base, root['owner'])
    # Two mid providers share priority/seq; the UUID tiebreak must be deterministic.
    mid_providers = []
    for i in range(2):
        _, pf, pr = create(db, mid, root['owner'], listeners=[
            listener(f'd11m{i}', 'emit', 5, {'type': 'in_db', 'op': 'const', 'value': {}})])
        drain_ready(db, pr); mid_providers.append(pf)
    _, rf, rr = create(db, base, root['owner'], listeners=[
        listener('d11r', 'emit', 5, {'type': 'in_db', 'op': 'const', 'value': {}})])
    drain_ready(db, rr)
    # Descendant and sibling listeners have higher priority but are out of route.
    for scope, lid in ((desc, 'd11d'), (sib, 'd11s')):
        create(db, scope, root['owner'], listeners=[
            listener(lid, 'emit', 99, {'type': 'in_db', 'op': 'const', 'value': {}})])
    _, sf, sr = create(db, mid, root['owner'], listeners=[
        listener('d11self', 'emit', 5, {'type': 'in_db', 'op': 'const', 'value': {}})])
    dispatch = one(db, "SELECT id FROM v24_cordis.effects WHERE kind='dispatch' AND fiber_id=%s", (sf,))
    snapshot_ids = [x['listener_id'] for x in one(db,
        'SELECT input->\'listeners\' FROM v24_cordis.effects WHERE id=%s', (dispatch,))]
    assert 'd11d' not in snapshot_ids and 'd11s' not in snapshot_ids, snapshot_ids
    assert set(snapshot_ids) == {'d11r', 'd11m0', 'd11m1', 'd11self'}, snapshot_ids
    expected = rows(db, """SELECT c.descriptor->>'listener_id' FROM v24_cordis.contributions c
     JOIN v24_cordis.fibers f ON f.id=c.fiber_id JOIN v24_cordis.episodes e ON e.id=c.episode_id
     WHERE c.kind='listener' AND c.withdrawn_at IS NULL AND c.released_at IS NULL
      AND f.scope_id=ANY(%s) AND e.closed_at IS NULL AND e.state='active'
     ORDER BY (c.descriptor->>'priority')::int DESC,c.seq,f.id,e.id,c.id""", ([base, mid],))
    expected = [x[0] for x in expected if x[0] in set(snapshot_ids)]
    assert snapshot_ids == expected, (snapshot_ids, expected)
    # No run_start: dispatch ordinal 0.
    assert one(db, "SELECT ordinal FROM v24_cordis.effects WHERE id=%s", (dispatch,)) == 0
    assert one(db, "SELECT count(*) FROM v24_cordis.effects WHERE parent_id=%s AND kind='run_start'",
               (one(db, 'SELECT parent_id FROM v24_cordis.effects WHERE id=%s', (dispatch,)),)) == 0
    print('[CDP5-D11] source/mid/root listeners are routed by the scope chain; descendant and '
          'sibling listeners are excluded; priority/seq/UUID ordering matches the independent SQL sort')


def test_d12_limits(db, root):
    scope, _ = fresh_scope(db, root)
    def activate_many(count):
        local, _ = fresh_scope(db, root)
        _, sf, sr = create(db, local, root['owner'],
                           listeners=[listener(f'd12-{count}-{i}', 'emit', 0,
                                               {'type': 'in_db', 'op': 'acc'})
                                      for i in range(count)])
        return sf, sr
    sf, sr = activate_many(15)
    dispatch = one(db, "SELECT id FROM v24_cordis.effects WHERE kind='dispatch' AND fiber_id=%s", (sf,))
    assert len(sr['emitted']) == 16, sr
    assert len(children(db, dispatch)) == 15
    sf, sr = activate_many(16)
    assert sr.get('error', {}).get('code') == 'invalid_outcome', sr
    assert one(db, "SELECT count(*) FROM v24_cordis.effects WHERE kind='dispatch' AND fiber_id=%s", (sf,)) == 0
    # A run_start consumes one of the same 16 created effects.
    model = declaration_with(root['scope'], root['owner'], provides=['model'])
    model['manifest']['provides'][0]['descriptor'] = {'capability': 'model_call'}
    model['contracts'] = {'model_call': RUN}
    effect, result, _ = commit_new(db, 'command_install', model)
    assert result['disposition'] == 'committed', result
    activate(db, model)
    def run_source(count):
        local, _ = fresh_scope(db, root)
        payload = declaration_with(local, root['owner'], requires=['model'], policy='chat_tool',
                                   contracts={'run_start': RUN},
                                   listeners=[listener(f'd12r-{count}-{i}', 'emit', 0,
                                                       {'type': 'in_db', 'op': 'acc'})
                                              for i in range(count)])
        effect, result, _ = commit_new(db, 'command_install', payload)
        assert result['disposition'] == 'committed', result
        return uuid.UUID(payload['fiber_id']), activate(db, payload)
    sf, sr = run_source(14)
    assert 'emitted' in sr, sr
    assert len(sr['emitted']) == 16, sr
    dispatch = one(db, "SELECT id FROM v24_cordis.effects WHERE kind='dispatch' AND fiber_id=%s", (sf,))
    assert one(db, "SELECT ordinal FROM v24_cordis.effects WHERE id=%s", (dispatch,)) == 1
    _, sr = run_source(15)
    assert sr.get('error', {}).get('code') == 'invalid_outcome', sr
    # Closure boundary: 512 distinct scope targets pass, 513 refuses, before any dispatch write.
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        ids = [uuid.uuid4() for _ in range(513)]
        for i in ids:
            query(conn, 'INSERT INTO v24_cordis.scopes(id) VALUES(%s)', (i,))
        conn.commit()
    seed = lambda n: [dict(t='scopes', id=str(x)) for x in ids[:n]]
    assert one(db, 'SELECT jsonb_array_length(v24_cordis.discover_closure(%s))', (Json(seed(512)),)) == 512
    assert one(db, 'SELECT v24_cordis.discover_closure(%s)', (Json(seed(513)),)) is None
    print('[CDP5-D12] 15 listeners+dispatch=16 passes, 16 rejects; run_start+14+dispatch=16 '
          'passes, run_start+15 rejects; discover_closure admits 512 and refuses 513')


def main():
    with Server() as server, TestDB(server) as db:
        root = root_fixture(db)
        test_d1_emit(db, root)
        test_d2_parallel(db, root)
        test_d3_serial(db, root)
        test_d3_unavailable(db, root)
        test_d4_bail(db, root)
        test_d5_waterfall(db, root)
        test_d6_tamper(db, root)
        test_d7_unknown(db, root)
        test_d8_replay_and_rollback(db, root)
        test_d9_emit_delayed(db, root)
        test_d10_claim_drain(db, root)
        test_d11_scope_order(db, root)
        test_d12_limits(db, root)
    print('[passed] CDP5-D (W3: D1-D12 atomic producer, five modes, host path, fences, limits)')


if __name__ == '__main__':
    main()
