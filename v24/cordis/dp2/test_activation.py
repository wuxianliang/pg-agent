"""CDP2-A: production P0-P4 activation.

Run with: uv run python v24/cordis/dp2/test_activation.py
Success paths use real command_install and command_reconcile. Owner DML is only for
negatives, address occupants, and the direct DAG call; it is not activation evidence.
"""
from __future__ import annotations
import contextlib
import uuid
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dp1'))

import psycopg2
from psycopg2.extras import Json

from test_support import (Server, TestDB, snapshot, query, api, command, no_write,
                          install_payload, reconcile_payload, sqlstate, derive, successor_key)

CONTRACT = dict(contract_version='1', handler_digest='a' * 64,
                replay=dict(repeat=True, concurrent=False))


def rows(db, statement, params=()):
    with contextlib.closing(db.connect('owner')) as conn:
        return query(conn, statement, params)


def one(db, statement, params=()):
    return rows(db, statement, params)[0][0]


def declaration(provides=(), requires=(), check=None, owner=None, mode='root', parent=None,
                existing=None, overrides=None):
    payload = install_payload(mode='existing' if mode == 'existing' else 'root', owner=owner,
                              existing_scope=existing)
    if mode == 'child':
        payload['scope'] = dict(mode='child', id=str(uuid.uuid4()), parent_id=str(parent),
                                realm_overrides=overrides or {})
    elif mode == 'root':
        payload['scope']['realm_overrides'] = overrides or {}
    payload['manifest'] = dict(
        requires=list(requires),
        provides=[dict(key=key, descriptor=dict(capability='cap'), contract_version='1')
                  for key in provides],
        priority=0, check={} if check is None else check)
    payload['contracts'] = {'cap': CONTRACT} if provides else {}
    return payload


def commit_new(db, kind, payload, alias='service'):
    with contextlib.closing(db.connect(alias)) as conn:
        effect, outcome = command(db, conn, alias, kind, payload)
        result = api(conn, effect, outcome)
        conn.commit()
    return effect, result, outcome


def child_call(db, parent, payload, alias='service'):
    key = successor_key(parent)
    effect = derive(db.roles[alias], key, 'command_reconcile')
    with contextlib.closing(db.connect(alias)) as conn:
        _, outcome = command(db, conn, alias, 'command_reconcile', payload, key=key, effect=effect)
    return effect, outcome


def commit_child(db, parent, payload, alias='service'):
    effect, outcome = child_call(db, parent, payload, alias)
    with contextlib.closing(db.connect(alias)) as conn:
        result = api(conn, effect, outcome)
        conn.commit()
    return effect, result


def expect_raise(db, effect, outcome, code='0A000'):
    with contextlib.closing(db.connect('owner')) as owner:
        before = snapshot(owner)
        owner.rollback()
    with contextlib.closing(db.connect('service')) as conn:
        sqlstate(conn, 'SELECT v24_cordis.advance(%s,%s)', (effect, Json(outcome)), code=code)
    with contextlib.closing(db.connect('owner')) as owner:
        assert snapshot(owner) == before
        owner.rollback()


def install(db, **kwargs):
    payload = declaration(**kwargs)
    effect, result, _ = commit_new(db, 'command_install', payload)
    assert result.get('disposition') == 'committed', result
    return payload, effect, result


def p0(db, fiber, expected=0):
    effect, result, outcome = commit_new(db, 'command_reconcile',
                                         reconcile_payload(fiber, 'on', expected))
    assert result.get('disposition') == 'committed', result
    return effect, result, outcome


def finish(db, parent, fiber, count, control=1):
    step, result = commit_child(db, parent, reconcile_payload(fiber, 'advance', control))
    assert result.get('disposition') == 'committed', result
    parent = step
    left = count
    batches = []
    while left:
        before = one(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id=%s AND kind=%s',
                     (fiber, 'service'))
        step, result = commit_child(db, parent, reconcile_payload(fiber, 'advance', control))
        assert result.get('disposition') == 'committed', result
        after = one(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id=%s AND kind=%s',
                    (fiber, 'service'))
        assert 1 <= after - before <= 32, (before, after)
        batches.append(after - before)
        left -= after - before
        parent = step
    step, result = commit_child(db, parent, reconcile_payload(fiber, 'advance', control))
    assert result.get('disposition') == 'committed', result
    assert result['emitted'] == [], result
    assert one(db, 'SELECT state FROM v24_cordis.episodes e JOIN v24_cordis.fibers f '
                   'ON f.current_episode_id=e.id WHERE f.id=%s', (fiber,)) == 'active'
    return parent, batches, result


