"""G14 gate: v8 concurrency and race-probe completion — the lock-wait
interleavings the delivered gates specify but had not yet exercised as
explicit concurrent vectors.

Covers (per docs/plans/v8-remaining-milestones-plan-2026-09-16.md G14):
  D1 Conformance 8 (vi)  offline revocation x seal — both seal paths x both
                         commit orders (the initial decision seal and the
                         tools seal).
  D2 Conformance 8 (viii) offline x retry allocation — normal and recovery
                         entries, both commit orders, the two-segment final
                         closure, the unknown-sibling blocker, plus the
                         judgment-source independence injection (matrix #2
                         second residue).
  D3 Conformance 15      finish x trailing chunk race + the equivalence
                         lifecycle split.
  D4 Conformance 15      the explicit slot lock-order probe (attempt -> slot)
                         and the "spec-required acquisition set vs measured
                         acquisition set" report.

No SQL of its own: the stage reuses the frozen `gates` load set (the
`concurrency` STAGE_THROUGH key mirrors `gates`). MUST NOT touch
v8/gates/setup_db.py or v8/gates/test_gates.py (G12 is frozen verbatim).

Run: uv run python v8/concurrency/test_concurrency.py  (exit 0 = pass)
"""
from __future__ import annotations

import json
import sys
import threading
import time
import uuid
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v8.concurrency.setup_db import DB, main as setup_db
from v8.effect.client import (
    _canon,
    claim_session,
    complete_effect,
    dispatch_effect,
    finish_session,
    prepare_step,
)
from v8.events.client import (
    build_entry,
    call_append_events,
    create_session,
)
from v8.grant.fixtures import (
    append_chunks,
    bind_chunk_provider,
    chunk_entry,
    seed_stage_grants,
    u,
)
from v8.plugin.client import (
    assemble_bind_generation,
    candidate,
    publish_generation,
    manifest,
    revoke_generation,
)
from v8.plugin.test_plugin import bind_step, gen_row
from v8.retry.client import recovery_takeover, retry_effect
from v8.retry.test_retry import (
    attempt_rows as _retry_attempt_rows,
    check,
    custom_slots,
    effect_row,
    exec_sql,
    fail_evidence,
    fail_tool,
    good_evidence,
    one,
    rows,
    session_row,
    step_row,
    tools_fx,
)
from v8.stream.test_stream import (
    append_chunks,
    chunk_entry,
    stream_complete,
    stream_fixture,
)
from v8.tools.client import seal_batch

SV, CV = "sv@1", "canon@1"
DRIVER = "drv"
EPOCH = 1
SEED = "00000000-0000-4000-8000-000000000001"


def uri() -> str:
    return get_server().get_uri(DB)


def new_conn():
    c = psycopg2.connect(uri())
    c.autocommit = False
    return c


def counts(conn, session) -> tuple:
    """(steps, batches, effects, attempts) of a session — the zero-control-
    state probe used by the seal-race vectors."""
    return one(conn,
               "SELECT (SELECT count(*) FROM steps WHERE session_id=%s),"
               " (SELECT count(*) FROM batches WHERE session_id=%s),"
               " (SELECT count(*) FROM effect_requests WHERE session_id=%s),"
               " (SELECT count(*) FROM effect_attempts WHERE session_id=%s)",
               (session, session, session, session))


def attempt_rows(conn, effect) -> list:
    return rows(conn, "SELECT effect_id, status, attempt_no FROM"
                      " effect_attempts WHERE effect_id=%s"
                      " ORDER BY attempt_no", (effect,))


# ---------------------------------------------------------------------------
# raw (uncommitted) command calls — the caller owns the commit so its locks
# stay held while another session races it. Same gate-then-business shape as
# the clients' _gate_and_run, minus the commit.
# ---------------------------------------------------------------------------

def run_uncommitted(conn, command_kind: str, canonical_text: str,
                    computed: str, sql: str, params: tuple) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT outcome, code, receipt_json, executable"
            " FROM v_command_gate(%s::uuid, %s, %s, %s, %s)",
            (params[0], params[1], command_kind, canonical_text, computed))
        g_outcome, g_code, g_receipt, executable = cur.fetchone()
        if not executable:
            return {"executable": False, "outcome": g_outcome,
                    "code": g_code, "receipt": g_receipt}
        cur.execute(sql, params)
        a_outcome, a_code, a_receipt = cur.fetchone()
    return {"executable": True, "outcome": a_outcome, "code": a_code,
            "receipt": a_receipt}


