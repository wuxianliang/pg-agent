"""Design-critical probes against duckdb==1.6.0.dev365 / engine v2.0.0-alpha38615."""
from __future__ import annotations

import json
import os
import tempfile
import time
import traceback

import duckdb


def try_sql(con, name: str, sql: str) -> dict:
    out = {"name": name, "sql": sql.strip()[:500], "ok": False, "result": None, "error": None}
    try:
        res = con.execute(sql).fetchall()
        out["ok"] = True
        out["result"] = str(res)[:800]
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def main() -> int:
    probes: list[dict] = []
    extras: dict = {}
    con = duckdb.connect()
    con.execute("CREATE TABLE t(x INTEGER, y INTEGER)")
    con.execute("INSERT INTO t VALUES (1,10),(2,20),(3,30)")

    # --- extract_statements classification ---
    samples = {
        "select": "SELECT * FROM t",
        "with_select": "WITH q AS (SELECT * FROM t) SELECT * FROM q",
        "dml_cte_insert": "WITH ins AS (INSERT INTO t VALUES (9, 90) RETURNING *) SELECT * FROM ins",
        "create_temp_view": "CREATE TEMP VIEW v AS SELECT * FROM t",
        "multi": "SELECT 1; SELECT 2",
        "from_first": "FROM t SELECT x",
        "bare_expr": "1 + 2",
        "copy": "COPY t TO '/tmp/x.parquet'",
        "attach": "ATTACH ':memory:' AS other",
        "set_var": "SET VARIABLE cutoff = 1",
        "merge": "MERGE INTO t USING t s ON t.x = s.x WHEN MATCHED THEN UPDATE SET y = s.y",
        "install": "INSTALL postgres",
        "commented": "SELECT 1 -- comment\n",
        "semicolon_in_literal": "SELECT 'a;b'",
    }
    extract = {}
    for k, sql in samples.items():
        try:
            stmts = con.extract_statements(sql)
            extract[k] = [
                {
                    "type": getattr(s, "type", None),
                    "type_repr": repr(getattr(s, "type", None)),
                    "query": getattr(s, "query", None) or str(s)[:300],
                    "attrs": [a for a in dir(s) if not a.startswith("_")],
                }
                for s in stmts
            ]
        except Exception as exc:
            extract[k] = {"error": f"{type(exc).__name__}: {exc}"}
    extras["extract_statements"] = extract

    # Inspect Statement object more deeply
    try:
        s0 = con.extract_statements("WITH ins AS (INSERT INTO t VALUES (99,1) RETURNING *) SELECT * FROM ins")[0]
        extras["dml_cte_stmt_dir"] = [a for a in dir(s0) if not a.startswith("_")]
        extras["dml_cte_stmt_type"] = repr(s0.type)
        for attr in extras["dml_cte_stmt_dir"]:
            try:
                extras[f"dml_cte.{attr}"] = repr(getattr(s0, attr))[:300]
            except Exception as exc:
                extras[f"dml_cte.{attr}"] = f"ERR {exc}"
    except Exception as exc:
        extras["dml_cte_inspect_error"] = str(exc)

    # --- transactional DDL / TEMP VIEW rollback ---
    con2 = duckdb.connect()
    con2.execute("CREATE TABLE base(id INTEGER)")
    con2.execute("INSERT INTO base VALUES (1)")
    probes.append(try_sql(con2, "BEGIN", "BEGIN"))
    probes.append(try_sql(con2, "CREATE TEMP VIEW in txn", "CREATE TEMP VIEW tv AS SELECT * FROM base"))
    probes.append(try_sql(con2, "SELECT from tv in txn", "SELECT * FROM tv"))
    probes.append(try_sql(con2, "ROLLBACK", "ROLLBACK"))
    probes.append(
        try_sql(
            con2,
            "tv after rollback",
            "SELECT view_name FROM duckdb_views() WHERE view_name = 'tv'",
        )
    )

    con3 = duckdb.connect()
    con3.execute("CREATE TABLE base(id INTEGER)")
    probes.append(try_sql(con3, "BEGIN2", "BEGIN"))
    probes.append(try_sql(con3, "CREATE TEMP VIEW commit", "CREATE TEMP VIEW tv2 AS SELECT * FROM base"))
    probes.append(try_sql(con3, "COMMIT", "COMMIT"))
    probes.append(
        try_sql(
            con3,
            "tv2 after commit",
            "SELECT view_name FROM duckdb_views() WHERE view_name = 'tv2'",
        )
    )

    # CREATE OR REPLACE TEMP VIEW
    probes.append(try_sql(con, "CREATE TEMP VIEW v_or", "CREATE TEMP VIEW v_or AS SELECT x FROM t"))
    probes.append(
        try_sql(
            con,
            "CREATE OR REPLACE TEMP VIEW",
            "CREATE OR REPLACE TEMP VIEW v_or AS SELECT x, y FROM t",
        )
    )
    probes.append(try_sql(con, "select replaced view", "SELECT * FROM v_or ORDER BY x LIMIT 1"))

    # duplicate CREATE TEMP VIEW without replace
    probes.append(
        try_sql(
            con,
            "duplicate CREATE TEMP VIEW",
            "CREATE TEMP VIEW v_or AS SELECT 1",
        )
    )

    # CONNECT after ATTACH memory
    probes.append(try_sql(con, "ATTACH mem_other", "ATTACH ':memory:' AS mem_other"))
    probes.append(try_sql(con, "CONNECT mem_other", "CONNECT mem_other"))
    probes.append(try_sql(con, "current_database after CONNECT", "SELECT current_database()"))
    probes.append(try_sql(con, "SHOW DATABASES", "SHOW DATABASES"))
    probes.append(try_sql(con, "USE mem_other", "USE mem_other"))
    # reconnect to memory
    probes.append(try_sql(con, "CONNECT memory", "CONNECT memory"))
    probes.append(try_sql(con, "current_database after reconnect", "SELECT current_database()"))

    # SET VARIABLE cannot substitute identifiers
    probes.append(try_sql(con, "SET VARIABLE rel", "SET VARIABLE rel = 't'"))
    probes.append(try_sql(con, "FROM $rel identifier", "SELECT * FROM $rel"))
    probes.append(try_sql(con, "named $parameter", "SELECT $parameter"))
    try:
        r = con.execute("SELECT $parameter", {"parameter": 7}).fetchall()
        probes.append({"name": "named param dict", "ok": True, "result": str(r)})
    except Exception as exc:
        probes.append({"name": "named param dict", "ok": False, "error": f"{type(exc).__name__}: {exc}"})

    # settings relevant to sandbox
    probes.append(
        try_sql(
            con,
            "sandbox-ish settings",
            """
            SELECT name, value FROM duckdb_settings()
            WHERE name IN (
              'memory_limit', 'max_memory', 'threads', 'enable_external_access',
              'allow_unsigned_extensions', 'autoinstall_known_extensions',
              'autoload_known_extensions', 'enable_fsst_vectors',
              'lock_configuration', 'disabled_filesystems', 'allowed_directories',
              'enable_external_file_cache'
            )
            ORDER BY 1
            """,
        )
    )
    probes.append(try_sql(con, "SET memory_limit", "SET memory_limit = '256MB'"))
    probes.append(
        try_sql(
            con,
            "memory_limit after set",
            "SELECT name, value FROM duckdb_settings() WHERE name = 'memory_limit'",
        )
    )
    probes.append(
        try_sql(
            con,
            "enable_external_access",
            "SELECT name, value, description FROM duckdb_settings() WHERE name = 'enable_external_access'",
        )
    )
    probes.append(
        try_sql(
            con,
            "SET enable_external_access false",
            "SET enable_external_access = false",
        )
    )
    probes.append(try_sql(con, "read_csv after lock", "SELECT * FROM read_csv_auto('/etc/passwd') LIMIT 1"))
    probes.append(try_sql(con, "COPY TO after lock", "COPY (SELECT 1) TO '/tmp/duck_probe_lock.parquet'"))

    # restore for remaining probes
    try:
        con.execute("SET enable_external_access = true")
    except Exception as exc:
        extras["restore_external_access"] = str(exc)

    # filesystem / extension surfaces (must reject in validator)
    probes.append(try_sql(con, "read_csv_auto exists", "SELECT * FROM read_csv_auto('/tmp/does-not-exist.csv')"))
    probes.append(try_sql(con, "read_parquet exists", "SELECT * FROM read_parquet('/tmp/does-not-exist.parquet')"))
    probes.append(try_sql(con, "read_json exists", "SELECT * FROM read_json('/tmp/does-not-exist.json')"))
    probes.append(try_sql(con, "glob", "SELECT * FROM glob('/tmp/*') LIMIT 1"))
    probes.append(try_sql(con, "INSTALL httpfs", "INSTALL httpfs"))
    probes.append(try_sql(con, "CREATE SECRET syntax", "CREATE SECRET s (TYPE s3, KEY_ID 'x', SECRET 'y')"))
    probes.append(try_sql(con, "postgres_execute exists", "SELECT function_name FROM duckdb_functions() WHERE function_name = 'postgres_execute'"))

    # JSON 2.0 functions from 2026-08-18 post
    for fn_sql, name in [
        ("SELECT json_normalize('{\"z\":1,\"a\":2}')", "json_normalize"),
        ("SELECT json_merge_patch_diff('{\"a\":1}', '{\"a\":2}')", "json_merge_patch_diff"),
        ("SELECT json_deep_merge('{\"a\":1}', '{\"b\":2}')", "json_deep_merge"),
        ("SELECT json_strip_nulls('{\"a\":null,\"b\":1}')", "json_strip_nulls"),
        ("SELECT json_set('{\"a\":1}', '$.a', 9)", "json_set"),
        ("SELECT json_remove('{\"a\":1,\"b\":2}', '$.a')", "json_remove"),
        ("SELECT json_insert('{\"a\":1}', '$.b', 2)", "json_insert"),
        ("SELECT json_replace('{\"a\":1}', '$.a', 9)", "json_replace"),
    ]:
        probes.append(try_sql(con, name, fn_sql))

    # dialect surfaces useful for prompt
    probes.append(try_sql(con, "SELECT * EXCLUDE y", "SELECT * EXCLUDE (y) FROM t"))
    probes.append(try_sql(con, "QUALIFY", "SELECT x, y, row_number() OVER (ORDER BY x) AS rn FROM t QUALIFY rn = 1"))
    probes.append(try_sql(con, "PIVOT", "PIVOT t ON x USING sum(y)"))
    probes.append(try_sql(con, "SAMPLE", "SELECT * FROM t USING SAMPLE 1"))
    probes.append(try_sql(con, "CREATE MACRO", "CREATE MACRO add1(a) AS a + 1; SELECT add1(1)"))
    probes.append(
        try_sql(
            con,
            "ASOF JOIN",
            """
            CREATE TABLE ev(ts INTEGER, v INTEGER);
            INSERT INTO ev VALUES (1,10),(3,30);
            CREATE TABLE mk(ts INTEGER);
            INSERT INTO mk VALUES (2);
            SELECT * FROM mk ASOF LEFT JOIN ev ON mk.ts >= ev.ts
            """,
        )
    )

    # get_table_names
    try:
        names = con.get_table_names("SELECT * FROM t JOIN v_or USING (x)")
        probes.append({"name": "get_table_names valid", "ok": True, "result": str(names)})
    except Exception as exc:
        probes.append({"name": "get_table_names valid", "ok": False, "error": f"{type(exc).__name__}: {exc}"})

    # comments / multi-statement execute
    probes.append(try_sql(con, "line comment", "SELECT 1 -- hello"))
    probes.append(try_sql(con, "block comment", "SELECT /* c */ 1"))
    probes.append(try_sql(con, "multi statement execute", "SELECT 1; SELECT 2"))

    # COPY PARTITION_BY on fresh dir
    dest = tempfile.mkdtemp(prefix="duck_probe_part_")
    probes.append(
        try_sql(
            con,
            "COPY PARTITION_BY empty dest",
            f"COPY (SELECT 1 AS a, 'x' AS p) TO '{dest}' (FORMAT parquet, PARTITION_BY p)",
        )
    )
    extras["copy_partition_dest"] = dest
    extras["copy_partition_listing"] = os.listdir(dest)

    # interrupt API: long query then interrupt from same connection? typically another thread.
    extras["has_interrupt"] = hasattr(con, "interrupt")
    extras["interrupt_callable"] = callable(getattr(con, "interrupt", None))

    # nested schemas
    probes.append(try_sql(con, "CREATE SCHEMA nested", "CREATE SCHEMA s1; CREATE SCHEMA s1.s2"))
    probes.append(try_sql(con, "CREATE TABLE nested schema", "CREATE TABLE s1.s2.n(x INTEGER); INSERT INTO s1.s2.n VALUES (1); SELECT * FROM s1.s2.n"))

    # quack / server
    probes.append(try_sql(con, "INSTALL quack", "INSTALL quack"))
    probes.append(
        try_sql(
            con,
            "quack functions",
            "SELECT function_name FROM duckdb_functions() WHERE function_name ILIKE '%quack%' OR function_name ILIKE '%server%' LIMIT 30",
        )
    )

    # parser override setting values
    probes.append(try_sql(con, "SET allow_parser_override_extension true", "SET allow_parser_override_extension = true"))
    probes.append(
        try_sql(
            con,
            "allow_parser_override after set",
            "SELECT name, value FROM duckdb_settings() WHERE name = 'allow_parser_override_extension'",
        )
    )

    # FROM-first CREATE VIEW?
    probes.append(try_sql(con, "CREATE TEMP VIEW FROM-first", "CREATE TEMP VIEW vf AS FROM t SELECT x"))
    probes.append(try_sql(con, "select vf", "SELECT * FROM vf ORDER BY x"))

    # python register / from arrow-less list
    try:
        con.register("py_t", [{"a": 1}, {"a": 2}])
        r = con.execute("SELECT * FROM py_t").fetchall()
        probes.append({"name": "python register list[dict]", "ok": True, "result": str(r)})
    except Exception as exc:
        probes.append({"name": "python register list[dict]", "ok": False, "error": f"{type(exc).__name__}: {exc}"})

    try:
        rel = con.sql("SELECT * FROM t WHERE x > 1")
        probes.append({"name": "con.sql relation", "ok": True, "result": str(rel.fetchall())})
    except Exception as exc:
        probes.append({"name": "con.sql relation", "ok": False, "error": f"{type(exc).__name__}: {exc}"})

    # fetchmany
    try:
        con.execute("SELECT * FROM t ORDER BY x")
        probes.append({"name": "fetchmany", "ok": True, "result": str(con.fetchmany(2))})
    except Exception as exc:
        probes.append({"name": "fetchmany", "ok": False, "error": f"{type(exc).__name__}: {exc}"})

    # lock_configuration
    probes.append(
        try_sql(
            con,
            "lock_configuration desc",
            "SELECT name, value, description FROM duckdb_settings() WHERE name ILIKE '%lock%' OR name ILIKE '%disabled_filesystem%' OR name ILIKE '%allowed_dir%'",
        )
    )

    # VARIANT shredding-ish
    probes.append(
        try_sql(
            con,
            "VARIANT extract",
            "SELECT {'a':1,'b':[2,3]}::VARIANT AS v, typeof({'a':1}::VARIANT)",
        )
    )

    # CREATE TEMP TABLE snapshot analog
    probes.append(try_sql(con, "CREATE TEMP TABLE AS", "CREATE TEMP TABLE snap AS SELECT * FROM t"))
    probes.append(try_sql(con, "select snap", "SELECT count(*) FROM snap"))

    print(json.dumps({"probes": probes, "extras": extras}, indent=2, default=str, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
