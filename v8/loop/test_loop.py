"""G5 gate: P0B minimal closed loop — normal loop, kill-at-every-boundary
chaos, duplicate-submit idempotency (Conformance 1), yield/worker handoff,
failure forms, and external-IO-outside-transaction.

Run: uv run python v8/loop/test_loop.py  (exit 0 = pass)
"""
from __future__ import annotations

import hashlib
import json
import sys
import uuid
from pathlib import Path

import psycopg2
from psycopg2.extensions import STATUS_BEGIN, STATUS_READY

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
    yield_session,
)
from v8.events.canonicalizer import normalize
from v8.events.client import build_entry, call_append_events
from v8.loop.runtime import (
    ALL_KILL_POINTS,
    BOUNDARIES,
    FakeLLM,
    ProcessDeath,
    advance_session,
    append_user_message,
    create_loop_session,
    read_effect_descriptor,
    run_user_message,
    seal_decision_step,
    acquire_lease,
)
from v8.loop.setup_db import DB, main as setup_db

DRIVER = "drv"
EPOCH = 1


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f": {detail}" if detail else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def u() -> str:
    return str(uuid.uuid4())


def rows(conn, sql: str, params: tuple = ()) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        out = cur.fetchall()
    conn.rollback()
    return out


def one(conn, sql: str, params: tuple = ()):
    r = rows(conn, sql, params)
    return r[0] if r else None


def uri() -> str:
    return get_server().get_uri(DB)


def semantic_trace(conn, session_id) -> list[tuple]:
    """Normalized semantic projection for chaos equivalence: event_type +
    payload + public ordinal, in seq order (receipts/audit/seq may differ
    between runs; this projection must not)."""
    out = []
    for event_type, payload, ordinal in rows(
            conn,
            "SELECT event_type, payload, semantic_input_ordinal"
            " FROM session_events WHERE session_id = %s"
            " AND event_class = 'semantic' ORDER BY seq", (session_id,)):
        out.append((event_type, json.loads(payload), ordinal))
    return out


def assert_persisted_invariants(conn, session_id, label: str) -> None:
    """Conformance 1 invariants checked at EVERY chaos observation point:
    no persisted planned step/effect, exactly one first attempt
    (attempt_no=1) per effect, no seq holes."""
    n_planned_steps = one(
        conn, "SELECT count(*) FROM steps WHERE session_id=%s"
              " AND status='planned'", (session_id,))[0]
    check(f"[{label}] no persisted planned step", n_planned_steps == 0)
    n_planned_effects = one(
        conn, "SELECT count(*) FROM effect_requests WHERE session_id=%s"
              " AND status='planned'", (session_id,))[0]
    check(f"[{label}] no persisted planned effect", n_planned_effects == 0)
    att = one(
        conn,
        "SELECT count(*), count(DISTINCT effect_id), min(attempt_no),"
        " max(attempt_no) FROM effect_attempts WHERE effect_id IN"
        " (SELECT effect_id FROM effect_requests WHERE session_id=%s)",
        (session_id,))
    n_effects = one(conn, "SELECT count(*) FROM effect_requests"
                          " WHERE session_id=%s", (session_id,))[0]
    if n_effects:
        check(f"[{label}] one first attempt per effect (no rebuilds)",
              att == (n_effects, n_effects, 1, 1), att)
    seqs = [r[0] for r in rows(
        conn, "SELECT seq FROM session_events WHERE session_id=%s"
              " ORDER BY seq", (session_id,))]
    check(f"[{label}] seq 1..N no holes",
          seqs == list(range(1, len(seqs) + 1)), seqs)
    next_seq = one(conn, "SELECT next_seq FROM sessions WHERE session_id=%s",
                   (session_id,))[0]
    check(f"[{label}] next_seq == N+1", next_seq == len(seqs) + 1,
          (next_seq, len(seqs)))


