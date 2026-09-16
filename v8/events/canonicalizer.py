"""v8/events/canonicalizer.py — normalize() and the unique turn-finalization
reducer (spec section 1.2, reducer paragraph at v8-dev.md line 71).

normalize(events, canonicalizer_version) -> observable_trace must produce a
UNIQUE output per input; uncovered raw combinations fail closed
(CANONICALIZER_UNSUPPORTED), never guess.

P0B input subset (documented input contract for this stage; later stages
extend, never silently reinterpret):

  event_type in {user/message, turn/start, agent/inject,          (semantic)
                 assistant/message, tool/call, tool/result,       (semantic)
                 turn/end,                                        (reducer slot)
                 assistant/chunk, session/heartbeat}              (observational)

Every input event is a dict with:
  event_type : str (required)
  payload    : dict (required)
  turn_id / step_id / effect_id : str | None (attribution)
  dispatch_ordinal  : int | None (semantic sort key component)
  semantic_input_ordinal : int | None (public input sort key component)
  effect_status : one of 'pending', 'failed_retryable', 'dispatch_started',
                  'succeeded', 'failed_terminal', 'cancelled_before_dispatch',
                  'cancelled_after_dispatch', 'unknown_outcome' | None
                  (effect-level terminal/pending signal carried by whichever
                  event represents that effect's state)
  code            : str | None (e.g. CANCELLED_BY_PROVIDER,
                   CANCELLED_BY_REQUEST_AFTER_DISPATCH, ABORTED_BEFORE_DISPATCH,
                   UNKNOWN_AFTER_DISPATCH)
  decision_only   : bool | None (the closing-decision marker, spec 2.6.1)
  sticky_cancel   : bool (sticky stop-latch signal for the turn)
  unsealed_tools_plan : bool (turn has an unsealed tools plan — guard input)

Input turn/end events are CANDIDATES/signals consumed by the reducer; the
reducer alone emits the canonical turn/end (at most one per turn, any path
bypassing it is a defect). Output events carry event_class tags; semantic
content sorts by turn/step/dispatch_ordinal (never wall-clock); chunks merge
by the frozen four-tuple key order.

G7c closer consumption (spec section 1.2 lines 66/69/71, the "canonical
slot + supersedes chain" recomputation): a repair closer is any input event
whose payload carries "closer": true plus the frozen metadata triple
  resolution           {"effect_id", "attempt_no", "resolution", "code"}
                        (resolution in the closed set succeeded /
                         failed_terminal / cancelled_after_dispatch)
  supersedes_event_key the chain predecessor (the provisional end or the
                        previous chain head)
and the event dict carries its event_key. A closer SUPERSEDES its effect's
provisional unknown representation in the output projection (the input
events never change — the projection replaces, history only appends): the
effect's status/code resolve from the closer's resolution identity, and the
provisional unknown marker no longer appears for it. While any unknown of
the turn remains unrepaired the reducer keeps emitting the ONE provisional
turn/end {outcome:unknown} and portable comparison stays
blocked_unknown_effect; once every unknown is repaired the unique known end
is recomputed from the remaining terminal candidates. A closer superseded
inside the SAME effect's lineage (a later closer of the same effect) is
eliminated from the trace; chain-intermediate closers of OTHER effects of
the turn keep their per-effect semantic role (the slot supersedes chain is
a slot-level lineage, never an erasure of a sibling effect's result).
"""
from __future__ import annotations

from typing import Any

CANONICALIZER_UNSUPPORTED = "CANONICALIZER_UNSUPPORTED"
CANONICALIZER_CONFLICT = "CANONICALIZER_CONFLICT"

