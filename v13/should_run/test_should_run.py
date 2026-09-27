"""Stage 26 gate: should_run projection.

Run: uv run python v13/should_run/test_should_run.py  (exit 0 = pass)
"""
from __future__ import annotations

import difflib
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

from server import get_server
from v13.load import STAGE_THROUGH
from v13.should_run.setup_db import DB, PRE, main as setup_db

N = 0
SEED = {
    "schema_version": 1,
    "gates": [
        {"id": "human_pending", "effect": "block"},
        {"id": "unknown_wall", "effect": "block"},
        {"id": "unconsumed_cancel", "effect": "block"},
        {"id": "duty_cycle", "effect": "shadow"},
    ],
}
DUTY_BLOCK = {
    "schema_version": 1,
    "gates": [
        {"id": "human_pending", "effect": "block"},
        {"id": "unknown_wall", "effect": "block"},
        {"id": "unconsumed_cancel", "effect": "block"},
        {"id": "duty_cycle", "effect": "block"},
    ],
}
FINISH = {"result_kind": "finish", "delivery_kind": "LOUD-BUT-BLIND"}
CALL = [{"id": "tc1", "name": "spawn_subsession", "args": {"task": "one"}}]


def check(label, condition, detail=""):
    global N
    N += 1
    mark = "PASS" if condition else "FAIL"
    extra = f": {detail}" if detail and (not condition or len(str(detail)) < 240) else ""
    print(f"[{mark}] {label}{extra}")
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def u():
    return str(uuid.uuid4())


def connect(server, db=DB):
    conn = psycopg2.connect(server.get_uri(db))
    conn.autocommit = False
    return conn


def q1(cur, sql, params=None):
    cur.execute(sql, params)
    row = cur.fetchone()
    return None if row is None else row[0]


def fails_with(cur, sql, params, needle, label):
    cur.execute("SAVEPOINT sp")
    try:
        cur.execute(sql, params)
    except psycopg2.Error as exc:
        msg = exc.diag.message_primary or str(exc).splitlines()[0]
        check(label, needle in msg, msg)
        cur.execute("ROLLBACK TO SAVEPOINT sp")
        return msg
    cur.execute("ROLLBACK TO SAVEPOINT sp")
    raise AssertionError(f"{label}: expected failure")


def open_session(cur, spec=None):
    return str(q1(cur, "SELECT v13_open_session(%s::jsonb)", (json.dumps(spec or {}),)))


def prefix(cur, sid, text="hello goal"):
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (sid, u(), json.dumps({"text": text})))


def snap_of(cur, sid, remaining=0, failed=False):
    cur.execute("SELECT v13_probe(%s)", (sid,))
    probe = cur.fetchone()[0]
    probe["sid"] = sid
    return {"snap": probe, "envelope": {"sid": sid}, "remaining": remaining,
            "failed": failed, "abandon": False}


def advance(cur, sid, failed=False, role=None):
    cur.execute("RESET ROLE")
    cur.execute(
        "UPDATE sessions SET context_active_revision = v13_context_required(session_id) "
        "WHERE session_id=%s", (sid,))
    snap = snap_of(cur, sid, failed=failed)
    if role:
        cur.execute(f"SET ROLE {role}")
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid, json.dumps(snap)))
    word = cur.fetchone()[0]
    if role:
        cur.execute("RESET ROLE")
    return word


def n_events(cur, sid, etype):
    return int(q1(
        cur, "SELECT count(*) FROM events WHERE session_id=%s AND type=%s", (sid, etype)))


def n_effects(cur, sid):
    return int(q1(cur, "SELECT count(*) FROM effects WHERE session_id=%s", (sid,)))


def n_children(cur, sid):
    return int(q1(cur, "SELECT count(*) FROM sessions WHERE parent_session_id=%s", (sid,)))


def status_of(cur, sid):
    return q1(cur, "SELECT status FROM sessions WHERE session_id=%s", (sid,))


def ready_claimed(cur, sid):
    return int(q1(
        cur,
        "SELECT count(*) FROM effects WHERE session_id=%s AND status IN ('ready','claimed')",
        (sid,)))


def flip_policy(cur, name, version, value):
    cur.execute(
        "INSERT INTO v13_policies (name, version, value, active) "
        "VALUES (%s, %s, %s::jsonb, false)",
        (name, version, json.dumps(value)))
    cur.execute(
        "UPDATE v13_policies SET active=false WHERE name=%s AND version<>%s",
        (name, version))
    cur.execute(
        "UPDATE v13_policies SET active=true WHERE name=%s AND version=%s",
        (name, version))


def prosrc(cur, sig):
    return q1(cur, "SELECT prosrc FROM pg_proc WHERE oid = %s::regprocedure", (sig,))


def trev(cur, sid):
    return int(q1(cur, "SELECT (v13_probe(%s)->>'tools_revision')::bigint", (sid,)))


def harness_request(ltid, index, revision):
    return {
        "tool": "harness_turn",
        "params": {},
        "handler": "worker:harness_turn",
        "tools_revision": revision,
        "logical_turn_id": ltid,
        "continuation_index": index,
    }


