"""v8/retry/client.py — Python command client for the G7 retry stage.

Same frozen command convention as G3/G4/G6: the caller builds the FULL
command request object, runs escape_dollar_keys + canonicalize to obtain
the canonical text and hash, and hands the canonical text plus the DECLARED
hash to SQL; SQL recomputes v_sha256_hex and compares. Receipts and
bindings always key on the computed hash.

  retry_effect       the public retry command (s32b §2.2): batch
                     precondition via the shared virtual aggregation, then
                     the shared batch retry allocation sub-operation
                     (attempt_no+1, identity reuse, superseded marker,
                     one-commit cohort flip to ready).
  recovery_takeover  the G7b recovery command (s32a §2.2 six-step atomic
                     flow): single-transaction takeover of the session's
                     result-less in-flight attempts (job lease guard, CAS
                     fence advance, unknown/known_failure settlement, and
                     the rule-5 cohort allocation through the same shared
                     sub-operation — the second allocation entry).

Every command function runs gate + business function + commit in ONE
transaction, so receipts, control mutations and events commit together and
vanish together on rollback.
"""
from __future__ import annotations

import json

from v8.effect.client import _canon, _gate_and_run


def retry_effect(
    conn, session_id, command_id: str, effect_id, driver: str,
    driver_epoch: int, session_fence: int,
    declared_hash: str | None = None,
) -> dict:
    """Gate + retry_effect + commit in ONE transaction."""
    request = {
        "command_kind": "retry_effect",
        "session_id": str(session_id),
        "command_id": command_id,
        "driver": driver,
        "driver_epoch": driver_epoch,
        "session_fence": session_fence,
        "effect_id": str(effect_id),
    }
    text, computed = _canon(request)
    declared = computed if declared_hash is None else declared_hash
    return _gate_and_run(
        conn, "retry_effect", text, declared,
        "SELECT outcome, code, receipt_json FROM v_retry_effect("
        "%s::uuid, %s, %s::uuid, %s, %s, %s, %s, %s)",
        (str(session_id), command_id, str(effect_id), driver, driver_epoch,
         session_fence, declared, text))


def recovery_takeover(
    conn, session_id, command_id: str, driver: str, driver_epoch: int = 1,
    evidence: dict | None = None, declared_hash: str | None = None,
) -> dict:
    """Gate + recovery_takeover + commit in ONE transaction.

    ``evidence`` maps effect_id -> the evidence object attesting that
    effect's CURRENT in-flight attempt (an attempt with no map entry is a
    result-less takeover and settles unknown_outcome). The client fills
    each entry's effect_id binding from the map key when omitted; the
    attempt_no binding must be carried by the entry itself — a mis-bound
    submission stays visible to the SQL-side classifier (it classifies
    unknown, mirroring the complete_effect convention).
    """
    ev_map: dict = {}
    for k, v in (evidence or {}).items():
        entry = dict(v)
        entry.setdefault("effect_id", str(k))
        ev_map[str(k)] = entry
    request = {
        "command_kind": "recovery_takeover",
        "session_id": str(session_id),
        "command_id": command_id,
        "driver": driver,
        "driver_epoch": driver_epoch,
        "evidence": ev_map,
    }
    text, computed = _canon(request)
    declared = computed if declared_hash is None else declared_hash
    return _gate_and_run(
        conn, "recovery_takeover", text, declared,
        "SELECT outcome, code, receipt_json FROM v_recovery_takeover("
        "%s::uuid, %s, %s, %s, %s::jsonb, %s, %s)",
        (str(session_id), command_id, driver, driver_epoch,
         json.dumps(ev_map, ensure_ascii=False), declared, text))
