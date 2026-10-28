"""CDP1-D: real constraints, transaction-final guards and zero-write negatives."""
from __future__ import annotations
import contextlib
import json
from pathlib import Path
import uuid
import psycopg2
from psycopg2 import sql
from psycopg2.extras import register_uuid
from setup_db import Server, TestDB, TABLES
register_uuid()

IDS = {k:uuid.uuid5(uuid.NAMESPACE_URL,'cordis-ddl-'+k) for k in
       ('s1','s2','i1','i2','f1','f2','e1','e2','e3','run','c1','c2','effect','event','pin')}
EXPECTED = {
 'installs':'id scope_id owner_fiber_id owner_episode_id identity version manifest artifact_digest contracts policy_ref overlay state created_at',
 'scopes':'id parent_id realm_overrides intercept closed_at',
 'fibers':'id install_id owner_id owner_episode_id scope_id want_on control_seq current_episode_id retire_started_at failure dispose_requested_at disposed_at',
 'episodes':'id fiber_id epoch state committed_view iterator outcome opened_at closed_at',
 'contributions':'id fiber_id episode_id seq kind realm key descriptor prev_contribution_id inverse contract_version withdrawn_at released_at',
 'pins':'id consumer_fiber_id consumer_episode_id consumer_run_id key contribution_id provider_epoch created_at released_at',
 'runs':'id owner_fiber_id owner_episode_id scope_id parent_run_id spawn_key state remaining_steps ended_at result',
 'effects':'id parent_id ordinal fiber_id episode_id run_id kind status input request_actor claim_owner attempt fence lease_until outcome settled_at',
 'events':'event_id effect_id seq entity_type entity_id event_kind payload',
 'requests':'principal_id request_key kind request_bytes request_digest effect_id response created_at',
}
COUNT=0

def snapshot(conn):
    result={}
    with conn.cursor() as c:
        for table in sorted(TABLES):
            c.execute(sql.SQL('SELECT to_jsonb(t)::text FROM v24_cordis.{} t ORDER BY 1').format(sql.Identifier(table)))
            result[table]=c.fetchall()
    return result


def rejected(conn,label,statement,params=(),states=('23514',),deferred=True):
    global COUNT
    before=snapshot(conn)
    with conn.cursor() as c:
        c.execute('SAVEPOINT negative')
        try:
            c.execute(statement,params)
            if deferred: c.execute('SET CONSTRAINTS ALL IMMEDIATE')
        except psycopg2.Error as exc:
            c.execute('ROLLBACK TO SAVEPOINT negative')
            assert exc.pgcode in states, (label,exc.pgcode,str(exc))
        else:
            c.execute('ROLLBACK TO SAVEPOINT negative')
            raise AssertionError(label+': invalid operation accepted')
        finally:
            c.execute('RELEASE SAVEPOINT negative')
    assert snapshot(conn)==before,label
    conn.commit()
    assert snapshot(conn)==before,label+' after COMMIT'
    COUNT+=1


def clone(conn,table,base,changes,label=None,state='23514'):
    """Insert a fresh row to test constraints without hitting UPDATE immutability first."""
    values={'id':str(uuid.uuid4()),**changes}
    statement=sql.SQL('INSERT INTO v24_cordis.{t} SELECT (jsonb_populate_record(NULL::v24_cordis.{t},to_jsonb(x)||%s::jsonb)).* FROM v24_cordis.{t} x WHERE id=%s').format(t=sql.Identifier(table))
    params=(json.dumps(values,default=str),base)
    if label:
        rejected(conn,label,statement,params,states=(state,))
    else:
        with conn.cursor() as c: c.execute(statement,params)
        conn.commit()
    return values['id']


