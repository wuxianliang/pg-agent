"""CDP3-D: W4 bounded dispose for real activated parent/child installs.

Production installs, activation, dispose requests, P5/P6 cleanup and fiber/install
tombstones all go through real `advance`. Owner DML is limited to explicit fixtures:
host_io/unknown effect barriers, an open run, and request-key forging probes.
It proves no W5/CDP3-B, DP4 settlement, DP5 dispatch, or DP6 external recovery.
"""
from __future__ import annotations
import contextlib
import uuid
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dp2'))

import psycopg2
from psycopg2.extras import Json

from test_support import (Server, TestDB, snapshot, query, api, command, no_write,
                          dispose_payload, reconcile_payload, successor_key, derive,
                          install_probe, set_probe, replace_function, function_defs,
                          delta, event)
from test_activation import (one, rows, install, phases, commit_new, child_call, expect_raise,
                             declaration)
from test_teardown import mutate, root_install, activate


def dispose_request(db, install_id):
    with contextlib.closing(db.connect('service')) as conn:
        effect, outcome = command(db, conn, 'service', 'command_dispose', dispose_payload(install_id))
        result = api(conn, effect, outcome)
        conn.commit()
    return effect, result, outcome


def effect_events(db, effect):
    return rows(db, "SELECT event_kind,payload FROM v24_cordis.events WHERE effect_id=%s ORDER BY seq",
                (effect,))


def ready_slots(db, install_id):
    return rows(db, 'SELECT x.id,x.parent_id,x.input FROM v24_cordis.effects x '
                    'JOIN v24_cordis.fibers f ON f.id=x.fiber_id '
                    'WHERE x.kind=%s AND x.status=%s '
                    'AND f.id IN (SELECT id FROM v24_cordis.dispose_subtree(%s)) ORDER BY x.id',
                ('command_reconcile', 'ready', install_id))


def advance_slot(db, effect, parent, payload):
    key = successor_key(parent)
    with contextlib.closing(db.connect('service')) as conn:
        _, outcome = command(db, conn, 'service', 'command_reconcile', payload, key=key, effect=effect)
        result = api(conn, effect, outcome)
        conn.commit()
    return result


def rank(db, install_id):
    with contextlib.closing(db.connect('owner')) as owner:
        row = query(owner, '''
WITH t AS (SELECT id,install_id FROM v24_cordis.dispose_subtree(%s)),
 sub AS (SELECT id FROM t), si AS (SELECT DISTINCT install_id FROM t)
SELECT
 (SELECT count(*) FROM v24_cordis.installs WHERE id IN (SELECT install_id FROM si) AND state='installed')
 +(SELECT count(*) FROM v24_cordis.installs WHERE id IN (SELECT install_id FROM si) AND state<>'disposed')
 +(SELECT count(*) FROM v24_cordis.fibers WHERE id IN (SELECT id FROM sub) AND dispose_requested_at IS NULL)
 +(SELECT count(*) FROM v24_cordis.fibers WHERE id IN (SELECT id FROM sub) AND disposed_at IS NULL)
 +(SELECT count(*) FROM v24_cordis.episodes WHERE fiber_id IN (SELECT id FROM sub)
   AND closed_at IS NULL AND state<>'closing')
 +(SELECT count(*) FROM v24_cordis.episodes WHERE fiber_id IN (SELECT id FROM sub) AND closed_at IS NULL)
 +(SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id IN (SELECT id FROM sub) AND released_at IS NULL)
 +(SELECT count(*) FROM v24_cordis.pins p WHERE p.released_at IS NULL AND (
   p.consumer_fiber_id IN (SELECT id FROM sub)
   OR p.contribution_id IN (SELECT id FROM v24_cordis.contributions WHERE fiber_id IN (SELECT id FROM sub)))),
 (SELECT count(*) FROM v24_cordis.fibers f WHERE f.id IN (SELECT id FROM sub)
   AND f.disposed_at IS NULL
   AND NOT EXISTS(SELECT 1 FROM v24_cordis.effects x WHERE x.fiber_id=f.id
     AND x.kind='command_reconcile' AND x.status IN ('ready','claimed'))
   AND (f.current_episode_id IS NOT NULL OR f.want_on
     OR EXISTS(SELECT 1 FROM v24_cordis.contributions c WHERE c.fiber_id=f.id AND c.released_at IS NULL)
     OR EXISTS(SELECT 1 FROM v24_cordis.pins p WHERE p.released_at IS NULL AND (
       p.consumer_fiber_id=f.id OR p.contribution_id IN (
        SELECT id FROM v24_cordis.contributions WHERE fiber_id=f.id)))
     OR EXISTS(SELECT 1 FROM v24_cordis.runs r WHERE r.owner_fiber_id=f.id AND r.ended_at IS NULL)
     OR EXISTS(SELECT 1 FROM v24_cordis.effects x WHERE x.fiber_id=f.id AND x.status IN ('ready','claimed'))))
''', (install_id,))[0]
        return int(row[0]), int(row[1])


