"""CDP2-K: W1 executable reconcile continuation, typed deltas, closure, receipts and events.

Every test runs on a disposable server/database. Production interpreters stay at their W1
unsupported seam; only interpret_command is replaced by a session-GUC probe. The validator,
applier, triggers and advance entry point are always the production SQL.
"""
from __future__ import annotations
import contextlib
import json
import sys
import threading
import time
import uuid
from pathlib import Path

# Exact DP1 directory before fixture imports; test_support is not the path bootstrap.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dp1'))

import psycopg2
from psycopg2 import sql
from psycopg2.extras import Json

from test_support import (Server, TestDB, TABLES, snapshot, query, api, principal, derive,
                          successor_key, command, install_payload, reconcile_payload,
                          dispose_payload, sqlstate, no_write, install_probe, set_probe,
                          set_probe_raise, delta, successor, event, seed_fiber, seed_episode,
                          seed_provider, seed_parent, seed_child, install_delta, active_owner)


def scalar(db, statement, params=()):
    with contextlib.closing(db.connect('owner')) as owner:
        return query(owner, statement, params)[0][0]


def rows(db, statement, params=()):
    with contextlib.closing(db.connect('owner')) as owner:
        return query(owner, statement, params)


def bad(result, code, reason=None):
    assert result.get('error', {}).get('code') == code, result
    if reason is not None:
        assert result['error']['detail'].get('reason') == reason, result
    return result


def ok(result, disposition='committed'):
    assert result.get('disposition') == disposition, result
    return result


def run_new(db, kind, payload, body, alias='service', key=None):
    with contextlib.closing(db.connect(alias)) as conn:
        effect, out = command(db, conn, alias, kind, payload, key=key)
        set_probe(conn, body)
        set_probe_raise(conn, False)
        result = api(conn, effect, out)
        conn.commit()
    return effect, result


def run_cont(db, parent, payload, body, alias='service', ordinal=0, child=None, key=None):
    key = key or successor_key(parent, ordinal)
    child = child or derive(db.roles[alias], key, 'command_reconcile')
    with contextlib.closing(db.connect(alias)) as conn:
        effect, out = command(db, conn, alias, 'command_reconcile', payload, key=key, effect=child)
        set_probe(conn, body)
        set_probe_raise(conn, False)
        result = api(conn, effect, out)
        conn.commit()
    return child, result, key


def p0_fixture(db, prefix, want_on=False, control_seq=0):
    f = seed_fiber(db, want_on=want_on, control_seq=control_seq, prefix=prefix)
    parent, _ = seed_parent(db, 'command_reconcile', reconcile_payload(f['fiber'], 'on', control_seq),
                            fiber=f['fiber'])
    payload = reconcile_payload(f['fiber'], 'advance', control_seq)
    child, key = seed_child(db, parent, f['fiber'], payload)
    return dict(fiber=f['fiber'], scope=f['scope'], parent=parent, payload=payload,
                child=child, key=key)


def p1_fixture(db, prefix, control_seq=1, expected=None):
    f = seed_fiber(db, want_on=True, control_seq=control_seq, prefix=prefix)
    parent, _ = seed_parent(db, 'command_reconcile', reconcile_payload(f['fiber'], 'on', control_seq),
                            fiber=f['fiber'])
    expected = control_seq if expected is None else expected
    payload = reconcile_payload(f['fiber'], 'advance', expected)
    child, key = seed_child(db, parent, f['fiber'], payload)
    return dict(fiber=f['fiber'], scope=f['scope'], parent=parent, payload=payload,
                child=child, key=key)


def p2_fixture(db, prefix, expected=None, provides=('a',)):
    f = seed_fiber(db, provides=provides, want_on=True, control_seq=1, prefix=prefix)
    episode = seed_episode(db, f['fiber'], epoch=1, state='reloading', control_seq=1,
                           next_index=0, registered=-1)
    parent, _ = seed_parent(db, 'command_reconcile', reconcile_payload(f['fiber'], 'on', 1),
                            fiber=f['fiber'])
    expected = 1 if expected is None else expected
    payload = reconcile_payload(f['fiber'], 'advance', expected)
    child, key = seed_child(db, parent, f['fiber'], payload, episode=episode)
    return dict(fiber=f['fiber'], scope=f['scope'], parent=parent, payload=payload,
                child=child, key=key, episode=episode)


def p1_body(fiber, episode, control=1):
    return delta(
        domain=[dict(op='episode_begin', id=str(episode), fiber_id=str(fiber), epoch=1,
                     committed_view={}, iterator=dict(v=1, next_index=0, registered_through=-1,
                                                       control_seq=control), pins=[])],
        events=[event('fiber', fiber, 'episode_begun',
                      dict(episode_id=str(episode), epoch=1, control_seq=control,
                           require_keys=[], pin_ids=[]))],
        successors=[successor(fiber, control)])


