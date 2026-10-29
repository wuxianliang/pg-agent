"""CDP5-R (W4): overlay/intercept, effective resolution, purity and five-mode refinement.

Run with: uv run python v24/cordis/dp5/test_resolution.py

R1-R8 are delivered here. W1 supplied R1-R4/R8; W4 adds R5 (pure listener_exec
dependency closure and read-table probe), R6 (independent Python reference for all
five modes plus the empty-set identity) and R7 (host conditional evidence). R6b is
the mixed-generation activation regression; R3b includes the no-config DP4 digest
recomputation.
"""
from __future__ import annotations
import contextlib
import hashlib
import json
import sys
import uuid
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dp2'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dp3'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dp4'))

from psycopg2 import sql  # noqa: E402
from psycopg2.extras import Json  # noqa: E402
from test_support import (Server, TestDB, query, command, install_payload,  # noqa: E402
                          descriptor_digest, no_write, snapshot, sqlstate,
                          replace_function)
from test_activation import (declaration, install, commit_new, phases, p0,  # noqa: E402
                             commit_child, one, rows)
from test_teardown import enter_closing, drain  # noqa: E402
from test_listeners import activate_plan  # noqa: E402
from test_dispatch import (HOST as DISPATCH_HOST, listener as dispatch_listener,  # noqa: E402
                           declaration_with, activate as activate_dispatch,
                           fresh_scope, create as dispatch_create, drain_ready,
                           parent_result, children)
from dp4_support import (claim, settle, model_body, tool_call, tool_body,  # noqa: E402
                         q1)

CONTRACT = dict(contract_version='1', handler_digest='a' * 64,
                replay=dict(repeat=True, concurrent=True))
DP4_POLICY_SHA = '06267903edfbb28c6b65c6e91d699b4e4ab6313e108255281189fd10f28c1a46'
DP4_SCHEMA_SHA = '0f782569eea55efa90a264e62e62868e32e3cc2c3b3807eeceff593c4ff58a4d'


def python_sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def python_toolset_sha(pairs):
    text = json.dumps([{'key': key, 'descriptor_digest': digest}
                       for key, digest in sorted(pairs)], separators=(', ', ': '))
    return python_sha(text)


def ref_filter(spec, params):
    if spec is None:
        return True
    current = params
    for part in spec['path']:
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return current == spec['value']


def ref_execute(execution, params, acc):
    """Independent in_db operator; never calls listener_exec/dispatch_fold."""
    if execution.get('type') != 'in_db':
        return 'host', None
    op = execution.get('op')
    if op == 'const':
        return 'success', execution.get('value')
    if op == 'acc':
        return 'success', acc
    if op == 'append':
        if isinstance(acc, list):
            return 'success', acc + [execution.get('value')]
        return 'failure', {'code': 'invalid_acc'}
    if op == 'fail':
        return 'failure', {'code': execution.get('code')}
    return 'failure', {'code': 'invalid_exec'}


def ref_fold(mode, params, items):
    """Synchronous DSH-style reference: sort, filter, execute and fold in Python."""
    ordered = sorted(items, key=lambda item: -item['priority'])
    assert len({item['priority'] for item in ordered}) == len(ordered), \
        'R6 scenarios need unique priorities for a deterministic ordinal order'
    called, outcomes, projections, chain = [], [], [], []
    joined, bailed, first = 0, False, None
    acc = params if mode == 'waterfall' else None
    for item in ordered:
        if mode in ('serial', 'bail') and bailed:
            break
        chain.append({'listener_id': item['listener_id'], 'acc': acc})
        status, value = ref_execute(item['exec'], params, acc)
        if status == 'host':
            break
        joined += 1
        called.append(item['listener_id'])
        outcomes.append((status, value))
        projection = value if status == 'success' else {'error': value}
        projections.append(projection)
        if (mode in ('serial', 'bail') and status == 'success'
                and isinstance(value, dict) and isinstance(value.get('bail'), bool)
                and value['bail'] is True):
            bailed = True
            if first is None:
                first = value
        if mode == 'waterfall':
            acc = projection
    result_acc = first if mode == 'bail' else (acc if mode == 'waterfall' else projections)
    sealed = mode == 'emit' or bailed or joined == len(ordered)
    return dict(mode=mode, ordered=ordered, called=called, joined=joined,
                acc=result_acc, bailed=bailed, sealed=sealed, chain=chain,
                outcomes=outcomes)


