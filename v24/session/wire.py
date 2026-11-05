"""Transport-neutral wire shapes, validation and cursor helpers."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

API_VERSION = 1
MAX_MESSAGE = 65536
MAX_KEY = 256
MAX_NAME = 120
MAX_TIMEOUT_MS = 600000
TOOLS = frozenset({"read", "write", "exec"})
BUDGET_KEYS = frozenset({"steps", "tool_calls", "tokens", "wall_ms"})
DEFAULT_TOKENS = 20000


class WireError(ValueError):
    def __init__(self, code, message="", details=None):
        super().__init__(code)
        self.code = code
        self.message = message
        self.details = details


def canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def sha256_hex(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def key_hash(key):
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _text(value, field, *, maximum, minimum=1):
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        raise WireError("invalid_args", field)
    return value


def _int(value, field, *, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise WireError("invalid_args", field)
    return value


def normalize_budget(value, *, default_tokens=DEFAULT_TOKENS):
    if value is None:
        return {"steps": 24, "tool_calls": 24, "tokens": default_tokens, "wall_ms": 600000}
    if not isinstance(value, dict) or set(value) - BUDGET_KEYS:
        raise WireError("invalid_args", "budget")
    # The frozen interpreter requires steps/tool_calls; tokens and wall_ms are
    # optional.  An absent tokens key means "unbounded" in v24 (the run's
    # remaining_tokens is NULL); null is rejected by the interpreter.
    steps = _int(value.get("steps"), "budget.steps", minimum=1, maximum=256)
    tool_calls = _int(value.get("tool_calls"), "budget.tool_calls", minimum=0, maximum=1024)
    normal = {"steps": steps, "tool_calls": tool_calls,
              "wall_ms": _int(value.get("wall_ms", 600000), "budget.wall_ms",
                              minimum=1, maximum=86400000)}
    if "tokens" in value:
        normal["tokens"] = _int(value["tokens"], "budget.tokens",
                                minimum=1, maximum=10**12)
    return normal


def normalize_start(request):
    if not isinstance(request, dict):
        raise WireError("invalid_args", "request")
    if request.get("op") not in (None, "start"):
        raise WireError("invalid_args", "op")
    if "session_id" in request:
        raise WireError("invalid_args", "start_does_not_accept_session_id")
    message = _text(request.get("message"), "message", maximum=MAX_MESSAGE)
    request_key = _text(request.get("request_key"), "request_key", maximum=MAX_KEY)
    name = request.get("name", request.get("session_name"))
    if name is not None:
        name = _text(name, "session_name", maximum=MAX_NAME)
    toolset = request.get("toolset")
    if toolset is not None and toolset not in TOOLS:
        raise WireError("invalid_args", "toolset")
    model = request.get("model")
    if model is not None:
        model = _text(model, "model", maximum=200)
    workspace = request.get("workspace_root")
    if workspace is not None:
        if not isinstance(workspace, str) or not Path(workspace).is_absolute():
            raise WireError("invalid_args", "workspace_root")
        workspace = str(Path(workspace).resolve())
    budget = normalize_budget(request.get("budget"))
    detach = request.get("detach", True)
    if not isinstance(detach, bool):
        raise WireError("invalid_args", "detach")
    timeout_ms = request.get("timeout_ms", 0)
    timeout_ms = _int(timeout_ms, "timeout_ms", minimum=0, maximum=MAX_TIMEOUT_MS)
    normal = {
        "message": message,
        "session_name": name,
        "model": model,
        "budget": budget,
        "toolset": toolset,
        "workspace_root": workspace,
    }
    return {
        "request_key": request_key,
        "normalized": normal,
        "digest": sha256_hex(normal),
        "key_hash": key_hash(request_key),
        "detach": detach,
        "timeout_ms": timeout_ms,
    }


def normalize_poll(request):
    if not isinstance(request, dict) or request.get("op") not in (None, "poll"):
        raise WireError("invalid_args", "request")
    single = request.get("session_id")
    many = request.get("session_ids")
    if (single is None) == (many is None):
        raise WireError("invalid_args", "session_id_xor_session_ids")
    if single is not None and not isinstance(single, str):
        raise WireError("invalid_args", "session_id")
    if many is not None:
        if (not isinstance(many, list) or not 1 <= len(many) <= 32
                or any(not isinstance(sid, str) for sid in many)):
            raise WireError("invalid_args", "session_ids")
    include = request.get("include_events", False)
    if not isinstance(include, bool):
        raise WireError("invalid_args", "include_events")
    cursor = request.get("cursor")
    if cursor is not None and not isinstance(cursor, dict):
        raise WireError("invalid_args", "cursor")
    return {"session_id": single, "session_ids": many, "include_events": include, "cursor": cursor}


def normalize_wait(request):
    if not isinstance(request, dict) or request.get("op") not in (None, "wait"):
        raise WireError("invalid_args", "request")
    single = request.get("session_id")
    many = request.get("session_ids")
    if (single is None) == (many is None):
        raise WireError("invalid_args", "session_id_xor_session_ids")
    if single is not None and not isinstance(single, str):
        raise WireError("invalid_args", "session_id")
    if many is not None:
        if (not isinstance(many, list) or not 1 <= len(many) <= 32
                or any(not isinstance(sid, str) for sid in many)):
            raise WireError("invalid_args", "session_ids")
    cursor = request.get("cursor")
    cursors = request.get("cursors")
    if cursor is not None and cursors is not None:
        raise WireError("invalid_args", "cursor_xor_cursors")
    if cursor is not None and not isinstance(cursor, dict):
        raise WireError("invalid_args", "cursor")
    if cursors is not None:
        if (not isinstance(cursors, dict) or len(cursors) > 32
                or any(not isinstance(key, str) or not isinstance(value, dict)
                       for key, value in cursors.items())):
            raise WireError("invalid_args", "cursors")
    timeout_ms = _int(request.get("timeout_ms", 120000), "timeout_ms",
                      minimum=0, maximum=MAX_TIMEOUT_MS)
    include = request.get("include_events", False)
    if not isinstance(include, bool):
        raise WireError("invalid_args", "include_events")
    return {"session_id": single, "session_ids": many, "cursor": cursor,
            "cursors": cursors, "timeout_ms": timeout_ms, "include_events": include}


def normalize_cancel(request):
    if not isinstance(request, dict) or request.get("op") not in (None, "cancel"):
        raise WireError("invalid_args", "request")
    session_id = _text(request.get("session_id"), "session_id", maximum=64)
    request_key = _text(request.get("request_key"), "request_key", maximum=MAX_KEY)
    expected_run_id = request.get("expected_run_id")
    if expected_run_id is not None and not isinstance(expected_run_id, str):
        raise WireError("invalid_args", "expected_run_id")
    expected_generation = request.get("expected_generation")
    if expected_generation is not None:
        expected_generation = _int(expected_generation, "expected_generation",
                                   minimum=0, maximum=10**9)
    normal = {"session_id": session_id, "expected_run_id": expected_run_id,
              "expected_generation": expected_generation}
    return {"session_id": session_id, "expected_run_id": expected_run_id,
            "expected_generation": expected_generation, "normalized": normal,
            "digest": sha256_hex(normal), "key_hash": key_hash(request_key)}


def _optional_dict(value, field):
    if value is not None and not isinstance(value, dict):
        raise WireError("invalid_args", field)
    return value


def normalize_steer(request):
    if not isinstance(request, dict) or request.get("op") not in (None, "steer"):
        raise WireError("invalid_args", "request")
    session_id = _text(request.get("session_id"), "session_id", maximum=64)
    message = _text(request.get("message"), "message", maximum=8192)
    request_key = _text(request.get("request_key"), "request_key", maximum=MAX_KEY)
    expected_run_id = request.get("expected_run_id")
    if expected_run_id is not None and not isinstance(expected_run_id, str):
        raise WireError("invalid_args", "expected_run_id")
    expected_generation = request.get("expected_generation")
    if expected_generation is not None:
        expected_generation = _int(expected_generation, "expected_generation",
                                   minimum=0, maximum=10**9)
    wait = request.get("wait", False)
    if not isinstance(wait, bool):
        raise WireError("invalid_args", "wait")
    timeout_ms = _int(request.get("timeout_ms", 0), "timeout_ms",
                      minimum=0, maximum=MAX_TIMEOUT_MS)
    if request.get("queue"):
        raise WireError("invalid_args", "queue")
    normal = {"session_id": session_id, "message": message,
              "expected_run_id": expected_run_id,
              "expected_generation": expected_generation}
    return {"session_id": session_id, "message": message,
            "expected_run_id": expected_run_id,
            "expected_generation": expected_generation, "wait": wait,
            "timeout_ms": timeout_ms, "normalized": normal,
            "digest": sha256_hex(normal), "key_hash": key_hash(request_key)}


def normalize_respond(request):
    if not isinstance(request, dict) or request.get("op") not in (None, "respond"):
        raise WireError("invalid_args", "request")
    session_id = _text(request.get("session_id"), "session_id", maximum=64)
    interaction_id = _text(request.get("interaction_id"), "interaction_id", maximum=128)
    request_key = _text(request.get("request_key"), "request_key", maximum=MAX_KEY)
    response = request.get("response")
    if response is not None and not isinstance(response, str):
        raise WireError("invalid_args", "response")
    answers = _optional_dict(request.get("answers"), "answers")
    content = _optional_dict(request.get("content"), "content")
    meta = _optional_dict(request.get("meta"), "meta")
    amendment = request.get("amendment")
    if amendment is not None and not isinstance(amendment, str):
        raise WireError("invalid_args", "amendment")
    if all(value is None for value in (response, answers, content, meta, amendment)):
        raise WireError("invalid_args", "response_required")
    if response == "" or amendment == "" or answers == {}:
        raise WireError("invalid_args", "response_empty")
    if amendment is not None:
        kernel = {"action": "accept_with_amendment", "amendment": amendment}
    elif answers is not None:
        kernel = {"answers": answers}
    elif content is not None or meta is not None:
        kernel = {"action": response or "accept"}
        if content is not None:
            kernel["content"] = content
        if meta is not None:
            kernel["meta"] = meta
    else:
        kernel = {"text": response}
    expected_generation = request.get("expected_generation")
    if expected_generation is not None:
        expected_generation = _int(expected_generation, "expected_generation",
                                   minimum=0, maximum=10**9)
    normal = {"session_id": session_id, "interaction_id": interaction_id,
              "response": kernel, "expected_generation": expected_generation}
    return {"session_id": session_id, "interaction_id": interaction_id,
            "response": kernel, "expected_generation": expected_generation,
            "normalized": normal, "digest": sha256_hex(normal),
            "key_hash": key_hash(request_key)}


def wake_reason(cursor, snap, *, include_events):
    """Return the highest-priority wake, or None for a revision-only change."""
    current = snap["cursor"]
    if cursor is None:
        return None
    if current.get("run_id") != cursor.get("run_id"):
        return "run_started"
    if snap.get("terminal"):
        return "terminal"
    interaction = snap.get("interaction") or {}
    if (snap.get("status") == "waiting_for_input"
            and interaction.get("interaction_id") != cursor.get("interaction_id")):
        return "interaction"
    if (current.get("registration_generation") != cursor.get("registration_generation")):
        return "epoch"
    if (current.get("epoch_no"), current.get("generation")) != (
            cursor.get("epoch_no"), cursor.get("generation")):
        return "epoch"
    if include_events and current.get("event_seq", 0) > cursor.get("event_seq", 0):
        return "event"
    return None


def public_status(session, run):
    state = session.get("state", "starting")
    if state == "closed":
        return "closed"
    if not run:
        return "idle" if state == "active" else "starting"
    status = run.get("status")
    if status == "waiting":
        return "waiting_for_input"
    if status in ("running", "completed", "failed", "cancelled", "blocked_unknown"):
        return status
    return "starting"


def run_view(run):
    if not isinstance(run, dict):
        return None
    keys = ("run_id", "status", "epoch_no", "registration_generation", "turn_no",
            "driving_generation", "revision", "created_at", "updated_at", "ended_at",
            "remaining_steps", "remaining_tokens", "remaining_tool_calls",
            "remaining_wall_ms", "interaction", "pending_steer", "close_intent", "result")
    view = {key: run.get(key) for key in keys if key in run}
    if view.get("status") not in ("completed", "failed", "cancelled", "blocked_unknown"):
        view["result"] = None
    return view


def cursor_for(session, run, *, event_seq=0):
    run = run or {}
    interaction = run.get("interaction") or {}
    return {
        "session_id": session.get("session_id"),
        "run_id": run.get("run_id"),
        "run_revision": int(run.get("revision", 0) or 0),
        "event_seq": int(event_seq or 0),
        "registration_generation": int(run.get("registration_generation", 0) or 0),
        "epoch_no": int(run.get("epoch_no", 0) or 0),
        "generation": int(run.get("driving_generation", 0) or 0),
        "interaction_id": interaction.get("interaction_id") if isinstance(interaction, dict) else None,
        "user_turn_no": int(session.get("user_turn_no", 0) or 0),
        "session_revision": int(session.get("session_revision", 0) or 0),
    }


def snapshot(session, run, *, event_seq=0):
    status = public_status(session, run)
    view = run_view(run)
    interaction = None
    if status == "waiting_for_input" and isinstance(run, dict):
        interaction = run.get("interaction")
    cursor = cursor_for(session, run, event_seq=event_seq)
    return {
        "v": API_VERSION,
        "session_id": session.get("session_id"),
        "name": session.get("name"),
        "state": session.get("state", "starting"),
        "status": status,
        "active": status in ("running", "waiting_for_input"),
        "terminal": status in ("completed", "failed", "cancelled", "blocked_unknown", "closed"),
        "workspace_root": session.get("workspace_root"),
        "toolset": session.get("toolset"),
        "model": session.get("model"),
        "created_at": session.get("created_at"),
        "updated_at": session.get("updated_at"),
        "run_no": int(session.get("run_no", 0) or 0),
        "user_turn_no": int(session.get("user_turn_no", 0) or 0),
        "current_run": view,
        "last_run": view,
        "interaction": interaction,
        "pending_steer": (run or {}).get("pending_steer") if isinstance(run, dict) else None,
        "counters": {
            "runs": int(session.get("run_no", 0) or 0),
            "effect_settlement_no": None,
            "model_round_no": None,
            "tool_round_no": None,
            "user_turn_no": int(session.get("user_turn_no", 0) or 0),
        },
        "cursor": cursor,
    }


def changed(cursor, current):
    if not isinstance(cursor, dict) or cursor.get("session_id") != current.get("session_id"):
        return True
    return any(cursor.get(field) != current.get(field)
               for field in ("run_id", "run_revision", "session_revision"))


def error_envelope(op, code, *, message="", details=None, session_id=None):
    payload = {"code": code}
    if message:
        payload["message"] = message
    if details is not None:
        payload["details"] = details
    envelope = {"v": API_VERSION, "op": op, "ok": False,
                "disposition": "rejected", "error": payload}
    if session_id is not None:
        envelope["session_id"] = session_id
    return envelope


def start_envelope(*, disposition, session, run, run_id, started, error=None):
    snap = snapshot(session, run)
    envelope = {
        "v": API_VERSION,
        "op": "start",
        "ok": disposition == "committed",
        "disposition": disposition,
        "session_id": session.get("session_id"),
        "run_id": run_id,
        "started": started,
        "snapshot": snap,
        "cursor": snap["cursor"],
        "error": error,
    }
    return envelope
