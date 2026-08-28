"""W5 gate: DuckDB PGMQ bridge, ordering, idempotency, and DLQ behavior."""
from __future__ import annotations
import hashlib, json, sys, uuid
from pathlib import Path
import duckdb, psycopg2
ROOT=Path(__file__).resolve().parent; AGENT_ROOT=ROOT.parent.parent
sys.path.insert(0,str(AGENT_ROOT))
from server import get_server
from v6.queue_bridge.setup_db import DB, main as setup_db
from v6.queue_bridge.duckdb_processor import DuckDBWorkerProcessor
from v6.kernel_freeze.worker import AgentWorker
from v6.source_ingress.duckdb_ingress import PostgresSourceResolver, SourceConfig

def check(label, cond, detail=''):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f": {detail}" if detail else ''))
    if not cond: raise AssertionError(f'{label}: {detail}')

def payload_hash(body): return hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def make_run(c):
    with c.cursor() as cur:
        cur.execute("SELECT agent_start_session(%s,8,'temp')",('queue bridge',)); run=cur.fetchone()[0]
        cur.execute("SELECT pgmq.purge_queue('llm_requests')")
        cur.execute("SELECT pgmq.purge_queue('duck_heavy_requests')")
        cur.execute("INSERT INTO duck_workbench_sessions(run_id,session_mode) VALUES(%s,'temp') ON CONFLICT DO NOTHING",(run,))
    return run

def op(c,run,seq,kind,body):
    rid=str(uuid.uuid4()); h=payload_hash(body)
    with c.cursor() as cur:
        cur.execute("INSERT INTO duck_operations(request_id,run_id,op_seq,op_kind,artifact_name,request_payload) VALUES(%s,%s,%s,%s,%s,%s::jsonb)",(rid,run,seq,kind,body.get('artifact_name'),json.dumps(body)))
        cur.execute("SELECT pgmq.send('duck_heavy_requests',%s::jsonb)",(json.dumps({'run_id':run,'request_id':rid,'op_seq':seq,'op_kind':kind,'payload_hash':h,**body}),))
        msg=cur.fetchone()[0]
        cur.execute("UPDATE duck_operations SET queue_msg_id=%s WHERE request_id=%s",(msg,rid))
    return rid,msg,h