def expected_parent(ref):
    if ref['mode'] == 'emit':
        return {'v': 1, 'mode': 'emit',
                'generated': [item['listener_id'] for item in ref['ordered']]}
    return {'v': 1, 'mode': ref['mode'], 'acc': ref['acc'], 'joined': ref['joined'],
            'called': ref['called'], 'bailed': ref['bailed']}


def actual_outcome(row):
    _, status, _, outcome = row
    if status == 'succeeded':
        return 'success', outcome['body']['result']['value']
    if status == 'failed':
        return 'failure', outcome['body']['error']
    return 'host', None


def params_for(db, fiber):
    fiber = uuid.UUID(str(fiber))
    episode = one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s', (fiber,))
    epoch = one(db, 'SELECT epoch FROM v24_cordis.episodes WHERE id=%s', (episode,))
    return {'fiber_id': str(fiber), 'episode_id': str(episode), 'epoch': epoch}


def settle_value(db, effect, value, claim_result):
    settled = settle(db, effect, {'kind': 'listener_call',
                                  'result': {'value': value}}, claim_result['claim'])
    assert settled.get('disposition') == 'committed', settled
    return settled


def assert_reference(db, dispatch, ref):
    result = parent_result(db, dispatch)
    expected = expected_parent(ref)
    assert result == expected, (result, expected)
    snapshot = one(db, "SELECT input->'listeners' FROM v24_cordis.effects WHERE id=%s",
                   (dispatch,))
    assert [item['listener_id'] for item in snapshot] == \
        [item['listener_id'] for item in ref['ordered']], snapshot
    actual = children(db, dispatch)
    assert [row[0] for row in actual] == list(range(len(ref['called']))), actual
    assert [row[2] for row in actual] == ref['called'], actual
    assert Counter(row[2] for row in actual) == Counter(ref['called']), actual
    assert [actual_outcome(row) for row in actual] == ref['outcomes'], actual
    if ref['mode'] == 'waterfall':
        accs = [row[0] for row in rows(
            db, "SELECT input->'acc' FROM v24_cordis.effects WHERE parent_id=%s "
                "AND kind='listener_call' ORDER BY ordinal", (dispatch,))]
        assert accs == [item['acc'] for item in ref['chain']], (accs, ref['chain'])


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
    # Independent DP4 summary recomputation: the no-config path must still use the
    # shipped policy/schema text and the raw descriptor digests, not an effective
    # overlay/intercept substitute.
    assert mc['input']['digests']['policy'] == DP4_POLICY_SHA, mc['input']['digests']
    assert mc['input']['digests']['schema'] == DP4_SCHEMA_SHA, mc['input']['digests']
    assert mc['input']['digests']['toolset'] == python_toolset_sha(
        [(item['key'], item['descriptor_digest']) for item in raw]), mc['input']['digests']
    print('[CDP5-R3b] no-config run keeps the DP4 claim shape and raw digest/toolset; '
          'policy/schema/toolset rehashed independently in Python')

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



