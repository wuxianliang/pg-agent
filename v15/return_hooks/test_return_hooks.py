"""Stage 11 gate: return_type hook and validate-return protocol (M2).

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
from v15.load import files_through
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


def install_hook(cur, key: str, body: str, invoke_id: str, config=None, *, grants: bool = True) -> None:
    role = f"v15_hook_{key}"
    cur.execute(
        f"CREATE ROLE {role} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT"
    )
    if grants:
        cur.execute(f"GRANT USAGE ON SCHEMA v15 TO {role}")
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
    if grants:
        cur.execute(
            f"GRANT EXECUTE ON FUNCTION v15.v15_return_validation_effect(jsonb, boolean, text) TO {role}"
        )
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


def attach_hook(cur, key: str, invoke_id: str, config, channel: str = "local") -> int:
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
        RETURNING ordinal
        """,
        (invoke_id, invoke_id, channel, json.dumps(config), key),
    )
    return cur.fetchone()[0]


def spec_fault(cur, value_sql: str, spec: dict):
    cur.execute(
        f"SELECT v15.v15_return_spec_fault({value_sql}, %s::jsonb)",
        (json.dumps(spec),),
    )
    return cur.fetchone()[0]


def spec_render(cur, spec: dict) -> str:
    cur.execute("SELECT v15.v15_return_spec_render(%s::jsonb)", (json.dumps(spec),))
    return cur.fetchone()[0]


def effect_snap(
    *,
    hook: str = "return_type",
    ordinal=0,
    max_failures=2,
    counters=None,
) -> dict:
    return {
        "span": "repl_exec",
        "phase": "complete",
        "io": {
            "result_kind": "return",
            "return_value": 1,
            "error": None,
            "capture": "",
        },
        "self": {
            "hook_key": hook,
            "ordinal": ordinal,
            "config": {"max_failures": max_failures},
        },
        "counters": {} if counters is None else counters,
    }


def call_effect(cur, snapshot: dict, valid, message: str = "x"):
    cur.execute(
        "SELECT v15.v15_return_validation_effect(%s::jsonb, %s, %s)",
        (json.dumps(snapshot), valid, message),
    )
    return parse_json(cur.fetchone()[0])


def counter_n(cur, invoke_id: str, key: str):
    cur.execute(
        "SELECT n FROM v15.hook_counters WHERE invoke_id = %s AND counter_key = %s",
        (invoke_id, key),
    )
    row = cur.fetchone()
    return None if row is None else row[0]


def message_rows(cur, invoke_id: str):
    cur.execute(
        """
        SELECT message_id, content
        FROM v15.llm_messages
        WHERE invoke_id = %s
        ORDER BY msg_seq
        """,
        (invoke_id,),
    )
    return cur.fetchall()


STRING_SPEC = {"type": "string"}
OBJECT_SPEC = {
    "type": "object",
    "required": ["n"],
    "properties": {"n": {"type": "number"}},
}
ANY_SPEC = {"anyOf": [{"type": "string"}, {"type": "null"}]}
NESTED_UNION = {
    "type": "object",
    "required": ["x"],
    "properties": {"x": {"anyOf": [{"type": "string"}, {"type": "null"}]}},
}
FROZEN = (
    (STRING_SPEC, "'1'::jsonb", "Expected string. Got jsonb number."),
    (OBJECT_SPEC, "'{}'::jsonb", "Expected object {n: number}. Missing key $.n."),
    (OBJECT_SPEC, '\'{"n":"x"}\'::jsonb', "Expected number at $.n. Got jsonb string."),
    (ANY_SPEC, "'1'::jsonb", "Expected anyOf (string | null). Got jsonb number."),
    (NESTED_UNION, '\'{"x":1}\'::jsonb', "Expected anyOf (string | null). Got jsonb number."),
)
PREFIX = "[v15 return_type] "


