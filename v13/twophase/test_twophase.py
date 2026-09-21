"""M4 gate: G-ctx1 + G-ctx8 parse-phase + slow path.

Run: uv run python v13/twophase/test_twophase.py  (exit 0 = pass)
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
V13 = AGENT_ROOT / "v13"
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v13.twophase.setup_db import DB, main as setup_db


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    extra = f": {detail}" if detail and (not condition or len(str(detail)) < 120) else ""
    print(f"[{mark}] {label}{extra}")
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def u() -> str:
    return str(uuid.uuid4())


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


def connect_as(server, user):
    uri = server.get_uri(DB)
    host = (parse_qs(urlparse(uri).query).get("host") or [None])[0]
    return psycopg2.connect(host=host, dbname=DB, user=user)


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


def sql_mock(cur, sid):
    return mock_from_needed(
        cur, sid,
        intent={"type": "choice", "choice": "sql_answer",
                "probabilities": {"sql_answer": 0.9}, "confidence": 0.9},
        gate_action={"type": "noul", "noul": 0.9},
        gate_off_topic={"type": "noul", "noul": 0.1},
        risk={"type": "score", "score": 0.5, "confidence": 0.9},
        tool={"type": "choice", "choice": "session_stats",
              "probabilities": {"session_stats": 0.9}, "confidence": 0.9})


def code_lines(path: Path) -> str:
    return "\n".join(l for l in path.read_text().splitlines()
                     if not l.lstrip().startswith("--"))


def main() -> int:
    setup_db()
    server = get_server()
    conn = psycopg2.connect(server.get_uri(DB))
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute("SET typesafe.model = 'jev-latest'")

    # G-ctx1-5(b) source scan: mock_response only in tests
    for p in V13.rglob("*.sql"):
        cl = code_lines(p)
        check(f"G-ctx1-5(b): no mock_response in {p.name}",
              "mock_response" not in cl and "set_config" not in cl)

    # G-ctx1-5(a) fresh connection
    fresh = psycopg2.connect(server.get_uri(DB))
    fc = fresh.cursor()
    fc.execute("SELECT current_setting('typesafe.mock_response', true)")
    check("G-ctx1-5(a): mock_response IS NULL on fresh conn",
          fc.fetchone()[0] in (None, ""))
    fresh.close()
    readme = (ROOT / "README.md").read_text() + (V13 / "schema" / "README.md").read_text()
    check("G-ctx1-5(c): README mentions GUC not shipped to prod",
          "mock" in readme.lower() or "GUC" in readme)

    # G-ctx1-3 full hit zero ask
    sid = new_session(cur)
    append_user(cur, sid)
    mock = sql_mock(cur, sid)
    set_mock(cur, mock)
    cur.execute("SELECT v13_parse(%s)", (sid,))
    p1 = cur.fetchone()[0]
    check("G-ctx1-3: first parse asked>0", p1["asked_questions"] > 0, p1["asked_questions"])
    conn.commit()
    poison(cur)
    cur.execute("SELECT v13_parse(%s)", (sid,))
    p2 = cur.fetchone()[0]
    check("G-ctx1-3: poison reparse failed=false asked=0",
          p2["failed"] is False and p2["asked_questions"] == 0, p2)
    cur.execute("SELECT count(*) FROM decisions WHERE session_id=%s", (sid,))
    n0 = cur.fetchone()[0]
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid, json.dumps(p2)))
    adv = cur.fetchone()[0]
    check("G-ctx1-3: advance ok", adv in ("progressed", "waiting", "terminal"), adv)
    cur.execute("SELECT count(*) FROM decisions WHERE session_id=%s", (sid,))
    check("G-ctx1-3: zero new decisions", cur.fetchone()[0] == n0)

    # G-ctx1-4 concurrent parse (forced overlap)
    conn.commit()
    sid4 = new_session(cur)
    append_user(cur, sid4, "conc")
    mock4 = sql_mock(cur, sid4)
    cur.execute("SELECT v13_judgment_envelope(%s)->>'candidate_set_hash'", (sid4,))
    csh4 = cur.fetchone()[0]
    conn.commit()
    result = {}
    hold4 = psycopg2.connect(server.get_uri(DB))
    hk4 = hold4.cursor()
    hk4.execute("SELECT pg_advisory_xact_lock(v13_lock_key(%s, %s))", (sid4, csh4))

    def parse_a():
        c = psycopg2.connect(server.get_uri(DB))
        k = c.cursor()
        k.execute("SELECT pg_backend_pid()")
        result["a_pid"] = k.fetchone()[0]
        set_mock(k, mock4)
        k.execute("SELECT v13_parse(%s)", (sid4,))
        result["a"] = k.fetchone()[0]
        c.commit(); c.close()

    def parse_b():
        c = psycopg2.connect(server.get_uri(DB))
        k = c.cursor()
        k.execute("SELECT pg_backend_pid()")
        result["b_pid"] = k.fetchone()[0]
        poison(k)
        k.execute("SELECT v13_parse(%s)", (sid4,))
        result["b"] = k.fetchone()[0]
        c.commit(); c.close()

    tA = threading.Thread(target=parse_a, daemon=True)
    tB = threading.Thread(target=parse_b, daemon=True)
    tA.start()
    a_blk = wait_until_lock(cur, result, "a_pid")
    tB.start()
    b_blk = wait_until_lock(cur, result, "b_pid")
    hold4.rollback(); hold4.close()
    tA.join(15); tB.join(15)
    check("G-ctx1-4: A blocked on advisory lock", a_blk)
    check("G-ctx1-4: B blocked on advisory lock", b_blk)
    check("G-ctx1-4: B failed=false asked=0",
          result["b"]["failed"] is False and result["b"]["asked_questions"] == 0,
          result["b"])
    check("G-ctx1-4: A asked = gap", result["a"]["asked_questions"] > 0,
          result["a"]["asked_questions"])

    # G-ctx1-1 events INSERT not blocked by parse advisory lock
    sid1 = new_session(cur)
    append_user(cur, sid1)
    mock1 = sql_mock(cur, sid1)
    cur.execute("SELECT v13_judgment_envelope(%s)->>'candidate_set_hash'", (sid1,))
    csh = cur.fetchone()[0]
    conn.commit()
    cC = psycopg2.connect(server.get_uri(DB))
    kC = cC.cursor()
    kC.execute("SELECT pg_advisory_xact_lock(v13_lock_key(%s, %s))", (sid1, csh))
    blocked = {}
    parse_box = {}

    def do_parse_a():
        c = psycopg2.connect(server.get_uri(DB))
        k = c.cursor()
        k.execute("SELECT pg_backend_pid()")
        parse_box["pid"] = k.fetchone()[0]
        set_mock(k, mock1)
        try:
            k.execute("SELECT v13_parse(%s)", (sid1,))
            parse_box["out"] = k.fetchone()[0]
            c.commit()
        except Exception as exc:
            parse_box["e"] = str(exc)
        c.close()

    def do_append():
        c = psycopg2.connect(server.get_uri(DB))
        k = c.cursor()
        t0 = time.time()
        k.execute("SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
                   (sid1, u(), json.dumps({"text": "concurrent"})))
        k.execute("SELECT v13_append_event(%s, %s, 'cancel/x', '{}'::jsonb)",
                   (sid1, u()))
        blocked["dt"] = time.time() - t0
        c.commit(); c.close()

    tP = threading.Thread(target=do_parse_a)
    tP.start()
    check("G-ctx1-1: parse A blocked", wait_until_lock(cur, parse_box, "pid"))
    t = threading.Thread(target=do_append)
    t.start(); t.join(5)
    check("G-ctx1-1: append during blocked parse <5s",
          t.is_alive() is False and blocked.get("dt", 9) < 5, blocked)
    check("G-ctx1-1: A still uncommitted", "out" not in parse_box, parse_box)
    t0c = time.time()
    cctrl = psycopg2.connect(server.get_uri(DB))
    kctrl = cctrl.cursor()
    kctrl.execute("SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
                  (sid1, u(), json.dumps({"text": "ctrl"})))
    dt_ctrl = time.time() - t0c
    cctrl.commit(); cctrl.close()
    check("G-ctx1-1: control append fast", dt_ctrl < 0.5, dt_ctrl)
    cC.rollback(); cC.close()
    tP.join(10)

    # G-ctx1-2 poison advance + lock-hold probe
    sid2 = new_session(cur)
    append_user(cur, sid2)
    set_mock(cur, sql_mock(cur, sid2))
    cur.execute("SELECT v13_parse(%s)", (sid2,))
    s2 = cur.fetchone()[0]
    poison(cur)
    t0 = time.time()
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid2, json.dumps(s2)))
    r2 = cur.fetchone()[0]
    dt = time.time() - t0
    check("G-ctx1-2: poison advance succeeds", r2 in ("progressed", "waiting", "terminal"), r2)
    check("G-ctx1-2: poison advance wall <500ms", dt < 0.5, dt)

    sid2b = new_session(cur)
    append_user(cur, sid2b)
    snap2b = None
    set_mock(cur, sql_mock(cur, sid2b))
    cur.execute("SELECT v13_parse(%s)", (sid2b,))
    snap2b = cur.fetchone()[0]
    conn.commit()
    cur.execute("""
        CREATE OR REPLACE FUNCTION v13_gctx_pause() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          PERFORM pg_advisory_xact_lock(879033);
          RETURN NEW;
        END $$;
    """)
    cur.execute("DROP TRIGGER IF EXISTS trg_gctx_pause ON effects")
    cur.execute("CREATE TRIGGER trg_gctx_pause BEFORE INSERT ON effects "
                "FOR EACH ROW EXECUTE FUNCTION v13_gctx_pause()")
    conn.commit()
    hold2 = psycopg2.connect(server.get_uri(DB))
    hk2 = hold2.cursor()
    hk2.execute("SELECT pg_advisory_xact_lock(879033)")
    box2 = {}
    happ = {}

    def run_adv2():
        c = psycopg2.connect(server.get_uri(DB))
        k = c.cursor()
        k.execute("SELECT pg_backend_pid()")
        box2["pid"] = k.fetchone()[0]
        try:
            k.execute("SELECT v13_advance(%s, %s::jsonb)",
                      (sid2b, json.dumps(snap2b)))
            box2["r"] = k.fetchone()[0]
            c.commit()
        except Exception as exc:
            box2["e"] = str(exc)
        c.close()

    def run_h():
        c = psycopg2.connect(server.get_uri(DB))
        k = c.cursor()
        k.execute("SELECT pg_backend_pid()")
        happ["pid"] = k.fetchone()[0]
        t0h = time.time()
        k.execute("SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
                  (sid2b, u(), json.dumps({"text": "H"})))
        happ["dt"] = time.time() - t0h
        c.commit(); c.close()

    ta2 = threading.Thread(target=run_adv2)
    ta2.start()
    check("G-ctx1-2: advance blocked in effects INSERT",
          wait_until_lock(cur, box2, "pid"))
    th = threading.Thread(target=run_h)
    th.start()
    check("G-ctx1-2: H waits in window", wait_until_lock(cur, happ, "pid"))
    hold2.rollback(); hold2.close()
    th.join(8); ta2.join(8)
    check("G-ctx1-2: H returned after window", "dt" in happ, happ)
    cur.execute("DROP TRIGGER IF EXISTS trg_gctx_pause ON effects")
    cur.execute("DROP FUNCTION IF EXISTS v13_gctx_pause()")
    conn.commit()

    sid2c = new_session(cur)
    append_user(cur, sid2c)
    set_mock(cur, sql_mock(cur, sid2c))
    cur.execute("SELECT v13_parse(%s)", (sid2c,))
    s2c = cur.fetchone()[0]
    conn.commit()
    happc = {}

    def run_adv2c():
        c = psycopg2.connect(server.get_uri(DB))
        k = c.cursor()
        k.execute("SELECT v13_advance(%s, %s::jsonb)", (sid2c, json.dumps(s2c)))
        k.fetchone()
        c.commit(); c.close()

    def run_hc():
        c = psycopg2.connect(server.get_uri(DB))
        k = c.cursor()
        try:
            t0h = time.time()
            k.execute("SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
                      (sid2c, u(), json.dumps({"text": "fast"})))
            happc["dt"] = time.time() - t0h
            c.commit()
        except Exception as exc:
            happc["e"] = str(exc)
        c.close()

    tad = threading.Thread(target=run_adv2c, daemon=True)
    thc = threading.Thread(target=run_hc, daemon=True)
    tad.start(); thc.start()
    tad.join(10); thc.join(10)
    check("G-ctx1-2: unprobed append wait <500ms",
          happc.get("dt", 9) < 0.5, happc)

    # K3 requeue_stale
    sidk = new_session(cur)
    append_user(cur, sidk)
    cur.execute("SELECT v13_enqueue_effect(%s, 'human', %s::jsonb)",
                (sidk, json.dumps({"reason": "x"})))
    hid = cur.fetchone()[0]
    cur.execute("SELECT v13_requeue_stale()")
    rq = cur.fetchone()[0]
    check("K3: requeue has keys",
          set(rq) >= {"reclaimed_ready", "walled_unknown", "lease_exhausted",
                      "woken_ready", "walls_total"}, rq)
    cl = claim_pinned(cur, hid, worker="w", lease_ms=1)
    time.sleep(0.05)
    cur.execute("UPDATE effects SET lease_until = clock_timestamp() - interval '1s' "
                "WHERE effect_id=%s", (cl["effect_id"],))
    cur.execute("SELECT v13_requeue_stale()")
    rq2 = cur.fetchone()[0]
    check("K3: non-judge claimed -> walled_unknown", rq2["walled_unknown"] >= 1, rq2)
    cur.execute("SELECT status FROM effects WHERE effect_id=%s", (cl["effect_id"],))
    check("K3: human expired -> unknown", cur.fetchone()[0] == "unknown")

    # K5 judge reclaim + (a1') lease exhaustion
    for i in range(20):
        spec = {"p1": {"question": f"K5Q{i}?", "stated": "S?", "options": {"a": "A", "b": "B"}},
                "p2": {"question": f"K5R{i}?", "stated": "T?", "options": {"a": "A", "b": "B"}}}
        cur.execute("INSERT INTO tools (name, description, kind, handler, param_spec) "
                    "VALUES (%s,'Tool.', 'tool', 'worker:x', %s::jsonb)",
                    (f"k5_{i}", json.dumps(spec)))
    sidj = new_session(cur)
    append_user(cur, sidj)
    set_mock(cur, mock_from_needed(cur, sidj))
    cur.execute("SELECT v13_parse(%s)", (sidj,))
    pj = cur.fetchone()[0]
    check("K5: remaining>0", pj["remaining"] > 0, pj["remaining"])
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sidj, json.dumps(pj)))
    check("K5: waiting judge", cur.fetchone()[0] == "waiting")
    cur.execute("SELECT effect_id FROM effects WHERE session_id=%s AND kind='judge'",
                (sidj,))
    jid = cur.fetchone()[0]
    last_tok = None
    for i in range(3):
        cj = claim_pinned(cur, jid)
        last_tok = cj
        cur.execute("UPDATE effects SET lease_until = clock_timestamp() - interval '1s' "
                    "WHERE effect_id=%s", (jid,))
        cur.execute("SELECT v13_requeue_stale()")
        rqj = cur.fetchone()[0]
        check(f"K5: (a1) round {i+1} reclaimed_ready", rqj["reclaimed_ready"] >= 1, rqj)
        cur.execute("SELECT status, attempt_no, fence FROM effects WHERE effect_id=%s",
                    (jid,))
        st, att, fn = cur.fetchone()
        check(f"K5: (a1) round {i+1} ready attempt={i+1}",
              st == "ready" and att == i + 1, (st, att, fn))
    cur.execute("SELECT v13_complete(%s, %s, %s, 'succeeded', '{}'::jsonb)",
                (jid, last_tok["attempt_no"], last_tok["fence"]))
    check("K5: old token after (a1) stale", cur.fetchone()[0] == "stale")
    cj4 = claim_pinned(cur, jid)
    check("K5: 4th claim attempt=4", cj4["attempt_no"] == 4, cj4)
    cur.execute("UPDATE effects SET lease_until = clock_timestamp() - interval '1s' "
                "WHERE effect_id=%s", (jid,))
    cur.execute("SELECT v13_requeue_stale()")
    rq4 = cur.fetchone()[0]
    check("K5: (a1') lease_exhausted=1", rq4["lease_exhausted"] == 1, rq4)
    cur.execute("SELECT status, attempt_no, error->>'code' FROM effects "
                "WHERE effect_id=%s", (jid,))
    st4, att4, code4 = cur.fetchone()
    check("K5: (a1') failed lease_exhausted attempt=4",
          st4 == "failed" and att4 == 4 and code4 == "lease_exhausted",
          (st4, att4, code4))
    cur.execute("SELECT v13_complete(%s, %s, %s, 'succeeded', '{}'::jsonb)",
                (jid, cj4["attempt_no"], cj4["fence"]))
    check("K5: dead worker token stale", cur.fetchone()[0] == "stale")
    set_mock(cur, mock_from_needed(cur, sidj))
    cur.execute("SELECT v13_parse(%s)", (sidj,))
    pj2 = cur.fetchone()[0]
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sidj, json.dumps(pj2)))
    check("K5: settle terminal", cur.fetchone()[0] == "terminal")
    cur.execute("SELECT payload->>'reason', payload->>'attempts_exhausted' "
                "FROM events WHERE session_id=%s AND type='turn/end'", (sidj,))
    reason, exh = cur.fetchone()
    check("K5: turn/end judge_attempts",
          reason == "judge_attempts" and exh == "true", (reason, exh))
    cur.execute("SELECT status FROM sessions WHERE session_id=%s", (sidj,))
    check("K5: session failed", cur.fetchone()[0] == "failed")
    cur.execute("SELECT count(*) FILTER (WHERE type='effect_done'), "
                "count(*) FILTER (WHERE type='turn/end') "
                "FROM events WHERE session_id=%s", (sidj,))
    edk, tek = cur.fetchone()
    check("K5: effect_done 0 turn/end 1", edk == 0 and tek == 1, (edk, tek))
    for i in range(20):
        cur.execute("DELETE FROM tools WHERE name=%s", (f"k5_{i}",))

    # K4 source scan
    resolve_sql = code_lines(V13 / "resolve" / "v13_resolve.sql")
    # typesafe_ask call should live in resolve_judgments
    check("K4: typesafe_ask in resolve.sql", "typesafe_ask" in resolve_sql)
    parse_fn = resolve_sql.split("CREATE FUNCTION v13_parse")[1].split("CREATE FUNCTION")[0] \
        if "CREATE FUNCTION v13_parse" in resolve_sql else resolve_sql
    check("K4: parse has no append_event", "v13_append_event" not in parse_fn)
    core = code_lines(V13 / "schema" / "v13_core.sql")
    check("K4: typesafe_ask absent from core code", "typesafe_ask" not in core)
    adv = code_lines(V13 / "loop" / "advance.sql")
    check("K4: typesafe_ask absent from advance code", "typesafe_ask" not in adv)

    # K6 fail -> abandon via V3001 (#45b)
    sid6 = new_session(cur)
    append_user(cur, sid6)
    bad = json.dumps({"model": "x", "answers": {"intent": {"type": "choice"}}})
    set_mock(cur, bad)
    cur.execute("SELECT v13_parse(%s)", (sid6,))
    f1 = cur.fetchone()[0]
    check("K6: parse1 failed", f1["failed"] is True)
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid6, json.dumps(f1)))
    check("K6: advance1 progressed", cur.fetchone()[0] == "progressed")
    set_mock(cur, bad)
    cur.execute("SELECT v13_parse(%s)", (sid6,))
    f2 = cur.fetchone()[0]
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid6, json.dumps(f2)))
    cur.fetchone()
    set_mock(cur, bad)
    cur.execute("SELECT v13_parse(%s)", (sid6,))
    f3 = cur.fetchone()[0]
    check("K6: parse3 abandon", f3["abandon"] is True, f3)
    poison(cur)
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid6, json.dumps(f3)))
    check("K6: abandon -> waiting human", cur.fetchone()[0] == "waiting")
    cur.execute("SELECT count(*) FROM events WHERE session_id=%s AND type='resolve/failed'",
                (sid6,))
    check("K6: resolve/failed == cap", cur.fetchone()[0] == 2)
    cur.execute("SELECT count(*) FROM effects WHERE session_id=%s AND kind='human'", (sid6,))
    check("K6: one human effect", cur.fetchone()[0] == 1)
    cur.execute("SELECT request->>'reason' FROM effects "
                "WHERE session_id=%s AND kind='human'", (sid6,))
    check("K6: reason=resolve_budget", cur.fetchone()[0] == "resolve_budget")
    cur.execute("SELECT count(*) FROM effects WHERE session_id=%s "
                "AND kind IN ('judge','tool','llm')", (sid6,))
    check("K6: zero judge/tool/llm effects", cur.fetchone()[0] == 0)

    # K7 complete human -> terminal
    cur.execute("SELECT effect_id FROM effects "
                "WHERE session_id=%s AND kind='human'", (sid6,))
    he = cur.fetchone()[0]
    ck7 = claim_pinned(cur, he)
    ha, hf = ck7["attempt_no"], ck7["fence"]
    cur.execute("SELECT v13_complete(%s, %s, %s, 'succeeded', '{}'::jsonb)",
                (he, ha, hf))
    check("K7: human complete accepted", cur.fetchone()[0] == "accepted")
    set_mock(cur, json.dumps({"model": "x", "answers": {"intent": {"type": "choice"}}}))
    cur.execute("SELECT v13_parse(%s)", (sid6,))
    p7 = cur.fetchone()[0]
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid6, json.dumps(p7)))
    k7 = cur.fetchone()[0]
    check("K7: after human -> terminal", k7 == "terminal", (k7, p7.get("abandon"), p7.get("failed")))
    cur.execute("SELECT v13_complete(%s, %s, %s, 'succeeded', '{}'::jsonb)",
                (he, ha, hf))
    check("K7: replay", cur.fetchone()[0] == "replay")

    # K8 straggler
    sid8 = new_session(cur)
    last = append_user(cur, sid8, "A")
    cur.execute("SELECT v13_enqueue_effect(%s, 'llm', %s::jsonb)",
                (sid8, json.dumps({"prompt": "x"})))
    lid = cur.fetchone()[0]
    cl8 = claim_pinned(cur, lid, worker="w")
    append_user(cur, sid8, "B")  # turn B
    cur.execute("SELECT v13_complete(%s, %s, %s, 'succeeded', %s::jsonb)",
                (lid, cl8["attempt_no"], cl8["fence"], json.dumps({"text": "old"})))
    cur.fetchone()
    set_mock(cur, sql_mock(cur, sid8))
    cur.execute("SELECT v13_parse(%s)", (sid8,))
    p8 = cur.fetchone()[0]
    cur.execute("SELECT v13_route(%s, %s::jsonb)", (sid8, json.dumps(p8["envelope"])))
    rt = cur.fetchone()[0]
    check("K8: straggler does not finish", rt.get("action") != "finish", rt)
    cur.execute("SELECT v13_canonical_state(%s)::text", (sid8,))
    ctx = cur.fetchone()[0]
    check("K8: canonical omits straggler text", "old" not in ctx, ctx)

    sid8b = new_session(cur)
    seq_a8 = append_user(cur, sid8b, "A")
    append_user(cur, sid8b, "B")
    cur.execute("SELECT v13_append_event(%s, %s, 'resolve/failed', %s::jsonb)",
                (sid8b, u(), json.dumps({"origin_user_seq": seq_a8})))
    set_mock(cur, sql_mock(cur, sid8b))
    cur.execute("SELECT v13_parse(%s)", (sid8b,))
    p8b = cur.fetchone()[0]
    check("K8: old-anchor resolve/failed does not eat new turn budget",
          p8b["abandon"] is False and p8b["failed"] is False, p8b)

    sid8c = new_session(cur)
    append_user(cur, sid8c, "C")
    cur.execute("SELECT v13_enqueue_effect(%s, 'llm', %s::jsonb)",
                (sid8c, json.dumps({"prompt": "late"})))
    lidc = cur.fetchone()[0]
    clc = claim_pinned(cur, lidc, worker="w")
    cur.execute("UPDATE sessions SET status='cancelled' WHERE session_id=%s", (sid8c,))
    cur.execute("SELECT v13_complete(%s, %s, %s, 'succeeded', %s::jsonb)",
                (lidc, clc["attempt_no"], clc["fence"], json.dumps({"text": "late"})))
    cur.fetchone()
    cur.execute("SELECT count(*) FROM effects WHERE session_id=%s", (sid8c,))
    ef8 = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM events WHERE session_id=%s AND type='turn/route'",
                (sid8c,))
    rt8 = cur.fetchone()[0]
    set_mock(cur, sql_mock(cur, sid8c))
    cur.execute("SELECT v13_parse(%s)", (sid8c,))
    p8c = cur.fetchone()[0]
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid8c, json.dumps(p8c)))
    check("K8: cancelled + late complete -> terminal", cur.fetchone()[0] == "terminal")
    cur.execute("SELECT status FROM sessions WHERE session_id=%s", (sid8c,))
    check("K8: stays cancelled", cur.fetchone()[0] == "cancelled")
    cur.execute("SELECT count(*) FROM effects WHERE session_id=%s", (sid8c,))
    check("K8: zero new effects", cur.fetchone()[0] == ef8)
    cur.execute("SELECT count(*) FROM events WHERE session_id=%s AND type='turn/route'",
                (sid8c,))
    check("K8: zero new turn/route", cur.fetchone()[0] == rt8)

    # K1 kill-during-insert
    sidk1 = new_session(cur)
    append_user(cur, sidk1)
    mockk1 = sql_mock(cur, sidk1)
    cur.execute("SELECT count(*) FROM decisions WHERE session_id=%s", (sidk1,))
    base_d = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM effects WHERE session_id=%s", (sidk1,))
    base_e = cur.fetchone()[0]
    conn.commit()
    cur.execute("""
        CREATE OR REPLACE FUNCTION v13_k1_pause() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          PERFORM pg_advisory_xact_lock(879011);
          RETURN NEW;
        END $$;
    """)
    cur.execute("DROP TRIGGER IF EXISTS trg_k1_pause ON decisions")
    cur.execute("CREATE TRIGGER trg_k1_pause BEFORE INSERT ON decisions "
                "FOR EACH ROW EXECUTE FUNCTION v13_k1_pause()")
    conn.commit()
    holdk = psycopg2.connect(server.get_uri(DB))
    hkk = holdk.cursor()
    hkk.execute("SELECT pg_advisory_xact_lock(879011)")
    boxk = {}

    def run_k1():
        c = psycopg2.connect(server.get_uri(DB))
        k = c.cursor()
        k.execute("SELECT pg_backend_pid()")
        boxk["pid"] = k.fetchone()[0]
        set_mock(k, mockk1)
        try:
            k.execute("SELECT v13_parse(%s)", (sidk1,))
            boxk["out"] = k.fetchone()[0]
            c.commit()
        except Exception as exc:
            boxk["e"] = str(exc)
        try:
            c.close()
        except Exception:
            pass

    tk1 = threading.Thread(target=run_k1)
    tk1.start()
    check("K1: parse blocked in decisions INSERT",
          wait_until_lock(cur, boxk, "pid"))
    cur.execute("SELECT pg_terminate_backend(%s)", (boxk["pid"],))
    tk1.join(8)
    cur.execute("SELECT count(*) FROM decisions WHERE session_id=%s", (sidk1,))
    check("K1: zero dirty decisions", cur.fetchone()[0] == base_d)
    cur.execute("SELECT count(*) FROM effects WHERE session_id=%s", (sidk1,))
    check("K1: zero dirty effects", cur.fetchone()[0] == base_e)
    cur.execute("SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND pid=%s",
                (boxk["pid"],))
    check("K1: advisory locks gone with rollback", cur.fetchone()[0] == 0)
    holdk.rollback(); holdk.close()
    cur.execute("DROP TRIGGER IF EXISTS trg_k1_pause ON decisions")
    cur.execute("DROP FUNCTION IF EXISTS v13_k1_pause()")
    conn.commit()
    cur.execute("SELECT count(*) FROM v13_needed_judgments(%s)", (sidk1,))
    gapk = cur.fetchone()[0]
    set_mock(cur, mockk1)
    poison(cur)
    cur.execute("SELECT set_config('typesafe.mock_response', %s, true)", (mockk1,))
    cur.execute("SELECT v13_parse(%s)", (sidk1,))
    pka = cur.fetchone()[0]
    check("K1 (i-a): asked=gap", pka["asked_questions"] == gapk, (pka, gapk))
    cur.execute("SELECT v13_parse(%s)", (sidk1,))
    pkb = cur.fetchone()[0]
    check("K1 (i-b): asked=0",
          pkb["asked_questions"] == 0 and pkb["failed"] is False, pkb)
    sidk1b = new_session(cur)
    append_user(cur, sidk1b)
    badk = json.dumps({"model": "x", "answers": {"intent": {"type": "choice"}}})
    set_mock(cur, badk)
    cur.execute("SELECT v13_parse(%s)", (sidk1b,))
    pkc = cur.fetchone()[0]
    check("K1 (ii): V3001 failed=true", pkc["failed"] is True, pkc)
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sidk1b, json.dumps(pkc)))
    check("K1 (ii): advance progressed", cur.fetchone()[0] == "progressed")
    cur.execute("SELECT count(*) FROM events WHERE session_id=%s AND type='resolve/failed'",
                (sidk1b,))
    check("K1 (ii): exactly one resolve/failed", cur.fetchone()[0] == 1)

    # K2 slow-path handoff: v13_claim + resolve_login loop
    for i in range(20):
        spec = {"p1": {"question": f"Q{i}?", "stated": "S?", "options": {"a": "A", "b": "B"}},
                "p2": {"question": f"R{i}?", "stated": "T?", "options": {"a": "A", "b": "B"}}}
        cur.execute("INSERT INTO tools (name, description, kind, handler, param_spec) "
                    "VALUES (%s,'Tool.', 'tool', 'worker:x', %s::jsonb)",
                    (f"w{i}", json.dumps(spec)))
    sidk2 = new_session(cur)
    append_user(cur, sidk2)
    set_mock(cur, mock_from_needed(cur, sidk2))
    cur.execute("SELECT v13_parse(%s)", (sidk2,))
    pk2 = cur.fetchone()[0]
    check("K2: fast path 32", pk2["asked_questions"] == 32, pk2["asked_questions"])
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sidk2, json.dumps(pk2)))
    check("K2: waiting judge", cur.fetchone()[0] == "waiting")
    cur.execute("SELECT effect_id, request, idempotency_key FROM effects "
                "WHERE session_id=%s AND kind='judge'", (sidk2,))
    je, jreq, ik2 = cur.fetchone()
    check("K2: request has envelope", "envelope" in jreq or "needed" in jreq, list(jreq))
    check("K2: idempotency_key stable", bool(ik2), ik2)
    conn.commit()
    wc = connect_as(server, "v13_route_login")
    wcur = wc.cursor()
    wcur.execute(
        "UPDATE effects SET status='cancelled' "
        "WHERE status='ready' AND effect_id IS DISTINCT FROM %s", (je,))
    wcur.execute("SELECT v13_claim('worker', 60000)")
    cj2 = wcur.fetchone()[0]
    check("K2: v13_claim pinned", str(cj2["effect_id"]) == str(je), cj2)
    wc.commit()
    env = jreq.get("envelope", jreq)
    remaining = 1
    rounds = 0
    while remaining and rounds < 10:
        rc = connect_as(server, "v13_resolve_login")
        rk = rc.cursor()
        rk.execute("SET typesafe.model = 'jev-latest'")
        set_mock(rk, mock_from_needed(rk, sidk2))
        rk.execute("SELECT v13_resolve_judgments(%s::jsonb, 1)", (json.dumps(env),))
        out = rk.fetchone()[0]
        remaining = out["remaining"]
        rc.commit(); rc.close()
        wcur.execute("SELECT v13_renew_lease(%s, %s, 60000)", (je, cj2["fence"]))
        check("K2: renew true", wcur.fetchone()[0] is True)
        wc.commit()
        rounds += 1
    check("K2: drained remaining", remaining == 0, (remaining, rounds))
    wcur.execute("SELECT v13_complete(%s, %s, %s, 'succeeded', '{}'::jsonb)",
                 (je, cj2["attempt_no"], cj2["fence"]))
    check("K2: complete accepted", wcur.fetchone()[0] == "accepted")
    wc.commit()
    wcur.execute("SELECT v13_renew_lease(%s, %s, 60000)", (je, cj2["fence"] + 99))
    check("K2: renew mismatch false", wcur.fetchone()[0] is False)
    wc.close()

    sidk2f = new_session(cur)
    append_user(cur, sidk2f)
    set_mock(cur, mock_from_needed(cur, sidk2f))
    cur.execute("SELECT v13_parse(%s)", (sidk2f,))
    pkf2 = cur.fetchone()[0]
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sidk2f, json.dumps(pkf2)))
    cur.fetchone()
    cur.execute("SELECT effect_id FROM effects WHERE session_id=%s AND kind='judge'",
                (sidk2f,))
    jef = cur.fetchone()[0]
    cjf = claim_pinned(cur, jef)
    conn.commit()
    rc = connect_as(server, "v13_resolve_login")
    rk = rc.cursor()
    rk.execute("SET typesafe.model = 'jev-latest'")
    rk.execute("SELECT set_config('typesafe.mock_response', %s, true)",
               (json.dumps({"model": "x", "answers": {"intent": {"type": "choice"}}}),))
    cur.execute("SELECT request FROM effects WHERE effect_id=%s", (jef,))
    envf = cur.fetchone()[0].get("envelope")
    rk.execute("SELECT v13_resolve_judgments(%s::jsonb, 1)", (json.dumps(envf),))
    outf = rk.fetchone()[0]
    check("K2 fail half: resolve failed", outf["failed"] is True, outf)
    rc.commit(); rc.close()
    cur.execute("SELECT v13_complete(%s, %s, %s, 'failed', NULL)",
                (jef, cjf["attempt_no"], cjf["fence"]))
    check("K2 fail half: complete failed", cur.fetchone()[0] == "accepted")
    set_mock(cur, mock_from_needed(cur, sidk2f))
    cur.execute("SELECT v13_parse(%s)", (sidk2f,))
    pnr = cur.fetchone()[0]
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sidk2f, json.dumps(pnr)))
    check("K2 fail half: rehang waiting", cur.fetchone()[0] == "waiting")
    cur.execute("SELECT v13_complete(%s, %s, %s, 'succeeded', '{}'::jsonb)",
                (jef, cjf["attempt_no"], cjf["fence"]))
    check("K2 fail half: old token stale", cur.fetchone()[0] == "stale")
    for i in range(20):
        cur.execute("DELETE FROM tools WHERE name=%s", (f"w{i}",))

    set_mock(cur, sql_mock(cur, sidk2))
    cur.execute("SELECT v13_parse(%s)", (sidk2,))
    pks = cur.fetchone()[0]
    check("K2: after judge remaining=0", pks["remaining"] == 0, pks["remaining"])
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sidk2, json.dumps(pks)))
    check("K2: sql progressed", cur.fetchone()[0] == "progressed")
    cur.execute("SELECT count(*) FROM events WHERE session_id=%s AND type='tool/result'",
                (sidk2,))
    check("K2: tool/result in projection", cur.fetchone()[0] >= 1)
    set_mock(cur, mock_from_needed(
        cur, sidk2,
        intent={"type": "choice", "choice": "llm_generate",
                "probabilities": {"llm_generate": 0.9}, "confidence": 0.9},
        gate_action={"type": "noul", "noul": 0.9}))
    cur.execute("SELECT v13_parse(%s)", (sidk2,))
    pkl = cur.fetchone()[0]
    check("K2: llm parse remaining=0", pkl["remaining"] == 0, pkl["remaining"])
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sidk2, json.dumps(pkl)))
    check("K2: llm waiting", cur.fetchone()[0] == "waiting")
    cur.execute("SELECT effect_id FROM effects WHERE session_id=%s AND kind='llm' "
                "AND status='ready'", (sidk2,))
    lid2 = cur.fetchone()[0]
    cll = claim_pinned(cur, lid2)
    cur.execute("SELECT v13_complete(%s, %s, %s, 'succeeded', %s::jsonb)",
                (lid2, cll["attempt_no"], cll["fence"],
                 json.dumps({"text": "final answer"})))
    check("K2: llm complete", cur.fetchone()[0] == "accepted")
    set_mock(cur, mock_from_needed(cur, sidk2))
    cur.execute("SELECT v13_parse(%s)", (sidk2,))
    pkf = cur.fetchone()[0]
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sidk2, json.dumps(pkf)))
    check("K2: P0 finish terminal", cur.fetchone()[0] == "terminal")
    cur.execute("SELECT count(*) FROM events WHERE session_id=%s AND type='turn/end'",
                (sidk2,))
    check("K2: turn/end", cur.fetchone()[0] >= 1)

    conn.commit()
    conn.close()
    print("[M4 twophase] ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