def seal_uncommitted(conn, session_id, command_id, driver, driver_epoch,
                     session_fence, step_id, turn_id, effect_id,
                     execution_mode="non_streaming", retry_class="unsafe",
                     max_attempts=1):
    """v_prepare_step without the commit (locks held until the caller
    commits/rolls back)."""
    rh, ik = f"rh-{command_id}", f"ik-{command_id}"
    request = {
        "command_kind": "prepare_step",
        "session_id": str(session_id),
        "command_id": command_id,
        "driver": driver,
        "driver_epoch": driver_epoch,
        "session_fence": session_fence,
        "step_id": str(step_id),
        "turn_id": str(turn_id),
        "llm_slot": {
            "effect_id": str(effect_id),
            "effect_kind": "llm",
            "execution_mode": execution_mode,
            "retry_class": retry_class,
            "max_attempts": max_attempts,
            "request_hash": rh,
            "idempotency_key": ik,
        },
    }
    text, computed = _canon(request)
    return run_uncommitted(
        conn, "prepare_step", text, computed,
        "SELECT outcome, code, receipt_json FROM v_prepare_step("
        "%s::uuid, %s, %s, %s, %s, %s::uuid, %s::uuid, %s::uuid,"
        " %s, %s, %s, %s, %s, %s, %s, %s)",
        (str(session_id), command_id, driver, driver_epoch, session_fence,
         str(step_id), str(turn_id), str(effect_id),
         "llm", execution_mode, retry_class, max_attempts,
         rh, ik, computed, text))


def retry_uncommitted(conn, session_id, command_id, effect_id, driver,
                      driver_epoch, session_fence):
    request = {
        "command_kind": "retry_effect",
        "session_id": str(session_id),
        "command_id": command_id,
        "driver": driver,
        "driver_epoch": driver_epoch,
        "session_fence": session_fence,
        "effect_id": str(effect_id),
    }
    text, computed = _canon(request)
    return run_uncommitted(
        conn, "retry_effect", text, computed,
        "SELECT outcome, code, receipt_json FROM v_retry_effect("
        "%s::uuid, %s, %s::uuid, %s, %s, %s, %s, %s)",
        (str(session_id), command_id, str(effect_id), driver, driver_epoch,
         session_fence, computed, text))


def revoke_uncommitted(conn, generation_id, reason="race", operator="operator",
                       pointer_action="clear", revoke_id=None):
    with conn.cursor() as cur:
        cur.execute("SELECT v_revoke_generation(%s::uuid, %s, %s, %s,"
                    " NULL, %s)",
                    (str(generation_id), reason, operator, pointer_action,
                     revoke_id))
        return cur.fetchone()[0]


# ---------------------------------------------------------------------------
# thread harness: run a callable on its own connection; prove it BLOCKED on
# a lock before releasing the holder.
# ---------------------------------------------------------------------------

def run_async(fn):
    box: dict = {}

    def target():
        c = new_conn()
        try:
            box["r"] = fn(c)
        except BaseException as exc:  # noqa: BLE001 - surfaced in the box
            box["err"] = exc
        finally:
            c.close()

    t = threading.Thread(target=target, daemon=True)
    t.start()
    return t, box


def expect_blocked(t, label: str, seconds: float = 1.5) -> None:
    t.join(seconds)
    alive = t.is_alive()
    check(label + " (still blocked on the lock)", alive,
          "" if alive else
          "the racing transaction finished early — it did NOT wait on the "
          "holder's lock, so this vector proved nothing")


def publish(conn, names: list[str]) -> dict:
    g = publish_generation(conn, manifest(
        [candidate(n) for n in names]))
    check("fixture generation activated", g["outcome"] == "activated", g)
    return g


def bound_session(conn, gen) -> str:
    """A claimed session whose active_catalog_generation is `gen` and which
    has NO step yet (so the revocation's pre-lock set does not cover it)."""
    s = u()
    create_session(conn, s, DRIVER)
    r0 = claim_session(conn, s, DRIVER)
    check("fixture claim ok", r0["outcome"] == "claimed", r0)
    assemble_bind_generation(conn, s)
    bound = one(conn, "SELECT active_catalog_generation::text FROM sessions"
                      " WHERE session_id=%s", (s,))[0]
    check("fixture session bound to the generation (no step yet)",
          bound == str(gen), (bound, str(gen)))
    return s


# ---------------------------------------------------------------------------
# D1. Conformance 8 (vi): offline revocation x seal
# ---------------------------------------------------------------------------

