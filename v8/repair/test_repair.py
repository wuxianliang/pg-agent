"""G7c gate: v8 repair — the unique exit for unknown_outcome (three terminal
states), the turn-end closer supersedes chain (protected slot update
function, (v) six controlled validations, two-level idempotency),
closer_event_key@v1 SQL/Python byte parity, canonicalizer closer
consumption (projection supersedes the provisional representation,
append-only recomputation), the blocked_unknown_effect recovery edges
(rules 4/5/6 + minimal rule-3) and the mixed-sibling acceptance
(Conformance 5).

Run: uv run python v8/repair/test_repair.py  (exit 0 = pass)
"""
from __future__ import annotations

import hashlib
import json
import secrets
import struct
import sys
import uuid
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v8.canonical import canonicalize, escape_dollar_keys
from v8.canonical.keys import closer_event_key_v1
from v8.effect.client import (
    claim_session,
    complete_effect,
    dispatch_effect,
    finish_session,
    prepare_step,
)
from v8.events.canonicalizer import CanonicalizerError, normalize
from v8.events.client import build_entry, call_append_events, create_session
from v8.repair.client import repair
from v8.repair.setup_db import DB, main as setup_db
from v8.retry.test_retry import (
    DRIVER,
    EPOCH,
    DyingConnection,
    ProcessDeath,
    attempt_rows,
    check,
    decision_fx,
    effect_row,
    fail_decision,
    fail_evidence,
    fail_tool,
    good_evidence,
    one,
    retry,
    rows,
    session_row,
    step_row,
    succeed_tool,
    tools_fx,
    u,
)

SV, CV = "sv@1", "canon@1"


def uri() -> str:
    return get_server().get_uri(DB)


def canon(obj) -> tuple[str, str]:
    return canonicalize(escape_dollar_keys(obj))


