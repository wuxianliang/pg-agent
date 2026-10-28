"""CDP4-B: layout, ACL, budget, write surface, structural limits and frozen surface."""
from __future__ import annotations
import contextlib
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dp2'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dp1'))

import psycopg2
from psycopg2 import sql
from psycopg2.extras import Json

from dp4_support import (Server, TestDB, snapshot, query, env, claim, settle,
                         prepare_run, model_body, tool_call, q1, rows,
                         provider, agent, install_payload, commit_new, phases, active_owner,
                         reconcile_payload)
from test_support import (assert_helper_budget, prove_helper_budget_boundary, LIMIT, no_write,
                          sqlstate, seed_fiber)
from test_kernel import host_seed

CORDIS = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[3]
SQL = CORDIS / 'sql'
HELPERS = ('40_advance.sql', '41_lifecycle.sql', '42_teardown.sql', '43_loop.sql', '44_events.sql')
DDL = ('10_installs.sql', '11_scopes.sql', '12_fibers.sql', '13_episodes.sql',
       '14_contributions.sql', '15_pins.sql', '16_runs.sql', '17_effects.sql',
       '20_relations.sql', '30_triggers.sql')
FROZEN = {
    '00_schema.sql': '05b6b47e0f71881e64fba3c55609c16608e4bc15c44f321ad5a87ede7979bc6d',
    '10_schema.sql': 'a365a235edefe49258038bef4b28a3cd5f8204ab22a71336e892efc706cbae76',
    '20_triggers.sql': '1c75ce97c79abdba9151bd8dfd22bb7b1167c10e256ed8fa54d4adf927da5af1',
    '30_advance.sql': '087a5bcdb4b9132e25b2d04bc0a31606d429fba5d5cfbb0a257f0a2440715870',
    '40_interpreters.sql': '2ebefff558f243891a613787a47ef68dcfb825b1bcc16b78f019e328f982c5f9',
    '45_capability.sql': 'f629ddd511754a4828da4b4dc4da278c1a4bfcb2359f15f00fd6634f9e4f332e',
    '46_cleanup.sql': 'bb32336bf6e262f62a55a78d55bf3ac7b649c06a50bdda9eda6263f96ed083ef',
    '47_verbs.sql': '5c5bdc611f33f5b37d1652f29aeda97323882487c27cf800ac53371a76ea0265',
    '48_loop.sql': 'f23a93cdd5c14966442bf30eb1339b6e110c3b1c279b95650704aa9e12870f30',
    '49_host_reads.sql': '242748a0fe29cbedc723df9d5de18dd1fba7e9767cfce56a3bc218d1a17ce6c4',
    '49_recovery.sql': 'b46abde9f5fc4259f9ea833440ca0c0815a4a14a578e058b861f59990d90af8d',
    '50_permissions.sql': '578cba9fefc0e0238d6ffd42e458b235bd59ae56a7fa6b1f84a2de36fddbdafe',
}


def _snap(db):
    with contextlib.closing(db.connect('owner')) as conn:
        return snapshot(conn)


def _source():
    return '\n'.join((SQL / name).read_text() for name in sorted(p.name for p in SQL.glob('*.sql')))


