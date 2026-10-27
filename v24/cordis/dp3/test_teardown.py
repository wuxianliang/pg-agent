"""CDP3-T: W3 production P6 drain, inverse, pin release and episode close.

Production installs, controls and P6 advances are exercised through real `advance`.
Owner DML is limited to explicit fixtures named at each use: tombstoned child,
run/pin facts, effect barriers, inverse kinds without a production registrar,
historical rows and fault-free terminal facts. It proves no W4 dispose, no DP4
settlement, no listener dispatch and no production run loop.
"""
from __future__ import annotations
import contextlib
import uuid
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dp2'))

from psycopg2.extras import Json

from test_support import (Server, TestDB, snapshot, query, api, no_write,
                          reconcile_payload, sqlstate)
from test_activation import (install, phases, commit_new, child_call, one, rows, finish)


def mutate(db, statement, params=()):
    """Owner-only fixture mutation. Every writer takes G before row locks."""
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, statement, params)
        conn.commit()


def owner_of(db, fiber):
    return dict(fiber_id=str(fiber), episode_id=str(one(
        db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s', (fiber,))))


def root_install(db):
    payload, _, _ = install(db)
    phases(db, uuid.UUID(payload['fiber_id']), 0)
    return payload


def activate(db, root, provides=(), requires=()):
    payload, _, _ = install(db, owner=owner_of(db, root['fiber_id']), mode='existing',
                            existing=root['scope']['id'], provides=list(provides),
                            requires=list(requires))
    phases(db, uuid.UUID(payload['fiber_id']), len(provides))
    return payload


def applied(db, effect, outcome):
    with contextlib.closing(db.connect('service')) as conn:
        result = api(conn, effect, outcome)
        assert result.get('disposition') == 'committed', result
        conn.commit()
    return result


def enter_closing(db, fiber):
    control = one(db, 'SELECT control_seq FROM v24_cordis.fibers WHERE id=%s', (fiber,))
    off, result, _ = commit_new(db, 'command_reconcile', reconcile_payload(fiber, 'off', control))
    assert result.get('disposition') == 'committed' and result['emitted'], result
    slot, outcome = child_call(db, off, reconcile_payload(fiber, 'advance', control + 1))
    applied(db, slot, outcome)
    assert rows(db, 'SELECT state,outcome FROM v24_cordis.episodes WHERE id=(SELECT '
                    'current_episode_id FROM v24_cordis.fibers WHERE id=%s)', (fiber,)) == [('closing', 'retire')]
    return control + 1


def p6_slot(db, fiber, control):
    """A fresh legal off/retry control allocates the one current-generation P6 slot."""
    off, result, _ = commit_new(db, 'command_reconcile', reconcile_payload(fiber, 'off', control))
    assert result.get('disposition') == 'committed' and len(result['emitted']) == 1, result
    new_control = one(db, 'SELECT control_seq FROM v24_cordis.fibers WHERE id=%s', (fiber,))
    effect, outcome = child_call(db, off, reconcile_payload(fiber, 'advance', new_control))
    assert effect == uuid.UUID(result['emitted'][0]), (effect, result['emitted'])
    return effect, outcome, new_control


def next_slot(db, parent, fiber, control):
    return child_call(db, parent, reconcile_payload(fiber, 'advance', control))


def drain(db, fiber, control, limit=8):
    effect, outcome, control = p6_slot(db, fiber, control)
    results = []
    for _ in range(limit):
        result = applied(db, effect, outcome)
        results.append(result)
        if not result['emitted']:
            return results
        effect, outcome = child_call(db, effect, reconcile_payload(fiber, 'advance', control))
    raise AssertionError('P6 drain did not converge')


def event_payload(db, effect):
    return one(db, 'SELECT payload FROM v24_cordis.events WHERE effect_id=%s', (effect,))


def contribution_json(db, contribution):
    return one(db, 'SELECT to_jsonb(c) FROM v24_cordis.contributions c WHERE id=%s', (contribution,))


def test_empty_close(db, root):
    fiber = uuid.UUID(activate(db, root)['fiber_id'])
    control = enter_closing(db, fiber)
    before_episodes = one(db, 'SELECT count(*) FROM v24_cordis.episodes WHERE fiber_id=%s', (fiber,))
    effect, outcome, _ = p6_slot(db, fiber, control)
    result = applied(db, effect, outcome)
    assert result['emitted'] == [], result
    assert rows(db, 'SELECT state,outcome,closed_at IS NOT NULL FROM v24_cordis.episodes '
                    'WHERE fiber_id=%s', (fiber,)) == [('closing', 'retire', True)]
    assert rows(db, 'SELECT current_episode_id IS NULL,retire_started_at IS NULL,want_on,failure '
                    'FROM v24_cordis.fibers WHERE id=%s', (fiber,)) == [(True, True, False, None)]
    assert one(db, 'SELECT count(*) FROM v24_cordis.episodes WHERE fiber_id=%s', (fiber,)) == before_episodes
    payload = event_payload(db, effect)
    assert set(payload) == {'episode_id', 'epoch', 'outcome', 'control_seq'}, payload
    assert payload['outcome'] == 'retire' and payload['epoch'] == 1, payload
    print('[CDP3-T1] empty-contribution episode closes without beginning a new episode')


def test_inverse_release_and_replay(db, root):
    payload = activate(db, root, provides=['inv-a', 'inv-b'])
    fiber = uuid.UUID(payload['fiber_id'])
    control = enter_closing(db, fiber)
    rows_before = rows(db, 'SELECT id,seq,descriptor,inverse FROM v24_cordis.contributions '
                           'WHERE fiber_id=%s ORDER BY seq DESC', (fiber,))
    effect, outcome, _ = p6_slot(db, fiber, control)
    result = applied(db, effect, outcome)
    assert len(result['emitted']) == 1, result
    event = event_payload(db, effect)
    assert event['seq_from'] == 1 and event['seq_through'] == 0, event
    assert event['contribution_ids'] == [str(row[0]) for row in rows_before], event
    assert rows(db, 'SELECT id,seq,descriptor,inverse FROM v24_cordis.contributions '
                    'WHERE fiber_id=%s ORDER BY seq DESC', (fiber,)) == rows_before
    assert one(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id=%s '
                   'AND withdrawn_at IS NOT NULL AND released_at IS NOT NULL', (fiber,)) == 2
    assert one(db, 'SELECT count(*) FROM v24_cordis.pins p JOIN v24_cordis.contributions c '
                   'ON c.id=p.contribution_id WHERE c.fiber_id=%s AND p.released_at IS NULL',
               (fiber,)) == 0
    released = one(db, 'SELECT min(released_at)::text||max(released_at)::text '
                        'FROM v24_cordis.contributions WHERE fiber_id=%s', (fiber,))
    with contextlib.closing(db.connect('owner')) as owner:
        before = snapshot(owner)
        owner.rollback()
    with contextlib.closing(db.connect('service')) as conn:
        assert api(conn, effect, outcome) == result
        conn.commit()
    with contextlib.closing(db.connect('owner')) as owner:
        assert snapshot(owner) == before
        owner.rollback()
    assert one(db, 'SELECT min(released_at)::text||max(released_at)::text '
                   'FROM v24_cordis.contributions WHERE fiber_id=%s', (fiber,)) == released
    successor, next_out = next_slot(db, effect, fiber, control)
    closed = applied(db, successor, next_out)
    assert closed['emitted'] == [], closed
    assert one(db, 'SELECT closed_at IS NOT NULL FROM v24_cordis.episodes WHERE fiber_id=%s',
               (fiber,)) is True
    print('[CDP3-T2] inverse releases highest seq first, keeps physical rows, and replay/refresh never re-releases')


def test_activation_pin_blocks_provider(db, root):
    provider = activate(db, root, provides=['pin-svc'])
    pf = uuid.UUID(provider['fiber_id'])
    consumer = activate(db, root, requires=['pin-svc'])
    cf = uuid.UUID(consumer['fiber_id'])
    assert one(db, 'SELECT count(*) FROM v24_cordis.pins WHERE consumer_fiber_id=%s', (cf,)) == 1
    pcontrol = enter_closing(db, pf)
    effect, outcome, _ = p6_slot(db, pf, pcontrol)
    with contextlib.closing(db.connect('service')) as conn:
        deferred = no_write(db, conn, effect, outcome, disposition='deferred')
    assert set(deferred) == {'v', 'disposition', 'effect_id', 'emitted', 'revision', 'claim'}
    assert one(db, "SELECT status FROM v24_cordis.effects WHERE id=%s", (effect,)) == 'ready'
    assert one(db, 'SELECT count(*) FROM v24_cordis.requests WHERE effect_id=%s', (effect,)) == 0
    assert one(db, 'SELECT count(*) FROM v24_cordis.events WHERE effect_id=%s', (effect,)) == 0
    ccontrol = enter_closing(db, cf)
    ceffect, cout, _ = p6_slot(db, cf, ccontrol)
    cres = applied(db, ceffect, cout)
    assert len(cres['emitted']) == 1, cres
    cevent = event_payload(db, ceffect)
    assert len(cevent['activation_pin_ids']) == 1 and cevent['run_pin_ids'] == [], cevent
    assert one(db, 'SELECT released_at IS NOT NULL FROM v24_cordis.pins WHERE consumer_fiber_id=%s',
               (cf,)) is True
    cnext, cnext_out = next_slot(db, ceffect, cf, ccontrol)
    assert applied(db, cnext, cnext_out)['emitted'] == []
    resumed = applied(db, effect, outcome)
    assert len(resumed['emitted']) == 1, resumed
    assert one(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id=%s '
                   'AND released_at IS NOT NULL', (pf,)) == 1
    pnext, pnext_out = next_slot(db, effect, pf, pcontrol)
    assert applied(db, pnext, pnext_out)['emitted'] == []
    print('[CDP3-T3] live activation pin with no run defers provider release; consumer pin release unblocks the same request')


def test_run_pin_release(db, root):
    provider = activate(db, root, provides=['run-svc'])
    qf = uuid.UUID(provider['fiber_id'])
    contribution = one(db, "SELECT id FROM v24_cordis.contributions WHERE fiber_id=%s "
                           "AND kind='service'", (qf,))
    epoch = one(db, 'SELECT e.epoch FROM v24_cordis.contributions c JOIN v24_cordis.episodes e '
                    'ON e.id=c.episode_id WHERE c.id=%s', (contribution,))
    fiber = uuid.UUID(activate(db, root)['fiber_id'])
    control = enter_closing(db, fiber)
    episode = one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s', (fiber,))
    run = uuid.uuid4()
    pin = uuid.uuid4()
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, 'INSERT INTO v24_cordis.runs(id,owner_fiber_id,owner_episode_id,scope_id,'
                    'spawn_key,remaining_steps) VALUES(%s,%s,%s,%s,%s,0)',
              (run, fiber, episode, root['scope']['id'], 'open-run'))
        query(conn, 'INSERT INTO v24_cordis.pins(id,consumer_run_id,key,contribution_id,provider_epoch) '
                    'VALUES(%s,%s,%s,%s,%s)', (pin, run, 'run-svc', contribution, epoch))
        conn.commit()
    assert one(db, 'SELECT v24_cordis.run_pin_release_delta(%s)', (run,)) == []
    effect, outcome, _ = p6_slot(db, fiber, control)
    with contextlib.closing(db.connect('service')) as conn:
        no_write(db, conn, effect, outcome, disposition='deferred')
    mutate(db, 'UPDATE v24_cordis.runs SET ended_at=clock_timestamp() WHERE id=%s', (run,))
    assert one(db, 'SELECT v24_cordis.run_pin_release_delta(%s)', (run,)) == [str(pin)]
    result = applied(db, effect, outcome)
    assert len(result['emitted']) == 1, result
    event = event_payload(db, effect)
    assert event['run_pin_ids'] == [str(pin)] and event['activation_pin_ids'] == [], event
    assert one(db, 'SELECT released_at IS NOT NULL FROM v24_cordis.pins WHERE id=%s', (pin,)) is True
    assert rows(db, 'SELECT result,ended_at IS NOT NULL FROM v24_cordis.runs WHERE id=%s',
                (run,)) == [(None, True)]
    successor, next_out = next_slot(db, effect, fiber, control)
    assert applied(db, successor, next_out)['emitted'] == []
    print('[CDP3-T4] open run defers; terminal run pin is released first with run result/settlement untouched')


def test_effect_barriers(db, root):
    fiber = uuid.UUID(activate(db, root)['fiber_id'])
    control = enter_closing(db, fiber)
    episode = one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s', (fiber,))
    effect, outcome, _ = p6_slot(db, fiber, control)
    barrier = uuid.uuid4()
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, "INSERT INTO v24_cordis.effects(id,fiber_id,episode_id,kind,status,input,"
                    "request_actor) VALUES(%s,%s,%s,'dispatch','ready','{}',%s)",
              (barrier, fiber, episode, db.roles['service']))
        conn.commit()
    with contextlib.closing(db.connect('service')) as conn:
        no_write(db, conn, effect, outcome, disposition='deferred')
    mutate(db, "UPDATE v24_cordis.effects SET status='claimed',claim_owner=request_actor,"
               "lease_until=clock_timestamp()-interval '1 minute',attempt=1,fence=1 WHERE id=%s", (barrier,))
    with contextlib.closing(db.connect('service')) as conn:
        no_write(db, conn, effect, outcome, disposition='deferred')
    assert one(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (barrier,)) == 'claimed'
    mutate(db, "UPDATE v24_cordis.effects SET status='succeeded',claim_owner=NULL,lease_until=NULL,"
               "outcome='{}'::jsonb,settled_at=clock_timestamp() WHERE id=%s", (barrier,))
    closed = applied(db, effect, outcome)
    assert closed['emitted'] == [], closed

    unknown_fiber = uuid.UUID(activate(db, root)['fiber_id'])
    unknown_control = enter_closing(db, unknown_fiber)
    unknown_ep = one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s', (unknown_fiber,))
    ueffect, uoutcome, _ = p6_slot(db, unknown_fiber, unknown_control)
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, "INSERT INTO v24_cordis.effects(id,fiber_id,episode_id,kind,status,input,"
                    "request_actor,outcome,settled_at) VALUES(%s,%s,%s,'dispatch','unknown','{}',%s,"
                    "'{}'::jsonb,clock_timestamp())", (uuid.uuid4(), unknown_fiber, unknown_ep,
                                                       db.roles['service']))
        conn.commit()
    with contextlib.closing(db.connect('service')) as conn:
        no_write(db, conn, ueffect, uoutcome, code='blocked_unknown')

    host_fiber = uuid.UUID(activate(db, root)['fiber_id'])
    host_control = enter_closing(db, host_fiber)
    host_ep = one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s', (host_fiber,))
    heffect, houtcome, _ = p6_slot(db, host_fiber, host_control)
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, "INSERT INTO v24_cordis.effects(id,fiber_id,episode_id,kind,status,input,"
                    "request_actor,outcome,settled_at) VALUES(%s,%s,%s,'host_io','succeeded','{}',%s,"
                    "'{}'::jsonb,clock_timestamp())", (uuid.uuid4(), host_fiber, host_ep,
                                                       db.roles['service']))
        conn.commit()
    with contextlib.closing(db.connect('owner')) as owner:
        before = snapshot(owner)
        owner.rollback()
    with contextlib.closing(db.connect('service')) as conn:
        sqlstate(conn, 'SELECT v24_cordis.advance(%s,%s)', (heffect, Json(houtcome)))
    with contextlib.closing(db.connect('owner')) as owner:
        assert snapshot(owner) == before
        owner.rollback()
    print('[CDP3-T5] ready/claimed/expired-lease/unknown/host_io effects stay barriers or hard refusals')


