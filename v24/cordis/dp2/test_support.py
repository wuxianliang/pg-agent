"""DP2 W1 disposable fixtures and protocol calls.

The database/role lifecycle and the ten-table snapshot are the existing DP1 fixture APIs:
this module deliberately imports them instead of copying a loader or fixture.
"""
from __future__ import annotations
import base64
import contextlib
import hashlib
import json
from pathlib import Path
import sys
import uuid

DP1 = Path(__file__).resolve().parents[1] / 'dp1'
sys.path.insert(0, str(DP1))
from setup_db import Server, TestDB, TABLES  # noqa: E402
from test_ddl import snapshot  # noqa: E402
import psycopg2  # noqa: E402
from psycopg2 import sql  # noqa: E402
from psycopg2.extras import Json, register_uuid  # noqa: E402

register_uuid()
ERRORS = ('invalid_args unauthorized not_found_or_denied request_conflict effect_id_conflict '
          'receipt_conflict stale_generation registration_stale already_terminal owner_closing '
          'install_not_ready interaction_mismatch provider_unavailable scope_closed '
          'dependency_unresolved provide_conflict install_identity_conflict budget_exceeded '
          'invalid_outcome stale_claim cleanup_cycle retry_with_closure blocked_unknown '
          'spawn_key_conflict').split()


def query(conn, statement, params=()):
    with conn.cursor() as c:
        c.execute(statement, params) if params else c.execute(statement)
        return c.fetchall() if c.description else None


def api(conn, effect, outcome):
    return query(conn, 'SELECT v24_cordis.advance(%s,%s)', (effect, Json(outcome)))[0][0]


def env(cls, body=None, claim=None, **extra):
    return dict(v=1, **{'class': cls}, claim=claim, body={} if body is None else body, **extra)


def principal(login):
    return uuid.UUID(hashlib.md5(login.encode()).hexdigest())


def derive(login, key, kind):
    digest = hashlib.sha256(f'{principal(login)}:{kind}:{key}'.encode()).hexdigest()
    return uuid.UUID(digest[:32])


def successor_key(parent, ordinal=0):
    return f'cordis/reconcile/{parent}/{ordinal}'


def canonical(conn, payload):
    return query(conn, 'SELECT %s::jsonb::text', (Json(payload),))[0][0]


def command(db, conn, alias, kind, payload, key=None, effect=None):
    key = key or uuid.uuid4().hex
    text = canonical(conn, payload)
    effect = effect or derive(db.roles[alias], key, kind)
    body = dict(op='admit_and_apply', kind=kind, request_key=key,
                canonical_bytes=base64.b64encode(text.encode()).decode(), payload=payload)
    return effect, env('command', body)


def install_payload(mode='root', owner=None, existing_scope=None):
    scope, install, fiber = (uuid.uuid4() for _ in range(3))
    if mode == 'existing':
        scope = existing_scope
        scope_value = dict(mode='existing', id=str(scope))
    else:
        scope_value = dict(mode='root', id=str(scope), realm_overrides={})
    return dict(scope=scope_value, owner=owner, install_id=str(install), fiber_id=str(fiber),
                identity='dp2-' + install.hex[:8], version='1',
                manifest=dict(requires=[], provides=[], priority=0, check={}),
                artifact_digest='a' * 64, contracts={}, policy_ref=None, overlay={})


def reconcile_payload(fiber, action='on', expected=0):
    return dict(fiber_id=str(fiber), action=action, expected_control_seq=expected)


def dispose_payload(install):
    return dict(install_id=str(install))


def sqlstate(conn, statement, params=(), code='0A000'):
    try:
        query(conn, statement, params)
    except psycopg2.Error as exc:
        conn.rollback()
        assert exc.pgcode == code, (exc.pgcode, str(exc))
    else:
        conn.rollback()
        raise AssertionError('expected SQLSTATE ' + code)


def no_write(db, conn, effect, outcome, code=None, disposition=None, detail=None, count=None):
    with contextlib.closing(db.connect('owner')) as owner:
        before = snapshot(owner)
        owner.rollback()
        result = api(conn, effect, outcome)
        if code:
            assert result.get('error', {}).get('code') == code, result
        if disposition:
            assert result.get('disposition') == disposition, result
        if detail is not None:
            assert result['error']['detail'] == detail, result
        conn.commit()
        after = snapshot(owner)
        assert after == before, (result, 'changed rows')
    if count is not None:
        count.append(result)
    return result


