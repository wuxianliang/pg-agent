"""Shared fixtures for the v24 M-P multilingual plugin extension checks.

Two layers are built here:

* :func:`build_spec` hashes the real reference plugins, emits the existing
  manifest format (``identity/version/requires/provides/adapter_digest``) and
  builds the immutable approved registry entry whose digests the tests assert;
* :class:`PluginHarness` drives the real public lifecycle through the frozen
  DB surface: install -> host_prepare -> fiber_control(on) -> start -> model ->
  plugin subprocess -> settle -> off -> dispose -> host_release -> scope close.

The harness never reads an owner table for host work; owner reads are used only
for evidence assertions.  The model is a scripted transport, never the network.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

S11 = Path(__file__).resolve().parent
V24 = S11.parent
ROOT = V24.parent
_PLUGIN_DIR = S11 / "plugins"

for _path in (V24 / "s1", V24 / "s2", V24 / "s4", ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from test_g2b import start  # noqa: E402
from test_g3a import advance, command, one  # noqa: E402

from v24.host.db import HostDB, is_error  # noqa: E402
from v24.host.deepseek import DeepSeekAdapter, provider_tool_name  # noqa: E402
from v24.host.journal import HostJournal, canonical_json  # noqa: E402
from v24.host.plugins import PluginDispatcher  # noqa: E402
from v24.host.registry import (  # noqa: E402
    ApprovedAdapter,
    ApprovedAdapterRegistry,
    descriptor_digest,
)
from v24.host.worker import HostWorker  # noqa: E402

PROTOCOL = "v24.line-json.v1"
VERSION = "1"
DEFAULT_ENV = ("PATH", "LANG", "LC_ALL", "PYTHONIOENCODING",
               "PYTHONDONTWRITEBYTECODE")
BUDGET = {"steps": 16, "tool_calls": 16, "tokens": 8000, "wall_ms": 600000}


class ToolchainAbsent(RuntimeError):
    def __init__(self, plane: str):
        self.plane = plane
        super().__init__(f"toolchain_absent:{plane}")


@dataclass(frozen=True)
class PluginSpec:
    language: str
    identity: str
    tool_key: str
    artifact_path: Path
    manifest: bytes
    descriptor: dict
    entry: ApprovedAdapter

    @property
    def artifact_digest(self) -> str:
        return self.entry.artifact_digest

    @property
    def manifest_digest(self) -> str:
        return self.entry.manifest_digest

    @property
    def descriptor_digest(self) -> str:
        return self.entry.descriptor_digest


def artifact_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def adapter_sha256(language: str) -> str:
    declaration = {"adapter": "v24.line-json", "language": language,
                   "protocol": PROTOCOL, "version": 1}
    return hashlib.sha256(canonical_json(declaration).encode("utf-8")).hexdigest()


def descriptor_for(tool_key: str) -> dict:
    return {"v": 1, "tool": {
        "description": f"v24 reference echo plugin ({tool_key})",
        "parameters": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "additionalProperties": True,
        },
    }}


def manifest_bytes(*, identity: str, language: str, tool_key: str,
                   realm: str, descriptor: dict) -> bytes:
    document = {
        "identity": identity,
        "version": VERSION,
        "requires": [],
        "provides": [{"realm": realm, "key": tool_key, "descriptor": descriptor}],
        "adapter_digest": "\\x" + adapter_sha256(language),
    }
    return json.dumps(document, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def build_adapter(*, language: str, identity: str, tool_key: str,
                  artifact_path: str | Path, interpreter: str,
                  cwd: str | Path | None = None,
                  manifest_digest: str, artifact_digest: str,
                  descriptor: dict, adapter_digest: str | None = None,
                  timeout_ms: int = 5000) -> ApprovedAdapter:
    digest = descriptor_digest(descriptor)
    return ApprovedAdapter(
        adapter_id=f"v24.echo.{language}",
        language=language,
        identity=identity,
        version=VERSION,
        manifest_digest=manifest_digest,
        artifact_digest=artifact_digest,
        adapter_digest=adapter_digest or adapter_sha256(language),
        descriptor_digest=digest,
        argv=(str(interpreter), str(Path(artifact_path).resolve())),
        cwd=str(Path(cwd or Path(artifact_path).parent).resolve()),
        environment_allowlist=DEFAULT_ENV,
        tool_key=tool_key,
        description=descriptor["tool"]["description"],
        parameters=descriptor["tool"]["parameters"],
        timeout_ms=timeout_ms,
    )


def build_spec(language: str, *, realm: str, tool_key: str | None = None,
               identity: str | None = None,
               artifact_path: str | Path | None = None,
               interpreter: str | None = None,
               timeout_ms: int = 5000) -> PluginSpec:
    if language not in ("python", "node"):
        raise ValueError("language")
    if artifact_path is None:
        artifact_path = _PLUGIN_DIR / ("echo.py" if language == "python" else "echo.js")
    if interpreter is None:
        if language == "python":
            interpreter = sys.executable
        else:
            interpreter = shutil.which("node")
            if interpreter is None:
                raise ToolchainAbsent("node")
    tool_key = tool_key or f"echo.{language}"
    identity = identity or f"v24.echo.{language}"
    descriptor = descriptor_for(tool_key)
    manifest = manifest_bytes(identity=identity, language=language,
                              tool_key=tool_key, realm=realm,
                              descriptor=descriptor)
    entry = build_adapter(
        language=language, identity=identity, tool_key=tool_key,
        artifact_path=artifact_path, interpreter=interpreter,
        manifest_digest=hashlib.sha256(manifest).hexdigest(),
        artifact_digest=artifact_sha256(artifact_path),
        descriptor=descriptor, timeout_ms=timeout_ms)
    return PluginSpec(language=language, identity=identity, tool_key=tool_key,
                      artifact_path=Path(artifact_path), manifest=manifest,
                      descriptor=descriptor, entry=entry)


def build_registry(*specs: PluginSpec) -> ApprovedAdapterRegistry:
    return ApprovedAdapterRegistry(tuple(spec.entry for spec in specs))


# ---------------------------------------------------------------------------
# Scripted model (no socket, no provider)
# ---------------------------------------------------------------------------
class FakeClock:
    def __init__(self, value: float = 1000.0):
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, ms: int) -> None:
        self.value += ms / 1000.0


class ScriptedTransport:
    """Deterministic transport: each item is one complete provider response."""

    def __init__(self, script):
        self.script = list(script)
        self.clock = FakeClock()
        self.calls = []

    def post(self, url, body, headers, deadline):
        self.calls.append({"url": url, "body": body, "headers": headers})
        if not self.script:
            raise AssertionError("unexpected scripted model call")
        item = self.script.pop(0)
        self.clock.advance(item.get("advance_ms", 5))
        raw = item.get("raw", b"")
        if not isinstance(raw, (bytes, bytearray)):
            raw = canonical_json(raw).encode("utf-8")
        return item["status"], bytes(raw)


def model_adapter(script, *, timeout_s: float = 30.0):
    transport = ScriptedTransport(script)
    adapter = DeepSeekAdapter(
        api_key="v24-scripted-model-not-real", timeout_s=timeout_s,
        transport=transport, monotonic=transport.clock)
    return adapter, transport


def _chat_body(*, content=None, tool_calls=None, finish="stop",
               usage=(10, 5), reasoning="plan", response_id="resp"):
    message = {"role": "assistant", "content": content}
    if reasoning is not None:
        message["reasoning_content"] = reasoning
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {"id": response_id, "model": "deepseek-flash",
            "choices": [{"finish_reason": finish, "message": message}],
            "usage": {"prompt_tokens": usage[0],
                      "completion_tokens": usage[1]}}


def tool_reply(call_id: str, tool_key: str, args: dict, *, reasoning="plan",
               usage=(10, 5), response_id="resp-tool"):
    arguments = json.dumps(args, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    call = {"id": call_id, "type": "function",
            "function": {"name": provider_tool_name(tool_key),
                         "arguments": arguments}}
    return {"status": 200, "advance_ms": 7,
            "raw": _chat_body(content=None, finish="tool_calls",
                              tool_calls=[call], usage=usage,
                              reasoning=reasoning, response_id=response_id)}


def final_reply(text: str, *, reasoning="done", usage=(10, 4),
                response_id="resp-final"):
    return {"status": 200, "advance_ms": 6,
            "raw": _chat_body(content=text, finish="stop", usage=usage,
                              reasoning=reasoning, response_id=response_id)}


# ---------------------------------------------------------------------------
# Lifecycle harness
# ---------------------------------------------------------------------------
def _one_commit(conn, sql, params=()):
    value = one(conn, sql, params)
    conn.commit()
    return value


def _owner(conn):
    with conn.cursor() as cur:
        cur.execute("SET ROLE v24_owner")
    conn.commit()
    return conn


class PluginHarness:
    def __init__(self, fixture, registry: ApprovedAdapterRegistry, workdir,
                 *, realm: str | None = None):
        self.fixture = fixture
        self.registry = registry
        self.workdir = Path(workdir)
        self.owner = _owner(fixture.connect())
        self.db = HostDB(fixture.role_dsn("admin"), fixture.role_dsn("service"))
        self.dispatcher = PluginDispatcher(self.db, registry)
        self.journal = HostJournal.open(self.workdir / "plugin-journal.jsonl")
        self.worker = HostWorker(
            self.db, self.journal,
            tool_handler=self.dispatcher.tool_handler,
            resource_handler=self.dispatcher.resource_handler)
        self.realm = realm or f"g10-{uuid4().hex[:8]}"
        response = _one_commit(
            self.db.control,
            "SELECT v24.scope_control('create_root',NULL,'{}',%s,%s)",
            (self.realm, f"{self.realm}-root-{uuid4().hex[:8]}"))
        if response.get("disposition") != "committed" or not response.get("emitted"):
            raise RuntimeError(f"scope create failed: {response}")
        self.scope = response["emitted"][0]
        self.scope_key_seq = 0

    # -- lifecycle -------------------------------------------------------
    def admit(self, spec: PluginSpec, *, artifact_digest: str | None = None):
        key = f"{self.realm}-install-{uuid4().hex[:8]}"
        payload = {
            "scope_id": str(self.scope),
            "owner_fiber_id": None,
            "manifest_bytes": base64.b64encode(spec.manifest).decode("ascii"),
            "artifact_digest": "\\x" + (artifact_digest or spec.artifact_digest),
        }
        effect_id, outcome = command(self.db.control, key, "command_install",
                                     payload)
        response = advance(self.db.control, effect_id, outcome)
        self.db.control.commit()
        if response.get("disposition") != "committed":
            raise RuntimeError(f"install failed: {response}")
        return response["emitted"][0]

    def run(self, script, *, max_rounds: int = 40, timeout_s: float = 30.0):
        if script is None:
            self.worker.adapter = None
        else:
            adapter, transport = model_adapter(script, timeout_s=timeout_s)
            self.worker.adapter = adapter
            self._transport = transport
        return self.worker.run_until_idle(self.scope, max_rounds=max_rounds)

    def prepare(self, install_ids):
        installed = set()
        for _ in range(max(2, len(install_ids) + 1)):
            stats = self.run(None, max_rounds=2)
            for install_id in install_ids:
                if self.install_row(install_id)["state"] != "preparing":
                    installed.add(install_id)
            if installed == set(install_ids) or stats.progress == 0:
                break
        for install_id in install_ids:
            state = self.install_row(install_id)["state"]
            if state != "installed":
                raise RuntimeError(f"prepare did not install {install_id}: {state}")

    def fiber(self, install_id) -> dict:
        response = self.db.host_install_fibers(install_id, None, 64)
        if is_error(response) or not response.get("items"):
            raise RuntimeError(f"fiber lookup failed: {response}")
        return response["items"][0]

    def activate(self, install_id, tool_key: str):
        fiber = self.fiber(install_id)
        response = _one_commit(
            self.db.control, "SELECT v24.fiber_control(%s,'on',%s,%s)",
            (fiber["fiber_id"], fiber["control_seq"],
             f"{self.realm}-on-{uuid4().hex[:8]}"))
        if response.get("disposition") != "committed":
            raise RuntimeError(f"fiber on failed: {response}")
        return response

    def start(self, owner_fiber_id, requires, messages, *, key=None):
        value = {"messages": messages, "max_output_tokens": 256,
                 "requires": [{"key": item} for item in requires]}
        response, _ = start(self.db.control, self.scope, owner_fiber_id, value,
                            dict(BUDGET), key or f"{self.realm}-start-{uuid4().hex}")
        self.db.control.commit()
        if response.get("disposition") != "committed":
            raise RuntimeError(f"start failed: {response}")
        return response

    def off(self, install_id):
        fiber = self.fiber(install_id)
        response = _one_commit(
            self.db.control, "SELECT v24.fiber_control(%s,'off',%s,%s)",
            (fiber["fiber_id"], fiber["control_seq"],
             f"{self.realm}-off-{uuid4().hex[:8]}"))
        if response.get("disposition") not in ("committed", "deferred"):
            raise RuntimeError(f"fiber off failed: {response}")
        return response

    def dispose(self, install_id):
        response = _one_commit(
            self.db.control, "SELECT v24.dispose(%s,%s)",
            (install_id, f"{self.realm}-dispose-{uuid4().hex[:8]}"))
        return response

    def close_scope(self, *, max_calls: int = 24, script=None):
        for _ in range(max_calls):
            row = self.scope_row()
            if row["closed_at"] is not None:
                return row
            self.scope_key_seq += 1
            response = _one_commit(
                self.db.control,
                "SELECT v24.scope_control('close',%s,NULL,NULL,%s)",
                (self.scope, f"{self.realm}-close-{self.scope_key_seq}-"
                             f"{uuid4().hex[:6]}"))
            if response.get("error"):
                raise RuntimeError(f"scope close error: {response}")
            self.run(script, max_rounds=6)
            if self.scope_row()["closed_at"] is not None:
                return self.scope_row()
        return self.scope_row()

    # -- owner evidence reads -------------------------------------------
    def install_row(self, install_id) -> dict:
        return _one_commit(
            self.owner,
            "SELECT to_jsonb(i) FROM v24.installs i WHERE install_id=%s",
            (install_id,))

    def scope_row(self) -> dict:
        return _one_commit(
            self.owner,
            "SELECT to_jsonb(s) FROM v24.scopes s WHERE scope_id=%s",
            (self.scope,))

    def run_row(self, run_id) -> dict:
        return _one_commit(
            self.owner, "SELECT to_jsonb(r) FROM v24.runs r WHERE run_id=%s",
            (run_id,))

    def effect_row(self, effect_id) -> dict:
        return _one_commit(
            self.owner, "SELECT to_jsonb(e) FROM v24.effects e WHERE effect_id=%s",
            (effect_id,))

    def count(self, sql, params=()) -> int:
        return _one_commit(self.owner, f"SELECT count(*) FROM {sql}", params)

    def close(self):
        try:
            self.journal.close()
        finally:
            self.db.close()
            self.owner.close()


def execute_single(harness: PluginHarness, spec: PluginSpec, args: dict,
                   final_text: str, *, tool_call_id="call_1"):
    """Full one-plugin lifecycle: admit, prepare, activate, start, run, off."""
    install_id = harness.admit(spec)
    harness.prepare([install_id])
    harness.activate(install_id, spec.tool_key)
    fiber = harness.fiber(install_id)
    response = harness.start(
        fiber["fiber_id"], [spec.tool_key],
        [{"role": "user", "content": f"invoke {spec.language} echo"}])
    run_id, model_id = response["emitted"]
    script = [tool_reply(tool_call_id, spec.tool_key, args),
              final_reply(final_text)]
    stats = harness.run(script, max_rounds=30)
    return {"install_id": install_id, "run_id": run_id, "model_id": model_id,
            "stats": stats, "transport": harness._transport}