def test_unsupported_and_unknown_inverse(db, root):
    cases = (('cell', {'op': 'restore_prev'}, 'unsupported'),
             ('reservation', {'op': 'release_reservation'}, 'unsupported'),
             ('service', {'op': 'unknown', 'debt': {'reason': 'fixture'}}, 'unknown'))
    for index, (kind, inverse, classification) in enumerate(cases):
        payload = activate(db, root)
        fiber = uuid.UUID(payload['fiber_id'])
        episode = one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s', (fiber,))
        service = kind == 'service'
        with contextlib.closing(db.connect('owner')) as conn:
            query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
            query(conn, 'INSERT INTO v24_cordis.contributions(id,fiber_id,episode_id,seq,kind,realm,key,'
                        'descriptor,inverse,contract_version) VALUES(%s,%s,%s,0,%s,%s,%s,\'{}\',%s,\'1\')',
                  (uuid.uuid4(), fiber, episode, kind, 'root' if service else None,
                   'unsupported-' + str(index) if service else None, Json(inverse)))
            conn.commit()
        control = enter_closing(db, fiber)
        # P5 withdraws service/cell/listener only; reservation/child/unknown keep their debt.
        assert one(db, 'SELECT withdrawn_at IS NOT NULL FROM v24_cordis.contributions '
                       'WHERE fiber_id=%s AND kind=%s', (fiber, kind)) is (kind != 'reservation')
        effect, outcome, _ = p6_slot(db, fiber, control)
        with contextlib.closing(db.connect('owner')) as owner:
            before = snapshot(owner)
            owner.rollback()
        with contextlib.closing(db.connect('service')) as conn:
            if classification == 'unsupported':
                sqlstate(conn, 'SELECT v24_cordis.advance(%s,%s)', (effect, Json(outcome)))
            else:
                no_write(db, conn, effect, outcome, code='blocked_unknown')
        with contextlib.closing(db.connect('owner')) as owner:
            assert snapshot(owner) == before
            owner.rollback()
    print('[CDP3-T6] cell/reservation inverse is 0A000 rollback; unknown inverse is blocked_unknown zero-write')