def seed(conn):
    with conn.cursor() as c:
        c.execute('SELECT pg_advisory_xact_lock(24,1)')
        c.execute('INSERT INTO v24_cordis.scopes(id) VALUES(%s),(%s)',(IDS['s1'],IDS['s2']))
        for suffix in ('1','2'):
            c.execute("INSERT INTO v24_cordis.installs(id,scope_id,owner_fiber_id,owner_episode_id,identity,version,manifest,artifact_digest,contracts,state) VALUES(%s,%s,%s,%s,%s,'1',%s,%s,'{}','installed')",
                      (IDS['i'+suffix],IDS['s'+suffix],(None if suffix=='1' else IDS['f1']),
                       (None if suffix=='1' else IDS['e1']),'plugin-'+suffix,
                       json.dumps({'requires':[],'provides':[],'priority':0,'check':{}}),'a'*64))
            c.execute('INSERT INTO v24_cordis.fibers(id,install_id,owner_id,owner_episode_id,scope_id) VALUES(%s,%s,%s,%s,%s)',
                      (IDS['f'+suffix],IDS['i'+suffix],(None if suffix=='1' else IDS['f1']),
                       (None if suffix=='1' else IDS['e1']),IDS['s'+suffix]))
        c.execute("INSERT INTO v24_cordis.episodes(id,fiber_id,epoch,state,closed_at) VALUES(%s,%s,0,'active',NULL),(%s,%s,1,'closing',now()),(%s,%s,0,'active',NULL)",
                  (IDS['e1'],IDS['f1'],IDS['e2'],IDS['f1'],IDS['e3'],IDS['f2']))
        c.execute('UPDATE v24_cordis.fibers SET current_episode_id=%s WHERE id=%s',(IDS['e1'],IDS['f1']))
        c.execute('INSERT INTO v24_cordis.runs(id,owner_fiber_id,owner_episode_id,scope_id,remaining_steps) VALUES(%s,%s,%s,%s,4)',(IDS['run'],IDS['f2'],IDS['e3'],IDS['s1']))
        for name,episode,seq in [('c1','e1',0),('c2','e2',0)]:
            c.execute("INSERT INTO v24_cordis.contributions(id,fiber_id,episode_id,seq,kind,realm,key,descriptor,inverse,contract_version) VALUES(%s,%s,%s,%s,'service','r',%s,'{}','{\"op\":\"delete_row\"}','1')",(IDS[name],IDS['f1'],IDS[episode],seq,name))
        c.execute("INSERT INTO v24_cordis.pins(id,consumer_fiber_id,consumer_episode_id,key,contribution_id,provider_epoch) VALUES(%s,%s,%s,'k',%s,0)",(IDS['pin'],IDS['f2'],IDS['e3'],IDS['c1']))
        c.execute("INSERT INTO v24_cordis.effects(id,kind,status,input,request_actor) VALUES(%s,'host_io','ready','{}','seed')",(IDS['effect'],))
        c.execute("INSERT INTO v24_cordis.events(event_id,effect_id,seq,entity_type,entity_id,event_kind,payload) VALUES(%s,%s,0,'fiber',%s,'seed','{}')",(IDS['event'],IDS['effect'],IDS['f1']))
    conn.commit()


def catalog(conn):
    with conn.cursor() as c:
        c.execute("SELECT table_name,column_name FROM information_schema.columns WHERE table_schema='v24_cordis'")
        actual={}
        for table,col in c.fetchall(): actual.setdefault(table,set()).add(col)
        assert actual=={t:set(cols.split()) for t,cols in EXPECTED.items()}
        c.execute("SELECT count(*) FROM pg_class WHERE relnamespace='v24_cordis'::regnamespace AND relowner<>(SELECT nspowner FROM pg_namespace WHERE nspname='v24_cordis')")
        assert c.fetchone()[0]==0
        c.execute("SELECT conrelid::regclass::text,condeferrable,condeferred FROM pg_constraint WHERE contype='f' AND conrelid IN ('v24_cordis.events'::regclass,'v24_cordis.requests'::regclass)")
        assert set(c.fetchall())=={('v24_cordis.events',True,True),('v24_cordis.requests',True,True)}
        c.execute("SELECT tgname,tgtype FROM pg_trigger WHERE tgrelid='v24_cordis.events'::regclass AND NOT tgisinternal")
        assert {r[0] for r in c.fetchall()}=={'events_no_update','events_no_delete','events_no_truncate'}
    root=Path(__file__).resolve().parents[1]/'sql'
    names=[f for f in root.glob('*.sql') if 10<=int(f.name[:2])<=17 or f.name in ('20_relations.sql','30_triggers.sql')]
    lines=sum(len(f.read_text().splitlines()) for f in names)
    assert len(names)==10,names
    print('[CDP1-D1] exact columns/owner/deferred FK/append-only catalog; DDL lines',lines)


