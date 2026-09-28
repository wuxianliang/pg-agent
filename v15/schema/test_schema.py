"""Stage 1 gate: v15 schema, privileges, and stub contracts.

Run: uv run python v15/schema/test_schema.py  (exit 0 = pass)
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v15.schema.setup_db import DB, main as setup_db

TABLES = {
    "budget_pools": [
        "pool_id", "calls_limit", "cost_limit", "calls_used", "calls_reserved",
        "cost_used", "cost_reserved", "revision",
    ],
    "tool_catalog": [
        "tool_id", "name", "arg_schema", "handler", "description", "external",
        "handler_digest",
    ],
    "config_profiles": [
        "profile_id", "llm", "repl", "protocol", "baseline_hooks",
        "profile_digest", "created_at",
    ],
    "config_scopes": ["scope_id", "profile_id", "scope_digest"],
    "config_layers": [
        "layer_id", "scope_id", "ordinal", "kind", "llm", "repl", "protocol",
        "depth_map", "extra_hooks", "layer_digest",
    ],
    "governance_manifest": [
        "manifest_id", "max_iterations", "max_depth", "max_io_attempts",
        "max_statement_ms", "manifest_digest", "created_at",
    ],
    "invokes": [
        "invoke_id", "parent_invoke_id", "parent_iteration", "root_invoke_id",
        "depth", "status", "return_value", "error", "fatal", "recursion_available",
        "resolved_config", "config_digest", "config_scope_id", "local_layer_id",
        "pool_id", "manifest_digest", "scratch_schema", "fence", "lease_owner",
        "lease_until", "revision", "created_at", "updated_at",
    ],
    "iterations": [
        "invoke_id", "iteration", "status", "resume_stmt", "result_kind",
        "capture", "revision",
    ],
    "statements": [
        "invoke_id", "iteration", "stmt_index", "sql", "sql_digest", "kind",
        "bind_name", "arg_sql", "status", "child_invoke_id", "error_sqlstate",
        "error", "revision",
    ],
    "llm_requests": [
        "request_id", "invoke_id", "iteration", "status", "logical_digest",
        "revision",
    ],
    "llm_attempts": [
        "attempt_id", "request_id", "n", "status", "fence", "lease_owner",
        "lease_until", "pool_id", "reserved_calls", "reserved_cost",
        "call_started", "calls_charged", "request", "response", "prompt_tokens",
        "cost_usd", "revision",
    ],
    "llm_messages": [
        "invoke_id", "msg_seq", "message_id", "iteration", "role", "kind",
        "content",
    ],
    "repl_history": [
        "invoke_id", "iteration", "llm_response", "repl_output", "repl_exception",
    ],
    "bindings": [
        "invoke_id", "name", "kind", "value", "tool_id", "show_in_prompt",
        "provenance", "revision",
    ],
    "exec_context": [
        "backend_pid", "invoke_id", "iteration", "stmt_index", "scratch_schema",
        "revision",
    ],
    "invoke_events": [
        "invoke_id", "seq", "event_class", "span", "phase", "outcome", "payload",
        "fence", "created_at",
    ],
    "hook_defs": [
        "hook_def_id", "hook_key", "regprocedure", "owner_role",
        "baseline_required", "handler_digest", "search_path", "created_at",
    ],
    "invoke_hooks": [
        "invoke_id", "ordinal", "hook_def_id", "channel", "config", "state",
        "revision",
    ],
    "blackboard": ["invoke_id", "key", "value", "generation", "revision"],
    "hook_counters": ["invoke_id", "counter_key", "n", "revision"],
    "tool_grants": ["invoke_id", "tool_id"],
}

PKS = {
    "budget_pools": ["pool_id"],
    "tool_catalog": ["tool_id"],
    "config_profiles": ["profile_id"],
    "config_scopes": ["scope_id"],
    "config_layers": ["layer_id"],
    "governance_manifest": ["manifest_id"],
    "invokes": ["invoke_id"],
    "iterations": ["invoke_id", "iteration"],
    "statements": ["invoke_id", "iteration", "stmt_index"],
    "llm_requests": ["request_id"],
    "llm_attempts": ["attempt_id"],
    "llm_messages": ["invoke_id", "msg_seq"],
    "repl_history": ["invoke_id", "iteration"],
    "bindings": ["invoke_id", "name"],
    "exec_context": ["backend_pid"],
    "invoke_events": ["invoke_id", "seq"],
    "hook_defs": ["hook_def_id"],
    "invoke_hooks": ["invoke_id", "ordinal"],
    "blackboard": ["invoke_id", "key"],
    "hook_counters": ["invoke_id", "counter_key"],
    "tool_grants": ["invoke_id", "tool_id"],
}

NAMED_CHECKS = {
    "invokes": {
        "invokes_parent_pair", "invokes_lease", "invokes_completed",
        "invokes_failed", "invokes_aborted",
    },
    "iterations": {"iterations_done_result"},
    "statements": {
        "statements_bind_name", "statements_error_sqlstate", "statements_sql_digest",
    },
    "llm_attempts": {
        "llm_attempts_failed", "llm_attempts_unknown", "llm_attempts_settled",
        "llm_attempts_leased",
    },
    "bindings": {"bindings_tool_pair"},
    "invoke_events": {"invoke_events_shape"},
    "invoke_hooks": {"invoke_hooks_state"},
}

REVOKED = (
    "set_config", "pg_sleep", "pg_sleep_for", "pg_sleep_until",
    "pg_read_file", "pg_read_binary_file", "pg_ls_dir", "pg_stat_file",
    "pg_terminate_backend", "pg_cancel_backend", "lo_import", "lo_export",
)


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f": {detail}" if detail != "" else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def connect(server, user: str | None = None):
    uri = server.get_uri(DB)
    if user is None:
        return psycopg2.connect(uri)
    parsed = urlparse(uri)
    host = (parse_qs(parsed.query).get("host") or [None])[0]
    return psycopg2.connect(host=host, dbname=DB, user=user)


def fails(cur, sql: str, params=None, code: str | None = None, label: str = "") -> None:
    cur.execute("SAVEPOINT sp")
    try:
        cur.execute(sql, params)
    except psycopg2.Error as exc:
        ok = code is None or exc.pgcode == code
        check(label, ok, f"{exc.pgcode} {str(exc).splitlines()[0]}")
        cur.execute("ROLLBACK TO SAVEPOINT sp")
        return
    cur.execute("ROLLBACK TO SAVEPOINT sp")
    raise AssertionError(f"{label}: expected failure {code}")


def scratch_for(invoke_id: str) -> str:
    return "s_" + invoke_id.replace("-", "")


def insert_invoke(cur, invoke_id: str, **kw) -> None:
    parent = kw.get("parent")
    cur.execute(
        """
        INSERT INTO v15.invokes (
          invoke_id, parent_invoke_id, parent_iteration, root_invoke_id, depth,
          status, return_value, error, fatal, recursion_available,
          resolved_config, config_digest, manifest_digest, scratch_schema,
          fence, lease_owner, lease_until, created_at, updated_at
        ) VALUES (
          %s, %s, %s, %s, %s,
          %s, %s::jsonb, %s::jsonb, %s, true,
          '{}'::jsonb, 'cfg', %s, %s,
          1, %s, %s, clock_timestamp(), clock_timestamp()
        )
        """,
        (
            invoke_id,
            parent,
            kw.get("parent_iteration"),
            kw.get("root", invoke_id),
            kw.get("depth", 1),
            kw.get("status", "runnable"),
            kw.get("return_value"),
            kw.get("error"),
            kw.get("fatal", False),
            kw.get("manifest_digest", "md"),
            kw.get("scratch", scratch_for(invoke_id)),
            kw.get("lease_owner"),
            kw.get("lease_until"),
        ),
    )


def test_catalog(cur) -> None:
    cur.execute("SHOW server_version_num")
    check("PG 18.4", cur.fetchone()[0] == "180004")
    cur.execute(
        """
        SELECT nspname, pg_get_userbyid(nspowner)
        FROM pg_namespace
        WHERE nspname IN ('v15', 'jaz')
        ORDER BY 1
        """
    )
    check("schema owners", cur.fetchall() == [("jaz", "v15_owner"), ("v15", "v15_owner")])
    cur.execute(
        """
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'v15' AND c.relkind = 'r'
        ORDER BY 1
        """
    )
    names = [row[0] for row in cur.fetchall()]
    check("21 tables", names == sorted(TABLES), names)
    cur.execute(
        """
        SELECT count(*) FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'jaz' AND c.relkind = 'r'
        """
    )
    check("jaz has no tables", cur.fetchone()[0] == 0)
    for forbidden in ("programs", "turns", "spans", "phases"):
        check(f"no {forbidden} table", forbidden not in names)
    for table, columns in TABLES.items():
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'v15' AND table_name = %s
            ORDER BY ordinal_position
            """,
            (table,),
        )
        got = [row[0] for row in cur.fetchall()]
        check(f"columns {table}", got == columns, got)
        cur.execute(
            """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            WHERE tc.table_schema = 'v15'
              AND tc.table_name = %s
              AND tc.constraint_type = 'PRIMARY KEY'
            ORDER BY kcu.ordinal_position
            """,
            (table,),
        )
        check(f"pk {table}", [row[0] for row in cur.fetchall()] == PKS[table])
    for table, required in NAMED_CHECKS.items():
        cur.execute(
            """
            SELECT conname FROM pg_constraint
            WHERE conrelid = %s::regclass AND contype = 'c'
            """,
            (f"v15.{table}",),
        )
        present = {row[0] for row in cur.fetchall()}
        check(f"checks {table}", required <= present, present)
    cur.execute(
        """
        SELECT pg_get_constraintdef(oid)
        FROM pg_constraint
        WHERE conrelid = 'v15.bindings'::regclass AND contype = 'f'
        """
    )
    defs = [row[0] for row in cur.fetchall()]
    check(
        "bindings.tool_id fk",
        any("tool_id" in d and "tool_catalog" in d for d in defs),
        defs,
    )
    cur.execute(
        """
        SELECT indexdef FROM pg_indexes
        WHERE schemaname = 'v15' AND indexname = 'invokes_local_layer_id_key'
        """
    )
    idx = cur.fetchone()
    check("local_layer partial unique", idx is not None and "UNIQUE" in idx[0], idx)
    cur.execute(
        """
        SELECT pg_get_userbyid(relowner)
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'v15' AND c.relkind = 'r' AND relowner <> 'v15_owner'::regrole
        """
    )
    check("table owners", cur.fetchall() == [])


