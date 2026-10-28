"""CDP1-K: protocol, real LOGIN ACL, ordered locking and durable receipt probes.
Only disposable probe interpreters/barrier are replaced; the applier is always production SQL.
The probe install path reuses the production typed install delta builder; W2 admission is CDP2-I.
"""
from __future__ import annotations
import base64
import contextlib
import hashlib
import json
from pathlib import Path
import sys
import threading
import time
import uuid
import psycopg2
from psycopg2 import sql
from psycopg2.extras import Json, register_uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from helper_budget import LIMIT, assert_helper_budget, prove_helper_budget_boundary
from load import CANONICAL_ORDER
from setup_db import Server, TestDB, TABLES
from test_ddl import snapshot
register_uuid()
ERRORS='invalid_args unauthorized not_found_or_denied request_conflict effect_id_conflict receipt_conflict stale_generation registration_stale already_terminal owner_closing install_not_ready interaction_mismatch provider_unavailable scope_closed dependency_unresolved provide_conflict install_identity_conflict budget_exceeded invalid_outcome stale_claim cleanup_cycle retry_with_closure blocked_unknown spawn_key_conflict'.split()
COUNT=0


def query(conn,statement,params=()):
    with conn.cursor() as c:
        c.execute(statement,params) if params else c.execute(statement)
        return c.fetchall() if c.description else None


def api(conn,effect,outcome):
    return query(conn,'SELECT v24_cordis.advance(%s,%s)',(effect,Json(outcome)))[0][0]


def env(cls,body=None,claim=None,**extra):
    return dict(v=1,**{'class':cls},claim=claim,body={} if body is None else body,**extra)


def install_payload():
    scope,install,fiber=(uuid.uuid4() for _ in range(3))
    return dict(scope=dict(mode='root',id=str(scope),realm_overrides={}),
                owner=None,install_id=str(install),fiber_id=str(fiber),identity='dp1-probe',version='1',
                manifest=dict(requires=[],provides=[],priority=0,check={}),
                artifact_digest='a'*64,contracts={},policy_ref=None,overlay={})


def command(db,alias='service',key=None,payload=None,kind='command_install'):
    key=key or uuid.uuid4().hex
    if payload is None:
        payload=install_payload() if kind=='command_install' else dict(install_id=str(uuid.uuid4()))
    principal=uuid.UUID(hashlib.md5(db.roles[alias].encode()).hexdigest())
    effect=uuid.UUID(hashlib.sha256(f'{principal}:{kind}:{key}'.encode()).hexdigest()[:32])
    # Obtain PostgreSQL canonical spelling; fixed vectors below independently freeze the protocol.
    with contextlib.closing(db.connect('owner')) as c:
        canonical=query(c,'SELECT %s::jsonb::text',(Json(payload),))[0][0]
    return effect,env('command',dict(op='admit_and_apply',kind=kind,request_key=key,
                                   canonical_bytes=base64.b64encode(canonical.encode()).decode(),payload=payload))


def sqlstate(conn,statement,params=(),code='0A000'):
    try: query(conn,statement,params)
    except psycopg2.Error as exc:
        conn.rollback(); assert exc.pgcode==code,(exc.pgcode,str(exc))
    else:
        conn.rollback(); raise AssertionError('expected SQLSTATE '+code)


def no_write(db,conn,effect,outcome,code=None,disposition=None,detail=None):
    global COUNT
    with contextlib.closing(db.connect('owner')) as owner:
        before=snapshot(owner); owner.rollback()
        result=api(conn,effect,outcome)
        if code: assert result.get('error',{}).get('code')==code,result
        if disposition: assert result.get('disposition')==disposition,result
        if detail is not None: assert result['error']['detail']==detail,result
        conn.commit()
        assert snapshot(owner)==before,(result,'changed rows')
    COUNT+=1
    return result


def active_root(db):
    """One spec-valid ownerless root per database; fixtures attach their fibers to it."""
    with contextlib.closing(db.connect('owner')) as owner:
        query(owner,'SELECT pg_advisory_xact_lock(24,1)')
        row=query(owner,"SELECT id,install_id,scope_id,current_episode_id,want_on FROM v24_cordis.fibers WHERE owner_id IS NULL LIMIT 1")
        if row:
            fiber,install,scope,episode,want_on=row[0]
            if episode is None:
                episode=uuid.uuid4()
                query(owner,"INSERT INTO v24_cordis.episodes(id,fiber_id,epoch,state,committed_view,iterator) SELECT %s,%s,coalesce(max(epoch),-1)+1,'active','{}',%s FROM v24_cordis.episodes WHERE fiber_id=%s",(episode,fiber,Json(dict(v=1,next_index=0,registered_through=-1,control_seq=0)),fiber))
                query(owner,'UPDATE v24_cordis.fibers SET current_episode_id=%s WHERE id=%s',(episode,fiber))
            if not want_on:
                query(owner,'UPDATE v24_cordis.fibers SET want_on=true WHERE id=%s',(fiber,))
            owner.commit()
            return dict(fiber=fiber,install=install,scope=scope,episode=episode)
        scope,install,fiber,episode=(uuid.uuid4() for _ in range(4))
        query(owner,'INSERT INTO v24_cordis.scopes(id) VALUES(%s)',(scope,))
        query(owner,"INSERT INTO v24_cordis.installs(id,scope_id,identity,version,manifest,artifact_digest,contracts,state) VALUES(%s,%s,%s,'1',%s,%s,'{}','installed')",(install,scope,str(install),Json({'requires':[],'provides':[],'priority':0,'check':{}}),'a'*64))
        query(owner,'INSERT INTO v24_cordis.fibers(id,install_id,scope_id) VALUES(%s,%s,%s)',(fiber,install,scope))
        query(owner,"INSERT INTO v24_cordis.episodes(id,fiber_id,epoch,state,committed_view,iterator) VALUES(%s,%s,0,'active','{}',%s)",(episode,fiber,Json(dict(v=1,next_index=0,registered_through=-1,control_seq=0))))
        query(owner,'UPDATE v24_cordis.fibers SET current_episode_id=%s,want_on=true WHERE id=%s',(episode,fiber))
        owner.commit()
    return dict(fiber=fiber,install=install,scope=scope,episode=episode)


