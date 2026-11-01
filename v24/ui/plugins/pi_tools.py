#!/usr/bin/env python3
"""Pi family v2 artifact; M1 exposes only ``read``."""
from __future__ import annotations

import json
import os
import re
import stat
import sys
import uuid
from pathlib import Path

FAMILY_IDENTITY = "v24.ui.pi_tools"
FAMILY_VERSION = "1"
TOOL_SPECS = ({
    "key": "read",
    "description": "Read verbatim text from a workspace file without line numbers; use offset to continue.",
    "parameters": {"type": "object", "additionalProperties": False, "required": ["path"],
                   "properties": {"path": {"type": "string"}, "offset": {"type": "integer", "minimum": 1},
                                  "limit": {"type": "integer", "minimum": 1, "maximum": 2000}}},
    "output_schema": {"type": "object", "additionalProperties": False,
                      "required": ["text", "truncated", "spill_path"],
                      "properties": {"text": {"type": "string"}, "truncated": {"type": "boolean"},
                                     "spill_path": {"type": "string", "maxLength": 128}}},
    "timeout_ms": 5000,
    "limits": {"timeout_ms": 5000, "max_args_bytes": 8192, "max_value_bytes": 40960,
               "max_content_bytes": 41984, "max_meta_bytes": 4096},
    "concurrency": "parallel", "replay_class": "read_only",
    "annotations": {"read_only": True, "destructive": False, "idempotent": True, "open_world": False},
},)

# ==== BEGIN SHARED CORE (v24-ui-family-v1) ====
# This block is copied byte-for-byte into the RP family artifact in M2.
MAX_TEXT_LINES = 2000
MAX_TEXT_BYTES = 32768
MAX_VALUE_BYTES = 40960
MAX_SPILL_BYTES = 8 * 1024 * 1024
SPILL_NAMESPACE = ".v24/spill"
_SAFE_INTEGER_MAX = 2**53 - 1
_SENSITIVE_PARTS = frozenset({".git", ".uidata"})


def _json_quote(value: str) -> str:
    if any(0xD800 <= ord(ch) <= 0xDFFF for ch in value):
        raise ValueError("lone_surrogate")
    return json.dumps(value, ensure_ascii=False)


def _canonical(value) -> str:
    if isinstance(value, dict):
        items = []
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("non_string_key")
            encoded = key.encode("utf-8")
            items.append((encoded, key, item))
        items.sort(key=lambda row: row[0])
        return "{" + ",".join(_json_quote(key) + ":" + _canonical(item) for _, key, item in items) + "}"
    if isinstance(value, list):
        return "[" + ",".join(_canonical(item) for item in value) + "]"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if type(value) is int:
        if abs(value) > _SAFE_INTEGER_MAX:
            raise ValueError("unsafe_integer")
        return str(value)
    if isinstance(value, float):
        raise ValueError("non_integer_number")
    if isinstance(value, str):
        return _json_quote(value)
    raise ValueError("unsupported_json_value")


def canonical_json(value) -> str:
    """Return compact J JSON with UTF-8 key ordering and no floating point."""
    return _canonical(value)


def frame(value) -> str:
    return canonical_json(value)


def _workspace_root() -> Path:
    raw = os.environ.get("V24_WORKSPACE_ROOT")
    if not raw or not os.path.isdir(raw) or os.path.realpath(raw) != raw:
        raise ValueError("root_unavailable")
    return Path(raw)


def _spill_root() -> Path:
    raw = os.environ.get("V24_SPILL_ROOT")
    if not raw or not os.path.isdir(raw) or os.path.realpath(raw) != raw:
        raise ValueError("spill_unavailable")
    return Path(raw)


def _excluded(relative: Path) -> bool:
    for part in relative.parts:
        lower = part.lower()
        if lower in _SENSITIVE_PARTS or lower.startswith(".env") or lower.endswith(".pem") \
                or lower.startswith("id_rsa") or lower.startswith("id_ed25519"):
            return True
    return False


def _regular(path: Path) -> bool:
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except OSError:
        return False


def _checked_path(base: Path, candidate: Path) -> Path:
    try:
        relative = candidate.relative_to(base)
    except ValueError:
        raise ValueError("path_escape") from None
    if _excluded(relative):
        raise ValueError("path_excluded")
    part = base
    for name in relative.parts:
        part = part / name
        if part.is_symlink():
            raise ValueError("path_escape")
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError:
        raise ValueError("not_found") from None
    except PermissionError:
        raise ValueError("permission_denied") from None
    except (OSError, RuntimeError):
        raise ValueError("path_escape") from None
    try:
        resolved.relative_to(base)
    except ValueError:
        raise ValueError("path_escape") from None
    if not _regular(resolved):
        raise ValueError("not_a_file")
    return resolved


def resolve_path(raw: str, *, write: bool = False) -> Path:
    """Resolve workspace paths and the virtual read-only spill mount."""
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise ValueError("invalid_arguments")
    lexical = Path(raw)
    if ".." in lexical.parts:
        raise ValueError("path_escape")
    if raw.startswith(SPILL_NAMESPACE + "/") or raw == SPILL_NAMESPACE:
        if write:
            raise ValueError("path_excluded")
        rel = raw[len(SPILL_NAMESPACE):].lstrip("/")
        if not rel or Path(rel).is_absolute() or ".." in Path(rel).parts:
            raise ValueError("path_escape")
        root = _spill_root()
        return _checked_path(root, root / rel)
    base = _workspace_root()
    candidate = Path(raw) if raw.startswith("/") else base / raw
    return _checked_path(base, candidate)


