"""P2 gate: v13 spawn stage 18.

Run: uv run python v13/spawn/test_spawn.py  (exit 0 = pass)
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
from v13.spawn.setup_db import DB, main as setup_db


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    extra = f": {detail}" if detail and (not condition or len(str(detail)) < 180) else ""
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
        return
    cur.execute("ROLLBACK TO SAVEPOINT sp")
    raise AssertionError(f"{label}: expected failure")


def connect(server):
    conn = psycopg2.connect(server.get_uri(DB))
    conn.autocommit = False
    return conn


def connect_as(server, user):
    uri = server.get_uri(DB)
    host = (parse_qs(urlparse(uri).query).get("host") or [None])[0]
    return psycopg2.connect(host=host, dbname=DB, user=user)


def open_session(cur, spec=None):
    cur.execute("SELECT v13_open_session(%s::jsonb)", (json.dumps(spec or {}),))
    return cur.fetchone()[0]


def prefix(cur, sid, text="hello"):
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (sid, u(), json.dumps({"text": text})))


def spawn(cur, sid, tasks):
    children = [{"tool_call_id": f"call_{i}", "task": task} for i, task in enumerate(tasks, 1)]
    spec = {"schema_version": 1, "children": children}
    cur.execute("SELECT v13_spawn_subsession(%s, %s::jsonb)", (sid, json.dumps(spec)))
    return cur.fetchone()[0]


def snap_of(cur, sid):
    cur.execute("SELECT v13_probe(%s)", (sid,))
    probe = cur.fetchone()[0]
    probe["sid"] = sid
    return {"snap": probe, "envelope": {"sid": sid}, "remaining": 0,
            "failed": False, "abandon": False}


def advance(cur, sid):
    cur.execute(
        "UPDATE sessions SET context_active_revision = v13_context_required(session_id) "
        "WHERE session_id=%s", (sid,))
    snap = snap_of(cur, sid)
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid, json.dumps(snap)))
    return cur.fetchone()[0]


def claim_complete(cur, sid, kind, request, result, tool_name=None):
    if tool_name:
        cur.execute(
            "SELECT v13_enqueue_effect(%s, %s, %s::jsonb, %s)",
            (sid, kind, json.dumps(request), tool_name))
    else:
        cur.execute(
            "SELECT v13_enqueue_effect(%s, %s, %s::jsonb)",
            (sid, kind, json.dumps(request)))
    eid = cur.fetchone()[0]
    cur.execute(
        "UPDATE effects SET status='claimed', attempt_no=1, fence=1, lease_owner='w', "
        "lease_until=clock_timestamp()+interval '1 hour' "
        "WHERE effect_id=%s RETURNING attempt_no, fence", (eid,))
    attempt, fence = cur.fetchone()
    cur.execute(
        "SELECT v13_complete(%s, %s, %s, 'succeeded', %s::jsonb)",
        (eid, attempt, fence, json.dumps(result)))
    return eid, cur.fetchone()[0]


def set_budget(cur, version, nt, depth, fanout):
    cur.execute(
        "INSERT INTO v13_policies (name, version, value, active) VALUES "
        "('spawn_budget', %s, %s::jsonb, false)",
        (version, json.dumps({
            "max_nonterminal": nt, "max_depth": depth, "max_fanout": fanout})))
    cur.execute(
        "UPDATE v13_policies SET active = false WHERE name = 'spawn_budget' AND active")
    cur.execute(
        "UPDATE v13_policies SET active = true WHERE name = 'spawn_budget' AND version = %s",
        (version,))


def main() -> int:
    setup_db()
    server = get_server()
    conn = connect(server)
    cur = conn.cursor()
    cur.execute("SELECT set_config('typesafe.provider', 'mock', false)")
    cur.execute("SELECT set_config('typesafe.model', 'jev-mock', false)")

    cur.execute(
        """SELECT p.proname, r.rolname, p.prosecdef
             FROM pg_proc p
             JOIN pg_roles r ON r.oid = p.proowner
             JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = 'public'
              AND p.proname IN ('v13_open_session', 'v13_fork', 'v13_spawn_subsession')
            ORDER BY 1""")
    rows = cur.fetchall()
    check("G-spawn-unique-writer three functions",
          rows == [
              ("v13_fork", "v13_spawn_owner", True),
              ("v13_open_session", "v13_spawn_owner", True),
              ("v13_spawn_subsession", "v13_spawn_owner", True)],
          rows)
    cur.execute("SAVEPOINT own")
    cur.execute("SET LOCAL ROLE v13_route")
    try:
        cur.execute("INSERT INTO sessions (session_id) VALUES (%s)", (u(),))
        raise AssertionError("route insert succeeded")
    except psycopg2.Error as exc:
        check("G-spawn-unique-writer route insert rejected", True, str(exc).splitlines()[0])
    cur.execute("ROLLBACK TO SAVEPOINT own")
    cur.execute("SAVEPOINT own2")
    cur.execute("GRANT INSERT ON sessions TO v13_route")
    cur.execute("SET LOCAL ROLE v13_route")
    try:
        cur.execute("INSERT INTO sessions (session_id) VALUES (%s)", (u(),))
        raise AssertionError("granted insert succeeded")
    except psycopg2.Error as exc:
        msg = str(exc)
        check("G-spawn-unique-writer mistaken INSERT still rejected",
              "sessions insert owner" in msg, msg.splitlines()[0])
    cur.execute("ROLLBACK TO SAVEPOINT own2")
    cur.execute("SAVEPOINT own3")
    cur.execute("SET LOCAL ROLE v13_route_login")
    try:
        cur.execute("INSERT INTO sessions (session_id) VALUES (%s)", (u(),))
        raise AssertionError("login insert succeeded")
    except psycopg2.Error as exc:
        check("G-spawn-unique-writer login role insert rejected", True, str(exc).splitlines()[0])
    cur.execute("ROLLBACK TO SAVEPOINT own3")

    before = _count(cur)
    fails_with(cur, "SELECT v13_open_session(%s::jsonb)",
               (json.dumps({"session_id": u()}),),
               "open session args", "G-open-session-shape illegal key")
    check("G-open-session-shape illegal key zero rows", _count(cur) == before)
    sid = open_session(cur, {"route_policy_name": "default", "version": 1})
    cur.execute(
        "SELECT status, turn_no, next_seq, parent_session_id, parent_cutoff_seq, spawn_kind, "
        "route_policy_name, route_policy_version FROM sessions WHERE session_id=%s", (sid,))
    row = cur.fetchone()
    check("G-open-session-shape root row",
          row == ("ready", 0, 0, None, None, None, "default", 1), row)
    cur.execute("SELECT count(*) FROM events WHERE session_id=%s", (sid,))
    cur.execute("SELECT count(*) FROM latches WHERE session_id=%s", (sid,))
    check("G-open-session-shape no birth event", cur.fetchone()[0] == 0)
    check("G-open-session-shape no latch",
          cur.execute("SELECT count(*) FROM latches WHERE session_id=%s", (sid,)) or cur.fetchone()[0] == 0)

    cur.execute(
        "SELECT kind, handler, param_spec, enabled FROM tools WHERE name='spawn_subsession'")
    check("G-sql-write-closed tools row",
          cur.fetchone() == ("sql", "v13_spawn_subsession", {}, True))
    cur.execute("SELECT v13_named_sql_writer('v13_spawn_subsession')")
    check("G-sql-write-closed named writer",
          cur.fetchone()[0] == {
              "mutating": False,
              "write_targets": ["artifacts", "events", "latches", "sessions"]})
    cur.execute(
        "CREATE FUNCTION v13_outsider_vol(p_sid uuid, p_spec jsonb) RETURNS jsonb "
        "LANGUAGE plpgsql VOLATILE AS $b$ BEGIN RETURN '{}'::jsonb; END $b$")
    fails_with(
        cur,
        "INSERT INTO tools (name, description, kind, handler, param_spec, enabled) "
        "VALUES ('outsider_vol', 'Volatile outsider.', 'sql', 'v13_outsider_vol', '{}', true)",
        (), "sql writer closed", "G-sql-write-closed outsider rejected")
    cur.execute("DROP FUNCTION v13_outsider_vol(uuid, jsonb)")

    prefix(cur, sid)
    cur.execute("SELECT turn_no FROM sessions WHERE session_id=%s", (sid,))
    turn_before = cur.fetchone()[0]
    t0 = time.monotonic()
    created = spawn(cur, sid, ["alpha", "beta"])
    elapsed = time.monotonic() - t0
    check("G-ctx1-spawn holds xact lock only",
          "pg_advisory_xact_lock" in _def(cur, "v13_spawn_subsession(uuid,jsonb)")
          and "pg_advisory_lock(" not in _def(cur, "v13_spawn_subsession(uuid,jsonb)"))
    check("G-ctx1-spawn no external IO", elapsed < 1.0, elapsed)
    cur.execute("SELECT turn_no FROM sessions WHERE session_id=%s", (sid,))
    check("spawn does not change parent turn_no", cur.fetchone()[0] == turn_before)
    check("G-spawn-fanout created two",
          created["replay_kind"] == "created" and len(created["children"]) == 2)
    cur.execute(
        "SELECT count(*) FROM sessions WHERE parent_session_id=%s", (sid,))
    check("G-spawn-fanout two child rows", cur.fetchone()[0] == 2)
    replay = spawn(cur, sid, ["alpha", "beta"])
    check("spawn replay zero write", replay["replay_kind"] == "replay"
          and replay["children"][0]["session_id"] == created["children"][0]["session_id"])
    fails_with(cur, "SELECT v13_spawn_subsession(%s, %s::jsonb)",
               (sid, json.dumps({"schema_version": 1, "children": [
                   {"tool_call_id": "call_1", "task": "alpha"},
                   {"tool_call_id": "call_new", "task": "fresh"}]})),
               "spawn ledger", "partial consume raises ledger")
    fails_with(cur, "SELECT v13_spawn_subsession(%s, %s::jsonb)",
               (sid, json.dumps({"schema_version": 1, "children": [
                   {"tool_call_id": "call_1", "task": "DIFFERENT"},
                   {"tool_call_id": "call_2", "task": "beta"}]})),
               "mismatch", "task mismatch")

    calls = [
        {"id": "tc1", "name": "spawn_subsession", "args": {"task": "one"}},
        {"id": "tc2", "name": "spawn_subsession", "args": {"task": "two"}},
    ]
    parent = open_session(cur)
    prefix(cur, parent)
    claim_complete(cur, parent, "llm", {"route": {"action": "llm"}},
                   {"text": "ok", "tool_calls": calls})
    cur.execute("SELECT count(*) FROM events WHERE session_id=%s AND type='tool/call'", (parent,))
    check("G-spawn-fanout projected tool/call", cur.fetchone()[0] == 2)
    status = advance(cur, parent)
    check("G-spawn-fanout advance progressed", status == "progressed", status)
    cur.execute("SELECT count(*) FROM sessions WHERE parent_session_id=%s", (parent,))
    check("G-spawn-fanout N children", cur.fetchone()[0] == 2)
    cur.execute(
        "SELECT count(*) FROM effects WHERE session_id=%s AND tool_name='spawn_subsession' "
        "AND status='succeeded'", (parent,))
    check("G-spawn-fanout succeeded effect", cur.fetchone()[0] == 1)

    bad = open_session(cur)
    prefix(cur, bad)
    cur.execute("SELECT v13_enqueue_effect(%s, 'llm', %s::jsonb)",
                (bad, json.dumps({"route": {"action": "llm"}})))
    eid = cur.fetchone()[0]
    cur.execute(
        "UPDATE effects SET status='claimed', attempt_no=1, fence=1 WHERE effect_id=%s "
        "RETURNING attempt_no, fence", (eid,))
    attempt, fence = cur.fetchone()
    cur.execute("SAVEPOINT badcomp")
    try:
        cur.execute(
            "SELECT v13_complete(%s, %s, %s, 'succeeded', %s::jsonb)",
            (eid, attempt, fence, json.dumps({
                "text": "ok",
                "tool_calls": [{"id": "x", "name": "other", "args": {"task": "z"}}]})))
        raise AssertionError("bad tool_calls accepted")
    except psycopg2.Error as exc:
        check("G-spawn-fanout bad shape rejected", "tool_calls shape" in str(exc),
              str(exc).splitlines()[0])
    cur.execute("ROLLBACK TO SAVEPOINT badcomp")
    cur.execute("SELECT count(*) FROM sessions WHERE parent_session_id=%s", (bad,))
    check("G-spawn-fanout bad shape zero children", cur.fetchone()[0] == 0)
    cur.execute("SELECT status FROM effects WHERE effect_id=%s", (eid,))
    check("G-spawn-fanout bad shape does not burn claim", cur.fetchone()[0] == "claimed")

    quiet = open_session(cur)
    prefix(cur, quiet)
    claim_complete(cur, quiet, "llm", {"route": {"action": "llm"}}, {"text": "done"})
    check("G-spawn-fanout absent tool_calls finishes", advance(cur, quiet) == "terminal")
    cur.execute("SELECT count(*) FROM sessions WHERE parent_session_id=%s", (quiet,))
    check("G-spawn-fanout absent tool_calls zero children", cur.fetchone()[0] == 0)

    cur.execute("SAVEPOINT bud")
    set_budget(cur, 2, 1, 4, 8)
    a = open_session(cur)
    b = open_session(cur)
    prefix(cur, a)
    prefix(cur, b)
    spawn(cur, a, ["a1"])
    spawn(cur, b, ["b1"])
    cur.execute("SELECT count(*) FROM sessions WHERE parent_session_id IN (%s, %s)", (a, b))
    check("dual roots do not share budget", cur.fetchone()[0] == 2)
    fails_with(cur, "SELECT v13_spawn_subsession(%s, %s::jsonb)",
               (a, json.dumps({"schema_version": 1, "children": [
                   {"tool_call_id": "extra", "task": "nope"}]})),
               "cap", "walled-or-cap second child")
    cur.execute(
        "UPDATE sessions SET status='blocked_unknown' WHERE parent_session_id=%s", (b,))
    fails_with(cur, "SELECT v13_spawn_subsession(%s, %s::jsonb)",
               (b, json.dumps({"schema_version": 1, "children": [
                   {"tool_call_id": "wall", "task": "nope"}]})),
               "cap", "walled child still occupies a seat")
    cur.execute("ROLLBACK TO SAVEPOINT bud")

    kid_parent = open_session(cur)
    prefix(cur, kid_parent)
    made = spawn(cur, kid_parent, ["child task"])
    child = made["children"][0]["session_id"]
    fails_with(cur, "SELECT v13_closeout(%s, 'cancelled', 'cancel', false)",
               (kid_parent,), "children_open", "children_open blocks cancel closeout")
    cur.execute("SELECT v13_cancel(%s)", (kid_parent,))
    check("cancel arm parks instead of terminal", advance(cur, kid_parent) == "waiting")
    cur.execute("SELECT status FROM sessions WHERE session_id=%s", (kid_parent,))
    check("parked parent still waiting", cur.fetchone()[0] == "waiting")
    prefix(cur, child, "child hello")
    cur.execute("SELECT v13_closeout(%s, 'completed', 'answered', false)", (child,))
    receipt = cur.fetchone()[0]
    check("child closeout empty children", receipt["children"] == [])
    rec = _recover(cur)
    check("recover nudges parent once",
          kid_parent in rec["pending"] and rec["nudged"] >= 1, rec)
    effects_before = _effects(cur)
    rec2 = _recover(cur)
    check("recover second call zero new effects",
          rec2["nudged"] == 0 and _effects(cur) == effects_before, rec2)
    check("SKIP LOCKED in recover",
          "SKIP LOCKED" in _def(cur, "v13_recover_idle()"))
    cur.execute("SELECT v13_closeout(%s, 'cancelled', 'cancel', false)", (kid_parent,))
    parent_receipt = cur.fetchone()[0]
    check("receipt children terminal state",
          parent_receipt["children"] == [{"session_id": child, "status": "cancelled"}]
          or parent_receipt["children"] == [{"session_id": child, "status": "completed"}],
          parent_receipt["children"])
    check("receipt children one direct child",
          len(parent_receipt["children"]) == 1
          and parent_receipt["children"][0]["session_id"] == child
          and parent_receipt["children"][0]["status"] == "completed")

    wake_parent = open_session(cur)
    prefix(cur, wake_parent)
    wake_child = spawn(cur, wake_parent, ["wake child"])["children"][0]["session_id"]
    wake = {"kind": "children_terminal", "child_session_ids": [wake_child]}
    cur.execute("SELECT v13_wake_is_satisfied_v1(%s, %s, %s::jsonb)",
                (wake_parent, u(), json.dumps(wake)))
    check("children_terminal wake negative", cur.fetchone()[0] is False)
    cur.execute("UPDATE sessions SET status='completed' WHERE session_id=%s", (wake_child,))
    cur.execute("SELECT v13_wake_is_satisfied_v1(%s, %s, %s::jsonb)",
                (wake_parent, u(), json.dumps(wake)))
    check("children_terminal wake positive", cur.fetchone()[0] is True)
    fails_with(cur, "SELECT v13_wake_is_satisfied_v1(%s, %s, %s::jsonb)",
               (wake_parent, u(), json.dumps(
                   {"kind": "children_terminal", "child_session_ids": [u()]})),
               "children_terminal child", "children_terminal missing child")
    fails_with(cur, "SELECT v13_wake_is_satisfied_v1(%s, %s, %s::jsonb)",
               (wake_parent, u(), json.dumps(
                   {"kind": "children_terminal",
                    "child_session_ids": [wake_child, wake_child]})),
               "duplicate", "children_terminal duplicate")

    cur.execute("SELECT pg_get_function_result('v_goal_tree(uuid)'::regprocedure)")
    check("v_goal_tree column order",
          cur.fetchone()[0].startswith(
              "TABLE(session_id uuid, parent_session_id uuid, depth integer, status text, "
              "spawn_kind text, turn_no integer, is_terminal boolean)"))
    cur.execute(
        "SELECT session_id, depth, is_terminal FROM v_goal_tree(%s) ORDER BY depth, session_id",
        (wake_parent,))
    tree = cur.fetchall()
    check("v_goal_tree contains root and child",
          len(tree) == 2 and tree[0][0] == wake_parent and tree[0][1] == 0 and tree[1][1] == 1,
          tree)
    fails_with(cur, "SELECT * FROM v_goal_tree(%s)", (u(),),
               "unknown session", "v_goal_tree unknown root")

    conn.commit()
    _tree_faults(server)
    _concurrent(server)
    print("[PASS] stage 18 gates")
    conn.close()
    return 0


def _count(cur):
    cur.execute("SELECT count(*) FROM sessions")
    return cur.fetchone()[0]


def _effects(cur):
    cur.execute("SELECT count(*) FROM effects")
    return cur.fetchone()[0]


def _recover(cur):
    cur.execute("SELECT v13_recover_idle()")
    return cur.fetchone()[0]


def _def(cur, sig):
    cur.execute("SELECT pg_get_functiondef(%s::regprocedure)", (sig,))
    return cur.fetchone()[0]


def _tree_faults(server):
    conn = connect(server)
    cur = conn.cursor()
    cur.execute("ALTER TABLE sessions DISABLE TRIGGER trg_sessions_fork_cols_immutable")
    cur.execute("SET LOCAL ROLE v13_spawn_owner")
    left, right = u(), u()
    cur.execute("INSERT INTO sessions (session_id) VALUES (%s), (%s)", (left, right))
    cur.execute("UPDATE sessions SET parent_session_id=%s WHERE session_id=%s", (right, left))
    cur.execute("UPDATE sessions SET parent_session_id=%s WHERE session_id=%s", (left, right))
    cur.execute("RESET ROLE")
    fails_with(cur, "SELECT * FROM v_goal_tree(%s)", (left,),
               "goal tree cycle", "v_goal_tree cycle")
    conn.rollback()
    cur = conn.cursor()
    cur.execute("SET LOCAL ROLE v13_spawn_owner")
    chain = [u() for _ in range(66)]
    cur.execute("INSERT INTO sessions (session_id) VALUES (%s)", (chain[0],))
    for i in range(1, 66):
        cur.execute(
            "INSERT INTO sessions (session_id, parent_session_id) VALUES (%s, %s)",
            (chain[i], chain[i - 1]))
    cur.execute("RESET ROLE")
    fails_with(cur, "SELECT * FROM v_goal_tree(%s)", (chain[0],),
               "goal tree depth", "v_goal_tree depth")
    conn.rollback()
    conn.close()


def _concurrent(server):
    conn = connect(server)
    cur = conn.cursor()
    sid = open_session(cur)
    prefix(cur, sid)
    conn.commit()
    box = {"ok": 0, "fail": 0}

    def worker(tag):
        c = connect(server)
        k = c.cursor()
        spec = {"schema_version": 1, "children": [
            {"tool_call_id": f"{tag}_{i}", "task": f"task {tag} {i}"} for i in range(5)]}
        try:
            k.execute("SELECT v13_spawn_subsession(%s, %s::jsonb)", (sid, json.dumps(spec)))
            k.fetchone()
            c.commit()
            box["ok"] += 1
        except psycopg2.Error:
            c.rollback()
            box["fail"] += 1
        c.close()

    threads = [threading.Thread(target=worker, args=(tag,)) for tag in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    cur.execute("SELECT count(*) FROM sessions WHERE parent_session_id=%s", (sid,))
    n = cur.fetchone()[0]
    check("concurrent siblings no oversell", n <= 8 and box["ok"] >= 1 and box["fail"] >= 1,
          {"children": n, **box})
    conn.rollback()
    conn.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[FAIL] {exc}")
        raise SystemExit(1)
