"""One-shot line-JSON process protocol for the v24 plugin plane.

This is intentionally *not* ``v13.read_tools.bridge.run_line_json``: the v13
bridge stops reading after the first line and captures stdout once, so it cannot
enforce the output bounds and the extra-frame rule this milestone needs.  The
frame contract is the v13 one, reimplemented here:

request (exactly one line written to stdin)::

    {"v":1,"operation":"prepare|invoke|release|inspect",
     "reservation":"<idempotency key>","args":{...}}

success (exit 0)::

    {"ok":true,"result":"<a string containing one JSON object>"}

known tool error (exit 3)::

    {"ok":false,"error":"<code>","message":"<text>"}

Everything else is an ``unknown`` receipt: EOF, malformed JSON, extra frames,
stdout > 64 KiB, stderr > 16 KiB, an unexpected exit code, a timeout, or an
abnormal signalled exit.  A timeout or output-limit breach kills the whole
process group and reaps it before returning.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace

from . import canonical, tool_results
from .process_io import (
    DEFAULT_TIMEOUT_MS,
    STDERR_LIMIT,
    STDOUT_LIMIT,
    ProcessError,
    ProcessSpec,
    run_process,
)

OPERATIONS = ("prepare", "invoke", "release", "inspect")
V2_OPERATIONS = ("prepare", "invoke", "release", "inspect")
RESERVED_TOOL_KEY = "agent.spawn"
TOOL_KEY_RE = re.compile(r"[a-z][a-z0-9_.-]{0,127}")


class LineJsonPreflight(RuntimeError):
    """The frame/argv/env was rejected before a process was created."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class Invocation:
    """Result of one line-JSON attempt.

    ``class_name`` is the v24 outcome class (``success``/``failure``/
    ``unknown``).  ``result`` is the JSON object carried by a success frame or
    the ``{code,message}`` pair of a known exit-3 error.  ``started`` is False
    only for a pre-spawn rejection.
    """

    class_name: str
    result: dict | None
    started: bool
    reason: str | None
    returncode: int | None
    wall_ms: int
    pid: int | None = None
    stdout: bytes = b""
    stderr: bytes = b""


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def build_frame(operation: str, reservation: str, args: dict) -> bytes:
    if operation not in OPERATIONS:
        raise LineJsonPreflight("operation_invalid")
    if not isinstance(reservation, str) or not reservation or "\x00" in reservation:
        raise LineJsonPreflight("reservation_invalid")
    if not isinstance(args, dict):
        raise LineJsonPreflight("args_invalid")
    return (_canonical({"v": 1, "operation": operation,
                        "reservation": reservation, "args": args}) + "\n").encode(
                            "utf-8")


def _spec(adapter, frame: bytes) -> ProcessSpec:
    return ProcessSpec(
        argv=tuple(adapter.argv),
        cwd=adapter.cwd,
        env=adapter.environment(),
        stdin=frame,
        timeout_ms=adapter.timeout_ms or DEFAULT_TIMEOUT_MS,
        stdout_limit=adapter.stdout_limit or STDOUT_LIMIT,
        stderr_limit=adapter.stderr_limit or STDERR_LIMIT,
    )


def _unknown(reason: str, *, returncode=None, wall_ms=0, pid=None,
             stdout=b"", stderr=b"") -> Invocation:
    return Invocation("unknown", None, True, reason, returncode, wall_ms, pid,
                      stdout, stderr)


def _frames(stdout: bytes):
    """Decode stdout as exactly one JSON frame or raise ``ValueError``."""
    try:
        text = stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("stdout_not_utf8") from exc
    lines = text.splitlines()
    if not lines or not lines[0].strip():
        raise ValueError("eof")
    if len(lines) > 1:
        # Any second line (including a second frame) is a protocol breach.
        raise ValueError("extra_frame")
    try:
        frame = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise ValueError("bad_frame") from exc
    if not isinstance(frame, dict):
        raise ValueError("bad_frame")
    return frame