def sha256_hex_text(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------

def unknown_decision(conn, retry_class: str = "verifiable_no_effect",
                     max_attempts: int = 3):
    """decision fixture whose completion classifies unknown (no bound
    terminal evidence) -> unknown_outcome + provisional slot + blocked."""
    fx = decision_fx(conn, retry_class=retry_class, max_attempts=max_attempts)
    r = fail_decision(conn, fx, evidence={"class": "provider_error"})
    check("fx unknown settlement accepted",
          r["outcome"] == "accepted"
          and r["receipt"]["classification"] == "unknown", r["receipt"])
    check("fx effect unknown_outcome + step/session blocked",
          effect_row(conn, fx["effect"])[0] == "unknown_outcome"
          and step_row(conn, fx["step"])[0] == "blocked_unknown_effect"
          and session_row(conn, fx["session"])[0] == "blocked_unknown_effect")
    return fx


def unknown_tools(conn, specs=None):
    """tools fixture with BOTH tools settled unknown (unique provisional end
    for the turn, step/session blocked)."""
    specs = specs or [("verifiable_no_effect", 3), ("verifiable_no_effect", 3)]
    fx = tools_fx(conn, specs)
    for i in range(len(fx["effects"])):
        r = fail_tool(conn, fx, i, evidence={"class": "provider_error"})
        check(f"fx tool {i} unknown settlement accepted",
              r["outcome"] == "accepted"
              and r["receipt"]["classification"] == "unknown", r["receipt"])
    check("fx tools step/session blocked_unknown_effect",
          step_row(conn, fx["step"])[0] == "blocked_unknown_effect"
          and session_row(conn, fx["session"])[0] == "blocked_unknown_effect")
    return fx


def slot_row(conn, session_id):
    return one(conn,
               "SELECT turn_end_key, head_event_key, slot_status, version,"
               " resolution_identity_canonical FROM turn_end_slots"
               " WHERE session_id=%s", (session_id,))


def closers_rows(conn, session_id):
    return rows(conn,
                "SELECT turn_id, turn_end_key,"
                " resolution_identity_canonical, resolution_digest,"
                " supersedes_event_key, closer_event_key, event_seq"
                " FROM turn_end_closers WHERE session_id=%s"
                " ORDER BY event_seq", (session_id,))


def event_row(conn, session_id, event_key):
    return one(conn,
               "SELECT event_type, payload, turn_id, step_id, effect_id,"
               " internal_semantic_ordinal, seq FROM session_events"
               " WHERE session_id=%s AND event_key=%s", (session_id, event_key))


def do_repair(conn, fx, evidence, resolution_kind, *, attempt_no=1,
              supersedes=None, cmd=None, declared_hash=None, **kw):
    """Repair a DECISION effect (LLM slot)."""
    if supersedes is None:
        supersedes = slot_row(conn, fx["session"])[1]
    return repair(conn, fx["session"], cmd or f"rpr-{u()[:8]}",
                  fx["effect"], attempt_no,
                  driver=DRIVER, driver_epoch=EPOCH,
                  supersedes_event_key=supersedes, evidence=evidence,
                  resolution_kind=resolution_kind,
                  declared_hash=declared_hash, **kw)


def repair_tool(conn, fx, i, evidence, resolution_kind, *, supersedes=None,
                cmd=None, output=None, declared_hash=None, **kw):
    e = fx["effects"][i]
    if supersedes is None:
        supersedes = slot_row(conn, fx["session"])[1]
    return repair(conn, fx["session"], cmd or f"rpr-{u()[:8]}",
                  e["effect_id"], 1,
                  driver=DRIVER, driver_epoch=EPOCH,
                  supersedes_event_key=supersedes, evidence=evidence,
                  resolution_kind=resolution_kind,
                  tool_call_id=e["tool_call_id"],
                  output=output if output is not None
                  else {"echo": "ok", "tool": "fake_tool"},
                  declared_hash=declared_hash, **kw)


def zero_state_unchanged(conn, fx, effect_id=None) -> bool:
    """The unknown target kept every bit of control state: effect/attempt
    unknown_outcome, one attempt row, provisional slot v1, no closers."""
    eff = effect_id or fx["effect"]
    er = effect_row(conn, eff)
    att = attempt_rows(conn, eff)
    sl = slot_row(conn, fx["session"])
    return (er[0] == "unknown_outcome"
            and len(att) == 1 and att[0][1] == "unknown_outcome"
            and att[0][2] is None
            and sl is not None and sl[2] == "provisional" and sl[3] == 1
            and closers_rows(conn, fx["session"]) == []
            and session_row(conn, fx["session"])[0] == "blocked_unknown_effect")


def expect_sql_error(conn, sql: str, params: tuple = ()) -> str:
    with conn.cursor() as cur:
        try:
            cur.execute(sql, params)
        except psycopg2.Error as exc:
            conn.rollback()
            return str(exc)
    conn.rollback()
    return ""


def trace_events(conn, session_id) -> list[dict]:
    """normalize() input built from the PERSISTED state: raw session_events
    rows (append-only) annotated with the effect statuses read back from
    effect_requests (the control-signal contract, now driven by the
    persisted control state)."""
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


def end_events(trace: list[dict]) -> list[dict]:
    return [e for e in trace if e["event_type"] == "turn/end"]


# ---------------------------------------------------------------------------
# 1. closer_event_key@v1 SQL == Python, >= 3 vectors, independent hashlib
# ---------------------------------------------------------------------------

def ref_closer_key(tek: str, sup: str, res_bytes: bytes) -> str:
    """Independent hand-computed reference (struct + hashlib only; never the
    implementations under test)."""
    blob = (b"v8:closer-event-key@v1\x00"
            + struct.pack(">Q", len(tek.encode("utf-8"))) + tek.encode("utf-8")
            + struct.pack(">Q", len(sup.encode("utf-8"))) + sup.encode("utf-8")
            + struct.pack(">Q", len(res_bytes)) + res_bytes)
    return hashlib.sha256(blob).hexdigest()


def test_closer_event_key_vectors(conn) -> None:
    vectors = [
        (hashlib.sha256(b"slot-one").hexdigest(),
         hashlib.sha256(b"prov-one").hexdigest(),
         b'{"attempt_no":1,"code":"SUCCEEDED","effect_id":"'
         b'00000000-0000-0000-0000-000000000001","resolution":"succeeded"}'),
        (hashlib.sha256(b"slot-two").hexdigest(),
         hashlib.sha256(b"closer-one").hexdigest(),
         b'{"attempt_no":2,"code":"RATE_LIMIT","effect_id":"'
         b'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee","resolution":"failed_terminal"}'),
        ("0" * 64, "f" * 64, b"{}"),
    ]
    for i, (tek, sup, res) in enumerate(vectors):
        want = ref_closer_key(tek, sup, res)
        got_py = closer_event_key_v1(tek, sup, res)
        got_sql = one(conn, "SELECT v_closer_event_key(%s, %s, %s::bytea)",
                      (tek, sup, res))[0]
        check(f"closer_event_key vector {i}: Python == independent hashlib",
              got_py == want, (got_py, want))
        check(f"closer_event_key vector {i}: SQL == independent hashlib",
              got_sql == want, (got_sql, want))


# ---------------------------------------------------------------------------
# 2. repair three terminal states
# ---------------------------------------------------------------------------

def test_three_terminal_states(conn) -> None:
    # (a) known_success: decision_only decision repair.
    fx = unknown_decision(conn)
    sl0 = slot_row(conn, fx["session"])
    check("fixture: provisional slot v1, no closers",
          sl0[2] == "provisional" and sl0[3] == 1
          and closers_rows(conn, fx["session"]) == [])
    r = do_repair(conn, fx, good_evidence(), "succeeded",
                  message={"text": "repaired"}, tools=[],
                  decision_only=True, final_tools=False)
    rec = r["receipt"]
    check("success repair accepted, classified known_success",
          r["outcome"] == "accepted" and rec["classification"] == "known_success"
          and rec["settled_status"] == "succeeded", rec)
    check("effect+attempt succeeded, no new attempt",
          effect_row(conn, fx["effect"])[0] == "succeeded"
          and len(attempt_rows(conn, fx["effect"])) == 1)
    check("step succeeded/closed/SUCCEEDED, session ready",
          step_row(conn, fx["step"])[0] == "succeeded"
          and session_row(conn, fx["session"])[0] == "ready")
    ck = rec["closer"]["event_key"]
    sl = slot_row(conn, fx["session"])
    check("slot known, head = closer, version advanced 1 -> 2",
          sl[2] == "known" and sl[1] == ck and sl[3] == 2, sl)
    cl = closers_rows(conn, fx["session"])
    check("exactly one closers row, supersedes the provisional head",
          len(cl) == 1 and cl[0][4] == sl0[1] and cl[0][5] == ck, cl)
    check("closer row digest = sha256(resolution canonical), 32 bytes",
          len(cl[0][3]) == 32
          and bytes(cl[0][3]) == hashlib.sha256(bytes(cl[0][2])).digest())
    ev = event_row(conn, fx["session"], ck)
    check("closer event is an assistant/message-class semantic event",
          ev is not None and ev[0] == "assistant/message"
          and json.loads(ev[1])["closer"] is True
          and json.loads(ev[1])["resolution"]["resolution"] == "succeeded", ev)
    # decision_only turn close goes through the shared finalize judgment:
    # claim + finish_session completes.
    r0 = claim_session(conn, fx["session"], DRIVER)
    check("claim after repair accepted", r0["outcome"] == "claimed", r0)
    rf = finish_session(conn, fx["session"], f"fin-{u()[:8]}", DRIVER, EPOCH,
                        r0["session_fence"])
    check("finish_session completed after decision_only repair",
          rf["outcome"] == "accepted"
          and session_row(conn, fx["session"])[0] == "completed", rf)

    # (b) known_failure: unsafe first attempt -> first_attempt_failure.
    fx = unknown_decision(conn, retry_class="unsafe", max_attempts=1)
    r = do_repair(conn, fx, fail_evidence(), "failed_terminal",
                  code="RATE_LIMIT")
    rec = r["receipt"]
    check("failure repair accepted, classified known_failure",
          r["outcome"] == "accepted" and rec["classification"] == "known_failure"
          and rec["settled_status"] == "failed_terminal", rec)
    check("retry_stop_reason persisted first_attempt_failure (max_attempts=1)",
          rec["retry_stop_reason"] == "first_attempt_failure"
          and effect_row(conn, fx["effect"])[5] == "first_attempt_failure", rec)
    check("step/session failed_terminal / FAILED_TERMINAL (rule 4)",
          step_row(conn, fx["step"])[0] == "failed_terminal"
          and session_row(conn, fx["session"])
          == ("failed", "FAILED_TERMINAL"))
    check("failure repair: no new attempt",
          len(attempt_rows(conn, fx["effect"])) == 1)
    ev = event_row(conn, fx["session"], rec["closer"]["event_key"])
    check("failure closer is a turn/end {interrupted:true, reason:failed}",
          ev is not None and ev[0] == "turn/end"
          and json.loads(ev[1])["interrupted"] is True
          and json.loads(ev[1])["reason"] == "failed", ev)
    check("slot known v2, one closers row",
          slot_row(conn, fx["session"])[2:4] == ("known", 2)
          and len(closers_rows(conn, fx["session"])) == 1)

    # (c) known_cancellation with a provider receipt -> CANCELLED_BY_PROVIDER.
    fx = unknown_decision(conn)
    r = do_repair(conn, fx,
                  {"class": "known_cancellation",
                   "provider_receipt": {"receipt_id": f"cr-{u()[:6]}"}},
                  "cancelled_after_dispatch")
    rec = r["receipt"]
    check("cancel repair accepted, classified known_cancellation",
          r["outcome"] == "accepted"
          and rec["classification"] == "known_cancellation"
          and rec["settled_status"] == "cancelled_after_dispatch", rec)
    check("effect cancelled_after_dispatch, code CANCELLED_BY_PROVIDER",
          effect_row(conn, fx["effect"])[0] == "cancelled_after_dispatch"
          and rec["effect_code"] == "CANCELLED_BY_PROVIDER", rec)
    check("step cancelled/CANCELLED_BY_PROVIDER, session cancelled (rule 3)",
          step_row(conn, fx["step"])[0:2]
          == ("cancelled", "CANCELLED_BY_PROVIDER")
          and session_row(conn, fx["session"])
          == ("cancelled", "CANCELLED_BY_PROVIDER"))
    ev = event_row(conn, fx["session"], rec["closer"]["event_key"])
    check("cancel closer reason cancelled_by_provider",
          ev is not None and ev[0] == "turn/end"
          and json.loads(ev[1])["reason"] == "cancelled_by_provider", ev)

    # (d) known_cancellation with a no-side-effect proof alone (cancel request
    #     took effect before the side effect) -> CANCELLED_BY_REQUEST_*.
    fx = unknown_decision(conn)
    r = do_repair(conn, fx,
                  {"class": "known_cancellation",
                   "no_side_effect_proof": {"checked": True}},
                  "cancelled_after_dispatch")
    rec = r["receipt"]
    check("request-family cancel repair accepted",
          r["outcome"] == "accepted"
          and rec["effect_code"] == "CANCELLED_BY_REQUEST_AFTER_DISPATCH", rec)
    check("step cancelled/CANCELLED_BY_REQUEST, session cancelled",
          step_row(conn, fx["step"])[0:2] == ("cancelled", "CANCELLED_BY_REQUEST")
          and session_row(conn, fx["session"])
          == ("cancelled", "CANCELLED_BY_REQUEST"))


# ---------------------------------------------------------------------------
# 3. budget exhaustion derivation (attempt 2 unknown, max_attempts=2)
# ---------------------------------------------------------------------------

def test_budget_exhausted_derivation(conn) -> None:
    fx = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=2)
    fail_decision(conn, fx)
    check("fixture: rule 5 after attempt-1 known failure",
          step_row(conn, fx["step"])[0] == "failed_retryable")
    rr = retry(conn, fx)
    check("fixture: cohort allocated attempt 2",
          rr["outcome"] == "accepted" and len(rr["receipt"]["effects"]) == 1, rr)
    jf2 = effect_row(conn, fx["effect"])[2]
    sf = one(conn, "SELECT session_fence FROM sessions WHERE session_id=%s",
             (fx["session"],))[0]
    rd = dispatch_effect(conn, fx["session"], f"dsp-{u()[:8]}", fx["effect"],
                         DRIVER, EPOCH, sf, jf2)
    check("attempt-2 dispatch accepted", rd["outcome"] == "accepted", rd)
    dsf2 = one(conn, "SELECT dispatch_session_fence FROM effect_attempts"
                     " WHERE effect_id=%s AND attempt_no=2",
               (fx["effect"],))[0]
    rc = complete_effect(
        conn, fx["session"], f"cmp-{u()[:8]}", fx["effect"], DRIVER, EPOCH,
        dispatch_session_fence=dsf2, job_fence=jf2,
        step_id=fx["step"], attempt_no=2, request_hash=fx["rh"],
        idempotency_key=fx["ik"], outcome="failed_retryable",
        message={"text": ""}, tools=[], decision_only=True, final_tools=False,
        evidence={"class": "provider_error"},
        result_payload={"error": {"kind": "timeout"}})
    check("attempt-2 completion settles unknown_outcome",
          rc["outcome"] == "accepted"
          and rc["receipt"]["classification"] == "unknown", rc["receipt"])
    ev = fail_evidence()
    ev["attempt_no"] = 2
    r = do_repair(conn, fx, ev, "failed_terminal", attempt_no=2,
                  code="RATE_LIMIT")
    rec = r["receipt"]
    check("attempt-2 failure repair accepted",
          r["outcome"] == "accepted"
          and rec["settled_status"] == "failed_terminal", rec)
    check("budget exhausted derivation: retry_stop_reason=budget_exhausted",
          rec["retry_stop_reason"] == "budget_exhausted"
          and effect_row(conn, fx["effect"])[5] == "budget_exhausted", rec)
    check("code derived FAILED_RETRY_BUDGET_EXHAUSTED (rule 4 reason set)",
          step_row(conn, fx["step"])[0:2]
          == ("failed_terminal", "FAILED_RETRY_BUDGET_EXHAUSTED")
          and session_row(conn, fx["session"])
          == ("failed", "FAILED_RETRY_BUDGET_EXHAUSTED"))
    check("repair never created an attempt (still attempts 1,2)",
          [a[0] for a in attempt_rows(conn, fx["effect"])] == [1, 2])