def enqueue(cur, sid, kind, request, tool_name=None):
    if tool_name:
        return str(q1(
            cur, "SELECT v13_enqueue_effect(%s, %s, %s::jsonb, %s)",
            (sid, kind, json.dumps(request), tool_name)))
    return str(q1(
        cur, "SELECT v13_enqueue_effect(%s, %s, %s::jsonb)",
        (sid, kind, json.dumps(request))))


def settle(cur, eid, result):
    cur.execute(
        "UPDATE effects SET status='claimed', attempt_no=attempt_no+1, fence=fence+1, "
        "lease_owner='w', lease_until=clock_timestamp()+interval '1 hour' "
        "WHERE effect_id=%s RETURNING attempt_no, fence", (eid,))
    attempt, fence = cur.fetchone()
    cur.execute(
        "SELECT v13_complete(%s, %s, %s, 'succeeded', %s::jsonb)",
        (eid, attempt, fence, json.dumps(result)))
    return cur.fetchone()[0]


def project_calls(cur, sid, reason, calls):
    eid = enqueue(cur, sid, "llm", {"route": {"action": "llm", "reason": reason}})
    cur.execute(
        "UPDATE effects SET status='claimed', attempt_no=1, fence=1, lease_owner='w', "
        "lease_until=clock_timestamp()+interval '1 hour' WHERE effect_id=%s "
        "RETURNING attempt_no, fence", (eid,))
    attempt, fence = cur.fetchone()
    cur.execute(
        "SELECT v13_complete(%s, %s, %s, 'succeeded', %s::jsonb)",
        (eid, attempt, fence, json.dumps({"text": "ok", "tool_calls": calls})))
    cur.fetchone()
    return eid


def gate(cur, sid):
    return q1(cur, "SELECT v13_should_run_gate(%s)", (sid,))


def only_inserts(old, new, label):
    matcher = difflib.SequenceMatcher(a=old.splitlines(keepends=True),
                                       b=new.splitlines(keepends=True))
    bad = [tag for tag, *_ in matcher.get_opcodes() if tag not in ("equal", "insert")]
    check(f"{label} diff is insertions only", not bad, bad)


def tuple_locks(cur, pid):
    cur.execute(
        """
        SELECT pol.name, pol.version, l.granted, l.mode
          FROM pg_locks l
          JOIN pg_class c ON c.oid = l.relation
          JOIN v13_policies pol
            ON pol.ctid = format('(%%s,%%s)', l.page, l.tuple)::tid
         WHERE l.pid = %s AND l.locktype = 'tuple' AND c.relname = 'v13_policies'
        """,
        (pid,))
    return cur.fetchall()


def test_install_markers(cur):
    for sig in ("v13_should_run(uuid)", "v13_should_run_gate(uuid)"):
        cur.execute(
            "SELECT provolatile, prosecdef, proconfig::text FROM pg_proc WHERE oid = %s::regprocedure",
            (sig,))
        volatile, secdef, config = cur.fetchone()
        check(f"{sig} stable invoker", volatile == "s" and secdef is False, (volatile, secdef))
        check(f"{sig} search_path", "search_path=pg_catalog, public" in config, config)
    active = q1(
        cur, "SELECT value FROM v13_policies WHERE name='should_run' AND active")
    check("seed gates", active == SEED, active)


def test_policy_share_contract(cur):
    cur.execute(
        """
        SELECT p.provolatile, p.prosecdef, r.rolname, p.proconfig
          FROM pg_proc p
          JOIN pg_roles r ON r.oid = p.proowner
         WHERE p.oid = 'v13_policy_share()'::regprocedure
        """)
    volatile, secdef, owner, config = cur.fetchone()
    check("policy_share volatile definer", volatile == "v" and secdef is True)
    check("policy_share owner", owner == "v13_spawn_owner", owner)
    check("policy_share search_path",
          config == ["search_path=pg_catalog, public, pg_temp"], config)
    check("policy_share route",
          q1(cur, "SELECT has_function_privilege('v13_route', 'v13_policy_share()', 'EXECUTE')") is True)
    check("policy_share public false",
          q1(cur, "SELECT has_function_privilege('public', 'v13_policy_share()', 'EXECUTE')") is False)
    cur.execute("SAVEPOINT share_call")
    cur.execute("SET ROLE v13_route")
    cur.execute("SELECT v13_policy_share()")
    cur.execute("RESET ROLE")
    cur.execute("ROLLBACK TO SAVEPOINT share_call")
    check("route calls policy_share", True)


