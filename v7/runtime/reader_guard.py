"""Fail-closed application-layer guard for Phase 1 query-only readers.

Plan §3.3: same-process query-only connections may run read-only statements
and connection-local TEMP staging. Persistent DDL/DML, ATTACH, INSTALL,
LOAD, and unknown SQL are rejected. Classification uses DuckDB's statement
parser plus tokenizer; if either is unavailable the statement is rejected.

Native connect(read_only=True) is used when compatible. The only writable
fallback is the verified same-process writer configuration conflict
(ConnectionException: different configuration than existing connections)
and only for an existing database file. Missing paths, :memory:, and
unrelated errors do not create a database.

The public reader API is GuardedReaderConnection. Raw DuckDBPyConnection
handles are stored in a module-private lease registry, never in the
instance dict, and never returned to callers.
"""
from __future__ import annotations

import os
import threading
import weakref
from typing import Any, Callable, Optional
from weakref import WeakKeyDictionary, WeakSet

DEFAULT_READER_LIMIT = 4
HARD_READER_CAP = 16

_TEMP_SCHEMAS = frozenset({"temp", "pg_temp"})
_SELECT_HEADS = frozenset(
    {
        "SELECT",
        "WITH",
        "FROM",
        "SHOW",
        "DESCRIBE",
        "DESC",
        "SUMMARIZE",
        "TABLE",
        "VALUES",
    }
)
_UNPROVABLE_KWS = frozenset({"PIVOT", "UNPIVOT", "LATERAL", "ASOF", "POSITIONAL"})
_SCALAR_FN_TYPES = frozenset({"scalar", "aggregate", "window"})
_TABLE_FN_TYPES = frozenset({"table", "table_macro", "pragma"})
_WRITER_READONLY_CONFIG_MSG = (
    "Can't open a connection to same database file with a different configuration "
    "than existing connections"
)
_TX_OK = frozenset({"BEGIN", "START", "COMMIT", "ROLLBACK", "ABORT", "END"})
_FETCH_METHODS = (
    "fetchall",
    "fetchone",
    "fetchmany",
    "fetchdf",
    "fetch_df",
    "fetch_df_chunk",
    "fetchnumpy",
    "fetch_arrow_table",
    "fetch_record_batch",
    "df",
    "arrow",
    "pl",
    "torch",
    "to_arrow_table",
    "to_arrow_reader",
)
_FETCH_ATTRS = frozenset(_FETCH_METHODS + ("description", "rowcount"))
_JOIN_PREFIX = frozenset(
    {
        "JOIN",
        "INNER",
        "LEFT",
        "RIGHT",
        "FULL",
        "CROSS",
        "NATURAL",
        "OUTER",
        "SEMI",
        "ANTI",
        "POSITIONAL",
        "ASOF",
        "STRAIGHT",
    }
)
_FROM_STOP = frozenset(
    {
        "WHERE",
        "GROUP",
        "HAVING",
        "ORDER",
        "LIMIT",
        "OFFSET",
        "UNION",
        "EXCEPT",
        "INTERSECT",
        "WINDOW",
        "QUALIFY",
        "RETURNING",
    }
)
_HEAD_RELATIONS = frozenset({"TABLE", "DESCRIBE", "DESC", "SUMMARIZE"})
_IDENT_STOP = frozenset(
    {
        "VALUES",
        "SET",
        "SELECT",
        "WHERE",
        "FROM",
        "USING",
        "ON",
        "AS",
        "WITH",
        "BY",
        "(",
        ")",
        ",",
        "JOIN",
        "LEFT",
        "RIGHT",
        "FULL",
        "INNER",
        "CROSS",
        "NATURAL",
        "OUTER",
        "GROUP",
        "ORDER",
        "LIMIT",
        "OFFSET",
        "UNION",
        "EXCEPT",
        "INTERSECT",
        "WINDOW",
        "QUALIFY",
        "RETURNING",
        "HAVING",
        "LATERAL",
    }
)
_FORBIDDEN_METHODS = frozenset(
    {
        "sql",
        "query",
        "from_query",
        "append",
        "checkpoint",
        "create_function",
        "duplicate",
        "from_arrow",
        "from_csv_auto",
        "from_df",
        "from_parquet",
        "install_extension",
        "load_extension",
        "read_csv",
        "read_json",
        "read_parquet",
        "register",
        "register_filesystem",
        "remove_function",
        "table",
        "table_function",
        "tf",
        "unregister",
        "unregister_filesystem",
        "values",
        "view",
        "extract_statements",
    }
)
_NOT_CALL_HEADS = frozenset(
    {
        "SELECT",
        "WITH",
        "FROM",
        "WHERE",
        "VALUES",
        "SET",
        "AND",
        "OR",
        "JOIN",
        "ON",
        "AS",
        "IN",
        "NOT",
        "IS",
        "CASE",
        "WHEN",
        "THEN",
        "ELSE",
        "END",
        "UNION",
        "EXCEPT",
        "INTERSECT",
        "ORDER",
        "GROUP",
        "HAVING",
        "LIMIT",
        "OFFSET",
        "CREATE",
        "TABLE",
        "INSERT",
        "INTO",
        "UPDATE",
        "DELETE",
        "USING",
        "TEMP",
        "TEMPORARY",
        "REPLACE",
        "EXPLAIN",
        "ANALYZE",
        "PRAGMA",
        "BEGIN",
        "COMMIT",
        "ROLLBACK",
        "BETWEEN",
        "LIKE",
        "ILIKE",
        "OVER",
        "PARTITION",
        "WINDOW",
        "LEFT",
        "RIGHT",
        "INNER",
        "OUTER",
        "CROSS",
        "NATURAL",
        "PIVOT",
        "UNPIVOT",
        "FILTER",
        "RETURNING",
        "LATERAL",
        "RECURSIVE",
        "MATERIALIZED",
    }
)
_SIDE_EFFECT_FNS = frozenset(
    {
        "nextval",
        "setval",
        "currval",
        "checkpoint",
        "force_checkpoint",
        "sleep_ms",
        "write_log",
        "query",
        "query_table",
        "sql",
        "copy",
        "import_database",
        "export_database",
    }
)
_PURE_TABLE_FNS = frozenset(
    {
        "duckdb_tables",
        "duckdb_columns",
        "duckdb_schemas",
        "duckdb_views",
        "duckdb_indexes",
        "duckdb_constraints",
        "duckdb_functions",
        "duckdb_databases",
        "duckdb_extensions",
        "duckdb_settings",
        "duckdb_types",
        "duckdb_sequences",
        "duckdb_temporary_files",
        "pragma_table_info",
        "pragma_database_list",
        "generate_series",
        "range",
        "unnest",
        "repeat",
        "table_info",
    }
)

__all__ = (
    "DEFAULT_READER_LIMIT",
    "HARD_READER_CAP",
    "ReaderGuardError",
    "ReaderAdmissionError",
    "GuardedReaderConnection",
    "ReaderPool",
    "connect_reader",
    "reader_execute",
    "reader_sql_allowed",
)


class ReaderGuardError(RuntimeError):
    """Reader connection rejected a forbidden statement or API."""


