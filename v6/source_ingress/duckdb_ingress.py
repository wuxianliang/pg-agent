"""Bounded, read-only PostgreSQL snapshot ingress for a run-local DuckDB session."""
from __future__ import annotations

import datetime as dt
import decimal
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any, Iterable

import duckdb
import psycopg2
from psycopg2 import sql

IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


class IngressError(RuntimeError):
    def __init__(self, type_: str, problem: str, solution: str, phase: str = "Ingress"):
        super().__init__(problem)
        self.envelope = {
            "success": False,
            "Type": type_,
            "Phase": phase,
            "Problem": problem[:1000],
            "Solution": solution[:1000],
        }


@dataclass(frozen=True)
class SnapshotBudget:
    max_rows: int = 100_000
    max_bytes: int = 64 * 1024 * 1024
    batch_rows: int = 1_000


@dataclass(frozen=True)
class SourceConfig:
    source_id: str
    uri: str
    allowed_tables: frozenset[tuple[str, str]]
    max_rows: int = 100_000
    max_bytes: int = 64 * 1024 * 1024
    allow_replay: bool = True


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    pg_type: str
    duck_type: str


@dataclass(frozen=True)
class SnapshotResult:
    source_id: str
    schema_name: str
    table_name: str
    artifact_name: str
    row_count: int
    byte_count: int
    columns: tuple[ColumnSpec, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "success": True,
            "source_id": self.source_id,
            "schema_name": self.schema_name,
            "table_name": self.table_name,
            "artifact_name": self.artifact_name,
            "row_count": self.row_count,
            "byte_count": self.byte_count,
            "columns": [c.__dict__ for c in self.columns],
        }


class PostgresSourceResolver:
    def __init__(self, configs: Iterable[SourceConfig]):
        self._configs = {c.source_id: c for c in configs}

    def resolve(self, source_id: str) -> SourceConfig:
        cfg = self._configs.get(source_id)
        if cfg is None:
            raise IngressError(
                "DUCK_SOURCE_NOT_FOUND", f"unknown source_id: {source_id}",
                "Use one of the configured source aliases; do not provide a DSN.",
                "Resolution",
            )
        return cfg


def validate_identifier(name: str, label: str = "identifier") -> str:
    if not isinstance(name, str) or not IDENT_RE.fullmatch(name):
        raise IngressError(
            "DUCK_IDENTIFIER_ERROR", f"invalid {label}: {name!r}",
            "Use an identifier beginning with a letter or underscore and containing only letters, digits, and underscores.",
            "Validation",
        )
    return name


def _duck_ident(name: str) -> str:
    return '"' + validate_identifier(name).replace('"', '""') + '"'


def _map_column(row: tuple[Any, ...]) -> ColumnSpec:
    name, data_type, udt_name, precision, scale = row
    pg = str(data_type)
    simple = {
        "boolean": "BOOLEAN",
        "smallint": "BIGINT",
        "integer": "BIGINT",
        "bigint": "BIGINT",
        "real": "DOUBLE",
        "double precision": "DOUBLE",
        "text": "VARCHAR",
        "character varying": "VARCHAR",
        "character": "VARCHAR",
        "date": "DATE",
        "timestamp without time zone": "TIMESTAMP",
        "timestamp with time zone": "TIMESTAMPTZ",
        "uuid": "UUID",
        "bytea": "BLOB",
        "json": "JSON",
        "jsonb": "JSON",
    }
    if data_type in simple:
        return ColumnSpec(name, pg if data_type not in ("ARRAY", "USER-DEFINED") else str(udt_name), simple[data_type])
    if data_type == "numeric":
        if precision is None or scale is None or int(precision) > 38:
            raise IngressError(
                "DUCK_SOURCE_TYPE_UNSUPPORTED",
                f"column {name} has unsupported numeric precision/scale: {precision},{scale}",
                "Cast the source column to NUMERIC with precision <= 38 before registration.",
            )
        return ColumnSpec(name, f"numeric({precision},{scale})", f"DECIMAL({int(precision)},{int(scale)})")
    if data_type == "ARRAY":
        arrays = {
            "_bool": "BOOLEAN[]", "_int2": "BIGINT[]", "_int4": "BIGINT[]", "_int8": "BIGINT[]",
            "_float4": "DOUBLE[]", "_float8": "DOUBLE[]", "_text": "VARCHAR[]",
            "_varchar": "VARCHAR[]", "_uuid": "UUID[]",
        }
        mapped = arrays.get(udt_name)
        if mapped:
            return ColumnSpec(name, str(udt_name), mapped)
    raise IngressError(
        "DUCK_SOURCE_TYPE_UNSUPPORTED", f"column {name} uses unsupported PostgreSQL type {data_type}/{udt_name}",
        "Cast the source column to a supported scalar or array type before registration.",
    )


def _parse_pg_array_text(value: str) -> list[str]:
    text = value.strip()
    if not (text.startswith("{") and text.endswith("}")):
        raise ValueError(f"invalid PostgreSQL array text: {value!r}")
    inner = text[1:-1]
    if not inner:
        return []
    # UUID arrays returned by the current psycopg2 connection are commonly
    # text such as {uuid1,uuid2}; UUID values themselves contain no commas.
    return [item.strip().strip('"') for item in inner.split(",")]