def counts(db, install_id):
    with contextlib.closing(db.connect('owner')) as owner:
        return query(owner, '''
WITH t AS (SELECT id,install_id FROM v24_cordis.dispose_subtree(%s))
SELECT
 (SELECT count(*) FROM v24_cordis.fibers WHERE id IN (SELECT id FROM t) AND disposed_at IS NULL),
 (SELECT count(*) FROM v24_cordis.installs WHERE id IN (SELECT DISTINCT install_id FROM t) AND state<>'disposed'),
 (SELECT count(*) FROM v24_cordis.episodes WHERE fiber_id IN (SELECT id FROM t) AND closed_at IS NULL),
 (SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id IN (SELECT id FROM t) AND released_at IS NULL),
 (SELECT count(*) FROM v24_cordis.pins p WHERE p.released_at IS NULL AND (
   p.consumer_fiber_id IN (SELECT id FROM t)
   OR p.contribution_id IN (SELECT id FROM v24_cordis.contributions WHERE fiber_id IN (SELECT id FROM t))))
''', (install_id,))[0]


def tree_state(db, install_id):
    with contextlib.closing(db.connect('owner')) as owner:
        return query(owner, 'SELECT i.id,i.state FROM v24_cordis.installs i '
                            'WHERE i.id IN (SELECT DISTINCT install_id FROM v24_cordis.dispose_subtree(%s)) '
                            'ORDER BY i.id', (install_id,))


def drive(db, install_id, sealed=False):
    """Bounded rank driver: one productive object step per attempt, fuel-capped."""
    if not sealed:
        effect, result, outcome = dispose_request(db, install_id)
        events = effect_events(db, effect)
        assert result.get('disposition') == 'committed', result
        assert [(k, p.get('phase')) for k, p in events] == [
            ('install_dispose_progress', 'requested')], events
        # Replay-first: the original key only replays the first response.
        before_replay = len(rows(db, 'SELECT event_id FROM v24_cordis.events'))
        with contextlib.closing(db.connect('service')) as conn:
            replay = api(conn, effect, outcome)
            conn.commit()
        assert replay == result
        assert len(rows(db, 'SELECT event_id FROM v24_cordis.events')) == before_replay

    f, i, e, c, p = (int(x) for x in counts(db, install_id))
    fuel = 16 * (1 + f + i + e + c + p)
    attempts = 0
    coalesced = False
    m, u = rank(db, install_id)
    while True:
        states = tree_state(db, install_id)
        if all(state == 'disposed' for _, state in states):
            break
        assert attempts < fuel, ('fuel exhausted', attempts, fuel, states)
        slots = ready_slots(db, install_id)
        before_m, before_u = rank(db, install_id)
        if slots:
            slot, parent, payload = slots[0]
            result = advance_slot(db, slot, parent, payload)
            assert result.get('disposition') == 'committed', result
            effect = slot
        else:
            effect, result, outcome = dispose_request(db, install_id)
            assert result.get('disposition') == 'committed', result
        events = effect_events(db, effect)
        after_m, after_u = rank(db, install_id)
        attempts += 1
        if not events:
            assert (after_m, after_u) == (before_m, before_u), (before_m, before_u, after_m, after_u)
            continue
        kind, payload = events[0]
        if kind == 'install_dispose_progress' and payload.get('phase') == 'work_scheduled':
            assert after_m == before_m, (before_m, after_m, events)
            assert after_u < before_u, (before_u, after_u, events)
        else:
            assert after_m < before_m, ('no rank progress', before_m, after_m, events)
        if kind == 'install_dispose_progress' and payload.get('phase') in (
                'fiber_requested', 'work_scheduled'):
            # A fresh dispose request while the selected fiber already has a slot
            # coalesces to a no-op receipt with zero new events.
            if not coalesced:
                noop_effect, noop_result, _ = dispose_request(db, install_id)
                assert noop_result.get('disposition') == 'committed'
                assert noop_result['emitted'] == []
                assert effect_events(db, noop_effect) == []
                assert rank(db, install_id) == (after_m, after_u)
                coalesced = True
        if slots:
            continue
    assert attempts <= fuel, (attempts, fuel)
    return {'attempts': attempts, 'fuel': fuel}


