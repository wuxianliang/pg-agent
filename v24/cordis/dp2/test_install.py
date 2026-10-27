"""CDP2-I: W2 install declaration, scope/owner admission, resolver and W2 guards.

Run with: uv run python v24/cordis/dp2/test_install.py
Every database is disposable. Production install/advance/DDL are exercised; the only
replaced function is interpret_command, and only for the forged-delta section at the end.
"""
from __future__ import annotations
import contextlib
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dp1'))

import psycopg2
from psycopg2.extras import Json

from test_support import (Server, TestDB, TABLES, snapshot, query, api, command, no_write,
                          install_payload, seed_fiber, seed_episode, seed_provider,
                          install_delta, active_owner, install_probe, set_probe,
                          replace_function, sqlstate, descriptor_digest, assert_helper_budget)

REPLAYS = ({'repeat': True, 'concurrent': True}, {'repeat': True, 'concurrent': False},
           {'repeat': False, 'concurrent': True}, {'repeat': False, 'concurrent': False})


def run(db, payload, alias='service'):
    with contextlib.closing(db.connect(alias)) as conn:
        effect, out = command(db, conn, alias, 'command_install', payload)
        result = api(conn, effect, out)
        conn.commit()
    return effect, result, out


def bad(db, payload, code, reason=None):
    with contextlib.closing(db.connect('service')) as conn:
        effect, out = command(db, conn, 'service', 'command_install', payload)
        result = no_write(db, conn, effect, out, code)
    if reason is not None:
        assert result['error']['detail'].get('reason') == reason, result
    return result


def commit_rejected(db, statements, params=(), code='23514', message=None):
    with contextlib.closing(db.connect('owner')) as conn:
        before = snapshot(conn)
        before = {k: list(v) for k, v in before.items()}
        conn.rollback()
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        try:
            with conn.cursor() as c:
                for statement, values in statements:
                    c.execute(statement, values)
            conn.commit()
        except psycopg2.Error as exc:
            conn.rollback()
            assert exc.pgcode == code, (exc.pgcode, str(exc))
            if message is not None:
                assert message in str(exc), str(exc)
        else:
            raise AssertionError('expected SQLSTATE ' + code)
    with contextlib.closing(db.connect('owner')) as conn:
        assert snapshot(conn) == before, 'guard rejection changed rows'
        conn.rollback()


def one(db, statement, params=()):
    with contextlib.closing(db.connect('owner')) as conn:
        return query(conn, statement, params)[0][0]


def rows(db, statement, params=()):
    with contextlib.closing(db.connect('owner')) as conn:
        return query(conn, statement, params)


def owner_pair(db, *, want_on=True, state='active', current=True, iterator=None,
               install_state='installed', disposed=False, retire=False, failure=None):
    root = active_owner(db)
    if state == 'active':
        episode = root['episode']
        if iterator is None:
            query_owner(db, 'UPDATE v24_cordis.episodes SET iterator=%s WHERE id=%s',
                        (Json(dict(v=1, next_index=0, registered_through=-1, control_seq=0)),
                         episode))
    else:
        episode = seed_episode(db, root['fiber'], epoch=2, state=state, control_seq=0)
    query_owner(db, 'UPDATE v24_cordis.fibers SET want_on=%s,current_episode_id=%s,'
                    'disposed_at=%s,retire_started_at=%s,failure=%s WHERE id=%s',
                (want_on, (episode if current else None),
                 ('2020-01-01' if disposed else None), ('2020-01-01' if retire else None),
                 (Json(failure) if failure is not None else None), root['fiber']))
    query_owner(db, 'UPDATE v24_cordis.installs SET state=%s WHERE id=%s',
                (install_state, root['install']))
    root['episode'] = episode
    return root


def query_owner(db, statement, params=()):
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, statement, params)
        conn.commit()


def fresh_owner(db, *, want_on=True, state='active', current=True, iterator=None,
                install_state='installed', disposed=False, retire=False, failure=None):
    root = active_owner(db)
    scope, install, fiber, episode = (uuid.uuid4() for _ in range(4))
    if failure is not None:
        failure = dict(v=1, control_seq=0, episode_id=str(episode), phase='p2',
                       code='provide_conflict', reason='address_conflict', key='fixture')
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, 'INSERT INTO v24_cordis.scopes(id,parent_id) VALUES(%s,%s)',
              (scope, root['scope']))
        query(conn, "INSERT INTO v24_cordis.installs(id,scope_id,owner_fiber_id,owner_episode_id,"
                    "identity,version,manifest,artifact_digest,contracts,state) VALUES"
                    "(%s,%s,%s,%s,%s,'1',%s,%s,'{}',%s)",
              (install, scope, root['fiber'], root['episode'], 'fresh-' + install.hex[:8],
               Json(dict(requires=[], provides=[], priority=0, check={})), 'a' * 64,
               install_state))
        query(conn, 'INSERT INTO v24_cordis.fibers(id,install_id,owner_id,owner_episode_id,'
                    'scope_id,want_on,current_episode_id,disposed_at,retire_started_at,failure) '
                    'VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
              (fiber, install, root['fiber'], root['episode'], scope, want_on,
               (episode if current else None), ('2020-01-01' if disposed else None),
               ('2020-01-01' if retire else None), (Json(failure) if failure is not None else None)))
        query(conn, 'INSERT INTO v24_cordis.episodes(id,fiber_id,epoch,state,committed_view,iterator) '
                    'VALUES(%s,%s,0,%s,%s,%s)',
              (episode, fiber, state,
               Json({'fresh': {'contribution_id': str(fiber)}}),
               Json(iterator or dict(v=1, next_index=0, registered_through=-1, control_seq=0))))
        conn.commit()
    return dict(fiber=fiber, episode=episode, install=install, scope=scope, root=root)