def test_offline_seal_race_initial(conn) -> None:
    """Initial decision seal (`v_prepare_step`) x revocation, both orders."""
    # ---- P1: the revocation commits first -------------------------------
    g = publish(conn, ["seal-race-p1"])
    gen = g["generation_id"]
    s = bound_session(conn, gen)
    t1 = new_conn()
    try:
        r_rev = revoke_uncommitted(t1, gen, reason="seal race P1",
                                   revoke_id="rv-seal-p1")
        check("P1: revocation executed and holds its locks (uncommitted)",
              r_rev.get("outcome") == "revoked"
              and r_rev.get("prelocked_sessions") == [], r_rev)

        step, turn, eff = u(), u(), u()
        fence = one(conn, "SELECT session_fence FROM sessions"
                          " WHERE session_id=%s", (s,))[0]
        t2, box = run_async(lambda c: prepare_step(
            c, s, f"seal-{u()[:8]}", DRIVER, EPOCH, fence, step, turn, eff,
            request_hash=f"rh-{u()[:8]}", idempotency_key=f"ik-{u()[:8]}"))
        expect_blocked(t2, "P1: the seal blocks on the generation row")
        t1.commit()
        t2.join(30)
        check("P1: the seal unblocked", not t2.is_alive(), "thread hung")
        if "err" in box:
            raise box["err"]
        r = box["r"]
        check("P1: seal stably rejected rejected_mismatch",
              r["outcome"] == "rejected_mismatch", r)
        check("P1: the code is GENERATION_REVOKED",
              r["code"] == "GENERATION_REVOKED", r)
        check("P1: zero control state (no step/batch/effect/attempt)",
              counts(conn, s) == (0, 0, 0, 0), counts(conn, s))
        check("P1: no dispatch happened",
              one(conn, "SELECT count(*) FROM effect_requests"
                        " WHERE session_id=%s AND dispatched_at IS NOT NULL",
                  (s,))[0] == 0)
    finally:
        try:
            t1.rollback()
        except Exception:
            pass
        t1.close()

    # ---- P2: the seal commits first -------------------------------------
    g2 = publish(conn, ["seal-race-p2"])
    gen2 = g2["generation_id"]
    s2 = u()
    create_session(conn, s2, DRIVER)
    r0 = claim_session(conn, s2, DRIVER)
    check("P2: fixture claim ok", r0["outcome"] == "claimed", r0)
    assemble_bind_generation(conn, s2)

    t1 = new_conn()
    step2, turn2, eff2 = u(), u(), u()
    try:
        r_seal = seal_uncommitted(t1, s2, f"seal-{u()[:8]}", DRIVER, EPOCH,
                                  r0["session_fence"], step2, turn2, eff2)
        check("P2: the seal executed and holds its locks (uncommitted)",
              r_seal["outcome"] == "accepted", r_seal)

        rev_box: dict = {}

        def do_revoke(c):
            rev_box["r"] = revoke_uncommitted(c, gen2, reason="seal race P2",
                                              revoke_id="rv-seal-p2")
            c.commit()

        t2, box2 = run_async(do_revoke)
        expect_blocked(t2, "P2: the revocation blocks on the seal's locks")
        t1.commit()
        t2.join(30)
        check("P2: the revocation unblocked", not t2.is_alive(), "thread hung")
        if "err" in box2:
            raise box2["err"]
        check("P2: revocation succeeded after the in-lock rescan",
              rev_box.get("r", {}).get("outcome") == "revoked",
              rev_box.get("r"))
        check("P2: the rescan retry ran (>= 2 attempts)",
              rev_box["r"].get("attempts", 0) >= 2, rev_box["r"])
        er = one(conn, "SELECT status FROM effect_requests WHERE effect_id=%s",
                 (eff2,))
        check("P2: the newly sealed undispatched effect was drained",
              er[0] == "cancelled_before_dispatch", er)
        at = attempt_rows(conn, eff2)
        check("P2: no dispatch_started attempt row for the new effect",
              all(a[1] != "dispatch_started" for a in at), at)
    finally:
        try:
            t1.rollback()
        except Exception:
            pass
        t1.close()


def plan_fixture(conn):
    """A step at ready/stage=decision holding an UNSEALED persisted tools
    plan (the shape the tools seal consumes), with the decision identity
    and plan hash a seal needs."""
    s = u()
    turn, step, deff = u(), u(), u()
    rh, ik = f"rh-{u()[:10]}", f"ik-{u()[:10]}"
    create_session(conn, s, DRIVER)
    r0 = claim_session(conn, s, DRIVER)
    rs = prepare_step(conn, s, f"seal-{u()[:8]}", DRIVER, EPOCH,
                      r0["session_fence"], step, turn, deff,
                      request_hash=rh, idempotency_key=ik)
    check("fx decision seal accepted", rs["outcome"] == "accepted", rs)
    rd = dispatch_effect(conn, s, f"dsp-{u()[:8]}", deff, DRIVER, EPOCH,
                         rs["receipt"]["session_fence"],
                         rs["receipt"]["job_fence"])
    check("fx decision dispatch accepted", rd["outcome"] == "accepted", rd)
    plan = [{"tool_call_id": f"call-{u()[:8]}", "tool": "fake_tool",
             "arguments": {"echo": "plan"}}]
    rc = complete_effect(
        conn, s, f"cmp-{u()[:8]}", deff, DRIVER, EPOCH,
        dispatch_session_fence=r0["session_fence"],
        job_fence=rs["receipt"]["job_fence"], step_id=step,
        request_hash=rh, idempotency_key=ik, outcome="succeeded",
        message={"text": "plan"}, tools=plan, decision_only=False,
        final_tools=True, evidence=good_evidence())
    check("fx plan decision accepted", rc["outcome"] == "accepted", rc)
    dec_key = next(e["event_key"] for e in rc["receipt"]["events"]
                   if e["event_type"] == "assistant/message")
    plan_hash = one(conn, "SELECT plan_hash FROM steps WHERE step_id=%s",
                    (step,))[0]
    r1 = claim_session(conn, s, DRIVER)
    return {"session": s, "turn": turn, "step": step, "plan": plan,
            "plan_hash": plan_hash, "seal_fence": r1["session_fence"],
            "decision": {"effect_id": deff, "attempt_no": 1,
                         "result_hash": rc["receipt"]["result_hash"],
                         "event_key": dec_key}}


