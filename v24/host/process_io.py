"""Bounded one-shot process executor scaffolding for M-P.

The provider path is in-process HTTP (M-R), so this module has no callers yet.
It fixes the bounds the plugin path will need: an argv array (never a shell),
a fixed cwd, a minimal environment, bounded stdin/stdout/stderr, and a deadline
that kills the whole process group and reaps it.  Importing it opens nothing.
"""
from __future__ import annotations

import os
import selectors
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass

STDIN_LIMIT = 1024 * 1024
STDOUT_LIMIT = 64 * 1024
STDERR_LIMIT = 16 * 1024
DEFAULT_TIMEOUT_MS = 5000


class ProcessError(RuntimeError):
    """A spawn precondition failed; no process was started."""


@dataclass(frozen=True)
class ProcessSpec:
    argv: tuple[str, ...]
    cwd: str
    env: dict[str, str]
    stdin: bytes = b""
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    stdout_limit: int = STDOUT_LIMIT
    stderr_limit: int = STDERR_LIMIT


@dataclass(frozen=True)
class ProcessResult:
    pid: int
    returncode: int | None
    stdout: bytes
    stderr: bytes
    timed_out: bool
    stdout_limited: bool
    stderr_limited: bool
    wall_ms: int

    @property
    def ok(self) -> bool:
        return (self.returncode == 0 and not self.timed_out
                and not self.stdout_limited and not self.stderr_limited)


def _validate(spec: ProcessSpec) -> None:
    if not isinstance(spec.argv, tuple) or not spec.argv:
        raise ProcessError("argv must be a non-empty tuple")
    for item in spec.argv:
        if not isinstance(item, str) or not item or "\x00" in item:
            raise ProcessError("argv entries must be non-empty NUL-free strings")
    if not isinstance(spec.cwd, str) or not os.path.isdir(spec.cwd):
        raise ProcessError("cwd must be an existing directory")
    if not isinstance(spec.env, dict):
        raise ProcessError("env must be a mapping")
    for key, value in spec.env.items():
        if (not isinstance(key, str) or not key or "=" in key
                or not isinstance(value, str) or "\x00" in value):
            raise ProcessError("env must be a flat str->str mapping")
    if not isinstance(spec.stdin, bytes):
        raise ProcessError("stdin must be bytes")
    if len(spec.stdin) > STDIN_LIMIT:
        raise ProcessError("stdin exceeds the 1 MiB bound")
    if isinstance(spec.timeout_ms, bool) or not isinstance(spec.timeout_ms, int):
        raise ProcessError("timeout_ms must be an integer")
    if not 0 < spec.timeout_ms <= 300000:
        raise ProcessError("timeout_ms must be in (0, 300000]")
    if spec.stdout_limit < 1 or spec.stderr_limit < 1:
        raise ProcessError("output limits must be positive")


def _kill_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def run_process(spec: ProcessSpec) -> ProcessResult:
    """Run one process to completion or deadline, then reap it.

    A timeout or an output-limit breach still returns a result (with the flag
    set) after the process group has been killed and reaped.  Callers map that
    to ``unknown``; spawn/precondition failures raise before starting.
    """
    _validate(spec)
    started = time.monotonic()
    deadline = started + spec.timeout_ms / 1000.0
    with tempfile.TemporaryFile() as stdin_file:
        stdin_file.write(spec.stdin)
        stdin_file.seek(0)
        try:
            proc = subprocess.Popen(
                list(spec.argv),
                cwd=spec.cwd,
                env=dict(spec.env),
                stdin=stdin_file,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                close_fds=True,
                start_new_session=True,
            )
        except OSError as exc:
            raise ProcessError(f"spawn failed: {exc.__class__.__name__}") from None

        assert proc.stdout is not None and proc.stderr is not None
        out_fd, err_fd = proc.stdout.fileno(), proc.stderr.fileno()
        selector = selectors.DefaultSelector()
        buffers = {out_fd: bytearray(), err_fd: bytearray()}
        limits = {out_fd: spec.stdout_limit, err_fd: spec.stderr_limit}
        limited = {out_fd: False, err_fd: False}
        for stream in (proc.stdout, proc.stderr):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream.fileno(), selectors.EVENT_READ)
        open_fds = set(buffers)
        timed_out = False
        try:
            while open_fds:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    _kill_group(proc.pid)
                    break
                events = selector.select(remaining)
                if not events:
                    timed_out = True
                    _kill_group(proc.pid)
                    break
                for key, _ in events:
                    fd = key.fd
                    capacity = limits[fd] + 1 - len(buffers[fd])
                    try:
                        block = os.read(fd, max(1, min(65536, capacity)))
                    except BlockingIOError:
                        continue
                    except OSError:
                        block = b""
                    if not block:
                        selector.unregister(fd)
                        open_fds.discard(fd)
                        continue
                    buffers[fd].extend(block)
                    if len(buffers[fd]) > limits[fd]:
                        limited[fd] = True
                        _kill_group(proc.pid)
                        open_fds.clear()
                        break
        finally:
            selector.close()
            for stream in (proc.stdout, proc.stderr):
                try:
                    stream.close()
                except OSError:
                    pass

        try:
            returncode = proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _kill_group(proc.pid)
            returncode = proc.wait()
        wall_ms = int(max(0.0, time.monotonic() - started) * 1000)
        return ProcessResult(
            pid=proc.pid,
            returncode=returncode,
            stdout=bytes(buffers[out_fd]),
            stderr=bytes(buffers[err_fd]),
            timed_out=timed_out,
            stdout_limited=limited[out_fd],
            stderr_limited=limited[err_fd],
            wall_ms=wall_ms,
        )
