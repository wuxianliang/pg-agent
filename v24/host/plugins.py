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

import os

from . import line_json
from .canonical import CanonicalError, compact_json
from .db import HostContractError, is_error
from .line_json import LineJsonPreflight
from .registry import AdapterNotFound, ApprovedAdapterRegistry, ApprovedPlugin
from .renderers import RENDERERS, RendererError
from .tool_pages import ToolPageError, validate_page
from .tool_results import (
    ToolDispatchResult,
    ToolResultError,
    assert_builtin_meta,
    failure_output,
    join_content,
    measure,
    success_output,
    unknown_output,
)
from .tool_schema import InstanceError

_HOST_MESSAGE = {
    "invalid_tool_arguments":
        "arguments do not match the approved tool schema",
    "lease_insufficient":
        "remaining effect lease is shorter than the approved tool timeout",
    "workspace_unavailable":
        "the approved workspace root is not available",
    "invalid_tool_output":
        "tool output does not satisfy the approved contract",
    "output_too_large":
        "tool output exceeds the approved size budget",
    "render_failed":
        "the host renderer rejected the tool value",
    "invalid_tool_content":
        "the renderer produced an invalid content block",
    "renderer_not_approved":
        "the approved renderer is not available",
}
_UNKNOWN_MESSAGE = "tool process did not produce a decidable outcome"
_DISPATCH_FAILED = "tool dispatch failed before execution"
_RENDER_FAILURES = frozenset({
    "renderer_not_approved", "render_failed", "invalid_tool_content",
})


