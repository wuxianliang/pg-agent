"""v8/stream/observation.py — G9b canonicalizer-side flow engine.

Frozen contract:
  * docs/designs/v8-dev.md section 1.2 (流完整性屏障, line 53) — the (a)/(b)/
    (c)/(d) equivalence lifecycle, the merge rules and the two-layer portable
    verifier input;
  * digest s32b-effect-ledger.md section 3.2 — the counting ABI grammar
    (0)/(1)-(7), the F4 extra-index criterion, the stream_progress five-state
    gate and the observation receipt contract (Q04);
  * digest s32c-completion-evidence.md — S04 observation payload layering.

The engine is the deterministic Python mirror of the SQL judgments
(v_stream_flow_indices / v_stream_equivalence in v8/stream/v8_stream.sql):
both consume ONLY the accepted assistant/chunk events (the unified controlled
extraction), both decide the collection criterion by exact set equality and
both apply F4 before any equivalence assertion. It exists so the canonicalizer
side can assert the frozen formulas without a round trip and so the two-layer
portable verifier has a single entry point.
"""
from __future__ import annotations

import json
from typing import Any

from v8.events.canonicalizer import (
    CANONICALIZER_CONFLICT,
    CanonicalizerError,
    _merge_chunks,
    normalize,
)

# ---------------------------------------------------------------------------
# closed code / reason vocabulary (frozen by s32b section 3.2)
# ---------------------------------------------------------------------------

# The five-state gate (first hit stops) — outcomes + codes.
GATE_SESSION_TERMINAL = ("rejected_mismatch", "SESSION_TERMINAL")
GATE_SUPERSEDED = ("rejected_stale", "ATTEMPT_SUPERSEDED")
GATE_STREAM_CLOSED = ("rejected_mismatch", "STREAM_CLOSED")
GATE_REPAIR_REQUIRED = ("repair_required", "REPAIR_REQUIRED")
GATE_ACCEPT = ("accepted", None)

# The reconcile entry sees an (iii)/(iv) form: fixed rejection (reconcile is
# not implemented in this stage — structural note, Y01).
OBSERVATION_WRONG_ENTRY = "OBSERVATION_WRONG_ENTRY"

# Window exhaustion records a REASON value, never a new closed code (grammar
# (7)).
STREAM_INCOMPLETE = "STREAM_INCOMPLETE"

# flow_state statuses
NO_FACT = "no_fact"
PENDING = "pending"
COMPLETE = "complete"
CONFLICT_EXTRA_INDEX = "conflict_extra_index"


def target_end(final_chunk_index: int | None,
               chunk_count: int | None) -> int | None:
    """The certified end index of the stream.

    Two equivalent representations — final_chunk_index = N, or
    chunk_count = C with end = C-1 (the C = N+1 coexistence is validated
    upstream as a structural reject, so the engine only ever sees a legal
    pair). Both representations yield the same {0..end} target set.
    """
    if final_chunk_index is not None:
        return final_chunk_index
    if chunk_count is not None:
        return chunk_count - 1
    return None


def flow_state(events: list[dict], effect_id, attempt_no,
               *, final_chunk_index: int | None = None,
               chunk_count: int | None = None) -> dict:
    """The counting ABI grammar (1)-(3) + F4, over the accepted chunk set.

    Returns {status, conflict, merged_text, indices, end}:
      * ``no_fact``               — neither count present;
      * ``conflict_extra_index``  — an accepted index outside the certified
                                    end range (F4): a conflict fact, recorded
                                    WITHOUT running any equivalence check;
      * ``pending``               — the accepted set is a proper subset of
                                    {0..end} (a missing index);
      * ``complete``              — the accepted set is EXACTLY {0..end}.

    The set equality is decided by (count, min, max) over the distinct
    accepted indices — distinctness is structural (one row per four-tuple),
    an index set is a set, and the exact-equality test never materialises
    {0..end} (N may be up to 2^63-2).
    """
    entry = _merge_chunks(events).get((effect_id, attempt_no))
    indices = entry["indices"] if entry else []
    merged_text = entry["text"] if entry else ""
    out = {"merged_text": merged_text, "indices": indices, "conflict": False,
           "end": None}
    end = target_end(final_chunk_index, chunk_count)
    if end is None:
        return {**out, "status": NO_FACT}
    out["end"] = end
    if indices and indices[-1] > end:
        return {**out, "status": CONFLICT_EXTRA_INDEX, "conflict": True}
    exact = (len(indices) == end + 1 and indices[0] == 0 and indices[-1] == end)
    return {**out, "status": COMPLETE if exact else PENDING}


def equivalence(events: list[dict], effect_id, attempt_no, final_text,
                *, final_chunk_index: int | None = None,
                chunk_count: int | None = None) -> dict:
    """The (a)/(b)/(c)/(d) equivalence lifecycle.

    Returns the flow_state dict plus a ``verification`` field:
      * ``conflict_extra_index`` — F4 hit; the equivalence assertion is NOT
                                   executed (must not be derived from it);
      * ``pending``              — the flow is not confirmed complete, or the
                                   final text has not arrived: the assertion
                                   stays pending and MUST NOT judge a conflict;
      * ``ok``                   — complete AND merged text == final text;
      * ``conflict_equivalence`` — complete AND merged text != final text
                                   (CANONICALIZER_CONFLICT).
    """
    st = flow_state(events, effect_id, attempt_no,
                    final_chunk_index=final_chunk_index,
                    chunk_count=chunk_count)
    if st["status"] == CONFLICT_EXTRA_INDEX:
        return {**st, "verification": "conflict_skipped"}
    if st["status"] != COMPLETE:
        return {**st, "verification": "pending"}
    if final_text is None:
        return {**st, "verification": "pending"}
    if st["merged_text"] == final_text:
        return {**st, "verification": "ok", "conflict": False}
    return {**st, "verification": "conflict_equivalence", "conflict": True}