def _convert_value(value: Any, spec: ColumnSpec) -> Any:
    if value is None:
        return None
    if spec.duck_type == "JSON":
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if spec.duck_type == "BLOB" and isinstance(value, memoryview):
        return bytes(value)
    if spec.duck_type == "UUID" and isinstance(value, uuid.UUID):
        return str(value)
    if spec.duck_type == "UUID[]":
        values = _parse_pg_array_text(value) if isinstance(value, str) else value
        if not isinstance(values, (list, tuple)):
            raise IngressError(
                "DUCK_SOURCE_TYPE_UNSUPPORTED", "uuid[] value has an unsupported driver representation",
                "Use a PostgreSQL driver that returns uuid[] as a sequence or cast it before registration.",
            )
        return [str(v) if isinstance(v, uuid.UUID) else v for v in values]
    return value


def _estimate_value(value: Any) -> int:
    if value is None:
        return 4
    if isinstance(value, (bytes, bytearray, memoryview)):
        return len(value)
    if isinstance(value, (dt.date, dt.datetime, dt.time, decimal.Decimal, uuid.UUID)):
        return len(str(value).encode("utf-8"))
    try:
        return len(json.dumps(value, default=str, ensure_ascii=False).encode("utf-8"))
    except Exception:
        return len(repr(value).encode("utf-8"))


def snapshot_table(
    duck: duckdb.DuckDBPyConnection,
    resolver: PostgresSourceResolver,
    *,
    source_id: str,
    schema_name: str,
    table_name: str,
    artifact_name: str,
    budget: SnapshotBudget | None = None,
) -> SnapshotResult:
    schema_name = validate_identifier(schema_name, "schema_name")
    table_name = validate_identifier(table_name, "table_name")
    artifact_name = validate_identifier(artifact_name, "artifact_name")
    cfg = resolver.resolve(source_id)
    if (schema_name, table_name) not in cfg.allowed_tables:
        raise IngressError(
            "DUCK_SOURCE_NOT_ALLOWED", f"source table is not allowed: {source_id}.{schema_name}.{table_name}",
            "Choose a table present in the configured source allowlist.", "Authorization",
        )
    budget = budget or SnapshotBudget(cfg.max_rows, cfg.max_bytes)
    max_rows = min(budget.max_rows, cfg.max_rows)
    max_bytes = min(budget.max_bytes, cfg.max_bytes)
    if max_rows <= 0 or max_bytes <= 0 or budget.batch_rows <= 0:
        raise IngressError("DUCK_ARGUMENT_ERROR", "snapshot budgets must be positive", "Use positive row, byte, and batch limits.", "Validation")

    pg = psycopg2.connect(cfg.uri)
    pg.autocommit = False
    row_count = 0
    byte_count = 0
    transaction_started = False
    try:
        with pg.cursor() as meta:
            meta.execute("SET TRANSACTION READ ONLY")
            meta.execute("SET LOCAL statement_timeout = '120000ms'")
            meta.execute("SET LOCAL lock_timeout = '5000ms'")
            meta.execute(
                """
                SELECT column_name, data_type, udt_name, numeric_precision, numeric_scale
                  FROM information_schema.columns
                 WHERE table_schema=%s AND table_name=%s
                 ORDER BY ordinal_position
                """,
                (schema_name, table_name),
            )
            raw_columns = meta.fetchall()
        if not raw_columns:
            raise IngressError(
                "DUCK_SOURCE_NOT_FOUND", f"missing table: {schema_name}.{table_name}",
                "Check the configured source alias, schema, and table name.", "Resolution",
            )
        columns = tuple(_map_column(r) for r in raw_columns)
        ddl = ", ".join(f"{_duck_ident(c.name)} {c.duck_type}" for c in columns)
        placeholders = ", ".join("?" for _ in columns)
        insert_sql = f"INSERT INTO {_duck_ident(artifact_name)} VALUES ({placeholders})"

        duck.execute("BEGIN")
        transaction_started = True
        duck.execute(f"CREATE TABLE {_duck_ident(artifact_name)} ({ddl})")
        with pg.cursor(name=f"duck_snapshot_{uuid.uuid4().hex[:12]}") as cur:
            cur.itersize = budget.batch_rows
            cur.execute(sql.SQL("SELECT * FROM {}.{}").format(sql.Identifier(schema_name), sql.Identifier(table_name)))
            while True:
                rows = cur.fetchmany(budget.batch_rows)
                if not rows:
                    break
                converted = []
                for row in rows:
                    row_count += 1
                    if row_count > max_rows:
                        raise IngressError(
                            "DUCK_SOURCE_BUDGET_EXCEEDED", f"source exceeds max_rows={max_rows}",
                            "Register a smaller source table or raise the operator-controlled snapshot budget.", "Budget",
                        )
                    out = tuple(_convert_value(v, s) for v, s in zip(row, columns, strict=True))
                    byte_count += sum(_estimate_value(v) for v in out)
                    if byte_count > max_bytes:
                        raise IngressError(
                            "DUCK_SOURCE_BUDGET_EXCEEDED", f"source exceeds max_bytes={max_bytes}",
                            "Register a smaller source table or raise the operator-controlled snapshot budget.", "Budget",
                        )
                    converted.append(out)
                duck.executemany(insert_sql, converted)
        duck.execute("COMMIT")
        pg.rollback()  # end the read-only source snapshot; no writes are ever committed
        return SnapshotResult(source_id, schema_name, table_name, artifact_name, row_count, byte_count, columns)
    except Exception:
        if transaction_started:
            try:
                duck.execute("ROLLBACK")
            except Exception:
                pass
        pg.rollback()
        raise
    finally:
        pg.close()
