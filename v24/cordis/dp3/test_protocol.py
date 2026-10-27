"""CDP3-P: command routing plus cumulative P0 and production P6 protocol evidence.

Run with: uv run python v24/cordis/dp3/test_protocol.py
The early barrier stand-in is a disposable replacement of command_barrier. It proves
private control routing, ten-table zero writes, and release of G after the caller
ends the transaction. W2 cumulatively proves production P0 controls; W3 adds a real
closing-episode P6 deferred request, its first commit after the barrier clears, and
byte-identical replay. The stand-in probe is still not production P6 evidence.
"""
from __future__ import annotations
import contextlib
import uuid
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dp2'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dp1'))

from psycopg2.extras import Json
from test_support import (Server, TestDB, snapshot, query, api, command, env, no_write,
                          install_payload, reconcile_payload, sqlstate, function_defs,
                          replace_function, seed_fiber, seed_episode, seed_parent, seed_child,
                          active_owner)

TAGS = ('control', 'idle', 'begin', 'iterate', 'finish', 'divert', 'raise', 'leave',
        'inverse_batch', 'pin_release_batch', 'close', 'dispose_request', 'dispose_progress',
        'dispose_wait', 'dispose_finish')
DEFERRED_KEYS = {'v', 'disposition', 'effect_id', 'emitted', 'revision', 'claim'}


def scalar(db, statement, params=()):
    with contextlib.closing(db.connect('owner')) as owner:
        return query(owner, statement, params)[0][0]


def barrier_sql(disposition):
    return (
        "CREATE OR REPLACE FUNCTION v24_cordis.command_barrier"
        "(p_effect_id uuid,p_outcome jsonb,p_closure jsonb) RETURNS jsonb "
        "LANGUAGE plpgsql SET search_path=pg_catalog,v24_cordis,pg_temp AS $$ BEGIN "
        f"RETURN jsonb_build_object('disposition',{disposition!r}); END $$;"
    )


def admitted_install(db):
    """Ownerful install into the open root scope. A second ownerless root is invalid_args."""
    root = active_owner(db)
    return install_payload(mode='existing', existing_scope=root['scope'],
                           owner=dict(fiber_id=str(root['fiber']), episode_id=str(root['episode'])))


def body_for(key, payload):
    return dict(op='admit_and_apply', kind='command_reconcile', request_key=key,
                canonical_bytes='e30=', payload=payload)


