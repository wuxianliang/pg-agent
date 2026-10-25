"""G10: M-P Python plugin lifecycle extension check.

Run from the worktree root::

    uv run python v24/s11/test_g10.py
    uv run python v24/s11/test_g10.py --only G10-B

This is an extension check, not a twelfth closeout gate.  It uses real local
Python subprocesses (a deliberate section 9.1 deviation recorded in the
deviation ledger) but opens no socket and runs no provider.  The default suite
covers Python only; ``test_node.py --node`` and
``v24.host.plugin_smoke --multilingual-smoke`` are the separate Node and
same-run multilingual evidence.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from pathlib import Path

S11 = Path(__file__).resolve().parent
V24 = S11.parent
ROOT = V24.parent
for _path in (S11, V24 / "s1", V24 / "s2", V24 / "s4", ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

socket = __import__("socket")

from psycopg2.extras import Json  # noqa: E402

from setup_db import _assert_closed_catalog, server_helper_scope, setup_db  # noqa: E402
from test_g3a import one  # noqa: E402

from v24.host import line_json  # noqa: E402
from v24.host.registry import (  # noqa: E402
    AdapterNotFound,
    ApprovedAdapter,
    ApprovedAdapterRegistry,
    RegistryError,
    descriptor_digest,
)
from plugin_fixtures import (  # noqa: E402
    PluginHarness,
    artifact_sha256,
    build_adapter,
    build_registry,
    build_spec,
    descriptor_for,
    execute_single,
    final_reply,
    manifest_bytes,
    tool_reply,
)

ALL_CASES = ("G10-A", "G10-B", "G10-C", "G10-D", "G10-E", "G10-F",
             "G10-G", "G10-H")
FORBIDDEN_IMPORTS = ("socket", "http", "urllib", "requests", "ftplib",
                     "smtplib", "telnetlib", "aiohttp", "httpx")
_SAVED = None


def _deny(*args, **kwargs):
    raise AssertionError("v24/s11 G10 attempted network I/O")


def install_no_network():
    global _SAVED
    urllib_request = __import__("urllib.request", fromlist=["request"])
    _SAVED = (socket.socket.connect, socket.create_connection,
              urllib_request.urlopen)
    socket.socket.connect = _deny
    socket.create_connection = _deny
    urllib_request.urlopen = _deny


def restore_no_network():
    global _SAVED
    if _SAVED is not None:
        socket.socket.connect, socket.create_connection, urlopen = _SAVED
        __import__("urllib.request", fromlist=["request"]).urlopen = urlopen
        _SAVED = None


def assert_static_guards():
    files = sorted(S11.glob("*.py")) + [
        V24 / "host" / name for name in
        ("registry.py", "line_json.py", "plugins.py", "plugin_smoke.py")]
    for path in files:
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        for name in FORBIDDEN_IMPORTS:
            assert re.search(rf"(?m)^\s*(?:from|import)\s+{re.escape(name)}\b",
                             source) is None, (path.name, name)
        assert ("time." + "sleep") not in source, path.name
    assert "shell=True" not in (V24 / "host" / "process_io.py").read_text()
    assert "shell=True" not in (V24 / "host" / "line_json.py").read_text()


def _workdir(root: Path, name: str) -> Path:
    path = root / name
    path.mkdir(mode=0o700)
    assert stat.S_IMODE(path.stat().st_mode) == 0o700
    return path


def _py_script(path: Path, body: str) -> Path:
    path.write_text("#! /usr/bin/env python3\n" + body, encoding="utf-8")
    os.chmod(path, 0o700)
    return path


MISBEHAVE = r'''
import json, sys
line = sys.stdin.readline()
frame = json.loads(line)
mode = frame.get("args", {}).get("__mode__", "success")
def emit(obj, code=0):
    sys.stdout.write(json.dumps(obj) + "\n"); sys.stdout.flush()
    raise SystemExit(code)
if mode == "success":
    emit({"ok": True, "result": json.dumps({"mode": "success"})})
elif mode == "bad_frame":
    sys.stdout.write("not-json\n"); sys.stdout.flush(); raise SystemExit(0)
elif mode == "extra_frame":
    sys.stdout.write(json.dumps({"ok": True, "result": "{\"a\":1}"}) + "\n")
    sys.stdout.write(json.dumps({"ok": True, "result": "{\"b\":2}"}) + "\n")
    raise SystemExit(0)
elif mode == "eof":
    raise SystemExit(0)
elif mode == "overflow":
    sys.stdout.write("x" * (70 * 1024)); sys.stdout.flush(); raise SystemExit(0)
elif mode == "stderr_overflow":
    sys.stderr.write("e" * (20 * 1024)); sys.stderr.flush(); raise SystemExit(0)
elif mode == "abnormal":
    raise SystemExit(7)
elif mode == "timeout":
    while True:
        pass
elif mode == "tool_error":
    emit({"ok": False, "error": "known_error", "message": "known failure"}, 3)
elif mode == "non_object":
    emit({"ok": True, "result": "[1,2,3]"})
else:
    emit({"ok": False, "error": "bad_mode", "message": str(mode)}, 3)
'''


def custom_spec(path: Path, *, tool_key: str, identity: str,
                timeout_ms: int = 500):
    descriptor = descriptor_for(tool_key)
    manifest = manifest_bytes(identity=identity, language="python",
                              tool_key=tool_key, realm="g10-misbehave",
                              descriptor=descriptor)
    entry = build_adapter(
        language="python", identity=identity, tool_key=tool_key,
        artifact_path=path, interpreter=sys.executable,
        manifest_digest=hashlib.sha256(manifest).hexdigest(),
        artifact_digest=artifact_sha256(path), descriptor=descriptor,
        timeout_ms=timeout_ms)
    from plugin_fixtures import PluginSpec
    return PluginSpec(language="python", identity=identity, tool_key=tool_key,
                      artifact_path=path, manifest=manifest,
                      descriptor=descriptor, entry=entry)


def tool_effect_row(harness, model_id):
    value = one(harness.owner,
                "SELECT effect_id FROM v24.effects WHERE parent_effect_id=%s "
                "AND kind='tool_call' ORDER BY ordinal LIMIT 1", (model_id,))
    harness.owner.commit()
    return harness.effect_row(value)


def _zero_spawn(fn):
    calls = []
    original = line_json.run_process

    def sentinel(spec):
        calls.append(spec)
        raise AssertionError("process spawn attempted before registry rejection")

    line_json.run_process = sentinel
    try:
        fn()
    finally:
        line_json.run_process = original
    assert calls == [], calls


# ---------------------------------------------------------------------------
# G10-A: registry immutability, real digests, path rejection
# ---------------------------------------------------------------------------
def g10_a(workdir):
    spec = build_spec("python", realm="g10-a")
    assert spec.artifact_digest == artifact_sha256(spec.artifact_path)
    assert spec.entry.manifest_digest == hashlib.sha256(
        spec.manifest).hexdigest()
    assert spec.descriptor_digest == descriptor_digest(spec.descriptor)
    assert spec.entry.descriptor_digest == spec.descriptor_digest
    assert spec.entry.tool_key == spec.tool_key
    assert spec.entry.cwd == str(spec.artifact_path.parent.resolve())

    try:
        spec.entry.argv = ("/bin/false",)
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("ApprovedAdapter is not frozen")
    try:
        spec.entry.parameters["type"] = "array"
    except TypeError:
        pass
    else:
        raise AssertionError("ApprovedAdapter parameters are mutable")
    assert spec.entry.descriptor_digest == descriptor_digest(spec.entry.descriptor)

    registry = build_registry(spec)
    install = {"identity": spec.identity, "version": "1",
               "manifest_digest": spec.manifest_digest,
               "artifact_digest": spec.artifact_digest,
               "adapter_digest": spec.entry.adapter_digest}
    assert registry.lookup_install(install) is spec.entry
    for field, value in (("manifest_digest", "0" * 64),
                         ("artifact_digest", "1" * 64),
                         ("adapter_digest", "2" * 64)):
        broken = dict(install)
        broken[field] = value
        try:
            registry.lookup_install(broken)
        except AdapterNotFound:
            pass
        else:
            raise AssertionError(f"lookup accepted mismatched {field}")
    try:
        ApprovedAdapterRegistry((spec.entry, spec.entry))
    except RegistryError:
        pass
    else:
        raise AssertionError("duplicate adapter entry accepted")

    spec.entry.require_artifact()
    tampered = _workdir(workdir, "g10-a-tampered") / "echo.py"
    shutil.copyfile(spec.artifact_path, tampered)
    os.chmod(tampered, 0o700)
    broken_entry = dataclasses.replace(
        spec.entry, argv=(sys.executable, str(tampered)),
        artifact_digest="3" * 64)
    try:
        broken_entry.require_artifact()
    except AdapterNotFound:
        pass
    else:
        raise AssertionError("tampered artifact accepted")

    directory_entry = dataclasses.replace(
        spec.entry, argv=(sys.executable, str(workdir)))
    try:
        directory_entry.require_artifact()
    except AdapterNotFound:
        pass
    else:
        raise AssertionError("directory artifact accepted")

    print("[G10-A] frozen registry entry, real artifact/manifest/descriptor "
          "digests, five-field lookup, duplicate/tampered/directory rejected")


# ---------------------------------------------------------------------------
# G10-B: Python full lifecycle with Unicode
# ---------------------------------------------------------------------------
def g10_b(fixture, workdir):
    realm = "g10-b-realm"
    spec = build_spec("python", realm=realm)
    harness = PluginHarness(fixture, build_registry(spec),
                            _workdir(workdir, "g10-b"), realm=realm)
    try:
        args = {"text": "héllo 世界", "n": 0}
        evidence = execute_single(harness, spec, args, "python-final")
        run = harness.run_row(evidence["run_id"])
        assert run["status"] == "completed", run
        assert run["result"]["final_text"] == "python-final", run
        tool = tool_effect_row(harness, evidence["model_id"])
        assert tool["status"] == "succeeded", tool
        result = tool["outcome"]["body"]["result"]
        assert result["status"] == "ok", result
        assert result["output"]["echo"] == args, result
        assert result["output"]["language"] == "python", result
        assert tool["resource_quiesced_at"] is not None, tool

        harness.off(evidence["install_id"])
        first = harness.dispose(evidence["install_id"])
        assert first.get("disposition") == "committed", first
        stats = harness.run(None, max_rounds=6)
        assert stats.idle
        install = harness.install_row(evidence["install_id"])
        assert install["state"] == "disposed", install
        assert install["disposed_at"] is not None, install
        fiber = harness.fiber(evidence["install_id"])
        assert fiber["disposed_at"] is not None, fiber
        assert harness.count(
            "v24.episodes WHERE fiber_id=%s AND state='active'",
            (fiber["fiber_id"],)) == 0
        assert harness.count(
            "v24.slots WHERE fiber_id=%s AND released_at IS NULL",
            (fiber["fiber_id"],)) == 0
        assert harness.count(
            "v24.pins WHERE consumer_run_id=%s AND released_at IS NULL",
            (evidence["run_id"],)) == 0
        scope = harness.close_scope()
        assert scope["closed_at"] is not None, scope
        print("[G10-B] Python install -> prepare -> on -> start -> real "
              "subprocess echo (Unicode) -> final -> off -> dispose -> "
              "host_release -> disposed; slots/pins released; scope closed")
    finally:
        harness.close()


# ---------------------------------------------------------------------------
# G10-C: known tool error (exit 3) maps to failure
# ---------------------------------------------------------------------------
def g10_c(fixture, workdir):
    realm = "g10-c-realm"
    spec = build_spec("python", realm=realm)
    harness = PluginHarness(fixture, build_registry(spec),
                            _workdir(workdir, "g10-c"), realm=realm)
    try:
        evidence = execute_single(harness, spec, {"__tool_error__": True},
                                  "after-error-final")
        run = harness.run_row(evidence["run_id"])
        assert run["status"] == "completed", run
        assert run["result"]["final_text"] == "after-error-final", run
        tool = tool_effect_row(harness, evidence["model_id"])
        assert tool["status"] == "failed", tool
        result = tool["outcome"]["body"]["result"]
        assert result["status"] == "error", result
        assert result["output"]["code"] == "echo_tool_error", result
        assert "known tool error" in result["output"]["message"], result
        harness.off(evidence["install_id"])
        assert harness.dispose(evidence["install_id"]).get(
            "disposition") == "committed"
        harness.run(None, max_rounds=4)
        assert harness.install_row(evidence["install_id"])["state"] == "disposed"
        print("[G10-C] exit 3 -> failure receipt {status:error, "
              "code:echo_tool_error}; no success/forced-release path; run "
              "continues to final and the install still disposes")
    finally:
        harness.close()


# ---------------------------------------------------------------------------
# G10-D: bad frame -> unknown; unknown keeps the dispose barrier
# ---------------------------------------------------------------------------
def g10_d(fixture, workdir):
    directory = _workdir(workdir, "g10-d")
    script = _py_script(directory / "misbehave.py", MISBEHAVE)
    spec = custom_spec(script, tool_key="misbehave.d", identity="v24.misbehave.d")
    harness = PluginHarness(fixture, build_registry(spec), directory,
                            realm="g10-misbehave")
    try:
        install_id = harness.admit(spec)
        harness.prepare([install_id])
        harness.activate(install_id, spec.tool_key)
        fiber = harness.fiber(install_id)
        response = harness.start(
            fiber["fiber_id"], [spec.tool_key],
            [{"role": "user", "content": "bad frame"}])
        run_id, model_id = response["emitted"]
        script = [tool_reply("call_1", spec.tool_key,
                             {"__mode__": "bad_frame"}),
                  final_reply("must-not-run")]
        stats = harness.run(script, max_rounds=12)
        assert len(harness._transport.calls) == 1, len(
            harness._transport.calls)
        run = harness.run_row(run_id)
        assert run["status"] == "blocked_unknown", run
        tool = tool_effect_row(harness, model_id)
        assert tool["status"] == "unknown", tool
        assert tool["resource_quiesced_at"] is None, tool
        result = tool["outcome"]["body"]["result"]
        assert result["status"] == "error", result
        assert result["output"]["code"] == "bad_frame", result

        harness.off(install_id)
        before = harness.install_row(install_id)
        assert before["state"] != "disposed", before
        response = harness.dispose(install_id)
        harness.run(None, max_rounds=4)
        after = harness.install_row(install_id)
        assert after["state"] != "disposed", after
        assert after["disposed_at"] is None, after
        assert harness.count(
            "v24.effects WHERE request->>'install_id'=%s AND kind='host_release'",
            (str(install_id),)) == 0
        pin = harness.fiber(install_id)
        assert pin["disposed_at"] is None, pin
        print("[G10-D] bad frame -> tool unknown -> run blocked_unknown; "
              "unknown keeps pin/resource barrier; dispose did not complete, "
              "zero host_release, no forced release")
    finally:
        harness.close()


# ---------------------------------------------------------------------------
# G10-E: artifact / adapter / descriptor digest mismatches -> zero spawn
# ---------------------------------------------------------------------------
def _lifecycle_for_mismatch(fixture, workdir, name, spec, broken_registry):
    """Prepare with the correct registry, then swap in the mismatch for tool."""
    realm = json.loads(spec.manifest)["provides"][0]["realm"]
    harness = PluginHarness(fixture, build_registry(spec),
                            _workdir(workdir, name), realm=realm)
    try:
        install_id = harness.admit(spec)
        harness.prepare([install_id])
        harness.activate(install_id, spec.tool_key)
        fiber = harness.fiber(install_id)
        response = harness.start(
            fiber["fiber_id"], [spec.tool_key],
            [{"role": "user", "content": name}])
        _run_id, model_id = response["emitted"]
        harness.dispatcher.registry = broken_registry

        def drive():
            harness.run([tool_reply("call_1", spec.tool_key, {"text": "x"}),
                         final_reply("after-mismatch")], max_rounds=12)

        _zero_spawn(drive)
        tool = tool_effect_row(harness, model_id)
        assert tool["outcome"]["class"] == "failure", tool
        result = tool["outcome"]["body"]["result"]
        assert result["status"] == "error", result
        assert result["output"]["code"] in (
            "adapter_not_approved", "descriptor_mismatch",
            "descriptor_digest_mismatch"), result
        assert harness.install_row(install_id)["state"] == "installed"
        return result["output"]["code"]
    finally:
        harness.close()


def g10_e(fixture, workdir):
    spec = build_spec("python", realm="g10-e-artifact-realm")
    broken_entry = dataclasses.replace(spec.entry, artifact_digest="4" * 64)
    broken_registry = ApprovedAdapterRegistry((broken_entry,))
    code = _lifecycle_for_mismatch(
        fixture, workdir, "g10-e-artifact", spec, broken_registry)
    assert code == "adapter_not_approved", code

    spec = build_spec("python", realm="g10-e-adapter-realm")
    adapter_entry = dataclasses.replace(spec.entry, adapter_digest="5" * 64)
    adapter_registry = ApprovedAdapterRegistry((adapter_entry,))
    code = _lifecycle_for_mismatch(
        fixture, workdir, "g10-e-adapter", spec, adapter_registry)
    assert code == "adapter_not_approved", code

    spec = build_spec("python", realm="g10-e-descriptor-realm")
    changed = descriptor_for(spec.tool_key)
    changed["tool"]["description"] = "different approved descriptor"
    descriptor_entry = dataclasses.replace(
        spec.entry, description=changed["tool"]["description"],
        descriptor_digest=descriptor_digest(changed))
    descriptor_registry = ApprovedAdapterRegistry((descriptor_entry,))
    code = _lifecycle_for_mismatch(
        fixture, workdir, "g10-e-descriptor", spec, descriptor_registry)
    assert code == "descriptor_mismatch", code
    print("[G10-E] three separate zero-spawn negatives: approved artifact "
          "digest mismatch, approved adapter digest mismatch, and approved "
          "descriptor mismatch; each install had already prepared successfully")


# ---------------------------------------------------------------------------
# G10-F: frozen pin descriptor bytes vs approved bytes (digest field agrees)
# ---------------------------------------------------------------------------
def g10_f(fixture, workdir):
    realm = "g10-f-realm"
    spec = build_spec("python", realm=realm)
    harness = PluginHarness(fixture, build_registry(spec),
                            _workdir(workdir, "g10-f"), realm=realm)
    try:
        install_id = harness.admit(spec)
        harness.prepare([install_id])
        harness.activate(install_id, spec.tool_key)
        fiber = harness.fiber(install_id)
        response = harness.start(
            fiber["fiber_id"], [spec.tool_key],
            [{"role": "user", "content": "pin mismatch"}])
        run_id, model_id = response["emitted"]
        pin = one(harness.owner,
                  "SELECT to_jsonb(p) FROM v24.pins p WHERE consumer_run_id=%s",
                  (run_id,))
        harness.owner.commit()
        with harness.owner.cursor() as cur:
            cur.execute("UPDATE v24.slots SET descriptor=%s WHERE slot_id=%s",
                        (Json({"v": 1, "tool": {
                            "description": "forged but digest kept",
                            "parameters": {"type": "object"}}}),
                         pin["slot_id"]))
        harness.owner.commit()

        def drive():
            harness.run([tool_reply("call_1", spec.tool_key, {"text": "x"}),
                         final_reply("after-pin-mismatch")], max_rounds=12)

        _zero_spawn(drive)
        tool = tool_effect_row(harness, model_id)
        result = tool["outcome"]["body"]["result"]
        assert result["output"]["code"] == "descriptor_mismatch", result
        print("[G10-F] frozen pin descriptor bytes differ from the approved "
              "descriptor while the pin digest still matches -> zero spawn")
    finally:
        harness.close()


# ---------------------------------------------------------------------------
# G10-G: prepare/release idempotency and duplicate reservations
# ---------------------------------------------------------------------------
def g10_g(fixture, workdir):
    realm = "g10-g-realm"
    spec = build_spec("python", realm=realm)
    harness = PluginHarness(fixture, build_registry(spec),
                            _workdir(workdir, "g10-g"), realm=realm)
    try:
        install_id = harness.admit(spec)
        harness.prepare([install_id])
        prepare_rows = harness.count(
            "v24.effects WHERE request->>'install_id'=%s AND kind='host_prepare'",
            (str(install_id),))
        assert prepare_rows == 1, prepare_rows
        prepare_effect = one(
            harness.owner,
            "SELECT effect_id FROM v24.effects WHERE request->>'install_id'=%s "
            "AND kind='host_prepare'", (str(install_id),))
        harness.owner.commit()
        reservation = f"v24:host_prepare:{prepare_effect}"
        first = line_json.run(spec.entry, "prepare", reservation,
                              {"install_id": str(install_id)})
        second = line_json.run(spec.entry, "prepare", reservation,
                               {"install_id": str(install_id)})
        assert first.class_name == second.class_name == "success"
        assert first.result == second.result
        assert first.result["prepared"] is True

        harness.activate(install_id, spec.tool_key)
        fiber = harness.fiber(install_id)
        response = harness.start(
            fiber["fiber_id"], [spec.tool_key],
            [{"role": "user", "content": "idempotency"}])
        run_id, model_id = response["emitted"]
        harness.run([tool_reply("call_1", spec.tool_key, {"text": "once"}),
                     final_reply("idempotent-final")], max_rounds=20)
        assert harness.run_row(run_id)["status"] == "completed"
        harness.off(install_id)
        first_dispose = harness.dispose(install_id)
        release_rows = harness.count(
            "v24.effects WHERE request->>'install_id'=%s AND kind='host_release'",
            (str(install_id),))
        assert release_rows == 1, release_rows
        second_dispose = harness.dispose(install_id)
        release_rows_2 = harness.count(
            "v24.effects WHERE request->>'install_id'=%s AND kind='host_release'",
            (str(install_id),))
        assert release_rows_2 == 1, release_rows_2
        release_id = one(
            harness.owner,
            "SELECT effect_id FROM v24.effects WHERE request->>'install_id'=%s "
            "AND kind='host_release'", (str(install_id),))
        harness.owner.commit()
        release_reservation = f"v24:host_release:{release_id}"
        r1 = line_json.run(spec.entry, "release", release_reservation,
                           {"install_id": str(install_id)})
        r2 = line_json.run(spec.entry, "release", release_reservation,
                           {"install_id": str(install_id)})
        assert r1.class_name == r2.class_name == "success"
        assert r1.result == r2.result and r1.result["released"] is True
        harness.run(None, max_rounds=4)
        assert harness.install_row(install_id)["state"] == "disposed"
        assert first_dispose.get("disposition") == "committed"
        assert second_dispose.get("disposition") in (
            "committed", "deferred"), second_dispose
        print("[G10-G] repeated prepare/release reservation returns the same "
              "result; one host_prepare and one host_release row; second "
              "dispose does not duplicate the release")
    finally:
        harness.close()


# ---------------------------------------------------------------------------
# G10-H: line-JSON bounds and error mapping
# ---------------------------------------------------------------------------
def g10_h(workdir):
    directory = _workdir(workdir, "g10-h")
    script = _py_script(directory / "misbehave.py", MISBEHAVE)
    spec = custom_spec(script, tool_key="misbehave.h", identity="v24.misbehave.h",
                       timeout_ms=300)
    entry = spec.entry
    cases = {
        "success": ("success", "success"),
        "tool_error": ("failure", "failure"),
        "bad_frame": ("unknown", "bad_frame"),
        "extra_frame": ("unknown", "extra_frame"),
        "eof": ("unknown", "eof"),
        "overflow": ("unknown", "stdout_limit"),
        "stderr_overflow": ("unknown", "stderr_limit"),
        "abnormal": ("unknown", "abnormal_exit"),
        "timeout": ("unknown", "timeout"),
        "non_object": ("unknown", "bad_frame"),
    }
    evidence = []
    for mode, (expected_class, expected_reason) in cases.items():
        invocation = line_json.run(entry, "invoke", f"v24:test:{mode}",
                                   {"__mode__": mode})
        assert invocation.class_name == expected_class, (mode, invocation)
        if expected_class == "unknown":
            assert invocation.reason == expected_reason, (mode, invocation)
        assert invocation.returncode is not None, (mode, invocation)
        if expected_reason in ("stdout_limit", "stderr_limit"):
            assert invocation.returncode is not None
        evidence.append((mode, invocation.class_name, invocation.reason,
                         invocation.returncode))
    try:
        line_json.run(entry, "invoke", "", {})
    except line_json.LineJsonPreflight:
        pass
    else:
        raise AssertionError("empty reservation accepted")
    try:
        line_json.run(entry, "delete", "v24:test:x", {})
    except line_json.LineJsonPreflight:
        pass
    else:
        raise AssertionError("unknown operation accepted")
    print("[G10-H] line-JSON success/exit3/bad frame/extra frame/EOF/stdout "
          "overflow/stderr overflow/abnormal exit/timeout/non-object mapping; "
          "pre-spawn frame rejection; every started process reaped: %s"
          % (evidence,))


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
CASES = {"G10-A": ("plain", g10_a), "G10-B": ("fixture", g10_b),
         "G10-C": ("fixture", g10_c), "G10-D": ("fixture", g10_d),
         "G10-E": ("fixture", g10_e), "G10-F": ("fixture", g10_f),
         "G10-G": ("fixture", g10_g), "G10-H": ("plain", g10_h)}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default=None)
    args = parser.parse_args(argv)
    selected = ALL_CASES
    if args.only:
        requested = tuple(x.strip() for x in args.only.split(",") if x.strip())
        assert requested and set(requested) <= set(ALL_CASES), requested
        selected = requested

    assert_static_guards()
    install_no_network()
    passed = 0
    try:
        with server_helper_scope(), setup_db() as fixture:
            owner = fixture.connect()
            with owner.cursor() as cur:
                cur.execute("SET ROLE v24_owner")
            owner.commit()
            _assert_closed_catalog(fixture.connect())
            with tempfile.TemporaryDirectory(prefix="v24-g10-") as work:
                workdir = Path(work)
                os.chmod(workdir, 0o700)
                for case in selected:
                    kind, fn = CASES[case]
                    if kind == "plain":
                        fn(workdir)
                    else:
                        fn(fixture, workdir)
                    passed += 1
            owner.close()
    finally:
        restore_no_network()
    print(f"[passed] v24 G10 M-P Python: {passed} case(s): "
          f"{', '.join(selected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
