"""Stage 13 gate: bind_tool store, classifier, suspend, begin/mark/settle/reclaim.

Run: uv run python v15/tools/test_tools.py  (exit 0 = pass)
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import psycopg2
from psycopg2 import sql as psql
from psycopg2.extras import Json

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v15.fake_tool import FakeTool
from v15.load import SQL_LOAD_ORDER, files_through
from v15.protocol.render_prompt import render_system
from v15.protocol.split_sql import classify_statement
from v15.tools.setup_db import DB, main as setup_db
from v15.worker import Worker, run_until_quiescent

OWNER = "tools-owner"
FENCE = 1
LEASE = "10 minutes"
SCOPE = "00000000-0000-4000-8000-0000000000b1"
TABLES = {
    "budget_pools", "tool_catalog", "config_profiles", "config_scopes",
    "config_layers", "governance_manifest", "invokes", "iterations",
    "statements", "llm_requests", "llm_attempts", "llm_messages",
    "repl_history", "bindings", "exec_context", "invoke_events",
    "hook_defs", "invoke_hooks", "blackboard", "hook_counters", "tool_grants",
    "tool_requests", "tool_attempts",
}


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


def parse_json(value):
    if isinstance(value, str):
        return json.loads(value)
    return value


def scratch_for(invoke_id: str) -> str:
    return "s_" + invoke_id.replace("-", "")


def test_load_order() -> None:
    replay = files_through("replay")
    tools = files_through("tools")
    check("SQL_LOAD_ORDER has thirteen files", len(SQL_LOAD_ORDER) == 13)
    check("tools is last file", SQL_LOAD_ORDER[-1].name == "v15_tools.sql")
    check("files_through tools is full order", tools == SQL_LOAD_ORDER)
    check(
        "tools keeps replay prefix",
        tools[:12] == replay and len(replay) == 12 and replay[-1].name == "v15_replay.sql",
    )


def test_classifier() -> None:
    got = classify_statement(
        "SELECT jaz.bind_tool('out','fake_search','{}'::jsonb)"
    )
    check("bind_tool kind", got.kind == "bind_tool", got)
    check("bind_tool bind_name", got.bind_name == "out", got)
    check("bind_tool tool_name", got.tool_name == "fake_search", got)
    check("bind_tool arg_sql", got.arg_sql == "'{}'::jsonb", got)
    check("bind_tool no reject", got.reject_code is None, got)
    quoted = classify_statement(
        'SELECT jaz."bind_tool"(\'out\',\'fake_search\',\'{}\'::jsonb)'
    )
    check("quoted bind_tool", quoted.kind == "bind_tool" and quoted.tool_name == "fake_search", quoted)
    folded = classify_statement(
        "select JAZ.bind_tool('out','fake_search','{}'::jsonb)"
    )
    check("bind_tool case", folded.kind == "bind_tool", folded)
    check(
        "string is not bind_tool",
        classify_statement("SELECT 'jaz.bind_tool'") == ("plain", None, None, None),
    )
    check(
        "comment is not bind_tool",
        classify_statement("/* jaz.bind_tool */ SELECT 1") == ("plain", None, None, None),
    )
    check(
        "line comment is not bind_tool",
        classify_statement("SELECT 1 -- jaz.bind_tool\n") == ("plain", None, None, None),
    )
    check(
        "dollar quote is not bind_tool",
        classify_statement("SELECT $$ jaz.bind_tool $$") == ("plain", None, None, None),
    )
    d24 = classify_statement(
        "SELECT jaz.bind_tool('out','fake_search',(SELECT 1 INTO t))"
    )
    check(
        "D24 write is bind_tool form",
        d24.kind == "bind_tool"
        and d24.reject_code == "V15_INVOKE_FORM"
        and d24.tool_name == "fake_search",
        d24,
    )
    insert = classify_statement(
        "SELECT jaz.bind_tool('out','fake_search',(INSERT))"
    )
    check("D24 INSERT token", insert.reject_code == "V15_INVOKE_FORM", insert)
    six = classify_statement("SELECT jaz.bind_tool('out','fake_search')")
    check("two-arg bind_tool is form", six == ("plain", None, None, "V15_INVOKE_FORM"), six)
    check(
        "DO is dialect",
        classify_statement("DO $$ BEGIN PERFORM 1; END $$")
        == ("plain", None, None, "V15_DIALECT"),
    )
    check(
        "unquoted return is form",
        classify_statement("SELECT jaz.return('null'::jsonb)")
        == ("plain", None, None, "V15_INVOKE_FORM"),
    )
    check(
        "ALTER TABLE is ddl",
        classify_statement("ALTER TABLE t ADD COLUMN x int")
        == ("plain", None, None, "V15_DDL"),
    )
    from v15.worker import statement_payload

    plain = statement_payload("SELECT 1")[0]
    check(
        "plain payload six keys",
        set(plain) == {"sql", "sql_digest", "kind", "bind_name", "arg_sql", "reject_code"}
        and "tool_name" not in plain,
        plain,
    )
    tool = statement_payload("SELECT jaz.bind_tool('out','fake_search','{}'::jsonb)")[0]
    check(
        "bind_tool payload seven keys",
        set(tool)
        == {
            "sql",
            "sql_digest",
            "kind",
            "bind_name",
            "arg_sql",
            "reject_code",
            "tool_name",
        }
        and tool["tool_name"] == "fake_search",
        tool,
    )
    invoke = statement_payload("SELECT jaz.bind_invoke('kid', '{}'::jsonb)")[0]
    check("bind_invoke payload six keys", "tool_name" not in invoke and len(invoke) == 6, invoke)


def test_no_socket() -> None:
    import v15.fake_tool as fake_tool
    import v15.protocol.split_sql as split
    from v15.fake_tool import FakeTool

    check("split_sql does not bind socket", "socket" not in split.__dict__)
    check("test_tools does not bind socket", "socket" not in globals())
    check("fake_tool does not bind socket", "socket" not in fake_tool.__dict__)
    src = (AGENT_ROOT / "v15" / "fake_tool.py").read_text()
    imports = "\n".join(
        line.strip()
        for line in src.splitlines()
        if line.startswith("import ") or line.startswith("from ")
    )
    for banned in ("socket", "urllib", "http"):
        check(f"fake_tool imports no {banned}", banned not in imports)
    check("unregistered FakeTool is ok false", FakeTool().call("missing", {}) == {"ok": False})
    default = FakeTool().call("fake_search", {})
    check(
        "default fake_search ok",
        default.get("ok") is True and "value" in default,
        default,
    )


def stmt_element(cur, sql_text: str, kind="plain", bind_name=None, arg_sql=None, reject_code=None, tool_name=None):
    cur.execute("SELECT md5(%s)", (sql_text,))
    elem = {
        "sql": sql_text,
        "sql_digest": cur.fetchone()[0],
        "kind": kind,
        "bind_name": bind_name,
        "arg_sql": arg_sql,
        "reject_code": reject_code,
    }
    if tool_name is not None:
        elem["tool_name"] = tool_name
    return elem


def seed_invoke(
    cur,
    invoke_id: str,
    statements: list,
    *,
    leased: bool = True,
    pool_id: str | None = None,
    max_io: int = 3,
) -> None:
    scratch = scratch_for(invoke_id)
    cur.execute(
        psql.SQL("CREATE SCHEMA {} AUTHORIZATION v15_owner").format(psql.Identifier(scratch))
    )
    status = "leased" if leased else "runnable"
    cur.execute(
        """
        INSERT INTO v15.invokes (
          invoke_id, parent_invoke_id, parent_iteration, root_invoke_id, depth,
          status, fatal, recursion_available, resolved_config, config_digest,
          pool_id, manifest_digest, scratch_schema, fence, lease_owner, lease_until,
          created_at, updated_at
        ) VALUES (
          %s, NULL, NULL, %s, 1,
          %s, false, true, '{"repl":{"timeout_ms":30000}}'::jsonb, 'cfg',
          %s, 'md', %s, %s,
          CASE WHEN %s THEN %s ELSE NULL END,
          CASE WHEN %s THEN clock_timestamp() + interval '10 minutes' ELSE NULL END,
          clock_timestamp(), clock_timestamp()
        )
        """,
        (invoke_id, invoke_id, status, pool_id, scratch, FENCE, leased, OWNER, leased),
    )
    cur.execute(
        """
        INSERT INTO v15.iterations (invoke_id, iteration, status, resume_stmt, capture)
        VALUES (%s, 0, 'executing', 0, '')
        """,
        (invoke_id,),
    )
    for ordinal, key, mx in (
        (0, "governance_iterations", 10),
        (1, "governance_depth", 8),
        (2, "governance_io", max_io),
        (3, "governance_statement", 30000),
    ):
        cur.execute(
            """
            INSERT INTO v15.invoke_hooks (
              invoke_id, ordinal, hook_def_id, channel, config, state
            )
            SELECT %s, %s, d.hook_def_id, 'baseline',
                   jsonb_build_object('max', %s), '{}'::jsonb
            FROM v15.hook_defs d
            WHERE d.hook_key = %s
            """,
            (invoke_id, ordinal, mx, key),
        )
    for index, spec in enumerate(statements):
        sql_text, kind = spec[0], spec[1]
        bind = spec[2] if len(spec) > 2 else None
        tool = spec[3] if len(spec) > 3 else None
        cur.execute(
            """
            INSERT INTO v15.statements (
              invoke_id, iteration, stmt_index, sql, sql_digest, kind,
              bind_name, tool_name, arg_sql, status
            ) VALUES (%s, 0, %s, %s, md5(%s), %s, %s, %s, %s, 'pending')
            """,
            (
                invoke_id, index, sql_text, sql_text, kind, bind, tool,
                "'{}'::jsonb" if kind == "bind_tool" else None,
            ),
        )


def enter_repl(conn, invoke_id: str) -> None:
    cur = conn.cursor()
    cur.execute("SET LOCAL lock_timeout = '2s'")
    cur.execute("SELECT v15.v15_begin_exec(%s, %s, %s)", (invoke_id, FENCE, OWNER))
    conn.commit()


def grant_catalog_tool(cur, invoke_id: str, name: str) -> str:
    cur.execute("SELECT tool_id::text FROM v15.tool_catalog WHERE name = %s", (name,))
    tool_id = cur.fetchone()[0]
    cur.execute(
        """
        INSERT INTO v15.bindings (
          invoke_id, name, kind, value, tool_id, show_in_prompt, provenance
        ) VALUES (%s, %s, 'tool', '{}'::jsonb, %s, false, 'explicit')
        """,
        (invoke_id, name, tool_id),
    )
    cur.execute(
        "INSERT INTO v15.tool_grants (invoke_id, tool_id) VALUES (%s, %s)",
        (invoke_id, tool_id),
    )
    return tool_id


def register_sync_tool(server, cur, name: str) -> str:
    role = "v15_tool_" + name
    fn = "sync_" + name
    admin = connect(server)
    admin.autocommit = True
    try:
        acur = admin.cursor()
        acur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
        if acur.fetchone() is None:
            acur.execute(
                psql.SQL(
                    "CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT"
                ).format(psql.Identifier(role))
            )
    finally:
        admin.close()
    cur.execute(
        psql.SQL(
            """
            CREATE FUNCTION public.{}(p jsonb) RETURNS jsonb
            LANGUAGE sql STABLE SECURITY DEFINER
            SET search_path = pg_catalog
            AS $fn$ SELECT '{{}}'::jsonb $fn$
            """
        ).format(psql.Identifier(fn))
    )
    cur.execute(
        psql.SQL("ALTER FUNCTION public.{}(jsonb) OWNER TO {}").format(
            psql.Identifier(fn), psql.Identifier(role)
        )
    )
    cur.execute(
        psql.SQL("REVOKE ALL ON FUNCTION public.{}(jsonb) FROM PUBLIC").format(
            psql.Identifier(fn)
        )
    )
    cur.execute(
        psql.SQL("REVOKE ALL ON FUNCTION public.{}(jsonb) FROM {}").format(
            psql.Identifier(fn), psql.Identifier(role)
        )
    )
    cur.execute(
        psql.SQL("GRANT EXECUTE ON FUNCTION public.{}(jsonb) TO v15_owner").format(
            psql.Identifier(fn)
        )
    )
    cur.execute(
        """
        SELECT p.oid
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public' AND p.proname = %s
        """,
        (fn,),
    )
    oid = cur.fetchone()[0]
    cur.execute(
        "SELECT v15.v15_register_tool(%s, %s, %s, '{}'::jsonb, false)",
        (name, oid, name),
    )
    return str(cur.fetchone()[0])


def call(conn, query: str, args=()):
    cur = conn.cursor()
    cur.execute("SET LOCAL lock_timeout = '2s'")
    cur.execute(query, args)
    row = cur.fetchone()
    return None if row is None else row[0]


def expect(conn, query: str, args, code: str, label: str) -> None:
    try:
        call(conn, query, args)
        conn.rollback()
        check(label, False, "returned instead of " + code)
    except psycopg2.Error as exc:
        conn.rollback()
        check(label, exc.pgcode == code, exc.pgcode)


def make_pool(cur, *, calls_limit=None, calls_used=0) -> str:
    pool_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO v15.budget_pools (pool_id, calls_limit, calls_used)
        VALUES (%s, %s, %s)
        """,
        (pool_id, calls_limit, calls_used),
    )
    return pool_id