def test_b1_b2_layout(db):
    names = sorted(p.name for p in SQL.glob('*.sql'))
    assert len(names) == 19, names
    spec = importlib.util.spec_from_file_location('cordis_dp4_loader', CORDIS / 'load.py')
    loader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)
    assert tuple(loader.SQL_LOAD_ORDER) == tuple(loader.CANONICAL_ORDER)
    assert len(loader.CANONICAL_ORDER) == 19
    assert set(names) == set(loader.CANONICAL_ORDER)
    assert loader.CANONICAL_ORDER.index('42_teardown.sql') < loader.CANONICAL_ORDER.index(
        '43_loop.sql') < loader.CANONICAL_ORDER.index('44_events.sql') < loader.CANONICAL_ORDER.index('50_permissions.sql')
    loader.self_check_manifest()
    prove_helper_budget_boundary()
    total, counts = assert_helper_budget(SQL)
    assert set(counts) == set(HELPERS), counts
    assert counts == {name: len((SQL / name).read_text().splitlines()) for name in HELPERS}
    assert counts['43_loop.sql'] <= 700, counts
    assert total <= LIMIT, total
    ddl = sum(len((SQL / name).read_text().splitlines()) for name in DDL)
    assert ddl <= 900, ddl
    text = _source()
    assert re.search(r'\bCREATE\s+(OR\s+REPLACE\s+)?(MATERIALIZED\s+)?VIEW\b', text, re.I) is None
    assert re.search(r'\bCREATE\s+EXTENSION\b', text, re.I) is None
    with contextlib.closing(db.connect('owner')) as conn:
        assert query(conn, "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                           "WHERE n.nspname='v24_cordis' AND c.relkind='r'")[0][0] == 10
        assert query(conn, "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                           "WHERE n.nspname='v24_cordis' AND c.relkind IN ('v','m')")[0][0] == 0
        assert query(conn, "SELECT extname FROM pg_extension WHERE extname<>'plpgsql'") == []
        assert query(conn, "SELECT proname FROM pg_proc WHERE pronamespace='v24_cordis'::regnamespace "
                           "AND prosecdef") == [('advance',)]
        public_exec = query(conn, "SELECT count(*) FROM pg_proc p WHERE p.pronamespace='v24_cordis'::regnamespace "
                                  "AND EXISTS(SELECT 1 FROM aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a "
                                  "WHERE a.grantee=0 AND a.privilege_type='EXECUTE')")[0][0]
        assert public_exec == 0, public_exec
        public_dml = query(conn, "SELECT count(*) FROM pg_class c CROSS JOIN LATERAL "
                                 "aclexplode(coalesce(c.relacl,acldefault('r',c.relowner))) a "
                                 "WHERE c.relnamespace='v24_cordis'::regnamespace AND c.relkind='r' "
                                 "AND a.grantee=0 AND a.privilege_type IN ('INSERT','UPDATE','DELETE')")[0][0]
        assert public_dml == 0, public_dml
        assert query(conn, "SELECT has_schema_privilege('public','v24_cordis','USAGE')")[0][0] is False
        for alias in ('admin', 'service', 'operator'):
            allowed = query(conn, "SELECT p.proname FROM pg_proc p "
                                  "WHERE p.pronamespace='v24_cordis'::regnamespace "
                                  "AND has_function_privilege(%s,p.oid,'EXECUTE') ORDER BY p.proname",
                            (db.roles[alias],))
            assert allowed == [('advance',)], (alias, allowed)
    print(f'[CDP4-B1] tables=10 manifest=19 helpers={total} 43={counts["43_loop.sql"]} '
          f'ddl={ddl} definer=advance public_execute=0 views/extensions=0')
    print(f'[CDP4-B2] {LIMIT}/{LIMIT + 1} helper-tree predicate reran; DDL {ddl}<=900; 43<=700')


def test_b3_acl(db, other):
    # Real production run_start -> model -> tool, plus owner-fixture host_io.
    provider(db, 'model_call', 'model')
    provider(db, 'tool_call', 'tool')
    chat = agent(db)
    rs = q1(db, 'SELECT id FROM v24_cordis.effects WHERE fiber_id=%s AND kind=\'run_start\' '
                'AND status=\'ready\' ORDER BY id LIMIT 1', (chat['fiber'],))
    assert rs is not None
    for alias in ('admin', 'operator'):
        with contextlib.closing(db.connect(alias)) as conn:
            no_write(db, conn, rs, env('claim', {'lease_ms': 300000}), 'unauthorized')
        with contextlib.closing(db.connect(alias)) as conn:
            no_write(db, conn, rs, env('success', {'v': 1, 'request': {}, 'steps': 2}, {'attempt': 0, 'fence': 0, 'owner': 'x'}), 'unauthorized')
    c = claim(db, rs)
    assert c.get('disposition') == 'claimed', c
    settled = settle(db, rs, {'v': 1, 'request': {}, 'steps': 2}, c['claim'])
    assert settled['disposition'] == 'committed' and len(settled['emitted']) == 1, settled
    model = uuid.UUID(settled['emitted'][0])
    for alias in ('admin', 'operator'):
        with contextlib.closing(db.connect(alias)) as conn:
            no_write(db, conn, model, env('claim', {'lease_ms': 300000}), 'unauthorized')
        with contextlib.closing(db.connect(alias)) as conn:
            no_write(db, conn, model, env('failure', {'kind': 'model_call',
                     'error': {'code': 'x'}}, {'attempt': 0, 'fence': 0, 'owner': 'x'}), 'unauthorized')
    mc = claim(db, model)
    mr = settle(db, model, model_body([tool_call('c1', 'tool')]), mc['claim'])
    assert mr['disposition'] == 'committed' and len(mr['emitted']) == 1, mr
    tool = uuid.UUID(mr['emitted'][0])
    for alias in ('admin', 'operator'):
        with contextlib.closing(db.connect(alias)) as conn:
            no_write(db, conn, tool, env('claim', {'lease_ms': 300000}), 'unauthorized')
        with contextlib.closing(db.connect(alias)) as conn:
            no_write(db, conn, tool, env('success', {'kind': 'tool_call', 'result': {
                'status': 'ok', 'output': {}, 'usage': None}}, {'attempt': 0, 'fence': 0, 'owner': 'x'}), 'unauthorized')
    tc = claim(db, tool)
    tr = settle(db, tool, {'kind': 'tool_call', 'result': {'status': 'ok', 'output': {},
                                                          'usage': None}}, tc['claim'])
    assert tr['disposition'] == 'committed', tr

    item = host_seed(db)
    hc = claim(db, item['effect'])
    assert hc.get('disposition') == 'claimed', hc
    with contextlib.closing(db.connect('service')) as conn:
        before = _snap(db)
        sqlstate(conn, 'SELECT v24_cordis.advance(%s,%s)',
                 (item['effect'], Json(env('success', {}, hc['claim']))))
        assert _snap(db) == before

    # A real foreign-family LOGIN with explicit grants is still unauthorized.
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, sql.SQL('GRANT USAGE ON SCHEMA v24_cordis TO {}').format(
            sql.Identifier(other.roles['service'])))
        query(conn, sql.SQL('GRANT EXECUTE ON FUNCTION v24_cordis.advance(uuid,jsonb) TO {}').format(
            sql.Identifier(other.roles['service'])))
        conn.commit()
    foreign = host_seed(db)
    try:
        with contextlib.closing(db.server.connect(db.name, other.roles['service'])) as conn:
            no_write(db, conn, foreign['effect'], env('claim', {'lease_ms': 1000}), 'unauthorized')
    finally:
        with contextlib.closing(db.connect('owner')) as conn:
            query(conn, sql.SQL('REVOKE EXECUTE ON FUNCTION v24_cordis.advance(uuid,jsonb) FROM {}').format(
                sql.Identifier(other.roles['service'])))
            query(conn, sql.SQL('REVOKE USAGE ON SCHEMA v24_cordis FROM {}').format(
                sql.Identifier(other.roles['service'])))
            conn.commit()
    print('[CDP4-B3] service claims host_io (settlement 0A000) and claims/settles run_start+model+tool; '
          'admin/operator are '
          'unauthorized for all run-kind claim+settle; foreign family is unauthorized')


def test_b4_surface(db):
    advance = (SQL / '40_advance.sql').read_text()
    run_slice = advance[advance.index("ELSIF v_op='run_create'"):advance.index(
        "ELSIF v_op='contribution_append'")]
    assert run_slice.count("ELSIF v_op='run_") == 5
    assert run_slice.count('INSERT INTO v24_cordis.runs') == 1
    assert run_slice.count('UPDATE v24_cordis.runs') == 3
    assert run_slice.count('INSERT INTO v24_cordis.pins') == 1
    assert 'UPDATE v24_cordis.pins' not in run_slice
    assert 'DELETE FROM v24_cordis.runs' not in advance
    assert advance.count('UPDATE v24_cordis.pins') == 1
    release = advance[advance.index("ELSIF v_op='pins_release'"):]
    assert release.index('UPDATE v24_cordis.pins') < release.index("ELSIF v_op='episode_close'")

    text = _source()
    assert re.search(r'\bCREATE\s+(OR\s+REPLACE\s+)?FUNCTION\s+v24_cordis\.'
                     r'(recover|scanner|sweep)\w*\s*\(', text, re.I) is None
    x = prepare_run(db, 3, ('toolb',), model_key='brain')
    mc = claim(db, x['model_effect'])
    before = _snap(db)
    bad = settle(db, x['model_effect'], model_body([tool_call('c1', 'brain')]), mc['claim'])
    assert bad['error']['code'] == 'invalid_outcome', bad
    assert _snap(db) == before
    assert q1(db, 'SELECT status FROM v24_cordis.effects WHERE id=%s',
              (x['model_effect'],)) == 'claimed'
    good = settle(db, x['model_effect'], model_body([tool_call('c1', 'toolb')]), mc['claim'])
    assert good['disposition'] == 'committed' and len(good['emitted']) == 1, good
    with contextlib.closing(db.connect('owner')) as conn:
        body = query(conn, "SELECT pg_get_functiondef('v24_cordis.run_pin_release_delta(uuid)'::regprocedure)")[0][0]
        assert re.search(r'\b(INSERT|UPDATE|DELETE)\b', body, re.I) is None
        principal = query(conn, 'SELECT v24_cordis.principal_id(session_user)')[0][0]
        item = host_seed(db)
        for status, settled in (('ready', False), ('claimed', False), ('succeeded', True),
                                ('failed', True), ('unknown', True), ('cancelled', True)):
            query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
            query(conn, '''UPDATE v24_cordis.effects SET status=%s,claim_owner=%s,
              lease_until=CASE WHEN %s='claimed' THEN now()+interval '1 hour' ELSE NULL END,
              outcome=%s,settled_at=CASE WHEN %s THEN now() ELSE NULL END WHERE id=%s''',
                  (status, 'seed' if status == 'claimed' else None, status,
                   Json({}) if status in ('succeeded', 'failed', 'unknown') else None,
                   settled, item['effect']))
            before = _snap(db)
            sqlstate(conn, 'SELECT v24_cordis.interpret_settlement(%s,%s,%s,%s)',
                     (item['effect'], principal, Json(env('success', {}, None)), Json([])))
            assert _snap(db) == before, status
            conn.rollback()
    # Production advance path for a claimed host_io effect.
    ready = host_seed(db)
    hc = claim(db, ready['effect'])
    before = _snap(db)
    with contextlib.closing(db.connect('service')) as conn:
        sqlstate(conn, 'SELECT v24_cordis.advance(%s,%s)',
                 (ready['effect'], Json(env('success', {}, hc['claim']))))
    assert _snap(db) == before
    for kind in ('dispatch', 'listener_call'):
        item = host_seed(db, kind=kind)
        with contextlib.closing(db.connect('service')) as conn:
            no_write(db, conn, item['effect'], env('claim', {'lease_ms': 1000}), 'unauthorized')
    print('[CDP4-B4] runs write only via 4 typed ops, pins only via run_pin_bind; host_io six '
          'states are 0A000; brain-key tool_calls is invalid_outcome; dispatch/listener unclaimable; '
          'no scanner; release delta is read-only')


def test_b5_limits(db):
    with contextlib.closing(db.connect('owner')) as conn:
        base = dict(domain=[], receipt=dict(status='succeeded'), events=[], successors=[])
        sixteen = [dict(ordinal=i, kind='host_io', input={}) for i in range(16)]
        assert query(conn, 'SELECT v24_cordis.validate_delta(%s,%s,%s)',
                     (Json(dict(base, successors=sixteen)), 'command', True))[0][0] is None
        seventeen = sixteen + [dict(ordinal=16, kind='host_io', input={})]
        assert query(conn, 'SELECT v24_cordis.validate_delta(%s,%s,%s)',
                     (Json(dict(base, successors=seventeen)), 'command', True))[0][0]['error']['code'] == 'invalid_outcome'
        batch16 = [dict(ordinal=i, key=f'k{i}', call_id=f'c{i}') for i in range(16)]
        batch17 = batch16 + [dict(ordinal=16, key='k16', call_id='c16')]
        state = dict(v=1, origin=str(uuid.uuid4()), step=0, phase='tools', batch=batch16, final=False)
        assert query(conn, 'SELECT v24_cordis.run_state_valid(%s)', (Json(state),))[0][0] is True
        assert query(conn, 'SELECT v24_cordis.run_state_valid(%s)',
                     (Json(dict(state, batch=batch17)),))[0][0] is False
        def pins(n):
            return [dict(id=str(uuid.uuid4()), key=f'p{i}', contribution_id=str(uuid.uuid4()),
                         provider_episode_id=str(uuid.uuid4()), provider_epoch=1) for i in range(n)]
        bind = dict(op='run_pin_bind', run_id=str(uuid.uuid4()), pins=pins(32))
        assert query(conn, 'SELECT v24_cordis.validate_delta(%s,%s,%s)',
                     (Json(dict(base, domain=[bind])), 'command', True))[0][0] is None
        bind33 = dict(bind, pins=pins(33))
        assert query(conn, 'SELECT v24_cordis.validate_delta(%s,%s,%s)',
                     (Json(dict(base, domain=[bind33])), 'command', True))[0][0]['error']['code'] == 'invalid_outcome'
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        scopes = [uuid.uuid4() for _ in range(513)]
        query(conn, 'INSERT INTO v24_cordis.scopes(id) SELECT unnest(%s::uuid[])', (scopes,))
        seed = [dict(t='scopes', id=str(item)) for item in scopes]
        assert len(query(conn, 'SELECT v24_cordis.discover_closure(%s)', (Json(seed[:512]),))[0][0]) == 512
        assert query(conn, 'SELECT v24_cordis.discover_closure(%s)', (Json(seed),))[0][0] is None
        conn.rollback()

    x = prepare_run(db, 3)
    run = rows(db, 'SELECT owner_fiber_id,owner_episode_id FROM v24_cordis.runs WHERE id=%s', (x['run_id'],))[0]
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, "INSERT INTO v24_cordis.effects(id,run_id,fiber_id,episode_id,kind,status,"
                    "input,request_actor,outcome,settled_at) SELECT gen_random_uuid(),%s,%s,%s,"
                    "'tool_call','succeeded','{}',%s,'{}',now() FROM generate_series(1,600)",
              (x['run_id'], run[0], run[1], db.roles['service']))
        conn.commit()
    seed = q1(db, 'SELECT v24_cordis.settlement_seed(%s)', (x['model_effect'],))
    assert len(seed) < 50, len(seed)
    closure = q1(db, 'SELECT v24_cordis.discover_closure(%s)', (Json(seed),))
    assert closure is not None and len(closure) < 50, closure
    host = host_seed(db)
    assert q1(db, 'SELECT v24_cordis.settlement_seed(%s)', (host['effect'],)) == [
        {'t': 'effects', 'id': str(host['effect'])}]
    print('[CDP4-B5] successor16/17, batch16/17, pins32/33 and closure512/513; 600 history '
          'effects leave a small seed; host_io seed is byte-identical')