def test_r5_purity(db):
    oid = q1(db, "SELECT oid FROM pg_proc WHERE oid="
                 "'v24_cordis.listener_exec(jsonb,jsonb,jsonb)'::regprocedure")
    meta = q1(db, "SELECT jsonb_build_object('volatile',provolatile,'strict',proisstrict,"
                  "'sql_body',prosqlbody IS NOT NULL,'definition',pg_get_functiondef(oid)) "
                  "FROM pg_proc WHERE oid=%s", (oid,))
    assert meta['volatile'] == 'i', meta
    assert meta['strict'] is True, meta
    assert meta['sql_body'] is True, meta
    assert 'BEGIN ATOMIC' in meta['definition'], meta['definition']

    def closure(function_oid):
        return q1(db, '''WITH RECURSIVE d(classid,objid,refclassid,refobjid) AS (
            SELECT classid,objid,refclassid,refobjid FROM pg_depend
             WHERE classid='pg_proc'::regclass AND objid=%s
            UNION
            SELECT g.classid,g.objid,g.refclassid,g.refobjid FROM pg_depend g
             JOIN d ON g.classid=d.refclassid AND g.objid=d.refobjid
             WHERE d.refclassid='pg_proc'::regclass)
          SELECT jsonb_build_object(
            'relations',count(*) FILTER (WHERE d.refclassid='pg_class'::regclass),
            'functions',count(DISTINCT d.refobjid) FILTER (WHERE d.refclassid='pg_proc'::regclass
              AND p.pronamespace<>'pg_catalog'::regnamespace),
            'missing_sql_body',count(DISTINCT d.refobjid) FILTER (WHERE d.refclassid='pg_proc'::regclass
              AND p.pronamespace<>'pg_catalog'::regnamespace AND p.prosqlbody IS NULL))
          FROM d LEFT JOIN pg_proc p ON p.oid=d.refobjid''', (function_oid,))

    dependency = closure(oid)
    assert dependency['relations'] == 0, ('listener_exec reads a relation', dependency)
    assert dependency['missing_sql_body'] == 0, ('callee has no parsed body', dependency)
    pure = ('event_policy', 'listener_exec', 'listener_contract', 'listener_call_input',
            'listener_available', 'dispatch_fold')
    definitions = rows(db, "SELECT proname,provolatile,pg_get_functiondef(oid) FROM pg_proc "
                           "WHERE pronamespace='v24_cordis'::regnamespace AND proname=ANY(%s) "
                           "ORDER BY proname", (list(pure),))
    assert {name for name, _, _ in definitions} == set(pure), definitions
    assert all(volatility == 'i' for _, volatility, _ in definitions), definitions
    forbidden = ('EXECUTE ', 'RAISE ', 'dblink', 'http://', 'https://', 'pg_read_file',
                 'pg_write_file', 'lo_import', 'lo_export', 'COPY ')
    for name, _, definition in definitions:
        for token in forbidden:
            assert token not in definition, (name, token)
    # A deliberately reading BEGIN ATOMIC probe must be visible to the same closure;
    # without this negative control, a zero-relation result would be vacuous.
    replace_function(db, '''CREATE OR REPLACE FUNCTION v24_cordis.dp5_probe_reads() RETURNS bigint
LANGUAGE sql BEGIN ATOMIC SELECT count(*) FROM v24_cordis.effects; END''')
    try:
        probe = q1(db, "SELECT oid FROM pg_proc WHERE oid="
                       "'v24_cordis.dp5_probe_reads()'::regprocedure")
        assert closure(probe)['relations'] > 0, 'BEGIN ATOMIC read probe was not detected'
    finally:
        with contextlib.closing(db.connect('owner')) as conn:
            query(conn, sql.SQL('SET ROLE {}').format(sql.Identifier(db.groups['owner'])))
            query(conn, 'DROP FUNCTION v24_cordis.dp5_probe_reads()')
            conn.commit()
    print('[CDP5-R5] listener_exec is IMMUTABLE STRICT BEGIN ATOMIC; its pg_depend closure '
          'has no pg_class or parsed-body gap; the read-table probe is detected; pure helpers '
          'have no dynamic SQL/outbound/RAISE')


