"""夹具绑定的现存 `p_sid`、`external_executor` version 1、STABLE INVOKER 函数 `v13_external_exec_classify`：允许动词返回七键且 `executed=false`；`source_principal`、未知键、列表外动词、空会话或不存在会话返回两键 `unsupported` 且零写。真正执行仍是既有 parse → advance 的 sql 臂，快照仍是 `controller` / 1。这不是可信产品入口，不是注册身份，不是 task lease。

Run: UV_FROZEN=1 uv run python v13/external_exec/test_external_exec.py
"""
from __future__ import annotations

import ast
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
from v13.external_exec.setup_db import DB, main as setup_db
import v13.external_exec.setup_db as setup_mod
from v13.load import run_psql
from v13.loop.test_loop import mock_from_needed, set_mock
from v13.plan_arm.test_plan_arm import r0_source_scope

N = 0
SQL_PATH = ROOT / "v13_external_exec.sql"
SQL = SQL_PATH.read_text()
CLAIM = (
    "夹具绑定的现存 `p_sid`、`external_executor` version 1、STABLE INVOKER 函数 "
    "`v13_external_exec_classify`：允许动词返回七键且 `executed=false`；"
    "`source_principal`、未知键、列表外动词、空会话或不存在会话返回两键 "
    "`unsupported` 且零写。真正执行仍是既有 parse → advance 的 sql 臂，快照仍是 "
    "`controller` / 1。这不是可信产品入口，不是注册身份，不是 task lease。"
)
SESSION_SPEC = {"route_policy_name": "controller", "version": 1}
SQL_NULL = object()
JSON_NULL = object()
SHAPE = {"ok": False, "reason": "shape"}
UNSUPPORTED = {"ok": False, "reason": "unsupported"}
CLASSIFY_SIG = "public.v13_external_exec_classify(uuid,jsonb)"
CLASSIFY_IDENT = "public.v13_external_exec_classify(p_sid uuid, p_spec jsonb)"
POLICY_VALUE = {
    "schema_version": 1,
    "verbs": [
        "agentctl_observe",
        "agentctl_steer",
        "agentctl_answer",
        "agentctl_cancel",
    ],
}
VERBS = (
    "agentctl_observe",
    "agentctl_steer",
    "agentctl_answer",
    "agentctl_cancel",
)
NO_ACTIVE = "v13: no active policy row for external_executor (seed lost?)"
BAD_POLICY = "v13: external_executor policy"
IMMUTABLE = "v13: policy rows are immutable (append new version + flip active)"
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
BANNED_CALLS = {
    "v13_agentctl_observe",
    "v13_agentctl_steer",
    "v13_agentctl_answer",
    "v13_agentctl_cancel",
    "v13_wake_is_satisfied_v1",
    "v13_claim",
    "v13_claim_fair",
}


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


def as_obj(value):
    if isinstance(value, str):
        return json.loads(value)
    return value


def legal(verb):
    return {"schema_version": 1, "verb": verb}


def success_obj(verb, policy_version=1):
    return {
        "schema_version": 1,
        "ok": True,
        "classified": True,
        "executed": False,
        "verb": verb,
        "policy_name": "external_executor",
        "policy_version": policy_version,
    }


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


def function_text(tree, text, name):
    node = function_node(tree, name)
    return "\n".join(text.splitlines()[node.lineno - 1:node.end_lineno])


def open_controller(cur):
    cur.execute(
        "SELECT v13_open_session(%s::jsonb)",
        (json.dumps(SESSION_SPEC),))
    return str(cur.fetchone()[0])


def classify(cur, sid, spec):
    if sid is SQL_NULL:
        sid_sql, sid_params = "NULL::uuid", ()
    else:
        sid_sql, sid_params = "%s::uuid", (sid,)
    if spec is SQL_NULL:
        spec_sql, spec_params = "NULL::jsonb", ()
    elif spec is JSON_NULL:
        spec_sql, spec_params = "'null'::jsonb", ()
    else:
        spec_sql, spec_params = "%s::jsonb", (json.dumps(spec),)
    cur.execute(
        "SELECT public.v13_external_exec_classify(%s, %s)" % (sid_sql, spec_sql),
        sid_params + spec_params)
    return as_obj(cur.fetchone()[0])