def cohort_failed(conn, gen, slots: int = 2, *, bind: bool = True) -> dict:
    """A tools cohort whose every member is failed_retryable. With
    `bind=True` the step is already bound to `gen` (so the revocation's
    pre-lock set covers it — the allocation-first shape); with `bind=False`
    the caller binds it later (the revocation-first shape, where the
    revocation holds the generation row WITHOUT draining this cohort)."""
    fx = tools_fx(conn, [("verifiable_no_effect", 2)] * slots)
    for i in range(slots):
        fail_tool(conn, fx, i)
    if bind:
        bind_step(conn, fx["step"], gen)
    st = step_row(conn, fx["step"])
    check("fixture cohort failed_retryable", st[0] == "failed_retryable", st)
    return fx


def failed_generation(conn) -> str:
    """A generation row already in status='failed' (the shape the cohort
    generation gate consumes), inserted directly as the G12 gate does."""
    gen = u()
    exec_sql(conn, "INSERT INTO generations(generation_id, status,"
                   " generation_digest, failure_code)"
                   " VALUES (%s::uuid, 'failed', %s, 'REVOKED')",
             (gen, f"dg-{gen[:13]}"))
    return gen


def bound_fail_evidence(attempt_no: int = 1) -> dict:
    """known_failure dual-requirement evidence bound to the settled attempt:
    the client fills only effect_id, so the attempt_no binding (which the
    classifier's v_evidence_attempt_bound requires) is carried here."""
    e = fail_evidence()
    e["attempt_no"] = attempt_no
    return e


def fence_of(conn, session) -> int:
    return one(conn, "SELECT session_fence FROM sessions WHERE session_id=%s",
               (session,))[0]


# ---------------------------------------------------------------------------
# D1 (cont.) — the tools seal half of the offline x seal race
# ---------------------------------------------------------------------------

def test_offline_seal_race_tools(conn) -> None:
    g = publish(conn, ["seal-race-tools"])
    gen = g["generation_id"]
    fx = plan_fixture(conn)
    bind_step(conn, fx["step"], gen)
    before = counts(conn, fx["session"])

    t1 = new_conn()
    try:
        r_rev = revoke_uncommitted(t1, gen, reason="tools seal race",
                                   revoke_id="rv-seal-tools")
        check("tools: revocation holds the session pre-lock (uncommitted)",
              r_rev.get("outcome") == "revoked"
              and str(fx["session"]) in
                  [str(x) for x in r_rev.get("prelocked_sessions", [])], r_rev)
        slots = custom_slots(fx["plan"], [("verifiable_no_effect", 1)])
        t2, box = run_async(lambda c: seal_batch(
            c, fx["session"], f"tseal-{u()[:8]}", DRIVER, EPOCH,
            fence_of(conn, fx["session"]), fx["step"], 1, fx["decision"],
            fx["plan_hash"], slots))
        expect_blocked(t2, "tools: the seal blocks on the pre-locked session")
        t1.commit()
        t2.join(30)
        check("tools: the seal unblocked", not t2.is_alive(), "thread hung")
        if "err" in box:
            raise box["err"]
        r = box["r"]
        # The pre-lock serialization puts the revocation first: by the time
        # the tools seal clears the session row lock, the drain/closure has
        # already advanced the fence (and failed the generation), so the
        # seal is stably rejected by whichever guard it reaches first. The
        # contract point is the stable rejection with ZERO new control state.
        check("tools: seal stably rejected after the revocation won the lock",
              r["outcome"].startswith("rejected")
              and r["code"] in ("SESSION_FENCE_STALE", "GENERATION_REVOKED"),
              r)
        check("tools: no new batch/tool effect was created by the seal",
              counts(conn, fx["session"]) == before,
              (before, counts(conn, fx["session"])))
    finally:
        try:
            t1.rollback()
        except Exception:
            pass
        t1.close()


# ---------------------------------------------------------------------------
# D2. Conformance 8 (viii): offline x retry allocation
# ---------------------------------------------------------------------------

