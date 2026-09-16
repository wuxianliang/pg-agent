"""v8/events/client.py — Python command client for the public append_events path.

Command convention (frozen, shared with G1/G2): the caller builds the FULL
command request object — command kind, target identity, expected values and
the complete business payload — runs it through escape_dollar_keys +
canonicalize to obtain the canonical text and hash, and hands the canonical
text plus the DECLARED hash to SQL; SQL recomputes v_sha256_hex over the
canonical text and compares (REQUEST_HASH_MISMATCH semantics). Receipts and
bindings always key on the computed hash.

Per-entry payloads follow the same pipeline individually: each entry's
payload object is escaped + canonicalized on this side and travels inside the
entry as ``payload_canonical`` (the JCS text); SQL re-hashes it with
v_sha256_hex for the event row and the derived event keys.

Transaction boundary: ``call_append_events`` runs gate + append + commit in a
single transaction, so receipts, control mutations (next_seq) and events
commit together and disappear together on rollback.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from v8.canonical import canonicalize, escape_dollar_keys

SEMANTIC_EVENT_TYPES = frozenset({"user/message", "turn/start", "agent/inject"})
OBSERVATIONAL_EVENT_TYPES = frozenset({"assistant/chunk", "session/heartbeat"})

# Beyond the safe-integer range integers MUST use the tagged $int encoding
# (canonical profile section 1.3); within it they MUST be JSON numbers.
_SAFE_INTEGER_LIMIT = 9007199254740991  # 2^53 - 1


def _int_field(name: str, n: int | None) -> int | dict | None:
    if n is None:
        return None
    if isinstance(n, bool) or not isinstance(n, int):
        raise TypeError(f"{name} must be an int, got {type(n).__name__}")
    if -_SAFE_INTEGER_LIMIT <= n <= _SAFE_INTEGER_LIMIT:
        return n
    return {"$int": str(n)}


def canonical_payload(payload_obj: Any) -> tuple[str, str]:
    """Escape + canonicalize one event payload object -> (text, hash)."""
    return canonicalize(escape_dollar_keys(payload_obj))


def build_entry(
    event_type: str,
    payload: Any,
    *,
    schema_version: str,
    canonicalizer_version: str,
    turn_id: str | uuid.UUID | None = None,
    step_id: str | uuid.UUID | None = None,
    effect_id: str | uuid.UUID | None = None,
    semantic_input_ordinal: int | None = None,
    attempt_no: int | None = None,
    stream_id: str | None = None,
    chunk_index: int | None = None,
) -> dict:
    """Build one append_events entry envelope.

    The attribution triple is declared explicitly (None -> JSON null: NULL is
    a value, not a missing field, per W03). Semantic entries must carry
    turn_id and a semantic_input_ordinal; assistant/chunk entries carry the
    four-tuple identity (effect_id/attempt_no/stream_id/chunk_index);
    session/heartbeat entries carry no attribution.
    """
    if event_type not in SEMANTIC_EVENT_TYPES | OBSERVATIONAL_EVENT_TYPES:
        raise ValueError(f"event_type {event_type!r} is not a public append type")
    payload_canonical, payload_hash = canonical_payload(payload)
    entry: dict[str, Any] = {
        "event_type": event_type,
        "schema_version": schema_version,
        "canonicalizer_version": canonicalizer_version,
        "payload_canonical": payload_canonical,
        "payload_hash": payload_hash,
    }
    if event_type in SEMANTIC_EVENT_TYPES:
        entry["turn_id"] = str(turn_id)
        entry["step_id"] = None if step_id is None else str(step_id)
        entry["effect_id"] = None if effect_id is None else str(effect_id)
        entry["semantic_input_ordinal"] = _int_field(
            "semantic_input_ordinal", semantic_input_ordinal)
    elif event_type == "assistant/chunk":
        entry["effect_id"] = str(effect_id)
        entry["attempt_no"] = _int_field("attempt_no", attempt_no)
        entry["stream_id"] = stream_id
        entry["chunk_index"] = _int_field("chunk_index", chunk_index)
    else:  # session/heartbeat
        entry["turn_id"] = None
        entry["step_id"] = None
        entry["effect_id"] = None
    return entry


def build_request(
    command_kind: str,
    session_id: str | uuid.UUID,
    command_id: str,
    driver: str,
    driver_epoch: int,
    expected_seq: int,
    entries: list[dict],
) -> tuple[str, str]:
    """Build the full canonical command request -> (canonical_text, hash).

    The request object covers command kind, target identity, the expected seq
    and the complete payload (entries with their canonical payload texts),
    matching the frozen command_request_hash input definition.
    """
    request = {
        "command_kind": command_kind,
        "session_id": str(session_id),
        "command_id": command_id,
        "driver": driver,
        "driver_epoch": driver_epoch,
        "expected_seq": expected_seq,
        "entries": entries,
    }
    return canonicalize(escape_dollar_keys(request))


def create_session(conn, session_id: str | uuid.UUID, driver: str) -> bool:
    """Controlled P0B bootstrap of a session row (idempotent)."""
    with conn.cursor() as cur:
        cur.execute("SELECT v_create_session(%s::uuid, %s)", (str(session_id), driver))
        created = cur.fetchone()[0]
    conn.commit()
    return bool(created)


def call_command_gate(
    conn,
    session_id: str | uuid.UUID,
    command_id: str,
    command_kind: str,
    payload_canonical: str,
    declared_hash: str,
) -> dict:
    """Run the generic receipt/binding gate alone (commits its own writes)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT outcome, code, receipt_json, executable FROM v_command_gate("
            "%s::uuid, %s, %s, %s, %s)",
            (str(session_id), command_id, command_kind,
             payload_canonical, declared_hash),
        )
        outcome, code, receipt_json, executable = cur.fetchone()
    conn.commit()
    return {
        "executable": bool(executable),
        "outcome": outcome,
        "code": code,
        "receipt": receipt_json,
    }


def call_append_events(
    conn,
    session_id: str | uuid.UUID,
    command_id: str,
    driver: str,
    driver_epoch: int,
    expected_seq: int,
    entries: list[dict],
    declared_hash: str | None = None,
) -> dict:
    """Gate + append + commit in ONE transaction; returns the structured result.

    ``declared_hash`` defaults to the correctly computed hash; tests may
    override it to exercise the REQUEST_HASH_MISMATCH path.
    """
    session_id = str(session_id)
    canonical_text, computed = build_request(
        "append_events", session_id, command_id, driver, driver_epoch,
        expected_seq, entries)
    declared = computed if declared_hash is None else declared_hash
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT outcome, code, receipt_json, executable"
                " FROM v_command_gate(%s::uuid, %s, %s, %s, %s)",
                (session_id, command_id, "append_events",
                 canonical_text, declared))
            g_outcome, g_code, g_receipt, executable = cur.fetchone()
            if not executable:
                result = {
                    "executable": False,
                    "outcome": g_outcome,
                    "code": g_code,
                    "receipt": g_receipt,
                }
            else:
                cur.execute(
                    "SELECT outcome, code, receipt_json FROM v_append_events("
                    "%s::uuid, %s, %s, %s, %s, %s, %s, %s)",
                    (session_id, command_id, driver, driver_epoch,
                     expected_seq, declared, canonical_text,
                     _entries_json(entries)))
                a_outcome, a_code, a_receipt = cur.fetchone()
                result = {
                    "executable": True,
                    "outcome": a_outcome,
                    "code": a_code,
                    "receipt": a_receipt,
                }
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return result


def _entries_json(entries: list[dict]) -> str:
    return json.dumps(entries, ensure_ascii=False, separators=(",", ":"))