def test_lifecycle(db):
    install_probe(db)
    f = seed_fiber(db, provides=('a', 'b'))
    p0 = reconcile_payload(f['fiber'], 'on', 0)
    parent, r0 = run_new(db, 'command_reconcile', p0, delta(
        domain=[dict(op='fiber_control', fiber_id=str(f['fiber']), want_on=True, control_seq=1)],
        events=[event('fiber', f['fiber'], 'fiber_target_requested',
                      dict(want_on=True, control_seq=1))],
        successors=[successor(f['fiber'], 1)]))
    ok(r0)
    child0 = derive(db.roles['service'], successor_key(parent, 0), 'command_reconcile')
    assert r0['emitted'] == [str(child0)], r0
    assert scalar(db, 'SELECT count(*) FROM v24_cordis.requests WHERE effect_id=%s', (child0,)) == 0
    assert scalar(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (child0,)) == 'ready'

    episode = uuid.uuid4()
    p1 = reconcile_payload(f['fiber'], 'advance', 1)
    child1, r1, key1 = run_cont(db, parent, p1, p1_body(f['fiber'], episode))
    ok(r1)
    assert child1 == child0
    assert r1['emitted'] == [str(derive(db.roles['service'], successor_key(child0, 0),
                                        'command_reconcile'))], r1
    assert scalar(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (child0,)) == 'succeeded'
    assert scalar(db, 'SELECT count(*) FROM v24_cordis.requests WHERE effect_id=%s', (child0,)) == 1
    assert scalar(db, 'SELECT count(*) FROM v24_cordis.events WHERE effect_id=%s', (child0,)) == 1
    assert scalar(db, 'SELECT state FROM v24_cordis.episodes WHERE id=%s', (episode,)) == 'reloading'
    assert scalar(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s',
                  (f['fiber'],)) == episode
    before = list(rows(db, 'SELECT id,status,attempt,fence FROM v24_cordis.effects ORDER BY id'))
    before_req = scalar(db, 'SELECT count(*) FROM v24_cordis.requests')
    with contextlib.closing(db.connect('service')) as conn:
        effect, out = command(db, conn, 'service', 'command_reconcile', p1, key=key1, effect=child0)
        replay = api(conn, effect, out)
        conn.commit()
    assert replay == r1, (replay, r1)
    assert rows(db, 'SELECT id,status,attempt,fence FROM v24_cordis.effects ORDER BY id') == before
    assert scalar(db, 'SELECT count(*) FROM v24_cordis.requests') == before_req

    c0, c1 = uuid.uuid4(), uuid.uuid4()
    p2 = reconcile_payload(f['fiber'], 'advance', 1)
    p2_body = delta(
        domain=[dict(op='contribution_append', id=str(c0), fiber_id=str(f['fiber']),
                     episode_id=str(episode), seq=0, kind='service', realm='root', key='a',
                     descriptor={}, prev_contribution_id=None,
                     inverse=dict(op='delete_row'), contract_version='1'),
                dict(op='contribution_append', id=str(c1), fiber_id=str(f['fiber']),
                     episode_id=str(episode), seq=1, kind='service', realm='root', key='b',
                     descriptor={}, prev_contribution_id=None,
                     inverse=dict(op='delete_row'), contract_version='1'),
                dict(op='episode_progress', episode_id=str(episode), next_index=2, registered_through=1)],
        events=[event('fiber', f['fiber'], 'contributions_appended',
                      dict(episode_id=str(episode), contribution_ids=[str(c0), str(c1)],
                           seq_from=0, seq_through=1, next_index=2))],
        successors=[successor(f['fiber'], 1)])
    child2, r2, key2 = run_cont(db, child0, p2, p2_body)
    ok(r2)
    assert scalar(db, 'SELECT (iterator->>\'next_index\')::int FROM v24_cordis.episodes WHERE id=%s',
                  (episode,)) == 2

    p4 = reconcile_payload(f['fiber'], 'advance', 1)
    child3, r3, key3 = run_cont(db, child2, p4, delta(
        domain=[dict(op='episode_activate', episode_id=str(episode))],
        events=[event('fiber', f['fiber'], 'episode_activated',
                      dict(episode_id=str(episode), epoch=1))]))
    ok(r3)
    assert r3['emitted'] == []
    assert scalar(db, 'SELECT state FROM v24_cordis.episodes WHERE id=%s', (episode,)) == 'active'
    assert [x[0] for x in rows(db, "SELECT seq FROM v24_cordis.events WHERE entity_type='fiber' "
                                   'AND entity_id=%s ORDER BY seq', (f['fiber'],))] == [0, 1, 2, 3]
    print('[CDP2-K2] ready child has no request; one execution writes request/event/successor; replay is exact')

    noop = reconcile_payload(f['fiber'], 'on', 1)
    noop_effect, noop_result = run_new(db, 'command_reconcile', noop, delta())
    ok(noop_result)
    assert noop_result['emitted'] == []
    assert scalar(db, 'SELECT count(*) FROM v24_cordis.events WHERE effect_id=%s',
                  (noop_effect,)) == 0

    owner_root = f['root']
    root_owner = dict(fiber_id=str(owner_root['fiber']), episode_id=str(owner_root['episode']))
    root = install_payload(mode='existing', existing_scope=owner_root['scope'], owner=root_owner)
    root_effect, root_result = run_new(db, 'command_install', root, install_delta(db, root))
    ok(root_result)
    assert scalar(db, 'SELECT fiber_id FROM v24_cordis.effects WHERE id=%s',
                  (root_effect,)) == owner_root['fiber']
    assert scalar(db, 'SELECT episode_id FROM v24_cordis.effects WHERE id=%s',
                  (root_effect,)) == owner_root['episode']
    assert scalar(db, 'SELECT state FROM v24_cordis.installs WHERE id=%s',
                  (root['install_id'],)) == 'installed'
    assert rows(db, "SELECT seq,event_kind,payload FROM v24_cordis.events WHERE effect_id=%s",
                (root_effect,))[0][:2] == (0, 'install_created')
    assert scalar(db, 'SELECT owner_id FROM v24_cordis.fibers WHERE id=%s',
                  (root['fiber_id'],)) == owner_root['fiber']

    existing = seed_fiber(db, prefix='existing')
    existing_payload = install_payload(mode='existing', existing_scope=existing['scope'],
                                        owner=root_owner)
    existing_effect, existing_result = run_new(db, 'command_install', existing_payload,
                                                install_delta(db, existing_payload))
    ok(existing_result)
    assert scalar(db, 'SELECT count(*) FROM v24_cordis.scopes WHERE id=%s',
                  (existing_payload['scope']['id'],)) == 1

    second = uuid.uuid4()
    with contextlib.closing(db.connect('owner')) as owner:
        query(owner, 'INSERT INTO v24_cordis.fibers(id,install_id,owner_id,owner_episode_id,'
                     'scope_id) VALUES(%s,%s,%s,%s,%s)',
              (second, root['install_id'], owner_root['fiber'], owner_root['episode'],
               root['scope']['id']))
        owner.commit()
    fibers = sorted(str(x[0]) for x in rows(db, 'SELECT id FROM v24_cordis.fibers '
                                                 'WHERE install_id=%s', (root['install_id'],)))
    with contextlib.closing(db.connect('owner')) as owner:
        query(owner, "UPDATE v24_cordis.fibers SET dispose_requested_at='2020-01-01 00:00:00+00', "
                     "disposed_at='2020-01-02 00:00:00+00' WHERE id=%s", (root['fiber_id'],))
        owner.commit()
    dispose = dispose_payload(root['install_id'])
    dispose_effect, dispose_result = run_new(db, 'command_dispose', dispose, delta(
        domain=[dict(op='basic_dispose', install_id=root['install_id'], fiber_ids=fibers)],
        events=[event('install', root['install_id'], 'install_disposed', dict(fiber_ids=fibers))]))
    ok(dispose_result)
    assert scalar(db, 'SELECT count(*) FROM v24_cordis.fibers WHERE install_id=%s '
                      'AND disposed_at IS NULL', (root['install_id'],)) == 0
    assert scalar(db, "SELECT dispose_requested_at='2020-01-01 00:00:00+00' AND "
                      "disposed_at='2020-01-02 00:00:00+00' FROM v24_cordis.fibers WHERE id=%s",
                  (root['fiber_id'],)) is True
    assert scalar(db, 'SELECT disposed_at IS NOT NULL FROM v24_cordis.fibers WHERE id=%s',
                  (second,)) is True
    assert scalar(db, 'SELECT state FROM v24_cordis.installs WHERE id=%s',
                  (root['install_id'],)) == 'disposed'
    print('[CDP2-K2] dispose preserves already-tombstoned timestamps and stamps fresh fibers')

    pf = seed_fiber(db, requires=('svc',), prefix='pinned')
    provider = seed_provider(db)
    pp0 = reconcile_payload(pf['fiber'], 'on', 0)
    pparent, pr0 = run_new(db, 'command_reconcile', pp0, delta(
        domain=[dict(op='fiber_control', fiber_id=str(pf['fiber']), want_on=True, control_seq=1)],
        events=[event('fiber', pf['fiber'], 'fiber_target_requested',
                      dict(want_on=True, control_seq=1))],
        successors=[successor(pf['fiber'], 1)]))
    ok(pr0)
    pepisode, pinid = uuid.uuid4(), uuid.uuid4()
    binding = dict(contribution_id=str(provider['contribution']),
                   provider_fiber_id=str(provider['fiber']),
                   provider_episode_id=str(provider['episode']),
                   provider_epoch=provider['epoch'],
                   descriptor_digest=provider['digest'], contract_version='1')
    pp1 = reconcile_payload(pf['fiber'], 'advance', 1)
    pp1_body = delta(
        domain=[dict(op='episode_begin', id=str(pepisode), fiber_id=str(pf['fiber']), epoch=1,
                     committed_view={provider['key']: binding},
                     iterator=dict(v=1, next_index=0, registered_through=-1, control_seq=1),
                     pins=[dict(id=str(pinid), key=provider['key'],
                                contribution_id=str(provider['contribution']),
                                provider_episode_id=str(provider['episode']),
                                provider_epoch=provider['epoch'])])],
        events=[event('fiber', pf['fiber'], 'episode_begun',
                      dict(episode_id=str(pepisode), epoch=1, control_seq=1,
                           require_keys=[provider['key']], pin_ids=[str(pinid)]))],
        successors=[successor(pf['fiber'], 1)])
    _, pr1, _ = run_cont(db, pparent, pp1, pp1_body)
    ok(pr1)
    assert scalar(db, 'SELECT key FROM v24_cordis.pins WHERE id=%s', (pinid,)) == provider['key']
    assert scalar(db, 'SELECT committed_view FROM v24_cordis.episodes WHERE id=%s',
                  (pepisode,)) == {provider['key']: binding}

    return dict(fiber=f['fiber'], scope=f['scope'], child0=child0, child1=child1, child2=child2,
                child3=child3, episode=episode, p4=p4, p4_key=key3, p4_result=r3, root=root,
                root_effect=root_effect, dispose_effect=dispose_effect, dispose_fibers=fibers,
                c0=c0, c1=c1, pinid=pinid, pepisode=pepisode, noop_effect=noop_effect,
                owner_root=owner_root)