def normalize_input_from_db(conn, session_id) -> list[dict]:
    """session_events -> G3 canonicalizer input, with the effect-level
    signals (status/decision_only) joined from the control tables.

    Effects whose terminal state has no event carrier (the unknown closure
    persists no assistant/message in P0B non-streaming) get a synthetic
    carrier event, per the canonicalizer's documented input contract
    ("effect_status carried by whichever event represents that effect's
    state") — same convention as the G4 unknown-path test."""
    out = []
    seen_effects = set()
    for (event_type, payload, turn_id, step_id, effect_id, ordinal,
         eff_status, decision_only) in rows(
        conn,
        "SELECT se.event_type, se.payload, se.turn_id, se.step_id,"
        " se.effect_id, se.semantic_input_ordinal, er.status, st.decision_only"
        " FROM session_events se"
        " LEFT JOIN effect_requests er ON er.effect_id = se.effect_id"
        " LEFT JOIN steps st ON st.step_id = se.step_id"
        " WHERE se.session_id = %s ORDER BY se.seq", (session_id,)):
        item = {"event_type": event_type, "payload": json.loads(payload),
                "turn_id": turn_id, "step_id": step_id,
                "effect_id": effect_id}
        if ordinal is not None:
            item["semantic_input_ordinal"] = ordinal
        if eff_status is not None:
            item["effect_status"] = eff_status
        if decision_only is not None:
            item["decision_only"] = decision_only
        if effect_id is not None:
            seen_effects.add(effect_id)
        out.append(item)
    for effect_id, status, turn_id in rows(
            conn,
            "SELECT er.effect_id, er.status, st.turn_id FROM effect_requests er"
            " JOIN steps st ON st.step_id = er.step_id"
            " WHERE er.session_id = %s ORDER BY er.dispatch_ordinal",
            (session_id,)):
        if str(effect_id) in seen_effects:
            continue
        carrier = {"event_type": "tool/result", "payload": {},
                   "turn_id": turn_id, "effect_id": str(effect_id),
                   "effect_status": status}
        if status == "unknown_outcome":
            carrier["code"] = "UNKNOWN_AFTER_DISPATCH"
        out.append(carrier)
    return out


def expected_assistant_payload(text: str) -> dict:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return {"text": f"fake-final:{text}", "model": "fake-llm@1",
            "seed": digest[:16]}


# ---------------------------------------------------------------------------
# Normal closed loop
# ---------------------------------------------------------------------------

def test_normal_closed_loop() -> None:
    text = "hello loop"
    s = create_loop_session(uri())
    r = run_user_message(uri(), s, text)
    check("normal loop completes", r["state"] == "completed", r)
    conn = psycopg2.connect(uri())
    try:
        check("session row completed",
              one(conn, "SELECT state FROM sessions WHERE session_id=%s",
                  (s,))[0] == "completed")

        events = rows(conn, "SELECT seq, event_type, payload FROM"
                            " session_events WHERE session_id=%s ORDER BY seq",
                      (s,))
        types = [e[1] for e in events]
        check("event order turn/start,user,assistant,turn/end",
              types == ["turn/start", "user/message", "assistant/message",
                        "turn/end"], types)
        check("seq 1..4 contiguous no holes",
              [e[0] for e in events] == [1, 2, 3, 4],
              [e[0] for e in events])
        check("each event type exactly once",
              len(set(types)) == 4 and len(types) == 4)
        check("user/message payload",
              json.loads(events[1][2]) == {"text": text})
        check("assistant/message payload == deterministic FakeLLM message",
              json.loads(events[2][2]) == expected_assistant_payload(text))
        check("turn/end {interrupted:false}",
              json.loads(events[3][2]) == {"interrupted": False})

        step = one(conn, "SELECT status, stage, decision_only, final_tools,"
                         " sealed_batch_no FROM steps WHERE session_id=%s",
                   (s,))
        check("step succeeded/closed/decision_only/final_tools=false",
              step == ("succeeded", "closed", True, False, 1), step)
        eff = one(conn, "SELECT status, dispatch_count FROM effect_requests"
                        " WHERE session_id=%s", (s,))
        check("effect succeeded, dispatched once", eff == ("succeeded", 1), eff)
        att = one(conn,
                  "SELECT count(*), min(attempt_no), max(attempt_no),"
                  " min(status) FROM effect_attempts WHERE effect_id IN"
                  " (SELECT effect_id FROM effect_requests WHERE session_id=%s)",
                  (s,))
        check("exactly one attempt row, attempt_no=1, succeeded",
              att == (1, 1, 1, "succeeded"), att)
        slot = one(conn, "SELECT slot_status, version FROM turn_end_slots"
                         " WHERE session_id=%s", (s,))
        check("turn_end_slot known", slot == ("known", 1), slot)

        receipts = dict(rows(conn, "SELECT command_kind, count(*) FROM"
                                   " command_receipts WHERE session_id=%s"
                                   " GROUP BY 1", (s,)))
        check("one receipt per command kind",
              receipts == {"append_events": 1, "prepare_step": 1,
                           "dispatch_effect": 1, "complete_effect": 1,
                           "finish_session": 1}, receipts)
        n_bind = one(conn, "SELECT count(*) FROM command_bindings"
                           " WHERE session_id=%s", (s,))[0]
        n_recv = one(conn, "SELECT count(*) FROM command_receipts"
                           " WHERE session_id=%s", (s,))[0]
        check("binding+receipt exactly one row per command",
              n_bind == n_recv == 5, (n_bind, n_recv))

        trace = normalize(normalize_input_from_db(conn, s))
        ends = [e for e in trace if e["event_type"] == "turn/end"]
        check("normalize(): exactly one turn/end",
              len(ends) == 1 and ends[0]["payload"] == {"interrupted": False},
              ends)
        check("normalize(): semantic order correct",
              [e["event_type"] for e in trace] ==
              ["turn/start", "user/message", "assistant/message", "turn/end"],
              [e["event_type"] for e in trace])
        assert_persisted_invariants(conn, s, "normal")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Multi-turn
