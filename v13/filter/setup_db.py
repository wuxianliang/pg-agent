"""Create the isolated v13 filter database and load through filter."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server import get_server
from v13.load import load_stage, run_psql
from v13.resolve.setup_db import run_probes

DB = "agent_v13_filter"
STAGE = "filter"

# Deployment ACL (DP5 characterize 面缺口,本 stage 补授;README 台账 #7):
# 角色对 stannum.full_score 有 PUBLIC EXECUTE,但 engine schema 无 USAGE、
# 其内部 score_bound/score_bound_indexed 带显式 owner-only ACL——角色身份
# 执行的动态引擎限定调用(trace→recall_candidates→recall 链)会 42501。
# 计划 H1 的 ACL 矩阵要求这些链在角色下可执行;H6 要求第 10 号 SQL 文件
# 零引擎限定名(零引擎依赖),故授予放部署面(setup_db,run_probes 同位),
# 不进 SQL 文件。
GRANTS = """
GRANT USAGE ON SCHEMA stannum TO v13_recall, v13_resolve, v13_route;
GRANT EXECUTE ON FUNCTION
  stannum.score_bound(text,text,integer,integer,integer,real,real,real,text[],text[]),
  stannum.score_bound_indexed(tid,text,integer,integer,integer,real,real,real,text[],text[])
TO v13_recall, v13_resolve, v13_route;
"""


def main() -> int:
    s = get_server()
    run_psql(s, "postgres", f"DROP DATABASE IF EXISTS {DB} WITH (FORCE);")
    run_psql(s, "postgres", f"CREATE DATABASE {DB};")
    load_stage(s, DB, STAGE)
    run_psql(s, DB, GRANTS)
    run_probes(s, DB)
    print("[ready]", DB)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