def phases(db, fiber, count, control=1):
    parent, started, _ = p0(db, fiber, 0)
    assert started['emitted'], started
    return finish(db, parent, fiber, count, control)


def test_zero_and_cas(db):
    payload, _, _ = install(db)
    fiber = uuid.UUID(payload['fiber_id'])
    effect, result, outcome = p0(db, fiber)
    assert result['emitted'] == [str(derive(db.roles['service'], successor_key(effect), 'command_reconcile'))]
    assert rows(db, 'SELECT want_on,control_seq FROM v24_cordis.fibers WHERE id=%s', (fiber,)) == [(True, 1)]
    assert one(db, "SELECT count(*) FROM v24_cordis.effects WHERE fiber_id=%s AND kind='command_reconcile' "
                   "AND status IN ('ready','claimed')", (fiber,)) == 1
    event = rows(db, 'SELECT event_kind,payload FROM v24_cordis.events WHERE entity_id=%s', (fiber,))
    assert event == [('fiber_target_requested', {'want_on': True, 'control_seq': 1})]
    with contextlib.closing(db.connect('service')) as conn:
        replay = api(conn, effect, outcome)
        conn.commit()
    assert replay == result, (replay, result)
    noop_effect, noop, _ = commit_new(db, 'command_reconcile', reconcile_payload(fiber, 'on', 1))
    assert noop['disposition'] == 'committed' and noop['emitted'] == [], noop
    assert rows(db, 'SELECT event_kind,payload FROM v24_cordis.events WHERE entity_id=%s', (fiber,)) == event
    assert one(db, 'SELECT control_seq FROM v24_cordis.fibers WHERE id=%s', (fiber,)) == 1
    with contextlib.closing(db.connect('service')) as conn:
        stale, stale_out = command(db, conn, 'service', 'command_reconcile',
                                   reconcile_payload(fiber, 'on', 0))
        no_write(db, conn, stale, stale_out, 'stale_generation')
    _, batches, _ = finish(db, effect, fiber, 0)
    assert batches == []
    assert one(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id=%s', (fiber,)) == 0
    assert rows(db, "SELECT committed_view,state FROM v24_cordis.episodes WHERE fiber_id=%s",
                (fiber,)) == [({}, 'active')]
    assert one(db, "SELECT count(*) FROM v24_cordis.effects WHERE kind='host_io'") == 0
    print('[CDP2-A1] P0 CAS/no-op/replay; one ready reconcile; zero-provide active episode')
    return payload


def test_batches(db, root):
    owner = dict(fiber_id=root['fiber_id'], episode_id=str(one(
        db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s', (root['fiber_id'],))))
    scope = root['scope']['id']
    for count in (1, 32, 33):
        payload, _, _ = install(db, provides=[f'p{count}-{i:02d}' for i in range(count)],
                                owner=owner, mode='existing', existing=scope)
        fiber = uuid.UUID(payload['fiber_id'])
        _, batches, _ = phases(db, fiber, count)
        assert sum(batches) == count and all(n <= 32 for n in batches), batches
        if count == 33:
            assert batches == [32, 1], batches
        seqs = [row[0] for row in rows(db, 'SELECT seq FROM v24_cordis.contributions '
                                           'WHERE fiber_id=%s AND kind=%s ORDER BY seq', (fiber, 'service'))]
        assert seqs == list(range(count))
        kinds = [row[0] for row in rows(db, 'SELECT event_kind FROM v24_cordis.events WHERE entity_id=%s ORDER BY seq',
                                        (fiber,))]
        assert kinds[0] == 'fiber_target_requested' and kinds[1] == 'episode_begun'
        assert kinds[-1] == 'episode_activated'
        assert kinds.count('contributions_appended') == len(batches)
    print('[CDP2-A3] 1/32/33 provides batch at most 32 and seq matches provides order')


def test_dependency_retry_and_realms(db, root):
    owner = dict(fiber_id=root['fiber_id'], episode_id=str(one(
        db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s', (root['fiber_id'],))))
    scope = root['scope']['id']
    consumer, _, _ = install(db, requires=['need'], owner=owner, mode='existing', existing=scope)
    fiber = uuid.UUID(consumer['fiber_id'])
    parent, started, _ = p0(db, fiber)
    effect, outcome = child_call(db, parent, reconcile_payload(fiber, 'advance', 1))
    with contextlib.closing(db.connect('service')) as conn:
        no_write(db, conn, effect, outcome, code='dependency_unresolved',
                 detail={'reason': 'dependency_missing', 'key': 'need'})
    assert one(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (effect,)) == 'ready'
    assert one(db, 'SELECT count(*) FROM v24_cordis.requests WHERE effect_id=%s', (effect,)) == 0
    assert one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s', (fiber,)) is None
    provider, _, _ = install(db, provides=['need'], owner=owner, mode='existing', existing=scope)
    phases(db, uuid.UUID(provider['fiber_id']), 1)
    step, begun = commit_child(db, parent, reconcile_payload(fiber, 'advance', 1))
    assert step == effect and begun['disposition'] == 'committed', begun
    view = one(db, 'SELECT e.committed_view FROM v24_cordis.episodes e JOIN v24_cordis.fibers f '
                   'ON f.current_episode_id=e.id WHERE f.id=%s', (fiber,))
    assert set(view) == {'need'}
    pin = rows(db, 'SELECT key,provider_epoch,contribution_id FROM v24_cordis.pins '
                   'WHERE consumer_fiber_id=%s AND released_at IS NULL', (fiber,))
    assert pin[0][0] == 'need' and pin[0][1] == view['need']['provider_epoch']
    assert str(pin[0][2]) == view['need']['contribution_id']
    replay = commit_child(db, parent, reconcile_payload(fiber, 'advance', 1))[1]
    assert replay == begun
    assert one(db, 'SELECT count(*) FROM v24_cordis.episodes WHERE fiber_id=%s', (fiber,)) == 1
    other, _, _ = install(db, provides=['shared'], owner=owner, mode='child', parent=scope,
                          overrides={'shared': 'other'})
    phases(db, uuid.UUID(other['fiber_id']), 1)
    assert one(db, "SELECT realm FROM v24_cordis.contributions WHERE fiber_id=%s AND kind='service'",
               (other['fiber_id'],)) == 'other'
    root_provider, _, _ = install(db, provides=['shared'], owner=owner, mode='existing', existing=scope)
    phases(db, uuid.UUID(root_provider['fiber_id']), 1)
    assert one(db, "SELECT realm FROM v24_cordis.contributions WHERE fiber_id=%s AND kind='service'",
               (root_provider['fiber_id'],)) == 'root'
    child_consumer, _, _ = install(db, requires=['shared'], owner=owner, mode='child', parent=scope,
                                   overrides={'shared': 'other'})
    phases(db, uuid.UUID(child_consumer['fiber_id']), 0)
    pinned = one(db, 'SELECT c.realm FROM v24_cordis.pins p JOIN v24_cordis.contributions c '
                     'ON c.id=p.contribution_id WHERE p.consumer_fiber_id=%s',
                 (child_consumer['fiber_id'],))
    assert pinned == 'other'
    print('[CDP2-A2/A5] P1 freezes view/pin/epoch; missing provider retries once; realms do not fall back')


def test_batch_retry_and_boundaries(db, root):
    owner = dict(fiber_id=root['fiber_id'], episode_id=str(one(
        db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s', (root['fiber_id'],))))
    scope = root['scope']['id']
    keys = [f'b{i:02d}' for i in range(33)]
    payload, _, _ = install(db, provides=keys, owner=owner, mode='existing', existing=scope)
    fiber = uuid.UUID(payload['fiber_id'])
    parent, _, _ = p0(db, fiber)
    begun, _ = commit_child(db, parent, reconcile_payload(fiber, 'advance', 1))
    batched, _ = commit_child(db, begun, reconcile_payload(fiber, 'advance', 1))
    assert one(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id=%s AND kind=%s',
               (fiber, 'service')) == 32
    second = batched
    # A real declared provider occupies the last address. Adding an undeclared
    # service to the owner itself would invalidate its totality in DP3.
    competitor, _, _ = install(db, provides=[keys[32]], owner=owner, mode='existing', existing=scope)
    phases(db, uuid.UUID(competitor['fiber_id']), 1)
    effect, outcome = child_call(db, second, reconcile_payload(fiber, 'advance', 1))
    with contextlib.closing(db.connect('service')) as conn:
        result = api(conn, effect, outcome)
        assert result.get('disposition') == 'committed', (result, outcome)
        conn.commit()
    assert one(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (effect,)) == 'succeeded'
    failure = one(db, 'SELECT failure FROM v24_cordis.fibers WHERE id=%s', (fiber,))
    assert failure['code'] == 'provide_conflict' and failure['reason'] == 'address_conflict'
    assert one(db, "SELECT (iterator->>'next_index')::int FROM v24_cordis.episodes e "
                   "JOIN v24_cordis.fibers f ON f.current_episode_id=e.id WHERE f.id=%s", (fiber,)) == 32
    # The classified address conflict commits Raise atomically. Earlier 32-row
    # prefix remains, this batch contributes nothing, and the episode closes.
    assert one(db, "SELECT state FROM v24_cordis.episodes e JOIN v24_cordis.fibers f "
                   "ON f.current_episode_id=e.id WHERE f.id=%s", (fiber,)) == 'closing'
    assert one(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id=%s AND kind=%s',
               (fiber, 'service')) == 32
    with contextlib.closing(db.connect('owner')) as conn:
        before = snapshot(conn)
        conn.rollback()
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        try:
            query(conn, "INSERT INTO v24_cordis.contributions(id,fiber_id,episode_id,seq,kind,realm,key,"
                        "descriptor,inverse,contract_version) SELECT gen_random_uuid(),id,current_episode_id,99,"
                        "'service','root',%s,'{}','{\"op\":\"delete_row\"}','1' FROM v24_cordis.fibers WHERE id=%s",
                  (keys[1], fiber))
            conn.commit()
        except psycopg2.Error as exc:
            conn.rollback()
            assert exc.pgcode == '23505', exc.pgcode
        else:
            raise AssertionError('expected 23505')
    with contextlib.closing(db.connect('owner')) as conn:
        assert snapshot(conn) == before
        conn.rollback()
    print('[CDP2-A3/A4/A5] later conflict commits Raise; 32-row prefix preserved; address uniqueness retained')


def test_dag_and_owner(db, root):
    owner = dict(fiber_id=root['fiber_id'], episode_id=str(one(
        db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s', (root['fiber_id'],))))
    scope = root['scope']['id']
    child, _, _ = install(db, owner=owner, mode='existing', existing=scope)
    cycle = one(db, 'SELECT v24_cordis.activation_dag(%s::uuid,%s::uuid[])',
                (root['fiber_id'], [child['fiber_id']]))
    assert cycle['code'] == 'cleanup_cycle', cycle
    provided, _, _ = install(db, provides=['owner.svc'], owner=owner, mode='existing', existing=scope)
    phases(db, uuid.UUID(provided['fiber_id']), 1)
    dependent, _, _ = install(db, requires=['owner.svc'], owner=dict(
        fiber_id=provided['fiber_id'], episode_id=str(one(
            db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s', (provided['fiber_id'],)))),
        mode='existing', existing=scope)
    phases(db, uuid.UUID(dependent['fiber_id']), 0)
    episode = one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s', (dependent['fiber_id'],))
    with contextlib.closing(db.connect('owner')) as conn:
        before = snapshot(conn)
        conn.rollback()
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        try:
            query(conn, "UPDATE v24_cordis.episodes SET committed_view='{\"x\":1}' WHERE id=%s", (episode,))
            conn.commit()
        except psycopg2.Error as exc:
            conn.rollback()
            assert exc.pgcode == '55000', exc.pgcode
        else:
            raise AssertionError('expected immutable view')
    with contextlib.closing(db.connect('owner')) as conn:
        assert snapshot(conn) == before
        conn.rollback()
    print('[CDP2-A6] real owner admission, no false cycle, committed view immutable, direct cycle proof')


def main():
    with Server() as server, TestDB(server) as db:
        root = test_zero_and_cas(db)
        test_batches(db, root)
        test_dependency_retry_and_realms(db, root)
        test_batch_retry_and_boundaries(db, root)
        test_dag_and_owner(db, root)
    print('[passed] CDP2-A')


if __name__ == '__main__':
    main()
