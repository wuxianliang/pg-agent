"""Create agent_v4_queue_kinds and load W1–W3 overlay. Own DB only."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server import get_server
from v4.load import load_stage, psql_has_row, run_psql

DB = "agent_v4_queue_kinds"
STAGE = "queue_kinds"


def main() -> int:
    server = get_server()
    run_psql(server, "postgres", f"DROP DATABASE IF EXISTS {DB} WITH (FORCE);")
    run_psql(server, "postgres", f"CREATE DATABASE {DB};")
    print(f"[created] {DB}")

    vec = run_psql(server, DB, "CREATE EXTENSION IF NOT EXISTS vector;")
    print(f"[vector ] CREATE EXTENSION vector: {vec.strip() or 'OK'}")
    vec_ok = run_psql(server, DB, "SELECT extname FROM pg_extension WHERE extname='vector';")
    if "vector" not in vec_ok:
        print("STOP: pgvector is not available; do not continue W3. Follow pgembed checklist.")
        return 1

    load_stage(server, DB, STAGE)

    print("\n=== 验证 ===")
    ok = True
    checks = [
        ("vector", "SELECT extname FROM pg_extension WHERE extname='vector'"),
        ("embed_requests", "SELECT queue_name FROM pgmq.meta WHERE queue_name='embed_requests'"),
        ("embed_requests_dlq", "SELECT queue_name FROM pgmq.meta WHERE queue_name='embed_requests_dlq'"),
        ("sql_heavy_requests", "SELECT queue_name FROM pgmq.meta WHERE queue_name='sql_heavy_requests'"),
        ("sql_heavy_requests_dlq", "SELECT queue_name FROM pgmq.meta WHERE queue_name='sql_heavy_requests_dlq'"),
        ("human_inbox", "SELECT queue_name FROM pgmq.meta WHERE queue_name='human_inbox'"),
        ("human_inbox_dlq", "SELECT queue_name FROM pgmq.meta WHERE queue_name='human_inbox_dlq'"),
        ("human_requests", "SELECT 1 FROM pg_class WHERE relname='human_requests'"),
        ("wb_request_embedding", "SELECT 1 FROM pg_proc WHERE proname='wb_request_embedding'"),
        ("wb_request_sql_heavy", "SELECT 1 FROM pg_proc WHERE proname='wb_request_sql_heavy'"),
        ("wb_request_human", "SELECT 1 FROM pg_proc WHERE proname='wb_request_human'"),
        ("queue_handler count",
         "SELECT count(*) FROM plugin_bindings WHERE binding_type='queue_handler'"),
        ("async tools",
         "SELECT count(*) FROM plugin_bindings WHERE binding_type='llm_tool' "
         "AND (metadata->'llm_tool'->>'async')::boolean"),
    ]
    for name, sql in checks:
        out = run_psql(server, DB, sql + ";")
        if name == "queue_handler count":
            found = bool(re.search(r"\n\s*4\s*\n", out))
        elif name == "async tools":
            found = bool(re.search(r"\n\s*3\s*\n", out))
        else:
            found = psql_has_row(out) or name.split("_")[0] in out
        print(f"  {DB}.{name}: {'✓' if found else '✗ MISSING'}  {out.strip()[:90]!r}")
        ok = ok and found
    print("\n全部就绪" if ok else "\n有缺失对象！")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
