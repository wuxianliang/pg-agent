"""G4 gate: v8 effect stage — claim/yield, initial decision seal, dispatch,
complete_effect (success + unknown), aggregation, finish_session.

Run: uv run python v8/effect/test_effect.py  (exit 0 = pass)
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
from v8.canonical import canonicalize, escape_dollar_keys
from v8.canonical.keys import turn_end_key_v1
from v8.effect.client import (
    claim_session,
    complete_effect,
    completion_event_key,
    dispatch_effect,
    finish_session,
    prepare_step,
    recovery_claim_session,
    yield_session,
)
from v8.effect.setup_db import DB, main as setup_db
from v8.events.canonicalizer import normalize
from v8.events.client import build_entry, call_append_events, create_session

SV, CV = "sv@1", "canon@1"


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f": {detail}" if detail else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def u() -> str:
    return str(uuid.uuid4())


def canon(obj) -> tuple[str, str]:
    return canonicalize(escape_dollar_keys(obj))


def fresh_session(conn, driver: str = "drv") -> str:
    s = u()
    create_session(conn, s, driver)
    return s


def seal_fixture(conn, driver: str = "drv"):
    """create -> claim -> prepare_step. Returns (session, turn, step, effect,
    fence_after_seal, job_fence)."""
    s = fresh_session(conn, driver)
    turn, step, effect = u(), u(), u()
    r0 = claim_session(conn, s, driver)
    check("fixture claim ok", r0["outcome"] == "claimed", r0)
    r = prepare_step(conn, s, f"seal-{u()[:8]}", driver, 1, r0["session_fence"],
                     step, turn, effect)
    check("fixture seal accepted", r["outcome"] == "accepted", r)
    return (s, turn, step, effect,
            r["receipt"]["session_fence"], r["receipt"]["job_fence"])


def full_chain_fixture(conn, driver: str = "drv"):
    """create -> claim -> seal -> dispatch (the completion itself is run by
    the caller). Returns (session, turn, step, effect, fence, job_fence,
    request_hash, idempotency_key)."""
    s = fresh_session(conn, driver)
    turn, step, effect = u(), u(), u()
    rh, ik = f"rh-{u()[:8]}", f"ik-{u()[:8]}"
    r0 = claim_session(conn, s, driver)
    rs = prepare_step(conn, s, f"seal-{u()[:8]}", driver, 1, r0["session_fence"],
                      step, turn, effect, request_hash=rh, idempotency_key=ik)
    check("chain seal accepted", rs["outcome"] == "accepted", rs)
    rd = dispatch_effect(conn, s, f"dsp-{u()[:8]}", effect, driver, 1,
                         rs["receipt"]["session_fence"], rs["receipt"]["job_fence"])
    check("chain dispatch accepted", rd["outcome"] == "accepted", rd)
    return (s, turn, step, effect, rs["receipt"]["session_fence"],
            rs["receipt"]["job_fence"], rh, ik)


def complete_ok(conn, s, step, effect, job_fence, rh, ik, message=None, cmd=None):
    """Convenience: a clean known_success decision_only completion."""
    return complete_effect(
        conn, s, cmd or f"cmp-{u()[:8]}", effect, "drv", 1,
        dispatch_session_fence=2, job_fence=job_fence, step_id=step,
        request_hash=rh, idempotency_key=ik, outcome="succeeded",
        message=message or {"text": "final"}, tools=[],
        decision_only=True, final_tools=False, evidence=good_evidence())


def good_evidence() -> dict:
    """Known_success evidence shape (the client fills the attempt binding)."""
    return {"class": "known_success",
            "provider_receipt": {"receipt_id": f"pr-{u()[:8]}"}}


def bound_evidence(effect: str, attempt: int = 1) -> dict:
    """good_evidence pre-bound to (effect, attempt) for DIRECT SQL calls
    (the client injects the binding for Python-side calls; direct SQL must
    carry it explicitly since the classifier requires it)."""
    e = good_evidence()
    e["effect_id"] = str(effect)
    e["attempt_no"] = attempt
    return e


# ---------------------------------------------------------------------------
# claim / recovery claim / yield
# ---------------------------------------------------------------------------

def test_claim_and_yield(conn) -> None:
    s = fresh_session(conn)
    r1 = claim_session(conn, s, "drv", lease_owner="w1", lease_seconds=60)
    check("first claim ok", r1 == {"outcome": "claimed", "session_fence": 2}, r1)
    r2 = claim_session(conn, s, "drv")
    check("second claim while lease live -> LEASE_HELD",
          r2["outcome"] == "rejected_mismatch" and r2["code"] == "LEASE_HELD", r2)
    r3 = claim_session(conn, s, "other", 1)
    check("claim wrong driver -> rejected_stale",
          r3["outcome"] == "rejected_stale" and r3["code"] == "DRIVER_EPOCH_MISMATCH", r3)
    r4 = yield_session(conn, s, "drv", 1, 2, lease_owner="w1")
    check("yield ok", r4 == {"outcome": "yielded", "session_fence": 3}, r4)
    with conn.cursor() as cur:
        cur.execute("SELECT state, session_fence, lease_owner, lease_until,"
                    " lease_purpose FROM sessions WHERE session_id=%s", (s,))
        row = cur.fetchone()
        check("yield leaves ready + fence 3 + lease cleared",
              row == ("ready", 3, None, None, None), row)
    # An old-fence coordination command after the yield is rejected.
    r5 = prepare_step(conn, s, f"seal-{u()[:8]}", "drv", 1, 2, u(), u(), u())
    check("old-fence seal after yield -> SESSION_FENCE_STALE",
          r5["outcome"] == "rejected_stale" and r5["code"] == "SESSION_FENCE_STALE", r5)
    r6 = yield_session(conn, s, "drv", 1, 2, lease_owner="w1")
    check("yield with stale fence -> rejected_stale",
          r6["outcome"] == "rejected_stale" and r6["code"] == "SESSION_FENCE_STALE", r6)
    r7 = claim_session(conn, s, "drv")
    check("re-claim after yield", r7["outcome"] == "claimed", r7)


def test_yield_preserves_active_step(conn) -> None:
    s, turn, step, effect, fence, _jf = seal_fixture(conn)
    # After the seal the session is waiting_effect with a live active step;
    # put it back into a simulated claimed+lease state to exercise the
    # yield row with a live step.
    with conn.cursor() as cur:
        cur.execute("UPDATE sessions SET state='claimed', lease_owner='w',"
                    " lease_until=now() + interval '60s', lease_purpose='coordinator'"
                    " WHERE session_id=%s", (s,))
    conn.commit()
    r = yield_session(conn, s, "drv", 1, fence, lease_owner="w")
    check("yield from simulated claim ok", r["outcome"] == "yielded", r)
    with conn.cursor() as cur:
        cur.execute("SELECT state, active_step_id FROM sessions WHERE session_id=%s",
                    (s,))
        state, active = cur.fetchone()
        check("yield preserves the active step",
              state == "ready" and active == step, (state, active))


def test_recovery_claim(conn) -> None:
    s, turn, step, effect, fence, _jf = seal_fixture(conn)
    r = recovery_claim_session(conn, s, "drv", lease_owner="rec")
    check("recovery claim on waiting_effect ok", r["outcome"] == "claimed", r)
    check("recovery lease purpose", r.get("purpose") == "recovery", r)
    with conn.cursor() as cur:
        cur.execute("SELECT state, active_step_id, lease_purpose, session_fence"
                    " FROM sessions WHERE session_id=%s", (s,))
        state, active, purpose, fence_now = cur.fetchone()
        check("recovery claim: no new work, state/pointer kept, fence bumped",
              state == "waiting_effect" and active == step
              and purpose == "recovery" and fence_now == fence + 1,
              (state, active, purpose, fence_now))
    r2 = claim_session(conn, s, "drv")
    check("normal claim blocked by live recovery lease",
          r2["code"] == "LEASE_HELD", r2)
    s2 = fresh_session(conn)
    with conn.cursor() as cur:
        cur.execute("UPDATE sessions SET state='failed' WHERE session_id=%s", (s2,))
    conn.commit()
    r3 = recovery_claim_session(conn, s2, "drv")
    check("recovery claim on terminal -> SESSION_TERMINAL",
          r3["code"] == "SESSION_TERMINAL", r3)


# ---------------------------------------------------------------------------
# Initial decision seal (Conformance 1 core)
# ---------------------------------------------------------------------------

def test_seal_happy(conn) -> None:
    s, turn, step, effect, fence, job_fence = seal_fixture(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM effect_attempts WHERE effect_id=%s", (effect,))
        check("exactly one attempt row", cur.fetchone()[0] == 1)
        cur.execute("SELECT attempt_no, status, dispatch_job_fence, driver,"
                    " driver_epoch, session_fence, dispatch_session_fence"
                    " FROM effect_attempts WHERE effect_id=%s", (effect,))
        att = cur.fetchone()
        check("first attempt frozen snapshot (dispatch_session_fence == fence)",
              att == (1, "ready", job_fence, "drv", 1, 2, 2), att)
        cur.execute("SELECT current_job_fence, status, dispatch_ordinal,"
                    " execution_mode, attempt_no, dispatch_count FROM effect_requests"
                    " WHERE effect_id=%s", (effect,))
        er = cur.fetchone()
        check("publish-as-ready + dual fence same value",
              er == (job_fence, "ready", 0, "non_streaming", 1, 0), er)
        cur.execute("SELECT status, stage, sealed_batch_no, pending_effect_count"
                    " FROM steps WHERE step_id=%s", (step,))
        check("step sealed + waiting_effect",
              cur.fetchone() == ("waiting_effect", "decision", 1, 1))
        cur.execute("SELECT count(*) FROM steps WHERE session_id=%s AND status='planned'",
                    (s,))
        check("no persisted planned step", cur.fetchone()[0] == 0)
        cur.execute("SELECT count(*) FROM effect_requests WHERE session_id=%s"
                    " AND status='planned'", (s,))
        check("no persisted planned effect", cur.fetchone()[0] == 0)
        cur.execute("SELECT count(*) FROM batches WHERE step_id=%s AND kind='decision'"
                    " AND sealed AND sealed_batch_no=1", (step,))
        check("one sealed decision batch", cur.fetchone()[0] == 1)
        cur.execute("SELECT state, session_fence, active_step_id, lease_owner"
                    " FROM sessions WHERE session_id=%s", (s,))
        sess = cur.fetchone()
        check("session waiting_effect + lease revoked + fence bumped",
              sess == ("waiting_effect", fence, step, None), sess)


def test_seal_cas_negatives(conn) -> None:
    # Stale fence: zero side effects (only the rejection receipt persists).
    s = fresh_session(conn)
    claim_session(conn, s, "drv")
    r = prepare_step(conn, s, f"seal-{u()[:8]}", "drv", 1, 99, u(), u(), u())
    check("seal stale fence -> SESSION_FENCE_STALE",
          r["outcome"] == "rejected_stale" and r["code"] == "SESSION_FENCE_STALE", r)
    with conn.cursor() as cur:
        for table in ("steps", "batches", "effect_requests", "effect_attempts"):
            cur.execute(f"SELECT count(*) FROM {table} WHERE session_id=%s", (s,))
            check(f"stale seal zero side effects ({table})", cur.fetchone()[0] == 0)
    # Sticky cancel set: the whole seal is rejected (planned cancel = whole
    # seal cancel, zero members published).
    s2 = fresh_session(conn)
    claim_session(conn, s2, "drv")
    with conn.cursor() as cur:
        cur.execute("UPDATE sessions SET cancellation_epoch=1 WHERE session_id=%s",
                    (s2,))
    conn.commit()
    r2 = prepare_step(conn, s2, f"seal-{u()[:8]}", "drv", 1, 2, u(), u(), u())
    check("seal with sticky cancel -> CANCEL_STICKY",
          r2["outcome"] == "rejected_mismatch" and r2["code"] == "CANCEL_STICKY", r2)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM steps WHERE session_id=%s", (s2,))
        check("sticky-cancel seal zero step rows", cur.fetchone()[0] == 0)
    # Epoch mismatch.
    s3 = fresh_session(conn)
    claim_session(conn, s3, "drv")
    r3 = prepare_step(conn, s3, f"seal-{u()[:8]}", "drv", 7, 2, u(), u(), u())
    check("seal epoch mismatch -> DRIVER_EPOCH_STALE",
          r3["outcome"] == "rejected_stale" and r3["code"] == "DRIVER_EPOCH_STALE", r3)
    # Active step still non-terminal: no second step (create_step CAS).
    s4, _t4, _step4, _e4, fence4, _j4 = seal_fixture(conn)
    with conn.cursor() as cur:
        cur.execute("UPDATE sessions SET state='claimed', lease_owner='w',"
                    " lease_until=now() + interval '60s' WHERE session_id=%s", (s4,))
    conn.commit()
    r4 = prepare_step(conn, s4, f"seal-{u()[:8]}", "drv", 1, fence4, u(), u(), u())
    check("seal while active step open -> ACTIVE_STEP_OPEN",
          r4["outcome"] == "rejected_mismatch" and r4["code"] == "ACTIVE_STEP_OPEN", r4)
    # TURN_ALREADY_CLOSED: a decision_only success closed the turn; a new
    # seal on the same turn is rejected even from a freshly claimed state.
    s5, turn5, st5, effect5, fence5, job5, rh5, ik5 = full_chain_fixture(conn)
    rc = complete_ok(conn, s5, st5, effect5, job5, rh5, ik5,
                     message={"text": "closed"})
    check("turn-close fixture accepted", rc["outcome"] == "accepted", rc)
    r5c = claim_session(conn, s5, "drv")
    check("re-claim after turn close", r5c["outcome"] == "claimed", r5c)
    r5 = prepare_step(conn, s5, f"seal-{u()[:8]}", "drv", 1, r5c["session_fence"],
                      u(), turn5, u())
    check("seal on closed turn -> TURN_ALREADY_CLOSED",
          r5["outcome"] == "rejected_mismatch" and r5["code"] == "TURN_ALREADY_CLOSED",
          r5)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM steps WHERE session_id=%s", (s5,))
        check("closed-turn seal zero new steps", cur.fetchone()[0] == 1)


def test_seal_command_idempotency(conn) -> None:
    s = fresh_session(conn)
    claim_session(conn, s, "drv")
    turn, step, effect = u(), u(), u()
    cmd = f"seal-{u()[:8]}"
    r1 = prepare_step(conn, s, cmd, "drv", 1, 2, step, turn, effect)
    check("seal accepted", r1["outcome"] == "accepted", r1)
    r2 = prepare_step(conn, s, cmd, "drv", 1, 2, step, turn, effect)
    check("seal same command_id replays original receipt",
          r2["outcome"] == "accepted" and r2["receipt"] == r1["receipt"])
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM effect_attempts WHERE session_id=%s", (s,))
        check("seal retry: still one attempt row", cur.fetchone()[0] == 1)


# ---------------------------------------------------------------------------
# Dispatch gate
# ---------------------------------------------------------------------------

def test_dispatch(conn) -> None:
    s, turn, step, effect, fence, job_fence = seal_fixture(conn)
    cmd = f"dsp-{u()[:8]}"
    r1 = dispatch_effect(conn, s, cmd, effect, "drv", 1, fence, job_fence)
    check("dispatch accepted", r1["outcome"] == "accepted", r1)
    check("dispatch receipt", r1["receipt"]["dispatch_count"] == 1
          and r1["receipt"]["status"] == "dispatch_started", r1["receipt"])
    with conn.cursor() as cur:
        cur.execute("SELECT status, dispatch_count, dispatched_at IS NOT NULL"
                    " FROM effect_requests WHERE effect_id=%s", (effect,))
        check("effect dispatch_started + count 1 + marker",
              cur.fetchone() == ("dispatch_started", 1, True))
        cur.execute("SELECT status, dispatched_at IS NOT NULL FROM effect_attempts"
                    " WHERE effect_id=%s AND attempt_no=1", (effect,))
        check("attempt dispatch marker written",
              cur.fetchone() == ("dispatch_started", True))
        cur.execute("SELECT count(*) FROM effect_attempts WHERE effect_id=%s", (effect,))
        check("no new attempt rows after dispatch (bind-only)", cur.fetchone()[0] == 1)
    r2 = dispatch_effect(conn, s, cmd, effect, "drv", 1, fence, job_fence)
    check("dispatch retry replays receipt",
          r2["outcome"] == "accepted" and r2["receipt"] == r1["receipt"])
    r3 = dispatch_effect(conn, s, f"dsp-{u()[:8]}", effect, "drv", 1, fence, job_fence)
    check("repeat dispatch -> EFFECT_NOT_READY",
          r3["outcome"] == "rejected_mismatch" and r3["code"] == "EFFECT_NOT_READY", r3)
    with conn.cursor() as cur:
        cur.execute("SELECT dispatch_count FROM effect_requests WHERE effect_id=%s",
                    (effect,))
        check("rejected re-dispatch does not bump the count", cur.fetchone()[0] == 1)
    # Old fence envelope / wrong job fence.
    s2, _t2, _s2, effect2, fence2, job2 = seal_fixture(conn)
    r4 = dispatch_effect(conn, s2, f"dsp-{u()[:8]}", effect2, "drv", 1, fence2 - 1, job2)
    check("dispatch stale fence -> SESSION_FENCE_STALE",
          r4["outcome"] == "rejected_stale" and r4["code"] == "SESSION_FENCE_STALE", r4)
    r5 = dispatch_effect(conn, s2, f"dsp-{u()[:8]}", effect2, "drv", 1, fence2, job2 + 3)
    check("dispatch stale job fence -> STALE_JOB_FENCE",
          r5["outcome"] == "rejected_stale" and r5["code"] == "STALE_JOB_FENCE", r5)
    with conn.cursor() as cur:
        cur.execute("SELECT status, dispatch_count FROM effect_requests"
                    " WHERE effect_id=%s", (effect2,))
        check("rejected dispatches left the effect untouched",
              cur.fetchone() == ("ready", 0))
    # Missing attempt row: INFRA_PROTOCOL_VIOLATION (dispatch MUST NOT
    # silently rebuild it).
    s3, _t3, _s3, effect3, fence3, job3 = seal_fixture(conn)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM effect_attempts WHERE effect_id=%s", (effect3,))
    conn.commit()
    try:
        dispatch_effect(conn, s3, f"dsp-{u()[:8]}", effect3, "drv", 1, fence3, job3)
        check("dispatch without attempt -> INFRA_PROTOCOL_VIOLATION", False, "no error")
    except psycopg2.Error as exc:
        check("dispatch without attempt -> INFRA_PROTOCOL_VIOLATION",
              "INFRA_PROTOCOL_VIOLATION" in str(exc), str(exc)[:120])
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM effect_attempts WHERE effect_id=%s",
                    (effect3,))
        check("dispatch did not rebuild the attempt row", cur.fetchone()[0] == 0)


# ---------------------------------------------------------------------------
# complete_effect: success full chain + finish_session
# ---------------------------------------------------------------------------

def test_complete_success_full_chain(conn) -> None:
    s = fresh_session(conn)
    turn = u()
    # The P0B loop starts with a user event (public append).
    entry = build_entry("user/message", {"text": "hello"}, schema_version=SV,
                        canonicalizer_version=CV, turn_id=turn,
                        semantic_input_ordinal=1)
    r0 = call_append_events(conn, s, f"usr-{u()[:8]}", "drv", 1, 1, [entry])
    check("user event appended", r0["outcome"] == "accepted", r0["outcome"])

    r1 = claim_session(conn, s, "drv")
    fence = r1["session_fence"]
    step, effect = u(), u()
    rs = prepare_step(conn, s, f"seal-{u()[:8]}", "drv", 1, fence, step, turn, effect,
                      request_hash="rh-full", idempotency_key="ik-full")
    check("seal accepted", rs["outcome"] == "accepted", rs)
    fence = rs["receipt"]["session_fence"]
    job_fence = rs["receipt"]["job_fence"]
    rd = dispatch_effect(conn, s, f"dsp-{u()[:8]}", effect, "drv", 1, fence, job_fence)
    check("dispatch accepted", rd["outcome"] == "accepted", rd)

    rc = complete_effect(
        conn, s, f"cmp-{u()[:8]}", effect, "drv", 1,
        dispatch_session_fence=2, job_fence=job_fence, step_id=step,
        request_hash="rh-full", idempotency_key="ik-full",
        outcome="succeeded", message={"text": "final answer"}, tools=[],
        decision_only=True, final_tools=False, evidence=good_evidence())
    check("complete accepted", rc["outcome"] == "accepted", rc)
    rec = rc["receipt"]
    check("complete receipt classification + step + session",
          rec["classification"] == "known_success"
          and rec["step_status"] == "succeeded"
          and rec["session_state"] == "ready", rec)

    with conn.cursor() as cur:
        cur.execute("SELECT status, result_hash, provider_request_id IS NOT NULL"
                    " FROM effect_requests WHERE effect_id=%s", (effect,))
        check("effect succeeded + result frozen",
              cur.fetchone() == ("succeeded", rec["result_hash"], True))
        cur.execute("SELECT status, result_hash, completed_at IS NOT NULL"
                    " FROM effect_attempts WHERE effect_id=%s AND attempt_no=1",
                    (effect,))
        check("attempt succeeded + completed",
              cur.fetchone() == ("succeeded", rec["result_hash"], True))
        # SQL-generated assistant/message: exactly one, payload = message.
        cur.execute("SELECT count(*) FROM session_events WHERE session_id=%s"
                    " AND event_type='assistant/message'", (s,))
        check("exactly one assistant/message event", cur.fetchone()[0] == 1)
        cur.execute("SELECT payload, payload_hash, event_class, turn_id, step_id,"
                    " effect_id, semantic_input_ordinal, internal_semantic_ordinal"
                    " FROM session_events WHERE session_id=%s"
                    " AND event_type='assistant/message'", (s,))
        amsg = cur.fetchone()
        msg_text, msg_hash = canon({"text": "final answer"})
        check("assistant/message payload = final message",
              amsg == (msg_text, msg_hash, "semantic", turn, step, effect, None, 1),
              amsg)
        cur.execute("SELECT payload, event_key, turn_id, internal_semantic_ordinal"
                    " FROM session_events WHERE session_id=%s AND event_type='turn/end'",
                    (s,))
        end_payload, end_key, end_turn, end_iso = cur.fetchone()
        check("turn/end payload {interrupted:false}",
              end_payload == '{"interrupted":false}' and end_turn == turn, end_payload)
        check("turn/end internal ordinal 2 (assistant/message first)", end_iso == 2)
        cur.execute("SELECT turn_end_key, head_event_key, slot_status,"
                    " resolution_identity_canonical, version FROM turn_end_slots"
                    " WHERE session_id=%s AND turn_id=%s", (s, turn))
        slot = cur.fetchone()
        check("turn_end_slot known row with head = turn/end key",
              slot[2] == "known" and slot[1] == end_key and slot[4] == 1, slot)
        check("v_turn_end_key == keys.turn_end_key_v1 (byte parity)",
              slot[0] == turn_end_key_v1(s, turn), slot[0])
        cur.execute("SELECT status, stage, outcome_code, decision_only, final_tools,"
                    " pending_effect_count, terminal_effect_count, closed_at IS NOT NULL"
                    " FROM steps WHERE step_id=%s", (step,))
        check("step succeeded/closed + marks persisted",
              cur.fetchone() == ("succeeded", "closed", "SUCCEEDED", True, False,
                                 0, 1, True))
        cur.execute("SELECT state, active_step_id FROM sessions WHERE session_id=%s",
                    (s,))
        check("session ready after rule 6 (aggregation never completes)",
              cur.fetchone() == ("ready", step))

    # finish_session: claim again, then complete.
    r2 = claim_session(conn, s, "drv")
    fence = r2["session_fence"]
    rf = finish_session(conn, s, f"fin-{u()[:8]}", "drv", 1, fence)
    check("finish_session accepted", rf["outcome"] == "accepted", rf)
    with conn.cursor() as cur:
        cur.execute("SELECT state, session_fence, active_step_id, lease_owner,"
                    " failure_code FROM sessions WHERE session_id=%s", (s,))
        row = cur.fetchone()
        check("session completed + pointer cleared + lease released",
              row == ("completed", fence + 1, None, None, None), row)
    # Terminal: a second finish is a stable rejection.
    rf2 = finish_session(conn, s, f"fin-{u()[:8]}", "drv", 1, fence + 1)
    check("finish on terminal -> SESSION_NOT_CLAIMED",
          rf2["outcome"] == "rejected_mismatch" and rf2["code"] == "SESSION_NOT_CLAIMED",
          rf2)
    # Stale fence / no closed turn: stable rejections.
    s2 = fresh_session(conn)
    claim_session(conn, s2, "drv")
    rf3 = finish_session(conn, s2, f"fin-{u()[:8]}", "drv", 1, 99)
    check("finish stale fence -> SESSION_FENCE_STALE",
          rf3["outcome"] == "rejected_stale" and rf3["code"] == "SESSION_FENCE_STALE",
          rf3)
    rf4 = finish_session(conn, s2, f"fin-{u()[:8]}", "drv", 1, 2)
    check("finish with no closed turn -> SESSION_NOT_FINALIZABLE",
          rf4["outcome"] == "rejected_mismatch"
          and rf4["code"] == "SESSION_NOT_FINALIZABLE", rf4)


def test_complete_idempotency(conn) -> None:
    s, turn, step, effect, fence, job_fence, rh, ik = full_chain_fixture(conn)
    cmd = f"cmp-{u()[:8]}"
    evidence = good_evidence()  # response-loss retries reuse ALL inputs
    kw = dict(driver="drv", driver_epoch=1, dispatch_session_fence=2,
              job_fence=job_fence, step_id=step,
              request_hash=rh, idempotency_key=ik,
              outcome="succeeded", message={"text": "done"}, tools=[],
              decision_only=True, final_tools=False, evidence=evidence)
    r1 = complete_effect(conn, s, cmd, effect, **kw)
    check("settlement accepted", r1["outcome"] == "accepted", r1)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM session_events WHERE session_id=%s", (s,))
        before = cur.fetchone()[0]
    r2 = complete_effect(conn, s, cmd, effect, **kw)
    check("same command_id retry replays original receipt",
          r2["outcome"] == "accepted" and r2["receipt"] == r1["receipt"])
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM session_events WHERE session_id=%s", (s,))
        check("retry stored zero new events", cur.fetchone()[0] == before)
    r3 = complete_effect(conn, s, f"cmp-{u()[:8]}", effect, **kw)
    check("different command_id re-settle -> ATTEMPT_ALREADY_SETTLED",
          r3["outcome"] == "rejected_mismatch"
          and r3["code"] == "ATTEMPT_ALREADY_SETTLED", r3)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM session_events WHERE session_id=%s", (s,))
        check("re-settle rejection stored zero new events",
              cur.fetchone()[0] == before)


# ---------------------------------------------------------------------------
# Dual fence + envelope reads the attempt-row authority
# ---------------------------------------------------------------------------

def test_dual_fence(conn) -> None:
    s, turn, step, effect, fence, job_fence, rh, ik = full_chain_fixture(conn)
    # Stale completion: manually advance current_job_fence (recovery-style
    # takeover), then complete with the OLD job fence.
    with conn.cursor() as cur:
        cur.execute("UPDATE effect_requests SET current_job_fence = current_job_fence + 5"
                    " WHERE effect_id=%s", (effect,))
    conn.commit()
    r = complete_effect(
        conn, s, f"cmp-{u()[:8]}", effect, "drv", 1,
        dispatch_session_fence=2, job_fence=job_fence, step_id=step,
        request_hash=rh, idempotency_key=ik, outcome="succeeded",
        message={"text": "late"}, tools=[], decision_only=True,
        final_tools=False, evidence=good_evidence())
    check("stale job fence -> STALE_JOB_FENCE rejected_stale",
          r["outcome"] == "rejected_stale" and r["code"] == "STALE_JOB_FENCE", r)
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM effect_requests WHERE effect_id=%s", (effect,))
        check("stale completion: zero control state (still dispatch_started)",
              cur.fetchone()[0] == "dispatch_started")
        cur.execute("SELECT status FROM effect_attempts WHERE effect_id=%s", (effect,))
        check("stale completion: attempt untouched",
              cur.fetchone()[0] == "dispatch_started")
        cur.execute("SELECT count(*) FROM session_events WHERE session_id=%s", (s,))
        check("stale completion: zero events", cur.fetchone()[0] == 0)
        cur.execute("SELECT count(*) FROM turn_end_slots WHERE session_id=%s", (s,))
        check("stale completion: zero slots", cur.fetchone()[0] == 0)
        cur.execute("SELECT reason FROM effect_audit WHERE effect_id=%s", (effect,))
        check("stale completion wrote the audit row",
              cur.fetchone()[0] == "STALE_JOB_FENCE")
    # Envelope reads the attempt-row authority (frozen snapshot columns).
    s2, _t2, step2, effect2, _f2, job2, rh2, ik2 = full_chain_fixture(conn)
    for label, override in [
        ("wrong driver", dict(driver="rogue")),
        ("wrong epoch", dict(driver_epoch=9)),
        ("wrong dispatch_session_fence", dict(dispatch_session_fence=99)),
        ("wrong request_hash", dict(request_hash="bogus")),
        ("wrong idempotency_key", dict(idempotency_key="bogus")),
        ("wrong step_id", dict(step_id=u())),
    ]:
        kw = dict(driver="drv", driver_epoch=1, dispatch_session_fence=2,
                  job_fence=job2, step_id=step2, request_hash=rh2,
                  idempotency_key=ik2,
                  outcome="succeeded", message={"text": "x"}, tools=[],
                  decision_only=True, final_tools=False, evidence=good_evidence())
        kw.update(override)
        rr = complete_effect(conn, s2, f"cmp-{u()[:8]}", effect2, **kw)
        check(f"envelope tamper ({label}) rejected",
              rr["outcome"] in ("rejected_stale", "rejected_mismatch")
              and rr["code"] in ("DRIVER_EPOCH_STALE", "STALE_SESSION_FENCE",
                                 "REQUEST_IDENTITY_MISMATCH",
                                 "STEP_MISMATCH"), rr)
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM effect_requests WHERE effect_id=%s", (effect2,))
        check("tampered envelopes left zero control state",
              cur.fetchone()[0] == "dispatch_started")


# ---------------------------------------------------------------------------
# Declared outcome vs derived (RESULT_OUTCOME_MISMATCH audit, never rejected)
# ---------------------------------------------------------------------------

def test_outcome_mismatch(conn) -> None:
    s, turn, step, effect, fence, job_fence, rh, ik = full_chain_fixture(conn)
    r = complete_effect(
        conn, s, f"cmp-{u()[:8]}", effect, "drv", 1,
        dispatch_session_fence=2, job_fence=job_fence, step_id=step,
        request_hash=rh, idempotency_key=ik,
        outcome="failed_retryable",  # untrusted declared outcome
        message={"text": "fine"}, tools=[], decision_only=True, final_tools=False,
        evidence=good_evidence())
    check("mismatched declared outcome still accepted (settlement by evidence)",
          r["outcome"] == "accepted", r)
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM effect_requests WHERE effect_id=%s", (effect,))
        check("derived status succeeded despite the declaration",
              cur.fetchone()[0] == "succeeded")
        cur.execute("SELECT reason FROM effect_audit WHERE effect_id=%s", (effect,))
        check("RESULT_OUTCOME_MISMATCH audit row present",
              cur.fetchone()[0] == "RESULT_OUTCOME_MISMATCH")

    # Audit timing (contract: the record is bound to the completion settling
    # by the derived result): declared outcome != derived AND an illegal
    # marks combination -> the semantic-layer DECISION_PLAN_INVALID
    # rejection must NOT leave a mismatch audit row behind.
    s2, _t2, step2, effect2, _f2, job2, rh2, ik2 = full_chain_fixture(conn)
    r2 = complete_effect(
        conn, s2, f"cmp-{u()[:8]}", effect2, "drv", 1,
        dispatch_session_fence=2, job_fence=job2, step_id=step2,
        request_hash=rh2, idempotency_key=ik2,
        outcome="failed_retryable",  # mismatching declaration ...
        message={"text": "bad marks"}, tools=[],
        decision_only=False, final_tools=False,  # ... plus an illegal combo
        evidence=good_evidence())
    check("mismatch + illegal marks -> DECISION_PLAN_INVALID",
          r2["outcome"] == "rejected_mismatch"
          and r2["code"] == "DECISION_PLAN_INVALID", r2)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM effect_audit WHERE effect_id=%s",
                    (effect2,))
        check("DECISION_PLAN_INVALID leaves no mismatch audit row",
              cur.fetchone()[0] == 0)
        cur.execute("SELECT status FROM effect_requests WHERE effect_id=%s",
                    (effect2,))
        check("audit-timing rejection: zero control state",
              cur.fetchone()[0] == "dispatch_started")

    # Control: the same mismatching declaration with LEGAL marks settles
    # normally and DOES write the audit row (same-transaction binding).
    s3, _t3, step3, effect3, _f3, job3, rh3, ik3 = full_chain_fixture(conn)
    r3 = complete_effect(
        conn, s3, f"cmp-{u()[:8]}", effect3, "drv", 1,
        dispatch_session_fence=2, job_fence=job3, step_id=step3,
        request_hash=rh3, idempotency_key=ik3,
        outcome="unknown_outcome",  # mismatching declaration
        message={"text": "fine"}, tools=[], decision_only=True, final_tools=False,
        evidence=good_evidence())
    check("mismatch with legal marks settles accepted",
          r3["outcome"] == "accepted", r3)
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM effect_requests WHERE effect_id=%s",
                    (effect3,))
        check("settlement still by evidence (succeeded)",
              cur.fetchone()[0] == "succeeded")
        cur.execute("SELECT reason FROM effect_audit WHERE effect_id=%s",
                    (effect3,))
        check("settled mismatch writes the audit row",
              cur.fetchone()[0] == "RESULT_OUTCOME_MISMATCH")

    # (ii) declared failed_retryable x evidence with NO terminal receipt
    # (neither provider_receipt nor no_side_effect_proof): the unique
    # classifier derives `unknown`, so the effect MUST settle unknown_outcome
    # (a known failure MUST NOT be recorded) with exactly one mismatch row.
    s4, _t4, step4, effect4, _f4, job4, rh4, ik4 = full_chain_fixture(conn)
    r4 = complete_effect(
        conn, s4, f"cmp-{u()[:8]}", effect4, "drv", 1,
        dispatch_session_fence=2, job_fence=job4, step_id=step4,
        request_hash=rh4, idempotency_key=ik4,
        outcome="failed_retryable",  # declared known failure ...
        message={"text": "no receipt"}, tools=[], decision_only=True,
        final_tools=False,
        evidence={"class": "known_failure"})  # ... but no receipt and no proof
    check("(ii) accepted (settlement by the derived classification)",
          r4["outcome"] == "accepted", r4)
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM effect_requests WHERE effect_id=%s",
                    (effect4,))
        check("(ii) evidence without a terminal receipt derives "
              "unknown_outcome", cur.fetchone()[0] == "unknown_outcome")
        cur.execute("SELECT count(*) FROM effect_audit WHERE effect_id=%s"
                    " AND reason='RESULT_OUTCOME_MISMATCH'", (effect4,))
        check("(ii) exactly one mismatch audit row", cur.fetchone()[0] == 1)

    # (iii) declared cancelled_after_dispatch x provider-confirmed success:
    # the derived classification wins, so the effect MUST settle succeeded
    # and MUST NOT take a cancellation terminal state.
    s5, _t5, step5, effect5, _f5, job5, rh5, ik5 = full_chain_fixture(conn)
    r5 = complete_effect(
        conn, s5, f"cmp-{u()[:8]}", effect5, "drv", 1,
        dispatch_session_fence=2, job_fence=job5, step_id=step5,
        request_hash=rh5, idempotency_key=ik5,
        outcome="cancelled_after_dispatch",  # declared cancellation ...
        message={"text": "ok"}, tools=[], decision_only=True,
        final_tools=False, evidence=good_evidence())  # ... provider says success
    check("(iii) accepted (settlement by the derived classification)",
          r5["outcome"] == "accepted", r5)
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM effect_requests WHERE effect_id=%s",
                    (effect5,))
        check("(iii) provider-confirmed success derives succeeded",
              cur.fetchone()[0] == "succeeded")
        cur.execute("SELECT count(*) FROM effect_audit WHERE effect_id=%s"
                    " AND reason='RESULT_OUTCOME_MISMATCH'", (effect5,))
        check("(iii) exactly one mismatch audit row", cur.fetchone()[0] == 1)


# ---------------------------------------------------------------------------
# Semantic layer: decision marks mutex (validation written in full)
# ---------------------------------------------------------------------------

def test_decision_plan_invalid(conn) -> None:
    cases = [
        ("empty plan x decision_only=false", [], False, False),
        ("empty plan x decision_only=true x final_tools=true", [], True, True),
        ("non-empty plan x decision_only=true", [{"tool": "t"}], True, False),
        ("non-empty plan x final_tools=false", [{"tool": "t"}], False, False),
    ]
    for label, tools, do, ft in cases:
        s, _t, st, effect, _f, job, rh, ik = full_chain_fixture(conn)
        r = complete_effect(
            conn, s, f"cmp-{u()[:8]}", effect, "drv", 1,
            dispatch_session_fence=2, job_fence=job, step_id=st,
            request_hash=rh, idempotency_key=ik, outcome="succeeded",
            message={"text": "m"}, tools=tools, decision_only=do,
            final_tools=ft, evidence=good_evidence())
        check(f"marks combination ({label}) -> DECISION_PLAN_INVALID",
              r["outcome"] == "rejected_mismatch"
              and r["code"] == "DECISION_PLAN_INVALID", r)
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM effect_requests WHERE effect_id=%s",
                        (effect,))
            check(f"({label}) zero control state",
                  cur.fetchone()[0] == "dispatch_started")
            cur.execute("SELECT count(*) FROM session_events WHERE session_id=%s"
                        " AND event_type='assistant/message'", (s,))
            check(f"({label}) zero semantic events", cur.fetchone()[0] == 0)


# ---------------------------------------------------------------------------
# Unknown path
# ---------------------------------------------------------------------------

def test_unknown_path(conn) -> None:
    s, turn, step, effect, fence, job_fence, rh, ik = full_chain_fixture(conn)
    r = complete_effect(
        conn, s, f"cmp-{u()[:8]}", effect, "drv", 1,
        dispatch_session_fence=2, job_fence=job_fence, step_id=step,
        request_hash=rh, idempotency_key=ik, outcome="unknown_outcome",
        message={"text": "?"}, tools=[], decision_only=False, final_tools=False,
        evidence={"class": "garbled"},  # no bound terminal receipt
        result_payload={"note": "no terminal receipt"})
    check("unknown settlement accepted", r["outcome"] == "accepted", r)
    check("receipt classification unknown",
          r["receipt"]["classification"] == "unknown", r["receipt"])
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM effect_requests WHERE effect_id=%s", (effect,))
        check("effect unknown_outcome", cur.fetchone()[0] == "unknown_outcome")
        cur.execute("SELECT status FROM effect_attempts WHERE effect_id=%s", (effect,))
        check("attempt unknown_outcome", cur.fetchone()[0] == "unknown_outcome")
        cur.execute("SELECT status, outcome_code, unknown_effect_count,"
                    " pending_effect_count FROM steps WHERE step_id=%s", (step,))
        check("step blocked_unknown_effect + derived code",
              cur.fetchone() == ("blocked_unknown_effect", "UNKNOWN_AFTER_DISPATCH",
                                 1, 0))
        cur.execute("SELECT count(*), max(payload) FROM session_events"
                    " WHERE session_id=%s AND event_type='turn/end'", (s,))
        cnt, payload = cur.fetchone()
        check("exactly one provisional turn/end",
              cnt == 1 and payload == '{"outcome":"unknown"}', (cnt, payload))
        cur.execute("SELECT slot_status, head_event_key IS NOT NULL,"
                    " turn_end_key IS NOT NULL FROM turn_end_slots"
                    " WHERE session_id=%s", (s,))
        check("provisional slot row",
              cur.fetchone() == ("provisional", True, True))
        cur.execute("SELECT count(*) FROM session_events WHERE session_id=%s"
                    " AND event_type='assistant/message'", (s,))
        check("no assistant/message on unknown", cur.fetchone()[0] == 0)
        cur.execute("SELECT state FROM sessions WHERE session_id=%s", (s,))
        check("session blocked_unknown_effect (not completed)",
              cur.fetchone()[0] == "blocked_unknown_effect")
    # finish_session cannot complete a blocked session.
    with conn.cursor() as cur:
        cur.execute("UPDATE sessions SET state='claimed', lease_owner='w',"
                    " lease_until=now() + interval '60s' WHERE session_id=%s", (s,))
    conn.commit()
    rf = finish_session(conn, s, f"fin-{u()[:8]}", "drv", 1, fence)
    check("finish on unknown-blocked session -> SESSION_NOT_FINALIZABLE",
          rf["outcome"] == "rejected_mismatch"
          and rf["code"] == "SESSION_NOT_FINALIZABLE", rf)

    # Canonicalizer cross-check: the stored events normalize to the blocked
    # (provisional unknown end) semantics.
    with conn.cursor() as cur:
        cur.execute("SELECT event_type, payload, turn_id, semantic_input_ordinal"
                    " FROM session_events WHERE session_id=%s ORDER BY seq", (s,))
        rows = cur.fetchall()
    normalize_input = []
    for event_type, payload, turn_id, ordinal in rows:
        item = {"event_type": event_type, "payload": json.loads(payload),
                "turn_id": turn_id}
        if ordinal is not None:
            item["semantic_input_ordinal"] = ordinal
        normalize_input.append(item)
    # Effect-level unknown signal read from the control state.
    normalize_input.append({
        "event_type": "tool/result", "payload": {}, "turn_id": turn,
        "effect_id": effect, "effect_status": "unknown_outcome",
        "code": "UNKNOWN_AFTER_DISPATCH"})
    trace = normalize(normalize_input)
    ends = [e for e in trace if e["event_type"] == "turn/end"]
    check("normalize(): single provisional unknown end",
          len(ends) == 1
          and ends[0]["payload"] == {"outcome": "unknown",
                                     "reason": "unknown_after_dispatch"},
          ends)


def test_classify_evidence_unit(conn) -> None:
    eff = u()
    other = u()

    def bound(evidence: dict, effect=eff, attempt=1) -> dict:
        e = dict(evidence)
        e["effect_id"] = str(effect)
        e["attempt_no"] = attempt
        return e

    with conn.cursor() as cur:
        for label, evidence, expected in [
            ("known_success + receipt", bound(good_evidence()), "known_success"),
            ("known_success without receipt", bound({"class": "known_success"}),
             "unknown"),
            ("no class", bound({"anything": 1}), "unknown"),
            ("null", None, "unknown"),
            ("known_cancellation + receipt (frozen row 2, provider leg)",
             bound({"class": "known_cancellation",
                    "provider_receipt": {"receipt_id": "r1"}}), "known_cancellation"),
            ("known_cancellation + pre-side-effect proof (frozen row 2)",
             bound({"class": "known_cancellation",
                    "no_side_effect_proof": {"checked": True}}), "known_cancellation"),
            ("known_cancellation without receipt or proof",
             bound({"class": "known_cancellation"}), "unknown"),
            ("known_failure dual requirement met",
             bound({"class": "known_failure",
                    "provider_receipt": {"receipt_id": "r1"},
                    "no_side_effect_proof": {"checked": True}}), "known_failure"),
            ("known_failure without proof",
             bound({"class": "known_failure",
                    "provider_receipt": {"receipt_id": "r1"}}), "unknown"),
            # Binding tightening: the evidence object must carry the settled
            # attempt's own (effect_id, attempt_no) — anything else is
            # unbound and classifies 'unknown'.
            ("cross-effect receipt_id (binding mismatch)",
             bound(good_evidence(), effect=other), "unknown"),
            ("cross-attempt binding",
             bound(good_evidence(), attempt=2), "unknown"),
            ("binding fields absent (legacy unbound shape)",
             good_evidence(), "unknown"),
            ("malformed effect_id binding",
             bound(good_evidence()) | {"effect_id": "not-a-uuid"}, "unknown"),
        ]:
            cur.execute("SELECT v_classify_evidence(%s::uuid, 1, %s::jsonb)",
                        (eff, json.dumps(evidence)))
            got = cur.fetchone()[0]
            check(f"classify({label}) = {expected}", got == expected, got)
    conn.commit()


# ---------------------------------------------------------------------------
# Late completion of an unknown-settled attempt -> REPAIR_REQUIRED
# ---------------------------------------------------------------------------

def test_late_completion_repair_required(conn) -> None:
    # Two-worker race aftermath: worker 1 settles the attempt unknown (no
    # terminal receipt); worker 2's real result arrives later with a NEW
    # command_id and a fully legal envelope.
    s, turn, step, effect, fence, job_fence, rh, ik = full_chain_fixture(conn)
    r1 = complete_effect(
        conn, s, f"cmp-{u()[:8]}", effect, "drv", 1,
        dispatch_session_fence=2, job_fence=job_fence, step_id=step,
        request_hash=rh, idempotency_key=ik, outcome="unknown_outcome",
        message={"text": "?"}, tools=[], decision_only=False, final_tools=False,
        evidence={"class": "timeout"},  # no terminal receipt -> unknown
        result_payload={"error": {"kind": "timeout"}})
    check("race fixture: unknown settlement accepted",
          r1["outcome"] == "accepted"
          and r1["receipt"]["classification"] == "unknown", r1)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM session_events WHERE session_id=%s", (s,))
        events_before = cur.fetchone()[0]

    # The late winner result: legal envelope (driver/epoch/fences/identity
    # all still match the frozen attempt snapshot), known_success evidence.
    late_evidence = good_evidence()
    r2 = complete_effect(
        conn, s, f"cmp-{u()[:8]}", effect, "drv", 1,
        dispatch_session_fence=2, job_fence=job_fence, step_id=step,
        request_hash=rh, idempotency_key=ik, outcome="succeeded",
        message={"text": "actually fine"}, tools=[], decision_only=True,
        final_tools=False, evidence=late_evidence)
    check("late completion of unknown attempt -> repair_required",
          r2["outcome"] == "repair_required"
          and r2["code"] == "REPAIR_REQUIRED", r2)
    check("repair receipt shape",
          r2["receipt"]["outcome"] == "repair_required"
          and r2["receipt"]["code"] == "REPAIR_REQUIRED"
          and r2["receipt"]["effect_id"] == effect, r2["receipt"])
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM effect_requests WHERE effect_id=%s", (effect,))
        check("repair_required: zero control state (still unknown_outcome)",
              cur.fetchone()[0] == "unknown_outcome")
        cur.execute("SELECT status FROM effect_attempts WHERE effect_id=%s", (effect,))
        check("repair_required: attempt still unknown_outcome",
              cur.fetchone()[0] == "unknown_outcome")
        cur.execute("SELECT state FROM sessions WHERE session_id=%s", (s,))
        check("repair_required: session still blocked_unknown_effect",
              cur.fetchone()[0] == "blocked_unknown_effect")
        cur.execute("SELECT count(*) FROM session_events WHERE session_id=%s", (s,))
        check("repair_required: zero new events",
              cur.fetchone()[0] == events_before)
        cur.execute("SELECT reason FROM effect_audit WHERE effect_id=%s", (effect,))
        check("repair_required audit row present",
              cur.fetchone()[0] == "REPAIR_REQUIRED")
        cur.execute("SELECT first_outcome FROM command_bindings"
                    " WHERE session_id=%s AND command_id=%s",
                    (s, r2["receipt"]["command_id"]))
        check("repair_required occupies the binding",
              cur.fetchone()[0] == "repair_required")
        cur.execute("SELECT outcome, code FROM command_receipts"
                    " WHERE session_id=%s AND command_id=%s",
                    (s, r2["receipt"]["command_id"]))
        check("repair_required receipt row persisted",
              cur.fetchone() == ("repair_required", "REPAIR_REQUIRED"))
    # Same command_id retry replays the repair_required receipt (byte-equal
    # request, evidence object included).
    r3 = complete_effect(
        conn, s, r2["receipt"]["command_id"], effect, "drv", 1,
        dispatch_session_fence=2, job_fence=job_fence, step_id=step,
        request_hash=rh, idempotency_key=ik, outcome="succeeded",
        message={"text": "actually fine"}, tools=[], decision_only=True,
        final_tools=False, evidence=late_evidence)
    check("repair_required retry replays the receipt",
          r3["outcome"] == "repair_required" and r3["receipt"] == r2["receipt"],
          r3)


# ---------------------------------------------------------------------------
# Evidence binding at the settlement boundary (EVIDENCE_NOT_BOUND)
# ---------------------------------------------------------------------------

def test_evidence_binding_settlement(conn) -> None:
    # A cross-effect receipt_id (legal known_success shape for ANOTHER
    # effect) must not settle this attempt as success: unbound -> unknown
    # closure, receipt annotated EVIDENCE_NOT_BOUND.
    s, turn, step, effect, fence, job_fence, rh, ik = full_chain_fixture(conn)
    cross = good_evidence() | {"effect_id": u(), "attempt_no": 1}
    r = complete_effect(
        conn, s, f"cmp-{u()[:8]}", effect, "drv", 1,
        dispatch_session_fence=2, job_fence=job_fence, step_id=step,
        request_hash=rh, idempotency_key=ik, outcome="succeeded",
        message={"text": "claim"}, tools=[], decision_only=True,
        final_tools=False, evidence=cross)
    check("cross-effect receipt -> accepted but classified unknown",
          r["outcome"] == "accepted"
          and r["receipt"]["classification"] == "unknown", r)
    check("cross-effect receipt annotated EVIDENCE_NOT_BOUND",
          r["receipt"].get("code") == "EVIDENCE_NOT_BOUND",
          r["receipt"].get("code"))
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM effect_requests WHERE effect_id=%s", (effect,))
        check("cross-effect evidence settles unknown_outcome",
              cur.fetchone()[0] == "unknown_outcome")
        cur.execute("SELECT count(*) FROM session_events WHERE session_id=%s"
                    " AND event_type='assistant/message'", (s,))
        check("cross-effect evidence: no assistant/message", cur.fetchone()[0] == 0)

    # Control: the SAME shape bound to the settled effect settles success.
    s2, _t2, step2, effect2, _f2, job2, rh2, ik2 = full_chain_fixture(conn)
    r2 = complete_effect(
        conn, s2, f"cmp-{u()[:8]}", effect2, "drv", 1,
        dispatch_session_fence=2, job_fence=job2, step_id=step2,
        request_hash=rh2, idempotency_key=ik2, outcome="succeeded",
        message={"text": "mine"}, tools=[], decision_only=True,
        final_tools=False, evidence=bound_evidence(effect2))
    check("correctly bound evidence settles known_success",
          r2["outcome"] == "accepted"
          and r2["receipt"]["classification"] == "known_success", r2)


# ---------------------------------------------------------------------------
# claim CAS: optional expected session fence
# ---------------------------------------------------------------------------

def test_claim_expected_fence_cas(conn) -> None:
    s = fresh_session(conn)
    # Matching expected fence claims normally.
    r1 = claim_session(conn, s, "drv", expected_session_fence=1)
    check("claim with matching expected fence",
          r1 == {"outcome": "claimed", "session_fence": 2}, r1)
    ry = yield_session(conn, s, "drv", 1, 2)
    check("fixture yield ok", ry["outcome"] == "yielded", ry)
    # Stale expected fence: rejected_stale, lease untouched.
    r2 = claim_session(conn, s, "drv", expected_session_fence=1)
    check("claim with stale expected fence -> SESSION_FENCE_STALE",
          r2["outcome"] == "rejected_stale"
          and r2["code"] == "SESSION_FENCE_STALE", r2)
    with conn.cursor() as cur:
        cur.execute("SELECT state, lease_owner, session_fence FROM sessions"
                    " WHERE session_id=%s", (s,))
        check("stale-fence claim left the lease untouched",
              cur.fetchone() == ("ready", None, 3))
    # NULL (default / legacy shape) keeps the unchecked behavior: a claim
    # with no expected fence still succeeds on the current fence.
    r3 = claim_session(conn, s, "drv", expected_session_fence=None)
    check("claim with NULL expected fence keeps legacy behavior",
          r3 == {"outcome": "claimed", "session_fence": 4}, r3)


# ---------------------------------------------------------------------------
# NULL envelope legs fail closed (driver/driver_epoch omitted = mismatch)
# ---------------------------------------------------------------------------

def test_null_envelope_fail_closed(conn) -> None:
    s = fresh_session(conn)
    r = claim_session(conn, s, "drv", None)
    check("claim epoch NULL -> rejected_stale",
          r["outcome"] == "rejected_stale" and r["code"] == "DRIVER_EPOCH_MISMATCH", r)
    r = claim_session(conn, s, None, 1)
    check("claim driver NULL -> rejected_stale",
          r["outcome"] == "rejected_stale" and r["code"] == "DRIVER_EPOCH_MISMATCH", r)
    with conn.cursor() as cur:
        cur.execute("SELECT state, lease_owner FROM sessions WHERE session_id=%s", (s,))
        check("NULL-epoch claims left no lease",
              cur.fetchone() == ("ready", None))
    # prepare_step seal guard: NULL epoch is stale, zero side effects.
    claim_session(conn, s, "drv")
    r = prepare_step(conn, s, f"seal-{u()[:8]}", "drv", None, 2, u(), u(), u())
    check("seal epoch NULL -> DRIVER_EPOCH_STALE",
          r["outcome"] == "rejected_stale" and r["code"] == "DRIVER_EPOCH_STALE", r)
    # yield guard: NULL epoch on a legitimately held lease is stale.
    s2 = fresh_session(conn)
    rc = claim_session(conn, s2, "drv", lease_owner="w", lease_seconds=60)
    ry = yield_session(conn, s2, "drv", None, rc["session_fence"], lease_owner="w")
    check("yield epoch NULL -> rejected_stale",
          ry["outcome"] == "rejected_stale" and ry["code"] == "DRIVER_EPOCH_MISMATCH",
          ry)
    with conn.cursor() as cur:
        cur.execute("SELECT state FROM sessions WHERE session_id=%s", (s2,))
        check("NULL-epoch yield did not release the lease",
              cur.fetchone()[0] == "claimed")
    # dispatch + complete guards against the session/attempt authorities.
    s3, _t3, st3, effect3, fence3, job3, rh3, ik3 = full_chain_fixture(conn)
    r = dispatch_effect(conn, s3, f"dsp-{u()[:8]}", effect3, "drv", None,
                        fence3, job3)
    check("dispatch epoch NULL -> DRIVER_EPOCH_STALE",
          r["outcome"] == "rejected_stale" and r["code"] == "DRIVER_EPOCH_STALE", r)
    r = complete_effect(
        conn, s3, f"cmp-{u()[:8]}", effect3, "drv", None,
        dispatch_session_fence=2, job_fence=job3, step_id=st3,
        request_hash=rh3, idempotency_key=ik3, outcome="succeeded",
        message={"text": "x"}, tools=[], decision_only=True, final_tools=False,
        evidence=good_evidence())
    check("complete epoch NULL (attempt authority) -> DRIVER_EPOCH_STALE",
          r["outcome"] == "rejected_stale" and r["code"] == "DRIVER_EPOCH_STALE", r)
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM effect_requests WHERE effect_id=%s", (effect3,))
        check("NULL-epoch envelopes left zero control state",
              cur.fetchone()[0] == "dispatch_started")
    # finish_session guard.
    s4, _t4, st4, effect4, fence4, job4, rh4, ik4 = full_chain_fixture(conn)
    complete_ok(conn, s4, st4, effect4, job4, rh4, ik4)
    claim = claim_session(conn, s4, "drv")
    r = finish_session(conn, s4, f"fin-{u()[:8]}", "drv", None,
                       claim["session_fence"])
    check("finish epoch NULL -> DRIVER_EPOCH_STALE",
          r["outcome"] == "rejected_stale" and r["code"] == "DRIVER_EPOCH_STALE", r)
    with conn.cursor() as cur:
        cur.execute("SELECT state FROM sessions WHERE session_id=%s", (s4,))
        check("NULL-epoch finish left the session claimed",
              cur.fetchone()[0] == "claimed")


# ---------------------------------------------------------------------------
# final_tools decision result: normalized tools plan persistence
# ---------------------------------------------------------------------------

def test_final_tools_plan_persistence(conn) -> None:
    s, turn, step, effect, fence, job_fence, rh, ik = full_chain_fixture(conn)
    tools = [{"name": "t1", "args": {"a": 1}}, {"name": "t2", "args": {}}]
    r = complete_effect(
        conn, s, f"cmp-{u()[:8]}", effect, "drv", 1,
        dispatch_session_fence=2, job_fence=job_fence, step_id=step,
        request_hash=rh, idempotency_key=ik, outcome="succeeded",
        message={"text": "plan"}, tools=tools, decision_only=False,
        final_tools=True, evidence=good_evidence())
    check("final_tools completion accepted", r["outcome"] == "accepted", r)
    plan_text, plan_hash = canon(tools)
    with conn.cursor() as cur:
        cur.execute("SELECT status, stage, decision_only, final_tools,"
                    " plan_canonical, plan_hash FROM steps WHERE step_id=%s",
                    (step,))
        row = cur.fetchone()
        check("final_tools: step ready/decision with persisted marks",
              row[:4] == ("ready", "decision", False, True), row)
        check("final_tools: normalized tools plan persisted verbatim",
              row[4] == plan_text, (row[4], plan_text))
        check("final_tools: plan_hash = SHA-256 over the persisted plan",
              row[5] == plan_hash, (row[5], plan_hash))
        check("plan_hash is a function of the plan, not the full result",
              row[5] != r["receipt"]["result_hash"],
              (row[5], r["receipt"]["result_hash"]))
        # The later tools seal recomputes plan_hash from the persisted plan
        # (digest 2.6.2 step 2 shape): recompute-and-match must succeed.
        cur.execute("SELECT v_sha256_hex(plan_canonical) = plan_hash"
                    " FROM steps WHERE step_id=%s", (step,))
        check("recompute plan_hash from the persisted plan matches",
              cur.fetchone()[0] is True)
        cur.execute("SELECT count(*) FROM session_events WHERE session_id=%s"
                    " AND event_type='turn/end'", (s,))
        check("final_tools branch emits no turn/end (tools seal is LATER)",
              cur.fetchone()[0] == 0)
    # decision_only branch keeps both plan columns NULL (empty plan is fully
    # determined by the mark) and still closes the turn.
    s2, _t2, step2, effect2, _f2, job2, rh2, ik2 = full_chain_fixture(conn)
    r2 = complete_ok(conn, s2, step2, effect2, job2, rh2, ik2,
                     message={"text": "final"})
    check("decision_only completion accepted", r2["outcome"] == "accepted", r2)
    with conn.cursor() as cur:
        cur.execute("SELECT plan_canonical, plan_hash, status FROM steps"
                    " WHERE step_id=%s", (step2,))
        pc, ph, status = cur.fetchone()
        check("decision_only: plan columns stay NULL, step closed",
              pc is None and ph is None and status == "succeeded", (pc, ph, status))
    # Semantic-layer rejections: plan text missing / not matching the result
    # payload's tools member (direct SQL — the client always sends a
    # consistent plan; the envelope must carry the fixture's frozen attempt
    # identity and known_success evidence so the run reaches the plan check).
    s5, _t5, st5, effect5, _f5, job5, rh5, ik5 = full_chain_fixture(conn)

    def direct_complete(cmd, result_text, plan_text):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT outcome, code FROM v_complete_effect("
                "%s::uuid, %s, %s::uuid, 1, %s::uuid, 'drv', 1, 2, %s,"
                " 'succeeded', %s, %s, %s, %s, %s, 'sv@1', 'canon@1',"
                " (SELECT v_sha256_hex('{}')), '{}', %s::jsonb)",
                (s5, cmd, effect5, st5, job5, rh5, ik5, result_text,
                 '{"text":"m"}', plan_text,
                 json.dumps(bound_evidence(effect5))))
            return cur.fetchone()

    result5 = ('{"message":{"text":"m"},"tools":[{"name":"t1"}],'
               '"decision_only":false,"final_tools":true}')
    outcome, code = direct_complete(f"cmp-{u()[:8]}", result5, None)
    check("missing plan canonical -> DECISION_PLAN_INVALID",
          outcome == "rejected_mismatch" and code == "DECISION_PLAN_INVALID",
          (outcome, code))
    outcome, code = direct_complete(f"cmp-{u()[:8]}", result5,
                                    '[{"name":"OTHER"}]')
    check("plan canonical mismatching result tools -> DECISION_PLAN_INVALID",
          outcome == "rejected_mismatch" and code == "DECISION_PLAN_INVALID",
          (outcome, code))
    outcome, code = direct_complete(f"cmp-{u()[:8]}", result5, 'not-json')
    check("plan canonical not valid JSON -> DECISION_PLAN_INVALID",
          outcome == "rejected_mismatch" and code == "DECISION_PLAN_INVALID",
          (outcome, code))
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM effect_requests WHERE effect_id=%s",
                    (effect5,))
        check("plan rejections left zero control state",
              cur.fetchone()[0] == "dispatch_started")
    conn.commit()


# ---------------------------------------------------------------------------
# known_cancellation settlement: NOT a G4-stage behaviour.
# ---------------------------------------------------------------------------
# G8b opens the known_cancellation terminal settlement (the exit-5
# disposition of the shared cancel closure sub-operation) through
# v_settle_known_cancellation, which lives in v8/cancel/v8_closure.sql and
# runs the shared aggregation + turn-end derivation — none of which exist in
# the effect-stage database (it stops before the retry stage). The
# classification rows of the frozen evidence decision table are covered by
# test_classify_evidence_unit above; the settlement itself is covered by the
# G8b gate (v8/cancel/test_closure.py). The pre-G8b `CANCEL_LATER` refusal
# this gate used to assert no longer exists (ledger A48).


# ---------------------------------------------------------------------------
# Aggregation priority smoke
# ---------------------------------------------------------------------------

def test_pending_sibling(conn) -> None:
    s, turn, step, effect, fence, job_fence, rh, ik = full_chain_fixture(conn)
    # Insert a pending sibling effect on the same sealed batch (tool slot).
    with conn.cursor() as cur:
        cur.execute("SELECT batch_id FROM effect_requests WHERE effect_id=%s", (effect,))
        batch = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO effect_requests(effect_id, session_id, step_id, batch_id,"
            " dispatch_ordinal, tool_call_id, effect_kind, execution_mode, driver,"
            " driver_epoch, session_fence, dispatch_session_fence, current_job_fence,"
            " request_hash, idempotency_key, status, retry_class, max_attempts,"
            " dispatched_at)"
            " VALUES (%s, %s, %s, %s, 1, 'tc-1', 'tool_x', 'non_streaming', 'drv', 1,"
            " 2, 2, nextval('v8_job_fence_seq'), 'rh-sib', 'ik-sib',"
            " 'dispatch_started', 'unsafe', 1, now())",
            (u(), s, step, batch))
    conn.commit()
    r = complete_ok(conn, s, step, effect, job_fence, rh, ik)
    check("sibling completion accepted", r["outcome"] == "accepted", r)
    with conn.cursor() as cur:
        cur.execute("SELECT status, outcome_code, pending_effect_count,"
                    " terminal_effect_count FROM steps WHERE step_id=%s", (step,))
        check("rule 2: pending sibling keeps step waiting_effect",
              cur.fetchone() == ("waiting_effect", None, 1, 1))
        cur.execute("SELECT state FROM sessions WHERE session_id=%s", (s,))
        check("rule 2: session stays waiting_effect",
              cur.fetchone()[0] == "waiting_effect")
        cur.execute("SELECT count(*) FROM session_events WHERE session_id=%s"
                    " AND event_type='assistant/message'", (s,))
        check("result event still emitted", cur.fetchone()[0] == 1)
        cur.execute("SELECT count(*) FROM session_events WHERE session_id=%s"
                    " AND event_type='turn/end'", (s,))
        check("no turn/end with a pending sibling", cur.fetchone()[0] == 0)
        cur.execute("SELECT count(*) FROM turn_end_slots WHERE session_id=%s", (s,))
        check("no slot row with a pending sibling", cur.fetchone()[0] == 0)


# ---------------------------------------------------------------------------
# Gate integration on effect commands
# ---------------------------------------------------------------------------

def test_gate_on_effect_commands(conn) -> None:
    s = fresh_session(conn)
    claim_session(conn, s, "drv")
    turn, step, effect = u(), u(), u()
    r = prepare_step(conn, s, f"seal-{u()[:8]}", "drv", 1, 2, step, turn, effect,
                     declared_hash="0" * 64)
    check("seal declared-hash mismatch -> REQUEST_HASH_MISMATCH",
          r["outcome"] == "rejected_mismatch" and r["code"] == "REQUEST_HASH_MISMATCH",
          r)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM steps WHERE session_id=%s", (s,))
        check("hash-mismatch seal zero rows", cur.fetchone()[0] == 0)
    cmd = f"seal-{u()[:8]}"
    r1 = prepare_step(conn, s, cmd, "drv", 1, 2, step, turn, effect)
    check("first payload accepted", r1["outcome"] == "accepted", r1)
    r2 = prepare_step(conn, s, cmd, "drv", 1, 2, u(), u(), u())  # different payload
    check("same command_id different payload -> IDEMPOTENCY_CONFLICT",
          r2["outcome"] == "rejected_mismatch" and r2["code"] == "IDEMPOTENCY_CONFLICT",
          r2)
    # dispatch_effect: mismatch + conflict.
    with conn.cursor() as cur:
        cur.execute("SELECT er.current_job_fence, se.session_fence"
                    " FROM effect_requests er JOIN sessions se"
                    " ON se.session_id = er.session_id WHERE er.effect_id=%s", (effect,))
        job, fence = cur.fetchone()
    r3 = dispatch_effect(conn, s, f"dsp-{u()[:8]}", effect, "drv", 1, fence, job,
                         declared_hash="1" * 64)
    check("dispatch declared-hash mismatch -> REQUEST_HASH_MISMATCH",
          r3["code"] == "REQUEST_HASH_MISMATCH", r3)
    dc = f"dsp-{u()[:8]}"
    r4 = dispatch_effect(conn, s, dc, effect, "drv", 1, fence, job)
    check("dispatch accepted", r4["outcome"] == "accepted", r4)
    r5 = dispatch_effect(conn, s, dc, effect, "drv", 1, fence, job + 1)
    check("dispatch conflict variant -> IDEMPOTENCY_CONFLICT",
          r5["outcome"] == "rejected_mismatch" and r5["code"] == "IDEMPOTENCY_CONFLICT",
          r5)
    # complete_effect: mismatch + conflict.
    with conn.cursor() as cur:
        cur.execute("SELECT request_hash, idempotency_key FROM effect_requests"
                    " WHERE effect_id=%s", (effect,))
        rh, ik = cur.fetchone()
    kw = dict(driver="drv", driver_epoch=1, dispatch_session_fence=2,
              job_fence=job, step_id=step, request_hash=rh,
              idempotency_key=ik,
              outcome="succeeded", tools=[], decision_only=True,
              final_tools=False, evidence=good_evidence())
    cc = f"cmp-{u()[:8]}"
    r6 = complete_effect(conn, s, cc, effect, message={"text": "z"},
                         declared_hash="2" * 64, **kw)
    check("complete declared-hash mismatch -> REQUEST_HASH_MISMATCH",
          r6["code"] == "REQUEST_HASH_MISMATCH", r6)
    # Correcting the declared hash on the SAME command_id replays the
    # original rejection (binding occupied; a new command_id is required).
    r7 = complete_effect(conn, s, cc, effect, message={"text": "z"}, **kw)
    check("complete corrected-hash retry replays the rejection",
          r7["outcome"] == "rejected_mismatch"
          and r7["code"] == "REQUEST_HASH_MISMATCH", r7)
    cc2 = f"cmp-{u()[:8]}"
    r7b = complete_effect(conn, s, cc2, effect, message={"text": "z"}, **kw)
    check("complete accepted under a new command_id",
          r7b["outcome"] == "accepted", r7b)
    r8 = complete_effect(conn, s, cc2, effect, message={"text": "DIFFERENT"}, **kw)
    check("complete conflict variant -> IDEMPOTENCY_CONFLICT",
          r8["outcome"] == "rejected_mismatch"
          and r8["code"] == "IDEMPOTENCY_CONFLICT", r8)


# ---------------------------------------------------------------------------
# SQL/Python cross-checks
# ---------------------------------------------------------------------------

def test_cross_checks(conn) -> None:
    s, turn, step, effect, fence, job_fence, rh, ik = full_chain_fixture(conn)
    r = complete_effect(
        conn, s, f"cmp-{u()[:8]}", effect, "drv", 1,
        dispatch_session_fence=2, job_fence=job_fence, step_id=step,
        request_hash=rh, idempotency_key=ik, outcome="succeeded",
        message={"text": "cross-check"}, tools=[], decision_only=True,
        final_tools=False, evidence=good_evidence())
    check("cross fixture accepted", r["outcome"] == "accepted", r)
    with conn.cursor() as cur:
        cur.execute("SELECT event_type, payload, payload_hash, event_key, seq"
                    " FROM session_events WHERE session_id=%s"
                    " AND event_type IN ('assistant/message','turn/end')"
                    " ORDER BY seq", (s,))
        rows = cur.fetchall()
        cur.execute("SELECT next_seq FROM sessions WHERE session_id=%s", (s,))
        next_seq = cur.fetchone()[0]
    check("two semantic result events", len(rows) == 2, rows)
    et, payload, payload_hash, event_key, seq = rows[0]
    py_text, py_hash = canon({"text": "cross-check"})
    check("assistant/message payload == Python canonical text",
          payload == py_text, payload)
    check("assistant/message payload_hash == Python canonical hash",
          payload_hash == py_hash)
    check("assistant/message event_key == Python completion_event_key",
          event_key == completion_event_key(s, et, effect, 1, payload_hash),
          event_key)
    et2, payload2, payload2_hash, event_key2, seq2 = rows[1]
    py_end_text, py_end_hash = canon({"interrupted": False})
    check("turn/end payload == Python canonical {interrupted:false}",
          payload2 == py_end_text, payload2)
    check("turn/end event_key == Python completion_event_key",
          event_key2 == completion_event_key(s, et2, effect, 1, payload2_hash))
    with conn.cursor() as cur:
        cur.execute("SELECT v_turn_end_key(%s::uuid, %s::uuid)", (s, turn))
        sql_tek = cur.fetchone()[0]
    check("v_turn_end_key == turn_end_key_v1", sql_tek == turn_end_key_v1(s, turn))
    with conn.cursor() as cur:
        cur.execute("SELECT seq FROM session_events WHERE session_id=%s ORDER BY seq",
                    (s,))
        seqs = [row[0] for row in cur.fetchall()]
    check("seq no holes through internal events",
          seqs == list(range(1, len(seqs) + 1)) and next_seq == len(seqs) + 1,
          (seqs, next_seq))
    with conn.cursor() as cur:
        cur.execute("SELECT internal_semantic_ordinal FROM session_events"
                    " WHERE session_id=%s AND internal_semantic_ordinal IS NOT NULL"
                    " ORDER BY internal_semantic_ordinal", (s,))
        isos = [row[0] for row in cur.fetchall()]
    check("internal semantic ordinals allocated 1..n",
          isos == list(range(1, len(isos) + 1)), isos)


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def main() -> int:
    check("setup", setup_db() == 0)
    conn = psycopg2.connect(get_server().get_uri(DB))
    try:
        test_claim_and_yield(conn)
        test_yield_preserves_active_step(conn)
        test_recovery_claim(conn)
        test_null_envelope_fail_closed(conn)
        test_seal_happy(conn)
        test_seal_cas_negatives(conn)
        test_seal_command_idempotency(conn)
        test_dispatch(conn)
        test_complete_success_full_chain(conn)
        test_complete_idempotency(conn)
        test_dual_fence(conn)
        test_outcome_mismatch(conn)
        test_decision_plan_invalid(conn)
        test_final_tools_plan_persistence(conn)
        test_unknown_path(conn)
        test_classify_evidence_unit(conn)
        test_late_completion_repair_required(conn)
        test_evidence_binding_settlement(conn)
        test_claim_expected_fence_cas(conn)
        # known_cancellation settlement is G8b (v8/cancel/test_closure.py);
        # the effect-stage database stops before the shared sub-operation.
        test_pending_sibling(conn)
        test_gate_on_effect_commands(conn)
        test_cross_checks(conn)
    finally:
        conn.close()
    print("[G4] all gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