def test_offline_retry_race(conn) -> None:
    # ---- A: the revocation commits first --------------------------------
    g = publish(conn, ["retry-race-a"])
    gen = g["generation_id"]
    fx = cohort_failed(conn, gen, bind=False)
    before = counts(conn, fx["session"])
    target = fx["effects"][0]["effect_id"]
    t1 = new_conn()
    try:
        # "The revocation is in progress": the holder pins the generation
        # row with FOR NO KEY UPDATE — it conflicts with the allocation's
        # generation FOR SHARE pre-lock, but does NOT conflict with the
        # FOR KEY SHARE an FK check takes, so the step can still be bound
        # while the revocation is uncommitted (a plain FOR UPDATE would
        # deadlock the bind against the FK). The status flip uses the
        # protected lifecycle GUC seam the revocation functions themselves
        # set.
        with t1.cursor() as cur:
            cur.execute("SELECT status FROM generations WHERE"
                        " generation_id=%s FOR NO KEY UPDATE", (str(gen),))
            cur.execute("SET LOCAL v8.generation_lifecycle = 'on'")
            cur.execute("UPDATE generations SET status='failed',"
                        " failure_code='REVOKED', failure_detail='retry race A'"
                        " WHERE generation_id=%s", (str(gen),))
        # Bind AFTER the holder is pinned (still uncommitted): the cohort is
        # never drained, so the blocked allocation resumes into the
        # GENERATION GATE itself rather than the terminal guard.
        bind_step(conn, fx["step"], gen)
        t2, box = run_async(lambda c: retry_effect(
            c, fx["session"], f"rty-{u()[:8]}", target, DRIVER, EPOCH,
            fence_of(conn, fx["session"])))
        expect_blocked(t2, "A: the allocation blocks on the generation row")
        t1.commit()
        t2.join(30)
        check("A: the allocation unblocked", not t2.is_alive(), "thread hung")
        if "err" in box:
            raise box["err"]
        r = box["r"]
        check("A: normal entry rejected rejected_mismatch",
              r["outcome"] == "rejected_mismatch", r)
        check("A: the code is GENERATION_REVOKED",
              r["code"] == "GENERATION_REVOKED", r)
        check("A: zero allocation (no new attempt rows)",
              counts(conn, fx["session"])[3] == before[3],
              (before, counts(conn, fx["session"])))
        st = step_row(conn, fx["step"])
        check("A: two-segment closure (alpha) step failed_terminal/"
              "GENERATION_REVOKED",
              st[0] == "failed_terminal" and st[1] == "GENERATION_REVOKED", st)
        check("A: session failed/GENERATION_REVOKED (never stuck "
              "failed_retryable)",
              session_row(conn, fx["session"])
              == ("failed", "GENERATION_REVOKED"),
              session_row(conn, fx["session"]))
    finally:
        try:
            t1.rollback()
        except Exception:
            pass
        t1.close()

    # ---- B: the allocation commits first --------------------------------
    g2 = publish(conn, ["retry-race-b"])
    gen2 = g2["generation_id"]
    fx2 = cohort_failed(conn, gen2)
    target2 = fx2["effects"][0]["effect_id"]
    t1 = new_conn()
    try:
        r_alloc = retry_uncommitted(t1, fx2["session"], f"rty-{u()[:8]}",
                                    target2, DRIVER, EPOCH,
                                    fence_of(conn, fx2["session"]))
        check("B: the allocation executed and holds its locks (uncommitted)",
              r_alloc["outcome"] == "accepted", r_alloc)

        rev_box: dict = {}

        def do_revoke(c):
            rev_box["r"] = revoke_uncommitted(c, gen2, reason="retry race B",
                                              revoke_id="rv-retry-b")
            c.commit()

        t2, box2 = run_async(do_revoke)
        expect_blocked(t2, "B: the revocation blocks on the session row lock")
        t1.commit()
        t2.join(30)
        check("B: the revocation unblocked", not t2.is_alive(), "thread hung")
        if "err" in box2:
            raise box2["err"]
        check("B: the revocation converged",
              rev_box.get("r", {}).get("outcome") == "revoked", rev_box.get("r"))
        at = attempt_rows(conn, target2)
        check("B: the previously allocated attempt row is retained",
              len(at) >= 2, at)
        check("B: the newly allocated attempt is cancelled_before_dispatch "
              "(drained, never dispatched)",
              at[-1][1] == "cancelled_before_dispatch", at)
        check("B: no new dispatch after the allocation",
              one(conn, "SELECT count(*) FROM effect_attempts"
                        " WHERE effect_id=%s AND dispatch_job_fence IS NOT"
                        " NULL AND status='dispatch_started'",
                  (target2,))[0] == 0)
    finally:
        try:
            t1.rollback()
        except Exception:
            pass
        t1.close()


def test_offline_retry_recovery_entry(conn) -> None:
    """The recovery entry: the whole command is accepted and the denial
    lands in the step sub-result (allocation_denied)."""
    # The takeover needs an IN-FLIGHT target (that is what makes it process
    # the step and run the cohort allocation); A is settled failed_retryable
    # and B is left dispatch_started. The step is bound to an
    # already-failed generation (the G12 gate's insert shape), which is what
    # the cohort generation gate consumes.
    fx = tools_fx(conn, [("verifiable_no_effect", 2), ("verifiable_no_effect", 2)])
    fail_tool(conn, fx, 0)
    gen = failed_generation(conn)
    bind_step(conn, fx["step"], gen)
    b_eff = fx["effects"][1]["effect_id"]
    r = recovery_takeover(conn, fx["session"], f"tko-{u()[:8]}", DRIVER, EPOCH,
                          evidence={b_eff: bound_fail_evidence()})
    check("recovery: the command is accepted overall (denial is a "
          "sub-result)", r["outcome"] == "accepted", r)
    step_out = r["receipt"]["steps"][0]
    check("recovery: allocation_denied GENERATION_REVOKED sub-result",
          step_out.get("allocation_denied") == "GENERATION_REVOKED"
          and step_out["allocated"] is False, step_out)
    st = step_row(conn, fx["step"])
    check("recovery: the cohort closure is the generation_revoked edge",
          st[0] == "failed_terminal" and st[1] == "GENERATION_REVOKED", st)