def test_policy_share_flip_blocks(server):
    conn = connect(server)
    cur = conn.cursor()
    src = prosrc(cur, "v13_policy_share()")
    lock_at = src.find("FOR SHARE OF locked")
    perform_at = src.find("PERFORM 1")
    lock_stmt = src[perform_at:lock_at] if 0 <= perform_at < lock_at else ""
    check("helper loop", "LOOP" in src and src.count("should_run") >= 1)
    check("helper lock has no active", "active" not in lock_stmt and "AND active" not in src, lock_stmt)
    check("helper order by name", "ORDER BY name" in src)
    for name in ("capabilities", "quota_window", "should_run", "spawn_budget", "triage"):
        check(f"helper names {name}", name in src)
    conn.rollback()
    conn.close()

    hold = connect(server)
    hc = hold.cursor()
    hc.execute("SET lock_timeout = '8s'")
    hc.execute(
        "INSERT INTO v13_policies (name, version, value, active) "
        "VALUES ('should_run', 901, %s::jsonb, false)",
        (json.dumps(SEED),))
    hc.execute("UPDATE v13_policies SET active=false WHERE name='should_run' AND version=1")
    b_pid = q1(hc, "SELECT pg_backend_pid()")
    box = {"release": threading.Event(), "returned": False, "err": None, "pid": None}
    obs = connect(server)
    obs.autocommit = True

    def run_a():
        c = connect(server)
        k = c.cursor()
        try:
            k.execute("SET statement_timeout = '20s'")
            k.execute("SET lock_timeout = '15s'")
            k.execute("SET ROLE v13_route")
            k.execute("SELECT pg_backend_pid()")
            box["pid"] = k.fetchone()[0]
            k.execute("SELECT v13_policy_share()")
            box["returned"] = True
            box["release"].wait(20)
            c.commit()
        except psycopg2.Error as exc:
            box["err"] = exc.diag.message_primary or str(exc)
            c.rollback()
        finally:
            c.close()

    thread = threading.Thread(target=run_a)
    thread.start()
    seen = False
    try:
        for _ in range(50):
            if box["pid"] is not None:
                blockers = q1(obs.cursor(), "SELECT pg_blocking_pids(%s)", (box["pid"],)) or []
                if b_pid in blockers:
                    seen = True
                    break
            if box["err"] or box["returned"]:
                break
            time.sleep(0.1)
        check("A blocked by should_run v1 holder", seen, (box, b_pid))
        a_locks = tuple_locks(obs.cursor(), box["pid"])
        check("A has not locked spawn_budget",
              not any(n == "spawn_budget" for n, *_ in a_locks), a_locks)
        third = connect(server)
        tc = third.cursor()
        tc.execute("SET lock_timeout = '2s'")
        try:
            tc.execute(
                "UPDATE v13_policies SET active=false WHERE name='spawn_budget' AND version=1")
            check("spawn_budget update not blocked", True)
        except psycopg2.Error as exc:
            check("spawn_budget update not blocked", False, exc.diag.message_primary)
        third.rollback()
        third.close()
        hc.execute("UPDATE v13_policies SET active=true WHERE name='should_run' AND version=901")
        hold.commit()
        for _ in range(50):
            if box["returned"] or box["err"]:
                break
            time.sleep(0.1)
        check("A retried and returned", box["returned"] and not box["err"], box)
        cbox = {"pid": None, "done": False, "err": None}

        def run_c():
            c = connect(server)
            k = c.cursor()
            try:
                k.execute("SET lock_timeout = '15s'")
                k.execute("SELECT pg_backend_pid()")
                cbox["pid"] = k.fetchone()[0]
                k.execute(
                    "UPDATE v13_policies SET active=false "
                    "WHERE name='should_run' AND version=901")
                cbox["done"] = True
                c.rollback()
            except psycopg2.Error as exc:
                cbox["err"] = exc.diag.message_primary or str(exc)
                c.rollback()
            finally:
                c.close()

        cthread = threading.Thread(target=run_c)
        cthread.start()
        blocked = False
        for _ in range(50):
            if cbox["pid"] is not None:
                blockers = q1(obs.cursor(), "SELECT pg_blocking_pids(%s)", (cbox["pid"],)) or []
                if box["pid"] in blockers:
                    blocked = True
                    break
            if cbox["done"] or cbox["err"]:
                break
            time.sleep(0.1)
        check("C blocked on v2 until A commits", blocked, cbox)
        box["release"].set()
        cthread.join(timeout=20)
        check("C unblocked after A commit", cbox["done"] and not cbox["err"], cbox)
    finally:
        try:
            hold.rollback()
        except psycopg2.Error:
            pass
        hold.close()
        box["release"].set()
        thread.join(timeout=8)
        obs.close()
        restore = connect(server)
        rc = restore.cursor()
        rc.execute("UPDATE v13_policies SET active=false WHERE name='should_run' AND version<>1")
        rc.execute("UPDATE v13_policies SET active=true WHERE name='should_run' AND version=1")
        restore.commit()
        active = q1(rc, "SELECT version FROM v13_policies WHERE name='should_run' AND active")
        restore.close()
        check("seed version restored", active == 1, active)


def test_red_note(cur):
    sql = (ROOT / "v13_should_run.sql").read_text()
    check("install DO baseline text", "v13: should_run baseline" in sql)
    check("functions exist after install",
          q1(cur, "SELECT to_regprocedure('v13_should_run(uuid)')") is not None)


