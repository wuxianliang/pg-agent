"""W4b filesystem tool gate: read, list, search and page convergence.

The vector cases run real approved-plugin subprocesses.  A smaller DB-backed
section reuses ``v24/s11/plugin_fixtures.PluginHarness`` to prove the same
tools through the host dispatcher.  No provider socket is opened and no real
provider is constructed.
"""
from __future__ import annotations

import copy
import contextlib
import hashlib
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import tracemalloc
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _path in (HERE, HERE / "plugins", ROOT, ROOT / "v24" / "s11",
              ROOT / "v24" / "s1", ROOT / "v24" / "s2", ROOT / "v24" / "s4"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from fixtures import (  # noqa: E402
    PLUGINS,
    SEARCH_CASES,
    TOOL_CONTRACTS,
    V2Spec,
    node_spec,
    open_harness,
    read_spec,
    read_workspace,
    search_workspace,
    spawn_count,
    workspace,
)
from plugin_fixtures import final_reply  # noqa: E402
from setup_db import server_helper_scope, setup_db  # noqa: E402
from v24.host.deepseek import _v2_provider_name  # noqa: E402
from v24.host.tool_pages import BUILTIN_PAGE_CONTRACTS, validate_page  # noqa: E402
from v24.host.tool_results import measure as result_measure  # noqa: E402
from v24.host.renderers import RENDERERS  # noqa: E402

CONTRACT = {case["id"]: case for case in TOOL_CONTRACTS["cases"]}
READ_CASES = CONTRACT["tool.read.contract"]["input"]["inputs"]
LIST_CASES = CONTRACT["tool.list.contract"]["input"]["inputs"]
SEARCH_INPUTS = CONTRACT["tool.search.contract"]["input"]["inputs"]


def node_path():
    return shutil.which("node")


def strip_non_utf8(value, kind):
    value = copy.deepcopy(value)
    if kind == "list":
        value.pop("skipped_non_utf8", None)
    else:
        value.get("skipped", {}).pop("non_utf8", None)
    return value


def shim_guard(base, list_tree):
    """Differential checks that the shim changes only the non-UTF-8 counters."""
    shim = node_spec(base / "guard-shim", list_tree)
    control = node_spec(base / "guard-control", list_tree.root)
    shim_value = invoke(shim, "list", {"path": "."})["result"]["value"]
    control_value = invoke(control, "list", {"path": "."})["result"]["value"]
    assert shim_value["skipped_non_utf8"] == 1, shim_value
    assert control_value["skipped_non_utf8"] == 0, control_value
    assert strip_non_utf8(shim_value, "list") == strip_non_utf8(
        control_value, "list")
    for offset in (1, 2, 3):
        left = invoke(shim, "list",
                      {"path": ".", "offset": offset, "limit": 1})
        right = invoke(control, "list",
                       {"path": ".", "offset": offset, "limit": 1})
        assert strip_non_utf8(left["result"]["value"], "list") == strip_non_utf8(
            right["result"]["value"], "list"), offset
    skip_tree = search_workspace(base / "guard-skip", "skip_counters")
    search_shim = node_spec(base / "guard-search-shim", skip_tree)
    search_control = node_spec(base / "guard-search-control", skip_tree.root)
    shim_search = invoke(search_shim, "search",
                         {"query": "x"})["result"]["value"]
    control_search = invoke(search_control, "search",
                            {"query": "x"})["result"]["value"]
    assert shim_search["skipped"]["non_utf8"] == 2, shim_search
    assert control_search["skipped"]["non_utf8"] == 1, control_search
    assert strip_non_utf8(shim_search, "search") == strip_non_utf8(
        control_search, "search")
    events = [json.loads(line) for line in
              list_tree.ledger.read_text(encoding="utf-8").splitlines() if line]
    assert not any(event.get("event") == "mismatch" for event in events), events
    assert any(event.get("event") == "inject" for event in events), events
    return 5


def preflight_shim(workspace):
    """Verify the test-only preload injects exactly one 0xff for this root."""
    ledger = workspace.ledger
    if ledger is not None and ledger.exists():
        ledger.unlink()
    env = {key: value for key, value in os.environ.items()
           if key != "NODE_OPTIONS"}
    env.update(workspace.env_overlay())
    root = workspace.root
    script = (
        "const fs=require('fs');"
        "const r=fs.readdirSync(process.argv[1],{encoding:'buffer'});"
        "const hits=r.filter(b=>b.length===1&&b[0]===255).length;"
        "if(hits!==1)process.exit(3);"
    )
    process = subprocess.run([node_path(), "-e", script, root], env=env,
                             capture_output=True, text=True)
    events = []
    if ledger is not None and ledger.exists():
        events = [json.loads(line) for line in
                  ledger.read_text(encoding="utf-8").splitlines() if line]
    loaded = any(event.get("event") == "loaded" for event in events)
    if process.returncode != 0:
        if loaded:
            raise AssertionError(("preload_loaded_but_no_inject",
                                  process.returncode, process.stderr))
        return False
    assert any(event.get("event") == "inject" for event in events), events
    assert not any(event.get("event") == "mismatch" for event in events), events
    control = Path(root).parent / f"control-{uuid.uuid4().hex[:8]}"
    control.mkdir()
    (control / "only.txt").write_bytes(b"")
    script_control = (
        "const fs=require('fs');"
        "const r=fs.readdirSync(process.argv[1],{encoding:'buffer'});"
        "if(r.some(b=>b.length===1&&b[0]===255))process.exit(4);"
    )
    control_process = subprocess.run(
        [node_path(), "-e", script_control, str(control)], env=env,
        capture_output=True, text=True)
    assert control_process.returncode == 0, control_process.stderr
    return True



def invoke(spec: V2Spec, tool: str, args: dict, *, timeout=60):
    frame = {"v": 2, "operation": "invoke",
             "reservation": f"v24:tool_call:{uuid.uuid4()}",
             "args": args, "tool": tool}
    source = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "V24_WORKSPACE_ROOT": spec.workspace,
    }
    source.update(dict(spec.env_overlay))
    env = spec.entry.environment(source)
    process = subprocess.run(
        list(spec.entry.argv),
        input=json.dumps(frame, ensure_ascii=False).encode("utf-8") + b"\n",
        cwd=spec.entry.cwd, env=env, capture_output=True, timeout=timeout)
    assert process.returncode in (0, 3), (process.returncode, process.stderr)
    payload = json.loads(process.stdout.decode("utf-8"))
    assert payload.get("v") == 2, payload
    return payload


