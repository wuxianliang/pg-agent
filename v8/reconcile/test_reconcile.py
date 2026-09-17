"""G18 gate: v8 reconcile — the §3.1.1 driver-switch positive protocol
(begin_switch / finish_switch) and the §3.3 fork full surface.

Plan docs/plans/v8-remaining-milestones-plan-2026-09-16.md G18 D1–D14.
Conformance 11 (a) fork assertions, (b) the positive switch cycle, (c) the
mandatory UNSUPPORTED negative.

Run: uv run python v8/reconcile/test_reconcile.py  (exit 0 = pass)
"""
from __future__ import annotations

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
    finish_session,
    prepare_step,
    recovery_claim_session,
)
from v8.events.client import build_entry, call_append_events, create_session
from v8.grant.fixtures import u
from v8.reconcile.fixtures import (
    declare_capability,
    reconcile,
    switch_intent_identity,
)
from v8.reconcile.setup_db import DB, main as setup_db
from v8.repair.client import repair
from v8.retry.client import recovery_takeover
from v8.retry.test_retry import (
    DRIVER,
    EPOCH,
    check,
    fail_evidence,
    good_evidence,
    one,
    session_row,
    step_row,
    tools_fx,
)
from v8.tools.client import complete_tool_effect

SV, CV = "sv@1", "canon@1"
TARGET = "drv2"
ORD = 9_000_000


def _uri() -> str:
    return get_server().get_uri(DB)


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


def set_quiescing(conn, session_id):
    exec_sql(conn, "UPDATE sessions SET driver_mode='quiescing'"
                   " WHERE session_id=%s", (session_id,))


def expire_session_lease(conn, session_id):
    exec_sql(conn, "UPDATE sessions SET lease_until=now()"
                   " - interval '10 seconds' WHERE session_id=%s",
             (session_id,))


def next_seq(conn, s) -> int:
    return one(conn, "SELECT next_seq FROM sessions WHERE session_id=%s",
               (s,))[0]


def append(conn, s, entry, driver=DRIVER, epoch=EPOCH, cmd=None):
    return call_append_events(conn, s, cmd or f"ap-{u()[:8]}", driver,
                              epoch, next_seq(conn, s), [entry])


def semantic_entry(event_type: str, turn, payload, ordinal: int):
    return build_entry(event_type, payload, schema_version=SV,
                       canonicalizer_version=CV, turn_id=turn,
                       semantic_input_ordinal=ordinal)


def heartbeat_entry(payload):
    return build_entry("session/heartbeat", payload, schema_version=SV,
                       canonicalizer_version=CV)


def fx_session(conn, driver: str = DRIVER) -> tuple[str, int]:
    """Fresh session claimed by the operator (the switch caller)."""
    s = u()
    create_session(conn, s, driver)
    r = claim_session(conn, s, driver, lease_owner="op")
    check("fx claim ok", r["outcome"] == "claimed", r)
    return s, r["session_fence"]


def begin(conn, s, fence, owner="op", target=TARGET, driver=DRIVER,
          epoch=EPOCH, mode="active", cmd=None):
    return reconcile(conn, s, cmd or f"bsw-{u()[:8]}", "begin_switch",
                     driver=driver, driver_epoch=epoch, expected_mode=mode,
                     session_fence=fence, lease_owner=owner,
                     target_driver=target)


def finish(conn, s, fence, owner="rec", driver=DRIVER, epoch=EPOCH,
           mode="quiescing", cmd=None):
    return reconcile(conn, s, cmd or f"fsw-{u()[:8]}", "finish_switch",
                     driver=driver, driver_epoch=epoch, expected_mode=mode,
                     session_fence=fence, lease_owner=owner)


def recover(conn, s, owner="rec", driver=DRIVER, epoch=EPOCH) -> int:
    r = recovery_claim_session(conn, s, driver, epoch, owner, 60)
    check("fx recovery claim ok", r["outcome"] == "claimed", r)
    return r["session_fence"]


def begin_current(conn, s, owner="rec-g", target=TARGET, driver=DRIVER,
                  mode="active", cmd=None):
    """begin_switch carrying the CURRENT CAS legs; takes a recovery claim
    first when the lease slot is vacant (the seal paths revoke the
    coordination lease when leaving claimed)."""
    fence, lease = one(
        conn, "SELECT session_fence, lease_owner FROM sessions"
              " WHERE session_id=%s", (s,))
    if lease is None:
        r = recovery_claim_session(conn, s, driver, EPOCH, owner, 60)
        check("fx reclaim ok", r["outcome"] == "claimed", r)
        fence = r["session_fence"]
    return begin(conn, s, fence, owner=owner, target=target, driver=driver,
                 mode=mode, cmd=cmd)


def seal_only_fx(conn, driver: str = DRIVER):
    """create -> claim -> initial decision seal (the effect stays `ready`,
    undispatched) — the begin_switch guard (iii) fixture."""
    s = u()
    turn, step, eff = u(), u(), u()
    rh, ik = f"rh-{u()[:10]}", f"ik-{u()[:10]}"
    create_session(conn, s, driver)
    r0 = claim_session(conn, s, driver, lease_owner="op")
    rs = prepare_step(conn, s, f"seal-{u()[:8]}", driver, EPOCH,
                      r0["session_fence"], step, turn, eff,
                      request_hash=rh, idempotency_key=ik)
    check("fx seal accepted", rs["outcome"] == "accepted", rs)
    return {"session": s, "turn": turn, "step": step, "effect": eff,
            "rh": rh, "ik": ik, "claim_fence": r0["session_fence"],
            "seal_fence": rs["receipt"]["session_fence"],
            "job_fence": rs["receipt"]["job_fence"]}


def ready_decision_fx(conn, driver: str = DRIVER):
    """A decision completing with a tools plan — the step lands
    ready, stage=decision (the guard (i) fixture: an unsealed plan)."""
    fx = seal_only_fx(conn, driver)
    dispatch_effect(conn, fx["session"], f"dsp-{u()[:8]}", fx["effect"],
                    driver, EPOCH, fx["seal_fence"], fx["job_fence"])
    complete_effect(conn, fx["session"], f"cmp-{u()[:8]}", fx["effect"],
                    driver, EPOCH, dispatch_session_fence=2,
                    job_fence=fx["job_fence"], step_id=fx["step"],
                    request_hash=fx["rh"], idempotency_key=fx["ik"],
                    outcome="succeeded", message={"text": "plan"},
                    tools=[{"tool_call_id": f"c-{u()[:6]}", "tool": "fake_tool",
                            "arguments": {}}],
                    decision_only=False, final_tools=True,
                    evidence=good_evidence())
    return fx


