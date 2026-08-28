"""建库并加载 v3（HTTP 基线 + PGMQ 入队）。库名 agent_v3，不碰 v1/v2。"""
import subprocess
import sys
from pathlib import Path

from pgembed import POSTGRES_BIN_PATH

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server import get_server

ROOT = Path(__file__).parent
DB = "agent_v3"
SQL_FILE = ROOT / "pg_agent_pgmq.sql"


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


def main() -> int:
    server = get_server()
    run_psql(server, "postgres", f"DROP DATABASE IF EXISTS {DB} WITH (FORCE);")
    run_psql(server, "postgres", f"CREATE DATABASE {DB};")
    print(f"[created] {DB}")

    out = run_psql(server, DB, SQL_FILE.read_text(), on_error_stop=True)
    errors = [l for l in out.splitlines() if "ERROR" in l or "FATAL" in l]
    print(f"[loaded ] {DB} <- {SQL_FILE.name}: {'FAIL' if errors else 'OK'}")
    for e in errors:
        print(f"          {e}")

    print("\n=== 验证 ===")
    ok = not errors
    checks = [
        ("http extension", "SELECT extname FROM pg_extension WHERE extname='http'"),
        ("pgmq extension", "SELECT extname FROM pg_extension WHERE extname='pgmq'"),
        ("llm_requests queue",
         "SELECT queue_name FROM pgmq.meta WHERE queue_name='llm_requests'"),
        ("agent_run", "SELECT 1 FROM pg_proc WHERE proname='agent_run'"),
        ("agent_start", "SELECT 1 FROM pg_proc WHERE proname='agent_start'"),
        ("prepare_llm_request", "SELECT 1 FROM pg_proc WHERE proname='prepare_llm_request'"),
        ("apply_llm_response", "SELECT 1 FROM pg_proc WHERE proname='apply_llm_response'"),
        ("http_call_llm", "SELECT 1 FROM pg_proc WHERE proname='http_call_llm'"),
        ("session_set", "SELECT 1 FROM pg_proc WHERE proname='session_set'"),
        ("session_get", "SELECT 1 FROM pg_proc WHERE proname='session_get'"),
        ("fail_run", "SELECT 1 FROM pg_proc WHERE proname='fail_run'"),
        ("llm_requests_dlq",
         "SELECT queue_name FROM pgmq.meta WHERE queue_name='llm_requests_dlq'"),
    ]
    for name, sql in checks:
        out = run_psql(server, DB, sql + ";")
        found = "1 row" in out or "http" in out or "pgmq" in out or "llm_requests" in out
        print(f"  {DB}.{name}: {'✓' if found else '✗ MISSING'}")
        ok = ok and found
    print("\n全部就绪" if ok else "\n有缺失对象！")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