# ---------------------------------------------------------------------------

def test_multi_turn() -> None:
    s = create_loop_session(uri())
    r1 = run_user_message(uri(), s, "first question", finish=False)
    check("turn 1 leaves session ready (finish deferred)",
          r1["state"] == "ready", r1)
    r2 = run_user_message(uri(), s, "second question")
    check("turn 2 completes the session", r2["state"] == "completed", r2)
    conn = psycopg2.connect(uri())
    try:
        events = rows(conn, "SELECT seq, event_type, payload, turn_id,"
                            " semantic_input_ordinal FROM session_events"
                            " WHERE session_id=%s AND event_class='semantic'"
                            " ORDER BY seq", (s,))
        seqs = [e[0] for e in events]
        check("multi-turn seq 1..8 no holes",
              seqs == list(range(1, 9)), seqs)
        turns = []
        for _seq, etype, _payload, turn, _ord in events:
            if turn not in turns:
                turns.append(turn)
        check("two distinct turns in first-appearance order",
              len(turns) == 2, turns)
        for i, turn in enumerate(turns):
            tev = [(e[1], e[4]) for e in events if e[3] == turn]
            check(f"turn {i + 1} event order + ordinals",
                  tev == [("turn/start", 2 * i + 1),
                          ("user/message", 2 * i + 2),
                          ("assistant/message", None),
                          ("turn/end", None)], tev)
        check("both turns closed known",
              sorted(r[0] for r in rows(
                  conn, "SELECT slot_status FROM turn_end_slots"
                        " WHERE session_id=%s", (s,))) == ["known", "known"])
        check("two assistant messages (one per turn)",
              one(conn, "SELECT count(*) FROM session_events"
                        " WHERE session_id=%s AND event_type="
                        "'assistant/message'", (s,))[0] == 2)
        check("assistant payloads per turn",
              [json.loads(r[0]) for r in rows(
                  conn, "SELECT payload FROM session_events WHERE session_id=%s"
                        " AND event_type='assistant/message' ORDER BY seq",
                  (s,))] == [expected_assistant_payload("first question"),
                             expected_assistant_payload("second question")])
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# kill-at-every-boundary chaos (P0B acceptance)
# ---------------------------------------------------------------------------