def host_seed(db,replay=True,binding=True,scopes=1,kind='host_io',status='ready',repeat=None,concurrent=None,replay_config=None,digest_value='a'*64,binding_digest_value=None):
    ids=[uuid.uuid4() for _ in range(4)]
    scope,install,fiber,effect=ids
    root=active_root(db)
    contract=dict(contract_version='1',handler_digest=digest_value,replay=(replay_config if replay_config is not None else dict(repeat=replay if repeat is None else repeat,concurrent=replay if concurrent is None else concurrent)))
    frozen=dict(contract_version='1',handler_digest=(binding_digest_value if binding_digest_value is not None else (digest_value if binding else ('b'*64))))
    with contextlib.closing(db.connect('owner')) as owner:
        query(owner,'SELECT pg_advisory_xact_lock(24,1)')
        parent=None
        for i in range(scopes):
            node=scope if i==scopes-1 else uuid.uuid4()
            query(owner,'INSERT INTO v24_cordis.scopes(id,parent_id) VALUES(%s,%s)',(node,parent)); parent=node
        query(owner,"INSERT INTO v24_cordis.installs(id,scope_id,owner_fiber_id,owner_episode_id,identity,version,manifest,artifact_digest,contracts,state) VALUES(%s,%s,%s,%s,%s,'1',%s,%s,%s,'installed')",(install,scope,root['fiber'],root['episode'],str(install),Json({'requires':[],'provides':[],'priority':0,'check':{}}),'a'*64,Json({'host_io':contract})))
        query(owner,'INSERT INTO v24_cordis.fibers(id,install_id,owner_id,owner_episode_id,scope_id) VALUES(%s,%s,%s,%s,%s)',(fiber,install,root['fiber'],root['episode'],scope))
        query(owner,"INSERT INTO v24_cordis.effects(id,fiber_id,kind,status,input,request_actor,settled_at) VALUES(%s,%s,%s,%s,%s,'seed',%s)",(effect,fiber,kind,status,Json({'contract':frozen}),'2026-01-01' if status=='cancelled' else None))
        owner.commit()
    return dict(scope=scope,install=install,fiber=fiber,effect=effect,root=root)


def function_defs(db):
    with contextlib.closing(db.connect('owner')) as owner:
        return dict(query(owner,"SELECT proname,pg_get_functiondef(oid) FROM pg_proc WHERE pronamespace='v24_cordis'::regnamespace"))


def replace_function(db,name,definition):
    with contextlib.closing(db.connect('owner')) as owner:
        query(owner,sql.SQL('SET ROLE {}').format(sql.Identifier(db.groups['owner'])))
        query(owner,definition)
        owner.commit()


def install_probe(db):
    original=function_defs(db)
    definition='''CREATE OR REPLACE FUNCTION v24_cordis.interpret_command(p_effect_id uuid,p_principal uuid,p_outcome jsonb,p_closure jsonb) RETURNS jsonb
        LANGUAGE plpgsql SET search_path=pg_catalog,v24_cordis AS $$
        DECLARE p jsonb:=p_outcome->'body'->'payload';
        BEGIN
          IF p_outcome->>'class'<>'command' THEN
            RETURN jsonb_build_object('domain','[]'::jsonb,'receipt',jsonb_build_object('status',
              CASE p_outcome->>'class' WHEN 'success' THEN 'succeeded' WHEN 'failure' THEN 'failed' ELSE 'unknown' END),
              'events',jsonb_build_array(jsonb_build_object('entity_type','effect','entity_id',p_effect_id,
                'event_kind','receipt','payload','{}'::jsonb)),'successors','[]'::jsonb);
          END IF;
          RETURN v24_cordis.install_delta(p);
        END $$;'''
    replace_function(db,'interpret_command',definition)
    replace_function(db,'interpret_settlement',definition.replace('v24_cordis.interpret_command','v24_cordis.interpret_settlement'))
    actual=function_defs(db)
    assert original['validate_and_apply_delta']==actual['validate_and_apply_delta']
    return original