def invoke_raw(spec: V2Spec, tool: str, args: dict, *, drop_root=False):
    frame = {"v": 2, "operation": "invoke",
             "reservation": f"v24:tool_call:{uuid.uuid4()}",
             "args": args, "tool": tool}
    source = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "V24_WORKSPACE_ROOT": spec.workspace,
    }
    source.update(dict(spec.env_overlay))
    env = spec.entry.environment(source)
    if drop_root:
        env.pop("V24_WORKSPACE_ROOT", None)
    process = subprocess.run(
        list(spec.entry.argv),
        input=json.dumps(frame, ensure_ascii=False).encode("utf-8") + b"\n",
        cwd=spec.entry.cwd, env=env, capture_output=True, timeout=60)
    assert process.returncode in (0, 3), (process.returncode, process.stderr)
    payload = json.loads(process.stdout.decode("utf-8"))
    assert payload.get("v") == 2, payload
    return payload


def check_value(spec: V2Spec, tool_key: str, args: dict, value):
    tool = spec.entry.tool_for(tool_key)
    assert tool is not None
    tool.output_check(value)
    validate_page(tool.render, args, value)


def expect_error(spec: V2Spec, tool: str, args: dict, code: str):
    payload = invoke(spec, tool, args)
    assert payload.get("ok") is False, payload
    assert payload.get("error", {}).get("code") == code, payload
    return payload


def expect_value(spec: V2Spec, tool: str, args: dict, expected: dict):
    payload = invoke(spec, tool, args)
    assert payload.get("ok") is True, payload
    value = payload["result"]["value"]
    check_value(spec, tool, args, value)
    assert value == expected, (tool, args, value, expected)
    return value