def block(conn, sqltext, params=()):
    query(conn, sqltext, params)


def wait_blocked(db, pid):
    deadline = time.monotonic() + 4
    with contextlib.closing(db.connect()) as monitor:
        while time.monotonic() < deadline:
            if query(monitor, 'SELECT cardinality(pg_blocking_pids(%s))', (pid,))[0][0] > 0:
                return
            monitor.rollback()
            time.sleep(.01)
    raise AssertionError('caller never waited at expected lock')


def test_locks(db, replay_db, ctx):
    f = seed_fiber(db, want_on=True, control_seq=1, prefix='lock')
    parent, _ = seed_parent(db, 'command_reconcile', reconcile_payload(f['fiber'], 'on', 0),
                            fiber=f['fiber'])
    payload = reconcile_payload(f['fiber'], 'advance', 1)
    child, key = seed_child(db, parent, f['fiber'], payload)
    with contextlib.closing(db.connect('service')) as setup:
        effect, out = command(db, setup, 'service', 'command_reconcile', payload, key=key,
                              effect=child)
        setup.commit()

    def blocked_until(statement, params, checks):
        result = []
        with contextlib.closing(db.connect('owner')) as blocker, \
             contextlib.closing(db.connect('service')) as caller, \
             contextlib.closing(db.connect('owner')) as monitor:
            block(blocker, statement, params)
            pid = caller.get_backend_pid()

            def call():
                try:
                    result.append(api(caller, effect, out))
                    caller.commit()
                except BaseException as exc:
                    caller.rollback()
                    result.append(exc)

            thread = threading.Thread(target=call)
            thread.start()
            try:
                wait_blocked(db, pid)
                checks(monitor, pid)
            finally:
                blocker.rollback()
                thread.join(6)
            assert not thread.is_alive()
        assert len(result) == 1 and isinstance(result[0], psycopg2.Error), result
        assert result[0].pgcode == '0A000', result

    # G before target: while the caller waits at G, the child row is freely lockable.
    blocked_until('SELECT pg_advisory_xact_lock(24,1)', (),
                  lambda m, pid: (query(m, 'SELECT id FROM v24_cordis.effects WHERE id=%s '
                                           'FOR UPDATE NOWAIT', (child,)), m.rollback()))
    # Target before closure scope: the caller waits at the continuation row and has not
    # reached the scope yet.
    blocked_until('SELECT id FROM v24_cordis.effects WHERE id=%s FOR UPDATE', (child,),
                  lambda m, pid: (query(m, 'SELECT id FROM v24_cordis.scopes WHERE id=%s '
                                           'FOR UPDATE NOWAIT', (f['scope'],)), m.rollback()))
    # Scope is the first closure target after the target: the caller already holds the child.
    blocked_until('SELECT id FROM v24_cordis.scopes WHERE id=%s FOR UPDATE', (f['scope'],),
                  lambda m, pid: (sqlstate(m, 'SELECT id FROM v24_cordis.effects WHERE id=%s '
                                              'FOR UPDATE NOWAIT', (child,), code='55P03'),
                                  m.rollback()))

    # Replay is decided before closure: a locked scope cannot delay an exact replay.
    with contextlib.closing(replay_db.connect('owner')) as blocker, \
         contextlib.closing(replay_db.connect('service')) as caller:
        query(blocker, 'SELECT id FROM v24_cordis.scopes WHERE id=%s FOR UPDATE', (ctx['scope'],))
        query(caller, "SELECT set_config('lock_timeout','200ms',false)")
        start = time.monotonic()
        effect, out = command(replay_db, caller, 'service', 'command_reconcile', ctx['p4'],
                              key=ctx['p4_key'], effect=ctx['child3'])
        got = api(caller, effect, out)
        caller.commit()
        blocker.rollback()
        elapsed = time.monotonic() - start
    assert got == ctx['p4_result'], (got, ctx['p4_result'])
    assert elapsed < 1.5, elapsed
    print('[CDP2-K1] G->target->scope closure order; replay bypasses locked closure')


def test_identity(db):
    def attempt(fixture, payload=None, alias='service', effect=None, key=None):
        payload = fixture['payload'] if payload is None else payload
        effect = fixture['child'] if effect is None else effect
        key = fixture['key'] if key is None else key
        with contextlib.closing(db.connect(alias)) as conn:
            e, out = command(db, conn, alias, 'command_reconcile', payload, key=key,
                             effect=effect)
            result = api(conn, e, out)
            conn.rollback()
        return result

    fixture = p0_fixture(db, 'id-derived')
    bad(attempt(fixture, effect=uuid.uuid4()), 'effect_id_conflict')
    ghost_key = successor_key(uuid.uuid4(), 0)
    bad(attempt(fixture, key=ghost_key,
                effect=derive(db.roles['service'], ghost_key, 'command_reconcile')),
        'not_found_or_denied')
    bad(attempt(fixture, alias='operator'), 'effect_id_conflict')
    # Frozen input and actor are part of the continuation identity.
    bad(attempt(fixture, payload={**fixture['payload'], 'expected_control_seq': 1}),
        'effect_id_conflict', 'continuation_identity')
    other = seed_fiber(db, prefix='id-binding')
    bad(attempt(fixture, payload={**fixture['payload'], 'fiber_id': str(other['fiber'])}),
        'effect_id_conflict')
    # Parent must be a succeeded reconcile with the same actor (terminal failure is not enough).
    pf = seed_fiber(db, want_on=True, control_seq=1, prefix='id-parent')
    pparent, _ = seed_parent(db, 'command_reconcile', reconcile_payload(pf['fiber'], 'on', 1),
                             fiber=pf['fiber'], status='failed')
    ppayload = reconcile_payload(pf['fiber'], 'advance', 1)
    pchild, pkey = seed_child(db, pparent, pf['fiber'], ppayload)
    bad(attempt(dict(payload=ppayload, child=pchild, key=pkey)), 'effect_id_conflict',
        'continuation_parent')
    # A child may not be rebound to a different fiber under the same succeeded parent.
    xf1 = seed_fiber(db, want_on=True, control_seq=1, prefix='id-xf1')
    xp, _ = seed_parent(db, 'command_reconcile', reconcile_payload(xf1['fiber'], 'on', 1),
                        fiber=xf1['fiber'])
    xf2 = seed_fiber(db, want_on=True, control_seq=1, prefix='id-xf2')
    xp2 = reconcile_payload(xf2['fiber'], 'advance', 1)
    xc, xk = seed_child(db, xp, xf2['fiber'], xp2)
    with contextlib.closing(db.connect('service')) as conn:
        e, out = command(db, conn, 'service', 'command_reconcile', xp2, key=xk, effect=xc)
        set_probe(conn, p1_body(xf2['fiber'], uuid.uuid4()))
        bad(api(conn, e, out), 'effect_id_conflict', 'continuation_parent')
        conn.rollback()
    # A non-NULL child episode must be the open current episode of the bound fiber.
    def episode_binding_case(prefix, close):
        ef = seed_fiber(db, want_on=True, control_seq=1, prefix=prefix)
        ep = seed_episode(db, ef['fiber'], epoch=1, state='reloading', control_seq=1)
        epar, _ = seed_parent(db, 'command_reconcile', reconcile_payload(ef['fiber'], 'on', 1),
                              fiber=ef['fiber'])
        epayload = reconcile_payload(ef['fiber'], 'advance', 1)
        echild, ekey = seed_child(db, epar, ef['fiber'], epayload, episode=ep)
        with contextlib.closing(db.connect('owner')) as owner:
            query(owner, 'UPDATE v24_cordis.fibers SET current_episode_id=NULL WHERE id=%s',
                  (ef['fiber'],))
            if close:
                query(owner, 'UPDATE v24_cordis.episodes SET closed_at=now() WHERE id=%s', (ep,))
            owner.commit()
        with contextlib.closing(db.connect('service')) as conn:
            e, out = command(db, conn, 'service', 'command_reconcile', epayload, key=ekey,
                             effect=echild)
            no_write(db, conn, e, out, code='effect_id_conflict',
                     detail={'reason': 'continuation_binding'})

    episode_binding_case('id-ep-closed', True)
    episode_binding_case('id-ep-drift', False)
    print('[CDP2-K2] child non-NULL episode closed/not-current -> effect_id_conflict/continuation_binding, zero write')
    # Claimed child is not admitted.
    claimed = p0_fixture(db, 'id-claimed')
    with contextlib.closing(db.connect('owner')) as owner:
        query(owner, "UPDATE v24_cordis.effects SET status='claimed',attempt=1,fence=1,"
                     "claim_owner=%s,lease_until=now()+interval '1 minute' WHERE id=%s",
              (db.roles['service'], claimed['child']))
        owner.commit()
    bad(attempt(claimed), 'effect_id_conflict')
    # Ordinal 1 is a legal successor slot; ordinal 16 is outside the reserved key shape.
    of = seed_fiber(db, want_on=True, control_seq=1, prefix='id-ordinal')
    oparent, _ = seed_parent(db, 'command_reconcile', reconcile_payload(of['fiber'], 'on', 1),
                             fiber=of['fiber'])
    opayload = reconcile_payload(of['fiber'], 'advance', 1)
    legal = seed_child(db, oparent, of['fiber'], opayload, ordinal=1)
    with contextlib.closing(db.connect('service')) as conn:
        key = successor_key(oparent, 1)
        e, out = command(db, conn, 'service', 'command_reconcile', opayload, key=key,
                         effect=legal[0])
        oepisode = uuid.uuid4()
        set_probe(conn, p1_body(of['fiber'], oepisode, 1))
        result = api(conn, e, out)
        conn.commit()
    ok(result)
    assert result['emitted'] == [str(derive(db.roles['service'], successor_key(legal[0], 0),
                                           'command_reconcile'))]
    with contextlib.closing(db.connect('service')) as conn:
        key16 = successor_key(oparent, 16)
        e, out = command(db, conn, 'service', 'command_reconcile', opayload, key=key16,
                         effect=derive(db.roles['service'], key16, 'command_reconcile'))
        bad(api(conn, e, out), 'invalid_args', 'reserved_key_shape')
        conn.rollback()
    print('[CDP2-K3] forged derivation/actor/parent/input/binding and non-ready child rejected')


