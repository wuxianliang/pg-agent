"""CDP5-E (W2): listener declaration and production registration only.

Run with: uv run python v24/cordis/dp5/test_listeners.py

E1-E7 are the W2 registration/revocation subset. W3 now provides the p4
producer and the D1-D12 event closure; this script still does not claim
ordering/unavailable/real-drain evidence, which lives in test_dispatch.py.
"""
from __future__ import annotations
import contextlib
import copy
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dp2'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dp3'))

from psycopg2.extras import Json  # noqa: E402
from test_support import (Server, TestDB, query, command, install_payload,  # noqa: E402
                          reconcile_payload, no_write, snapshot, sqlstate,
                          replace_function, principal)
from test_activation import (declaration, install, p0,  # noqa: E402
                             commit_new, commit_child, child_call, one, rows)
from test_teardown import enter_closing, drain  # noqa: E402

HOST = dict(contract_version='host_v1', handler_digest='b' * 64,
            replay=dict(repeat=False, concurrent=False))


def listener(listener_id='l1', event='fiber.activated', mode='emit', priority=0,
             filter=None, exec=None, contract_version=None, sync_reads=False):
    ex = dict(type='in_db', op='const', value={}) if exec is None else exec
    cv = contract_version or ('in_db_v1' if ex['type'] == 'in_db' else HOST['contract_version'])
    return dict(listener_id=listener_id, event=event, mode=mode, priority=priority,
                filter=filter, exec=ex, contract_version=cv, sync_reads=sync_reads)


def declaration_with(owner, scope, provides=(), listeners=None, contracts=None):
    payload = declaration(provides=list(provides), owner=owner, mode='existing',
                          existing=scope)
    if listeners is not None:
        payload['manifest']['listeners'] = copy.deepcopy(listeners)
    if contracts:
        payload['contracts'].update(copy.deepcopy(contracts))
    return payload


def activate_plan(db, fiber, total, control=0):
    parent, _, _ = p0(db, fiber, control)
    parent, begun = commit_child(db, parent,
                                 reconcile_payload(fiber, 'advance', control + 1))
    assert begun.get('disposition') == 'committed', begun
    left, batches = total, []
    while left:
        before = one(db, 'SELECT count(*) FROM v24_cordis.contributions '
                         'WHERE fiber_id=%s', (fiber,))
        parent, result = commit_child(db, parent,
                                      reconcile_payload(fiber, 'advance', control + 1))
        assert result.get('disposition') == 'committed', result
        after = one(db, 'SELECT count(*) FROM v24_cordis.contributions '
                        'WHERE fiber_id=%s', (fiber,))
        assert 1 <= after - before <= 32, (before, after)
        batches.append(after - before)
        left -= after - before
    parent, result = commit_child(db, parent,
                                  reconcile_payload(fiber, 'advance', control + 1))
    assert result.get('disposition') == 'committed', result
    assert one(db, 'SELECT state FROM v24_cordis.episodes e JOIN v24_cordis.fibers f '
                   'ON f.current_episode_id=e.id WHERE f.id=%s', (fiber,)) == 'active'
    return parent, batches, result


def create(db, payload, activate=True):
    effect, result, _ = commit_new(db, 'command_install', payload)
    assert result.get('disposition') == 'committed', result
    fiber = uuid.UUID(payload['fiber_id'])
    if activate:
        activate_plan(db, fiber, len(payload['manifest']['provides'])
                      + len(payload['manifest'].get('listeners', [])))
    return payload, fiber


def bad_install(db, payload, code='invalid_args'):
    with contextlib.closing(db.connect('service')) as conn:
        effect, outcome = command(db, conn, 'service', 'command_install', payload)
        return no_write(db, conn, effect, outcome, code=code)


def registration_plan(db, payload):
    return one(db, 'SELECT v24_cordis.registration_plan(i) FROM v24_cordis.installs i '
                   'WHERE id=%s', (uuid.UUID(payload['install_id']),))


def contribution_rows(db, fiber, kind=None):
    statement = ('SELECT seq,kind,realm,key,descriptor,inverse,contract_version '
                 'FROM v24_cordis.contributions WHERE fiber_id=%s')
    params = [fiber]
    if kind:
        statement += ' AND kind=%s'
        params.append(kind)
    return rows(db, statement + ' ORDER BY seq', tuple(params))