def test_kill_at_every_boundary() -> None:
    text = "chaos proof"
    baseline_session = create_loop_session(uri())
    run_user_message(uri(), baseline_session, text)
    bconn = psycopg2.connect(uri())
    try:
        baseline = semantic_trace(bconn, baseline_session)
    finally:
        bconn.close()
    check("baseline trace shape",
          [e[0] for e in baseline] == ["turn/start", "user/message",
                                       "assistant/message", "turn/end"],
          [e[0] for e in baseline])

    check("boundary list frozen", BOUNDARIES == [
        "after_user_append", "after_claim", "after_seal_commit",
        "after_worker_read", "after_fake_llm", "after_complete_commit",
        "after_finish_commit"])
    for point in ALL_KILL_POINTS:
        s = create_loop_session(uri())
        try:
            run_user_message(uri(), s, text, kill_after=point)
            check(f"[{point}] run dies at the kill point", False, "no death")
        except ProcessDeath as pd:
            check(f"[{point}] ProcessDeath at the kill point",
                  pd.point == point, pd.point)
        conn = psycopg2.connect(uri())
        try:
            # (b) invariants at the crash state itself
            assert_persisted_invariants(conn, s, f"{point}/after-kill")
            # NEW PROCESS: fresh connections, zero memory state, new command
            # ids — rerun the same user message to completion.
            r = run_user_message(uri(), s, text)
            check(f"[{point}] rerun converges to completed",
                  r["state"] == "completed", r)
            assert_persisted_invariants(conn, s, f"{point}/after-rerun")
            # (c) final semantic trace event-for-event equal to the normal
            # loop (semantic_input_ordinal + content must match)
            check(f"[{point}] semantic trace == normal loop",
                  semantic_trace(conn, s) == baseline)
            # (d) exactly one assistant/message (late/duplicate completion
            # cannot produce a second one)
            n_am = one(conn, "SELECT count(*) FROM session_events"
                             " WHERE session_id=%s AND event_type="
                             "'assistant/message'", (s,))[0]
            check(f"[{point}] exactly one assistant/message", n_am == 1, n_am)
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# session/heartbeat interference (legal observational input must never
# wedge the loop; turn bookkeeping reads the last ATTRIBUTED event)
# ---------------------------------------------------------------------------

def append_heartbeat(session_id) -> dict:
    """External session/heartbeat via the public append path."""
    conn = psycopg2.connect(uri())
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT next_seq FROM sessions WHERE session_id=%s",
                        (session_id,))
            next_seq = cur.fetchone()[0]
        conn.rollback()
        return call_append_events(
            conn, session_id, f"hb-{u()[:8]}", DRIVER, EPOCH, next_seq,
            [build_entry("session/heartbeat", {"beat": 1},
                         schema_version="sv@1",
                         canonicalizer_version="canon@1")])
    finally:
        conn.close()


