"""Stage 2 gate: jaz wrappers, definer bodies, and model-facing views.

Run: uv run python v15/namespace/test_namespace.py  (exit 0 = pass)
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
from v15.namespace.setup_db import DB, main as setup_db

WRAPPERS = (
    "var", "assign", "print", "tool", "return", "raise", "bind_invoke", "prior_history",
)
DEFINERS = (
    "jaz_var", "jaz_assign", "jaz_print", "jaz_tool", "jaz_return", "jaz_raise",
    "jaz_bind_invoke", "jaz_prior_history",
)
A = "00000000-0000-0000-0000-0000000000a1"
B = "00000000-0000-0000-0000-0000000000b1"
ROOT_ID = "00000000-0000-0000-0000-0000000000c1"
MID = "00000000-0000-0000-0000-0000000000c2"
LEAF = "00000000-0000-0000-0000-0000000000c3"


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
          status, fatal, recursion_available, resolved_config, config_digest,
          manifest_digest, scratch_schema, fence, created_at, updated_at
        ) VALUES (
          %s, %s, %s, %s, %s,
          'runnable', false, true, '{}'::jsonb, 'cfg',
          'md', %s, 1, clock_timestamp(), clock_timestamp()
        )
        """,
        (
            invoke_id,
            parent,
            kw.get("parent_iteration"),
            kw.get("root", invoke_id),
            kw.get("depth", 1),
            kw.get("scratch", scratch_for(invoke_id)),
        ),
    )


def insert_iteration(cur, invoke_id: str, iteration: int, status: str = "executing") -> None:
    result = "continue" if status == "done" else None
    cur.execute(
        """
        INSERT INTO v15.iterations (
          invoke_id, iteration, status, result_kind, capture
        ) VALUES (%s, %s, %s, %s, '')
        """,
        (invoke_id, iteration, status, result),
    )


def insert_statement(cur, invoke_id: str, iteration: int, kind: str, status: str = "running") -> None:
    sql = f"SELECT jaz.{kind}"
    bind = "child" if kind == "bind_invoke" else None
    cur.execute(
        """
        INSERT INTO v15.statements (
          invoke_id, iteration, stmt_index, sql, sql_digest, kind, bind_name, status
        ) VALUES (%s, %s, 0, %s, md5(%s), %s, %s, %s)
        """,
        (invoke_id, iteration, sql, sql, kind, bind, status),
    )


def point_exec(cur, pid: int, invoke_id: str, iteration: int = 0) -> None:
    cur.execute(
        """
        INSERT INTO v15.exec_context (
          backend_pid, invoke_id, iteration, stmt_index, scratch_schema
        ) VALUES (%s, %s, %s, 0, %s)
        ON CONFLICT (backend_pid) DO UPDATE
        SET invoke_id = EXCLUDED.invoke_id,
            iteration = EXCLUDED.iteration,
            stmt_index = EXCLUDED.stmt_index,
            scratch_schema = EXCLUDED.scratch_schema,
            revision = v15.exec_context.revision + 1
        """,
        (pid, invoke_id, iteration, scratch_for(invoke_id)),
    )


def fn_oid(cur, nsp: str, name: str):
    cur.execute(
        """
        SELECT p.oid
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = %s AND p.proname = %s
        """,
        (nsp, name),
    )
    row = cur.fetchone()
    if row is None:
        raise AssertionError(f"missing function {nsp}.{name}")
    return row[0]