def test_typed(db):
    gold = {
        'scope_create': dict(op='scope_create', id=str(uuid.uuid4()), parent_id=None, realm_overrides={}),
        'install_create': dict(op='install_create', id=str(uuid.uuid4()), scope_id=str(uuid.uuid4()),
                               owner_fiber_id=None, owner_episode_id=None, identity='i', version='1',
                               manifest=dict(requires=[], provides=[], priority=0, check={}),
                               artifact_digest='a' * 64, contracts={}, policy_ref=None, overlay={}),
        'fiber_create': dict(op='fiber_create', id=str(uuid.uuid4()), install_id=str(uuid.uuid4()),
                             owner_id=None, owner_episode_id=None, scope_id=str(uuid.uuid4())),
        'fiber_control': dict(op='fiber_control', fiber_id=str(uuid.uuid4()), want_on=True, control_seq=1),
        'episode_begin': dict(op='episode_begin', id=str(uuid.uuid4()), fiber_id=str(uuid.uuid4()),
                              epoch=1, committed_view={}, iterator=dict(v=1, next_index=0,
                              registered_through=-1, control_seq=1), pins=[]),
        'contribution_append': dict(op='contribution_append', id=str(uuid.uuid4()),
                                    fiber_id=str(uuid.uuid4()), episode_id=str(uuid.uuid4()), seq=0,
                                    kind='service', realm='root', key='k', descriptor={},
                                    prev_contribution_id=None, inverse=dict(op='delete_row'),
                                    contract_version='1'),
        'episode_progress': dict(op='episode_progress', episode_id=str(uuid.uuid4()), next_index=1,
                                 registered_through=0),
        'episode_activate': dict(op='episode_activate', episode_id=str(uuid.uuid4())),
        'basic_dispose': dict(op='basic_dispose', install_id=str(uuid.uuid4()), fiber_ids=[]),
    }
    base = delta()
    with contextlib.closing(db.connect('owner')) as owner:
        def check(d, structure=True):
            return query(owner, "SELECT v24_cordis.validate_delta(%s,'command',%s)",
                         (Json(d), structure))[0][0]
        for name, item in gold.items():
            assert check({**base, 'domain': [item]}, True) is None, name
            assert check({**base, 'domain': [item]}, False) is None, name
            for key in list(item)[1:3]:
                got = check({**base, 'domain': [{k: v for k, v in item.items() if k != key}]})
                assert got['error']['code'] == 'invalid_outcome', (name, key)
            assert check({**base, 'domain': [{**item, 'extra': 1}]})['error']['code'] == 'invalid_outcome', name
        for item in ({**gold['fiber_control'], 'want_on': 'true'},
                     {**gold['fiber_control'], 'control_seq': '1'},
                     {**gold['scope_create'], 'id': None},
                     {**gold['episode_begin'], 'pins': {}},
                     {**gold['contribution_append'], 'inverse': {'op': 'sql'}},
                     {**gold['episode_progress'], 'next_index': '1'}):
            assert check({**base, 'domain': [item]})['error']['code'] == 'invalid_outcome', item
        pc, pe, pfb = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        pin = {'id': str(uuid.uuid4()), 'key': 'k', 'contribution_id': str(pc),
               'provider_episode_id': str(pe), 'provider_epoch': 1}
        binding = {'contribution_id': str(pc), 'provider_fiber_id': str(pfb),
                   'provider_episode_id': str(pe), 'provider_epoch': 1,
                   'descriptor_digest': 'a' * 64, 'contract_version': '1'}
        assert check({**base, 'domain': [{**gold['episode_begin'],
                    'committed_view': {'k': binding}, 'pins': [pin]}]}) is None
        assert check({**base, 'domain': [{**gold['episode_begin'], 'pins': [pin]}]}
                     )['error']['code'] == 'invalid_outcome'
        assert check({**base, 'successors': [{'ordinal': 0, 'kind': 'host_io', 'input': {}}]}) is None
        assert check({**base, 'successors': [{'ordinal': 0, 'kind': 'command_reconcile',
                                              'input': {}}]})['error']['code'] == 'invalid_outcome'
        assert check({**base, 'successors': [{'ordinal': 16, 'kind': 'host_io', 'input': {}}]}
                     )['error']['code'] == 'invalid_outcome'
        assert check({**base, 'domain': [gold['contribution_append'],
                                         gold['contribution_append']]}
                     )['error']['code'] == 'invalid_outcome'
        evs = {
            'install_created': event('install', uuid.uuid4(), 'install_created', dict(
                scope_id=str(uuid.uuid4()), scope_created=True, fiber_id=str(uuid.uuid4()),
                owner_fiber_id=None, owner_episode_id=None, child_contribution_id=None)),
            'fiber_target_requested': event('fiber', uuid.uuid4(), 'fiber_target_requested',
                                            dict(want_on=True, control_seq=1)),
            'episode_begun': event('fiber', uuid.uuid4(), 'episode_begun', dict(
                episode_id=str(uuid.uuid4()), epoch=1, control_seq=1,
                require_keys=[], pin_ids=[])),
            'contributions_appended': event('fiber', uuid.uuid4(), 'contributions_appended', dict(
                episode_id=str(uuid.uuid4()), contribution_ids=[str(uuid.uuid4())],
                seq_from=0, seq_through=0, next_index=1)),
            'episode_activated': event('fiber', uuid.uuid4(), 'episode_activated',
                                        dict(episode_id=str(uuid.uuid4()), epoch=1)),
            'install_disposed': event('install', uuid.uuid4(), 'install_disposed',
                                       dict(fiber_ids=[str(uuid.uuid4())])),
        }
        bads = {
            'install_created': [dict(scope_id=None), dict(scope_created='true'), dict(owner_fiber_id='x')],
            'fiber_target_requested': [dict(want_on=None), dict(control_seq='1')],
            'episode_begun': [dict(episode_id=None), dict(epoch='1'), dict(require_keys=[None]), dict(pin_ids=['x'])],
            'contributions_appended': [dict(episode_id=None), dict(seq_from='0'), dict(contribution_ids=[None])],
            'episode_activated': [dict(episode_id=None), dict(epoch='1')],
            'install_disposed': [dict(fiber_ids=None), dict(fiber_ids=['x'])],
        }
        for kind, ev in evs.items():
            assert check(delta(events=[ev])) is None, kind
            for patch in bads[kind]:
                bad_ev = {**ev, 'payload': {**ev['payload'], **patch}}
                assert check(delta(events=[bad_ev]))['error']['code'] == 'invalid_outcome', (kind, patch)
        print('[CDP2-K4] six event variants reject null/wrong scalar types in validate_delta')
        owner.rollback()

    # A lifecycle successor must be command_reconcile/ordinal 0 with exact input before DML.
    sf = p1_fixture(db, 'typed-su')
    sbad = p1_body(sf['fiber'], uuid.uuid4())
    sbad['successors'] = [dict(ordinal=0, kind='host_io', input={})]
    with contextlib.closing(db.connect('owner')) as owner:
        before = snapshot(owner)
        owner.rollback()
    with contextlib.closing(db.connect('service')) as conn:
        e, out = command(db, conn, 'service', 'command_reconcile', sf['payload'], key=sf['key'],
                         effect=sf['child'])
        set_probe(conn, sbad)
        bad(api(conn, e, out), 'invalid_outcome', 'successor_kind')
        conn.rollback()
    with contextlib.closing(db.connect('owner')) as owner:
        assert snapshot(owner) == before
        owner.rollback()
    # P2 branch refuses P0/P1 domain ops; a P1 child refuses a cross-fiber episode_begin
    # before any episode insert (the trigger would raise U0009 if validation missed it).
    p2 = p2_fixture(db, 'typed-p2')
    with contextlib.closing(db.connect('service')) as conn:
        e, out = command(db, conn, 'service', 'command_reconcile', p2['payload'], key=p2['key'],
                         effect=p2['child'])
        set_probe(conn, delta(domain=[dict(op='fiber_control', fiber_id=str(p2['fiber']),
                                           want_on=True, control_seq=2)]))
        assert api(conn, e, out)['error']['code'] == 'invalid_outcome'
        conn.rollback()
    # A fresh no-episode child for the cross-fiber episode_begin precheck.
    f = seed_fiber(db, want_on=True, control_seq=1, prefix='typed-p1b')
    parent, _ = seed_parent(db, 'command_reconcile', reconcile_payload(f['fiber'], 'on', 1),
                            fiber=f['fiber'])
    payload = reconcile_payload(f['fiber'], 'advance', 1)
    child, key = seed_child(db, parent, f['fiber'], payload)
    other = seed_fiber(db, prefix='typed-other')
    new_ep = uuid.uuid4()
    wrong = p1_body(f['fiber'], new_ep)
    wrong['domain'] = [dict(op='episode_begin', id=str(new_ep), fiber_id=str(other['fiber']),
                            epoch=1, committed_view={}, iterator=dict(v=1, next_index=0,
                            registered_through=-1, control_seq=1), pins=[])]
    with contextlib.closing(db.connect('owner')) as owner:
        query(owner, sql.SQL('SET ROLE {}').format(sql.Identifier(db.groups['owner'])))
        query(owner, """CREATE FUNCTION v24_cordis.w1_no_dml() RETURNS trigger LANGUAGE plpgsql AS $$
          BEGIN RAISE EXCEPTION 'domain DML reached' USING ERRCODE='U0009'; END $$;
          CREATE TRIGGER w1_no_dml BEFORE INSERT ON v24_cordis.episodes FOR EACH ROW
          EXECUTE FUNCTION v24_cordis.w1_no_dml();""")
        owner.commit()
    try:
        with contextlib.closing(db.connect('service')) as conn:
            e, out = command(db, conn, 'service', 'command_reconcile', payload, key=key,
                             effect=child)
            set_probe(conn, wrong)
            got = api(conn, e, out)
            bad(got, 'invalid_outcome', 'p1_context')
            conn.rollback()
    finally:
        with contextlib.closing(db.connect('owner')) as owner:
            query(owner, 'DROP TRIGGER w1_no_dml ON v24_cordis.episodes')
            query(owner, 'DROP FUNCTION v24_cordis.w1_no_dml()')
            owner.commit()
    print('[CDP2-K4] nine typed ops closed shapes; branch/cross-fiber denial before domain DML')


