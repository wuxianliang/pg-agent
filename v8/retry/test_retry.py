"""G7a gate: v8 retry stage — known_failure settlement (dual requirement,
Conformance 5 decision table), the retry_eligible predicate, the shared
batch retry allocation sub-operation (cohort flip, superseded markers,
identity reuse), retry_effect guards/idempotency, aggregation rules 4/5
with the retry_stop_reason ordered classification, dual-table consistency,
late-completion stale rejection and allocation-transaction chaos.

Run: uv run python v8/retry/test_retry.py  (exit 0 = pass)
"""
from __future__ import annotations

import hashlib
import sys
import uuid
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v8.canonical import canonicalize, escape_dollar_keys
from v8.effect.client import (
    claim_session,
    complete_effect,
    dispatch_effect,
    prepare_step,
)
from v8.events.client import create_session
from v8.loop.runtime import ProcessDeath
from v8.retry.client import retry_effect
from v8.retry.setup_db import DB, main as setup_db
from v8.tools.client import complete_tool_effect, seal_batch

DRIVER = "drv"
EPOCH = 1


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f": {detail}" if detail else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def u() -> str:
    return str(uuid.uuid4())


def uri() -> str:
    return get_server().get_uri(DB)


def canon(obj) -> tuple[str, str]:
    return canonicalize(escape_dollar_keys(obj))


def rows(conn, sql: str, params: tuple = ()) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        out = cur.fetchall()
    conn.rollback()
    return out


def one(conn, sql: str, params: tuple = ()):
    r = rows(conn, sql, params)
    return r[0] if r else None


def exec_sql(conn, sql: str, params: tuple = ()) -> None:
    with conn.cursor() as cur:
        cur.execute(sql, params)
    conn.commit()


def good_evidence() -> dict:
    return {"class": "known_success",
            "provider_receipt": {"receipt_id": f"pr-{u()[:8]}"}}


def fail_evidence() -> dict:
    """The known_failure dual requirement: a deterministic provider failure
    receipt AND a persisted no-side-effect proof (both bound to the settled
    attempt by the client)."""
    return {"class": "known_failure",
            "provider_receipt": {"receipt_id": f"fr-{u()[:8]}"},
            "no_side_effect_proof": {"checked": True}}


class DyingConnection:
    """Process-death proxy (same shape as v8/loop/runtime.py): the first
    commit() rolls the real transaction back and raises — a dead backend's
    open transaction is rolled back by the server."""

    def __init__(self, conn):
        self._conn = conn

    def cursor(self, *args, **kwargs):
        return self._conn.cursor(*args, **kwargs)

    def commit(self):
        self._conn.rollback()
        raise ProcessDeath("mid_tx_before_retry_commit")

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def decision_fx(conn, retry_class: str = "verifiable_no_effect",
                max_attempts: int = 3):
    """create -> claim -> initial decision seal (single LLM slot with the
    given retry metadata) -> dispatch. The completion is run by the caller."""
    s = u()
    turn, step, eff = u(), u(), u()
    rh, ik = f"rh-{u()[:10]}", f"ik-{u()[:10]}"
    create_session(conn, s, DRIVER)
    r0 = claim_session(conn, s, DRIVER)
    rs = prepare_step(conn, s, f"seal-{u()[:8]}", DRIVER, EPOCH,
                      r0["session_fence"], step, turn, eff,
                      request_hash=rh, idempotency_key=ik,
                      retry_class=retry_class, max_attempts=max_attempts)
    check("fx seal accepted", rs["outcome"] == "accepted", rs)
    fence = rs["receipt"]["session_fence"]
    jf = rs["receipt"]["job_fence"]
    rd = dispatch_effect(conn, s, f"dsp-{u()[:8]}", eff, DRIVER, EPOCH,
                         fence, jf)
    check("fx dispatch accepted", rd["outcome"] == "accepted", rd)
    return {"session": s, "turn": turn, "step": step, "effect": eff,
            "fence": fence, "dsf": 2, "job_fence": jf, "rh": rh, "ik": ik,
            "kind": "decision"}


def fail_decision(conn, fx, attempt_no: int = 1, job_fence: int = None,
                  evidence: dict = None, declared: str = "failed_retryable"):
    dsf = 2 if attempt_no == 1 else fx["fence"]
    return complete_effect(
        conn, fx["session"], f"cmp-{u()[:8]}", fx["effect"], DRIVER, EPOCH,
        dispatch_session_fence=dsf, job_fence=job_fence or fx["job_fence"],
        step_id=fx["step"], attempt_no=attempt_no, request_hash=fx["rh"],
        idempotency_key=fx["ik"], outcome=declared, message={"text": ""},
        tools=[], decision_only=True, final_tools=False,
        evidence=evidence if evidence is not None else fail_evidence(),
        result_payload={"error": {"kind": "rate_limit"}})


def custom_slots(plan: list, specs: list) -> list:
    """Seal manifest with PER-SLOT (retry_class, max_attempts) specs —
    build_tool_slots applies uniform metadata, the mixed-budget fixtures
    need per-slot control."""
    slots = []
    for call, (rc, ma) in zip(plan, specs):
        payload = {"tool_call_id": call["tool_call_id"], "tool": call["tool"],
                   "arguments": call.get("arguments")}
        pc, _ = canon(payload)
        digest = hashlib.sha256(pc.encode("utf-8")).hexdigest()
        slots.append({
            "effect_id": u(),
            "tool_call_id": call["tool_call_id"],
            "tool": call["tool"],
            "arguments": call.get("arguments"),
            "payload_canonical": pc,
            "execution_mode": "non_streaming",
            "retry_class": rc,
            "max_attempts": ma,
            "request_hash": f"tool-req-{digest[:40]}",
            "idempotency_key": f"tool-ik-{digest[:40]}",
        })
    return slots


def tools_fx(conn, specs: list, seed: str = None):
    """decision with a tools plan -> successful final_tools decision ->
    claim -> tools seal with per-slot retry metadata -> dispatch every tool.
    The tool completions are run by the caller."""
    seed = seed or u()[:8]
    s = u()
    turn = u()
    create_session(conn, s, DRIVER)
    plan = [{"tool_call_id": f"call-{seed}-{i}", "tool": "fake_tool",
             "arguments": {"echo": seed}} for i in range(len(specs))]
    step, deff = u(), u()
    rh, ik = f"rh-{u()[:10]}", f"ik-{u()[:10]}"
    r0 = claim_session(conn, s, DRIVER)
    rs = prepare_step(conn, s, f"seal-{u()[:8]}", DRIVER, EPOCH,
                      r0["session_fence"], step, turn, deff,
                      request_hash=rh, idempotency_key=ik)
    check("fx decision seal accepted", rs["outcome"] == "accepted", rs)
    rd = dispatch_effect(conn, s, f"dsp-{u()[:8]}", deff, DRIVER, EPOCH,
                         rs["receipt"]["session_fence"],
                         rs["receipt"]["job_fence"])
    rc = complete_effect(
        conn, s, f"cmp-{u()[:8]}", deff, DRIVER, EPOCH,
        dispatch_session_fence=2, job_fence=rs["receipt"]["job_fence"],
        step_id=step, request_hash=rh, idempotency_key=ik,
        outcome="succeeded", message={"text": f"plan:{seed}"}, tools=plan,
        decision_only=False, final_tools=True, evidence=good_evidence())
    check("fx decision complete accepted", rc["outcome"] == "accepted", rc)
    dec_event_key = next(e["event_key"] for e in rc["receipt"]["events"]
                         if e["event_type"] == "assistant/message")
    plan_hash = one(conn, "SELECT plan_hash FROM steps WHERE step_id=%s",
                    (step,))[0]
    r1 = claim_session(conn, s, DRIVER)
    seal_fence = r1["session_fence"]
    slots = custom_slots(plan, specs)
    rseal = seal_batch(
        conn, s, f"tseal-{u()[:8]}", DRIVER, EPOCH, seal_fence, step, 1,
        {"effect_id": deff, "attempt_no": 1,
         "result_hash": rc["receipt"]["result_hash"],
         "event_key": dec_event_key},
        plan_hash, slots)
    check("fx tools seal accepted", rseal["outcome"] == "accepted", rseal)
    batch_id = rseal["receipt"]["batch_id"]
    by_ordinal = {e["dispatch_ordinal"]: e
                  for e in rseal["receipt"]["effects"]}
    effects = []
    for i, slot in enumerate(slots):
        e = by_ordinal[i]
        rd = dispatch_effect(conn, s, f"dsp-{u()[:8]}", e["effect_id"],
                             DRIVER, EPOCH, seal_fence + 1, e["job_fence"])
        check(f"fx tool {i} dispatch accepted", rd["outcome"] == "accepted",
              rd)
        effects.append({"effect_id": e["effect_id"],
                        "tool_call_id": slot["tool_call_id"],
                        "request_hash": slot["request_hash"],
                        "idempotency_key": slot["idempotency_key"],
                        "job_fence": e["job_fence"]})
    return {"session": s, "turn": turn, "step": step, "batch_id": batch_id,
            "effects": effects, "seal_fence": seal_fence,
            "post_seal_fence": seal_fence + 1, "kind": "tools"}


