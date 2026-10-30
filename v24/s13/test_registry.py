"""W3 registry contract gate: immutable approvals and pre-spawn matching.

Read-only over the frozen W1 vectors.  No network, DB, Node, subprocess or
artifact execution is performed; artifact checks use patched filesystem calls.
"""
from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v24.host import line_json, registry  # noqa: E402
from v24.host.registry import (  # noqa: E402
    AdapterNotFound,
    ApprovedAdapter,
    ApprovedAdapterRegistry,
    ApprovedPlugin,
    ApprovedTool,
    RegistryError,
    adapter_declaration_digest,
    descriptor_digest,
)
from v24.host.tool_schema import InstanceError  # noqa: E402

S13 = Path(__file__).resolve().parent
MANIFESTS = S13 / "vectors" / "manifest_adapter_v2.json"
DESCRIPTORS = S13 / "vectors" / "descriptor_v2.json"
FORBIDDEN_IMPORTS = ("socket", "http", "urllib", "requests", "ftplib",
                     "smtplib", "telnetlib", "aiohttp", "httpx")


def expect_registry(fn, reason):
    try:
        fn()
    except RegistryError as exc:
        assert str(exc) == reason, (reason, str(exc))
        assert exc.args == (reason,), exc.args
        return
    raise AssertionError(f"expected RegistryError({reason!r})")


def expect_registry_text(fn, text):
    try:
        fn()
    except RegistryError as exc:
        assert text in str(exc), (text, str(exc))
        return
    raise AssertionError(f"expected RegistryError containing {text!r}")


def expect_adapter_not_found(fn, reason):
    try:
        fn()
    except AdapterNotFound as exc:
        assert exc.reason == reason, (reason, exc.reason)
        return
    raise AssertionError(f"expected AdapterNotFound({reason!r})")


def make_adapter(*, adapter_id="v1.adapter", identity="v1.identity",
                 artifact="/tmp/v24-gate-artifact.py", cwd=None,
                 artifact_digest="a" * 64, manifest_digest="b" * 64,
                 adapter_digest="c" * 64, tool_key="read", timeout_ms=5000):
    cwd = cwd or str(Path.cwd())
    descriptor = {"v": 1, "tool": {
        "description": f"v24 reference echo plugin ({tool_key})",
        "parameters": {"type": "object", "properties": {"text": {"type": "string"}},
                       "additionalProperties": True},
    }}
    return ApprovedAdapter(
        adapter_id=adapter_id, language="python", identity=identity, version="1",
        manifest_digest=manifest_digest, artifact_digest=artifact_digest,
        adapter_digest=adapter_digest, descriptor_digest=descriptor_digest(descriptor),
        argv=(sys.executable, artifact), cwd=cwd,
        environment_allowlist=("PATH", "LANG"), tool_key=tool_key,
        description=descriptor["tool"]["description"],
        parameters=descriptor["tool"]["parameters"], timeout_ms=timeout_ms,
    )


def fixture_plugin(manifest, *, language="node", adapter_id="v2.node",
                   workspace_root=None, timeout_cap_ms=25000):
    workspace_root = workspace_root or str(Path.cwd().resolve())
    return ApprovedPlugin.from_manifest(
        manifest, language=language, artifact_digest="d" * 64,
        adapter_id=adapter_id, argv=(sys.executable, "/tmp/v24-gate-plugin.js"),
        cwd=str(Path.cwd().resolve()), environment_allowlist=("PATH", "LANG"),
        workspace_root=workspace_root, timeout_cap_ms=timeout_cap_ms,
    )


def tool_from_descriptor(descriptor, *, key=None):
    return ApprovedTool.from_descriptor(descriptor, key=key or descriptor["tool"]["key"])


def manifest_document(base, *, keys=None):
    result = copy.deepcopy(base)
    if keys is not None:
        result["provides"] = [copy.deepcopy(base["provides"][0]) for _ in keys]
        for provide, key in zip(result["provides"], keys):
            provide["key"] = key
            provide["descriptor"]["tool"]["key"] = key
    return result