def test_faults(db):
    with contextlib.closing(db.connect('owner')) as owner:
        query(owner, sql.SQL('SET ROLE {}').format(sql.Identifier(db.groups['owner'])))
        query(owner, """CREATE FUNCTION v24_cordis.w1_fault() RETURNS trigger LANGUAGE plpgsql AS $$
          DECLARE p text:=current_setting('cordis_fault.point',true);
          BEGIN
           IF TG_OP='INSERT' THEN
            IF p='scope' AND TG_TABLE_NAME='scopes' THEN
             RAISE EXCEPTION 'fault scope' USING ERRCODE='U0001';
            ELSIF p='effect' AND TG_TABLE_NAME='effects' AND (to_jsonb(NEW)->>'parent_id') IS NULL THEN
             RAISE EXCEPTION 'fault effect' USING ERRCODE='U0001';
            ELSIF p='request' AND TG_TABLE_NAME='requests' THEN
             RAISE EXCEPTION 'fault request' USING ERRCODE='U0001';
            ELSIF p='event' AND TG_TABLE_NAME='events' THEN
             RAISE EXCEPTION 'fault event' USING ERRCODE='U0001';
            ELSIF p='successor' AND TG_TABLE_NAME='effects' AND (to_jsonb(NEW)->>'parent_id') IS NOT NULL THEN
             RAISE EXCEPTION 'fault successor' USING ERRCODE='U0001';
            END IF;
           ELSIF TG_OP='UPDATE' AND p='settle' AND TG_TABLE_NAME='effects'
            AND (to_jsonb(OLD)->>'status')='ready' THEN
            RAISE EXCEPTION 'fault settle' USING ERRCODE='U0001';
           END IF;
          RETURN NEW;
          END $$;
          CREATE TRIGGER w1_fault_s BEFORE INSERT ON v24_cordis.scopes FOR EACH ROW EXECUTE FUNCTION v24_cordis.w1_fault();
          CREATE TRIGGER w1_fault_e BEFORE INSERT OR UPDATE ON v24_cordis.effects FOR EACH ROW EXECUTE FUNCTION v24_cordis.w1_fault();
          CREATE TRIGGER w1_fault_q BEFORE INSERT ON v24_cordis.requests FOR EACH ROW EXECUTE FUNCTION v24_cordis.w1_fault();
          CREATE TRIGGER w1_fault_v BEFORE INSERT ON v24_cordis.events FOR EACH ROW EXECUTE FUNCTION v24_cordis.w1_fault();""")
        owner.commit()
    try:
        owner_root = active_owner(db)
        for point in ('scope', 'effect', 'request', 'event'):
            payload = install_payload(mode='existing', existing_scope=owner_root['scope'],
                                      owner=dict(fiber_id=str(owner_root['fiber']),
                                                 episode_id=str(owner_root['episode'])))
            if point=='scope':
                payload['scope']=dict(mode='child', id=str(uuid.uuid4()),
                                      parent_id=str(owner_root['scope']), realm_overrides={})
            with contextlib.closing(db.connect('owner')) as owner:
                before = snapshot(owner)
                owner.rollback()
            with contextlib.closing(db.connect('service')) as conn:
                effect, out = command(db, conn, 'service', 'command_install', payload)
                set_probe(conn, install_delta(db, payload))
                query(conn, "SELECT set_config('cordis_fault.point',%s,false)", (point,))
                sqlstate(conn, 'SELECT v24_cordis.advance(%s,%s)', (effect, Json(out)), code='U0001')
            with contextlib.closing(db.connect('owner')) as owner:
                assert snapshot(owner) == before, point
                owner.rollback()
        fixture = p1_fixture(db, 'fault-cont')
        body = p1_body(fixture['fiber'], uuid.uuid4())
        for point in ('settle', 'request', 'event', 'successor'):
            with contextlib.closing(db.connect('owner')) as owner:
                before = snapshot(owner)
                owner.rollback()
            with contextlib.closing(db.connect('service')) as conn:
                e, out = command(db, conn, 'service', 'command_reconcile', fixture['payload'],
                                 key=fixture['key'], effect=fixture['child'])
                set_probe(conn, body)
                query(conn, "SELECT set_config('cordis_fault.point',%s,false)", (point,))
                sqlstate(conn, 'SELECT v24_cordis.advance(%s,%s)', (e, Json(out)), code='U0001')
            with contextlib.closing(db.connect('owner')) as owner:
                assert snapshot(owner) == before, point
                owner.rollback()
            assert scalar(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s',
                          (fixture['child'],)) == 'ready'
            assert scalar(db, 'SELECT count(*) FROM v24_cordis.requests WHERE effect_id=%s',
                          (fixture['child'],)) == 0
    finally:
        with contextlib.closing(db.connect('owner')) as owner:
            for trigger, table in (('w1_fault_s', 'scopes'), ('w1_fault_e', 'effects'),
                                   ('w1_fault_q', 'requests'), ('w1_fault_v', 'events')):
                query(owner, f'DROP TRIGGER {trigger} ON v24_cordis.{table}')
            query(owner, 'DROP FUNCTION v24_cordis.w1_fault()')
            owner.commit()
    print('[CDP2-K5] fault at scope/effect/settle/request/event/successor rolls back atomically')