def continue_body(message: str, msg_id: str) -> str:
    return f"""
    BEGIN
      IF p_snapshot->>'span' = 'repl_exec'
         AND p_snapshot->>'phase' = 'complete'
         AND p_snapshot #>> '{{io,result_kind}}' = 'return' THEN
        RETURN jsonb_build_object(
          'contract', 1,
          'action', 'proceed',
          'exec_result', jsonb_build_object(
            'result_kind', 'continue',
            'return_value', 'null'::jsonb,
            'error', 'null'::jsonb
          ),
          'messages', jsonb_build_array(jsonb_build_object(
            'id', '{msg_id}',
            'role', 'user',
            'content', '{message}',
            'persistent', true
          ))
        );
      END IF;
      RETURN '{{"contract":1,"action":"proceed"}}'::jsonb;
    END
    """


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
    check("return_hooks prefix has eleven files", len(full) == 11)
    check("full load ends at return_hooks", full[-1].name == "v15_return_hooks.sql")
    check("full load keeps provider prefix", full[:10] == provider)
    check("stage through return_hooks", files_through("return_hooks") == full)


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
    install_hook(
        cur,
        "vr_raise_win",
        """
        BEGIN
          IF p_snapshot->>'span' = 'repl_exec'
             AND p_snapshot->>'phase' = 'complete'
             AND p_snapshot #>> '{io,result_kind}' = 'return' THEN
            RETURN jsonb_build_object(
              'contract', 1,
              'action', 'proceed',
              'exec_result', jsonb_build_object(
                'result_kind', 'raise',
                'return_value', 'null'::jsonb,
                'error', jsonb_build_object('code', 'V15_VALIDATION_FAILED', 'message', 'cap')
              ),
              'messages', jsonb_build_array(jsonb_build_object(
                'id', 'winner-msg',
                'role', 'user',
                'content', 'kept',
                'persistent', true
              ))
            );
          END IF;
          RETURN '{"contract":1,"action":"proceed"}'::jsonb;
        END
        """,
        iid,
    )
    ret = call_phase(cur, iid, COMPLETE_IO)
    ids = [m["id"] for m in ret.get("messages", [])]
    check("raise wins over continue", ret.get("exec_result", {}).get("result_kind") == "raise", ret)
    check("winner message survives", "winner-msg" in ids, ids)
    check("loser continue message dropped", "loser-msg" not in ids, ids)
    cur.execute(
        "SELECT count(*) FROM v15.llm_messages WHERE invoke_id = %s AND message_id = 'loser-msg'",
        (iid,),
    )
    check("loser message not stored", cur.fetchone()[0] == 0)
    cur.execute(
        "SELECT content FROM v15.llm_messages WHERE invoke_id = %s AND message_id = 'winner-msg'",
        (iid,),
    )
    check("winner message stored", cur.fetchone() == ("kept",))
    other = str(uuid.uuid4())
    open_invoke(wconn, other)
    install_hook(cur, "vr_raise_a", raise_body("one"), other)
    install_hook(cur, "vr_raise_b", raise_body("two"), other)
    ret = call_phase(cur, other, COMPLETE_IO)
    check(
        "unequal raises keep min ordinal",
        ret.get("exec_result", {}).get("result_kind") == "raise"
        and ret["exec_result"]["error"] == {"code": "V15_VALIDATION_FAILED", "message": "one"},
        ret,
    )
    merged = str(uuid.uuid4())
    open_invoke(wconn, merged)
    install_hook(cur, "vr_cont_a", continue_body("a", "cont-a"), merged)
    install_hook(cur, "vr_cont_b", continue_body("b", "cont-b"), merged)
    ret = call_phase(cur, merged, COMPLETE_IO)
    ids = [m["id"] for m in ret.get("messages", [])]
    check("equal continues merge", ret.get("exec_result", {}).get("result_kind") == "continue", ret)
    check("equal continue messages kept", "cont-a" in ids and "cont-b" in ids, ids)


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


def nest(inner: dict, wraps: int) -> dict:
    spec = inner
    for _ in range(wraps):
        spec = {"type": "array", "items": spec}
    return spec