def unknown_decision_fx(conn, driver: str = DRIVER):
    """A decision effect settling unknown_outcome — the guard (iv) fixture
    (blocked_unknown_effect, stage=decision) and the fork-cutoff fixture."""
    fx = seal_only_fx(conn, driver)
    dispatch_effect(conn, fx["session"], f"dsp-{u()[:8]}", fx["effect"],
                    driver, EPOCH, fx["seal_fence"], fx["job_fence"])
    complete_effect(conn, fx["session"], f"cmp-{u()[:8]}", fx["effect"],
                    driver, EPOCH, dispatch_session_fence=2,
                    job_fence=fx["job_fence"], step_id=fx["step"],
                    request_hash=fx["rh"], idempotency_key=fx["ik"],
                    outcome="failed_retryable", message={"text": ""},
                    tools=[], decision_only=True, final_tools=False,
                    evidence={"class": "garbled"})
    return fx


def repair_unknown(conn, fx, *, decision_only=True, tool_call_id=None,
                   output=None):
    head = one(conn, "SELECT head_event_key FROM turn_end_slots"
                     " WHERE session_id=%s", (fx["session"],))[0]
    kw = {}
    if tool_call_id is not None:
        kw = {"tool_call_id": tool_call_id,
              "output": output if output is not None else {"ok": 1}}
    return repair(conn, fx["session"], f"rpr-{u()[:8]}", fx["effect"], 1,
                  driver=DRIVER, driver_epoch=1,
                  supersedes_event_key=head, evidence=good_evidence(),
                  resolution_kind="succeeded",
                  message={"text": "repaired"}, tools=[],
                  decision_only=decision_only, final_tools=not decision_only,
                  **kw)


def switch_ready_session(conn):
    """A claimed quiescing-free session with the capability declared and no
    work — the clean positive-switch fixture. Returns (session, fence)."""
    declare_capability(conn, DRIVER, "supported")
    s, fence = fx_session(conn)
    return s, fence


# ---------------------------------------------------------------------------
# D1: the switch-intent companion table + the sessions column closure
# ---------------------------------------------------------------------------

def test_intent_table(conn) -> None:
    cols = rows(conn, "SELECT column_name FROM information_schema.columns"
                      " WHERE table_name='sessions' ORDER BY ordinal_position")
    names = [c[0] for c in cols]
    check("sessions keeps the frozen closed column list (no switch column)",
          all(n not in names for n in
              ("switch_intent", "switch_identity", "target_driver",
               "fork_depth", "parent_session_id")), names)
    intent_cols = rows(
        conn, "SELECT column_name FROM information_schema.columns"
              " WHERE table_name='session_switch_intents'"
              " ORDER BY ordinal_position")
    inames = [c[0] for c in intent_cols]
    check("session_switch_intents carries the frozen columns",
          inames == ["session_id", "switch_identity", "target_driver",
                     "created_session_fence", "created_driver",
                     "created_driver_epoch", "created_by_command_id",
                     "created_at"], inames)
    cap_cols = rows(
        conn, "SELECT column_name FROM information_schema.columns"
              " WHERE table_name='driver_switch_capabilities'"
              " ORDER BY ordinal_position")
    check("driver_switch_capabilities table exists",
          [c[0] for c in cap_cols] == ["driver", "switch_capability",
                                       "declared_at"], cap_cols)
    # Created-immutable: an UPDATE is a database-level violation.
    declare_capability(conn, "drv-imm", "unsupported")
    try:
        exec_sql(conn, "UPDATE driver_switch_capabilities"
                       " SET switch_capability='supported'"
                       " WHERE driver='drv-imm'")
        immutable = False
    except psycopg2.Error:
        conn.rollback()
        immutable = True
    check("capability declaration is created-immutable", immutable)


# ---------------------------------------------------------------------------
# D2: the unified entry — envelope CAS, replay, unknown action
# ---------------------------------------------------------------------------

def test_entry_contract(conn) -> None:
    s, fence = switch_ready_session(conn)

    r = begin(conn, s, fence, owner="op", epoch=2)
    check("envelope epoch mismatch -> rejected_stale/DRIVER_EPOCH_STALE",
          r["outcome"] == "rejected_stale"
          and r["code"] == "DRIVER_EPOCH_STALE", r)
    check("envelope mismatch leaves zero control state",
          one(conn, "SELECT driver_mode, session_fence, lease_owner"
                    " FROM sessions WHERE session_id=%s", (s,))
          == ("active", fence, "op"))

    r = begin(conn, s, fence, owner="nobody")
    check("missing lease -> rejected_stale/NO_VALID_LEASE",
          r["outcome"] == "rejected_stale" and r["code"] == "NO_VALID_LEASE",
          r)

    r = reconcile(conn, s, f"rcn-{u()[:8]}", "abort_switch", driver=DRIVER,
                  driver_epoch=EPOCH, expected_mode="active",
                  session_fence=fence, lease_owner="op")
    check("unknown action -> rejected_mismatch/UNKNOWN_ACTION",
          r["outcome"] == "rejected_mismatch"
          and r["code"] == "UNKNOWN_ACTION", r)

    cmd = f"bsw-{u()[:8]}"
    r1 = begin(conn, s, fence, owner="op", cmd=cmd)
    check("clean begin accepted", r1["outcome"] == "accepted", r1)
    r2 = reconcile(conn, s, cmd, "begin_switch", driver=DRIVER,
                   driver_epoch=EPOCH, expected_mode="active",
                   session_fence=fence, lease_owner="op",
                   target_driver=TARGET)
    check("same command_id replays the original receipt idempotently",
          r2["outcome"] == "accepted"
          and r2["receipt"]["switch_identity"]
          == r1["receipt"]["switch_identity"], r2)
    check("replay did not execute twice (one intent row, fence advanced once)",
          one(conn, "SELECT count(*) FROM session_switch_intents"
                    " WHERE session_id=%s", (s,))[0] == 1
          and one(conn, "SELECT session_fence FROM sessions"
                        " WHERE session_id=%s", (s,))[0] == fence + 1)


