"""v8/repair/client.py — Python command client for the G7c repair stage.

Same frozen command convention as the earlier stages: the caller builds the
FULL command request object, runs escape_dollar_keys + canonicalize to
obtain the canonical text and hash, and hands the canonical text plus the
DECLARED hash to SQL; SQL recomputes v_sha256_hex and compares. Receipts
and bindings always key on the computed hash. Gate + business function +
commit run in ONE transaction, so receipts, control mutations and events
commit together and vanish together on rollback.

  repair   the unique exit for unknown_outcome (s32b §2.7): the envelope
           carries the target effect/attempt, the structured resolution
           identity object (canonical bytes produced here), the caller's
           view of the supersedes chain head, the evidence object, and —
           for a success resolution — the result payload in the same shape
           as the completion path. The closer event type/payload are
           DERIVED here from the resolution kind and the slot family (LLM ->
           assistant/message-class, tool -> tool/result-class,
           failure/cancellation -> turn/end-class) and validated SQL-side.

Evidence binding follows the completion convention: this client fills the
evidence object's effect_id/attempt_no from the target when omitted;
caller-supplied values are preserved verbatim so a mis-bound submission
stays visible to the SQL-side guard (REPAIR_EVIDENCE_REQUIRED).
"""
from __future__ import annotations

import json
from typing import Any

from v8.effect.client import _canon, _gate_and_run, build_result_payload


def repair(
    conn, session_id, command_id: str, effect_id, attempt_no: int, *,
    driver: str, driver_epoch: int,
    supersedes_event_key: str,
    evidence: dict,
    resolution_kind: str,
    code: str | None = None,
    message: Any = None, tools: list | None = None,
    decision_only: bool | None = None, final_tools: bool | None = None,
    tool_call_id: str | None = None, output: Any = None,
    result: dict | None = None,
    schema_version: str = "sv@1", canonicalizer_version: str = "canon@1",
    declared_hash: str | None = None,
    resolution: dict | None = None,
    closer_event_type: str | None = None,
    closer_payload: dict | None = None,
) -> dict:
    """Gate + repair + commit in ONE transaction.

    ``resolution_kind`` is one of 'succeeded' | 'failed_terminal' |
    'cancelled_after_dispatch'. ``code`` defaults: 'SUCCEEDED' for success;
    for cancellation derived from the evidence shape (a provider receipt ->
    CANCELLED_BY_PROVIDER, a no-side-effect proof alone ->
    CANCELLED_BY_REQUEST_AFTER_DISPATCH); for failure it is the provider
    failure code kept verbatim (default 'REPAIR_FAILED').

    ``resolution`` / ``closer_event_type`` / ``closer_payload`` are escape
    hatches for the negative tests (SQL re-validates every derived value);
    production callers never pass them.
    """
    evidence_out = dict(evidence)
    evidence_out.setdefault("effect_id", str(effect_id))
    evidence_out.setdefault("attempt_no", attempt_no)

    if code is None:
        if resolution_kind == "succeeded":
            code = "SUCCEEDED"
        elif resolution_kind == "cancelled_after_dispatch":
            code = ("CANCELLED_BY_PROVIDER"
                    if evidence_out.get("provider_receipt")
                    else "CANCELLED_BY_REQUEST_AFTER_DISPATCH")
        else:
            code = "REPAIR_FAILED"

    if resolution is None:
        resolution = {
            "attempt_no": attempt_no,
            "code": code,
            "effect_id": str(effect_id),
            "resolution": resolution_kind,
        }
    resolution_text, _ = _canon(resolution)

    if resolution_kind == "succeeded":
        derived_type = "tool/result" if tool_call_id is not None \
            else "assistant/message"
    else:
        derived_type = "turn/end"
    if closer_event_type is None:
        closer_event_type = derived_type

    if closer_payload is None:
        base = {
            "closer": True,
            "resolution": resolution,
            "supersedes_event_key": supersedes_event_key,
        }
        if resolution_kind == "succeeded":
            if tool_call_id is not None:
                closer_payload = {**base, "tool_call_id": tool_call_id,
                                  "output": output}
            else:
                closer_payload = {**base, "message": message}
        elif resolution_kind == "failed_terminal":
            closer_payload = {**base, "interrupted": True, "reason": "failed"}
        else:
            reason = ("cancelled_by_provider"
                      if code == "CANCELLED_BY_PROVIDER"
                      else "cancelled_by_request_after_dispatch")
            closer_payload = {**base, "interrupted": True, "reason": reason}
    closer_text, _ = _canon(closer_payload)

    if result is None:
        if resolution_kind == "succeeded":
            if tool_call_id is not None:
                result = {"tool_call_id": tool_call_id, "output": output}
            else:
                result = build_result_payload(
                    message, tools if tools is not None else [],
                    bool(decision_only), bool(final_tools))
        else:
            result = {"repair": {"evidence_class": evidence_out.get("class"),
                                 "code": code}}
    result_text, _ = _canon(result)
    plan_text = None
    if resolution_kind == "succeeded" and tool_call_id is None \
            and tools is not None:
        plan_text, _ = _canon(tools)

    request = {
        "command_kind": "repair",
        "session_id": str(session_id),
        "command_id": command_id,
        "driver": driver,
        "driver_epoch": driver_epoch,
        "effect_id": str(effect_id),
        "attempt_no": attempt_no,
        "resolution": resolution,
        "supersedes_event_key": supersedes_event_key,
        "closer_event_type": closer_event_type,
        "closer_payload": closer_payload,
        "result": result,
        "plan": tools if plan_text is not None else None,
        "evidence": evidence_out,
    }
    text, computed = _canon(request)
    declared = computed if declared_hash is None else declared_hash
    return _gate_and_run(
        conn, "repair", text, declared,
        "SELECT outcome, code, receipt_json FROM v_repair("
        "%s::uuid, %s, %s, %s, %s::uuid, %s, %s, %s, %s, %s, %s, %s,"
        " %s::jsonb, %s, %s, %s, %s)",
        (str(session_id), command_id, driver, driver_epoch,
         str(effect_id), attempt_no, resolution_text, supersedes_event_key,
         closer_event_type, closer_text, result_text, plan_text,
         json.dumps(evidence_out, ensure_ascii=False),
         schema_version, canonicalizer_version, declared, text))
