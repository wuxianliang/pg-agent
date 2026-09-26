"""Create the isolated v13 characterize database and load through characterize.

Hard fail-closed if the text-search extension is not in pg_available_extensions.
"""
from __future__ import annotations

import sys
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server import get_server
from v13.load import load_stage, run_psql
from v13.resolve.setup_db import run_probes

DB = "agent_v13_characterize"
STAGE = "characterize"

# Deployment ACL (DP5 部署面，蓝本=filter setup_db；E-DP5-2 授权):
# 角色对 stannum.full_score 有 PUBLIC EXECUTE，但 engine schema 无 USAGE、
# 其内部 score_bound/score_bound_indexed 带 owner-only ACL——角色身份执行
# 的引擎限定调用(recall 链)会 42501。授予放部署面(setup_db,run_probes
# 同位)，不进 SQL 文件(R 组扫描断言「9 号 stannum. 恰 3」封死 SQL 内授权)。
GRANTS = """
GRANT USAGE ON SCHEMA stannum TO v13_recall, v13_resolve, v13_route;
GRANT EXECUTE ON FUNCTION
  stannum.score_bound(text,text,integer,integer,integer,real,real,real,text[],text[]),
  stannum.score_bound_indexed(tid,text,integer,integer,integer,real,real,real,text[],text[]),
  stannum.tokenize(text,text,text,text,text,integer,text,text)
TO v13_recall, v13_resolve, v13_route;
"""


def probe_extension(server) -> None:
    conn = psycopg2.connect(server.get_uri("postgres"))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM pg_available_extensions WHERE name='stannum'")
        row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        print("[fail] text-search extension not in pg_available_extensions")
        print("rollback: leave characterize unloaded; T0 tsvector remains")
        raise SystemExit(1)


def main() -> int:
    s = get_server()
    probe_extension(s)
    run_psql(s, "postgres", f"DROP DATABASE IF EXISTS {DB} WITH (FORCE);")
    run_psql(s, "postgres", f"CREATE DATABASE {DB};")
    load_stage(s, DB, STAGE)
    run_psql(s, DB, GRANTS)
    run_probes(s, DB)
    print("[ready]", DB)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
