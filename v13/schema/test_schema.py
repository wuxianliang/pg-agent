"""M1 gate: v13 core schema stage — three planes, ACL matrix, catalog revisions.

Implements all 14 assertions of DP1 §4 「M1 v13/schema」 gate table
(docs/plans/v13-dp1-two-phase-advance-plan-2026-09-20.md), with the later
amendments applied (R2 #50/A17: unnamed VOLATILE sql handler still rejected).

Run: uv run python v13/schema/test_schema.py  (exit 0 = pass)
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

from server import PGDATA, get_server
from v13.schema.setup_db import DB, main as setup_db

CORE_SQL = ROOT / "v13_core.sql"
SEVEN_TABLES = ["sessions", "events", "decisions", "thresholds", "tools",
                "v13_policies", "v13_tools_meta"]


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f": {detail}" if detail else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def u() -> str:
    return str(uuid.uuid4())


def fails_with(cur, sql: str, params: tuple, needle: str, label: str) -> None:
    """Autocommit-mode negative probe: a failed statement leaves no open tx."""
    try:
        cur.execute(sql, params)
    except psycopg2.Error as exc:
        msg = str(exc).lower()
        check(label, needle.lower() in msg, exc)
        return
    raise AssertionError(f"{label}: expected failure containing {needle!r}, got success")


def role_conn(role: str):
    c = psycopg2.connect(dbname=DB, user=role, host=str(PGDATA))
    c.autocommit = True
    return c


def strip_sql_comments(text: str) -> str:
    """Drop `-- ...` comments so source scans measure executable SQL only.

    A `--` inside a single-quoted literal is kept (odd quote count before it).
    """
    out = []
    for line in text.splitlines():
        idx = 0
        while True:
            idx = line.find("--", idx)
            if idx < 0:
                out.append(line)
                break
            if line.count("'", 0, idx) % 2 == 0:
                out.append(line[:idx])
                break
            idx += 2
    return "\n".join(out)


def one(cur, sql: str, params: tuple = ()):
    cur.execute(sql, params)
    row = cur.fetchone()
    return row[0] if row else None


def new_session(cur, with_user_message: bool = True) -> str:
    sid = u()
    cur.execute("INSERT INTO sessions (session_id) VALUES (%s)", (sid,))
    if with_user_message:
        cur.execute("SELECT v13_append_event(%s, gen_random_uuid(), 'user/message', %s)",
                    (sid, json.dumps({"text": "hello"})))
    return sid


def mk_decision(cur, sid: str, signal: str, kind: str, question: str,
                criteria, rhash: str, status: str = "open") -> str:
    return one(cur,
               "INSERT INTO decisions (session_id, signal, kind, question, criteria,"
               " context, request_hash, status) VALUES (%s,%s,%s,%s,%s,'{}'::jsonb,%s,%s)"
               " RETURNING decision_id",
               (sid, signal, kind, question,
                None if criteria is None else json.dumps(criteria), rhash, status))


def effect_row(cur, eid: str) -> dict:
    cur.execute("SELECT status, attempt_no, fence, idempotency_key, error,"
                " origin_user_seq FROM effects WHERE effect_id = %s", (eid,))
    r = cur.fetchone()
    return dict(zip(("status", "attempt_no", "fence", "idempotency_key",
                     "error", "origin_user_seq"), r))


def claim_expect(cur, eid: str, lease_ms: int = 60000) -> tuple:
    tok = one(cur, "SELECT v13_claim(%s, %s)", ("w1", lease_ms))
    assert tok is not None and tok["effect_id"] == eid, (tok, eid)
    return tok["attempt_no"], tok["fence"]


def events_of(cur, sid: str) -> list:
    cur.execute("SELECT type, payload, source_effect_id FROM events"
                " WHERE session_id = %s ORDER BY seq", (sid,))
    return cur.fetchall()


def revs(cur) -> tuple:
    cur.execute("SELECT revision, candidate_generation_revision FROM v13_tools_meta")
    return cur.fetchone()


# ---------------------------------------------------------------- assertions
def a1_append_only(cur) -> None:
    sid = new_session(cur)
    fails_with(cur, "UPDATE events SET payload = '{}' WHERE session_id = %s", (sid,),
               "append-only", "M1-1 journal: UPDATE events rejected")
    fails_with(cur, "DELETE FROM events WHERE session_id = %s", (sid,),
               "append-only", "M1-1 journal: DELETE events rejected")
    fails_with(cur, "SELECT v13_append_event(%s, gen_random_uuid(), 'x', '{}')", (u(),),
               "unknown session", "M1-1 journal: append to unknown session rejected")


def a2_concurrent_no_holes(server, cur) -> None:
    sid = new_session(cur, with_user_message=False)
    errs: list = []

    def worker(n: int) -> None:
        try:
            c = psycopg2.connect(server.get_uri(DB))
            c.autocommit = True
            k = c.cursor()
            for i in range(n):
                k.execute("SELECT v13_append_event(%s, gen_random_uuid(),"
                          " 'user/message', %s)", (sid, json.dumps({"i": i})))
            c.close()
        except Exception as exc:          # pragma: no cover - surfaced below
            errs.append(exc)

    ts = [threading.Thread(target=worker, args=(25,)) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    check("M1-2 journal: concurrent append has no errors", not errs, errs)
    cur.execute("SELECT max(seq), count(*), max(turn_no) FROM events"
                " WHERE session_id = %s", (sid,))
    mx, cnt, turn = cur.fetchone()
    check("M1-2 journal: max(seq) = count(*)-1 (no holes)", mx == cnt - 1, (mx, cnt))
    check("M1-2 journal: 50 events, turn_no tracks user/message count",
          cnt == 50 and turn == 50, (cnt, turn))
    check("M1-2 journal: next_seq = count(*)",
          one(cur, "SELECT next_seq FROM sessions WHERE session_id=%s", (sid,)) == cnt)


def a3_event_id_and_provenance(cur) -> None:
    sid = new_session(cur, with_user_message=False)
    eid = u()
    cur.execute("SELECT v13_append_event(%s, %s, 'user/message', '{}')", (sid, eid))
    fails_with(cur, "SELECT v13_append_event(%s, %s, 'system/note', '{}')", (sid, eid),
               "duplicate key", "M1-3 journal: duplicate event_id rejected (UNIQUE)")
    src = u()
    cur.execute("SELECT v13_append_event(%s, gen_random_uuid(), 'tool/result',"
                " '{}', %s)", (sid, src))
    got = one(cur, "SELECT source_effect_id FROM events WHERE session_id=%s"
                   " AND type='tool/result'", (sid,))
    check("M1-3 journal: p_source_effect lands in source_effect_id (P2 provenance)",
          str(got) == src, got)
    check("M1-3 journal: payload_hash computed on append",
          one(cur, "SELECT payload_hash FROM events WHERE session_id=%s AND seq=0",
              (sid,)) == one(cur, "SELECT encode(digest('{}','sha256'),'hex')"))


def a4_decisions(cur) -> None:
    sid = new_session(cur)
    sid2 = new_session(cur)
    mk_decision(cur, sid, "intent", "choice", "Pick one.", {"a": "option a"}, "h_ok")
    check("M1-4 decisions: valid choice row accepted", True)
    mk_decision(cur, sid, "risk", "score", "Rate it.", ["low", "mid", "high"], "h_score")
    mk_decision(cur, sid, "gate_off_topic", "noul", "Is it off topic?", None, "h_noul")
    check("M1-4 decisions: noul with SQL NULL criteria accepted",
          one(cur, "SELECT criteria IS NULL FROM decisions WHERE session_id=%s"
                   " AND signal='gate_off_topic'", (sid,)) is True)

    fails_with(cur, "INSERT INTO decisions (session_id, signal, kind, question,"
                    " context, request_hash) VALUES (%s,'x','noul','真的吗?',"
                    " '{}'::jsonb,'h_cjk')", (sid,),
               "decisions_question_check", "M1-4 decisions: non-ASCII question rejected")
    fails_with(cur, "INSERT INTO decisions (session_id, signal, kind, question,"
                    " criteria, context, request_hash) VALUES (%s,'x','choice','Pick.',"
                    " %s,'{}'::jsonb,'h_c1')", (sid, json.dumps(["a", "b"])),
               "v13_decisions_choice_shape",
               "M1-4 decisions: choice with array criteria rejected")
    fails_with(cur, "INSERT INTO decisions (session_id, signal, kind, question,"
                    " criteria, context, request_hash) VALUES (%s,'x','choice','Pick.',"
                    " '{}'::jsonb,'{}'::jsonb,'h_c2')", (sid,),
               "v13_decisions_choice_shape",
               "M1-4 decisions: choice with empty object criteria rejected")
    fails_with(cur, "INSERT INTO decisions (session_id, signal, kind, question,"
                    " criteria, context, request_hash) VALUES (%s,'x','score','Rate.',"
                    " %s,'{}'::jsonb,'h_s1')", (sid, json.dumps(["only"])),
               "v13_decisions_score_shape",
               "M1-4 decisions: score with one level rejected")
    fails_with(cur, "INSERT INTO decisions (session_id, signal, kind, question,"
                    " criteria, context, request_hash) VALUES (%s,'x','noul','Ok?',"
                    " 'null'::jsonb,'{}'::jsonb,'h_n1')", (sid,),
               "v13_decisions_noul_shape",
               "M1-4 decisions: noul with jsonb 'null' literal rejected (#11)")
    fails_with(cur, "INSERT INTO decisions (session_id, signal, kind, question,"
                    " criteria, context, request_hash) VALUES (%s,'x','choice','Pick.',"
                    " %s,'{}'::jsonb,'h_a1')", (sid, json.dumps({"a": "描述"})),
               "v13_decisions_criteria_ascii",
               "M1-4 decisions: non-ASCII criteria rejected")

    did = mk_decision(cur, sid, "tool", "choice", "Which tool?", {"t": "one"}, "h_ans")
    cur.execute("UPDATE decisions SET answer = %s WHERE decision_id = %s",
                (json.dumps({"confidence": 0.9, "choice": "t"}), did))
    cur.execute("SELECT status, answered_at IS NOT NULL FROM decisions"
                " WHERE decision_id = %s", (did,))
    st, ans_at = cur.fetchone()
    check("M1-4 decisions: answer NULL->non-NULL derives status/answered_at",
          st == "answered" and ans_at, (st, ans_at))
    fails_with(cur, "UPDATE decisions SET answer = %s WHERE decision_id = %s",
               (json.dumps({"confidence": 0.1, "choice": "t"}), did),
               "immutable", "M1-4 decisions: second answer rewrite rejected (answer-once)")
    cur.execute("UPDATE decisions SET answer = %s WHERE decision_id = %s",
                (json.dumps({"confidence": 0.9, "choice": "t"}), did))
    check("M1-4 decisions: idempotent same-answer UPDATE tolerated", True)

    fails_with(cur, "INSERT INTO decisions (session_id, signal, kind, question,"
                    " context, request_hash) VALUES (%s,'dup','noul','Dup?',"
                    " '{}'::jsonb,'h_ok')", (sid,),
               "duplicate key",
               "M1-4 decisions: UNIQUE(session_id, request_hash) rejects second insert")
    mk_decision(cur, sid2, "intent", "choice", "Pick one.", {"a": "option a"}, "h_ok")
    cur.execute("SELECT count(*) FROM decisions WHERE request_hash='h_ok'"
                " GROUP BY session_id")
    counts = [r[0] for r in cur.fetchall()]
    check("M1-4 decisions: same hash across sessions lands one row each (P0-4)",
          counts == [1, 1], counts)


def a5_effects(cur) -> None:
    sid = new_session(cur)
    # (a) kind='tool' without tool_name -> CHECK
    fails_with(cur, "INSERT INTO effects (effect_id, session_id, kind, request,"
                    " request_hash, origin_user_seq) VALUES"
                    " (gen_random_uuid(), %s, 'tool', '{}'::jsonb, 'h', 0)", (sid,),
               "v13_effects_tool_named",
               "M1-5 effects: kind='tool' with NULL tool_name rejected (P2)")
    # (b) single active unique index
    e1 = u()
    cur.execute("INSERT INTO effects (effect_id, session_id, kind, request,"
                " request_hash, origin_user_seq) VALUES (%s,%s,'judge','{}'::jsonb,"
                " 'h1', 0)", (e1, sid))
    fails_with(cur, "INSERT INTO effects (effect_id, session_id, kind, request,"
                    " request_hash, origin_user_seq) VALUES (gen_random_uuid(),%s,"
                    " 'judge','{}'::jsonb,'h2',0)", (sid,),
               "ux_v13_effects_single_active",
               "M1-5 effects: second ready effect in a session rejected")
    cur.execute("DELETE FROM effects WHERE effect_id = %s", (e1,))

    # (c) enqueue idempotency: succeeded replay returns the same id
    s1 = new_session(cur)
    req = json.dumps({"q": 1})
    id1 = one(cur, "SELECT v13_enqueue_effect(%s,'judge',%s)", (s1, req))
    row = effect_row(cur, id1)
    check("M1-5 effects: new row carries stable idempotency_key (#13)",
          row["idempotency_key"] == "v13:" + str(id1), row)
    a, f = claim_expect(cur, id1)
    check("M1-5 effects: complete succeeded",
          one(cur, "SELECT v13_complete(%s,%s,%s,'succeeded','{}'::jsonb)",
              (id1, a, f)) == "accepted")
    check("M1-5 effects: succeeded replay returns the same id (idempotent enqueue)",
          str(one(cur, "SELECT v13_enqueue_effect(%s,'judge',%s)", (s1, req))) == str(id1))

    # (f) same turn, same kind, different request -> distinct ids coexist
    req2 = json.dumps({"q": 2})
    id2 = one(cur, "SELECT v13_enqueue_effect(%s,'judge',%s)", (s1, req2))
    check("M1-5 effects: different request in same turn yields a new id (P0-3)",
          str(id2) != str(id1))
    check("M1-5 effects: both rows coexist",
          one(cur, "SELECT count(*) FROM effects WHERE session_id=%s", (s1,)) == 2)
    a, f = claim_expect(cur, id2)
    cur.execute("SELECT v13_complete(%s,%s,%s,'succeeded','{}'::jsonb)", (id2, a, f))

    # (d) failed re-enqueue: same id, fence+1, old tokens go stale
    s2 = new_session(cur)
    reqf = json.dumps({"q": "f"})
    idf = one(cur, "SELECT v13_enqueue_effect(%s,'judge',%s)", (s2, reqf))
    a, f = claim_expect(cur, idf)
    cur.execute("SELECT v13_complete(%s,%s,%s,'failed')", (idf, a, f))
    before_key = effect_row(cur, idf)["idempotency_key"]
    idf2 = one(cur, "SELECT v13_enqueue_effect(%s,'judge',%s)", (s2, reqf))
    after = effect_row(cur, idf)
    check("M1-5 effects: failed re-enqueue keeps the id and bumps fence (P0-5)",
          str(idf2) == str(idf) and after["status"] == "ready" and after["fence"] == f + 1,
          after)
    check("M1-5 effects: re-enqueue does not rotate idempotency_key (#13)",
          after["idempotency_key"] == before_key)
    snap = effect_row(cur, idf)
    check("M1-5 effects: pre-requeue (attempt,fence) completes as 'stale'",
          one(cur, "SELECT v13_complete(%s,%s,%s,'succeeded','{}'::jsonb)",
              (idf, a, f)) == "stale")
    check("M1-5 effects: stale completion changes nothing",
          effect_row(cur, idf) == snap)
    a, f = claim_expect(cur, idf)
    cur.execute("SELECT v13_complete(%s,%s,%s,'succeeded','{}'::jsonb)", (idf, a, f))

    # (e) unknown is a wall
    s3 = new_session(cur)
    requ = json.dumps({"q": "u"})
    idu = one(cur, "SELECT v13_enqueue_effect(%s,'tool',%s,'session_stats')",
              (s3, requ))
    a, f = claim_expect(cur, idu)
    cur.execute("SELECT v13_complete(%s,%s,%s,'unknown')", (idu, a, f))
    fails_with(cur, "SELECT v13_enqueue_effect(%s,'tool',%s,'session_stats')",
               (s3, requ), "is unknown",
               "M1-5 effects: unknown effect refuses re-entry (ch12 wall)")

    # (h) attempt cap refuses re-enqueue (human=2 seed)
    s4 = new_session(cur)
    reqh = json.dumps({"escalate": True})
    idh = one(cur, "SELECT v13_enqueue_effect(%s,'human',%s)", (s4, reqh))
    for _ in range(2):
        a, f = claim_expect(cur, idh)
        cur.execute("SELECT v13_complete(%s,%s,%s,'failed')", (idh, a, f))
        if effect_row(cur, idh)["attempt_no"] < 2:
            cur.execute("SELECT v13_enqueue_effect(%s,'human',%s)", (s4, reqh))
    capped = effect_row(cur, idh)
    n_ev = len(events_of(cur, s4))
    idh2 = one(cur, "SELECT v13_enqueue_effect(%s,'human',%s)", (s4, reqh))
    after = effect_row(cur, idh)
    check("M1-5 effects: attempt cap refuses re-enqueue, row stays terminal (#49)",
          str(idh2) == str(idh) and after == capped and after["status"] == "failed"
          and after["attempt_no"] == 2, after)
    check("M1-5 effects: capped re-enqueue emits zero events",
          len(events_of(cur, s4)) == n_ev)

    # (i) missing cap key is fail-loud at enqueue (turn 9 #61 / turn 10 #64 order)
    s5 = new_session(cur)
    cap_v2 = json.dumps({"judge": 4, "tool": 3, "llm": 3, "context_refresh": 3})
    try:
        cur.execute("INSERT INTO v13_policies (name, version, value, active)"
                    " VALUES ('effect_attempt_cap', 2, %s, false)", (cap_v2,))
        cur.execute("UPDATE v13_policies SET active=false"
                    " WHERE name='effect_attempt_cap' AND version=1")
        cur.execute("UPDATE v13_policies SET active=true"
                    " WHERE name='effect_attempt_cap' AND version=2")
        fails_with(cur, "SELECT v13_enqueue_effect(%s,'human','{}'::jsonb)", (s5,),
                   "effect_attempt_cap policy missing kind",
                   "M1-5 effects: missing cap key is fail-loud at enqueue (#61)")
        check("M1-5 effects: fail-loud enqueue lands zero rows",
              one(cur, "SELECT count(*) FROM effects WHERE session_id=%s", (s5,)) == 0)
    finally:
        cur.execute("UPDATE v13_policies SET active=false"
                    " WHERE name='effect_attempt_cap' AND version=2")
        cur.execute("UPDATE v13_policies SET active=true"
                    " WHERE name='effect_attempt_cap' AND version=1")
    check("M1-5 effects: cap policy restored to v1",
          one(cur, "SELECT value FROM v13_policies WHERE name='effect_attempt_cap'"
                   " AND active")["human"] == 2)


def a6_claim_complete(cur) -> None:
    # CAS hardening negatives
    s = new_session(cur)
    eid = one(cur, "SELECT v13_enqueue_effect(%s,'judge',%s)",
              (s, json.dumps({"k": "cas"})))
    snap = effect_row(cur, eid)
    check("M1-6 complete: ready row with native (0,0) is 'stale' (claimed precondition)",
          one(cur, "SELECT v13_complete(%s,0,0,'succeeded','{}'::jsonb)", (eid,)) == "stale")
    check("M1-6 complete: rejected settlement changes nothing",
          effect_row(cur, eid) == snap and len(events_of(cur, s)) == 1)
    fails_with(cur, "SELECT v13_complete(%s, NULL::int, 0::bigint, 'succeeded')", (eid,),
               "non-null", "M1-6 complete: NULL attempt token raises")
    fails_with(cur, "SELECT v13_complete(%s, 0::int, NULL::bigint, 'succeeded')", (eid,),
               "non-null", "M1-6 complete: NULL fence token raises")
    fails_with(cur, "SELECT v13_complete(gen_random_uuid(), 1, 1, 'succeeded')", (),
               "unknown effect", "M1-6 complete: unknown effect_id raises")
    fails_with(cur, "SELECT v13_complete(%s, 1, 1, 'weird')", (eid,),
               "bad outcome", "M1-6 complete: unknown outcome raises")
    a, f = claim_expect(cur, eid)
    check("M1-6 claim: claim bumps attempt_no and fence",
          (a, f) == (snap["attempt_no"] + 1, snap["fence"] + 1), (a, f))
    check("M1-6 complete: stale fence settles as 'stale'",
          one(cur, "SELECT v13_complete(%s,%s,%s,'succeeded','{}'::jsonb)",
              (eid, a, f - 1)) == "stale")
    cur.execute("SELECT v13_complete(%s,%s,%s,'succeeded','{}'::jsonb)", (eid, a, f))
    n_ev = len(events_of(cur, s))
    check("M1-6 complete: repeat succeeded settlement is 'replay'",
          one(cur, "SELECT v13_complete(%s,%s,%s,'succeeded','{}'::jsonb)",
              (eid, a, f)) == "replay")
    check("M1-6 complete: replay adds zero events", len(events_of(cur, s)) == n_ev)

    # terminal re-entry guard over all four terminal states
    for state in ("failed", "unknown", "cancelled"):
        st = new_session(cur)
        e = one(cur, "SELECT v13_enqueue_effect(%s,'llm',%s)",
                (st, json.dumps({"t": state})))
        a, f = claim_expect(cur, e)
        cur.execute("UPDATE effects SET status=%s WHERE effect_id=%s", (state, e))
        check(f"M1-6 complete: terminal '{state}' re-entry guard returns 'replay'",
              one(cur, "SELECT v13_complete(%s,%s,%s,'succeeded','{}'::jsonb)",
                  (e, a, f)) == "replay")

    # semantic halves: tool success
    st = new_session(cur)
    e = one(cur, "SELECT v13_enqueue_effect(%s,'tool',%s,'session_stats')",
            (st, json.dumps({"tool": "session_stats"})))
    a, f = claim_expect(cur, e)
    cur.execute("SELECT v13_complete(%s,%s,%s,'succeeded',%s)",
                (e, a, f, json.dumps({"ok": True})))
    evs = [r for r in events_of(cur, st) if r[0] in ("effect_done", "tool/result")]
    kinds = [r[0] for r in evs]
    tr = [r for r in evs if r[0] == "tool/result"][0]
    check("M1-6 complete: tool success lands effect_done + tool/result (#1/#20)",
          kinds == ["effect_done", "tool/result"], kinds)
    check("M1-6 complete: tool/result carries source_effect_id and origin anchor",
          str(tr[2]) == str(e) and tr[1]["origin_user_seq"] == 0
          and tr[1]["tool"] == "session_stats", tr)

    # semantic halves: llm success + shape downgrade over five shapes
    st = new_session(cur)
    e = one(cur, "SELECT v13_enqueue_effect(%s,'llm',%s)",
            (st, json.dumps({"n": "good"})))
    a, f = claim_expect(cur, e)
    cur.execute("SELECT v13_complete(%s,%s,%s,'succeeded',%s)",
                (e, a, f, json.dumps({"text": "an answer"})))
    evs = [r for r in events_of(cur, st) if r[0] in ("effect_done", "llm/message")]
    lm = [r for r in evs if r[0] == "llm/message"][0]
    check("M1-6 complete: llm success lands effect_done + llm/message",
          [r[0] for r in evs] == ["effect_done", "llm/message"], evs)
    check("M1-6 complete: llm/message carries source_effect_id and origin anchor",
          str(lm[2]) == str(e) and lm[1]["origin_user_seq"] == 0
          and lm[1]["text"] == "an answer", lm)

    shapes = [("null result", None), ("empty object", {}), ("missing text", {"a": 1}),
              ("non-string text", {"text": 1}), ("blank text", {"text": "   "})]
    for idx, (name, payload) in enumerate(shapes):
        st = new_session(cur)
        e = one(cur, "SELECT v13_enqueue_effect(%s,'llm',%s)",
                (st, json.dumps({"shape": idx})))
        a, f = claim_expect(cur, e)
        cur.execute("SELECT v13_complete(%s,%s,%s,'succeeded',%s)",
                    (e, a, f, None if payload is None else json.dumps(payload)))
        row = effect_row(cur, e)
        types = [r[0] for r in events_of(cur, st)]
        check(f"M1-6 complete: llm shape '{name}' downgrades to failed (#26)",
              row["status"] == "failed"
              and row["error"] == {"code": "llm_result_shape"}
              and "llm/message" not in types, (row, types))

    # judge failure audit half
    st = new_session(cur)
    e = one(cur, "SELECT v13_enqueue_effect(%s,'judge',%s)",
            (st, json.dumps({"j": 1})))
    a, f = claim_expect(cur, e)
    cur.execute("SELECT v13_complete(%s,%s,%s,'failed')", (e, a, f))
    evs = [r for r in events_of(cur, st) if r[0] in ("effect_done", "resolve/failed")]
    rf = [r for r in evs if r[0] == "resolve/failed"][0]
    check("M1-6 complete: judge failure lands effect_done + resolve/failed (#15)",
          [r[0] for r in evs] == ["effect_done", "resolve/failed"], evs)
    check("M1-6 complete: resolve/failed records worker path + origin anchor",
          rf[1]["path"] == "worker" and rf[1]["origin_user_seq"] == 0, rf)
    n_ev = len(events_of(cur, st))
    check("M1-6 complete: repeat failed settlement is 'replay'",
          one(cur, "SELECT v13_complete(%s,%s,%s,'failed')", (e, a, f)) == "replay")
    check("M1-6 complete: repeat failed settlement adds no second resolve/failed",
          len(events_of(cur, st)) == n_ev)


def a7_roles(cur) -> None:
    sid = new_session(cur)
    # ---- v13_recall
    cur.execute("SET ROLE v13_recall")
    for t in SEVEN_TABLES:
        cur.execute(f"SELECT count(*) FROM {t}")
    check("M1-7 acl: v13_recall reads the seven envelope tables", True)
    fails_with(cur, "INSERT INTO decisions (session_id, signal, kind, question,"
                    " context, request_hash) VALUES (%s,'x','noul','Q?','{}'::jsonb,'h')",
               (sid,), "permission denied", "M1-7 acl: v13_recall cannot INSERT decisions")
    fails_with(cur, "UPDATE sessions SET status='waiting' WHERE session_id=%s", (sid,),
               "permission denied", "M1-7 acl: v13_recall cannot UPDATE sessions")
    fails_with(cur, "SELECT v13_append_event(%s, gen_random_uuid(), 'x', '{}')", (sid,),
               "permission denied", "M1-7 acl: v13_recall cannot EXECUTE v13_append_event")
    fails_with(cur, "SELECT count(*) FROM v_routes", (),
               "permission denied", "M1-7 acl: v13_recall cannot SELECT v_routes (#6)")
    cur.execute("RESET ROLE")

    # ---- v13_resolve
    did = mk_decision(cur, sid, "acl", "noul", "Acl probe?", None, "h_acl")
    cur.execute("SET ROLE v13_resolve")
    fails_with(cur, "INSERT INTO effects (effect_id, session_id, kind, request,"
                    " request_hash, origin_user_seq) VALUES (gen_random_uuid(),%s,"
                    " 'judge','{}'::jsonb,'h',0)", (sid,),
               "permission denied", "M1-7 acl: v13_resolve cannot INSERT effects")
    fails_with(cur, "SELECT v13_enqueue_effect(%s,'judge','{}'::jsonb)", (sid,),
               "permission denied",
               "M1-7 acl: v13_resolve cannot EXECUTE v13_enqueue_effect")
    fails_with(cur, "SELECT count(*) FROM v13_remote_sqlstates", (),
               "permission denied",
               "M1-7 acl: v13_resolve cannot SELECT v13_remote_sqlstates (#40)")
    fails_with(cur, "SELECT count(*) FROM v13_route_policies", (),
               "permission denied",
               "M1-7 acl: v13_resolve cannot SELECT v13_route_policies")
    for col in ("question", "context", "provider"):
        val = "'Other?'" if col == "question" else ("'{}'::jsonb" if col == "context"
                                                    else "'p'")
        fails_with(cur, f"UPDATE decisions SET {col} = {val} WHERE decision_id = %s",
                   (did,), "permission denied",
                   f"M1-7 acl: v13_resolve cannot UPDATE decisions.{col} (#17/#28)")
    cur.execute("RESET ROLE")

    # ---- v13_route
    s_route = new_session(cur)
    cur.execute("SET ROLE v13_route")
    rid = one(cur, "SELECT v13_enqueue_effect(%s,'judge','{\"acl\":1}'::jsonb)",
              (s_route,))
    check("M1-7 acl: v13_route can EXECUTE v13_enqueue_effect", rid is not None)
    cur.execute("SELECT count(*) FROM v_routes")
    check("M1-7 acl: v13_route can SELECT v_routes (#6)", True)
    cur.execute("SELECT count(*) FROM v13_route_policies")
    check("M1-7 acl: v13_route can SELECT v13_route_policies (#35)", True)
    fails_with(cur, "SELECT count(*) FROM v13_remote_sqlstates", (),
               "permission denied",
               "M1-7 acl: v13_route cannot SELECT v13_remote_sqlstates")
    cur.execute("RESET ROLE")
    cur.execute("DELETE FROM effects WHERE session_id=%s", (s_route,))

    check("M1-7 acl: v13_tool_session_stats keeps PUBLIC EXECUTE (intentional, #6)",
          one(cur, "SELECT has_function_privilege('public',"
                   " 'v13_tool_session_stats(uuid,jsonb)','EXECUTE')") is True)

    # ---- production login roles (turn 6 #41: dual login mandatory)
    cur.execute("SELECT rolname, rolcanlogin, rolinherit FROM pg_roles"
                " WHERE rolname IN ('v13_resolve_login','v13_route_login','v13_worker')"
                " ORDER BY rolname")
    attrs = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    check("M1-7 acl: both login roles can log in",
          attrs["v13_resolve_login"][0] and attrs["v13_route_login"][0], attrs)
    check("M1-7 acl: v13_worker is LOGIN NOINHERIT (recorded degraded fallback)",
          attrs["v13_worker"] == (True, False), attrs)
    for login, grp in (("v13_resolve_login", "v13_resolve"),
                       ("v13_route_login", "v13_route")):
        cur.execute("SELECT array_agg(roleid::regrole::text ORDER BY"
                    " roleid::regrole::text) FROM pg_auth_members"
                    " WHERE member = %s::regrole", (login,))
        members = cur.fetchone()[0]
        check(f"M1-7 acl: {login} is a member of exactly {{{grp}}} (single-member)",
              members == [grp], members)
    cur.execute("SELECT array_agg(roleid::regrole::text ORDER BY"
                " roleid::regrole::text) FROM pg_auth_members"
                " WHERE member = 'v13_worker'::regrole")
    check("M1-7 acl: v13_worker holds exactly the two plane groups",
          cur.fetchone()[0] == ["v13_resolve", "v13_route"])

    s_login = new_session(cur)
    rc = role_conn("v13_route_login")
    try:
        rk = rc.cursor()
        eid = one(rk, "SELECT v13_enqueue_effect(%s,'judge','{\"login\":1}'::jsonb)",
                  (s_login,))
        check("M1-7 acl: v13_route_login can EXECUTE v13_enqueue_effect", eid is not None)
        fails_with(rk, "SET ROLE v13_resolve", (), "permission denied",
                   "M1-7 acl: v13_route_login cannot SET ROLE v13_resolve (DB-enforced)")
    finally:
        rc.close()
    cur.execute("DELETE FROM effects WHERE session_id=%s", (s_login,))
    lc = role_conn("v13_resolve_login")
    try:
        lk = lc.cursor()
        fails_with(lk, "SET ROLE v13_route", (), "permission denied",
                   "M1-7 acl: v13_resolve_login cannot SET ROLE v13_route")
    finally:
        lc.close()


def a8_threshold_bands(cur) -> None:
    cur.execute("INSERT INTO v13_route_policies (policy_name, policy_version)"
                " VALUES ('t_bands', 1)")
    cur.execute("INSERT INTO thresholds (policy_name, policy_version, signal,"
                " band_no, lo, hi, action) VALUES"
                " ('t_bands',1,'x',1,0.20,0.75,'pass'),"
                " ('t_bands',1,'x',2,0.75,'Infinity','reject')")
    cur.execute("UPDATE v13_route_policies SET state='frozen'"
                " WHERE policy_name='t_bands' AND policy_version=1")

    overlaps = one(cur, "SELECT count(*) FROM thresholds a JOIN thresholds b"
                        " ON a.policy_name=b.policy_name"
                        " AND a.policy_version=b.policy_version"
                        " AND a.signal=b.signal AND a.band_no < b.band_no"
                        " WHERE a.lo < b.hi AND b.lo < a.hi")
    check("M1-8 bands: no two bands of one (policy, signal) overlap", overlaps == 0,
          overlaps)
    cur.execute("SELECT lo, hi FROM thresholds WHERE policy_name='t_bands'"
                " AND signal='x' ORDER BY band_no")
    (lo1, hi1), (lo2, _) = cur.fetchall()
    check("M1-8 bands: adjacent band lo equals previous hi (continuity)",
          lo2 == hi1 and lo1 < hi1, (lo1, hi1, lo2))
    cur.execute("SELECT band_no FROM thresholds WHERE policy_name='t_bands'"
                " AND policy_version=1 AND signal='x'"
                " AND 0.75 >= lo AND 0.75 < hi")
    hit = cur.fetchall()
    check("M1-8 bands: boundary 0.75 hits only the later band (half-open, P1-10)",
          hit == [(2,)], hit)

    sid = u()
    cur.execute("INSERT INTO sessions (session_id, route_policy_name,"
                " route_policy_version) VALUES (%s,'t_bands',1)", (sid,))
    did = mk_decision(cur, sid, "x", "score", "Rate x.", ["low", "mid", "high"],
                      "h_band")
    cur.execute("UPDATE decisions SET answer=%s WHERE decision_id=%s",
                (json.dumps({"score": 0.75}), did))
    cur.execute("SELECT band_no, action, value FROM v_routes WHERE session_id=%s", (sid,))
    rows = cur.fetchall()
    check("M1-8 bands: v_routes resolves boundary 0.75 to exactly one band (band 2)",
          len(rows) == 1 and rows[0][0] == 2 and rows[0][1] == 'reject', rows)

    gap = one(cur, "SELECT count(*) FROM thresholds WHERE policy_name='default'"
                   " AND policy_version=1 AND signal='intent'"
                   " AND 0.5 >= lo AND 0.5 < hi")
    check("M1-8 bands: band gaps are allowed (0.5 hits no 'intent' band)", gap == 0, gap)


def a9_policy_versions(cur) -> None:
    cur.execute("SELECT name, version, active FROM v13_policies"
                " WHERE version=1 AND active ORDER BY name")
    seeds = cur.fetchall()
    names = [r[0] for r in seeds]
    check("M1-9 policies: four v1 seed rows active",
          names == ["effect_attempt_cap", "resolve_fast_path", "resolve_retry",
                    "turn_budget"], names)
    cap = one(cur, "SELECT v13_policy('effect_attempt_cap')")
    check("M1-9 policies: effect_attempt_cap seeds all five kinds (#49/#61)",
          sorted(cap) == ["context_refresh", "human", "judge", "llm", "tool"], cap)

    cur.execute("INSERT INTO v13_policies (name, version, value, active)"
                " VALUES ('gate_probe', 1, '{\"a\":1}'::jsonb, true)")
    check("M1-9 policies: v13_policy() reads the active row",
          one(cur, "SELECT v13_policy('gate_probe')") == {"a": 1})
    cur.execute("UPDATE v13_policies SET active=false"
                " WHERE name='gate_probe' AND version=1")
    cur.execute("INSERT INTO v13_policies (name, version, value, active)"
                " VALUES ('gate_probe', 2, '{\"a\":2}'::jsonb, true)")
    check("M1-9 policies: appended version becomes active, old row kept (P1-10)",
          one(cur, "SELECT v13_policy('gate_probe')") == {"a": 2}
          and one(cur, "SELECT count(*) FROM v13_policies WHERE name='gate_probe'") == 2)
    fails_with(cur, "INSERT INTO v13_policies (name, version, value, active)"
                    " VALUES ('gate_probe', 3, '{\"a\":3}'::jsonb, true)", (),
               "ux_v13_policies_one_active",
               "M1-9 policies: second active row for one name rejected")
    fails_with(cur, "UPDATE v13_policies SET value='{\"a\":9}'::jsonb"
                    " WHERE name='gate_probe' AND version=2", (),
               "immutable", "M1-9 policies: UPDATE value rejected (#29)")
    fails_with(cur, "UPDATE v13_policies SET version=7"
                    " WHERE name='gate_probe' AND version=2", (),
               "immutable", "M1-9 policies: UPDATE version rejected (#29)")
    fails_with(cur, "UPDATE v13_policies SET name='other'"
                    " WHERE name='gate_probe' AND version=2", (),
               "immutable", "M1-9 policies: UPDATE name rejected (#29)")
    fails_with(cur, "DELETE FROM v13_policies WHERE name='gate_probe' AND version=1",
               (), "append-only", "M1-9 policies: DELETE rejected (#29)")
    cur.execute("UPDATE v13_policies SET active=false, updated_at=now()"
                " WHERE name='gate_probe' AND version=2")
    cur.execute("UPDATE v13_policies SET active=true"
                " WHERE name='gate_probe' AND version=1")
    check("M1-9 policies: flipping active (+updated_at) is the permitted UPDATE",
          one(cur, "SELECT v13_policy('gate_probe')") == {"a": 1})
    fails_with(cur, "SELECT v13_policy('never_seeded')", (),
               "no active policy row",
               "M1-9 policies: v13_policy() is fail-closed without an active row")


def a10_source_scan(cur) -> None:
    raw = CORE_SQL.read_text()
    code = strip_sql_comments(raw)
    check("M1-10 scan: typesafe_ask absent from executable SQL of v13_core.sql"
          " (invariant 2)", "typesafe_ask" not in code)
    check("M1-10 scan: no typesafe_ask call syntax anywhere in v13_core.sql,"
          " comments included", "typesafe_ask(" not in raw)
    pure = ["v13_uuid_v5", "v13_last_user_seq", "v13_cycle_no", "v13_signal",
            "v13_effect_id", "v13_policy", "v13_attempt_ok",
            "v13_tool_session_stats"]
    cur.execute("SELECT proname, prosrc FROM pg_proc WHERE proname = ANY(%s)", (pure,))
    rows = cur.fetchall()
    check("M1-10 scan: all pure-read functions found", len(rows) == len(pure), rows)
    for name, src in rows:
        low = src.lower()
        check(f"M1-10 scan: {name} does not call v13_append_event",
              "v13_append_event" not in low)
        check(f"M1-10 scan: {name} does not UPDATE sessions",
              "update sessions" not in low)


def a11_threshold_immutable(cur) -> None:
    fails_with(cur, "UPDATE thresholds SET action='reject' WHERE policy_name='default'"
                    " AND policy_version=1 AND signal='intent' AND band_no=1", (),
               "append-only", "M1-11 thresholds: UPDATE a band rejected (#29/#35)")
    fails_with(cur, "DELETE FROM thresholds WHERE policy_name='default'"
                    " AND policy_version=1 AND signal='intent'", (),
               "append-only", "M1-11 thresholds: DELETE a band rejected")
    cur.execute("INSERT INTO v13_route_policies (policy_name, policy_version)"
                " VALUES ('default', 99)")
    cur.execute("UPDATE v13_route_policies SET state='frozen'"
                " WHERE policy_name='default' AND policy_version=99")
    sid = u()
    cur.execute("INSERT INTO sessions (session_id, route_policy_name,"
                " route_policy_version) VALUES (%s,'default',99)", (sid,))
    check("M1-11 thresholds: empty frozen version is the no-band fixture (not DELETE)",
          one(cur, "SELECT count(*) FROM thresholds WHERE policy_name='default'"
                   " AND policy_version=99") == 0)


def a12_version_lifecycle(server, cur) -> None:
    fails_with(cur, "INSERT INTO thresholds (policy_name, policy_version, signal,"
                    " band_no, lo, hi, action) VALUES"
                    " ('default',1,'intent',2,0.10,0.20,'pass')", (),
               "need a draft parent",
               "M1-12 lifecycle: appending a band to a frozen version rejected")
    cur.execute("INSERT INTO v13_route_policies (policy_name, policy_version)"
                " VALUES ('t2', 1)")
    cur.execute("INSERT INTO thresholds (policy_name, policy_version, signal,"
                " band_no, lo, hi, action) VALUES ('t2',1,'x',1,0.5,'Infinity','pass')")
    check("M1-12 lifecycle: draft version accepts bands", True)
    cur.execute("UPDATE v13_route_policies SET state='frozen'"
                " WHERE policy_name='t2' AND policy_version=1")
    check("M1-12 lifecycle: freeze sets frozen_at",
          one(cur, "SELECT frozen_at IS NOT NULL FROM v13_route_policies"
                   " WHERE policy_name='t2' AND policy_version=1") is True)
    fails_with(cur, "INSERT INTO thresholds (policy_name, policy_version, signal,"
                    " band_no, lo, hi, action) VALUES ('t2',1,'x',2,0.1,0.5,'pass')", (),
               "need a draft parent",
               "M1-12 lifecycle: frozen version refuses further bands")
    fails_with(cur, "UPDATE v13_route_policies SET state='draft'"
                    " WHERE policy_name='t2' AND policy_version=1", (),
               "only transitions draft->frozen",
               "M1-12 lifecycle: unfreezing rejected")
    fails_with(cur, "UPDATE v13_route_policies SET policy_version=2"
                    " WHERE policy_name='t2' AND policy_version=1", (),
               "key is immutable", "M1-12 lifecycle: version key change rejected")
    fails_with(cur, "UPDATE v13_route_policies SET policy_name='t2b'"
                    " WHERE policy_name='t2' AND policy_version=1", (),
               "key is immutable", "M1-12 lifecycle: name key change rejected")
    fails_with(cur, "DELETE FROM v13_route_policies WHERE policy_name='t2'", (),
               "append-only", "M1-12 lifecycle: DELETE a version row rejected")

    cur.execute("INSERT INTO v13_route_policies (policy_name, policy_version)"
                " VALUES ('t_draft', 1)")
    fails_with(cur, "INSERT INTO sessions (session_id, route_policy_name,"
                    " route_policy_version) VALUES (gen_random_uuid(),'t_draft',1)", (),
               "must reference a frozen route policy",
               "M1-12 lifecycle: session referencing a draft version rejected")
    fails_with(cur, "INSERT INTO sessions (session_id, route_policy_name,"
                    " route_policy_version) VALUES (gen_random_uuid(),'nope',1)", (),
               "must reference a frozen route policy",
               "M1-12 lifecycle: session referencing a missing version rejected")
    sid = u()
    cur.execute("INSERT INTO sessions (session_id, route_policy_name,"
                " route_policy_version) VALUES (%s,'t2',1)", (sid,))
    check("M1-12 lifecycle: session referencing a frozen version accepted", True)
    fails_with(cur, "UPDATE sessions SET route_policy_name='t_draft',"
                    " route_policy_version=1 WHERE session_id=%s", (sid,),
               "must reference a frozen route policy",
               "M1-12 lifecycle: repointing a session at a draft version rejected")
    cur.execute("UPDATE sessions SET status='waiting' WHERE session_id=%s", (sid,))
    check("M1-12 lifecycle: plain status UPDATE does not trip the policy guard",
          one(cur, "SELECT status FROM sessions WHERE session_id=%s",
              (sid,)) == "waiting")

    # INSERT || freeze serialization on the parent row (turn 6, #39)
    cur.execute("INSERT INTO v13_route_policies (policy_name, policy_version)"
                " VALUES ('t3', 1)")
    ca = psycopg2.connect(server.get_uri(DB))
    cb = psycopg2.connect(server.get_uri(DB))
    result: dict = {}
    try:
        ka, kb = ca.cursor(), cb.cursor()
        ka.execute("INSERT INTO thresholds (policy_name, policy_version, signal,"
                   " band_no, lo, hi, action) VALUES ('t3',1,'x',1,0.5,'Infinity','pass')")

        def freeze() -> None:
            try:
                kb.execute("UPDATE v13_route_policies SET state='frozen'"
                           " WHERE policy_name='t3' AND policy_version=1")
                cb.commit()
                result["ok"] = True
            except Exception as exc:      # pragma: no cover - surfaced below
                result["err"] = exc

        t = threading.Thread(target=freeze)
        t.start()
        time.sleep(0.6)
        check("M1-12 lifecycle: freeze blocks on the parent row held by the"
              " insert guard (#39)", t.is_alive() and not result, result)
        ca.commit()
        t.join(timeout=10)
        check("M1-12 lifecycle: freeze completes after the band insert commits",
              result.get("ok") is True, result)
    finally:
        ca.close()
        cb.close()
    check("M1-12 lifecycle: the frozen version contains the concurrently added band",
          one(cur, "SELECT count(*) FROM thresholds WHERE policy_name='t3'") == 1)
    fails_with(cur, "INSERT INTO thresholds (policy_name, policy_version, signal,"
                    " band_no, lo, hi, action) VALUES ('t3',1,'x',2,0.1,0.5,'pass')", (),
               "need a draft parent",
               "M1-12 lifecycle: no band can be appended after that freeze")

    # reverse order: freeze commits first, then the insert must be rejected
    cur.execute("INSERT INTO v13_route_policies (policy_name, policy_version)"
                " VALUES ('t4', 1)")
    cur.execute("UPDATE v13_route_policies SET state='frozen'"
                " WHERE policy_name='t4' AND policy_version=1")
    fails_with(cur, "INSERT INTO thresholds (policy_name, policy_version, signal,"
                    " band_no, lo, hi, action) VALUES ('t4',1,'x',1,0.5,1.0,'pass')", (),
               "need a draft parent",
               "M1-12 lifecycle: freeze-first order rejects the later band insert")


def a13_catalog_revisions(cur) -> None:
    r0, g0 = revs(cur)
    cur.execute("CREATE FUNCTION v13_test_ddl_fn(uuid, jsonb) RETURNS jsonb"
                " LANGUAGE sql STABLE AS $$ SELECT $2 $$")
    check("M1-13 revision: creating a not-yet-referenced function bumps nothing",
          revs(cur) == (r0, g0), revs(cur))

    steps = [
        ("INSERT a tool row",
         "INSERT INTO tools (name, description, kind, handler) VALUES"
         " ('ddl_probe','A throwaway probe tool.','sql','v13_test_ddl_fn')"),
        ("UPDATE kind", "UPDATE tools SET kind='tool' WHERE name='ddl_probe'"),
        ("UPDATE handler",
         "UPDATE tools SET handler='worker:probe' WHERE name='ddl_probe'"),
        ("UPDATE param_spec",
         "UPDATE tools SET param_spec='{\"k\":1}'::jsonb WHERE name='ddl_probe'"),
        ("UPDATE enabled", "UPDATE tools SET enabled=false WHERE name='ddl_probe'"),
        ("restore to sql kind",
         "UPDATE tools SET kind='sql', handler='v13_test_ddl_fn', enabled=true,"
         " param_spec='{}'::jsonb WHERE name='ddl_probe'"),
    ]
    prev = r0
    for label, sql in steps:
        cur.execute(sql)
        r, g = revs(cur)
        check(f"M1-13 revision: catalog DML ({label}) bumps revision monotonically",
              r > prev and g == g0, (prev, r, g))
        prev = r

    ddl = [
        ("CREATE OR REPLACE swaps the body",
         "CREATE OR REPLACE FUNCTION v13_test_ddl_fn(uuid, jsonb) RETURNS jsonb"
         " LANGUAGE sql STABLE AS $$ SELECT $2 || '{\"v\":2}'::jsonb $$"),
        ("ALTER FUNCTION SET VOLATILE",
         "ALTER FUNCTION v13_test_ddl_fn(uuid, jsonb) VOLATILE"),
        ("ALTER FUNCTION restore STABLE",
         "ALTER FUNCTION v13_test_ddl_fn(uuid, jsonb) STABLE"),
        ("ALTER ROUTINE SET VOLATILE (synonym tag)",
         "ALTER ROUTINE v13_test_ddl_fn(uuid, jsonb) VOLATILE"),
        ("ALTER ROUTINE restore STABLE",
         "ALTER ROUTINE v13_test_ddl_fn(uuid, jsonb) STABLE"),
    ]
    for label, sql in ddl:
        cur.execute(sql)
        r, g = revs(cur)
        check(f"M1-13 revision: handler DDL ({label}) bumps revision via event trigger",
              r > prev and g == g0, (prev, r, g))
        prev = r

    fails_with(cur, "CREATE OR REPLACE ROUTINE v13_test_ddl_fn(uuid, jsonb)"
                    " RETURNS jsonb LANGUAGE sql STABLE AS $$ SELECT $2 $$", (),
               "syntax error",
               "M1-13 revision: CREATE OR REPLACE ROUTINE is a syntax error"
               " (no such command tag; belt entry stays unreachable)")
    check("M1-13 revision: the rejected ROUTINE spelling changes neither key",
          revs(cur) == (prev, g0), revs(cur))

    cur.execute("CREATE FUNCTION v13_unrelated_fn(uuid, jsonb) RETURNS jsonb"
                " LANGUAGE sql STABLE AS $$ SELECT $2 $$")
    cur.execute("DROP FUNCTION v13_unrelated_fn(uuid, jsonb)")
    check("M1-13 revision: DDL on a name outside the handler set bumps neither key",
          revs(cur) == (prev, g0), revs(cur))

    cur.execute("DROP FUNCTION v13_test_ddl_fn(uuid, jsonb)")
    r, g = revs(cur)
    check("M1-13 revision: DROP FUNCTION bumps revision via the sql_drop face (#62)",
          r > prev and g == g0, (prev, r, g))
    prev = r
    cur.execute("DELETE FROM tools WHERE name='ddl_probe'")
    r, g = revs(cur)
    check("M1-13 revision: DELETE of the tool row bumps revision",
          r > prev and g == g0, (prev, r, g))
    check("M1-13 revision: candidate_generation_revision stayed 0 all along"
          " (v13_needed_judgments is an M2 object)", g == g0 == 0, (g, g0))
    check("M1-13 revision: seed handler untouched",
          one(cur, "SELECT handler FROM tools WHERE name='session_stats'")
          == "v13_tool_session_stats")


def a14_tools_guard(cur) -> None:
    ok_desc = "A probe tool."
    base = ("INSERT INTO tools (name, description, kind, handler, param_spec,"
            " enabled) VALUES (%s,%s,%s,%s,%s,%s)")
    fails_with(cur, base, ("a::b", ok_desc, "tool", "worker:x", "{}", True),
               'contain no "::"', "M1-14 guard: tool name with '::' rejected (#48)")
    fails_with(cur, base, ("", ok_desc, "tool", "worker:x", "{}", True),
               "non-empty", "M1-14 guard: empty tool name rejected")
    fails_with(cur, base, ("pk", ok_desc, "tool", "worker:x",
                           json.dumps({"x::y": {}}), True),
               'contain no "::"', "M1-14 guard: param key with '::' rejected (#48)")
    fails_with(cur, base, ("pe", ok_desc, "tool", "worker:x",
                           json.dumps({"": {}}), True),
               "non-empty", "M1-14 guard: empty param key rejected")
    fails_with(cur, base, ("nope", ok_desc, "sql", "v13_no_such_handler", "{}", True),
               "not found", "M1-14 guard: missing sql handler rejected (#50)")

    cur.execute("CREATE FUNCTION v13_guard_volatile(uuid, jsonb) RETURNS jsonb"
                " LANGUAGE sql VOLATILE AS $$ SELECT $2 $$")
    fails_with(cur, base, ("vol", ok_desc, "sql", "v13_guard_volatile", "{}", True),
               "must be immutable/stable",
               "M1-14 guard: unnamed VOLATILE sql handler rejected"
               " (R2 #50 named closed set does not cover it)")
    cur.execute("CREATE FUNCTION v13_guard_onearg(uuid) RETURNS jsonb"
                " LANGUAGE sql STABLE AS $$ SELECT '{}'::jsonb $$")
    fails_with(cur, base, ("sig", ok_desc, "sql", "v13_guard_onearg", "{}", True),
               "not found", "M1-14 guard: wrong handler signature rejected")
    cur.execute("CREATE FUNCTION v13_guard_norights(uuid, jsonb) RETURNS jsonb"
                " LANGUAGE sql STABLE AS $$ SELECT $2 $$")
    cur.execute("REVOKE EXECUTE ON FUNCTION v13_guard_norights(uuid, jsonb)"
                " FROM PUBLIC")
    fails_with(cur, base, ("norights", ok_desc, "sql", "v13_guard_norights",
                           "{}", True),
               "executable by v13_route",
               "M1-14 guard: handler v13_route cannot execute is rejected")
    cur.execute("CREATE SCHEMA IF NOT EXISTS v13_probe_ns")
    cur.execute("CREATE FUNCTION v13_dup_handler(uuid, jsonb) RETURNS jsonb"
                " LANGUAGE sql STABLE AS $$ SELECT $2 $$")
    cur.execute("CREATE FUNCTION v13_probe_ns.v13_dup_handler(uuid, jsonb)"
                " RETURNS jsonb LANGUAGE sql STABLE AS $$ SELECT $2 $$")
    fails_with(cur, base, ("ambig", ok_desc, "sql", "v13_dup_handler", "{}", True),
               "ambiguous across schemas",
               "M1-14 guard: cross-schema handler name collision rejected")

    r_before, g_before = revs(cur)
    fails_with(cur, base, ("rej", ok_desc, "sql", "v13_no_such_handler", "{}", True),
               "not found", "M1-14 guard: rejected write fails loudly")
    check("M1-14 guard: a rejected write leaves revision untouched"
          " (BEFORE raise -> AFTER bump never runs)",
          revs(cur) == (r_before, g_before), revs(cur))

    cur.execute("UPDATE tools SET description='A demo tool, updated.'"
                " WHERE name='session_stats'")
    check("M1-14 guard: legal sql seed row still accepts a description UPDATE",
          one(cur, "SELECT description FROM tools WHERE name='session_stats'")
          == "A demo tool, updated.")
    cur.execute("INSERT INTO tools (name, description, kind, handler) VALUES"
                " ('worker_tool','A worker side effect tool.','tool',"
                " 'worker:send_thing')")
    check("M1-14 guard: kind='tool' rows skip the handler checks", True)
    cur.execute("INSERT INTO tools (name, description, kind, handler, enabled)"
                " VALUES ('disabled_bad','A disabled tool with a bad handler.',"
                " 'sql','v13_no_such_handler', false)")
    check("M1-14 guard: disabled sql row with a missing handler is accepted", True)

    cur.execute("CREATE FUNCTION v13_guard_iso(uuid, jsonb) RETURNS jsonb"
                " LANGUAGE sql STABLE AS $$ SELECT $2 $$")
    cur.execute("INSERT INTO tools (name, description, kind, handler) VALUES"
                " ('iso_probe','An isolation probe tool.','sql','v13_guard_iso')")
    cur.execute("DROP FUNCTION v13_guard_iso(uuid, jsonb)")
    cur.execute("UPDATE tools SET enabled=false WHERE name='iso_probe'")
    check("M1-14 guard: a row whose handler was dropped can still be disabled (#53)",
          one(cur, "SELECT enabled FROM tools WHERE name='iso_probe'") is False)
    fails_with(cur, "UPDATE tools SET enabled=true WHERE name='iso_probe'", (),
               "not found",
               "M1-14 guard: re-enabling revalidates the handler (fail-closed)")

    cur.execute("DELETE FROM tools WHERE name IN ('worker_tool','disabled_bad',"
                "'iso_probe')")
    cur.execute("UPDATE tools SET description='Answer questions about this"
                " conversation itself: message counts, pending effects, session"
                " status.' WHERE name='session_stats'")


def main() -> int:
    setup_db()
    server = get_server()
    conn = psycopg2.connect(server.get_uri(DB))
    conn.autocommit = True
    cur = conn.cursor()

    a1_append_only(cur)
    a2_concurrent_no_holes(server, cur)
    a3_event_id_and_provenance(cur)
    a4_decisions(cur)
    a5_effects(cur)
    a6_claim_complete(cur)
    a7_roles(cur)
    a8_threshold_bands(cur)
    a9_policy_versions(cur)
    a10_source_scan(cur)
    a11_threshold_immutable(cur)
    a12_version_lifecycle(server, cur)
    a13_catalog_revisions(cur)
    a14_tools_guard(cur)

    conn.close()
    print("[M1 schema] ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
