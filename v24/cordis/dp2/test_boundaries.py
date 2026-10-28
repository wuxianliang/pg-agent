"""CDP2-B: basic dispose and DP2 failure boundaries.

Run with: uv run python v24/cordis/dp2/test_boundaries.py
Clean dispose uses a real direct child install. Obligation rows are owner DML.
Success activation evidence is not claimed from those rows.
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
                          dispose_payload, sqlstate, install_probe, set_probe, replace_function,
                          function_defs, assert_helper_budget)
from test_activation import (install, phases, one, rows, expect_raise, child_call, reconcile_payload,
                                declaration, commit_new, p0)


def dispose(db, install_id):
    with contextlib.closing(db.connect('service')) as conn:
        effect, outcome = command(db, conn, 'service', 'command_dispose', dispose_payload(install_id))
        result = api(conn, effect, outcome)
        conn.commit()
    return effect, result, outcome


def dispose_attempt(db, install_id):
    """One staged dispose request: a deferred response or an unsupported 0A000."""
    with contextlib.closing(db.connect('service')) as conn:
        effect, outcome = command(db, conn, 'service', 'command_dispose', dispose_payload(install_id))
        try:
            result = api(conn, effect, outcome)
        except psycopg2.Error as exc:
            conn.rollback()
            assert exc.pgcode == '0A000', (exc.pgcode, str(exc))
            return dict(error=dict(code='0A000'))
        conn.commit()
    return result


def drive_dispose(db, install_id, limit=12):
    """Fresh same-LOGIN requests: seal, one bounded step each, then the final tombstone."""
    last = None
    for _ in range(limit):
        effect, result, outcome = dispose(db, install_id)
        assert result.get('disposition') == 'committed', result
        last = (effect, result, outcome)
        if one(db, 'SELECT state FROM v24_cordis.installs WHERE id=%s', (install_id,)) == 'disposed':
            return last
    raise AssertionError('dispose did not converge')


def assert_not_tombstoned(db, install_id):
    assert one(db, 'SELECT state FROM v24_cordis.installs WHERE id=%s', (install_id,)) != 'disposed'
    assert one(db, 'SELECT count(*) FROM v24_cordis.fibers WHERE install_id=%s AND disposed_at IS NOT NULL',
               (install_id,)) == 0


def refuse(db, install_id):
    """Seal once, then prove the obligation prevents the next step from tombstoning."""
    dispose(db, install_id)
    result = dispose_attempt(db, install_id)
    assert result.get('disposition') in ('committed', 'deferred') or result.get('error', {}).get('code') == '0A000', result
    assert one(db, 'SELECT state FROM v24_cordis.installs WHERE id=%s', (install_id,)) == 'dispose_pending'
    assert one(db, 'SELECT count(*) FROM v24_cordis.fibers WHERE install_id=%s AND disposed_at IS NOT NULL',
               (install_id,)) == 0


def owner_pair(db, root):
    episode = one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s', (root['fiber_id'],))
    return dict(fiber_id=root['fiber_id'], episode_id=str(episode)), root['scope']['id']


def child_install(db, owner, scope):
    payload, _, _ = install(db, owner=owner, mode='existing', existing=scope)
    return payload


def dml(db, statements):
    with contextlib.closing(db.connect('owner')) as conn:
        query(conn, 'SELECT pg_advisory_xact_lock(24,1)')
        for statement, params in statements:
            query(conn, statement, params)
        conn.commit()


def test_clean_dispose(db):
    root_payload, _, _ = install(db)
    root_fiber = uuid.UUID(root_payload['fiber_id'])
    phases(db, root_fiber, 0)
    owner, scope = owner_pair(db, root_payload)
    child = child_install(db, owner, scope)
    before_owner = one(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id=%s AND kind=%s',
                       (root_fiber, 'child'))
    effect, result, outcome = drive_dispose(db, child['install_id'])
    assert one(db, 'SELECT state FROM v24_cordis.installs WHERE id=%s', (child['install_id'],)) == 'disposed'
    assert one(db, 'SELECT disposed_at IS NOT NULL AND dispose_requested_at IS NOT NULL AND NOT want_on '
                   'FROM v24_cordis.fibers WHERE id=%s', (child['fiber_id'],)) is True
    assert one(db, 'SELECT closed_at IS NULL FROM v24_cordis.scopes WHERE id=%s', (scope,)) is True
    assert one(db, 'SELECT count(*) FROM v24_cordis.episodes WHERE fiber_id=%s', (child['fiber_id'],)) == 0
    assert one(db, "SELECT count(*) FROM v24_cordis.effects WHERE kind='host_io' AND fiber_id=%s",
               (child['fiber_id'],)) == 0
    assert one(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id=%s AND kind=%s',
               (root_fiber, 'child')) == before_owner
    assert one(db, 'SELECT released_at IS NULL AND withdrawn_at IS NULL FROM v24_cordis.contributions '
                   'WHERE fiber_id=%s AND kind=%s AND descriptor->>%s=%s',
               (root_fiber, 'child', 'child_fiber_id', child['fiber_id'])) is True
    event = rows(db, "SELECT event_kind,payload->>'phase' FROM v24_cordis.events "
                     "WHERE entity_id=%s AND event_kind=%s ORDER BY seq",
                 (child['install_id'], 'install_dispose_progress'))
    assert event == [('install_dispose_progress', 'requested'),
                     ('install_dispose_progress', 'fiber_disposed'),
                     ('install_dispose_progress', 'completed')], event
    with contextlib.closing(db.connect('service')) as conn:
        replay = api(conn, effect, outcome)
        conn.commit()
    assert replay == result
    with contextlib.closing(db.connect('service')) as conn:
        effect2, out2 = command(db, conn, 'service', 'command_dispose', dispose_payload(child['install_id']))
        no_write(db, conn, effect2, out2, 'already_terminal')
    print('[CDP2-B2/B3] clean child dispose is sealed, bounded, keeps history, replays exact, then already_terminal')
    return root_payload, owner, scope


def test_obligations(db, owner, scope):
    cases = []
    child = child_install(db, owner, scope)
    dml(db, [('UPDATE v24_cordis.fibers SET want_on=true WHERE id=%s', (child['fiber_id'],))])
    refuse(db, child['install_id'])
    cases.append('want_on')
    child = child_install(db, owner, scope)
    episode = uuid.uuid4()
    dml(db, [("INSERT INTO v24_cordis.episodes(id,fiber_id,epoch,state,committed_view,iterator) "
              "VALUES(%s,%s,1,'reloading','{}','{\"v\":1,\"next_index\":0,\"registered_through\":-1,\"control_seq\":0}')",
              (episode, child['fiber_id']))])
    refuse(db, child['install_id'])
    cases.append('open_episode')
    child = child_install(db, owner, scope)
    episode = uuid.uuid4()
    dml(db, [("INSERT INTO v24_cordis.episodes(id,fiber_id,epoch,state,committed_view,iterator,closed_at) "
              "VALUES(%s,%s,1,'active','{}','{\"v\":1,\"next_index\":0,\"registered_through\":-1,\"control_seq\":0}',now())",
              (episode, child['fiber_id'])),
             ("INSERT INTO v24_cordis.contributions(id,fiber_id,episode_id,seq,kind,realm,key,descriptor,inverse,"
              "contract_version) VALUES(%s,%s,%s,0,'service','root','held','{}','{\"op\":\"delete_row\"}','1')",
              (uuid.uuid4(), child['fiber_id'], episode))])
    refuse(db, child['install_id'])
    cases.append('contribution')
    child = child_install(db, owner, scope)
    episode = uuid.uuid4()
    root_contrib, root_epoch = rows(db, 'SELECT c.id,e.epoch FROM v24_cordis.contributions c '
                                        'JOIN v24_cordis.episodes e ON e.id=c.episode_id '
                                        'WHERE c.fiber_id=%s LIMIT 1', (owner['fiber_id'],))[0]
    dml(db, [("INSERT INTO v24_cordis.episodes(id,fiber_id,epoch,state,committed_view,iterator,closed_at) "
              "VALUES(%s,%s,1,'active','{}','{\"v\":1,\"next_index\":0,\"registered_through\":-1,\"control_seq\":0}',now())",
              (episode, child['fiber_id'])),
             ("INSERT INTO v24_cordis.pins(id,consumer_fiber_id,consumer_episode_id,key,contribution_id,provider_epoch) "
              "VALUES(%s,%s,%s,'gone',%s,%s)",
              (uuid.uuid4(), child['fiber_id'], episode, root_contrib, root_epoch))])
    refuse(db, child['install_id'])
    cases.append('pin')
    child = child_install(db, owner, scope)
    episode = uuid.uuid4()
    dml(db, [("INSERT INTO v24_cordis.episodes(id,fiber_id,epoch,state,committed_view,iterator,closed_at) "
              "VALUES(%s,%s,1,'active','{}','{\"v\":1,\"next_index\":0,\"registered_through\":-1,\"control_seq\":0}',now())",
              (episode, child['fiber_id'])),
             ("INSERT INTO v24_cordis.runs(id,owner_fiber_id,owner_episode_id,scope_id,remaining_steps) "
              "VALUES(%s,%s,%s,%s,1)",
              (uuid.uuid4(), child['fiber_id'], episode, scope))])
    refuse(db, child['install_id'])
    cases.append('run')
    child = child_install(db, owner, scope)
    episode = uuid.uuid4()
    owned = uuid.uuid4()
    owned_fiber = uuid.uuid4()
    owned_episode = uuid.uuid4()
    dml(db, [("INSERT INTO v24_cordis.episodes(id,fiber_id,epoch,state,committed_view,iterator,closed_at) "
              "VALUES(%s,%s,1,'active','{}','{\"v\":1,\"next_index\":0,\"registered_through\":-1,\"control_seq\":0}',now())",
              (episode, child['fiber_id'])),
             ("INSERT INTO v24_cordis.installs(id,scope_id,owner_fiber_id,owner_episode_id,identity,version,"
              "manifest,artifact_digest,contracts,state) VALUES(%s,%s,%s,%s,%s,'1',%s,%s,'{}','installed')",
              (owned, scope, child['fiber_id'], episode, 'owned-' + owned.hex[:8],
               Json(dict(requires=[], provides=[], priority=0, check={})), 'a' * 64)),
             ("INSERT INTO v24_cordis.fibers(id,install_id,owner_id,owner_episode_id,scope_id,current_episode_id) "
              "VALUES(%s,%s,%s,%s,%s,%s)",
              (owned_fiber, owned, child['fiber_id'], episode, scope, owned_episode)),
             ("INSERT INTO v24_cordis.episodes(id,fiber_id,epoch,state,committed_view,iterator) "
              "VALUES(%s,%s,1,'reloading','{}','{\"v\":1,\"next_index\":0,\"registered_through\":-1,\"control_seq\":0}')",
              (owned_episode, owned_fiber))])
    refuse(db, child['install_id'])
    cases.append('child_install')
    for kind in ('dispatch', 'listener_call', 'model_call', 'tool_call', 'run_start', 'command_reconcile'):
        child = child_install(db, owner, scope)
        dml(db, [("INSERT INTO v24_cordis.effects(id,fiber_id,kind,status,input,request_actor) "
                  "VALUES(%s,%s,%s,'ready','{}','seed')",
                  (uuid.uuid4(), child['fiber_id'], kind))])
        refuse(db, child['install_id'])
        child = child_install(db, owner, scope)
        dml(db, [("INSERT INTO v24_cordis.effects(id,fiber_id,kind,status,input,request_actor,claim_owner,lease_until) "
                  "VALUES(%s,%s,%s,'claimed','{}','seed','seed',now()+interval '1 minute')",
                  (uuid.uuid4(), child['fiber_id'], kind))])
        refuse(db, child['install_id'])
    cases.append('live_effects')
    for status, extra in (
            ('ready', ""),
            ('claimed', ",claim_owner,lease_until"),
            ('unknown', ",outcome,settled_at"),
            ('succeeded', ",outcome,settled_at"),
            ('failed', ",outcome,settled_at"),
            ('cancelled', ",settled_at")):
        child = child_install(db, owner, scope)
        if status == 'ready':
            sql = ("INSERT INTO v24_cordis.effects(id,fiber_id,kind,status,input,request_actor) "
                   "VALUES(%s,%s,'host_io','ready','{}','seed')")
            params = (uuid.uuid4(), child['fiber_id'])
        elif status == 'claimed':
            sql = ("INSERT INTO v24_cordis.effects(id,fiber_id,kind,status,input,request_actor,claim_owner,lease_until) "
                   "VALUES(%s,%s,'host_io','claimed','{}','seed','seed',now()+interval '1 minute')")
            params = (uuid.uuid4(), child['fiber_id'])
        elif status == 'cancelled':
            sql = ("INSERT INTO v24_cordis.effects(id,fiber_id,kind,status,input,request_actor,settled_at) "
                   "VALUES(%s,%s,'host_io','cancelled','{}','seed',now())")
            params = (uuid.uuid4(), child['fiber_id'])
        else:
            sql = ("INSERT INTO v24_cordis.effects(id,fiber_id,kind,status,input,request_actor,outcome,settled_at) "
                   "VALUES(%s,%s,'host_io',%s,'{}','seed','{}',now())")
            params = (uuid.uuid4(), child['fiber_id'], status)
        dml(db, [(sql, params)])
        refuse(db, child['install_id'])
    cases.append('host_io')
    print('[CDP2-B2/B5] each obligation and six host statuses block tombstone:', ','.join(cases))


def test_multi_and_bounds(db, owner, scope):
    child = child_install(db, owner, scope)
    second = uuid.uuid4()
    dml(db, [('INSERT INTO v24_cordis.fibers(id,install_id,owner_id,owner_episode_id,scope_id) '
              'VALUES(%s,%s,%s,%s,%s)',
              (second, child['install_id'], owner['fiber_id'], owner['episode_id'], scope))])
    dml(db, [('UPDATE v24_cordis.fibers SET want_on=true WHERE id=%s', (second,))])
    effect, result, _ = drive_dispose(db, child['install_id'])
    assert result['disposition'] == 'committed', result
    ids = sorted([child['fiber_id'], str(second)])
    assert one(db, 'SELECT count(*) FROM v24_cordis.fibers WHERE install_id=%s AND disposed_at IS NOT NULL',
               (child['install_id'],)) == 2
    payload = rows(db, "SELECT payload FROM v24_cordis.events WHERE entity_id=%s "
                       "AND event_kind='install_dispose_progress' AND payload->>'phase'='fiber_disposed' "
                       "ORDER BY seq", (child['install_id'],))
    disposed_ids = sorted(p['fiber_id'] for p, in payload)
    assert disposed_ids == ids, payload
    root = Path(__file__).resolve().parents[1]
    sql_files = sorted(p.name for p in (root / 'sql').glob('*.sql'))
    assert len(sql_files) == 18, sql_files
    total, counts = assert_helper_budget(root / 'sql')
    prefix = sum(len((root / 'sql' / name).read_text().splitlines()) for name in (
        '10_installs.sql', '11_scopes.sql', '12_fibers.sql', '13_episodes.sql', '14_contributions.sql',
        '15_pins.sql', '16_runs.sql', '17_effects.sql', '20_relations.sql', '30_triggers.sql'))
    assert prefix <= 900, prefix
    assert one(db, "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                   "WHERE n.nspname='v24_cordis' AND c.relkind='r'") == 10
    assert one(db, "SELECT count(*) FROM pg_proc WHERE pronamespace='v24_cordis'::regnamespace AND prosecdef") == 1
    print(f'[CDP2-B4/B5] multi-fiber dispose; tables=10 manifest=18 helpers={total} '
          f'40={counts["40_advance.sql"]} 41={counts["41_lifecycle.sql"]} '
          f'42={counts["42_teardown.sql"]} 43={counts["43_loop.sql"]} ddl={prefix}')


def test_w2_classification(db, owner, scope):
    missing = child_install(db, owner, scope)
    missing['manifest'] = dict(requires=['absent'], provides=[], priority=0, check={})
    # Real missing dependency: install a consumer and execute its P1 child.
    consumer, _, _ = install(db, requires=['absent'], owner=owner, mode='existing', existing=scope)
    parent, started, _ = __import__('test_activation', fromlist=['p0']).p0(db, uuid.UUID(consumer['fiber_id']))
    effect, outcome = child_call(db, parent, reconcile_payload(uuid.UUID(consumer['fiber_id']), 'advance', 1))
    with contextlib.closing(db.connect('service')) as conn:
        no_write(db, conn, effect, outcome, 'dependency_unresolved')
    assert one(db, 'SELECT current_episode_id FROM v24_cordis.fibers WHERE id=%s',
               (consumer['fiber_id'],)) is None
    checked = declaration(provides=['checked'], owner=owner, mode='existing', existing=scope)
    _, result, _ = commit_new(db, 'command_install', checked)
    assert result['disposition'] == 'committed', result
    phases(db, uuid.UUID(checked['fiber_id']), 1)
    bad_check = declaration(requires=['checked'], owner=owner, mode='existing', existing=scope,
                            check={'checked': dict(v=1, op='equals', path=['flag'], value=True)})
    _, result, _ = commit_new(db, 'command_install', bad_check)
    parent, _, _ = p0(db, uuid.UUID(bad_check['fiber_id']))
    effect, outcome = child_call(db, parent, reconcile_payload(uuid.UUID(bad_check['fiber_id']), 'advance', 1))
    expect_raise(db, effect, outcome)
    first = declaration(provides=['clash'], owner=owner, mode='existing', existing=scope)
    _, result, _ = commit_new(db, 'command_install', first)
    phases(db, uuid.UUID(first['fiber_id']), 1)
    second = declaration(provides=['clash'], owner=owner, mode='existing', existing=scope)
    _, result, _ = commit_new(db, 'command_install', second)
    parent, _, _ = p0(db, uuid.UUID(second['fiber_id']))
    begun, begun_result = child_call(db, parent, reconcile_payload(uuid.UUID(second['fiber_id']), 'advance', 1))
    with contextlib.closing(db.connect('service')) as conn:
        got = api(conn, begun, begun_result)
        conn.commit()
    assert got['disposition'] == 'committed', got
    effect, outcome = child_call(db, begun, reconcile_payload(uuid.UUID(second['fiber_id']), 'advance', 1))
    with contextlib.closing(db.connect('service')) as conn:
        assert api(conn, effect, outcome)['disposition'] == 'committed'
        conn.commit()
    assert one(db, "SELECT e.state='closing' AND e.outcome='error' AND f.failure->>'phase'='p2' "
                   "AND f.failure->>'key'='clash' FROM v24_cordis.fibers f "
                   "JOIN v24_cordis.episodes e ON e.id=f.current_episode_id WHERE f.id=%s",
               (second['fiber_id'],)) is True
    assert one(db, 'SELECT count(*) FROM v24_cordis.contributions WHERE fiber_id=%s AND kind=%s',
               (second['fiber_id'], 'service')) == 0
    drifted = declaration(provides=['drifted'], owner=owner, mode='existing', existing=scope)
    _, result, _ = commit_new(db, 'command_install', drifted)
    parent, _, _ = p0(db, uuid.UUID(drifted['fiber_id']))
    begun, _ = child_call(db, parent, reconcile_payload(uuid.UUID(drifted['fiber_id']), 'advance', 1))
    with contextlib.closing(db.connect('service')) as conn:
        api(conn, begun, _)
        conn.commit()
    dml(db, [('UPDATE v24_cordis.fibers SET control_seq=control_seq+1 WHERE id=%s', (drifted['fiber_id'],))])
    effect, outcome = child_call(db, begun, reconcile_payload(uuid.UUID(drifted['fiber_id']), 'advance', 1))
    with contextlib.closing(db.connect('service')) as conn:
        assert api(conn, effect, outcome)['disposition'] == 'committed'
        conn.commit()
    assert one(db, "SELECT e.state='closing' AND e.outcome='divert' AND f.failure IS NULL "
                   "FROM v24_cordis.fibers f JOIN v24_cordis.episodes e ON e.id=f.current_episode_id "
                   "WHERE f.id=%s", (drifted['fiber_id'],)) is True
    assert one(db, "SELECT (iterator->>'next_index')::int FROM v24_cordis.episodes e "
                   "JOIN v24_cordis.fibers f ON f.current_episode_id=e.id WHERE f.id=%s",
               (drifted['fiber_id'],)) == 0
    print('[CDP2-B1] missing P1 dependency zero-write; P1 check stays unsupported; P2 conflict Raises; drift Diverts')


def main():
    with Server() as server, TestDB(server) as db:
        root, owner, scope = test_clean_dispose(db)
        test_obligations(db, owner, scope)
        test_multi_and_bounds(db, owner, scope)
        test_w2_classification(db, owner, scope)
    print('[passed] CDP2-B')


if __name__ == '__main__':
    main()