def fail_tool(conn, fx, i: int, attempt_no: int = 1, job_fence: int = None,
              evidence: dict = None, declared: str = "failed_retryable"):
    e = fx["effects"][i]
    dsf = fx["seal_fence"] if attempt_no == 1 else fx["post_seal_fence"]
    return complete_tool_effect(
        conn, fx["session"], f"cmp-{u()[:8]}", e["effect_id"], DRIVER, EPOCH,
        dispatch_session_fence=dsf, job_fence=job_fence or e["job_fence"],
        attempt_no=attempt_no, step_id=fx["step"],
        request_hash=e["request_hash"], idempotency_key=e["idempotency_key"],
        outcome=declared, tool_call_id=e["tool_call_id"],
        output={"error": "rate_limited"},
        evidence=evidence if evidence is not None else fail_evidence())


def succeed_tool(conn, fx, i: int, attempt_no: int = 1,
                 job_fence: int = None):
    e = fx["effects"][i]
    dsf = fx["seal_fence"] if attempt_no == 1 else fx["post_seal_fence"]
    return complete_tool_effect(
        conn, fx["session"], f"cmp-{u()[:8]}", e["effect_id"], DRIVER, EPOCH,
        dispatch_session_fence=dsf, job_fence=job_fence or e["job_fence"],
        attempt_no=attempt_no, step_id=fx["step"],
        request_hash=e["request_hash"], idempotency_key=e["idempotency_key"],
        outcome="succeeded", tool_call_id=e["tool_call_id"],
        output={"echo": "ok", "tool": "fake_tool"},
        evidence=good_evidence())


def retry(conn, fx, effect_id=None, fence: int = None, cmd: str = None):
    target = effect_id or (fx["effects"][0]["effect_id"]
                           if fx["kind"] == "tools" else fx["effect"])
    fence = fence if fence is not None else fx.get("post_seal_fence",
                                                   fx.get("fence"))
    return retry_effect(conn, fx["session"], cmd or f"rty-{u()[:8]}",
                        target, DRIVER, EPOCH, fence)


def effect_row(conn, effect_id):
    return one(conn,
               "SELECT status, attempt_no, current_job_fence, retry_class,"
               " max_attempts, retry_stop_reason, result_hash,"
               " provider_request_id FROM effect_requests WHERE effect_id=%s",
               (effect_id,))


def attempt_rows(conn, effect_id):
    return rows(conn,
                "SELECT attempt_no, status, superseded_by_attempt_no,"
                " dispatch_job_fence, request_hash, idempotency_key,"
                " driver, driver_epoch, session_fence, dispatch_session_fence"
                " FROM effect_attempts WHERE effect_id=%s ORDER BY attempt_no",
                (effect_id,))


def step_row(conn, step_id):
    return one(conn,
               "SELECT status, outcome_code, pending_effect_count,"
               " unknown_effect_count, retryable_effect_count,"
               " terminal_effect_count, retry_count, max_retries, closed_at"
               " FROM steps WHERE step_id=%s", (step_id,))


def session_row(conn, session_id):
    return one(conn, "SELECT state, failure_code FROM sessions"
                     " WHERE session_id=%s", (session_id,))


# ---------------------------------------------------------------------------
# 1. Conformance 5 decision table (known_failure dual requirement)
# ---------------------------------------------------------------------------

def test_conformance5_decision_table(conn) -> None:
    # (a) provider idempotent but NO bound terminal evidence -> unknown
    #     (idempotency only makes retries safe, never proves the result).
    fx = decision_fx(conn, retry_class="provider_idempotent", max_attempts=3)
    r = fail_decision(conn, fx, evidence={"class": "provider_error"})
    check("(a) idempotent + no receipt -> accepted, classified unknown",
          r["outcome"] == "accepted"
          and r["receipt"]["classification"] == "unknown", r["receipt"])
    check("(a) effect unknown_outcome (MUST NOT be known failure)",
          effect_row(conn, fx["effect"])[0] == "unknown_outcome")
    check("(a) step blocked_unknown_effect",
          step_row(conn, fx["step"])[0] == "blocked_unknown_effect")

    # (b) provider NON-idempotent (verifiable_no_effect) + deterministic
    #     failure receipt + persisted no-side-effect proof + eligible ->
    #     known failure with a SAFE retry (MUST NOT force unknown because
    #     the provider is not idempotent).
    fx = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=3)
    r = fail_decision(conn, fx)
    check("(b) non-idempotent + dual evidence -> accepted known_failure",
          r["outcome"] == "accepted"
          and r["receipt"]["classification"] == "known_failure"
          and r["receipt"]["derived_status"] == "failed_retryable"
          and r["receipt"]["retry_eligible"] is True, r["receipt"])
    check("(b) dual-requirement evidence persisted bound to the attempt",
          sorted(e[0] for e in rows(
              conn, "SELECT evidence_class FROM effect_evidence"
                    " WHERE effect_id=%s AND attempt_no=1", (fx["effect"],)))
          == ["failure_receipt", "no_side_effect_proof"])
    rr = retry(conn, fx, fence=fx["fence"])
    check("(b) safe retry allocated (attempt 2)",
          rr["outcome"] == "accepted"
          and attempt_rows(conn, fx["effect"])[-1][0] == 2, rr)

    # (c) ONLY a bound no-side-effect proof, NO provider terminal receipt
    #     (the golden catch-all row): unknown — the proof only witnesses
    #     retry safety, it never proves the result known.
    fx = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=3)
    r = fail_decision(conn, fx, evidence={
        "class": "known_failure",
        "no_side_effect_proof": {"checked": True}})
    check("(c) proof-only -> accepted, classified unknown (catch-all)",
          r["outcome"] == "accepted"
          and r["receipt"]["classification"] == "unknown", r["receipt"])
    check("(c) effect unknown_outcome (MUST NOT be known failure)",
          effect_row(conn, fx["effect"])[0] == "unknown_outcome")
    check("(c) no failure evidence persisted (no receipt component)",
          one(conn, "SELECT count(*) FROM effect_evidence"
                    " WHERE effect_id=%s", (fx["effect"],))[0] == 0)

    # (d) provider non-idempotent and no evidence at all -> unknown.
    fx = decision_fx(conn, retry_class="unsafe", max_attempts=3)
    r = fail_decision(conn, fx, evidence={"class": "provider_error"})
    check("(d) non-idempotent + no evidence -> unknown",
          r["outcome"] == "accepted"
          and r["receipt"]["classification"] == "unknown", r["receipt"])
    check("(d) effect unknown_outcome",
          effect_row(conn, fx["effect"])[0] == "unknown_outcome")