# ---------------------------------------------------------------------------
# 4. REPAIR_EVIDENCE_REQUIRED negatives + old-attempt impersonation
# ---------------------------------------------------------------------------

def test_evidence_required_negatives(conn) -> None:
    # (iv) only a bound no-side-effect proof, no provider terminal receipt.
    fx = unknown_decision(conn)
    r = do_repair(conn, fx,
                  {"class": "known_failure",
                   "no_side_effect_proof": {"checked": True}},
                  "failed_terminal", code="X")
    check("(iv) proof-only repair -> REPAIR_EVIDENCE_REQUIRED",
          r["outcome"] == "rejected_mismatch"
          and r["code"] == "REPAIR_EVIDENCE_REQUIRED", r)
    check("(iv) zero control state (unknown kept, no closer, slot v1)",
          zero_state_unchanged(conn, fx))

    # (v) failure receipt bound correctly but side-effect state unclear.
    r = do_repair(conn, fx,
                  {"class": "known_failure",
                   "provider_receipt": {"receipt_id": f"fr-{u()[:6]}"}},
                  "failed_terminal", code="X")
    check("(v) receipt-without-proof repair -> REPAIR_EVIDENCE_REQUIRED",
          r["outcome"] == "rejected_mismatch"
          and r["code"] == "REPAIR_EVIDENCE_REQUIRED", r)
    check("(v) zero control state", zero_state_unchanged(conn, fx))
    check("evidence rejections audited",
          one(conn, "SELECT count(*) FROM effect_audit"
                    " WHERE effect_id=%s AND reason='REPAIR_EVIDENCE_REQUIRED'",
              (fx["effect"],))[0] == 2)

    # Old-attempt impersonation: unknown on attempt 2, evidence bound to
    # the superseded attempt 1 (Conformance 5 mandatory case).
    fx = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=3)
    fail_decision(conn, fx)
    rr = retry(conn, fx)
    check("fixture: attempt 2 allocated", rr["outcome"] == "accepted", rr)
    jf2 = effect_row(conn, fx["effect"])[2]
    sf = one(conn, "SELECT session_fence FROM sessions WHERE session_id=%s",
             (fx["session"],))[0]
    dispatch_effect(conn, fx["session"], f"dsp-{u()[:8]}", fx["effect"],
                    DRIVER, EPOCH, sf, jf2)
    dsf2 = one(conn, "SELECT dispatch_session_fence FROM effect_attempts"
                     " WHERE effect_id=%s AND attempt_no=2",
               (fx["effect"],))[0]
    rc = complete_effect(
        conn, fx["session"], f"cmp-{u()[:8]}", fx["effect"], DRIVER, EPOCH,
        dispatch_session_fence=dsf2, job_fence=jf2,
        step_id=fx["step"], attempt_no=2, request_hash=fx["rh"],
        idempotency_key=fx["ik"], outcome="failed_retryable",
        message={"text": ""}, tools=[], decision_only=True, final_tools=False,
        evidence={"class": "provider_error"},
        result_payload={"error": {"kind": "timeout"}})
    check("fixture: attempt 2 settled unknown_outcome",
          effect_row(conn, fx["effect"])[0] == "unknown_outcome", rc)
    ev1 = good_evidence()
    ev1["attempt_no"] = 1  # impersonate the superseded attempt
    r = do_repair(conn, fx, ev1, "succeeded", attempt_no=2,
                  message={"text": "x"}, tools=[], decision_only=True,
                  final_tools=False)
    check("evidence bound to superseded attempt -> REPAIR_EVIDENCE_REQUIRED",
          r["outcome"] == "rejected_mismatch"
          and r["code"] == "REPAIR_EVIDENCE_REQUIRED", r)
    r = do_repair(conn, fx, good_evidence(), "succeeded", attempt_no=1,
                  message={"text": "x"}, tools=[], decision_only=True,
                  final_tools=False)
    check("envelope naming the old attempt -> REPAIR_EVIDENCE_REQUIRED",
          r["outcome"] == "rejected_mismatch"
          and r["code"] == "REPAIR_EVIDENCE_REQUIRED", r)
    check("impersonation rejections: zero control state",
          effect_row(conn, fx["effect"])[0] == "unknown_outcome"
          and len(attempt_rows(conn, fx["effect"])) == 2
          and closers_rows(conn, fx["session"]) == []
          and slot_row(conn, fx["session"])[2:4] == ("provisional", 1))
    # The same execution's correctly bound evidence repairs it (fence
    # advance never changes the execution identity awaiting repair).
    r = do_repair(conn, fx, good_evidence(), "succeeded", attempt_no=2,
                  message={"text": "x"}, tools=[], decision_only=True,
                  final_tools=False)
    check("bound current-attempt evidence repairs successfully",
          r["outcome"] == "accepted"
          and effect_row(conn, fx["effect"])[0] == "succeeded", r)


