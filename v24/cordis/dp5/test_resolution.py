"""CDP5-R (W1): overlay/intercept ABI, effective resolution, run/claim consistency, guard/ACL.

Run with: uv run python v24/cordis/dp5/test_resolution.py

R1-R4 and R8 are delivered here. R5-R7 (purity, independent five-mode reference,
host assumptions) belong to W4 and are not claimed by this script.
"""
from __future__ import annotations
import contextlib
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dp2'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dp4'))

from psycopg2.extras import Json  # noqa: E402
from test_support import (Server, TestDB, query, command, install_payload,  # noqa: E402
                          descriptor_digest, no_write, snapshot, sqlstate)
from test_activation import (declaration, install, commit_new, phases, p0,  # noqa: E402
                             commit_child, one, rows)
from dp4_support import (claim, settle, model_body, tool_call, tool_body,  # noqa: E402
                         q1)

CONTRACT = dict(contract_version='1', handler_digest='a' * 64,
                replay=dict(repeat=True, concurrent=True))


def owner_of(db, payload):
    return dict(fiber_id=payload['fiber_id'],
                episode_id=str(one(db, 'SELECT current_episode_id FROM v24_cordis.fibers '
                                       'WHERE id=%s', (uuid.UUID(payload['fiber_id']),))))


def root_owner(db):
    payload, _, _ = install(db)
    phases(db, uuid.UUID(payload['fiber_id']), 0)
    return payload, owner_of(db, payload)


def provider(db, root_scope, owner, key, descriptor, *, overlay=None,
             provides=None, realm_overrides=None):
    payload = declaration(mode='existing', existing=root_scope, owner=owner,
                          provides=provides if provides is not None else [key])
    if realm_overrides is not None:
        payload['scope']['realm_overrides'] = realm_overrides
    for item in payload['manifest']['provides']:
        if item['key'] == key:
            item['descriptor'] = descriptor
    payload['contracts'] = {descriptor['capability']: dict(CONTRACT)}
    if overlay is not None:
        payload['overlay'] = overlay
    effect, result, _ = commit_new(db, 'command_install', payload)
    assert result.get('disposition') == 'committed', result
    fiber = uuid.UUID(payload['fiber_id'])
    phases(db, fiber, len(payload['manifest']['provides']))
    return payload


def child_scope_holder(db, root_scope, owner, intercept, *, realm_overrides=None,
                       provides=()):
    payload = declaration(mode='child', parent=root_scope, owner=owner,
                          provides=list(provides))
    payload['scope']['intercept'] = intercept
    payload['scope']['realm_overrides'] = realm_overrides or {}
    effect, result, _ = commit_new(db, 'command_install', payload)
    assert result.get('disposition') == 'committed', result
    fiber = uuid.UUID(payload['fiber_id'])
    phases(db, fiber, len(payload['manifest']['provides']))
    return payload


def agent_in(db, scope_value, owner, requires, check=None):
    payload = install_payload(mode='existing', existing_scope=uuid.UUID(scope_value['id']),
                              owner=owner)
    payload['scope'] = scope_value
    payload['manifest'] = dict(requires=list(requires), provides=[], priority=0,
                               check={} if check is None else check)
    payload['contracts'] = {'run_start': dict(CONTRACT)}
    payload['policy_ref'] = 'chat_tool'
    effect, result, _ = commit_new(db, 'command_install', payload)
    assert result.get('disposition') == 'committed', result
    fiber = uuid.UUID(payload['fiber_id'])
    parent, _, _ = p0(db, fiber)
    parent, p1 = commit_child(db, parent, dict(fiber_id=str(fiber), action='advance',
                                               expected_control_seq=1))
    assert p1.get('disposition') == 'committed', p1
    parent, activated = commit_child(db, parent, dict(fiber_id=str(fiber), action='advance',
                                                      expected_control_seq=1))
    assert activated.get('disposition') == 'committed', activated
    assert activated['emitted'], activated
    return payload, fiber, activated, uuid.UUID(activated['emitted'][0])


def resolve(db, scope, key):
    return rows(db, 'SELECT * FROM v24_cordis.resolve(%s,ARRAY[%s])', (scope, key))[0]


