"""G7b gate: v8 recovery takeover — the single-transaction atomic takeover
of result-less in-flight (dispatch_started) attempts.

Conformance 2 mandatory subset (spec section 6, line 843):
- unknown branch with no new attempt: current_job_fence monotonically
  advanced, attempt frozen dispatch_job_fence unchanged, late old-fence
  completion stale-rejects with zero control state, dual-table snapshot
  contract holds (control fence outside the snapshot domain);
- job lease validity guard: session lease expired x job lease valid ->
  the attempt is untouched and a later legal completion is accepted;
  after the job lease expires a rescan takes over;
- pure eligible batch recovery path: equivalent bound failure evidence
  after a result-less takeover allocates the cohort through the shared
  sub-operation (3(c)); two-entry comparison (normal complete_effect ->
  retry_effect vs recovery takeover): new-attempt allocation counts,
  three-layer terminal states and codes identical;
- takeover unknown: no-evidence attempt -> unknown_outcome + provisional
  end, budget exhaustion never produces a known terminal failure;
- chaos: takeover transaction killed before commit rolls back whole; the
  rerun converges without duplicate allocation
  (UNIQUE(effect_id, dispatch_job_fence)).

Run: uv run python v8/retry/test_takeover.py  (exit 0 = pass)
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
from v8.effect.client import complete_effect, dispatch_effect, \
    recovery_claim_session
from v8.retry.client import recovery_takeover
from v8.retry.setup_db import main as setup_db
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
    session_row,
    step_row,
    succeed_tool,
    tools_fx,
    u,
    uri,
)


def bound(ev: dict, effect_id, attempt_no: int = 1) -> dict:
    """Bind an evidence object to the attempt it attests (the classifier
    requires the carried (effect_id, attempt_no) pair)."""
    out = dict(ev)
    out["effect_id"] = str(effect_id)
    out["attempt_no"] = attempt_no
    return out


def takeover(conn, session_id, evidence: dict | None = None, cmd: str = None,
             driver: str = DRIVER, declared_hash: str = None) -> dict:
    return recovery_takeover(conn, session_id, cmd or f"tko-{u()[:8]}",
                             driver, EPOCH, evidence=evidence,
                             declared_hash=declared_hash)


def set_job_lease(conn, effect_id, owner: str = "w1", seconds: int = 60) -> None:
    exec_sql_local(
        conn,
        "UPDATE effect_requests SET lease_owner=%s,"
        " lease_until=now() + make_interval(secs => %s) WHERE effect_id=%s",
        (owner, seconds, effect_id))


def expire_job_lease(conn, effect_id) -> None:
    exec_sql_local(
        conn,
        "UPDATE effect_requests SET lease_until=now() - interval '10 seconds'"
        " WHERE effect_id=%s", (effect_id,))


def expire_session_lease(conn, session_id) -> None:
    exec_sql_local(
        conn,
        "UPDATE sessions SET lease_until=now() - interval '10 seconds'"
        " WHERE session_id=%s", (session_id,))


def exec_sql_local(conn, sql: str, params: tuple = ()) -> None:
    with conn.cursor() as cur:
        cur.execute(sql, params)
    conn.commit()


def succeed_decision(conn, fx) -> dict:
    return complete_effect(
        conn, fx["session"], f"cmp-{u()[:8]}", fx["effect"], DRIVER, EPOCH,
        dispatch_session_fence=2, job_fence=fx["job_fence"],
        step_id=fx["step"], attempt_no=1, request_hash=fx["rh"],
        idempotency_key=fx["ik"], outcome="succeeded", message={"text": "ok"},
        tools=[], decision_only=True, final_tools=False,
        evidence=good_evidence())


def snapshot_domain_ok(conn, session_id) -> int:
    """Dual-table contract over the SNAPSHOT domain only (the control
    fence current_job_fence is deliberately outside it — after a
    no-allocation takeover advance it legitimately differs from the
    attempt's frozen dispatch_job_fence)."""
    return one(conn,
               "SELECT count(*) FROM effect_requests er"
               " JOIN LATERAL (SELECT * FROM effect_attempts a"
               "   WHERE a.effect_id = er.effect_id"
               "   ORDER BY attempt_no DESC LIMIT 1) a ON true"
               " WHERE er.session_id = %s"
               "   AND (er.status <> a.status OR er.attempt_no <> a.attempt_no"
               "    OR er.session_fence <> a.session_fence"
               "    OR er.dispatch_session_fence <> a.dispatch_session_fence)",
               (session_id,))[0]


def snap(conn, fx) -> dict:
    """Comparable three-layer terminal snapshot for the two-entry test
    (fences/hashes/receipt ids are per-path values and excluded)."""
    effects = []
    for e in (fx["effects"] if fx["kind"] == "tools"
              else [{"effect_id": fx["effect"]}]):
        er = effect_row(conn, e["effect_id"])
        att = attempt_rows(conn, e["effect_id"])
        dc = one(conn, "SELECT dispatch_count FROM effect_requests"
                       " WHERE effect_id=%s", (e["effect_id"],))[0]
        effects.append({
            "status": er[0], "attempt_no": er[1], "stop_reason": er[5],
            "n_attempts": len(att), "old_status": att[0][1],
            "old_superseded": att[0][2], "new_status": att[-1][1],
            "identity_reuse": att[0][4] == att[-1][4]
                              and att[0][5] == att[-1][5],
            "fences_increase": att[0][3] < att[-1][3],
            "dispatch_count": dc})
    return {"effects": effects, "step": step_row(conn, fx["step"]),
            "session": session_row(conn, fx["session"])}


# ---------------------------------------------------------------------------
# 1. Unknown branch (no new attempt): fence split, stale-reject, budget
# ---------------------------------------------------------------------------

def test_unknown_branch(conn) -> None:
    fx = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=3)
    old_jf = fx["job_fence"]
    r = takeover(conn, fx["session"])
    rec = r["receipt"]
    tk = [a for a in rec["attempts"] if a["disposition"] == "taken_over"]
    check("no-evidence takeover accepted, one taken-over attempt",
          r["outcome"] == "accepted" and len(tk) == 1, rec)
    check("result-less takeover classifies unknown (never known failure)",
          tk[0]["classification"] == "unknown"
          and tk[0]["settled_status"] == "unknown_outcome", tk[0])
    check("receipt records the fence advance and the lease revocation",
          tk[0]["old_job_fence"] == old_jf
          and tk[0]["new_job_fence"] > old_jf, tk[0])
    er = effect_row(conn, fx["effect"])
    att = attempt_rows(conn, fx["effect"])
    check("effect unknown_outcome, fence advanced, no stop reason",
          er[0] == "unknown_outcome" and er[2] > old_jf and er[5] is None, er)
    check("fence dual-field split: attempt dispatch_job_fence unchanged",
          len(att) == 1 and att[0][3] == old_jf
          and att[0][1] == "unknown_outcome", att)
    check("control fence now differs from the frozen attempt fence",
          er[2] != att[0][3], (er, att))
    check("step/session blocked_unknown_effect",
          step_row(conn, fx["step"])[0] == "blocked_unknown_effect"
          and session_row(conn, fx["session"])[0] == "blocked_unknown_effect")
    check("unique provisional turn/end + provisional slot",
          one(conn, "SELECT count(*) FROM session_events"
                    " WHERE session_id=%s AND event_type='turn/end'",
              (fx["session"],))[0] == 1
          and one(conn, "SELECT slot_status FROM turn_end_slots"
                        " WHERE session_id=%s", (fx["session"],))[0]
          == "provisional")

    # Old worker completion (old fence) -> STALE_JOB_FENCE, zero control.
    r2 = fail_decision(conn, fx, attempt_no=1, job_fence=old_jf,
                       declared="succeeded")
    check("old-fence completion -> rejected_stale STALE_JOB_FENCE",
          r2["outcome"] == "rejected_stale"
          and r2["code"] == "STALE_JOB_FENCE", r2)
    check("stale completion audit row written",
          one(conn, "SELECT count(*) FROM effect_audit"
                    " WHERE effect_id=%s AND reason='STALE_JOB_FENCE'",
              (fx["effect"],))[0] == 1)
    check("stale completion: zero control state (unknown terminal kept)",
          effect_row(conn, fx["effect"])[0] == "unknown_outcome"
          and step_row(conn, fx["step"])[0] == "blocked_unknown_effect"
          and session_row(conn, fx["session"])[0] == "blocked_unknown_effect")
    # A completion naming the unknown attempt with the CURRENT fence:
    # repair is the only exit for unknown (G7c).
    new_jf = effect_row(conn, fx["effect"])[2]
    r3 = fail_decision(conn, fx, attempt_no=1, job_fence=new_jf)
    check("current-fence completion on unknown attempt -> repair_required",
          r3["outcome"] == "repair_required"
          and r3["code"] == "REPAIR_REQUIRED", r3)
    check("dual-table snapshot contract holds (fence excluded)",
          snapshot_domain_ok(conn, fx["session"]) == 0)

    # Budget exhaustion / unsafe class NEVER yields a known terminal
    # failure from a result-less takeover.
    fx = decision_fx(conn, retry_class="unsafe", max_attempts=1)
    r = takeover(conn, fx["session"])
    check("unsafe zero-budget takeover still settles unknown_outcome",
          r["outcome"] == "accepted"
          and effect_row(conn, fx["effect"])[0] == "unknown_outcome", r)
    check("no terminal failure derived (session blocked, not failed)",
          session_row(conn, fx["session"]) == ("blocked_unknown_effect", None)
          and effect_row(conn, fx["effect"])[5] is None)

    # known_success evidence at the takeover defers to repair (G7b scope):
    # conservative unknown settlement with the annotation recorded.
    fx = decision_fx(conn, retry_class="provider_idempotent", max_attempts=3)
    r = takeover(conn, fx["session"], evidence={
        fx["effect"]: bound(
            {"class": "known_success",
             "provider_receipt": {"receipt_id": f"sr-{u()[:6]}"}},
            fx["effect"])})
    tk = r["receipt"]["attempts"][0]
    check("success evidence deferred to repair, settles unknown",
          r["outcome"] == "accepted" and tk["classification"] == "unknown"
          and tk["note"] == "known_success_deferred_to_repair"
          and effect_row(conn, fx["effect"])[0] == "unknown_outcome", tk)