# ---------------------------------------------------------------------------
# 5. REPAIR_TARGET_INVALID negatives (target + four chain classes) and the
#    database-level closers protections
# ---------------------------------------------------------------------------

def test_target_invalid(conn) -> None:
    # Target not unknown (a normally completed decision effect).
    fx = decision_fx(conn)
    rc = complete_effect(
        conn, fx["session"], f"cmp-{u()[:8]}", fx["effect"], DRIVER, EPOCH,
        dispatch_session_fence=2, job_fence=fx["job_fence"],
        step_id=fx["step"], request_hash=fx["rh"], idempotency_key=fx["ik"],
        outcome="succeeded", message={"text": "ok"}, tools=[],
        decision_only=True, final_tools=False, evidence=good_evidence())
    check("fixture: effect succeeded", rc["outcome"] == "accepted", rc)
    r = repair(conn, fx["session"], f"rpr-{u()[:8]}", fx["effect"], 1,
               driver=DRIVER, driver_epoch=EPOCH,
               supersedes_event_key=slot_row(conn, fx["session"])[1],
               evidence=good_evidence(), resolution_kind="succeeded",
               message={"text": "x"}, tools=[], decision_only=True,
               final_tools=False)
    check("non-unknown target -> REPAIR_TARGET_INVALID",
          r["outcome"] == "rejected_mismatch"
          and r["code"] == "REPAIR_TARGET_INVALID", r)
    check("non-unknown target: state untouched",
          effect_row(conn, fx["effect"])[0] == "succeeded"
          and closers_rows(conn, fx["session"]) == [])

    # Target not persisted at all.
    fx = unknown_decision(conn)
    r = repair(conn, fx["session"], f"rpr-{u()[:8]}", u(), 1,
               driver=DRIVER, driver_epoch=EPOCH,
               supersedes_event_key="ab" * 32,
               evidence=good_evidence(), resolution_kind="succeeded",
               message={"text": "x"}, tools=[], decision_only=True,
               final_tools=False)
    check("unpersisted target -> REPAIR_TARGET_INVALID",
          r["outcome"] == "rejected_mismatch"
          and r["code"] == "REPAIR_TARGET_INVALID", r)

    # Chain class: orphan key.
    r = do_repair(conn, fx, good_evidence(), "succeeded",
                  supersedes="ab" * 32,
                  message={"text": "x"}, tools=[], decision_only=True,
                  final_tools=False)
    check("orphan supersedes key -> REPAIR_TARGET_INVALID",
          r["outcome"] == "rejected_mismatch"
          and r["code"] == "REPAIR_TARGET_INVALID", r)
    check("orphan key: zero side effects", zero_state_unchanged(conn, fx))

    # Two-turn fixture for cross-turn / ordinary-event classes: repair turn
    # 1 succeeded first (making the session ready), then start turn 2 and
    # settle it unknown.
    r = do_repair(conn, fx, good_evidence(), "succeeded",
                  message={"text": "t1"}, tools=[], decision_only=True,
                  final_tools=False)
    check("fixture: turn 1 repaired succeeded", r["outcome"] == "accepted", r)
    end1_key = r["receipt"]["closer"]["event_key"]
    r0 = claim_session(conn, fx["session"], DRIVER)
    step2, turn2, eff2 = u(), u(), u()
    rh2, ik2 = f"rh-{u()[:10]}", f"ik-{u()[:10]}"
    rs = prepare_step(conn, fx["session"], f"seal-{u()[:8]}", DRIVER, EPOCH,
                      r0["session_fence"], step2, turn2, eff2,
                      request_hash=rh2, idempotency_key=ik2)
    check("fixture: turn 2 sealed", rs["outcome"] == "accepted", rs)
    rd = dispatch_effect(conn, fx["session"], f"dsp-{u()[:8]}", eff2,
                         DRIVER, EPOCH, rs["receipt"]["session_fence"],
                         rs["receipt"]["job_fence"])
    check("fixture: turn 2 dispatched", rd["outcome"] == "accepted", rd)
    dsf2 = one(conn, "SELECT dispatch_session_fence FROM effect_attempts"
                     " WHERE effect_id=%s AND attempt_no=1", (eff2,))[0]
    rc = complete_effect(
        conn, fx["session"], f"cmp-{u()[:8]}", eff2, DRIVER, EPOCH,
        dispatch_session_fence=dsf2, job_fence=rs["receipt"]["job_fence"],
        step_id=step2, request_hash=rh2, idempotency_key=ik2,
        outcome="failed_retryable", message={"text": ""}, tools=[],
        decision_only=True, final_tools=False,
        evidence={"class": "provider_error"},
        result_payload={"error": {"kind": "timeout"}})
    check("fixture: turn 2 effect unknown_outcome",
          effect_row(conn, eff2)[0] == "unknown_outcome", rc)
    slot2 = one(conn, "SELECT head_event_key FROM turn_end_slots"
                      " WHERE session_id=%s AND turn_id=%s",
                (fx["session"], turn2))
    check("fixture: turn 2 provisional slot exists", slot2 is not None)

    # Cross-turn supersedes (turn 1's closer as turn 2's chain head).
    r = repair(conn, fx["session"], f"rpr-{u()[:8]}", eff2, 1,
               driver=DRIVER, driver_epoch=EPOCH,
               supersedes_event_key=end1_key,
               evidence=good_evidence(), resolution_kind="succeeded",
               message={"text": "x"}, tools=[], decision_only=True,
               final_tools=False)
    check("cross-turn supersedes -> REPAIR_TARGET_INVALID",
          r["outcome"] == "rejected_mismatch"
          and r["code"] == "REPAIR_TARGET_INVALID", r)

    # Ordinary event as chain head (a user/message of turn 2).
    nxt = one(conn, "SELECT next_seq FROM sessions WHERE session_id=%s",
              (fx["session"],))[0]
    entry = build_entry("user/message", {"text": "hi"},
                        schema_version=SV, canonicalizer_version=CV,
                        turn_id=turn2, semantic_input_ordinal=1)
    ra = call_append_events(conn, fx["session"], f"apx-{u()[:8]}", DRIVER,
                            EPOCH, nxt, [entry])
    check("fixture: user/message appended to turn 2",
          ra["outcome"] == "accepted", ra)
    um_key = ra["receipt"]["items"][0]["event_key"]
    r = repair(conn, fx["session"], f"rpr-{u()[:8]}", eff2, 1,
               driver=DRIVER, driver_epoch=EPOCH,
               supersedes_event_key=um_key,
               evidence=good_evidence(), resolution_kind="succeeded",
               message={"text": "x"}, tools=[], decision_only=True,
               final_tools=False)
    check("ordinary event as chain head -> REPAIR_TARGET_INVALID",
          r["outcome"] == "rejected_mismatch"
          and r["code"] == "REPAIR_TARGET_INVALID", r)
    check("chain rejections: zero side effects (turn 2 unknown kept)",
          effect_row(conn, eff2)[0] == "unknown_outcome"
          and one(conn, "SELECT count(*) FROM turn_end_closers"
                        " WHERE session_id=%s AND turn_id=%s",
                  (fx["session"], turn2))[0] == 0
          and one(conn, "SELECT slot_status || ':' || version FROM"
                        " turn_end_slots WHERE session_id=%s AND turn_id=%s",
                  (fx["session"], turn2))[0] == "provisional:1")

    # Database-level protections on turn_end_closers.
    cl = closers_rows(conn, fx["session"])
    check("fixture: turn 1 has exactly one closers row", len(cl) == 1)
    err = expect_sql_error(
        conn, "UPDATE turn_end_closers SET event_seq = event_seq + 100"
              " WHERE session_id=%s", (fx["session"],))
    check("closers rows immutable (UPDATE rejected)", "immutable" in err, err)
    err = expect_sql_error(
        conn, "DELETE FROM turn_end_closers WHERE session_id=%s",
        (fx["session"],))
    check("closers rows immutable (DELETE rejected)", "immutable" in err, err)
    # Protected-write: a direct INSERT with fully valid references but no
    # GUC channel is rejected by the trigger.
    sl = slot_row(conn, fx["session"])
    err = expect_sql_error(
        conn,
        "INSERT INTO turn_end_closers(session_id, turn_id, turn_end_key,"
        " resolution_identity_canonical, resolution_digest,"
        " supersedes_event_key, closer_event_key, event_seq)"
        " VALUES (%s, %s, %s, %s::bytea, %s::bytea, %s, %s, 999)",
        (fx["session"], cl[0][0], sl[0], b'{"fake":1}',
         hashlib.sha256(b'{"fake":1}').digest(), sl[1], sl[1]))
    check("insert outside the protected function rejected",
          "protected" in err or "slot update function" in err, err)
    # FK backstop: an orphan closer_event_key can never persist.
    err = expect_sql_error(
        conn,
        "INSERT INTO turn_end_closers(session_id, turn_id, turn_end_key,"
        " resolution_identity_canonical, resolution_digest,"
        " supersedes_event_key, closer_event_key, event_seq)"
        " VALUES (%s, %s, %s, %s::bytea, %s::bytea, %s, %s, 998)",
        (fx["session"], cl[0][0], sl[0], b'{"fake":2}',
         hashlib.sha256(b'{"fake":2}').digest(), sl[1], "cd" * 32))
    check("orphan closer_event_key rejected (FK or guard)", err != "", "no error")