def applied(db, effect, outcome):
    with contextlib.closing(db.connect('service')) as conn:
        result = query(conn, 'SELECT v24_cordis.advance(%s,%s)',
                       (effect, Json(outcome)))[0][0]
        conn.commit()
    return result


def p6_attempt(db, fiber, control):
    off, result, _ = commit_new(db, 'command_reconcile',
                                reconcile_payload(fiber, 'off', control))
    assert result.get('disposition') == 'committed', result
    new_control = one(db, 'SELECT control_seq FROM v24_cordis.fibers WHERE id=%s', (fiber,))
    effect, outcome = child_call(db, off, reconcile_payload(fiber, 'advance', new_control))
    with contextlib.closing(db.connect('service')) as conn:
        got = query(conn, 'SELECT v24_cordis.advance(%s,%s)', (effect, Json(outcome)))[0][0]
        conn.commit()
    return got


def test_e1_manifest_and_overlay(db, scope, owner):
    legacy = declaration_with(owner, scope, provides=['legacy-svc'])
    create(db, legacy)
    empty = declaration_with(owner, scope, provides=['empty-svc'], listeners=[])
    create(db, empty)
    old_plan = registration_plan(db, legacy)
    empty_plan = registration_plan(db, empty)
    assert [x['kind'] for x in old_plan] == ['service']
    assert [x['kind'] for x in empty_plan] == ['service']
    assert old_plan[0]['descriptor'] == empty_plan[0]['descriptor']
    old_rows = contribution_rows(db, uuid.UUID(legacy['fiber_id']))
    empty_rows = contribution_rows(db, uuid.UUID(empty['fiber_id']))
    normalize = lambda row: (row[0], row[1], row[2], row[4], row[5], row[6])
    assert [normalize(x) for x in old_rows] == [normalize(x) for x in empty_rows]

    for label, mutate in (
            ('unknown fifth key', lambda m: m.update(listener=[])),
            ('listeners object', lambda m: m.update(listeners={})),
            ('listeners over 16', lambda m: m.update(listeners=[listener(f'x{i}') for i in range(17)])),
            ('listener extra key', lambda m: m.update(listeners=[dict(listener(), extra=1)]))):
        payload = declaration_with(owner, scope)
        mutate(payload['manifest'])
        bad_install(db, payload)
        print(f'  E1 reject: {label}')

    # W1 rejected every listener overlay target because no declaration existed.
    # W2 applies a declared listener patch, including a cross-namespace same name.
    same = listener('same', priority=1, filter=None)
    overlay = {'v': 1,
               'services': {'same': {'config': {'patched': True}}},
               'listeners': {'same': {'priority': 9,
                                      'filter': {'v': 1, 'op': 'equals',
                                                 'path': ['fiber_id'], 'value': 'x'}}}}
    payload = declaration_with(owner, scope, provides=['same'], listeners=[same])
    payload['overlay'] = overlay
    create(db, payload)
    stored = rows(db, 'SELECT kind,descriptor FROM v24_cordis.contributions '
                      'WHERE fiber_id=%s ORDER BY seq', (uuid.UUID(payload['fiber_id']),))
    assert stored[0][0] == 'service'
    assert stored[0][1]['config'] == {'patched': True}
    assert stored[1][0] == 'listener'
    assert stored[1][1]['listener_id'] == 'same' and stored[1][1]['priority'] == 9
    assert stored[1][1]['filter']['value'] == 'x'
    print('  E1 declared listener overlay patches priority/filter; service/listener same name are separate namespaces')

    for label, patch in (
            ('protected listener_id', {'listener_id': 'other'}),
            ('protected event', {'event': 'other'}),
            ('protected mode', {'mode': 'serial'}),
            ('protected exec', {'exec': {'type': 'in_db', 'op': 'acc'}}),
            ('protected contract', {'contract_version': 'other'}),
            ('protected sync_reads', {'sync_reads': True}),
            ('invalid filter', {'filter': {'v': 1, 'op': 'contains', 'path': ['x'], 'value': 1}})):
        payload = declaration_with(owner, scope, provides=['same'],
                                   listeners=[listener('same')])
        payload['overlay'] = {'v': 1, 'services': {}, 'listeners': {'same': patch}}
        bad_install(db, payload)
        print(f'  E1 overlay reject: {label}')
    payload = declaration_with(owner, scope, listeners=[listener('l1')])
    payload['overlay'] = {'v': 1, 'services': {}, 'listeners': {'missing': {'priority': 1}}}
    bad_install(db, payload)
    print('[CDP5-E1] legacy four-key and listeners=[] register identically; optional fifth key, '
          'unknown keys and declared-listener overlay validation')


