"""Phase A workflow_bind gate.

Run: UV_FROZEN=1 uv run python v13/workflow_bind/test_workflow_bind.py
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import uuid
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v13.load import run_psql
from v13.workflow_bind.setup_db import DB, main as setup_db
import v13.workflow_bind.setup_db as setup_mod

N = 0
SQL = (ROOT / "v13_workflow_bind.sql").read_text()
LAYER_ORDER = ("assertion", "assembly", "judgment", "workflow")
FORBIDDEN = ("skip", "workflow_id", "plan/committed", "insert")
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


def fn_hash(cur, sig):
    return q1(
        cur,
        "SELECT encode(digest(convert_to(pg_get_functiondef(%s::regprocedure), 'UTF8'), 'sha256'), 'hex')",
        (sig,))


def expect_raise(cur, sql, params, needle):
    cur.execute("SAVEPOINT sp_expect")
    try:
        cur.execute(sql, params)
    except psycopg2.Error as exc:
        msg = exc.diag.message_primary or str(exc).splitlines()[0]
        cur.execute("ROLLBACK TO SAVEPOINT sp_expect")
        return msg == needle, msg
    cur.execute("ROLLBACK TO SAVEPOINT sp_expect")
    return False, "no error"


def expect_pgcode(cur, sql, params, code):
    cur.execute("SAVEPOINT sp_code")
    try:
        cur.execute(sql, params)
    except psycopg2.Error as exc:
        got = exc.pgcode
        cur.execute("ROLLBACK TO SAVEPOINT sp_code")
        return got == code, got
    cur.execute("ROLLBACK TO SAVEPOINT sp_code")
    return False, "no error"


def open_root(cur):
    spec = {"route_policy_name": "default", "version": 1}
    return str(q1(cur, "SELECT v13_plan_commit_entry(%s::jsonb)", (json.dumps(spec),)))


def prefix(cur, sid, text):
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (sid, u(), json.dumps({"text": text})))


def max_seq(cur, sid):
    return q1(cur, "SELECT max(seq) FROM events WHERE session_id=%s", (sid,))


def insert_child(cur, parent):
    cur.execute("SAVEPOINT sp_child")
    cur.execute("SET ROLE v13_spawn_owner")
    cur.execute(
        "INSERT INTO sessions (parent_session_id, route_policy_name, route_policy_version) "
        "VALUES (%s, 'default', 1) RETURNING session_id",
        (parent,))
    child = str(cur.fetchone()[0])
    cur.execute("RESET ROLE")
    cur.execute("RELEASE SAVEPOINT sp_child")
    return child


def commit_plan(cur, sid, text):
    tid = u()
    body = {
        "schema_version": 1,
        "call_kind": "plan_commit",
        "based_on_seq": max_seq(cur, sid),
        "supersedes": None,
        "todos": [{
            "todo_id": tid,
            "text": text,
            "text_hash": sha(text),
            "task_class": "advancement_task",
            "status": "runnable",
            "due": None,
            "verb": "add_new",
        }],
    }
    cur.execute(
        "SELECT v13_plan_writer(%s::uuid, %s::uuid, %s::uuid, %s, %s::jsonb, %s::timestamptz)",
        (None, sid, u(), "plan_commit", json.dumps(body), None))
    out = as_obj(cur.fetchone()[0])
    return tid, out["plan_id"]


def seed(cur, text="parent-transcript-not-for-child"):
    sid = open_root(cur)
    prefix(cur, sid, text)
    tid, plan_id = commit_plan(cur, sid, "plan-canonical-not-for-pointer")
    child = insert_child(cur, sid)
    return sid, child, tid, plan_id


def pointer(cur, child, parent, root, tid, up_to):
    cur.execute(
        "SELECT v13_child_pointer(%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s)",
        (child, parent, root, tid, up_to))
    return str(cur.fetchone()[0])


def n_type(cur, sid, typ):
    return q1(
        cur,
        "SELECT count(*) FROM events WHERE session_id=%s AND type=%s",
        (sid, typ))


def jt_snap(cur):
    cols = q1(
        cur,
        "SELECT array_agg(attname ORDER BY attnum) FROM pg_attribute "
        "WHERE attrelid = 'public.judgment_templates'::regclass "
        "AND attnum > 0 AND NOT attisdropped")
    digest = q1(
        cur,
        "SELECT md5(coalesce(string_agg("
        "template_name || ':' || template_version::text || ':' || kind || ':' || "
        "coalesce(question, ''), '|' ORDER BY template_name, template_version), '')) "
        "FROM judgment_templates")
    count = q1(cur, "SELECT count(*) FROM judgment_templates")
    return (tuple(cols), digest, count)


def tools_snap(cur):
    cur.execute(
        "SELECT name, enabled, kind, handler FROM tools ORDER BY name")
    rows = tuple(cur.fetchall())
    rev = q1(cur, "SELECT revision FROM v13_tools_meta WHERE singleton")
    return rows, rev


def test_resolve_v1(cur):
    before = (
        q1(cur, "SELECT count(*) FROM sessions"),
        q1(cur, "SELECT count(*) FROM events"),
        q1(cur, "SELECT count(*) FROM effects"),
        q1(cur, "SELECT count(*) FROM v13_policies"),
    )
    policy = as_obj(q1(
        cur,
        "SELECT value FROM v13_policies WHERE name='workflow_template' AND version=1 AND active"))
    got = as_obj(q1(cur, "SELECT v13_workflow_resolve('workflow_template', 1)"))
    after = (
        q1(cur, "SELECT count(*) FROM sessions"),
        q1(cur, "SELECT count(*) FROM events"),
        q1(cur, "SELECT count(*) FROM effects"),
        q1(cur, "SELECT count(*) FROM v13_policies"),
    )
    policy_after = as_obj(q1(
        cur,
        "SELECT value FROM v13_policies WHERE name='workflow_template' AND version=1 AND active"))
    vol = q1(
        cur,
        "SELECT provolatile FROM pg_proc WHERE oid = 'public.v13_workflow_resolve(text,integer)'::regprocedure")
    src = q1(
        cur,
        "SELECT pg_get_functiondef('public.v13_workflow_resolve(text,integer)'::regprocedure)")
    keys = q1(cur, "SELECT v13_json_keys(%s::jsonb)", (json.dumps(got),))
    texts = [got[name] for name in LAYER_ORDER]
    joined = "\n".join(texts)
    forbidden_hit = [
        word for word in FORBIDDEN
        for text in texts
        if word in text.lower()
    ]
    missing_ok, missing_msg = expect_raise(
        cur, "SELECT v13_workflow_resolve('workflow_template', 99)", None,
        "v13: workflow resolve: missing")
    cur.execute("SAVEPOINT sp_inactive")
    cur.execute(
        "INSERT INTO v13_policies (name, version, value, active) "
        "VALUES ('workflow_template', 2, '{}'::jsonb, false)")
    inactive_ok, inactive_msg = expect_raise(
        cur, "SELECT v13_workflow_resolve('workflow_template', 2)", None,
        "v13: workflow resolve: inactive")
    cur.execute("ROLLBACK TO SAVEPOINT sp_inactive")
    cur.execute("SAVEPOINT sp_canon")
    cur.execute(
        "UPDATE v13_policies SET active = false "
        "WHERE name = 'workflow_template' AND version = 1")
    cur.execute(
        "INSERT INTO v13_policies (name, version, value, active) "
        "VALUES ('workflow_template', 3, '{\"schema_version\": 1}'::jsonb, true)")
    canon_ok, canon_msg = expect_raise(
        cur, "SELECT v13_workflow_resolve('workflow_template', 3)", None,
        "v13: workflow resolve: canonical")
    cur.execute("ROLLBACK TO SAVEPOINT sp_canon")
    still = as_obj(q1(
        cur,
        "SELECT value FROM v13_policies WHERE name='workflow_template' AND active"))
    ok = (
        before == after
        and policy == policy_after == still
        and vol == "s"
        and "INSERT" not in src and "UPDATE" not in src and "DELETE" not in src
        and "judgment_templates" not in src
        and "v13_append_event" not in src
        and list(keys) == ["assembly", "assertion", "judgment", "workflow"]
        and all(isinstance(text, str) and text.strip() for text in texts)
        and texts == [policy["layers"][name] for name in LAYER_ORDER]
        and got != joined
        and "SYSTEM_PROMPT" not in json.dumps(got)
        and not forbidden_hit
        and policy["labels"] == ["read_only"]
        and policy["allowed_tools"] == [
            "read_pi", "read_file_swift", "read_file_py", "read_duck"]
        and policy["parent_tools"] == ["spawn_subsession"]
        and policy["chain"] == "first_real_chain"
        and policy["schema_version"] == 1
        and missing_ok and inactive_ok and canon_ok
        and "CREATE OR REPLACE" not in SQL
        and "v13_advance" not in SQL
    )
    check(
        "resolve_v1",
        ok,
        (vol, keys, forbidden_hit, missing_msg, inactive_msg, canon_msg, before, after))


def test_label_does_not_open_explore(cur):
    labels = as_obj(q1(
        cur,
        "SELECT value->'labels' FROM v13_policies "
        "WHERE name='workflow_template' AND version=1 AND active"))
    src = q1(
        cur,
        "SELECT pg_get_functiondef('public.v13_triage_block_explore_spawn(uuid)'::regprocedure)")
    sid = open_root(cur)
    prefix(cur, sid, "explore label fixture")
    eid = q1(
        cur,
        "SELECT v13_enqueue_effect(%s, 'llm', %s::jsonb)",
        (sid, json.dumps({"route": {"action": "llm", "reason": "explore"}})))
    cur.execute(
        "UPDATE effects SET status='claimed', attempt_no=attempt_no+1, fence=fence+1, "
        "lease_owner='w', lease_until=clock_timestamp()+interval '1 hour' "
        "WHERE effect_id=%s RETURNING attempt_no, fence",
        (eid,))
    attempt, fence = cur.fetchone()
    cur.execute(
        "SELECT v13_complete(%s, %s, %s, 'succeeded', %s::jsonb)",
        (eid, attempt, fence, json.dumps({"text": "ok", "tool_calls": CALL})))
    cur.fetchone()
    raised, msg = expect_raise(
        cur, "SELECT v13_triage_block_explore_spawn(%s)", (sid,),
        "v13: explore spawn")
    tools_named = q1(cur, "SELECT count(*) FROM tools WHERE name = 'read_only'")
    ok = (
        labels == ["read_only"]
        and "v13: explore spawn" in src
        and "workflow_template" not in src
        and "read_only" not in src
        and "v13_triage_block_explore_spawn" not in SQL
        and raised
        and tools_named == 0
    )
    check("label_does_not_open_explore", ok, (labels, msg, tools_named))


def test_one_pointer(cur):
    sid, child, tid, _plan = seed(cur)
    other = insert_child(cur, sid)
    up_to = max_seq(cur, sid)
    before = n_type(cur, child, "workflow/pointer")
    eid = pointer(cur, child, sid, sid, tid, up_to)
    seq_before = q1(cur, "SELECT next_seq FROM sessions WHERE session_id=%s", (child,))
    again = pointer(cur, child, sid, sid, tid, up_to)
    seq_after = q1(cur, "SELECT next_seq FROM sessions WHERE session_id=%s", (child,))
    other_id = pointer(cur, other, sid, sid, tid, up_to)
    conflict_ok, conflict_msg = expect_raise(
        cur,
        "SELECT v13_child_pointer(%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s)",
        (child, sid, sid, tid, up_to + 1),
        "v13: workflow pointer: replay_conflict")
    raw_ok, raw_code = expect_pgcode(
        cur,
        "SELECT v13_append_event(%s, %s, 'workflow/pointer', %s::jsonb)",
        (child, u(), json.dumps({
            "schema_version": 1,
            "parent_session_id": sid,
            "root_session_id": sid,
            "todo_id": tid,
            "up_to_seq": up_to,
        })),
        "23505")
    stopped = insert_child(cur, sid)
    cur.execute("SELECT v13_goal_stop(%s, %s)", (stopped, "pause"))
    cur.fetchone()
    stop_ok, stop_msg = expect_raise(
        cur,
        "SELECT v13_child_pointer(%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s)",
        (stopped, sid, sid, tid, up_to),
        "v13: workflow pointer: stopped")
    terminal_ok = True
    terminal_msg = ""
    for status in ("completed", "failed", "cancelled"):
        term = insert_child(cur, sid)
        cur.execute(
            "UPDATE sessions SET status=%s WHERE session_id=%s",
            (status, term))
        ok, msg = expect_raise(
            cur,
            "SELECT v13_child_pointer(%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s)",
            (term, sid, sid, tid, up_to),
            "v13: workflow pointer: terminal")
        terminal_ok = terminal_ok and ok and n_type(cur, term, "workflow/pointer") == 0
        terminal_msg = msg
    root_events = q1(cur, "SELECT count(*) FROM events WHERE session_id=%s", (sid,))
    not_child_ok, not_child_msg = expect_raise(
        cur,
        "SELECT v13_child_pointer(%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s)",
        (sid, sid, sid, tid, up_to),
        "v13: workflow pointer: not_child")
    root_events_after = q1(cur, "SELECT count(*) FROM events WHERE session_id=%s", (sid,))
    src = q1(
        cur,
        "SELECT pg_get_functiondef('public.v13_child_pointer(uuid,uuid,uuid,uuid,bigint)'::regprocedure)")
    idx = q1(
        cur,
        "SELECT indexdef FROM pg_indexes WHERE indexname = 'ux_events_workflow_pointer'")
    conflict_at = src.find("workflow pointer: replay_conflict")
    stop_at = src.find("workflow pointer: stopped")
    term_at = src.find("workflow pointer: terminal")
    append_at = src.find("v13_append_event")
    unique_at = src.find("unique_violation")
    ok = (
        before == 0
        and eid == again
        and seq_before == seq_after
        and n_type(cur, child, "workflow/pointer") == 1
        and other_id != eid
        and n_type(cur, other, "workflow/pointer") == 1
        and conflict_ok
        and n_type(cur, child, "workflow/pointer") == 1
        and raw_ok
        and stop_ok
        and n_type(cur, stopped, "workflow/pointer") == 0
        and terminal_ok
        and not_child_ok
        and root_events_after == root_events
        and "unique_violation" in src
        and idx is not None
        and "workflow/pointer" in idx
        and 0 <= conflict_at < stop_at < term_at < append_at < unique_at
    )
    check(
        "one_pointer",
        ok,
        (eid, again, conflict_msg, raw_code, stop_msg, terminal_msg, not_child_msg, idx))


def test_pointer_not_transcript(cur):
    sid, child, tid, plan_id = seed(cur, "parent-transcript-not-for-child")
    up_to = max_seq(cur, sid)
    pointer(cur, child, sid, sid, tid, up_to)
    payload = as_obj(q1(
        cur,
        "SELECT payload FROM events WHERE session_id=%s AND type='workflow/pointer'",
        (child,)))
    keys = q1(cur, "SELECT v13_json_keys(%s::jsonb)", (json.dumps(payload),))
    blob = json.dumps(payload)
    extra_ok, extra_msg = expect_raise(
        cur,
        "SELECT v13_append_event(%s, %s, 'workflow/pointer', %s::jsonb)",
        (child, u(), json.dumps({
            "schema_version": 1,
            "parent_session_id": sid,
            "root_session_id": sid,
            "todo_id": tid,
            "up_to_seq": up_to,
            "transcript": "parent-transcript-not-for-child",
            "canonical": {"plan_id": plan_id},
        })),
        "v13: workflow pointer: payload")
    ok = (
        list(keys) == [
            "parent_session_id", "root_session_id", "schema_version",
            "todo_id", "up_to_seq"]
        and payload["schema_version"] == 1
        and payload["parent_session_id"] == sid
        and payload["root_session_id"] == sid
        and payload["todo_id"] == tid
        and payload["up_to_seq"] == up_to
        and "parent-transcript-not-for-child" not in blob
        and "plan-canonical-not-for-pointer" not in blob
        and "canonical" not in payload
        and "transcript" not in payload
        and n_type(cur, child, "user/message") == 0
        and n_type(cur, child, "plan/committed") == 0
        and n_type(cur, child, "spawn/task") == 0
        and extra_ok
    )
    check("pointer_not_transcript", ok, (keys, extra_msg, payload))


def test_root_waterline(cur):
    sid, child, tid, plan_id = seed(cur)
    um = n_type(cur, sid, "user/message")
    turn = q1(cur, "SELECT turn_no FROM sessions WHERE session_id=%s", (sid,))
    events = q1(cur, "SELECT count(*) FROM events WHERE session_id=%s", (sid,))
    current = as_obj(q1(cur, "SELECT v13_plan_current(%s)", (sid,)))
    pointer(cur, child, sid, sid, tid, max_seq(cur, sid))
    current_after = as_obj(q1(cur, "SELECT v13_plan_current(%s)", (sid,)))
    child_current = as_obj(q1(cur, "SELECT v13_plan_current(%s)", (child,)))
    ok = (
        um == 1
        and n_type(cur, sid, "user/message") == um
        and q1(cur, "SELECT turn_no FROM sessions WHERE session_id=%s", (sid,)) == turn
        and q1(cur, "SELECT count(*) FROM events WHERE session_id=%s", (sid,)) == events
        and n_type(cur, sid, "workflow/pointer") == 0
        and n_type(cur, child, "workflow/pointer") == 1
        and current["plan_id"] == plan_id
        and current_after["plan_id"] == plan_id
        and child_current["plan_id"] == plan_id
    )
    check(
        "root_waterline_unchanged",
        ok,
        (um, turn, events, plan_id, current_after["plan_id"] if current_after else None))


def test_untouched(cur, before_jt, before_tools, slog_hash):
    after_jt = jt_snap(cur)
    src = q1(
        cur,
        "SELECT pg_get_functiondef('public.v13_workflow_resolve(text,integer)'::regprocedure)")
    pointer_src = q1(
        cur,
        "SELECT pg_get_functiondef('public.v13_child_pointer(uuid,uuid,uuid,uuid,bigint)'::regprocedure)")
    ok = (
        before_jt == after_jt
        and "judgment_templates" not in SQL
        and "judgment_templates" not in src
        and "judgment_templates" not in pointer_src
    )
    check("judgment_templates_untouched", ok, (before_jt[2], after_jt[2]))
    after_tools, after_rev = tools_snap(cur)
    before_rows, before_rev = before_tools
    names = {row[0] for row in after_tools}
    code = re.sub(r"--[^\n]*", "", SQL).lower()
    ok = (
        before_rows == after_tools
        and before_rev == after_rev
        and "update tools" not in code
        and "update public.tools" not in code
        and "insert into tools" not in code
        and "insert into public.tools" not in code
        and "delete from tools" not in code
        and "delete from public.tools" not in code
        and "read_pi" not in names
        and "read_file_swift" not in names
        and "read_file_py" not in names
        and "read_duck" not in names
    )
    check("no_tool_flag_update", ok, (before_rev, after_rev, len(after_tools)))
    after_hash = fn_hash(cur, "public.v13_session_log(uuid,uuid,bigint)")
    log_src = q1(
        cur,
        "SELECT pg_get_functiondef('public.v13_session_log(uuid,uuid,bigint)'::regprocedure)")
    ok = (
        slog_hash == after_hash
        and "v13_session_log" not in SQL
        and "v13: session log cursor" in log_src
        and "workflow/pointer" not in log_src
        and "workflow_template" not in log_src
    )
    check("session_log_unchanged", ok, after_hash)


def run(cur):
    before_jt = jt_snap(cur)
    before_tools = tools_snap(cur)
    slog_hash = fn_hash(cur, "public.v13_session_log(uuid,uuid,bigint)")
    test_resolve_v1(cur)
    test_label_does_not_open_explore(cur)
    test_one_pointer(cur)
    test_pointer_not_transcript(cur)
    test_root_waterline(cur)
    test_untouched(cur, before_jt, before_tools, slog_hash)
    cur.execute("COMMIT")


def main() -> int:
    print("[db]", DB)
    if setup_db() != 0:
        return 1
    server = get_server()
    conn = connect(server)
    try:
        run(conn.cursor())
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