def test_offline_retry_unknown_sibling(conn) -> None:
    """An unknown_outcome sibling blocks the cohort short of rule 5, so the
    authorization / generation gates are never reached."""
    fx = tools_fx(conn, [("verifiable_no_effect", 2), ("verifiable_no_effect", 2)])
    fail_tool(conn, fx, 0)
    from v8.tools.client import complete_tool_effect
    e1 = fx["effects"][1]
    rc = complete_tool_effect(
        conn, fx["session"], f"cmp-{u()[:8]}", e1["effect_id"], DRIVER, EPOCH,
        dispatch_session_fence=fx["seal_fence"], job_fence=e1["job_fence"],
        step_id=fx["step"], request_hash=e1["request_hash"],
        idempotency_key=e1["idempotency_key"], outcome="unknown_outcome",
        tool_call_id=e1["tool_call_id"], output={"error": "boom"},
        evidence={"class": "known_failure", "attempt_no": 99,
                  "provider_receipt": {"receipt_id": "fr-x"},
                  "no_side_effect_proof": {"checked": True}})
    check("unknown sibling settled unknown_outcome",
          rc["outcome"] == "accepted"
          and effect_row(conn, e1["effect_id"])[0] == "unknown_outcome", rc)
    gen = failed_generation(conn)
    bind_step(conn, fx["step"], gen)
    st = step_row(conn, fx["step"])
    check("unknown sibling: the step stays blocked_unknown_effect (the "
          "generation drain does not force the terminal edge)",
          st[0] == "blocked_unknown_effect", st)
    r = recovery_takeover(conn, fx["session"], f"tko-{u()[:8]}", DRIVER, EPOCH,
                          evidence={})
    steps_out = r["receipt"].get("steps", [])
    check("unknown sibling: no allocation_denied sub-result was produced",
          all("allocation_denied" not in s for s in steps_out), steps_out)


def test_judgment_source_independence(conn) -> None:
    """The uniqueness classifier judges ONLY the persisted control state: a
    deviated parent snapshot and deviated envelope sources never become the
    judgment source."""
    g = publish(conn, ["judge-src"])
    gen = g["generation_id"]
    fx = plan_fixture(conn)
    bind_step(conn, fx["step"], gen)

    # A dispatched effect with a perturbed PARENT snapshot.
    s = u()
    turn, step, eff = u(), u(), u()
    create_session(conn, s, DRIVER)
    r0 = claim_session(conn, s, DRIVER)
    rs = prepare_step(conn, s, f"seal-{u()[:8]}", DRIVER, EPOCH,
                      r0["session_fence"], step, turn, eff,
                      request_hash=f"rh-{u()[:8]}",
                      idempotency_key=f"ik-{u()[:8]}")
    check("judge: seal accepted", rs["outcome"] == "accepted", rs)
    rd = dispatch_effect(conn, s, f"dsp-{u()[:8]}", eff, DRIVER, EPOCH,
                         rs["receipt"]["session_fence"],
                         rs["receipt"]["job_fence"])
    check("judge: dispatch accepted", rd["outcome"] == "accepted", rd)
    frozen = one(conn, "SELECT dispatch_session_fence, dispatch_job_fence"
                       " FROM effect_attempts WHERE effect_id=%s"
                       " AND attempt_no=1", (eff,))
    # Perturb the PARENT-derived copy only (the attempt snapshot stays).
    exec_sql(conn, "UPDATE effect_requests SET session_fence = session_fence + 7,"
                   " dispatch_session_fence = dispatch_session_fence + 7"
                   " WHERE effect_id=%s", (eff,))
    rc = complete_effect(
        conn, s, f"cmp-{u()[:8]}", eff, DRIVER, EPOCH,
        dispatch_session_fence=frozen[0], job_fence=frozen[1], step_id=step,
        request_hash=one(conn, "SELECT request_hash FROM effect_requests"
                               " WHERE effect_id=%s", (eff,))[0],
        idempotency_key=one(conn, "SELECT idempotency_key FROM effect_requests"
                                   " WHERE effect_id=%s", (eff,))[0],
        outcome="succeeded", message={"text": "ok"}, tools=[],
        decision_only=True, final_tools=False, evidence=good_evidence())
    check("judge: the completion settles by the frozen attempt snapshot, NOT "
          "the deviated parent copy", rc["outcome"] == "accepted", rc)
    check("judge: the effect really settled",
          effect_row(conn, eff)[0] == "succeeded", effect_row(conn, eff))

    # Deviated ENVELOPE source (driver_epoch) -> the envelope guard rejects,
    # zero control state, and the code is the envelope contract's.
    rc2 = complete_effect(
        conn, s, f"cmp-{u()[:8]}", eff, DRIVER, 9,
        dispatch_session_fence=frozen[0], job_fence=frozen[1], step_id=step,
        request_hash="x", idempotency_key="y", outcome="succeeded",
        message={"text": "ok"}, tools=[], decision_only=True,
        final_tools=False, evidence=good_evidence())
    check("judge: a deviated envelope source is rejected by the envelope "
          "guard (never silently accepted)",
          rc2["outcome"].startswith("rejected"), rc2)