def test_drift_split(db):
    fiber = seed_fiber(db, want_on=True, control_seq=1, prefix='p-gen')
    episode = seed_episode(db, fiber['fiber'], epoch=1, state='reloading', control_seq=1)
    payload = reconcile_payload(fiber['fiber'], 'advance', 0)
    parent, _ = seed_parent(db, 'command_reconcile', reconcile_payload(fiber['fiber'], 'on', 1),
                            actor='owner', fiber=fiber['fiber'])
    child, key = seed_child(db, parent, fiber['fiber'], payload, episode=episode, actor='owner')
    with contextlib.closing(db.connect('owner')) as conn:
        principal = query(conn, 'SELECT v24_cordis.principal_id(session_user)')[0][0]
        state = query(conn, 'SELECT v24_cordis.continuation_state(%s,%s,%s)',
                      (child, principal, Json(body_for(key, payload))))[0][0]
        forged = dict(body_for(key, payload))
        forged['payload'] = dict(payload, expected_control_seq=1)
        identity = query(conn, 'SELECT v24_cordis.continuation_state(%s,%s,%s)',
                         (child, principal, Json(forged)))[0][0]
        conn.rollback()
    assert state == {'class': 'control', 'reason': 'generation'}, state
    assert identity['code'] == 'effect_id_conflict' and identity['reason'] == 'continuation_identity', identity
    phase_fiber = seed_fiber(db, want_on=True, control_seq=1, prefix='p-phase')
    phase_ep = seed_episode(db, phase_fiber['fiber'], epoch=1, state='active', control_seq=1)
    phase_payload = reconcile_payload(phase_fiber['fiber'], 'advance', 1)
    phase_parent, _ = seed_parent(db, 'command_reconcile', reconcile_payload(phase_fiber['fiber'], 'on', 1),
                                  actor='owner', fiber=phase_fiber['fiber'])
    phase_child, phase_key = seed_child(db, phase_parent, phase_fiber['fiber'], phase_payload,
                                        episode=phase_ep, actor='owner')
    with contextlib.closing(db.connect('owner')) as conn:
        principal = query(conn, 'SELECT v24_cordis.principal_id(session_user)')[0][0]
        phase = query(conn, 'SELECT v24_cordis.continuation_state(%s,%s,%s)',
                      (phase_child, principal, Json(body_for(phase_key, phase_payload))))[0][0]
        conn.rollback()
    assert phase == {'class': 'control', 'reason': 'phase'}, phase
    target_fiber = seed_fiber(db, want_on=False, control_seq=1, prefix='p-target')
    target_ep = seed_episode(db, target_fiber['fiber'], epoch=1, state='reloading', control_seq=1)
    target_payload = reconcile_payload(target_fiber['fiber'], 'advance', 1)
    target_parent, _ = seed_parent(db, 'command_reconcile', reconcile_payload(target_fiber['fiber'], 'on', 1),
                                   actor='service', fiber=target_fiber['fiber'])
    target_child, target_key = seed_child(db, target_parent, target_fiber['fiber'], target_payload,
                                          episode=target_ep, actor='service')
    # The private continuation classifier is exercised through advance below;
    # direct helper EXECUTE is intentionally revoked from LOGIN roles.
    # Valid continuation target drift is classified by the lifecycle selector:
    # the old reloading episode is diverted and remains withdraw-free.
    with contextlib.closing(db.connect('service')) as conn:
        effect, outcome = command(db, conn, 'service', 'command_reconcile',
                                  target_payload, key=target_key, effect=target_child)
        result = api(conn, effect, outcome)
        assert result.get('disposition') == 'committed', (result, outcome)
        conn.commit()
    assert scalar(db, 'SELECT state FROM v24_cordis.episodes WHERE id=%s', (target_ep,)) == 'closing'
    assert scalar(db, 'SELECT outcome FROM v24_cordis.episodes WHERE id=%s', (target_ep,)) == 'divert'
    assert scalar(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE episode_id=%s AND withdrawn_at IS NOT NULL',
                  (target_ep,)) == 0
    stale = seed_fiber(db, want_on=True, control_seq=1, prefix='p-stale')
    stale_payload = reconcile_payload(stale['fiber'], 'advance', 0)
    stale_parent, _ = seed_parent(db, 'command_reconcile', reconcile_payload(stale['fiber'], 'on', 1),
                                  actor='owner', fiber=stale['fiber'])
    stale_child, stale_key = seed_child(db, stale_parent, stale['fiber'], stale_payload, actor='owner')
    with contextlib.closing(db.connect('owner')) as conn:
        principal = query(conn, 'SELECT v24_cordis.principal_id(session_user)')[0][0]
        stale_state = query(conn, 'SELECT v24_cordis.continuation_state(%s,%s,%s)',
                            (stale_child, principal, Json(body_for(stale_key, stale_payload))))[0][0]
        conn.rollback()
    assert stale_state == {'class': 'control', 'reason': 'generation'}, stale_state
    service = seed_fiber(db, want_on=True, control_seq=1, prefix='p-svc')
    service_ep = seed_episode(db, service['fiber'], epoch=1, state='reloading', control_seq=1)
    service_payload = reconcile_payload(service['fiber'], 'advance', 0)
    service_parent, _ = seed_parent(db, 'command_reconcile', reconcile_payload(service['fiber'], 'on', 1),
                                    fiber=service['fiber'])
    service_child, service_key = seed_child(db, service_parent, service['fiber'], service_payload,
                                            episode=service_ep)
    with contextlib.closing(db.connect('owner')) as owner:
        before = snapshot(owner)
        owner.rollback()
    with contextlib.closing(db.connect('service')) as conn:
        effect, outcome = command(db, conn, 'service', 'command_reconcile', service_payload,
                                  key=service_key, effect=service_child)
        result = api(conn, effect, outcome)
        assert result.get('disposition') == 'committed', result
        conn.commit()
    assert scalar(db, 'SELECT outcome FROM v24_cordis.episodes WHERE id=%s', (service_ep,)) == 'divert'
    assert scalar(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (service_child,)) == 'succeeded'
    print('[CDP3-P1] control drift is not effect_id_conflict; target drift diverts without withdrawal')


