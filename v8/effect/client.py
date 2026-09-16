"""v8/effect/client.py — Python command client for the G4 effect loop.

Same frozen command convention as G3: the caller builds the FULL command
request object (command kind, target identity, expected values, complete
business payload), runs escape_dollar_keys + canonicalize to obtain the
canonical text and hash, and hands the canonical text plus the DECLARED
hash to SQL; SQL recomputes v_sha256_hex and compares. Receipts and
bindings always key on the computed hash.

claim / recovery_claim / yield are coordination lease CAS operations, not
receipt commands: they take no command_id and return a plain jsonb result.

Every command function runs gate + business function + commit in ONE
transaction, so receipts, control mutations and events commit together and
vanish together on rollback.
"""
from __future__ import annotations

import hashlib
import json
import struct
import uuid
from typing import Any

from v8.canonical import canonicalize, escape_dollar_keys
from v8.canonical.keys import canonical_integer_bytes, identity_bytes

# Database-internal completion-event key domain (mirrors
# v_completion_event_key in v8/effect/v8_effect.sql byte-for-byte).
COMPLETION_EVENT_KEY_DOMAIN = b"v8:completion-event-key@db1\x00"


def _text_bytes(value: str) -> bytes:
    if not isinstance(value, str):
        raise TypeError(f"text field must be str, got {type(value).__name__}")
    return value.encode("utf-8")


def _len_prefixed(b: bytes) -> bytes:
    return struct.pack(">Q", len(b)) + b


def completion_event_key(session_id, event_type: str, effect_id,
                         attempt_no: int, payload_hash: str) -> str:
    """Python reference of v_completion_event_key (db-internal tier):
    SHA-256("v8:completion-event-key@db1\\0"
        || len8(session_id) || len8(event_type) || len8(effect_id)
        || canonical_integer_bytes(attempt_no) || len8(payload_hash))."""
    blob = (COMPLETION_EVENT_KEY_DOMAIN
            + _len_prefixed(identity_bytes(session_id))
            + _len_prefixed(_text_bytes(event_type))
            + _len_prefixed(identity_bytes(effect_id))
            + canonical_integer_bytes(attempt_no)
            + _len_prefixed(_text_bytes(payload_hash)))
    return hashlib.sha256(blob).hexdigest()


def _canon(obj: Any) -> tuple[str, str]:
    return canonicalize(escape_dollar_keys(obj))


def _gate_and_run(conn, command_kind: str, canonical_text: str, declared: str,
                  sql: str, params: tuple) -> dict:
    """G3 client pattern: generic gate, then the business function."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT outcome, code, receipt_json, executable"
                " FROM v_command_gate(%s::uuid, %s, %s, %s, %s)",
                (params[0], params[1], command_kind, canonical_text, declared))
            g_outcome, g_code, g_receipt, executable = cur.fetchone()
            if not executable:
                result = {"executable": False, "outcome": g_outcome,
                          "code": g_code, "receipt": g_receipt}
            else:
                cur.execute(sql, params)
                a_outcome, a_code, a_receipt = cur.fetchone()
                result = {"executable": True, "outcome": a_outcome,
                          "code": a_code, "receipt": a_receipt}
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return result


# ---------------------------------------------------------------------------
# Coordination lease CAS (no command_id, no receipt)
# ---------------------------------------------------------------------------

def claim_session(conn, session_id, driver: str, driver_epoch: int = 1,
                  lease_owner: str | None = None, lease_seconds: int = 60,
                  expected_session_fence: int | None = None) -> dict:
    """Claim the coordination lease (lease CAS, not a receipt command).

    ``expected_session_fence`` (optional): when given, the claim also
    compares it against the current session_fence (rejected_stale /
    SESSION_FENCE_STALE on mismatch, zero side effects) — an old-fence CAS
    so a claimer acting on a stale snapshot cannot take a lease that a
    fence bump has superseded. None keeps the legacy unchecked shape.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT v_claim_session(%s::uuid, %s, %s, %s, %s, %s)",
                    (str(session_id), driver, driver_epoch,
                     lease_owner or driver, lease_seconds,
                     expected_session_fence))
        out = cur.fetchone()[0]
    conn.commit()
    return out