def three_representations_agree(events: list[dict], effect_id, attempt_no,
                                *, final_chunk_index: int | None = None,
                                chunk_count: int | None = None) -> bool:
    """Only-N / only-C / coexistence must decide the SAME flow status."""
    canon = flow_state(events, effect_id, attempt_no,
                       final_chunk_index=final_chunk_index,
                       chunk_count=chunk_count)["status"]
    if final_chunk_index is not None:
        only_n = flow_state(events, effect_id, attempt_no,
                            final_chunk_index=final_chunk_index)["status"]
        if only_n != canon:
            return False
    if chunk_count is not None:
        only_c = flow_state(events, effect_id, attempt_no,
                            chunk_count=chunk_count)["status"]
        if only_c != canon:
            return False
    return True


def partial_text(events: list[dict], effect_id, attempt_no) -> str | None:
    """The assistant/partial prefix source: the accepted chunk events alone
    (S04 clause 3 — observations never contribute). None when no prefix."""
    entry = _merge_chunks(events).get((effect_id, attempt_no))
    if entry is None or not entry["text"]:
        return None
    return entry["text"]


def partial_events(trace: list[dict]) -> list[dict]:
    return [e for e in trace if e["event_type"] == "assistant/partial"]


def portable_verify(events: list[dict], *, conflict_fact: bool,
                    canonicalizer_version: str = "canon@1") -> dict:
    """The frozen two-layer portable verifier.

    Input = normalize(session_events) + "this session has a persisted
    chunk-conflict fact" (either shape: the append-layer CANONICALIZER_CONFLICT
    rejection receipt/audit, or the canonicalizer-side equivalence/extra-index
    conflict audit mark). normalize still passes; the verifier's boolean is
    driven by the conflict fact — any fact means portable comparison fails.
    """
    trace = normalize(events, canonicalizer_version)
    return {"trace": trace, "conflict_fact": bool(conflict_fact),
            "passed": not bool(conflict_fact)}


# ---------------------------------------------------------------------------
# persistence helpers (thin wrappers over the SQL sub-operations)
# ---------------------------------------------------------------------------

def conflict_fact(conn, session_id, effect_id, attempt_no, scope: str,
                  fingerprint: str) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT v_stream_conflict_fact(%s::uuid, %s::uuid, %s, %s, %s)",
                    (str(session_id), str(effect_id), attempt_no, scope,
                     fingerprint))
    conn.commit()


def incomplete_fact(conn, session_id, effect_id, attempt_no,
                    fingerprint: str) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT v_stream_incomplete_fact(%s::uuid, %s::uuid, %s, %s)",
                    (str(session_id), str(effect_id), attempt_no, fingerprint))
    conn.commit()


def session_conflict_fact(conn, session_id) -> bool:
    """Persisted chunk-conflict fact (either shape) for the session."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM command_receipts"
            "   WHERE session_id=%s AND code='CANONICALIZER_CONFLICT')"
            "  OR EXISTS (SELECT 1 FROM effect_audit"
            "   WHERE session_id=%s AND reason='CANONICALIZER_CONFLICT')",
            (str(session_id), str(session_id)))
        return bool(cur.fetchone()[0])


def session_stream_incomplete(conn, session_id) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM effect_audit"
            "   WHERE session_id=%s AND reason='STREAM_INCOMPLETE')",
            (str(session_id),))
        return bool(cur.fetchone()[0])


def db_equivalence(conn, session_id, effect_id, attempt_no,
                   final_chunk_index, chunk_count, final_text) -> dict:
    """Run the SQL equivalence judgment (records the conflict fact on a
    mismatch / F4 hit). Read-only for control state."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT v_stream_equivalence(%s::uuid, %s::uuid, %s, %s, %s, %s)",
            (str(session_id), str(effect_id), attempt_no, final_chunk_index,
             chunk_count, final_text))
        out = cur.fetchone()[0]
    conn.commit()
    return out


def load_stream_events(conn, session_id) -> list[dict]:
    """normalize()-shaped events read back from session_events, including the
    stream four-tuple columns (the flow engine's input)."""
    import json as _json
    with conn.cursor() as cur:
        cur.execute(
            "SELECT event_type, payload, turn_id, step_id, effect_id,"
            " event_key, attempt_no, stream_id, chunk_index, seq"
            " FROM session_events WHERE session_id=%s ORDER BY seq",
            (str(session_id),))
        rows = cur.fetchall()
    out = []
    for et, payload, turn, step, eff, key, att, sid, cidx, seq in rows:
        d = {"event_type": et, "payload": _json.loads(payload),
             "turn_id": str(turn) if turn is not None else None,
             "step_id": str(step) if step is not None else None,
             "effect_id": str(eff) if eff is not None else None,
             "event_key": key, "attempt_no": att, "stream_id": sid,
             "chunk_index": cidx, "seq": seq}
        out.append(d)
    return out


def accepted_events(conn, session_id) -> list[dict]:
    """The canonicalizer input domain (accepted chunk events only) — the
    engine + verifier consume exactly this (S04 clause 2)."""
    return [e for e in load_stream_events(conn, session_id)
            if e["event_type"] == "assistant/chunk"]
