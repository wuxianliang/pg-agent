"""Additional probes: CONNECT/sandbox order, VARIANT, interrupt, lineage, dialect leftovers."""
from __future__ import annotations

import json
import threading
import time

import duckdb


def try_sql(con, name: str, sql: str) -> dict:
    out = {"name": name, "sql": sql.strip()[:400], "ok": False, "result": None, "error": None}
    try:
        out["result"] = str(con.execute(sql).fetchall())[:800]
        out["ok"] = True
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def main() -> int:
    probes: list[dict] = []

    con = duckdb.connect()
    probes.append(try_sql(con, "LOAD postgres", "LOAD postgres"))
    probes.append(try_sql(con, "CONNECT postgres uri after load", "CONNECT 'postgres://127.0.0.1:1/postgres'"))
    probes.append(try_sql(con, "DISCONNECT", "DISCONNECT"))
    probes.append(
        try_sql(
            con,
            "ATTACH TYPE postgres",
            "ATTACH 'dbname=x host=127.0.0.1 port=1' AS pg (TYPE postgres, READ_ONLY)",
        )
    )
    probes.append(
        try_sql(
            con,
            "postgres funcs after load",
            "SELECT function_name FROM duckdb_functions() WHERE function_name ILIKE 'postgres%' ORDER BY 1",
        )
    )

    con2 = duckdb.connect()
    con2.execute("LOAD postgres")
    probes.append(try_sql(con2, "lock after LOAD postgres", "SET enable_external_access = false"))
    probes.append(
        try_sql(
            con2,
            "postgres_scan after lock",
            "SELECT * FROM postgres_scan('host=127.0.0.1 port=1 dbname=x user=x', 'public', 't') LIMIT 1",
        )
    )
    probes.append(
        try_sql(
            con2,
            "ATTACH postgres after lock",
            "ATTACH 'dbname=x host=127.0.0.1 port=1' AS pg (TYPE postgres, READ_ONLY)",
        )
    )

    con3 = duckdb.connect()
    con3.execute("SET enable_external_access = false")
    probes.append(try_sql(con3, "LOAD postgres after lock", "LOAD postgres"))

    con4 = duckdb.connect()
    for name, sql in [
        ("variant_type", "SELECT variant_type({'user': {'id': 42}}::VARIANT)"),
        ("variant_keys", "SELECT variant_keys({'user': {'id': 42}}::VARIANT)"),
        ("variant_contains", "SELECT variant_contains({'user': {'id': 42}}::VARIANT, {'user': {'id': 42}}::VARIANT)"),
        ("JSON::VARIANT", "SELECT '{\"a\":1}'::JSON::VARIANT"),
        ("FETCH FIRST", "SELECT * FROM (VALUES (1),(2),(3)) t(x) FETCH FIRST 2 ROWS ONLY"),
        ("OVERLAY", "SELECT OVERLAY('abcdef' PLACING 'xyz' FROM 2)"),
        ("USING KEY recursive", "WITH RECURSIVE tbl(a, b) USING KEY (a, avg(b)) AS (SELECT 1, 5 UNION ALL SELECT a, b - 1 FROM tbl WHERE b > 0) TABLE tbl"),
        ("AT TIME ZONE", "SELECT '2026-08-14 12:00:00'::TIMESTAMPTZ AT TIME ZONE 'Europe/Paris'"),
        ("COLLATE de", "SELECT 'ä' COLLATE de < 'z' COLLATE de"),
        ("CREATE EXTENSION REPOSITORY", "CREATE EXTENSION REPOSITORY my_repo FROM 'https://example.invalid'"),
    ]:
        probes.append(try_sql(con4, name, sql))

    con5 = duckdb.connect()
    con5.execute("CREATE TABLE staging(id INTEGER); INSERT INTO staging VALUES (1),(2)")
    con5.execute("CREATE TABLE archive(id INTEGER)")
    probes.append(
        try_sql(
            con5,
            "DELETE in CTE",
            "WITH moved AS MATERIALIZED (DELETE FROM staging RETURNING *) INSERT INTO archive SELECT * FROM moved",
        )
    )
    try:
        stmts = con5.extract_statements(
            "WITH moved AS MATERIALIZED (DELETE FROM staging RETURNING *) INSERT INTO archive SELECT * FROM moved"
        )
        probes.append(
            {
                "name": "extract DELETE-in-CTE",
                "ok": True,
                "result": [(repr(s.type), s.query) for s in stmts],
            }
        )
    except Exception as exc:
        probes.append({"name": "extract DELETE-in-CTE", "ok": False, "error": str(exc)})
    try:
        stmts = con5.extract_statements("WITH c AS (COPY (SELECT 1 AS a) TO '/tmp/x.parquet') SELECT 1")
        probes.append(
            {
                "name": "extract COPY-in-CTE",
                "ok": True,
                "result": [(repr(s.type), s.query) for s in stmts],
            }
        )
    except Exception as exc:
        probes.append({"name": "extract COPY-in-CTE", "ok": False, "error": str(exc)})

    con6 = duckdb.connect()
    err: dict = {"e": None}

    def run() -> None:
        try:
            con6.execute("SELECT count(*) FROM range(1000000000)").fetchall()
        except Exception as exc:
            err["e"] = f"{type(exc).__name__}: {exc}"

    th = threading.Thread(target=run)
    th.start()
    time.sleep(0.05)
    con6.interrupt()
    th.join(timeout=5)
    probes.append(
        {
            "name": "interrupt long range",
            "ok": err["e"] is not None and not th.is_alive(),
            "result": err["e"],
            "thread_alive": th.is_alive(),
        }
    )

    con7 = duckdb.connect()
    con7.execute("CREATE TABLE t(x INTEGER); CREATE TABLE u(x INTEGER)")
    for sql, name in [
        ("SELECT * FROM t", "get_table_names simple"),
        ("SELECT t.x FROM t, u WHERE t.x = u.x", "get_table_names comma join"),
        ("FROM t", "get_table_names FROM-first"),
        ("SELECT * FROM t JOIN u USING (x)", "get_table_names JOIN USING"),
    ]:
        try:
            probes.append({"name": name, "ok": True, "result": str(con7.get_table_names(sql)), "sql": sql})
        except Exception as exc:
            probes.append({"name": name, "ok": False, "error": f"{type(exc).__name__}: {exc}", "sql": sql})

    con8 = duckdb.connect()
    for val in ("DEFAULT", "FALLBACK"):
        probes.append(try_sql(con8, f"parser_override={val}", f"SET allow_parser_override_extension = '{val}'"))

    con9 = duckdb.connect()
    probes.append(try_sql(con9, "INSTALL quack", "INSTALL quack"))
    probes.append(try_sql(con9, "CALL quack_serve short token", "CALL quack_serve(token := 't')"))

    print(json.dumps({"probes": probes}, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