def expire_tool_attempt(cur, attempt_id: str) -> None:
    cur.execute(
        """
        UPDATE v15.tool_attempts
        SET lease_until = clock_timestamp() - interval '1 second'
        WHERE attempt_id = %s
        """,
        (attempt_id,),
    )


def seed_wait(
    admin,
    worker,
    *,
    extra=(),
    occupancy=None,
    pool_id=None,
    max_io=3,
    llm_req=False,
    bind_name="out",
):
    iid = str(uuid.uuid4())
    stmts = [
        (
            f"SELECT jaz.bind_tool('{bind_name}','fake_search','{{}}'::jsonb)",
            "bind_tool",
            bind_name,
            "fake_search",
        )
    ]
    stmts.extend(extra)
    cur = admin.cursor()
    seed_invoke(cur, iid, stmts, pool_id=pool_id, max_io=max_io)
    grant_catalog_tool(cur, iid, "fake_search")
    if occupancy is not None:
        cur.execute(
            """
            INSERT INTO v15.bindings (
              invoke_id, name, kind, value, show_in_prompt, provenance
            ) VALUES (%s, %s, 'scope', '{}'::jsonb, true, 'scope')
            """,
            (iid, occupancy),
        )
    if llm_req:
        cur.execute(
            """
            INSERT INTO v15.llm_requests (
              request_id, invoke_id, iteration, status, logical_digest
            ) VALUES (gen_random_uuid(), %s, 0, 'settled', md5('seed-llm'))
            """,
            (iid,),
        )
    admin.commit()
    enter_repl(worker, iid)
    wcur = worker.cursor()
    wcur.execute(
        "SELECT v15.v15_suspend_for_tool(%s, 0, 0, %s, '{}'::jsonb)",
        (iid, OWNER),
    )
    got = parse_json(wcur.fetchone()[0])
    worker.commit()
    if got.get("action") != "wait":
        raise AssertionError("expected wait, got " + str(got))
    return iid, got["request_id"]


def begin_tool(conn, invoke_id: str):
    got = parse_json(
        call(
            conn,
            "SELECT v15.v15_begin_tool(%s, %s, %s::interval)",
            (invoke_id, OWNER, LEASE),
        )
    )
    conn.commit()
    return got


def mark_tool(conn, attempt_id: str, fence: int = 1) -> None:
    call(
        conn,
        "SELECT v15.v15_mark_tool_started(%s, %s, %s)",
        (attempt_id, fence, OWNER),
    )
    conn.commit()


def settle_tool(conn, attempt_id: str, result: dict, fence: int = 1) -> None:
    call(
        conn,
        "SELECT v15.v15_settle_tool(%s, %s, %s, %s)",
        (attempt_id, fence, OWNER, Json(result)),
    )
    conn.commit()


def next_tool_ids(conn) -> list:
    cur = conn.cursor()
    cur.execute("SELECT v15.v15_next_tool()")
    ids = [str(row[0]) for row in cur.fetchall()]
    conn.rollback()
    return ids


def expect_store(conn, payload, code: str, label: str, invoke_id=None) -> None:
    iid = invoke_id or str(uuid.uuid4())
    try:
        conn.cursor().execute(
            "SELECT v15.v15_io_store_statements(%s, 0, %s, false)",
            (iid, Json(payload)),
        )
        conn.rollback()
        check(label, False, "returned instead of " + code)
    except psycopg2.Error as exc:
        conn.rollback()
        check(label, exc.pgcode == code, exc.pgcode)


