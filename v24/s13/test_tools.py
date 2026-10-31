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
    DESCRIPTORS,
    PLUGINS,
    SEARCH_CASES,
    TOOL_CONTRACTS,
    V2Spec,
    node_spec,
    node_workspace,
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
    check_error(payload, code, spec.workspace)
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


MAX_SAFE_INTEGER = 2**53 - 1
DEFAULT_CAPS = {"value": 40960, "content": 41984, "meta": 4096,
                "frame": 60000}
JS_PROLOGUE = (
    "const m=require(process.argv[1]);"
    "const root=process.argv[2];"
    "function emit(fn,trace){try{const value=fn();"
    "console.log(JSON.stringify({ok:true,v:2,result:{value},"
    "trace:(trace===undefined?null:trace)}));}"
    "catch(e){if(e&&typeof e.code==='string'&&typeof e.message==='string'){"
    "console.log(JSON.stringify({ok:false,v:2,error:{code:e.code,message:e.message},"
    "trace:(trace===undefined?null:trace)}));}else{throw e;}}}"
)


def js_call(script, root="."):
    """Run a Node probe against the production plugin entry points."""
    process = subprocess.run(
        [node_path(), "-e", JS_PROLOGUE + script,
         str(PLUGINS / "fs_tools.js"), str(root)],
        capture_output=True, text=True, timeout=180)
    assert process.returncode == 0, (
        process.returncode, process.stdout, process.stderr)
    lines = process.stdout.splitlines()
    assert len(lines) == 1, (process.stdout, process.stderr)
    payload = json.loads(lines[0])
    assert payload.get("v") == 2, payload
    return payload


def check_error(payload, code, root):
    assert payload.get("ok") is False, payload
    assert payload.get("v") == 2, payload
    assert set(payload) - {"trace"} == {"ok", "v", "error"}, payload
    error = payload.get("error")
    assert isinstance(error, dict) and set(error) == {"code", "message"}, payload
    assert error["code"] == code, payload
    message = error["message"]
    assert isinstance(message, str) and message, payload
    assert len(message.encode("utf-8")) <= 1024, payload
    assert str(root) not in message, payload
    trace = payload.get("trace")
    if trace is not None:
        assert isinstance(trace, dict), payload
        assert set(trace) == {"stopReason", "nowCalls"}, payload
        assert trace["stopReason"] in ("eof", "sentinel", "file-cap",
                                       "time-cap"), payload
        assert type(trace["nowCalls"]) is int and trace["nowCalls"] >= 1, payload
    return payload


def js_value(script, root="."):
    payload = js_call(script, root)
    assert payload.get("ok") is True, payload
    assert set(payload["result"]) == {"value"}, payload
    return payload["result"]["value"]


def js_payload(script, root="."):
    payload = js_call(script, root)
    assert payload.get("ok") is True, payload
    assert set(payload["result"]) == {"value"}, payload
    return payload


def js_error(script, root, code):
    return check_error(js_call(script, root), code, root)


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


