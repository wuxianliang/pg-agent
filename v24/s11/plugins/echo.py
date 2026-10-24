#!/usr/bin/env python3
"""Reference Python plugin for the v24 line-JSON plane.

One request frame on stdin, one response frame on stdout.  The same file is the
artifact hashed by ``v24/s11/plugin_fixtures.py``.

Operations:

* ``prepare``  - validate the reservation shape, report prepared;
* ``invoke``   - return ``{"echo": <args>, "language": "python"}``; the test
  sentinel ``{"__tool_error__": true}`` produces a known exit-3 tool error;
* ``release``  - idempotent success;
* ``inspect``  - report ``known`` for a v24 reservation, otherwise ``absent``.

No network, no files, no writes: an invocation is a pure function of the frame.
"""
from __future__ import annotations

import json
import sys


def _emit(frame: dict, code: int = 0) -> int:
    sys.stdout.write(json.dumps(frame, ensure_ascii=False, sort_keys=True,
                                separators=(",", ":")) + "\n")
    sys.stdout.flush()
    return code


def _ok(result: dict) -> int:
    return _emit({"ok": True, "result": json.dumps(
        result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))})


def _error(code: str, message: str) -> int:
    return _emit({"ok": False, "error": code, "message": message}, 3)


def main() -> int:
    line = sys.stdin.readline()
    try:
        frame = json.loads(line)
    except (TypeError, json.JSONDecodeError):
        return _error("invalid_frame", "request is not one JSON object")
    if (not isinstance(frame, dict) or frame.get("v") != 1
            or frame.get("operation") not in
            ("prepare", "invoke", "release", "inspect")
            or not isinstance(frame.get("reservation"), str)
            or not frame.get("reservation")
            or not isinstance(frame.get("args"), dict)):
        return _error("invalid_frame", "request frame shape is invalid")
    operation = frame["operation"]
    reservation = frame["reservation"]
    args = frame["args"]

    if operation == "prepare":
        if not reservation.startswith("v24:host_prepare:"):
            return _error("reservation_invalid", "prepare reservation mismatch")
        return _ok({"prepared": True, "language": "python",
                    "reservation": reservation})
    if operation == "invoke":
        if args.get("__tool_error__") is True:
            return _error("echo_tool_error", "requested known tool error")
        return _ok({"echo": args, "language": "python"})
    if operation == "release":
        if not reservation.startswith("v24:host_release:"):
            return _error("reservation_invalid", "release reservation mismatch")
        return _ok({"released": True, "language": "python",
                    "reservation": reservation})
    observed = "known" if reservation.startswith(
        ("v24:host_prepare:", "v24:host_release:")) else "absent"
    return _ok({"v": 1, "observed": observed, "reservation": reservation})


if __name__ == "__main__":
    raise SystemExit(main())