def test_shape(cur) -> None:
    replay = files_through("replay")
    tools = files_through("tools")
    check("SQL_LOAD_ORDER has thirteen files", len(SQL_LOAD_ORDER) == 13)
    check("tools is last file", SQL_LOAD_ORDER[-1].name == "v15_tools.sql")
    check("files_through tools is full order", tools == SQL_LOAD_ORDER)
    check("first twelve equal replay prefix", tools[:12] == replay)
    cur.execute(
        """
        SELECT c.relname FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'v15' AND c.relkind = 'r' ORDER BY 1
        """
    )
    names = {row[0] for row in cur.fetchall()}
    check("twenty-three v15 tables", names == TABLES, names ^ TABLES)
    cur.execute(
        """
        SELECT c.conname
        FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE n.nspname = 'v15' AND t.relname = 'invokes' AND c.contype = 'c'
          AND pg_get_constraintdef(c.oid) LIKE '%tool_wait%'
        """
    )
    status_names = [row[0] for row in cur.fetchall()]
    check("invokes status check discovered", len(status_names) == 1, status_names)
    print("[info] invokes status constraint:", status_names[0])
    cur.execute(
        """
        SELECT c.conname
        FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE n.nspname = 'v15' AND t.relname = 'statements' AND c.contype = 'c'
          AND pg_get_constraintdef(c.oid) LIKE '%bind_tool%'
          AND pg_get_constraintdef(c.oid) LIKE '%plain%'
        """
    )
    kind_names = [row[0] for row in cur.fetchall()]
    check("statements kind check discovered", len(kind_names) == 1, kind_names)
    print("[info] statements kind constraint:", kind_names[0])
    cur.execute(
        """
        SELECT v15.v15_io_sqlstate('V15_TOOL_BINDING'),
               v15.v15_io_sqlstate('V15_TOOL_FAILED'),
               v15.v15_io_sqlstate('V15_TOOL_EXHAUSTED'),
               v15.v15_io_sqlstate('V15_TOOL_UNAUTHORIZED')
        """
    )
    check("sqlstate rows", cur.fetchone() == ("P1543", "P1544", "P1545", "P1507"))
    cur.execute(
        """
        SELECT v15.v15_govern_known_code('V15_TOOL_BINDING'),
               v15.v15_govern_known_code('V15_TOOL_FAILED'),
               v15.v15_govern_known_code('V15_TOOL_EXHAUSTED')
        """
    )
    check("known-code three new", cur.fetchone() == (True, True, True))
    cur.execute(
        """
        SELECT name, external, pg_get_userbyid(p.proowner), r.rolcanlogin
        FROM v15.tool_catalog c
        JOIN pg_proc p ON p.oid = c.handler
        JOIN pg_roles r ON r.oid = p.proowner
        WHERE c.name = 'fake_search'
        """
    )
    row = cur.fetchone()
    check(
        "fake_search seed",
        row == ("fake_search", True, "v15_tool_fake_search", False),
        row,
    )
    cur.execute(
        """
        SELECT has_function_privilege('v15_worker', 'v15.v15_suspend_for_tool(uuid,integer,integer,text,jsonb)', 'EXECUTE'),
               has_function_privilege('v15_repl', 'v15.v15_suspend_for_tool(uuid,integer,integer,text,jsonb)', 'EXECUTE'),
               has_function_privilege('public', 'v15.v15_suspend_for_tool(uuid,integer,integer,text,jsonb)', 'EXECUTE'),
               has_function_privilege('v15_repl', 'jaz.bind_tool(text,text,jsonb)', 'EXECUTE'),
               has_function_privilege('v15_worker', 'jaz.bind_tool(text,text,jsonb)', 'EXECUTE'),
               has_function_privilege('public', 'jaz.bind_tool(text,text,jsonb)', 'EXECUTE')
        """
    )
    check("ACL suspend and bind_tool", cur.fetchone() == (True, False, False, True, False, False))
    cur.execute(
        """
        SELECT has_function_privilege('v15_worker', 'v15.v15_next_tool()', 'EXECUTE'),
               has_function_privilege('v15_worker', 'v15.v15_begin_tool(uuid,text,interval)', 'EXECUTE'),
               has_function_privilege('v15_worker', 'v15.v15_mark_tool_started(uuid,bigint,text)', 'EXECUTE'),
               has_function_privilege('v15_worker', 'v15.v15_settle_tool(uuid,bigint,text,jsonb)', 'EXECUTE'),
               has_function_privilege('v15_repl', 'v15.v15_begin_tool(uuid,text,interval)', 'EXECUTE'),
               has_function_privilege('public', 'v15.v15_settle_tool(uuid,bigint,text,jsonb)', 'EXECUTE'),
               has_function_privilege('v15_worker', 'v15.v15_tool_fail_wrap(uuid,integer,integer,text,bigint)', 'EXECUTE')
        """
    )
    check(
        "ACL begin/mark/settle/next",
        cur.fetchone() == (True, True, True, True, False, False, False),
    )
    cur.execute(
        """
        SELECT p.prosrc
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'v15' AND p.proname IN (
          'v15_suspend_for_tool', 'jaz_bind_tool', 'v15_next_tool',
          'v15_begin_tool', 'v15_mark_tool_started', 'v15_settle_tool',
          'v15_tool_fail_wrap', 'v15_reclaim_expired', 'v15_io_reclaim_invoke',
          'v15_prepare_statement'
        )
        """
    )
    bodies = "\n".join(row[0] for row in cur.fetchall())
    check("no SET ROLE in new functions", "SET ROLE" not in bodies and "RESET ROLE" not in bodies)


def test_store_statements(admin) -> None:
    cur = admin.cursor()
    plain = stmt_element(cur, "SELECT 1")
    bad_digest = stmt_element(cur, "SELECT 1")
    bad_digest["sql_digest"] = "not-a-digest"
    bad_kind = stmt_element(cur, "SELECT 1")
    bad_kind["kind"] = "nope"
    bad_arg = stmt_element(cur, "SELECT 1", "bind_invoke", "child", None, None)
    expect_store(admin, [bad_digest], "P1524", "old fixture bad digest")
    expect_store(admin, [bad_kind], "P1524", "old fixture bad kind")
    expect_store(admin, [bad_arg], "P1524", "old fixture bind_invoke missing arg_sql")
    six_tool = stmt_element(
        cur, "SELECT jaz.bind_tool('out','fake_search','{}'::jsonb)",
        "bind_tool", "out", "'{}'::jsonb", None,
    )
    expect_store(admin, [six_tool], "P1524", "six-key bind_tool")
    seven = stmt_element(
        cur, "SELECT jaz.bind_tool('out','fake_search','{}'::jsonb)",
        "bind_tool", "out", "'{}'::jsonb", None, "fake_search",
    )
    extra = dict(seven)
    extra["bonus"] = "x"
    expect_store(admin, [extra], "P1524", "eight-key bind_tool")
    bad_name = dict(seven)
    bad_name["tool_name"] = "Fake"
    expect_store(admin, [bad_name], "P1524", "tool_name regex")
    iid = str(uuid.uuid4())
    seed_invoke(cur, iid, [], leased=False)
    cur.execute(
        "UPDATE v15.iterations SET status = 'pending' WHERE invoke_id = %s",
        (iid,),
    )
    admin.commit()
    cur.execute(
        "SELECT v15.v15_io_store_statements(%s, 0, %s, true)",
        (iid, Json([plain, seven])),
    )
    check("store two statements", cur.fetchone()[0] == 2)
    admin.commit()
    cur.execute(
        """
        SELECT kind, bind_name, tool_name, status
        FROM v15.statements
        WHERE invoke_id = %s
        ORDER BY stmt_index
        """,
        (iid,),
    )
    rows = cur.fetchall()
    check(
        "stored kinds",
        rows == [("plain", None, None, "pending"), ("bind_tool", "out", "fake_search", "pending")],
        rows,
    )


