"""JS, Go, and Swift read ports on real framework tools.

能跑的组先跑；断言失败退出 1；有跳过才退出 2。
JS 组标签不变。Go 组标签带 GO- 前缀，Swift 组带 SW- 前缀，语义对齐，不改既有断言。
"""
from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys
import tempfile
import uuid
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
    check("G0", "lstatSync" in src and "not a regular file" in src, "regular-file precheck")
    check("G0", "function truncateHead" not in src and "truncateHead(" not in src, "no copied truncate")
    check("G0", "writeSync" in src and "process.stdout.write" not in src, "emit source")
    check("G0", "path: absolutePath" in src, "fenced path is what execute sees")
    pig_src = (ROOT / "pig_port" / "main.go").read_text()
    check("G0", "coding.NewSession(" in pig_src and "tool.Execute(" in pig_src, "pig framework call")
    check("G0", "internal/codingagent" not in pig_src, "no internal import")
    check("G0", "TruncateHead" not in pig_src, "no copied truncate")
    check("G0", '{"path": absolutePath}' in pig_src, "fenced path is what Execute sees")
    sw_src = (ROOT / "piswift_port" / "Sources" / "read_piswift" / "main.swift").read_text()
    check("G0", "createReadTool(" in sw_src and ".execute(" in sw_src, "swift framework call")
    check("G0", "truncateHead(" not in sw_src, "no copied truncate")
    check("G0", "FileHandle.standardOutput.write" in sw_src and "print(" not in sw_src, "swift emit")
    check("G0", "prepared.transformed ? prepared.path : absolutePath" in sw_src, "copy path is gated")
    check("G0", "path=fenced-absolute" in sw_src and "path=fenced-derived-copy" in sw_src, "evidence distinguishes copy")
    check("G0", "prepareFrameworkPath(snapshot:" in sw_src and "contentsOfFile" not in sw_src, "copy uses snapshot")
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