def relations(conn):
    clone(conn,'installs',IDS['i1'],{'identity':'bad-owner','owner_fiber_id':IDS['f1'],'owner_episode_id':IDS['e3']},'install cross episode','23503')
    clone(conn,'installs',IDS['i1'],{'identity':'pair','owner_fiber_id':IDS['f1']},'install pair')
    clone(conn,'installs',IDS['i1'],{},'install identity unique','23505')
    clone(conn,'installs',IDS['i1'],{'identity':'bad-state','state':'bogus'},'install state')
    for manifest,label in [({'requires':[],'provides':[],'priority':0},'manifest requires check'),
                           ({'provides':[],'priority':0,'check':{}},'manifest missing requires'),
                           ({'requires':{},'provides':[],'priority':0,'check':{}},'manifest requires array'),
                           ({'requires':[],'provides':{},'priority':0,'check':{}},'manifest provides array'),
                           ({'requires':[],'provides':[],'priority':'0','check':{}},'manifest priority number')]:
        clone(conn,'installs',IDS['i1'],{'identity':'manifest-'+label,'manifest':manifest},label)
    clone(conn,'installs',IDS['i1'],{'identity':'bad-digest','artifact_digest':'A'*64},'artifact sha256')
    clone(conn,'fibers',IDS['f2'],{'owner_id':IDS['f1'],'owner_episode_id':IDS['e3']},'fiber cross episode','23503')
    clone(conn,'fibers',IDS['f2'],{'owner_id':IDS['f1'],'owner_episode_id':None},'fiber owner pair')
    ident=uuid.uuid4()
    clone(conn,'fibers',IDS['f2'],{'id':ident,'owner_id':ident,'owner_episode_id':IDS['e3']},'fiber self owner')
    for cols in ({'owner_fiber_id':None,'owner_episode_id':None},{'owner_fiber_id':None},{'owner_episode_id':None}):
        clone(conn,'runs',IDS['run'],cols,'run nonnullable owner','23502')
    clone(conn,'runs',IDS['run'],{'owner_episode_id':IDS['e1']},'run cross episode','23503')
    clone(conn,'runs',IDS['run'],{'remaining_steps':-1},'run budget')
    clone(conn,'runs',IDS['run'],{'parent_run_id':uuid.uuid4()},'run missing parent','23503')
    clone(conn,'runs',IDS['run'],{'parent_run_id':IDS['run'],'spawn_key':'k'})
    clone(conn,'runs',IDS['run'],{'parent_run_id':IDS['run'],'spawn_key':'k'},'spawn unique','23505')
    clone(conn,'contributions',IDS['c1'],{'seq':5,'key':'mismatch','episode_id':IDS['e3']},'contribution cross episode','23503')
    clone(conn,'pins',IDS['pin'],{'key':'mismatch','consumer_episode_id':IDS['e1']},'pin cross episode','23503')
    clone(conn,'effects',IDS['effect'],{'fiber_id':IDS['f1'],'episode_id':IDS['e3']},'effect cross episode','23503')
    clone(conn,'pins',IDS['pin'],{'consumer_fiber_id':None,'consumer_episode_id':None},'pin neither consumer')
    clone(conn,'pins',IDS['pin'],{'consumer_run_id':IDS['run'],'key':'both'},'pin both consumers')
    clone(conn,'pins',IDS['pin'],{'consumer_episode_id':None,'key':'partial'},'pin partial consumer')
    clone(conn,'pins',IDS['pin'],{'consumer_fiber_id':None,'consumer_episode_id':None,'consumer_run_id':uuid.uuid4()},'pin missing run','23503')
    clone(conn,'pins',IDS['pin'],{'key':'epoch','provider_epoch':1},'pin provider epoch')
    # Constraint triggers inspect the final pin row, not an intermediate UPDATE version.
    with conn.cursor() as c:
        temporary=uuid.uuid4()
        c.execute("INSERT INTO v24_cordis.pins(id,consumer_fiber_id,consumer_episode_id,key,contribution_id,provider_epoch) VALUES(%s,%s,%s,'delete-before-commit',%s,1)",(temporary,IDS['f2'],IDS['e3'],IDS['c1']))
        c.execute('DELETE FROM v24_cordis.pins WHERE id=%s',(temporary,))
    conn.commit()
    clone(conn,'pins',IDS['pin'],{},'pin active fiber unique','23505')
    clone(conn,'pins',IDS['pin'],{'released_at':'2026-01-01'})
    runpin={'consumer_fiber_id':None,'consumer_episode_id':None,'consumer_run_id':IDS['run']}
    clone(conn,'pins',IDS['pin'],runpin)
    clone(conn,'pins',IDS['pin'],runpin,'pin active run unique','23505')
    clone(conn,'contributions',IDS['c1'],{'seq':2},'service unique','23505')
    clone(conn,'contributions',IDS['c1'],{'seq':2,'key':'new','released_at':'2026-01-01'},'release needs withdrawal')
    clone(conn,'contributions',IDS['c1'],{'seq':2,'key':'new','withdrawn_at':'2026-01-02','released_at':'2026-01-01'},'release time order')
    clone(conn,'contributions',IDS['c1'],{'seq':2,'key':'new','inverse':{'op':'unknown'}},'unknown inverse needs debt')
    clone(conn,'contributions',IDS['c1'],{'seq':2,'key':'new','inverse':{'op':None}},'inverse op cannot be null')
    clone(conn,'contributions',IDS['c1'],{'seq':2,'key':'new','inverse':{'op':'sql'}},'closed inverse ops')
    listener={'seq':3,'kind':'listener','descriptor':{'event':'ev','listener_id':'l'}}
    clone(conn,'contributions',IDS['c1'],listener)
    clone(conn,'contributions',IDS['c1'],{**listener,'seq':4},'listener unique','23505')
    clone(conn,'contributions',IDS['c1'],{'key':'unique-key'},'contribution seq unique','23505')
    clone(conn,'episodes',IDS['e1'],{'epoch':8},'one open episode','23505')
    rejected(conn,'cross fiber current','UPDATE v24_cordis.fibers SET current_episode_id=%s WHERE id=%s',(IDS['e3'],IDS['f1']),states=('23503','23514'))
    rejected(conn,'closed current','UPDATE v24_cordis.fibers SET current_episode_id=%s WHERE id=%s',(IDS['e2'],IDS['f1']))
    rejected(conn,'closing current','UPDATE v24_cordis.episodes SET closed_at=now() WHERE id=%s',(IDS['e1'],))
    # E1 closes, E2-new opens, and history continues to reference E1. Deferred guards see final state.
    with conn.cursor() as c:
        c.execute('UPDATE v24_cordis.fibers SET current_episode_id=%s WHERE id=%s',(IDS['e1'],IDS['f1']))
        c.execute('UPDATE v24_cordis.episodes SET closed_at=now() WHERE id=%s',(IDS['e1'],))
        fresh=uuid.uuid4()
        c.execute("INSERT INTO v24_cordis.episodes(id,fiber_id,epoch,state) VALUES(%s,%s,2,'active')",(fresh,IDS['f1']))
        c.execute('UPDATE v24_cordis.fibers SET current_episode_id=%s WHERE id=%s',(fresh,IDS['f1']))
    conn.commit()
    clone(conn,'installs',IDS['i1'],{'identity':'historical-owner','owner_fiber_id':IDS['f1'],'owner_episode_id':IDS['e1']})
    clone(conn,'fibers',IDS['f2'],{'owner_id':IDS['f1'],'owner_episode_id':IDS['e1']})
    print('[CDP1-D2] cross-episode FKs, current/history, pin XOR/epoch, partial uniqueness')