def relation_snapshot(cur):
    cur.execute(
        "SELECT row_to_json(s)::text FROM sessions s ORDER BY session_id")
    sessions = cur.fetchall()
    cur.execute(
        "SELECT row_to_json(e)::text FROM events e ORDER BY session_id, seq")
    events = cur.fetchall()
    cur.execute(
        "SELECT row_to_json(x)::text FROM effects x ORDER BY effect_id")
    effects = cur.fetchall()
    cur.execute(
        "SELECT row_to_json(p)::text FROM v13_policies p ORDER BY name, version")
    policies = cur.fetchall()
    return sessions, events, effects, policies


def measured_classify(cur, sid, spec):
    before = relation_snapshot(cur)
    got = classify(cur, sid, spec)
    after = relation_snapshot(cur)
    return got, before == after


def expect_shape(cur, label, sid, spec):
    got, same = measured_classify(cur, sid, spec)
    check(label, got == SHAPE and same and "policy_version" not in got, (got, same))


def expect_unsupported(cur, label, sid, spec):
    got, same = measured_classify(cur, sid, spec)
    check(
        label,
        got == UNSUPPORTED and same and "policy_version" not in got,
        (got, same))


def expect_success(cur, label, sid, verb, policy_version=1):
    got, same = measured_classify(cur, sid, legal(verb))
    want = success_obj(verb, policy_version)
    check(
        label,
        got == want and got.get("executed") is False and same and len(got) == 7,
        (got, same))
    return got


def policy_v1_only(cur):
    cur.execute(
        "SELECT version, active, value FROM v13_policies "
        "WHERE name = 'external_executor' ORDER BY version")
    rows = cur.fetchall()
    n2 = q1(
        cur,
        "SELECT count(*) FROM v13_policies "
        "WHERE name = 'external_executor' AND version = 2")
    return (
        len(rows) == 1
        and rows[0][0] == 1
        and rows[0][1] is True
        and as_obj(rows[0][2]) == POLICY_VALUE
        and n2 == 0
    )


def assert_restored(cur, before, label):
    after = relation_snapshot(cur)
    check(label, after == before and policy_v1_only(cur), (policy_v1_only(cur),))


def next_policy_version(cur):
    return q1(
        cur,
        "SELECT COALESCE(max(version), 0) + 1 FROM v13_policies "
        "WHERE name = 'external_executor'")


def flip_active(cur, version, value):
    cur.execute(
        "INSERT INTO v13_policies (name, version, value, active) "
        "VALUES ('external_executor', %s, %s::jsonb, false)",
        (version, json.dumps(value)))
    cur.execute(
        "UPDATE v13_policies SET active = false "
        "WHERE name = 'external_executor' AND version = 1")
    cur.execute(
        "UPDATE v13_policies SET active = true "
        "WHERE name = 'external_executor' AND version = %s",
        (version,))


def measured_raise(cur, sid, spec, needle, label):
    spec_lit = "'" + json.dumps(spec).replace("'", "''") + "'::jsonb"
    sid_lit = "'" + str(sid) + "'::uuid"
    cur.execute(
        """
        DO $trap$
        DECLARE
          v_msg text := '';
          v_auth oid := 'public.v13_control_authorized(uuid,uuid)'::regprocedure;
          v_append oid := 'public.v13_append_event(uuid,uuid,text,jsonb,uuid)'::regprocedure;
          v_b bigint;
          v_a bigint;
          v_append_b bigint;
          v_append_d bigint;
        BEGIN
          SELECT coalesce(sum(calls), 0) INTO v_b
            FROM pg_stat_xact_user_functions WHERE funcid = v_auth;
          PERFORM public.v13_control_authorized(NULL::uuid, NULL::uuid);
          SELECT coalesce(sum(calls), 0) INTO v_a
            FROM pg_stat_xact_user_functions WHERE funcid = v_auth;
          IF v_a - v_b < 1 THEN
            RAISE EXCEPTION 'environment block: track_functions';
          END IF;
          SELECT coalesce(sum(calls), 0) INTO v_append_b
            FROM pg_stat_xact_user_functions WHERE funcid = v_append;
          BEGIN
            PERFORM public.v13_external_exec_classify(%s, %s);
            v_msg := 'no-error';
          EXCEPTION WHEN OTHERS THEN
            GET STACKED DIAGNOSTICS v_msg = MESSAGE_TEXT;
          END;
          SELECT coalesce(sum(calls), 0) - v_append_b INTO v_append_d
            FROM pg_stat_xact_user_functions WHERE funcid = v_append;
          CREATE TEMP TABLE IF NOT EXISTS ext_trap (
            message text, append_d bigint
          ) ON COMMIT DROP;
          DELETE FROM ext_trap;
          INSERT INTO ext_trap VALUES (v_msg, v_append_d);
        END
        $trap$
        """ % (sid_lit, spec_lit))
    cur.execute("SELECT message, append_d FROM ext_trap")
    msg, append_d = cur.fetchone()
    check(label, msg == needle, msg)
    check(label + " append", append_d == 0, append_d)


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


