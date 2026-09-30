"""Phase A plan_arm gate.

Run: UV_FROZEN=1 uv run python v13/plan_arm/test_plan_arm.py
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v13.load import run_psql
from v13.plan_arm.setup_db import DB, main as setup_db
import v13.plan_arm.setup_db as setup_mod

N = 0
SQL = (ROOT / "v13_plan_arm.sql").read_text()
FINISH = {"result_kind": "finish", "delivery_kind": "LOUD-BUT-BLIND"}
PROGRESS = {"result_kind": "progress"}
WAIT = {"result_kind": "wait", "wait_reason": "evidence",
       "wake": {"kind": "not_before", "at": "2099-01-01T00:00:00Z"}}
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


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def as_obj(value):
    if value is None:
        return None
    if isinstance(value, str):
        return json.loads(value)
    return value


def connect(server):
    conn = psycopg2.connect(server.get_uri(DB))
    conn.autocommit = False
    return conn


def q1(cur, sql, params=None):
    cur.execute(sql, params)
    row = cur.fetchone()
    return None if row is None else row[0]


def open_root(cur, version=1):
    spec = {"route_policy_name": "default", "version": version}
    return str(q1(cur, "SELECT v13_plan_commit_entry(%s::jsonb)", (json.dumps(spec),)))


def prefix(cur, sid, text="hello goal"):
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (sid, u(), json.dumps({"text": text})))


def max_seq(cur, sid):
    return q1(cur, "SELECT max(seq) FROM events WHERE session_id=%s", (sid,))


def plan_n(cur, sid):
    return q1(
        cur,
        "SELECT count(*) FROM events WHERE session_id=%s "
        "AND type IN ('plan/committed','todo/delta')",
        (sid,))


def n_effects(cur, sid=None):
    if sid is None:
        return q1(cur, "SELECT count(*) FROM effects")
    return q1(cur, "SELECT count(*) FROM effects WHERE session_id=%s", (sid,))


def todo(tid, text, cls, status, verb="add_new", due=None):
    return {
        "todo_id": tid,
        "text": text,
        "text_hash": sha(text),
        "task_class": cls,
        "status": status,
        "due": due,
        "verb": verb,
    }


def plan_body(todos, based):
    return {
        "schema_version": 1,
        "call_kind": "plan_commit",
        "based_on_seq": based,
        "supersedes": None,
        "todos": todos,
    }


def writer(cur, sid, canonical, now=None):
    cur.execute(
        "SELECT v13_plan_writer(%s::uuid, %s::uuid, %s::uuid, %s, %s::jsonb, %s::timestamptz)",
        (None, sid, u(), canonical["call_kind"], json.dumps(canonical), now))
    return as_obj(cur.fetchone()[0])


def seed(cur, specs, text="anchor"):
    sid = open_root(cur)
    prefix(cur, sid, text)
    ids = [spec[0] for spec in specs]
    cur.execute("SELECT id::text FROM unnest(%s::uuid[]) AS id ORDER BY id", (ids,))
    ordered = [row[0] for row in cur.fetchall()]
    by_id = {spec[0]: spec for spec in specs}
    body = plan_body([todo(*by_id[tid]) for tid in ordered], max_seq(cur, sid))
    writer(cur, sid, body)
    return sid, ordered


def fresh(cur):
    sid = open_root(cur)
    prefix(cur, sid)
    return sid


def snap_of(cur, sid, remaining=0, include_failed=True, failed=False):
    cur.execute(
        "UPDATE sessions SET context_active_revision = v13_context_required(session_id) "
        "WHERE session_id=%s",
        (sid,))
    cur.execute("SELECT v13_probe(%s)", (sid,))
    probe = cur.fetchone()[0]
    probe["sid"] = sid
    snap = {"snap": probe, "envelope": {"sid": sid}, "remaining": remaining, "abandon": False}
    if include_failed:
        snap["failed"] = failed
    return snap


def advance(cur, sid, remaining=0, include_failed=True, failed=False):
    snap = snap_of(cur, sid, remaining=remaining, include_failed=include_failed, failed=failed)
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid, json.dumps(snap)))
    return cur.fetchone()[0]


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
        "WHERE effect_id=%s RETURNING attempt_no, fence",
        (eid,))
    attempt, fence = cur.fetchone()
    cur.execute(
        "SELECT v13_complete(%s, %s, %s, 'succeeded', %s::jsonb)",
        (eid, attempt, fence, json.dumps(result)))
    return cur.fetchone()[0]


def bind(cur, sid, tid, text, effect_id, status="runnable"):
    canonical = {
        "schema_version": 1,
        "call_kind": "todo_delta",
        "verb": "update",
        "todo_id": tid,
        "status_from": status,
        "status_to": status,
        "binding": {"effect_id": effect_id, "child_session_id": None},
        "due": None,
        "quarantine": None,
        "text_hash": sha(text),
        "link": None,
    }
    writer(cur, sid, canonical)


def fn_hash(cur, sig):
    return q1(
        cur,
        "SELECT encode(digest(convert_to(pg_get_functiondef(%s::regprocedure), 'UTF8'), 'sha256'), 'hex')",
        (sig,))


def load_arm(server):
    run_psql(server, DB, SQL)


def test_hashes_and_source(cur, before):
    after = (
        fn_hash(cur, "public.v13_recover_idle()"),
        fn_hash(cur, "public.v13_goal_fingerprint(uuid)"),
    )
    src = q1(cur, "SELECT pg_get_functiondef('public.v13_advance(uuid,jsonb)'::regprocedure)")
    prefix = q1(cur, "SELECT pg_get_functiondef('public.v13_plan_advance_prefix(uuid)'::regprocedure)")
    check("recover_idle_and_fingerprint_unmodified", before == after, (before, after))
    check(
        "spawn_arm_still_calls_spawn_subsession",
        "v13_spawn_subsession" in src and src.count("v13_spawn_subsession") >= 1)
    check(
        "plan_arm_does_not_call_child_pointer",
        "v13_child_pointer" not in src and "v13_child_pointer" not in prefix and "v13_child_pointer" not in SQL)
    check(
        "live_approval",
        "approval human exists" in src and "v13: approval human exists" in src)
    check(
        "live_continuation",
        "harness_continuation" in src)
    ver = q1(
        cur,
        "SELECT version FROM v13_policies WHERE name = 'should_run' AND active ORDER BY version DESC LIMIT 1")
    check("policy_version_unchanged", ver == 3, ver)
    check(
        "stage_bytes",
        SQL.count("CREATE OR REPLACE FUNCTION public.v13_advance") == 1
        and "CREATE OR REPLACE FUNCTION public.v13_recover_idle" not in SQL
        and "CREATE OR REPLACE FUNCTION public.v13_goal_fingerprint" not in SQL)


def test_stage_bytes():
    paths = [
        "v13/schema", "v13/resolve", "v13/loop", "v13/twophase", "v13/envelope",
        "v13/manifest", "v13/chunks", "v13/recall", "v13/characterize", "v13/filter",
        "v13/memory", "v13/economy", "v13/summary", "v13/periphery", "v13/mgraph",
        "v13/mgraph_assembly", "v13/control", "v13/spawn", "v13/fanout", "v13/triage",
        "v13/seam", "v13/catalog", "v13/acl", "v13/observe", "v13/handoff",
        "v13/should_run", "v13/quota_window", "v13/attention", "v13/govern",
        "docs/plans/v13-long-loop-phase-a-plan-2026-09-29.md",
    ]
    diff = subprocess.check_output(["git", "diff", "HEAD", "--", *paths], cwd=AGENT_ROOT)
    load = subprocess.check_output(["git", "diff", "HEAD", "--", "v13/load.py"], cwd=AGENT_ROOT).decode()
    head_load = subprocess.check_output(
        ["git", "show", "HEAD:v13/load.py"], cwd=AGENT_ROOT).decode()
    removed = [
        line for line in load.splitlines()
        if line.startswith("-") and not line.startswith("---")
    ]
    check(
        "stage_bytes",
        diff == b"" and removed == [] and "plan_arm" in (load + head_load),
        (removed, load, "plan_arm" in head_load))


def harness_req(cur, sid):
    rev = int(q1(cur, "SELECT (v13_probe(%s)->>'tools_revision')::bigint", (sid,)))
    return {
        "tool": "harness_turn",
        "params": {},
        "handler": "worker:harness_turn",
        "tools_revision": rev,
        "logical_turn_id": u(),
        "continuation_index": 0,
    }


def test_live_arms_runtime(cur):
    sid = fresh(cur)
    eid = enqueue(cur, sid, "tool", harness_req(cur, sid), "harness_turn")
    settle(cur, eid, {
        "result_kind": "wait",
        "wait_reason": "approval",
        "interaction_id": "ix-approval-1",
        "delivery_kind": "USER_ACTION_REQUIRED",
    })
    word = advance(cur, sid)
    href = as_obj(q1(
        cur,
        "SELECT request FROM effects WHERE session_id=%s AND kind='human'",
        (sid,)))
    check(
        "live_approval",
        word == "waiting" and href == {"schema_version": 1, "interaction_ref": "ix-approval-1"},
        (word, href))
    sid = fresh(cur)
    eid = enqueue(cur, sid, "tool", harness_req(cur, sid), "harness_turn")
    settle(cur, eid, {"result_kind": "progress", "signals": ["repair/required"]})
    word = advance(cur, sid)
    reason = q1(
        cur,
        "SELECT payload->>'reason' FROM events WHERE session_id=%s AND type='turn/route' "
        "ORDER BY seq DESC LIMIT 1",
        (sid,))
    check("live_continuation", word == "waiting" and reason == "harness_continuation", (word, reason))


def test_no_plan(cur):
    sid = fresh(cur)
    before = plan_n(cur, sid)
    effects = n_effects(cur, sid)
    word = advance(cur, sid)
    sel = q1(
        cur,
        "SELECT count(*) FROM effects WHERE session_id=%s AND request::text LIKE %s",
        (sid, "%selected_todo%"))
    check(
        "no_plan_no_new_effect",
        plan_n(cur, sid) == before and sel == 0 and word in ("waiting", "progressed", "terminal"),
        (word, effects, n_effects(cur, sid)))


def test_live_stop_and_receipt(cur):
    sid = fresh(cur)
    eid = enqueue(cur, sid, "llm", {"route": {"action": "llm", "reason": "answer"}})
    settle(cur, eid, {"text": "ok", "tool_calls": CALL})
    cur.execute("SELECT v13_goal_stop(%s, %s)", (sid, "pause"))
    effects = n_effects(cur, sid)
    word = advance(cur, sid)
    check("live_spawn_stopped", word == "waiting" and n_effects(cur, sid) == effects, word)

    sid = fresh(cur)
    eid = enqueue(
        cur, sid, "tool",
        {
            "tool": "harness_turn",
            "params": {},
            "handler": "worker:harness_turn",
            "tools_revision": 1,
            "logical_turn_id": u(),
            "continuation_index": 0,
        },
        "harness_turn")
    settle(cur, eid, PROGRESS)
    cur.execute("SELECT v13_goal_stop(%s, %s)", (sid, "pause"))
    materials = q1(
        cur, "SELECT count(*) FROM events WHERE session_id=%s AND type='turn/material_spent'", (sid,))
    plans = plan_n(cur, sid)
    word = advance(cur, sid, include_failed=False)
    check(
        "live_receipt",
        word == "waiting"
        and q1(cur, "SELECT count(*) FROM events WHERE session_id=%s AND type='turn/material_spent'", (sid,))
        == materials + 1
        and plan_n(cur, sid) == plans,
        word)
    sid = fresh(cur)
    eid = enqueue(
        cur, sid, "tool",
        {
            "tool": "harness_turn",
            "params": {},
            "handler": "worker:harness_turn",
            "tools_revision": 1,
            "logical_turn_id": u(),
            "continuation_index": 0,
        },
        "harness_turn")
    settle(cur, eid, FINISH)
    cur.execute("SELECT v13_goal_stop(%s, %s)", (sid, "pause"))
    plans = plan_n(cur, sid)
    word = advance(cur, sid, include_failed=False)
    check(
        "live_finish_stopped_without_failed_key",
        word == "terminal" and plan_n(cur, sid) == plans,
        word)


def test_dispatch_and_bind(cur):
    tid = u()
    sid, _ids = seed(cur, [(tid, "do work", "advancement_task", "runnable")])
    before = n_effects(cur, sid)
    word = advance(cur, sid)
    kind = q1(
        cur,
        "SELECT kind FROM effects WHERE session_id=%s AND request::text LIKE %s",
        (sid, "%selected_todo%"))
    check(
        "dispatch_kind",
        word == "waiting" and kind == "llm" and n_effects(cur, sid) == before + 1,
        (word, kind))
    again = n_effects(cur, sid)
    word2 = advance(cur, sid)
    check("bind_once", word2 == "waiting" and n_effects(cur, sid) == again, word2)

    ot = u()
    sid, _ids = seed(cur, [(ot, "ask", "user_gate", "runnable")])
    advance(cur, sid)
    okind = q1(
        cur,
        "SELECT kind FROM effects WHERE session_id=%s AND request::text LIKE %s",
        (sid, "%selected_todo%"))
    check("dispatch_kind", okind == "human", okind)

    nt = u()
    sid, _ids = seed(cur, [(nt, "later", "advancement_task", "pending")])
    before = n_effects(cur, sid)
    advance(cur, sid)
    sel = q1(
        cur,
        "SELECT count(*) FROM effects WHERE session_id=%s AND request::text LIKE %s",
        (sid, "%selected_todo%"))
    check("dispatch_kind", sel == 0, (before, n_effects(cur, sid), sel))


def test_archive_and_child(cur):
    tid = u()
    sid, ids = seed(cur, [(tid, "chain", "advancement_task", "runnable")])
    eid = enqueue(cur, sid, "llm", {"route": {"action": "llm", "reason": "answer"}})
    settle(cur, eid, {"text": "ok", "tool_calls": CALL})
    plans = plan_n(cur, sid)
    cur.execute("SET ROLE v13_route")
    word = advance(cur, sid)
    cur.execute("RESET ROLE")
    check("archive_child_excerpt_done", word == "progressed" and plan_n(cur, sid) == plans, word)
    cur.execute("SELECT session_id::text FROM sessions WHERE parent_session_id=%s", (sid,))
    child = cur.fetchone()[0]
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'workflow/pointer', %s::jsonb)",
        (child, u(), json.dumps({
            "schema_version": 1,
            "parent_session_id": sid,
            "root_session_id": sid,
            "todo_id": ids[0],
            "up_to_seq": 0,
        })))
    plans_before_child = plan_n(cur, sid)
    word = advance(cur, child)
    read_id = q1(
        cur,
        "SELECT effect_id::text FROM effects WHERE session_id=%s AND tool_name='read_file_py'",
        (child,))
    calls = q1(cur, "SELECT count(*) FROM events WHERE session_id=%s AND type='tool/call'", (child,))
    check(
        "child_read_effect_not_tool_call",
        word == "waiting" and read_id is not None and calls == 0 and plan_n(cur, sid) == plans_before_child,
        (word, read_id, calls))
    check("child_skips_arm", plan_n(cur, child) == 0 and plan_n(cur, sid) == plans_before_child)
    settle(cur, read_id, {"excerpt": "bounded text"})
    effects = n_effects(cur, sid)
    word = advance(cur, sid)
    status = q1(cur, "SELECT status FROM v13_plan_todo_fold(%s) WHERE todo_id=%s", (sid, ids[0]))
    deltas = q1(
        cur,
        "SELECT count(*) FROM events WHERE session_id=%s AND type='todo/delta' "
        "AND payload->'canonical'->>'status_to'='done'",
        (sid,))
    check(
        "archive_child_excerpt_done",
        word == "waiting" and status == "done" and deltas == 1 and n_effects(cur, sid) == effects,
        (word, status, deltas))

    tid = u()
    text = "progress me"
    sid, ids = seed(cur, [(tid, text, "advancement_task", "runnable")])
    eid = enqueue(
        cur, sid, "tool",
        {
            "tool": "harness_turn",
            "params": {},
            "handler": "worker:harness_turn",
            "tools_revision": 1,
            "logical_turn_id": u(),
            "continuation_index": 0,
        },
        "harness_turn")
    settle(cur, eid, PROGRESS)
    bind(cur, sid, ids[0], text, eid)
    effects = n_effects(cur, sid)
    word = advance(cur, sid)
    status = q1(cur, "SELECT status FROM v13_plan_todo_fold(%s) WHERE todo_id=%s", (sid, ids[0]))
    check("archive_progress", status == "done" and word in ("waiting", "terminal", "progressed"), (word, status))

    tid = u()
    text = "finish me"
    sid, ids = seed(cur, [(tid, text, "advancement_task", "runnable")])
    eid = enqueue(
        cur, sid, "tool",
        {
            "tool": "harness_turn",
            "params": {},
            "handler": "worker:harness_turn",
            "tools_revision": 1,
            "logical_turn_id": u(),
            "continuation_index": 0,
        },
        "harness_turn")
    settle(cur, eid, FINISH)
    bind(cur, sid, ids[0], text, eid)
    effects = n_effects(cur, sid)
    word = advance(cur, sid)
    status = q1(cur, "SELECT status FROM v13_plan_todo_fold(%s) WHERE todo_id=%s", (sid, ids[0]))
    check(
        "archive_when_not_reselected",
        status == "done" and n_effects(cur, sid) == effects and word == "terminal",
        (word, status, effects, n_effects(cur, sid)))
    tid = u()
    text = "wait me"
    sid, ids = seed(cur, [(tid, text, "advancement_task", "runnable")])
    eid = enqueue(
        cur, sid, "tool",
        {
            "tool": "harness_turn",
            "params": {},
            "handler": "worker:harness_turn",
            "tools_revision": 1,
            "logical_turn_id": u(),
            "continuation_index": 0,
        },
        "harness_turn")
    settle(cur, eid, WAIT)
    bind(cur, sid, ids[0], text, eid)
    plans = plan_n(cur, sid)
    advance(cur, sid)
    check("archive_when_not_reselected", plan_n(cur, sid) == plans)

    mid = u()
    sid, ids = seed(cur, [(mid, "watch", "continuous_monitor", "waiting", "add_new", "2099-01-01T00:00:00Z")])
    plans = plan_n(cur, sid)
    advance(cur, sid)
    status = q1(cur, "SELECT status FROM v13_plan_todo_fold(%s) WHERE todo_id=%s", (sid, ids[0]))
    check("monitor_due_not_guessed", plan_n(cur, sid) == plans and status == "waiting", status)


def test_reenable(cur):
    tid = u()
    text = "again"
    sid, ids = seed(cur, [(tid, text, "advancement_task", "runnable")])
    eid = enqueue(cur, sid, "llm", {"route": {"action": "llm", "reason": "old"}})
    settle(cur, eid, {"text": "no"})
    cur.execute("UPDATE effects SET status='failed' WHERE effect_id=%s", (eid,))
    bind(cur, sid, ids[0], text, eid)
    writer(cur, sid, {
        "schema_version": 1,
        "call_kind": "todo_delta",
        "verb": "update",
        "todo_id": ids[0],
        "status_from": "runnable",
        "status_to": "blocked",
        "binding": None,
        "due": None,
        "quarantine": {"effect_id": eid, "cleared": False},
        "text_hash": sha(text),
        "link": None,
    })
    writer(cur, sid, {
        "schema_version": 1,
        "call_kind": "todo_delta",
        "verb": "update",
        "todo_id": ids[0],
        "status_from": "blocked",
        "status_to": "runnable",
        "binding": {"clear_binding": True},
        "due": None,
        "quarantine": {"effect_id": eid, "cleared": True},
        "text_hash": sha(text),
        "link": None,
    })
    before = {
        row[0] for row in q1_all(cur, "SELECT effect_id::text FROM effects WHERE session_id=%s", (sid,))
    }
    word = advance(cur, sid)
    new_id = q1(
        cur,
        "SELECT effect_id::text FROM effects WHERE session_id=%s AND request::text LIKE %s",
        (sid, "%selected_todo%"))
    check(
        "reenable_binds_new_effect",
        word == "waiting" and new_id is not None and new_id not in before,
        (word, new_id))


def q1_all(cur, sql, params=None):
    cur.execute(sql, params)
    return cur.fetchall()


def fold_of(cur, sid, tid):
    cur.execute(
        "SELECT status, due, quarantine FROM v13_plan_todo_fold(%s) WHERE todo_id=%s",
        (sid, tid))
    status, due, quarantine = cur.fetchone()
    return status, due, as_obj(quarantine)


def open_session(cur, status="ready"):
    sid = str(q1(cur, "SELECT v13_open_session(%s::jsonb)", ('{"version":1}',)))
    if status != "ready":
        cur.execute("UPDATE sessions SET status=%s WHERE session_id=%s", (status, sid))
    return sid


def insert_effect(cur, sid, eid, kind, status, result=None, tool_name=None):
    cur.execute(
        "INSERT INTO effects (effect_id, session_id, kind, tool_name, request, request_hash, "
        "origin_user_seq, status, result) "
        "VALUES (%s, %s, %s, %s, %s::jsonb, %s, 0, %s, %s::jsonb)",
        (eid, sid, kind, tool_name, '{"fixture":true}', "fixture", status,
         None if result is None else json.dumps(result)))


def bind_child(cur, sid, tid, text, child, status="runnable"):
    writer(cur, sid, {
        "schema_version": 1,
        "call_kind": "todo_delta",
        "verb": "update",
        "todo_id": tid,
        "status_from": status,
        "status_to": status,
        "binding": {"effect_id": None, "child_session_id": child},
        "due": None,
        "quarantine": None,
        "text_hash": sha(text),
        "link": None,
    })


def promote_monitor(cur, sid, tid, text):
    writer(cur, sid, {
        "schema_version": 1,
        "call_kind": "todo_delta",
        "verb": "update",
        "todo_id": tid,
        "status_from": "waiting",
        "status_to": "runnable",
        "binding": None,
        "due": None,
        "quarantine": None,
        "text_hash": sha(text),
        "link": None,
    }, now="2026-09-30T00:00:00Z")


def test_p1_fixes(cur):
    noop_id = "00000000-0000-4000-8000-000000000001"
    hold_id = "00000000-0000-4000-8000-000000000002"
    other = open_session(cur)
    insert_effect(cur, other, hold_id, "llm", "ready")
    tid_noop, tid_arch, tid_hold = u(), u(), u()
    text_noop, text_arch, text_hold = "noop", "archive", "hold"
    sid, ids = seed(cur, [
        (tid_noop, text_noop, "advancement_task", "runnable"),
        (tid_arch, text_arch, "advancement_task", "runnable"),
        (tid_hold, text_hold, "advancement_task", "runnable"),
    ])
    by = {tid_noop: text_noop, tid_arch: text_arch, tid_hold: text_hold}
    insert_effect(
        cur, sid, noop_id, "llm", "succeeded",
        {"text": "x", "result_kind": "progress"})
    eid = enqueue(cur, sid, "tool", harness_req(cur, sid), "harness_turn")
    settle(cur, eid, FINISH)
    check("bound_scan_effect_order", noop_id < eid and hold_id < eid, (noop_id, hold_id, eid))
    bind(cur, sid, tid_noop, by[tid_noop], noop_id)
    bind(cur, sid, tid_arch, by[tid_arch], eid)
    bind(cur, sid, tid_hold, by[tid_hold], hold_id)
    effects = n_effects(cur, sid)
    word = advance(cur, sid)
    st_noop, _, _ = fold_of(cur, sid, tid_noop)
    st_arch, _, _ = fold_of(cur, sid, tid_arch)
    st_hold, _, _ = fold_of(cur, sid, tid_hold)
    sel = q1(
        cur,
        "SELECT count(*) FROM effects WHERE session_id=%s AND request::text LIKE %s",
        (sid, "%selected_todo%"))
    check("bound_scan_past_noop", st_arch == "done" and st_noop == "runnable", (st_arch, st_noop))
    check("non_harness_not_archive_pair", st_noop == "runnable", st_noop)
    check(
        "archive_skips_inflight_waiting",
        word == "terminal" and sel == 0 and n_effects(cur, sid) == effects and st_hold == "runnable",
        (word, sel, effects, n_effects(cur, sid), st_hold))

    tid = u()
    text = "fail me"
    sid, ids = seed(cur, [(tid, text, "advancement_task", "runnable")])
    eid = enqueue(cur, sid, "llm", {"route": {"action": "llm", "reason": "old"}})
    settle(cur, eid, {"text": "no"})
    cur.execute("UPDATE effects SET status='failed' WHERE effect_id=%s", (eid,))
    bind(cur, sid, ids[0], text, eid)
    plans = plan_n(cur, sid)
    advance(cur, sid)
    status, _, quarantine = fold_of(cur, sid, ids[0])
    check(
        "isolate_runnable_failed",
        status == "blocked" and quarantine == {"cleared": False, "effect_id": eid}
        and plan_n(cur, sid) == plans + 1,
        (status, quarantine, plan_n(cur, sid), plans))
    plans = plan_n(cur, sid)
    advance(cur, sid)
    check("isolate_skips_uncleared", plan_n(cur, sid) == plans, plan_n(cur, sid))

    tid = u()
    text = "stay blocked"
    sid, ids = seed(cur, [(tid, text, "advancement_task", "runnable")])
    eid = enqueue(cur, sid, "llm", {"route": {"action": "llm", "reason": "old"}})
    settle(cur, eid, {"text": "no"})
    cur.execute("UPDATE effects SET status='cancelled' WHERE effect_id=%s", (eid,))
    bind(cur, sid, ids[0], text, eid)
    writer(cur, sid, {
        "schema_version": 1,
        "call_kind": "todo_delta",
        "verb": "update",
        "todo_id": ids[0],
        "status_from": "runnable",
        "status_to": "blocked",
        "binding": None,
        "due": None,
        "quarantine": None,
        "text_hash": sha(text),
        "link": None,
    })
    plans = plan_n(cur, sid)
    advance(cur, sid)
    status, _, quarantine = fold_of(cur, sid, ids[0])
    check(
        "isolate_blocked_same_status",
        status == "blocked" and quarantine == {"cleared": False, "effect_id": eid}
        and plan_n(cur, sid) == plans + 1,
        (status, quarantine))

    tid = u()
    text = "stay pending"
    sid, ids = seed(cur, [(tid, text, "advancement_task", "pending")])
    eid = enqueue(cur, sid, "llm", {"route": {"action": "llm", "reason": "old"}})
    settle(cur, eid, {"text": "no"})
    cur.execute("UPDATE effects SET status='failed' WHERE effect_id=%s", (eid,))
    plan_id = q1(
        cur,
        "SELECT payload->>'plan_id' FROM events WHERE session_id=%s AND type='plan/committed'",
        (sid,))
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'todo/delta', %s::jsonb)",
        (sid, u(), json.dumps({
            "apply_id": u(),
            "call_kind": "todo_delta",
            "canonical": {
                "schema_version": 1,
                "call_kind": "todo_delta",
                "verb": "update",
                "todo_id": ids[0],
                "status_from": "pending",
                "status_to": "pending",
                "binding": {"effect_id": eid, "child_session_id": None},
                "due": None,
                "quarantine": None,
                "text_hash": sha(text),
                "link": None,
            },
            "plan_id": plan_id,
            "todo_id": ids[0],
        })))
    plans = plan_n(cur, sid)
    advance(cur, sid)
    status, _, quarantine = fold_of(cur, sid, ids[0])
    check(
        "isolate_pending_same_status",
        status == "pending" and quarantine == {"cleared": False, "effect_id": eid}
        and plan_n(cur, sid) == plans + 1,
        (status, quarantine, plan_n(cur, sid), plans))

    tid = u()
    text = "watch fail"
    due = "2020-01-01T00:00:00Z"
    sid, ids = seed(cur, [(tid, text, "continuous_monitor", "waiting", "add_new", due)])
    promote_monitor(cur, sid, ids[0], text)
    eid = enqueue(cur, sid, "llm", {"route": {"action": "llm", "reason": "old"}})
    settle(cur, eid, {"text": "no"})
    cur.execute("UPDATE effects SET status='failed' WHERE effect_id=%s", (eid,))
    bind(cur, sid, ids[0], text, eid)
    plans = plan_n(cur, sid)
    advance(cur, sid)
    status, due_now, quarantine = fold_of(cur, sid, ids[0])
    check(
        "isolate_monitor_failed",
        status == "blocked" and quarantine == {"cleared": False, "effect_id": eid}
        and due_now == due and plan_n(cur, sid) == plans + 1,
        (status, due_now, quarantine))

    tid = u()
    text = "watch ok"
    sid, ids = seed(cur, [(tid, text, "continuous_monitor", "waiting", "add_new", due)])
    promote_monitor(cur, sid, ids[0], text)
    eid = enqueue(cur, sid, "tool", harness_req(cur, sid), "harness_turn")
    settle(cur, eid, PROGRESS)
    bind(cur, sid, ids[0], text, eid)
    plans = plan_n(cur, sid)
    advance(cur, sid)
    status, due_now, quarantine = fold_of(cur, sid, ids[0])
    check(
        "monitor_success_writes_nothing",
        status == "runnable" and due_now == due and quarantine is None and plan_n(cur, sid) == plans,
        (status, due_now, quarantine, plan_n(cur, sid), plans))

    tid = u()
    text = "already done"
    sid, ids = seed(cur, [(tid, text, "advancement_task", "runnable")])
    eid = enqueue(cur, sid, "llm", {"route": {"action": "llm", "reason": "old"}})
    settle(cur, eid, {"text": "no"})
    bind(cur, sid, ids[0], text, eid)
    writer(cur, sid, {
        "schema_version": 1,
        "call_kind": "todo_delta",
        "verb": "update",
        "todo_id": ids[0],
        "status_from": "runnable",
        "status_to": "done",
        "binding": None,
        "due": None,
        "quarantine": None,
        "text_hash": sha(text),
        "link": None,
    })
    cur.execute("UPDATE effects SET status='failed' WHERE effect_id=%s", (eid,))
    plans = plan_n(cur, sid)
    advance(cur, sid)
    status, _, quarantine = fold_of(cur, sid, ids[0])
    check(
        "isolate_skips_done",
        status == "done" and quarantine is None and plan_n(cur, sid) == plans,
        (status, quarantine, plan_n(cur, sid), plans))

    done_id, live_id = u(), u()
    sid, ids = seed(cur, [
        (done_id, "old excerpt", "advancement_task", "runnable"),
        (live_id, "new excerpt", "advancement_task", "runnable"),
    ])
    writer(cur, sid, {
        "schema_version": 1,
        "call_kind": "todo_delta",
        "verb": "update",
        "todo_id": done_id,
        "status_from": "runnable",
        "status_to": "done",
        "binding": None,
        "due": None,
        "quarantine": None,
        "text_hash": sha("old excerpt"),
        "link": None,
    })
    spawned = as_obj(q1(
        cur,
        "SELECT v13_spawn_subsession(%s, %s::jsonb)",
        (sid, json.dumps({
            "schema_version": 1,
            "children": [
                {"tool_call_id": "old", "task": "old"},
                {"tool_call_id": "new", "task": "new"},
            ],
        }))))
    by_call = {row["tool_call_id"]: row["session_id"] for row in spawned["children"]}
    old_child, new_child = by_call["old"], by_call["new"]
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'workflow/pointer', %s::jsonb)",
        (old_child, u(), json.dumps({
            "schema_version": 1, "parent_session_id": sid, "root_session_id": sid,
            "todo_id": done_id, "up_to_seq": 0,
        })))
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'fixture/pad', %s::jsonb)",
        (new_child, u(), json.dumps({"n": 1})))
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'workflow/pointer', %s::jsonb)",
        (new_child, u(), json.dumps({
            "schema_version": 1, "parent_session_id": sid, "root_session_id": sid,
            "todo_id": live_id, "up_to_seq": 0,
        })))
    insert_effect(cur, old_child, u(), "tool", "succeeded", {"excerpt": "old"}, "read_file_py")
    insert_effect(cur, new_child, u(), "tool", "succeeded", {"excerpt": "new"}, "read_file_py")
    effects = n_effects(cur, sid)
    word = advance(cur, sid)
    status, _, _ = fold_of(cur, sid, live_id)
    check(
        "child_excerpt_skips_historical_pointer",
        word == "waiting" and status == "done" and n_effects(cur, sid) == effects,
        (word, status, effects, n_effects(cur, sid)))

    small, large = sorted((u(), u()))
    sid, ids = seed(cur, [
        (small, "bound child", "advancement_task", "runnable"),
        (large, "free", "advancement_task", "runnable"),
    ])
    child = open_session(cur, "completed")
    bind_child(cur, sid, small, "bound child", child)
    word = advance(cur, sid)
    picked = q1(
        cur,
        "SELECT request->>'todo_id' FROM effects WHERE session_id=%s AND request::text LIKE %s",
        (sid, "%selected_todo%"))
    check("selector_excludes_terminal_child", word == "waiting" and picked == large, (word, picked, large))
    for child_status in ("failed", "cancelled", "ready"):
        tid = u()
        text = "only " + child_status
        sid, ids = seed(cur, [(tid, text, "advancement_task", "runnable")])
        child = open_session(cur, child_status)
        bind_child(cur, sid, ids[0], text, child)
        nsel = q1(cur, "SELECT count(*) FROM v13_selected_todo(%s)", (sid,))
        check("selector_excludes_terminal_child", nsel == 0, (child_status, nsel))


def run(cur, server):
    before = (
        fn_hash(cur, "public.v13_recover_idle()"),
        fn_hash(cur, "public.v13_goal_fingerprint(uuid)"),
    )
    load_arm(server)
    test_hashes_and_source(cur, before)
    test_stage_bytes()
    test_live_arms_runtime(cur)
    test_no_plan(cur)
    test_live_stop_and_receipt(cur)
    test_dispatch_and_bind(cur)
    test_archive_and_child(cur)
    test_reenable(cur)
    test_p1_fixes(cur)
    cur.execute("COMMIT")


def main() -> int:
    print("[db]", DB)
    if setup_db() != 0:
        return 1
    server = get_server()
    conn = connect(server)
    try:
        run(conn.cursor(), server)
    finally:
        conn.close()
        if setup_mod.CREATED:
            run_psql(server, "postgres", f'DROP DATABASE "{DB}" WITH (FORCE);')
            setup_mod.CREATED = False
            print("[dropped]", DB)
    print(f"[ok] {N} checks")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[FAIL] {exc}")
        if setup_mod.CREATED:
            try:
                run_psql(get_server(), "postgres", f'DROP DATABASE "{DB}" WITH (FORCE);')
                print("[dropped]", DB)
            except Exception as drop_exc:
                print("[cleanup-fail]", drop_exc)
        raise SystemExit(1)