SEMANTIC_TYPES = frozenset({
    "user/message", "turn/start", "agent/inject",
    "assistant/message", "tool/call", "tool/result",
})
OBSERVATIONAL_TYPES = frozenset({"assistant/chunk", "session/heartbeat"})
# G9b/S04 — repeatable O01 (alpha) observation event types. Their payloads
# live ONLY in observational/audit storage and MUST NOT enter the semantic
# normalize input: the observation payload is accepted by the input contract
# (an accepted session_events row) but is excluded from every output, from the
# chunk-merge source, and from the reducer's effect aggregation. A
# stream_progress observation carrying an effect_id MUST NOT be mistaken for a
# per-effect status signal (its count fields are audit-only and never
# constitute a flow-collection fact, S04 clause 2).
OBSERVATION_TYPES = frozenset({"stream_progress", "attempt/heartbeat"})
# G17 (D12) — the compact semantic result representation: normalize
# extracts it VERBATIM from the finalize record (the compaction/end event
# payload's three logical fields) and never recomputes, guesses or rewrites
# it from the event stream. The compaction/end raw event itself is an audit
# event (never part of the semantic trace); the extracted representation is
# a distinct semantic element.
COMPACT_RESULT_TYPES = frozenset({"compaction/end"})
# compaction/start is an audit-class control event: accepted by the input
# contract, excluded from every output (the lock's true state is control
# plane, not trace).
COMPACT_AUDIT_TYPES = frozenset({"compaction/start"})
COMPACT_RESULT_FIELDS = ("logical_cutoff_digest", "replacement_set_digest",
                         "compact_result_identity")
SUPPORTED_TYPES = (SEMANTIC_TYPES | OBSERVATIONAL_TYPES
                   | OBSERVATION_TYPES | {"turn/end"} | COMPACT_RESULT_TYPES
                   | COMPACT_AUDIT_TYPES)

# Segment-2 eligibility guard input: "pending" in the §3.2.1 aggregation
# sense — the three pending_effect_count statuses (planned/ready/
# dispatch_started) plus failed_retryable (a non-terminal failure awaiting
# retry or closure). An in-flight attempt (dispatch_started) MUST suppress a
# known end exactly like a planned/ready one (Conformance 15 guard (a):
# provider-cancel + a still-in-flight sibling -> no known turn/end).
_PENDING_STATUSES = frozenset({"planned", "ready", "dispatch_started",
                               "pending", "failed_retryable"})
_TERMINAL_STATUSES = frozenset({
    "succeeded", "failed_terminal", "cancelled_before_dispatch",
    "cancelled_after_dispatch", "unknown_outcome",
})

_STICKY_CODES = frozenset({
    "CANCELLED_BY_REQUEST_AFTER_DISPATCH",
    "CANCELLED_BY_REQUEST_BEFORE_DISPATCH",
    "cancelled_by_request_after_dispatch",
    "cancelled_by_request_before_dispatch",
})
_PROVIDER_CODES = frozenset({"CANCELLED_BY_PROVIDER", "cancelled_by_provider"})

_CLOSER_RESOLUTIONS = frozenset({
    "succeeded", "failed_terminal", "cancelled_after_dispatch",
})