def bad_install(db, payload, code='invalid_args'):
    with contextlib.closing(db.connect('service')) as conn:
        effect, outcome = command(db, conn, 'service', 'command_install', payload)
        return no_write(db, conn, effect, outcome, code=code)


def test_r1_overlay(db, root, owner):
    root_scope = uuid.UUID(root['scope']['id'])
    base = dict(capability='cap', config=dict(a=1, b=2), arr=[1, 2], scalar='old')
    overlay = {'v': 1, 'services': {'svc': {'config': {'a': 9, 'c': [3]},
                                            'arr': [9], 'scalar': None}},
               'listeners': {}}
    provider(db, root_scope, owner, 'svc', base, overlay=overlay)
    expected = dict(capability='cap', config=dict(a=9, b=2, c=[3]), arr=[9],
                    scalar=None)
    stored = q1(db, "SELECT descriptor FROM v24_cordis.contributions "
                    "WHERE key='svc' AND kind='service'")
    assert stored == expected, stored
    got = resolve(db, root_scope, 'svc')
    assert got[5] == expected and got[6] == descriptor_digest(db, expected), got

    # Depth 4 patch/effective passes; the wrapper and the descriptor-root rule
    # are not counted as extra container layers.
    deep = {'v': 1, 'services': {'deep': {'a': {'b': {'c': {'d': 1}}}}}, 'listeners': {}}
    provider(db, root_scope, owner, 'deep', {'capability': 'cap'}, overlay=deep)
    assert q1(db, "SELECT descriptor FROM v24_cordis.contributions WHERE key='deep'") == \
        {'capability': 'cap', 'a': {'b': {'c': {'d': 1}}}}

    def variant(target, patch, *, listeners=None, version=None):
        payload = install_payload(mode='existing', existing_scope=root_scope, owner=owner)
        payload['manifest'] = dict(requires=[], priority=0, check={}, provides=[
            dict(key='svc', descriptor={'capability': 'cap'}, contract_version='1')])
        payload['contracts'] = {'cap': dict(CONTRACT)}
        payload['overlay'] = {'v': version if version is not None else 1,
                             'services': {target: patch},
                             'listeners': {} if listeners is None else listeners}
        return payload

    for label, payload in (
        ('unknown target', variant('missing', {})),
        ('protected capability', variant('svc', {'capability': 'other'})),
        ('protected contract', variant('svc', {'contract_version': '2'})),
        ('protected identity', variant('svc', {'identity': 'x'})),
        ('protected version', variant('svc', {'version': '2'})),
        ('protected artifact', variant('svc', {'artifact_digest': 'b' * 64})),
        ('depth five', variant('svc', {'a': {'b': {'c': {'d': {'e': 1}}}}})),
        ('scalar patch root', variant('svc', None)),
        ('listener namespace', variant('svc', {}, listeners={'svc': {}})),
        ('wrong version', variant('svc', {}, version=2)),
        ('protocol key budget', variant('svc', {f'k{i}': 1 for i in range(201)})),
        ('missing listeners map', {**variant('svc', {}),
                                   'overlay': {'v': 1, 'services': {}}}),
        ('extra overlay key', {**variant('svc', {}),
                               'overlay': {'v': 1, 'services': {}, 'listeners': {},
                                           'extra': 1}}),
    ):
        if label == 'scalar patch root':
            payload['overlay']['services'] = {'svc': [1, 2]}
        try:
            bad_install(db, payload)
        except AssertionError as exc:
            raise AssertionError((label, exc)) from exc
    print('[CDP5-R1] overlay recursive merge, array/scalar/null replacement, protected '
          'identity, unknown target, dual namespace, depth 4/5 and wrapper boundary')