# ---------------------------------------------------------------------------
# 6. Slot chain: provisional -> closer -> head/version/status advance,
#    idempotent resend, conflict variants, CAS reject + resend convergence
# ---------------------------------------------------------------------------

def test_slot_chain(conn) -> None:
    fx = unknown_tools(conn)
    check("unique provisional end for two unknown siblings",
          one(conn, "SELECT count(*) FROM session_events"
                    " WHERE session_id=%s AND event_type='turn/end'",
              (fx["session"],))[0] == 1
          and one(conn, "SELECT count(*) FROM turn_end_slots"
                        " WHERE session_id=%s", (fx["session"],))[0] == 1)
    prov_head = slot_row(conn, fx["session"])[1]

    # Repair A (tool 0) succeeded: partial repair stays blocked (rule 1).
    ev_a = good_evidence()
    rA = repair_tool(conn, fx, 0, ev_a, "succeeded", supersedes=prov_head)
    recA = rA["receipt"]
    check("repair A accepted", rA["outcome"] == "accepted", recA)
    ckA = recA["closer"]["event_key"]
    sl = slot_row(conn, fx["session"])
    check("head/version/status advanced: provisional -> closer A (v2 known)",
          sl[1] == ckA and sl[2] == "known" and sl[3] == 2, sl)
    cl = closers_rows(conn, fx["session"])
    check("exactly one closers row after A",
          len(cl) == 1 and cl[0][4] == prov_head and cl[0][5] == ckA, cl)
    check("partial repair: step/session still blocked (unknown sibling)",
          step_row(conn, fx["step"])[0] == "blocked_unknown_effect"
          and session_row(conn, fx["session"])[0] == "blocked_unknown_effect")
    check("partial repair: no new attempt for the repaired effect",
          len(attempt_rows(conn, fx["effects"][0]["effect_id"])) == 1)

    # Same-resolution resend carrying the OLD chain head (new command_id):
    # idempotent return of the original closer, chain check NOT executed.
    r = repair_tool(conn, fx, 0, ev_a, "succeeded", supersedes=prov_head)
    check("same-resolution resend with old head -> idempotent return",
          r["outcome"] == "accepted"
          and r["receipt"]["idempotent"] is True
          and r["receipt"]["closer"]["event_key"] == ckA, r["receipt"])
    check("idempotent resend: no second closer, version unchanged",
          len(closers_rows(conn, fx["session"])) == 1
          and slot_row(conn, fx["session"])[3] == 2)

    # Same resolution, different payload -> IDEMPOTENCY_CONFLICT.
    r = repair_tool(conn, fx, 0, ev_a, "succeeded", supersedes=prov_head,
                    output={"echo": "DIFFERENT"})
    check("same resolution different payload -> IDEMPOTENCY_CONFLICT",
          r["outcome"] == "rejected_mismatch"
          and r["code"] == "IDEMPOTENCY_CONFLICT", r)

    # Same resolution + payload, different supersedes (the current head) ->
    # IDEMPOTENCY_CONFLICT (the idempotency pre-check precedes chain checks).
    r = repair_tool(conn, fx, 0, ev_a, "succeeded", supersedes=ckA)
    check("same resolution different supersedes -> IDEMPOTENCY_CONFLICT",
          r["outcome"] == "rejected_mismatch"
          and r["code"] == "IDEMPOTENCY_CONFLICT", r)
    check("conflict variants: no second closer",
          len(closers_rows(conn, fx["session"])) == 1
          and slot_row(conn, fx["session"])[1] == ckA)

    # Repair B with a STALE head (the provisional) -> REPAIR_TARGET_INVALID;
    # resend against the current head converges.
    r = repair_tool(conn, fx, 1, good_evidence(), "succeeded",
                    supersedes=prov_head)
    check("stale head repair -> REPAIR_TARGET_INVALID (zero side effects)",
          r["outcome"] == "rejected_mismatch"
          and r["code"] == "REPAIR_TARGET_INVALID", r)
    check("stale head: effect B still unknown, no closer for B",
          effect_row(conn, fx["effects"][1]["effect_id"])[0]
          == "unknown_outcome"
          and len(closers_rows(conn, fx["session"])) == 1)
    rB = repair_tool(conn, fx, 1, good_evidence(), "succeeded",
                     supersedes=ckA)
    check("resend with the current head converges",
          rB["outcome"] == "accepted", rB["receipt"])
    ckB = rB["receipt"]["closer"]["event_key"]
    cl = closers_rows(conn, fx["session"])
    sl = slot_row(conn, fx["session"])
    check("chain: B supersedes A, head = B, version 3, closers exactly 2",
          len(cl) == 2 and cl[1][4] == ckA and cl[1][5] == ckB
          and sl[1] == ckB and sl[2] == "known" and sl[3] == 3, (cl, sl))
    check("closer keys derive as closer_event_key@v1",
          ckA == closer_event_key_v1(
              cl[0][1], prov_head, bytes(cl[0][2]))
          and ckB == closer_event_key_v1(
              cl[1][1], ckA, bytes(cl[1][2])))
    check("full repair: step succeeded/closed, session ready (rule 6)",
          step_row(conn, fx["step"])[0] == "succeeded"
          and session_row(conn, fx["session"])[0] == "ready")
    check("no new attempts anywhere (repair never allocates)",
          all(len(attempt_rows(conn, e["effect_id"])) == 1
              for e in fx["effects"]))