# ---------------------------------------------------------------------------
# 2. Job lease guard (session lease expired x job lease valid)
# ---------------------------------------------------------------------------

def test_job_lease_guard(conn) -> None:
    fx = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=3)
    set_job_lease(conn, fx["effect"], "worker-1", 60)
    r1 = recovery_claim_session(conn, fx["session"], DRIVER, EPOCH,
                                lease_owner="coord", lease_seconds=60)
    check("fixture: recovery claim taken (state untouched)",
          r1["outcome"] == "claimed" and r1["purpose"] == "recovery", r1)
    expire_session_lease(conn, fx["session"])

    r = takeover(conn, fx["session"])
    rec = r["receipt"]
    check("session lease expired x job lease valid -> takeover accepted",
          r["outcome"] == "accepted", r)
    check("the attempt is skipped (not taken over)",
          len(rec["attempts"]) == 1
          and rec["attempts"][0]["disposition"] == "skipped_lease_valid"
          and rec["attempts"][0]["lease_owner"] == "worker-1", rec["attempts"])
    er = effect_row(conn, fx["effect"])
    att = attempt_rows(conn, fx["effect"])
    check("skip: no fence advance, attempt untouched",
          er[0] == "dispatch_started" and er[2] == fx["job_fence"]
          and att[0][1] == "dispatch_started" and att[0][3] == fx["job_fence"],
          (er, att))
    check("skip: step/session control state unchanged (recovery lease kept)",
          step_row(conn, fx["step"])[0] == "waiting_effect"
          and one(conn, "SELECT state, lease_owner FROM sessions"
                        " WHERE session_id=%s", (fx["session"],))
          == ("waiting_effect", "coord"))
    check("skip: no settlement writes (no events, no evidence)",
          one(conn, "SELECT count(*) FROM session_events"
                    " WHERE session_id=%s", (fx["session"],))[0] == 0
          and one(conn, "SELECT count(*) FROM effect_evidence"
                        " WHERE effect_id=%s", (fx["effect"],))[0] == 0)
    rc = succeed_decision(conn, fx)
    check("later legal completion is accepted normally",
          rc["outcome"] == "accepted"
          and effect_row(conn, fx["effect"])[0] == "succeeded", rc)

    # Job lease expiry then a rescan: the takeover processes the attempt.
    fx = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=3)
    set_job_lease(conn, fx["effect"], "worker-2", 60)
    r = takeover(conn, fx["session"])
    check("live lease again -> skipped (rescan waits)",
          r["receipt"]["attempts"][0]["disposition"] == "skipped_lease_valid",
          r["receipt"])
    expire_job_lease(conn, fx["effect"])
    r = takeover(conn, fx["session"])
    check("job lease expired -> rescan takes over",
          r["outcome"] == "accepted"
          and r["receipt"]["attempts"][0]["disposition"] == "taken_over"
          and r["receipt"]["attempts"][0]["new_job_fence"] > fx["job_fence"],
          r["receipt"]["attempts"])