def test_generation(db):
    sf = seed_fiber(db, want_on=True, control_seq=1, prefix='gen-stale')
    sp, _ = seed_parent(db, 'command_reconcile', reconcile_payload(sf['fiber'], 'on', 1),
                        fiber=sf['fiber'])
    spayload = reconcile_payload(sf['fiber'], 'advance', 0)
    sc, sk = seed_child(db, sp, sf['fiber'], spayload)
    with contextlib.closing(db.connect('owner')) as owner:
        before = snapshot(owner)
        owner.rollback()
    with contextlib.closing(db.connect('service')) as conn:
        e, out = command(db, conn, 'service', 'command_reconcile', spayload, key=sk, effect=sc)
        set_probe(conn, p1_body(sf['fiber'], uuid.uuid4()))
        bad(api(conn, e, out), 'stale_generation', 'continuation_generation')
        conn.rollback()
    with contextlib.closing(db.connect('owner')) as owner:
        assert snapshot(owner) == before
        owner.rollback()
    drift = p2_fixture(db, 'gen-drift', expected=0)
    with contextlib.closing(db.connect('owner')) as owner:
        before = snapshot(owner)
        owner.rollback()
    with contextlib.closing(db.connect('service')) as conn:
        e, out = command(db, conn, 'service', 'command_reconcile', drift['payload'],
                         key=drift['key'], effect=drift['child'])
        set_probe(conn, p1_body(drift['fiber'], drift['episode']))  # ignored after drift
        # p2_fixture is a P2 phase; the generation drift is checked before the interpreter.

        sqlstate(conn, 'SELECT v24_cordis.advance(%s,%s)', (e, Json(out)))
    with contextlib.closing(db.connect('owner')) as owner:
        assert snapshot(owner) == before
        owner.rollback()
    retry = p1_fixture(db, 'gen-retry')
    body = p1_body(retry['fiber'], uuid.uuid4())
    with contextlib.closing(db.connect('service')) as conn:
        e, out = command(db, conn, 'service', 'command_reconcile', retry['payload'],
                         key=retry['key'], effect=retry['child'])
        set_probe(conn, body)
        set_probe_raise(conn, True)
        sqlstate(conn, 'SELECT v24_cordis.advance(%s,%s)', (e, Json(out)))
    assert scalar(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (retry['child'],)) == 'ready'
    _, result, _ = run_cont(db, retry['parent'], retry['payload'], body, child=retry['child'],
                            key=retry['key'])
    ok(result)
    counts = tuple(scalar(db, f'SELECT count(*) FROM v24_cordis.{t} WHERE {w}', (retry['child'],))
                   for t, w in (('requests', 'effect_id=%s'), ('events', 'effect_id=%s'),
                                ('effects', 'parent_id=%s')))
    assert counts == (1, 1, 1), counts
    replay = run_cont(db, retry['parent'], retry['payload'], body, child=retry['child'],
                      key=retry['key'])[1]
    assert replay == result
    assert tuple(scalar(db, f'SELECT count(*) FROM v24_cordis.{t} WHERE {w}', (retry['child'],))
                 for t, w in (('requests', 'effect_id=%s'), ('events', 'effect_id=%s'),
                              ('effects', 'parent_id=%s'))) == counts
    ghost = uuid.uuid4()
    missing_key = successor_key(ghost, 0)
    missing_payload = reconcile_payload(uuid.uuid4(), 'advance', 0)
    with contextlib.closing(db.connect('owner')) as owner:
        before = snapshot(owner)
        owner.rollback()
    with contextlib.closing(db.connect('service')) as conn:
        e, out = command(db, conn, 'service', 'command_reconcile', missing_payload,
                         key=missing_key,
                         effect=derive(db.roles['service'], missing_key, 'command_reconcile'))
        assert api(conn, e, out)['error']['code'] == 'not_found_or_denied'
        conn.rollback()
    with contextlib.closing(db.connect('owner')) as owner:
        assert snapshot(owner) == before
        owner.rollback()
    print('[CDP2-K7] generation precheck before DML; drift 0A000; failed retry reuses one receipt')


def test_terminal(db, ctx):
    effect = ctx['child3']
    with contextlib.closing(db.connect('owner')) as owner:
        for change in ("status='ready'", "outcome='{\"x\":1}'",
                       "settled_at=now()+interval '1 second'", 'attempt=attempt+1',
                       'fence=fence+1', "claim_owner='reopen'",
                       "lease_until=now()+interval '1 second'"):
            sqlstate(owner, f'UPDATE v24_cordis.effects SET {change} WHERE id=%s', (effect,),
                     code='55000')
        sqlstate(owner, "UPDATE v24_cordis.requests SET response='{}' WHERE effect_id=%s",
                 (effect,), code='55000')
        owner.rollback()
    before = (scalar(db, 'SELECT count(*) FROM v24_cordis.requests'),
              scalar(db, 'SELECT count(*) FROM v24_cordis.events'))
    replay = run_cont(db, ctx['child2'], ctx['p4'], delta(), key=ctx['p4_key'],
                      child=ctx['child3'])[1]
    assert replay == ctx['p4_result'], (replay, ctx['p4_result'])
    assert (scalar(db, 'SELECT count(*) FROM v24_cordis.requests'),
            scalar(db, 'SELECT count(*) FROM v24_cordis.events')) == before
    print('[CDP2-K6] terminal status/outcome/settled/attempt/fence/claim/lease and response immutable')