def _success_frame(frame) -> dict | None:
    if set(frame) != {"ok", "result"} or frame.get("ok") is not True:
        return None
    result = frame.get("result")
    if not isinstance(result, str):
        return None
    try:
        decoded = json.loads(result)
    except json.JSONDecodeError:
        return None
    if not isinstance(decoded, dict):
        return None
    return decoded


def _error_frame(frame) -> dict | None:
    if set(frame) != {"ok", "error", "message"} or frame.get("ok") is not False:
        return None
    error, message = frame.get("error"), frame.get("message")
    if not isinstance(error, str) or not error or not isinstance(message, str):
        return None
    return {"code": error, "message": message}


def _protocol(entry) -> int:
    protocol = getattr(entry, "protocol", 1)
    if type(protocol) is not int or protocol not in (1, 2):
        raise LineJsonPreflight("protocol_mismatch")
    return protocol


def build_frame_v2(operation, reservation, args, tool=None) -> bytes:
    """Build one canonical v2 request, rejecting it before any spawn."""
    if operation not in V2_OPERATIONS:
        raise LineJsonPreflight("bad_request")
    if not isinstance(reservation, str) or not reservation or "\x00" in reservation:
        raise LineJsonPreflight("bad_request")
    if not isinstance(args, dict):
        raise LineJsonPreflight("bad_request")
    if operation == "invoke":
        if (not isinstance(tool, str) or TOOL_KEY_RE.fullmatch(tool) is None
                or tool == RESERVED_TOOL_KEY):
            raise LineJsonPreflight("bad_request")
    elif tool is not None:
        raise LineJsonPreflight("bad_request")
    frame = {"v": 2, "operation": operation,
             "reservation": reservation, "args": args}
    if operation == "invoke":
        frame["tool"] = tool
    try:
        raw = canonical.compact_json(frame) + b"\n"
    except (canonical.CanonicalError, UnicodeError, RecursionError) as exc:
        raise LineJsonPreflight("bad_request") from exc
    if len(raw) > 1024 * 1024:
        raise LineJsonPreflight("bad_request")
    return raw


def _classify_v2(raw, *, operation, exit_code) -> tuple[str, dict | None]:
    """Classify v2 stdout using only the terminal LF byte as a boundary."""
    if raw == b"":
        return "eof", None
    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeDecodeError:
        return "stdout_not_utf8", None
    lf_count = raw.count(b"\n")
    if lf_count > 1:
        return "extra_frame", None
    if not raw.endswith(b"\n") or lf_count != 1 or text.startswith("\ufeff"):
        return "bad_frame", None
    text = text[:-1].strip(" \t\r")
    try:
        obj = canonical.strict_loads(text)
    except (ValueError, UnicodeError, RecursionError):
        return "bad_frame", None
    if not isinstance(obj, dict):
        return "bad_frame", None
    if obj.get("v") != 2:
        return "version_mismatch", None
    if type(obj.get("ok")) is not bool:
        return "bad_frame", None
    if obj["ok"] is True:
        if exit_code != 0 or set(obj) != {"ok", "v", "result"}:
            return "bad_frame", None
        result = obj["result"]
        if not isinstance(result, dict):
            return "bad_frame", None
        keys = set(result)
        if operation == "invoke":
            if not {"value"} <= keys <= {"value", "meta"}:
                return "bad_frame", None
            if "meta" in result and not isinstance(result["meta"], dict):
                return "bad_frame", None
        elif operation == "prepare":
            if keys != {"prepared"} or result["prepared"] is not True:
                return "bad_frame", None
        elif operation == "release":
            if keys != {"released"} or result["released"] is not True:
                return "bad_frame", None
        elif operation == "inspect":
            if keys != {"observed"} or result["observed"] not in ("known", "absent"):
                return "bad_frame", None
        else:
            return "bad_frame", None
        # strict_loads already rejects every value outside the J domain (D14).
        return "success", result
    if exit_code != 3 or set(obj) != {"ok", "v", "error"}:
        return "bad_frame", None
    error = obj["error"]
    try:
        tool_results.assert_unknown_output({"error": error})
    except tool_results.ToolResultError:
        return "bad_frame", None
    return "known_error", error