def policy_rows(cur):
    cur.execute(
        "SELECT name, version, active, value FROM v13_policies ORDER BY 1, 2")
    return [(name, version, active, as_obj(value))
            for name, version, active, value in cur.fetchall()]


def route_policy_rows(cur):
    cur.execute(
        "SELECT policy_name, policy_version, state "
        "FROM v13_route_policies ORDER BY 1, 2")
    return cur.fetchall()


def surface_row(cur):
    return qrow(
        cur,
        "SELECT name, version, active, value::text FROM v13_policies "
        "WHERE name = 'controller_surface' AND version = 1")


def spawn_row(cur):
    return qrow(
        cur,
        "SELECT name, description, kind, handler, param_spec::text, enabled "
        "FROM tools WHERE name = 'spawn_subsession'")


def token_hits(text, extra=()):
    norm = squash(text)
    found = [token for token in BANNED_TOKENS if token in norm]
    for token in extra:
        if token in norm:
            found.append(token)
    return found


def static_source():
    text = (ROOT / "test_external_exec.py").read_text()
    first = (__doc__ or "").split("\n\n", 1)[0]
    check("claim sentence", first == CLAIM, first)
    tree = ast.parse(text)
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and call_name(node) in BANNED_CALLS:
            calls.append(call_name(node))
    check("no banned calls", calls == [], calls)
    sql_arm = function_text(tree, text, "ext_steer_sql_arm")
    uncalled = function_text(tree, text, "ext_steer_classify_uncalled")
    check(
        "sql arm markers",
        "v13_parse" in sql_arm and "v13_advance" in sql_arm
        and "v13_external_exec_classify" not in sql_arm,
        "")
    check(
        "uncalled markers",
        "v13_external_exec_classify" in uncalled
        and "v13_parse" not in uncalled and "v13_advance" not in uncalled,
        "")
    leaked = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name in ("ext_steer_sql_arm", "static_source", "source_prosrc"):
            continue
        src = function_text(tree, text, node.name)
        if "v13_parse" in src or "v13_advance" in src:
            leaked.append(node.name)
    check("classify fixtures unmarked", leaked == [], leaked)
    counts = {name: SQL.count(name) for name in VERBS}
    check("file verb counts", counts == {name: 1 for name in VERBS}, counts)
    hits = token_hits(SQL, extra=("security definer", "insert into tools", "v13_agentctl_"))
    check("sql file tokens", hits == [], hits)