def test_suspend_paths(server, admin, worker) -> None:
    cur = admin.cursor()
    unknown_id = str(uuid.uuid4())
    seed_invoke(
        cur, unknown_id,
        [("SELECT jaz.bind_tool('out','nope_tool','{}'::jsonb)", "bind_tool", "out", "nope_tool")],
    )
    admin.commit()
    enter_repl(worker, unknown_id)
    wcur = worker.cursor()
    wcur.execute(
        "SELECT v15.v15_suspend_for_tool(%s, 0, 0, %s, '{}'::jsonb)",
        (unknown_id, OWNER),
    )
    got = parse_json(wcur.fetchone()[0])
    worker.commit()
    check("unknown tool reject", got == {"action": "reject", "code": "V15_TOOL_UNAUTHORIZED"}, got)
    cur.execute(
        """
        SELECT s.status, s.error->>'code', s.error->>'sqlstate', i.status,
               (SELECT count(*) FROM v15.tool_requests r WHERE r.invoke_id = %s)
        FROM v15.statements s
        JOIN v15.invokes i ON i.invoke_id = s.invoke_id
        WHERE s.invoke_id = %s
        """,
        (unknown_id, unknown_id),
    )
    row = cur.fetchone()
    check(
        "unknown keeps leased no request",
        row == ("failed", "V15_TOOL_UNAUTHORIZED", "P1507", "leased", 0),
        row,
    )

    nogrant_id = str(uuid.uuid4())
    seed_invoke(
        cur, nogrant_id,
        [("SELECT jaz.bind_tool('out','fake_search','{}'::jsonb)", "bind_tool", "out", "fake_search")],
    )
    admin.commit()
    enter_repl(worker, nogrant_id)
    wcur = worker.cursor()
    wcur.execute(
        "SELECT v15.v15_suspend_for_tool(%s, 0, 0, %s, '{}'::jsonb)",
        (nogrant_id, OWNER),
    )
    got = parse_json(wcur.fetchone()[0])
    worker.commit()
    check("no grant reject", got == {"action": "reject", "code": "V15_TOOL_UNAUTHORIZED"}, got)

    sync_id = str(uuid.uuid4())
    seed_invoke(
        cur, sync_id,
        [("SELECT jaz.bind_tool('out','echo_tool','{}'::jsonb)", "bind_tool", "out", "echo_tool")],
    )
    register_sync_tool(server, cur, "echo_tool")
    grant_catalog_tool(cur, sync_id, "echo_tool")
    admin.commit()
    enter_repl(worker, sync_id)
    wcur = worker.cursor()
    wcur.execute(
        "SELECT v15.v15_suspend_for_tool(%s, 0, 0, %s, '{}'::jsonb)",
        (sync_id, OWNER),
    )
    got = parse_json(wcur.fetchone()[0])
    worker.commit()
    check("external=false reject", got == {"action": "reject", "code": "V15_TOOL_BINDING"}, got)
    cur.execute(
        "SELECT error->>'sqlstate' FROM v15.statements WHERE invoke_id = %s",
        (sync_id,),
    )
    check("external=false is P1543", cur.fetchone()[0] == "P1543")

    wait_id = str(uuid.uuid4())
    seed_invoke(
        cur, wait_id,
        [("SELECT jaz.bind_tool('out','fake_search','{}'::jsonb)", "bind_tool", "out", "fake_search")],
    )
    grant_catalog_tool(cur, wait_id, "fake_search")
    admin.commit()
    enter_repl(worker, wait_id)
    wcur = worker.cursor()
    wcur.execute(
        "SELECT v15.v15_suspend_for_tool(%s, 0, 0, %s, '{}'::jsonb)",
        (wait_id, OWNER),
    )
    got = parse_json(wcur.fetchone()[0])
    worker.commit()
    check("wait action", got.get("action") == "wait" and "request_id" in got, got)
    cur.execute(
        """
        SELECT i.status, i.lease_owner, i.fence, it.status, s.status, s.child_invoke_id,
               r.status, r.bind_name
        FROM v15.invokes i
        JOIN v15.iterations it ON it.invoke_id = i.invoke_id
        JOIN v15.statements s ON s.invoke_id = i.invoke_id
        JOIN v15.tool_requests r ON r.invoke_id = i.invoke_id
        WHERE i.invoke_id = %s
        """,
        (wait_id,),
    )
    row = cur.fetchone()
    check(
        "tool_wait snapshot",
        row[:6] == ("tool_wait", None, FENCE, "suspended", "running", None)
        and row[6] == "open"
        and row[7] == "out",
        row,
    )
    wcur = worker.cursor()
    wcur.execute(
        "SELECT v15.v15_claim(%s, %s, '30 seconds'::interval)",
        (wait_id, OWNER),
    )
    check("claim tool_wait is NULL", wcur.fetchone()[0] is None)
    worker.rollback()
    wcur.execute("SELECT v15.v15_next_runnable()")
    runnable = [row[0] for row in wcur.fetchall()]
    worker.rollback()
    check("next_runnable omits tool_wait", uuid.UUID(wait_id) not in runnable, runnable)
    return wait_id


def test_direct_bind_tool(server, admin, worker) -> None:
    iid = str(uuid.uuid4())
    seed_invoke(
        admin.cursor(), iid,
        [("SELECT jaz.bind_tool('out','fake_search','{}'::jsonb)", "bind_tool", "out", "fake_search")],
    )
    admin.commit()
    enter_repl(worker, iid)
    cur = worker.cursor()
    cur.execute("SET LOCAL lock_timeout = '2s'")
    cur.execute(
        "SELECT v15.v15_prepare_statement(%s, %s, %s, 0)",
        (iid, FENCE, OWNER),
    )
    info = parse_json(cur.fetchone()[0])
    cur.execute(
        psql.SQL("SET LOCAL search_path TO {}, pg_catalog").format(
            psql.Identifier(info["scratch_schema"])
        )
    )
    cur.execute("SAVEPOINT model_stmt")
    cur.execute("SET LOCAL ROLE v15_repl")
    try:
        cur.execute("SELECT jaz.bind_tool('out', 'fake_search', '{}'::jsonb)")
        if cur.description:
            cur.fetchall()
        raise AssertionError("bind_tool should fail")
    except psycopg2.Error as exc:
        check("direct jaz.bind_tool form", exc.pgcode == "P1503", exc.pgcode)
        worker.rollback()


def test_success_delivery(admin, worker) -> None:
    cur = admin.cursor()
    pool_id = make_pool(cur)
    iid, _req = seed_wait(
        admin, worker,
        extra=[("SELECT 1", "plain")],
        pool_id=pool_id,
        llm_req=True,
    )
    cur.execute(
        """
        SELECT i.status, i.lease_owner, i.fence, it.status, s.status, s.child_invoke_id,
               i.parent_invoke_id,
               (SELECT count(*) FROM v15.invokes c WHERE c.parent_invoke_id = i.invoke_id)
        FROM v15.invokes i
        JOIN v15.iterations it ON it.invoke_id = i.invoke_id AND it.iteration = 0
        JOIN v15.statements s ON s.invoke_id = i.invoke_id AND s.stmt_index = 0
        WHERE i.invoke_id = %s
        """,
        (iid,),
    )
    snap = cur.fetchone()
    check(
        "wait snapshot no child/tree",
        snap == ("tool_wait", None, FENCE, "suspended", "running", None, None, 0),
        snap,
    )
    cur.execute(
        """
        SELECT span, phase
        FROM v15.invoke_events
        WHERE invoke_id = %s AND event_class = 'span' AND span = 'repl_exec'
        ORDER BY seq
        """,
        (iid,),
    )
    spans = cur.fetchall()
    check("repl_exec enter no exit", spans == [("repl_exec", "enter"), ("repl_exec", "send")], spans)
    waiting = next_tool_ids(worker)
    check("next_tool lists wait", iid in waiting, waiting)
    opened = begin_tool(worker, iid)
    check(
        "begin proceed",
        opened.get("action") == "proceed"
        and opened.get("n") == 1
        and opened.get("tool_name") == "fake_search"
        and opened.get("args") == {},
        opened,
    )
    after_begin = next_tool_ids(worker)
    check("next_tool omits leased", iid not in after_begin, after_begin)
    expect(
        worker,
        "SELECT v15.v15_begin_tool(%s, %s, %s::interval)",
        (iid, OWNER, LEASE),
        "P1523",
        "second begin while leased",
    )
    mark_tool(worker, opened["attempt_id"])
    settle_tool(worker, opened["attempt_id"], {"ok": True, "value": {"hits": 1}})
    cur.execute(
        """
        SELECT i.status, i.fence, i.lease_owner, it.status, it.resume_stmt,
               s.status, s.child_invoke_id, r.status, a.status, a.calls_charged, a.n,
               b.kind, b.provenance, b.show_in_prompt, b.value
        FROM v15.invokes i
        JOIN v15.iterations it ON it.invoke_id = i.invoke_id AND it.iteration = 0
        JOIN v15.statements s ON s.invoke_id = i.invoke_id AND s.stmt_index = 0
        JOIN v15.tool_requests r ON r.invoke_id = i.invoke_id
        JOIN v15.tool_attempts a ON a.request_id = r.request_id
        LEFT JOIN v15.bindings b ON b.invoke_id = i.invoke_id AND b.name = 'out'
        WHERE i.invoke_id = %s
        """,
        (iid,),
    )
    row = cur.fetchone()
    check(
        "success delivery snapshot",
        row[:11] == (
            "runnable", FENCE, None, "executing", 1,
            "done", None, "settled", "settled", True, 1,
        )
        and row[11:14] == ("var", "delivery", True)
        and parse_json(row[14]) == {"hits": 1},
        row,
    )
    cur.execute(
        "SELECT status FROM v15.statements WHERE invoke_id = %s AND stmt_index = 1",
        (iid,),
    )
    check("remaining statement pending", cur.fetchone()[0] == "pending")
    cur.execute(
        "SELECT count(*) FROM v15.llm_requests WHERE invoke_id = %s AND iteration = 0",
        (iid,),
    )
    check("llm_requests still 1", cur.fetchone()[0] == 1)
    cur.execute(
        "SELECT count(*) FROM v15.repl_history WHERE invoke_id = %s",
        (iid,),
    )
    check("success writes no repl_history", cur.fetchone()[0] == 0)
    cur.execute(
        """
        SELECT span, phase
        FROM v15.invoke_events
        WHERE invoke_id = %s AND event_class = 'span' AND span = 'repl_exec'
        ORDER BY seq
        """,
        (iid,),
    )
    check(
        "success leaves repl_exec open",
        cur.fetchall() == [("repl_exec", "enter"), ("repl_exec", "send")],
    )
    cur.execute(
        """
        SELECT payload->>'op' FROM v15.invoke_events
        WHERE invoke_id = %s AND event_class = 'audit'
        ORDER BY seq
        """,
        (iid,),
    )
    ops = [row[0] for row in cur.fetchall()]
    check(
        "success audit ops",
        "tool_suspend" in ops and "attempt_leased" in ops
        and "call_started" in ops and "deliver" in ops,
        ops,
    )
    after = next_tool_ids(worker)
    check("next_tool omits delivered", iid not in after, after)
    cur.execute(
        "SELECT calls_used, calls_reserved FROM v15.budget_pools WHERE pool_id = %s",
        (pool_id,),
    )
    check("success charges one call", cur.fetchone() == (1, 0))