def test_preserved(db):
    fiber = seed_fiber(db, want_on=False, control_seq=0, prefix='p-slot')
    payload = reconcile_payload(fiber['fiber'], 'advance', 0)
    parent, _ = seed_parent(db, 'command_reconcile', reconcile_payload(fiber['fiber'], 'on', 0),
                            fiber=fiber['fiber'])
    child, key = seed_child(db, parent, fiber['fiber'], payload)
    stored = scalar(db, 'SELECT input FROM v24_cordis.effects WHERE id=%s', (child,))
    with contextlib.closing(db.connect('owner')) as owner:
        sqlstate(owner, 'UPDATE v24_cordis.effects SET input=%s WHERE id=%s',
                 (Json({'fiber_id': str(fiber['fiber']), 'action': 'advance', 'expected_control_seq': 9}),
                  child), code='55000')
    assert scalar(db, 'SELECT input FROM v24_cordis.effects WHERE id=%s', (child,)) == stored
    other_parent, _ = seed_parent(db, 'command_reconcile', reconcile_payload(fiber['fiber'], 'on', 0),
                                  fiber=fiber['fiber'])
    with contextlib.closing(db.connect('owner')) as owner:
        sqlstate(owner, "INSERT INTO v24_cordis.effects(id,parent_id,ordinal,fiber_id,kind,status,input,"
                        "request_actor) VALUES(%s,%s,0,%s,'command_reconcile','ready',%s,%s)",
                 (uuid.uuid4(), other_parent, fiber['fiber'], Json(payload), db.roles['service']),
                 code='23505')
    assert scalar(db, "SELECT count(*) FROM v24_cordis.effects WHERE fiber_id=%s AND kind='command_reconcile' "
                      "AND status IN ('ready','claimed')", (fiber['fiber'],)) == 1
    with contextlib.closing(db.connect('service')) as conn:
        on_payload = reconcile_payload(fiber['fiber'], 'on', 0)
        effect, outcome = command(db, conn, 'service', 'command_reconcile', on_payload)
        first = api(conn, effect, outcome)
        assert first.get('disposition') == 'committed', first
        conn.commit()
    assert scalar(db, 'SELECT control_seq FROM v24_cordis.fibers WHERE id=%s', (fiber['fiber'],)) == 1
    assert scalar(db, 'SELECT input FROM v24_cordis.effects WHERE id=%s', (child,)) == stored
    assert scalar(db, "SELECT count(*) FROM v24_cordis.effects WHERE fiber_id=%s AND kind='command_reconcile' "
                      "AND status IN ('ready','claimed')", (fiber['fiber'],)) == 1
    with contextlib.closing(db.connect('service')) as conn:
        off_payload = reconcile_payload(fiber['fiber'], 'off', 1)
        effect, outcome = command(db, conn, 'service', 'command_reconcile', off_payload)
        second = api(conn, effect, outcome)
        assert second.get('disposition') == 'committed', second
        conn.commit()
    assert scalar(db, 'SELECT want_on FROM v24_cordis.fibers WHERE id=%s', (fiber['fiber'],)) is False
    assert scalar(db, 'SELECT control_seq FROM v24_cordis.fibers WHERE id=%s', (fiber['fiber'],)) == 2
    assert scalar(db, 'SELECT input FROM v24_cordis.effects WHERE id=%s', (child,)) == stored
    assert scalar(db, 'SELECT input FROM v24_cordis.effects WHERE id=%s', (child,)) == stored
    with contextlib.closing(db.connect('operator')) as conn:
        effect, outcome = command(db, conn, 'operator', 'command_reconcile', payload,
                                  key=key, effect=child)
        no_write(db, conn, effect, outcome, code='effect_id_conflict')
    claimed = seed_fiber(db, prefix='p-claim')
    effect_id = uuid.uuid4()
    with contextlib.closing(db.connect('owner')) as owner:
        query(owner, "INSERT INTO v24_cordis.effects(id,fiber_id,kind,status,input,request_actor,"
                     "claim_owner,lease_until,attempt,fence) VALUES(%s,%s,'host_io','claimed',%s,%s,%s,"
                     "now()+interval '1 minute',1,1)",
              (effect_id, claimed['fiber'], Json({}), db.roles['service'], db.roles['service']))
        owner.commit()
    with contextlib.closing(db.connect('service')) as conn:
        no_write(db, conn, effect_id, env('claim', {'lease_ms': 1000}),
                 code='stale_claim', detail={'reason': 'claim_busy'})
    print('[CDP3-P2] ready input unchanged, I7 slot, same-LOGIN rejection, P0 coalescing, claim_busy')


def control_shape(db, disposition=None):
    payload = admitted_install(db)
    with contextlib.closing(db.connect('owner')) as owner:
        effect, outcome = command(db, owner, 'owner', 'command_install', payload)
        principal = query(owner, 'SELECT v24_cordis.principal_id(session_user)')[0][0]
        got = query(owner, 'SELECT v24_cordis.interpret_command(%s,%s,%s,%s)',
                    (effect, principal, Json(outcome), Json([])))[0][0]
        owner.rollback()
    assert set(got) == {'kind', 'step', 'barrier', 'context'}, got
    if disposition is None:
        assert got['kind'] == 'ready' and got['step'] == 'command_install' and got['barrier'] is None, got
        assert set(got['context']) == {'domain', 'receipt', 'events', 'successors'}, got
    else:
        assert got['kind'] == disposition and got['step'] is None and got['context'] is None, got
        assert got['barrier'] == {'disposition': disposition}, got
    return got