def test_gate_matrix(cur):
    cur.execute("SAVEPOINT matrix")
    sid = open_session(cur)
    prefix(cur, sid)
    check("ready gate null", gate(cur, sid) is None)
    check("ready boolean true", q1(cur, "SELECT v13_should_run(%s)", (sid,)) is True)
    empty = open_session(cur)
    check("empty session true", q1(cur, "SELECT v13_should_run(%s)", (empty,)) is True)
    enqueue(cur, sid, "human", {"reason": "ask"})
    check("human_pending", gate(cur, sid) == "human_pending")
    check("human boolean false", q1(cur, "SELECT v13_should_run(%s)", (sid,)) is False)
    other = open_session(cur)
    prefix(cur, other)
    check("new session true again", gate(cur, other) is None)
    done = open_session(cur)
    prefix(cur, done)
    cur.execute("UPDATE sessions SET status='completed' WHERE session_id=%s", (done,))
    check("completed still true", gate(cur, done) is None)
    wall = open_session(cur)
    prefix(cur, wall)
    cur.execute("UPDATE sessions SET status='blocked_unknown' WHERE session_id=%s", (wall,))
    check("unknown_wall", gate(cur, wall) == "unknown_wall")
    unk = open_session(cur)
    prefix(cur, unk)
    eid = enqueue(cur, unk, "tool", {
        "tool": "send_summary_email", "params": {},
        "handler": "worker:send_summary_email", "tools_revision": 1,
    }, "send_summary_email")
    cur.execute("UPDATE effects SET status='unknown' WHERE effect_id=%s", (eid,))
    check("unknown effect wall", gate(cur, unk) == "unknown_wall")
    cancelled = open_session(cur)
    prefix(cur, cancelled)
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'cancel/requested', %s::jsonb)",
        (cancelled, u(), json.dumps({"schema_version": 1, "scope": "session"})))
    check("unconsumed_cancel", gate(cur, cancelled) == "unconsumed_cancel")
    flip_policy(cur, "triage", 2, {"duty_cycle": 0})
    shadow = open_session(cur)
    prefix(cur, shadow)
    check("duty shadow still null", gate(cur, shadow) is None)
    missing = u()
    fails_with(cur, "SELECT v13_should_run_gate(%s)", (missing,),
               f"v13: unknown session {missing}", "unknown uuid")
    flip_policy(cur, "triage", 3, {"duty_cycle": "2"})
    bad_uuid = u()
    msg = fails_with(cur, "SELECT v13_should_run_gate(%s)", (bad_uuid,),
                     f"v13: unknown session {bad_uuid}", "bad triage still unknown session")
    check("bad triage does not win", "triage policy" not in msg, msg)
    cur.execute("ROLLBACK TO SAVEPOINT matrix")
    cur.execute("SAVEPOINT sp_order")
    both = open_session(cur)
    prefix(cur, both)
    enqueue(cur, both, "human", {"reason": "ask"})
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'cancel/requested', %s::jsonb)",
        (both, u(), json.dumps({"schema_version": 1, "scope": "session"})))
    human_first = {
        "schema_version": 1,
        "gates": [
            {"id": "human_pending", "effect": "block"},
            {"id": "unconsumed_cancel", "effect": "block"},
        ],
    }
    cancel_first = {
        "schema_version": 1,
        "gates": [
            {"id": "unconsumed_cancel", "effect": "block"},
            {"id": "human_pending", "effect": "block"},
        ],
    }
    oid = q1(cur, "SELECT oid FROM pg_proc WHERE oid = 'v13_should_run_gate(uuid)'::regprocedure")
    flip_policy(cur, "should_run", 2, human_first)
    check("order human first", gate(cur, both) == "human_pending")
    flip_policy(cur, "should_run", 3, cancel_first)
    check("order cancel first", gate(cur, both) == "unconsumed_cancel")
    check("gate oid unchanged",
          q1(cur, "SELECT oid FROM pg_proc WHERE oid = 'v13_should_run_gate(uuid)'::regprocedure") == oid)
    cur.execute("ROLLBACK TO SAVEPOINT sp_order")
    cur.execute("SAVEPOINT badtail")
    victim = open_session(cur)
    prefix(cur, victim)
    enqueue(cur, victim, "human", {"reason": "ask"})
    flip_policy(cur, "should_run", 4, {
        "schema_version": 1,
        "gates": [
            {"id": "human_pending", "effect": "block"},
            {"id": "not_a_gate", "effect": "block"},
        ],
    })
    fails_with(cur, "SELECT v13_should_run_gate(%s)", (victim,),
               "v13: should_run gate", "bad tail unknown id")
    flip_policy(cur, "should_run", 5, {
        "schema_version": 1,
        "gates": [
            {"id": "human_pending", "effect": "block"},
            {"id": "human_pending", "effect": "shadow"},
        ],
    })
    fails_with(cur, "SELECT v13_should_run_gate(%s)", (victim,),
               "v13: should_run gate", "duplicate id")
    cur.execute("UPDATE v13_policies SET active=false WHERE name='should_run' AND active")
    msg = fails_with(cur, "SELECT v13_should_run_gate(%s)", (victim,),
                     "v13: should_run policy", "missing policy row")
    check("missing row is not v13_policy text", "no active policy" not in msg, msg)
    flip_policy(cur, "should_run", 6, {"schema_version": 1, "gates": [], "extra": 1})
    fails_with(cur, "SELECT v13_should_run_gate(%s)", (victim,),
               "v13: should_run policy", "bad top-level keys")
    flip_policy(cur, "should_run", 7, {"schema_version": 1, "gates": {"id": "human_pending"}})
    fails_with(cur, "SELECT v13_should_run_gate(%s)", (victim,),
               "v13: should_run policy", "gates not array")
    flip_policy(cur, "should_run", 8, {"schema_version": 1, "gates": ["human_pending"]})
    fails_with(cur, "SELECT v13_should_run_gate(%s)", (victim,),
               "v13: should_run policy", "element not object")
    cur.execute("ROLLBACK TO SAVEPOINT badtail")


