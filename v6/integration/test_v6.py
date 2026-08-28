"""W9 core integration: PostgreSQL source -> DuckDB views -> chained analysis."""
from __future__ import annotations
import hashlib,json,re,sys
from pathlib import Path
import psycopg2
ROOT=Path(__file__).resolve().parent; AGENT_ROOT=ROOT.parent.parent
sys.path.insert(0,str(AGENT_ROOT))
from server import get_server
from v6.integration.setup_db import DB,main as setup_db
from v6.queue_bridge.duckdb_processor import DuckDBWorkerProcessor
from v6.source_ingress.duckdb_ingress import PostgresSourceResolver,SourceConfig
from v6.load import SQL_LOAD_ORDER

def check(n,c,d=''):
 print(f"[{'PASS' if c else 'FAIL'}] {n}"+(f': {d}' if d else ''))
 if not c: raise AssertionError(f'{n}: {d}')
def main():
 check('setup',setup_db()==0); server=get_server(); uri=server.get_uri(DB)
 c=psycopg2.connect(uri); c.autocommit=True
 with c.cursor() as cur:
  cur.execute('CREATE TABLE sales(month text,segment text,revenue int)')
  cur.execute("INSERT INTO sales VALUES('2026-01','North',100),('2026-01','South',200),('2026-02','South',250)")
  cur.execute("SELECT agent_start_session('South revenue',10,'temp')"); run=cur.fetchone()[0]
  cur.execute("SELECT pgmq.purge_queue('llm_requests')")
 resolver=PostgresSourceResolver([SourceConfig('agent_db',uri,frozenset({('public','sales')}))])
 worker=DuckDBWorkerProcessor(uri,resolver=resolver)
 def tool(action,args):
  with c.cursor() as cur:
   cur.execute("SELECT set_config('pg_agent.current_run_id',%s,false)",(run,))
   cur.execute('SELECT invoke_named_llm_tool(%s,%s)',(action,json.dumps(args)))
   env=cur.fetchone()[0]; nested=env['data'][0][action]
  check(action+' named envelope',env['success'] and nested['defer'],env)
  with c.cursor() as cur:
   cur.execute("SELECT message FROM pgmq.read('duck_heavy_requests',60,1)"); row=cur.fetchone(); check(action+' queue message',row is not None)
  msg=json.loads(row[0]) if isinstance(row[0],str) else row[0]
  result=worker.process(msg); check(action+' worker success',result.get('success') is True,result)
  with c.cursor() as cur:
   cur.execute("SELECT apply_queue_result('duck_heavy_requests',%s,%s,%s::jsonb)",(nested['msg_id'],run,json.dumps(result,default=str))); applied=cur.fetchone()[0]
   cur.execute("SELECT pgmq.purge_queue('llm_requests')")
  check(action+' apply result',applied is not None,applied); return result
 register=tool('wb_duck_register',{'p_brief':'读取销售表','p_source_id':'agent_db','p_schema_name':'public','p_table_name':'sales','p_view_name':'sales_src'})
 check('registered source rows',register['row_count']==3,register)
 query=tool('wb_duck_query',{'p_brief':'筛选 South','p_view_name':'south_sales','p_query':"SELECT month,revenue FROM sales_src WHERE segment='South'"})
 check('named view preview',query['row_count']==2,query)
 summary=tool('wb_duck_query',{'p_brief':'汇总 South','p_view_name':'south_total','p_query':'SELECT sum(revenue) AS total FROM south_sales'})
 check('chained analysis total',summary['data']==[[450]],summary)
 brief=tool('wb_duck_brief_query',{'p_brief':'预览汇总','p_view_name':'south_total','p_limit':1})
 check('brief query bounded',brief['row_count']==1 and brief['data']==[[450]],brief)
 listing=tool('wb_duck_list',{'p_brief':'列出工作台'})
 check('list returns success',listing['success'] is True,listing)
 cols=tool('wb_duck_columns',{'p_brief':'查看列','p_view_name':'south_total'})
 check('columns returns success',cols['success'] is True,cols)
 shown=tool('wb_duck_show_create',{'p_brief':'查看定义','p_view_name':'south_total'})
 check('show create returns success',shown['success'] is True,shown)
 with c.cursor() as cur:
  cur.execute("SELECT count(*) FROM duck_artifacts WHERE run_id=%s AND artifact_name='south_sales' AND depends_on ? 'sales_src'",(run,)); check('dependency metadata recorded',cur.fetchone()[0]==1)
 # Drop guard before execution.
 with c.cursor() as cur:
  cur.execute("SELECT set_config('pg_agent.current_run_id',%s,false)",(run,)); cur.execute("SELECT wb_duck_drop('删源','sales_src')"); blocked=cur.fetchone()[0]
 check('dependent drop blocked',blocked['Type']=='DUCK_DEPENDENCY_EXISTS',blocked)
 tool('wb_duck_drop',{'p_brief':'删汇总','p_view_name':'south_total'})
 tool('wb_duck_drop',{'p_brief':'删筛选','p_view_name':'south_sales'})
 tool('wb_duck_drop',{'p_brief':'删源','p_view_name':'sales_src'})
 with c.cursor() as cur:
  cur.execute("SELECT count(*) FROM duck_artifacts WHERE run_id=%s AND artifact_status='ACTIVE'",(run,)); check('all artifacts dropped',cur.fetchone()[0]==0)
  cur.execute("SELECT count(*) FROM plugin_bindings WHERE binding_type='llm_tool' AND binding_name LIKE 'wb_duck_%'"); check('v6 tools remain registered',cur.fetchone()[0]==7)
 check('loader inherited prefix intact',len(SQL_LOAD_ORDER)>=17 and all('/v6/' not in str(p) for p in SQL_LOAD_ORDER[:17]))
 worker.close(); c.close(); print('[W9] all gates passed'); return 0
if __name__=='__main__': raise SystemExit(main())
