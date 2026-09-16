"""G17 Python mirror of the compact digest input layer (D11).

An INDEPENDENT re-implementation of the canonical record encoding and the
two digests over the covered semantic set, used by the gate for the
SQL==Python byte-level cross-check (A75 precedent). The mirror reads the
raw session_events rows and derives the covered set with the same S03
truncation rules; any divergence from the SQL side is a finding, never
silently absorbed.
"""
from __future__ import annotations

import hashlib
import struct
import uuid as uuid_mod

PUBLIC_APPEND = ("user/message", "turn/start", "agent/inject")


def _seg(b: bytes | None) -> bytes:
    b = b or b""
    return struct.pack(">Q", len(b)) + b


def _uuid_raw(value) -> bytes | None:
    if value is None:
        return None
    if isinstance(value, uuid_mod.UUID):
        return value.bytes
    return uuid_mod.UUID(str(value)).bytes


def _sha_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def unknown_set_digest(effect_ids) -> str:
    ids = sorted({_uuid_raw(e) for e in effect_ids if e is not None})
    return _sha_hex(b"".join(_seg(x) for x in ids))


def encode_record(event_class: str, event_type: str, turn_id, step_id,
                  dispatch_ordinal, occurrence: bytes | None,
                  payload_hash: str) -> tuple:
    """Return (six sort-key segments, full record bytes)."""
    k_turn = _seg(_uuid_raw(turn_id))
    k_step = _seg(_uuid_raw(step_id))
    k_ord = _seg(dispatch_ordinal.encode() if dispatch_ordinal is not None
                 else None)
    k_type = _seg(event_type.encode())
    k_occ = _seg(occurrence)
    k_digest = bytes.fromhex(payload_hash)
    record = (_seg(event_class.encode()) + k_type + k_turn + k_step + k_ord
              + k_occ + k_digest)
    return (k_turn, k_step, k_ord, k_type, k_occ, k_digest), record


def covered_elements(events: list[dict]) -> list[dict]:
    """Derive the covered semantic set (S03 truncation semantics).

    ``events`` are raw rows: seq, event_type, event_class, turn_id, step_id,
    effect_id, payload (dict), payload_hash, semantic_input_ordinal.
    """
    import json

    def payload(ev):
        p = ev.get("payload")
        return json.loads(p) if isinstance(p, str) else (p or {})

    out: list[dict] = []
    turn_ids = sorted({ev["turn_id"] for ev in events
                       if ev.get("turn_id") is not None
                       and ev.get("event_type") == "turn/end"
                       and ev.get("event_class") == "semantic"})
    non_end = [ev for ev in events
               if ev.get("event_class") == "semantic"
               and ev.get("event_type") != "turn/end"]
    for ev in non_end:
        p = payload(ev)
        occ = None
        if ev["event_type"] in PUBLIC_APPEND \
                and ev.get("semantic_input_ordinal") is not None:
            occ = _seg(str(ev["semantic_input_ordinal"]).encode())
        elif ev["event_type"] == "tool/call" \
                and "dispatch_ordinal" in p:
            occ = _seg(str(p["dispatch_ordinal"]).encode())
        elif ev["event_type"] == "assistant/message" \
                and ev.get("effect_id") is not None \
                and p.get("closer") is not True:
            occ = _seg(_uuid_raw(ev["effect_id"]))
        out.append({
            "event_type": ev["event_type"],
            "turn_id": ev.get("turn_id"),
            "step_id": ev.get("step_id"),
            "dispatch_ordinal": (str(p["dispatch_ordinal"])
                                 if ev["event_type"] == "tool/call"
                                 and "dispatch_ordinal" in p else None),
            "occurrence": occ,
            "payload_hash": ev["payload_hash"],
        })
    for turn in turn_ids:
        ends = [ev for ev in events if ev.get("turn_id") == turn
                and ev.get("event_class") == "semantic"
                and ev.get("event_type") == "turn/end"]
        closers = [ev for ev in ends if payload(ev).get("closer") is True]
        unknown_attr = {ev.get("effect_id") for ev in ends
                        if payload(ev).get("outcome") == "unknown"}
        chunk_effects = {ev.get("effect_id") for ev in events
                         if ev.get("event_class") == "observational"
                         and ev.get("event_type") == "assistant/chunk"}
        terminal_effects = {ev.get("effect_id") for ev in events
                            if ev.get("event_class") == "semantic"
                            and ev.get("event_type") == "assistant/message"
                            and ev.get("effect_id") is not None}
        superseded = {ev.get("effect_id") for ev in closers}
        partial_only = chunk_effects - terminal_effects
        unresolved = (unknown_attr | partial_only) - superseded
        unresolved.discard(None)
        if unresolved:
            digest = unknown_set_digest(unresolved)
            out.append({
                "event_type": "turn/end", "turn_id": turn, "step_id": None,
                "dispatch_ordinal": None,
                "occurrence": _seg(_uuid_raw(turn))
                              + _seg(digest.encode()),
                "payload_hash": _sha_hex(b'{"outcome":"unknown"}'),
            })
        else:
            known = [ev for ev in ends
                     if payload(ev).get("closer") is True
                     or payload(ev).get("outcome") != "unknown"]
            if not known:
                continue
            pick = max(known, key=lambda e: (
                payload(e).get("closer") is True, e.get("seq", 0)))
            p = payload(pick)
            if p.get("closer") is True:
                res = pick.get("resolution_identity_canonical")
                occ = _seg(_uuid_raw(turn)) + _seg(res)
            else:
                occ = _seg(_uuid_raw(turn))
            out.append({
                "event_type": "turn/end", "turn_id": turn, "step_id": None,
                "dispatch_ordinal": None, "occurrence": occ,
                "payload_hash": pick["payload_hash"],
            })
    return out


def digests(elements: list[dict], session_id) -> tuple[str, str, str]:
    """(logical_cutoff_digest, replacement_set_digest, identity)."""
    recs = [encode_record("semantic", e["event_type"], e["turn_id"],
                          e["step_id"], e["dispatch_ordinal"],
                          e["occurrence"], e["payload_hash"])
            for e in elements]
    by_logical = b"".join(r[1] for r in sorted(
        recs, key=lambda kr: (kr[0][0], kr[0][1], kr[0][2], kr[0][3],
                              kr[0][4], kr[0][5])))
    by_bytes = b"".join(r[1] for r in sorted(recs, key=lambda kr: kr[1]))
    a = _sha_hex(by_logical)
    b = _sha_hex(by_bytes)
    ident = hashlib.sha256(
        b"v8:compact-result@v1\x00"
        + struct.pack(">Q", 16) + _uuid_raw(session_id)
        + bytes.fromhex(a) + bytes.fromhex(b)).hexdigest()
    return a, b, ident