def valid_declaration(scope_mode='existing', parent=None):
    payload = install_payload()
    payload['identity'] = 'decl-' + payload['install_id'][:8]
    if scope_mode == 'existing':
        payload['scope'] = dict(mode='existing', id=str(scope_id_holder[0]))
    elif scope_mode == 'child':
        payload['scope'] = dict(mode='child', id=str(uuid.uuid4()),
                                parent_id=str(parent), realm_overrides={'svc': 'ra'})
    payload['manifest'] = dict(
        requires=['need.a', 'need.b'],
        provides=[dict(key='svc.a', descriptor=dict(capability='cap.a', name='a'),
                       contract_version='1'),
                  dict(key='svc.b', descriptor=dict(capability='cap.b', name='b'),
                       contract_version='2')],
        priority=-7,
        check={'need.a': None,
               'need.b': dict(v=1, op='equals', path=['nested', 'ok'], value=True)})
    payload['contracts'] = {
        'cap.a': dict(contract_version='1', handler_digest='a' * 64,
                      replay=dict(repeat=True, concurrent=False)),
        'cap.b': dict(contract_version='2', handler_digest='b' * 64,
                      replay=dict(repeat=False, concurrent=True)),
    }
    payload['policy_ref'] = 'chat_tool'
    return payload


scope_id_holder = [None]


