"""S0 AgentRuntime adapter for the headless SessionService.

The service owns the host ledger (``sessions.json`` v2).  This adapter owns the
PostgreSQL runtime: scope creation, installs, run start/poll and the existing
run-level control verbs.  It is deliberately not imported by the legacy UI
unless ``V24_SESSION_API`` selects the service path.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json

from v24.session.models import StartResult
from v24.ui import catalog


class AgentRuntimeBackend:
    """Map a session command onto one AgentRuntime scope.

    The adapter is owner-thread only, like ``AgentRuntime`` itself.  ``respond``
    is intentionally unsupported in S0 real mode; the durable run and its
    interaction remain inspectable, but no provider answer is fabricated.
    """

    def __init__(self, runtime, env, *, mode, toolset, limits=None):
        self.runtime = runtime
        self.env = env
        self.mode = mode
        self.toolset = toolset
        self.limits = limits or runtime.limits

    def _limits_digest(self):
        values = dataclasses.asdict(self.limits)
        values["budget_items"] = sorted(self.limits.budget_items)
        return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def _binding(self, *, scope, realm, run_id, binding=None):
        value = dict(binding or {})
        value.update({
            "scope_id": str(scope),
            "realm": realm,
            "run_id": str(run_id),
            "workspace_root": str(self.env.workspace_root),
            "toolset": self.toolset,
            "catalog_digest": catalog.catalog_digest(catalog.families(realm, self.toolset)),
            "mode": self.mode,
            "limits_digest": self._limits_digest(),
        })
        return value

    def start(self, *, session_id, message, toolset, budget, run_key,
              workspace_root, model, seed=None, binding=None):
        binding = dict(binding or {})
        scope = binding.get("scope_id")
        realm = binding.get("realm")
        if scope and scope not in self.runtime.caches:
            self.runtime.rehydrate(scope, realm, str(self.env.workspace_root), self.toolset)
        if not scope:
            realm = f"ui-{session_id}"
            scope = self.runtime.create_scope(realm)
            self.runtime.install_tools(scope, catalog.families(realm, self.toolset))
        realm = realm or f"ui-{session_id}"
        owner = self.runtime.fiber_for(scope, "v24.ui.pi_tools")
        messages = seed if isinstance(seed, list) and seed else [
            {"role": "user", "content": message}]
        emitted = self.runtime.start_run(
            scope, owner, messages, toolset=self.toolset, budget=budget,
            key=run_key)
        run_id = str(emitted[0])
        projection = self.runtime.run_state(run_id)
        run = projection.get("run") or {}
        out_binding = self._binding(scope=scope, realm=realm, run_id=run_id,
                                    binding=binding)
        return StartResult(run_id=run_id, scope_id=str(scope), realm=realm,
                           binding=out_binding, run=run)

    def poll(self, run_id, after_revision=0):
        value = self.runtime.run_state(run_id, after_revision)
        if isinstance(value, dict) and isinstance(value.get("run"), dict):
            return value
        return {"v": 1, "error": {"code": "not_found_or_denied"}}

    def cancel(self, run_id, request_key):
        value = self.runtime.cancel(run_id, request_key)
        if isinstance(value, dict) and value.get("disposition") in (
                "committed", "replay", "deferred"):
            try:
                value["run"] = self.runtime.run_state(run_id).get("run")
            except Exception:
                pass
        return value

    def steer(self, run_id, message, generation, request_key):
        value = self.runtime.steer(run_id, message, request_key)
        if isinstance(value, dict) and value.get("disposition") in (
                "committed", "replay", "deferred"):
            value.setdefault("queued", True)
            value.setdefault("superseded", False)
            try:
                value["run"] = self.runtime.run_state(run_id).get("run")
            except Exception:
                pass
        return value

    def respond(self, run_id, interaction_id, response, generation, request_key):
        # S0 real mode has no durable interaction outcome in the provider
        # adapter.  Never claim a respond that did not happen.
        if self.mode == "real":
            raise RuntimeError("waiting_unsupported")
        return self.runtime.respond(run_id, interaction_id, response, request_key)

    def recover(self, session, binding):
        """Rehydrate one durable scope and return its run projection."""
        scope = binding.get("scope_id")
        realm = binding.get("realm", "")
        if not scope:
            raise RuntimeError("setup_incomplete")
        if scope not in self.runtime.caches:
            self.runtime.rehydrate(scope, realm, str(self.env.workspace_root), self.toolset)
        run_id = session.get("active_run_id") or binding.get("run_id")
        if not run_id:
            return None
        return self.runtime.run_state(run_id).get("run") or None