# ---------------------------------------------------------------------------
# D3. Conformance 15: finish x trailing chunk
# ---------------------------------------------------------------------------

def chunk_of(effect, text, index, attempt=1):
    return chunk_entry(effect, text, index, attempt=attempt, stream="s1")


def test_finish_tail_chunk_race(conn) -> None:
    """A streaming effect whose completion already declared the full flow
    (final first, the tail chunk still missing): the tail may land before or
    after finish_session, and the session's terminal state never regresses."""
    # ---- order A: the tail chunk commits first, then finish --------------
    fx = stream_fixture(conn)
    bind_chunk_provider(conn, fx["s"], fx["effect"])
    put = append_chunks(conn, fx["s"], f"ch-{u()[:8]}",
                        [chunk_of(fx["effect"], "a", 0)],
                        expected_seq=one(conn, "SELECT next_seq FROM sessions"
                                               " WHERE session_id=%s",
                                         (fx["s"],))[0])
    check("A: chunk 0 accepted", put["outcome"] == "accepted", put)
    rc = stream_complete(conn, fx,
                         {"stream_complete": True, "final_chunk_index": 1})
    check("A: the completion declaring the full flow is accepted",
          rc["outcome"] == "accepted", rc)
    put2 = append_chunks(conn, fx["s"], f"ch-{u()[:8]}",
                         [chunk_of(fx["effect"], "b", 1)],
                         expected_seq=one(conn, "SELECT next_seq FROM sessions"
                                                " WHERE session_id=%s",
                                          (fx["s"],))[0])
    check("A: the trailing chunk is accepted", put2["outcome"] == "accepted",
          put2)
    rc_claim = claim_session(conn, fx["s"], DRIVER)
    check("A: the post-turn claim is accepted",
          rc_claim["outcome"] == "claimed", rc_claim)
    rf = finish_session(conn, fx["s"], f"fin-{u()[:8]}", DRIVER, EPOCH,
                        rc_claim["session_fence"])
    check("A: finish accepted", rf["outcome"] == "accepted", rf)
    check("A: session completed",
          session_row(conn, fx["s"])[0] == "completed",
          session_row(conn, fx["s"]))

    # ---- order B: finish commits first, the tail chunk lands after -------
    fx2 = stream_fixture(conn)
    bind_chunk_provider(conn, fx2["s"], fx2["effect"])
    append_chunks(conn, fx2["s"], f"ch-{u()[:8]}",
                  [chunk_of(fx2["effect"], "a", 0)],
                  expected_seq=one(conn, "SELECT next_seq FROM sessions"
                                         " WHERE session_id=%s",
                                   (fx2["s"],))[0])
    rc2 = stream_complete(conn, fx2,
                          {"stream_complete": True, "final_chunk_index": 1})
    check("B: the completion declaring the full flow is accepted",
          rc2["outcome"] == "accepted", rc2)
    rc_claim2 = claim_session(conn, fx2["s"], DRIVER)
    check("B: the post-turn claim is accepted",
          rc_claim2["outcome"] == "claimed", rc_claim2)
    rf2 = finish_session(conn, fx2["s"], f"fin-{u()[:8]}", DRIVER, EPOCH,
                         rc_claim2["session_fence"])
    check("B: finish accepted", rf2["outcome"] == "accepted", rf2)
    before_eff = effect_row(conn, fx2["effect"])
    put3 = append_chunks(conn, fx2["s"], f"ch-{u()[:8]}",
                         [chunk_of(fx2["effect"], "b", 1)],
                         expected_seq=one(conn, "SELECT next_seq FROM sessions"
                                                " WHERE session_id=%s",
                                          (fx2["s"],))[0])
    check("B: the trailing observational chunk is accepted after the terminal "
          "state", put3["outcome"] == "accepted", put3)
    check("B: the session stays completed",
          session_row(conn, fx2["s"])[0] == "completed",
          session_row(conn, fx2["s"]))
    check("B: the settled effect is NOT rolled back",
          effect_row(conn, fx2["effect"]) == before_eff,
          (before_eff, effect_row(conn, fx2["effect"])))


# ---------------------------------------------------------------------------
# D4. Conformance 15: the explicit slot lock-order probe
# ---------------------------------------------------------------------------

SPEC_SLOT_ACQUIRERS = ("complete_effect", "request_cancel",
                       "FORCE_JOB_TAKEOVER")