def effects(conn):
    for status in ('ready','claimed','succeeded','failed','unknown','cancelled'):
        terminal=status in ('succeeded','failed','unknown','cancelled')
        receipt=status in ('succeeded','failed','unknown')
        base={'status':status,'outcome':{} if receipt else None,'settled_at':'2026-01-01' if terminal else None,
              'claim_owner':'seed' if status=='claimed' else None,'lease_until':'infinity' if status=='claimed' else None}
        clone(conn,'effects',IDS['effect'],base)
        clone(conn,'effects',IDS['effect'],{**base,'outcome':None if receipt else {}},status+' outcome truth')
        clone(conn,'effects',IDS['effect'],{**base,'settled_at':None if terminal else '2026-01-01'},status+' settled truth')
        clone(conn,'effects',IDS['effect'],{**base,'claim_owner':None if status=='claimed' else 'residue'},status+' owner truth')
        clone(conn,'effects',IDS['effect'],{**base,'lease_until':None if status=='claimed' else 'infinity'},status+' lease truth')
    for change in ({'ordinal':0},{'parent_id':IDS['effect']},{'parent_id':IDS['effect'],'ordinal':16},{'attempt':-1},{'fence':1},{'episode_id':IDS['e1']}):
        clone(conn,'effects',IDS['effect'],change,'effect local check')
    child={'parent_id':IDS['effect'],'ordinal':0}
    clone(conn,'effects',IDS['effect'],child)
    clone(conn,'effects',IDS['effect'],child,'child ordinal unique','23505')
    for change in ({'kind':'model_call','run_id':IDS['run']},{'kind':'command_reconcile','fiber_id':IDS['f1']}):
        clone(conn,'effects',IDS['effect'],change)
        clone(conn,'effects',IDS['effect'],change,'inflight unique','23505')
    print('[CDP1-D3] six-state outcome/settled/owner/lease truth table and bounded ordinals')