def install_compare(cur, server, spawn_before):
    before_fns = fn_rows(cur)
    before_tools = tool_rows(cur)
    before_rels = rel_rows(cur)
    before_meta = qrow(
        cur, "SELECT revision, candidate_generation_revision FROM v13_tools_meta")
    before_events = q1(cur, "SELECT count(*) FROM events")
    before_effects = q1(cur, "SELECT count(*) FROM effects")
    before_policies = policy_rows(cur)
    before_routes = route_policy_rows(cur)
    before_surface = surface_row(cur)
    cur.connection.commit()
    run_psql(server, DB, SQL)
    after_fns = fn_rows(cur)
    added = set(after_fns) - set(before_fns)
    check("one new function", added == {CLASSIFY_IDENT}, added)
    for sig, row in before_fns.items():
        check("function unchanged " + sig, after_fns[sig] == row)
    new = after_fns[CLASSIFY_IDENT]
    config = (new[5] or "").replace(" ", "")
    owner = q1(cur, "SELECT current_user")
    check(
        "classify attrs",
        new[1] == owner
        and new[2] is False
        and new[4] == "s"
        and new[6] is False
        and "search_path=pg_catalog,public" in config,
        new[1:])
    check("tools unchanged", tool_rows(cur) == before_tools)
    meta = qrow(cur, "SELECT revision, candidate_generation_revision FROM v13_tools_meta")
    check("tools meta unchanged", meta == before_meta, (before_meta, meta))
    check("relations unchanged", rel_rows(cur) == before_rels)
    check("install events unchanged", q1(cur, "SELECT count(*) FROM events") == before_events)
    check("install effects unchanged", q1(cur, "SELECT count(*) FROM effects") == before_effects)
    after_policies = policy_rows(cur)
    extra = [row for row in after_policies if row not in before_policies]
    check(
        "policy rows +1",
        extra == [("external_executor", 1, True, POLICY_VALUE)]
        and len(after_policies) == len(before_policies) + 1,
        extra)
    check("route policies unchanged", route_policy_rows(cur) == before_routes)
    state = q1(
        cur,
        "SELECT state FROM v13_route_policies "
        "WHERE policy_name = 'controller' AND policy_version = 1")
    check("controller frozen", state == "frozen", state)
    check("controller_surface unchanged", surface_row(cur) == before_surface)
    check(
        "classify named null",
        q1(cur, "SELECT public.v13_named_sql_writer('v13_external_exec_classify')") is None)
    check(
        "classify writer false",
        q1(cur, "SELECT public.v13_spawn_writer_ok('v13_external_exec_classify')") is False)
    check(
        "route execute",
        q1(cur, "SELECT has_function_privilege('v13_route', %s, 'EXECUTE')", (CLASSIFY_SIG,))
        is True)
    for role in ("public", "v13_recall", "v13_worker", "v13_resolve", "v13_spawn_owner"):
        check(
            role + " no execute",
            q1(cur, "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, CLASSIFY_SIG,))
            is False)
    sid = open_controller(cur)
    cur.execute("SET ROLE v13_route")
    try:
        got = classify(cur, sid, legal("agentctl_steer"))
    finally:
        cur.execute("RESET ROLE")
    want = success_obj("agentctl_steer", 1)
    check(
        "route classify",
        got == want and got.get("executed") is False and got.get("policy_version") == 1,
        got)
    cur.execute("SAVEPOINT ext_recall")
    cur.execute("SET ROLE v13_recall")
    code = None
    try:
        try:
            classify(cur, sid, legal("agentctl_steer"))
        except psycopg2.Error as exc:
            code = exc.pgcode
            cur.execute("ROLLBACK TO SAVEPOINT ext_recall")
        else:
            cur.execute("ROLLBACK TO SAVEPOINT ext_recall")
    finally:
        cur.execute("RESET ROLE")
    check("recall 42501", code == "42501", code)
    after_spawn = spawn_row(cur)
    check("spawn enabled after install", after_spawn is not None and after_spawn[5] is True)
    check("spawn row after install", after_spawn == spawn_before, after_spawn)
    cur.connection.commit()
    return sid


def source_prosrc(cur):
    body = q1(cur, "SELECT pg_get_functiondef(%s::regprocedure)", (CLASSIFY_SIG,))
    prosrc = q1(
        cur,
        "SELECT prosrc FROM pg_proc WHERE oid = %s::regprocedure",
        (CLASSIFY_SIG,))
    norm = squash(prosrc or "")
    hits = token_hits(prosrc or "")
    for token in (
        "security definer",
        "v13_parse",
        "v13_advance",
        "v13_route",
        "v13_append_event",
        "v13_control_authorized",
        "v13_policy(",
        "btrim",
        "route_policy",
        "v13_enqueue_effect",
    ):
        if token in norm:
            hits.append(token)
    for token in ("execute", "insert", "update", "delete"):
        if re.search(r"(?<![a-z0-9_])" + token + r"(?![a-z0-9_])", norm):
            hits.append(token)
    names = [name for name in VERBS if name in squash(prosrc or "")]
    def_names = [name for name in VERBS if name in squash(body or "")]
    check(
        "ext_source_scan",
        hits == [] and names == [] and def_names == [],
        (hits, names, def_names))


def classify_active(cur, sid, missing):
    expect_shape(cur, "ext_shape_null_spec", sid, SQL_NULL)
    expect_shape(cur, "ext_shape_json_null", sid, JSON_NULL)
    expect_shape(cur, "ext_shape_array", sid, [])
    expect_shape(cur, "ext_shape_scalar", sid, "scalar")
    expect_shape(cur, "ext_shape_number", sid, 1)
    expect_shape(cur, "ext_shape_bool", sid, True)
    expect_shape(cur, "ext_shape_empty", sid, {})
    expect_shape(cur, "ext_shape_only_verb", missing, {"verb": "agentctl_steer"})
    expect_shape(cur, "ext_shape_only_version", sid, {"schema_version": 1})
    expect_shape(
        cur, "ext_shape_version_string", sid,
        {"schema_version": "1", "verb": "agentctl_steer"})
    expect_shape(
        cur, "ext_shape_version_zero", sid,
        {"schema_version": 0, "verb": "agentctl_steer"})
    expect_shape(
        cur, "ext_shape_version_two", sid,
        {"schema_version": 2, "verb": "agentctl_steer"})
    expect_shape(
        cur, "ext_shape_version_fraction", sid,
        {"schema_version": 1.5, "verb": "agentctl_steer"})
    expect_shape(
        cur, "ext_shape_verb_number", sid,
        {"schema_version": 1, "verb": 1})
    expect_shape(
        cur, "ext_shape_verb_null", sid,
        {"schema_version": 1, "verb": None})
    expect_shape(
        cur, "ext_shape_verb_object", sid,
        {"schema_version": 1, "verb": {}})
    expect_unsupported(
        cur, "ext_unsupported_source_principal", sid,
        {"schema_version": 1, "verb": "agentctl_steer", "source_principal": "controller"})
    expect_unsupported(
        cur, "ext_unsupported_principal_bad_version", sid,
        {"schema_version": "1", "verb": "agentctl_steer", "source_principal": "controller"})
    expect_unsupported(
        cur, "ext_unsupported_unknown_note", sid,
        {"schema_version": 1, "verb": "agentctl_steer", "note": "x"})
    expect_unsupported(
        cur, "ext_unsupported_note_bad_version", sid,
        {"schema_version": 2, "verb": "agentctl_steer", "note": "x"})
    expect_unsupported(
        cur, "ext_unsupported_unknown_policy_version", sid,
        {"schema_version": 1, "verb": "agentctl_steer", "policy_version": 1})
    expect_unsupported(
        cur, "ext_unsupported_unknown_executed", sid,
        {"schema_version": 1, "verb": "agentctl_steer", "executed": False})
    expect_unsupported(cur, "ext_unsupported_null_sid", SQL_NULL, legal("agentctl_steer"))
    expect_unsupported(cur, "ext_unsupported_missing_session", missing, legal("agentctl_steer"))
    expect_unsupported(
        cur, "ext_unsupported_unknown_verb", sid,
        {"schema_version": 1, "verb": "not_a_verb"})
    expect_unsupported(
        cur, "ext_unsupported_prefixed_verb", sid,
        {"schema_version": 1, "verb": "v13_agentctl_steer"})
    expect_unsupported(
        cur, "ext_unsupported_padded_verb", sid,
        {"schema_version": 1, "verb": " agentctl_steer"})
    expect_unsupported(
        cur, "ext_unsupported_empty_verb", sid,
        {"schema_version": 1, "verb": ""})
    expect_success(cur, "ext_classify_observe", sid, "agentctl_observe")
    steer = expect_success(cur, "ext_classify_steer", sid, "agentctl_steer")
    expect_success(cur, "ext_classify_answer", sid, "agentctl_answer")
    expect_success(cur, "ext_classify_cancel", sid, "agentctl_cancel")
    got, same = measured_classify(cur, sid, legal("agentctl_steer"))
    check("ext_repeat_steer", got == steer and same, got)


def classify_inactive(cur, sid, missing):
    before = relation_snapshot(cur)
    cur.execute("SAVEPOINT ext_inactive")
    try:
        cur.execute(
            "UPDATE v13_policies SET active = false "
            "WHERE name = 'external_executor' AND version = 1")
        expect_shape(cur, "ext_inactive_shape_null", sid, SQL_NULL)
        expect_unsupported(
            cur, "ext_inactive_unsupported_principal", sid,
            {"schema_version": 1, "verb": "agentctl_steer", "source_principal": "controller"})
        expect_unsupported(
            cur, "ext_inactive_unsupported_note", sid,
            {"schema_version": 1, "verb": "agentctl_steer", "note": "x"})
        expect_shape(
            cur, "ext_inactive_shape_version", sid,
            {"schema_version": "1", "verb": "agentctl_steer"})
        expect_unsupported(
            cur, "ext_inactive_unsupported_null_sid", SQL_NULL, legal("agentctl_steer"))
        expect_unsupported(
            cur, "ext_inactive_unsupported_missing_sid", missing, legal("agentctl_steer"))
        measured_raise(cur, sid, legal("agentctl_steer"), NO_ACTIVE, "ext_raise_no_active_row")
    finally:
        cur.execute("ROLLBACK TO SAVEPOINT ext_inactive")
    assert_restored(cur, before, "ext_inactive restored")


def classify_immutable(cur):
    before = relation_snapshot(cur)
    cur.execute("SAVEPOINT ext_immut")
    try:
        msg = None
        try:
            cur.execute(
                "UPDATE v13_policies SET value = %s::jsonb "
                "WHERE name = 'external_executor' AND version = 1",
                (json.dumps({"schema_version": 1, "verbs": []}),))
        except psycopg2.Error as exc:
            msg = exc.diag.message_primary
        check("ext_policy_value_immutable", msg == IMMUTABLE, msg)
    finally:
        cur.execute("ROLLBACK TO SAVEPOINT ext_immut")
    assert_restored(cur, before, "ext_immut restored")


def raise_bad_policy(cur, sid, label, value):
    before = relation_snapshot(cur)
    cur.execute("SAVEPOINT " + label)
    try:
        version = next_policy_version(cur)
        flip_active(cur, version, value)
        measured_raise(cur, sid, legal("agentctl_steer"), BAD_POLICY, label)
    finally:
        cur.execute("ROLLBACK TO SAVEPOINT " + label)
    assert_restored(cur, before, label + " restored")


def classify_bad_values(cur, sid):
    verbs = list(VERBS)
    extra = dict(POLICY_VALUE)
    extra = {
        "schema_version": 1,
        "verbs": verbs,
        "note": "x",
    }
    raise_bad_policy(cur, sid, "ext_raise_policy_extra_key", extra)
    raise_bad_policy(
        cur, sid, "ext_raise_policy_version_number",
        {"schema_version": 2, "verbs": verbs})
    raise_bad_policy(
        cur, sid, "ext_raise_policy_version_string",
        {"schema_version": "1", "verbs": verbs})
    raise_bad_policy(
        cur, sid, "ext_raise_policy_verbs_dup",
        {"schema_version": 1, "verbs": ["agentctl_steer", "agentctl_steer"]})
    raise_bad_policy(
        cur, sid, "ext_raise_policy_verbs_element",
        {"schema_version": 1, "verbs": ["agentctl_observe", 1]})
    raise_bad_policy(
        cur, sid, "ext_raise_policy_verbs_scalar",
        {"schema_version": 1, "verbs": "agentctl_steer"})


def classify_empty_verbs(cur, sid):
    before = relation_snapshot(cur)
    cur.execute("SAVEPOINT ext_empty")
    try:
        flip_active(cur, next_policy_version(cur), {"schema_version": 1, "verbs": []})
        expect_unsupported(
            cur, "ext_unsupported_empty_verbs_array", sid, legal("agentctl_steer"))
    finally:
        cur.execute("ROLLBACK TO SAVEPOINT ext_empty")
    assert_restored(cur, before, "ext_empty restored")


def classify_version_from_row(cur, sid):
    before = relation_snapshot(cur)
    cur.execute("SAVEPOINT ext_ver")
    try:
        flip_active(cur, next_policy_version(cur), POLICY_VALUE)
        expect_success(cur, "ext_policy_version_from_row", sid, "agentctl_steer", 2)
    finally:
        cur.execute("ROLLBACK TO SAVEPOINT ext_ver")
    assert_restored(cur, before, "ext_ver restored")
    got, same = measured_classify(cur, sid, legal("agentctl_steer"))
    check(
        "ext_policy_version_from_row after",
        got == success_obj("agentctl_steer", 1) and got.get("executed") is False and same,
        got)


def classify_membership(cur, sid):
    before = relation_snapshot(cur)
    cur.execute("SAVEPOINT ext_mem")
    try:
        flip_active(
            cur, next_policy_version(cur),
            {"schema_version": 1, "verbs": ["agentctl_observe"]})
        expect_success(cur, "ext_membership_uses_row", sid, "agentctl_observe", 2)
        expect_unsupported(cur, "ext_membership_uses_row steer", sid, legal("agentctl_steer"))
    finally:
        cur.execute("ROLLBACK TO SAVEPOINT ext_mem")
    assert_restored(cur, before, "ext_mem restored")
    got, same = measured_classify(cur, sid, legal("agentctl_steer"))
    check(
        "ext_membership_uses_row restored",
        got == success_obj("agentctl_steer", 1) and got.get("executed") is False and same,
        got)


def auth_probe(cur):
    cur.execute("SAVEPOINT ext_probe")
    try:
        before = q1(
            cur,
            "SELECT coalesce(sum(calls), 0) FROM pg_stat_xact_user_functions "
            "WHERE funcid = 'public.v13_control_authorized(uuid,uuid)'::regprocedure")
        cur.execute("SELECT public.v13_control_authorized(NULL::uuid, NULL::uuid)")
        cur.fetchone()
        after = q1(
            cur,
            "SELECT coalesce(sum(calls), 0) FROM pg_stat_xact_user_functions "
            "WHERE funcid = 'public.v13_control_authorized(uuid,uuid)'::regprocedure")
    except psycopg2.Error as exc:
        cur.execute("ROLLBACK TO SAVEPOINT ext_probe")
        raise AssertionError("environment block: track_functions: %s" % exc)
    cur.execute("ROLLBACK TO SAVEPOINT ext_probe")
    if after - before < 1:
        raise AssertionError("environment block: track_functions")


def choice(value, confidence=0.9):
    return {
        "type": "choice",
        "choice": value,
        "probabilities": {value: confidence},
        "confidence": confidence,
    }


def ext_steer_sql_arm(cur):
    cur.execute("SELECT set_config('typesafe.provider', 'mock', false)")
    cur.execute("SELECT set_config('typesafe.model', 'jev-mock', false)")
    cur.execute(
        "SELECT param_spec, kind, enabled FROM tools WHERE name = 'agentctl_steer'")
    spec, kind, enabled = cur.fetchone()
    keys = set(as_obj(spec))
    if keys != {"target", "text"} or kind != "sql" or enabled is not True:
        raise AssertionError(
            "agentctl_steer live row is not target+text sql enabled: %s"
            % ((keys, kind, enabled),))
    cur.execute(
        "SELECT v13_open_session(%s::jsonb)",
        (json.dumps(SESSION_SPEC),))
    root = str(cur.fetchone()[0])
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (root, str(uuid.uuid4()), json.dumps({"text": "route agentctl_steer"})))
    cur.fetchone()
    cur.execute(
        "SELECT v13_spawn_subsession(%s, %s::jsonb)",
        (root, json.dumps({
            "schema_version": 1,
            "children": [{
                "tool_call_id": "tc-" + uuid.uuid4().hex[:8],
                "task": "routed child",
            }],
        })))
    spawned = as_obj(cur.fetchone()[0])
    child = str(spawned["children"][0]["session_id"])
    ready = q1(
        cur,
        "SELECT count(*) FROM effects "
        "WHERE session_id = %s AND status IN ('ready', 'claimed')",
        (root,))
    if ready != 0:
        raise AssertionError("root ready|claimed effect count is %s" % (ready,))
    cur.execute(
        "SELECT v13_submit_override(%s, %s::jsonb)",
        (root, json.dumps({
            "intent": "direct",
            "reason": "",
            "schema_version": 1,
            "source_principal": "operator",
        })))
    cur.fetchone()
    cur.execute(
        "UPDATE tools SET enabled = false "
        "WHERE enabled AND kind IN ('sql','tool') "
        "AND NOT (name = ANY(ARRAY['spawn_subsession','agentctl_steer']))")
    overrides = {
        "intent": choice("sql_answer"),
        "tool": choice("agentctl_steer"),
        "gate_action": {"type": "noul", "noul": 0.9},
        "gate_off_topic": {"type": "noul", "noul": 0.1},
        "risk": {"type": "score", "score": 0.5, "confidence": 0.9},
        "stated::agentctl_steer::target": {"type": "noul", "noul": 0.9},
        "stated::agentctl_steer::text": {"type": "noul", "noul": 0.9},
        "param::agentctl_steer::target": choice(child),
        "param::agentctl_steer::text": choice("steer-text"),
    }
    mock = mock_from_needed(cur, root, **overrides)
    set_mock(cur, mock)
    cur.execute("SELECT v13_parse(%s)", (root,))
    parsed = as_obj(cur.fetchone()[0])
    snap = parsed.get("snap") or {}
    check(
        "ext_steer_parse_controller",
        parsed.get("remaining") == 0
        and parsed.get("failed") is False
        and parsed.get("abandon") is False
        and snap.get("route_policy_name") == "controller"
        and str(snap.get("route_policy_version")) == "1",
        parsed)
    cur.execute(
        "UPDATE sessions SET context_active_revision = v13_context_required(session_id) "
        "WHERE session_id = %s",
        (root,))
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (root, json.dumps(parsed)))
    word = cur.fetchone()[0]
    cur.execute(
        """
        SELECT payload FROM events
         WHERE session_id = %s AND type = 'turn/route'
         ORDER BY seq DESC LIMIT 1
        """,
        (root,))
    row = cur.fetchone()
    route = as_obj(row[0]) if row else None
    if word != "progressed" or not route or route.get("action") != "sql" or route.get("tool") != "agentctl_steer":
        raise AssertionError(
            "sql arm mismatch word=%s payload=%s" % (word, route))
    check(
        "ext_steer_sql_arm",
        word == "progressed"
        and route.get("action") == "sql"
        and route.get("tool") == "agentctl_steer",
        (word, route))


