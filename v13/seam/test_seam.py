"""Phase A stage 21 gate: D11 cap exemption + D12 worktree/released.

Run: uv run python v13/seam/test_seam.py  (exit 0 = pass)
"""
from __future__ import annotations

import json
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v13.load import load_stage, run_psql
from v13.seam.setup_db import DB, main as setup_db

G10_BRANCH = "b"
FINISH = {"result_kind": "finish", "delivery_kind": "LOUD-BUT-BLIND"}


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    extra = f": {detail}" if detail and (not condition or len(str(detail)) < 220) else ""
    print(f"[{mark}] {label}{extra}")
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def u() -> str:
    return str(uuid.uuid4())


def fails_with(cur, sql, params, needle, label):
    cur.execute("SAVEPOINT sp")
    try:
        cur.execute(sql, params)
    except psycopg2.Error as exc:
        msg = str(exc)
        check(label, needle.lower() in msg.lower(), msg.splitlines()[0])
        cur.execute("ROLLBACK TO SAVEPOINT sp")
        return msg
    cur.execute("ROLLBACK TO SAVEPOINT sp")
    raise AssertionError(f"{label}: expected failure")


def connect(server, db=DB):
    conn = psycopg2.connect(server.get_uri(db))
    conn.autocommit = False
    return conn


def connect_as(server, user, db=DB):
    uri = server.get_uri(db)
    host = (parse_qs(urlparse(uri).query).get("host") or [None])[0]
    return psycopg2.connect(host=host, dbname=db, user=user)


def open_session(cur, spec=None):
    cur.execute("SELECT v13_open_session(%s::jsonb)", (json.dumps(spec or {}),))
    return str(cur.fetchone()[0])


def prefix(cur, sid, text="hello"):
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (sid, u(), json.dumps({"text": text})))


def trev(cur, sid):
    cur.execute("SELECT (v13_probe(%s)->>'tools_revision')::bigint", (sid,))
    return int(cur.fetchone()[0])


def harness_request(ltid, index, revision, handler="worker:harness_turn"):
    return {
        "tool": "harness_turn",
        "params": {},
        "handler": handler,
        "tools_revision": revision,
        "logical_turn_id": ltid,
        "continuation_index": index,
    }


def enqueue(cur, sid, kind, request, tool_name=None):
    if tool_name:
        cur.execute(
            "SELECT v13_enqueue_effect(%s, %s, %s::jsonb, %s)",
            (sid, kind, json.dumps(request), tool_name))
    else:
        cur.execute(
            "SELECT v13_enqueue_effect(%s, %s, %s::jsonb)",
            (sid, kind, json.dumps(request)))
    return str(cur.fetchone()[0])


def settle(cur, eid, result=None, status="succeeded"):
    cur.execute(
        "UPDATE effects SET status='claimed', attempt_no=attempt_no+1, fence=fence+1, "
        "lease_owner='w', lease_until=clock_timestamp()+interval '1 hour' "
        "WHERE effect_id=%s RETURNING attempt_no, fence", (eid,))
    attempt, fence = cur.fetchone()
    cur.execute(
        "SELECT v13_complete(%s, %s, %s, %s, %s::jsonb)",
        (eid, attempt, fence, status, None if result is None else json.dumps(result)))
    return cur.fetchone()[0], attempt, fence


def event_count(cur, sid, etype=None):
    if etype is None:
        cur.execute("SELECT count(*) FROM events WHERE session_id=%s", (sid,))
    else:
        cur.execute(
            "SELECT count(*) FROM events WHERE session_id=%s AND type=%s", (sid, etype))
    return int(cur.fetchone()[0])


def exempt(cur, sid, eid):
    cur.execute("SELECT v13_tail_gap_cap_exempt(%s, %s)", (sid, eid))
    return cur.fetchone()[0]


def anchor_rows(cur, sid, eid):
    cur.execute(
        "SELECT cap_class, anchor_seq FROM v13_cap_answer_anchor(%s, %s) ORDER BY cap_class",
        (sid, eid))
    return cur.fetchall()


def cap_answered(cur, sid, eid):
    cur.execute("SELECT v13_cap_human_answered(%s, %s)", (sid, eid))
    return cur.fetchone()[0]


def wt_request(tool, bid, revision):
    return {
        "tool": tool,
        "params": {"binding_artifact_id": bid},
        "handler": "worker:" + tool,
        "tools_revision": revision,
    }


def prepare_latch(cur, sid, bid):
    rev = trev(cur, sid)
    eid = enqueue(cur, sid, "tool", wt_request("worktree_prepare", bid, rev), "worktree_prepare")
    settle(cur, eid, {"schema_version": 1, "root_path": "/tmp/wt", "base_ref": "main"})
    cur.execute("SELECT v13_bind_worktree_from_prepare(%s)", (sid,))
    return eid


def session_with_user(cur):
    sid = open_session(cur)
    prefix(cur, sid)
    return sid


def gap(cur, sid, signals, ltid=None, index=0, result_kind="progress", extra=None):
    ltid = ltid or u()
    req = harness_request(ltid, index, trev(cur, sid))
    eid = enqueue(cur, sid, "tool", req, "harness_turn")
    body = {"result_kind": result_kind}
    if signals is not None:
        body["signals"] = signals
    if extra:
        body.update(extra)
    if result_kind == "wait":
        body = extra
    settle(cur, eid, body)
    return eid, ltid


def legacy_human(cur, sid, reason):
    eid = enqueue(cur, sid, "human", {"reason": reason})
    settle(cur, eid, {"response": "ok"})
    return eid


def arm_a_human(cur, sid, kind, ref):
    eid = enqueue(cur, sid, "human", {"interaction_kind": kind, "interaction_ref": ref})
    settle(cur, eid, {"schema_version": 1, "interaction_ref": ref, "response": "ok"})
    return eid


def stamp(cur, sid, status="succeeded", result=None):
    eid, ltid = gap(cur, sid, None, result_kind="finish") if False else (None, None)
    ltid = u()
    req = harness_request(ltid, 0, trev(cur, sid))
    eid = enqueue(cur, sid, "tool", req, "harness_turn")
    if status == "succeeded":
        settle(cur, eid, result or FINISH, "succeeded")
    else:
        settle(cur, eid, result, status)
    return eid, ltid


def answers_for(cur, sid):
    cur.execute("SELECT signal, kind, criteria FROM v13_needed_judgments(%s)", (sid,))
    answers = {}
    for signal, kind, criteria in cur.fetchall():
        if signal == "intent":
            answers[signal] = {"type": "choice", "choice": "tool_action",
                               "probabilities": {"tool_action": 0.9}, "confidence": 0.9}
        elif signal == "tool":
            answers[signal] = {"type": "choice", "choice": "harness_turn",
                               "probabilities": {"harness_turn": 0.9}, "confidence": 0.9}
        elif signal == "gate_action":
            answers[signal] = {"type": "noul", "noul": 0.9}
        elif signal == "gate_off_topic":
            answers[signal] = {"type": "noul", "noul": 0.1}
        elif signal == "risk":
            answers[signal] = {"type": "score", "score": 0.5, "confidence": 0.9}
        elif signal == "triage":
            answers[signal] = {"type": "choice", "choice": "direct",
                               "probabilities": {"direct": 0.9}, "confidence": 0.9}
        elif kind == "choice":
            keys = list(criteria.keys()) if isinstance(criteria, dict) else ["none"]
            ch = keys[0]
            answers[signal] = {"type": "choice", "choice": ch,
                               "probabilities": {ch: 0.9}, "confidence": 0.9}
        elif kind == "score":
            answers[signal] = {"type": "score", "score": 0.5, "confidence": 0.9}
        else:
            answers[signal] = {"type": "noul", "noul": 0.1}
    return answers