def test_events(db, ctx):
    got = rows(db, "SELECT seq,event_kind,payload FROM v24_cordis.events WHERE entity_type='fiber' "
                   'AND entity_id=%s ORDER BY seq', (ctx['fiber'],))
    assert [r[:2] for r in got] == [(0, 'fiber_target_requested'), (1, 'episode_begun'),
                                    (2, 'contributions_appended'), (3, 'episode_activated')], got
    assert got[0][2] == {'want_on': True, 'control_seq': 1}, got[0]
    assert got[1][2] == {'episode_id': str(ctx['episode']), 'epoch': 1, 'control_seq': 1,
                         'require_keys': [], 'pin_ids': []}, got[1]
    assert got[2][2] == {'episode_id': str(ctx['episode']),
                         'contribution_ids': [str(ctx['c0']), str(ctx['c1'])],
                         'seq_from': 0, 'seq_through': 1, 'next_index': 2}, got[2]
    assert got[3][2] == {'episode_id': str(ctx['episode']), 'epoch': 1}, got[3]
    install = rows(db, 'SELECT seq,event_kind,payload FROM v24_cordis.events WHERE effect_id=%s',
                   (ctx['root_effect'],))
    assert [r[:2] for r in install] == [(0, 'install_created')], install
    assert install[0][2]['scope_id'] == ctx['root']['scope']['id']
    assert install[0][2]['scope_created'] is False
    assert install[0][2]['fiber_id'] == ctx['root']['fiber_id']
    assert install[0][2]['owner_fiber_id'] == str(ctx['owner_root']['fiber'])
    assert install[0][2]['owner_episode_id'] == str(ctx['owner_root']['episode'])
    assert install[0][2]['child_contribution_id'] is not None
    dispose = rows(db, "SELECT seq,event_kind,payload FROM v24_cordis.events "
                       "WHERE entity_type='install' AND entity_id=%s ORDER BY seq",
                   (ctx['root']['install_id'],))
    assert [r[:2] for r in dispose] == [(0, 'install_created'), (1, 'install_disposed')], dispose
    assert dispose[1][2] == {'fiber_ids': ctx['dispose_fibers']}, dispose[1]
    assert scalar(db, 'SELECT count(*) FROM v24_cordis.events WHERE effect_id=%s',
                  (ctx['noop_effect'],)) == 0
    assert scalar(db, 'SELECT count(*) FROM v24_cordis.events WHERE effect_id=%s',
                  (ctx['child0'],)) == 1
    print('[CDP2-K8] exact event tuple/payload and one entity cursor; no-op and replay add no event')


def zero_state(db, conn, effect, out, code='0A000'):
    with contextlib.closing(db.connect('owner')) as owner:
        before = snapshot(owner)
        owner.rollback()
    sqlstate(conn, 'SELECT v24_cordis.advance(%s,%s)', (effect, Json(out)), code=code)
    with contextlib.closing(db.connect('owner')) as owner:
        assert snapshot(owner) == before
        owner.rollback()


def test_production(db):
    # W2 production install is data-only; P0-P4 and dispose remain the W3/W4 0A000 seams.
    payload = install_payload()
    with contextlib.closing(db.connect('service')) as conn:
        effect, out = command(db, conn, 'service', 'command_install', payload)
        result = api(conn, effect, out)
        assert result.get('disposition') == 'committed', result
        conn.commit()
    assert scalar(db, 'SELECT fiber_id FROM v24_cordis.effects WHERE id=%s',
                  (effect,)) == uuid.UUID(payload['fiber_id'])
    assert scalar(db, 'SELECT episode_id FROM v24_cordis.effects WHERE id=%s', (effect,)) is None
    assert scalar(db, 'SELECT state FROM v24_cordis.installs WHERE id=%s',
                  (payload['install_id'],)) == 'installed'
    assert scalar(db, 'SELECT want_on OR control_seq<>0 OR current_episode_id IS NOT NULL '
                      'FROM v24_cordis.fibers WHERE id=%s', (payload['fiber_id'],)) is False
    assert scalar(db, 'SELECT count(*) FROM v24_cordis.episodes WHERE fiber_id=%s',
                  (payload['fiber_id'],)) == 0
    assert scalar(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id=%s',
                  (payload['fiber_id'],)) == 0
    assert scalar(db, 'SELECT count(*) FROM v24_cordis.pins WHERE consumer_fiber_id=%s',
                  (payload['fiber_id'],)) == 0
    assert scalar(db, "SELECT count(*) FROM v24_cordis.effects WHERE kind<>'command_install'") == 0
    assert rows(db, "SELECT event_kind FROM v24_cordis.events WHERE effect_id=%s",
                (effect,)) == [('install_created',)]
    f = seed_fiber(db, prefix='prod-p0')
    p0 = reconcile_payload(f['fiber'], 'on', 0)
    with contextlib.closing(db.connect('service')) as conn:
        effect, out = command(db, conn, 'service', 'command_reconcile', p0)
        zero_state(db, conn, effect, out)
    cf = seed_fiber(db, want_on=True, control_seq=1, prefix='prod-p1')
    parent, _ = seed_parent(db, 'command_reconcile', reconcile_payload(cf['fiber'], 'on', 1),
                            fiber=cf['fiber'])
    cp = reconcile_payload(cf['fiber'], 'advance', 1)
    child, key = seed_child(db, parent, cf['fiber'], cp)
    with contextlib.closing(db.connect('service')) as conn:
        effect, out = command(db, conn, 'service', 'command_reconcile', cp, key=key, effect=child)
        zero_state(db, conn, effect, out)
    d = seed_fiber(db, prefix='prod-dispose')
    dis = dispose_payload(d['install'])
    with contextlib.closing(db.connect('service')) as conn:
        effect, out = command(db, conn, 'service', 'command_dispose', dis)
        zero_state(db, conn, effect, out)
        bad_dis = {**dis, 'fiber_ids': [str(d['fiber'])]}
        effect, out = command(db, conn, 'service', 'command_dispose', bad_dis)
        bad(api(conn, effect, out), 'invalid_args', 'dispose_payload')
        conn.rollback()
    # Malformed reconcile/dispose payloads are handled before the unsupported seam.
    with contextlib.closing(db.connect('owner')) as owner:
        before = snapshot(owner)
        owner.rollback()
    with contextlib.closing(db.connect('service')) as conn:
        effect, out = command(db, conn, 'service', 'command_reconcile', {'fiber_id': str(f['fiber'])})
        bad(api(conn, effect, out), 'invalid_args', 'reconcile_payload')
        conn.commit()
    with contextlib.closing(db.connect('owner')) as owner:
        assert snapshot(owner) == before
        owner.rollback()
    print('[CDP2-K4] production install commits data-only; P0-P4 and dispose stay 0A000; malformed payload is invalid_args')


