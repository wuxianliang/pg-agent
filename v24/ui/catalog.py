"""Dynamic v2 catalog for the staged UI family artifacts."""
from __future__ import annotations

import hashlib
import ast
import os
import re
import stat
import sys
from html import escape
from dataclasses import dataclass, replace
from pathlib import Path

from v24.host.canonical import compact_json
from v24.host.registry import ApprovedAdapterRegistry, ApprovedPlugin, ApprovedTool, adapter_declaration_digest
from v24.host.renderers import RENDERERS

MAX_SAFE_ARGS_BYTES = 128
# Measured 2026-11-04 on the current profile (512 completion cap including
# reasoning): 45 probes across 13 targets 64..124 plus two 128 B repeats per
# class.  The capacity record keeps every attempt and names accepted fidelity
# misses; finish_length at or below the bound is accepted only with its exact
# observed rate, never averaged away.  The batch ran while the prompt already
# rendered 128, so it is a compliance/robustness result, not an unprompted
# threshold.  Working recommendation, not a token guarantee.
# Shared UI/provider limits.  The values are the frozen legacy baseline; the
# capacity checkpoint may recommend a value later, but it must not be guessed.
OUTPUT_TOKEN_CAP = 512
BODY_BYTE_CEILING = 8000
DEFAULT_PROVIDER_TIMEOUT_S = 120.0
DEFAULT_WORKER_LEASE_MS = 30000
DEFAULT_RUN_BUDGET = {"steps": 24, "tool_calls": 24, "tokens": 20000, "wall_ms": 600000}
_DEFAULT_BUDGET_ITEMS = tuple(DEFAULT_RUN_BUDGET.items())


@dataclass(frozen=True)
class UiLimits:
    body_byte_ceiling: int = BODY_BYTE_CEILING
    completion_cap: int = OUTPUT_TOKEN_CAP
    timeout_s: float = DEFAULT_PROVIDER_TIMEOUT_S
    worker_lease_ms: int = DEFAULT_WORKER_LEASE_MS
    budget_items: tuple[tuple[str, int], ...] = _DEFAULT_BUDGET_ITEMS

    def __post_init__(self):
        # These are independent knobs; validate ranges and duplicate budget keys.
        if (isinstance(self.body_byte_ceiling, bool)
                or not isinstance(self.body_byte_ceiling, int)
                or not 1 <= self.body_byte_ceiling <= 65536):
            raise ValueError("body_byte_ceiling")
        if (isinstance(self.completion_cap, bool)
                or not isinstance(self.completion_cap, int)
                or not 1 <= self.completion_cap <= OUTPUT_TOKEN_CAP):
            raise ValueError("completion_cap")
        if (isinstance(self.timeout_s, bool)
                or not isinstance(self.timeout_s, (int, float))
                or not 0 < self.timeout_s <= 239):
            raise ValueError("timeout_s")
        # Non-model effects use this lease; the worker's own tool timeout cap
        # is 25s, so anything below 30s can expire a live tool dispatch.
        if (isinstance(self.worker_lease_ms, bool)
                or not isinstance(self.worker_lease_ms, int)
                or not 30000 <= self.worker_lease_ms <= 300000):
            raise ValueError("worker_lease_ms")
        try:
            items = tuple(self.budget_items)
            pairs = []
            for item in items:
                if not isinstance(item, tuple) or len(item) != 2:
                    raise ValueError
                key, value = item
                if not isinstance(key, str) or key in {k for k, _ in pairs}:
                    raise ValueError
                if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                    raise ValueError
                pairs.append((key, value))
            if (not isinstance(self.budget_items, tuple)
                    or len(pairs) != len(DEFAULT_RUN_BUDGET)
                    or {k for k, _ in pairs} != DEFAULT_RUN_BUDGET.keys()):
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError("budget_items") from None

    def run_budget(self) -> dict:
        return dict(self.budget_items)


LEGACY_UI_LIMITS = UiLimits()
# Admission-only headroom for multi-round real history (six rounds stay inside
# the 20,000-token run budget); the SQL 4,096-token reserve is unchanged.
REAL_UI_LIMITS = replace(LEGACY_UI_LIMITS, body_byte_ceiling=16384)

LIMITS = {"max_value_bytes": 40960, "max_content_bytes": 41984, "max_meta_bytes": 4096}


def limits_contract(*, completion_cap: int = OUTPUT_TOKEN_CAP,
                    body_byte_ceiling: int = BODY_BYTE_CEILING,
                    max_safe_args_bytes: int | None = MAX_SAFE_ARGS_BYTES) -> str:
    """Single-source limit text for the system prompt and the UI footer.

    A measured safe-args value renders its number; the unmeasured ``None``
    renders no number at all, because the plan forbids guessing it.
    """
    safe = (f"tool-call args <= {max_safe_args_bytes} bytes" if max_safe_args_bytes is not None
            else "tool-call args unmeasured; keep them small")
    return (f"{completion_cap} tokens/reply including reasoning; "
            f"request body <= {body_byte_ceiling} bytes; {safe}")


def build_system_prompt(skills_block: str, history: str,
                        completion_cap: int = OUTPUT_TOKEN_CAP,
                        body_byte_ceiling: int = BODY_BYTE_CEILING,
                        max_safe_args_bytes: int | None = MAX_SAFE_ARGS_BYTES) -> str:
    return (
        "stream:false; complete answer. Reply in the user's language.\n"
        "Call only this request's tools; skills add none.\n"
        "| Choice | Pi | RPCE |\n|---|---|---|\n"
        "| Read | read: verbatim, offset | read_file: start_line; -N tail, no limit |\n"
        "| Search | grep: glob/literal | file_search: mode/filter/regex |\n"
        "| Edit | edit: one batch, same original, no overlaps | apply_edits: exactly one of rewrite, search+replace, edits; on_missing only with rewrite |\n"
        + limits_contract(completion_cap=completion_cap, body_byte_ceiling=body_byte_ceiling,
                          max_safe_args_bytes=max_safe_args_bytes)
        + '; finish_reason="length" => finish_length ends the run; '
        "no truncated answers/arguments. Small write.append calls.\n"
        "For a matching skill, first read its location in full with read/read_file.\n"
        + skills_block + "\n" + history
    )


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
