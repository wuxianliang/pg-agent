"""G6 gate: v8 tools stage — the tools seal (second seal path), tool
batches, slot-level occurrence identity (Conformance 1(4)), reverse-order
parallel completion (Conformance 7), the "tools -> re-decide -> answer"
intermediate-ready flow (Conformance 5), seal receipt idempotency/replay,
CAS zero-side-effect negatives, coordinator continuation, and tools-phase
chaos (kill at tools boundaries; partial tool completion convergence).

Run: uv run python v8/tools/test_tools.py  (exit 0 = pass)
"""
from __future__ import annotations

import hashlib
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
from v8.effect.client import (
    claim_session,
    complete_effect,
    dispatch_effect,
    finish_session,
    prepare_step,
)
from v8.events.canonicalizer import normalize
from v8.events.client import build_entry, call_append_events, create_session
from v8.loop.runtime import (
    ProcessDeath,
    TOOLS_KILL_POINTS,
    create_loop_session,
    run_user_message,
    worker_execute,
)
from v8.tools.client import (
    build_tool_slots,
    complete_tool_effect,
    seal_batch,
    seal_event_key,
)
from v8.tools.setup_db import DB, main as setup_db

DRIVER = "drv"
EPOCH = 1
SV, CV = "sv@1", "canon@1"


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f": {detail}" if detail else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def u() -> str:
    return str(uuid.uuid4())


def uri() -> str:
    return get_server().get_uri(DB)


def rows(conn, sql: str, params: tuple = ()) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        out = cur.fetchall()
    conn.rollback()
    return out


def one(conn, sql: str, params: tuple = ()):
    r = rows(conn, sql, params)
    return r[0] if r else None


def canon(obj) -> tuple[str, str]:
    return canonicalize(escape_dollar_keys(obj))


def exec_sql(conn, sql: str, params: tuple = ()) -> None:
    with conn.cursor() as cur:
        cur.execute(sql, params)
    conn.commit()


def good_evidence() -> dict:
    return {"class": "known_success",
            "provider_receipt": {"receipt_id": f"pr-{u()[:8]}"}}


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def two_slot_plan(seed: str) -> list:
    """Two tool calls with the SAME tool and the SAME arguments — only
    tool_call_id differs (Conformance 1 scenario (4) shape)."""
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return [
        {"tool_call_id": f"call-{digest[:12]}-0", "tool": "fake_tool",
         "arguments": {"echo": seed}},
        {"tool_call_id": f"call-{digest[:12]}-1", "tool": "fake_tool",
         "arguments": {"echo": seed}},
    ]


def decision_fixture(conn, seed: str, driver: str = DRIVER):
    """create -> public user/message (+turn/start) -> claim -> prepare_step
    (decision seal) -> dispatch -> complete with the NON-EMPTY tools plan.

    Returns the full fixture dict: ids, the persisted step row, the plan,
    the decision result identity, the completion receipt and the
    post-completion session fence.
    """
    s = u()
    turn = u()
    create_session(conn, s, driver)
    r_app = call_append_events(conn, s, f"usr-{u()[:8]}", driver, EPOCH, 1, [
        build_entry("turn/start", {"reason": "user_message"},
                    schema_version=SV, canonicalizer_version=CV,
                    turn_id=turn, semantic_input_ordinal=1),
        build_entry("user/message", {"text": f"tools for {seed}"},
                    schema_version=SV, canonicalizer_version=CV,
                    turn_id=turn, semantic_input_ordinal=2),
    ])
    check("fixture append accepted", r_app["outcome"] == "accepted", r_app)

    step, effect = u(), u()
    rh, ik = f"rh-{u()[:10]}", f"ik-{u()[:10]}"
    plan = two_slot_plan(seed)
    r0 = claim_session(conn, s, driver)
    check("fixture claim ok", r0["outcome"] == "claimed", r0)
    rs = prepare_step(conn, s, f"seal-{u()[:8]}", driver, EPOCH,
                      r0["session_fence"], step, turn, effect,
                      request_hash=rh, idempotency_key=ik)
    check("fixture decision seal accepted", rs["outcome"] == "accepted", rs)
    rd = dispatch_effect(conn, s, f"dsp-{u()[:8]}", effect, driver, EPOCH,
                         rs["receipt"]["session_fence"],
                         rs["receipt"]["job_fence"])
    check("fixture dispatch accepted", rd["outcome"] == "accepted", rd)
    message = {"text": f"plan-first:{seed}", "model": "fake-llm@1"}
    rc = complete_effect(
        conn, s, f"cmp-{u()[:8]}", effect, driver, EPOCH,
        dispatch_session_fence=r0["session_fence"],
        job_fence=rs["receipt"]["job_fence"], step_id=step,
        request_hash=rh, idempotency_key=ik, outcome="succeeded",
        message=message, tools=plan, decision_only=False, final_tools=True,
        evidence=good_evidence())
    check("fixture decision complete accepted", rc["outcome"] == "accepted",
          rc)
    step_row = one(
        conn, "SELECT status, stage, sealed_batch_no, plan_canonical,"
        " plan_hash, decision_only, final_tools, pending_effect_count"
        " FROM steps WHERE step_id = %s", (step,))
    dec_event_key = next(e["event_key"] for e in rc["receipt"]["events"]
                         if e["event_type"] == "assistant/message")
    return {
        "session": s, "turn": turn, "step": step, "effect": effect,
        "claim_fence": r0["session_fence"],
        "post_seal_fence": rs["receipt"]["session_fence"],
        "fence_after": one(conn, "SELECT session_fence FROM sessions"
                                 " WHERE session_id=%s", (s,))[0],
        "job_fence": rs["receipt"]["job_fence"], "rh": rh, "ik": ik,
        "plan": plan, "step_row": step_row,
        "decision": {"effect_id": effect, "attempt_no": 1,
                     "result_hash": rc["receipt"]["result_hash"],
                     "event_key": dec_event_key},
        "complete_receipt": rc,
    }


