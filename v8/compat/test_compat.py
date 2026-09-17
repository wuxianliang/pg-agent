"""G13 gate: P0C dsh-compat host-agnostic contract surface.

Run: uv run python v8/compat/test_compat.py  (exit 0 = pass)

Covers (plan G13 row, all MUSTs):
  * compat_unmapped_audit unified command — envelope (adapter identity /
    fixture digest / unknown DSH type canonical identity / payload hash),
    unified receipt/binding, same command_id + same payload idempotent
    (exactly one row), different payload -> IDEMPOTENCY_CONFLICT, zero
    control state, no semantic-result events, public append of
    compat/unmapped -> EVENT_TYPE_RESTRICTED;
  * adapter manifest persistence — dispatch_interception x
    driver_switch_capability, immutable after creation, explicit
    compat-only lists, dropping-unsupported-events-while-claiming-
    portable refused;
  * the section 5.1 sixteen-row mapping at the database layer (whitelist
    rows, semantic-result rows routed to ledger commands, not-persisted
    rows, X03 attribution matrix row by row with direct-inserted grants);
  * Conformance 11 dependency-free subcases — fork cutoff
    FORK_CUTOFF_UNSTABLE three assertions + the mandatory unsupported
    driver UNSUPPORTED negative (never exempt);
  * the two-dimension capability matrix blocked-set union rules driven
    through the GUC seam (matrix logic only);
  * the P0C passed/failed/blocked reporter with the six fail-class
    refusals and the pinned-host unresolved-manifest rule;
  * the real-provider (DeepSeek) DB protocol layer subcases, an
    EXPLICIT opt-in smoke: the default run is keyless (the adapter is
    never constructed, the fake suite runs unconditionally),
    `--real-provider-smoke` opts in (missing credentials -> not_run +
    exit 2; started-but-failing -> failed + exit 1, never swallowed;
    real calls always outside database transactions; the fake suite
    stays authoritative).
  * `--report-json <path>` writes the final honest build_report dict
    (schema v2) atomically after it is produced — refusal/kill leaves
    the file absent, which is itself the signal (runner contract).

Exit codes: 0 = the must-run set (DB contract + fake + reporter) green
(plus a passed opt-in smoke when requested); 1 = a failure (never
swallowed); 2 = `--real-provider-smoke` requested but credentials
absent (the explicit target did not execute).

Spec: docs/designs/v8-dev.md sections 5/5.1/5.2, P0C, Conformance
11/12/16; digests s31b (compat_unmapped_audit row), s2 (grant stub).
"""
from __future__ import annotations

import contextlib
import json
import sys
import uuid
from dataclasses import dataclass, replace
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v8.canonical import canonicalize, escape_dollar_keys
from v8.cancel.client import request_cancel
from v8.effect.client import (
    build_result_payload,
    claim_session,
    complete_effect,
    dispatch_effect,
    prepare_step,
)
from v8.events.canonicalizer import normalize
from v8.events.client import build_request, create_session
from v8.repair.client import repair
from v8.tools.client import complete_tool_effect, seal_batch

from v8.compat import client as compat
from v8.compat import p0c_report
from v8.compat.setup_db import DB, main as setup_db
from v8.loop.runtime import DeepSeekLLM, FakeLLM

DRIVER_C = "dsh-compat"
ADAPTER = "dsh-compat-adapter@1"
SV, CV = "sv@1", "canon@1"

RESULTS: dict[str, str] = {}
NOT_RUN_REASONS: dict[str, str] = {}
# The initial six-item host fact set (J0 plan §4.1): the working set is
# REBUILT at every main() entry — never an empty set (the reporter's
# allowlist validation would then reject legal sources), never the
# previous run's residue (dynamically injected items would leak into
# the next report). The reporter's EXTERNAL_BLOCKED is the ALLOWED
# superset (7 items); this set is the CURRENT host fact set.
INITIAL_EXTERNAL_BLOCKED = frozenset({
    "blocked:section-5.2-pre-verification",
    "blocked:all-real-io-subcases",
    "blocked:p0c-minimal-turn-dual-runtime",
    "blocked:pinned-five-piece-values",
    "blocked:compat-only-t0-t4-participation",
    "blocked:p0c-final-sign-off",
})
EXTERNAL_BLOCKED: set[str] = set(INITIAL_EXTERNAL_BLOCKED)
SMOKE_SUBCASE = "c12-db-real-provider-protocol"


def _reset_state() -> None:
    """Per-run state reset (J0 plan §4.1): two consecutive main()/test
    runs never reuse the previous round's results or dynamic blocked
    sources."""
    RESULTS.clear()
    NOT_RUN_REASONS.clear()
    EXTERNAL_BLOCKED.clear()
    EXTERNAL_BLOCKED.update(INITIAL_EXTERNAL_BLOCKED)


def uri() -> str:
    return get_server().get_uri(DB)


def u() -> str:
    return str(uuid.uuid4())


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f": {detail}" if detail else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def one(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def rows(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def exec_sql(conn, sql, params=()) -> None:
    with conn.cursor() as cur:
        cur.execute(sql, params)
    conn.commit()


def expect_error(conn, label: str, fn) -> None:
    try:
        fn()
    except psycopg2.Error as exc:  # noqa: PERF203
        conn.rollback()
        check(label, True, type(exc).__name__)
        return
    conn.rollback()
    check(label, False, "expected a database rejection, none was raised")


def fresh_session(conn, driver: str = DRIVER_C) -> str:
    s = u()
    create_session(conn, s, driver)
    return s


def next_seq_of(conn, s) -> int:
    return one(conn, "SELECT next_seq FROM sessions WHERE session_id=%s", (s,))[0]


def next_ordinal(conn, s) -> int:
    return one(conn, "SELECT coalesce(max(semantic_input_ordinal), 0) + 1"
                     " FROM session_events WHERE session_id=%s", (s,))[0]


def session_row(conn, s):
    return one(conn,
               "SELECT state, driver_mode, session_fence, driver_epoch,"
               " cancellation_epoch, lease_owner, active_step_id"
               " FROM sessions WHERE session_id=%s", (s,))


def events_of_type(conn, s, event_type: str):
    return rows(conn, "SELECT seq, event_class, payload FROM session_events"
                      " WHERE session_id=%s AND event_type=%s ORDER BY seq",
                (s, event_type))


def raw_entry(event_type: str, payload=None, **kw) -> dict:
    payload_canonical, payload_hash = canonicalize(
        escape_dollar_keys(payload if payload is not None else {}))
    entry = {"event_type": event_type, "schema_version": SV,
             "canonicalizer_version": CV,
             "payload_canonical": payload_canonical,
             "payload_hash": payload_hash}
    entry.update(kw)
    return entry


def semantic_entry(event_type: str, turn: str, payload=None, *,
                   ordinal: int | None = None, step_id=None,
                   effect_id=None) -> dict:
    e = raw_entry(event_type, payload, turn_id=turn,
                  step_id=step_id, effect_id=effect_id,
                  semantic_input_ordinal=(ordinal if ordinal is not None
                                          else 10**6 + hash(event_type) % 7))
    return e


def append_public(conn, session_id, entries, *, driver: str = DRIVER_C,
                  driver_epoch: int = 1, command_id: str | None = None,
                  caller_subject=None, caller_driver=None,
                  caller_epoch=None, caller_grant_id=None) -> dict:
    """Gate + append + commit with arbitrary (including restricted) entry
    types — the compat append facade probe."""
    session_id = str(session_id)
    command_id = command_id or f"ap-{u()[:10]}"
    expected = next_seq_of(conn, session_id)
    canonical_text, computed = build_request(
        "append_events", session_id, command_id, driver, driver_epoch,
        expected, entries)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT outcome, code, receipt_json, executable"
                " FROM v_command_gate(%s::uuid, %s, %s, %s, %s)",
                (session_id, command_id, "append_events", canonical_text,
                 computed))
            _o, _c, _r, executable = cur.fetchone()
            if not executable:
                conn.rollback()
                return {"outcome": _o, "code": _c, "receipt": _r,
                        "executable": False}
            cur.execute(
                "SELECT outcome, code, receipt_json FROM v_append_events("
                "%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (session_id, command_id, driver, driver_epoch, expected,
                 computed, canonical_text,
                 json.dumps(entries, ensure_ascii=False,
                            separators=(",", ":")),
                 caller_subject, caller_driver, caller_epoch, caller_grant_id))
            outcome, code, receipt = cur.fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"outcome": outcome, "code": code, "receipt": receipt,
            "executable": True, "command_id": command_id}


def trace_events(conn, session_id) -> list[dict]:
    evs = rows(conn,
               "SELECT event_type, payload, turn_id, step_id, effect_id,"
               " event_key, attempt_no FROM session_events"
               " WHERE session_id=%s ORDER BY seq", (session_id,))
    statuses = {str(r[0]): r[1] for r in rows(
        conn, "SELECT effect_id, status FROM effect_requests"
              " WHERE session_id=%s", (session_id,))}
    out = []
    for et, payload, turn, step, eff, key, att in evs:
        d = {"event_type": et, "payload": json.loads(payload),
             "turn_id": str(turn) if turn is not None else None,
             "step_id": str(step) if step is not None else None,
             "effect_id": str(eff) if eff is not None else None,
             "event_key": key, "attempt_no": att}
        if eff is not None and not d["payload"].get("closer"):
            st = statuses.get(str(eff))
            if st is not None:
                d["effect_status"] = st
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# fixtures walking the seal/dispatch/completion paths under the compat
# driver (the fixed-name seeded grants cover these once the G12 gates
# turn real; under the Wave1 stub they are present-but-dormant)
# ---------------------------------------------------------------------------