def test_negatives(db, ctx):
    # Reserved key/action pairing and malformed reconcile are decided before any lock.
    f = seed_fiber(db, prefix='neg-pair')
    ghost = uuid.uuid4()
    with contextlib.closing(db.connect('service')) as conn:
        e, out = command(db, conn, 'service', 'command_reconcile',
                         reconcile_payload(f['fiber'], 'on', 0), key=successor_key(ghost, 0))
        bad(api(conn, e, out), 'invalid_args', 'reserved_key_pairing')
        conn.rollback()
        e, out = command(db, conn, 'service', 'command_reconcile',
                         reconcile_payload(f['fiber'], 'advance', 0))
        bad(api(conn, e, out), 'invalid_args', 'reserved_key_pairing')
        conn.rollback()
    # W2 admission: an ownerful root-mode install is not a legal scope/owner combination.
    of = seed_fiber(db, prefix='neg-owner')
    oep = seed_episode(db, of['fiber'], epoch=1, state='active', control_seq=0)
    owner = dict(fiber_id=str(of['fiber']), episode_id=str(oep))
    payload = install_payload(owner=owner)
    with contextlib.closing(db.connect('service')) as conn:
        e, out = command(db, conn, 'service', 'command_install', payload)
        set_probe(conn, install_delta(db, payload))
        bad(api(conn, e, out), 'invalid_outcome', 'install_admission')
        conn.rollback()
    # A second ownerless root is refused by admission before the forged delta can apply.
    duplicate = install_payload()
    with contextlib.closing(db.connect('service')) as conn:
        e, out = command(db, conn, 'service', 'command_install', duplicate)
        set_probe(conn, delta(domain=[]))
        bad(api(conn, e, out), 'invalid_outcome', 'install_admission')
        conn.rollback()
    # Root scope wire v1 is exactly {mode,id,realm_overrides}; parent_id is child-only.
    badroot = install_payload()
    badroot['scope']['parent_id'] = None
    with contextlib.closing(db.connect('service')) as conn:
        e, out = command(db, conn, 'service', 'command_install', badroot)
        set_probe(conn, delta(domain=[]))
        bad(api(conn, e, out), 'invalid_args', 'install_payload')
        conn.rollback()
    # Dispose must name exactly the install's fiber set.
    d = seed_fiber(db, prefix='neg-dispose')
    second = uuid.uuid4()
    with contextlib.closing(db.connect('owner')) as owner_conn:
        query(owner_conn, 'INSERT INTO v24_cordis.fibers(id,install_id,owner_id,owner_episode_id,'
                          'scope_id) VALUES(%s,%s,%s,%s,%s)',
              (second, d['install'], d['root']['fiber'], d['root']['episode'], d['scope']))
        owner_conn.commit()
    subset = [str(d['fiber'])]
    dis = dispose_payload(d['install'])
    with contextlib.closing(db.connect('service')) as conn:
        e, out = command(db, conn, 'service', 'command_dispose', dis)
        set_probe(conn, delta(domain=[dict(op='basic_dispose', install_id=str(d['install']),
                                           fiber_ids=subset)],
                              events=[event('install', d['install'], 'install_disposed',
                                            dict(fiber_ids=subset))]))
        bad(api(conn, e, out), 'invalid_outcome', 'dispose_set')
        conn.rollback()
    # P1 provider binding digest is checked against the committed contribution.
    pf = seed_fiber(db, requires=('svc2',), want_on=True, control_seq=1, prefix='neg-pin')
    provider = seed_provider(db, key='svc2')
    pparent, _ = seed_parent(db, 'command_reconcile', reconcile_payload(pf['fiber'], 'on', 1),
                             fiber=pf['fiber'])
    ppayload = reconcile_payload(pf['fiber'], 'advance', 1)
    pchild, pkey = seed_child(db, pparent, pf['fiber'], ppayload)
    wrong_binding = dict(contribution_id=str(provider['contribution']),
                         provider_fiber_id=str(provider['fiber']),
                         provider_episode_id=str(provider['episode']),
                         provider_epoch=provider['epoch'],
                         descriptor_digest='b' * 64, contract_version='1')
    pin = dict(id=str(uuid.uuid4()), key=provider['key'],
               contribution_id=str(provider['contribution']),
               provider_episode_id=str(provider['episode']), provider_epoch=provider['epoch'])
    pep = uuid.uuid4()
    with contextlib.closing(db.connect('service')) as conn:
        e, out = command(db, conn, 'service', 'command_reconcile', ppayload, key=pkey, effect=pchild)
        set_probe(conn, delta(domain=[dict(op='episode_begin', id=str(pep), fiber_id=str(pf['fiber']),
                                           epoch=1, committed_view={provider['key']: wrong_binding},
                                           iterator=dict(v=1, next_index=0, registered_through=-1,
                                                         control_seq=1), pins=[pin])],
                              events=[event('fiber', pf['fiber'], 'episode_begun',
                                            dict(episode_id=str(pep), epoch=1, control_seq=1,
                                                 require_keys=[provider['key']],
                                                 pin_ids=[pin['id']]))]))
        bad(api(conn, e, out), 'invalid_outcome', 'p1_binding')
        conn.rollback()
    # P2 contributions must follow the installed provides order.
    p2 = p2_fixture(db, 'neg-p2', provides=('a',))
    cid = uuid.uuid4()
    with contextlib.closing(db.connect('service')) as conn:
        e, out = command(db, conn, 'service', 'command_reconcile', p2['payload'], key=p2['key'],
                         effect=p2['child'])
        set_probe(conn, delta(
            domain=[dict(op='contribution_append', id=str(cid), fiber_id=str(p2['fiber']),
                         episode_id=str(p2['episode']), seq=0, kind='service', realm='root',
                         key='b', descriptor={}, prev_contribution_id=None,
                         inverse=dict(op='delete_row'), contract_version='1'),
                    dict(op='episode_progress', episode_id=str(p2['episode']), next_index=1,
                         registered_through=0)],
            events=[event('fiber', p2['fiber'], 'contributions_appended',
                          dict(episode_id=str(p2['episode']), contribution_ids=[str(cid)],
                               seq_from=0, seq_through=0, next_index=1))],
            successors=[successor(p2['fiber'], 1)]))
        bad(api(conn, e, out), 'invalid_outcome', 'p2_provide')
        conn.rollback()
    # 513-or-more dispose closure is refused before any lock or interpreter call.
    big = seed_fiber(db, prefix='neg-cap')
    with contextlib.closing(db.connect('owner')) as owner_conn:
        query(owner_conn, 'INSERT INTO v24_cordis.fibers(id,install_id,owner_id,'
                          'owner_episode_id,scope_id) SELECT gen_random_uuid(),%s,%s,%s,%s '
                          'FROM generate_series(1,511)',
              (big['install'], big['root']['fiber'], big['root']['episode'], big['scope']))
        owner_conn.commit()
    seed_episode(db, big['fiber'], epoch=1, state='reloading', control_seq=0)
    with contextlib.closing(db.connect('owner')) as owner_conn:
        before = snapshot(owner_conn)
        owner_conn.rollback()
    with contextlib.closing(db.connect('service')) as conn:
        e, out = command(db, conn, 'service', 'command_dispose', {'install_id': str(big['install'])})
        bad(api(conn, e, out), 'retry_with_closure')
        conn.commit()
    with contextlib.closing(db.connect('owner')) as owner_conn:
        assert snapshot(owner_conn) == before
        owner_conn.rollback()
    # P0 no-op may not smuggle an event.
    with contextlib.closing(db.connect('service')) as conn:
        noop = reconcile_payload(ctx['fiber'], 'on', 1)
        e, out = command(db, conn, 'service', 'command_reconcile', noop)
        set_probe(conn, delta(events=[event('fiber', ctx['fiber'], 'fiber_target_requested',
                                            dict(want_on=True, control_seq=1))]))
        bad(api(conn, e, out), 'invalid_outcome', 'event_cardinality')
        conn.rollback()
        e, out = command(db, conn, 'service', 'command_reconcile', noop)
        set_probe(conn, delta(successors=[successor(ctx['fiber'], 1)]))
        bad(api(conn, e, out), 'invalid_outcome', 'p0_noop')
        conn.rollback()
    print('[CDP2-K4b] pairing/owner/install/dispose/pin/provide bounds; 513 closure cutoff; P0 no-op event/successor denied')

def main():
    from pathlib import Path
    sql_dir = Path(__file__).resolve().parents[1] / 'sql'
    advance = sql_dir / '40_advance.sql'
    assert len(advance.read_text().splitlines()) <= 1200
    ddl = [f for f in sql_dir.glob('*.sql') if 10 <= int(f.name[:2]) <= 17
           or f.name in ('20_relations.sql', '30_triggers.sql')]
    assert len(ddl) == 10 and sum(len(f.read_text().splitlines()) for f in ddl) <= 900
    with Server() as server, TestDB(server) as production, TestDB(server) as probe:
        test_production(production)
        ctx = test_lifecycle(probe)
        test_locks(production, probe, ctx)
        test_identity(probe)
        test_typed(probe)
        test_negatives(probe, ctx)
        test_faults(probe)
        test_generation(probe)
        test_terminal(probe, ctx)
        test_events(probe, ctx)
    print('[passed] CDP2-K (W1 continuation, typed delta, closure, terminal receipt, events)')


if __name__ == '__main__':
    main()