class ReaderAdmissionError(ReaderGuardError):
    """Reader pool rejected an acquire (admission cap or closed pool)."""


class _Resource:
    """Shared raw-handle lifetime for one root wrapper and its cursor children."""

    __slots__ = (
        "raw",
        "on_close",
        "notified",
        "lock",
        "cond",
        "in_flight",
        "op_threads",
        "raw_closed",
        "root_closed",
        "wrappers",
        "root_ref",
        "live",
    )

    def __init__(self, raw, on_close: Optional[Callable[[Any], None]], root: Any):
        self.raw = raw
        self.on_close = on_close
        self.notified = False
        self.lock = threading.RLock()
        self.cond = threading.Condition(self.lock)
        self.in_flight = 0
        self.op_threads: dict[int, int] = {}
        self.raw_closed = False
        self.root_closed = False
        self.wrappers: WeakSet = WeakSet()
        self.root_ref = weakref.ref(root)
        self.live = 0


class _Lease:
    __slots__ = ("resource", "closed", "parent", "children")

    def __init__(self, resource: _Resource, *, parent: Optional[Any] = None):
        self.resource = resource
        self.closed = False
        self.parent = weakref.ref(parent) if parent is not None else None
        self.children: WeakSet = WeakSet()


_LEASES: WeakKeyDictionary = WeakKeyDictionary()


def _is_child_lease(rec: _Lease) -> bool:
    return rec.parent is not None


def _notify_owner_locked(res: _Resource):
    """Return the on_close callback once. Caller holds res.lock."""
    if res.notified:
        return None
    res.notified = True
    return res.on_close


def _close_resource_raw(res: _Resource, reader: Optional[Any]) -> None:
    raw = None
    cb = None
    owner = reader
    with res.lock:
        if not res.raw_closed:
            res.raw_closed = True
            raw = res.raw
        cb = _notify_owner_locked(res)
        if owner is None and res.root_ref is not None:
            owner = res.root_ref()
    try:
        if raw is not None:
            closer = getattr(raw, "close", None)
            if callable(closer):
                closer()
    finally:
        if cb is not None:
            try:
                cb(owner)
            except Exception:
                pass


def _finalize_resource_if_last(res: _Resource) -> None:
    with res.lock:
        res.live = max(res.live - 1, 0)
        if res.raw_closed or res.live > 0 or res.in_flight > 0:
            return
    _close_resource_raw(res, None)


def _install_wrapper(wrapper: Any, rec: _Lease) -> None:
    res = rec.resource
    with res.lock:
        res.live += 1
        res.wrappers.add(wrapper)
    _LEASES[wrapper] = rec
    weakref.finalize(wrapper, _finalize_resource_if_last, res)


def _begin_op(wrapper: GuardedReaderConnection) -> _Resource:
    rec = _LEASES.get(wrapper)
    if rec is None:
        raise ReaderGuardError("reader connection is closed")
    res = rec.resource
    ident = threading.get_ident()
    with res.lock:
        if res.raw_closed:
            raise ReaderGuardError("reader connection is closed")
        if rec.closed or res.root_closed:
            if res.op_threads.get(ident, 0) <= 0:
                raise ReaderGuardError("reader connection is closed")
        res.in_flight += 1
        res.op_threads[ident] = res.op_threads.get(ident, 0) + 1
    return res


def _end_op(wrapper: GuardedReaderConnection, res: _Resource) -> None:
    ident = threading.get_ident()
    close_now = False
    with res.lock:
        res.in_flight = max(res.in_flight - 1, 0)
        held = res.op_threads.get(ident, 0) - 1
        if held <= 0:
            res.op_threads.pop(ident, None)
        else:
            res.op_threads[ident] = held
        if res.in_flight == 0:
            res.cond.notify_all()
        if res.root_closed and res.in_flight == 0 and not res.raw_closed:
            close_now = True
    if close_now:
        owner = res.root_ref() if res.root_ref is not None else wrapper
        _close_resource_raw(res, owner)


def _duckdb_mod():
    try:
        import duckdb
    except ImportError:
        return None
    return duckdb


def _norm_kw(text: str) -> str:
    return text.strip().strip(",;").upper()


def _is_quoted_ident(text: str) -> bool:
    token = text.strip().strip(",;")
    return len(token) >= 2 and token[0] == '"' and token[-1] == '"'


def _kw(text: str) -> str:
    """Uppercase keyword text, or empty if the token is a quoted identifier."""
    if _is_quoted_ident(text):
        return ""
    return _norm_kw(text)


def _unquote_ident(text: str) -> str:
    token = text.strip().strip(",;")
    if len(token) >= 2 and token[0] == '"' and token[-1] == '"':
        return token[1:-1].replace('""', '"')
    return token


def _is_dot_token(text: str) -> bool:
    return text.strip() == "." or _unquote_ident(text) == "."


def _kw_or_sym(text: str) -> str:
    stripped = text.strip()
    if stripped in {"(", ")", ",", ";", ".", "*"}:
        return stripped
    return _kw(text)


def _is_comma_token(text: str) -> bool:
    return text.strip() == ","


def _kind_name(typ: Any) -> str:
    name = getattr(typ, "name", None)
    if isinstance(name, str):
        return name.lower()
    text = str(typ).lower()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text


def _significant_tokens(sql: str, duckdb_mod) -> list[tuple[Any, str]]:
    raw = duckdb_mod.tokenize(sql)
    comment = duckdb_mod.token_type.comment
    out: list[tuple[Any, str]] = []
    for i, (start, typ) in enumerate(raw):
        end = raw[i + 1][0] if i + 1 < len(raw) else len(sql)
        text = sql[start:end]
        if typ == comment or not text.strip():
            continue
        out.append((typ, text))
    return out


def _ident_chain(toks: list[tuple[Any, str]], idx: int) -> Optional[list[str]]:
    parts: list[str] = []
    i = idx
    n = len(toks)
    while i < n:
        typ, text = toks[i]
        kind = _kind_name(typ)
        word = _unquote_ident(text)
        if not word:
            break
        if word == ".":
            i += 1
            continue
        if "operator" in kind or "numeric" in kind or "string" in kind:
            break
        if _kw(text) in _IDENT_STOP:
            break
        parts.append(word)
        i += 1
        if i < n and _unquote_ident(toks[i][1]) == ".":
            i += 1
            continue
        break
    return parts or None


def _is_create_temp_table(toks: list[tuple[Any, str]]) -> bool:
    if not toks or _norm_kw(toks[0][1]) != "CREATE":
        return False
    i = 1
    if (
        i + 1 < len(toks)
        and _norm_kw(toks[i][1]) == "OR"
        and _norm_kw(toks[i + 1][1]) == "REPLACE"
    ):
        i += 2
    if i >= len(toks) or _norm_kw(toks[i][1]) not in {"TEMP", "TEMPORARY"}:
        return False
    i += 1
    return i < len(toks) and _norm_kw(toks[i][1]) == "TABLE"


def _transaction_allowed(toks: list[tuple[Any, str]]) -> bool:
    if not toks:
        return False
    words = [_norm_kw(t[1]) for t in toks]
    if words[0] not in _TX_OK:
        return False
    return "WRITE" not in words


