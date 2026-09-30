"""Phase B workspace_admit gate.

Run: UV_FROZEN=1 uv run python v13/workspace_admit/test_workspace_admit.py
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import threading
import uuid
from pathlib import Path

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_REPEATABLE_READ

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v13.load import run_psql
from v13.workspace_admit.setup_db import DB, main as setup_db
import v13.workspace_admit.setup_db as setup_mod

N = 0
SQL = (ROOT / "v13_workspace_admit.sql").read_text()
WS = "/tmp/ws"
WS_SUB = "/tmp/ws/sub"
HEX = "ab" * 32
READS = ("read_pi", "read_file_swift", "read_file_py", "read_duck")
BANNED = ("explore", "pair", "read_pi", "read_file_swift", "read_file_py",
          "read_duck", "spawn_subsession")
HASH_FNS = (
    "public.v13_advance(uuid,jsonb)",
    "public.v13_goal_fingerprint(uuid)",
    "public.v13_enqueue_effect(uuid,text,jsonb,text)",
    "public.v13_llm_tool_calls(jsonb)",
    "public.v13_recover_idle()",
)


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


def fails(cur, sql, params, needle, label):
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


def open_root(cur):
    spec = {"route_policy_name": "default", "version": 1}
    return str(q1(cur, "SELECT v13_plan_commit_entry(%s::jsonb)", (json.dumps(spec),)))


def prefix(cur, sid, text="hello goal"):
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (sid, u(), json.dumps({"text": text})))


def max_seq(cur, sid):
    return q1(cur, "SELECT max(seq) FROM events WHERE session_id=%s", (sid,))


def writer(cur, sid, canonical):
    cur.execute(
        "SELECT v13_plan_writer(%s::uuid, %s::uuid, %s::uuid, %s, %s::jsonb, %s::timestamptz)",
        (None, sid, u(), canonical["call_kind"], json.dumps(canonical), None))
    return as_obj(cur.fetchone()[0])


def plant(cur, sid):
    tid = u()
    text = "pending advancement"
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
            "status": "pending",
            "due": None,
            "verb": "add_new",
        }],
    }
    writer(cur, sid, body)
    return tid


def n_effects(cur):
    return q1(cur, "SELECT count(*) FROM effects")


def effect_ids(cur):
    cur.execute("SELECT effect_id::text FROM effects ORDER BY effect_id")
    return [row[0] for row in cur.fetchall()]


def n_calls(cur, sid):
    return q1(
        cur,
        "SELECT count(*) FROM events WHERE session_id=%s AND type='tool/call'",
        (sid,))


def n_roots(cur):
    return q1(cur, "SELECT count(*) FROM sessions WHERE parent_session_id IS NULL")


def qcount(cur):
    if q1(cur, "SELECT to_regclass('pgmq.q_v13_work')") is None:
        return 0
    return q1(cur, "SELECT count(*) FROM pgmq.q_v13_work")


def fn_hash(cur, sig):
    return q1(
        cur,
        "SELECT encode(digest(convert_to(pg_get_functiondef(%s::regprocedure), 'UTF8'), 'sha256'), 'hex')",
        (sig,))


def request(tool, paths, payload, label="workspace_edit", key=None):
    return {
        "schema_version": 1,
        "tool": tool,
        "label": label,
        "paths": paths,
        "attempt_key": key or u(),
        "payload": payload,
    }


def open_params(sid, label, req, root=WS, roots=None):
    return (
        "SELECT v13_tool_effect_open(%s::uuid, %s::uuid, %s, %s, %s::text[], %s::jsonb)",
        (None, sid, label, root, roots or [root, WS_SUB], json.dumps(req)),
    )


def opened(cur, sid, label, req, root=WS, roots=None):
    sql, params = open_params(sid, label, req, root, roots)
    cur.execute(sql, params)
    return as_obj(cur.fetchone()[0])


def shape(tool, text="", byte_length=None, truncated=None, ok=True, token=None,
          depth=False):
    if byte_length is None:
        byte_length = len(text.encode("utf-8"))
    if truncated is None:
        truncated = byte_length > 51200
    return {
        "schema_version": 1,
        "ok": ok,
        "tool": tool,
        "truncated": truncated,
        "depth_limited": depth,
        "byte_length": byte_length,
        "text": text,
        "error_token": token,
    }


def accept(cur, row, status, body):
    cur.execute(
        "SELECT v13_tool_result_accept(%s::uuid, %s, %s, %s, %s::jsonb)",
        (row["effect_id"], row["attempt_no"], row["fence"], status, json.dumps(body)))
    return cur.fetchone()[0]


def free_failed(cur, row, tool):
    accept(cur, row, "failed", shape(tool, ok=False, token="hash_mismatch"))


def ls_req(path="dir", key=None):
    return request("ls", [path], {"path": path}, key=key)


def snap_of(cur, sid):
    cur.execute(
        "UPDATE sessions SET context_active_revision = v13_context_required(session_id) "
        "WHERE session_id=%s",
        (sid,))
    cur.execute("SELECT v13_probe(%s)", (sid,))
    probe = cur.fetchone()[0]
    if isinstance(probe, str):
        probe = json.loads(probe)
    probe["sid"] = sid
    return {"snap": probe, "envelope": {"sid": sid}}


def advance(cur, sid):
    snap = snap_of(cur, sid)
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid, json.dumps(snap)))
    return cur.fetchone()[0]


def status_of(cur, sid):
    return q1(cur, "SELECT status FROM sessions WHERE session_id=%s", (sid,))


def effect_status(cur, eid):
    return q1(cur, "SELECT status FROM effects WHERE effect_id=%s", (eid,))


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
    load = subprocess.check_output(
        ["git", "diff", "HEAD", "--", "v13/load.py"], cwd=AGENT_ROOT).decode()
    removed = [
        line for line in load.splitlines()
        if line.startswith("-") and not line.startswith("---")
    ]
    text = (AGENT_ROOT / "v13/load.py").read_text()
    order = text.split("STAGE_THROUGH", 1)[0]
    through = text.split("STAGE_THROUGH", 1)[1]
    tail_ok = (
        order.rfind("real_chain") < order.rfind("workspace_admit")
        and through.rfind('"real_chain": 35') < through.rfind('"workspace_admit": 36')
        and "workspace_admit" not in order[:order.rfind("real_chain")]
    )
    if load.strip():
        load_ok = "workspace_admit" in load and removed == [] and tail_ok
    else:
        load_ok = tail_ok and "workspace_admit" in text
    check("stage_bytes", diff == b"" and load_ok, (removed, tail_ok, bool(load.strip())))


def test_policy_and_hashes(cur, server):
    before = tuple(fn_hash(cur, sig) for sig in HASH_FNS)
    wf = q1(
        cur,
        "SELECT value FROM v13_policies WHERE name='workflow_template' AND version=1 AND active")
    cur.execute(
        "SELECT name, kind, handler, description, param_spec::text "
        "FROM tools WHERE name = ANY(%s) ORDER BY name",
        (list(READS),))
    tools_before = cur.fetchall()
    pol = as_obj(q1(
        cur,
        "SELECT value FROM v13_policies WHERE name='workspace_tool_subset' AND version=1 AND active"))
    n_pol = q1(
        cur,
        "SELECT count(*) FROM v13_policies WHERE name='workspace_tool_subset'")
    cur.connection.commit()
    run_psql(server, DB, SQL)
    pol2 = as_obj(q1(
        cur,
        "SELECT value FROM v13_policies WHERE name='workspace_tool_subset' AND version=1 AND active"))
    n_pol2 = q1(
        cur,
        "SELECT count(*) FROM v13_policies WHERE name='workspace_tool_subset'")
    revoked = q1(
        cur,
        "SELECT NOT has_function_privilege('public', "
        "'public.v13_tool_effect_open(uuid,uuid,text,text,text[],jsonb)', 'EXECUTE')")
    check(
        "policy_seed_idempotent",
        n_pol == 1 and n_pol2 == 1 and pol == pol2 and pol["schema_version"] == 1
        and revoked and "stannum" not in SQL.lower()
        and "CREATE OR REPLACE FUNCTION public.v13_advance" not in SQL,
        (n_pol, n_pol2, revoked))
    wf2 = q1(
        cur,
        "SELECT value FROM v13_policies WHERE name='workflow_template' AND version=1 AND active")
    check(
        "workflow_template_v1_unchanged",
        wf == wf2 and "UPDATE public.v13_policies" not in SQL
        and "workflow_template" not in SQL,
        None)
    blob = json.dumps(pol2, sort_keys=True)
    check(
        "read_names_absent_from_policy",
        all(name not in blob for name in BANNED),
        blob)
    cur.execute(
        "SELECT name, kind, handler, description, param_spec::text "
        "FROM tools WHERE name = ANY(%s) ORDER BY name",
        (list(READS),))
    tools_after = cur.fetchall()
    check(
        "read_tool_rows_unchanged",
        tools_before == tools_after and len(tools_before) == 4
        and "INSERT INTO tools" not in SQL and "UPDATE tools" not in SQL,
        len(tools_after))
    after = tuple(fn_hash(cur, sig) for sig in HASH_FNS)
    check("hashes_unmodified", before == after, (before, after))


def test_flow(cur, server):
    sid = open_root(cur)
    prefix(cur, sid)
    before = n_effects(cur)
    fails(
        cur, *open_params(sid, "read_only", request(
            "ls", ["dir"], {"path": "dir"}, label="read_only")),
        "v13: workspace open: no_plan", "no_plan_refuses_open")
    check("no_plan zero writes", n_effects(cur) == before)
    plant(cur, sid)
    current = as_obj(q1(cur, "SELECT v13_plan_current(%s)", (sid,)))
    selected = q1(cur, "SELECT count(*) FROM v13_selected_todo(%s)", (sid,))
    row = opened(cur, sid, "read_only", request(
        "ls", ["dir"], {"path": "dir"}, label="read_only"))
    check(
        "plan_without_selected_todo_still_opens",
        current is not None and selected == 0 and row["status"] == "claimed"
        and row["replayed"] is False and "v13_plan_gate(" not in SQL,
        (selected, row["status"]))
    calls = n_calls(cur, sid)
    check(
        "open_claims_without_increment",
        row["status"] == "claimed" and row["attempt_no"] == 0 and row["fence"] == 0
        and calls == 0 and effect_status(cur, row["effect_id"]) == "claimed",
        row)
    claimed = q1(cur, "SELECT v13_claim('worker', 60000)")
    check(
        "claim_skips_claimed_row",
        claimed is None or as_obj(claimed).get("effect_id") != row["effect_id"],
        claimed)
    free_failed(cur, row, "ls")

    rejected = []
    for tool, payload, paths in (
        ("edit", {"path": "a", "old": "x", "new": "y", "expected_sha256": HEX}, ["a"]),
        ("write", {"path": "a", "content": "z", "expected_sha256": None}, ["a"]),
        ("bash", {"argv": ["mkdir", "a"]}, ["a"]),
    ):
        cur.execute("SAVEPOINT rej")
        try:
            cur.execute(*open_params(sid, "read_only", request(
                tool, paths, payload, label="read_only")))
            rejected.append("opened")
        except psycopg2.Error as exc:
            rejected.append(exc.diag.message_primary or "")
        cur.execute("ROLLBACK TO SAVEPOINT rej")
    check(
        "read_only_rejects_edit_write_bash",
        rejected == ["v13: workspace open: subset"] * 3,
        rejected)
    admitted = []
    for tool, payload, paths in (
        ("find", {"path": "dir"}, ["dir"]),
        ("grep", {"path": "dir", "pattern": "x"}, ["dir"]),
        ("ls", {"path": "dir"}, ["dir"]),
    ):
        got = opened(cur, sid, "read_only", request(
            tool, paths, payload, label="read_only"))
        admitted.append(got["tool"])
        free_failed(cur, got, tool)
    check("read_only_admits_grep_find_ls", admitted == ["find", "grep", "ls"], admitted)

    six = []
    samples = (
        ("bash", {"argv": ["mkdir", "a"]}, ["a"]),
        ("edit", {"path": "a", "old": "x", "new": "y", "expected_sha256": HEX}, ["a"]),
        ("find", {"path": "dir"}, ["dir"]),
        ("grep", {"path": "dir", "pattern": "x"}, ["dir"]),
        ("ls", {"path": "dir"}, ["dir"]),
        ("write", {"path": "a", "content": "z", "expected_sha256": None}, ["a"]),
    )
    for tool, payload, paths in samples:
        got = opened(cur, sid, "workspace_edit", request(tool, paths, payload))
        six.append(got["status"])
        free_failed(cur, got, tool)
    check("workspace_edit_admits_six", six == ["claimed"] * 6, six)

    fails(
        cur, *open_params(sid, "explore", request(
            "ls", ["dir"], {"path": "dir"}, label="explore")),
        "v13: workspace open: explore_not_a_tool_label", "explore_label_rejected")

    cur.execute("SAVEPOINT explore")
    eid = q1(
        cur,
        "SELECT v13_enqueue_effect(%s, 'llm', %s::jsonb)",
        (sid, json.dumps({"route": {"action": "llm", "reason": "explore"}})))
    cur.execute(
        "UPDATE effects SET status='claimed', attempt_no=1, fence=1, lease_owner='w', "
        "lease_until=clock_timestamp()+interval '1 hour' WHERE effect_id=%s "
        "RETURNING attempt_no, fence",
        (eid,))
    attempt, fence = cur.fetchone()
    cur.execute(
        "SELECT v13_complete(%s, %s, %s, 'succeeded', %s::jsonb)",
        (eid, attempt, fence, json.dumps({
            "text": "ok",
            "tool_calls": [{
                "id": "tc1", "name": "spawn_subsession", "args": {"task": "one"}}],
        })))
    cur.fetchone()
    fails(
        cur, "SELECT v13_triage_block_explore_spawn(%s)", (sid,),
        "v13: explore spawn", "explore_spawn_still_raises")
    cur.execute("ROLLBACK TO SAVEPOINT explore")

    fails(
        cur,
        "SELECT v13_llm_tool_calls(%s::jsonb)",
        (json.dumps([{"id": "tc1", "name": "edit", "args": {"task": "x"}}]),),
        "v13: tool_calls shape", "spawn_guard_rejects_edit")
    fails(
        cur, *open_params(sid, "workspace_edit", request(
            "read_file_py", ["a"], {"path": "a"})),
        "v13: workspace open: not_this_opener", "not_this_opener_rejects_read_file_py")

    cur.execute("SAVEPOINT stop")
    cur.execute("SELECT v13_goal_stop(%s, %s)", (sid, "pause"))
    cur.fetchone()
    fails(
        cur, *open_params(sid, "read_only", request(
            "ls", ["dir"], {"path": "dir"}, label="read_only")),
        "v13: workspace open: stopped", "first_open_stopped")
    cur.execute("ROLLBACK TO SAVEPOINT stop")

    cur.execute("SAVEPOINT term")
    cur.execute("SELECT v13_cancel(%s)", (sid,))
    cur.fetchone()
    word = advance(cur, sid)
    fails(
        cur, *open_params(sid, "read_only", request(
            "ls", ["dir"], {"path": "dir"}, label="read_only")),
        "v13: workspace open: terminal", "first_open_terminal")
    check("terminal closeout word", word == "terminal", word)
    cur.execute("ROLLBACK TO SAVEPOINT term")

    cur.execute("SAVEPOINT human")
    cur.execute(
        "SELECT v13_enqueue_effect(%s, 'human', %s::jsonb)",
        (sid, json.dumps({"reason": "ask"})))
    cur.fetchone()
    fails(
        cur, *open_params(sid, "read_only", request(
            "ls", ["dir"], {"path": "dir"}, label="read_only")),
        "v13: workspace open: human_pending", "human_pending_rejected")
    cur.execute("ROLLBACK TO SAVEPOINT human")

    cur.execute("SAVEPOINT run")
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'cancel/requested', %s::jsonb)",
        (sid, u(), json.dumps({"schema_version": 1, "scope": "session"})))
    before = n_effects(cur)
    fails(
        cur, *open_params(sid, "read_only", request(
            "ls", ["dir"], {"path": "dir"}, label="read_only")),
        "v13: workspace open: should_run", "should_run_false_refuses_open")
    check("should_run zero writes", n_effects(cur) == before)
    cur.execute("ROLLBACK TO SAVEPOINT run")

    cur.execute("SAVEPOINT tree")
    cur.execute(
        "SELECT v13_open_session(%s::jsonb)",
        (json.dumps({"route_policy_name": "default", "version": 1}),))
    cur.fetchone()
    before = n_effects(cur)
    fails(
        cur, *open_params(sid, "read_only", request(
            "ls", ["dir"], {"path": "dir"}, label="read_only")),
        "v13: workspace open: not_single_tree", "not_single_tree")
    check("not_single_tree zero workspace effects", n_effects(cur) == before)
    cur.execute("ROLLBACK TO SAVEPOINT tree")
    check("not_single_tree rolled back to one root", n_roots(cur) == 1, n_roots(cur))

    fails(
        cur,
        "SELECT v13_tool_effect_open(%s::uuid, %s::uuid, %s, %s, %s::text[], %s::jsonb)",
        (u(), sid, "read_only", WS, [WS, WS_SUB], json.dumps(request(
            "ls", ["dir"], {"path": "dir"}, label="read_only"))),
        "v13: workspace open: auth", "root_actor_rejected")

    held = opened(cur, sid, "workspace_edit", request("ls", ["a"], {"path": "a"}))
    fails(
        cur, *open_params(sid, "workspace_edit", request("ls", ["a"], {"path": "a"})),
        "v13: workspace open: path_busy", "path_busy_same_path")
    free_failed(cur, held, "ls")

    held = opened(cur, sid, "workspace_edit", request(
        "ls", ["a"], {"path": "a"}))
    fails(
        cur, *open_params(sid, "workspace_edit", request(
            "ls", ["a", "a/b"], {"path": "a"})),
        "v13: workspace open: path_busy", "path_busy_prefix")
    free_failed(cur, held, "ls")

    held = opened(
        cur, sid, "workspace_edit",
        request("ls", ["sub", "sub/file.txt"], {"path": "sub"}),
        root=WS, roots=[WS, WS_SUB])
    fails(
        cur, *open_params(
            sid, "workspace_edit",
            request("ls", ["file.txt"], {"path": "file.txt"}),
            root=WS_SUB, roots=[WS, WS_SUB]),
        "v13: workspace open: path_busy", "path_busy_overlapping_roots")
    free_failed(cur, held, "ls")

    cur.execute("SAVEPOINT pathdistinct")
    first = opened(cur, sid, "workspace_edit", request("ls", ["a"], {"path": "a"}))
    cur.execute("SELECT v13_fork(%s::uuid, 0, 'fresh_fork')", (sid,))
    child = str(cur.fetchone()[0])
    second = opened(cur, child, "workspace_edit", request("ls", ["ab"], {"path": "ab"}))
    free_failed(cur, first, "ls")
    free_failed(cur, second, "ls")
    third = opened(cur, sid, "workspace_edit", request("ls", ["ab"], {"path": "ab"}))
    fourth = opened(cur, child, "workspace_edit", request(
        "ls", ["a", "a/b"], {"path": "a"}))
    check(
        "path_distinct_ab",
        first["status"] == "claimed" and second["status"] == "claimed"
        and third["status"] == "claimed" and fourth["status"] == "claimed"
        and n_roots(cur) == 1,
        (first["effect_id"], second["effect_id"]))
    cur.execute("ROLLBACK TO SAVEPOINT pathdistinct")

    both = opened(cur, sid, "workspace_edit", request(
        "ls", ["a", "a/b"], {"path": "a/b"}))
    check(
        "parent_segment_not_self_busy",
        both["status"] == "claimed" and both["replayed"] is False,
        both["status"])
    free_failed(cur, both, "ls")

    fails(
        cur, *open_params(sid, "workspace_edit", request(
            "ls", ["A", "a"], {"path": "a"})),
        "v13: workspace open: canonical", "case_alias_rejected")
    fails(
        cur, *open_params(sid, "workspace_edit", request(
            "ls", ["ss", "\u00df"], {"path": "ss"})),
        "v13: workspace open: canonical", "casefold_sharp_s_rejected")
    temps = []
    for path, needle in ((".V13TMP-x", "canonical"), (".v13tmp-x", "temp_namespace")):
        cur.execute("SAVEPOINT tmp")
        try:
            cur.execute(*open_params(sid, "workspace_edit", request(
                "ls", [path], {"path": path})))
            temps.append("opened")
        except psycopg2.Error as exc:
            temps.append(exc.diag.message_primary or "")
        cur.execute("ROLLBACK TO SAVEPOINT tmp")
    check(
        "temp_prefix_case_rejected",
        temps == [
            "v13: workspace open: canonical",
            "v13: workspace open: temp_namespace",
        ],
        temps)

    fails(
        cur, *open_params(sid, "workspace_edit", request(
            "ls", ["a/b"], {"path": "a/b"})),
        "v13: workspace open: canonical", "parent_missing_rejected")
    fails(
        cur, *open_params(sid, "workspace_edit", request(
            "ls", ["b", "a"], {"path": "a"})),
        "v13: workspace open: canonical", "unsorted_paths_rejected")
    fails(
        cur, *open_params(sid, "workspace_edit", request(
            "bash", ["safe"], {"argv": ["rm", "rm"], "expected_sha256": HEX})),
        "v13: workspace open: payload", "bash_operand_equals_verb_rejected")
    fails(
        cur,
        "SELECT v13_tool_effect_open(%s::uuid, %s::uuid, %s, %s, %s::text[], %s::jsonb)",
        (None, sid, "workspace_edit", "/tmp/outside", [WS, None], json.dumps(
            request("ls", ["a"], {"path": "a"}))),
        "v13: workspace open: canonical", "null_allowlist_does_not_admit")
    fails(
        cur,
        "SELECT v13_tool_effect_open(%s::uuid, %s::uuid, %s, %s, %s::text[], %s::jsonb)",
        (None, sid, "workspace_edit", WS, [WS, WS_SUB], json.dumps({
            "schema_version": 1, "tool": "ls", "label": "workspace_edit",
            "paths": [123], "attempt_key": u(), "payload": {"path": "123"},
        })),
        "v13: workspace open: canonical", "path_element_not_string")
    fails(
        cur, *open_params(sid, "workspace_edit", {
            "schema_version": 1, "tool": "bash", "label": "workspace_edit",
            "paths": ["123"], "attempt_key": u(),
            "payload": {"argv": ["mkdir", 123]},
        }),
        "v13: workspace open: payload", "argv_element_not_string")

    held = opened(cur, sid, "workspace_edit", request(
        "ls", ["a", "a/b"], {"path": "a"}))
    fails(
        cur, *open_params(sid, "workspace_edit", request(
            "ls", ["a", "a/c"], {"path": "a"})),
        "v13: workspace open: path_busy", "same_parent_blocks")
    check(
        "crashed_claim_stays_busy",
        effect_status(cur, held["effect_id"]) == "claimed",
        effect_status(cur, held["effect_id"]))
    accept(cur, held, "succeeded", shape("ls", text="a\n"))
    again = opened(cur, sid, "workspace_edit", request("ls", ["a"], {"path": "a"}))
    check(
        "terminal_releases_path",
        again["status"] == "claimed" and again["replayed"] is False,
        again["status"])
    replay = opened(cur, sid, "workspace_edit", request(
        "ls", ["a"], {"path": "a"}, key=again["effect_id"] and
        q1(cur, "SELECT request->>'attempt_key' FROM effects WHERE effect_id=%s",
           (again["effect_id"],))))
    check(
        "replay_open_same_fence",
        replay["replayed"] is True and replay["fence"] == again["fence"]
        and replay["attempt_no"] == again["attempt_no"]
        and replay["status"] == "claimed" and replay["result"] is None
        and n_effects(cur) == n_effects(cur),
        replay)
    free_failed(cur, again, "ls")

    failed = opened(cur, sid, "workspace_edit", ls_req("gone"))
    free_failed(cur, failed, "ls")
    key = q1(
        cur, "SELECT request->>'attempt_key' FROM effects WHERE effect_id=%s",
        (failed["effect_id"],))
    fails(
        cur, *open_params(sid, "workspace_edit", ls_req("gone", key=key)),
        "v13: workspace open: effect_exists", "effect_exists_no_requeue")
    check(
        "effect_exists stays failed",
        effect_status(cur, failed["effect_id"]) == "failed",
        effect_status(cur, failed["effect_id"]))
    fails(
        cur, *open_params(sid, "workspace_edit", request(
            "ls", ["other"], {"path": "other"}, key=key)),
        "v13: workspace open: effect_exists",
        "failed_attempt_key_different_request_rejected")

    bad = opened(cur, sid, "workspace_edit", ls_req("cap"))
    long_text = "a" * 51201
    fails(
        cur,
        "SELECT v13_tool_result_accept(%s::uuid, %s, %s, 'succeeded', %s::jsonb)",
        (bad["effect_id"], bad["attempt_no"], bad["fence"], json.dumps(
            shape("ls", text=long_text, byte_length=51201, truncated=True))),
        "v13: workspace result: over_cap", "result_over_cap_rejected")
    check(
        "over_cap stays claimed",
        effect_status(cur, bad["effect_id"]) == "claimed"
        and q1(cur, "SELECT result FROM effects WHERE effect_id=%s",
               (bad["effect_id"],)) is None)
    minus = "b" * 51199
    word = accept(cur, bad, "succeeded", shape("ls", text=minus))
    stored = as_obj(q1(cur, "SELECT result FROM effects WHERE effect_id=%s",
                       (bad["effect_id"],)))
    check(
        "result_cap_minus_one",
        word == "accepted" and stored["truncated"] is False and stored["text"] == minus
        and stored["byte_length"] == 51199,
        stored["byte_length"] if stored else None)

    exact_row = opened(cur, sid, "workspace_edit", ls_req("exact"))
    exact = "c" * 51200
    word = accept(cur, exact_row, "succeeded", shape("ls", text=exact))
    stored = as_obj(q1(
        cur, "SELECT result FROM effects WHERE effect_id=%s", (exact_row["effect_id"],)))
    check(
        "result_cap_exact",
        word == "accepted" and stored["truncated"] is False
        and stored["byte_length"] == 51200 and len(stored["text"]) == 51200,
        stored["truncated"] if stored else None)

    plus = opened(cur, sid, "workspace_edit", ls_req("plus"))
    prefix_text = "d" * 51200
    word = accept(cur, plus, "succeeded", shape(
        "ls", text=prefix_text, byte_length=51201, truncated=True))
    stored = as_obj(q1(cur, "SELECT result FROM effects WHERE effect_id=%s",
                       (plus["effect_id"],)))
    check(
        "result_cap_plus_one",
        word == "accepted" and stored["truncated"] is True
        and stored["text"] == prefix_text and stored["byte_length"] == 51201
        and len(stored["text"].encode("utf-8")) == 51200,
        stored["byte_length"] if stored else None)
    huge = opened(cur, sid, "workspace_edit", ls_req("huge"))
    word = accept(cur, huge, "succeeded", shape(
        "ls", text="z", byte_length=2147483648, truncated=True))
    stored = as_obj(q1(cur, "SELECT result FROM effects WHERE effect_id=%s",
                       (huge["effect_id"],)))
    check(
        "byte_length_above_int32_accepted",
        word == "accepted" and stored["byte_length"] == 2147483648
        and stored["truncated"] is True and stored["text"] == "z",
        stored["byte_length"] if stored else None)

    flag = opened(cur, sid, "workspace_edit", ls_req("flag"))
    fails(
        cur,
        "SELECT v13_tool_result_accept(%s::uuid, %s, %s, 'succeeded', %s::jsonb)",
        (flag["effect_id"], flag["attempt_no"], flag["fence"], json.dumps(
            shape("ls", text="ab", byte_length=1, truncated=False))),
        "v13: workspace result: flag_inconsistent", "truncated_flag_consistent")
    check(
        "flag stays claimed",
        effect_status(cur, flag["effect_id"]) == "claimed")
    free_failed(cur, flag, "ls")

    shaped = opened(cur, sid, "workspace_edit", ls_req("shape"))
    broken = shape("ls", text="ok")
    broken["extra"] = 1
    fails(
        cur,
        "SELECT v13_tool_result_accept(%s::uuid, %s, %s, 'succeeded', %s::jsonb)",
        (shaped["effect_id"], shaped["attempt_no"], shaped["fence"], json.dumps(broken)),
        "v13: workspace result: canonical", "result_shape_rejected")
    check(
        "shape result unchanged",
        effect_status(cur, shaped["effect_id"]) == "claimed"
        and q1(cur, "SELECT result FROM effects WHERE effect_id=%s",
               (shaped["effect_id"],)) is None)
    fails(
        cur,
        "SELECT v13_tool_result_accept(%s::uuid, %s, %s, 'unknown', %s::jsonb)",
        (shaped["effect_id"], shaped["attempt_no"], shaped["fence"], json.dumps(
            shape("ls", text="ok"))),
        "v13: workspace result: canonical", "bad_status_rejected")
    free_failed(cur, shaped, "ls")

    kind = q1(
        cur,
        "SELECT count(*) FROM effects WHERE kind='sql' AND tool_name IN "
        "('edit','write','bash','grep','find','ls')")
    check("no_sql_kind", kind == 0 and "kind, 'sql'" not in SQL, kind)
    return sid


def test_advance_dispatch(cur, sid):
    cur.execute("SAVEPOINT pcs")
    src = q1(
        cur,
        "SELECT pg_get_functiondef('public.v13_advance(uuid,jsonb)'::regprocedure)")
    tool_at = src.find("WHEN 'tool'")
    gate_at = src.rfind("status IN ('ready', 'claimed')", 0, tool_at)
    enq_at = src.find("v13_enqueue_effect")
    send_at = src.find("v13_send_work")
    oid_before = q1(
        cur,
        "SELECT oid FROM pg_proc WHERE proname='v13_advance' AND pronargs=2")
    before_ids = effect_ids(cur)
    before_q = qcount(cur)
    row = opened(cur, sid, "workspace_edit", request(
        "ls", ["gate"], {"path": "gate"}))
    ids_after_open = effect_ids(cur)
    word = advance(cur, sid)
    ids_after = effect_ids(cur)
    q_after = qcount(cur)
    st = status_of(cur, sid)
    still = effect_status(cur, row["effect_id"])
    oid_after = q1(
        cur,
        "SELECT oid FROM pg_proc WHERE proname='v13_advance' AND pronargs=2")
    p_ok = (
        word == "waiting" and st == "waiting" and still == "claimed"
        and ids_after == ids_after_open and q_after == before_q
        and row["effect_id"] in ids_after)
    cur.execute("ROLLBACK TO SAVEPOINT pcs")
    c_before = effect_ids(cur)
    c_q = qcount(cur)
    c_word = advance(cur, sid)
    c_ids = effect_ids(cur)
    c_q2 = qcount(cur)
    c_ok = c_word != "waiting" or c_ids != c_before or c_q2 != c_q
    s_ok = (
        gate_at >= 0 and tool_at > gate_at and enq_at > gate_at and send_at > gate_at
        and oid_before == oid_after)
    check(
        "advance_does_not_dispatch_tool",
        p_ok and c_ok and s_ok,
        {
            "P": (word, st, still, ids_after == ids_after_open, q_after == before_q),
            "C": (c_word, c_ids != c_before, c_q2 != c_q),
            "S": (gate_at, tool_at, enq_at, send_at, str(oid_before) == str(oid_after)),
            "open_ids": before_ids != ids_after_open,
        })
    cur.execute("ROLLBACK TO SAVEPOINT pcs")


def test_root_lock(server, sid):
    conn1 = connect(server)
    try:
        cur1 = conn1.cursor()
        row = opened(cur1, sid, "workspace_edit", request(
            "ls", ["lock"], {"path": "lock"}))
        box = {}

        def second():
            conn2 = connect(server)
            try:
                cur2 = conn2.cursor()
                cur2.execute("SET lock_timeout = '8s'")
                sql, params = open_params(sid, "workspace_edit", request(
                    "ls", ["lock"], {"path": "lock"}))
                try:
                    cur2.execute("SET lock_timeout = '15s'")
                    cur2.execute(sql, params)
                    box["row"] = cur2.fetchone()
                except psycopg2.Error as exc:
                    box["err"] = exc.diag.message_primary or str(exc).splitlines()[0]
                conn2.rollback()
            finally:
                conn2.close()

        worker = threading.Thread(target=second)
        worker.start()
        worker.join(0.4)
        conn1.commit()
        worker.join(15)
        check(
            "root_lock_then_path_busy",
            box.get("err") and "path_busy" in box["err"]
            and effect_status(cur1, row["effect_id"]) == "claimed",
            box)
    finally:
        conn1.close()


def test_isolation(server, sid):
    conn = connect(server)
    try:
        conn.set_isolation_level(ISOLATION_LEVEL_REPEATABLE_READ)
        cur = conn.cursor()
        before = n_effects(cur)
        try:
            cur.execute(*open_params(sid, "read_only", request(
                "ls", ["dir"], {"path": "dir"}, label="read_only")))
            raise AssertionError("isolation open succeeded")
        except psycopg2.Error as exc:
            msg = exc.diag.message_primary or str(exc).splitlines()[0]
            check(
                "isolation_not_read_committed_rejected",
                "v13: workspace open: canonical" in msg,
                msg)
        conn.rollback()
        check("isolation zero writes", n_effects(cur) == before)
    finally:
        conn.close()


def main() -> int:
    print("[db]", DB)
    test_stage_bytes()
    if setup_db() != 0:
        return 1
    server = get_server()
    conn = connect(server)
    try:
        cur = conn.cursor()
        test_policy_and_hashes(cur, server)
        sid = test_flow(cur, server)
        test_advance_dispatch(cur, sid)
        conn.commit()
        test_root_lock(server, sid)
        test_isolation(server, sid)
    finally:
        conn.close()
        if setup_mod.CREATED:
            run_psql(server, "postgres", 'DROP DATABASE "%s" WITH (FORCE);' % DB)
            setup_mod.CREATED = False
            print("[dropped]", DB)
    print("[ok] %s checks" % N)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("[FAIL]", exc)
        if setup_mod.CREATED:
            try:
                run_psql(get_server(), "postgres", 'DROP DATABASE "%s" WITH (FORCE);' % DB)
                print("[dropped]", DB)
            except Exception as drop_exc:
                print("[cleanup-fail]", drop_exc)
        raise SystemExit(1)
