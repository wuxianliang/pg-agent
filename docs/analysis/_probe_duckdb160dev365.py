"""Probe duckdb==1.6.0.dev365 for announced 2.0-era capabilities."""
from __future__ import annotations

import json
import traceback

import duckdb


def try_sql(con, name: str, sql: str, setup: str | None = None) -> dict:
    out = {"name": name, "sql": sql, "ok": False, "result": None, "error": None}
    try:
        if setup:
            con.execute(setup)
        res = con.execute(sql).fetchall()
        out["ok"] = True
        out["result"] = str(res)[:800]
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def main() -> int:
    report: dict = {
        "python_package": getattr(duckdb, "__version__", None),
        "module_file": getattr(duckdb, "__file__", None),
        "probes": [],
    }
    con = duckdb.connect()

    report["probes"].append(try_sql(con, "SELECT version()", "SELECT version()"))
    try:
        report["library_version"] = duckdb.__version__
    except Exception as exc:
        report["library_version_error"] = str(exc)

    # Identity / parser
    report["probes"].append(try_sql(con, "pragma_version", "PRAGMA version"))
    report["probes"].append(
        try_sql(con, "duckdb_settings parser", "SELECT name, value FROM duckdb_settings() WHERE name ILIKE '%parser%' OR name ILIKE '%peg%' OR name ILIKE '%grammar%'")
    )

    # Pipe syntax (grammar-extension demo from 2.0 posts)
    con.execute("CREATE TABLE t(x INTEGER, y INTEGER)")
    con.execute("INSERT INTO t VALUES (1,10),(2,20),(3,30)")
    report["probes"].append(try_sql(con, "pipe WHERE", "FROM t |> WHERE x > 1"))
    report["probes"].append(try_sql(con, "pipe SELECT", "FROM t |> SELECT x, y"))
    report["probes"].append(try_sql(con, "pipe AGGREGATE", "FROM t |> AGGREGATE sum(y) AS s"))
    report["probes"].append(try_sql(con, "pipe ORDER BY", "FROM t |> ORDER BY x DESC"))
    report["probes"].append(try_sql(con, "pipe chained", "FROM t |> WHERE x >= 2 |> SELECT x, y"))

    # Expression statement without SELECT
    report["probes"].append(try_sql(con, "bare expression 1+2", "1 + 2"))
    report["probes"].append(try_sql(con, "bare column", "FROM t"))

    # Variables $x
    report["probes"].append(
        try_sql(con, "SET VARIABLE + $x", "SELECT $cutoff", setup="SET VARIABLE cutoff = 2")
    )
    report["probes"].append(try_sql(con, "SET VARIABLE syntax", "SET VARIABLE cutoff = 2; SELECT $cutoff"))
    try:
        con.execute("SET VARIABLE cutoff = 2")
        report["probes"].append(try_sql(con, "WHERE $cutoff", "SELECT * FROM t WHERE x >= $cutoff"))
    except Exception as exc:
        report["probes"].append({"name": "SET VARIABLE setup", "ok": False, "error": str(exc)})

    # Prepared $1
    try:
        rel = con.execute("SELECT * FROM t WHERE x = $1", [2]).fetchall()
        report["probes"].append({"name": "positional $1", "ok": True, "result": str(rel)})
    except Exception as exc:
        report["probes"].append({"name": "positional $1", "ok": False, "error": f"{type(exc).__name__}: {exc}"})

    # CONNECT
    report["probes"].append(try_sql(con, "CONNECT help", "HELP CONNECT"))
    report["probes"].append(try_sql(con, "CONNECT statement", "CONNECT 'memory'"))
    report["probes"].append(
        try_sql(con, "SHOW statements CONNECT", "SELECT * FROM duckdb_functions() WHERE function_name ILIKE '%connect%' LIMIT 20")
    )

    # postgres extension
    report["probes"].append(try_sql(con, "INSTALL postgres", "INSTALL postgres"))
    report["probes"].append(try_sql(con, "LOAD postgres", "LOAD postgres"))
    report["probes"].append(
        try_sql(con, "postgres_scan exists", "SELECT function_name FROM duckdb_functions() WHERE function_name ILIKE '%postgres%' ORDER BY 1")
    )

    # ATTACH
    report["probes"].append(try_sql(con, "ATTACH memory", "ATTACH ':memory:' AS mem2"))

    # VARIANT
    report["probes"].append(try_sql(con, "VARIANT type", "SELECT {'a': 1}::VARIANT AS v"))
    report["probes"].append(try_sql(con, "VARIANT typeof", "SELECT typeof({'a':1}::VARIANT)"))

    # DML in CTE
    con.execute("CREATE TABLE u(id INTEGER)")
    report["probes"].append(
        try_sql(
            con,
            "DML inside CTE INSERT",
            "WITH ins AS (INSERT INTO u VALUES (1) RETURNING *) SELECT * FROM ins",
        )
    )
    report["probes"].append(
        try_sql(
            con,
            "DML inside CTE UPDATE",
            "WITH upd AS (UPDATE u SET id = id + 1 RETURNING *) SELECT * FROM upd",
        )
    )

    # Triggers
    report["probes"].append(
        try_sql(
            con,
            "CREATE TRIGGER",
            """
            CREATE TABLE trg(x INTEGER);
            CREATE TRIGGER t_ai AFTER INSERT ON trg
            BEGIN
                SELECT 1;
            END
            """,
        )
    )
    report["probes"].append(
        try_sql(
            con,
            "CREATE TRIGGER row",
            """
            CREATE TABLE trg2(x INTEGER);
            CREATE TRIGGER t_bi BEFORE INSERT ON trg2
            FOR EACH ROW BEGIN SELECT 1; END
            """,
        )
    )

    # Nested schemas / MERGE
    report["probes"].append(
        try_sql(
            con,
            "MERGE INTO",
            """
            CREATE TABLE tgt(k INTEGER, v INTEGER);
            CREATE TABLE src(k INTEGER, v INTEGER);
            INSERT INTO tgt VALUES (1, 10);
            INSERT INTO src VALUES (1, 99), (2, 20);
            MERGE INTO tgt USING src ON tgt.k = src.k
            WHEN MATCHED THEN UPDATE SET v = src.v
            WHEN NOT MATCHED THEN INSERT VALUES (src.k, src.v);
            SELECT * FROM tgt ORDER BY k
            """,
        )
    )

    # COPY PARTITION BY
    report["probes"].append(
        try_sql(
            con,
            "COPY PARTITION BY syntax check",
            "COPY (SELECT 1 AS a, 'x' AS p) TO '/tmp/duck_probe_copy' (FORMAT parquet, PARTITION_BY p)",
        )
    )

    # TEMP VIEW chaining (MVP path)
    report["probes"].append(
        try_sql(
            con,
            "CREATE TEMP VIEW chain",
            """
            CREATE TEMP VIEW v1 AS SELECT * FROM t WHERE x >= 2;
            CREATE TEMP VIEW v2 AS SELECT x, y * 2 AS y2 FROM v1;
            SELECT * FROM v2 ORDER BY x
            """,
        )
    )
    report["probes"].append(try_sql(con, "SHOW TABLES", "SHOW TABLES"))
    report["probes"].append(try_sql(con, "duckdb_views", "SELECT view_name, sql FROM duckdb_views()"))

    # Trailing AS view_name (InfiniSQL-like) — expect fail unless grammar extension
    report["probes"].append(
        try_sql(con, "trailing AS view_name", "SELECT x FROM t AS named_out")
    )
    report["probes"].append(
        try_sql(con, "statement AS view suffix", "SELECT x FROM t AS named_out;")
    )

    # Grammar extension / pipe extension load
    report["probes"].append(try_sql(con, "INSTALL pipe", "INSTALL pipe"))
    report["probes"].append(try_sql(con, "LOAD pipe", "LOAD pipe"))
    report["probes"].append(
        try_sql(con, "duckdb_extensions", "SELECT extension_name, loaded, installed FROM duckdb_extensions() ORDER BY 1")
    )

    # Recursive CTE
    report["probes"].append(
        try_sql(
            con,
            "recursive CTE",
            """
            WITH RECURSIVE c(n) AS (
                SELECT 1
                UNION ALL
                SELECT n + 1 FROM c WHERE n < 3
            )
            SELECT * FROM c
            """,
        )
    )

    # Python API extras
    api = {}
    for attr in ("extract_statements", "sql", "query", "interrupt", "get_table_names"):
        api[attr] = hasattr(con, attr)
    report["python_connection_attrs"] = api
    report["module_attrs"] = {
        "extract_statements": hasattr(duckdb, "extract_statements"),
        "read_json": hasattr(duckdb, "read_json"),
        "default_connection": hasattr(duckdb, "default_connection"),
    }

    if hasattr(con, "extract_statements"):
        try:
            stmts = con.extract_statements("SELECT 1; SELECT 2")
            report["extract_statements"] = str(stmts)[:500]
        except Exception as exc:
            report["extract_statements_error"] = f"{type(exc).__name__}: {exc}"

    # Interruption API
    report["has_interrupt"] = hasattr(con, "interrupt")

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