def search_probes(base, record=None):
    """W6-S01..S26: search cutoff, glob, integer and evidence probes."""
    import w1_reference as reference
    from v24.host.line_json import _classify_v2
    from v24.host.registry import AdapterNotFound
    from v24.host.tool_results import failure_output

    passed = []

    def done(number):
        assert number not in passed, number
        passed.append(number)

    def run(number, fn):
        label = f"S{number:02d}"
        try:
            fn()
        except Exception as exc:
            if record is None:
                raise
            record(label, "error", exc)
        else:
            done(number)
            if record is not None:
                record(label, "ok", None)

    def mk_tree(name, nodes):
        return node_workspace(base / f"w6s-{name}", nodes)

    def mk_spec(tree, name):
        return node_spec(base / f"w6s-spec-{name}", tree)

    def direct(spec, args):
        payload = invoke(spec, "search", args)
        assert payload.get("ok") is True, payload
        value = payload["result"]["value"]
        check_value(spec, "search", args, value)
        return value

    def js_success(script, tree, spec, args):
        payload = js_payload(script, tree.root)
        value = payload["result"]["value"]
        check_value(spec, "search", args, value)
        return value, payload.get("trace")

    empty_skipped = {"hidden": 0, "symlink": 0, "binary": 0, "too_large": 0,
                     "non_utf8": 0, "long_lines": 0}

    def hit(path, line=1, column=1, text="x"):
        return {"path": path, "line": line, "column": column, "text": text,
                "text_truncated": False}

    def s01():
        tree = mk_tree("s01", [
            {"kind": "file", "path": "a0.txt", "bytes_hex": "780a"},
            {"kind": "file", "path": "a1.txt", "bytes_hex": "780a"},
            {"kind": "directory", "path": ".",
             "recipe": {"regular_files": 9999, "name": "f%05d.txt",
                        "content_hex": "790a"}},
        ])
        spec = mk_spec(tree, "s01")
        value = direct(spec, {"query": "x", "limit": 2})
        assert value == {
            "path": ".", "offset": 1, "hits": [hit("a0.txt"), hit("a1.txt")],
            "total": 2, "complete": False, "scanned_files": 10000,
            "skipped": dict(empty_skipped), "truncated": True,
            "next_offset": 3}, value

    def s02():
        tree = mk_tree("s02", [
            {"kind": "file", "path": "a0.txt", "bytes_hex": "780a"},
            {"kind": "file", "path": "a1.txt", "bytes_hex": "780a"},
            {"kind": "file", "path": "a2.txt", "bytes_hex": "780a"},
            {"kind": "file", "path": "z.txt", "bytes_hex": "790a"},
        ])
        spec = mk_spec(tree, "s02")
        script = """
        emit(() => {
          const wide = m.searchTool({query:"x", limit:3}, root,
            {fileLimit:3, caps:{value:40960, content:41984, meta:4096, frame:60000}});
          const one = Object.assign({}, wide, {hits: wide.hits.slice(0,1),
            truncated:true, next_offset:2});
          const cap = Buffer.byteLength(JSON.stringify(one), 'utf8');
          return m.searchTool({query:"x", limit:3}, root,
            {fileLimit:3, caps:{value:cap}});
        });
        """
        value, _trace = js_success(script, tree, spec, {"query": "x", "limit": 3})
        assert value["hits"] == [hit("a0.txt")], value
        assert value["total"] == 3, value
        assert value["complete"] is False, value
        assert value["next_offset"] == 2, value
        assert value["scanned_files"] == 3, value

    def s03():
        tree = mk_tree("s03", [
            {"kind": "file", "path": "a0.txt", "bytes_hex": "780a"},
            {"kind": "file", "path": "y.txt", "bytes_hex": "790a"},
        ])
        js_error("emit(()=>m.searchTool({query:'x', limit:2}, root, "
                 "{fileLimit:1}));", tree.root, "search_scope_too_large")

    def s04():
        tree = mk_tree("s04", [
            {"kind": "file", "path": "a0.txt", "bytes_hex": "780a"},
            {"kind": "file", "path": "a1.txt", "bytes_hex": "780a"},
            {"kind": "file", "path": "a2.txt", "bytes_hex": "780a"},
            {"kind": "file", "path": "z.txt", "bytes_hex": "790a"},
        ])
        js_error("emit(()=>m.searchTool({query:'x', offset:5, limit:3}, root, "
                 "{fileLimit:3}));", tree.root, "search_scope_too_large")

    def s05():
        tree = mk_tree("s05", [
            {"kind": "file", "path": "a.txt", "bytes_hex": "790a"},
            {"kind": "file", "path": "b.txt", "bytes_hex": "790a"},
        ])
        js_error("emit(()=>m.searchTool({query:'none'}, root, "
                 "{fileLimit:1}));", tree.root, "search_scope_too_large")

    def time_tree(name):
        return mk_tree(name, [
            {"kind": "file", "path": "a0.txt", "bytes_hex": "780a"},
            {"kind": "file", "path": "a1.txt", "bytes_hex": "780a"},
            {"kind": "file", "path": "b0.txt", "bytes_hex": "790a"},
        ])

    def timed_search(tree, args, expire_at, limit=None):
        args_js = json.dumps(args)
        trace = "const trace={};let calls=0;"
        clock = (f"const now=()=>{{calls+=1;return calls>={expire_at}?1000000:0;}};")
        script = trace + clock + (
            f"emit(()=>m.searchTool({args_js}, root, "
            "{budgetMs:12000, now, trace}), trace);")
        return script

    def s06():
        tree = time_tree("s06")
        spec = mk_spec(tree, "s06")
        script = timed_search(tree, {"query": "x", "limit": 2}, 4)
        value, trace = js_success(script, tree, spec, {"query": "x", "limit": 2})
        assert value["hits"] == [hit("a0.txt"), hit("a1.txt")], value
        assert value["complete"] is False, value
        assert value["next_offset"] == 3, value
        assert value["scanned_files"] == 2, value
        assert trace == {"stopReason": "time-cap", "nowCalls": 4}, trace

    def s07():
        tree = time_tree("s07")
        script = timed_search(tree, {"query": "x", "limit": 3}, 4)
        payload = js_call(script, tree.root)
        check_error(payload, "search_scope_too_large", tree.root)
        assert payload["trace"] == {"stopReason": "time-cap", "nowCalls": 4}, payload

    def s08():
        tree = time_tree("s08")
        script = timed_search(tree, {"query": "x", "offset": 5}, 4)
        payload = js_call(script, tree.root)
        check_error(payload, "search_scope_too_large", tree.root)
        assert payload["trace"] == {"stopReason": "time-cap", "nowCalls": 4}, payload

    def s09():
        tree = mk_tree("s09", [
            {"kind": "file", "path": "a.txt", "bytes_hex": "790a"},
            {"kind": "file", "path": "b.txt", "bytes_hex": "790a"},
        ])
        script = timed_search(tree, {"query": "none"}, 3)
        payload = js_call(script, tree.root)
        check_error(payload, "search_scope_too_large", tree.root)
        assert payload["trace"] == {"stopReason": "time-cap", "nowCalls": 3}, payload

    def s10():
        one = mk_tree("s10a", [
            {"kind": "file", "path": "a0.txt", "bytes_hex": "780a"},
        ])
        spec = mk_spec(one, "s10a")
        script = timed_search(one, {"query": "x"}, 3)
        value, trace = js_success(script, one, spec, {"query": "x"})
        assert value["complete"] is True and value["total"] == 1, value
        assert trace == {"stopReason": "eof", "nowCalls": 2}, trace
        two = mk_tree("s10b", [
            {"kind": "file", "path": "a0.txt", "bytes_hex": "780a"},
            {"kind": "file", "path": "a1.txt", "bytes_hex": "780a"},
        ])
        script = timed_search(two, {"query": "x"}, 3)
        payload = js_call(script, two.root)
        check_error(payload, "search_scope_too_large", two.root)
        assert payload["trace"] == {"stopReason": "time-cap", "nowCalls": 3}, payload

    def s11():
        tree = mk_tree("s11", [
            {"kind": "file", "path": "a0.txt", "bytes_hex": "780a"},
            {"kind": "file", "path": "a1.txt", "bytes_hex": "780a"},
            {"kind": "file", "path": "a2.txt", "bytes_hex": "780a"},
            {"kind": "file", "path": "b0.txt", "bytes_hex": "790a"},
        ])
        spec = mk_spec(tree, "s11")
        script = timed_search(tree, {"query": "x", "limit": 2}, 5)
        value, trace = js_success(script, tree, spec, {"query": "x", "limit": 2})
        assert value["hits"] == [hit("a0.txt"), hit("a1.txt")], value
        assert value["next_offset"] == 3 and value["total"] == 3, value
        assert value["scanned_files"] == 3, value
        assert trace == {"stopReason": "sentinel", "nowCalls": 4}, trace

    def s12():
        tree = mk_tree("s12a", [
            {"kind": "file", "path": "a0.txt", "bytes_hex": "780a"},
            {"kind": "file", "path": "z.txt", "bytes_hex": "790a"},
        ])
        script = """
        emit(() => {
          const args={query:"x"};
          const wide=m.searchTool(args, root,
            {caps:{value:40960, content:41984, meta:4096, frame:60000}});
          const valueCap=Buffer.byteLength(JSON.stringify(wide), 'utf8');
          const contentCap=27+(Buffer.byteLength(JSON.stringify(m.searchText(wide)), 'utf8')-2);
          const frameCap=Buffer.byteLength(JSON.stringify({ok:true,v:2,result:{value:wide}}), 'utf8')+1;
          const caps={value:valueCap-1, content:contentCap-1, meta:1, frame:frameCap-1};
          const out={};
          for (const [domain,cap] of Object.entries(caps)) {
            try { m.searchTool(args, root, {caps:{[domain]:cap}}); out[domain]="no_error"; }
            catch (e) { out[domain]=e.code; }
          }
          try { m.searchTool(args, root, {fileLimit:1, caps:{value:1}});
                out.file_limit="no_error"; }
          catch (e) { out.file_limit=e.code; }
          return out;
        });
        """
        got = js_value(script, tree.root)
        for domain in ("value", "content", "meta", "frame", "file_limit"):
            assert got.get(domain) == "hit_too_large", (domain, got)
        empty = mk_tree("s12b", [])
        script = """
        emit(() => {
          const args={query:"x"};
          const wide=m.searchTool(args, root,
            {caps:{value:40960, content:41984, meta:4096, frame:60000}});
          const valueCap=Buffer.byteLength(JSON.stringify(wide), 'utf8');
          const contentCap=27+(Buffer.byteLength(JSON.stringify(m.searchText(wide)), 'utf8')-2);
          const frameCap=Buffer.byteLength(JSON.stringify({ok:true,v:2,result:{value:wide}}), 'utf8')+1;
          const caps={value:valueCap-1, content:contentCap-1, meta:1, frame:frameCap-1};
          const out={};
          for (const [domain,cap] of Object.entries(caps)) {
            try { m.searchTool(args, root, {caps:{[domain]:cap}}); out[domain]="no_error"; }
            catch (e) { out[domain]=e.code; }
          }
          try { m.searchTool({query:"x", offset:2}, root, {caps:{value:valueCap-1}});
                out.offset2="no_error"; }
          catch (e) { out.offset2=e.code; }
          return out;
        });
        """
        got = js_value(script, empty.root)
        for domain in ("value", "content", "meta", "frame"):
            assert got.get(domain) == "output_too_large", (domain, got)
        assert got.get("offset2") == "offset_out_of_range", got

    def glob_tree(name):
        return mk_tree(name, [
            {"kind": "file", "path": "src/a.py", "bytes_hex": "780a"},
            {"kind": "file", "path": "src/sub/a.py", "bytes_hex": "780a"},
            {"kind": "file", "path": "b.txt", "bytes_hex": "780a"},
        ])

    def s13():
        tree = glob_tree("s13")
        spec = mk_spec(tree, "s13")
        value = direct(spec, {"query": "x", "glob": "*.py"})
        assert [item["path"] for item in value["hits"]] == [
            "src/a.py", "src/sub/a.py"], value
        value = direct(spec, {"query": "x", "glob": "*.txt"})
        assert [item["path"] for item in value["hits"]] == ["b.txt"], value

    def s14():
        tree = glob_tree("s14")
        spec = mk_spec(tree, "s14")
        value = direct(spec, {"query": "x", "glob": "src/*.py"})
        assert [item["path"] for item in value["hits"]] == ["src/a.py"], value
        value = direct(spec, {"query": "x", "glob": "src/**/a.py"})
        assert [item["path"] for item in value["hits"]] == [
            "src/a.py", "src/sub/a.py"], value

    def s15():
        tree = mk_tree("s15", [
            {"kind": "file", "path": "é.txt", "bytes_hex": "780a"},
            {"kind": "file", "path": "a/b.txt", "bytes_hex": "780a"},
        ])
        spec = mk_spec(tree, "s15")
        value = direct(spec, {"query": "x", "glob": "?.txt"})
        assert [item["path"] for item in value["hits"]] == [
            "a/b.txt", "é.txt"], value
        value = direct(spec, {"query": "x", "glob": "a/**/b.txt"})
        assert [item["path"] for item in value["hits"]] == ["a/b.txt"], value

    def s16():
        tree = mk_tree("s16", [
            {"kind": "file", "path": "a.txt", "bytes_hex": "780a"},
        ])
        spec = mk_spec(tree, "s16")
        codes = {}
        for tool, base_args in (("list", {}), ("search", {"query": "x"})):
            for key in ("offset", "limit"):
                args = dict(base_args)
                args[key] = 9007199254740993
                payload = invoke(spec, tool, args)
                codes[f"{tool}_{key}"] = payload.get("error", {}).get("code")
        assert codes == {"list_offset": "invalid_path",
                         "list_limit": "invalid_path",
                         "search_offset": "invalid_path",
                         "search_limit": "invalid_path"}, codes
        script = """
        emit(() => {
          const out={};
          try { m.listTool({offset:9007199254740981, limit:200}, root); }
          catch (e) { out.list=e.code; }
          try { m.searchTool({query:"x", offset:9007199254740981, limit:200}, root); }
          catch (e) { out.search=e.code; }
          return out;
        });
        """
        got = js_value(script, tree.root)
        assert got == {"list": "offset_out_of_range",
                       "search": "offset_out_of_range"}, got
        js_error("emit(()=>m.addSafe(9007199254740991, 1));", tree.root,
                 "invalid_tool_output")
        script = """
        emit(() => {
          const out={};
          try {
            m.listText({path:".", offset:9007199254740991,
              entries:[{path:"a",kind:"file",size:1},
                       {path:"b",kind:"file",size:1}],
              total:3, truncated:true, next_offset:null,
              skipped_non_utf8:0, skipped_special:0});
          } catch (e) { out.list=e.code; }
          try {
            m.searchText({path:".", offset:9007199254740991,
              hits:[{path:"a",line:1,column:1,text:"x",text_truncated:false},
                    {path:"b",line:1,column:1,text:"x",text_truncated:false}],
              total:3, complete:false, scanned_files:0,
              skipped:{hidden:0,symlink:0,binary:0,too_large:0,non_utf8:0,long_lines:0},
              truncated:true, next_offset:null});
          } catch (e) { out.search=e.code; }
          return out;
        });
        """
        got = js_value(script, tree.root)
        assert got == {"list": "invalid_tool_output",
                       "search": "invalid_tool_output"}, got

    def s17():
        tree = mk_tree("s17", [
            {"kind": "file", "path": "a.txt", "bytes_hex": "780a"},
            {"kind": "file", "path": "b.log", "bytes_hex": "780a"},
            {"kind": "file", "path": "c.log", "bytes_hex": "780a"},
        ])
        spec = mk_spec(tree, "s17")
        value = direct(spec, {"query": "x", "glob": "*.txt"})
        assert [item["path"] for item in value["hits"]] == ["a.txt"], value
        assert value["scanned_files"] == 3, value
        js_error("emit(()=>m.searchTool({query:'x', glob:'*.txt'}, root, "
                 "{fileLimit:2}));", tree.root, "search_scope_too_large")

    def s18():
        tree = mk_tree("s18", [
            {"kind": "file", "path": "big",
             "recipe": {"repeat_hex": "00", "count": 1048577}},
            {"kind": "file", "path": "binnul", "bytes_hex": "00ff"},
            {"kind": "file", "path": "badutf", "bytes_hex": "ff" + "61" * 4097},
            {"kind": "file", "path": "long", "bytes_hex": "61" * 4097},
            {"kind": "file", "path": "ok.txt", "bytes_hex": "780a"},
        ])
        spec = mk_spec(tree, "s18")
        value = direct(spec, {"query": "x"})
        assert value["skipped"] == {
            "too_large": 1, "binary": 1, "non_utf8": 1, "long_lines": 1,
            "hidden": 0, "symlink": 0}, value
        assert value["scanned_files"] == 1 and value["total"] == 1, value

    def s19():
        tree = mk_tree("s19", [
            {"kind": "file", "path": "longfirst",
             "bytes_hex": "780a" + "61" * 4097},
        ])
        spec = mk_spec(tree, "s19")
        value = direct(spec, {"query": "x"})
        assert value["skipped"]["long_lines"] == 1, value
        assert value["scanned_files"] == 0, value
        assert value["total"] == 0 and value["complete"] is True, value

    def s20():
        tree = mk_tree("s20", [
            {"kind": "file", "path": "a.txt", "bytes_hex": "63310a780a6333"},
        ])
        spec = mk_spec(tree, "s20")
        args = {"query": "x", "context": 1}
        value = direct(spec, args)
        content, meta = RENDERERS.render(
            spec.entry.tool_for("search").render, args, value)
        text = content[0]["text"]
        assert text == ("a.txt-1- c1\na.txt:2:1: x\na.txt-3- c3"
                        "\n\n[hits 1-1 of 1; scanned 1; skipped 0]"), text
        measures = reference.budget_measures(
            args, value, content, meta)
        assert measures["content"] == 27 + reference.escaped_payload_bytes(text), (
            measures, text)

    def s21():
        tree = mk_tree("s21", [
            {"kind": "file", "path": "a.txt", "bytes_hex": "f09f9880f09f9880780a"},
            {"kind": "file", "path": "b.txt", "bytes_hex": "c3a9780a"},
        ])
        spec = mk_spec(tree, "s21")
        value = direct(spec, {"query": "x"})
        columns = {item["path"]: item["column"] for item in value["hits"]}
        assert columns == {"a.txt": 3, "b.txt": 2}, columns

    def s22():
        tree = mk_tree("s22", [
            {"kind": "file", "path": "long.txt",
             "bytes_hex": "78" + "f09f9880" * 500 + "0a"},
            {"kind": "file", "path": "edge.txt",
             "bytes_hex": "78" + "f09f9880" * 499 + "0a"},
        ])
        spec = mk_spec(tree, "s22")
        value = direct(spec, {"query": "x"})
        hits = {item["path"]: item for item in value["hits"]}
        assert len(hits["long.txt"]["text"]) == 500, hits
        assert len(hits["edge.txt"]["text"]) == 500, hits
        assert hits["long.txt"]["text_truncated"] is True, hits
        assert hits["edge.txt"]["text_truncated"] is False, hits

    def s23():
        tree = mk_tree("s23", [
            {"kind": "file", "path": ".git/x.txt", "bytes_hex": "780a"},
            {"kind": "file", "path": ".hidden/y.txt", "bytes_hex": "780a"},
            {"kind": "file", "path": ".hid.txt", "bytes_hex": "780a"},
            {"kind": "file", "path": "vis.txt", "bytes_hex": "780a"},
        ])
        spec = mk_spec(tree, "s23")
        value = direct(spec, {"query": "x"})
        assert value["skipped"]["hidden"] == 2, value
        assert value["total"] == 1, value
        value = direct(spec, {"query": "x", "include_hidden": True})
        assert value["skipped"]["hidden"] == 0, value
        assert value["total"] == 3, value
        assert not any(item["path"].startswith(".git") for item in value["hits"])

    def s24():
        source_path = PLUGINS / "fs_tools.js"
        source = source_path.read_text(encoding="utf-8")
        assert DESCRIPTORS["search"]["tool"]["limits"]["timeout_ms"] == 15000
        assert (DESCRIPTORS["search"]["tool"]["limits"]["timeout_ms"]
                - 12000 >= 3000)
        lines = source.splitlines()

        def span(name):
            start = next(index for index, line in enumerate(lines)
                         if line.startswith(f"function {name}("))
            end = next((index for index in range(start + 1, len(lines))
                        if lines[index].startswith("function ")), len(lines))
            return start, end

        root_span = span("rootPath")
        search_span = span("searchTool")
        for index, line in enumerate(lines):
            if "process.env" in line:
                assert root_span[0] <= index < root_span[1], (index, line)
            if "hrtime" in line or "Date.now" in line:
                assert search_span[0] <= index < search_span[1], (index, line)
        tree = mk_tree("s24", [
            {"kind": "file", "path": "a.txt", "bytes_hex": "780a"},
        ])
        spec = mk_spec(tree, "s24")
        digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
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
                raise AssertionError("W6-S24 accepted tampered artifact")
        finally:
            artifact.write_bytes(original)
        spec.entry.require_artifact()
        for code in ("output_too_large", "invalid_tool_output"):
            raw = json.dumps(
                {"ok": False, "v": 2,
                 "error": {"code": code, "message": "tool output exceeds the budget"}},
                separators=(",", ":")).encode("utf-8") + b"\n"
            kind, error = _classify_v2(raw, operation="invoke", exit_code=3)
            assert kind == "known_error" and error["code"] == code, (kind, error)
            output = failure_output(code, "tool output exceeds the budget",
                                    [{"type": "text", "text": "x"}])
            assert output["error"]["code"] == code, output
        payload = js_payload(
            "emit(()=>({budget:m.SCAN_BUDGET_MS, addSafe:typeof m.addSafe, "
            "search:typeof m.searchTool, list:typeof m.listTool, "
            "emptyMeasures:typeof m.emptyMeasures}));")
        value = payload["result"]["value"]
        assert value.get("budget") == 12000, value
        assert value.get("addSafe") == "function", value
        assert value.get("emptyMeasures") == "function", value
        assert value.get("search") == "function", value
        assert value.get("list") == "function", value

    def s25():
        tree = mk_tree("s25", [
            {"kind": "directory", "path": ".",
             "recipe": {"regular_files": 10000, "name": "f%05d.txt",
                        "content_hex": "790a"}},
        ])
        script = """
        emit(() => {
          const t0=process.hrtime.bigint();
          let outcome="complete_empty", value=null;
          try { value=m.searchTool({query:"x"}, root, {budgetMs:50}); }
          catch (e) {
            if (e.code==="search_scope_too_large") outcome="scope";
            else throw e;
          }
          const elapsed=Number(process.hrtime.bigint()-t0)/1e6;
          return {outcome, elapsed_ms:elapsed, value};
        });
        """
        got = js_value(script, tree.root)
        assert got["outcome"] in ("complete_empty", "scope"), got
        if got["outcome"] == "complete_empty":
            assert got["value"] == {
                "path": ".", "offset": 1, "hits": [], "total": 0,
                "complete": True, "scanned_files": 10000,
                "skipped": dict(empty_skipped), "truncated": False,
                "next_offset": None}, got
        elapsed = got["elapsed_ms"]
        overshoot = max(0.0, elapsed - 50.0)
        print(f"[probe] W6-S25 real_clock_elapsed_ms={elapsed:.3f}; "
              f"overshoot_ms={overshoot:.3f}")

    def s26():
        lines = ["a" * 3999 + "x"] * 5
        nodes = [{"kind": "file", "path": f"f{index:03d}.txt",
                  "recipe": {"lines": lines, "final_newline": True}}
                 for index in range(200)]
        tree = mk_tree("s26", nodes)
        spec = mk_spec(tree, "s26")
        args = {"query": "x", "context": 2, "limit": 200}
        script = """
        emit(() => {
          const original=JSON.stringify;
          let count=0;
          JSON.stringify=function(...args){count+=1;return original.apply(JSON,args);};
          let value=null;
          const t0=process.hrtime.bigint();
          try {
            value=m.searchTool({query:"x", context:2, limit:200}, root,
              {caps:{value:40960, content:41984, meta:4096, frame:60000}});
          } finally {
            JSON.stringify=original;
          }
          const elapsed=Number(process.hrtime.bigint()-t0)/1e6;
          return {count, elapsed_ms:elapsed, value};
        });
        """
        got = js_value(script, tree.root)
        value = got["value"]
        check_value(spec, "search", args, value)
        assert len(value["hits"]) < 200, len(value["hits"])
        assert got["count"] == 600, got["count"]
        print(f"[probe] W6-S26 enum_cost_wall_ms={got['elapsed_ms']:.3f}; "
              f"json_stringify_count={got['count']}")

    run(1, s01)
    run(2, s02)
    run(3, s03)
    run(4, s04)
    run(5, s05)
    run(6, s06)
    run(7, s07)
    run(8, s08)
    run(9, s09)
    run(10, s10)
    run(11, s11)
    run(12, s12)
    run(13, s13)
    run(14, s14)
    run(15, s15)
    run(16, s16)
    run(17, s17)
    run(18, s18)
    run(19, s19)
    run(20, s20)
    run(21, s21)
    run(22, s22)
    run(23, s23)
    run(24, s24)
    run(25, s25)
    run(26, s26)
    if record is None:
        assert sorted(passed) == list(range(1, 27)), passed
        print("[probe] W6-S01..S26 green")
    return len(passed)


