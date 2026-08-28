"""Create agent_v5_integration and load the full v5 stack."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server import get_server
from v5.load import load_stage, psql_has_row, run_psql

DB = "agent_v5_integration"
STAGE = "integration"


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
        ("assemble", "SELECT 1 FROM pg_proc WHERE proname='assemble_prompt_messages'"),
        ("named tools", "SELECT 1 FROM pg_proc WHERE proname='invoke_named_llm_tool'"),
        ("store part", "SELECT 1 FROM pg_proc WHERE proname='wb_store_prompt_part'"),
        ("bootstrap",
         "SELECT 1 FROM prompt_recipes WHERE recipe_name='agent_system_generate' AND active"),
        ("agent_system v2",
         "SELECT 1 FROM prompt_recipes WHERE recipe_name='agent_system' AND version=2 AND active"),
    ]:
        out = run_psql(server, DB, sql + ";")
        found = psql_has_row(out)
        print(f"  {DB}.{name}: {'✓' if found else '✗'}  {out.strip()[:80]!r}")
        ok = ok and found
    print("\n全部就绪" if ok else "\n有缺失对象！")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