def test_r2_intercept(db, root, owner):
    root_scope = uuid.UUID(root['scope']['id'])
    provider(db, root_scope, owner, 'svc2', {'capability': 'cap', 'config': {'source': 'stored'}})
    far_desc = {'capability': 'cap', 'config': {'source': 'far'}}
    near_desc = {'capability': 'cap', 'config': {'source': 'near'}}
    far = child_scope_holder(db, root_scope, owner, {'v': 1, 'rules': [
        dict(realm='root', key='svc2', action='replace', descriptor=far_desc,
             descriptor_digest=descriptor_digest(db, far_desc), contract_version='1')]})
    far_scope = uuid.UUID(far['scope']['id'])
    assert resolve(db, far_scope, 'svc2')[5] == far_desc
    near = child_scope_holder(db, far_scope, owner, {'v': 1, 'rules': [
        dict(realm='root', key='svc2', action='replace', descriptor=near_desc,
             descriptor_digest=descriptor_digest(db, near_desc), contract_version='1')]})
    near_scope = uuid.UUID(near['scope']['id'])
    assert resolve(db, near_scope, 'svc2')[5] == near_desc, 'nearest rule must replace, not stack'
    reject = child_scope_holder(db, near_scope, owner, {'v': 1, 'rules': [
        dict(realm='root', key='svc2', action='reject')]})
    assert resolve(db, uuid.UUID(reject['scope']['id']), 'svc2')[8] is False
    deep_rule = {'capability': 'cap', 'a': {'b': {'c': {'d': 1}}}}
    deep_scope = child_scope_holder(db, root_scope, owner, {'v': 1, 'rules': [
        dict(realm='root', key='svc2', action='replace', descriptor=deep_rule,
             descriptor_digest=descriptor_digest(db, deep_rule), contract_version='1')]})
    assert resolve(db, uuid.UUID(deep_scope['scope']['id']), 'svc2')[5] == deep_rule

    # Realm is resolved before the rule lookup: a root-realm rule does not match
    # an overridden realm, while the matching realm rule does.
    realm_child = child_scope_holder(db, root_scope, owner, {'v': 1, 'rules': [
        dict(realm='root', key='svc2', action='reject'),
        dict(realm='other', key='svc2', action='replace', descriptor=near_desc,
             descriptor_digest=descriptor_digest(db, near_desc), contract_version='1')]},
        realm_overrides={'svc2': 'other'}, provides=['svc2'])
    realm_scope = uuid.UUID(realm_child['scope']['id'])
    assert resolve(db, realm_scope, 'svc2')[5] == near_desc
    assert resolve(db, root_scope, 'svc2')[5] == {'capability': 'cap',
                                                  'config': {'source': 'stored'}}

    # Structural/digest/depth checks happen through the production scope declaration.
    for label, descriptor, contract in (
        ('forged digest', {'capability': 'cap'}, '1'),
        ('contract drift', {'capability': 'cap'}, '2'),
        ('depth five', {'capability': 'cap', 'a': {'b': {'c': {'d': {'e': 1}}}}}, '1'),
    ):
        payload = declaration(mode='child', parent=root_scope, owner=owner)
        digest = descriptor_digest(db, descriptor)
        if label == 'forged digest':
            digest = '0' * 64
        payload['scope']['intercept'] = {'v': 1, 'rules': [
            dict(realm='root', key='svc2', action='replace', descriptor=descriptor,
                 descriptor_digest=digest, contract_version=contract)]}
        if label == 'contract drift':
            # Shape/digest legal; only resolution against the concrete provider rejects it.
            with contextlib.closing(db.connect('owner')) as conn:
                query(conn, 'INSERT INTO v24_cordis.scopes(id,parent_id,intercept) '
                            'VALUES(%s,%s,%s)', (uuid.UUID(payload['scope']['id']),
                                                 root_scope, Json(payload['scope']['intercept'])))
                conn.commit()
            assert resolve(db, uuid.UUID(payload['scope']['id']), 'svc2')[8] is False
        else:
            bad_install(db, payload)

    # Rule list is bounded and unique at scope shape level.
    for label, rules in (
        ('duplicate rule', [dict(realm='root', key='svc2', action='reject'),
                            dict(realm='root', key='svc2', action='reject')]),
        ('extra rule key', [dict(realm='root', key='svc2', action='reject', extra=1)]),
        ('empty rule list', []),
        ('seventeen rules', [dict(realm='root', key=f'bound-{i}', action='reject')
                             for i in range(17)]),
    ):
        payload = declaration(mode='child', parent=root_scope, owner=owner)
        payload['scope']['intercept'] = {'v': 1, 'rules': rules}
        bad_install(db, payload)
    null_payload = declaration(mode='child', parent=root_scope, owner=owner)
    null_payload['scope']['intercept'] = None
    bad_install(db, null_payload)
    bound = declaration(mode='child', parent=root_scope, owner=owner)
    bound['scope']['intercept'] = {'v': 1, 'rules': [
        dict(realm='root', key=f'bound-{i}', action='reject') for i in range(16)]}
    _, committed, _ = commit_new(db, 'command_install', bound)
    assert committed.get('disposition') == 'committed', committed
    # A rejected/unknown nearest rule never falls back to the stored descriptor.
    assert resolve(db, uuid.UUID(reject['scope']['id']), 'svc2')[8] is False
    # Production scope_create stored the declaration exactly.
    assert q1(db, 'SELECT intercept FROM v24_cordis.scopes WHERE id=%s', (near_scope,)) == \
        near['scope']['intercept']
    print('[CDP5-R2] nearest replace/reject, realm-first matching, depth 4/5, forged '
          'digest and resolve-time contract rejection; production scope_create path')