def compat_decision_fx(conn, *, execution_mode: str = "non_streaming",
                        retry_class: str = "verifiable_no_effect",
                        max_attempts: int = 3):
    s = fresh_session(conn)
    turn, step, eff = u(), u(), u()
    rh, ik = f"rh-{u()[:10]}", f"ik-{u()[:10]}"
    r0 = claim_session(conn, s, DRIVER_C)
    rs = prepare_step(conn, s, f"seal-{u()[:8]}", DRIVER_C, 1,
                      r0["session_fence"], step, turn, eff,
                      execution_mode=execution_mode,
                      retry_class=retry_class, max_attempts=max_attempts,
                      request_hash=rh, idempotency_key=ik)
    check("fx compat decision seal accepted", rs["outcome"] == "accepted", rs)
    rd = dispatch_effect(conn, s, f"dsp-{u()[:8]}", eff, DRIVER_C, 1,
                         rs["receipt"]["session_fence"],
                         rs["receipt"]["job_fence"])
    check("fx compat dispatch accepted", rd["outcome"] == "accepted", rd)
    return {"session": s, "turn": turn, "step": step, "effect": eff,
            "fence": rs["receipt"]["session_fence"],
            "job_fence": rs["receipt"]["job_fence"], "rh": rh, "ik": ik}


def compat_succeed_decision(conn, fx, *, text: str = "compat-final"):
    return complete_effect(
        conn, fx["session"], f"cmp-{u()[:8]}", fx["effect"], DRIVER_C, 1,
        dispatch_session_fence=2, job_fence=fx["job_fence"],
        step_id=fx["step"], request_hash=fx["rh"], idempotency_key=fx["ik"],
        outcome="succeeded", message={"text": text}, tools=[],
        decision_only=True, final_tools=False,
        evidence={"class": "known_success",
                  "provider_receipt": {"receipt_id": f"pr-{u()[:8]}"}})


def compat_unknown_decision(conn, fx):
    return complete_effect(
        conn, fx["session"], f"cmp-{u()[:8]}", fx["effect"], DRIVER_C, 1,
        dispatch_session_fence=2, job_fence=fx["job_fence"],
        step_id=fx["step"], request_hash=fx["rh"], idempotency_key=fx["ik"],
        outcome="failed_retryable", message={"text": ""}, tools=[],
        decision_only=True, final_tools=False,
        evidence={"class": "provider_error"},
        result_payload={"error": {"kind": "provider_error"}})


def compat_repair_success(conn, fx):
    head = one(conn, "SELECT head_event_key FROM turn_end_slots"
                     " WHERE session_id=%s", (fx["session"],))[0]
    return repair(conn, fx["session"], f"rpr-{u()[:8]}", fx["effect"], 1,
                  driver=DRIVER_C, driver_epoch=1,
                  supersedes_event_key=head,
                  evidence={"class": "known_success",
                            "provider_receipt": {"receipt_id": f"pr-{u()[:8]}"}},
                  resolution_kind="succeeded",
                  message={"text": "repaired-final"}, tools=[],
                  decision_only=True, final_tools=False)


def slot_head(conn, session_id):
    return one(conn, "SELECT head_event_key FROM turn_end_slots"
                     " WHERE session_id=%s", (session_id,))[0]


# ---------------------------------------------------------------------------
# 1. compat_unmapped_audit unified command
# ---------------------------------------------------------------------------

def test_unmapped_audit(conn) -> None:
    s = fresh_session(conn)
    before = session_row(conn, s)
    seq0 = next_seq_of(conn, s)
    cmd = f"cua-{u()[:10]}"

    r1 = compat.compat_unmapped_audit(
        conn, s, cmd, DRIVER_C, 1, ADAPTER,
        fixture_digest=f"fdg-{u()[:12]}",
        dsh_type_canonical_identity="dsh:unknown-type@x",
        payload_hash="ab" * 32)
    check("unmapped audit accepted", r1["outcome"] == "accepted", r1)
    evs = events_of_type(conn, s, "compat/unmapped")
    check("exactly one compat/unmapped audit event, class=audit",
          len(evs) == 1 and evs[0][1] == "audit", evs)
    check("normal seq allocation (next_seq consumed)",
          evs[0][0] == seq0 and next_seq_of(conn, s) == seq0 + 1,
          (seq0, next_seq_of(conn, s)))
    payload = json.loads(evs[0][2])
    check("audit event envelope carries the four frozen fields",
          payload.get("adapter_identity") == ADAPTER
          and payload.get("dsh_type_canonical_identity")
          == "dsh:unknown-type@x"
          and payload.get("payload_hash") == "ab" * 32
          and bool(payload.get("fixture_digest")), payload)
    rec1 = r1["receipt"]
    check("receipt returns the audit event identity + seq",
          rec1["events"][0]["event_type"] == "compat/unmapped"
          and rec1["events"][0]["seq"] == seq0, rec1)

    after = session_row(conn, s)
    check("zero control state (only next_seq moved)",
          after[:7] == before[:7], (before, after))
    check("no semantic-result events written by the command",
          one(conn, "SELECT count(*) FROM session_events WHERE session_id=%s"
                    " AND event_class='semantic'", (s,))[0] == 0)

    # Same command_id + same payload -> idempotent replay, no second row.
    r2 = compat.compat_unmapped_audit(
        conn, s, cmd, DRIVER_C, 1, ADAPTER,
        fixture_digest=payload["fixture_digest"],
        dsh_type_canonical_identity="dsh:unknown-type@x",
        payload_hash="ab" * 32)
    check("same command_id same payload replays the original receipt",
          r2["outcome"] == "accepted" and r2["receipt"] == rec1, r2)
    check("still exactly one audit event",
          len(events_of_type(conn, s, "compat/unmapped")) == 1)

    # Same command_id + DIFFERENT payload -> stable IDEMPOTENCY_CONFLICT.
    r3 = compat.compat_unmapped_audit(
        conn, s, cmd, DRIVER_C, 1, ADAPTER,
        fixture_digest=f"fdg-other-{u()[:8]}",
        dsh_type_canonical_identity="dsh:unknown-type@x",
        payload_hash="cd" * 32)
    check("same command_id different payload -> IDEMPOTENCY_CONFLICT",
          r3["outcome"] == "rejected_mismatch"
          and r3["code"] == "IDEMPOTENCY_CONFLICT", r3)
    check("conflict appended no second event",
          len(events_of_type(conn, s, "compat/unmapped")) == 1)
    bind = one(conn, "SELECT first_key_kind, first_outcome"
                     " FROM command_bindings WHERE session_id=%s"
                     " AND command_id=%s", (s, cmd))
    check("first binding kept (accepted, canonical hash)",
          bind == ("canonical_request_hash", "accepted"), bind)

    # Adapter identity mismatch -> stable rejection, zero events.
    r4 = compat.compat_unmapped_audit(
        conn, s, f"cua-{u()[:10]}", DRIVER_C, 1, "rogue-adapter@9",
        fixture_digest=f"fdg-{u()[:8]}",
        dsh_type_canonical_identity="dsh:other@y",
        payload_hash="ef" * 32)
    check("unbound adapter identity -> ADAPTER_IDENTITY_MISMATCH",
          r4["outcome"] == "rejected_mismatch"
          and r4["code"] == "ADAPTER_IDENTITY_MISMATCH", r4)
    check("mismatch rejection wrote no audit event",
          len(events_of_type(conn, s, "compat/unmapped")) == 1)

    # Envelope driver/epoch stale.
    r5 = compat.compat_unmapped_audit(
        conn, s, f"cua-{u()[:10]}", DRIVER_C, 7, ADAPTER,
        fixture_digest=f"fdg-{u()[:8]}",
        dsh_type_canonical_identity="dsh:other@z",
        payload_hash="99" * 32)
    check("stale driver/epoch -> rejected_stale",
          r5["outcome"] == "rejected_stale", r5)

    # Missing envelope field.
    r6 = compat.compat_unmapped_audit(
        conn, s, f"cua-{u()[:10]}", DRIVER_C, 1, ADAPTER,
        fixture_digest="",
        dsh_type_canonical_identity="dsh:other@w",
        payload_hash="11" * 32)
    check("missing envelope field -> ENVELOPE_FIELD_MISSING",
          r6["outcome"] == "rejected_mismatch"
          and r6["code"] == "ENVELOPE_FIELD_MISSING", r6)

    # The public append facade refuses compat/unmapped.
    r7 = append_public(conn, s, [raw_entry(
        "compat/unmapped", {"dsh_type": "dsh:unknown-type@x"})])
    check("public append of compat/unmapped -> EVENT_TYPE_RESTRICTED",
          r7["outcome"] == "rejected_mismatch"
          and r7["code"] == "EVENT_TYPE_RESTRICTED", r7)
    check("refused append persisted nothing",
          len(events_of_type(conn, s, "compat/unmapped")) == 1)

    RESULTS["c1-db-receipt-idempotency"] = "passed"
    RESULTS["c16-db-unmapped-audit"] = "passed"


# ---------------------------------------------------------------------------
# 2. adapter manifest persistence
# ---------------------------------------------------------------------------