def _spec_v2(entry, operation, tool) -> ProcessSpec:
    timeout_ms = entry.timeout_ms
    if operation == "invoke":
        approved = next((item for item in entry.tools if item.key == tool), None)
        if approved is None:
            raise LineJsonPreflight("tool_not_approved")
        timeout_ms = approved.timeout_ms
    return ProcessSpec(
        argv=tuple(entry.argv),
        cwd=entry.cwd,
        env=entry.environment(),
        timeout_ms=timeout_ms,
        stdout_limit=entry.stdout_limit,
        stderr_limit=entry.stderr_limit,
    )


def _run_v2(entry, operation, reservation, args, tool) -> Invocation:
    frame = build_frame_v2(operation, reservation, args, tool)
    try:
        spec = replace(_spec_v2(entry, operation, tool), stdin=frame)
    except (AttributeError, ProcessError) as exc:
        raise LineJsonPreflight("process_spec_invalid") from exc
    try:
        result = run_process(spec)
    except ProcessError as exc:
        raise LineJsonPreflight("spawn_failed") from exc
    common = {
        "returncode": result.returncode,
        "wall_ms": result.wall_ms,
        "pid": result.pid,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    if result.timed_out:
        return _unknown("timeout", **common)
    if result.stdout_limited:
        return _unknown("stdout_limit", **common)
    if result.stderr_limited:
        return _unknown("stderr_limit", **common)
    if result.returncode not in (0, 3):
        return _unknown("abnormal_exit", **common)
    classification, decoded = _classify_v2(
        result.stdout, operation=operation, exit_code=result.returncode)
    if classification not in ("success", "known_error"):
        return _unknown(classification, **common)
    class_name = "success" if classification == "success" else "failure"
    return Invocation(class_name, decoded, True, None, result.returncode,
                      result.wall_ms, result.pid, result.stdout, result.stderr)


def run(adapter, operation: str, reservation: str, args: dict,
        tool=None) -> Invocation:
    """Run one frame and classify the result.

    Raises :class:`LineJsonPreflight` only for a pre-spawn rejection; once a
    process exists every protocol defect is returned as ``unknown`` after the
    process group has been killed and reaped.
    """
    if _protocol(adapter) == 2:
        return _run_v2(adapter, operation, reservation, args, tool)
    frame = build_frame(operation, reservation, args)
    try:
        spec = _spec(adapter, frame)
    except (AttributeError, ProcessError) as exc:
        raise LineJsonPreflight("process_spec_invalid") from exc

    started = False
    try:
        result = run_process(spec)
        started = True
    except ProcessError as exc:
        raise LineJsonPreflight("spawn_failed") from exc

    common = {
        "returncode": result.returncode,
        "wall_ms": result.wall_ms,
        "pid": result.pid,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    if result.timed_out:
        return _unknown("timeout", **common)
    if result.stdout_limited:
        return _unknown("stdout_limit", **common)
    if result.stderr_limited:
        return _unknown("stderr_limit", **common)

    if result.returncode not in (0, 3):
        return _unknown("abnormal_exit", **common)
    try:
        frame = _frames(result.stdout)
    except ValueError as exc:
        return _unknown(str(exc), **common)

    if result.returncode == 0:
        decoded = _success_frame(frame)
        if decoded is None:
            return _unknown("bad_frame", **common)
        return Invocation("success", decoded, True, None, result.returncode,
                          result.wall_ms, result.pid, result.stdout,
                          result.stderr)
    decoded = _error_frame(frame)
    if decoded is None:
        return _unknown("bad_frame", **common)
    return Invocation("failure", decoded, True, None, result.returncode,
                      result.wall_ms, result.pid, result.stdout,
                      result.stderr)