def function_defs(db):
    with contextlib.closing(db.connect('owner')) as owner:
        return dict(query(owner, "SELECT proname,pg_get_functiondef(oid) FROM pg_proc "
                                "WHERE pronamespace='v24_cordis'::regnamespace"))


def replace_function(db, definition):
    with contextlib.closing(db.connect('owner')) as owner:
        query(owner, sql.SQL('SET ROLE {}').format(sql.Identifier(db.groups['owner'])))
        query(owner, definition)
        owner.commit()


PROBE = '''CREATE OR REPLACE FUNCTION v24_cordis.interpret_command(
 p_effect_id uuid,p_principal uuid,p_outcome jsonb,p_closure jsonb) RETURNS jsonb
LANGUAGE plpgsql SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
BEGIN
 IF current_setting('cordis_probe.raise',true)='1' THEN
  RAISE EXCEPTION 'W1 probe interpreter is unavailable' USING ERRCODE='0A000';
 END IF;
 RETURN current_setting('cordis_probe.delta',true)::jsonb;
END $$;'''


def install_probe(db):
    original = function_defs(db)
    replace_function(db, PROBE)
    assert function_defs(db)['validate_and_apply_delta'] == original['validate_and_apply_delta']
    return original


def set_probe(conn, delta):
    query(conn, 'SELECT set_config(%s,%s,false)', ('cordis_probe.delta', json.dumps(delta)))


def set_probe_raise(conn, active=True):
    query(conn, 'SELECT set_config(%s,%s,false)', ('cordis_probe.raise', '1' if active else '0'))


def delta(domain=(), receipt='succeeded', events=(), successors=()):
    return dict(domain=list(domain), receipt=dict(status=receipt), events=list(events),
                successors=list(successors))


def successor(parent_fiber, expected, ordinal=0):
    return dict(ordinal=ordinal, kind='command_reconcile',
                input=dict(fiber_id=str(parent_fiber), action='advance', expected_control_seq=expected))


def event(entity_type, entity_id, kind, payload):
    return dict(entity_type=entity_type, entity_id=str(entity_id), event_kind=kind, payload=payload)


def active_owner(db, prefix='root'):
    """One spec-valid ownerless root per database; W2 fixtures attach child resources to it."""
    with contextlib.closing(db.connect('owner')) as owner:
        query(owner, 'SELECT pg_advisory_xact_lock(24,1)')
        row = query(owner, 'SELECT id,install_id,scope_id,current_episode_id,want_on '
                           'FROM v24_cordis.fibers WHERE owner_id IS NULL LIMIT 1')
        if row:
            fiber, install, scope, episode, want_on = row[0]
            if episode is None:
                episode = uuid.uuid4()
                query(owner, 'INSERT INTO v24_cordis.episodes(id,fiber_id,epoch,state,'
                             'committed_view,iterator) SELECT %s,%s,coalesce(max(epoch),-1)+1,'
                             "'active','{}',%s FROM v24_cordis.episodes WHERE fiber_id=%s",
                      (episode, fiber, Json(dict(v=1, next_index=0, registered_through=-1,
                                                 control_seq=0)), fiber))
                query(owner, 'UPDATE v24_cordis.fibers SET current_episode_id=%s WHERE id=%s',
                      (episode, fiber))
            if not want_on:
                query(owner, 'UPDATE v24_cordis.fibers SET want_on=true WHERE id=%s', (fiber,))
            owner.commit()
            return dict(fiber=fiber, install=install, scope=scope, episode=episode)
        scope, install, fiber, episode = (uuid.uuid4() for _ in range(4))
        query(owner, 'INSERT INTO v24_cordis.scopes(id) VALUES(%s)', (scope,))
        query(owner, "INSERT INTO v24_cordis.installs(id,scope_id,identity,version,manifest,"
                     "artifact_digest,contracts,state) VALUES(%s,%s,%s,'1',%s,%s,'{}','installed')",
              (install, scope, prefix + '-' + install.hex[:8],
               Json(dict(requires=[], provides=[], priority=0, check={})), 'a' * 64))
        query(owner, 'INSERT INTO v24_cordis.fibers(id,install_id,scope_id) VALUES(%s,%s,%s)',
              (fiber, install, scope))
        query(owner, "INSERT INTO v24_cordis.episodes(id,fiber_id,epoch,state,committed_view,"
                     "iterator) VALUES(%s,%s,0,'active','{}',%s)",
              (episode, fiber, Json(dict(v=1, next_index=0, registered_through=-1, control_seq=0))))
        query(owner, 'UPDATE v24_cordis.fibers SET current_episode_id=%s,want_on=true WHERE id=%s',
              (episode, fiber))
        owner.commit()
    return dict(fiber=fiber, install=install, scope=scope, episode=episode)