# ---------------------------------------------------------------------------
# 3. Two-entry comparison: pure eligible batch (Conformance 2(4)/(6))
# ---------------------------------------------------------------------------

def test_two_entry_pure_eligible(conn) -> None:
    specs = [("verifiable_no_effect", 3), ("verifiable_no_effect", 3)]

    # Path 1: normal completion -> failed_retryable -> retry_effect.
    fx1 = tools_fx(conn, specs)
    fail_tool(conn, fx1, 0)
    fail_tool(conn, fx1, 1)
    check("path 1 fixture: rule 5 after both failures",
          step_row(conn, fx1["step"])[0] == "failed_retryable")
    rr = retry(conn, fx1)
    check("path 1: retry_effect allocated the cohort",
          rr["outcome"] == "accepted"
          and len(rr["receipt"]["effects"]) == 2, rr)
    f1 = {e["effect_id"]: e["job_fence"] for e in rr["receipt"]["effects"]}
    for i, e in enumerate(fx1["effects"]):
        rd = dispatch_effect(conn, fx1["session"], f"dsp-{u()[:8]}",
                             e["effect_id"], DRIVER, EPOCH,
                             fx1["post_seal_fence"], f1[e["effect_id"]])
        check(f"path 1 tool {i} attempt-2 dispatch accepted",
              rd["outcome"] == "accepted", rd)
    fail_tool(conn, fx1, 0, attempt_no=2, job_fence=f1[fx1["effects"][0]["effect_id"]])
    succeed_tool(conn, fx1, 1, attempt_no=2,
                 job_fence=f1[fx1["effects"][1]["effect_id"]])
    s1 = snap(conn, fx1)

    # Path 2: recovery takeover with equivalent bound failure evidence.
    fx2 = tools_fx(conn, specs)
    for e in fx2["effects"]:
        expire_job_lease(conn, e["effect_id"])
    ev = {e["effect_id"]: bound(fail_evidence(), e["effect_id"], 1)
          for e in fx2["effects"]}
    tk = takeover(conn, fx2["session"], evidence=ev)
    check("path 2: takeover accepted", tk["outcome"] == "accepted", tk)
    st0 = tk["receipt"]["steps"][0]
    check("path 2: rule-5 judgment allocated the cohort in-transaction",
          st0["allocated"] is True and len(st0["effects"]) == 2, st0)
    check("path 2: attempts settled known_failure -> failed_retryable",
          all(a["disposition"] == "taken_over"
              and a["classification"] == "known_failure"
              and a["settled_status"] == "failed_retryable"
              for a in tk["receipt"]["attempts"]),
          tk["receipt"]["attempts"])
    check("path 2: dual evidence persisted per attempt",
          one(conn, "SELECT count(*) FROM effect_evidence ee"
                    " WHERE ee.effect_id IN (SELECT effect_id"
                    "  FROM effect_requests WHERE session_id=%s)",
              (fx2["session"],))[0] == 4)
    check("path 2: post-allocation rule 2 (MUST NOT derive session ready)",
          step_row(conn, fx2["step"])[0] == "waiting_effect"
          and session_row(conn, fx2["session"])[0] == "waiting_effect")
    f2 = {e["effect_id"]: e["job_fence"] for e in st0["effects"]}
    for i, e in enumerate(fx2["effects"]):
        rd = dispatch_effect(conn, fx2["session"], f"dsp-{u()[:8]}",
                             e["effect_id"], DRIVER, EPOCH,
                             fx2["post_seal_fence"], f2[e["effect_id"]])
        check(f"path 2 tool {i} attempt-2 dispatch accepted",
              rd["outcome"] == "accepted", rd)
    fail_tool(conn, fx2, 0, attempt_no=2,
              job_fence=f2[fx2["effects"][0]["effect_id"]])
    succeed_tool(conn, fx2, 1, attempt_no=2,
                 job_fence=f2[fx2["effects"][1]["effect_id"]])
    s2 = snap(conn, fx2)

    check("two-entry: identical three-layer terminal states/codes/counts",
          s1 == s2, (s1, s2))

    # Single-effect recovery allocation assertion (Conformance 2):
    # effect ready + new attempt allocated, step waiting_effect, session
    # waiting_effect; then the late-completion family over the old era.
    fx = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=3)
    expire_job_lease(conn, fx["effect"])
    tk = takeover(conn, fx["session"],
                  evidence={fx["effect"]: bound(fail_evidence(), fx["effect"])})
    check("single-effect takeover allocation accepted",
          tk["outcome"] == "accepted"
          and tk["receipt"]["steps"][0]["allocated"] is True, tk)
    er = effect_row(conn, fx["effect"])
    att = attempt_rows(conn, fx["effect"])
    check("effect ready with the new attempt, old attempt superseded",
          er[0] == "ready" and er[1] == 2 and len(att) == 2
          and att[0][2] == 2 and att[0][1] == "failed_retryable"
          and att[1][1] == "ready" and att[1][2] is None, (er, att))
    check("step/session waiting_effect (not ready)",
          step_row(conn, fx["step"])[0] == "waiting_effect"
          and session_row(conn, fx["session"])[0] == "waiting_effect")
    check("superseded marker only written when a new attempt exists "
          "(write-once, points forward)",
          att[0][2] == 2 and att[0][3] == fx["job_fence"])

    r = fail_decision(conn, fx, attempt_no=1, job_fence=fx["job_fence"],
                      declared="succeeded")
    check("old-era completion after takeover -> STALE_JOB_FENCE",
          r["outcome"] == "rejected_stale" and r["code"] == "STALE_JOB_FENCE",
          r)
    r = fail_decision(conn, fx, attempt_no=1, job_fence=er[2])
    check("superseded attempt + current fence -> ATTEMPT_SUPERSEDED",
          r["outcome"] == "rejected_stale"
          and r["code"] == "ATTEMPT_SUPERSEDED", r)
    check("late completions left zero control state (attempt 2 ready)",
          effect_row(conn, fx["effect"])[0] == "ready"
          and len(attempt_rows(conn, fx["effect"])) == 2)