def assert_tree_disposed(db, install_id):
    states = tree_state(db, install_id)
    assert states and all(state == 'disposed' for _, state in states), states
    assert one(db, 'SELECT count(*) FROM v24_cordis.fibers WHERE install_id IN '
                   '(SELECT DISTINCT install_id FROM v24_cordis.dispose_subtree(%s)) '
                   'AND disposed_at IS NULL', (install_id,)) == 0
    assert one(db, 'SELECT count(*) FROM v24_cordis.episodes WHERE fiber_id IN '
                   '(SELECT id FROM v24_cordis.dispose_subtree(%s)) AND closed_at IS NULL',
               (install_id,)) == 0


def parent_child(db):
    root = root_install(db)
    child = activate(db, root)
    return root, child


def test_bounded_child_first(db):
    root, child = parent_child(db)
    grandchild = activate(db, child)
    root_install_id = root['install_id']
    out = drive(db, root_install_id)
    assert_tree_disposed(db, root_install_id)
    for item in (child, grandchild):
        assert one(db, 'SELECT state FROM v24_cordis.installs WHERE id=%s',
                   (item['install_id'],)) == 'disposed'
    phases = rows(db, "SELECT payload->>'phase',payload->>'fiber_id',payload->>'child_install_id' "
                      "FROM v24_cordis.events WHERE entity_type='install' AND entity_id=%s "
                      "AND event_kind='install_dispose_progress' ORDER BY seq", (root_install_id,))
    assert phases[0][0] == 'requested', phases
    assert phases[-1][0] == 'completed' and phases[-1][2] is None, phases
    grandchild_completed = [k for k, ph in enumerate(phases)
                            if ph[0] == 'completed' and ph[2] == grandchild['install_id']]
    child_completed = [k for k, ph in enumerate(phases)
                       if ph[0] == 'completed' and ph[2] == child['install_id']]
    parent_fiber_disposed = [k for k, ph in enumerate(phases)
                             if ph[0] == 'fiber_disposed' and ph[1] == root['fiber_id']]
    assert grandchild_completed and child_completed and parent_fiber_disposed, phases
    assert grandchild_completed[0] < child_completed[0] < parent_fiber_disposed[0], phases
    # Exactly one successor per dispose step, always the selected fiber's ordinal 0.
    slots = rows(db, "SELECT x.ordinal,x.kind,x.input->>'fiber_id' FROM v24_cordis.effects x "
                     "JOIN v24_cordis.fibers f ON f.id=x.fiber_id "
                     "WHERE x.parent_id IN (SELECT id FROM v24_cordis.effects WHERE kind='command_dispose')")
    assert all(o == 0 and k == 'command_reconcile' and fid is not None for o, k, fid in slots), slots
    print(f'[CDP3-D1] real activated parent/child, child-first, parent-last, bounded '
          f'attempts={out["attempts"]}/{out["fuel"]}')