def test_listener_inverse(db, root):
    # Owner fixture: DP3 has no production listener registrar. The teardown ledger is real.
    fiber = uuid.UUID(activate(db, root)['fiber_id'])
    episode = one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s', (fiber,))
    listener = uuid.uuid4()
    descriptor = {'event': 'evt', 'listener_id': 'l1'}
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, 'INSERT INTO v24_cordis.contributions(id,fiber_id,episode_id,seq,kind,realm,key,'
                    'descriptor,inverse,contract_version) VALUES(%s,%s,%s,0,\'listener\',NULL,NULL,'
                    "%s,'{\"op\":\"delete_row\"}','1')", (listener, fiber, episode, Json(descriptor)))
        conn.commit()
    control = enter_closing(db, fiber)
    after_withdraw = contribution_json(db, listener)
    assert after_withdraw['descriptor'] == descriptor and after_withdraw['released_at'] is None
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        sqlstate(conn, 'INSERT INTO v24_cordis.contributions(id,fiber_id,episode_id,seq,kind,realm,key,'
                       'descriptor,inverse,contract_version) VALUES(%s,%s,%s,1,\'listener\',NULL,NULL,'
                       "%s,'{\"op\":\"delete_row\"}','1')",
                 (uuid.uuid4(), fiber, episode, Json(descriptor)), code='23505')
    effect, outcome, _ = p6_slot(db, fiber, control)
    applied(db, effect, outcome)
    released = contribution_json(db, listener)
    assert released['descriptor'] == descriptor and released['inverse'] == {'op': 'delete_row'}
    assert released['withdrawn_at'] is not None and released['released_at'] is not None, released
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, 'INSERT INTO v24_cordis.contributions(id,fiber_id,episode_id,seq,kind,realm,key,'
                    'descriptor,inverse,contract_version) VALUES(%s,%s,%s,1,\'listener\',NULL,NULL,'
                    "%s,'{\"op\":\"delete_row\"}','1')",
              (uuid.uuid4(), fiber, episode, Json(descriptor)))
        conn.rollback()
    successor, next_out = next_slot(db, effect, fiber, control)
    assert applied(db, successor, next_out)['emitted'] == []
    print('[CDP3-T7b] listener owner-fixture inverse releases the ledger row and frees the listener address')