def replay_under(db, payload, key, effect, first, disposition):
    replace_function(db, barrier_sql(disposition))
    with contextlib.closing(db.connect('owner')) as owner:
        before = snapshot(owner)
        owner.rollback()
    with contextlib.closing(db.connect('service')) as conn:
        again, outcome = command(db, conn, 'service', 'command_install', payload, key=key, effect=effect)
        replay = api(conn, again, outcome)
        assert replay == first and again == effect, (disposition, replay)
        conn.commit()
    with contextlib.closing(db.connect('owner')) as owner:
        assert snapshot(owner) == before, disposition
        owner.rollback()
    assert scalar(db, 'SELECT count(*) FROM v24_cordis.requests WHERE effect_id=%s', (effect,)) == 1
    assert scalar(db, 'SELECT count(*) FROM v24_cordis.events WHERE effect_id=%s', (effect,)) == 1


def test_routing(db):
    original = function_defs(db)['command_barrier']
    try:
        control_shape(db)
        payload = admitted_install(db)
        with contextlib.closing(db.connect('service')) as conn:
            key = uuid.uuid4().hex
            effect, outcome = command(db, conn, 'service', 'command_install', payload, key=key)
            first = api(conn, effect, outcome)
            assert first.get('disposition') == 'committed', first
            conn.commit()
        # Replay-first is decided before the barrier. A non-ready barrier must not change it.
        for disposition in ('deferred', 'blocked_unknown'):
            replay_under(db, payload, key, effect, first, disposition)
        replace_function(db, barrier_sql('deferred'))
        control_shape(db, 'deferred')
        payload = admitted_install(db)
        with contextlib.closing(db.connect('owner')) as owner:
            before = snapshot(owner)
            owner.rollback()
        service = db.connect('service')
        watcher = db.connect('owner')
        try:
            effect, outcome = command(db, service, 'service', 'command_install', payload)
            result = api(service, effect, outcome)
            assert set(result) == DEFERRED_KEYS, result
            assert result['v'] == 1 and result['disposition'] == 'deferred', result
            assert result['effect_id'] == str(effect) and result['emitted'] == []
            assert result['revision'] == 0 and result['claim'] is None, result
            assert query(watcher, 'SELECT pg_try_advisory_xact_lock(24,1)')[0][0] is False
            assert snapshot(watcher) == before
            service.commit()
            assert query(watcher, 'SELECT pg_try_advisory_xact_lock(24,1)')[0][0] is True
        finally:
            service.rollback()
            watcher.rollback()
            service.close()
            watcher.close()
        with contextlib.closing(db.connect('owner')) as owner:
            assert snapshot(owner) == before
            owner.rollback()
        assert scalar(db, 'SELECT count(*) FROM v24_cordis.effects WHERE id=%s', (effect,)) == 0
        assert scalar(db, 'SELECT count(*) FROM v24_cordis.requests WHERE effect_id=%s', (effect,)) == 0
        assert scalar(db, 'SELECT count(*) FROM v24_cordis.events WHERE effect_id=%s', (effect,)) == 0
        assert scalar(db, 'SELECT count(*) FROM v24_cordis.effects WHERE parent_id=%s', (effect,)) == 0
        held = seed_fiber(db, want_on=True, control_seq=1, prefix='p-hold')
        held_payload = reconcile_payload(held['fiber'], 'advance', 1)
        held_parent, _ = seed_parent(db, 'command_reconcile', reconcile_payload(held['fiber'], 'on', 1),
                                     fiber=held['fiber'])
        held_child, held_key = seed_child(db, held_parent, held['fiber'], held_payload)
        held_input = scalar(db, 'SELECT input FROM v24_cordis.effects WHERE id=%s', (held_child,))
        with contextlib.closing(db.connect('service')) as conn:
            effect, outcome = command(db, conn, 'service', 'command_reconcile', held_payload,
                                      key=held_key, effect=held_child)
            result = no_write(db, conn, effect, outcome, disposition='deferred')
        assert set(result) == DEFERRED_KEYS and result['claim'] is None
        assert scalar(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (held_child,)) == 'ready'
        assert scalar(db, 'SELECT settled_at IS NULL AND outcome IS NULL FROM v24_cordis.effects WHERE id=%s',
                      (held_child,)) is True
        assert scalar(db, 'SELECT input FROM v24_cordis.effects WHERE id=%s', (held_child,)) == held_input
        assert scalar(db, 'SELECT count(*) FROM v24_cordis.requests WHERE effect_id=%s', (held_child,)) == 0
        assert scalar(db, 'SELECT count(*) FROM v24_cordis.events WHERE effect_id=%s', (held_child,)) == 0
        replace_function(db, barrier_sql('blocked_unknown'))
        control_shape(db, 'blocked_unknown')
        with contextlib.closing(db.connect('service')) as conn:
            effect, outcome = command(db, conn, 'service', 'command_install', admitted_install(db))
            no_write(db, conn, effect, outcome, code='blocked_unknown')
        replace_function(db, barrier_sql('unsupported'))
        with contextlib.closing(db.connect('owner')) as owner:
            before = snapshot(owner)
            owner.rollback()
        with contextlib.closing(db.connect('service')) as conn:
            effect, outcome = command(db, conn, 'service', 'command_install', admitted_install(db))
            sqlstate(conn, 'SELECT v24_cordis.advance(%s,%s)', (effect, Json(outcome)))
        with contextlib.closing(db.connect('owner')) as owner:
            assert snapshot(owner) == before
            owner.rollback()
    finally:
        replace_function(db, original)
    print('[CDP3-P3] non-production barrier routes deferred, blocked_unknown and unsupported; '
          'G is held until the caller commits; replay-first keeps the original response '
          'while the barrier is non-ready')