class CanonicalizerError(Exception):
    """Fail-closed rejection with a stable code (closed set per stage)."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _require(cond: bool, detail: str) -> None:
    if not cond:
        raise CanonicalizerError(CANONICALIZER_UNSUPPORTED, detail)


def _clean(ev: dict, event_class: str) -> dict:
    """Output projection: attribution + type + payload + class tag only."""
    return {
        "event_type": ev["event_type"],
        "payload": ev.get("payload") or {},
        "event_class": event_class,
        "turn_id": ev.get("turn_id"),
        "step_id": ev.get("step_id"),
        "effect_id": ev.get("effect_id"),
        "semantic_input_ordinal": ev.get("semantic_input_ordinal"),
    }


def _merge_chunks(events: list[dict]) -> dict[tuple, dict]:
    """Merge assistant/chunk events by the frozen four-tuple key order.

    Returns {(effect_id, attempt_no): {"text": ..., "stream_id": ...,
    "chunks": n}} — arrival order and gaps never affect legality; the merged
    text is assembled in chunk_index order. Multiple stream_ids inside one
    (effect_id, attempt_no) fail closed (cross-stream order is
    undeterminable); same four-tuple with different content is a conflict.
    """
    streams: dict[tuple, dict[int, str]] = {}
    stream_ids: dict[tuple, str] = {}
    for ev in events:
        if ev.get("event_type") != "assistant/chunk":
            continue
        key = (ev.get("effect_id"), ev.get("attempt_no"))
        _require(ev.get("stream_id") is not None,
                 "assistant/chunk requires stream_id")
        _require(isinstance(ev.get("chunk_index"), int),
                 "assistant/chunk requires an integer chunk_index")
        prev_stream = stream_ids.get(key)
        if prev_stream is None:
            stream_ids[key] = ev["stream_id"]
        else:
            _require(prev_stream == ev["stream_id"],
                     f"multiple stream_ids within attempt {key}: "
                     "cross-stream order is undeterminable")
        text = (ev.get("payload") or {}).get("text")
        _require(isinstance(text, str),
                 "assistant/chunk payload must carry a string text")
        idx = ev["chunk_index"]
        per_stream = streams.setdefault(key, {})
        if idx in per_stream:
            if per_stream[idx] != text:
                raise CanonicalizerError(
                    CANONICALIZER_CONFLICT,
                    f"chunk {key}[{idx}] re-submitted with different content")
            continue  # idempotent duplicate collapse
        per_stream[idx] = text
    merged: dict[tuple, dict] = {}
    for key, per_stream in streams.items():
        merged[key] = {
            "text": "".join(per_stream[i] for i in sorted(per_stream)),
            "stream_id": stream_ids[key],
            "chunks": len(per_stream),
            # G9b: the sorted accepted index set — the flow-collection set
            # fact consumed by the completion-criteria engine.
            "indices": sorted(per_stream),
        }
    return merged


def _is_closer(ev: dict) -> bool:
    return (ev.get("payload") or {}).get("closer") is True


def _resolve_closers(turn_events: list[dict]) -> set[int]:
    """Validate the turn's repair closers and return the input positions to
    DROP from the projection (closers superseded inside the same effect's
    lineage — the per-effect latest closer survives).

    Fail-closed on any malformed closer (an uncovered raw combination is
    never guessed): the frozen metadata triple (resolution object in the
    closed set with a non-empty code, supersedes_event_key) and the event's
    own event_key are all required.
    """
    latest: dict[Any, int] = {}
    drops: set[int] = set()
    for pos, ev in enumerate(turn_events):
        if not _is_closer(ev):
            continue
        payload = ev.get("payload") or {}
        res = payload.get("resolution")
        _require(isinstance(res, dict),
                 "closer event requires a resolution identity object")
        _require(res.get("resolution") in _CLOSER_RESOLUTIONS,
                 f"closer resolution outside the closed set: "
                 f"{res.get('resolution')!r}")
        _require(isinstance(res.get("code"), str) and bool(res["code"]),
                 "closer resolution requires a non-empty code")
        _require(ev.get("event_key") is not None,
                 "closer event requires its event_key (supersedes chain)")
        _require(payload.get("supersedes_event_key") is not None,
                 "closer event requires supersedes_event_key")
        _require(ev.get("effect_id") is not None,
                 "closer event requires effect attribution")
        eff = ev["effect_id"]
        if eff in latest:
            drops.add(latest[eff])
        latest[eff] = pos
    return drops


def _turn_state(events: list[dict]) -> dict:
    """Per-turn aggregation of effect-level signals (last status wins)."""
    state: dict[str, Any] = {
        "effects": {},          # effect_id -> {status, code, decision_only, dispatched, order}
        "sticky_cancel": False,
        "unsealed_tools_plan": False,
        "candidates": [],       # terminal-signal candidates from input turn/end
        "order": 0,
    }
    for ev in events:
        turn_id = ev.get("turn_id")
        if ev.get("sticky_cancel"):
            state["sticky_cancel"] = True
        if ev.get("unsealed_tools_plan"):
            state["unsealed_tools_plan"] = True
        effect_id = ev.get("effect_id")
        if effect_id is not None:
            eff = state["effects"].setdefault(effect_id, {
                "status": None, "code": None, "decision_only": False,
                "dispatched": False, "order": state["order"],
            })
            state["order"] += 1
            status = ev.get("effect_status")
            if status is not None:
                eff["status"] = status
                if status != "pending":
                    eff["dispatched"] = eff["dispatched"] or (
                        status in ("dispatch_started", "succeeded",
                                   "failed_retryable", "failed_terminal",
                                   "cancelled_after_dispatch", "unknown_outcome"))
            if ev.get("code") is not None:
                eff["code"] = ev["code"]
            if ev.get("decision_only"):
                eff["decision_only"] = True
            if ev.get("event_type") == "assistant/chunk":
                eff["dispatched"] = True
            if _is_closer(ev):
                # G7c: the repair closer SUPERSEDES the effect's provisional
                # unknown representation — the effect's status/code resolve
                # from the closer's resolution identity (the projection
                # replaces; the input events never change).
                res = (ev.get("payload") or {}).get("resolution") or {}
                eff["status"] = res.get("resolution")
                eff["code"] = res.get("code")
                eff["dispatched"] = True
        if ev.get("event_type") == "turn/end":
            payload = ev.get("payload") or {}
            if payload.get("outcome") == "unknown":
                state["candidates"].append({"kind": "unknown"})
            else:
                state["candidates"].append({
                    "kind": "known",
                    "interrupted": bool(payload.get("interrupted", False)),
                    "reason": payload.get("reason"),
                })
    return state


def _reduce_turn(turn_events: list[dict], merged: dict[tuple, dict]) -> tuple[list[dict], dict | None]:
    """The unique turn-finalization reducer (three ordered segments).

    Returns (synthesized events, canonical turn/end payload or None).
    """
    state = _turn_state(turn_events)
    effects = state["effects"]

    def eff_payload_key(effect_id):
        return (effects[effect_id]["order"], effect_id or "")

    # Segment 1 — provisional representation of unresolved unknowns: emit
    # each unknown effect's representation and keep exactly ONE provisional
    # turn/end {outcome:unknown, reason:unknown_after_dispatch}. This
    # representation is provisional, NOT a known end: it is not subject to
    # the segment-2 eligibility guard.
    unknown_effects = [eid for eid, e in effects.items()
                        if e["status"] == "unknown_outcome"]
    synthesized: list[dict] = []
    if unknown_effects:
        for eid in sorted(unknown_effects, key=eff_payload_key):
            prefix = merged.get((eid, _attempt_of(turn_events, eid)))
            if prefix is not None and prefix["text"]:
                synthesized.append({
                    "event_type": "assistant/partial",
                    "payload": {"text": prefix["text"], "outcome": "unknown"},
                    "event_class": "semantic",
                    "turn_id": _turn_id_of(turn_events, eid),
                    "step_id": _step_id_of(turn_events, eid),
                    "effect_id": eid,
                })
        return synthesized, {
            "outcome": "unknown", "reason": "unknown_after_dispatch"}

    # Segment 2 — turn finalization eligibility guard: every terminal signal
    # (table rows and repair closers) is only a CANDIDATE; a KNOWN end may be
    # published only when the turn has no pending effect and no unsealed
    # tools plan. While the guard is open the candidates are retained and the
    # turn MUST NOT end (no known end output).
    guard_open = (
        any(e["status"] in _PENDING_STATUSES for e in effects.values())
        or state["unsealed_tools_plan"]
    )

    # Segment 3 — with eligibility passed, pick the unique reason by the
    # frozen priority, first hit stops:
    #   (1) unresolved unknown -> the segment-1 provisional representation
    #       (unreachable here: handled in segment 1);
    #   (2) sticky cancel (wins over provider cancel on double trigger) with
    #       the dispatch-phase split;
    #   (3) provider cancellation without a local sticky latch;
    #   (4) terminal failure -> {interrupted:true, reason:failed};
    #   (5) normal close -> {interrupted:false}, with the missing_final
    #       special form only when the succeeded closing LLM effect is the
    #       turn's decision_only decision.
    any_dispatched = any(e["dispatched"] for e in effects.values())
    sticky = state["sticky_cancel"] or any(
        e["code"] in _STICKY_CODES or
        (e["status"] == "cancelled_after_dispatch" and
         e["code"] in _STICKY_CODES)
        for e in effects.values()) or any(
        c["kind"] == "known" and c.get("reason") in
        ("cancelled_by_request_after_dispatch",
         "cancelled_by_request_before_dispatch",
         "CANCELLED_BY_REQUEST_AFTER_DISPATCH",
         "CANCELLED_BY_REQUEST_BEFORE_DISPATCH")
        for c in state["candidates"])
    provider = any(e["code"] in _PROVIDER_CODES for e in effects.values()) or any(
        c["kind"] == "known" and c.get("reason") in
        ("cancelled_by_provider", "CANCELLED_BY_PROVIDER")
        for c in state["candidates"])
    failed = any(e["status"] == "failed_terminal" for e in effects.values()) or any(
        c["kind"] == "known" and c.get("reason") == "failed"
        for c in state["candidates"])
    all_terminal_succeeded = (
        len(effects) > 0 and
        all(e["status"] == "succeeded" for e in effects.values()))
    normal_close = all_terminal_succeeded or any(
        c["kind"] == "known" and not c["interrupted"] and not c.get("reason")
        for c in state["candidates"])

    if sticky:
        reason = ("cancelled_by_request_after_dispatch" if any_dispatched
                  else "cancelled_by_request_before_dispatch")
        # G9b (spec §1.2 sticky-cancel row): a dispatched LLM effect cancelled
        # by request that has an accepted chunk prefix MUST output exactly one
        # assistant/partial (merged by the frozen four-tuple key order); no
        # prefix MUST output none. The prefix source is the accepted chunk
        # events alone (S04 clause 3 — observations never contribute). Pre-
        # dispatch cancels are cancelled_before_dispatch with no stream, so
        # the effect's status/code gate naturally yields no prefix.
        for eid in sorted(effects, key=eff_payload_key):
            e = effects[eid]
            if e["status"] != "cancelled_after_dispatch":
                continue
            prefix = merged.get((eid, _attempt_of(turn_events, eid)))
            if prefix is not None and prefix["text"]:
                synthesized.append({
                    "event_type": "assistant/partial",
                    "payload": {"text": prefix["text"]},
                    "event_class": "semantic",
                    "turn_id": _turn_id_of(turn_events, eid),
                    "step_id": _step_id_of(turn_events, eid),
                    "effect_id": eid,
                })
        end = {"interrupted": True, "reason": reason}
    elif provider:
        for eid in sorted(effects, key=eff_payload_key):
            e = effects[eid]
            if e["code"] in _PROVIDER_CODES:
                prefix = merged.get((eid, _attempt_of(turn_events, eid)))
                if prefix is not None and prefix["text"]:
                    synthesized.append({
                        "event_type": "assistant/partial",
                        "payload": {"text": prefix["text"]},
                        "event_class": "semantic",
                        "turn_id": _turn_id_of(turn_events, eid),
                        "step_id": _step_id_of(turn_events, eid),
                        "effect_id": eid,
                    })
        end = {"interrupted": True, "reason": "cancelled_by_provider"}
    elif failed:
        end = {"interrupted": True, "reason": "failed"}
    elif normal_close:
        # Chunk-only succeeded LLM effect: the merged prefix is RETAINED as
        # assistant/partial (spec §1.2 row "仅有 chunk，无 final，且 LLM effect
        # succeeded"). The missing_final end form applies only when that
        # succeeded LLM effect IS the turn's closing decision (decision_only)
        # and no tools plan is unsealed: a decision with tool calls keeps the
        # partial and the turn MUST NOT end (Conformance 15 guard (b); the
        # unsealed-tools-plan guard above carries the no-end part).
        missing_final = False
        if all_terminal_succeeded:
            for eid in sorted(effects, key=eff_payload_key):
                e = effects[eid]
                prefix = merged.get((eid, _attempt_of(turn_events, eid)))
                has_final = any(
                    ev.get("event_type") == "assistant/message"
                    and ev.get("effect_id") == eid
                    for ev in turn_events)
                if (prefix is not None and prefix["chunks"] > 0
                        and not has_final):
                    synthesized.append({
                        "event_type": "assistant/partial",
                        "payload": {"text": prefix["text"]},
                        "event_class": "semantic",
                        "turn_id": _turn_id_of(turn_events, eid),
                        "step_id": _step_id_of(turn_events, eid),
                        "effect_id": eid,
                    })
                    if (e["decision_only"]
                            and not state["unsealed_tools_plan"]):
                        missing_final = True
        end = ({"incomplete": True, "reason": "missing_final"}
               if missing_final else {"interrupted": False})
    else:
        end = None  # no terminal signal: the turn stays open

    if guard_open:
        return synthesized, None
    return synthesized, end


def _attempt_of(events: list[dict], effect_id) -> Any:
    for ev in events:
        if ev.get("effect_id") == effect_id and ev.get("attempt_no") is not None:
            return ev.get("attempt_no")
    return None


def _turn_id_of(events: list[dict], effect_id):
    for ev in events:
        if ev.get("effect_id") == effect_id:
            return ev.get("turn_id")
    return None


def _step_id_of(events: list[dict], effect_id):
    for ev in events:
        if ev.get("effect_id") == effect_id:
            return ev.get("step_id")
    return None


def normalize(events: list[dict], canonicalizer_version: str = "@v1") -> list[dict]:
    """Canonical observable_trace for the P0B event subset (unique output).

    Semantic events sort by turn/step/dispatch_ordinal (never wall-clock);
    chunks merge by the four-tuple key order and drop when a final
    assistant/message exists; the unique reducer emits at most one turn/end
    per turn; observational events stay tagged (comparison layers ignore
    them); turn order is first-appearance (logical), never timestamp.
    """
    _require(isinstance(canonicalizer_version, str) and canonicalizer_version,
             "canonicalizer_version required")
    _require(isinstance(events, list), "events must be a list")

    for i, ev in enumerate(events):
        _require(isinstance(ev, dict), f"event {i} is not an object")
        _require(isinstance(ev.get("event_type"), str), f"event {i} lacks event_type")
        _require(ev["event_type"] in SUPPORTED_TYPES,
                 f"event {i}: unsupported raw combination for event_type "
                 f"{ev['event_type']!r}")
        _require(isinstance(ev.get("payload") or {}, dict),
                 f"event {i}: payload must be an object")

    # S04 clause 1: observation payloads (stream_progress / attempt/heartbeat)
    # are accepted by the input contract but excluded from the semantic
    # normalize input — they never reach the chunk merge, the reducer's
    # per-effect aggregation or the output trace.
    # G17 (D12): the compact semantic result representation is extracted
    # verbatim from each finalize record FIRST — the three logical fields
    # ride the payload as persisted by compact_finalize; nothing is derived
    # from the stream. The audit raw event itself never enters the trace.
    compact_results = [
        {
            "event_type": "compaction/result",
            "payload": {k: (ev.get("payload") or {})[k]
                        for k in COMPACT_RESULT_FIELDS},
            "event_class": "semantic",
            "turn_id": None,
            "step_id": None,
            "effect_id": None,
        }
        for ev in events
        if ev["event_type"] in COMPACT_RESULT_TYPES
        and all(k in (ev.get("payload") or {})
                for k in COMPACT_RESULT_FIELDS)
    ]
    events = [ev for ev in events
              if ev["event_type"] not in OBSERVATION_TYPES
              and ev["event_type"] not in COMPACT_AUDIT_TYPES]

    merged = _merge_chunks(events)

    # Turn grouping in first-appearance order (logical, not wall-clock); the
    # session-level bucket holds turn-less events.
    turn_order: list = []
    turns: dict[Any, list[dict]] = {}
    session_level: list[dict] = []
    for ev in events:
        t = ev.get("turn_id")
        if t is None:
            session_level.append(ev)
        else:
            if t not in turns:
                turns[t] = []
                turn_order.append(t)
            turns[t].append(ev)

    out: list[dict] = []
    for t in turn_order:
        tevents = turns[t]

        # G7c closer consumption: validate closers and drop the ones
        # superseded inside the same effect's lineage (projection replaces;
        # the input events are append-only and never modified). Closers of
        # OTHER effects keep their per-effect semantic role.
        drops = _resolve_closers(tevents)
        if drops:
            tevents = [ev for pos, ev in enumerate(tevents)
                       if pos not in drops]

        # Semantic passthrough sorted by turn/step/dispatch_ordinal; chunks
        # are consumed by the merge above; turn/end is reducer-owned.
        semantic = [(pos, ev) for pos, ev in enumerate(tevents)
                    if ev["event_type"] in SEMANTIC_TYPES]
        semantic.sort(key=lambda pair: (
            str(pair[1].get("step_id") or ""),
            pair[1].get("dispatch_ordinal")
            if pair[1].get("dispatch_ordinal") is not None else 1 << 62,
            pair[1].get("semantic_input_ordinal")
            if pair[1].get("semantic_input_ordinal") is not None else 1 << 62,
            pair[0],
        ))
        for _pos, ev in semantic:
            out.append(_clean(ev, "semantic"))

        synthesized, end = _reduce_turn(tevents, merged)
        out.extend(synthesized)
        if end is not None:
            out.append({
                "event_type": "turn/end",
                "payload": end,
                "event_class": "semantic",
                "turn_id": t,
                "step_id": None,
                "effect_id": None,
            })

    for ev in session_level:
        if ev["event_type"] == "session/heartbeat":
            out.append(_clean(ev, "observational"))
        elif ev["event_type"] in SEMANTIC_TYPES:
            out.append(_clean(ev, "semantic"))
        # turn-less turn/end or chunk inputs are unreachable in the P0B
        # subset contract (chunks carry effect attribution; ends are
        # turn-owned); anything else already failed SUPPORTED above.
    out.extend(compact_results)
    return out
