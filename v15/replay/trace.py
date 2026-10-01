"""Trace v1 load/export/compare. JSON numbers stay decimal; no float."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

DIGEST_SCHEME = "md5((request-'attempt_id')::text)"

TOP_KEYS = ("version", "digest_scheme", "pool", "pool_outcome", "invokes")
POOL_KEYS = ("calls_limit", "cost_limit")
OUTCOME_KEYS = ("calls_used", "cost_used")
INVOKE_KEYS = (
    "path",
    "depth",
    "status",
    "fatal",
    "error_code",
    "return_value",
    "steps",
    "bindings",
    "blackboard",
)
STEP_KEYS = (
    "iteration",
    "result_kind",
    "logical_digest",
    "response_content",
    "recorded_cost_usd",
    "statements",
    "repl_output",
    "repl_exception_code",
)
STMT_KEYS = ("stmt_index", "sql_digest", "kind", "status", "bind_name")
BIND_KEYS = ("name", "kind", "provenance", "tool_name", "value")
BOARD_KEYS = ("key", "value")

INVOKE_STATUS = frozenset({"completed", "failed", "aborted"})
RESULT_KIND = frozenset({"continue", "return", "raise"})
STMT_KIND = frozenset({"plain", "bind_invoke", "return", "raise", "print", "assign"})
STMT_STATUS = frozenset({"pending", "running", "done", "failed", "skipped"})
BIND_KIND = frozenset({"input", "scope", "var", "tool"})
BIND_PROVENANCE = frozenset({"explicit", "scope", "hook", "repl", "delivery"})
JSON_SCALAR = (str, int, bool, Decimal, type(None))


class TraceInvalid(ValueError):
    pass


def _parse(value: str) -> Any:
    return json.loads(value, parse_int=Decimal, parse_float=Decimal)


def dumps(value: Any, *, indent: int | None = None) -> str:
    """Serialize Trace JSON. Decimal tokens are produced only here, never via placeholder replace."""

    def encode(obj: Any, level: int) -> str:
        if isinstance(obj, dict):
            if not obj:
                return "{}"
            items: list[tuple[str, str]] = []
            for key, item in obj.items():
                if not isinstance(key, str):
                    raise TypeError("dict key")
                items.append((json.dumps(key, ensure_ascii=False), encode(item, level + 1)))
            if indent is None:
                return "{" + ",".join(k + ":" + v for k, v in items) + "}"
            pad = " " * (indent * (level + 1))
            close = " " * (indent * level)
            inner = ",\n".join(pad + k + ": " + v for k, v in items)
            return "{\n" + inner + "\n" + close + "}"
        if isinstance(obj, list):
            if not obj:
                return "[]"
            encoded = [encode(item, level + 1) for item in obj]
            if indent is None:
                return "[" + ",".join(encoded) + "]"
            pad = " " * (indent * (level + 1))
            close = " " * (indent * level)
            inner = ",\n".join(pad + item for item in encoded)
            return "[\n" + inner + "\n" + close + "]"
        if isinstance(obj, str):
            return json.dumps(obj, ensure_ascii=False)
        if obj is None:
            return "null"
        if isinstance(obj, bool):
            return "true" if obj else "false"
        if type(obj) is int:
            return str(obj)
        if isinstance(obj, Decimal):
            if not obj.is_finite():
                raise TypeError("non-finite Decimal")
            if obj == obj.to_integral_value():
                return str(int(obj))
            return format(obj, "f")
        raise TypeError(f"unsupported {type(obj).__name__}")

    return encode(value, 0)


def _expect_keys(obj: Any, keys: tuple[str, ...], label: str) -> dict:
    if not isinstance(obj, dict):
        raise TraceInvalid(f"{label} not object")
    extra = set(obj) - set(keys)
    missing = set(keys) - set(obj)
    if extra or missing:
        raise TraceInvalid(f"{label} keys extra={extra} missing={missing}")
    return obj


def _hex32(value: Any, allow_null: bool) -> None:
    if value is None:
        if allow_null:
            return
        raise TraceInvalid("digest null")
    if not isinstance(value, str) or len(value) != 32 or value != value.lower() or any(
        c not in "0123456789abcdef" for c in value
    ):
        raise TraceInvalid(f"digest shape {value!r}")


def _as_int(value: Any, label: str) -> int:
    if isinstance(value, Decimal):
        if value != value.to_integral_value():
            raise TraceInvalid(label)
        value = int(value)
    if type(value) is not int:
        raise TraceInvalid(label)
    return value


def _as_number(value: Any, label: str) -> Decimal:
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise TraceInvalid(label)
        return value
    if type(value) is int:
        return Decimal(value)
    if isinstance(value, str):
        try:
            parsed = Decimal(value)
        except Exception as exc:
            raise TraceInvalid(label) from exc
        if not parsed.is_finite():
            raise TraceInvalid(label)
        return parsed
    raise TraceInvalid(label)


def _as_str(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise TraceInvalid(label)
    return value


def _as_str_or_none(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _as_str(value, label)


def _closed(value: Any, allowed: frozenset[str], label: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise TraceInvalid(label)
    return value


def _closed_or_none(value: Any, allowed: frozenset[str], label: str) -> str | None:
    if value is None:
        return None
    return _closed(value, allowed, label)


def _json_value(value: Any, label: str) -> None:
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise TraceInvalid(label)
        return
    if isinstance(value, JSON_SCALAR):
        return
    if isinstance(value, list):
        for item in value:
            _json_value(item, label)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TraceInvalid(label)
            _json_value(item, label)
        return
    raise TraceInvalid(label)


def validate_trace(trace: Any) -> dict:
    try:
        return _validate_trace(trace)
    except TraceInvalid:
        raise
    except TypeError as exc:
        raise TraceInvalid("type") from exc


def _validate_trace(trace: Any) -> dict:
    obj = _expect_keys(trace, TOP_KEYS, "trace")
    version = _as_int(obj["version"], "version")
    if version != 1:
        raise TraceInvalid(f"version {obj['version']!r}")
    if obj["digest_scheme"] != DIGEST_SCHEME:
        raise TraceInvalid("digest_scheme")
    if obj["pool"] is not None:
        pool = _expect_keys(obj["pool"], POOL_KEYS, "pool")
        _as_number(pool["calls_limit"], "calls_limit")
        _as_number(pool["cost_limit"], "cost_limit")
    if obj["pool_outcome"] is not None:
        outcome = _expect_keys(obj["pool_outcome"], OUTCOME_KEYS, "pool_outcome")
        _as_number(outcome["calls_used"], "calls_used")
        _as_number(outcome["cost_used"], "cost_used")
    invokes = obj["invokes"]
    if not isinstance(invokes, list):
        raise TraceInvalid("invokes")
    coords: set[tuple[str, int]] = set()
    paths: list[str] = []
    for inv in invokes:
        inv = _expect_keys(inv, INVOKE_KEYS, "invoke")
        path = inv["path"]
        if not isinstance(path, str):
            raise TraceInvalid("path")
        paths.append(path)
        depth = _as_int(inv["depth"], "depth")
        if depth < 1:
            raise TraceInvalid("depth")
        _closed(inv["status"], INVOKE_STATUS, "status")
        if type(inv["fatal"]) is not bool:
            raise TraceInvalid("fatal")
        _as_str_or_none(inv["error_code"], "error_code")
        _json_value(inv["return_value"], "return_value")
        if not isinstance(inv["steps"], list):
            raise TraceInvalid("steps")
        prev_iter = None
        for step in inv["steps"]:
            step = _expect_keys(step, STEP_KEYS, "step")
            iteration = _as_int(step["iteration"], "iteration")
            if iteration < 0:
                raise TraceInvalid("iteration")
            key = (path, iteration)
            if key in coords:
                raise TraceInvalid(f"duplicate coordinate {key}")
            coords.add(key)
            if prev_iter is not None and iteration <= prev_iter:
                raise TraceInvalid("step order")
            prev_iter = iteration
            _closed_or_none(step["result_kind"], RESULT_KIND, "result_kind")
            digest = step["logical_digest"]
            _hex32(digest, allow_null=True)
            content = step["response_content"]
            if digest:
                if not isinstance(content, str):
                    raise TraceInvalid("response_content")
            elif content is not None and not isinstance(content, str):
                raise TraceInvalid("response_content")
            cost = step["recorded_cost_usd"]
            if cost is not None:
                _as_number(cost, "recorded_cost_usd")
            if not isinstance(step["repl_output"], str):
                raise TraceInvalid("repl_output")
            _as_str_or_none(step["repl_exception_code"], "repl_exception_code")
            if not isinstance(step["statements"], list):
                raise TraceInvalid("statements")
            prev_stmt = None
            for stmt in step["statements"]:
                stmt = _expect_keys(stmt, STMT_KEYS, "statement")
                idx = _as_int(stmt["stmt_index"], "stmt_index")
                if idx < 0:
                    raise TraceInvalid("stmt_index")
                if prev_stmt is not None and idx <= prev_stmt:
                    raise TraceInvalid("statement order")
                prev_stmt = idx
                _hex32(stmt["sql_digest"], allow_null=False)
                _closed(stmt["kind"], STMT_KIND, "statement kind")
                _closed(stmt["status"], STMT_STATUS, "statement status")
                bind_name = stmt["bind_name"]
                if bind_name is not None:
                    bind_name = _as_str(bind_name, "bind_name")
                    if "/" in bind_name or ":" in bind_name:
                        raise TraceInvalid("bind_name")
        if not isinstance(inv["bindings"], list):
            raise TraceInvalid("bindings")
        prev_name = None
        for bind in inv["bindings"]:
            bind = _expect_keys(bind, BIND_KEYS, "binding")
            name = _as_str(bind["name"], "binding name")
            if prev_name is not None and name.encode("utf-8") <= prev_name.encode("utf-8"):
                raise TraceInvalid("binding order")
            prev_name = name
            _closed(bind["kind"], BIND_KIND, "binding kind")
            _closed(bind["provenance"], BIND_PROVENANCE, "provenance")
            _as_str_or_none(bind["tool_name"], "tool_name")
            _json_value(bind["value"], "binding value")
        if not isinstance(inv["blackboard"], list):
            raise TraceInvalid("blackboard")
        prev_key = None
        for row in inv["blackboard"]:
            row = _expect_keys(row, BOARD_KEYS, "blackboard")
            board_key = _as_str(row["key"], "blackboard key")
            if prev_key is not None and board_key.encode("utf-8") <= prev_key.encode("utf-8"):
                raise TraceInvalid("blackboard order")
            prev_key = board_key
            _json_value(row["value"], "blackboard value")
    if paths != sorted(paths, key=lambda s: s.encode("utf-8")):
        raise TraceInvalid("invoke path order")
    return obj


def load_trace(source) -> dict:
    if isinstance(source, Path):
        text = source.read_text()
    elif hasattr(source, "read"):
        text = source.read()
    elif isinstance(source, str) and not source.lstrip().startswith("{") and not source.lstrip().startswith("["):
        text = Path(source).read_text()
    else:
        text = source
    try:
        raw = _parse(text)
    except json.JSONDecodeError as exc:
        raise TraceInvalid("json") from exc
    return validate_trace(raw)


def write_trace(path: str | Path, trace: dict) -> None:
    validate_trace(trace)
    Path(path).write_text(dumps(trace, indent=2) + "\n")


def export_trace(conn, root: str) -> dict:
    """Export Trace v1 at REPEATABLE READ. Caller must have no uncommitted work on the connection; this function starts with conn.rollback()."""
    conn.rollback()
    cur = conn.cursor()
    cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
    cur.execute("SELECT v15.v15_replay_export(%s)::text", (root,))
    raw = cur.fetchone()[0]
    conn.commit()
    return validate_trace(_parse(raw))


def index_frames(trace: dict) -> dict[tuple[str, int], dict]:
    frames: dict[tuple[str, int], dict] = {}
    for inv in trace["invokes"]:
        for step in inv["steps"]:
            iteration = int(step["iteration"])
            key = (inv["path"], iteration)
            if key in frames:
                raise TraceInvalid(f"duplicate coordinate {key}")
            frames[key] = step
    return frames


def projection(trace: dict, *, drop_cost: bool = False) -> Any:
    """Comparable projection. drop_cost ignores recorded_cost_usd and pool cost_used."""

    def walk(value):
        if isinstance(value, dict):
            out = {}
            for k, v in value.items():
                if drop_cost and k in {"recorded_cost_usd", "cost_used"}:
                    continue
                out[k] = walk(v)
            return out
        if isinstance(value, list):
            return [walk(v) for v in value]
        if isinstance(value, Decimal):
            return value
        return value

    return walk(trace)