def test_reclaim_tool(admin, worker) -> None:
    cur = admin.cursor()
    pool_id = make_pool(cur)
    iid, _req = seed_wait(admin, worker, pool_id=pool_id)
    opened = begin_tool(worker, iid)
    expire_tool_attempt(cur, opened["attempt_id"])
    admin.commit()
    n = call(worker, "SELECT v15.v15_reclaim_expired()")
    worker.commit()
    check("unmarked reclaim count", n == 1, n)
    cur.execute(
        """
        SELECT a.status, a.call_started, a.calls_charged, i.status, r.status,
               p.calls_used, p.calls_reserved
        FROM v15.tool_attempts a
        JOIN v15.tool_requests r ON r.request_id = a.request_id
        JOIN v15.invokes i ON i.invoke_id = r.invoke_id
        JOIN v15.budget_pools p ON p.pool_id = %s
        WHERE a.attempt_id = %s
        """,
        (pool_id, opened["attempt_id"]),
    )
    row = cur.fetchone()
    check(
        "unmarked failed no charge",
        row == ("failed", False, False, "tool_wait", "open", 0, 0),
        row,
    )
    marked_pool = make_pool(cur)
    mid, _ = seed_wait(admin, worker, pool_id=marked_pool)
    mopened = begin_tool(worker, mid)
    mark_tool(worker, mopened["attempt_id"])
    expire_tool_attempt(cur, mopened["attempt_id"])
    admin.commit()
    n = call(worker, "SELECT v15.v15_reclaim_expired()")
    worker.commit()
    check("marked reclaim count", n == 1, n)
    cur.execute(
        """
        SELECT a.status, a.call_started, a.calls_charged, i.status, r.status,
               p.calls_used, p.calls_reserved
        FROM v15.tool_attempts a
        JOIN v15.tool_requests r ON r.request_id = a.request_id
        JOIN v15.invokes i ON i.invoke_id = r.invoke_id
        JOIN v15.budget_pools p ON p.pool_id = %s
        WHERE a.attempt_id = %s
        """,
        (marked_pool, mopened["attempt_id"]),
    )
    row = cur.fetchone()
    check(
        "marked unknown charges calls",
        row == ("unknown", True, True, "tool_wait", "open", 1, 0),
        row,
    )
    retry = begin_tool(worker, mid)
    check("re-begin n=2", retry.get("action") == "proceed" and retry.get("n") == 2, retry)
    cur.execute(
        "SELECT calls_reserved FROM v15.budget_pools WHERE pool_id = %s",
        (marked_pool,),
    )
    check("n=2 re-reserves", cur.fetchone()[0] == 1)
    expect(
        worker,
        "SELECT v15.v15_settle_tool(%s, 1, %s, %s)",
        (mopened["attempt_id"], OWNER, Json({"ok": True, "value": {}})),
        "P1502",
        "unknown late settle",
    )
    cur.execute(
        "SELECT count(*) FROM v15.bindings WHERE invoke_id = %s AND name = 'out'",
        (mid,),
    )
    check("late settle wrote no binding", cur.fetchone()[0] == 0)
    cur.execute(
        """
        SELECT payload->>'op' FROM v15.invoke_events
        WHERE invoke_id = %s AND event_class = 'audit' AND payload->>'op' = 'tool_retry'
        """,
        (mid,),
    )
    check("tool_retry audit", cur.fetchone()[0] == "tool_retry")
    waiting = next_tool_ids(worker)
    check("leased retry omitted from next_tool", mid not in waiting, waiting)


def test_exhausted_and_budget(admin, worker) -> None:
    cur = admin.cursor()
    pool_id = make_pool(cur)
    iid, _ = seed_wait(admin, worker, pool_id=pool_id, max_io=1)
    opened = begin_tool(worker, iid)
    check("first begin n=1", opened.get("n") == 1, opened)
    expire_tool_attempt(cur, opened["attempt_id"])
    admin.commit()
    call(worker, "SELECT v15.v15_reclaim_expired()")
    worker.commit()
    got = begin_tool(worker, iid)
    check(
        "second begin exhausted",
        got.get("action") == "abort"
        and got.get("fatal") is False
        and got.get("code") == "V15_TOOL_EXHAUSTED"
        and got.get("attempt_id") is None,
        got,
    )
    cur.execute(
        """
        SELECT
          (SELECT count(*) FROM v15.tool_attempts a
           JOIN v15.tool_requests x ON x.request_id = a.request_id
           WHERE x.invoke_id = i.invoke_id AND a.n = 2),
          r.status, s.status, s.error->>'code', s.error->>'sqlstate',
          i.status, i.fatal,
          (SELECT status FROM v15.iterations WHERE invoke_id = i.invoke_id AND iteration = 1)
        FROM v15.invokes i
        JOIN v15.tool_requests r ON r.invoke_id = i.invoke_id
        JOIN v15.statements s ON s.invoke_id = i.invoke_id AND s.stmt_index = 0
        WHERE i.invoke_id = %s
        """,
        (iid,),
    )
    row = cur.fetchone()
    check(
        "exhausted wrap-up",
        row == (0, "exhausted", "failed", "V15_TOOL_EXHAUSTED", "P1545", "runnable", False, "pending"),
        row,
    )

    tight = make_pool(cur, calls_limit=1, calls_used=1)
    bid, _ = seed_wait(admin, worker, pool_id=tight)
    got = begin_tool(worker, bid)
    check(
        "pool abort",
        got.get("action") == "abort"
        and got.get("fatal") is True
        and got.get("code") == "V15_BUDGET_EXHAUSTED",
        got,
    )
    cur.execute(
        """
        SELECT i.status, i.fatal, i.error->>'sqlstate', i.error->>'code',
               r.status,
               (SELECT count(*) FROM v15.tool_attempts a
                JOIN v15.tool_requests x ON x.request_id = a.request_id
                WHERE x.invoke_id = i.invoke_id)
        FROM v15.invokes i
        JOIN v15.tool_requests r ON r.invoke_id = i.invoke_id
        WHERE i.invoke_id = %s
        """,
        (bid,),
    )
    row = cur.fetchone()
    check(
        "budget fatal no attempt",
        row == ("aborted", True, "P1514", "V15_BUDGET_EXHAUSTED", "failed", 0),
        row,
    )