def install_tool(cur, name: str, body: str, external: bool, language: str = "sql") -> str:
    role = "v15_tool_" + name
    cur.execute(
        "SELECT 1 FROM pg_roles WHERE rolname = %s",
        (role,),
    )
    if cur.fetchone() is None:
        cur.execute(
            f"CREATE ROLE {role} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT"
        )
    fn = f"public.ns_{name}"
    if language == "sql":
        cur.execute(
            f"""
            CREATE FUNCTION {fn}(p jsonb) RETURNS jsonb
            LANGUAGE sql STABLE SECURITY DEFINER
            SET search_path = pg_catalog
            AS $fn$ {body} $fn$
            """
        )
    else:
        cur.execute(
            f"""
            CREATE FUNCTION {fn}(p jsonb) RETURNS jsonb
            LANGUAGE plpgsql STABLE SECURITY DEFINER
            SET search_path = pg_catalog
            AS $fn$ {body} $fn$
            """
        )
    cur.execute(f"ALTER FUNCTION {fn}(jsonb) OWNER TO {role}")
    cur.execute(f"REVOKE ALL ON FUNCTION {fn}(jsonb) FROM PUBLIC")
    cur.execute(f"REVOKE ALL ON FUNCTION {fn}(jsonb) FROM {role}")
    cur.execute(f"GRANT EXECUTE ON FUNCTION {fn}(jsonb) TO v15_owner")
    cur.execute("SELECT oid FROM pg_proc WHERE proname = %s", (f"ns_{name}",))
    oid = cur.fetchone()[0]
    cur.execute("SELECT v15.v15_handler_digest(%s)", (oid,))
    digest = cur.fetchone()[0]
    tool_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO v15.tool_catalog (
          tool_id, name, arg_schema, handler, description, external, handler_digest
        ) VALUES (%s, %s, '{}'::jsonb, %s, %s, %s, %s)
        """,
        (tool_id, name, oid, name, external, digest),
    )
    return tool_id


def bind_tool(cur, invoke_id: str, name: str, tool_id: str, grant: bool = True) -> None:
    cur.execute(
        """
        INSERT INTO v15.bindings (
          invoke_id, name, kind, value, tool_id, show_in_prompt, provenance
        ) VALUES (%s, %s, 'tool', '{}'::jsonb, %s, false, 'explicit')
        """,
        (invoke_id, name, tool_id),
    )
    if grant:
        cur.execute(
            "INSERT INTO v15.tool_grants (invoke_id, tool_id) VALUES (%s, %s)",
            (invoke_id, tool_id),
        )


def test_shape(cur) -> None:
    cur.execute("SHOW server_version_num")
    check("PG 18.4", cur.fetchone()[0] == "180004")
    cur.execute(
        """
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'v15' AND c.relkind = 'r'
        """
    )
    check("no new tables", len(cur.fetchall()) == 21)
    cur.execute(
        """
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'jaz' AND c.relkind = 'v'
        ORDER BY 1
        """
    )
    check("views", [r[0] for r in cur.fetchall()] == ["history", "request_messages"])
    for name in WRAPPERS:
        cur.execute(
            """
            SELECT p.prosecdef, p.provolatile, l.lanname, p.proconfig,
                   pg_get_userbyid(p.proowner),
                   has_function_privilege('v15_repl', p.oid, 'EXECUTE'),
                   has_function_privilege('v15_worker', p.oid, 'EXECUTE'),
                   has_function_privilege('v15_owner', p.oid, 'EXECUTE'),
                   has_function_privilege('public', p.oid, 'EXECUTE'),
                   p.prosrc
            FROM pg_proc p
            JOIN pg_namespace n ON n.oid = p.pronamespace
            JOIN pg_language l ON l.oid = p.prolang
            WHERE n.nspname = 'jaz' AND p.proname = %s
            """,
            (name,),
        )
        row = cur.fetchone()
        check(f"wrapper {name}", row is not None)
        prosecdef, vol, lang, cfg, owner, repl, worker, own, public, src = row
        check(f"wrapper {name} invoker", prosecdef is False and vol == "v" and lang == "plpgsql")
        check(f"wrapper {name} owner", owner == "v15_owner")
        check(f"wrapper {name} search_path", cfg == ["search_path=pg_catalog"])
        check(f"wrapper {name} execute", (repl, worker, own, public) == (True, False, False, False))
        check(f"wrapper {name} no set role", "SET ROLE" not in src.upper())
    for name in DEFINERS:
        cur.execute(
            """
            SELECT p.prosecdef, p.provolatile, l.lanname, p.proconfig,
                   pg_get_userbyid(p.proowner),
                   has_function_privilege('v15_repl', p.oid, 'EXECUTE'),
                   has_function_privilege('v15_worker', p.oid, 'EXECUTE'),
                   has_function_privilege('v15_owner', p.oid, 'EXECUTE'),
                   has_function_privilege('public', p.oid, 'EXECUTE'),
                   p.prosrc
            FROM pg_proc p
            JOIN pg_namespace n ON n.oid = p.pronamespace
            JOIN pg_language l ON l.oid = p.prolang
            WHERE n.nspname = 'v15' AND p.proname = %s
            """,
            (name,),
        )
        row = cur.fetchone()
        check(f"definer {name}", row is not None)
        prosecdef, vol, lang, cfg, owner, repl, worker, own, public, src = row
        check(f"definer {name} definer", prosecdef is True and vol == "v" and lang == "plpgsql")
        check(f"definer {name} owner", owner == "v15_owner" and cfg == ["search_path=pg_catalog"])
        check(f"definer {name} execute", (repl, worker, own, public) == (True, False, False, False))
        upper = src.upper()
        check(
            f"definer {name} no role switch",
            "SET ROLE" not in upper and "RESET ROLE" not in upper
            and "SET SESSION AUTHORIZATION" not in upper,
        )
    cur.execute(
        """
        SELECT c.relname, pg_get_userbyid(c.relowner), c.reloptions,
               has_table_privilege('v15_repl', c.oid, 'SELECT'),
               has_table_privilege('v15_worker', c.oid, 'SELECT'),
               has_table_privilege('public', c.oid, 'SELECT')
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'jaz' AND c.relkind = 'v'
        ORDER BY 1
        """
    )
    for name, owner, opts, repl, worker, public in cur.fetchall():
        opts = opts or []
        check(f"view {name} owner", owner == "v15_owner")
        check(f"view {name} barrier", "security_barrier=true" in opts, opts)
        check(f"view {name} invoker", "security_invoker=false" in opts, opts)
        check(f"view {name} select", (repl, worker, public) == (True, False, False))
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'jaz' AND table_name = 'history'
        ORDER BY ordinal_position
        """
    )
    check(
        "history columns",
        [r[0] for r in cur.fetchall()] == [
            "iteration", "llm_response", "repl_output", "repl_exception",
        ],
    )
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'jaz' AND table_name = 'request_messages'
        ORDER BY ordinal_position
        """
    )
    check(
        "request_messages columns",
        [r[0] for r in cur.fetchall()] == ["seq", "role", "kind", "content"],
    )
    cur.execute(
        """
        SELECT has_table_privilege('v15_repl', 'v15.repl_history', 'SELECT')
            OR has_table_privilege('v15_repl', 'v15.exec_context', 'INSERT')
            OR has_table_privilege('v15_repl', 'v15.exec_context', 'UPDATE')
            OR has_table_privilege('v15_worker', 'v15.exec_context', 'INSERT')
            OR has_table_privilege('v15_worker', 'v15.exec_context', 'UPDATE')
            OR has_table_privilege('v15_worker', 'v15.bindings', 'UPDATE')
        """
    )
    check("no direct dml", cur.fetchone()[0] is False)
    cur.execute(
        """
        SELECT has_table_privilege('v15_owner', 'v15.exec_context', 'INSERT')
           AND has_table_privilege('v15_owner', 'v15.exec_context', 'UPDATE')
        """
    )
    check("owner exec_context dml", cur.fetchone()[0] is True)


def test_behavior(server) -> None:
    owner = connect(server)
    owner.autocommit = True
    ocur = owner.cursor()
    worker = connect(server, "v15_worker")
    worker.autocommit = False
    wcur = worker.cursor()
    wcur.execute("SELECT pg_backend_pid()")
    pid = wcur.fetchone()[0]
    sup = connect(server)
    sup.autocommit = False
    scur = sup.cursor()
    fails(scur, "SELECT jaz.var('x')", code="P1522", label="superuser wrapper role")
    fails(wcur, "SELECT jaz.var('x')", code="42501", label="worker wrapper denied")
    fails(wcur, "SELECT v15.jaz_var('x')", code="42501", label="worker definer denied")
    wcur.execute("SET ROLE v15_repl")
    fails(wcur, "SELECT jaz.var('x')", code="P1523", label="missing exec wrapper")
    fails(wcur, "SELECT v15.jaz_var('x')", code="P1523", label="missing exec definer")
    fails(wcur, "SELECT * FROM jaz.history", code="P1523", label="history missing exec")
    fails(
        wcur, "SELECT * FROM jaz.request_messages", code="P1523",
        label="request_messages missing exec",
    )
    fails(wcur, "SELECT * FROM v15.repl_history", code="42501", label="repl no base select")
    insert_invoke(ocur, A)
    insert_iteration(ocur, A, 0)
    insert_statement(ocur, A, 0, "plain", status="pending")
    point_exec(ocur, pid, A, 0)
    fails(wcur, "SELECT jaz.var('x')", code="P1523", label="statement not running")
    ocur.execute(
        """
        UPDATE v15.statements SET status = 'running', revision = revision + 1
        WHERE invoke_id = %s
        """,
        (A,),
    )
    for kind, value, show, prov, rev in (
        ("input", "1", True, "explicit", 4),
        ("scope", "2", True, "scope", 5),
        ("var", "3", False, "delivery", 6),
    ):
        ocur.execute(
            """
            INSERT INTO v15.bindings (
              invoke_id, name, kind, value, show_in_prompt, provenance, revision
            ) VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s)
            """,
            (A, kind + "_n", kind, value, show, prov, rev),
        )
    echo_id = install_tool(
        ocur, "echo",
        "SELECT jsonb_build_object('who', current_user, 'args', p)",
        False,
    )
    bind_tool(ocur, A, "echo", echo_id)
    wcur.execute("SELECT jaz.var('input_n')::text, jaz.var('scope_n')::text, jaz.var('var_n')::text")
    check("var reads kinds", wcur.fetchone() == ("1", "2", "3"))
    fails(wcur, "SELECT jaz.var('echo')", code="P1524", label="var rejects tool")
    fails(wcur, "SELECT jaz.var('missing')", code="P1524", label="var missing")
    fails(wcur, "SELECT jaz.var('return')", code="P1524", label="var reserved")
    ocur.execute(
        "SELECT revision FROM v15.bindings WHERE invoke_id = %s AND name = 'var_n'",
        (A,),
    )
    check("var does not bump revision", ocur.fetchone()[0] == 6)
    wcur.execute("SELECT jaz.assign('fresh', '9'::jsonb)::text")
    check("assign returns value", wcur.fetchone()[0] == "9")
    worker.commit()
    ocur.execute(
        """
        SELECT kind, value::text, show_in_prompt, provenance, revision, tool_id IS NULL
        FROM v15.bindings WHERE invoke_id = %s AND name = 'fresh'
        """,
        (A,),
    )
    check("assign insert", ocur.fetchone() == ("var", "9", True, "repl", 0, True))
    wcur.execute("SELECT jaz.assign('var_n', '\"z\"'::jsonb)::text")
    check("assign update returns", wcur.fetchone()[0] == '"z"')
    wcur.execute("SELECT jaz.assign('Return', 'true'::jsonb)::text")
    check("assign Return", wcur.fetchone()[0] == "true")
    wcur.execute("SELECT jaz.assign('nil', 'null'::jsonb)::text")
    check("assign jsonb null", wcur.fetchone()[0] == "null")
    fails(wcur, "SELECT jaz.assign('input_n', '1'::jsonb)", code="P1524", label="assign input")
    fails(wcur, "SELECT jaz.assign('scope_n', '1'::jsonb)", code="P1524", label="assign scope")
    fails(wcur, "SELECT jaz.assign('echo', '{}'::jsonb)", code="P1524", label="assign tool")
    fails(wcur, "SELECT jaz.assign('return', '1'::jsonb)", code="P1524", label="assign reserved")
    fails(wcur, "SELECT jaz.assign('1bad', '1'::jsonb)", code="P1524", label="assign grammar")
    fails(wcur, "SELECT jaz.assign('x', NULL::jsonb)", code="P1524", label="assign sql null")
    worker.commit()
    ocur.execute(
        """
        SELECT kind, revision, show_in_prompt, provenance, value::text
        FROM v15.bindings WHERE invoke_id = %s AND name = 'input_n'
        """,
        (A,),
    )
    check("assign input unchanged", ocur.fetchone() == ("input", 4, True, "explicit", "1"))
    ocur.execute(
        """
        SELECT revision, show_in_prompt, provenance, value::text
        FROM v15.bindings WHERE invoke_id = %s AND name = 'var_n'
        """,
        (A,),
    )
    check("assign var revision", ocur.fetchone() == (7, False, "repl", '"z"'))
    wcur.execute("SELECT jaz.print('ab')")
    wcur.execute("SELECT jaz.print('c'), jaz.print('d')")
    worker.commit()
    ocur.execute(
        "SELECT capture, revision FROM v15.iterations WHERE invoke_id = %s AND iteration = 0",
        (A,),
    )
    check("print concat", ocur.fetchone() == ("abcd", 3))
    fails(wcur, "SELECT jaz.print(NULL)", code="P1524", label="print null")
    worker.commit()
    ocur.execute(
        "SELECT capture FROM v15.iterations WHERE invoke_id = %s AND iteration = 0",
        (A,),
    )
    check("print null leaves capture", ocur.fetchone()[0] == "abcd")
    fails(wcur, 'SELECT jaz."return"(\'1\'::jsonb)', code="P1503", label="return wrong kind")
    fails(wcur, 'SELECT jaz."raise"(\'no\')', code="P1503", label="raise wrong kind")
    ocur.execute(
        """
        UPDATE v15.statements SET kind = 'return', revision = revision + 1
        WHERE invoke_id = %s
        """,
        (A,),
    )
    fails(
        wcur, 'SELECT jaz."return"(\'1\'::jsonb)', code="P1515",
        label="print and return",
    )
    worker.commit()
    ocur.execute(
        "SELECT status, return_value IS NULL FROM v15.invokes WHERE invoke_id = %s",
        (A,),
    )
    check("print and return no write", ocur.fetchone() == ("runnable", True))
    ocur.execute(
        """
        UPDATE v15.iterations SET capture = '', revision = revision + 1
        WHERE invoke_id = %s AND iteration = 0
        """,
        (A,),
    )
    wcur.execute('SELECT jaz."return"(\'{"ok":true}\'::jsonb)::text')
    check("return value", wcur.fetchone()[0] == '{"ok": true}')
    fails(wcur, 'SELECT jaz."raise"(\'x\')', code="P1503", label="raise on return kind")
    fails(wcur, 'SELECT jaz."return"(NULL::jsonb)', code="P1524", label="return null")
    worker.commit()
    ocur.execute(
        "SELECT status, return_value::text FROM v15.invokes WHERE invoke_id = %s",
        (A,),
    )
    check("return stored", ocur.fetchone() == ("runnable", '{"ok": true}'))
    ocur.execute(
        """
        UPDATE v15.statements SET kind = 'raise', revision = revision + 1
        WHERE invoke_id = %s
        """,
        (A,),
    )
    fails(wcur, 'SELECT jaz."return"(\'1\'::jsonb)', code="P1503", label="return on raise kind")
    long_msg = "m" * 1025
    wcur.execute('SELECT jaz."raise"(%s)', (long_msg,))
    worker.commit()
    ocur.execute(
        """
        SELECT status, error->>'sqlstate', error->>'code',
               char_length(error->>'message'), left(error->>'message', 1)
        FROM v15.invokes WHERE invoke_id = %s
        """,
        (A,),
    )
    check("raise stored", ocur.fetchone() == ("runnable", "P1529", "V15_RAISE", 1024, "m"))
    ocur.execute(
        """
        UPDATE v15.iterations SET capture = 'x', revision = revision + 1
        WHERE invoke_id = %s AND iteration = 0
        """,
        (A,),
    )
    ocur.execute(
        """
        UPDATE v15.invokes SET error = NULL, revision = revision + 1
        WHERE invoke_id = %s
        """,
        (A,),
    )
    fails(wcur, 'SELECT jaz."raise"(\'again\')', code="P1515", label="print and raise")
    worker.commit()
    ocur.execute("SELECT error IS NULL, status FROM v15.invokes WHERE invoke_id = %s", (A,))
    check("print and raise no write", ocur.fetchone() == (True, "runnable"))
    fails(wcur, "SELECT jaz.bind_invoke('child', '{}'::jsonb)", code="P1503", label="bind_invoke")
    ocur.execute("SELECT count(*) FROM v15.invokes WHERE parent_invoke_id = %s", (A,))
    check("bind_invoke no child", ocur.fetchone()[0] == 0)
    ocur.execute(
        """
        UPDATE v15.statements
        SET kind = 'bind_invoke', bind_name = 'child', revision = revision + 1
        WHERE invoke_id = %s
        """,
        (A,),
    )
    fails(
        wcur, "SELECT jaz.bind_invoke('child', '{}'::jsonb)", code="P1503",
        label="bind_invoke on bind kind",
    )
    fails(wcur, "SELECT jaz.print('no')", code="P1503", label="print during bind eval")
    fails(wcur, "SELECT jaz.tool('echo', '{}'::jsonb)", code="P1503", label="tool during bind eval")
    worker.commit()
    ocur.execute(
        "SELECT capture FROM v15.iterations WHERE invoke_id = %s AND iteration = 0",
        (A,),
    )
    check("bind eval print rolled back", ocur.fetchone()[0] == "x")
    ocur.execute(
        """
        UPDATE v15.statements
        SET kind = 'plain', bind_name = NULL, revision = revision + 1
        WHERE invoke_id = %s
        """,
        (A,),
    )
    wcur.execute("SELECT jaz.tool('echo', '{\"n\":1}'::jsonb)::text")
    payload = json.loads(wcur.fetchone()[0])
    check("tool result", payload == {"who": "v15_tool_echo", "args": {"n": 1}})
    wcur.execute("SELECT current_user, session_user")
    check("tool returns to repl", wcur.fetchone() == ("v15_repl", "v15_worker"))
    fails(wcur, "SELECT jaz.tool('missing', '{}'::jsonb)", code="P1507", label="tool unauthorized")
    fails(wcur, "SELECT jaz.tool('echo', '[]'::jsonb)", code="P1524", label="tool args")
    ext_id = install_tool(
        ocur, "ext",
        "BEGIN RAISE EXCEPTION 'called' USING ERRCODE = 'XX000'; END",
        True,
        language="plpgsql",
    )
    bind_tool(ocur, A, "ext", ext_id)
    fails(wcur, "SELECT jaz.tool('ext', '{}'::jsonb)", code="P1517", label="external tool")
    boom_id = install_tool(
        ocur, "boom",
        "BEGIN RAISE EXCEPTION 'boom' USING ERRCODE = '22000'; END",
        False,
        language="plpgsql",
    )
    bind_tool(ocur, A, "boom", boom_id)
    fails(wcur, "SELECT jaz.tool('boom', '{}'::jsonb)", code="P1525", label="handler failed")
    passthrough_id = install_tool(
        ocur, "pass",
        "BEGIN RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524'; END",
        False,
        language="plpgsql",
    )
    bind_tool(ocur, A, "pass", passthrough_id)
    fails(wcur, "SELECT jaz.tool('pass', '{}'::jsonb)", code="P1524", label="handler v15 passthrough")
    insert_invoke(ocur, B)
    insert_iteration(ocur, B, 0, status="done")
    insert_iteration(ocur, B, 1)
    insert_statement(ocur, B, 1, "plain")
    ocur.execute(
        """
        INSERT INTO v15.repl_history (
          invoke_id, iteration, llm_response, repl_output, repl_exception
        ) VALUES (%s, 0, 'b-llm', 'b-out', '{"code":"B"}'::jsonb)
        """,
        (B,),
    )
    insert_iteration(ocur, A, 1, status="done")
    ocur.execute(
        """
        INSERT INTO v15.repl_history (
          invoke_id, iteration, llm_response, repl_output
        ) VALUES (%s, 1, 'a-llm', 'a-out')
        """,
        (A,),
    )
    wcur.execute(
        "SELECT iteration, llm_response, repl_output FROM jaz.history ORDER BY iteration"
    )
    check("history own rows", wcur.fetchall() == [(1, "a-llm", "a-out")])
    ocur.execute(
        """
        CREATE FUNCTION public.v15_ns_leak(p integer) RETURNS boolean
        LANGUAGE plpgsql AS $fn$
        BEGIN
          IF p = 0 THEN
            RAISE EXCEPTION 'leaked';
          END IF;
          RETURN true;
        END;
        $fn$
        """
    )
    ocur.execute("GRANT EXECUTE ON FUNCTION public.v15_ns_leak(integer) TO v15_repl")
    wcur.execute(
        "SELECT iteration FROM jaz.history WHERE public.v15_ns_leak(iteration) ORDER BY iteration"
    )
    check("history barrier", wcur.fetchall() == [(1,)])
    point_exec(ocur, pid, B, 1)
    wcur.execute("SELECT iteration, repl_output FROM jaz.history ORDER BY iteration")
    check("history other invoke", wcur.fetchall() == [(0, "b-out")])
    for iid, parent, depth in (
        (ROOT_ID, None, 1),
        (MID, ROOT_ID, 2),
        (LEAF, MID, 3),
    ):
        insert_invoke(
            ocur, iid, parent=parent,
            parent_iteration=0 if parent else None,
            root=ROOT_ID, depth=depth,
        )
        insert_iteration(ocur, iid, 0, status="done")
        insert_iteration(ocur, iid, 1)
        insert_statement(ocur, iid, 1, "plain")
        ocur.execute(
            """
            INSERT INTO v15.repl_history (
              invoke_id, iteration, llm_response, repl_output
            ) VALUES (%s, 0, %s, %s)
            """,
            (iid, iid[-2:] + "-llm", iid[-2:] + "-out"),
        )
    point_exec(ocur, pid, LEAF, 1)
    wcur.execute("SELECT repl_output FROM jaz.prior_history(%s::uuid)", (LEAF,))
    check("prior self", wcur.fetchall() == [("c3-out",)])
    wcur.execute("SELECT repl_output FROM jaz.prior_history(%s::uuid)", (MID,))
    check("prior parent", wcur.fetchall() == [("c2-out",)])
    wcur.execute("SELECT repl_output FROM jaz.prior_history(%s::uuid)", (ROOT_ID,))
    check("prior root", wcur.fetchall() == [("c1-out",)])
    fails(wcur, "SELECT * FROM jaz.prior_history(%s::uuid)", (A,), code="P1510", label="prior unrelated")
    fails(wcur, "SELECT * FROM jaz.prior_history(NULL)", code="P1510", label="prior null")
    point_exec(ocur, pid, ROOT_ID, 1)
    fails(
        wcur, "SELECT * FROM jaz.prior_history(%s::uuid)", (LEAF,),
        code="P1510", label="prior descendant",
    )
    empty = "00000000-0000-0000-0000-0000000000e1"
    insert_invoke(ocur, empty, parent=ROOT_ID, parent_iteration=0, root=ROOT_ID, depth=2)
    insert_iteration(ocur, empty, 1)
    insert_statement(ocur, empty, 1, "plain")
    point_exec(ocur, pid, empty, 1)
    wcur.execute("SELECT count(*) FROM jaz.prior_history(%s::uuid)", (empty,))
    check("prior self empty", wcur.fetchone()[0] == 0)
    wcur.execute("SELECT count(*) FROM jaz.history")
    check("history empty invoke", wcur.fetchone()[0] == 0)
    req = str(uuid.uuid4())
    ocur.execute(
        """
        INSERT INTO v15.llm_requests (
          request_id, invoke_id, iteration, status, logical_digest
        ) VALUES (%s, %s, 1, 'settled', 'dig')
        """,
        (req, A),
    )
    def add_attempt(n, status, content, started, charged):
        ocur.execute(
            """
            INSERT INTO v15.llm_attempts (
              attempt_id, request_id, n, status, fence, call_started, calls_charged, request
            ) VALUES (
              %s, %s, %s, %s, 1, %s, %s,
              jsonb_build_object(
                'attempt_id', %s::text,
                'messages', jsonb_build_array(
                  jsonb_build_object(
                    'seq', 0, 'message_id', 'm', 'role', 'user',
                    'kind', 'transient_hook', 'content', %s
                  )
                )
              )
            )
            """,
            (str(uuid.uuid4()), req, n, status, started, charged, str(uuid.uuid4()), content),
        )
    add_attempt(1, "settled", "old", True, True)
    add_attempt(2, "leased", "leased", False, False)
    point_exec(ocur, pid, A, 0)
    wcur.execute("SELECT count(*) FROM jaz.request_messages")
    check("request other iteration empty", wcur.fetchone()[0] == 0)
    point_exec(ocur, pid, A, 1)
    wcur.execute("SELECT seq, role, kind, content FROM jaz.request_messages ORDER BY seq")
    check("request max settled", wcur.fetchall() == [(0, "user", "transient_hook", "old")])
    add_attempt(3, "settled", "new", True, True)
    wcur.execute("SELECT content FROM jaz.request_messages")
    check("request later settled", wcur.fetchone()[0] == "new")
    point_exec(ocur, pid, B, 1)
    wcur.execute("SELECT count(*) FROM jaz.request_messages")
    check("request other invoke empty", wcur.fetchone()[0] == 0)
    ocur.execute("DELETE FROM v15.exec_context WHERE backend_pid = %s", (pid,))
    fails(wcur, "SELECT * FROM jaz.history", code="P1523", label="history after delete")
    fails(wcur, "SELECT jaz.var('fresh')", code="P1523", label="var after delete")
    wcur.execute("RESET ROLE")
    worker.commit()
    worker.close()
    owner.close()
    sup.close()


def main() -> int:
    server = get_server()
    setup_db()
    conn = connect(server)
    conn.autocommit = False
    cur = conn.cursor()
    test_shape(cur)
    conn.rollback()
    conn.close()
    test_behavior(server)
    print("[ready] namespace gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