def test_vectors_acl(db,other):
    with contextlib.closing(db.connect('owner')) as owner:
        assert query(owner,"SELECT v24_cordis.principal_id('cordis_vector_service')::text")[0][0]=='5dac475d-3b76-12b3-59c5-c8abcdabea0e'
        assert query(owner,"SELECT v24_cordis.effect_id_for('5dac475d-3b76-12b3-59c5-c8abcdabea0e','dp1-vector-1','command_install')::text")[0][0]=='becfa4ba-9941-f073-26ad-ec08ef8cae3b'
        for payload,canonical,b64,digest in [({},'{}','e30=','44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a'),
            ({'z':[1,True],'a':{'x':'你好'}},'{"a": {"x": "你好"}, "z": [1, true]}','eyJhIjogeyJ4IjogIuS9oOWlvSJ9LCAieiI6IFsxLCB0cnVlXX0=','729a79256ffe193cbf67b726a6394f0206323acc11f1ca7ee1388f61bd1a7761')]:
            got=query(owner,"SELECT v24_cordis.canonical_json(%s),encode(sha256(convert_to(v24_cordis.canonical_json(%s),'UTF8')),'hex')",(Json(payload),Json(payload)))[0]
            assert got==(canonical,digest)
            assert base64.b64encode(canonical.encode()).decode()==b64
        for code in ERRORS:
            assert query(owner,'SELECT v24_cordis.error_v1(%s)',(code,))[0][0]==dict(v=1,error=dict(code=code,detail={}))
        sqlstate(owner,"SELECT v24_cordis.error_v1('not_a_code')",code='22023')
        rows=query(owner,"SELECT proname,prosecdef,proconfig,proowner FROM pg_proc WHERE pronamespace='v24_cordis'::regnamespace")
        assert [r[0] for r in rows if r[1]]==['advance']
        owner_oid=query(owner,"SELECT nspowner FROM pg_namespace WHERE nspname='v24_cordis'")[0][0]
        assert all(r[3]==owner_oid and 'search_path=pg_catalog, v24_cordis, pg_temp' in r[2] for r in rows)
        for alias in ('admin','service','operator','owner'):
            for cls in ('command','claim','success','failure','unknown','bad'):
                for kind in ('command_install','command_reconcile','command_dispose','host_io','model_call','tool_call','run_start'):
                    got=query(owner,'SELECT v24_cordis.role_allowed(%s,%s,%s,%s)',(db.roles[alias],cls,kind,'admit_and_apply' if cls=='command' else cls))[0][0]
                    expected=(alias in ('admin','service','operator') and cls=='command' and kind.startswith('command_')) or (alias=='service' and cls in ('claim','success','failure','unknown') and kind in ('host_io','model_call','tool_call','run_start'))
                    assert got==expected,(alias,cls,kind,got)
        for alias in ('admin','service','operator'):
            role=db.roles[alias]
            assert query(owner,"SELECT has_schema_privilege(%s,'v24_cordis','USAGE'),has_function_privilege(%s,'v24_cordis.advance(uuid,jsonb)','EXECUTE')",(role,role))[0]==(True,True)
            for table in TABLES:
                assert query(owner,'SELECT has_table_privilege(%s,%s,\'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER\')',(role,'v24_cordis.'+table))[0][0] is False
            assert query(owner,"SELECT bool_or(has_function_privilege(%s,p.oid,'EXECUTE')) FROM pg_proc p WHERE pronamespace='v24_cordis'::regnamespace AND proname<>'advance'",(role,))[0][0] is False
        assert not query(owner,"SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_namespace n, LATERAL pg_catalog.aclexplode(coalesce(n.nspacl,pg_catalog.acldefault('n',n.nspowner))) a WHERE n.nspname='v24_cordis' AND a.grantee=0)")[0][0]
        assert not query(owner,"SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_class r JOIN pg_catalog.pg_namespace n ON n.oid=r.relnamespace CROSS JOIN LATERAL pg_catalog.aclexplode(coalesce(r.relacl,pg_catalog.acldefault('r',r.relowner))) a WHERE n.nspname='v24_cordis' AND a.grantee=0)")[0][0]
        assert not query(owner,"SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace CROSS JOIN LATERAL pg_catalog.aclexplode(coalesce(p.proacl,pg_catalog.acldefault('f',p.proowner))) a WHERE n.nspname='v24_cordis' AND a.grantee=0)")[0][0]
    seed=host_seed(db)
    for alias in ('admin','service','operator'):
        with contextlib.closing(db.connect(alias)) as conn:
            sqlstate(conn,'SELECT * FROM v24_cordis.effects',code='42501')
            sqlstate(conn,"INSERT INTO v24_cordis.scopes(id) VALUES(gen_random_uuid())",code='42501')
            eid,out=command(db,alias,kind='command_reconcile',payload=dict(fiber_id=str(seed['fiber']),action='off',expected_control_seq=0))
            # W2 off-off is an authorized no-op with a durable first receipt.
            result=api(conn,eid,out)
            assert result.get('disposition')=='committed' and result['emitted']==[],result
            conn.commit()
            with contextlib.closing(db.connect('owner')) as owner:
                assert query(owner,'SELECT count(*) FROM v24_cordis.requests WHERE effect_id=%s',(eid,))[0][0]==1
                assert query(owner,'SELECT count(*) FROM v24_cordis.events WHERE effect_id=%s',(eid,))[0][0]==0
                assert query(owner,'SELECT want_on,control_seq FROM v24_cordis.fibers WHERE id=%s',(seed['fiber'],))[0]==(False,0)
            assert no_write(db,conn,eid,out,disposition='committed')==result
            if alias!='service': no_write(db,conn,seed['effect'],env('claim',{'lease_ms':1000}),'unauthorized')
    with contextlib.closing(db.connect('owner')) as owner:
        query(owner,sql.SQL('GRANT USAGE ON SCHEMA v24_cordis TO {}').format(sql.Identifier(other.roles['service'])))
        query(owner,sql.SQL('GRANT EXECUTE ON FUNCTION v24_cordis.advance(uuid,jsonb) TO {}').format(sql.Identifier(other.roles['service'])))
        owner.commit()
    # Real foreign LOGIN with explicit EXECUTE, plus hostile temporary catalog shadows.
    try:
        with contextlib.closing(db.server.connect(db.name,other.roles['service'])) as conn:
            fake_family=other.groups['service'][:-8]
            role_rows=[]
            for name in list(other.groups.values())+[other.roles['service']]:
                row=query(conn,"SELECT oid,rolname,rolcanlogin,rolinherit,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_catalog.pg_roles WHERE rolname=%s",(name,))[0]
                role_rows.append(row)
            foreign_owner=next(r[0] for r in role_rows if r[1]==other.groups['owner'])
            namespace_oid=query(conn,"SELECT oid FROM pg_catalog.pg_namespace WHERE nspname='v24_cordis'")[0][0]
            login_oid=next(r[0] for r in role_rows if r[1]==other.roles['service'])
            service_oid=next(r[0] for r in role_rows if r[1]==other.groups['service'])
            query(conn,'''CREATE TEMP TABLE pg_namespace(nspname name,nspowner oid);
              CREATE TEMP TABLE pg_roles(oid oid,rolname name,rolcanlogin boolean,rolinherit boolean,rolsuper boolean,
                rolcreatedb boolean,rolcreaterole boolean,rolreplication boolean,rolbypassrls boolean);
              CREATE TEMP TABLE pg_proc(pronamespace oid,proowner oid);
              CREATE TEMP TABLE pg_auth_members(roleid oid,member oid);''')
            query(conn,'INSERT INTO pg_temp.pg_namespace VALUES(%s,%s)',('v24_cordis',foreign_owner))
            for oid,name,*_ in role_rows:
                if name.startswith(other.family+'_'):
                    query(conn,'INSERT INTO pg_temp.pg_roles VALUES(%s,%s,false,false,false,false,false,false,false)',(oid,name))
            query(conn,'INSERT INTO pg_temp.pg_roles VALUES(%s,%s,true,true,false,false,false,false,false)',(login_oid,other.roles['service']))
            query(conn,'INSERT INTO pg_temp.pg_proc VALUES(%s,%s)',(namespace_oid,foreign_owner))
            query(conn,'INSERT INTO pg_temp.pg_auth_members VALUES(%s,%s)',(service_oid,login_oid))
            no_write(db,conn,seed['effect'],env('claim',{'lease_ms':1000}),'unauthorized')
    finally:
        with contextlib.closing(db.connect('owner')) as owner:
            query(owner,sql.SQL('REVOKE EXECUTE ON FUNCTION v24_cordis.advance(uuid,jsonb) FROM {}').format(sql.Identifier(other.roles['service'])))
            query(owner,sql.SQL('REVOKE USAGE ON SCHEMA v24_cordis FROM {}').format(sql.Identifier(other.roles['service'])))
            owner.commit()
    print('[CDP1-K1] fixed vectors, 24 error codes, 120 role/class/kind combinations and real ACL')