# ---------------------------------------------------------------------------
# D3: the four safety guards (each fixture -> stable SWITCH_DEFERRED)
# ---------------------------------------------------------------------------

def test_guards(conn) -> None:
    declare_capability(conn, DRIVER, "supported")

    # (iii): an undispatched ready decision effect; then the clearing chain
    # (iii) -> dispatch -> (ii) -> decision_only completion -> success.
    fx = seal_only_fx(conn)
    r = begin_current(conn, fx["session"])
    check("guard (iii): undispatched ready effect -> SWITCH_DEFERRED",
          r["outcome"] == "rejected_mismatch"
          and r["code"] == "SWITCH_DEFERRED"
          and "guard (iii)" in r["receipt"]["detail"], r)
    before = one(conn, "SELECT driver_mode, session_fence, lease_owner"
                       " FROM sessions WHERE session_id=%s", (fx["session"],))
    r_again = begin_current(conn, fx["session"])
    check("guard (iii) deferral is stable on re-issue",
          r_again["outcome"] == "rejected_mismatch"
          and r_again["code"] == "SWITCH_DEFERRED", r_again)
    check("guard refusal: mode/fence/lease/intent untouched",
          one(conn, "SELECT driver_mode, session_fence, lease_owner"
                    " FROM sessions WHERE session_id=%s",
              (fx["session"],)) == before
          and one(conn, "SELECT count(*) FROM session_switch_intents"
                        " WHERE session_id=%s", (fx["session"],))[0] == 0)

    cur_fence = one(conn, "SELECT session_fence FROM sessions"
                           " WHERE session_id=%s", (fx["session"],))[0]
    dispatch_effect(conn, fx["session"], f"dsp-{u()[:8]}", fx["effect"],
                    DRIVER, EPOCH, cur_fence, fx["job_fence"])
    r = begin_current(conn, fx["session"])
    check("guard (ii): in-flight decision effect -> SWITCH_DEFERRED",
          r["outcome"] == "rejected_mismatch"
          and "guard (ii)" in r["receipt"]["detail"], r)

    complete_effect(conn, fx["session"], f"cmp-{u()[:8]}", fx["effect"],
                    DRIVER, EPOCH, dispatch_session_fence=2,
                    job_fence=fx["job_fence"], step_id=fx["step"],
                    request_hash=fx["rh"], idempotency_key=fx["ik"],
                    outcome="succeeded", message={"text": "done"},
                    tools=[], decision_only=True, final_tools=False,
                    evidence=good_evidence())
    r = begin_current(conn, fx["session"])
    check("guards cleared by completion -> begin accepted",
          r["outcome"] == "accepted", r)

    # (i): a step ready, stage=decision (an unsealed tools plan).
    fx1 = ready_decision_fx(conn)
    r = begin_current(conn, fx1["session"])
    check("guard (i): unsealed tools plan -> SWITCH_DEFERRED",
          r["outcome"] == "rejected_mismatch"
          and "guard (i)" in r["receipt"]["detail"], r)

    # (iv): a blocked_unknown_effect decision step.
    fx4 = unknown_decision_fx(conn)
    r = begin_current(conn, fx4["session"])
    check("guard (iv): blocked_unknown decision step -> SWITCH_DEFERRED",
          r["outcome"] == "rejected_mismatch"
          and "guard (iv)" in r["receipt"]["detail"], r)


# ---------------------------------------------------------------------------
# D4: the begin success transaction — identity, fence, lease, job lease
# ---------------------------------------------------------------------------

def test_begin_effects(conn) -> None:
    s, fence = switch_ready_session(conn)
    identity_golden = switch_intent_identity(s, TARGET, fence)
    r = begin(conn, s, fence, owner="op")
    check("begin accepted", r["outcome"] == "accepted", r)
    check("the persisted switch identity equals the standalone hashlib"
          " golden vector",
          r["receipt"]["switch_identity"] == identity_golden, r["receipt"])
    row = one(conn, "SELECT switch_identity, target_driver,"
                    " created_session_fence, created_driver,"
                    " created_driver_epoch FROM session_switch_intents"
                    " WHERE session_id=%s", (s,))
    check("intent row persists the create-time CAS snapshot",
          row == (identity_golden, TARGET, fence, DRIVER, EPOCH), row)
    check("session_fence+1, coordination lease revoked, mode=quiescing",
          one(conn, "SELECT session_fence, lease_owner, lease_until,"
                    " driver_mode FROM sessions WHERE session_id=%s", (s,))
          == (fence + 1, None, None, "quiescing"))
    check("session business state kept (not reset)",
          one(conn, "SELECT state FROM sessions WHERE session_id=%s",
              (s,))[0] == "claimed")

    # The job lease of an in-flight tools effect survives begin (D4: MUST
    # NOT auto-revoke a valid job lease). Tools stage in flight is
    # begin-compatible (guards (i)/(ii) are decision-stage only).
    fx = tools_fx(conn, [("verifiable_no_effect", 3)])
    exec_sql(conn, "UPDATE effect_requests SET lease_owner='w1',"
                   " lease_until=now() + interval '5 minutes'"
                   " WHERE effect_id=%s", (fx["effects"][0]["effect_id"],))
    r = begin_current(conn, fx["session"])
    check("tools-stage in-flight work does not defer the switch",
          r["outcome"] == "accepted", r)
    check("begin does NOT revoke the valid job lease",
          one(conn, "SELECT lease_owner, lease_until > now()"
                    " FROM effect_requests WHERE effect_id=%s",
               (fx["effects"][0]["effect_id"],)) == ("w1", True))


# ---------------------------------------------------------------------------
# D5: the quiescing rejection closed set + the observation exceptions
# ---------------------------------------------------------------------------