# ---------------------------------------------------------------------------
# 2. Rule 5 settlement: pure eligible batch -> step failed_retryable,
#    session ready, MUST NOT fail_session
# ---------------------------------------------------------------------------

def test_rule5_settlement(conn) -> None:
    fx = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=3)
    r = fail_decision(conn, fx)
    check("rule 5 completion accepted", r["outcome"] == "accepted", r)
    check("rule 5 receipt derives failed_retryable + FAILED_RETRYABLE",
          r["receipt"]["derived_status"] == "failed_retryable"
          and r["receipt"]["step_status"] == "failed_retryable"
          and r["receipt"]["session_state"] == "ready", r["receipt"])
    er = effect_row(conn, fx["effect"])
    check("effect+parent snapshot failed_retryable, no stop reason yet",
          er[0] == "failed_retryable" and er[5] is None, er)
    att = attempt_rows(conn, fx["effect"])
    check("attempt settles failed_retryable (dual-table sync)",
          len(att) == 1 and att[0][1] == "failed_retryable", att)
    check("failure facts frozen (result_hash + provider receipt id)",
          er[6] is not None and er[7] is not None, er)
    st = step_row(conn, fx["step"])
    check("step failed_retryable / FAILED_RETRYABLE / counters",
          st[0] == "failed_retryable" and st[1] == "FAILED_RETRYABLE"
          and st[2] == 0 and st[5] == 0 and st[6 + 0] == 0
          and st[4] == 1, st)
    sess = session_row(conn, fx["session"])
    check("session ready, failure_code NULL (MUST NOT fail_session)",
          sess == ("ready", None), sess)
    check("no terminal session row (fail_session source assertion)",
          one(conn, "SELECT count(*) FROM sessions WHERE session_id=%s"
                    " AND state='failed'", (fx["session"],))[0] == 0)
    check("no semantic events from a failure settlement",
          one(conn, "SELECT count(*) FROM session_events"
                    " WHERE session_id=%s", (fx["session"],))[0] == 0)


# ---------------------------------------------------------------------------
# 3. Budget exhaustion controlled edge (completion path)
# ---------------------------------------------------------------------------

def test_budget_first_attempt(conn) -> None:
    # max_attempts=1: zero retry budget at creation -> the FIRST failure is
    # terminal with first_attempt_failure (never budget_exhausted).
    fx = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=1)
    r = fail_decision(conn, fx)
    check("max_attempts=1 first failure -> accepted terminal",
          r["outcome"] == "accepted"
          and r["receipt"]["derived_status"] == "failed_terminal", r["receipt"])
    check("max_attempts=1 -> first_attempt_failure (not budget bucket)",
          r["receipt"]["retry_stop_reason"] == "first_attempt_failure",
          r["receipt"])
    er = effect_row(conn, fx["effect"])
    check("retry_stop_reason persisted on the effect row",
          er[5] == "first_attempt_failure" and er[0] == "failed_terminal", er)
    st = step_row(conn, fx["step"])
    check("step failed_terminal / FAILED_TERMINAL (rule 4)",
          st[0] == "failed_terminal" and st[1] == "FAILED_TERMINAL", st)
    sess = session_row(conn, fx["session"])
    check("session failed / FAILED_TERMINAL (fail_session class (1))",
          sess == ("failed", "FAILED_TERMINAL"), sess)


def test_unsafe_with_budget(conn) -> None:
    # retry_class=unsafe with budget available: never creation-eligible ->
    # first_attempt_failure (never not_retry_eligible).
    fx = decision_fx(conn, retry_class="unsafe", max_attempts=3)
    r = fail_decision(conn, fx)
    check("unsafe + budget -> accepted terminal",
          r["outcome"] == "accepted"
          and r["receipt"]["derived_status"] == "failed_terminal", r["receipt"])
    check("unsafe -> first_attempt_failure (not not_retry_eligible)",
          r["receipt"]["retry_stop_reason"] == "first_attempt_failure",
          r["receipt"])
    check("step/session FAILED_TERMINAL",
          step_row(conn, fx["step"])[1] == "FAILED_TERMINAL"
          and session_row(conn, fx["session"]) == ("failed", "FAILED_TERMINAL"))


def test_budget_multi_attempt(conn) -> None:
    # max_attempts=2: attempt 1 retryable -> retry -> attempt 2 exhausts the
    # budget -> budget_exhausted at settlement, FAILED_RETRY_BUDGET_EXHAUSTED.
    fx = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=2)
    r1 = fail_decision(conn, fx)
    check("attempt 1 retryable (budget 1 < 2)",
          r1["receipt"]["derived_status"] == "failed_retryable", r1["receipt"])
    rr = retry(conn, fx, fence=fx["fence"])
    check("retry allocated attempt 2", rr["outcome"] == "accepted", rr)
    jf2 = rr["receipt"]["effects"][0]["job_fence"]
    rd = dispatch_effect(conn, fx["session"], f"dsp-{u()[:8]}", fx["effect"],
                         DRIVER, EPOCH, fx["fence"], jf2)
    check("attempt 2 dispatch accepted", rd["outcome"] == "accepted", rd)
    r2 = fail_decision(conn, fx, attempt_no=2, job_fence=jf2)
    check("attempt 2 (2 >= 2) -> accepted terminal budget_exhausted",
          r2["outcome"] == "accepted"
          and r2["receipt"]["derived_status"] == "failed_terminal"
          and r2["receipt"]["retry_stop_reason"] == "budget_exhausted",
          r2["receipt"])
    st = step_row(conn, fx["step"])
    check("step failed_terminal / FAILED_RETRY_BUDGET_EXHAUSTED",
          st[0] == "failed_terminal"
          and st[1] == "FAILED_RETRY_BUDGET_EXHAUSTED", st)
    sess = session_row(conn, fx["session"])
    check("session failed / FAILED_RETRY_BUDGET_EXHAUSTED",
          sess == ("failed", "FAILED_RETRY_BUDGET_EXHAUSTED"), sess)
    check("evidence rows persisted per attempt",
          one(conn, "SELECT count(DISTINCT attempt_no)"
                    " FROM effect_evidence WHERE effect_id=%s",
              (fx["effect"],))[0] == 2)


# ---------------------------------------------------------------------------
# 4. Pure-budget batch (rule 4, all reasons budget_exhausted)
# ---------------------------------------------------------------------------

