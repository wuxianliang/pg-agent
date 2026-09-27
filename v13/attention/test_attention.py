"""Stage 28 gate: attention rank and scheduler hint.

Run: uv run python v13/attention/test_attention.py  (exit 0 = pass)
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v13.load import STAGE_THROUGH
from v13.attention.setup_db import DB, main as setup_db

N = 0
VER = 100
FINISH = {"result_kind": "finish", "delivery_kind": "LOUD-BUT-BLIND"}
CLOSED = {"run_now", "wait", "dont_notify"}


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


def next_ver():
    global VER
    VER += 1
    return VER


def connect(server, db=DB):
    conn = psycopg2.connect(server.get_uri(db))
    conn.autocommit = False
    return conn


def q1(cur, sql, params=None):
    cur.execute(sql, params)
    row = cur.fetchone()
    return None if row is None else row[0]


def qall(cur, sql, params=None):
    cur.execute(sql, params)
    return cur.fetchall()


def fails_with(cur, sql, params, needle, label, exact=False):
    cur.execute("SAVEPOINT sp")
    try:
        cur.execute(sql, params)
    except psycopg2.Error as exc:
        msg = exc.diag.message_primary or str(exc).splitlines()[0]
        ok = msg == needle if exact else needle in msg
        check(label, ok, msg)
        cur.execute("ROLLBACK TO SAVEPOINT sp")
        return msg
    cur.execute("ROLLBACK TO SAVEPOINT sp")
    raise AssertionError(f"{label}: expected failure")


def expect_42501(cur, role, sql, params, label):
    cur.execute("SAVEPOINT sp_acl")
    cur.execute(f"SET ROLE {role}")
    try:
        cur.execute(sql, params)
    except psycopg2.Error as exc:
        check(label, exc.pgcode == "42501", exc.pgcode)
        cur.execute("ROLLBACK TO SAVEPOINT sp_acl")
        cur.execute("RESET ROLE")
        return
    cur.execute("ROLLBACK TO SAVEPOINT sp_acl")
    cur.execute("RESET ROLE")
    raise AssertionError(f"{label}: expected 42501")


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


def n_events(cur, sid=None, etype=None):
    if sid is None:
        return int(q1(cur, "SELECT count(*) FROM events"))
    if etype is None:
        return int(q1(cur, "SELECT count(*) FROM events WHERE session_id=%s", (sid,)))
    return int(q1(
        cur, "SELECT count(*) FROM events WHERE session_id=%s AND type=%s", (sid, etype)))


def n_effects(cur, sid):
    return int(q1(cur, "SELECT count(*) FROM effects WHERE session_id=%s", (sid,)))


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


def fresh_pair(cur):
    sid = open_session(cur)
    prefix(cur, sid)
    return sid


def harness_effect(cur, sid, result=None):
    eid = enqueue(cur, sid, "tool", harness_request(u(), 0, trev(cur, sid)), "harness_turn")
    settle(cur, eid, result or FINISH)
    return eid


def hint(cur, sid):
    return q1(cur, "SELECT v13_scheduler_hint(%s)", (sid,))


def budget(cur, sid, requested, root=None):
    if root is None:
        return q1(cur, "SELECT v13_spawn_budget_snapshot(%s, %s)", (sid, requested))
    return q1(
        cur, "SELECT v13_spawn_budget_snapshot(%s, %s, %s)", (sid, requested, root))


def insert_children(cur, parent, n, status="ready"):
    cur.execute("SET ROLE v13_spawn_owner")
    cur.execute(
        "INSERT INTO sessions (status, parent_session_id, spawn_kind) "
        "SELECT %s, %s, 'fresh_fork' FROM generate_series(1, %s) RETURNING session_id",
        (status, parent, n))
    ids = [str(row[0]) for row in cur.fetchall()]
    cur.execute("RESET ROLE")
    return ids


def insert_one(cur, parent, status="ready", sid=None):
    cid = sid or u()
    cur.execute("SET ROLE v13_spawn_owner")
    cur.execute(
        "INSERT INTO sessions (session_id, status, parent_session_id, spawn_kind) "
        "VALUES (%s, %s, %s, 'fresh_fork')",
        (cid, status, parent))
    cur.execute("RESET ROLE")
    return cid


def plant_calls(cur, sid, n):
    eid = enqueue(cur, sid, "llm", {"route": {"action": "llm", "reason": "answer"}})
    cur.execute("UPDATE effects SET status='succeeded' WHERE effect_id=%s", (eid,))
    for i in range(n):
        cur.execute(
            "SELECT v13_append_event(%s, %s, 'tool/call', %s::jsonb, %s)",
            (sid, u(), json.dumps({
                "schema_version": 1,
                "id": f"call{i}",
                "name": "spawn_subsession",
                "args": {"task": "task"},
            }), eid))
    return eid


def attention_rows(cur, root, limit=None):
    if limit is None:
        cur.execute(
            "SELECT attention_rank, session_id::text, parent_session_id::text, depth, "
            "status, spawn_kind, turn_no, is_terminal, should_run, blocked_by "
            "FROM v13_attention(%s) ORDER BY attention_rank",
            (root,))
    else:
        cur.execute(
            "SELECT attention_rank, session_id::text, parent_session_id::text, depth, "
            "status, spawn_kind, turn_no, is_terminal, should_run, blocked_by "
            "FROM v13_attention(%s, %s) ORDER BY attention_rank",
            (root, limit))
    return cur.fetchall()


def test_unknown_root(cur):
    missing = u()
    fails_with(
        cur, "SELECT * FROM v13_attention(%s)", (missing,),
        "v13: unknown session", "unknown root", exact=True)


def test_attention_limit(cur):
    cur.execute("SAVEPOINT limit_tree")
    root = open_session(cur)
    insert_children(cur, root, 511, "completed")
    rows = attention_rows(cur, root)
    check("512 rows returned", len(rows) == 512, len(rows))
    check("512 ranks cover", [r[0] for r in rows] == list(range(1, 513)))
    cur.execute("SAVEPOINT one_more")
    insert_one(cur, root, "completed")
    fails_with(
        cur, "SELECT count(*) FROM v13_attention(%s)", (root,),
        "v13: attention limit", "513 rows", exact=True)
    cur.execute("ROLLBACK TO SAVEPOINT one_more")
    for bad, label in ((None, "null"), (0, "zero"), (-1, "negative"), (1025, "over 1024")):
        fails_with(
            cur, "SELECT count(*) FROM v13_attention(%s, %s)", (root, bad),
            "v13: attention limit", f"limit {label}", exact=True)
    src = prosrc(cur, "v13_attention(uuid, integer)")
    check("count before gate", src.index("v_n > p_max_rows") < src.index("v13_should_run_gate"))
    check("gate call once", src.count("v13_should_run_gate") == 1)
    defn = q1(cur, "SELECT pg_get_functiondef('v13_attention(uuid, integer)'::regprocedure)")
    check("default 512", "DEFAULT 512" in defn)
    cur.execute("ROLLBACK TO SAVEPOINT limit_tree")


def test_hint_unknown_precedes_bad_policy(cur):
    cur.execute("SAVEPOINT unk_pol")
    before = n_events(cur)
    flip_policy(cur, "triage", next_ver(), {"broken": True})
    missing = u()
    fails_with(
        cur, "SELECT v13_scheduler_hint(%s)", (missing,),
        f"v13: unknown session {missing}", "hint unknown before triage policy", exact=True)
    check("unknown hint zero writes", n_events(cur) == before)
    cur.execute("ROLLBACK TO SAVEPOINT unk_pol")


def test_single_root(cur):
    sid = fresh_pair(cur)
    rows = attention_rows(cur, sid)
    check("single row", len(rows) == 1, len(rows))
    rank, sess, parent, depth, status, kind, turn, term, run, blocked = rows[0]
    tree = qall(
        cur,
        "SELECT session_id::text, parent_session_id::text, depth, status, spawn_kind, "
        "turn_no, is_terminal FROM v_goal_tree(%s)",
        (sid,))[0]
    live = qall(
        cur,
        "SELECT session_id::text, parent_session_id::text, status, spawn_kind, turn_no "
        "FROM sessions WHERE session_id=%s",
        (sid,))[0]
    check("rank 1", rank == 1, rank)
    check("depth 0", depth == 0, depth)
    check("blocked null", blocked is None, blocked)
    check("should_run true", run is True, run)
    check("matches tree", (sess, parent, depth, status, kind, turn, term) == tree, (rows[0], tree))
    check("matches session", (sess, parent, status, kind, turn) == live, (rows[0], live))


def test_rank_human_before_runnable(cur):
    cur.execute("SAVEPOINT rank")
    root = fresh_pair(cur)
    kids = insert_children(cur, root, 2, "ready")
    for kid in kids:
        prefix(cur, kid)
        enqueue(cur, kid, "human", {"schema_version": 1, "interaction_ref": u()})
    grand = insert_one(cur, kids[0], "completed")
    rows = attention_rows(cur, root)
    by_id = {row[1]: row for row in rows}
    check("rank rows", len(rows) == 4, len(rows))
    check("ranks contiguous", [row[0] for row in rows] == [1, 2, 3, 4])
    ordered_kids = sorted(kids)
    check("same depth session_id order", [row[1] for row in rows[:2]] == ordered_kids,
          [row[1] for row in rows[:2]])
    for kid in kids:
        check(f"{kid[:8]} human block", by_id[kid][9] == "human_pending", by_id[kid][9])
        check(f"{kid[:8]} before root", by_id[kid][0] < by_id[root][0])
        check(f"{kid[:8]} depth 1", by_id[kid][3] == 1, by_id[kid][3])
    check("root runnable", by_id[root][8] is True and by_id[root][9] is None)
    check("terminal sinks", by_id[grand][0] == 4 and by_id[grand][7] is True)
    check("terminal blocked null", by_id[grand][9] is None, by_id[grand][9])
    check("terminal after nonterminal",
          by_id[grand][0] > max(by_id[sid][0] for sid in (root, *kids)))
    cur.execute("ROLLBACK TO SAVEPOINT rank")


def test_rank_not_stored(cur):
    sid = fresh_pair(cur)
    cols = int(q1(
        cur,
        "SELECT count(*) FROM information_schema.columns WHERE column_name = 'attention_rank'"))
    check("rank not a column", cols == 0, cols)
    check("attention is not a relation", q1(cur, "SELECT to_regclass('public.v13_attention')") is None)
    before = n_events(cur)
    a = q1(
        cur,
        "SELECT jsonb_agg(to_jsonb(t) ORDER BY attention_rank) FROM v13_attention(%s) t",
        (sid,))
    b = q1(
        cur,
        "SELECT jsonb_agg(to_jsonb(t) ORDER BY attention_rank) FROM v13_attention(%s) t",
        (sid,))
    check("two calls identical", a == b, (a, b))
    check("two calls zero events", n_events(cur) == before)


def test_hint_matrix(cur):
    sid = fresh_pair(cur)
    check("duty is 1", int(q1(cur, "SELECT v13_triage_duty()")) == 1)
    word = hint(cur, sid)
    check("ready run_now", word == "run_now", word)
    check("word in closed set", word in CLOSED, word)

    cur.execute("SAVEPOINT duty0")
    flip_policy(cur, "triage", next_ver(), {"duty_cycle": 0})
    holds = n_events(cur, sid, "triage/hold")
    check("cancel absent", q1(cur, "SELECT v13_unconsumed_cancel(%s)", (sid,)) is False)
    word = hint(cur, sid)
    check("duty 0 waits", word == "wait", word)
    check("hint writes no hold", n_events(cur, sid, "triage/hold") == holds)
    cur.execute("SELECT v13_cancel(%s)", (sid,))
    word = hint(cur, sid)
    check("cancel without claimed runs", word == "run_now", word)
    cur.execute("ROLLBACK TO SAVEPOINT duty0")

    cur.execute("SAVEPOINT cancel_ready")
    ready_sid = fresh_pair(cur)
    enqueue(cur, ready_sid, "tool", harness_request(u(), 0, trev(cur, ready_sid)), "harness_turn")
    cur.execute("SELECT v13_cancel(%s)", (ready_sid,))
    word = hint(cur, ready_sid)
    check("cancel ready still runs", word == "run_now", word)
    cur.execute("ROLLBACK TO SAVEPOINT cancel_ready")

    cur.execute("SAVEPOINT cancel_claimed")
    claimed = fresh_pair(cur)
    eid = enqueue(cur, claimed, "human", {"schema_version": 1, "interaction_ref": u()})
    cur.execute(
        "UPDATE effects SET status='claimed', attempt_no=1, fence=1, lease_owner='w', "
        "lease_until=clock_timestamp()+interval '1 hour' WHERE effect_id=%s",
        (eid,))
    cur.execute("SELECT v13_cancel(%s)", (claimed,))
    word = hint(cur, claimed)
    check("cancel claimed waits", word == "wait", word)
    cur.execute("ROLLBACK TO SAVEPOINT cancel_claimed")

    cur.execute("SAVEPOINT human")
    human = fresh_pair(cur)
    enqueue(cur, human, "human", {"schema_version": 1, "interaction_ref": u()})
    word = hint(cur, human)
    check("ready human waits", word == "wait", word)
    cur.execute("ROLLBACK TO SAVEPOINT human")

    cur.execute("SAVEPOINT allowed0")
    flip_policy(cur, "quota_window", next_ver(), {
        "schema_version": 1, "window_hours": 8760, "slot_minutes": 0, "allowed": 0,
    })
    blocked = fresh_pair(cur)
    word = hint(cur, blocked)
    check("allowed 0 waits", word == "wait", word)
    cur.execute("ROLLBACK TO SAVEPOINT allowed0")

    cur.execute("SAVEPOINT inflight")
    busy = fresh_pair(cur)
    enqueue(cur, busy, "tool", harness_request(u(), 0, trev(cur, busy)), "harness_turn")
    flip_policy(cur, "triage", next_ver(), {"broken": True})
    try:
        word = hint(cur, busy)
    except psycopg2.Error as exc:
        raise AssertionError(f"inflight bad policy raised {exc.diag.message_primary}") from exc
    check("inflight bad policy waits", word == "wait", word)
    cur.execute("ROLLBACK TO SAVEPOINT inflight")

    cur.execute("SAVEPOINT fanout")
    flip_policy(cur, "spawn_budget", next_ver(), {
        "max_depth": 4, "max_fanout": 1, "max_nonterminal": 8,
    })
    fan = fresh_pair(cur)
    plant_calls(cur, fan, 2)
    check("fanout snapshot false", budget(cur, fan, 2) is False)
    word = hint(cur, fan)
    check("fanout waits", word == "wait", word)
    cur.execute("ROLLBACK TO SAVEPOINT fanout")

    cur.execute("SAVEPOINT depth")
    deep = fresh_pair(cur)
    for _ in range(4):
        deep = insert_one(cur, deep, "ready")
    prefix(cur, deep)
    plant_calls(cur, deep, 1)
    check("depth snapshot false", budget(cur, deep, 1) is False)
    word = hint(cur, deep)
    check("depth waits", word == "wait", word)
    cur.execute("ROLLBACK TO SAVEPOINT depth")

    cur.execute("SAVEPOINT cap")
    root = fresh_pair(cur)
    kids = insert_children(cur, root, 8, "ready")
    control = kids[0]
    target = kids[1]
    prefix(cur, control)
    prefix(cur, target)
    check("full tree snapshot false", budget(cur, control, 1) is False)
    word = hint(cur, control)
    check("full tree without calls runs", word == "run_now", word)
    plant_calls(cur, target, 1)
    check("cap snapshot false", budget(cur, target, 1) is False)
    word = hint(cur, target)
    check("nonroot cap waits", word == "wait", word)
    flip_policy(cur, "spawn_budget", next_ver(), {
        "max_depth": 4, "max_fanout": 8, "max_nonterminal": 100,
    })
    check("budget restored snapshot", budget(cur, target, 1) is True)
    word = hint(cur, target)
    check("budget restored runs", word == "run_now", word)
    cur.execute("ROLLBACK TO SAVEPOINT cap")

    cur.execute("SAVEPOINT policy_err")
    bad = fresh_pair(cur)
    plant_calls(cur, bad, 1)
    cur.execute("UPDATE v13_policies SET active=false WHERE name='spawn_budget' AND active")
    fails_with(
        cur, "SELECT v13_scheduler_hint(%s)", (bad,),
        "v13: spawn_budget policy", "missing budget policy", exact=True)
    cur.execute("ROLLBACK TO SAVEPOINT policy_err")

    cur.execute("SAVEPOINT cycle")
    cyc = u()
    insert_one(cur, cyc, "ready", sid=cyc)
    prefix(cur, cyc)
    plant_calls(cur, cyc, 1)
    fails_with(
        cur, "SELECT v13_scheduler_hint(%s)", (cyc,),
        "v13: spawn root cycle", "hint cycle", exact=True)
    other = open_session(cur)
    plain = fresh_pair(cur)
    check("snapshot two-arg true", budget(cur, plain, 1) is True)
    check("snapshot matching root true", budget(cur, plain, 1, plain) is True)
    fails_with(
        cur, "SELECT v13_spawn_budget_snapshot(%s, 1, %s)", (plain, other),
        "v13: spawn root cycle", "snapshot root mismatch", exact=True)
    cur.execute("ROLLBACK TO SAVEPOINT cycle")

    cur.execute("SAVEPOINT done")
    done = fresh_pair(cur)
    harness_effect(cur, done)
    check("finish no ready", ready_claimed(cur, done) == 0)
    word = advance(cur, done)
    check("closeout terminal", word == "terminal", word)
    check("closeout completed", status_of(cur, done) == "completed")
    word = hint(cur, done)
    check("completed dont_notify", word == "dont_notify", word)
    check("dont_notify in closed set", word in CLOSED)
    cur.execute("ROLLBACK TO SAVEPOINT done")


def test_hint_not_ack(cur):
    sid = fresh_pair(cur)
    seq = int(q1(cur, "SELECT next_seq FROM sessions WHERE session_id=%s", (sid,)))
    before = n_events(cur, sid)
    ack = int(q1(cur, "SELECT count(*) FROM events WHERE type = 'scheduler_ack'"))
    a = hint(cur, sid)
    b = hint(cur, sid)
    check("hint stable word", a == b == "run_now", (a, b))
    check("next_seq unchanged",
          int(q1(cur, "SELECT next_seq FROM sessions WHERE session_id=%s", (sid,))) == seq)
    check("no scheduler_ack",
          int(q1(cur, "SELECT count(*) FROM events WHERE type = 'scheduler_ack'")) == ack)
    check("hint zero new events", n_events(cur, sid) == before)


def test_no_cron_job(cur):
    reg = q1(cur, "SELECT to_regclass('cron.job')")
    sid = fresh_pair(cur)
    if reg is None:
        check("cron.job absent", True)
        check("hint runs without cron", hint(cur, sid) == "run_now")
        return
    before = int(q1(cur, "SELECT count(*) FROM cron.job"))
    hint(cur, sid)
    after = int(q1(cur, "SELECT count(*) FROM cron.job"))
    check("cron.job unchanged", before == after, (before, after))


def test_source(cur):
    sql = (ROOT / "v13_attention.sql").read_text()
    for banned in ("CREATE EXTENSION", "CREATE VIEW", "CREATE TABLE", "MATERIALIZED",
                   "LISTEN", "pg_sleep", "cron.schedule", "COMMENT ON",
                   "goal/stopped", "goal/resumed"):
        check(f"sql lacks {banned}", banned not in sql)
    check("sql does not replace should_run",
          "CREATE OR REPLACE FUNCTION public.v13_should_run" not in sql)
    check("single transaction", "BEGIN;" in sql and sql.strip().endswith("COMMIT;"))
    for sig in (
        "v13_attention(uuid, integer)",
        "v13_scheduler_hint(uuid)",
        "v13_spawn_budget_snapshot(uuid, integer, uuid)",
    ):
        src = prosrc(cur, sig)
        for banned in ("goal/stopped", "pg_sleep", "LISTEN", "INSERT", "UPDATE", "cron.schedule"):
            check(f"{sig} lacks {banned}", banned not in src)
        row = qall(
            cur,
            "SELECT provolatile, prosecdef, proconfig FROM pg_proc WHERE oid = %s::regprocedure",
            (sig,))[0]
        check(f"{sig} stable invoker", row[0] == "s" and row[1] is False, row)
        check(f"{sig} search_path", row[2] == ["search_path=pg_catalog, public"], row[2])
    attn = prosrc(cur, "v13_attention(uuid, integer)")
    hint_src = prosrc(cur, "v13_scheduler_hint(uuid)")
    snap = prosrc(cur, "v13_spawn_budget_snapshot(uuid, integer, uuid)")
    check("attention uses gate not wrapper",
          "v13_should_run_gate" in attn and "v13_should_run(" not in attn)
    check("attention keeps goal_stopped arm", "goal_stopped" in attn)
    check("attention does not call hint", "v13_scheduler_hint" not in attn)
    check("hint does not call attention", "v13_attention" not in hint_src)
    check("hint unknown before duty",
          hint_src.index("unknown session") < hint_src.index("v13_triage_duty"))
    check("hint cancel before inflight",
          hint_src.index("v13_unconsumed_cancel") < hint_src.index("v13_triage_duty"))
    check("hint duty before should_run",
          hint_src.index("v13_triage_duty") < hint_src.index("v13_should_run("))
    check("hint should_run before snapshot",
          hint_src.index("v13_should_run(") < hint_src.index("v13_spawn_budget_snapshot"))
    check("hint no lifecycle", "v13_goal_lifecycle" not in hint_src)
    returns = set()
    for part in hint_src.split("RETURN '")[1:]:
        returns.add(part.split("'", 1)[0])
    check("hint return words closed", returns == CLOSED, returns)
    for banned in ("pg_advisory_xact_lock", "FOR SHARE", "FOR UPDATE"):
        check(f"snapshot no {banned}", banned not in snap)


def test_acl_route(cur):
    sid = fresh_pair(cur)
    sigs = (
        "v13_scheduler_hint(uuid)",
        "v13_attention(uuid, integer)",
        "v13_spawn_budget_snapshot(uuid, integer, uuid)",
    )
    for role, expect in (
        ("v13_route", True),
        ("v13_worker", False),
        ("public", False),
        ("v13_recall", False),
        ("v13_resolve", False),
        ("v13_spawn_owner", False),
    ):
        for sig in sigs:
            got = q1(cur, "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, sig))
            check(f"{sig} {role}", got is expect, got)
    cur.execute("SAVEPOINT route_call")
    cur.execute("SET ROLE v13_route")
    word = hint(cur, sid)
    rows = q1(cur, "SELECT count(*) FROM v13_attention(%s)", (sid,))
    allowed = q1(cur, "SELECT v13_spawn_budget_snapshot(%s, 1)", (sid,))
    cur.execute("RESET ROLE")
    check("route hint", word == "run_now", word)
    check("route attention", int(rows) == 1, rows)
    check("route snapshot", allowed is True, allowed)
    cur.execute("RELEASE SAVEPOINT route_call")
    expect_42501(cur, "v13_worker", "SELECT v13_scheduler_hint(%s)", (sid,), "worker hint 42501")
    expect_42501(cur, "v13_worker", "SELECT count(*) FROM v13_attention(%s)", (sid,),
                 "worker attention 42501")
    expect_42501(
        cur, "v13_spawn_owner", "SELECT v13_spawn_budget_snapshot(%s, 1)", (sid,),
        "spawn_owner snapshot 42501")
    vol = q1(
        cur,
        "SELECT provolatile FROM pg_proc "
        "WHERE oid = 'v13_spawn_budget_snapshot(uuid, integer, uuid)'::regprocedure")
    check("snapshot stable", vol == "s", vol)


def test_attention_large_tree_cost(cur):
    cur.execute("SAVEPOINT large")
    root = open_session(cur)
    insert_children(cur, root, 500, "completed")
    started = time.perf_counter()
    n = int(q1(cur, "SELECT count(*) FROM v13_attention(%s)", (root,)))
    elapsed_ms = (time.perf_counter() - started) * 1000
    check("large tree returned", n >= 500, f"rows={n} ms={elapsed_ms:.1f}")
    cur.execute("ROLLBACK TO SAVEPOINT large")


def test_regression_note(cur):
    check("attention registered 28", STAGE_THROUGH["attention"] == 28)
    check("quota_window still 27", STAGE_THROUGH["quota_window"] == 27)
    print("[note] regression 1-27 is run by the implementer, not this script")


def test_hint_then_advance_rechecks(server):
    a = connect(server)
    b = connect(server)
    try:
        ac = a.cursor()
        sid = fresh_pair(ac)
        ac.execute(
            "SELECT v13_submit_override(%s, %s::jsonb)",
            (sid, json.dumps({
                "schema_version": 1,
                "intent": "decompose",
                "reason": "split",
                "source_principal": "user",
            })))
        a.commit()
        ac = a.cursor()
        word = hint(ac, sid)
        check("pre-flip hint run_now", word == "run_now", word)
        a.commit()
        bc = b.cursor()
        flip_policy(bc, "quota_window", 9001, {
            "schema_version": 1, "window_hours": 8760, "slot_minutes": 0, "allowed": 0,
        })
        b.commit()
        ac = a.cursor()
        effects = n_effects(ac, sid)
        check("flip visible", q1(ac, "SELECT v13_should_run(%s)", (sid,)) is False)
        word = advance(ac, sid)
        check("advance after flip waiting", word == "waiting", word)
        check("advance after flip zero effects", n_effects(ac, sid) == effects)
        a.rollback()
    finally:
        a.close()
        b.close()
        restore = connect(server)
        try:
            rc = restore.cursor()
            rc.execute(
                "UPDATE v13_policies SET active=false "
                "WHERE name='quota_window' AND version<>1")
            rc.execute(
                "UPDATE v13_policies SET active=true "
                "WHERE name='quota_window' AND version=1")
            restore.commit()
        finally:
            restore.close()


def main() -> int:
    global N
    setup_db()
    server = get_server()
    conn = connect(server)
    cur = conn.cursor()
    try:
        test_unknown_root(cur)
        test_attention_limit(cur)
        test_hint_unknown_precedes_bad_policy(cur)
        test_single_root(cur)
        test_rank_human_before_runnable(cur)
        test_rank_not_stored(cur)
        test_hint_matrix(cur)
        test_hint_not_ack(cur)
        test_no_cron_job(cur)
        test_source(cur)
        test_acl_route(cur)
        test_attention_large_tree_cost(cur)
        test_regression_note(cur)
        conn.rollback()
    finally:
        conn.close()
    test_hint_then_advance_rechecks(server)
    print(f"[attention] ALL PASS ({N})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
