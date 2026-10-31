#!/usr/bin/env python3
"""v24 line-JSON v2 filesystem read plugin.

One request frame on stdin, one response frame on stdout.  The plugin is a
single standard-library file so the approved artifact digest is meaningful.
It implements the four v2 operations (prepare/release/inspect/invoke) and the
``read`` tool contract from design §6.1/§6.2.

Only an explicitly supplied ``--spawn-log <absolute path>`` is written; the
production path has no side effect.
"""
from __future__ import annotations

import json
import os
import stat
import sys

MAX_FILE_BYTES = 1024 * 1024
MAX_LINE_BYTES = 16384
MAX_READ_LINES = 2000
MAX_ARGS_BYTES = 16384
MAX_VALUE_BYTES = 40960
MAX_CONTENT_BYTES = 41984
MAX_META_BYTES = 4096
FRAME_TARGET = 60000


class ToolError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(code)


def _spawn_log(argv):
    if "--spawn-log" not in argv:
        return None
    index = argv.index("--spawn-log")
    if index + 1 >= len(argv):
        return None
    return argv[index + 1]


def _append_spawn(path, operation):
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"{os.getpid()} {operation}\n")
        handle.flush()


def _emit(payload, code=0):
    sys.stdout.buffer.write(
        json.dumps(payload, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()
    return code


def _ok(result):
    return _emit({"ok": True, "v": 2, "result": result})


def _error(code, message):
    return _emit({"ok": False, "v": 2,
                  "error": {"code": code, "message": message}}, 3)


def _root():
    root = os.environ.get("V24_WORKSPACE_ROOT")
    if not isinstance(root, str) or not root or not os.path.isdir(root):
        raise ToolError("root_unavailable",
                        "the approved workspace root is not available")
    return root


def _path_arg(value):
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ToolError("invalid_path", "path is not a valid string")
    try:
        raw = value.encode("utf-8")
    except UnicodeEncodeError:
        raise ToolError("invalid_path", "path is not valid UTF-8") from None
    if len(raw) > 1024:
        raise ToolError("invalid_path", "path is longer than 1024 bytes")
    return value


def _components(value):
    parts = value.split("/")
    components = [part for part in parts if part not in ("", ".")]
    if any(part == ".." for part in components):
        raise ToolError("path_escape", "path must not contain ..")
    return components


def _resolve(value, root):
    """Resolve one path without following symlinks; return absolute + relative."""
    value = _path_arg(value)
    components = _components(value)
    if os.path.isabs(value):
        normalized = os.path.normpath(value)
        root_normalized = os.path.normpath(root)
        if normalized != root_normalized and not normalized.startswith(
                root_normalized + os.sep):
            raise ToolError("path_escape", "absolute path is outside the workspace")
        relative = os.path.relpath(normalized, root_normalized)
        components = [] if relative == "." else relative.split(os.sep)
    if any(part == ".git" for part in components):
        raise ToolError("path_excluded", "path is excluded")
    current = root
    for part in components:
        current = os.path.join(current, part)
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            raise ToolError("not_found", "path does not exist") from None
        except PermissionError:
            raise ToolError("permission_denied", "path is not readable") from None
        except OSError:
            raise ToolError("io_error", "path could not be inspected") from None
        if stat.S_ISLNK(info.st_mode):
            raise ToolError("symlink_denied", "path contains a symlink")
    return current, ("/".join(components) or ".")


def _read_bytes(path):
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        raise ToolError("not_found", "path does not exist") from None
    except PermissionError:
        raise ToolError("permission_denied", "path is not readable") from None
    except OSError:
        raise ToolError("io_error", "path could not be inspected") from None
    if stat.S_ISLNK(info.st_mode):
        raise ToolError("symlink_denied", "path contains a symlink")
    if not stat.S_ISREG(info.st_mode):
        raise ToolError("not_a_file", "path is not a regular file")
    if info.st_size > MAX_FILE_BYTES:
        raise ToolError("file_too_large", "file is larger than 1 MiB")
    try:
        with open(path, "rb") as handle:
            data = handle.read(MAX_FILE_BYTES + 1)
    except PermissionError:
        raise ToolError("permission_denied", "file is not readable") from None
    except OSError:
        raise ToolError("io_error", "file could not be read") from None
    if len(data) > MAX_FILE_BYTES:
        raise ToolError("file_too_large", "file is larger than 1 MiB")
    if b"\x00" in data[:8192]:
        raise ToolError("binary_file", "file contains a NUL byte")
    return data


def _line_ranges(data):
    ranges = []
    start = 0
    for index, byte in enumerate(data):
        if byte == 0x0A:
            ranges.append((start, index))
            start = index + 1
    if start < len(data):
        ranges.append((start, len(data)))
    final_newline = bool(data) and data.endswith(b"\n")
    return ranges, final_newline


def _escaped_len(text):
    return len(json.dumps(text, ensure_ascii=False).encode("utf-8")) - 2


def _json_len(value):
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")).encode("utf-8"))


def _frame_len(value):
    return _json_len({"ok": True, "v": 2, "result": {"value": value}}) + 1


def select_prefix(lengths, cap):
    """Return the largest prefix index whose length fits; enumerate all."""
    best = 0
    for index, length in enumerate(lengths, start=1):
        if length <= cap:
            best = index
    return best


def _empty_value(relative):
    return {
        "path": relative,
        "text": "",
        "start_line": 0,
        "end_line": 0,
        "total_lines": 0,
        "final_newline": False,
        "truncated": False,
        "truncated_by": None,
        "next_offset": None,
    }


def _read_page(relative, data, offset, limit):
    ranges, final_newline = _line_ranges(data)
    total = len(ranges)
    if total == 0:
        if offset != 1:
            raise ToolError("offset_out_of_range", "offset is outside the file")
        return _empty_value(relative)
    if offset > total:
        raise ToolError("offset_out_of_range", "offset is outside the file")
    max_k = min(limit, total - offset + 1)
    # §5.6: decode the requested window (up to limit lines), not only a
    # candidate prefix.  A bad line outside offset..offset+limit-1 does not
    # fail this page; a bad line inside it is not_utf8 even when a shorter
    # prefix could be encoded.
    decoded = []
    for index in range(offset - 1, offset - 1 + max_k):
        start, end = ranges[index]
        if end - start > MAX_LINE_BYTES:
            raise ToolError("line_too_long", "a selected line is too long")
        try:
            decoded.append(data[start:end].decode("utf-8", "strict"))
        except UnicodeDecodeError:
            raise ToolError("not_utf8", "selected text is not valid UTF-8") from None
    best = None
    for count in range(1, max_k + 1):
        text = "\n".join(decoded[:count])
        truncated = offset + count - 1 < total
        value = {
            "path": relative,
            "text": text,
            "start_line": offset,
            "end_line": offset + count - 1,
            "total_lines": total,
            "final_newline": final_newline,
            "truncated": truncated,
            "truncated_by": (("lines" if count == limit else "bytes")
                             if truncated else None),
            "next_offset": offset + count if truncated else None,
        }
        content_len = 27 + _escaped_len(text)
        if (_json_len(value) > MAX_VALUE_BYTES
                or content_len > MAX_CONTENT_BYTES
                or _frame_len(value) > FRAME_TARGET):
            continue
        best = value
    if best is not None:
        return best
    raise ToolError("line_too_long", "no page fits the approved budgets")


def read_tool(args, root):
    path = _path_arg(args.get("path"))
    offset = args.get("offset", 1)
    limit = args.get("limit", MAX_READ_LINES)
    if (type(offset) is not int or type(limit) is not int
            or offset < 1 or not 1 <= limit <= MAX_READ_LINES):
        raise ToolError("invalid_path", "offset or limit is invalid")
    target, relative = _resolve(path, root)
    data = _read_bytes(target)
    return _read_page(relative, data, offset, limit)


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    if len(argv) < 2 or argv[1] != "serve":
        return 2
    spawn_log = _spawn_log(argv)
    line = sys.stdin.buffer.readline()
    frame = None
    try:
        frame = json.loads(line.decode("utf-8", "strict"))
        operation = frame.get("operation")
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        operation = None
    _append_spawn(spawn_log, operation or "unknown")
    try:
        if (not isinstance(frame, dict) or frame.get("v") != 2
                or operation not in ("prepare", "invoke", "release", "inspect")
                or not isinstance(frame.get("reservation"), str)
                or not frame["reservation"]
                or not isinstance(frame.get("args"), dict)):
            raise ToolError("bad_request", "request frame is invalid")
        reservation = frame["reservation"]
        args = frame["args"]
        root = _root()
        if operation == "prepare":
            if not reservation.startswith("v24:host_prepare:"):
                raise ToolError("reservation_invalid", "prepare reservation mismatch")
            return _ok({"prepared": True})
        if operation == "release":
            if not reservation.startswith("v24:host_release:"):
                raise ToolError("reservation_invalid", "release reservation mismatch")
            return _ok({"released": True})
        if operation == "inspect":
            target = args.get("target")
            target_reservation = args.get("target_reservation")
            if target not in ("host_prepare", "host_release") or not isinstance(
                    target_reservation, str):
                raise ToolError("inspect_request_invalid",
                                "inspect request is invalid")
            return _ok({"observed": "known" if target_reservation.startswith(
                "v24:host_prepare:" if target == "host_prepare"
                else "v24:host_release:") else "absent"})
        tool = frame.get("tool")
        if tool != "read":
            raise ToolError("tool_not_approved", "tool is not approved")
        value = read_tool(args, root)
        return _ok({"value": value})
    except ToolError as exc:
        return _error(exc.code, exc.message)
    except Exception:
        return _error("io_error", "tool execution failed")


if __name__ == "__main__":
    raise SystemExit(main())