def test_layout(db):
    with contextlib.closing(db.connect('owner')) as owner:
        before = snapshot(owner)
        owner.rollback()
        got = query(owner, "SELECT v24_cordis.lifecycle_step(NULL,'{}'::jsonb,'[]'::jsonb)")[0][0]
        owner.rollback()
        assert snapshot(owner) == before
        advance = query(owner, "SELECT prosrc FROM pg_proc WHERE oid='v24_cordis.advance(uuid,jsonb)'::regprocedure")[0][0]
        command_src = query(owner, "SELECT prosrc FROM pg_proc WHERE oid="
                            "'v24_cordis.interpret_command(uuid,uuid,jsonb,jsonb)'::regprocedure")[0][0]
        definers = query(owner, "SELECT proname FROM pg_proc WHERE pronamespace='v24_cordis'::regnamespace "
                                "AND prosecdef")
        owner.rollback()
    assert set(got) == {'tag'} and got['tag'] in TAGS and got['tag'] == 'idle', got
    assert 'lifecycle_step' not in advance and 'lifecycle_step' not in command_src
    assert 'command_barrier' in command_src and 'barrier_ready' in advance
    assert [row[0] for row in definers] == ['advance']
    print('[CDP3-P4] lifecycle_step stays idle and unwired; only advance is SECURITY DEFINER')