def begin_routed(server):
    conn = connect(server)
    cur = conn.cursor()
    cur.execute("SELECT set_config('typesafe.provider', 'mock', false)")
    cur.execute("SELECT set_config('typesafe.model', 'jev-mock', false)")
    sid, snap = open_routed(cur)
    return conn, cur, sid, snap


def open_routed(cur):
    cur.execute("UPDATE tools SET enabled=false WHERE name='spawn_subsession'")
    sid = open_session(cur)
    prefix(cur, sid)
    cur.execute(
        "SELECT v13_submit_override(%s, %s::jsonb)",
        (sid, json.dumps({
            "schema_version": 1, "intent": "direct", "reason": "gate",
            "source_principal": "user"})))
    cur.execute(
        "SELECT set_config('typesafe.mock_response', %s, true)",
        (json.dumps({
            "model": "jev-mock", "answers": answers_for(cur, sid),
            "usage": {"input_tokens": 1, "output_tokens": 1}}),))
    cur.execute("SELECT v13_parse(%s)", (sid,))
    return sid, cur.fetchone()[0]


def advance(cur, sid, snap):
    cur.execute(
        "UPDATE sessions SET context_active_revision = v13_context_required(session_id) "
        "WHERE session_id=%s", (sid,))
    cur.execute("SELECT v13_probe(%s)", (sid,))
    probe = cur.fetchone()[0]
    probe["sid"] = sid
    snap = json.loads(json.dumps(snap))
    snap["snap"].update(probe)
    snap["snap"]["sid"] = sid
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid, json.dumps(snap)))
    return cur.fetchone()[0], snap


def ready_harness(cur, sid):
    cur.execute(
        "SELECT effect_id, request FROM effects WHERE session_id=%s AND kind='tool' "
        "AND status='ready' AND tool_name='harness_turn'", (sid,))
    row = cur.fetchone()
    return (str(row[0]), row[1]) if row else None


def ledger(cur, sid):
    cur.execute(
        "SELECT effect_id::text, status, fence, attempt_no, request::text "
        "FROM effects WHERE session_id=%s ORDER BY effect_id", (sid,))
    effects = cur.fetchall()
    cur.execute("SELECT count(*), coalesce(max(seq), -1) FROM events WHERE session_id=%s", (sid,))
    ev = cur.fetchone()
    cur.execute("SELECT status FROM sessions WHERE session_id=%s", (sid,))
    return effects, ev, cur.fetchone()[0]


def source_asserts():
    sql = (ROOT / "v13_seam.sql").read_text()
    check("seam sql has no UPDATE latches", "UPDATE latches" not in sql and "UPDATE public.latches" not in sql)
    check("seam sql has no INSERT latches", "INSERT INTO latches" not in sql and "INSERT INTO public.latches" not in sql)
    bodies = []
    for chunk in sql.split("CREATE FUNCTION")[1:]:
        bodies.append(chunk.split("CREATE ")[0])
    check("production functions do not read latch state",
          all("->>'state'" not in b for b in bodies))
    check("install DO reads historical released state", "value->>'state' = 'released'" in sql)