def test_quiescing_closed_set(conn) -> None:
    declare_capability(conn, DRIVER, "supported")
    # A tools effect in flight, then the switch.
    fx = tools_fx(conn, [("verifiable_no_effect", 3)])
    eff = fx["effects"][0]
    r = begin_current(conn, fx["session"])
    check("switch entered over tools work", r["outcome"] == "accepted", r)
    qf = r["receipt"]["session_fence"]

    # Semantic input append is rejected; the observation heartbeat is
    # accepted — including the OLD epoch (recorded mismatch, L4-U03).
    rj = append(conn, fx["session"],
                semantic_entry("user/message", fx["turn"], {"text": "hi"},
                               ORD + 1))
    check("semantic input append under quiescing -> DRIVER_QUIESCING",
          rj["outcome"] == "rejected_mismatch"
          and rj["code"] == "DRIVER_QUIESCING", rj)

    rh = append(conn, fx["session"], heartbeat_entry({"beat": 1}))
    check("session/heartbeat under quiescing accepted (matching epoch)",
          rh["outcome"] == "accepted", rh)
    rh2 = append(conn, fx["session"], heartbeat_entry({"beat": 2}),
                 epoch=99)
    check("OLD-epoch session/heartbeat under quiescing accepted,"
          " mismatch recorded (L4-U03)",
          rh2["outcome"] == "accepted"
          and rh2["receipt"].get("epoch_mismatch_recorded") is True
          and rh2["receipt"].get("submitted_driver_epoch") == 99, rh2)
    check("heartbeat did not advance fence/lease (zero control state)",
          one(conn, "SELECT session_fence, lease_owner FROM sessions"
                    " WHERE session_id=%s", (fx["session"],))
          == (qf, None))

    # The active-state old-epoch heartbeat stays a standard rejection.
    fx_a = seal_only_fx(conn)
    rh3 = append(conn, fx_a["session"], heartbeat_entry({"beat": 3}),
                 epoch=7)
    check("active-state old-epoch heartbeat -> DRIVER_EPOCH_STALE",
          rh3["outcome"] == "rejected_stale"
          and rh3["code"] == "DRIVER_EPOCH_STALE", rh3)

    # stream_progress (the non-terminal stream observation) passes its own
    # five gates — quiescing is not one of them. The tools effect is
    # non-streaming, so the gates reject it on the stream applicability
    # ground (not on quiescing): the five gates remain the only judge.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT outcome, code FROM v_stream_observe("
            "%s::uuid, %s, %s::uuid, 1, '{\"stream_complete\":false}',"
            " 'sv@1', 'canon@1', %s)",
            (fx["session"], f"obs-{u()[:8]}", eff["effect_id"], u()[:12]))
        oo, oc = cur.fetchone()
    conn.commit()
    check("stream_progress under quiescing judged by its own gates"
          " (quiescing is not one of them)",
          oo == "accepted" and oc is None, (oo, oc))

    # Terminal completion of the in-flight effect is refused (W01).
    rt = complete_tool_effect(
        conn, fx["session"], f"cmp-{u()[:8]}", eff["effect_id"], DRIVER,
        EPOCH, dispatch_session_fence=fx["seal_fence"],
        job_fence=eff["job_fence"], attempt_no=1, step_id=fx["step"],
        request_hash=eff["request_hash"],
        idempotency_key=eff["idempotency_key"], outcome="succeeded",
        tool_call_id=eff["tool_call_id"], output={"ok": 1},
        evidence=good_evidence())
    check("terminal completion under quiescing -> DRIVER_QUIESCING",
          rt["outcome"] == "rejected_mismatch"
          and rt["code"] == "DRIVER_QUIESCING", rt)

    # The remaining closed-set members on separate quiescing fixtures.
    s2, f2 = fx_session(conn)
    set_quiescing(conn, s2)
    rc = claim_session(conn, s2, DRIVER)
    check("normal claim under quiescing -> DRIVER_QUIESCING",
          rc["outcome"] == "rejected_mismatch"
          and rc["code"] == "DRIVER_QUIESCING", rc)
    rfin = finish_session(conn, s2, f"fin-{u()[:8]}", DRIVER, EPOCH, f2)
    check("finish_session under quiescing -> DRIVER_QUIESCING",
          rfin["outcome"] == "rejected_mismatch"
          and rfin["code"] == "DRIVER_QUIESCING", rfin)
    fx3 = seal_only_fx(conn)
    set_quiescing(conn, fx3["session"])
    rdisp = dispatch_effect(conn, fx3["session"], f"dsp-{u()[:8]}",
                            fx3["effect"], DRIVER, EPOCH, fx3["seal_fence"],
                            fx3["job_fence"])
    check("dispatch under quiescing -> DRIVER_QUIESCING",
          rdisp["outcome"] == "rejected_mismatch"
          and rdisp["code"] == "DRIVER_QUIESCING", rdisp)
    fx4 = seal_only_fx(conn)
    set_quiescing(conn, fx4["session"])
    import hashlib as _hl
    _pc = "{}"
    _dh = _hl.sha256(_pc.encode()).hexdigest()
    rretry = None
    with conn.cursor() as cur:
        cur.execute(
            "SELECT outcome, code FROM v_retry_effect("
            "%s::uuid, %s, %s::uuid, %s, 1, %s, %s, %s)",
            (fx4["session"], f"rty-{u()[:8]}", fx4["effect"], DRIVER,
             fx4["seal_fence"], _dh, _pc))
        rretry = cur.fetchone()
    conn.commit()
    check("retry under quiescing -> DRIVER_QUIESCING",
          rretry == ("rejected_mismatch", "DRIVER_QUIESCING"), rretry)


# ---------------------------------------------------------------------------
# D6: A37 remaining leg — quiescing takeover known_failure controlled edge
# ---------------------------------------------------------------------------

