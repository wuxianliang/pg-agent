"""Create agent_v4_sticky_workbench and load W1+W2 overlay. Own DB only."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server import get_server
from v4.load import load_stage, psql_has_row, run_psql

DB = "agent_v4_sticky_workbench"
STAGE = "sticky_workbench"


def main() -> int:
    server = get_server()
    run_psql(server, "postgres", f"DROP DATABASE IF EXISTS {DB} WITH (FORCE);")
    run_psql(server, "postgres", f"CREATE DATABASE {DB};")
    print(f"[created] {DB}")
    load_stage(server, DB, STAGE)

    print("\n=== 验证 ===")
    ok = True
    checks = [
        ("pgmq", "SELECT extname FROM pg_extension WHERE extname='pgmq'"),
        ("apply_queue_result", "SELECT 1 FROM pg_proc WHERE proname='apply_queue_result'"),
        ("wb_brief_query", "SELECT 1 FROM pg_proc WHERE proname='wb_brief_query'"),
        ("wb_temp_view_list", "SELECT 1 FROM pg_proc WHERE proname='wb_temp_view_list'"),
        ("wb_temp_view_columns", "SELECT 1 FROM pg_proc WHERE proname='wb_temp_view_columns'"),
        ("wb_temp_view_create", "SELECT 1 FROM pg_proc WHERE proname='wb_temp_view_create'"),
        ("wb_temp_view_drop", "SELECT 1 FROM pg_proc WHERE proname='wb_temp_view_drop'"),
        ("wb_sql_curate", "SELECT 1 FROM pg_proc WHERE proname='wb_sql_curate'"),
        ("llm_tool count",
         "SELECT count(*) FROM plugin_bindings WHERE binding_type='llm_tool'"),
        ("llm_requests binding",
         "SELECT count(*) FROM plugin_bindings "
         "WHERE binding_type='queue_handler' AND queue_name='llm_requests'"),
    ]
    for name, sql in checks:
        out = run_psql(server, DB, sql + ";")
        if "count" in name:
            found = "6" in out.split("\n")[2] if "llm_tool" in name else psql_has_row(out)
            if name == "llm_tool count":
                found = bool(__import__("re").search(r"\n\s*6\s*\n", out))
            elif name == "llm_requests binding":
                found = bool(__import__("re").search(r"\n\s*1\s*\n", out))
        else:
            found = psql_has_row(out)
        print(f"  {DB}.{name}: {'✓' if found else '✗ MISSING'}  {out.strip()[:80]!r}")
        ok = ok and found
    print("\n全部就绪" if ok else "\n有缺失对象！")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