# ---------------------------------------------------------------------------
# 7. normalize: unknown -> partial repair -> full repair (append-only
#    recomputation; the closer supersedes the provisional representation)
# ---------------------------------------------------------------------------

def test_normalize_unknown_then_repair(conn) -> None:
    fx = unknown_tools(conn)
    raw1 = one(conn, "SELECT count(*) FROM session_events WHERE session_id=%s",
               (fx["session"],))[0]
    t1 = normalize(trace_events(conn, fx["session"]), CV)
    ends1 = end_events(t1)
    check("stage 1: unique provisional end, blocked_unknown_effect",
          len(ends1) == 1
          and ends1[0]["payload"]
          == {"outcome": "unknown", "reason": "unknown_after_dispatch"},
          ends1)
    check("stage 1: no tool/result messages for the unknown tools",
          not any(e["event_type"] == "tool/result" for e in t1))

    rA = repair_tool(conn, fx, 0, good_evidence(), "succeeded")
    ckA = rA["receipt"]["closer"]["event_key"]
    raw2 = one(conn, "SELECT count(*) FROM session_events WHERE session_id=%s",
               (fx["session"],))[0]
    check("append-only: raw event count grew by exactly the closer",
          raw2 == raw1 + 1, (raw1, raw2))
    t2 = normalize(trace_events(conn, fx["session"]), CV)
    ends2 = end_events(t2)
    check("stage 2 (partial repair): still the unique provisional end",
          len(ends2) == 1 and ends2[0]["payload"]["outcome"] == "unknown",
          ends2)
    msgs2 = [e for e in t2 if e["event_type"] == "tool/result"]
    check("stage 2: A's closer message present, carrying the resolution",
          any(e["payload"].get("closer") is True
              and e["payload"]["resolution"]["resolution"] == "succeeded"
              and e["effect_id"] == fx["effects"][0]["effect_id"]
              for e in msgs2), msgs2)

    rB = repair_tool(conn, fx, 1, good_evidence(), "succeeded")
    raw3 = one(conn, "SELECT count(*) FROM session_events WHERE session_id=%s",
               (fx["session"],))[0]
    check("append-only: second closer appended", raw3 == raw2 + 1, (raw2, raw3))
    t3 = normalize(trace_events(conn, fx["session"]), CV)
    ends3 = end_events(t3)
    check("stage 3 (full repair): unique known end {interrupted:false}",
          len(ends3) == 1 and ends3[0]["payload"] == {"interrupted": False},
          ends3)
    check("stage 3: provisional unknown marker eliminated from the trace",
          not any(e["payload"].get("outcome") == "unknown" for e in t3))
    msgs3 = [e for e in t3 if e["event_type"] == "tool/result"]
    check("stage 3: both closer messages present (chain-intermediate closer"
          " of the OTHER effect keeps its semantic role)",
          {e["effect_id"] for e in msgs3}
          == {fx["effects"][0]["effect_id"], fx["effects"][1]["effect_id"]},
          msgs3)
    check("raw provisional end still persisted (input events never change)",
          one(conn, "SELECT count(*) FROM session_events"
                    " WHERE session_id=%s AND event_type='turn/end'"
                    " AND payload='{\"outcome\":\"unknown\"}'",
              (fx["session"],))[0] == 1)

    # Same-effect lineage: a closer superseded by a later closer of the
    # SAME effect is eliminated from the projection.
    eff1, turn1 = u(), u()
    res = {"attempt_no": 1, "code": "SUCCEEDED", "effect_id": eff1,
           "resolution": "succeeded"}
    c1 = {"event_type": "assistant/message",
          "payload": {"closer": True, "message": {"text": "v1"},
                      "resolution": res, "supersedes_event_key": "e" * 64},
          "turn_id": turn1, "step_id": None, "effect_id": eff1,
          "event_key": "a" * 64}
    c2 = {"event_type": "assistant/message",
          "payload": {"closer": True, "message": {"text": "v2"},
                      "resolution": res, "supersedes_event_key": "a" * 64},
          "turn_id": turn1, "step_id": None, "effect_id": eff1,
          "event_key": "b" * 64}
    tr = normalize([c1, c2], CV)
    texts = [e["payload"]["message"]["text"] for e in tr
             if e["event_type"] == "assistant/message"]
    check("superseded same-effect closer eliminated; latest survives",
          texts == ["v2"], texts)
    check("lineage fixture ends with the known end",
          end_events(tr)[-1]["payload"] == {"interrupted": False}, tr)

    # Malformed closers fail closed.
    bad = dict(c2)
    bad = {**c2, "event_key": None}
    try:
        normalize([c1, bad], CV)
        check("closer without event_key fails closed", False, "accepted")
    except CanonicalizerError as exc:
        check("closer without event_key fails closed",
              exc.code == "CANONICALIZER_UNSUPPORTED", exc.code)


