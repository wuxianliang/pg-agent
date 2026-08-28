"""Create agent_v5_prompt_taxonomy and load kernel + taxonomy overlay."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server import get_server
from v5.load import load_stage, psql_has_row, run_psql

DB = "agent_v5_prompt_taxonomy"
STAGE = "prompt_taxonomy"


def main() -> int:
    server = get_server()
    run_psql(server, "postgres", f"DROP DATABASE IF EXISTS {DB} WITH (FORCE);")
    run_psql(server, "postgres", f"CREATE DATABASE {DB};")
    print(f"[created] {DB}")
    run_psql(server, DB, "CREATE EXTENSION IF NOT EXISTS vector;")
    load_stage(server, DB, STAGE)
    print("\n=== 验证 ===")
    ok = True
    for name, sql in [
        ("apply_queue_result", "SELECT 1 FROM pg_proc WHERE proname='apply_queue_result'"),
        ("refresh_plugins", "SELECT 1 FROM pg_proc WHERE proname='refresh_plugins'"),
        ("prompt_slot allowed",
         "SELECT 1 FROM pg_constraint WHERE conname='plugin_bindings_binding_type_check'"),
    ]:
        out = run_psql(server, DB, sql + ";")
        found = psql_has_row(out)
        print(f"  {DB}.{name}: {'✓' if found else '✗'}  {out.strip()[:80]!r}")
        ok = ok and found
    print("\n全部就绪" if ok else "\n有缺失对象！")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
