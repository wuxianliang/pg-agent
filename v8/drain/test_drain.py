"""G15 gate: v8 failure-drain — the §3.1.1 fail_session class (3) INFRA
closure.

Run: uv run python v8/drain/test_drain.py  (exit 0 = pass)
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v8.drain.setup_db import DB, main as setup_db
from v8.effect.client import (
    claim_session,
    complete_effect,
    dispatch_effect,
    prepare_step,
)
from v8.events.client import create_session
from v8.grant.fixtures import seed_stage_grants, u

SV, CV = "sv@1", "canon@1"
EPOCH = 1


def _uri() -> str:
    return get_server().get_uri(DB)


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f": {detail}" if detail else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def one(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    conn.commit()
    return row


def rows(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        out = cur.fetchall()
    conn.commit()
    return out


def exec_sql(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
    conn.commit()


def good_evidence() -> dict:
    return {"class": "known_success",
            "provider_receipt": {"receipt_id": f"pr-{u()[:8]}"}}


def fail_evidence() -> dict:
    return {"class": "known_failure",
            "provider_receipt": {"receipt_id": f"fr-{u()[:8]}"},
            "no_side_effect_proof": {"checked": True}}


def unknown_evidence() -> dict:
    return {"class": "garbled"}


def session_row(conn, s):
    return one(conn, "SELECT state, failure_code, active_step_id,"
                     " lease_owner, drain_step_id, session_fence"
                     " FROM sessions WHERE session_id=%s", (s,))


def step_row(conn, st):
    return one(conn, "SELECT status, outcome_code FROM steps"
                     " WHERE step_id=%s", (st,))


def effect_row(conn, e):
    return one(conn, "SELECT status FROM effect_requests WHERE effect_id=%s",
               (e,))[0]


def seal_fx(conn, drv: str, *, max_attempts: int = 1):
    """create -> claim -> initial decision seal (effect left `ready`)."""
    s = u()
    turn, step, eff = u(), u(), u()
    rh, ik = f"rh-{u()[:10]}", f"ik-{u()[:10]}"
    create_session(conn, s, drv)
    r0 = claim_session(conn, s, drv)
    check("fx claim ok", r0["outcome"] == "claimed", r0)
    rs = prepare_step(conn, s, f"seal-{u()[:8]}", drv, EPOCH,
                      r0["session_fence"], step, turn, eff,
                      request_hash=rh, idempotency_key=ik,
                      max_attempts=max_attempts)
    check("fx seal accepted", rs["outcome"] == "accepted", rs)
    return {"session": s, "turn": turn, "step": step, "effect": eff, "rh": rh,
            "ik": ik, "claim_fence": r0["session_fence"],
            "seal_fence": rs["receipt"]["session_fence"],
            "job_fence": rs["receipt"]["job_fence"]}


def dispatch_fx(conn, drv: str, **kw):
    """seal_fx + dispatch (the effect is in flight)."""
    fx = seal_fx(conn, drv, **kw)
    rd = dispatch_effect(conn, fx["session"], f"dsp-{u()[:8]}", fx["effect"],
                         drv, EPOCH, fx["seal_fence"], fx["job_fence"])
    check("fx dispatch accepted", rd["outcome"] == "accepted", rd)
    return fx


def fail_session(conn, session, code, reason="g15 test"):
    return one(conn, "SELECT v_fail_session(%s::uuid, %s, %s)",
               (session, code, reason))[0]


# ---------------------------------------------------------------------------
# 1. D1 — the class (3) closure: both codes, closed-set guard
# ---------------------------------------------------------------------------

def test_d1_class3_closure(conn) -> None:
    for code, tag in (("INFRA_ASSEMBLY_FAILED", "asm"),
                      ("INFRA_PROTOCOL_VIOLATION", "prt")):
        drv = f"g15-{tag}"
        seed_stage_grants(conn, drivers=(drv,))
        fx = seal_fx(conn, drv)
        exec_sql(conn, "UPDATE sessions SET lease_owner='w',"
                       " lease_until=now() + interval '60s',"
                       " lease_purpose='coordinator' WHERE session_id=%s",
                 (fx["session"],))
        before = session_row(conn, fx["session"])
        r = fail_session(conn, fx["session"], code, f"{code} vector")
        check(f"D1 {code}: accepted", r["outcome"] == "accepted", r)
        row = session_row(conn, fx["session"])
        check(f"D1 {code}: session failed / {code}",
              row[0] == "failed" and row[1] == code, row)
        check(f"D1 {code}: lease revoked, active_step cleared, fence +1",
              row[2] is None and row[3] is None
              and row[5] == before[5] + 1, (row, before))
        # The single `ready` effect was drained by the shared pre-dispatch
        # sync (D3 shape, asserted fully in test_d3).
        check(f"D1 {code}: ready effect cancelled_before_dispatch",
              effect_row(conn, fx["effect"]) == "cancelled_before_dispatch",
              (effect_row(conn, fx["effect"]), r))
        # The step had no unknown and no remaining pending effect -> the
        # `neither` arm -> failed_terminal / the INFRA code.
        check(f"D1 {code}: step failed_terminal / {code}",
              step_row(conn, fx["step"]) == ("failed_terminal", code),
              step_row(conn, fx["step"]))
        check(f"D1 {code}: drain_step_id NULL (step terminalized)",
              row[4] is None, row)

    # Negative: a code outside the closed set is a stable rejection with
    # ZERO control state (public callers MUST NOT pick an arbitrary code).
    drv = "g15-neg"
    seed_stage_grants(conn, drivers=(drv,))
    fx = seal_fx(conn, drv)
    before = session_row(conn, fx["session"])
    r = fail_session(conn, fx["session"], "WORKSPACE_LOST", "smuggled code")
    check("D1 negative: non-closed-set code -> FAILURE_CODE_INVALID",
          r["outcome"] == "rejected_mismatch"
          and r["code"] == "FAILURE_CODE_INVALID", r)
    check("D1 negative: zero control state",
          session_row(conn, fx["session"]) == before
          and effect_row(conn, fx["effect"]) == "ready",
          session_row(conn, fx["session"]))


# ---------------------------------------------------------------------------
# 2. D2 — the three drain branches + repeat convergence
# ---------------------------------------------------------------------------

def test_d2_three_branches(conn) -> None:
    # (i) unknown_outcome effect -> step blocked_unknown_effect.
    drv = "g15-d2i"
    seed_stage_grants(conn, drivers=(drv,))
    fx = dispatch_fx(conn, drv)
    rc = complete_effect(
        conn, fx["session"], f"cmp-{u()[:8]}", fx["effect"], drv, EPOCH,
        dispatch_session_fence=fx["claim_fence"], job_fence=fx["job_fence"],
        step_id=fx["step"], request_hash=fx["rh"], idempotency_key=fx["ik"],
        outcome="unknown_outcome", message={"text": ""}, tools=[],
        decision_only=False, final_tools=False, evidence=unknown_evidence())
    check("D2(i) fx unknown_outcome settlement accepted",
          rc["outcome"] == "accepted", rc)
    r = fail_session(conn, fx["session"], "INFRA_PROTOCOL_VIOLATION")
    check("D2(i) accepted", r["outcome"] == "accepted", r)
    check("D2(i) step stays blocked_unknown_effect",
          step_row(conn, fx["step"])[0] == "blocked_unknown_effect",
          step_row(conn, fx["step"]))
    check("D2(i) drain_step_id pins the non-terminal step",
          session_row(conn, fx["session"])[4] == fx["step"])

    # (ii) in-flight pending effect -> step stays waiting_effect, outcome
    # code NULL.
    drv = "g15-d2ii"
    seed_stage_grants(conn, drivers=(drv,))
    fx = dispatch_fx(conn, drv)
    r = fail_session(conn, fx["session"], "INFRA_ASSEMBLY_FAILED")
    check("D2(ii) accepted", r["outcome"] == "accepted", r)
    check("D2(ii) step stays waiting_effect / outcome_code NULL",
          step_row(conn, fx["step"]) == ("waiting_effect", None),
          step_row(conn, fx["step"]))
    check("D2(ii) in-flight effect untouched (dispatch_started)",
          effect_row(conn, fx["effect"]) == "dispatch_started")
    check("D2(ii) drain_step_id pins the waiting step",
          session_row(conn, fx["session"])[4] == fx["step"])

    # (ii-sticky) a sticky cancellation latch flips the pending arm to
    # cancel_requested.
    drv = "g15-d2iis"
    seed_stage_grants(conn, drivers=(drv,))
    fx = dispatch_fx(conn, drv)
    exec_sql(conn, "UPDATE sessions SET cancellation_epoch=1"
                   " WHERE session_id=%s", (fx["session"],))
    r = fail_session(conn, fx["session"], "INFRA_ASSEMBLY_FAILED")
    check("D2(sticky) accepted", r["outcome"] == "accepted", r)
    check("D2(sticky) step cancel_requested / outcome_code NULL",
          step_row(conn, fx["step"]) == ("cancel_requested", None),
          step_row(conn, fx["step"]))

    # (iii) neither: a non-terminal step whose effects are all terminal
    # (decision settled with final_tools=true, awaiting the tools seal) ->
    # step failed_terminal / the INFRA code.
    drv = "g15-d2iii"
    seed_stage_grants(conn, drivers=(drv,))
    fx = dispatch_fx(conn, drv)
    rc = complete_effect(
        conn, fx["session"], f"cmp-{u()[:8]}", fx["effect"], drv, EPOCH,
        dispatch_session_fence=fx["claim_fence"], job_fence=fx["job_fence"],
        step_id=fx["step"], request_hash=fx["rh"], idempotency_key=fx["ik"],
        outcome="succeeded", message={"text": "plan"},
        tools=[{"tool_call_id": "c-0", "tool": "fake_tool"}],
        decision_only=False, final_tools=True, evidence=good_evidence())
    check("D2(iii) fx decision settlement accepted",
          rc["outcome"] == "accepted", rc)
    check("D2(iii) step is non-terminal before the drain",
          step_row(conn, fx["step"])[0] not in
          ("succeeded", "failed_terminal", "cancelled"),
          step_row(conn, fx["step"]))
    r = fail_session(conn, fx["session"], "INFRA_PROTOCOL_VIOLATION")
    check("D2(iii) accepted", r["outcome"] == "accepted", r)
    check("D2(iii) step failed_terminal / INFRA_PROTOCOL_VIOLATION",
          step_row(conn, fx["step"])
          == ("failed_terminal", "INFRA_PROTOCOL_VIOLATION"),
          step_row(conn, fx["step"]))
    check("D2(iii) drain_step_id NULL (terminal step)",
          session_row(conn, fx["session"])[4] is None)

    # D10 repeat convergence: a second drain re-evaluates the branch, keeps
    # the terminal session (no second fence bump) and refreshes the pointer.
    drv = "g15-d2rep"
    seed_stage_grants(conn, drivers=(drv,))
    fx = dispatch_fx(conn, drv)
    fail_session(conn, fx["session"], "INFRA_PROTOCOL_VIOLATION")
    after_first = session_row(conn, fx["session"])
    r2 = fail_session(conn, fx["session"], "INFRA_PROTOCOL_VIOLATION")
    after_second = session_row(conn, fx["session"])
    check("D2 repeat: marked repeated", r2["repeated"] is True, r2)
    check("D2 repeat: session unchanged, fence not bumped again",
          after_second == after_first, (after_first, after_second))
    check("D2 repeat: audited exactly once per drain call",
          one(conn, "SELECT count(*) FROM grant_ops_audit"
                    " WHERE target_id=%s AND action='infra_drain'",
              (fx["session"],))[0] == 2)


# ---------------------------------------------------------------------------
# 3. D3 — the pre-dispatch dual-table atomic sync consumption
# ---------------------------------------------------------------------------

def test_d3_predispatch_sync(conn) -> None:
    drv = "g15-d3"
    seed_stage_grants(conn, drivers=(drv,))
    fx = seal_fx(conn, drv)
    r = fail_session(conn, fx["session"], "INFRA_PROTOCOL_VIOLATION")
    check("D3 accepted", r["outcome"] == "accepted", r)
    row = one(conn, "SELECT er.status, a.status, er.dispatched_at,"
                    " er.dispatch_count FROM effect_requests er"
                    " JOIN effect_attempts a ON a.effect_id = er.effect_id"
                    " AND a.attempt_no = er.attempt_no"
                    " WHERE er.effect_id=%s", (fx["effect"],))
    check("D3 dual-table sync: effect + attempt cancelled_before_dispatch",
          row == ("cancelled_before_dispatch", "cancelled_before_dispatch",
                  None, 0), row)
    check("D3 no single-sided intermediate state",
          one(conn, "SELECT count(*) FROM effect_requests er"
                    " JOIN effect_attempts a ON a.effect_id = er.effect_id"
                    " AND a.attempt_no = er.attempt_no"
                    " WHERE er.effect_id=%s AND"
                    " er.status IS DISTINCT FROM a.status",
              (fx["effect"],))[0] == 0)
    check("D3 ABORTED_BEFORE_DISPATCH audit row written",
          one(conn, "SELECT count(*) FROM effect_audit WHERE effect_id=%s"
                    " AND reason='ABORTED_BEFORE_DISPATCH'",
              (fx["effect"],))[0] == 1)
    check("D3 no completion semantic event / receipt for the drained effect",
          one(conn, "SELECT count(*) FROM session_events WHERE session_id=%s"
                    " AND event_type IN ('tool/result','assistant/message')",
              (fx["session"],))[0] == 0)
    # A late worker completion is rejected by the existing settled-attempt
    # rules, writing only a receipt + audit (no control-state change).
    before = effect_row(conn, fx["effect"])
    rc = complete_effect(
        conn, fx["session"], f"cmp-{u()[:8]}", fx["effect"], drv, EPOCH,
        dispatch_session_fence=fx["claim_fence"], job_fence=fx["job_fence"],
        step_id=fx["step"], request_hash=fx["rh"], idempotency_key=fx["ik"],
        outcome="succeeded", message={"text": "late"}, tools=[],
        decision_only=False, final_tools=False, evidence=good_evidence())
    check("D3 late completion rejected (already settled attempt)",
          rc["outcome"] != "accepted", rc)
    check("D3 late completion changed no control state",
          effect_row(conn, fx["effect"]) == before ==
          "cancelled_before_dispatch")


# ---------------------------------------------------------------------------
# 4. D4 — DECISION_PLAN_INVALID settles INFRA, retry_stop_reason derived
# ---------------------------------------------------------------------------

def test_d4_decision_plan_invalid(conn) -> None:
    """The drain-stage database loads the retry stage, so the §3.2.2 ordered
    classification IS reachable here (the effect-stage gate cannot assert it
    — see the IF to_regprocedure guard in v_infra_closure_effect)."""
    drv = "g15-d4"
    seed_stage_grants(conn, drivers=(drv,))
    fx = dispatch_fx(conn, drv, max_attempts=1)
    r = complete_effect(
        conn, fx["session"], f"cmp-{u()[:8]}", fx["effect"], drv, EPOCH,
        dispatch_session_fence=fx["claim_fence"], job_fence=fx["job_fence"],
        step_id=fx["step"], request_hash=fx["rh"], idempotency_key=fx["ik"],
        outcome="succeeded", message={"text": "m"}, tools=[],
        decision_only=False, final_tools=False, evidence=good_evidence())
    check("D4 illegal marks -> DECISION_PLAN_INVALID",
          r["outcome"] == "rejected_mismatch"
          and r["code"] == "DECISION_PLAN_INVALID", r)
    check("D4 effect failed_terminal", effect_row(conn, fx["effect"])
          == "failed_terminal")
    check("D4 step failed_terminal / INFRA_PROTOCOL_VIOLATION",
          step_row(conn, fx["step"])
          == ("failed_terminal", "INFRA_PROTOCOL_VIOLATION"))
    srow = session_row(conn, fx["session"])
    check("D4 session failed / INFRA_PROTOCOL_VIOLATION",
          (srow[0], srow[1]) == ("failed", "INFRA_PROTOCOL_VIOLATION"), srow)
    check("D4 retry_stop_reason derived (max_attempts=1 ->"
          " first_attempt_failure)",
          one(conn, "SELECT retry_stop_reason FROM effect_requests"
                    " WHERE effect_id=%s", (fx["effect"],))[0]
          == "first_attempt_failure")
    check("D4 closure audit row exactly one",
          one(conn, "SELECT count(*) FROM effect_audit WHERE effect_id=%s"
                    " AND reason='INFRA_PROTOCOL_VIOLATION'"
                    " AND internal_op_kind='infra_closure'",
              (fx["effect"],))[0] == 1)


# ---------------------------------------------------------------------------
# 5. D5 — parent-layer failure-code priority
# ---------------------------------------------------------------------------

def test_d5_parent_code_priority(conn) -> None:
    drv = "g15-d5"
    seed_stage_grants(conn, drivers=(drv,))
    fx = dispatch_fx(conn, drv)
    # Parent layer fails the session first (WORKSPACE_LOST), then an illegal
    # decision completion arrives: the session MUST keep its original cause.
    exec_sql(conn, "UPDATE sessions SET state='failed',"
                   " failure_code='WORKSPACE_LOST' WHERE session_id=%s",
             (fx["session"],))
    r = complete_effect(
        conn, fx["session"], f"cmp-{u()[:8]}", fx["effect"], drv, EPOCH,
        dispatch_session_fence=fx["claim_fence"], job_fence=fx["job_fence"],
        step_id=fx["step"], request_hash=fx["rh"], idempotency_key=fx["ik"],
        outcome="succeeded", message={"text": "m"}, tools=[],
        decision_only=False, final_tools=False, evidence=good_evidence())
    check("D5 illegal completion still rejects",
          r["outcome"] == "rejected_mismatch"
          and r["code"] == "DECISION_PLAN_INVALID", r)
    srow = session_row(conn, fx["session"])
    check("D5 session keeps WORKSPACE_LOST as its cause",
          (srow[0], srow[1]) == ("failed", "WORKSPACE_LOST"), srow)
    check("D5 effect closed failed_terminal with an INFRA audit row",
          effect_row(conn, fx["effect"]) == "failed_terminal"
          and one(conn, "SELECT count(*) FROM effect_audit"
                        " WHERE effect_id=%s"
                        " AND reason='INFRA_PROTOCOL_VIOLATION'",
                  (fx["effect"],))[0] == 1)


# ---------------------------------------------------------------------------
# 6. D6 — the two exclusions
# ---------------------------------------------------------------------------

def test_d6_exclusions(conn) -> None:
    # (b) a terminal completion under quiescing returns DRIVER_QUIESCING and
    # never reaches the semantic layer (so never the INFRA closure).
    drv = "g15-d6b"
    seed_stage_grants(conn, drivers=(drv,))
    fx = dispatch_fx(conn, drv)
    exec_sql(conn, "UPDATE sessions SET driver_mode='quiescing'"
                   " WHERE session_id=%s", (fx["session"],))
    r = complete_effect(
        conn, fx["session"], f"cmp-{u()[:8]}", fx["effect"], drv, EPOCH,
        dispatch_session_fence=fx["claim_fence"], job_fence=fx["job_fence"],
        step_id=fx["step"], request_hash=fx["rh"], idempotency_key=fx["ik"],
        outcome="succeeded", message={"text": "m"}, tools=[],
        decision_only=False, final_tools=False, evidence=good_evidence())
    check("D6(b) quiescing terminal completion -> DRIVER_QUIESCING",
          r["outcome"] == "rejected_mismatch"
          and r["code"] == "DRIVER_QUIESCING", r)
    check("D6(b) zero control-state change (no INFRA closure)",
          effect_row(conn, fx["effect"]) == "dispatch_started"
          and session_row(conn, fx["session"])[0] != "failed")


# ---------------------------------------------------------------------------
# 7. D8 — ISOLATION_UNSUPPORTED on both entries
# ---------------------------------------------------------------------------

def test_d8_isolation(conn) -> None:
    drv = "g15-d8"
    seed_stage_grants(conn, drivers=(drv,))
    fx = seal_fx(conn, drv)
    for entry, sql, params in (
        ("v_fail_session", "SELECT v_fail_session(%s::uuid,"
                           " 'INFRA_PROTOCOL_VIOLATION', 'iso')",
         (fx["session"],)),
        ("v_failure_drain_core",
         "SELECT v_failure_drain_core(%s::uuid, 'INFRA_PROTOCOL_VIOLATION',"
         " 'iso', 'k', 'infra_drain')", (fx["session"],)),
    ):
        before = session_row(conn, fx["session"])
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cur.execute(sql, params)
            r = cur.fetchone()[0]
            conn.rollback()
        check(f"D8 {entry}: non-READ COMMITTED -> ISOLATION_UNSUPPORTED",
              r["code"] == "ISOLATION_UNSUPPORTED", r)
        check(f"D8 {entry}: zero control state",
              session_row(conn, fx["session"]) == before
              and effect_row(conn, fx["effect"]) == "ready")


# ---------------------------------------------------------------------------
# 8. D11 — one shared pre-dispatch implementation, three trigger sources
# ---------------------------------------------------------------------------

def test_d11_single_predispatch_impl(conn) -> None:
    # G15 D11: the WORKSPACE_LOST drain and the INFRA closure call the SAME
    # shared pre-dispatch sync function; the two legacy definitions (the
    # grant-stage narrow variant consumed by WORKSPACE_LOST and the
    # plugin-stage six-parameter variant consumed by request_cancel / the
    # generation drain) are still both present — their unification is
    # G17-D14, NOT this gate. This gate asserts behavioural equivalence
    # instead of same-source identity.
    rows_ = rows(conn, "SELECT p.proname FROM pg_proc p WHERE"
                       " p.proname IN ('v_predispatch_cancel_sync',"
                       " 'v_pre_dispatch_cancel_sync') ORDER BY 1")
    check("D11 both pre-dispatch definitions still present (unification is"
          " G17-D14)",
          [r[0] for r in rows_] == ["v_pre_dispatch_cancel_sync",
                                    "v_predispatch_cancel_sync"],
          rows_)
    drv = "g15-d11"
    seed_stage_grants(conn, drivers=(drv,))
    fx = seal_fx(conn, drv)
    r = fail_session(conn, fx["session"], "INFRA_ASSEMBLY_FAILED")
    check("D11 INFRA closure drains through the shared sync (dual-table)",
          r["outcome"] == "accepted"
          and effect_row(conn, fx["effect"]) == "cancelled_before_dispatch")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    setup_db()
    conn = psycopg2.connect(_uri())
    conn.autocommit = False
    try:
        test_d1_class3_closure(conn)
        test_d2_three_branches(conn)
        test_d3_predispatch_sync(conn)
        test_d4_decision_plan_invalid(conn)
        test_d5_parent_code_priority(conn)
        test_d6_exclusions(conn)
        test_d8_isolation(conn)
        test_d11_single_predispatch_impl(conn)
    finally:
        conn.close()
    print("[G15] all gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
