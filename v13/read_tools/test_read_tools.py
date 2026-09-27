"""Native read-tool gates.

--contract: A-C and F, exit 0 = pass.
No flag: A-E and F, exit 0 = pass.
Missing swift, node, or duck bring-up:
prints [SKIP] not_run/toolchain_absent and exits 2
before setup_db and before any green assertion.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from v13.read_tools.bridge import ProtocolError, run_line_json
from v13.read_tools.read_contract import ReadError, read_text, resolve_path
from v13.read_tools.read_duck_port import (
    EXPECTED_DUCKDB_VERSION,
    EXPECTED_EXTENSIONS,
    EXPECTED_PLATFORM,
    EXTENSION_CACHE,
    ToolError,
    resolve_path as duck_resolve,
)

SWIFT_SRC = str(ROOT / "read_file_swift.swift")
PI_SRC = str(ROOT / "read_pi.mjs")
DUCK_PY = ROOT / ".duck-venv" / "bin" / "python"
DUCK_PORT = ROOT / "read_duck_port.py"
FIXTURES = ROOT / "fixtures"
FIB_BYTES = (
    b"def fib(n):\n"
    b"    if n < 2:\n"
    b"        return n\n"
    b"    return fib(n - 1) + fib(n - 2)\n"
    b"\n"
    b"\n"
    b"print(fib(6))\n"
)
FIB_RENDER = (
    "fib(n)\n"
    "\n"
    "def fib(n):\n"
    "    if n < 2:\n"
    "        return n\n"
    "    return fib(n - 1) + fib(n - 2)"
)
JS_BYTES = b"function add(a, b) {\n  return a + b;\n}\nadd(1, 2);\n"
JS_RENDER = "add(a, b)\n\nfunction add(a, b) {\n  return a + b;\n}"
PIN_LABEL = (
    f"duckdb={EXPECTED_DUCKDB_VERSION}"
    f" sitting_duck={EXPECTED_EXTENSIONS['sitting_duck']['version']}"
    f" duck_block_utils={EXPECTED_EXTENSIONS['duck_block_utils']['version']}"
)
HELLO = b"line one\nline two\nline three\n"
CRLF = b"alpha\r\nbeta\r\n"
HEADLESS_CRLF = "alpha\n\nbeta\n\n"


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    extra = f": {detail}" if detail and (not condition or len(str(detail)) < 100) else ""
    print(f"[{mark}] {label}{extra}")
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def toolchain_present() -> bool:
    for cmd in (["swift", "--version"], ["node", "--version"]):
        try:
            proc = subprocess.run(cmd, capture_output=True)
        except OSError:
            return False
        if proc.returncode != 0:
            return False
    return True


def duck_toolchain_present() -> bool:
    if not DUCK_PY.is_file():
        return False
    return all(
        (EXTENSION_CACHE / f"{name}.duckdb_extension").is_file()
        for name in EXPECTED_EXTENSIONS
    )


def duck_argv() -> list[str]:
    return [str(DUCK_PY), str(DUCK_PORT)]


def duck_read(root: str, path: str, *, path_key: bool = True):
    payload = {"root": root}
    if path_key:
        payload["path"] = path
    return run_line_json(duck_argv(), payload)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def duck_inventory() -> dict:
    script = """
