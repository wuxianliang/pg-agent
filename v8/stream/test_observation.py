"""G9b gate: v8 stream observation path — the five-state gate, the observation
receipt contract, the completion-criteria / equivalence lifecycle, the F4
extra-index criterion, assistant/partial synthesis and the two-layer portable
verifier (Conformance 10).

Run: uv run python v8/stream/test_observation.py  (exit 0 = pass)

Spec: docs/designs/v8-dev.md section 1.2 (integrity barrier, line 53) +
Conformance 10; digest s32b-effect-ledger.md section 3.2 grammar (0)/(1)-(7),
stream_progress five-state gate, observation receipt contract (Q04), zero
control state (AF01), observation payload layering (S04); digest
s32c-completion-evidence.md (L4-R03/F5).
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
from v8.effect.client import build_result_payload, complete_effect
from v8.events.canonicalizer import (
    normalize,
)
from v8.retry.client import recovery_takeover
from v8.stream import observation as obs
from v8.stream.setup_db import DB, main as setup_db
from v8.stream.test_stream import (
    append_chunks,
    check,
    chunk_entry,
    fresh_session,
    stream_fixture,
    u,
)

CV = "canon@1"


def uri() -> str:
    return get_server().get_uri(DB)


def next_seq(conn, s) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT next_seq FROM sessions WHERE session_id=%s", (s,))
        return cur.fetchone()[0]


def exec_local(conn, sql, params=()) -> None:
    """Run a control-state setup statement in its own committed tx."""
    with conn.cursor() as cur:
        cur.execute(sql, params)
    conn.commit()


def one(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------

def complete_cmd(conn, fx, extra, command_id, *, outcome="succeeded",
                 message=None, evidence=None, attempt_no=1) -> dict:
    message = {"text": "final"} if message is None else message
    payload = build_result_payload(message, [], True, False)
    if extra is not None:
        payload.update(extra)
    return complete_effect(
        conn, fx["s"], command_id, fx["effect"], fx["driver"], 1,
        dispatch_session_fence=fx["dispatch_fence"], job_fence=fx["job_fence"],
        step_id=fx["step"], attempt_no=attempt_no, request_hash=fx["rh"],
        idempotency_key=fx["ik"], outcome=outcome, message=message, tools=[],
        decision_only=True, final_tools=False,
        evidence=evidence or {"class": "known_success",
                              "provider_receipt": {"receipt_id": f"pr-{u()[:8]}"}},
        result_payload=payload)


def put_chunks(conn, s, entries, **kw) -> dict:
    return append_chunks(conn, s, f"ch-{u()[:8]}", entries,
                         expected_seq=next_seq(conn, s), **kw)


def observe(conn, s, effect, *, attempt=1, payload='{"stream_complete":false}',
            cmd=None, computed=None, window_exhausted=False) -> dict:
    """Call the five-state observation sub-operation directly (constructed
    state vectors the completion entry cannot reach)."""
    cmd = cmd or f"obs-{u()[:8]}"
    computed = computed or f"c{u().replace('-', '')}"
    with conn.cursor() as cur:
        if window_exhausted:
            cur.execute("SELECT set_config('v8.stream_window_exhausted','on',true)")
        cur.execute(
            "SELECT outcome, code, receipt_json FROM v_stream_observe("
            "%s::uuid, %s, %s::uuid, %s, %s, 'sv@1', 'canon@1', %s)",
            (str(s), cmd, str(effect), attempt, payload, computed))
        out, code, rec = cur.fetchone()
    conn.commit()
    return {"outcome": out, "code": code, "receipt": rec}


def eff_row(conn, effect_id) -> tuple:
    return one(conn, "SELECT status, result_hash, current_job_fence"
                     " FROM effect_requests WHERE effect_id=%s", (effect_id,))


def att_row(conn, effect_id, attempt_no=1) -> tuple:
    return one(conn, "SELECT status, result_hash FROM effect_attempts"
                     " WHERE effect_id=%s AND attempt_no=%s",
               (effect_id, attempt_no))


def session_row(conn, s) -> tuple:
    return one(conn, "SELECT state, driver_mode, session_fence, cancellation_epoch,"
                     " next_seq FROM sessions WHERE session_id=%s", (s,))


def obs_count(conn, s) -> tuple:
    return one(conn, "SELECT count(*), max(observation_ordinal) FROM session_events"
                     " WHERE session_id=%s AND event_type='stream_progress'", (s,))


# ---------------------------------------------------------------------------
# 1. five-state gate: five branches + two cross products
# ---------------------------------------------------------------------------

def test_gate_branches(conn) -> None:
    # --- gate 5: accept (current in-flight attempt, live window) ---
    fx = stream_fixture(conn)
    before_session = session_row(conn, fx["s"])
    before_eff = eff_row(conn, fx["effect"])
    before_att = att_row(conn, fx["effect"])
    r = observe(conn, fx["s"], fx["effect"])
    ident = r["receipt"]["observation_identity"]
    check("gate 5: current in-flight attempt accepted",
          r["outcome"] == "accepted" and r["code"] is None, r)
    check("observation receipt carries the (attempt_no, ordinal, digest) triple",
          ident["attempt_no"] == 1 and ident["observation_ordinal"] == 1
          and len(ident["payload_digest"]) == 64, ident)
    check("observation writes exactly one stream_progress event",
          obs_count(conn, fx["s"]) == (1, 1), obs_count(conn, fx["s"]))
    # zero control state (AF01): effect/attempt/session unchanged apart from
    # the session next_seq advance required by the event.
    check("observation: effect row unchanged (status/result_hash/fence)",
          eff_row(conn, fx["effect"]) == before_eff, eff_row(conn, fx["effect"]))
    check("observation: attempt row unchanged (status/result_hash)",
          att_row(conn, fx["effect"]) == before_att, att_row(conn, fx["effect"]))
    after_session = session_row(conn, fx["s"])
    check("observation: session control state unchanged (state/mode/fence/epoch)",
          after_session[:4] == before_session[:4]
          and after_session[4] == before_session[4] + 1,
          (before_session, after_session))

    # --- gate 1: terminal session ---
    fx1 = stream_fixture(conn)
    exec_local(conn, "UPDATE sessions SET state='failed' WHERE session_id=%s",
               (fx1["s"],))
    r = observe(conn, fx1["s"], fx1["effect"])
    check("gate 1: terminal session -> SESSION_TERMINAL",
          r["outcome"] == "rejected_mismatch" and r["code"] == "SESSION_TERMINAL",
          (r["outcome"], r["code"]))

    # --- gate 2: superseded attempt ---
    fx2 = stream_fixture(conn)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO effect_attempts(effect_id, attempt_no, session_id,"
            " step_id, dispatch_job_fence, driver, driver_epoch, session_fence,"
            " dispatch_session_fence, request_hash, idempotency_key,"
            " execution_mode, status)"
            " SELECT effect_id, 2, session_id, step_id, dispatch_job_fence + 1,"
            " driver, driver_epoch, session_fence, dispatch_session_fence,"
            " request_hash, idempotency_key, execution_mode, 'ready'"
            " FROM effect_attempts WHERE effect_id=%s AND attempt_no=1",
            (fx2["effect"],))
        cur.execute("UPDATE effect_attempts SET superseded_by_attempt_no=2"
                    " WHERE effect_id=%s AND attempt_no=1", (fx2["effect"],))
    conn.commit()
    r = observe(conn, fx2["s"], fx2["effect"])
    check("gate 2: superseded attempt -> rejected_stale",
          r["outcome"] == "rejected_stale", (r["outcome"], r["code"]))

    # --- gate 3: attempt four terminal statuses -> STREAM_CLOSED ---
    for st in ("succeeded", "failed_terminal", "cancelled_before_dispatch",
               "cancelled_after_dispatch"):
        fxn = stream_fixture(conn)
        exec_local(conn, "UPDATE effect_attempts SET status=%s"
                         " WHERE effect_id=%s AND attempt_no=1",
                   (st, fxn["effect"]))
        r = observe(conn, fxn["s"], fxn["effect"])
        check(f"gate 3: attempt status {st} -> STREAM_CLOSED",
              r["outcome"] == "rejected_mismatch" and r["code"] == "STREAM_CLOSED",
              (st, r["outcome"], r["code"]))
        check(f"gate 3 ({st}): no observation event written",
              obs_count(conn, fxn["s"]) == (0, None), obs_count(conn, fxn["s"]))

    # --- gate 4a: unknown_outcome ---
    fx4 = stream_fixture(conn)
    exec_local(conn, "UPDATE effect_attempts SET status='unknown_outcome'"
                     " WHERE effect_id=%s AND attempt_no=1", (fx4["effect"],))
    r = observe(conn, fx4["s"], fx4["effect"])
    check("gate 4a: unknown_outcome -> repair_required / REPAIR_REQUIRED",
          r["outcome"] == "repair_required" and r["code"] == "REPAIR_REQUIRED",
          (r["outcome"], r["code"]))

    # --- gate 4b: waiting window exhausted ---
    fx5 = stream_fixture(conn)
    r = observe(conn, fx5["s"], fx5["effect"], window_exhausted=True)
    check("gate 4b: exhausted waiting window -> repair_required",
          r["outcome"] == "repair_required" and r["code"] == "REPAIR_REQUIRED",
          (r["outcome"], r["code"]))

    # --- cross product A: terminal session x exhausted window -> gate 1 wins ---
    fxA = stream_fixture(conn)
    exec_local(conn, "UPDATE sessions SET state='failed' WHERE session_id=%s",
               (fxA["s"],))
    r = observe(conn, fxA["s"], fxA["effect"], window_exhausted=True)
    check("cross A: terminal session wins over window exhaustion",
          r["code"] == "SESSION_TERMINAL", (r["outcome"], r["code"]))

    # --- cross product B: attempt success terminal x exhausted window -> g3 ---
    fxB = stream_fixture(conn)
    exec_local(conn, "UPDATE effect_attempts SET status='succeeded'"
                     " WHERE effect_id=%s AND attempt_no=1", (fxB["effect"],))
    r = observe(conn, fxB["s"], fxB["effect"], window_exhausted=True)
    check("cross B: closed attempt (STREAM_CLOSED) wins over window exhaustion",
          r["code"] == "STREAM_CLOSED", (r["outcome"], r["code"]))


# ---------------------------------------------------------------------------
# 2. quiescing is NOT one of the five gates
# ---------------------------------------------------------------------------

def test_quiescing(conn) -> None:
    # positive: a non-terminal observation is judged by the five gates and is
    # ACCEPTED under quiescing.
    fx = stream_fixture(conn)
    exec_local(conn, "UPDATE sessions SET driver_mode='quiescing'"
                     " WHERE session_id=%s", (fx["s"],))
    r = observe(conn, fx["s"], fx["effect"])
    check("quiescing: non-terminal observation accepted (not a gate)",
          r["outcome"] == "accepted", (r["outcome"], r["code"]))

    # terminal completion under quiescing -> DRIVER_QUIESCING (W01).
    fx2 = stream_fixture(conn)
    exec_local(conn, "UPDATE sessions SET driver_mode='quiescing'"
                     " WHERE session_id=%s", (fx2["s"],))
    r = complete_cmd(conn, fx2, {"stream_complete": True, "final_chunk_index": 0},
                     f"cmp-{u()[:8]}")
    check("quiescing: terminal completion -> DRIVER_QUIESCING",
          r["outcome"] == "rejected_mismatch" and r["code"] == "DRIVER_QUIESCING",
          (r["outcome"], r["code"]))
    check("quiescing terminal reject: effect stays dispatch_started",
          eff_row(conn, fx2["effect"])[0] == "dispatch_started",
          eff_row(conn, fx2["effect"]))

    # non-observation negative: a semantic append under quiescing is rejected.
    from v8.events.client import build_entry

    s = fresh_session(conn)
    entry = build_entry("user/message", {"text": "q"}, schema_version="sv@1",
                        canonicalizer_version=CV, turn_id=u(),
                        semantic_input_ordinal=1)
    exec_local(conn, "UPDATE sessions SET driver_mode='quiescing'"
                     " WHERE session_id=%s", (s,))
    r = append_chunks(conn, s, f"ap-{u()[:8]}", [entry],
                      expected_seq=next_seq(conn, s))
    check("quiescing: semantic append -> DRIVER_QUIESCING",
          r["code"] == "DRIVER_QUIESCING", (r["outcome"], r["code"]))


# ---------------------------------------------------------------------------
# 3. observation receipt contract + the four junctions
# ---------------------------------------------------------------------------

def test_receipt_contract(conn) -> None:
    # idempotent retry: same command_id + same request -> same triple, no
    # re-execution, no second event.
    fx = stream_fixture(conn)
    cmd = f"cmp-{u()[:8]}"
    extra = {"stream_complete": False, "final_chunk_index": 0}
    ev = {"class": "known_success",
          "provider_receipt": {"receipt_id": f"pr-{u()[:8]}"}}
    r1 = complete_cmd(conn, fx, extra, cmd, evidence=ev)
    r2 = complete_cmd(conn, fx, extra, cmd, evidence=ev)
    check("observation retry is idempotent (same triple)",
          r1["outcome"] == r2["outcome"] == "accepted"
          and r1["receipt"]["observation_identity"]
          == r2["receipt"]["observation_identity"],
          (r1["receipt"].get("observation_identity"),
           r2["receipt"].get("observation_identity")))
    check("observation retry writes no second event / ordinal stays 1",
          obs_count(conn, fx["s"]) == (1, 1), obs_count(conn, fx["s"]))

    # same command_id, different payload -> IDEMPOTENCY_CONFLICT.
    r3 = complete_cmd(conn, fx, {"stream_complete": False, "chunk_count": 9}, cmd)
    check("same command_id with a different payload -> IDEMPOTENCY_CONFLICT",
          r3["code"] == "IDEMPOTENCY_CONFLICT", (r3["outcome"], r3["code"]))

    # a second observation (new command_id) gets ordinal 2 in its own binding.
    cmd4 = f"cmp-{u()[:8]}"
    r4 = complete_cmd(conn, fx, extra, cmd4, evidence=ev)
    check("second observation -> ordinal 2",
          r4["outcome"] == "accepted"
          and r4["receipt"]["observation_identity"]["observation_ordinal"] == 2, r4)
    check("two observations: two events, ordinals 1..2",
          obs_count(conn, fx["s"]) == (2, 2), obs_count(conn, fx["s"]))
    # each command keeps its own binding; no cross-command overwrite.
    b1 = one(conn, "SELECT first_outcome, first_key_value FROM command_bindings"
                   " WHERE session_id=%s AND command_id=%s", (fx["s"], cmd))
    b2 = one(conn, "SELECT first_outcome, first_key_value FROM command_bindings"
                   " WHERE session_id=%s AND command_id=%s", (fx["s"], cmd4))
    check("observation bindings are per-command (no cross overwrite)",
          b1 is not None and b2 is not None and b1[0] == "accepted"
          and b2[0] == "accepted" and b1[1] != b2[1], (b1, b2))

    # observation then terminal completion (new command_id) settles normally.
    fx2 = stream_fixture(conn)
    ro = complete_cmd(conn, fx2, {"stream_complete": False}, f"cmp-{u()[:8]}")
    check("junction: observation accepted", ro["outcome"] == "accepted", ro)
    rc = complete_cmd(conn, fx2, {"stream_complete": True, "final_chunk_index": 0},
                      f"cmp-{u()[:8]}")
    check("junction: observation then terminal completion accepted",
          rc["outcome"] == "accepted"
          and rc["receipt"]["classification"] == "known_success"
          and eff_row(conn, fx2["effect"])[0] == "succeeded", (rc, ))

    # observation receipt is independent of the terminal settlement receipt:
    # the terminal attempt keeps its own (settlement) result_hash.
    check("observation does not occupy the terminal settlement receipt",
          eff_row(conn, fx2["effect"])[1] is not None, eff_row(conn, fx2["effect"]))


# ---------------------------------------------------------------------------
# 4. equivalence lifecycle + F4 extra index + three representations
# ---------------------------------------------------------------------------

def test_equivalence_lifecycle(conn) -> None:
    # --- (a)(b): final arrives first, tail chunk missing -> pending, no
    #     conflict; the late tail chunk completes the verification ---
    fx = stream_fixture(conn)
    e = fx["effect"]
    put_chunks(conn, fx["s"], [chunk_entry(e, "A", 0), chunk_entry(e, "B", 1)])
    r = complete_cmd(conn, fx, {"stream_complete": True, "final_chunk_index": 2},
                     f"cmp-{u()[:8]}", message={"text": "ABC"})
    check("(b) final first / tail missing -> completion accepted, no conflict",
          r["outcome"] == "accepted"
          and obs.session_conflict_fact(conn, fx["s"]) is False,
          (r["outcome"], obs.session_conflict_fact(conn, fx["s"])))
    check("(b) equivalence is pending (verdict inspectable, no fact)",
          obs.db_equivalence(conn, fx["s"], e, 1, 2, None, "ABC")["status"]
          == "pending",
          obs.db_equivalence(conn, fx["s"], e, 1, 2, None, "ABC"))
    # correct tail arrives -> verification completes OK, still no conflict.
    rt = put_chunks(conn, fx["s"], [chunk_entry(e, "C", 2)])
    check("(b) correct tail chunk accepted after the terminal fact",
          rt["outcome"] == "accepted", rt)
    check("(b) correct tail completes the equivalence -> no conflict fact",
          obs.session_conflict_fact(conn, fx["s"]) is False,
          obs.session_conflict_fact(conn, fx["s"]))

    # --- (d): terminal then a CONTRADICTORY tail -> conflict fact, business
    #     terminal state unchanged ---
    fx2 = stream_fixture(conn)
    e2 = fx2["effect"]
    put_chunks(conn, fx2["s"], [chunk_entry(e2, "A", 0), chunk_entry(e2, "B", 1)])
    complete_cmd(conn, fx2, {"stream_complete": True, "final_chunk_index": 2},
                 f"cmp-{u()[:8]}", message={"text": "ABC"})
    before = eff_row(conn, e2)
    put_chunks(conn, fx2["s"], [chunk_entry(e2, "Z", 2)])
    check("(d) contradictory tail records CANONICALIZER_CONFLICT",
          obs.session_conflict_fact(conn, fx2["s"]) is True,
          obs.session_conflict_fact(conn, fx2["s"]))
    check("(d) business terminal state is NOT rewritten",
          eff_row(conn, e2) == before, (before, eff_row(conn, e2)))
    # two-layer verifier: normalize still succeeds, the verifier fails.
    evs = obs.load_stream_events(conn, fx2["s"])
    ver = obs.portable_verify(evs, conflict_fact=obs.session_conflict_fact(
        conn, fx2["s"]))
    check("(d) portable verifier fails on the conflict fact (normalize ok)",
          ver["passed"] is False and isinstance(ver["trace"], list), ver["passed"])

    # --- (a) complete flow with a mismatching final text at settlement ---
    fx3 = stream_fixture(conn)
    e3 = fx3["effect"]
    put_chunks(conn, fx3["s"], [chunk_entry(e3, "A", 0), chunk_entry(e3, "B", 1)])
    complete_cmd(conn, fx3, {"stream_complete": True, "final_chunk_index": 1},
                 f"cmp-{u()[:8]}", message={"text": "XX"})
    check("(a) complete flow with a mismatch -> conflict fact",
          obs.session_conflict_fact(conn, fx3["s"]) is True,
          obs.session_conflict_fact(conn, fx3["s"]))

    # --- three representations agree ---
    fx4 = stream_fixture(conn)
    e4 = fx4["effect"]
    put_chunks(conn, fx4["s"], [chunk_entry(e4, "A", 0), chunk_entry(e4, "B", 1)])
    evs4 = obs.accepted_events(conn, fx4["s"])
    check("three representations agree (complete: N only / C only / both)",
          obs.three_representations_agree(evs4, e4, 1,
                                          final_chunk_index=1, chunk_count=2),
          [obs.flow_state(evs4, e4, 1, final_chunk_index=1)["status"],
           obs.flow_state(evs4, e4, 1, chunk_count=2)["status"],
           obs.flow_state(evs4, e4, 1, final_chunk_index=1,
                          chunk_count=2)["status"]])
    fx5 = stream_fixture(conn)
    e5 = fx5["effect"]
    put_chunks(conn, fx5["s"], [chunk_entry(e5, "A", 0)])
    evs5 = obs.accepted_events(conn, fx5["s"])
    check("three representations agree (pending: missing index)",
          obs.three_representations_agree(evs5, e5, 1,
                                          final_chunk_index=1, chunk_count=2)
          and obs.flow_state(evs5, e5, 1, final_chunk_index=1)["status"]
          == "pending",
          obs.flow_state(evs5, e5, 1, final_chunk_index=1))


def test_extra_index(conn) -> None:
    # form (a): an index > N accepted BEFORE the completion (ahead).
    fx = stream_fixture(conn)
    e = fx["effect"]
    put_chunks(conn, fx["s"], [chunk_entry(e, "A", 0), chunk_entry(e, "B", 1),
                               chunk_entry(e, "C", 3)])
    complete_cmd(conn, fx, {"stream_complete": True, "final_chunk_index": 2},
                 f"cmp-{u()[:8]}", message={"text": "ABC"})
    check("F4(a) ahead extra index (3 > N=2) -> conflict at settlement",
          obs.session_conflict_fact(conn, fx["s"]) is True,
          obs.session_conflict_fact(conn, fx["s"]))
    check("F4(a) equivalence was NOT evaluated (range criterion only)",
          obs.db_equivalence(conn, fx["s"], e, 1, 2, None, "ABC")["status"]
          == "conflict_extra_index",
          obs.db_equivalence(conn, fx["s"], e, 1, 2, None, "ABC"))

    # form (b): an extra index accepted AFTER the end fact, equivalence still
    # pending (tail missing) -> conflict.
    fx2 = stream_fixture(conn)
    e2 = fx2["effect"]
    put_chunks(conn, fx2["s"], [chunk_entry(e2, "A", 0), chunk_entry(e2, "B", 1),
                                chunk_entry(e2, "C", 2)])
    complete_cmd(conn, fx2, {"stream_complete": True, "final_chunk_index": 3},
                 f"cmp-{u()[:8]}", message={"text": "ABC"})
    check("F4(b) setup: verification is pending",
          obs.session_conflict_fact(conn, fx2["s"]) is False,
          obs.session_conflict_fact(conn, fx2["s"]))
    put_chunks(conn, fx2["s"], [chunk_entry(e2, "D", 4)])
    check("F4(b) extra index after the end fact -> conflict",
          obs.session_conflict_fact(conn, fx2["s"]) is True,
          obs.session_conflict_fact(conn, fx2["s"]))

    # form (c): an extra index accepted AFTER the verification completed OK.
    fx3 = stream_fixture(conn)
    e3 = fx3["effect"]
    put_chunks(conn, fx3["s"], [chunk_entry(e3, "A", 0), chunk_entry(e3, "B", 1)])
    complete_cmd(conn, fx3, {"stream_complete": True, "final_chunk_index": 1},
                 f"cmp-{u()[:8]}", message={"text": "AB"})
    check("F4(c) setup: verification complete, no conflict",
          obs.session_conflict_fact(conn, fx3["s"]) is False,
          obs.session_conflict_fact(conn, fx3["s"]))
    put_chunks(conn, fx3["s"], [chunk_entry(e3, "X", 2)])
    check("F4(c) extra index after verification -> conflict still recorded",
          obs.session_conflict_fact(conn, fx3["s"]) is True,
          obs.session_conflict_fact(conn, fx3["s"]))

    # empty-payload extra chunk: same criterion, not exempt.
    fx4 = stream_fixture(conn)
    e4 = fx4["effect"]
    put_chunks(conn, fx4["s"], [chunk_entry(e4, "A", 0), chunk_entry(e4, "B", 1)])
    complete_cmd(conn, fx4, {"stream_complete": True, "final_chunk_index": 1},
                 f"cmp-{u()[:8]}", message={"text": "AB"})
    put_chunks(conn, fx4["s"], [chunk_entry(e4, "", 5)])
    check("F4 empty-payload extra chunk -> same range conflict",
          obs.session_conflict_fact(conn, fx4["s"]) is True,
          obs.session_conflict_fact(conn, fx4["s"]))


# ---------------------------------------------------------------------------
# 5. assistant/partial synthesis (S04 clause 3)
# ---------------------------------------------------------------------------

def test_partial_synthesis(conn) -> None:
    t = str(uuid.uuid4())
    e = str(uuid.uuid4())

    def chunk(idx, text):
        return {"event_type": "assistant/chunk", "payload": {"text": text},
                "turn_id": t, "effect_id": e, "attempt_no": 1,
                "stream_id": "s1", "chunk_index": idx}

    # unknown path WITH a prefix -> one assistant/partial with merged text.
    tr = normalize([
        chunk(0, "AB"), chunk(1, "C"),
        {"event_type": "tool/result", "payload": {}, "turn_id": t,
         "effect_id": e, "attempt_no": 1, "effect_status": "unknown_outcome"},
    ])
    parts = obs.partial_events(tr)
    ends = [x for x in tr if x["event_type"] == "turn/end"]
    check("unknown path with a prefix -> one assistant/partial (merged)",
          len(parts) == 1 and parts[0]["payload"] == {"text": "ABC",
                                                      "outcome": "unknown"},
          parts)
    check("unknown path -> provisional unknown end",
          len(ends) == 1 and ends[0]["payload"]["outcome"] == "unknown", ends)

    # unknown path WITHOUT a prefix -> no partial.
    tr2 = normalize([
        {"event_type": "tool/result", "payload": {}, "turn_id": t,
         "effect_id": e, "attempt_no": 1, "effect_status": "unknown_outcome"},
    ])
    check("unknown path without a prefix -> no assistant/partial",
          obs.partial_events(tr2) == [], tr2)

    # cancelled_after_dispatch (sticky request cancel) WITH a prefix -> partial.
    tr3 = normalize([
        chunk(0, "AB"), chunk(1, "C"),
        {"event_type": "tool/result", "payload": {}, "turn_id": t,
         "effect_id": e, "attempt_no": 1,
         "effect_status": "cancelled_after_dispatch",
         "code": "CANCELLED_BY_REQUEST_AFTER_DISPATCH"},
    ])
    parts3 = obs.partial_events(tr3)
    ends3 = [x for x in tr3 if x["event_type"] == "turn/end"]
    check("cancelled_after_dispatch with a prefix -> one assistant/partial",
          len(parts3) == 1 and parts3[0]["payload"] == {"text": "ABC"}, parts3)
    check("sticky cancel end reason",
          len(ends3) == 1
          and ends3[0]["payload"]["reason"] == "cancelled_by_request_after_dispatch",
          ends3)

    # cancelled_after_dispatch WITHOUT a prefix -> no partial.
    tr4 = normalize([
        {"event_type": "tool/result", "payload": {}, "turn_id": t,
         "effect_id": e, "attempt_no": 1,
         "effect_status": "cancelled_after_dispatch",
         "code": "CANCELLED_BY_REQUEST_AFTER_DISPATCH"},
    ])
    check("cancelled_after_dispatch without a prefix -> no assistant/partial",
          obs.partial_events(tr4) == [], tr4)

    # provider cancel prefix (existing behavior) still holds.
    tr5 = normalize([
        chunk(0, "AB"),
        {"event_type": "tool/result", "payload": {}, "turn_id": t,
         "effect_id": e, "attempt_no": 1,
         "effect_status": "cancelled_after_dispatch",
         "code": "CANCELLED_BY_PROVIDER"},
    ])
    check("provider cancel with a prefix -> one assistant/partial",
          len(obs.partial_events(tr5)) == 1, tr5)


# ---------------------------------------------------------------------------
# 6. observation payload layering (S04 clause 1) — normalize ignores
#    stream_progress entirely
# ---------------------------------------------------------------------------

def test_observation_layering(conn) -> None:
    t = str(uuid.uuid4())
    e = str(uuid.uuid4())
    base = [
        {"event_type": "user/message", "payload": {"text": "q"}, "turn_id": t,
         "semantic_input_ordinal": 1},
        {"event_type": "assistant/message", "payload": {"text": "r"},
         "turn_id": t, "effect_id": e, "effect_status": "succeeded"},
    ]
    tr_wo = normalize(base)
    tr_w = normalize(base + [
        {"event_type": "stream_progress",
         "payload": {"stream_complete": False, "final_chunk_index": 9},
         "turn_id": t, "effect_id": e, "attempt_no": 1,
         "observation_ordinal": 1},
    ])
    check("a stream_progress observation never enters the normalize output",
          tr_w == tr_wo, (tr_w, tr_wo))

    # its count fields are never a flow-collection fact: a bogus huge count in
    # an observation does not make the (empty) flow complete.
    evs = [{"event_type": "stream_progress",
            "payload": {"final_chunk_index": 0}, "turn_id": t, "effect_id": e,
            "attempt_no": 1, "observation_ordinal": 1}]
    check("observation counts are audit-only, never a flow fact",
          obs.flow_state(evs, e, 1, final_chunk_index=0)["status"] == "pending",
          obs.flow_state(evs, e, 1, final_chunk_index=0))


# ---------------------------------------------------------------------------
# 7. two-layer portable verifier (both fact shapes)
# ---------------------------------------------------------------------------

def test_portable_verifier(conn) -> None:
    # fact shape 1: the append-layer CANONICALIZER_CONFLICT rejection.
    fx = stream_fixture(conn)
    e = fx["effect"]
    put_chunks(conn, fx["s"], [chunk_entry(e, "A", 0)])
    r = put_chunks(conn, fx["s"], [chunk_entry(e, "DIFF", 0)])
    check("append-layer chunk conflict -> CANONICALIZER_CONFLICT",
          r["code"] == "CANONICALIZER_CONFLICT", (r["outcome"], r["code"]))
    check("append-layer conflict is a persisted fact",
          obs.session_conflict_fact(conn, fx["s"]) is True,
          obs.session_conflict_fact(conn, fx["s"]))
    evs = obs.load_stream_events(conn, fx["s"])
    ver = obs.portable_verify(evs, conflict_fact=True)
    check("verifier: normalize passes but portable comparison fails",
          isinstance(ver["trace"], list) and ver["passed"] is False, ver["passed"])

    # no fact -> passes.
    s = fresh_session(conn)
    ver2 = obs.portable_verify(obs.load_stream_events(conn, s), conflict_fact=False)
    check("verifier: no conflict fact -> portable comparison passes",
          ver2["passed"] is True, ver2["passed"])


# ---------------------------------------------------------------------------
# 8. Conformance 10: window exhaustion (alpha) -> unknown + STREAM_INCOMPLETE
# ---------------------------------------------------------------------------

def test_window_exhaustion(conn) -> None:
    # (alpha) a result-less in-flight streaming attempt taken over with no
    # terminal evidence settles unknown and records STREAM_INCOMPLETE.
    fx = stream_fixture(conn)
    e = fx["effect"]
    put_chunks(conn, fx["s"], [chunk_entry(e, "AB", 0)])
    r = recovery_takeover(conn, fx["s"], f"tko-{u()[:8]}", fx["driver"], 1,
                          evidence=None)
    check("window exhaustion (alpha): takeover accepted",
          r["outcome"] == "accepted", r)
    check("window exhaustion (alpha): effect settled unknown_outcome",
          eff_row(conn, e)[0] == "unknown_outcome", eff_row(conn, e))
    check("window exhaustion (alpha): STREAM_INCOMPLETE audit reason recorded",
          obs.session_stream_incomplete(conn, fx["s"]) is True,
          obs.session_stream_incomplete(conn, fx["s"]))
    # the prefix is retained as an assistant/partial in normalize.
    evs = obs.load_stream_events(conn, fx["s"])
    for ev in evs:
        if ev["effect_id"] == str(e):
            ev["effect_status"] = "unknown_outcome"
    parts = obs.partial_events(normalize(evs))
    check("window exhaustion (alpha): prefix retained as assistant/partial",
          len(parts) == 1 and parts[0]["payload"]["text"] == "AB", parts)

    # (beta) completion first, tail window exhausted: terminal unchanged,
    # equivalence pending, no conflict, no STREAM_INCOMPLETE.
    fx2 = stream_fixture(conn)
    e2 = fx2["effect"]
    put_chunks(conn, fx2["s"], [chunk_entry(e2, "A", 0)])
    complete_cmd(conn, fx2, {"stream_complete": True, "final_chunk_index": 1},
                 f"cmp-{u()[:8]}", message={"text": "AB"})
    check("window exhaustion (beta): flow terminal state unchanged",
          eff_row(conn, e2)[0] == "succeeded", eff_row(conn, e2))
    check("window exhaustion (beta): equivalence stays pending, no conflict",
          obs.db_equivalence(conn, fx2["s"], e2, 1, 1, None, "AB")["status"]
          == "pending" and obs.session_conflict_fact(conn, fx2["s"]) is False,
          (obs.db_equivalence(conn, fx2["s"], e2, 1, 1, None, "AB"),
           obs.session_conflict_fact(conn, fx2["s"])))
    check("window exhaustion (beta): no STREAM_INCOMPLETE for a completed flow",
          obs.session_stream_incomplete(conn, fx2["s"]) is False,
          obs.session_stream_incomplete(conn, fx2["s"]))


# ---------------------------------------------------------------------------
# 9. attribution premise: a rejected chunk never enters any merge/conflict
# ---------------------------------------------------------------------------

def test_attribution_premise(conn) -> None:
    fx = stream_fixture(conn)
    e = fx["effect"]
    # an unattributable chunk (unknown effect) is rejected, zero events.
    r = put_chunks(conn, fx["s"], [chunk_entry(uuid.uuid4(), "X", 0)])
    check("rejected chunk (unknown effect) -> CHUNK_ATTRIBUTION_INVALID",
          r["code"] == "CHUNK_ATTRIBUTION_INVALID", (r["outcome"], r["code"]))
    evs = obs.accepted_events(conn, fx["s"])
    check("a rejected chunk enters no merge / conflict / flow fact",
          evs == []
          and obs.flow_state(evs, e, 1, final_chunk_index=0)["status"]
          == "pending", evs)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--no-setup":
        pass
    else:
        setup_db()
    conn = psycopg2.connect(uri())
    conn.autocommit = False
    try:
        test_gate_branches(conn)
        test_quiescing(conn)
        test_receipt_contract(conn)
        test_equivalence_lifecycle(conn)
        test_extra_index(conn)
        test_partial_synthesis(conn)
        test_observation_layering(conn)
        test_portable_verifier(conn)
        test_window_exhaustion(conn)
        test_attribution_premise(conn)
    finally:
        conn.close()
    print("[G9b] all gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