def test_seal_blocks_descendants(db):
    root, _, _ = install(db, provides=['svc'])
    phases(db, uuid.UUID(root['fiber_id']), 1)
    child = activate(db, root, requires=['svc'])
    root_fiber = uuid.UUID(root['fiber_id'])
    owner = dict(fiber_id=root['fiber_id'],
                 episode_id=str(one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s',
                                    (root_fiber,))))
    sibling, _, _ = install(db, owner=owner, mode='existing', existing=root['scope']['id'])
    assert one(db, 'SELECT count(*) FROM v24_cordis.resolve(%s,ARRAY[%s]) WHERE available',
               (root['scope']['id'], 'svc')) == 1
    # Seal only; no cleanup yet.
    dispose_request(db, root['install_id'])
    assert one(db, 'SELECT state FROM v24_cordis.installs WHERE id=%s', (root['install_id'],)) == 'dispose_pending'
    assert one(db, 'SELECT state FROM v24_cordis.installs WHERE id=%s', (child['install_id'],)) == 'installed'

    # Register a new child under the sealed owner.
    payload = declaration(owner=owner, mode='existing', existing=root['scope']['id'])
    with contextlib.closing(db.connect('service')) as conn:
        effect, outcome = command(db, conn, 'service', 'command_install', payload)
        no_write(db, conn, effect, outcome, 'owner_closing')

    # Activation/retry on sealed descendants is rejected before any write. 'on' for an
    # already-on fiber is the legitimate P0 no-op, so use the unactivated sibling.
    sibling_control = one(db, 'SELECT control_seq FROM v24_cordis.fibers WHERE id=%s',
                          (sibling['fiber_id'],))
    child_control = one(db, 'SELECT control_seq FROM v24_cordis.fibers WHERE id=%s', (child['fiber_id'],))
    for fiber, action, control in ((sibling['fiber_id'], 'on', sibling_control),
                                   (child['fiber_id'], 'retry', child_control)):
        with contextlib.closing(db.connect('service')) as conn:
            effect, outcome = command(db, conn, 'service', 'command_reconcile',
                                      reconcile_payload(uuid.UUID(fiber), action, control))
            no_write(db, conn, effect, outcome, 'owner_closing')

    # Resolve returns nothing for a contribution owned by the sealed install.
    assert one(db, 'SELECT count(*) FROM v24_cordis.resolve(%s,ARRAY[%s]) WHERE available',
               (root['scope']['id'], 'svc')) == 0

    # Driving to completion tears the child down before the parent tombstone.
    drive(db, root['install_id'], sealed=True)
    assert_tree_disposed(db, root['install_id'])

    # Tombstones never revive.
    root_control = one(db, 'SELECT control_seq FROM v24_cordis.fibers WHERE id=%s', (root_fiber,))
    with contextlib.closing(db.connect('service')) as conn:
        effect, outcome = command(db, conn, 'service', 'command_reconcile',
                                  reconcile_payload(root_fiber, 'on', root_control))
        no_write(db, conn, effect, outcome, 'already_terminal')
    assert one(db, 'SELECT state FROM v24_cordis.installs WHERE id=%s', (root['install_id'],)) == 'disposed'
    print('[CDP3-D2] dispose seal blocks descendant register/on/retry/resolve; tombstone never revives')


def test_different_login(db):
    root = root_install(db)
    child = activate(db, root)
    dispose_request(db, root['install_id'])
    effect, result, _ = dispose_request(db, root['install_id'])
    assert result['emitted'], result
    slot = uuid.UUID(result['emitted'][0])
    with contextlib.closing(db.connect('owner')) as owner:
        parent, payload = query(owner, 'SELECT parent_id,input FROM v24_cordis.effects WHERE id=%s',
                                (slot,))[0]
    key = successor_key(parent)
    with contextlib.closing(db.connect('operator')) as conn:
        _, outcome = command(db, conn, 'operator', 'command_reconcile', payload, key=key, effect=slot)
        no_write(db, conn, slot, outcome, 'effect_id_conflict')
    assert one(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (slot,)) == 'ready'
    print('[CDP3-D3] a different LOGIN cannot take over the selected fiber reconcile')


def test_host_io_states(db):
    root = root_install(db)
    owner = dict(fiber_id=root['fiber_id'],
                 episode_id=str(one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s',
                                    (root['fiber_id'],))))
    for state in ('ready', 'claimed', 'unknown', 'succeeded', 'failed', 'cancelled'):
        # A fresh child install per state keeps each proof independent.
        probe, _, _ = install(db, owner=owner, mode='existing', existing=root['scope']['id'])
        dispose_request(db, probe['install_id'])
        fiber = probe['fiber_id']
        if state == 'ready':
            mutate(db, "INSERT INTO v24_cordis.effects(id,fiber_id,kind,status,input,request_actor) "
                       "VALUES(%s,%s,'host_io','ready','{}','seed')", (uuid.uuid4(), fiber))
        elif state == 'claimed':
            mutate(db, "INSERT INTO v24_cordis.effects(id,fiber_id,kind,status,input,request_actor,"
                       "claim_owner,lease_until) VALUES(%s,%s,'host_io','claimed','{}','seed','seed',"
                       "now()+interval '1 minute')", (uuid.uuid4(), fiber))
        elif state == 'cancelled':
            mutate(db, "INSERT INTO v24_cordis.effects(id,fiber_id,kind,status,input,request_actor,"
                       "settled_at) VALUES(%s,%s,'host_io','cancelled','{}','seed',now())",
                   (uuid.uuid4(), fiber))
        else:
            mutate(db, "INSERT INTO v24_cordis.effects(id,fiber_id,kind,status,input,request_actor,"
                       "outcome,settled_at) VALUES(%s,%s,'host_io',%s,'{}','seed','{}',now())",
                   (uuid.uuid4(), fiber, state))
        with contextlib.closing(db.connect('service')) as conn:
            effect, outcome = command(db, conn, 'service', 'command_dispose',
                                      dispose_payload(probe['install_id']))
            try:
                result = api(conn, effect, outcome)
            except psycopg2.Error as exc:
                conn.rollback()
                assert exc.pgcode == '0A000', (exc.pgcode, str(exc))
                result = {'error': {'code': '0A000'}}
        assert result.get('error', {}).get('code') in ('0A000',), result
        assert one(db, 'SELECT state FROM v24_cordis.installs WHERE id=%s',
                   (probe['install_id'],)) == 'dispose_pending'
    print('[CDP3-D4] all six host_io labels stay conservative barriers; terminal labels never prove release')