def run_plane(invoke, argv, tag, needles) -> None:
    fixture_root = str(FIXTURES)
    hello = HELLO.decode("utf-8")
    lines = pi_lines(hello)
    got = invoke(fixture_root, "hello.txt", offset=2)
    expected = "\n".join(lines[1:])
    check(f"{tag}C1", got.ok and got.exit_code == 0 and got.result == expected, got.payload)
    for off in (0, -4):
        reply = invoke(fixture_root, "hello.txt", offset=off)
        check(f"{tag}C1b", reply.ok and reply.result == "\n".join(lines), (off, reply.payload))

    evidenced = subprocess.run(
        argv,
        input=json.dumps({"root": fixture_root, "path": "hello.txt"}).encode(),
        capture_output=True,
        timeout=60,
    )
    err = evidenced.stderr.decode("utf-8", "replace")
    check(f"{tag}EVID",
        evidenced.returncode == 0 and all(needle in err for needle in needles),
        err,
    )

    with tempfile.TemporaryDirectory(prefix="v13pi-") as raw:
        tmp = Path(raw)
        (tmp / "a.txt").write_bytes(b"a\n")
        ok_tail = invoke(str(tmp), "a.txt", offset=2)
        check(f"{tag}C2", ok_tail.ok and ok_tail.result == "", ok_tail.payload)
        past = invoke(str(tmp), "a.txt", offset=3)
        check(f"{tag}C2",
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
        c3 = invoke(fixture_root, "hello.txt", limit=limit)
        c3_expected = (
            f"{selected}\n\n[{remaining} more lines in file. Use offset={next_offset} to continue.]"
        )
        check(f"{tag}C3", c3.ok and c3.result == c3_expected, c3.result)
        check(f"{tag}C3", c3.result is not None and "Showing lines" not in c3.result and "50.0KB" not in c3.result)

        c3b = invoke(fixture_root, "hello.txt", limit=0)
        c3b_expected = f"\n\n[{len(lines)} more lines in file. Use offset=1 to continue.]"
        check(f"{tag}C3b", c3b.ok and c3b.result == c3b_expected, c3b.result)
        for neg in (-1, -99):
            c3e = invoke(fixture_root, "hello.txt", limit=neg)
            check(f"{tag}C3e", c3e.ok and c3e.result == c3b.result, (neg, c3e.result))

        wide = "b" * (20 * 1024)
        (tmp / "wide.txt").write_bytes("\n".join([wide] * 5).encode("utf-8"))
        c3c = invoke(str(tmp), "wide.txt", limit=5)
        c3c_expected = (
            "\n".join([wide] * 2)
            + "\n\n[Showing lines 1-2 of 5 (50.0KB limit). Use offset=3 to continue.]"
        )
        check(f"{tag}C3c", c3c.ok and c3c.result == c3c_expected, c3c.result)

        missing_limit = invoke(fixture_root, "hello.txt")
        null_limit = invoke(fixture_root, "hello.txt", limit=None)
        check(f"{tag}C3d", missing_limit.ok and missing_limit.result == hello, missing_limit.payload)
        check(f"{tag}C3d", null_limit.ok and null_limit.result == hello, null_limit.payload)

        short = "\n".join(["x"] * 2001)
        (tmp / "lines.txt").write_bytes(short.encode("utf-8"))
        c4_lines = invoke(str(tmp), "lines.txt")
        line_notice = "\n\n[Showing lines 1-2000 of 2001. Use offset=2001 to continue.]"
        check(f"{tag}C4", c4_lines.ok and c4_lines.result == "\n".join(["x"] * 2000) + line_notice, c4_lines.result)

        byte_lines = ["a" * 1000] * 80
        (tmp / "bytes.txt").write_bytes("\n".join(byte_lines).encode("utf-8"))
        c4_bytes = invoke(str(tmp), "bytes.txt")
        byte_notice = "\n\n[Showing lines 1-51 of 80 (50.0KB limit). Use offset=52 to continue.]"
        check(f"{tag}C4", c4_bytes.ok and c4_bytes.result == "\n".join(["a" * 1000] * 51) + byte_notice, c4_bytes.result)

        long_name = "longline.txt"
        (tmp / long_name).write_bytes(b"Q" * 51201)
        c5 = invoke(str(tmp), long_name)
        c5_expected = (
            "[Line 1 is 50.0KB, exceeds 50.0KB limit. "
            f"Use bash: sed -n '1p' {long_name} | head -c 51200]"
        )
        check(f"{tag}C5", c5.ok and c5.result == c5_expected, c5.result)

        mib_name = "mib.txt"
        (tmp / mib_name).write_bytes(b"Z" * (1024 * 1024))
        c5b = invoke(str(tmp), mib_name)
        c5b_expected = (
            "[Line 1 is 1.0MB, exceeds 50.0KB limit. "
            f"Use bash: sed -n '1p' {mib_name} | head -c 51200]"
        )
        check(f"{tag}C5b", c5b.ok and c5b.result == c5b_expected, c5b.result)

        outside = invoke(fixture_root, "../hello.txt")
        check(f"{tag}C6", outside.error == "path_outside_workspace" and outside.exit_code == 3, outside.payload)
        absolute = invoke(fixture_root, "/etc/hosts")
        check(f"{tag}C6", absolute.error == "path_outside_workspace", absolute.payload)
        tilde = invoke(fixture_root, "~/hello.txt")
        check(f"{tag}C6", (not tilde.ok) and tilde.error == "read_failed", tilde.payload)
        blank_path = invoke(fixture_root, "")
        check(f"{tag}C6", blank_path.error == "invalid_params" and blank_path.exit_code == 3, blank_path.payload)
        blank_root = invoke("", "hello.txt")
        check(f"{tag}C6", blank_root.error == "invalid_params" and blank_root.exit_code == 3, blank_root.payload)
        spaced_root = invoke("   ", "hello.txt")
        check(f"{tag}C6", spaced_root.error == "invalid_params" and spaced_root.exit_code == 3, spaced_root.payload)
        nul_path = invoke(fixture_root, "a\0b")
        check(f"{tag}C6", nul_path.error == "path_outside_workspace" and nul_path.exit_code == 3, nul_path.payload)
        rel_ok = invoke(fixture_root, "hello.txt")
        check(f"{tag}C6", rel_ok.ok and rel_ok.exit_code == 0 and rel_ok.result == hello, rel_ok.payload)
        dotdot = invoke(fixture_root, "foo/../hello.txt")
        check(f"{tag}C6", dotdot.ok and dotdot.result == rel_ok.result, dotdot.payload)
        fenced = tmp / "c6root"
        fenced.mkdir()
        outside_link = tmp / "secret-outside.txt"
        outside_link.write_bytes(b"secret-outside\n")
        (fenced / "escape").symlink_to(outside_link)
        escaped = invoke(str(fenced), "escape")
        check(f"{tag}C6", escaped.error == "path_outside_workspace" and escaped.exit_code == 3, escaped.payload)
        loop = fenced / "loop"
        loop.symlink_to("loop")
        looped = invoke(str(fenced), "loop")
        check(f"{tag}C6", looped.error == "read_failed" and looped.exit_code == 3, looped.payload)
        outside_dir = tmp / "outside-dir"
        outside_dir.mkdir()
        (outside_dir / "secret.txt").write_bytes(b"SENTINEL-DIRLINK\n")
        (fenced / "inside.txt").write_bytes(b"inside-hello\n")
        (fenced / "out").symlink_to(outside_dir, target_is_directory=True)
        dir_escape = invoke(str(fenced), "out/secret.txt")
        check(f"{tag}C6d",
            dir_escape.error == "path_outside_workspace"
            and dir_escape.exit_code == 3
            and "SENTINEL-DIRLINK" not in json.dumps(dir_escape.payload),
            dir_escape.payload,
        )
        dir_dotdot = invoke(str(fenced), "out/../inside.txt")
        check(f"{tag}C6d",
            dir_dotdot.ok
            and dir_dotdot.result == "inside-hello\n"
            and "SENTINEL-DIRLINK" not in (dir_dotdot.result or ""),
            dir_dotdot.payload,
        )
        (tmp / "nul.txt").write_bytes(b"a\x00b")
        nul_body = invoke(str(tmp), "nul.txt")
        encoded = json.dumps(nul_body.payload)
        check(f"{tag}C10",
            nul_body.error == "read_failed"
            and nul_body.exit_code == 3
            and nul_body.message == "contains NUL"
            and "result" not in nul_body.payload
            and "\0" not in encoded,
            nul_body.payload,
        )
        (tmp / "badenc.txt").write_bytes(b"\xff\xfe")
        badenc = invoke(str(tmp), "badenc.txt")
        check(f"{tag}A12", badenc.error == "read_failed" and badenc.message == "not utf-8", badenc.payload)

        marker = b"UNIQUE_IMAGE_BYTES_ZZZ"
        for name in ("x.png", "x.jpg", "x.jpeg", "x.gif", "x.webp", "x.bmp", "x.PNG"):
            (tmp / name).write_bytes(marker)
            reply = invoke(str(tmp), name)
            encoded = json.dumps(reply.payload)
            check(f"{tag}C7",
                reply.error == "image_unsupported"
                and reply.exit_code == 3
                and "result" not in reply.payload
                and "UNIQUE_IMAGE_BYTES_ZZZ" not in encoded,
                (name, reply.payload),
            )
        outside_png = invoke(str(tmp), "/etc/outside.png")
        check(f"{tag}C7", outside_png.error == "path_outside_workspace", outside_png.payload)

        empty = run_line_json(argv, {}, stdin=b"", timeout=60)
        check(f"{tag}C8", empty.error == "invalid_params" and empty.exit_code == 3, empty.payload)
        bad = subprocess.run(argv, input=b"{", capture_output=True, timeout=60)
        check(f"{tag}C8", bad.returncode == 1, bad.returncode)
        not_obj = subprocess.run(argv, input=b"[]", capture_output=True, timeout=60)
        check(f"{tag}C8", not_obj.returncode == 1, not_obj.returncode)
        ok_proc = subprocess.run(
            argv,
            input=json.dumps({"root": fixture_root, "path": "hello.txt"}).encode(),
            capture_output=True,
            timeout=60,
        )
        ok_frames = [line for line in ok_proc.stdout.split(b"\n") if line.strip()]
        check(f"{tag}C8", ok_proc.returncode == 0 and len(ok_frames) == 1, (ok_proc.returncode, ok_proc.stdout))
        err_proc = subprocess.run(
            argv,
            input=json.dumps({"root": fixture_root, "path": "../hello.txt"}).encode(),
            capture_output=True,
            timeout=60,
        )
        err_frames = [line for line in err_proc.stdout.split(b"\n") if line.strip()]
        check(f"{tag}C8", err_proc.returncode == 3 and len(err_frames) == 1, (err_proc.returncode, err_proc.stdout))

    pi_crlf = invoke(fixture_root, "crlf.txt")
    raw = CRLF.decode("utf-8")
    by_lf = "\n".join(raw.split("\n"))
    check(f"{tag}C9", pi_crlf.ok and pi_crlf.result != HEADLESS_CRLF and pi_crlf.result == by_lf, pi_crlf.result)
    crlf_lines = raw.split("\n")
    crlf_limit = invoke(fixture_root, "crlf.txt", limit=1)
    crlf_expected = (
        f"{crlf_lines[0]}\n\n[{len(crlf_lines) - 1} more lines in file. Use offset=2 to continue.]"
    )
    check(f"{tag}C9",
        crlf_limit.ok
        and crlf_limit.result == crlf_expected
        and crlf_limit.result.startswith("alpha\r")
        and "beta" not in crlf_limit.result.split("[", 1)[0],
        crlf_limit.result,
    )
    run_tilde(argv, tag)


def run_tilde(argv, tag) -> None:
    with tempfile.TemporaryDirectory(prefix="v13pi-tilde-") as raw:
        tmp = Path(raw)
        root = tmp / "root"
        home = tmp / "home"
        (root / "~").mkdir(parents=True)
        home.mkdir()
        (root / "~" / "sentinel").write_bytes(b"sentinel-A\n")
        (home / "sentinel").write_bytes(b"sentinel-B\n")
        proc = subprocess.run(
            argv,
            input=json.dumps({"root": str(root), "path": "~/sentinel"}).encode(),
            capture_output=True,
            timeout=60,
            env={**os.environ, "HOME": str(home), "USERPROFILE": str(home)},
        )
        stdout = proc.stdout.decode("utf-8", "replace")
        stderr = proc.stderr.decode("utf-8", "replace")
        check(f"{tag}P0", proc.returncode == 0 and stdout.strip(), (proc.returncode, stdout, stderr))
        payload = json.loads(stdout.splitlines()[0])
        check(f"{tag}P0",
            payload.get("ok") is True
            and payload.get("result") == "sentinel-A\n"
            and "sentinel-B" not in stdout
            and "sentinel-B" not in stderr,
            payload,
        )



JS_EVIDENCE = [
    "createReadTool=",
    str(PI_READ),
    "execute=AgentTool.execute",
    "version=0.87.1",
]
GO_EVIDENCE = [
    "module=github.com/MichaelKinsy/PiG",
    "version=0.2.0+0.87.1",
    "go_list=v0.2.0",
    "function=coding.NewSession",
    "tool=read",
    "execute=agent.AgentTool.Execute",
    "path=fenced-absolute",
]
PIG_ROOT = Path("/Users/wxl/Projects/PiG")
SW_EVIDENCE = [
    "module=PiSwift",
    "version=0.87.1",
    "function=createReadTool",
    "tool=read",
    "execute=AgentTool.execute",
    "path=fenced-absolute",
]
PISWIFT_ROOT = Path("/Users/wxl/Projects/PiSwift")


def run_js_extra() -> None:
    hello = HELLO.decode("utf-8")
    full = pi_read(str(FIXTURES), "hello.txt")
    check("JS-TAKE", full.ok and full.result == hello, full.payload)
    for dropped in (1.5, "10"):
        reply = pi_read(str(FIXTURES), "hello.txt", offset=dropped)
        check("JS-TAKE", reply.ok and reply.exit_code == 0 and reply.result == hello, (dropped, reply.payload))

    def once(root, path, timeout=30):
        proc = subprocess.run(
            NODE,
            input=json.dumps({"root": root, "path": path}).encode(),
            capture_output=True,
            timeout=timeout,
        )
        line = proc.stdout.split(b"\n", 1)[0]
        payload = json.loads(line.decode()) if line.strip() else {}
        return proc.returncode, payload

    with tempfile.TemporaryDirectory(prefix="v13js-fence-") as raw:
        parent = Path(raw)
        fifo = parent / "pipe"
        os.mkfifo(fifo)
        code, payload = once(str(parent), "pipe", timeout=5)
        check(
            "JS-F2",
            code == 3
            and payload.get("error") == "read_failed"
            and payload.get("message") == "not a regular file"
            and "result" not in payload,
            payload,
        )
        if Path("/dev/zero").exists():
            code, payload = once("/dev", "zero", timeout=5)
            check(
                "JS-F2",
                code == 3
                and payload.get("error") == "read_failed"
                and payload.get("message") == "not a regular file"
                and "result" not in payload,
                payload,
            )
        quoted = "Offset 3 is beyond end of file (1 lines total)\n"
        (parent / "quoted.txt").write_bytes(quoted.encode())
        code, payload = once(str(parent), "quoted.txt")
        check("JS-BODY", code == 0 and payload.get("result") == quoted, payload)


def run_c() -> None:
    run_plane(pi_read, NODE, "", JS_EVIDENCE)
    run_js_extra()


def pig_read(argv, root: str, path: str, **fields):
    payload = {"root": root, "path": path}
    payload.update(fields)
    return run_line_json(argv, payload, timeout=90)


def run_go(argv) -> None:
    run_plane(lambda root, path, **fields: pig_read(argv, root, path, **fields), argv, "GO-", GO_EVIDENCE)
    run_go_fence(argv)


def run_go_fence(argv) -> None:
    def once(cwd, root, path, timeout=30):
        proc = subprocess.run(
            argv,
            input=json.dumps({"root": root, "path": path}).encode(),
            capture_output=True,
            timeout=timeout,
            cwd=cwd,
        )
        line = proc.stdout.split(b"\n", 1)[0]
        payload = json.loads(line.decode()) if line.strip() else {}
        return proc.returncode, payload

    with tempfile.TemporaryDirectory(prefix="v13pig-fence-") as raw:
        parent = Path(raw)
        fixtures = parent / "fixtures"
        fixtures.mkdir()
        (fixtures / "inside.txt").write_bytes(b"inside-ok\n")
        (parent / "secret.txt").write_bytes(b"secret-no\n")
        abs_inside = str((fixtures / "inside.txt").resolve())
        abs_secret = str((parent / "secret.txt").resolve())

        code, payload = once(str(fixtures), ".", "inside.txt")
        check("GO-F1", code == 0 and payload.get("result") == "inside-ok\n", payload)
        code, payload = once(str(fixtures), ".", abs_inside)
        check("GO-F1", code == 0 and payload.get("result") == "inside-ok\n", payload)
        code, payload = once(str(parent), "fixtures", "inside.txt")
        check("GO-F1", code == 0 and payload.get("result") == "inside-ok\n", payload)
        code, payload = once(str(parent), "fixtures", abs_inside)
        check(
            "GO-F1",
            code == 0 and payload.get("result") == "inside-ok\n" and "secret-no" not in json.dumps(payload),
            payload,
        )
        code, payload = once(None, "/", abs_inside)
        check("GO-F1", code == 0 and payload.get("result") == "inside-ok\n", payload)
        code, payload = once(str(parent), "fixtures", abs_secret)
        check("GO-F1", code == 3 and payload.get("error") == "path_outside_workspace", payload)

        fifo = parent / "pipe"
        os.mkfifo(fifo)
        code, payload = once(None, "/", str(fifo), timeout=5)
        check(
            "GO-F2",
            code == 3 and payload.get("error") == "read_failed" and "result" not in payload,
            payload,
        )
        if Path("/dev/zero").exists():
            code, payload = once(None, "/", "/dev/zero", timeout=5)
            check(
                "GO-F2",
                code == 3 and payload.get("error") == "read_failed" and "result" not in payload,
                payload,
            )

    bad_off = pig_read(argv, str(FIXTURES), "hello.txt", offset="10")
    check("GO-P2", bad_off.error == "invalid_params" and bad_off.exit_code == 3, bad_off.payload)
    bad_lim = pig_read(argv, str(FIXTURES), "hello.txt", limit=1.5)
    check("GO-P2", bad_lim.error == "invalid_params" and bad_lim.exit_code == 3, bad_lim.payload)
    huge = pig_read(argv, str(FIXTURES), "hello.txt", offset=1e20)
    check("GO-P2", huge.error == "invalid_params" and huge.exit_code == 3, huge.payload)
    with tempfile.TemporaryDirectory(prefix="v13pig-body-") as raw:
        quoted = "Offset 3 is beyond end of file (1 lines total)\n"
        (Path(raw) / "quoted.txt").write_bytes(quoted.encode())
        got = pig_read(argv, raw, "quoted.txt")
        check("GO-BODY", got.ok and got.exit_code == 0 and got.result == quoted, got.payload)


class ToolchainMissing(Exception):
    def __init__(self, planes: list[str], detail: str = "") -> None:
        super().__init__(detail)
        self.planes = planes


def build_pig() -> list[str]:
    out = ROOT / "pig_port" / "read_pig"
    env = os.environ.copy()
    env["GOWORK"] = "off"
    env["GOTOOLCHAIN"] = "auto"
    proc = subprocess.run(
        ["go", "build", "-o", str(out), "."],
        cwd=ROOT / "pig_port",
        capture_output=True,
        text=True,
        timeout=300,
        env=env,
    )
    if proc.returncode != 0:
        err = (proc.stderr or "") + (proc.stdout or "")
        lowered = err.lower()
        if "download go" in lowered or "toolchain not available" in lowered:
            raise ToolchainMissing(["go_toolchain"], err)
        raise AssertionError(f"go build: {err[-2000:]}")
    return [str(out)]


def run_catalog_row(tag: str, name: str, description: str) -> None:
    import psycopg2

    from server import get_server
    from v13.pi_ports.setup_db import DB, main as setup_db

    check(f"{tag}R0", setup_db() == 0, "setup_db")
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
    handler = f"worker:{name}"
    cur = conn.cursor()
    try:
        cur.execute("SELECT count(*) FROM tools")
        before = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO tools (name, description, kind, handler, param_spec, enabled) "
            "VALUES (%s, %s, 'tool', %s, %s::jsonb, true)",
            (name, description, handler, json.dumps(spec)),
        )
        cur.execute(
            "SELECT kind, handler, enabled FROM tools WHERE name=%s",
            (name,),
        )
        row = cur.fetchone()
        check(f"{tag}R1", row == ("tool", handler, True), row)
        cur.execute("SELECT count(*) FROM tools")
        check(f"{tag}R1", cur.fetchone()[0] == before + 1, before)
        cur.execute("DELETE FROM tools WHERE name=%s", (name,))
        cur.execute("SELECT count(*) FROM tools WHERE name=%s", (name,))
        check(f"{tag}R1", cur.fetchone()[0] == 0)
        cur.execute("SELECT count(*) FROM tools")
        check(f"{tag}R1", cur.fetchone()[0] == before, before)
        conn.commit()
    finally:
        conn.rollback()
        conn.close()


