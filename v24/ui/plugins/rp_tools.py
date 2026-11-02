#!/usr/bin/env python3
"""RepoPrompt-style family v2 artifact; M2 exposes only file_search."""
from __future__ import annotations

import fnmatch
import json
import os
import re
import stat
import sys
import uuid
from pathlib import Path

FAMILY_IDENTITY = "v24.ui.rp_tools"
FAMILY_VERSION = "1"
TOOL_SPECS = ({
    "key": "file_search",
    "description": "Search workspace paths/content, grouped by file. Use mode and filter (unlike Pi grep's glob/literal); regex defaults to true. Auto infers path for glob-like patterns, otherwise content. Binary files are skipped and counted.",
    "parameters": {"type": "object", "additionalProperties": False, "required": ["pattern"],
        "properties": {"pattern": {"type": "string", "minLength": 1},
            "mode": {"type": "string", "enum": ["auto", "path", "content", "both"]},
            "regex": {"type": "boolean"}, "whole_word": {"type": "boolean"},
            "context_lines": {"type": "integer", "minimum": 0, "maximum": 100},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 1000},
            "count_only": {"type": "boolean"},
            "filter": {"type": "object", "additionalProperties": False, "required": [],
                "properties": {"extensions": {"type": "array", "items": {"type": "string"}},
                    "paths": {"type": "array", "items": {"type": "string"}},
                    "exclude": {"type": "array", "items": {"type": "string"}}}}}},
    "output_schema": {"type": "object", "additionalProperties": False,
        "required": ["text", "truncated", "spill_path"],
        "properties": {"text": {"type": "string"}, "truncated": {"type": "boolean"},
                       "spill_path": {"type": "string", "maxLength": 128}}},
    "timeout_ms": 15000,
    "limits": {"timeout_ms": 15000, "max_args_bytes": 16384, "max_value_bytes": 40960,
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


def _search_root(raw):
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise ValueError("invalid_arguments")
    lexical = Path(raw)
    if ".." in lexical.parts:
        raise ValueError("path_escape")
    root = _workspace_root()
    candidate = lexical if lexical.is_absolute() else root / lexical
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        raise ValueError("path_escape") from None
    # Check lexical exclusions before testing existence (no existence oracle).
    if _excluded(relative) or relative.parts[:1] == (".v24",):
        raise ValueError("path_excluded")
    part = root
    for name in relative.parts:
        part = part / name
        if part.is_symlink():
            raise ValueError("path_escape")
    if not candidate.exists():
        raise ValueError("not_found")
    return candidate


def _walk(path):
    """Deterministic, non-following walk; dot and sensitive paths stay hidden."""
    if path.is_file():
        yield path
        return
    if not path.is_dir():
        raise ValueError("not_a_file")
    for child in sorted(path.iterdir(), key=lambda item: item.name):
        if child.name.startswith(".") or child.is_symlink() or _excluded(Path(child.name)):
            continue
        if child.is_dir():
            yield from _walk(child)
        elif _regular(child):
            yield child


def file_search(args):
    allowed = {"pattern", "mode", "regex", "whole_word", "context_lines", "max_results", "count_only", "filter"}
    if type(args) is not dict or set(args) - allowed or not isinstance(args.get("pattern"), str) or not args["pattern"] or "\x00" in args["pattern"]:
        raise ValueError("invalid_arguments")
    mode = args.get("mode", "auto")
    regex = args.get("regex", True)
    whole = args.get("whole_word", False)
    count_only = args.get("count_only", False)
    context = args.get("context_lines", 0)
    maximum = args.get("max_results", 50)
    filters = args.get("filter", {})
    if mode not in ("auto", "path", "content", "both") or any(type(x) is not bool for x in (regex, whole, count_only)) or type(context) is not int or not 0 <= context <= 100 or type(maximum) is not int or not 1 <= maximum <= 1000:
        raise ValueError("invalid_arguments")
    if type(filters) is not dict or set(filters) - {"extensions", "paths", "exclude"} or any(type(v) is not list or any(not isinstance(x, str) or "\x00" in x for x in v) for v in filters.values()):
        raise ValueError("invalid_arguments")
    pattern = args["pattern"]
    auto_glob = mode == "auto" and any(char in pattern for char in "*?[")
    if mode == "auto":
        mode = "path" if auto_glob or "/" in pattern else "content"
    path_glob = mode == "path" and (auto_glob or not regex)
    try:
        expression = pattern if regex else re.escape(pattern)
        matcher = None if path_glob else re.compile(r"\b(?:" + expression + r")\b" if whole else expression)
    except re.error:
        raise ValueError("invalid_arguments") from None
    roots = [_search_root(raw) for raw in filters.get("paths", ["."])]
    paths = sorted({path for root in roots for path in _walk(root)})
    groups = []
    matches = 0
    binary = 0
    extensions = filters.get("extensions", [])
    output_bytes = 0
    for path in paths:
        relative = path.relative_to(_workspace_root()).as_posix()
        if extensions and path.suffix not in extensions:
            continue
        if any(fnmatch.fnmatchcase(relative, pat) or fnmatch.fnmatchcase(path.name, pat) for pat in filters.get("exclude", [])):
            continue
        hits = []
        lines = []
        # In both mode a skipped content file contributes no pathname hit.
        # Check eligibility before admitting/counting any match.
        if mode in ("content", "both"):
            try:
                lines = read_utf8(resolve_path(relative)).splitlines()
            except ValueError as exc:
                if str(exc) == "binary_file":
                    binary += 1
                    continue
                if str(exc) in ("not_utf8", "file_too_large", "io_error"):
                    continue
                raise
        if mode in ("path", "both"):
            matched = fnmatch.fnmatchcase(relative, pattern) if path_glob or not regex else bool(matcher.search(relative))
            if matched and matches < maximum:
                hits.append("  [path]")
                matches += 1
        if mode in ("content", "both"):
            indexes = [i for i, line in enumerate(lines) if matcher.search(line)]
            visible = set()
            for index in indexes:
                if matches >= maximum:
                    break
                matches += 1
                visible.update(range(max(0, index - context), min(len(lines), index + context + 1)))
            hits.extend(f"  {i + 1}: {lines[i]}" for i in sorted(visible))
        if hits:
            group = relative + "\n" + "\n".join(hits)
            output_bytes += len(group.encode("utf-8")) + 2
            # Pi read loads the whole spill before paging and caps it at 1 MiB.
            # Reject before spill_write, reserving room for summary/framing.
            if not count_only and output_bytes > 1024 * 1024 - 4096:
                raise ValueError("output_too_large")
            groups.append(group)
        if matches >= maximum:
            break
    summary = f"matches={matches}; files={len(groups)}; skipped_binary={binary}; limit={maximum}; limit_reached={str(matches >= maximum).lower()}"
    text = summary if count_only else summary + ("\n\n" + "\n\n".join(groups) if groups else "")
    return finish_text(text)


def main():
    if sys.argv[1:] != ["serve"]:
        raise SystemExit(3)
    try:
        request = json.loads(sys.stdin.buffer.readline())
        operation = request.get("operation")
        if request.get("v") != 2:
            raise ValueError("invalid_arguments")
        if operation == "invoke":
            if request.get("tool") != "file_search":
                raise ValueError("not_found")
            result = {"value": file_search(request.get("args")), "meta": {}}
        elif operation == "prepare":
            result = {"prepared": True}
        elif operation == "release":
            result = {"released": True}
        elif operation == "inspect":
            result = {"observed": "known"}
        else:
            raise ValueError("invalid_arguments")
        response = {"ok": True, "v": 2, "result": result}
        code = 0
    except (ValueError, OSError) as exc:
        known = {"root_unavailable", "spill_unavailable", "invalid_arguments", "path_escape", "path_excluded", "not_found", "permission_denied", "line_too_long", "not_a_file", "binary_file", "not_utf8", "file_too_large", "spill_write_failed", "io_error", "output_too_large"}
        reason = str(exc) if str(exc) in known else "io_error"
        response = {"ok": False, "v": 2, "error": {"code": reason, "message": reason}}
        code = 3
    sys.stdout.buffer.write((frame(response) + "\n").encode("utf-8"))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
