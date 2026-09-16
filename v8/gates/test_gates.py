"""G12 gate: v8 two real-time authorization gates + cohort replacement.

Covers (plan G12 row, contract MUSTs):
- first gate (seal authorization stage) on both seal paths: prepare_step
  and seal_batch — per-member authorize_effect + effect_submit grants with
  concrete params, zero-creation GRANT_DENIED, same-command replay,
  re-issue + new command_id acceptance, generation check GENERATION_REVOKED;
- second gate (dispatch revalidation): unbound effect, revoke-after-seal,
  dispatch-then-revoke two-commit order, generation read-only rejection,
  two-gate independence;
- cohort authorization/generation checks (the replaced always-pass steps):
  normal-entry GRANT_DENIED zero control state (ready + claimed initial
  conditions), slice-revoked variant, recovery-entry allocation_denied
  sub-results (grant + generation), pass-through superseded_by control,
  mixed-entry full-prelock coverage (lock-wait form);
- recovery takeover ISOLATION_UNSUPPORTED entry guard (Conformance 8 (x));
- A39 closure: WORKSPACE_LOST drain -> terminal recovery claim -> late
  completion -> terminal repair -> repeat-drain convergence.

Run: uv run python v8/gates/test_gates.py  (exit 0 = pass)
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
from v8.effect.client import (
    claim_session,
    complete_effect,
    dispatch_effect,
    prepare_step,
    recovery_claim_session,
)
from v8.events.client import (
    build_entry,
    call_append_events,
    create_session,
)
from v8.gates.setup_db import DB, main as setup_db
from v8.grant.fixtures import (
    append_chunks,
    chunk_entry,
    seed_grant,
    seed_slice,
    seed_stage_grants,
    u,
)
from v8.repair.client import repair
from v8.retry.client import recovery_takeover, retry_effect
from v8.tools.client import build_tool_slots, complete_tool_effect, seal_batch

SV, CV = "sv@1", "canon@1"
EPOCH = 1
SEED_GEN = "00000000-0000-4000-8000-000000000001"


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f": {detail}" if detail else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def _uri() -> str:
    return get_server().get_uri(DB)


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


def fail_evidence(attempt_no: int = 1) -> dict:
    return {"class": "known_failure",
            "attempt_no": attempt_no,
            "provider_receipt": {"receipt_id": f"fr-{u()[:8]}"},
            "no_side_effect_proof": {"checked": True}}


def revoke_grant(conn, grant_id: str) -> None:
    one(conn, "SELECT v_operator_revoke_grant('g12-test', %s, 'g12 vector')",
        (grant_id,))


def revoke_slice(conn, slice_id: str) -> None:
    one(conn, "SELECT v_operator_revoke_slice('g12-test', %s::uuid,"
              " 'g12 vector')", (slice_id,))


def insert_generation(conn, gen: str, status: str) -> None:
    exec_sql(conn,
             "INSERT INTO generations(generation_id, status,"
             " generation_digest, failure_code)"
             " VALUES (%s::uuid, %s, %s, %s)",
             (gen, status, f"dg-{gen[:13]}",
              'FATAL_DEFECT' if status == 'failed' else None))


def fail_generation(conn, gen: str) -> None:
    """Direct status flip through the protected-lifecycle GUC (test seam —
    the offline drain is NOT run: the gate vectors need a failed generation
    without the drain's pre-dispatch cancellation)."""
    with conn.cursor() as cur:
        cur.execute("SET LOCAL v8.generation_lifecycle='on'")
        cur.execute("UPDATE generations SET status='failed',"
                    " failure_code='FATAL_DEFECT'"
                    " WHERE generation_id=%s::uuid", (gen,))
    conn.commit()


def grant_of(conn, effect) -> str:
    return one(conn, "SELECT grant_id FROM effect_requests"
                     " WHERE effect_id=%s", (effect,))[0]


def slice_of(conn, grant_id: str) -> str:
    return str(one(conn, "SELECT slice_id FROM grants WHERE grant_id=%s",
                   (grant_id,))[0])


def counts(conn, session) -> tuple:
    return one(conn,
               "SELECT (SELECT count(*) FROM steps WHERE session_id=%s),"
               " (SELECT count(*) FROM batches WHERE session_id=%s),"
               " (SELECT count(*) FROM effect_requests WHERE session_id=%s),"
               " (SELECT count(*) FROM effect_attempts WHERE session_id=%s)",
               (session, session, session, session))


def seal_fx(conn, driver: str, *, max_attempts: int = 2,
            retry_class: str = "verifiable_no_effect"):
    """create -> claim -> initial decision seal. Returns the fixture dict
    with the post-claim and post-seal fences for the follow-up commands."""
    s = u()
    turn, step, eff = u(), u(), u()
    rh, ik = f"rh-{u()[:10]}", f"ik-{u()[:10]}"
    create_session(conn, s, driver)
    r0 = claim_session(conn, s, driver)
    check("fx claim ok", r0["outcome"] == "claimed", r0)
    rs = prepare_step(conn, s, f"seal-{u()[:8]}", driver, EPOCH,
                      r0["session_fence"], step, turn, eff,
                      request_hash=rh, idempotency_key=ik,
                      retry_class=retry_class, max_attempts=max_attempts)
    check("fx decision seal accepted", rs["outcome"] == "accepted", rs)
    return {"session": s, "turn": turn, "step": step, "effect": eff,
            "rh": rh, "ik": ik, "claim_fence": r0["session_fence"],
            "seal_fence": rs["receipt"]["session_fence"],
            "job_fence": rs["receipt"]["job_fence"]}


def failed_batch_fx(conn, driver: str):
    """seal -> dispatch -> complete known_failure: effect + step
    failed_retryable (rule 5 batch), session ready."""
    fx = seal_fx(conn, driver, max_attempts=2)
    rd = dispatch_effect(conn, fx["session"], f"dsp-{u()[:8]}",
                         fx["effect"], driver, EPOCH, fx["seal_fence"],
                         fx["job_fence"])
    check("fx dispatch accepted", rd["outcome"] == "accepted", rd)
    rc = complete_effect(
        conn, fx["session"], f"cmp-{u()[:8]}", fx["effect"], driver, EPOCH,
        dispatch_session_fence=fx["claim_fence"], job_fence=fx["job_fence"],
        step_id=fx["step"], request_hash=fx["rh"], idempotency_key=fx["ik"],
        outcome="failed_retryable", message={"text": "boom"}, tools=[],
        decision_only=True, final_tools=False, evidence=fail_evidence())
    check("fx known_failure settlement accepted", rc["outcome"] == "accepted",
          rc)
    st = one(conn, "SELECT status FROM steps WHERE step_id=%s", (fx["step"],))
    check("fx step failed_retryable", st[0] == "failed_retryable", st)
    fx["fence"] = one(conn, "SELECT session_fence FROM sessions"
                            " WHERE session_id=%s", (fx["session"],))[0]
    return fx


def tools_fx(conn, driver: str, *, slot_attempts: int = 1):
    """Full decision flow ending in a tools-sealable step
    (ready, stage=decision, final_tools=true) with a two-slot plan."""
    s = u()
    turn = u()
    create_session(conn, s, driver)
    r_app = call_append_events(conn, s, f"usr-{u()[:8]}", driver, EPOCH, 1, [
        build_entry("turn/start", {"reason": "user_message"},
                    schema_version=SV, canonicalizer_version=CV,
                    turn_id=turn, semantic_input_ordinal=1),
        build_entry("user/message", {"text": "tools please"},
                    schema_version=SV, canonicalizer_version=CV,
                    turn_id=turn, semantic_input_ordinal=2),
    ])
    check("fx append accepted", r_app["outcome"] == "accepted", r_app)
    step, eff = u(), u()
    rh, ik = f"rh-{u()[:10]}", f"ik-{u()[:10]}"
    plan = [
        {"tool_call_id": f"call-{u()[:8]}-0", "tool": "fake_tool",
         "arguments": {"echo": "a"}},
        {"tool_call_id": f"call-{u()[:8]}-1", "tool": "fake_tool",
         "arguments": {"echo": "b"}},
    ]
    r0 = claim_session(conn, s, driver)
    rs = prepare_step(conn, s, f"seal-{u()[:8]}", driver, EPOCH,
                      r0["session_fence"], step, turn, eff,
                      request_hash=rh, idempotency_key=ik)
    check("fx decision seal accepted", rs["outcome"] == "accepted", rs)
    rd = dispatch_effect(conn, s, f"dsp-{u()[:8]}", eff, driver, EPOCH,
                         rs["receipt"]["session_fence"],
                         rs["receipt"]["job_fence"])
    check("fx dispatch accepted", rd["outcome"] == "accepted", rd)
    rc = complete_effect(
        conn, s, f"cmp-{u()[:8]}", eff, driver, EPOCH,
        dispatch_session_fence=r0["session_fence"],
        job_fence=rs["receipt"]["job_fence"], step_id=step,
        request_hash=rh, idempotency_key=ik, outcome="succeeded",
        message={"text": "plan"}, tools=plan, decision_only=False,
        final_tools=True, evidence=good_evidence())
    check("fx decision complete accepted", rc["outcome"] == "accepted", rc)
    dec_key = next(e["event_key"] for e in rc["receipt"]["events"]
                   if e["event_type"] == "assistant/message")
    step_row = one(conn, "SELECT plan_hash FROM steps WHERE step_id=%s",
                   (step,))
    r1 = claim_session(conn, s, driver)
    check("fx re-claim ok", r1["outcome"] == "claimed", r1)
    return {"session": s, "turn": turn, "step": step, "effect": eff,
            "rh": rh, "ik": ik, "plan": plan, "plan_hash": step_row[0],
            "decision": {"effect_id": eff, "attempt_no": 1,
                         "result_hash": rc["receipt"]["result_hash"],
                         "event_key": dec_key},
            "claim_fence": r1["session_fence"],
            "slot_attempts": slot_attempts}


# ---------------------------------------------------------------------------
# 1. first gate: initial decision seal (prepare_step)
# ---------------------------------------------------------------------------

def test_seal_gate_prepare_step(conn) -> None:
    # (a) no grants at all -> GRANT_DENIED, zero creation (Conformance 14
    # seal negative: no step member/LLM slot/batch/first attempt/seal
    # receipt; only binding + rejection receipt persist).
    s, turn, step, eff = u(), u(), u(), u()
    create_session(conn, s, "g12-none")
    r0 = claim_session(conn, s, "g12-none")
    r = prepare_step(conn, s, "seal-neg1", "g12-none", EPOCH,
                     r0["session_fence"], step, turn, eff)
    check("seal: no grants -> GRANT_DENIED",
          r["outcome"] == "rejected_mismatch" and r["code"] == "GRANT_DENIED",
          r)
    check("seal denial: zero creation (no step/batch/effect/attempt)",
          counts(conn, s) == (0, 0, 0, 0), counts(conn, s))
    n_rec = one(conn, "SELECT count(*), count(*) FILTER (WHERE outcome"
                      " <> 'rejected_mismatch') FROM command_receipts"
                      " WHERE session_id=%s", (s,))
    check("seal denial: exactly the rejection receipt persists",
          n_rec == (1, 0), n_rec)

    # same command_id replay -> the SAME rejection receipt (idempotent).
    r2 = prepare_step(conn, s, "seal-neg1", "g12-none", EPOCH,
                      r0["session_fence"], step, turn, eff)
    check("seal denial replay: same command_id returns the same rejection",
          r2["outcome"] == "rejected_mismatch"
          and r2["code"] == "GRANT_DENIED", r2)
    check("seal denial replay: still zero creation",
          counts(conn, s) == (0, 0, 0, 0), counts(conn, s))

    # (b) authorize_effect only -> the effect_submit half still denies.
    seed_stage_grants(conn, drivers=("g12-half",),
                      capabilities=("authorize_effect",))
    s2 = u()
    create_session(conn, s2, "g12-half")
    r0b = claim_session(conn, s2, "g12-half")
    rb = prepare_step(conn, s2, f"seal-{u()[:8]}", "g12-half", EPOCH,
                      r0b["session_fence"], u(), u(), u())
    check("seal: authorize_effect only -> GRANT_DENIED (submit half)",
          rb["code"] == "GRANT_DENIED"
          and "effect_submit" in rb["receipt"]["detail"], rb["receipt"])

    # (c) revoke before seal -> denied; authorization restored -> a NEW
    # command_id seals (Conformance 14: manifest snapshot never exempts;
    # re-issued grant is a new grant_id).
    drv = "g12-rv1"
    seed_stage_grants(conn, drivers=(drv,))
    s3, turn3, step3, eff3 = u(), u(), u(), u()
    create_session(conn, s3, drv)
    r0c = claim_session(conn, s3, drv)
    revoke_grant(conn, f"g-stage-{drv}-effect_submit")
    rc1 = prepare_step(conn, s3, "seal-rv1", drv, EPOCH,
                       r0c["session_fence"], step3, turn3, eff3)
    check("seal: revoke-before-seal -> GRANT_DENIED (snapshot no exempt)",
          rc1["code"] == "GRANT_DENIED", rc1)
    check("seal revoke denial: zero creation", counts(conn, s3) == (0, 0, 0, 0),
          counts(conn, s3))
    seed_grant(conn, f"g-{drv}-submit-2", one(conn,
               "SELECT workspace_id FROM grants WHERE grant_id=%s",
               (f"g-stage-{drv}-effect_submit",))[0],
               slice_of(conn, f"g-stage-{drv}-effect_submit"),
               "driver", drv, "effect_submit")
    rc2 = prepare_step(conn, s3, "seal-rv2", drv, EPOCH,
                       r0c["session_fence"], step3, turn3, eff3)
    check("seal: authorization restored -> new command_id seals",
          rc2["outcome"] == "accepted", rc2)
    check("seal: restored seal froze the NEW grant onto the effect",
          grant_of(conn, eff3) == f"g-{drv}-submit-2",
          grant_of(conn, eff3))

    # (d) slice-membership / constrained slice negative: the grant's slice
    # resource set does not contain the seal target (Conformance 14 (iii)).
    drv = "g12-mem"
    s4 = u()
    create_session(conn, s4, drv)
    ws4 = one(conn, "SELECT workspace_id FROM grants WHERE grant_id=%s",
              ("g-stage-drv-effect_submit",))[0]
    sl4 = seed_slice(conn, str(ws4), f"mem-{u()[:8]}", kind="tool_set",
                     spec={"resources": {"tool:unrelated": True}})
    seed_grant(conn, f"g-{drv}-auth", str(ws4), sl4, "driver", drv,
               "authorize_effect")
    seed_grant(conn, f"g-{drv}-sub", str(ws4), sl4, "driver", drv,
               "effect_submit")
    r0d = claim_session(conn, s4, drv)
    rd4 = prepare_step(conn, s4, f"seal-{u()[:8]}", drv, EPOCH,
                       r0d["session_fence"], u(), u(), u())
    check("seal: target outside slice.spec -> GRANT_DENIED (membership)",
          rd4["code"] == "GRANT_DENIED", rd4)


def test_seal_gate_generation(conn) -> None:
    # generation failed before the seal -> GENERATION_REVOKED, zero
    # creation (Conformance 8 (vi), prepare_step half).
    drv = "g12-gen"
    seed_stage_grants(conn, drivers=(drv,))
    gen = u()
    insert_generation(conn, gen, "failed")
    s, turn, step, eff = u(), u(), u(), u()
    create_session(conn, s, drv)
    r0 = claim_session(conn, s, drv)
    exec_sql(conn, "UPDATE sessions SET active_catalog_generation=%s::uuid"
                   " WHERE session_id=%s", (gen, s))
    r = prepare_step(conn, s, f"seal-{u()[:8]}", drv, EPOCH,
                     r0["session_fence"], step, turn, eff)
    check("seal: bound generation failed -> GENERATION_REVOKED",
          r["outcome"] == "rejected_mismatch"
          and r["code"] == "GENERATION_REVOKED", r)
    check("seal generation denial: zero creation",
          counts(conn, s) == (0, 0, 0, 0), counts(conn, s))
    # retired passes (no revocation semantics).
    gen2 = u()
    insert_generation(conn, gen2, "retired")
    s2 = u()
    create_session(conn, s2, drv)
    r0b = claim_session(conn, s2, drv)
    exec_sql(conn, "UPDATE sessions SET active_catalog_generation=%s::uuid"
                   " WHERE session_id=%s", (gen2, s2))
    r2 = prepare_step(conn, s2, f"seal-{u()[:8]}", drv, EPOCH,
                      r0b["session_fence"], u(), u(), u())
    check("seal: retired generation passes", r2["outcome"] == "accepted", r2)


# ---------------------------------------------------------------------------
# 2. first gate: tools seal (seal_batch)
# ---------------------------------------------------------------------------

def test_seal_gate_tools(conn) -> None:
    drv = "g12-tools"
    seed_stage_grants(conn, drivers=(drv,))
    fx = tools_fx(conn, drv)
    before = counts(conn, fx["session"])
    revoke_grant(conn, f"g-stage-{drv}-effect_submit")
    slots = build_tool_slots(fx["plan"], max_attempts=fx["slot_attempts"])
    r = seal_batch(conn, fx["session"], "tseal-neg1", drv, EPOCH,
                   fx["claim_fence"], fx["step"], 1, fx["decision"],
                   fx["plan_hash"], slots)
    check("tools seal: revoked member grant -> GRANT_DENIED",
          r["outcome"] == "rejected_mismatch" and r["code"] == "GRANT_DENIED",
          r)
    check("tools seal denial: zero creation (no batch/effect/attempt)",
          counts(conn, fx["session"]) == before,
          (counts(conn, fx["session"]), before))
    st = one(conn, "SELECT status, stage, sealed_batch_no FROM steps"
                   " WHERE step_id=%s", (fx["step"],))
    check("tools seal denial: step stays ready/decision",
          st == ("ready", "decision", 1), st)

    # restore -> new command_id seals.
    ws = one(conn, "SELECT workspace_id FROM grants WHERE grant_id=%s",
             (f"g-stage-{drv}-effect_submit",))[0]
    seed_grant(conn, f"g-{drv}-submit-2", ws,
               slice_of(conn, f"g-stage-{drv}-effect_submit"),
               "driver", drv, "effect_submit")
    r2 = seal_batch(conn, fx["session"], "tseal-ok2", drv, EPOCH,
                    fx["claim_fence"], fx["step"], 1, fx["decision"],
                    fx["plan_hash"], slots)
    check("tools seal: authorization restored -> new command_id seals",
          r2["outcome"] == "accepted", r2)
    g0 = one(conn, "SELECT grant_id FROM effect_requests WHERE batch_id=%s"
                   " ORDER BY dispatch_ordinal LIMIT 1",
             (r2["receipt"]["batch_id"],))
    check("tools seal: members froze the re-issued grant",
          g0[0] == f"g-{drv}-submit-2", g0)

    # generation failed -> GENERATION_REVOKED (Conformance 8 (vi),
    # seal_batch half).
    fx2 = tools_fx(conn, drv)
    gen = u()
    insert_generation(conn, gen, "failed")
    exec_sql(conn, "UPDATE steps SET catalog_generation=%s::uuid"
                   " WHERE step_id=%s", (gen, fx2["step"]))
    r3 = seal_batch(conn, fx2["session"], f"tseal-{u()[:8]}", drv, EPOCH,
                    fx2["claim_fence"], fx2["step"], 1, fx2["decision"],
                    fx2["plan_hash"],
                    build_tool_slots(fx2["plan"],
                                     max_attempts=fx2["slot_attempts"]))
    check("tools seal: generation failed -> GENERATION_REVOKED",
          r3["outcome"] == "rejected_mismatch"
          and r3["code"] == "GENERATION_REVOKED", r3)
    check("tools seal generation denial: zero creation",
          counts(conn, fx2["session"]) == counts(conn, fx2["session"])
          and one(conn, "SELECT count(*) FROM batches WHERE session_id=%s",
                  (fx2["session"],))[0] == 1, "only the decision batch")


# ---------------------------------------------------------------------------
# 3. second gate: dispatch revalidation
# ---------------------------------------------------------------------------

def test_dispatch_gate(conn) -> None:
    # Each sub-case gets its own driver + slice + grant: seed_stage_grants
    # shares ONE slice per call and names grants per driver, so a revocation
    # in sub-case (b)/(c)/(e) would otherwise leak into the later sub-cases.
    drv_a, drv_b, drv_c, drv_d, drv_e = (
        "g12-dsp-a", "g12-dsp-b", "g12-dsp-c", "g12-dsp-d", "g12-dsp-e")
    for d in (drv_a, drv_b, drv_c, drv_d, drv_e):
        seed_stage_grants(conn, drivers=(d,))
    drv = drv_a

    # (a) unbound effect (grant_id NULL) -> GRANT_DENIED read-only
    # (Conformance 14: no grant -> denied, never dispatch_started).
    fx = seal_fx(conn, drv)
    exec_sql(conn, "UPDATE effect_requests SET grant_id=NULL,"
                   " authz_params=NULL WHERE effect_id=%s", (fx["effect"],))
    r = dispatch_effect(conn, fx["session"], f"dsp-{u()[:8]}", fx["effect"],
                        drv, EPOCH, fx["seal_fence"], fx["job_fence"])
    check("dispatch: unbound effect -> GRANT_DENIED",
          r["outcome"] == "rejected_mismatch" and r["code"] == "GRANT_DENIED",
          r)
    row = one(conn, "SELECT er.status, at.status, er.dispatched_at,"
                    " er.dispatch_count FROM effect_requests er"
                    " JOIN effect_attempts at ON at.effect_id=er.effect_id"
                    " AND at.attempt_no=1 WHERE er.effect_id=%s",
              (fx["effect"],))
    check("dispatch denial read-only: effect+attempt stay ready",
          row == ("ready", "ready", None, 0), row)

    # (b) revoke after seal -> dispatch GRANT_DENIED; seal pass never
    # exempts the dispatch gate (two-gate independence sequence 1).
    fx2 = seal_fx(conn, drv_b)
    g2 = grant_of(conn, fx2["effect"])
    revoke_grant(conn, g2)
    r2 = dispatch_effect(conn, fx2["session"], f"dsp-{u()[:8]}",
                         fx2["effect"], drv_b, EPOCH, fx2["seal_fence"],
                         fx2["job_fence"])
    check("dispatch: revoke-after-seal -> GRANT_DENIED (gate independence)",
          r2["outcome"] == "rejected_mismatch"
          and r2["code"] == "GRANT_DENIED", r2)
    row = one(conn, "SELECT status FROM effect_requests WHERE effect_id=%s",
              (fx2["effect"],))
    check("dispatch denial: effect stays ready", row[0] == "ready", row)

    # (c) dispatch first, revoke after -> the valid dispatch stands; the
    # revocation MUST NOT retro-cancel the dispatched attempt; completion
    # settles normally (two-commit order, Conformance 14).
    fx3 = seal_fx(conn, drv_c)
    g3 = grant_of(conn, fx3["effect"])
    r3 = dispatch_effect(conn, fx3["session"], f"dsp-{u()[:8]}",
                         fx3["effect"], drv_c, EPOCH, fx3["seal_fence"],
                         fx3["job_fence"])
    check("dispatch-then-revoke: dispatch accepted", r3["outcome"] == "accepted",
          r3)
    revoke_grant(conn, g3)
    rc3 = complete_effect(
        conn, fx3["session"], f"cmp-{u()[:8]}", fx3["effect"], drv_c, EPOCH,
        dispatch_session_fence=fx3["claim_fence"], job_fence=fx3["job_fence"],
        step_id=fx3["step"], request_hash=fx3["rh"], idempotency_key=fx3["ik"],
        outcome="succeeded", message={"text": "ok"}, tools=[],
        decision_only=True, final_tools=False, evidence=good_evidence())
    check("dispatch-then-revoke: completion settles (no retro-cancel)",
          rc3["outcome"] == "accepted", rc3)
    row = one(conn, "SELECT status FROM effect_requests WHERE effect_id=%s",
              (fx3["effect"],))
    check("dispatch-then-revoke: effect succeeded", row[0] == "succeeded", row)

    # (d) generation failed -> read-only GENERATION_REVOKED (dispatch half
    # of the §4 third gate); the effect stays ready.
    fx4 = seal_fx(conn, drv_d)
    gen = u()
    insert_generation(conn, gen, "active")
    exec_sql(conn, "UPDATE steps SET catalog_generation=%s::uuid"
                   " WHERE step_id=%s", (gen, fx4["step"]))
    fail_generation(conn, gen)
    r4 = dispatch_effect(conn, fx4["session"], f"dsp-{u()[:8]}",
                         fx4["effect"], drv_d, EPOCH, fx4["seal_fence"],
                         fx4["job_fence"])
    check("dispatch: generation failed -> GENERATION_REVOKED",
          r4["outcome"] == "rejected_mismatch"
          and r4["code"] == "GENERATION_REVOKED", r4)
    row = one(conn, "SELECT er.status, er.dispatched_at FROM effect_requests"
                    " er WHERE er.effect_id=%s", (fx4["effect"],))
    check("dispatch generation denial read-only: effect stays ready",
          row == ("ready", None), row)

    # (e) slice revoked (grant itself unrevoked) -> GRANT_DENIED
    # (Conformance 14 (ii)).
    fx5 = seal_fx(conn, drv_e)
    revoke_slice(conn, slice_of(conn, grant_of(conn, fx5["effect"])))
    r5 = dispatch_effect(conn, fx5["session"], f"dsp-{u()[:8]}",
                         fx5["effect"], drv_e, EPOCH, fx5["seal_fence"],
                         fx5["job_fence"])
    check("dispatch: slice revoked -> GRANT_DENIED",
          r5["code"] == "GRANT_DENIED", r5)


# ---------------------------------------------------------------------------
# 4. cohort authorization check (normal entry)
# ---------------------------------------------------------------------------

def test_cohort_grant_denied(conn) -> None:
    # (a) ready-state entry: zero control state on denial (session ready
    # unchanged, cohort keeps failed_retryable, no new attempt).
    drv = "g12-c1"
    seed_stage_grants(conn, drivers=(drv,))
    fx = failed_batch_fx(conn, drv)
    g = grant_of(conn, fx["effect"])
    revoke_grant(conn, g)
    r = retry_effect(conn, fx["session"], f"rty-{u()[:8]}", fx["effect"],
                     drv, EPOCH, fx["fence"])
    check("cohort: grant revoked -> retry_effect GRANT_DENIED",
          r["outcome"] == "rejected_mismatch" and r["code"] == "GRANT_DENIED",
          r)
    row = one(conn, "SELECT s.state, s.session_fence, s.lease_owner,"
                    " st.status, er.status,"
                    " (SELECT count(*) FROM effect_attempts a"
                    "   WHERE a.effect_id=er.effect_id)"
                    " FROM sessions s, steps st, effect_requests er"
                    " WHERE s.session_id=%s AND st.step_id=%s"
                    " AND er.effect_id=%s",
              (fx["session"], fx["step"], fx["effect"]))
    check("cohort denial (ready entry): zero control state — session ready,"
          " fence unchanged, cohort failed_retryable, no new attempt",
          row == ("ready", fx["fence"], None, "failed_retryable",
                  "failed_retryable", 1), row)

    # (b) claimed-state entry: lease kept, fence not bumped.
    drv2 = "g12-c2"
    seed_stage_grants(conn, drivers=(drv2,))
    fx2 = failed_batch_fx(conn, drv2)
    rc2 = claim_session(conn, fx2["session"], drv2)
    check("cohort: claim ok", rc2["outcome"] == "claimed", rc2)
    lease_before = one(conn, "SELECT lease_owner, session_fence FROM sessions"
                             " WHERE session_id=%s", (fx2["session"],))
    revoke_grant(conn, grant_of(conn, fx2["effect"]))
    r2 = retry_effect(conn, fx2["session"], f"rty-{u()[:8]}", fx2["effect"],
                      drv2, EPOCH, rc2["session_fence"])
    check("cohort denial (claimed entry): GRANT_DENIED",
          r2["code"] == "GRANT_DENIED", r2)
    lease_after = one(conn, "SELECT lease_owner, session_fence, state"
                            " FROM sessions WHERE session_id=%s",
                      (fx2["session"],))
    check("cohort denial (claimed entry): lease kept, fence unchanged,"
          " session stays claimed",
          lease_after == (lease_before[0], lease_before[1], "claimed"),
          (lease_before, lease_after))

    # (c) slice revoked (grant unrevoked) -> GRANT_DENIED.
    drv3 = "g12-c3"
    seed_stage_grants(conn, drivers=(drv3,))
    fx3 = failed_batch_fx(conn, drv3)
    revoke_slice(conn, slice_of(conn, grant_of(conn, fx3["effect"])))
    r3 = retry_effect(conn, fx3["session"], f"rty-{u()[:8]}", fx3["effect"],
                      drv3, EPOCH, fx3["fence"])
    check("cohort: slice revoked -> GRANT_DENIED",
          r3["code"] == "GRANT_DENIED", r3)


def test_cohort_generation(conn) -> None:
    # step bound to a failed generation -> zero-allocation GENERATION_REVOKED
    # + the post-denial final aggregation (three-conjunction closure:
    # residual failed_retryable -> failed_terminal keeping the original
    # code + RETRY_STOPPED_BY_CLOSURE audit; step/session failed).
    drv = "g12-cg"
    seed_stage_grants(conn, drivers=(drv,))
    fx = failed_batch_fx(conn, drv)
    gen = u()
    insert_generation(conn, gen, "failed")
    exec_sql(conn, "UPDATE steps SET catalog_generation=%s::uuid"
                   " WHERE step_id=%s", (gen, fx["step"]))
    r = retry_effect(conn, fx["session"], f"rty-{u()[:8]}", fx["effect"],
                     drv, EPOCH, fx["fence"])
    check("cohort: generation failed -> GENERATION_REVOKED",
          r["outcome"] == "rejected_mismatch"
          and r["code"] == "GENERATION_REVOKED", r)
    row = one(conn, "SELECT er.status, st.status, st.outcome_code,"
                    " s.state, s.failure_code,"
                    " (SELECT count(*) FROM effect_attempts a"
                    "   WHERE a.effect_id=er.effect_id)"
                    " FROM effect_requests er, steps st, sessions s"
                    " WHERE er.effect_id=%s AND st.step_id=%s"
                    " AND s.session_id=%s",
              (fx["effect"], fx["step"], fx["session"]))
    check("cohort generation closure: controlled edge + step/session"
          " GENERATION_REVOKED, no new attempt",
          row == ("failed_terminal", "failed_terminal", "GENERATION_REVOKED",
                  "failed", "GENERATION_REVOKED", 1), row)
    aud = one(conn, "SELECT reason FROM effect_audit WHERE effect_id=%s"
                    " ORDER BY audit_id DESC LIMIT 1", (fx["effect"],))
    check("cohort generation closure: RETRY_STOPPED_BY_CLOSURE audit",
          aud[0] == "RETRY_STOPPED_BY_CLOSURE", aud)


# ---------------------------------------------------------------------------
# 5. cohort gates at the recovery entry (two-entry contract)
# ---------------------------------------------------------------------------

def takeover_batch_fx(conn, drv: str):
    """One batch, two tool effects: A settled failed_retryable by a normal
    completion (grant GA), B in-flight dispatch_started (grant GB)."""
    fx = tools_fx(conn, drv)
    slots = build_tool_slots(fx["plan"], retry_class="verifiable_no_effect",
                             max_attempts=2)
    rs = seal_batch(conn, fx["session"], f"tseal-{u()[:8]}", drv, EPOCH,
                    fx["claim_fence"], fx["step"], 1, fx["decision"],
                    fx["plan_hash"], slots)
    check("fx tools seal accepted", rs["outcome"] == "accepted", rs)
    ga, gb = f"GA-{u()[:6]}", f"GB-{u()[:6]}"
    ws = one(conn, "SELECT workspace_id FROM grants WHERE grant_id=%s",
             (f"g-stage-{drv}-effect_submit",))[0]
    sl = slice_of(conn, f"g-stage-{drv}-effect_submit")
    seed_grant(conn, ga, ws, sl, "driver", drv, "effect_submit")
    seed_grant(conn, gb, ws, sl, "driver", drv, "effect_submit")
    effs = rows(conn, "SELECT effect_id FROM effect_requests"
                      " WHERE batch_id=%s ORDER BY dispatch_ordinal",
                (rs["receipt"]["batch_id"],))
    a_eff, b_eff = str(effs[0][0]), str(effs[1][0])
    exec_sql(conn, "UPDATE effect_requests SET grant_id=%s WHERE effect_id=%s",
             (ga, a_eff))
    exec_sql(conn, "UPDATE effect_requests SET grant_id=%s WHERE effect_id=%s",
             (gb, b_eff))
    # dispatch both, then settle A failed_retryable by a normal completion.
    fence = one(conn, "SELECT session_fence FROM sessions WHERE session_id=%s",
                (fx["session"],))[0]
    jf = {e["effect_id"]: e["job_fence"] for e in rs["receipt"]["effects"]}
    for e in (a_eff, b_eff):
        rd = dispatch_effect(conn, fx["session"], f"dsp-{u()[:8]}", e, drv,
                             EPOCH, fence, jf[e])
        check("fx tool dispatch accepted", rd["outcome"] == "accepted", rd)
    slot_a = slots[0]
    rc = complete_tool_effect(
        conn, fx["session"], f"cmp-{u()[:8]}", a_eff, drv, EPOCH,
        dispatch_session_fence=fx["claim_fence"], job_fence=jf[a_eff],
        step_id=fx["step"], request_hash=slot_a["request_hash"],
        idempotency_key=slot_a["idempotency_key"],
        outcome="failed_retryable", tool_call_id=slot_a["tool_call_id"],
        output={"error": "boom"}, evidence=fail_evidence())
    check("fx A settled failed_retryable", rc["outcome"] == "accepted", rc)
    st = one(conn, "SELECT status FROM effect_requests WHERE effect_id=%s",
             (a_eff,))
    check("fx A failed_retryable", st[0] == "failed_retryable", st)
    return {"session": fx["session"], "step": fx["step"],
            "a": a_eff, "b": b_eff, "ga": ga, "gb": gb, "jf": jf,
            "fence": fence}


def test_cohort_recovery_grant(conn) -> None:
    drv = "g12-rec"
    seed_stage_grants(conn, drivers=(drv,))
    fx = takeover_batch_fx(conn, drv)
    revoke_grant(conn, fx["ga"])
    cmd = f"tko-{u()[:8]}"
    ev = {fx["b"]: fail_evidence()}
    r = recovery_takeover(conn, fx["session"], cmd, drv, EPOCH, evidence=ev)
    check("recovery: command accepted overall (denial is a sub-result)",
          r["outcome"] == "accepted", r)
    step_out = r["receipt"]["steps"][0]
    check("recovery: allocation_denied GRANT_DENIED sub-result",
          step_out.get("allocation_denied") == "GRANT_DENIED"
          and step_out["allocated"] is False, step_out)
    b_out = next(a for a in r["receipt"]["attempts"]
                 if a["effect_id"] == fx["b"])
    check("recovery: B settled failed_retryable and NOT rolled back",
          b_out["disposition"] == "taken_over"
          and b_out["settled_status"] == "failed_retryable", b_out)
    row = one(conn, "SELECT (SELECT count(*) FROM effect_attempts"
                    "  WHERE effect_id=%s), (SELECT count(*) FROM"
                    " effect_attempts WHERE effect_id=%s),"
                    " (SELECT status FROM effect_requests"
                    "  WHERE effect_id=%s),"
                    " (SELECT status FROM steps WHERE step_id=%s),"
                    " (SELECT state FROM sessions WHERE session_id=%s)",
              (fx["a"], fx["b"], fx["a"], fx["step"], fx["session"]))
    check("recovery denial: zero allocation (no attempt_no increments),"
          " cohort failed_retryable, final aggregation session ready",
          row == (1, 1, "failed_retryable", "failed_retryable", "ready"), row)

    # idempotent replay returns the original accepted receipt incl. the
    # sub-result.
    r2 = recovery_takeover(conn, fx["session"], cmd, drv, EPOCH,
                           evidence={k: dict(v) for k, v in ev.items()})
    check("recovery denial replay: original receipt with the sub-result",
          r2["outcome"] == "accepted"
          and r2["receipt"]["steps"][0].get("allocation_denied")
          == "GRANT_DENIED", r2)

    # pass-through control (two-entry superseded_by consistency): the same
    # shape without any revocation allocates and writes superseded_by on
    # BOTH entries' old attempts (the normal-entry half is the G7a gate).
    fx2 = takeover_batch_fx(conn, drv)
    r3 = recovery_takeover(conn, fx2["session"], f"tko-{u()[:8]}", drv,
                           EPOCH, evidence={fx2["b"]: fail_evidence()})
    step3 = r3["receipt"]["steps"][0]
    check("recovery pass-through: allocation succeeds with valid grants",
          step3.get("allocated") is True, step3)
    sup = rows(conn, "SELECT a.effect_id, a.superseded_by_attempt_no"
                     " FROM effect_attempts a WHERE a.effect_id IN (%s, %s)"
                     " AND a.attempt_no = 1 ORDER BY a.effect_id",
               (fx2["a"], fx2["b"]))
    check("recovery pass-through: both old attempts superseded_by written",
          len(sup) == 2 and all(x[1] == 2 for x in sup), sup)


def test_cohort_recovery_generation(conn) -> None:
    drv = "g12-reg"
    seed_stage_grants(conn, drivers=(drv,))
    fx = takeover_batch_fx(conn, drv)
    gen = u()
    insert_generation(conn, gen, "failed")
    exec_sql(conn, "UPDATE steps SET catalog_generation=%s::uuid"
                   " WHERE step_id=%s", (gen, fx["step"]))
    r = recovery_takeover(conn, fx["session"], f"tko-{u()[:8]}", drv, EPOCH,
                          evidence={fx["b"]: fail_evidence()})
    check("recovery generation: command accepted overall",
          r["outcome"] == "accepted", r)
    step_out = r["receipt"]["steps"][0]
    check("recovery generation: allocation_denied GENERATION_REVOKED"
          " sub-result",
          step_out.get("allocation_denied") == "GENERATION_REVOKED",
          step_out)
    row = one(conn, "SELECT status, outcome_code FROM steps"
                    " WHERE step_id=%s", (fx["step"],))
    check("recovery generation: post-denial closure fired"
          " (three-conjunction)",
          row == ("failed_terminal", "GENERATION_REVOKED"), row)


def test_takeover_prelock_lockwait(conn) -> None:
    # Mixed-entry full-prelock coverage (Conformance 14, lock-wait form):
    # A's grant GA is NOT a takeover target's grant — the takeover's step-1
    # prelock set MUST still cover it. Hold GA's row lock in the main
    # transaction, start the takeover in a thread (it blocks on GA),
    # revoke GA, commit — the takeover unblocks and its cohort check
    # detects the revocation inside the complete lock set: no allocation,
    # B's settlement stands.
    drv = "g12-lw"
    seed_stage_grants(conn, drivers=(drv,))
    fx = takeover_batch_fx(conn, drv)

    holder = psycopg2.connect(_uri())
    try:
        with holder.cursor() as cur:
            cur.execute("SELECT 1 FROM grants WHERE grant_id=%s FOR UPDATE",
                        (fx["ga"],))
        result: dict = {}

        def run_takeover():
            c2 = psycopg2.connect(_uri())
            try:
                result["r"] = recovery_takeover(
                    c2, fx["session"], f"tko-{u()[:8]}", drv, EPOCH,
                    evidence={fx["b"]: fail_evidence()})
            finally:
                c2.close()

        t = threading.Thread(target=run_takeover)
        t.start()
        time.sleep(0.8)  # the takeover is blocked on GA's row lock
        alive_before_revoke = t.is_alive()
        # Test-only revocation vector: the holder already owns GA's row lock,
        # so flip revoked_at directly. Going through v_operator_revoke_grant
        # here would take the slice lock BEFORE the grant lock (the operator
        # function's fixed slice->grant order), which inverts against the
        # holder's pre-acquired grant lock and self-deadlocks the vector; the
        # operator's slice->grant ordering is exercised by the other revoke
        # vectors and MUST match the prelock order, so the deadlock is a
        # test-harness artifact, not an implementation defect.
        exec_sql(holder, "UPDATE grants SET revoked_at = now()"
                         " WHERE grant_id = %s", (fx["ga"],))
        holder.commit()
        t.join(timeout=30)
        check("prelock: the takeover blocked on the non-target sibling's"
              " grant (GA covered by the step-1 prelock set)",
              alive_before_revoke, "takeover did not wait on GA")
        check("prelock: thread completed", not t.is_alive(), "thread hung")
        r = result["r"]
        step_out = r["receipt"]["steps"][0]
        check("prelock: cohort check inside the complete lock set detects"
              " the concurrent revocation -> no allocation",
              step_out.get("allocation_denied") == "GRANT_DENIED", step_out)
        row = one(conn, "SELECT count(*) FROM effect_attempts"
                        " WHERE effect_id=%s", (fx["b"],))
        check("prelock: B settlement stands (no rollback, no new attempt)",
              row[0] == 1, row)
    finally:
        holder.close()


def test_takeover_isolation(conn) -> None:
    drv = "g12-iso"
    seed_stage_grants(conn, drivers=(drv,))
    fx = takeover_batch_fx(conn, drv)
    c2 = psycopg2.connect(_uri())
    c2.set_isolation_level(
        psycopg2.extensions.ISOLATION_LEVEL_REPEATABLE_READ)
    try:
        r = recovery_takeover(c2, fx["session"], f"tko-{u()[:8]}", drv,
                              EPOCH, evidence={fx["b"]: fail_evidence()})
        check("takeover: REPEATABLE READ -> ISOLATION_UNSUPPORTED"
              " (Conformance 8 (x))",
              r["outcome"] == "rejected_mismatch"
              and r["code"] == "ISOLATION_UNSUPPORTED", r)
    finally:
        c2.close()


# ---------------------------------------------------------------------------
# 6. A39 closure: WORKSPACE_LOST terminal recovery claim / repair
# ---------------------------------------------------------------------------

def test_workspace_lost_a39(conn) -> None:
    drv = "g12-wl"
    seed_stage_grants(conn, drivers=(drv,))
    # One step, two tool effects: e1 in-flight (dispatch_started), e2
    # unknown_outcome (unbound evidence). Tools batch with max_attempts=1
    # so the repaired failure is terminal.
    fx = tools_fx(conn, drv)
    slots = build_tool_slots(fx["plan"], max_attempts=1)
    rs = seal_batch(conn, fx["session"], f"tseal-{u()[:8]}", drv, EPOCH,
                    fx["claim_fence"], fx["step"], 1, fx["decision"],
                    fx["plan_hash"], slots)
    check("fx tools seal accepted", rs["outcome"] == "accepted", rs)
    effs = rows(conn, "SELECT effect_id FROM effect_requests"
                      " WHERE batch_id=%s ORDER BY dispatch_ordinal",
                (rs["receipt"]["batch_id"],))
    e1, e2 = str(effs[0][0]), str(effs[1][0])
    jf = {e["effect_id"]: e["job_fence"] for e in rs["receipt"]["effects"]}
    fence = one(conn, "SELECT session_fence FROM sessions"
                      " WHERE session_id=%s", (fx["session"],))[0]
    for e in (e1, e2):
        rd = dispatch_effect(conn, fx["session"], f"dsp-{u()[:8]}", e, drv,
                             EPOCH, fence, jf[e])
        check("fx tool dispatch accepted", rd["outcome"] == "accepted", rd)
    # e2 -> unknown_outcome (unbound evidence classifies unknown).
    rc2 = complete_tool_effect(
        conn, fx["session"], f"cmp-{u()[:8]}", e2, drv, EPOCH,
        dispatch_session_fence=fx["claim_fence"], job_fence=jf[e2],
        step_id=fx["step"], request_hash=slots[1]["request_hash"],
        idempotency_key=slots[1]["idempotency_key"],
        outcome="unknown_outcome", tool_call_id=slots[1]["tool_call_id"],
        output={"error": "boom"},
        evidence={"class": "known_failure",
                  "attempt_no": 99,
                  "provider_receipt": {"receipt_id": "fr-x"},
                  "no_side_effect_proof": {"checked": True}})
    check("fx e2 settled unknown_outcome",
          one(conn, "SELECT status FROM effect_requests WHERE effect_id=%s",
              (e2,))[0] == "unknown_outcome", rc2)

    # WORKSPACE_LOST drain -> session failed, step stays blocked (unknown),
    # drain_step_id points at the non-terminal step.
    r = one(conn, "SELECT v_workspace_fail_closed(%s::uuid, 'run-a39',"
                  " 'g12')", (fx["session"],))[0]
    check("drain: accepted, session failed/WORKSPACE_LOST",
          r["outcome"] == "accepted" and r["failure_code"] == "WORKSPACE_LOST",
          r)
    row = one(conn, "SELECT state, failure_code, drain_step_id FROM sessions"
                    " WHERE session_id=%s", (fx["session"],))
    check("drain: terminal failed + drain_step_id at the blocked step",
          row == ("failed", "WORKSPACE_LOST", fx["step"]), row)

    # A39 (i): recovery claim on the drain-terminal session (closure only).
    rc = recovery_claim_session(conn, fx["session"], drv, lease_owner="rec")
    check("A39: recovery claim on drain-terminal session allowed",
          rc["outcome"] == "claimed", rc)
    row = one(conn, "SELECT state, failure_code FROM sessions"
                    " WHERE session_id=%s", (fx["session"],))
    check("A39: the claim changes no business state",
          row == ("failed", "WORKSPACE_LOST"), row)

    # A39 (ii): the late completion settles the in-flight effect; the
    # terminal session state is NEVER overwritten.
    rc1 = complete_tool_effect(
        conn, fx["session"], f"cmp-{u()[:8]}", e1, drv, EPOCH,
        dispatch_session_fence=fx["claim_fence"], job_fence=jf[e1],
        step_id=fx["step"], request_hash=slots[0]["request_hash"],
        idempotency_key=slots[0]["idempotency_key"], outcome="succeeded",
        tool_call_id=slots[0]["tool_call_id"], output={"echo": "ok"},
        evidence=good_evidence())
    check("A39: late completion on terminal session accepted",
          rc1["outcome"] == "accepted", rc1)
    row = one(conn, "SELECT er.status, s.state, s.failure_code"
                    " FROM effect_requests er, sessions s"
                    " WHERE er.effect_id=%s AND s.session_id=%s",
              (e1, fx["session"]))
    check("A39: effect settled succeeded, session stays failed/WL",
          row == ("succeeded", "failed", "WORKSPACE_LOST"), row)

    # A39 (iii): terminal-session repair closes the unknown effect (budget
    # exhausted -> failed_terminal); the step terminalizes, the session
    # terminal state is preserved.
    slot = one(conn, "SELECT head_event_key FROM turn_end_slots"
                     " WHERE session_id=%s", (fx["session"],))
    rpr = repair(conn, fx["session"], f"rpr-{u()[:8]}", e2, 1,
                 driver=drv, driver_epoch=EPOCH,
                 supersedes_event_key=slot[0], evidence=fail_evidence(),
                 resolution_kind="failed_terminal",
                 tool_call_id=slots[1]["tool_call_id"],
                 output={"error": "boom"})
    check("A39: terminal-session repair accepted",
          rpr["outcome"] == "accepted", rpr)
    row = one(conn, "SELECT er.status, st.status, s.state, s.failure_code"
                    " FROM effect_requests er, steps st, sessions s"
                    " WHERE er.effect_id=%s AND st.step_id=%s"
                    " AND s.session_id=%s",
              (e2, fx["step"], fx["session"]))
    check("A39: repair closed effect+step, session stays failed/WL",
          row == ("failed_terminal", "failed_terminal", "failed",
                  "WORKSPACE_LOST"), row)

    # repeat drain: the same judgment converges — drain_step_id cleared,
    # no second workspace/lost event, no second fence bump.
    fence_before = one(conn, "SELECT session_fence FROM sessions"
                             " WHERE session_id=%s", (fx["session"],))[0]
    r2 = one(conn, "SELECT v_workspace_fail_closed(%s::uuid, 'run-a39',"
                   " 'g12')", (fx["session"],))[0]
    row = one(conn, "SELECT drain_step_id, session_fence,"
                    " (SELECT count(*) FROM session_events"
                    "  WHERE session_id=%s AND event_type='workspace/lost')"
                    " FROM sessions WHERE session_id=%s",
              (fx["session"], fx["session"]))
    check("A39: repeat drain converges — drain_step_id cleared, one event,"
          " fence stable",
          row == (None, fence_before, 1), (row, r2))

    # negative: a completed session stays rejected for recovery claim.
    s2 = u()
    create_session(conn, s2, drv)
    exec_sql(conn, "UPDATE sessions SET state='completed'"
                   " WHERE session_id=%s", (s2,))
    rn = recovery_claim_session(conn, s2, drv, lease_owner="rec")
    check("A39: completed session still SESSION_TERMINAL for recovery"
          " claim", rn["code"] == "SESSION_TERMINAL", rn)
    # negative: repair on a completed session is rejected.
    rnx = repair(conn, s2, f"rpr-{u()[:8]}", u(), 1,
                 driver=drv, driver_epoch=EPOCH,
                 supersedes_event_key="k", evidence=good_evidence(),
                 resolution_kind="succeeded")
    check("A39: repair on completed session -> SESSION_TERMINAL",
          rnx["code"] == "SESSION_TERMINAL", rnx)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    setup_db()
    conn = psycopg2.connect(_uri())
    conn.autocommit = False
    try:
        test_seal_gate_prepare_step(conn)
        test_seal_gate_generation(conn)
        test_seal_gate_tools(conn)
        test_dispatch_gate(conn)
        test_cohort_grant_denied(conn)
        test_cohort_generation(conn)
        test_cohort_recovery_grant(conn)
        test_cohort_recovery_generation(conn)
        test_takeover_prelock_lockwait(conn)
        test_takeover_isolation(conn)
        test_workspace_lost_a39(conn)
    finally:
        conn.close()
    print("[G12] all gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
