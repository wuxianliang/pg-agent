"""JS read port on the real pi createReadTool.

能跑的组先跑；断言失败退出 1；有跳过才退出 2。
本轮 gate：契约断言（read_tools C 组语义 + 行 JSON 帧）与本库运行时目录行。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from v13.read_tools.bridge import ProtocolError, run_line_json

PI_SRC = str(ROOT / "read_pi_ext.mjs")
PI_READ = Path("/Users/wxl/Projects/pi/packages/coding-agent/src/core/tools/read.ts")
FIXTURES = AGENT_ROOT / "v13" / "read_tools" / "fixtures"
NODE = ["node", "--experimental-strip-types", PI_SRC]
HELLO = b"line one\nline two\nline three\n"
CRLF = b"alpha\r\nbeta\r\n"
HEADLESS_CRLF = "alpha\n\nbeta\n\n"


def check(label: str, condition: bool, detail: object = "") -> None:
    if condition:
        print(f"[PASS] {label}")
        return
    print(f"[FAIL] {label}: {detail!r}")
    raise AssertionError(f"{label}: {detail!r}")


def command_ok(argv: list[str]) -> bool:
    try:
        proc = subprocess.run(argv, capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def pi_read(root: str, path: str, **fields):
    payload = {"root": root, "path": path}
    payload.update(fields)
    return run_line_json(NODE, payload, timeout=60)


def pi_lines(text: str) -> list[str]:
    return text.split("\n")


def protected_dirty(paths: list[str]) -> list[str]:
    bad = []
    for name in paths:
        if name in {"v13/load.py", "pyproject.toml", "uv.lock"} or (
            name.startswith("v13/") and name.endswith(".sql")
        ):
            bad.append(name)
        if name.startswith("v13/read_tools/"):
            bad.append(name)
    return bad


def run_guard() -> None:
    src = Path(PI_SRC).read_text()
    check("G0", "createReadTool" in src and "AgentTool.execute" in src, "framework call")
    check("G0", "function truncateHead" not in src and "truncateHead(" not in src, "no copied truncate")
    check("G0", "writeSync" in src and "process.stdout.write" not in src, "emit source")
    check("G0", "path: absolutePath" in src, "fenced path is what execute sees")
    load = (AGENT_ROOT / "v13" / "load.py").read_text()
    check("G0", "pi_ports" not in load, "load.py")
    names = []
    for argv in (
        ["git", "diff", "--name-only", "HEAD", "--", "v13", "pyproject.toml", "uv.lock"],
        ["git", "diff", "--name-only", "HEAD^", "HEAD", "--", "v13", "pyproject.toml", "uv.lock"],
        ["git", "ls-files", "--others", "--exclude-standard", "--", "v13", "pyproject.toml", "uv.lock"],
    ):
        proc = subprocess.run(argv, cwd=AGENT_ROOT, capture_output=True, text=True)
        check("G2", proc.returncode == 0, (argv, proc.stderr))
        names.extend(line for line in proc.stdout.splitlines() if line.strip())
    bad = protected_dirty(names)
    check("G2", not bad, bad)


def run_c() -> None:
    fixture_root = str(FIXTURES)
    hello = HELLO.decode("utf-8")
    lines = pi_lines(hello)
    got = pi_read(fixture_root, "hello.txt", offset=2)
    expected = "\n".join(lines[1:])
    check("C1", got.ok and got.exit_code == 0 and got.result == expected, got.payload)
    for off in (0, -4):
        reply = pi_read(fixture_root, "hello.txt", offset=off)
        check("C1b", reply.ok and reply.result == "\n".join(lines), (off, reply.payload))

    evidenced = subprocess.run(
        NODE,
        input=json.dumps({"root": fixture_root, "path": "hello.txt"}).encode(),
        capture_output=True,
        timeout=60,
    )
    err = evidenced.stderr.decode("utf-8", "replace")
    check(
        "EVID",
        evidenced.returncode == 0
        and "createReadTool=" in err
        and str(PI_READ) in err
        and "execute=AgentTool.execute" in err
        and "version=0.87.1" in err,
        err,
    )

    with tempfile.TemporaryDirectory(prefix="v13pi-") as raw:
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
        for neg in (-1, -99):
            c3e = pi_read(fixture_root, "hello.txt", limit=neg)
            check("C3e", c3e.ok and c3e.result == c3b.result, (neg, c3e.result))

        wide = "b" * (20 * 1024)
        (tmp / "wide.txt").write_bytes("\n".join([wide] * 5).encode("utf-8"))
        c3c = pi_read(str(tmp), "wide.txt", limit=5)
        c3c_expected = (
            "\n".join([wide] * 2)
            + "\n\n[Showing lines 1-2 of 5 (50.0KB limit). Use offset=3 to continue.]"
        )
        check("C3c", c3c.ok and c3c.result == c3c_expected, c3c.result)

        missing_limit = pi_read(fixture_root, "hello.txt")
        null_limit = pi_read(fixture_root, "hello.txt", limit=None)
        check("C3d", missing_limit.ok and missing_limit.result == hello, missing_limit.payload)
        check("C3d", null_limit.ok and null_limit.result == hello, null_limit.payload)

        short = "\n".join(["x"] * 2001)
        (tmp / "lines.txt").write_bytes(short.encode("utf-8"))
        c4_lines = pi_read(str(tmp), "lines.txt")
        line_notice = "\n\n[Showing lines 1-2000 of 2001. Use offset=2001 to continue.]"
        check("C4", c4_lines.ok and c4_lines.result == "\n".join(["x"] * 2000) + line_notice, c4_lines.result)

        byte_lines = ["a" * 1000] * 80
        (tmp / "bytes.txt").write_bytes("\n".join(byte_lines).encode("utf-8"))
        c4_bytes = pi_read(str(tmp), "bytes.txt")
        byte_notice = "\n\n[Showing lines 1-51 of 80 (50.0KB limit). Use offset=52 to continue.]"
        check("C4", c4_bytes.ok and c4_bytes.result == "\n".join(["a" * 1000] * 51) + byte_notice, c4_bytes.result)

        long_name = "longline.txt"
        (tmp / long_name).write_bytes(b"Q" * 51201)
        c5 = pi_read(str(tmp), long_name)
        c5_expected = (
            "[Line 1 is 50.0KB, exceeds 50.0KB limit. "
            f"Use bash: sed -n '1p' {long_name} | head -c 51200]"
        )
        check("C5", c5.ok and c5.result == c5_expected, c5.result)

        mib_name = "mib.txt"
        (tmp / mib_name).write_bytes(b"Z" * (1024 * 1024))
        c5b = pi_read(str(tmp), mib_name)
        c5b_expected = (
            "[Line 1 is 1.0MB, exceeds 50.0KB limit. "
            f"Use bash: sed -n '1p' {mib_name} | head -c 51200]"
        )
        check("C5b", c5b.ok and c5b.result == c5b_expected, c5b.result)

        outside = pi_read(fixture_root, "../hello.txt")
        check("C6", outside.error == "path_outside_workspace" and outside.exit_code == 3, outside.payload)
        absolute = pi_read(fixture_root, "/etc/hosts")
        check("C6", absolute.error == "path_outside_workspace", absolute.payload)
        tilde = pi_read(fixture_root, "~/hello.txt")
        check("C6", (not tilde.ok) and tilde.error == "read_failed", tilde.payload)
        blank_path = pi_read(fixture_root, "")
        check("C6", blank_path.error == "invalid_params" and blank_path.exit_code == 3, blank_path.payload)
        blank_root = pi_read("", "hello.txt")
        check("C6", blank_root.error == "invalid_params" and blank_root.exit_code == 3, blank_root.payload)
        spaced_root = pi_read("   ", "hello.txt")
        check("C6", spaced_root.error == "invalid_params" and spaced_root.exit_code == 3, spaced_root.payload)
        nul_path = pi_read(fixture_root, "a\0b")
        check("C6", nul_path.error == "path_outside_workspace" and nul_path.exit_code == 3, nul_path.payload)
        rel_ok = pi_read(fixture_root, "hello.txt")
        check("C6", rel_ok.ok and rel_ok.exit_code == 0 and rel_ok.result == hello, rel_ok.payload)
        dotdot = pi_read(fixture_root, "foo/../hello.txt")
        check("C6", dotdot.ok and dotdot.result == rel_ok.result, dotdot.payload)
        fenced = tmp / "c6root"
        fenced.mkdir()
        outside_link = tmp / "secret-outside.txt"
        outside_link.write_bytes(b"secret-outside\n")
        (fenced / "escape").symlink_to(outside_link)
        escaped = pi_read(str(fenced), "escape")
        check("C6", escaped.error == "path_outside_workspace" and escaped.exit_code == 3, escaped.payload)
        loop = fenced / "loop"
        loop.symlink_to("loop")
        looped = pi_read(str(fenced), "loop")
        check("C6", looped.error == "read_failed" and looped.exit_code == 3, looped.payload)
        outside_dir = tmp / "outside-dir"
        outside_dir.mkdir()
        (outside_dir / "secret.txt").write_bytes(b"SENTINEL-DIRLINK\n")
        (fenced / "inside.txt").write_bytes(b"inside-hello\n")
        (fenced / "out").symlink_to(outside_dir, target_is_directory=True)
        dir_escape = pi_read(str(fenced), "out/secret.txt")
        check(
            "C6d",
            dir_escape.error == "path_outside_workspace"
            and dir_escape.exit_code == 3
            and "SENTINEL-DIRLINK" not in json.dumps(dir_escape.payload),
            dir_escape.payload,
        )
        dir_dotdot = pi_read(str(fenced), "out/../inside.txt")
        check(
            "C6d",
            dir_dotdot.ok
            and dir_dotdot.result == "inside-hello\n"
            and "SENTINEL-DIRLINK" not in (dir_dotdot.result or ""),
            dir_dotdot.payload,
        )
        (tmp / "nul.txt").write_bytes(b"a\x00b")
        nul_body = pi_read(str(tmp), "nul.txt")
        encoded = json.dumps(nul_body.payload)
        check(
            "C10",
            nul_body.error == "read_failed"
            and nul_body.exit_code == 3
            and nul_body.message == "contains NUL"
            and "result" not in nul_body.payload
            and "\0" not in encoded,
            nul_body.payload,
        )
        (tmp / "badenc.txt").write_bytes(b"\xff\xfe")
        badenc = pi_read(str(tmp), "badenc.txt")
        check("A12", badenc.error == "read_failed" and badenc.message == "not utf-8", badenc.payload)

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

        empty = run_line_json(NODE, {}, stdin=b"", timeout=60)
        check("C8", empty.error == "invalid_params" and empty.exit_code == 3, empty.payload)
        bad = subprocess.run(NODE, input=b"{", capture_output=True, timeout=60)
        check("C8", bad.returncode == 1, bad.returncode)
        not_obj = subprocess.run(NODE, input=b"[]", capture_output=True, timeout=60)
        check("C8", not_obj.returncode == 1, not_obj.returncode)
        ok_proc = subprocess.run(
            NODE,
            input=json.dumps({"root": fixture_root, "path": "hello.txt"}).encode(),
            capture_output=True,
            timeout=60,
        )
        ok_frames = [line for line in ok_proc.stdout.split(b"\n") if line.strip()]
        check("C8", ok_proc.returncode == 0 and len(ok_frames) == 1, (ok_proc.returncode, ok_proc.stdout))
        err_proc = subprocess.run(
            NODE,
            input=json.dumps({"root": fixture_root, "path": "../hello.txt"}).encode(),
            capture_output=True,
            timeout=60,
        )
        err_frames = [line for line in err_proc.stdout.split(b"\n") if line.strip()]
        check("C8", err_proc.returncode == 3 and len(err_frames) == 1, (err_proc.returncode, err_proc.stdout))

    pi_crlf = pi_read(fixture_root, "crlf.txt")
    raw = CRLF.decode("utf-8")
    by_lf = "\n".join(raw.split("\n"))
    check("C9", pi_crlf.ok and pi_crlf.result != HEADLESS_CRLF and pi_crlf.result == by_lf, pi_crlf.result)
    crlf_lines = raw.split("\n")
    crlf_limit = pi_read(fixture_root, "crlf.txt", limit=1)
    crlf_expected = (
        f"{crlf_lines[0]}\n\n[{len(crlf_lines) - 1} more lines in file. Use offset=2 to continue.]"
    )
    check(
        "C9",
        crlf_limit.ok
        and crlf_limit.result == crlf_expected
        and crlf_limit.result.startswith("alpha\r")
        and "beta" not in crlf_limit.result.split("[", 1)[0],
        crlf_limit.result,
    )
    run_tilde()


def run_tilde() -> None:
    with tempfile.TemporaryDirectory(prefix="v13pi-tilde-") as raw:
        tmp = Path(raw)
        root = tmp / "root"
        home = tmp / "home"
        (root / "~").mkdir(parents=True)
        home.mkdir()
        (root / "~" / "sentinel").write_bytes(b"sentinel-A\n")
        (home / "sentinel").write_bytes(b"sentinel-B\n")
        proc = subprocess.run(
            NODE,
            input=json.dumps({"root": str(root), "path": "~/sentinel"}).encode(),
            capture_output=True,
            timeout=60,
            env={**os.environ, "HOME": str(home), "USERPROFILE": str(home)},
        )
        stdout = proc.stdout.decode("utf-8", "replace")
        stderr = proc.stderr.decode("utf-8", "replace")
        check("P0", proc.returncode == 0 and stdout.strip(), (proc.returncode, stdout, stderr))
        payload = json.loads(stdout.splitlines()[0])
        check(
            "P0",
            payload.get("ok") is True
            and payload.get("result") == "sentinel-A\n"
            and "sentinel-B" not in stdout
            and "sentinel-B" not in stderr,
            payload,
        )


def run_catalog() -> None:
    import psycopg2

    from server import get_server
    from v13.pi_ports.setup_db import DB, main as setup_db

    check("R0", setup_db() == 0, "setup_db")
    server = get_server()
    conn = psycopg2.connect(server.get_uri(DB))
    conn.autocommit = False
    spec = {
        "path": {
            "question": "Which fixture file should be read?",
            "stated": "Does the user name a fixture file to read?",
            "options": {"hello.txt": "LF fixture"},
        }
    }
    cur = conn.cursor()
    try:
        cur.execute("SELECT count(*) FROM tools")
        before = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO tools (name, description, kind, handler, param_spec, enabled) "
            "VALUES (%s, %s, 'tool', %s, %s::jsonb, true)",
            (
                "read_pi_ext",
                "Read a text file through the pi framework read tool.",
                "worker:read_pi_ext",
                json.dumps(spec),
            ),
        )
        cur.execute(
            "SELECT kind, handler, enabled FROM tools WHERE name=%s",
            ("read_pi_ext",),
        )
        row = cur.fetchone()
        check("R1", row == ("tool", "worker:read_pi_ext", True), row)
        cur.execute("SELECT count(*) FROM tools")
        check("R1", cur.fetchone()[0] == before + 1, before)
        cur.execute("DELETE FROM tools WHERE name=%s", ("read_pi_ext",))
        cur.execute("SELECT count(*) FROM tools WHERE name=%s", ("read_pi_ext",))
        check("R1", cur.fetchone()[0] == 0)
        cur.execute("SELECT count(*) FROM tools")
        check("R1", cur.fetchone()[0] == before, before)
        conn.commit()
    finally:
        conn.rollback()
        conn.close()


def toolchain_absent() -> list[str]:
    skipped = []
    if not command_ok(["node", "--version"]):
        skipped.append("node")
    if not PI_READ.is_file():
        skipped.append("pi_checkout")
    if not (ROOT / "node_modules" / "marked").is_dir():
        skipped.append("node_modules")
    return skipped


def main(argv: list[str]) -> int:
    del argv
    failed = False
    skipped = toolchain_absent()
    try:
        run_guard()
        if not skipped:
            run_c()
            run_catalog()
    except AssertionError as exc:
        print(exc)
        failed = True
    except ProtocolError as exc:
        print(f"[FAIL] protocol: {exc}")
        failed = True
    if failed:
        return 1
    if skipped:
        print(f"[SKIP] not_run/toolchain_absent planes={','.join(skipped)}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