def test_preflight_claim(db):
    seed=host_seed(db)
    with contextlib.closing(db.connect('service')) as conn, contextlib.closing(db.connect('owner')) as owner:
        malformed=[{},env('bad'),env('claim',{'lease_ms':0}),env('claim',{'lease_ms':300001}),env('claim',{'lease_ms':1.5}),env('claim',{'lease_ms':10,'extra':1}),env('claim',{'lease_ms':1},{}),env('unknown',{'successors':[]},dict(attempt=0,fence=0,owner='x')),
                   env('success',{},dict(attempt=9223372036854775808,fence=0,owner='x')),env('success',{},dict(attempt=1,fence=1,owner='x',extra=1)),env('claim',{'lease_ms':True}),env('claim',{'lease_ms':None}),env('claim')]
        malformed[-1]['body']=None
        deep={}
        for _ in range(33): deep={'a':deep}
        malformed.extend([env('claim',deep),env('claim',{str(i):i for i in range(201)}),env('claim',{'x':'a'*1048576})])
        assert query(owner,'SELECT v24_cordis.valid_body(%s)',(Json({'items':list(range(20000))}),))[0][0] is True
        assert query(owner,'SELECT v24_cordis.valid_body(NULL)')[0][0] is False
        eid,out=command(db)
        for mutation in ({'op':None},{'canonical_bytes':'!'},{'canonical_bytes':'e30K'},{'payload':[]},{'extra':1},{'request_key':''}):
            malformed.append({**out,'body':{**out['body'],**mutation}})
        query(conn,"SET lock_timeout='100ms'")
        # G held elsewhere: malformed preflight must return without attempting G.
        query(owner,'SELECT pg_advisory_xact_lock(24,1)')
        for item in malformed: no_write(db,conn,eid,item,'invalid_args')
        owner.rollback()
        no_write(db,conn,uuid.uuid4(),out,'effect_id_conflict')
        no_write(db,conn,uuid.uuid4(),env('claim',{'lease_ms':1}),'not_found_or_denied')
        before=snapshot(owner); owner.rollback()
        got=api(conn,seed['effect'],env('claim',{'lease_ms':300000}))
        assert got['disposition']=='claimed' and set(got)=={'v','disposition','effect_id','emitted','revision','claim','input'}
        assert got['claim']==dict(attempt=1,fence=1,owner=db.roles['service'])
        assert query(owner,'SELECT status FROM v24_cordis.effects WHERE id=%s',(seed['effect'],))[0][0]=='ready'
        conn.rollback(); assert snapshot(owner)==before; owner.rollback()
        claim=api(conn,seed['effect'],env('claim',{'lease_ms':300000})); conn.commit()
        no_write(db,conn,seed['effect'],env('claim',{'lease_ms':1000}),'stale_claim',detail={'reason':'claim_busy'})
        # A distinct LOGIN in the same family is authorized but still sees the active claim as busy.
        extra=db.name+'_service2'
        try:
            query(db.admin,sql.SQL('CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS').format(sql.Identifier(extra)))
            query(db.admin,sql.SQL('GRANT {} TO {}').format(sql.Identifier(db.groups['service']),sql.Identifier(extra)))
            with contextlib.closing(db.server.connect(db.name,extra)) as second:
                no_write(db,second,seed['effect'],env('claim',{'lease_ms':1000}),'stale_claim',detail={'reason':'claim_busy'})
        finally:
            query(db.admin,sql.SQL('REVOKE {} FROM {}').format(sql.Identifier(db.groups['service']),sql.Identifier(extra)))
            query(db.admin,sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(extra)))
        no_write(db,conn,seed['effect'],env('success',{},dict(attempt=0,fence=1,owner=db.roles['service'])),'stale_claim')
        no_write(db,conn,seed['effect'],env('success',{},dict(attempt=1,fence=0,owner=db.roles['service'])),'stale_claim')
        no_write(db,conn,seed['effect'],env('success',{},dict(attempt=1,fence=1,owner='wrong')),'stale_claim')
        sqlstate(conn,'SELECT v24_cordis.advance(%s,%s)',(seed['effect'],Json(env('success',{},claim['claim']))))
        query(owner,"UPDATE v24_cordis.effects SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s",(seed['effect'],)); owner.commit()
        sqlstate(conn,'SELECT v24_cordis.advance(%s,%s)',(seed['effect'],Json(env('success',{},claim['claim'])))) # expiry did not revoke
        got2=api(conn,seed['effect'],env('claim',{'lease_ms':300000})); conn.commit()
        assert got2['claim']['attempt']==2 and got2['claim']['fence']==2
        no_write(db,conn,seed['effect'],env('success',{},claim['claim']),'stale_claim')
    for replay_config in ({'repeat':True,'concurrent':False},{'repeat':False,'concurrent':True},{'repeat':None,'concurrent':True},{'repeat':'true','concurrent':True},{}):
        item=host_seed(db,replay_config=replay_config)
        with contextlib.closing(db.connect('service')) as conn:
            api(conn,item['effect'],env('claim',{'lease_ms':1})); conn.commit()
            with contextlib.closing(db.connect('owner')) as owner:
                query(owner,"UPDATE v24_cordis.effects SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s",(item['effect'],)); owner.commit()
            no_write(db,conn,item['effect'],env('claim',{'lease_ms':1}),'blocked_unknown')
    malformed_digest=10**63+123
    item=host_seed(db,digest_value=malformed_digest,binding_digest_value=malformed_digest)
    with contextlib.closing(db.connect('service')) as conn:
        no_write(db,conn,item['effect'],env('claim',{'lease_ms':100}),'invalid_args')
    item=host_seed(db,binding=False)
    with contextlib.closing(db.connect('service')) as conn:
        no_write(db,conn,item['effect'],env('claim',{'lease_ms':100}),'invalid_args')
    for kind in ('model_call','tool_call','run_start'):
        item=host_seed(db,kind=kind)
        with contextlib.closing(db.connect('service')) as conn:
            got=api(conn,item['effect'],env('claim',{'lease_ms':1})); conn.rollback()
            assert got['error']['code']=='invalid_outcome',got
        for alias in ('admin','operator'):
            with contextlib.closing(db.connect(alias)) as conn:
                no_write(db,conn,item['effect'],env('claim',{'lease_ms':1}),'unauthorized')
    cancelled=host_seed(db,status='cancelled')
    with contextlib.closing(db.connect('service')) as conn:
        no_write(db,conn,cancelled['effect'],env('success',{},dict(attempt=0,fence=0,owner='x')),'receipt_conflict')
    print('[CDP1-K2] preflight before G; claim visibility/rollback/busy/reclaim/old-token/contract guards')


