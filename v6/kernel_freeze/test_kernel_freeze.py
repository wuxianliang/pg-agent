"""W1 gate: v6 loads v5's inherited SQL by path and keeps the generic runtime seam."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
V6_ROOT = ROOT.parent
AGENT_ROOT = V6_ROOT.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v6.kernel_freeze.setup_db import DB, main as setup_db
from v6.load import SQL_LOAD_ORDER


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f": {detail}" if detail else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def relative_paths(paths: list[Path]) -> list[str]:
    return [str(p.relative_to(AGENT_ROOT)) for p in paths]


def main() -> int:
    print("[W1] creating isolated database")
    check("setup_db succeeds", setup_db() == 0)

    v5_order = (AGENT_ROOT / "v5" / "load.py").read_text()
    v6_order = (V6_ROOT / "load.py").read_text()
    check("v6 inherited prefix has 17 entries", len(SQL_LOAD_ORDER[:17]) == 17)
    check("v6 loader has no runtime v5 import", not re.search(r"^\s*(from|import)\s+v5\b", v6_order, re.M))
    check("v6 loader has no runtime v4 import", not re.search(r"^\s*(from|import)\s+v4\b", v6_order, re.M))
    check("kernel_freeze contains no copied SQL", not list(ROOT.glob("**/*.sql")))
    check("v5 loader remains unchanged by v6", "The first 17 entries" not in v5_order)
    check("all inherited paths exist", all(p.exists() for p in SQL_LOAD_ORDER), relative_paths(SQL_LOAD_ORDER))

    uri = get_server().get_uri(DB)
    import psycopg2
    conn = psycopg2.connect(uri)
    try:
        with conn.cursor() as cur:
            checks = {
                "pgmq extension": "SELECT 1 FROM pg_extension WHERE extname='pgmq'",
                "generic apply": "SELECT 1 FROM pg_proc WHERE proname='apply_queue_result'",
                "LLM apply": "SELECT 1 FROM pg_proc WHERE proname='apply_llm_response'",
                "prompt assembly": "SELECT 1 FROM pg_proc WHERE proname='assemble_prompt_messages'",
                "named tool dispatch": "SELECT 1 FROM pg_proc WHERE proname='invoke_named_llm_tool'",
                "visible prompt store": "SELECT 1 FROM pg_proc WHERE proname='wb_store_prompt_part'",
                "session entry": "SELECT 1 FROM pg_proc WHERE proname='agent_start_session'",
            }
            for label, sql in checks.items():
                cur.execute(sql)
                check(label, cur.fetchone() is not None)

            try:
                cur.execute("SELECT http_call_llm('[]'::jsonb)")
                check("SQL-side HTTP is forbidden", False, "call unexpectedly succeeded")
            except Exception as exc:
                conn.rollback()
                check("SQL-side HTTP is forbidden", "v4 forbids SQL-side model HTTP" in str(exc), exc)

            cur.execute("SELECT 1 FROM information_schema.tables WHERE table_name='plugin_bindings'")
            check("plugin registry exists", cur.fetchone() is not None)
    finally:
        conn.close()

    status = subprocess.run(
        ["git", "status", "--porcelain", "--", "v1", "v2", "v3", "v4", "v5"],
        cwd=str(AGENT_ROOT), capture_output=True, text=True, check=False,
    )
    # Existing worktree changes are not ours; W1 does not add or edit old files.
    print("[INFO] existing old-version worktree status kept untouched")
    print(status.stdout.strip() or "[INFO] no old-version status output")
    print("[W1] all gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
