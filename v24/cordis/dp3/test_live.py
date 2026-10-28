"""CDP3-L: W2 live, closing, and failure atomicity.

Production install/activation/control/advance paths provide transition evidence.
Owner DML is explicitly limited to scheduling an active reconcile, corruption
negatives, run-pin facts, and fault injection; it proves no W3 release writer.
"""
from __future__ import annotations
import contextlib
import copy
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dp2'))
from test_support import (Server, TestDB, query, snapshot, api, command, no_write,
                          reconcile_payload, seed_child, sqlstate, replace_function)
from test_activation import (install, phases, p0, commit_new, commit_child,
                             child_call, one, rows)
from psycopg2.extras import Json


def mutate(db, statement, params=()):
    """Owner-only fixture mutation, always under G."""
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, statement, params)
        conn.commit()


def owner_of(db, payload):
    return dict(fiber_id=payload['fiber_id'], episode_id=str(one(
        db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s',
        (payload['fiber_id'],))))


def activate(db, root, provides=(), requires=(), **kwargs):
    payload, _, _ = install(db, owner=owner_of(db, root), mode='existing',
                            existing=root['scope']['id'], provides=provides,
                            requires=requires, **kwargs)
    phases(db, uuid.UUID(payload['fiber_id']), len(provides))
    return payload


def live(db, payload):
    return one(db, 'SELECT v24_cordis.fiber_live_state(id,current_episode_id) '
                   'FROM v24_cordis.fibers WHERE id=%s', (payload['fiber_id'],))


def available(db, scope, key):
    return one(db, 'SELECT available FROM v24_cordis.resolve(%s,ARRAY[%s])', (scope, key))


def active_work(db, payload):
    """Explicit same-LOGIN scheduling fixture, using a real successful parent."""
    fiber = payload['fiber_id']
    parent = one(db, "SELECT effect_id FROM v24_cordis.events WHERE entity_id=%s "
                     "AND event_kind='episode_activated' ORDER BY seq DESC LIMIT 1", (fiber,))
    episode = one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s', (fiber,))
    control = one(db, 'SELECT control_seq FROM v24_cordis.fibers WHERE id=%s', (fiber,))
    request = reconcile_payload(fiber, 'advance', control)
    effect, key = seed_child(db, parent, fiber, request, episode=episode)
    with contextlib.closing(db.connect('service')) as conn:
        _, outcome = command(db, conn, 'service', 'command_reconcile', request,
                             key=key, effect=effect)
    return effect, outcome


def applied(db, effect, outcome):
    with contextlib.closing(db.connect('service')) as conn:
        result = api(conn, effect, outcome)
        assert result.get('disposition') == 'committed', result
        conn.commit()
    return result


def failure(db, payload, phase, code, reason, key, effect=None):
    fiber = payload['fiber_id']
    ep, seq, value = rows(db, 'SELECT current_episode_id,control_seq,failure '
                              'FROM v24_cordis.fibers WHERE id=%s', (fiber,))[0]
    expected = dict(v=1, control_seq=seq, episode_id=str(ep), phase=phase,
                    code=code, reason=reason, key=key)
    assert value == expected, (value, expected)
    assert one(db, 'SELECT v24_cordis.failure_v1_valid(%s)', (Json(value),)) is True
    assert rows(db, 'SELECT state,outcome,closed_at FROM v24_cordis.episodes WHERE id=%s',
                (ep,)) == [('closing', 'error', None)]
    assert one(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE episode_id=%s '
                   'AND (withdrawn_at IS NOT NULL OR released_at IS NOT NULL)', (ep,)) == 0
    if effect:
        assert one(db, 'SELECT count(*) FROM v24_cordis.events WHERE effect_id=%s', (effect,)) == 1
        assert one(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (effect,)) == 'succeeded'
    return expected


def test_transitive(db, root):
    m = activate(db, root, provides=['live-m'])
    a = activate(db, root, provides=['live-a'], requires=['live-m'])
    b = activate(db, root, provides=['live-b'], requires=['live-a'])
    for node in (root, m, a, b):
        assert live(db, node)['live'] is True
    assert live(db, b)['visited_count'] == 4  # root is shared and visited once
    pins = rows(db, 'SELECT id FROM v24_cordis.pins WHERE consumer_fiber_id IN (%s,%s)',
                (a['fiber_id'], b['fiber_id']))
    # W2 constructs an old run demand only; no production run/settlement is claimed.
    run = uuid.uuid4()
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, 'INSERT INTO v24_cordis.runs(id,owner_fiber_id,owner_episode_id,scope_id,spawn_key,remaining_steps) '
                    'VALUES(%s,%s,%s,%s,%s,0)', (run, b['fiber_id'], owner_of(db, b)['episode_id'],
                    root['scope']['id'], 'w2-old-run'))
        query(conn, 'INSERT INTO v24_cordis.pins(id,consumer_run_id,key,contribution_id,provider_epoch) '
                    'SELECT gen_random_uuid(),%s,key,contribution_id,provider_epoch FROM v24_cordis.pins WHERE id=%s '
                    'RETURNING id', (run, pins[0][0]))
        run_pin = query(conn, 'SELECT id FROM v24_cordis.pins WHERE consumer_run_id=%s', (run,))[0][0]
        conn.commit()
    off, result, _ = commit_new(db, 'command_reconcile',
                                reconcile_payload(m['fiber_id'], 'off', 1))
    assert result['disposition'] == 'committed'
    assert one(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id=%s '
                   'AND withdrawn_at IS NOT NULL', (m['fiber_id'],)) == 0
    assert one(db, 'SELECT state FROM v24_cordis.episodes WHERE id=(SELECT current_episode_id '
                   'FROM v24_cordis.fibers WHERE id=%s)', (m['fiber_id'],)) == 'active'
    for node, key in ((m, 'live-m'), (a, 'live-a'), (b, 'live-b')):
        assert live(db, node)['live'] is False
        assert available(db, root['scope']['id'], key) is False
    for pin, in pins + [(run_pin,)]:
        assert one(db, 'SELECT v24_cordis.pin_readable(%s)', (pin,)) is True
    effect, outcome = child_call(db, off, reconcile_payload(m['fiber_id'], 'advance', 2))
    applied(db, effect, outcome)
    for node in (a, b):
        effect, outcome = active_work(db, node)
        applied(db, effect, outcome)
    for node in (m, a, b):
        assert rows(db, 'SELECT state,outcome FROM v24_cordis.episodes WHERE id=(SELECT '
                    'current_episode_id FROM v24_cordis.fibers WHERE id=%s)',
                    (node['fiber_id'],)) == [('closing', 'retire')]
        assert one(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id=%s '
                       "AND kind='service' AND withdrawn_at IS NOT NULL AND released_at IS NULL",
                   (node['fiber_id'],)) == 1
    for pin, in pins + [(run_pin,)]:
        assert one(db, 'SELECT v24_cordis.pin_readable(%s)', (pin,)) is True
    # Release is fixture-only in W2. The deferred guard rejects one-sided release.
    contribution = one(db, 'SELECT contribution_id FROM v24_cordis.pins WHERE id=%s', (pins[0][0],))
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        sqlstate(conn, 'UPDATE v24_cordis.contributions SET released_at=clock_timestamp() '
                      'WHERE id=%s; SET CONSTRAINTS ALL IMMEDIATE', (contribution,), code='23514')
    mutate(db, 'UPDATE v24_cordis.pins SET released_at=clock_timestamp() WHERE id=%s', (pins[0][0],))
    assert one(db, 'SELECT v24_cordis.pin_readable(%s)', (pins[0][0],)) is False
    mutate(db, 'UPDATE v24_cordis.pins SET released_at=clock_timestamp() WHERE id=%s', (run_pin,))
    assert one(db, 'SELECT v24_cordis.pin_readable(%s)', (run_pin,)) is False
    print('[CDP3-L1] production M→A→B invalidation; P0 preserves visibility facts; P5 exact withdrawal; old pins readable')