def test_manifest(conn) -> None:
    m = one(conn, "SELECT dispatch_interception, dispatch_note,"
                  " driver_switch_capability FROM compat_adapter_manifests"
                  " WHERE adapter_id=%s", (ADAPTER,))
    check("seeded pinned manifest: unresolved dispatch (NULL+note),"
          " unsupported switch",
          m is not None and m[0] is None and bool(m[1])
          and m[2] == "unsupported", m)

    expect_error(conn, "manifest UPDATE refused (immutable after creation)",
                 lambda: exec_sql(
                     conn, "UPDATE compat_adapter_manifests"
                           " SET driver_switch_capability='supported'"
                           " WHERE adapter_id=%s", (ADAPTER,)))
    expect_error(conn, "manifest DELETE refused",
                 lambda: exec_sql(
                     conn, "DELETE FROM compat_adapter_manifests"
                           " WHERE adapter_id=%s", (ADAPTER,)))
    current = one(conn, "SELECT driver_switch_capability"
                        " FROM compat_adapter_manifests WHERE adapter_id=%s",
                  (ADAPTER,))
    check("immutable refusal left the row untouched",
          current == ("unsupported",), current)

    expect_error(conn, "register with unknown dispatch value refused",
                 lambda: compat.register_manifest(
                     conn, "bad-adapter@1", "bad-drv", "sometimes", None,
                     "unsupported"))
    expect_error(conn, "register NULL without note refused",
                 lambda: compat.register_manifest(
                     conn, "bad-adapter@2", "bad-drv", None, None,
                     "unsupported"))
    expect_error(conn, "register resolved value WITH note refused",
                 lambda: compat.register_manifest(
                     conn, "bad-adapter@3", "bad-drv", "none", "a note",
                     "unsupported"))
    expect_error(conn, "register with a bad switch declaration refused",
                 lambda: compat.register_manifest(
                     conn, "bad-adapter@4", "bad-drv", None, "n", "maybe"))
    expect_error(conn, "register with non-list compat-only scope refused",
                 lambda: compat.register_manifest(
                     conn, "bad-adapter@5", "bad-drv", None, "n",
                     "unsupported", compat_only_plugins="all-of-them"))
    expect_error(conn, "register with non-string fixture element refused",
                 lambda: compat.register_manifest(
                     conn, "bad-adapter@6", "bad-drv", None, "n",
                     "unsupported", compat_only_fixtures=[1, 2]))

    # A resolved probe manifest (switch supported, dispatch verified sync)
    # registers fine and feeds the matrix-logic section below.
    compat.register_manifest(conn, "dsh-compat-adapter-probe@1",
                             "dsh-compat-probe", "sync_before_io", None,
                             "supported")

    # compat-only declaration acts on an explicit list; a fixture in that
    # list can never be claimed portable (dropping unsupported events
    # while claiming portable is forbidden).
    compat.register_manifest(conn, "drop-adapter@1", "drop-drv", "none",
                             None, "unsupported",
                             compat_only_fixtures=["fx-drop-1"])
    check("compat-only fixture claimed portable -> refused",
          compat.portable_claim_ok(conn, "drop-adapter@1",
                                   ["fx-drop-1", "fx-ok"]) is False)
    check("disjoint portable claim ok",
          compat.portable_claim_ok(conn, "drop-adapter@1",
                                   ["fx-ok"]) is True)

    RESULTS["c16-db-matrix-logic"] = "passed"   # proven below, kept here


# ---------------------------------------------------------------------------
# 3. section 5.1 sixteen-row mapping (database layer)
# ---------------------------------------------------------------------------

RESTRICTED_TYPES = [
    "assistant/message",       # row 2: ledger command only
    "stream_progress",         # row 4: complete_effect non-final only
    "turn/end",                # rows 6/7: internal commands only
    "tool/call",               # row 8: controlled seal path only
    "tool/result",             # row 9: completion/repair only
    "attempt/heartbeat",       # row 12: DB-internal observation only
    "heartbeat",               # bare heartbeat removed from the whitelist
    "compaction/start",        # row 13: compact control plane only
    "compaction/end",
    "compat/unmapped",         # row 16 (Conformance 16 tail)
    "fiber/frame",             # row 15: not persisted at all
    "isolate/frame",
    "dsh/next",
    "dsh/plan-mode",           # row 16: not persisted at all
]