def run_catalog() -> None:
    run_catalog_row("", "read_pi_ext", "Read a text file through the pi framework read tool.")


def run_catalog_pig() -> None:
    run_catalog_row("GO-", "read_pig", "Read a text file through the PiG framework read tool.")


def run_catalog_piswift() -> None:
    run_catalog_row("SW-", "read_piswift", "Read a text file through the PiSwift framework read tool.")


WORKERS: dict[str, tuple[list[str], int]] = {}
BASELINE_TOOLS = (
    "session_stats",
    "send_summary_email",
    "harness_turn",
    "spawn_subsession",
    "worktree_prepare",
    "worktree_merge",
    "worktree_release",
)
LLM_RESULT = {
    "text": "pi ports recorded",
    "model": "fake",
    "usage": {"input_tokens": 1, "output_tokens": 1},
}
RING_SPEC = {
    "path": {
        "question": "Which fixture file should be read?",
        "stated": "Does the user name a fixture file to read?",
        "options": {"hello.txt": "LF fixture"},
    }
}


class PortError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


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


def jsonb_safe_result(status: str, payload):
    if status == "succeeded" and isinstance(payload, str) and "\0" in payload:
        return "failed", {"error": "read_failed", "message": "contains NUL"}
    if isinstance(payload, dict):
        cleaned = {}
        changed = False
        for key, value in payload.items():
            if isinstance(value, str) and "\0" in value:
                cleaned[key] = "contains NUL"
                changed = True
            else:
                cleaned[key] = value
        if changed:
            return status, cleaned
    return status, payload


