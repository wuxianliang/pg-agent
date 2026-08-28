"""Create agent_v5_recipe_components and load through W3."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server import get_server
from v5.load import load_stage, psql_has_row, run_psql

DB = "agent_v5_recipe_components"
STAGE = "recipe_components"


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
        ("prompt_recipes", "SELECT 1 FROM pg_class WHERE relname='prompt_recipes'"),
        ("prompt_slots", "SELECT 1 FROM pg_class WHERE relname='prompt_slots'"),
        ("prompt_parts", "SELECT 1 FROM pg_class WHERE relname='prompt_parts'"),
        ("compile_prompt_recipe", "SELECT 1 FROM pg_proc WHERE proname='compile_prompt_recipe'"),
        ("prompt_stored_part", "SELECT 1 FROM pg_proc WHERE proname='prompt_stored_part'"),
        ("active recipe",
         "SELECT 1 FROM prompt_recipes WHERE recipe_name='agent_system' AND active"),
        ("prompt_slot bindings",
         "SELECT 1 FROM plugin_bindings WHERE binding_type='prompt_slot' LIMIT 1"),
    ]:
        out = run_psql(server, DB, sql + ";")
        found = psql_has_row(out)
        print(f"  {DB}.{name}: {'✓' if found else '✗'}  {out.strip()[:80]!r}")
        ok = ok and found
    print("\n全部就绪" if ok else "\n有缺失对象！")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