def test_bootstrap(db):
    payload = install_payload()
    effect, result, out = run(db, payload)
    assert result.get('disposition') == 'committed', result
    assert one(db, 'SELECT fiber_id FROM v24_cordis.effects WHERE id=%s', (effect,)) == uuid.UUID(payload['fiber_id'])
    assert one(db, 'SELECT episode_id FROM v24_cordis.effects WHERE id=%s', (effect,)) is None
    assert one(db, 'SELECT state FROM v24_cordis.installs WHERE id=%s', (payload['install_id'],)) == 'installed'
    assert rows(db, 'SELECT want_on,control_seq,current_episode_id FROM v24_cordis.fibers WHERE id=%s',
                (payload['fiber_id'],)) == [(False, 0, None)]
    assert one(db, 'SELECT count(*) FROM v24_cordis.episodes WHERE fiber_id=%s', (payload['fiber_id'],)) == 0
    assert one(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id=%s', (payload['fiber_id'],)) == 0
    assert one(db, 'SELECT count(*) FROM v24_cordis.pins WHERE consumer_fiber_id=%s', (payload['fiber_id'],)) == 0
    assert one(db, 'SELECT count(*) FROM v24_cordis.effects WHERE kind<>%s', ('command_install',)) == 0
    event = rows(db, 'SELECT entity_type,entity_id,event_kind,payload FROM v24_cordis.events WHERE effect_id=%s',
                 (effect,))
    assert [(r[0], str(r[1]), r[2]) for r in event] == [('install', payload['install_id'], 'install_created')]
    assert event[0][3] == {'scope_id': payload['scope']['id'], 'scope_created': True,
                           'fiber_id': payload['fiber_id'], 'owner_fiber_id': None,
                           'owner_episode_id': None, 'child_contribution_id': None}
    # Replay is exact and does not create a second install or event.
    with contextlib.closing(db.connect('service')) as conn:
        replay = api(conn, effect, out)
        conn.commit()
    assert replay == result
    assert one(db, 'SELECT count(*) FROM v24_cordis.installs') == 1
    assert one(db, 'SELECT count(*) FROM v24_cordis.events') == 1
    scope_id_holder[0] = uuid.UUID(payload['scope']['id'])
    # A second ownerless root is refused before DML; root wire v1 requires realm_overrides.
    bad(db, install_payload(), 'invalid_args', 'unique_root')
    no_overrides = install_payload()
    no_overrides['scope'].pop('realm_overrides')
    bad(db, no_overrides, 'invalid_args', 'install_payload')
    # A root scene is created before the guard can see a second root; first use a child scope.
    print('[CDP2-I1] direct root install is data-only; replay exact; second ownerless root refused')


def test_ownerless_existing(db):
    scope = uuid.uuid4()
    query_owner(db, 'INSERT INTO v24_cordis.scopes(id) VALUES(%s)', (scope,))
    payload = install_payload(mode='existing', existing_scope=scope)
    effect, result, out = run(db, payload)
    assert result.get('disposition') == 'committed', result
    assert one(db, 'SELECT count(*) FROM v24_cordis.fibers WHERE owner_id IS NULL') == 1
    assert one(db, 'SELECT count(*) FROM v24_cordis.episodes') == 0
    print('[CDP2-I2] ownerless install into an existing open scope; still exactly one root')


def test_admission(db):
    root = owner_pair(db)
    owner = dict(fiber_id=str(root['fiber']), episode_id=str(root['episode']))
    before_seq = one(db, "SELECT (iterator->>'registered_through')::int FROM v24_cordis.episodes WHERE id=%s",
                     (root['episode'],))
    next_index = one(db, "SELECT (iterator->>'next_index')::int FROM v24_cordis.episodes WHERE id=%s",
                     (root['episode'],))
    payload = install_payload(mode='existing', existing_scope=scope_id_holder[0], owner=owner)
    payload['identity'] = 'owner-existing'
    effect, result, out = run(db, payload)
    assert result.get('disposition') == 'committed', result
    assert rows(db, 'SELECT fiber_id,episode_id FROM v24_cordis.effects WHERE id=%s', (effect,)) == \
        [(root['fiber'], root['episode'])]
    ledger = rows(db, 'SELECT seq,kind,realm,key,descriptor,inverse,contract_version '
                      'FROM v24_cordis.contributions WHERE fiber_id=%s AND episode_id=%s '
                      'ORDER BY seq DESC LIMIT 1', (root['fiber'], root['episode']))
    assert ledger == [(before_seq + 1, 'child', None, None,
                       {'child_fiber_id': payload['fiber_id']}, {'op': 'dispose_child'}, '1')], ledger
    assert one(db, "SELECT (iterator->>'registered_through')::int FROM v24_cordis.episodes WHERE id=%s",
               (root['episode'],)) == before_seq + 1
    assert one(db, "SELECT (iterator->>'next_index')::int FROM v24_cordis.episodes WHERE id=%s",
               (root['episode'],)) == next_index
    assert rows(db, 'SELECT owner_id,owner_episode_id FROM v24_cordis.fibers WHERE id=%s',
                (payload['fiber_id'],)) == [(root['fiber'], root['episode'])]
    # Caller-supplied UUID text is canonicalized in domain rows and the event.
    upper = install_payload(mode='existing', existing_scope=scope_id_holder[0], owner=owner)
    upper['identity'] = 'owner-upper'
    upper['scope']['id'] = str(upper['scope']['id']).upper()
    upper['install_id'] = upper['install_id'].upper()
    upper['fiber_id'] = upper['fiber_id'].upper()
    upper['owner'] = dict(fiber_id=owner['fiber_id'].upper(), episode_id=owner['episode_id'].upper())
    _, result, _ = run(db, upper)
    assert result.get('disposition') == 'committed', result
    event = rows(db, "SELECT entity_id::text,payload->>'scope_id',payload->>'fiber_id',"
                     "payload->>'owner_fiber_id',payload->>'owner_episode_id',"
                     "payload->>'child_contribution_id' FROM v24_cordis.events "
                     "WHERE entity_id=%s AND event_kind='install_created'", (upper['install_id'],))[0]
    assert event[:5] == (upper['install_id'].lower(), upper['scope']['id'].lower(),
                         upper['fiber_id'].lower(), owner['fiber_id'].lower(),
                         owner['episode_id'].lower()), event
    assert event[5] is not None
    # A child scope is legal for the same owner, with the declared overrides.
    child = install_payload()
    child['scope'] = dict(mode='child', id=str(uuid.uuid4()), parent_id=str(scope_id_holder[0]),
                          realm_overrides={'svc': 'rc'})
    child['identity'] = 'owner-child'
    child['owner'] = owner
    _, result, _ = run(db, child)
    assert result.get('disposition') == 'committed', result
    assert rows(db, 'SELECT parent_id,realm_overrides FROM v24_cordis.scopes WHERE id=%s',
                (child['scope']['id'],)) == [(scope_id_holder[0], {'svc': 'rc'})]
    # Ownerful root scope is not a legal combination in W2 wire v1.
    bad(db, install_payload(owner=owner), 'invalid_args', 'install_scope_mode')
    # Ownerless child scope is likewise not a legal combination.
    ownerless_child = install_payload()
    ownerless_child['scope'] = dict(mode='child', id=str(uuid.uuid4()),
                                    parent_id=str(scope_id_holder[0]), realm_overrides={})
    bad(db, ownerless_child, 'invalid_args', 'install_scope_mode')
    # Missing/closed targets and owner states.
    missing = install_payload(mode='existing', existing_scope=uuid.uuid4(), owner=owner)
    bad(db, missing, 'not_found_or_denied', 'install_scope')
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'INSERT INTO v24_cordis.scopes(id,closed_at) VALUES(%s,now())', (uuid.uuid4(),))
        closed_id = query(conn, 'SELECT id FROM v24_cordis.scopes WHERE closed_at IS NOT NULL')[0][0]
        conn.commit()
    bad(db, install_payload(mode='existing', existing_scope=closed_id, owner=owner),
        'scope_closed', 'install_scope')
    missing_parent = install_payload()
    missing_parent['scope'] = dict(mode='child', id=str(uuid.uuid4()), parent_id=str(uuid.uuid4()),
                                   realm_overrides={})
    bad(db, missing_parent, 'not_found_or_denied', 'install_parent')
    bad(db, install_payload(mode='existing', existing_scope=scope_id_holder[0],
                            owner=dict(fiber_id=str(uuid.uuid4()), episode_id=str(uuid.uuid4()))),
        'not_found_or_denied', 'install_owner')
    for mutate, reason in (
            ({'want_on': False}, 'install_owner'), ({'disposed': True}, 'install_owner'),
            ({'retire': True}, 'install_owner'), ({'current': False}, 'install_owner'),
            ({'state': 'closing'}, 'install_owner'),
            ({'install_state': 'preparing'}, 'install_owner_install'),
            ({'failure': {'control_seq': 0}}, 'install_owner_failure')):
        owner_state = fresh_owner(db, **mutate)
        bad(db, install_payload(mode='existing', existing_scope=scope_id_holder[0],
                                owner=dict(fiber_id=str(owner_state['fiber']),
                                           episode_id=str(owner_state['episode']))),
            'owner_closing', reason)
    for bad_iterator in ({'bad': 1}, {'v': 1, 'next_index': 0, 'registered_through': -1},
                         {'v': '1', 'next_index': 0, 'registered_through': -1, 'control_seq': 0},
                         {'v': 1, 'next_index': 0, 'registered_through': -1, 'control_seq': 0,
                          'extra': 0}):
        owner_state = fresh_owner(db, iterator=bad_iterator)
        bad(db, install_payload(mode='existing', existing_scope=scope_id_holder[0],
                                owner=dict(fiber_id=str(owner_state['fiber']),
                                           episode_id=str(owner_state['episode']))),
            'invalid_args', 'install_owner_iterator')
    # UUID and identity collisions.
    collision = install_payload(mode='existing', existing_scope=scope_id_holder[0], owner=owner)
    collision['install_id'] = payload['install_id']
    bad(db, collision, 'invalid_args', 'install_id')
    collision = install_payload(mode='existing', existing_scope=scope_id_holder[0], owner=owner)
    collision['fiber_id'] = payload['fiber_id']
    bad(db, collision, 'invalid_args', 'fiber_id')
    collision = install_payload(mode='existing', existing_scope=scope_id_holder[0], owner=owner)
    collision['identity'] = payload['identity']
    collision['version'] = payload['version']
    bad(db, collision, 'install_identity_conflict', 'install_address')
    # Existing scope id used as a new root/child scope id.
    duplicate_scope = install_payload()
    duplicate_scope['scope']['id'] = str(scope_id_holder[0])
    bad(db, duplicate_scope, 'invalid_args', 'scope_id')
    # Unsupported overlay/intercept are 0A000, not silently ignored.
    overlay = install_payload(mode='existing', existing_scope=scope_id_holder[0], owner=owner)
    overlay['overlay'] = {'x': 'y'}
    with contextlib.closing(db.connect('service')) as conn:
        effect, out = command(db, conn, 'service', 'command_install', overlay)
        sqlstate(conn, 'SELECT v24_cordis.advance(%s,%s)', (effect, Json(out)), code='0A000')
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, 'INSERT INTO v24_cordis.scopes(id,intercept) VALUES(%s,%s)',
              (uuid.uuid4(), Json({'x': 'y'})))
        intercept_id = query(conn, "SELECT id FROM v24_cordis.scopes WHERE intercept<>'{}'")[0][0]
        conn.commit()
    intercept = install_payload(mode='existing', existing_scope=intercept_id, owner=owner)
    with contextlib.closing(db.connect('service')) as conn:
        effect, out = command(db, conn, 'service', 'command_install', intercept)
        sqlstate(conn, 'SELECT v24_cordis.advance(%s,%s)', (effect, Json(out)), code='0A000')
    print('[CDP2-I3] owner ledger seq/descriptor/inverse/progress; scope/owner/UUID/identity/0A000 negatives')