def test_spec_and_config(cur, wconn) -> None:
    check("scalar spec valid", spec_fault(cur, "'1'::jsonb", {"type": "number"}) is None)
    check("depth 8 valid", cur.execute("SELECT v15.v15_return_spec_valid(%s::jsonb)", (json.dumps(nest({"type": "string"}, 7)),)) or cur.fetchone()[0] is True)
    cur.execute("SELECT v15.v15_return_spec_valid(%s::jsonb)", (json.dumps(nest({"type": "string"}, 8)),))
    check("depth 9 invalid", cur.fetchone()[0] is False)
    check("bad key invalid", cur.execute(
        "SELECT v15.v15_return_spec_valid(%s::jsonb)",
        (json.dumps({"type": "object", "required": ["1bad"], "properties": {"1bad": {"type": "string"}}}),),
    ) or cur.fetchone()[0] is False)
    cur.execute(
        "SELECT v15.v15_return_spec_valid(%s::jsonb)",
        (json.dumps({"anyOf": [{"type": "string"}] * 9}),),
    )
    check("anyOf 9 invalid", cur.fetchone()[0] is False)
    cur.execute("SELECT v15.v15_return_spec_valid(%s::jsonb)", (json.dumps({"enum": []}),))
    check("empty enum invalid", cur.fetchone()[0] is False)
    cur.execute("SELECT v15.v15_return_spec_valid(%s::jsonb)", (json.dumps({"type": "int"}),))
    check("unknown scalar invalid", cur.fetchone()[0] is False)
    cur.execute("SELECT v15.v15_return_spec_valid(%s::jsonb)", (json.dumps({"type": None}),))
    check("json null type invalid", cur.fetchone()[0] is False)
    cur.execute("SELECT v15.v15_return_spec_valid(%s::jsonb)", (json.dumps({"type": 1}),))
    check("numeric type invalid", cur.fetchone()[0] is False)
    cur.execute(
        "SELECT v15.v15_return_spec_valid(%s::jsonb)",
        (json.dumps({"anyOf": [{"type": None}]}),),
    )
    check("nested json null type invalid", cur.fetchone()[0] is False)
    for spec, value_sql, text in FROZEN:
        check("frozen helper " + text, spec_fault(cur, value_sql, spec) == text, spec_fault(cur, value_sql, spec))
    check(
        "sql null root",
        spec_fault(cur, "NULL::jsonb", STRING_SPEC) == "Expected string. Got SQL NULL.",
    )
    check("json null matches null", spec_fault(cur, "'null'::jsonb", {"type": "null"}) is None)
    check("json null matches any", spec_fault(cur, "'null'::jsonb", {"type": "any"}) is None)
    check("json null matches anyOf", spec_fault(cur, "'null'::jsonb", ANY_SPEC) is None)
    check("enum numeric equal", spec_fault(cur, "'1.0'::jsonb", {"enum": [1]}) is None)
    check(
        "enum render",
        spec_render(cur, {"enum": [1, "a"]}) == 'enum (1, "a")',
        spec_render(cur, {"enum": [1, "a"]}),
    )
    multi = {
        "type": "object",
        "required": ["z", "a"],
        "properties": {
            "z": {"type": "string"},
            "a": {"type": "number"},
            "m": {"type": "boolean"},
            "b": {"type": "string"},
        },
    }
    check(
        "object render order",
        spec_render(cur, multi) == "object {z: string, a: number, b?: string, m?: boolean}",
        spec_render(cur, multi),
    )
    check(
        "open object extra key",
        spec_fault(cur, '\'{"n":1,"extra":true}\'::jsonb', OBJECT_SPEC) is None,
    )
    check("empty array matches", spec_fault(cur, "'[]'::jsonb", {"type": "array", "items": STRING_SPEC}) is None)
    check(
        "array path",
        spec_fault(cur, "'[1,\"x\"]'::jsonb", {"type": "array", "items": {"type": "number"}})
        == "Expected number at $[1]. Got jsonb string.",
    )
    check(
        "invalid spec fault",
        spec_fault(cur, "'1'::jsonb", {"type": "nope"}) == "config spec invalid",
    )
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    shapes = (
        {"type": "string"},
        {"type": "array", "items": {"type": "number"}},
        OBJECT_SPEC,
        ANY_SPEC,
        {"enum": ["a", 1, True]},
    )
    for spec in shapes:
        other = str(uuid.uuid4())
        open_invoke(wconn, other)
        attach_hook(cur, "return_type", other, {"spec": spec, "max_failures": 1})
    null_id = str(uuid.uuid4())
    open_invoke(wconn, null_id)
    attach_hook(cur, "return_type", null_id, {"spec": STRING_SPEC, "max_failures": None})
    zero_id = str(uuid.uuid4())
    open_invoke(wconn, zero_id)
    attach_hook(cur, "return_type", zero_id, {"spec": STRING_SPEC, "max_failures": 0})
    check("five shapes and null/zero max install", True)
    bad_id = str(uuid.uuid4())
    open_invoke(wconn, bad_id)
    fails(
        cur,
        """
        INSERT INTO v15.invoke_hooks (
          invoke_id, ordinal, hook_def_id, channel, config, state
        )
        SELECT %s, 9, d.hook_def_id, 'local', %s::jsonb, '{}'::jsonb
        FROM v15.hook_defs d WHERE d.hook_key = 'return_type'
        """,
        (bad_id, json.dumps({"max_failures": 1})),
        "P1524",
        "return_type missing spec is P1524",
    )
    fails(
        cur,
        """
        INSERT INTO v15.invoke_hooks (
          invoke_id, ordinal, hook_def_id, channel, config, state
        )
        SELECT %s, 9, d.hook_def_id, 'local', %s::jsonb, '{}'::jsonb
        FROM v15.hook_defs d WHERE d.hook_key = 'return_type'
        """,
        (bad_id, json.dumps({"spec": STRING_SPEC, "max_failures": 1, "extra": 1})),
        "P1524",
        "return_type extra key is P1524",
    )
    fails(
        cur,
        """
        INSERT INTO v15.invoke_hooks (
          invoke_id, ordinal, hook_def_id, channel, config, state
        )
        SELECT %s, 9, d.hook_def_id, 'local', %s::jsonb, '{}'::jsonb
        FROM v15.hook_defs d WHERE d.hook_key = 'return_type'
        """,
        (bad_id, json.dumps({"spec": {"type": "nope"}, "max_failures": 1})),
        "P1524",
        "bad spec shape is P1524",
    )
    fails(
        cur,
        """
        INSERT INTO v15.invoke_hooks (
          invoke_id, ordinal, hook_def_id, channel, config, state
        )
        SELECT %s, 9, d.hook_def_id, 'local', %s::jsonb, '{}'::jsonb
        FROM v15.hook_defs d WHERE d.hook_key = 'return_type'
        """,
        (bad_id, json.dumps({"spec": nest({"type": "string"}, 8), "max_failures": 1})),
        "P1524",
        "depth 9 spec is P1524",
    )
    fails(
        cur,
        """
        INSERT INTO v15.invoke_hooks (
          invoke_id, ordinal, hook_def_id, channel, config, state
        )
        SELECT %s, 9, d.hook_def_id, 'local', %s::jsonb, '{}'::jsonb
        FROM v15.hook_defs d WHERE d.hook_key = 'return_type'
        """,
        (bad_id, json.dumps({"spec": {"anyOf": [{"type": "string"}] * 9}, "max_failures": 1})),
        "P1524",
        "anyOf over 8 is P1524",
    )
    fails(
        cur,
        """
        INSERT INTO v15.invoke_hooks (
          invoke_id, ordinal, hook_def_id, channel, config, state
        )
        SELECT %s, 9, d.hook_def_id, 'local', %s::jsonb, '{}'::jsonb
        FROM v15.hook_defs d WHERE d.hook_key = 'return_type'
        """,
        (bad_id, json.dumps({"spec": {"type": None}, "max_failures": 1})),
        "P1524",
        "json null type is P1524",
    )
    fails(
        cur,
        """
        INSERT INTO v15.invoke_hooks (
          invoke_id, ordinal, hook_def_id, channel, config, state
        )
        SELECT %s, 9, d.hook_def_id, 'local', %s::jsonb, '{}'::jsonb
        FROM v15.hook_defs d WHERE d.hook_key = 'return_type'
        """,
        (bad_id, json.dumps({"spec": {"anyOf": [{"type": None}]}, "max_failures": 1})),
        "P1524",
        "nested json null type is P1524",
    )
    fails(
        cur,
        """
        INSERT INTO v15.invoke_hooks (
          invoke_id, ordinal, hook_def_id, channel, config, state
        )
        SELECT %s, 9, d.hook_def_id, 'local', %s::jsonb, '{}'::jsonb
        FROM v15.hook_defs d WHERE d.hook_key = 'return_type'
        """,
        (bad_id, json.dumps({"spec": STRING_SPEC, "max_failures": -1})),
        "P1524",
        "negative max_failures is P1524",
    )
    fails(
        cur,
        """
        INSERT INTO v15.invoke_hooks (
          invoke_id, ordinal, hook_def_id, channel, config, state
        )
        SELECT %s, 9, d.hook_def_id, 'baseline', %s::jsonb, '{}'::jsonb
        FROM v15.hook_defs d WHERE d.hook_key = 'return_type'
        """,
        (bad_id, json.dumps({"spec": STRING_SPEC, "max_failures": 1})),
        "P1524",
        "return_type baseline channel is P1524",
    )
    install_hook(cur, "validate_return", "BEGIN RETURN '{\"contract\":1,\"action\":\"proceed\"}'::jsonb; END", iid, {"max_failures": 1})
    install_hook(cur, "validate_return_q", "BEGIN RETURN '{\"contract\":1,\"action\":\"proceed\"}'::jsonb; END", iid, {"max_failures": None})
    install_hook(cur, "validate_returnx", "BEGIN RETURN '{\"contract\":1,\"action\":\"proceed\"}'::jsonb; END", iid, {})
    fails(
        cur,
        """
        INSERT INTO v15.invoke_hooks (
          invoke_id, ordinal, hook_def_id, channel, config, state
        )
        SELECT %s, 40, d.hook_def_id, 'local', '{}'::jsonb, '{}'::jsonb
        FROM v15.hook_defs d WHERE d.hook_key = 'validate_return'
        """,
        (bad_id,),
        "P1524",
        "validate_return empty config is P1524",
    )
    install_hook(cur, "custom_probe", "BEGIN RETURN '{\"contract\":1,\"action\":\"proceed\"}'::jsonb; END", iid, {"whatever": 1})
    cur.execute(
        """
        SELECT baseline_required,
               pg_catalog.pg_get_userbyid(owner_role),
               handler_digest = v15.v15_handler_digest(regprocedure)
        FROM v15.hook_defs
        WHERE hook_key = 'return_type'
        """
    )
    check("return_type hook_defs row", cur.fetchone() == (False, "v15_hook_return_type", True))
    cur.execute(
        """
        SELECT has_function_privilege('v15_hook_return_type', 'v15.v15_return_spec_fault(jsonb,jsonb)', 'EXECUTE'),
               has_function_privilege('v15_worker', 'v15.v15_return_spec_fault(jsonb,jsonb)', 'EXECUTE')
        """
    )
    check("spec fault grants", cur.fetchone() == (True, False))