def test_e2_cross_batch(db, scope, owner):
    provides = [f'e2-svc-{i:02d}' for i in range(30)]
    listeners = [listener(f'e2-l-{i:02d}') for i in range(3)]
    payload = declaration_with(owner, scope, provides=provides, listeners=listeners)
    effect, result, _ = commit_new(db, 'command_install', payload)
    assert result.get('disposition') == 'committed', result
    fiber = uuid.UUID(payload['fiber_id'])
    _, batches, final = activate_plan(db, fiber, 33)
    assert batches == [32, 1], batches
    assert len(final['emitted']) == 4, final
    assert final['ready_effects'] == [], final
    seqs = rows(db, 'SELECT seq,kind FROM v24_cordis.contributions WHERE fiber_id=%s '
                    'ORDER BY seq', (fiber,))
    assert [x[0] for x in seqs] == list(range(33))
    assert [x[1] for x in seqs] == ['service'] * 30 + ['listener'] * 3
    iterator = one(db, 'SELECT iterator FROM v24_cordis.episodes e JOIN v24_cordis.fibers f '
                       'ON f.current_episode_id=e.id WHERE f.id=%s', (fiber,))
    assert iterator['next_index'] == 33 and iterator['registered_through'] == 32
    plan = registration_plan(db, payload)
    assert [x['kind'] for x in plan] == ['service'] * 30 + ['listener'] * 3
    assert [x['index'] for x in plan] == list(range(33))
    assert one(db, "SELECT state FROM v24_cordis.episodes e JOIN v24_cordis.fibers f "
                   "ON f.current_episode_id=e.id WHERE f.id=%s", (fiber,)) == 'active'

    # A target change after batch one must Divert, never mix the old and new generation.
    drift = declaration_with(owner, scope,
                             provides=[f'e2d-svc-{i:02d}' for i in range(30)],
                             listeners=listeners)
    effect, result, _ = commit_new(db, 'command_install', drift)
    assert result.get('disposition') == 'committed', result
    drift_fiber = uuid.UUID(drift['fiber_id'])
    parent, _, _ = p0(db, drift_fiber)
    parent, _ = commit_child(db, parent, reconcile_payload(drift_fiber, 'advance', 1))
    parent, batch = commit_child(db, parent,
                                reconcile_payload(drift_fiber, 'advance', 1))
    assert batch.get('disposition') == 'committed', batch
    count = one(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id=%s',
                (drift_fiber,))
    assert count == 32, count
    off, off_result, _ = commit_new(db, 'command_reconcile',
                                    reconcile_payload(drift_fiber, 'off', 1))
    assert off_result.get('disposition') == 'committed', off_result
    assert off_result['emitted'] == [], off_result
    slot, outcome = child_call(db, parent, reconcile_payload(drift_fiber, 'advance', 1))
    diverted = applied(db, slot, outcome)
    assert diverted.get('disposition') == 'committed', diverted
    assert one(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id=%s',
               (drift_fiber,)) == 32
    episode = rows(db, 'SELECT state,outcome,iterator FROM v24_cordis.episodes e '
                       'JOIN v24_cordis.fibers f ON f.current_episode_id=e.id WHERE f.id=%s',
                   (drift_fiber,))[0]
    assert episode[0] == 'closing' and episode[1] == 'divert', episode
    assert episode[2]['next_index'] == 32 and episode[2]['registered_through'] == 31, episode
    print('[CDP5-E2] service+listener total 33 crosses two batches; seq/iterator/plan are '
          'continuous; P4 totality activates; a target change after batch one Diverts with no mixed registration')