def test_child_inverse_tombstone(db, root):
    parent = activate(db, root)
    pf = uuid.UUID(parent['fiber_id'])
    child = activate(db, parent, provides=['child-svc'])
    cf = uuid.UUID(child['fiber_id'])
    contribution = one(db, "SELECT id FROM v24_cordis.contributions WHERE fiber_id=%s "
                           "AND kind='child'", (pf,))
    control = enter_closing(db, pf)
    assert one(db, 'SELECT withdrawn_at IS NULL FROM v24_cordis.contributions WHERE id=%s',
               (contribution,)) is True
    effect, outcome, _ = p6_slot(db, pf, control)
    with contextlib.closing(db.connect('service')) as conn:
        no_write(db, conn, effect, outcome, disposition='deferred')
    assert one(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE id=%s '
                   'AND released_at IS NULL', (contribution,)) == 1
    mutate(db, 'UPDATE v24_cordis.fibers SET disposed_at=clock_timestamp() WHERE id=%s', (cf,))
    result = applied(db, effect, outcome)
    assert len(result['emitted']) == 1, result
    row = contribution_json(db, contribution)
    assert row['descriptor'] == {'child_fiber_id': str(cf)}, row
    assert row['inverse'] == {'op': 'dispose_child'}, row
    assert row['withdrawn_at'] is not None and row['released_at'] is not None, row
    assert one(db, 'SELECT disposed_at IS NOT NULL FROM v24_cordis.fibers WHERE id=%s', (cf,)) is True
    successor, next_out = next_slot(db, effect, pf, control)
    assert applied(db, successor, next_out)['emitted'] == []
    print('[CDP3-T7] child inverse waits for an owner-fixture tombstone, then releases with schema-forced withdrawn_at')