def test_prompt_and_match(cur, wconn) -> None:
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    ordinal = attach_hook(cur, "return_type", iid, {"spec": OBJECT_SPEC, "max_failures": 1})
    entered = call_phase_enter(cur, iid)
    msgs = entered.get("messages") or []
    check("prompt once on first enter", len(msgs) == 1 and msgs[0]["id"] == f"return_type:prompt:{ordinal}", msgs)
    check(
        "prompt text",
        msgs[0]["content"] == "[v15 return_type] The return value must match this jsonb spec: object {n: number}",
        msgs[0]["content"],
    )
    check("prompt persistent user", msgs[0]["role"] == "user" and msgs[0]["persistent"] is True)
    again = call_phase_enter(cur, iid, next_attempt_n=2)
    check("retry does not repeat prompt", "messages" not in again or not again.get("messages"), again)
    later = call_phase_enter(cur, iid, iteration=1, next_attempt_n=1)
    check("later iteration does not prompt", "messages" not in later or not later.get("messages"), later)
    matched = call_phase(cur, iid, {
        "result_kind": "return",
        "return_value": {"n": 1},
        "error": None,
        "capture": "",
    })
    check("matching spec proceeds", matched.get("action") == "proceed" and "exec_result" not in matched, matched)
    mismatched = call_phase(cur, iid, {
        "result_kind": "return",
        "return_value": {},
        "error": None,
        "capture": "",
    })
    got = mismatched.get("messages", [{}])[0].get("content")
    check(
        "mismatch continue uses frozen text",
        mismatched.get("exec_result", {}).get("result_kind") == "continue" and got == PREFIX + FROZEN[1][2],
        mismatched,
    )
    check("complete does not bump", counter_n(cur, iid, f"return_type:{ordinal}") is None)
    for spec, value_sql, text in FROZEN:
        sample = str(uuid.uuid4())
        open_invoke(wconn, sample)
        attach_hook(cur, "return_type", sample, {"spec": spec, "max_failures": 0})
        cur.execute(
            f"""
            SELECT v15.v15_on_phase(
              %s, 0, 'repl_exec', 'complete',
              jsonb_build_object(
                'result_kind', 'return',
                'return_value', {value_sql},
                'error', 'null'::jsonb,
                'capture', ''
              )
            )
            """,
            (sample,),
        )
        ret = parse_json(cur.fetchone()[0])
        check(
            "frozen handler " + text,
            ret.get("exec_result", {}).get("error", {}).get("message") == PREFIX + text,
            ret,
        )
    dirty = str(uuid.uuid4())
    open_invoke(wconn, dirty)
    attach_hook(cur, "return_type", dirty, {"spec": STRING_SPEC, "max_failures": 1})
    cur.execute("ALTER TABLE v15.invoke_hooks DISABLE TRIGGER invoke_hooks_optional")
    try:
        cur.execute(
            """
            UPDATE v15.invoke_hooks h
            SET config = '{"spec":{"type":"nope"},"max_failures":1}'::jsonb
            FROM v15.hook_defs d
            WHERE h.invoke_id = %s AND h.hook_def_id = d.hook_def_id AND d.hook_key = 'return_type'
            """,
            (dirty,),
        )
        ret = call_phase(cur, dirty, {
            "result_kind": "return",
            "return_value": 1,
            "error": None,
            "capture": "",
        })
    finally:
        cur.execute("ALTER TABLE v15.invoke_hooks ENABLE TRIGGER invoke_hooks_optional")
    check(
        "invalid spec is a mismatch",
        ret.get("messages", [{}])[0].get("content") == PREFIX + "config spec invalid",
        ret,
    )