def test_p0_truth_table(db):
    # On-on/off-off are fresh durable receipts without an event or second slot.
    f = seed_fiber(db, admitted=True, prefix='p0-table')
    def control(action, seq, expected_code=None):
        payload = reconcile_payload(f['fiber'], action, seq)
        with contextlib.closing(db.connect('service')) as conn:
            effect, outcome = command(db, conn, 'service', 'command_reconcile', payload)
            if expected_code:
                return no_write(db, conn, effect, outcome, code=expected_code)
            result = api(conn, effect, outcome)
            assert result.get('disposition') == 'committed', result
            conn.commit()
            assert api(conn, effect, outcome) == result
            conn.commit()
        assert scalar(db, 'SELECT count(*) FROM v24_cordis.requests WHERE effect_id=%s', (effect,)) == 1
        return effect, result
    for action in ('on', 'off', 'retry'):
        control(action, 9, 'stale_generation')
    control('retry', 0, 'stale_generation')
    noop, result = control('off', 0)
    assert result['emitted'] == []
    assert scalar(db, 'SELECT count(*) FROM v24_cordis.events WHERE effect_id=%s', (noop,)) == 0
    on, result = control('on', 0)
    assert len(result['emitted']) == 1
    slot = uuid.UUID(result['emitted'][0])
    frozen = scalar(db, 'SELECT to_jsonb(e) FROM v24_cordis.effects e WHERE id=%s', (slot,))
    noop, _ = control('on', 1)
    assert scalar(db, 'SELECT count(*) FROM v24_cordis.events WHERE effect_id=%s', (noop,)) == 0
    control('retry', 1, 'stale_generation')
    control('off', 1)
    control('off', 2)
    control('on', 2)
    assert scalar(db, 'SELECT to_jsonb(e) FROM v24_cordis.effects e WHERE id=%s', (slot,)) == frozen
    # A claimed slot is coalesced without changing its lease, actor or frozen input.
    with contextlib.closing(db.connect('owner')) as owner:
        query(owner, 'SELECT pg_advisory_xact_lock(24,1)')
        query(owner, "UPDATE v24_cordis.effects SET status='claimed',claim_owner=request_actor,"
                     "lease_until=now()+interval '1 minute',attempt=1,fence=1 WHERE id=%s", (slot,))
        owner.commit()
    frozen = scalar(db, 'SELECT to_jsonb(e) FROM v24_cordis.effects e WHERE id=%s', (slot,))
    ep = seed_episode(db, f['fiber'], state='reloading', control_seq=3)
    with contextlib.closing(db.connect('owner')) as owner:
        query(owner, 'SELECT pg_advisory_xact_lock(24,1)')
        query(owner, "UPDATE v24_cordis.episodes SET state='closing',outcome='error' WHERE id=%s", (ep,))
        query(owner, "UPDATE v24_cordis.fibers SET failure=v24_cordis.failure_v1(3,%s,'p2',"
                     "'provide_conflict','address_conflict','fixture') WHERE id=%s", (ep, f['fiber']))
        owner.commit()
    control('retry', 3)
    assert scalar(db, 'SELECT control_seq FROM v24_cordis.fibers WHERE id=%s', (f['fiber'],)) == 4
    assert scalar(db, "SELECT failure->>'control_seq' FROM v24_cordis.fibers WHERE id=%s", (f['fiber'],)) == '3'
    assert scalar(db, 'SELECT to_jsonb(e) FROM v24_cordis.effects e WHERE id=%s', (slot,)) == frozen
    assert scalar(db, 'SELECT count(*) FROM v24_cordis.effects WHERE fiber_id=%s AND '
                      "status IN ('ready','claimed') AND kind='command_reconcile'", (f['fiber'],)) == 1
    # Off remains admitted with a closed scope. On/retry do not reopen lineage.
    with contextlib.closing(db.connect('owner')) as owner:
        query(owner, 'SELECT pg_advisory_xact_lock(24,1)')
        query(owner, 'UPDATE v24_cordis.scopes SET closed_at=now() WHERE id=%s', (f['scope'],))
        owner.commit()
    control('off', 4)
    control('on', 5, 'scope_closed')
    control('retry', 5, 'scope_closed')
    # Exact bigint max permits no-op, refuses every required increment before DML.
    maxf = seed_fiber(db, admitted=True, want_on=False, control_seq=9223372036854775807, prefix='p0-max')
    for action in ('on', 'off', 'retry'):
        with contextlib.closing(db.connect('service')) as conn:
            effect, outcome = command(db, conn, 'service', 'command_reconcile',
                reconcile_payload(maxf['fiber'], action, 9223372036854775807))
            if action == 'on':
                no_write(db, conn, effect, outcome, code='budget_exceeded', detail={'reason': 'control_seq'})
            elif action == 'retry':
                no_write(db, conn, effect, outcome, code='stale_generation')
            else:
                assert api(conn, effect, outcome)['disposition'] == 'committed'
                conn.commit()
    maxon = seed_fiber(db, admitted=True, want_on=True, control_seq=9223372036854775807, prefix='p0-max-on')
    maxep = seed_episode(db, maxon['fiber'], state='closing', control_seq=9223372036854775807)
    for action in ('off', 'retry'):
        with contextlib.closing(db.connect('service')) as conn:
            effect, outcome = command(db, conn, 'service', 'command_reconcile',
                reconcile_payload(maxon['fiber'], action, 9223372036854775807))
            no_write(db, conn, effect, outcome, code='budget_exceeded', detail={'reason': 'control_seq'})
    # Off-off with an open old episode and no slot schedules once without a domain event.
    scheduled = seed_fiber(db, admitted=True, prefix='p0-schedule')
    seed_episode(db, scheduled['fiber'], state='reloading', control_seq=0)
    with contextlib.closing(db.connect('service')) as conn:
        effect, outcome = command(db, conn, 'service', 'command_reconcile',
                                  reconcile_payload(scheduled['fiber'], 'off', 0))
        result = api(conn, effect, outcome)
        assert result['disposition'] == 'committed' and len(result['emitted']) == 1, result
        conn.commit()
    assert scalar(db, 'SELECT count(*) FROM v24_cordis.events WHERE effect_id=%s', (effect,)) == 0
    assert scalar(db, 'SELECT control_seq FROM v24_cordis.fibers WHERE id=%s', (scheduled['fiber'],)) == 0
    # Terminal facts are owner fixtures; every direct control refuses without writes.
    for state, code in [('dispose_pending', 'owner_closing'), ('disposed', 'already_terminal')]:
        terminal = seed_fiber(db, admitted=True, prefix='p0-terminal')
        with contextlib.closing(db.connect('owner')) as owner:
            query(owner, 'SELECT pg_advisory_xact_lock(24,1)')
            query(owner, 'UPDATE v24_cordis.installs SET state=%s WHERE id=%s', (state, terminal['install']))
            owner.commit()
        for action in ('on', 'off', 'retry'):
            with contextlib.closing(db.connect('service')) as conn:
                effect, outcome = command(db, conn, 'service', 'command_reconcile',
                                          reconcile_payload(terminal['fiber'], action, 0))
                no_write(db, conn, effect, outcome, code=code)
    print('[CDP3-P5] production P0 truth table/CAS/no-op receipt/replay, ready+claimed coalescing, all increment overflows and terminal refusal')