def guards(conn):
    for table,base,change in [('installs',IDS['i1'],"contracts='{}'::jsonb || '{\"changed\":true}'"),
                              ('fibers',IDS['f1'],'scope_id=NULL'),('episodes',IDS['e1'],'epoch=9'),
                              ('contributions',IDS['c1'],"inverse='{\"op\":\"unknown\",\"debt\":\"x\"}'"),
                              ('pins',IDS['pin'],'provider_epoch=1'),('runs',IDS['run'],'scope_id=NULL'),
                              ('effects',IDS['effect'],"input='{\"x\":1}'")]:
        rejected(conn,table+' immutable',f'UPDATE v24_cordis.{table} SET {change} WHERE id=%s',(base,),states=('55000',))
    for table,base,field in [('scopes',IDS['s1'],'closed_at'),('fibers',IDS['f2'],'dispose_requested_at'),('fibers',IDS['f2'],'disposed_at'),('pins',IDS['pin'],'released_at')]:
        with conn.cursor() as c: c.execute(f'UPDATE v24_cordis.{table} SET {field}=now() WHERE id=%s',(base,))
        conn.commit()
        rejected(conn,field+' tombstone',f'UPDATE v24_cordis.{table} SET {field}=NULL WHERE id=%s',(base,),states=('55000',))
    with conn.cursor() as c:
        c.execute('UPDATE v24_cordis.effects SET attempt=2,fence=2 WHERE id=%s',(IDS['effect'],))
        c.execute('UPDATE v24_cordis.fibers SET control_seq=2 WHERE id=%s',(IDS['f1'],))
        c.execute('UPDATE v24_cordis.contributions SET withdrawn_at=now(),released_at=now() WHERE id=%s',(IDS['c2'],))
    conn.commit()
    for field in ('attempt','fence'):
        rejected(conn,field+' monotonic',f'UPDATE v24_cordis.effects SET {field}=1 WHERE id=%s',(IDS['effect'],))
    rejected(conn,'control monotonic','UPDATE v24_cordis.fibers SET control_seq=1 WHERE id=%s',(IDS['f1'],))
    rejected(conn,'withdraw tombstone','UPDATE v24_cordis.contributions SET withdrawn_at=NULL WHERE id=%s',(IDS['c2'],),states=('55000',))
    ident=uuid.uuid4()
    rejected(conn,'scope self cycle','INSERT INTO v24_cordis.scopes(id,parent_id) VALUES(%s,%s)',(ident,ident))
    # A multi-row insert can close a cycle despite an ordinary FK; the trigger rejects it.
    a,b=uuid.uuid4(),uuid.uuid4()
    rejected(conn,'scope two-node cycle','INSERT INTO v24_cordis.scopes(id,parent_id) VALUES(%s,%s),(%s,%s)',(a,b,b,a),states=('23514','23503'))
    for verb in ('UPDATE v24_cordis.events SET payload=payload','DELETE FROM v24_cordis.events','TRUNCATE v24_cordis.events'):
        rejected(conn,'events append only',verb,states=('55000',))
    event="INSERT INTO v24_cordis.events(event_id,effect_id,seq,entity_type,entity_id,event_kind,payload) VALUES(%s,%s,%s,'fiber',%s,%s,'{}')"
    rejected(conn,'event cursor',event,(uuid.uuid4(),None,0,IDS['f1'],'another'),states=('23505',))
    rejected(conn,'event effect/entity/kind',event,(uuid.uuid4(),IDS['effect'],1,IDS['f1'],'seed'),states=('23505',))
    # Real COMMIT failure, not just SET CONSTRAINTS, followed by full ten-table equality.
    for target in ('events','requests'):
        before=snapshot(conn); conn.commit()
        with conn.cursor() as c:
            if target=='events': c.execute(event,(uuid.uuid4(),uuid.uuid4(),2,IDS['f1'],'missing'))
            else: c.execute("INSERT INTO v24_cordis.requests VALUES(%s,'k','command_install','x',sha256('x'::bytea),%s,'{}',now())",(uuid.uuid4(),uuid.uuid4()))
        try: conn.commit()
        except psycopg2.Error as exc:
            assert exc.pgcode=='23503'; conn.rollback()
        else: raise AssertionError('dangling '+target+' effect committed')
        assert snapshot(conn)==before
    # DP2 W1 terminal receipt guard: one legal ready->succeeded, then no reopen or replacement.
    with conn.cursor() as c:
        c.execute("UPDATE v24_cordis.effects SET status='succeeded',outcome='{\"ok\":1}',settled_at=now(),claim_owner=NULL,lease_until=NULL WHERE id=%s",(IDS['effect'],))
    conn.commit()
    for change in ("status='ready'","outcome='{\"ok\":2}'","settled_at=now()+interval '1 second'",'attempt=attempt+1','attempt=attempt-1','fence=fence+1','fence=fence-1',"claim_owner='reopen'","lease_until=now()+interval '1 second'"):
        rejected(conn,'terminal effect '+change,f'UPDATE v24_cordis.effects SET {change} WHERE id=%s',(IDS['effect'],),states=('55000',))
    print('[CDP1-D4] terminal attempt/fence +1 and -1 -> 55000')
    for status in ('failed','unknown','cancelled'):
        terminal=clone(conn,'effects',IDS['effect'],{'status':status,'outcome':({} if status!='cancelled' else None),'settled_at':'2026-01-01'})
        rejected(conn,status+' reopen',"UPDATE v24_cordis.effects SET status='ready',settled_at=NULL WHERE id=%s",(terminal,),states=('55000',))
        rejected(conn,status+' outcome','UPDATE v24_cordis.effects SET outcome=%s WHERE id=%s',(json.dumps({'x':1}),terminal),states=('55000',))
    principal=uuid.uuid4()
    with conn.cursor() as c:
        c.execute("INSERT INTO v24_cordis.requests(principal_id,request_key,kind,request_bytes,request_digest,effect_id,response) VALUES(%s,'terminal','command_install','x',sha256('x'::bytea),%s,'{}'::jsonb)",(principal,IDS['effect']))
    conn.commit()
    rejected(conn,'request response immutable',"UPDATE v24_cordis.requests SET response='{\"x\":1}' WHERE principal_id=%s AND request_key='terminal'",(principal,),states=('55000',))
    rejected(conn,'committed view immutable',"UPDATE v24_cordis.episodes SET committed_view='{\"k\":1}' WHERE id=%s",(IDS['e1'],),states=('55000',))
    rejected(conn,'second ownerless root',"INSERT INTO v24_cordis.fibers(id,install_id,scope_id) VALUES(%s,%s,%s)",(uuid.uuid4(),IDS['i1'],IDS['s1']))
    rejected(conn,'fiber graph self pin',"INSERT INTO v24_cordis.pins(id,consumer_fiber_id,consumer_episode_id,key,contribution_id,provider_epoch) VALUES(%s,%s,%s,'graph-cycle',%s,0)",(uuid.uuid4(),IDS['f1'],IDS['e1'],IDS['c1']))
    run2=uuid.uuid4()
    with conn.cursor() as c:
        c.execute("INSERT INTO v24_cordis.runs(id,owner_fiber_id,owner_episode_id,scope_id,remaining_steps) VALUES(%s,%s,%s,%s,1)",(run2,IDS['f1'],IDS['e1'],IDS['s1']))
    conn.commit()
    rejected(conn,'fiber graph run pin',"INSERT INTO v24_cordis.pins(id,consumer_run_id,key,contribution_id,provider_epoch) VALUES(%s,%s,'graph-run-cycle',%s,0)",(uuid.uuid4(),run2,IDS['c1']))
    print('[CDP1-D4] immutable identities, monotonic values, terminal receipts, append-only events, real COMMIT FK rollback')


def main():
    with Server() as server, TestDB(server) as db:
        assert db.assert_catalog()==TABLES
        with contextlib.closing(db.connect('owner')) as conn:
            catalog(conn); seed(conn); relations(conn); effects(conn); guards(conn)
    print(f'[passed] CDP1-D ({COUNT} zero-write negative probes plus positive/COMMIT cases)')

if __name__=='__main__': main()