def call_phase_enter(cur, invoke_id: str, iteration: int = 0, next_attempt_n: int = 1):
    cur.execute(
        "SELECT v15.v15_on_phase(%s, %s, 'llm_query', 'enter', %s::jsonb)",
        (invoke_id, iteration, json.dumps({"iteration": iteration, "next_attempt_n": next_attempt_n})),
    )
    return parse_json(cur.fetchone()[0])


def validator_body(message: str, valid_sql: str = "false") -> str:
    return f"""
    BEGIN
      IF p_snapshot->>'span' IS DISTINCT FROM 'repl_exec'
         OR p_snapshot->>'phase' IS DISTINCT FROM 'complete'
         OR p_snapshot #>> '{{io,result_kind}}' IS DISTINCT FROM 'return' THEN
        RETURN '{{"contract":1,"action":"proceed"}}'::jsonb;
      END IF;
      IF {valid_sql} THEN
        RETURN v15.v15_return_validation_effect(p_snapshot, true, 'ok');
      END IF;
      RETURN v15.v15_return_validation_effect(p_snapshot, false, '{message}');
    END
    """


def test_validator_phase(cur, wconn) -> None:
    cur.connection.commit()
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    install_hook(cur, "validate_return_bad", validator_body("raw-bad"), iid, {"max_failures": 2})
    install_hook(cur, "validate_return_ok", validator_body("nope", "true"), iid, {"max_failures": 0})
    ret = call_phase(cur, iid, COMPLETE_IO)
    ids = [m["id"] for m in ret.get("messages", [])]
    check("only invalid validator emits", len(ids) == 1 and ids[0].startswith("validate_return_bad:"), ids)
    check("raw message unwrapped", ret["messages"][0]["content"] == "raw-bad", ret)
    check("validator continue", ret.get("exec_result", {}).get("result_kind") == "continue")
    cap = str(uuid.uuid4())
    open_invoke(wconn, cap)
    install_hook(cur, "validate_return_cap", validator_body("capped"), cap, {"max_failures": 0})
    raised = call_phase(cur, cap, COMPLETE_IO)
    check(
        "validator cap is raise",
        raised.get("exec_result", {}).get("result_kind") == "raise"
        and raised["exec_result"]["error"] == {"code": "V15_VALIDATION_FAILED", "message": "capped"}
        and "messages" not in raised,
        raised,
    )
    skipped = str(uuid.uuid4())
    open_invoke(wconn, skipped)
    install_hook(cur, "validate_return_skip", validator_body("should-not"), skipped, {"max_failures": 0})
    ret = call_phase_named(cur, skipped, "invoke", "complete", {"outcome": "completed"})
    check("invoke complete does not validate", ret.get("action") == "proceed" and "exec_result" not in ret, ret)
    cur.execute(
        """
        SELECT count(*) FROM v15.invoke_events
        WHERE invoke_id = %s AND event_class = 'audit' AND payload->>'op' = 'handler_exception'
        """,
        (skipped,),
    )
    check("invoke complete has no handler exception", cur.fetchone()[0] == 0)


def call_phase_named(cur, invoke_id: str, span: str, phase: str, io: dict):
    cur.execute(
        "SELECT v15.v15_on_phase(%s, 0, %s, %s, %s::jsonb)",
        (invoke_id, span, phase, json.dumps(io)),
    )
    return parse_json(cur.fetchone()[0])


def test_known_code(cur) -> None:
    cur.execute("SELECT v15.v15_govern_known_code('V15_VALIDATION_FAILED')")
    check("known_code V15_VALIDATION_FAILED", cur.fetchone()[0] is True)


def test_effect_builder(cur) -> None:
    got = call_effect(cur, effect_snap(), True)
    check("p_valid true proceeds", got == {"contract": 1, "action": "proceed"}, got)
    got = call_effect(cur, effect_snap(max_failures=0), None)
    check(
        "p_valid null raises",
        got.get("exec_result", {}).get("result_kind") == "raise",
        got,
    )
    got = call_effect(cur, effect_snap(max_failures=2), False)
    check(
        "absent counter continues",
        got.get("exec_result", {}).get("result_kind") == "continue"
        and got.get("messages", [{}])[0].get("id") == "return_type:0:0",
        got,
    )
    got = call_effect(
        cur,
        effect_snap(max_failures=2, counters={"return_type:0": -1}),
        False,
    )
    check(
        "negative counter raises",
        got.get("exec_result", {}).get("result_kind") == "raise"
        and "messages" not in got,
        got,
    )
    got = call_effect(
        cur,
        effect_snap(max_failures=2, counters={"return_type:0": "bad"}),
        False,
    )
    check("bad counter raises", got.get("exec_result", {}).get("result_kind") == "raise", got)
    got = call_effect(cur, effect_snap(ordinal=2147483648, max_failures=2), False)
    check(
        "overflow ordinal raises",
        got.get("exec_result", {}).get("result_kind") == "raise"
        and "messages" not in got,
        got,
    )
    got = call_effect(cur, effect_snap(hook="iteration_limit", max_failures=2), False)
    check(
        "non family hook raises",
        got.get("exec_result", {}).get("result_kind") == "raise"
        and "messages" not in got,
        got,
    )


