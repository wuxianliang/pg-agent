"""v8/tools/client.py — Python command client for the G6 tools seal.

Same frozen command convention as G3/G4: the caller builds the FULL command
request object (command kind, target identity, expected values, complete
business payload), runs escape_dollar_keys + canonicalize to obtain the
canonical text and hash, and hands the canonical text plus the DECLARED
hash to SQL; SQL recomputes v_sha256_hex and compares. Receipts and
bindings always key on the computed hash.

  seal_batch         the tools seal (digest s31b 2.6.2 four steps): CAS
                     ready/stage=decision + expected sealed_batch_no,
                     decision result identity verification, plan_hash
                     recomputation from the persisted plan, one-transaction
                     batch + tool effects + first attempts + tool/call
                     events, publish-as-ready, aggregation waiting_effect.
  complete_tool_effect  the tool-result completion path of the shared
                     v_complete_effect (batch kind='tools' arm): settles
                     effect+attempt succeeded, SQL-generates the
                     tool/result semantic event, aggregates per rule 6's
                     final_tools arm.

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

from v8.canonical.keys import canonical_integer_bytes, identity_bytes
from v8.effect.client import _canon, _gate_and_run

# Database-internal seal-event key domain (mirrors v_seal_event_key in
# v8/tools/v8_tools.sql byte-for-byte).
SEAL_EVENT_KEY_DOMAIN = b"v8:seal-event-key@db1\x00"


def _text_bytes(value: str) -> bytes:
    if not isinstance(value, str):
        raise TypeError(f"text field must be str, got {type(value).__name__}")
    return value.encode("utf-8")


def _len_prefixed(b: bytes) -> bytes:
    return struct.pack(">Q", len(b)) + b


def seal_event_key(session_id, event_type: str, batch_id,
                   dispatch_ordinal: int, payload_hash: str) -> str:
    """Python reference of v_seal_event_key (slot-level occurrence identity
    (batch_id, dispatch_ordinal); SHA-256("v8:seal-event-key@db1\\0"
        || len8(session_id) || len8(event_type) || len8(batch_id)
        || canonical_integer_bytes(dispatch_ordinal)
        || len8(payload_hash))."""
    blob = (SEAL_EVENT_KEY_DOMAIN
            + _len_prefixed(identity_bytes(session_id))
            + _len_prefixed(_text_bytes(event_type))
            + _len_prefixed(identity_bytes(batch_id))
            + canonical_integer_bytes(dispatch_ordinal)
            + _len_prefixed(_text_bytes(payload_hash)))
    return hashlib.sha256(blob).hexdigest()


def tool_call_payload(tool_call_id: str, tool: str, arguments: Any) -> dict:
    """The tool/call event payload object (carries the slot attribution)."""
    return {"tool_call_id": tool_call_id, "tool": tool, "arguments": arguments}


def build_tool_slots(plan: list, *, retry_class: str = "unsafe",
                     max_attempts: int = 1) -> list[dict]:
    """Build the seal manifest from a persisted normalized tools plan.

    dispatch_ordinal is the array position (frozen); request_hash /
    idempotency_key are derived deterministically from the canonical slot
    payload so chaos reruns reproduce identical slot identity.
    """
    slots: list[dict] = []
    for call in plan:
        payload = tool_call_payload(call["tool_call_id"], call["tool"],
                                    call.get("arguments"))
        payload_canonical, _ = _canon(payload)
        digest = hashlib.sha256(payload_canonical.encode("utf-8")).hexdigest()
        slots.append({
            "effect_id": str(uuid.uuid4()),
            "tool_call_id": call["tool_call_id"],
            "tool": call["tool"],
            "arguments": call.get("arguments"),
            "payload_canonical": payload_canonical,
            "execution_mode": "non_streaming",
            "retry_class": retry_class,
            "max_attempts": max_attempts,
            "request_hash": f"tool-req-{digest[:40]}",
            "idempotency_key": f"tool-ik-{digest[:40]}",
        })
    return slots


# ---------------------------------------------------------------------------
# seal_batch — the tools seal (second seal path)
# ---------------------------------------------------------------------------

def seal_batch(
    conn, session_id, command_id: str, driver: str, driver_epoch: int,
    session_fence: int, step_id, expected_sealed_batch_no: int,
    decision: dict, plan_hash: str, slots: list,
    schema_version: str = "sv@1", canonicalizer_version: str = "canon@1",
    declared_hash: str | None = None,
) -> dict:
    """Gate + tools seal + commit in ONE transaction.

    ``decision`` carries the accepted decision result identity to verify:
    {"effect_id", "attempt_no", "result_hash", "event_key"} (the event_key
    of the SQL-generated assistant/message event). ``slots`` is the ordered
    manifest (see build_tool_slots); the array position is the frozen
    dispatch_ordinal.
    """
    request = {
        "command_kind": "seal_batch",
        "session_id": str(session_id),
        "command_id": command_id,
        "driver": driver,
        "driver_epoch": driver_epoch,
        "session_fence": session_fence,
        "step_id": str(step_id),
        "expected_sealed_batch_no": expected_sealed_batch_no,
        "decision": {
            "effect_id": str(decision["effect_id"]),
            "attempt_no": decision["attempt_no"],
            "result_hash": decision["result_hash"],
            "event_key": decision["event_key"],
        },
        "plan_hash": plan_hash,
        "schema_version": schema_version,
        "canonicalizer_version": canonicalizer_version,
        "slots": slots,
    }
    text, computed = _canon(request)
    declared = computed if declared_hash is None else declared_hash
    return _gate_and_run(
        conn, "seal_batch", text, declared,
        "SELECT outcome, code, receipt_json FROM v_seal_batch("
        "%s::uuid, %s, %s, %s, %s, %s::uuid, %s, %s::uuid, %s, %s, %s, %s,"
        " %s, %s, %s, %s, %s::jsonb)",
        (str(session_id), command_id, driver, driver_epoch, session_fence,
         str(step_id), expected_sealed_batch_no,
         str(decision["effect_id"]), decision["attempt_no"],
         decision["result_hash"], decision["event_key"], plan_hash,
         schema_version, canonicalizer_version,
         declared, text, json.dumps(slots, ensure_ascii=False)))


# ---------------------------------------------------------------------------
# complete_tool_effect — tool-result terminal settlement
# ---------------------------------------------------------------------------

def complete_tool_effect(
    conn, session_id, command_id: str, effect_id, driver: str,
    driver_epoch: int, dispatch_session_fence: int, job_fence: int, *,
    step_id, attempt_no: int = 1,
    request_hash: str, idempotency_key: str,
    outcome: str, tool_call_id: str, output: Any, evidence: dict,
    schema_version: str = "sv@1", canonicalizer_version: str = "canon@1",
    declared_hash: str | None = None,
) -> dict:
    """Gate + tool completion + commit in ONE transaction.

    ``step_id`` is the EffectResult ABI step attribution (compared against
    the settled attempt row). The result payload is the tool result object
    {"tool_call_id", "output"}; SQL validates the tool_call_id against the
    sealed slot, settles by the derived classification and SQL-generates
    the tool/result semantic event (workers MUST NOT attach events).
    Evidence binding follows the G4 contract: this client fills
    effect_id/attempt_no when the caller omits them.
    """
    result_obj = {"tool_call_id": tool_call_id, "output": output}
    result_canonical, _ = _canon(result_obj)
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
         result_canonical, result_canonical, "[]",
         schema_version, canonicalizer_version,
         declared, text, json.dumps(evidence_out, ensure_ascii=False)))