def test_declaration(db):
    root = owner_pair(db)
    owner = dict(fiber_id=str(root['fiber']), episode_id=str(root['episode']))
    payload = valid_declaration(scope_mode='existing')
    payload['owner'] = owner
    effect, result, out = run(db, payload)
    assert result.get('disposition') == 'committed', result
    stored = rows(db, 'SELECT manifest,contracts,policy_ref,state FROM v24_cordis.installs WHERE id=%s',
                  (payload['install_id'],))[0]
    assert stored[0] == payload['manifest']
    assert stored[1] == payload['contracts']
    assert stored[2] == 'chat_tool' and stored[3] == 'installed'
    long_key = 'k' * 256
    long = valid_declaration(scope_mode='existing')
    long['owner'] = owner
    long['identity'] = 'long-keys'
    long['manifest']['requires'] = [long_key]
    long['manifest']['check'] = {long_key: None}
    long['manifest']['provides'] = [dict(key='p' * 256,
                                         descriptor=dict(capability='cap.long'), contract_version='1')]
    long['contracts'] = {'cap.long': dict(contract_version='1', handler_digest='c' * 64,
                                          replay=dict(repeat=False, concurrent=False))}
    _, result, _ = run(db, long)
    assert result.get('disposition') == 'committed', result
    for combo in REPLAYS:
        child = valid_declaration(scope_mode='existing')
        child['owner'] = owner
        child['contracts']['cap.a']['replay'] = dict(combo)
        _, result, _ = run(db, child)
        assert result.get('disposition') == 'committed', result
    assert one(db, 'SELECT count(*) FROM v24_cordis.effects WHERE kind<>%s', ('command_install',)) == 0
    bad_manifest = {
        'missing requires': {'provides': [], 'priority': 0, 'check': {}},
        'extra key': {'requires': [], 'provides': [], 'priority': 0, 'check': {}, 'x': 1},
        'requires not array': {'requires': {}, 'provides': [], 'priority': 0, 'check': {}},
        'requires duplicate': {'requires': ['a', 'a'], 'provides': [], 'priority': 0, 'check': {}},
        'requires non-string': {'requires': [1], 'provides': [], 'priority': 0, 'check': {}},
        'requires too long': {'requires': ['k' * 257], 'provides': [], 'priority': 0, 'check': {}},
        'provides extra key': {'requires': [], 'provides': [dict(key='k', descriptor={},
                                                                 contract_version='1', x=1)],
                               'priority': 0, 'check': {}},
        'provides duplicate': {'requires': [], 'provides': [
            dict(key='k', descriptor=dict(capability='cap.a'), contract_version='1'),
            dict(key='k', descriptor=dict(capability='cap.a'), contract_version='1')],
            'priority': 0, 'check': {}},
        'missing contract': {'requires': [], 'provides': [
            dict(key='k', descriptor=dict(capability='cap.missing'), contract_version='1')],
            'priority': 0, 'check': {}},
        'contract version mismatch': {'requires': [], 'provides': [
            dict(key='k', descriptor=dict(capability='cap.a'), contract_version='2')],
            'priority': 0, 'check': {}},
        'priority float': {'requires': [], 'provides': [], 'priority': 1.5, 'check': {}},
        'priority overflow': {'requires': [], 'provides': [], 'priority': 2147483648, 'check': {}},
        'check not required': {'requires': [], 'provides': [], 'priority': 0,
                               'check': {'ghost': None}},
        'check extra key': {'requires': ['a'], 'provides': [], 'priority': 0,
                            'check': {'a': dict(v=1, op='equals', path=['x'], value=1, y=1)}},
        'check path empty': {'requires': ['a'], 'provides': [], 'priority': 0,
                             'check': {'a': dict(v=1, op='equals', path=[], value=1)}},
        'check path long': {'requires': ['a'], 'provides': [], 'priority': 0,
                            'check': {'a': dict(v=1, op='equals', path=['x'] * 9, value=1)}},
        'check op': {'requires': ['a'], 'provides': [], 'priority': 0,
                     'check': {'a': dict(v=1, op='contains', path=['x'], value=1)}},
        'check version': {'requires': ['a'], 'provides': [], 'priority': 0,
                          'check': {'a': dict(v=2, op='equals', path=['x'], value=1)}},
    }
    for label, manifest in bad_manifest.items():
        payload = install_payload(mode='existing', existing_scope=scope_id_holder[0], owner=owner)
        payload['identity'] = 'bad-' + label.replace(' ', '-')
        payload['manifest'] = manifest
        bad(db, payload, 'invalid_args', 'install_payload')
    for label, contracts in (
            ('contract extra', {'cap.a': dict(contract_version='1', handler_digest='a' * 64,
                                              replay=dict(repeat=True, concurrent=True), x=1)}),
            ('digest upper', {'cap.a': dict(contract_version='1', handler_digest='A' * 64,
                                            replay=dict(repeat=True, concurrent=True))}),
            ('replay string', {'cap.a': dict(contract_version='1', handler_digest='a' * 64,
                                             replay=dict(repeat='yes', concurrent=True))}),
            ('replay missing', {'cap.a': dict(contract_version='1', handler_digest='a' * 64,
                                              replay=dict(repeat=True))})):
        payload = install_payload(mode='existing', existing_scope=scope_id_holder[0], owner=owner)
        payload['identity'] = 'bad-' + label.replace(' ', '-')
        payload['contracts'] = contracts
        payload['manifest'] = dict(requires=[], provides=[
            dict(key='k', descriptor=dict(capability='cap.a'), contract_version='1')],
            priority=0, check={})
        bad(db, payload, 'invalid_args', 'install_payload')
    for label, mutate in (
            ('overlay type', lambda p: p.update(overlay=[])),
            ('policy other', lambda p: p.update(policy_ref='other')),
            ('owner partial', lambda p: p.update(owner={'fiber_id': owner['fiber_id']})),
            ('scope extra', lambda p: p['scope'].update(x=1)),
            ('identity empty', lambda p: p.update(identity='')),):
        payload = install_payload(mode='existing', existing_scope=scope_id_holder[0], owner=owner)
        payload['identity'] = 'bad-' + label.replace(' ', '-')
        mutate(payload)
        bad(db, payload, 'invalid_args')
    print('[CDP2-I4] declaration/contracts/check policy and all four replay rights; malformed shapes zero-write')


