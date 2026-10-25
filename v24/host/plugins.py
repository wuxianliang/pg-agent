"""Plugin dispatch: approved registry -> line-JSON process -> v24 receipt.

The worker owns claim/settle.  This module only turns one already-claimed
``tool_call`` / ``host_prepare`` / ``host_release`` / ``inspect_resource``
effect into the exact ``(class, result)`` pair the worker settles.

Before a process is created every path re-reads the public host surface:

* the install row via ``host_scope_installs`` (never an owner table);
* the run pin via ``host_run_pins`` (for tool calls);
* the approved entry via the five-field install match;
* the frozen pin descriptor/digest via ``match_pin``;
* the artifact path (regular file, inside cwd, exact SHA-256).

``argv``/``cwd``/environment come only from the approved entry.  There is no
shell, no manifest argument, no tool-argument interpolation and no model text
in the command line.
"""
from __future__ import annotations

from . import line_json
from .db import HostContractError, is_error
from .line_json import LineJsonPreflight
from .registry import AdapterNotFound, ApprovedAdapterRegistry


class PluginError(RuntimeError):
    """A dispatcher precondition failed before a process was created."""


class PluginDispatcher:
    def __init__(self, db, registry: ApprovedAdapterRegistry):
        if not isinstance(registry, ApprovedAdapterRegistry):
            raise TypeError("registry must be an ApprovedAdapterRegistry")
        self.db = db
        self.registry = registry
        self.last_invocation = None

    # -- worker handlers -------------------------------------------------
    def tool_handler(self, effect: dict):
        try:
            return self._tool(effect)
        except (AdapterNotFound, PluginError, HostContractError,
                LineJsonPreflight) as exc:
            return "failure", _tool_error(getattr(exc, "reason", str(exc)))

    def resource_handler(self, effect: dict):
        kind = effect.get("kind")
        if kind == "inspect_resource":
            return self._inspect(effect)
        if kind in ("host_prepare", "host_release"):
            return self._resource(effect, kind)
        return "failure", {"v": 1, "observed": "unknown",
                           "reason": "unsupported_host_effect"}

    # -- tool call -------------------------------------------------------
    def _tool(self, effect: dict):
        request = _object(effect.get("request"), "request_invalid")
        key = request.get("key")
        args = request.get("args")
        if not isinstance(key, str) or not isinstance(args, dict):
            raise PluginError("tool_request_invalid")
        pin = self._pin(effect)
        install = self._install(effect.get("scope_id"), pin.get("provider_install_id"))
        entry = self.registry.match_pin(install, pin)
        if entry.tool_key != key:
            raise PluginError("tool_key_mismatch")
        entry.require_artifact()
        reservation = f"v24:tool_call:{effect['effect_id']}"
        invocation = line_json.run(entry, "invoke", reservation, args)
        self.last_invocation = invocation
        if invocation.class_name == "success":
            return "success", {
                "status": "ok",
                "output": invocation.result,
                "usage": {"wall_ms": invocation.wall_ms},
            }
        if invocation.class_name == "failure":
            return "failure", {
                "status": "error",
                "output": {"code": invocation.result["code"],
                           "message": invocation.result["message"]},
            }
        return "unknown", _tool_unknown(invocation.reason, invocation.wall_ms)

    # -- host resources --------------------------------------------------
    def _resource(self, effect: dict, kind: str):
        request = _object(effect.get("request"), "request_invalid")
        install_id = request.get("install_id")
        install = self._install(effect.get("scope_id"), install_id)
        reservation = request.get("reservation")
        expected_prefix = f"v24:{kind}:"
        if not isinstance(reservation, str) or not reservation.startswith(
                expected_prefix):
            raise PluginError("reservation_invalid")
        try:
            entry = self.registry.lookup_install(install)
            entry.require_artifact()
        except AdapterNotFound as exc:
            return "failure", _resource_failure(kind, exc.reason)
        try:
            invocation = line_json.run(
                entry, "prepare" if kind == "host_prepare" else "release",
                reservation, {"install_id": str(install_id)})
        except LineJsonPreflight as exc:
            return "failure", _resource_failure(kind, exc.reason)
        self.last_invocation = invocation
        if invocation.class_name == "success":
            result = {"v": 1, "adapter_id": entry.adapter_id,
                      "language": entry.language, "reservation": reservation}
            if kind == "host_prepare":
                result["prepared"] = True
            else:
                result["released"] = True
            return "success", result
        if invocation.class_name == "failure":
            return "failure", _resource_failure(kind, invocation.result["code"])
        return "unknown", {"v": 1, "reason": invocation.reason}

    # -- inspect ---------------------------------------------------------
    def _inspect(self, effect: dict):
        request = _object(effect.get("request"), "request_invalid")
        install_id = request.get("install_id")
        install = self._install(effect.get("scope_id"), install_id)
        target = request.get("target")
        target_reservation = request.get("target_reservation")
        if target not in ("host_prepare", "host_release") or not isinstance(
                target_reservation, str):
            raise PluginError("inspect_request_invalid")
        try:
            entry = self.registry.lookup_install(install)
            entry.require_artifact()
        except AdapterNotFound:
            return "failure", {"v": 1, "observed": "unknown",
                               "reason": "inspect_failed"}
        try:
            invocation = line_json.run(
                entry, "inspect", target_reservation,
                {"install_id": str(install_id), "target": target})
        except LineJsonPreflight:
            return "failure", {"v": 1, "observed": "unknown",
                               "reason": "inspect_failed"}
        self.last_invocation = invocation
        if invocation.class_name == "success":
            observed = invocation.result.get("observed")
            if observed not in ("known", "absent"):
                return "unknown", {"v": 1, "observed": "unknown"}
            return "success", {
                "v": 1,
                "observed": observed,
                "target_effect_id": request.get("target_effect_id"),
                "target_reservation": target_reservation,
            }
        if invocation.class_name == "failure":
            return "failure", {"v": 1, "observed": "unknown",
                               "reason": "inspect_failed"}
        return "unknown", {"v": 1, "observed": "unknown"}

    # -- public reads ----------------------------------------------------
    def _install(self, scope_id, install_id) -> dict:
        if not isinstance(install_id, str):
            raise PluginError("install_id_invalid")
        cursor = None
        while True:
            if cursor is None:
                response = self.db.host_scope_installs(scope_id, None, 64)
            else:
                response = self.db.host_scope_installs(
                    scope_id, cursor["install_id"], 64)
            if is_error(response):
                raise PluginError("install_read_failed")
            for item in response.get("items", []):
                if str(item.get("install_id")) == install_id:
                    return item
            if not response.get("has_more"):
                raise PluginError("install_not_found")
            cursor = response.get("next_cursor")
            if not isinstance(cursor, dict):
                raise PluginError("install_cursor_invalid")

    def _pin(self, effect) -> dict:
        pin_id = effect.get("pin_id")
        run_id = effect.get("run_id")
        if not isinstance(pin_id, str) or not isinstance(run_id, str):
            raise PluginError("pin_missing")
        cursor = None
        while True:
            if cursor is None:
                response = self.db.host_run_pins(run_id, None, 64)
            else:
                response = self.db.host_run_pins(run_id, cursor["pin_id"], 64)
            if is_error(response):
                raise PluginError("pin_read_failed")
            for item in response.get("items", []):
                if str(item.get("pin_id")) == pin_id:
                    return item
            if not response.get("has_more"):
                raise PluginError("pin_not_found")
            cursor = response.get("next_cursor")
            if not isinstance(cursor, dict):
                raise PluginError("pin_cursor_invalid")


def _object(value, reason):
    if not isinstance(value, dict):
        raise PluginError(reason)
    return value


def _tool_error(code: str) -> dict:
    return {"status": "error", "output": {"code": code}}


def _tool_unknown(reason, wall_ms: int) -> dict:
    return {"status": "error", "output": {"code": reason or "unknown"},
            "usage": {"wall_ms": int(wall_ms)}}


def _resource_failure(kind: str, code: str) -> dict:
    if kind == "host_prepare":
        return {"v": 1, "prepared": False, "reason": code}
    return {"v": 1, "released": False, "reason": code}
