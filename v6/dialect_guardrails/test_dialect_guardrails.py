from __future__ import annotations
import sys
from pathlib import Path
import duckdb, psycopg2
ROOT=Path(__file__).resolve().parent; sys.path.insert(0,str(ROOT.parent.parent))
from server import get_server
from v6.dialect_guardrails.duckdb_validation import QueryValidationError,validate_read_query
from v6.dialect_guardrails.setup_db import DB,main as setup_db

def check(n,c,d=''):
 print(f"[{'PASS' if c else 'FAIL'}] {n}"+(f': {d}' if d else ''))
 if not c: raise AssertionError(n)
def expect(t,fn):
 try: fn()
 except QueryValidationError as e: check(t,e.envelope['Type'] in {'DUCK_READ_ONLY_VIOLATION','DUCK_EXTERNAL_ACCESS_FORBIDDEN','DUCK_PARSE_ERROR'},e.envelope); return
 raise AssertionError('expected '+t)
def main():
 check('setup',setup_db()==0)
 c=duckdb.connect(); c.execute('create table t(x int, y int)'); c.execute('insert into t values (1,10),(2,20)')
 for label,q in [('select','SELECT x FROM t'),('cte','WITH q AS (SELECT * FROM t) SELECT * FROM q'),('from-first','FROM t SELECT x LIMIT 1'),('qualify','SELECT x,row_number() over(order by x) rn FROM t QUALIFY rn=1')]:
  v=validate_read_query(q,c); check(label,v.statement_type.endswith('SELECT'))
 for label,q in [('dml cte','WITH x AS (INSERT INTO t VALUES (3,30) RETURNING *) SELECT * FROM x'),('copy cte','WITH x AS (COPY (SELECT 1) TO \'/tmp/v6-copy\') SELECT 1'),('ddl','CREATE TABLE bad(x int)'),('attach','ATTACH \'x.db\' AS x'),('postgres','SELECT * FROM postgres_scan(\'x\')'),('file','SELECT * FROM read_csv_auto(\'x.csv\')'),('pragma','PRAGMA show_tables'),('pivot expansion','PIVOT t ON x USING sum(y)')]: expect(label,lambda q=q:validate_read_query(q,c))
 check('keyword in string allowed',validate_read_query("SELECT 'INSERT;PIVOT' AS text_value FROM t",c).statement_type.endswith('SELECT'))
 check('keyword in comment allowed',validate_read_query('SELECT x FROM t -- DROP TABLE t\n',c).statement_type.endswith('SELECT'))
 check('quoted identifier allowed',validate_read_query('SELECT "DROP" FROM (SELECT 1 AS "DROP")',c).statement_type.endswith('SELECT'))
 pg=psycopg2.connect(get_server().get_uri(DB)); pg.autocommit=True
 with pg.cursor() as cur:
  cur.execute("SELECT count(*) FROM prompt_recipes WHERE recipe_name='agent_system' AND version=3 AND active"); check('agent_system v3 active',cur.fetchone()[0]==1)
  cur.execute("SELECT value FROM prompt_parts WHERE recipe_name='agent_system' AND recipe_version=3 AND slot_key='task'"); row=cur.fetchone(); check('DuckDB guidance in recipe',row is not None and 'wb_duck_register' in str(row[0]))
 pg.close(); c.close(); print('[W7] all gates passed'); return 0
if __name__=='__main__': raise SystemExit(main())