# ---------------------------------------------------------------------------
# 4. Sibling blockers through the recovery entry (unknown / pending)
# ---------------------------------------------------------------------------

def test_sibling_blockers(conn) -> None:
    # unknown sibling: settle-only, no allocation (Conformance 2(3)).
    fx = tools_fx(conn, [("verifiable_no_effect", 3),
                   ("verifiable_no_effect", 3)])
    for e in fx["effects"]:
        expire_job_lease(conn, e["effect_id"])
    ev = {fx["effects"][0]["effect_id"]:
          bound(fail_evidence(), fx["effects"][0]["effect_id"])}
    tk = takeover(conn, fx["session"], evidence=ev)
    st0 = tk["receipt"]["steps"][0]
    check("unknown sibling -> rule 1, settle-only",
          tk["outcome"] == "accepted" and st0["allocated"] is False
          and st0["rule_no"] == 1, st0)
    check("A failed_retryable, B unknown_outcome",
          effect_row(conn, fx["effects"][0]["effect_id"])[0]
          == "failed_retryable"
          and effect_row(conn, fx["effects"][1]["effect_id"])[0]
          == "unknown_outcome")
    check("zero allocation (one attempt row per effect)",
          one(conn, "SELECT count(*) FROM effect_attempts a"
                    " JOIN effect_requests er ON er.effect_id = a.effect_id"
                    " WHERE er.batch_id = %s",
              (fx["batch_id"],))[0] == 2)
    check("step/session blocked_unknown_effect",
          step_row(conn, fx["step"])[0] == "blocked_unknown_effect"
          and session_row(conn, fx["session"])[0] == "blocked_unknown_effect")

    # pending sibling (a lease-valid skip keeps the attempt in-flight):
    # rule 2, settle-only, no allocation.
    fx = tools_fx(conn, [("verifiable_no_effect", 3),
                   ("verifiable_no_effect", 3)])
    set_job_lease(conn, fx["effects"][0]["effect_id"], "w0", 60)
    expire_job_lease(conn, fx["effects"][1]["effect_id"])
    ev = {fx["effects"][1]["effect_id"]:
          bound(fail_evidence(), fx["effects"][1]["effect_id"])}
    tk = takeover(conn, fx["session"], evidence=ev)
    st0 = tk["receipt"]["steps"][0]
    check("pending sibling (lease-valid skip) -> rule 2, settle-only",
          tk["outcome"] == "accepted" and st0["allocated"] is False
          and st0["rule_no"] == 2, st0)
    disps = [a["disposition"] for a in tk["receipt"]["attempts"]]
    check("one skip + one takeover in the same command",
          sorted(disps) == ["skipped_lease_valid", "taken_over"], disps)
    check("settled sibling failed_retryable, skipped still dispatch_started",
          effect_row(conn, fx["effects"][1]["effect_id"])[0]
          == "failed_retryable"
          and effect_row(conn, fx["effects"][0]["effect_id"])[0]
          == "dispatch_started")
    check("zero allocation, step/session waiting_effect",
          one(conn, "SELECT count(*) FROM effect_attempts a"
                    " JOIN effect_requests er ON er.effect_id = a.effect_id"
                    " WHERE er.batch_id = %s",
              (fx["batch_id"],))[0] == 2
          and step_row(conn, fx["step"])[0] == "waiting_effect"
          and session_row(conn, fx["session"])[0] == "waiting_effect")