def test_pure_budget_batch(conn) -> None:
    fx = tools_fx(conn, [("verifiable_no_effect", 2), ("verifiable_no_effect", 2)])
    fail_tool(conn, fx, 0)
    fail_tool(conn, fx, 1)
    st = step_row(conn, fx["step"])
    check("both tools failed_retryable -> rule 5 first",
          st[0] == "failed_retryable" and st[1] == "FAILED_RETRYABLE", st)
    rr = retry(conn, fx)
    check("cohort retry allocated both attempts",
          rr["outcome"] == "accepted"
          and len(rr["receipt"]["effects"]) == 2, rr["receipt"])
    fences = {e["effect_id"]: e["job_fence"] for e in rr["receipt"]["effects"]}
    for i, e in enumerate(fx["effects"]):
        rd = dispatch_effect(conn, fx["session"], f"dsp-{u()[:8]}",
                             e["effect_id"], DRIVER, EPOCH,
                             fx["post_seal_fence"], fences[e["effect_id"]])
        check(f"tool {i} attempt-2 dispatch accepted",
              rd["outcome"] == "accepted", rd)
        rci = fail_tool(conn, fx, i, attempt_no=2,
                        job_fence=fences[e["effect_id"]])
        check(f"tool {i} attempt 2 (2 >= 2) -> terminal budget_exhausted",
              rci["receipt"]["derived_status"] == "failed_terminal"
              and rci["receipt"]["retry_stop_reason"] == "budget_exhausted",
              rci["receipt"])
    st = step_row(conn, fx["step"])
    sess = session_row(conn, fx["session"])
    check("pure budget batch: step FAILED_RETRY_BUDGET_EXHAUSTED",
          st[0] == "failed_terminal"
          and st[1] == "FAILED_RETRY_BUDGET_EXHAUSTED", st)
    check("pure budget batch: session failed with the same code",
          sess == ("failed", "FAILED_RETRY_BUDGET_EXHAUSTED"), sess)
    check("no RETRY_STOPPED_BY_CLOSURE audit on a pure budget batch "
          "(both effects settled terminal directly)",
          one(conn, "SELECT count(*) FROM effect_audit"
                    " WHERE session_id=%s"
                    " AND reason='RETRY_STOPPED_BY_CLOSURE'",
              (fx["session"],))[0] == 0)


# ---------------------------------------------------------------------------
# 5. Mixed-budget batch: rule 4 residual closure + code derivation
# ---------------------------------------------------------------------------

def test_rule4_residual_closure(conn) -> None:
    fx = tools_fx(conn, [("verifiable_no_effect", 3),   # A: budget remains
                   ("verifiable_no_effect", 2)])  # B: exhausts at attempt 2
    fail_tool(conn, fx, 0)
    fail_tool(conn, fx, 1)
    check("mixed fixture: rule 5 after both first failures",
          step_row(conn, fx["step"])[0] == "failed_retryable")
    rr = retry(conn, fx)
    fences = {e["effect_id"]: e["job_fence"] for e in rr["receipt"]["effects"]}
    # B fails terminally first (budget exhausted); A is still pending ->
    # rule 2 keeps the step waiting.
    rd = dispatch_effect(conn, fx["session"], f"dsp-{u()[:8]}",
                         fx["effects"][1]["effect_id"], DRIVER, EPOCH,
                         fx["post_seal_fence"], fences[fx["effects"][1]["effect_id"]])
    rb = fail_tool(conn, fx, 1, attempt_no=2,
                   job_fence=fences[fx["effects"][1]["effect_id"]])
    check("B attempt 2 -> terminal budget_exhausted",
          rb["receipt"]["derived_status"] == "failed_terminal"
          and rb["receipt"]["retry_stop_reason"] == "budget_exhausted",
          rb["receipt"])
    check("A pending keeps the step waiting (rule 2)",
          step_row(conn, fx["step"])[0] == "waiting_effect")
    # A fails retryably (2 < 3, eligible) -> the batch has a failed_terminal
    # sibling -> rule 4 closes A through the controlled edge.
    rd = dispatch_effect(conn, fx["session"], f"dsp-{u()[:8]}",
                         fx["effects"][0]["effect_id"], DRIVER, EPOCH,
                         fx["post_seal_fence"], fences[fx["effects"][0]["effect_id"]])
    ra = fail_tool(conn, fx, 0, attempt_no=2,
                   job_fence=fences[fx["effects"][0]["effect_id"]])
    check("A settles retryable by evidence, closes by rule 4",
          ra["receipt"]["derived_status"] == "failed_retryable"
          and ra["receipt"]["step_status"] == "failed_terminal", ra["receipt"])
    er_a = effect_row(conn, fx["effects"][0]["effect_id"])
    check("A closed failed_terminal with not_retry_eligible "
          "(residual eligible sibling)",
          er_a[0] == "failed_terminal" and er_a[5] == "not_retry_eligible",
          er_a)
    check("RETRY_STOPPED_BY_CLOSURE audit written for A",
          one(conn, "SELECT count(*) FROM effect_audit"
                    " WHERE effect_id=%s AND reason='RETRY_STOPPED_BY_CLOSURE'",
              (fx["effects"][0]["effect_id"],))[0] == 1)
    st = step_row(conn, fx["step"])
    sess = session_row(conn, fx["session"])
    check("reason set {budget_exhausted, not_retry_eligible} -> "
          "FAILED_TERMINAL (not the budget code)",
          st[0] == "failed_terminal" and st[1] == "FAILED_TERMINAL"
          and sess == ("failed", "FAILED_TERMINAL"), (st, sess))
    check("retry_effect after closure -> SESSION_TERMINAL",
          retry(conn, fx, fence=fx["post_seal_fence"])["code"]
          == "SESSION_TERMINAL")


# ---------------------------------------------------------------------------
# 6. Cohort allocation on a pure eligible batch (normal entry assertions)
# ---------------------------------------------------------------------------

def test_cohort_allocation(conn) -> None:
    fx = tools_fx(conn, [("verifiable_no_effect", 3),
                   ("provider_idempotent", 3)])
    fail_tool(conn, fx, 0)
    check("first failure with pending sibling -> rule 2",
          step_row(conn, fx["step"])[0] == "waiting_effect"
          and session_row(conn, fx["session"])[0] == "waiting_effect")
    fail_tool(conn, fx, 1)
    st = step_row(conn, fx["step"])
    check("both failed -> rule 5: step failed_retryable, session ready",
          st[0] == "failed_retryable" and st[1] == "FAILED_RETRYABLE"
          and session_row(conn, fx["session"])[0] == "ready", st)
    pre_fences = [e["job_fence"] for e in fx["effects"]]

    rr = retry(conn, fx)
    check("retry_effect accepted for the whole cohort",
          rr["outcome"] == "accepted", rr)
    rec = rr["receipt"]
    check("receipt allocates both members in ordinal order",
          [e["dispatch_ordinal"] for e in rec["effects"]] == [0, 1]
          and all(e["attempt_no"] == 2 and e["old_attempt_no"] == 1
                  for e in rec["effects"]), rec["effects"])

    for i, e in enumerate(fx["effects"]):
        er = effect_row(conn, e["effect_id"])
        att = attempt_rows(conn, e["effect_id"])
        check(f"tool {i}: effect ready, attempt_no=2, fresh fence",
              er[0] == "ready" and er[1] == 2
              and er[2] > pre_fences[i], er)
        check(f"tool {i}: exactly two attempt rows, no ready-without-attempt"
              " window (single commit)",
              len(att) == 2 and att[1][0] == 2 and att[1][1] == "ready", att)
        check(f"tool {i}: old attempt superseded, status preserved",
              att[0][2] == 2 and att[0][1] == "failed_retryable", att)
        check(f"tool {i}: identity reuse (request_hash/idempotency_key)",
              att[1][4] == e["request_hash"]
              and att[1][5] == e["idempotency_key"]
              and att[0][4] == att[1][4] and att[0][5] == att[1][5], att)
        check(f"tool {i}: execution snapshot re-frozen from current session",
              att[1][6] == DRIVER and att[1][7] == 1
              and att[1][8] == fx["post_seal_fence"]
              and att[1][9] == fx["post_seal_fence"], att)
        check(f"tool {i}: dual fence same value (current == dispatch)",
              er[2] == att[1][3], (er, att))
        check(f"tool {i}: fences strictly increasing",
              att[0][3] < att[1][3], att)

    st = step_row(conn, fx["step"])
    check("post-allocation final aggregation: rule 2 waiting_effect "
          "(MUST NOT derive session ready)",
          st[0] == "waiting_effect" and st[1] is None
          and st[2] == 2 and st[4] == 0
          and session_row(conn, fx["session"])[0] == "waiting_effect", st)
    check("derived retry caches advanced (retry_count=2, max_retries=2)",
          st[6] == 2 and st[7] == 2, st)

    # The recovered loop: dispatch + succeed both -> final_tools
    # terminalization works over the retried attempts.
    fences = {e["effect_id"]: e["job_fence"] for e in rec["effects"]}
    for i, e in enumerate(fx["effects"]):
        rd = dispatch_effect(conn, fx["session"], f"dsp-{u()[:8]}",
                             e["effect_id"], DRIVER, EPOCH,
                             fx["post_seal_fence"], fences[e["effect_id"]])
        check(f"recovered tool {i} dispatch accepted",
              rd["outcome"] == "accepted", rd)
        rci = succeed_tool(conn, fx, i, attempt_no=2,
                           job_fence=fences[e["effect_id"]])
        check(f"recovered tool {i} success accepted",
              rci["outcome"] == "accepted", rci)
    st = step_row(conn, fx["step"])
    check("all-succeeded retried batch -> step succeeded/closed (rule 6)",
          st[0] == "succeeded" and st[1] == "SUCCEEDED" and st[8] is not None,
          st)
    check("session back to ready after the recovered batch",
          session_row(conn, fx["session"])[0] == "ready")