def install_delta(db, payload):
    scope = payload['scope']
    scope_created = scope['mode'] != 'existing'
    owner = payload['owner']
    domain = []
    if scope_created:
        domain.append(dict(op='scope_create', id=scope['id'],
                           parent_id=scope.get('parent_id'),
                           realm_overrides=scope.get('realm_overrides', {})))
    domain.append(dict(op='install_create', id=payload['install_id'], scope_id=scope['id'],
                       owner_fiber_id=(owner or {}).get('fiber_id'),
                       owner_episode_id=(owner or {}).get('episode_id'),
                       identity=payload['identity'], version=payload['version'],
                       manifest=payload['manifest'], artifact_digest=payload['artifact_digest'],
                       contracts=payload['contracts'], policy_ref=payload['policy_ref'],
                       overlay=payload['overlay']))
    domain.append(dict(op='fiber_create', id=payload['fiber_id'], install_id=payload['install_id'],
                       owner_id=(owner or {}).get('fiber_id'),
                       owner_episode_id=(owner or {}).get('episode_id'), scope_id=scope['id']))
    child = None
    if owner:
        with contextlib.closing(db.connect('owner')) as conn:
            next_index, registered = query(
                conn, "SELECT (iterator->>'next_index')::int,(iterator->>'registered_through')::int "
                      "FROM v24_cordis.episodes WHERE id=%s", (owner['episode_id'],))[0]
            seq = query(conn, 'SELECT coalesce(max(seq),-1)::bigint+1 FROM v24_cordis.contributions '
                              'WHERE fiber_id=%s AND episode_id=%s',
                        (owner['fiber_id'], owner['episode_id']))[0][0]
        child = uuid.uuid4()
        domain.append(dict(op='contribution_append', id=str(child),
                           fiber_id=owner['fiber_id'], episode_id=owner['episode_id'],
                           seq=int(seq), kind='child', realm=None, key=None,
                           descriptor=dict(child_fiber_id=payload['fiber_id']),
                           prev_contribution_id=None, inverse=dict(op='dispose_child'),
                           contract_version='1'))
        domain.append(dict(op='episode_progress', episode_id=owner['episode_id'],
                           next_index=next_index, registered_through=int(seq)))
    return delta(domain=domain, events=[event(
        'install', payload['install_id'], 'install_created',
        dict(scope_id=scope['id'], scope_created=scope_created, fiber_id=payload['fiber_id'],
             owner_fiber_id=(owner or {}).get('fiber_id'),
             owner_episode_id=(owner or {}).get('episode_id'),
             child_contribution_id=(str(child) if child else None)))])


def seed_fiber(db, provides=(), requires=(), want_on=False, control_seq=0, prefix='w1'):
    scope, install, fiber = (uuid.uuid4() for _ in range(3))
    root = active_owner(db)
    manifest = dict(requires=[dict(key=k, descriptor={}, contract_version='1') for k in requires],
                    provides=[dict(key=k, descriptor={}, contract_version='1') for k in provides],
                    priority=0, check={})
    with contextlib.closing(db.connect('owner')) as owner:
        query(owner, 'SELECT pg_advisory_xact_lock(24,1)')
        query(owner, 'INSERT INTO v24_cordis.scopes(id) VALUES(%s)', (scope,))
        query(owner, "INSERT INTO v24_cordis.installs(id,scope_id,owner_fiber_id,owner_episode_id,"
                     "identity,version,manifest,artifact_digest,contracts,state) "
                     "VALUES(%s,%s,%s,%s,%s,'1',%s,%s,'{}','installed')",
              (install, scope, root['fiber'], root['episode'], prefix + '-' + install.hex[:8],
               Json(manifest), 'a' * 64))
        query(owner, 'INSERT INTO v24_cordis.fibers(id,install_id,owner_id,owner_episode_id,'
                     'scope_id,want_on,control_seq) VALUES(%s,%s,%s,%s,%s,%s,%s)',
              (fiber, install, root['fiber'], root['episode'], scope, want_on, control_seq))
        owner.commit()
    return dict(scope=scope, install=install, fiber=fiber, manifest=manifest, root=root)