def test_delta(db):
    with contextlib.closing(db.connect('owner')) as owner:
        base=dict(domain=[],receipt=dict(status='succeeded'),events=[],successors=[])
        def validate(delta,structure=False,cls='command'):
            return query(owner,"SELECT v24_cordis.validate_delta(%s,%s,%s)",(Json(delta),cls,structure))[0][0]
        assert validate(base) is None
        successors=[dict(ordinal=i,kind='host_io',input={}) for i in range(16)]
        assert validate({**base,'successors':successors},True) is None
        for delta in ({**base,'successors':successors+[dict(ordinal=16,kind='host_io',input={})]},
                      {**base,'successors':[successors[0],successors[0]]},{**base,'successors':[dict(ordinal=16,kind='host_io',input={})]},
                      {**base,'receipt':dict(status='failed')},{**base,'events':[{}]},{**base,'extra':1},
                      {**base,'domain':[dict(op='episode_begin')]},
                      {**base,'domain':[dict(op='contribution_append',inverse=dict(op='unknown'))]}):
            assert validate(delta,True)['error']['code']=='invalid_outcome',delta
        # DP1's old inverse-only probe is replaced by a typed contribution delta; the union is closed.
        contribution=dict(op='contribution_append',id=str(uuid.uuid4()),fiber_id=str(uuid.uuid4()),
            episode_id=str(uuid.uuid4()),seq=0,kind='service',realm='root',key='svc',descriptor={},
            prev_contribution_id=None,inverse=dict(op='delete_row'),contract_version='1')
        assert validate({**base,'domain':[contribution]},True) is None
        assert validate({**base,'domain':[contribution]}) is None
        for mutation in ({'key':None},{'realm':None},{'seq':-1},{'inverse':dict(op='unknown')},
                         {'extra':1},{'descriptor':[]},{'kind':'child'},{'prev_contribution_id':str(uuid.uuid4())}):
            assert validate({**base,'domain':[{**contribution,**mutation}]},True)['error']['code']=='invalid_outcome'
        # Non-command settlement classes never gain domain or successor write rights.
        for cls,status in (('success','succeeded'),('failure','failed'),('unknown','unknown')):
            delta={**base,'receipt':dict(status=status),'domain':[contribution]}
            got=validate(delta,False,cls)['error']['detail']
            assert got==dict(reason='settlement_has_no_domain'),got
            got=validate({**base,'receipt':dict(status=status),'successors':successors[:1]},False,cls)['error']['detail']
            assert got==dict(reason='settlement_has_no_domain'),got
        owner.rollback()
    print('[CDP1-K3] typed delta validator: closed shapes, 16/17 successors, settlement write denial')


