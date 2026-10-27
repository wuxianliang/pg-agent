"""CDP3-P: W1 command routing. This is not a production P6 gate.

Run with: uv run python v24/cordis/dp3/test_protocol.py
The barrier stand-in is a disposable replacement of command_barrier. It proves
private control routing, ten-table zero writes, and release of G after the caller
ends the transaction. off/on/retry transitions stay unimplemented.
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
                                   actor='owner', fiber=target_fiber['fiber'])
    target_child, target_key = seed_child(db, target_parent, target_fiber['fiber'], target_payload,
                                          episode=target_ep, actor='owner')
    with contextlib.closing(db.connect('owner')) as conn:
        principal = query(conn, 'SELECT v24_cordis.principal_id(session_user)')[0][0]
        target = query(conn, 'SELECT v24_cordis.continuation_state(%s,%s,%s)',
                       (target_child, principal, Json(body_for(target_key, target_payload))))[0][0]
        conn.rollback()
    assert target == {'class': 'control', 'reason': 'target'}, target
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
    assert stale_state['code'] == 'stale_generation', stale_state
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
        sqlstate(conn, 'SELECT v24_cordis.advance(%s,%s)', (effect, Json(outcome)))
    with contextlib.closing(db.connect('owner')) as owner:
        assert snapshot(owner) == before
        owner.rollback()
    assert scalar(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (service_child,)) == 'ready'
    print('[CDP3-P1] control drift is not effect_id_conflict; advance still fail-closes with zero writes')


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
    with contextlib.closing(db.connect('owner')) as owner:
        before = snapshot(owner)
        owner.rollback()
    with contextlib.closing(db.connect('service')) as conn:
        on_payload = reconcile_payload(fiber['fiber'], 'on', 0)
        effect, outcome = command(db, conn, 'service', 'command_reconcile', on_payload)
        sqlstate(conn, 'SELECT v24_cordis.advance(%s,%s)', (effect, Json(outcome)))
        off_payload = reconcile_payload(fiber['fiber'], 'off', 0)
        effect, outcome = command(db, conn, 'service', 'command_reconcile', off_payload)
        sqlstate(conn, 'SELECT v24_cordis.advance(%s,%s)', (effect, Json(outcome)))
    with contextlib.closing(db.connect('owner')) as owner:
        assert snapshot(owner) == before
        owner.rollback()
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
    print('[CDP3-P2] ready input unchanged, I7 slot, same-LOGIN rejection, off 0A000, claim_busy')


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


def main():
    with Server() as server, TestDB(server) as db:
        test_layout(db)
        test_drift_split(db)
        test_preserved(db)
        test_routing(db)
    print('[passed] CDP3-P')


if __name__ == '__main__':
    main()
