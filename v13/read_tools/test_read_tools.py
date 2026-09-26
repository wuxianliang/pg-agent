"""M1 contract gate for native read tools.

Run: uv run python v13/read_tools/test_read_tools.py --contract  (exit 0 = pass)
Missing swift or node: prints [SKIP] not_run/toolchain_absent and exits 2.
"""

from __future__ import annotations

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
from v13.read_tools.read_contract import ReadError, read_text

SWIFT_SRC = str(ROOT / "read_file_swift.swift")
PI_SRC = str(ROOT / "read_pi.mjs")
FIXTURES = ROOT / "fixtures"
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


def main(argv: list[str]) -> int:
    if not toolchain_present():
        print("[SKIP] not_run/toolchain_absent")
        return 2
    try:
        run_a()
        run_b()
        run_c()
    except AssertionError:
        return 1
    if "--contract" in argv:
        return 0
    print("TODO: M2 groups D-E are not implemented in this milestone")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