def test_duty_unchanged(cur):
    cur.execute("SAVEPOINT duty")
    flip_policy(cur, "triage", 11, {"duty_cycle": 0})
    sid = open_session(cur)
    prefix(cur, sid)
    before = n_effects(cur, sid)
    check("no ready before duty advance", ready_claimed(cur, sid) == 0)
    word = advance(cur, sid, role="v13_route")
    check("duty 0 route advance waiting", word == "waiting", word)
    check("duty hold one", n_events(cur, sid, "triage/hold") == 1)
    reason = q1(
        cur,
        "SELECT payload->>'reason' FROM events WHERE session_id=%s AND type='triage/hold'",
        (sid,))
    check("hold reason duty_cycle", reason == "duty_cycle", reason)
    check("duty 0 effect count", n_effects(cur, sid) == before)
    check("duty 0 status waiting", status_of(cur, sid) == "waiting")
    check("duty 0 second advance", advance(cur, sid) == "waiting")
    check("hold not duplicated", n_events(cur, sid, "triage/hold") == 1)
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'repair/required', %s::jsonb, %s)",
        (sid, u(), json.dumps({"schema_version": 1}), u()))
    before_nudge = n_events(cur, sid, "recover/nudge")
    cur.execute("SELECT v13_recover_idle()")
    check("duty hold blocks recover", n_events(cur, sid, "recover/nudge") == before_nudge)
    flip_policy(cur, "triage", 12, {"duty_cycle": 1})
    plain = open_session(cur)
    prefix(cur, plain)
    advance(cur, plain)
    check("duty 1 writes no hold", n_events(cur, plain, "triage/hold") == 0)
    cur.execute("ROLLBACK TO SAVEPOINT duty")


def test_cancel_not_blocked_by_projection(cur):
    cur.execute("SAVEPOINT cancel")
    flip_policy(cur, "triage", 13, {"duty_cycle": 0})
    flip_policy(cur, "should_run", 13, DUTY_BLOCK)
    sid = open_session(cur)
    prefix(cur, sid)
    cur.execute("SELECT v13_cancel(%s)", (sid,))
    check("cancel accepted", cur.fetchone()[0] == "accepted")
    check("no claimed before cancel advance", ready_claimed(cur, sid) == 0)
    check("no open children", n_children(cur, sid) == 0)
    word = advance(cur, sid)
    check("cancel still terminal", word == "terminal", word)
    check("cancel status", status_of(cur, sid) == "cancelled")
    check("session/cancelled exists", n_events(cur, sid, "session/cancelled") == 1)
    cur.execute("ROLLBACK TO SAVEPOINT cancel")


def test_spawn_suppressed_when_duty_block(cur):
    cur.execute("SAVEPOINT spawn")
    flip_policy(cur, "triage", 14, {"duty_cycle": 0})
    sid = open_session(cur)
    prefix(cur, sid)
    project_calls(cur, sid, "answer", CALL)
    check("spawn A no ready/claimed", ready_claimed(cur, sid) == 0)
    before_kids = n_children(cur, sid)
    word = advance(cur, sid, role="v13_route")
    check("shadow duty still spawns", word == "progressed", word)
    check("shadow child or fanout",
          n_children(cur, sid) == before_kids + 1 and n_events(cur, sid, "turn/route") >= 1)
    flip_policy(cur, "should_run", 14, DUTY_BLOCK)
    blocked = open_session(cur)
    prefix(cur, blocked)
    project_calls(cur, blocked, "answer", CALL)
    other = open_session(cur)
    other_status = status_of(cur, other)
    check("spawn B no ready/claimed", ready_claimed(cur, blocked) == 0)
    kids = n_children(cur, blocked)
    effects = n_effects(cur, blocked)
    fanout = n_events(cur, blocked, "turn/route")
    calls = n_events(cur, blocked, "tool/call")
    word = advance(cur, blocked)
    check("duty block suppresses spawn", word == "waiting", word)
    check("suppressed status waiting", status_of(cur, blocked) == "waiting")
    check("suppressed no hold", n_events(cur, blocked, "triage/hold") == 0)
    check("suppressed no new child", n_children(cur, blocked) == kids)
    check("suppressed no fanout", n_events(cur, blocked, "turn/route") == fanout)
    check("suppressed no new effect", n_effects(cur, blocked) == effects)
    check("tool/call remains", n_events(cur, blocked, "tool/call") == calls and calls == 1)
    check("unrelated status unchanged", status_of(cur, other) == other_status)
    cur.execute("ROLLBACK TO SAVEPOINT spawn")