def test_heartbeat_interference() -> None:
    # Mid-turn heartbeat: appended while the turn is open (after the user
    # message, before the loop advances). The same-text rerun must converge
    # — no bogus new turn, no ordinal reuse, no IDEMPOTENCY_CONFLICT.
    s = create_loop_session(uri())
    ap = append_user_message(uri(), s, "beat during turn")
    check("mid-turn fixture: user append ok", ap["appended"] is True)
    hb = append_heartbeat(s)
    check("mid-turn heartbeat accepted (lifecycle matrix: active 照常)",
          hb["outcome"] == "accepted", hb)
    r = run_user_message(uri(), s, "beat during turn")
    check("same-text rerun after mid-turn heartbeat converges",
          r["state"] == "completed", r)
    conn = psycopg2.connect(uri())
    try:
        check("mid-turn heartbeat: one turn only",
              one(conn, "SELECT count(DISTINCT turn_id) FROM session_events"
                        " WHERE session_id=%s AND turn_id IS NOT NULL", (s,))[0]
              == 1)
        check("mid-turn heartbeat: heartbeat row persisted as observational",
              one(conn, "SELECT event_class FROM session_events"
                        " WHERE session_id=%s AND event_type='session/heartbeat'",
                  (s,))[0] == "observational")
        assert_persisted_invariants(conn, s, "hb-mid-turn")
    finally:
        conn.close()

    # A DIFFERENT text after a mid-turn heartbeat is still a new turn of the
    # SAME open turn's session flow (turn not closed yet -> same turn).
    s2 = create_loop_session(uri())
    append_user_message(uri(), s2, "open beat turn")
    append_heartbeat(s2)
    r2 = run_user_message(uri(), s2, "open beat followup")
    check("different text on the still-open turn completes",
          r2["state"] == "completed", r2)

    # Between-turns heartbeat: lands after turn 1 closed (finish deferred),
    # before turn 2 opens. Turn 2 must open with the NEXT session-wide
    # ordinals (3, 4) — the pre-fix last-event inference wedged here.
    s3 = create_loop_session(uri())
    r3a = run_user_message(uri(), s3, "first beat turn", finish=False)
    check("between-turns fixture: turn 1 ready", r3a["state"] == "ready", r3a)
    hb3 = append_heartbeat(s3)
    check("between-turns heartbeat accepted", hb3["outcome"] == "accepted", hb3)
    r3b = run_user_message(uri(), s3, "second beat turn")
    check("turn 2 after between-turns heartbeat completes",
          r3b["state"] == "completed", r3b)
    conn = psycopg2.connect(uri())
    try:
        semantic = rows(
            conn,
            "SELECT event_type, semantic_input_ordinal FROM session_events"
            " WHERE session_id=%s AND event_class='semantic' ORDER BY seq",
            (s3,))
        check("turn 2 ordinals continue after turn 1 (no reuse)",
              semantic == [("turn/start", 1), ("user/message", 2),
                           ("assistant/message", None), ("turn/end", None),
                           ("turn/start", 3), ("user/message", 4),
                           ("assistant/message", None), ("turn/end", None)],
              semantic)
        check("between-turns: both turns closed known",
              sorted(r[0] for r in rows(
                  conn, "SELECT slot_status FROM turn_end_slots"
                        " WHERE session_id=%s", (s3,))) == ["known", "known"])
        assert_persisted_invariants(conn, s3, "hb-between-turns")
    finally:
        conn.close()

    # Heartbeat on a fresh session (before any turn event): the loop must
    # still open turn 1 at ordinals 1, 2.
    s4 = create_loop_session(uri())
    hb4 = append_heartbeat(s4)
    check("fresh-session heartbeat accepted", hb4["outcome"] == "accepted", hb4)
    r4 = run_user_message(uri(), s4, "fresh beat turn")
    check("loop after fresh-session heartbeat completes",
          r4["state"] == "completed", r4)
    conn = psycopg2.connect(uri())
    try:
        ordinals = rows(
            conn,
            "SELECT semantic_input_ordinal FROM session_events"
            " WHERE session_id=%s AND semantic_input_ordinal IS NOT NULL"
            " ORDER BY semantic_input_ordinal", (s4,))
        check("fresh-session heartbeat: turn opens at ordinals 1, 2",
              ordinals == [(1,), (2,)], ordinals)
        assert_persisted_invariants(conn, s4, "hb-fresh")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Duplicate-submit idempotency (Conformance 1 main assertion)
# ---------------------------------------------------------------------------

