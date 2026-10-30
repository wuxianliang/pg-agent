"""W3 line-JSON transport gate: every frozen v2 byte/corpus row.

Read-only over the W1 vectors and B0 golden frames; no re-bless mode.
DB-free, Node-free, socket-free and subprocess-free: only the transport's
run_process binding is patched, and an audit hook rejects real external I/O.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v24.host import line_json  # noqa: E402
from v24.host.canonical import descriptor_digest  # noqa: E402
from v24.host.descriptor import KEY_RE  # noqa: E402
from v24.host.process_io import (  # noqa: E402
    STDERR_LIMIT, STDIN_LIMIT, STDOUT_LIMIT, ProcessResult, ProcessSpec,
)
from v24.host.registry import (  # noqa: E402
    ApprovedAdapter, ApprovedPlugin, ApprovedTool, adapter_declaration_digest,
)

VECTORS = Path(__file__).resolve().parent / "vectors"
V1_FRAMES = ROOT / "v24" / "b0" / "golden" / "frames_v1.json"
V1_RESERVATION = "v24:host_prepare:b0-golden-reservation"
REQUEST_IDS = (
    "frame.request.invoke", "frame.request.prepare", "frame.request.release",
    "frame.request.inspect", "frame.request.utf8_sort_trap",
)
RESPONSE_IDS = ("frame.response.success", "frame.response.known_error")
TABLE_IDS = (
    "frame.response.whitespace_corpus", "frame.response.invalid_corpus",
    "frame.process.unknown_outcomes",
)
# The same nine network roots as s11/test_g10.py, plus DB client roots.
FORBIDDEN_IMPORTS = {
    "socket", "http", "urllib", "requests", "ftplib", "smtplib",
    "telnetlib", "aiohttp", "httpx", "psycopg", "psycopg2",
    "asyncpg", "duckdb", "sqlite3",
}


def static_guards() -> None:
    paths = [Path(__file__).resolve()] + [
        ROOT / "v24" / "host" / name for name in (
            "line_json.py", "process_io.py", "registry.py", "canonical.py",
            "descriptor.py", "renderers.py", "tool_schema.py", "tool_results.py",
        )
    ]
    for path in paths:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
                modules += [(node.module + "." if node.module else "") + alias.name
                            for alias in node.names]
            else:
                modules = []
            for module in modules:
                assert module.split(".")[0] not in FORBIDDEN_IMPORTS, (path, module)
                assert module not in {"db", "v24.host.db"}, (path, module)
            if isinstance(node, ast.Call):
                assert not any(keyword.arg == "shell"
                               and isinstance(keyword.value, ast.Constant)
                               and keyword.value.value is True
                               for keyword in node.keywords), path
        # Text scans include comments/docstrings without matching their own needles.
        assert "time" + ".sleep" not in source, path
        assert "shell" + "=True" not in source, path


class ExternalIOGuard:
    """Observe/deny actual launches without replacing subprocess.Popen."""

    def __init__(self):
        self.events = []

    def __call__(self, event, args):
        if (event == "subprocess.Popen" or event.startswith("socket.")
                or event.startswith("sqlite3.")
                or event in {"os.system", "os.posix_spawn", "os.fork", "os.exec"}):
            self.events.append(event)
            raise AssertionError(f"external I/O attempted: {event}")


def byte_case(case, raw) -> bytes:
    assert type(raw) is bytes, case["id"]
    assert raw == bytes.fromhex(case["expected_hex"]), case["id"]
    assert len(raw) == case["expected_length"], case["id"]
    assert hashlib.sha256(raw).hexdigest() == case["expected_sha256"], case["id"]
    if case["expected_text"] is not None:
        assert raw == case["expected_text"].encode("utf-8"), case["id"]
    return raw


def process_result(**overrides) -> ProcessResult:
    fields = dict(pid=4242, returncode=0, stdout=b"", stderr=b"gate stderr",
                  timed_out=False, stdout_limited=False, stderr_limited=False,
                  wall_ms=19)
    fields.update(overrides)
    return ProcessResult(**fields)


def approved_entries(descriptors):
    cwd = str(ROOT.resolve())
    env_names = ("PATH", "HOME", "V24_W3_UNSET_TEST_VARIABLE")
    descriptor = {"v": 1, "tool": {
        "description": "W3 v1 transport probe", "parameters": {"type": "object"},
    }}
    v1 = ApprovedAdapter(
        adapter_id="w3-v1", language="python", identity="w3-v1", version="1",
        manifest_digest="0" * 64, artifact_digest="1" * 64,
        adapter_digest="2" * 64, descriptor_digest=descriptor_digest(descriptor),
        argv=(sys.executable, str(Path(__file__).resolve()), "v1-never-executed"),
        cwd=cwd, environment_allowlist=env_names, tool_key="read",
        description=descriptor["tool"]["description"],
        parameters=descriptor["tool"]["parameters"], timeout_ms=1207,
        stdout_limit=54321, stderr_limit=12345,
    )
    tool = ApprovedTool.from_descriptor(descriptors["descriptor.v2.read"]["input"], key="read")
    v2 = ApprovedPlugin(
        adapter_id="w3-v2", language="python", identity="w3-v2", version="2",
        manifest_digest="3" * 64, artifact_digest="4" * 64,
        adapter_digest=adapter_declaration_digest("python"),
        argv=(sys.executable, str(Path(__file__).resolve()), "v2-never-executed"),
        cwd=cwd, environment_allowlist=env_names, tools=(tool,), workspace_root=cwd,
        timeout_ms=1703, stdout_limit=60001, stderr_limit=12001,
    )
    assert not hasattr(v1, "protocol") and v2.protocol == 2
    assert v2.tools[0].timeout_ms != v2.timeout_ms
    return v1, v2


class TransportStub:
    def __init__(self):
        self.calls = []
        self.result = None

    def __call__(self, spec):
        assert isinstance(spec, ProcessSpec)
        assert isinstance(self.result, ProcessResult), "preset result required"
        self.calls.append(spec)
        return self.result

    def invoke(self, entry, request, result, frozen_stdin):
        self.result = result
        before = len(self.calls)
        if getattr(entry, "protocol", 1) == 1:
            # Preserve the pre-W3 public keyword interface as well as B0's
            # positional callers.
            invocation = line_json.run(adapter=entry, **request)
        else:
            invocation = line_json.run(entry, **request)
        assert len(self.calls) == before + 1, request
        timeout = entry.timeout_ms
        if getattr(entry, "protocol", 1) == 2 and request["operation"] == "invoke":
            timeout = next(tool.timeout_ms for tool in entry.tools
                           if tool.key == request["tool"])
        expected_env = {name: os.environ[name] for name in entry.environment_allowlist
                        if name in os.environ}
        assert self.calls[-1] == ProcessSpec(
            argv=entry.argv, cwd=entry.cwd, env=expected_env, stdin=frozen_stdin,
            timeout_ms=timeout, stdout_limit=entry.stdout_limit,
            stderr_limit=entry.stderr_limit,
        ), request
        assert invocation.started is True
        assert invocation.returncode == result.returncode
        assert invocation.wall_ms == result.wall_ms and invocation.pid == result.pid
        assert invocation.stdout == result.stdout and invocation.stderr == result.stderr
        return invocation

    def reject(self, fn, reason):
        before = len(self.calls)
        try:
            fn()
        except line_json.LineJsonPreflight as exc:
            assert exc.reason == reason and exc.args == (reason,), (reason, exc)
        else:
            raise AssertionError(f"expected LineJsonPreflight({reason!r})")
        assert len(self.calls) == before, reason


def check_invocation(invocation, classification, expected):
    if classification in ("success", "known_error"):
        class_name = "success" if classification == "success" else "failure"
        assert invocation.class_name == class_name, (classification, invocation)
        assert invocation.reason is None and invocation.result == expected, invocation
    else:
        assert invocation.class_name == "unknown", (classification, invocation)
        assert invocation.reason == classification and invocation.result is None, invocation


def check_response(stub, entry, request_case, raw, operation, exit_code, expected_class):
    expected_result = None
    if expected_class in ("success", "known_error"):
        frame = json.loads(raw.decode("utf-8"))
        expected_result = frame["result" if expected_class == "success" else "error"]
    assert line_json._classify_v2(raw, operation=operation, exit_code=exit_code) == (
        expected_class, expected_result,
    ), (operation, expected_class, raw)
    invocation = stub.invoke(
        entry, request_case["input"], process_result(stdout=raw, returncode=exit_code),
        bytes.fromhex(request_case["expected_hex"]),
    )
    check_invocation(invocation, expected_class, expected_result)
    return invocation


def main() -> int:
    assert not sys.argv[1:], "this read-only gate accepts no arguments"
    static_guards()
    if not hasattr(sys, "addaudithook"):
        print("[SKIP] W3 line-json v2 contract: audit hooks unavailable")
        return 2
    guard = ExternalIOGuard()
    sys.addaudithook(guard)
    paths = (VECTORS / "frames_v2.json", V1_FRAMES, VECTORS / "descriptor_v2.json")
    originals = {path: path.read_bytes() for path in paths}
    document, v1_document, descriptor_document = [json.loads(originals[path]) for path in paths]
    assert document["format"] == "v24-tool-plugin-abi-w1-vectors-1"
    assert v1_document["format"] == "v24-tool-plugin-abi-v1-golden-1"
    cases = {case["id"]: case for case in document["cases"]}
    assert len(document["cases"]) == len(cases) == 10
    assert set(cases) == set(REQUEST_IDS + RESPONSE_IDS + TABLE_IDS)
    for case in cases.values():
        assert case["status"] == "m2_pending", case["id"]
        assert case["first_production_stage"] == "M2", case["id"]
    descriptors = {case["id"]: case for case in descriptor_document["cases"]}
    v1, v2 = approved_entries(descriptors)
    assert line_json.TOOL_KEY_RE.pattern == KEY_RE.pattern
    process_input = cases["frame.process.unknown_outcomes"]["input"]
    assert process_input["limits"] == {
        "stdin": STDIN_LIMIT, "stdout": STDOUT_LIMIT, "stderr": STDERR_LIMIT,
    } == {"stdin": 1048576, "stdout": 65536, "stderr": 16384}
    assert line_json.STDOUT_LIMIT == STDOUT_LIMIT
    assert line_json.STDERR_LIMIT == STDERR_LIMIT

    checked_cases = set()
    frame_bytes = parse_rows = preflight_rejections = unknown_outcomes = 0
    v1_probes = dispatch_probes = j_probes = v1_request_bytes = 0
    whitespace = cases[TABLE_IDS[0]]["input"]
    invalid = cases[TABLE_IDS[1]]["input"]
    assert len(whitespace) == 9 and len(invalid) == 46
    request_for = {operation: cases[f"frame.request.{operation}"]
                   for operation in line_json.V2_OPERATIONS}
    success_for = {row["operation"]: bytes.fromhex(row["hex"]) for row in whitespace}
    stub = TransportStub()
    # This is the only patched binding. The real executor and Popen stay intact.
    with patch.object(line_json, "run_process", new=stub):
        # 1. Five request bytes, also sent unchanged to the stub executor.
        for case_id in REQUEST_IDS:
            case = cases[case_id]
            raw = byte_case(case, line_json.build_frame_v2(**case["input"]))
            assert raw.endswith(b"\n") and raw.count(b"\n") == 1, case_id
            invocation = stub.invoke(
                v2, case["input"], process_result(stdout=success_for[case["input"]["operation"]]), raw,
            )
            assert invocation.class_name == "success" and invocation.reason is None, case_id
            frame_bytes += 1
            checked_cases.add(case_id)

        # 2. Both response byte cases: classifier and public Invocation mapping.
        for case_id in RESPONSE_IDS:
            case = cases[case_id]
            raw = byte_case(case, bytes.fromhex(case["expected_hex"]))
            assert raw.endswith(b"\n") and raw.count(b"\n") == 1, case_id
            check_response(stub, v2, request_for[case["input"]["operation"]], raw,
                           case["input"]["operation"], case["input"]["exit_code"],
                           case["classification"])
            frame_bytes += 1
            checked_cases.add(case_id)

        # 3/4. Every corpus row, including success/error controls in 'invalid'.
        for case_id, rows in ((TABLE_IDS[0], whitespace), (TABLE_IDS[1], invalid)):
            assert len({row["id"] for row in rows}) == len(rows)
            for row in rows:
                raw = bytes.fromhex(row["hex"])
                invocation = check_response(
                    stub, v2, request_for[row["operation"]], raw,
                    row["operation"], row["exit_code"], row["classification"],
                )
                if case_id == TABLE_IDS[0]:
                    assert row["classification"] == "success", row["id"]
                if row["id"] == "u2028_string":
                    assert raw.count(b"\n") == 1 and b"\xe2\x80\xa8" in raw
                    assert invocation.result == {"value": {"text": "a\u2028b\u2029c"}}
                if row["id"] in ("double_lf", "extra_frame"):
                    assert invocation.reason == "extra_frame", row["id"]
                parse_rows += 1
            checked_cases.add(case_id)

        # 5. Each frozen bad build rejects directly and via run, before the stub.
        assert len(process_input["preflight"]) == 5
        for row in process_input["preflight"]:
            assert row["expected"] == "bad_request", row["id"]
            stub.reject(lambda row=row: line_json.build_frame_v2(**row["input"]), "bad_request")
            stub.reject(lambda row=row: line_json.run(v2, **row["input"]), "bad_request")
            preflight_rejections += 1

        # 6. Flags/exit code, rather than parser guesses, drive unknown outcomes.
        outcomes = {
            "timeout": process_result(timed_out=True, returncode=-9),
            "stdout_limit": process_result(stdout_limited=True, returncode=-9),
            "stderr_limit": process_result(stderr_limited=True, returncode=-9),
            "abnormal_exit": process_result(returncode=17),
        }
        assert len(process_input["outcomes"]) == len(outcomes) == 4
        assert set(process_input["outcomes"]) == set(outcomes)
        for reason in process_input["outcomes"]:
            case = request_for["invoke"]
            invocation = stub.invoke(v2, case["input"], outcomes[reason],
                                     bytes.fromhex(case["expected_hex"]))
            check_invocation(invocation, reason, None)
            unknown_outcomes += 1
        checked_cases.add(TABLE_IDS[2])

        # 7. All four frozen v1 request bytes, then three frozen response probes.
        v1_cases = {case["id"]: case for case in v1_document["cases"]}
        for operation in line_json.OPERATIONS:
            case = v1_cases[f"frame.{operation}"]
            raw = line_json.build_frame(operation, V1_RESERVATION, case["semantic"]["args"])
            byte_case(case, raw)
            assert raw.count(b"\n") == 1 and raw.endswith(b"\n")
            v1_request_bytes += 1
        v1_request = dict(operation="invoke", reservation=V1_RESERVATION,
                          args=v1_cases["frame.invoke"]["semantic"]["args"])
        v1_stdin = bytes.fromhex(v1_cases["frame.invoke"]["expected_hex"])
        for case_id in ("stdout.python.invoke_success", "stdout.python.invoke_error", "parser.u2028"):
            case = v1_cases[case_id]
            raw = byte_case(case, bytes.fromhex(case["expected_hex"]))
            semantic = case["semantic"]
            invocation = stub.invoke(v1, v1_request,
                                     process_result(stdout=raw, returncode=semantic.get("returncode", 0)),
                                     v1_stdin)
            if "exit_class" in semantic:
                assert invocation.class_name == semantic["exit_class"], case_id
                assert invocation.result == semantic["result"] and invocation.reason is None, case_id
            else:
                check_invocation(invocation, semantic["classification"], None)
            v1_probes += 1

        # 8. Genuine v1/default and explicit v2 dispatch; unknown protocol cannot spawn.
        assert line_json._protocol(v1) == 1
        invocation = stub.invoke(v1, v1_request,
                                 process_result(stdout=bytes.fromhex(v1_cases["stdout.python.invoke_success"]["expected_hex"])),
                                 v1_stdin)
        assert invocation.result == v1_cases["stdout.python.invoke_success"]["semantic"]["result"]
        assert invocation.class_name == "success"
        dispatch_probes += 1
        assert line_json._protocol(v2) == 2
        case = request_for["invoke"]
        check_response(stub, v2, case, bytes.fromhex(cases[RESPONSE_IDS[0]]["expected_hex"]),
                       "invoke", 0, "success")
        dispatch_probes += 1
        # A minimal entry suffices: dispatch must reject before touching any other field.
        stub.reject(lambda: line_json.run(SimpleNamespace(protocol=3), **case["input"]),
                    "protocol_mismatch")
        dispatch_probes += 1

        # 9. D14/C.8: J-domain violations are unknown bad_frame, never failure.
        for raw in (b'{"ok":true,"v":2,"result":{"value":1.5}}\n',
                    b'{"ok":true,"v":2,"result":{"value":9007199254740992}}\n'):
            invocation = check_response(stub, v2, case, raw, "invoke", 0, "bad_frame")
            assert invocation.class_name == "unknown" and invocation.class_name != "failure"
            j_probes += 1

    assert guard.events == [], guard.events  # includes zero subprocess.Popen events
    assert all(path.read_bytes() == original for path, original in originals.items())
    assert checked_cases == set(cases)
    assert (frame_bytes, parse_rows, preflight_rejections, unknown_outcomes) == (7, 55, 5, 4)
    assert (v1_request_bytes, v1_probes, dispatch_probes, j_probes) == (4, 3, 3, 2)
    print(
        f"[passed] W3 line-json v2 contract; cases={len(checked_cases)}; "
        f"frame_bytes={frame_bytes}; parse_rows={parse_rows}; "
        f"preflight_rejections={preflight_rejections}; unknown_outcomes={unknown_outcomes}; "
        "v1_bytes_unchanged=true"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
