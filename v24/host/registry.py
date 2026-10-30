"""Approved adapter and plugin registry for the v24 line-JSON plane."""
from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_STDOUT_LIMIT = 64 * 1024
DEFAULT_STDERR_LIMIT = 16 * 1024
DEFAULT_TIMEOUT_MS = 5000
_HEX64_REQUIRED = "0123456789abcdef"

from .canonical import (  # noqa: F401
    RegistryError,
    _FrozenDict,
    _FrozenList,
    _freeze,
    _quote,
    descriptor_digest,
    pg_jsonb_text,
    compact_json,
    strict_loads,
)
from .descriptor import DescriptorError, validate_descriptor
from .renderers import RENDERERS, RendererRef
from .tool_schema import SchemaError, compile_schema


class AdapterNotFound(RegistryError):
    """No approved entry matches this install (or its frozen descriptor)."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _hex64(value, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise RegistryError(f"{name} must be 64 lowercase hex characters")
    if any(ch not in _HEX64_REQUIRED for ch in value):
        raise RegistryError(f"{name} must be 64 lowercase hex characters")
    return value


class _ApprovedEntry:
    @property
    def artifact_path(self) -> str:
        """The one script the registry is allowed to execute."""
        return self.argv[1]

    def canonical_key(self) -> tuple[str, str, str, str, str]:
        return (self.identity, self.version, self.manifest_digest,
                self.artifact_digest, self.adapter_digest)

    def require_artifact(self) -> None:
        """Reject a non-regular, out-of-tree or byte-mismatched artifact.

        This runs immediately before spawn.  A failure here is a pre-spawn
        failure: no process may have been created.
        """
        artifact = Path(self.artifact_path)
        cwd = Path(self.cwd)
        try:
            real_artifact = artifact.resolve(strict=True)
            real_cwd = cwd.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise AdapterNotFound("artifact_missing") from exc
        try:
            if os.path.commonpath((str(real_artifact), str(real_cwd))) != str(real_cwd):
                raise AdapterNotFound("artifact_outside_cwd")
        except ValueError as exc:
            raise AdapterNotFound("artifact_outside_cwd") from exc
        try:
            mode = real_artifact.stat().st_mode
        except OSError as exc:
            raise AdapterNotFound("artifact_unreadable") from exc
        if not stat.S_ISREG(mode):
            raise AdapterNotFound("artifact_not_regular")
        digest = hashlib.sha256(real_artifact.read_bytes()).hexdigest()
        if digest != self.artifact_digest:
            raise AdapterNotFound("artifact_digest_mismatch")

    def environment(self, source=None) -> dict[str, str]:
        """Select only allowlisted variables from the host environment."""
        source = os.environ if source is None else source
        return {key: source[key] for key in self.environment_allowlist
                if key in source}


@dataclass(frozen=True)
class ApprovedAdapter(_ApprovedEntry):
    """One immutable host-approved process adapter entry."""

    adapter_id: str
    language: str
    identity: str
    version: str
    manifest_digest: str
    artifact_digest: str
    adapter_digest: str
    descriptor_digest: str
    argv: tuple[str, ...]
    cwd: str
    environment_allowlist: tuple[str, ...]
    tool_key: str
    description: str
    parameters: dict = field(hash=False)
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    stdout_limit: int = DEFAULT_STDOUT_LIMIT
    stderr_limit: int = DEFAULT_STDERR_LIMIT

    def __post_init__(self) -> None:
        for name in ("adapter_id", "language", "identity", "version",
                     "tool_key", "cwd", "description"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise RegistryError(f"{name} must be a non-empty string")
        for name in ("manifest_digest", "artifact_digest", "adapter_digest",
                     "descriptor_digest"):
            object.__setattr__(self, name, _hex64(getattr(self, name), name))
        if not isinstance(self.argv, tuple) or not self.argv:
            raise RegistryError("argv must be a non-empty tuple")
        for item in self.argv:
            if not isinstance(item, str) or not item or "\x00" in item:
                raise RegistryError("argv entries must be non-empty NUL-free strings")
        if not os.path.isabs(self.argv[0]):
            raise RegistryError("argv[0] must be an absolute executable path")
        if len(self.argv) < 2 or not os.path.isabs(self.argv[1]):
            raise RegistryError("argv[1] must be the absolute artifact path")
        if not os.path.isabs(self.cwd) or not os.path.isdir(self.cwd):
            raise RegistryError("cwd must be an existing absolute directory")
        if not isinstance(self.environment_allowlist, tuple) or any(
                not isinstance(key, str) or not key
                for key in self.environment_allowlist):
            raise RegistryError("environment_allowlist must be a tuple of names")
        if not isinstance(self.parameters, dict):
            raise RegistryError("parameters must be an object")
        object.__setattr__(self, "parameters", _freeze(self.parameters))
        computed = descriptor_digest(self.descriptor)
        if computed != self.descriptor_digest:
            raise RegistryError(
                "descriptor_digest does not match the approved descriptor")
        if (not isinstance(self.timeout_ms, int) or isinstance(self.timeout_ms, bool)
                or not 0 < self.timeout_ms <= 300000):
            raise RegistryError("timeout_ms must be in (0, 300000]")
        for name, value in (("stdout_limit", self.stdout_limit),
                            ("stderr_limit", self.stderr_limit)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise RegistryError(f"{name} must be a positive integer")

    @property
    def descriptor(self) -> dict:
        """The frozen host tool descriptor for this entry."""
        return {"v": 1, "tool": {"description": self.description,
                                 "parameters": self.parameters}}

    @property
    def descriptor_bytes(self) -> bytes:
        return pg_jsonb_text(self.descriptor).encode("utf-8")


@dataclass(frozen=True)
class ApprovedTool:
    key: str
    descriptor: dict = field(hash=False)
    descriptor_digest: str
    timeout_ms: int
    render: RendererRef | None
    output_schema: dict | None = field(hash=False)
    parameters_check: object | None = field(init=False, default=None, compare=False,
                                             hash=False, repr=False)
    output_check: object | None = field(init=False, default=None, compare=False,
                                         hash=False, repr=False)

    def __post_init__(self) -> None:
        if (not isinstance(self.key, str) or not self.key
                or not isinstance(self.descriptor, dict)
                or not isinstance(self.timeout_ms, int)
                or isinstance(self.timeout_ms, bool)
                or not 0 < self.timeout_ms <= 300000
                or (self.render is not None and not isinstance(self.render, RendererRef))
                or (self.output_schema is not None and not isinstance(self.output_schema, dict))):
            raise RegistryError("approved_tool_invalid")
        _hex64(self.descriptor_digest, "descriptor_digest")
        version = self.descriptor.get("v")
        if type(version) is not int:
            raise RegistryError("invalid_descriptor")
        if version == 1:
            if self.render is not None or self.output_schema is not None:
                raise RegistryError("approved_tool_invalid")
            object.__setattr__(self, "descriptor", _freeze(self.descriptor))
        elif version == 2:
            try:
                frozen = validate_descriptor(self.descriptor, provide_key=self.key)
            except DescriptorError as exc:
                raise RegistryError(exc.reason) from None
            tool = frozen["tool"]
            try:
                expected_render = RendererRef(**tool["render"])
                consistent = (self.timeout_ms == tool["limits"]["timeout_ms"]
                              and self.render == expected_render
                              and self.output_schema == tool["output_schema"])
            except (TypeError, KeyError, AttributeError):
                consistent = False
            if not consistent:
                raise RegistryError("approved_tool_invalid")
            try:
                parameters_check = compile_schema(tool["parameters"], kind="parameters")
                output_check = compile_schema(tool["output_schema"], kind="output_schema")
            except SchemaError:
                raise RegistryError("invalid_descriptor") from None
            object.__setattr__(self, "descriptor", frozen)
            object.__setattr__(self, "output_schema", tool["output_schema"])
            object.__setattr__(self, "parameters_check", parameters_check)
            object.__setattr__(self, "output_check", output_check)
        else:
            raise RegistryError("invalid_descriptor")
        if descriptor_digest(self.descriptor) != self.descriptor_digest:
            raise RegistryError("descriptor_digest does not match the approved descriptor")

    @classmethod
    def from_descriptor(cls, descriptor, *, key: str) -> "ApprovedTool":
        try:
            frozen = validate_descriptor(descriptor, provide_key=key)
            tool = frozen["tool"]
            return cls(key=key, descriptor=frozen,
                       descriptor_digest=descriptor_digest(frozen),
                       timeout_ms=tool["limits"]["timeout_ms"],
                       render=RendererRef(**tool["render"]),
                       output_schema=tool["output_schema"])
        except DescriptorError as exc:
            raise RegistryError(exc.reason) from None
        except RegistryError:
            raise
        except (TypeError, ValueError, UnicodeError, RecursionError, KeyError, AttributeError):
            raise RegistryError("invalid_descriptor") from None


@dataclass(frozen=True)
class ApprovedPlugin(_ApprovedEntry):
    adapter_id: str
    language: str
    identity: str
    version: str
    manifest_digest: str
    artifact_digest: str
    adapter_digest: str
    argv: tuple[str, ...]
    cwd: str
    environment_allowlist: tuple[str, ...]
    tools: tuple[ApprovedTool, ...]
    workspace_root: str
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    timeout_cap_ms: int = 25000
    stdout_limit: int = DEFAULT_STDOUT_LIMIT
    stderr_limit: int = DEFAULT_STDERR_LIMIT
    protocol: int = 2

    def __post_init__(self) -> None:
        for name in ("adapter_id", "language", "identity", "version", "cwd"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise RegistryError(f"{name} must be a non-empty string")
        for name in ("manifest_digest", "artifact_digest", "adapter_digest"):
            object.__setattr__(self, name, _hex64(getattr(self, name), name))
        if not isinstance(self.argv, tuple) or not self.argv:
            raise RegistryError("argv must be a non-empty tuple")
        for item in self.argv:
            if not isinstance(item, str) or not item or "\x00" in item:
                raise RegistryError("argv entries must be non-empty NUL-free strings")
        if not os.path.isabs(self.argv[0]):
            raise RegistryError("argv[0] must be an absolute executable path")
        if len(self.argv) < 2 or not os.path.isabs(self.argv[1]):
            raise RegistryError("argv[1] must be the absolute artifact path")
        if not os.path.isabs(self.cwd) or not os.path.isdir(self.cwd):
            raise RegistryError("cwd must be an existing absolute directory")
        if not isinstance(self.environment_allowlist, tuple) or any(
                not isinstance(key, str) or not key for key in self.environment_allowlist):
            raise RegistryError("environment_allowlist must be a tuple of names")
        if not isinstance(self.timeout_ms, int) or isinstance(self.timeout_ms, bool) or not 0 < self.timeout_ms <= 300000:
            raise RegistryError("timeout_ms must be in (0, 300000]")
        for name, value in (("stdout_limit", self.stdout_limit), ("stderr_limit", self.stderr_limit)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise RegistryError(f"{name} must be a positive integer")
        if type(self.protocol) is not int or self.protocol != 2:
            raise RegistryError("protocol_invalid")
        if (not isinstance(self.tools, tuple) or not 1 <= len(self.tools) <= 16
                or any(not isinstance(tool, ApprovedTool) for tool in self.tools)):
            raise RegistryError("tools_invalid")
        keys = [tool.key for tool in self.tools]
        if len(set(keys)) != len(keys):
            raise RegistryError("duplicate_tool_key")
        if any(tool.descriptor.get("v") != 2 for tool in self.tools):
            raise RegistryError("invalid_descriptor")
        root = self.workspace_root
        if (not isinstance(root, str) or not os.path.isabs(root)
                or os.path.realpath(root) != root or not os.path.isdir(root)):
            raise RegistryError("workspace_root_invalid")
        if (not isinstance(self.timeout_cap_ms, int) or isinstance(self.timeout_cap_ms, bool)
                or not 1 <= self.timeout_cap_ms <= 25000):
            raise RegistryError("timeout_cap_invalid")
        if any(tool.timeout_ms > self.timeout_cap_ms for tool in self.tools):
            raise RegistryError("timeout_exceeds_cap")

    def tool_for(self, key: str) -> ApprovedTool | None:
        if not isinstance(key, str):
            return None
        return next((tool for tool in self.tools if tool.key == key), None)

    @classmethod
    def from_manifest(cls, manifest, *, language, artifact_digest, adapter_id,
                      argv, cwd, environment_allowlist, workspace_root,
                      timeout_ms=5000, timeout_cap_ms=25000,
                      stdout_limit=65536, stderr_limit=16384) -> "ApprovedPlugin":
        try:
            if isinstance(manifest, dict):
                raw = compact_json(manifest)
                parsed = manifest
            elif isinstance(manifest, bytes):
                raw = manifest
                parsed = strict_loads(raw)
            elif isinstance(manifest, str):
                raw = manifest.encode("utf-8")
                parsed = strict_loads(raw)
            else:
                raise ValueError
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise RegistryError("manifest_invalid") from None
        if not isinstance(parsed, dict) or set(parsed) != {"identity", "version", "requires", "provides", "adapter_digest"}:
            raise RegistryError("manifest_invalid")
        if (not isinstance(parsed["identity"], str) or not parsed["identity"]
                or not isinstance(parsed["version"], str) or not parsed["version"]
                or not isinstance(parsed["requires"], list)
                or not isinstance(parsed["provides"], list)
                or not 1 <= len(parsed["provides"]) <= 16):
            raise RegistryError("manifest_invalid")
        provides = parsed["provides"]
        for provide in provides:
            if (not isinstance(provide, dict) or set(provide) != {"realm", "key", "descriptor"}
                    or not isinstance(provide["realm"], str) or not provide["realm"]
                    or not isinstance(provide["key"], str) or not provide["key"]
                    or not isinstance(provide["descriptor"], dict)):
                raise RegistryError("manifest_invalid")
        versions = set()
        for provide in provides:
            version = provide["descriptor"].get("v")
            try:
                versions.add((type(version), version))
            except TypeError:
                versions.add((type(version), repr(version)))
        if len(versions) > 1:
            raise RegistryError("mixed_descriptor_versions")
        if any(type(p["descriptor"].get("v")) is not int or p["descriptor"].get("v") != 2 for p in provides):
            raise RegistryError("manifest_invalid")
        declared = parsed["adapter_digest"]
        if not isinstance(declared, str) or len(declared) != 64 or any(c not in _HEX64_REQUIRED for c in declared):
            raise RegistryError("manifest_invalid")
        if declared != adapter_declaration_digest(language):
            raise RegistryError("adapter_digest_mismatch")
        tools = tuple(ApprovedTool.from_descriptor(p["descriptor"], key=p["key"]) for p in provides)
        manifest_hash = hashlib.sha256(raw).hexdigest()
        return cls(adapter_id=adapter_id, language=language,
                   identity=parsed["identity"], version=parsed["version"],
                   manifest_digest=manifest_hash, artifact_digest=artifact_digest,
                   adapter_digest=declared, argv=argv, cwd=cwd,
                   environment_allowlist=environment_allowlist, tools=tools,
                   workspace_root=workspace_root, timeout_ms=timeout_ms,
                   timeout_cap_ms=timeout_cap_ms, stdout_limit=stdout_limit,
                   stderr_limit=stderr_limit)


def adapter_declaration_digest(language: str) -> str:
    return hashlib.sha256(compact_json({
        "adapter": "v24.line-json", "language": language,
        "protocol": "v24.line-json.v2", "version": 2,
    })).hexdigest()


@dataclass(frozen=True)
class ToolBinding:
    entry: ApprovedAdapter | ApprovedPlugin
    tool: ApprovedTool


class ApprovedAdapterRegistry:
    """Read-only collection of approved entries indexed by install identity."""

    def __init__(self, adapters):
        entries = tuple(adapters)
        by_key = {}
        by_id = {}
        for entry in entries:
            if not isinstance(entry, (ApprovedAdapter, ApprovedPlugin)):
                raise RegistryError("registry entries must be ApprovedAdapter or ApprovedPlugin")
            key = entry.canonical_key()
            if key in by_key:
                raise RegistryError(f"ambiguous approved adapter for install key {key}")
            if entry.adapter_id in by_id:
                raise RegistryError(f"duplicate adapter_id {entry.adapter_id!r}")
            by_key[key] = entry
            by_id[entry.adapter_id] = entry
        self._entries = entries
        self._by_key = by_key
        self._by_id = by_id

    @property
    def entries(self) -> tuple[ApprovedAdapter | ApprovedPlugin, ...]:
        return self._entries

    def __len__(self) -> int:
        return len(self._entries)

    def by_id(self, adapter_id: str) -> ApprovedAdapter | ApprovedPlugin | None:
        return self._by_id.get(adapter_id)

    def lookup_install(self, install: dict) -> ApprovedAdapter | ApprovedPlugin:
        if not isinstance(install, dict):
            raise AdapterNotFound("install_invalid")
        try:
            key = (install["identity"], install["version"],
                   str(install["manifest_digest"]).lower(),
                   str(install["artifact_digest"]).lower(),
                   str(install["adapter_digest"]).lower())
        except KeyError as exc:
            raise AdapterNotFound("install_invalid") from exc
        entry = self._by_key.get(key)
        if entry is None:
            raise AdapterNotFound("adapter_not_approved")
        return entry

    def match_tool(self, install: dict, pin: dict, key: str) -> ToolBinding:
        entry = self.lookup_install(install)
        if not isinstance(pin, dict) or not isinstance(key, str) or pin.get("key") != key:
            raise AdapterNotFound("pin_key_mismatch")
        if isinstance(entry, ApprovedAdapter):
            if entry.tool_key != key:
                raise AdapterNotFound("tool_not_approved")
            tool = ApprovedTool(key=entry.tool_key, descriptor=entry.descriptor,
                                descriptor_digest=entry.descriptor_digest,
                                timeout_ms=entry.timeout_ms, render=None,
                                output_schema=None)
        else:
            tool = entry.tool_for(key)
            if tool is None:
                raise AdapterNotFound("tool_not_approved")
        descriptor = pin.get("descriptor")
        if not isinstance(descriptor, dict):
            raise AdapterNotFound("descriptor_missing")
        pin_digest = pin.get("descriptor_digest")
        if not isinstance(pin_digest, str):
            raise AdapterNotFound("descriptor_digest_missing")
        if pg_jsonb_text(tool.descriptor) != pg_jsonb_text(descriptor):
            raise AdapterNotFound("descriptor_mismatch")
        if tool.descriptor_digest != pin_digest.lower():
            raise AdapterNotFound("descriptor_digest_mismatch")
        return ToolBinding(entry, tool)

    def match_pin(self, install: dict, pin: dict) -> ApprovedAdapter:
        entry = self.lookup_install(install)
        if isinstance(entry, ApprovedPlugin):
            raise AdapterNotFound("protocol_mismatch")
        descriptor = pin.get("descriptor") if isinstance(pin, dict) else None
        pin_digest = pin.get("descriptor_digest") if isinstance(pin, dict) else None
        if not isinstance(descriptor, dict):
            raise AdapterNotFound("descriptor_missing")
        if not isinstance(pin_digest, str):
            raise AdapterNotFound("descriptor_digest_missing")
        if pg_jsonb_text(entry.descriptor) != pg_jsonb_text(descriptor):
            raise AdapterNotFound("descriptor_mismatch")
        if entry.descriptor_digest != pin_digest.lower():
            raise AdapterNotFound("descriptor_digest_mismatch")
        return entry