def test_e3_identity(db, scope, owner):
    dup = [listener('dup'), listener('dup')]
    payload = declaration_with(owner, scope, listeners=dup)
    bad_install(db, payload)
    print('  E3 duplicate listener_id in one manifest rejected invalid_args')

    payload = declaration_with(owner, scope, listeners=[listener('reuse', event='tick')])
    create(db, payload)
    fiber = uuid.UUID(payload['fiber_id'])
    row = rows(db, "SELECT id,episode_id,descriptor FROM v24_cordis.contributions "
                   "WHERE fiber_id=%s AND kind='listener'", (fiber,))[0]
    contributor, episode, descriptor = row
    # Owner fixture: the DB unique index is the final defence for a same-episode
    # event/id collision; no production writer can produce this row after W2.
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        sqlstate(conn,
                 "INSERT INTO v24_cordis.contributions(id,fiber_id,episode_id,seq,kind,"
                 "descriptor,inverse,contract_version) VALUES(%s,%s,%s,1,'listener',%s,"
                 "'{\"op\":\"delete_row\"}','in_db_v1')",
                 (uuid.uuid4(), fiber, episode, Json(descriptor)), code='23505')
    print('  E3 same-episode event/listener_id collision is rejected by contributions_listener_addr')

    control = enter_closing(db, fiber)
    drain(db, fiber, control)
    assert one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s',
               (fiber,)) is None
    control = one(db, 'SELECT control_seq FROM v24_cordis.fibers WHERE id=%s', (fiber,))
    activate_plan(db, fiber, 1, control)
    reused = rows(db, "SELECT episode_id,released_at,withdrawn_at,descriptor "
                      "FROM v24_cordis.contributions WHERE fiber_id=%s AND kind='listener' "
                      "ORDER BY seq", (fiber,))
    assert len(reused) == 2, reused
    assert reused[0][0] != reused[1][0]
    old = next(x for x in reused if x[1] is not None)
    new = next(x for x in reused if x[1] is None)
    assert old[2] is not None and new[2] is None
    assert old[3] == new[3]
    print('[CDP5-E3] duplicate listener_id and same-episode event/id collision reject; a new '
          'episode reuses the same listener_id over the retained released row')