def test_select_32_strict_desc(db, root):
    payload = activate(db, root, provides=[f'desc-{i:02d}' for i in range(33)])
    fiber = uuid.UUID(payload['fiber_id'])
    control = enter_closing(db, fiber)
    expected = rows(db, 'SELECT id FROM v24_cordis.contributions WHERE fiber_id=%s '
                        'ORDER BY seq DESC', (fiber,))
    effect, outcome, _ = p6_slot(db, fiber, control)
    result = applied(db, effect, outcome)
    assert len(result['emitted']) == 1
    event = event_payload(db, effect)
    assert event['contribution_ids'] == [str(row[0]) for row in expected[:32]], event
    assert event['seq_from'] == 32 and event['seq_through'] == 1, event
    assert one(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id=%s '
                   'AND released_at IS NULL', (fiber,)) == 1
    assert one(db, 'SELECT released_at IS NULL AND seq=0 FROM v24_cordis.contributions '
                   'WHERE fiber_id=%s AND released_at IS NULL', (fiber,)) is True
    second, second_out = next_slot(db, effect, fiber, control)
    assert len(applied(db, second, second_out)['emitted']) == 1
    event2 = event_payload(db, second)
    assert event2['contribution_ids'] == [str(expected[32][0])], event2
    assert event2['seq_from'] == 0 and event2['seq_through'] == 0, event2
    third, third_out = next_slot(db, second, fiber, control)
    assert applied(db, third, third_out)['emitted'] == []
    print('[CDP3-T8] 32+1 takes highest unreleased seq DESC without filtering and never skips to lower seq')


