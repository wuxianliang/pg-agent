"""M1 gate: v13 schema stage — core slice + scaffolding.

Run: uv run python v13/schema/test_schema.py  (exit 0 = pass)
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import psycopg2
import psycopg2.errors

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v13.schema.setup_db import DB, main as setup_db


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f": {detail}" if detail else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def u() -> str:
    return str(uuid.uuid4())


def fails_with(cur, sql: str, params: tuple, needle: str, label: str) -> None:
    cur.execute("SAVEPOINT sp")
    try:
        cur.execute(sql, params)
    except psycopg2.Error as exc:
        msg = str(exc).lower()
        check(label, needle.lower() in msg, str(exc).splitlines()[0])
        cur.execute("ROLLBACK TO SAVEPOINT sp")
        return
    cur.execute("ROLLBACK TO SAVEPOINT sp")
    raise AssertionError(f"{label}: expected failure containing {needle!r}, got success")


def connect_as(server, user: str):
    uri = server.get_uri(DB)
    parsed = urlparse(uri)
    qs = parse_qs(parsed.query)
    host = (qs.get("host") or [None])[0] or parsed.hostname
    return psycopg2.connect(
        host=host,
        dbname=DB,
        user=user,
    )


def new_session(cur, sid=None, policy=("default", 1)):
    sid = sid or u()
    cur.execute(
        "INSERT INTO sessions (session_id, route_policy_name, route_policy_version) "
        "VALUES (%s, %s, %s)",
        (sid, policy[0], policy[1]),
    )
    return sid


def append_user(cur, sid, text="hello"):
    eid = u()
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (sid, eid, json.dumps({"text": text})),
    )
    return cur.fetchone()[0]


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


def main() -> int:
    setup_db()
    server = get_server()
    conn = psycopg2.connect(server.get_uri(DB))
    conn.autocommit = False
    cur = conn.cursor()

    # --- M1-1 events UPDATE/DELETE append-only --------------------------------
    sid = new_session(cur)
    append_user(cur, sid, "a")
    fails_with(cur, "UPDATE events SET payload = '{}'::jsonb WHERE session_id = %s",
               (sid,), "append-only", "M1-1: UPDATE events rejected")
    fails_with(cur, "DELETE FROM events WHERE session_id = %s",
               (sid,), "append-only", "M1-1: DELETE events rejected")

    # --- M1-2 concurrent append, no holes -------------------------------------
    conn.commit()
    sid2 = u()
    cur.execute("INSERT INTO sessions (session_id) VALUES (%s)", (sid2,))
    conn.commit()

    def _append_one(payload: str) -> None:
        c = psycopg2.connect(server.get_uri(DB))
        try:
            k = c.cursor()
            k.execute("SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
                      (sid2, u(), json.dumps({"t": payload})))
            c.commit()
        finally:
            c.close()

    import threading
    t1 = threading.Thread(target=_append_one, args=("a",))
    t2 = threading.Thread(target=_append_one, args=("b",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    cur.execute("SELECT max(seq), count(*) FROM events WHERE session_id = %s", (sid2,))
    mx, cnt = cur.fetchone()
    check("M1-2: max(seq)=count(*)-1 no holes", mx == cnt - 1, (mx, cnt))

    # --- M1-3 duplicate event_id; source_effect_id ----------------------------
    sid3 = new_session(cur)
    eid = u()
    cur.execute("SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
                (sid3, eid, json.dumps({"t": 1})))
    fails_with(cur,
               "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
               (sid3, eid, json.dumps({"t": 2})),
               "unique", "M1-3: duplicate event_id rejected")
    seid = u()
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'tool/result', %s::jsonb, %s::uuid)",
        (sid3, u(), json.dumps({"ok": True}), seid))
    cur.execute("SELECT source_effect_id FROM events WHERE session_id = %s "
                "AND type = 'tool/result'", (sid3,))
    check("M1-3: source_effect_id landed", str(cur.fetchone()[0]) == seid)

    # --- M1-4 decisions -------------------------------------------------------
    sid4 = new_session(cur)
    ctx = json.dumps({"k": "v"})
    rh = "h1"
    cur.execute(
        "INSERT INTO decisions (session_id, signal, kind, question, criteria, "
        "context, request_hash) VALUES (%s, 'intent', 'choice', 'Pick one.', "
        "%s::jsonb, %s::jsonb, %s)",
        (sid4, json.dumps({"a": "A", "b": "B"}), ctx, rh))
    fails_with(cur,
               "INSERT INTO decisions (session_id, signal, kind, question, criteria, "
               "context, request_hash) VALUES (%s, 'intent', 'choice', '中文题目', "
               "%s::jsonb, %s::jsonb, 'h2')",
               (sid4, json.dumps({"a": "A"}), ctx),
               "check", "M1-4: non-ASCII question rejected")
    fails_with(cur,
               "INSERT INTO decisions (session_id, signal, kind, question, criteria, "
               "context, request_hash) VALUES (%s, 'x', 'choice', 'Pick.', "
               "'[]'::jsonb, %s::jsonb, 'h3')",
               (sid4, ctx),
               "choice_shape", "M1-4: choice array criteria rejected")
    fails_with(cur,
               "INSERT INTO decisions (session_id, signal, kind, question, criteria, "
               "context, request_hash) VALUES (%s, 'x', 'score', 'Rate.', "
               "'[\"a\"]'::jsonb, %s::jsonb, 'h4')",
               (sid4, ctx),
               "score_shape", "M1-4: score one-level rejected")
    fails_with(cur,
               "INSERT INTO decisions (session_id, signal, kind, question, criteria, "
               "context, request_hash) VALUES (%s, 'x', 'noul', 'Is it?', "
               "'null'::jsonb, %s::jsonb, 'h5')",
               (sid4, ctx),
               "noul_shape", "M1-4: noul jsonb null rejected")
    cur.execute(
        "INSERT INTO decisions (session_id, signal, kind, question, criteria, "
        "context, request_hash) VALUES (%s, 'n1', 'noul', 'Is it?', "
        "NULL, %s::jsonb, 'h6')",
        (sid4, ctx))
    cur.execute("SELECT criteria IS NULL FROM decisions "
                "WHERE session_id=%s AND signal='n1'", (sid4,))
    check("M1-4: noul SQL NULL criteria accepted", cur.fetchone()[0] is True)
    cur.execute(
        "UPDATE decisions SET answer = %s::jsonb WHERE session_id = %s "
        "AND request_hash = 'h1'",
        (json.dumps({"type": "choice", "choice": "a", "confidence": 0.9}), sid4))
    fails_with(cur,
               "UPDATE decisions SET answer = %s::jsonb WHERE session_id = %s "
               "AND request_hash = 'h1'",
               (json.dumps({"type": "choice", "choice": "b", "confidence": 0.8}), sid4),
               "immutable", "M1-4: answer-once rewrite rejected")
    fails_with(cur,
               "INSERT INTO decisions (session_id, signal, kind, question, criteria, "
               "context, request_hash) VALUES (%s, 'intent', 'choice', 'Pick one.', "
               "%s::jsonb, %s::jsonb, %s)",
               (sid4, json.dumps({"a": "A", "b": "B"}), ctx, rh),
               "unique", "M1-4: same session duplicate request_hash rejected")
    sid4b = new_session(cur)
    cur.execute(
        "INSERT INTO decisions (session_id, signal, kind, question, criteria, "
        "context, request_hash) VALUES (%s, 'intent', 'choice', 'Pick one.', "
        "%s::jsonb, %s::jsonb, %s)",
        (sid4b, json.dumps({"a": "A", "b": "B"}), ctx, rh))
    cur.execute("SELECT count(*) FROM decisions WHERE request_hash = %s", (rh,))
    check("M1-4: cross-session same hash each 1 row", cur.fetchone()[0] == 2)

    # --- M1-5 effects ---------------------------------------------------------
    sid5 = new_session(cur)
    append_user(cur, sid5, "do it")
    fails_with(cur,
               "INSERT INTO effects (effect_id, session_id, kind, tool_name, request, "
               "request_hash, origin_user_seq) VALUES (%s, %s, 'tool', NULL, "
               "'{}'::jsonb, 'x', 0)",
               (u(), sid5),
               "tool_named", "M1-5: kind=tool tool_name NULL rejected")
    cur.execute("SELECT v13_enqueue_effect(%s, 'human', %s::jsonb)",
                (sid5, json.dumps({"reason": "r1"})))
    hid = cur.fetchone()[0]
    fails_with(cur,
               "SELECT v13_enqueue_effect(%s, 'llm', %s::jsonb)",
               (sid5, json.dumps({"prompt": "x"})),
               "single_active", "M1-5: second ready effect rejected")
    # succeeded replay
    claimed = claim_pinned(cur, hid)
    check("M1-5: claim returns effect", str(claimed["effect_id"]) == str(hid), claimed)
    cur.execute("SELECT v13_complete(%s, %s, %s, 'succeeded', %s::jsonb)",
                (hid, claimed["attempt_no"], claimed["fence"], json.dumps({"ok": True})))
    check("M1-5: complete succeeded", cur.fetchone()[0] == "accepted")
    cur.execute("SELECT v13_enqueue_effect(%s, 'human', %s::jsonb)",
                (sid5, json.dumps({"reason": "r1"})))
    check("M1-5: succeeded re-enqueue same id", cur.fetchone()[0] == hid)
    cur.execute("SELECT status FROM effects WHERE effect_id = %s", (hid,))
    check("M1-5: succeeded replay stays succeeded", cur.fetchone()[0] == "succeeded")

    # failed rehang + old token stale
    sid5b = new_session(cur)
    append_user(cur, sid5b)
    cur.execute("SELECT v13_enqueue_effect(%s, 'human', %s::jsonb)",
                (sid5b, json.dumps({"reason": "r2"})))
    hid2 = cur.fetchone()[0]
    c2 = claim_pinned(cur, hid2)
    old_attempt, old_fence = c2["attempt_no"], c2["fence"]
    cur.execute("SELECT v13_complete(%s, %s, %s, 'failed', NULL)",
                (hid2, old_attempt, old_fence))
    check("M1-5: first fail accepted", cur.fetchone()[0] == "accepted")
    cur.execute("SELECT fence FROM effects WHERE effect_id = %s", (hid2,))
    fence_before = cur.fetchone()[0]
    cur.execute("SELECT v13_enqueue_effect(%s, 'human', %s::jsonb)",
                (sid5b, json.dumps({"reason": "r2"})))
    check("M1-5: failed rehang same id", cur.fetchone()[0] == hid2)
    cur.execute("SELECT status, fence FROM effects WHERE effect_id = %s", (hid2,))
    st, fn = cur.fetchone()
    check("M1-5: rehang ready fence+1", st == "ready" and fn == fence_before + 1, (st, fn))
    cur.execute("SELECT v13_complete(%s, %s, %s, 'succeeded', '{}'::jsonb)",
                (hid2, old_attempt, old_fence))
    check("M1-5: old token complete stale", cur.fetchone()[0] == "stale")
    cur.execute("SELECT status FROM effects WHERE effect_id = %s", (hid2,))
    check("M1-5: stale complete zero status change", cur.fetchone()[0] == "ready")

    # unknown refuse reentry
    c3 = claim_pinned(cur, hid2)
    cur.execute("SELECT v13_complete(%s, %s, %s, 'unknown', NULL)",
                (c3["effect_id"], c3["attempt_no"], c3["fence"]))
    check("M1-5: complete unknown", cur.fetchone()[0] == "accepted")
    fails_with(cur,
               "SELECT v13_enqueue_effect(%s, 'human', %s::jsonb)",
               (sid5b, json.dumps({"reason": "r2"})),
               "unknown", "M1-5: unknown refuses reentry")

    # same turn same kind different request -> two ids
    sid5c = new_session(cur)
    append_user(cur, sid5c)
    cur.execute("SELECT v13_enqueue_effect(%s, 'human', %s::jsonb)",
                (sid5c, json.dumps({"reason": "a"})))
    id_a = cur.fetchone()[0]
    cur.execute("UPDATE effects SET status='succeeded' WHERE effect_id = %s", (id_a,))
    cur.execute("SELECT v13_enqueue_effect(%s, 'human', %s::jsonb)",
                (sid5c, json.dumps({"reason": "b"})))
    id_b = cur.fetchone()[0]
    check("M1-5: different request different id", id_a != id_b)
    cur.execute("SELECT count(*) FROM effects WHERE session_id = %s", (sid5c,))
    check("M1-5: two rows coexist", cur.fetchone()[0] == 2)

    cur.execute("SELECT idempotency_key FROM effects WHERE effect_id = %s", (id_a,))
    ik = cur.fetchone()[0]
    check("M1-5: idempotency_key = v13:id", ik == "v13:" + str(id_a), ik)

    # attempt cap: human=2, two claim+fail then enqueue no rehang
    sid5d = new_session(cur)
    append_user(cur, sid5d)
    req = json.dumps({"reason": "cap"})
    cur.execute("SELECT v13_enqueue_effect(%s, 'human', %s::jsonb)", (sid5d, req))
    hid3 = cur.fetchone()[0]
    for _ in range(2):
        ck = claim_pinned(cur, hid3)
        cur.execute("SELECT v13_complete(%s, %s, %s, 'failed', NULL)",
                    (hid3, ck["attempt_no"], ck["fence"]))
        cur.fetchone()
        cur.execute("SELECT v13_enqueue_effect(%s, 'human', %s::jsonb)", (sid5d, req))
        cur.fetchone()
    cur.execute("SELECT attempt_no, status, fence FROM effects WHERE effect_id = %s",
                (hid3,))
    att, st, fn_cap = cur.fetchone()
    check("M1-5: after two fails attempt_no=2", att == 2, att)
    fence_at_cap = fn_cap
    cur.execute("SELECT count(*) FROM events WHERE session_id = %s", (sid5d,))
    ev_before = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM pgmq.q_v13_work")
    q_before = cur.fetchone()[0]
    cur.execute("SELECT v13_enqueue_effect(%s, 'human', %s::jsonb)", (sid5d, req))
    check("M1-5: cap enqueue returns same id", cur.fetchone()[0] == hid3)
    cur.execute("SELECT status, fence FROM effects WHERE effect_id = %s", (hid3,))
    st, fn = cur.fetchone()
    check("M1-5: cap refuses rehang stays failed", st == "failed" and fn == fence_at_cap,
          (st, fn))
    cur.execute("SELECT count(*) FROM events WHERE session_id = %s", (sid5d,))
    check("M1-5: cap rehang zero events", cur.fetchone()[0] == ev_before)
    cur.execute("SELECT count(*) FROM pgmq.q_v13_work")
    check("M1-5: cap rehang zero wake", cur.fetchone()[0] == q_before)

    # missing key fail-loud (turn 10 fixture order)
    cur.execute(
        "INSERT INTO v13_policies (name, version, value, active) VALUES "
        "('effect_attempt_cap', 2, %s::jsonb, false)",
        ('{"judge":4,"tool":3,"llm":3,"context_refresh":3}',),
    )
    cur.execute("UPDATE v13_policies SET active=false "
                "WHERE name='effect_attempt_cap' AND version=1")
    cur.execute("UPDATE v13_policies SET active=true "
                "WHERE name='effect_attempt_cap' AND version=2")
    sid5e = new_session(cur)
    append_user(cur, sid5e)
    fails_with(cur,
               "SELECT v13_enqueue_effect(%s, 'human', %s::jsonb)",
               (sid5e, json.dumps({"reason": "missing"})),
               "missing kind", "M1-5: missing cap key RAISE")
    cur.execute("SELECT count(*) FROM effects WHERE session_id = %s", (sid5e,))
    check("M1-5: missing key zero rows", cur.fetchone()[0] == 0)
    cur.execute("UPDATE v13_policies SET active=false "
                "WHERE name='effect_attempt_cap' AND version=2")
    cur.execute("UPDATE v13_policies SET active=true "
                "WHERE name='effect_attempt_cap' AND version=1")

    # --- M1-6 claim/complete CAS ---------------------------------------------
    sid6 = new_session(cur)
    append_user(cur, sid6)
    cur.execute("SELECT v13_enqueue_effect(%s, 'human', %s::jsonb)",
                (sid6, json.dumps({"k": 1})))
    e6 = cur.fetchone()[0]
    # ready row complete with (0,0) -> stale
    cur.execute("SELECT v13_complete(%s, 0, 0, 'succeeded', '{}'::jsonb)", (e6,))
    check("M1-6: unclaimed complete stale", cur.fetchone()[0] == "stale")
    cur.execute("SELECT status FROM effects WHERE effect_id = %s", (e6,))
    check("M1-6: unclaimed zero change", cur.fetchone()[0] == "ready")
    fails_with(cur,
               "SELECT v13_complete(%s, NULL, 0, 'succeeded', NULL)",
               (e6,),
               "non-null", "M1-6: NULL attempt RAISE")
    fails_with(cur,
               "SELECT v13_complete(%s, 0, NULL, 'succeeded', NULL)",
               (e6,),
               "non-null", "M1-6: NULL fence RAISE")
    fails_with(cur,
               "SELECT v13_complete(%s, 1, 1, 'succeeded', NULL)",
               (u(),),
               "unknown effect", "M1-6: missing effect RAISE")

    c6 = claim_pinned(cur, e6)
    cur.execute("SELECT v13_complete(%s, %s, %s, 'succeeded', %s::jsonb)",
                (e6, c6["attempt_no"], c6["fence"], json.dumps({"ok": 1})))
    check("M1-6: accepted", cur.fetchone()[0] == "accepted")
    cur.execute("SELECT v13_complete(%s, %s, %s, 'succeeded', %s::jsonb)",
                (e6, c6["attempt_no"], c6["fence"], json.dumps({"ok": 1})))
    check("M1-6: succeeded replay", cur.fetchone()[0] == "replay")
    cur.execute("SELECT count(*) FROM events WHERE session_id = %s AND type='effect_done'",
                (sid6,))
    n_done = cur.fetchone()[0]
    cur.execute("SELECT v13_complete(%s, %s, %s, 'succeeded', %s::jsonb)",
                (e6, c6["attempt_no"], c6["fence"], json.dumps({"ok": 1})))
    cur.fetchone()
    cur.execute("SELECT count(*) FROM events WHERE session_id = %s AND type='effect_done'",
                (sid6,))
    check("M1-6: succeeded replay zero new events", cur.fetchone()[0] == n_done)

    # failed replay only one effect_done + one resolve/failed for judge
    sid6j = new_session(cur)
    append_user(cur, sid6j)
    cur.execute("SELECT v13_enqueue_effect(%s, 'judge', %s::jsonb)",
                (sid6j, json.dumps({"needed": []})))
    ej = cur.fetchone()[0]
    cj = claim_pinned(cur, ej)
    cur.execute("SELECT v13_complete(%s, %s, %s, 'failed', NULL)",
                (ej, cj["attempt_no"], cj["fence"]))
    check("M1-6: judge fail accepted", cur.fetchone()[0] == "accepted")
    cur.execute("SELECT v13_complete(%s, %s, %s, 'failed', NULL)",
                (ej, cj["attempt_no"], cj["fence"]))
    check("M1-6: failed replay", cur.fetchone()[0] == "replay")
    cur.execute("SELECT count(*) FILTER (WHERE type='effect_done'), "
                "count(*) FILTER (WHERE type='resolve/failed') "
                "FROM events WHERE session_id = %s", (sid6j,))
    ed, rf = cur.fetchone()
    check("M1-6: judge fail one effect_done + one resolve/failed",
          ed == 1 and rf == 1, (ed, rf))

    # tool success -> effect_done + tool/result with source_effect_id
    sid6t = new_session(cur)
    append_user(cur, sid6t)
    cur.execute("SELECT v13_enqueue_effect(%s, 'tool', %s::jsonb, 'session_stats')",
                (sid6t, json.dumps({"tool": "session_stats", "params": {}})))
    et = cur.fetchone()[0]
    ct = claim_pinned(cur, et)
    cur.execute("SELECT v13_complete(%s, %s, %s, 'succeeded', %s::jsonb)",
                (et, ct["attempt_no"], ct["fence"], json.dumps({"n": 1})))
    cur.fetchone()
    cur.execute("SELECT type, source_effect_id FROM events WHERE session_id = %s "
                "AND type IN ('effect_done','tool/result') ORDER BY seq", (sid6t,))
    rows = cur.fetchall()
    types = [r[0] for r in rows]
    check("M1-6: tool success events", types == ["effect_done", "tool/result"], types)
    check("M1-6: tool/result source_effect_id",
          all(str(r[1]) == str(et) for r in rows), rows)

    # llm success + shape failures
    sid6l = new_session(cur)
    append_user(cur, sid6l)
    cur.execute("SELECT v13_last_user_seq(%s)", (sid6l,))
    origin = cur.fetchone()[0]
    cur.execute("SELECT v13_enqueue_effect(%s, 'llm', %s::jsonb)",
                (sid6l, json.dumps({"prompt": "hi"})))
    el = cur.fetchone()[0]
    cl = claim_pinned(cur, el)
    cur.execute("SELECT v13_complete(%s, %s, %s, 'succeeded', %s::jsonb)",
                (el, cl["attempt_no"], cl["fence"], json.dumps({"text": "hello"})))
    check("M1-6: llm good shape accepted", cur.fetchone()[0] == "accepted")
    cur.execute("SELECT payload FROM events WHERE session_id = %s AND type='llm/message'",
                (sid6l,))
    payload = cur.fetchone()[0]
    check("M1-6: llm/message origin_user_seq",
          payload.get("origin_user_seq") == origin, payload)

    for i, bad in enumerate([None, {}, {"text": None}, {"text": 1}, {"text": "  "}]):
        sidb = new_session(cur)
        append_user(cur, sidb)
        cur.execute("SELECT v13_enqueue_effect(%s, 'llm', %s::jsonb)",
                    (sidb, json.dumps({"prompt": f"b{i}"})))
        eb = cur.fetchone()[0]
        cb = claim_pinned(cur, eb)
        result = None if bad is None else json.dumps(bad)
        cur.execute("SELECT v13_complete(%s, %s, %s, 'succeeded', %s)",
                    (eb, cb["attempt_no"], cb["fence"], result))
        check(f"M1-6: llm bad shape {i} accepted-as-failed-path",
              cur.fetchone()[0] == "accepted")
        cur.execute("SELECT status, error->>'code' FROM effects WHERE effect_id = %s",
                    (eb,))
        st, code = cur.fetchone()
        check(f"M1-6: llm bad shape {i} failed llm_result_shape",
              st == "failed" and code == "llm_result_shape", (st, code))
        cur.execute("SELECT count(*) FROM events WHERE session_id = %s "
                    "AND type='llm/message'", (sidb,))
        check(f"M1-6: llm bad shape {i} zero llm/message", cur.fetchone()[0] == 0)

    # --- M1-7 roles -----------------------------------------------------------
    conn.commit()
    cur.execute("SET ROLE v13_recall")
    cur.execute("SELECT count(*) FROM sessions")
    cur.execute("SELECT count(*) FROM events")
    cur.execute("SELECT count(*) FROM decisions")
    cur.execute("SELECT count(*) FROM thresholds")
    cur.execute("SELECT count(*) FROM tools")
    cur.execute("SELECT count(*) FROM v13_policies")
    cur.execute("SELECT count(*) FROM v13_tools_meta")
    n_meta = cur.fetchone()[0]
    check("M1-7: recall SELECT seven tables", isinstance(n_meta, int) and n_meta >= 1, n_meta)
    fails_with(cur, "INSERT INTO decisions (session_id, signal, kind, question, "
               "context, request_hash) VALUES (%s, 'x', 'noul', 'Q', '{}'::jsonb, 'z')",
               (sid4,), "permission", "M1-7: recall INSERT decisions denied")
    fails_with(cur, "UPDATE sessions SET status='ready' WHERE session_id = %s",
               (sid4,), "permission", "M1-7: recall UPDATE sessions denied")
    fails_with(cur, "SELECT v13_append_event(%s, %s, 'user/message', '{}'::jsonb)",
               (sid4, u()), "permission", "M1-7: recall EXECUTE append denied")
    fails_with(cur, "SELECT * FROM v_routes LIMIT 1", (),
               "permission", "M1-7: recall SELECT v_routes denied")
    cur.execute("RESET ROLE")

    cur.execute("SET ROLE v13_resolve")
    fails_with(cur, "INSERT INTO effects (effect_id, session_id, kind, request, "
               "request_hash, origin_user_seq) VALUES (%s, %s, 'human', '{}'::jsonb, "
               "'x', 0)",
               (u(), sid4), "permission", "M1-7: resolve INSERT effects denied")
    fails_with(cur, "SELECT v13_enqueue_effect(%s, 'human', '{}'::jsonb)",
               (sid4,), "permission", "M1-7: resolve EXECUTE enqueue denied")
    fails_with(cur, "SELECT * FROM v13_remote_sqlstates", (),
               "permission", "M1-7: resolve SELECT remote_sqlstates denied")
    fails_with(cur, "SELECT * FROM v13_route_policies", (),
               "permission", "M1-7: resolve SELECT route_policies denied")
    fails_with(cur, "UPDATE decisions SET question = 'nope' WHERE session_id = %s",
               (sid4,), "permission", "M1-7: resolve UPDATE question denied")
    fails_with(cur, "UPDATE decisions SET context = '{}'::jsonb WHERE session_id = %s",
               (sid4,), "permission", "M1-7: resolve UPDATE context denied")
    fails_with(cur, "UPDATE decisions SET provider = 'x' WHERE session_id = %s",
               (sid4,), "permission", "M1-7: resolve UPDATE provider denied")
    cur.execute("RESET ROLE")

    cur.execute("SET ROLE v13_route")
    cur.execute("SELECT has_function_privilege('v13_route', "
                "'v13_enqueue_effect(uuid,text,jsonb,text)', 'EXECUTE')")
    check("M1-7: route EXECUTE enqueue", cur.fetchone()[0] is True)
    cur.execute("SELECT count(*) FROM v_routes")
    n_routes = cur.fetchone()[0]
    check("M1-7: route SELECT v_routes", isinstance(n_routes, int) and n_routes >= 0, n_routes)
    cur.execute("SELECT count(*) FROM v13_route_policies")
    n_pol = cur.fetchone()[0]
    check("M1-7: route SELECT route_policies", isinstance(n_pol, int) and n_pol >= 1, n_pol)
    fails_with(cur, "SELECT * FROM v13_remote_sqlstates", (),
               "permission", "M1-7: route SELECT remote_sqlstates denied")
    cur.execute("RESET ROLE")

    cur.execute("SELECT has_function_privilege('public', "
                "'v13_tool_session_stats(uuid,jsonb)', 'EXECUTE')")
    check("M1-7: tool_session_stats PUBLIC EXECUTE", cur.fetchone()[0] is True)

    cur.execute("SELECT rolcanlogin FROM pg_roles WHERE rolname='v13_resolve_login'")
    check("M1-7: resolve_login can login", cur.fetchone()[0] is True)
    cur.execute("SELECT rolcanlogin FROM pg_roles WHERE rolname='v13_route_login'")
    check("M1-7: route_login can login", cur.fetchone()[0] is True)
    cur.execute("SELECT r.rolname FROM pg_auth_members m "
                "JOIN pg_roles r ON r.oid = m.roleid "
                "JOIN pg_roles u ON u.oid = m.member "
                "WHERE u.rolname='v13_resolve_login' ORDER BY 1")
    mem = [r[0] for r in cur.fetchall()]
    check("M1-7: resolve_login members {v13_resolve}", mem == ["v13_resolve"], mem)
    cur.execute("SELECT r.rolname FROM pg_auth_members m "
                "JOIN pg_roles r ON r.oid = m.roleid "
                "JOIN pg_roles u ON u.oid = m.member "
                "WHERE u.rolname='v13_route_login' ORDER BY 1")
    mem = [r[0] for r in cur.fetchall()]
    check("M1-7: route_login members {v13_route}", mem == ["v13_route"], mem)

    rconn = connect_as(server, "v13_route_login")
    rc = rconn.cursor()
    rc.execute("SELECT has_function_privilege('v13_enqueue_effect(uuid,text,jsonb,text)', "
               "'EXECUTE')")
    check("M1-7: route_login EXECUTE enqueue", rc.fetchone()[0] is True)
    try:
        rc.execute("SET ROLE v13_resolve")
        check("M1-7: route_login SET ROLE resolve denied", False, "unexpected success")
    except psycopg2.Error as exc:
        check("M1-7: route_login SET ROLE resolve denied",
              "permission" in str(exc).lower() or "set role" in str(exc).lower(),
              str(exc).splitlines()[0])
        rconn.rollback()
    rconn.close()

    cur.execute("SELECT rolcanlogin, rolinherit FROM pg_roles WHERE rolname='v13_worker'")
    can, inh = cur.fetchone()
    check("M1-7: worker LOGIN NOINHERIT", can is True and inh is False, (can, inh))
    cur.execute("SELECT r.rolname FROM pg_auth_members m "
                "JOIN pg_roles r ON r.oid = m.roleid "
                "JOIN pg_roles u ON u.oid = m.member "
                "WHERE u.rolname='v13_worker' ORDER BY 1")
    mem = [r[0] for r in cur.fetchall()]
    check("M1-7: worker members {v13_resolve, v13_route}",
          mem == ["v13_resolve", "v13_route"], mem)

    # --- M1-8 thresholds bands ------------------------------------------------
    cur.execute("""
        SELECT count(*) FROM thresholds a
        JOIN thresholds b
          ON a.policy_name=b.policy_name AND a.policy_version=b.policy_version
         AND a.signal=b.signal AND a.band_no < b.band_no
         AND a.hi > b.lo
    """)
    check("M1-8: seed bands pairwise non-overlapping", cur.fetchone()[0] == 0)
    cur.execute(
        "INSERT INTO v13_route_policies (policy_name, policy_version) "
        "VALUES ('m1bands', 1)")
    cur.execute(
        "INSERT INTO thresholds (policy_name, policy_version, signal, band_no, "
        "lo, hi, action) VALUES "
        "('m1bands',1,'intent',1,0.0,0.75,'pass'),"
        "('m1bands',1,'intent',2,0.75,'Infinity','pass')")
    cur.execute("UPDATE v13_route_policies SET state='frozen' "
                "WHERE policy_name='m1bands' AND policy_version=1")
    cur.execute("""
        SELECT a.hi = b.lo FROM thresholds a
        JOIN thresholds b ON a.policy_name=b.policy_name
         AND a.policy_version=b.policy_version AND a.signal=b.signal
         AND a.band_no+1 = b.band_no
        WHERE a.policy_name='m1bands'
    """)
    check("M1-8: adjacent lo=previous hi", cur.fetchone()[0] is True)
    sid8 = new_session(cur, policy=("m1bands", 1))
    cur.execute(
        "INSERT INTO decisions (session_id, signal, kind, question, criteria, "
        "context, request_hash, answer) VALUES "
        "(%s, 'intent', 'choice', 'Pick.', %s::jsonb, '{}'::jsonb, 'b075', "
        "%s::jsonb)",
        (sid8, json.dumps({"a": "A", "b": "B"}),
         json.dumps({"choice": "a", "confidence": 0.75})))
    # answer-once trigger only fires on UPDATE NULL->nonNULL; INSERT with answer
    # leaves status open unless we update. Set answered via update path:
    # actually INSERT with answer may stay open. Force status:
    cur.execute("UPDATE decisions SET status='answered' WHERE session_id=%s "
                "AND request_hash='b075'", (sid8,))
    # status update is allowed; answer already set
    cur.execute("SELECT band_no, action FROM v_routes WHERE session_id=%s "
                "AND signal='intent'", (sid8,))
    row = cur.fetchone()
    check("M1-8: 0.75 hits later band not earlier",
          row is not None and row[0] == 2, row)

    # --- M1-9 v13_policies versioning -----------------------------------------
    cur.execute("SELECT count(*) FROM v13_policies WHERE version=1 AND active")
    check("M1-9: four v1 active rows", cur.fetchone()[0] == 4)
    cur.execute("SELECT value FROM v13_policies "
                "WHERE name='effect_attempt_cap' AND active")
    cap = cur.fetchone()[0]
    for k in ("judge", "tool", "llm", "human", "context_refresh"):
        check(f"M1-9: cap has {k}", k in cap, cap)
    cur.execute("UPDATE v13_policies SET active=false "
                "WHERE name='turn_budget' AND version=1")
    cur.execute(
        "INSERT INTO v13_policies (name, version, value, active) VALUES "
        "('turn_budget', 2, '{\"max_cycles\": 9}'::jsonb, true)")
    cur.execute("SELECT v13_policy('turn_budget')->>'max_cycles'")
    check("M1-9: policy() reads v2", cur.fetchone()[0] == "9")
    cur.execute("SELECT count(*) FROM v13_policies WHERE name='turn_budget'")
    check("M1-9: old version row kept", cur.fetchone()[0] == 2)
    fails_with(cur,
               "INSERT INTO v13_policies (name, version, value, active) VALUES "
               "('turn_budget', 3, '{\"max_cycles\": 1}'::jsonb, true)",
               (),
               "unique", "M1-9: second active rejected")
    fails_with(cur,
               "UPDATE v13_policies SET value='{}'::jsonb "
               "WHERE name='turn_budget' AND version=2",
               (), "immutable", "M1-9: UPDATE value rejected")
    fails_with(cur,
               "UPDATE v13_policies SET version=9 "
               "WHERE name='turn_budget' AND version=2",
               (), "immutable", "M1-9: UPDATE version rejected")
    fails_with(cur,
               "UPDATE v13_policies SET name='x' "
               "WHERE name='turn_budget' AND version=2",
               (), "immutable", "M1-9: UPDATE name rejected")
    fails_with(cur,
               "DELETE FROM v13_policies WHERE name='turn_budget' AND version=2",
               (), "append-only", "M1-9: DELETE rejected")
    fails_with(cur, "SELECT v13_policy('no_such_policy')", (),
               "no active policy", "M1-9: missing name fail-closed")
    # restore turn_budget v1
    cur.execute("UPDATE v13_policies SET active=false "
                "WHERE name='turn_budget' AND version=2")
    cur.execute("UPDATE v13_policies SET active=true "
                "WHERE name='turn_budget' AND version=1")

    # --- M1-10 source scan ----------------------------------------------------
    core = (ROOT / "v13_core.sql").read_text()
    core_code = "\n".join(
        l for l in core.splitlines() if not l.lstrip().startswith("--"))
    check("M1-10: typesafe_ask absent from core", "typesafe_ask" not in core_code)
    for fn in ("v13_last_user_seq", "v13_cycle_no", "v13_signal",
               "v13_uuid_v5", "v13_tool_session_stats", "v13_policy"):
        part = core.split(f"CREATE FUNCTION {fn}")[1].split("CREATE FUNCTION")[0]
        check(f"M1-10: {fn} has no append_event", "v13_append_event" not in part)
        check(f"M1-10: {fn} has no UPDATE sessions", "UPDATE sessions" not in part)

    # --- M1-11 thresholds version immutable -----------------------------------
    fails_with(cur,
               "UPDATE thresholds SET lo=0.1 WHERE policy_name='default' "
               "AND signal='intent'",
               (), "append-only", "M1-11: UPDATE threshold rejected")
    fails_with(cur,
               "DELETE FROM thresholds WHERE policy_name='default' AND signal='intent'",
               (), "append-only", "M1-11: DELETE threshold rejected")
    cur.execute("INSERT INTO v13_route_policies (policy_name, policy_version) "
                "VALUES ('tnew', 1)")
    cur.execute("INSERT INTO thresholds (policy_name, policy_version, signal, "
                "band_no, lo, hi, action) VALUES "
                "('tnew',1,'intent',1,0.5,'Infinity','pass')")
    cur.execute("SELECT count(*) FROM thresholds WHERE policy_name='tnew'")
    check("M1-11: INSERT new version band ok", cur.fetchone()[0] == 1)
    cur.execute("INSERT INTO v13_route_policies (policy_name, policy_version) "
                "VALUES ('default', 99)")
    cur.execute("UPDATE v13_route_policies SET state='frozen' "
                "WHERE policy_name='default' AND policy_version=99")
    cur.execute("SELECT state FROM v13_route_policies "
                "WHERE policy_name='default' AND policy_version=99")
    check("M1-11: empty frozen version 99", cur.fetchone()[0] == "frozen")

    # --- M1-12 thresholds lifecycle + concurrent freeze -----------------------
    fails_with(cur,
               "INSERT INTO thresholds (policy_name, policy_version, signal, "
               "band_no, lo, hi, action) VALUES "
               "('default',1,'intent',99,0.1,0.2,'pass')",
               (), "draft parent", "M1-12: insert into frozen seed rejected")
    cur.execute("INSERT INTO v13_route_policies (policy_name, policy_version) "
                "VALUES ('t2', 1)")
    cur.execute("INSERT INTO thresholds (policy_name, policy_version, signal, "
                "band_no, lo, hi, action) VALUES "
                "('t2',1,'intent',1,0.5,'Infinity','pass')")
    cur.execute("SELECT count(*) FROM thresholds WHERE policy_name='t2'")
    check("M1-12: insert into draft t2 ok", cur.fetchone()[0] == 1)
    cur.execute("UPDATE v13_route_policies SET state='frozen' "
                "WHERE policy_name='t2' AND policy_version=1")
    cur.execute("SELECT frozen_at IS NOT NULL FROM v13_route_policies "
                "WHERE policy_name='t2' AND policy_version=1")
    check("M1-12: freeze sets frozen_at", cur.fetchone()[0] is True)
    fails_with(cur,
               "INSERT INTO thresholds (policy_name, policy_version, signal, "
               "band_no, lo, hi, action) VALUES "
               "('t2',1,'intent',2,0.1,0.2,'pass')",
               (), "draft parent", "M1-12: insert after freeze rejected")
    fails_with(cur,
               "UPDATE v13_route_policies SET state='draft' "
               "WHERE policy_name='t2' AND policy_version=1",
               (), "draft->frozen", "M1-12: unfreeze rejected")
    fails_with(cur,
               "UPDATE v13_route_policies SET policy_name='x' "
               "WHERE policy_name='t2' AND policy_version=1",
               (), "immutable", "M1-12: rename key rejected")
    fails_with(cur,
               "DELETE FROM v13_route_policies WHERE policy_name='t2'",
               (), "append-only", "M1-12: DELETE policy rejected")
    fails_with(cur,
               "INSERT INTO sessions (session_id, route_policy_name, "
               "route_policy_version) VALUES (%s, 'tnew', 1)",
               (u(),), "frozen", "M1-12: INSERT session draft policy rejected")
    fails_with(cur,
               "INSERT INTO sessions (session_id, route_policy_name, "
               "route_policy_version) VALUES (%s, 'nope', 1)",
               (u(),), "frozen", "M1-12: INSERT session missing policy rejected")
    sid12 = new_session(cur, policy=("t2", 1))
    cur.execute("SELECT route_policy_name, route_policy_version FROM sessions "
                "WHERE session_id=%s", (sid12,))
    check("M1-12: INSERT session frozen ok", cur.fetchone() == ("t2", 1))
    fails_with(cur,
               "UPDATE sessions SET route_policy_version=1, "
               "route_policy_name='tnew' WHERE session_id=%s",
               (sid12,), "frozen", "M1-12: UPDATE session to draft rejected")
    cur.execute("UPDATE sessions SET status='waiting' WHERE session_id=%s", (sid12,))
    cur.execute("SELECT status FROM sessions WHERE session_id=%s", (sid12,))
    check("M1-12: UPDATE status does not trip policy guard",
          cur.fetchone()[0] == "waiting")

    # concurrent INSERT vs freeze
    conn.commit()
    cur.execute("INSERT INTO v13_route_policies (policy_name, policy_version) "
                "VALUES ('tlock', 1)")
    conn.commit()
    ca_conn = psycopg2.connect(server.get_uri(DB))
    cb_conn = psycopg2.connect(server.get_uri(DB))
    ca_conn.autocommit = False
    cb_conn.autocommit = False
    cA, cB = ca_conn.cursor(), cb_conn.cursor()
    cA.execute(
        "INSERT INTO thresholds (policy_name, policy_version, signal, "
        "band_no, lo, hi, action) VALUES "
        "('tlock',1,'intent',1,0.1,0.5,'pass')")
    cB.execute("SET lock_timeout = '500ms'")
    blocked = False
    try:
        cB.execute("UPDATE v13_route_policies SET state='frozen' "
                   "WHERE policy_name='tlock' AND policy_version=1")
    except psycopg2.Error as exc:
        blocked = "lock" in str(exc).lower() or getattr(exc, "pgcode", "") == "55P03"
        check("M1-12: B freeze blocked on A insert", blocked, str(exc).splitlines()[0])
        cb_conn.rollback()
    else:
        check("M1-12: B freeze blocked on A insert", False, "B did not wait")
    ca_conn.commit()
    cB.execute("UPDATE v13_route_policies SET state='frozen' "
               "WHERE policy_name='tlock' AND policy_version=1")
    cb_conn.commit()
    cur.execute("SELECT count(*) FROM thresholds WHERE policy_name='tlock'")
    check("M1-12: frozen version contains A band", cur.fetchone()[0] == 1)
    fails_with(cur,
               "INSERT INTO thresholds (policy_name, policy_version, signal, "
               "band_no, lo, hi, action) VALUES "
               "('tlock',1,'intent',2,0.5,'Infinity','pass')",
               (), "draft parent", "M1-12: insert after concurrent freeze rejected")
    ca_conn.close()
    cb_conn.close()

    # reverse: freeze first then insert
    cur.execute("INSERT INTO v13_route_policies (policy_name, policy_version) "
                "VALUES ('tlock2', 1)")
    conn.commit()
    cb_conn = psycopg2.connect(server.get_uri(DB))
    cb_conn.autocommit = False
    cB = cb_conn.cursor()
    cB.execute("UPDATE v13_route_policies SET state='frozen' "
               "WHERE policy_name='tlock2' AND policy_version=1")
    cb_conn.commit()
    cb_conn.close()
    fails_with(cur,
               "INSERT INTO thresholds (policy_name, policy_version, signal, "
               "band_no, lo, hi, action) VALUES "
               "('tlock2',1,'intent',1,0.1,0.5,'pass')",
               (), "draft parent", "M1-12: reverse freeze-then-insert rejected")

    # --- M1-13 tools revision monotonic + DDL event trigger -------------------
    cur.execute("SELECT revision, candidate_generation_revision FROM v13_tools_meta")
    r0, g0 = cur.fetchone()
    cur.execute(
        "CREATE FUNCTION v13_test_ddl_fn(uuid, jsonb) RETURNS jsonb "
        "LANGUAGE sql STABLE AS $$ SELECT '{}'::jsonb $$")
    cur.execute(
        "INSERT INTO tools (name, description, kind, handler, param_spec) "
        "VALUES ('ddl_probe', 'Throwaway ddl probe tool.', 'sql', "
        "'v13_test_ddl_fn', '{}'::jsonb)")
    cur.execute("SELECT revision FROM v13_tools_meta")
    r = cur.fetchone()[0]
    check("M1-13: INSERT tool bumps revision", r >= r0 + 1, (r0, r))
    r_ins = r
    cur.execute("UPDATE tools SET kind='tool', handler='worker:x' WHERE name='ddl_probe'")
    # kind tool: guard skips sql handler check; then set back
    cur.execute("SELECT revision FROM v13_tools_meta")
    r = cur.fetchone()[0]
    check("M1-13: UPDATE kind bumps", r >= r_ins + 1, r)
    cur.execute("UPDATE tools SET kind='sql', handler='v13_test_ddl_fn', enabled=true "
                "WHERE name='ddl_probe'")
    cur.execute("UPDATE tools SET handler='v13_tool_session_stats' WHERE name='ddl_probe'")
    cur.execute("SELECT revision FROM v13_tools_meta")
    r_h = cur.fetchone()[0]
    check("M1-13: UPDATE handler bumps", r_h > r, r_h)
    cur.execute("UPDATE tools SET param_spec='{\"n\":{\"question\":\"N?\","
                "\"stated\":\"S?\",\"options\":{\"a\":\"A\"}}}'::jsonb "
                "WHERE name='ddl_probe'")
    cur.execute("SELECT revision FROM v13_tools_meta")
    r_p = cur.fetchone()[0]
    check("M1-13: UPDATE param_spec bumps", r_p > r_h, r_p)
    cur.execute("UPDATE tools SET enabled=false WHERE name='ddl_probe'")
    cur.execute("SELECT revision FROM v13_tools_meta")
    r_e = cur.fetchone()[0]
    check("M1-13: UPDATE enabled bumps", r_e > r_p, r_e)
    cur.execute("DELETE FROM tools WHERE name='ddl_probe'")
    cur.execute("SELECT revision FROM v13_tools_meta")
    r_d = cur.fetchone()[0]
    check("M1-13: DELETE bumps", r_d > r_e, r_d)

    # recreate for DDL tests
    cur.execute(
        "INSERT INTO tools (name, description, kind, handler, param_spec, enabled) "
        "VALUES ('ddl_probe', 'Throwaway ddl probe tool.', 'sql', "
        "'v13_test_ddl_fn', '{}'::jsonb, true)")
    cur.execute("SELECT revision, candidate_generation_revision FROM v13_tools_meta")
    r_ddl0, g_ddl0 = cur.fetchone()
    cur.execute(
        "CREATE OR REPLACE FUNCTION v13_test_ddl_fn(uuid, jsonb) RETURNS jsonb "
        "LANGUAGE sql STABLE AS $$ SELECT jsonb_build_object('x',1) $$")
    cur.execute("SELECT revision FROM v13_tools_meta")
    r = cur.fetchone()[0]
    check("M1-13: OR REPLACE body bumps >=+1", r >= r_ddl0 + 1, (r_ddl0, r))
    r_or = r
    cur.execute("ALTER FUNCTION v13_test_ddl_fn(uuid, jsonb) VOLATILE")
    cur.execute("SELECT revision FROM v13_tools_meta")
    r = cur.fetchone()[0]
    check("M1-13: ALTER FUNCTION VOLATILE bumps", r >= r_or + 1, r)
    cur.execute("ALTER FUNCTION v13_test_ddl_fn(uuid, jsonb) STABLE")
    r_alt = r
    cur.execute("ALTER ROUTINE v13_test_ddl_fn(uuid, jsonb) VOLATILE")
    cur.execute("SELECT revision FROM v13_tools_meta")
    r = cur.fetchone()[0]
    check("M1-13: ALTER ROUTINE VOLATILE bumps", r >= r_alt + 1, r)
    cur.execute("ALTER ROUTINE v13_test_ddl_fn(uuid, jsonb) STABLE")
    r_before_drop = r
    cur.execute("DROP FUNCTION v13_test_ddl_fn(uuid, jsonb)")
    cur.execute("SELECT revision FROM v13_tools_meta")
    r = cur.fetchone()[0]
    check("M1-13: DROP FUNCTION bumps (sql_drop path)", r >= r_before_drop + 1, r)

    # Recreate handler after DROP so later cgr/independence tests have a live fn.
    cur.execute(
        "CREATE FUNCTION v13_test_ddl_fn(uuid, jsonb) RETURNS jsonb "
        "LANGUAGE sql STABLE AS $$ SELECT '{}'::jsonb $$")
    cur.execute("UPDATE tools SET handler='v13_test_ddl_fn', kind='sql', enabled=true "
                "WHERE name='ddl_probe'")
    cur.execute("SELECT revision FROM v13_tools_meta")
    r_before_routine = cur.fetchone()[0]
    cur.execute("SAVEPOINT sp_routine")
    try:
        cur.execute("CREATE OR REPLACE ROUTINE v13_test_ddl_fn(uuid, jsonb) "
                    "LANGUAGE sql AS $$ SELECT '{}'::jsonb $$")
        check("M1-13: CREATE OR REPLACE ROUTINE syntax rejected", False, "engine accepted")
    except psycopg2.Error as exc:
        check("M1-13: CREATE OR REPLACE ROUTINE syntax rejected",
              "syntax error" in str(exc).lower() and "routine" in str(exc).lower(),
              str(exc).splitlines()[0])
        cur.execute("ROLLBACK TO SAVEPOINT sp_routine")
    cur.execute("SELECT revision FROM v13_tools_meta")
    check("M1-13: ROUTINE spelling leaves revision unchanged",
          cur.fetchone()[0] == r_before_routine)

    cur.execute("SELECT revision, candidate_generation_revision FROM v13_tools_meta")
    r_u, g_u = cur.fetchone()
    cur.execute(
        "CREATE FUNCTION v13_unrelated_fn() RETURNS int LANGUAGE sql AS $$ SELECT 1 $$")
    cur.execute("SELECT revision, candidate_generation_revision FROM v13_tools_meta")
    r2, g2 = cur.fetchone()
    check("M1-13: unrelated CREATE leaves both keys", r2 == r_u and g2 == g_u, (r2, g2))
    cur.execute("DROP FUNCTION v13_unrelated_fn()")
    cur.execute("SELECT revision, candidate_generation_revision FROM v13_tools_meta")
    r3, g3 = cur.fetchone()
    check("M1-13: unrelated DROP leaves both keys", r3 == r_u and g3 == g_u, (r3, g3))

    # cgr independence
    cur.execute("SELECT revision, candidate_generation_revision FROM v13_tools_meta")
    rr, gg = cur.fetchone()
    cur.execute("UPDATE tools SET description='Throwaway ddl probe tool x.' "
                "WHERE name='ddl_probe'")
    cur.execute("SELECT revision, candidate_generation_revision FROM v13_tools_meta")
    rr2, gg2 = cur.fetchone()
    check("M1-13: tools DML bumps revision not cgr", rr2 > rr and gg2 == gg, (rr2, gg2))
    cur.execute(
        "CREATE OR REPLACE FUNCTION v13_test_ddl_fn(uuid, jsonb) RETURNS jsonb "
        "LANGUAGE sql STABLE AS $$ SELECT jsonb_build_object('y',1) $$")
    cur.execute("SELECT revision, candidate_generation_revision FROM v13_tools_meta")
    rr3, gg3 = cur.fetchone()
    check("M1-13: handler DDL bumps revision not cgr", rr3 > rr2 and gg3 == gg, (rr3, gg3))

    cur.execute("DELETE FROM tools WHERE name='ddl_probe'")
    cur.execute("DROP FUNCTION IF EXISTS v13_test_ddl_fn(uuid, jsonb)")

    # --- M1-14 tools dual guards ----------------------------------------------
    fails_with(cur,
               "INSERT INTO tools (name, description, kind, handler) "
               "VALUES ('a::b', 'A tool.', 'tool', 'worker:x')",
               (), '::', "M1-14: name with :: rejected")
    fails_with(cur,
               "INSERT INTO tools (name, description, kind, handler) "
               "VALUES ('', 'A tool.', 'tool', 'worker:x')",
               (), "non-empty", "M1-14: empty name rejected")
    fails_with(cur,
               "INSERT INTO tools (name, description, kind, handler, param_spec) "
               "VALUES ('tkey', 'A tool.', 'tool', 'worker:x', "
               "'{\"x::y\":{\"question\":\"Q\",\"stated\":\"S\","
               "\"options\":{\"a\":\"A\"}}}'::jsonb)",
               (), '::', "M1-14: param key with :: rejected")
    fails_with(cur,
               "INSERT INTO tools (name, description, kind, handler) "
               "VALUES ('ghost', 'A sql tool.', 'sql', 'no_such_fn')",
               (), "not found", "M1-14: missing handler rejected")
    cur.execute(
        "CREATE FUNCTION v13_vol_fn(uuid, jsonb) RETURNS jsonb "
        "LANGUAGE plpgsql VOLATILE AS $$ BEGIN RETURN '{}'::jsonb; END $$")
    fails_with(cur,
               "INSERT INTO tools (name, description, kind, handler) "
               "VALUES ('vol', 'A sql tool.', 'sql', 'v13_vol_fn')",
               (), "immutable/stable", "M1-14: VOLATILE handler rejected")
    cur.execute(
        "CREATE FUNCTION v13_onearg(uuid) RETURNS jsonb "
        "LANGUAGE sql STABLE AS $$ SELECT '{}'::jsonb $$")
    fails_with(cur,
               "INSERT INTO tools (name, description, kind, handler) "
               "VALUES ('onearg', 'A sql tool.', 'sql', 'v13_onearg')",
               (), "not found", "M1-14: wrong signature rejected")
    cur.execute(
        "CREATE FUNCTION v13_priv_fn(uuid, jsonb) RETURNS jsonb "
        "LANGUAGE sql STABLE AS $$ SELECT '{}'::jsonb $$")
    cur.execute("REVOKE EXECUTE ON FUNCTION v13_priv_fn(uuid, jsonb) FROM PUBLIC")
    cur.execute("REVOKE EXECUTE ON FUNCTION v13_priv_fn(uuid, jsonb) FROM v13_route")
    fails_with(cur,
               "INSERT INTO tools (name, description, kind, handler) "
               "VALUES ('priv', 'A sql tool.', 'sql', 'v13_priv_fn')",
               (), "executable", "M1-14: no EXECUTE for route rejected")
    cur.execute("CREATE SCHEMA IF NOT EXISTS other")
    cur.execute(
        "CREATE FUNCTION other.v13_priv_fn(uuid, jsonb) RETURNS jsonb "
        "LANGUAGE sql STABLE AS $$ SELECT '{}'::jsonb $$")
    # two schemas same proname (uuid,jsonb) — v13_priv_fn in public + other
    # but public one has no route EXECUTE; count of matching proname+args
    # still 2. Insert uses proname match count.
    fails_with(cur,
               "INSERT INTO tools (name, description, kind, handler) "
               "VALUES ('ambig', 'A sql tool.', 'sql', 'v13_priv_fn')",
               (), "ambiguous", "M1-14: cross-schema ambiguous rejected")
    cur.execute("UPDATE tools SET description = "
                "'Answer questions about this conversation itself: "
                "message counts, pending effects, session status.' "
                "WHERE name='session_stats'")
    cur.execute("SELECT description LIKE 'Answer questions%' FROM tools "
                "WHERE name='session_stats'")
    check("M1-14: legal sql handler description update ok", cur.fetchone()[0] is True)
    cur.execute(
        "INSERT INTO tools (name, description, kind, handler) "
        "VALUES ('email2', 'Send mail.', 'tool', 'worker:send')")
    cur.execute("SELECT kind FROM tools WHERE name='email2'")
    check("M1-14: kind=tool skips handler check", cur.fetchone()[0] == "tool")

    # disabled isolation
    cur.execute(
        "CREATE FUNCTION v13_drop_fn(uuid, jsonb) RETURNS jsonb "
        "LANGUAGE sql STABLE AS $$ SELECT '{}'::jsonb $$")
    cur.execute(
        "INSERT INTO tools (name, description, kind, handler, enabled) "
        "VALUES ('dropme', 'Throwaway.', 'sql', 'v13_drop_fn', true)")
    cur.execute("DROP FUNCTION v13_drop_fn(uuid, jsonb)")
    cur.execute("UPDATE tools SET enabled=false WHERE name='dropme'")
    cur.execute("SELECT enabled FROM tools WHERE name='dropme'")
    check("M1-14: disable after DROP handler ok", cur.fetchone()[0] is False)
    fails_with(cur,
               "UPDATE tools SET enabled=true WHERE name='dropme'",
               (), "not found", "M1-14: re-enable without handler rejected")
    cur.execute(
        "INSERT INTO tools (name, description, kind, handler, enabled) "
        "VALUES ('sick', 'Disabled sick.', 'sql', 'nope_fn', false)")
    cur.execute("SELECT enabled, handler FROM tools WHERE name='sick'")
    en, hd = cur.fetchone()
    check("M1-14: disabled sql missing handler insert ok",
          en is False and hd == "nope_fn", (en, hd))

    cur.execute("SELECT revision FROM v13_tools_meta")
    r_before_bad = cur.fetchone()[0]
    cur.execute("SAVEPOINT sp_rev")
    try:
        cur.execute(
            "INSERT INTO tools (name, description, kind, handler) "
            "VALUES ('a::b2', 'A tool.', 'tool', 'worker:x')")
        check("M1-14: rejected write should not succeed", False)
    except psycopg2.Error:
        cur.execute("ROLLBACK TO SAVEPOINT sp_rev")
    cur.execute("SELECT revision FROM v13_tools_meta")
    check("M1-14: rejected write leaves revision",
          cur.fetchone()[0] == r_before_bad)

    cur.execute("DROP FUNCTION IF EXISTS v13_vol_fn(uuid, jsonb)")
    cur.execute("DROP FUNCTION IF EXISTS v13_onearg(uuid)")
    cur.execute("DROP FUNCTION IF EXISTS v13_priv_fn(uuid, jsonb)")
    cur.execute("DROP FUNCTION IF EXISTS other.v13_priv_fn(uuid, jsonb)")
    cur.execute("DELETE FROM tools WHERE name IN ('email2','dropme','sick')")

    conn.commit()
    conn.close()
    print("[M1 schema] ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
