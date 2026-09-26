"""Line-JSON subprocess bridge for the Swift and Node read ports."""

from __future__ import annotations

import json
import subprocess


class ProtocolError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class LineReply:
    def __init__(self, exit_code: int, payload: dict) -> None:
        self.exit_code = exit_code
        self.payload = payload

    @property
    def ok(self) -> bool:
        return self.payload.get("ok") is True

    @property
    def result(self) -> str | None:
        value = self.payload.get("result")
        return value if isinstance(value, str) else None

    @property
    def error(self) -> str | None:
        value = self.payload.get("error")
        return value if isinstance(value, str) else None

    @property
    def message(self) -> str | None:
        value = self.payload.get("message")
        return value if isinstance(value, str) else None


_OMIT = object()


def run_line_json(argv, payload, *, timeout=30, stdin=_OMIT) -> LineReply:
    if stdin is _OMIT:
        data = json.dumps(payload).encode("utf-8")
    else:
        data = bytes(stdin)
    try:
        proc = subprocess.run(
            argv,
            input=data,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProtocolError(f"timeout: {exc}") from exc
    except OSError as exc:
        raise ProtocolError(str(exc)) from exc
    code = proc.returncode
    if code not in (0, 3):
        raise ProtocolError(f"exit {code}")
    stdout = proc.stdout
    if not stdout or not stdout.strip():
        raise ProtocolError("eof")
    line = stdout.split(b"\n", 1)[0]
    if not line.strip():
        raise ProtocolError("eof")
    try:
        parsed = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"bad frame: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ProtocolError("frame is not an object")
    if code == 0:
        if parsed.get("ok") is not True or not isinstance(parsed.get("result"), str):
            raise ProtocolError("exit 0 requires ok=true and string result")
    else:
        if parsed.get("ok") is not False or not isinstance(parsed.get("error"), str):
            raise ProtocolError("exit 3 requires ok=false and string error")
    return LineReply(code, parsed)
