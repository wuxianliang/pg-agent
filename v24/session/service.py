"""Transport-neutral session service: start and poll (S0-M1)."""
from __future__ import annotations

import copy
import time
import uuid
from pathlib import Path

from . import wire
from .driver import SessionSerialDomain
from .store import StoreError
from .models import StartResult

_SAFE_ERRORS = frozenset({
    "invalid_args", "request_conflict", "not_found_or_denied", "scope_closed",
    "provider_unavailable", "dependency_unresolved", "budget_exceeded",
    "catalog_changed", "workspace_mismatch", "setup_incomplete", "session_busy",
    "session_closed", "owner_fenced", "invalid_run", "receipt_missing",
    "already_terminal", "interaction_pending", "interaction_mismatch",
    "not_waiting", "stale_generation", "waiting_unsupported", "blocked_unknown",
})


def _error_code(exc):
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code in _SAFE_ERRORS:
        return code
    text = str(exc)
    return text if text in _SAFE_ERRORS else "provider_unavailable"


class SessionService:
    def __init__(self, store, backend, *, principal_id="local"):
        self.store = store
        self.backend = backend
        self.principal_id = principal_id
        self.domain = SessionSerialDomain(store)
        self._wait_rotation = 0

    # ---- helpers -------------------------------------------------------------

    def _current_run_id(self, session):
        run_id = session.get("active_run_id")
        if run_id:
            return run_id
        bindings = session.get("bindings") or []
        return bindings[-1].get("run_id") if bindings else None

    def _projection(self, run_id):
        if not run_id:
            return {}
        value = self.backend.poll(str(run_id), 0)
        if not isinstance(value, dict):
            raise WireError("provider_unavailable", "projection")
        if isinstance(value.get("error"), dict):
            code = value["error"].get("code", "provider_unavailable")
            raise WireError(code if code in _SAFE_ERRORS else "provider_unavailable")
        return value

    def _start_result(self, value, *, session_id, workspace_root, toolset):
        if isinstance(value, StartResult):
            result = value
        elif isinstance(value, dict):
            if isinstance(value.get("error"), dict):
                code = value["error"].get("code", "provider_unavailable")
                raise WireError(code if code in _SAFE_ERRORS else "provider_unavailable")
            result = StartResult(
                run_id=value.get("run_id"),
                scope_id=value.get("scope_id"),
                realm=value.get("realm"),
                binding=value.get("binding") or {},
                run=value.get("run"),
            )
        elif isinstance(value, (tuple, list)) and value:
            result = StartResult(run_id=value[0],
                                 binding=value[1] if len(value) > 1 and isinstance(value[1], dict) else {})
        else:
            raise WireError("provider_unavailable", "start_result")
        if not isinstance(result.run_id, str) or not result.run_id:
            raise WireError("provider_unavailable", "run_id")
        run = result.run or {}
        if not run:
            try:
                run = self._projection(result.run_id).get("run") or {}
            except WireError:
                run = {}
        if not run:
            run = {"run_id": result.run_id, "status": "running", "revision": 1,
                   "epoch_no": 1, "registration_generation": 1, "driving_generation": 1}
        binding = dict(result.binding or {})
        binding["run_id"] = result.run_id
        if result.scope_id is not None:
            binding.setdefault("scope_id", result.scope_id)
        if result.realm is not None:
            binding.setdefault("realm", result.realm)
        binding.setdefault("workspace_root", str(Path(workspace_root).resolve()) if workspace_root else "")
        binding.setdefault("toolset", toolset or "")
        binding.setdefault("at", run.get("created_at") or "")
        if not isinstance(binding.get("scope_id"), str):
            raise WireError("setup_incomplete", "scope_id")
        return result, run, binding

    def _deferred(self, session, *, run_id, code, command_id=None):
        error = {"code": code}
        envelope = wire.start_envelope(
            disposition="deferred", session=session, run=None, run_id=run_id,
            started=False, error=error)
        if command_id is not None:
            try:
                self.store.freeze_deferred(session["session_id"], command_id, envelope)
            except StoreError:
                pass
        return envelope

    def _replay(self, receipt):
        envelope = copy.deepcopy(receipt.get("original_envelope"))
        if not isinstance(envelope, dict):
            return None
        if receipt.get("frozen_deferred"):
            envelope["ok"] = False
            envelope["disposition"] = "deferred"
            envelope["started"] = False
            return envelope
        envelope["ok"] = True
        envelope["disposition"] = "replay"
        envelope["started"] = bool(envelope.get("run_id"))
        envelope["error"] = None
        return envelope

    # ---- start ---------------------------------------------------------------

    def start(self, request):
        with self.domain.enter():
            try:
                norm = wire.normalize_start(request)
            except wire.WireError as exc:
                return wire.error_envelope("start", exc.code, message=exc.message)
            hit = self.store.get_start(self.principal_id, norm["key_hash"])
            if hit is not None:
                return self._replay_start(hit, norm)
            session_id = str(uuid.uuid4())
            run_key = f"s:{session_id}:start:{norm['key_hash'][:32]}"
            command_id = str(uuid.uuid4())
            name = norm["normalized"]["session_name"]
            if not name:
                name = norm["normalized"]["message"][:40]
            try:
                self.store.begin_start(
                    session_id=session_id, principal_id=self.principal_id,
                    key_hash=norm["key_hash"], command_id=command_id,
                    run_key=run_key, normalized_request=norm["normalized"],
                    digest=norm["digest"], name=name,
                    metadata={
                        "toolset": norm["normalized"]["toolset"],
                        "workspace_root": norm["normalized"]["workspace_root"],
                        "model": norm["normalized"]["model"] or "deepseek-flash",
                    })
            except StoreError as exc:
                return wire.error_envelope("start", _error_code(exc))
            session = self.store.get(session_id)
            try:
                value = self.backend.start(
                    session_id=session_id,
                    message=norm["normalized"]["message"],
                    toolset=norm["normalized"]["toolset"],
                    budget=norm["normalized"]["budget"],
                    run_key=run_key,
                    workspace_root=norm["normalized"]["workspace_root"],
                    model=norm["normalized"]["model"],
                )
                result, run, binding = self._start_result(
                    value, session_id=session_id,
                    workspace_root=norm["normalized"]["workspace_root"],
                    toolset=norm["normalized"]["toolset"])
            except Exception as exc:
                return self._deferred(session, run_id=getattr(exc, "run_id", None),
                                      code=_error_code(exc), command_id=command_id)
            holder = {}
            def build_envelope(session_row, _run_id):
                envelope = wire.start_envelope(
                    disposition="committed", session=session_row, run=run,
                    run_id=result.run_id, started=True, error=None)
                holder["envelope"] = envelope
                return envelope
            try:
                self.store.complete_start(
                    session_id=session_id, owner_epoch=session["pending_intent"]["owner_epoch"],
                    run_id=result.run_id, binding=binding,
                    message=norm["normalized"]["message"], envelope_factory=build_envelope)
            except Exception as exc:
                return self._deferred(session, run_id=result.run_id,
                                      code=_error_code(exc), command_id=command_id)
            self.domain.notify()
            return holder["envelope"]

    def _replay_start(self, hit, norm):
        session_id = hit.get("session_id")
        session = self.store.get(session_id)
        if session is None:
            return wire.error_envelope("start", "not_found_or_denied")
        if hit.get("digest") not in (None, norm["digest"]):
            return wire.error_envelope("start", "request_conflict", session_id=session_id)
        receipt = self.store.get_receipt(session_id, "start", norm["key_hash"])
        if receipt is not None:
            replay = self._replay(receipt)
            if replay is not None:
                return replay
        # Intent without a frozen response: return the same deferred answer and
        # freeze it so a later call cannot turn the same key into a commit.
        pending = session.get("pending_intent") or {}
        return self._deferred(session, run_id=pending.get("run_id"),
                              code="setup_incomplete",
                              command_id=(receipt or {}).get("command_id"))

    # ---- steer / respond -----------------------------------------------------

    def _replay_command(self, receipt):
        envelope = copy.deepcopy(receipt.get("original_envelope"))
        if not isinstance(envelope, dict):
            return None
        envelope["disposition"] = "deferred" if receipt.get("frozen_deferred") else "replay"
        return envelope

    def _reject_command(self, session, op, norm, code, *, details=None, run=None):
        command_id = str(uuid.uuid4())
        try:
            self.store.begin_command(
                session["session_id"], principal_id=self.principal_id, op=op,
                key_hash=norm["key_hash"], command_id=command_id,
                normalized_request=norm["normalized"], digest=norm["digest"],
                target_run_id=(run or {}).get("run_id"))
        except StoreError as exc:
            return wire.error_envelope(op, _error_code(exc), session_id=session["session_id"])
        snap = wire.snapshot(session, run)
        error = {"code": code}
        if details is not None:
            error["details"] = details
        envelope = {
            "v": wire.API_VERSION, "op": op, "ok": False,
            "disposition": "rejected", "session_id": session["session_id"],
            "run_id": (run or {}).get("run_id"), "error": error,
            "snapshot": snap, "cursor": snap["cursor"],
        }
        self.store.complete_command(session["session_id"], command_id, envelope,
                                    outcome="rejected",
                                    target_run_id=(run or {}).get("run_id"))
        return envelope

    def steer(self, request):
        try:
            norm = wire.normalize_steer(request)
        except wire.WireError as exc:
            return wire.error_envelope("steer", exc.code, message=exc.message)
        response = self._steer_locked(request)
        if norm["wait"] and response.get("ok"):
            waited = self.wait({"session_id": norm["session_id"],
                                "cursor": response["cursor"],
                                "timeout_ms": norm["timeout_ms"],
                                "include_events": False})
            response["wake"] = waited.get("wake", {"ready": False, "reason": "none"})
            if "snapshot" in waited:
                response["snapshot"] = waited["snapshot"]
                response["cursor"] = waited["cursor"]
        return response

    def _steer_locked(self, request):
        with self.domain.enter():
            try:
                norm = wire.normalize_steer(request)
            except wire.WireError as exc:
                return wire.error_envelope("steer", exc.code, message=exc.message)
            session = self.store.get(norm["session_id"])
            if session is None:
                return wire.error_envelope("steer", "not_found_or_denied")
            sid = norm["session_id"]
            if session.get("state") == "closed":
                return wire.error_envelope("steer", "session_closed", session_id=sid)
            receipt = self.store.get_receipt(sid, "steer", norm["key_hash"])
            if receipt is not None:
                if receipt.get("digest") not in (None, norm["digest"]):
                    return wire.error_envelope("steer", "request_conflict", session_id=sid)
                replay = self._replay_command(receipt)
                if replay is not None:
                    return replay
            run_id = self._current_run_id(session)
            run = None
            if run_id:
                try:
                    run = self._projection(run_id).get("run")
                except wire.WireError as exc:
                    return wire.error_envelope("steer", exc.code, session_id=sid)
            status = wire.public_status(session, run)
            if norm["expected_run_id"] is not None and norm["expected_run_id"] != run_id:
                return wire.error_envelope("steer", "stale_generation", session_id=sid)
            generation = int((run or {}).get("driving_generation", 0) or 0)
            if (norm["expected_generation"] is not None
                    and norm["expected_generation"] != generation):
                return wire.error_envelope("steer", "stale_generation", session_id=sid)

            if session.get("state") == "starting" or session.get("pending_intent"):
                return self._reject_command(session, "steer", norm,
                                            "setup_incomplete" if session.get("pending_intent")
                                            else "session_busy", run=run)
            if status == "waiting_for_input":
                interaction = (run or {}).get("interaction") or {}
                return self._reject_command(session, "steer", norm, "interaction_pending",
                                            details={"interaction_id": interaction.get("interaction_id")},
                                            run=run)
            if status == "blocked_unknown":
                return self._reject_command(session, "steer", norm, "blocked_unknown", run=run)
            if status == "starting":
                return self._reject_command(session, "steer", norm, "setup_incomplete", run=run)

            if status in ("completed", "failed", "cancelled", "closed", "idle"):
                command_id = str(uuid.uuid4())
                run_key = f"s:{sid}:steer:{norm['key_hash'][:32]}"
                pending = {"op": "steer", "command_id": command_id,
                           "variant": "steer_new_run", "run_key": run_key,
                           "owner_epoch": int(session.get("session_revision", 0)) + 1,
                           "phase": "intent"}
                try:
                    self.store.begin_command(
                        sid, principal_id=self.principal_id, op="steer",
                        key_hash=norm["key_hash"], command_id=command_id,
                        normalized_request=norm["normalized"], digest=norm["digest"],
                        pending_intent=pending)
                except StoreError as exc:
                    return wire.error_envelope("steer", _error_code(exc), session_id=sid)
                try:
                    value = self.backend.start(
                        session_id=sid, message=norm["message"],
                        toolset=session.get("toolset") or None,
                        budget=wire.normalize_budget(None), run_key=run_key,
                        workspace_root=session.get("workspace_root"),
                        model=session.get("model"),
                        seed=self._seed_messages(sid, norm["message"]))
                    result, new_run, binding = self._start_result(
                        value, session_id=sid,
                        workspace_root=session.get("workspace_root"),
                        toolset=session.get("toolset"))
                except Exception as exc:
                    snap = wire.snapshot(session, run)
                    envelope = {
                        "v": wire.API_VERSION, "op": "steer", "ok": False,
                        "disposition": "deferred", "session_id": sid,
                        "run_id": None, "started": False, "queued": False,
                        "superseded": False, "error": {"code": _error_code(exc)},
                        "snapshot": snap, "cursor": snap["cursor"],
                    }
                    self.store.freeze_command(sid, command_id, envelope)
                    return envelope
                holder = {}
                def build_steer_envelope(session_row):
                    envelope = {
                        "v": wire.API_VERSION, "op": "steer", "ok": True,
                        "disposition": "committed", "session_id": sid,
                        "run_id": result.run_id, "started": True,
                        "queued": False, "superseded": False,
                        "snapshot": wire.snapshot(session_row, new_run),
                    }
                    envelope["cursor"] = envelope["snapshot"]["cursor"]
                    holder["envelope"] = envelope
                    return envelope
                try:
                    self.store.complete_steer_run(sid, command_id, result.run_id,
                                                  binding, norm["message"],
                                                  build_steer_envelope)
                except Exception as exc:
                    snap = wire.snapshot(session, run)
                    envelope = {
                        "v": wire.API_VERSION, "op": "steer", "ok": False,
                        "disposition": "deferred", "session_id": sid,
                        "run_id": result.run_id, "started": False, "queued": False,
                        "superseded": False, "error": {"code": _error_code(exc)},
                        "snapshot": snap, "cursor": snap["cursor"],
                    }
                    self.store.freeze_command(sid, command_id, envelope)
                    return envelope
                self.domain.notify()
                return holder["envelope"]

            # Active run: queue the instruction on the same run.
            command_id = str(uuid.uuid4())
            try:
                self.store.begin_command(
                    sid, principal_id=self.principal_id, op="steer",
                    key_hash=norm["key_hash"], command_id=command_id,
                    normalized_request=norm["normalized"], digest=norm["digest"],
                    target_run_id=run_id)
            except StoreError as exc:
                return wire.error_envelope("steer", _error_code(exc), session_id=sid)
            try:
                value = self.backend.steer(run_id, norm["message"], generation,
                                           self._command_key("steer", norm))
                if isinstance(value, dict) and isinstance(value.get("error"), dict):
                    code = value["error"].get("code", "provider_unavailable")
                    raise wire.WireError(code if code in _SAFE_ERRORS else "provider_unavailable")
            except Exception as exc:
                code = _error_code(exc)
                snap = wire.snapshot(session, run)
                if code in ("already_terminal", "interaction_pending",
                            "blocked_unknown", "stale_generation"):
                    envelope = {
                        "v": wire.API_VERSION, "op": "steer", "ok": False,
                        "disposition": "rejected", "session_id": sid,
                        "run_id": run_id, "started": False, "queued": False,
                        "superseded": False, "error": {"code": code},
                        "snapshot": snap, "cursor": snap["cursor"],
                    }
                    self.store.complete_command(sid, command_id, envelope,
                                                outcome="rejected", target_run_id=run_id)
                    return envelope
                envelope = {
                    "v": wire.API_VERSION, "op": "steer", "ok": False,
                    "disposition": "deferred", "session_id": sid,
                    "run_id": run_id, "started": False, "queued": False,
                    "superseded": False, "error": {"code": code},
                    "snapshot": snap, "cursor": snap["cursor"],
                }
                self.store.freeze_command(sid, command_id, envelope)
                return envelope
            if isinstance(value, dict) and isinstance(value.get("run"), dict):
                run = value["run"]
            else:
                try:
                    run = self._projection(run_id).get("run") or run
                except wire.WireError:
                    pass
            queued = bool(value.get("queued", True)) if isinstance(value, dict) else True
            superseded = bool(value.get("superseded", False)) if isinstance(value, dict) else False
            holder = {}
            def build_active_envelope(session_row):
                envelope = {
                    "v": wire.API_VERSION, "op": "steer", "ok": True,
                    "disposition": "committed", "session_id": sid,
                    "run_id": run_id, "started": False,
                    "queued": queued, "superseded": superseded,
                    "snapshot": wire.snapshot(session_row, run),
                }
                envelope["cursor"] = envelope["snapshot"]["cursor"]
                holder["envelope"] = envelope
                return envelope
            try:
                self.store.complete_steer_active(sid, command_id, run_id,
                                                  norm["message"], build_active_envelope)
            except Exception as exc:
                snap = wire.snapshot(session, run)
                envelope = {
                    "v": wire.API_VERSION, "op": "steer", "ok": False,
                    "disposition": "deferred", "session_id": sid,
                    "run_id": run_id, "started": False, "queued": False,
                    "superseded": False, "error": {"code": _error_code(exc)},
                    "snapshot": snap, "cursor": snap["cursor"],
                }
                self.store.freeze_command(sid, command_id, envelope)
                return envelope
            self.domain.notify()
            return holder["envelope"]

    def respond(self, request):
        with self.domain.enter():
            try:
                norm = wire.normalize_respond(request)
            except wire.WireError as exc:
                return wire.error_envelope("respond", exc.code, message=exc.message)
            session = self.store.get(norm["session_id"])
            if session is None:
                return wire.error_envelope("respond", "not_found_or_denied")
            sid = norm["session_id"]
            if session.get("state") == "closed":
                return wire.error_envelope("respond", "session_closed", session_id=sid)
            receipt = self.store.get_receipt(sid, "respond", norm["key_hash"])
            if receipt is not None:
                if receipt.get("digest") not in (None, norm["digest"]):
                    return wire.error_envelope("respond", "request_conflict", session_id=sid)
                replay = self._replay_command(receipt)
                if replay is not None:
                    return replay
            run_id = self._current_run_id(session)
            if not run_id:
                return wire.error_envelope("respond", "not_waiting", session_id=sid)
            try:
                run = self._projection(run_id).get("run")
            except wire.WireError as exc:
                return wire.error_envelope("respond", exc.code, session_id=sid)
            status = wire.public_status(session, run)
            if status in ("completed", "failed", "cancelled", "blocked_unknown"):
                return wire.error_envelope("respond", "already_terminal", session_id=sid,
                                           details={"status": status})
            if status != "waiting_for_input":
                return wire.error_envelope("respond", "not_waiting", session_id=sid)
            interaction = (run or {}).get("interaction") or {}
            if interaction.get("interaction_id") != norm["interaction_id"]:
                return wire.error_envelope("respond", "interaction_mismatch", session_id=sid)
            generation = int((run or {}).get("driving_generation", 0) or 0)
            if (norm["expected_generation"] is not None
                    and norm["expected_generation"] != generation):
                return wire.error_envelope("respond", "stale_generation", session_id=sid)
            command_id = str(uuid.uuid4())
            try:
                self.store.begin_command(
                    sid, principal_id=self.principal_id, op="respond",
                    key_hash=norm["key_hash"], command_id=command_id,
                    normalized_request=norm["normalized"], digest=norm["digest"],
                    target_run_id=run_id)
            except StoreError as exc:
                return wire.error_envelope("respond", _error_code(exc), session_id=sid)
            try:
                value = self.backend.respond(run_id, norm["interaction_id"],
                                             norm["response"], generation,
                                             self._command_key("respond", norm))
                if isinstance(value, dict) and isinstance(value.get("error"), dict):
                    code = value["error"].get("code", "provider_unavailable")
                    raise wire.WireError(code if code in _SAFE_ERRORS else "provider_unavailable")
            except Exception as exc:
                code = _error_code(exc)
                snap = wire.snapshot(session, run)
                envelope = {
                    "v": wire.API_VERSION, "op": "respond", "ok": False,
                    "disposition": "rejected", "session_id": sid,
                    "run_id": run_id, "error": {"code": code},
                    "snapshot": snap, "cursor": snap["cursor"],
                }
                self.store.complete_command(sid, command_id, envelope,
                                            outcome="rejected", target_run_id=run_id)
                return envelope
            try:
                run = self._projection(run_id).get("run") or run
            except wire.WireError:
                pass
            snap = wire.snapshot(session, run)
            envelope = {
                "v": wire.API_VERSION, "op": "respond", "ok": True,
                "disposition": "committed", "session_id": sid,
                "run_id": run_id, "consumed_interaction_id": norm["interaction_id"],
                "snapshot": snap, "cursor": snap["cursor"],
            }
            self.store.complete_command(sid, command_id, envelope,
                                        outcome="committed", target_run_id=run_id)
            self.domain.notify()
            return envelope

    # ---- wait ----------------------------------------------------------------

    def _read_state(self, session_id, cursor, include_events, *, baseline=False):
        with self.domain.enter():
            session = self.store.get(session_id)
            if session is None:
                return {"error": "not_found_or_denied"}
            run_id = self._current_run_id(session)
            try:
                projection = self._projection(run_id)
            except wire.WireError as exc:
                return {"error": exc.code}
            run = projection.get("run") if isinstance(projection, dict) else None
            events = projection.get("events", []) if isinstance(projection, dict) else []
            if not isinstance(events, list):
                events = []
            events = [event for event in events if isinstance(event, dict)][:64]
            event_seq = 0
            if isinstance(cursor, dict) and cursor.get("session_id") == session_id:
                if cursor.get("run_id") == (run or {}).get("run_id"):
                    value = cursor.get("event_seq", 0)
                    event_seq = value if type(value) is int and value >= 0 else 0
            high = max([0] + [event.get("seq", 0) for event in events
                              if type(event.get("seq")) is int])
            if baseline and cursor is None:
                event_seq = high
            elif include_events:
                event_seq = max(event_seq, high)
            snap = wire.snapshot(session, run, event_seq=event_seq)
            return {"session": session, "run": run, "snapshot": snap,
                    "events": events, "high_water": high}

    def _wait_response(self, session_id, reason, state, *, include_events, cursor):
        snap = state["snapshot"]
        if reason == "epoch":
            snap = wire.snapshot(state["session"], state["run"], event_seq=0)
        ready = reason not in ("timeout", "none")
        response = {
            "v": wire.API_VERSION,
            "op": "wait",
            "ok": True,
            "disposition": "read",
            "session_id": session_id,
            "run_id": snap["cursor"].get("run_id"),
            "wake": {"ready": ready, "reason": reason},
            "snapshot": snap,
            "events": state["events"] if include_events and reason in (
                "run_started", "terminal", "interaction", "epoch", "event") else [],
            "cursor": snap["cursor"],
            "changed": ready or (wire.changed(cursor, snap["cursor"])
                                 if cursor is not None else True),
        }
        if reason == "interaction":
            interaction = snap.get("interaction") or {}
            response["interaction_id"] = interaction.get("interaction_id")
        return response

    def _wait_single(self, session_id, cursor, timeout_ms, include_events):
        deadline = time.monotonic() + timeout_ms / 1000.0
        baseline = cursor is None
        while True:
            state = self._read_state(session_id, cursor, include_events, baseline=baseline)
            if "error" in state:
                return wire.error_envelope("wait", state["error"], session_id=session_id)
            if cursor is None:
                cursor = state["snapshot"]["cursor"]
            reason = wire.wake_reason(cursor, state["snapshot"], include_events=include_events)
            if reason:
                return self._wait_response(session_id, reason, state,
                                           include_events=include_events, cursor=cursor)
            if timeout_ms == 0:
                return self._wait_response(session_id, "none", state,
                                           include_events=include_events, cursor=cursor)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return self._wait_response(session_id, "timeout", state,
                                           include_events=include_events, cursor=cursor)
            self.domain.pause(min(0.02, remaining))

    def _wait_many(self, session_ids, cursors, timeout_ms, include_events):
        deadline = time.monotonic() + timeout_ms / 1000.0
        base = dict(cursors or {})
        rotation = self._wait_rotation
        self._wait_rotation = (self._wait_rotation + 1) % max(1, len(session_ids))
        order = [session_ids[(rotation + index) % len(session_ids)]
                 for index in range(len(session_ids))]
        while True:
            states = {}
            errors = {}
            for session_id in session_ids:
                state = self._read_state(session_id, base.get(session_id), include_events,
                                         baseline=session_id not in base)
                if "error" in state:
                    errors[session_id] = {"code": state["error"]}
                    continue
                states[session_id] = state
                if session_id not in base:
                    base[session_id] = state["snapshot"]["cursor"]
            if errors:
                return {"v": wire.API_VERSION, "op": "wait", "ok": False,
                        "disposition": "rejected", "errors": errors}
            winner = None
            reason = None
            for session_id in order:
                candidate = wire.wake_reason(base[session_id], states[session_id]["snapshot"],
                                             include_events=include_events)
                if candidate:
                    winner, reason = session_id, candidate
                    break
            if winner is None and timeout_ms == 0:
                winner, reason = order[0], "none"
            if winner is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    winner, reason = order[0], "timeout"
                else:
                    self.domain.pause(min(0.02, remaining))
                    continue
            state = states[winner]
            response = self._wait_response(winner, reason, state,
                                           include_events=include_events,
                                           cursor=base[winner])
            response["winner_session_id"] = winner
            response["pending_session_ids"] = [sid for sid in session_ids if sid != winner]
            response["all_terminal"] = all(item["snapshot"]["terminal"]
                                           for item in states.values())
            response["cursors"] = dict(base)
            response["cursors"][winner] = response["cursor"]
            return response

    def wait(self, request):
        try:
            norm = wire.normalize_wait(request)
        except wire.WireError as exc:
            return wire.error_envelope("wait", exc.code, message=exc.message)
        if norm["session_id"] is not None:
            return self._wait_single(norm["session_id"], norm["cursor"],
                                     norm["timeout_ms"], norm["include_events"])
        return self._wait_many(norm["session_ids"], norm["cursors"],
                               norm["timeout_ms"], norm["include_events"])

    # ---- cancel --------------------------------------------------------------

    def _cancel_replay(self, receipt):
        if receipt.get("digest") is None:
            return None
        envelope = copy.deepcopy(receipt.get("original_envelope"))
        if not isinstance(envelope, dict):
            return None
        envelope["disposition"] = "deferred" if receipt.get("frozen_deferred") else "replay"
        return envelope

    def cancel(self, request):
        with self.domain.enter():
            try:
                norm = wire.normalize_cancel(request)
            except wire.WireError as exc:
                return wire.error_envelope("cancel", exc.code, message=exc.message)
            session = self.store.get(norm["session_id"])
            if session is None:
                return wire.error_envelope("cancel", "not_found_or_denied")
            sid = norm["session_id"]
            if session.get("state") == "closed":
                return wire.error_envelope("cancel", "session_closed", session_id=sid)
            receipt = self.store.get_receipt(sid, "cancel", norm["key_hash"])
            if receipt is not None:
                if receipt.get("digest") not in (None, norm["digest"]):
                    return wire.error_envelope("cancel", "request_conflict", session_id=sid)
                replay = self._cancel_replay(receipt)
                if replay is not None:
                    return replay
            run_id = self._current_run_id(session)
            run = None
            if run_id:
                try:
                    run = self._projection(run_id).get("run")
                except wire.WireError as exc:
                    if receipt is None:
                        return wire.error_envelope("cancel", exc.code, session_id=sid)
            if norm["expected_run_id"] is not None and norm["expected_run_id"] != run_id:
                return wire.error_envelope("cancel", "stale_generation", session_id=sid)
            generation = int((run or {}).get("driving_generation", 0) or 0)
            if (norm["expected_generation"] is not None
                    and norm["expected_generation"] != generation):
                return wire.error_envelope("cancel", "stale_generation", session_id=sid)

            if receipt is None:
                command_id = str(uuid.uuid4())
                try:
                    receipt = self.store.begin_command(
                        sid, principal_id=self.principal_id, op="cancel",
                        key_hash=norm["key_hash"], command_id=command_id,
                        normalized_request=norm["normalized"], digest=norm["digest"],
                        target_run_id=run_id)
                except StoreError as exc:
                    return wire.error_envelope("cancel", _error_code(exc), session_id=sid)
            command_id = receipt.get("command_id")

            if session.get("state") == "starting":
                closed = dict(session)
                closed["state"] = "closed"
                closed["pending_intent"] = None
                closed["active_run_id"] = None
                snap = wire.snapshot(closed, None)
                envelope = {
                    "v": wire.API_VERSION, "op": "cancel", "ok": True,
                    "disposition": "committed", "session_id": sid,
                    "run_id": run_id, "already_terminal": False,
                    "snapshot": snap, "cursor": snap["cursor"],
                }
                self.store.complete_command(sid, command_id, envelope,
                                            outcome="committed", state="closed")
                self.domain.notify()
                return envelope

            if run_id is None:
                snap = wire.snapshot(session, None)
                envelope = {
                    "v": wire.API_VERSION, "op": "cancel", "ok": False,
                    "disposition": "rejected", "session_id": sid,
                    "run_id": None, "already_terminal": True,
                    "error": {"code": "already_terminal"},
                    "snapshot": snap, "cursor": snap["cursor"],
                }
                self.store.complete_command(sid, command_id, envelope, outcome="rejected")
                return envelope

            status = (run or {}).get("status")
            if status in ("completed", "failed", "cancelled", "blocked_unknown"):
                snap = wire.snapshot(session, run)
                envelope = {
                    "v": wire.API_VERSION, "op": "cancel", "ok": False,
                    "disposition": "rejected", "session_id": sid,
                    "run_id": run_id, "already_terminal": True,
                    "error": {"code": "already_terminal"},
                    "snapshot": snap, "cursor": snap["cursor"],
                }
                self.store.complete_command(sid, command_id, envelope,
                                            outcome="rejected", target_run_id=run_id)
                return envelope

            backend_already = False
            returned_run = None
            try:
                value = self.backend.cancel(run_id, self._command_key("cancel", norm))
                if isinstance(value, dict):
                    if isinstance(value.get("error"), dict):
                        code = value["error"].get("code", "provider_unavailable")
                        if code == "already_terminal":
                            backend_already = True
                        else:
                            raise wire.WireError(code if code in _SAFE_ERRORS else "provider_unavailable")
                    if isinstance(value.get("run"), dict):
                        returned_run = value["run"]
            except Exception as exc:
                if _error_code(exc) != "already_terminal":
                    snap = wire.snapshot(session, run)
                    envelope = {
                        "v": wire.API_VERSION, "op": "cancel", "ok": False,
                        "disposition": "deferred", "session_id": sid,
                        "run_id": run_id, "already_terminal": False,
                        "error": {"code": _error_code(exc)},
                        "snapshot": snap, "cursor": snap["cursor"],
                    }
                    self.store.freeze_command(sid, command_id, envelope)
                    return envelope
                backend_already = True
            try:
                projection = self._projection(run_id)
                run = projection.get("run") or returned_run or run
            except wire.WireError:
                run = returned_run or run
            if backend_already:
                snap = wire.snapshot(session, run)
                envelope = {
                    "v": wire.API_VERSION, "op": "cancel", "ok": False,
                    "disposition": "rejected", "session_id": sid,
                    "run_id": run_id, "already_terminal": True,
                    "error": {"code": "already_terminal"},
                    "snapshot": snap, "cursor": snap["cursor"],
                }
                self.store.complete_command(sid, command_id, envelope,
                                            outcome="rejected", target_run_id=run_id)
                return envelope
            snap = wire.snapshot(session, run)
            envelope = {
                "v": wire.API_VERSION, "op": "cancel", "ok": True,
                "disposition": "committed", "session_id": sid,
                "run_id": run_id, "already_terminal": False,
                "snapshot": snap, "cursor": snap["cursor"],
            }
            self.store.complete_command(sid, command_id, envelope,
                                        outcome="committed", target_run_id=run_id)
            self.domain.notify()
            return envelope

    def _command_key(self, op, norm):
        return f"{op[0]}:{norm['session_id']}:{norm['key_hash'][:48]}"

    def _seed_messages(self, session_id, message):
        block = self.store.history_block(session_id)
        return [{"role": "system", "content": block},
                {"role": "user", "content": message}]

    # ---- poll ----------------------------------------------------------------

    def poll(self, request):
        with self.domain.enter():
            try:
                norm = wire.normalize_poll(request)
            except wire.WireError as exc:
                return wire.error_envelope("poll", exc.code, message=exc.message)
            if norm["session_ids"] is not None:
                items = [self._poll_one(sid, None, norm["include_events"])
                         for sid in norm["session_ids"]]
                return {"v": wire.API_VERSION, "op": "poll", "ok": True,
                        "disposition": "read", "sessions": items}
            return self._poll_one(norm["session_id"], norm["cursor"], norm["include_events"],
                                  single=True)

    def _poll_one(self, session_id, cursor, include_events, *, single=False):
        session = self.store.get(session_id)
        if session is None:
            if single:
                return wire.error_envelope("poll", "not_found_or_denied")
            return {"session_id": session_id, "ok": False,
                    "error": {"code": "not_found_or_denied"}}
        run_id = self._current_run_id(session)
        try:
            projection = self._projection(run_id)
        except wire.WireError as exc:
            if single:
                return wire.error_envelope("poll", exc.code, session_id=session_id)
            return {"session_id": session_id, "ok": False, "error": {"code": exc.code}}
        run = projection.get("run") if isinstance(projection, dict) else None
        events = projection.get("events", []) if isinstance(projection, dict) else []
        if not isinstance(events, list):
            events = []
        # v24.poll itself limits to the earliest 64; keep the S0 contract even
        # when a test/backend returns a larger page.
        events = [event for event in events if isinstance(event, dict)][:64]
        event_seq = 0
        if isinstance(cursor, dict) and cursor.get("session_id") == session_id:
            if cursor.get("run_id") == (run or {}).get("run_id"):
                value = cursor.get("event_seq", 0)
                event_seq = value if type(value) is int and value >= 0 else 0
        snap = wire.snapshot(session, run, event_seq=event_seq)
        if include_events and events:
            event_seq = max([event_seq] + [e.get("seq", 0) for e in events
                                          if isinstance(e, dict) and type(e.get("seq")) is int])
            snap = wire.snapshot(session, run, event_seq=event_seq)
        result = {
            "v": wire.API_VERSION,
            "op": "poll",
            "ok": True,
            "disposition": "read",
            "session_id": session_id,
            "run_id": (run or {}).get("run_id"),
            "changed": wire.changed(cursor, snap["cursor"]),
            "snapshot": snap,
            "events": events if include_events else [],
            "cursor": snap["cursor"],
        }
        if not single:
            result.pop("op", None)
            result.pop("v", None)
            result.pop("disposition", None)
        return result

    def snapshot(self, session_id):
        with self.domain.enter():
            return self._poll_one(session_id, None, False, single=True).get("snapshot")