def test_register_shape(cur) -> None:
    cur.execute("CREATE ROLE v15_hook_bad_own2 NOLOGIN NOSUPERUSER")
    cur.execute(
        """
        CREATE FUNCTION v15.bad_own2(jsonb) RETURNS jsonb
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog
        AS $fn$ SELECT '{"contract":1,"action":"proceed"}'::jsonb $fn$
        """
    )
    cur.execute("ALTER FUNCTION v15.bad_own2(jsonb) OWNER TO v15_owner")
    cur.execute("REVOKE ALL ON FUNCTION v15.bad_own2(jsonb) FROM PUBLIC")
    cur.execute("GRANT EXECUTE ON FUNCTION v15.bad_own2(jsonb) TO v15_owner")
    fails(
        cur,
        "SELECT v15.v15_register_hook('bad_own2', 'v15.bad_own2(jsonb)'::regprocedure, false)",
        code="P1537",
        label="wrong owner still P1537",
    )


def test_register_grants(cur, wconn) -> None:
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    install_hook(
        cur,
        "validate_return_grant",
        validator_body("no-manual"),
        iid,
        {"max_failures": 0},
        grants=False,
    )
    ret = call_phase(cur, iid, COMPLETE_IO)
    check(
        "register_hook grants rejection without manual ACL",
        ret.get("exec_result", {}).get("result_kind") == "raise"
        and ret["exec_result"]["error"] == {
            "code": "V15_VALIDATION_FAILED",
            "message": "no-manual",
        },
        ret,
    )


def scratch_gone(cur, invoke_id: str) -> bool:
    cur.execute(
        "SELECT count(*) FROM pg_catalog.pg_namespace WHERE nspname = 's_' || replace(%s, '-', '')",
        (invoke_id,),
    )
    return cur.fetchone()[0] == 0


def test_prompt_lands(server, cur, wconn) -> None:
    park(cur)
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    ordinal = attach_hook(cur, "return_type", iid, {"spec": STRING_SPEC, "max_failures": 1})
    cur.execute("COMMIT")
    run_until_quiescent(server.get_uri(DB), Script(['SELECT jaz."return"(\'"ok"\'::jsonb);']), OWNER)
    rows = message_rows(cur, iid)
    prompts = [row for row in rows if row[0] == f"return_type:prompt:{ordinal}"]
    check("prompt landed once", len(prompts) == 1 and prompts[0][1].endswith("string"), prompts)
    check("matching finish does not bump", counter_n(cur, iid, f"return_type:{ordinal}") is None)
    cur.execute("SELECT status, return_value::text FROM v15.invokes WHERE invoke_id = %s", (iid,))
    got = cur.fetchone()
    check("matching return completes", got[0] == "completed", got)


def test_cap_paths(server, cur, wconn) -> None:
    park(cur)
    zero = str(uuid.uuid4())
    open_invoke(wconn, zero)
    zord = attach_hook(cur, "return_type", zero, {"spec": STRING_SPEC, "max_failures": 0})
    cur.execute("COMMIT")
    run_until_quiescent(server.get_uri(DB), Script(["SELECT jaz.\"return\"('1'::jsonb);"]), OWNER)
    cur.execute(
        """
        SELECT status, fatal, return_value IS NULL, error->>'code', error->>'sqlstate', error->>'message'
        FROM v15.invokes WHERE invoke_id = %s
        """,
        (zero,),
    )
    check(
        "max_failures 0 raises immediately",
        cur.fetchone() == ("failed", False, True, "V15_VALIDATION_FAILED", "P1540", PREFIX + FROZEN[0][2]),
    )
    check("max_failures 0 does not bump", counter_n(cur, zero, f"return_type:{zord}") is None)
    check("max_failures 0 clears scratch", scratch_gone(cur, zero))
    cur.execute(
        """
        SELECT span, outcome FROM v15.invoke_events
        WHERE invoke_id = %s AND event_class = 'span' AND phase = 'exit'
        ORDER BY seq
        """,
        (zero,),
    )
    exits = cur.fetchall()
    check(
        "raise exits failed",
        ("repl_exec", "failed") in exits and ("invoke", "failed") in exits,
        exits,
    )
    cur.execute(
        """
        SELECT count(*) FROM v15.invoke_events
        WHERE invoke_id = %s AND event_class = 'span' AND span = 'invoke' AND phase = 'complete'
        """,
        (zero,),
    )
    check("cap writes no invoke complete", cur.fetchone()[0] == 0)
    park(cur)
    one = str(uuid.uuid4())
    open_invoke(wconn, one)
    ordinal = attach_hook(cur, "return_type", one, {"spec": STRING_SPEC, "max_failures": 1})
    cur.execute("COMMIT")
    run_until_quiescent(
        server.get_uri(DB),
        Script([
            "SELECT jaz.\"return\"('1'::jsonb);",
            "SELECT jaz.\"return\"('1'::jsonb);",
        ]),
        OWNER,
    )
    check("finish bumps once before cap", counter_n(cur, one, f"return_type:{ordinal}") == 1)
    ids = [row[0] for row in message_rows(cur, one)]
    check("counted id uses pre-increment n", f"return_type:{ordinal}:0" in ids, ids)
    check("cap does not write next counted id", f"return_type:{ordinal}:1" not in ids, ids)
    check("prompt still once after second iteration", ids.count(f"return_type:prompt:{ordinal}") == 1, ids)
    cur.execute("SELECT error->>'code', error->>'sqlstate' FROM v15.invokes WHERE invoke_id = %s", (one,))
    check("second mismatch raises", cur.fetchone() == ("V15_VALIDATION_FAILED", "P1540"))
    park(cur)
    free = str(uuid.uuid4())
    open_invoke(wconn, free)
    ford = attach_hook(cur, "return_type", free, {"spec": STRING_SPEC, "max_failures": None})
    cur.execute("COMMIT")
    run_until_quiescent(
        server.get_uri(DB),
        Script([
            "SELECT jaz.\"return\"('1'::jsonb);",
            "SELECT jaz.\"return\"('1'::jsonb);",
            "SELECT jaz.\"return\"('\"ok\"'::jsonb);",
        ]),
        OWNER,
    )
    check("null max never caps", counter_n(cur, free, f"return_type:{ford}") == 2)
    cur.execute("SELECT status FROM v15.invokes WHERE invoke_id = %s", (free,))
    check("null max still completes", cur.fetchone() == ("completed",))