def test_resolver(db):
    root_scope = scope_id_holder[0]
    ra, rc, b, d = (uuid.uuid4() for _ in range(4))
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, 'INSERT INTO v24_cordis.scopes(id,parent_id,realm_overrides) VALUES'
                    '(%s,%s,%s),(%s,%s,%s),(%s,%s,%s)',
              (ra, root_scope, Json({'svc': 'ra'}), rc, root_scope, Json({'svc': 'rc'}),
               b, root_scope, Json({})))
        query(conn, 'INSERT INTO v24_cordis.scopes(id,parent_id,realm_overrides) VALUES(%s,%s,%s)',
              (d, rc, Json({})))
        conn.commit()
    providers = {}
    for realm in ('root', 'ra', 'rc'):
        providers[realm] = seed_provider(db, realm=realm, key='svc')
        query_owner(db, 'UPDATE v24_cordis.fibers SET want_on=true WHERE id=%s',
                    (providers[realm]['fiber'],))
    extra = {}
    for key in ('svc-want', 'svc-disposed', 'svc-failure', 'svc-install'):
        extra[key] = seed_provider(db, realm='root', key=key)
        query_owner(db, 'UPDATE v24_cordis.fibers SET want_on=true WHERE id=%s',
                    (extra[key]['fiber'],))
    def resolved(scope, keys):
        with contextlib.closing(db.connect('owner')) as conn:
            before = snapshot(conn)
            conn.rollback()
            with conn.cursor() as c:
                c.execute('SELECT * FROM v24_cordis.resolve(%s,%s)', (scope, keys))
                got = c.fetchall()
                conn.rollback()
            with conn.cursor() as c:
                c.execute('SELECT to_jsonb(t)::text FROM v24_cordis.scopes t ORDER BY id')
                after = c.fetchall()
                conn.rollback()
        return got
    got = resolved(b, ['svc'])
    assert len(got) == 1 and got[0][0] == 'svc' and got[0][8] is True
    assert got[0][6] == providers['root']['digest'] and got[0][7] == '1'
    assert resolved(ra, ['svc'])[0][1] != got[0][1]
    assert resolved(d, ['svc'])[0][1] == resolved(rc, ['svc'])[0][1]
    assert resolved(b, ['missing']) == [('missing', None, None, None, None, None, None, None, False)]
    assert resolved(uuid.uuid4(), ['svc']) == [('svc', None, None, None, None, None, None, None, False)]
    assert len(resolved(b, [f'k{i}' for i in range(257)])) == 0
    assert resolved(b, [None]) == []
    assert len(resolved(b, ['svc', 'missing'])) == 2
    # The nearest override wins; there is no fallback across realms.
    query_owner(db, 'UPDATE v24_cordis.scopes SET realm_overrides=%s WHERE id=%s',
                (Json({'svc': 'missing-realm'}), b))
    assert resolved(b, ['svc'])[0][8] is False
    query_owner(db, 'UPDATE v24_cordis.scopes SET realm_overrides=%s WHERE id=%s', (Json({}), b))
    # Unavailable providers make the key unavailable.
    want = extra['svc-want']
    query_owner(db, 'UPDATE v24_cordis.fibers SET want_on=false WHERE id=%s', (want['fiber'],))
    assert resolved(b, ['svc-want'])[0][8] is False
    disposed = extra['svc-disposed']
    query_owner(db, 'UPDATE v24_cordis.fibers SET disposed_at=now() WHERE id=%s', (disposed['fiber'],))
    assert resolved(b, ['svc-disposed'])[0][8] is False
    failure = extra['svc-failure']
    query_owner(db, "UPDATE v24_cordis.fibers SET failure=v24_cordis.failure_v1(0,%s,'p2',"
                    "'provide_conflict','address_conflict',%s) WHERE id=%s",
                (failure['episode'], failure['key'], failure['fiber']))
    assert resolved(b, ['svc-failure'])[0][8] is False
    preparing = extra['svc-install']
    query_owner(db, 'UPDATE v24_cordis.installs SET state=%s WHERE id=(SELECT install_id FROM '
                    'v24_cordis.fibers WHERE id=%s)', ('preparing', preparing['fiber']))
    assert resolved(b, ['svc-install'])[0][8] is False
    query_owner(db, 'UPDATE v24_cordis.installs SET state=%s WHERE id=(SELECT install_id FROM '
                    'v24_cordis.fibers WHERE id=%s)', ('installed', preparing['fiber']))
    assert resolved(b, ['svc-install'])[0][8] is True
    print('[CDP2-I5] nearest realm override, root default, no cross-realm fallback, provider admission, 256 bound')