def claim_fence(conn, fx, *, driver: str = DRIVER, epoch: int = EPOCH):
    """Claim the coordination lease from the post-decision ready state."""
    r = claim_session(conn, fx["session"], driver)
    check("seal claim ok", r["outcome"] == "claimed", r)
    return r["session_fence"]


def seal_side_effect_counts(conn, s) -> tuple:
    """The zero-side-effect assertion tuple for the tools seal."""
    return (
        one(conn, "SELECT count(*) FROM batches WHERE session_id=%s", (s,))[0],
        one(conn, "SELECT count(*) FROM effect_requests WHERE session_id=%s",
            (s,))[0],
        one(conn, "SELECT count(*) FROM effect_attempts WHERE session_id=%s",
            (s,))[0],
        one(conn, "SELECT count(*) FROM session_events WHERE session_id=%s"
                  " AND event_type='tool/call'", (s,))[0],
    )


def assert_no_seq_holes(conn, s, label: str) -> None:
    seqs = [r[0] for r in rows(
        conn, "SELECT seq FROM session_events WHERE session_id=%s"
              " ORDER BY seq", (s,))]
    check(f"[{label}] no seq holes",
          seqs == list(range(1, len(seqs) + 1)), seqs)


def assert_invariants(conn, s, label: str) -> None:
    """Conformance 1 invariants: no persisted planned step/effect, exactly
    one first attempt per effect (attempt_no=1 only), no seq holes."""
    check(f"[{label}] no persisted planned step",
          one(conn, "SELECT count(*) FROM steps WHERE session_id=%s"
                    " AND status='planned'", (s,))[0] == 0)
    check(f"[{label}] no persisted planned effect",
          one(conn, "SELECT count(*) FROM effect_requests WHERE session_id=%s"
                    " AND status='planned'", (s,))[0] == 0)
    att = one(conn, "SELECT count(*), count(DISTINCT effect_id),"
                    " min(attempt_no), max(attempt_no) FROM effect_attempts"
                    " WHERE session_id=%s", (s,))
    check(f"[{label}] exactly one first attempt per effect",
          att[0] == att[1] and (att[0] == 0 or
                                (att[2] == 1 and att[3] == 1)), att)
    assert_no_seq_holes(conn, s, label)


def normalize_input(conn, s) -> list:
    """session_events -> normalize() input dicts (dispatch_ordinal joined
    from the effect row; effect status as the terminal/pending signal)."""
    out = []
    for (event_type, payload, turn_id, step_id, effect_id, sio, dord,
         status) in rows(
            conn,
            "SELECT se.event_type, se.payload, se.turn_id::text,"
            " se.step_id::text, se.effect_id::text,"
            " se.semantic_input_ordinal, er.dispatch_ordinal, er.status"
            " FROM session_events se"
            " LEFT JOIN effect_requests er ON er.effect_id = se.effect_id"
            " WHERE se.session_id=%s ORDER BY se.seq", (s,)):
        out.append({"event_type": event_type, "payload": json.loads(payload),
                    "turn_id": turn_id, "step_id": step_id,
                    "effect_id": effect_id,
                    "semantic_input_ordinal": sio,
                    "dispatch_ordinal": dord, "effect_status": status})
    return out


def labeled(events: list) -> list:
    """Replace volatile ids with positional labels so traces of two
    independent runs become comparable (same logical shape)."""
    step_labels: dict = {}
    effect_labels: dict = {}
    out = []
    for d in events:
        e = dict(d)
        e["turn_id"] = "T" if e.get("turn_id") else None
        for key, labels, prefix in (("step_id", step_labels, "S"),
                                    ("effect_id", effect_labels, "E")):
            v = e.get(key)
            if v is None:
                e[key] = None
                continue
            if v not in labels:
                labels[v] = f"{prefix}{len(labels)}"
            e[key] = labels[v]
        out.append(e)
    return out


def observable_trace(conn, s) -> list:
    return normalize(labeled(normalize_input(conn, s)))


def semantic_projection(conn, s) -> list:
    """event_type + payload + public ordinal in seq order (chaos
    equivalence projection; receipts/audit/seq may differ, this may not)."""
    return [(t, json.loads(p), o) for t, p, o in rows(
        conn, "SELECT event_type, payload, semantic_input_ordinal"
              " FROM session_events WHERE session_id=%s"
              " AND event_class='semantic' ORDER BY seq", (s,))]


# ---------------------------------------------------------------------------
# G6 main
# ---------------------------------------------------------------------------