def test_e4_forged_delta(db, scope, owner):
    payload = declaration_with(owner, scope, provides=['e4-svc'],
                               listeners=[listener('e4-l')])
    effect, result, _ = commit_new(db, 'command_install', payload)
    assert result.get('disposition') == 'committed', result
    fiber = uuid.UUID(payload['fiber_id'])
    parent, _, _ = p0(db, fiber)
    parent, _ = commit_child(db, parent, reconcile_payload(fiber, 'advance', 1))
    child, outcome = child_call(db, parent, reconcile_payload(fiber, 'advance', 1))
    delta = one(db, 'SELECT v24_cordis.interpret_reconcile(%s,%s,%s,%s)',
                (child, principal(db.roles['service']), Json(outcome), Json([])))
    assert delta and delta['domain'], delta
    listener_op = next(x for x in delta['domain'] if x['kind'] == 'listener')
    service_op = next(x for x in delta['domain'] if x['kind'] == 'service')
    print(f"  E4 base delta: {service_op['kind']} seq {service_op['seq']}, "
          f"listener seq {listener_op['seq']}")

    original = None
    with contextlib.closing(db.connect('owner')) as conn:
        original = query(conn, "SELECT pg_get_functiondef('v24_cordis.interpret_reconcile"
                               "(uuid,uuid,jsonb,jsonb)'::regprocedure)")[0][0]
    replace_function(db, '''CREATE OR REPLACE FUNCTION v24_cordis.interpret_reconcile(
 p_effect_id uuid,p_principal uuid,p_outcome jsonb,p_closure jsonb) RETURNS jsonb
LANGUAGE plpgsql SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
BEGIN
 RETURN current_setting('cordis_e4.delta',true)::jsonb;
END $$;''')
    labels = ('listener realm', 'listener key', 'listener prev', 'listener inverse',
              'listener contract', 'listener seq', 'listener descriptor',
              'missing append', 'extra typed append')
    try:
        for label in labels:
            forged = copy.deepcopy(delta)
            forged_listener = next(x for x in forged['domain'] if x.get('kind') == 'listener')
            if label == 'listener realm':
                forged_listener['realm'] = 'root'
            elif label == 'listener key':
                forged_listener['key'] = 'not-an-address'
            elif label == 'listener prev':
                forged_listener['prev_contribution_id'] = str(uuid.uuid4())
            elif label == 'listener inverse':
                forged_listener['inverse'] = {'op': 'dispose_child'}
            elif label == 'listener contract':
                forged_listener['contract_version'] = 'wrong'
            elif label == 'listener seq':
                forged_listener['seq'] = 99
            elif label == 'listener descriptor':
                forged_listener['descriptor']['priority'] = 7
            elif label == 'missing append':
                forged['domain'].remove(forged_listener)
            elif label == 'extra typed append':
                extra = copy.deepcopy(forged_listener)
                extra['id'] = str(uuid.uuid4())
                extra['seq'] = 99
                extra['descriptor']['listener_id'] = 'e4-extra'
                forged['domain'].append(extra)
            with contextlib.closing(db.connect('owner')) as snap:
                before = snapshot(snap)
            with contextlib.closing(db.connect('service')) as conn:
                query(conn, 'SELECT set_config(%s,%s,false)',
                      ('cordis_e4.delta', json.dumps(forged)))
                result = query(conn, 'SELECT v24_cordis.advance(%s,%s)',
                               (child, Json(outcome)))[0][0]
                assert result.get('error', {}).get('code') == 'invalid_outcome', (label, result)
                conn.rollback()
            with contextlib.closing(db.connect('owner')) as snap:
                assert snapshot(snap) == before, label
            print(f'  E4 forged {label}: invalid_outcome, zero write')
    finally:
        replace_function(db, original)
    committed = applied(db, child, outcome)
    assert committed.get('disposition') == 'committed', committed
    print('[CDP5-E4] forged listener realm/key/prev/inverse/contract/seq/descriptor and '
          'missing/extra appends are invalid_outcome with zero write; the unmodified plan commits')

    # A forged P4 delta cannot paper over a missing listener contribution.
    p4 = declaration_with(owner, scope, listeners=[listener('p4-a'), listener('p4-b')])
    effect, result, _ = commit_new(db, 'command_install', p4)
    assert result.get('disposition') == 'committed', result
    p4_fiber = uuid.UUID(p4['fiber_id'])
    parent, _, _ = p0(db, p4_fiber)
    parent, _ = commit_child(db, parent, reconcile_payload(p4_fiber, 'advance', 1))
    parent, batch = commit_child(db, parent, reconcile_payload(p4_fiber, 'advance', 1))
    assert batch.get('disposition') == 'committed', batch
    next_effect, next_outcome = child_call(db, parent,
                                           reconcile_payload(p4_fiber, 'advance', 1))
    p4_delta = one(db, 'SELECT v24_cordis.interpret_reconcile(%s,%s,%s,%s)',
                   (next_effect, principal(db.roles['service']), Json(next_outcome),
                    Json([])))
    assert p4_delta['domain'][0]['op'] == 'episode_activate', p4_delta
    victim = one(db, "SELECT id FROM v24_cordis.contributions WHERE fiber_id=%s "
                     "AND kind='listener' ORDER BY seq LIMIT 1", (p4_fiber,))
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, 'UPDATE v24_cordis.contributions SET withdrawn_at=clock_timestamp() '
                    'WHERE id=%s', (victim,))
        conn.commit()
    replace_function(db, '''CREATE OR REPLACE FUNCTION v24_cordis.interpret_reconcile(
 p_effect_id uuid,p_principal uuid,p_outcome jsonb,p_closure jsonb) RETURNS jsonb
LANGUAGE plpgsql SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
BEGIN
 RETURN current_setting('cordis_e4.delta',true)::jsonb;
END $$;''')
    try:
        with contextlib.closing(db.connect('owner')) as snap:
            before = snapshot(snap)
        with contextlib.closing(db.connect('service')) as conn:
            query(conn, 'SELECT set_config(%s,%s,false)',
                  ('cordis_e4.delta', json.dumps(p4_delta)))
            result = query(conn, 'SELECT v24_cordis.advance(%s,%s)',
                           (next_effect, Json(next_outcome)))[0][0]
            assert result.get('error', {}).get('code') == 'invalid_outcome', result
            conn.rollback()
        with contextlib.closing(db.connect('owner')) as snap:
            assert snapshot(snap) == before
    finally:
        replace_function(db, original)
    print('  E4 forged P4 with a withdrawn listener is invalid_outcome p4_totality with zero write')