def _limits(tool) -> dict:
    return tool.descriptor["tool"]["limits"]


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
        entry = self.registry.lookup_install(install)
        if isinstance(entry, ApprovedPlugin):
            return self._tool_v2(effect, entry, install, pin, key, args)
        return self._tool_v1(effect, install, pin, key, args)

    def _tool_v1(self, effect: dict, install: dict, pin: dict, key: str,
                 args: dict):
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

    def _tool_v2(self, effect: dict, entry: ApprovedPlugin, install: dict,
                 pin: dict, key: str, args: dict):
        try:
            tool = self.registry.match_tool(install, pin, key).tool
            limits = _limits(tool)
            try:
                args_size = len(compact_json(args))
            except (CanonicalError, RecursionError, UnicodeError):
                return self._v2_failure(
                    "invalid_tool_arguments",
                    _HOST_MESSAGE["invalid_tool_arguments"], 0)
            if args_size > limits["max_args_bytes"]:
                return self._v2_failure(
                    "invalid_tool_arguments",
                    _HOST_MESSAGE["invalid_tool_arguments"], 0)
            try:
                tool.parameters_check(args)
            except InstanceError as exc:
                return self._instance_failure(
                    "invalid_tool_arguments", exc, 0)
            entry.require_artifact()
            root = entry.workspace_root
            if (not isinstance(root, str) or os.path.realpath(root) != root
                    or not os.path.isdir(root)):
                return self._v2_failure(
                    "workspace_unavailable",
                    _HOST_MESSAGE["workspace_unavailable"], 0)
            lease_until = effect.get("lease_until")
            if not isinstance(lease_until, str):
                return self._v2_failure(
                    "lease_insufficient",
                    _HOST_MESSAGE["lease_insufficient"], 0)
            try:
                remaining = self.db.remaining_lease_ms(lease_until)
            except Exception:
                remaining = None
            if type(remaining) is not int or remaining < tool.timeout_ms + 5000:
                return self._v2_failure(
                    "lease_insufficient",
                    _HOST_MESSAGE["lease_insufficient"], 0)
            reservation = f"v24:tool_call:{effect['effect_id']}"
            invocation = line_json.run(
                entry, "invoke", reservation, args, tool=key)
            self.last_invocation = invocation
            wall_ms = invocation.wall_ms
            if invocation.class_name == "unknown":
                return self._v2_unknown(invocation)
            if invocation.class_name == "failure":
                error = (invocation.result
                         if isinstance(invocation.result, dict) else {})
                return self._v2_failure(
                    error.get("code", "unknown"),
                    error.get("message", ""), wall_ms)
            value = invocation.result.get("value")
            wire_meta = invocation.result.get("meta")
            try:
                value_size = len(compact_json(value))
            except (CanonicalError, RecursionError, UnicodeError):
                return self._v2_failure(
                    "invalid_tool_output",
                    _HOST_MESSAGE["invalid_tool_output"], wall_ms)
            if value_size > limits["max_value_bytes"]:
                return self._v2_failure(
                    "output_too_large", _HOST_MESSAGE["output_too_large"],
                    wall_ms)
            try:
                tool.output_check(value)
            except InstanceError as exc:
                return self._instance_failure(
                    "invalid_tool_output", exc, wall_ms)
            try:
                assert_builtin_meta(wire_meta)
                validate_page(tool.render, args, value)
            except (ToolResultError, ToolPageError):
                return self._v2_failure(
                    "invalid_tool_output",
                    _HOST_MESSAGE["invalid_tool_output"], wall_ms)
            try:
                content, meta = RENDERERS.render(tool.render, args, value)
            except RendererError as exc:
                code = (exc.reason if exc.reason in _RENDER_FAILURES
                        else "render_failed")
                return self._v2_failure(code, _HOST_MESSAGE[code], wall_ms)
            try:
                measured = measure(args, value, content, meta)
            except ToolResultError:
                return self._v2_failure(
                    "invalid_tool_output",
                    _HOST_MESSAGE["invalid_tool_output"], wall_ms)
            if (measured["content"] > limits["max_content_bytes"]
                    or measured["meta"] > limits["max_meta_bytes"]):
                return self._v2_failure(
                    "output_too_large", _HOST_MESSAGE["output_too_large"],
                    wall_ms)
            return self._v2_success(value, content, meta, wall_ms)
        except (AdapterNotFound, LineJsonPreflight) as exc:
            reason = getattr(exc, "reason", "dispatch_failed")
            return self._v2_failure(
                reason, _HOST_MESSAGE.get(reason, _DISPATCH_FAILED), 0)

    def _v2_failure(self, code: str, message: str, wall_ms: int) -> dict:
        content = [{"type": "text",
                    "text": f"Error [{code}]: {message}"}]
        output = failure_output(code, message, content)
        result = {"status": "error", "output": output,
                  "usage": {"wall_ms": wall_ms}}
        dispatch = ToolDispatchResult("failure", result, join_content(content))
        return {"class": "failure", "result": result,
                "model_text": dispatch.model_text}

    def _v2_unknown(self, invocation) -> dict:
        reason = invocation.reason
        code = reason if isinstance(reason, str) and reason else "unknown"
        output = unknown_output(code, _UNKNOWN_MESSAGE)
        result = {"status": "error", "output": output,
                  "usage": {"wall_ms": invocation.wall_ms}}
        ToolDispatchResult("unknown", result, "")
        return {"class": "unknown", "result": result, "model_text": ""}

    def _v2_success(self, value, content: list, meta: dict,
                    wall_ms: int) -> dict:
        output = success_output(value, content, meta)
        result = {"status": "ok", "output": output,
                  "usage": {"wall_ms": wall_ms}}
        model_text = join_content(content)
        dispatch = ToolDispatchResult("success", result, model_text)
        return {"class": "success", "result": result,
                "model_text": dispatch.model_text}

    def _instance_failure(self, code: str, exc: InstanceError,
                          wall_ms: int) -> dict:
        path = getattr(exc, "path", "$")
        rule = getattr(exc, "rule", "invalid")
        if not isinstance(rule, str) or not rule:
            rule = "invalid"
        if (not isinstance(path, str) or len(path) > 256
                or "/" in path or "\\" in path or "\x00" in path):
            message = f"$: {rule}"
        else:
            message = f"{path}: {rule}"
        try:
            return self._v2_failure(code, message, wall_ms)
        except ToolResultError:
            return self._v2_failure(code, f"$: {rule}", wall_ms)

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