def test_null_fence_progress(db):
    from test_activation import install, commit_new, child_call, finish
    root = active_owner(db)  # Existing owner fixture; child controls and activation use advance.
    for turn_on in (False, True):
        declaration, _, _ = install(db, mode='existing', existing=root['scope'],
                                     owner=dict(fiber_id=str(root['fiber']), episode_id=str(root['episode'])))
        fiber = declaration['fiber_id']
        parent, first, _ = commit_new(db, 'command_reconcile', reconcile_payload(fiber, 'on', 0))
        slot, old_outcome = child_call(db, parent, reconcile_payload(fiber, 'advance', 1))
        frozen = scalar(db, 'SELECT input FROM v24_cordis.effects WHERE id=%s', (slot,))
        commit_new(db, 'command_reconcile', reconcile_payload(fiber, 'off', 1))
        control = 2
        if turn_on:
            commit_new(db, 'command_reconcile', reconcile_payload(fiber, 'on', 2))
            control = 3
        with contextlib.closing(db.connect('service')) as conn:
            result = api(conn, slot, old_outcome)
            assert result.get('disposition') == 'committed' and result['emitted'] == [], result
            conn.commit()
            assert api(conn, slot, old_outcome) == result
            conn.commit()
        assert scalar(db, 'SELECT input FROM v24_cordis.effects WHERE id=%s', (slot,)) == frozen
        assert scalar(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (slot,)) == 'succeeded'
        assert scalar(db, 'SELECT count(*) FROM v24_cordis.events WHERE effect_id=%s', (slot,)) == 0
        assert scalar(db, 'SELECT count(*) FROM v24_cordis.episodes WHERE fiber_id=%s', (fiber,)) == 0
        assert scalar(db, 'SELECT control_seq FROM v24_cordis.fibers WHERE id=%s', (fiber,)) == control
        assert scalar(db, "SELECT count(*) FROM v24_cordis.effects WHERE fiber_id=%s AND status IN ('ready','claimed')",
                      (fiber,)) == 0
        # A new legal control cycle can now allocate the sole current-generation
        # slot. The obsolete input never begins or schedules another generation.
        if turn_on:
            off_parent, off_result, _ = commit_new(db, 'command_reconcile',
                                                   reconcile_payload(fiber, 'off', control))
            control += 1
            assert len(off_result['emitted']) == 1, off_result
            off_slot, off_outcome = child_call(db, off_parent, reconcile_payload(fiber, 'advance', control))
            with contextlib.closing(db.connect('service')) as conn:
                settled = api(conn, off_slot, off_outcome)
                assert settled.get('disposition') == 'committed' and settled['emitted'] == [], settled
                conn.commit()
            assert scalar(db, 'SELECT count(*) FROM v24_cordis.episodes WHERE fiber_id=%s', (fiber,)) == 0
        parent, result, _ = commit_new(db, 'command_reconcile', reconcile_payload(fiber, 'on', control))
        assert len(result['emitted']) == 1, (turn_on, control, result,
            scalar(db, 'SELECT row_to_json(f) FROM v24_cordis.fibers f WHERE id=%s', (fiber,)))
        finish(db, parent, fiber, 0, control + 1)
        assert scalar(db, 'SELECT count(*) FROM v24_cordis.episodes WHERE fiber_id=%s', (fiber,)) == 1
    print('[CDP3-P6] NULL-fence on/off and on/off/on settle obsolete slots as no-op; new legal controls reach active')