def test_pin_ordering_and_combined_cap(db, root):
    provider = activate(db, root, provides=['order-svc'])
    qf = uuid.UUID(provider['fiber_id'])
    contribution = one(db, "SELECT id FROM v24_cordis.contributions WHERE fiber_id=%s "
                           "AND kind='service'", (qf,))
    epoch = one(db, 'SELECT e.epoch FROM v24_cordis.contributions c JOIN v24_cordis.episodes e '
                    'ON e.id=c.episode_id WHERE c.id=%s', (contribution,))
    fiber = uuid.UUID(activate(db, root)['fiber_id'])
    control = enter_closing(db, fiber)
    episode = one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s', (fiber,))
    run_ids = [uuid.UUID(int=0x2000 + i) for i in range(29)]
    run_pins = {}
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        for index, run in enumerate(run_ids):
            query(conn, 'INSERT INTO v24_cordis.runs(id,owner_fiber_id,owner_episode_id,scope_id,'
                        'spawn_key,remaining_steps,ended_at) VALUES(%s,%s,%s,%s,%s,0,clock_timestamp())',
                  (run, fiber, episode, root['scope']['id'], 'order-run-' + str(index)))
            pin = uuid.uuid4()
            query(conn, 'INSERT INTO v24_cordis.pins(id,consumer_run_id,key,contribution_id,provider_epoch) '
                        'VALUES(%s,%s,%s,%s,%s)', (pin, run, 'r' + str(index), contribution, epoch))
            run_pins[run] = pin
        double = uuid.UUID(int=0x3000)
        query(conn, 'INSERT INTO v24_cordis.runs(id,owner_fiber_id,owner_episode_id,scope_id,spawn_key,'
                    'remaining_steps,ended_at) VALUES(%s,%s,%s,%s,%s,0,clock_timestamp())',
              (double, fiber, episode, root['scope']['id'], 'order-double'))
        for key in ('r-b', 'r-a'):
            pin = uuid.uuid4()
            query(conn, 'INSERT INTO v24_cordis.pins(id,consumer_run_id,key,contribution_id,provider_epoch) '
                        'VALUES(%s,%s,%s,%s,%s)', (pin, double, key, contribution, epoch))
            run_pins[(double, key)] = pin
        activation = []
        for key in ('a0', 'a1'):
            pin = uuid.uuid4()
            query(conn, 'INSERT INTO v24_cordis.pins(id,consumer_fiber_id,consumer_episode_id,key,'
                        'contribution_id,provider_epoch) VALUES(%s,%s,%s,%s,%s,%s)',
                  (pin, fiber, episode, key, contribution, epoch))
            activation.append(pin)
        conn.commit()
    effect, outcome, _ = p6_slot(db, fiber, control)
    result = applied(db, effect, outcome)
    assert len(result['emitted']) == 1
    event = event_payload(db, effect)
    expected_runs = [run_pins[run] for run in sorted(run_ids)]
    expected_runs += [run_pins[(double, 'r-a')], run_pins[(double, 'r-b')]]
    assert event['run_pin_ids'] == [str(pin) for pin in expected_runs], event
    assert event['activation_pin_ids'] == [str(activation[0])], event
    assert len(event['run_pin_ids']) + len(event['activation_pin_ids']) == 32, event
    assert one(db, 'SELECT released_at IS NULL FROM v24_cordis.pins WHERE id=%s', (activation[1],)) is True
    second, second_out = next_slot(db, effect, fiber, control)
    result2 = applied(db, second, second_out)
    assert len(result2['emitted']) == 1
    event2 = event_payload(db, second)
    assert event2['run_pin_ids'] == [] and event2['activation_pin_ids'] == [str(activation[1])], event2
    third, third_out = next_slot(db, second, fiber, control)
    assert applied(db, third, third_out)['emitted'] == []
    print('[CDP3-T9] run pins order by run/key/id before activation key/id; combined batch is at most 32')