def reloading(db, root, keys, prefix=0, requires=()):
    payload, _, _ = install(db, provides=keys, requires=requires, owner=owner_of(db, root),
                            mode='existing', existing=root['scope']['id'])
    parent, _, _ = p0(db, payload['fiber_id'])
    parent, result = commit_child(db, parent, reconcile_payload(payload['fiber_id'], 'advance', 1))
    assert result['disposition'] == 'committed', result
    for _ in range(prefix):
        parent, result = commit_child(db, parent, reconcile_payload(payload['fiber_id'], 'advance', 1))
        assert result['disposition'] == 'committed', result
    effect, outcome = child_call(db, parent, reconcile_payload(payload['fiber_id'], 'advance', 1))
    return payload, effect, outcome


def test_fault_atomicity(db, root):
    payload, effect, outcome = reloading(db, root, [f'atomic-{i}' for i in range(34)], prefix=1)
    fiber = payload['fiber_id']
    episode = one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s', (fiber,))
    replace_function(db, '''CREATE FUNCTION v24_cordis.w2_fault() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE point text:=current_setting('cordis_w2.point',true); state text;
BEGIN
 IF TG_TABLE_NAME='contributions' AND (to_jsonb(NEW)->>'seq')::int=33 THEN
  IF (SELECT count(*) FROM v24_cordis.contributions WHERE episode_id=NEW.episode_id)<34 THEN
   RAISE EXCEPTION 'fault must follow actual batch writes' USING ERRCODE='U0008'; END IF;
  IF point='narrow' THEN RAISE EXCEPTION 'injected' USING ERRCODE='23505',CONSTRAINT='contributions_service_addr'; END IF;
  state:=CASE point WHEN 'unique' THEN '23505' WHEN 'fk' THEN '23503' WHEN 'check' THEN '23514'
   WHEN 'cancel' THEN '57014' WHEN 'timeout' THEN '55P03' WHEN 'domain' THEN 'U0007' END;
  IF state IS NOT NULL THEN RAISE EXCEPTION 'injected' USING ERRCODE=state,CONSTRAINT='other_constraint'; END IF;
 ELSIF TG_TABLE_NAME='episodes' AND point='iterator' THEN
  RAISE EXCEPTION 'injected iterator' USING ERRCODE='U0007';
 ELSIF TG_TABLE_NAME='effects' AND ((point='effect' AND TG_OP='UPDATE')
    OR (point='successor' AND TG_OP='INSERT')) THEN
  RAISE EXCEPTION 'injected effect' USING ERRCODE='U0007';
 ELSIF TG_TABLE_NAME='requests' AND point='request' THEN
  RAISE EXCEPTION 'injected request' USING ERRCODE='U0007';
 ELSIF TG_TABLE_NAME='events' AND point='event' THEN
  RAISE EXCEPTION 'injected event' USING ERRCODE='U0007';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER w2_fault_c AFTER INSERT ON v24_cordis.contributions FOR EACH ROW EXECUTE FUNCTION v24_cordis.w2_fault();
CREATE TRIGGER w2_fault_i AFTER UPDATE ON v24_cordis.episodes FOR EACH ROW EXECUTE FUNCTION v24_cordis.w2_fault();
CREATE TRIGGER w2_fault_e AFTER INSERT OR UPDATE ON v24_cordis.effects FOR EACH ROW EXECUTE FUNCTION v24_cordis.w2_fault();
CREATE TRIGGER w2_fault_q AFTER INSERT ON v24_cordis.requests FOR EACH ROW EXECUTE FUNCTION v24_cordis.w2_fault();
CREATE TRIGGER w2_fault_v AFTER INSERT ON v24_cordis.events FOR EACH ROW EXECUTE FUNCTION v24_cordis.w2_fault();''')
    try:
        for point, code in [('domain', 'U0007'), ('iterator', 'U0007'), ('effect', 'U0007'),
                            ('request', 'U0007'), ('event', 'U0007'), ('successor', 'U0007'),
                            ('unique', '23505'), ('fk', '23503'), ('check', '23514'),
                            ('cancel', '57014'), ('timeout', '55P03')]:
            with contextlib.closing(db.connect('owner')) as conn:
                before = snapshot(conn)
            with contextlib.closing(db.connect('service')) as conn:
                query(conn, "SELECT set_config('cordis_w2.point',%s,false)", (point,))
                sqlstate(conn, 'SELECT v24_cordis.advance(%s,%s)', (effect, Json(outcome)), code=code)
            with contextlib.closing(db.connect('owner')) as conn:
                assert snapshot(conn) == before, point
        with contextlib.closing(db.connect('service')) as conn:
            query(conn, "SELECT set_config('cordis_w2.point','narrow',false)")
            result = api(conn, effect, outcome)
            assert result['disposition'] == 'committed', result
            conn.commit()
        failure(db, payload, 'p2', 'provide_conflict', 'address_conflict', 'atomic-33', effect)
        assert one(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE episode_id=%s', (episode,)) == 32
        assert one(db, "SELECT (iterator->>'next_index')::int FROM v24_cordis.episodes WHERE id=%s", (episode,)) == 32
        assert one(db, 'SELECT count(*) FROM v24_cordis.effects WHERE parent_id=%s', (effect,)) == 0
    finally:
        replace_function(db, '''DROP TRIGGER w2_fault_c ON v24_cordis.contributions;
DROP TRIGGER w2_fault_i ON v24_cordis.episodes;
DROP TRIGGER w2_fault_e ON v24_cordis.effects;
DROP TRIGGER w2_fault_q ON v24_cordis.requests;
DROP TRIGGER w2_fault_v ON v24_cordis.events;
DROP FUNCTION v24_cordis.w2_fault();''')
    print('[CDP3-L2] six failure boundaries and unrelated SQL errors roll back; narrow after-write conflict commits one Raise preserving prefix32')


def test_failure_types(db):
    good = dict(v=1, control_seq=1, episode_id=str(uuid.uuid4()), phase='p2',
                code='provide_conflict', reason='address_conflict', key='key')
    combinations = [('p2', 'provide_conflict', 'address_conflict'),
                    ('p2', 'registration_stale', 'contract_drift'),
                    ('p3', 'registration_stale', 'contract_drift'),
                    ('p3', 'provider_unavailable', 'check_failed'),
                    ('p4', 'registration_stale', 'totality_failed')]
    for phase, code, reason in combinations:
        value = dict(good, phase=phase, code=code, reason=reason)
        assert one(db, 'SELECT v24_cordis.failure_v1_valid(%s)', (Json(value),)) is True
    for key in good:
        for invalid in (None, [], {}, True):
            value = dict(good, **{key: invalid})
            assert one(db, 'SELECT v24_cordis.failure_v1_valid(%s)', (Json(value),)) is False, value
        value = dict(good)
        del value[key]
        assert one(db, 'SELECT v24_cordis.failure_v1_valid(%s)', (Json(value),)) is False
    for change in (dict(extra=1), dict(v=2), dict(control_seq=-1),
                   dict(control_seq=9223372036854775808), dict(control_seq='1'),
                   dict(control_seq=1.5), dict(key=''), dict(key='x' * 129),
                   dict(phase='p4', reason='address_conflict'), dict(episode_id='bad')):
        value = dict(good, **change)
        assert one(db, 'SELECT v24_cordis.failure_v1_valid(%s)', (Json(value),)) is False, value
    print('[CDP3-L3] failure-v1 seven keys, scalar types, nullability, integer ranges and five combinations')


def test_guards_and_types(db, root):
    payload = activate(db, root, provides=['guard-service'])
    fiber, ep = payload['fiber_id'], owner_of(db, payload)['episode_id']
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        sqlstate(conn, "UPDATE v24_cordis.episodes SET state='reloading' WHERE id=%s", (ep,), code='55000')
    off, _, _ = commit_new(db, 'command_reconcile', reconcile_payload(fiber, 'off', 1))
    effect, outcome = child_call(db, off, reconcile_payload(fiber, 'advance', 2))
    applied(db, effect, outcome)
    for statement in (
        "UPDATE v24_cordis.episodes SET state='active' WHERE id=%s",
        "UPDATE v24_cordis.episodes SET outcome='divert' WHERE id=%s",
        "UPDATE v24_cordis.episodes SET iterator=jsonb_set(iterator,'{next_index}','99') WHERE id=%s",
        'UPDATE v24_cordis.contributions SET withdrawn_at=NULL WHERE episode_id=%s',
        "UPDATE v24_cordis.contributions SET withdrawn_at=withdrawn_at+interval '1 second' WHERE episode_id=%s",
    ):
        with contextlib.closing(db.connect('owner')) as conn:
            query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
            sqlstate(conn, statement, (ep,), code='55000')
    failed, effect, outcome = reloading(db, root, ['guard-service'])
    applied(db, effect, outcome)
    fact = failure(db, failed, 'p2', 'provide_conflict', 'address_conflict', 'guard-service')
    for value, code in ((None, '55000'), ({}, '23514'),
                        (dict(fact, control_seq=9), '23514'),
                        (dict(fact, episode_id=ep), '23514')):
        with contextlib.closing(db.connect('owner')) as conn:
            query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
            sqlstate(conn, 'UPDATE v24_cordis.fibers SET failure=%s WHERE id=%s; SET CONSTRAINTS ALL IMMEDIATE',
                     (None if value is None else Json(value), failed['fiber_id']), code=code)
    for field in ('phase', 'code', 'reason'):
        args = dict(phase='p2', code='provide_conflict', reason='address_conflict')
        args[field] = None
        with contextlib.closing(db.connect('owner')) as conn:
            sqlstate(conn, 'SELECT v24_cordis.failure_v1(1,%s,%s,%s,%s,\'key\')',
                     (ep, args['phase'], args['code'], args['reason']), code='22023')
    base = dict(op='episode_close_start', fiber_id=fiber, episode_id=ep, outcome='retire', failure=None)
    for patch in (dict(outcome=None), dict(outcome=[]), dict(outcome='closed'),
                  dict(extra=1), dict(failure={}), dict(fiber_id='bad')):
        delta = dict(domain=[dict(base, **patch)], receipt=dict(status='succeeded'), events=[], successors=[])
        result = one(db, "SELECT v24_cordis.validate_delta(%s,'command',true)", (Json(delta),))
        assert result['error']['code'] == 'invalid_outcome', (patch, result)
    print('[CDP3-L9] production closing/withdraw/failure guards, frozen generation binding, typed close and NULL constructor negatives')


def test_classified_and_divert(db, root):
    # Immutable declaration corruption is an owner-only negative fixture. Restore
    # the guard before invoking advance so the production writer remains intact.
    def declaration_damage(payload, patch):
        with contextlib.closing(db.connect('owner')) as conn:
            query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
            query(conn, 'ALTER TABLE v24_cordis.installs DISABLE TRIGGER installs_immutable')
            query(conn, 'UPDATE v24_cordis.installs SET manifest=manifest||%s WHERE id=%s',
                  (Json(patch), payload['install_id']))
            query(conn, 'ALTER TABLE v24_cordis.installs ENABLE TRIGGER installs_immutable')
            conn.commit()

    provider = activate(db, root, provides=['p3-source'])
    p2, effect, outcome = reloading(db, root, ['p2-contract'])
    damaged = copy.deepcopy(p2['manifest']['provides'])
    damaged[0]['contract_version'] = '2'
    declaration_damage(p2, {'provides': damaged})
    applied(db, effect, outcome)
    failure(db, p2, 'p2', 'registration_stale', 'contract_drift', 'p2-contract', effect)
    for mode in ('check', 'contract'):
        payload, effect, outcome = reloading(db, root, [], requires=['p3-source'])
        if mode == 'check':
            declaration_damage(payload, {'check': {'p3-source': dict(
                v=1, op='equals', path=['capability'], value='other')}})
            expected = ('provider_unavailable', 'check_failed')
        else:
            declaration_damage(payload, {'requires': [dict(key='p3-source', contract_version='2')]})
            expected = ('registration_stale', 'contract_drift')
        applied(db, effect, outcome)
        failure(db, payload, 'p3', *expected, 'p3-source', effect)
    for mode in ('missing', 'mismatch', 'extra', 'empty_extra'):
        keys = [] if mode == 'empty_extra' else ['p4-' + mode]
        payload, effect, outcome = reloading(db, root, keys, prefix=1 if keys else 0)
        fiber = payload['fiber_id']
        if mode == 'missing':
            mutate(db, "UPDATE v24_cordis.contributions SET withdrawn_at=clock_timestamp() WHERE fiber_id=%s AND kind='service'", (fiber,))
        elif mode == 'mismatch':
            damaged = copy.deepcopy(payload['manifest']['provides'])
            damaged[0]['descriptor']['value'] = 'changed'
            declaration_damage(payload, {'provides': damaged})
        else:
            mutate(db, "INSERT INTO v24_cordis.contributions(id,fiber_id,episode_id,seq,kind,realm,key,descriptor,inverse,contract_version) "
                       "SELECT gen_random_uuid(),id,current_episode_id,100,'service','root',%s,'{\"capability\":\"cap\"}',"
                       "'{\"op\":\"delete_row\"}','1' FROM v24_cordis.fibers WHERE id=%s", ('p4-extra-' + mode, fiber))
        if mode in ('extra', 'empty_extra'):
            with contextlib.closing(db.connect('owner')) as conn:
                before = snapshot(conn)
            with contextlib.closing(db.connect('service')) as conn:
                sqlstate(conn, 'SELECT v24_cordis.advance(%s,%s)', (effect, Json(outcome)))
            with contextlib.closing(db.connect('owner')) as conn:
                assert snapshot(conn) == before
        else:
            applied(db, effect, outcome)
            # withdrawn fixture remains withdrawn; Raise adds no release/inverse.
            value = one(db, 'SELECT failure FROM v24_cordis.fibers WHERE id=%s', (fiber,))
            assert value == dict(v=1, control_seq=1, episode_id=str(one(db,
                'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s', (fiber,))),
                phase='p4', code='registration_stale', reason='totality_failed', key=keys[0]), value
            assert one(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id=%s AND released_at IS NOT NULL', (fiber,)) == 0
    # Target drift after a real prefix never appends, withdraws or rewrites iterator.
    payload, effect, outcome = reloading(db, root, [f'divert-{i}' for i in range(33)],
                                         prefix=1, requires=['p3-source'])
    mutate(db, "UPDATE v24_cordis.contributions SET withdrawn_at=clock_timestamp() "
               "WHERE fiber_id=%s AND kind='service' AND released_at IS NULL", (provider['fiber_id'],))
    applied(db, effect, outcome)
    assert one(db, 'SELECT outcome FROM v24_cordis.episodes WHERE id=(SELECT current_episode_id '
                   'FROM v24_cordis.fibers WHERE id=%s)', (payload['fiber_id'],)) == 'divert'
    assert one(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id=%s AND withdrawn_at IS NULL '
                   'AND released_at IS NULL', (payload['fiber_id'],)) == 32
    assert one(db, "SELECT (iterator->>'next_index')::int FROM v24_cordis.episodes WHERE id=(SELECT current_episode_id "
                   'FROM v24_cordis.fibers WHERE id=%s)', (payload['fiber_id'],)) == 32
    print('[CDP3-L4] P2/P3/P4 exact classified Raise; unassignable totality damage propagates; target drift Divert preserves prefix')


def test_live_negatives(db, root):
    provider = activate(db, root, provides=['negative-source'])
    consumer = activate(db, root, requires=['negative-source'], provides=['negative-consumer'])
    ep = owner_of(db, consumer)['episode_id']
    # Every malformed historical fixture is rolled back, leaving the real success intact.
    cases = [
        ("UPDATE v24_cordis.pins SET released_at=clock_timestamp() WHERE consumer_fiber_id=%s", (consumer['fiber_id'],), 'pin_mismatch'),
        ("UPDATE v24_cordis.episodes SET committed_view=committed_view||'{\"extra\":{}}' WHERE id=%s", (ep,), 'pin_mismatch'),
        ("UPDATE v24_cordis.episodes SET committed_view=jsonb_set(committed_view,'{negative-source,provider_epoch}','999') WHERE id=%s", (ep,), 'pin_mismatch'),
        ("UPDATE v24_cordis.episodes SET committed_view=jsonb_set(committed_view,'{negative-source,descriptor_digest}','\"bad\"') WHERE id=%s", (ep,), 'pin_mismatch'),
        ("UPDATE v24_cordis.pins SET provider_epoch=999 WHERE consumer_fiber_id=%s", (consumer['fiber_id'],), 'pin_mismatch'),
        ("UPDATE v24_cordis.installs SET manifest=jsonb_set(manifest,'{check}',%s) WHERE id=%s",
         (Json({'negative-source': dict(v=1, op='equals', path=['capability'], value='wrong')}), consumer['install_id']), 'check_failed'),
        ("UPDATE v24_cordis.installs SET manifest=jsonb_set(manifest,'{requires}','[\"different\"]') WHERE id=%s", (consumer['install_id'],), 'pin_mismatch'),
    ]
    for statement, params, reason in cases:
        with contextlib.closing(db.connect('owner')) as conn:
            query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
            for table, trigger in [('episodes', 'episodes_immutable'), ('pins', 'pins_immutable'), ('installs', 'installs_immutable')]:
                query(conn, f'ALTER TABLE v24_cordis.{table} DISABLE TRIGGER {trigger}')
            query(conn, statement, params)
            result = query(conn, 'SELECT v24_cordis.fiber_live_state(%s,%s)', (consumer['fiber_id'], ep))[0][0]
            assert result['live'] is False and result['reason'] == reason, result
            assert query(conn, 'SELECT available FROM v24_cordis.resolve(%s,ARRAY[%s])',
                         (root['scope']['id'], 'negative-consumer'))[0][0] is False
            conn.rollback()
    assert live(db, consumer)['live'] is True
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, 'INSERT INTO v24_cordis.pins(id,consumer_fiber_id,consumer_episode_id,key,contribution_id,provider_epoch) '
                    "SELECT gen_random_uuid(),consumer_fiber_id,consumer_episode_id,'extra',contribution_id,provider_epoch "
                    'FROM v24_cordis.pins WHERE consumer_fiber_id=%s', (consumer['fiber_id'],))
        assert query(conn, 'SELECT v24_cordis.fiber_live_state(%s,%s)', (consumer['fiber_id'], ep))[0][0]['reason'] == 'pin_mismatch'
        conn.rollback()
    # Owner-only corrupt cycle must remain a graph diagnostic across all readers.
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, 'ALTER TABLE v24_cordis.fibers DISABLE TRIGGER fibers_immutable')
        query(conn, 'ALTER TABLE v24_cordis.fibers DISABLE TRIGGER fibers_graph')
        query(conn, 'UPDATE v24_cordis.fibers SET owner_id=%s,owner_episode_id=%s WHERE id=%s',
              (provider['fiber_id'], owner_of(db, provider)['episode_id'], consumer['fiber_id']))
        query(conn, 'UPDATE v24_cordis.fibers SET owner_id=%s,owner_episode_id=%s WHERE id=%s',
              (consumer['fiber_id'], ep, provider['fiber_id']))
        assert query(conn, 'SELECT v24_cordis.fiber_live_state(%s,%s)', (consumer['fiber_id'], ep))[0][0]['cycle'] is True
        assert query(conn, 'SELECT v24_cordis.activation_admission(%s,true)', (consumer['fiber_id'],))[0][0]['code'] == 'retry_with_closure'
        # sqlstate rolls the whole fixture back after verifying the resolver exception.
        sqlstate(conn, 'SELECT * FROM v24_cordis.resolve(%s,ARRAY[%s])', (root['scope']['id'], 'negative-consumer'), code='P0401')
    # Scope and owner closure immediately affect admission and resolution.
    for statement, params in [
        ('UPDATE v24_cordis.scopes SET closed_at=clock_timestamp() WHERE id=%s', (root['scope']['id'],)),
        ('UPDATE v24_cordis.fibers SET want_on=false WHERE id=%s', (root['fiber_id'],)),
        ("UPDATE v24_cordis.installs SET state='dispose_pending' WHERE id=%s", (root['install_id'],)),
    ]:
        with contextlib.closing(db.connect('owner')) as conn:
            query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
            query(conn, statement, params)
            assert query(conn, 'SELECT v24_cordis.fiber_live_state(%s,%s)', (consumer['fiber_id'], ep))[0][0]['live'] is False
            assert query(conn, 'SELECT available FROM v24_cordis.resolve(%s,ARRAY[%s])', (root['scope']['id'], 'negative-consumer'))[0][0] is False
            assert query(conn, 'SELECT v24_cordis.activation_admission(%s,true)', (consumer['fiber_id'],))[0][0] is not None
            conn.rollback()
    print('[CDP3-L5] exact require/view/pin keys, epoch/digest/check; scope and owner closure agree with resolver/admission')