def test_roles(cur) -> None:
    cur.execute(
        """
        SELECT rolname, rolcanlogin, rolsuper
        FROM pg_roles
        WHERE starts_with(rolname, 'v15_')
        ORDER BY 1
        """
    )
    rows = cur.fetchall()
    by = {name: (login, superuser) for name, login, superuser in rows}
    check("bootstrap nologin", by.get("v15_bootstrap") == (False, False), by)
    check("owner nologin", by.get("v15_owner") == (False, False))
    check("worker login", by.get("v15_worker") == (True, False))
    check("repl nologin", by.get("v15_repl") == (False, False))
    for key in (
        "governance_iterations", "governance_depth", "governance_io",
        "governance_statement",
    ):
        check(f"hook role {key}", by.get(f"v15_hook_{key}") == (False, False))
    cur.execute(
        """
        SELECT a.inherit_option, a.set_option
        FROM pg_auth_members a
        JOIN pg_roles r ON r.oid = a.roleid
        JOIN pg_roles m ON m.oid = a.member
        WHERE r.rolname = 'v15_repl' AND m.rolname = 'v15_worker'
        """
    )
    check("worker member of repl", cur.fetchone() == (False, True))
    cur.execute(
        """
        SELECT count(*)
        FROM pg_auth_members a
        JOIN pg_roles r ON r.oid = a.roleid
        JOIN pg_roles m ON m.oid = a.member
        WHERE (r.rolname = 'v15_repl' AND m.rolname = 'v15_owner')
           OR (r.rolname = 'v15_worker' AND m.rolname = 'v15_repl'
               AND a.member = r.oid)
           OR (r.rolname = 'v15_worker' AND m.rolname = 'v15_owner')
        """
    )
    check("owner is not a repl member", cur.fetchone()[0] == 0)
    cur.execute(
        """
        SELECT count(*)
        FROM pg_auth_members a
        JOIN pg_roles r ON r.oid = a.roleid
        JOIN pg_roles m ON m.oid = a.member
        WHERE r.rolname = 'v15_repl' AND m.rolname = 'v15_owner'
           OR m.rolname = 'v15_repl' AND r.rolname = 'v15_owner'
        """
    )
    check("no owner-repl membership", cur.fetchone()[0] == 0)
    for role in (
        "v15_hook_governance_iterations", "v15_hook_governance_depth",
        "v15_hook_governance_io", "v15_hook_governance_statement",
    ):
        cur.execute(
            """
            SELECT has_schema_privilege(%s, 'v15', 'USAGE')
                OR has_schema_privilege(%s, 'jaz', 'USAGE')
            """,
            (role, role),
        )
        check(f"{role} no schema usage", cur.fetchone()[0] is False)
    cur.execute(
        """
        SELECT has_database_privilege('v15_repl', current_database(), 'TEMP')
            OR has_database_privilege('v15_worker', current_database(), 'TEMP')
            OR has_database_privilege('public', current_database(), 'TEMP')
        """
    )
    check("no TEMP", cur.fetchone()[0] is False)


