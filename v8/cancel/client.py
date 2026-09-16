"""v8/cancel/client.py — Python command client for the G8a request_cancel stage.

Same frozen command convention as the earlier stages: the caller builds the
FULL command request object, runs escape_dollar_keys + canonicalize to
obtain the canonical text and hash, and hands the canonical text plus the
DECLARED hash to SQL; SQL recomputes v_sha256_hex and compares. Receipts
and bindings always key on the computed hash. Gate + business function +
commit run in ONE transaction, so the receipt, the sticky latch, the
pre-dispatch dual-table sync, the session collapse and the derived turn/end
event commit together (or vanish together on rollback).

  request_cancel   the sticky stop command (s31a §2.10): the first
                   effective cancel increments cancellation_epoch, syncs
                   every published ready effect to cancelled_before_dispatch
                   (dual-table), collapses the no-active-work session to
                   cancelled/CANCELLED_BY_REQUEST and derives the canonical
                   turn/end (before/after dispatch split). A terminal
                   session returns its original state with the epoch
                   unchanged.
"""
from __future__ import annotations

from v8.effect.client import _canon, _gate_and_run


def request_cancel(
    conn, session_id, command_id: str, driver: str, driver_epoch: int,
    schema_version: str = "sv@1", canonicalizer_version: str = "canon@1",
    declared_hash: str | None = None,
) -> dict:
    """Gate + request_cancel + commit in ONE transaction."""
    request = {
        "command_kind": "request_cancel",
        "session_id": str(session_id),
        "command_id": command_id,
        "driver": driver,
        "driver_epoch": driver_epoch,
        "schema_version": schema_version,
        "canonicalizer_version": canonicalizer_version,
    }
    text, computed = _canon(request)
    declared = computed if declared_hash is None else declared_hash
    return _gate_and_run(
        conn, "request_cancel", text, declared,
        "SELECT outcome, code, receipt_json FROM v_request_cancel("
        "%s::uuid, %s, %s, %s, %s, %s, %s, %s)",
        (str(session_id), command_id, driver, driver_epoch,
         schema_version, canonicalizer_version, declared, text))