def _pragma_table_info(toks: list[tuple[Any, str]]) -> bool:
    if len(toks) < 2:
        return False
    return _norm_kw(toks[0][1]) == "PRAGMA" and _unquote_ident(toks[1][1]).lower() == "table_info"


def _select_like(toks: list[tuple[Any, str]]) -> bool:
    if not toks:
        return False
    if _pragma_table_info(toks):
        return True
    first = _norm_kw(toks[0][1])
    if first == "(":
        return True
    return first in _SELECT_HEADS


def _explain_allowed(toks: list[tuple[Any, str]]) -> bool:
    if not toks or _norm_kw(toks[0][1]) != "EXPLAIN":
        return False
    rest = toks[1:]
    if rest and _norm_kw(rest[0][1]) == "ANALYZE":
        return False
    return _select_like(rest)


def _dml_target(toks: list[tuple[Any, str]], kind: str) -> Optional[list[str]]:
    depth = 0
    i = 0
    n = len(toks)
    while i < n:
        _typ, text = toks[i]
        word = _norm_kw(text)
        if word == "(":
            depth += 1
            i += 1
            continue
        if word == ")":
            depth = max(depth - 1, 0)
            i += 1
            continue
        if depth != 0:
            i += 1
            continue
        if kind == "INSERT" and word == "INSERT":
            j = i + 1
            if j < n and _norm_kw(toks[j][1]) == "OR":
                j += 1
                if j < n and _norm_kw(toks[j][1]) in {"REPLACE", "IGNORE"}:
                    j += 1
            if j < n and _norm_kw(toks[j][1]) == "INTO":
                return _ident_chain(toks, j + 1)
            return None
        if kind == "UPDATE" and word == "UPDATE":
            return _ident_chain(toks, i + 1)
        if kind == "DELETE" and word == "DELETE":
            j = i + 1
            if j < n and _norm_kw(toks[j][1]) == "FROM":
                return _ident_chain(toks, j + 1)
            if j < n and _norm_kw(toks[j][1]) == "TABLE":
                return _ident_chain(toks, j + 1)
            return _ident_chain(toks, j)
        if word == "TRUNCATE":
            j = i + 1
            if j < n and _norm_kw(toks[j][1]) == "TABLE":
                j += 1
            return _ident_chain(toks, j)
        i += 1
    return None


def _is_connection_like(obj: Any) -> bool:
    if obj is None or isinstance(obj, GuardedReaderConnection):
        return False
    mod = _duckdb_mod()
    cls = getattr(mod, "DuckDBPyConnection", None) if mod is not None else None
    if cls is not None and isinstance(obj, cls):
        return True
    return type(obj).__name__ == "DuckDBPyConnection"


def _raw_handle(wrapper: GuardedReaderConnection):
    rec = _LEASES.get(wrapper)
    if rec is None:
        raise ReaderGuardError("reader connection is closed")
    res = rec.resource
    ident = threading.get_ident()
    with res.lock:
        if res.raw_closed or res.raw is None:
            raise ReaderGuardError("reader connection is closed")
        if rec.closed or res.root_closed:
            if res.op_threads.get(ident, 0) <= 0:
                raise ReaderGuardError("reader connection is closed")
        return res.raw


def _bind_on_close(wrapper: GuardedReaderConnection, on_close) -> None:
    rec = _LEASES.get(wrapper)
    if rec is None:
        raise ReaderGuardError("reader connection is closed")
    res = rec.resource
    with res.lock:
        if rec.closed or _is_child_lease(rec) or res.root_closed or res.raw_closed:
            raise ReaderGuardError("reader connection is closed")
        if res.on_close is not None:
            raise ReaderGuardError("reader connection is already bound")
        res.on_close = on_close