def main() -> int:
    source_asserts()
    setup_db()
    server = get_server()
    conn = connect(server)
    cur = conn.cursor()

    cur.execute(
        "SELECT proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
        "WHERE n.nspname='public' AND p.prokind='f' "
        "AND pg_get_functiondef(p.oid) ~ 'material_cap' ORDER BY 1")
    check("material_cap lives only in anchor",
          [r[0] for r in cur.fetchall()] == ["v13_cap_answer_anchor"])
    cur.execute(
        "SELECT proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
        "WHERE n.nspname='public' AND p.prokind='f' "
        "AND pg_get_functiondef(p.oid) ~ 'repair_cap|replan_cap' ORDER BY 1")
    names = [r[0] for r in cur.fetchall()]
    check("cap predicate literals not copied; frozen fold_reason residual only",
          names == ["v13_cap_answer_anchor", "v13_triage_fold_reason"], names)
    cur.execute("SELECT pg_get_functiondef('v13_cap_human_answered(uuid,uuid)'::regprocedure)")
    cap_def = cur.fetchone()[0]
    check("cap_human_answered delegates and has no cap literal",
          "v13_cap_answer_anchor" in cap_def and "repair_cap" not in cap_def
          and "replan_cap" not in cap_def and "material_cap" not in cap_def)
    cur.execute("SELECT pg_get_functiondef('v13_tail_gap_cap_exempt(uuid,uuid)'::regprocedure)")
    ex_def = cur.fetchone()[0]
    check("exempt stamp uses source_effect_id and seq",
          "source_effect_id = n.effect_id" in ex_def and "ev.seq >" in ex_def)
    for bad in ("->>'effect_id'", "->>'logical_turn_id'", "harness_effect_id", "reason"):
        check(f"exempt body has no {bad}", bad not in ex_def)
    check("exempt has no row count", "count(" not in ex_def.lower())
    cur.execute("SELECT pg_get_functiondef('v13_harness_tail_gap(uuid,uuid)'::regprocedure)")
    gap_def = cur.fetchone()[0]
    check("tail_gap keeps original raise and adds exempt",
          "v13: harness tail gap" in gap_def and "v13_tail_gap_cap_exempt(p_sid, e.effect_id)" in gap_def)
    for fn in ("v13_closeout(uuid,text,text,boolean)", "v13_advance(uuid,jsonb)", "v13_state_hash(uuid)"):
        cur.execute("SELECT pg_get_functiondef(%s::regprocedure)", (fn,))
        body = cur.fetchone()[0]
        check(f"{fn} not replaced", "v13_record_worktree_released" not in body
              and "v13_tail_gap_cap_exempt" not in body)
    for fn in ("v13_complete(uuid,integer,bigint,text,jsonb)", "v13_resolve_unknown(uuid,text,jsonb)"):
        cur.execute("SELECT pg_get_functiondef(%s::regprocedure)", (fn,))
        body = cur.fetchone()[0]
        check(f"{fn} writer call outside EXCEPTION handler",
              "v13_record_worktree_released" in body and "EXCEPTION WHEN" not in body)
        if fn.startswith("v13_resolve_unknown"):
            lock_at = body.find("FROM sessions WHERE session_id = v_sid FOR UPDATE")
            call_at = body.find("v13_record_worktree_released")
            check("resolve holds session row lock before writer",
                  0 <= lock_at < call_at, (lock_at, call_at))

    def priv(fn, role):
        cur.execute("SELECT has_function_privilege(%s, %s, 'execute')", (role, fn))
        return cur.fetchone()[0]

    writer = "v13_record_worktree_released(uuid,uuid)"
    check("writer execute route", priv(writer, "v13_route") is True)
    check("writer execute worker false", priv(writer, "v13_worker") is False)
    check("writer execute resolve false", priv(writer, "v13_resolve") is False)
    check("writer execute public false", priv(writer, "public") is False)
    cur.execute("SELECT pg_get_functiondef('v13_seam_event_guard()'::regprocedure)")
    guard_def = cur.fetchone()[0]
    for banned in ("FOR UPDATE", "FOR SHARE", "FOR NO KEY UPDATE", "FOR KEY SHARE",
                   "LOCK TABLE", "pg_advisory_", "NOWAIT", "SKIP LOCKED"):
        check(f"guard has no {banned}", banned not in guard_def)
    cur.execute("SELECT pg_get_functiondef('v13_record_worktree_released(uuid,uuid)'::regprocedure)")
    writer_def = cur.fetchone()[0]
    check("writer locks latches FOR UPDATE",
          "FROM latches" in writer_def and "FOR UPDATE" in writer_def)
    check("writer has no advisory lock or ON CONFLICT",
          "pg_advisory_" not in writer_def and "ON CONFLICT" not in writer_def)
    lock_stmt = writer_def.split("FOR UPDATE")[0].rsplit(";", 1)[-1] + "FOR UPDATE"
    check("event recheck is not in the FOR UPDATE statement",
          "events" not in lock_stmt and "FROM events" not in lock_stmt)
    for fn in ("v13_cap_answer_anchor(uuid,uuid)", "v13_tail_gap_cap_exempt(uuid,uuid)",
               "v13_worktree_state(uuid)"):
        check(f"{fn} route", priv(fn, "v13_route") is True)
        check(f"{fn} public false", priv(fn, "public") is False)
        check(f"{fn} worker false", priv(fn, "v13_worker") is False)
    conn.commit()

    sid = session_with_user(cur)
    eid, ltid = gap(cur, sid, ["repair/required"])
    fails_with(cur, "SELECT v13_harness_tail_gap(%s, %s)", (sid, u()),
               "v13: harness tail gap", "unanswered gap still raises")
    check("unanswered exempt false", exempt(cur, sid, eid) is False)
    conn.rollback()

    sid = session_with_user(cur)
    early, _ = gap(cur, sid, ["repair/required"], ltid=u())
    late, _ = gap(cur, sid, ["repair/required"], ltid=u())
    legacy_human(cur, sid, "repair_cap")
    stamp(cur, sid)
    fails_with(cur, "SELECT v13_harness_tail_gap(%s, %s)", (sid, u()),
               "v13: harness tail gap", "earlier independent gap still raises")
    conn.rollback()

    sid = session_with_user(cur)
    eid, ltid = gap(cur, sid, ["repair/required"])
    legacy_human(cur, sid, "repair_cap")
    stamp(cur, sid)
    wait_id, _ = gap(cur, sid, None, result_kind="wait", extra={
        "result_kind": "wait", "wait_reason": "evidence",
        "wake": {"kind": "event", "event_type": "demo/ping"}})
    check("wait never exempt", exempt(cur, sid, wait_id) is False)
    fails_with(cur, "SELECT v13_harness_tail_gap(%s, %s)", (sid, eid),
               "v13: harness tail gap", "unpaid wait still raises")
    conn.rollback()

    sid = session_with_user(cur)
    eid, _ = gap(cur, sid, ["repair/required"])
    legacy_human(cur, sid, "replan_cap")
    stamp(cur, sid)
    check("replan does not exempt repair chain", exempt(cur, sid, eid) is False)
    fails_with(cur, "SELECT v13_harness_tail_gap(%s, %s)", (sid, u()),
               "v13: harness tail gap", "replan_cap does not clear repair gap")
    conn.rollback()

    sid = session_with_user(cur)
    eid, _ = gap(cur, sid, ["repair/required"])
    arm_a_human(cur, sid, "material_cap", "ix-mat")
    stamp(cur, sid)
    check("material does not exempt", exempt(cur, sid, eid) is False)
    classes = [r[0] for r in anchor_rows(cur, sid, eid)]
    check("material anchor present", classes == ["material"], classes)
    conn.rollback()

    sid = session_with_user(cur)
    eid, _ = gap(cur, sid, ["repair/required"])
    arm_a_human(cur, sid, "material_cap", "ix-early")
    legacy_human(cur, sid, "repair_cap")
    stamp(cur, sid)
    classes = [r[0] for r in anchor_rows(cur, sid, eid)]
    check("class-earliest keeps repair not global first", "repair" in classes and "material" in classes, classes)
    check("class-earliest exempts repair signal", exempt(cur, sid, eid) is True)
    cur.execute("SELECT v13_harness_tail_gap(%s, %s)", (sid, u()))
    check("class-earliest tail_gap does not raise", True)
    conn.rollback()

    sid = session_with_user(cur)
    eid, _ = gap(cur, sid, ["repair/required"])
    arm_a_human(cur, sid, "repair_cap", "ix-a")
    check("arm (a) anchor", [r[0] for r in anchor_rows(cur, sid, eid)] == ["repair"])
    conn.rollback()

    sid = session_with_user(cur)
    eid, _ = gap(cur, sid, ["repair/required"])
    legacy_human(cur, sid, "repair_cap")
    check("arm (b) anchor", [r[0] for r in anchor_rows(cur, sid, eid)] == ["repair"])
    check("arm (b) cap answered", cap_answered(cur, sid, eid) is True)
    conn.rollback()

    sid = session_with_user(cur)
    eid, _ = gap(cur, sid, ["repair/required", "replan/required"])
    legacy_human(cur, sid, "repair_cap")
    stamp(cur, sid)
    check("dual signal one cap exempts", exempt(cur, sid, eid) is True)
    cur.execute("SELECT v13_harness_tail_gap(%s, %s)", (sid, u()))
    check("dual signal one cap does not raise", True)
    conn.rollback()

    sid = session_with_user(cur)
    heid = legacy_human(cur, sid, "repair_cap")
    eid, ltid = gap(cur, sid, ["repair/required"])
    check("out-of-order legacy not answered", cap_answered(cur, sid, eid) is False)
    check("out-of-order not exempt", exempt(cur, sid, eid) is False)
    conn.rollback()

    sid = session_with_user(cur)
    eid, ltid = gap(cur, sid, ["repair/required"])
    heid = legacy_human(cur, sid, "repair_cap")
    cur.execute("UPDATE effects SET origin_user_seq = origin_user_seq + 1 WHERE effect_id=%s", (heid,))
    check("cross-turn legacy not answered", cap_answered(cur, sid, eid) is False)
    check("cross-turn not exempt", exempt(cur, sid, eid) is False)
    conn.rollback()

    sid = session_with_user(cur)
    eid, ltid = gap(cur, sid, ["repair/required"])
    nxt = enqueue(cur, sid, "tool", harness_request(ltid, 1, trev(cur, sid)), "harness_turn")
    settle(cur, nxt, {"result_kind": "progress"})
    cur.execute("SELECT v13_harness_tail_gap(%s, %s)", (sid, u()))
    check("same logical turn index+1 uses successor rule", True)
    check("successor path does not need exemption", exempt(cur, sid, eid) is False)
    conn.rollback()

    sid = session_with_user(cur)
    a, _ = gap(cur, sid, ["repair/required"])
    b, _ = gap(cur, sid, ["replan/required"])
    legacy_human(cur, sid, "replan_cap")
    stamp(cur, sid)
    check("only the matched gap is exempt", exempt(cur, sid, b) is True and exempt(cur, sid, a) is False)
    fails_with(cur, "SELECT v13_harness_tail_gap(%s, %s)", (sid, b),
               "v13: harness tail gap", "unmatched independent gap still raises")
    conn.rollback()

    other = session_with_user(cur)
    oe, _ = gap(cur, other, ["repair/required"])
    sid = session_with_user(cur)
    eid, _ = gap(cur, sid, ["repair/required"])
    legacy_human(cur, sid, "repair_cap")
    stamp(cur, sid)
    check("cross-session decoy does not answer A", cap_answered(cur, other, oe) is False)
    fails_with(cur, "SELECT v13_harness_tail_gap(%s, %s)", (other, u()),
               "v13: harness tail gap", "cross-session decoy does not clear A")
    check("cross-session B exempt", exempt(cur, sid, eid) is True)
    conn.rollback()

    sid = session_with_user(cur)
    eid, _ = gap(cur, sid, ["repair/required"])
    cur.execute("SAVEPOINT tie")
    cur.execute("ALTER TABLE events DROP CONSTRAINT events_pkey CASCADE")
    cur.execute("ALTER TABLE events DISABLE TRIGGER trg_v13_control_event_guard")
    h1 = enqueue(cur, sid, "human", {"interaction_kind": "repair_cap", "interaction_ref": "t1"})
    cur.execute("UPDATE effects SET status='succeeded' WHERE effect_id=%s", (h1,))
    h2 = enqueue(cur, sid, "human", {"interaction_kind": "repair_cap", "interaction_ref": "t2"})
    cur.execute("UPDATE effects SET status='succeeded' WHERE effect_id=%s", (h2,))
    cur.execute(
        "SELECT max(seq) FROM events WHERE session_id=%s AND source_effect_id=%s AND type='effect_done'",
        (sid, eid))
    done = cur.fetchone()[0]
    tied = done + 50
    for hid in (h1, h2):
        cur.execute(
            "INSERT INTO events (session_id, seq, event_id, type, payload, payload_hash, source_effect_id) "
            "SELECT %s, %s, %s, 'human/responded', p.payload, "
            "encode(digest(p.payload::text, 'sha256'), 'hex'), %s "
            "FROM (SELECT '{}'::jsonb AS payload) p",
            (sid, tied, u(), hid))
    check("tied earliest anchor drops the class", anchor_rows(cur, sid, eid) == [])
    check("tie is not exempt", exempt(cur, sid, eid) is False)
    fails_with(cur, "SELECT v13_harness_tail_gap(%s, %s)", (sid, u()),
               "v13: harness tail gap", "tied anchor still raises")
    cur.execute("ROLLBACK TO SAVEPOINT tie")
    conn.rollback()

    sid = session_with_user(cur)
    eid, _ = gap(cur, sid, ["repair/required"])
    legacy_human(cur, sid, "repair_cap")
    check("uncast predicate false", exempt(cur, sid, eid) is False)
    cur.execute("SELECT v13_harness_tail_gap(%s, %s)", (sid, eid))
    check("tail_gap keep=broken chain does not raise", True)
    fails_with(cur, "SELECT v13_harness_tail_gap(%s, %s)", (sid, u()),
               "v13: harness tail gap", "spectator still raises before cast")
    conn.rollback()

    sid = session_with_user(cur)
    eid, _ = gap(cur, sid, ["repair/required"])
    cur.execute(
        "INSERT INTO effects (effect_id, session_id, kind, tool_name, request, request_hash, "
        "origin_user_seq, status) "
        "SELECT %s, %s, 'tool', 'harness_turn', r.request, encode(digest(r.request::text, 'sha256'), 'hex'), "
        "e.origin_user_seq, 'succeeded' FROM effects e, "
        "(SELECT %s::jsonb AS request) r WHERE e.effect_id=%s",
        (u(), sid, json.dumps(harness_request(u(), 0, trev(cur, sid))), eid))
    legacy_human(cur, sid, "repair_cap")
    check("G4 pre-anchor eventless index-0 does not stamp", exempt(cur, sid, eid) is False)
    fails_with(cur, "SELECT v13_harness_tail_gap(%s, %s)", (sid, u()),
               "v13: harness tail gap", "G4 spectator raises")
    conn.rollback()

    sid = session_with_user(cur)
    eid, _ = gap(cur, sid, ["repair/required"])
    legacy_human(cur, sid, "repair_cap")
    quiet = enqueue(cur, sid, "tool", harness_request(u(), 0, trev(cur, sid)), "harness_turn")
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'turn/route', %s::jsonb)",
        (sid, u(), json.dumps({
            "action": "tool", "reason": "harness_continuation",
            "tool": "harness_turn", "params": {}})))
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'turn/route', %s::jsonb)",
        (sid, u(), json.dumps({
            "action": "tool", "reason": "side_effect_tool",
            "tool": "harness_turn", "params": {}})))
    check("G5 route events do not stamp", exempt(cur, sid, eid) is False)
    conn.rollback()

    sid = session_with_user(cur)
    eid, _ = gap(cur, sid, ["repair/required"])
    legacy_human(cur, sid, "repair_cap")
    cur.execute(
        "INSERT INTO effects (effect_id, session_id, kind, tool_name, request, request_hash, "
        "origin_user_seq, status) "
        "SELECT %s, %s, 'tool', 'harness_turn', r.request, encode(digest(r.request::text, 'sha256'), 'hex'), "
        "e.origin_user_seq, 'succeeded' FROM effects e, "
        "(SELECT %s::jsonb AS request) r WHERE e.effect_id=%s",
        (u(), sid, json.dumps(harness_request(u(), 0, 1)), eid))
    stamp(cur, sid)
    check("G6 old eventless row does not block a stamped row", exempt(cur, sid, eid) is True)
    conn.rollback()

    sid = session_with_user(cur)
    eid, _ = gap(cur, sid, ["repair/required"])
    legacy_human(cur, sid, "repair_cap")
    enqueue(cur, sid, "tool", harness_request(u(), 0, trev(cur, sid)), "harness_turn")
    cur.execute("UPDATE effects SET status='succeeded' WHERE session_id=%s AND status='ready'", (sid,))
    enqueue(cur, sid, "tool", harness_request(u(), 0, trev(cur, sid)), "harness_turn")
    check("G7 two eventless post-anchor rows do not stamp", exempt(cur, sid, eid) is False)
    fails_with(cur, "SELECT v13_harness_tail_gap(%s, %s)", (sid, u()),
               "v13: harness tail gap", "G7 still raises")
    conn.rollback()

    sid = session_with_user(cur)
    eid, _ = gap(cur, sid, ["repair/required"])
    early, _ = stamp(cur, sid)
    legacy_human(cur, sid, "repair_cap")
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'turn/route', %s::jsonb)",
        (sid, u(), json.dumps({"action": "tool", "reason": "side_effect_tool",
                               "tool": "harness_turn", "params": {}})))
    check("G8 own event at or before anchor does not stamp", exempt(cur, sid, eid) is False)
    conn.rollback()

    sid = session_with_user(cur)
    eid, _ = gap(cur, sid, ["repair/required"])
    legacy_human(cur, sid, "repair_cap")
    failed, _ = stamp(cur, sid, status="failed")
    check("G2/G3 failed outcome exempts", exempt(cur, sid, eid) is True)
    fin, _ = stamp(cur, sid, status="succeeded", result=FINISH)
    check("G2 finish effect_done exempts", exempt(cur, sid, eid) is True)
    conn.rollback()

    conn.commit()
    cur.close()
    conn.close()

    conn, cur, sid, snap = begin_routed(server)
    word, snap = advance(cur, sid, snap)
    row = ready_harness(cur, sid)
    check("W1 first harness waiting", word == "waiting" and row is not None, word)
    old_id, old_req = row
    old_ltid = old_req["logical_turn_id"]
    settle(cur, old_id, {"result_kind": "progress", "signals": ["repair/required"]})
    heid = enqueue(cur, sid, "human", {"reason": "repair_cap"})
    settle(cur, heid, {"response": "ok"})
    check("W1 cap answered", cap_answered(cur, sid, old_id) is True)
    check("G9 uncast predicate false", exempt(cur, sid, old_id) is False)
    cur.execute("SELECT v13_harness_tail_gap(%s, %s)", (sid, old_id))
    fails_with(cur, "SELECT v13_harness_tail_gap(%s, %s)", (sid, u()),
               "v13: harness tail gap", "G9 spectator raises")
    fails_with(cur, "SELECT v13_closeout(%s, 'completed', 'harness_finish', false)", (sid,),
               "v13: closeout continuation owed", "G9/G10 closeout owed")
    word, snap = advance(cur, sid, snap)
    cast = ready_harness(cur, sid)
    check("W1/G9 cast one index-0", word == "waiting" and cast is not None, word)
    new_id, new_req = cast
    check("W1 new uuid index 0",
          new_req["logical_turn_id"] != old_ltid and new_req["continuation_index"] == 0)
    cur.execute(
        "SELECT count(*) FROM effects WHERE session_id=%s AND kind='tool' AND tool_name='harness_turn' "
        "AND request->>'continuation_index' = '0' AND status='ready'", (sid,))
    check("G9 exactly one ready index-0", cur.fetchone()[0] == 1)
    before = ledger(cur, sid)
    word, snap = advance(cur, sid, snap)
    after = ledger(cur, sid)
    check("G10 branch b returns waiting", word == "waiting" and G10_BRANCH == "b", word)
    check("G10 zero writes", before == after, (word, before[2], after[2]))
    cur.execute("SELECT v13_claim('worker-1', 60000)")
    claimed = cur.fetchone()[0]
    check("G12 worker claim independent of advance",
          claimed is not None and claimed["effect_id"] == new_id, claimed)
    print("finish claim", settle(cur, new_id, FINISH))
    check("G11/W1 exempt after finish", exempt(cur, sid, old_id) is True)
    word, snap = advance(cur, sid, snap)
    check("W1/G11 advance after finish does not raise", word == "terminal", word)
    cur.execute("SELECT status FROM sessions WHERE session_id=%s", (sid,))
    check("W1 closeout completed", cur.fetchone()[0] == "completed")
    cur.execute("SELECT payload FROM events WHERE session_id=%s AND type='session/completed'", (sid,))
    seal = cur.fetchone()[0]
    cur.execute("SELECT v13_closeout(%s, 'completed', 'harness_finish', false)", (sid,))
    check("closeout replay succeeds", cur.fetchone()[0] == seal)
    cur.execute("SELECT count(*) FROM events WHERE session_id=%s AND type='session/completed'", (sid,))
    check("closeout replay does not write a second seal", cur.fetchone()[0] == 1)
    conn.rollback()
    conn.close()
    conn, cur, sid, snap = begin_routed(server)
    heid = enqueue(cur, sid, "human", {"reason": "repair_cap"})
    settle(cur, heid, {"response": "ok"})
    old_id = enqueue(cur, sid, "tool", harness_request(u(), 0, trev(cur, sid)), "harness_turn")
    settle(cur, old_id, {"result_kind": "progress", "signals": ["repair/required"]})
    cur.execute("SELECT request FROM effects WHERE effect_id=%s", (old_id,))
    old_req = cur.fetchone()[0]
    check("out-of-order advance does not skip", cap_answered(cur, sid, old_id) is False)
    word, snap = advance(cur, sid, snap)
    cont = ready_harness(cur, sid)
    check("out-of-order writes index+1",
          word == "waiting" and cont is not None
          and cont[1]["logical_turn_id"] == old_req["logical_turn_id"]
          and cont[1]["continuation_index"] == 1, cont)
    conn.rollback()
    conn.close()
    conn, cur, sid, snap = begin_routed(server)
    word, snap = advance(cur, sid, snap)
    old_id, old_req = ready_harness(cur, sid)
    settle(cur, old_id, {"result_kind": "progress", "signals": ["repair/required"]})
    heid = enqueue(cur, sid, "human", {"reason": "repair_cap"})
    settle(cur, heid, {"response": "ok"})
    cur.execute("UPDATE effects SET origin_user_seq = origin_user_seq + 9 WHERE effect_id=%s", (heid,))
    word, snap = advance(cur, sid, snap)
    cont = ready_harness(cur, sid)
    check("cross-turn legacy writes index+1",
          word == "waiting" and cont is not None
          and cont[1]["continuation_index"] == 1
          and cont[1]["logical_turn_id"] == old_req["logical_turn_id"], cont)
    conn.rollback()
    conn.close()
    conn, cur, sid, snap = begin_routed(server)
    word, snap = advance(cur, sid, snap)
    old_id, _ = ready_harness(cur, sid)
    settle(cur, old_id, {"result_kind": "progress", "signals": ["repair/required"]})
    legacy_human(cur, sid, "repair_cap")
    word, snap = advance(cur, sid, snap)
    new_id, new_req = ready_harness(cur, sid)
    settle(cur, new_id, None, "failed")
    check("G3 failed stamp exempts", exempt(cur, sid, old_id) is True)
    word, snap = advance(cur, sid, snap)
    cur.execute("SELECT status, request->>'logical_turn_id' FROM effects WHERE effect_id=%s", (new_id,))
    retried = cur.fetchone()
    check("G3 retry arm reopens failed row", word == "waiting" and retried[0] == "ready"
          and retried[1] == new_req["logical_turn_id"], (word, retried))
    conn.rollback()
    conn.close()
    conn, cur, sid, snap = begin_routed(server)
    word, snap = advance(cur, sid, snap)
    parent = sid
    cur.execute(
        "SELECT v13_spawn_subsession(%s, %s::jsonb)",
        (parent, json.dumps({"schema_version": 1, "children": [
            {"tool_call_id": "c1", "task": "child"}]})))
    spawned = cur.fetchone()[0]
    child = spawned["children"][0]["session_id"]
    hid, hreq = ready_harness(cur, parent)
    settle(cur, hid, {
        "result_kind": "wait", "wait_reason": "evidence",
        "wake": {"kind": "children_terminal", "child_session_ids": [child]}})
    n_before = event_count(cur, parent)
    cur.execute("SELECT count(*) FROM effects WHERE session_id=%s", (parent,))
    e_before = cur.fetchone()[0]
    word, snap = advance(cur, parent, snap)
    cur.execute("SELECT count(*) FROM effects WHERE session_id=%s", (parent,))
    check("children_terminal unsatisfied parks",
          word == "waiting" and cur.fetchone()[0] == e_before
          and event_count(cur, parent, "wake/satisfied") == 0, word)
    prefix(cur, child, "child hello")
    cur.execute("SELECT v13_closeout(%s, 'completed', 'answered', false)", (child,))
    cur.fetchone()
    cur.execute("SELECT v13_recover_idle()")
    rec = cur.fetchone()[0]
    check("recover nudges parent", parent in rec["pending"] and rec["nudged"] >= 1, rec)
    word, snap = advance(cur, parent, snap)
    cont = ready_harness(cur, parent)
    check("children_terminal satisfied continues index+1",
          word == "waiting" and cont is not None
          and cont[1]["logical_turn_id"] == hreq["logical_turn_id"]
          and cont[1]["continuation_index"] == 1
          and event_count(cur, parent, "wake/satisfied") == 1, (word, cont))
    conn.rollback()
    conn.close()
    conn, cur, sid, snap = begin_routed(server)
    word, snap = advance(cur, sid, snap)
    hid, _ = ready_harness(cur, sid)
    stranger = u()
    settle(cur, hid, {
        "result_kind": "wait", "wait_reason": "evidence",
        "wake": {"kind": "children_terminal", "child_session_ids": [stranger]}})
    cur.execute(
        "UPDATE sessions SET context_active_revision = v13_context_required(session_id) "
        "WHERE session_id=%s", (sid,))
    cur.execute("SELECT v13_probe(%s)", (sid,))
    probe = cur.fetchone()[0]
    probe["sid"] = sid
    snap = json.loads(json.dumps(snap))
    snap["snap"].update(probe)
    snap["snap"]["sid"] = sid
    fails_with(cur, "SELECT v13_advance(%s, %s::jsonb)", (sid, json.dumps(snap)),
               "children_terminal child", "non-direct child raises")
    fails_with(
        cur, "SELECT v13_wake_is_satisfied_v1(%s, %s, %s::jsonb)",
        (sid, u(), json.dumps({"kind": "children_terminal", "child_session_ids": [u()]})),
        "children_terminal child", "missing id raises")
    fails_with(
        cur, "SELECT v13_wake_is_satisfied_v1(%s, %s, %s::jsonb)",
        (sid, u(), json.dumps({"kind": "children_terminal", "child_session_ids": [stranger, stranger]})),
        "duplicate", "duplicate id raises")
    conn.rollback()
    conn.commit()
    cur.close()
    conn.close()

    conn = connect(server)
    cur = conn.cursor()
    sid = session_with_user(cur)
    bid = u()
    prepare_latch(cur, sid, bid)
    cur.execute("SELECT value->>'state' FROM latches WHERE session_id=%s AND name='worktree'", (sid,))
    check("prepare latch stays prepared", cur.fetchone()[0] == "prepared")
    cur.execute("SELECT v13_worktree_state(%s)", (sid,))
    check("prepare projection prepared", cur.fetchone()[0] == "prepared")
    rel = enqueue(cur, sid, "tool", wt_request("worktree_release", bid, trev(cur, sid)), "worktree_release")
    word, attempt, fence = settle(cur, rel, {"schema_version": 1})
    check("release complete accepted", word == "accepted")
    check("one released event", event_count(cur, sid, "worktree/released") == 1)
    cur.execute("SELECT v13_worktree_state(%s)", (sid,))
    check("projection released", cur.fetchone()[0] == "released")
    cur.execute("SELECT value->>'state' FROM latches WHERE session_id=%s AND name='worktree'", (sid,))
    check("latch row still prepared", cur.fetchone()[0] == "prepared")
    cur.execute("SELECT v13_complete(%s, %s, %s, 'succeeded', %s::jsonb)",
                (rel, attempt, fence, json.dumps({"schema_version": 1})))
    check("second complete is replay", cur.fetchone()[0] == "replay")
    check("replay keeps one event", event_count(cur, sid, "worktree/released") == 1)

    bad = enqueue(cur, sid, "tool", wt_request("worktree_release", bid, trev(cur, sid) + 1), "worktree_release")
    cur.execute("UPDATE effects SET status='succeeded' WHERE effect_id=%s", (bad,))
    fails_with(
        cur,
        "SELECT v13_append_event(%s, %s, 'worktree/released', %s::jsonb, %s)",
        (sid, u(), json.dumps({"schema_version": 1, "binding_artifact_id": bid}), bad),
        "v13: worktree released", "second source direct insert raises")
    check("bypass insert keeps one event", event_count(cur, sid, "worktree/released") == 1)
    cur.execute("UPDATE effects SET status='cancelled' WHERE effect_id=%s", (bad,))

    again = enqueue(cur, sid, "tool", wt_request("worktree_release", bid, trev(cur, sid) + 3), "worktree_release")
    word, _, _ = settle(cur, again, {"schema_version": 1})
    check("second independent release succeeds", word == "accepted")
    check("second independent release adds no event", event_count(cur, sid, "worktree/released") == 1)
    cur.execute("SELECT v13_worktree_state(%s)", (sid,))
    check("projection stays released", cur.fetchone()[0] == "released")

    sid_f = session_with_user(cur)
    bid_f = u()
    prepare_latch(cur, sid_f, bid_f)
    failed = enqueue(cur, sid_f, "tool", wt_request("worktree_release", bid_f, trev(cur, sid_f)), "worktree_release")
    settle(cur, failed, None, "failed")
    check("failed release zero events", event_count(cur, sid_f, "worktree/released") == 0)
    cur.execute("SELECT v13_worktree_state(%s)", (sid_f,))
    check("failed projection prepared", cur.fetchone()[0] == "prepared")
    unknown = enqueue(cur, sid_f, "tool", wt_request("worktree_release", bid_f, trev(cur, sid_f) + 1), "worktree_release")
    settle(cur, unknown, {"schema_version": 1, "note": "maybe"}, "unknown")
    check("unknown release zero events", event_count(cur, sid_f, "worktree/released") == 0)
    cur.execute(
        "SELECT encode(digest(result::text, 'sha256'), 'hex') FROM effects WHERE effect_id=%s",
        (unknown,))
    payload_hash = cur.fetchone()[0]
    cur.execute(
        "SELECT v13_resolve_unknown(%s, 'confirmed', %s::jsonb)",
        (unknown, json.dumps({"observation": "committed", "payload_hash": payload_hash})))
    check("confirmed resolve accepted", cur.fetchone()[0] == "accepted")
    cur.execute("SELECT v13_worktree_state(%s)", (sid_f,))
    check("confirmed release projects released", cur.fetchone()[0] == "released")

    sid_n = session_with_user(cur)
    bid_n = u()
    prepare_latch(cur, sid_n, bid_n)
    nope = enqueue(cur, sid_n, "tool", wt_request("worktree_release", bid_n, trev(cur, sid_n)), "worktree_release")
    settle(cur, nope, {"schema_version": 1}, "unknown")
    cur.execute(
        "SELECT v13_resolve_unknown(%s, 'not_happened', %s::jsonb)",
        (nope, json.dumps({"observation": "absent"})))
    check("not_happened accepted", cur.fetchone()[0] == "accepted")
    cur.execute("SELECT v13_worktree_state(%s)", (sid_n,))
    check("not_happened stays prepared", cur.fetchone()[0] == "prepared")

    cur.execute(
        "SELECT v13_spawn_subsession(%s, %s::jsonb)",
        (sid, json.dumps({"schema_version": 1, "children": [{"tool_call_id": "k", "task": "nope"}]})))
    child = cur.fetchone()[0]["children"][0]["session_id"]
    check("child does not inherit released event", event_count(cur, child, "worktree/released") == 0)
    cur.execute("SELECT v13_worktree_state(%s)", (child,))
    check("child projection null", cur.fetchone()[0] is None)

    def guard_insert(label, payload, source, session=sid):
        before = event_count(cur, session, "worktree/released")
        fails_with(
            cur,
            "INSERT INTO events (session_id, seq, event_id, type, payload, payload_hash, source_effect_id) "
            "SELECT %s, 900000 + floor(random()*100000)::int, %s, 'worktree/released', p.payload, "
            "encode(digest(p.payload::text, 'sha256'), 'hex'), %s FROM (SELECT %s::jsonb AS payload) p",
            (session, u(), source, json.dumps(payload)),
            "v13: worktree released", label)
        check(label + " event count unchanged", event_count(cur, session, "worktree/released") == before)

    guard_insert("missing key", {"schema_version": 1}, rel)
    guard_insert("extra key", {"schema_version": 1, "binding_artifact_id": bid, "extra": 1}, rel)
    guard_insert("string schema_version", {"schema_version": "1", "binding_artifact_id": bid}, rel)
    guard_insert("noncanonical uuid", {"schema_version": 1, "binding_artifact_id": bid.upper()}, rel)
    guard_insert("null source", {"schema_version": 1, "binding_artifact_id": bid}, None)
    other = session_with_user(cur)
    guard_insert("cross session source", {"schema_version": 1, "binding_artifact_id": bid}, rel, other)
    plain = enqueue(cur, sid, "tool", {"tool": "send_summary_email", "params": {}}, "send_summary_email")
    settle(cur, plain, {"ok": True})
    guard_insert("non release source", {"schema_version": 1, "binding_artifact_id": bid}, plain)
    mismatch = u()
    guard_insert("payload binding != request", {"schema_version": 1, "binding_artifact_id": mismatch}, rel)

    cur.execute("ALTER TABLE events DISABLE TRIGGER trg_v13_seam_event_guard")
    orphan = open_session(cur)
    cur.execute(
        "INSERT INTO events (session_id, seq, event_id, type, payload, payload_hash) "
        "SELECT %s, 1, %s, 'worktree/released', p.payload, encode(digest(p.payload::text, 'sha256'), 'hex') "
        "FROM (SELECT jsonb_build_object('schema_version', 1, 'binding_artifact_id', %s) AS payload) p",
        (orphan, u(), u()))
    cur.execute("SELECT v13_worktree_state(%s)", (orphan,))
    check("orphan event does not project released", cur.fetchone()[0] is None)
    cur.execute("ALTER TABLE events ENABLE TRIGGER trg_v13_seam_event_guard")
    conn.rollback()

    sid_p = session_with_user(cur)
    bid_p = u()
    prepare_latch(cur, sid_p, bid_p)
    ready_p = enqueue(cur, sid_p, "tool", wt_request("worktree_release", bid_p, trev(cur, sid_p)), "worktree_release")
    cur.execute("SELECT v13_claim('cmp', 60000)")
    claim_prepared = cur.fetchone()[0]
    sid_r = session_with_user(cur)
    bid_r = u()
    prepare_latch(cur, sid_r, bid_r)
    rel_r = enqueue(cur, sid_r, "tool", wt_request("worktree_release", bid_r, trev(cur, sid_r)), "worktree_release")
    settle(cur, rel_r, {"schema_version": 1})
    ready_r = enqueue(cur, sid_r, "tool", wt_request("worktree_release", bid_r, trev(cur, sid_r) + 2), "worktree_release")
    cur.execute("SELECT v13_worktree_state(%s)", (sid_r,))
    check("claim fixture projection released", cur.fetchone()[0] == "released")
    cur.execute("SELECT v13_claim('cmp', 60000)")
    claim_released = cur.fetchone()[0]
    check("claim under released matches prepared latch",
          claim_prepared is not None and claim_released is not None
          and claim_prepared["kind"] == claim_released["kind"]
          and claim_prepared["request"]["tool"] == claim_released["request"]["tool"] == "worktree_release",
          (claim_prepared, claim_released))
    conn.rollback()

    sid_h = session_with_user(cur)
    bid_h = u()
    prepare_latch(cur, sid_h, bid_h)
    src = enqueue(cur, sid_h, "tool", wt_request("worktree_release", bid_h, trev(cur, sid_h)), "worktree_release")
    cur.execute("UPDATE effects SET status='succeeded' WHERE effect_id=%s", (src,))
    cur.execute("SELECT v13_state_hash(%s)", (sid_h,))
    h_before = cur.fetchone()[0]
    cur.execute("SELECT v13_state_hash(%s)", (sid_h,))
    check("state_hash stable before event", cur.fetchone()[0] == h_before)
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'worktree/released', %s::jsonb, %s)",
        (sid_h, u(), json.dumps({"schema_version": 1, "binding_artifact_id": bid_h}), src))
    cur.execute("SELECT v13_state_hash(%s)", (sid_h,))
    h_after = cur.fetchone()[0]
    check("state_hash changes when released event is folded in", h_after != h_before)
    cur.execute("SELECT v13_state_hash(%s)", (sid_h,))
    check("state_hash stable after event", cur.fetchone()[0] == h_after)
    cur.execute("SELECT v13_closeout(%s, 'completed', 'answered', false)", (sid_h,))
    seal = cur.fetchone()[0]
    cur.execute("SELECT v13_state_hash(%s)", (sid_h,))
    check("state_hash matches closeout and unknown type does not raise",
          cur.fetchone()[0] == seal["state_hash"])
    conn.rollback()
    conn.commit()
    cur.close()
    conn.close()

    concurrent(server)
    migration(server)
    print("[PASS] stage 21 gates")
    return 0