def dispatch_handler(handler: str, params: dict, root: str) -> str:
    spec = WORKERS.get(handler)
    if spec is None:
        raise PortError("protocol_error", f"unknown handler {handler}")
    if "path" not in params:
        raise PortError("invalid_params", "path missing")
    argv, timeout = spec
    reply = run_line_json(argv, {"root": root, "path": params["path"]}, timeout=timeout)
    if not reply.ok:
        raise PortError(reply.error or "read_failed", reply.message or "")
    return reply.result or ""


def run_ring(planes: list[tuple[str, str, str, list[str], int]]) -> None:
    import psycopg2

    from server import get_server
    from v13.pi_ports.setup_db import DB, main as setup_db

    n = len(planes)
    names = [plane[1] for plane in planes]
    WORKERS.clear()
    for _tag, name, _desc, argv, timeout in planes:
        WORKERS[f"worker:{name}"] = (list(argv), timeout)
    fixture_root = os.path.realpath(FIXTURES)
    direct: dict[str, str] = {}
    for tag, name, _desc, argv, timeout in planes:
        reply = run_line_json(argv, {"root": fixture_root, "path": "hello.txt"}, timeout=timeout)
        check(
            f"{tag}Hdirect",
            reply.ok and reply.exit_code == 0 and isinstance(reply.result, str),
            reply.payload,
        )
        direct[name] = reply.result or ""
        print(f"[ring] {name} direct_len={len(direct[name])}")

    ticks = {"n": 0}

    def q1(cur, sql, params=None):
        cur.execute(sql, params)
        return cur.fetchone()[0]

    def begin():
        if conn.get_transaction_status() != psycopg2.extensions.TRANSACTION_STATUS_IDLE:
            conn.rollback()
        return conn.cursor()

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
                answers[signal] = choice_answer(keys[0])
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

    def overrides_for(cur, sid) -> dict:
        base = {
            "gate_action": {"type": "noul", "noul": 0.9},
            "gate_off_topic": {"type": "noul", "noul": 0.1},
            "risk": {"type": "score", "score": 0, "confidence": 0.9},
        }
        n_tools = event_count(cur, sid, "tool/result")
        has_llm = event_count(cur, sid, "llm/message") > 0
        if has_llm or n_tools >= n:
            base["intent"] = choice_answer("llm_generate")
            base["tool"] = choice_answer("none")
            return base
        tool = names[n_tools]
        base["intent"] = choice_answer("tool_action")
        base["tool"] = choice_answer(tool)
        base[f"stated::{tool}::path"] = {"type": "noul", "noul": 0.9}
        base[f"param::{tool}::path"] = choice_answer("hello.txt")
        return base

    def parse_fresh(sid):
        pc = psycopg2.connect(server.get_uri(DB))
        pc.autocommit = False
        pcur = pc.cursor()
        pcur.execute("SELECT set_config('typesafe.provider', 'mock', false)")
        pcur.fetchone()
        pcur.execute("SELECT set_config('typesafe.model', 'fake-judge', false)")
        pcur.fetchone()
        mock = mock_from_needed(pcur, sid, **overrides_for(pcur, sid))
        pcur.execute("SELECT set_config('typesafe.mock_response', %s, true)", (mock,))
        pcur.fetchone()
        try:
            snap = as_obj(q1(pcur, "SELECT v13_parse(%s)", (sid,)))
        except psycopg2.Error as exc:
            pc.rollback()
            pc.close()
            raise AssertionError(
                f"parse: {exc.pgcode} {exc.diag.message_primary if exc.diag else exc}"
            ) from exc
        pc.commit()
        pc.close()
        return snap

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

    def beat(sid, expect_terminal=False):
        ticks["n"] += 1
        check("ticks", ticks["n"] <= 24, ticks["n"])
        snap = parse_fresh(sid)
        check("Hparse", int(snap["remaining"]) == 0, snap.get("remaining"))
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
                f"advance: {exc.pgcode} {exc.diag.message_primary if exc.diag else exc}"
            ) from exc
        conn.commit()
        if status == "terminal":
            check("Hadvance", expect_terminal, status)
            return {"advance": status}
        check("Hadvance", status == "waiting", status)
        cur = begin()
        cur.execute(
            "SELECT effect_id::text, session_id::text FROM effects WHERE status='ready'"
        )
        ready = cur.fetchall()
        check("Hclaim", len(ready) == 1 and ready[0][1] == sid, ready)
        claim = as_obj(q1(cur, "SELECT v13_claim(%s, %s)", ("pi-ports-hub", 120000)))
        check("Hclaim", claim and str(claim["effect_id"]) == ready[0][0], claim)
        conn.commit()
        req = claim.get("request") or {}
        print(f"[beat] {claim['kind']} {req.get('handler') or req.get('reason')}")
        completed = False
        flag = None
        try:
            kind = claim["kind"]
            request = claim["request"]
            if kind == "human":
                payload, st, flag = {"reason": request.get("reason")}, "succeeded", "human"
            elif kind == "llm":
                payload, st, flag = LLM_RESULT, "succeeded", None
            elif kind == "judge":
                payload = {"error": "protocol_error", "message": "judge effect"}
                st, flag = "failed", "unknown"
            elif kind != "tool":
                payload = {"error": "protocol_error", "message": f"unknown kind {kind}"}
                st, flag = "failed", "unknown"
            else:
                handler = request.get("handler")
                params = dict(request.get("params") or {})
                try:
                    payload = dispatch_handler(handler, params, fixture_root)
                    st, flag = "succeeded", None
                except PortError as exc:
                    payload = {"error": exc.code, "message": exc.message}
                    st, flag = "failed", "port"
            st, payload = jsonb_safe_result(st, payload)
            cur = begin()
            cur.execute("SET LOCAL lock_timeout='250ms'")
            cur.execute("SET LOCAL statement_timeout='5s'")
            got = complete(cur, claim, st, payload)
            check("H8", got == "accepted", got)
            conn.commit()
            completed = True
            if flag == "unknown":
                raise AssertionError(f"unknown handler settled: {claim}")
            if flag in ("port", "human"):
                raise AssertionError(f"ring beat {flag}: {payload}")
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
        rows = [as_obj(row[0]) for row in cur.fetchall()]
        conn.rollback()
        return rows

    def end_of(sid):
        cur = begin()
        cur.execute(
            "SELECT payload FROM events WHERE session_id=%s AND type='turn/end' ORDER BY seq",
            (sid,),
        )
        rows = [as_obj(row[0]) for row in cur.fetchall()]
        status = q1(cur, "SELECT status FROM sessions WHERE session_id=%s", (sid,))
        conn.rollback()
        return status, rows

    check("H7", "FROM tools" not in inspect.getsource(dispatch_handler))
    beat_src = inspect.getsource(beat)
    accepted_at = beat_src.index('got == "accepted"')
    commit_at = beat_src.index("conn.commit()", accepted_at)
    completed_at = beat_src.index("completed = True")
    check("H8", accepted_at < commit_at < completed_at, (accepted_at, commit_at, completed_at))

    check("H0", setup_db() == 0, "setup_db")
    server = get_server()
    conn = psycopg2.connect(server.get_uri(DB))
    conn.autocommit = False
    try:
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
        cur.execute(
            "INSERT INTO v13_route_policies (policy_name, policy_version) VALUES ('default', 2)"
        )
        cur.execute(
            "INSERT INTO thresholds (policy_name, policy_version, signal, band_no, lo, hi, action) "
            "SELECT 'default', 2, signal, band_no, lo, hi, action "
            "FROM thresholds WHERE policy_name='default' AND policy_version=1"
        )
        bands = []
        for name in names:
            bands.append(f"param::{name}::path")
            bands.append(f"stated::{name}::path")
        for signal in bands:
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
            (bands,),
        )
        found_bands = {row[0] for row in cur.fetchall()}
        state = q1(
            cur,
            "SELECT state FROM v13_route_policies WHERE policy_name='default' AND policy_version=2",
        )
        check("Hcat", v2_bands == v1_bands + 2 * n, (v1_bands, v2_bands, n))
        check("Hcat", found_bands == set(bands), found_bands)
        check("Hcat", state == "frozen", state)
        conn.commit()

        cur = begin()
        base_count = q1(cur, "SELECT count(*) FROM tools")
        cur.execute("SELECT name FROM tools ORDER BY name")
        base_names = tuple(row[0] for row in cur.fetchall())
        base_rev = q1(cur, "SELECT revision FROM v13_tools_meta WHERE singleton")
        measure = str(q1(cur, "SELECT v13_open_session('{}'::jsonb)"))
        needed_before = q1(cur, "SELECT count(*) FROM v13_needed_judgments(%s)", (measure,))
        batch = int(q1(cur, "SELECT v13_policy('resolve_fast_path')->>'batch_questions'"))
        check("Hcat", base_count == 7 and set(base_names) == set(BASELINE_TOOLS), base_names)
        for index, (tag, name, description, _argv, _timeout) in enumerate(planes, start=1):
            handler = f"worker:{name}"
            cur.execute(
                "INSERT INTO tools (name, description, kind, handler, param_spec, enabled) "
                "VALUES (%s, %s, 'tool', %s, %s::jsonb, true)",
                (name, description, handler, json.dumps(RING_SPEC)),
            )
            cur.execute(
                "SELECT kind, handler, enabled, param_spec FROM tools WHERE name=%s",
                (name,),
            )
            kind, got_handler, enabled, spec = cur.fetchone()
            spec = as_obj(spec)
            check(f"{tag}Hcat", (kind, got_handler, enabled) == ("tool", handler, True), (kind, got_handler, enabled))
            check(f"{tag}Hcat", spec["path"]["options"] == {"hello.txt": "LF fixture"}, spec)
            check(f"{tag}Hcat", description.isascii(), description)
            check(f"{tag}Hcat", q1(cur, "SELECT count(*) FROM tools") == base_count + index, index)
        after_rev = q1(cur, "SELECT revision FROM v13_tools_meta WHERE singleton")
        needed_after = q1(cur, "SELECT count(*) FROM v13_needed_judgments(%s)", (measure,))
        check("Hcat", after_rev == base_rev + n, (base_rev, after_rev, n))
        check("Hcat", needed_after == needed_before + 2 * n, (needed_before, needed_after))
        check("Hcat", needed_after <= batch, (needed_after, batch))
        conn.commit()

        cycles = n + 2
        cur = begin()
        if cycles != 3:
            cur.execute("UPDATE v13_policies SET active=false WHERE name='turn_budget' AND active")
            cur.execute(
                "INSERT INTO v13_policies (name, version, value, active) "
                "VALUES ('turn_budget', 2, %s::jsonb, true)",
                (json.dumps({"max_cycles": cycles}),),
            )
        check("Hbudget", q1(cur, "SELECT v13_policy('turn_budget')->>'max_cycles'") == str(cycles), cycles)
        conn.commit()

        cur = begin()
        sid = str(q1(
            cur,
            "SELECT v13_open_session(%s::jsonb)",
            (json.dumps({"route_policy_name": "default", "version": 2}),),
        ))
        cur.execute(
            "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
            (sid, str(uuid.uuid4()), json.dumps({"text": "Read hello.txt via pi ports"})),
        )
        override_seq = q1(
            cur,
            "SELECT v13_submit_override(%s, %s::jsonb)",
            (sid, json.dumps({
                "schema_version": 1,
                "intent": "direct",
                "source_principal": "user",
                "reason": "pi-ports gate",
            })),
        )
        stored_override = as_obj(q1(
            cur,
            "SELECT payload FROM events WHERE session_id=%s AND type='goal/override' AND seq=%s",
            (sid, override_seq),
        ))
        override_count = q1(
            cur,
            "SELECT count(*) FROM events WHERE session_id=%s AND type='goal/override'",
            (sid,),
        )
        check(
            "Hoverride",
            override_seq > 0
            and override_count == 1
            and stored_override["intent"] == "direct"
            and stored_override["source_principal"] == "user"
            and stored_override["reason"] == "pi-ports gate"
            and stored_override["schema_version"] == 1,
            (override_seq, override_count, stored_override),
        )
        pointed = q1(cur, "SELECT route_policy_version FROM sessions WHERE session_id=%s", (sid,))
        user_seq = q1(
            cur,
            "SELECT max(seq) FROM events WHERE session_id=%s AND type='user/message'",
            (sid,),
        )
        check("Hsession", pointed == 2, pointed)
        conn.commit()

        steps = [beat(sid) for _ in range(n + 1)]
        end = beat(sid, expect_terminal=True)
        check("H1", [row.get("action") for row in routes_of(sid)] == ["tool"] * n + ["llm", "finish"], routes_of(sid))
        check("H1", [row.get("tool") for row in routes_of(sid)[:n]] == names, routes_of(sid))
        check("H5", end["advance"] == "terminal", end)
        for step, name in zip(steps[:n], names):
            req = step["claim"]["request"]
            check(
                "H2",
                step["claim"]["kind"] == "tool"
                and req.get("handler") == f"worker:{name}"
                and req.get("params") == {"path": "hello.txt"},
                req,
            )
        check("H2", steps[n]["claim"]["kind"] == "llm", steps[n].get("claim"))
        cur = begin()
        cur.execute(
            "SELECT payload->>'tool', payload->>'result' FROM events "
            "WHERE session_id=%s AND type='tool/result' ORDER BY seq",
            (sid,),
        )
        result_events = cur.fetchall()
        cur.execute(
            "SELECT tool_name, status, jsonb_typeof(result), result #>> '{}', origin_user_seq "
            "FROM effects WHERE session_id=%s AND kind='tool'",
            (sid,),
        )
        effects = cur.fetchall()
        by_effect = {row[0]: row for row in effects}
        cur.execute(
            "SELECT payload->>'text', (payload->>'origin_user_seq')::bigint "
            "FROM events WHERE session_id=%s AND type='llm/message'",
            (sid,),
        )
        llm_rows = cur.fetchall()
        conn.rollback()
        check("H3", [row[0] for row in result_events] == names, result_events)
        for tool, result in result_events:
            check("H3", result == direct[tool], (tool, result, direct.get(tool)))
        check("H4", set(by_effect) == set(names), effects)
        check("H4", all(row[1] == "succeeded" and row[2] == "string" for row in effects), effects)
        for name in names:
            tool_name, _status, _kind, decoded, origin = by_effect[name]
            check("H4", decoded == direct[tool_name] and origin == user_seq, (tool_name, decoded, origin, user_seq))
        sess_status, ends = end_of(sid)
        check("H5", sess_status == "completed", sess_status)
        check("H5", len(ends) == 1 and ends[0].get("delivered") is True, ends)
        check("H5", len(llm_rows) == 1 and llm_rows[0][0] == "pi ports recorded" and llm_rows[0][1] == user_seq, llm_rows)

        replay_claim = steps[0]["claim"]
        replay_text = steps[0]["payload"]
        cur = begin()
        before_results = q1(
            cur,
            "SELECT count(*) FROM events WHERE session_id=%s AND type='tool/result'",
            (sid,),
        )
        replay = complete(cur, replay_claim, "succeeded", replay_text)
        after_results = q1(
            cur,
            "SELECT count(*) FROM events WHERE session_id=%s AND type='tool/result'",
            (sid,),
        )
        conn.rollback()
        check("H9", replay == "replay" and before_results == after_results == n, (replay, before_results, after_results))

        cur = begin()
        cur.execute("DELETE FROM tools WHERE name = ANY(%s)", (names,))
        end_count = q1(cur, "SELECT count(*) FROM tools")
        end_rev = q1(cur, "SELECT revision FROM v13_tools_meta WHERE singleton")
        cur.execute("SELECT name FROM tools WHERE name = ANY(%s)", (names,))
        still = [row[0] for row in cur.fetchall()]
        check("H6", still == [], still)
        check("H6", end_count == base_count, (end_count, base_count))
        check("H6", end_rev == after_rev + n, (after_rev, end_rev, n))
        conn.commit()
    finally:
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


