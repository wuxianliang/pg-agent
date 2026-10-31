"""W4b filesystem tool gate: read, list, search and page convergence.

The vector cases run real approved-plugin subprocesses.  A smaller DB-backed
section reuses ``v24/s11/plugin_fixtures.PluginHarness`` to prove the same
tools through the host dispatcher.  No provider socket is opened and no real
provider is constructed.
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
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
    search_workspace,
    spawn_count,
    workspace,
)
from plugin_fixtures import final_reply  # noqa: E402
from setup_db import server_helper_scope, setup_db  # noqa: E402
from v24.host.deepseek import _v2_provider_name  # noqa: E402
from v24.host.tool_pages import BUILTIN_PAGE_CONTRACTS, validate_page  # noqa: E402

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
                     value_check):
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
            f"[passed] W4 fs tools; cases={cases}; read={read_cases}; "
            f"list={list_cases}; search={search_cases}; "
            f"pagination_converged=true; page_contracts_imported=3")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