def test_capacity_and_history(db, root):
    from test_activation import CONTRACT
    # Owner-built DAG proves bounded read semantics only; production paths above
    # prove creation/activation. No W3 release/close writer is introduced here.
    count = 512
    nodes = [dict(fiber=uuid.uuid4(), install=uuid.uuid4(), episode=uuid.uuid4(),
                  contribution=uuid.uuid4(), key=f'dag-{i}') for i in range(count)]
    scope = root['scope']['id']
    owner = owner_of(db, root)

    def dependencies(index):
        start = (1 << (index + 1).bit_length()) - 1
        # Dense shared edges between adjacent levels; no path enumeration.
        return sorted({j for j in (index * 2 + 1, index * 2 + 2, *range(start, start + 8))
                       if start <= j < min(511, 2 * start + 1)})

    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        for table, trigger in [('fibers', 'fibers_graph'), ('pins', 'pins_graph')]:
            query(conn, f'ALTER TABLE v24_cordis.{table} DISABLE TRIGGER {trigger}')
        for index, node in enumerate(nodes):
            # Shared dense layered DAG, with small depth and 512/513 distinct nodes.
            children = [nodes[j] for j in dependencies(index)]
            manifest = dict(requires=[c['key'] for c in children], provides=[dict(
                key=node['key'], descriptor={'capability': 'cap'}, contract_version='1')], priority=0, check={})
            query(conn, "INSERT INTO v24_cordis.installs(id,scope_id,owner_fiber_id,owner_episode_id,identity,version,"
                        "manifest,artifact_digest,contracts,state) VALUES(%s,%s,%s,%s,%s,'1',%s,%s,%s,'installed')",
                  (node['install'], scope, owner['fiber_id'], owner['episode_id'], node['key'], Json(manifest), 'a' * 64, Json({'cap': CONTRACT})))
            query(conn, 'INSERT INTO v24_cordis.fibers(id,install_id,owner_id,owner_episode_id,scope_id,want_on,control_seq) '
                        'VALUES(%s,%s,%s,%s,%s,true,1)',
                  (node['fiber'], node['install'], owner['fiber_id'], owner['episode_id'], scope))
            view = {c['key']: dict(contribution_id=str(c['contribution']), provider_fiber_id=str(c['fiber']),
                     provider_episode_id=str(c['episode']), provider_epoch=1, descriptor_digest=one(db,
                     "SELECT encode(sha256(convert_to(v24_cordis.canonical_json('{\"capability\":\"cap\"}'::jsonb),'UTF8')),'hex')"), contract_version='1') for c in children}
            query(conn, "INSERT INTO v24_cordis.episodes(id,fiber_id,epoch,state,committed_view,iterator) "
                        "VALUES(%s,%s,1,'active',%s,%s)", (node['episode'], node['fiber'], Json(view),
                        Json(dict(v=1, next_index=1, registered_through=0, control_seq=1))))
            query(conn, 'UPDATE v24_cordis.fibers SET current_episode_id=%s WHERE id=%s', (node['episode'], node['fiber']))
            query(conn, "INSERT INTO v24_cordis.contributions(id,fiber_id,episode_id,seq,kind,realm,key,descriptor,inverse,contract_version) "
                        "VALUES(%s,%s,%s,0,'service','root',%s,'{\"capability\":\"cap\"}','{\"op\":\"delete_row\"}','1')",
                  (node['contribution'], node['fiber'], node['episode'], node['key']))
        for index, node in enumerate(nodes[:511]):
            for j in dependencies(index):
                child = nodes[j]
                query(conn, 'INSERT INTO v24_cordis.pins(id,consumer_fiber_id,consumer_episode_id,key,contribution_id,provider_epoch) '
                            'VALUES(%s,%s,%s,%s,%s,1)', (uuid.uuid4(), node['fiber'], node['episode'], child['key'], child['contribution']))
        query(conn, 'SET CONSTRAINTS ALL IMMEDIATE')
        for table, trigger in [('fibers', 'fibers_graph'), ('pins', 'pins_graph')]:
            query(conn, f'ALTER TABLE v24_cordis.{table} ENABLE TRIGGER {trigger}')
        # Force the production deferred graph guard to validate the fixture once.
        query(conn, 'UPDATE v24_cordis.fibers SET want_on=want_on WHERE id=%s', (nodes[0]['fiber'],))
        conn.commit()
    result = one(db, 'SELECT v24_cordis.fiber_live_state(%s,%s)', (nodes[0]['fiber'], nodes[0]['episode']))
    assert result['live'] is True and result['visited_count'] == 512, result
    # Connect the extra node through a leaf. Mutations are negative fixtures,
    # rolled back before returning; the immutable declarations remain unchanged.
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        leaf, extra = nodes[255], nodes[511]
        query(conn, 'ALTER TABLE v24_cordis.installs DISABLE TRIGGER installs_immutable')
        query(conn, 'ALTER TABLE v24_cordis.episodes DISABLE TRIGGER episodes_immutable')
        query(conn, 'UPDATE v24_cordis.installs SET manifest=jsonb_set(manifest,\'{requires}\',%s) WHERE id=%s',
              (Json([extra['key']]), leaf['install']))
        query(conn, 'UPDATE v24_cordis.episodes SET committed_view=jsonb_build_object(%s::text,jsonb_build_object('
                    "'contribution_id',%s::text,'provider_fiber_id',%s::text,'provider_episode_id',%s::text,"
                    "'provider_epoch',1,'descriptor_digest',encode(sha256(convert_to(v24_cordis.canonical_json("
                    "'{\"capability\":\"cap\"}'::jsonb),'UTF8')),'hex'),'contract_version','1')) WHERE id=%s",
              (extra['key'], extra['contribution'], extra['fiber'], extra['episode'], leaf['episode']))
        query(conn, 'INSERT INTO v24_cordis.pins(id,consumer_fiber_id,consumer_episode_id,key,contribution_id,provider_epoch) '
                    'VALUES(%s,%s,%s,%s,%s,1)', (uuid.uuid4(), leaf['fiber'], leaf['episode'], extra['key'], extra['contribution']))
        result = query(conn, 'SELECT v24_cordis.fiber_live_state(%s,%s)', (nodes[0]['fiber'], nodes[0]['episode']))[0][0]
        assert result['closure_overflow'] is True and result['visited_count'] == 513, result
        sqlstate(conn, 'SELECT * FROM v24_cordis.resolve(%s,ARRAY[%s])', (scope, nodes[0]['key']), code='P0401')
    # Exact current write-closure bound, without historical parent recursion.
    scopes = [uuid.uuid4() for _ in range(513)]
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, 'INSERT INTO v24_cordis.scopes(id) SELECT unnest(%s::uuid[])', (scopes,))
        seed = [dict(t='scopes', id=str(i)) for i in scopes]
        assert len(query(conn, 'SELECT v24_cordis.discover_closure(%s)', (Json(seed[:512]),))[0][0]) == 512
        assert query(conn, 'SELECT v24_cordis.discover_closure(%s)', (Json(seed),))[0][0] is None
        conn.rollback()
    small = activate(db, root)
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, "INSERT INTO v24_cordis.episodes(id,fiber_id,epoch,state,committed_view,iterator,outcome,closed_at) "
                    "SELECT gen_random_uuid(),%s,n,'closing','{}',%s,'retire',now() FROM generate_series(2,602) n",
              (small['fiber_id'], Json(dict(v=1, next_index=0, registered_through=-1, control_seq=1))))
        conn.commit()
    from test_support import seed_parent, derive, successor_key
    ancestor, _ = seed_parent(db, 'command_reconcile', reconcile_payload(small['fiber_id'], 'on', 1), fiber=small['fiber_id'])
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        for _ in range(600):
            key = successor_key(ancestor)
            child = derive(db.roles['service'], key, 'command_reconcile')
            query(conn, "INSERT INTO v24_cordis.effects(id,parent_id,ordinal,fiber_id,kind,status,input,request_actor,outcome,settled_at) "
                        "VALUES(%s,%s,0,%s,'command_reconcile','succeeded',%s,%s,'{}',now())",
                  (child, ancestor, small['fiber_id'], Json(reconcile_payload(small['fiber_id'], 'advance', 1)), db.roles['service']))
            ancestor = child
        conn.commit()
    request = reconcile_payload(small['fiber_id'], 'advance', 1)
    effect, key = seed_child(db, ancestor, small['fiber_id'], request, episode=owner_of(db, small)['episode_id'])
    with contextlib.closing(db.connect('service')) as conn:
        _, outcome = command(db, conn, 'service', 'command_reconcile', request, key=key, effect=effect)
    applied(db, effect, outcome)
    assert live(db, small)['live'] is True
    print('[CDP3-L6] DAG dedup512/overflow513; exact write closure512/513; 601 closed generations do not inflate active work')


