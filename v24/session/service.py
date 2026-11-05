"""Transport-neutral session service: start and poll (S0-M1)."""
from __future__ import annotations

import copy
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