# ---------------------------------------------------------------------------
# 8. Mixed sibling acceptance (Conformance 5): unknown + failed_retryable
#    -> blocked -> repair proves success -> rule 5 -> retry recovery
# ---------------------------------------------------------------------------

def test_mixed_sibling(conn) -> None:
    fx = tools_fx(conn, [("verifiable_no_effect", 3),
                         ("verifiable_no_effect", 3)])
    fail_tool(conn, fx, 0, evidence={"class": "provider_error"})
    check("fixture: A unknown, step blocked_unknown_effect",
          effect_row(conn, fx["effects"][0]["effect_id"])[0]
          == "unknown_outcome"
          and step_row(conn, fx["step"])[0] == "blocked_unknown_effect")
    fail_tool(conn, fx, 1)
    check("fixture: B failed_retryable (eligible), step still blocked",
          effect_row(conn, fx["effects"][1]["effect_id"])[0]
          == "failed_retryable"
          and step_row(conn, fx["step"])[0] == "blocked_unknown_effect"
          and session_row(conn, fx["session"])[0] == "blocked_unknown_effect")

    rA = repair_tool(conn, fx, 0, good_evidence(), "succeeded")
    recA = rA["receipt"]
    check("repair proves A succeeded",
          rA["outcome"] == "accepted"
          and recA["settled_status"] == "succeeded", recA)
    check("rule 5 aggregation-completion edge: step failed_retryable/"
          "FAILED_RETRYABLE, session ready",
          step_row(conn, fx["step"])[0:2]
          == ("failed_retryable", "FAILED_RETRYABLE")
          and session_row(conn, fx["session"]) == ("ready", None))
    check("no new attempt for the repaired effect (A keeps attempt 1)",
          len(attempt_rows(conn, fx["effects"][0]["effect_id"])) == 1)

    rr = retry(conn, fx, effect_id=fx["effects"][1]["effect_id"])
    check("retry_effect recovers: cohort is B alone",
          rr["outcome"] == "accepted"
          and len(rr["receipt"]["effects"]) == 1
          and rr["receipt"]["effects"][0]["effect_id"]
          == fx["effects"][1]["effect_id"], rr["receipt"])
    jf2 = {e["effect_id"]: e["job_fence"]
           for e in rr["receipt"]["effects"]}[fx["effects"][1]["effect_id"]]
    rd = dispatch_effect(conn, fx["session"], f"dsp-{u()[:8]}",
                         fx["effects"][1]["effect_id"], DRIVER, EPOCH,
                         fx["post_seal_fence"], jf2)
    check("B attempt-2 dispatch accepted", rd["outcome"] == "accepted", rd)
    rs = succeed_tool(conn, fx, 1, attempt_no=2, job_fence=jf2)
    check("B attempt-2 succeeds", rs["outcome"] == "accepted", rs)
    check("terminal states per the matrix: step succeeded/closed/SUCCEEDED,"
          " session ready, no failure_code",
          step_row(conn, fx["step"])[0:2] == ("succeeded", "SUCCEEDED")
          and session_row(conn, fx["session"]) == ("ready", None))
    check("A still has exactly one attempt (never re-executed)",
          len(attempt_rows(conn, fx["effects"][0]["effect_id"])) == 1
          and [a[0] for a in attempt_rows(conn, fx["effects"][1]["effect_id"])]
          == [1, 2])
    check("turn slot: single closer (A's), head known",
          len(closers_rows(conn, fx["session"])) == 1
          and slot_row(conn, fx["session"])[2] == "known")


# ---------------------------------------------------------------------------
# 9. Decision repair with a tools plan: the blocked_unknown_effect -> ready
#    controlled recovery edge (decision_result_identity + normalized plan
#    persisted isomorphically; tools-seal consumption is the LATER note)
# ---------------------------------------------------------------------------

def test_decision_tools_plan_recovery_edge(conn) -> None:
    fx = unknown_decision(conn)
    plan = [{"tool_call_id": f"call-{u()[:6]}", "tool": "fake_tool",
             "arguments": {"echo": "x"}}]
    r = do_repair(conn, fx, good_evidence(), "succeeded",
                  message={"text": "plan"}, tools=plan,
                  decision_only=False, final_tools=True)
    rec = r["receipt"]
    check("tools-plan decision repair accepted",
          r["outcome"] == "accepted", rec)
    st = step_row(conn, fx["step"])
    check("step ready, stage=decision (controlled recovery edge)",
          st[0] == "ready", st)
    plan_text, plan_hash = canon(plan)
    row = one(conn, "SELECT stage, plan_hash, decision_only, final_tools"
                    " FROM steps WHERE step_id=%s", (fx["step"],))
    check("plan persisted isomorphically (plan_hash over the plan, marks)",
          row == ("decision", plan_hash, False, True), row)
    check("session ready (coordinator may claim for the tools seal)",
          session_row(conn, fx["session"])[0] == "ready")
    check("decision_result_identity components persisted (result_hash +"
          " closer event_key)",
          effect_row(conn, fx["effect"])[6] is not None
          and event_row(conn, fx["session"], rec["closer"]["event_key"])
          is not None)

    # DECISION_PLAN_INVALID on the repair path (zero control state).
    fx = unknown_decision(conn)
    r = do_repair(conn, fx, good_evidence(), "succeeded",
                  message={"text": "x"}, tools=[], decision_only=False,
                  final_tools=True)
    check("invalid marks combo -> DECISION_PLAN_INVALID, zero state",
          r["outcome"] == "rejected_mismatch"
          and r["code"] == "DECISION_PLAN_INVALID", r)
    check("DECISION_PLAN_INVALID: unknown kept",
          zero_state_unchanged(conn, fx))


# ---------------------------------------------------------------------------
# 10. Resolution length boundary: oversized (>= 2704B) and high-entropy
#     resolution canonical bytes write normally (digest carries uniqueness)
# ---------------------------------------------------------------------------