def test_r3_effective_run(db, root, owner):
    root_scope = uuid.UUID(root['scope']['id'])
    provider(db, root_scope, owner, 'model',
             {'capability': 'model_call', 'config': {'source': 'stored'}},
             overlay={'v': 1, 'services': {'model': {'config': {'overlay': True}}},
                      'listeners': {}})
    provider(db, root_scope, owner, 'tool',
             {'capability': 'tool_call', 'config': {'source': 'stored'}},
             overlay={'v': 1, 'services': {'tool': {'config': {'overlay': True}}},
                      'listeners': {}})
    fake = {'handler_digest': 'f' * 64,
            'replay': {'repeat': True, 'concurrent': True}}
    model_eff = {'capability': 'model_call', 'config': {'source': 'intercept'}, **fake}
    tool_eff = {'capability': 'tool_call', 'config': {'source': 'intercept'}, **fake}
    check = {'model': dict(v=1, op='equals', path=['config', 'source'], value='intercept'),
             'tool': dict(v=1, op='equals', path=['config', 'source'], value='intercept')}
    payload = declaration(mode='child', parent=root_scope, owner=owner,
                          requires=['model', 'tool'], check=check)
    payload['scope']['intercept'] = {'v': 1, 'rules': [
        dict(realm='root', key='model', action='replace', descriptor=model_eff,
             descriptor_digest=descriptor_digest(db, model_eff), contract_version='1'),
        dict(realm='root', key='tool', action='replace', descriptor=tool_eff,
             descriptor_digest=descriptor_digest(db, tool_eff), contract_version='1')]}
    payload['contracts'] = {'run_start': dict(CONTRACT)}
    payload['policy_ref'] = 'chat_tool'
    _, result, _ = commit_new(db, 'command_install', payload)
    assert result.get('disposition') == 'committed', result
    fiber = uuid.UUID(payload['fiber_id'])
    parent, _, _ = p0(db, fiber)
    parent, p1 = commit_child(db, parent, dict(fiber_id=str(fiber), action='advance',
                                               expected_control_seq=1))
    assert p1.get('disposition') == 'committed', p1
    parent, activated = commit_child(db, parent, dict(fiber_id=str(fiber), action='advance',
                                                      expected_control_seq=1))
    assert activated.get('disposition') == 'committed' and activated['emitted'], activated
    rs = uuid.UUID(activated['emitted'][0])
    episode = q1(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s', (fiber,))
    view = q1(db, 'SELECT committed_view FROM v24_cordis.episodes WHERE id=%s', (episode,))
    assert view['model']['descriptor_digest'] == descriptor_digest(db, model_eff), view
    assert view['tool']['descriptor_digest'] == descriptor_digest(db, tool_eff), view

    rc = claim(db, rs)
    assert rc.get('disposition') == 'claimed' and 'execution' not in rc, rc
    run = settle(db, rs, {'v': 1, 'request': {}, 'steps': 2}, rc['claim'])
    assert run.get('disposition') == 'committed', run
    model_effect = uuid.UUID(run['emitted'][0])
    mc = claim(db, model_effect)
    assert mc.get('execution') == {'descriptor': model_eff,
                                   'descriptor_digest': descriptor_digest(db, model_eff)}, mc
    assert mc['input']['contract'] == {'contract_version': '1',
                                       'handler_digest': 'a' * 64}, mc
    assert mc['input']['contract']['handler_digest'] != fake['handler_digest']
    provider_contract = q1(db, 'SELECT v24_cordis.claim_contract(e) FROM v24_cordis.effects e '
                               'WHERE e.id=%s', (model_effect,))
    assert provider_contract['handler_digest'] == 'a' * 64, provider_contract
    assert provider_contract['replay'] == {'repeat': True, 'concurrent': True}
    run_id = q1(db, 'SELECT run_id FROM v24_cordis.effects WHERE id=%s', (model_effect,))
    digests = q1(db, "SELECT input->'digests' FROM v24_cordis.effects WHERE id=%s",
                 (model_effect,))
    assert digests == q1(db, 'SELECT v24_cordis.run_digests(%s)', (run_id,)), digests
    raw = [
        {'key': 'model', 'descriptor_digest': descriptor_digest(
            db, {'capability': 'model_call', 'config': {'source': 'stored', 'overlay': True}})},
        {'key': 'tool', 'descriptor_digest': descriptor_digest(
            db, {'capability': 'tool_call', 'config': {'source': 'stored', 'overlay': True}})},
    ]
    raw_toolset = q1(db, "SELECT v24_cordis.run_digests_of(%s)->>'toolset'", (Json(raw),))
    assert digests['toolset'] != raw_toolset, 'toolset must hash effective, not stored/raw config'

    ms = settle(db, model_effect, model_body(tool_calls=[tool_call('c1', 'tool')]), mc['claim'])
    assert ms.get('disposition') == 'committed', ms
    tool_effect = uuid.UUID(ms['emitted'][0])
    assert q1(db, "SELECT input->>'descriptor_digest' FROM v24_cordis.effects WHERE id=%s",
              (tool_effect,)) == view['tool']['descriptor_digest']
    tc = claim(db, tool_effect)
    assert tc.get('execution') == {'descriptor': tool_eff,
                                   'descriptor_digest': descriptor_digest(db, tool_eff)}, tc
    print('[CDP5-R3] check view/run input/toolset/claim execution all use the effective '
          'descriptor; empty configuration keeps the legacy claim shape')



def test_r3_legacy(db, root, owner):
    root_scope = uuid.UUID(root['scope']['id'])
    provider(db, root_scope, owner, 'model0', {'capability': 'model_call'})
    provider(db, root_scope, owner, 'tool0', {'capability': 'tool_call'})
    payload = install_payload(mode='existing', existing_scope=root_scope, owner=owner)
    payload['manifest'] = dict(requires=['model0', 'tool0'], provides=[], priority=0, check={})
    payload['contracts'] = {'run_start': dict(CONTRACT)}
    payload['policy_ref'] = 'chat_tool'
    _, result, _ = commit_new(db, 'command_install', payload)
    assert result.get('disposition') == 'committed', result
    fiber = uuid.UUID(payload['fiber_id'])
    parent, _, _ = p0(db, fiber)
    parent, p1 = commit_child(db, parent, dict(fiber_id=str(fiber), action='advance',
                                               expected_control_seq=1))
    parent, activated = commit_child(db, parent, dict(fiber_id=str(fiber), action='advance',
                                                      expected_control_seq=1))
    rs = uuid.UUID(activated['emitted'][0])
    rc = claim(db, rs)
    run = settle(db, rs, {'v': 1, 'request': {}, 'steps': 1}, rc['claim'])
    model_effect = uuid.UUID(run['emitted'][0])
    episode = q1(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s', (fiber,))
    view = q1(db, 'SELECT committed_view FROM v24_cordis.episodes WHERE id=%s', (episode,))
    raw_model = {'capability': 'model_call'}
    raw_tool = {'capability': 'tool_call'}
    assert view['model0']['descriptor_digest'] == descriptor_digest(db, raw_model)
    assert view['tool0']['descriptor_digest'] == descriptor_digest(db, raw_tool)
    mc = claim(db, model_effect)
    assert 'execution' not in mc, mc
    assert set(mc) == {'v', 'disposition', 'effect_id', 'emitted', 'revision',
                       'claim', 'input'}, mc
    run_id = q1(db, 'SELECT run_id FROM v24_cordis.effects WHERE id=%s', (model_effect,))
    assert mc['input']['digests'] == q1(db, 'SELECT v24_cordis.run_digests(%s)', (run_id,))
    raw = [{'key': 'model0', 'descriptor_digest': descriptor_digest(db, raw_model)},
           {'key': 'tool0', 'descriptor_digest': descriptor_digest(db, raw_tool)}]
    assert mc['input']['digests']['toolset'] == \
        q1(db, "SELECT v24_cordis.run_digests_of(%s)->>'toolset'", (Json(raw),))
    print('[CDP5-R3b] no-config run keeps the DP4 claim shape and raw digest/toolset')

def test_r4_old_drain(db, root, owner):
    root_scope = uuid.UUID(root['scope']['id'])
    provider(db, root_scope, owner, 'model4',
             {'capability': 'model_call', 'config': {'source': 'stored'}},
             overlay={'v': 1, 'services': {'model4': {'config': {'overlay': True}}},
                      'listeners': {}})
    provider(db, root_scope, owner, 'tool4',
             {'capability': 'tool_call', 'config': {'source': 'stored'}},
             overlay={'v': 1, 'services': {'tool4': {'config': {'overlay': True}}},
                      'listeners': {}})
    payload = install_payload(mode='existing', existing_scope=root_scope, owner=owner)
    payload['manifest'] = dict(requires=['model4', 'tool4'], provides=[], priority=0, check={})
    payload['contracts'] = {'run_start': dict(CONTRACT)}
    payload['policy_ref'] = 'chat_tool'
    _, result, _ = commit_new(db, 'command_install', payload)
    assert result.get('disposition') == 'committed', result
    fiber = uuid.UUID(payload['fiber_id'])
    parent, _, _ = p0(db, fiber)
    parent, p1 = commit_child(db, parent, dict(fiber_id=str(fiber), action='advance',
                                               expected_control_seq=1))
    parent, activated = commit_child(db, parent, dict(fiber_id=str(fiber), action='advance',
                                                      expected_control_seq=1))
    rs = uuid.UUID(activated['emitted'][0])
    rc = claim(db, rs)
    run = settle(db, rs, {'v': 1, 'request': {}, 'steps': 2}, rc['claim'])
    model_effect = uuid.UUID(run['emitted'][0])
    episode = q1(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s', (fiber,))
    bindings = q1(db, 'SELECT v24_cordis.run_bindings(%s)', (episode,))
    pinned = {b['key']: b for b in bindings}
    # Fixture: a frozen-view contract drift is rejected by the binding helper even
    # though the effective descriptor digest is unchanged. Rolled back immediately.
    run_id = q1(db, 'SELECT run_id FROM v24_cordis.effects WHERE id=%s', (model_effect,))
    tool_pin = q1(db, 'SELECT id FROM v24_cordis.pins WHERE consumer_run_id=%s AND key=%s',
                  (run_id, 'tool4'))
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'ALTER TABLE v24_cordis.episodes DISABLE TRIGGER episodes_immutable')
        query(conn, "UPDATE v24_cordis.episodes SET committed_view="
                    "jsonb_set(committed_view,'{tool4,contract_version}','\"2\"') WHERE id=%s",
              (episode,))
        drifted = query(conn, 'SELECT v24_cordis.run_binding_desc(%s,%s,%s)',
                        (run_id, tool_pin, 'tool4'))[0][0]
        assert drifted['available'] is False, drifted
        conn.rollback()
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, "UPDATE v24_cordis.contributions SET withdrawn_at=clock_timestamp() "
                    "WHERE key IN ('model4','tool4') AND kind='service' AND released_at IS NULL")
        conn.commit()
    assert resolve(db, root_scope, 'model4')[8] is False
    after = q1(db, 'SELECT v24_cordis.run_bindings(%s)', (episode,))
    assert {b['key']: (b['contribution_id'], b['descriptor_digest']) for b in after} == \
        {k: (v['contribution_id'], v['descriptor_digest']) for k, v in pinned.items()}
    mc = claim(db, model_effect)
    assert mc.get('disposition') == 'claimed' and mc.get('execution'), mc
    ms = settle(db, model_effect, model_body(tool_calls=[tool_call('c1', 'tool4')]), mc['claim'])
    assert ms.get('disposition') == 'committed', ms
    tool_effect = uuid.UUID(ms['emitted'][0])
    tc = claim(db, tool_effect)
    assert tc.get('disposition') == 'claimed', tc
    # Releasing the old pin/contribution rejects the still-claimed tool receipt.
    pin_id = q1(db, "SELECT (input->>'pin_id')::uuid FROM v24_cordis.effects WHERE id=%s",
                (tool_effect,))
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'UPDATE v24_cordis.pins SET released_at=clock_timestamp() WHERE id=%s',
              (pin_id,))
        conn.commit()
    with contextlib.closing(db.connect('owner')) as conn:
        before = snapshot(conn)
    rejected = settle(db, tool_effect, tool_body(), tc['claim'])
    assert rejected.get('error', {}).get('code') == 'dependency_unresolved', rejected
    with contextlib.closing(db.connect('owner')) as conn:
        assert snapshot(conn) == before
    print('[CDP5-R4] withdrawn provider pins still drain with the frozen effective config; '
          'frozen contract drift and released pins reject without rebinding')