def test_s5_mapping(conn) -> None:
    # ---- rows 1/5/10/11: whitelist input/observation via the public
    #      append facade, X03 attribution matrix row by row ----
    s = fresh_session(conn)
    turn = u()
    r = append_public(conn, s, [semantic_entry(
        "user/message", turn, {"text": "hello"},
        ordinal=next_ordinal(conn, s))])
    check("row 1 user/message via public facade accepted",
          r["outcome"] == "accepted", r)
    r = append_public(conn, s, [semantic_entry(
        "turn/start", turn, {"origin": "user"},
        ordinal=next_ordinal(conn, s))])
    check("row 5 turn/start via public facade accepted",
          r["outcome"] == "accepted", r)
    r = append_public(conn, s, [semantic_entry(
        "agent/inject", turn, {"text": "reminder"},
        ordinal=next_ordinal(conn, s))])
    check("row 10 agent/inject via public facade accepted",
          r["outcome"] == "accepted", r)
    r = append_public(conn, s, [raw_entry(
        "session/heartbeat", {"driver": DRIVER_C})])
    check("row 11 session/heartbeat via public facade accepted",
          r["outcome"] == "accepted", r)
    check("heartbeat row is observational with no turn attribution",
          one(conn, "SELECT event_class, turn_id FROM session_events"
                    " WHERE session_id=%s AND event_type='session/heartbeat'",
              (s,)) == ("observational", None))

    # X03 row by row: each input type requires turn_id non-NULL and
    # step_id/effect_id fixed NULL.
    for etype in ("user/message", "turn/start", "agent/inject"):
        rx = append_public(conn, s, [semantic_entry(
            etype, None, {"t": 1}, ordinal=next_ordinal(conn, s))])
        check(f"X03 {etype}: missing turn_id -> ATTRIBUTION_MATRIX_VIOLATION",
              rx["outcome"] == "rejected_mismatch"
              and rx["code"] == "ATTRIBUTION_MATRIX_VIOLATION", rx)
        rx = append_public(conn, s, [semantic_entry(
            etype, turn, {"t": 2}, ordinal=next_ordinal(conn, s),
            step_id=u())])
        check(f"X03 {etype}: step_id set -> ATTRIBUTION_MATRIX_VIOLATION",
              rx["code"] == "ATTRIBUTION_MATRIX_VIOLATION", rx)
        rx = append_public(conn, s, [semantic_entry(
            etype, turn, {"t": 3}, ordinal=next_ordinal(conn, s),
            effect_id=u())])
        check(f"X03 {etype}: effect_id set -> ATTRIBUTION_MATRIX_VIOLATION",
              rx["code"] == "ATTRIBUTION_MATRIX_VIOLATION", rx)

    # ---- rows 2/4/6/7/8/9/13/15/16: semantic-result / internal types
    #      refuse on the public facade ----
    for etype in RESTRICTED_TYPES:
        rx = append_public(conn, s, [raw_entry(etype, {"x": 1})])
        check(f"public append of {etype} -> EVENT_TYPE_RESTRICTED",
              rx["outcome"] == "rejected_mismatch"
              and rx["code"] == "EVENT_TYPE_RESTRICTED", rx)
    check("restricted probes persisted no events",
          one(conn, "SELECT count(*) FROM session_events WHERE session_id=%s"
                    " AND event_type != ALL(%s)",
              (s, ["user/message", "turn/start", "agent/inject",
                   "session/heartbeat"]))[0] == 0)

    # ---- row 2: assistant final routed through the completion facade ----
    fx = compat_decision_fx(conn)
    rc = compat_succeed_decision(conn, fx)
    check("row 2 completion facade accepted", rc["outcome"] == "accepted", rc)
    msgs = events_of_type(conn, fx["session"], "assistant/message")
    check("row 2 assistant/message generated by complete_effect",
          len(msgs) == 1 and msgs[0][1] == "semantic"
          and json.loads(msgs[0][2]).get("text") == "compat-final", msgs)

    # ---- row 6: normal turn/end from the turn-close internal path ----
    ends = events_of_type(conn, fx["session"], "turn/end")
    check("row 6 turn/end {interrupted:false} generated internally",
          len(ends) == 1
          and json.loads(ends[0][2]).get("interrupted") is False, ends)

    # ---- row 7: interrupted turn/end from the cancel closure ----
    s2 = fresh_session(conn)
    turn2 = u()
    append_public(conn, s2, [semantic_entry(
        "turn/start", turn2, {"origin": "user"},
        ordinal=next_ordinal(conn, s2))])
    exec_sql(conn, "UPDATE sessions SET state='waiting_event'"
                   " WHERE session_id=%s", (s2,))
    rcx = request_cancel(conn, s2, f"cxl-{u()[:8]}", DRIVER_C, 1)
    check("row 7 request_cancel accepted", rcx["outcome"] == "accepted", rcx)
    ends2 = events_of_type(conn, s2, "turn/end")
    check("row 7 turn/end {interrupted:true} generated by cancel closure",
          len(ends2) == 1
          and json.loads(ends2[0][2]).get("interrupted") is True, ends2)

    # ---- row 3: assistant token/chunk via the public facade with the
    #      stub grants (X03 direct-inserted grants surface) ----
    s3 = fresh_session(conn)
    with conn.cursor() as cur:
        turn3, step3, batch3, effect3 = u(), u(), u(), u()
        cur.execute(
            "INSERT INTO steps(step_id, session_id, turn_id, status, stage)"
            " VALUES (%s, %s, %s, 'waiting_effect', 'decision')",
            (step3, s3, turn3))
        cur.execute(
            "INSERT INTO batches(batch_id, session_id, step_id,"
            " sealed_batch_no, kind, sealed) VALUES (%s, %s, %s, 1,"
            " 'decision', true)", (batch3, s3, step3))
        cur.execute(
            "INSERT INTO effect_requests(effect_id, session_id, step_id,"
            " batch_id, dispatch_ordinal, effect_kind, execution_mode,"
            " driver, driver_epoch, session_fence, dispatch_session_fence,"
            " current_job_fence, request_hash, idempotency_key, status,"
            " retry_class, max_attempts, grant_id)"
            " VALUES (%s, %s, %s, %s, 0, 'llm_decision', 'streaming', %s,"
            " 1, 1, 1, 1, 'rh', 'ik', 'dispatch_started', 'unsafe', 1, %s)",
            (effect3, s3, step3, batch3, DRIVER_C,
             "g13-grant-stream-ingest"))
        cur.execute(
            "INSERT INTO effect_attempts(effect_id, attempt_no, session_id,"
            " step_id, dispatch_job_fence, driver, driver_epoch,"
            " session_fence, dispatch_session_fence, request_hash,"
            " idempotency_key, execution_mode, status)"
            " VALUES (%s, 1, %s, %s, 1, %s, 1, 1, 1, 'rh', 'ik',"
            " 'streaming', 'dispatch_started')",
            (effect3, s3, step3, DRIVER_C))
    conn.commit()
    chunk = raw_entry("assistant/chunk", {"text": "tok"},
                      effect_id=effect3, attempt_no=1, stream_id="sm1",
                      chunk_index=0)
    rchunk = append_public(conn, s3, [chunk], caller_subject=DRIVER_C,
                           caller_driver=DRIVER_C, caller_epoch=1)
    check("row 3 assistant/chunk accepted with the seeded dual grants"
          " (item 3+6 conjunction)",
          rchunk["outcome"] == "accepted", rchunk)
    check("row 3 chunk persisted as observational",
          events_of_type(conn, s3, "assistant/chunk")[0][1]
          == "observational")

    # Negative: same shape but the caller subject holds event_append only
    # (no stream_ingest) -> the dual-grant conjunction refuses.
    s4 = fresh_session(conn)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO grants(grant_id, workspace_id, slice_id,"
            " subject_kind, subject_id, capability, expires_at)"
            " VALUES ('x-grant-ea-only', %s, %s, 'driver', 'dsh-noingest',"
            " 'event_append', now() + interval '1 hour')",
            ("00000013-0013-4013-8013-000000000013",
             "00000013-0013-4013-8013-000000000101"))
        turn4, step4, batch4, effect4 = u(), u(), u(), u()
        cur.execute(
            "INSERT INTO steps(step_id, session_id, turn_id, status, stage)"
            " VALUES (%s, %s, %s, 'waiting_effect', 'decision')",
            (step4, s4, turn4))
        cur.execute(
            "INSERT INTO batches(batch_id, session_id, step_id,"
            " sealed_batch_no, kind, sealed) VALUES (%s, %s, %s, 1,"
            " 'decision', true)", (batch4, s4, step4))
        cur.execute(
            "INSERT INTO effect_requests(effect_id, session_id, step_id,"
            " batch_id, dispatch_ordinal, effect_kind, execution_mode,"
            " driver, driver_epoch, session_fence, dispatch_session_fence,"
            " current_job_fence, request_hash, idempotency_key, status,"
            " retry_class, max_attempts, grant_id)"
            " VALUES (%s, %s, %s, %s, 0, 'llm_decision', 'streaming', %s,"
            " 1, 1, 1, 1, 'rh', 'ik', 'dispatch_started', 'unsafe', 1, %s)",
            (effect4, s4, step4, batch4, "dsh-noingest", "x-grant-ea-only"))
        cur.execute(
            "INSERT INTO effect_attempts(effect_id, attempt_no, session_id,"
            " step_id, dispatch_job_fence, driver, driver_epoch,"
            " session_fence, dispatch_session_fence, request_hash,"
            " idempotency_key, execution_mode, status)"
            " VALUES (%s, 1, %s, %s, 1, %s, 1, 1, 1, 'rh', 'ik',"
            " 'streaming', 'dispatch_started')",
            (effect4, s4, step4, "dsh-noingest"))
    conn.commit()
    chunk4 = raw_entry("assistant/chunk", {"text": "tok"},
                       effect_id=effect4, attempt_no=1, stream_id="sm2",
                       chunk_index=0)
    rchunk4 = append_public(conn, s4, [chunk4], caller_subject="dsh-noingest",
                            caller_driver="dsh-noingest", caller_epoch=1)
    check("row 3 negative: caller without stream_ingest ->"
          " CHUNK_ATTRIBUTION_INVALID (zero events)",
          rchunk4["outcome"] == "rejected_mismatch"
          and rchunk4["code"] == "CHUNK_ATTRIBUTION_INVALID"
          and one(conn, "SELECT count(*) FROM session_events"
                        " WHERE session_id=%s"
                        " AND event_type='assistant/chunk'", (s4,))[0] == 0,
          rchunk4)

    # ---- row 4: stream_progress ONLY through complete_effect
    #      (non-final path) ----
    fxs = compat_decision_fx(conn, execution_mode="streaming")
    rs = complete_effect(
        conn, fxs["session"], f"cmp-{u()[:8]}", fxs["effect"], DRIVER_C, 1,
        dispatch_session_fence=2, job_fence=fxs["job_fence"],
        step_id=fxs["step"], request_hash=fxs["rh"],
        idempotency_key=fxs["ik"], outcome="succeeded",
        message={"text": "partial"}, tools=[], decision_only=True,
        final_tools=False,
        evidence={"class": "known_success",
                  "provider_receipt": {"receipt_id": f"pr-{u()[:8]}"}},
        result_payload={**build_result_payload({"text": "partial"}, [],
                                               True, False),
                        "stream_complete": False})
    check("row 4 stream_complete=false -> pending observation accepted",
          rs["outcome"] == "accepted", rs)
    prog = events_of_type(conn, fxs["session"], "stream_progress")
    check("row 4 stream_progress generated internally by complete_effect",
          len(prog) == 1 and prog[0][1] == "observational", prog)

    # ---- rows 8/9: tool/call via seal, tool/result via completion ----
    st = compat_tools_fx(conn)
    calls = events_of_type(conn, st["session"], "tool/call")
    check("row 8 tool/call generated by the controlled seal path",
          len(calls) == 1 and calls[0][1] == "semantic"
          and json.loads(calls[0][2]).get("tool") == "fake_tool", calls)
    rtool = complete_tool_effect(
        conn, st["session"], f"cmp-{u()[:8]}", st["effects"][0]["effect_id"],
        DRIVER_C, 1, st["seal_fence"], st["effects"][0]["job_fence"],
        step_id=st["step"], request_hash=st["effects"][0]["request_hash"],
        idempotency_key=st["effects"][0]["idempotency_key"],
        outcome="succeeded", tool_call_id=st["effects"][0]["tool_call_id"],
        output={"echo": "ok"},
        evidence={"class": "known_success",
                  "provider_receipt": {"receipt_id": f"pr-{u()[:8]}"}})
    check("row 9 tool completion accepted", rtool["outcome"] == "accepted",
          rtool)
    tresults = events_of_type(conn, st["session"], "tool/result")
    check("row 9 tool/result generated by complete_effect",
          len(tresults) == 1 and tresults[0][1] == "semantic", tresults)

    # ---- row 14: load()-synthesized closers MUST walk the shared repair
    #      (a tool effect settled unknown then repaired) ----
    su = compat_tools_fx(conn)
    runk = complete_tool_effect(
        conn, su["session"], f"cmp-{u()[:8]}", su["effects"][0]["effect_id"],
        DRIVER_C, 1, su["seal_fence"], su["effects"][0]["job_fence"],
        step_id=su["step"], attempt_no=1,
        request_hash=su["effects"][0]["request_hash"],
        idempotency_key=su["effects"][0]["idempotency_key"],
        outcome="failed_retryable",
        tool_call_id=su["effects"][0]["tool_call_id"],
        output={"error": "provider_error"},
        evidence={"class": "provider_error"})
    check("row 14 unknown tool settlement accepted",
          runk["outcome"] == "accepted", runk)
    head = slot_head(conn, su["session"])
    rrep = repair(
        conn, su["session"], f"rpr-{u()[:8]}", su["effects"][0]["effect_id"],
        1, driver=DRIVER_C, driver_epoch=1, supersedes_event_key=head,
        evidence={"class": "known_success",
                  "provider_receipt": {"receipt_id": f"pr-{u()[:8]}"}},
        resolution_kind="succeeded",
        tool_call_id=su["effects"][0]["tool_call_id"],
        output={"echo": "late-ok"})
    check("row 14 shared repair accepted", rrep["outcome"] == "accepted",
          rrep)
    tclose = events_of_type(conn, su["session"], "tool/result")
    check("row 14 tool/result closer written by the shared repair",
          len(tclose) == 1
          and json.loads(tclose[0][2]).get("closer"), tclose)

    # rows 12/13/15/16 negative halves are covered by the RESTRICTED_TYPES
    # loop above; the internal paths are reporter-level partials (gaps).
    RESULTS["c10-db-s5-mapping"] = "passed"
    RESULTS["c1-db-occurrence-identity"] = "passed"
    RESULTS["c14-db-grant-denied"] = "passed"