def test_e5_declaration_bounds(db, scope, owner):
    valid = [listener(f'e5-{i:02d}', exec={'type': 'in_db', 'op': 'acc'})
             for i in range(16)]
    payload = declaration_with(owner, scope, listeners=valid)
    effect, result, _ = commit_new(db, 'command_install', payload)
    assert result.get('disposition') == 'committed', result
    plan = registration_plan(db, payload)
    assert len(plan) == 16 and all(x['kind'] == 'listener' for x in plan)
    fiber = uuid.UUID(payload['fiber_id'])
    parent, _, _ = p0(db, fiber, 0)
    parent, begun = commit_child(db, parent, reconcile_payload(fiber, 'advance', 1))
    assert begun.get('disposition') == 'committed', begun
    parent, batch = commit_child(db, parent, reconcile_payload(fiber, 'advance', 1))
    assert batch.get('disposition') == 'committed', batch
    _, overflow = commit_child(db, parent, reconcile_payload(fiber, 'advance', 1))
    assert overflow.get('error', {}).get('code') == 'invalid_outcome', overflow
    assert one(db, 'SELECT state FROM v24_cordis.episodes e JOIN v24_cordis.fibers f '
                   'ON f.current_episode_id=e.id WHERE f.id=%s', (fiber,)) == 'reloading'
    assert one(db, "SELECT count(*) FROM v24_cordis.effects WHERE kind='dispatch' "
                   'AND fiber_id=%s', (fiber,)) == 0

    seventeen = declaration_with(owner, scope,
                                 listeners=[listener(f'e5x-{i:02d}') for i in range(17)])
    bad_install(db, seventeen)
    host = listener('e5-host', exec={'type': 'host', 'capability': 'listener_call'})
    host_payload = declaration_with(owner, scope, listeners=[host],
                                    contracts={'listener_call': dict(HOST)})
    create(db, host_payload)
    assert registration_plan(db, host_payload)[0]['descriptor']['exec']['type'] == 'host'
    print('  E5 16 declared listeners register but p4 rejects the 17-created budget; 17 reject invalid_args')

    def reject(label, mutate):
        item = listener('bad')
        mutate(item)
        payload = declaration_with(owner, scope, listeners=[item])
        if label.startswith('host') and label != 'host missing contract':
            payload['contracts']['listener_call'] = dict(HOST)
        bad_install(db, payload)
        print(f'  E5 reject: {label}')

    reject('missing sync_reads', lambda x: x.pop('sync_reads'))
    reject('sync_reads true', lambda x: x.update(sync_reads=True))
    reject('sync_reads null', lambda x: x.update(sync_reads=None))
    reject('sync_reads string', lambda x: x.update(sync_reads='false'))
    reject('invalid mode', lambda x: x.update(mode='broadcast'))
    reject('priority float', lambda x: x.update(priority=1.5))
    reject('priority overflow', lambda x: x.update(priority=2147483648))
    reject('filter empty path', lambda x: x.update(filter={
        'v': 1, 'op': 'equals', 'path': [], 'value': 1}))
    reject('filter op', lambda x: x.update(filter={
        'v': 1, 'op': 'contains', 'path': ['x'], 'value': 1}))
    reject('exec unknown type', lambda x: x.update(exec={'type': 'sql', 'op': 'const'}))
    reject('const missing value', lambda x: x.update(exec={'type': 'in_db', 'op': 'const'}))
    reject('acc extra key', lambda x: x.update(exec={'type': 'in_db', 'op': 'acc', 'x': 1}))
    reject('append missing value', lambda x: x.update(exec={'type': 'in_db', 'op': 'append'}))
    reject('fail missing code', lambda x: x.update(exec={'type': 'in_db', 'op': 'fail'}))
    reject('fail empty code', lambda x: x.update(exec={
        'type': 'in_db', 'op': 'fail', 'code': ''}))
    reject('host capability', lambda x: x.update(exec={
        'type': 'host', 'capability': 'other'}))
    reject('host extra key', lambda x: x.update(exec={
        'type': 'host', 'capability': 'listener_call', 'x': 1}))
    reject('in_db version', lambda x: x.update(contract_version='other'))
    reject('host missing contract', lambda x: x.update(exec={
        'type': 'host', 'capability': 'listener_call'}))
    reject('host version mismatch', lambda x: x.update(contract_version='host_v2'))
    reject('listener_id empty', lambda x: x.update(listener_id=''))
    reject('event empty', lambda x: x.update(event=''))
    reject('listener_id long', lambda x: x.update(listener_id='x' * 129))
    reject('listener extra key', lambda x: x.update(extra=1))
    print('[CDP5-E5] 16/17 boundary and invalid mode/filter/exec/contract/sync_reads/identity '
          'declarations all reject invalid_args with zero write')