def test_r8_guard_acl(db, root, owner):
    root_scope = uuid.UUID(root['scope']['id'])
    with contextlib.closing(db.connect('owner')) as conn:
        sqlstate(conn, 'UPDATE v24_cordis.scopes SET realm_overrides=%s WHERE id=%s',
                 (Json({'svc': 'other'}), root_scope), code='55000')
        sqlstate(conn, 'UPDATE v24_cordis.scopes SET intercept=%s WHERE id=%s',
                 (Json({'v': 1, 'rules': [dict(realm='root', key='svc', action='reject')]}),
                  root_scope), code='55000')
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'UPDATE v24_cordis.scopes SET closed_at=clock_timestamp() WHERE id=%s',
              (root_scope,))
        conn.commit()
    with contextlib.closing(db.connect('owner')) as conn:
        sqlstate(conn,
                 'UPDATE v24_cordis.scopes SET closed_at=clock_timestamp()+interval \'1 second\' '
                 'WHERE id=%s', (root_scope,), code='55000')
    install_id = q1(db, 'SELECT id FROM v24_cordis.installs LIMIT 1')
    with contextlib.closing(db.connect('owner')) as conn:
        sqlstate(conn,
                 'UPDATE v24_cordis.installs SET overlay=%s WHERE id=%s',
                 (Json({'v': 1, 'services': {}, 'listeners': {}}), install_id), code='55000')
    names = ('descriptor_depth', 'descriptor_merge', 'descriptor_patch_ok', 'overlay_apply',
             'install_overlay_valid', 'scope_intercept_valid', 'intercept_for',
             'descriptor_effective', 'run_binding_desc', 'claim_execution')
    with contextlib.closing(db.connect('owner')) as conn:
        found = query(conn, 'SELECT proname FROM pg_proc WHERE pronamespace='
                            "'v24_cordis'::regnamespace AND proname=ANY(%s)", (list(names),))
        assert {x[0] for x in found} == set(names), found
        claim_funcs = query(conn, "SELECT p.proname, has_function_privilege(%s,p.oid,'EXECUTE') "
                                  "FROM pg_proc p WHERE p.pronamespace='v24_cordis'::regnamespace "
                                  "AND p.proname=ANY(%s) ORDER BY p.proname",
                            (db.roles['service'], list(names)))
        assert all(not allowed for _, allowed in claim_funcs), claim_funcs
        public = query(conn, "SELECT count(*) FROM pg_proc p WHERE p.pronamespace="
                             "'v24_cordis'::regnamespace AND p.proname=ANY(%s) AND EXISTS("
                             "SELECT 1 FROM aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a "
                             "WHERE a.grantee=0 AND a.privilege_type='EXECUTE')", (list(names),))[0][0]
        assert public == 0, public
    print('[CDP5-R8] scope realm/intercept UPDATE guard, close tombstone, install overlay '
          'immutability and private helper ACL')


def main():
    with Server() as server, TestDB(server) as db:
        root, owner = root_owner(db)
        test_r1_overlay(db, root, owner)
        test_r2_intercept(db, root, owner)
        test_r3_effective_run(db, root, owner)
        test_r3_legacy(db, root, owner)
        test_r4_old_drain(db, root, owner)
        test_r8_guard_acl(db, root, owner)
    print('[passed] CDP5-R (W1: R1-R4/R8; R5-R7 deferred to W4)')


if __name__ == '__main__':
    main()