def test_explore_raise_survives_gate(cur):
    cur.execute("SAVEPOINT explore")
    flip_policy(cur, "triage", 15, {"duty_cycle": 0})
    flip_policy(cur, "should_run", 15, DUTY_BLOCK)
    sid = open_session(cur)
    prefix(cur, sid)
    project_calls(cur, sid, "explore", CALL)
    before_e = n_effects(cur, sid)
    before_r = n_events(cur, sid, "turn/route")
    before_k = n_children(cur, sid)
    fails_with(cur, "SELECT v13_advance(%s, %s::jsonb)",
               (sid, json.dumps(snap_of(cur, sid))),
               "v13: explore spawn", "explore raise survives false gate")
    check("explore zero new effect", n_effects(cur, sid) == before_e)
    check("explore zero route", n_events(cur, sid, "turn/route") == before_r)
    check("explore zero children", n_children(cur, sid) == before_k)
    cur.execute("ROLLBACK TO SAVEPOINT explore")


def test_bad_spawn_shape_suppressed(cur):
    src = prosrc(cur, "v13_advance(uuid,jsonb)")
    check("should_run before spawn_children",
          src.index("v13_should_run(") < src.index("v13_spawn_children"))
    cur.execute("SAVEPOINT badshape")
    flip_policy(cur, "triage", 16, {"duty_cycle": 0})
    flip_policy(cur, "should_run", 16, DUTY_BLOCK)

    def plant(sid):
        eid = enqueue(cur, sid, "llm", {"route": {"action": "llm", "reason": "answer"}})
        cur.execute("UPDATE effects SET status='succeeded' WHERE effect_id=%s", (eid,))
        cur.execute(
            "SELECT v13_append_event(%s, %s, 'tool/call', %s::jsonb, %s)",
            (sid, u(), json.dumps({
                "schema_version": 1, "id": None, "name": "spawn_subsession",
                "args": {"task": "x"},
            }), eid))

    sid = open_session(cur)
    prefix(cur, sid)
    plant(sid)
    before = n_effects(cur, sid)
    word = advance(cur, sid)
    check("bad shape false gate waiting", word == "waiting", word)
    check("bad shape false gate no new effect", n_effects(cur, sid) == before)
    cur.execute("ROLLBACK TO SAVEPOINT badshape")
    cur.execute("SAVEPOINT badshape_true")
    sid = open_session(cur)
    prefix(cur, sid)
    plant(sid)
    fails_with(cur, "SELECT v13_advance(%s, %s::jsonb)",
               (sid, json.dumps(snap_of(cur, sid))),
               "v13: spawn args", "bad shape true gate still raises")
    cur.execute("ROLLBACK TO SAVEPOINT badshape_true")


def test_finish_closeout_despite_block(cur):
    cur.execute("SAVEPOINT finish")
    flip_policy(cur, "triage", 17, {"duty_cycle": 0})
    flip_policy(cur, "should_run", 17, DUTY_BLOCK)
    sid = open_session(cur)
    prefix(cur, sid)
    eid = enqueue(cur, sid, "tool", harness_request(u(), 0, trev(cur, sid)), "harness_turn")
    settle(cur, eid, FINISH)
    check("finish no ready/claimed", ready_claimed(cur, sid) == 0)
    check("finish no children", n_children(cur, sid) == 0)
    word = advance(cur, sid)
    check("finish still terminal", word == "terminal", word)
    check("finish completed", status_of(cur, sid) == "completed")
    cur.execute("ROLLBACK TO SAVEPOINT finish")


def test_resolve_failed_audit_exemption(cur):
    cur.execute("SAVEPOINT audit")
    flip_policy(cur, "triage", 18, {"duty_cycle": 0})
    flip_policy(cur, "should_run", 18, DUTY_BLOCK)
    sid = open_session(cur)
    prefix(cur, sid)
    word = advance(cur, sid, failed=True)
    check("duty 0 does not prewrite", word == "waiting", word)
    check("resolve/failed zero", n_events(cur, sid, "resolve/failed") == 0)
    check("duty branch still holds", n_events(cur, sid, "triage/hold") == 1)
    src = prosrc(cur, "v13_advance(uuid,jsonb)")
    call_at = src.index("v_triage := v13_triage_prework(p_sid)")
    head = src[:call_at]
    for needle in (
        "v13_triage_duty()<>0",
        "NOT public.v13_should_run(p_sid)",
        "p_snap->>'failed' IS NOT NULL",
        "resolve/failed",
    ):
        check(f"precheck before prework: {needle}", needle in head)
    check("original resolve/failed remains after prework",
          src[call_at:].count("resolve/failed") == 1)
    check("precheck does not return", "RETURN" not in head[head.index("v13_triage_duty()<>0"):])
    cur.execute("ROLLBACK TO SAVEPOINT audit")


