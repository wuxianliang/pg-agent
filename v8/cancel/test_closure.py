"""G8b gate: v8 shared cancel closure — the five exits (s32b §2.8), the AG01
trigger-source consolidation (α complete_effect / β request_cancel / γ repair /
δ recovery takeover), the cancel-wins matrix (sticky × provider × mixed
sibling shapes, s32a §2.1 rule 3), the §4.3 effect cancel code map, the shared
canonical turn/end derivation (s31a §2.10 / §1.2 reducer priority (2)/(3)) and
the Conformance 6 (spec §6 line 846) / Conformance 15 (line 855) mandatory
fixtures — all asserted at the canonicalizer byte level where the item demands
it.

Run: uv run python v8/cancel/test_closure.py  (exit 0 = pass)
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v8.cancel.client import request_cancel
from v8.cancel.setup_db import DB, main as setup_db
from v8.cancel.test_cancel import append_turn_start, predispatch_fx
from v8.effect.client import (
    claim_session,
    complete_effect,
    dispatch_effect,
    prepare_step,
)
from v8.events.canonicalizer import normalize
from v8.events.client import create_session
from v8.repair.client import repair
from v8.repair.test_repair import repair_tool, unknown_tools
from v8.retry.client import recovery_takeover
from v8.retry.test_retry import (
    DRIVER,
    EPOCH,
    attempt_rows,
    check,
    decision_fx,
    effect_row,
    exec_sql,
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

CV = "canon@1"


def uri() -> str:
    return get_server().get_uri(DB)


# ---------------------------------------------------------------------------
# read-back helpers
# ---------------------------------------------------------------------------

def cancel(conn, session_id, cmd=None, declared_hash=None):
    return request_cancel(conn, session_id, cmd or f"cx-{u()[:8]}", DRIVER,
                          EPOCH, declared_hash=declared_hash)


def latch(conn, session_id, value: int = 1) -> None:
    """Set the sticky stop latch directly (control-state fixture; the public
    entry is request_cancel, exercised separately)."""
    exec_sql(conn, "UPDATE sessions SET cancellation_epoch=%s"
                   " WHERE session_id=%s", (value, session_id))


def effect_codes(conn, session_id) -> dict:
    """The §4.3 cancel code of every effect, resolved by the SAME derived
    reader the aggregation uses (v_effect_cancel_code)."""
    return {str(eid): code for eid, code in rows(
        conn, "SELECT effect_id, v_effect_cancel_code(effect_id)"
              " FROM effect_requests WHERE session_id=%s", (session_id,))}


def trace(conn, session_id) -> list[dict]:
    """normalize() input built from the persisted rows (boundary note: the
    canonicalizer consumes events + the control signals carried on them; the
    signals here are read back from the CONTROL plane — effect statuses, the
    §4.3 cancel codes, the sticky latch and the unsealed-tools-plan fact —
    never hand-written)."""
    latch_v = one(conn, "SELECT cancellation_epoch FROM sessions"
                        " WHERE session_id=%s", (session_id,))[0]
    unsealed = one(conn, "SELECT coalesce(bool_or(status='ready'"
                         " AND stage='decision' AND plan_hash IS NOT NULL),"
                         " false) FROM steps WHERE session_id=%s",
                   (session_id,))[0]
    statuses = {str(e): s for e, s in rows(
        conn, "SELECT effect_id, status FROM effect_requests"
              " WHERE session_id=%s", (session_id,))}
    codes = effect_codes(conn, session_id)
    out = []
    for et, payload, turn, step, eff, key, att, iso in rows(
            conn, "SELECT event_type, payload, turn_id, step_id, effect_id,"
                  " event_key, attempt_no, internal_semantic_ordinal"
                  " FROM session_events WHERE session_id=%s ORDER BY seq",
            (session_id,)):
        d = {"event_type": et, "payload": json.loads(payload),
             "turn_id": str(turn) if turn is not None else None,
             "step_id": str(step) if step is not None else None,
             "effect_id": str(eff) if eff is not None else None,
             "event_key": key, "attempt_no": att,
             "internal_semantic_ordinal": iso}
        if eff is not None:
            st = statuses.get(str(eff))
            if st is not None:
                d["effect_status"] = st
            code = codes.get(str(eff))
            if code is not None:
                d["code"] = code
        if turn is not None:
            d["sticky_cancel"] = latch_v > 0
            d["unsealed_tools_plan"] = bool(unsealed)
        out.append(d)
    return out


def ends(t: list[dict]) -> list[dict]:
    return [e for e in t if e["event_type"] == "turn/end"]


def end_events(conn, session_id) -> list[tuple]:
    return rows(conn, "SELECT payload, event_key FROM session_events"
                      " WHERE session_id=%s AND event_type='turn/end'"
                      " ORDER BY seq", (session_id,))


def audit_reasons(conn, effect_id) -> list[str]:
    return [r[0] for r in rows(
        conn, "SELECT reason FROM effect_audit WHERE effect_id=%s"
              " ORDER BY audit_id", (effect_id,))]


def closure(conn, session_id, step_id, family: str) -> dict:
    """Direct invocation of the shared sub-operation (unit-level exit
    coverage; the trigger sources below run it through the aggregation)."""
    with conn.cursor() as cur:
        cur.execute("SELECT v_shared_cancel_closure(%s::uuid, %s::uuid,"
                    " %s, %s, %s)", (str(session_id), str(step_id),
                                     f"cl-{u()[:8]}", f"kv-{u()[:8]}", family))
        out = cur.fetchone()[0]
    conn.commit()
    return out


def facts(conn, session_id, step_id, effect_id) -> tuple:
    return (effect_row(conn, effect_id)[0], step_row(conn, step_id)[0:2],
            session_row(conn, session_id))


def three_layer(conn, session_id, step_id, effect_ids) -> list:
    return [facts(conn, session_id, step_id, e) for e in effect_ids]


# ---------------------------------------------------------------------------
# 1. the five exits (s32b §2.8)
# ---------------------------------------------------------------------------

def test_exit1_retry_suppressed(conn) -> None:
    """exit 1 — a known retryable failure under the latch closes to
    cancelled_after_dispatch + audit RETRY_SUPPRESSED_BY_CANCEL (α)."""
    fx = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=3)
    latch(conn, fx["session"])
    r = fail_decision(conn, fx)
    check("exit 1 (α): completion accepted", r["outcome"] == "accepted", r)
    check("exit 1: effect cancelled_after_dispatch (MUST NOT stay retryable)",
          effect_row(conn, fx["effect"])[0] == "cancelled_after_dispatch",
          effect_row(conn, fx["effect"]))
    check("exit 1: attempt row synced to cancelled_after_dispatch",
          attempt_rows(conn, fx["effect"])[0][1] == "cancelled_after_dispatch",
          attempt_rows(conn, fx["effect"]))
    check("exit 1: §4.3 code = CANCELLED_BY_REQUEST_AFTER_DISPATCH",
          effect_codes(conn, fx["session"])[fx["effect"]]
          == "CANCELLED_BY_REQUEST_AFTER_DISPATCH")
    check("exit 1: RETRY_SUPPRESSED_BY_CANCEL audit written",
          "RETRY_SUPPRESSED_BY_CANCEL" in audit_reasons(conn, fx["effect"]),
          audit_reasons(conn, fx["effect"]))
    check("exit 1: the declared-vs-derived mismatch is audited, never rejected",
          "RESULT_OUTCOME_MISMATCH" in audit_reasons(conn, fx["effect"]),
          audit_reasons(conn, fx["effect"]))
    check("exit 1: step/page cancelled, session cancelled/CANCELLED_BY_REQUEST",
          step_row(conn, fx["step"])[0:2] == ("cancelled", "CANCELLED_BY_REQUEST")
          and session_row(conn, fx["session"])
          == ("cancelled", "CANCELLED_BY_REQUEST"),
          (step_row(conn, fx["step"]), session_row(conn, fx["session"])))
    check("exit 1: no new attempt (attempt_no stays 1)",
          effect_row(conn, fx["effect"])[1] == 1)
    check("exit 1: one derived turn/end after_dispatch",
          [json.loads(p) for p, _ in end_events(conn, fx["session"])]
          == [{"interrupted": True,
               "reason": "cancelled_by_request_after_dispatch"}])


def test_exit2_terminal_kept(conn) -> None:
    """exit 2 — a known terminal failure keeps failed_terminal and its
    original failure code; the parent layer derives cancel-wins."""
    fx = decision_fx(conn, retry_class="unsafe", max_attempts=1)
    latch(conn, fx["session"])
    r = fail_decision(conn, fx)
    check("exit 2 (α): completion accepted", r["outcome"] == "accepted", r)
    check("exit 2: effect stays failed_terminal, retry_stop_reason kept",
          effect_row(conn, fx["effect"])[0] == "failed_terminal"
          and effect_row(conn, fx["effect"])[5] == "first_attempt_failure",
          effect_row(conn, fx["effect"]))
    check("exit 2: MUST NOT write RETRY_SUPPRESSED_BY_CANCEL",
          "RETRY_SUPPRESSED_BY_CANCEL" not in audit_reasons(conn, fx["effect"]),
          audit_reasons(conn, fx["effect"]))
    check("exit 2: step FAILED_TERMINAL_CANCELLED, session "
          "cancelled/CANCELLED_BY_REQUEST (cancel-wins)",
          step_row(conn, fx["step"])[0:2]
          == ("cancelled", "FAILED_TERMINAL_CANCELLED")
          and session_row(conn, fx["session"])
          == ("cancelled", "CANCELLED_BY_REQUEST"),
          (step_row(conn, fx["step"]), session_row(conn, fx["session"])))


def test_exit3_completed_after_cancel(conn) -> None:
    """exit 3 — a success landing under the latch keeps succeeded and records
    COMPLETED_AFTER_CANCEL; cancel-wins still terminates the step/session."""
    fx = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=3)
    latch(conn, fx["session"])
    r = complete_effect(
        conn, fx["session"], f"cmp-{u()[:8]}", fx["effect"], DRIVER, EPOCH,
        dispatch_session_fence=2, job_fence=fx["job_fence"],
        step_id=fx["step"], request_hash=fx["rh"], idempotency_key=fx["ik"],
        outcome="succeeded", message={"text": "late"}, tools=[],
        decision_only=True, final_tools=False, evidence=good_evidence())
    check("exit 3 (α): completion accepted", r["outcome"] == "accepted", r)
    check("exit 3: receipt records the closure exit",
          r["receipt"].get("cancel_closure") == "completed_after_cancel", r)
    check("exit 3: effect kept succeeded",
          effect_row(conn, fx["effect"])[0] == "succeeded")
    check("exit 3: COMPLETED_AFTER_CANCEL audit written",
          audit_reasons(conn, fx["effect"]) == ["COMPLETED_AFTER_CANCEL"],
          audit_reasons(conn, fx["effect"]))
    check("exit 3: step/session cancelled (cancel-wins over success)",
          step_row(conn, fx["step"])[0:2] == ("cancelled", "CANCELLED_BY_REQUEST")
          and session_row(conn, fx["session"])
          == ("cancelled", "CANCELLED_BY_REQUEST"))
    tr = normalize(trace(conn, fx["session"]), CV)
    check("exit 3: canonical end is the sticky cancel (not a normal close)",
          [e["payload"] for e in ends(tr)]
          == [{"interrupted": True,
               "reason": "cancelled_by_request_after_dispatch"}], tr)


def test_exit4_unknown_kept(conn) -> None:
    """exit 4 — an unknown sibling is kept as-is (rule 1 outranks the cancel);
    the disposition function reports it and mutates nothing."""
    fx = decision_fx(conn)
    fail_decision(conn, fx, evidence={"class": "provider_error"})
    check("exit 4 fixture: unknown_outcome + blocked",
          effect_row(conn, fx["effect"])[0] == "unknown_outcome"
          and step_row(conn, fx["step"])[0] == "blocked_unknown_effect")
    summary = closure(conn, fx["session"], fx["step"], "sticky")
    check("exit 4: the closure reports the unknown exit",
          summary["unknown_kept"] == [fx["effect"]]
          and summary["retry_suppressed"] == [], summary)
    check("exit 4: unknown kept verbatim, no closure audit, step unchanged",
          effect_row(conn, fx["effect"])[0] == "unknown_outcome"
          and "RETRY_SUPPRESSED_BY_CANCEL"
          not in audit_reasons(conn, fx["effect"])
          and "COMPLETED_AFTER_CANCEL"
          not in audit_reasons(conn, fx["effect"])
          and step_row(conn, fx["step"])[0] == "blocked_unknown_effect")

    # under the latch the (α) unknown settlement still lands rule 1: the
    # cancel MUST NOT turn an unresolved unknown into a cancellation.
    fx2 = decision_fx(conn)
    latch(conn, fx2["session"])
    r = fail_decision(conn, fx2, evidence={"class": "provider_error"})
    check("exit 4 (α): unknown completion accepted under the latch",
          r["outcome"] == "accepted"
          and r["receipt"]["classification"] == "unknown", r["receipt"])
    check("exit 4 (α): step/session blocked_unknown_effect (MUST NOT cancel)",
          step_row(conn, fx2["step"])[0] == "blocked_unknown_effect"
          and session_row(conn, fx2["session"])[0] == "blocked_unknown_effect",
          session_row(conn, fx2["session"]))


def test_exit5_known_cancellation(conn) -> None:
    """exit 5 — a known cancellation keeps cancelled_after_dispatch with the
    §4.3 map code; MUST NOT write COMPLETED_AFTER_CANCEL /
    RETRY_SUPPRESSED_BY_CANCEL."""
    # (i) provider-confirmed (bound provider receipt) -> CANCELLED_BY_PROVIDER
    fx = decision_fx(conn)
    r = complete_effect(
        conn, fx["session"], f"cmp-{u()[:8]}", fx["effect"], DRIVER, EPOCH,
        dispatch_session_fence=2, job_fence=fx["job_fence"],
        step_id=fx["step"], request_hash=fx["rh"], idempotency_key=fx["ik"],
        outcome="cancelled_after_dispatch", message={"text": ""}, tools=[],
        decision_only=False, final_tools=False,
        evidence={"class": "known_cancellation",
                  "provider_receipt": {"receipt_id": f"cr-{u()[:6]}"}})
    check("exit 5 (α): provider-confirmed cancellation accepted",
          r["outcome"] == "accepted"
          and r["receipt"]["classification"] == "known_cancellation", r)
    check("exit 5: effect cancelled_after_dispatch, code CANCELLED_BY_PROVIDER",
          effect_row(conn, fx["effect"])[0] == "cancelled_after_dispatch"
          and r["receipt"]["effect_code"] == "CANCELLED_BY_PROVIDER", r)
    check("exit 5: MUST NOT write either closure audit",
          audit_reasons(conn, fx["effect"]) == [],
          audit_reasons(conn, fx["effect"]))
    check("exit 5: step cancelled/CANCELLED_BY_PROVIDER, session cancelled",
          step_row(conn, fx["step"])[0:2] == ("cancelled", "CANCELLED_BY_PROVIDER")
          and session_row(conn, fx["session"])
          == ("cancelled", "CANCELLED_BY_PROVIDER"))
    tr = normalize(trace(conn, fx["session"]), CV)
    check("exit 5: canonical end cancelled_by_provider (no sticky latch)",
          [e["payload"] for e in ends(tr)]
          == [{"interrupted": True, "reason": "cancelled_by_provider"}], tr)

    # (ii) request-family: a no-side-effect proof alone -> CANCELLED_BY_REQUEST
    fx2 = decision_fx(conn)
    r2 = complete_effect(
        conn, fx2["session"], f"cmp-{u()[:8]}", fx2["effect"], DRIVER, EPOCH,
        dispatch_session_fence=2, job_fence=fx2["job_fence"],
        step_id=fx2["step"], request_hash=fx2["rh"], idempotency_key=fx2["ik"],
        outcome="cancelled_after_dispatch", message={"text": ""}, tools=[],
        decision_only=False, final_tools=False,
        evidence={"class": "known_cancellation",
                  "no_side_effect_proof": {"checked": True}})
    check("exit 5: request-family cancellation accepted",
          r2["outcome"] == "accepted", r2)
    check("exit 5: code CANCELLED_BY_REQUEST_AFTER_DISPATCH, step "
          "cancelled/CANCELLED_BY_REQUEST",
          r2["receipt"]["effect_code"] == "CANCELLED_BY_REQUEST_AFTER_DISPATCH"
          and step_row(conn, fx2["step"])[0:2]
          == ("cancelled", "CANCELLED_BY_REQUEST")
          and session_row(conn, fx2["session"])
          == ("cancelled", "CANCELLED_BY_REQUEST"), r2)
    check("exit 5: late repeat of the same command replays",
          complete_effect(
              conn, fx2["session"], r2["receipt"]["command_id"], fx2["effect"],
              DRIVER, EPOCH, dispatch_session_fence=2,
              job_fence=fx2["job_fence"], step_id=fx2["step"],
              request_hash=fx2["rh"], idempotency_key=fx2["ik"],
              outcome="cancelled_after_dispatch", message={"text": ""},
              tools=[], decision_only=False, final_tools=False,
              evidence={"class": "known_cancellation",
                        "no_side_effect_proof": {"checked": True}}
          )["receipt"] == r2["receipt"])


# ---------------------------------------------------------------------------
# 2. trigger sources: two-entry consistency (Conformance 2(1) cancel arm)
# ---------------------------------------------------------------------------

def test_alpha_delta_consistency(conn) -> None:
    """The same bound known_failure evidence under the latch MUST produce
    identical effect/step/session facts and codes through the normal
    completion entry (α) and through the recovery takeover entry (δ)."""
    a = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=3)
    latch(conn, a["session"])
    ra = fail_decision(conn, a)
    check("(α) entry accepted", ra["outcome"] == "accepted", ra)
    fa = facts(conn, a["session"], a["step"], a["effect"])

    d = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=3)
    latch(conn, d["session"])
    rd = recovery_takeover(
        conn, d["session"], f"tko-{u()[:8]}", DRIVER, EPOCH,
        evidence={d["effect"]: dict(fail_evidence(),
                                    effect_id=d["effect"], attempt_no=1)})
    check("(δ) entry accepted", rd["outcome"] == "accepted", rd)
    fd = facts(conn, d["session"], d["step"], d["effect"])

    check("two entries: effect/step/session facts identical", fa == fd,
          (fa, fd))
    check("two entries: three-layer result is the cancel-wins closure",
          fa == ("cancelled_after_dispatch",
                 ("cancelled", "CANCELLED_BY_REQUEST"),
                 ("cancelled", "CANCELLED_BY_REQUEST")), fa)
    check("two entries: both wrote RETRY_SUPPRESSED_BY_CANCEL",
          "RETRY_SUPPRESSED_BY_CANCEL" in audit_reasons(conn, a["effect"])
          and "RETRY_SUPPRESSED_BY_CANCEL" in audit_reasons(conn, d["effect"]),
          (audit_reasons(conn, a["effect"]), audit_reasons(conn, d["effect"])))
    check("two entries: identical derived turn/end reason",
          rd["receipt"]["derived_turn_end"]["reason"]
          == "cancelled_by_request_after_dispatch"
          and [json.loads(p) for p, _ in end_events(conn, d["session"])]
          == [{"interrupted": True,
               "reason": "cancelled_by_request_after_dispatch"}],
          rd["receipt"])


def test_beta_request_cancel_known_results(conn) -> None:
    """(β) — request_cancel's known-result disposition: an effect known
    retryable at cancel time closes through the shared sub-operation (exit 1)
    in the cancel transaction."""
    fx = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=3)
    fail_decision(conn, fx)
    check("(β) fixture: rule 5 failed_retryable",
          step_row(conn, fx["step"])[0] == "failed_retryable",
          step_row(conn, fx["step"]))
    r = cancel(conn, fx["session"])
    check("(β): cancel accepted", r["outcome"] == "accepted", r)
    check("(β): retryable sibling closed to cancelled_after_dispatch",
          effect_row(conn, fx["effect"])[0] == "cancelled_after_dispatch")
    check("(β): RETRY_SUPPRESSED_BY_CANCEL audit written",
          audit_reasons(conn, fx["effect"]) == ["RETRY_SUPPRESSED_BY_CANCEL"],
          audit_reasons(conn, fx["effect"]))
    check("(β): step cancelled/CANCELLED_BY_REQUEST, session cancelled",
          step_row(conn, fx["step"])[0:2] == ("cancelled", "CANCELLED_BY_REQUEST")
          and session_row(conn, fx["session"])
          == ("cancelled", "CANCELLED_BY_REQUEST"))
    check("(β): derived turn/end after_dispatch (a dispatched effect exists)",
          [json.loads(p) for p, _ in end_events(conn, fx["session"])]
          == [{"interrupted": True,
               "reason": "cancelled_by_request_after_dispatch"}])


def test_gamma_repair_cancel_closure(conn) -> None:
    """(γ) — repair's known-result closure: provider family (no latch) and the
    sticky arm keep the same rules; a known terminal failure is kept (exit 2).
    """
    # provider-confirmed cancellation via repair -> exit 5 + provider family
    fx = unknown_tools(conn, [("verifiable_no_effect", 3)])
    r = repair_tool(conn, fx, 0,
                    {"class": "known_cancellation",
                     "provider_receipt": {"receipt_id": f"cr-{u()[:6]}"}},
                    "cancelled_after_dispatch")
    check("(γ) provider: repair accepted",
          r["outcome"] == "accepted"
          and r["receipt"]["effect_code"] == "CANCELLED_BY_PROVIDER", r)
    check("(γ) provider: step/session cancelled/CANCELLED_BY_PROVIDER",
          step_row(conn, fx["step"])[0:2] == ("cancelled", "CANCELLED_BY_PROVIDER")
          and session_row(conn, fx["session"])
          == ("cancelled", "CANCELLED_BY_PROVIDER"))
    check("(γ) provider: no closure audit written (exit 5)",
          "RETRY_SUPPRESSED_BY_CANCEL"
          not in audit_reasons(conn, fx["effects"][0]["effect_id"])
          and "COMPLETED_AFTER_CANCEL"
          not in audit_reasons(conn, fx["effects"][0]["effect_id"]))

    # sticky arm: a repaired failure is a known terminal failure -> exit 2
    fx2 = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=3)
    r2 = fail_decision(conn, fx2, evidence={"class": "provider_error"})
    check("(γ) sticky fixture: unknown settlement",
          r2["outcome"] == "accepted"
          and effect_row(conn, fx2["effect"])[0] == "unknown_outcome", r2)
    latch(conn, fx2["session"])
    sup = one(conn, "SELECT head_event_key FROM turn_end_slots"
                    " WHERE session_id=%s", (fx2["session"],))[0]
    r3 = repair(conn, fx2["session"], f"rpr-{u()[:8]}", fx2["effect"], 1,
                driver=DRIVER, driver_epoch=EPOCH,
                supersedes_event_key=sup, evidence=fail_evidence(),
                resolution_kind="failed_terminal")
    check("(γ) sticky: repair accepted", r3["outcome"] == "accepted", r3)
    check("(γ) sticky: repaired failure kept failed_terminal (exit 2)",
          effect_row(conn, fx2["effect"])[0] == "failed_terminal"
          and "RETRY_SUPPRESSED_BY_CANCEL"
          not in audit_reasons(conn, fx2["effect"]))
    check("(γ) sticky: step FAILED_TERMINAL_CANCELLED, session "
          "cancelled/CANCELLED_BY_REQUEST",
          step_row(conn, fx2["step"])[0:2]
          == ("cancelled", "FAILED_TERMINAL_CANCELLED")
          and session_row(conn, fx2["session"])
          == ("cancelled", "CANCELLED_BY_REQUEST"),
          (step_row(conn, fx2["step"]), session_row(conn, fx2["session"])))
    tr = normalize(trace(conn, fx2["session"]), CV)
    check("(γ) sticky: sticky beats the repaired failure in the canonical end",
          [e["payload"] for e in ends(tr)]
          == [{"interrupted": True,
               "reason": "cancelled_by_request_after_dispatch"}], tr)


# ---------------------------------------------------------------------------
# 3. cancel-wins matrix (sticky × provider × mixed sibling shapes)
# ---------------------------------------------------------------------------

def test_cancel_wins_matrix(conn) -> None:
    # row 1: sticky, no failed_terminal sibling (a succeeded sibling present)
    # -> CANCELLED_BY_REQUEST; the success keeps its COMPLETED_AFTER_CANCEL.
    fx = tools_fx(conn, [("verifiable_no_effect", 3),
                         ("verifiable_no_effect", 3)])
    succeed_tool(conn, fx, 0)         # A succeeded
    fail_tool(conn, fx, 1)            # B eligible -> rule 5 failed_retryable
    check("matrix sticky/success: fixture at rule 5",
          step_row(conn, fx["step"])[0] == "failed_retryable"
          and effect_row(conn, fx["effects"][0]["effect_id"])[0] == "succeeded")
    r = cancel(conn, fx["session"])
    check("matrix sticky/success: cancel accepted", r["outcome"] == "accepted", r)
    check("matrix sticky/success: step/session CANCELLED_BY_REQUEST",
          step_row(conn, fx["step"])[0:2] == ("cancelled", "CANCELLED_BY_REQUEST")
          and session_row(conn, fx["session"])
          == ("cancelled", "CANCELLED_BY_REQUEST"),
          (step_row(conn, fx["step"]), session_row(conn, fx["session"])))
    check("matrix sticky/success: the success keeps succeeded + "
          "COMPLETED_AFTER_CANCEL",
          effect_row(conn, fx["effects"][0]["effect_id"])[0] == "succeeded"
          and "COMPLETED_AFTER_CANCEL"
          in audit_reasons(conn, fx["effects"][0]["effect_id"]),
          audit_reasons(conn, fx["effects"][0]["effect_id"]))
    check("matrix sticky/success: the retryable sibling closed (exit 1)",
          effect_row(conn, fx["effects"][1]["effect_id"])[0]
          == "cancelled_after_dispatch"
          and "RETRY_SUPPRESSED_BY_CANCEL"
          in audit_reasons(conn, fx["effects"][1]["effect_id"]))

    # row 2: sticky + a failed_terminal sibling -> FAILED_TERMINAL_CANCELLED
    fx2 = tools_fx(conn, [("unsafe", 1), ("verifiable_no_effect", 3)])
    fail_tool(conn, fx2, 0)          # unsafe/max_attempts=1 -> failed_terminal
    latch(conn, fx2["session"])
    fail_tool(conn, fx2, 1)          # eligible sibling settles under the latch
    check("matrix sticky/failed_terminal: step FAILED_TERMINAL_CANCELLED",
          step_row(conn, fx2["step"])[0:2]
          == ("cancelled", "FAILED_TERMINAL_CANCELLED")
          and session_row(conn, fx2["session"])
          == ("cancelled", "CANCELLED_BY_REQUEST"),
          (step_row(conn, fx2["step"]), session_row(conn, fx2["session"])))
    check("matrix sticky/failed_terminal: the failure sibling kept",
          effect_row(conn, fx2["effects"][0]["effect_id"])[0] == "failed_terminal")

    # row 3: provider (no latch), no failed_terminal -> CANCELLED_BY_PROVIDER
    fx3 = unknown_tools(conn, [("verifiable_no_effect", 3)])
    repair_tool(conn, fx3, 0,
                {"class": "known_cancellation",
                 "provider_receipt": {"receipt_id": f"cr-{u()[:6]}"}},
                "cancelled_after_dispatch")
    check("matrix provider/no-terminal: CANCELLED_BY_PROVIDER",
          step_row(conn, fx3["step"])[0:2] == ("cancelled", "CANCELLED_BY_PROVIDER")
          and session_row(conn, fx3["session"])
          == ("cancelled", "CANCELLED_BY_PROVIDER"))

    # row 4: provider (no latch) + a residual retryable sibling -> the
    # controlled edge closes it to failed_terminal and the step keeps the
    # failure fact: FAILED_TERMINAL_PROVIDER_CANCELLED
    fx4 = tools_fx(conn, [("verifiable_no_effect", 3),
                          ("verifiable_no_effect", 3)])
    fail_tool(conn, fx4, 0, evidence={"class": "provider_error"})   # unknown
    l0 = one(conn, "SELECT head_event_key FROM turn_end_slots"
                   " WHERE session_id=%s", (fx4["session"],))
    check("matrix provider/residual fixture: slot present", l0 is not None)
    repair_tool(conn, fx4, 0,
                {"class": "known_cancellation",
                 "provider_receipt": {"receipt_id": f"cr-{u()[:6]}"}},
                "cancelled_after_dispatch")
    fail_tool(conn, fx4, 1)          # sibling settles -> rule 3 provider
    check("matrix provider/residual: residual sibling closed to failed_terminal",
          effect_row(conn, fx4["effects"][1]["effect_id"])[0] == "failed_terminal")
    check("matrix provider/residual: audit RETRY_STOPPED_BY_CLOSURE written",
          "RETRY_STOPPED_BY_CLOSURE"
          in audit_reasons(conn, fx4["effects"][1]["effect_id"]),
          audit_reasons(conn, fx4["effects"][1]["effect_id"]))
    check("matrix provider/residual: step FAILED_TERMINAL_PROVIDER_CANCELLED, "
          "session cancelled/CANCELLED_BY_PROVIDER",
          step_row(conn, fx4["step"])[0:2]
          == ("cancelled", "FAILED_TERMINAL_PROVIDER_CANCELLED")
          and session_row(conn, fx4["session"])
          == ("cancelled", "CANCELLED_BY_PROVIDER"),
          (step_row(conn, fx4["step"]), session_row(conn, fx4["session"])))


# ---------------------------------------------------------------------------
# 4. Conformance 15 fixtures
# ---------------------------------------------------------------------------

def test_c15_mixed_cancel_turn(conn) -> None:
    """Mixed cancel turn: one effect provider-confirmed
    (CANCELLED_BY_PROVIDER), one closed under the sticky cancel
    (CANCELLED_BY_REQUEST_AFTER_DISPATCH) -> the canonical output MUST contain
    exactly one turn/end {interrupted:true,
    reason:cancelled_by_request_after_dispatch} (sticky beats provider) and
    MUST NOT contain a second turn/end or a cancelled_by_provider reason."""
    fx = tools_fx(conn, [("verifiable_no_effect", 3),
                         ("verifiable_no_effect", 3)])
    r0 = cancel(conn, fx["session"])   # latch while both effects are in flight
    check("mixed: cancel accepted while both effects in flight",
          r0["outcome"] == "accepted", r0)
    check("mixed: rule 2 sticky -> step cancel_requested, session waiting",
          step_row(conn, fx["step"])[0] == "cancel_requested"
          and session_row(conn, fx["session"])[0] == "waiting_effect")
    fail_tool(conn, fx, 0, evidence={"class": "provider_error"})   # A unknown
    repair_tool(conn, fx, 0,
                {"class": "known_cancellation",
                 "provider_receipt": {"receipt_id": f"cr-{u()[:6]}"}},
                "cancelled_after_dispatch")
    check("mixed: after the repair the sibling keeps the batch cancel-waiting",
          step_row(conn, fx["step"])[0] == "cancel_requested"
          and session_row(conn, fx["session"])[0] == "waiting_effect",
          (step_row(conn, fx["step"]), session_row(conn, fx["session"])))
    check("mixed: provider effect settled cancelled_after_dispatch",
          effect_row(conn, fx["effects"][0]["effect_id"])[0]
          == "cancelled_after_dispatch"
          and effect_codes(conn, fx["session"])[fx["effects"][0]["effect_id"]]
          == "CANCELLED_BY_PROVIDER")
    rb = fail_tool(conn, fx, 1)            # B: known failure under the latch
    check("mixed: B settled through the sticky closure",
          rb["outcome"] == "accepted"
          and effect_row(conn, fx["effects"][1]["effect_id"])[0]
          == "cancelled_after_dispatch"
          and effect_codes(conn, fx["session"])[fx["effects"][1]["effect_id"]]
          == "CANCELLED_BY_REQUEST_AFTER_DISPATCH", rb)
    check("mixed: step/session cancelled/CANCELLED_BY_REQUEST",
          step_row(conn, fx["step"])[0:2] == ("cancelled", "CANCELLED_BY_REQUEST")
          and session_row(conn, fx["session"])
          == ("cancelled", "CANCELLED_BY_REQUEST"))
    reload = end_events(conn, fx["session"])
    check("mixed: persisted turn/end events = the provisional unknown end + "
          "the repair closer (the sticky derivation MUST NOT add a third)",
          len(reload) == 2
          and json.loads(reload[0][0]) == {"outcome": "unknown"}
          and json.loads(reload[1][0])["closer"] is True
          and not any("cancelled_by_request" in p for p, _ in reload), reload)
    tr = normalize(trace(conn, fx["session"]), CV)
    check("mixed: exactly one canonical turn/end", len(ends(tr)) == 1, tr)
    check("mixed: the unique reason is the sticky one (sticky beats provider)",
          [e["payload"] for e in ends(tr)]
          == [{"interrupted": True,
               "reason": "cancelled_by_request_after_dispatch"}], tr)
    check("mixed: NO cancelled_by_provider reason in the canonical output",
          not any(e["payload"].get("reason") == "cancelled_by_provider"
                  for e in tr), tr)


def test_c15_provider_confirmed(conn) -> None:
    """provider-confirmed cancel-after-dispatch fixture: the unique canonical
    end is {interrupted:true, reason:cancelled_by_provider}."""
    fx = unknown_tools(conn, [("verifiable_no_effect", 3)])
    repair_tool(conn, fx, 0,
                {"class": "known_cancellation",
                 "provider_receipt": {"receipt_id": f"cr-{u()[:6]}"}},
                "cancelled_after_dispatch")
    tr = normalize(trace(conn, fx["session"]), CV)
    check("provider fixture: exactly one canonical end",
          len(ends(tr)) == 1, tr)
    check("provider fixture: reason cancelled_by_provider",
          [e["payload"] for e in ends(tr)]
          == [{"interrupted": True, "reason": "cancelled_by_provider"}], tr)
    check("provider fixture: no sticky reason present",
          not any("cancelled_by_request" in str(e["payload"].get("reason"))
                  for e in tr), tr)

    # and the completion entry (α) lands the identical canonical end
    fx2 = decision_fx(conn)
    complete_effect(
        conn, fx2["session"], f"cmp-{u()[:8]}", fx2["effect"], DRIVER, EPOCH,
        dispatch_session_fence=2, job_fence=fx2["job_fence"],
        step_id=fx2["step"], request_hash=fx2["rh"], idempotency_key=fx2["ik"],
        outcome="cancelled_after_dispatch", message={"text": ""}, tools=[],
        decision_only=False, final_tools=False,
        evidence={"class": "known_cancellation",
                  "provider_receipt": {"receipt_id": f"cr-{u()[:6]}"}})
    tr2 = normalize(trace(conn, fx2["session"]), CV)
    check("provider fixture (α): same unique end",
          [e["payload"] for e in ends(tr2)]
          == [{"interrupted": True, "reason": "cancelled_by_provider"}], tr2)


def test_c15_cancel_after_unknown(conn) -> None:
    """cancel-after-unknown fixture: the canonical output is the unique
    unknown representation — MUST NOT show known cancel semantics."""
    fx = decision_fx(conn)
    fail_decision(conn, fx, evidence={"class": "provider_error"})
    r = cancel(conn, fx["session"])
    check("cancel-after-unknown: accepted", r["outcome"] == "accepted", r)
    check("cancel-after-unknown: rule 1 keeps blocked (no cancellation)",
          step_row(conn, fx["step"])[0] == "blocked_unknown_effect"
          and session_row(conn, fx["session"])[0] == "blocked_unknown_effect",
          (step_row(conn, fx["step"]), session_row(conn, fx["session"])))
    tr = normalize(trace(conn, fx["session"]), CV)
    check("cancel-after-unknown: only the provisional unknown end",
          [e["payload"] for e in ends(tr)]
          == [{"outcome": "unknown", "reason": "unknown_after_dispatch"}], tr)
    check("cancel-after-unknown: no known cancel reason present",
          not any("cancelled_by_request" in str(e["payload"].get("reason"))
                  or "cancelled_by_provider" in str(e["payload"].get("reason"))
                  for e in tr), tr)


def test_c15_all_predispatch(conn) -> None:
    """all-pre-dispatch cancel: the latch set and every effect of the turn
    cancelled before dispatch -> the unique end is
    cancelled_by_request_before_dispatch."""
    fx = predispatch_fx(conn)
    r = cancel(conn, fx["session"])
    check("all-pre-dispatch: cancel accepted", r["outcome"] == "accepted", r)
    tr = normalize(trace(conn, fx["session"]), CV)
    check("all-pre-dispatch: exactly one before_dispatch end",
          [e["payload"] for e in ends(tr)]
          == [{"interrupted": True,
               "reason": "cancelled_by_request_before_dispatch"}], tr)
    check("all-pre-dispatch: no after_dispatch reason",
          not any(str(e["payload"].get("reason")).endswith("after_dispatch")
                  for e in tr), tr)


def test_c15_guard_provider_pending(conn) -> None:
    """eligibility guard (a): provider-cancel + a still-in-flight sibling ->
    NO known turn/end; the terminal effect's own representation stands; after
    the sibling settles the guard re-evaluates and the unique reason appears.
    """
    fx = tools_fx(conn, [("verifiable_no_effect", 3),
                         ("verifiable_no_effect", 3)])
    fail_tool(conn, fx, 0, evidence={"class": "provider_error"})
    repair_tool(conn, fx, 0,
                {"class": "known_cancellation",
                 "provider_receipt": {"receipt_id": f"cr-{u()[:6]}"}},
                "cancelled_after_dispatch")
    check("guard (a) fixture: sibling still dispatch_started",
          effect_row(conn, fx["effects"][1]["effect_id"])[0] == "dispatch_started")
    tr = normalize(trace(conn, fx["session"]), CV)
    check("guard (a): NO known turn/end while the sibling is in flight",
          ends(tr) == [], tr)
    check("guard (a): the cancelled effect's representation stands "
          "(provisional unknown end + the repair closer, no derived end)",
          len(end_events(conn, fx["session"])) == 2
          and not any("cancelled_by_request" in p
                      for p, _ in end_events(conn, fx["session"])),
          end_events(conn, fx["session"]))
    # settle the sibling (unknown first, then a provider-confirmed
    # cancellation) -> the guard re-evaluates
    fail_tool(conn, fx, 1, evidence={"class": "provider_error"})
    repair_tool(conn, fx, 1, {"class": "known_cancellation",
                              "provider_receipt": {"receipt_id": f"cr-{u()[:6]}"}},
                "cancelled_after_dispatch")
    tr2 = normalize(trace(conn, fx["session"]), CV)
    check("guard (a): after the sibling settles the unique reason appears",
          [e["payload"] for e in ends(tr2)]
          == [{"interrupted": True, "reason": "cancelled_by_provider"}], tr2)


def test_c15_guard_tools_plan(conn) -> None:
    """eligibility guard (b): a decision with tool calls and no final message
    keeps its assistant/partial prefix and MUST NOT end the turn (the
    unsealed tools plan waits for the tools seal / continuation)."""
    s, turn, step, eff = u(), u(), u(), u()
    rh, ik = f"rh-{u()[:10]}", f"ik-{u()[:10]}"
    create_session(conn, s, DRIVER)
    r0 = claim_session(conn, s, DRIVER)
    rs = prepare_step(conn, s, f"seal-{u()[:8]}", DRIVER, EPOCH,
                      r0["session_fence"], step, turn, eff,
                      request_hash=rh, idempotency_key=ik)
    check("guard (b) fixture: seal accepted", rs["outcome"] == "accepted", rs)
    rd = dispatch_effect(conn, s, f"dsp-{u()[:8]}", eff, DRIVER, EPOCH,
                         rs["receipt"]["session_fence"],
                         rs["receipt"]["job_fence"])
    check("guard (b) fixture: dispatch accepted", rd["outcome"] == "accepted", rd)
    plan = [{"tool_call_id": f"call-{u()[:6]}", "tool": "fake_tool",
             "arguments": {"echo": "x"}}]
    rc = complete_effect(
        conn, s, f"cmp-{u()[:8]}", eff, DRIVER, EPOCH,
        dispatch_session_fence=2, job_fence=rs["receipt"]["job_fence"],
        step_id=step, request_hash=rh, idempotency_key=ik,
        outcome="succeeded", message={"text": "plan:" + s[:6]}, tools=plan,
        decision_only=False, final_tools=True, evidence=good_evidence())
    check("guard (b) fixture: decision with a tools plan accepted",
          rc["outcome"] == "accepted", rc)
    check("guard (b) fixture: step ready, stage=decision with a frozen plan",
          step_row(conn, step)[0] == "ready"
          and one(conn, "SELECT stage FROM steps WHERE step_id=%s",
                  (step,))[0] == "decision"
          and one(conn, "SELECT plan_hash FROM steps WHERE step_id=%s",
                  (step,))[0] is not None,
          (step_row(conn, step),
           one(conn, "SELECT stage, plan_hash FROM steps WHERE step_id=%s",
               (step,))))
    # the streaming prefix is the G9 producer; the canonicalizer contract
    # takes chunk dicts directly (same convention as the G3 unit vectors).
    # The unsealed-tools-plan signal is read back from the persisted step.
    tr = normalize([
        {"event_type": "user/message", "payload": {"text": "q"},
         "turn_id": turn, "semantic_input_ordinal": 1},
        {"event_type": "assistant/chunk",
         "payload": {"text": "planning"}, "turn_id": turn,
         "effect_id": str(eff), "attempt_no": 1, "stream_id": "s1",
         "chunk_index": 0},
        {"event_type": "tool/call", "payload": {"tool": "fake_tool"},
         "turn_id": turn, "effect_id": str(eff),
         "effect_status": "succeeded", "unsealed_tools_plan": True},
    ], CV)
    check("guard (b): assistant/partial retained",
          any(e["event_type"] == "assistant/partial"
              and e["payload"].get("text") == "planning" for e in tr), tr)
    check("guard (b): MUST NOT contain a turn/end", ends(tr) == [], tr)


# ---------------------------------------------------------------------------
# 5. Conformance 6 (this stage's reachable part)
# ---------------------------------------------------------------------------

def test_c6_cancel_completion_two_orders(conn) -> None:
    # order 1: completion first -> rule 5 (failed_retryable), then cancel
    fx = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=3)
    fail_decision(conn, fx)
    check("c6 completion-first: rule 5 batch",
          step_row(conn, fx["step"])[0] == "failed_retryable")
    r1 = cancel(conn, fx["session"])
    check("c6 completion-first: cancel closes the retryable sibling",
          r1["outcome"] == "accepted"
          and effect_row(conn, fx["effect"])[0] == "cancelled_after_dispatch"
          and session_row(conn, fx["session"])
          == ("cancelled", "CANCELLED_BY_REQUEST"), r1)

    # order 2: cancel first (in flight) -> then the completion lands under
    # the latch and settles through the closure
    fx2 = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=3)
    r2 = cancel(conn, fx2["session"])
    check("c6 cancel-first: rule 2 sticky (cancel_requested)",
          r2["outcome"] == "accepted"
          and step_row(conn, fx2["step"])[0] == "cancel_requested"
          and session_row(conn, fx2["session"])[0] == "waiting_effect", r2)
    rc = fail_decision(conn, fx2)
    check("c6 cancel-first: late completion settles through the closure",
          rc["outcome"] == "accepted"
          and effect_row(conn, fx2["effect"])[0] == "cancelled_after_dispatch"
          and session_row(conn, fx2["session"])
          == ("cancelled", "CANCELLED_BY_REQUEST"), rc)


def test_c6_cancel_retry_two_orders(conn) -> None:
    # order 1: retry allocation first -> the new ready attempt is then
    # sync-cancelled by the pre-dispatch dual-table sync
    fx = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=3)
    fail_decision(conn, fx)
    rr = retry(conn, fx)
    check("c6 retry-first: cohort allocated",
          rr["outcome"] == "accepted" and len(rr["receipt"]["effects"]) == 1, rr)
    check("c6 retry-first: effect ready (attempt 2)",
          effect_row(conn, fx["effect"])[0] == "ready"
          and effect_row(conn, fx["effect"])[1] == 2)
    r1 = cancel(conn, fx["session"])
    check("c6 retry-first: the ready attempt is sync-cancelled before dispatch",
          r1["outcome"] == "accepted"
          and effect_row(conn, fx["effect"])[0] == "cancelled_before_dispatch"
          and attempt_rows(conn, fx["effect"])[-1][1]
          == "cancelled_before_dispatch", r1)
    # The before/after split reads the effect-level status signal (the same
    # fact the canonicalizer's `dispatched` set consumes): the effect's
    # CURRENT status is cancelled_before_dispatch, so the turn derives
    # before_dispatch. The retired attempt-1 row keeps its dispatched history
    # in effect_attempts, but a failure settlement emits no semantic event
    # (ledger A31), so no canonical carrier exists for it — documented
    # boundary (ledger A50).
    check("c6 retry-first: step/session cancelled, derived end before_dispatch",
          session_row(conn, fx["session"]) == ("cancelled", "CANCELLED_BY_REQUEST")
          and [json.loads(p) for p, _ in end_events(conn, fx["session"])]
          == [{"interrupted": True,
               "reason": "cancelled_by_request_before_dispatch"}])
    tr = normalize(trace(conn, fx["session"]), CV)
    check("c6 retry-first: the canonicalizer agrees with the derived end",
          [e["payload"] for e in ends(tr)]
          == [{"interrupted": True,
               "reason": "cancelled_by_request_before_dispatch"}], tr)

    # order 2: cancel first (rule 2 sticky while an effect is in flight) ->
    # retry_effect stably refuses with zero control state (no retry after
    # cancel)
    fx2 = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=3)
    r2 = cancel(conn, fx2["session"])
    check("c6 cancel-first: rule 2 sticky (cancel_requested / waiting_effect)",
          r2["outcome"] == "accepted"
          and step_row(conn, fx2["step"])[0] == "cancel_requested"
          and session_row(conn, fx2["session"])[0] == "waiting_effect", r2)
    new_fence = one(conn, "SELECT session_fence FROM sessions"
                          " WHERE session_id=%s", (fx2["session"],))[0]
    rr2 = retry(conn, fx2, fence=new_fence)
    check("c6 cancel-first: retry_effect stably refused (CANCEL_STICKY)",
          rr2["outcome"] == "rejected_mismatch"
          and rr2["code"] == "CANCEL_STICKY", rr2)
    check("c6 cancel-first: no new attempt created, effect untouched",
          effect_row(conn, fx2["effect"])[1] == 1
          and effect_row(conn, fx2["effect"])[0] == "dispatch_started")


def test_c6_repeat_cancel_idempotent(conn) -> None:
    """After a sticky closure the session is terminal: a repeat cancel (new
    command_id) returns the original terminal state with the epoch fixed."""
    fx = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=3)
    latch(conn, fx["session"])
    fail_decision(conn, fx)
    before = one(conn, "SELECT state, failure_code, cancellation_epoch,"
                       " session_fence FROM sessions WHERE session_id=%s",
                 (fx["session"],))
    r = cancel(conn, fx["session"])
    check("repeat cancel: terminal session returns the original state",
          r["outcome"] == "accepted" and r["receipt"]["terminal"] is True
          and r["receipt"]["state"] == "cancelled"
          and r["receipt"]["cancellation_epoch"] == 1
          and r["receipt"]["epoch_changed"] is False, r["receipt"])
    check("repeat cancel: zero control-state change",
          one(conn, "SELECT state, failure_code, cancellation_epoch,"
                    " session_fence FROM sessions WHERE session_id=%s",
              (fx["session"],)) == before)
    check("repeat cancel: no second derived end",
          len(end_events(conn, fx["session"])) == 1)


def test_c6_cancel_repair_two_orders(conn) -> None:
    """cancel × repair (slot lock order, §3.1.2: the slot row lock is taken
    after the attempt row lock; both orders serialize by commit order and
    converge to one canonical turn/end)."""
    # order 1: repair (provider cancellation) first -> the session is
    # cancelled; the later cancel returns the terminal state unchanged.
    fx = unknown_tools(conn, [("verifiable_no_effect", 3)])
    repair_tool(conn, fx, 0,
                {"class": "known_cancellation",
                 "provider_receipt": {"receipt_id": f"cr-{u()[:6]}"}},
                "cancelled_after_dispatch")
    check("c6 cancel×repair (repair first): session cancelled/CANCELLED_BY_PROVIDER",
          session_row(conn, fx["session"])
          == ("cancelled", "CANCELLED_BY_PROVIDER"),
          session_row(conn, fx["session"]))
    before = one(conn, "SELECT state, failure_code, cancellation_epoch,"
                       " session_fence FROM sessions WHERE session_id=%s",
                 (fx["session"],))
    r = cancel(conn, fx["session"])
    check("c6 cancel×repair (repair first): the cancel is a terminal no-op",
          r["outcome"] == "accepted" and r["receipt"]["terminal"] is True
          and r["receipt"]["cancellation_epoch"] == 0
          and one(conn, "SELECT state, failure_code, cancellation_epoch,"
                        " session_fence FROM sessions WHERE session_id=%s",
                  (fx["session"],)) == before, r["receipt"])
    tr = normalize(trace(conn, fx["session"]), CV)
    check("c6 cancel×repair (repair first): one canonical end (provider)",
          [e["payload"] for e in ends(tr)]
          == [{"interrupted": True, "reason": "cancelled_by_provider"}], tr)

    # order 2: cancel first (unknown -> rule 1 blocked), then repair: the
    # provider cancellation fact is kept, the sticky latch still wins.
    fx2 = unknown_tools(conn, [("verifiable_no_effect", 3)])
    r2 = cancel(conn, fx2["session"])
    check("c6 cancel×repair (cancel first): rule 1 keeps blocked",
          r2["outcome"] == "accepted"
          and session_row(conn, fx2["session"])[0] == "blocked_unknown_effect",
          r2)
    sup = one(conn, "SELECT head_event_key FROM turn_end_slots"
                    " WHERE session_id=%s", (fx2["session"],))[0]
    r3 = repair_tool(conn, fx2, 0,
                     {"class": "known_cancellation",
                      "provider_receipt": {"receipt_id": f"cr-{u()[:6]}"}},
                     "cancelled_after_dispatch", supersedes=sup)
    check("c6 cancel×repair (cancel first): repair closes the unknown",
          r3["outcome"] == "accepted", r3)
    check("c6 cancel×repair (cancel first): the sticky latch still wins "
          "(cancel-wins over the provider cancellation)",
          step_row(conn, fx2["step"])[0:2]
          == ("cancelled", "CANCELLED_BY_REQUEST")
          and session_row(conn, fx2["session"])
          == ("cancelled", "CANCELLED_BY_REQUEST"),
          (step_row(conn, fx2["step"]), session_row(conn, fx2["session"])))
    check("c6 cancel×repair (cancel first): the provider effect code is kept "
          "(MUST NOT be rewritten)",
          effect_codes(conn, fx2["session"])[fx2["effects"][0]["effect_id"]]
          == "CANCELLED_BY_PROVIDER")
    tr2 = normalize(trace(conn, fx2["session"]), CV)
    check("c6 cancel×repair (cancel first): one canonical end, sticky reason",
          [e["payload"] for e in ends(tr2)]
          == [{"interrupted": True,
               "reason": "cancelled_by_request_after_dispatch"}], tr2)


def test_chaos_closure_kill(conn) -> None:
    """chaos: the cancel-closure transaction killed before commit rolls back
    whole (latch, closure, derived end), and the rerun converges."""
    from v8.retry.test_retry import DyingConnection, ProcessDeath
    fx = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=3)
    fail_decision(conn, fx)
    dying = DyingConnection(conn)
    try:
        cancel(dying, fx["session"])
        raise AssertionError("expected the mid-transaction kill")
    except ProcessDeath:
        pass
    check("chaos: killed cancel-closure rolled back completely",
          effect_row(conn, fx["effect"])[0] == "failed_retryable"
          and step_row(conn, fx["step"])[0] == "failed_retryable"
          and one(conn, "SELECT cancellation_epoch FROM sessions"
                        " WHERE session_id=%s", (fx["session"],))[0] == 0
          and end_events(conn, fx["session"]) == []
          and "RETRY_SUPPRESSED_BY_CANCEL"
          not in audit_reasons(conn, fx["effect"]))
    r = cancel(conn, fx["session"])
    check("chaos: rerun converges to the same closure",
          r["outcome"] == "accepted"
          and effect_row(conn, fx["effect"])[0] == "cancelled_after_dispatch"
          and session_row(conn, fx["session"])
          == ("cancelled", "CANCELLED_BY_REQUEST"))


def test_code_map_and_closure_units(conn) -> None:
    """§4.3 code map unit assertions + the closure's family guard."""
    fx = decision_fx(conn)
    check("code map: a non-cancelled effect has no cancel code",
          one(conn, "SELECT v_effect_cancel_code(%s::uuid)",
              (fx["effect"],))[0] is None)
    pre = predispatch_fx(conn)
    cancel(conn, pre["session"])
    check("code map: ABORTED_BEFORE_DISPATCH for a pre-dispatch cancel",
          one(conn, "SELECT v_effect_cancel_code(%s::uuid)",
              (pre["effect"],))[0] == "ABORTED_BEFORE_DISPATCH")
    check("closure unit: family outside the closed set is refused",
          "INFRA_PROTOCOL_VIOLATION" in expect_sql_error(
              conn, "SELECT v_shared_cancel_closure(%s::uuid, %s::uuid, 'c',"
                    " 'k', 'bogus')", (fx["session"], fx["step"])))
    summary = closure(conn, fx["session"], fx["step"], "sticky")
    check("closure unit: the summary carries every exit bucket",
          set(summary) == {"family", "retry_suppressed",
                           "completed_after_cancel", "terminal_kept",
                           "unknown_kept", "cancel_kept"}, summary)


