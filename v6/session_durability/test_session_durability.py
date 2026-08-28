"""W4 gate: run isolation, temp loss, and run_schema definition replay."""
from __future__ import annotations
import hashlib, json, sys
from pathlib import Path
import psycopg2
ROOT=Path(__file__).resolve().parent
AGENT_ROOT=ROOT.parent.parent
sys.path.insert(0,str(AGENT_ROOT))
from server import get_server
from v6.session_durability.duckdb_runtime import DuckSessionManager, SessionError
from v6.source_ingress.duckdb_ingress import PostgresSourceResolver, SourceConfig, snapshot_table
from v6.session_durability.setup_db import DB, main as setup_db

def check(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f": {detail}" if detail else ""))
    if not cond: raise AssertionError(f"{label}: {detail}")

def new_run(conn, mode, question):
    with conn.cursor() as cur:
        cur.execute("SELECT agent_start_session(%s,6,%s)",(question,mode)); run=cur.fetchone()[0]
        cur.execute("SELECT pgmq.purge_queue('llm_requests')")
    return run

def save_source(conn, run, name='sales_src'):
    cols=[{"name":"month","pg_type":"text","duck_type":"VARCHAR"},{"name":"revenue","pg_type":"integer","duck_type":"BIGINT"}]
    h=hashlib.sha256(b"agent_db.public.sales").hexdigest()
    with conn.cursor() as cur:
        cur.execute("INSERT INTO duck_artifacts(run_id,artifact_name,artifact_kind,source_id,source_schema,source_table,columns,definition_hash) VALUES(%s,%s,'source','agent_db','public','sales',%s::jsonb,%s)",(run,name,json.dumps(cols),h))

def save_view(conn, run, name, query, deps):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO duck_artifacts(run_id,artifact_name,artifact_kind,definition_sql,depends_on,definition_hash) VALUES(%s,%s,'view',%s,%s::jsonb,%s)",(run,name,query,json.dumps(deps),hashlib.sha256(query.encode()).hexdigest()))

def main():
    check('setup', setup_db()==0)
    server=get_server(); uri=server.get_uri(DB)
    pg=psycopg2.connect(uri); pg.autocommit=True
    with pg.cursor() as cur:
        cur.execute("CREATE TABLE sales(month text,revenue int)")
        cur.execute("INSERT INTO sales VALUES('2026-01',100),('2026-02',250)")
    resolver=PostgresSourceResolver([SourceConfig('agent_db',uri,frozenset({('public','sales')}))])

    temp_run=new_run(pg,'temp','temp duck session')
    mgr=DuckSessionManager(uri,resolver=resolver)
    mgr.ensure_metadata_session(temp_run,'temp')
    s=mgr.get_or_open(temp_run)
    snapshot_table(s.connection,resolver,source_id='agent_db',schema_name='public',table_name='sales',artifact_name='sales_src')
    s.create_view('monthly','SELECT month,revenue FROM sales_src WHERE revenue>=100')
    s.create_view('summary','SELECT sum(revenue) AS total FROM monthly')
    check('same run chains views',s.connection.execute('SELECT total FROM summary').fetchone()[0]==350)
    check('same run reuses connection',mgr.get_or_open(temp_run) is s)

    other=new_run(pg,'temp','other run'); mgr.ensure_metadata_session(other,'temp'); o=mgr.get_or_open(other)
    try:
        o.connection.execute('SELECT * FROM summary')
        check('cross run isolation',False)
    except Exception as exc: check('cross run isolation','does not exist' in str(exc).lower(),exc)

    mgr.close_run(temp_run,lost=True)
    try:
        mgr.get_or_open(temp_run); check('temp lost fails closed',False)
    except SessionError as exc: check('temp lost fails closed',exc.envelope['Type']=='DUCK_SESSION_LOST',exc.envelope)

    durable=new_run(pg,'run_schema','durable duck session'); mgr.ensure_metadata_session(durable,'run_schema')
    # No metadata yet: first open is a valid empty hydrate.
    d=mgr.get_or_open(durable)
    snapshot_table(d.connection,resolver,source_id='agent_db',schema_name='public',table_name='sales',artifact_name='sales_src')
    d.create_view('monthly','SELECT month,revenue FROM sales_src')
    d.create_view('summary','SELECT sum(revenue) AS total FROM monthly')
    save_source(pg,durable); save_view(pg,durable,'monthly','SELECT month,revenue FROM sales_src',['sales_src']); save_view(pg,durable,'summary','SELECT sum(revenue) AS total FROM monthly',['monthly'])
    check('durable initial result',d.connection.execute('SELECT total FROM summary').fetchone()[0]==350)
    mgr.close_run(durable,lost=True)
    with pg.cursor() as cur: cur.execute("UPDATE sales SET revenue=300 WHERE month='2026-02'")
    mgr2=DuckSessionManager(uri,worker_id='v6-worker-2',resolver=resolver)
    d2=mgr2.get_or_open(durable)
    check('run_schema rehydrates definitions',d2.connection.execute('SELECT total FROM summary').fetchone()[0]==400)
    with pg.cursor() as cur:
        cur.execute("SELECT session_generation,status FROM duck_workbench_sessions WHERE run_id=%s",(durable,)); gen,status=cur.fetchone()
        cur.execute("SELECT count(*) FROM duck_artifacts WHERE run_id=%s",(durable,)); artifacts=cur.fetchone()[0]
    check('rehydration increments generation',gen>=2,gen)
    check('rehydrated status OPEN',status=='OPEN',status)
    check('metadata stores definitions only',artifacts==3,artifacts)

    child=new_run(pg,'run_schema','child run')
    mgr2.ensure_metadata_session(child,'run_schema'); child_s=mgr2.get_or_open(child)
    try:
        child_s.connection.execute('SELECT * FROM summary'); check('child does not inherit artifacts',False)
    except Exception as exc: check('child does not inherit artifacts','does not exist' in str(exc).lower(),exc)

    mgr.close_run(other,lost=False); mgr2.close_run(durable,lost=False); mgr2.close_run(child,lost=False); pg.close()
    print('[W4] all gates passed'); return 0
if __name__=='__main__': raise SystemExit(main())