# ---------------------------------------------------------------------------
# 7. Success with a failure sibling (rules 4/5 outrank the success arm)
# ---------------------------------------------------------------------------

def test_success_with_failure_sibling(conn) -> None:
    fx = tools_fx(conn, [("verifiable_no_effect", 3), ("unsafe", 1)])
    rb = fail_tool(conn, fx, 1)                 # B: unsafe -> terminal first
    check("B unsafe -> terminal first_attempt_failure",
          rb["receipt"]["derived_status"] == "failed_terminal"
          and rb["receipt"]["retry_stop_reason"] == "first_attempt_failure",
          rb["receipt"])
    check("terminal B with pending A -> rule 2 waiting",
          step_row(conn, fx["step"])[0] == "waiting_effect")
    ra = fail_tool(conn, fx, 0)                 # A: eligible retryable
    # The batch now holds a failed_terminal sibling -> rule 4 closes A
    # through the controlled edge (aggregation priority failed_terminal >
    # failed_retryable).
    check("A settles retryable then the batch closes by rule 4",
          ra["receipt"]["derived_status"] == "failed_retryable"
          and ra["receipt"]["step_status"] == "failed_terminal", ra["receipt"])
    er_a = effect_row(conn, fx["effects"][0]["effect_id"])
    check("A closed failed_terminal with not_retry_eligible",
          er_a[0] == "failed_terminal" and er_a[5] == "not_retry_eligible",
          er_a)
    check("RETRY_STOPPED_BY_CLOSURE audit written for A",
          one(conn, "SELECT count(*) FROM effect_audit"
                    " WHERE effect_id=%s AND reason='RETRY_STOPPED_BY_CLOSURE'",
              (fx["effects"][0]["effect_id"],))[0] == 1)
    check("step/session FAILED_TERMINAL (first_attempt_failure in the set)",
          step_row(conn, fx["step"])[1] == "FAILED_TERMINAL"
          and session_row(conn, fx["session"]) == ("failed", "FAILED_TERMINAL"))

    # Control: the SAME batch shape with B SUCCEEDING instead -> rule 5
    # outranks success; a retry then recovers the batch.
    fx = tools_fx(conn, [("verifiable_no_effect", 3), ("verifiable_no_effect", 1)])
    fail_tool(conn, fx, 0)
    rbs = succeed_tool(conn, fx, 1)              # B succeeds (max_attempts=1)
    check("B success with failed_retryable A accepted",
          rbs["outcome"] == "accepted", rbs)
    st = step_row(conn, fx["step"])
    check("rule 5 outranks success: step failed_retryable, session ready",
          st[0] == "failed_retryable" and st[1] == "FAILED_RETRYABLE"
          and session_row(conn, fx["session"])[0] == "ready", st)
    rr = retry(conn, fx)
    check("cohort = only the failed_retryable member (B stays succeeded)",
          len(rr["receipt"]["effects"]) == 1
          and rr["receipt"]["effects"][0]["effect_id"]
          == fx["effects"][0]["effect_id"], rr["receipt"])
    jf = rr["receipt"]["effects"][0]["job_fence"]
    rd = dispatch_effect(conn, fx["session"], f"dsp-{u()[:8]}",
                         fx["effects"][0]["effect_id"], DRIVER, EPOCH,
                         fx["post_seal_fence"], jf)
    rcs = succeed_tool(conn, fx, 0, attempt_no=2, job_fence=jf)
    check("recovered A succeeds", rcs["outcome"] == "accepted", rcs)
    check("batch all-succeeded -> step succeeded (full recovery)",
          step_row(conn, fx["step"])[0] == "succeeded")


# ---------------------------------------------------------------------------
# 8. Sibling blockers: pending / unknown (public path + drift path)
# ---------------------------------------------------------------------------

def test_sibling_blockers(conn) -> None:
    # Public path, pending sibling: A fails while B is dispatch_started.
    fx = tools_fx(conn, [("verifiable_no_effect", 3),
                   ("verifiable_no_effect", 3)])
    fail_tool(conn, fx, 0)
    rr = retry(conn, fx)
    check("pending sibling blocks retry (step still waiting)",
          rr["outcome"] == "rejected_mismatch"
          and step_row(conn, fx["step"])[0] == "waiting_effect", rr)
    check("pending-sibling rejection: zero allocation",
          one(conn, "SELECT count(*) FROM effect_attempts a"
                    " WHERE a.effect_id IN (SELECT effect_id"
                    " FROM effect_requests WHERE batch_id=%s)",
              (fx["batch_id"],))[0] == 2)

    # Public path, unknown sibling: A settles unknown, B fails retryably.
    fx = tools_fx(conn, [("verifiable_no_effect", 3),
                   ("verifiable_no_effect", 3)])
    ra = fail_tool(conn, fx, 0, evidence={"class": "provider_error"})
    check("A unknown settlement", ra["receipt"]["classification"] == "unknown")
    rb = fail_tool(conn, fx, 1)
    check("B known_failure settles retryable under an unknown sibling",
          rb["receipt"]["derived_status"] == "failed_retryable"
          and rb["receipt"]["step_status"] == "blocked_unknown_effect",
          rb["receipt"])
    rr = retry(conn, fx)
    check("unknown sibling blocks retry (step stays blocked)",
          rr["outcome"] == "rejected_mismatch"
          and step_row(conn, fx["step"])[0] == "blocked_unknown_effect", rr)
    check("unknown-sibling rejection: zero allocation",
          one(conn, "SELECT count(*) FROM effect_attempts a"
                    " WHERE a.effect_id IN (SELECT effect_id"
                    " FROM effect_requests WHERE batch_id=%s)",
              (fx["batch_id"],))[0] == 2)

    # Drift path (batch-level precondition codes): a pure eligible batch
    # (step failed_retryable, session ready) gains a direct-SQL pending /
    # unknown sibling -> the virtual aggregation classifies the rejection.
    fx = tools_fx(conn, [("verifiable_no_effect", 3),
                   ("verifiable_no_effect", 3)])
    fail_tool(conn, fx, 0)
    fail_tool(conn, fx, 1)
    check("drift fixture: rule 5", step_row(conn, fx["step"])[0]
          == "failed_retryable")
    for status, code in (("dispatch_started", "SIBLING_PENDING"),
                         ("unknown_outcome", "SIBLING_UNKNOWN")):
        exec_sql(
            conn,
            "INSERT INTO effect_requests(effect_id, session_id, step_id,"
            " batch_id, dispatch_ordinal, tool_call_id, effect_kind,"
            " execution_mode, driver, driver_epoch, session_fence,"
            " dispatch_session_fence, current_job_fence, request_hash,"
            " idempotency_key, status, retry_class, max_attempts,"
            " dispatched_at)"
            " VALUES (%s, %s, %s, %s, 9, %s, 'tool_x', 'non_streaming',"
            " 'drv', 1, 5, 5, nextval('v8_job_fence_seq'), 'rh-x', 'ik-x',"
            " %s, 'unsafe', 1, now())",
            (u(), fx["session"], fx["step"], fx["batch_id"],
             f"tc-{code}", status))
        rr = retry(conn, fx)
        check(f"batch precondition ({status}) -> {code}",
              rr["outcome"] == "rejected_mismatch" and rr["code"] == code,
              rr)
        check(f"{code}: zero allocation, step keeps failed_retryable",
              one(conn, "SELECT count(*) FROM effect_attempts a"
                        " WHERE a.effect_id IN (SELECT effect_id"
                        " FROM effect_requests WHERE batch_id=%s)",
                  (fx["batch_id"],))[0] == 2
              and step_row(conn, fx["step"])[0] == "failed_retryable")
        exec_sql(conn, "DELETE FROM effect_requests WHERE session_id=%s"
                       " AND dispatch_ordinal=9", (fx["session"],))