def test_takeover_controlled_edge(conn) -> None:
    from v8.retry.test_retry import decision_fx
    fx = decision_fx(conn, retry_class="verifiable_no_effect",
                     max_attempts=3)
    set_quiescing(conn, fx["session"])
    exec_sql(conn, "UPDATE effect_requests SET lease_owner='w1',"
                   " lease_until=now() - interval '10 seconds'"
                   " WHERE effect_id=%s", (fx["effect"],))
    exec_sql(conn, "UPDATE sessions SET lease_until=now()"
                   " - interval '10 seconds' WHERE session_id=%s",
             (fx["session"],))
    recover(conn, fx["session"], owner="rec")
    r = recovery_takeover(
        conn, fx["session"], f"tko-{u()[:8]}", DRIVER, EPOCH,
        evidence={fx["effect"]: {
            "class": "known_failure",
            "provider_receipt": {"receipt_id": f"fr-{u()[:8]}"},
            "no_side_effect_proof": {"checked": True},
            "attempt_no": 1}})
    check("quiescing takeover with known_failure accepted (was structural"
          " DRIVER_QUIESCING before A37)",
          r["outcome"] == "accepted", r)
    tk = [a for a in r["receipt"]["attempts"]
          if a["disposition"] == "taken_over"]
    check("the known failure settled through the controlled edge",
          len(tk) == 1 and tk[0]["settled_status"] == "failed_terminal"
          and tk[0]["classification"] == "known_failure", tk)
    check("no new attempt was created (attempt count stays 1)",
          one(conn, "SELECT count(*) FROM effect_attempts"
                    " WHERE effect_id=%s", (fx["effect"],))[0] == 1)
    check("retry_stop_reason persisted (not_retry_eligible)",
          one(conn, "SELECT retry_stop_reason FROM effect_requests"
                    " WHERE effect_id=%s", (fx["effect"],))[0]
          == "not_retry_eligible")
    check("audit RETRY_STOPPED_BY_CLOSURE recorded",
          one(conn, "SELECT count(*) FROM effect_audit WHERE effect_id=%s"
                    " AND reason='RETRY_STOPPED_BY_CLOSURE'",
              (fx["effect"],))[0] == 1)
    check("rule-4 aggregation: step failed_terminal, session failed"
          " (identical to the (alpha) completion entry)",
          step_row(conn, fx["step"])[0] == "failed_terminal"
          and session_row(conn, fx["session"])[0] == "failed")

    # Same three-layer equality without quiescing: the (alpha) control.
    fxc = decision_fx(conn, retry_class="verifiable_no_effect",
                      max_attempts=1)
    complete_effect(conn, fxc["session"], f"cmp-{u()[:8]}", fxc["effect"],
                    DRIVER, EPOCH, dispatch_session_fence=2,
                    job_fence=fxc["job_fence"], step_id=fxc["step"],
                    request_hash=fxc["rh"], idempotency_key=fxc["ik"],
                    outcome="failed_retryable", message={"text": ""},
                    tools=[], decision_only=True, final_tools=False,
                    evidence=fail_evidence())
    check("(alpha) control: max_attempts=1 terminal failure -> same"
          " step/session layer",
          step_row(conn, fxc["step"])[0] == "failed_terminal"
          and session_row(conn, fxc["session"])[0] == "failed")


# ---------------------------------------------------------------------------
# D7: the finish_switch CAS barrier + the one-shot epoch advance
# ---------------------------------------------------------------------------

def test_finish_barrier(conn) -> None:
    declare_capability(conn, DRIVER, "supported")
    declare_capability(conn, TARGET, "supported")
    # Non-terminal effect blocks; unknown blocks; job lease blocks; each
    # keeps the session quiescing with zero mutation.
    fx = tools_fx(conn, [("verifiable_no_effect", 3)])
    eff = fx["effects"][0]
    r = begin_current(conn, fx["session"])
    check("switch entered", r["outcome"] == "accepted", r)

    rf = recover(conn, fx["session"], owner="rec")
    r1 = finish(conn, fx["session"], rf)
    check("barrier: non-terminal effect -> SWITCH_DEFERRED, still quiescing",
          r1["outcome"] == "rejected_mismatch"
          and r1["code"] == "SWITCH_DEFERRED"
          and one(conn, "SELECT driver_mode FROM sessions"
                        " WHERE session_id=%s", (fx["session"],))[0]
          == "quiescing", r1)

    # Settle the effect unknown (the quiescing terminal completion is
    # refused, so the unknown settles through the takeover branch with an
    # expired job lease).
    exec_sql(conn, "UPDATE effect_requests SET lease_owner='w1',"
                   " lease_until=now() - interval '10 seconds'"
                   " WHERE effect_id=%s", (eff["effect_id"],))
    exec_sql(conn, "UPDATE sessions SET lease_until=now()"
                   " - interval '10 seconds' WHERE session_id=%s",
             (fx["session"],))
    rf2 = recover(conn, fx["session"], owner="rec2")
    rtk = recovery_takeover(conn, fx["session"], f"tko-{u()[:8]}", DRIVER,
                            EPOCH, evidence=None)
    check("quiescing takeover unknown settles unknown_outcome",
          rtk["outcome"] == "accepted"
          and one(conn, "SELECT status FROM effect_requests"
                        " WHERE effect_id=%s",
                  (eff["effect_id"],))[0] == "unknown_outcome", rtk)

    r2 = finish(conn, fx["session"], rf2, owner="rec2")
    check("barrier: unresolved unknown -> SWITCH_DEFERRED",
          r2["outcome"] == "rejected_mismatch"
          and "unresolved unknown" in r2["receipt"]["detail"], r2)

    # Repair the unknown to success.
    rrep = repair_unknown(conn, {"session": fx["session"],
                                 "effect": eff["effect_id"]},
                          decision_only=False,
                          tool_call_id=eff["tool_call_id"],
                          output={"ok": 1})
    check("fixture: repair of the tools unknown accepted",
          rrep["outcome"] == "accepted", rrep)

    # A valid old job lease blocks the barrier.
    exec_sql(conn, "UPDATE effect_requests SET lease_owner='w2',"
                   " lease_until=now() + interval '5 minutes'"
                   " WHERE effect_id=%s", (eff["effect_id"],))
    expire_session_lease(conn, fx["session"])
    rf3 = recover(conn, fx["session"], owner="rec3")
    r3 = finish(conn, fx["session"], rf3, owner="rec3")
    check("barrier: valid old job lease -> SWITCH_DEFERRED",
          r3["outcome"] == "rejected_mismatch"
          and "job lease" in r3["receipt"]["detail"], r3)
    exec_sql(conn, "UPDATE effect_requests SET lease_until=now()"
                   " - interval '10 seconds' WHERE effect_id=%s",
             (eff["effect_id"],))

    # active_step_id pointing at a non-terminal step blocks the barrier
    # (a fresh waiting step from a separate fixture).
    fx_hold = seal_only_fx(conn)
    expire_session_lease(conn, fx["session"])
    rf4 = recover(conn, fx["session"], owner="rec4")
    exec_sql(conn, "UPDATE sessions SET active_step_id=%s"
                   " WHERE session_id=%s", (fx_hold["step"], fx["session"]))
    r4 = finish(conn, fx["session"], rf4, owner="rec4")
    check("barrier: non-terminal active_step_id -> SWITCH_DEFERRED",
          r4["outcome"] == "rejected_mismatch", r4)
    exec_sql(conn, "UPDATE sessions SET active_step_id=NULL"
                   " WHERE session_id=%s", (fx["session"],))

    expire_session_lease(conn, fx["session"])
    expire_session_lease(conn, fx["session"])
    rf5 = recover(conn, fx["session"], owner="rec5")
    state_before = one(conn, "SELECT state, failure_code FROM sessions"
                             " WHERE session_id=%s", (fx["session"],))
    r5 = finish(conn, fx["session"], rf5, owner="rec5")
    check("barrier met -> finish accepted",
          r5["outcome"] == "accepted", r5)
    check("finish keeps the business state it found (no unconditional"
          " reset)",
          one(conn, "SELECT state, failure_code FROM sessions"
                    " WHERE session_id=%s", (fx["session"],)) == state_before,
          (state_before,))
    check("one-shot: driver=target, epoch+1, fence+1, lease cleared,"
          " mode=active",
          one(conn, "SELECT driver, driver_epoch, driver_mode,"
                    " session_fence, lease_owner FROM sessions"
                    " WHERE session_id=%s", (fx["session"],))
          == (TARGET, 2, "active", rf5 + 1, None))
    check("switch intent cleared in the same transaction",
          one(conn, "SELECT count(*) FROM session_switch_intents"
                    " WHERE session_id=%s", (fx["session"],))[0] == 0)

    # finish without an intent is a stable rejection (the switch already
    # completed: the session now runs the target driver at epoch 2).
    expire_session_lease(conn, fx["session"])
    recover(conn, fx["session"], owner="rec6", driver=TARGET, epoch=2)
    rf6 = one(conn, "SELECT session_fence FROM sessions"
                    " WHERE session_id=%s", (fx["session"],))[0]
    r6 = finish(conn, fx["session"], rf6, owner="rec6", driver=TARGET,
                epoch=2, mode="active")
    check("finish without a switch intent -> SWITCH_INTENT_MISSING",
          r6["outcome"] == "rejected_mismatch"
          and r6["code"] == "SWITCH_INTENT_MISSING", r6)

    # A second begin while an intent exists -> SWITCH_IN_PROGRESS.
    s, f = switch_ready_session(conn)
    begin(conn, s, f)
    rf7 = recover(conn, s, owner="rec7")
    r7 = begin(conn, s, rf7, owner="rec7", mode="quiescing")
    check("second begin while an intent exists -> SWITCH_IN_PROGRESS",
          r7["outcome"] == "rejected_mismatch"
          and r7["code"] == "SWITCH_IN_PROGRESS", r7)