# ---------------------------------------------------------------------------
# 5. Guards + receipt idempotency
# ---------------------------------------------------------------------------

def test_guards(conn) -> None:
    fx = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=3)
    r = takeover(conn, fx["session"], driver="rogue")
    check("wrong driver -> DRIVER_EPOCH_STALE",
          r["outcome"] == "rejected_stale"
          and r["code"] == "DRIVER_EPOCH_STALE", r)
    r = takeover(conn, fx["session"], declared_hash="0" * 64)
    check("declared-hash mismatch -> REQUEST_HASH_MISMATCH",
          r["outcome"] == "rejected_mismatch"
          and r["code"] == "REQUEST_HASH_MISMATCH", r)
    check("rejections: zero control state",
          effect_row(conn, fx["effect"])[0] == "dispatch_started"
          and effect_row(conn, fx["effect"])[2] == fx["job_fence"])

    cmd = f"tko-{u()[:8]}"
    r1 = takeover(conn, fx["session"], cmd=cmd)
    check("takeover executed (unknown branch)", r1["outcome"] == "accepted",
          r1)
    r2 = takeover(conn, fx["session"], cmd=cmd)
    check("same command_id replays the original receipt",
          r2["outcome"] == "accepted" and r2["receipt"] == r1["receipt"], r2)
    r3 = takeover(conn, fx["session"], cmd=cmd,
                  evidence={fx["effect"]: bound(fail_evidence(), fx["effect"])})
    check("same command_id different payload -> IDEMPOTENCY_CONFLICT",
          r3["outcome"] == "rejected_mismatch"
          and r3["code"] == "IDEMPOTENCY_CONFLICT", r3)

    # Terminal session: refused (also the gate's session-terminal leg).
    fx2 = decision_fx(conn, retry_class="unsafe", max_attempts=1)
    fail_decision(conn, fx2)
    check("fixture: session failed", session_row(conn, fx2["session"])[0]
          == "failed")
    r = takeover(conn, fx2["session"])
    check("terminal session -> SESSION_TERMINAL",
          r["outcome"] == "rejected_mismatch"
          and r["code"] == "SESSION_TERMINAL", r)

    # Sticky cancel (G8b): NO LONGER a structural refusal. The takeover is
    # trigger source (δ) — the taken-over known failure settles through the
    # shared retry_eligible split and the shared cancel closure
    # (aggregation rule 3 + the shared sub-operation) closes it in the same
    # transaction: effect cancelled_after_dispatch + RETRY_SUPPRESSED_BY_CANCEL
    # audit, step/session cancelled/CANCELLED_BY_REQUEST, and the canonical
    # turn/end derived by the shared derivation.
    fx3 = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=3)
    exec_sql_local(conn, "UPDATE sessions SET cancellation_epoch=1"
                         " WHERE session_id=%s", (fx3["session"],))
    r = takeover(conn, fx3["session"],
                 evidence={fx3["effect"]: bound(fail_evidence(),
                                                fx3["effect"])})
    check("sticky cancel + known_failure -> in-transaction closure (accepted)",
          r["outcome"] == "accepted", r)
    check("sticky closure: effect cancelled_after_dispatch, step/session "
          "cancelled/CANCELLED_BY_REQUEST",
          effect_row(conn, fx3["effect"])[0] == "cancelled_after_dispatch"
          and step_row(conn, fx3["step"])[0:2]
          == ("cancelled", "CANCELLED_BY_REQUEST")
          and session_row(conn, fx3["session"])
          == ("cancelled", "CANCELLED_BY_REQUEST"),
          (effect_row(conn, fx3["effect"]), step_row(conn, fx3["step"]),
           session_row(conn, fx3["session"])))
    check("sticky closure: RETRY_SUPPRESSED_BY_CANCEL audit written",
          one(conn, "SELECT count(*) FROM effect_audit WHERE effect_id=%s"
                    " AND reason='RETRY_SUPPRESSED_BY_CANCEL'",
              (fx3["effect"],))[0] == 1)
    check("sticky closure: derived turn/end cancelled_by_request_after_dispatch",
          r["receipt"]["derived_turn_end"]["reason"]
          == "cancelled_by_request_after_dispatch", r["receipt"])
    check("sticky closure: no new attempt allocated (attempt_no stays 1)",
          effect_row(conn, fx3["effect"])[1] == 1)

    # Quiescing gate — G18 (A37 remaining leg): the known_failure
    # disposition under quiescing settles through the §3.2.2 controlled
    # edge (failed_terminal + RETRY_STOPPED_BY_CLOSURE + not_retry_eligible,
    # no new attempt), no longer a structural whole-command refusal.
    fx5 = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=3)
    exec_sql_local(conn, "UPDATE sessions SET driver_mode='quiescing'"
                         " WHERE session_id=%s", (fx5["session"],))
    r = takeover(conn, fx5["session"],
                 evidence={fx5["effect"]: bound(fail_evidence(),
                                                fx5["effect"])})
    tk5 = [a for a in r["receipt"]["attempts"]
           if a["disposition"] == "taken_over"]
    check("quiescing + known_failure -> controlled-edge settlement"
          " (failed_terminal, no new attempt)",
          r["outcome"] == "accepted"
          and len(tk5) == 1
          and tk5[0]["settled_status"] == "failed_terminal"
          and effect_row(conn, fx5["effect"])[0] == "failed_terminal"
          and effect_row(conn, fx5["effect"])[1] == 1, r)
    check("quiescing controlled edge: RETRY_STOPPED_BY_CLOSURE audit"
          " + not_retry_eligible + rule-4 session closure",
          one(conn, "SELECT count(*) FROM effect_audit WHERE effect_id=%s"
                    " AND reason='RETRY_STOPPED_BY_CLOSURE'",
              (fx5["effect"],))[0] == 1
          and one(conn, "SELECT retry_stop_reason FROM effect_requests"
                        " WHERE effect_id=%s", (fx5["effect"],))[0]
          == "not_retry_eligible"
          and session_row(conn, fx5["session"])[0] == "failed", r)
    exec_sql_local(conn, "UPDATE sessions SET driver_mode='active'"
                         " WHERE session_id=%s", (fx5["session"],))

    # No in-flight attempts: accepted scan with nothing to do.
    fx4 = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=3)
    rc = succeed_decision(conn, fx4)
    check("fixture: effect settled", rc["outcome"] == "accepted", rc)
    r = takeover(conn, fx4["session"])
    check("no in-flight attempts -> accepted empty scan",
          r["outcome"] == "accepted" and r["receipt"]["attempts"] == []
          and r["receipt"]["steps"] == [], r["receipt"])
    check("unused evidence keys surfaced (non-target entry)",
          takeover(conn, fx4["session"],
                   evidence={u(): bound(fail_evidence(), u())})
          ["receipt"]["evidence_unused"] != [])


