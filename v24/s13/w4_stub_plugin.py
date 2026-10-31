"""Test-only v2 line-JSON plugin for the W4a wiring gate.

This is not one of the M3 filesystem tools and has no filesystem semantics.  It
reads exactly one request frame, writes at most one response frame, and exits
with the code the selected scenario requires.  When ``--spawn-log <abs path>``
is present it appends ``<pid> <operation>`` for every process start; without
the flag it writes no file (D15).
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

SCENARIOS = (
    "ok",
    "known_error",
    "bad_frame",
    "extra_frame",
    "no_lf",
    "timeout",
    "nonempty_meta",
    "bad_value",
    "bad_relation",
    "huge_value",
    "crash",
    "grandchild",
    "kill_parent",
)


def _spawn_log_path(argv):
    if "--spawn-log" not in argv:
        return None
    index = argv.index("--spawn-log")
    if index + 1 >= len(argv):
        return None
    return argv[index + 1]


def _append_spawn(path, operation):
    if path is None:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"{os.getpid()} {operation}\n")
        handle.flush()


def _read_value(**overrides):
    value = {
        "path": "a.txt",
        "text": "one",
        "start_line": 1,
        "end_line": 1,
        "total_lines": 1,
        "final_newline": False,
        "truncated": False,
        "truncated_by": None,
        "next_offset": None,
    }
    value.update(overrides)
    return value


def _success(result):
    return {"ok": True, "v": 2, "result": result}


def _write_frame(payload, *, newline=True):
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(raw + (b"\n" if newline else b""))
    sys.stdout.buffer.flush()


def _write_result(result, *, newline=True):
    _write_frame(_success(result), newline=newline)


def _known_error(code="stub_known_error", message="stub known error"):
    _write_frame({"ok": False, "v": 2,
                  "error": {"code": code, "message": message}}, newline=True)
    return 3


def _invoke(args):
    scenario = args.get("scenario", "ok")
    path = args.get("path", "a.txt")
    if scenario == "ok":
        if path == "join.txt":
            value = _read_value(path=path, text="one\n二\n三", end_line=3,
                                total_lines=3)
        else:
            value = _read_value(path=path)
        _write_result({"value": value})
        return 0
    if scenario == "known_error":
        return _known_error()
    if scenario == "bad_frame":
        sys.stdout.buffer.write(b"not-json\n")
        sys.stdout.buffer.flush()
        return 0
    if scenario == "extra_frame":
        _write_result({"value": _read_value(path=path)})
        _write_result({"value": _read_value(path=path)})
        return 0
    if scenario == "no_lf":
        _write_result({"value": _read_value(path=path)}, newline=False)
        return 0
    if scenario == "timeout":
        time.sleep(0.6)
        _write_result({"value": _read_value(path=path)})
        return 0
    if scenario == "nonempty_meta":
        _write_result({"value": _read_value(path=path),
                       "meta": {"private": "not model text"}})
        return 0
    if scenario == "bad_value":
        _write_result({"value": {"path": 7}})
        return 0
    if scenario == "bad_relation":
        _write_result({"value": _read_value(
            total_lines=3, end_line=1, text="one",
            truncated=False, truncated_by=None, next_offset=None)})
        return 0
    if scenario == "huge_value":
        _write_result({"value": _read_value(text="x" * 45000)})
        return 0
    if scenario == "crash":
        os._exit(7)
    if scenario == "grandchild":
        spawn_log = _spawn_log_path(sys.argv)
        assert spawn_log is not None
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"])
        Path(f"{spawn_log}.child").write_text(str(child.pid),
                                              encoding="utf-8")
        time.sleep(60)
    if scenario == "kill_parent":
        os.kill(os.getppid(), signal.SIGKILL)
        time.sleep(5)
    raise SystemExit(3)


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if len(argv) < 2 or argv[1] != "serve":
        print("stub_plugin: expected serve", file=sys.stderr)
        return 2
    spawn_log = _spawn_log_path(argv)
    line = sys.stdin.buffer.readline()
    frame = None
    try:
        frame = json.loads(line.decode("utf-8"))
        operation = frame.get("operation")
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        operation = "unknown"
    _append_spawn(spawn_log, operation)
    if not isinstance(frame, dict):
        sys.stdout.buffer.write(b"not-object\n")
        sys.stdout.buffer.flush()
        return 0
    if operation == "prepare":
        _write_result({"prepared": True})
        return 0
    if operation == "release":
        _write_result({"released": True})
        return 0
    if operation == "inspect":
        _write_result({"observed": "known"})
        return 0
    if operation == "invoke":
        args = frame.get("args")
        if not isinstance(args, dict):
            return _known_error("invalid_tool_arguments",
                                "arguments must be an object")
        return _invoke(args)
    sys.stdout.buffer.write(b"bad-operation\n")
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