def compat_tools_fx(conn):
    """decision with a one-tool plan -> successful final_tools decision ->
    tools seal -> dispatch the tool effect (compat driver)."""
    s = fresh_session(conn)
    turn = u()
    seed = u()[:8]
    plan = [{"tool_call_id": f"call-{seed}-0", "tool": "fake_tool",
             "arguments": {"echo": seed}}]
    step, deff = u(), u()
    rh, ik = f"rh-{u()[:10]}", f"ik-{u()[:10]}"
    r0 = claim_session(conn, s, DRIVER_C)
    rs = prepare_step(conn, s, f"seal-{u()[:8]}", DRIVER_C, 1,
                      r0["session_fence"], step, turn, deff,
                      request_hash=rh, idempotency_key=ik)
    check("tools fx decision seal accepted", rs["outcome"] == "accepted", rs)
    rd = dispatch_effect(conn, s, f"dsp-{u()[:8]}", deff, DRIVER_C, 1,
                         rs["receipt"]["session_fence"],
                         rs["receipt"]["job_fence"])
    check("tools fx dispatch accepted", rd["outcome"] == "accepted", rd)
    rc = complete_effect(
        conn, s, f"cmp-{u()[:8]}", deff, DRIVER_C, 1,
        dispatch_session_fence=2, job_fence=rs["receipt"]["job_fence"],
        step_id=step, request_hash=rh, idempotency_key=ik,
        outcome="succeeded", message={"text": f"plan:{seed}"}, tools=plan,
        decision_only=False, final_tools=True,
        evidence={"class": "known_success",
                  "provider_receipt": {"receipt_id": f"pr-{u()[:8]}"}})
    check("tools fx decision complete accepted", rc["outcome"] == "accepted",
          rc)
    dec_event_key = next(e["event_key"] for e in rc["receipt"]["events"]
                         if e["event_type"] == "assistant/message")
    plan_hash = one(conn, "SELECT plan_hash FROM steps WHERE step_id=%s",
                    (step,))[0]
    r1 = claim_session(conn, s, DRIVER_C)
    seal_fence = r1["session_fence"]
    from v8.tools.client import build_tool_slots
    slots = build_tool_slots(plan, retry_class="verifiable_no_effect",
                             max_attempts=2)
    rseal = seal_batch(
        conn, s, f"tseal-{u()[:8]}", DRIVER_C, 1, seal_fence, step, 1,
        {"effect_id": deff, "attempt_no": 1,
         "result_hash": rc["receipt"]["result_hash"],
         "event_key": dec_event_key},
        plan_hash, slots)
    check("tools fx tools seal accepted", rseal["outcome"] == "accepted",
          rseal)
    by_ordinal = {e["dispatch_ordinal"]: e
                  for e in rseal["receipt"]["effects"]}
    effects = []
    for i in range(len(slots)):
        e = by_ordinal[i]
        rd = dispatch_effect(conn, s, f"dsp-{u()[:8]}", e["effect_id"],
                             DRIVER_C, 1, seal_fence + 1, e["job_fence"])
        check(f"tools fx tool {i} dispatch accepted",
              rd["outcome"] == "accepted", rd)
        effects.append({"effect_id": e["effect_id"],
                        "tool_call_id": slots[i]["tool_call_id"],
                        "request_hash": slots[i]["request_hash"],
                        "idempotency_key": slots[i]["idempotency_key"],
                        "job_fence": e["job_fence"]})
    return {"session": s, "turn": turn, "step": step, "effects": effects,
            "seal_fence": seal_fence, "post_seal_fence": seal_fence + 1}


# ---------------------------------------------------------------------------
# 4. Conformance 11 (a): fork cutoff, three assertions
# ---------------------------------------------------------------------------

def test_fork_cutoff(conn) -> None:
    # Assertion 1: unresolved unknown within the cutoff -> fork refused.
    fx1 = compat_decision_fx(conn)
    ru = compat_unknown_decision(conn, fx1)
    check("fork fx1 unknown settlement accepted",
          ru["outcome"] == "accepted", ru)
    seq_end = one(conn, "SELECT max(seq) FROM session_events"
                        " WHERE session_id=%s", (fx1["session"],))[0]
    before = session_row(conn, fx1["session"])
    child = u()
    rf1 = compat.fork(conn, fx1["session"], seq_end, child_session_id=child)
    check("assertion 1: unresolved unknown -> FORK_CUTOFF_UNSTABLE",
          rf1["outcome"] == "rejected_mismatch"
          and rf1["code"] == "FORK_CUTOFF_UNSTABLE", rf1)
    check("assertion 1: parent control state untouched",
          session_row(conn, fx1["session"]) == before)
    check("assertion 1: no child session created",
          one(conn, "SELECT count(*) FROM sessions WHERE session_id=%s",
              (child,))[0] == 0)

    # Assertion 2: fully repaired prefix -> child created, canonical trace
    # without the provisional unknown representation.
    fx2 = compat_decision_fx(conn)
    compat_unknown_decision(conn, fx2)
    rrep = compat_repair_success(conn, fx2)
    check("fork fx2 repair accepted", rrep["outcome"] == "accepted", rrep)
    seq_end2 = one(conn, "SELECT max(seq) FROM session_events"
                         " WHERE session_id=%s", (fx2["session"],))[0]
    child2 = u()
    rf2 = compat.fork(conn, fx2["session"], seq_end2,
                      child_session_id=child2)
    check("assertion 2: repaired prefix fork accepted",
          rf2["outcome"] == "accepted"
          and rf2["inherited_event_count"] == seq_end2, rf2)
    check("assertion 2: child inherits no control state (no steps/effects)",
          one(conn, "SELECT (SELECT count(*) FROM steps WHERE session_id=%s),"
                    " (SELECT count(*) FROM effect_requests"
                    " WHERE session_id=%s)", (child2, child2)) == (0, 0))
    inherited = one(conn, "SELECT count(*) FROM session_events"
                          " WHERE session_id=%s", (child2,))[0]
    check("assertion 2: child event prefix == parent seq <= cutoff",
          inherited == seq_end2, (inherited, seq_end2))
    trace2 = normalize(trace_events(conn, child2), CV)
    unknown_ends = [e for e in trace2 if e["event_type"] == "turn/end"
                    and e["payload"].get("outcome") == "unknown"]
    check("assertion 2: child canonical trace has no provisional unknown"
          " representation", not unknown_ends, trace2)

    # Parent appends after the fork never change the child's fixed cutoff.
    turn_new = u()
    append_public(conn, fx2["session"], [semantic_entry(
        "user/message", turn_new, {"text": "post-fork"},
        ordinal=10_000_000)])
    check("post-fork parent append leaves the child prefix unchanged",
          one(conn, "SELECT count(*) FROM session_events"
                    " WHERE session_id=%s", (child2,))[0] == inherited)

    # Assertion 3: parent repaired AFTER the cutoff -> still refused.
    fx3 = compat_decision_fx(conn)
    compat_unknown_decision(conn, fx3)
    prov_seq = one(
        conn, "SELECT seq FROM session_events WHERE session_id=%s"
              " AND event_type='turn/end' ORDER BY seq DESC LIMIT 1",
        (fx3["session"],))[0]
    compat_repair_success(conn, fx3)
    rf3 = compat.fork(conn, fx3["session"], prov_seq)
    check("assertion 3: cutoff before the parent repair ->"
          " FORK_CUTOFF_UNSTABLE",
          rf3["outcome"] == "rejected_mismatch"
          and rf3["code"] == "FORK_CUTOFF_UNSTABLE", rf3)

    RESULTS["c11-db-fork-cutoff"] = "passed"


# ---------------------------------------------------------------------------
# 5. Conformance 11 (c): mandatory UNSUPPORTED negative
# ---------------------------------------------------------------------------

def test_switch_negative(conn) -> None:
    s = fresh_session(conn)          # driver dsh-compat -> unsupported
    before = session_row(conn, s)
    cmd = f"bsw-{u()[:10]}"
    r = compat.begin_switch(conn, s, cmd, DRIVER_C, 1)
    check("unsupported driver: begin_switch -> UNSUPPORTED",
          r["outcome"] == "rejected_mismatch" and r["code"] == "UNSUPPORTED",
          r)
    check("unsupported driver: mode/fence/switch intent unchanged",
          session_row(conn, s) == before)
    r2 = compat.begin_switch(conn, s, cmd, DRIVER_C, 1)
    check("UNSUPPORTED refusal replays idempotently",
          r2["outcome"] == "rejected_mismatch"
          and r2["code"] == "UNSUPPORTED", r2)

    # A83 convergence (G18): a supported declaration ROUTES into the shared
    # reconcile implementation — no stage-local SWITCH_PROTOCOL_NOT_IMPLEMEN
    # TED stub remains. Without a lease the shared core refuses (proof of
    # the routing: the receipt is the shared core's, not a stage stub).
    sp = fresh_session(conn, driver="dsh-compat-probe")
    before_p = session_row(conn, sp)
    rp = compat.begin_switch(conn, sp, f"bsw-{u()[:10]}", "dsh-compat-probe",
                             1)
    check("supported driver without a lease -> the shared core's"
          " NO_VALID_LEASE (routed, zero mutation)",
          rp["outcome"] == "rejected_stale"
          and rp["code"] == "NO_VALID_LEASE"
          and session_row(conn, sp) == before_p, rp)

    # With the lease held, the shared core executes the real begin:
    # quiescing entered, the switch intent persisted, fence advanced.
    rc = claim_session(conn, sp, "dsh-compat-probe", 1,
                       lease_owner="compat-op")
    rp2 = compat.begin_switch(conn, sp, f"bsw-{u()[:10]}", "dsh-compat-probe",
                              1, target_driver="dsh-compat-next",
                              lease_owner="compat-op")
    check("supported driver + lease -> real begin_switch through the shared"
          " core (accepted, quiescing)",
          rp2["outcome"] == "accepted"
          and one(conn, "SELECT driver_mode, session_fence, lease_owner"
                        " FROM sessions WHERE session_id=%s", (sp,))
          == ("quiescing", rc["session_fence"] + 1, None), rp2)
    check("the switch intent persisted through the shared core",
          one(conn, "SELECT count(*) FROM session_switch_intents"
                    " WHERE session_id=%s", (sp,))[0] == 1)

    # A driver without a compat manifest declaration has no switch surface.
    sn = fresh_session(conn, driver="native-drv")
    rn = compat.begin_switch(conn, sn, f"bsw-{u()[:10]}", "native-drv", 1)
    check("undeclared driver -> DRIVER_MANIFEST_MISSING",
          rn["outcome"] == "rejected_mismatch"
          and rn["code"] == "DRIVER_MANIFEST_MISSING", rn)

    RESULTS["c11-db-unsupported-negative"] = "passed"


