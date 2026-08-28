from __future__ import annotations
import datetime as dt, decimal, json, math, sys, uuid, hashlib
from pathlib import Path
import duckdb, psycopg2
ROOT=Path(__file__).resolve().parent; sys.path.insert(0,str(ROOT.parent.parent))
from server import get_server
from v6.budget_observability.setup_db import DB,main as setup_db
from v6.budget_observability.duckdb_results import bounded_result,json_safe
from v6.budget_observability.duckdb_errors import error_envelope
from v6.queue_bridge.duckdb_processor import DuckDBWorkerProcessor

def check(n,c,d=''):
 print(f"[{'PASS' if c else 'FAIL'}] {n}"+(f': {d}' if d else ''))
 if not c: raise AssertionError(n)
def main():
 check('setup',setup_db()==0)
 values=[None,True,1,1.5,float('inf'),decimal.Decimal('1.20'),dt.date(2026,8,28),uuid.UUID(int=0),b'abc',[decimal.Decimal('2')]]
 converted=[json_safe(v) for v in values]; check('JSON safe conversion',converted[0] is None and converted[4]=='inf' and converted[5]=='1.20' and converted[8]=='YWJj',converted)
 result=bounded_result(['x'],[(i,) for i in range(5)],limit=3); check('limit+1 bounded preview',result['row_count']==3 and result['truncated'] and len(result['data'])==3,result)
 huge=bounded_result(['x'],[('x'*100000,) for _ in range(10)],limit=10); check('result summary capped',len(json.dumps(huge,ensure_ascii=False).encode())<=256*1024 and huge.get('result_truncated_by_bytes'),len(json.dumps(huge).encode()))
 exc=RuntimeError('failed postgres://user:password@localhost/db password=sekret token=abc'); env=error_envelope(exc); text=json.dumps(env); check('error redaction','password' not in text.lower() and 'sekret' not in text and 'postgres://' not in text,env)
 uri=get_server().get_uri(DB); c=psycopg2.connect(uri); c.autocommit=True
 with c.cursor() as cur:
  cur.execute("SELECT agent_start_session('timeout',8,'temp')"); run=cur.fetchone()[0]; cur.execute("SELECT pgmq.purge_queue('llm_requests')"); cur.execute("INSERT INTO duck_workbench_sessions(run_id,session_mode) VALUES(%s,'temp') ON CONFLICT DO NOTHING",(run,))
  body={'brief':'timeout','artifact_name':'slow','query':'SELECT sum(i) FROM range(1000000000000) t(i)','timeout_ms':10,'depends_on':[]}
  rid=str(uuid.uuid4()); h=hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest(); cur.execute("INSERT INTO duck_operations(request_id,run_id,op_seq,op_kind,artifact_name,request_payload) VALUES(%s,%s,1,'query','slow',%s::jsonb)",(rid,run,json.dumps(body))); 
 proc=DuckDBWorkerProcessor(uri); out=proc.process({'run_id':run,'request_id':rid,'op_seq':1,'op_kind':'query','payload_hash':h,**body}); check('timeout returns structured result',out.get('Type')=='DUCK_TIMEOUT',out)
 con=proc.sessions.sessions.get(run); check('timeout leaves no session view',con is None or con.connection.execute("SELECT count(*) FROM duckdb_views() WHERE view_name='slow'").fetchone()[0]==0)
 proc.close(); c.close(); print('[W8] all gates passed'); return 0
if __name__=='__main__': raise SystemExit(main())
