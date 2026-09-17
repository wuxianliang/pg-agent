"""G19b gate: v8 closeout — the wait/wake layer, the attempt/heartbeat
split, FORCE_JOB_TAKEOVER, the reconcile result-receipt entry, the
create-when-absent slot, cross-attempt residue, the real lease window,
the credential-missing regression and the capability API boundary (DB
half).

Plan docs/plans/v8-remaining-milestones-plan-2026-09-16.md G19 D7–D15.

Run: uv run python v8/closeout/test_closeout.py  (exit 0 = pass)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v8.effect.client import (
    claim_session,
    complete_effect,
    dispatch_effect,
    prepare_step,
    recovery_claim_session,
)
from v8.events.client import create_session
from v8.grant.fixtures import u
from v8.closeout.setup_db import DB, main as setup_db
from v8.repair.client import repair
from v8.retry.client import recovery_takeover
from v8.retry.test_retry import (
    DRIVER,
    EPOCH,
    check,
    fail_evidence,
    good_evidence,
    one,
    rows,
    session_row,
    step_row,
    tools_fx,
)

SV, CV = "sv@1", "canon@1"


def _uri() -> str:
    return get_server().get_uri(DB)


def exec_sql(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
    conn.commit()


def call(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        out = cur.fetchone()
    conn.commit()
    return out


def seal_only_fx(conn, driver=DRIVER):
    s = u()
    turn, step, eff = u(), u(), u()
    rh, ik = f"rh-{u()[:10]}", f"ik-{u()[:10]}"
    create_session(conn, s, driver)
    r0 = claim_session(conn, s, driver, lease_owner="op")
    rs = prepare_step(conn, s, f"seal-{u()[:8]}", driver, EPOCH,
                      r0["session_fence"], step, turn, eff,
                      request_hash=rh, idempotency_key=ik,
                      execution_mode="streaming")
    check("fx seal accepted", rs["outcome"] == "accepted", rs)
    return {"session": s, "turn": turn, "step": step, "effect": eff,
            "rh": rh, "ik": ik, "claim_fence": r0["session_fence"],
            "seal_fence": rs["receipt"]["session_fence"],
            "job_fence": rs["receipt"]["job_fence"]}


def dispatch_only_fx(conn, driver=DRIVER):
    fx = seal_only_fx(conn, driver)
    r = dispatch_effect(conn, fx["session"], f"dsp-{u()[:8]}", fx["effect"],
                        driver, EPOCH, fx["seal_fence"], fx["job_fence"])
    check("fx dispatch accepted", r["outcome"] == "accepted", r)
    return fx


def canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


# ---------------------------------------------------------------------------
# D7: transition_wait + the scan (NOTIFY only a hint)
# ---------------------------------------------------------------------------

def test_wait_layer(conn) -> None:
    s = u()
    create_session(conn, s, DRIVER)
    r0 = claim_session(conn, s, DRIVER, lease_owner="w")

    # Satisfied in the same transaction -> not waiting, no row, lease kept.
    r1 = call(conn, "SELECT v_transition_wait(%s::uuid, %s, %s, 1, %s,"
                   " %s::jsonb, 1)",
              (s, f"wt-{u()[:8]}", DRIVER, r0["session_fence"],
               canon({"kind": "seq_at_least", "value": 0})))
    check("satisfied predicate -> not waiting, lease kept",
          r1[0]["outcome"] == "accepted" and r1[0]["waiting"] is False
          and one(conn, "SELECT count(*) FROM wait_registrations"
                        " WHERE session_id=%s", (s,))[0] == 0
          and one(conn, "SELECT lease_owner FROM sessions"
                        " WHERE session_id=%s", (s,))[0] == "w", r1)

    # Unsatisfied -> the wait row persists, lease released, waiting_event.
    fence = one(conn, "SELECT session_fence FROM sessions"
                      " WHERE session_id=%s", (s,))[0]
    r2 = call(conn, "SELECT v_transition_wait(%s::uuid, %s, %s, 1, %s,"
                   " %s::jsonb, 1)",
              (s, f"wt-{u()[:8]}", DRIVER, fence,
               canon({"kind": "seq_at_least", "value": 5})))
    check("unsatisfied predicate -> waiting, lease released, fence+1",
          r2[0]["waiting"] is True
          and one(conn, "SELECT state, lease_owner FROM sessions"
                        " WHERE session_id=%s", (s,))
          == ("waiting_event", None)
          and r2[0]["session_fence"] == fence + 1, r2)

    # The completion side never woke it; the SCAN (no NOTIFY at all)
    # recovers: append an event, rerun the scan -> ready.
    check("wait scan idempotent before the predicate holds",
          call(conn, "SELECT v_wait_scan()")[0]["woken"] == 0)
    exec_sql(conn, "UPDATE sessions SET next_seq=6 WHERE session_id=%s",
             (s,))
    scan1 = call(conn, "SELECT v_wait_scan()")[0]
    check("scan wakes the satisfied wait (NOTIFY lost converges)",
          scan1["woken"] == 1
          and one(conn, "SELECT state FROM sessions"
                        " WHERE session_id=%s", (s,))[0] == "ready"
          and one(conn, "SELECT state FROM wait_registrations"
                        " WHERE session_id=%s", (s,))[0] == "ready", scan1)
    scan2 = call(conn, "SELECT v_wait_scan()")[0]
    check("duplicate scan is a no-op (duplicated NOTIFY converges)",
          scan2["woken"] == 0
          and one(conn, "SELECT state FROM sessions"
                        " WHERE session_id=%s", (s,))[0] == "ready")

    # A timer wait + the expired-claimed recovery both wake through the
    # same scan.
    s2 = u()
    create_session(conn, s2, DRIVER)
    rc = claim_session(conn, s2, DRIVER, lease_owner="w2")
    r3 = call(conn, "SELECT v_transition_wait(%s::uuid, %s, %s, 1, %s,"
                   " %s::jsonb, 1, true)",
              (s2, f"wt-{u()[:8]}", DRIVER, rc["session_fence"],
               canon({"kind": "timer",
                      "wake_at": "2099-01-01T00:00:00Z"})))
    check("sleep form persists a timer wait (state sleeping)",
          r3[0]["waiting"] is True
          and one(conn, "SELECT state FROM sessions"
                        " WHERE session_id=%s", (s2,))[0] == "sleeping", r3)
    scan_pre = call(conn, "SELECT v_wait_scan()")[0]
    check("a future timer wakes nothing yet",
          one(conn, "SELECT state FROM sessions"
                    " WHERE session_id=%s", (s2,))[0] == "sleeping",
          scan_pre)
    # The scanner clock advances (fixture equivalent): the wake time
    # becomes due.
    exec_sql(conn, "UPDATE wait_registrations"
                   " SET predicate=jsonb_build_object("
                   " 'kind','timer','wake_at','2000-01-01T00:00:00Z')"
                   " WHERE session_id=%s", (s2,))
    scan3 = call(conn, "SELECT v_wait_scan()")[0]
    check("due timer wakes through the scan",
          scan3["woken"] == 1
          and one(conn, "SELECT state FROM sessions"
                        " WHERE session_id=%s", (s2,))[0] == "ready")

    s3 = u()
    create_session(conn, s3, DRIVER)
    claim_session(conn, s3, DRIVER, lease_owner="dead")
    exec_sql(conn, "UPDATE sessions SET lease_until=now()"
                   " - interval '10 seconds' WHERE session_id=%s", (s3,))
    scan4 = call(conn, "SELECT v_wait_scan()")[0]
    check("expired claimed lease recovers to ready (fence bumped)",
          scan4["woken"] >= 1
          and one(conn, "SELECT state, lease_owner FROM sessions"
                        " WHERE session_id=%s", (s3,)) == ("ready", None),
          (scan4, one(conn, "SELECT state, lease_owner FROM sessions"
                            " WHERE session_id=%s", (s3,))))

    # The NOTIFY hint fires without carrying authority.
    call(conn, "SELECT v_wait_notify(%s::uuid, 'x')", (s3,))


# ---------------------------------------------------------------------------
# D8: attempt/heartbeat — the four-check split
# ---------------------------------------------------------------------------

def test_attempt_heartbeat(conn) -> None:
    fx = dispatch_only_fx(conn)
    exec_sql(conn, "UPDATE effect_requests SET lease_owner='worker-1',"
                   " lease_until=now() + interval '5 minutes'"
                   " WHERE effect_id=%s", (fx["effect"],))
    jf = one(conn, "SELECT current_job_fence FROM effect_requests"
                   " WHERE effect_id=%s", (fx["effect"],))[0]

    r = call(conn, "SELECT v_attempt_heartbeat(%s::uuid, %s, %s::uuid, 1,"
                   " 'worker-1', %s, '{}')",
             (fx["session"], f"ahb-{u()[:8]}", fx["effect"], jf))
    check("attempt/heartbeat accepted (owner+fence match)",
          r[0]["outcome"] == "accepted" and r[0]["observation_ordinal"] == 1,
          r)
    check("zero control state (no lease/fence/state change)",
          one(conn, "SELECT lease_owner, current_job_fence FROM"
                    " effect_requests WHERE effect_id=%s",
              (fx["effect"],)) == ("worker-1", jf)
          and one(conn, "SELECT session_fence FROM sessions"
                        " WHERE session_id=%s",
                  (fx["session"],))[0] == fx["seal_fence"])

    # (iv) superseded -> rejected_stale. A FRESH fixture (the pointer is
    # write-once): a sibling attempt-2 row exists so the FK-checked
    # superseded pointer can be set.
    fx_s = dispatch_only_fx(conn)
    exec_sql(conn, "UPDATE effect_requests SET lease_owner='w-s',"
                   " lease_until=now() + interval '5 minutes'"
                   " WHERE effect_id=%s", (fx_s["effect"],))
    cols = [r[0] for r in rows(
        conn, "SELECT column_name FROM information_schema.columns"
              " WHERE table_name='effect_attempts'"
              " ORDER BY ordinal_position")]
    sel = ", ".join(
        "2" if c == "attempt_no"
        else ("nextval('v8_job_fence_seq')" if c == "dispatch_job_fence"
              else c) for c in cols)
    exec_sql(conn,
             f"INSERT INTO effect_attempts ({', '.join(cols)})"
             f" SELECT {sel} FROM effect_attempts"
             " WHERE effect_id=%s AND attempt_no=1"
             " ON CONFLICT DO NOTHING", (fx_s["effect"],))
    exec_sql(conn, "UPDATE effect_attempts SET superseded_by_attempt_no=2"
                   " WHERE effect_id=%s AND attempt_no=1", (fx_s["effect"],))
    jf_s = one(conn, "SELECT current_job_fence FROM effect_requests"
                     " WHERE effect_id=%s", (fx_s["effect"],))[0]
    r2 = call(conn, "SELECT v_attempt_heartbeat(%s::uuid, %s, %s::uuid, 1,"
                    " 'w-s', %s, '{}')",
              (fx_s["session"], f"ahb-{u()[:8]}", fx_s["effect"], jf_s))
    check("superseded attempt -> rejected_stale",
          r2[0]["outcome"] == "rejected_stale"
          and r2[0]["code"] == "ATTEMPT_SUPERSEDED", r2)

    # (iii) wrong owner (active mode) -> rejected_stale; quiescing accepts
    # the old-epoch heartbeat with the difference recorded.
    r3 = call(conn, "SELECT v_attempt_heartbeat(%s::uuid, %s, %s::uuid, 1,"
                    " 'not-owner', 999, '{}')",
              (fx["session"], f"ahb-{u()[:8]}", fx["effect"]))
    check("wrong lease owner under active -> rejected_stale",
          r3[0]["outcome"] == "rejected_stale"
          and r3[0]["code"] == "LEASE_OWNER_MISMATCH", r3)
    exec_sql(conn, "UPDATE sessions SET driver_mode='quiescing'"
                   " WHERE session_id=%s", (fx["session"],))
    r4 = call(conn, "SELECT v_attempt_heartbeat(%s::uuid, %s, %s::uuid, 1,"
                    " 'not-owner', 999, '{}')",
              (fx["session"], f"ahb-{u()[:8]}", fx["effect"]))
    check("quiescing old-epoch heartbeat accepted, mismatch recorded",
          r4[0]["outcome"] == "accepted"
          and r4[0].get("epoch_mismatch_recorded") is True, r4)
    exec_sql(conn, "UPDATE sessions SET driver_mode='active'"
                   " WHERE session_id=%s", (fx["session"],))

    # (i) attribution: a foreign session's attempt is not found.
    fx2 = seal_only_fx(conn)
    r5 = call(conn, "SELECT v_attempt_heartbeat(%s::uuid, %s, %s::uuid, 1,"
                    " 'worker-1', 1, '{}')",
              (fx2["session"], f"ahb-{u()[:8]}", fx["effect"]))
    check("foreign-session attempt -> ATTEMPT_NOT_FOUND",
          r5[0]["outcome"] == "rejected_mismatch"
          and r5[0]["code"] == "ATTEMPT_NOT_FOUND", r5)

    # Session lifecycle gate: terminal x attempt terminal rejects (a
    # fresh fixture: the superseded pointer above is write-once).
    fx_l = dispatch_only_fx(conn)
    exec_sql(conn, "UPDATE sessions SET state='failed',"
                   " failure_code='WORKSPACE_LOST'"
                   " WHERE session_id=%s", (fx_l["session"],))
    exec_sql(conn, "UPDATE effect_requests SET status='unknown_outcome'"
                   " WHERE effect_id=%s", (fx_l["effect"],))
    r6 = call(conn, "SELECT v_attempt_heartbeat(%s::uuid, %s, %s::uuid, 1,"
                    " 'worker-1', 1, '{}')",
              (fx_l["session"], f"ahb-{u()[:8]}", fx_l["effect"]))
    check("terminal x non-terminal attempt heartbeat accepted"
          " (failure-drain observation need)",
          r6[0]["outcome"] == "accepted", r6)
    exec_sql(conn, "UPDATE effect_requests SET status='failed_terminal'"
                   " WHERE effect_id=%s", (fx_l["effect"],))
    exec_sql(conn, "UPDATE effect_attempts SET status='failed_terminal'"
                   " WHERE effect_id=%s", (fx_l["effect"],))
    r7 = call(conn, "SELECT v_attempt_heartbeat(%s::uuid, %s, %s::uuid, 1,"
                    " 'worker-1', 1, '{}')",
              (fx_l["session"], f"ahb-{u()[:8]}", fx_l["effect"]))
    check("terminal attempt -> ATTEMPT_TERMINAL", r7[0]["code"]
          == "ATTEMPT_TERMINAL", r7)

    # The public append facade rejects attempt/heartbeat (O01 split: it is
    # an internal observation type, EVENT_TYPE_RESTRICTED).
    from v8.events.client import build_entry, call_append_events
    entry = {"event_type": "attempt/heartbeat", "schema_version": SV,
             "canonicalizer_version": CV, "payload_canonical": "{}",
             "payload_hash": "00" * 32}
    seq = one(conn, "SELECT next_seq FROM sessions WHERE session_id=%s",
              (fx2["session"],))[0]
    ra = call_append_events(conn, fx2["session"], f"ap-{u()[:8]}", DRIVER,
                            EPOCH, seq, [entry])
    check("public append of attempt/heartbeat -> EVENT_TYPE_RESTRICTED",
          ra["outcome"] == "rejected_mismatch"
          and ra["code"] == "EVENT_TYPE_RESTRICTED", ra)


# ---------------------------------------------------------------------------
# D9: FORCE_JOB_TAKEOVER — the five outcomes
# ---------------------------------------------------------------------------

def force(conn, s, cmd, effect, *, fence, owner, operator="op-x",
          reason="stuck worker", driver=DRIVER, epoch=EPOCH,
          payload="{}", declared=None, isolation=None):
    import hashlib
    dh = declared or hashlib.sha256(payload.encode()).hexdigest()
    with conn.cursor() as cur:
        if isolation:
            cur.execute(f"SET TRANSACTION ISOLATION LEVEL {isolation}")
        cur.execute(
            "SELECT outcome, code FROM v_force_job_takeover("
            "%s::uuid, %s, %s, %s, %s, %s, %s::uuid, %s, %s, NULL, %s, %s)",
            (s, cmd, operator, reason, driver, epoch, str(effect),
             fence, owner, dh, payload))
        out = cur.fetchone()
    conn.commit()
    return {"outcome": out[0], "code": out[1]}


def test_force_job_takeover(conn) -> None:
    # (5) isolation gate first: REPEATABLE READ refuses, zero locks.
    fx = dispatch_only_fx(conn)
    exec_sql(conn, "UPDATE effect_requests SET lease_owner='w-live',"
                   " lease_until=now() + interval '5 minutes'"
                   " WHERE effect_id=%s", (fx["effect"],))
    jf = one(conn, "SELECT current_job_fence FROM effect_requests"
                   " WHERE effect_id=%s", (fx["effect"],))[0]
    r5 = force(conn, fx["session"], f"fjt-{u()[:8]}", fx["effect"],
               fence=jf, owner="w-live", isolation="REPEATABLE READ")
    check("(5) REPEATABLE READ -> ISOLATION_UNSUPPORTED",
          r5["outcome"] == "rejected_mismatch"
          and r5["code"] == "ISOLATION_UNSUPPORTED", r5)
    # READ COMMITTED positive control: the same call proceeds.
    cmd = f"fjt-{u()[:8]}"
    r1 = force(conn, fx["session"], cmd, fx["effect"],
               fence=jf, owner="w-live")
    check("(1) READ COMMITTED + live lease -> success (fence advanced,"
          " lease revoked, operator+reason audited)",
          r1["outcome"] == "accepted"
          and one(conn, "SELECT current_job_fence FROM"
                        " effect_requests WHERE effect_id=%s",
                  (fx["effect"],))[0] > jf
          and one(conn, "SELECT lease_owner FROM effect_requests"
                        " WHERE effect_id=%s",
                  (fx["effect"],))[0] is None
          and one(conn, "SELECT count(*) FROM grant_ops_audit"
                        " WHERE action='revoke_grant'"
                        " AND details->>'action'='force_job_takeover'"
                        " AND details->>'reason'='stuck worker'"
                        " AND operator_id='op-x'",
                  (None,))[0] >= 1, r1)

    # Same command_id replays idempotently.
    rr = force(conn, fx["session"], cmd, fx["effect"], fence=jf,
               owner="w-live")
    check("(1) same command_id replays the original receipt",
          rr["outcome"] == "accepted", rr)

    # (2) target missing / terminal.
    fx2 = dispatch_only_fx(conn)
    r2 = force(conn, fx2["session"], f"fjt-{u()[:8]}", u(),
               fence=1, owner="x")
    check("(2) missing target -> EFFECT_NOT_FOUND",
          r2["code"] == "EFFECT_NOT_FOUND", r2)
    exec_sql(conn, "UPDATE effect_requests SET status='failed_terminal'"
                   " WHERE effect_id=%s", (fx2["effect"],))
    r2b = force(conn, fx2["session"], f"fjt-{u()[:8]}", fx2["effect"],
                fence=1, owner="x")
    check("(2) terminal target -> ATTEMPT_ALREADY_SETTLED",
          r2b["code"] == "ATTEMPT_ALREADY_SETTLED", r2b)

    # (3) expected fence / owner mismatch.
    fx3 = dispatch_only_fx(conn)
    exec_sql(conn, "UPDATE effect_requests SET lease_owner='w3',"
                   " lease_until=now() + interval '5 minutes'"
                   " WHERE effect_id=%s", (fx3["effect"],))
    jf3 = one(conn, "SELECT current_job_fence FROM effect_requests"
                    " WHERE effect_id=%s", (fx3["effect"],))[0]
    r3 = force(conn, fx3["session"], f"fjt-{u()[:8]}", fx3["effect"],
               fence=jf3 + 99, owner="w3")
    check("(3) fence mismatch -> JOB_FENCE_STALE",
          r3["outcome"] == "rejected_stale"
          and r3["code"] == "JOB_FENCE_STALE", r3)

    # (4) dead lease -> FORCE_NOT_REQUIRED.
    exec_sql(conn, "UPDATE effect_requests SET lease_until=now()"
                   " - interval '10 seconds' WHERE effect_id=%s",
             (fx3["effect"],))
    r4 = force(conn, fx3["session"], f"fjt-{u()[:8]}", fx3["effect"],
               fence=jf3, owner="w3")
    check("(4) dead lease -> FORCE_NOT_REQUIRED",
          r4["outcome"] == "rejected_mismatch"
          and r4["code"] == "FORCE_NOT_REQUIRED", r4)


# ---------------------------------------------------------------------------
# D10: the reconcile result-receipt entry (X01 + OBSERVATION_WRONG_ENTRY)
# ---------------------------------------------------------------------------

def reconcile_result(conn, s, cmd, effect, *, step, dsf, jf, rh, ik,
                     outcome="succeeded", message=None, tools=None,
                     decision_only=True, final_tools=False, evidence=None,
                     result_payload=None):
    message = message if message is not None else {"text": "final"}
    tools = tools if tools is not None else []
    result_obj = result_payload if result_payload is not None else {
        "message": message, "tools": tools,
        "decision_only": decision_only, "final_tools": final_tools}
    result_canonical = canon(result_obj)
    request = {"command_kind": "complete_effect", "session_id": str(s),
               "command_id": cmd, "effect_id": str(effect), "attempt_no": 1,
               "step_id": str(step), "driver": DRIVER, "driver_epoch": 1,
               "dispatch_session_fence": dsf, "job_fence": jf,
               "request_hash": rh, "idempotency_key": ik,
               "outcome": outcome, "result": result_obj,
               "evidence": evidence}
    import hashlib
    text = canon(request)
    dh = hashlib.sha256(text.encode()).hexdigest()
    ev = json.dumps(evidence, ensure_ascii=False)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT outcome, code, receipt_json FROM v_reconcile_result("
            "%s::uuid, %s, %s::uuid, 1, %s::uuid, %s, 1, %s, %s, %s, %s,"
            " %s, %s, %s, %s, 'sv@1', 'canon@1', %s, %s, %s::jsonb)",
            (str(s), cmd, str(effect), str(step), DRIVER, dsf, jf,
             outcome, rh, ik, result_canonical, canon(message),
             canon(tools), dh, text, ev))
        out = cur.fetchone()
    conn.commit()
    return {"outcome": out[0], "code": out[1], "receipt": out[2]}


def test_reconcile_result(conn) -> None:
    # Quiescing with an in-flight tools effect: the direct terminal
    # completion refuses (W01) but the reconcile entry settles.
    fx = tools_fx(conn, [("verifiable_no_effect", 3)])
    eff = fx["effects"][0]
    exec_sql(conn, "UPDATE sessions SET driver_mode='quiescing'"
                   " WHERE session_id=%s", (fx["session"],))
    from v8.tools.client import complete_tool_effect
    r_direct = complete_tool_effect(
        conn, fx["session"], f"cmp-{u()[:8]}", eff["effect_id"], DRIVER,
        EPOCH, dispatch_session_fence=fx["seal_fence"],
        job_fence=eff["job_fence"], attempt_no=1, step_id=fx["step"],
        request_hash=eff["request_hash"],
        idempotency_key=eff["idempotency_key"], outcome="succeeded",
        tool_call_id=eff["tool_call_id"], output={"ok": 1},
        evidence=good_evidence())
    check("D10 control: direct terminal completion under quiescing"
          " still refuses (W01)",
          r_direct["code"] == "DRIVER_QUIESCING", r_direct)

    tool_result = {"tool_call_id": eff["tool_call_id"],
                   "output": {"ok": 1}}
    r = reconcile_result(conn, fx["session"], f"rcr-{u()[:8]}",
                         eff["effect_id"], step=fx["step"],
                         dsf=fx["seal_fence"], jf=eff["job_fence"],
                         rh=eff["request_hash"], ik=eff["idempotency_key"],
                         outcome="succeeded", message=tool_result,
                         tools=[], decision_only=False, final_tools=True,
                         evidence=good_evidence(),
                         result_payload=tool_result)
    check("D10: the reconcile entry settles under quiescing"
          " (the one legal terminal path)",
          r["outcome"] == "accepted"
          and one(conn, "SELECT status FROM effect_requests"
                        " WHERE effect_id=%s",
                  (eff["effect_id"],))[0] == "succeeded", r)

    # The (iii)/(iv) pending stream form through reconcile is a WRONG
    # ENTRY (fixed code, no observation write).
    fx2 = dispatch_only_fx(conn)  # streaming decision_only effect
    rw = reconcile_result(conn, fx2["session"], f"rcr-{u()[:8]}",
                          fx2["effect"], step=fx2["step"],
                          dsf=2, jf=fx2["job_fence"], rh=fx2["rh"],
                          ik=fx2["ik"], outcome="succeeded",
                          result_payload={"stream_complete": False})
    check("D10: (iii)/(iv) form through reconcile ->"
          " OBSERVATION_WRONG_ENTRY, zero observation writes",
          rw["outcome"] == "rejected_mismatch"
          and rw["code"] == "OBSERVATION_WRONG_ENTRY"
          and one(conn, "SELECT count(*) FROM session_events"
                        " WHERE session_id=%s"
                        " AND event_type='stream_progress'",
                  (fx2["session"],))[0] == 0, rw)

    # The same form through complete_effect's five gates still accepts
    # (the entry split is real).
    from v8.events.client import call_append_events  # noqa: F401
    with conn.cursor() as cur:
        cur.execute(
            "SELECT outcome FROM v_stream_observe("
            "%s::uuid, %s, %s::uuid, 1,"
            " '{\"stream_complete\":false}', 'sv@1', 'canon@1', %s)",
            (fx2["session"], f"obs-{u()[:8]}", fx2["effect"], u()[:12]))
        obs = cur.fetchone()[0]
    conn.commit()
    check("D10: the same form through the five gates accepts",
          obs == "accepted", obs)


# ---------------------------------------------------------------------------
# D11: create-when-absent slot rows (A41)
# ---------------------------------------------------------------------------

def test_slot_create_when_absent(conn) -> None:
    # A turn whose slot ROW is absent while its chain event (the
    # provisional unknown end) exists: the repair creates the row (no
    # REPAIR_TARGET_INVALID) and the closer becomes the head.
    fx = dispatch_only_fx(conn)
    r_unknown = complete_effect(
        conn, fx["session"], f"cmp-{u()[:8]}", fx["effect"], DRIVER, EPOCH,
        dispatch_session_fence=2, job_fence=fx["job_fence"],
        step_id=fx["step"], request_hash=fx["rh"], idempotency_key=fx["ik"],
        outcome="failed_retryable", message={"text": ""},
        tools=[], decision_only=True, final_tools=False,
        evidence={"class": "garbled"})
    check("fixture: unknown settled with a provisional end",
          one(conn, "SELECT status FROM effect_requests"
                    " WHERE effect_id=%s", (fx["effect"],))[0]
          == "unknown_outcome", r_unknown)
    head = one(conn, "SELECT head_event_key FROM turn_end_slots"
                     " WHERE session_id=%s", (fx["session"],))[0]
    exec_sql(conn, "DELETE FROM turn_end_slots WHERE session_id=%s",
             (fx["session"],))
    check("fixture: no slot row exists (chain event kept)",
          one(conn, "SELECT count(*) FROM turn_end_slots"
                    " WHERE session_id=%s", (fx["session"],))[0] == 0
          and one(conn, "SELECT count(*) FROM turn_end_closers"
                        " WHERE session_id=%s", (fx["session"],))[0] == 0)
    r = repair(conn, fx["session"], f"rpr-{u()[:8]}", fx["effect"], 1,
               driver=DRIVER, driver_epoch=1, supersedes_event_key=head,
               evidence=good_evidence(), resolution_kind="succeeded",
               message={"text": "repaired"}, tools=[], decision_only=True,
               final_tools=False)
    check("D11: repair creates the absent slot (no REPAIR_TARGET_INVALID)",
          r["outcome"] == "accepted", r)
    slot = one(conn, "SELECT turn_end_key, slot_status, version"
                     " FROM turn_end_slots WHERE session_id=%s",
               (fx["session"],))
    tek = call(conn, "SELECT v_turn_end_key(%s::uuid, %s::uuid)",
               (fx["session"], fx["turn"]))[0]
    check("D11: the created row carries the derived key and the closer"
          " advanced the head",
          slot is not None and slot[0] == tek and slot[1] in ("known",),
          slot)


# ---------------------------------------------------------------------------
# D12: cross-attempt residue — superseded chunks never join the merge
# ---------------------------------------------------------------------------

def test_cross_attempt_residue(conn) -> None:
    from v8.events.canonicalizer import normalize
    fx = tools_fx(conn, [("verifiable_no_effect", 3)])
    eff = fx["effects"][0]
    # Chunks of attempt 1 (later superseded by a cohort retry allocation).
    for i, text in enumerate(("old-a", "old-b")):
        exec_sql(
            conn,
            "INSERT INTO session_events(seq, session_id, event_type,"
            " event_class, schema_version, canonicalizer_version,"
            " event_key, turn_id, step_id, effect_id, payload,"
            " payload_hash, attempt_no, stream_id, chunk_index)"
            " VALUES ((SELECT next_seq FROM sessions WHERE session_id=%s),"
            " %s, 'assistant/chunk', 'observational', 'sv@1', 'canon@1',"
            " %s, %s, %s, %s, %s, %s, 1, %s, %s)",
            (fx["session"], fx["session"], f"ck-old-{i}", fx["turn"],
             fx["step"], eff["effect_id"],
             canon({"text": text, "chunk_index": i}), "ab" * 32,
             f"st-{fx['session'][:8]}", i))
        exec_sql(conn, "UPDATE sessions SET next_seq=next_seq+1"
                       " WHERE session_id=%s", (fx["session"],))
    # The attempt settles retryable -> the cohort allocates attempt 2.
    from v8.tools.client import complete_tool_effect
    complete_tool_effect(
        conn, fx["session"], f"cmp-{u()[:8]}", eff["effect_id"], DRIVER,
        EPOCH, dispatch_session_fence=fx["seal_fence"],
        job_fence=eff["job_fence"], attempt_no=1, step_id=fx["step"],
        request_hash=eff["request_hash"],
        idempotency_key=eff["idempotency_key"], outcome="failed_retryable",
        tool_call_id=eff["tool_call_id"], output={"error": "x"},
        evidence=fail_evidence())
    from v8.retry.client import retry_effect
    rcur = one(conn, "SELECT session_fence FROM sessions"
                     " WHERE session_id=%s", (fx["session"],))[0]
    rr = retry_effect(conn, fx["session"], f"rty-{u()[:8]}",
                      eff["effect_id"], DRIVER, EPOCH, rcur)
    check("fixture: attempt 2 allocated",
          rr["outcome"] == "accepted"
          and one(conn, "SELECT max(attempt_no) FROM effect_attempts"
                        " WHERE effect_id=%s",
                  (eff["effect_id"],))[0] == 2, rr)
    # Fresh chunks of attempt 2 complete the text.
    for i, text in enumerate(("new-a", "new-b")):
        exec_sql(
            conn,
            "INSERT INTO session_events(seq, session_id, event_type,"
            " event_class, schema_version, canonicalizer_version,"
            " event_key, turn_id, step_id, effect_id, payload,"
            " payload_hash, attempt_no, stream_id, chunk_index)"
            " VALUES ((SELECT next_seq FROM sessions WHERE session_id=%s),"
            " %s, 'assistant/chunk', 'observational', 'sv@1', 'canon@1',"
            " %s, %s, %s, %s, %s, %s, 2, %s, %s)",
            (fx["session"], fx["session"], f"ck-new-{i}", fx["turn"],
             fx["step"], eff["effect_id"],
             canon({"text": text, "chunk_index": i}), "cd" * 32,
             f"st-{fx['session'][:8]}", i))
        exec_sql(conn, "UPDATE sessions SET next_seq=next_seq+1"
                       " WHERE session_id=%s", (fx["session"],))
    evs = rows(conn, "SELECT event_type, payload, attempt_no, stream_id,"
                     " chunk_index, effect_id FROM session_events"
                     " WHERE session_id=%s ORDER BY seq", (fx["session"],))
    chunks = [dict(event_type=e[0], payload=json.loads(e[1]),
                   attempt_no=e[2], stream_id=e[3], chunk_index=e[4],
                   effect_id=str(e[5])) for e in evs]
    from v8.events.canonicalizer import _merge_chunks
    merged = _merge_chunks(chunks)
    a1 = merged.get((str(eff["effect_id"]), 1), {})
    a2 = merged.get((str(eff["effect_id"]), 2), {})
    check("D12: the merge keys split per attempt (the frozen four-tuple"
          " carries attempt_no) and the CURRENT attempt's text excludes"
          " the superseded residue",
          "old-a" in a1.get("text", "") and "new-a" in a2.get("text", "")
          and "old-a" not in a2.get("text", "")
          and a2.get("chunks") == 2, (a1, a2))
    # The residue stays observational history only: the collected-set
    # extraction of attempt 2 never sees the old attempt's chunks.
    set2 = call(conn, "SELECT indices FROM v_stream_flow_indices("
                      " %s::uuid, %s::uuid, 2)",
                (fx["session"], eff["effect_id"]))[0]
    check("D12: the collected set of the new attempt is exactly its own"
          " chunks", set2 == [0, 1], set2)


# ---------------------------------------------------------------------------
# D13: the real lease window (GUC retired)
# ---------------------------------------------------------------------------

def test_real_window(conn) -> None:
    fx = dispatch_only_fx(conn)  # streaming, no lease armed
    r_live = call(conn, "SELECT outcome FROM v_stream_observe("
                        " %s::uuid, %s, %s::uuid, 1,"
                        " '{\"stream_complete\":false}', 'sv@1', 'canon@1',"
                        " %s)",
                  (fx["session"], f"obs-{u()[:8]}", fx["effect"],
                   u()[:12]))[0]
    check("D13: unarmed lease = live window (observation accepted)",
          r_live == "accepted", r_live)
    exec_sql(conn, "UPDATE effect_requests SET lease_owner='w',"
                   " lease_until=now() - interval '10 seconds'"
                   " WHERE effect_id=%s", (fx["effect"],))
    r_dead = call(conn, "SELECT outcome, code FROM v_stream_observe("
                        " %s::uuid, %s, %s::uuid, 1,"
                        " '{\"stream_complete\":false}', 'sv@1', 'canon@1',"
                        " %s)",
                  (fx["session"], f"obs-{u()[:8]}", fx["effect"],
                   u()[:12]))
    check("D13: expired lease = exhausted window (REPAIR_REQUIRED)",
          r_dead == ("repair_required", "REPAIR_REQUIRED"), r_dead)
    # STREAM_INCOMPLETE only on a real exhaustion: the takeover of the
    # dead-window streaming attempt records it.
    exec_sql(conn, "UPDATE sessions SET lease_until=now()"
                   " - interval '10 seconds' WHERE session_id=%s",
             (fx["session"],))
    recovery_claim_session(conn, fx["session"], DRIVER, EPOCH, "rec-w", 60)
    recovery_takeover(conn, fx["session"], f"tko-{u()[:8]}", DRIVER, EPOCH,
                      evidence=None)
    check("D13: STREAM_INCOMPLETE recorded for the exhausted-window"
          " streaming takeover",
          one(conn, "SELECT count(*) FROM effect_audit"
                    " WHERE effect_id=%s AND reason='STREAM_INCOMPLETE'",
              (fx["effect"],))[0] >= 1)


# ---------------------------------------------------------------------------
# D14 + D15: credential-missing regression + capability API boundary (DB)
# ---------------------------------------------------------------------------

def test_credentials_and_boundary(conn) -> None:
    import os
    # D14: no credential env -> the DeepSeek adapter never constructs, no
    # real call can happen (the G13 gating contract, runtime regression).
    from v8.loop.runtime import FakeLLM
    llm = FakeLLM()
    gen = llm.generate({"prompt": {"seed_text": "hi"}})
    check("D14: the fake suite stays authoritative (deterministic"
          " generate)",
          isinstance(gen, dict) and gen == llm.generate(
              {"prompt": {"seed_text": "hi"}}))
    missing = {k: os.environ.pop(k, None)
               for k in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY",
                         "OPENAI_API_URI")}
    try:
        from v8.loop.runtime import DeepSeekLLM
        adapter = DeepSeekLLM()
        check("D14: with the credential env absent the adapter reports"
              " no capability source (blocked, A87 gating)",
              adapter.credentials_present is False)
        refused = False
        try:
            adapter.generate({"prompt": {"seed_text": "hi"}})
        except Exception:
            refused = True
        check("D14: no credential -> no real call can ever be issued",
              refused is True)
    finally:
        for k, v in missing.items():
            if v is not None:
                os.environ[k] = v

    # D15: credentials never enter the event/audit carriers (DB half).
    probe = "sk-PROBE-DO-NOT-LEAK"
    hits = rows(conn, "SELECT count(*) FROM session_events"
                      " WHERE payload::text LIKE %s", (f"%{probe}%",))
    check("D15: no credential-shaped material in any event payload",
          hits[0][0] == 0, hits)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

TESTS = (
    test_wait_layer,
    test_attempt_heartbeat,
    test_force_job_takeover,
    test_reconcile_result,
    test_slot_create_when_absent,
    test_cross_attempt_residue,
    test_real_window,
    test_credentials_and_boundary,
)


def main() -> int:
    setup_db()
    conn = psycopg2.connect(_uri())
    try:
        for t in TESTS:
            t(conn)
            print(f"[ok] {t.__name__}")
    finally:
        conn.close()
    print("[G19b] all gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
