"""单 goal、测试超级用户、Fake 夹具、场景自有 advance 上界 4（常数只活在 `v13/goal_workflow/test_goal_workflow.py`）、无真实 provider、唯一推进者是一个 `LoopDriver`：宏观门放行后，`workflow_template` version 1 / `first_real_chain` 展开成一条 advancement todo、一个子会话、一次 `read_file_py`、根上归档为 done，根与子都没有 human effect。已有 human pending 时场景停在非终态、不 skip、不 complete、不 cancel。这不是人可以离开生产终端。

Run: UV_FROZEN=1 uv run python v13/goal_workflow/test_goal_workflow.py
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg2
import psycopg2.extensions

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v13.goal_workflow.setup_db import DB, main as setup_db
import v13.goal_workflow.setup_db as setup_mod
from v13.load import run_psql
from v13.loop_driver.driver import LAYER_ORDER, PROVIDER_ATTEMPT_CAP, LoopDriver, as_obj
from v13.plan_arm.test_plan_arm import r0_source_scope, r1_driver_restore
from v13.real_chain.chain import EXCERPT_CAP, _plan_answer_ok, _spawn_answer_ok, text_hash

N = 0
SQL_PATH = ROOT / "v13_goal_workflow.sql"
SQL = SQL_PATH.read_text()
GOAL_WORKFLOW_MAX_ADVANCE = 4
CLAIM = (
    "单 goal、测试超级用户、Fake 夹具、场景自有 advance 上界 4（常数只活在 "
    "`v13/goal_workflow/test_goal_workflow.py`）、无真实 provider、唯一推进者是一个 "
    "`LoopDriver`：宏观门放行后，`workflow_template` version 1 / `first_real_chain` "
    "展开成一条 advancement todo、一个子会话、一次 `read_file_py`、根上归档为 done，"
    "根与子都没有 human effect。已有 human pending 时场景停在非终态、不 skip、不 complete、"
    "不 cancel。这不是人可以离开生产终端。"
)
SESSION_SPEC = {"route_policy_name": "controller", "version": 1}
EXCERPT_TEXT = "bounded excerpt"
IDLE = psycopg2.extensions.TRANSACTION_STATUS_IDLE
TERMINAL = ("completed", "failed", "cancelled")
DENIED_TOOLS = ("edit", "write", "bash")
SHAPE = {"ok": False, "reason": "shape", "admitted": False}
MISSING = {"ok": False, "reason": "missing", "admitted": False}
EVAL_KEYS = {"schema_version", "ok", "admitted", "should_run", "quota_eligible", "gate"}
MACRO_SIG = "public.v13_macro_suggestion(uuid,jsonb)"
MACRO_IDENT = "public.v13_macro_suggestion(p_sid uuid, p_suggestion jsonb)"
DRIVER_BASE = "fb295ac6c7459bb98dac57e37883af549d2d8a4c"
SQL_NULL = object()
JSON_NULL = object()
PRED_SIG = {
    "should_run": "public.v13_should_run(uuid)",
    "gate": "public.v13_should_run_gate(uuid)",
    "quota": "public.v13_quota_eligible(uuid)",
}
AUTH_SIG = "public.v13_control_authorized(uuid,uuid)"
BANNED_TOKENS = (
    "dblink",
    "pg_net",
    "lo_import",
    "lo_export",
    "pg_read_file",
    "pg_write_file",
    "copy program",
    "v13_wake_is_satisfied_v1",
    "v13_claim(",
    "v13_claim_fair",
    "13002",
    "13003",
)
DECIDE_BANNED = {
    "decide",
    "decide_exit",
    "run_turn",
    "tick",
    "plan_prelude",
    "plan_admit",
    "run",
    "_run",
    "v13_agentctl_observe",
    "v13_agentctl_steer",
    "v13_agentctl_answer",
    "v13_agentctl_cancel",
    "v13_parse",
    "RealChain",
    "GoalSupervisor",
}
WAKE_CALLS = {"v13_wake_is_satisfied_v1", "v13_claim", "v13_claim_fair"}
HUMAN_AST_BANNED = {
    "v13_cancel",
    "v13_complete",
    "v13_agentctl_answer",
    "v13_agentctl_cancel",
}
READ_TOOLS = ("read_pi", "read_file_swift", "read_file_py", "read_duck")
CATALOG_TOOLS = READ_TOOLS + (
    "agentctl_observe",
    "agentctl_steer",
    "agentctl_answer",
    "agentctl_cancel",
    "spawn_subsession",
)
_OIDS = {}


def check(label, condition, detail=""):
    global N
    N += 1
    mark = "PASS" if condition else "FAIL"
    extra = ""
    if detail != "" and (not condition or len(str(detail)) < 240):
        extra = ": %s" % (detail,)
    print("[%s] %s%s" % (mark, label, extra))
    if not condition:
        raise AssertionError("%s: %s" % (label, detail))


def q1(cur, sql, params=None):
    row = qrow(cur, sql, params)
    return None if row is None else row[0]


def qrow(cur, sql, params=None):
    cur.execute(sql, params)
    return cur.fetchone()


def squash(text):
    return re.sub(r"\s+", " ", text.lower())


def call_name(node):
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def function_node(tree, name):
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError("missing function %s" % name)


def parent_map(tree):
    parents = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    return parents


def enclosing_function(parents, node):
    cur = parents.get(node)
    while cur is not None and not isinstance(cur, ast.FunctionDef):
        cur = parents.get(cur)
    return "" if cur is None else cur.name


def canonical_sid(value):
    return str(uuid.UUID(str(value)))


def suggestion(sid, suggested=True, note=SQL_NULL):
    body = {
        "schema_version": 1,
        "kind": "macro_suggestion",
        "subject_session_id": sid,
        "suggested_should_run": suggested,
    }
    if note is not SQL_NULL:
        body["note"] = note
    return body


def eval_invariant(obj):
    if not isinstance(obj, dict) or set(obj) != EVAL_KEYS:
        return False
    should = obj["should_run"] is True
    quota = obj["quota_eligible"] is True
    return (
        obj["schema_version"] == 1
        and obj["ok"] is True
        and obj["admitted"] is (should and quota)
        and should is (obj["gate"] is None)
    )


def open_controller(cur):
    cur.execute(
        "SELECT v13_plan_commit_entry(%s::jsonb)",
        (json.dumps(SESSION_SPEC),))
    return canonical_sid(cur.fetchone()[0])


def v13_workflow_resolve(cur):
    cur.execute("SELECT v13_workflow_resolve('workflow_template', 1)")
    return as_obj(cur.fetchone()[0])


def v13_macro_suggestion(cur, sid, payload):
    sid_expr = "NULL::uuid" if sid is None else "%s::uuid"
    if payload is SQL_NULL:
        sug_expr = "NULL::jsonb"
        sug_params = ()
    elif payload is JSON_NULL:
        sug_expr = "'null'::jsonb"
        sug_params = ()
    else:
        sug_expr = "%s::jsonb"
        sug_params = (json.dumps(payload),)
    sid_params = () if sid is None else (sid,)
    sql = "SELECT public.v13_macro_suggestion(%s, %s)" % (sid_expr, sug_expr)
    cur.execute(sql, sid_params + sug_params)
    return as_obj(cur.fetchone()[0])


def v13_plan_writer(driver, root, apply_id, canonical):
    return driver.plan_writer(root, apply_id, "plan_commit", canonical)


def v13_submit_override(driver, root):
    driver.submit_override(root)


def v13_advance(driver, sid):
    return driver.advance(sid)


def v13_child_pointer(cur, child, parent, root, todo, up_to):
    cur.execute(
        "SELECT v13_child_pointer(%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s)",
        (child, parent, root, todo, up_to))
    return cur.fetchone()[0]


def v13_complete(cur, effect_id, attempt, fence, status, result):
    cur.execute(
        "SELECT v13_complete(%s::uuid, %s, %s, %s, %s::jsonb)",
        (effect_id, attempt, fence, status, json.dumps(result)))
    return cur.fetchone()[0]


def v13_goal_stop(cur, sid, reason):
    cur.execute("SELECT v13_goal_stop(%s::uuid, %s)", (sid, reason))
    return cur.fetchone()[0]


def v13_enqueue_effect(cur, sid, request):
    cur.execute(
        "SELECT v13_enqueue_effect(%s, 'human', %s::jsonb)",
        (sid, json.dumps(request)))
    return str(cur.fetchone()[0])


def bind_advance_cap(driver, words):
    original_advance = driver.advance
    original_settle = driver._settlement_advance

    def wrapped_advance(sid, snap=None):
        if len(words) >= GOAL_WORKFLOW_MAX_ADVANCE:
            raise AssertionError("scene_advance_cap")
        word = original_advance(sid, snap)
        words.append((canonical_sid(sid), word))
        return word

    def wrapped_settle(cur, sid, *args, **kwargs):
        if len(words) >= GOAL_WORKFLOW_MAX_ADVANCE:
            raise AssertionError("scene_advance_cap")
        word = original_settle(cur, sid, *args, **kwargs)
        words.append((canonical_sid(sid), word))
        return word

    driver.advance = wrapped_advance
    driver._settlement_advance = wrapped_settle


def assert_idle(driver):
    status = driver.connection().get_transaction_status()
    if status != IDLE:
        raise AssertionError("io inside txn: %s" % status)


def require_excerpt(excerpt):
    if not isinstance(excerpt, str) or excerpt == "" or len(excerpt) > EXCERPT_CAP:
        raise RuntimeError("excerpt cap")


def function_call_counts(cur):
    cur.execute("SELECT funcid::text, calls FROM pg_stat_xact_user_functions")
    return {row[0]: row[1] for row in cur.fetchall()}


def oid_of(cur, sig):
    if sig not in _OIDS:
        _OIDS[sig] = q1(cur, "SELECT %s::regprocedure::oid::text", (sig,))
    return _OIDS[sig]


def arm_probe(cur):
    oid = oid_of(cur, AUTH_SIG)
    before = function_call_counts(cur).get(oid, 0)
    cur.execute("SAVEPOINT gw_probe")
    try:
        cur.execute("SELECT public.v13_control_authorized(NULL::uuid, NULL::uuid)")
        cur.fetchone()
        after = function_call_counts(cur).get(oid, 0)
    except psycopg2.Error as exc:
        cur.execute("ROLLBACK TO SAVEPOINT gw_probe")
        raise AssertionError("environment block: track_functions: %s" % exc)
    cur.execute("ROLLBACK TO SAVEPOINT gw_probe")
    if after - before < 1:
        raise AssertionError("environment block: track_functions")


def read_window(cur):
    cur.execute(
        "SELECT session_id::text, status, next_seq, parent_session_id::text "
        "FROM sessions ORDER BY 1")
    sessions = cur.fetchall()
    cur.execute(
        "SELECT event_id::text, session_id::text, seq, type, payload::text "
        "FROM events ORDER BY 2, 3, 1")
    events = cur.fetchall()
    cur.execute(
        "SELECT effect_id::text, session_id::text, status, kind, tool_name, "
        "attempt_no, fence, lease_owner "
        "FROM effects ORDER BY 1")
    effects = cur.fetchall()
    cur.execute(
        "SELECT name, version, active, value::text FROM v13_policies ORDER BY 1, 2")
    policies = cur.fetchall()
    cur.execute(
        "SELECT policy_name, policy_version, state FROM v13_route_policies ORDER BY 1, 2")
    routes = cur.fetchall()
    artifacts = q1(cur, "SELECT count(*) FROM artifacts")
    latches = q1(cur, "SELECT count(*) FROM latches")
    return sessions, events, effects, policies, routes, artifacts, latches


def measured_macro(cur, sid, payload):
    arm_probe(cur)
    oids = {name: oid_of(cur, sig) for name, sig in PRED_SIG.items()}
    baseline = function_call_counts(cur)
    before = read_window(cur)
    got = v13_macro_suggestion(cur, sid, payload)
    after = read_window(cur)
    now = function_call_counts(cur)
    deltas = {
        name: now.get(oid, 0) - baseline.get(oid, 0)
        for name, oid in oids.items()
    }
    return got, before == after, deltas


def token_hits(text):
    norm = squash(text)
    found = [token for token in BANNED_TOKENS if token in norm]
    if "security definer" in norm:
        found.append("security definer")
    if "insert into tools" in norm:
        found.append("insert into tools")
    if "v13_agentctl_" in norm:
        found.append("v13_agentctl_")
    return found


def fn_rows(cur):
    cur.execute(
        """
        SELECT n.nspname || '.' || p.proname
                 || '(' || pg_get_function_identity_arguments(p.oid) || ')',
               pg_get_functiondef(p.oid),
               r.rolname,
               p.prosecdef,
               p.proacl::text,
               p.provolatile,
               p.proconfig::text,
               p.proisstrict
          FROM pg_proc p
          JOIN pg_namespace n ON n.oid = p.pronamespace
          JOIN pg_roles r ON r.oid = p.proowner
         WHERE n.nspname = 'public'
           AND (p.proname LIKE 'v13\\_%' OR p.proname = 'v_goal_tree')
         ORDER BY 1
        """)
    rows = {}
    for sig, body, owner, secdef, acl, vol, config, strict in cur.fetchall():
        rows[sig] = (
            hashlib.sha256(body.encode()).hexdigest(),
            owner,
            secdef,
            acl,
            vol,
            config,
            strict,
        )
    return rows


def tool_rows(cur):
    cur.execute(
        "SELECT name, description, kind, handler, param_spec::text, enabled "
        "FROM tools ORDER BY name")
    return cur.fetchall()


def rel_rows(cur):
    cur.execute(
        """
        SELECT c.relname, c.relkind
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public'
         ORDER BY 1, 2
        """)
    rels = cur.fetchall()
    cur.execute(
        """
        SELECT table_name, column_name
          FROM information_schema.columns
         WHERE table_schema = 'public'
         ORDER BY 1, 2
        """)
    cols = cur.fetchall()
    cur.execute(
        """
        SELECT tgname, tgrelid::regclass::text
          FROM pg_trigger
         WHERE NOT tgisinternal
         ORDER BY 1, 2
        """)
    triggers = cur.fetchall()
    cur.execute(
        "SELECT indexname FROM pg_indexes WHERE schemaname = 'public' ORDER BY 1")
    indexes = [row[0] for row in cur.fetchall()]
    return rels, cols, triggers, indexes


def spawn_row(cur):
    cur.execute(
        "SELECT name, description, kind, handler, param_spec::text, enabled "
        "FROM tools WHERE name = 'spawn_subsession'")
    return cur.fetchone()


def policy_snapshot(cur):
    cur.execute(
        "SELECT name, version, active, value::text FROM v13_policies ORDER BY 1, 2")
    policies = cur.fetchall()
    cur.execute(
        "SELECT policy_name, policy_version, state, created_at::text, frozen_at::text "
        "FROM v13_route_policies ORDER BY 1, 2")
    routes = cur.fetchall()
    return policies, routes


def active_policy(cur, name):
    cur.execute(
        "SELECT version, value::text FROM v13_policies WHERE name = %s AND active",
        (name,))
    return cur.fetchone()


def constant_proof():
    text = (ROOT / "test_goal_workflow.py").read_text()
    needle = "GOAL_WORKFLOW_MAX_ADVANCE" + " = 4"
    if text.count(needle) != 1:
        return False, "assignment count"
    try:
        out = subprocess.check_output(
            ["git", "grep", "-n", "-F", "GOAL_WORKFLOW_MAX_ADVANCE", "--", "v13"],
            cwd=str(AGENT_ROOT),
        ).decode()
    except subprocess.CalledProcessError as exc:
        return False, exc.output
    bad = []
    for line in out.splitlines():
        path = line.split(":", 1)[0]
        if path != "v13/goal_workflow/test_goal_workflow.py":
            bad.append(path)
    if bad or not out.strip():
        return False, bad or "no hits"
    return True, "ok"


def actl_driver_untouched():
    try:
        subprocess.check_call(
            ["git", "cat-file", "-e", DRIVER_BASE + "^{commit}"],
            cwd=str(AGENT_ROOT))
        original = subprocess.check_output(
            ["git", "show", DRIVER_BASE + ":v13/loop_driver/driver.py"],
            cwd=str(AGENT_ROOT))
        current = (AGENT_ROOT / "v13/loop_driver/driver.py").read_bytes()
        restored, _block = r1_driver_restore(current, original)
        ok = restored == original
        detail = ""
    except AssertionError as exc:
        ok = False
        detail = str(exc)
    check("actl_driver_untouched", ok, detail)


def static_source():
    text = (ROOT / "test_goal_workflow.py").read_text()
    first = (__doc__ or "").split("\n\n", 1)[0]
    check("claim sentence", first == CLAIM, first)
    tree = ast.parse(text)
    parents = parent_map(tree)
    problems = []
    stops = []
    enqueues = []
    wake = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in ("run", "_run"):
            problems.append("def " + node.name)
        if not isinstance(node, ast.Call):
            continue
        name = call_name(node)
        if name in DECIDE_BANNED:
            problems.append("call " + name)
        if name in WAKE_CALLS:
            wake.append(name)
        if name == "v13_goal_stop":
            stops.append(enclosing_function(parents, node))
        elif name == "v13_enqueue_effect":
            enqueues.append(enclosing_function(parents, node))
    check("actl_scene_no_decide_exit", problems == [], problems)
    check(
        "goal_stop and enqueue parents",
        stops == ["scene_macro_reject_zero_write"]
        and enqueues == ["scene_human_pending_holds"],
        (stops, enqueues))
    human = function_node(tree, "scene_human_pending_holds")
    human_problems = []
    for node in ast.walk(human):
        if isinstance(node, ast.Call) and call_name(node) in HUMAN_AST_BANNED:
            human_problems.append("call " + call_name(node))
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if re.search(r"\bUPDATE\b", node.value, re.I):
                human_problems.append("update")
            for name in HUMAN_AST_BANNED:
                if name in node.value:
                    human_problems.append("sql " + name)
    if human_problems:
        check("scene_human_pending_holds", False, human_problems)
    file_hits = token_hits(SQL)
    if file_hits or wake:
        check("scene_no_wake_no_claim", False, (file_hits, wake))
    ok, detail = constant_proof()
    if not ok:
        check("scene_advance_cap", False, detail)
    return file_hits, wake, ok


def install_compare(cur, server, spawn_before):
    before_fns = fn_rows(cur)
    before_tools = tool_rows(cur)
    before_rels = rel_rows(cur)
    before_meta = qrow(
        cur, "SELECT revision, candidate_generation_revision FROM v13_tools_meta")
    before_events = q1(cur, "SELECT count(*) FROM events")
    before_effects = q1(cur, "SELECT count(*) FROM effects")
    before_policies = policy_snapshot(cur)
    cur.connection.commit()
    run_psql(server, DB, SQL)
    after_fns = fn_rows(cur)
    added = set(after_fns) - set(before_fns)
    check("one new function", added == {MACRO_IDENT}, added)
    for sig, row in before_fns.items():
        check("function unchanged " + sig, after_fns[sig] == row)
    new = after_fns[MACRO_IDENT]
    config = (new[5] or "").replace(" ", "")
    owner = q1(cur, "SELECT current_user")
    check(
        "macro attrs",
        new[1] == owner
        and new[2] is False
        and new[4] == "s"
        and new[6] is False
        and "search_path=pg_catalog,public" in config,
        new[1:])
    check("tools unchanged", tool_rows(cur) == before_tools)
    names = {row[0] for row in before_tools}
    check("catalog tools present", set(CATALOG_TOOLS) <= names, sorted(set(CATALOG_TOOLS) - names))
    meta = qrow(cur, "SELECT revision, candidate_generation_revision FROM v13_tools_meta")
    check("tools meta unchanged", meta == before_meta, (before_meta, meta))
    check("relations unchanged", rel_rows(cur) == before_rels)
    check("install events unchanged", q1(cur, "SELECT count(*) FROM events") == before_events)
    check("install effects unchanged", q1(cur, "SELECT count(*) FROM effects") == before_effects)
    check("policy rows unchanged", policy_snapshot(cur) == before_policies)
    state = q1(
        cur,
        "SELECT state FROM v13_route_policies "
        "WHERE policy_name = 'controller' AND policy_version = 1")
    if state is None:
        raise AssertionError("41 was not loaded")
    check("controller frozen", state == "frozen", state)
    check(
        "macro named null",
        q1(cur, "SELECT public.v13_named_sql_writer('v13_macro_suggestion')") is None)
    check(
        "macro writer false",
        q1(cur, "SELECT public.v13_spawn_writer_ok('v13_macro_suggestion')") is False)
    check(
        "observe named null",
        q1(cur, "SELECT public.v13_named_sql_writer('v13_agentctl_observe')") is None)
    check(
        "spawn writer true",
        q1(cur, "SELECT public.v13_spawn_writer_ok('v13_spawn_subsession')") is True)
    check(
        "route execute",
        q1(cur, "SELECT has_function_privilege('v13_route', %s, 'EXECUTE')", (MACRO_SIG,))
        is True)
    for role in ("public", "v13_recall", "v13_worker", "v13_resolve", "v13_spawn_owner"):
        check(
            role + " no execute",
            q1(cur, "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, MACRO_SIG,))
            is False)
    sid = open_controller(cur)
    policy = qrow(
        cur,
        "SELECT route_policy_name, route_policy_version, parent_session_id::text, status "
        "FROM sessions WHERE session_id = %s::uuid",
        (sid,))
    check(
        "controller session",
        policy[0] == "controller" and policy[1] == 1 and policy[2] is None
        and policy[3] not in TERMINAL,
        policy)
    cur.execute("SET ROLE v13_route")
    try:
        got = v13_macro_suggestion(cur, sid, suggestion(sid, True))
    finally:
        cur.execute("RESET ROLE")
    check(
        "route eval",
        got.get("ok") is True and got.get("admitted") is True and "reason" not in got
        and eval_invariant(got),
        got)
    cur.execute("SAVEPOINT gw_recall")
    cur.execute("SET ROLE v13_recall")
    code = None
    try:
        try:
            v13_macro_suggestion(cur, sid, suggestion(sid, True))
        except psycopg2.Error as exc:
            code = exc.pgcode
            cur.execute("ROLLBACK TO SAVEPOINT gw_recall")
        else:
            cur.execute("ROLLBACK TO SAVEPOINT gw_recall")
    finally:
        cur.execute("RESET ROLE")
    check("recall 42501", code == "42501", code)
    after_spawn = spawn_row(cur)
    check("spawn enabled after install", after_spawn is not None and after_spawn[5] is True)
    check("spawn row after install", after_spawn == spawn_before, after_spawn)
    cur.connection.commit()
    return active_policy(cur, "quota_window"), active_policy(cur, "should_run"), spawn_before


def scene_no_wake_no_claim(cur, file_hits, wake_calls):
    body = q1(cur, "SELECT pg_get_functiondef(%s::regprocedure)", (MACRO_SIG,))
    prosrc = q1(
        cur,
        "SELECT prosrc FROM pg_proc WHERE oid = %s::regprocedure",
        (MACRO_SIG,))
    hits = token_hits(body) + token_hits(prosrc)
    if re.search(r"\bexecute\b", prosrc or "", re.I):
        hits.append("prosrc execute")
    if re.search(r"exception\s+when", prosrc or "", re.I):
        hits.append("exception when")
    if "v13_agentctl_" in (prosrc or "").lower():
        hits.append("prosrc v13_agentctl_")
    check(
        "scene_no_wake_no_claim",
        not file_hits and not wake_calls and hits == [],
        (file_hits, wake_calls, hits))


def expect_shape(cur, label, sid, payload, zero_pred=True):
    got, same, deltas = measured_macro(cur, sid, payload)
    pred_ok = (not zero_pred) or deltas == {"should_run": 0, "gate": 0, "quota": 0}
    check(label, got == SHAPE and same and pred_ok, (got, same, deltas))
    return got


def expect_eval(cur, label, sid, payload, admitted=True):
    got, same, deltas = measured_macro(cur, sid, payload)
    pred_ok = all(deltas[name] >= 1 for name in ("should_run", "gate", "quota"))
    check(
        label,
        same and pred_ok and eval_invariant(got) and got["admitted"] is admitted
        and got["ok"] is True,
        (got, same, deltas))
    return got


def scene_suggestion_shape_zero_write(cur):
    sid_a = open_controller(cur)
    sid_b = open_controller(cur)
    cur.connection.commit()
    missing_sid = str(uuid.uuid4())
    present = q1(cur, "SELECT 1 FROM sessions WHERE session_id = %s::uuid", (missing_sid,))
    check("missing uuid has no row", present is None, present)
    expect_shape(cur, "shape sql null", sid_a, SQL_NULL)
    expect_shape(cur, "shape json null", sid_a, JSON_NULL)
    expect_shape(cur, "shape array", sid_a, [])
    expect_shape(cur, "shape scalar", sid_a, "scalar")
    expect_shape(cur, "shape number", sid_a, 1)
    expect_shape(cur, "shape bool", sid_a, True)
    expect_shape(cur, "shape empty object", sid_a, {})
    for key in ("kind", "schema_version", "subject_session_id", "suggested_should_run"):
        body = suggestion(sid_a, True)
        del body[key]
        expect_shape(cur, "shape missing " + key, sid_a, body)
    extra_principal = suggestion(sid_a, True)
    extra_principal["source_principal"] = "operator"
    expect_shape(cur, "shape extra source_principal", sid_a, extra_principal)
    extra_admitted = suggestion(sid_a, True)
    extra_admitted["admitted"] = True
    expect_shape(cur, "shape extra admitted", sid_a, extra_admitted)
    bad_kind = suggestion(sid_a, True)
    bad_kind["kind"] = "other"
    expect_shape(cur, "shape kind other", sid_a, bad_kind)
    padded = suggestion(sid_a, True)
    padded["kind"] = " macro_suggestion"
    expect_shape(cur, "shape kind pad", sid_a, padded)
    trailed = suggestion(sid_a, True)
    trailed["kind"] = "macro_suggestion "
    expect_shape(cur, "shape kind trail", sid_a, trailed)
    for label, version in (
        ("shape version string", "1"),
        ("shape version zero", 0),
        ("shape version two", 2),
        ("shape version fraction", 1.5),
    ):
        body = suggestion(sid_a, True)
        body["schema_version"] = version
        expect_shape(cur, label, sid_a, body)
    upper = suggestion(sid_a.upper(), True)
    expect_shape(cur, "shape subject upper", sid_a, upper)
    spaced = suggestion(" " + sid_a, True)
    expect_shape(cur, "shape subject space", sid_a, spaced)
    plain = suggestion(sid_a.replace("-", ""), True)
    expect_shape(cur, "shape subject plain", sid_a, plain)
    other = suggestion(sid_b, True)
    got = expect_shape(cur, "shape subject other session", sid_a, other)
    check("other subject is shape", got["reason"] == "shape", got)
    for label, value in (("shape suggested string", "true"), ("shape suggested number", 1)):
        body = suggestion(sid_a, True)
        body["suggested_should_run"] = value
        expect_shape(cur, label, sid_a, body)
    expect_shape(cur, "shape note null", sid_a, suggestion(sid_a, True, None))
    expect_shape(cur, "shape note 257", sid_a, suggestion(sid_a, True, "字" * 257))
    expect_eval(cur, "eval note 256", sid_a, suggestion(sid_a, True, "字" * 256))
    expect_eval(cur, "eval omit note", sid_a, suggestion(sid_a, True))
    expect_eval(cur, "eval note empty", sid_a, suggestion(sid_a, True, ""))
    expect_eval(cur, "eval note blank", sid_a, suggestion(sid_a, True, "   "))
    expect_shape(cur, "shape null sid", None, suggestion(sid_a, True))
    missing_payload = suggestion(missing_sid, True)
    got, same, deltas = measured_macro(cur, missing_sid, missing_payload)
    check(
        "missing session",
        got == MISSING and same and deltas == {"should_run": 0, "gate": 0, "quota": 0},
        (got, same, deltas))
    expect_shape(cur, "shape beats missing", missing_sid, SQL_NULL)
    discard_sid = open_controller(cur)
    cur.connection.commit()
    got, same, deltas = measured_macro(cur, discard_sid, suggestion(discard_sid, False))
    check(
        "discard suggested false",
        same and eval_invariant(got) and got["admitted"] is True
        and got["should_run"] is True and got["quota_eligible"] is True
        and got["gate"] is None,
        (got, same, deltas))
    quiet = open_controller(cur)
    cur.connection.commit()
    original_quota = active_policy(cur, "quota_window")
    original_should = active_policy(cur, "should_run")
    quota_value = json.dumps({
        "schema_version": 1,
        "window_hours": 8760,
        "slot_minutes": 0,
        "allowed": 0,
    })
    cur.execute("SAVEPOINT gw_quota")
    try:
        cur.execute(
            "INSERT INTO v13_policies (name, version, value, active) "
            "VALUES ('quota_window', 2, %s::jsonb, false)",
            (quota_value,))
        cur.execute(
            "UPDATE v13_policies SET active = false "
            "WHERE name = 'quota_window' AND version = 1")
        cur.execute(
            "UPDATE v13_policies SET active = true "
            "WHERE name = 'quota_window' AND version = 2")
        got, same, _deltas = measured_macro(cur, quiet, suggestion(quiet, True))
        quota_ok = (
            same and eval_invariant(got) and got["quota_eligible"] is False
            and got["should_run"] is False and got["admitted"] is False
            and got["gate"] == "quota_window")
    finally:
        cur.execute("ROLLBACK TO SAVEPOINT gw_quota")
    check("quota allowed 0", quota_ok, got)
    check(
        "quota version restored",
        active_policy(cur, "quota_window") == original_quota
        and q1(cur, "SELECT count(*) FROM v13_policies WHERE name = 'quota_window' AND version = 2")
        == 0)
    should_version = q1(cur, "SELECT COALESCE(max(version), 0) FROM v13_policies WHERE name = 'should_run'")
    next_should = int(should_version) + 1
    shadow_value = json.dumps({
        "schema_version": 1,
        "gates": [{"id": "quota_window", "effect": "shadow"}],
    })
    cur.execute("SAVEPOINT gw_shadow")
    try:
        cur.execute(
            "INSERT INTO v13_policies (name, version, value, active) "
            "VALUES ('should_run', %s, %s::jsonb, false)",
            (next_should, shadow_value))
        cur.execute(
            "INSERT INTO v13_policies (name, version, value, active) "
            "VALUES ('quota_window', 2, %s::jsonb, false)",
            (quota_value,))
        cur.execute(
            "UPDATE v13_policies SET active = false "
            "WHERE name = 'should_run' AND version = %s",
            (original_should[0],))
        cur.execute(
            "UPDATE v13_policies SET active = false "
            "WHERE name = 'quota_window' AND version = 1")
        cur.execute(
            "UPDATE v13_policies SET active = true "
            "WHERE name = 'should_run' AND version = %s",
            (next_should,))
        cur.execute(
            "UPDATE v13_policies SET active = true "
            "WHERE name = 'quota_window' AND version = 2")
        got, same, _deltas = measured_macro(cur, quiet, suggestion(quiet, True))
        shadow_ok = (
            same and eval_invariant(got) and got["should_run"] is True
            and got["quota_eligible"] is False and got["admitted"] is False
            and got["gate"] is None)
    finally:
        cur.execute("ROLLBACK TO SAVEPOINT gw_shadow")
    check("shadow conjunction", shadow_ok, got)
    restored = (
        active_policy(cur, "should_run") == original_should
        and active_policy(cur, "quota_window") == original_quota
        and q1(cur, "SELECT count(*) FROM v13_policies WHERE name = 'quota_window' AND version = 2")
        == 0
        and q1(
            cur,
            "SELECT count(*) FROM v13_policies WHERE name = 'should_run' AND version = %s",
            (next_should,)) == 0
        and q1(
            cur,
            "SELECT count(*) FROM v13_policies "
            "WHERE name = 'quota_window' AND value->>'allowed' = '0'") == 0)
    check("seeds restored", restored, (active_policy(cur, "should_run"), active_policy(cur, "quota_window")))
    check(
        "scene_suggestion_shape_zero_write",
        quota_ok and shadow_ok and restored)
    cur.connection.commit()


def scene_macro_reject_zero_write(cur):
    sid = open_controller(cur)
    busy = q1(
        cur,
        "SELECT count(*) FROM effects "
        "WHERE session_id = %s::uuid AND status IN ('ready', 'claimed', 'unknown')",
        (sid,))
    check("reject session quiet", busy == 0, busy)
    v13_goal_stop(cur, sid, "operator_stop")
    stopped = q1(
        cur,
        "SELECT count(*) FROM events WHERE session_id = %s::uuid AND type = 'goal/stopped'",
        (sid,))
    check("one goal stopped", stopped == 1, stopped)
    plans_before = q1(
        cur,
        "SELECT count(*) FROM events WHERE session_id = %s::uuid AND type = 'plan/committed'",
        (sid,))
    deltas_before = q1(
        cur,
        "SELECT count(*) FROM events WHERE session_id = %s::uuid AND type = 'todo/delta'",
        (sid,))
    effects_before = q1(
        cur, "SELECT count(*) FROM effects WHERE session_id = %s::uuid", (sid,))
    got, same, _deltas = measured_macro(cur, sid, suggestion(sid, True))
    plans_after = q1(
        cur,
        "SELECT count(*) FROM events WHERE session_id = %s::uuid AND type = 'plan/committed'",
        (sid,))
    deltas_after = q1(
        cur,
        "SELECT count(*) FROM events WHERE session_id = %s::uuid AND type = 'todo/delta'",
        (sid,))
    effects_after = q1(
        cur, "SELECT count(*) FROM effects WHERE session_id = %s::uuid", (sid,))
    stopped_after = q1(
        cur,
        "SELECT count(*) FROM events WHERE session_id = %s::uuid AND type = 'goal/stopped'",
        (sid,))
    check(
        "scene_macro_reject_zero_write",
        same and eval_invariant(got) and got["admitted"] is False
        and got["should_run"] is False and got["quota_eligible"] is True
        and got["gate"] == "goal_stopped"
        and plans_after == plans_before == 0
        and deltas_after == deltas_before == 0
        and effects_after == effects_before == 0
        and stopped_after == 1,
        got)
    cur.connection.commit()


def scene_human_pending_holds(cur):
    root = open_controller(cur)
    eid = v13_enqueue_effect(
        cur, root, {"schema_version": 1, "interaction_ref": "ix-goal-workflow-hold"})
    row = qrow(
        cur,
        "SELECT status, kind FROM effects WHERE effect_id = %s::uuid",
        (eid,))
    check("human enqueued", row == ("ready", "human"), row)
    got, same, _deltas = measured_macro(cur, root, suggestion(root, True))
    status = q1(cur, "SELECT status FROM effects WHERE effect_id = %s::uuid", (eid,))
    cancel_n = q1(
        cur,
        "SELECT count(*) FROM events WHERE session_id = %s::uuid AND type = 'cancel/requested'",
        (root,))
    responded_n = q1(
        cur,
        "SELECT count(*) FROM events WHERE session_id = %s::uuid AND type = 'human/responded'",
        (root,))
    session_status = q1(
        cur, "SELECT status FROM sessions WHERE session_id = %s::uuid", (root,))
    check(
        "scene_human_pending_holds",
        same and eval_invariant(got) and got["admitted"] is False
        and got["should_run"] is False and got["quota_eligible"] is True
        and got["gate"] == "human_pending"
        and status == "ready" and cancel_n == 0 and responded_n == 0
        and session_status not in TERMINAL,
        (got, status, session_status))
    cur.connection.commit()


class Probe:
    def __init__(self):
        self.driver = None
        self.calls = []

    def llm(self, layers, peek):
        txn = None if self.driver.conn is None else self.driver.conn.get_transaction_status()
        self.calls.append({
            "channel": "llm",
            "kind": peek.get("kind"),
            "layers": layers,
            "txn": txn,
        })
        if txn != IDLE:
            raise AssertionError("llm inside txn")
        if peek.get("kind") == "plan":
            answer = {"todos": [{
                "text": "read one bounded file",
                "task_class": "advancement_task",
                "status": "runnable",
                "verb": "add_new",
                "due": None,
            }]}
            if not _plan_answer_ok(answer):
                raise AssertionError("plan shape")
            return answer
        answer = {
            "text": "open one child for the bounded read",
            "tool_calls": [{
                "id": "tc-read",
                "name": "spawn_subsession",
                "args": {"task": "read the bound file"},
            }],
        }
        if not _spawn_answer_ok(answer):
            raise AssertionError("spawn shape")
        return answer

    def read_file_py(self, peek):
        txn = None if self.driver.conn is None else self.driver.conn.get_transaction_status()
        self.calls.append({
            "channel": "tool",
            "tool_name": peek.get("tool_name"),
            "txn": txn,
        })
        if txn != IDLE:
            raise AssertionError("tool inside txn")
        return EXCERPT_TEXT


class Scene:
    def __init__(self):
        self.driver = None
        self.root = None
        self.child = None
        self.todo_id = None
        self.words = []
        self.macros = []
        self.layers = None
        self.llm_effect = None
        self.read_effect = None
        self.probe = None


def macro_checkpoint(scene, root):
    driver = scene.driver
    assert_idle(driver)
    cur = driver.connection().cursor()
    before = read_window(cur)
    got = v13_macro_suggestion(cur, root, suggestion(root, True))
    after = read_window(cur)
    driver.connection().commit()
    if before != after:
        raise AssertionError("macro checkpoint wrote")
    if got.get("ok") is not True or got.get("admitted") is not True or not eval_invariant(got):
        raise AssertionError("macro checkpoint refused: %s" % (got,))
    scene.macros.append(got)
    return got


def canonical_plan(seq, proposal):
    if seq is None:
        raise AssertionError("waterline")
    todos = []
    for item in proposal["todos"]:
        text = item["text"]
        tid = item.get("todo_id") or str(uuid.uuid4())
        todos.append({
            "todo_id": str(tid),
            "text": text,
            "text_hash": text_hash(text),
            "task_class": item["task_class"],
            "status": item["status"],
            "due": item.get("due"),
            "verb": item["verb"],
        })
    todos.sort(key=lambda row: uuid.UUID(row["todo_id"]).bytes)
    canonical = {
        "schema_version": 1,
        "call_kind": "plan_commit",
        "based_on_seq": int(seq),
        "supersedes": None,
        "todos": todos,
    }
    return canonical, todos[0]["todo_id"]


def claim_and_complete(conn, driver, effect_id, excerpt):
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE effects SET status='claimed', attempt_no=attempt_no+1, "
            "fence=fence+1, lease_owner=%s, "
            "lease_until=clock_timestamp()+interval '1 hour' "
            "WHERE effect_id=%s::uuid AND status='ready' "
            "RETURNING attempt_no, fence",
            (driver.worker, effect_id))
        claimed = cur.fetchone()
        if claimed is None:
            raise AssertionError("read not ready")
        attempt, fence = claimed
        outcome = v13_complete(
            cur, effect_id, attempt, fence, "succeeded", {"excerpt": excerpt})
        return outcome
    except Exception:
        conn.rollback()
        raise


def prove_bad_excerpt(cur, effect_id, excerpt, attempt_no):
    cur.execute("SAVEPOINT gw_excerpt")
    raised = False
    try:
        require_excerpt(excerpt)
    except RuntimeError:
        raised = True
    cur.execute("ROLLBACK TO SAVEPOINT gw_excerpt")
    row = qrow(
        cur,
        "SELECT status, attempt_no FROM effects WHERE effect_id = %s::uuid",
        (effect_id,))
    if not raised or row != ("ready", attempt_no):
        raise AssertionError("bad excerpt mutated effect: %s %s" % (excerpt, row))


def explain_spawn_waiting(driver, root):
    conn = driver.connection()
    cur = conn.cursor()
    try:
        should = q1(cur, "SELECT v13_should_run(%s::uuid)", (root,))
        allowed = q1(cur, "SELECT v13_spawn_batch_allowed(%s::uuid, 1)", (root,))
        conn.commit()
    except psycopg2.Error as exc:
        conn.rollback()
        return "word 2 is waiting (diagnose failed: %s)" % exc
    where = "plan_arm :486" if should is not True else "plan_arm :489"
    return "word 2 is waiting at %s (should_run=%s v13_spawn_batch_allowed=%s)" % (
        where, should, allowed)


def assert_product_seeds(cur, quota_seed, should_seed):
    quota = active_policy(cur, "quota_window")
    should = active_policy(cur, "should_run")
    if quota != quota_seed or (quota[1] and '"allowed": 0' in quota[1].replace(" ", "")):
        raise AssertionError("success scene saw allowed=0: %s" % (quota,))
    if should != should_seed:
        raise AssertionError("success scene saw shadow policy: %s" % (should,))


def run_scene(server, quota_seed, should_seed):
    scene = Scene()
    probe = Probe()
    driver = LoopDriver(
        lambda: psycopg2.connect(server.get_uri(DB)),
        llm=probe.llm,
        tools={"read_file_py": probe.read_file_py})
    probe.driver = driver
    scene.driver = driver
    scene.probe = probe
    bind_advance_cap(driver, scene.words)
    try:
        cur = driver.connection().cursor()
        assert_product_seeds(cur, quota_seed, should_seed)
        driver.connection().commit()
        resolved = v13_workflow_resolve(cur)
        driver.connection().commit()
        layers = {}
        for name in LAYER_ORDER:
            text = resolved.get(name)
            if not isinstance(text, str) or text.strip() == "":
                raise AssertionError("empty layer %s" % name)
            layers[name] = text
        driver.layers = layers
        scene.layers = layers
        scene.root = canonical_sid(driver.plan_commit_entry(dict(SESSION_SPEC)))
        root = scene.root
        policy = qrow(
            cur,
            "SELECT route_policy_name, route_policy_version, parent_session_id::text, status "
            "FROM sessions WHERE session_id = %s::uuid",
            (root,))
        driver.connection().commit()
        check(
            "root controller",
            policy[0] == "controller" and policy[1] == 1 and policy[2] is None
            and policy[3] not in TERMINAL,
            policy)
        v13_submit_override(driver, root)
        override_n = q1(
            cur,
            "SELECT count(*) FROM events WHERE session_id = %s::uuid AND type = 'goal/override'",
            (root,))
        water = q1(cur, "SELECT max(seq) FROM events WHERE session_id = %s::uuid", (root,))
        driver.connection().commit()
        check("waterline", override_n == 1 and water is not None and scene.words == [], (override_n, water))
        macro_checkpoint(scene, root)
        proposal = None
        for _ in range(PROVIDER_ATTEMPT_CAP):
            assert_idle(driver)
            answer = driver.llm(driver.four_layers(), {"kind": "plan"})
            if _plan_answer_ok(answer):
                proposal = answer
                break
            driver.attempts_used += 1
        if proposal is None:
            raise AssertionError("plan attempts")
        check("plan attempts unused", driver.attempts_used == 0, driver.attempts_used)
        seq = q1(cur, "SELECT max(seq) FROM events WHERE session_id = %s::uuid", (root,))
        driver.connection().commit()
        canonical, scene.todo_id = canonical_plan(seq, proposal)
        v13_plan_writer(driver, root, str(uuid.uuid4()), canonical)
        fold = qrow(
            cur,
            "SELECT status, task_class FROM v13_plan_todo_fold(%s::uuid) "
            "WHERE todo_id = %s::uuid",
            (root, scene.todo_id))
        ready_n = q1(
            cur,
            "SELECT count(*) FROM effects "
            "WHERE session_id = %s::uuid AND status IN ('ready', 'claimed')",
            (root,))
        driver.connection().commit()
        check("todo runnable", fold == ("runnable", "advancement_task") and ready_n == 0, (fold, ready_n))
        macro_checkpoint(scene, root)
        word = v13_advance(driver, root)
        llm_rows = driver._read(
            "SELECT effect_id::text, request FROM effects "
            "WHERE session_id = %s::uuid AND kind = 'llm' AND status = 'ready'",
            (root,))
        check(
            "first advance waiting",
            word == "waiting" and len(llm_rows) == 1
            and as_obj(llm_rows[0][1]).get("route", {}).get("reason") == "selected_todo",
            (word, llm_rows))
        scene.llm_effect = llm_rows[0][0]
        macro_checkpoint(scene, root)
        state, outcome = driver.serve(root)
        if len(scene.words) >= 2 and scene.words[1][1] == "waiting":
            raise AssertionError(explain_spawn_waiting(driver, root))
        check(
            "serve accepted",
            (state, outcome) == ("served", "accepted")
            and len(scene.words) == 2
            and scene.words[1] == (root, "progressed"),
            (state, outcome, scene.words))
        children = driver._read(
            "SELECT session_id::text FROM sessions WHERE parent_session_id = %s::uuid",
            (root,))
        check("one child", len(children) == 1, children)
        scene.child = canonical_sid(children[0][0])
        child = scene.child
        llm_status = q1(
            cur, "SELECT status FROM effects WHERE effect_id = %s::uuid", (scene.llm_effect,))
        child_status = q1(
            cur, "SELECT status FROM sessions WHERE session_id = %s::uuid", (child,))
        driver.connection().commit()
        check(
            "child open",
            llm_status == "succeeded" and child_status not in TERMINAL,
            (llm_status, child_status))
        cur = driver.connection().cursor()
        parent = q1(
            cur, "SELECT parent_session_id::text FROM sessions WHERE session_id = %s::uuid", (child,))
        mapped = q1(cur, "SELECT v13_plan_map_root(%s::uuid)::text", (child,))
        todos = []
        cur.execute(
            "SELECT todo_id::text, effect_id::text FROM v13_plan_todo_fold(%s::uuid) "
            "WHERE task_class = 'advancement_task' AND effect_id IS NOT NULL",
            (root,))
        todos = cur.fetchall()
        up_to = q1(cur, "SELECT max(seq) FROM events WHERE session_id = %s::uuid", (root,))
        check(
            "pointer inputs",
            parent == root and mapped == root and len(todos) == 1
            and todos[0][1] == scene.llm_effect and up_to is not None,
            (parent, mapped, todos, up_to))
        v13_child_pointer(cur, child, parent, mapped, todos[0][0], up_to)
        driver.connection().commit()
        pointer_n = q1(
            cur,
            "SELECT count(*) FROM events WHERE session_id = %s::uuid AND type = 'workflow/pointer'",
            (child,))
        driver.connection().commit()
        check("one pointer", pointer_n == 1, pointer_n)
        macro_checkpoint(scene, child and root)
        word = v13_advance(driver, child)
        reads = driver._read(
            "SELECT effect_id::text, tool_name, request, attempt_no FROM effects "
            "WHERE session_id = %s::uuid AND status = 'ready' AND kind = 'tool'",
            (child,))
        check(
            "child read waiting",
            word == "waiting" and len(reads) == 1 and reads[0][1] == "read_file_py",
            (word, reads))
        effect_id, tool_name, request, attempt_no = reads[0]
        if tool_name in DENIED_TOOLS or tool_name != "read_file_py":
            raise AssertionError("denied tool %s" % tool_name)
        scene.read_effect = effect_id
        assert_idle(driver)
        handler = driver.tools.get(tool_name)
        if handler is None:
            raise AssertionError("no handler")
        excerpt = handler({
            "effect_id": effect_id,
            "kind": "tool",
            "tool_name": tool_name,
            "request": as_obj(request),
        })
        require_excerpt(excerpt)
        if excerpt != EXCERPT_TEXT:
            raise AssertionError("excerpt %r" % (excerpt,))
        conn = driver.connection()
        cur = conn.cursor()
        prove_bad_excerpt(cur, effect_id, "", attempt_no)
        prove_bad_excerpt(cur, effect_id, "x" * (EXCERPT_CAP + 1), attempt_no)
        outcome = claim_and_complete(conn, driver, effect_id, excerpt)
        conn.commit()
        stored = qrow(
            cur,
            "SELECT status, result->>'excerpt', char_length(result->>'excerpt'), lease_owner "
            "FROM effects WHERE effect_id = %s::uuid",
            (effect_id,))
        driver.connection().commit()
        check(
            "read stored",
            outcome == "accepted" and stored[0] == "succeeded" and stored[1] == EXCERPT_TEXT
            and stored[2] == len(EXCERPT_TEXT) and stored[2] <= 1024
            and stored[3] == driver.worker
            and len(scene.words) == 3,
            (outcome, stored, scene.words))
        macro_checkpoint(scene, root)
        cur = driver.connection().cursor()
        word = driver._settlement_advance(cur, root)
        driver.connection().commit()
        check(
            "fourth settle",
            word == "waiting" and len(scene.words) == 4 and scene.words[3] == (root, "waiting"),
            (word, scene.words))
        check(
            "five macro checkpoints",
            len(scene.macros) == 5 and all(
                item["ok"] is True and item["admitted"] is True for item in scene.macros))
        return scene
    except Exception:
        driver.close()
        scene.driver = None
        raise


def event_count(cur, sid, event_type):
    return q1(
        cur,
        "SELECT count(*) FROM events WHERE session_id = %s::uuid AND type = %s",
        (sid, event_type))


def scene_solved_no_human(scene):
    driver = scene.driver
    cur = driver.connection().cursor()
    root, child = scene.root, scene.child
    words = [word for _sid, word in scene.words]
    human = q1(
        cur,
        "SELECT count(*) FROM effects WHERE session_id IN (%s::uuid, %s::uuid) AND kind = 'human'",
        (root, child))
    steer = event_count(cur, root, "steer/injected") + event_count(cur, child, "steer/injected")
    low = q1(
        cur,
        "SELECT count(*) FROM events WHERE session_id IN (%s::uuid, %s::uuid) "
        "AND payload->>'reason' = 'low_intent_confidence'",
        (root, child))
    kinds = driver._read(
        "SELECT DISTINCT kind FROM effects WHERE session_id IN (%s::uuid, %s::uuid)",
        (root, child))
    kind_set = {row[0] for row in kinds}
    calls = [name for name, _sid in driver.calls]
    llm_calls = [item for item in scene.probe.calls if item["channel"] == "llm"]
    tool_calls = [item for item in scene.probe.calls if item["channel"] == "tool"]
    driver.connection().commit()
    check(
        "scene_solved_no_human",
        words == ["waiting", "progressed", "waiting", "waiting"]
        and [sid for sid, _word in scene.words] == [root, root, child, root]
        and human == 0 and steer == 0 and low == 0
        and len(scene.macros) == 5
        and kind_set <= {"llm", "tool"} and "llm" in kind_set and "tool" in kind_set
        and calls.count("v13_complete") == 1
        and calls.count("v13_advance") == 4
        and driver.attempts_used == 0
        and len(llm_calls) >= 2
        and all(item["txn"] == IDLE for item in llm_calls)
        and len(tool_calls) == 1
        and tool_calls[0]["tool_name"] == "read_file_py"
        and tool_calls[0]["txn"] == IDLE,
        (words, human, steer, low, kind_set, calls))


def scene_archive_waiting(scene):
    cur = scene.driver.connection().cursor()
    root, child = scene.root, scene.child
    done_n = q1(
        cur,
        "SELECT count(*) FROM events WHERE session_id = %s::uuid AND type = 'todo/delta' "
        "AND payload->'canonical'->>'status_to' = 'done'",
        (root,))
    status = q1(
        cur,
        "SELECT status FROM v13_plan_todo_fold(%s::uuid) WHERE todo_id = %s::uuid",
        (root, scene.todo_id))
    root_status = q1(cur, "SELECT status FROM sessions WHERE session_id = %s::uuid", (root,))
    child_status = q1(cur, "SELECT status FROM sessions WHERE session_id = %s::uuid", (child,))
    plans = event_count(cur, root, "plan/committed")
    pointer_n = event_count(cur, child, "workflow/pointer")
    reads = q1(
        cur,
        "SELECT count(*) FROM effects WHERE session_id = %s::uuid "
        "AND tool_name = 'read_file_py' AND status = 'succeeded' "
        "AND result->>'excerpt' = %s",
        (child, EXCERPT_TEXT))
    fold_n = q1(
        cur,
        "SELECT count(*) FROM v13_plan_todo_fold(%s::uuid) WHERE task_class = 'advancement_task'",
        (root,))
    children = q1(
        cur, "SELECT count(*) FROM sessions WHERE parent_session_id = %s::uuid", (root,))
    override_n = event_count(cur, root, "goal/override")
    cancel_n = event_count(cur, root, "cancel/requested") + event_count(cur, child, "cancel/requested")
    responded_n = event_count(cur, root, "human/responded") + event_count(cur, child, "human/responded")
    call = qrow(
        cur,
        "SELECT payload->>'name', payload->'args' FROM events "
        "WHERE session_id = %s::uuid AND type = 'tool/call'",
        (root,))
    scene.driver.connection().commit()
    args = as_obj(call[1]) if call else None
    check(
        "scene_archive_waiting",
        scene.words[3][1] == "waiting" and status == "done" and done_n == 1
        and root_status not in TERMINAL and child_status not in TERMINAL
        and plans == 1 and pointer_n == 1 and reads == 1 and fold_n == 1
        and children == 1 and override_n == 1 and cancel_n == 0 and responded_n == 0
        and call is not None and call[0] == "spawn_subsession" and set(args) == {"task"},
        (status, done_n, root_status, child_status, call))


def scene_layers_unjoined(server, scene):
    llm_calls = [item for item in scene.probe.calls if item["channel"] == "llm"]
    texts_ok = True
    detail = []
    for item in llm_calls:
        layers = item["layers"]
        if isinstance(layers, str) or not isinstance(layers, list) or len(layers) != 4:
            texts_ok = False
            detail.append(layers)
            continue
        names = [name for name, _text in layers]
        texts = [text for _name, text in layers]
        joined = "".join(texts)
        fresh = [scene.layers[name] for name in LAYER_ORDER]
        if (
            names != list(LAYER_ORDER)
            or texts != fresh
            or any(not isinstance(text, str) or text.strip() == "" for text in texts)
            or any(joined == text for text in texts)
            or joined == layers
        ):
            texts_ok = False
            detail.append(names)
    cur = scene.driver.connection().cursor()
    before = q1(cur, "SELECT count(*) FROM effects")
    scene.driver.connection().commit()
    empty = LoopDriver(lambda: psycopg2.connect(server.get_uri(DB)), layers={})
    raised = False
    try:
        try:
            empty.four_layers()
        except KeyError:
            raised = True
    finally:
        empty.close()
    after = q1(cur, "SELECT count(*) FROM effects")
    scene.driver.connection().commit()
    plan_seen = any(item["kind"] == "plan" for item in llm_calls)
    serve_seen = any(item["kind"] != "plan" for item in llm_calls)
    check(
        "scene_layers_unjoined",
        len(llm_calls) >= 2 and plan_seen and serve_seen and texts_ok
        and raised and before == after,
        (len(llm_calls), texts_ok, raised, before, after, detail))


def scene_advance_cap(scene, constant_ok):
    driver = scene.driver
    cur = driver.connection().cursor()
    root = scene.root
    before_events = q1(cur, "SELECT count(*) FROM events")
    before_human = q1(cur, "SELECT count(*) FROM effects WHERE kind = 'human'")
    before_done = q1(
        cur,
        "SELECT status FROM v13_plan_todo_fold(%s::uuid) WHERE todo_id = %s::uuid",
        (root, scene.todo_id))
    driver.connection().commit()
    raised = False
    message = ""
    try:
        driver.advance(root)
    except AssertionError as exc:
        message = str(exc)
        raised = "scene_advance_cap" in message
    after_events = q1(cur, "SELECT count(*) FROM events")
    after_human = q1(cur, "SELECT count(*) FROM effects WHERE kind = 'human'")
    after_done = q1(
        cur,
        "SELECT status FROM v13_plan_todo_fold(%s::uuid) WHERE todo_id = %s::uuid",
        (root, scene.todo_id))
    driver.connection().commit()
    check(
        "scene_advance_cap",
        constant_ok and GOAL_WORKFLOW_MAX_ADVANCE == 4 and raised
        and len(scene.words) == 4
        and before_events == after_events
        and before_human == after_human
        and before_done == after_done == "done",
        (message, before_events, after_events, before_human, after_human, before_done, after_done))


def main() -> int:
    server = get_server()
    conn = None
    scene = None
    try:
        r0_source_scope()
        actl_driver_untouched()
        file_hits, wake_calls, constant_ok = static_source()
        if setup_db() != 0:
            return 1
        conn = psycopg2.connect(server.get_uri(DB))
        conn.autocommit = False
        cur = conn.cursor()
        cur.execute("SET track_functions = 'all'")
        conn.commit()
        spawn_before = spawn_row(cur)
        check("spawn enabled before install", spawn_before is not None and spawn_before[5] is True)
        quota_seed, should_seed, spawn_before = install_compare(cur, server, spawn_before)
        scene_no_wake_no_claim(cur, file_hits, wake_calls)
        scene_suggestion_shape_zero_write(cur)
        scene_macro_reject_zero_write(cur)
        scene_human_pending_holds(cur)
        scene = run_scene(server, quota_seed, should_seed)
        scene_solved_no_human(scene)
        scene_archive_waiting(scene)
        scene_layers_unjoined(server, scene)
        scene_advance_cap(scene, constant_ok)
        after = spawn_row(cur)
        check("spawn enabled after behavior", after == spawn_before and after[5] is True, after)
        conn.commit()
    finally:
        try:
            if scene is not None and scene.driver is not None:
                scene.driver.close()
            if conn is not None:
                conn.close()
        finally:
            if setup_mod.CREATED:
                try:
                    run_psql(server, "postgres", 'DROP DATABASE "%s" WITH (FORCE);' % DB)
                    setup_mod.CREATED = False
                    print("[dropped]", DB)
                except Exception as exc:
                    print("[cleanup-fail]", exc)
                    raise SystemExit(1)
    print("[ok] %s checks" % N)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        print("[FAIL]", exc)
        raise SystemExit(1)
