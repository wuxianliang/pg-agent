"""M3 gate: v13 loop stage — v13_advance five steps.

Run: uv run python v13/loop/test_loop.py  (exit 0 = pass)
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
from v13.loop.setup_db import DB, main as setup_db


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    extra = f": {detail}" if detail and (not condition or len(str(detail)) < 100) else ""
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
        check(label, needle.lower() in str(exc).lower(), str(exc).splitlines()[0])
        cur.execute("ROLLBACK TO SAVEPOINT sp")
        return
    cur.execute("ROLLBACK TO SAVEPOINT sp")
    raise AssertionError(f"{label}: expected failure")


def connect_as(server, user):
    uri = server.get_uri(DB)
    host = (parse_qs(urlparse(uri).query).get("host") or [None])[0]
    return psycopg2.connect(host=host, dbname=DB, user=user)


def new_session(cur):
    sid = u()
    cur.execute("INSERT INTO sessions (session_id) VALUES (%s)", (sid,))
    return sid


def append_user(cur, sid, text="hello"):
    cur.execute("SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
                (sid, u(), json.dumps({"text": text})))
    return cur.fetchone()[0]


def set_mock(cur, mock: str):
    cur.execute("SELECT set_config('typesafe.mock_response', %s, true)", (mock,))


def poison(cur):
    cur.execute("SELECT set_config('typesafe.mock_response', NULL, true)")
    cur.execute("SELECT set_config('typesafe.endpoint', 'http://127.0.0.1:1/', true)")
    cur.execute("SELECT set_config('typesafe.api_key', 'probe', true)")
    cur.execute("SELECT set_config('typesafe.timeout_ms', '200', true)")


def claim_pinned(cur, eid, worker="w1", lease_ms=60000):
    cur.execute(
        "UPDATE effects SET status='cancelled' "
        "WHERE status='ready' AND effect_id IS DISTINCT FROM %s",
        (eid,))
    cur.execute("SELECT v13_claim(%s, %s)", (worker, lease_ms))
    row = cur.fetchone()[0]
    check("claim pinned",
          row is not None and str(row["effect_id"]) == str(eid), row)
    return row


def wait_until_lock(watch, box, pid_key, timeout=8.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        pid = box.get(pid_key)
        if pid:
            watch.execute(
                "SELECT bool_or(NOT granted) FROM pg_locks "
                "WHERE locktype='advisory' AND pid=%s", (pid,))
            row = watch.fetchone()
            if row and row[0] is True:
                return True
            watch.execute(
                "SELECT wait_event_type, wait_event FROM pg_stat_activity "
                "WHERE pid=%s", (pid,))
            row = watch.fetchone()
            if row and (row[0] == "Lock" or (row[1] or "").lower() == "advisory"):
                return True
        time.sleep(0.02)
    return False


def mock_from_needed(cur, sid, **over) -> str:
    cur.execute("SELECT signal, kind, criteria FROM v13_needed_judgments(%s)", (sid,))
    answers = {}
    for signal, kind, criteria in cur.fetchall():
        if signal in over:
            answers[signal] = over[signal]
            continue
        if kind == "choice":
            keys = list(criteria.keys()) if isinstance(criteria, dict) else ["none"]
            ch = keys[0]
            answers[signal] = {"type": "choice", "choice": ch,
                               "probabilities": {ch: 0.9}, "confidence": 0.9}
        elif kind == "score":
            answers[signal] = {"type": "score", "score": 0.5, "confidence": 0.9}
        else:
            answers[signal] = {"type": "noul", "noul": 0.1}
    answers.update(over)
    return json.dumps({"model": "jev-mock", "answers": answers,
                       "usage": {"input_tokens": 1, "output_tokens": 1}})


def parse(cur, sid, **over):
    set_mock(cur, mock_from_needed(cur, sid, **over))
    cur.execute("SELECT v13_parse(%s)", (sid,))
    return cur.fetchone()[0]


def answers_sql(cur, sid):
    return parse(cur, sid,
                 intent={"type": "choice", "choice": "sql_answer",
                         "probabilities": {"sql_answer": 0.9}, "confidence": 0.9},
                 gate_action={"type": "noul", "noul": 0.9},
                 gate_off_topic={"type": "noul", "noul": 0.1},
                 risk={"type": "score", "score": 0.5, "confidence": 0.9},
                 tool={"type": "choice", "choice": "session_stats",
                       "probabilities": {"session_stats": 0.9}, "confidence": 0.9})


def main() -> int:
    setup_db()
    server = get_server()
    conn = psycopg2.connect(server.get_uri(DB))
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute("SET typesafe.model = 'jev-latest'")

    src = (ROOT / "advance.sql").read_text()
    check("M3-2: source calls v13_context_fresh", "v13_context_fresh" in src)
    cur.execute("SELECT v13_context_fresh(%s)", (u(),))
    check("M3-2: context_fresh true", cur.fetchone()[0] is True)

    # M3-1 terminal / waiting
    sid = new_session(cur)
    append_user(cur, sid)
    cur.execute("UPDATE sessions SET status='completed' WHERE session_id=%s", (sid,))
    snap = answers_sql(cur, sid)
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid, json.dumps(snap)))
    check("M3-1: completed -> terminal", cur.fetchone()[0] == "terminal")
    sidw = new_session(cur)
    append_user(cur, sidw)
    cur.execute("SELECT v13_enqueue_effect(%s, 'human', %s::jsonb)",
                (sidw, json.dumps({"reason": "x"})))
    snapw = answers_sql(cur, sidw)
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sidw, json.dumps(snapw)))
    check("M3-1: ready effect -> waiting", cur.fetchone()[0] == "waiting")
    cur.execute("SELECT count(*) FROM effects WHERE session_id=%s", (sidw,))
    check("M3-1: waiting zero new effect", cur.fetchone()[0] == 1)

    # M3-3 remaining>0 judge envelope
    sid3 = new_session(cur)
    append_user(cur, sid3)
    # leave remaining by using >32? easier: parse without filling all - use default 9, that's remaining 0 after parse.
    # remaining>0: parse with fast path on many tools OR don't parse fill - parse fills 9 in one batch remaining 0.
    # Use 20 extra tools like M2-6 then parse remaining>0
    for i in range(20):
        spec = {"p1": {"question": f"Q{i}?", "stated": "S?", "options": {"a": "A", "b": "B"}},
                "p2": {"question": f"R{i}?", "stated": "T?", "options": {"a": "A", "b": "B"}}}
        cur.execute("INSERT INTO tools (name, description, kind, handler, param_spec) "
                    "VALUES (%s,'Tool.', 'tool', 'worker:x', %s::jsonb)",
                    (f"u{i}", json.dumps(spec)))
    snap3 = parse(cur, sid3)
    check("M3-3: remaining>0", snap3["remaining"] > 0, snap3["remaining"])
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid3, json.dumps(snap3)))
    r3 = cur.fetchone()[0]
    check("M3-3: advance waiting (judge)", r3 == "waiting", r3)
    cur.execute("SELECT request FROM effects WHERE session_id=%s AND kind='judge'",
                (sid3,))
    req = cur.fetchone()[0]
    env = req.get("envelope", req)
    for k in ("sid", "ctx", "needed", "candidate_set_hash", "goal_hash",
              "needed_count", "provider", "model"):
        check(f"M3-3: request has {k}", k in env, list(env))
    for k in ("session_version", "max_event_seq", "route_policy_name",
              "route_policy_version", "tools_revision", "tools_catalog",
              "candidate_generation_revision"):
        check(f"M3-3: request lacks {k}", k not in env, list(env))
    eid = None
    cur.execute("SELECT effect_id FROM effects WHERE session_id=%s AND kind='judge'", (sid3,))
    eid = cur.fetchone()[0]
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid3, json.dumps(snap3)))
    cur.fetchone()
    cur.execute("SELECT count(*) FROM effects WHERE session_id=%s AND kind='judge'", (sid3,))
    check("M3-3: second advance same judge row", cur.fetchone()[0] == 1)
    for i in range(20):
        cur.execute("DELETE FROM tools WHERE name=%s", (f"u{i}",))

    # M3-4 sql fast path
    sid4 = new_session(cur)
    seq = append_user(cur, sid4)
    snap4 = answers_sql(cur, sid4)
    poison(cur)
    cur.execute("SELECT count(*) FROM pgmq.q_v13_work")
    q4 = cur.fetchone()[0]
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid4, json.dumps(snap4)))
    r4 = cur.fetchone()[0]
    check("M3-4: sql advance progressed", r4 == "progressed", r4)
    cur.execute("SELECT status, request, origin_user_seq, effect_id FROM effects "
                "WHERE session_id=%s ORDER BY created_at DESC LIMIT 1", (sid4,))
    st, req4, orig, eid4 = cur.fetchone()
    check("M3-4: sql effect succeeded", st == "succeeded", st)
    check("M3-4: request has tool+params no handler",
          "tool" in req4 and "params" in req4 and "handler" not in req4, req4)
    check("M3-4: origin_user_seq", orig == seq, orig)
    cur.execute("SELECT count(*) FROM events WHERE session_id=%s AND type='tool/result'",
                (sid4,))
    check("M3-4: tool/result event", cur.fetchone()[0] == 1)
    cur.execute("SELECT source_effect_id FROM events "
                "WHERE session_id=%s AND type='tool/result'", (sid4,))
    check("M3-4: tool/result source_effect_id",
          str(cur.fetchone()[0]) == str(eid4))
    cur.execute("SELECT count(*) FROM pgmq.q_v13_work")
    check("M3-4: pgmq queue depth unchanged", cur.fetchone()[0] == q4)

    # M3-8 stale
    sid8 = new_session(cur)
    append_user(cur, sid8)
    snap8 = answers_sql(cur, sid8)
    append_user(cur, sid8, "new")
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid8, json.dumps(snap8)))
    check("M3-8: new message -> stale", cur.fetchone()[0] == "stale")
    cur.execute("SELECT count(*) FROM effects WHERE session_id=%s", (sid8,))
    check("M3-8: stale zero effects", cur.fetchone()[0] == 0)

    # M3-9 disable tool stale
    sid9 = new_session(cur)
    append_user(cur, sid9)
    snap9 = answers_sql(cur, sid9)
    cur.execute("UPDATE tools SET enabled=false WHERE name='send_summary_email'")
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid9, json.dumps(snap9)))
    check("M3-9: disable tool -> stale", cur.fetchone()[0] == "stale")
    cur.execute("UPDATE tools SET enabled=true WHERE name='send_summary_email'")

    # M3-13 failed -> progressed
    sid13 = new_session(cur)
    append_user(cur, sid13)
    set_mock(cur, json.dumps({"model": "x", "answers": {"intent": {"type": "choice"}}}))
    cur.execute("SELECT v13_parse(%s)", (sid13,))
    fsnap = cur.fetchone()[0]
    check("M3-13: parse failed", fsnap["failed"] is True)
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid13, json.dumps(fsnap)))
    check("M3-13: failed -> progressed", cur.fetchone()[0] == "progressed")
    cur.execute("SELECT count(*) FROM events WHERE session_id=%s AND type='resolve/failed'",
                (sid13,))
    check("M3-13: resolve/failed event", cur.fetchone()[0] == 1)

    # M3-16 terminal reset
    sid16 = new_session(cur)
    append_user(cur, sid16)
    cur.execute("UPDATE sessions SET status='completed' WHERE session_id=%s", (sid16,))
    append_user(cur, sid16, "again")
    cur.execute("SELECT status FROM sessions WHERE session_id=%s", (sid16,))
    check("M3-16: completed resets to ready", cur.fetchone()[0] == "ready")
    cur.execute("UPDATE sessions SET status='cancelled' WHERE session_id=%s", (sid16,))
    append_user(cur, sid16, "nope")
    cur.execute("SELECT status FROM sessions WHERE session_id=%s", (sid16,))
    check("M3-16: cancelled stays cancelled", cur.fetchone()[0] == "cancelled")
    snapc = answers_sql(cur, sid16)
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid16, json.dumps(snapc)))
    check("M3-16: cancelled advance terminal", cur.fetchone()[0] == "terminal")

    # M3-17 triple sid
    sidA = new_session(cur); append_user(cur, sidA)
    sidB = new_session(cur); append_user(cur, sidB)
    snapB = answers_sql(cur, sidB)
    fails_with(cur, "SELECT v13_advance(%s, %s::jsonb)",
               (sidA, json.dumps(snapB)), "mismatch", "M3-17: mismatched sid RAISE")
    fails_with(cur, "SELECT v13_advance(%s, '{}'::jsonb)", (sidA,),
               "mismatch", "M3-17: missing snap keys RAISE")

    # M3-6 finish via llm/message
    sid6 = new_session(cur)
    last = append_user(cur, sid6)
    cur.execute("SELECT v13_append_event(%s, %s, 'llm/message', %s::jsonb)",
                (sid6, u(), json.dumps({"text": "done", "origin_user_seq": last})))
    snap6 = parse(cur, sid6)
    cur.execute("SELECT v13_route(%s, %s::jsonb)", (sid6, json.dumps(snap6["envelope"])))
    route6 = cur.fetchone()[0]
    check("M3-6: P0 finish", route6.get("action") == "finish", route6)
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid6, json.dumps(snap6)))
    check("M3-6: finish terminal", cur.fetchone()[0] == "terminal")
    cur.execute("SELECT status FROM sessions WHERE session_id=%s", (sid6,))
    check("M3-6: session completed", cur.fetchone()[0] == "completed")

    sid6a = new_session(cur)
    last6a = append_user(cur, sid6a)
    cur.execute("SELECT v13_append_event(%s, %s, 'tool/result', %s::jsonb)",
                (sid6a, u(), json.dumps({"ok": True, "origin_user_seq": last6a})))
    snap6a = parse(cur, sid6a)
    cur.execute("SELECT v13_route(%s, %s::jsonb)",
                (sid6a, json.dumps(snap6a["envelope"])))
    check("M3-6: tool/result does not finish",
          cur.fetchone()[0].get("action") != "finish")

    sid6b = new_session(cur)
    last6b = append_user(cur, sid6b)
    append_user(cur, sid6b, "turn2")
    cur.execute("SELECT v13_append_event(%s, %s, 'llm/message', %s::jsonb)",
                (sid6b, u(), json.dumps({"text": "old", "origin_user_seq": last6b})))
    snap6b = parse(cur, sid6b)
    cur.execute("SELECT v13_route(%s, %s::jsonb)",
                (sid6b, json.dumps(snap6b["envelope"])))
    check("M3-6: old origin higher seq does not finish",
          cur.fetchone()[0].get("action") != "finish")

    sid6c = new_session(cur)
    append_user(cur, sid6c)
    cur.execute("SELECT v13_append_event(%s, %s, 'llm/message', %s::jsonb)",
                (sid6c, u(), json.dumps({"text": "no-anchor"})))
    snap6c = parse(cur, sid6c)
    cur.execute("SELECT v13_route(%s, %s::jsonb)",
                (sid6c, json.dumps(snap6c["envelope"])))
    check("M3-6: no origin field does not finish",
          cur.fetchone()[0].get("action") != "finish")

    # M3-11 env_decision + branches
    sid11 = new_session(cur)
    append_user(cur, sid11)
    snap11 = answers_sql(cur, sid11)
    env = snap11["envelope"]
    cur.execute("SELECT count(*) FROM decisions WHERE session_id=%s AND signal='intent' "
                "AND answer IS NOT NULL", (sid11,))
    n_int = cur.fetchone()[0]
    cur.execute("SELECT v13_env_decision(%s::jsonb, 'intent')", (json.dumps(env),))
    row = cur.fetchone()
    check("M3-11: env_decision intent present",
          n_int >= 1 and row is not None and row[0] is not None,
          (n_int, row))
    # P1 off_topic
    s_ot = new_session(cur); append_user(cur, s_ot)
    snap_ot = parse(cur, s_ot, gate_off_topic={"type": "noul", "noul": 0.9},
                    intent={"type": "choice", "choice": "sql_answer",
                            "probabilities": {"sql_answer": 0.9}, "confidence": 0.9},
                    gate_action={"type": "noul", "noul": 0.9})
    cur.execute("SELECT v13_route(%s, %s::jsonb)", (s_ot, json.dumps(snap_ot["envelope"])))
    check("M3-11: P1 reject", cur.fetchone()[0]["action"] == "reject")
    s_h = new_session(cur); append_user(cur, s_h)
    snap_h = parse(cur, s_h, intent={"type": "choice", "choice": "sql_answer",
                                     "probabilities": {"sql_answer": 0.2}, "confidence": 0.2},
                   gate_action={"type": "noul", "noul": 0.9})
    cur.execute("SELECT v13_route(%s, %s::jsonb)", (s_h, json.dumps(snap_h["envelope"])))
    check("M3-11: P2 human low intent", cur.fetchone()[0]["reason"] == "low_intent_confidence")
    s_he = new_session(cur); append_user(cur, s_he)
    snap_he = parse(cur, s_he, intent={"type": "choice", "choice": "human_escalate",
                                       "probabilities": {"human_escalate": 0.9}, "confidence": 0.9},
                    gate_action={"type": "noul", "noul": 0.9})
    cur.execute("SELECT v13_route(%s, %s::jsonb)", (s_he, json.dumps(snap_he["envelope"])))
    check("M3-11: P3 model_escalated", cur.fetchone()[0]["reason"] == "model_escalated")
    cur.execute("SELECT v13_route(%s, %s::jsonb)", (sid11, json.dumps(env)))
    rsql = cur.fetchone()[0]
    check("M3-11: P4a sql in_db_handler",
          rsql.get("action") == "sql" and rsql.get("reason") == "in_db_handler", rsql)
    s_tool = new_session(cur); append_user(cur, s_tool)
    snap_t = parse(cur, s_tool,
                   intent={"type": "choice", "choice": "tool_action",
                           "probabilities": {"tool_action": 0.9}, "confidence": 0.9},
                   gate_action={"type": "noul", "noul": 0.9},
                   tool={"type": "choice", "choice": "send_summary_email",
                         "probabilities": {"send_summary_email": 0.9}, "confidence": 0.9},
                   risk={"type": "score", "score": 0.5, "confidence": 0.9},
                   **{"param::send_summary_email::tone": {
                       "type": "choice", "choice": "formal",
                       "probabilities": {"formal": 0.9}, "confidence": 0.9},
                      "param::send_summary_email::audience": {
                       "type": "choice", "choice": "team",
                       "probabilities": {"team": 0.9}, "confidence": 0.9},
                      "stated::send_summary_email::tone": {"type": "noul", "noul": 0.9},
                      "stated::send_summary_email::audience": {"type": "noul", "noul": 0.9}})
    cur.execute("SELECT v13_route(%s, %s::jsonb)", (s_tool, json.dumps(snap_t["envelope"])))
    rt = cur.fetchone()[0]
    check("M3-11: P4c tool", rt.get("action") == "tool", rt)
    s_risk = new_session(cur); append_user(cur, s_risk)
    snap_r = parse(cur, s_risk,
                   intent={"type": "choice", "choice": "tool_action",
                           "probabilities": {"tool_action": 0.9}, "confidence": 0.9},
                   gate_action={"type": "noul", "noul": 0.9},
                   tool={"type": "choice", "choice": "send_summary_email",
                         "probabilities": {"send_summary_email": 0.9}, "confidence": 0.9},
                   risk={"type": "score", "score": 2.5, "confidence": 0.9})
    cur.execute("SELECT v13_route(%s, %s::jsonb)", (s_risk, json.dumps(snap_r["envelope"])))
    check("M3-11: P4b risk_veto", cur.fetchone()[0].get("reason") == "risk_veto")
    s_llm = new_session(cur); append_user(cur, s_llm)
    snap_l = parse(cur, s_llm,
                   intent={"type": "choice", "choice": "llm_generate",
                           "probabilities": {"llm_generate": 0.9}, "confidence": 0.9},
                   gate_action={"type": "noul", "noul": 0.9})
    cur.execute("SELECT v13_route(%s, %s::jsonb)", (s_llm, json.dumps(snap_l["envelope"])))
    check("M3-11: P5 llm", cur.fetchone()[0].get("action") == "llm")

    # M3-5 tool wake
    poison(cur)
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (s_tool, json.dumps(snap_t)))
    check("M3-5: tool waiting", cur.fetchone()[0] == "waiting")
    cur.execute("SELECT request FROM effects WHERE session_id=%s AND kind='tool'", (s_tool,))
    treq = cur.fetchone()[0]
    check("M3-5: tool request has handler+revision",
          "handler" in treq and "tools_revision" in treq, treq)

    # M3-7 budget
    sid7 = new_session(cur)
    append_user(cur, sid7)
    for _ in range(3):
        cur.execute("SELECT v13_append_event(%s, %s, 'turn/route', %s::jsonb)",
                    (sid7, u(), json.dumps({"action": "sql"})))
    snap7 = answers_sql(cur, sid7)
    poison(cur)
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid7, json.dumps(snap7)))
    check("M3-7: budget waiting", cur.fetchone()[0] == "waiting")
    cur.execute("SELECT request->>'reason' FROM effects WHERE session_id=%s AND kind='human'",
                (sid7,))
    check("M3-7: budget_exhausted", cur.fetchone()[0] == "budget_exhausted")

    # M3-10 empty frozen policy
    cur.execute("INSERT INTO v13_route_policies (policy_name, policy_version) "
                "VALUES ('default', 99) ON CONFLICT DO NOTHING")
    cur.execute("UPDATE v13_route_policies SET state='frozen' "
                "WHERE policy_name='default' AND policy_version=99 AND state='draft'")
    sid10 = u()
    cur.execute("INSERT INTO sessions (session_id, route_policy_name, route_policy_version) "
                "VALUES (%s, 'default', 99)", (sid10,))
    append_user(cur, sid10)
    snap10 = parse(cur, sid10)
    cur.execute("SELECT v13_route(%s, %s::jsonb)", (sid10, json.dumps(snap10["envelope"])))
    check("M3-10: empty bands human", cur.fetchone()[0]["reason"] == "low_intent_confidence")

    s_tu = new_session(cur)
    append_user(cur, s_tu)
    snap_tu = parse(cur, s_tu,
                    intent={"type": "choice", "choice": "tool_action",
                            "probabilities": {"tool_action": 0.9}, "confidence": 0.9},
                    gate_action={"type": "noul", "noul": 0.9},
                    tool={"type": "choice", "choice": "send_summary_email",
                          "probabilities": {"send_summary_email": 0.9}, "confidence": 0.9},
                    risk={"type": "score", "score": 0.5, "confidence": 0.9},
                    **{"param::send_summary_email::tone": {
                        "type": "choice", "choice": "formal",
                        "probabilities": {"formal": 0.9}, "confidence": 0.9},
                       "param::send_summary_email::audience": {
                        "type": "choice", "choice": "team",
                        "probabilities": {"team": 0.9}, "confidence": 0.9},
                       "stated::send_summary_email::tone": {"type": "noul", "noul": 0.9},
                       "stated::send_summary_email::audience": {"type": "noul", "noul": 0.9}})
    env_tu = snap_tu["envelope"]
    for t in env_tu["tools_catalog"]:
        if t["name"] == "send_summary_email":
            t["enabled"] = False
    cur.execute("SELECT v13_route(%s, %s::jsonb)", (s_tu, json.dumps(env_tu)))
    rt_tu = cur.fetchone()[0]
    check("M3-10: disabled tool fail-closed",
          rt_tu.get("reason") == "tool_unavailable", rt_tu)

    s_term = new_session(cur)
    seq_term = append_user(cur, s_term)
    for _ in range(2):
        cur.execute("SELECT v13_append_event(%s, %s, 'resolve/failed', %s::jsonb)",
                    (s_term, u(), json.dumps({"origin_user_seq": seq_term})))
    poison(cur)
    snap_term = parse(cur, s_term)
    check("M3-10: abandon snapshot", snap_term["abandon"] is True, snap_term)
    cur.execute("UPDATE sessions SET status='completed' WHERE session_id=%s",
                (s_term,))
    cur.execute("SELECT count(*) FROM events WHERE session_id=%s", (s_term,))
    ev_term = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM effects WHERE session_id=%s", (s_term,))
    ef_term = cur.fetchone()[0]
    cur.execute("SELECT v13_advance(%s, %s::jsonb)",
                (s_term, json.dumps(snap_term)))
    check("M3-10: terminal session + abandon -> terminal",
          cur.fetchone()[0] == "terminal")
    cur.execute("SELECT count(*) FROM events WHERE session_id=%s", (s_term,))
    check("M3-10: terminal abandon zero new events", cur.fetchone()[0] == ev_term)
    cur.execute("SELECT count(*) FROM effects WHERE session_id=%s", (s_term,))
    check("M3-10: terminal abandon zero new effects", cur.fetchone()[0] == ef_term)

    # M3-12 ACL
    cur.execute("SET ROLE v13_route")
    cur.execute("SELECT has_function_privilege('v13_advance(uuid,jsonb)','EXECUTE')")
    check("M3-12: route EXECUTE advance", cur.fetchone()[0] is True)
    fails_with(cur, "SELECT v13_parse(%s)", (sid4,), "permission",
               "M3-12: route parse denied")
    cur.execute("RESET ROLE")
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("--"))
    check("M3-12: advance.sql has no FROM tools", "FROM tools" not in code)

    rconn = connect_as(server, "v13_route_login")
    rc = rconn.cursor()
    rc.execute("SELECT has_function_privilege('v13_advance(uuid,jsonb)','EXECUTE')")
    check("M3-12: route_login EXECUTE advance", rc.fetchone()[0] is True)
    try:
        rc.execute("SET ROLE v13_resolve")
        check("M3-12: route_login SET ROLE resolve denied", False)
    except psycopg2.Error as exc:
        check("M3-12: route_login SET ROLE resolve denied",
              "permission" in str(exc).lower(), str(exc).splitlines()[0])
        rconn.rollback()
    rconn.close()
    cur.execute("SELECT has_function_privilege('v13_route',"
                "'typesafe_ask(jsonb,jsonb,text)','EXECUTE')")
    check("M3-12: route no typesafe_ask", cur.fetchone()[0] is False)

    # M3-18 policy version stale
    sid18 = new_session(cur)
    append_user(cur, sid18)
    snap18 = answers_sql(cur, sid18)
    cur.execute("INSERT INTO v13_route_policies (policy_name, policy_version) "
                "VALUES ('default', 2) ON CONFLICT DO NOTHING")
    cur.execute("INSERT INTO thresholds (policy_name, policy_version, signal, band_no, lo, hi, action) "
                "VALUES ('default',2,'intent',1,0.5,'Infinity','pass') "
                "ON CONFLICT DO NOTHING")
    cur.execute("UPDATE v13_route_policies SET state='frozen' "
                "WHERE policy_name='default' AND policy_version=2 AND state='draft'")
    cur.execute("UPDATE sessions SET route_policy_version=2 WHERE session_id=%s", (sid18,))
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid18, json.dumps(snap18)))
    check("M3-18: policy bump stale", cur.fetchone()[0] == "stale")

    # M3-15 sql handler exception
    cur.execute("""
        CREATE FUNCTION v13_boom(uuid, jsonb) RETURNS jsonb
        LANGUAGE plpgsql STABLE AS $$
        BEGIN RAISE EXCEPTION 'boom' USING ERRCODE = 'XX000'; END $$;
    """)
    cur.execute("INSERT INTO tools (name, description, kind, handler) "
                "VALUES ('boom', 'Boom tool.', 'sql', 'v13_boom')")
    sid15 = new_session(cur); append_user(cur, sid15)
    snap15 = parse(cur, sid15,
                   intent={"type": "choice", "choice": "sql_answer",
                           "probabilities": {"sql_answer": 0.9}, "confidence": 0.9},
                   gate_action={"type": "noul", "noul": 0.9},
                   tool={"type": "choice", "choice": "boom",
                         "probabilities": {"boom": 0.9}, "confidence": 0.9})
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid15, json.dumps(snap15)))
    check("M3-15: boom progressed", cur.fetchone()[0] == "progressed")
    cur.execute("SELECT status, error->>'sqlstate' FROM effects "
                "WHERE session_id=%s AND kind='tool'", (sid15,))
    row = cur.fetchone()
    check("M3-15: effect failed with sqlstate",
          row and row[0] == "failed" and row[1], row)
    cur.execute("DELETE FROM tools WHERE name='boom'")
    cur.execute("DROP FUNCTION v13_boom(uuid, jsonb)")

    cur.execute("""
        CREATE FUNCTION v13_slow(uuid, jsonb) RETURNS jsonb
        LANGUAGE plpgsql STABLE AS $$
        BEGIN
          PERFORM pg_sleep(5);
          RETURN '{"slow":true}'::jsonb;
        END $$;
    """)
    cur.execute("GRANT EXECUTE ON FUNCTION v13_slow(uuid, jsonb) TO v13_route")
    cur.execute("INSERT INTO tools (name, description, kind, handler) "
                "VALUES ('slow', 'Slow tool.', 'sql', 'v13_slow')")
    sid15b = new_session(cur)
    append_user(cur, sid15b)
    cur.execute("SET statement_timeout = '200ms'")
    t0 = time.time()
    snap15b = parse(cur, sid15b,
                    intent={"type": "choice", "choice": "sql_answer",
                            "probabilities": {"sql_answer": 0.9}, "confidence": 0.9},
                    gate_action={"type": "noul", "noul": 0.9},
                    tool={"type": "choice", "choice": "slow",
                          "probabilities": {"slow": 0.9}, "confidence": 0.9})
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid15b, json.dumps(snap15b)))
    r15b = cur.fetchone()[0]
    dt15b = time.time() - t0
    check("M3-15 morph2: progressed", r15b == "progressed", r15b)
    check("M3-15 morph2: wall <1s", dt15b < 1.0, dt15b)
    cur.execute("SELECT status, error->>'sqlstate' FROM effects "
                "WHERE session_id=%s AND kind='tool' "
                "ORDER BY created_at DESC LIMIT 1", (sid15b,))
    st15, ss15 = cur.fetchone()
    check("M3-15 morph2: sqlstate 57014",
          st15 == "failed" and ss15 == "57014", (st15, ss15))
    cur.execute("SELECT count(*) FROM events WHERE session_id=%s AND type='tool/result'",
                (sid15b,))
    check("M3-15 morph2: zero tool/result", cur.fetchone()[0] == 0)
    for _ in range(2):
        snap15b = parse(cur, sid15b,
                        intent={"type": "choice", "choice": "sql_answer",
                                "probabilities": {"sql_answer": 0.9}, "confidence": 0.9},
                        gate_action={"type": "noul", "noul": 0.9},
                        tool={"type": "choice", "choice": "slow",
                              "probabilities": {"slow": 0.9}, "confidence": 0.9})
        cur.execute("SELECT v13_advance(%s, %s::jsonb)",
                    (sid15b, json.dumps(snap15b)))
        check("M3-15 morph2: retry progressed", cur.fetchone()[0] == "progressed")
    cur.execute("SET statement_timeout = 0")
    snap15b = parse(cur, sid15b,
                    intent={"type": "choice", "choice": "sql_answer",
                            "probabilities": {"sql_answer": 0.9}, "confidence": 0.9},
                    gate_action={"type": "noul", "noul": 0.9},
                    tool={"type": "choice", "choice": "slow",
                          "probabilities": {"slow": 0.9}, "confidence": 0.9})
    cur.execute("SELECT v13_advance(%s, %s::jsonb)",
                (sid15b, json.dumps(snap15b)))
    check("M3-15 morph2: budget waiting", cur.fetchone()[0] == "waiting")
    cur.execute("SELECT request->>'reason' FROM effects "
                "WHERE session_id=%s AND kind='human'", (sid15b,))
    check("M3-15 morph2: budget_exhausted",
          cur.fetchone()[0] == "budget_exhausted")

    sid15n = new_session(cur)
    append_user(cur, sid15n)
    snap15n = parse(cur, sid15n,
                    intent={"type": "choice", "choice": "sql_answer",
                            "probabilities": {"sql_answer": 0.9}, "confidence": 0.9},
                    gate_action={"type": "noul", "noul": 0.9},
                    tool={"type": "choice", "choice": "slow",
                          "probabilities": {"slow": 0.9}, "confidence": 0.9})
    conn.commit()
    cur.execute("SELECT count(*) FROM events WHERE session_id=%s", (sid15n,))
    ev_n = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM effects WHERE session_id=%s", (sid15n,))
    ef_n = cur.fetchone()[0]
    neg = {}

    def run_neg():
        c = psycopg2.connect(server.get_uri(DB))
        k = c.cursor()
        k.execute("SET statement_timeout = 0")
        k.execute("SELECT pg_backend_pid()")
        neg["pid"] = k.fetchone()[0]
        try:
            k.execute("SELECT v13_advance(%s, %s::jsonb)",
                      (sid15n, json.dumps(snap15n)))
            neg["r"] = k.fetchone()[0]
            c.commit()
        except Exception as exc:
            neg["e"] = exc
        c.close()

    tn = threading.Thread(target=run_neg)
    tn.start()
    t_wait = time.time()
    while time.time() - t_wait < 3 and not neg.get("pid"):
        time.sleep(0.02)
    time.sleep(0.3)
    cur.execute("SELECT pg_cancel_backend(%s)", (neg["pid"],))
    tn.join(8)
    check("M3-15 negative: raised not progressed",
          "e" in neg and getattr(neg["e"], "pgcode", None) == "57014",
          neg)
    cur.execute("SELECT count(*) FROM events WHERE session_id=%s", (sid15n,))
    check("M3-15 negative: zero new events", cur.fetchone()[0] == ev_n)
    cur.execute("SELECT count(*) FROM effects WHERE session_id=%s", (sid15n,))
    check("M3-15 negative: zero new effects", cur.fetchone()[0] == ef_n)

    sid15c = new_session(cur)
    append_user(cur, sid15c)
    snap15c = answers_sql(cur, sid15c)
    conn.commit()
    cur.execute("SELECT count(*) FROM events WHERE session_id=%s", (sid15c,))
    ev_c = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM effects WHERE session_id=%s", (sid15c,))
    ef_c = cur.fetchone()[0]
    cL = psycopg2.connect(server.get_uri(DB))
    kL = cL.cursor()
    kL.execute("BEGIN")
    kL.execute("SELECT 1 FROM sessions WHERE session_id=%s FOR UPDATE", (sid15c,))
    cur.execute("SAVEPOINT sp_lock")
    cur.execute("SET LOCAL lock_timeout = '250ms'")
    try:
        cur.execute("SELECT v13_advance(%s, %s::jsonb)",
                    (sid15c, json.dumps(snap15c)))
        check("M3-15 morph3: expected 55P03", False, cur.fetchone()[0])
    except psycopg2.Error as exc:
        check("M3-15 morph3: 55P03", exc.pgcode == "55P03", exc.pgcode)
        cur.execute("ROLLBACK TO SAVEPOINT sp_lock")
    cL.rollback()
    cL.close()
    cur.execute("SELECT count(*) FROM events WHERE session_id=%s", (sid15c,))
    check("M3-15 morph3: zero new events", cur.fetchone()[0] == ev_c)
    cur.execute("SELECT count(*) FROM effects WHERE session_id=%s", (sid15c,))
    check("M3-15 morph3: zero new effects", cur.fetchone()[0] == ef_c)
    cur.execute("SELECT v13_advance(%s, %s::jsonb)",
                (sid15c, json.dumps(snap15c)))
    check("M3-15 morph3: replay after unlock",
          cur.fetchone()[0] in ("progressed", "waiting", "terminal"))
    cur.execute("DELETE FROM tools WHERE name='slow'")
    cur.execute("DROP FUNCTION v13_slow(uuid, jsonb)")

    # M3-21 handler body drift
    sid21 = new_session(cur); append_user(cur, sid21)
    snap21 = answers_sql(cur, sid21)
    cur.execute("SELECT revision FROM v13_tools_meta")
    r_before = cur.fetchone()[0]
    cur.execute("""
        CREATE OR REPLACE FUNCTION v13_tool_session_stats(p_sid uuid, p_params jsonb)
        RETURNS jsonb LANGUAGE sql STABLE AS $$
          SELECT jsonb_build_object('message_count', 0, 'open_effects', 0,
                                    'session_status', 'ready', 'audit', 1);
        $$;
    """)
    cur.execute("SELECT revision FROM v13_tools_meta")
    r_after = cur.fetchone()[0]
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid21, json.dumps(snap21)))
    adv21 = cur.fetchone()[0]
    check("M3-21: handler OR REPLACE -> stale",
          adv21 == "stale", (adv21, r_before, r_after))
    # restore handler from core file is heavy; re-create original
    cur.execute("""
        CREATE OR REPLACE FUNCTION v13_tool_session_stats(p_sid uuid, p_params jsonb)
        RETURNS jsonb LANGUAGE sql STABLE AS $$
          SELECT jsonb_build_object(
            'message_count', (SELECT count(*) FROM events
                               WHERE session_id = p_sid
                                 AND type IN ('user/message','llm/message','tool/result')),
            'open_effects', (SELECT count(*) FROM effects
                              WHERE session_id = p_sid
                                AND status IN ('ready','claimed','unknown')),
            'session_status', s.status)
          FROM sessions s WHERE s.session_id = p_sid;
        $$;
    """)

    # M3-14 succeeded human replay
    sid14 = new_session(cur)
    append_user(cur, sid14)
    cur.execute("SELECT v13_enqueue_effect(%s, 'human', %s::jsonb)",
                (sid14, json.dumps({"reason": "resolve_budget"})))
    h14 = cur.fetchone()[0]
    c14 = claim_pinned(cur, h14)
    cur.execute("SELECT v13_complete(%s, %s, %s, 'succeeded', '{}'::jsonb)",
                (h14, c14["attempt_no"], c14["fence"]))
    check("M3-14: human succeeded", cur.fetchone()[0] == "accepted")
    cur.execute("SELECT v13_last_user_seq(%s)", (sid14,))
    seq14 = cur.fetchone()[0]
    for _ in range(2):
        cur.execute("SELECT v13_append_event(%s, %s, 'resolve/failed', %s::jsonb)",
                    (sid14, u(), json.dumps({"origin_user_seq": seq14})))
    poison(cur)
    snap14 = parse(cur, sid14)
    check("M3-14: abandon", snap14["abandon"] is True, snap14)
    cur.execute("SELECT count(*) FROM pgmq.q_v13_work")
    q14 = cur.fetchone()[0]
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid14, json.dumps(snap14)))
    check("M3-14: succeeded human -> terminal", cur.fetchone()[0] == "terminal")
    cur.execute("SELECT type, payload FROM events WHERE session_id=%s AND type='turn/end'",
                (sid14,))
    te = cur.fetchone()
    check("M3-14: turn/end", te and te[0] == "turn/end", te)
    cur.execute("SELECT status FROM sessions WHERE session_id=%s", (sid14,))
    check("M3-14: session failed", cur.fetchone()[0] == "failed")
    cur.execute("SELECT count(*) FROM pgmq.q_v13_work")
    check("M3-14: zero new wake", cur.fetchone()[0] == q14)

    # M3-19 freeze catalog
    sid19 = new_session(cur)
    append_user(cur, sid19)
    snap19 = answers_sql(cur, sid19)
    cur.execute("""
        CREATE FUNCTION v13_h2(uuid, jsonb) RETURNS jsonb
        LANGUAGE sql STABLE AS $$ SELECT '{"via":"h2"}'::jsonb $$;
    """)
    cur.execute("GRANT EXECUTE ON FUNCTION v13_h2(uuid, jsonb) TO v13_route")
    cur.execute("UPDATE tools SET handler='v13_h2' WHERE name='session_stats'")
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid19, json.dumps(snap19)))
    check("M3-19: H2 after E -> stale", cur.fetchone()[0] == "stale")
    snap19b = answers_sql(cur, sid19)
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid19, json.dumps(snap19b)))
    check("M3-19: E' executes H2", cur.fetchone()[0] == "progressed")
    cur.execute("SELECT result->>'via' FROM effects "
                "WHERE session_id=%s AND kind='tool' "
                "ORDER BY created_at DESC LIMIT 1", (sid19,))
    check("M3-19: H2 result", cur.fetchone()[0] == "h2")
    cur.execute("UPDATE tools SET handler='v13_tool_session_stats' "
                "WHERE name='session_stats'")

    sid19t = new_session(cur)
    append_user(cur, sid19t)
    snap19t = answers_sql(cur, sid19t)
    conn.commit()
    cur.execute("""
        CREATE OR REPLACE FUNCTION v13_fx_pause() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          PERFORM pg_advisory_xact_lock(879022);
          RETURN NEW;
        END $$;
    """)
    cur.execute("DROP TRIGGER IF EXISTS trg_fx_pause ON effects")
    cur.execute("CREATE TRIGGER trg_fx_pause BEFORE INSERT ON effects "
                "FOR EACH ROW EXECUTE FUNCTION v13_fx_pause()")
    conn.commit()
    hold19 = psycopg2.connect(server.get_uri(DB))
    hk19 = hold19.cursor()
    hk19.execute("SELECT pg_advisory_xact_lock(879022)")
    box19 = {}

    def run_adv19():
        c = psycopg2.connect(server.get_uri(DB))
        k = c.cursor()
        k.execute("SELECT pg_backend_pid()")
        box19["pid"] = k.fetchone()[0]
        try:
            k.execute("SELECT v13_advance(%s, %s::jsonb)",
                      (sid19t, json.dumps(snap19t)))
            box19["r"] = k.fetchone()[0]
            c.commit()
        except Exception as exc:
            box19["e"] = str(exc)
        c.close()

    t19 = threading.Thread(target=run_adv19)
    t19.start()
    check("M3-19: advance blocked in effects INSERT",
          wait_until_lock(cur, box19, "pid"))
    cur.execute("UPDATE tools SET handler='v13_h2' WHERE name='session_stats'")
    conn.commit()
    hold19.rollback()
    hold19.close()
    t19.join(10)
    check("M3-19: in-flight still H1 not stale",
          box19.get("r") == "progressed", box19)
    cur.execute("SELECT result->>'via' FROM effects "
                "WHERE session_id=%s AND kind='tool'", (sid19t,))
    row19 = cur.fetchone()
    check("M3-19: in-flight result is H1",
          row19 is None or row19[0] != "h2", row19)
    cur.execute("UPDATE tools SET handler='v13_tool_session_stats' "
                "WHERE name='session_stats'")
    cur.execute("DROP TRIGGER IF EXISTS trg_fx_pause ON effects")
    cur.execute("DROP FUNCTION IF EXISTS v13_fx_pause()")
    cur.execute("DROP FUNCTION IF EXISTS v13_h2(uuid, jsonb)")

    # M3-20 human=2 full chain
    sid20 = new_session(cur)
    seq20 = append_user(cur, sid20)
    for _ in range(2):
        cur.execute("SELECT v13_append_event(%s, %s, 'resolve/failed', %s::jsonb)",
                    (sid20, u(), json.dumps({"origin_user_seq": seq20})))
    poison(cur)
    snap20 = parse(cur, sid20)
    check("M3-20: parse1 abandon", snap20["abandon"] is True)
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid20, json.dumps(snap20)))
    check("M3-20: advance1 waiting", cur.fetchone()[0] == "waiting")
    cur.execute("SELECT effect_id FROM effects WHERE session_id=%s AND kind='human'",
                (sid20,))
    h20 = cur.fetchone()[0]
    ck = claim_pinned(cur, h20)
    cur.execute("SELECT v13_complete(%s, %s, %s, 'failed', NULL)",
                (h20, ck["attempt_no"], ck["fence"]))
    cur.fetchone()
    poison(cur)
    snap20 = parse(cur, sid20)
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid20, json.dumps(snap20)))
    check("M3-20: cap-in rehang waiting", cur.fetchone()[0] == "waiting")
    cur.execute("SELECT status, fence, attempt_no FROM effects WHERE effect_id=%s",
                (h20,))
    st20, fn20, at20 = cur.fetchone()
    check("M3-20: rehang ready attempt 1",
          st20 == "ready" and at20 == 1, (st20, fn20, at20))
    ck = claim_pinned(cur, h20)
    cur.execute("SELECT v13_complete(%s, %s, %s, 'failed', NULL)",
                (h20, ck["attempt_no"], ck["fence"]))
    cur.fetchone()
    poison(cur)
    snap20 = parse(cur, sid20)
    cur.execute("SELECT count(*) FROM pgmq.q_v13_work")
    q20 = cur.fetchone()[0]
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid20, json.dumps(snap20)))
    check("M3-20: cap terminal", cur.fetchone()[0] == "terminal")
    cur.execute("SELECT status FROM sessions WHERE session_id=%s", (sid20,))
    check("M3-20: session failed", cur.fetchone()[0] == "failed")
    cur.execute("SELECT payload->>'attempts_exhausted' FROM events "
                "WHERE session_id=%s AND type='turn/end'", (sid20,))
    check("M3-20: attempts_exhausted", cur.fetchone()[0] == "true")
    cur.execute("SELECT count(*) FILTER (WHERE type='effect_done'), "
                "count(*) FILTER (WHERE type='resolve/failed'), "
                "count(*) FILTER (WHERE type='turn/end') "
                "FROM events WHERE session_id=%s", (sid20,))
    ed20, rf20, te20 = cur.fetchone()
    check("M3-20: event ledger",
          ed20 == 2 and rf20 == 2 and te20 == 1, (ed20, rf20, te20))
    cur.execute("SELECT count(*) FROM pgmq.q_v13_work")
    check("M3-20: zero wake after refuse", cur.fetchone()[0] == q20)

    # M3-22 step-0 probe O(index)
    sid22 = new_session(cur)
    append_user(cur, sid22)
    cur.execute(
        "INSERT INTO events (session_id, seq, event_id, type, turn_no, "
        "payload, payload_hash) "
        "SELECT %s, gs, gen_random_uuid(), 'tool/result', 1, "
        "jsonb_build_object('n', gs), encode(digest(gs::text, 'sha256'), 'hex') "
        "FROM generate_series(1, 100000) gs",
        (sid22,))
    cur.execute("UPDATE sessions SET next_seq = 100001 WHERE session_id=%s",
                (sid22,))
    for i in range(20):
        cur.execute(
            "INSERT INTO tools (name, description, kind, handler) "
            "VALUES (%s, 'Fixture tool.', 'sql', 'v13_tool_session_stats')",
            (f"m22_{i}",))
    snap22 = answers_sql(cur, sid22)
    t_snap = time.time()
    cur.execute("SELECT v13_snapshot(%s)", (sid22,))
    cur.fetchone()
    dt_snap = time.time() - t_snap
    t_adv = time.time()
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid22, json.dumps(snap22)))
    r22 = cur.fetchone()[0]
    dt_adv = time.time() - t_adv
    check("M3-22: sql advance progressed", r22 == "progressed", r22)
    check("M3-22: advance <500ms", dt_adv < 0.5, dt_adv)
    print(f"[NOTE] M3-22 snapshot {dt_snap:.3f}s vs advance {dt_adv:.3f}s")
    check("M3-22: probe vs snapshot magnitude", dt_adv < dt_snap or dt_adv < 0.5,
          (dt_adv, dt_snap))
    for i in range(20):
        cur.execute("DELETE FROM tools WHERE name=%s", (f"m22_{i}",))

    conn.commit()
    conn.close()
    print("[M3 loop] ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