# ---------------------------------------------------------------------------
# 9. retry_effect guards + receipt idempotency
# ---------------------------------------------------------------------------

def test_retry_guards(conn) -> None:
    fx = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=3)
    r = retry(conn, fx, fence=fx["fence"])
    check("retry on a non-failed effect -> EFFECT_NOT_RETRYABLE",
          r["outcome"] == "rejected_mismatch"
          and r["code"] == "EFFECT_NOT_RETRYABLE", r)
    check("rejection: zero allocation",
          one(conn, "SELECT count(*) FROM effect_attempts"
                    " WHERE effect_id=%s", (fx["effect"],))[0] == 1)
    r = retry(conn, fx, fence=fx["fence"] - 1)
    check("stale session fence -> SESSION_FENCE_STALE",
          r["outcome"] == "rejected_stale" and r["code"] == "SESSION_FENCE_STALE",
          r)
    r = retry_effect(conn, fx["session"], f"rty-{u()[:8]}", fx["effect"],
                     "rogue", EPOCH, fx["fence"])
    check("wrong driver -> DRIVER_EPOCH_STALE",
          r["outcome"] == "rejected_stale" and r["code"] == "DRIVER_EPOCH_STALE",
          r)
    r = retry_effect(conn, fx["session"], f"rty-{u()[:8]}", u(), DRIVER,
                     EPOCH, fx["fence"])
    check("unknown effect -> EFFECT_NOT_FOUND",
          r["outcome"] == "rejected_mismatch" and r["code"] == "EFFECT_NOT_FOUND",
          r)

    fail_decision(conn, fx)
    # Sticky cancel blocks retry.
    exec_sql(conn, "UPDATE sessions SET cancellation_epoch=1"
                   " WHERE session_id=%s", (fx["session"],))
    r = retry(conn, fx, fence=fx["fence"])
    check("sticky cancel -> CANCEL_STICKY (no retry after cancel)",
          r["outcome"] == "rejected_mismatch" and r["code"] == "CANCEL_STICKY",
          r)
    exec_sql(conn, "UPDATE sessions SET cancellation_epoch=0"
                   " WHERE session_id=%s", (fx["session"],))

    # Receipt idempotency: same command replays, different payload conflicts.
    cmd = f"rty-{u()[:8]}"
    r1 = retry_effect(conn, fx["session"], cmd, fx["effect"], DRIVER, EPOCH,
                      fx["fence"])
    check("retry accepted", r1["outcome"] == "accepted", r1)
    r2 = retry_effect(conn, fx["session"], cmd, fx["effect"], DRIVER, EPOCH,
                      fx["fence"])
    check("same command_id retry replays the original receipt",
          r2["outcome"] == "accepted" and r2["receipt"] == r1["receipt"], r2)
    r3 = retry_effect(conn, fx["session"], cmd, fx["effect"], DRIVER, EPOCH,
                      fx["fence"] + 5)
    check("same command_id different payload -> IDEMPOTENCY_CONFLICT",
          r3["outcome"] == "rejected_mismatch"
          and r3["code"] == "IDEMPOTENCY_CONFLICT", r3)
    r4 = retry(conn, fx, fence=fx["fence"])
    check("post-allocation re-retry (effect now ready) -> "
          "EFFECT_NOT_RETRYABLE",
          r4["outcome"] == "rejected_mismatch"
          and r4["code"] == "EFFECT_NOT_RETRYABLE", r4)
    check("no extra attempts from replays/rejections",
          one(conn, "SELECT count(*) FROM effect_attempts"
                    " WHERE effect_id=%s", (fx["effect"],))[0] == 2)

    # Declared-hash gate on the retry command.
    fx = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=3)
    fail_decision(conn, fx)
    r = retry_effect(conn, fx["session"], f"rty-{u()[:8]}", fx["effect"],
                     DRIVER, EPOCH, fx["fence"], declared_hash="0" * 64)
    check("declared-hash mismatch -> REQUEST_HASH_MISMATCH",
          r["outcome"] == "rejected_mismatch"
          and r["code"] == "REQUEST_HASH_MISMATCH", r)


# ---------------------------------------------------------------------------
# 10. Late completion after a retry: stale + superseded
# ---------------------------------------------------------------------------

def test_late_completion_after_retry(conn) -> None:
    fx = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=3)
    fail_decision(conn, fx)
    rr = retry(conn, fx, fence=fx["fence"])
    old_fence = fx["job_fence"]

    # The old-era completion carries the OLD job fence -> STALE_JOB_FENCE
    # (the dual fence is the sole stale authority), receipt + audit only.
    r = fail_decision(conn, fx, attempt_no=1, job_fence=old_fence,
                      declared="succeeded")
    check("old-era completion -> rejected_stale STALE_JOB_FENCE",
          r["outcome"] == "rejected_stale" and r["code"] == "STALE_JOB_FENCE",
          r)
    check("stale completion wrote the audit row",
          one(conn, "SELECT count(*) FROM effect_audit"
                    " WHERE effect_id=%s AND reason='STALE_JOB_FENCE'",
              (fx["effect"],))[0] == 1)
    check("stale completion: zero control state (attempt 2 still ready)",
          effect_row(conn, fx["effect"])[0] == "ready"
          and one(conn, "SELECT count(*) FROM effect_attempts"
                        " WHERE effect_id=%s", (fx["effect"],))[0] == 2)

    # A completion naming the REPLACED attempt with the CURRENT fence ->
    # ATTEMPT_SUPERSEDED (late results of a replaced attempt are
    # audit-only).
    r = fail_decision(conn, fx, attempt_no=1,
                      job_fence=rr["receipt"]["effects"][0]["job_fence"])
    check("superseded attempt + current fence -> ATTEMPT_SUPERSEDED",
          r["outcome"] == "rejected_stale"
          and r["code"] == "ATTEMPT_SUPERSEDED", r)
    check("superseded audit row written",
          one(conn, "SELECT count(*) FROM effect_audit"
                    " WHERE effect_id=%s AND reason='ATTEMPT_SUPERSEDED'",
              (fx["effect"],))[0] == 1)
    check("old attempt keeps its own status (superseded, failed_retryable)",
          attempt_rows(conn, fx["effect"])[0][1] == "failed_retryable")


# ---------------------------------------------------------------------------
# 11. Declared outcome vs evidence (Conformance 5 vector (i))
# ---------------------------------------------------------------------------

