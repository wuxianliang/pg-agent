"""Create agent_v4_plugin_taxonomy and load W1 overlay. Does not touch v1/v2/v3 or other stage DBs."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from pgembed import POSTGRES_BIN_PATH

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server import get_server

from v4.load import files_through, REFRESH_AFTER

ROOT = Path(__file__).resolve().parent
DB = "agent_v4_plugin_taxonomy"
STAGE = "plugin_taxonomy"


def run_psql(server, database: str, sql: str, on_error_stop: bool = True) -> str:
    uri = server.get_uri(database)
    proc = subprocess.run(
        [str(POSTGRES_BIN_PATH / "psql"), uri, "-v",
         "ON_ERROR_STOP=" + ("1" if on_error_stop else "0"), "-q"],
        input=sql.encode(),
        capture_output=True,
    )
    out = proc.stdout.decode() + proc.stderr.decode()
    if proc.returncode != 0 and on_error_stop:
        raise RuntimeError(f"psql failed ({proc.returncode}):\n{out}")
    return out


def load_stage(server, database: str, stage: str) -> None:
    for path in files_through(stage):
        if not path.exists():
            raise FileNotFoundError(f"missing SQL in load order: {path}")
        out = run_psql(server, database, path.read_text(), on_error_stop=True)
        errors = [l for l in out.splitlines() if "ERROR" in l or "FATAL" in l]
        print(f"[loaded ] {database} <- {path.name}: {'FAIL' if errors else 'OK'}")
        for e in errors:
            print(f"          {e}")
        if errors:
            raise RuntimeError(f"errors loading {path}")
        if path.resolve() in {p.resolve() for p in REFRESH_AFTER}:
            out = run_psql(server, database, "SELECT refresh_plugins();")
            print(f"[refresh] {database} after {path.name}: {out.strip() or 'OK'}")


def main() -> int:
    server = get_server()
    run_psql(server, "postgres", f"DROP DATABASE IF EXISTS {DB} WITH (FORCE);")
    run_psql(server, "postgres", f"CREATE DATABASE {DB};")
    print(f"[created] {DB}")

    load_stage(server, DB, STAGE)

    print("\n=== 验证 ===")
    ok = True
    checks = [
        ("pgmq extension", "SELECT extname FROM pg_extension WHERE extname='pgmq'"),
        ("llm_requests queue",
         "SELECT queue_name FROM pgmq.meta WHERE queue_name='llm_requests'"),
        ("llm_requests_dlq",
         "SELECT queue_name FROM pgmq.meta WHERE queue_name='llm_requests_dlq'"),
        ("plugin_packages", "SELECT 1 FROM pg_class WHERE relname='plugin_packages'"),
        ("plugin_bindings", "SELECT 1 FROM pg_class WHERE relname='plugin_bindings'"),
        ("processed_queue_messages",
         "SELECT 1 FROM pg_class WHERE relname='processed_queue_messages'"),
        ("refresh_plugins", "SELECT 1 FROM pg_proc WHERE proname='refresh_plugins'"),
        ("apply_queue_result", "SELECT 1 FROM pg_proc WHERE proname='apply_queue_result'"),
        ("apply_llm_result", "SELECT 1 FROM pg_proc WHERE proname='apply_llm_result'"),
        ("agent_current_run_id", "SELECT 1 FROM pg_proc WHERE proname='agent_current_run_id'"),
        ("list_queue_bindings", "SELECT 1 FROM pg_proc WHERE proname='list_queue_bindings'"),
        ("render_plugin_tools", "SELECT 1 FROM pg_proc WHERE proname='render_plugin_tools'"),
        ("agent_start", "SELECT 1 FROM pg_proc WHERE proname='agent_start'"),
        ("http_call_llm guard exists", "SELECT 1 FROM pg_proc WHERE proname='http_call_llm'"),
        ("agent_run guard exists", "SELECT 1 FROM pg_proc WHERE proname='agent_run'"),
        ("llm_requests binding",
         "SELECT count(*) FROM plugin_bindings "
         "WHERE binding_type='queue_handler' AND queue_name='llm_requests'"),
    ]
    for name, sql in checks:
        out = run_psql(server, DB, sql + ";")
        if name == "llm_requests binding":
            found = bool(re.search(r"\n\s*1\s*\n", out))
        else:
            found = "1 row" in out or "pgmq" in out or "llm_requests" in out
        print(f"  {DB}.{name}: {'✓' if found else '✗ MISSING'}  {out.strip()[:80]!r}")
        ok = ok and found
    print("\n全部就绪" if ok else "\n有缺失对象！")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