def test_b5_manifest(db):
    def manifest(n):
        return dict(requires=[f'r{i}' for i in range(n)], provides=[], priority=0, check={})
    with contextlib.closing(db.connect('owner')) as conn:
        assert query(conn, 'SELECT v24_cordis.manifest_shape_valid(%s,%s)',
                     (Json(manifest(256)), Json({})))[0][0] is True
        assert query(conn, 'SELECT v24_cordis.manifest_shape_valid(%s,%s)',
                     (Json(manifest(257)), Json({})))[0][0] is False
    keys = [f'req-{i:03d}' for i in range(224)]
    root = active_owner(db)
    for start in range(0, len(keys), 32):
        chunk = keys[start:start + 32]
        payload = install_payload(mode='existing', existing_scope=root['scope'],
                                  owner=dict(fiber_id=str(root['fiber']),
                                             episode_id=str(root['episode'])))
        payload['manifest'] = dict(
            requires=[],
            provides=[dict(key=key, descriptor={'capability': 'cap'}, contract_version='1')
                      for key in chunk],
            priority=0, check={})
        payload['contracts'] = {'cap': dict(contract_version='1', handler_digest='a' * 64,
                                           replay=dict(repeat=True, concurrent=True))}
        _, result, _ = commit_new(db, 'command_install', payload)
        assert result.get('disposition') == 'committed', result
        phases(db, uuid.UUID(payload['fiber_id']), len(chunk))
    provider(db, 'model_call', 'model')
    tool_keys = [f'tool-{i:02d}' for i in range(31)]
    for key in tool_keys:
        provider(db, 'tool_call', key)
    # Shape-legal 256-entry manifest. It cannot activate: reconcile_command_seed expands each
    # resolved require to contribution+fiber+episode (224*3) before the 32 model/tool bindings.
    payload = install_payload(mode='existing', existing_scope=root['scope'],
                              owner=dict(fiber_id=str(root['fiber']), episode_id=str(root['episode'])))
    payload['manifest'] = dict(requires=keys + ['model'] + tool_keys, provides=[],
                               priority=0, check={})
    payload['contracts'] = {'run_start': dict(
        contract_version='1', handler_digest='c' * 64,
        replay=dict(repeat=True, concurrent=True))}
    payload['policy_ref'] = 'chat_tool'
    _, installed, _ = commit_new(db, 'command_install', payload)
    assert installed.get('disposition') == 'committed', installed
    fiber = uuid.UUID(payload['fiber_id'])
    _, blocked, _ = commit_new(db, 'command_reconcile', reconcile_payload(fiber, 'on', 0))
    assert blocked['error']['code'] == 'retry_with_closure', blocked
    assert q1(db, 'SELECT count(*) FROM v24_cordis.runs') == 0
    print(f'[CDP4-B5a] manifest 256 accepted/257 rejected; the 224+32 production activation is '
          f'retry_with_closure before any run (seed cap 512); shape-legal is not executable')

    # Owner fixture: 288 committed_view entries, created at episode birth (immutable afterwards).
    # This is NOT a legal manifest: 288 > the 256 requires cap. It only stresses run_bindings.
    y = prepare_run(db, 3, tuple(f'stress-{i}' for i in range(31)), model_key='stressmodel')
    pins = rows(db, "SELECT p.key,p.contribution_id,c.descriptor FROM v24_cordis.pins p "
                    "JOIN v24_cordis.contributions c ON c.id=p.contribution_id "
                    "WHERE p.consumer_run_id=%s", (y['run_id'],))
    def _dg(descriptor):
        return q1(db, "SELECT encode(sha256(convert_to(%s::jsonb::text,'UTF8')),'hex')",
                  (Json(descriptor),))
    view = {key: {'contribution_id': str(cid), 'contract_version': '1',
                  'descriptor_digest': _dg(descriptor)} for key, cid, descriptor in pins}
    stress_digest = _dg({'capability': 'cap'})
    fixture = seed_fiber(db)
    scope, install, fiber = fixture['scope'], fixture['install'], fixture['fiber']
    episode = uuid.uuid4()
    stress_ids = [uuid.uuid4() for _ in range(256)]
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        for i, cid in enumerate(stress_ids):
            view[f'unrelated-{i}'] = {'contribution_id': str(cid), 'contract_version': '1',
                                      'descriptor_digest': stress_digest}
        query(conn, "INSERT INTO v24_cordis.episodes(id,fiber_id,epoch,state,committed_view,iterator) "
                    "VALUES(%s,%s,1,'reloading',%s,%s)",
              (episode, fiber, Json(view), Json({'v': 1, 'next_index': 0,
               'registered_through': -1, 'control_seq': 1})))
        for i, cid in enumerate(stress_ids):
            query(conn, """INSERT INTO v24_cordis.contributions(id,fiber_id,episode_id,seq,kind,key,
                        descriptor,inverse,contract_version) VALUES(%s,%s,%s,%s,'service',%s,
                        %s,'{\"op\":\"delete_row\"}','1')""",
                  (cid, fiber, episode, i, f'unrelated-{i}', Json({'capability': 'cap'})))
        query(conn, 'UPDATE v24_cordis.fibers SET current_episode_id=%s WHERE id=%s', (episode, fiber))
        conn.commit()
    assert q1(db, 'SELECT count(*) FROM jsonb_object_keys((SELECT committed_view '
                  'FROM v24_cordis.episodes WHERE id=%s))', (episode,)) == 288
    bindings = q1(db, 'SELECT v24_cordis.run_bindings(%s)', (episode,))
    assert len(bindings) == 32, len(bindings)
    assert {b['capability'] for b in bindings} == {'model_call', 'tool_call'}
    # Owner fixture, not production: a ready run_start effect over the same 288-entry episode
    # proves settlement_seed expands only the 32 bindings and discover_closure stays under 512.
    effect = uuid.uuid4()
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        query(conn, "INSERT INTO v24_cordis.effects(id,kind,status,fiber_id,episode_id,input,"
                    "request_actor) VALUES(%s,'run_start','ready',%s,%s,%s,%s)",
              (effect, fiber, episode, Json({'v': 1, 'fiber_id': str(fiber),
               'episode_id': str(episode), 'contract': {'contract_version': '1',
               'handler_digest': 'c' * 64}}), db.roles['service']))
        conn.commit()
    seed = q1(db, 'SELECT v24_cordis.settlement_seed(%s)', (effect,))
    assert seed is not None and len(seed) == 97, len(seed)
    closure = q1(db, 'SELECT v24_cordis.discover_closure(%s)', (Json(seed),))
    assert closure is not None and len(seed) <= len(closure) < 512, closure
    with contextlib.closing(db.connect('owner')) as conn:
        assert query(conn, 'SELECT v24_cordis.manifest_shape_valid(%s,%s)',
                     (Json(dict(requires=[f'u{i}' for i in range(288)], provides=[],
                                priority=0, check={})), Json({})))[0][0] is False
    print(f'[CDP4-B5b] owner-injected 288-entry committed_view fixture filters to 32 run bindings; '
          f'run_start seed={len(seed)} and closure={len(closure)} (<512); '
          f'288 requires is rejected as an illegal manifest')