def concurrent(server):
    conn = connect(server)
    cur = conn.cursor()
    sid = session_with_user(cur)
    bid = u()
    prepare_latch(cur, sid, bid)
    src = enqueue(cur, sid, "tool", wt_request("worktree_release", bid, trev(cur, sid)), "worktree_release")
    cur.execute(
        "UPDATE effects SET status='succeeded', result=%s::jsonb WHERE effect_id=%s",
        (json.dumps({"schema_version": 1}), src))
    victim = enqueue(cur, sid, "tool", wt_request("worktree_release", bid, trev(cur, sid) + 1), "worktree_release")
    cur.execute(
        "UPDATE effects SET status='claimed', attempt_no=1, fence=7, lease_owner='b', "
        "lease_until=clock_timestamp()+interval '1 hour' WHERE effect_id=%s", (victim,))
    conn.commit()
    a = connect(server)
    acur = a.cursor()
    acur.execute("SELECT pg_backend_pid()")
    a_pid = acur.fetchone()[0]
    acur.execute("BEGIN")
    acur.execute("SELECT 1 FROM sessions WHERE session_id=%s FOR UPDATE", (sid,))
    acur.execute("SELECT pg_current_xact_id()::text")
    a_xid = acur.fetchone()[0]
    obs = connect(server)
    obs.autocommit = True
    ocur = obs.cursor()
    box = {}
    ready = threading.Event()

    def run_b():
        b = connect(server)
        bcur = b.cursor()
        bcur.execute("SET lock_timeout = '20s'")
        bcur.execute("SELECT pg_backend_pid()")
        box["pid"] = bcur.fetchone()[0]
        ready.set()
        try:
            bcur.execute(
                "SELECT v13_complete(%s, 1, 7, 'succeeded', %s::jsonb)",
                (victim, json.dumps({"schema_version": 1})))
            box["result"] = bcur.fetchone()[0]
            b.commit()
        except Exception as exc:
            box["error"] = str(exc)
            b.rollback()
        finally:
            b.close()

    thread = threading.Thread(target=run_b)
    thread.start()
    check("concurrent B started", ready.wait(5))
    seen = False
    deadline = time.time() + 8
    while time.time() < deadline and "result" not in box and "error" not in box:
        ocur.execute(
            "SELECT %s = ANY(pg_blocking_pids(%s)), "
            "EXISTS (SELECT 1 FROM pg_locks WHERE pid=%s AND locktype='transactionid' "
            "AND mode='ShareLock' AND NOT granted AND transactionid::text=%s), "
            "EXISTS (SELECT 1 FROM pg_stat_activity WHERE pid=%s "
            "AND wait_event_type='Lock' AND wait_event='transactionid')",
            (a_pid, box["pid"], box["pid"], a_xid, box["pid"]))
        blocking, xid_wait, wait_ev = ocur.fetchone()
        if blocking and xid_wait and wait_ev:
            seen = True
            break
        time.sleep(0.05)
    check("concurrent B waits on A's session xid before latch lock",
          seen and "result" not in box, (box, a_xid))
    try:
        acur.execute(
            "SELECT 1 FROM latches WHERE session_id=%s AND name='worktree' FOR UPDATE", (sid,))
        acur.execute(
            "INSERT INTO events (session_id, seq, event_id, type, payload, payload_hash, source_effect_id) "
            "SELECT %s, 1000000, %s, 'worktree/released', p.payload, "
            "encode(digest(p.payload::text, 'sha256'), 'hex'), %s "
            "FROM (SELECT jsonb_build_object('schema_version', 1, 'binding_artifact_id', %s) AS payload) p",
            (sid, u(), src, bid))
    except psycopg2.Error as exc:
        ocur.execute(
            "SELECT pid, locktype, relation::regclass::text, mode, granted, transactionid::text "
            "FROM pg_locks WHERE pid IN (%s, %s) AND (NOT granted OR locktype IN ('tuple','transactionid'))",
            (a_pid, box.get("pid")))
        snap = ocur.fetchall()
        raise AssertionError(f"40P01 or lock failure: {exc}\nlocks={snap}") from exc
    a.commit()
    thread.join(25)
    check("concurrent B returns succeeded", box.get("result") == "accepted" and "error" not in box, box)
    cur.execute("SELECT count(*) FROM events WHERE session_id=%s AND type='worktree/released'", (sid,))
    check("concurrent event count stays 1", cur.fetchone()[0] == 1)
    third = enqueue(cur, sid, "tool", wt_request("worktree_release", bid, trev(cur, sid) + 4), "worktree_release")
    word, _, _ = settle(cur, third, {"schema_version": 1})
    check("third release still succeeds", word == "accepted")
    cur.execute("SELECT count(*) FROM events WHERE session_id=%s AND type='worktree/released'", (sid,))
    check("third release event count stays 1", cur.fetchone()[0] == 1)
    conn.commit()
    conn.close()
    a.close()
    obs.close()