def test_duplicate_command_idempotency() -> None:
    s = create_loop_session(uri())
    text = "idempotent retry"

    ap1 = append_user_message(uri(), s, text, command_id="usr-idem-1")
    check("user append accepted", ap1["appended"] is True)

    conn = psycopg2.connect(uri())
    try:
        # Network-retry simulation on the append: same command_id, same
        # canonical request (entries + expected_seq byte-equal) — the G3
        # adjudicator must return the ORIGINAL receipt, zero new events.
        turn = ap1["turn_id"]
        entries = [
            build_entry("turn/start", {"reason": "user_message"},
                        schema_version="sv@1", canonicalizer_version="canon@1",
                        turn_id=turn, semantic_input_ordinal=1),
            build_entry("user/message", {"text": text},
                        schema_version="sv@1", canonicalizer_version="canon@1",
                        turn_id=turn, semantic_input_ordinal=2),
        ]
        r1 = call_append_events(conn, s, "usr-idem-1", DRIVER, EPOCH, 1,
                                entries)
        check("append replay path is accepted (all-duplicate batch)",
              r1["outcome"] == "accepted", r1)
        r2 = call_append_events(conn, s, "usr-idem-1", DRIVER, EPOCH, 1,
                                entries)
        check("append retry replays the original receipt",
              r2["receipt"] == r1["receipt"], (r1, r2))
        n_events = one(conn, "SELECT count(*) FROM session_events"
                             " WHERE session_id=%s", (s,))[0]
        check("append retry stored zero new events", n_events == 2, n_events)

        # claim + seal with a FIXED command id, retried after acceptance
        claim = acquire_lease(conn, s, driver=DRIVER, driver_epoch=EPOCH,
                              lease_owner="idem", lease_seconds=60)
        check("idem claim ok", claim["outcome"] == "claimed", claim)
        prompt = {"messages": [{"role": "user", "text": text}],
                  "seed_text": text}
        turn = ap1["turn_id"]
        seal1 = seal_decision_step(conn, s, turn, driver=DRIVER,
                                   driver_epoch=EPOCH,
                                   session_fence=claim["session_fence"],
                                   prompt=prompt, command_id="seal-idem-1")
        check("seal accepted", seal1["result"]["outcome"] == "accepted")
        seal2 = seal_decision_step(conn, s, turn, driver=DRIVER,
                                   driver_epoch=EPOCH,
                                   session_fence=claim["session_fence"],
                                   prompt=prompt, command_id="seal-idem-1",
                                   step_id=seal1["step_id"],
                                   effect_id=seal1["effect_id"])
        check("seal retry replays the original receipt",
              seal2["result"]["receipt"] == seal1["result"]["receipt"])
        check("seal retry: still exactly one step",
              one(conn, "SELECT count(*) FROM steps WHERE session_id=%s",
                  (s,))[0] == 1)

        effect = seal1["effect_id"]
        fence = seal1["result"]["receipt"]["session_fence"]
        job = seal1["result"]["receipt"]["job_fence"]
        dsp1 = dispatch_effect(conn, s, "dsp-idem-1", effect, DRIVER, EPOCH,
                               fence, job)
        check("dispatch accepted", dsp1["outcome"] == "accepted")
        dsp2 = dispatch_effect(conn, s, "dsp-idem-1", effect, DRIVER, EPOCH,
                               fence, job)
        check("dispatch retry replays the original receipt",
              dsp2["receipt"] == dsp1["receipt"])
        check("dispatch retry: dispatch_count unchanged",
              one(conn, "SELECT dispatch_count FROM effect_requests"
                        " WHERE effect_id=%s", (effect,))[0] == 1)

        rconn = psycopg2.connect(uri())
        rconn.autocommit = True
        desc = read_effect_descriptor(rconn, s, effect)
        rconn.close()
        result = FakeLLM().generate(desc)
        kw = dict(driver=DRIVER, driver_epoch=EPOCH,
                  dispatch_session_fence=desc["dispatch_session_fence"],
                  job_fence=desc["current_job_fence"],
                  attempt_no=desc["attempt_no"],
                  step_id=desc["step_id"],
                  request_hash=desc["request_hash"],
                  idempotency_key=desc["idempotency_key"],
                  outcome=result["outcome"], message=result["message"],
                  tools=result["tools"],
                  decision_only=result["decision_only"],
                  final_tools=result["final_tools"],
                  evidence=result["evidence"])
        cmp1 = complete_effect(conn, s, "cmp-idem-1", effect, **kw)
        check("complete accepted", cmp1["outcome"] == "accepted")
        n_events = one(conn, "SELECT count(*) FROM session_events"
                             " WHERE session_id=%s", (s,))[0]
        cmp2 = complete_effect(conn, s, "cmp-idem-1", effect, **kw)
        check("complete retry replays the original receipt",
              cmp2["receipt"] == cmp1["receipt"])
        check("complete retry stored zero new events",
              one(conn, "SELECT count(*) FROM session_events"
                        " WHERE session_id=%s", (s,))[0] == n_events)
        check("exactly one assistant/message after the retry",
              one(conn, "SELECT count(*) FROM session_events"
                        " WHERE session_id=%s AND event_type="
                        "'assistant/message'", (s,))[0] == 1)
        # finish off the session so later stages see a clean terminal state
        claim2 = acquire_lease(conn, s, driver=DRIVER, driver_epoch=EPOCH,
                               lease_owner="idem", lease_seconds=60)
        rf = finish_session(conn, s, "fin-idem-1", DRIVER, EPOCH,
                            claim2["session_fence"])
        check("finish accepted", rf["outcome"] == "accepted", rf)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# yield / worker handoff
# ---------------------------------------------------------------------------