def test_child_delivery(server, cur, wconn) -> None:
    park(cur)
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    attach_hook(cur, "return_type", iid, {"spec": STRING_SPEC, "max_failures": 0}, channel="propagating")
    cur.execute("COMMIT")
    run_until_quiescent(
        server.get_uri(DB),
        Script([
            "SELECT jaz.bind_invoke('out', '{}'::jsonb);\nSELECT jaz.\"return\"(jaz.var('out'));",
            "SELECT jaz.\"return\"('1'::jsonb);",
            "SELECT jaz.\"return\"('\"ok\"'::jsonb);",
        ]),
        OWNER,
    )
    cur.execute(
        "SELECT invoke_id::text FROM v15.invokes WHERE parent_invoke_id = %s",
        (iid,),
    )
    kid = cur.fetchone()[0]
    cur.execute(
        "SELECT status, error->>'code', error->>'sqlstate' FROM v15.invokes WHERE invoke_id = %s",
        (kid,),
    )
    check("child keeps P1540", cur.fetchone() == ("failed", "V15_VALIDATION_FAILED", "P1540"))
    cur.execute(
        """
        SELECT status, error->>'code', error->>'sqlstate'
        FROM v15.statements
        WHERE invoke_id = %s AND iteration = 0 AND stmt_index = 0
        """,
        (iid,),
    )
    check("parent statement is P1528", cur.fetchone() == ("failed", "V15_CHILD_ERROR", "P1528"))
    check("child scratch cleared", scratch_gone(cur, kid))


def test_handler_exception(server, cur, wconn) -> None:
    park(cur)
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    install_hook(
        cur,
        "validate_return_boom",
        """
        BEGIN
          IF p_snapshot->>'span' = 'repl_exec' AND p_snapshot->>'phase' = 'complete' THEN
            RAISE EXCEPTION 'optional boom' USING ERRCODE = 'P0001';
          END IF;
          RETURN '{"contract":1,"action":"proceed"}'::jsonb;
        END
        """,
        iid,
        {"max_failures": 0},
    )
    cur.execute("COMMIT")
    run_until_quiescent(server.get_uri(DB), Script([RETURN_SQL]), OWNER)
    cur.execute("SELECT status FROM v15.invokes WHERE invoke_id = %s", (iid,))
    check("handler exception does not reject return", cur.fetchone() == ("completed",))
    cur.execute(
        """
        SELECT payload->>'op', payload->>'hook_key', payload->>'sqlstate'
        FROM v15.invoke_events
        WHERE invoke_id = %s AND event_class = 'audit' AND payload->>'op' = 'handler_exception'
        """,
        (iid,),
    )
    check("handler exception audited", cur.fetchone() == ("handler_exception", "validate_return_boom", "P0001"))
    check("handler exception does not bump", counter_n(cur, iid, "validate_return_boom:4") is None)
    cur.execute("SELECT count(*) FROM v15.hook_counters WHERE invoke_id = %s", (iid,))
    check("handler exception leaves counters empty", cur.fetchone()[0] == 0)


def test_abort_normalizes(server, cur, wconn) -> None:
    park(cur)
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    install_hook(
        cur,
        "vr_abort_p1540",
        """
        BEGIN
          IF p_snapshot->>'span' = 'repl_exec' AND p_snapshot->>'phase' = 'complete' THEN
            RETURN jsonb_build_object(
              'contract', 1,
              'action', 'abort',
              'fatal', false,
              'error', jsonb_build_object('code', 'V15_VALIDATION_FAILED', 'message', 'nope')
            );
          END IF;
          RETURN '{"contract":1,"action":"proceed"}'::jsonb;
        END
        """,
        iid,
        {},
    )
    phase = str(uuid.uuid4())
    open_invoke(wconn, phase)
    install_hook(
        cur,
        "vr_abort_phase",
        """
        BEGIN
          RETURN jsonb_build_object(
            'contract', 1,
            'action', 'abort',
            'fatal', false,
            'error', jsonb_build_object('code', 'V15_VALIDATION_FAILED', 'message', 'nope')
          );
        END
        """,
        phase,
        {},
    )
    ret = call_phase(cur, phase, COMPLETE_IO)
    check("abort P1540 normalizes in phase", ret.get("code") == "V15_HOOK_ABORT" and ret.get("action") == "abort", ret)
    cur.execute(
        """
        UPDATE v15.invokes
        SET status = 'failed', fatal = false,
            lease_owner = NULL, lease_until = NULL,
            error = '{"sqlstate":"P1520","code":"V15_ITERATION_EXCEEDED","message":"parked"}'::jsonb
        WHERE invoke_id = %s
        """,
        (phase,),
    )
    cur.execute("COMMIT")
    run_until_quiescent(server.get_uri(DB), Script([RETURN_SQL]), OWNER)
    cur.execute(
        "SELECT status, error->>'code', error->>'sqlstate' FROM v15.invokes WHERE invoke_id = %s",
        (iid,),
    )
    check("abort P1540 commits as P1538", cur.fetchone() == ("failed", "V15_HOOK_ABORT", "P1538"))


