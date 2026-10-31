"""W4a dispatch wiring gate: provider projection, worker text, v2 dispatcher.

Segments:
1. provider projection bytes and v1-byte baseline (no DB);
2. handler normalization (no DB) and the two non-handler worker branches (DB);
3. pre-spawn v2 failures with a process-count sentinel and the stub spawn log;
4. one real v2 subprocess lifecycle with the 11-byte model-text vector.

DB-backed segments use a local PostgreSQL test database and local subprocesses
only.  No provider socket is opened and no real provider is constructed.
"""
from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
V24 = ROOT / "v24"
S11 = V24 / "s11"
for _path in (S11, V24 / "s1", V24 / "s2", V24 / "s4", ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from setup_db import server_helper_scope, setup_db  # noqa: E402

from plugin_fixtures import (  # noqa: E402
    PluginHarness,
    build_registry,
    build_spec,
    final_reply,
    tool_reply,
)
from v24.host import line_json  # noqa: E402
from v24.host.canonical import compact_json  # noqa: E402
from v24.host.deepseek import (  # noqa: E402
    AdapterFailure, DeepSeekAdapter, _v2_provider_name,
)
from v24.host.plugins import PluginDispatcher  # noqa: E402
from v24.host.registry import (  # noqa: E402
    ApprovedAdapterRegistry,
    ApprovedPlugin,
    ApprovedTool,
    adapter_declaration_digest,
)
from v24.host.tool_results import (  # noqa: E402
    ToolDispatchResult,
    assert_failure_output,
    assert_success_output,
    assert_unknown_output,
    join_content,
)
from v24.host.worker import _call_tool_handler  # noqa: E402

VECTORS = HERE / "vectors"
STUB = HERE / "w4_stub_plugin.py"
DESCRIPTOR_DOC = json.loads(
    (VECTORS / "descriptor_v2.json").read_text(encoding="utf-8"))
DESCRIPTORS = {
    case["id"].rsplit(".", 1)[-1]: case["input"]
    for case in DESCRIPTOR_DOC["cases"]
    if case["id"].startswith("descriptor.v2.")
}
READ_DESCRIPTOR = DESCRIPTORS["read"]
SCENARIOS = ("ok", "known_error", "bad_frame", "extra_frame", "no_lf",
             "timeout", "nonempty_meta", "bad_value", "bad_relation",
             "huge_value", "crash")
LEASE_SENTINEL = "2000-01-01T00:00:00+00:00"
COUNTER = {"cases": 0}
DISPATCH_KEYS = {
    "claim", "kind", "ordinal", "outcome", "parent_effect_id", "reason",
    "request", "tool_message", "tool_result",
}
MESSAGE_KEYS = {"role", "tool_call_id", "content"}


def expect_adapter_failure(fn, reason):
    try:
        fn()
    except AdapterFailure as exc:
        assert exc.reason == reason, (reason, exc.reason)
        return
    raise AssertionError(f"expected AdapterFailure({reason!r})")


def v2_tool(descriptor):
    return ApprovedTool.from_descriptor(descriptor, key=descriptor["tool"]["key"])


def v2_tool_reply(call_id, tool_key, args):
    """A scripted provider reply using the v2 provider-visible name."""
    arguments = compact_json(args).decode("utf-8")
    call = {"id": call_id, "type": "function",
            "function": {"name": _v2_provider_name(tool_key),
                         "arguments": arguments}}
    raw = {
        "id": "resp-tool", "model": "deepseek-flash",
        "choices": [{"finish_reason": "tool_calls", "message": {
            "role": "assistant", "content": None,
            "reasoning_content": "plan", "tool_calls": [call]}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    return {"status": 200, "advance_ms": 7, "raw": raw}


def descriptor_for(key, timeout_ms=5000, *, scenario=True):
    descriptor = copy.deepcopy(READ_DESCRIPTOR)
    descriptor["tool"]["key"] = key
    descriptor["tool"]["limits"]["timeout_ms"] = timeout_ms
    descriptor["tool"]["description"] = f"W4a stub tool {key}"
    if scenario:
        descriptor["tool"]["parameters"]["properties"]["scenario"] = {
            "type": "string", "enum": list(SCENARIOS)}
    return descriptor


def manifest_for(realm, descriptors):
    return compact_json({
        "identity": f"w4a.stub.{realm}",
        "version": "1",
        "requires": [],
        "provides": [{"realm": realm, "key": item["tool"]["key"],
                      "descriptor": item} for item in descriptors],
        "adapter_digest": "\\x" + adapter_declaration_digest("python"),
    })


def build_plugin(base, *, realm, descriptors, timeout_ms=5000,
                 workspace=None, artifact=None, cwd=None, spawn_log=None):
    """Return (plugin, install_dict) for a direct (non-manifest) approval."""
    base = Path(base)
    install_dir = base / "install"
    workspace = Path(workspace) if workspace is not None else base / "workspace"
    install_dir.mkdir(parents=True, exist_ok=True)
    workspace.mkdir(parents=True, exist_ok=True)
    stub = install_dir / "stub_plugin.py"
    if artifact is None:
        shutil.copyfile(STUB, stub)
        artifact = stub
    artifact = Path(artifact)
    digest = (hashlib.sha256(artifact.read_bytes()).hexdigest()
              if artifact.is_file() else "0" * 64)
    log = Path(spawn_log) if spawn_log is not None else base / "spawn.log"
    argv = (sys.executable, str(artifact), "serve", "--spawn-log", str(log))
    manifest = manifest_for(realm, descriptors)
    plugin = ApprovedPlugin(
        adapter_id=f"w4a.{realm}",
        language="python",
        identity=f"w4a.stub.{realm}",
        version="1",
        manifest_digest=hashlib.sha256(manifest).hexdigest(),
        artifact_digest=digest,
        adapter_digest=adapter_declaration_digest("python"),
        argv=argv,
        cwd=str(Path(cwd) if cwd is not None else install_dir),
        environment_allowlist=("PATH", "HOME", "V24_WORKSPACE_ROOT"),
        tools=tuple(v2_tool(item) for item in descriptors),
        workspace_root=os.path.realpath(workspace),
        timeout_ms=timeout_ms,
    )
    install = {
        "identity": plugin.identity,
        "version": plugin.version,
        "manifest_digest": plugin.manifest_digest,
        "artifact_digest": plugin.artifact_digest,
        "adapter_digest": plugin.adapter_digest,
    }
    return plugin, install, manifest, log


@dataclasses.dataclass
class StubSpec:
    manifest: bytes
    artifact_digest: str
    tool_key: str = "read"
    language: str = "python"


class FakeDB:
    def __init__(self, remaining=30000):
        self.remaining = remaining
        self.calls = []

    def remaining_lease_ms(self, lease_until):
        self.calls.append(lease_until)
        return self.remaining


class ZeroSpawn:
    """Fail if any code path tries to create a process."""

    def __init__(self):
        self.calls = []
        self._saved = None

    def __enter__(self):
        self._saved = line_json.run_process

        def sentinel(*args, **kwargs):
            self.calls.append((args, kwargs))
            raise AssertionError("unexpected run_process call")

        line_json.run_process = sentinel
        return self

    def __exit__(self, exc_type, exc, tb):
        line_json.run_process = self._saved
        assert self.calls == [], self.calls
        return False


class RecordingSpawn:
    def __init__(self):
        self.calls = []
        self._saved = None

    def __enter__(self):
        self._saved = line_json.run_process

        def sentinel(*args, **kwargs):
            self.calls.append((args, kwargs))
            raise line_json.ProcessError("spawn blocked by test")

        line_json.run_process = sentinel
        return self

    def __exit__(self, exc_type, exc, tb):
        line_json.run_process = self._saved
        return False


def assert_v2(result):
    assert set(result) == {"class", "result", "model_text"}, set(result)
    assert set(result["result"]) == {"status", "output", "usage"}
    ToolDispatchResult(result["class"], result["result"], result["model_text"])
    return result


def assert_v2_failure(result, code):
    assert_v2(result)
    assert result["class"] == "failure", result
    assert result["result"]["status"] == "error"
    assert result["result"]["output"]["error"]["code"] == code, result
    assert result["model_text"].startswith(f"Error [{code}]: "), result
    assert len(result["result"]["output"]["content"]) == 1
    return result


def dispatch_records(harness, kind):
    found = []
    for record in harness.journal.records:
        if record.get("event_type") != "dispatch_finished":
            continue
        payload = record.get("payload") or {}
        if payload.get("kind") == kind:
            found.append(payload)
    return found


def spawn_lines(spawn_log):
    path = Path(spawn_log)
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


# ---------------------------------------------------------------------------
# Segment 1: provider projection
# ---------------------------------------------------------------------------
def segment_projection():
    document = json.loads(
        (VECTORS / "provider_projection_v2.json").read_text(encoding="utf-8"))
    by_id = {case["id"]: case for case in document["cases"]}
    for kind in ("read", "list", "search"):
        descriptor = DESCRIPTORS[kind]
        case = by_id[f"provider.projection.{kind}"]
        pin = {"key": kind, "released_at": None, "descriptor": descriptor}
        tools, meta = DeepSeekAdapter._tools([pin])
        projected = meta["descriptors"][kind]
        assert set(projected) == {"name", "description", "parameters"}
        raw = compact_json(projected)
        assert len(raw) == case["expected_length"], (kind, len(raw))
        assert raw.hex() == case["expected_hex"], kind
        assert hashlib.sha256(raw).hexdigest() == case["expected_sha256"]
        assert tools[0]["function"] == projected

    mapping = by_id["provider.safe_name_mapping"]
    assert mapping["expected"]["projection_keys"] == [
        "name", "description", "parameters"]
    for row in mapping["input"]:
        descriptor = copy.deepcopy(DESCRIPTORS[row["descriptor_key"]])
        descriptor["tool"]["key"] = row["descriptor_key"]
        pin = {"key": row["pin_key"], "released_at": None,
               "descriptor": descriptor}
        tools, meta = DeepSeekAdapter._tools([pin])
        projected = meta["descriptors"][row["pin_key"]]
        assert projected["name"] == row["name"], row
        assert set(projected) == set(mapping["expected"]["projection_keys"])

    mismatch = by_id["provider.key_mismatch"]
    for row in mismatch["input"]:
        descriptor = copy.deepcopy(DESCRIPTORS["read"])
        descriptor["tool"]["key"] = row["descriptor_key"]
        pin = {"key": row["pin_key"], "released_at": None,
               "descriptor": descriptor}
        expect_adapter_failure(lambda pin=pin: DeepSeekAdapter._tools([pin]),
                               row["expected"])

    # B0's structural descriptor-v2 rejection must survive the widened v1
    # check: {"v":2,"tool":{}} has no key, so the provider rejects it.
    expect_adapter_failure(
        lambda: DeepSeekAdapter._tools([
            {"key": "read", "released_at": None,
             "descriptor": {"v": 2, "tool": {}}}]),
        "descriptor_invalid")

    # v1 request bodies are read-only baseline rows; B0 re-checks the actual
    # bytes end-to-end in both golden runs.
    golden = json.loads(
        (V24 / "b0" / "golden" / "provider_requests_v1.json").read_text(
            encoding="utf-8"))
    golden_by_id = {case["id"]: case for case in golden["cases"]}
    baseline = by_id["provider.v1_bytes_unchanged"]
    for row in baseline["input"]:
        case = golden_by_id[row["id"]]
        assert case["expected_length"] == row["expected_length"], row["id"]
        assert case["expected_sha256"] == row["expected_sha256"], row["id"]

    COUNTER["cases"] += 13
    print("[W4a] provider projection: 3 bytes cases, mapping=3, mismatch=2, "
          "v1_baseline=4")


# ---------------------------------------------------------------------------
# Segment 2: handler normalization
# ---------------------------------------------------------------------------
def segment_handler_unit():
    result = {"status": "error", "output": {"code": "x"},
              "usage": {"wall_ms": 0}}
    assert _call_tool_handler(lambda effect: ("failure", result), {}) == (
        "failure", result, None)
    assert _call_tool_handler(
        lambda effect: {"class": "failure", "result": result}, {}) == (
        "failure", result, None)
    assert _call_tool_handler(
        lambda effect: {"class": "failure", "result": result,
                        "model_text": "text"}, {}) == (
        "failure", result, "text")
    for bad in ({**{"class": "failure", "result": result}, "model_text": 1},
                {"class": "failure"}, ("failure",)):
        try:
            _call_tool_handler(lambda effect, bad=bad: bad, {})
        except TypeError:
            pass
        else:
            raise AssertionError(f"accepted invalid handler return {bad!r}")
    COUNTER["cases"] += 6


def v1_worker_branch(fixture, work, mode):
    realm = f"w4a-branch-{mode}-{uuid.uuid4().hex[:8]}"
    workdir = Path(work) / f"branch-{mode}-{uuid.uuid4().hex[:8]}"
    workdir.mkdir(parents=True)
    os.chmod(workdir, 0o700)
    spec = build_spec("python", realm=realm)
    harness = PluginHarness(fixture, build_registry(spec), workdir, realm=realm)
    try:
        install_id = harness.admit(spec)
        harness.prepare([install_id])
        harness.activate(install_id, spec.tool_key)
        fiber = harness.fiber(install_id)
        response = harness.start(
            fiber["fiber_id"], [spec.tool_key],
            [{"role": "user", "content": "echo"}])
        run_id = response["emitted"][0]
        if mode == "absent":
            harness.worker.tool_handler = None
        else:
            def raising(effect):
                raise RuntimeError("scripted handler failure")
            harness.worker.tool_handler = raising
        script = [tool_reply("call_1", spec.tool_key, {"text": "x"}),
                  final_reply("final")]
        harness.run(script, max_rounds=12)
        payloads = dispatch_records(harness, "tool_call")
        assert len(payloads) == 1, len(payloads)
        payload = payloads[0]
        assert set(payload) == DISPATCH_KEYS, set(payload)
        message = payload["tool_message"]
        assert set(message) == MESSAGE_KEYS, set(message)
        expected_code = ("tool_handler_absent" if mode == "absent"
                         else "tool_executor_error")
        assert message["content"] == compact_json(
            {"code": expected_code}).decode("utf-8")
        assert payload["reason"] == expected_code, payload["reason"]
        assert payload["tool_result"]["output"] == {"code": expected_code}
        assert harness.run_row(run_id)["status"] in (
            "blocked_unknown", "failed", "completed")
        COUNTER["cases"] += 1
        return expected_code
    finally:
        harness.close()


# ---------------------------------------------------------------------------
# Segment 2b: environment injection and per-tool process specs
# ---------------------------------------------------------------------------
def segment_environment(work):
    base = Path(work) / f"env-{uuid.uuid4().hex[:8]}"
    base.mkdir(parents=True)
    plugin, _install, _manifest, _log = build_plugin(
        base, realm=f"env-{uuid.uuid4().hex[:8]}",
        descriptors=[descriptor_for("read", 5000)])
    source = {"PATH": "/bin", "HOME": "/home",
              "V24_WORKSPACE_ROOT": "/host/not-approved"}
    env = plugin.environment(source)
    assert env["V24_WORKSPACE_ROOT"] == plugin.workspace_root, env
    assert env["V24_WORKSPACE_ROOT"] != source["V24_WORKSPACE_ROOT"]
    assert env["PATH"] == "/bin"

    spec = build_spec("python", realm=f"env-v1-{uuid.uuid4().hex[:8]}")
    v1_env = spec.entry.environment(source)
    assert "V24_WORKSPACE_ROOT" not in v1_env, v1_env

    no_root = dataclasses.replace(plugin, environment_allowlist=("PATH",))
    assert "V24_WORKSPACE_ROOT" not in no_root.environment(source)
    COUNTER["cases"] += 3


def segment_timeouts(work):
    base = Path(work) / f"timeout-{uuid.uuid4().hex[:8]}"
    base.mkdir(parents=True)
    plugin, _install, _manifest, _log = build_plugin(
        base, realm=f"timeout-{uuid.uuid4().hex[:8]}",
        descriptors=[descriptor_for("read", 5000),
                     descriptor_for("slow", 15000)],
        timeout_ms=1234)
    assert plugin.timeout_ms == 1234
    assert line_json._spec_v2(plugin, "invoke", "read").timeout_ms == 5000
    assert line_json._spec_v2(plugin, "invoke", "slow").timeout_ms == 15000
    assert line_json._spec_v2(plugin, "prepare", None).timeout_ms == 1234
    COUNTER["cases"] += 3


# ---------------------------------------------------------------------------
# Segment 3: pre-spawn v2 failures, no process
# ---------------------------------------------------------------------------
def pre_spawn_segment(work):
    base = Path(work) / f"pre-{uuid.uuid4().hex[:8]}"
    base.mkdir(parents=True)
    realm = f"pre-{uuid.uuid4().hex[:8]}"
    descriptors = [descriptor_for("read", 5000),
                   descriptor_for("slow", 15000)]
    plugin, install, _manifest, spawn_log = build_plugin(
        base, realm=realm, descriptors=descriptors)
    db = FakeDB(19999)
    dispatcher = PluginDispatcher(db, ApprovedAdapterRegistry((plugin,)))
    effect = {"effect_id": str(uuid.uuid4()), "lease_until": LEASE_SENTINEL}
    read_tool = plugin.tool_for("read")
    slow_tool = plugin.tool_for("slow")
    assert read_tool is not None and slow_tool is not None

    def pin(tool):
        return {"key": tool.key, "descriptor": tool.descriptor,
                "descriptor_digest": tool.descriptor_digest}

    def call(args, *, key="read", tool=read_tool, entry=plugin,
             pin_value=None, effect_value=effect):
        return dispatcher._tool_v2(
            effect_value, entry, install,
            pin(tool) if pin_value is None else pin_value, key, args)

    zero_spawn_paths = 0
    assert not Path(spawn_log).exists()
    with ZeroSpawn():
        assert_v2_failure(call({"path": "x" * 20000}), "invalid_tool_arguments")
        assert_v2_failure(call({"path": "x", "offset": 1.5}),
                          "invalid_tool_arguments")
        zero_spawn_paths += 1

    with ZeroSpawn():
        result = call({"path": "x", "limit": 0})
        assert_v2_failure(result, "invalid_tool_arguments")
        assert result["model_text"].startswith("Error [invalid_tool_arguments]: $.")
        zero_spawn_paths += 1
    assert not Path(spawn_log).exists()

    # Artifact five reasons, all before any process.
    path_type = type(Path())
    artifact_cases = {
        "artifact_missing": {"resolve": FileNotFoundError()},
        "artifact_outside_cwd": {"resolve": [Path("/tmp/outside.py"),
                                             Path(plugin.cwd)]},
        "artifact_not_regular": {
            "resolve": [Path(plugin.cwd) / "artifact.py", Path(plugin.cwd)],
            "stat": type("S", (), {"st_mode": 0o040755})()},
        "artifact_unreadable": {
            "resolve": [Path(plugin.cwd) / "artifact.py", Path(plugin.cwd)],
            "stat": OSError("unreadable")},
        "artifact_digest_mismatch": {
            "resolve": [Path(plugin.cwd) / "artifact.py", Path(plugin.cwd)],
            "stat": type("S", (), {"st_mode": 0o100600})(),
            "read_bytes": b"different bytes"},
    }
    for code, setup in artifact_cases.items():
        with ZeroSpawn():
            with patch.object(path_type, "resolve",
                              side_effect=setup.get("resolve")):
                if "stat" in setup:
                    with patch.object(path_type, "stat",
                                      side_effect=setup["stat"]
                                      if isinstance(setup["stat"], Exception)
                                      else None,
                                      return_value=None if isinstance(
                                          setup["stat"], Exception)
                                      else setup["stat"]):
                        if "read_bytes" in setup:
                            with patch.object(path_type, "read_bytes",
                                              return_value=setup["read_bytes"]):
                                result = call({"path": "x"})
                        else:
                            result = call({"path": "x"})
                else:
                    result = call({"path": "x"})
            assert_v2_failure(result, code)
    zero_spawn_paths += 1
    assert not Path(spawn_log).exists()

    # Workspace disappears after approval.
    missing_base = Path(work) / f"missing-{uuid.uuid4().hex[:8]}"
    missing_base.mkdir(parents=True)
    missing_ws = missing_base / "workspace"
    missing_ws.mkdir()
    missing_plugin, missing_install, _m, missing_log = build_plugin(
        missing_base, realm=f"missing-{uuid.uuid4().hex[:8]}",
        descriptors=[descriptor_for("read", 5000)], workspace=missing_ws)
    missing_dispatcher = PluginDispatcher(
        FakeDB(30000), ApprovedAdapterRegistry((missing_plugin,)))
    missing_tool = missing_plugin.tool_for("read")
    os.rmdir(missing_ws)
    with ZeroSpawn():
        result = missing_dispatcher._tool_v2(
            effect, missing_plugin, missing_install, pin(missing_tool),
            "read", {"path": "x"})
        assert_v2_failure(result, "workspace_unavailable")
    zero_spawn_paths += 1
    assert not missing_log.exists()

    # Lease uses the approved tool timeout, not the worker default.
    db.calls.clear()
    with ZeroSpawn():
        result = call({"path": "x"}, key="slow", tool=slow_tool)
        assert_v2_failure(result, "lease_insufficient")
    assert db.calls == [LEASE_SENTINEL], db.calls
    assert db.calls[0] != (datetime.now(timezone.utc) + timedelta(
        milliseconds=30000)).isoformat()

    # Missing lease_until fails closed too.
    db.calls.clear()
    with ZeroSpawn():
        result = call({"path": "x"}, effect_value={"effect_id": str(uuid.uuid4())})
        assert_v2_failure(result, "lease_insufficient")
    zero_spawn_paths += 1

    # match_tool failures are inside _tool_v2 and produce the v2 envelope.
    # The second case needs a plugin without read; build it separately.
    with ZeroSpawn():
        result = call({"path": "x"}, key="read", tool=read_tool,
                      pin_value={"key": "list",
                                 "descriptor": read_tool.descriptor,
                                 "descriptor_digest":
                                     read_tool.descriptor_digest})
        assert_v2_failure(result, "pin_key_mismatch")
    list_only_base = Path(work) / f"list-only-{uuid.uuid4().hex[:8]}"
    list_only_base.mkdir(parents=True)
    list_desc = descriptor_for("list", 5000)
    list_tool = v2_tool(list_desc)
    list_plugin = ApprovedPlugin(
        adapter_id="w4a.listonly", language="python", identity="w4a.listonly",
        version="1", manifest_digest=hashlib.sha256(
            manifest_for("listonly", [list_desc])).hexdigest(),
        artifact_digest="0" * 64, adapter_digest=adapter_declaration_digest("python"),
        argv=(sys.executable, str(STUB), "serve", "--spawn-log",
              str(list_only_base / "spawn.log")),
        cwd=str(list_only_base), environment_allowlist=("PATH",),
        tools=(list_tool,), workspace_root=os.path.realpath(list_only_base))
    list_install = {
        "identity": list_plugin.identity, "version": list_plugin.version,
        "manifest_digest": list_plugin.manifest_digest,
        "artifact_digest": list_plugin.artifact_digest,
        "adapter_digest": list_plugin.adapter_digest,
    }
    list_dispatcher = PluginDispatcher(
        FakeDB(30000), ApprovedAdapterRegistry((list_plugin,)))
    with ZeroSpawn():
        result = list_dispatcher._tool_v2(
            effect, list_plugin, list_install,
            {"key": "read", "descriptor": read_tool.descriptor,
             "descriptor_digest": read_tool.descriptor_digest},
            "read", {"path": "x"})
        assert_v2_failure(result, "tool_not_approved")
    bad_descriptor = json.loads(json.dumps(read_tool.descriptor))
    bad_descriptor["tool"]["description"] = "tampered"
    descriptor_mismatch_pin = {"key": "read", "descriptor": bad_descriptor,
                               "descriptor_digest": read_tool.descriptor_digest}
    with ZeroSpawn():
        result = call({"path": "x"}, pin_value=descriptor_mismatch_pin)
        assert_v2_failure(result, "descriptor_mismatch")
    digest_mismatch_pin = {"key": "read", "descriptor": read_tool.descriptor,
                           "descriptor_digest": "0" * 64}
    with ZeroSpawn():
        result = call({"path": "x"}, pin_value=digest_mismatch_pin)
        assert_v2_failure(result, "descriptor_digest_mismatch")
    missing_pin = {"key": "read", "descriptor_digest": read_tool.descriptor_digest}
    with ZeroSpawn():
        result = call({"path": "x"}, pin_value=missing_pin)
        assert_v2_failure(result, "descriptor_missing")
    zero_spawn_paths += 1
    assert not Path(spawn_log).exists()

    # 5000 ms tool with 19999 ms remaining passes the lease gate and attempts
    # exactly one spawn; the sentinel turns that into a preflight failure.
    db.calls.clear()
    with RecordingSpawn() as recorder:
        result = call({"path": "x"})
        assert_v2_failure(result, "spawn_failed")
    assert len(recorder.calls) == 1, recorder.calls
    assert db.calls == [LEASE_SENTINEL], db.calls
    assert not Path(spawn_log).exists()

    assert zero_spawn_paths == 6, zero_spawn_paths
    COUNTER["cases"] += 17
    return zero_spawn_paths


# ---------------------------------------------------------------------------
# Segment 4: end-to-end v2 subprocess
# ---------------------------------------------------------------------------
def run_stub_case(fixture, work, scenario, *, timeout_ms=5000,
                  path="a.txt", require_release=False):
    realm = f"w4a.e2e.{scenario}.{uuid.uuid4().hex[:8]}"
    base = Path(work) / f"e2e-{scenario}-{uuid.uuid4().hex[:8]}"
    base.mkdir(parents=True)
    descriptors = [descriptor_for("read", timeout_ms)]
    plugin, _install, manifest, spawn_log = build_plugin(
        base, realm=realm, descriptors=descriptors)
    spec = StubSpec(manifest=manifest, artifact_digest=plugin.artifact_digest)
    harness = PluginHarness(fixture, ApprovedAdapterRegistry((plugin,)),
                            base / "harness", realm=realm)
    result = {"spawn_log": spawn_log, "harness": harness}
    try:
        install_id = harness.admit(spec)
        harness.prepare([install_id])
        harness.activate(install_id, "read")
        fiber = harness.fiber(install_id)
        response = harness.start(
            fiber["fiber_id"], ["read"],
            [{"role": "user", "content": f"run {scenario}"}])
        run_id = response["emitted"][0]
        script = [v2_tool_reply("call_1", "read",
                                {"path": path, "scenario": scenario}),
                  final_reply("final")]
        harness.run(script, max_rounds=30)
        payloads = dispatch_records(harness, "tool_call")
        assert len(payloads) == 1, (scenario, len(payloads))
        payload = payloads[0]
        assert set(payload) == DISPATCH_KEYS, set(payload)
        message = payload["tool_message"]
        assert set(message) == MESSAGE_KEYS, set(message)
        resource = dispatch_records(harness, "host_prepare")
        assert resource, scenario
        assert resource[0]["resource_result"]["v"] == 1, resource[0]
        assert {"adapter_id", "language", "reservation"} <= set(
            resource[0]["resource_result"])
        result.update({
            "run_id": run_id, "install_id": install_id,
            "payload": payload, "message": message,
            "run_status": harness.run_row(run_id)["status"],
            "resource": resource[0],
        })
        if require_release:
            harness.off(install_id)
            harness.dispose(install_id)
            harness.run(None, max_rounds=12)
            release = dispatch_records(harness, "host_release")
            assert release, "missing host_release dispatch"
            assert release[0]["resource_result"]["v"] == 1
            result["release"] = release[0]
        return result
    finally:
        harness.close()


def end_to_end_segment(fixture, work):
    join_case = run_stub_case(fixture, work, "ok", path="join.txt")
    payload = join_case["payload"]
    assert payload["outcome"]["class"] == "success", payload["outcome"]
    assert payload["claim"] == payload["outcome"]["claim"]
    assert_success_output(payload["tool_result"]["output"])
    expected_content = "one\n二\n三"
    assert join_case["message"]["content"] == expected_content
    assert len(expected_content.encode("utf-8")) == 11
    assert hashlib.sha256(expected_content.encode("utf-8")).hexdigest() == (
        "cdf4e39b8e0f067155ba61109423ae8b50ec2a6a4395910d6020017e1373f8a8")
    journal_text = "".join(
        record["payload"]["tool_message"]["content"]
        for record in join_case["harness"].journal.records
        if record.get("event_type") == "dispatch_finished"
        and record["payload"].get("kind") == "tool_call")
    assert journal_text == expected_content
    lines = spawn_lines(join_case["spawn_log"])
    assert len(lines) == 2, lines
    assert [line.split(" ", 1)[1] for line in lines] == ["prepare", "invoke"]

    # 11-byte join and meta exclusion are the frozen result vectors.
    results = json.loads((VECTORS / "results_v2.json").read_text(
        encoding="utf-8"))
    by_id = {case["id"]: case for case in results["cases"]}
    join_vector = by_id["result.model_text_join"]
    joined = join_content(join_vector["input"])
    assert joined.encode("utf-8").hex() == join_vector["expected_hex"]
    assert len(joined.encode("utf-8")) == join_vector["expected_length"] == 11
    meta_vector = by_id["result.meta_excluded_from_model_text"]
    assert join_content(meta_vector["input"]["content"]) == joined
    assert len(compact_json(meta_vector["input"]["meta"])) > 2

    expected = {
        "known_error": ("failure", "stub_known_error",
                        "Error [stub_known_error]: stub known error"),
        "bad_frame": ("unknown", "bad_frame", ""),
        "extra_frame": ("unknown", "extra_frame", ""),
        "no_lf": ("unknown", "bad_frame", ""),
        "timeout": ("unknown", "timeout", ""),
        "nonempty_meta": ("failure", "invalid_tool_output", None),
        "bad_value": ("failure", "invalid_tool_output", None),
        "bad_relation": ("failure", "invalid_tool_output", None),
        "huge_value": ("failure", "output_too_large", None),
        "crash": ("unknown", "abnormal_exit", ""),
    }
    for scenario, (class_name, code, content) in expected.items():
        case = run_stub_case(fixture, work, scenario,
                             timeout_ms=300 if scenario == "timeout" else 5000)
        outcome = case["payload"]["outcome"]
        assert outcome["class"] == class_name, (scenario, outcome)
        assert case["message"]["content"].startswith(
            "" if class_name == "unknown" else f"Error [{code}]: "), (
            scenario, case["message"])
        if class_name == "unknown":
            assert case["message"]["content"] == "", (scenario, case["message"])
            assert_unknown_output(case["payload"]["tool_result"]["output"])
            assert case["payload"]["tool_result"]["output"]["error"]["code"] == code
        else:
            assert_failure_output(case["payload"]["tool_result"]["output"])
            assert case["payload"]["tool_result"]["output"]["error"]["code"] == code
            if content is not None:
                assert case["message"]["content"] == content
        lines = spawn_lines(case["spawn_log"])
        assert len(lines) == 2, (scenario, lines)
        assert lines[1].endswith(" invoke"), (scenario, lines)

    release_case = run_stub_case(fixture, work, "ok", path="join.txt",
                                 require_release=True)
    assert release_case["release"]["resource_result"]["v"] == 1
    COUNTER["cases"] += 12
    return join_case


# ---------------------------------------------------------------------------
# Scope audit (enabled after the W4-6 design repin)
# ---------------------------------------------------------------------------
BASE = "c8c4bd0"


def _git(*args, check=True):
    return subprocess.run(["git", *args], cwd=ROOT, check=check,
                          capture_output=True, text=True)


def scope_audit():
    """Six pinned-baseline audits; [passed] is deliberately not printed."""
    checks = 0
    frozen = (
        "v24/b0", "v24/s10", "v24/s11", "v24/load.py",
        "v24/host/canonical.py", "v24/host/descriptor.py",
        "v24/host/tool_schema.py", "v24/host/renderers.py",
        "v24/host/tool_results.py", "v24/host/line_json.py",
        "v24/host/journal.py", "v24/host/db.py", "v24/host/process_io.py",
    )
    assert _git("diff", "--exit-code", BASE, "--", *frozen).returncode == 0
    untracked = _git("ls-files", "--others", "--exclude-standard", "--",
                     "v24/b0", "v24/s10", "v24/s11", "v24/sql",
                     "v24/s13/vectors").stdout
    assert untracked == "", untracked
    checks += 1

    vectors = _git("diff", "--exit-code", BASE, "--", "v24/s13/vectors",
                   ":!v24/s13/vectors/design_conformance.json")
    assert vectors.returncode == 0, vectors.stdout
    checks += 1

    path = "v24/s13/vectors/design_conformance.json"
    current_text = (ROOT / path).read_text(encoding="utf-8")
    baseline_text = _git("show", f"{BASE}:{path}").stdout
    current_sha = json.loads(current_text)["design_input"]["sha256_at_review"]
    baseline_sha = json.loads(baseline_text)["design_input"]["sha256_at_review"]
    assert current_sha != baseline_sha
    assert current_text.replace(current_sha, baseline_sha, 1) == baseline_text
    diff = _git("diff", "-U0", BASE, "--", path).stdout.splitlines()
    minus = [line for line in diff if line.startswith("-")
             and not line.startswith("---")]
    plus = [line for line in diff if line.startswith("+")
            and not line.startswith("+++")]
    assert len(minus) == 1 and len(plus) == 1, (minus, plus)
    assert "sha256_at_review" in minus[0] and "sha256_at_review" in plus[0]
    checks += 1

    registry = "v24/host/registry.py"
    baseline_registry = _git("show", f"{BASE}:{registry}").stdout
    current_registry = (ROOT / registry).read_text(encoding="utf-8")
    old_block = (
        "    def environment(self, source=None) -> dict[str, str]:\n"
        "        \"\"\"Select only allowlisted variables from the host environment.\"\"\"\n"
        "        source = os.environ if source is None else source\n"
        "        return {key: source[key] for key in self.environment_allowlist\n"
        "                if key in source}\n"
    )
    new_block = (
        "    def environment(self, source=None) -> dict[str, str]:\n"
        "        \"\"\"Select only allowlisted variables from the host environment.\"\"\"\n"
        "        source = os.environ if source is None else source\n"
        "        env = {key: source[key] for key in self.environment_allowlist\n"
        "                if key in source}\n"
        "        root = getattr(self, \"workspace_root\", None)\n"
        "        if root is not None and \"V24_WORKSPACE_ROOT\" in self.environment_allowlist:\n"
        "            env[\"V24_WORKSPACE_ROOT\"] = root\n"
        "        return env\n"
    )
    assert baseline_registry.count(old_block) == 1
    assert baseline_registry.replace(old_block, new_block, 1) == current_registry
    registry_diff = _git("diff", "-U1", BASE, "--", registry).stdout
    assert len([line for line in registry_diff.splitlines()
                if line.startswith("@@")]) == 1, registry_diff
    registry_minus = [line for line in registry_diff.splitlines()
                      if line.startswith("-") and not line.startswith("---")]
    registry_plus = [line for line in registry_diff.splitlines()
                     if line.startswith("+") and not line.startswith("+++")]
    assert len(registry_minus) == 1 and len(registry_plus) == 5, (
        registry_minus, registry_plus)
    checks += 1

    for needle, label in (("v24/s13/vectors", "vector_import"),
                          ("w1_reference", "oracle_import")):
        found = subprocess.run(["grep", "-rn", needle, "v24/host"], cwd=ROOT,
                               capture_output=True, text=True)
        assert found.returncode != 0, (label, found.stdout)
    checks += 1

    sql = _git("diff", "--exit-code", BASE, "--", "v24/sql")
    assert sql.returncode == 0, sql.stdout
    checks += 1
    assert checks == 6, checks
    print(f"[scope] passed base={BASE} checks={checks}")

def main() -> int:
    segment_projection()
    segment_handler_unit()
    with server_helper_scope(), setup_db() as fixture:
        with tempfile.TemporaryDirectory(prefix="w4a-wiring-") as work:
            os.chmod(work, 0o700)
            segment_environment(work)
            segment_timeouts(work)
            zero_spawn_paths = pre_spawn_segment(work)
            end_to_end_segment(fixture, work)
            for mode in ("absent", "raising"):
                v1_worker_branch(fixture, work, mode)
    scope_audit()
    print(f"[passed] W4 dispatch wiring; cases={COUNTER['cases']}; "
          f"zero_spawn_paths={zero_spawn_paths}; model_text_bytes=11; "
          f"v1_bytes_unchanged=true; resource_receipt_v1=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