def test_b6_frozen(db):
    for name, want in FROZEN.items():
        got = hashlib.sha256((ROOT / 'v24' / 'sql' / name).read_bytes()).hexdigest()
        assert got == want, (name, got)
    assert subprocess.run(['git', 'diff', '--check'], cwd=ROOT).returncode == 0
    assert subprocess.run(['git', 'diff', '--exit-code', '17c855d', '--', 'v24/load.py'],
                          cwd=ROOT).returncode == 0
    assert subprocess.run(['git', 'diff', '--exit-code', '57e2c1e', '--'] +
                          [f'v24/sql/{name}' for name in FROZEN],
                          cwd=ROOT).returncode == 0
    print('[CDP4-B6] twelve frozen v24/sql hashes, load.py since B0, DP2-frozen diff and '
          'git diff --check are unchanged')


def main():
    with Server() as server:
        with TestDB(server) as db:
            test_b1_b2_layout(db)
        with TestDB(server) as db, TestDB(server) as other:
            test_b3_acl(db, other)
        with TestDB(server) as db:
            test_b4_surface(db)
        with TestDB(server) as db:
            test_b5_limits(db)
        with TestDB(server) as db:
            test_b5_manifest(db)
        with TestDB(server) as db:
            test_b6_frozen(db)
    print('[passed] CDP4-B')


if __name__ == '__main__':
    main()