def run_r6_mode(db, root, mode, specs):
    scope, _ = fresh_scope(db, root)
    listeners = [dispatch_listener(name, mode, priority, execution)
                 for name, priority, execution in specs]
    _, fiber, result = dispatch_create(db, scope, root['owner'], listeners=listeners)
    drain_ready(db, result)
    dispatch = one(db, "SELECT id FROM v24_cordis.effects WHERE kind='dispatch' "
                       'AND fiber_id=%s', (fiber,))
    params = params_for(db, fiber) if mode == 'waterfall' else None
    items = [dict(listener_id=name, priority=priority, exec=execution)
             for name, priority, execution in specs]
    return dispatch, ref_fold(mode, params, items)


def test_r6_reference(db, root):
    dispatch, ref = run_r6_mode(db, root, 'emit', [
        ('r6e-1', 30, {'type': 'in_db', 'op': 'const', 'value': {'emit': 1}}),
        ('r6e-2', 20, {'type': 'in_db', 'op': 'const', 'value': {'emit': 2}}),
        ('r6e-3', 10, {'type': 'in_db', 'op': 'fail', 'code': 'emit_fail'})])
    assert ref['called'] == ['r6e-1', 'r6e-2', 'r6e-3']
    assert_reference(db, dispatch, ref)

    dispatch, ref = run_r6_mode(db, root, 'parallel', [
        ('r6p-1', 30, {'type': 'in_db', 'op': 'const', 'value': {'parallel': 1}}),
        ('r6p-2', 20, {'type': 'in_db', 'op': 'const', 'value': {'parallel': 2}}),
        ('r6p-3', 10, {'type': 'in_db', 'op': 'fail', 'code': 'parallel_fail'})])
    assert ref['acc'] == [{'parallel': 1}, {'parallel': 2},
                          {'error': {'code': 'parallel_fail'}}]
    assert_reference(db, dispatch, ref)

    dispatch, ref = run_r6_mode(db, root, 'serial', [
        ('r6s-1', 30, {'type': 'in_db', 'op': 'const',
                       'value': {'bail': True, 'serial': 1}}),
        ('r6s-2', 20, {'type': 'in_db', 'op': 'const', 'value': {'serial': 2}}),
        ('r6s-3', 10, {'type': 'in_db', 'op': 'fail', 'code': 'serial_fail'})])
    assert ref['called'] == ['r6s-1'] and ref['joined'] == 1 and ref['bailed'] is True
    assert ref['acc'] == [{'bail': True, 'serial': 1}]
    assert_reference(db, dispatch, ref)

    dispatch, ref = run_r6_mode(db, root, 'bail', [
        ('r6b-1', 30, {'type': 'in_db', 'op': 'const',
                       'value': {'bail': True, 'hit': 1}}),
        ('r6b-2', 20, {'type': 'in_db', 'op': 'const', 'value': {'hit': 2}})])
    assert ref['called'] == ['r6b-1'] and ref['joined'] == 1 and ref['bailed'] is True
    assert ref['acc'] == {'bail': True, 'hit': 1}
    assert_reference(db, dispatch, ref)

    dispatch, ref = run_r6_mode(db, root, 'bail', [
        ('r6n-1', 30, {'type': 'in_db', 'op': 'const', 'value': {'bail': False}}),
        ('r6n-2', 20, {'type': 'in_db', 'op': 'const', 'value': {'hit': 2}})])
    assert ref['called'] == ['r6n-1', 'r6n-2'] and ref['joined'] == 2
    assert ref['bailed'] is False and ref['acc'] is None
    assert_reference(db, dispatch, ref)

    dispatch, ref = run_r6_mode(db, root, 'waterfall', [
        ('r6w-1', 60, {'type': 'in_db', 'op': 'acc'}),
        ('r6w-2', 50, {'type': 'in_db', 'op': 'const', 'value': [1]}),
        ('r6w-3', 40, {'type': 'in_db', 'op': 'append', 'value': 2}),
        ('r6w-4', 30, {'type': 'in_db', 'op': 'fail', 'code': 'waterfall_fail'}),
        ('r6w-5', 20, {'type': 'in_db', 'op': 'acc'}),
        ('r6w-6', 10, {'type': 'in_db', 'op': 'append', 'value': 4})])
    assert ref['called'] == [f'r6w-{i}' for i in range(1, 7)]
    assert ref['acc'] == {'error': {'code': 'invalid_acc'}}
    assert_reference(db, dispatch, ref)

    # Cross-provider duplicate listener ids are a multiset, not a set.
    scope, _ = fresh_scope(db, root)
    _, _, result1 = dispatch_create(db, scope, root['owner'], listeners=[
        dispatch_listener('r6dup', 'parallel', 20,
                          {'type': 'in_db', 'op': 'const', 'value': {'source': 'a'}})])
    drain_ready(db, result1)
    _, _, result2 = dispatch_create(db, scope, root['owner'], listeners=[
        dispatch_listener('r6dup', 'parallel', 10,
                          {'type': 'in_db', 'op': 'const', 'value': {'source': 'b'}})])
    drain_ready(db, result2)
    _, source, _ = dispatch_create(db, scope, root['owner'])
    dispatch = one(db, "SELECT id FROM v24_cordis.effects WHERE kind='dispatch' "
                       'AND fiber_id=%s', (source,))
    ref = ref_fold('parallel', None, [
        dict(listener_id='r6dup', priority=20, exec={
            'type': 'in_db', 'op': 'const', 'value': {'source': 'a'}}),
        dict(listener_id='r6dup', priority=10, exec={
            'type': 'in_db', 'op': 'const', 'value': {'source': 'b'}})])
    assert ref['called'] == ['r6dup', 'r6dup']
    assert_reference(db, dispatch, ref)
    actual = [row[2] for row in children(db, dispatch)]
    assert Counter(actual) == Counter(['r6dup', 'r6dup']), actual

    # Filter is evaluated against event params before sorting/execution.
    scope, _ = fresh_scope(db, root)
    payload = declaration_with(scope, root['owner'])
    fiber_id = payload['fiber_id']
    keep = {'v': 1, 'op': 'equals', 'path': ['fiber_id'], 'value': fiber_id}
    drop = {'v': 1, 'op': 'equals', 'path': ['fiber_id'],
            'value': '00000000-0000-0000-0000-000000000000'}
    payload['manifest']['listeners'] = [
        dispatch_listener('r6f-yes', 'parallel', 20,
                          {'type': 'in_db', 'op': 'const', 'value': {'kept': 1}},
                          filter=keep),
        dispatch_listener('r6f-no', 'parallel', 10,
                          {'type': 'in_db', 'op': 'const', 'value': {'dropped': 1}},
                          filter=drop)]
    effect, result, _ = commit_new(db, 'command_install', payload)
    assert result.get('disposition') == 'committed', result
    activate_dispatch(db, payload)
    fiber = uuid.UUID(fiber_id)
    dispatch = one(db, "SELECT id FROM v24_cordis.effects WHERE kind='dispatch' "
                       'AND fiber_id=%s', (fiber,))
    params = params_for(db, fiber)
    kept = [item for item in (
        dict(listener_id='r6f-yes', priority=20, filter=keep,
             exec={'type': 'in_db', 'op': 'const', 'value': {'kept': 1}}),
        dict(listener_id='r6f-no', priority=10, filter=drop,
             exec={'type': 'in_db', 'op': 'const', 'value': {'dropped': 1}}))
        if ref_filter(item['filter'], params)]
    assert [item['listener_id'] for item in kept] == ['r6f-yes']
    assert_reference(db, dispatch, ref_fold('parallel', None, kept))

    # Empty-set identity is asserted independently, then checked against the deployed
    # helper branch. The five-mode answers above never use the SQL fold as reference.
    for mode in ('emit', 'parallel', 'serial', 'bail', 'waterfall'):
        params = {'seed': 1}
        empty = ref_fold(mode, params, [])
        got = one(db, 'SELECT v24_cordis.dispatch_fold(%s,%s)',
                  (Json({'mode': mode, 'params': params, 'listeners': []}), Json([])))
        assert got['joined'] == 0 and got['called'] == [] and got['bailed'] is False, got
        assert got['sealed'] is True and got['next_ordinal'] == 0, got
        assert got['acc'] == empty['acc'], (mode, got['acc'], empty['acc'])
    print('[CDP5-R6] independent Python sort/filter/exec/fold matches emit generated, '
          'parallel/serial/bail/waterfall acc/joined/called; serial and bail short-circuit; '
          'duplicate listener_id across providers is a multiset; empty-set identity matches')