def test_e6_withdraw_and_release(db, scope, owner):
    provides = [f'e6-svc-{i:02d}' for i in range(30)]
    listeners = [listener(f'e6-l-{i:02d}') for i in range(3)]
    payload = declaration_with(owner, scope, provides=provides, listeners=listeners)
    create(db, payload)
    fiber = uuid.UUID(payload['fiber_id'])
    before = rows(db, "SELECT id,descriptor,inverse FROM v24_cordis.contributions "
                      'WHERE fiber_id=%s AND kind=%s ORDER BY seq', (fiber, 'listener'))
    control = enter_closing(db, fiber)
    withdrawn = rows(db, "SELECT id,withdrawn_at,released_at FROM v24_cordis.contributions "
                         'WHERE fiber_id=%s AND kind=%s ORDER BY seq', (fiber, 'listener'))
    assert len(withdrawn) == 3
    assert all(x[1] is not None and x[2] is None for x in withdrawn)
    assert rows(db, "SELECT id,descriptor,inverse FROM v24_cordis.contributions "
                    'WHERE fiber_id=%s AND kind=%s ORDER BY seq', (fiber, 'listener')) == before
    plan = one(db, 'SELECT v24_cordis.p6_plan(NULL,%s)', (fiber,))
    assert plan['kind'] == 'inverse', plan
    seqs = [one(db, 'SELECT seq FROM v24_cordis.contributions WHERE id=%s', (x,))
            for x in plan['contribution_ids']]
    assert seqs == sorted(seqs, reverse=True), (seqs, plan)
    released_events = []
    for result in drain(db, fiber, control):
        released_events.extend(rows(
            db, "SELECT payload FROM v24_cordis.events WHERE effect_id=%s "
                "AND event_kind='contributions_released'", (result['effect_id'],)))
    assert released_events[0][0]['seq_from'] == 32, released_events
    assert released_events[0][0]['seq_through'] == 1, released_events
    assert released_events[1][0]['seq_from'] == 0, released_events
    assert released_events[1][0]['seq_through'] == 0, released_events
    after = rows(db, "SELECT id,withdrawn_at,released_at,descriptor,inverse "
                     'FROM v24_cordis.contributions WHERE fiber_id=%s AND kind=%s ORDER BY seq',
                 (fiber, 'listener'))
    assert len(after) == 3
    assert all(x[1] is not None and x[2] is not None and x[2] >= x[1] for x in after)
    assert all(x[3] == before[i][1] and x[4] == before[i][2]
               for i, x in enumerate(after))
    assert one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s',
               (fiber,)) is None
    print('[CDP5-E6] production P5 withdraws all listener rows; P6 releases in strict LIFO '
          'batches 32..1 then 0..0 and retains the historical listener rows/descriptors/inverse')


