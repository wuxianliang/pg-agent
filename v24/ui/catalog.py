"""Dynamic v2 catalog for the staged UI family artifacts."""
from __future__ import annotations

import hashlib
import ast
import os
import re
import stat
import sys
from html import escape
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


def _skill_metadata(data: bytes, directory: str) -> dict[str, str]:
    # A deliberately small plain-scalar frontmatter grammar, not general YAML.
    lines = data.split(b"\n")
    if len(lines) < 4 or [line.removesuffix(b"\r") for line in (lines[0], lines[3])] != [b"---", b"---"]:
        raise ValueError("invalid_skill")
    fields = {}
    for raw in lines[1:3]:
        line = raw.removesuffix(b"\r").decode("utf-8")
        match = re.fullmatch(r"(name|description): +(.+)", line)
        if not match or match[1] in fields:
            raise ValueError("invalid_skill")
        value = match[2].strip(" ")
        if (not value or value[0] in "\"'[]{} ,#&*!|>%@`"
                or re.search(r"^[-?:](?:\s|$)|:(?:\s|$)|\s#", value)
                or any(ord(c) < 32 or 127 <= ord(c) <= 159 or ord(c) in (0xFFFE, 0xFFFF) for c in value)):
            raise ValueError("invalid_skill")
        fields[match[1]] = value
    if (not re.fullmatch(r"[a-z0-9-]{1,64}", fields["name"])
            or fields["name"] != directory or len(fields["description"]) > 1024):
        raise ValueError("invalid_skill")
    return fields


def available_skills() -> str:
    """Describe immediate skills from the effective root without following links.

    An unavailable root is empty; a malformed discovered skill fails closed.
    open_env owns the default root. This pure discovery helper never changes it.
    """
    empty = "<available_skills>\n</available_skills>"
    configured = os.environ.get("V24_SKILLS_ROOT")
    if not configured:
        return empty
    root_fd = None
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        root = Path(configured)
        if not root.is_absolute() or root.resolve() != root:
            return empty
        # Anchor every component so symlink replacement cannot escape the root.
        root_fd = os.open(root.anchor, directory_flags)
        for part in root.parts[1:]:
            next_fd = os.open(part, directory_flags, dir_fd=root_fd)
            os.close(root_fd)
            root_fd = next_fd
        entries = sorted(os.listdir(root_fd))
    except (OSError, ValueError, RuntimeError):
        if root_fd is not None:
            os.close(root_fd)
        return empty
    skills = []
    try:
        for name in entries:
            info = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                raise ValueError("invalid_skill")
            if not stat.S_ISDIR(info.st_mode):
                continue
            skill_fd = os.open(name, directory_flags, dir_fd=root_fd)
            try:
                try:
                    info = os.stat("SKILL.md", dir_fd=skill_fd, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError("invalid_skill")
                fd = os.open("SKILL.md", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=skill_fd)
                with os.fdopen(fd, "rb") as stream:
                    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                        raise ValueError("invalid_skill")
                    # Only frontmatter is loaded. Legal metadata fits in 8 KiB.
                    fields = _skill_metadata(stream.read(8192), name)
                location = f".v24/skills/{name}/SKILL.md"
                skills.append("  <skill>\n"
                    f"    <name>{escape(fields['name'])}</name>\n"
                    f"    <description>{escape(fields['description'])}</description>\n"
                    f"    <location>{escape(location)}</location>\n"
                    "  </skill>")
            finally:
                os.close(skill_fd)
    except (OSError, ValueError, UnicodeError):
        raise ValueError("invalid_skill") from None
    finally:
        os.close(root_fd)
    return "<available_skills>\n" + "\n".join(skills) + ("\n" if skills else "") + "</available_skills>"


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