# ---------------------------------------------------------------------------
# 6. capability matrix logic + the GUC seam
# ---------------------------------------------------------------------------

DISPATCH_ROWS = set(p0c_report.DISPATCH_REAL_ROWS)


def test_matrix_logic(conn) -> None:
    m = compat.matrix_blocked(conn, "sync_before_io", "supported")
    check("sync+supported: no blocked subcases",
          set(m["blocked"]) == set() and m["mandated_negative"] == [], m)

    m = compat.matrix_blocked(conn, "sync_before_io", "unsupported")
    check("sync+unsupported: ONLY the clause-11 positive blocked,"
          " mandated negative required",
          set(m["blocked"]) == {"c11-db-switch-positive"}
          and set(m["mandated_negative"]) == {"c11-db-unsupported-negative"},
          m)

    for dim in ("after_io_only", "none"):
        m = compat.matrix_blocked(conn, dim, "supported")
        check(f"{dim}+supported: exactly the dispatch-dimension rows blocked",
              set(m["blocked"]) == DISPATCH_ROWS
              and m["mandated_negative"] == [], m)

    for dim in ("after_io_only", "none"):
        m = compat.matrix_blocked(conn, dim, "unsupported")
        check(f"{dim}+unsupported: union of both dimensions",
              set(m["blocked"]) == DISPATCH_ROWS | {"c11-db-switch-positive"}
              and set(m["mandated_negative"])
              == {"c11-db-unsupported-negative"}, m)

    m = compat.matrix_blocked(conn, "who-knows", "supported")
    check("unknown dispatch value IS none",
          set(m["blocked"]) == DISPATCH_ROWS, m)
    m = compat.matrix_blocked(conn, None, "supported")
    check("NULL dispatch value IS none",
          set(m["blocked"]) == DISPATCH_ROWS, m)

    # Participation of the seeded pinned manifest (unresolved dispatch).
    p = compat.participation(conn, ADAPTER)
    check("pinned manifest: dispatch unresolved, effective none,"
          " dispatch rows blocked",
          p["dispatch_unresolved"] is True
          and p["dispatch_interception_effective"] == "none"
          and set(p["matrix"]["blocked"])
          == DISPATCH_ROWS | {"c11-db-switch-positive"}, p)

    # GUC seam: overrides the matrix-logic inputs ONLY (transaction-local).
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('v8.compat_dispatch_interception',"
                    " 'sync_before_io', true)")
        p2 = compat.participation(conn, ADAPTER)
    conn.rollback()
    check("GUC seam drives matrix logic (sync override unblocks the"
          " dispatch rows)",
          p2["dispatch_interception_effective"] == "sync_before_io"
          and "v8.compat_dispatch_interception"
          in p2["guc_overrides_used"]
          and set(p2["matrix"]["blocked"]) == {"c11-db-switch-positive"},
          p2)
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('v8.compat_dispatch_interception',"
                    " 'gibberish', true)")
        p3 = compat.participation(conn, ADAPTER)
    conn.rollback()
    check("GUC seam ignores non-enum values (falls back to the manifest)",
          p3["dispatch_interception_effective"] == "none"
          and p3["guc_overrides_used"] == [], p3)
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('v8.compat_driver_switch',"
                    " 'supported', true)")
        p4 = compat.participation(conn, ADAPTER)
    conn.rollback()
    check("driver-switch GUC seam drives the switch dimension only",
          p4["driver_switch"] == "supported"
          and set(p4["matrix"]["blocked"]) == DISPATCH_ROWS, p4)
    # The seam cannot mark real-I/O rows green: participation returns
    # blocked sets only, and even a sync override leaves the real rows
    # non-passable while no real compat loop exists (reporter fail-classes
    # 4/5 enforce this — asserted in the reporter section).
    check("GUC seam exposes no green path (blocked sets only)",
          isinstance(p2["matrix"].get("blocked"), list)
          and "green" not in p2["matrix"])

    RESULTS["c16-db-matrix-logic"] = "passed"


# ---------------------------------------------------------------------------
# 7. must-run fake suite + the opt-in real-provider smoke (J0 W1)
# ---------------------------------------------------------------------------

def test_fake_provider() -> None:
    """The MUST-RUN fake suite (Conformance 12) — independent of any
    provider credential since J0: two fresh FakeLLM instances, a fixed
    seed input, full-object equality. The result is registered only
    after the check succeeds; a failure raises immediately (never a
    pre-registered green, never swallowed)."""
    fa = FakeLLM().generate({"prompt": {"seed_text": "s"}})
    fb = FakeLLM().generate({"prompt": {"seed_text": "s"}})
    check("fake suite stays deterministic and authoritative", fa == fb)
    RESULTS["c12-db-fake-suite"] = "passed"


@dataclass(frozen=True)
class SmokeOutcome:
    """The immutable smoke result: state in {passed, failed, not_run},
    reason in {none, not_requested, credentials_absent,
    provider_failure}. provider_failure classifies the raising path — a
    started smoke that fails never returns; its failure is kept in
    RESULTS and the exception propagates (exit 1)."""

    state: str
    reason: str


def test_real_provider_smoke(conn, *, requested: bool) -> SmokeOutcome:
    """The opt-in real-provider (DeepSeek) DB protocol smoke. Default
    (requested=False): the real adapter is NEVER constructed — no
    credential is read, checked, or printed (J0 plan §4.3)."""
    if not requested:
        RESULTS[SMOKE_SUBCASE] = "not_run"
        NOT_RUN_REASONS[SMOKE_SUBCASE] = "not_requested"
        print("[SKIP] real-provider smoke not requested (default keyless; "
              "pass --real-provider-smoke to opt in)")
        return SmokeOutcome("not_run", "not_requested")

    adapter = DeepSeekLLM()
    if not adapter.credentials_present:
        RESULTS[SMOKE_SUBCASE] = "not_run"
        NOT_RUN_REASONS[SMOKE_SUBCASE] = "credentials_absent"
        EXTERNAL_BLOCKED.add("blocked:real-provider-credentials")
        print("[SKIP] --real-provider-smoke requested but credentials "
              "absent (DEEPSEEK_API_KEY / OPENAI_API_KEY) — the explicit "
              "target did not execute, exit 2; generate() was never "
              "called")
        return SmokeOutcome("not_run", "credentials_absent")

    try:
        # Protocol assertions may contain response objects as detail. Never
        # emit these in stdout/stderr, even on a failed assertion.
        import os
        with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink), \
                contextlib.redirect_stderr(sink):
            _real_smoke_body(conn, adapter)
    except Exception:
        # A started smoke that fails keeps its failure (never swallowed,
        # never downgraded to not_run). Only the safe state summary is
        # recorded here; the exception itself propagates (exit 1) — no
        # real response/request text may leak through this handler.
        RESULTS[SMOKE_SUBCASE] = "failed"
        raise RuntimeError("real-provider smoke failed") from None
    RESULTS[SMOKE_SUBCASE] = "passed"
    return SmokeOutcome("passed", "none")