def expect_sql_error(conn, sql: str, params: tuple = ()) -> str:
    with conn.cursor() as cur:
        try:
            cur.execute(sql, params)
        except psycopg2.Error as exc:
            conn.rollback()
            return str(exc)
    conn.rollback()
    return ""


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------

def main() -> int:
    check("setup", setup_db() == 0)
    conn = psycopg2.connect(uri())
    try:
        test_exit1_retry_suppressed(conn)
        test_exit2_terminal_kept(conn)
        test_exit3_completed_after_cancel(conn)
        test_exit4_unknown_kept(conn)
        test_exit5_known_cancellation(conn)
        test_alpha_delta_consistency(conn)
        test_beta_request_cancel_known_results(conn)
        test_gamma_repair_cancel_closure(conn)
        test_cancel_wins_matrix(conn)
        test_c15_mixed_cancel_turn(conn)
        test_c15_provider_confirmed(conn)
        test_c15_cancel_after_unknown(conn)
        test_c15_all_predispatch(conn)
        test_c15_guard_provider_pending(conn)
        test_c15_guard_tools_plan(conn)
        test_c6_cancel_completion_two_orders(conn)
        test_c6_cancel_retry_two_orders(conn)
        test_c6_repeat_cancel_idempotent(conn)
        test_c6_cancel_repair_two_orders(conn)
        test_chaos_closure_kill(conn)
        test_code_map_and_closure_units(conn)
    finally:
        conn.close()
    print("[G8b] all gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
