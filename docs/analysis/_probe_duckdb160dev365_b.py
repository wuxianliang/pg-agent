"""Second-pass probes: CONNECT, postgres attach, triggers, trailing-AS side effects."""
from __future__ import annotations

import json

import duckdb


def try_sql(con, name: str, sql: str) -> dict:
    out = {"name": name, "sql": sql.strip()[:400], "ok": False, "result": None, "error": None}
    try:
        res = con.execute(sql).fetchall()
        out["ok"] = True
        out["result"] = str(res)[:800]
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def main() -> int:
    probes = []
    con = duckdb.connect()
    con.execute("CREATE TABLE t(x INTEGER)")
    con.execute("INSERT INTO t VALUES (1),(2)")

    # Trailing AS is table alias: should NOT create a view named named_out
    probes.append(try_sql(con, "SELECT x FROM t AS named_out", "SELECT x FROM t AS named_out"))
    probes.append(
        try_sql(
            con,
            "views after trailing AS",
            "SELECT view_name FROM duckdb_views() WHERE view_name = 'named_out'",
        )
    )
    probes.append(
        try_sql(
            con,
            "tables after trailing AS",
            "SELECT table_name FROM duckdb_tables() WHERE table_name = 'named_out'",
        )
    )

    # FROM-first
    probes.append(try_sql(con, "FROM-first SELECT", "FROM t SELECT x"))

    # 2.0 trigger syntax from 2026-08-17 post
    probes.append(
        try_sql(
            con,
            "trigger AFTER UPDATE STATEMENT",
            """
            CREATE TABLE target (id INTEGER, val INTEGER);
            CREATE TABLE audit (id INTEGER, old_val INTEGER, new_val INTEGER);
            CREATE TRIGGER trg_audit AFTER UPDATE ON target
            REFERENCING OLD TABLE AS o NEW TABLE AS n
            FOR EACH STATEMENT
                INSERT INTO audit
                SELECT n.id, o.val, n.val
                FROM o
                JOIN n ON o.id = n.id;
            INSERT INTO target VALUES (1, 10), (2, 20);
            UPDATE target SET val = val * 10 WHERE id <= 2;
            SELECT * FROM audit ORDER BY id
            """,
        )
    )

    # CONNECT variants
    for sql, name in [
        ("CONNECT 'postgres://127.0.0.1:1/postgres'", "CONNECT postgres uri"),
        ("CONNECT postgres", "CONNECT identifier"),
        ("HELP 'CONNECT'", "HELP 'CONNECT'"),
    ]:
        probes.append(try_sql(con, name, sql))

    con.execute("LOAD postgres")
    probes.append(
        try_sql(
            con,
            "ATTACH TYPE postgres invalid",
            "ATTACH 'dbname=does_not_exist host=127.0.0.1 port=1' AS pg (TYPE postgres, READ_ONLY)",
        )
    )
    probes.append(
        try_sql(
            con,
            "postgres_scan dummy",
            "SELECT * FROM postgres_scan('host=127.0.0.1 port=1 dbname=x user=x', 'public', 't') LIMIT 1",
        )
    )
    probes.append(
        try_sql(
            con,
            "postgres_query dummy",
            "SELECT * FROM postgres_query('pg', 'SELECT 1')",
        )
    )

    # parser override
    probes.append(
        try_sql(
            con,
            "allow_parser_override_extension",
            "SELECT name, value, description FROM duckdb_settings() WHERE name = 'allow_parser_override_extension'",
        )
    )

    # nested / struct
    probes.append(try_sql(con, "STRUCT", "SELECT {'a': 1, 'b': {'c': 2}} AS s"))
    probes.append(try_sql(con, "VARIANT nested", "SELECT {'a':[1,2,3]}::VARIANT"))

    # get_table_names
    try:
        names = con.get_table_names("SELECT * FROM t JOIN target USING (id)")
        probes.append({"name": "get_table_names", "ok": True, "result": str(names)})
    except Exception as exc:
        probes.append({"name": "get_table_names", "ok": False, "error": f"{type(exc).__name__}: {exc}"})

    print(json.dumps({"probes": probes}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