def test_withdraw_bounds(db, root):
    for count in (256, 257):
        payload = activate(db, root)
        fiber = payload['fiber_id']
        ep = owner_of(db, payload)['episode_id']
        # Oversized registration is not reachable through the 200-key envelope;
        # construct only the P5 ledger boundary, then run production Leave.
        mutate(db, "INSERT INTO v24_cordis.contributions(id,fiber_id,episode_id,seq,kind,realm,key,descriptor,inverse,contract_version) "
                   "SELECT gen_random_uuid(),%s,%s,n,'service','root',%s||n,'{}','{\"op\":\"delete_row\"}','1' "
                   "FROM generate_series(0,255) n", (fiber, ep, f'withdraw-{count}-'))
        # Nonservice obligations are owner fixture facts, not registrations.
        mutate(db, "INSERT INTO v24_cordis.contributions(id,fiber_id,episode_id,seq,kind,descriptor,inverse,contract_version) "
                   "VALUES(gen_random_uuid(),%s,%s,300,'reservation','{}','{\"op\":\"release_reservation\"}','1'),"
                   "(gen_random_uuid(),%s,%s,301,'child','{}','{\"op\":\"dispose_child\"}','1')", (fiber, ep, fiber, ep))
        if count == 257:
            mutate(db, "INSERT INTO v24_cordis.contributions(id,fiber_id,episode_id,seq,kind,descriptor,inverse,contract_version) "
                       "VALUES(gen_random_uuid(),%s,%s,302,'cell','{}','{\"op\":\"restore_prev\"}','1')", (fiber, ep))
        off, result, _ = commit_new(db, 'command_reconcile', reconcile_payload(fiber, 'off', 1))
        assert result['disposition'] == 'committed', result
        effect, outcome = child_call(db, off, reconcile_payload(fiber, 'advance', 2))
        if count == 257:
            with contextlib.closing(db.connect('service')) as conn:
                no_write(db, conn, effect, outcome, code='retry_with_closure', detail={'reason': 'withdraw_budget'})
        else:
            applied(db, effect, outcome)
            actual = rows(db, 'SELECT kind,withdrawn_at IS NOT NULL,released_at IS NOT NULL '
                             'FROM v24_cordis.contributions WHERE episode_id=%s', (ep,))
            assert actual.count(('service', True, False)) == 256
            assert actual.count(('child', False, False)) == actual.count(('reservation', False, False)) == 1
            event = one(db, 'SELECT payload FROM v24_cordis.events WHERE effect_id=%s', (effect,))
            expected = [str(row[0]) for row in rows(db, "SELECT id FROM v24_cordis.contributions WHERE episode_id=%s "
                                                     "AND kind='service' ORDER BY id::text", (ep,))]
            assert event['withdrawn_ids'] == expected
    print('[CDP3-L7] P5 exact256 withdrawal; 257 refuses before writes; child/reservation debts untouched')


