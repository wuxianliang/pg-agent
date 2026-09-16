"""v8/plugin/client.py — G11 Python client for the §4 generation domain.

SQL command wrappers (build / activate / fail / retire / revoke / GC /
pointer dispose / assemble bind), the byte-level Python mirrors of the two
canonical digest constructions (asserted SQL == Python with hand-computed
golden vectors in the gate), and the process-level plugin readiness
registry with the §4 `apply(ctx, config)` shape:

  * apply is an IN-PROCESS IDEMPOTENT PURE REGISTRATION — no external IO,
    no session-state change;
  * the registration key is at least (generation_id, identity,
    plugin_version, handler_name);
  * re-registering the same key with the SAME digest is a no-op;
  * a DIFFERENT digest for the same key is a conflict;
  * the handler registry is a non-authoritative cache only — catalog
    active does NOT mean handler ready (a worker that has not loaded the
    digest MUST NOT claim).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

# ---------------------------------------------------------------------------
# canonical digest mirrors (byte-level identical to the SQL functions
# v_generation_member_digest / v_implementation_content_digest — both sides
# use compact JSON with sorted keys, ensure_ascii=False escaping)
# ---------------------------------------------------------------------------

GENERATION_DIGEST_PROFILE = "v8:generation-members@v1"
IMPLEMENTATION_DIGEST_PROFILE = "v8:implementation-content@v1"

_MEMBER_KEYS = ("contract_version", "driver", "identity",
                "implementation_digest", "locus", "plugin_version")


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def generation_member_digest(members: list[dict]) -> str:
    """Python mirror of v_generation_member_digest: SHA-256 over the compact
    canonical JSON of
      {"generation_digest_profile": "v8:generation-members@v1",
       "members": [ {contract_version, driver, identity,
                     implementation_digest, locus, plugin_version}, ... ]}
    members are the RESOLVED stable-order member records (surrogate
    implementation ids excluded)."""
    records = [{k: str(m[k]) for k in _MEMBER_KEYS} for m in members]
    text = _canonical_json({
        "generation_digest_profile": GENERATION_DIGEST_PROFILE,
        "members": records,
    })
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def implementation_content_digest(candidate: dict) -> str:
    """Python mirror of v_implementation_content_digest: SHA-256 over the
    compact canonical JSON of the scanned implementation content record
    (content, contract_version, driver, entry, identity,
    implementation_digest_profile, locus, plugin_version)."""
    text = _canonical_json({
        "content": str(candidate["content"]),
        "contract_version": str(candidate["contract_version"]),
        "driver": str(candidate["driver"]),
        "entry": str(candidate["entry"]),
        "identity": str(candidate["identity"]),
        "implementation_digest_profile": IMPLEMENTATION_DIGEST_PROFILE,
        "locus": str(candidate["locus"]),
        "plugin_version": str(candidate["plugin_version"]),
    })
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def candidate(identity: str, *, contract_version: str = "cv@1",
              plugin_version: str = "1.0.0", driver: str = "native",
              locus: str = "sql", entry: str | None = None,
              content: str | None = None, priority: int = 0,
              requires: list[dict] | None = None,
              provides: list[dict] | None = None,
              spec: dict | None = None,
              declared_digest: str | None = None) -> dict:
    """Build a manifest candidate with the digest recomputed from the
    scanned content (declared_digest lets tests forge a mismatch)."""
    base = {
        "identity": identity,
        "contract_version": contract_version,
        "plugin_version": plugin_version,
        "driver": driver,
        "locus": locus,
        "entry": entry or f"{locus}:{identity}@{plugin_version}",
        "content": content if content is not None else
            f"define_plugin({identity!r}, {contract_version!r}, "
            f"{plugin_version!r})",
        "priority": priority,
        "requires": requires or [],
        "provides": provides or [],
        "spec": spec or {},
    }
    base["implementation_digest"] = (
        declared_digest if declared_digest is not None
        else implementation_content_digest(base))
    return base


def manifest(candidates: list[dict]) -> dict:
    return {"candidates": candidates}


# ---------------------------------------------------------------------------
# readiness registry (process-level; §4 apply(ctx, config) contract)
# ---------------------------------------------------------------------------

class ReadinessConflict(RuntimeError):
    """The same registration key re-registered with a different digest."""


class _ToolsRegister:
    def __init__(self, ctx: "NativeCtx"):
        self._ctx = ctx

    def register(self, tool_def: dict) -> None:
        if not isinstance(tool_def, dict) or "name" not in tool_def:
            raise ValueError(
                "define_tool(...) payload must be a dict with a name")
        self._ctx._registered_tools.append(tool_def)


class NativeCtx:
    """The §4 Native ctx surface: only tools.register(define_tool(...)),
    systemPrompt.section, on(event, handler) voting registration and
    get(key). Pure registration — no external IO, no session state."""

    def __init__(self):
        self.tools = _ToolsRegister(self)
        self._registered_tools: list[dict] = []
        self.prompt_sections: list[dict] = []
        self.hooks: dict[str, Callable[..., Any]] = {}
        self.config: dict[str, Any] = {}

    def systemPrompt_section(self, section_id: str, text: str) -> None:
        self.prompt_sections.append({"id": section_id, "text": text})

    def on(self, event: str, handler: Callable[..., Any]) -> None:
        self.hooks[event] = handler

    def get(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)


def default_apply(ctx: NativeCtx, config: dict) -> None:
    """The default plugin apply body used by the publish preload: a pure
    registration of one no-op handler + one prompt section (real plugins
    carry their own apply; the shape is the contract under test)."""
    ctx.tools.register({
        "name": config.get("handler_name", "default"),
        "handler_name": config.get("handler_name", "default"),
    })
    ctx.systemPrompt_section(config.get("identity", ""),
                             f"plugin:{config.get('identity', '')}")


class PluginHandlerRegistry:
    """In-process handler registry keyed by (generation_id, identity,
    plugin_version, handler_name) -> {digest, handler, ctx}. A
    NON-AUTHORITATIVE cache: catalog active != handler ready."""

    def __init__(self):
        self._entries: dict[tuple[str, str, str, str], dict] = {}

    @staticmethod
    def key(generation_id, identity: str, plugin_version: str,
            handler_name: str = "default") -> tuple[str, str, str, str]:
        return (str(generation_id), str(identity), str(plugin_version),
                handler_name)

    def apply(self, generation_id, members: list[dict],
              apply_fn: Callable[[NativeCtx, dict], None] | None = None,
              handler_name: str = "default") -> list[tuple[str, str, str, str]]:
        """The §4 `apply(ctx, config)` readiness registration over a
        generation's member set: idempotent pure registration per member —
        the same key + same digest is a no-op, a different digest is a
        conflict. No external IO, no session-state change."""
        applied: list[tuple[str, str, str, str]] = []
        for m in members:
            k = self.key(generation_id, m["identity"], m["plugin_version"],
                         handler_name)
            digest = str(m["implementation_digest"])
            existing = self._entries.get(k)
            if existing is not None:
                if existing["digest"] != digest:
                    raise ReadinessConflict(
                        f"handler registry key {k} re-registered with a "
                        f"different digest (had {existing['digest']}, got "
                        f"{digest})")
                continue                     # same digest: no-op
            ctx = NativeCtx()
            config = {"identity": m["identity"],
                      "handler_name": handler_name}
            (apply_fn or default_apply)(ctx, config)
            self._entries[k] = {"digest": digest, "ctx": ctx,
                                "handler": ctx.hooks.get("plugin") or
                                ctx._registered_tools[0]
                                if ctx._registered_tools else None}
            applied.append(k)
        return applied

    def has(self, generation_id, identity: str, plugin_version: str,
            handler_name: str = "default") -> bool:
        return self.key(generation_id, identity, plugin_version,
                        handler_name) in self._entries

    def ready_to_claim(self, generation_id, members: list[dict],
                       handler_name: str = "default") -> bool:
        """Every member's digest loaded in THIS process — a worker that has
        not loaded the corresponding digest MUST NOT claim (catalog active
        does not mean handler ready)."""
        return all(self.has(generation_id, m["identity"],
                            m["plugin_version"], handler_name)
                   for m in members)

    def handler(self, generation_id, identity: str, plugin_version: str,
                handler_name: str = "default"):
        entry = self._entries.get(self.key(generation_id, identity,
                                           plugin_version, handler_name))
        return None if entry is None else entry["handler"]


# ---------------------------------------------------------------------------
# SQL wrappers (same frozen convention as the other stage clients: the
# caller's connection, one transaction per call)
# ---------------------------------------------------------------------------

def build_generation(conn, m: dict) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT v_build_generation(%s::jsonb)",
                    (json.dumps(m, ensure_ascii=False),))
        out = cur.fetchone()[0]
    conn.commit()
    return out


def activate_generation(conn, generation_id, operator: str = "operator") -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT v_activate_generation(%s::uuid, %s)",
                    (str(generation_id), operator))
        out = cur.fetchone()[0]
    conn.commit()
    return out


def fail_generation_building(conn, generation_id, code: str, detail: str) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT v_fail_generation_building(%s::uuid, %s, %s)",
            (str(generation_id), code, detail))
        out = cur.fetchone()[0]
    conn.commit()
    return out


def retire_generation(conn, generation_id, operator: str = "operator") -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT v_retire_generation(%s::uuid, %s)",
                    (str(generation_id), operator))
        out = cur.fetchone()[0]
    conn.commit()
    return out


def revoke_generation(conn, generation_id, reason: str,
                      operator: str = "operator",
                      pointer_action: str | None = None,
                      pointer_target=None, revoke_id: str | None = None) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT v_revoke_generation(%s::uuid, %s, %s, %s, %s::uuid, %s)",
            (str(generation_id), reason, operator, pointer_action,
             None if pointer_target is None else str(pointer_target),
             revoke_id))
        out = cur.fetchone()[0]
    conn.commit()
    return out


def gc_generation(conn, generation_id) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT v_gc_generation(%s::uuid)", (str(generation_id),))
        out = cur.fetchone()[0]
    conn.commit()
    return out


def dispose_pointer(conn, action: str, target=None,
                    operator: str = "operator") -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT v_catalog_pointer_dispose(%s, %s::uuid, %s)",
            (action, None if target is None else str(target), operator))
        out = cur.fetchone()[0]
    conn.commit()
    return out


def assemble_bind_generation(conn, session_id) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT v_assemble_bind_generation(%s::uuid)",
                    (str(session_id),))
        out = cur.fetchone()[0]
    conn.commit()
    return out


def step_generation_status(conn, step_id) -> str | None:
    with conn.cursor() as cur:
        cur.execute("SELECT v_step_generation_status(%s::uuid)",
                    (str(step_id),))
        out = cur.fetchone()[0]
    conn.rollback()
    return out


def active_pointer(conn) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT active_generation_id::text FROM catalog_config WHERE id=1")
        row = cur.fetchone()
    conn.rollback()
    return None if row is None else row[0]


# ---------------------------------------------------------------------------
# publish_generation — the §4 publish flow: build (DB) -> worker preload
# and readiness report (in-process apply) -> atomic activate. ANY failure
# of the four build phases terminates the candidate building -> failed
# and leaves the active pointer and every bound step/job untouched.
# ---------------------------------------------------------------------------

def publish_generation(conn, m: dict, *, operator: str = "operator",
                       registry: PluginHandlerRegistry | None = None,
                       apply_fn: Callable[[NativeCtx, dict], None] | None = None,
                       skip_preload: bool = False) -> dict:
    built = build_generation(conn, m)
    if built["outcome"] != "built":
        return built                      # building -> failed (build phase)
    if skip_preload:
        return built                      # stays building (test hook)
    reg = registry if registry is not None else PluginHandlerRegistry()
    try:
        reg.apply(built["generation_id"], built["members"],
                  apply_fn=apply_fn)
    except Exception as exc:              # preload/readiness failure
        return fail_generation_building(
            conn, built["generation_id"], "READINESS_FAILED", str(exc))
    return activate_generation(conn, built["generation_id"], operator=operator)