def wait_blocked(db,pid):
    deadline=time.monotonic()+4
    with contextlib.closing(db.connect()) as monitor:
        while time.monotonic()<deadline:
            if query(monitor,'SELECT cardinality(pg_blocking_pids(%s))',(pid,))[0][0]>0: return
            monitor.rollback(); time.sleep(.01)
    raise AssertionError('caller never waited at expected row lock')


def test_locks_closure(db):
    # Hold G: a caller must wait on G while the replay-target effect remains independently lockable.
    g_item=host_seed(db)
    with contextlib.closing(db.connect('owner')) as blocker, contextlib.closing(db.connect('service')) as caller, contextlib.closing(db.connect('owner')) as monitor:
        query(blocker,'SELECT pg_advisory_xact_lock(24,1)')
        pid=caller.get_backend_pid(); result=[]
        def call_g():
            try: result.append(api(caller,g_item['effect'],env('claim',{'lease_ms':1000}))); caller.commit()
            except BaseException as exc: result.append(exc); caller.rollback()
        thread=threading.Thread(target=call_g); thread.start()
        try:
            wait_blocked(db,pid)
            waiting=query(monitor,"SELECT granted FROM pg_locks WHERE pid=%s AND locktype='advisory' AND classid=24 AND objid=1",(pid,))
            assert waiting==[(False,)],waiting
            query(monitor,'SELECT id FROM v24_cordis.effects WHERE id=%s FOR UPDATE NOWAIT',(g_item['effect'],))
            monitor.rollback()
        finally:
            blocker.rollback(); thread.join(6)
        assert not thread.is_alive() and result[0]['disposition']=='claimed',result
    item=host_seed(db)
    with contextlib.closing(db.connect('owner')) as blocker, contextlib.closing(db.connect('service')) as caller, contextlib.closing(db.connect('owner')) as monitor:
        query(blocker,'SELECT id FROM v24_cordis.scopes WHERE id=%s FOR UPDATE',(item['scope'],))
        pid=caller.get_backend_pid(); result=[]
        def call():
            try: result.append(api(caller,item['effect'],env('claim',{'lease_ms':1000}))); caller.commit()
            except BaseException as exc: result.append(exc); caller.rollback()
        thread=threading.Thread(target=call); thread.start()
        try:
            wait_blocked(db,pid)
            locks=query(monitor,"SELECT granted FROM pg_locks WHERE pid=%s AND locktype='advisory' AND classid=24 AND objid=1",(pid,))
            assert locks==[(True,)]
            sqlstate(monitor,'SELECT id FROM v24_cordis.effects WHERE id=%s FOR UPDATE NOWAIT',(item['effect'],),code='55P03')
            # Fiber lies later than the blocked scope and is not locked yet.
            query(monitor,'SELECT id FROM v24_cordis.fibers WHERE id=%s FOR UPDATE NOWAIT',(item['fiber'],)); monitor.rollback()
        finally:
            blocker.rollback(); thread.join(6)
        assert not thread.is_alive() and result[0]['disposition']=='claimed',result
    # Exactly 512 typed targets: effect/fiber/install plus 509 ancestor scopes.
    at_limit=host_seed(db,scopes=505); over=host_seed(db,scopes=506)
    with contextlib.closing(db.connect('service')) as conn:
        assert api(conn,at_limit['effect'],env('claim',{'lease_ms':1000}))['disposition']=='claimed'; conn.rollback()
        no_write(db,conn,over['effect'],env('claim',{'lease_ms':1000}),'retry_with_closure')
    definitions=function_defs(db)
    refs=definitions['target_refs'].replace('BEGIN',"BEGIN\n PERFORM set_config('cordis.ref_count',(coalesce(nullif(current_setting('cordis.ref_count',true),''),'0')::int+1)::text,true);",1)
    replace_function(db,'target_refs',refs)
    try:
        with contextlib.closing(db.connect('owner')) as owner:
            seed=[dict(t='effects',id=str(over['effect']))]
            assert query(owner,'SELECT v24_cordis.discover_closure(%s)',(Json(seed),))[0][0] is None
            assert int(query(owner,"SELECT current_setting('cordis.ref_count')")[0][0])==512
            owner.rollback()
            target=dict(t='effects',id=str(item['effect']))
            got=query(owner,'SELECT v24_cordis.discover_closure(%s)',(Json([target,target]),))[0][0]
            assert len(got)==8
            missing=[dict(t='effects',id=str(uuid.uuid4()))]
            assert query(owner,'SELECT v24_cordis.discover_closure(%s)',(Json(missing),))[0][0] is None
    finally: replace_function(db,'target_refs',definitions['target_refs'])
    drift=definitions['discover_closure'].replace('BEGIN',"BEGIN\n IF current_setting('cordis.drift',true)='second' THEN RETURN '[]'::jsonb; END IF;\n PERFORM set_config('cordis.drift','second',true);",1)
    replace_function(db,'discover_closure',drift)
    try:
        with contextlib.closing(db.connect('service')) as conn:
            no_write(db,conn,item['effect'],env('claim',{'lease_ms':1}),'retry_with_closure')
    finally: replace_function(db,'discover_closure',definitions['discover_closure'])
    print('[CDP1-K4] real G→replay effect→scope lock wait; 512/513 early cutoff, typed dedupe, missing/drift')
    return over