def go_toolchain_absent() -> list[str]:
    skipped = []
    if not command_ok(["go", "version"]):
        skipped.append("go")
    if not (PIG_ROOT / "go.mod").is_file() or not (PIG_ROOT / "coding" / "pigversion" / "pigversion.go").is_file():
        skipped.append("pig_checkout")
    return skipped


def swift_toolchain_absent() -> list[str]:
    skipped = []
    if not command_ok(["swift", "--version"]):
        skipped.append("swift")
    read_tool = PISWIFT_ROOT / "Sources" / "PiSwiftCodingAgent" / "Core" / "Tools" / "ReadTool.swift"
    if not (PISWIFT_ROOT / "Package.swift").is_file() or not read_tool.is_file():
        skipped.append("piswift_checkout")
    return skipped


def piswift_read(argv, root: str, path: str, **fields):
    payload = {"root": root, "path": path}
    payload.update(fields)
    return run_line_json(argv, payload, timeout=90)


def run_swift(argv) -> None:
    run_plane(lambda root, path, **fields: piswift_read(argv, root, path, **fields), argv, "SW-", SW_EVIDENCE)
    run_swift_fence(argv)


def run_swift_fence(argv) -> None:
    def once(cwd, root, path, timeout=30):
        proc = subprocess.run(
            argv,
            input=json.dumps({"root": root, "path": path}).encode(),
            capture_output=True,
            timeout=timeout,
            cwd=cwd,
        )
        line = proc.stdout.split(b"\n", 1)[0]
        payload = json.loads(line.decode()) if line.strip() else {}
        return proc.returncode, payload

    with tempfile.TemporaryDirectory(prefix="v13sw-fence-") as raw:
        parent = Path(raw)
        fixtures = parent / "fixtures"
        fixtures.mkdir()
        (fixtures / "inside.txt").write_bytes(b"inside-ok\n")
        (parent / "secret.txt").write_bytes(b"secret-no\n")
        abs_inside = str((fixtures / "inside.txt").resolve())
        abs_secret = str((parent / "secret.txt").resolve())

        code, payload = once(str(fixtures), ".", "inside.txt")
        check("SW-F1", code == 0 and payload.get("result") == "inside-ok\n", payload)
        code, payload = once(str(fixtures), ".", abs_inside)
        check("SW-F1", code == 0 and payload.get("result") == "inside-ok\n", payload)
        code, payload = once(str(parent), "fixtures", "inside.txt")
        check("SW-F1", code == 0 and payload.get("result") == "inside-ok\n", payload)
        code, payload = once(str(parent), "fixtures", abs_inside)
        check(
            "SW-F1",
            code == 0 and payload.get("result") == "inside-ok\n" and "secret-no" not in json.dumps(payload),
            payload,
        )
        code, payload = once(None, "/", abs_inside)
        check("SW-F1", code == 0 and payload.get("result") == "inside-ok\n", payload)
        code, payload = once(str(parent), "fixtures", abs_secret)
        check("SW-F1", code == 3 and payload.get("error") == "path_outside_workspace", payload)

        fifo = parent / "pipe"
        os.mkfifo(fifo)
        code, payload = once(None, "/", str(fifo), timeout=5)
        check(
            "SW-F2",
            code == 3 and payload.get("error") == "read_failed" and "result" not in payload,
            payload,
        )
        if Path("/dev/zero").exists():
            code, payload = once(None, "/", "/dev/zero", timeout=5)
            check(
                "SW-F2",
                code == 3 and payload.get("error") == "read_failed" and "result" not in payload,
                payload,
            )

    bad_off = piswift_read(argv, str(FIXTURES), "hello.txt", offset="10")
    check("SW-P2", bad_off.error == "invalid_params" and bad_off.exit_code == 3, bad_off.payload)
    bad_lim = piswift_read(argv, str(FIXTURES), "hello.txt", limit=1.5)
    check("SW-P2", bad_lim.error == "invalid_params" and bad_lim.exit_code == 3, bad_lim.payload)
    huge = piswift_read(argv, str(FIXTURES), "hello.txt", offset=1e20)
    check("SW-P2", huge.error == "invalid_params" and huge.exit_code == 3, huge.payload)
    exact = piswift_read(argv, str(FIXTURES), "hello.txt", offset=2**53 + 1)
    check("SW-P2", exact.error == "offset_out_of_range" and exact.exit_code == 3, exact.payload)
    imax = piswift_read(argv, str(FIXTURES), "hello.txt", offset=2**63 - 1)
    check("SW-P2", imax.error == "offset_out_of_range" and imax.exit_code == 3, imax.payload)
    over = piswift_read(argv, str(FIXTURES), "hello.txt", offset=2**63)
    check("SW-P2", over.error == "invalid_params" and over.exit_code == 3, over.payload)

    with tempfile.TemporaryDirectory(prefix="v13sw-adapt-") as raw:
        root = Path(raw)
        quoted = "Offset 3 is beyond end of file (1 lines total)\n"
        (root / "quoted.txt").write_bytes(quoted.encode())
        got = piswift_read(argv, str(root), "quoted.txt")
        check("SW-BODY", got.ok and got.exit_code == 0 and got.result == quoted, got.payload)

        sed_path = root / "sed.txt"
        sed_path.write_bytes(b"placeholder\n")
        abs_sed = str(sed_path.resolve())
        sed_body = f"note sed -n '1p' {abs_sed} | head stays\n"
        sed_path.write_bytes(sed_body.encode())
        got = piswift_read(argv, str(root), "sed.txt")
        check("SW-SED", got.ok and got.result == sed_body, got.payload)

        trail = "hello\n\n[note to continue]"
        (root / "trail.txt").write_bytes(trail.encode())
        got = piswift_read(argv, str(root), "trail.txt")
        check("SW-TRAIL", got.ok and got.result == trail, got.payload)

        mixed = "keep\r\uE000here\r\nnext\n"
        (root / "mixed.txt").write_bytes(mixed.encode())
        got = piswift_read(argv, str(root), "mixed.txt")
        check("SW-E000", got.ok and got.result == mixed and "\uE000" in (got.result or ""), got.payload)

        (root / "nulcrlf.txt").write_bytes(b"a\x00b\r\n")
        got = piswift_read(argv, str(root), "nulcrlf.txt")
        check(
            "SW-NUL",
            (not got.ok)
            and got.exit_code == 3
            and got.error == "read_failed"
            and got.message == "contains NUL"
            and got.result != "a\rb\r\n"
            and "result" not in got.payload,
            got.payload,
        )

        under = b"a" * 51198 + b"\r\n"
        (root / "cap.txt").write_bytes(under)
        proc = subprocess.run(
            argv,
            input=json.dumps({"root": str(root), "path": "cap.txt"}).encode(),
            capture_output=True,
            timeout=60,
        )
        line = proc.stdout.split(b"\n", 1)[0]
        payload = json.loads(line.decode()) if line.strip() else {}
        check(
            "SW-CAP",
            proc.returncode == 0
            and payload.get("result") == under.decode()
            and "50.0KB" not in (payload.get("result") or "")
            and b"path=fenced-derived-copy" in proc.stderr
            and b"path=fenced-absolute" not in proc.stderr,
            (proc.returncode, payload.get("result", "")[-80:], proc.stderr.decode("utf-8", "replace")),
        )
        over_cap = b"b" * 51199 + b"\r\n"
        (root / "over.txt").write_bytes(over_cap)
        got = piswift_read(argv, str(root), "over.txt")
        check(
            "SW-CAP",
            got.ok
            and got.result != over_cap.decode()
            and got.result is not None
            and "50.0KB limit" in got.result
            and got.result.startswith("b" * 51199 + "\r"),
            got.result[-120:] if got.result else got.payload,
        )