def recovery_claim_session(conn, session_id, driver: str, driver_epoch: int = 1,
                           lease_owner: str | None = None,
                           lease_seconds: int = 60) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT v_recovery_claim_session(%s::uuid, %s, %s, %s, %s)",
                    (str(session_id), driver, driver_epoch,
                     lease_owner or driver, lease_seconds))
        out = cur.fetchone()[0]
    conn.commit()
    return out


def yield_session(conn, session_id, driver: str, driver_epoch: int,
                  session_fence: int, lease_owner: str | None = None) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT v_yield_session(%s::uuid, %s, %s, %s, %s)",
                    (str(session_id), driver, driver_epoch, session_fence,
                     lease_owner or driver))
        out = cur.fetchone()[0]
    conn.commit()
    return out


# ---------------------------------------------------------------------------
# prepare_step — initial decision seal
# ---------------------------------------------------------------------------

def prepare_step(
    conn, session_id, command_id: str, driver: str, driver_epoch: int,
    session_fence: int, step_id, turn_id, effect_id=None, *,
    effect_kind: str = "llm", execution_mode: str = "non_streaming",
    retry_class: str = "unsafe", max_attempts: int = 1,
    request_hash: str | None = None, idempotency_key: str | None = None,
    declared_hash: str | None = None,
) -> dict:
    effect_id = str(effect_id or uuid.uuid4())
    request_hash = request_hash or f"llm-req-{command_id}"
    idempotency_key = idempotency_key or f"llm-ik-{command_id}"
    request = {
        "command_kind": "prepare_step",
        "session_id": str(session_id),
        "command_id": command_id,
        "driver": driver,
        "driver_epoch": driver_epoch,
        "session_fence": session_fence,
        "step_id": str(step_id),
        "turn_id": str(turn_id),
        "llm_slot": {
            "effect_id": effect_id,
            "effect_kind": effect_kind,
            "execution_mode": execution_mode,
            "retry_class": retry_class,
            "max_attempts": max_attempts,
            "request_hash": request_hash,
            "idempotency_key": idempotency_key,
        },
    }
    text, computed = _canon(request)
    declared = computed if declared_hash is None else declared_hash
    return _gate_and_run(
        conn, "prepare_step", text, declared,
        "SELECT outcome, code, receipt_json FROM v_prepare_step("
        "%s::uuid, %s, %s, %s, %s, %s::uuid, %s::uuid, %s::uuid,"
        " %s, %s, %s, %s, %s, %s, %s, %s)",
        (str(session_id), command_id, driver, driver_epoch, session_fence,
         str(step_id), str(turn_id), effect_id,
         effect_kind, execution_mode, retry_class, max_attempts,
         request_hash, idempotency_key, declared, text))


# ---------------------------------------------------------------------------
# dispatch_effect — the dispatch gate
# ---------------------------------------------------------------------------

def dispatch_effect(
    conn, session_id, command_id: str, effect_id, driver: str,
    driver_epoch: int, session_fence: int, job_fence: int,
    declared_hash: str | None = None,
) -> dict:
    request = {
        "command_kind": "dispatch_effect",
        "session_id": str(session_id),
        "command_id": command_id,
        "driver": driver,
        "driver_epoch": driver_epoch,
        "session_fence": session_fence,
        "effect_id": str(effect_id),
        "job_fence": job_fence,
    }
    text, computed = _canon(request)
    declared = computed if declared_hash is None else declared_hash
    return _gate_and_run(
        conn, "dispatch_effect", text, declared,
        "SELECT outcome, code, receipt_json FROM v_dispatch_effect("
        "%s::uuid, %s, %s::uuid, %s, %s, %s, %s, %s, %s)",
        (str(session_id), command_id, str(effect_id), driver, driver_epoch,
         session_fence, job_fence, declared, text))


# ---------------------------------------------------------------------------
# complete_effect — terminal settlement (worker completion envelope)
# ---------------------------------------------------------------------------

def build_result_payload(message: Any, tools: list, decision_only: bool,
                         final_tools: bool) -> dict:
    return {"message": message, "tools": tools,
            "decision_only": decision_only, "final_tools": final_tools}