def test_forcing_raise_finish(server, cur, wconn) -> None:
    park(cur)
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    ford = attach_hook(cur, "budget_forcing", iid, {"max_rejections": 2})
    attach_hook(cur, "vr_raise_win", iid, {})
    cur.execute("COMMIT")
    run_until_quiescent(server.get_uri(DB), Script([RETURN_SQL]), OWNER)
    check("forcing plus raise does not bump", counter_n(cur, iid, f"budget_forcing:{ford}") is None)
    cur.execute("SELECT count(*) FROM v15.hook_counters WHERE invoke_id = %s", (iid,))
    check("forcing plus raise leaves counters at 0", cur.fetchone()[0] == 0)
    ids = [row[0] for row in message_rows(cur, iid)]
    check("winner kept after finish", "winner-msg" in ids, ids)
    check("real forcing id dropped", not any(item.startswith("budget_forcing:") for item in ids), ids)
    cur.execute("SELECT error->>'code', error->>'sqlstate' FROM v15.invokes WHERE invoke_id = %s", (iid,))
    check("forcing plus raise finishes P1540", cur.fetchone() == ("V15_VALIDATION_FAILED", "P1540"))


def test_two_validators(server, cur, wconn) -> None:
    park(cur)
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    install_hook(
        cur,
        "validate_return_one",
        validator_body("raw-one", "p_snapshot #>> '{io,return_value}' = 'stop'"),
        iid,
        {"max_failures": None},
    )
    install_hook(
        cur,
        "validate_return_two",
        validator_body("raw-two", "p_snapshot #>> '{io,return_value}' = 'stop'"),
        iid,
        {"max_failures": None},
    )
    cur.execute(
        """
        SELECT h.ordinal, d.hook_key
        FROM v15.invoke_hooks h
        JOIN v15.hook_defs d ON d.hook_def_id = h.hook_def_id
        WHERE h.invoke_id = %s AND d.hook_key LIKE 'validate_return_%%'
        ORDER BY h.ordinal
        """,
        (iid,),
    )
    rows = cur.fetchall()
    cur.execute("COMMIT")
    run_until_quiescent(
        server.get_uri(DB),
        Script([
            "SELECT jaz.\"return\"('1'::jsonb);",
            "SELECT jaz.\"return\"('\"stop\"'::jsonb);",
        ]),
        OWNER,
    )
    check("two validators bump independently", (
        counter_n(cur, iid, f"{rows[0][1]}:{rows[0][0]}"),
        counter_n(cur, iid, f"{rows[1][1]}:{rows[1][0]}"),
    ) == (1, 1), rows)
    contents = [row[1] for row in message_rows(cur, iid)]
    check("raw validator texts stored", "raw-one" in contents and "raw-two" in contents, contents)
    cur.execute("SELECT status, error->>'code' FROM v15.invokes WHERE invoke_id = %s", (iid,))
    got = cur.fetchone()
    check("validators do not wrap as V15_RAISE", got == ("completed", None), got)


def test_two_cap_validators(server, cur, wconn) -> None:
    park(cur)
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    install_hook(
        cur,
        "validate_return_alpha",
        validator_body("alpha-msg"),
        iid,
        {"max_failures": 0},
    )
    install_hook(
        cur,
        "validate_return_beta",
        validator_body("beta-msg"),
        iid,
        {"max_failures": 0},
    )
    cur.execute("COMMIT")
    run_until_quiescent(server.get_uri(DB), Script([RETURN_SQL]), OWNER)
    cur.execute(
        """
        SELECT status, error->>'code', error->>'sqlstate', error->>'message'
        FROM v15.invokes WHERE invoke_id = %s
        """,
        (iid,),
    )
    got = cur.fetchone()
    check(
        "two cap validators finish P1540",
        got == ("failed", "V15_VALIDATION_FAILED", "P1540", "alpha-msg"),
        got,
    )
    cur.execute("SELECT count(*) FROM v15.hook_counters WHERE invoke_id = %s", (iid,))
    check("two cap validators do not bump", cur.fetchone()[0] == 0)
    ids = [row[0] for row in message_rows(cur, iid)]
    check(
        "losing cap raise messages not stored",
        not any(item.startswith("validate_return_beta:") for item in ids),
        ids,
    )


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
        test_spec_and_config(cur, worker)
        test_prompt_and_match(cur, worker)
        test_validator_phase(cur, worker)
        test_known_code(cur)
        test_effect_builder(cur)
        test_register_shape(cur)
        test_register_grants(cur, worker)
        cur.execute("COMMIT")
        test_finish_raise(server, cur, worker)
        test_prompt_lands(server, cur, worker)
        test_cap_paths(server, cur, worker)
        test_child_delivery(server, cur, worker)
        test_handler_exception(server, cur, worker)
        test_abort_normalizes(server, cur, worker)
        test_forcing_raise_finish(server, cur, worker)
        test_two_validators(server, cur, worker)
        test_two_cap_validators(server, cur, worker)
    finally:
        worker.close()
        admin.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