def build_piswift() -> list[str]:
    port = ROOT / "piswift_port"
    build_path = AGENT_ROOT / ".piswift-build"
    proc = subprocess.run(
        ["swift", "build", "-c", "release", "--product", "read_piswift", "--build-path", str(build_path)],
        cwd=port,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if proc.returncode != 0:
        err = (proc.stderr or "") + (proc.stdout or "")
        lowered = err.lower()
        if "unable to find" in lowered and "swift" in lowered:
            raise ToolchainMissing(["swift"], err)
        raise AssertionError(f"swift build: {err[-2000:]}")
    shown = subprocess.run(
        ["swift", "build", "-c", "release", "--product", "read_piswift", "--build-path", str(build_path), "--show-bin-path"],
        cwd=port,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if shown.returncode != 0:
        raise AssertionError(f"swift bin path: {(shown.stderr or shown.stdout)[-1000:]}")
    binary = Path(shown.stdout.strip()) / "read_piswift"
    if not binary.is_file():
        raise AssertionError(f"missing binary: {binary}")
    return [str(binary)]



def main(argv: list[str]) -> int:
    del argv
    failed = False
    skipped = toolchain_absent()
    go_skipped = go_toolchain_absent()
    swift_skipped = swift_toolchain_absent()
    pig_argv = None
    swift_argv = None
    if not go_skipped:
        try:
            pig_argv = build_pig()
        except ToolchainMissing as exc:
            go_skipped.extend(exc.planes)
        except AssertionError as exc:
            print(exc)
            failed = True
    if not swift_skipped:
        try:
            swift_argv = build_piswift()
        except ToolchainMissing as exc:
            swift_skipped.extend(exc.planes)
        except AssertionError as exc:
            print(exc)
            failed = True
    try:
        run_guard()
        if not skipped:
            run_c()
            run_catalog()
        if pig_argv is not None:
            run_go(pig_argv)
            run_catalog_pig()
        if swift_argv is not None:
            run_swift(swift_argv)
            run_catalog_piswift()
        ring_planes = []
        if not skipped:
            ring_planes.append(("", "read_pi_ext", "Read a text file through the pi framework read tool.", NODE, 60))
        if pig_argv is not None:
            ring_planes.append(("GO-", "read_pig", "Read a text file through the PiG framework read tool.", pig_argv, 90))
        if swift_argv is not None:
            ring_planes.append(("SW-", "read_piswift", "Read a text file through the PiSwift framework read tool.", swift_argv, 90))
        if ring_planes:
            run_ring(ring_planes)
    except AssertionError as exc:
        print(exc)
        failed = True
    except ProtocolError as exc:
        print(f"[FAIL] protocol: {exc}")
        failed = True
    if failed:
        return 1
    planes = skipped + go_skipped + swift_skipped
    if planes:
        print(f"[SKIP] not_run/toolchain_absent planes={','.join(planes)}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