def test_ok_false_and_conflict(admin, worker) -> None:
    cur = admin.cursor()
    pool_id = make_pool(cur)
    iid, _ = seed_wait(
        admin, worker,
        extra=[("SELECT 1", "plain")],
        pool_id=pool_id,
    )
    opened = begin_tool(worker, iid)
    mark_tool(worker, opened["attempt_id"])
    settle_tool(worker, opened["attempt_id"], {"ok": False})
    cur.execute(
        """
        SELECT i.status, i.fatal,
               s0.status, s0.error->>'code', s0.error->>'sqlstate',
               s1.status,
               it0.status, it0.result_kind,
               it1.status,
               r.status, a.status, a.calls_charged,
               (SELECT count(*) FROM v15.bindings b WHERE b.invoke_id = i.invoke_id AND b.name = 'out'),
               (SELECT payload->>'op' FROM v15.invoke_events e
                WHERE e.invoke_id = i.invoke_id AND e.event_class = 'audit'
                ORDER BY e.seq DESC LIMIT 1),
               (SELECT h.repl_exception->>'code' FROM v15.repl_history h
                WHERE h.invoke_id = i.invoke_id AND h.iteration = 0)
        FROM v15.invokes i
        JOIN v15.statements s0 ON s0.invoke_id = i.invoke_id AND s0.stmt_index = 0
        JOIN v15.statements s1 ON s1.invoke_id = i.invoke_id AND s1.stmt_index = 1
        JOIN v15.iterations it0 ON it0.invoke_id = i.invoke_id AND it0.iteration = 0
        JOIN v15.iterations it1 ON it1.invoke_id = i.invoke_id AND it1.iteration = 1
        JOIN v15.tool_requests r ON r.invoke_id = i.invoke_id
        JOIN v15.tool_attempts a ON a.request_id = r.request_id
        WHERE i.invoke_id = %s
        """,
        (iid,),
    )
    row = cur.fetchone()
    check(
        "ok=false wrap-up",
        row == (
            "runnable", False,
            "failed", "V15_TOOL_FAILED", "P1544",
            "skipped",
            "done", "continue",
            "pending",
            "failed", "settled", True,
            0,
            "tool_failed",
            "V15_TOOL_FAILED",
        ),
        row,
    )
    cur.execute(
        """
        SELECT phase FROM v15.invoke_events
        WHERE invoke_id = %s AND event_class = 'span' AND span = 'repl_exec' AND phase = 'exit'
        """,
        (iid,),
    )
    check("ok=false closes repl_exec", cur.fetchone()[0] == "exit")
    cur.execute(
        "SELECT calls_used FROM v15.budget_pools WHERE pool_id = %s",
        (pool_id,),
    )
    check("ok=false calls already 1", cur.fetchone()[0] == 1)

    cid, _ = seed_wait(
        admin, worker,
        extra=[("SELECT 1", "plain")],
        occupancy="out",
    )
    copened = begin_tool(worker, cid)
    mark_tool(worker, copened["attempt_id"])
    settle_tool(worker, copened["attempt_id"], {"ok": True, "value": {"x": 1}})
    cur.execute(
        """
        SELECT a.status, r.status, b.kind, b.provenance, b.value,
               s0.status, s0.error->>'code', s0.error->>'sqlstate',
               s1.status, i.status, i.fatal,
               (SELECT status FROM v15.iterations WHERE invoke_id = i.invoke_id AND iteration = 1)
        FROM v15.invokes i
        JOIN v15.statements s0 ON s0.invoke_id = i.invoke_id AND s0.stmt_index = 0
        JOIN v15.statements s1 ON s1.invoke_id = i.invoke_id AND s1.stmt_index = 1
        JOIN v15.tool_requests r ON r.invoke_id = i.invoke_id
        JOIN v15.tool_attempts a ON a.request_id = r.request_id
        JOIN v15.bindings b ON b.invoke_id = i.invoke_id AND b.name = 'out'
        WHERE i.invoke_id = %s
        """,
        (cid,),
    )
    row = cur.fetchone()
    check(
        "scope occupancy conflict",
        row[:4] == ("settled", "settled", "scope", "scope")
        and parse_json(row[4]) == {}
        and row[5:11] == ("failed", "V15_DELIVERY_CONFLICT", "P1527", "skipped", "runnable", False)
        and row[11] == "pending",
        row,
    )


def test_settle_errors(admin, worker) -> None:
    iid, _ = seed_wait(admin, worker)
    opened = begin_tool(worker, iid)
    expect(
        worker,
        "SELECT v15.v15_settle_tool(%s, 1, %s, %s)",
        (opened["attempt_id"], OWNER, Json({"ok": True, "value": {}})),
        "P1523",
        "settle before mark",
    )
    expect(
        worker,
        "SELECT v15.v15_mark_tool_started(%s, %s, %s)",
        (opened["attempt_id"], 99, OWNER),
        "P1501",
        "mark wrong fence",
    )
    mark_tool(worker, opened["attempt_id"])
    expect(
        worker,
        "SELECT v15.v15_settle_tool(%s, %s, %s, %s)",
        (opened["attempt_id"], 99, OWNER, Json({"ok": True, "value": {}})),
        "P1501",
        "settle wrong fence",
    )
    expect(
        worker,
        "SELECT v15.v15_settle_tool(%s, 1, %s, %s)",
        (opened["attempt_id"], OWNER, Json({"ok": True, "value": {}, "extra": 1})),
        "P1524",
        "extra result keys",
    )
    cur = admin.cursor()
    cur.execute(
        "SELECT status, call_started, result IS NULL FROM v15.tool_attempts WHERE attempt_id = %s",
        (opened["attempt_id"],),
    )
    check("bad shape keeps leased", cur.fetchone() == ("leased", True, True))
    settle_tool(worker, opened["attempt_id"], {"ok": True, "value": {"k": 1}})
    expect(
        worker,
        "SELECT v15.v15_settle_tool(%s, 1, %s, %s)",
        (opened["attempt_id"], OWNER, Json({"ok": True, "value": {}})),
        "P1502",
        "duplicate settle",
    )