def test_r6b_mixed_generation(db, root):
    scope, _ = fresh_scope(db, root)
    _, provider, result = dispatch_create(db, scope, root['owner'], listeners=[
        dispatch_listener('r6gen', 'parallel', 20,
                          {'type': 'in_db', 'op': 'const', 'value': {'gen': 1}})])
    drain_ready(db, result)
    control = enter_closing(db, provider)
    drain(db, provider, control)
    old = one(db, "SELECT id FROM v24_cordis.contributions WHERE fiber_id=%s AND kind='listener' "
                  'AND released_at IS NOT NULL ORDER BY seq LIMIT 1', (provider,))
    control = one(db, 'SELECT control_seq FROM v24_cordis.fibers WHERE id=%s', (provider,))
    activate_plan(db, provider, 1, control)
    new = one(db, "SELECT id FROM v24_cordis.contributions WHERE fiber_id=%s AND kind='listener' "
                  'AND released_at IS NULL ORDER BY seq LIMIT 1', (provider,))
    assert old != new
    _, source, _ = dispatch_create(db, scope, root['owner'])
    dispatch = one(db, "SELECT id FROM v24_cordis.effects WHERE kind='dispatch' "
                       'AND fiber_id=%s', (source,))
    snapshot = one(db, "SELECT input->'listeners' FROM v24_cordis.effects WHERE id=%s",
                   (dispatch,))
    assert [item['listener_id'] for item in snapshot] == ['r6gen'], snapshot
    assert snapshot[0]['contribution_id'] == str(new), (snapshot, old, new)
    assert all(item['contribution_id'] != str(old) for item in snapshot), snapshot
    ref = ref_fold('parallel', None, [dict(
        listener_id='r6gen', priority=20,
        exec={'type': 'in_db', 'op': 'const', 'value': {'gen': 1}})])
    assert_reference(db, dispatch, ref)
    print('[CDP5-R6b] a reactivated provider contributes only its current-generation listener; '
          'the released generation is excluded from the mixed-generation snapshot')