def test_yield_worker_handoff() -> None:
    # Variant A: worker A claims then yields before any work; a stale-fence
    # control write is rejected; worker B (fresh process context) runs the
    # whole seal -> dispatch -> complete -> finish chain.
    s = create_loop_session(uri())
    append_user_message(uri(), s, "handoff A")
    w1 = psycopg2.connect(uri())
    try:
        rc = claim_session(w1, s, DRIVER, EPOCH, lease_owner="worker-A",
                           lease_seconds=60)
        check("A claim ok", rc["outcome"] == "claimed", rc)
        ry = yield_session(w1, s, DRIVER, EPOCH, rc["session_fence"],
                           lease_owner="worker-A")
        check("A yield ok, fence incremented",
              ry == {"outcome": "yielded",
                     "session_fence": rc["session_fence"] + 1}, ry)
        check("A yield left state ready",
              one(w1, "SELECT state FROM sessions WHERE session_id=%s",
                  (s,))[0] == "ready")
        stale = prepare_step(w1, s, f"seal-stale-{u()[:6]}", DRIVER, EPOCH,
                             rc["session_fence"], u(), u(), u())
        check("A old-fence seal rejected (SESSION_FENCE_STALE)",
              stale["outcome"] == "rejected_stale"
              and stale["code"] == "SESSION_FENCE_STALE", stale)
    finally:
        w1.close()
    r = run_user_message(uri(), s, "handoff A")  # worker B: fresh process
    check("worker B completes the loop", r["state"] == "completed", r)

    conn = psycopg2.connect(uri())
    try:
        check("A/B handoff: turn closed known",
              one(conn, "SELECT slot_status FROM turn_end_slots"
                        " WHERE session_id=%s", (s,))[0] == "known")
        check("A/B handoff: full op chain (usr,seal,dsp,cmp,fin)",
              dict(rows(conn, "SELECT command_kind, count(*) FROM"
                              " command_receipts WHERE session_id=%s"
                              " AND outcome='accepted' GROUP BY 1",
                              (s,))) ==
              {"append_events": 1, "prepare_step": 1, "dispatch_effect": 1,
               "complete_effect": 1, "finish_session": 1})
        check("A/B handoff: stale rejection kept its audit receipt",
              one(conn, "SELECT count(*) FROM command_receipts"
                        " WHERE session_id=%s AND outcome='rejected_stale'",
                  (s,))[0] == 1)
        assert_persisted_invariants(conn, s, "handoff-A")

        # Variant B: after the seal-driven work closes the turn (the only
        # reachable claimed->ready point once the seal auto-revokes the
        # lease), the coordinator claims at step (6), yields instead of
        # finishing; a new worker claims with the incremented fence — the
        # old-fence finish is rejected — and completes the session.
        s2 = create_loop_session(uri())
        append_user_message(uri(), s2, "handoff B")
        r2 = advance_session(uri(), s2, finish=False)
        check("B advance (no finish) closes the turn, stays ready",
              r2["state"] == "ready"
              and r2["actions"] == ["claim", "seal", "worker"], r2)
        w2 = psycopg2.connect(uri())
        try:
            rc2 = claim_session(w2, s2, DRIVER, EPOCH,
                                lease_owner="coord-A", lease_seconds=60)
            check("B claim ok", rc2["outcome"] == "claimed", rc2)
            ry2 = yield_session(w2, s2, DRIVER, EPOCH, rc2["session_fence"],
                                lease_owner="coord-A")
            check("B yield ok, fence incremented",
                  ry2["outcome"] == "yielded"
                  and ry2["session_fence"] == rc2["session_fence"] + 1, ry2)
            stale2 = finish_session(w2, s2, f"fin-stale-{u()[:6]}", DRIVER,
                                    EPOCH, rc2["session_fence"])
            check("B old-fence finish rejected (SESSION_FENCE_STALE)",
                  stale2["outcome"] == "rejected_stale"
                  and stale2["code"] == "SESSION_FENCE_STALE", stale2)
        finally:
            w2.close()
        r3 = advance_session(uri(), s2, finish=True)  # worker B2 finishes
        check("B new worker finishes the session",
              r3["state"] == "completed", r3)
        check("B turn closed known",
              one(conn, "SELECT slot_status FROM turn_end_slots"
                        " WHERE session_id=%s", (s2,))[0] == "known")
        assert_persisted_invariants(conn, s2, "handoff-B")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Failure forms (injected faults -> unknown settlement)
# ---------------------------------------------------------------------------