def test_outcome_mismatch_on_failure(conn) -> None:
    fx = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=3)
    r = fail_decision(conn, fx, declared="succeeded")
    check("declared succeeded x failure evidence -> accepted (never "
          "rejected)",
          r["outcome"] == "accepted"
          and r["receipt"]["derived_status"] == "failed_retryable",
          r["receipt"])
    check("settlement by evidence (MUST NOT settle success)",
          effect_row(conn, fx["effect"])[0] == "failed_retryable")
    check("RESULT_OUTCOME_MISMATCH audit row present",
          one(conn, "SELECT count(*) FROM effect_audit"
                    " WHERE effect_id=%s"
                    " AND reason='RESULT_OUTCOME_MISMATCH'",
              (fx["effect"],))[0] == 1)
    # Control vector: matching declaration -> no audit row.
    fx = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=3)
    fail_decision(conn, fx, declared="failed_retryable")
    check("matching declaration -> no mismatch audit row",
          one(conn, "SELECT count(*) FROM effect_audit"
                    " WHERE effect_id=%s"
                    " AND reason='RESULT_OUTCOME_MISMATCH'",
              (fx["effect"],))[0] == 0)


# ---------------------------------------------------------------------------
# 12. Ordered classification function + R-01 cache contract (unit)
# ---------------------------------------------------------------------------

def test_stop_reason_unit(conn) -> None:
    def reason_of(eff) -> str:
        return one(conn, "SELECT v_retry_stop_reason(%s)", (eff,))[0]

    # unsafe + budget available -> first_attempt_failure (item 2).
    fx = decision_fx(conn, retry_class="unsafe", max_attempts=3)
    check("unsafe + budget -> first_attempt_failure",
          reason_of(fx["effect"]) == "first_attempt_failure")
    # max_attempts=1 -> first_attempt_failure (item 2, never budget).
    fx = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=1)
    check("max_attempts=1 -> first_attempt_failure",
          reason_of(fx["effect"]) == "first_attempt_failure")
    # eligible class + budget remaining -> not_retry_eligible fallthrough
    # (item 3: only reachable as a closure output).
    fx = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=3)
    fail_decision(conn, fx)
    check("eligible + budget remaining -> not_retry_eligible (fallthrough)",
          reason_of(fx["effect"]) == "not_retry_eligible")
    # budget exhausted (max > 1) -> budget_exhausted (item 1).
    fx = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=2)
    fail_decision(conn, fx)
    retry(conn, fx, fence=fx["fence"])
    jf2 = one(conn, "SELECT current_job_fence FROM effect_requests"
                    " WHERE effect_id=%s", (fx["effect"],))[0]
    dispatch_effect(conn, fx["session"], f"dsp-{u()[:8]}", fx["effect"],
                    DRIVER, EPOCH, fx["fence"], jf2)
    fail_decision(conn, fx, attempt_no=2, job_fence=jf2)
    check("attempt_no == max_attempts -> budget_exhausted",
          reason_of(fx["effect"]) == "budget_exhausted")

    # R-01 cache contract: recomputing on an agreeing column is idempotent;
    # a disagreeing column is an INFRA_PROTOCOL_VIOLATION (kept original).
    fx = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=1)
    fail_decision(conn, fx)
    with conn.cursor() as cur:
        cur.execute("SELECT v_retry_stop_reason_cas(%s)", (fx["effect"],))
        again = cur.fetchone()[0]
    conn.commit()
    check("CAS on an agreeing column is idempotent",
          again == "first_attempt_failure"
          and effect_row(conn, fx["effect"])[5] == "first_attempt_failure")
    exec_sql(conn, "UPDATE effect_requests SET retry_stop_reason="
                   "'budget_exhausted' WHERE effect_id=%s", (fx["effect"],))
    with conn.cursor() as cur:
        cur.execute("SELECT v_retry_stop_reason_cas(%s)", (fx["effect"],))
        cas = cur.fetchone()[0]
    conn.commit()
    check("CAS mismatch -> controlled INFRA_PROTOCOL_VIOLATION, no abort",
          cas == "INFRA_PROTOCOL_VIOLATION", cas)
    check("column keeps the original value through the violation",
          effect_row(conn, fx["effect"])[5] == "budget_exhausted")
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM effect_audit WHERE effect_id=%s"
                    " AND reason='INFRA_PROTOCOL_VIOLATION'", (fx["effect"],))
        check("CAS mismatch retains both sides in exactly one audit row",
              cur.fetchone()[0] == 1)
    # Idempotent: re-running the same CAS returns the same controlled code
    # and writes no second audit row.
    with conn.cursor() as cur:
        cur.execute("SELECT v_retry_stop_reason_cas(%s)", (fx["effect"],))
        cas2 = cur.fetchone()[0]
    conn.commit()
    check("CAS mismatch replay: same code", cas2 == "INFRA_PROTOCOL_VIOLATION")
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM effect_audit WHERE effect_id=%s"
                    " AND reason='INFRA_PROTOCOL_VIOLATION'", (fx["effect"],))
        check("CAS mismatch replay: still exactly one audit row",
              cur.fetchone()[0] == 1)


# ---------------------------------------------------------------------------
# 13. retry_eligible unit (budget / class / persisted evidence legs)
# ---------------------------------------------------------------------------

def test_retry_eligible_unit(conn) -> None:
    def eligible(eff) -> bool:
        return one(conn, "SELECT v_retry_eligible(%s)", (eff,))[0]

    fx = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=3)
    check("no evidence persisted yet -> not eligible",
          eligible(fx["effect"]) is False)
    fail_decision(conn, fx)
    check("dual evidence persisted -> eligible",
          eligible(fx["effect"]) is True)
    fx = decision_fx(conn, retry_class="provider_idempotent", max_attempts=3)
    fail_decision(conn, fx)
    check("provider_idempotent + dual evidence -> eligible",
          eligible(fx["effect"]) is True)
    fx = decision_fx(conn, retry_class="unsafe", max_attempts=3)
    fail_decision(conn, fx)
    check("unsafe class -> never eligible", eligible(fx["effect"]) is False)
    fx = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=2)
    fail_decision(conn, fx)
    check("budget available (1 < 2) -> eligible", eligible(fx["effect"]) is True)
    retry(conn, fx, fence=fx["fence"])
    jf2 = one(conn, "SELECT current_job_fence FROM effect_requests"
                    " WHERE effect_id=%s", (fx["effect"],))[0]
    dispatch_effect(conn, fx["session"], f"dsp-{u()[:8]}", fx["effect"],
                    DRIVER, EPOCH, fx["fence"], jf2)
    fail_decision(conn, fx, attempt_no=2, job_fence=jf2)
    check("budget exhausted (2 >= 2) -> not eligible",
          eligible(fx["effect"]) is False)


# ---------------------------------------------------------------------------
# 14. Immutability: evidence rows + superseded write-once
# ---------------------------------------------------------------------------

def test_immutability(conn) -> None:
    fx = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=3)
    fail_decision(conn, fx)
    retry(conn, fx, fence=fx["fence"])
    try:
        exec_sql(conn, "UPDATE effect_evidence SET receipt_id='tampered'"
                       " WHERE effect_id=%s", (fx["effect"],))
        check("effect_evidence is append-only", False, "update succeeded")
    except psycopg2.Error as exc:
        conn.rollback()
        check("effect_evidence is append-only", "append-only" in str(exc),
              str(exc)[:80])
    try:
        exec_sql(conn, "UPDATE effect_attempts SET superseded_by_attempt_no=99"
                       " WHERE effect_id=%s AND attempt_no=1", (fx["effect"],))
        check("superseded marker is write-once", False, "update succeeded")
    except psycopg2.Error as exc:
        conn.rollback()
        check("superseded marker is write-once", "write-once" in str(exc),
              str(exc)[:80])
    try:
        exec_sql(conn, "UPDATE effect_attempts SET superseded_by_attempt_no"
                       "=NULL WHERE effect_id=%s AND attempt_no=1",
                 (fx["effect"],))
        check("superseded marker cannot be cleared", False, "update succeeded")
    except psycopg2.Error as exc:
        conn.rollback()
        check("superseded marker cannot be cleared", "write-once" in str(exc),
              str(exc)[:80])


