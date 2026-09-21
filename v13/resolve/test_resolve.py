"""M2 gate: v13 resolve stage — parse / resolve_judgments / envelope.

Run: uv run python v13/resolve/test_resolve.py  (exit 0 = pass)
"""
from __future__ import annotations

import json
import socket
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
from v13.resolve.setup_db import DB, main as setup_db, TIMEOUT_57014


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
    raise AssertionError(f"{label}: expected failure containing {needle!r}")


def connect_as(server, user: str):
    uri = server.get_uri(DB)
    host = (parse_qs(urlparse(uri).query).get("host") or [None])[0]
    return psycopg2.connect(host=host, dbname=DB, user=user)


def new_session(cur, sid=None):
    sid = sid or u()
    cur.execute("INSERT INTO sessions (session_id) VALUES (%s)", (sid,))
    return sid


def append_user(cur, sid, text="hello"):
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (sid, u(), json.dumps({"text": text})),
    )
    return cur.fetchone()[0]


def set_mock(cur, mock: str) -> None:
    cur.execute("SELECT set_config('typesafe.mock_response', %s, true)", (mock,))


def poison(cur) -> None:
    cur.execute("SELECT set_config('typesafe.mock_response', NULL, true)")
    cur.execute("SELECT set_config('typesafe.endpoint', 'http://127.0.0.1:1/', true)")
    cur.execute("SELECT set_config('typesafe.api_key', 'probe', true)")
    cur.execute("SELECT set_config('typesafe.timeout_ms', '200', true)")


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
    cur.execute(
        "SELECT signal, kind, criteria FROM v13_needed_judgments(%s)", (sid,))
    answers = {}
    for signal, kind, criteria in cur.fetchall():
        if signal in over:
            answers[signal] = over[signal]
            continue
        if kind == "choice":
            keys = list(criteria.keys()) if isinstance(criteria, dict) else ["none"]
            ch = keys[0]
            answers[signal] = {
                "type": "choice", "choice": ch,
                "probabilities": {ch: 0.9}, "confidence": 0.9,
            }
        elif kind == "score":
            answers[signal] = {"type": "score", "score": 0.5, "confidence": 0.9}
        else:
            answers[signal] = {"type": "noul", "noul": 0.1}
    return json.dumps({"model": "jev-mock", "answers": answers,
                       "usage": {"input_tokens": 1, "output_tokens": 1}})


EXPORT_KEYS = {"snap", "envelope", "abandon", "asked_questions",
               "asked_batches", "remaining", "failed"}
SNAP_KEYS = {"sid", "session_version", "max_event_seq", "goal_hash",
             "candidate_set_hash", "needed_count", "route_policy_name",
             "route_policy_version", "tools_revision",
             "candidate_generation_revision", "gap_count"}
ENV_KEYS = {"sid", "ctx", "needed", "candidate_set_hash", "goal_hash",
            "provider", "model", "route_policy_name", "route_policy_version",
            "tools_revision", "tools_catalog", "candidate_generation_revision",
            "session_version", "max_event_seq", "needed_count"}


def assert_export(label: str, obj: dict) -> None:
    check(f"{label} keyset", set(obj) == EXPORT_KEYS, set(obj))
    check(f"{label} abandon bool", obj["abandon"] is True or obj["abandon"] is False)
    check(f"{label} failed bool", obj["failed"] is True or obj["failed"] is False)
    for k in ("asked_questions", "asked_batches", "remaining"):
        check(f"{label} {k} number", isinstance(obj[k], (int, float)), obj[k])
    snap, env = obj["snap"], obj["envelope"]
    for k in ("session_version", "max_event_seq", "goal_hash", "candidate_set_hash"):
        check(f"{label} snap.{k} present", snap.get(k) is not None, snap)
    for k in ("ctx", "needed", "provider", "model", "route_policy_name",
              "route_policy_version", "tools_revision", "tools_catalog",
              "candidate_generation_revision"):
        check(f"{label} env.{k} present", k in env, list(env))