def test_deferred_zero_write_and_g(db):
    root = root_install(db)
    dispose_request(db, root['install_id'])
    fiber = root['fiber_id']
    episode = one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s', (fiber,))
    run = uuid.uuid4()
    mutate(db, "INSERT INTO v24_cordis.runs(id,owner_fiber_id,owner_episode_id,scope_id,remaining_steps) "
               "VALUES(%s,%s,%s,%s,1)", (run, fiber, episode, root['scope']['id']))
    with contextlib.closing(db.connect('service')) as conn:
        effect, outcome = command(db, conn, 'service', 'command_dispose', dispose_payload(root['install_id']))
        result = no_write(db, conn, effect, outcome, disposition='deferred')
        assert result.get('disposition') == 'deferred'
    with contextlib.closing(db.connect('owner')) as owner:
        query(owner, "SET LOCAL lock_timeout='2s'")
        query(owner, 'SELECT pg_advisory_xact_lock(24,1)')
        owner.rollback()
    mutate(db, 'UPDATE v24_cordis.runs SET ended_at=clock_timestamp() WHERE id=%s', (run,))
    effect, result, _ = dispose_request(db, root['install_id'])
    assert result.get('disposition') == 'committed' and result['emitted'], result
    print('[CDP3-D5] deferred dispose is ten-table zero-write and G is free after commit; retry progresses')


def test_unknown_effect(db):
    root = root_install(db)
    dispose_request(db, root['install_id'])
    mutate(db, "INSERT INTO v24_cordis.effects(id,fiber_id,kind,status,input,request_actor,outcome,settled_at) "
               "VALUES(%s,%s,'dispatch','unknown','{}','seed','{}',now())", (uuid.uuid4(), root['fiber_id']))
    with contextlib.closing(db.connect('service')) as conn:
        effect, outcome = command(db, conn, 'service', 'command_dispose', dispose_payload(root['install_id']))
        no_write(db, conn, effect, outcome, 'blocked_unknown')
    print('[CDP3-D6] unknown non-host effect blocks dispose with zero write')


def test_validator_forgery(db):
    root = root_install(db)
    original = install_probe(db)
    try:
        other = str(uuid.uuid4())
        cases = [
            delta(domain=[dict(op='install_dispose_request', install_id=other)],
                  events=[event('install', root['install_id'], 'install_dispose_progress',
                                dict(phase='requested', fiber_id=None, child_install_id=None,
                                     scheduled_targets=None))]),
            delta(domain=[dict(op='install_dispose_request', install_id=root['install_id'])],
                  events=[event('install', root['install_id'], 'install_dispose_progress',
                                dict(phase='completed', fiber_id=None, child_install_id=None,
                                     scheduled_targets=None))]),
            delta(domain=[],
                  events=[event('install', root['install_id'], 'install_dispose_progress',
                                dict(phase='work_scheduled', fiber_id=root['fiber_id'],
                                     child_install_id=None,
                                     scheduled_targets=[root['fiber_id']]))],
                  successors=[dict(ordinal=0, kind='command_reconcile',
                                   input=dict(fiber_id=root['fiber_id'], action='advance',
                                              expected_control_seq=0))]),
        ]
        for forged in cases:
            with contextlib.closing(db.connect('service')) as conn:
                effect, outcome = command(db, conn, 'service', 'command_dispose',
                                          dispose_payload(root['install_id']))
                set_probe(conn, forged)
                no_write(db, conn, effect, outcome, 'invalid_outcome')
        assert one(db, 'SELECT state FROM v24_cordis.installs WHERE id=%s', (root['install_id'],)) == 'installed'
    finally:
        replace_function(db, original['interpret_command'])
    print('[CDP3-D7] validator recomputes target/phase/successor and rejects forged interpreter output')


