"""建库并加载 pg-agent v2（数据分析系统）。

库名 da_agent，与 v1 的 agent_fixed / agent_func / agent_rlm 隔离。
加载顺序：functional → rlm → data_analysis。
v2 源文件已含 PG17 兼容修正，不再运行时打补丁。
"""
import subprocess
import sys
from pathlib import Path

from pgembed import POSTGRES_BIN_PATH

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server import get_server

ROOT = Path(__file__).parent
DB = "da_agent"
SQL_FILES = [
    ROOT / "pg_agent_functional.sql",
    ROOT / "pg_agent_rlm.sql",
    ROOT / "pg_agent_data_analysis.sql",
]


def run_psql(server, database: str, sql: str, on_error_stop: bool = False) -> str:
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


def main():
    server = get_server()
    run_psql(server, "postgres", f"DROP DATABASE IF EXISTS {DB} WITH (FORCE);")
    run_psql(server, "postgres", f"CREATE DATABASE {DB};")
    print(f"[created] {DB}")

    ok = True
    for sql_file in SQL_FILES:
        out = run_psql(server, DB, sql_file.read_text(), on_error_stop=True)
        errors = [l for l in out.splitlines() if "ERROR" in l or "FATAL" in l]
        status = "OK" if not errors else "FAIL"
        print(f"[loaded ] {DB} <- {sql_file.name}: {status}")
        for e in errors:
            print(f"          {e}")
            ok = False

    print("\n=== 验证 ===")
    for name in ["http extension", "exec_sql_readonly", "http_call_llm",
                 "rlm_loop", "agent_run_rlm", "agent_run_data_analysis",
                 "make_da_prompt", "da_list_tables"]:
        if name == "http extension":
            out = run_psql(server, DB, "SELECT extname FROM pg_extension WHERE extname='http';")
        else:
            out = run_psql(server, DB,
                f"SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                f"WHERE n.nspname='public' AND p.proname='{name}';")
        found = "1 row" in out or "http" in out
        print(f"  {DB}.{name}: {'✓' if found else '✗ MISSING'}")
        ok = ok and found
    print("\n全部就绪" if ok else "\n有缺失对象！")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