def test_resolution_length_boundary(conn) -> None:
    fx = unknown_decision(conn)
    big_resolution = {
        "attempt_no": 1, "code": "SUCCEEDED", "effect_id": fx["effect"],
        "resolution": "succeeded", "detail": "x" * 3000,
    }
    res_text, _ = canon(big_resolution)
    check("fixture: resolution canonical >= 2704 bytes",
          len(res_text.encode("utf-8")) >= 2704, len(res_text.encode("utf-8")))
    r = do_repair(conn, fx, good_evidence(), "succeeded",
                  resolution=big_resolution,
                  message={"text": "big"}, tools=[], decision_only=True,
                  final_tools=False)
    check("oversized resolution repair accepted",
          r["outcome"] == "accepted", r["receipt"])
    cl = closers_rows(conn, fx["session"])
    check("oversized canonical retained in the non-indexed column,"
          " digest 32 bytes",
          len(cl) == 1 and len(bytes(cl[0][2])) >= 2704
          and len(cl[0][3]) == 32
          and bytes(cl[0][2]) == res_text.encode("utf-8"), cl[0][2][:40])

    fx = unknown_decision(conn)
    ent_resolution = {
        "attempt_no": 1, "code": "SUCCEEDED", "effect_id": fx["effect"],
        "resolution": "succeeded", "detail": secrets.token_hex(1600),
    }
    r = do_repair(conn, fx, good_evidence(), "succeeded",
                  resolution=ent_resolution,
                  message={"text": "entropy"}, tools=[], decision_only=True,
                  final_tools=False)
    check("high-entropy resolution repair accepted",
          r["outcome"] == "accepted", r["receipt"])
    cl = closers_rows(conn, fx["session"])
    ent_text, _ = canon(ent_resolution)
    check("high-entropy canonical byte-identical, digest matches",
          len(cl) == 1 and bytes(cl[0][2]) == ent_text.encode("utf-8")
          and bytes(cl[0][3])
          == hashlib.sha256(ent_text.encode("utf-8")).digest())


# ---------------------------------------------------------------------------
# 11. Command guards: receipt idempotency, conflict, hash/driver gates
# ---------------------------------------------------------------------------

def test_guards(conn) -> None:
    fx = unknown_decision(conn)
    cmd = f"rpr-{u()[:8]}"
    prov_head = slot_row(conn, fx["session"])[1]
    kw = dict(message={"text": "g"}, tools=[], decision_only=True,
              final_tools=False, supersedes=prov_head)
    ev = good_evidence()  # identical inputs across the replay pair
    r1 = do_repair(conn, fx, ev, "succeeded", cmd=cmd, **kw)
    check("repair executed", r1["outcome"] == "accepted", r1)
    r2 = do_repair(conn, fx, ev, "succeeded", cmd=cmd, **kw)
    check("same command_id replays the original receipt",
          r2["outcome"] == "accepted" and r2["receipt"] == r1["receipt"], r2)
    r3 = do_repair(conn, fx, good_evidence(), "succeeded", cmd=cmd,
                   message={"text": "DIFFERENT"}, tools=[],
                   decision_only=True, final_tools=False)
    check("same command_id different payload -> IDEMPOTENCY_CONFLICT",
          r3["outcome"] == "rejected_mismatch"
          and r3["code"] == "IDEMPOTENCY_CONFLICT", r3)

    fx = unknown_decision(conn)
    r = do_repair(conn, fx, good_evidence(), "succeeded",
                  declared_hash="0" * 64, **kw)
    check("declared-hash mismatch -> REQUEST_HASH_MISMATCH",
          r["outcome"] == "rejected_mismatch"
          and r["code"] == "REQUEST_HASH_MISMATCH", r)
    check("hash gate: zero control state", zero_state_unchanged(conn, fx))
    r = repair(conn, fx["session"], f"rpr-{u()[:8]}", fx["effect"], 1,
               driver="rogue", driver_epoch=EPOCH,
               supersedes_event_key=slot_row(conn, fx["session"])[1],
               evidence=good_evidence(), resolution_kind="succeeded",
               message={"text": "g"}, tools=[], decision_only=True,
               final_tools=False)
    check("wrong driver -> DRIVER_EPOCH_STALE",
          r["outcome"] == "rejected_stale"
          and r["code"] == "DRIVER_EPOCH_STALE", r)
    check("driver gate: zero control state", zero_state_unchanged(conn, fx))


# ---------------------------------------------------------------------------
# 12. Chaos: repair transaction killed before commit; rerun converges
# ---------------------------------------------------------------------------

def test_chaos_kill_repair(conn) -> None:
    fx = unknown_decision(conn)
    ev = good_evidence()
    prov_head = slot_row(conn, fx["session"])[1]
    kw = dict(message={"text": "chaos"}, tools=[], decision_only=True,
              final_tools=False, supersedes=prov_head)
    cmd = f"rpr-{u()[:8]}"
    real = psycopg2.connect(uri())
    dying = DyingConnection(real)
    try:
        do_repair(dying, fx, ev, "succeeded", cmd=cmd, **kw)
        check("dying repair raised ProcessDeath", False, "committed")
    except ProcessDeath:
        check("dying repair raised ProcessDeath", True)
    finally:
        real.close()
    check("kill rollback: unknown kept, no closer, slot provisional v1",
          zero_state_unchanged(conn, fx))
    n_events = one(conn, "SELECT count(*) FROM session_events"
                         " WHERE session_id=%s", (fx["session"],))[0]
    check("kill rollback: no closer event persisted (seq gap-free)",
          n_events == 1)  # only the provisional turn/end

    r = do_repair(conn, fx, ev, "succeeded", cmd=cmd, **kw)
    check("rerun (same command_id, no binding survived) executes",
          r["outcome"] == "accepted", r)
    ck = r["receipt"]["closer"]["event_key"]
    check("converged: exactly one closers row (unique constraint)",
          len(closers_rows(conn, fx["session"])) == 1
          and closers_rows(conn, fx["session"])[0][5] == ck)
    r2 = do_repair(conn, fx, ev, "succeeded", **kw)
    check("cross-command resend idempotent (still one closer)",
          r2["outcome"] == "accepted"
          and r2["receipt"]["idempotent"] is True
          and len(closers_rows(conn, fx["session"])) == 1, r2["receipt"])


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def main() -> int:
    check("setup", setup_db() == 0)
    conn = psycopg2.connect(uri())
    try:
        test_closer_event_key_vectors(conn)
        test_three_terminal_states(conn)
        test_budget_exhausted_derivation(conn)
        test_evidence_required_negatives(conn)
        test_target_invalid(conn)
        test_slot_chain(conn)
        test_normalize_unknown_then_repair(conn)
        test_mixed_sibling(conn)
        test_decision_tools_plan_recovery_edge(conn)
        test_resolution_length_boundary(conn)
        test_guards(conn)
        test_chaos_kill_repair(conn)
    finally:
        conn.close()
    print("[G7c] all gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