def test_history_and_address_reuse(db, root):
    fiber = uuid.UUID(activate(db, root)['fiber_id'])
    consumer = activate(db, root)
    consumer_fiber = uuid.UUID(consumer['fiber_id'])
    consumer_episode = one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s',
                           (consumer_fiber,))
    first, second = uuid.uuid4(), uuid.uuid4()
    pin = uuid.uuid4()
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, 'INSERT INTO v24_cordis.contributions(id,fiber_id,episode_id,seq,kind,realm,key,'
                    'descriptor,inverse,contract_version) SELECT %s,id,current_episode_id,0,'
                    "'service','root','hist-a','{}','{\"op\":\"delete_row\"}','1' "
                    'FROM v24_cordis.fibers WHERE id=%s', (first, fiber))
        query(conn, 'INSERT INTO v24_cordis.contributions(id,fiber_id,episode_id,seq,kind,realm,key,'
                    'descriptor,prev_contribution_id,inverse,contract_version) SELECT %s,id,'
                    "current_episode_id,1,'service','root','hist-b','{}',%s,"
                    "'{\"op\":\"delete_row\"}','1' FROM v24_cordis.fibers WHERE id=%s",
              (second, first, fiber))
        query(conn, 'INSERT INTO v24_cordis.pins(id,consumer_fiber_id,consumer_episode_id,key,'
                    'contribution_id,provider_epoch) SELECT %s,%s,%s,%s,%s,e.epoch '
                    'FROM v24_cordis.contributions c JOIN v24_cordis.episodes e '
                    'ON e.id=c.episode_id WHERE c.id=%s',
              (pin, consumer_fiber, consumer_episode, 'hist-old', first, first))
        query(conn, 'UPDATE v24_cordis.pins SET released_at=clock_timestamp() WHERE id=%s', (pin,))
        conn.commit()
    control = enter_closing(db, fiber)
    assert one(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id=%s '
                   'AND withdrawn_at IS NOT NULL AND released_at IS NULL', (fiber,)) == 2
    effect, outcome, _ = p6_slot(db, fiber, control)
    applied(db, effect, outcome)
    assert one(db, 'SELECT prev_contribution_id=%s FROM v24_cordis.contributions WHERE id=%s',
               (first, second)) is True
    assert one(db, 'SELECT count(*) FROM v24_cordis.contributions a JOIN '
                   'v24_cordis.contributions b ON b.prev_contribution_id=a.id WHERE b.id=%s',
               (second,)) == 1
    assert one(db, 'SELECT count(*) FROM v24_cordis.pins WHERE id=%s', (pin,)) == 1
    assert one(db, 'SELECT v24_cordis.pin_readable(%s)', (pin,)) is False

    holder = activate(db, root, provides=['addr-key'])
    holder_fiber = uuid.UUID(holder['fiber_id'])
    failed, _, _ = install(db, owner=owner_of(db, root['fiber_id']), mode='existing',
                           existing=root['scope']['id'], provides=['addr-key'])
    failed_fiber = uuid.UUID(failed['fiber_id'])
    on, result, _ = commit_new(db, 'command_reconcile', reconcile_payload(failed_fiber, 'on', 0))
    assert result.get('disposition') == 'committed', result
    slot, outcome = child_call(db, on, reconcile_payload(failed_fiber, 'advance', 1))
    begun = applied(db, slot, outcome)
    assert len(begun['emitted']) == 1, begun
    slot, outcome = child_call(db, slot, reconcile_payload(failed_fiber, 'advance', 1))
    assert applied(db, slot, outcome)['emitted'] == []
    assert one(db, "SELECT failure->>'key' FROM v24_cordis.fibers WHERE id=%s", (failed_fiber,)) == 'addr-key'
    assert one(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id=%s', (failed_fiber,)) == 0
    holder_control = enter_closing(db, holder_fiber)
    # P5 has withdrawn the holder contribution but not released it: the address is still occupied.
    blocked, _, _ = install(db, owner=owner_of(db, root['fiber_id']), mode='existing',
                            existing=root['scope']['id'], provides=['addr-key'])
    blocked_fiber = uuid.UUID(blocked['fiber_id'])
    blocked_on, blocked_result, _ = commit_new(db, 'command_reconcile',
                                               reconcile_payload(blocked_fiber, 'on', 0))
    assert blocked_result.get('disposition') == 'committed', blocked_result
    blocked_slot, blocked_out = child_call(db, blocked_on, reconcile_payload(blocked_fiber, 'advance', 1))
    blocked_begun = applied(db, blocked_slot, blocked_out)
    assert len(blocked_begun['emitted']) == 1, blocked_begun
    blocked_slot, blocked_out = child_call(db, blocked_slot, reconcile_payload(blocked_fiber, 'advance', 1))
    assert applied(db, blocked_slot, blocked_out)['emitted'] == []
    assert one(db, "SELECT failure->>'key' FROM v24_cordis.fibers WHERE id=%s",
               (blocked_fiber,)) == 'addr-key'
    assert one(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id=%s',
               (blocked_fiber,)) == 0
    hold_effect, hold_out, _ = p6_slot(db, holder_fiber, holder_control)
    applied(db, hold_effect, hold_out)
    holder_close, holder_close_out = next_slot(db, hold_effect, holder_fiber, holder_control)
    assert applied(db, holder_close, holder_close_out)['emitted'] == []
    failed_control = one(db, 'SELECT control_seq FROM v24_cordis.fibers WHERE id=%s', (failed_fiber,))
    off, off_result, _ = commit_new(db, 'command_reconcile',
                                    reconcile_payload(failed_fiber, 'off', failed_control))
    assert off_result['emitted'], off_result
    close_slot, close_out = child_call(db, off, reconcile_payload(failed_fiber, 'advance', failed_control + 1))
    assert applied(db, close_slot, close_out)['emitted'] == []
    on2, on_result, _ = commit_new(db, 'command_reconcile',
                                   reconcile_payload(failed_fiber, 'on', failed_control + 1))
    assert on_result['emitted'], on_result
    finish(db, on2, failed_fiber, 1, control=failed_control + 2)
    assert one(db, "SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id=%s "
                   "AND key='addr-key' AND released_at IS NULL", (failed_fiber,)) == 1
    assert rows(db, 'SELECT state FROM v24_cordis.episodes WHERE id=(SELECT current_episode_id '
                    'FROM v24_cordis.fibers WHERE id=%s)', (failed_fiber,)) == [('active',)]
    print('[CDP3-T10] historical pin/prev rows survive release; the service address is reusable only after release')


def main():
    with Server() as server, TestDB(server) as db:
        root = root_install(db)
        test_empty_close(db, root)
        test_inverse_release_and_replay(db, root)
        test_activation_pin_blocks_provider(db, root)
        test_run_pin_release(db, root)
        test_effect_barriers(db, root)
        test_unsupported_and_unknown_inverse(db, root)
        test_listener_inverse(db, root)
        test_child_inverse_tombstone(db, root)
        test_select_32_strict_desc(db, root)
        test_pin_ordering_and_combined_cap(db, root)
        test_history_and_address_reuse(db, root)
    print('[passed] CDP3-T')


if __name__ == '__main__':
    main()