def main():
    check('setup',setup_db()==0)
    s=get_server(); uri=s.get_uri(DB); c=psycopg2.connect(uri); c.autocommit=True
    with c.cursor() as cur:
        cur.execute('CREATE TABLE sales(month text,revenue int)')
        cur.execute("INSERT INTO sales VALUES('2026-01',100),('2026-02',250)")
    resolver=PostgresSourceResolver([SourceConfig('agent_db',uri,frozenset({('public','sales')}))])
    p=DuckDBWorkerProcessor(uri,resolver=resolver)
    run=make_run(c)
    body1={'source_id':'agent_db','schema_name':'public','table_name':'sales','artifact_name':'sales_src'}
    rid1,msg1,_=op(c,run,1,'register',body1)
    with c.cursor() as cur: cur.execute("SELECT message FROM pgmq.read('duck_heavy_requests',60,1)"); row=cur.fetchone()
    check('queue message readable',row is not None)
    msg=json.loads(row[0]) if isinstance(row[0],str) else row[0]
    result1=p.process(msg)
    check('register processor succeeds',result1.get('success') is True,result1)
    with c.cursor() as cur:
        cur.execute("SELECT apply_queue_result('duck_heavy_requests',%s,%s,%s::jsonb)",(msg1,run,json.dumps(result1,default=str)))
        applied=cur.fetchone()[0]
        cur.execute("SELECT o.status,s.last_completed_op_seq FROM duck_operations o JOIN duck_workbench_sessions s USING(run_id) WHERE o.request_id=%s",(rid1,)); status,last=cur.fetchone()
        cur.execute("SELECT artifact_name FROM duck_artifacts WHERE run_id=%s",(run,)); artifact=cur.fetchone()[0]
    check('generic apply invokes duck handler',applied is not None,applied)
    check('operation succeeds and sequence advances',status=='SUCCEEDED' and last==1,(status,last))
    check('artifact metadata written',artifact=='sales_src',artifact)

    body2={'artifact_name':'monthly','query':'SELECT month,revenue FROM sales_src','depends_on':['sales_src']}
    rid2,msg2,_=op(c,run,2,'query',body2)
    body3={'artifact_name':'summary','query':'SELECT sum(revenue) AS total FROM monthly','depends_on':['monthly']}
    rid3,msg3,_=op(c,run,3,'query',body3)
    out_of_order=p.process({'run_id':run,'request_id':rid3,'op_seq':3,'op_kind':'query','payload_hash':payload_hash(body3),**body3})
    check('op3 before op2 is retryable',out_of_order.get('status')=='retry' and out_of_order.get('retryable'),out_of_order)
    result2=p.process({'run_id':run,'request_id':rid2,'op_seq':2,'op_kind':'query','payload_hash':payload_hash(body2),**body2})
    check('ordered query succeeds',result2.get('success') is True,result2)
    with c.cursor() as cur:
        cur.execute("SELECT apply_queue_result('duck_heavy_requests',%s,%s,%s::jsonb)",(msg2,run,json.dumps(result2,default=str)))
        cur.fetchone()
        cur.execute("SELECT count(*) FROM duck_artifacts WHERE run_id=%s AND artifact_name='monthly'",(run,)); check('query artifact committed',cur.fetchone()[0]==1)
        cur.execute("SELECT apply_queue_result('duck_heavy_requests',%s,%s,%s::jsonb)",(msg2,run,json.dumps(result2,default=str)))
        replay=cur.fetchone()[0]
    check('same message replay is harmless',replay.get('replayed') is True,replay)
    duplicate=p.process({'run_id':run,'request_id':rid2,'op_seq':2,'op_kind':'query','payload_hash':payload_hash(body2),**body2})
    check('same request replay is harmless',duplicate.get('replayed') is True,duplicate)
    result3=p.process({'run_id':run,'request_id':rid3,'op_seq':3,'op_kind':'query','payload_hash':payload_hash(body3),**body3})
    check('next ordered operation succeeds',result3.get('success') is True,result3)

    bad=make_run(c); badbody={'source_id':'missing','schema_name':'public','table_name':'sales','artifact_name':'bad'}; rid3,msg3,_=op(c,bad,1,'register',badbody)
    badmsg={'run_id':bad,'request_id':rid3,'op_seq':1,'op_kind':'register','payload_hash':payload_hash(badbody),**badbody}
    badresult=p.process(badmsg); check('permanent source error structured',badresult.get('Type')=='DUCK_SOURCE_NOT_FOUND',badresult)
    with c.cursor() as cur:
        cur.execute("SELECT apply_queue_result('duck_heavy_requests',%s,%s,%s::jsonb)",(msg3,bad,json.dumps(badresult)))
        cur.fetchone(); cur.execute("SELECT status FROM duck_operations WHERE request_id=%s",(rid3,)); check('failed operation terminal',cur.fetchone()[0]=='FAILED')

    # PostgreSQL apply must independently reject a result that skips op_seq.
    ordered=make_run(c); ob1={'artifact_name':'one','query':'SELECT 1 AS x','depends_on':[]}; or1,om1,_=op(c,ordered,1,'query',ob1)
    ob2={'artifact_name':'two','query':'SELECT 2 AS x','depends_on':[]}; or2,om2,_=op(c,ordered,2,'query',ob2)
    try:
        with c.cursor() as cur:
            cur.execute("SELECT apply_queue_result('duck_heavy_requests',%s,%s,%s::jsonb)",(om2,ordered,json.dumps({'success':True,'request_id':or2,'op_seq':2,'worker_id':'fake'})))
        check('apply rejects out-of-order result',False)
    except Exception as exc:
        check('apply rejects out-of-order result','out of order' in str(exc).lower(),exc)

    # Real AgentWorker path consumes the Duck queue and applies the result.
    actual=make_run(c); abody={'source_id':'agent_db','schema_name':'public','table_name':'sales','artifact_name':'actual_src'}; arid,amsg,_=op(c,actual,1,'register',abody)
    actual_processor=DuckDBWorkerProcessor(uri,resolver=resolver,worker_id='actual-worker')
    aw=AgentWorker(uri,api_uri='http://127.0.0.1/v1',api_key='none',model='mock',poll_queues=('duck_heavy_requests',),duck_processor=actual_processor,db=DB)
    actual_result=aw.pump_once(); check('actual AgentWorker consumes duck queue',actual_result is not None and actual_result.get('request_id')==arid,actual_result)
    with c.cursor() as cur:
        cur.execute("SELECT status FROM duck_operations WHERE request_id=%s",(arid,)); check('actual worker apply succeeds',cur.fetchone()[0]=='SUCCEEDED')
        cur.execute("SELECT pgmq.purge_queue('llm_requests')")
    aw.close()

    # Real max_read_ct DLQ path updates operation status.
    dlq=make_run(c); dlqbody={'artifact_name':'never','query':'SELECT 1','depends_on':[]}; rid4,msg4,_=op(c,dlq,1,'query',dlqbody)
    dw=AgentWorker(uri,api_uri='http://127.0.0.1/v1',api_key='none',model='mock',poll_queues=('duck_heavy_requests',),max_read_ct=0,duck_processor=DuckDBWorkerProcessor(uri,resolver=resolver),db=DB)
    dlq_result=dw.pump_once(); check('real DLQ path fires',dlq_result is not None and dlq_result.get('dead_lettered'),dlq_result)
    with c.cursor() as cur:
        cur.execute("SELECT status FROM duck_operations WHERE request_id=%s",(rid4,)); check('DLQ operation state',cur.fetchone()[0]=='DLQ')
    dw.close()

    # Malformed message is archived into DLQ instead of poisoning the queue.
    with c.cursor() as cur:
        cur.execute("SELECT pgmq.send('duck_heavy_requests','{\"bad\":1}'::jsonb)")
    mw=AgentWorker(uri,api_uri='http://127.0.0.1/v1',api_key='none',model='mock',poll_queues=('duck_heavy_requests',),duck_processor=DuckDBWorkerProcessor(uri,resolver=resolver),db=DB)
    malformed=mw.pump_once(); check('malformed message dead-lettered',malformed is not None and malformed.get('dead_lettered'),malformed)
    mw.close()
    p.close(); c.close(); print('[W5] all gates passed'); return 0
if __name__=='__main__': raise SystemExit(main())