# ---------------------------------------------------------------------------
# 15. Dual-table consistency after retry commits
# ---------------------------------------------------------------------------

def test_dual_table_consistency(conn) -> None:
    fx = tools_fx(conn, [("verifiable_no_effect", 3),
                   ("verifiable_no_effect", 3)])
    fail_tool(conn, fx, 0)
    fail_tool(conn, fx, 1)
    retry(conn, fx)
    fences = {str(r[0]): r[1] for r in rows(
        conn,
        "SELECT er.effect_id, a.dispatch_job_fence FROM effect_requests er"
        " JOIN LATERAL (SELECT dispatch_job_fence FROM effect_attempts x"
        "   WHERE x.effect_id = er.effect_id"
        "   ORDER BY attempt_no DESC LIMIT 1) a ON true"
        " WHERE er.batch_id = %s", (fx["batch_id"],))}
    for i, e in enumerate(fx["effects"]):
        dispatch_effect(conn, fx["session"], f"dsp-{u()[:8]}", e["effect_id"],
                        DRIVER, EPOCH, fx["post_seal_fence"],
                        fences[e["effect_id"]])
        if i == 0:
            fail_tool(conn, fx, i, attempt_no=2, job_fence=fences[e["effect_id"]])
        else:
            succeed_tool(conn, fx, i, attempt_no=2, job_fence=fences[e["effect_id"]])
    bad = one(conn,
              "SELECT count(*) FROM effect_requests er"
              " JOIN LATERAL (SELECT * FROM effect_attempts a"
              "   WHERE a.effect_id = er.effect_id"
              "   ORDER BY attempt_no DESC LIMIT 1) a ON true"
              " WHERE er.session_id = %s"
              "   AND (er.status <> a.status OR er.attempt_no <> a.attempt_no"
              "    OR er.current_job_fence <> a.dispatch_job_fence"
              "    OR er.session_fence <> a.session_fence"
              "    OR er.dispatch_session_fence <> a.dispatch_session_fence)",
              (fx["session"],))[0]
    check("parent execution snapshot == current max attempt authority row",
          bad == 0, bad)


# ---------------------------------------------------------------------------
# 15b. retry_effect from the CLAIMED entry (lease held -> revoked on leave)
# ---------------------------------------------------------------------------

def test_retry_from_claimed(conn) -> None:
    fx = decision_fx(conn, retry_class="verifiable_no_effect", max_attempts=3)
    fail_decision(conn, fx)
    r1 = claim_session(conn, fx["session"], DRIVER, lease_owner="coord",
                       lease_seconds=60)
    check("claim over the rule-5 ready state", r1["outcome"] == "claimed", r1)
    rr = retry(conn, fx, fence=r1["session_fence"])
    check("retry from claimed accepted", rr["outcome"] == "accepted", rr)
    sess = one(conn, "SELECT state, session_fence, lease_owner FROM sessions"
                     " WHERE session_id=%s", (fx["session"],))
    check("leaving claimed revokes the lease and bumps the fence",
          sess[0] == "waiting_effect" and sess[1] == r1["session_fence"] + 1
          and sess[2] is None, sess)
    att = attempt_rows(conn, fx["effect"])
    check("new attempt froze the claim-era fence",
          att[1][8] == r1["session_fence"]
          and att[1][9] == r1["session_fence"], att)
    check("post-allocation target waiting_effect both layers",
          step_row(conn, fx["step"])[0] == "waiting_effect")


# ---------------------------------------------------------------------------
# 16. Chaos: allocation transaction killed before commit, rerun converges
# ---------------------------------------------------------------------------

def test_chaos_kill_allocation(conn) -> None:
    fx = tools_fx(conn, [("verifiable_no_effect", 3),
                   ("verifiable_no_effect", 3)])
    fail_tool(conn, fx, 0)
    fail_tool(conn, fx, 1)
    check("chaos fixture: rule 5",
          step_row(conn, fx["step"])[0] == "failed_retryable")

    real = psycopg2.connect(uri())
    dying = DyingConnection(real)
    try:
        retry_effect(dying, fx["session"], f"rty-{u()[:8]}",
                     fx["effects"][0]["effect_id"], DRIVER, EPOCH,
                     fx["post_seal_fence"])
        check("dying allocation raised ProcessDeath", False, "committed")
    except ProcessDeath:
        check("dying allocation raised ProcessDeath", True)
    finally:
        real.close()

    # The killed transaction rolled back whole: no allocation, no
    # superseded markers, no ready effects, step still failed_retryable.
    check("kill rollback: attempts unchanged (1 per effect)",
          sorted(r[0] for r in rows(
              conn, "SELECT count(*) FROM effect_attempts a"
                    " WHERE a.effect_id IN (SELECT effect_id"
                    " FROM effect_requests WHERE batch_id=%s)"
                    " GROUP BY a.effect_id",
              (fx["batch_id"],))) == [1, 1])
    check("kill rollback: no superseded markers",
          one(conn, "SELECT count(*) FROM effect_attempts"
                    " WHERE session_id=%s"
                    " AND superseded_by_attempt_no IS NOT NULL",
              (fx["session"],))[0] == 0)
    check("kill rollback: step keeps failed_retryable",
          step_row(conn, fx["step"])[0] == "failed_retryable")

    # Rerun with a fresh process: converges to exactly one new attempt per
    # member (PK + UNIQUE(effect_id, dispatch_job_fence) collapse the
    # rerun; the burned sequence values only skip fence numbers).
    rr = retry(conn, fx)
    check("rerun allocates the cohort", rr["outcome"] == "accepted", rr)
    for e in fx["effects"]:
        att = attempt_rows(conn, e["effect_id"])
        check(f"converged: exactly attempts 1,2 for {e['effect_id'][:8]}",
              [a[0] for a in att] == [1, 2] and att[0][2] == 2
              and att[1][2] is None, att)
        check("fence uniqueness holds (distinct dispatch fences)",
              att[0][3] != att[1][3], att)
    dup = one(conn,
              "SELECT count(*) FROM (SELECT effect_id, dispatch_job_fence"
              "   FROM effect_attempts WHERE session_id=%s"
              "   GROUP BY effect_id, dispatch_job_fence"
              "   HAVING count(*) > 1) d", (fx["session"],))[0]
    check("UNIQUE(effect_id, dispatch_job_fence) convergence", dup == 0, dup)
    check("step/session waiting_effect after the rerun",
          step_row(conn, fx["step"])[0] == "waiting_effect"
          and session_row(conn, fx["session"])[0] == "waiting_effect")


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def main() -> int:
    check("setup", setup_db() == 0)
    conn = psycopg2.connect(uri())
    try:
        test_conformance5_decision_table(conn)
        test_rule5_settlement(conn)
        test_budget_first_attempt(conn)
        test_unsafe_with_budget(conn)
        test_budget_multi_attempt(conn)
        test_pure_budget_batch(conn)
        test_rule4_residual_closure(conn)
        test_cohort_allocation(conn)
        test_success_with_failure_sibling(conn)
        test_sibling_blockers(conn)
        test_retry_guards(conn)
        test_late_completion_after_retry(conn)
        test_outcome_mismatch_on_failure(conn)
        test_stop_reason_unit(conn)
        test_retry_eligible_unit(conn)
        test_immutability(conn)
        test_dual_table_consistency(conn)
        test_retry_from_claimed(conn)
        test_chaos_kill_allocation(conn)
    finally:
        conn.close()
    print("[G7a] all gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
