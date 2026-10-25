"""Approved adapter registry for the v24 line-JSON plugin plane.

The registry is the *only* source of ``argv``, ``cwd`` and the child
environment.  A manifest, a tool argument, a model response or a descriptor can
never add an argument or change the working directory.  Matching happens on the
install row that already exists in v24:

    (identity, version, manifest_digest, artifact_digest, adapter_digest)

After that match, the entry supplies the fixed adapter id, language, argv, cwd,
tool key, descriptor and process bounds.  No new manifest top-level key, SQL
column or revision registry is introduced.

``descriptor_digest`` is part of the contract, not documentation: dispatch must
compare the approved descriptor's canonical bytes/digest with the descriptor
and digest frozen on the run pin before any process is created.

All entries are immutable frozen dataclasses built once by startup code.  The
registry itself stores tuples and private mappings and exposes no mutator.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_STDOUT_LIMIT = 64 * 1024
DEFAULT_STDERR_LIMIT = 16 * 1024
DEFAULT_TIMEOUT_MS = 5000

_HEX64_REQUIRED = "0123456789abcdef"


class _FrozenDict(dict):
    """A JSON object that cannot be mutated after registry construction."""

    def _readonly(self, *args, **kwargs):
        raise TypeError("approved adapter parameters are immutable")

    __setitem__ = _readonly
    __delitem__ = _readonly
    __ior__ = _readonly
    clear = _readonly
    pop = _readonly
    popitem = _readonly
    setdefault = _readonly
    update = _readonly


class _FrozenList(list):
    """A JSON array that cannot be mutated after registry construction."""

    def _readonly(self, *args, **kwargs):
        raise TypeError("approved adapter parameters are immutable")

    __setitem__ = _readonly
    __delitem__ = _readonly
    __iadd__ = _readonly
    __imul__ = _readonly
    append = _readonly
    clear = _readonly
    extend = _readonly
    insert = _readonly
    pop = _readonly
    remove = _readonly
    reverse = _readonly
    sort = _readonly


def _freeze(value):
    """Deep-freeze the JSON-shaped ``parameters`` field."""
    if isinstance(value, dict):
        return _FrozenDict({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return _FrozenList(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    return value


class RegistryError(RuntimeError):
    """An approved adapter entry is structurally invalid or ambiguous."""


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


def _quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def pg_jsonb_text(value) -> str:
    """Render the exact text PostgreSQL ``jsonb::text`` produces.

    ``v24.canonical_json(jsonb)`` is ``p_payload::text``.  JSON object keys are
    ordered by byte length and then bytewise, with ``", "``/``": "`` spacing.
    Descriptor digests are computed over that text, so Python must mirror it
    rather than use a compact ``json.dumps``.
    """
    if isinstance(value, dict):
        items = sorted(value.items(),
                       key=lambda kv: (len(kv[0].encode("utf-8")),
                                       kv[0].encode("utf-8")))
        return "{" + ", ".join(
            f"{_quote(key)}: {pg_jsonb_text(item)}" for key, item in items
        ) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(pg_jsonb_text(item) for item in value) + "]"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return json.dumps(value, allow_nan=False)
    if isinstance(value, str):
        return _quote(value)
    raise TypeError(f"unsupported JSON value in descriptor: {type(value)!r}")


def descriptor_digest(descriptor: dict) -> str:
    """SHA-256 hex of the PostgreSQL canonical descriptor text."""
    if not isinstance(descriptor, dict):
        raise RegistryError("descriptor must be an object")
    return hashlib.sha256(pg_jsonb_text(descriptor).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ApprovedAdapter:
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
        # Freeze the descriptor-independent identifier at construction time.
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

    # -- descriptor / artifact ------------------------------------------
    @property
    def descriptor(self) -> dict:
        """The frozen host tool descriptor for this entry."""
        return {"v": 1, "tool": {"description": self.description,
                                 "parameters": self.parameters}}

    @property
    def descriptor_bytes(self) -> bytes:
        return pg_jsonb_text(self.descriptor).encode("utf-8")

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


class ApprovedAdapterRegistry:
    """Read-only collection of approved entries indexed by install identity."""

    def __init__(self, adapters):
        entries = tuple(adapters)
        by_key: dict[tuple[str, str, str, str, str], ApprovedAdapter] = {}
        by_id: dict[str, ApprovedAdapter] = {}
        for entry in entries:
            if not isinstance(entry, ApprovedAdapter):
                raise RegistryError("registry entries must be ApprovedAdapter")
            key = entry.canonical_key()
            if key in by_key:
                raise RegistryError(
                    f"ambiguous approved adapter for install key {key}")
            if entry.adapter_id in by_id:
                raise RegistryError(f"duplicate adapter_id {entry.adapter_id!r}")
            by_key[key] = entry
            by_id[entry.adapter_id] = entry
        self._entries = entries
        self._by_key = by_key
        self._by_id = by_id

    @property
    def entries(self) -> tuple[ApprovedAdapter, ...]:
        return self._entries

    def __len__(self) -> int:
        return len(self._entries)

    def by_id(self, adapter_id: str) -> ApprovedAdapter | None:
        return self._by_id.get(adapter_id)

    def lookup_install(self, install: dict) -> ApprovedAdapter:
        """Return the approved entry for one ``host_scope_installs`` item."""
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

    def match_pin(self, install: dict, pin: dict) -> ApprovedAdapter:
        """Match an install and enforce its frozen pin descriptor.

        Both checks happen before any process is created:

        * the approved descriptor text must equal the pin's frozen descriptor;
        * the approved digest must equal the pin's frozen descriptor digest.

        The second check catches an entry whose stored digest was forged even
        when the descriptor bytes were changed independently.
        """
        entry = self.lookup_install(install)
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