def test_execute(cur) -> None:
    expectations = [
        ("v15.v15_on_phase(uuid,integer,text,text,jsonb)", "v15_owner", True),
        ("v15.v15_on_phase(uuid,integer,text,text,jsonb)", "v15_worker", False),
        ("v15.v15_on_phase(uuid,integer,text,text,jsonb)", "v15_repl", False),
        ("v15.v15_on_phase(uuid,integer,text,text,jsonb)", "public", False),
        ("v15.v15_assert_manifest()", "v15_owner", True),
        ("v15.v15_assert_manifest()", "v15_worker", False),
        ("v15.v15_assert_manifest()", "v15_repl", False),
        ("v15.v15_assert_invoke_manifest(uuid)", "v15_owner", True),
        ("v15.v15_assert_invoke_manifest(uuid)", "v15_worker", False),
        ("v15.v15_span_open(uuid,text)", "v15_owner", True),
        ("v15.v15_span_open(uuid,text)", "v15_worker", True),
        ("v15.v15_span_open(uuid,text)", "v15_repl", False),
        ("v15.v15_next_runnable()", "v15_worker", True),
        ("v15.v15_next_runnable()", "v15_repl", False),
        ("v15.v15_current_scratch_schema()", "v15_repl", True),
        ("v15.v15_current_scratch_schema()", "v15_worker", False),
        ("v15.v15_current_scratch_schema()", "v15_owner", False),
        ("v15.governance_iterations(jsonb)", "v15_owner", True),
        ("v15.governance_iterations(jsonb)", "v15_repl", False),
        ("v15.governance_iterations(jsonb)", "v15_hook_governance_iterations", False),
    ]
    for fn, role, expected in expectations:
        cur.execute("SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, fn))
        check(f"execute {role} {fn}", cur.fetchone()[0] is expected)
    cur.execute(
        """
        SELECT bool_or(a.is_grantable)
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        CROSS JOIN LATERAL aclexplode(p.proacl) a
        WHERE n.nspname = 'v15'
          AND p.proname IN (
            'v15_on_phase', 'v15_assert_manifest', 'v15_assert_invoke_manifest',
            'governance_iterations', 'governance_depth', 'governance_io',
            'governance_statement'
          )
        """
    )
    check("no grant option on phase/asserts/handlers", cur.fetchone()[0] is False)
    cur.execute(
        """
        SELECT p.proname
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'pg_catalog'
          AND (
            p.proname = ANY(%s)
            OR p.proname LIKE 'pg_advisory%%'
            OR p.proname LIKE 'pg_try_advisory%%'
            OR p.proname LIKE 'dblink%%'
          )
          AND p.proname <> 'pg_cancel_backend'
          AND (
            has_function_privilege('public', p.oid, 'EXECUTE')
            OR has_function_privilege('v15_repl', p.oid, 'EXECUTE')
          )
        """,
        (list(REVOKED),),
    )
    check("revoked catalog functions", cur.fetchall() == [])
    cur.execute(
        """
        SELECT has_function_privilege('public', 'pg_cancel_backend(integer)', 'EXECUTE'),
               has_function_privilege('v15_repl', 'pg_cancel_backend(integer)', 'EXECUTE'),
               has_function_privilege('v15_worker', 'pg_cancel_backend(integer)', 'EXECUTE')
        """
    )
    check("pg_cancel_backend only worker", cur.fetchone() == (False, False, True))
    cur.execute(
        """
        SELECT proname FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'v15' AND p.prosecdef
          AND p.prosrc ~* '(set[[:space:]]+role|reset[[:space:]]+role|set[[:space:]]+session[[:space:]]+authorization)'
        """
    )
    check("definer bodies do not switch role", cur.fetchall() == [])


def test_manifest(cur) -> None:
    cur.execute(
        """
        SELECT max_iterations, max_depth, max_io_attempts, max_statement_ms,
               manifest_digest = md5(jsonb_build_object(
                 'max_depth', max_depth,
                 'max_io_attempts', max_io_attempts,
                 'max_iterations', max_iterations,
                 'max_statement_ms', max_statement_ms
               )::text),
               (SELECT count(*) FROM v15.governance_manifest)
        FROM v15.governance_manifest
        """
    )
    row = cur.fetchone()
    check("manifest seed", row[0:4] == (10, 8, 3, 30000), row)
    check("manifest digest matches columns", row[4] is True)
    check("manifest singleton count", row[5] == 1)
    cur.execute("SELECT v15.v15_assert_manifest()")
    check("assert_manifest ok", True)
    cur.execute("UPDATE v15.governance_manifest SET manifest_digest = 'bad'")
    fails(cur, "SELECT v15.v15_assert_manifest()", code="P1504", label="bad digest")
    cur.execute(
        """
        UPDATE v15.governance_manifest
           SET manifest_digest = md5(jsonb_build_object(
                 'max_depth', max_depth,
                 'max_io_attempts', max_io_attempts,
                 'max_iterations', max_iterations,
                 'max_statement_ms', max_statement_ms
               )::text)
        """
    )
    fails(
        cur,
        "INSERT INTO v15.governance_manifest VALUES (1, 1, 1, 1, 1, 'x', clock_timestamp())",
        code="23505",
        label="second manifest row",
    )
    fails(
        cur,
        "DELETE FROM v15.governance_manifest",
        code="55000",
        label="manifest delete",
    )
    fails(
        cur,
        "INSERT INTO v15.governance_manifest (manifest_id, max_iterations, max_depth, max_io_attempts, max_statement_ms, manifest_digest, created_at) VALUES (1, 0, 1, 1, 1, 'x', clock_timestamp())",
        code="23514",
        label="manifest limit < 1",
    )
    cur.execute("ALTER TABLE v15.governance_manifest DISABLE TRIGGER USER")
    cur.execute("DELETE FROM v15.governance_manifest")
    fails(cur, "SELECT v15.v15_assert_manifest()", code="P1504", label="missing manifest")
    cur.execute(
        """
        INSERT INTO v15.governance_manifest
        SELECT 1, 10, 8, 3, 30000,
               md5(jsonb_build_object(
                 'max_depth', 8,
                 'max_io_attempts', 3,
                 'max_iterations', 10,
                 'max_statement_ms', 30000
               )::text),
               clock_timestamp()
        """
    )
    cur.execute("ALTER TABLE v15.governance_manifest ENABLE TRIGGER USER")
    cur.execute("SELECT v15.v15_assert_manifest()")
    check("assert_manifest restored", True)


def test_checks(cur) -> None:
    iid = str(uuid.uuid4())
    fails(
        cur,
        """
        INSERT INTO v15.invokes (
          invoke_id, parent_invoke_id, parent_iteration, root_invoke_id, depth,
          status, fatal, recursion_available, resolved_config, config_digest,
          manifest_digest, scratch_schema, fence, created_at, updated_at
        ) VALUES (
          %s, %s, NULL, %s, 1, 'runnable', false, true, '{}', 'c', 'm', %s, 1,
          clock_timestamp(), clock_timestamp()
        )
        """,
        (iid, iid, iid, scratch_for(iid)),
        code="23514",
        label="parent pair",
    )
    fails(
        cur,
        """
        INSERT INTO v15.invokes (
          invoke_id, root_invoke_id, depth, status, fatal, recursion_available,
          resolved_config, config_digest, manifest_digest, scratch_schema, fence,
          lease_owner, created_at, updated_at
        ) VALUES (
          %s, %s, 1, 'runnable', false, true, '{}', 'c', 'm', %s, 1, 'w',
          clock_timestamp(), clock_timestamp()
        )
        """,
        (iid, iid, scratch_for(iid)),
        code="23514",
        label="runnable lease",
    )
    fails(
        cur,
        """
        INSERT INTO v15.invokes (
          invoke_id, root_invoke_id, depth, status, fatal, recursion_available,
          resolved_config, config_digest, manifest_digest, scratch_schema, fence,
          created_at, updated_at
        ) VALUES (
          %s, %s, 1, 'completed', false, true, '{}', 'c', 'm', %s, 1,
          clock_timestamp(), clock_timestamp()
        )
        """,
        (iid, iid, scratch_for(iid)),
        code="23514",
        label="completed requires return_value",
    )
    fails(
        cur,
        """
        INSERT INTO v15.invokes (
          invoke_id, root_invoke_id, depth, status, return_value, error, fatal,
          recursion_available, resolved_config, config_digest, manifest_digest,
          scratch_schema, fence, created_at, updated_at
        ) VALUES (
          %s, %s, 1, 'failed', NULL, NULL, false, true, '{}', 'c', 'm', %s, 1,
          clock_timestamp(), clock_timestamp()
        )
        """,
        (iid, iid, scratch_for(iid)),
        code="23514",
        label="failed requires error",
    )
    fails(
        cur,
        """
        INSERT INTO v15.invokes (
          invoke_id, root_invoke_id, depth, status, error, fatal,
          recursion_available, resolved_config, config_digest, manifest_digest,
          scratch_schema, fence, created_at, updated_at
        ) VALUES (
          %s, %s, 1, 'aborted', '{"code":"V15_BUDGET_EXHAUSTED"}', false, true,
          '{}', 'c', 'm', %s, 1, clock_timestamp(), clock_timestamp()
        )
        """,
        (iid, iid, scratch_for(iid)),
        code="23514",
        label="aborted requires fatal",
    )
    insert_invoke(cur, iid, return_value='{"ok":true}', status="completed")
    cur.execute("DELETE FROM v15.invokes WHERE invoke_id = %s", (iid,))
    pool = str(uuid.uuid4())
    fails(
        cur,
        """
        INSERT INTO v15.budget_pools (pool_id, cost_reserved)
        VALUES (%s, -1)
        """,
        (pool,),
        code="23514",
        label="cost_reserved >= 0",
    )
    insert_invoke(cur, iid)
    cur.execute(
        """
        INSERT INTO v15.iterations (invoke_id, iteration, status)
        VALUES (%s, 0, 'pending')
        """,
        (iid,),
    )
    fails(
        cur,
        """
        INSERT INTO v15.statements (
          invoke_id, iteration, stmt_index, sql, sql_digest, kind, status
        ) VALUES (%s, 0, 0, 'select 1', 'nope', 'plain', 'pending')
        """,
        (iid,),
        code="23514",
        label="sql_digest",
    )
    fails(
        cur,
        """
        INSERT INTO v15.statements (
          invoke_id, iteration, stmt_index, sql, sql_digest, kind, status
        ) VALUES (%s, 0, 0, 'select 1', md5('select 1'), 'bind_invoke', 'pending')
        """,
        (iid,),
        code="23514",
        label="bind_invoke name",
    )
    fails(
        cur,
        """
        INSERT INTO v15.bindings (invoke_id, name, kind, value, show_in_prompt, provenance)
        VALUES (%s, 'answer', 'tool', '{}'::jsonb, false, 'explicit')
        """,
        (iid,),
        code="23514",
        label="tool without tool_id",
    )
    fails(
        cur,
        """
        INSERT INTO v15.bindings (
          invoke_id, name, kind, value, tool_id, show_in_prompt, provenance
        ) VALUES (%s, 'answer', 'tool', '{}'::jsonb, %s, false, 'explicit')
        """,
        (iid, str(uuid.uuid4())),
        code="23503",
        label="tool_id fk",
    )

def test_events_and_messages(cur) -> None:
    iid = str(uuid.uuid4())
    insert_invoke(cur, iid)
    cur.execute(
        """
        INSERT INTO v15.invoke_events (
          invoke_id, seq, event_class, span, phase, payload, created_at
        ) VALUES (%s, 0, 'span', 'invoke', 'enter', '{}', clock_timestamp())
        """,
        (iid,),
    )
    fails(
        cur,
        """
        INSERT INTO v15.invoke_events (
          invoke_id, seq, event_class, span, phase, payload, created_at
        ) VALUES (%s, 2, 'span', 'invoke', 'exit', '{}', clock_timestamp())
        """,
        (iid,),
        code="23514",
        label="event seq gap",
    )
    fails(
        cur,
        "UPDATE v15.invoke_events SET payload = '{}' WHERE invoke_id = %s",
        (iid,),
        code="55000",
        label="event update",
    )
    fails(
        cur,
        "DELETE FROM v15.invoke_events WHERE invoke_id = %s",
        (iid,),
        code="55000",
        label="event delete",
    )
    cur.execute(
        """
        INSERT INTO v15.llm_messages (
          invoke_id, msg_seq, message_id, role, kind, content
        ) VALUES (%s, 0, 'seed:system', 'system', 'seed', 'hi')
        """,
        (iid,),
    )
    fails(
        cur,
        """
        INSERT INTO v15.llm_messages (
          invoke_id, msg_seq, message_id, role, kind, content
        ) VALUES (%s, 2, 'seed:inputs', 'user', 'seed', 'in')
        """,
        (iid,),
        code="23514",
        label="message seq gap",
    )
    fails(
        cur,
        "UPDATE v15.llm_messages SET content = 'x' WHERE invoke_id = %s",
        (iid,),
        code="55000",
        label="message update",
    )
    fails(
        cur,
        "DELETE FROM v15.llm_messages WHERE invoke_id = %s",
        (iid,),
        code="55000",
        label="message delete",
    )
    fails(
        cur,
        """
        INSERT INTO v15.llm_messages (
          invoke_id, msg_seq, message_id, iteration, role, kind, content
        ) VALUES (%s, 1, 'seed:inputs', 0, 'user', 'seed', 'in')
        """,
        (iid,),
        code="23514",
        label="seed iteration null",
    )

def test_hooks_and_phase(cur) -> None:
    cur.execute(
        """
        SELECT hook_key, baseline_required, search_path,
               pg_get_userbyid(owner_role),
               handler_digest = v15.v15_handler_digest(regprocedure)
        FROM v15.hook_defs
        ORDER BY hook_key
        """
    )
    rows = cur.fetchall()
    check(
        "four governance hook_defs",
        rows == [
            ("governance_depth", True, "pg_catalog", "v15_hook_governance_depth", True),
            ("governance_io", True, "pg_catalog", "v15_hook_governance_io", True),
            ("governance_iterations", True, "pg_catalog", "v15_hook_governance_iterations", True),
            ("governance_statement", True, "pg_catalog", "v15_hook_governance_statement", True),
        ],
        rows,
    )
    for key in (
        "governance_iterations", "governance_depth", "governance_io",
        "governance_statement",
    ):
        cur.execute(f"SELECT v15.{key}('{{}}'::jsonb)")
        body = cur.fetchone()[0]
        if isinstance(body, str):
            body = json.loads(body)
        check(f"stub {key}", body == {"contract": 1, "action": "proceed"}, body)
    cur.execute(
        """
        SELECT v15.v15_on_phase(
          '00000000-0000-0000-0000-000000000000'::uuid, 0, 'invoke', 'enter', '{}'::jsonb
        )
        """
    )
    body = cur.fetchone()[0]
    if isinstance(body, str):
        body = json.loads(body)
    check("on_phase stub", body == {"contract": 1, "action": "proceed"}, body)
    cur.execute(
        """
        SELECT prosecdef, provolatile, proconfig
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'v15' AND p.proname = 'v15_on_phase'
        """
    )
    check("on_phase contract attrs", cur.fetchone() == (True, "v", ["search_path=pg_catalog"]))
    iid = str(uuid.uuid4())
    ceilings = (4, 2, 2, 1000)
    digest_sql = """
      md5(jsonb_build_object(
        'max_depth', %s,
        'max_io_attempts', %s,
        'max_iterations', %s,
        'max_statement_ms', %s
      )::text)
    """
    cur.execute("SELECT " + digest_sql, (ceilings[1], ceilings[2], ceilings[0], ceilings[3]))
    digest = cur.fetchone()[0]
    insert_invoke(cur, iid, manifest_digest=digest)
    keys = {
        "governance_iterations": ceilings[0],
        "governance_depth": ceilings[1],
        "governance_io": ceilings[2],
        "governance_statement": ceilings[3],
    }
    for ordinal, (key, value) in enumerate(keys.items()):
        cur.execute(
            """
            INSERT INTO v15.invoke_hooks (
              invoke_id, ordinal, hook_def_id, channel, config, state
            )
            SELECT %s, %s, hook_def_id, 'baseline', jsonb_build_object('max', %s), '{}'
            FROM v15.hook_defs WHERE hook_key = %s
            """,
            (iid, ordinal, value, key),
        )
    cur.execute("SELECT v15.v15_assert_invoke_manifest(%s)", (iid,))
    check("assert_invoke_manifest ok", True)
    cur.execute(
        "UPDATE v15.invokes SET manifest_digest = 'bad' WHERE invoke_id = %s",
        (iid,),
    )
    fails(
        cur,
        "SELECT v15.v15_assert_invoke_manifest(%s)",
        (iid,),
        code="P1521",
        label="invoke digest mismatch",
    )
    fails(
        cur,
        "DELETE FROM v15.invoke_hooks WHERE invoke_id = %s",
        (iid,),
        code="P1532",
        label="baseline delete",
    )
    fails(
        cur,
        """
        UPDATE v15.invoke_hooks
           SET config = '{"max": 1}'::jsonb
         WHERE invoke_id = %s AND ordinal = 0
        """,
        (iid,),
        code="P1532",
        label="baseline config update",
    )
    missing = str(uuid.uuid4())
    insert_invoke(cur, missing, manifest_digest=digest)
    fails(
        cur,
        "SELECT v15.v15_assert_invoke_manifest(%s)",
        (missing,),
        code="P1521",
        label="missing baseline",
    )

def test_worker_scan(server) -> None:
    root_a = "00000000-0000-0000-0000-0000000000a1"
    child = "00000000-0000-0000-0000-0000000000a2"
    root_b = "00000000-0000-0000-0000-0000000000b1"
    leased = "00000000-0000-0000-0000-0000000000c1"
    suspended = "00000000-0000-0000-0000-0000000000d1"
    conn = connect(server)
    conn.autocommit = True
    cur = conn.cursor()
    insert_invoke(cur, root_a)
    insert_invoke(cur, child, parent=root_a, parent_iteration=0, root=root_a, depth=2)
    insert_invoke(cur, root_b)
    insert_invoke(
        cur, leased, status="leased", lease_owner="old",
        lease_until="2000-01-01 00:00:00+00",
    )
    insert_invoke(cur, suspended, status="suspended")
    cur.execute(
        """
        INSERT INTO v15.invoke_events (
          invoke_id, seq, event_class, span, phase, payload, created_at
        ) VALUES (%s, 0, 'span', 'llm_query', 'enter', '{}', clock_timestamp())
        """,
        (root_a,),
    )
    conn.close()
    worker = connect(server, "v15_worker")
    worker.autocommit = False
    wcur = worker.cursor()
    fails(
        wcur,
        "INSERT INTO v15.invokes (invoke_id) VALUES (%s)",
        (str(uuid.uuid4()),),
        code="42501",
        label="worker no kernel dml",
    )
    fails(
        wcur,
        "SELECT v15.v15_on_phase(%s::uuid, 0, 'invoke', 'enter', '{}'::jsonb)",
        (root_a,),
        code="42501",
        label="worker cannot execute on_phase",
    )
    wcur.execute("SELECT v15.v15_next_runnable()")
    got = [str(row[0]) for row in wcur.fetchall()]
    check(
        "next_runnable order",
        got == [child, root_a, root_b],
        got,
    )
    wcur.execute("SELECT v15.v15_span_open(%s::uuid, 'llm_query')", (root_a,))
    check("span open", wcur.fetchone()[0] is True)
    worker.close()
    conn = connect(server)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO v15.invoke_events (
          invoke_id, seq, event_class, span, phase, outcome, payload, created_at
        ) VALUES (
          %s, 1, 'span', 'llm_query', 'exit', 'completed', '{}', clock_timestamp()
        )
        """,
        (root_a,),
    )
    conn.close()
    worker = connect(server, "v15_worker")
    worker.autocommit = False
    wcur = worker.cursor()
    wcur.execute("SELECT v15.v15_span_open(%s::uuid, 'llm_query')", (root_a,))
    check("span closed", wcur.fetchone()[0] is False)
    wcur.execute("SET ROLE v15_repl")
    fails(
        wcur,
        "INSERT INTO v15.exec_context (backend_pid, invoke_id, iteration, stmt_index, scratch_schema) VALUES (pg_backend_pid(), %s, 0, 0, 's_x')",
        (root_a,),
        code="42501",
        label="repl no exec_context dml",
    )
    fails(
        wcur,
        "SELECT set_config('search_path', 'pg_catalog', true)",
        code="42501",
        label="repl set_config",
    )
    fails(wcur, "SELECT pg_sleep(0)", code="42501", label="repl pg_sleep")
    fails(
        wcur,
        "CREATE TEMP TABLE v15_should_not_exist (id int)",
        code="42501",
        label="repl no temp",
    )
    wcur.execute("SELECT current_user, session_user")
    check("model statement identity", wcur.fetchone() == ("v15_repl", "v15_worker"))
    wcur.execute("RESET ROLE")
    wcur.execute("SELECT current_user")
    check("reset role returns to worker", wcur.fetchone()[0] == "v15_worker")
    worker.close()
    sup = connect(server)
    sup.autocommit = True
    scur = sup.cursor()
    scur.execute("SET SESSION AUTHORIZATION v15_repl")
    try:
        scur.execute("SET ROLE v15_worker")
    except psycopg2.Error as exc:
        check("repl cannot set worker", exc.pgcode == "42501", exc.pgcode)
    else:
        raise AssertionError("repl cannot set worker: expected failure")
    scur.execute("RESET SESSION AUTHORIZATION")
    sup.close()
    conn = connect(server)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("ALTER TABLE v15.invoke_events DISABLE TRIGGER USER")
    for iid in (child, root_a, root_b, leased, suspended):
        cur.execute("DELETE FROM v15.invoke_events WHERE invoke_id = %s", (iid,))
        cur.execute("DELETE FROM v15.invokes WHERE invoke_id = %s", (iid,))
    cur.execute("ALTER TABLE v15.invoke_events ENABLE TRIGGER USER")
    conn.close()


def test_scratch_guard(server) -> None:
    iid = str(uuid.uuid4())
    scratch = scratch_for(iid)
    conn = connect(server)
    conn.autocommit = False
    cur = conn.cursor()
    insert_invoke(cur, iid, scratch=scratch)
    cur.execute("SELECT pg_backend_pid()")
    pid = cur.fetchone()[0]
    cur.execute(
        """
        INSERT INTO v15.exec_context (
          backend_pid, invoke_id, iteration, stmt_index, scratch_schema
        ) VALUES (%s, %s, 0, 0, %s)
        """,
        (pid, iid, scratch),
    )
    cur.execute(f"CREATE SCHEMA {scratch} AUTHORIZATION v15_owner")
    cur.execute(f"GRANT USAGE, CREATE ON SCHEMA {scratch} TO v15_repl")
    cur.execute("CREATE SCHEMA outside AUTHORIZATION v15_owner")
    cur.execute("GRANT USAGE, CREATE ON SCHEMA outside TO v15_repl")
    cur.execute("CREATE TABLE outside.owned (id int)")
    cur.execute("ALTER TABLE outside.owned OWNER TO v15_repl")
    cur.execute("SET LOCAL ROLE v15_repl")
    cur.execute(f"CREATE TABLE {scratch}.ok (id int)")
    cur.execute(f"CREATE UNIQUE INDEX ok_id ON {scratch}.ok (id)")
    cur.execute(f"CREATE VIEW {scratch}.v AS SELECT 1 AS n")
    cur.execute(f"CREATE TABLE {scratch}.t2 AS SELECT 1 AS n")
    cur.execute(f"SELECT 2 INTO {scratch}.t3")
    cur.execute("RESET ROLE")
    cur.execute(
        """
        SELECT pg_get_userbyid(relowner), relacl IS NULL
        FROM pg_class
        WHERE oid = %s::regclass
        """,
        (f"{scratch}.ok",),
    )
    check("scratch table owner", cur.fetchone() == ("v15_repl", True))
    cur.execute("SET LOCAL ROLE v15_repl")
    fails(
        cur,
        "CREATE TABLE outside.nope (id int)",
        code="P1512",
        label="guard rejects outside create",
    )
    fails(
        cur,
        f"CREATE FUNCTION {scratch}.f() RETURNS int LANGUAGE sql AS 'SELECT 1'",
        code="P1512",
        label="guard rejects create function",
    )
    fails(
        cur,
        f"ALTER TABLE {scratch}.ok ADD COLUMN extra int",
        code="P1512",
        label="guard rejects alter table",
    )
    fails(
        cur,
        "DROP TABLE outside.owned",
        code="P1512",
        label="sql_drop rejects outside drop",
    )
    cur.execute(f"DROP VIEW {scratch}.v")
    cur.execute(f"DROP TABLE {scratch}.ok")
    cur.execute(
        """
        SELECT prosrc, prosecdef, proconfig
        FROM pg_proc
        WHERE proname = 'v15_scratch_guard'
        """
    )
    src, defin, cfg = cur.fetchone()
    check("guard qualified scratch call", "v15.v15_current_scratch_schema()" in src)
    check("guard invoker", defin is False)
    check("guard search_path", cfg == ["search_path=pg_catalog"])
    cur.execute(
        """
        SELECT evtname FROM pg_event_trigger
        WHERE evtname IN ('v15_scratch_guard', 'v15_scratch_sql_drop')
        ORDER BY 1
        """
    )
    check(
        "event triggers",
        [row[0] for row in cur.fetchall()] == ["v15_scratch_guard", "v15_scratch_sql_drop"],
    )
    conn.rollback()
    conn.close()


def main() -> int:
    server = get_server()
    setup_db()
    conn = connect(server)
    conn.autocommit = False
    cur = conn.cursor()
    test_catalog(cur)
    test_roles(cur)
    test_execute(cur)
    test_manifest(cur)
    test_checks(cur)
    test_events_and_messages(cur)
    test_hooks_and_phase(cur)
    conn.rollback()
    conn.close()
    test_worker_scan(server)
    test_scratch_guard(server)
    print("[ready] schema gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