def test_finish_terminal_variant(conn) -> None:
    """Terminal matrix (d): a terminal session with a switch intent keeps
    its business terminal state through a restricted finish_switch."""
    s, f = switch_ready_session(conn)
    r = begin(conn, s, f)
    check("switch entered", r["outcome"] == "accepted", r)
    # The session fails terminally while quiescing (constructed state: the
    # rule-4 aggregation path is exercised in D6; here the control row
    # carries the terminal fact).
    exec_sql(conn, "UPDATE sessions SET state='failed',"
                   " failure_code='FAILED_TERMINAL'"
                   " WHERE session_id=%s", (s,))
    rf = recover(conn, s, owner="rec-t")
    rt = finish(conn, s, rf, owner="rec-t")
    check("terminal (d) finish accepted", rt["outcome"] == "accepted", rt)
    check("terminal (d): only mode/driver/epoch/ownership/fence changed",
          one(conn, "SELECT state, failure_code, driver, driver_epoch,"
                    " driver_mode, session_fence, lease_owner"
                    " FROM sessions WHERE session_id=%s", (s,))
          == ("failed", "FAILED_TERMINAL", TARGET, 2, "active", rf + 1,
              None))

    # Without an intent, a terminal session is NOT claimable ((e) row).
    s2 = u()
    create_session(conn, s2, DRIVER)
    exec_sql(conn, "UPDATE sessions SET state='failed',"
                   " failure_code='FAILED_TERMINAL'"
                   " WHERE session_id=%s", (s2,))
    rc = recovery_claim_session(conn, s2, DRIVER, EPOCH, "rec-x", 60)
    check("terminal session without an intent is NOT recovery-claimable",
          rc["outcome"] == "rejected_mismatch"
          and rc["code"] == "SESSION_TERMINAL", rc)

    # The GENERATION_REVOKED drain family is claimable (matrix (b) third
    # type).
    s3 = u()
    create_session(conn, s3, DRIVER)
    exec_sql(conn, "UPDATE sessions SET state='failed',"
                   " failure_code='GENERATION_REVOKED'"
                   " WHERE session_id=%s", (s3,))
    rc3 = recovery_claim_session(conn, s3, DRIVER, EPOCH, "rec-g", 60)
    check("GENERATION_REVOKED terminal session is recovery-claimable"
          " (matrix (b) third family)",
          rc3["outcome"] == "claimed", rc3)


# ---------------------------------------------------------------------------
# D8: post-switch stale-reject of old-epoch writes
# ---------------------------------------------------------------------------

def test_post_switch_stale(conn) -> None:
    s, f = switch_ready_session(conn)
    begin(conn, s, f)
    rf = recover(conn, s, owner="rec")
    cmd = f"fsw-{u()[:8]}"
    rfin = finish(conn, s, rf, cmd=cmd)
    check("switch completed", rfin["outcome"] == "accepted", rfin)

    rc = claim_session(conn, s, DRIVER, EPOCH, "old-coord")
    check("old-epoch claim stale-rejected",
          rc["outcome"] == "rejected_stale"
          and rc["code"] == "DRIVER_EPOCH_MISMATCH", rc)
    rc2 = recovery_claim_session(conn, s, TARGET, 2, "new-coord")
    check("new-epoch claim proceeds under the target identity",
          rc2["outcome"] == "claimed", rc2)
    ra = append(conn, s, semantic_entry("user/message", u(),
                                        {"text": "late"}, ORD + 2))
    check("old-epoch append stale-rejected (DRIVER_EPOCH_STALE)",
          ra["outcome"] == "rejected_stale"
          and ra["code"] == "DRIVER_EPOCH_STALE", ra)

    # Historical receipt reads are NOT new writes: the finish receipt
    # replays under the old epoch without re-checking the envelope.
    replay = reconcile(conn, s, cmd, "finish_switch", driver=DRIVER,
                       driver_epoch=EPOCH, expected_mode="quiescing",
                       session_fence=rf, lease_owner="rec")
    check("finish receipt replays idempotently after the epoch advance"
          " (history reads are not new writes)",
          replay["outcome"] == "accepted"
          and replay["receipt"]["switch_identity"]
          == rfin["receipt"]["switch_identity"], replay)


