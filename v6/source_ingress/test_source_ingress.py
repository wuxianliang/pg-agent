"""W3 gate: real PostgreSQL types snapshot into a hardened DuckDB connection."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v6.source_ingress.duckdb_ingress import (
    IngressError,
    PostgresSourceResolver,
    SnapshotBudget,
    SourceConfig,
    snapshot_table,
)
from v6.source_ingress.setup_db import DB, main as setup_db


def check(label: str, condition: bool, detail: object = "") -> None:
    print(f"[{('PASS' if condition else 'FAIL')}] {label}" + (f": {detail}" if detail else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def hardened():
    con = duckdb.connect()
    con.execute("SET autoinstall_known_extensions=false")
    con.execute("SET autoload_known_extensions=false")
    con.execute("SET enable_external_access=false")
    con.execute("SET memory_limit='512 MiB'")
    return con


def expect_ingress(type_: str, fn) -> dict:
    try:
        fn()
    except IngressError as exc:
        check(f"structured {type_}", exc.envelope["Type"] == type_, exc.envelope)
        return exc.envelope
    raise AssertionError(f"expected {type_}")


def seed(uri: str) -> None:
    c = psycopg2.connect(uri)
    c.autocommit = True
    with c.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS source_types")
        cur.execute("DROP TABLE IF EXISTS source_large")
        cur.execute("DROP TABLE IF EXISTS source_unsupported")
        cur.execute("""
            CREATE TABLE source_types (
                b boolean,
                i2 smallint,
                i4 integer,
                i8 bigint,
                f4 real,
                f8 double precision,
                amount numeric(10,2),
                txt text,
                d date,
                ts timestamp,
                tstz timestamptz,
                u uuid,
                bin bytea,
                doc jsonb,
                tags text[],
                nums integer[],
                uuids uuid[]
            )
        """)
        cur.execute("""
            INSERT INTO source_types VALUES (
                true, -12, 1234, 9876543210, 1.25, 2.5, 12345.67, 'hello',
                DATE '2026-08-28', TIMESTAMP '2026-08-28 10:20:30',
                TIMESTAMPTZ '2026-08-28 10:20:30+08',
                '12345678-1234-5678-1234-567812345678'::uuid,
                decode('00ff10','hex'), '{"a":1,"nested":{"ok":true}}'::jsonb,
                ARRAY['a','b'], ARRAY[1,2,3],
                ARRAY['12345678-1234-5678-1234-567812345678'::uuid]
            ),
            (NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL)
        """)
        cur.execute("CREATE TABLE source_large AS SELECT i FROM generate_series(1,5) AS g(i)")
        cur.execute("CREATE TABLE source_unsupported(addr inet)")
        cur.execute("INSERT INTO source_unsupported VALUES ('127.0.0.1')")
    c.close()


def main() -> int:
    check("setup succeeds", setup_db() == 0)
    server = get_server()
    uri = server.get_uri(DB)
    seed(uri)
    resolver = PostgresSourceResolver([
        SourceConfig(
            "agent_db", uri,
            frozenset({
                ("public", "source_types"),
                ("public", "source_large"),
                ("public", "source_unsupported"),
            }),
            max_rows=1000,
            max_bytes=1024 * 1024,
        )
    ])
    con = hardened()
    try:
        result = snapshot_table(
            con, resolver,
            source_id="agent_db", schema_name="public", table_name="source_types",
            artifact_name="registered_types",
        )
        check("all rows copied", result.row_count == 2, result.as_dict())
        check("result contains no URI", uri not in json.dumps(result.as_dict(), default=str))
        desc = con.execute("DESCRIBE registered_types").fetchall()
        type_map = {row[0]: row[1] for row in desc}
        expected = {
            "b": "BOOLEAN", "i2": "BIGINT", "i4": "BIGINT", "i8": "BIGINT",
            "f4": "DOUBLE", "f8": "DOUBLE", "amount": "DECIMAL(10,2)",
            "txt": "VARCHAR", "d": "DATE", "ts": "TIMESTAMP",
            "tstz": "TIMESTAMP WITH TIME ZONE", "u": "UUID", "bin": "BLOB",
            "doc": "JSON", "tags": "VARCHAR[]", "nums": "BIGINT[]", "uuids": "UUID[]",
        }
        check("type matrix preserved", all(type_map[k] == v for k, v in expected.items()), type_map)
        row = con.execute("""
            SELECT b,i2,i4,i8,f4,f8,amount,txt,d,ts,tstz,u,hex(bin),
                   json_extract(doc,'$.nested.ok'),tags,nums,uuids
              FROM registered_types WHERE b IS TRUE
        """).fetchone()
        check("scalar values preserved", row[:8] == (True, -12, 1234, 9876543210, 1.25, 2.5, __import__('decimal').Decimal('12345.67'), 'hello'), row[:8])
        check("binary preserved", row[12] == "00FF10", row[12])
        check("JSON preserved", row[13] == "true", row[13])
        check("arrays preserved", row[14] == ["a", "b"] and row[15] == [1, 2, 3], row[14:16])
        check("NULL row preserved", con.execute("SELECT count(*) FROM registered_types WHERE b IS NULL").fetchone()[0] == 1)

        # Snapshot semantics: source changes do not mutate the DuckDB table.
        pg = psycopg2.connect(uri)
        pg.autocommit = True
        with pg.cursor() as cur:
            cur.execute("UPDATE source_types SET txt='changed' WHERE b IS TRUE")
        pg.close()
        check("registered data is a snapshot", con.execute("SELECT txt FROM registered_types WHERE b IS TRUE").fetchone()[0] == "hello")

        expect_ingress("DUCK_SOURCE_NOT_FOUND", lambda: snapshot_table(
            con, resolver, source_id="missing", schema_name="public",
            table_name="source_types", artifact_name="missing_source"))
        expect_ingress("DUCK_SOURCE_NOT_ALLOWED", lambda: snapshot_table(
            con, resolver, source_id="agent_db", schema_name="public",
            table_name="agent_runs", artifact_name="not_allowed"))
        expect_ingress("DUCK_IDENTIFIER_ERROR", lambda: snapshot_table(
            con, resolver, source_id="agent_db", schema_name="public",
            table_name="source_types", artifact_name="bad-name"))
        expect_ingress("DUCK_SOURCE_TYPE_UNSUPPORTED", lambda: snapshot_table(
            con, resolver, source_id="agent_db", schema_name="public",
            table_name="source_unsupported", artifact_name="unsupported"))
        check("unsupported type leaves no table", con.execute(
            "SELECT count(*) FROM duckdb_tables() WHERE table_name='unsupported'"
        ).fetchone()[0] == 0)

        expect_ingress("DUCK_SOURCE_BUDGET_EXCEEDED", lambda: snapshot_table(
            con, resolver, source_id="agent_db", schema_name="public",
            table_name="source_large", artifact_name="too_many",
            budget=SnapshotBudget(max_rows=2, max_bytes=1024, batch_rows=2)))
        check("row budget rollback removes partial table", con.execute(
            "SELECT count(*) FROM duckdb_tables() WHERE table_name='too_many'"
        ).fetchone()[0] == 0)

        expect_ingress("DUCK_SOURCE_BUDGET_EXCEEDED", lambda: snapshot_table(
            con, resolver, source_id="agent_db", schema_name="public",
            table_name="source_types", artifact_name="too_big",
            budget=SnapshotBudget(max_rows=10, max_bytes=8, batch_rows=1)))
        check("byte budget rollback removes partial table", con.execute(
            "SELECT count(*) FROM duckdb_tables() WHERE table_name='too_big'"
        ).fetchone()[0] == 0)

        # W3 PostgreSQL metadata exists but bulk source rows remain only in DuckDB.
        pg = psycopg2.connect(uri)
        with pg.cursor() as cur:
            for table in ("duck_workbench_sessions", "duck_artifacts", "duck_operations"):
                cur.execute("SELECT to_regclass(%s)", (table,))
                check(f"metadata table {table}", cur.fetchone()[0] == table)
            cur.execute("SELECT count(*) FROM duck_artifacts")
            check("W3 ingress does not persist rows in metadata", cur.fetchone()[0] == 0)
        pg.close()
        print("[W3] all gates passed")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
