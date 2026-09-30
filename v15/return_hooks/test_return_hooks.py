"""Stage 11 gate: return-validation core (M1).

Run: uv run python v15/return_hooks/test_return_hooks.py  (exit 0 = pass)
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
from v15.load import SQL_LOAD_ORDER, files_through
from v15.protocol.render_prompt import render_system
from v15.return_hooks.setup_db import DB, main as setup_db
from v15.worker import run_until_quiescent

SCOPE = "00000000-0000-4000-8000-0000000000b1"
OWNER = "return-hooks-owner"
RETURN_SQL = 'SELECT jaz."return"(\'{"ok":true}\'::jsonb);'
COMPLETE_IO = {
    "result_kind": "return",
    "return_value": {"ok": True},
    "error": None,
    "capture": "",
}


class Script:
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)

    def complete(self, logical_digest: str, n: int, request: dict, llm_config=None) -> dict:
        if not self.replies:
            raise AssertionError(f"script exhausted at n={n}")
        return {"content": self.replies.pop(0)}


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


def system_text() -> str:
    return render_system(recursion_available=True, bindings=[])


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


def open_invoke(conn, invoke_id: str) -> None:
    cur = conn.cursor()
    cur.execute("SET LOCAL lock_timeout = '2s'")
    cur.execute("SET LOCAL statement_timeout = '30s'")
    cur.execute(
        """
        SELECT v15.v15_open_invoke(%s, %s, NULL, '[]'::jsonb, NULL, NULL, %s, NULL)
        """,
        (invoke_id, SCOPE, system_text()),
    )
    conn.commit()


def call_phase(cur, invoke_id: str, io: dict):
    cur.execute(
        "SELECT v15.v15_on_phase(%s, %s, %s, %s, %s::jsonb)",
        (invoke_id, 0, "repl_exec", "complete", json.dumps(io)),
    )
    return parse_json(cur.fetchone()[0])


def install_hook(cur, key: str, body: str, invoke_id: str, config=None) -> None:
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
    cur.execute(
        """
        INSERT INTO v15.invoke_hooks (
          invoke_id, ordinal, hook_def_id, channel, config, state
        )
        SELECT %s,
               (SELECT coalesce(max(ordinal), -1) + 1
                FROM v15.invoke_hooks WHERE invoke_id = %s),
               d.hook_def_id, 'local', %s::jsonb, '{}'::jsonb
        FROM v15.hook_defs d
        WHERE d.hook_key = %s
        """,
        (invoke_id, invoke_id, json.dumps(config or {}), key),
    )


def raise_body(message: str, code: str = "V15_VALIDATION_FAILED") -> str:
    return f"""
    BEGIN
      IF p_snapshot->>'span' = 'repl_exec'
         AND p_snapshot->>'phase' = 'complete'
         AND p_snapshot #>> '{{io,result_kind}}' = 'return' THEN
        RETURN jsonb_build_object(
          'contract', 1,
          'action', 'proceed',
          'exec_result', jsonb_build_object(
            'result_kind', 'raise',
            'return_value', 'null'::jsonb,
            'error', jsonb_build_object('code', '{code}', 'message', '{message}')
          )
        );
      END IF;
      RETURN '{{"contract":1,"action":"proceed"}}'::jsonb;
    END
    """


def test_load_order() -> None:
    govern = files_through("govern")
    provider = files_through("provider")
    full = files_through("return_hooks")
    check("govern prefix has nine files", len(govern) == 9 and govern[-1].name == "v15_govern.sql")
    check(
        "provider prefix has ten files",
        len(provider) == 10 and provider[-1].name == "v15_provider.sql" and provider[:9] == govern,
    )
    check("full load has eleven files", len(SQL_LOAD_ORDER) == 11 and len(full) == 11)
    check("full load ends at return_hooks", full[-1].name == "v15_return_hooks.sql")
    check("full load keeps provider prefix", full[:10] == provider)
    check("stage through return_hooks", files_through("return_hooks") == SQL_LOAD_ORDER)


def test_one_dispatcher(cur) -> None:
    cur.execute(
        """
        SELECT count(*)
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'v15' AND p.proname = 'v15_on_phase'
        """
    )
    check("one v15_on_phase", cur.fetchone()[0] == 1)


def test_check_return_raise(cur, wconn) -> None:
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    install_hook(cur, "vr_raise", raise_body("nope"), iid)
    ret = call_phase(cur, iid, COMPLETE_IO)
    check(
        "return to raise accepted",
        ret.get("exec_result", {}).get("result_kind") == "raise"
        and ret["exec_result"]["error"]["code"] == "V15_VALIDATION_FAILED"
        and ret["exec_result"]["return_value"] is None,
        ret,
    )
    bad = str(uuid.uuid4())
    open_invoke(wconn, bad)
    install_hook(cur, "vr_wrong", raise_body("nope", "V15_RAISE"), bad)
    fails(
        cur,
        "SELECT v15.v15_on_phase(%s, 0, 'repl_exec', 'complete', %s::jsonb)",
        (bad, json.dumps(COMPLETE_IO)),
        "P1506",
        "wrong raise code is P1506",
    )
    long_id = str(uuid.uuid4())
    open_invoke(wconn, long_id)
    install_hook(cur, "vr_long", raise_body("x" * 1025), long_id)
    fails(
        cur,
        "SELECT v15.v15_on_phase(%s, 0, 'repl_exec', 'complete', %s::jsonb)",
        (long_id, json.dumps(COMPLETE_IO)),
        "P1506",
        "overlong raise message is P1506",
    )


def test_raise_wins(cur, wconn) -> None:
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    install_hook(
        cur,
        "vr_cont",
        """
        BEGIN
          IF p_snapshot->>'span' = 'repl_exec'
             AND p_snapshot->>'phase' = 'complete'
             AND p_snapshot #>> '{io,result_kind}' = 'return' THEN
            RETURN jsonb_build_object(
              'contract', 1,
              'action', 'proceed',
              'exec_result', jsonb_build_object(
                'result_kind', 'continue',
                'return_value', 'null'::jsonb,
                'error', 'null'::jsonb
              ),
              'messages', jsonb_build_array(jsonb_build_object(
                'id', 'loser-msg',
                'role', 'user',
                'content', 'lose',
                'persistent', true
              ))
            );
          END IF;
          RETURN '{"contract":1,"action":"proceed"}'::jsonb;
        END
        """,
        iid,
    )
    install_hook(cur, "vr_raise_win", raise_body("cap"), iid)
    ret = call_phase(cur, iid, COMPLETE_IO)
    ids = [m["id"] for m in ret.get("messages", [])]
    check("raise wins over continue", ret.get("exec_result", {}).get("result_kind") == "raise", ret)
    check("loser continue message dropped", "loser-msg" not in ids, ids)
    cur.execute(
        "SELECT count(*) FROM v15.llm_messages WHERE invoke_id = %s AND message_id = 'loser-msg'",
        (iid,),
    )
    check("loser message not stored", cur.fetchone()[0] == 0)
    other = str(uuid.uuid4())
    open_invoke(wconn, other)
    install_hook(cur, "vr_raise_a", raise_body("one"), other)
    install_hook(cur, "vr_raise_b", raise_body("two"), other)
    fails(
        cur,
        "SELECT v15.v15_on_phase(%s, 0, 'repl_exec', 'complete', %s::jsonb)",
        (other, json.dumps(COMPLETE_IO)),
        "P1535",
        "unequal raises still conflict",
    )


def test_counter_parse(cur, wconn) -> None:
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    cur.execute(
        """
        INSERT INTO v15.invoke_hooks (
          invoke_id, ordinal, hook_def_id, channel, config, state
        )
        SELECT %s,
               (SELECT coalesce(max(ordinal), -1) + 1
                FROM v15.invoke_hooks WHERE invoke_id = %s),
               d.hook_def_id, 'local', '{"max_rejections":2}'::jsonb, '{}'::jsonb
        FROM v15.hook_defs d
        WHERE d.hook_key = 'budget_forcing'
        RETURNING ordinal
        """,
        (iid, iid),
    )
    ordinal = cur.fetchone()[0]
    ident = f"budget_forcing:{ordinal}:0"
    cur.execute(
        "SELECT v15.v15_loop_accept_forcing(%s, 0, 0, %s::jsonb)",
        (
            iid,
            json.dumps([
                {"id": ident},
                {"id": ident},
                {"id": f"return_type:prompt:{ordinal}"},
                {"id": "context_window_warning:1:0"},
                {"id": "budget_forcing:2147483648:0"},
            ]),
        ),
    )
    cur.execute(
        """
        SELECT n FROM v15.hook_counters
        WHERE invoke_id = %s AND counter_key = %s
        """,
        (iid, f"budget_forcing:{ordinal}"),
    )
    check("duplicate counted id bumps once", cur.fetchone() == (1,))
    cur.execute(
        "SELECT v15.v15_loop_accept_forcing(%s, 0, 0, %s::jsonb)",
        (iid, json.dumps([{"id": "return_type:prompt:4"}])),
    )
    cur.execute(
        "SELECT count(*) FROM v15.hook_counters WHERE invoke_id = %s",
        (iid,),
    )
    check("prompt id does not bump", cur.fetchone()[0] == 1)
    fails(
        cur,
        "SELECT v15.v15_loop_accept_forcing(%s, 0, 0, %s::jsonb)",
        (iid, json.dumps([{"id": "budget_forcing:99:0"}])),
        "P1523",
        "missing ordinal is P1523",
    )


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


def test_finish_raise(server, cur, wconn) -> None:
    park(cur)
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    install_hook(cur, "vr_finish", raise_body("rejected"), iid)
    cur.execute("COMMIT")
    run_until_quiescent(server.get_uri(DB), Script([RETURN_SQL]), OWNER)
    cur.execute(
        """
        SELECT status, fatal, return_value IS NULL,
               error->>'code', error->>'sqlstate', error->>'message'
        FROM v15.invokes WHERE invoke_id = %s
        """,
        (iid,),
    )
    got = cur.fetchone()
    check(
        "finish return to raise",
        got == ("failed", False, True, "V15_VALIDATION_FAILED", "P1540", "rejected"),
        got,
    )
    cur.execute(
        """
        SELECT it.result_kind, h.repl_output, h.repl_exception->>'code',
               h.repl_exception->>'sqlstate'
        FROM v15.repl_history h
        JOIN v15.iterations it
          ON it.invoke_id = h.invoke_id AND it.iteration = h.iteration
        WHERE h.invoke_id = %s
        """,
        (iid,),
    )
    check("raise history keeps P1540", cur.fetchone() == ("raise", "", "V15_VALIDATION_FAILED", "P1540"))
    cur.execute(
        """
        SELECT count(*) FROM v15.invoke_events
        WHERE invoke_id = %s AND event_class = 'span'
          AND span = 'invoke' AND phase = 'complete'
        """,
        (iid,),
    )
    check("raise writes no invoke complete", cur.fetchone()[0] == 0)
    cur.execute(
        """
        SELECT kind, status FROM v15.statements
        WHERE invoke_id = %s ORDER BY stmt_index
        """,
        (iid,),
    )
    check("return statement stays done", cur.fetchone() == ("return", "done"))
    cur.execute(
        "SELECT count(*) FROM v15.hook_counters WHERE invoke_id = %s",
        (iid,),
    )
    check("raise path does not bump", cur.fetchone()[0] == 0)


def main() -> int:
    test_load_order()
    setup_db()
    server = get_server()
    admin = connect(server)
    worker = connect(server, "v15_worker")
    try:
        admin.autocommit = False
        worker.autocommit = False
        cur = admin.cursor()
        test_one_dispatcher(cur)
        test_check_return_raise(cur, worker)
        test_raise_wins(cur, worker)
        test_counter_parse(cur, worker)
        cur.execute("COMMIT")
        test_finish_raise(server, cur, worker)
    finally:
        worker.close()
        admin.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