# ---------------------------------------------------------------------------
# D9 + D10: fork provenance + the inheritance matrix
# ---------------------------------------------------------------------------

def fork_session(conn, parent, through_seq, driver=None,
                 manifest="assembly-manifest@v1"):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM v_fork_session(%s::uuid, %s, %s, %s)",
                    (str(parent), through_seq, driver, manifest))
        out = cur.fetchone()[0]
    conn.commit()
    return out


def test_fork_surface(conn) -> None:
    fx = unknown_decision_fx(conn)
    repair_unknown(conn, fx)
    last = one(conn, "SELECT max(seq) FROM session_events"
                     " WHERE session_id=%s", (fx["session"],))[0]

    out = fork_session(conn, fx["session"], last)
    check("fork accepted", out["outcome"] == "accepted", out)
    child = out["child_session_id"]
    prov = one(conn, "SELECT parent_session_id, parent_through_seq,"
                     " fork_depth, manifest_version, inherited_event_count"
                     " FROM session_fork_provenance WHERE session_id=%s",
               (child,))
    check("provenance persists {session_id, seq}, depth, manifest and the"
          " cached count",
          prov == (fx["session"], last, 1, "assembly-manifest@v1",
                   out["inherited_event_count"]), prov)
    check("the cached count equals the child event rows (cache semantics)",
          one(conn, "SELECT count(*) FROM session_events"
                    " WHERE session_id=%s", (child,))[0] == prov[4])
    check("child control plane: epoch=1/fence=1/mode=active, no lease,"
          " no latch",
          one(conn, "SELECT driver_epoch, driver_mode, session_fence,"
                    " lease_owner, cancellation_epoch FROM sessions"
                    " WHERE session_id=%s", (child,))
          == (1, "active", 1, None, 0))
    check("no switch intent / job (effect) plane inherited by the child"
          " (a fresh child session row structurally cannot carry a"
          " compact lock)",
          one(conn, "SELECT count(*) FROM session_switch_intents"
                    " WHERE session_id=%s", (child,))[0] == 0
          and one(conn, "SELECT count(*) FROM effect_requests"
                        " WHERE session_id=%s", (child,))[0] == 0)
    check("child driver defaults to the parent driver",
          one(conn, "SELECT driver FROM sessions WHERE session_id=%s",
              (child,))[0] == DRIVER)

    # A grandchild fork: fork_depth accumulates; an explicit p_driver wins.
    last2 = one(conn, "SELECT max(seq) FROM session_events"
                      " WHERE session_id=%s", (child,))[0]
    out2 = fork_session(conn, child, last2, driver="alt-drv")
    check("grandchild accepted with the explicit driver",
          out2["outcome"] == "accepted"
          and one(conn, "SELECT driver FROM sessions"
                        " WHERE session_id=%s",
                  (out2["child_session_id"],))[0] == "alt-drv", out2)
    check("fork_depth accumulates (root -> 1 -> 2)",
          one(conn, "SELECT fork_depth FROM session_fork_provenance"
                    " WHERE session_id=%s", (out2["child_session_id"],))[0]
          == 2)

    # D10 switch interplay: a parent in quiescing (with an intent) still
    # forks; the parent's control state is untouched.
    sq, fq = switch_ready_session(conn)
    declare_capability(conn, TARGET, "supported")
    rb = begin(conn, sq, fq)
    check("switch entered on the fork parent", rb["outcome"] == "accepted",
          rb)
    append(conn, sq, heartbeat_entry({"beat": "pre-fork"}))
    before = one(conn, "SELECT driver_mode, session_fence, lease_owner,"
                       " state FROM sessions WHERE session_id=%s", (sq,))
    outf = fork_session(conn, sq, 1)
    check("fork from a quiescing parent with a switch intent accepted",
          outf["outcome"] == "accepted", outf)
    check("parent control state untouched by the fork (intent kept)",
          one(conn, "SELECT driver_mode, session_fence, lease_owner, state"
                    " FROM sessions WHERE session_id=%s", (sq,)) == before
          and one(conn, "SELECT count(*) FROM session_switch_intents"
                        " WHERE session_id=%s", (sq,))[0] == 1)


# ---------------------------------------------------------------------------
# D11 (a): Conformance 11 fork-cutoff three assertions (native command)
# ---------------------------------------------------------------------------