def test_reclaim_homomorphism(admin, worker) -> None:
    cur = admin.cursor()
    iid = str(uuid.uuid4())
    seed_invoke(cur, iid, [("SELECT 1", "plain")], leased=True)
    cur.execute(
        "UPDATE v15.statements SET status = 'running' WHERE invoke_id = %s",
        (iid,),
    )
    cur.execute(
        """
        UPDATE v15.invokes
        SET lease_until = clock_timestamp() - interval '1 second'
        WHERE invoke_id = %s
        """,
        (iid,),
    )
    admin.commit()
    n = call(worker, "SELECT v15.v15_reclaim_expired()")
    worker.commit()
    check("lease reclaim returns 0", n == 0, n)
    cur.execute(
        """
        SELECT v.status, v.fence, s.status, s.error IS NULL,
               (SELECT count(*) FROM v15.invoke_events e
                WHERE e.invoke_id = v.invoke_id AND e.phase = 'retry'),
               (SELECT payload->>'op' FROM v15.invoke_events e
                WHERE e.invoke_id = v.invoke_id AND e.event_class = 'audit'
                ORDER BY e.seq DESC LIMIT 1)
        FROM v15.invokes v
        JOIN v15.statements s ON s.invoke_id = v.invoke_id
        WHERE v.invoke_id = %s
        """,
        (iid,),
    )
    check(
        "running statement repaired",
        cur.fetchone() == ("runnable", 2, "pending", True, 0, "lease_reclaimed"),
    )

    pool_id = make_pool(cur)
    lid = str(uuid.uuid4())
    seed_invoke(cur, lid, [], leased=True, pool_id=pool_id)
    cur.execute(
        "UPDATE v15.budget_pools SET calls_reserved = 1 WHERE pool_id = %s",
        (pool_id,),
    )
    cur.execute(
        """
        INSERT INTO v15.llm_requests (
          request_id, invoke_id, iteration, status, logical_digest
        ) VALUES (gen_random_uuid(), %s, 0, 'open', md5('llm-homomorphism'))
        RETURNING request_id
        """,
        (lid,),
    )
    req = cur.fetchone()[0]
    att = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO v15.llm_attempts (
          attempt_id, request_id, n, status, fence, lease_owner, lease_until,
          pool_id, reserved_calls, reserved_cost, call_started, calls_charged, request
        ) VALUES (
          %s, %s, 1, 'leased', 1, %s, clock_timestamp() - interval '1 second',
          %s, 1, 0, true, false, jsonb_build_object('attempt_id', %s::text, 'messages', '[]'::jsonb)
        )
        """,
        (att, req, OWNER, pool_id, att),
    )
    admin.commit()
    n = call(worker, "SELECT v15.v15_reclaim_expired()")
    worker.commit()
    check("llm marked-homomorphism count", n == 1, n)
    cur.execute(
        """
        SELECT a.status, a.call_started, a.calls_charged,
               p.calls_used, p.calls_reserved,
               i.status, i.fence
        FROM v15.llm_attempts a
        JOIN v15.budget_pools p ON p.pool_id = a.pool_id
        JOIN v15.llm_requests r ON r.request_id = a.request_id
        JOIN v15.invokes i ON i.invoke_id = r.invoke_id
        WHERE a.attempt_id = %s
        """,
        (att,),
    )
    row = cur.fetchone()
    check(
        "llm marked reclaim terminals",
        row == ("unknown", True, True, 1, 0, "runnable", 2),
        row,
    )

    wait_id, _ = seed_wait(admin, worker)
    try:
        admin.cursor().execute("SELECT v15.v15_io_reclaim_invoke(%s)", (wait_id,))
        admin.rollback()
        check("reclaim_invoke tool_wait", False, "returned instead of P1523")
    except psycopg2.Error as exc:
        admin.rollback()
        check("reclaim_invoke tool_wait P1523", exc.pgcode == "P1523", exc.pgcode)
    cur.execute(
        """
        SELECT i.status, s.status, r.status
        FROM v15.invokes i
        JOIN v15.statements s ON s.invoke_id = i.invoke_id AND s.stmt_index = 0
        JOIN v15.tool_requests r ON r.invoke_id = i.invoke_id
        WHERE i.invoke_id = %s
        """,
        (wait_id,),
    )
    check(
        "reclaim_invoke did not knock wait back",
        cur.fetchone() == ("tool_wait", "running", "open"),
    )


class Script:
    def __init__(self, replies: list) -> None:
        self.replies = list(replies)
        self.calls = []

    def complete(self, logical_digest: str, n: int, request: dict, llm_config=None) -> dict:
        self.calls.append((logical_digest, n, request))
        if not self.replies:
            raise AssertionError("script exhausted at n=" + str(n))
        return {"content": self.replies.pop(0)}


class SpyTool:
    def __init__(self, admin, inner=None) -> None:
        self.admin = admin
        self.inner = inner or FakeTool()
        self.shots = []

    def call(self, tool_name: str, args):
        self.admin.rollback()
        cur = self.admin.cursor()
        cur.execute(
            """
            SELECT i.invoke_id::text, i.status, a.call_started, a.status,
                   (SELECT json_agg(json_build_object(
                      'idx', s.stmt_index, 'status', s.status, 'kind', s.kind
                    ) ORDER BY s.stmt_index)
                    FROM v15.statements s
                    WHERE s.invoke_id = i.invoke_id AND s.iteration = r.iteration),
                   (SELECT count(*) FROM v15.invokes c WHERE c.parent_invoke_id = i.invoke_id),
                   (SELECT coalesce(json_agg(e.phase ORDER BY e.seq), '[]'::json)
                    FROM v15.invoke_events e
                    WHERE e.invoke_id = i.invoke_id
                      AND e.event_class = 'span'
                      AND e.span = 'repl_exec')
            FROM v15.tool_attempts a
            JOIN v15.tool_requests r ON r.request_id = a.request_id
            JOIN v15.invokes i ON i.invoke_id = r.invoke_id
            WHERE a.status = 'leased'
            ORDER BY a.n
            """
        )
        row = cur.fetchone()
        self.admin.commit()
        self.shots.append(
            {
                "invoke_id": row[0],
                "status": row[1],
                "call_started": row[2],
                "attempt_status": row[3],
                "statements": parse_json(row[4]) or [],
                "children": row[5],
                "repl_exec": parse_json(row[6]) or [],
                "tool_name": tool_name,
            }
        )
        return self.inner.call(tool_name, args)


def system_text() -> str:
    return render_system(recursion_available=True, bindings=[])


def open_invoke(conn, invoke_id: str, *, pool_id=None, user=None) -> None:
    cur = conn.cursor()
    cur.execute("SET LOCAL lock_timeout = '2s'")
    cur.execute(
        """
        SELECT v15.v15_open_invoke(%s, %s, NULL, '[]'::jsonb, %s, NULL, %s, %s)
        """,
        (invoke_id, SCOPE, pool_id, system_text(), user),
    )
    conn.commit()


def test_worker_loop_and_replay(server) -> None:
    setup_db()
    admin = connect(server)
    worker = connect(server, "v15_worker")
    admin.autocommit = False
    worker.autocommit = False
    RET = 'SELECT jaz."return"(\'{"ok":true}\'::jsonb);'
    BIND_RET = (
        "SELECT jaz.bind_tool('out','fake_search','{}'::jsonb);\n"
        'SELECT jaz."return"(jaz.var(\'out\'));'
    )
    TWO = (
        "SELECT jaz.bind_tool('a','fake_search','{}'::jsonb);\n"
        "SELECT jaz.bind_tool('b','fake_search','{}'::jsonb);\n"
        "SELECT jaz.\"return\"(jsonb_build_object('a', jaz.var('a'), 'b', jaz.var('b')));"
    )
    MIX = (
        "SELECT jaz.bind_tool('out','fake_search','{}'::jsonb);\n"
        "SELECT jaz.bind_invoke('kid', '{}'::jsonb);\n"
        'SELECT jaz."return"(jaz.var(\'kid\'));'
    )
    CHILD = 'SELECT jaz."return"(\'{"from":"kid"}\'::jsonb);'
    SYNC = "SELECT jaz.tool('echo_tool', '{}'::jsonb);\n" + RET
    EXT = "SELECT jaz.tool('fake_search', '{}'::jsonb);\n" + RET
    FAIL_SQL = (
        "SELECT jaz.bind_tool('out','fake_search','{}'::jsonb);\n"
        "SELECT 1;\n" + RET
    )
    try:
        cur = admin.cursor()
        pool_id = make_pool(cur)
        admin.commit()
        iid = str(uuid.uuid4())
        open_invoke(worker, iid, pool_id=pool_id)
        grant_catalog_tool(cur, iid, "fake_search")
        admin.commit()
        spy = SpyTool(admin)
        script = Script([BIND_RET])
        run_until_quiescent(server.get_uri(DB), script, OWNER, faketool=spy)
        admin.rollback()
        check("FakeTool called once", len(spy.shots) == 1, spy.shots)
        shot = spy.shots[0]
        check("FakeTool after mark", shot["call_started"] is True and shot["attempt_status"] == "leased")
        check("FakeTool sees tool_wait", shot["status"] == "tool_wait")
        check("no child during tool", shot["children"] == 0)
        check(
            "repl_exec enter without exit",
            "enter" in shot["repl_exec"] and "exit" not in shot["repl_exec"],
            shot["repl_exec"],
        )
        kinds = [(s["idx"], s["status"], s["kind"]) for s in shot["statements"]]
        check(
            "running bind_tool no second running",
            kinds[0] == (0, "running", "bind_tool")
            and all(s["status"] != "running" for s in shot["statements"][1:]),
            kinds,
        )
        cur.execute(
            """
            SELECT i.status, i.parent_invoke_id, i.fence,
                   b.kind, b.provenance, b.show_in_prompt,
                   (SELECT count(*) FROM v15.invokes c WHERE c.parent_invoke_id = i.invoke_id),
                   (SELECT count(*) FROM v15.llm_requests r WHERE r.invoke_id = i.invoke_id AND r.iteration = 0),
                   (SELECT count(*) FROM v15.repl_history h WHERE h.invoke_id = i.invoke_id),
                   s.child_invoke_id
            FROM v15.invokes i
            JOIN v15.bindings b ON b.invoke_id = i.invoke_id AND b.name = 'out'
            JOIN v15.statements s ON s.invoke_id = i.invoke_id AND s.stmt_index = 0 AND s.iteration = 0
            WHERE i.invoke_id = %s
            """,
            (iid,),
        )
        row = cur.fetchone()
        check(
            "worker delivery",
            row[0] == "completed"
            and row[1] is None
            and row[3:6] == ("var", "delivery", True)
            and row[6] == 0
            and row[7] == 1
            and row[9] is None,
            row,
        )
        cur.execute(
            """
            SELECT span, phase FROM v15.invoke_events
            WHERE invoke_id = %s AND event_class = 'span' AND span = 'repl_exec'
            ORDER BY seq
            """,
            (iid,),
        )
        repl = cur.fetchall()
        check(
            "repl_exec has enter",
            ("repl_exec", "enter") in repl,
            repl,
        )
        cur.execute(
            """
            SELECT event_class, span, payload->>'op'
            FROM v15.invoke_events WHERE invoke_id = %s
            """,
            (iid,),
        )
        events = cur.fetchall()
        spans = {row[1] for row in events if row[0] == "span"}
        ops = {row[2] for row in events if row[0] == "audit" and row[2]}
        check("no new span names", spans <= {"invoke", "llm_query", "repl_exec"}, spans)
        check(
            "tool audit ops",
            {"tool_suspend", "attempt_leased", "call_started", "deliver"} <= ops,
            ops,
        )
        expect(
            worker,
            "SELECT v15.v15_replay_export(%s)",
            (iid,),
            "P1524",
            "export bind_tool tree",
        )

        two_id = str(uuid.uuid4())
        two_pool = make_pool(cur, calls_limit=10)
        admin.commit()
        open_invoke(worker, two_id, pool_id=two_pool)
        grant_catalog_tool(cur, two_id, "fake_search")
        admin.commit()
        spy2 = SpyTool(admin)
        script2 = Script([TWO])
        run_until_quiescent(server.get_uri(DB), script2, OWNER, faketool=spy2)
        admin.rollback()
        check("two FakeTool calls", len(spy2.shots) == 2, spy2.shots)
        first, second = spy2.shots
        first_stmts = {s["idx"]: s for s in first["statements"]}
        check(
            "first wait second not running",
            first_stmts[0]["status"] == "running"
            and first_stmts[1]["status"] != "running",
            first_stmts,
        )
        check("no new llm between tools", len(script2.calls) == 1, script2.calls)
        cur.execute(
            """
            SELECT count(*) FILTER (WHERE kind = 'assistant'),
                   (SELECT count(*) FROM v15.llm_requests WHERE invoke_id = %s),
                   (SELECT count(*) FROM v15.tool_attempts a
                    JOIN v15.tool_requests r ON r.request_id = a.request_id
                    WHERE r.invoke_id = %s AND a.calls_charged),
                   (SELECT count(*) FROM v15.bindings WHERE invoke_id = %s AND name IN ('a','b') AND kind = 'var')
            FROM v15.llm_messages WHERE invoke_id = %s
            """,
            (two_id, two_id, two_id, two_id),
        )
        row = cur.fetchone()
        check("two vars one request calls+2", row == (1, 1, 2, 2), row)

        mix_id = str(uuid.uuid4())
        open_invoke(worker, mix_id)
        grant_catalog_tool(cur, mix_id, "fake_search")
        admin.commit()
        spy3 = SpyTool(admin)
        run_until_quiescent(
            server.get_uri(DB), Script([MIX, CHILD]), OWNER, faketool=spy3
        )
        admin.rollback()
        check("mix FakeTool once", len(spy3.shots) == 1, spy3.shots)
        check("tool segment no tree edge", spy3.shots[0]["children"] == 0)
        check("tool segment is tool_wait", spy3.shots[0]["status"] == "tool_wait")
        cur.execute(
            """
            SELECT i.status,
                   (SELECT count(*) FROM v15.invokes c WHERE c.parent_invoke_id = i.invoke_id),
                   (SELECT status FROM v15.invokes c WHERE c.parent_invoke_id = i.invoke_id),
                   EXISTS (
                     SELECT 1 FROM v15.invokes p
                     JOIN v15.invokes c ON c.parent_invoke_id = p.invoke_id
                     WHERE p.invoke_id = i.invoke_id AND p.status = 'tool_wait'
                   )
            FROM v15.invokes i WHERE i.invoke_id = %s
            """,
            (mix_id,),
        )
        row = cur.fetchone()
        check(
            "after mix parent completed one child",
            row[0] == "completed" and row[1] == 1 and row[3] is False,
            row,
        )

        boom_id = str(uuid.uuid4())
        open_invoke(worker, boom_id)
        grant_catalog_tool(cur, boom_id, "fake_search")
        admin.commit()

        class Boom:
            def call(self, tool_name, args):
                raise RuntimeError("boom")

        run_until_quiescent(
            server.get_uri(DB), Script([FAIL_SQL, RET]), OWNER, faketool=Boom()
        )
        admin.rollback()
        cur.execute(
            """
            SELECT s.error->>'code', s.error->>'sqlstate',
                   (SELECT count(*) FROM v15.bindings WHERE invoke_id = %s AND name = 'out'),
                   (SELECT count(*) FROM v15.tool_attempts a
                    JOIN v15.tool_requests r ON r.request_id = a.request_id
                    WHERE r.invoke_id = %s AND a.status = 'leased'),
                   (SELECT status FROM v15.statements WHERE invoke_id = %s AND stmt_index = 1 AND iteration = 0),
                   (SELECT status FROM v15.iterations WHERE invoke_id = %s AND iteration = 1),
                   i.status
            FROM v15.invokes i
            JOIN v15.statements s ON s.invoke_id = i.invoke_id AND s.stmt_index = 0 AND s.iteration = 0
            WHERE i.invoke_id = %s
            """,
            (boom_id, boom_id, boom_id, boom_id, boom_id),
        )
        row = cur.fetchone()
        check(
            "FakeTool exception P1544",
            row[:6] == ("V15_TOOL_FAILED", "P1544", 0, 0, "skipped", "pending")
            or row[:5] == ("V15_TOOL_FAILED", "P1544", 0, 0, "skipped"),
            row,
        )
        check("no leaked leased attempt", row[3] == 0, row)
        cur.execute(
            """
            SELECT payload->>'op'
            FROM v15.invoke_events
            WHERE invoke_id = %s AND event_class = 'audit'
            """,
            (boom_id,),
        )
        boom_ops = {r[0] for r in cur.fetchall() if r[0]}
        check("boom tool_failed op", "tool_failed" in boom_ops, boom_ops)
        check(
            "no on_phase family",
            not any((op or "").startswith("on_phase") for op in boom_ops),
            boom_ops,
        )

        echo_id = str(uuid.uuid4())
        open_invoke(worker, echo_id)
        register_sync_tool(server, cur, "echo_tool")
        grant_catalog_tool(cur, echo_id, "echo_tool")
        admin.commit()
        run_until_quiescent(server.get_uri(DB), Script([SYNC]), OWNER)
        admin.rollback()
        cur.execute(
            """
            SELECT i.status,
                   (SELECT count(*) FROM v15.tool_attempts a
                    JOIN v15.tool_requests r ON r.request_id = a.request_id
                    WHERE r.invoke_id = %s)
            FROM v15.invokes i WHERE i.invoke_id = %s
            """,
            (echo_id, echo_id),
        )
        check("sync jaz.tool no attempts", cur.fetchone() == ("completed", 0))

        ext_id = str(uuid.uuid4())
        open_invoke(worker, ext_id)
        grant_catalog_tool(cur, ext_id, "fake_search")
        admin.commit()
        run_until_quiescent(server.get_uri(DB), Script([EXT, RET]), OWNER)
        admin.rollback()
        cur.execute(
            """
            SELECT s.error->>'code', s.error->>'sqlstate', s.error->>'message',
                   (SELECT count(*) FROM v15.tool_attempts a
                    JOIN v15.tool_requests r ON r.request_id = a.request_id
                    WHERE r.invoke_id = %s)
            FROM v15.statements s
            WHERE s.invoke_id = %s AND s.iteration = 0 AND s.stmt_index = 0
            """,
            (ext_id, ext_id),
        )
        row = cur.fetchone()
        check(
            "sync external=true",
            row is not None
            and row[3] == 0
            and (
                row[0] == "V15_EXTERNAL_TOOL"
                or row[1] == "P1517"
                or (row[2] or "").startswith("V15_EXTERNAL_TOOL")
            ),
            row,
        )

        occ_id = str(uuid.uuid4())
        open_invoke(worker, occ_id)
        grant_catalog_tool(cur, occ_id, "fake_search")
        cur.execute(
            """
            INSERT INTO v15.bindings (
              invoke_id, name, kind, value, show_in_prompt, provenance
            ) VALUES (%s, 'out', 'scope', '{}'::jsonb, true, 'scope')
            """,
            (occ_id,),
        )
        admin.commit()
        spy_occ = SpyTool(admin)
        occ_script = Script([
            "SELECT jaz.bind_tool('out','fake_search','{}'::jsonb);\n"
            "SELECT 1;\n" + RET
        ])
        occ_worker = Worker(
            server.get_uri(DB), occ_script, OWNER, faketool=spy_occ
        )
        try:
            occ_worker.reclaim()
            occ_worker.drive_tools()
            fence = occ_worker.claim(occ_id)
            occ_worker.drive(occ_id, fence)
            occ_worker.reclaim()
            occ_worker.drive_tools()
        finally:
            occ_worker.close()
        admin.rollback()
        check("occupancy FakeTool called", len(spy_occ.shots) == 1, spy_occ.shots)
        cur.execute(
            """
            SELECT a.status, r.status, b.kind, b.provenance, b.value,
                   s0.status, s0.error->>'code', s0.error->>'sqlstate',
                   s1.status, i.status, i.fatal,
                   (SELECT status FROM v15.iterations
                    WHERE invoke_id = i.invoke_id AND iteration = 1)
            FROM v15.invokes i
            JOIN v15.statements s0
              ON s0.invoke_id = i.invoke_id AND s0.iteration = 0 AND s0.stmt_index = 0
            JOIN v15.statements s1
              ON s1.invoke_id = i.invoke_id AND s1.iteration = 0 AND s1.stmt_index = 1
            JOIN v15.tool_requests r ON r.invoke_id = i.invoke_id
            JOIN v15.tool_attempts a ON a.request_id = r.request_id
            JOIN v15.bindings b ON b.invoke_id = i.invoke_id AND b.name = 'out'
            WHERE i.invoke_id = %s
            """,
            (occ_id,),
        )
        row = cur.fetchone()
        check(
            "worker occupancy conflict",
            row is not None
            and row[:4] == ("settled", "settled", "scope", "scope")
            and parse_json(row[4]) == {}
            and row[5:11]
            == ("failed", "V15_DELIVERY_CONFLICT", "P1527", "skipped", "runnable", False)
            and row[11] == "pending",
            row,
        )

        wait_id, _ = seed_wait(admin, worker)
        expect(
            worker,
            "SELECT v15.v15_replay_export(%s)",
            (wait_id,),
            "P1524",
            "export tool_wait",
        )
    finally:
        worker.close()
        admin.close()


def main() -> int:
    test_load_order()
    test_classifier()
    test_no_socket()
    setup_db()
    server = get_server()
    admin = connect(server)
    worker = connect(server, "v15_worker")
    try:
        admin.autocommit = False
        worker.autocommit = False
        test_shape(admin.cursor())
        admin.commit()
        test_store_statements(admin)
        test_suspend_paths(server, admin, worker)
        test_direct_bind_tool(server, admin, worker)
        test_success_delivery(admin, worker)
        test_reclaim_tool(admin, worker)
        test_exhausted_and_budget(admin, worker)
        test_ok_false_and_conflict(admin, worker)
        test_settle_errors(admin, worker)
        test_reclaim_homomorphism(admin, worker)
    finally:
        worker.close()
        admin.close()
    test_worker_loop_and_replay(server)
    print("[ok] v15 tools slice 1-9")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
