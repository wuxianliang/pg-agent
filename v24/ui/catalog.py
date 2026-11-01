"""Dynamic v2 catalog for the staged UI family artifacts."""
from __future__ import annotations

import hashlib
import ast
import sys
from dataclasses import dataclass
from pathlib import Path

from v24.host.canonical import compact_json
from v24.host.registry import ApprovedAdapterRegistry, ApprovedPlugin, ApprovedTool, adapter_declaration_digest
from v24.host.renderers import RENDERERS

MAX_SAFE_ARGS_BYTES = None
LIMITS = {"max_value_bytes": 40960, "max_content_bytes": 41984, "max_meta_bytes": 4096}
_TOOLSETS = {
    "read": frozenset({"read", "grep", "find", "ls", "read_file", "file_search", "get_file_tree"}),
    "write": frozenset({"read", "grep", "find", "ls", "read_file", "file_search", "get_file_tree", "write", "edit", "apply_edits"}),
    "exec": frozenset({"read", "grep", "find", "ls", "read_file", "file_search", "get_file_tree", "write", "edit", "apply_edits", "bash"}),
}


@dataclass(frozen=True)
class ToolSpec:
    key: str
    description: str
    parameters: dict
    output_schema: dict
    timeout_ms: int
    limits: dict
    concurrency: str
    replay_class: str
    annotations: dict


@dataclass(frozen=True)
class FamilySpec:
    identity: str
    version: str
    artifact: Path
    realm: str
    tools: tuple[ToolSpec, ...]


def _artifact_specs(path: Path, artifact_bytes=None):
    """Extract literal declarations without importing executable artifact code."""
    tree = ast.parse(path.read_bytes() if artifact_bytes is None else artifact_bytes)
    namespace = {}
    required_names = {"FAMILY_IDENTITY", "FAMILY_VERSION", "TOOL_SPECS"}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in required_names:
                    if target.id in namespace: raise ValueError("invalid_catalog")
                    namespace[target.id] = ast.literal_eval(node.value)
    identity = namespace.get("FAMILY_IDENTITY")
    version = namespace.get("FAMILY_VERSION")
    declared = namespace.get("TOOL_SPECS")
    if not isinstance(identity, str) or not isinstance(version, str) or not isinstance(declared, (tuple, list)):
        raise ValueError("invalid_catalog")
    specs = []
    for raw in declared:
        required = {"key", "description", "parameters", "output_schema", "timeout_ms", "limits", "concurrency", "replay_class", "annotations"}
        if not isinstance(raw, dict) or set(raw) != required or not isinstance(raw["key"], str):
            raise ValueError("invalid_catalog")
        specs.append(ToolSpec(**raw))
    if len({spec.key for spec in specs}) != len(specs): raise ValueError("invalid_catalog")
    return identity, version, tuple(specs)


def families(realm: str, toolset: str) -> tuple[FamilySpec, ...]:
    if toolset not in _TOOLSETS:
        raise ValueError("invalid_toolset")
    directory = Path(__file__).parent / "plugins"
    result = []
    allowed = _TOOLSETS[toolset]
    for artifact in sorted(directory.glob("*.py")):
        if artifact.name.startswith("__"):
            continue
        metadata = _artifact_specs(artifact)
        identity, version, declared = metadata
        selected = tuple(spec for spec in declared if spec.key in allowed)
        if selected:
            result.append(FamilySpec(identity, version, artifact, realm, selected))
    return tuple(result)


def _descriptor(spec: ToolSpec) -> dict:
    limits = dict(spec.limits)
    limits.setdefault("max_value_bytes", LIMITS["max_value_bytes"])
    limits.setdefault("max_content_bytes", LIMITS["max_content_bytes"])
    limits.setdefault("max_meta_bytes", LIMITS["max_meta_bytes"])
    return {"v": 2, "tool": {"key": spec.key, "description": spec.description, "parameters": spec.parameters,
        "output_schema": spec.output_schema,
        "render": {"id": "v24.text.plain", "version": 1, "digest": RENDERERS.by_id("v24.text.plain", 1).ref.digest},
        "limits": limits, "concurrency": spec.concurrency, "replay_class": spec.replay_class,
        "annotations": spec.annotations}}


def manifest(family: FamilySpec) -> dict:
    return {"identity": family.identity, "version": family.version, "requires": [],
            "provides": [{"realm": family.realm, "key": spec.key, "descriptor": _descriptor(spec)} for spec in family.tools],
            "adapter_digest": "\\x" + adapter_declaration_digest("python")}


def build_plugin(family: FamilySpec, env) -> ApprovedPlugin:
    artifact = family.artifact.resolve()
    artifact_bytes = artifact.read_bytes()
    identity, version, declared = _artifact_specs(artifact, artifact_bytes)
    if (identity, version) != (family.identity, family.version) or any(spec not in declared for spec in family.tools):
        raise ValueError("catalog_changed")
    raw = compact_json(manifest(family))
    tools = tuple(ApprovedTool.from_descriptor(_descriptor(spec), key=spec.key) for spec in family.tools)
    return ApprovedPlugin(adapter_id=f"{family.identity}.{family.realm}", language="python", identity=family.identity,
        version=family.version, manifest_digest=hashlib.sha256(raw).hexdigest(),
        artifact_digest=hashlib.sha256(artifact_bytes).hexdigest(), adapter_digest=adapter_declaration_digest("python"),
        argv=(sys.executable, str(artifact), "serve"), cwd=str(artifact.parent),
        environment_allowlist=("PATH", "HOME", "LANG", "LC_ALL", "V24_WORKSPACE_ROOT", "V24_SPILL_ROOT", "V24_SKILLS_ROOT"),
        tools=tools, workspace_root=str(env.workspace_root.resolve()), timeout_ms=5000, timeout_cap_ms=25000)


def build_registry(plugins):
    return ApprovedAdapterRegistry(tuple(plugins))


def catalog_digest(families_):
    rows = []
    for family in families_:
        rows.append({"identity": family.identity, "version": family.version,
            "artifact_digest": hashlib.sha256(family.artifact.read_bytes()).hexdigest(),
            "tools": [{"key": spec.key, "descriptor_digest": ApprovedTool.from_descriptor(_descriptor(spec), key=spec.key).descriptor_digest} for spec in family.tools]})
    return hashlib.sha256(compact_json(sorted(rows, key=lambda row: (row["identity"], row["version"])))) .hexdigest()


def toolset_keys(toolset, families_):
    return tuple(spec.key for family in families_ for spec in family.tools)