def test_independent_validator(db, root):
    from test_support import function_defs, install_probe, set_probe
    payload, effect, outcome = reloading(db, root, ['validator-p2'])
    with contextlib.closing(db.connect('owner')) as conn:
        principal = query(conn, 'SELECT v24_cordis.principal_id(%s)', (db.roles['service'],))[0][0]
        closure = query(conn, 'SELECT v24_cordis.command_closure(%s,%s)',
                        ('command_reconcile', Json(outcome['body']['payload'])))[0][0]
        delta = query(conn, 'SELECT v24_cordis.interpret_reconcile(%s,%s,%s,%s)',
                      (effect, principal, Json(outcome), Json(closure)))[0][0]
    provider = activate(db, root, provides=['validator-good', 'validator-other'])
    consumer, _, _ = install(db, owner=owner_of(db, root), mode='existing',
                              existing=root['scope']['id'], requires=['validator-good'])
    parent, _, _ = p0(db, consumer['fiber_id'])
    p1_effect, p1_outcome = child_call(db, parent, reconcile_payload(consumer['fiber_id'], 'advance', 1))
    with contextlib.closing(db.connect('owner')) as conn:
        closure = query(conn, 'SELECT v24_cordis.command_closure(%s,%s)',
                        ('command_reconcile', Json(p1_outcome['body']['payload'])))[0][0]
        forged_p1 = query(conn, 'SELECT v24_cordis.interpret_reconcile(%s,%s,%s,%s)',
                          (p1_effect, principal, Json(p1_outcome), Json(closure)))[0][0]
        target = query(conn, 'SELECT contribution_id,provider_fiber_id,provider_episode_id,provider_epoch,'
                            'descriptor_digest,contract_version FROM v24_cordis.resolve(%s,ARRAY[%s])',
                       (root['scope']['id'], 'validator-other'))[0]
    # Internally coherent real ledger row, same provider, wrong resolved key.
    binding = dict(zip(('contribution_id', 'provider_fiber_id', 'provider_episode_id',
                        'provider_epoch', 'descriptor_digest', 'contract_version'),
                       (str(v) if isinstance(v, uuid.UUID) else v for v in target)))
    begin = forged_p1['domain'][0]
    begin['committed_view']['validator-good'] = binding
    begin['pins'][0].update({k: binding[k] for k in ('contribution_id', 'provider_episode_id', 'provider_epoch')})
    original = install_probe(db)['interpret_command']
    try:
        with contextlib.closing(db.connect('service')) as conn:
            set_probe(conn, forged_p1)
            no_write(db, conn, p1_effect, p1_outcome, code='retry_with_closure', detail={'reason': 'write_target'})
        # Expand only the read proof to reach independent target validation.
        with contextlib.closing(db.connect('owner')) as conn:
            before = snapshot(conn)
            expanded = query(conn, 'SELECT v24_cordis.discover_closure(%s)',
                             (Json(closure + [dict(t='contributions', id=binding['contribution_id'])]),))[0][0]
            rejected = query(conn, 'SELECT v24_cordis.validate_domain(%s,'
                                  'v24_cordis.principal_id(session_user),%s,%s,%s)',
                             (p1_effect, Json(p1_outcome), Json(forged_p1), Json(expanded)))[0][0]
            assert rejected['error'] == {'code': 'invalid_outcome', 'detail': {'reason': 'p1_target'}}, rejected
            assert snapshot(conn) == before
            conn.rollback()
        # Persist generation drift after obtaining the old, otherwise valid P2 delta.
        mutate(db, 'UPDATE v24_cordis.fibers SET control_seq=2 WHERE id=%s', (payload['fiber_id'],))
        with contextlib.closing(db.connect('service')) as conn:
            set_probe(conn, delta)
            no_write(db, conn, effect, outcome, code='invalid_outcome')
        # A forged Raise cause/event cannot substitute for the selected Divert.
        ep = owner_of(db, payload)['episode_id']
        with contextlib.closing(db.connect('owner')) as conn:
            selected = query(conn, 'SELECT v24_cordis.reconcile_branch(%s,\'advance\',1)', (payload['fiber_id'],))[0][0]
            forged = query(conn, 'SELECT v24_cordis.closing_delta(%s,%s)', (payload['fiber_id'], Json(selected)))[0][0]
        forged['events'][0]['payload']['reason'] = 'dependency_lost'
        with contextlib.closing(db.connect('service')) as conn:
            set_probe(conn, forged)
            no_write(db, conn, effect, outcome, code='invalid_outcome', detail={'reason': 'teardown_diagnosis'})
    finally:
        replace_function(db, original)
    # Faulty triggers cannot silently suppress a production domain write.
    payload, effect, outcome = reloading(db, root, ['postcheck'])
    replace_function(db, '''CREATE FUNCTION v24_cordis.w2_suppress() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RETURN NULL; END $$;
CREATE TRIGGER w2_suppress BEFORE INSERT ON v24_cordis.contributions FOR EACH ROW EXECUTE FUNCTION v24_cordis.w2_suppress();''')
    try:
        with contextlib.closing(db.connect('owner')) as conn:
            before = snapshot(conn)
        with contextlib.closing(db.connect('service')) as conn:
            sqlstate(conn, 'SELECT v24_cordis.advance(%s,%s)', (effect, Json(outcome)), code='23514')
        with contextlib.closing(db.connect('owner')) as conn:
            assert snapshot(conn) == before
    finally:
        replace_function(db, 'DROP TRIGGER w2_suppress ON v24_cordis.contributions; DROP FUNCTION v24_cordis.w2_suppress();')
    print('[CDP3-L8] independent validator rejects wrong P1 target, old P2 vs Divert and forged diagnosis; fresh postwrite SQL detects suppressed insert')


def main():
    with Server() as server, TestDB(server) as db:
        root, _, _ = install(db)
        phases(db, uuid.UUID(root['fiber_id']), 0)
        test_failure_types(db)
        test_transitive(db, root)
        test_guards_and_types(db, root)
        test_fault_atomicity(db, root)
        test_classified_and_divert(db, root)
        test_live_negatives(db, root)
        test_withdraw_bounds(db, root)
        test_independent_validator(db, root)
        test_capacity_and_history(db, root)
    print('[passed] CDP3-L')


if __name__ == '__main__':
    main()