def _mig_clone(server, base, name):
    run_psql(server, "postgres", f"DROP DATABASE IF EXISTS {name} WITH (FORCE);")
    run_psql(server, "postgres", f"CREATE DATABASE {name} TEMPLATE {base};")
    return connect(server, name)


def migration(server):
    base = "agent_v13_seam_mig_base"
    sql = (ROOT / "v13_seam.sql").read_text()
    run_psql(server, "postgres", f"DROP DATABASE IF EXISTS {base} WITH (FORCE);")
    run_psql(server, "postgres", f"CREATE DATABASE {base};")
    load_stage(server, base, "triage")
    names = []

    def clone(tag):
        name = f"agent_v13_seam_mig_{tag}"
        names.append(name)
        return name, _mig_clone(server, base, name)

    name, conn = clone("bare")
    cur = conn.cursor()
    sid = open_session(cur)
    bid = u()
    cur.execute(
        "INSERT INTO latches (session_id, name, value) VALUES (%s, 'worktree', %s::jsonb)",
        (sid, json.dumps({
            "schema_version": 1, "binding_artifact_id": bid, "state": "released"})))
    conn.commit()
    conn.close()
    try:
        run_psql(server, name, sql)
        raise AssertionError("migration released latch without event should fail")
    except RuntimeError as exc:
        msg = str(exc)
        check("migration released latch without event fails",
              sid in msg and bid in msg, msg.splitlines()[-1])

    name, conn = clone("bad")
    cur = conn.cursor()
    sid = open_session(cur)
    bid = u()
    src = u()
    req = wt_request("worktree_release", bid, 1)
    cur.execute(
        "INSERT INTO effects (effect_id, session_id, kind, tool_name, request, request_hash, "
        "origin_user_seq, status) VALUES (%s, %s, 'tool', 'worktree_release', %s::jsonb, "
        "encode(digest(%s::jsonb::text, 'sha256'), 'hex'), 0, 'succeeded')",
        (src, sid, json.dumps(req), json.dumps(req)))
    cur.execute(
        "INSERT INTO latches (session_id, name, value) VALUES (%s, 'worktree', %s::jsonb)",
        (sid, json.dumps({
            "schema_version": 1, "binding_artifact_id": bid, "state": "prepared"})))
    cur.execute(
        "INSERT INTO events (session_id, seq, event_id, type, payload, payload_hash, source_effect_id) "
        "VALUES (%s, 3, %s, 'worktree/released', %s::jsonb, 'abc', %s)",
        (sid, u(), json.dumps({"schema_version": "1", "binding_artifact_id": bid}), src))
    conn.commit()
    conn.close()
    try:
        run_psql(server, name, sql)
        raise AssertionError("migration malformed event should fail")
    except RuntimeError as exc:
        msg = str(exc)
        check("migration malformed event fails", sid in msg and bid in msg, msg.splitlines()[-1])

    name, conn = clone("ok")
    cur = conn.cursor()
    sid = open_session(cur)
    bid = u()
    src = u()
    req = wt_request("worktree_release", bid, 1)
    cur.execute(
        "INSERT INTO effects (effect_id, session_id, kind, tool_name, request, request_hash, "
        "origin_user_seq, status) VALUES (%s, %s, 'tool', 'worktree_release', %s::jsonb, "
        "encode(digest(%s::jsonb::text, 'sha256'), 'hex'), 0, 'succeeded')",
        (src, sid, json.dumps(req), json.dumps(req)))
    cur.execute(
        "INSERT INTO latches (session_id, name, value) VALUES (%s, 'worktree', %s::jsonb)",
        (sid, json.dumps({
            "schema_version": 1, "binding_artifact_id": bid, "state": "released"})))
    cur.execute(
        "INSERT INTO events (session_id, seq, event_id, type, payload, payload_hash, source_effect_id) "
        "SELECT %s, 4, %s, 'worktree/released', p.payload, encode(digest(p.payload::text, 'sha256'), 'hex'), %s "
        "FROM (SELECT jsonb_build_object('schema_version', 1, 'binding_artifact_id', %s) AS payload) p",
        (sid, u(), src, bid))
    conn.commit()
    run_psql(server, name, sql)
    cur.execute("SELECT v13_worktree_state(%s)", (sid,))
    check("migration legal event keeps projection released", cur.fetchone()[0] == "released")
    cur.execute("SELECT value->>'state' FROM latches WHERE session_id=%s AND name='worktree'", (sid,))
    check("migration does not rewrite latch state", cur.fetchone()[0] == "released")
    conn.close()
    for name in [base, *names]:
        run_psql(server, "postgres", f"DROP DATABASE IF EXISTS {name} WITH (FORCE);")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[FAIL] {exc}")
        raise
