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
import errno
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
CHUNK = 65536


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


def _signature(info):
    return (info.st_dev, info.st_ino, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _same_file(left, right):
    return _signature(left) == _signature(right)


def _open_regular(target, info):
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(target, flags)
    except FileNotFoundError:
        raise ToolError("not_found", "path does not exist") from None
    except PermissionError:
        raise ToolError("permission_denied", "file is not readable") from None
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise ToolError("symlink_denied", "path contains a symlink") from None
        raise ToolError("io_error", "file could not be opened") from None
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or not _same_file(info, opened):
            raise ToolError("io_error", "file changed while opening")
        return fd, opened
    except Exception:
        os.close(fd)
        raise


def _scan(fd, st, offset, limit):
    """Count LF in chunks and retain only the requested window boundaries."""
    lf_count = 0
    bytes_seen = 0
    last = b""
    target_lo = max(0, offset - 2)
    target_hi = offset + limit - 2
    positions = {}
    while True:
        try:
            chunk = os.read(fd, CHUNK)
        except OSError:
            raise ToolError("io_error", "file could not be read") from None
        if not chunk:
            break
        chunk_start = bytes_seen
        bytes_seen += len(chunk)
        if bytes_seen > MAX_FILE_BYTES:
            raise ToolError("file_too_large", "file is larger than 1 MiB")
        chunk_lfs = chunk.count(b"\n")
        if lf_count <= target_hi and lf_count + chunk_lfs > target_lo:
            # Locate the first requested LF without retaining or iterating
            # over all preceding lines in this chunk.
            first = max(target_lo - lf_count, 0)
            index = 0
            if first:
                low, high = 0, len(chunk)
                while low < high:
                    middle = (low + high) // 2
                    if chunk.count(b"\n", 0, middle) >= first:
                        high = middle
                    else:
                        low = middle + 1
                index = low
            for number in range(lf_count + first,
                                min(lf_count + chunk_lfs, target_hi + 1)):
                found = chunk.find(b"\n", index)
                positions[number] = chunk_start + found
                index = found + 1
        lf_count += chunk_lfs
        last = chunk[-1:]
    if bytes_seen != st.st_size:
        raise ToolError("io_error", "file changed while scanning")
    if bytes_seen == 0:
        total = 0
    else:
        total = lf_count if last == b"\n" else lf_count + 1
    final_newline = bool(bytes_seen) and last == b"\n"
    bounds = []
    if total:
        max_k = min(limit, total - offset + 1)
        for index in range(offset - 1, offset - 1 + max_k):
            start = 0 if index == 0 else positions[index - 1] + 1
            end = positions[index] if index < lf_count else bytes_seen
            bounds.append((start, end))
    return total, final_newline, bounds


def _read_window(fd, st, bounds):
    if not bounds:
        return []
    start = bounds[0][0]
    end = bounds[-1][1]
    try:
        raw = os.pread(fd, end - start, start)
    except OSError:
        raise ToolError("io_error", "file could not be read") from None
    if len(raw) != end - start:
        raise ToolError("io_error", "file changed while reading")
    return [raw[left - start:right - start] for left, right in bounds]


def escaped_bytes_len(raw: bytes) -> int:
    """Length of a UTF-8 byte payload after JSON string escaping, sans quotes."""
    extra = 0
    for byte in raw:
        if byte in (0x22, 0x5C, 0x08, 0x0C, 0x0D, 0x09, 0x0A):
            extra += 1
        elif byte < 0x20:
            extra += 5
    return len(raw) + extra


def _escaped_len(text):
    return escaped_bytes_len(text.encode("utf-8"))


def _json_len(value):
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")).encode("utf-8"))


CONTENT_BASE_BYTES = _json_len([{"text": "", "type": "text"}])
EMPTY_CONTENT_BYTES = CONTENT_BASE_BYTES + escaped_bytes_len(b"[empty file]")
META_BYTES = _json_len({})


def select_prefix(lengths, cap):
    """Return the largest prefix index whose length fits; enumerate all."""
    best = 0
    for index, length in enumerate(lengths, start=1):
        if length <= cap:
            best = index
    return best


def _caps():
    return {"value": MAX_VALUE_BYTES, "content": MAX_CONTENT_BYTES,
            "meta": MAX_META_BYTES, "frame": FRAME_TARGET}


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


def empty_measures(relative):
    value = _empty_value(relative)
    return {"value": _json_len(value), "content": EMPTY_CONTENT_BYTES,
            "meta": META_BYTES,
            "frame": _json_len({"ok": True, "v": 2,
                                "result": {"value": value}}) + 1,
            "value_skeleton": value}


def page_measures(relative, offset, limit, total, final_newline, line_e):
    measures = []
    text_bytes = 0
    for count, one_line in enumerate(line_e, start=1):
        text_bytes += one_line
        escaped_text = text_bytes + 2 * (count - 1)
        truncated = offset + count - 1 < total
        truncated_by = (("lines" if count == limit else "bytes")
                        if truncated else None)
        next_offset = offset + count if truncated else None
        value = {
            "path": relative,
            "text": "",
            "start_line": offset,
            "end_line": offset + count - 1,
            "total_lines": total,
            "final_newline": final_newline,
            "truncated": truncated,
            "truncated_by": truncated_by,
            "next_offset": next_offset,
        }
        footer = (f"\n\n[Showing lines {offset}-{offset + count - 1} of "
                  f"{total}. Use offset={next_offset} to continue.]")
        content = CONTENT_BASE_BYTES + escaped_text
        if truncated:
            content += escaped_bytes_len(footer.encode("utf-8"))
        measures.append({"value": _json_len(value) + escaped_text,
                         "content": content, "meta": META_BYTES,
                         "frame": _json_len({"ok": True, "v": 2,
                             "result": {"value": value}}) + 1 + escaped_text,
                         "value_skeleton": value,
                         "text_bytes": escaped_text})
    return measures


def choose_k(measures, caps):
    overflows = [max(measure[name] - caps[name]
                     for name in ("value", "content", "meta", "frame"))
                 for measure in measures]
    return select_prefix(overflows, 0)


def _read_page(relative, fd, st, offset, limit, total, final_newline, bounds):
    raw_lines = _read_window(fd, st, bounds)
    if not _same_file(st, os.fstat(fd)):
        raise ToolError("io_error", "file changed while reading")
    decoded = []
    line_e = []
    for raw in raw_lines:
        if len(raw) > MAX_LINE_BYTES:
            raise ToolError("line_too_long", "a selected line is too long")
        try:
            decoded.append(raw.decode("utf-8", "strict"))
        except UnicodeDecodeError:
            raise ToolError("not_utf8", "selected text is not valid UTF-8") from None
        line_e.append(escaped_bytes_len(raw))
    measures = page_measures(relative, offset, limit, total, final_newline, line_e)
    chosen = choose_k(measures, _caps())
    if chosen == 0:
        raise ToolError("line_too_long", "no page fits the approved budgets")
    value = dict(measures[chosen - 1]["value_skeleton"])
    value["text"] = "\n".join(decoded[:chosen])
    return value


def read_tool(args, root):
    path = _path_arg(args.get("path"))
    offset = args.get("offset", 1)
    limit = args.get("limit", MAX_READ_LINES)
    if (type(offset) is not int or type(limit) is not int
            or offset < 1 or not 1 <= limit <= MAX_READ_LINES):
        raise ToolError("invalid_path", "offset or limit is invalid")
    target, relative = _resolve(path, root)
    try:
        try:
            info = os.lstat(target)
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
        fd, opened = _open_regular(target, info)
        try:
            try:
                prefix = os.pread(fd, 8192, 0)
            except OSError:
                raise ToolError("io_error", "file could not be read") from None
            if b"\x00" in prefix:
                raise ToolError("binary_file", "file contains a NUL byte")
            total, final_newline, bounds = _scan(fd, opened, offset, limit)
            if not _same_file(opened, os.fstat(fd)):
                raise ToolError("io_error", "file changed while scanning")
            if total == 0:
                if offset != 1:
                    raise ToolError("offset_out_of_range", "offset is outside the file")
                measures = empty_measures(relative)
                caps = _caps()
                if any(measures[name] > caps[name]
                       for name in ("value", "content", "meta", "frame")):
                    raise ToolError("output_too_large", "empty page exceeds output budgets")
                return measures["value_skeleton"]
            if offset > total:
                raise ToolError("offset_out_of_range", "offset is outside the file")
            return _read_page(relative, fd, opened, offset, limit,
                              total, final_newline, bounds)
        finally:
            os.close(fd)
    except ToolError:
        raise
    except PermissionError:
        raise ToolError("permission_denied", "file is not readable") from None
    except OSError:
        raise ToolError("io_error", "file could not be read") from None


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