def _real_smoke_body(conn, adapter: DeepSeekLLM) -> None:
    """The three real sub-cases (protocol shape / idempotency / the
    uncertain window) plus their DB settlement halves. All real calls
    happen outside any open database transaction."""
    conn.rollback()
    status_before = conn.status
    check("real provider call point: connection idle (no open tx)",
          status_before == 1, status_before)

    # (1) protocol shape.
    r1 = adapter.generate({"prompt": {"seed_text": "compat protocol probe"}})
    check("protocol shape: openai-compatible envelope mapped to the "
          "EffectResult classification inputs",
          r1["outcome"] == "succeeded"
          and r1["evidence"]["class"] == "known_success"
          and r1["evidence"]["provider_receipt"]["protocol"]
          == "openai-compatible/chat.completions"
          and r1["evidence"]["provider_receipt"]["receipt_id"]
          and r1["evidence"]["provider_receipt"]["finish_reason"] is not None
          and isinstance(r1["evidence"]["provider_receipt"]["usage"], dict),
          r1)
    check("connection still idle after the real call", conn.status == 1)

    # DB half: the real evidence settles known_success through the
    # compat-driver completion facade (the adapter envelope maps into the
    # standard EffectResult shape).
    fx = compat_decision_fx(conn)
    rc = complete_effect(
        conn, fx["session"], f"cmp-{u()[:10]}", fx["effect"], DRIVER_C, 1,
        dispatch_session_fence=2, job_fence=fx["job_fence"],
        step_id=fx["step"], request_hash=fx["rh"], idempotency_key=fx["ik"],
        outcome="succeeded", message=r1["message"], tools=[],
        decision_only=True, final_tools=False,
        evidence=r1["evidence"],
        result_payload=build_result_payload(r1["message"], [], True, False))
    check("protocol shape: real-evidence completion accepted (DB layer)",
          rc["outcome"] == "accepted"
          and rc["receipt"]["classification"] == "known_success", rc)

    # (2) idempotency: two identical wire requests both produce
    # well-formed envelopes; the DATABASE side keeps one settlement per
    # command_id (receipt replay).
    conn.rollback()
    check("second provider call is outside a transaction", conn.status == 1)
    r2 = adapter.generate({"prompt": {"seed_text":
                                      "compat protocol probe"}})
    check("idempotency: identical request re-issued yields a well-formed "
          "envelope", r2["outcome"] == "succeeded"
          and r2["evidence"]["provider_receipt"]["receipt_id"], r2)
    check("second provider returned outside a transaction", conn.status == 1)
    fx2 = compat_decision_fx(conn)
    cmd = f"cmp-{u()[:10]}"
    ca = complete_effect(
        conn, fx2["session"], cmd, fx2["effect"], DRIVER_C, 1,
        dispatch_session_fence=2, job_fence=fx2["job_fence"],
        step_id=fx2["step"], request_hash=fx2["rh"],
        idempotency_key=fx2["ik"], outcome="succeeded",
        message=r2["message"], tools=[], decision_only=True,
        final_tools=False, evidence=r2["evidence"],
        result_payload=build_result_payload(r2["message"], [], True, False))
    cb = complete_effect(
        conn, fx2["session"], cmd, fx2["effect"], DRIVER_C, 1,
        dispatch_session_fence=2, job_fence=fx2["job_fence"],
        step_id=fx2["step"], request_hash=fx2["rh"],
        idempotency_key=fx2["ik"], outcome="succeeded",
        message=r2["message"], tools=[], decision_only=True,
        final_tools=False, evidence=r2["evidence"],
        result_payload=build_result_payload(r2["message"], [], True, False))
    check("idempotency: same command_id replays one settlement",
          cb["outcome"] == "accepted"
          and one(conn, "SELECT count(*) FROM session_events"
                        " WHERE session_id=%s"
                        " AND event_type='assistant/message'",
                 (fx2["session"],))[0] == 1, cb)

    # (3) uncertain window: a real call abandoned before any terminal
    # receipt classifies unknown (provisional end, blocked session).
    conn.rollback()
    check("uncertain call is outside a transaction", conn.status == 1)
    abandoned = DeepSeekLLM(abandon_after=0.001)
    r3 = abandoned.generate({"prompt": {"seed_text": "compat window probe"}})
    check("uncertain window: abandoned call yields the unknown shape "
          "(no bound terminal provider receipt)",
          r3["outcome"] == "unknown_outcome"
          and r3["evidence"]["class"] == "timeout", r3)
    check("uncertain call returned outside a transaction", conn.status == 1)
    fx3 = compat_decision_fx(conn)
    rc3 = complete_effect(
        conn, fx3["session"], f"cmp-{u()[:10]}", fx3["effect"], DRIVER_C, 1,
        dispatch_session_fence=2, job_fence=fx3["job_fence"],
        step_id=fx3["step"], request_hash=fx3["rh"],
        idempotency_key=fx3["ik"], outcome="failed_retryable",
        message={"text": ""}, tools=[], decision_only=True,
        final_tools=False, evidence=r3["evidence"],
        result_payload=r3["result_payload"])
    ends3 = events_of_type(conn, fx3["session"], "turn/end")
    check("uncertain window: DB classification unknown + provisional end",
          rc3["outcome"] == "accepted"
          and rc3["receipt"]["classification"] == "unknown"
          and len(ends3) == 1
          and json.loads(ends3[0][2]).get("outcome") == "unknown",
          (rc3["receipt"].get("classification"), ends3))


# ---------------------------------------------------------------------------
# 8. P0C reporter (schema v2): precise-code refusals + conclusions
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def synthetic_catalog(catalog):
    """TEST ONLY: formula vectors are never returned as actual evidence."""
    from unittest.mock import patch
    with patch.object(p0c_report, "CATALOG", catalog), patch.object(
            p0c_report, "BY_ID", {s.subcase_id: s for s in catalog}):
        yield


def refusal(code, fn):
    try:
        fn()
    except p0c_report.ReportError as exc:
        check(f"precise refusal {code}", exc.code == code, exc.code)
    else:
        check(f"precise refusal {code}", False, "no refusal")


def test_reporter(conn) -> dict:
    p = p0c_report
    matrix = compat.participation(conn, ADAPTER)["matrix"]
    results = dict(RESULTS)
    options = dict(external_blocked=frozenset(EXTERNAL_BLOCKED),
                   not_run_reasons=dict(NOT_RUN_REASONS))

    def build(r=None, m=None, **kw):
        return p.build_report(results if r is None else r,
                              matrix if m is None else m, **(options | kw))

    report = build()
    check("honest report: no failures or synthetic unmapped fixture",
          report["counts"]["failed"] == 0
          and not report["unmapped_failed_fixtures"])
    check("all clauses represented (4 merged into 3)",
          {r["clause"] for r in report["rows"]} >= set(range(1, 17)) - {4})
    check("mandatory fork and UNSUPPORTED negative passed",
          all(r["state"] == "passed" for r in report["rows"]
              if r["subcase"] in (p.FORK_DB_ROW, p.MANDATED_NEGATIVE)))
    check("real layer blocked, unimplemented gaps retained",
          all(r["state"] == "blocked" for r in report["rows"]
              if r["boundary"] == p.REAL)
          and all(r["gap"] for r in report["rows"] if r["state"] == p.PARTIAL))
    check("pinned unresolved: all actual conclusions false; no final signature",
          bool(report["pinned_unresolved"])
          and not any(c["passed"] for c in report["conclusions"].values())
          and report["compat_contract_passed"] is False
          and report["compat_contract_passable"] is False)
    demo = build(unmapped_failed_fixtures=("fx-unmapped-demo",))
    check("unmapped demo blocks conclusion, separate from actual report",
          "unmapped_failed_fixtures" in demo["conclusions"][
              "full_target_achieved"]["blockers"])

    audit = "c16-db-unmapped-audit"
    real = "c1-real-retry-single-batch"
    dropped = {k: v for k, v in results.items() if k != audit}
    refusal(p.INVALID_BLOCK_SOURCE, lambda: build(
        external_blocked=frozenset({"blocked:invented-source"})))
    refusal(p.MISSING_RESULT, lambda: build(dropped))
    refusal(p.NATIVE_EVIDENCE_AS_COMPAT, lambda: build(
        native_evidence_only=frozenset({audit})))
    # Isolate FC4/FC5 from the earlier unimplemented-pass check. Only this
    # test-local target is implemented; the production catalog is untouched.
    with synthetic_catalog([replace(s, implemented=True) if s.subcase_id == real
                            else s for s in p.CATALOG]):
        refusal(p.BLOCKED_REAL_MARKED_PASSED, lambda: build(
            results | {real: p.PASSED}, real_loop_available=True))
        sync = compat.matrix_blocked(conn, "sync_before_io", "supported")
        refusal(p.REAL_PASS_WITHOUT_LOOP, lambda: build(
            results | {real: p.PASSED}, sync,
            external_blocked=frozenset(EXTERNAL_BLOCKED - {
                "blocked:all-real-io-subcases"})))
    unsup = compat.matrix_blocked(conn, "sync_before_io", "unsupported")
    refusal(p.MANDATORY_NEGATIVE_NOT_PASSED, lambda: build(
        results | {p.MANDATED_NEGATIVE: p.FAILED}, unsup))
    refusal(p.MISSING_RESULT, lambda: build(
        {k: v for k, v in results.items() if k != p.MANDATED_NEGATIVE}, unsup))
    refusal(p.INVALID_RESULT_ID, lambda: build(results | {"unknown": p.PASSED}))
    refusal(p.INVALID_RESULT_STATE, lambda: build(results | {audit: "blocked"}))
    refusal(p.UNIMPLEMENTED_MARKED_PASSED, lambda: build(
        results | {real: p.PASSED}))
    refusal(p.INVALID_NOT_RUN_REASON, lambda: build(
        results | {audit: p.NOT_RUN}))
    for reason in ("not_requested", "credentials_absent", "unknown"):
        refusal(p.INVALID_NOT_RUN_REASON, lambda: build(
            results | {audit: p.NOT_RUN},
            not_run_reasons=NOT_RUN_REASONS | {audit: reason}))
    refusal(p.INVALID_NOT_RUN_REASON, lambda: build(
        not_run_reasons=NOT_RUN_REASONS | {audit: "execution_interrupted"}))
    # Dual-invalid vectors lock first-error-wins ordering.
    refusal(p.INVALID_NOT_RUN_REASON, lambda: build(
        dropped | {"c12-db-fake-suite": p.NOT_RUN}))
    refusal(p.MISSING_RESULT, lambda: build(
        dropped, native_evidence_only=frozenset({"c12-db-fake-suite"})))
    with synthetic_catalog(p.CATALOG + [p.CATALOG[0]]):
        refusal(p.INVALID_CATALOG, lambda: build())
    with synthetic_catalog([s for s in p.CATALOG if s.clause != 10]):
        refusal(p.MISSING_RESULT, lambda: build(
            {k: v for k, v in results.items() if k in p.BY_ID}))
    test_conclusion_formulas()
    check("compat-only fixture excluded from portable",
          compat.portable_claim_ok(conn, "drop-adapter@1", ["fx-drop-1"]) is False)
    print(p.render(report))
    return report