def test_closed_resolver(server):
    with TestDB(server) as db:
        payload = install_payload()
        run(db, payload)
        child = uuid.uuid4()
        query_owner(db, 'INSERT INTO v24_cordis.scopes(id,parent_id) VALUES(%s,%s)',
                    (child, payload['scope']['id']))
        provider = seed_provider(db, realm='root', key='svc')
        query_owner(db, 'UPDATE v24_cordis.fibers SET want_on=true WHERE id=%s', (provider['fiber'],))
        with contextlib.closing(db.connect('owner')) as conn:
            assert query(conn, 'SELECT available FROM v24_cordis.resolve(%s,%s)',
                         (child, ['svc']))[0][0] is True
            conn.rollback()
        query_owner(db, 'UPDATE v24_cordis.scopes SET closed_at=now() WHERE id=%s',
                    (payload['scope']['id'],))
        with contextlib.closing(db.connect('owner')) as conn:
            assert query(conn, 'SELECT available FROM v24_cordis.resolve(%s,%s)',
                         (child, ['svc']))[0][0] is False
            conn.rollback()
    print('[CDP2-I5b] a closed scope ancestor makes the whole resolver chain unavailable')


def test_guards(db):
    root = active_owner(db)
    # A second ownerless root is rejected at COMMIT.
    commit_rejected(db, [('INSERT INTO v24_cordis.fibers(id,install_id,scope_id) VALUES(%s,%s,%s)',
                          (uuid.uuid4(), root['install'], root['scope']))],
                    message='fiber graph multiple roots')
    # A legal owner edge commits; then a self pin makes a cycle.
    child = seed_fiber(db, prefix='guard-child')
    contribution = uuid.uuid4()
    episode = seed_episode(db, child['fiber'], epoch=1, state='active', control_seq=0)
    query_owner(db, "INSERT INTO v24_cordis.contributions(id,fiber_id,episode_id,seq,kind,realm,key,"
                    "descriptor,inverse,contract_version) VALUES(%s,%s,%s,0,'service','r','guard',"
                    "'{}','{\"op\":\"delete_row\"}','1')",
                (contribution, child['fiber'], episode))
    commit_rejected(db, [('INSERT INTO v24_cordis.pins(id,consumer_fiber_id,consumer_episode_id,'
                          'key,contribution_id,provider_epoch) VALUES(%s,%s,%s,%s,%s,1)',
                          (uuid.uuid4(), child['fiber'], episode, 'self', contribution))],
                    message='fiber graph cycle')
    run = uuid.uuid4()
    commit_rejected(db, [
        ('INSERT INTO v24_cordis.runs(id,owner_fiber_id,owner_episode_id,scope_id,remaining_steps) '
         'VALUES(%s,%s,%s,%s,1)', (run, child['fiber'], episode, child['scope'])),
        ('INSERT INTO v24_cordis.pins(id,consumer_run_id,key,contribution_id,provider_epoch) '
         'VALUES(%s,%s,%s,%s,1)', (uuid.uuid4(), run, 'self-run', contribution))],
                    message='fiber graph cycle')
    # A disposed consumer is not part of the live DAG, so its self pin is legal.
    query_owner(db, 'UPDATE v24_cordis.fibers SET disposed_at=now() WHERE id=%s', (child['fiber'],))
    query_owner(db, 'INSERT INTO v24_cordis.pins(id,consumer_fiber_id,consumer_episode_id,key,'
                    'contribution_id,provider_epoch) VALUES(%s,%s,%s,%s,%s,1)',
                (uuid.uuid4(), child['fiber'], episode, 'disposed-self', contribution))
    # committed_view is fixed at episode creation; closing may not rewrite it either.
    closed = uuid.uuid4()
    view_fiber = seed_fiber(db, prefix='view')['fiber']
    query_owner(db, "INSERT INTO v24_cordis.episodes(id,fiber_id,epoch,state,committed_view,iterator) "
                    "VALUES(%s,%s,0,'active',%s,%s)",
                (closed, view_fiber, Json({'legal': {'contribution_id': str(contribution)}}),
                 Json(dict(v=1, next_index=0, registered_through=-1, control_seq=0))))
    query_owner(db, "UPDATE v24_cordis.episodes SET state='closing',closed_at=now() WHERE id=%s",
                (closed,))
    sqlstate_owner(db, "UPDATE v24_cordis.episodes SET committed_view='{}'::jsonb WHERE id=%s",
                   (closed,), '55000')
    print('[CDP2-I6] unique root, pin/run DAG cycles, committed-view immutability')


