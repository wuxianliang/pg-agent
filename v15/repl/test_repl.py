"""Stage 5 gate: one statement per transaction, scratch grants, tools.

Run: uv run python v15/repl/test_repl.py  (exit 0 = pass)
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import psycopg2
from psycopg2 import sql as psql
from psycopg2.extras import Json

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v15.protocol.split_sql import classify_statement, sql_without_timeout_pragma
from v15.repl.setup_db import DB, main as setup_db

OWNER = "repl-owner"
FENCE = 2
KEYS = ["kind", "scratch_schema", "statement_fence", "timeout_ms"]
V15_NAME = {
    "P1503": "V15_INVOKE_FORM",
    "P1512": "V15_DDL",
    "P1515": "V15_PRINT_AND_RETURN",
    "P1517": "V15_EXTERNAL_TOOL",
    "P1523": "V15_INVALID_TRANSITION",
    "P1524": "V15_VALUE_INVALID",
    "P1525": "V15_HANDLER_FAILED",
    "P1526": "V15_STATEMENT_TIMEOUT",
    "P1537": "V15_HANDLER_SHAPE",
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


def scratch_for(invoke_id: str) -> str:
    return "s_" + invoke_id.replace("-", "")


def parse_json(value):
    if isinstance(value, str):
        return json.loads(value)
    return value


def err_of(exc: psycopg2.Error) -> dict:
    line = (str(exc).splitlines() or [""])[0][:1024]
    return {
        "sqlstate": exc.pgcode,
        "code": V15_NAME.get(exc.pgcode, exc.pgcode),
        "message": line,
    }


def seed(cur, invoke_id: str, statements: list, timeout_ms: int | None = 30000, ceiling: int = 30000) -> str:
    scratch = scratch_for(invoke_id)
    cur.execute(
        psql.SQL("CREATE SCHEMA {} AUTHORIZATION v15_owner").format(psql.Identifier(scratch))
    )
    resolved = {} if timeout_ms is None else {"repl": {"timeout_ms": timeout_ms}}
    cur.execute(
        """
        INSERT INTO v15.invokes (
          invoke_id, parent_invoke_id, parent_iteration, root_invoke_id, depth,
          status, fatal, recursion_available, resolved_config, config_digest,
          manifest_digest, scratch_schema, fence, lease_owner, lease_until,
          created_at, updated_at
        ) VALUES (
          %s, NULL, NULL, %s, 1,
          'leased', false, true, %s, 'cfg',
          'md', %s, %s, %s, clock_timestamp() + interval '10 minutes',
          clock_timestamp(), clock_timestamp()
        )
        """,
        (invoke_id, invoke_id, Json(resolved), scratch, FENCE, OWNER),
    )
    cur.execute(
        """
        INSERT INTO v15.iterations (invoke_id, iteration, status, resume_stmt, capture)
        VALUES (%s, 0, 'executing', 0, '')
        """,
        (invoke_id,),
    )
    for index, spec in enumerate(statements):
        sql_text, kind = spec[0], spec[1]
        bind = spec[2] if len(spec) > 2 else None
        cur.execute(
            """
            INSERT INTO v15.statements (
              invoke_id, iteration, stmt_index, sql, sql_digest, kind, bind_name, status
            ) VALUES (%s, 0, %s, %s, md5(%s), %s, %s, 'pending')
            """,
            (invoke_id, index, sql_text, sql_text, kind, bind),
        )
    cur.execute(
        """
        INSERT INTO v15.invoke_hooks (
          invoke_id, ordinal, hook_def_id, channel, config, state
        )
        SELECT %s, 0, d.hook_def_id, 'baseline',
               jsonb_build_object('max', %s), '{}'::jsonb
        FROM v15.hook_defs d
        WHERE d.hook_key = 'governance_statement'
        """,
        (invoke_id, ceiling),
    )
    return scratch


def begin_exec(conn, invoke_id: str) -> None:
    cur = conn.cursor()
    cur.execute("SET LOCAL lock_timeout = '2s'")
    cur.execute("SET LOCAL statement_timeout = '30s'")
    cur.execute(
        "SELECT v15.v15_begin_exec(%s, %s, %s)",
        (invoke_id, FENCE, OWNER),
    )
    conn.commit()


def fail_statement(conn, invoke_id: str, index: int, error: dict) -> None:
    cur = conn.cursor()
    cur.execute("SET LOCAL lock_timeout = '2s'")
    cur.execute("SET LOCAL statement_timeout = '30s'")
    cur.execute(
        "SELECT v15.v15_fail_statement(%s, %s, %s, %s, %s)",
        (invoke_id, FENCE, OWNER, index, Json(error)),
    )
    conn.commit()


def prepare_only(conn, invoke_id: str, index: int):
    cur = conn.cursor()
    cur.execute("SET LOCAL lock_timeout = '2s'")
    cur.execute("SHOW search_path")
    before = cur.fetchone()[0]
    cur.execute("SELECT current_user, session_user")
    who_before = cur.fetchone()
    cur.execute(
        "SELECT v15.v15_prepare_statement(%s, %s, %s, %s)",
        (invoke_id, FENCE, OWNER, index),
    )
    info = parse_json(cur.fetchone()[0])
    cur.execute("SHOW search_path")
    after = cur.fetchone()[0]
    cur.execute("SELECT current_user, session_user")
    who_after = cur.fetchone()
    check("prepare leaves search_path", before == after, (before, after))
    check("prepare leaves role", who_before == who_after == ("v15_worker", "v15_worker"), who_after)
    check("prepare keys", sorted(info) == KEYS, sorted(info))
    return info, cur


def arm(cur, info: dict) -> None:
    ms = int(info["timeout_ms"]) + 1000
    cur.execute(
        psql.SQL("SET LOCAL search_path TO {}, pg_catalog").format(
            psql.Identifier(info["scratch_schema"])
        )
    )
    cur.execute(f"SET LOCAL statement_timeout = '{ms}ms'")
    cur.execute("SAVEPOINT model_stmt")
    cur.execute("SET LOCAL ROLE v15_repl")


def finish_ok(conn, cur, invoke_id: str, index: int, info: dict) -> None:
    cur.execute("RESET ROLE")
    cur.execute("RELEASE SAVEPOINT model_stmt")
    cur.execute(
        """
        SELECT v15.v15_complete_statement(%s, %s, %s, %s, %s, 'done', NULL)
        """,
        (invoke_id, FENCE, OWNER, index, int(info["statement_fence"])),
    )
    conn.commit()


def finish_fail(conn, cur, invoke_id: str, index: int, info: dict, exc: psycopg2.Error) -> dict:
    cur.execute("ROLLBACK TO SAVEPOINT model_stmt")
    cur.execute("RESET ROLE")
    error = err_of(exc)
    cur.execute(
        """
        SELECT v15.v15_complete_statement(%s, %s, %s, %s, %s, 'failed', %s)
        """,
        (invoke_id, FENCE, OWNER, index, int(info["statement_fence"]), Json(error)),
    )
    conn.commit()
    return error


def run_sql(conn, invoke_id: str, index: int, sql_text: str):
    info, cur = prepare_only(conn, invoke_id, index)
    arm(cur, info)
    try:
        cur.execute(sql_text)
        rows = cur.fetchall() if cur.description else None
    except psycopg2.Error as exc:
        if exc.pgcode == "57014":
            raise
        error = finish_fail(conn, cur, invoke_id, index, info, exc)
        return info, error, None
    finish_ok(conn, cur, invoke_id, index, info)
    return info, None, rows


def schema_priv(cur, schema: str):
    cur.execute(
        """
        SELECT has_schema_privilege('v15_repl', %s, 'USAGE'),
               has_schema_privilege('v15_repl', %s, 'CREATE')
        """,
        (schema, schema),
    )
    return cur.fetchone()


def grant_rows(cur, schema: str):
    cur.execute(
        """
        SELECT a.privilege_type, a.is_grantable
        FROM pg_namespace n
        CROSS JOIN LATERAL aclexplode(n.nspacl) a
        JOIN pg_roles r ON r.oid = a.grantee
        WHERE n.nspname = %s AND r.rolname = 'v15_repl'
        ORDER BY 1
        """,
        (schema,),
    )
    return cur.fetchall()


def stmt_row(cur, invoke_id: str, index: int):
    cur.execute(
        """
        SELECT status, error, error_sqlstate
        FROM v15.statements
        WHERE invoke_id = %s AND iteration = 0 AND stmt_index = %s
        """,
        (invoke_id, index),
    )
    return cur.fetchone()


def ensure_role(server, role: str) -> None:
    conn = connect(server)
    conn.autocommit = True
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
        if cur.fetchone() is None:
            cur.execute(
                psql.SQL(
                    "CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT"
                ).format(psql.Identifier(role))
            )
    finally:
        conn.close()


def install_handler(server, cur, name: str, body: str, language: str = "sql", volatility: str = "STABLE") -> int:
    role = "v15_tool_" + name
    ensure_role(server, role)
    fn = f"repl_{name}"
    cur.execute(
        psql.SQL(
            """
            CREATE FUNCTION public.{}(p jsonb) RETURNS jsonb
            LANGUAGE {} {} SECURITY DEFINER
            SET search_path = pg_catalog
            AS $fn$ {} $fn$
            """
        ).format(
            psql.Identifier(fn),
            psql.SQL(language),
            psql.SQL(volatility),
            psql.SQL(body),
        )
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
    return cur.fetchone()[0]


def register_tool(cur, name: str, oid: int, external: bool = False) -> str:
    cur.execute(
        "SELECT v15.v15_register_tool(%s, %s, %s, '{}'::jsonb, %s)",
        (name, oid, name, external),
    )
    return str(cur.fetchone()[0])


def bind_tool(cur, invoke_id: str, name: str, tool_id: str) -> None:
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


def test_shape(cur) -> None:
    cur.execute("SHOW server_version_num")
    check("PG 18.4", cur.fetchone()[0] == "180004")
    cur.execute(
        """
        SELECT count(*)
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'v15' AND c.relkind = 'r'
        """
    )
    check("no new tables", cur.fetchone()[0] == 21)
    do = classify_statement("DO $$ BEGIN PERFORM 1; END $$;")
    check("DO rejected before exec", do.reject_code == "V15_DIALECT", do.reject_code)
    trunc = classify_statement("TRUNCATE t")
    check("TRUNCATE rejected before exec", trunc.reject_code == "V15_DIALECT", trunc.reject_code)
    cur.execute(
        """
        SELECT p.proname, p.prosecdef, p.provolatile, p.proconfig,
               pg_get_userbyid(p.proowner),
               has_function_privilege('v15_worker', p.oid, 'EXECUTE'),
               has_function_privilege('v15_repl', p.oid, 'EXECUTE'),
               has_function_privilege('public', p.oid, 'EXECUTE'),
               p.prosrc
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'v15'
          AND p.proname IN (
            'v15_begin_exec', 'v15_prepare_statement', 'v15_complete_statement',
            'v15_fail_statement', 'v15_register_tool'
          )
        ORDER BY 1
        """
    )
    rows = cur.fetchall()
    check("five entry points", len(rows) == 5, [r[0] for r in rows])
    for name, defin, vol, cfg, owner, worker, repl, public, src in rows:
        low = src.lower()
        check(
            f"{name} definer",
            defin is True and vol == "v" and owner == "v15_owner"
            and cfg == ["search_path=pg_catalog"],
            (defin, vol, owner, cfg),
        )
        check(f"{name} execute", worker is True and repl is False and public is False)
        check(
            f"{name} no role switch",
            "set role" not in low and "reset role" not in low
            and "set session authorization" not in low and "set_config" not in low,
        )
    cur.execute(
        """
        SELECT p.prosrc
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'v15' AND p.proname = 'v15_repl_grant_scratch'
        """
    )
    grant_src = cur.fetchone()[0].lower()
    check("schema grant only", "on schema" in grant_src and "on table" not in grant_src)


def test_holder(server, scur) -> None:
    invoke_id = "00000000-0000-0000-0000-00000000051b"
    seed(scur, invoke_id, [("SELECT 1", "plain")])
    scur.connection.commit()
    wconn = connect(server, "v15_worker")
    try:
        cur = wconn.cursor()
        cur.execute("SET LOCAL lock_timeout = '2s'")
        cur.execute("SET LOCAL statement_timeout = '30s'")
        try:
            cur.execute(
                "SELECT v15.v15_begin_exec(%s, %s, %s)",
                (invoke_id, FENCE + 1, OWNER),
            )
        except psycopg2.Error as exc:
            wconn.rollback()
            check("stale fence", exc.pgcode == "P1501", exc.pgcode)
        else:
            raise AssertionError("stale fence did not fail")
        cur = wconn.cursor()
        cur.execute("SET LOCAL lock_timeout = '2s'")
        cur.execute("SET LOCAL statement_timeout = '30s'")
        try:
            cur.execute(
                "SELECT v15.v15_begin_exec(%s, %s, %s)",
                (invoke_id, FENCE, "other-owner"),
            )
        except psycopg2.Error as exc:
            wconn.rollback()
            check("wrong owner", exc.pgcode == "P1523", exc.pgcode)
        else:
            raise AssertionError("wrong owner did not fail")
        begin_exec(wconn, invoke_id)
        cur = wconn.cursor()
        cur.execute("SET LOCAL lock_timeout = '2s'")
        cur.execute("SET LOCAL statement_timeout = '30s'")
        try:
            cur.execute(
                "SELECT v15.v15_begin_exec(%s, %s, %s)",
                (invoke_id, FENCE, OWNER),
            )
        except psycopg2.Error as exc:
            wconn.rollback()
            check("second begin_exec", exc.pgcode == "P1523", exc.pgcode)
        else:
            raise AssertionError("second begin_exec did not fail")
    finally:
        wconn.close()
    scur.execute(
        """
        UPDATE v15.invokes
        SET lease_until = clock_timestamp() - interval '1 second'
        WHERE invoke_id = %s
        """,
        (invoke_id,),
    )
    scur.connection.commit()
    wconn = connect(server, "v15_worker")
    try:
        cur = wconn.cursor()
        cur.execute("SET LOCAL lock_timeout = '2s'")
        cur.execute("SET LOCAL statement_timeout = '30s'")
        try:
            cur.execute(
                "SELECT v15.v15_prepare_statement(%s, %s, %s, 0)",
                (invoke_id, FENCE, OWNER),
            )
        except psycopg2.Error as exc:
            wconn.rollback()
            check("expired lease", exc.pgcode == "P1523", exc.pgcode)
        else:
            raise AssertionError("expired lease did not fail")
    finally:
        wconn.close()


def test_scratch(server, scur) -> None:
    invoke_id = "00000000-0000-0000-0000-000000000511"
    stored = "-- timeout: 2.5\nCREATE TABLE t (n int)"
    scratch = seed(
        scur,
        invoke_id,
        [
            (stored, "plain"),
            ("INSERT INTO t VALUES (7)", "plain"),
            ("SELECT n FROM t", "plain"),
            (
                "WITH RECURSIVE c(n) AS ("
                "SELECT 1 UNION ALL SELECT n + 1 FROM c WHERE n < 3"
                ") SELECT max(n) FROM c",
                "plain",
            ),
            ("DROP TABLE t", "plain"),
        ],
    )
    scur.connection.commit()
    check("committed has no usage", schema_priv(scur, scratch) == (False, False))
    wconn = connect(server, "v15_worker")
    try:
        begin_exec(wconn, invoke_id)
        scur.execute(
            """
            SELECT phase FROM v15.invoke_events
            WHERE invoke_id = %s AND span = 'repl_exec'
            ORDER BY seq
            """,
            (invoke_id,),
        )
        check("enter then send", [r[0] for r in scur.fetchall()] == ["enter", "send"])
        info, cur = prepare_only(wconn, invoke_id, 0)
        check("pragma timeout", int(info["timeout_ms"]) == 2500, info["timeout_ms"])
        check("kind plain", info["kind"] == "plain" and info["scratch_schema"] == scratch)
        check("usage and create", schema_priv(cur, scratch) == (True, True))
        check("no grant option", grant_rows(cur, scratch) == [("CREATE", False), ("USAGE", False)])
        check("sibling usage denied", schema_priv(cur, "repl_sibling") == (False, False))
        arm(cur, info)
        cur.execute("SAVEPOINT sib")
        try:
            cur.execute("CREATE TABLE repl_sibling.x (n int)")
            raise AssertionError("sibling create should fail")
        except psycopg2.Error as exc:
            check("sibling create rejected", exc.pgcode in ("42501", "P1512"), exc.pgcode)
            cur.execute("ROLLBACK TO SAVEPOINT sib")
        cur.execute("SAVEPOINT cfg")
        try:
            cur.execute("SELECT set_config('search_path', 'pg_catalog', true)")
            raise AssertionError("set_config should fail")
        except psycopg2.Error as exc:
            check("repl cannot set_config", exc.pgcode == "42501", exc.pgcode)
            cur.execute("ROLLBACK TO SAVEPOINT cfg")
        cur.execute(sql_without_timeout_pragma(stored))
        if cur.description:
            cur.fetchall()
        finish_ok(wconn, cur, invoke_id, 0, info)
    finally:
        wconn.close()
    check("revoke after complete", schema_priv(scur, scratch) == (False, False))
    scur.execute(
        """
        SELECT n.nspname, pg_get_userbyid(c.relowner), c.relacl::text
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relname = 't' AND n.nspname = %s
        """,
        (scratch,),
    )
    row = scur.fetchone()
    check("table in scratch owned by repl", row == (scratch, "v15_repl", None), row)
    wconn = connect(server, "v15_worker")
    try:
        info, err, rows = run_sql(wconn, invoke_id, 1, "INSERT INTO t VALUES (7)")
        check("insert committed", err is None, err)
        info, err, rows = run_sql(wconn, invoke_id, 2, "SELECT n FROM t")
        check("select row", err is None and rows == [(7,)], rows)
        recursive = (
            "WITH RECURSIVE c(n) AS ("
            "SELECT 1 UNION ALL SELECT n + 1 FROM c WHERE n < 3"
            ") SELECT max(n) FROM c"
        )
        info, err, rows = run_sql(wconn, invoke_id, 3, recursive)
        check("with recursive", err is None and rows == [(3,)], rows)
        info, err, rows = run_sql(wconn, invoke_id, 4, "DROP TABLE t")
        check("drop table", err is None, err)
    finally:
        wconn.close()
    scur.execute(
        "SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = %s AND c.relname = 't'",
        (scratch,),
    )
    check("dropped", scur.fetchone() is None)
    wconn = connect(server, "v15_worker")
    try:
        cur = wconn.cursor()
        cur.execute("SET LOCAL lock_timeout = '2s'")
        try:
            cur.execute(
                "SELECT v15.v15_prepare_statement(%s, %s, %s, 0)",
                (invoke_id, FENCE, OWNER),
            )
        except psycopg2.Error as exc:
            wconn.rollback()
            check("done is not re-executed", exc.pgcode == "P1523", exc.pgcode)
        else:
            raise AssertionError("replay prepare should fail")
    finally:
        wconn.close()


def test_assign_print(server, scur) -> None:
    invoke_id = "00000000-0000-0000-0000-000000000512"
    seed(
        scur,
        invoke_id,
        [
            ("SELECT jaz.assign('answer', '42'::jsonb)", "assign"),
            ("SELECT jaz.print('hello')", "print"),
            ("SELECT jaz.print('!')", "print"),
        ],
    )
    scur.connection.commit()
    wconn = connect(server, "v15_worker")
    try:
        begin_exec(wconn, invoke_id)
        info, err, _rows = run_sql(
            wconn, invoke_id, 0, "SELECT jaz.assign('answer', '42'::jsonb)"
        )
        check("assign ok", err is None, err)
        info, err, _rows = run_sql(wconn, invoke_id, 1, "SELECT jaz.print('hello')")
        check("print ok", err is None, err)
        info, err, _rows = run_sql(wconn, invoke_id, 2, "SELECT jaz.print('!')")
        check("print append ok", err is None, err)
    finally:
        wconn.close()
    scur.execute(
        """
        SELECT kind, value::text, revision, show_in_prompt
        FROM v15.bindings
        WHERE invoke_id = %s AND name = 'answer'
        """,
        (invoke_id,),
    )
    check("assign binding", scur.fetchone() == ("var", "42", 0, True))
    scur.execute(
        "SELECT capture FROM v15.iterations WHERE invoke_id = %s AND iteration = 0",
        (invoke_id,),
    )
    check("print capture", scur.fetchone()[0] == "hello!")


def test_return_raise(server, scur) -> None:
    ret_id = "00000000-0000-0000-0000-000000000513"
    seed(
        scur,
        ret_id,
        [
            ('SELECT jaz."return"(\'1\'::jsonb)', "return"),
            ("SELECT 1", "plain"),
        ],
    )
    raise_id = "00000000-0000-0000-0000-000000000514"
    seed(
        scur,
        raise_id,
        [
            ("SELECT jaz.\"raise\"('nope')", "raise"),
            ("SELECT 1", "plain"),
        ],
    )
    scur.connection.commit()
    wconn = connect(server, "v15_worker")
    try:
        begin_exec(wconn, ret_id)
        info, err, _rows = run_sql(wconn, ret_id, 0, "SELECT jaz.\"return\"('1'::jsonb)")
        check("quoted return", err is None, err)
    finally:
        wconn.close()
    scur.execute(
        """
        SELECT i.status, i.return_value::text, it.resume_stmt, it.status
        FROM v15.invokes i
        JOIN v15.iterations it ON it.invoke_id = i.invoke_id AND it.iteration = 0
        WHERE i.invoke_id = %s
        """,
        (ret_id,),
    )
    check("return staged", scur.fetchone() == ("leased", "1", 2, "executing"))
    status, error, _sqlstate = stmt_row(scur, ret_id, 1)
    check("return successor not skipped", status == "pending" and error is None, status)
    wconn = connect(server, "v15_worker")
    try:
        begin_exec(wconn, raise_id)
        info, err, _rows = run_sql(wconn, raise_id, 0, "SELECT jaz.\"raise\"('nope')")
        check("quoted raise", err is None, err)
    finally:
        wconn.close()
    scur.execute(
        """
        SELECT status, error->>'code', error->>'sqlstate', fatal
        FROM v15.invokes WHERE invoke_id = %s
        """,
        (raise_id,),
    )
    check("raise staged", scur.fetchone() == ("leased", "V15_RAISE", "P1529", False))
    scur.execute(
        "SELECT resume_stmt FROM v15.iterations WHERE invoke_id = %s AND iteration = 0",
        (raise_id,),
    )
    check("raise resume at count", scur.fetchone()[0] == 2)
    status, error, _sqlstate = stmt_row(scur, raise_id, 1)
    check("raise successor not skipped", status == "pending" and error is None, status)


def test_print_and_return(server, scur) -> None:
    invoke_id = "00000000-0000-0000-0000-000000000515"
    seed(
        scur,
        invoke_id,
        [
            ("SELECT jaz.print('kept')", "print"),
            ("SELECT jaz.\"return\"('1'::jsonb)", "return"),
            ("SELECT 1", "plain"),
        ],
    )
    scur.connection.commit()
    wconn = connect(server, "v15_worker")
    try:
        begin_exec(wconn, invoke_id)
        info, err, _rows = run_sql(wconn, invoke_id, 0, "SELECT jaz.print('kept')")
        check("prior print", err is None, err)
        info, err, _rows = run_sql(
            wconn, invoke_id, 1, "SELECT jaz.\"return\"('1'::jsonb)"
        )
        check("print and return failed", err is not None and err["code"] == "V15_PRINT_AND_RETURN", err)
        check("print and return sqlstate", err["sqlstate"] == "P1515")
    finally:
        wconn.close()
    scur.execute(
        """
        SELECT status, return_value IS NULL, fatal
        FROM v15.invokes WHERE invoke_id = %s
        """,
        (invoke_id,),
    )
    check("invoke not terminal", scur.fetchone() == ("leased", True, False))
    scur.execute(
        "SELECT capture, resume_stmt FROM v15.iterations WHERE invoke_id = %s",
        (invoke_id,),
    )
    check("capture kept", scur.fetchone() == ("kept", 1))
    status, error, sqlstate = stmt_row(scur, invoke_id, 1)
    check("return row failed", status == "failed" and sqlstate == "P1515", (status, sqlstate))
    status, error, _sqlstate = stmt_row(scur, invoke_id, 0)
    check("prior print done", status == "done")
    status, error, _sqlstate = stmt_row(scur, invoke_id, 2)
    check("later not skipped", status == "pending" and error is None, status)


def test_tools(server, scur) -> None:
    invoke_id = "00000000-0000-0000-0000-000000000516"
    scratch = scratch_for(invoke_id)
    echo = install_handler(
        server,
        scur,
        "echo",
        "SELECT jsonb_build_object('user', current_user, 'n', p->'n')",
    )
    boom = install_handler(
        server,
        scur,
        "boom",
        "BEGIN RAISE EXCEPTION 'boom'; END;",
        language="plpgsql",
    )
    ext = install_handler(server, scur, "ext", "SELECT jsonb_build_object('called', true)")
    writer = install_handler(
        server,
        scur,
        "writer",
        "BEGIN EXECUTE 'INSERT INTO v15.invokes (invoke_id) VALUES (NULL)'; "
        "RETURN '{}'::jsonb; END;",
        language="plpgsql",
    )
    side_scratch = scratch_for("00000000-0000-0000-0000-000000000520")
    side = install_handler(
        server,
        scur,
        "side",
        f"BEGIN EXECUTE 'CREATE TABLE {side_scratch}.tool_side (n int)'; "
        "RETURN '{}'::jsonb; END;",
        language="plpgsql",
    )
    bad = install_handler(server, scur, "badvol", "SELECT p", volatility="VOLATILE")
    scur.connection.commit()
    try:
        scur.execute(
            "SELECT v15.v15_register_tool('badvol', %s, 'badvol', '{}'::jsonb, false)",
            (bad,),
        )
        raise AssertionError("volatile register should fail")
    except psycopg2.Error as exc:
        scur.connection.rollback()
        check("volatile register", exc.pgcode == "P1537", exc.pgcode)
    echo_id = register_tool(scur, "echo", echo)
    boom_id = register_tool(scur, "boom", boom)
    ext_id = register_tool(scur, "ext", ext, external=True)
    writer_id = register_tool(scur, "writer", writer)
    side_id = register_tool(scur, "side", side)
    seed(scur, invoke_id, [("SELECT jaz.tool('echo', '{\"n\":1}'::jsonb)", "plain")])
    bind_tool(scur, invoke_id, "echo", echo_id)
    scur.connection.commit()
    scur.execute(
        "SELECT has_function_privilege('v15_repl', %s, 'EXECUTE')",
        (echo,),
    )
    check("repl has no handler execute", scur.fetchone()[0] is False)
    wconn = connect(server, "v15_worker")
    try:
        begin_exec(wconn, invoke_id)
        info, cur = prepare_only(wconn, invoke_id, 0)
        arm(cur, info)
        cur.execute("SELECT jaz.tool('echo', '{\"n\":1}'::jsonb)")
        payload = parse_json(cur.fetchone()[0])
        check("handler current_user", payload["user"] == "v15_tool_echo", payload)
        check("handler args", payload["n"] == 1, payload)
        cur.execute("SELECT current_user, session_user")
        check("model user after tool", cur.fetchone() == ("v15_repl", "v15_worker"))
        scur.execute(
            "SELECT has_function_privilege('v15_repl', %s, 'EXECUTE')",
            (echo,),
        )
        check("still no handler execute", scur.fetchone()[0] is False)
        finish_ok(wconn, cur, invoke_id, 0, info)
    finally:
        wconn.close()
    cases = (
        ("00000000-0000-0000-0000-00000000051d", "ext", ext_id, "SELECT jaz.tool('ext', '{}'::jsonb)", "V15_EXTERNAL_TOOL"),
        ("00000000-0000-0000-0000-00000000051e", "boom", boom_id, "SELECT jaz.tool('boom', '{}'::jsonb)", "V15_HANDLER_FAILED"),
        ("00000000-0000-0000-0000-00000000051f", "writer", writer_id, "SELECT jaz.tool('writer', '{}'::jsonb)", "V15_HANDLER_FAILED"),
        ("00000000-0000-0000-0000-000000000520", "side", side_id, "SELECT jaz.tool('side', '{}'::jsonb)", "V15_HANDLER_FAILED"),
    )
    for case_id, name, tool_id, sql_text, code in cases:
        seed(scur, case_id, [(sql_text, "plain")])
        bind_tool(scur, case_id, name, tool_id)
        scur.connection.commit()
        wconn = connect(server, "v15_worker")
        try:
            begin_exec(wconn, case_id)
            _info, err, _rows = run_sql(wconn, case_id, 0, sql_text)
        finally:
            wconn.close()
        check(name, err is not None and err["code"] == code, err)
        scur.execute("SELECT status FROM v15.invokes WHERE invoke_id = %s", (case_id,))
        check(f"{name} not terminal", scur.fetchone()[0] == "leased")
    scur.execute(
        """
        SELECT count(*)
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND pg_get_userbyid(c.relowner) LIKE 'v15_tool_%%'
        """,
        (scratch,),
    )
    check("tool owns no scratch table", scur.fetchone()[0] == 0)
    scur.execute(
        "SELECT status FROM v15.invokes WHERE invoke_id = %s",
        (invoke_id,),
    )
    check("tool failure is not terminal", scur.fetchone()[0] == "leased")


def test_bind_invoke(server, scur) -> None:
    invoke_id = "00000000-0000-0000-0000-000000000517"
    scratch = seed(
        scur,
        invoke_id,
        [("SELECT jaz.bind_invoke('child', '{}'::jsonb)", "bind_invoke", "child")],
    )
    scur.connection.commit()
    before = None
    scur.execute("SELECT count(*) FROM v15.invokes")
    before = scur.fetchone()[0]
    wconn = connect(server, "v15_worker")
    try:
        begin_exec(wconn, invoke_id)
        info, cur = prepare_only(wconn, invoke_id, 0)
        check("bind kind", info["kind"] == "bind_invoke")
        check("usage only", schema_priv(cur, scratch) == (True, False))
        check("usage not grantable", grant_rows(cur, scratch) == [("USAGE", False)])
        arm(cur, info)
        try:
            cur.execute("SELECT jaz.bind_invoke('child', '{}'::jsonb)")
            if cur.description:
                cur.fetchall()
            raise AssertionError("bind_invoke should fail")
        except psycopg2.Error as exc:
            check("bind_invoke form", exc.pgcode == "P1503", exc.pgcode)
            finish_fail(wconn, cur, invoke_id, 0, info, exc)
    finally:
        wconn.close()
    scur.execute("SELECT count(*) FROM v15.invokes")
    check("no child row", scur.fetchone()[0] == before)
    scur.execute(
        "SELECT child_invoke_id FROM v15.statements WHERE invoke_id = %s",
        (invoke_id,),
    )
    check("no child id", scur.fetchone()[0] is None)
    check("bind revoke", schema_priv(scur, scratch) == (False, False))


def test_illegal_pragma(server, scur) -> None:
    invoke_id = "00000000-0000-0000-0000-00000000051c"
    seed(scur, invoke_id, [("-- timeout: 0\nSELECT 1", "plain")])
    scur.connection.commit()
    wconn = connect(server, "v15_worker")
    try:
        begin_exec(wconn, invoke_id)
        cur = wconn.cursor()
        cur.execute("SET LOCAL lock_timeout = '2s'")
        try:
            cur.execute(
                "SELECT v15.v15_prepare_statement(%s, %s, %s, 0)",
                (invoke_id, FENCE, OWNER),
            )
        except psycopg2.Error as exc:
            wconn.rollback()
            check("illegal pragma", exc.pgcode == "P1524", exc.pgcode)
        else:
            raise AssertionError("illegal pragma should fail")
    finally:
        wconn.close()
    status, error, _sqlstate = stmt_row(scur, invoke_id, 0)
    check("pragma still pending", status == "pending" and error is None, status)


def cancel_at(server, pid: int, deadline: float) -> None:
    delay = deadline - time.monotonic()
    if delay > 0:
        time.sleep(delay)
    conn = connect(server, "v15_worker")
    conn.autocommit = True
    try:
        cur = conn.cursor()
        cur.execute("SELECT pg_cancel_backend(%s)", (pid,))
        cur.fetchone()
    finally:
        conn.close()


def test_timeout(server, scur) -> None:
    invoke_id = "00000000-0000-0000-0000-000000000518"
    long_sql = (
        "WITH RECURSIVE slow(n) AS ("
        "SELECT 1 UNION ALL SELECT n + 1 FROM slow WHERE n < 100000000"
        ") SELECT max(n) FROM slow"
    )
    seed(
        scur,
        invoke_id,
        [(long_sql, "plain"), ("SELECT 1", "plain")],
        timeout_ms=2000,
    )
    scur.connection.commit()
    wconn = connect(server, "v15_worker")
    pid = None
    try:
        cur = wconn.cursor()
        cur.execute("SELECT pg_backend_pid()")
        pid = cur.fetchone()[0]
        wconn.commit()
        begin_exec(wconn, invoke_id)
        started = time.monotonic()
        info, cur = prepare_only(wconn, invoke_id, 0)
        deadline = started + int(info["timeout_ms"]) / 1000.0
        check("deadline budget", int(info["timeout_ms"]) == 2000, info["timeout_ms"])
        arm(cur, info)
        cur.execute("SHOW statement_timeout")
        shown = cur.fetchone()[0]
        check("statement_timeout armed", shown not in ("0", "0ms"), shown)
        thread = threading.Thread(
            target=cancel_at, args=(server, pid, deadline), daemon=True
        )
        thread.start()
        try:
            cur.execute(long_sql)
            if cur.description:
                cur.fetchall()
            raise AssertionError("long statement finished")
        except psycopg2.Error as exc:
            check("long statement cancelled", exc.pgcode == "57014", exc.pgcode)
            thread.join(timeout=5)
            wconn.close()
            wconn = None
            fresh = connect(server, "v15_worker")
            try:
                fail_statement(
                    fresh,
                    invoke_id,
                    0,
                    {
                        "sqlstate": "P1526",
                        "code": "V15_STATEMENT_TIMEOUT",
                        "message": "statement timeout",
                    },
                )
            finally:
                fresh.close()
    finally:
        if wconn is not None:
            wconn.close()
    status, error, sqlstate = stmt_row(scur, invoke_id, 0)
    parsed = parse_json(error)
    check("timeout failed", status == "failed" and sqlstate == "P1526", (status, sqlstate))
    check("timeout code", parsed["code"] == "V15_STATEMENT_TIMEOUT", parsed)
    status, error, _sqlstate = stmt_row(scur, invoke_id, 1)
    check("timeout does not skip", status == "pending" and error is None, status)
    scur.execute(
        "SELECT count(*) FROM v15.exec_context WHERE backend_pid = %s",
        (pid,),
    )
    check("cancelled prepare rolled back", scur.fetchone()[0] == 0)


def test_cancel(server, scur) -> None:
    invoke_id = "00000000-0000-0000-0000-000000000519"
    long_sql = (
        "WITH RECURSIVE slow(n) AS ("
        "SELECT 1 UNION ALL SELECT n + 1 FROM slow WHERE n < 100000000"
        ") SELECT max(n) FROM slow"
    )
    seed(scur, invoke_id, [(long_sql, "plain")], timeout_ms=30000)
    scur.connection.commit()
    wconn = connect(server, "v15_worker")
    try:
        cur = wconn.cursor()
        cur.execute("SELECT pg_backend_pid()")
        pid = cur.fetchone()[0]
        wconn.commit()
        begin_exec(wconn, invoke_id)
        info, cur = prepare_only(wconn, invoke_id, 0)
        deadline = time.monotonic() + int(info["timeout_ms"]) / 1000.0
        arm(cur, info)
        thread = threading.Thread(
            target=cancel_at,
            args=(server, pid, time.monotonic() + 0.2),
            daemon=True,
        )
        thread.start()
        try:
            cur.execute(long_sql)
            if cur.description:
                cur.fetchall()
            raise AssertionError("cancel target finished")
        except psycopg2.Error as exc:
            check("native cancel", exc.pgcode == "57014", exc.pgcode)
            check("before deadline", time.monotonic() < deadline - 1)
            thread.join(timeout=5)
            wconn.close()
            wconn = None
            fresh = connect(server, "v15_worker")
            try:
                fail_statement(fresh, invoke_id, 0, err_of(exc))
            finally:
                fresh.close()
    finally:
        if wconn is not None:
            wconn.close()
    status, error, sqlstate = stmt_row(scur, invoke_id, 0)
    parsed = parse_json(error)
    check("cancel kept sqlstate", status == "failed" and sqlstate == "57014", (status, parsed))
    check("cancel not renamed", parsed["code"] == "57014", parsed)


def test_crash(server, scur) -> None:
    invoke_id = "00000000-0000-0000-0000-00000000051a"
    seed(scur, invoke_id, [("SELECT 1", "plain"), ("SELECT 2", "plain")])
    scur.connection.commit()
    wconn = connect(server, "v15_worker")
    pid = None
    fence1 = None
    try:
        cur = wconn.cursor()
        cur.execute("SELECT pg_backend_pid()")
        pid = cur.fetchone()[0]
        wconn.commit()
        begin_exec(wconn, invoke_id)
        info, err, rows = run_sql(wconn, invoke_id, 0, "SELECT 1")
        check("first committed", err is None and rows == [(1,)], rows)
        fence1 = int(info["statement_fence"])
        info, cur = prepare_only(wconn, invoke_id, 1)
        scur.execute("SELECT pg_terminate_backend(%s)", (pid,))
        scur.fetchone()
        time.sleep(0.3)
        try:
            wconn.commit()
        except Exception:
            pass
        wconn.close()
        wconn = None
    finally:
        if wconn is not None:
            wconn.close()
    status, error, _sqlstate = stmt_row(scur, invoke_id, 0)
    check("committed stays done", status == "done" and error is None, status)
    status, error, _sqlstate = stmt_row(scur, invoke_id, 1)
    check("killed statement pending", status == "pending" and error is None, status)
    scur.execute(
        """
        SELECT revision, stmt_index
        FROM v15.exec_context
        WHERE backend_pid = %s
        """,
        (pid,),
    )
    ctx = scur.fetchone()
    check("exec_context restored", ctx == (fence1, 0), ctx)
    wconn = connect(server, "v15_worker")
    try:
        cur = wconn.cursor()
        cur.execute("SET LOCAL lock_timeout = '2s'")
        try:
            cur.execute(
                "SELECT v15.v15_prepare_statement(%s, %s, %s, 0)",
                (invoke_id, FENCE, OWNER),
            )
        except psycopg2.Error as exc:
            wconn.rollback()
            check("crash does not rerun done", exc.pgcode == "P1523", exc.pgcode)
        else:
            raise AssertionError("done statement was prepared again")
        info, err, rows = run_sql(wconn, invoke_id, 1, "SELECT 2")
        check("pending reruns", err is None and rows == [(2,)], rows)
    finally:
        wconn.close()
    rev = stmt_row(scur, invoke_id, 0)
    check("done row untouched", rev[0] == "done")


def test_cascade(server, scur) -> None:
    probe_id = "00000000-0000-0000-0000-000000000521"
    schema = scratch_for(probe_id)
    scur.execute("GRANT CREATE ON DATABASE agent_v15_repl TO v15_owner")
    scur.execute(
        """
        INSERT INTO v15.invokes (
          invoke_id, parent_invoke_id, parent_iteration, root_invoke_id, depth,
          status, fatal, recursion_available, resolved_config, config_digest,
          manifest_digest, scratch_schema, fence, created_at, updated_at
        ) VALUES (
          %s, NULL, NULL, %s, 1,
          'runnable', false, true, '{}'::jsonb, 'cfg',
          'md', %s, 1, clock_timestamp(), clock_timestamp()
        )
        """,
        (probe_id, probe_id, schema),
    )
    scur.execute(
        """
        CREATE FUNCTION v15.v15_probe_make(p_name text) RETURNS text
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $fn$
        BEGIN
          EXECUTE format('CREATE SCHEMA %I', p_name);
          RETURN current_user::text;
        END;
        $fn$
        """
    )
    scur.execute(
        """
        CREATE FUNCTION v15.v15_probe_drop(p_name text) RETURNS text
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $fn$
        BEGIN
          EXECUTE format('DROP SCHEMA %I CASCADE', p_name);
          RETURN current_user::text;
        END;
        $fn$
        """
    )
    scur.execute("ALTER FUNCTION v15.v15_probe_make(text) OWNER TO v15_owner")
    scur.execute("ALTER FUNCTION v15.v15_probe_drop(text) OWNER TO v15_owner")
    scur.connection.commit()
    scur.execute("SELECT v15.v15_probe_make(%s)", (schema,))
    check("definer created schema", scur.fetchone()[0] == "v15_owner")
    scur.execute(
        psql.SQL("GRANT USAGE, CREATE ON SCHEMA {} TO v15_repl").format(psql.Identifier(schema))
    )
    scur.connection.commit()
    wconn = connect(server, "v15_worker")
    try:
        cur = wconn.cursor()
        cur.execute("SELECT pg_backend_pid()")
        pid = cur.fetchone()[0]
        wconn.commit()
        scur.execute(
            """
            INSERT INTO v15.exec_context (
              backend_pid, invoke_id, iteration, stmt_index, scratch_schema
            ) VALUES (%s, %s, 0, 0, %s)
            ON CONFLICT (backend_pid) DO UPDATE
            SET invoke_id = EXCLUDED.invoke_id,
                iteration = EXCLUDED.iteration,
                stmt_index = EXCLUDED.stmt_index,
                scratch_schema = EXCLUDED.scratch_schema
            """,
            (pid, probe_id, schema),
        )
        scur.connection.commit()
        cur.execute("SET LOCAL ROLE v15_repl")
        cur.execute(
            psql.SQL("CREATE TABLE {}.t (n int)").format(psql.Identifier(schema))
        )
        cur.execute("RESET ROLE")
        wconn.commit()
    finally:
        wconn.close()
    scur.execute(
        """
        SELECT pg_get_userbyid(c.relowner)
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND c.relname = 't'
        """,
        (schema,),
    )
    check("probe table owner", scur.fetchone()[0] == "v15_repl")
    scur.execute(
        """
        SELECT 1
        FROM pg_auth_members a
        JOIN pg_roles r ON r.oid = a.roleid
        JOIN pg_roles m ON m.oid = a.member
        WHERE r.rolname = 'v15_repl' AND m.rolname = 'v15_owner'
        """
    )
    check("owner is not a repl member", scur.fetchone() is None)
    scur.execute("SELECT v15.v15_probe_drop(%s)", (schema,))
    check("definer dropped schema", scur.fetchone()[0] == "v15_owner")
    scur.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (schema,))
    check("cascade removed schema", scur.fetchone() is None)
    scur.execute("DROP FUNCTION v15.v15_probe_make(text)")
    scur.execute("DROP FUNCTION v15.v15_probe_drop(text)")
    scur.execute("REVOKE CREATE ON DATABASE agent_v15_repl FROM v15_owner")
    scur.connection.commit()


def main() -> int:
    setup_db()
    server = get_server()
    sconn = connect(server)
    sconn.autocommit = False
    try:
        scur = sconn.cursor()
        test_shape(scur)
        scur.execute("CREATE SCHEMA repl_sibling")
        scur.execute("REVOKE ALL ON SCHEMA repl_sibling FROM PUBLIC")
        sconn.commit()
        test_holder(server, scur)
        test_scratch(server, scur)
        test_assign_print(server, scur)
        test_return_raise(server, scur)
        test_print_and_return(server, scur)
        test_tools(server, scur)
        test_bind_invoke(server, scur)
        test_illegal_pragma(server, scur)
        test_timeout(server, scur)
        test_cancel(server, scur)
        test_crash(server, scur)
        test_cascade(server, scur)
    finally:
        sconn.close()
    print("[ready] v15 repl gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