def complete_effect(
    conn, session_id, command_id: str, effect_id, driver: str,
    driver_epoch: int, dispatch_session_fence: int, job_fence: int, *,
    step_id, attempt_no: int = 1,
    request_hash: str, idempotency_key: str,
    outcome: str, message: Any, tools: list, decision_only: bool,
    final_tools: bool, evidence: dict,
    result_payload: dict | None = None,
    schema_version: str = "sv@1", canonicalizer_version: str = "canon@1",
    declared_hash: str | None = None,
) -> dict:
    """Gate + complete + commit in ONE transaction.

    ``step_id`` is the EffectResult ABI step attribution (s32b §5.2): it is
    compared against the settled attempt row's step and a mismatch is
    rejected (STEP_MISMATCH, zero control state).

    ``result_payload`` defaults to build_result_payload(message, tools,
    decision_only, final_tools); tests may override the object (the unknown
    path does not require the decision shape). The normalized tools plan
    canonical text (digest s31b 2.6.1) is derived from ``tools`` through the
    same escape + canonicalize pipeline and travels as its own envelope
    field; SQL validates it against the result payload's tools member and
    persists it with plan_hash over the plan.

    Evidence binding (s32a §3.5): the evidence object must carry the
    (effect_id, attempt_no) of the attempt it attests; SQL classifies an
    unbound or cross-attempt object as 'unknown'. This client fills the two
    fields from the settlement parameters when the caller omits them —
    caller-supplied values are preserved verbatim so a mis-bound submission
    stays visible to the SQL-side guard.
    """
    result_obj = result_payload if result_payload is not None else \
        build_result_payload(message, tools, decision_only, final_tools)
    result_canonical, _ = _canon(result_obj)
    message_canonical, _ = _canon(message)
    plan_canonical, _ = _canon(tools)
    evidence_out = dict(evidence)
    evidence_out.setdefault("effect_id", str(effect_id))
    evidence_out.setdefault("attempt_no", attempt_no)
    request = {
        "command_kind": "complete_effect",
        "session_id": str(session_id),
        "command_id": command_id,
        "effect_id": str(effect_id),
        "attempt_no": attempt_no,
        "step_id": str(step_id),
        "driver": driver,
        "driver_epoch": driver_epoch,
        "dispatch_session_fence": dispatch_session_fence,
        "job_fence": job_fence,
        "request_hash": request_hash,
        "idempotency_key": idempotency_key,
        "outcome": outcome,
        "result": result_obj,
        "evidence": evidence_out,
    }
    text, computed = _canon(request)
    declared = computed if declared_hash is None else declared_hash
    return _gate_and_run(
        conn, "complete_effect", text, declared,
        "SELECT outcome, code, receipt_json FROM v_complete_effect("
        "%s::uuid, %s, %s::uuid, %s, %s::uuid, %s, %s, %s, %s, %s, %s, %s,"
        " %s, %s, %s, %s, %s, %s, %s, %s::jsonb)",
        (str(session_id), command_id, str(effect_id), attempt_no,
         str(step_id), driver, driver_epoch, dispatch_session_fence, job_fence,
         outcome, request_hash, idempotency_key,
         result_canonical, message_canonical, plan_canonical,
         schema_version, canonicalizer_version,
         declared, text, json.dumps(evidence_out, ensure_ascii=False)))


# ---------------------------------------------------------------------------
# finish_session
# ---------------------------------------------------------------------------

def finish_session(
    conn, session_id, command_id: str, driver: str, driver_epoch: int,
    session_fence: int, declared_hash: str | None = None,
) -> dict:
    request = {
        "command_kind": "finish_session",
        "session_id": str(session_id),
        "command_id": command_id,
        "driver": driver,
        "driver_epoch": driver_epoch,
        "session_fence": session_fence,
    }
    text, computed = _canon(request)
    declared = computed if declared_hash is None else declared_hash
    return _gate_and_run(
        conn, "finish_session", text, declared,
        "SELECT outcome, code, receipt_json FROM v_finish_session("
        "%s::uuid, %s, %s, %s, %s, %s, %s)",
        (str(session_id), command_id, driver, driver_epoch, session_fence,
         declared, text))