def test_dispose_request(server):
    with TestDB(server) as db:
        root = active_owner(db)
        child = seed_fiber(db, prefix='dispose-lineage')
        episode = seed_episode(db, child['fiber'], epoch=1, state='active', control_seq=0)
        query_owner(db, 'UPDATE v24_cordis.fibers SET want_on=true WHERE id=%s', (child['fiber'],))
        query_owner(db, 'UPDATE v24_cordis.fibers SET dispose_requested_at=now() WHERE id=%s',
                    (root['fiber'],))
        payload = install_payload(mode='existing', existing_scope=child['scope'],
                                  owner=dict(fiber_id=str(child['fiber']), episode_id=str(episode)))
        # W2 recursively checks the owner's lineage, including ancestor retirement.
        bad(db, payload, 'owner_closing', 'install_owner_live')
        provider = seed_provider(db, realm='root', key='dispose-lineage')
        query_owner(db, 'UPDATE v24_cordis.fibers SET want_on=true WHERE id=%s',
                    (provider['fiber'],))
        with contextlib.closing(db.connect('owner')) as conn:
            got = query(conn, 'SELECT available FROM v24_cordis.resolve(%s,%s)',
                        (root['scope'], ['dispose-lineage']))
            conn.rollback()
        assert got == [(False,)], got
    print('[CDP2-I5c] an ancestor disposal request closes child admission and descendant resolution')


def test_dense_dag(server):
    with TestDB(server) as db:
        root = active_owner(db)
        nodes, episodes, contributions, epochs = [root['fiber']], [root['episode']], [], []
        root_contribution = uuid.uuid4()
        query_owner(db, "INSERT INTO v24_cordis.contributions(id,fiber_id,episode_id,seq,kind,realm,key,"
                        "descriptor,inverse,contract_version) VALUES(%s,%s,%s,0,'service','root','dag0',"
                        "'{}','{\"op\":\"delete_row\"}','1')",
                    (root_contribution, root['fiber'], root['episode']))
        contributions.append(root_contribution)
        epochs.append(0)
        for index in range(1, 19):
            child = seed_fiber(db, prefix='dag-%02d' % index)
            episode = seed_episode(db, child['fiber'], epoch=1, state='active', control_seq=0)
            query_owner(db, 'UPDATE v24_cordis.fibers SET want_on=true WHERE id=%s',
                        (child['fiber'],))
            contribution = uuid.uuid4()
            query_owner(db, "INSERT INTO v24_cordis.contributions(id,fiber_id,episode_id,seq,kind,realm,key,"
                            "descriptor,inverse,contract_version) VALUES(%s,%s,%s,0,'service','root',%s,"
                            "'{}','{\"op\":\"delete_row\"}','1')",
                        (contribution, child['fiber'], episode, 'dag%d' % index))
            nodes.append(child['fiber'])
            episodes.append(episode)
            contributions.append(contribution)
            epochs.append(1)
        with contextlib.closing(db.connect('owner')) as conn:
            query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
            for index in range(1, 19):
                for earlier in range(index):
                    query(conn, 'INSERT INTO v24_cordis.pins(id,consumer_fiber_id,'
                                'consumer_episode_id,key,contribution_id,provider_epoch) '
                                'VALUES(%s,%s,%s,%s,%s,%s)',
                          (uuid.uuid4(), nodes[index], episodes[index],
                           'dag-%d-%d' % (index, earlier), contributions[earlier], epochs[earlier]))
            conn.commit()
        assert one(db, 'SELECT count(*) FROM v24_cordis.fibers') == 19
        assert one(db, 'SELECT count(*) FROM v24_cordis.pins') == 171
    print('[CDP2-I6c] a dense 19-fiber DAG commits under deduplicated graph validation')