def test_committed_probe(production,probe):
    frozen=function_defs(production)
    applier_hash=hashlib.sha256(function_defs(probe)['validate_and_apply_delta'].encode()).hexdigest()
    original=install_probe(probe)
    with contextlib.closing(probe.connect('owner')) as owner:
        assert 'DP1 lifecycle' not in query(owner,"SELECT pg_get_functiondef('v24_cordis.interpret_command(uuid,uuid,jsonb,jsonb)'::regprocedure)")[0][0]
    effect,out=command(probe,key='durable')
    with contextlib.closing(probe.connect('service')) as conn:
        first=api(conn,effect,out); assert first['disposition']=='committed'; conn.commit()
    with contextlib.closing(probe.connect('service')) as conn:
        replay=no_write(probe,conn,effect,out); assert replay==first
        changed={**out,'receipt_key':'transport-change'}
        assert no_write(probe,conn,effect,changed)==first
        wrongbytes=command(probe,key='durable',payload={'different':True})
        no_write(probe,conn,*wrongbytes,'request_conflict')
        differentkind=command(probe,key='durable',kind='command_dispose')
        no_write(probe,conn,*differentkind,'request_conflict')
        no_write(probe,conn,uuid.uuid4(),out,'effect_id_conflict')
    for cls in ('success','failure','unknown'):
        item=host_seed(probe)
        with contextlib.closing(probe.connect('service')) as conn:
            claim=api(conn,item['effect'],env('claim',{'lease_ms':300000}))['claim']; conn.commit()
        with contextlib.closing(probe.connect('owner')) as owner:
            query(owner,"UPDATE v24_cordis.effects SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s",(item['effect'],)); owner.commit()
        outcome=env(cls,{'answer':cls},claim,receipt_key='first')
        with contextlib.closing(probe.connect('service')) as conn:
            assert api(conn,item['effect'],outcome)['disposition']=='committed'; conn.commit()
        with contextlib.closing(probe.connect('service')) as conn:
            no_write(probe,conn,item['effect'],{**outcome,'receipt_key':'changed'},disposition='replay')
            no_write(probe,conn,item['effect'],{**outcome,'claim':dict(attempt=99,fence=99,owner='wrong')},'receipt_conflict')
            no_write(probe,conn,item['effect'],{**outcome,'body':{'different':True}},'receipt_conflict')
    # Rejected expired reclaim preserves the original claim's settlement eligibility.
    item=host_seed(probe,replay=False)
    with contextlib.closing(probe.connect('service')) as conn, contextlib.closing(probe.connect('owner')) as owner:
        token=api(conn,item['effect'],env('claim',{'lease_ms':300000}))['claim']; conn.commit()
        query(owner,"UPDATE v24_cordis.effects SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s",(item['effect'],)); owner.commit()
        no_write(probe,conn,item['effect'],env('claim',{'lease_ms':1000}),'blocked_unknown')
        assert api(conn,item['effect'],env('success',{},token))['disposition']=='committed'; conn.commit()
    # A replay/conflict cannot invoke discovery even for an oversized closure or wait on its scope.
    over=host_seed(probe,scopes=506)
    with contextlib.closing(probe.connect('owner')) as owner:
        query(owner,"UPDATE v24_cordis.effects SET status='claimed',attempt=1,fence=1,claim_owner=%s,lease_until='2020-01-01' WHERE id=%s",(probe.roles['service'],over['effect']))
        owner.commit()
    outcome=env('success',{},dict(attempt=1,fence=1,owner=probe.roles['service']))
    # Seed terminal receipt only as fixture DML because new oversized execution correctly cannot pass closure.
    with contextlib.closing(probe.connect('owner')) as owner:
        query(owner,"UPDATE v24_cordis.effects SET status='succeeded',outcome=%s,settled_at=now(),claim_owner=NULL,lease_until=NULL WHERE id=%s",(Json(outcome),over['effect'])); owner.commit()
    definitions=function_defs(probe)
    bomb=definitions['discover_closure'].replace('BEGIN',"BEGIN RAISE EXCEPTION 'discovery must not run' USING ERRCODE='U0001';",1)
    replace_function(probe,'discover_closure',bomb)
    try:
        with contextlib.closing(probe.connect('owner')) as blocker, contextlib.closing(probe.connect('service')) as conn:
            query(blocker,'SELECT id FROM v24_cordis.scopes WHERE id=%s FOR UPDATE',(over['scope'],))
            query(conn,"SET lock_timeout='100ms'")
            no_write(probe,conn,over['effect'],outcome,disposition='replay')
            no_write(probe,conn,over['effect'],{**outcome,'body':{'conflict':1}},'receipt_conflict')
            assert no_write(probe,conn,effect,out)==first
            no_write(probe,conn,*command(probe,key='durable',payload={'x':1}),'request_conflict')
            blocker.rollback()
    finally: replace_function(probe,'discover_closure',definitions['discover_closure'])
    # W3 B1: the command effect exists before events, while the request cache is
    # deliberately written after the event phase. The trigger proves that order,
    # then raises so the whole effect/event/cache transaction must roll back.
    with contextlib.closing(probe.connect('owner')) as owner:
        query(owner,sql.SQL('SET ROLE {}').format(sql.Identifier(probe.groups['owner'])))
        query(owner,"""CREATE FUNCTION v24_cordis.probe_fault() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN IF NOT EXISTS(SELECT 1 FROM v24_cordis.effects WHERE id=NEW.effect_id)
          OR EXISTS(SELECT 1 FROM v24_cordis.requests WHERE effect_id=NEW.effect_id) THEN
          RAISE EXCEPTION 'wrong injection point' USING ERRCODE='U0002'; END IF;
          RAISE EXCEPTION 'post effect/pre-cache fault' USING ERRCODE='U0001'; END $$;
        CREATE TRIGGER probe_fault BEFORE INSERT ON v24_cordis.events FOR EACH ROW EXECUTE FUNCTION v24_cordis.probe_fault();""")
        owner.commit(); before=snapshot(owner); owner.rollback()
        fault_payload=install_payload()
        fault_payload['scope']=dict(mode='existing',id=str(over['root']['scope']))
        fault_payload['identity']='dp1-fault'
        fault_payload['owner']=dict(fiber_id=str(over['root']['fiber']),episode_id=str(over['root']['episode']))
        eid,attempt=command(probe,key='fault',payload=fault_payload)
        with contextlib.closing(probe.connect('service')) as conn:
            sqlstate(conn,'SELECT v24_cordis.advance(%s,%s)',(eid,Json(attempt)),code='U0001')
        assert snapshot(owner)==before
        query(owner,'DROP TRIGGER probe_fault ON v24_cordis.events; DROP FUNCTION v24_cordis.probe_fault()'); owner.commit()
    barrier=definitions['barrier_ready'].replace('SELECT true','SELECT false')
    replace_function(probe,'barrier_ready',barrier)
    try:
        item=host_seed(probe)
        with contextlib.closing(probe.connect('service')) as conn:
            result=no_write(probe,conn,item['effect'],env('claim',{'lease_ms':1000}),disposition='deferred'); assert result['claim'] is None
        with contextlib.closing(probe.connect('owner')) as owner:
            assert query(owner,'SELECT pg_try_advisory_xact_lock(24,1)')[0][0] is True
    finally: replace_function(probe,'barrier_ready',definitions['barrier_ready'])
    assert hashlib.sha256(function_defs(probe)['validate_and_apply_delta'].encode()).hexdigest()==applier_hash
    probe.cleanup()
    assert function_defs(production)==frozen
    with contextlib.closing(production.connect('owner')) as owner:
        sqlstate(owner,"SELECT v24_cordis.interpret_settlement(gen_random_uuid(),gen_random_uuid(),'{}','[]')")
        got=query(owner,"SELECT v24_cordis.interpret_command(gen_random_uuid(),gen_random_uuid(),'{}','[]')")[0][0]
        assert got['error']['code']=='invalid_args',got
        malformed={'v':1,'class':'command','claim':None,'body':{'op':'admit_and_apply','kind':'command_reconcile',
            'request_key':'probe','canonical_bytes':'e30=','payload':{'action':'on'}}}
        got=query(owner,'SELECT v24_cordis.interpret_command(%s,%s,%s,%s)',(uuid.uuid4(),uuid.uuid4(),Json(malformed),Json([])))[0][0]
        assert got['error']['code']=='invalid_args',got
        valid={'v':1,'class':'command','claim':None,'body':{'op':'admit_and_apply','kind':'command_reconcile',
            'request_key':'probe','canonical_bytes':'e30=','payload':{'fiber_id':str(uuid.uuid4()),'action':'on','expected_control_seq':0}}}
        got=query(owner,'SELECT v24_cordis.interpret_command(%s,%s,%s,%s)',(uuid.uuid4(),uuid.uuid4(),Json(valid),Json([])))[0][0]
        assert got['error']['code']=='not_found_or_denied',got
        for action in ('off','retry'):
            control=json.loads(json.dumps(valid))
            control['body']['payload']['action']=action
            got=query(owner,'SELECT v24_cordis.interpret_command(%s,%s,%s,%s)',
                      (uuid.uuid4(),uuid.uuid4(),Json(control),Json([])))[0][0]
            assert got['error']['code']=='not_found_or_denied',got
    print('[CDP1-K5] disposable COMMIT probe, new-connection command/terminal replay, post-write rollback, barrier and original production hashes')


def main():
    assert len(CANONICAL_ORDER) == 19 and len(list((Path(__file__).resolve().parents[1] / 'sql').glob('*.sql'))) == 19
    prove_helper_budget_boundary()
    total,counts=assert_helper_budget(Path(__file__).resolve().parents[1]/'sql')
    print(f'[CDP1-K0] helper budget {total}<={LIMIT} {counts}; predicate admits a {LIMIT}-line tree and rejects {LIMIT + 1}')
    with Server() as server, TestDB(server) as production, TestDB(server) as probe:
        test_vectors_acl(production,probe)
        test_preflight_claim(production)
        test_delta(production)
        test_locks_closure(production)
        test_committed_probe(production,probe)
    print(f'[passed] CDP1-K ({COUNT} committed zero-write assertions; reconcile on/off/retry/advance is production through W2; activated teardown/dispose remains later scope)')

if __name__=='__main__': main()