def test_failure_forms() -> None:
    for fault in ("provider_error", "timeout"):
        s = create_loop_session(uri())
        r = run_user_message(uri(), s, f"boom {fault}",
                             fake_llm=FakeLLM(injected_fault=fault))
        check(f"[{fault}] session NOT completed (stalls blocked)",
              r["state"] == "blocked_unknown_effect", r)
        conn = psycopg2.connect(uri())
        try:
            check(f"[{fault}] no assistant/message",
                  one(conn, "SELECT count(*) FROM session_events"
                            " WHERE session_id=%s AND event_type="
                            "'assistant/message'", (s,))[0] == 0)
            check(f"[{fault}] effect not succeeded (unknown_outcome)",
                  one(conn, "SELECT status FROM effect_requests"
                            " WHERE session_id=%s", (s,))[0]
                  == "unknown_outcome")
            check(f"[{fault}] attempt unknown_outcome",
                  one(conn, "SELECT status FROM effect_attempts"
                            " WHERE effect_id IN (SELECT effect_id FROM"
                            " effect_requests WHERE session_id=%s)",
                      (s,))[0] == "unknown_outcome")
            check(f"[{fault}] provisional turn/end {{outcome:unknown}}",
                  one(conn, "SELECT payload FROM session_events"
                            " WHERE session_id=%s AND event_type="
                            "'turn/end'", (s,))[0]
                  == '{"outcome":"unknown"}')
            check(f"[{fault}] provisional slot",
                  one(conn, "SELECT slot_status FROM turn_end_slots"
                            " WHERE session_id=%s", (s,))[0]
                  == "provisional")
            check(f"[{fault}] session state blocked_unknown_effect",
                  one(conn, "SELECT state FROM sessions WHERE session_id=%s",
                      (s,))[0] == "blocked_unknown_effect")
            # canonicalizer: unique provisional unknown end, no known close
            trace = normalize(normalize_input_from_db(conn, s))
            ends = [e for e in trace if e["event_type"] == "turn/end"]
            check(f"[{fault}] normalize(): single provisional unknown end",
                  len(ends) == 1
                  and ends[0]["payload"] == {"outcome": "unknown",
                                             "reason": "unknown_after_dispatch"},
                  ends)
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# External IO strictly outside transactions
# ---------------------------------------------------------------------------

def test_external_io_outside_tx() -> None:
    observed: dict[str, list[dict]] = {}

    def hook(info: dict) -> None:
        observed.setdefault(info["boundary"], []).append(info)

    s = create_loop_session(uri())
    run_user_message(uri(), s, "io boundary check", on_boundary=hook)
    check("worker-read boundary observed", "after_worker_read" in observed)
    check("fake-llm boundary observed", "after_fake_llm" in observed)
    check("complete boundary observed", "after_complete_commit" in observed)

    read_info = observed["after_worker_read"][0]
    check("worker read connection is autocommit (no tx)",
          read_info["read_autocommit"] is True)
    check("worker read left the connection IDLE",
          read_info["read_status"] == STATUS_READY
          and read_info["write_status"] == STATUS_READY,
          (read_info["read_status"], read_info["write_status"]))

    llm_info = observed["after_fake_llm"][0]
    statuses = llm_info["tx_status_at_llm"]
    check("FakeLLM call point: no connection holds an open transaction",
          all(st == STATUS_READY for st in statuses)
          and STATUS_BEGIN not in statuses, statuses)
    check("FakeLLM call point: read connection still autocommit",
          llm_info["read_autocommit"] is True)

    comp_info = observed["after_complete_commit"][0]
    check("complete tx: write connection IDLE before the settlement tx",
          comp_info["status_before_complete"] == STATUS_READY,
          comp_info["status_before_complete"])
    check("complete tx: write connection IDLE after commit",
          comp_info["status_after_complete"] == STATUS_READY,
          comp_info["status_after_complete"])


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def main() -> int:
    check("setup", setup_db() == 0)
    test_normal_closed_loop()
    test_multi_turn()
    test_kill_at_every_boundary()
    test_heartbeat_interference()
    test_duplicate_command_idempotency()
    test_yield_worker_handoff()
    test_failure_forms()
    test_external_io_outside_tx()
    print("[G5] all gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