def ext_steer_classify_uncalled(cur):
    auth_probe(cur)
    cur.execute(
        "SELECT coalesce(sum(calls), 0) FROM pg_stat_xact_user_functions "
        "WHERE funcid = 'public.v13_external_exec_classify(uuid,jsonb)'::regprocedure")
    before = cur.fetchone()[0]
    ext_steer_sql_arm(cur)
    cur.execute(
        "SELECT coalesce(sum(calls), 0) FROM pg_stat_xact_user_functions "
        "WHERE funcid = 'public.v13_external_exec_classify(uuid,jsonb)'::regprocedure")
    after = cur.fetchone()[0]
    check("ext_steer_classify_uncalled", after - before == 0, (before, after))


def main() -> int:
    server = get_server()
    conn = None
    try:
        r0_source_scope()
        static_source()
        if setup_db() != 0:
            return 1
        conn = psycopg2.connect(server.get_uri(DB))
        conn.autocommit = False
        cur = conn.cursor()
        cur.execute("SET track_functions = 'all'")
        conn.commit()
        spawn_before = spawn_row(cur)
        check("spawn enabled before install", spawn_before is not None and spawn_before[5] is True)
        sid = install_compare(cur, server, spawn_before)
        source_prosrc(cur)
        missing = str(uuid.uuid4())
        present = q1(cur, "SELECT 1 FROM sessions WHERE session_id = %s::uuid", (missing,))
        check("missing sid absent", present is None, present)
        classify_active(cur, sid, missing)
        classify_inactive(cur, sid, missing)
        classify_immutable(cur)
        classify_bad_values(cur, sid)
        classify_empty_verbs(cur, sid)
        classify_version_from_row(cur, sid)
        classify_membership(cur, sid)
        check("ext_active_v1_before_exec", policy_v1_only(cur), "")
        conn.commit()
        cur.execute("SET track_functions = 'all'")
        ext_steer_classify_uncalled(cur)
        conn.commit()
    finally:
        try:
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