def test_p6_protocol(db):
    from test_activation import install, phases, commit_new, child_call, one
    root = active_owner(db)
    payload, _, _ = install(db, owner=dict(fiber_id=str(root['fiber']), episode_id=str(root['episode'])),
                            mode='existing', existing=root['scope'])
    fiber = uuid.UUID(payload['fiber_id'])
    phases(db, fiber, 0)
    control = 1
    off, result, _ = commit_new(db, 'command_reconcile', reconcile_payload(fiber, 'off', control))
    assert result.get('disposition') == 'committed' and result['emitted'], result
    slot, outcome = child_call(db, off, reconcile_payload(fiber, 'advance', control + 1))
    with contextlib.closing(db.connect('service')) as conn:
        assert api(conn, slot, outcome)['disposition'] == 'committed'
        conn.commit()
    control += 1
    # A fresh legal off control allocates the one P6 continuation slot for the closing episode.
    off, result, _ = commit_new(db, 'command_reconcile', reconcile_payload(fiber, 'off', control))
    assert result.get('disposition') == 'committed' and len(result['emitted']) == 1, result
    effect, outcome = child_call(db, off, reconcile_payload(fiber, 'advance', control))
    episode = one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s', (fiber,))
    run = uuid.uuid4()
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, 'INSERT INTO v24_cordis.runs(id,owner_fiber_id,owner_episode_id,scope_id,'
                    'spawn_key,remaining_steps) VALUES(%s,%s,%s,%s,%s,0)',
              (run, fiber, episode, root['scope'], 'p6-protocol-open'))
        conn.commit()
    with contextlib.closing(db.connect('owner')) as owner:
        before = snapshot(owner)
        owner.rollback()
    with contextlib.closing(db.connect('service')) as conn:
        deferred = no_write(db, conn, effect, outcome, disposition='deferred')
    assert set(deferred) == DEFERRED_KEYS and deferred['claim'] is None, deferred
    with contextlib.closing(db.connect('owner')) as owner:
        assert snapshot(owner) == before
        assert query(owner, 'SELECT pg_try_advisory_xact_lock(24,1)')[0][0] is True
        owner.rollback()
    assert scalar(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (effect,)) == 'ready'
    assert scalar(db, 'SELECT count(*) FROM v24_cordis.requests WHERE effect_id=%s', (effect,)) == 0
    assert scalar(db, 'SELECT count(*) FROM v24_cordis.events WHERE effect_id=%s', (effect,)) == 0
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, 'UPDATE v24_cordis.runs SET ended_at=clock_timestamp() WHERE id=%s', (run,))
        conn.commit()
    with contextlib.closing(db.connect('service')) as conn:
        committed = api(conn, effect, outcome)
        assert committed.get('disposition') == 'committed', committed
        conn.commit()
    with contextlib.closing(db.connect('owner')) as owner:
        after_commit = snapshot(owner)
        response_text = query(owner, 'SELECT response::text FROM v24_cordis.requests WHERE effect_id=%s',
                              (effect,))[0][0]
        owner.rollback()
    with contextlib.closing(db.connect('service')) as conn:
        replay = api(conn, effect, outcome)
        assert replay == committed, (replay, committed)
        conn.commit()
    with contextlib.closing(db.connect('owner')) as owner:
        assert snapshot(owner) == after_commit
        assert query(owner, 'SELECT response::text FROM v24_cordis.requests WHERE effect_id=%s',
                     (effect,))[0][0] == response_text
        assert query(owner, 'SELECT count(*) FROM v24_cordis.requests WHERE effect_id=%s',
                     (effect,))[0][0] == 1
        assert query(owner, 'SELECT count(*) FROM v24_cordis.events WHERE effect_id=%s',
                     (effect,))[0][0] == 1
        owner.rollback()
    assert scalar(db, "SELECT event_kind FROM v24_cordis.events WHERE effect_id=%s", (effect,)) == 'episode_closed'
    assert scalar(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (effect,)) == 'succeeded'
    print('[CDP3-P7] real P6 deferred is ten-table zero-write; the same request commits after the barrier clears and replays byte-identically')


def main():
    with Server() as server, TestDB(server) as db:
        test_layout(db)
        test_drift_split(db)
        test_preserved(db)
        test_p0_truth_table(db)
        test_null_fence_progress(db)
        test_p6_protocol(db)
        test_routing(db)
    print('[passed] CDP3-P')


if __name__ == '__main__':
    main()