def test_forged_successor(db):
    root = root_install(db)
    child = activate(db, root)
    control = one(db, 'SELECT control_seq FROM v24_cordis.fibers WHERE id=%s', (child['fiber_id'],))
    episode = one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s', (child['fiber_id'],))
    parent, result, _ = dispose_request(db, root['install_id'])
    assert result['emitted'] == []
    payload = reconcile_payload(uuid.UUID(child['fiber_id']), 'advance', control)
    key = successor_key(parent)
    forged = derive(db.roles['service'], key, 'command_reconcile')
    mutate(db, "INSERT INTO v24_cordis.effects(id,parent_id,ordinal,fiber_id,episode_id,kind,status,"
               "input,request_actor) VALUES(%s,%s,0,%s,%s,'command_reconcile','ready',%s,%s)",
           (forged, parent, child['fiber_id'], episode, Json(payload), db.roles['service']))
    with contextlib.closing(db.connect('service')) as conn:
        _, outcome = command(db, conn, 'service', 'command_reconcile', payload, key=key, effect=forged)
        no_write(db, conn, forged, outcome, 'effect_id_conflict')
    mutate(db, 'DELETE FROM v24_cordis.effects WHERE id=%s', (forged,))
    # A second parent really emits the selected child successor; an ordinal-1 forgery
    # under it is rejected even though the fiber is in the sealed subtree.
    parent2, result2, _ = dispose_request(db, root['install_id'])
    assert len(result2['emitted']) == 1, result2
    key2 = successor_key(parent2, 1)
    forged2 = derive(db.roles['service'], key2, 'command_reconcile')
    root_control = one(db, 'SELECT control_seq FROM v24_cordis.fibers WHERE id=%s', (root['fiber_id'],))
    root_episode = one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s', (root['fiber_id'],))
    payload2 = reconcile_payload(uuid.UUID(root['fiber_id']), 'advance', root_control)
    mutate(db, "INSERT INTO v24_cordis.effects(id,parent_id,ordinal,fiber_id,episode_id,kind,status,"
               "input,request_actor) VALUES(%s,%s,1,%s,%s,'command_reconcile','ready',%s,%s)",
           (forged2, parent2, root['fiber_id'], root_episode, Json(payload2), db.roles['service']))
    with contextlib.closing(db.connect('service')) as conn:
        _, outcome = command(db, conn, 'service', 'command_reconcile', payload2, key=key2, effect=forged2)
        no_write(db, conn, forged2, outcome, 'effect_id_conflict')
    print('[CDP3-D8] dispose-parent successors require ordinal 0 and the parent receipt emitted id')


def test_history_does_not_inflate_closure(db):
    root = root_install(db)
    mutate(db, "INSERT INTO v24_cordis.effects(id,fiber_id,kind,status,input,request_actor,outcome,settled_at) "
               "SELECT gen_random_uuid(),%s,'dispatch','succeeded','{}','seed','{}',now() "
               'FROM generate_series(1,600)', (root['fiber_id'],))
    assert one(db, 'SELECT count(*) FROM v24_cordis.effects WHERE fiber_id=%s',
               (root['fiber_id'],)) >= 600
    out = drive(db, root['install_id'])
    assert_tree_disposed(db, root['install_id'])
    print(f'[CDP3-D9] 600 settled historical effects do not inflate closure; '
          f'attempts={out["attempts"]}/{out["fuel"]}')


def main():
    tests = (test_bounded_child_first, test_seal_blocks_descendants, test_different_login,
             test_host_io_states, test_deferred_zero_write_and_g, test_unknown_effect,
             test_validator_forgery, test_forged_successor, test_history_does_not_inflate_closure)
    with Server() as server:
        for test in tests:
            with TestDB(server) as db:
                test(db)
    print('[passed] CDP3-D')


if __name__ == '__main__':
    main()