def test_continuation_suppressed(cur):
    cur.execute("SAVEPOINT cont")
    flip_policy(cur, "triage", 19, {"duty_cycle": 0})
    flip_policy(cur, "should_run", 19, DUTY_BLOCK)
    sid = open_session(cur)
    prefix(cur, sid)
    eid = enqueue(cur, sid, "tool", harness_request(u(), 0, trev(cur, sid)), "harness_turn")
    settle(cur, eid, {"result_kind": "progress", "signals": ["repair/required"]})
    repairs = n_events(cur, sid, "repair/required")
    check("continuation predecessor has repair", repairs == 1, repairs)
    check("continuation no ready/claimed", ready_claimed(cur, sid) == 0)
    routes = n_events(cur, sid, "turn/route")
    other = open_session(cur)
    other_status = status_of(cur, other)
    word = advance(cur, sid)
    check("continuation waiting", word == "waiting", word)
    check("continuation status waiting", status_of(cur, sid) == "waiting")
    check("continuation not terminal", status_of(cur, sid) not in ("completed", "failed", "cancelled"))
    nxt = q1(
        cur,
        "SELECT count(*) FROM effects WHERE session_id=%s "
        "AND request->>'continuation_index' = '1'",
        (sid,))
    check("no continuation_index+1", int(nxt) == 0, nxt)
    check("no harness_continuation route", n_events(cur, sid, "turn/route") == routes)
    check("repair count unchanged", n_events(cur, sid, "repair/required") == repairs)
    check("continuation no hold", n_events(cur, sid, "triage/hold") == 0)
    check("continuation unrelated status", status_of(cur, other) == other_status)
    cur.execute("ROLLBACK TO SAVEPOINT cont")


def test_prework_enqueue_blocked(cur):
    src = prosrc(cur, "v13_triage_prework(uuid)")
    gate_at = src.index("v13_should_run(")
    human_at = src.index("IF v_dec = 'human'")
    fold_at = src.index("v_reason := v13_triage_fold_reason")
    check("prework gate before human exit", gate_at < human_at)
    check("fold_reason stays after gate", fold_at > human_at)
    check("prework one should_run", src.count("v13_should_run(") == 1)


def parent_of(cur, sid):
    return q1(cur, "SELECT parent_session_id::text FROM sessions WHERE session_id=%s", (sid,))


def raise_exact(cur, sql, params, expected, label):
    cur.execute("SAVEPOINT sp_parent")
    try:
        cur.execute(sql, params)
    except psycopg2.Error as exc:
        msg = exc.diag.message_primary or ""
        check(label, msg == expected, msg)
        cur.execute("ROLLBACK TO SAVEPOINT sp_parent")
        return
    cur.execute("ROLLBACK TO SAVEPOINT sp_parent")
    raise AssertionError(f"{label}: expected {expected}")


def test_parent_immutable(cur):
    fmt = "v13: fork columns are write-once (session %)"
    defn = q1(cur, "SELECT pg_get_functiondef('v13_spawn_cols_guard()'::regprocedure)")
    line = next(l for l in defn.splitlines() if "fork columns are write-once" in l)
    check("guard format string", fmt in defn)
    check("guard one placeholder", line.count("%") == 1, line)
    tdef = q1(
        cur,
        "SELECT pg_get_triggerdef(oid) FROM pg_trigger "
        "WHERE tgname = 'trg_sessions_fork_cols_immutable'")
    check("fork guard is before update", "BEFORE UPDATE" in tdef, tdef)
    for col in ("parent_session_id", "parent_cutoff_seq", "spawn_kind"):
        check(f"fork guard OF {col}", col in tdef, tdef)
    check("fork guard executes spawn_cols_guard", "v13_spawn_cols_guard" in tdef, tdef)
    check("new parent trigger absent",
          q1(cur, "SELECT count(*) FROM pg_trigger WHERE tgname = 'trg_sessions_parent_immutable'") == 0)
    check("new parent function absent",
          q1(cur, "SELECT to_regprocedure('v13_sessions_parent_immutable()')") is None)
    sql = (ROOT / "v13_should_run.sql").read_text()
    check("sql does not create parent trigger",
          "CREATE TRIGGER trg_sessions_parent_immutable" not in sql)
    check("sql has no parent immutable text", "v13: parent immutable" not in sql)
    parent = open_session(cur)
    prefix(cur, parent)
    child = str(q1(cur, "SELECT v13_fork(%s, 0, 'fresh_fork', NULL)", (parent,)))
    check("fork insert sets parent", parent_of(cur, child) == parent)
    other = open_session(cur)
    for role in ("v13_route", "v13_spawn_owner"):
        cur.execute("RESET ROLE")
        before = parent_of(cur, child)
        cur.execute(f"SET ROLE {role}")
        raise_exact(
            cur,
            "UPDATE sessions SET parent_session_id=%s WHERE session_id=%s",
            (other, child),
            f"v13: fork columns are write-once (session {child})",
            f"{role} cannot change parent")
        cur.execute("RESET ROLE")
        check(f"{role} parent unchanged", parent_of(cur, child) == before, parent_of(cur, child))
    root = open_session(cur)
    root_parent = parent_of(cur, root)
    check("root parent is null", root_parent is None, root_parent)
    cur.execute("SET ROLE v13_route")
    raise_exact(
        cur,
        "UPDATE sessions SET parent_session_id=%s WHERE session_id=%s",
        (parent, root),
        f"v13: fork columns are write-once (session {root})",
        "null parent cannot be set")
    cur.execute("RESET ROLE")
    check("null parent unchanged", parent_of(cur, root) is None)
    cur.execute("UPDATE sessions SET status='waiting' WHERE session_id=%s", (child,))
    check("status update still succeeds", status_of(cur, child) == "waiting")