def sqlstate_owner(db, statement, params, code):
    with contextlib.closing(db.connect('owner')) as conn:
        sqlstate(conn, statement, params, code)


def test_disposed_root(server):
    with TestDB(server) as db:
        payload = install_payload()
        run(db, payload)
        query_owner(db, 'UPDATE v24_cordis.fibers SET disposed_at=now() WHERE id=%s',
                    (payload['fiber_id'],))
        commit_rejected(db, [('INSERT INTO v24_cordis.fibers(id,install_id,scope_id) VALUES(%s,%s,%s)',
                              (uuid.uuid4(), payload['install_id'], payload['scope']['id']))],
                          message='fiber graph multiple roots')
    print('[CDP2-I6b] a disposed ownerless root still occupies the unique root slot')


def test_forged(db):
    root = owner_pair(db)
    owner = dict(fiber_id=str(root['fiber']), episode_id=str(root['episode']))
    payload = install_payload(mode='existing', existing_scope=scope_id_holder[0], owner=owner)
    payload['identity'] = 'forged'
    original = install_probe(db)
    try:
        with contextlib.closing(db.connect('service')) as conn:
            effect, out = command(db, conn, 'service', 'command_install', payload)
            valid = install_delta(db, payload)
            set_probe(conn, valid)
            assert api(conn, effect, out).get('disposition') == 'committed'
            conn.commit()
        occupied = one(db, 'SELECT id FROM v24_cordis.contributions LIMIT 1')
        for label, mutate in (
                ('install owner', lambda ds: next(x for x in ds['domain']
                                                  if x['op'] == 'install_create').update(
                                                      owner_fiber_id=None, owner_episode_id=None)),
                ('ledger id collision',
                 lambda ds: ds['domain'][2].update(id=str(occupied))),
                ('ledger seq', lambda ds: ds['domain'][2].update(seq=99)),
                ('ledger inverse', lambda ds: ds['domain'][2].update(inverse={'op': 'delete_row'})),
                ('ledger progress', lambda ds: ds['domain'][3].update(registered_through=99)),
                ('event child', lambda ds: ds['events'][0]['payload'].update(child_contribution_id=None)),
                ('scope create', lambda ds: ds['domain'].insert(0, dict(op='scope_create',
                                                                        id=str(uuid.uuid4()),
                                                                        parent_id=None,
                                                                        realm_overrides={}))),
                ('successor', lambda ds: ds.update(successors=[dict(ordinal=0, kind='command_reconcile',
                                                                    input=dict(fiber_id=str(root['fiber']),
                                                                               action='advance',
                                                                               expected_control_seq=0))]))):
            payload = install_payload(mode='existing', existing_scope=scope_id_holder[0], owner=owner)
            payload['identity'] = 'forged-' + label.replace(' ', '-')
            with contextlib.closing(db.connect('service')) as conn:
                effect, out = command(db, conn, 'service', 'command_install', payload)
                ds = install_delta(db, payload)
                mutate(ds)
                set_probe(conn, ds)
                result = api(conn, effect, out)
                assert result.get('error', {}).get('code') == 'invalid_outcome', (label, result)
                conn.rollback()
    finally:
        replace_function(db, original['interpret_command'])
        replace_function(db, original['interpret_settlement'])
    print('[CDP2-I7] forged install deltas fail context/ledger/event/successor validation')


def main():
    sql_dir = Path(__file__).resolve().parents[1] / 'sql'
    assert (sql_dir / '41_lifecycle.sql').is_file()
    assert (sql_dir / '42_teardown.sql').is_file()
    total, counts = assert_helper_budget(sql_dir)
    print(f'[CDP2-I0] helper budget {total}<=5000 {counts}; predicate admits a 5000-line tree and rejects 5001')
    ddl = [f for f in sql_dir.glob('*.sql') if 10 <= int(f.name[:2]) <= 17
           or f.name in ('20_relations.sql', '30_triggers.sql')]
    assert len(ddl) == 10 and sum(len(f.read_text().splitlines()) for f in ddl) <= 900
    with Server() as server:
        with TestDB(server) as db:
            test_bootstrap(db)
            test_admission(db)
            test_declaration(db)
            test_resolver(db)
            test_closed_resolver(server)
            test_guards(db)
            test_forged(db)
        test_dispose_request(server)
        test_dense_dag(server)
        test_disposed_root(server)
        with TestDB(server) as db:
            test_ownerless_existing(db)
    print('[passed] CDP2-I (W2 install declaration, scope/owner admission, resolver, W2 guards)')


if __name__ == '__main__':
    main()
