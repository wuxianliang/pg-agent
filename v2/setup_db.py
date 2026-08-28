"""建库并加载 pg-agent v2（数据分析系统）。

库名 da_agent，与 v1 的 agent_fixed / agent_func / agent_rlm 隔离。
加载顺序：functional → rlm → workbench_core → data_analysis → plugin_*。
每个 plugin_*.sql 加载后立即执行 refresh_workbench_tools()：
plugin_brief_query → 1 个工具；plugin_temp_views → 累计 5 个；
plugin_sql_curator → 累计 6 个（最终门闩：brief + list + columns +
create + drop + curate）。
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
    ROOT / "pg_agent_workbench_core.sql",
    ROOT / "pg_agent_data_analysis.sql",
    ROOT / "plugin_brief_query.sql",
    ROOT / "plugin_temp_views.sql",
    ROOT / "plugin_sql_curator.sql",
]

# 每个 plugin_*.sql 加载后 refresh 应达到的累计工具数（最终 6 是 W7/W8 门闩）
PLUGIN_TOOL_COUNTS = {
    "plugin_brief_query.sql": 1,   # + wb_brief_query
    "plugin_temp_views.sql": 5,    # + list/columns/create/drop
    "plugin_sql_curator.sql": 6,   # + curate（最终门闩：六工具）
}


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
        # 插件文件落地后立即刷新注册表并核对累计工具数
        expected = PLUGIN_TOOL_COUNTS.get(sql_file.name)
        if expected is not None:
            out2 = run_psql(server, DB,
                f"SELECT CASE WHEN refresh_workbench_tools() = {expected} THEN 'WB_TOOLS_OK'"
                f" ELSE 'WB_TOOLS_UNEXPECTED' END AS wb_check;",
                on_error_stop=True)
            wb_ok = "WB_TOOLS_OK" in out2
            print(f"[refresh] {sql_file.name}: workbench_tools "
                  f"{'OK (' + str(expected) + ' tools)' if wb_ok else 'FAIL: ' + out2.strip()}")
            ok = ok and wb_ok

    print("\n=== 验证 ===")
    for name in ["http extension", "exec_sql_readonly", "http_call_llm",
                 "rlm_loop", "agent_run_rlm", "agent_run_data_analysis",
                 "make_da_prompt", "da_list_tables",
                 "workbench_tools", "refresh_workbench_tools",
                 "render_workbench_tools", "_wb_normalize_temp_view_name",
                 "wb_brief_query", "wb_temp_view_list", "wb_temp_view_columns",
                 "wb_temp_view_create", "wb_temp_view_drop",
                 "wb_sql_curate"]:
        if name == "http extension":
            out = run_psql(server, DB, "SELECT extname FROM pg_extension WHERE extname='http';")
        elif name == "workbench_tools":
            out = run_psql(server, DB,
                "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename='workbench_tools';")
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
