"""G8a gate: v8 request_cancel — the sticky stop latch, the no-active-work
branch three windows, the canonical turn/end derivation (before/after
dispatch split, append-only), the pre-dispatch dual-table atomic sync and
the finish_session / dispatch commit-order races.

Run: uv run python v8/cancel/test_cancel.py  (exit 0 = pass)
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
from v8.effect.client import (
    claim_session,
    complete_effect,
    dispatch_effect,
    finish_session,
    prepare_step,
)
from v8.events.canonicalizer import normalize
from v8.events.client import build_entry, call_append_events, create_session
from v8.retry.test_retry import (
    DRIVER,
    EPOCH,
    DyingConnection,
    ProcessDeath,
    attempt_rows,
    check,
    decision_fx,
    effect_row,
    exec_sql,
    fail_decision,
    good_evidence,
    one,
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

def session_full(conn, session_id):
    return one(conn,
               "SELECT state, failure_code, cancellation_epoch, session_fence,"
               " active_step_id, lease_owner, lease_until FROM sessions"
               " WHERE session_id=%s", (session_id,))


def slot_row(conn, session_id, turn_id=None):
    if turn_id is None:
        return one(conn,
                   "SELECT turn_id, turn_end_key, head_event_key, slot_status,"
                   " version, resolution_identity_canonical FROM turn_end_slots"
                   " WHERE session_id=%s", (session_id,))
    return one(conn,
               "SELECT turn_id, turn_end_key, head_event_key, slot_status,"
               " version, resolution_identity_canonical FROM turn_end_slots"
               " WHERE session_id=%s AND turn_id=%s", (session_id, turn_id))


def counts(conn, session_id):
    return one(conn,
               "SELECT (SELECT count(*) FROM steps WHERE session_id=%s),"
               " (SELECT count(*) FROM effect_requests WHERE session_id=%s),"
               " (SELECT count(*) FROM effect_attempts a JOIN effect_requests er"
               "    ON er.effect_id=a.effect_id WHERE er.session_id=%s)",
               (session_id, session_id, session_id))


def turn_end_events(conn, session_id):
    return rows(conn,
                "SELECT turn_id, payload, event_key, internal_semantic_ordinal"
                " FROM session_events WHERE session_id=%s AND event_type='turn/end'"
                " ORDER BY seq", (session_id,))


def trace_events(conn, session_id) -> list[dict]:
    """normalize() input built from the persisted rows: raw session_events
    annotated with the effect statuses read back from effect_requests."""
    evs = rows(conn,
               "SELECT event_type, payload, turn_id, step_id, effect_id,"
               " event_key, attempt_no, internal_semantic_ordinal"
               " FROM session_events WHERE session_id=%s ORDER BY seq",
               (session_id,))
    statuses = {str(r[0]): r[1] for r in rows(
        conn, "SELECT effect_id, status FROM effect_requests"
              " WHERE session_id=%s", (session_id,))}
    out = []
    for et, payload, turn, step, eff, key, att, iso in evs:
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
        out.append(d)
    return out


def end_events(t: list[dict]) -> list[dict]:
    return [e for e in t if e["event_type"] == "turn/end"]


def append_turn_start(conn, session_id, turn_id, ordinal: int):
    entry = build_entry("turn/start", {"reason": "user_message"},
                        schema_version="sv@1", canonicalizer_version="canon@1",
                        turn_id=turn_id, semantic_input_ordinal=ordinal)
    seq = one(conn, "SELECT next_seq FROM sessions WHERE session_id=%s",
              (session_id,))[0]
    return call_append_events(conn, session_id, f"ap-{u()[:8]}", DRIVER, EPOCH,
                              seq, [entry])


def cancel(conn, session_id, cmd=None, declared_hash=None):
    return request_cancel(conn, session_id, cmd or f"cx-{u()[:8]}", DRIVER, EPOCH,
                          declared_hash=declared_hash)


# ---------------------------------------------------------------------------
# 1. three windows (no-active-work branch)
# ---------------------------------------------------------------------------

def test_window_i_ready_no_step(conn) -> None:
    s = u()
    create_session(conn, s, DRIVER)
    before = session_full(conn, s)
    r = cancel(conn, s)
    check("window (i): accepted", r["outcome"] == "accepted", r)
    after = session_full(conn, s)
    check("window (i): session cancelled/CANCELLED_BY_REQUEST",
          after[0] == "cancelled" and after[1] == "CANCELLED_BY_REQUEST", after)
    check("window (i): epoch 0->1, session_fence +1",
          before[2] == 0 and after[2] == 1 and after[3] == before[3] + 1, after)
    check("window (i): active_step_id cleared", after[4] is None, after)
    check("window (i): no turn -> zero events", turn_end_events(conn, s) == [])
    check("window (i): no step/effect created", counts(conn, s) == (0, 0, 0))

    # The same no-active-work branch revokes a HELD coordination lease
    # (claimed, no step yet).
    s2 = u()
    create_session(conn, s2, DRIVER)
    r0 = claim_session(conn, s2, DRIVER)
    check("window (i): coordination lease held before cancel",
          r0["outcome"] == "claimed"
          and session_full(conn, s2)[5] == DRIVER, r0)
    r = cancel(conn, s2)
    check("window (i): cancel accepted on a claimed session",
          r["outcome"] == "accepted", r)
    after2 = session_full(conn, s2)
    check("window (i): coordination lease revoked, session cancelled",
          after2[0] == "cancelled" and after2[1] == "CANCELLED_BY_REQUEST"
          and after2[5] is None and after2[6] is None, after2)


def test_window_ii_waiting_event(conn) -> None:
    # (ii) waiting_event/sleeping with a turn already opened but no work:
    # the unique known end is before_dispatch.
    s = u()
    turn = u()
    create_session(conn, s, DRIVER)
    ra = append_turn_start(conn, s, turn, 1)
    check("window (ii): turn/start appended", ra["outcome"] == "accepted", ra)
    exec_sql(conn, "UPDATE sessions SET state='waiting_event' WHERE session_id=%s",
             (s,))
    before = session_full(conn, s)
    r = cancel(conn, s)
    check("window (ii): accepted", r["outcome"] == "accepted", r)
    after = session_full(conn, s)
    check("window (ii): session cancelled", after[0] == "cancelled"
          and after[1] == "CANCELLED_BY_REQUEST", after)
    check("window (ii): epoch 0->1, fence +1",
          before[2] == 0 and after[2] == 1 and after[3] == before[3] + 1, after)
    ends = turn_end_events(conn, s)
    check("window (ii): one turn/end before_dispatch", len(ends) == 1
          and json.loads(ends[0][1]) == {
              "interrupted": True,
              "reason": "cancelled_by_request_before_dispatch"}, ends)
    sl = slot_row(conn, s, turn)
    check("window (ii): known slot head = the turn/end event",
          sl[3] == "known" and sl[2] == ends[0][2] and sl[1] is not None, sl)
    tr = normalize(trace_events(conn, s), CV)
    check("window (ii): normalize agrees (one end, before_dispatch)",
          [e["payload"] for e in end_events(tr)] == [
              {"interrupted": True,
               "reason": "cancelled_by_request_before_dispatch"}], tr)


def closed_turn_fx(conn):
    """decision_only success -> the turn is closed (known slot), step
    succeeded/closed, session ready — window (iii) turn-close subcase."""
    s, turn, step, eff = u(), u(), u(), u()
    rh, ik = f"rh-{u()[:10]}", f"ik-{u()[:10]}"
    create_session(conn, s, DRIVER)
    r0 = claim_session(conn, s, DRIVER)
    rs = prepare_step(conn, s, f"seal-{u()[:8]}", DRIVER, EPOCH,
                      r0["session_fence"], step, turn, eff,
                      request_hash=rh, idempotency_key=ik)
    check("fx close seal accepted", rs["outcome"] == "accepted", rs)
    rd = dispatch_effect(conn, s, f"dsp-{u()[:8]}", eff, DRIVER, EPOCH,
                         rs["receipt"]["session_fence"],
                         rs["receipt"]["job_fence"])
    check("fx close dispatch accepted", rd["outcome"] == "accepted", rd)
    rc = complete_effect(
        conn, s, f"cmp-{u()[:8]}", eff, DRIVER, EPOCH,
        dispatch_session_fence=2, job_fence=rs["receipt"]["job_fence"],
        step_id=step, request_hash=rh,
        idempotency_key=ik, outcome="succeeded",
        message={"text": "done"}, tools=[], decision_only=True,
        final_tools=False, evidence=good_evidence())
    check("fx close complete accepted", rc["outcome"] == "accepted", rc)
    return {"session": s, "turn": turn, "step": step, "effect": eff}


def test_window_iii_turn_close(conn) -> None:
    fx = closed_turn_fx(conn)
    s, turn, step = fx["session"], fx["turn"], fx["step"]
    sl_before = slot_row(conn, s)
    st_before = step_row(conn, step)
    check("window (iii)-close: turn slot known before cancel",
          sl_before[3] == "known", sl_before)
    before = session_full(conn, s)
    r = cancel(conn, s)
    check("window (iii)-close: accepted", r["outcome"] == "accepted", r)
    after = session_full(conn, s)
    check("window (iii)-close: session cancelled",
          after[0] == "cancelled" and after[1] == "CANCELLED_BY_REQUEST", after)
    check("window (iii)-close: epoch 0->1, fence +1",
          before[2] == 0 and after[2] == 1 and after[3] == before[3] + 1, after)
    sl_after = slot_row(conn, s)
    check("window (iii)-close: existing end NOT rewritten (head+version同一)",
          sl_after[2] == sl_before[2] and sl_after[4] == sl_before[4]
          and sl_after[3] == "known", (sl_before, sl_after))
    st_after = step_row(conn, step)
    check("window (iii)-close: terminal step unchanged (SUCCEEDED)",
          st_after[0] == "succeeded" and st_after[1] == "SUCCEEDED"
          and st_after[0] == st_before[0] and st_after[1] == st_before[1],
          st_after)
    check("window (iii)-close: exactly one turn/end event (the close)",
          len(turn_end_events(conn, s)) == 1)
    check("window (iii)-close: no new step/effect", counts(conn, s) == (1, 1, 1))
    tr = normalize(trace_events(conn, s), CV)
    check("window (iii)-close: normalize still the normal close",
          [e["payload"] for e in end_events(tr)] == [{"interrupted": False}], tr)


def test_window_iii_final_tools(conn) -> None:
    fx = tools_fx(conn, [("verifiable_no_effect", 3),
                         ("verifiable_no_effect", 3)])
    for i in range(2):
        r = succeed_tool(conn, fx, i)
        check(f"window (iii)-tools: tool {i} succeeded", r["outcome"] == "accepted",
              r)
    s, turn, step = fx["session"], fx["turn"], fx["step"]
    check("window (iii)-tools: step succeeded/closed, session ready",
          step_row(conn, step)[0] == "succeeded"
          and session_row(conn, s)[0] == "ready", step_row(conn, step))
    check("window (iii)-tools: turn still open (no slot)",
          slot_row(conn, s) is None)
    before = session_full(conn, s)
    r = cancel(conn, s)
    check("window (iii)-tools: accepted", r["outcome"] == "accepted", r)
    after = session_full(conn, s)
    check("window (iii)-tools: session cancelled",
          after[0] == "cancelled" and after[1] == "CANCELLED_BY_REQUEST", after)
    check("window (iii)-tools: epoch 0->1, fence +1",
          before[2] == 0 and after[2] == 1 and after[3] == before[3] + 1, after)
    ends = turn_end_events(conn, s)
    check("window (iii)-tools: one turn/end after_dispatch", len(ends) == 1
          and json.loads(ends[0][1]) == {
              "interrupted": True,
              "reason": "cancelled_by_request_after_dispatch"}, ends)
    sl = slot_row(conn, s, turn)
    check("window (iii)-tools: known slot", sl is not None and sl[3] == "known"
          and sl[2] == ends[0][2], sl)
    st = step_row(conn, step)
    check("window (iii)-tools: step terminal unchanged (SUCCEEDED)",
          st[0] == "succeeded" and st[1] == "SUCCEEDED", st)
    tr = normalize(trace_events(conn, s), CV)
    check("window (iii)-tools: normalize agrees (one end, after_dispatch)",
          [e["payload"] for e in end_events(tr)] == [
              {"interrupted": True,
               "reason": "cancelled_by_request_after_dispatch"}], tr)


# ---------------------------------------------------------------------------
# 2. pre-dispatch cancellation dual-table atomic sync
# ---------------------------------------------------------------------------

def predispatch_fx(conn):
    """seal published a ready effect but did not dispatch it."""
    s, turn, step, eff = u(), u(), u(), u()
    rh, ik = f"rh-{u()[:10]}", f"ik-{u()[:10]}"
    create_session(conn, s, DRIVER)
    r0 = claim_session(conn, s, DRIVER)
    rs = prepare_step(conn, s, f"seal-{u()[:8]}", DRIVER, EPOCH,
                      r0["session_fence"], step, turn, eff,
                      request_hash=rh, idempotency_key=ik)
    check("fx predispatch seal accepted", rs["outcome"] == "accepted", rs)
    return {"session": s, "turn": turn, "step": step, "effect": eff,
            "fence": rs["receipt"]["session_fence"],
            "job_fence": rs["receipt"]["job_fence"], "rh": rh, "ik": ik}


def test_predispatch_dual_table(conn) -> None:
    fx = predispatch_fx(conn)
    s, eff = fx["session"], fx["effect"]
    check("predispatch: effect ready, attempt ready before cancel",
          effect_row(conn, eff)[0] == "ready"
          and attempt_rows(conn, eff)[0][1] == "ready")
    r = cancel(conn, s)
    check("predispatch: cancel accepted", r["outcome"] == "accepted", r)
    # (i) dual-table consistency + parent snapshot sync.
    er = effect_row(conn, eff)
    att = attempt_rows(conn, eff)
    check("predispatch: effect_requests -> cancelled_before_dispatch",
          er[0] == "cancelled_before_dispatch", er)
    check("predispatch: current attempt -> cancelled_before_dispatch",
          att[0][1] == "cancelled_before_dispatch", att)
    check("predispatch: receipt lists the cancelled effect with the code",
          r["receipt"]["cancelled_effects"] == [
              {"effect_id": eff, "attempt_no": 1,
               "code": "ABORTED_BEFORE_DISPATCH"}], r["receipt"])
    # (iii) audit trail queryable.
    check("predispatch: ABORTED_BEFORE_DISPATCH audit rows present",
          one(conn, "SELECT count(*) FROM effect_audit WHERE effect_id=%s"
                    " AND reason='ABORTED_BEFORE_DISPATCH'", (eff,))[0] == 1)
    # no completion semantic event from the cancellation.
    check("predispatch: no completion event generated",
          turn_end_events(conn, s) != []
          and one(conn, "SELECT count(*) FROM session_events"
                        " WHERE session_id=%s AND event_type='assistant/message'",
                  (s,))[0] == 0)
    check("predispatch: step cancelled, session cancelled (rule 3)",
          step_row(conn, fx["step"])[0] == "cancelled"
          and session_row(conn, s)[0] == "cancelled", step_row(conn, fx["step"]))
    check("predispatch: one turn/end before_dispatch",
          [json.loads(e[1]) for e in turn_end_events(conn, s)] == [
              {"interrupted": True,
               "reason": "cancelled_by_request_before_dispatch"}])

    # (ii) late completion of the cancelled attempt is stably rejected with
    # zero control state (receipt + audit only).
    before_events = one(conn, "SELECT count(*) FROM session_events"
                              " WHERE session_id=%s", (s,))[0]
    rc = complete_effect(
        conn, s, f"cmp-{u()[:8]}", eff, DRIVER, EPOCH,
        dispatch_session_fence=2, job_fence=fx["job_fence"],
        step_id=fx["step"], request_hash=fx["rh"], idempotency_key=fx["ik"],
        outcome="succeeded", message={"text": "too late"}, tools=[],
        decision_only=True, final_tools=False, evidence=good_evidence())
    check("predispatch: late completion rejected (terminal attempt)",
          rc["outcome"] == "rejected_mismatch"
          and rc["code"] == "ATTEMPT_ALREADY_SETTLED", rc)
    check("predispatch: late completion zero control state",
          effect_row(conn, eff)[0] == "cancelled_before_dispatch"
          and attempt_rows(conn, eff)[0][1] == "cancelled_before_dispatch"
          and session_row(conn, s)[0] == "cancelled"
          and one(conn, "SELECT count(*) FROM session_events"
                        " WHERE session_id=%s", (s,))[0] == before_events)
    check("predispatch: late completion wrote the audit row",
          one(conn, "SELECT count(*) FROM effect_audit WHERE effect_id=%s"
                    " AND reason='ATTEMPT_ALREADY_SETTLED'", (eff,))[0] == 1)


# ---------------------------------------------------------------------------
# 3. sticky latch + idempotency
# ---------------------------------------------------------------------------

def test_sticky_latch_semantics(conn) -> None:
    # First cancel increments 0->1; a second cancel (different command_id)
    # on the now-terminal session returns the original state, epoch fixed.
    s = u()
    create_session(conn, s, DRIVER)
    r1 = cancel(conn, s)
    check("latch: first cancel epoch_incremented",
          r1["receipt"]["epoch_incremented"] is True
          and r1["receipt"]["cancellation_epoch"] == 1, r1["receipt"])
    r2 = cancel(conn, s)
    check("latch: second cancel on terminal session returns original state, "
          "epoch unchanged",
          r2["outcome"] == "accepted"
          and r2["receipt"]["terminal"] is True
          and r2["receipt"]["state"] == "cancelled"
          and r2["receipt"]["cancellation_epoch"] == 1
          and r2["receipt"]["epoch_changed"] is False, r2["receipt"])
    check("latch: epoch still 1 in the control row",
          session_full(conn, s)[2] == 1)

    # same command_id replay: original receipt, zero new state/events.
    s2 = u()
    create_session(conn, s2, DRIVER)
    cmd = f"cx-{u()[:8]}"
    ra = cancel(conn, s2, cmd=cmd)
    ev = one(conn, "SELECT count(*) FROM session_events WHERE session_id=%s",
             (s2,))[0]
    rb = cancel(conn, s2, cmd=cmd)
    check("latch: same command_id replays the original receipt",
          rb["receipt"] == ra["receipt"] and rb["outcome"] == "accepted", rb)
    check("latch: replay stored zero new state/events",
          session_full(conn, s2)[2] == 1
          and one(conn, "SELECT count(*) FROM session_events WHERE session_id=%s",
                  (s2,))[0] == ev)


def test_command_gate_mismatch(conn) -> None:
    # declared hash mismatch -> REQUEST_HASH_MISMATCH, zero control state.
    s = u()
    create_session(conn, s, DRIVER)
    r = cancel(conn, s, declared_hash="0" * 64)
    check("gate: declared hash mismatch rejected",
          r["outcome"] == "rejected_mismatch"
          and r["code"] == "REQUEST_HASH_MISMATCH", r)
    check("gate: zero control state on the mismatch",
          session_row(conn, s)[0] == "ready"
          and session_full(conn, s)[2] == 0)


# ---------------------------------------------------------------------------
# 4. finish_session race (two commit orders)
# ---------------------------------------------------------------------------

def test_finish_race(conn) -> None:
    # cancel first -> session cancelled; a later finish_session changes nothing.
    fx = closed_turn_fx(conn)
    s = fx["session"]
    r = cancel(conn, s)
    check("race: cancel-first accepted", r["outcome"] == "accepted", r)
    after_cancel = session_full(conn, s)
    check("race: cancel-first -> cancelled", after_cancel[0] == "cancelled",
          after_cancel)
    rf = finish_session(conn, s, f"fin-{u()[:8]}", DRIVER, EPOCH,
                        after_cancel[3])
    check("race: later finish_session is not accepted",
          rf["outcome"] != "accepted", rf)
    after_finish = session_full(conn, s)
    check("race: finish_session left every state bit unchanged",
          after_finish == after_cancel, (after_cancel, after_finish))

    # finish first -> session completed; a later cancel returns the original
    # terminal state and does not change the epoch.
    fx2 = closed_turn_fx(conn)
    s2 = fx2["session"]
    r0 = claim_session(conn, s2, DRIVER)
    rf2 = finish_session(conn, s2, f"fin-{u()[:8]}", DRIVER, EPOCH,
                         r0["session_fence"])
    check("race: finish-first -> completed",
          rf2["outcome"] == "accepted"
          and session_row(conn, s2)[0] == "completed", rf2)
    before = session_full(conn, s2)
    rc = cancel(conn, s2)
    check("race: later cancel returns the original terminal state",
          rc["outcome"] == "accepted" and rc["receipt"]["terminal"] is True
          and rc["receipt"]["state"] == "completed"
          and rc["receipt"]["cancellation_epoch"] == 0
          and rc["receipt"]["epoch_changed"] is False, rc["receipt"])
    check("race: later cancel changed nothing (state_fence/epoch)",
          session_full(conn, s2) == before, before)


# ---------------------------------------------------------------------------
# 5. cancel x dispatch race (two commit orders)
# ---------------------------------------------------------------------------

def test_dispatch_race(conn) -> None:
    # dispatch first -> the attempt stays dispatch_started; a later cancel
    # does not retroactively cancel it (only the G8b closure path settles it).
    fx = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=3)
    s, eff = fx["session"], fx["effect"]
    r = cancel(conn, s)
    check("dispatch-first: cancel accepted", r["outcome"] == "accepted", r)
    check("dispatch-first: attempt stays dispatch_started (not retro-cancelled)",
          attempt_rows(conn, eff)[0][1] == "dispatch_started"
          and effect_row(conn, eff)[0] == "dispatch_started",
          attempt_rows(conn, eff))
    check("dispatch-first: pending sibling -> step cancel_requested, "
          "session waiting_effect (no turn/end)",
          step_row(conn, fx["step"])[0] == "cancel_requested"
          and session_row(conn, s)[0] == "waiting_effect"
          and turn_end_events(conn, s) == [],
          (step_row(conn, fx["step"]), session_row(conn, s)))
    check("dispatch-first: latch set", session_full(conn, s)[2] == 1)
    # A second cancel with a NEW command_id while the session is still
    # non-terminal (pending sibling) keeps the latch: no re-increment.
    r2 = cancel(conn, s)
    check("dispatch-first: second cancel keeps the latch (no re-increment)",
          r2["outcome"] == "accepted"
          and r2["receipt"]["epoch_incremented"] is False
          and r2["receipt"]["cancellation_epoch"] == 1
          and session_full(conn, s)[2] == 1, r2["receipt"])
    check("dispatch-first: second cancel left the dispatched attempt alone",
          attempt_rows(conn, eff)[0][1] == "dispatch_started", None)

    # cancel first -> a later dispatch is stably rejected, never dispatched.
    fx2 = predispatch_fx(conn)
    s2, eff2 = fx2["session"], fx2["effect"]
    rc = cancel(conn, s2)
    check("cancel-first: cancel accepted", rc["outcome"] == "accepted", rc)
    new_fence = rc["receipt"]["session_fence"]
    rd = dispatch_effect(conn, s2, f"dsp-{u()[:8]}", eff2, DRIVER, EPOCH,
                         new_fence, fx2["job_fence"])
    check("cancel-first: later dispatch stably rejected (CANCEL_STICKY)",
          rd["outcome"] == "rejected_mismatch"
          and rd["code"] == "CANCEL_STICKY", rd)
    check("cancel-first: attempt never entered dispatch_started",
          attempt_rows(conn, eff2)[0][1] == "cancelled_before_dispatch"
          and effect_row(conn, eff2)[0] == "cancelled_before_dispatch",
          attempt_rows(conn, eff2))


# ---------------------------------------------------------------------------
# 6. chaos: cancel transaction kill + rerun convergence
# ---------------------------------------------------------------------------

def test_chaos_cancel_kill(conn) -> None:
    fx = predispatch_fx(conn)
    s, eff = fx["session"], fx["effect"]
    dying = DyingConnection(conn)
    try:
        cancel(dying, s, cmd=f"cx-{u()[:8]}")
        raise AssertionError("expected the mid-transaction kill")
    except ProcessDeath:
        pass
    check("chaos: killed cancel rolled back completely",
          effect_row(conn, eff)[0] == "ready"
          and attempt_rows(conn, eff)[0][1] == "ready"
          and session_row(conn, s)[0] == "waiting_effect"
          and session_full(conn, s)[2] == 0
          and turn_end_events(conn, s) == [], session_full(conn, s))
    # Rerun converges to the same terminal outcome.
    r = cancel(conn, s, cmd=f"cx-{u()[:8]}")
    check("chaos: rerun accepted", r["outcome"] == "accepted", r)
    check("chaos: rerun converges (cancelled, one before_dispatch end)",
          session_row(conn, s)[0] == "cancelled"
          and effect_row(conn, eff)[0] == "cancelled_before_dispatch"
          and [json.loads(e[1]) for e in turn_end_events(conn, s)] == [
              {"interrupted": True,
               "reason": "cancelled_by_request_before_dispatch"}])


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------

def main() -> int:
    setup_db()
    conn = psycopg2.connect(uri())
    try:
        test_window_i_ready_no_step(conn)
        test_window_ii_waiting_event(conn)
        test_window_iii_turn_close(conn)
        test_window_iii_final_tools(conn)
        test_predispatch_dual_table(conn)
        test_sticky_latch_semantics(conn)
        test_command_gate_mismatch(conn)
        test_finish_race(conn)
        test_dispatch_race(conn)
        test_chaos_cancel_kill(conn)
    finally:
        conn.close()
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