def _wrap_result(owner: GuardedReaderConnection, result: Any):
    rec = _LEASES.get(owner)
    raw = rec.resource.raw if rec is not None else None
    if result is owner or result is raw:
        return owner
    if _is_connection_like(result):
        closer = getattr(result, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:
                pass
        raise ReaderGuardError("reader connection refuses duplicated handles")
    return result


def _catalog_execute(conn, sql: str, params=None):
    if conn is None:
        return None
    if isinstance(conn, GuardedReaderConnection):
        res = _begin_op(conn)
        try:
            raw = _raw_handle(conn)
            if params is None:
                return raw.execute(sql)
            return raw.execute(sql, params)
        finally:
            _end_op(conn, res)
    if params is None:
        return conn.execute(sql)
    return conn.execute(sql, params)


def _catalog_parts_match(catalog_name, schema_name, object_name, parts: list[str]) -> bool:
    n = len(parts)
    if n == 0 or n > 3 or object_name is None:
        return False
    if not _catalog_name_eq(object_name, parts[-1], quoted=False):
        return False
    if n >= 2 and not _catalog_name_eq(schema_name, parts[-2], quoted=False):
        return False
    if n == 3 and not _catalog_name_eq(catalog_name, parts[0], quoted=False):
        return False
    return True


def _is_temp_table(conn, parts: list[str]) -> bool:
    if conn is None or not parts or len(parts) > 3:
        return False
    table = parts[-1]
    schema = parts[-2] if len(parts) >= 2 else None
    if schema is not None and schema.lower() not in _TEMP_SCHEMAS:
        return False
    try:
        rows = _catalog_execute(
            conn,
            "SELECT database_name, schema_name, table_name, temporary FROM duckdb_tables() "
            "WHERE table_name = ? OR lower(table_name) = lower(?)",
            [table, table],
        ).fetchall()
    except Exception:
        return False
    for catalog, sch, name, temporary in rows:
        if not _catalog_parts_match(catalog, sch, name, parts):
            continue
        if temporary or str(sch).lower() in _TEMP_SCHEMAS:
            return True
    return False


def _temp_dml_allowed(conn, toks: list[tuple[Any, str]], kind: str) -> bool:
    target = _dml_target(toks, kind)
    if not target:
        return False
    return _is_temp_table(conn, target)


def _extract_statements(duckdb_mod, sql: str):
    extract = getattr(duckdb_mod, "extract_statements", None)
    if extract is None:
        return None
    try:
        return extract(sql)
    except Exception:
        return None


def _is_column_list_name(toks: list[tuple[Any, str]], idx: int) -> bool:
    """CREATE TABLE t ( ... ) / INSERT INTO t ( ... ) column lists are not calls."""
    if idx <= 0:
        return False
    prev = _kw(toks[idx - 1][1])
    return prev in {"TABLE", "INTO"}


def _can_be_name(typ: Any, text: str) -> bool:
    word = _unquote_ident(text)
    if not word or word in {".", ",", ";", "(", ")", "*"}:
        return False
    kind = _kind_name(typ)
    if "string" in kind or "operator" in kind:
        return False
    if "numeric" in kind:
        return False
    return True


def _is_filter_clause(toks: list[tuple[Any, str]], idx: int) -> bool:
    if _kw(toks[idx][1]) != "FILTER":
        return False
    n = len(toks)
    if idx + 1 >= n or _unquote_ident(toks[idx + 1][1]) != "(":
        return False
    j = _skip_empty_toks(toks, idx + 2)
    return j < n and _kw(toks[j][1]) == "WHERE"


def _call_identity(toks: list[tuple[Any, str]], head_idx: int) -> Optional[tuple[list[str], list[bool]]]:
    """Qualified function identity ending at head_idx, with per-part quoted flags."""
    typ, text = toks[head_idx]
    if not _can_be_name(typ, text):
        return None
    if not _is_quoted_ident(text) and _kw(text) in _NOT_CALL_HEADS:
        if _kw(text) != "FILTER" or _is_filter_clause(toks, head_idx):
            return None
    if _is_column_list_name(toks, head_idx):
        return None
    parts = [_unquote_ident(text)]
    quoted = [_is_quoted_ident(text)]
    j = head_idx - 1
    while j >= 0 and _is_dot_token(toks[j][1]):
        j -= 1
        if j < 0 or not _can_be_name(toks[j][0], toks[j][1]):
            return None
        parts.append(_unquote_ident(toks[j][1]))
        quoted.append(_is_quoted_ident(toks[j][1]))
        j -= 1
    parts.reverse()
    quoted.reverse()
    return parts, quoted


def _call_identities(toks: list[tuple[Any, str]]) -> list[tuple[list[str], list[bool], int]]:
    out: list[tuple[list[str], list[bool], int]] = []
    n = len(toks)
    for i in range(n - 1):
        if _unquote_ident(toks[i + 1][1]) != "(":
            continue
        ident = _call_identity(toks, i)
        if ident is None:
            continue
        out.append((ident[0], ident[1], i))
    return out


def _call_expected_type(toks: list[tuple[Any, str]], head_idx: int) -> str:
    depth = 0
    ctx = {0: "scalar"}
    for i in range(head_idx):
        word = _unquote_ident(toks[i][1])
        kw = _kw(toks[i][1])
        if word == "(":
            depth += 1
            ctx.setdefault(depth, "scalar")
            continue
        if word == ")":
            ctx.pop(depth, None)
            depth = max(depth - 1, 0)
            continue
        if not kw:
            continue
        if kw in {"SELECT", "VALUES", "WHERE", "HAVING", "SET"}:
            ctx[depth] = "scalar"
        elif kw in {"FROM", "JOIN", "LATERAL", "TABLE", "PRAGMA"}:
            ctx[depth] = "table"
    return ctx.get(depth, "scalar")


def _function_catalog_rows(conn, name: str):
    try:
        cur = _catalog_execute(
            conn,
            "SELECT database_name, schema_name, function_name, function_type, "
            "internal, has_side_effects FROM duckdb_functions() "
            "WHERE function_name = ? OR lower(function_name) = lower(?)",
            [name, name],
        )
        if cur is None:
            return None
        return cur.fetchall()
    except Exception:
        return None


def _catalog_name_eq(catalog_name: Any, part: str, quoted: bool) -> bool:
    if catalog_name is None:
        return False
    text = str(catalog_name)
    if quoted:
        return text == part
    return text == part or text.lower() == part.lower()


def _row_matches_identity(row, parts: list[str], quoted: list[bool]) -> bool:
    database_name, schema_name, function_name = row[0], row[1], row[2]
    n = len(parts)
    if n == 0 or n > 3 or n != len(quoted):
        return False
    if not _catalog_name_eq(function_name, parts[-1], quoted[-1]):
        return False
    if n == 1:
        return True
    if n == 2:
        return _catalog_name_eq(schema_name, parts[0], quoted[0])
    return _catalog_name_eq(database_name, parts[0], quoted[0]) and _catalog_name_eq(
        schema_name, parts[1], quoted[1]
    )


def _is_proven_builtin(row, expected: str) -> bool:
    database_name, _schema, function_name, function_type, internal, has_side_effects = row
    if internal is not True:
        return False
    if str(database_name).lower() != "system":
        return False
    ftype = str(function_type).lower() if function_type is not None else ""
    fname = str(function_name).lower() if function_name is not None else ""
    if expected == "table":
        if ftype not in {"table", "pragma"}:
            return False
        return fname in _PURE_TABLE_FNS
    if ftype not in _SCALAR_FN_TYPES:
        return False
    return has_side_effects is False


def _function_call_forbidden(parts: list[str], quoted: list[bool], expected: str, conn) -> bool:
    if not parts or len(parts) != len(quoted) or len(parts) > 3:
        return True
    final = parts[-1].lower()
    if final in _SIDE_EFFECT_FNS or final.startswith("read_") or final.endswith("_scan"):
        return True
    if conn is None:
        return True
    rows = _function_catalog_rows(conn, parts[-1])
    if not rows:
        return True
    matched = [row for row in rows if _row_matches_identity(row, parts, quoted)]
    if not matched:
        return True
    # Unqualified names match every schema; a single non-builtin overload taints the identity.
    for row in matched:
        if row[4] is not True or str(row[0]).lower() != "system":
            return True
    family = []
    for row in matched:
        ftype = str(row[3]).lower() if row[3] is not None else ""
        if expected == "table":
            if ftype in _TABLE_FN_TYPES:
                family.append(row)
        elif ftype in _SCALAR_FN_TYPES or ftype == "macro":
            family.append(row)
    if not family:
        return True
    for row in family:
        if not _is_proven_builtin(row, expected):
            return True
    return False


def _has_prohibited_side_effects(toks: list[tuple[Any, str]], conn) -> bool:
    for parts, quoted, idx in _call_identities(toks):
        expected = _call_expected_type(toks, idx)
        if _function_call_forbidden(parts, quoted, expected, conn):
            return True
    return False


def _skip_empty_toks(toks: list[tuple[Any, str]], idx: int) -> int:
    n = len(toks)
    i = idx
    while i < n and not toks[i][1].strip():
        i += 1
    return i


def _ident_span(toks: list[tuple[Any, str]], idx: int) -> tuple[Optional[list[str]], int]:
    parts = _ident_chain(toks, idx)
    if not parts:
        return None, idx
    i = idx
    n = len(toks)
    remaining = list(parts)
    while remaining and i < n:
        word = _unquote_ident(toks[i][1])
        if word == ".":
            i += 1
            continue
        if word == remaining[0]:
            remaining.pop(0)
            i += 1
            continue
        break
    return parts, i


def _balanced_paren_span(toks: list[tuple[Any, str]], idx: int) -> Optional[tuple[int, int]]:
    n = len(toks)
    if idx >= n or _unquote_ident(toks[idx][1]) != "(":
        return None
    after = _skip_balanced_parens(toks, idx)
    if after <= idx + 1 or after > n:
        return None
    if _unquote_ident(toks[after - 1][1]) != ")":
        return None
    return idx + 1, after


def _append_walked_ref(refs: list, ref) -> None:
    kind, payload = ref
    if kind == "subquery":
        if payload is None:
            refs.append(("unknown", None))
            return
        refs.extend(payload)
        return
    if kind == "call":
        inner = payload[1] if isinstance(payload, tuple) and len(payload) == 2 else None
        if inner:
            refs.extend(inner)
        return
    refs.append(ref)


def _consume_table_ref(toks: list[tuple[Any, str]], idx: int):
    i = _skip_empty_toks(toks, idx)
    n = len(toks)
    if i >= n:
        return ("unknown", None), i
    if _norm_kw(toks[i][1]) == "LATERAL":
        i = _skip_empty_toks(toks, i + 1)
        if i >= n:
            return ("unknown", None), i
    if _norm_kw(toks[i][1]) in _HEAD_RELATIONS:
        nxt = _skip_empty_toks(toks, i + 1)
        if nxt >= n:
            return ("unknown", None), nxt
        return _consume_table_ref(toks, nxt)
    word = _unquote_ident(toks[i][1])
    kind = _kind_name(toks[i][0])
    if word == "(":
        span = _balanced_paren_span(toks, i)
        if span is None:
            return ("unknown", None), i + 1
        inner_start, after = span
        inner = toks[inner_start : after - 1]
        if not inner:
            return ("unknown", None), after
        return ("subquery", _relation_refs(inner)), after
    if "string" in kind:
        return ("string", toks[i][1]), i + 1
    parts, j = _ident_span(toks, i)
    if not parts:
        return ("unknown", word), i + 1
    j = _skip_empty_toks(toks, j)
    if j < n and _unquote_ident(toks[j][1]) == "(":
        span = _balanced_paren_span(toks, j)
        if span is None:
            return ("unknown", parts), j + 1
        inner_start, after = span
        inner_refs = _relation_refs(toks[inner_start : after - 1])
        return ("call", (parts, inner_refs)), after
    return ("ident", parts), j


def _skip_alias(toks: list[tuple[Any, str]], idx: int) -> int:
    i = _skip_empty_toks(toks, idx)
    n = len(toks)
    if i >= n:
        return i
    if _norm_kw(toks[i][1]) == "AS":
        i = _skip_empty_toks(toks, i + 1)
        if i < n:
            i += 1
        return i
    word = _kw_or_sym(toks[i][1])
    if word in _FROM_STOP or word in _JOIN_PREFIX or word in {",", "ON", "USING", ")", "(", ";"}:
        return i
    if "identifier" in _kind_name(toks[i][0]):
        return i + 1
    return i


def _skip_on_using(toks: list[tuple[Any, str]], idx: int, refs: list) -> int:
    i = _skip_empty_toks(toks, idx)
    n = len(toks)
    if i >= n:
        return i
    head = _kw_or_sym(toks[i][1])
    if head not in {"ON", "USING"}:
        return i
    i += 1
    start = i
    depth = 0
    while i < n:
        word = _kw_or_sym(toks[i][1])
        if word == "(":
            depth += 1
        elif word == ")":
            if depth == 0:
                break
            depth -= 1
        elif depth == 0 and (
            word == "," or word in _FROM_STOP or word in _JOIN_PREFIX
        ):
            break
        i += 1
    if start >= i:
        refs.append(("unknown", None))
    else:
        refs.extend(_relation_refs(toks[start:i]))
    return i


def _skip_join_operator(toks: list[tuple[Any, str]], idx: int) -> Optional[int]:
    i = idx
    n = len(toks)
    saw_join = False
    while i < n and _norm_kw(toks[i][1]) in _JOIN_PREFIX:
        if _norm_kw(toks[i][1]) == "JOIN":
            saw_join = True
            i += 1
            break
        i += 1
    return i if saw_join else None


def _collect_from_list(toks: list[tuple[Any, str]], idx: int, refs: list) -> int:
    i = _skip_empty_toks(toks, idx)
    n = len(toks)
    first = True
    while i < n:
        i = _skip_empty_toks(toks, i)
        if i >= n:
            break
        word = _kw_or_sym(toks[i][1])
        if word == ")" or word in _FROM_STOP:
            return i
        if not first:
            if word == ",":
                i += 1
            else:
                joined = _skip_join_operator(toks, i)
                if joined is None:
                    return i
                i = joined
        first = False
        start_ref = i
        ref, i = _consume_table_ref(toks, i)
        if i <= start_ref:
            refs.append(("unknown", None))
            i = start_ref + 1
        else:
            _append_walked_ref(refs, ref)
        i = _skip_alias(toks, i)
        i = _skip_on_using(toks, i, refs)
    return i


def _relation_refs(toks: list[tuple[Any, str]]) -> list[tuple[str, Any]]:
    refs: list[tuple[str, Any]] = []
    n = len(toks)
    i = 0
    if toks and _norm_kw(toks[0][1]) in _HEAD_RELATIONS:
        ref, i = _consume_table_ref(toks, 1)
        _append_walked_ref(refs, ref)
    while i < n:
        word = _unquote_ident(toks[i][1])
        kw = _norm_kw(toks[i][1])
        if kw == "FROM":
            i = _collect_from_list(toks, i + 1, refs)
            continue
        if word == "(":
            span = _balanced_paren_span(toks, i)
            if span is None:
                refs.append(("unknown", None))
                i += 1
                continue
            inner_start, after = span
            refs.extend(_relation_refs(toks[inner_start : after - 1]))
            i = after
            continue
        i += 1
    return refs


def _classify_relation(conn, parts: list[str]) -> str:
    if conn is None or not parts or len(parts) > 3:
        return "unknown"
    name = parts[-1]
    try:
        view_rows = _catalog_execute(
            conn,
            "SELECT database_name, schema_name, view_name, temporary FROM duckdb_views() "
            "WHERE view_name = ? OR lower(view_name) = lower(?)",
            [name, name],
        ).fetchall()
    except Exception:
        return "unknown"
    for catalog, sch, view_name, temporary in view_rows or []:
        if not _catalog_parts_match(catalog, sch, view_name, parts):
            continue
        if temporary or str(sch).lower() in _TEMP_SCHEMAS:
            continue
        return "persistent_view"
    try:
        table_rows = _catalog_execute(
            conn,
            "SELECT database_name, schema_name, table_name, temporary FROM duckdb_tables() "
            "WHERE table_name = ? OR lower(table_name) = lower(?)",
            [name, name],
        ).fetchall()
    except Exception:
        return "unknown"
    matched_table = None
    matched_temp_view = False
    for catalog, sch, view_name, temporary in view_rows or []:
        if not _catalog_parts_match(catalog, sch, view_name, parts):
            continue
        if temporary or str(sch).lower() in _TEMP_SCHEMAS:
            matched_temp_view = True
    for catalog, sch, table_name, temporary in table_rows or []:
        if not _catalog_parts_match(catalog, sch, table_name, parts):
            continue
        if temporary or str(sch).lower() in _TEMP_SCHEMAS:
            matched_table = "temp_table"
        elif matched_table is None:
            matched_table = "base_table"
    if matched_temp_view:
        return "temp_view"
    if matched_table is not None:
        return matched_table
    try:
        seq_rows = _catalog_execute(
            conn,
            "SELECT database_name, schema_name, sequence_name FROM duckdb_sequences() "
            "WHERE sequence_name = ? OR lower(sequence_name) = lower(?)",
            [name, name],
        ).fetchall()
    except Exception:
        seq_rows = None
    for catalog, sch, seq_name in seq_rows or []:
        if _catalog_parts_match(catalog, sch, seq_name, parts):
            return "sequence"
    return "unknown"


def _skip_balanced_parens(toks: list[tuple[Any, str]], idx: int) -> int:
    i = idx
    n = len(toks)
    if i >= n or _unquote_ident(toks[i][1]) != "(":
        return i
    depth = 0
    while i < n:
        word = _unquote_ident(toks[i][1])
        if word == "(":
            depth += 1
        elif word == ")":
            depth -= 1
            i += 1
            if depth == 0:
                return i
            continue
        i += 1
    return i


def _skip_explain_prefix(toks: list[tuple[Any, str]]) -> int:
    i = _skip_empty_toks(toks, 0)
    n = len(toks)
    if i < n and _kw(toks[i][1]) == "EXPLAIN":
        i = _skip_empty_toks(toks, i + 1)
        if i < n and _kw(toks[i][1]) == "ANALYZE":
            i = _skip_empty_toks(toks, i + 1)
    return i


def _with_keyword_count(toks: list[tuple[Any, str]]) -> int:
    return sum(1 for _typ, text in toks if _kw(text) == "WITH")


def _has_unprovable_forms(toks: list[tuple[Any, str]]) -> bool:
    for _typ, text in toks:
        if _kw(text) in _UNPROVABLE_KWS:
            return True
    return False


def _has_delete_using(toks: list[tuple[Any, str]]) -> bool:
    depth = 0
    delete_depth: Optional[int] = None
    for _typ, text in toks:
        word = _unquote_ident(text)
        kw = _kw(text)
        if word == "(":
            depth += 1
            continue
        if word == ")":
            depth = max(depth - 1, 0)
            continue
        if kw == "DELETE":
            delete_depth = depth
        elif delete_depth is not None and kw == "USING" and depth == delete_depth:
            return True
    return False


def _parse_simple_ctes(toks: list[tuple[Any, str]]):
    """Linear non-recursive leading WITH, or None if the CTE graph is unprovable."""
    with_count = _with_keyword_count(toks)
    if with_count == 0:
        return [], 0
    if with_count != 1:
        return None
    i = _skip_explain_prefix(toks)
    n = len(toks)
    if i >= n or _kw(toks[i][1]) != "WITH":
        return None
    i = _skip_empty_toks(toks, i + 1)
    if i < n and _kw(toks[i][1]) == "RECURSIVE":
        return None
    ctes: list[tuple[str, list[tuple[Any, str]]]] = []
    seen: set[str] = set()
    while i < n:
        parts, j = _ident_span(toks, i)
        if not parts or len(parts) != 1:
            return None
        name = parts[0].lower()
        if name in seen:
            return None
        i = _skip_empty_toks(toks, j)
        if i < n and _unquote_ident(toks[i][1]) == "(":
            i = _skip_balanced_parens(toks, i)
            i = _skip_empty_toks(toks, i)
        if i >= n or _kw(toks[i][1]) != "AS":
            return None
        i = _skip_empty_toks(toks, i + 1)
        if i < n and _kw(toks[i][1]) == "NOT":
            i = _skip_empty_toks(toks, i + 1)
        if i < n and _kw(toks[i][1]) == "MATERIALIZED":
            i = _skip_empty_toks(toks, i + 1)
        if i >= n or _unquote_ident(toks[i][1]) != "(":
            return None
        body_start = i + 1
        after = _skip_balanced_parens(toks, i)
        if after <= body_start:
            return None
        body = toks[body_start : after - 1]
        ctes.append((name, body))
        seen.add(name)
        i = _skip_empty_toks(toks, after)
        if i < n and _is_comma_token(toks[i][1]):
            i = _skip_empty_toks(toks, i + 1)
            continue
        break
    if not ctes:
        return None
    return ctes, i


def _relation_forbidden(kind: str, payload: Any, conn, cte_scope: set[str]) -> bool:
    if kind == "string":
        return True
    if kind == "ident" and payload:
        if len(payload) == 1 and payload[0].lower() in cte_scope:
            return False
        classified = _classify_relation(conn, payload)
        return classified not in {"base_table", "temp_table", "temp_view"}
    return True  # unknown, unwalkable, call-as-relation, empty, or any other form


def _refs_forbidden(toks: list[tuple[Any, str]], conn, cte_scope: set[str]) -> bool:
    for kind, payload in _relation_refs(toks):
        if _relation_forbidden(kind, payload, conn, cte_scope):
            return True
    return False


def _has_forward_cte_ref(body: list[tuple[Any, str]], allowed: set[str], all_names: set[str]) -> bool:
    for kind, payload in _relation_refs(body):
        if kind == "ident" and payload and len(payload) == 1:
            name = payload[0].lower()
            if name in all_names and name not in allowed:
                return True
    return False


def _has_prohibited_relations(toks: list[tuple[Any, str]], conn) -> bool:
    if _has_unprovable_forms(toks) or _has_delete_using(toks):
        return True
    parsed = _parse_simple_ctes(toks)
    if parsed is None:
        return True
    ctes, main_idx = parsed
    if not ctes:
        return _refs_forbidden(toks, conn, set())
    all_names = {name for name, _body in ctes}
    seen: list[str] = []
    for name, body in ctes:
        allowed = set(seen)
        if _has_forward_cte_ref(body, allowed, all_names):
            return True
        if _refs_forbidden(body, conn, allowed):
            return True
        seen.append(name)
    return _refs_forbidden(toks[main_idx:], conn, set(seen))


def reader_sql_allowed(sql: str, conn=None) -> bool:
    """True only for an explicit single read-only or TEMP-staging statement."""
    if not isinstance(sql, str) or not sql.strip():
        return False
    duckdb_mod = _duckdb_mod()
    if duckdb_mod is None:
        return False
    if not hasattr(duckdb_mod, "extract_statements") or not hasattr(duckdb_mod, "tokenize"):
        return False
    statements = _extract_statements(duckdb_mod, sql)
    if statements is None:
        return False
    if len(statements) != 1:
        return False
    stype = getattr(statements[0], "type", None)
    types = getattr(duckdb_mod, "StatementType", None)
    if types is None or stype is None:
        return False
    try:
        toks = _significant_tokens(sql, duckdb_mod)
    except Exception:
        return False
    if not toks:
        return False

    forbidden = {
        types.ALTER,
        types.ANALYZE,
        types.ATTACH,
        types.CALL,
        types.COPY,
        types.COPY_DATABASE,
        types.CREATE_FUNC,
        types.DETACH,
        types.DROP,
        types.EXECUTE,
        types.EXPORT,
        types.EXTENSION,
        types.INVALID,
        types.LOAD,
        types.LOGICAL_PLAN,
        types.MERGE_INTO,
        types.MULTI,
        types.PREPARE,
        types.RELATION,
        types.SET,
        types.VACUUM,
        types.VARIABLE_SET,
    }
    for attr in ("PIVOT", "UNPIVOT"):
        extra = getattr(types, attr, None)
        if extra is not None:
            forbidden.add(extra)
    if stype in forbidden:
        return False
    allowed = False
    if stype == types.CREATE:
        allowed = _is_create_temp_table(toks)
    elif stype == types.INSERT:
        allowed = _temp_dml_allowed(conn, toks, "INSERT")
    elif stype == types.UPDATE:
        allowed = _temp_dml_allowed(conn, toks, "UPDATE")
    elif stype == types.DELETE:
        allowed = _temp_dml_allowed(conn, toks, "DELETE")
    elif stype == types.TRANSACTION:
        allowed = _transaction_allowed(toks)
    elif stype == types.EXPLAIN:
        allowed = _explain_allowed(toks)
    elif stype == types.PRAGMA:
        allowed = _pragma_table_info(toks)
    elif stype == types.SELECT:
        allowed = _select_like(toks)
    if not allowed:
        return False
    if _has_prohibited_side_effects(toks, conn):
        return False
    if _has_prohibited_relations(toks, conn):
        return False
    return True


def reader_execute(conn, sql: str, *args):
    if not isinstance(conn, GuardedReaderConnection):
        raise ReaderGuardError("reader_execute requires GuardedReaderConnection")
    return conn.execute(sql, *args) if args else conn.execute(sql)


def _database_text(database) -> Optional[str]:
    if database is None:
        return None
    try:
        text = os.fspath(database)
    except TypeError:
        return None
    if not isinstance(text, str):
        try:
            text = os.fsdecode(text)
        except Exception:
            return None
    return text


def _is_memory_database(database) -> bool:
    if database is None:
        return True
    text = _database_text(database)
    return text in {"", ":memory:"}


def _reject_memory_lookalike(database) -> None:
    if database is None:
        return
    text = _database_text(database)
    if text is None or text in {"", ":memory:"}:
        return
    stripped = text.strip()
    lowered = stripped.lower()
    if lowered == ":memory:" or lowered.startswith(":memory:"):
        raise ReaderGuardError(
            "reader connections require canonical :memory: or a filesystem path"
        )


def _is_existing_db_file(database) -> bool:
    if _is_memory_database(database):
        return False
    try:
        text = os.fspath(database)
    except TypeError:
        return False
    return os.path.isfile(text)


def _is_writer_readonly_config_conflict(exc, duckdb_module) -> bool:
    cls = getattr(duckdb_module, "ConnectionException", None)
    if cls is None or not isinstance(exc, cls):
        return False
    return _WRITER_READONLY_CONFIG_MSG in str(exc)


def _open_reader_raw(duckdb_module, database, **kwargs):
    kwargs = dict(kwargs)
    requested = kwargs.pop("read_only", None)
    if requested is False:
        raise ReaderGuardError("reader connections cannot request a writable open")
    config = kwargs.get("config")
    if isinstance(config, dict):
        mode = str(config.get("access_mode", "")).lower()
        if mode in {"read_write", "automatic"}:
            raise ReaderGuardError("reader connections cannot request a writable access_mode")
    _reject_memory_lookalike(database)
    if _is_memory_database(database):
        return duckdb_module.connect(":memory:", **kwargs)
    try:
        return duckdb_module.connect(database, read_only=True, **kwargs)
    except Exception as exc:
        if _is_writer_readonly_config_conflict(exc, duckdb_module) and _is_existing_db_file(database):
            return duckdb_module.connect(database, **kwargs)
        raise


def connect_reader(duckdb_module, database, **kwargs):
    """Open a guarded reader connection, using native read_only when compatible."""
    return GuardedReaderConnection(_open_reader_raw(duckdb_module, database, **kwargs))


class GuardedReaderConnection:
    """Owns a DuckDB connection and refuses raw access plus non-reader APIs."""

    __slots__ = ("__weakref__",)

    def __init__(
        self,
        conn,
        on_close: Optional[Callable[[GuardedReaderConnection], None]] = None,
        *,
        _parent: Optional[GuardedReaderConnection] = None,
    ):
        if _parent is not None:
            prec = _LEASES.get(_parent)
            if prec is None:
                raise ReaderGuardError("reader connection is closed")
            res = prec.resource
            with res.lock:
                if prec.closed or _is_child_lease(prec) or res.root_closed or res.raw_closed:
                    raise ReaderGuardError("reader connection is closed")
                rec = _Lease(res, parent=_parent)
                prec.children.add(self)
                _install_wrapper(self, rec)
            return
        if conn is None:
            raise ReaderGuardError("reader wrapper requires a connection")
        if isinstance(conn, GuardedReaderConnection):
            raise ReaderGuardError("reader wrapper does not accept another wrapper")
        rec = _Lease(_Resource(conn, on_close, self))
        _install_wrapper(self, rec)

    def _ensure_open(self) -> None:
        rec = _LEASES.get(self)
        if rec is None:
            raise ReaderGuardError("reader connection is closed")
        res = rec.resource
        with res.lock:
            if rec.closed or res.root_closed or res.raw_closed:
                raise ReaderGuardError("reader connection is closed")

    def _forbid_sql(self, sql: str) -> None:
        raise ReaderGuardError(f"reader connection forbids: {sql!r}")

    def _run(self, sql: str, fn):
        res = _begin_op(self)
        try:
            if not reader_sql_allowed(sql, conn=self):
                self._forbid_sql(sql)
            return _wrap_result(self, fn())
        finally:
            _end_op(self, res)

    def _call_raw(self, fn):
        res = _begin_op(self)
        try:
            return _wrap_result(self, fn(_raw_handle(self)))
        finally:
            _end_op(self, res)

    def execute(self, script, parameters=None, multiple_parameter_sets=False):
        def _call():
            raw = _raw_handle(self)
            if parameters is None and multiple_parameter_sets is False:
                return raw.execute(script)
            return raw.execute(script, parameters, multiple_parameter_sets)

        return self._run(script, _call)

    def executemany(self, script, parameters):
        return self._run(script, lambda: _raw_handle(self).executemany(script, parameters))

    def cursor(self):
        self._ensure_open()
        rec = _LEASES.get(self)
        if rec is None:
            raise ReaderGuardError("reader connection is closed")
        root = rec.parent() if rec.parent is not None else self
        if root is None:
            raise ReaderGuardError("reader connection is closed")
        return GuardedReaderConnection(None, _parent=root)

    def begin(self):
        return self._call_raw(lambda raw: raw.begin())

    def commit(self):
        return self._call_raw(lambda raw: raw.commit())

    def rollback(self):
        return self._call_raw(lambda raw: raw.rollback())

    def interrupt(self):
        res = _begin_op(self)
        try:
            return _raw_handle(self).interrupt()
        finally:
            _end_op(self, res)

    def close(self) -> None:
        rec = _LEASES.get(self)
        if rec is None:
            return
        res = rec.resource
        with res.lock:
            if rec.closed:
                return
            rec.closed = True
            children = list(rec.children)
            rec.children.clear()
            is_root = not _is_child_lease(rec)
            if is_root:
                res.root_closed = True
        for child in children:
            try:
                child.close()
            except Exception:
                pass
        if not is_root:
            _LEASES.pop(self, None)
            return
        close_now = False
        with res.lock:
            ident = threading.get_ident()
            same_thread_busy = res.op_threads.get(ident, 0) > 0
            if not same_thread_busy:
                while res.in_flight > 0:
                    res.cond.wait()
            close_now = res.in_flight == 0 and not res.raw_closed
        if close_now:
            _close_resource_raw(res, self)
            _LEASES.pop(self, None)

    @property
    def closed(self) -> bool:
        rec = _LEASES.get(self)
        if rec is None:
            return True
        res = rec.resource
        with res.lock:
            return rec.closed or res.root_closed or res.raw_closed

    @property
    def connection(self):
        raise ReaderGuardError("raw connection is not available to callers")

    @property
    def raw(self):
        raise ReaderGuardError("raw connection is not available to callers")

    def unwrap(self):
        raise ReaderGuardError("raw connection is not available to callers")

    def __enter__(self):
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def fetchone(self, *args, **kwargs):
        return self._call_raw(lambda raw: raw.fetchone(*args, **kwargs))

    def fetchall(self, *args, **kwargs):
        return self._call_raw(lambda raw: raw.fetchall(*args, **kwargs))

    def fetchmany(self, *args, **kwargs):
        return self._call_raw(lambda raw: raw.fetchmany(*args, **kwargs))

    def fetchdf(self, *args, **kwargs):
        return self._call_raw(lambda raw: raw.fetchdf(*args, **kwargs))

    def fetch_df(self, *args, **kwargs):
        return self._call_raw(lambda raw: raw.fetch_df(*args, **kwargs))

    def fetch_df_chunk(self, *args, **kwargs):
        return self._call_raw(lambda raw: raw.fetch_df_chunk(*args, **kwargs))

    def fetchnumpy(self, *args, **kwargs):
        return self._call_raw(lambda raw: raw.fetchnumpy(*args, **kwargs))

    def fetch_arrow_table(self, *args, **kwargs):
        return self._call_raw(lambda raw: raw.fetch_arrow_table(*args, **kwargs))

    def fetch_record_batch(self, *args, **kwargs):
        return self._call_raw(lambda raw: raw.fetch_record_batch(*args, **kwargs))

    def df(self, *args, **kwargs):
        return self._call_raw(lambda raw: raw.df(*args, **kwargs))

    def arrow(self, *args, **kwargs):
        return self._call_raw(lambda raw: raw.arrow(*args, **kwargs))

    def pl(self, *args, **kwargs):
        return self._call_raw(lambda raw: raw.pl(*args, **kwargs))

    def torch(self, *args, **kwargs):
        return self._call_raw(lambda raw: raw.torch(*args, **kwargs))

    def to_arrow_table(self, *args, **kwargs):
        return self._call_raw(lambda raw: raw.to_arrow_table(*args, **kwargs))

    def to_arrow_reader(self, *args, **kwargs):
        return self._call_raw(lambda raw: raw.to_arrow_reader(*args, **kwargs))

    @property
    def description(self):
        res = _begin_op(self)
        try:
            return _raw_handle(self).description
        finally:
            _end_op(self, res)

    @property
    def rowcount(self):
        res = _begin_op(self)
        try:
            return _raw_handle(self).rowcount
        finally:
            _end_op(self, res)

    def __getattr__(self, name: str):
        if name in _FORBIDDEN_METHODS:
            raise ReaderGuardError(f"reader connection forbids {name}")
        raise AttributeError(name)

    def __setattr__(self, name: str, value) -> None:
        raise ReaderGuardError("reader connection attributes are frozen")


class ReaderPool:
    """Admission-capped set of guarded reader connections (default 4, hard cap 16)."""

    DEFAULT_LIMIT = DEFAULT_READER_LIMIT
    HARD_CAP = HARD_READER_CAP

    def __init__(self, opener: Callable[[], Any], max_readers: int = DEFAULT_READER_LIMIT):
        if not callable(opener):
            raise ReaderGuardError("reader pool requires a connection opener")
        limit = int(max_readers)
        if limit < 1:
            raise ReaderGuardError("max_readers must be >= 1")
        self._opener = opener
        self._limit = min(limit, self.HARD_CAP)
        self._lock = threading.Lock()
        self._in_flight = 0
        self._acquired: set[GuardedReaderConnection] = set()
        self._closed = False
        self._guard = GuardedReaderConnection
        self._close_cb = self._on_reader_close

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def in_flight(self) -> int:
        with self._lock:
            return self._in_flight

    def acquire(self) -> GuardedReaderConnection:
        with self._lock:
            if self._closed:
                raise ReaderAdmissionError("reader pool is closed")
            if self._in_flight >= self._limit:
                raise ReaderAdmissionError(
                    f"reader admission cap {self._limit} (hard cap {self.HARD_CAP})"
                )
            self._in_flight += 1
        opened = None
        guarded = None
        claimed = False
        try:
            opened = self._opener()
            if opened is None:
                raise ReaderGuardError("reader opener returned None")
            if isinstance(opened, GuardedReaderConnection):
                rec = _LEASES.get(opened)
                if rec is None:
                    raise ReaderGuardError("reader connection is closed")
                if _is_child_lease(rec):
                    raise ReaderGuardError("reader pool cannot acquire a cursor child")
                res = rec.resource
                with res.lock:
                    if rec.closed or res.root_closed or res.raw_closed:
                        raise ReaderGuardError("reader connection is closed")
                    if _is_child_lease(rec):
                        raise ReaderGuardError("reader pool cannot acquire a cursor child")
                    if res.on_close is not None:
                        raise ReaderGuardError("reader pool cannot acquire a foreign connection")
                _bind_on_close(opened, self._close_cb)
                guarded = opened
            else:
                guarded = self._guard(opened, on_close=self._close_cb)
            claimed = True
        except Exception:
            if not claimed:
                with self._lock:
                    self._in_flight = max(self._in_flight - 1, 0)
                if not isinstance(opened, GuardedReaderConnection):
                    closer = getattr(opened, "close", None) if opened is not None else None
                    if callable(closer):
                        try:
                            closer()
                        except Exception:
                            pass
            else:
                try:
                    guarded.close()
                except Exception:
                    pass
            raise
        with self._lock:
            if self._closed:
                stale = True
            else:
                self._acquired.add(guarded)
                stale = False
        if stale:
            try:
                guarded.close()
            except Exception:
                pass
            raise ReaderAdmissionError("reader pool is closed")
        return guarded

    def release(self, reader: GuardedReaderConnection) -> None:
        if reader is None or not isinstance(reader, GuardedReaderConnection):
            raise ReaderGuardError("reader pool cannot release an unknown connection")
        rec = _LEASES.get(reader)
        if rec is None:
            raise ReaderGuardError("reader connection is closed")
        res = rec.resource
        with res.lock:
            if rec.closed or res.root_closed or res.raw_closed:
                raise ReaderGuardError("reader connection is closed")
            if _is_child_lease(rec):
                raise ReaderGuardError("reader pool cannot release a cursor child")
            if res.on_close is not self._close_cb:
                raise ReaderGuardError("reader pool cannot release a foreign connection")
        reader.close()

    def _on_reader_close(self, reader: GuardedReaderConnection) -> None:
        with self._lock:
            if reader is not None:
                self._acquired.discard(reader)
            self._in_flight = max(self._in_flight - 1, 0)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            to_close = list(self._acquired)
        for reader in to_close:
            try:
                reader.close()
            except Exception:
                pass