def seed_episode(db, fiber, epoch=1, state='reloading', next_index=0, registered=-1, control_seq=1,
                 committed_view=None, pins=()):
    episode = uuid.uuid4()
    iterator = dict(v=1, next_index=next_index, registered_through=registered, control_seq=control_seq)
    with contextlib.closing(db.connect('owner')) as owner:
        query(owner, 'SELECT pg_advisory_xact_lock(24,1)')
        query(owner, 'INSERT INTO v24_cordis.episodes(id,fiber_id,epoch,state,committed_view,iterator) '
                     'VALUES(%s,%s,%s,%s,%s,%s)', (episode, fiber, epoch, state,
                                                  Json(committed_view or {}), Json(iterator)))
        for item in pins:
            query(owner, 'INSERT INTO v24_cordis.pins(id,consumer_fiber_id,consumer_episode_id,key,'
                         'contribution_id,provider_epoch) VALUES(%s,%s,%s,%s,%s,%s)',
                  (uuid.uuid4(), fiber, episode, item['key'], item['contribution_id'], item['provider_epoch']))
        query(owner, 'UPDATE v24_cordis.fibers SET current_episode_id=%s WHERE id=%s', (episode, fiber))
        owner.commit()
    return episode


def descriptor_digest(db, descriptor):
    with contextlib.closing(db.connect('owner')) as owner:
        return query(owner, "SELECT encode(sha256(convert_to(%s::jsonb::text,'UTF8')),'hex')",
                     (Json(descriptor),))[0][0]


def seed_provider(db, realm='root', key='svc', epoch=1):
    fiber = seed_fiber(db, prefix='prov')
    episode = seed_episode(db, fiber['fiber'], epoch=epoch, state='active', control_seq=0)
    contribution = uuid.uuid4()
    descriptor = {'name': key}
    with contextlib.closing(db.connect('owner')) as owner:
        query(owner, 'SELECT pg_advisory_xact_lock(24,1)')
        query(owner, "INSERT INTO v24_cordis.contributions(id,fiber_id,episode_id,seq,kind,realm,key,"
                     "descriptor,inverse,contract_version) VALUES(%s,%s,%s,0,'service',%s,%s,%s,"
                     "'{\"op\":\"delete_row\"}','1')",
              (contribution, fiber['fiber'], episode, realm, key, Json(descriptor)))
        owner.commit()
    return dict(fiber=fiber['fiber'], episode=episode, contribution=contribution, epoch=epoch,
                descriptor=descriptor, realm=realm, key=key, digest=descriptor_digest(db, descriptor))


def seed_parent(db, kind, payload, actor='service', fiber=None, episode=None, key=None, status='succeeded'):
    key = key or uuid.uuid4().hex
    effect = derive(db.roles[actor], key, kind)
    body = dict(op='admit_and_apply', kind=kind, request_key=key,
                canonical_bytes=base64.b64encode(json.dumps(payload).encode()).decode(), payload=payload)
    with contextlib.closing(db.connect('owner')) as owner:
        query(owner, 'SELECT pg_advisory_xact_lock(24,1)')
        query(owner, "INSERT INTO v24_cordis.effects(id,kind,status,fiber_id,episode_id,input,"
                     "request_actor,outcome,settled_at) VALUES(%s,%s,%s,%s,%s,%s,%s,"
                     "CASE WHEN %s IN ('succeeded','failed','unknown') THEN %s::jsonb ELSE NULL END,"
                     "CASE WHEN %s IN ('succeeded','failed','unknown','cancelled') THEN now() ELSE NULL END)",
              (effect, kind, status, fiber, episode, Json(payload), db.roles[actor], status,
               Json(dict(v=1, **{'class': 'command'}, claim=None, body=body)), status))
        owner.commit()
    return effect, key


def seed_child(db, parent, fiber, payload, episode=None, ordinal=0, actor='service', status='ready',
               attempt=0, fence=0):
    key = successor_key(parent, ordinal)
    effect = derive(db.roles[actor], key, 'command_reconcile')
    with contextlib.closing(db.connect('owner')) as owner:
        query(owner, 'SELECT pg_advisory_xact_lock(24,1)')
        query(owner, "INSERT INTO v24_cordis.effects(id,parent_id,ordinal,fiber_id,episode_id,kind,"
                     "status,input,request_actor,attempt,fence) VALUES(%s,%s,%s,%s,%s,"
                     "'command_reconcile',%s,%s,%s,%s,%s)",
              (effect, parent, ordinal, fiber, episode, status, Json(payload), db.roles[actor],
               attempt, fence))
        owner.commit()
    return effect, key


def execute(db, effect, outcome, alias='service'):
    with contextlib.closing(db.connect(alias)) as conn:
        got = api(conn, effect, outcome)
        conn.commit()
    return got
