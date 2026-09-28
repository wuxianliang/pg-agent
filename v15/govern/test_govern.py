"""Stage 9 gate: hook dispatcher, governance, and budgets.

Run: uv run python v15/govern/test_govern.py  (exit 0 = pass)
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import psycopg2
from psycopg2.extras import Json

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v15.fake_llm import FakeLLM
from v15.govern.setup_db import DB, main as setup_db
from v15.protocol.render_prompt import render_system
from v15.worker import run_until_quiescent

SCOPE = "00000000-0000-4000-8000-0000000000b1"
PROFILE = "00000000-0000-4000-8000-0000000000a1"
OWNER = "govern-owner"
FORCING = (
    "[v15 budget_forcing] The finish was not accepted. "
    "Continue the task. Finished iterations are rows of jaz.history."
)
WARN_TRUE = (
    "[v15 context_window_warning] The prompt is near max_invoke_input_length. "
    "Finished iterations are rows of jaz.history. Ancestor history is "
    "jaz.prior_history(invoke_id). To delegate, end with exactly these two "
    "statements and no further statements after them:\n"
    "SELECT jaz.bind_invoke('<ident>', <jsonb-expr>);\n"
    'SELECT jaz."return"(jaz.var(\'<ident>\'));'
)
WARN_FALSE = (
    "[v15 context_window_warning] The prompt is near max_invoke_input_length. "
    "Finished iterations are rows of jaz.history. Ancestor history is "
    "jaz.prior_history(invoke_id)."
)
BIND = (
    "SELECT jaz.bind_invoke('kid', '{}'::jsonb);\n"
    'SELECT jaz."return"(jaz.var(\'kid\'));'
)
RET = 'SELECT jaz."return"(\'{"ok":true}\'::jsonb);'


class ScriptLLM:
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.inner = FakeLLM()
        self.calls = []

    def complete(self, logical_digest: str, n: int, request: dict) -> dict:
        self.calls.append((logical_digest, n, request))
        key = (logical_digest, n)
        if key not in self.inner._script:
            if not self.replies:
                raise AssertionError(f"script exhausted at n={n}")
            self.inner.register(logical_digest, n, {"content": self.replies.pop(0)})
        return self.inner.complete(logical_digest, n, request)


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


def system_text(recursion: bool = True) -> str:
    return render_system(recursion_available=recursion, bindings=[])


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


def open_invoke(
    conn,
    invoke_id: str,
    *,
    pool_id: str | None = None,
    ceilings=None,
    scope: str = SCOPE,
    local: str | None = None,
    inputs=None,
) -> None:
    cur = conn.cursor()
    cur.execute("SET LOCAL lock_timeout = '2s'")
    cur.execute("SET LOCAL statement_timeout = '30s'")
    cur.execute(
        """
        SELECT v15.v15_open_invoke(%s, %s, %s, %s::jsonb, %s, %s::jsonb, %s, %s)
        """,
        (
            invoke_id,
            scope,
            local,
            json.dumps(inputs or []),
            pool_id,
            None if ceilings is None else json.dumps(ceilings),
            system_text(),
            None,
        ),
    )
    conn.commit()


def call_phase(cur, invoke_id: str, iteration: int, span: str, phase: str, io: dict):
    cur.execute(
        "SELECT v15.v15_on_phase(%s, %s, %s, %s, %s::jsonb)",
        (invoke_id, iteration, span, phase, json.dumps(io)),
    )
    return parse_json(cur.fetchone()[0])


def expect_phase(cur, invoke_id, iteration, span, phase, io, code: str, label: str) -> None:
    cur.execute("SAVEPOINT sp")
    try:
        call_phase(cur, invoke_id, iteration, span, phase, io)
    except psycopg2.Error as exc:
        check(label, exc.pgcode == code, f"{exc.pgcode} {str(exc).splitlines()[0]}")
        cur.execute("ROLLBACK TO SAVEPOINT sp")
        return
    cur.execute("ROLLBACK TO SAVEPOINT sp")
    raise AssertionError(f"{label}: expected {code}")


def install_hook(cur, key: str, body: str, invoke_id: str | None = None, config=None, channel="propagating") -> None:
    role = f"v15_hook_{key}"
    cur.execute(
        f"CREATE ROLE {role} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT"
    )
    cur.execute(
        f"""
        CREATE FUNCTION v15.{key}(p_snapshot jsonb) RETURNS jsonb
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        SET search_path = pg_catalog
        AS $body$
        {body}
        $body$
        """
    )
    cur.execute(f"ALTER FUNCTION v15.{key}(jsonb) OWNER TO {role}")
    cur.execute(f"REVOKE ALL ON FUNCTION v15.{key}(jsonb) FROM PUBLIC")
    cur.execute(f"REVOKE ALL ON FUNCTION v15.{key}(jsonb) FROM {role}")
    cur.execute(f"GRANT EXECUTE ON FUNCTION v15.{key}(jsonb) TO v15_owner")
    cur.execute(
        "SELECT v15.v15_register_hook(%s, %s::regprocedure, false)",
        (key, f"v15.{key}(jsonb)"),
    )
    if invoke_id is not None:
        cur.execute(
            """
            INSERT INTO v15.invoke_hooks (
              invoke_id, ordinal, hook_def_id, channel, config, state
            )
            SELECT %s,
                   (SELECT coalesce(max(ordinal), -1) + 1
                    FROM v15.invoke_hooks WHERE invoke_id = %s),
                   d.hook_def_id, %s, %s::jsonb, '{}'::jsonb
            FROM v15.hook_defs d
            WHERE d.hook_key = %s
            """,
            (invoke_id, invoke_id, channel, json.dumps(config or {}), key),
        )


def board_write(key: str, value: str) -> str:
    return f"""
    BEGIN
      RETURN jsonb_build_object(
        'contract', 1,
        'action', 'proceed',
        'blackboard_writes', jsonb_build_array(
          jsonb_build_object('key', '{key}', 'value', '{value}'::jsonb)
        )
      );
    END
    """


def park(cur, keep: str | None = None) -> None:
    cur.execute(
        """
        UPDATE v15.invokes
        SET status = 'failed', fatal = false,
            lease_owner = NULL, lease_until = NULL,
            error = '{"sqlstate":"P1520","code":"V15_ITERATION_EXCEEDED","message":"parked"}'::jsonb
        WHERE status IN ('pending', 'runnable', 'leased', 'suspended')
          AND (%s::uuid IS NULL OR invoke_id <> %s::uuid)
        """,
        (keep, keep),
    )
    cur.execute("COMMIT")


def add_scope(cur, scope: str, hooks: list, layer: str) -> None:
    cur.execute("SELECT v15.v15_register_scope(%s, %s)", (scope, PROFILE))
    cur.execute(
        """
        SELECT v15.v15_add_layer(%s, %s, 0, 'plain', NULL, NULL, NULL, NULL, %s::jsonb)
        """,
        (layer, scope, json.dumps(hooks)),
    )


def test_oids(cur) -> None:
    cur.execute(
        """
        SELECT b.proname, b.oid::text = p.oid::text
        FROM public.v15_pre_govern_oids b
        JOIN pg_proc p ON p.proname = b.proname
        JOIN pg_namespace n ON n.oid = p.pronamespace AND n.nspname = 'v15'
        ORDER BY b.proname
        """
    )
    rows = cur.fetchall()
    check("replace kept five oids", len(rows) == 5 and all(row[1] for row in rows), rows)
    cur.execute(
        """
        SELECT count(*)
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'v15' AND p.proname = 'v15_on_phase'
        """
    )
    check("one v15_on_phase", cur.fetchone()[0] == 1)


def test_decoy_and_replace(cur, wconn) -> None:
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    cur.execute(
        """
        CREATE FUNCTION public.governance_iterations(jsonb) RETURNS jsonb
        LANGUAGE sql
        AS $fn$
          SELECT '{"contract":1,"action":"proceed","messages":[
            {"id":"decoy","role":"user","content":"decoy","persistent":true}
          ]}'::jsonb
        $fn$
        """
    )
    cur.execute("SET search_path TO public, v15, pg_catalog")
    ret = call_phase(cur, iid, 0, "llm_query", "enter", {"iteration": 0, "next_attempt_n": 1})
    cur.execute("SET search_path TO pg_catalog")
    check("decoy not called", "decoy" not in json.dumps(ret), ret)
    check("enter proceed", ret.get("action") == "proceed", ret)
    cur.execute("SELECT oid FROM pg_proc WHERE proname = 'bb_body' AND pronamespace = 'v15'::regnamespace")
    install_hook(cur, "bb_body", board_write("old", "1"), iid)
    cur.execute(
        """
        SELECT p.oid
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'v15' AND p.proname = 'bb_body'
        """
    )
    old_oid = cur.fetchone()[0]
    cur.execute("SAVEPOINT repl")
    cur.execute(
        """
        CREATE OR REPLACE FUNCTION v15.bb_body(p_snapshot jsonb) RETURNS jsonb
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        SET search_path = pg_catalog
        AS $fn$
        BEGIN
          RETURN jsonb_build_object(
            'contract', 1, 'action', 'proceed',
            'blackboard_writes', jsonb_build_array(
              jsonb_build_object('key', 'newbody', 'value', '1'::jsonb)
            )
          );
        END
        $fn$
        """
    )
    cur.execute(
        """
        SELECT p.oid
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'v15' AND p.proname = 'bb_body'
        """
    )
    check("same-session replace keeps oid", cur.fetchone()[0] == old_oid)
    expect_phase(
        cur, iid, 0, "invoke", "complete", {"outcome": "completed"},
        "P1536", "digest drift after replace",
    )
    cur.execute(
        """
        UPDATE v15.hook_defs
        SET handler_digest = v15.v15_handler_digest(regprocedure)
        WHERE hook_key = 'bb_body'
        """
    )
    ret = call_phase(cur, iid, 0, "invoke", "complete", {"outcome": "completed"})
    cur.execute(
        "SELECT value::text FROM v15.blackboard WHERE invoke_id = %s AND key = 'newbody'",
        (iid,),
    )
    check("new body effective without new connection", cur.fetchone()[0] == "1", ret)
    cur.execute("ROLLBACK TO SAVEPOINT repl")
    cur.execute("SAVEPOINT aclgrant")
    cur.execute("GRANT EXECUTE ON FUNCTION v15.governance_iterations(jsonb) TO v15_worker")
    expect_phase(
        cur, iid, 0, "llm_query", "enter", {"iteration": 0, "next_attempt_n": 1},
        "P1536", "grant changes handler digest",
    )
    cur.execute("ROLLBACK TO SAVEPOINT aclgrant")
    cur.execute("SAVEPOINT tabl")
    cur.execute("GRANT SELECT ON v15.invokes TO v15_hook_governance_iterations")
    expect_phase(
        cur, iid, 0, "llm_query", "enter", {"iteration": 0, "next_attempt_n": 1},
        "P1536", "table grant is handler digest",
    )
    cur.execute("ROLLBACK TO SAVEPOINT tabl")


def test_synthesis(cur, wconn) -> None:
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    install_hook(cur, "bb_a", board_write("k", "1"), iid)
    install_hook(cur, "bb_b", board_write("k", "1"), iid)
    call_phase(cur, iid, 0, "invoke", "complete", {"outcome": "completed"})
    cur.execute(
        "SELECT generation, value::text FROM v15.blackboard WHERE invoke_id = %s AND key = 'k'",
        (iid,),
    )
    check("equal blackboard merges", cur.fetchone() == (1, "1"))
    cur.execute("ROLLBACK")
    cur.execute("BEGIN")
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    install_hook(cur, "bb_c", board_write("k", "1"), iid)
    install_hook(cur, "bb_d", board_write("k", "2"), iid)
    expect_phase(
        cur, iid, 0, "invoke", "complete", {"outcome": "completed"},
        "P1533", "unequal blackboard conflicts",
    )
    cur.execute("SELECT count(*) FROM v15.blackboard WHERE invoke_id = %s", (iid,))
    check("conflict leaves no blackboard", cur.fetchone()[0] == 0)
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    install_hook(
        cur, "in_a",
        """
        BEGIN
          RETURN jsonb_build_object(
            'contract', 1, 'action', 'proceed',
            'input_adds', jsonb_build_array(jsonb_build_object(
              'name', 'n', 'value', '1'::jsonb, 'show_in_prompt', true
            ))
          );
        END
        """,
        iid,
    )
    install_hook(
        cur, "in_b",
        """
        BEGIN
          RETURN jsonb_build_object(
            'contract', 1, 'action', 'proceed',
            'input_adds', jsonb_build_array(jsonb_build_object(
              'name', 'n', 'value', '2'::jsonb, 'show_in_prompt', true
            ))
          );
        END
        """,
        iid,
    )
    expect_phase(cur, iid, 0, "invoke", "enter", {"depth": 1}, "P1534", "input conflict")
    cur.execute("SELECT count(*) FROM v15.bindings WHERE invoke_id = %s AND name = 'n'", (iid,))
    check("input conflict leaves no binding", cur.fetchone()[0] == 0)
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    install_hook(
        cur, "bad_supply",
        """
        BEGIN
          RETURN jsonb_build_object(
            'contract', 1, 'action', 'proceed', 'supply_llm_response', '1'::jsonb
          );
        END
        """,
        iid,
    )
    expect_phase(cur, iid, 0, "invoke", "complete", {"outcome": "completed"}, "P1506", "reserved effect")
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    install_hook(
        cur, "bad_key",
        """
        BEGIN
          RETURN jsonb_build_object('contract', 1, 'action', 'proceed', 'nope', 1);
        END
        """,
        iid,
    )
    expect_phase(cur, iid, 0, "invoke", "complete", {"outcome": "completed"}, "P1516", "unknown key")
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    install_hook(
        cur, "bad_code",
        """
        BEGIN
          RETURN jsonb_build_object(
            'contract', 1, 'action', 'abort', 'fatal', false,
            'error', jsonb_build_object('code', 'V15_STALE_FENCE', 'message', 'x')
          );
        END
        """,
        iid,
    )
    ret = call_phase(cur, iid, 0, "llm_query", "enter", {"iteration": 0, "next_attempt_n": 1})
    check("non-retain code becomes hook abort", ret.get("code") == "V15_HOOK_ABORT" and ret.get("fatal") is False, ret)
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    install_hook(
        cur, "msg_a",
        """
        BEGIN
          RETURN jsonb_build_object(
            'contract', 1, 'action', 'proceed',
            'messages', jsonb_build_array(jsonb_build_object(
              'id', 'same', 'role', 'user', 'content', 'a', 'persistent', true
            ))
          );
        END
        """,
        iid,
    )
    install_hook(
        cur, "msg_b",
        """
        BEGIN
          RETURN jsonb_build_object(
            'contract', 1, 'action', 'proceed',
            'messages', jsonb_build_array(jsonb_build_object(
              'id', 'same', 'role', 'user', 'content', 'b', 'persistent', true
            ))
          );
        END
        """,
        iid,
    )
    expect_phase(
        cur, iid, 0, "llm_query", "enter", {"iteration": 0, "next_attempt_n": 1},
        "P1535", "unequal messages conflict",
    )
    cur.execute("ROLLBACK")


def test_abort_algebra(cur, wconn) -> None:
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    install_hook(
        cur, "ab_iter",
        """
        BEGIN
          RETURN jsonb_build_object(
            'contract', 1, 'action', 'abort', 'fatal', true,
            'error', jsonb_build_object('code', 'V15_ITERATION_EXCEEDED', 'message', 'a')
          );
        END
        """,
        iid,
    )
    ret = call_phase(cur, iid, 0, "llm_query", "enter", {"iteration": 0, "next_attempt_n": 1})
    check("fatal normalized false", ret.get("code") == "V15_ITERATION_EXCEEDED" and ret.get("fatal") is False, ret)
    install_hook(
        cur, "ab_io",
        """
        BEGIN
          RETURN jsonb_build_object(
            'contract', 1, 'action', 'abort', 'fatal', true,
            'error', jsonb_build_object('code', 'V15_IO_EXHAUSTED', 'message', 'b')
          );
        END
        """,
        iid,
    )
    ret = call_phase(cur, iid, 0, "llm_query", "enter", {"iteration": 0, "next_attempt_n": 1})
    check("disagreeing retain codes", ret.get("code") == "V15_HOOK_ABORT", ret)
    install_hook(
        cur, "ab_budget",
        """
        BEGIN
          RETURN jsonb_build_object(
            'contract', 1, 'action', 'abort', 'fatal', false,
            'error', jsonb_build_object('code', 'V15_BUDGET_EXHAUSTED', 'message', '')
          );
        END
        """,
        iid,
    )
    ret = call_phase(cur, iid, 0, "repl_exec", "send", {})
    check("budget fatal forced true", ret.get("code") == "V15_HOOK_ABORT" and ret.get("fatal") is True, ret)
    cur.execute("ROLLBACK")


def test_isolation(cur, wconn) -> None:
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    install_hook(
        cur, "boom_opt",
        """
        BEGIN
          RAISE EXCEPTION 'optional boom' USING ERRCODE = 'P0001';
        END
        """,
        iid,
    )
    install_hook(cur, "kept_bb", board_write("kept", "1"), iid)
    call_phase(cur, iid, 0, "invoke", "complete", {"outcome": "completed"})
    cur.execute(
        """
        SELECT payload->>'op', payload->>'hook_key', payload->>'sqlstate'
        FROM v15.invoke_events
        WHERE invoke_id = %s AND event_class = 'audit'
          AND payload->>'op' = 'handler_exception'
        """,
        (iid,),
    )
    check("optional exception audited", cur.fetchone() == ("handler_exception", "boom_opt", "P0001"))
    cur.execute(
        "SELECT value::text FROM v15.blackboard WHERE invoke_id = %s AND key = 'kept'",
        (iid,),
    )
    check("sibling effect kept", cur.fetchone()[0] == "1")
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    cur.execute("SAVEPOINT base")
    cur.execute(
        """
        CREATE OR REPLACE FUNCTION v15.governance_iterations(p_snapshot jsonb) RETURNS jsonb
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        SET search_path = pg_catalog
        AS $fn$
        BEGIN
          RAISE EXCEPTION 'baseline boom' USING ERRCODE = 'P0001';
        END
        $fn$
        """
    )
    cur.execute(
        """
        UPDATE v15.hook_defs
        SET handler_digest = v15.v15_handler_digest(regprocedure)
        WHERE hook_key = 'governance_iterations'
        """
    )
    expect_phase(
        cur, iid, 0, "llm_query", "enter", {"iteration": 0, "next_attempt_n": 1},
        "P1508", "baseline exception is governance fault",
    )
    cur.execute("ROLLBACK TO SAVEPOINT base")
    cur.execute(
        """
        SELECT count(*) FROM v15.invoke_events
        WHERE invoke_id = %s AND payload->>'op' = 'handler_exception'
        """,
        (iid,),
    )
    check("baseline fault leaves no audit", cur.fetchone()[0] == 0)
    cur.execute("SAVEPOINT exitab")
    cur.execute(
        """
        INSERT INTO v15.invoke_events (
          invoke_id, seq, event_class, span, phase, outcome, payload, created_at
        )
        SELECT %s, coalesce(max(seq), -1) + 1, 'span', 'invoke', 'exit', 'completed',
               '{\"outcome\":\"completed\"}'::jsonb, clock_timestamp()
        FROM v15.invoke_events WHERE invoke_id = %s
        """,
        (iid, iid),
    )
    install_hook(
        cur, "exit_abort",
        """
        BEGIN
          RETURN jsonb_build_object(
            'contract', 1, 'action', 'abort', 'fatal', false,
            'error', jsonb_build_object('code', 'V15_ITERATION_EXCEEDED', 'message', '')
          );
        END
        """,
        iid,
    )
    try:
        call_phase(cur, iid, 0, "invoke", "exit", {"outcome": "completed"})
        raised = False
    except psycopg2.Error as exc:
        raised = True
        check("exit abort rejected", exc.pgcode == "P1506", exc.pgcode)
    if not raised:
        raise AssertionError("exit abort rejected: expected P1506")
    cur.execute("ROLLBACK TO SAVEPOINT exitab")
    cur.execute(
        """
        SELECT count(*) FROM v15.invoke_events
        WHERE invoke_id = %s AND phase = 'exit'
        """,
        (iid,),
    )
    check("exit abort rolls outcome back", cur.fetchone()[0] == 0)
    install_hook(cur, "exit_bb", board_write("later", "1"), iid)
    cur.execute(
        """
        INSERT INTO v15.invoke_events (
          invoke_id, seq, event_class, span, phase, outcome, payload, created_at
        )
        SELECT %s, coalesce(max(seq), -1) + 1, 'span', 'invoke', 'exit', 'completed',
               '{"outcome":"completed"}'::jsonb, clock_timestamp()
        FROM v15.invoke_events WHERE invoke_id = %s
        """,
        (iid, iid),
    )
    call_phase(cur, iid, 0, "invoke", "exit", {"outcome": "completed"})
    cur.execute(
        "SELECT value::text FROM v15.blackboard WHERE invoke_id = %s AND key = 'later'",
        (iid,),
    )
    check("exit may write blackboard", cur.fetchone()[0] == "1")
    cur.execute("ROLLBACK")


def test_generation(cur, wconn) -> None:
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    install_hook(cur, "gen_a", board_write("a", "1"), iid)
    install_hook(
        cur, "gen_b",
        """
        BEGIN
          RETURN jsonb_build_object(
            'contract', 1, 'action', 'proceed',
            'blackboard_writes', jsonb_build_array(jsonb_build_object(
              'key', 'seen',
              'value', to_jsonb(coalesce((p_snapshot #>> '{blackboard,generation,a}')::int, 0))
            ))
          );
        END
        """,
        iid,
    )
    call_phase(cur, iid, 0, "invoke", "complete", {"outcome": "completed"})
    cur.execute(
        """
        SELECT key, generation, value::text
        FROM v15.blackboard WHERE invoke_id = %s AND key IN ('a', 'seen')
        ORDER BY key
        """,
        (iid,),
    )
    rows = cur.fetchall()
    check("same phase reads old generation", rows == [("a", 1, "1"), ("seen", 1, "0")], rows)
    cur.execute("ROLLBACK")


def test_handlers(cur, wconn) -> None:
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    ret = call_phase(cur, iid, 10, "llm_query", "enter", {"iteration": 10, "next_attempt_n": 1})
    check("iteration abort before lease", ret.get("action") == "abort" and ret.get("code") == "V15_ITERATION_EXCEEDED" and ret.get("fatal") is False, ret)
    cur.execute("SELECT count(*) FROM v15.llm_attempts a JOIN v15.llm_requests r ON r.request_id = a.request_id WHERE r.invoke_id = %s", (iid,))
    check("iteration abort inserts no attempt", cur.fetchone()[0] == 0)
    ret = call_phase(cur, iid, 0, "llm_query", "enter", {"iteration": 0, "next_attempt_n": 4})
    check("io ceiling abort", ret.get("code") == "V15_IO_EXHAUSTED", ret)
    ret = call_phase(cur, iid, 0, "invoke", "enter", {"depth": 8})
    check("depth equals max disables", ret.get("recursion_available") is False, ret)
    cur.execute("SELECT recursion_available FROM v15.invokes WHERE invoke_id = %s", (iid,))
    check("disable landed", cur.fetchone()[0] is False)
    ret = call_phase(cur, iid, 0, "invoke", "enter", {"depth": 9})
    check("depth above max aborts", ret.get("code") == "V15_RECURSION_EXCEEDED" and ret.get("fatal") is False, ret)
    fails(
        cur,
        "SELECT v15.governance_statement(%s::jsonb)",
        (json.dumps({
            "span": "repl_exec", "phase": "enter",
            "ceilings": {"max_statement_ms": 1},
            "self": {"config": {"max": 2}},
        }),),
        "P1521",
        "statement ceiling mismatch",
    )
    cur.execute(
        """
        SELECT v15.v15_repl_timeout_ms(
          %s, %s, (SELECT resolved_config FROM v15.invokes WHERE invoke_id = %s)
        )
        """,
        (iid, "-- timeout: 999\nSELECT 1", iid),
    )
    check("timeout floored by governance max", cur.fetchone()[0] == 30000)
    cur.execute("ROLLBACK")


def test_register(cur) -> None:
    cur.execute("CREATE ROLE v15_hook_bad_immut NOLOGIN NOSUPERUSER")
    cur.execute(
        """
        CREATE FUNCTION v15.bad_immut(jsonb) RETURNS jsonb
        LANGUAGE sql IMMUTABLE SECURITY DEFINER
        SET search_path = pg_catalog
        AS $fn$ SELECT '{"contract":1,"action":"proceed"}'::jsonb $fn$
        """
    )
    cur.execute("ALTER FUNCTION v15.bad_immut(jsonb) OWNER TO v15_hook_bad_immut")
    cur.execute("REVOKE ALL ON FUNCTION v15.bad_immut(jsonb) FROM PUBLIC, v15_hook_bad_immut")
    cur.execute("GRANT EXECUTE ON FUNCTION v15.bad_immut(jsonb) TO v15_owner")
    fails(
        cur,
        "SELECT v15.v15_register_hook('bad_immut', 'v15.bad_immut(jsonb)'::regprocedure, false)",
        code="P1537",
        label="immutable handler rejected",
    )
    cur.execute("SELECT count(*) FROM v15.hook_defs WHERE hook_key = 'bad_immut'")
    check("rejected register leaves no row", cur.fetchone()[0] == 0)
    cur.execute("CREATE ROLE v15_hook_bad_path NOLOGIN NOSUPERUSER")
    cur.execute(
        """
        CREATE FUNCTION v15.bad_path(jsonb) RETURNS jsonb
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $fn$ SELECT '{"contract":1,"action":"proceed"}'::jsonb $fn$
        """
    )
    cur.execute("ALTER FUNCTION v15.bad_path(jsonb) OWNER TO v15_hook_bad_path")
    cur.execute("REVOKE ALL ON FUNCTION v15.bad_path(jsonb) FROM PUBLIC, v15_hook_bad_path")
    cur.execute("GRANT EXECUTE ON FUNCTION v15.bad_path(jsonb) TO v15_owner")
    fails(
        cur,
        "SELECT v15.v15_register_hook('bad_path', 'v15.bad_path(jsonb)'::regprocedure, false)",
        code="P1537",
        label="pg_temp search_path rejected",
    )
    cur.execute("CREATE ROLE v15_hook_bad_own NOLOGIN NOSUPERUSER")
    cur.execute(
        """
        CREATE FUNCTION v15.bad_own(jsonb) RETURNS jsonb
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog
        AS $fn$ SELECT '{"contract":1,"action":"proceed"}'::jsonb $fn$
        """
    )
    cur.execute("ALTER FUNCTION v15.bad_own(jsonb) OWNER TO v15_owner")
    cur.execute("REVOKE ALL ON FUNCTION v15.bad_own(jsonb) FROM PUBLIC")
    cur.execute("GRANT EXECUTE ON FUNCTION v15.bad_own(jsonb) TO v15_owner")
    fails(
        cur,
        "SELECT v15.v15_register_hook('bad_own', 'v15.bad_own(jsonb)'::regprocedure, false)",
        code="P1537",
        label="wrong owner rejected",
    )
    cur.execute("CREATE ROLE v15_hook_bad_tab NOLOGIN NOSUPERUSER")
    cur.execute(
        """
        CREATE FUNCTION v15.bad_tab(jsonb) RETURNS jsonb
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog
        AS $fn$ SELECT '{"contract":1,"action":"proceed"}'::jsonb $fn$
        """
    )
    cur.execute("ALTER FUNCTION v15.bad_tab(jsonb) OWNER TO v15_hook_bad_tab")
    cur.execute("REVOKE ALL ON FUNCTION v15.bad_tab(jsonb) FROM PUBLIC, v15_hook_bad_tab")
    cur.execute("GRANT EXECUTE ON FUNCTION v15.bad_tab(jsonb) TO v15_owner")
    cur.execute("GRANT SELECT ON v15.invokes TO v15_hook_bad_tab")
    fails(
        cur,
        "SELECT v15.v15_register_hook('bad_tab', 'v15.bad_tab(jsonb)'::regprocedure, false)",
        code="P1537",
        label="kernel table privilege rejected",
    )
    cur.execute("CREATE ROLE v15_hook_bad_c NOLOGIN NOSUPERUSER")
    fails(
        cur,
        """
        INSERT INTO v15.hook_defs (
          hook_def_id, hook_key, regprocedure, owner_role, baseline_required,
          handler_digest, search_path, created_at
        )
        SELECT gen_random_uuid(), 'bad_c', p.oid, r.oid, false, 'x', 'pg_catalog', clock_timestamp()
        FROM pg_proc p, pg_roles r, pg_language l
        WHERE l.lanname = 'c' AND p.prolang = l.oid AND r.rolname = 'v15_hook_bad_c'
        LIMIT 1
        """,
        code="P1537",
        label="c language rejected",
    )
    cur.execute("ROLLBACK")


def test_tool(cur, wconn) -> None:
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    wcur = wconn.cursor()
    wcur.execute("SELECT pg_backend_pid()")
    pid = wcur.fetchone()[0]
    cur.execute(
        """
        INSERT INTO v15.statements (
          invoke_id, iteration, stmt_index, sql, sql_digest, kind, status
        ) VALUES (%s, 0, 0, 'SELECT 1', md5('SELECT 1'), 'plain', 'running')
        """,
        (iid,),
    )
    cur.execute(
        """
        INSERT INTO v15.exec_context (
          backend_pid, invoke_id, iteration, stmt_index, scratch_schema
        ) VALUES (%s, %s, 0, 0, %s)
        """,
        (pid, iid, "s_" + iid.replace("-", "")),
    )
    cur.execute("COMMIT")
    wcur.execute("BEGIN")
    wcur.execute("SET LOCAL ROLE v15_repl")
    fails(wcur, "SELECT jaz.tool('missing', '{}'::jsonb)", code="P1507", label="tool unauthorized")
    wconn.rollback()
    cur.execute("DELETE FROM v15.exec_context WHERE invoke_id = %s", (iid,))
    cur.execute("DELETE FROM v15.statements WHERE invoke_id = %s", (iid,))
    cur.execute(
        """
        UPDATE v15.invokes
        SET status = 'failed', fatal = false,
            error = '{"sqlstate":"P1507","code":"V15_TOOL_UNAUTHORIZED","message":""}'::jsonb
        WHERE invoke_id = %s
        """,
        (iid,),
    )
    cur.execute("COMMIT")


def test_budget(cur, wconn, server) -> None:
    scope = str(uuid.uuid4())
    layer = str(uuid.uuid4())
    pool = str(uuid.uuid4())
    add_scope(cur, scope, [{
        "hook_key": "budget_pool",
        "config": {"reserve_calls": 2, "reserve_cost": 0},
    }], layer)
    cur.execute(
        "INSERT INTO v15.budget_pools (pool_id, calls_limit) VALUES (%s, 20)",
        (pool,),
    )
    cur.execute("COMMIT")
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid, pool_id=pool, scope=scope)
    park(cur, iid)
    script = ScriptLLM([RET])
    run_until_quiescent(server.get_uri(DB), script, OWNER)
    cur.execute(
        "SELECT calls_used, calls_reserved, revision FROM v15.budget_pools WHERE pool_id = %s",
        (pool,),
    )
    check("reserve then settle once", cur.fetchone() == (2, 0, 2))
    cur.execute(
        """
        SELECT reserved_calls FROM v15.llm_attempts a
        JOIN v15.llm_requests r ON r.request_id = a.request_id
        WHERE r.invoke_id = %s
        """,
        (iid,),
    )
    check("attempt stores synthesized reserve", cur.fetchone()[0] == 2)
    pool2 = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO v15.budget_pools (pool_id, calls_limit) VALUES (%s, 20)",
        (pool2,),
    )
    cur.execute("COMMIT")
    iid2 = str(uuid.uuid4())
    open_invoke(wconn, iid2, pool_id=pool2, scope=scope)
    wcur = wconn.cursor()
    wcur.execute("BEGIN")
    wcur.execute("SET LOCAL lock_timeout = '2s'")
    wcur.execute("SELECT v15.v15_claim(%s, %s, '30 seconds'::interval)", (iid2, OWNER))
    fence = wcur.fetchone()[0]
    wcur.execute("SELECT v15.v15_loop_snapshot(%s)", (iid2,))
    snap = parse_json(wcur.fetchone()[0])
    from v15.worker import build_base
    wcur.execute(
        "SELECT v15.v15_begin_llm(%s, %s, %s, %s)",
        (iid2, fence, OWNER, Json(build_base(snap))),
    )
    begun = parse_json(wcur.fetchone()[0])
    check("begin proceeds after one reserve", begun["action"] == "proceed")
    wcur.execute("COMMIT")
    cur.execute(
        "SELECT calls_reserved, revision FROM v15.budget_pools WHERE pool_id = %s",
        (pool2,),
    )
    check("pool reserved exactly once", cur.fetchone() == (2, 1))
    cur.execute(
        """
        UPDATE v15.llm_attempts
        SET lease_until = clock_timestamp() - interval '1 minute'
        WHERE attempt_id = %s
        """,
        (begun["attempt_id"],),
    )
    cur.execute("COMMIT")
    wcur.execute("BEGIN")
    wcur.execute("SET LOCAL lock_timeout = '2s'")
    wcur.execute("SELECT v15.v15_reclaim_expired()")
    wcur.execute("COMMIT")
    cur.execute(
        "SELECT calls_used, calls_reserved FROM v15.budget_pools WHERE pool_id = %s",
        (pool2,),
    )
    check("unstarted reclaim refunds reserve", cur.fetchone() == (0, 0))
    cur.execute(
        """
        UPDATE v15.invokes
        SET status = 'failed', fatal = false, lease_owner = NULL, lease_until = NULL,
            error = '{"sqlstate":"P1513","code":"V15_IO_EXHAUSTED","message":""}'::jsonb
        WHERE invoke_id = %s
        """,
        (iid2,),
    )
    cur.execute("COMMIT")
    pool3 = str(uuid.uuid4())
    scope3 = str(uuid.uuid4())
    layer3 = str(uuid.uuid4())
    add_scope(cur, scope3, [{
        "hook_key": "budget_pool",
        "config": {"reserve_calls": 2, "reserve_cost": 0},
    }], layer3)
    cur.execute(
        "INSERT INTO v15.budget_pools (pool_id, calls_limit) VALUES (%s, 1)",
        (pool3,),
    )
    cur.execute("COMMIT")
    iid3 = str(uuid.uuid4())
    open_invoke(wconn, iid3, pool_id=pool3, scope=scope3)
    park(cur, iid3)
    run_until_quiescent(server.get_uri(DB), ScriptLLM([]), OWNER)
    cur.execute(
        "SELECT status, fatal, error->>'code', error->>'sqlstate' FROM v15.invokes WHERE invoke_id = %s",
        (iid3,),
    )
    check("zero-row reserve is fatal budget", cur.fetchone() == ("aborted", True, "V15_BUDGET_EXHAUSTED", "P1514"))
    cur.execute("SELECT count(*) FROM v15.llm_attempts a JOIN v15.llm_requests r ON r.request_id = a.request_id WHERE r.invoke_id = %s", (iid3,))
    check("zero-row inserts no attempt", cur.fetchone()[0] == 0)
    cur.execute("SELECT calls_reserved, revision FROM v15.budget_pools WHERE pool_id = %s", (pool3,))
    check("zero-row leaves pool untouched", cur.fetchone() == (0, 0))


def test_warnings_and_forcing(cur, wconn) -> None:
    scope = str(uuid.uuid4())
    layer = str(uuid.uuid4())
    add_scope(cur, scope, [
        {"hook_key": "budget_forcing", "config": {"max_rejections": 2}},
        {"hook_key": "context_window_warning", "config": {"ratio": 0.0001}},
    ], layer)
    cur.execute("COMMIT")
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid, scope=scope)
    ret = call_phase(
        cur, iid, 0, "llm_query", "send",
        {
            "iteration": 0,
            "logical_digest": "abc",
            "input_chars": 100,
            "enter_messages": None,
            "enter_overlay": {"recursion_available": False},
        },
    )
    texts = [m["content"] for m in ret.get("messages", []) if m["id"] == "context_window_warning"]
    check("leaf warning has no bind", texts == [WARN_FALSE], texts)
    check("warning is transient", ret["messages"][0]["persistent"] is False)
    cur.execute(
        "SELECT count(*) FROM v15.llm_messages WHERE invoke_id = %s AND message_id = 'context_window_warning'",
        (iid,),
    )
    check("transient warning not stored", cur.fetchone()[0] == 0)
    cur.execute("UPDATE v15.invokes SET recursion_available = true WHERE invoke_id = %s", (iid,))
    ret = call_phase(
        cur, iid, 0, "llm_query", "send",
        {
            "iteration": 0,
            "logical_digest": "abc",
            "input_chars": 100,
            "enter_messages": None,
            "enter_overlay": None,
        },
    )
    texts = [m["content"] for m in ret.get("messages", []) if m["id"] == "context_window_warning"]
    check("open warning includes bind", texts == [WARN_TRUE], texts)
    ret = call_phase(
        cur, iid, 0, "repl_exec", "complete",
        {"result_kind": "return", "return_value": {"ok": True}, "error": None, "capture": ""},
    )
    ids = [m["id"] for m in ret.get("messages", [])]
    check("forcing id uses pre-increment count", ids == ["budget_forcing:4:0"], ids)
    check("forcing text", ret["messages"][0]["content"] == FORCING)
    cur.execute("SELECT count(*) FROM v15.hook_counters WHERE invoke_id = %s", (iid,))
    check("complete does not bump forcing counter", cur.fetchone()[0] == 0)
    cur.execute("ROLLBACK")


def test_manifest(cur, wconn) -> None:
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    cur.execute("SAVEPOINT man")
    cur.execute("UPDATE v15.invokes SET manifest_digest = 'drift' WHERE invoke_id = %s", (iid,))
    fails(
        cur,
        "SELECT v15.v15_assert_invoke_manifest(%s)",
        (iid,),
        "P1521",
        "invoke manifest drift",
    )
    cur.execute("ROLLBACK TO SAVEPOINT man")
    scope = str(uuid.uuid4())
    layer = str(uuid.uuid4())
    add_scope(cur, scope, [{"hook_key": "iteration_limit", "config": {"max": 11}}], layer)
    cur.execute("COMMIT")
    loose = str(uuid.uuid4())
    wcur = wconn.cursor()
    wcur.execute("BEGIN")
    wcur.execute("SET LOCAL lock_timeout = '2s'")
    fails(
        wcur,
        "SELECT v15.v15_open_invoke(%s, %s, NULL, '[]'::jsonb, NULL, NULL, %s, NULL)",
        (loose, scope, system_text()),
        "P1505",
        "optional max cannot loosen",
    )
    wconn.rollback()
    cur.execute("SELECT count(*) FROM v15.invokes WHERE invoke_id = %s", (loose,))
    check("loose open leaves no row", cur.fetchone()[0] == 0)


def test_e2e(cur, wconn, server) -> None:
    scope = str(uuid.uuid4())
    layer = str(uuid.uuid4())
    pool = str(uuid.uuid4())
    add_scope(cur, scope, [
        {"hook_key": "budget_forcing", "config": {"max_rejections": 1}},
        {"hook_key": "context_window_warning", "config": {"ratio": 0.0001}},
        {"hook_key": "budget_pool", "config": {"reserve_calls": 1, "reserve_cost": 0}},
    ], layer)
    cur.execute(
        "INSERT INTO v15.budget_pools (pool_id, calls_limit) VALUES (%s, 20)",
        (pool,),
    )
    cur.execute("COMMIT")
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid, pool_id=pool, scope=scope, ceilings={"max_depth": 3})
    park(cur, iid)
    script = ScriptLLM([BIND, BIND, RET, RET, RET, RET])
    run_until_quiescent(server.get_uri(DB), script, OWNER)
    cur.execute(
        """
        SELECT depth, status, error->>'code'
        FROM v15.invokes
        WHERE root_invoke_id = %s
        ORDER BY depth
        """,
        (iid,),
    )
    rows = cur.fetchall()
    check("nested tree completed", rows == [(1, "completed", None), (2, "completed", None), (3, "completed", None)], rows)
    cur.execute(
        """
        SELECT n FROM v15.hook_counters
        WHERE invoke_id IN (SELECT invoke_id FROM v15.invokes WHERE root_invoke_id = %s)
          AND counter_key = 'budget_forcing:4'
        ORDER BY n
        """,
        (iid,),
    )
    check("forcing counted once per invoke", cur.fetchall() == [(1,), (1,), (1,)])
    cur.execute(
        """
        SELECT count(*) FROM v15.llm_messages
        WHERE message_id = 'budget_forcing:4:0'
          AND content = %s
          AND invoke_id IN (SELECT invoke_id FROM v15.invokes WHERE root_invoke_id = %s)
        """,
        (FORCING, iid),
    )
    check("forcing message persisted", cur.fetchone()[0] == 3)
    cur.execute(
        """
        SELECT count(*) FROM v15.llm_messages
        WHERE message_id = 'context_window_warning'
          AND invoke_id IN (SELECT invoke_id FROM v15.invokes WHERE root_invoke_id = %s)
        """,
        (iid,),
    )
    check("warnings stayed out of llm_messages", cur.fetchone()[0] == 0)
    warn = []
    for _digest, _n, request in script.calls:
        for message in request["messages"]:
            if message.get("message_id") == "context_window_warning":
                warn.append(message["content"])
    check("both warning variants", WARN_TRUE in warn and WARN_FALSE in warn, warn)
    check("leaf variant omits bind", all("bind_invoke" not in text or text == WARN_TRUE for text in warn))
    cur.execute(
        "SELECT calls_used, calls_reserved FROM v15.budget_pools WHERE pool_id = %s",
        (pool,),
    )
    used, reserved = cur.fetchone()
    check("e2e pool settled", reserved == 0 and used == len(script.calls), (used, reserved, len(script.calls)))
    cur.execute(
        "SELECT recursion_available FROM v15.invokes WHERE root_invoke_id = %s AND depth = 3",
        (iid,),
    )
    check("leaf recursion disabled", cur.fetchone()[0] is False)


def test_enter_delivery(cur, wconn, server) -> None:
    scope = str(uuid.uuid4())
    layer = str(uuid.uuid4())
    add_scope(cur, scope, [], layer)
    cur.execute("COMMIT")
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid, scope=scope)
    install_hook(
        cur, "enter_nf",
        """
        BEGIN
          IF coalesce((p_snapshot #>> '{io,depth}')::int, 0) >= 2 THEN
            RETURN jsonb_build_object(
              'contract', 1, 'action', 'abort', 'fatal', false,
              'error', jsonb_build_object('code', 'V15_RECURSION_EXCEEDED', 'message', '')
            );
          END IF;
          RETURN '{"contract":1,"action":"proceed"}'::jsonb;
        END
        """,
        iid,
    )
    cur.execute("COMMIT")
    park(cur, iid)
    run_until_quiescent(server.get_uri(DB), ScriptLLM([BIND, RET]), OWNER)
    cur.execute(
        """
        SELECT c.status, c.error->>'code', s.error->>'code', p.status
        FROM v15.invokes c
        JOIN v15.statements s ON s.child_invoke_id = c.invoke_id
        JOIN v15.invokes p ON p.invoke_id = c.parent_invoke_id
        WHERE c.parent_invoke_id = %s
        """,
        (iid,),
    )
    row = cur.fetchone()
    check(
        "hook enter abort delivered",
        row[0] == "failed" and row[1] == "V15_RECURSION_EXCEEDED" and row[2] == "V15_CHILD_ERROR" and row[3] != "suspended",
        row,
    )
    scope2 = str(uuid.uuid4())
    layer2 = str(uuid.uuid4())
    add_scope(cur, scope2, [], layer2)
    cur.execute("COMMIT")
    iid2 = str(uuid.uuid4())
    open_invoke(wconn, iid2, scope=scope2)
    install_hook(
        cur, "enter_ft",
        """
        BEGIN
          IF coalesce((p_snapshot #>> '{io,depth}')::int, 0) >= 2 THEN
            RETURN jsonb_build_object(
              'contract', 1, 'action', 'abort', 'fatal', true,
              'error', jsonb_build_object('code', 'V15_BUDGET_EXHAUSTED', 'message', 'hook')
            );
          END IF;
          RETURN '{"contract":1,"action":"proceed"}'::jsonb;
        END
        """,
        iid2,
    )
    cur.execute("COMMIT")
    park(cur, iid2)
    run_until_quiescent(server.get_uri(DB), ScriptLLM([BIND]), OWNER)
    cur.execute(
        """
        SELECT depth, status, fatal, error->>'code'
        FROM v15.invokes WHERE root_invoke_id = %s ORDER BY depth
        """,
        (iid2,),
    )
    rows = cur.fetchall()
    check(
        "hook fatal expands",
        rows == [
            (1, "aborted", True, "V15_BUDGET_EXHAUSTED"),
            (2, "aborted", True, "V15_BUDGET_EXHAUSTED"),
        ],
        rows,
    )


def test_iteration_hook(cur, wconn, server) -> None:
    scope = str(uuid.uuid4())
    layer = str(uuid.uuid4())
    add_scope(cur, scope, [{"hook_key": "iteration_limit", "config": {"max": 1}}], layer)
    cur.execute("COMMIT")
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid, scope=scope)
    park(cur, iid)
    run_until_quiescent(server.get_uri(DB), ScriptLLM(["SELECT 1;", RET]), OWNER)
    cur.execute(
        "SELECT status, fatal, error->>'code', error->>'sqlstate' FROM v15.invokes WHERE invoke_id = %s",
        (iid,),
    )
    check("tighter iteration aborts before next lease", cur.fetchone() == ("failed", False, "V15_ITERATION_EXCEEDED", "P1520"))
    cur.execute(
        """
        SELECT count(*) FROM v15.llm_attempts a
        JOIN v15.llm_requests r ON r.request_id = a.request_id
        WHERE r.invoke_id = %s AND r.iteration = 1
        """,
        (iid,),
    )
    check("no attempt on the aborted iteration", cur.fetchone()[0] == 0)


def main() -> int:
    server = get_server()
    setup_db()
    conn = connect(server)
    cur = conn.cursor()
    wconn = connect(server, "v15_worker")
    test_oids(cur)
    test_decoy_and_replace(cur, wconn)
    conn.commit()
    test_synthesis(cur, wconn)
    conn.commit()
    test_abort_algebra(cur, wconn)
    conn.commit()
    test_isolation(cur, wconn)
    conn.commit()
    test_generation(cur, wconn)
    conn.commit()
    test_handlers(cur, wconn)
    conn.commit()
    test_register(cur)
    conn.commit()
    test_tool(cur, wconn)
    conn.commit()
    test_budget(cur, wconn, server)
    conn.commit()
    test_warnings_and_forcing(cur, wconn)
    conn.commit()
    test_e2e(cur, wconn, server)
    conn.commit()
    test_enter_delivery(cur, wconn, server)
    conn.commit()
    test_iteration_hook(cur, wconn, server)
    wconn.close()
    conn.close()
    print("ALL PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