# ---------------------------------------------------------------------------
# 6. Chaos: takeover transaction killed before commit, rerun converges
# ---------------------------------------------------------------------------

def test_chaos_kill_takeover(conn) -> None:
    # (a) allocation branch
    fx = tools_fx(conn, [("verifiable_no_effect", 3),
                   ("verifiable_no_effect", 3)])
    for e in fx["effects"]:
        expire_job_lease(conn, e["effect_id"])
    ev = {e["effect_id"]: bound(fail_evidence(), e["effect_id"], 1)
          for e in fx["effects"]}
    real = psycopg2.connect(uri())
    dying = DyingConnection(real)
    try:
        takeover(dying, fx["session"], evidence=ev)
        check("dying takeover raised ProcessDeath", False, "committed")
    except ProcessDeath:
        check("dying takeover raised ProcessDeath", True)
    finally:
        real.close()
    for e in fx["effects"]:
        er = effect_row(conn, e["effect_id"])
        att = attempt_rows(conn, e["effect_id"])
        check(f"kill rollback: {e['effect_id'][:8]} untouched",
              er[0] == "dispatch_started" and er[2] == e["job_fence"]
              and len(att) == 1 and att[0][2] is None, (er, att))
    check("kill rollback: no evidence persisted",
          one(conn, "SELECT count(*) FROM effect_evidence ee"
                    " WHERE ee.effect_id IN (SELECT effect_id"
                    " FROM effect_requests WHERE session_id=%s)",
              (fx["session"],))[0] == 0)
    check("kill rollback: step keeps waiting_effect",
          step_row(conn, fx["step"])[0] == "waiting_effect")
    tk = takeover(conn, fx["session"], evidence=ev)
    check("rerun allocates the cohort", tk["outcome"] == "accepted"
          and tk["receipt"]["steps"][0]["allocated"] is True, tk)
    for e in fx["effects"]:
        att = attempt_rows(conn, e["effect_id"])
        check(f"converged: exactly attempts 1,2 for {e['effect_id'][:8]}",
              [a[0] for a in att] == [1, 2] and att[0][2] == 2
              and att[1][2] is None, att)
    dup = one(conn,
              "SELECT count(*) FROM (SELECT effect_id, dispatch_job_fence"
              "   FROM effect_attempts WHERE session_id=%s"
              "   GROUP BY effect_id, dispatch_job_fence"
              "   HAVING count(*) > 1) d", (fx["session"],))[0]
    check("UNIQUE(effect_id, dispatch_job_fence) convergence", dup == 0, dup)

    # (b) unknown branch
    fx = decision_fx(conn, retry_class="provider_idempotent", max_attempts=3)
    expire_job_lease(conn, fx["effect"])
    real = psycopg2.connect(uri())
    dying = DyingConnection(real)
    try:
        takeover(dying, fx["session"])
        check("dying unknown takeover raised ProcessDeath", False, "committed")
    except ProcessDeath:
        check("dying unknown takeover raised ProcessDeath", True)
    finally:
        real.close()
    check("kill rollback: attempt still in-flight, no provisional end",
          effect_row(conn, fx["effect"])[0] == "dispatch_started"
          and one(conn, "SELECT count(*) FROM session_events"
                        " WHERE session_id=%s AND event_type='turn/end'",
                  (fx["session"],))[0] == 0
          and one(conn, "SELECT count(*) FROM turn_end_slots"
                        " WHERE session_id=%s", (fx["session"],))[0] == 0)
    tk = takeover(conn, fx["session"])
    check("rerun settles unknown_outcome",
          tk["outcome"] == "accepted"
          and effect_row(conn, fx["effect"])[0] == "unknown_outcome", tk)
    check("exactly one provisional end after convergence",
          one(conn, "SELECT count(*) FROM session_events"
                    " WHERE session_id=%s AND event_type='turn/end'",
              (fx["session"],))[0] == 1
          and one(conn, "SELECT count(*) FROM turn_end_slots"
                        " WHERE session_id=%s", (fx["session"],))[0] == 1)
    check("dual-table snapshot contract holds after convergence",
          snapshot_domain_ok(conn, fx["session"]) == 0)


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def main() -> int:
    check("setup", setup_db() == 0)
    conn = psycopg2.connect(uri())
    try:
        test_unknown_branch(conn)
        test_job_lease_guard(conn)
        test_two_entry_pure_eligible(conn)
        test_sibling_blockers(conn)
        test_guards(conn)
        test_chaos_kill_takeover(conn)
    finally:
        conn.close()
    print("[G7b] all gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