def test_conclusion_formulas():
    """Synthetic all-implemented vectors; not runtime participation evidence."""
    from unittest.mock import patch
    p = p0c_report
    with synthetic_catalog([replace(s, implemented=True) for s in p.CATALOG]), \
            patch.object(p, "pinned_unresolved_items", return_value=[]):
        results = {s.subcase_id: p.PASSED for s in p.CATALOG}
        results[SMOKE_SUBCASE] = p.NOT_RUN
        reasons = {SMOKE_SUBCASE: "not_requested"}
        matrix = {"blocked": [], "mandated_negative": []}

        def build(r=None, **kw):
            args = dict(real_loop_available=True, not_run_reasons=reasons)
            return p.build_report(results if r is None else r, matrix, **(args | kw))

        green = build()
        check("TEST ONLY all-implemented formula permits optional absence",
              all(c["passed"] for c in green["conclusions"].values())
              and green["compat_contract_passable"]
              and green["compat_contract_passed"] is False)
        for reason in sorted(p.NOT_RUN_REASONS):
            check(f"optional absence {reason} does not block formula",
                  build(not_run_reasons={SMOKE_SUBCASE: reason})[
                      "conclusions"]["full_target_achieved"]["passed"])
        sid = "c16-db-unmapped-audit"
        for state in (p.PARTIAL, p.NOT_RUN, p.FAILED):
            rr = reasons | ({sid: "dependency_unavailable"} if state == p.NOT_RUN else {})
            r = build(results | {sid: state}, not_run_reasons=rr)
            check(f"mandatory {state} blocks support/full, minimal is independent",
                  not r["conclusions"]["declared_support_surface_conformant"]["passed"]
                  and not r["conclusions"]["full_target_achieved"]["passed"]
                  and r["conclusions"]["minimal_dual_loop_passed"]["passed"])
        failed = build(results | {SMOKE_SUBCASE: p.FAILED}, not_run_reasons={})
        check("executed optional failure is not an absence",
              not failed["conclusions"]["full_target_achieved"]["passed"])
        matrix["blocked"] = [p.SWITCH_DB_ROW]
        matrix["mandated_negative"] = [p.MANDATED_NEGATIVE]
        reduced = build({k: v for k, v in results.items() if k != p.SWITCH_DB_ROW})
        check("unsupported positive blocked tolerable only for support surface",
              reduced["conclusions"]["declared_support_surface_conformant"]["passed"]
              and not reduced["conclusions"]["full_target_achieved"]["passed"])
        hidden = build(results | {p.SWITCH_DB_ROW: p.FAILED})
        check("explicit failure hidden by blocked display still blocks conclusion",
              not hidden["conclusions"]["declared_support_surface_conformant"]["passed"])
        rendered = p.render(reduced) + p.render(failed) + p.render(r)
        check("render understands five states and new conclusions",
              all(s in rendered for s in ("passed", "failed", "blocked", "partial", "not_run"))
              and "full target" in rendered)


# ---------------------------------------------------------------------------

def test_keyless_branches():
    """No DB/network: sentinels exercise orchestration, never a provider."""
    import io
    import os
    from unittest.mock import patch
    module = sys.modules[__name__]
    saved = (dict(RESULTS), dict(NOT_RUN_REASONS), set(EXTERNAL_BLOCKED))
    try:
        for key in ("", "sentinel-j0-never-send"):
            _reset_state()
            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": key,
                                         "OPENAI_API_KEY": key}), \
                    patch.object(module, "DeepSeekLLM", side_effect=AssertionError("live")), \
                    patch.object(FakeLLM, "generate", autospec=True,
                                 return_value={"full": [1, {"x": "same"}]}) as fake, \
                    patch("urllib.request.urlopen", side_effect=AssertionError("network")):
                test_fake_provider()
                outcome = test_real_provider_smoke(None, requested=False)
                check("keyless path: two fake calls, zero live, optional not requested",
                      fake.call_count == 2
                      and fake.call_args_list[0].args[0] is not fake.call_args_list[1].args[0]
                      and outcome == SmokeOutcome("not_run", "not_requested"))
        _reset_state()
        with patch.object(FakeLLM, "generate", side_effect=[{"x": 1}, {"x": 2}]), \
                contextlib.redirect_stdout(io.StringIO()):
            try:
                test_fake_provider()
            except AssertionError:
                pass
            else:
                raise AssertionError("unequal fake must fail")
        check("failed fake never registered green", "c12-db-fake-suite" not in RESULTS)
        with patch.object(module, "DeepSeekLLM") as adapter:
            adapter.return_value.credentials_present = False
            test_fake_provider()
            missing = test_real_provider_smoke(None, requested=True)
            check("requested absent credentials: no generate, fake still green",
                  missing == SmokeOutcome("not_run", "credentials_absent")
                  and not adapter.return_value.generate.called
                  and RESULTS["c12-db-fake-suite"] == "passed")
            adapter.return_value.credentials_present = True
            for fail in (False, True):
                _reset_state()
                with patch.object(module, "_real_smoke_body",
                                  side_effect=RuntimeError("sentinel-private-response") if fail else None):
                    try:
                        outcome = test_real_provider_smoke(None, requested=True)
                    except RuntimeError as exc:
                        check("started smoke fails safely, never downgraded",
                              fail and RESULTS[SMOKE_SUBCASE] == "failed"
                              and str(exc) == "real-provider smoke failed")
                    else:
                        check("fake adapter success branch registered", not fail and outcome.state == "passed")
        EXTERNAL_BLOCKED.add("blocked:real-provider-credentials")
        RESULTS["residue"] = "passed"
        _reset_state()
        check("per-run reset restores exactly initial six sources",
              not RESULTS and not NOT_RUN_REASONS
              and EXTERNAL_BLOCKED == set(INITIAL_EXTERNAL_BLOCKED))
        # Execute main twice with all DB work stubbed; assert actual CLI
        # exits, stale file removal, reset, closure and JSON atomic output.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
            for name in ("setup_db", "test_unmapped_audit", "test_manifest",
                         "test_s5_mapping", "test_fork_cutoff", "test_switch_negative",
                         "test_matrix_logic", "test_keyless_branches"):
                stack.enter_context(patch.object(module, name))
            stack.enter_context(patch.object(module, "uri", return_value="unused"))
            db = stack.enter_context(patch.object(psycopg2, "connect"))
            reporter = stack.enter_context(patch.object(module, "test_reporter",
                return_value={"report_schema_version": 2, "test_only": True}))
            adapter = stack.enter_context(patch.object(module, "DeepSeekLLM"))
            adapter.return_value.credentials_present = False
            target = Path(tmp) / "report.json"
            check("main explicit missing credentials exits 2",
                  main(["--real-provider-smoke", "--report-json", str(target)]) == 2)
            check("main default exits 0 after reset",
                  main(["--report-json", str(target)]) == 0
                  and "blocked:real-provider-credentials" not in EXTERNAL_BLOCKED
                  and json.loads(target.read_text())["report_schema_version"] == 2)
            reporter.side_effect = p0c_report.ReportError("refused", code=p0c_report.MISSING_RESULT)
            try:
                main(["--report-json", str(target)])
            except p0c_report.ReportError:
                check("refusal removes stale report and closes connection",
                      not target.exists() and db.return_value.close.call_count == 3)
            else:
                raise AssertionError("report refusal swallowed")
    finally:
        RESULTS.clear()
        RESULTS.update(saved[0])
        NOT_RUN_REASONS.clear()
        NOT_RUN_REASONS.update(saved[1])
        EXTERNAL_BLOCKED.clear()
        EXTERNAL_BLOCKED.update(saved[2])


def write_report(path: Path, report: dict):
    import os
    import tempfile
    from datetime import datetime, timezone
    report = report | {"generated_at_utc": datetime.now(timezone.utc).isoformat()}
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                         dir=path.parent, delete=False) as fh:
            name = fh.name
            json.dump(report, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(name, path)
    finally:
        if name and Path(name).exists():
            Path(name).unlink()


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real-provider-smoke", action="store_true")
    parser.add_argument("--report-json", type=Path)
    args = parser.parse_args(argv)
    _reset_state()
    if args.report_json:
        args.report_json.unlink(missing_ok=True)  # failed rerun cannot leave old green
    test_keyless_branches()
    setup_db()
    conn = psycopg2.connect(uri())
    try:
        test_unmapped_audit(conn)
        test_manifest(conn)
        test_s5_mapping(conn)
        test_fork_cutoff(conn)
        test_switch_negative(conn)
        test_matrix_logic(conn)
        test_fake_provider()
        smoke = test_real_provider_smoke(conn, requested=args.real_provider_smoke)
        report = test_reporter(conn)
        if args.report_json:
            write_report(args.report_json, report)
    finally:
        conn.close()
    if args.real_provider_smoke and smoke.state == "not_run":
        return 2
    print("[G13] all gates passed; script green != P0C complete")
    return 0


if __name__ == "__main__":
    # Safe top-level diagnostic: no provider response, request, URI or
    # exception message is printed. Exceptions still produce failure.
    try:
        code = main()
    except Exception as exc:
        safe_code = exc.code if isinstance(exc, p0c_report.ReportError) else "TEST_FAILURE"
        print(f"[FAIL] G13 {type(exc).__name__} code={safe_code}", file=sys.stderr)
        code = 1
    raise SystemExit(code)