def list_probes(base, record=None):
    """W6-L01..L11: list pagination, caps, scan accounting and rendering."""
    import w1_reference as reference

    passed = []

    def done(number):
        assert number not in passed, number
        passed.append(number)

    def run(number, fn):
        label = f"L{number:02d}"
        try:
            fn()
        except Exception as exc:
            if record is None:
                raise
            record(label, "error", exc)
        else:
            done(number)
            if record is not None:
                record(label, "ok", None)

    def mk_tree(name, nodes):
        return node_workspace(base / f"w6l-{name}", nodes)

    def mk_spec(tree, name):
        return node_spec(base / f"w6l-spec-{name}", tree)

    def direct(spec, args):
        payload = invoke(spec, "list", args)
        assert payload.get("ok") is True, payload
        value = payload["result"]["value"]
        check_value(spec, "list", args, value)
        return value

    def l01():
        names = [("f%03d" % index) + "a" * 251 for index in range(200)]
        tree = mk_tree("l01", [
            {"kind": "directory", "path": ".",
             "recipe": {"regular_files": 200,
                        "name": "f%03d" + "a" * 251,
                        "content_hex": "780a"}},
        ])
        spec = mk_spec(tree, "l01")
        entries = [{"path": name, "kind": "file", "size": 1} for name in names]
        values = []
        for count in range(1, 201):
            truncated = count < 200
            values.append({
                "path": ".", "offset": 1, "entries": entries[:count],
                "total": 200, "truncated": truncated,
                "next_offset": count + 1 if truncated else None,
                "skipped_non_utf8": 0, "skipped_special": 0})
        expected = reference.select_prefix(
            "list", {"limit": 500}, values, dict(DEFAULT_CAPS))
        assert expected is not None and 0 < expected < 500, expected
        value = direct(spec, {"limit": 500})
        assert len(value["entries"]) == expected, (value, expected)
        assert value["total"] == 200, value
        assert value["next_offset"] == expected + 1, (value, expected)
        second = direct(spec, {"limit": 500, "offset": expected + 1})
        assert second["total"] == 200, second
        assert second["entries"], second
        assert second["next_offset"] is None or second["next_offset"] > expected + 1

    def l02():
        tree = mk_tree("l02a", [
            {"kind": "file", "path": "a.txt", "bytes_hex": "780a"},
        ])
        script = """
        emit(() => {
          const v=m.listTool({}, root);
          const valueCap=Buffer.byteLength(JSON.stringify(v), 'utf8');
          const contentCap=27+(Buffer.byteLength(JSON.stringify(m.listText(v)), 'utf8')-2);
          const frameCap=Buffer.byteLength(JSON.stringify({ok:true,v:2,result:{value:v}}), 'utf8')+1;
          const caps={value:valueCap-1, content:contentCap-1, meta:1, frame:frameCap-1};
          const out={};
          for (const [domain,cap] of Object.entries(caps)) {
            try { m.listTool({}, root, {caps:{[domain]:cap}}); out[domain]="no_error"; }
            catch (e) { out[domain]=e.code; }
          }
          return out;
        });
        """
        got = js_value(script, tree.root)
        for domain in ("value", "content", "meta", "frame"):
            assert got.get(domain) == "entry_too_large", (domain, got)
        empty = mk_tree("l02b", [])
        script = """
        emit(() => {
          const v=m.listTool({}, root);
          const valueCap=Buffer.byteLength(JSON.stringify(v), 'utf8');
          const contentCap=27+(Buffer.byteLength(JSON.stringify(m.listText(v)), 'utf8')-2);
          const frameCap=Buffer.byteLength(JSON.stringify({ok:true,v:2,result:{value:v}}), 'utf8')+1;
          const caps={value:valueCap-1, content:contentCap-1, meta:1, frame:frameCap-1};
          const out={};
          for (const [domain,cap] of Object.entries(caps)) {
            try { m.listTool({}, root, {caps:{[domain]:cap}}); out[domain]="no_error"; }
            catch (e) { out[domain]=e.code; }
          }
          try { m.listTool({offset:2}, root, {caps:{value:valueCap-1}});
                out.offset2="no_error"; }
          catch (e) { out.offset2=e.code; }
          return out;
        });
        """
        got = js_value(script, empty.root)
        for domain in ("value", "content", "meta", "frame"):
            assert got.get(domain) == "output_too_large", (domain, got)
        assert got.get("offset2") == "offset_out_of_range", got

    def l03():
        tree = mk_tree("l03a", [
            {"kind": "file", "path": ".git/x", "bytes_hex": "780a"},
            {"kind": "file", "path": "d/.git/y", "bytes_hex": "780a"},
            {"kind": "file", "path": "d/f", "bytes_hex": "780a"},
        ])
        spec = mk_spec(tree, "l03a")
        value = direct(spec, {"recursive": True})
        assert [item["path"] for item in value["entries"]] == ["d", "d/f"], value
        assert value["total"] == 2, value
        wide = mk_tree("l03c1", [
            {"kind": "directory", "path": ".",
             "recipe": {"regular_files": 10000, "name": "f%05d.txt",
                        "content_hex": "780a"}},
        ])
        value = direct(mk_spec(wide, "l03c1"), {"limit": 1})
        assert value["total"] == 10000, value
        assert len(value["entries"]) == 1, value
        over = mk_tree("l03c2", [
            {"kind": "file", "path": ".hidden", "bytes_hex": "780a"},
            {"kind": "directory", "path": ".",
             "recipe": {"regular_files": 10000, "name": "f%05d.txt",
                        "content_hex": "780a"}},
        ])
        expect_error(mk_spec(over, "l03c2"), "list", {"limit": 1},
                     "directory_too_large")
        got = js_value(
            "emit(()=>m.listTool({recursive:true}, root, {scanLimit:4}));",
            tree.root)
        assert got["total"] == 2, got
        js_error("emit(()=>m.listTool({recursive:true}, root, {scanLimit:3}));",
                 tree.root, "directory_too_large")

    def l04():
        tree = mk_tree("l04", [
            {"kind": "file", "path": ".h/a", "bytes_hex": "780a"},
            {"kind": "file", "path": ".h/b", "bytes_hex": "780a"},
            {"kind": "file", "path": "vis", "bytes_hex": "780a"},
        ])
        spec = mk_spec(tree, "l04")
        value = direct(spec, {"recursive": True})
        assert value["total"] == 1, value
        value = direct(spec, {"recursive": True, "include_hidden": True})
        assert value["total"] == 4, value
        assert [item["path"] for item in value["entries"]] == [
            ".h", ".h/a", ".h/b", "vis"], value

    def l05():
        tree = mk_tree("l05", [
            {"kind": "file", "path": "d/f", "bytes_hex": "780a"},
            {"kind": "symlink", "path": "dlink", "target": "d"},
            {"kind": "symlink", "path": "flink", "target": "f"},
        ])
        spec = mk_spec(tree, "l05")
        value = direct(spec, {"recursive": True})
        entries = {item["path"]: item for item in value["entries"]}
        assert set(entries) == {"d", "d/f", "dlink", "flink"}, entries
        assert entries["d"]["kind"] == "directory", entries
        assert entries["d/f"]["kind"] == "file", entries
        assert entries["dlink"]["kind"] == "symlink"
        assert entries["flink"]["kind"] == "symlink"
        assert entries["dlink"]["size"] is None and entries["flink"]["size"] is None
        assert "dlink/f" not in entries, entries

    def l06():
        tree = mk_tree("l06", [{"kind": "special", "path": "fifo"}])
        spec = mk_spec(tree, "l06")
        value = direct(spec, {})
        assert value["skipped_special"] == 1, value
        assert value["entries"] == [] and value["total"] == 0, value

    def l07():
        tree = workspace(base / "w6l-l07", "list")
        spec = mk_spec(tree, "l07")
        value = direct(spec, {})
        assert value["skipped_non_utf8"] == 1, value
        assert value["skipped_special"] == 1, value
        assert [item["path"] for item in value["entries"]] == [
            "a", "b", "c"], value
        assert value["total"] == 3, value

    def l08():
        tree = mk_tree("l08", [
            {"kind": "file", "path": "B", "bytes_hex": "780a"},
            {"kind": "directory", "path": "a"},
            {"kind": "file", "path": "a/c", "bytes_hex": "780a"},
            {"kind": "file", "path": "a-b", "bytes_hex": "780a"},
            {"kind": "file", "path": "é", "bytes_hex": "780a"},
            {"kind": "file", "path": "～", "bytes_hex": "780a"},
            {"kind": "file", "path": "😀", "bytes_hex": "780a"},
        ])
        spec = mk_spec(tree, "l08")
        value = direct(spec, {"recursive": True})
        assert [item["path"] for item in value["entries"]] == [
            "B", "a", "a-b", "a/c", "é", "～", "😀"], value
        value = direct(spec, {})
        assert [item["path"] for item in value["entries"]] == [
            "B", "a", "a-b", "é", "～", "😀"], value

    def l09():
        tree = mk_tree("l09", [
            {"kind": "file", "path": "a", "bytes_hex": "780a"},
            {"kind": "file", "path": "b", "bytes_hex": "780a"},
            {"kind": "file", "path": "c", "bytes_hex": "780a"},
        ])
        spec = mk_spec(tree, "l09")
        value = direct(spec, {"offset": 3, "limit": 500})
        assert len(value["entries"]) == 1, value
        assert value["truncated"] is False, value
        assert value["next_offset"] is None, value
        expect_error(spec, "list", {"offset": 4}, "offset_out_of_range")
        empty = mk_tree("l09-empty", [])
        empty_spec = mk_spec(empty, "l09-empty")
        value = direct(empty_spec, {})
        assert value["entries"] == [] and value["total"] == 0, value
        expect_error(empty_spec, "list", {"offset": 2}, "offset_out_of_range")

    def l10():
        tree = mk_tree("l10", [
            {"kind": "file", "path": "a", "bytes_hex": "780a"},
            {"kind": "file", "path": "b", "bytes_hex": "780a"},
            {"kind": "directory", "path": "d"},
        ])
        spec = mk_spec(tree, "l10")
        implicit = direct(spec, {})
        explicit = direct(spec, {
            "path": ".", "recursive": False, "include_hidden": False,
            "offset": 1, "limit": 500})
        assert json.dumps(implicit, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":")) == json.dumps(
            explicit, sort_keys=True, ensure_ascii=False,
            separators=(",", ":")), (implicit, explicit)
        assert implicit["total"] == 3, implicit
        assert implicit["truncated"] is False, implicit
        assert implicit["next_offset"] is None, implicit

    def l11():
        def check(spec, args, expected_text):
            value = direct(spec, args)
            content, meta = RENDERERS.render(
                spec.entry.tool_for("list").render, args, value)
            text = reference.render("list", value)[0][0]["text"]
            assert text == expected_text, (text, expected_text)
            measures = reference.budget_measures(args, value, content, meta)
            assert measures["content"] == (
                27 + reference.escaped_payload_bytes(text)), (measures, text)
            assert not text.endswith("\n"), text
            return value

        tree = mk_tree("l11", [
            {"kind": "file", "path": "a", "bytes_hex": "78"},
            {"kind": "file", "path": "b", "bytes_hex": "78"},
            {"kind": "file", "path": "c", "bytes_hex": "78"},
        ])
        spec = mk_spec(tree, "l11")
        check(spec, {}, "a (1 B)\nb (1 B)\nc (1 B)")
        value = check(spec, {"limit": 2},
                      "a (1 B)\nb (1 B)\n\n[Showing 1-2 of 3. "
                      "Use offset=3 to continue.]")
        assert value["next_offset"] == 3, value
        empty = mk_tree("l11-empty", [])
        check(mk_spec(empty, "l11-empty"), {}, "[empty directory]")

    run(1, l01)
    run(2, l02)
    run(3, l03)
    run(4, l04)
    run(5, l05)
    run(6, l06)
    run(7, l07)
    run(8, l08)
    run(9, l09)
    run(10, l10)
    run(11, l11)
    if record is None:
        assert sorted(passed) == list(range(1, 12)), passed
        print("[probe] W6-L01..L11 green")
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
        list_probe_count = list_probes(base)
        cases += list_probe_count
        search_probe_count = search_probes(base)
        cases += search_probe_count

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
            f"list_probes={list_probe_count}; search={search_cases}; "
            f"search_probes={search_probe_count}; pagination_converged=true; "
            f"page_contracts_imported=3")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