def test_e7_no_pin_and_fixture_barrier(db, scope, owner):
    def closed_listener(index):
        payload = declaration_with(owner, scope,
                                   listeners=[listener(f'e7-l-{index}')])
        create(db, payload)
        fiber = uuid.UUID(payload['fiber_id'])
        control = enter_closing(db, fiber)
        episode = one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s',
                      (fiber,))
        return fiber, episode, control

    fiber, _, _ = closed_listener(0)
    listener_ids = [x[0] for x in rows(
        db, "SELECT id FROM v24_cordis.contributions WHERE fiber_id=%s AND kind='listener'",
        (fiber,))]
    assert listener_ids
    assert one(db, 'SELECT count(*) FROM v24_cordis.pins WHERE contribution_id=ANY(%s)',
               (listener_ids,)) == 0
    assert one(db, 'SELECT count(*) FROM v24_cordis.runs WHERE owner_fiber_id=%s',
               (fiber,)) == 0
    # W3 supersedes the W2 no-producer assertion: activation now emits a dispatch
    # and its in_db children. The registration/revocation evidence is unchanged.
    assert one(db, "SELECT count(*) FROM v24_cordis.effects WHERE fiber_id=%s "
                   "AND kind='dispatch'", (fiber,)) == 1
    assert one(db, "SELECT count(*) FROM v24_cordis.effects WHERE fiber_id=%s "
                   "AND kind='listener_call'", (fiber,)) >= 1
    # Owner fixtures: W2 has no dispatch producer. These provider-owned rows prove
    # the existing P6 barrier facts without claiming a real listener drain.
    for index, (status, expected) in enumerate((('ready', 'deferred'),
                                                ('claimed', 'deferred')), start=1):
        fiber, episode, control = closed_listener(index)
        effect = uuid.uuid4()
        with contextlib.closing(db.connect('owner')) as conn:
            query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
            query(conn, "INSERT INTO v24_cordis.effects(id,kind,status,fiber_id,episode_id,"
                        "input,request_actor,claim_owner,lease_until) VALUES(%s,'listener_call',"
                        "%s,%s,%s,'{}',%s,%s,%s)",
                  (effect, status, fiber, episode, db.roles['service'],
                   db.roles['service'] if status == 'claimed' else None,
                   'infinity' if status == 'claimed' else None))
            conn.commit()
        got = p6_attempt(db, fiber, control)
        assert got.get('disposition') == expected, (status, got)
        print(f'  E7 fixture {status} listener_call: P6 {expected}')
    fiber, episode, control = closed_listener(3)
    effect = uuid.uuid4()
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, "INSERT INTO v24_cordis.effects(id,kind,status,fiber_id,episode_id,input,"
                    "request_actor,outcome,settled_at) VALUES(%s,'listener_call','unknown',%s,%s,"
                    "'{}',%s,%s,now())",
              (effect, fiber, episode, db.roles['service'],
               Json(dict(v=1, **{'class': 'unknown'}, claim=None,
                         body=dict(kind='listener_call')))))
        conn.commit()
    got = p6_attempt(db, fiber, control)
    assert got.get('error', {}).get('code') == 'blocked_unknown', got
    print('[CDP5-E7] listeners create no pin/run; fixture provider-owned ready/claimed block P6 '
          'as deferred and unknown blocks it as blocked_unknown')


def main():
    with Server() as server, TestDB(server) as db:
        root, _, _ = install(db)
        activate_plan(db, uuid.UUID(root['fiber_id']), 0)
        scope = root['scope']['id']
        owner = dict(fiber_id=root['fiber_id'],
                     episode_id=str(one(db, 'SELECT current_episode_id FROM v24_cordis.fibers '
                                            'WHERE id=%s', (root['fiber_id'],))))
        test_e1_manifest_and_overlay(db, scope, owner)
        test_e2_cross_batch(db, scope, owner)
        test_e3_identity(db, scope, owner)
        test_e4_forged_delta(db, scope, owner)
        test_e5_declaration_bounds(db, scope, owner)
        test_e6_withdraw_and_release(db, scope, owner)
        test_e7_no_pin_and_fixture_barrier(db, scope, owner)
    print('[passed] CDP5-E (W2: E1-E7 registration/revocation subset; '
          'ordering/unavailable/real drain are W3 D evidence)')


if __name__ == '__main__':
    main()