def test_source_delta(cur):
    old_adv = (PRE / "advance.prosrc").read_text()
    old_pre = (PRE / "prework.prosrc").read_text()
    new_adv = prosrc(cur, "v13_advance(uuid,jsonb)")
    new_pre = prosrc(cur, "v13_triage_prework(uuid)")
    only_inserts(old_adv, new_adv, "advance")
    only_inserts(old_pre, new_pre, "prework")
    check("advance four should_run", new_adv.count("v13_should_run(") == 4)
    check("advance one policy_share", new_adv.count("v13_policy_share()") == 1)
    share_at = new_adv.index("v13_policy_share()")
    if_at = new_adv.index("IF jsonb_array_length(v_calls) > 0")
    explore_at = new_adv.index("v13_triage_block_explore_spawn")
    first_should = new_adv.index("v13_should_run(")
    check("policy_share outside calls IF", explore_at < share_at < if_at < first_should)
    pre_at = new_adv.index("v_triage := v13_triage_prework(p_sid)")
    check("no should_run after prework", "v13_should_run(" not in new_adv[pre_at:])
    check("no defer flag or batch wrapper",
          "v_defer_spawn" not in new_adv and "v13_spawn_batch_allowed" not in new_adv)
    check("prework gate before human",
          new_pre.index("v13_should_run(") < new_pre.index("IF v_dec = 'human'"))
    arm = old_adv[old_adv.index("WHEN query_canceled THEN"):old_adv.index("WHEN OTHERS THEN")]
    check("query_canceled arm preserved", arm in new_adv)
    check("current_setting count stays 1",
          old_adv.count("current_setting") == 1 and new_adv.count("current_setting") == 1)
    check("current_setting call text",
          new_adv.count("current_setting('statement_timeout', true)") == 1)
    check("prework current_setting 0", new_pre.count("current_setting") == 0)
    for word in ("goal/stopped", "goal/resumed", "v13_goal_lifecycle",
                 "quota/spent", "quota/voided", "v13.control_actor"):
        check(f"advance lacks {word}", new_adv.count(word) == 0)
        check(f"prework lacks {word}", new_pre.count(word) == 0)
    for sig in ("v13_should_run(uuid)", "v13_should_run_gate(uuid)", "v13_policy_share()"):
        body = prosrc(cur, sig)
        for banned in ("INSERT", "UPDATE", "DELETE", "v13_append_event"):
            check(f"{sig} no {banned}", banned not in body)
    wrap = prosrc(cur, "v13_should_run(uuid)")
    for literal in ("human_pending", "unknown_wall", "unconsumed_cancel", "duty_cycle"):
        check(f"wrapper lacks {literal}", literal not in wrap)
    sql = (ROOT / "v13_should_run.sql").read_text()
    for banned in ("CREATE TABLE", "CREATE VIEW", "MATERIALIZED", "ALTER TABLE",
                   "LISTEN", "pg_terminate_backend", "pg_sleep"):
        check(f"sql lacks {banned}", banned not in sql)
    for role, expect in (
        ("v13_worker", False), ("public", False), ("v13_recall", False),
        ("v13_resolve", False), ("v13_route", True),
    ):
        for sig in ("v13_should_run(uuid)", "v13_should_run_gate(uuid)"):
            got = q1(cur, "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, sig))
            check(f"{sig} {role}", got is expect, got)
    sid = open_session(cur)
    prefix(cur, sid)
    cur.execute("SET ROLE v13_route")
    got = q1(cur, "SELECT v13_should_run(%s)", (sid,))
    cur.execute("RESET ROLE")
    check("route boolean call", got is True, got)


def test_regression_note(cur):
    check("should_run registered 26", STAGE_THROUGH["should_run"] == 26)
    check("handoff still 25", STAGE_THROUGH["handoff"] == 25)
    print("[note] regression 1-25 is run by the implementer, not this script")


def main() -> int:
    global N
    setup_db()
    server = get_server()
    conn = connect(server)
    cur = conn.cursor()
    try:
        test_install_markers(cur)
        test_policy_share_contract(cur)
        test_policy_share_flip_blocks(server)
        test_red_note(cur)
        test_gate_matrix(cur)
        test_duty_unchanged(cur)
        test_cancel_not_blocked_by_projection(cur)
        test_spawn_suppressed_when_duty_block(cur)
        test_explore_raise_survives_gate(cur)
        test_bad_spawn_shape_suppressed(cur)
        test_finish_closeout_despite_block(cur)
        test_resolve_failed_audit_exemption(cur)
        test_continuation_suppressed(cur)
        test_prework_enqueue_blocked(cur)
        test_parent_immutable(cur)
        test_source_delta(cur)
        test_regression_note(cur)
        conn.rollback()
    finally:
        conn.close()
    print(f"[should_run] ALL PASS ({N})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