def selector_probe():
    import fs_read
    cases = [
        ([83, 43, 83], 50, 2),
        ([83, 43, 60, 44], 50, 4),
        ([60, 50, 70], 50, 2),
        ([51, 52], 50, 0),
    ]
    for lengths, cap, expected in cases:
        assert fs_read.select_prefix(lengths, cap) == expected, (
            lengths, cap, fs_read.select_prefix(lengths, cap), expected)
    script = (
        "const m=require(process.argv[1]);"
        "const cases=[[[83,43,83],50,2],[[83,43,60,44],50,4],"
        "[[60,50,70],50,2],[[51,52],50,0]];"
        "for (const [lengths,cap,expected] of cases) {"
        "if (m.selectPrefix(lengths,cap)!==expected) process.exit(1);"
        "} console.log('ok');"
    )
    process = subprocess.run(
        [node_path(), "-e", script, str(PLUGINS / "fs_tools.js")],
        capture_output=True, text=True)
    assert process.returncode == 0, (process.stdout, process.stderr)
    return 4


def v2_tool_reply(call_id, tool_key, args):
    call = {"id": call_id, "type": "function",
            "function": {"name": _v2_provider_name(tool_key),
                         "arguments": json.dumps(args, ensure_ascii=False,
                                                sort_keys=True,
                                                separators=(",", ":"))}}
    raw = {
        "id": "resp-tool", "model": "deepseek-flash",
        "choices": [{"finish_reason": "tool_calls", "message": {
            "role": "assistant", "content": None,
            "reasoning_content": "plan", "tool_calls": [call]}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    return {"status": 200, "advance_ms": 7, "raw": raw}


def dispatch_records(harness, kind):
    found = []
    for record in harness.journal.records:
        if record.get("event_type") != "dispatch_finished":
            continue
        payload = record.get("payload") or {}
        if payload.get("kind") == kind:
            found.append(payload)
    return found


def run_harness_case(fixture, base, spec: V2Spec, tool_key: str, args: dict,
                     value_check, result_check=None):
    realm = spec.realm
    harness = open_harness(fixture, [spec], base / f"harness-{realm}",
                           realm=realm)
    try:
        install_id = harness.admit(spec)
        harness.prepare([install_id])
        harness.activate(install_id, tool_key)
        fiber = harness.fiber(install_id)
        requires = [tool_key]
        response = harness.start(
            fiber["fiber_id"], requires,
            [{"role": "user", "content": f"invoke {tool_key}"}])
        script = [v2_tool_reply("call_1", tool_key, args), final_reply("final")]
        harness.run(script, max_rounds=30)
        payloads = dispatch_records(harness, "tool_call")
        assert len(payloads) == 1, len(payloads)
        payload = payloads[0]
        if result_check is not None:
            result_check(payload)
        if result_check is not None and payload["tool_result"].get("status") != "ok":
            return payload
        value = payload["tool_result"]["output"]["value"]
        check_value(spec, tool_key, args, value)
        value_check(value)
        assert spawn_count(harness, install_id) >= 2
        resource = dispatch_records(harness, "host_prepare")
        assert resource and resource[0]["resource_result"]["v"] == 1
        return value
    finally:
        harness.close()


def path_differential(base, read_spec_value, node_spec_value):
    common = (
        ("../escape", "path_escape"),
        (".git/config", "path_excluded"),
        ("missing", "not_found"),
        ("bad\x00path", "invalid_path"),
    )
    for path, code in common:
        expect_error(read_spec_value, "read", {"path": path}, code)
        expect_error(node_spec_value, "list", {"path": path}, code)
        expect_error(node_spec_value, "search", {"query": "x", "path": path},
                     code)
    expect_error(read_spec_value, "read", {"path": "link"}, "symlink_denied")
    expect_error(node_spec_value, "list", {"path": "b"}, "symlink_denied")
    expect_error(node_spec_value, "search", {"query": "x", "path": "b"},
                 "symlink_denied")
    return len(common) * 3 + 3


READ_EVIDENCE = {}


def read_probes(base):
    """W5-R01..R29: read-only contracts beyond the frozen sixteen cases."""
    import errno
    from unittest.mock import patch
    import fs_read
    import w1_reference as reference
    from v24.host.registry import AdapterNotFound
    from v24.host.tool_results import _assert_error

    tree = read_workspace(base / "read-probes")
    spec = read_spec(base / "read-probe-spec", tree)
    root = Path(tree.root)
    passed = []

    def done(number):
        assert number not in passed, number
        passed.append(number)

    def error_payload(payload, code):
        assert payload.get("ok") is False, payload
        assert payload["error"]["code"] == code, payload
        _assert_error(payload["error"])
        assert tree.root not in payload["error"]["message"]

    def error(args, code):
        error_payload(invoke(spec, "read", args), code)

    def local_error(fn, code):
        try:
            fn()
        except fs_read.ToolError as exc:
            assert exc.code == code, (exc.code, code)
            _assert_error({"code": exc.code, "message": exc.message})
            assert tree.root not in exc.message
        else:
            raise AssertionError(("expected read error", code))

    def success(args):
        payload = invoke(spec, "read", args)
        assert payload.get("ok") is True, payload
        assert set(payload["result"]) == {"value"}, payload
        value = payload["result"]["value"]
        check_value(spec, "read", args, value)
        return value

    error({"path": "binary"}, "binary_file")
    done(1)
    error({"path": "dir"}, "not_a_file")
    done(2)
    error({"path": "fifo"}, "not_a_file")
    done(3)
    if os.geteuid() == 0:
        with patch.object(fs_read.os, "open", side_effect=PermissionError()):
            local_error(lambda: fs_read.read_tool({"path": "noperm"}, tree.root),
                        "permission_denied")
        permission_probe = "mock_root"
    else:
        mode = (root / "noperm").stat().st_mode
        try:
            (root / "noperm").chmod(0)
            error({"path": "noperm"}, "permission_denied")
        finally:
            (root / "noperm").chmod(mode)
        permission_probe = "real"
    done(4)
    with patch.object(fs_read.os, "open", side_effect=OSError(errno.EIO, "injected")):
        local_error(lambda: fs_read.read_tool({"path": "three"}, tree.root),
                    "io_error")
    done(5)
    error_payload(invoke_raw(spec, "read", {"path": "three"}, drop_root=True),
                  "root_unavailable")
    done(6)
    error({"path": "three", "offset": 4}, "offset_out_of_range")
    done(7)
    assert success({"path": "nul_late"})["text"] == "a" * 8192 + "\x00"
    done(8)
    assert success({"path": str(root / "three")})["path"] == "three"
    done(9)
    outside = base / "outside.txt"
    outside.write_bytes(b"x")
    error({"path": str(outside)}, "path_escape")
    done(10)
    error({"path": "dirlink/f"}, "symlink_denied")
    done(11)
    assert success({"path": "./dir//f"})["path"] == "dir/f"
    done(12)
    error({"path": ""}, "invalid_path")
    done(13)
    error({"path": "a" * 1025}, "invalid_path")
    done(14)
    # The schema counts scalars; the plugin intentionally fails closed in bytes.
    spec.entry.tool_for("read").parameters_check({"path": "é" * 513})
    error({"path": "é" * 513}, "invalid_path")
    done(15)
    assert success({"path": ".hidden"})["text"] == "h"
    done(16)
    assert success({"path": "three"})["text"] == "a\nb\nc"
    done(17)
    error({"path": "long_after"}, "line_too_long")
    done(18)
    value = success({"path": "nine5", "limit": 4})
    assert (value["end_line"], value["truncated_by"]) == (4, "lines"), value
    done(19)
    value = success({"path": "nine5", "limit": 5})
    assert (value["end_line"], value["truncated_by"]) == (4, "bytes"), value
    done(20)
    error({"path": "ctrl16384"}, "line_too_long")
    done(21)

    domains = ("value", "content", "meta", "frame")
    empty = next(case["expected"]["value"] for case in READ_CASES
                 if case["id"] == "empty_offset1")
    empty_counts = fs_read.empty_measures("empty")
    for domain in domains:
        caps = fs_read._caps()
        caps[domain] = empty_counts[domain] - 1
        with patch.object(fs_read, "_caps", return_value=caps):
            local_error(lambda: fs_read.read_tool({"path": "empty"}, tree.root),
                        "output_too_large")
            local_error(lambda: fs_read.read_tool(
                {"path": "empty", "offset": 2}, tree.root), "offset_out_of_range")
    assert fs_read.read_tool({"path": "empty"}, tree.root) == empty
    done(22)

    def candidate(path, offset, limit, total, final_newline, lines, k):
        end = offset + k - 1
        truncated = end < total
        return {"path": path, "text": "\n".join(lines[:k]),
                "start_line": offset, "end_line": end, "total_lines": total,
                "final_newline": final_newline, "truncated": truncated,
                "truncated_by": (("lines" if k == limit else "bytes")
                                 if truncated else None),
                "next_offset": end + 1 if truncated else None}

    def compare(args, value, actual):
        content, meta = reference.render("read", value)
        reference_counts = reference.budget_measures(args, value, content, meta)
        host_content, host_meta = RENDERERS.render(
            spec.entry.tool_for("read").render, args, value)
        assert (host_content, host_meta) == (content, meta)
        host_counts = result_measure(args, value, host_content, host_meta)
        for domain in domains:
            assert actual[domain] == reference_counts[domain] == host_counts[domain], (
                "W5-R23", domain, args, actual, reference_counts, host_counts)

    for raw in [bytes([byte]) for byte in range(128)] + [
            sample.encode("utf-8") for sample in ("é", "😀", "\u2028", "\u2029", "\x7f")]:
        assert fs_read.escaped_bytes_len(raw) == reference.escaped_payload_bytes(
            raw.decode("utf-8", "strict")), raw
    lines = ['"', "\\", "\b\f\r\t", "\x01", "\x1f", "tail\r",
             "é😀\u2028\u2029", "", "x", ""]
    line_e = [fs_read.escaped_bytes_len(line.encode("utf-8")) for line in lines]
    for offset in (1, 9, 10, 99, 100, 1000):
        for total in (offset + len(lines) - 1, offset + len(lines), 10000):
            for final_newline in (False, True):
                args = {"path": 'é/ctrl\x01/"\\', "offset": offset, "limit": len(lines)}
                measures = fs_read.page_measures(
                    args["path"], offset, len(lines), total, final_newline, line_e)
                assert len(measures) == len(lines)
                for k, counts in enumerate(measures, 1):
                    value = candidate(args["path"], offset, len(lines), total,
                                      final_newline, lines, k)
                    compare(args, value, counts)
    compare({"path": "empty"}, empty, empty_counts)
    # A later finalized prefix may fit after an earlier one fails.
    caps = dict.fromkeys(domains, 50)
    assert fs_read.choose_k([dict.fromkeys(domains, n) for n in (83, 43, 83)], caps) == 2
    done(23)

    args = {"path": "three", "limit": 2}
    one = candidate("three", 1, 2, 3, True, ["a", "b"], 1)
    content, meta = reference.render("read", one)
    cap = reference.budget_measures(args, one, content, meta)["content"]
    assert 27 + reference.escaped_payload_bytes("a\nb") <= cap
    with patch.object(fs_read, "MAX_CONTENT_BYTES", cap):
        selected = fs_read.read_tool(args, tree.root)
    assert selected == one, (selected, one)
    done(24)

    peaks = []
    for name in ("newlines_1m", "wide"):
        tracemalloc.start()
        try:
            measured_value = fs_read.read_tool({"path": name}, tree.root)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        assert peak < 8 * 1024 * 1024, ("W5-R25", name, peak)
        if name == "newlines_1m":
            assert measured_value["total_lines"] == 1048576
            assert measured_value["final_newline"] is True
        else:
            assert measured_value["total_lines"] == 2000
        peaks.append(peak)
        print(f"[probe] W5-R25 {name}; peak_kib={peak / 1024:.3f}")
    # Offset past many chunks must still retain only the selected boundaries.
    for offset in (65535, 65536, 65537, 1048576):
        tail = fs_read.read_tool(
            {"path": "newlines_1m", "offset": offset, "limit": 2}, tree.root)
        assert tail["end_line"] == min(offset + 1, 1048576), tail
        assert tail["text"] == ("\n" if offset < 1048576 else ""), tail
    crossing = fs_read.read_tool(
        {"path": "wide", "offset": 126, "limit": 2}, tree.root)
    assert crossing["text"] == "\x01" * 523 + "\n" + "\x01" * 523, crossing
    assert (crossing["start_line"], crossing["end_line"]) == (126, 127), crossing
    done(25)

    wall = []
    def harness_result(payload):
        result = payload["tool_result"]
        assert payload["outcome"]["class"] == "success", payload
        assert result["status"] == "ok", result
        wall.append(result["usage"]["wall_ms"])

    with server_helper_scope(), setup_db() as fixture:
        run_harness_case(fixture, base,
                         read_spec(base / "read-wide-harness-spec", tree.root),
                         "read", {"path": "wide"},
                         lambda value: compare({"path": "wide"}, value,
                             fs_read.page_measures("wide", 1, 2000, 2000, False,
                                 [523 * 6] * value["end_line"])[-1]),
                         result_check=harness_result)
    assert len(wall) == 1
    done(26)

    dumps = json.dumps
    serialized = []
    def skeleton_dumps(obj, *args, **kwargs):
        encoded = dumps(obj, *args, **kwargs)
        if isinstance(obj, dict) and "text" in obj:
            assert obj["text"] == "", "W5-R27 serialized body in value"
        elif isinstance(obj, dict) and "result" in obj:
            assert obj["result"]["value"]["text"] == "", "W5-R27 serialized body in frame"
        else:
            raise AssertionError(("W5-R27 unexpected serialization", type(obj)))
        size = len(encoded.encode("utf-8"))
        assert size <= 4096 + fs_read.escaped_bytes_len(b"wide"), size
        serialized.append(size)
        return encoded

    with patch.object(fs_read.json, "dumps", side_effect=skeleton_dumps):
        value = fs_read.read_tool({"path": "wide"}, tree.root)
    assert 0 < len(serialized) <= 2 * 2000 + 8, len(serialized)
    done(27)

    digest = hashlib.sha256((PLUGINS / "fs_read.py").read_bytes()).hexdigest()
    artifact = Path(spec.entry.argv[1])
    assert digest == hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert digest == spec.artifact_digest == spec.entry.artifact_digest
    spec.entry.require_artifact()
    original = artifact.read_bytes()
    try:
        artifact.write_bytes(bytes([original[0] ^ 1]) + original[1:])
        try:
            spec.entry.require_artifact()
        except AdapterNotFound as exc:
            assert exc.reason == "artifact_digest_mismatch", exc
        else:
            raise AssertionError("W5-R28 accepted tampered artifact")
    finally:
        artifact.write_bytes(original)
    spec.entry.require_artifact()
    done(28)

    scan = fs_read._scan
    for same_size in (False, True):
        path = root / "three"
        before = path.stat()
        original = path.read_bytes()
        def changed_scan(*args, **kwargs):
            scanned = scan(*args, **kwargs)
            if same_size:
                path.write_bytes(b"z" + original[1:])
                os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
                assert path.stat().st_size == before.st_size
                assert path.stat().st_mtime_ns == before.st_mtime_ns
                assert path.stat().st_ctime_ns != before.st_ctime_ns
            else:
                with path.open("ab") as handle:
                    handle.write(b"x")
            return scanned
        try:
            with patch.object(fs_read, "_scan", side_effect=changed_scan):
                local_error(lambda: fs_read.read_tool({"path": "three"}, tree.root),
                            "io_error")
        finally:
            path.write_bytes(original)
    read_window = fs_read._read_window
    path = root / "three"
    original = path.read_bytes()
    def changed_window(*args, **kwargs):
        window = read_window(*args, **kwargs)
        path.write_bytes(b"z" + original[1:])
        return window
    try:
        with patch.object(fs_read, "_read_window", side_effect=changed_window):
            local_error(lambda: fs_read.read_tool({"path": "three"}, tree.root),
                        "io_error")
    finally:
        path.write_bytes(original)
    done(29)
    assert sorted(passed) == list(range(1, 30)), passed
    READ_EVIDENCE.update(read_artifact_sha256=digest, read_1m_wall_ms=wall[0],
                         read_peak_kib=f"{max(peaks) / 1024:.3f}",
                         permission_probe=permission_probe)
    print("[probe] W5-R01..R29 green")
    return len(passed)


def main() -> int:
    node = node_path()
    if node is None:
        print("[SKIP] W4 fs tools; node_missing")
        return 2
    with tempfile.TemporaryDirectory(prefix="w4b-tools-") as temp:
        base = Path(temp)
        portable = workspace(base / "portable", "portable")
        list_tree = workspace(base / "list", "list")
        assert portable.root and list_tree.root
        shim = list_tree.non_utf8_mode == "preload_shim"
        if shim and not preflight_shim(list_tree):
            print("[SKIP] W4 fs tools; preload_unavailable")
            return 2
        if not shim:
            assert list_tree.non_utf8_mode == "filesystem", list_tree
            names = set(os.listdir(os.fsencode(list_tree.root)))
            assert b"\xff" in names, names
        read_plugin = read_spec(base / "read", portable)
        list_plugin = node_spec(base / "listnode", list_tree)
        list_plugin_portable = node_spec(base / "listportable", portable)
        cases = 0
        read_cases = 0
        list_cases = 0
        search_cases = 0
        for case in READ_CASES:
            expected = case["expected"]
            if "error" in expected:
                expect_error(read_plugin, "read", case["args"], expected["error"])
            else:
                expect_value(read_plugin, "read", case["args"],
                             expected["value"])
            read_cases += 1
            cases += 1
        for index, case in enumerate(LIST_CASES):
            expected = case["expected"]
            spec = list_plugin if index < 5 else list_plugin_portable
            if "error" in expected:
                expect_error(spec, "list", case["args"], expected["error"])
            else:
                expect_value(spec, "list", case["args"], expected["value"])
            list_cases += 1
            cases += 1
        for case in SEARCH_INPUTS:
            tree = search_workspace(base / f"search-{uuid.uuid4().hex[:8]}",
                                    case["id"])
            assert tree.root
            spec = node_spec(base / f"searchspec-{uuid.uuid4().hex[:8]}", tree)
            expected = case["expected"]
            if "error" in expected:
                expect_error(spec, "search", case["args"], expected["error"])
            else:
                expect_value(spec, "search", case["args"], expected["value"])
            search_cases += 1
            cases += 1
        cases += path_differential(base, read_plugin, list_plugin)
        if shim:
            cases += shim_guard(base, list_tree)
        cases += selector_probe()
        read_probe_count = read_probes(base)
        cases += read_probe_count

        with server_helper_scope(), setup_db() as fixture:
            def check_read(value):
                assert value["text"] == "a"
            run_harness_case(fixture, base, read_spec(base / "hread", portable.root),
                             "read", {"path": "tail"}, check_read)
            def check_list(value):
                assert value["total"] == 3
            run_harness_case(fixture, base, node_spec(base / "hlist", list_tree.root),
                             "list", {"path": "."}, check_list)
            def check_search(value):
                assert value["total"] >= 1
            run_harness_case(fixture, base, node_spec(base / "hsearch", list_tree.root),
                             "search", {"query": "x"}, check_search)
            cases += 3

        budget = CONTRACT["tool.search_budget_file_count"]
        timing = CONTRACT["tool.search_budget_timing_m3_pending"]
        assert budget["expected"]["file_count_exceed"] == "search_scope_too_large"
        assert budget["expected"]["timing"] == "not_frozen"
        assert timing["status"] == "m3_pending"
        assert timing["expected"]["deterministic_w1_pass"] is False
        assert len(BUILTIN_PAGE_CONTRACTS) == 3
        for plugin in (PLUGINS / "fs_read.py", PLUGINS / "fs_tools.js"):
            source = plugin.read_text(encoding="utf-8")
            assert "W4B_" not in source, plugin
            assert "NODE_OPTIONS" not in source, plugin
            assert "w4b_non_utf8_preload" not in source, plugin
        linux_real = ("filesystem" if list_tree.non_utf8_mode == "filesystem"
                      else "not_run")
        print(f"[evidence] non_utf8_source={list_tree.non_utf8_mode}; "
              f"linux_real={linux_real}")
        print(
            f"[evidence] read_artifact_sha256={READ_EVIDENCE['read_artifact_sha256']}; "
            f"read_1m_wall_ms={READ_EVIDENCE['read_1m_wall_ms']}; "
            f"read_peak_kib={READ_EVIDENCE['read_peak_kib']}; "
            f"permission_probe={READ_EVIDENCE['permission_probe']}")
        print(
            f"[passed] W4 fs tools; cases={cases}; read={read_cases}; "
            f"read_probes={read_probe_count}; list={list_cases}; "
            f"search={search_cases}; pagination_converged=true; "
            f"page_contracts_imported=3")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