def static_guards():
    for path in (Path(__file__), ROOT / "v24/host/registry.py",
                 ROOT / "v24/host/line_json.py"):
        source = path.read_text(encoding="utf-8")
        for name in FORBIDDEN_IMPORTS:
            assert re.search(rf"(?m)^\s*(?:from|import)\s+{re.escape(name)}\b", source) is None, (path, name)
        assert "time." + "sleep" not in source, path
        assert "shell=" + "True" not in source, path


def main() -> int:
    manifests_doc = json.loads(MANIFESTS.read_text(encoding="utf-8"))
    manifest_cases = {case["id"]: case for case in manifests_doc["cases"]}
    descriptor_doc = json.loads(DESCRIPTORS.read_text(encoding="utf-8"))
    descriptor_cases = {case["id"]: case for case in descriptor_doc["cases"]}
    read_v2 = descriptor_cases["descriptor.v2.read"]["input"]
    two_case = manifest_cases["manifest.one_install_two_provides"]
    pending_case = manifest_cases["manifest.five_field_key"]
    tmp = tempfile.TemporaryDirectory(prefix="v24-registry-gate-")
    root = Path(tmp.name).resolve()
    calls = []
    artifact_calls = []
    popen_calls = []
    manifest_bytes = 0
    zero_spawn_paths = 0
    construction_reasons = 0
    cases = 0

    def record_process(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("registry gate invoked line_json.run_process")

    def record_artifact(*args, **kwargs):
        artifact_calls.append((args, kwargs))
        raise AssertionError("registry gate invoked require_artifact")

    def record_popen(*args, **kwargs):
        popen_calls.append((args, kwargs))
        raise AssertionError("registry gate touched subprocess.Popen")

    try:
        # Every constructor/matcher negative below is guarded against an
        # artifact check, line-json process call, or real subprocess launch.
        with patch.object(ApprovedAdapter, "require_artifact", record_artifact), \
             patch.object(ApprovedPlugin, "require_artifact", record_artifact), \
             patch.object(line_json, "run_process", record_process), \
             patch.object(subprocess, "Popen", record_popen):
            # 1-2. Adapter declarations are compact canonical bytes, not merely
            # digest constants copied from the vector.
            cases += 2
            manifest_bytes += 2
            for case_id, language, length, digest in (
                ("manifest.adapter.python_read", "python", 89,
                 "90c4dca5b11d830300e898129e2a6210cf694f5c1f31dd67985a444448a0f7cf"),
                ("manifest.adapter.node_list_search", "node", 87,
                 "06451360abe502b96b23115973a5797af50954909a9555a8d4e0a0a9fd9a60ec"),
            ):
                case = manifest_cases[case_id]
                encoded = registry.compact_json(case["input"])
                assert encoded.hex() == case["expected_hex"]
                assert len(encoded) == length == case["expected_length"]
                assert hashlib.sha256(encoded).hexdigest() == digest == case["expected_sha256"]
                assert adapter_declaration_digest(language) == digest

            # 3. One node install produces separate ApprovedTool bindings and
            # retains per-tool timeouts from the descriptor.
            cases += 1
            manifest_bytes += 1
            encoded = registry.compact_json(two_case["input"])
            assert len(encoded) == two_case["expected_length"] == 4745
            assert hashlib.sha256(encoded).hexdigest() == two_case["expected_sha256"] == \
                "0ad584415af8743045dd12275a54fa2f43a65395fc8669753416688c9c3e3db5"
            plugin = fixture_plugin(two_case["input"], language="node")
            assert plugin.manifest_digest == two_case["manifest_digest"] == \
                "0ad584415af8743045dd12275a54fa2f43a65395fc8669753416688c9c3e3db5"
            # Raw bytes and UTF-8 str retain noncanonical manifest identity.
            raw_manifest = json.dumps(two_case["input"], ensure_ascii=False,
                                      indent=2).encode("utf-8") + b"\n"
            raw_digest = hashlib.sha256(raw_manifest).hexdigest()
            assert raw_manifest != encoded
            assert raw_digest != plugin.manifest_digest
            for manifest_input in (raw_manifest, raw_manifest.decode("utf-8")):
                raw_plugin = fixture_plugin(manifest_input, language="node")
                assert raw_plugin.manifest_digest == raw_digest
                assert raw_plugin.tools == plugin.tools

            install = {name: getattr(plugin, name) for name in
                       ("identity", "version", "manifest_digest", "artifact_digest", "adapter_digest")}
            registry_union = ApprovedAdapterRegistry((plugin,))
            list_binding = registry_union.match_tool(install, {
                "key": "list", "descriptor": two_case["input"]["provides"][0]["descriptor"],
                "descriptor_digest": plugin.tool_for("list").descriptor_digest,
            }, "list")
            search_binding = registry_union.match_tool(install, {
                "key": "search", "descriptor": two_case["input"]["provides"][1]["descriptor"],
                "descriptor_digest": plugin.tool_for("search").descriptor_digest,
            }, "search")
            assert list_binding.entry is search_binding.entry is plugin
            assert list_binding.tool is plugin.tool_for("list")
            assert search_binding.tool is plugin.tool_for("search")
            assert list_binding.tool is not search_binding.tool
            assert list_binding.tool.timeout_ms == 5000
            assert search_binding.tool.timeout_ms == 15000

            # 4. Reproduce the vector's closed five-field identity set and keep
            # the pending M3 status untouched.
            cases += 1
            expected_fields = pending_case["expected"]["fields"]
            assert pending_case["expected"] == {"field_count": 5, "fields": expected_fields}
            assert set(expected_fields) == {"identity", "version", "manifest_digest",
                                           "artifact_digest", "adapter_digest"}
            key_plugin = fixture_plugin(pending_case["input"]["manifest"], language="python",
                                        adapter_id="five-field")
            key = key_plugin.canonical_key()
            assert len(key) == pending_case["expected"]["field_count"] == 5
            assert key == tuple(getattr(key_plugin, field) for field in expected_fields)
            assert pending_case["status"] == "m3_pending"
            assert pending_case["first_production_stage"] == "M3"

            # 5. v1 field order and descriptor bytes/reasons stay frozen.
            cases += 1
            fields = tuple(field.name for field in dataclasses.fields(ApprovedAdapter))
            assert fields == ("adapter_id", "language", "identity", "version",
                "manifest_digest", "artifact_digest", "adapter_digest", "descriptor_digest",
                "argv", "cwd", "environment_allowlist", "tool_key", "description",
                "parameters", "timeout_ms", "stdout_limit", "stderr_limit")
            assert len(fields) == 17
            adapter = make_adapter(cwd=str(root))
            legacy = ApprovedAdapterRegistry((adapter,))
            good_install = {name: getattr(adapter, name) for name in
                            ("identity", "version", "manifest_digest", "artifact_digest", "adapter_digest")}
            assert legacy.match_pin(good_install, {
                "descriptor": adapter.descriptor, "descriptor_digest": adapter.descriptor_digest,
            }) is adapter
            assert registry.pg_jsonb_text(adapter.descriptor).encode("utf-8") == adapter.descriptor_bytes
            assert adapter.descriptor == {"v": 1, "tool": {
                "description": "v24 reference echo plugin (read)",
                "parameters": {"type": "object", "properties": {"text": {"type": "string"}},
                               "additionalProperties": True},
            }}
            expect_adapter_not_found(lambda: legacy.match_pin(good_install, {}), "descriptor_missing")
            expect_adapter_not_found(lambda: legacy.match_pin(good_install, {"descriptor": adapter.descriptor}),
                                     "descriptor_digest_missing")
            assert dataclasses.fields(ApprovedAdapter)[13].name == "parameters"

            cases += 1
            # 6. tools count boundaries: 1 and 16 accepted; 0 and 17 rejected.
            one = fixture_plugin(two_case["input"], language="node", adapter_id="one-tool")
            assert len(one.tools) == 2
            base_manifest = copy.deepcopy(two_case["input"])
            single_manifest = copy.deepcopy(base_manifest)
            single_manifest["provides"] = [single_manifest["provides"][0]]
            assert len(fixture_plugin(single_manifest, adapter_id="one").tools) == 1
            sixteen = manifest_document(base_manifest, keys=[f"t{i}" for i in range(16)])
            assert len(fixture_plugin(sixteen, adapter_id="sixteen").tools) == 16
            for count in (0, 17):
                bad = copy.deepcopy(base_manifest)
                bad["provides"] = (bad["provides"] * 9)[:count]
                expect_registry(lambda bad=bad: fixture_plugin(bad), "manifest_invalid")
            # The direct plugin constructor reports tools_invalid for the same bounds.
            for count in (0, 17):
                too_many = tuple(plugin.tools[0] for _ in range(count))
                expect_registry(lambda too_many=too_many: dataclasses.replace(plugin, tools=too_many),
                                "tools_invalid")

            cases += 1
            # 7. Duplicate provided keys fail closed.
            duplicate = copy.deepcopy(base_manifest)
            duplicate["provides"][1]["key"] = "list"
            duplicate["provides"][1]["descriptor"] = copy.deepcopy(duplicate["provides"][0]["descriptor"])
            expect_registry(lambda: fixture_plugin(duplicate), "duplicate_tool_key")
            dup_tools = (plugin.tools[0], dataclasses.replace(plugin.tools[0]))
            expect_registry(lambda: dataclasses.replace(plugin, tools=dup_tools), "duplicate_tool_key")

            cases += 2
            # 8-9. Version mix and provide/descriptor key mismatch.
            mixed = copy.deepcopy(base_manifest)
            mixed["provides"][1]["descriptor"]["v"] = 1
            expect_registry(lambda: fixture_plugin(mixed), "mixed_descriptor_versions")
            mismatch = copy.deepcopy(base_manifest)
            mismatch["provides"][0]["key"] = "different"
            expect_registry(lambda: fixture_plugin(mismatch), "descriptor_key_mismatch")

            cases += 1
            # 10. Per-tool timeout over cap, plus exact cap type/range boundaries.
            expect_registry(lambda: fixture_plugin(base_manifest, timeout_cap_ms=4999), "timeout_exceeds_cap")
            for cap in (0, 25001, True):
                expect_registry(lambda cap=cap: fixture_plugin(base_manifest, timeout_cap_ms=cap),
                                "timeout_cap_invalid")
            assert fixture_plugin(single_manifest, timeout_cap_ms=5000).timeout_cap_ms == 5000
            boundary = copy.deepcopy(single_manifest)
            boundary["provides"][0]["descriptor"]["tool"]["limits"]["timeout_ms"] = 25000
            assert fixture_plugin(boundary, timeout_cap_ms=25000).tools[0].timeout_ms == 25000

            cases += 1
            # 11. workspace_root absolute/existing/realpath and symlink policy.
            expect_registry(lambda: fixture_plugin(single_manifest, workspace_root="relative"),
                            "workspace_root_invalid")
            expect_registry(lambda: fixture_plugin(single_manifest,
                            workspace_root=str(root / "missing")), "workspace_root_invalid")
            link = root / "root-link"
            try:
                link.symlink_to(root, target_is_directory=True)
            except (OSError, NotImplementedError):
                print("[SKIP] platform cannot create symlink required for workspace_root assertion")
                return 2
            expect_registry(lambda: fixture_plugin(single_manifest, workspace_root=str(link)),
                            "workspace_root_invalid")

            cases += 1
            # 12. Renderer id and digest are checked against the frozen registry.
            unknown = copy.deepcopy(single_manifest)
            unknown["provides"][0]["descriptor"]["tool"]["render"]["id"] = "v24.fs.unknown.text"
            expect_registry(lambda: fixture_plugin(unknown), "renderer_not_approved")
            tampered_renderer = copy.deepcopy(single_manifest)
            tampered_renderer["provides"][0]["descriptor"]["tool"]["render"]["digest"] = "0" * 64
            expect_registry(lambda: fixture_plugin(tampered_renderer), "renderer_digest_mismatch")

            cases += 1
            # 13. Six match_tool reasons, each pre-spawn; the match is pure.
            entry = plugin
            registry_union = ApprovedAdapterRegistry((entry,))
            install = {name: getattr(entry, name) for name in
                       ("identity", "version", "manifest_digest", "artifact_digest", "adapter_digest")}
            tool = entry.tool_for("list")
            good_pin = {"key": "list", "descriptor": tool.descriptor,
                        "descriptor_digest": tool.descriptor_digest}
            expect_adapter_not_found(lambda: registry_union.match_tool(install, good_pin, "nope"),
                                     "pin_key_mismatch")
            zero_spawn_paths += 1
            expect_adapter_not_found(lambda: registry_union.match_tool(install, {**good_pin, "key": "nope"}, "nope"),
                                     "tool_not_approved")
            zero_spawn_paths += 1
            expect_adapter_not_found(lambda: registry_union.match_tool(install, {"key": "list"}, "list"),
                                     "descriptor_missing")
            zero_spawn_paths += 1
            expect_adapter_not_found(lambda: registry_union.match_tool(install,
                {"key": "list", "descriptor": tool.descriptor}, "list"), "descriptor_digest_missing")
            zero_spawn_paths += 1
            expect_adapter_not_found(lambda: registry_union.match_tool(install,
                {**good_pin, "descriptor": {"v": 2}}, "list"), "descriptor_mismatch")
            zero_spawn_paths += 1
            expect_adapter_not_found(lambda: registry_union.match_tool(install,
                {**good_pin, "descriptor_digest": "0" * 64}, "list"), "descriptor_digest_mismatch")
            zero_spawn_paths += 1

            cases += 1
            # 14. v2 entries never pass the v1 pin API.
            expect_adapter_not_found(lambda: registry_union.match_pin(install, good_pin), "protocol_mismatch")

            cases += 1
            # 15. Union indexes preserve tuple entries and reject both collision types.
            adapter2 = make_adapter(cwd=str(root), adapter_id="v1.other")
            union = ApprovedAdapterRegistry((adapter2, plugin))
            assert isinstance(union.entries, tuple) and union.entries == (adapter2, plugin)
            assert union.by_id(adapter2.adapter_id) is adapter2
            assert union.by_id(plugin.adapter_id) is plugin
            assert isinstance(union.by_id(plugin.adapter_id), ApprovedPlugin)
            expect_registry(lambda: ApprovedAdapterRegistry((plugin, dataclasses.replace(plugin,
                            adapter_id="different"))),
                            f"ambiguous approved adapter for install key {plugin.canonical_key()}")
            expect_registry(lambda: ApprovedAdapterRegistry((plugin, dataclasses.replace(plugin,
                            adapter_id=plugin.adapter_id, identity="another"))),
                            f"duplicate adapter_id {plugin.adapter_id!r}")

            cases += 1
            # 16. The three key digests all participate in install approval.
            for name in ("manifest_digest", "artifact_digest", "adapter_digest"):
                bad_install = dict(install)
                bad_install[name] = "0" * 64
                expect_adapter_not_found(lambda bad_install=bad_install:
                                         registry_union.match_tool(bad_install, good_pin, "list"),
                                         "adapter_not_approved")

            cases += 1
            # 17a. v1 synthetic ApprovedTool has no schema closures. v2 closures
            # enforce descriptor schemas, are regenerated by replace, and are
            # bound to the approved descriptor fields.
            v1_binding = legacy.match_tool(good_install if False else {
                name: getattr(adapter, name) for name in
                ("identity", "version", "manifest_digest", "artifact_digest", "adapter_digest")
            }, {"key": "read", "descriptor": adapter.descriptor,
                "descriptor_digest": adapter.descriptor_digest}, "read")
            assert v1_binding.tool.parameters_check is None
            assert v1_binding.tool.output_check is None
            v2_tool = tool_from_descriptor(read_v2)
            assert v2_tool.parameters_check is not None and v2_tool.output_check is not None
            v2_tool.parameters_check({"path": "README.md"})
            v2_tool.output_check({"path": "README.md", "text": "", "start_line": 0,
                "end_line": 0, "total_lines": 0, "final_newline": False,
                "truncated": False, "truncated_by": None, "next_offset": None})
            for fn, value in ((v2_tool.parameters_check, {"path": 1}),
                              (v2_tool.output_check, {"path": "README.md"})):
                try:
                    fn(value)
                except InstanceError:
                    pass
                else:
                    raise AssertionError("schema closure accepted invalid instance")
            # Rebuilding an ApprovedTool recompiles both descriptor-bound closures.
            rebuilt_tool = dataclasses.replace(v2_tool)
            assert rebuilt_tool == v2_tool
            assert rebuilt_tool.parameters_check is not v2_tool.parameters_check
            assert rebuilt_tool.output_check is not v2_tool.output_check
            rebuilt_tool.parameters_check({"path": "README.md"})
            rebuilt_tool.output_check({"path": "README.md", "text": "", "start_line": 0,
                "end_line": 0, "total_lines": 0, "final_newline": False,
                "truncated": False, "truncated_by": None, "next_offset": None})
            for fn, value in ((rebuilt_tool.parameters_check, {"path": 1}),
                              (rebuilt_tool.output_check, {"path": "README.md"})):
                try:
                    fn(value)
                except InstanceError:
                    pass
                else:
                    raise AssertionError("rebuilt schema closure accepted invalid instance")
            # Replacing the plugin retains its already-approved nested tools.
            replaced_plugin = dataclasses.replace(plugin, cwd="/tmp")
            replaced = replaced_plugin.tool_for("list")
            original_list = plugin.tool_for("list")
            assert replaced.parameters_check is original_list.parameters_check
            replaced.parameters_check({})
            try:
                replaced.parameters_check({"unexpected": 1})
            except InstanceError:
                pass
            else:
                raise AssertionError("replace lost descriptor-bound closure")
            changed = dict(v2_tool.descriptor)
            changed["tool"] = dict(changed["tool"])
            changed["tool"]["limits"] = dict(changed["tool"]["limits"])
            changed["tool"]["limits"]["timeout_ms"] = 6000
            expect_registry(lambda: dataclasses.replace(v2_tool, descriptor=changed),
                            "approved_tool_invalid")
            digest_only = dict(v2_tool.descriptor)
            digest_only["tool"] = dict(digest_only["tool"])
            digest_only["tool"]["description"] += " changed"
            expect_registry_text(lambda: dataclasses.replace(v2_tool, descriptor=digest_only),
                                 "descriptor_digest does not match the approved descriptor")

            # Construction reason inventory includes all 14 W3 tokens. Cases
            # above exercise the listed reasons; add explicit protocol and
            # manifest/declaration/descriptor-shape probes here.
            reason_probes = {
                "approved_tool_invalid": lambda: dataclasses.replace(v2_tool, timeout_ms=True),
                "protocol_invalid": lambda: dataclasses.replace(plugin, protocol=1),
                "tools_invalid": lambda: dataclasses.replace(plugin, tools=[]),
                "duplicate_tool_key": lambda: dataclasses.replace(plugin, tools=(plugin.tools[0], plugin.tools[0])),
                "workspace_root_invalid": lambda: dataclasses.replace(plugin, workspace_root="relative"),
                "timeout_cap_invalid": lambda: dataclasses.replace(plugin, timeout_cap_ms=True),
                "manifest_invalid": lambda: ApprovedPlugin.from_manifest({}, language="node",
                    artifact_digest="d" * 64, adapter_id="bad", argv=(sys.executable, "/tmp/a"),
                    cwd=str(root), environment_allowlist=(), workspace_root=str(root)),
                "adapter_digest_mismatch": lambda: fixture_plugin({**single_manifest,
                    "adapter_digest": "0" * 64}),
                "invalid_descriptor": lambda: ApprovedTool("x", {"v": 3}, "0" * 64, 1, None, None),
                "descriptor_key_mismatch": lambda: tool_from_descriptor(read_v2, key="other"),
                "renderer_not_approved": lambda: fixture_plugin(unknown),
                "renderer_digest_mismatch": lambda: fixture_plugin(tampered_renderer),
                "mixed_descriptor_versions": lambda: fixture_plugin(mixed),
                "timeout_exceeds_cap": lambda: fixture_plugin(base_manifest, timeout_cap_ms=4999),
            }
            assert len(reason_probes) == 14
            for reason, probe in reason_probes.items():
                expect_registry(probe, reason)
                construction_reasons += 1

            assert cases == 17
            assert manifest_bytes == 3
            assert zero_spawn_paths == 6
            assert construction_reasons == 14

        assert calls == [], calls
        assert artifact_calls == [], artifact_calls
        assert popen_calls == [], popen_calls
        static_guards()

        # Artifact reason parity is the one intentional call to require_artifact;
        # patch pathlib operations so no real artifact is read or executed.
        probe_adapter = make_adapter(cwd=str(root))
        probe_plugin = plugin
        reason_for = {
            "missing": ("artifact_missing", "missing"),
            "outside": ("artifact_outside_cwd", "outside"),
            "not_regular": ("artifact_not_regular", "not_regular"),
            "unreadable": ("artifact_unreadable", "unreadable"),
            "digest": ("artifact_digest_mismatch", "digest"),
        }
        path_type = type(Path())
        for name, (expected, mode) in reason_for.items():
            for entry in (probe_adapter, probe_plugin):
                if mode == "missing":
                    with patch.object(path_type, "resolve", side_effect=FileNotFoundError):
                        expect_adapter_not_found(entry.require_artifact, expected)
                elif mode == "outside":
                    with patch.object(path_type, "resolve", side_effect=[Path("/tmp/outside.py"), root]):
                        expect_adapter_not_found(entry.require_artifact, expected)
                elif mode == "not_regular":
                    with patch.object(path_type, "resolve", side_effect=[root / "artifact.py", root]), \
                         patch.object(path_type, "stat", return_value=type("S", (), {"st_mode": 0o040755})()):
                        expect_adapter_not_found(entry.require_artifact, expected)
                elif mode == "unreadable":
                    with patch.object(path_type, "resolve", side_effect=[root / "artifact.py", root]), \
                         patch.object(path_type, "stat", side_effect=OSError("unreadable")):
                        expect_adapter_not_found(entry.require_artifact, expected)
                else:
                    with patch.object(path_type, "resolve", side_effect=[root / "artifact.py", root]), \
                         patch.object(path_type, "stat", return_value=type("S", (), {"st_mode": 0o100600})()), \
                         patch.object(path_type, "read_bytes", return_value=b"different bytes"):
                        expect_adapter_not_found(entry.require_artifact, expected)
        print(f"[passed] W3 registry contract; cases={cases}; "
              f"manifest_bytes={manifest_bytes}; zero_spawn_paths={zero_spawn_paths}; "
              f"construction_reasons={construction_reasons}")
        return 0
    finally:
        tmp.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