def test_fork_cutoff(conn) -> None:
    # Assertion 1: an unresolved unknown inside the cutoff -> reject.
    fx = unknown_decision_fx(conn)
    last = one(conn, "SELECT max(seq) FROM session_events"
                     " WHERE session_id=%s", (fx["session"],))[0]
    r1 = fork_session(conn, fx["session"], last)
    check("(a)1 unresolved unknown in the cutoff -> FORK_CUTOFF_UNSTABLE",
          r1["outcome"] == "rejected_mismatch"
          and r1["code"] == "FORK_CUTOFF_UNSTABLE", r1)

    # Assertion 3: the parent repaired AFTER the cutoff still rejects.
    provisional_seq = one(
        conn, "SELECT max(seq) FROM session_events WHERE session_id=%s"
              " AND event_type='turn/end'", (fx["session"],))[0]
    repair_unknown(conn, fx)
    r3 = fork_session(conn, fx["session"], provisional_seq)
    check("(a)3 cutoff before the parent repair -> FORK_CUTOFF_UNSTABLE"
          " (stability never borrows a post-cutoff resolution)",
          r3["outcome"] == "rejected_mismatch"
          and r3["code"] == "FORK_CUTOFF_UNSTABLE", r3)

    # Assertion 2: a fully repaired prefix forks and the child trace
    # carries the closer (no provisional unknown representation).
    last2 = one(conn, "SELECT max(seq) FROM session_events"
                      " WHERE session_id=%s", (fx["session"],))[0]
    r2 = fork_session(conn, fx["session"], last2)
    check("(a)2 repaired prefix forks", r2["outcome"] == "accepted", r2)
    child = r2["child_session_id"]
    closers = one(conn, "SELECT count(*) FROM session_events"
                        " WHERE session_id=%s"
                        " AND payload::jsonb->>'closer' = 'true'",
                  (child,))[0]
    check("(a)2 the child trace carries the closer (canonical replacement"
          " of the unknown marker)",
          closers == 1, closers)

    # Post-fork parent appends never change the child prefix.
    n_before = one(conn, "SELECT count(*) FROM session_events"
                         " WHERE session_id=%s", (child,))[0]
    append(conn, fx["session"],
           semantic_entry("user/message", u(), {"text": "after"}, ORD + 3))
    check("post-fork parent append leaves the child prefix fixed",
          one(conn, "SELECT count(*) FROM session_events"
                    " WHERE session_id=%s", (child,))[0] == n_before)


# ---------------------------------------------------------------------------
# D11 (b): the full positive switch cycle (Conformance 11 (b), DB layer)
# ---------------------------------------------------------------------------

def test_positive_cycle(conn) -> None:
    declare_capability(conn, DRIVER, "supported")
    declare_capability(conn, TARGET, "supported")
    s = u()
    create_session(conn, s, DRIVER)
    r0 = claim_session(conn, s, DRIVER, lease_owner="coordinator")
    fence = r0["session_fence"]
    r1 = begin(conn, s, fence, owner="coordinator")
    check("(b) begin accepted", r1["outcome"] == "accepted", r1)
    rf = recover(conn, s, owner="new-owner")
    r2 = finish(conn, s, rf, owner="new-owner")
    check("(b) finish accepted, epoch advanced",
          r2["outcome"] == "accepted"
          and r2["receipt"]["new_driver_epoch"] == 2, r2)
    # The old driver's writes are stale; the new driver proceeds.
    ro = claim_session(conn, s, DRIVER, EPOCH, "old")
    check("(b) old-driver claim rejected after the epoch advance",
          ro["outcome"] == "rejected_stale", ro)
    rn = recovery_claim_session(conn, s, TARGET, 2, "new-driver")
    check("(b) target-driver identity proceeds at epoch 2",
          rn["outcome"] == "claimed", rn)


# ---------------------------------------------------------------------------
# D11 (c): the mandatory UNSUPPORTED negative
# ---------------------------------------------------------------------------

def test_unsupported_negative(conn) -> None:
    declare_capability(conn, "drv-unsup", "unsupported")
    s = u()
    create_session(conn, s, "drv-unsup")
    r0 = claim_session(conn, s, "drv-unsup", lease_owner="op-u")
    r = begin(conn, s, r0["session_fence"], owner="op-u",
              driver="drv-unsup")
    check("(c) unsupported driver -> UNSUPPORTED before any mutation",
          r["outcome"] == "rejected_mismatch" and r["code"] == "UNSUPPORTED",
          r)
    check("(c) mode/fence/lease/switch intent unchanged",
          one(conn, "SELECT driver_mode, session_fence, lease_owner"
                    " FROM sessions WHERE session_id=%s", (s,))
          == ("active", r0["session_fence"], "op-u")
          and one(conn, "SELECT count(*) FROM session_switch_intents"
                        " WHERE session_id=%s", (s,))[0] == 0)
    cmd = f"bsw-{u()[:8]}"
    rb = begin(conn, s, r0["session_fence"], owner="op-u",
               driver="drv-unsup", cmd=cmd)
    check("(c) UNSUPPORTED replays idempotently",
          rb["outcome"] == "rejected_mismatch"
          and rb["code"] == "UNSUPPORTED", rb)

    # An undeclared driver fails closed to UNSUPPORTED.
    s2 = u()
    create_session(conn, s2, "drv-undeclared")
    r2 = claim_session(conn, s2, "drv-undeclared", lease_owner="op-d")
    rd = begin(conn, s2, r2["session_fence"], owner="op-d",
               driver="drv-undeclared")
    check("undeclared driver fails closed -> UNSUPPORTED",
          rd["outcome"] == "rejected_mismatch"
          and rd["code"] == "UNSUPPORTED", rd)


# ---------------------------------------------------------------------------
# D12 + D13: single guard implementation, generation-drain interface,
# isolation ruling
# ---------------------------------------------------------------------------

def test_shared_and_isolation(conn) -> None:
    impls = one(conn, "SELECT count(*) FROM pg_proc"
                      " WHERE proname='v_begin_switch_core'")[0]
    check("exactly one shared switch-guard implementation"
          " (A83: the compat entry routes into it — asserted by the G13"
          " gate on the compat database)",
          impls == 1, impls)

    # Isolation ruling (open item 5): reconcile is NOT a post-lock rescan
    # protocol — no ISOLATION_UNSUPPORTED gate applies. READ COMMITTED
    # positive control.
    s, f = switch_ready_session(conn)
    with conn.cursor() as cur:
        cur.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        cur.execute(
            "SELECT outcome, code FROM v_reconcile("
            "%s::uuid, %s, 'begin_switch', %s, 1, 'active', %s, 'op',"
            " %s, NULL, NULL)",
            (s, f"iso-{u()[:8]}", DRIVER, f, TARGET))
        outcome, code = cur.fetchone()
    conn.commit()
    check("reconcile under READ COMMITTED: no ISOLATION_UNSUPPORTED gate"
          " (ruling recorded)",
          outcome == "accepted" and code is None, (outcome, code))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

TESTS = (
    test_intent_table,
    test_entry_contract,
    test_guards,
    test_begin_effects,
    test_quiescing_closed_set,
    test_takeover_controlled_edge,
    test_finish_barrier,
    test_finish_terminal_variant,
    test_post_switch_stale,
    test_fork_surface,
    test_fork_cutoff,
    test_positive_cycle,
    test_unsupported_negative,
    test_shared_and_isolation,
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
    print("[G18] all gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