import json
import duckdb
con = duckdb.connect(":memory:")
con.execute("SET autoinstall_known_extensions=false")
con.execute("SET autoload_known_extensions=false")
con.execute("LOAD sitting_duck")
con.execute("LOAD duck_block_utils")
platform = con.execute("PRAGMA platform").fetchone()[0]
rows = con.execute(
    "SELECT extension_name, extension_version, loaded FROM duckdb_extensions() "
    "WHERE extension_name IN ('sitting_duck', 'duck_block_utils')"
).fetchall()
langs = con.execute(
    "SELECT language, extensions FROM ast_supported_languages()"
).fetchall()
print(json.dumps({
    "duckdb": duckdb.__version__,
    "platform": platform,
    "rows": rows,
    "langs": langs,
}))
"""
    proc = subprocess.run(duck_argv()[:1] + ["-c", script], capture_output=True, text=True)
    check("F1", proc.returncode == 0, proc.stderr)
    return json.loads(proc.stdout)


def expect_py(label: str, root: str, path: str, code: str) -> None:
    try:
        read_text(root, path)
    except ReadError as exc:
        check(label, exc.code == code, exc.code)
        return
    check(label, False, f"expected {code}")


def swift_read(root: str, path: str, start_line=None, limit=None, *, path_key: bool = True):
    payload = {"root": root, "start_line": start_line, "limit": limit}
    if path_key:
        payload["path"] = path
    return run_line_json(["swift", SWIFT_SRC], payload)


def pi_read(root: str, path: str, **fields):
    payload = {"root": root, "path": path}
    payload.update(fields)
    return run_line_json(["node", PI_SRC], payload)


def expect_protocol(label: str, argv, stdin: bytes = b"", pidfile: Path | None = None) -> None:
    started = time.monotonic()
    try:
        run_line_json(argv, {}, stdin=stdin)
    except ProtocolError:
        elapsed = time.monotonic() - started
        reaped = True
        if pidfile is not None and pidfile.is_file():
            pid = int(pidfile.read_text())
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                reaped = True
            else:
                reaped = False
        check(label, elapsed < 10 and reaped, {"elapsed": round(elapsed, 3), "reaped": reaped})
        return
    check(label, False, "expected ProtocolError")


def py_child(pidfile: Path, body: str) -> list[str]:
    script = (
        "import os, pathlib, sys\n"
        f"pathlib.Path({str(pidfile)!r}).write_text(str(os.getpid()))\n"
        + body
    )
    return [sys.executable, "-c", script]


def node_child(pidfile: Path, body: str) -> list[str]:
    script = (
        f"require('fs').writeFileSync({str(pidfile)!r}, String(process.pid));"
        + body
    )
    return ["node", "-e", script]


def run_a() -> None:
    fixture_root = str(FIXTURES)
    body = (FIXTURES / "hello.txt").read_bytes()
    check("A1", body == HELLO and read_text(fixture_root, "hello.txt") == body.decode("utf-8"))
    check("A2", read_text(fixture_root, "hello.txt", 2, 2) == "line two\nline three")
    full = read_text(fixture_root, "hello.txt", 0)
    check("A3", full == read_text(fixture_root, "hello.txt", 1) == body.decode("utf-8"))
    check("A4", read_text(fixture_root, "hello.txt", -1) == "")
    check("A4", read_text(fixture_root, "hello.txt", -2, 1) == "line three\n")
    try:
        missed = read_text(fixture_root, "hello.txt", 99)
    except ReadError as exc:
        check("A5", False, exc.code)
        return
    check("A5", missed == "")
    check("A6", read_text(fixture_root, "hello.txt", 1, 0) == "")
    check("A6", read_text(fixture_root, "hello.txt", limit=1) == body.decode("utf-8"))
    crlf_bytes = (FIXTURES / "crlf.txt").read_bytes()
    check("A7", crlf_bytes == CRLF, crlf_bytes)
    check("A7", read_text(fixture_root, "crlf.txt") == HEADLESS_CRLF)

    with tempfile.TemporaryDirectory(prefix="v13read-a-") as raw:
        tmp = Path(raw)
        (tmp / "empty.txt").write_bytes(b"")
        check("A6", read_text(str(tmp), "empty.txt") == "")
        (tmp / "u2028.txt").write_bytes("a\u2028b".encode("utf-8"))
        check("A8", read_text(str(tmp), "u2028.txt") == "a\nb")
        expect_py("A9", fixture_root, "", "invalid_params")
        expect_py("A9", fixture_root, "   \t", "invalid_params")
        try:
            read_text(fixture_root, None)
        except ReadError as exc:
            check("A9", exc.code == "invalid_params", exc.code)
        else:
            check("A9", False, "missing path")
        expect_py("A9", fixture_root, "a\0b", "path_outside_workspace")
        expect_py("A9", fixture_root, "../../etc/hosts", "path_outside_workspace")
        (tmp / "bad.bin").write_bytes(b"\xff\xfe")
        expect_py("A9", str(tmp), "bad.bin", "read_failed")
        expect_py("A9", fixture_root, "missing.txt", "read_failed")

        real = tmp / "realroot"
        real.mkdir()
        (real / "inside.txt").write_bytes(b"inside\n")
        link = tmp / "linkroot"
        link.symlink_to(real, target_is_directory=True)
        check("A10", read_text(str(link), "inside.txt") == "inside\n")
        outside = tmp / "outside.txt"
        outside.write_bytes(b"secret\n")
        (real / "escape").symlink_to(outside)
        expect_py("A10", str(real), "escape", "path_outside_workspace")

        var_real = os.path.realpath("/var")
        if var_real == "/var":
            print("[SKIP] A10 realpath('/var') == '/var'; /var spelling check not run")
        else:
            host = tempfile.mkdtemp(prefix="v13a10-", dir="/var/tmp")
            try:
                host_real = os.path.realpath(host)
                check("A10", host_real.startswith(var_real), host_real)
                host_var = "/var" + host_real[len(var_real) :]
                (Path(host_real) / "f.txt").write_bytes(b"v\n")
                via_var = read_text(host_real, host_var + "/f.txt")
                via_real = read_text(host_real, host_real + "/f.txt")
                check("A10", via_var == via_real == "v\n", (via_var, via_real))
            finally:
                shutil.rmtree(host, ignore_errors=True)

        work = tmp / "a11"
        work.mkdir()
        (work / "hello.txt").write_bytes(HELLO)
        out_dir = tmp / "a11out"
        out_dir.mkdir()
        (work / "foo").symlink_to(out_dir, target_is_directory=True)
        rel = read_text(str(work), "hello.txt")
        abs_path = os.path.realpath(work / "hello.txt")
        check("A11", rel == read_text(str(work), abs_path) == HELLO.decode("utf-8"))
        check("A11", read_text(str(work), "foo/../hello.txt") == HELLO.decode("utf-8"))
        expect_py("A11", str(work), "/etc/hosts", "path_outside_workspace")


def run_b() -> None:
    fixture_root = str(FIXTURES)
    body = HELLO.decode("utf-8")
    full = swift_read(fixture_root, "hello.txt")
    check(
        "B1",
        full.ok and full.exit_code == 0 and full.result == read_text(fixture_root, "hello.txt") == body,
        full.payload,
    )
    for start, limit in ((2, 2), (-1, None), (99, None)):
        py = read_text(fixture_root, "hello.txt", start, limit)
        sw = swift_read(fixture_root, "hello.txt", start, limit)
        check("B2", sw.ok and sw.result == py, (start, limit, sw.payload))
    crlf = swift_read(fixture_root, "crlf.txt")
    check("B3", crlf.ok and crlf.result == read_text(fixture_root, "crlf.txt") == HEADLESS_CRLF)

    blank = swift_read(fixture_root, "   ")
    check("B4", blank.error == "invalid_params" and blank.exit_code == 3)
    try:
        read_text(fixture_root, "   ")
    except ReadError as exc:
        check("B4", exc.code == blank.error)
    else:
        check("B4", False, "python blank")
    missing_key = swift_read(fixture_root, "hello.txt", path_key=False)
    check("B4", missing_key.error == "invalid_params" and missing_key.exit_code == 3)
    nul = swift_read(fixture_root, "a\0b")
    try:
        read_text(fixture_root, "a\0b")
    except ReadError as exc:
        check("B4", nul.error == exc.code == "path_outside_workspace", nul.payload)
    else:
        check("B4", False, "python nul")
    escaped = swift_read(fixture_root, "../../etc/hosts")
    try:
        read_text(fixture_root, "../../etc/hosts")
    except ReadError as exc:
        check("B4", escaped.error == exc.code == "path_outside_workspace")
    else:
        check("B4", False, "python escape")

    with tempfile.TemporaryDirectory(prefix="v13read-b-") as raw:
        tmp = Path(raw)
        (tmp / "bad.bin").write_bytes(b"\xff\xfe")
        bad = swift_read(str(tmp), "bad.bin")
        try:
            read_text(str(tmp), "bad.bin")
        except ReadError as exc:
            check("B4", bad.error == exc.code == "read_failed", bad.payload)
        else:
            check("B4", False, "python utf8")
        missing = swift_read(fixture_root, "missing.txt")
        try:
            read_text(fixture_root, "missing.txt")
        except ReadError as exc:
            check("B4", missing.error == exc.code == "read_failed")
        else:
            check("B4", False, "python missing")
        (tmp / "u2028.txt").write_bytes("a\u2028b".encode("utf-8"))
        sw = swift_read(str(tmp), "u2028.txt")
        check("B7", sw.ok and sw.result == read_text(str(tmp), "u2028.txt") == "a\nb", sw.payload)

        empty = run_line_json(["swift", SWIFT_SRC], {}, stdin=b"")
        check("B4", empty.error == "invalid_params" and empty.exit_code == 3)
        blank_in = run_line_json(["swift", SWIFT_SRC], {}, stdin=b" \n\t")
        check("B4", blank_in.error == "invalid_params" and blank_in.exit_code == 3)

        pid_bad = tmp / "bad.pid"
        expect_protocol(
            "B5",
            py_child(pid_bad, "sys.stdout.buffer.write(b'not-json\\n')"),
            pidfile=pid_bad,
        )
        pid_eof = tmp / "eof.pid"
        expect_protocol("B5", py_child(pid_eof, "sys.exit(0)"), pidfile=pid_eof)
        pid_flag = tmp / "flag.pid"
        expect_protocol(
            "B5",
            py_child(
                pid_flag,
                "sys.stdout.write('{\"ok\":false,\"error\":\"x\",\"message\":\"y\"}\\n')",
            ),
            pidfile=pid_flag,
        )
        try:
            run_line_json(["swift", SWIFT_SRC], {}, stdin=b"{")
        except ProtocolError:
            check("B5", True)
        else:
            check("B5", False, "swift bad json")

    started = time.monotonic()
    timed = swift_read(fixture_root, "hello.txt")
    elapsed = time.monotonic() - started
    check("B6", timed.ok and timed.result == body and elapsed < 10, round(elapsed, 3))


def pi_lines(text: str) -> list[str]:
    return text.split("\n")


def run_c() -> None:
    fixture_root = str(FIXTURES)
    hello = HELLO.decode("utf-8")
    lines = pi_lines(hello)
    offset = 2
    start = max(0, offset - 1)
    expected = "\n".join(lines[start:])
    got = pi_read(fixture_root, "hello.txt", offset=offset)
    check("C1", got.ok and got.exit_code == 0 and got.result == expected, got.payload)
    for off in (0, -4):
        reply = pi_read(fixture_root, "hello.txt", offset=off)
        check("C1b", reply.ok and reply.result == "\n".join(lines), (off, reply.payload))

    with tempfile.TemporaryDirectory(prefix="v13read-c-") as raw:
        tmp = Path(raw)
        (tmp / "a.txt").write_bytes(b"a\n")
        ok_tail = pi_read(str(tmp), "a.txt", offset=2)
        check("C2", ok_tail.ok and ok_tail.result == "", ok_tail.payload)
        past = pi_read(str(tmp), "a.txt", offset=3)
        check(
            "C2",
            (not past.ok)
            and past.exit_code == 3
            and past.error == "offset_out_of_range"
            and "result" not in past.payload,
            past.payload,
        )

        limit = 2
        user_limited = min(limit, len(lines))
        selected = "\n".join(lines[:user_limited])
        remaining = len(lines) - user_limited
        next_offset = user_limited + 1
        c3 = pi_read(fixture_root, "hello.txt", limit=limit)
        c3_expected = (
            f"{selected}\n\n[{remaining} more lines in file. Use offset={next_offset} to continue.]"
        )
        check("C3", c3.ok and c3.result == c3_expected, c3.result)
        check("C3", c3.result is not None and "Showing lines" not in c3.result and "50.0KB" not in c3.result)

        c3b = pi_read(fixture_root, "hello.txt", limit=0)
        c3b_expected = f"\n\n[{len(lines)} more lines in file. Use offset=1 to continue.]"
        check("C3b", c3b.ok and c3b.result == c3b_expected, c3b.result)
        check("C3b", c3b.result is not None and "line one" not in c3b.result)

        wide = "b" * (20 * 1024)
        (tmp / "wide.txt").write_bytes("\n".join([wide] * 5).encode("utf-8"))
        c3c = pi_read(str(tmp), "wide.txt", limit=5)
        c3c_expected = (
            "\n".join([wide] * 2)
            + "\n\n[Showing lines 1-2 of 5 (50.0KB limit). Use offset=3 to continue.]"
        )
        check("C3c", c3c.ok and c3c.result == c3c_expected)
        check("C3c", c3c.result is not None and "more lines in file" not in c3c.result)

        missing_limit = pi_read(fixture_root, "hello.txt")
        null_limit = pi_read(fixture_root, "hello.txt", limit=None)
        check("C3d", missing_limit.ok and missing_limit.result == hello)
        check("C3d", null_limit.ok and null_limit.result == hello)
        check(
            "C3d",
            missing_limit.result is not None
            and "more lines in file" not in missing_limit.result
            and "Showing lines" not in missing_limit.result,
        )

        short = "\n".join(["x"] * 2001)
        (tmp / "lines.txt").write_bytes(short.encode("utf-8"))
        c4_lines = pi_read(str(tmp), "lines.txt")
        line_notice = "\n\n[Showing lines 1-2000 of 2001. Use offset=2001 to continue.]"
        check("C4", c4_lines.ok and c4_lines.result == "\n".join(["x"] * 2000) + line_notice)
        check("C4", c4_lines.result is not None and "50.0KB" not in c4_lines.result)

        byte_lines = ["a" * 1000] * 80
        (tmp / "bytes.txt").write_bytes("\n".join(byte_lines).encode("utf-8"))
        c4_bytes = pi_read(str(tmp), "bytes.txt")
        byte_notice = "\n\n[Showing lines 1-51 of 80 (50.0KB limit). Use offset=52 to continue.]"
        check("C4", c4_bytes.ok and c4_bytes.result == "\n".join(["a" * 1000] * 51) + byte_notice)

        long_name = "longline.txt"
        (tmp / long_name).write_bytes(b"Q" * 51201)
        c5 = pi_read(str(tmp), long_name)
        c5_expected = (
            "[Line 1 is 50.0KB, exceeds 50.0KB limit. "
            f"Use bash: sed -n '1p' {long_name} | head -c 51200]"
        )
        check("C5", c5.ok and c5.result == c5_expected, c5.result)
        check("C5", c5.result is not None and "Q" not in c5.result and "head -c 51200" in c5.result)

        outside = pi_read(fixture_root, "../hello.txt")
        check("C6", outside.error == "path_outside_workspace" and outside.exit_code == 3)
        absolute = pi_read(fixture_root, "/etc/hosts")
        check("C6", absolute.error == "path_outside_workspace")
        tilde = pi_read(fixture_root, "~/hello.txt")
        check("C6", (not tilde.ok) and tilde.error == "read_failed" and tilde.result != hello, tilde.payload)

        marker = b"UNIQUE_IMAGE_BYTES_ZZZ"
        for name in ("x.png", "x.jpg", "x.jpeg", "x.gif", "x.webp", "x.bmp", "x.PNG"):
            (tmp / name).write_bytes(marker)
            reply = pi_read(str(tmp), name)
            encoded = json.dumps(reply.payload)
            check(
                "C7",
                reply.error == "image_unsupported"
                and reply.exit_code == 3
                and "result" not in reply.payload
                and "UNIQUE_IMAGE_BYTES_ZZZ" not in encoded,
                (name, reply.payload),
            )
        outside_png = pi_read(str(tmp), "/etc/outside.png")
        check("C7", outside_png.error == "path_outside_workspace", outside_png.payload)

        pid_bad = tmp / "c8-bad.pid"
        expect_protocol(
            "C8",
            node_child(pid_bad, "process.stdout.write('nope');"),
            pidfile=pid_bad,
        )
        pid_eof = tmp / "c8-eof.pid"
        expect_protocol("C8", node_child(pid_eof, "process.exit(0);"), pidfile=pid_eof)
        pid_flag = tmp / "c8-flag.pid"
        expect_protocol(
            "C8",
            node_child(
                pid_flag,
                "process.stdout.write(JSON.stringify({ok:false,error:'x',message:'y'})+'\\n');",
            ),
            pidfile=pid_flag,
        )
        empty = run_line_json(["node", PI_SRC], {}, stdin=b"")
        check("C8", empty.error == "invalid_params" and empty.exit_code == 3)

    pi_crlf = pi_read(fixture_root, "crlf.txt")
    raw = CRLF.decode("utf-8")
    by_lf = "\n".join(raw.split("\n"))
    check("C9", pi_crlf.ok and pi_crlf.result != HEADLESS_CRLF and pi_crlf.result == by_lf, pi_crlf.result)


PARAM_SPEC = {
    "path": {
        "question": "Which fixture file should be read?",
        "stated": "Does the user name a fixture file to read?",
        "options": {"hello.txt": "LF fixture", "crlf.txt": "CRLF fixture"},
    }
}
DUCK_PARAM_SPEC = {
    "path": {
        "question": "Which fixture file should be read?",
        "stated": "Does the user name a fixture file to read?",
        "options": {"fib.py": "Python fixture"},
    }
}
TOOL_ROWS = (
    ("read_pi", "Read a text file with Pi line slicing and truncation.", "worker:read_pi", PARAM_SPEC),
    ("read_file_swift", "Read a text file with the headless line contract (swift).", "worker:read_file_swift", PARAM_SPEC),
    ("read_file_py", "Read a text file with the headless line contract (python).", "worker:read_file_py", PARAM_SPEC),
    ("read_duck", "Read a source file with the DuckDB AST block contract.", "worker:read_duck", DUCK_PARAM_SPEC),
)
NEW_BANDS = (
    "param::read_pi::path",
    "stated::read_pi::path",
    "param::read_file_swift::path",
    "stated::read_file_swift::path",
    "param::read_file_py::path",
    "stated::read_file_py::path",
    "param::read_duck::path",
    "stated::read_duck::path",
)
HANDLERS = {
    "worker:read_pi": "read_pi",
    "worker:read_file_swift": "read_file_swift",
    "worker:read_file_py": "read_file_py",
    "worker:read_duck": "read_duck",
}
LLM_RESULT = {
    "text": "four reads recorded",
    "model": "fake",
    "usage": {"input_tokens": 1, "output_tokens": 1},
}
BASELINE_TOOLS = (
    "session_stats",
    "send_summary_email",
    "harness_turn",
    "spawn_subsession",
    "worktree_prepare",
    "worktree_merge",
    "worktree_release",
)


def as_obj(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def choice_answer(name: str, conf: float = 0.9) -> dict:
    return {
        "type": "choice",
        "choice": name,
        "probabilities": {name: conf},
        "confidence": conf,
    }


def dispatch_handler(handler: str, params: dict, root: str) -> str:
    if handler == "worker:read_file_py":
        return read_text(root, params["path"])
    if handler == "worker:read_file_swift":
        reply = run_line_json(
            ["swift", SWIFT_SRC],
            {"root": root, "path": params["path"], "start_line": None, "limit": None},
        )
        if not reply.ok:
            raise ReadError(reply.error or "read_failed", reply.message or "swift read failed")
        return reply.result or ""
    if handler == "worker:read_pi":
        reply = run_line_json(["node", PI_SRC], {"root": root, "path": params["path"]})
        if not reply.ok:
            raise ReadError(reply.error or "read_failed", reply.message or "pi read failed")
        return reply.result or ""
    if handler == "worker:read_duck":
        reply = run_line_json(duck_argv(), {"root": root, "path": params["path"]})
        if not reply.ok:
            raise ReadError(reply.error or "read_failed", reply.message or "duck read failed")
        return reply.result or ""
    raise ReadError("protocol_error", f"unknown handler {handler}")


def pi_plain(text: str) -> str:
    return "\n".join(text.split("\n"))


def run_ring() -> None:
    import inspect
    import uuid

    import psycopg2

    from server import get_server
    from v13.read_tools.setup_db import DB, main as setup_db

    setup_db()
    server = get_server()
    conn = psycopg2.connect(server.get_uri(DB))
    conn.autocommit = False
    fixture_root = os.path.realpath(FIXTURES)
    ticks = {"n": 0}
    saved = {}

    def begin():
        if conn.get_transaction_status() != psycopg2.extensions.TRANSACTION_STATUS_IDLE:
            conn.rollback()
        return conn.cursor()

    def parse_fresh(sid, mode, phase):
        pc = psycopg2.connect(server.get_uri(DB))
        pc.autocommit = False
        pcur = pc.cursor()
        pcur.execute("SELECT set_config('typesafe.provider', 'mock', false)")
        pcur.fetchone()
        pcur.execute("SELECT set_config('typesafe.model', 'fake-judge', false)")
        pcur.fetchone()
        mock = mock_from_needed(pcur, sid, **overrides_for(pcur, sid, mode, phase))
        pcur.execute("SELECT set_config('typesafe.mock_response', %s, true)", (mock,))
        pcur.fetchone()
        try:
            snap = as_obj(q1(pcur, "SELECT v13_parse(%s)", (sid,)))
        except psycopg2.Error as exc:
            pc.rollback()
            pc.close()
            raise AssertionError(
                f"parse {mode}: {exc.pgcode} {exc.diag.message_primary if exc.diag else exc}"
            ) from exc
        pc.commit()
        pc.close()
        return snap

    def q1(cur, sql, params=None):
        cur.execute(sql, params)
        return cur.fetchone()[0]

    def event_count(cur, sid, etype) -> int:
        cur.execute(
            "SELECT count(*) FROM events WHERE session_id=%s AND type=%s",
            (sid, etype),
        )
        return cur.fetchone()[0]

    def mock_from_needed(cur, sid, **over) -> str:
        cur.execute("SELECT signal, kind, criteria FROM v13_needed_judgments(%s)", (sid,))
        answers = {}
        for signal, kind, criteria in cur.fetchall():
            criteria = as_obj(criteria)
            if signal in over:
                answers[signal] = over[signal]
                continue
            if kind == "choice":
                keys = list(criteria.keys()) if isinstance(criteria, dict) else ["none"]
                ch = keys[0]
                answers[signal] = choice_answer(ch)
            elif kind == "score":
                answers[signal] = {"type": "score", "score": 0.5, "confidence": 0.9}
            else:
                answers[signal] = {"type": "noul", "noul": 0.1}
        answers.update(over)
        return json.dumps({
            "model": "jev-mock",
            "answers": answers,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        })

    def overrides_for(cur, sid, mode: str, phase: str | None = None) -> dict:
        base = {
            "gate_action": {"type": "noul", "noul": 0.9},
            "gate_off_topic": {"type": "noul", "noul": 0.1},
            "risk": {"type": "score", "score": 0, "confidence": 0.9},
        }
        n_tools = event_count(cur, sid, "tool/result")
        has_llm = event_count(cur, sid, "llm/message") > 0
        if phase is None:
            if mode == "literal":
                phase = "tool"
            elif has_llm:
                phase = "finish"
            elif n_tools >= (3 if mode == "neg" else 4):
                phase = "llm"
            else:
                phase = "tool"
        if phase == "tool":
            if mode == "duck_fail":
                tool = "read_duck"
            elif mode in ("fail", "literal"):
                tool = "read_file_py"
            else:
                tool = ("read_pi", "read_file_swift", "read_file_py", "read_duck")[n_tools]
            path_choice = "fib.py" if tool == "read_duck" else "hello.txt"
            base["intent"] = choice_answer("tool_action")
            base["tool"] = choice_answer(tool)
            base[f"stated::{tool}::path"] = {"type": "noul", "noul": 0.9}
            base[f"param::{tool}::path"] = choice_answer(path_choice)
        else:
            base["intent"] = choice_answer("llm_generate")
            base["tool"] = choice_answer("none")
        return base

    def open_session(cur, text="Read hello.txt") -> str:
        sid = str(q1(
            cur,
            "SELECT v13_open_session(%s::jsonb)",
            (json.dumps({"route_policy_name": "default", "version": 2}),),
        ))
        cur.execute(
            "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
            (sid, str(uuid.uuid4()), json.dumps({"text": text})),
        )
        cur.execute(
            "SELECT v13_submit_override(%s, %s::jsonb)",
            (sid, json.dumps({
                "schema_version": 1,
                "intent": "direct",
                "source_principal": "user",
                "reason": "read-tools gate",
            })),
        )
        return sid

    def complete(cur, claim, status, result):
        cur.execute(
            "SELECT v13_complete(%s, %s, %s, %s, %s::jsonb)",
            (
                claim["effect_id"],
                claim["attempt_no"],
                claim["fence"],
                status,
                json.dumps(result),
            ),
        )
        return cur.fetchone()[0]

    def abort_claim(claim) -> None:
        try:
            conn.rollback()
        except Exception:
            pass
        try:
            cur = begin()
            complete(cur, claim, "failed", {
                "error": "protocol_error",
                "message": "hub aborted",
            })
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

    def beat(sid, mode, swap=None, expect_terminal=False, phase=None):
        ticks["n"] += 1
        check("ticks", ticks["n"] <= 16, ticks["n"])
        snap = parse_fresh(sid, mode, phase)
        remaining = int(snap["remaining"])
        check(mode, remaining == 0, remaining)

        cur = begin()
        cur.execute("SET LOCAL lock_timeout='250ms'")
        cur.execute("SET LOCAL statement_timeout='5s'")
        cur.execute(
            "UPDATE sessions SET context_active_revision = v13_context_required(session_id) "
            "WHERE session_id=%s",
            (sid,),
        )
        try:
            status = q1(cur, "SELECT v13_advance(%s, %s::jsonb)", (sid, json.dumps(snap)))
        except psycopg2.Error as exc:
            conn.rollback()
            raise AssertionError(
                f"advance {mode}: {exc.pgcode} {exc.diag.message_primary if exc.diag else exc}"
            ) from exc
        conn.commit()
        if status == "terminal":
            check(mode, expect_terminal, status)
            return {"advance": status}
        check(mode, status == "waiting", status)

        cur = begin()
        cur.execute(
            "SELECT effect_id::text, session_id::text FROM effects WHERE status='ready'"
        )
        ready = cur.fetchall()
        check(mode, len(ready) == 1 and ready[0][1] == sid, ready)
        claim = as_obj(q1(cur, "SELECT v13_claim(%s, %s)", ("read-tools-hub", 60000)))
        check(mode, claim and str(claim["effect_id"]) == ready[0][0], claim)
        conn.commit()
        req = claim.get("request") or {}
        print(f"[beat] {mode} {claim['kind']} {req.get('handler') or req.get('reason')}")

        completed = False
        flag = None
        try:
            kind = claim["kind"]
            request = claim["request"]
            if kind == "human":
                payload, st, flag = {"reason": request["reason"]}, "succeeded", None
            elif kind == "llm":
                payload, st, flag = LLM_RESULT, "succeeded", None
            elif kind == "judge":
                raise AssertionError(f"judge effect: {claim}")
            elif kind != "tool":
                payload = {"error": "protocol_error", "message": f"unknown kind {kind}"}
                st, flag = "failed", "unknown"
            else:
                handler = request.get("handler")
                if handler not in HANDLERS:
                    payload = {"error": "protocol_error", "message": f"unknown handler {handler}"}
                    st, flag = "failed", "unknown"
                else:
                    params = dict(request.get("params") or {})
                    root = fixture_root
                    if swap:
                        if "path" in swap:
                            params["path"] = swap["path"]
                        if "root" in swap:
                            root = swap["root"]
                    try:
                        payload = dispatch_handler(handler, params, root)
                        st, flag = "succeeded", None
                    except ReadError as exc:
                        payload = {"error": exc.code, "message": exc.message}
                        st, flag = "failed", None
            cur = begin()
            cur.execute("SET LOCAL lock_timeout='250ms'")
            cur.execute("SET LOCAL statement_timeout='5s'")
            got = complete(cur, claim, st, payload)
            conn.commit()
            completed = True
            check(mode, got == "accepted", got)
            if flag == "unknown":
                raise AssertionError(f"unknown handler settled: {claim}")
            return {"advance": status, "claim": claim, "payload": payload, "status": st}
        finally:
            if not completed:
                abort_claim(claim)

    def routes_of(sid):
        cur = begin()
        cur.execute(
            "SELECT payload FROM events WHERE session_id=%s AND type='turn/route' ORDER BY seq",
            (sid,),
        )
        rows = [as_obj(r[0]) for r in cur.fetchall()]
        conn.rollback()
        return rows

    def end_of(sid):
        cur = begin()
        cur.execute(
            "SELECT payload FROM events WHERE session_id=%s AND type='turn/end' ORDER BY seq",
            (sid,),
        )
        rows = [as_obj(r[0]) for r in cur.fetchall()]
        status = q1(cur, "SELECT status FROM sessions WHERE session_id=%s", (sid,))
        conn.rollback()
        return status, rows

    def residual(cur):
        cur.execute(
            "SELECT count(*) FROM effects WHERE status IN ('ready', 'claimed', 'unknown')"
        )
        return cur.fetchone()[0]

    src = inspect.getsource(dispatch_handler)
    check("D14", "FROM tools" not in src, src)

    cur = begin()
    cur.execute("SELECT set_config('typesafe.provider', 'mock', false)")
    cur.fetchone()
    cur.execute("SELECT set_config('typesafe.model', 'fake-judge', false)")
    cur.fetchone()
    cur.execute(
        "UPDATE tools SET enabled=false WHERE name='spawn_subsession' AND enabled"
    )
    conn.commit()

    cur = begin()
    check("D1", q1(cur, "SELECT v13_policy('turn_budget')->>'max_cycles'") == "3")
    complete_def = q1(
        cur,
        "SELECT pg_get_functiondef('v13_complete(uuid,integer,bigint,text,jsonb)'::regprocedure)",
    )
    advance_def = q1(
        cur,
        "SELECT pg_get_functiondef('v13_advance(uuid,jsonb)'::regprocedure)",
    )
    check("D3b", "v13_record_worktree_released" in complete_def)
    check("D3b", "WHEN 'finish'" in advance_def and "v13_triage_prework" in advance_def)

    cur.execute(
        "INSERT INTO v13_route_policies (policy_name, policy_version) VALUES ('default', 2)"
    )
    cur.execute(
        "INSERT INTO thresholds (policy_name, policy_version, signal, band_no, lo, hi, action) "
        "SELECT 'default', 2, signal, band_no, lo, hi, action "
        "FROM thresholds WHERE policy_name='default' AND policy_version=1"
    )
    for signal in NEW_BANDS:
        cur.execute(
            "INSERT INTO thresholds (policy_name, policy_version, signal, band_no, lo, hi, action) "
            "VALUES ('default', 2, %s, 1, 0.60, 'Infinity', 'pass')",
            (signal,),
        )
    cur.execute(
        "UPDATE v13_route_policies SET state='frozen' "
        "WHERE policy_name='default' AND policy_version=2"
    )
    v1_bands = q1(
        cur,
        "SELECT count(*) FROM thresholds WHERE policy_name='default' AND policy_version=1",
    )
    v2_bands = q1(
        cur,
        "SELECT count(*) FROM thresholds WHERE policy_name='default' AND policy_version=2",
    )
    cur.execute(
        "SELECT signal FROM thresholds WHERE policy_name='default' AND policy_version=2 "
        "AND signal = ANY(%s)",
        (list(NEW_BANDS),),
    )
    found_bands = {row[0] for row in cur.fetchall()}
    state = q1(
        cur,
        "SELECT state FROM v13_route_policies WHERE policy_name='default' AND policy_version=2",
    )
    check("D2", v2_bands == v1_bands + 8, (v1_bands, v2_bands))
    check("D2", found_bands == set(NEW_BANDS), found_bands)
    check("D2", state == "frozen", state)
    conn.commit()

    cur = begin()
    base_count = q1(cur, "SELECT count(*) FROM tools")
    cur.execute("SELECT name FROM tools ORDER BY name")
    base_names = tuple(row[0] for row in cur.fetchall())
    base_rev = q1(cur, "SELECT revision FROM v13_tools_meta WHERE singleton")
    measure = str(q1(cur, "SELECT v13_open_session('{}'::jsonb)"))
    needed_before = q1(cur, "SELECT count(*) FROM v13_needed_judgments(%s)", (measure,))
    cur.execute("SELECT signal FROM v13_needed_judgments(%s) ORDER BY signal", (measure,))
    signals_before = [row[0] for row in cur.fetchall()]
    batch = int(q1(cur, "SELECT v13_policy('resolve_fast_path')->>'batch_questions'"))
    check("D3", base_count == 7 and set(base_names) == set(BASELINE_TOOLS), base_names)
    print(f"[anchor] tools={base_count} needed_before={needed_before} signals={signals_before}")
    for name, desc, handler, spec in TOOL_ROWS:
        cur.execute(
            "INSERT INTO tools (name, description, kind, handler, param_spec, enabled) "
            "VALUES (%s, %s, 'tool', %s, %s::jsonb, true)",
            (name, desc, handler, json.dumps(spec)),
        )
    after_count = q1(cur, "SELECT count(*) FROM tools")
    after_rev = q1(cur, "SELECT revision FROM v13_tools_meta WHERE singleton")
    needed_after = q1(cur, "SELECT count(*) FROM v13_needed_judgments(%s)", (measure,))
    duck_row = as_obj(q1(
        cur,
        "SELECT jsonb_build_object('kind', kind, 'handler', handler, 'enabled', enabled, "
        "'description', description, 'param_spec', param_spec) FROM tools WHERE name='read_duck'",
    ))
    check("D3", after_count == base_count + 4, (base_count, after_count))
    check("D3", after_rev == base_rev + 4, (base_rev, after_rev))
    check("D3", needed_after == needed_before + 8, (needed_before, needed_after, signals_before))
    check("D3", duck_row["kind"] == "tool" and duck_row["handler"] == "worker:read_duck" and duck_row["enabled"] is True, duck_row)
    check("D3", duck_row["description"].isascii(), duck_row["description"])
    check("D3", duck_row["param_spec"]["path"]["options"] == {"fib.py": "Python fixture"}, duck_row["param_spec"])
    check("D3", needed_after <= batch, (needed_after, batch))
    conn.commit()
    saved["needed_before"] = needed_before
    saved["base_count"] = base_count
    saved["base_rev"] = base_rev

    cur = begin()
    neg = open_session(cur, "Read hello.txt")
    pointed = q1(
        cur,
        "SELECT route_policy_version FROM sessions WHERE session_id=%s",
        (neg,),
    )
    check("D2", pointed == 2, pointed)
    conn.commit()
    neg_reads = []
    for _ in range(3):
        step = beat(neg, "neg")
        neg_reads.append(step)
    budget = beat(neg, "neg")
    check(
        "D4",
        budget["claim"]["kind"] == "human"
        and budget["claim"]["request"].get("reason") == "budget_exhausted",
        budget.get("claim"),
    )
    terminal = beat(neg, "neg", expect_terminal=True)
    check("D4", terminal["advance"] == "terminal", terminal)
    neg_routes = routes_of(neg)
    check("D4", len(neg_routes) == 3, neg_routes)
    check("D4", [r.get("action") for r in neg_routes] == ["tool", "tool", "tool"], neg_routes)
    check(
        "D4",
        [r.get("tool") for r in neg_routes] == ["read_pi", "read_file_swift", "read_file_py"],
        neg_routes,
    )
    neg_status, neg_ends = end_of(neg)
    check("D4", neg_status == "failed", neg_status)
    check(
        "D4",
        len(neg_ends) == 1
        and neg_ends[0].get("delivered") is False
        and neg_ends[0].get("reason") == "budget_exhausted",
        neg_ends,
    )
    cur = begin()
    check("D4", residual(cur) == 0, residual(cur))
    conn.rollback()
    check("D4", [step["claim"]["request"]["handler"] for step in neg_reads] == [
        "worker:read_pi", "worker:read_file_swift", "worker:read_file_py",
    ])

    cur = begin()
    cur.execute("UPDATE v13_policies SET active=false WHERE name='turn_budget' AND active")
    cur.execute(
        "INSERT INTO v13_policies (name, version, value, active) "
        "VALUES ('turn_budget', 2, %s::jsonb, true)",
        (json.dumps({"max_cycles": 6}),),
    )
    check("D5", q1(cur, "SELECT v13_policy('turn_budget')->>'max_cycles'") == "6")
    conn.commit()

    cur = begin()
    fail_sid = open_session(cur, "Read missing fixture")
    conn.commit()
    failed = beat(fail_sid, "fail", swap={"path": "missing.txt"}, phase="tool")
    check(
        "D15",
        failed["claim"]["request"].get("handler") == "worker:read_file_py",
        failed.get("claim"),
    )
    check("D15", failed["status"] == "failed" and failed["payload"]["error"] == "read_failed", failed)
    cur = begin()
    fail_effect = q1(
        cur,
        "SELECT status FROM effects WHERE effect_id=%s::uuid",
        (failed["claim"]["effect_id"],),
    )
    fail_type = q1(
        cur,
        "SELECT jsonb_typeof(result) FROM effects WHERE effect_id=%s::uuid",
        (failed["claim"]["effect_id"],),
    )
    fail_err = q1(
        cur,
        "SELECT result->>'error' FROM effects WHERE effect_id=%s::uuid",
        (failed["claim"]["effect_id"],),
    )
    tool_results = q1(
        cur,
        "SELECT count(*) FROM events WHERE session_id=%s AND type='tool/result'",
        (fail_sid,),
    )
    sess_status = q1(cur, "SELECT status FROM sessions WHERE session_id=%s", (fail_sid,))
    conn.rollback()
    check("D15", fail_effect == "failed" and fail_type == "object" and fail_err == "read_failed")
    check("D15", tool_results == 0, tool_results)
    check("D15", sess_status not in ("completed", "failed", "cancelled"), sess_status)
    cur = begin()
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (fail_sid, str(uuid.uuid4()), json.dumps({"text": "Now write a short note"})),
    )
    conn.commit()
    llm = beat(fail_sid, "fail", phase="llm")
    check("D15", llm["advance"] == "waiting" and llm["claim"]["kind"] == "llm", llm.get("claim"))
    fin = beat(fail_sid, "fail", expect_terminal=True, phase="finish")
    check("D15", fin["advance"] == "terminal")
    fail_status, fail_ends = end_of(fail_sid)
    check("D15", fail_status == "completed", fail_status)
    check(
        "D15",
        len(fail_ends) == 1 and fail_ends[0].get("delivered") is True,
        fail_ends,
    )
    cur = begin()
    check("D15", residual(cur) == 0)
    conn.rollback()

    cur = begin()
    duck_sid = open_session(cur, "Read fib.py")
    conn.commit()
    duck_failed = beat(duck_sid, "duck_fail", swap={"path": "hello.txt"}, phase="tool")
    check(
        "D15b",
        duck_failed["claim"]["request"].get("handler") == "worker:read_duck"
        and duck_failed["claim"]["request"].get("params") == {"path": "fib.py"},
        duck_failed.get("claim"),
    )
    check(
        "D15b",
        duck_failed["status"] == "failed"
        and duck_failed["payload"]["error"] == "language_unsupported",
        duck_failed,
    )
    cur = begin()
    duck_effect = q1(
        cur,
        "SELECT status FROM effects WHERE effect_id=%s::uuid",
        (duck_failed["claim"]["effect_id"],),
    )
    duck_type = q1(
        cur,
        "SELECT jsonb_typeof(result) FROM effects WHERE effect_id=%s::uuid",
        (duck_failed["claim"]["effect_id"],),
    )
    duck_err = q1(
        cur,
        "SELECT result->>'error' FROM effects WHERE effect_id=%s::uuid",
        (duck_failed["claim"]["effect_id"],),
    )
    duck_results = q1(
        cur,
        "SELECT count(*) FROM events WHERE session_id=%s AND type='tool/result'",
        (duck_sid,),
    )
    duck_status = q1(cur, "SELECT status FROM sessions WHERE session_id=%s", (duck_sid,))
    check("D15b", residual(cur) == 0)
    conn.rollback()
    check("D15b", duck_effect == "failed" and duck_type == "object" and duck_err == "language_unsupported")
    check("D15b", duck_results == 0, duck_results)
    check("D15b", duck_status not in ("completed", "failed", "cancelled"), duck_status)

    cur = begin()
    happy = open_session(cur, "Read hello.txt and fib.py")
    user_seq = q1(
        cur,
        "SELECT max(seq) FROM events WHERE session_id=%s AND type='user/message'",
        (happy,),
    )
    conn.commit()
    happy_steps = [beat(happy, "happy") for _ in range(5)]
    happy_end = beat(happy, "happy", expect_terminal=True)
    check("D6", happy_end["advance"] == "terminal")
    happy_routes = routes_of(happy)
    check("D6", len(happy_routes) == 6, happy_routes)
    check("D6", [r.get("action") for r in happy_routes] == ["tool", "tool", "tool", "tool", "llm", "finish"], happy_routes)
    check(
        "D6",
        [r.get("tool") for r in happy_routes[:4]] == ["read_pi", "read_file_swift", "read_file_py", "read_duck"],
        happy_routes,
    )
    for step, handler, path in zip(happy_steps[:4], (
        "worker:read_pi", "worker:read_file_swift", "worker:read_file_py", "worker:read_duck",
    ), ("hello.txt", "hello.txt", "hello.txt", "fib.py")):
        req = step["claim"]["request"]
        check("D7", req.get("handler") == handler and req.get("params") == {"path": path}, req)
    cur = begin()
    cur.execute(
        "SELECT effect_id::text, tool_name, request_hash, idempotency_key, origin_user_seq, "
        "request->>'tools_revision', request->>'handler', request->'params', status, "
        "jsonb_typeof(result), result #>> '{}' "
        "FROM effects WHERE session_id=%s AND kind='tool' ORDER BY created_at",
        (happy,),
    )
    effects = cur.fetchall()
    cur.execute(
        "SELECT seq, payload->>'tool', payload->>'result' FROM events "
        "WHERE session_id=%s AND type='tool/result' ORDER BY seq",
        (happy,),
    )
    result_events = cur.fetchall()
    cur.execute(
        "SELECT payload->>'text', (payload->>'origin_user_seq')::bigint "
        "FROM events WHERE session_id=%s AND type='llm/message'",
        (happy,),
    )
    llm_rows = cur.fetchall()
    conn.rollback()
    check("D9", len(effects) == 4 and all(row[8] == "succeeded" for row in effects), effects)
    check("D9", len({row[5] for row in effects}) == 1, [row[5] for row in effects])
    check("D9", len({row[4] for row in effects}) == 1 and effects[0][4] == user_seq, effects)
    check("D10", len({row[0] for row in effects}) == 4)
    check("D10", len({row[2] for row in effects}) == 4)
    check("D10", len({row[3] for row in effects}) == 4)
    check("D10", [row[1] for row in effects] == ["read_pi", "read_file_swift", "read_file_py", "read_duck"])
    check("D10", len(result_events) == 4 and len({row[0] for row in result_events}) == 4)
    headless = HELLO.decode("utf-8")
    by_tool = {row[1]: row[2] for row in result_events}
    check("D8", by_tool["read_file_swift"] == by_tool["read_file_py"] == headless, by_tool)
    check("D8", by_tool["read_pi"] == pi_plain(headless), by_tool["read_pi"])
    check("D8", by_tool["read_duck"] == FIB_RENDER, by_tool.get("read_duck"))
    duck_effect = next(row for row in effects if row[1] == "read_duck")
    check(
        "D9",
        duck_effect[8] == "succeeded" and duck_effect[9] == "string" and duck_effect[10] == FIB_RENDER,
        duck_effect,
    )
    check("D9", all(row[9] == "string" for row in effects), [row[9] for row in effects])
    happy_status, happy_ends = end_of(happy)
    check("D6", happy_status == "completed", happy_status)
    check("D6", len(happy_ends) == 1 and happy_ends[0].get("delivered") is True, happy_ends)
    check("D6", len(llm_rows) == 1 and llm_rows[0][0] and llm_rows[0][1] == user_seq, llm_rows)
    cur = begin()
    check("D11", residual(cur) == 0)
    conn.rollback()

    for step in happy_steps[:4]:
        replay_claim = step["claim"]
        replay_text = step["payload"]
        cur = begin()
        before_results = q1(
            cur,
            "SELECT count(*) FROM events WHERE session_id=%s AND type='tool/result'",
            (happy,),
        )
        replay = complete(cur, replay_claim, "succeeded", replay_text)
        after_results = q1(
            cur,
            "SELECT count(*) FROM events WHERE session_id=%s AND type='tool/result'",
            (happy,),
        )
        conn.rollback()
        check("D13", replay == "replay" and step["claim"]["request"].get("handler"), replay)
        check("D13", before_results == after_results == 4, (before_results, after_results, step["claim"]["request"].get("handler")))

    with tempfile.TemporaryDirectory(prefix="v13read-d16-") as raw:
        body = Path(raw) / "body.txt"
        body.write_bytes(b"true")
        cur = begin()
        literal = open_session(cur, "Read a four-letter token")
        conn.commit()
        step = beat(literal, "literal", swap={"root": raw, "path": "body.txt"}, phase="tool")
        cur = begin()
        cur.execute(
            "SELECT jsonb_typeof(result), result #>> '{}' FROM effects WHERE effect_id=%s::uuid",
            (step["claim"]["effect_id"],),
        )
        rtype, decoded = cur.fetchone()
        conn.rollback()
        check("D16", rtype == "string" and decoded == "true", (rtype, decoded, step.get("payload")))

    cur = begin()
    check("D12", q1(cur, "SELECT current_setting('typesafe.provider', true)") == "mock")
    conn.rollback()
    conn2 = psycopg2.connect(server.get_uri(DB))
    conn2.autocommit = False
    cur2 = conn2.cursor()
    try:
        cur2.execute("SELECT v13_parse(%s)", (happy,))
        check("D12", False, "parse succeeded without provider")
    except psycopg2.Error as exc:
        check("D12", exc.pgcode == "V3002", exc.pgcode)
        conn2.rollback()
    finally:
        conn2.close()
    cur = begin()
    check("D12", q1(cur, "SELECT current_setting('typesafe.provider', true)") == "mock")
    conn.rollback()

    cur = begin()
    cur.execute(
        "DELETE FROM tools WHERE name IN ('read_pi', 'read_file_swift', 'read_file_py', 'read_duck')"

    )
    end_count = q1(cur, "SELECT count(*) FROM tools")
    end_rev = q1(cur, "SELECT revision FROM v13_tools_meta WHERE singleton")
    check("E1", end_count == saved["base_count"], (end_count, saved["base_count"]))
    check("E1", end_rev > after_rev, (after_rev, end_rev))
    conn.commit()
    conn.close()

    readme = (ROOT / "README.md").read_text()
    for needle in (
        "uv run python v13/read_tools/test_read_tools.py --contract",
        "uv run python v13/read_tools/test_read_tools.py",
        "[SKIP] not_run/toolchain_absent",
        "swift",
        "node",
        "splitlines",
        "start_line=-1",
        "image_unsupported",
        "单 root",
        "零 SQL",
        "agent_v13_read_tools",
        "P1",
        "P2",
        "E4",
        "worker:read_duck",
        "max_cycles=6",
        ".duck-venv",
        "FIB_RENDER",
    ):
        check("E3", needle in readme, needle)


def run_f() -> None:
    inventory = duck_inventory()
    check(f"F1 {PIN_LABEL}", inventory["duckdb"] == EXPECTED_DUCKDB_VERSION, inventory["duckdb"])
    check(f"F1 {PIN_LABEL}", inventory["platform"] == EXPECTED_PLATFORM, inventory["platform"])
    found = {row[0]: row for row in inventory["rows"]}
    for name, pin in EXPECTED_EXTENSIONS.items():
        row = found.get(name)
        check(f"F1 {PIN_LABEL}", row is not None and row[1] == pin["version"] and row[2] is True, row)
        binary = EXTENSION_CACHE / f"{name}.duckdb_extension"
        digest = file_sha256(binary)
        check(f"F2 {PIN_LABEL}", digest == pin["sha256"], digest)
        info = (EXTENSION_CACHE / f"{name}.duckdb_extension.info").read_bytes()
        check("F2", b"http://community-extensions.duckdb.org" in info, name)
        check("F2", pin["version"].encode() in info, name)
    src = DUCK_PORT.read_text()
    for needle in (
        "SET autoinstall_known_extensions=false",
        "SET autoload_known_extensions=false",
        "LOAD sitting_duck",
        "LOAD duck_block_utils",
        "SET enable_external_access=false",
        "parse_ast(?, ?, peek := 'full')",
        "ast_to_blocks_from('ast')",
        "duck_blocks_to_text",
        "duck_blocks_validate",
    ):
        check("F2", needle in src, needle)
    check("F2", "INSTALL " not in src and "allow_unsigned_extensions" not in src)
    check("F2", "read_contract" not in src)

    body = (FIXTURES / "fib.py").read_bytes()
    check("F3", body == FIB_BYTES and body.endswith(b"\n") and body.isascii(), body)
    proc = subprocess.run(
        duck_argv(),
        input=json.dumps({"root": str(FIXTURES), "path": "fib.py"}).encode(),
        capture_output=True,
    )
    frames = [line for line in proc.stdout.split(b"\n") if line.strip()]
    check("F3", proc.returncode == 0 and len(frames) == 1, (proc.returncode, proc.stdout, proc.stderr))
    got = duck_read(str(FIXTURES), "fib.py")
    source = FIB_BYTES.decode("utf-8")
    check(
        f"F3 {PIN_LABEL}",
        got.ok and got.exit_code == 0 and got.result == FIB_RENDER and got.result != source,
        got.payload,
    )
    check("F3", got.result is not None and "print(fib(6))" not in got.result and "fib(n)" in got.result)

    by_lang = {row[0]: row[1] for row in inventory["langs"]}
    check("F4", "py" in (by_lang.get("python") or []), by_lang.get("python"))
    check("F4", "javascript" in by_lang and "js" in by_lang["javascript"], by_lang.get("javascript"))
    check("F4", "javascript" != "python")

    root = str(FIXTURES)
    for raw in ("fib.py", "../../etc/hosts", "/etc/hosts", "a\0b", "", "   ", "~/fib.py"):
        try:
            py_path = resolve_path(root, raw)
            py_code = None
        except ReadError as exc:
            py_path = None
            py_code = exc.code
        try:
            duck_path = duck_resolve(root, raw)
            duck_code = None
        except ToolError as exc:
            duck_path = None
            duck_code = exc.code
        check("F6", py_code == duck_code and py_path == duck_path, (raw, py_code, duck_code, py_path, duck_path))

    escaped = duck_read(root, "../../etc/hosts")
    check("F6", escaped.error == "path_outside_workspace" and escaped.exit_code == 3, escaped.payload)
    absolute = duck_read(root, "/etc/hosts")
    check("F6", absolute.error == "path_outside_workspace" and absolute.exit_code == 3, absolute.payload)
    nul = duck_read(root, "a\0b")
    check("F6", nul.error == "path_outside_workspace" and nul.exit_code == 3, nul.payload)
    tilde = duck_read(root, "~/fib.py")
    check("F6", (not tilde.ok) and tilde.error == "read_failed" and tilde.exit_code == 3, tilde.payload)
    missing_key = duck_read(root, "fib.py", path_key=False)
    check("F7", missing_key.error == "invalid_params" and missing_key.exit_code == 3, missing_key.payload)
    blank = duck_read(root, "   ")
    check("F7", blank.error == "invalid_params" and blank.exit_code == 3, blank.payload)
    empty = run_line_json(duck_argv(), {}, stdin=b"")
    check("F8", empty.error == "invalid_params" and empty.exit_code == 3, empty.payload)
    blank_in = run_line_json(duck_argv(), {}, stdin=b" \n\t")
    check("F8", blank_in.error == "invalid_params" and blank_in.exit_code == 3, blank_in.payload)
    try:
        run_line_json(duck_argv(), {}, stdin=b"{")
    except ProtocolError:
        check("F8", True)
    else:
        check("F8", False, "bad json")

    with tempfile.TemporaryDirectory(prefix="v13read-f-") as raw_dir:
        tmp = Path(raw_dir)
        outside = tmp / "secret.py"
        outside.write_bytes(b"def secret():\n    return 1\n")
        fenced = tmp / "root"
        fenced.mkdir()
        (fenced / "escape.py").symlink_to(outside)
        link = duck_read(str(fenced), "escape.py")
        check("F6", link.error == "path_outside_workspace" and link.exit_code == 3, link.payload)
        (fenced / "note.txt").write_bytes(b"hello\n")
        unsupported = duck_read(str(fenced), "note.txt")
        check(
            "F5",
            unsupported.error == "language_unsupported" and unsupported.exit_code == 3,
            unsupported.payload,
        )
        (fenced / "bad.py").write_bytes(b"\xff\xfe")
        bad = duck_read(str(fenced), "bad.py")
        check("F9", bad.error == "read_failed" and bad.exit_code == 3, bad.payload)
        missing = duck_read(str(fenced), "missing.py")
        check("F9", missing.error == "read_failed" and missing.exit_code == 3, missing.payload)
        (fenced / "add.js").write_bytes(JS_BYTES)
        js = duck_read(str(fenced), "add.js")
        check(
            f"F4 {PIN_LABEL}",
            js.ok and js.exit_code == 0 and js.result == JS_RENDER and "add(1, 2)" not in (js.result or ""),
            js.payload,
        )

    readme = (ROOT / "README.md").read_text()
    for needle in (
        "uv run python v13/read_tools/duck_bringup.py",
        EXPECTED_DUCKDB_VERSION,
        EXPECTED_PLATFORM,
        EXPECTED_EXTENSIONS["sitting_duck"]["version"],
        EXPECTED_EXTENSIONS["duck_block_utils"]["version"],
        EXPECTED_EXTENSIONS["sitting_duck"]["sha256"],
        EXPECTED_EXTENSIONS["duck_block_utils"]["sha256"],
        "language_unsupported",
        "ast_to_blocks_from",
        "duck_blocks_to_text",
        "D1-A",
        "enable_external_access=false",
    ):
        check("F10", needle in readme, needle)


def main(argv: list[str]) -> int:
    contract = "--contract" in argv
    if not toolchain_present() or not duck_toolchain_present():
        print("[SKIP] not_run/toolchain_absent")
        return 2
    try:
        run_a()
        run_b()
        run_c()
        if not contract:
            run_ring()
        run_f()
    except AssertionError as exc:
        print(exc)
        return 1
    except Exception as exc:
        if exc.__class__.__name__ == "OperationalError":
            print(exc)
            return 1
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