def read_utf8(path: Path) -> str:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode): raise ValueError("not_a_file")
            data = stream.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024: raise ValueError("file_too_large")
    except OSError:
        raise ValueError("io_error") from None
    if b"\x00" in data:
        raise ValueError("binary_file")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("not_utf8") from None


def _prune_spill(root: Path) -> None:
    files = []
    try:
        for item in root.iterdir():
            if _regular(item) and item.suffix == ".txt":
                try:
                    files.append((item.stat().st_mtime_ns, item, item.stat().st_size))
                except OSError:
                    pass
    except OSError:
        return
    files.sort()
    total = sum(size for _, _, size in files)
    while len(files) > 50 or total > MAX_SPILL_BYTES:
        _, item, size = files.pop(0)
        try:
            item.unlink()
            total -= size
        except OSError:
            pass


def spill_write(text: str) -> str:
    if not isinstance(text, str) or "\x00" in text:
        raise ValueError("binary_file")
    try:
        payload = text.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("not_utf8") from None
    root = _spill_root()
    root.mkdir(parents=True, exist_ok=True)
    name = uuid.uuid4().hex + ".txt"
    target = root / name
    temporary = root / ("." + name + ".tmp")
    try:
        with open(temporary, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        directory_fd = os.open(root, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise ValueError("spill_write_failed") from None
    _prune_spill(root)
    return f"{SPILL_NAMESPACE}/{name}"


def spill_read(path: str) -> str:
    return read_utf8(resolve_path(path))


def finish_text(text: str, *, spill: bool = True, offset: int = 1, limit: int = MAX_TEXT_LINES) -> dict:
    """Keep whole lines and reserve a rendered continuation/spill notice."""
    if not isinstance(text, str) or "\x00" in text:
        raise ValueError("binary_file")
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("not_utf8") from None
    lines = text.splitlines(keepends=True)
    start = offset - 1
    selected = lines[start:start + limit]
    # Reserve a full-length virtual path before writing any spill data.
    placeholder = f"{SPILL_NAMESPACE}/{'0' * 32}.txt"
    for count in range(len(selected), -1, -1):
        shown = "".join(selected[:count])
        truncated = start + count < len(lines)
        spill_path = placeholder if truncated else ""
        footer = (f"[Showing lines {offset}-{start + count} of {len(lines)}. "
                  f"Use offset={start + count + 1} to continue. Full text: {spill_path}]") if truncated else ""
        rendered = shown + ("" if not shown or shown.endswith(('\n', '\r')) else "\n") + footer if footer else shown
        value = {"text": rendered, "truncated": truncated, "spill_path": spill_path}
        if len(rendered.splitlines()) <= MAX_TEXT_LINES and len(rendered.encode('utf-8')) <= MAX_TEXT_BYTES and len(frame(value).encode('utf-8')) <= MAX_VALUE_BYTES - 128:
            if selected and count == 0:
                raise ValueError("line_too_long")
            if truncated:
                if not spill: raise ValueError("spill_write_failed")
                actual = spill_write(text)
                value["text"] = rendered.replace(placeholder, actual)
                value["spill_path"] = actual
            return value
    raise ValueError("line_too_long")

# ==== END SHARED CORE ====


def fail(code, message=None):
    return {"ok": False, "v": 2, "error": {"code": code, "message": message or code}}


def read_tool(args):
    if type(args) is not dict or set(args) - {"path", "offset", "limit"} or "path" not in args:
        raise ValueError("invalid_arguments")
    offset = args.get("offset", 1)
    limit = args.get("limit", MAX_TEXT_LINES)
    if type(offset) is not int or offset < 1 or type(limit) is not int or not 1 <= limit <= MAX_TEXT_LINES:
        raise ValueError("invalid_arguments")
    text = read_utf8(resolve_path(args["path"]))
    return finish_text(text, offset=offset, limit=limit)


def invoke(tool, args):
    if tool != "read":
        raise ValueError("not_found")
    return read_tool(args)


def main():
    for line in sys.stdin.buffer:
        try:
            request = json.loads(line)
            operation = request.get("operation")
            if operation == "prepare":
                result = {"prepared": True}
            elif operation == "release":
                result = {"released": True}
            elif operation == "inspect":
                result = {"observed": "known"}
            elif operation == "invoke":
                result = invoke(request.get("tool"), request.get("args"))
            else:
                raise ValueError("invalid_arguments")
            sys.stdout.buffer.write((frame({"ok": True, "v": 2, "result": result if operation != "invoke" else {"value": result, "meta": {}}}) + '\n').encode('utf-8'))
            sys.stdout.buffer.flush()
        except Exception as exc:
            code = str(exc) if str(exc) in {"root_unavailable", "spill_unavailable", "invalid_arguments", "path_escape", "path_excluded", "not_found", "permission_denied", "line_too_long", "not_a_file", "binary_file", "not_utf8", "file_too_large", "spill_write_failed", "io_error"} else "io_error"
            sys.stdout.buffer.write((frame(fail(code)) + '\n').encode('utf-8'))
            sys.stdout.buffer.flush()
            raise SystemExit(3)

if __name__ == "__main__":
    main()