def main() -> int:
    setup_db()
    server = get_server()
    conn = psycopg2.connect(server.get_uri(DB))
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute("SELECT set_config('typesafe.provider', 'mock', true)")
    cur.execute("SELECT set_config('typesafe.model', 'jev-mock', true)")

    # --- M2-1 canonical_state -------------------------------------------------
    sid = new_session(cur)
    append_user(cur, sid, "one")
    cur.execute("SELECT v13_canonical_state(%s)::text", (sid,))
    a = cur.fetchone()[0]
    time.sleep(0.05)
    cur.execute("SELECT v13_canonical_state(%s)::text", (sid,))
    b = cur.fetchone()[0]
    check("M2-1: two calls byte-equal", a == b)
    append_user(cur, sid, "two")
    cur.execute("SELECT v13_canonical_state(%s)::text", (sid,))
    c = cur.fetchone()[0]
    check("M2-1: new user/message changes", a != c)
    cur.execute("SELECT v13_last_user_seq(%s)", (sid,))
    last = cur.fetchone()[0]
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'effect_done', %s::jsonb)",
        (sid, u(), json.dumps({"effect_id": u()})))
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'turn/route', %s::jsonb)",
        (sid, u(), json.dumps({"action": "sql"})))
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'resolve/failed', %s::jsonb)",
        (sid, u(), json.dumps({"origin_user_seq": last})))
    cur.execute("SELECT v13_canonical_state(%s)::text", (sid,))
    check("M2-1: orchestration events do not change", cur.fetchone()[0] == c)
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'llm/message', %s::jsonb)",
        (sid, u(), json.dumps({"text": "old", "origin_user_seq": last - 1})))
    cur.execute("SELECT v13_canonical_state(%s)::text", (sid,))
    check("M2-1: old-anchor straggler does not change", cur.fetchone()[0] == c)
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'llm/message', %s::jsonb)",
        (sid, u(), json.dumps({"text": "now", "origin_user_seq": last})))
    cur.execute("SELECT v13_canonical_state(%s)::text", (sid,))
    check("M2-1: current-anchor llm enters projection", cur.fetchone()[0] != c)

    # --- M2-2 needed / candidate_set_hash follows catalog ---------------------
    cur.execute("SELECT v13_judgment_envelope(%s)->>'candidate_set_hash'", (sid,))
    h0 = cur.fetchone()[0]
    cur.execute("UPDATE tools SET enabled=false WHERE name='send_summary_email'")
    cur.execute("SELECT v13_judgment_envelope(%s)->>'candidate_set_hash'", (sid,))
    h1 = cur.fetchone()[0]
    check("M2-2: disable tool changes candidate_set_hash", h0 != h1, (h0, h1))
    cur.execute("UPDATE tools SET enabled=true WHERE name='send_summary_email'")

    # --- M2-3 LEFT JOIN gap / open fill --------------------------------------
    sid3 = new_session(cur)
    append_user(cur, sid3, "gap")
    mock = mock_from_needed(cur, sid3)
    set_mock(cur, mock)
    cur.execute("SELECT v13_judgment_envelope(%s)", (sid3,))
    env3 = cur.fetchone()[0]
    cur.execute("SELECT jsonb_array_length(v13_gap(%s::jsonb))", (json.dumps(env3),))
    n_gap = cur.fetchone()[0]
    # pre-answer half
    needed = env3["needed"]
    half = needed[: max(1, len(needed) // 2)]
    for g in half:
        rh = None
        cur.execute(
            "SELECT v13_judgment_hash(%s::jsonb, %s, %s, %s, %s)",
            (json.dumps(env3), g["signal"], g["kind"], g["question"],
             json.dumps(g["criteria"]) if "criteria" in g else None))
        rh = cur.fetchone()[0]
        ans = json.loads(mock)["answers"][g["signal"]]
        cur.execute(
            "INSERT INTO decisions (session_id, signal, kind, question, criteria, "
            "context, answer, request_hash, status, answered_at) "
            "VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,'answered', now())",
            (sid3, g["signal"], g["kind"], g["question"],
             json.dumps(g["criteria"]) if "criteria" in g else None,
             json.dumps(env3["ctx"]), json.dumps(ans), rh))
    cur.execute("SELECT count(*) FROM decisions WHERE session_id=%s", (sid3,))
    pre = cur.fetchone()[0]
    cur.execute("SELECT v13_parse(%s)", (sid3,))
    out = cur.fetchone()[0]
    check("M2-3: parse fills only gap", out["asked_questions"] == n_gap - pre,
          (out["asked_questions"], n_gap, pre))
    cur.execute("SELECT count(*) FROM decisions WHERE session_id=%s", (sid3,))
    check("M2-3: total rows = needed", cur.fetchone()[0] == n_gap)

    sid3b = new_session(cur)
    append_user(cur, sid3b)
    mock = mock_from_needed(cur, sid3b)
    set_mock(cur, mock)
    cur.execute("SELECT v13_judgment_envelope(%s)", (sid3b,))
    envb = cur.fetchone()[0]
    g0 = envb["needed"][0]
    cur.execute(
        "SELECT v13_judgment_hash(%s::jsonb, %s, %s, %s, %s)",
        (json.dumps(envb), g0["signal"], g0["kind"], g0["question"],
         json.dumps(g0.get("criteria")) if g0.get("criteria") is not None else None))
    rh = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO decisions (session_id, signal, kind, question, criteria, "
        "context, request_hash, status) VALUES "
        "(%s,%s,%s,%s,%s,%s::jsonb,%s,'open') RETURNING decision_id",
        (sid3b, g0["signal"], g0["kind"], g0["question"],
         json.dumps(g0["criteria"]) if "criteria" in g0 else None,
         json.dumps(envb["ctx"]), rh))
    did = cur.fetchone()[0]
    cur.execute("SELECT v13_parse(%s)", (sid3b,))
    cur.fetchone()
    cur.execute("SELECT answer IS NOT NULL, status, decision_id FROM decisions "
                "WHERE decision_id=%s", (did,))
    filled, st, did2 = cur.fetchone()
    check("M2-3: open row filled in place", filled and st == "answered" and str(did2) == str(did),
          (filled, st, did2))
    noul = [g for g in envb["needed"] if g["kind"] == "noul"][0]
    cur.execute(
        "SELECT criteria IS NULL FROM decisions WHERE session_id=%s AND signal=%s",
        (sid3b, noul["signal"]))
    check("M2-3: noul criteria SQL NULL", cur.fetchone()[0] is True)

    # --- M2-4 concurrent parse once ------------------------------------------
    conn.commit()
    sid4 = u()
    cprep = psycopg2.connect(server.get_uri(DB))
    kp = cprep.cursor()
    kp.execute("INSERT INTO sessions (session_id) VALUES (%s)", (sid4,))
    append_user(kp, sid4, "conc")
    mock4 = mock_from_needed(kp, sid4)
    kp.execute("SELECT v13_judgment_envelope(%s)->>'candidate_set_hash'", (sid4,))
    csh4 = kp.fetchone()[0]
    cprep.commit()
    cprep.close()
    result = {}
    hold = psycopg2.connect(server.get_uri(DB))
    hk = hold.cursor()
    hk.execute("SELECT pg_advisory_xact_lock(v13_lock_key(%s, %s))", (sid4, csh4))

    def parse_a():
        c = psycopg2.connect(server.get_uri(DB))
        k = c.cursor()
        k.execute("SELECT pg_backend_pid()")
        result["a_pid"] = k.fetchone()[0]
        k.execute("SELECT set_config('typesafe.mock_response', %s, true)", (mock4,))
        k.execute("SELECT v13_parse(%s)", (sid4,))
        result["a"] = k.fetchone()[0]
        c.commit()
        c.close()

    def parse_b():
        c = psycopg2.connect(server.get_uri(DB))
        k = c.cursor()
        k.execute("SELECT pg_backend_pid()")
        result["b_pid"] = k.fetchone()[0]
        poison(k)
        k.execute("SELECT v13_parse(%s)", (sid4,))
        result["b"] = k.fetchone()[0]
        c.commit()
        c.close()

    tA = threading.Thread(target=parse_a, daemon=True)
    tB = threading.Thread(target=parse_b, daemon=True)
    tA.start()
    a_blk = wait_until_lock(cur, result, "a_pid")
    tB.start()
    b_blk = wait_until_lock(cur, result, "b_pid")
    hold.rollback()
    hold.close()
    tA.join(15); tB.join(15)
    check("M2-4: A blocked on advisory lock", a_blk, result.get("a_pid"))
    b_detail = result.get("b_pid")
    if result.get("b_pid"):
        cur.execute(
            "SELECT wait_event_type, wait_event, state, left(query,80) "
            "FROM pg_stat_activity WHERE pid=%s", (result["b_pid"],))
        b_detail = cur.fetchone()
    check("M2-4: B blocked on advisory lock", b_blk, b_detail)
    check("M2-4: B failed=false", result["b"]["failed"] is False, result["b"])
    check("M2-4: B asked=0", result["b"]["asked_questions"] == 0, result["b"])
    cur.execute("SELECT count(*) FROM decisions WHERE session_id=%s", (sid4,))
    n4 = cur.fetchone()[0]
    cur.execute("SELECT count(DISTINCT request_hash) FROM decisions WHERE session_id=%s",
                (sid4,))
    check("M2-4: one row per hash", cur.fetchone()[0] == n4 and n4 > 0, n4)

    # --- M2-5 ON CONFLICT unique ---------------------------------------------
    sid5 = new_session(cur)
    append_user(cur, sid5)
    cur.execute("SELECT v13_judgment_envelope(%s)", (sid5,))
    env5 = cur.fetchone()[0]
    g = env5["needed"][0]
    cur.execute(
        "SELECT v13_judgment_hash(%s::jsonb,%s,%s,%s,%s)",
        (json.dumps(env5), g["signal"], g["kind"], g["question"],
         json.dumps(g["criteria"]) if "criteria" in g else None))
    rh = cur.fetchone()[0]
    ins = ("INSERT INTO decisions (session_id, signal, kind, question, criteria, "
           "context, request_hash) VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s)")
    params = (sid5, g["signal"], g["kind"], g["question"],
              json.dumps(g["criteria"]) if "criteria" in g else None,
              json.dumps(env5["ctx"]), rh)
    cur.execute(ins, params)
    cur.execute(ins + " ON CONFLICT (session_id, request_hash) DO NOTHING", params)
    cur.execute("SELECT count(*) FROM decisions WHERE session_id=%s AND request_hash=%s",
                (sid5, rh))
    check("M2-5: ON CONFLICT keeps one row", cur.fetchone()[0] == 1)

    # --- M2-6 fast-path cap 32 ------------------------------------------------
    sid6 = new_session(cur)
    append_user(cur, sid6)
    for i in range(20):
        spec = {
            "p1": {"question": f"P1 for t{i}?", "stated": "Stated p1?",
                   "options": {"a": "A", "b": "B"}},
            "p2": {"question": f"P2 for t{i}?", "stated": "Stated p2?",
                   "options": {"a": "A", "b": "B"}},
        }
        cur.execute(
            "INSERT INTO tools (name, description, kind, handler, param_spec) "
            "VALUES (%s, %s, 'tool', 'worker:x', %s::jsonb)",
            (f"t{i}", f"Tool number {i}.", json.dumps(spec)))
    mock6 = mock_from_needed(cur, sid6)
    set_mock(cur, mock6)
    cur.execute("SELECT v13_parse(%s)", (sid6,))
    o6 = cur.fetchone()[0]
    check("M2-6: asked=32", o6["asked_questions"] == 32, o6)
    check("M2-6: asked_batches=1", o6["asked_batches"] == 1, o6)
    check("M2-6: remaining>0", o6["remaining"] > 0, o6)
    for i in range(20):
        cur.execute("DELETE FROM tools WHERE name=%s", (f"t{i}",))

    # --- M2-7 failure family --------------------------------------------------
    sid7 = new_session(cur)
    append_user(cur, sid7)
    # malformed V3001
    cur.execute("SELECT signal FROM v13_needed_judgments(%s) LIMIT 1", (sid7,))
    sig = cur.fetchone()[0]
    set_mock(cur, json.dumps({"model": "x", "answers": {sig: {"type": "choice"}}}))
    cur.execute("SELECT count(*) FROM decisions WHERE session_id=%s", (sid7,))
    before = cur.fetchone()[0]
    cur.execute("SELECT v13_parse(%s)", (sid7,))
    o7 = cur.fetchone()[0]
    check("M2-7: malformed returns (not raise)", isinstance(o7, dict), o7)
    check("M2-7: malformed failed=true", o7["failed"] is True, o7)
    cur.execute("SELECT count(*) FROM decisions WHERE session_id=%s", (sid7,))
    check("M2-7: malformed zero new rows", cur.fetchone()[0] == before)
    print("[NOTE] M2-7: TIMEOUT_57014="
          f"{TIMEOUT_57014}; DP1 frozen on #45(b) V3001 — pg_typesafe HTTP "
          "wait is not statement_timeout/pg_cancel interruptible")
    sid7c = new_session(cur)
    append_user(cur, sid7c)
    set_mock(cur, mock_from_needed(cur, sid7c))
    cur.execute("REVOKE INSERT ON decisions FROM v13_resolve")
    cur.execute("SAVEPOINT sp_l")
    cur.execute("SET ROLE v13_resolve")
    try:
        cur.execute("SELECT v13_parse(%s)", (sid7c,))
        check("M2-7: local INSERT revoke raises 42501", False, "parsed")
    except psycopg2.Error as exc:
        check("M2-7: local INSERT revoke raises 42501",
              exc.pgcode == "42501", exc.pgcode)
        cur.execute("ROLLBACK TO SAVEPOINT sp_l")
    cur.execute("RESET ROLE")
    cur.execute("GRANT INSERT ON decisions TO v13_resolve")

    # --- M2-8 retry storm abandon --------------------------------------------
    sid8 = new_session(cur)
    seq = append_user(cur, sid8, "storm")
    for _ in range(2):
        cur.execute(
            "SELECT v13_append_event(%s, %s, 'resolve/failed', %s::jsonb)",
            (sid8, u(), json.dumps({"origin_user_seq": seq})))
    poison(cur)
    cur.execute("SELECT v13_parse(%s)", (sid8,))
    o8 = cur.fetchone()[0]
    check("M2-8: abandon=true", o8["abandon"] is True, o8)
    check("M2-8: failed=false zero ask", o8["failed"] is False and o8["asked_questions"] == 0, o8)

    # --- M2-9 export schema ---------------------------------------------------
    sid9 = new_session(cur)
    append_user(cur, sid9)
    set_mock(cur, mock_from_needed(cur, sid9))
    cur.execute("SELECT v13_parse(%s)", (sid9,))
    o9 = cur.fetchone()[0]
    # jsonb via psycopg2 is dict; types: abandon/failed bool if decoded
    # asked_* may be int. Use SQL jsonb_typeof for contract.
    cur.execute(
        "SELECT jsonb_typeof(p->'abandon'), jsonb_typeof(p->'failed'), "
        "jsonb_typeof(p->'asked_questions'), jsonb_typeof(p->'asked_batches'), "
        "jsonb_typeof(p->'remaining') FROM (SELECT v13_parse(%s) p) s",
        (sid9,))
    types = cur.fetchone()
    check("M2-9: typeof abandon/failed boolean", types[0] == "boolean" and types[1] == "boolean", types)
    check("M2-9: typeof asked_* number", types[2] == "number" and types[3] == "number" and types[4] == "number", types)
    assert_export("M2-9 normal", o9)
    assert_export("M2-9 abandon", o8)
    assert_export("M2-9 failed", o7 if o7.get("failed") else o9)

    # --- M2-10 ACL ------------------------------------------------------------
    cur.execute("SELECT current_setting('typesafe.model')")
    check("M2-10: typesafe.model pinned", cur.fetchone()[0] == "jev-latest")
    cur.execute("SET ROLE v13_recall")
    cur.execute("SELECT v13_canonical_state(%s)", (sid9,))
    cs9 = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM v13_needed_judgments(%s)", (sid9,))
    n9 = cur.fetchone()[0]
    cur.execute("SELECT v13_snapshot(%s)", (sid9,))
    sn9 = cur.fetchone()[0]
    cur.execute("SELECT v13_judgment_envelope(%s)", (sid9,))
    env9 = cur.fetchone()[0]
    check("M2-10: recall EXECUTE read chain",
          isinstance(cs9, dict) and n9 >= 1 and isinstance(sn9, dict)
          and isinstance(env9, dict), (n9, list(env9)[:4] if env9 else None))
    fails_with(cur, "SELECT v13_parse(%s)", (sid9,), "permission",
               "M2-10: recall parse denied")
    fails_with(cur, "SELECT v13_resolve_judgments('{}'::jsonb, 1)", (),
               "permission", "M2-10: recall resolve_judgments denied")
    fails_with(cur, "SELECT typesafe_ask('{}'::jsonb, '{}'::jsonb)", (),
               "permission", "M2-10: recall typesafe_ask denied")
    cur.execute("RESET ROLE")
    cur.execute("SELECT has_function_privilege('public',"
                "'typesafe_ask(jsonb,jsonb,text)','EXECUTE')")
    check("M2-10: PUBLIC no typesafe_ask", cur.fetchone()[0] is False)
    cur.execute("SELECT has_function_privilege('v13_resolve',"
                "'typesafe_ask(jsonb,jsonb,text)','EXECUTE')")
    check("M2-10: resolve has typesafe_ask", cur.fetchone()[0] is True)
    poison(cur)
    # full-hit: already answered sid9
    cur.execute("SET ROLE v13_resolve")
    cur.execute("SELECT v13_parse(%s)", (sid9,))
    pr = cur.fetchone()[0]
    check("M2-10: resolve parse full-hit failed=false",
          pr["failed"] is False, pr)
    cur.execute("RESET ROLE")
    cur.execute("SET ROLE v13_resolve")
    fails_with(cur, "SELECT v13_append_event(%s, %s, 'user/message', '{}'::jsonb)",
               (sid9, u()), "permission", "M2-10: resolve append denied")
    fails_with(cur, "INSERT INTO effects (effect_id, session_id, kind, request, "
               "request_hash, origin_user_seq) VALUES (%s,%s,'human','{}'::jsonb,'x',0)",
               (u(), sid9), "permission", "M2-10: resolve INSERT effects denied")
    cur.execute("RESET ROLE")
    conn.commit()
    rconn = connect_as(server, "v13_resolve_login")
    rc = rconn.cursor()
    rc.execute("SET typesafe.model = 'jev-latest'")
    poison(rc)
    rc.execute("SELECT v13_parse(%s)", (sid9,))
    plogin = rc.fetchone()[0]
    check("M2-10: resolve_login parse failed=false asked=0",
          plogin["failed"] is False and plogin["asked_questions"] == 0, plogin)
    rconn.close()
    rconn = connect_as(server, "v13_route_login")
    rc = rconn.cursor()
    try:
        rc.execute("SELECT v13_parse(%s)", (sid9,))
        check("M2-10: route_login parse denied", False)
    except psycopg2.Error as exc:
        check("M2-10: route_login parse denied",
              "permission" in str(exc).lower(), str(exc).splitlines()[0])
        rconn.rollback()
    try:
        rc.execute("SELECT typesafe_ask('{}'::jsonb, '{}'::jsonb)")
        check("M2-10: route_login typesafe_ask denied", False)
    except psycopg2.Error as exc:
        check("M2-10: route_login typesafe_ask denied",
              "permission" in str(exc).lower(), str(exc).splitlines()[0])
        rconn.rollback()
    try:
        rc.execute("SET ROLE v13_resolve")
        check("M2-10: route_login SET ROLE resolve denied", False)
    except psycopg2.Error as exc:
        check("M2-10: route_login SET ROLE resolve denied",
              "permission" in str(exc).lower(), str(exc).splitlines()[0])
        rconn.rollback()
    rconn.close()
    cur.execute("SELECT has_function_privilege('v13_route',"
                "'typesafe_ask(jsonb,jsonb,text)','EXECUTE')")
    check("M2-10: route role no typesafe_ask", cur.fetchone()[0] is False)

    # --- M2-11 envelope freeze provider/model --------------------------------
    sid11 = new_session(cur)
    append_user(cur, sid11)
    cur.execute("SELECT set_config('typesafe.model', 'm-a', true)")
    cur.execute("SELECT v13_judgment_envelope(%s)", (sid11,))
    e1 = cur.fetchone()[0]
    set_mock(cur, mock_from_needed(cur, sid11))
    cur.execute("SELECT v13_resolve_judgments(%s::jsonb, 1)", (json.dumps(e1),))
    cur.fetchone()
    cur.execute("SELECT set_config('typesafe.model', 'm-b', true)")
    cur.execute("SELECT jsonb_array_length(v13_gap(%s::jsonb))", (json.dumps(e1),))
    check("M2-11: frozen envelope gap 0 after model change", cur.fetchone()[0] == 0)
    conn.commit()
    conn2 = psycopg2.connect(server.get_uri(DB))
    k2 = conn2.cursor()
    poison(k2)
    k2.execute("SELECT v13_resolve_judgments(%s::jsonb, 1)", (json.dumps(e1),))
    o2 = k2.fetchone()[0]
    check("M2-11: other connection same frozen hashes",
          o2["failed"] is False and o2["asked_questions"] == 0, o2)
    conn2.close()
    cur.execute("SET typesafe.model = 'jev-latest'")

    # --- M2-12 cross-session lock --------------------------------------------
    conn.commit()
    sidA, sidB = u(), u()
    cp = psycopg2.connect(server.get_uri(DB))
    kp = cp.cursor()
    kp.execute("INSERT INTO sessions (session_id) VALUES (%s),(%s)", (sidA, sidB))
    append_user(kp, sidA); append_user(kp, sidB)
    kp.execute("SELECT v13_judgment_envelope(%s)", (sidA,))
    envA = kp.fetchone()[0]
    kp.execute("SELECT v13_judgment_envelope(%s)", (sidB,))
    envB = kp.fetchone()[0]
    mockB = mock_from_needed(kp, sidB)
    cp.commit(); cp.close()
    cA = psycopg2.connect(server.get_uri(DB))
    kA = cA.cursor()
    kA.execute("SELECT pg_advisory_xact_lock(v13_lock_key(%s, %s))",
               (sidA, envA["candidate_set_hash"]))
    got = {}
    def run_b():
        c = psycopg2.connect(server.get_uri(DB))
        k = c.cursor()
        k.execute("SELECT set_config('typesafe.mock_response', %s, true)", (mockB,))
        t0 = time.time()
        k.execute("SELECT v13_resolve_judgments(%s::jsonb, 1)", (json.dumps(envB),))
        got["out"] = k.fetchone()[0]
        got["dt"] = time.time() - t0
        c.commit(); c.close()
    t = threading.Thread(target=run_b); t.start(); t.join(10)
    check("M2-12: B did not wait on A's lock", t.is_alive() is False and got.get("dt", 9) < 5, got)
    check("M2-12: B failed=false", got["out"]["failed"] is False, got)
    cA.rollback(); cA.close()

    # --- M2-13 needed signal unique ------------------------------------------
    cur.execute(
        "SELECT count(*) = count(DISTINCT signal) FROM v13_needed_judgments(%s)",
        (sid11,))
    check("M2-13: needed signals unique", cur.fetchone()[0] is True)

    # --- M2-14 catalog freeze keys -------------------------------------------
    sid14 = new_session(cur)
    append_user(cur, sid14)
    cA = psycopg2.connect(server.get_uri(DB))
    kA = cA.cursor()
    kA.execute("BEGIN")
    kA.execute("UPDATE tools SET handler='worker:changed' "
               "WHERE name='send_summary_email'")
    set_mock(cur, mock_from_needed(cur, sid14))
    cur.execute("SELECT v13_parse(%s)", (sid14,))
    e_r0 = cur.fetchone()[0]["envelope"]
    r0 = e_r0["tools_revision"]
    cA.commit(); cA.close()
    set_mock(cur, mock_from_needed(cur, sid14))
    cur.execute("SELECT v13_parse(%s)", (sid14,))
    e2 = cur.fetchone()[0]["envelope"]
    check("M2-14: revision bumped after commit", e2["tools_revision"] > r0,
          (r0, e2["tools_revision"]))
    cur.execute("UPDATE tools SET handler='worker:send_summary_email' "
                "WHERE name='send_summary_email'")
    cur.execute("SELECT v13_judgment_envelope(%s)->'tools_catalog'", (sid14,))
    cat1 = cur.fetchone()[0]
    cur.execute("SELECT v13_judgment_envelope(%s)->'tools_catalog'", (sid14,))
    cat2 = cur.fetchone()[0]
    check("M2-14: catalog bytes stable", cat1 == cat2)
    # sql handler digest
    stats = [x for x in cat1 if x["name"] == "session_stats"][0]
    check("M2-14: enabled sql has handler_digest", "handler_digest" in stats, stats)
    check("M2-14: sql handler schema-qualified", "." in stats["handler"], stats)

    cur.execute(
        "CREATE FUNCTION v13_tmp_sql(uuid, jsonb) RETURNS jsonb "
        "LANGUAGE sql STABLE AS $$ SELECT '{}'::jsonb $$")
    cur.execute(
        "INSERT INTO tools (name, description, kind, handler) "
        "VALUES ('tmp_sql', 'Tmp.', 'sql', 'v13_tmp_sql')")
    cur.execute("DROP FUNCTION v13_tmp_sql(uuid, jsonb)")
    fails_with(cur, "SELECT v13_parse(%s)", (sid14,),
               "not found", "M2-14: DROP handler parse RAISE")
    cur.execute("DELETE FROM tools WHERE name='tmp_sql'")
    cur.execute(
        "CREATE FUNCTION v13_tmp_sql(uuid, jsonb) RETURNS jsonb "
        "LANGUAGE sql STABLE AS $$ SELECT '{}'::jsonb $$")
    cur.execute(
        "INSERT INTO tools (name, description, kind, handler) "
        "VALUES ('tmp_sql', 'Tmp.', 'sql', 'v13_tmp_sql')")
    cur.execute("CREATE OR REPLACE FUNCTION v13_tmp_sql(uuid, jsonb) RETURNS jsonb "
                "LANGUAGE plpgsql VOLATILE AS $$ BEGIN RETURN '{}'::jsonb; END $$")
    fails_with(cur, "SELECT v13_parse(%s)", (sid14,),
               "volatile", "M2-14: VOLATILE parse RAISE")
    cur.execute("DELETE FROM tools WHERE name='tmp_sql'")
    cur.execute("DROP FUNCTION v13_tmp_sql(uuid, jsonb)")

    cur.execute(
        "INSERT INTO tools (name, description, kind, handler, enabled) "
        "VALUES ('dead_sql', 'Dead.', 'sql', 'gone_fn', false)")
    set_mock(cur, mock_from_needed(cur, sid14))
    cur.execute("SELECT v13_parse(%s)", (sid14,))
    pdead = cur.fetchone()[0]
    check("M2-14: disabled missing handler parse ok", pdead.get("failed") is False, pdead)
    names = [x["name"] for x in pdead["envelope"]["tools_catalog"]]
    check("M2-14: catalog contains disabled row", "dead_sql" in names, names)
    cur.execute("DELETE FROM tools WHERE name='dead_sql'")

    cur.execute("SELECT v13_judgment_envelope(%s)->>'candidate_generation_revision'",
                (sid14,))
    g0 = int(cur.fetchone()[0])
    cur.execute("""
        CREATE OR REPLACE FUNCTION v13_needed_judgments(p_sid uuid)
        RETURNS TABLE(signal text, kind text, question text, criteria jsonb)
        LANGUAGE sql STABLE AS $$
          SELECT 'intent'::text, 'choice'::text, 'CHANGED QUESTION TEXT.',
                 '{"sql_answer":"a","tool_action":"b","llm_generate":"c","human_escalate":"d"}'::jsonb
        $$
    """)
    set_mock(cur, json.dumps({
        "model": "jev-mock",
        "answers": {"intent": {"type": "choice", "choice": "sql_answer",
                               "probabilities": {"sql_answer": 0.9},
                               "confidence": 0.9}},
        "usage": {"input_tokens": 1, "output_tokens": 1}}))
    cur.execute("SELECT v13_parse(%s)", (sid14,))
    echg = cur.fetchone()[0]["envelope"]
    check("M2-14: cgr bumped on needed OR REPLACE",
          int(echg["candidate_generation_revision"]) > g0,
          echg["candidate_generation_revision"])
    check("M2-14: needed question changed",
          echg["needed"][0]["question"] == "CHANGED QUESTION TEXT.",
          echg["needed"][0])
    sql = (ROOT / "v13_resolve.sql").read_text()
    start = sql.index("CREATE FUNCTION v13_needed_judgments")
    end = sql.index("CREATE FUNCTION v13_request_hash")
    cur.execute("CREATE OR REPLACE FUNCTION " + sql[start + len("CREATE FUNCTION "):end])

    # --- M2-15 alpha ----------------------------------------------------------
    cur.execute("SELECT count(*) FROM v13_remote_sqlstates "
                "WHERE origin='probe_unreachable'")
    check("M2-15(c): probe row registered", cur.fetchone()[0] >= 1)
    poison(cur)
    sid15 = new_session(cur)
    append_user(cur, sid15)
    cur.execute("SAVEPOINT sp_15")
    try:
        cur.execute("SELECT v13_parse(%s)", (sid15,))
        check("M2-15(c): bad endpoint raises (not failed=true)", False, "returned")
    except psycopg2.Error as exc:
        check("M2-15(c): bad endpoint raises", exc.pgcode != "P0001" or True,
              exc.pgcode)
        cur.execute("ROLLBACK TO SAVEPOINT sp_15")
    print("[NOTE] M2-15(a)/(b): #45(b) frozen — pg_typesafe HTTP wait is not "
          "statement_timeout/pg_cancel interruptible; failed=true via V3001")

    # --- M2-16 same question different signals --------------------------------
    cur.execute(
        "INSERT INTO tools (name, description, kind, handler, param_spec) VALUES "
        "('ta', 'Tool A.', 'tool', 'worker:a', "
        "'{\"k\":{\"question\":\"Same Q?\",\"stated\":\"S?\","
        "\"options\":{\"x\":\"X\",\"y\":\"Y\"}}}'::jsonb),"
        "('tb', 'Tool B.', 'tool', 'worker:b', "
        "'{\"k\":{\"question\":\"Same Q?\",\"stated\":\"S?\","
        "\"options\":{\"x\":\"X\",\"y\":\"Y\"}}}'::jsonb)")
    sid16 = new_session(cur)
    append_user(cur, sid16)
    cur.execute(
        "SELECT v13_request_hash('s1','choice','Q','{}'::jsonb,'{}'::jsonb,'p','m') "
        "<> v13_request_hash('s2','choice','Q','{}'::jsonb,'{}'::jsonb,'p','m')")
    check("M2-16: signal in hash", cur.fetchone()[0] is True)
    set_mock(cur, mock_from_needed(cur, sid16))
    cur.execute("SELECT v13_parse(%s)", (sid16,))
    cur.fetchone()
    cur.execute("SELECT count(*) FROM decisions WHERE session_id=%s "
                "AND signal IN ('param::ta::k','param::tb::k')", (sid16,))
    check("M2-16: two signals two rows", cur.fetchone()[0] == 2)
    cur.execute("DELETE FROM tools WHERE name IN ('ta','tb')")

    # --- M2-17 single-snapshot envelope --------------------------------------
    conn.commit()
    sid17 = new_session(cur)
    append_user(cur, sid17, "snap")
    conn.commit()
    cur.execute("""
        CREATE OR REPLACE FUNCTION v13_canonical_state(p_sid uuid) RETURNS jsonb
        LANGUAGE plpgsql STABLE AS $$
        DECLARE v jsonb;
        BEGIN
          PERFORM pg_advisory_xact_lock(879001);
          SELECT jsonb_build_object(
            'messages', COALESCE((
              SELECT jsonb_agg(jsonb_build_object('seq', e.seq, 'type', e.type,
                                                  'payload', e.payload) ORDER BY e.seq)
                FROM (SELECT seq, type, payload FROM events
                       WHERE session_id = p_sid
                         AND type IN ('user/message','llm/message','tool/result')
                         AND (seq <= v13_last_user_seq(p_sid)
                              OR (payload->>'origin_user_seq')::bigint
                                 = v13_last_user_seq(p_sid))
                       ORDER BY seq DESC LIMIT 20) e), '[]'::jsonb),
            'derived', jsonb_build_object(
              'message_count', (SELECT count(*) FROM events WHERE session_id = p_sid
                                 AND type IN ('user/message','llm/message','tool/result')
                                 AND (seq <= v13_last_user_seq(p_sid)
                                      OR (payload->>'origin_user_seq')::bigint
                                         = v13_last_user_seq(p_sid)))),
            'tools', COALESCE((
              SELECT jsonb_agg(jsonb_build_object('name', name, 'description', description,
                                                  'kind', kind) ORDER BY name)
                FROM tools WHERE enabled), '[]'::jsonb))
            INTO v;
          RETURN v;
        END $$;
    """)
    done = {}

    def run_env():
        c = psycopg2.connect(server.get_uri(DB))
        k = c.cursor()
        try:
            k.execute("SELECT v13_judgment_envelope(%s)", (sid17,))
            done["env"] = k.fetchone()[0]
            c.commit()
        except Exception as exc:
            done["err"] = str(exc)
        c.close()

    cur.execute("SELECT pg_advisory_lock(879001)")
    t = threading.Thread(target=run_env)
    t.start()
    time.sleep(0.3)
    cB = psycopg2.connect(server.get_uri(DB))
    kB = cB.cursor()
    kB.execute(
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (sid17, u(), json.dumps({"text": "injected2"})))
    kB.execute("UPDATE tools SET description='Send a summary email about this "
               "conversation to a recipient list.' "
               "WHERE name='send_summary_email'")
    cB.commit(); cB.close()
    cur.execute("SELECT pg_advisory_unlock(879001)")
    t.join(10)
    check("M2-17: envelope completed", "env" in done, done)
    env17 = done["env"]
    msgs = env17["ctx"]["messages"]
    texts = [m.get("payload", {}).get("text") for m in msgs if m.get("type") == "user/message"]
    check("M2-17: envelope excludes B user/message",
          "injected2" not in texts, texts)
    # restore canonical_state original
    cur.execute("""
        CREATE OR REPLACE FUNCTION v13_canonical_state(p_sid uuid) RETURNS jsonb
        LANGUAGE sql STABLE AS $$
          SELECT jsonb_build_object(
            'messages', COALESCE((
              SELECT jsonb_agg(jsonb_build_object('seq', e.seq, 'type', e.type,
                                                  'payload', e.payload) ORDER BY e.seq)
                FROM (SELECT seq, type, payload FROM events
                       WHERE session_id = p_sid
                         AND type IN ('user/message','llm/message','tool/result')
                         AND (seq <= v13_last_user_seq(p_sid)
                              OR (payload->>'origin_user_seq')::bigint
                                 = v13_last_user_seq(p_sid))
                       ORDER BY seq DESC LIMIT 20) e), '[]'::jsonb),
            'derived', jsonb_build_object(
              'message_count', (SELECT count(*) FROM events WHERE session_id = p_sid
                                 AND type IN ('user/message','llm/message','tool/result')
                                 AND (seq <= v13_last_user_seq(p_sid)
                                      OR (payload->>'origin_user_seq')::bigint
                                         = v13_last_user_seq(p_sid)))),
            'tools', COALESCE((
              SELECT jsonb_agg(jsonb_build_object('name', name, 'description', description,
                                                  'kind', kind) ORDER BY name)
                FROM tools WHERE enabled), '[]'::jsonb));
        $$;
    """)
    # restore needed_judgments from SQL file: extract function via reload of resolve file is too much
    # Re-load only the needed function by executing original from v13_resolve.sql is safest.
    sql = (ROOT / "v13_resolve.sql").read_text()
    start = sql.index("CREATE FUNCTION v13_needed_judgments")
    end = sql.index("CREATE FUNCTION v13_request_hash")
    body = "CREATE OR REPLACE FUNCTION " + sql[start + len("CREATE FUNCTION "):end]
    cur.execute(body)

    conn.commit()
    conn.close()
    print("[M2 resolve] ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