def main() -> int:
    check("setup", setup_db() == 0)
    conn = psycopg2.connect(uri())

    # =====================================================================
    # 1. complete_effect non-empty-plan branch (task item 1)
    # =====================================================================
    fx = decision_fixture(conn, "item1")
    st = fx["step_row"]
    check("decision step aggregates ready/stage=decision",
          st[0] == "ready" and st[1] == "decision", st)
    check("decision marks frozen (decision_only=false, final_tools=true)",
          st[5] is False and st[6] is True, st)
    plan_canonical, _ = canon(fx["plan"])
    check("normalized plan persisted verbatim",
          st[3] == plan_canonical, st[3][:60])
    check("plan_hash is sha256(plan_canonical)",
          st[4] == hashlib.sha256(plan_canonical.encode()).hexdigest())
    check("step NOT terminalized", st[0] == "ready")
    check("session intermediate state ready (Conformance 5)",
          one(conn, "SELECT state FROM sessions WHERE session_id=%s",
              (fx["session"],))[0] == "ready")
    check("assistant/message event persisted for the decision",
          one(conn, "SELECT count(*) FROM session_events WHERE session_id=%s"
                    " AND event_type='assistant/message'",
              (fx["session"],))[0] == 1)
    check("no turn/end yet (turn stays open for the tools phase)",
          one(conn, "SELECT count(*) FROM session_events WHERE session_id=%s"
                    " AND event_type='turn/end'", (fx["session"],))[0] == 0)
    assert_invariants(conn, fx["session"], "item1")

    # =====================================================================
    # 2. tools seal positive + Conformance 1 first-attempt / publish-ready
    # =====================================================================
    fence = claim_fence(conn, fx)
    slots = build_tool_slots(fx["plan"])
    pre_seq = one(conn, "SELECT next_seq FROM sessions WHERE session_id=%s",
                  (fx["session"],))[0]
    pre_iso = one(conn, "SELECT coalesce(max(internal_semantic_ordinal), 0)"
                        " FROM session_events WHERE session_id=%s",
                  (fx["session"],))[0]
    seal_cmd = f"tseal-{u()[:8]}"
    r = seal_batch(conn, fx["session"], seal_cmd, DRIVER, EPOCH,
                   fence, fx["step"], 1, fx["decision"],
                   fx["step_row"][4], slots)
    check("tools seal accepted", r["outcome"] == "accepted", r)
    receipt = r["receipt"]
    batch_id = receipt["batch_id"]

    check("tools batch sealed (kind=tools, sealed_batch_no=2)",
          one(conn, "SELECT kind, sealed_batch_no, sealed FROM batches"
                    " WHERE batch_id=%s", (batch_id,)) == ("tools", 2, True))
    check("step advanced to tools/waiting_effect with sealed_batch_no=2",
          one(conn, "SELECT stage, status, sealed_batch_no,"
                    " pending_effect_count FROM steps WHERE step_id=%s",
              (fx["step"],)) == ("tools", "waiting_effect", 2, 2))
    sess = one(conn, "SELECT state, session_fence, lease_owner FROM sessions"
                     " WHERE session_id=%s", (fx["session"],))
    check("session aggregated waiting_effect, fence bumped, lease revoked",
          sess[0] == "waiting_effect" and sess[1] == fence + 1
          and sess[2] is None, sess)

    eff_rows = rows(
        conn, "SELECT effect_id, dispatch_ordinal, tool_call_id,"
              " effect_kind, execution_mode, status, current_job_fence,"
              " request_hash, idempotency_key, retry_class, max_attempts"
              " FROM effect_requests WHERE batch_id=%s"
              " ORDER BY dispatch_ordinal", (batch_id,))
    check("two tool effects at fixed ordinals 0,1",
          [e[1] for e in eff_rows] == [0, 1], eff_rows)
    check("effects are tool/non_streaming/ready (publish-as-ready)",
          all(e[3] == "tool" and e[4] == "non_streaming" and e[5] == "ready"
              for e in eff_rows), eff_rows)
    check("slot identity frozen (tool_call_id/request_hash/idempotency)",
          [(e[2], e[7], e[8]) for e in eff_rows]
          == [(sl["tool_call_id"], sl["request_hash"], sl["idempotency_key"])
              for sl in slots])
    att_rows = rows(
        conn, "SELECT a.effect_id, a.attempt_no, a.status,"
              " a.dispatch_job_fence, er.current_job_fence"
              " FROM effect_attempts a JOIN effect_requests er"
              " ON er.effect_id = a.effect_id WHERE er.batch_id=%s",
        (batch_id,))
    check("first attempt created in the seal transaction (attempt_no=1)",
          sorted((str(a[0]), a[1]) for a in att_rows)
          == sorted((str(e[0]), 1) for e in eff_rows))
    check("attempt ready + job fence frozen at the same value",
          all(a[2] == "ready" and a[3] == a[4] for a in att_rows), att_rows)

    call_rows = rows(
        conn, "SELECT seq, event_key, effect_id, step_id, turn_id,"
              " internal_semantic_ordinal, payload, command_id"
              " FROM session_events WHERE session_id=%s"
              " AND event_type='tool/call' ORDER BY seq", (fx["session"],))
    check("two independent tool/call events, contiguous seq from next_seq",
          [c[0] for c in call_rows] == [pre_seq, pre_seq + 1],
          [c[0] for c in call_rows])
    check("tool/call internal semantic ordinals allocated consecutively",
          [c[5] for c in call_rows] == [pre_iso + 1, pre_iso + 2])
    check("tool/call event_keys mutually distinct (slot occurrence identity)",
          len({c[1] for c in call_rows}) == 2)
    check("tool/call payload carries its slot tool_call_id",
          all(json.loads(c[6])["tool_call_id"] == sl["tool_call_id"]
              for c, sl in zip(call_rows, slots)))
    check("tool/call attributed to step+effect of its slot",
          all(str(c[3]) == fx["step"] and str(c[2]) == str(eff_rows[i][0])
              for i, c in enumerate(call_rows)))
    check("event_key equals the python seal_event_key mirror",
          all(c[1] == seal_event_key(
                  fx["session"], "tool/call", batch_id, i,
                  hashlib.sha256(
                      slots[i]["payload_canonical"].encode()).hexdigest())
              for i, c in enumerate(call_rows)))
    check("receipt carries batch/effects/events identity",
          receipt["sealed_batch_no"] == 2
          and len(receipt["effects"]) == 2 and len(receipt["events"]) == 2
          and receipt["step_status"] == "waiting_effect")
    assert_invariants(conn, fx["session"], "tools-seal")

    # =====================================================================
    # 3. seal idempotency (Conformance 1)
    # =====================================================================
    before = seal_side_effect_counts(conn, fx["session"])
    orig_receipt_json = json.dumps(receipt, sort_keys=True)

    # (a) same command_id network retry -> adjudicator receipt replay
    r2 = seal_batch(conn, fx["session"], seal_cmd, DRIVER, EPOCH,
                    fence, fx["step"], 1, fx["decision"],
                    fx["step_row"][4], slots)
    check("same-command retry returns the original receipt",
          r2["outcome"] == "accepted"
          and json.dumps(r2["receipt"], sort_keys=True) == orig_receipt_json)
    check("same-command retry: still exactly one tools batch / two effects",
          seal_side_effect_counts(conn, fx["session"]) == before)

    # (b) NEW command_id, identical result/plan/slot payload -> original
    # seal receipt + referencing receipt saved for the new command_id
    cmd_b = f"tseal-replay-{u()[:8]}"
    r3 = seal_batch(conn, fx["session"], cmd_b, DRIVER, EPOCH, fence,
                    fx["step"], 1, fx["decision"], fx["step_row"][4], slots)
    check("new-command replay accepted, returns the ORIGINAL seal receipt",
          r3["outcome"] == "accepted"
          and json.dumps({k: v for k, v in r3["receipt"].items()
                          if k not in ("replay", "replay_of_command_id")},
                         sort_keys=True) == orig_receipt_json)
    check("referencing receipt marks replay + original command",
          r3["receipt"].get("replay") is True
          and r3["receipt"].get("replay_of_command_id") == seal_cmd)
    ref = one(conn, "SELECT outcome, code, result_canonical"
                    " FROM command_receipts WHERE session_id=%s"
                    " AND command_id=%s", (fx["session"], cmd_b))
    check("referencing receipt persisted for the new command_id",
          ref is not None and ref[0] == "accepted"
          and json.loads(ref[2])["batch_id"] == batch_id)
    check("replay: zero new side effects",
          seal_side_effect_counts(conn, fx["session"]) == before)

    # (c) new command_id, DIFFERENT slot payload -> mismatch, zero effects
    bad_slots = [dict(slots[0]), dict(slots[1])]
    bad_slots[1]["request_hash"] = "tampered"
    r4 = seal_batch(conn, fx["session"], f"tseal-bad-{u()[:8]}", DRIVER,
                    EPOCH, fence, fx["step"], 1, fx["decision"],
                    fx["step_row"][4], bad_slots)
    check("inconsistent slot payload -> SEAL_MISMATCH",
          r4["outcome"] == "rejected_mismatch"
          and r4["code"] == "SEAL_MISMATCH", r4)
    check("mismatch rejection: zero side effects",
          seal_side_effect_counts(conn, fx["session"]) == before)

    # (d) new command_id, different plan_hash -> mismatch
    r5 = seal_batch(conn, fx["session"], f"tseal-bad-{u()[:8]}", DRIVER,
                    EPOCH, fence, fx["step"], 1, fx["decision"],
                    "deadbeef", slots)
    check("inconsistent plan_hash -> SEAL_MISMATCH",
          r5["outcome"] == "rejected_mismatch"
          and r5["code"] == "SEAL_MISMATCH", r5)

    # (e) new command_id, wrong decision result identity -> mismatch
    bad_dec = dict(fx["decision"])
    bad_dec["result_hash"] = "0" * 64
    r6 = seal_batch(conn, fx["session"], f"tseal-bad-{u()[:8]}", DRIVER,
                    EPOCH, fence, fx["step"], 1, bad_dec,
                    fx["step_row"][4], slots)
    check("inconsistent decision identity -> SEAL_MISMATCH",
          r6["outcome"] == "rejected_mismatch"
          and r6["code"] == "SEAL_MISMATCH", r6)
    check("all mismatch rejections: still zero side effects",
          seal_side_effect_counts(conn, fx["session"]) == before)

    # =====================================================================
    # 4. tool dispatch/complete via the G4 channel + full two-step flow
    # =====================================================================
    effects = [str(e[0]) for e in eff_rows]
    job_fences = {str(e[0]): e[6] for e in eff_rows}
    seal_fence = fence  # the fence frozen into the attempts at seal time

    rd0 = dispatch_effect(conn, fx["session"], f"dsp-{u()[:8]}",
                          effects[0], DRIVER, EPOCH, fence + 1,
                          job_fences[effects[0]])
    check("tool dispatch accepted (binds the existing attempt)",
          rd0["outcome"] == "accepted", rd0)
    check("tool dispatch did not create any attempt",
          one(conn, "SELECT count(*), count(DISTINCT effect_id)"
                    " FROM effect_attempts WHERE session_id=%s"
                    " AND effect_id IN (SELECT effect_id FROM"
                    " effect_requests WHERE batch_id=%s)",
              (fx["session"], batch_id)) == (2, 2))

    out0 = {"echo": "item1", "tool": "fake_tool", "kind": "fake-tool@1"}
    rc0 = complete_tool_effect(
        conn, fx["session"], f"cmp-{u()[:8]}", effects[0], DRIVER, EPOCH,
        dispatch_session_fence=seal_fence, job_fence=job_fences[effects[0]],
        step_id=fx["step"], request_hash=slots[0]["request_hash"],
        idempotency_key=slots[0]["idempotency_key"], outcome="succeeded",
        tool_call_id=slots[0]["tool_call_id"], output=out0,
        evidence=good_evidence())
    check("tool completion accepted", rc0["outcome"] == "accepted", rc0)
    check("tool effect+attempt succeeded",
          one(conn, "SELECT er.status, a.status FROM effect_requests er"
                    " JOIN effect_attempts a ON a.effect_id=er.effect_id"
                    " AND a.attempt_no=er.attempt_no WHERE er.effect_id=%s",
              (effects[0],)) == ("succeeded", "succeeded"))
    check("tool/result semantic event SQL-generated",
          one(conn, "SELECT count(*) FROM session_events WHERE session_id=%s"
                    " AND event_type='tool/result' AND effect_id=%s",
              (fx["session"], effects[0]))[0] == 1)
    check("pending sibling keeps step/session waiting_effect",
          one(conn, "SELECT status, pending_effect_count FROM steps"
                    " WHERE step_id=%s", (fx["step"],))
          == ("waiting_effect", 1)
          and one(conn, "SELECT state FROM sessions WHERE session_id=%s",
                  (fx["session"],))[0] == "waiting_effect")

    # wrong tool_call_id in the payload is a stable rejection
    rd1 = dispatch_effect(conn, fx["session"], f"dsp-{u()[:8]}",
                          effects[1], DRIVER, EPOCH, fence + 1,
                          job_fences[effects[1]])
    check("tool1 dispatch accepted", rd1["outcome"] == "accepted", rd1)
    rbad = complete_tool_effect(
        conn, fx["session"], f"cmp-{u()[:8]}", effects[1], DRIVER, EPOCH,
        dispatch_session_fence=seal_fence, job_fence=job_fences[effects[1]],
        step_id=fx["step"], request_hash=slots[1]["request_hash"],
        idempotency_key=slots[1]["idempotency_key"], outcome="succeeded",
        tool_call_id=slots[0]["tool_call_id"], output=out0,
        evidence=good_evidence())
    check("tool result with wrong tool_call_id -> TOOL_RESULT_MISMATCH",
          rbad["outcome"] == "rejected_mismatch"
          and rbad["code"] == "TOOL_RESULT_MISMATCH", rbad)

    rc1 = complete_tool_effect(
        conn, fx["session"], f"cmp-{u()[:8]}", effects[1], DRIVER, EPOCH,
        dispatch_session_fence=seal_fence, job_fence=job_fences[effects[1]],
        step_id=fx["step"], request_hash=slots[1]["request_hash"],
        idempotency_key=slots[1]["idempotency_key"], outcome="succeeded",
        tool_call_id=slots[1]["tool_call_id"], output=out0,
        evidence=good_evidence())
    check("second tool completion accepted", rc1["outcome"] == "accepted",
          rc1)
    step_final = one(conn, "SELECT status, stage, outcome_code, closed_at"
                           " FROM steps WHERE step_id=%s", (fx["step"],))
    check("final_tools all-succeeded -> step succeeded/stage=closed",
          step_final[0] == "succeeded" and step_final[1] == "closed"
          and step_final[2] == "SUCCEEDED" and step_final[3] is not None,
          step_final)
    check("session intermediate state ready, NOT completed (Conformance 5)",
          one(conn, "SELECT state FROM sessions WHERE session_id=%s",
              (fx["session"],))[0] == "ready")
    check("turn still open (no decision_only closer yet)",
          one(conn, "SELECT count(*) FROM session_events WHERE session_id=%s"
                    " AND event_type='turn/end'", (fx["session"],))[0] == 0)

    # finish is not yet possible: the turn is not closed
    rf0 = claim_session(conn, fx["session"], DRIVER)
    rfin0 = finish_session(conn, fx["session"], f"fin-{u()[:8]}", DRIVER,
                           EPOCH, rf0["session_fence"])
    check("finish before the closing decision -> SESSION_NOT_FINALIZABLE",
          rfin0["outcome"] == "rejected_mismatch"
          and rfin0["code"] == "SESSION_NOT_FINALIZABLE", rfin0)

    # re-seal pointing past the sealed batch (expected=2): the step is no
    # longer ready/stage=decision -> members and ordinals immutable.
    r7 = seal_batch(conn, fx["session"], f"tseal-re2-{u()[:8]}", DRIVER,
                    EPOCH, rf0["session_fence"], fx["step"], 2,
                    fx["decision"], fx["step_row"][4], slots)
    check("re-seal at expected=2 -> STEP_NOT_SEALABLE (stage now closed)",
          r7["outcome"] == "rejected_mismatch"
          and r7["code"] == "STEP_NOT_SEALABLE", r7)
    check("re-seal negative: zero side effects",
          seal_side_effect_counts(conn, fx["session"])
          == (2, 3, 3, 2))

    # --- coordinator continuation: the extra decision is a NEW step ---
    step2, effect2 = u(), u()
    rh2, ik2 = f"rh-{u()[:10]}", f"ik-{u()[:10]}"
    rp2 = prepare_step(conn, fx["session"], f"seal2-{u()[:8]}", DRIVER,
                       EPOCH, rf0["session_fence"], step2, fx["turn"],
                       effect2, request_hash=rh2, idempotency_key=ik2)
    check("next decision step created in the same turn",
          rp2["outcome"] == "accepted", rp2)
    check("step2 sealed as decision batch #1 of its own",
          one(conn, "SELECT kind, sealed_batch_no FROM batches"
                    " WHERE step_id=%s", (step2,)) == ("decision", 1))
    rd2 = dispatch_effect(conn, fx["session"], f"dsp-{u()[:8]}", effect2,
                          DRIVER, EPOCH, rp2["receipt"]["session_fence"],
                          rp2["receipt"]["job_fence"])
    check("closing decision dispatched", rd2["outcome"] == "accepted", rd2)
    rc2b = complete_effect(
        conn, fx["session"], f"cmp-{u()[:8]}", effect2, DRIVER, EPOCH,
        dispatch_session_fence=rf0["session_fence"],
        job_fence=rp2["receipt"]["job_fence"], step_id=step2,
        request_hash=rh2, idempotency_key=ik2, outcome="succeeded",
        message={"text": "final answer", "model": "fake-llm@1"}, tools=[],
        decision_only=True, final_tools=False, evidence=good_evidence())
    check("closing decision accepted", rc2b["outcome"] == "accepted", rc2b)
    check("closing step succeeded/closed, turn/end known, session ready",
          one(conn, "SELECT status, stage FROM steps WHERE step_id=%s",
              (step2,)) == ("succeeded", "closed")
          and one(conn, "SELECT count(*) FROM session_events"
                        " WHERE session_id=%s AND event_type='turn/end'",
                  (fx["session"],))[0] == 1
          and one(conn, "SELECT state FROM sessions WHERE session_id=%s",
                  (fx["session"],))[0] == "ready")

    # TURN_ALREADY_CLOSED: the closed turn refuses a new step (the guard
    # sits behind the claimed-state CAS, so claim first)
    rf1 = claim_session(conn, fx["session"], DRIVER)
    rtac = prepare_step(conn, fx["session"], f"seal3-{u()[:8]}", DRIVER,
                        EPOCH, rf1["session_fence"], u(), fx["turn"], u())
    check("step in a closed turn -> TURN_ALREADY_CLOSED",
          rtac["outcome"] == "rejected_mismatch"
          and rtac["code"] == "TURN_ALREADY_CLOSED", rtac)

    rfin = finish_session(conn, fx["session"], f"fin-{u()[:8]}", DRIVER,
                          EPOCH, rf1["session_fence"])
    check("finish_session -> completed (the only completed path)",
          rfin["outcome"] == "accepted"
          and one(conn, "SELECT state FROM sessions WHERE session_id=%s",
                  (fx["session"],))[0] == "completed", rfin)
    rf2 = claim_session(conn, fx["session"], DRIVER)
    check("claim on completed session rejected",
          rf2["outcome"] == "rejected_mismatch"
          and rf2.get("code") in ("SESSION_TERMINAL", "SESSION_NOT_READY"),
          rf2)
    assert_invariants(conn, fx["session"], "two-step-flow")

    # =====================================================================
    # 5. seal CAS negatives: every rejection is the whole seal with zero
    #    side effects (no batch/effect/attempt/tool_call rows appear)
    # =====================================================================
    def cas_negative(label: str, *, claim=True, fence_delta=0,
                     epoch=EPOCH, expected=None, slots_override=None,
                     plan_hash=None, decision=None, prep=None):
        fxn = decision_fixture(conn, f"cas-{label}")
        f = claim_fence(conn, fxn) if claim else fxn["fence_after"]
        if prep:
            prep(conn, fxn)
        before_counts = seal_side_effect_counts(conn, fxn["session"])
        rj = seal_batch(
            conn, fxn["session"], f"tseal-{u()[:8]}", DRIVER, epoch,
            f + fence_delta, fxn["step"],
            expected if expected is not None else 1,
            decision or fxn["decision"],
            plan_hash or fxn["step_row"][4],
            slots_override if slots_override is not None
            else build_tool_slots(fxn["plan"]))
        check(f"CAS negative [{label}]: {rj['outcome']}/{rj['code']}",
              rj["outcome"] in ("rejected_mismatch", "rejected_stale"), rj)
        check(f"CAS negative [{label}]: zero side effects",
              seal_side_effect_counts(conn, fxn["session"]) == before_counts)
        return rj

    rj = cas_negative("not-claimed", claim=False)
    check("not-claimed code", rj["code"] == "SESSION_NOT_CLAIMED", rj)
    rj = cas_negative("stale-fence", fence_delta=-1)
    check("stale fence code", rj["code"] == "SESSION_FENCE_STALE", rj)
    rj = cas_negative("stale-epoch", epoch=EPOCH + 1)
    check("stale epoch code", rj["code"] == "DRIVER_EPOCH_STALE", rj)
    rj = cas_negative("wrong-expected-batch-no", expected=0)
    check("wrong expected sealed_batch_no code",
          rj["code"] == "SEALED_BATCH_NO_STALE", rj)
    rj = cas_negative(
        "sticky-cancel",
        prep=lambda c, x: exec_sql(
            c, "UPDATE sessions SET cancellation_epoch = 1"
               " WHERE session_id=%s", (x["session"],)))
    check("sticky cancel code", rj["code"] == "CANCEL_STICKY", rj)
    rj = cas_negative(
        "quiescing",
        prep=lambda c, x: exec_sql(
            c, "UPDATE sessions SET driver_mode='quiescing'"
               " WHERE session_id=%s", (x["session"],)))
    check("quiescing code", rj["code"] == "DRIVER_QUIESCING", rj)
    rj = cas_negative("empty-plan", slots_override=[])
    check("empty plan code", rj["code"] == "EMPTY_TOOLS_PLAN", rj)
    rj = cas_negative(
        "bad-retry-class",
        slots_override=[dict(s, retry_class="nope")
                        for s in build_tool_slots(two_slot_plan("cas-x"))])
    check("bad retry_class code", rj["code"] == "SLOT_SPEC_INVALID", rj)
    rj = cas_negative(
        "duplicate-tool-call-id",
        slots_override=build_tool_slots([
            {"tool_call_id": "dup", "tool": "fake_tool",
             "arguments": {"echo": "x"}},
            {"tool_call_id": "dup", "tool": "fake_tool",
             "arguments": {"echo": "x"}}]))
    check("duplicate tool_call_id code", rj["code"] == "SLOT_SPEC_INVALID",
          rj)
    rj = cas_negative(
        "payload-mismatch",
        slots_override=[dict(s, payload_canonical=
                          '{"arguments":{"echo":"cas-y"},"tool":"t",'
                          '"tool_call_id":"other"}')
                        if i == 0 else s
                        for i, s in enumerate(
                            build_tool_slots(two_slot_plan("cas-y")))])
    check("payload_canonical mismatch code",
          rj["code"] == "SLOT_SPEC_INVALID", rj)
    # pre-seal identity/plan/mark negatives (fresh fixture, valid CAS legs)
    fxn = decision_fixture(conn, "cas-identity")
    f = claim_fence(conn, fxn)
    bd = dict(fxn["decision"])
    bd["result_hash"] = "1" * 64
    rj = seal_batch(conn, fxn["session"], f"tseal-{u()[:8]}", DRIVER, EPOCH,
                    f, fxn["step"], 1, bd, fxn["step_row"][4],
                    build_tool_slots(fxn["plan"]))
    check("wrong decision identity (pre-seal) -> DECISION_IDENTITY_MISMATCH",
          rj["outcome"] == "rejected_mismatch"
          and rj["code"] == "DECISION_IDENTITY_MISMATCH", rj)
    check("identity rejection: zero side effects",
          seal_side_effect_counts(conn, fxn["session"]) == (1, 1, 1, 0))
    rj = seal_batch(conn, fxn["session"], f"tseal-{u()[:8]}", DRIVER, EPOCH,
                    f, fxn["step"], 1, fxn["decision"], "beef",
                    build_tool_slots(fxn["plan"]))
    check("wrong plan_hash (pre-seal) -> PLAN_HASH_MISMATCH",
          rj["outcome"] == "rejected_mismatch"
          and rj["code"] == "PLAN_HASH_MISMATCH", rj)
    exec_sql(conn, "UPDATE steps SET final_tools=false WHERE step_id=%s",
             (fxn["step"],))
    rj = seal_batch(conn, fxn["session"], f"tseal-{u()[:8]}", DRIVER, EPOCH,
                    f, fxn["step"], 1, fxn["decision"], fxn["step_row"][4],
                    build_tool_slots(fxn["plan"]))
    check("persisted final_tools=false -> DECISION_MARK_INVALID",
          rj["outcome"] == "rejected_mismatch"
          and rj["code"] == "DECISION_MARK_INVALID", rj)

    # =====================================================================
    # 6. reverse-order completion (Conformance 7): same batch completed in
    #    opposite orders -> identical aggregation and observable trace
    # =====================================================================
    def completed_tools_session(order: str):
        fxr = decision_fixture(conn, "reverse-seed")
        fr = claim_fence(conn, fxr)
        rslots = build_tool_slots(fxr["plan"])
        sr = seal_batch(conn, fxr["session"], f"tseal-{u()[:8]}", DRIVER,
                        EPOCH, fr, fxr["step"], 1, fxr["decision"],
                        fxr["step_row"][4], rslots)
        check(f"[{order}] seal accepted", sr["outcome"] == "accepted", sr)
        effs = [str(e["effect_id"]) for e in sr["receipt"]["effects"]]
        jfs = {str(e["effect_id"]): e["job_fence"]
               for e in sr["receipt"]["effects"]}
        slot_by_eff = {str(e["effect_id"]): sl for e, sl in
                       zip(sr["receipt"]["effects"], rslots)}
        seq_order = (list(range(len(effs))) if order == "forward"
                     else list(reversed(range(len(effs)))))
        for i in seq_order:
            eid = effs[i]
            rdi = dispatch_effect(conn, fxr["session"], f"dsp-{u()[:8]}",
                                  eid, DRIVER, EPOCH, fr + 1, jfs[eid])
            check(f"[{order}] dispatch tool {i} accepted",
                  rdi["outcome"] == "accepted", rdi)
            rci = complete_tool_effect(
                conn, fxr["session"], f"cmp-{u()[:8]}", eid, DRIVER, EPOCH,
                dispatch_session_fence=fr, job_fence=jfs[eid],
                step_id=fxr["step"],
                request_hash=slot_by_eff[eid]["request_hash"],
                idempotency_key=slot_by_eff[eid]["idempotency_key"],
                outcome="succeeded",
                tool_call_id=slot_by_eff[eid]["tool_call_id"],
                output={"echo": "reverse-seed", "kind": "fake-tool@1"},
                evidence=good_evidence())
            check(f"[{order}] complete tool {i} accepted",
                  rci["outcome"] == "accepted", rci)
        return fxr, effs

    fxa, effs_a = completed_tools_session("forward")
    fxb, effs_b = completed_tools_session("reverse")
    check("reverse: aggregation identical (succeeded/closed + ready)",
          one(conn, "SELECT status, stage, outcome_code FROM steps"
                    " WHERE step_id=%s", (fxb["step"],))
          == one(conn, "SELECT status, stage, outcome_code FROM steps"
                       " WHERE step_id=%s", (fxa["step"],))
          == ("succeeded", "closed", "SUCCEEDED"))
    check("reverse: session state identical (ready)",
          one(conn, "SELECT state FROM sessions WHERE session_id=%s",
              (fxb["session"],))[0]
          == one(conn, "SELECT state FROM sessions WHERE session_id=%s",
                 (fxa["session"],))[0] == "ready")

    tr_seq = dict((str(e), s) for e, s in rows(
        conn, "SELECT effect_id, seq FROM session_events"
              " WHERE session_id=%s AND event_type='tool/result'"
              " ORDER BY seq", (fxb["session"],)))
    check("reverse: tool/result seqs really landed in reverse order",
          tr_seq[effs_b[1]] < tr_seq[effs_b[0]], tr_seq)

    def ordinal_view(fx):
        return rows(conn,
                    "SELECT er.dispatch_ordinal, se.event_type, se.payload"
                    " FROM session_events se JOIN effect_requests er"
                    " ON er.effect_id = se.effect_id"
                    " WHERE se.session_id=%s"
                    " AND se.event_type IN ('tool/call','tool/result')"
                    " ORDER BY er.dispatch_ordinal, se.event_type",
                    (fx["session"],))

    check("reverse: semantic order by dispatch_ordinal unchanged",
          ordinal_view(fxa) == ordinal_view(fxb))
    check("reverse: normalize() observable traces identical (Conf 7)",
          observable_trace(conn, fxa["session"])
          == observable_trace(conn, fxb["session"]))
    assert_invariants(conn, fxa["session"], "reverse-forward")
    assert_invariants(conn, fxb["session"], "reverse-reverse")

    # =====================================================================
    # 7. full runtime loop with tools (coordinator continuation end-to-end)
    # =====================================================================
    conn.close()
    text = "please use_tool for me"
    s = create_loop_session(uri())
    r = run_user_message(uri(), s, text)
    check("runtime tools loop -> completed", r["state"] == "completed", r)
    rc = psycopg2.connect(uri())
    trace_types = [t[0] for t in semantic_projection(rc, s)]
    check("runtime trace: plan decision, two calls+results, final, end",
          trace_types == ["turn/start", "user/message", "assistant/message",
                          "tool/call", "tool/call", "tool/result",
                          "tool/result", "assistant/message", "turn/end"],
          trace_types)
    steps_rows = rows(rc, "SELECT status, stage, decision_only, final_tools"
                          " FROM steps WHERE session_id=%s"
                          " ORDER BY created_at", (s,))
    check("two steps: tools step then decision_only closer",
          steps_rows == [("succeeded", "closed", False, True),
                         ("succeeded", "closed", True, False)], steps_rows)
    calls = [json.loads(p[0]) for p in rows(
        rc, "SELECT payload FROM session_events WHERE session_id=%s"
            " AND event_type='tool/call'", (s,))]
    check("runtime slots: same tool+arguments, distinct tool_call_id",
          len({c["tool_call_id"] for c in calls}) == 2
          and len({json.dumps({k: v for k, v in c.items()
                               if k != "tool_call_id"}, sort_keys=True)
                   for c in calls}) == 1, calls)
    baseline_projection = semantic_projection(rc, s)
    assert_invariants(rc, s, "runtime-loop")
    rc.close()

    # =====================================================================
    # 8. chaos: kill at tools-phase boundaries + worker kill points inside
    #    the tools phase; every rerun converges with an identical trace
    # =====================================================================
    check("tools kill points registered",
          TOOLS_KILL_POINTS == ["after_tools_seal_commit",
                                "mid_tx_before_tools_seal_commit"])
    chaos_points = [
        "after_claim", "after_seal_commit", "after_tools_seal_commit",
        "after_worker_read", "after_fake_llm", "after_complete_commit",
        "mid_tx_before_seal_commit", "mid_tx_before_complete_commit",
        "mid_tx_before_tools_seal_commit",
    ]
    for point in chaos_points:
        sc = create_loop_session(uri())
        try:
            run_user_message(uri(), sc, text, kill_after=point)
            check(f"[{point}] run dies at the kill point", False, "no death")
        except ProcessDeath as pd:
            check(f"[{point}] ProcessDeath at the kill point",
                  pd.point == point, pd.point)
        cc = psycopg2.connect(uri())
        try:
            assert_invariants(cc, sc, f"{point}/after-kill")
            rr = run_user_message(uri(), sc, text)
            check(f"[{point}] rerun converges to completed",
                  rr["state"] == "completed", rr)
            assert_invariants(cc, sc, f"{point}/after-rerun")
            check(f"[{point}] semantic trace == normal tools loop",
                  semantic_projection(cc, sc) == baseline_projection)
        finally:
            cc.close()

    # partial tool completion: one tool of the batch has settled, the
    # process dies inside the SECOND tool's completion transaction; the
    # rerun must only complete the remaining effect (the succeeded one is
    # never re-dispatched or re-opened).
    sp = create_loop_session(uri())
    r1 = run_user_message(uri(), sp, text, max_iterations=1)
    # iteration 1: decision1 sealed + completed -> step ready/stage=decision
    r2 = run_user_message(uri(), sp, text, max_iterations=1)
    # iteration 2: tools sealed + FIRST tool completed -> one settled
    pc = psycopg2.connect(uri())
    tools_batch = one(pc, "SELECT batch_id FROM batches"
                          " WHERE session_id=%s AND kind='tools'", (sp,))
    check("partial fixture: tools batch sealed", tools_batch is not None)
    tool_states = rows(pc, "SELECT effect_id, status FROM effect_requests"
                           " WHERE session_id=%s AND effect_kind='tool'"
                           " ORDER BY dispatch_ordinal", (sp,))
    check("partial fixture: exactly one tool settled, one pending",
          [t[1] for t in tool_states] == ["succeeded", "ready"], tool_states)
    pc.close()
    second_tool = str(tool_states[1][0])
    try:
        worker_execute(uri(), sp, second_tool,
                       kill_after="mid_tx_before_complete_commit")
        check("partial-completion kill died", False, "no death")
    except ProcessDeath as pd:
        check("partial-completion kill dies inside the complete tx",
              pd.point == "mid_tx_before_complete_commit", pd.point)
    pc = psycopg2.connect(uri())
    try:
        check("at death: first tool still succeeded, second dispatch_started",
              [t[0] for t in rows(
                  pc, "SELECT status FROM effect_requests"
                      " WHERE session_id=%s AND effect_kind='tool'"
                      " ORDER BY dispatch_ordinal", (sp,))]
              == ["succeeded", "dispatch_started"])
        rr = run_user_message(uri(), sp, text)
        check("partial-completion rerun converges", rr["state"] == "completed",
              rr)
        dispatch_counts = rows(pc, "SELECT dispatch_count FROM effect_requests"
                                   " WHERE session_id=%s"
                                   " AND effect_kind='tool'"
                                   " ORDER BY dispatch_ordinal", (sp,))
        check("each tool dispatched exactly once (settled one not reopened)",
              [d[0] for d in dispatch_counts] == [1, 1], dispatch_counts)
        check("partial-completion trace == baseline",
              semantic_projection(pc, sp) == baseline_projection)
        assert_invariants(pc, sp, "partial-completion")
    finally:
        pc.close()

    # =====================================================================
    # 9. initial decision seal network retry (Conformance 1): one batch,
    #    one LLM slot, receipt replay only (fresh session, no fixture step)
    # =====================================================================
    conn2 = psycopg2.connect(uri())
    s9 = u()
    turn9 = u()
    create_session(conn2, s9, DRIVER)
    r91 = claim_session(conn2, s9, DRIVER)
    cmd9 = f"seal-retry-{u()[:8]}"
    step9, effect9 = u(), u()
    p1 = prepare_step(conn2, s9, cmd9, DRIVER, EPOCH, r91["session_fence"],
                      step9, turn9, effect9)
    check("retry fixture decision seal accepted", p1["outcome"] == "accepted",
          p1)
    p2 = prepare_step(conn2, s9, cmd9, DRIVER, EPOCH, r91["session_fence"],
                      step9, turn9, effect9)
    check("initial decision seal retry returns the original receipt",
          p2["outcome"] == "accepted"
          and json.dumps(p2["receipt"], sort_keys=True)
          == json.dumps(p1["receipt"], sort_keys=True))
    check("retry: exactly one decision batch and one LLM slot",
          one(conn2, "SELECT count(*), count(*) FILTER (WHERE kind='decision')"
                     " FROM batches WHERE step_id=%s", (step9,)) == (1, 1)
          and one(conn2, "SELECT count(*) FROM effect_requests"
                         " WHERE step_id=%s", (step9,))[0] == 1)
    conn2.close()

    print("[G6] all gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
