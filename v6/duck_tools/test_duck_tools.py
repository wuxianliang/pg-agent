from __future__ import annotations
import json,sys
from pathlib import Path
import psycopg2
ROOT=Path(__file__).resolve().parent; sys.path.insert(0,str(ROOT.parent.parent))
from server import get_server
from v6.duck_tools.setup_db import DB,main as setup_db

def check(n,c,d=''):
 print(f"[{'PASS' if c else 'FAIL'}] {n}"+(f': {d}' if d else ''))
 if not c: raise AssertionError(n)
def main():
 check('setup',setup_db()==0); uri=get_server().get_uri(DB); c=psycopg2.connect(uri); c.autocommit=True
 with c.cursor() as cur:
  cur.execute("SELECT agent_start_session('tools',8,'temp')"); run=cur.fetchone()[0]; cur.execute("SELECT pgmq.purge_queue('llm_requests')")
  cur.execute("SELECT count(*) FROM plugin_bindings WHERE binding_type='llm_tool' AND binding_name LIKE 'wb_duck_%'"); check('seven tools registered',cur.fetchone()[0]==7)
  cur.execute("SELECT set_config('pg_agent.current_run_id',%s,false)",(run,))
  args=json.dumps({'p_brief':'register sales','p_source_id':'agent_db','p_schema_name':'public','p_table_name':'sales','p_view_name':'sales_src'})
  cur.execute("SELECT invoke_named_llm_tool('wb_duck_register',%s)",(args,)); env=cur.fetchone()[0]; nested=env['data'][0]['wb_duck_register']
  check('named envelope success',env['success'] and nested['defer'],env)
  check('wait shape',nested['queue']=='duck_heavy_requests' and nested['wait_kind']=='duck_heavy',nested)
  cur.execute("SELECT status,op_kind,artifact_name FROM duck_operations WHERE request_id=%s",(nested['request_id'],)); check('operation queued',cur.fetchone()==('QUEUED','register','sales_src'))
  cur.execute("SELECT count(*) FROM pgmq.q_duck_heavy_requests WHERE msg_id=%s",(nested['msg_id'],)); check('message queued',cur.fetchone()[0]==1)
  cur.execute("SELECT invoke_named_llm_tool('wb_duck_query',%s)",(json.dumps({'p_brief':'bad','p_view_name':'bad-name','p_query':'SELECT 1'}),)); bad=cur.fetchone()[0]['data'][0]['wb_duck_query']; check('invalid args do not defer',not bad['success'],bad)
  cur.execute("SELECT count(*) FROM duck_operations"); check('invalid args create no operation',cur.fetchone()[0]==1)
  cur.execute("SELECT set_config('pg_agent.current_run_id','',false)")
  cur.execute("SELECT wb_duck_list('list')"); check('no current run rejected',not cur.fetchone()[0]['success'])
 c.close(); print('[W6] all gates passed'); return 0
if __name__=='__main__': raise SystemExit(main())