def test_r7_host_assumptions(db, root):
    # P7.1 (no inter-listener data dependency), P7.3 (no order-only synchronous side
    # effect), and E1-E3 (fair scan, timely receipt, finite convergence) are host
    # premises. This gate observes generated/ready/settled/withdrawn state only; it
    # makes no timing-equivalence claim and sync_reads=false is not external isolation.
    scope, _ = fresh_scope(db, root)
    provider, pf, result = dispatch_create(db, scope, root['owner'], listeners=[
        dispatch_listener('r7e', 'emit', 10,
                          {'type': 'host', 'capability': 'listener_call'})],
        contracts={'listener_call': dict(DISPATCH_HOST)})
    assert one(db, "SELECT descriptor->'sync_reads' FROM v24_cordis.contributions "
                   'WHERE fiber_id=%s AND kind=%s', (pf, 'listener')) is False
    drain_ready(db, result)
    _, source, activation = dispatch_create(db, scope, root['owner'])
    dispatch = one(db, "SELECT id FROM v24_cordis.effects WHERE kind='dispatch' "
                       'AND fiber_id=%s', (source,))
    before = parent_result(db, dispatch)
    assert before == {'v': 1, 'mode': 'emit', 'generated': ['r7e']}, before
    child = uuid.UUID(activation['ready_effects'][0]['effect_id'])
    assert one(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (child,)) == 'ready'
    assert parent_result(db, dispatch) == before
    assert one(db, "SELECT count(*) FROM v24_cordis.events WHERE event_kind="
                   "'dispatch_progress' AND entity_id=%s", (dispatch,)) == 0
    claim_result = claim(db, child)
    assert claim_result['disposition'] == 'claimed', claim_result
    assert claim_result['execution']['descriptor']['sync_reads'] is False, claim_result
    settle_value(db, child, {'late': 1}, claim_result)
    assert parent_result(db, dispatch) == before
    assert one(db, "SELECT count(*) FROM v24_cordis.events WHERE event_kind="
                   "'dispatch_progress' AND entity_id=%s", (dispatch,)) == 1

    scope, _ = fresh_scope(db, root)
    provider, pf, result = dispatch_create(db, scope, root['owner'], listeners=[
        dispatch_listener('r7p', 'parallel', 10,
                          {'type': 'host', 'capability': 'listener_call'})],
        contracts={'listener_call': dict(DISPATCH_HOST)})
    drain_ready(db, result)
    _, source, activation = dispatch_create(db, scope, root['owner'])
    dispatch = one(db, "SELECT id FROM v24_cordis.effects WHERE kind='dispatch' "
                       'AND fiber_id=%s', (source,))
    assert parent_result(db, dispatch) is None
    child = uuid.UUID(activation['ready_effects'][0]['effect_id'])
    assert one(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s', (child,)) == 'ready'
    claim_result = claim(db, child)
    settle_value(db, child, {'seen': 1}, claim_result)
    assert parent_result(db, dispatch) == {
        'v': 1, 'mode': 'parallel', 'acc': [{'seen': 1}], 'joined': 1,
        'called': ['r7p'], 'bailed': False}

    scope, _ = fresh_scope(db, root)
    provider, pf, result = dispatch_create(db, scope, root['owner'], listeners=[
        dispatch_listener('r7w', 'parallel', 10,
                          {'type': 'host', 'capability': 'listener_call'})],
        contracts={'listener_call': dict(DISPATCH_HOST)})
    drain_ready(db, result)
    _, source, activation = dispatch_create(db, scope, root['owner'])
    dispatch = one(db, "SELECT id FROM v24_cordis.effects WHERE kind='dispatch' "
                       'AND fiber_id=%s', (source,))
    child = uuid.UUID(activation['ready_effects'][0]['effect_id'])
    claim_result = claim(db, child)
    control = enter_closing(db, pf)
    assert one(db, 'SELECT v24_cordis.p6_plan(NULL,%s)', (pf,))['kind'] == 'deferred'
    settle_value(db, child, {'drained': 1}, claim_result)
    drain(db, pf, control)
    assert one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s',
               (pf,)) is None
    assert parent_result(db, dispatch) == {
        'v': 1, 'mode': 'parallel', 'acc': [{'drained': 1}], 'joined': 1,
        'called': ['r7w'], 'bailed': False}
    _, later, _ = dispatch_create(db, scope, root['owner'])
    assert one(db, "SELECT count(*) FROM v24_cordis.effects WHERE kind='dispatch' "
                   'AND fiber_id=%s', (later,)) == 0
    print('[CDP5-R7] host proves generation/claim/settlement/withdrawal only; P7.1/P7.3 '
          'and E1-E3 remain external premises; sync_reads=false is not isolation')


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
        test_r5_purity(db)
        host_root = dict(payload=root, fiber=uuid.UUID(root['fiber_id']),
                         scope=uuid.UUID(root['scope']['id']), owner=owner)
        test_r6_reference(db, host_root)
        test_r6b_mixed_generation(db, host_root)
        test_r7_host_assumptions(db, host_root)
        test_r8_guard_acl(db, root, owner)
    print('[passed] CDP5-R (W4: R1-R8, five-mode reference, purity and host premises)')


if __name__ == '__main__':
    main()