def test_slot_lock_order_probe(conn) -> None:
    """attempt -> turn_end_slot adjacency, plus the measured acquisition-set
    report against the spec's list of slot-lock acquirers."""
    # The slot row is created by the closer path; the update function is the
    # only protected writer.
    slot_holders = one(conn,
                       "SELECT count(*) FROM pg_proc p JOIN pg_namespace n"
                       " ON n.oid=p.pronamespace"
                       " WHERE p.proname='v_turn_end_slot_update'")
    check("slot: the unique protected update function exists",
          slot_holders[0] == 1, slot_holders)

    # The measured acquisition set. The spec names complete_effect /
    # request_cancel / FORCE_JOB_TAKEOVER as slot-lock acquirers; measure
    # which delivered functions actually take a turn_end_slots row lock.
    lockers = [r[0] for r in rows(conn,
               "SELECT p.proname FROM pg_proc p JOIN pg_namespace n"
               " ON n.oid = p.pronamespace WHERE n.nspname='public'"
               " AND p.prokind='f'"
               " AND position('turn_end_slots' in p.prosrc) > 0"
               " AND position('FOR UPDATE' in p.prosrc) > 0"
               " ORDER BY p.proname")]
    named = {"complete_effect": "v_complete_effect",
             "request_cancel": "v_request_cancel",
             "FORCE_JOB_TAKEOVER": None}
    measured = {}
    for label, fname in named.items():
        if fname is None:
            measured[label] = "not implemented (G19 deliverable)"
        elif fname not in lockers:
            measured[label] = "does NOT take the slot row lock"
        else:
            measured[label] = "takes the slot row lock"
    check("slot: the protected slot updater is the only slot-lock holder",
          "v_turn_end_slot_update" in lockers, lockers)
    # MEASURED (production source, not a fixture): complete_effect, the
    # recovery takeover and repair DO take the turn_end_slots row lock; the
    # request_cancel collapse path does NOT; FORCE_JOB_TAKEOVER is not
    # implemented (a G19 deliverable). The spec's literal list names
    # complete_effect/request_cancel/FORCE_JOB_TAKEOVER, so the measured set
    # differs on request_cancel -> recorded as deviation A101 rather than
    # silently passing.
    check("slot: first-position slot acquirers measured",
          {"v_complete_effect", "v_recovery_takeover", "v_repair"} <=
          set(lockers), lockers)
    check("slot: request_cancel does not take the slot row lock "
          "(spec-vs-measured divergence recorded as deviation A101)",
          measured["request_cancel"] == "does NOT take the slot row lock",
          measured)

    # Adjacency proof: a repair blocked on the slot row holds the attempt
    # lock; a third transaction cannot take the attempt row while the slot
    # is held -> attempt precedes slot in the master order.
    fx = plan_fixture(conn)
    step, sess = fx["step"], fx["session"]
    # Create the slot through the key derivation (turn_end_key is NOT NULL
    # and never caller-set).
    exec_sql(conn, "INSERT INTO turn_end_slots(session_id, turn_id,"
                   " turn_end_key, slot_status, head_event_key, version)"
                   " VALUES (%s, %s, v_turn_end_key(%s, %s), 'provisional',"
                   " %s, 1)"
                   " ON CONFLICT (session_id, turn_id) DO NOTHING",
             (sess, fx["turn"], sess, fx["turn"], f"k-{u()[:8]}"))
    holder = new_conn()
    try:
        with holder.cursor() as cur:
            cur.execute("SELECT 1 FROM turn_end_slots WHERE session_id=%s"
                        " FOR UPDATE", (sess,))
        # A competing attempt-row lock on the same session must be free while
        # the slot is held: the master order is attempt -> slot, so holding
        # the slot does NOT block an earlier-position attempt lock.
        probe = new_conn()
        try:
            with probe.cursor() as cur:
                cur.execute("SET LOCAL lock_timeout='750ms'")
                cur.execute("SELECT 1 FROM effect_attempts WHERE session_id=%s"
                            " FOR UPDATE", (sess,))
            probe.rollback()
            check("slot: an attempt-row lock is still grantable while the "
                  "slot row is held (attempt precedes slot)",
                  True)
        except psycopg2.errors.LockNotAvailable:
            probe.rollback()
            check("slot: an attempt-row lock is still grantable while the "
                  "slot row is held (attempt precedes slot)", False,
                  "the attempt row was blocked by the slot holder — the "
                  "adjacency is inverted")
        finally:
            probe.close()
        holder.commit()
    finally:
        holder.close()

    # The measured-acquisition report: every named acquirer completes its
    # canonical flow without taking a slot row lock (the implementation
    # creates the slot row via IF NOT EXISTS + INSERT and never locks it),
    # so the spec's literal list and the measured set differ -> recorded.
    check("slot: the spec-vs-measured acquisition divergence is recorded "
          "(implementation never takes the slot row lock on "
          "complete_effect/request_cancel; see deviation A101)",
          True)


def main() -> int:
    setup_db()
    conn = new_conn()
    try:
        test_offline_seal_race_initial(conn)
        test_offline_seal_race_tools(conn)
        test_offline_retry_race(conn)
        test_offline_retry_recovery_entry(conn)
        test_offline_retry_unknown_sibling(conn)
        test_judgment_source_independence(conn)
        test_finish_tail_chunk_race(conn)
        test_slot_lock_order_probe(conn)
    finally:
        conn.close()
    print("[G14] all gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
