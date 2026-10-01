"""Stage 12 gate: deterministic trajectory replay.

Run: uv run python v15/replay/test_replay.py  (exit 0 = pass)
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import uuid
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import psycopg2
from psycopg2 import sql
from psycopg2.extras import Json

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v15.load import SQL_LOAD_ORDER, files_through, load_stage
from v15.protocol.render_prompt import render_system
from v15.replay.replay import ReplayAttemptShape, ReplayLLM
from v15.replay.setup_db import DB, main as setup_db
from v15.replay.trace import (
    DIGEST_SCHEME,
    TraceInvalid,
    dumps,
    export_trace,
    load_trace,
    projection,
    validate_trace,
    write_trace,
)
from v15.worker import run_until_quiescent

SCOPE = "00000000-0000-4000-8000-0000000000b1"
OWNER = "replay-owner"
PLAY = "agent_v15_replay_play"
PLAY2 = "agent_v15_replay_play2"
COST = Decimal("1.25")
RET = "SELECT jaz.\"return\"('{\"ok\":true}'::jsonb);"
RAISE_SQL = "SELECT jaz.\"raise\"('boom');"
RET_A = "SELECT jaz.\"return\"('{\"who\":\"a\"}'::jsonb);"
RET_B = "SELECT jaz.\"return\"('{\"who\":\"b\"}'::jsonb);"
BIND_ONE = (
    "SELECT jaz.bind_invoke('kid', '{}'::jsonb);\n"
    "SELECT jaz.\"return\"(jaz.var('kid'));"
)
BIND_TWO = (
    "SELECT jaz.bind_invoke('a', '{}'::jsonb);\n"
    "SELECT jaz.bind_invoke('b', '{}'::jsonb);\n"
    "SELECT jaz.\"return\"(jsonb_build_object('a', jaz.var('a'), 'b', jaz.var('b')));"
)
TABLES = {
    "budget_pools", "tool_catalog", "config_profiles", "config_scopes",
    "config_layers", "governance_manifest", "invokes", "iterations",
    "statements", "llm_requests", "llm_attempts", "llm_messages",
    "repl_history", "bindings", "exec_context", "invoke_events",
    "hook_defs", "invoke_hooks", "blackboard", "hook_counters", "tool_grants",
}
DUMMY_DSN = "host=/no/such/replay-socket dbname=replay_no_connect"


def one_step_trace(**step_over) -> dict:
    step = {
        "iteration": 0,
        "result_kind": "return",
        "logical_digest": "a" * 32,
        "response_content": "SELECT 1;",
        "recorded_cost_usd": Decimal("1.25"),
        "statements": [],
        "repl_output": "",
        "repl_exception_code": None,
    }
    step.update(step_over)
    return {
        "version": 1,
        "digest_scheme": DIGEST_SCHEME,
        "pool": {"calls_limit": Decimal(40), "cost_limit": Decimal("100.5")},
        "pool_outcome": {"calls_used": Decimal("4E1"), "cost_used": Decimal("1.25")},
        "invokes": [{
            "path": "",
            "depth": 1,
            "status": "completed",
            "fatal": False,
            "error_code": None,
            "return_value": {"ok": True},
            "steps": [step],
            "bindings": [],
            "blackboard": [],
        }],
    }


class RecordingLLM:
    def __init__(self, replies: list[dict]) -> None:
        self.replies = list(replies)

    def complete(self, logical_digest: str, n: int, request: dict, llm_config=None) -> dict:
        if not self.replies:
            raise AssertionError("script exhausted")
        return dict(self.replies.pop(0))


def paid(content: str) -> dict:
    return {"content": content, "cost_usd": COST}


def sample_step(**over) -> dict:
    step = {
        "iteration": 0,
        "result_kind": "return",
        "logical_digest": "a" * 32,
        "response_content": "SELECT 1;",
        "recorded_cost_usd": Decimal("0"),
        "statements": [],
        "repl_output": "",
        "repl_exception_code": None,
    }
    step.update(over)
    return step


def sample_invoke(**over) -> dict:
    inv = {
        "path": "",
        "depth": 1,
        "status": "completed",
        "fatal": False,
        "error_code": None,
        "return_value": {"ok": True},
        "steps": [sample_step()],
        "bindings": [],
        "blackboard": [],
    }
    inv.update(over)
    return inv


def sample_trace(**over) -> dict:
    trace = {
        "version": 1,
        "digest_scheme": DIGEST_SCHEME,
        "pool": {"calls_limit": Decimal("40.0"), "cost_limit": Decimal("1.25")},
        "pool_outcome": {"calls_used": Decimal(1), "cost_used": Decimal("1.25")},
        "invokes": [sample_invoke()],
    }
    trace.update(over)
    return trace


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f": {detail}" if detail != "" else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def connect(server, user: str | None = None, database: str = DB):
    uri = server.get_uri(database)
    if user is None:
        return psycopg2.connect(uri)
    parsed = urlparse(uri)
    host = (parse_qs(parsed.query).get("host") or [None])[0]
    return psycopg2.connect(host=host, dbname=database, user=user)


def parse_json(value):
    return json.loads(value) if isinstance(value, str) else value


def system_text() -> str:
    return render_system(recursion_available=True, bindings=[])


def base_messages() -> list[dict]:
    return [{
        "message_id": "seed:system",
        "role": "system",
        "kind": "system",
        "content": system_text(),
    }]


def fails(cur, sql_text: str, params=None, code: str | None = None, label: str = "") -> None:
    cur.execute("SAVEPOINT sp")
    try:
        cur.execute(sql_text, params)
    except psycopg2.Error as exc:
        check(label, code is None or exc.pgcode == code, f"{exc.pgcode} {str(exc).splitlines()[0]}")
        cur.execute("ROLLBACK TO SAVEPOINT sp")
        return
    cur.execute("ROLLBACK TO SAVEPOINT sp")
    raise AssertionError(f"{label}: expected {code}")


def open_invoke(conn, invoke_id: str, pool_id: str | None = None) -> None:
    cur = conn.cursor()
    cur.execute("SET LOCAL lock_timeout = '2s'")
    cur.execute("SET LOCAL statement_timeout = '30s'")
    cur.execute(
        "SELECT v15.v15_open_invoke(%s, %s, NULL, '[]'::jsonb, %s, NULL, %s, NULL)",
        (invoke_id, SCOPE, pool_id, system_text()),
    )
    conn.commit()


def make_pool(cur) -> str:
    pool_id = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO v15.budget_pools (pool_id, calls_limit, cost_limit) VALUES (%s, 40, 100)",
        (pool_id,),
    )
    return pool_id


def install_hook(cur, key: str, body: str, invoke_id: str) -> None:
    role = f"v15_hook_{key}"
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
    if cur.fetchone() is None:
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
               (SELECT coalesce(max(ordinal), -1) + 1 FROM v15.invoke_hooks WHERE invoke_id = %s),
               d.hook_def_id, 'local', '{}'::jsonb, '{}'::jsonb
        FROM v15.hook_defs d WHERE d.hook_key = %s
        """,
        (invoke_id, invoke_id, key),
    )


def pin_hook_body(content: str) -> str:
    return f"""
      BEGIN
        IF p_snapshot->>'span' = 'llm_query' AND p_snapshot->>'phase' = 'enter'
           AND coalesce(p_snapshot#>>'{{io,iteration}}', p_snapshot->>'iteration') = '0' THEN
          RETURN jsonb_build_object(
            'contract', 1, 'action', 'proceed',
            'messages', jsonb_build_array(jsonb_build_object(
              'id', 'replay-pin', 'role', 'user', 'content', '{content}', 'persistent', true
            ))
          );
        END IF;
        RETURN '{{"contract":1,"action":"proceed"}}'::jsonb;
      END
    """


def create_loaded_db(server, name: str) -> None:
    conn = psycopg2.connect(server.get_uri("postgres"))
    conn.autocommit = True
    try:
        cur = conn.cursor()
        cur.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s", (name,))
        cur.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
        cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    finally:
        conn.close()
    load_stage(server, name, "replay")


def spans(cur, invoke_id: str) -> list[tuple]:
    cur.execute(
        """
        SELECT span, phase, outcome
        FROM v15.invoke_events
        WHERE invoke_id = %s AND event_class = 'span' AND span = 'llm_query'
        ORDER BY seq
        """,
        (invoke_id,),
    )
    return cur.fetchall()


def llm_query_groups(cur, invoke_id: str) -> list[list[str]]:
    cur.execute(
        """
        SELECT phase
        FROM v15.invoke_events
        WHERE invoke_id = %s AND event_class = 'span' AND span = 'llm_query'
        ORDER BY seq
        """,
        (invoke_id,),
    )
    phases = [row[0] for row in cur.fetchall()]
    return [phases[i:i + 4] for i in range(0, len(phases), 4)] if phases else []


def park_open(cur) -> None:
    cur.execute(
        """
        UPDATE v15.invokes
        SET status = 'aborted',
            fatal = true,
            error = jsonb_build_object(
              'code', 'V15_HOOK_ABORT',
              'sqlstate', 'P1538',
              'message', 'parked'
            ),
            lease_owner = NULL,
            lease_until = NULL
        WHERE status IN ('pending', 'runnable', 'leased')
        """
    )


def test_load_order() -> None:
    hooks = files_through("return_hooks")
    replay = files_through("replay")
    check("replay prefix has twelve files", len(replay) == 12)
    check("replay prefix ends at replay", replay[-1].name == "v15_replay.sql")
    check("stage through replay", replay == SQL_LOAD_ORDER[:12])
    check("replay keeps return_hooks prefix", replay[:11] == hooks and len(hooks) == 11)


def test_trace_local() -> None:
    try:
        load_trace("{not json")
        raise AssertionError("bad json")
    except TraceInvalid:
        check("bad json is local", True)
    try:
        validate_trace({
            "version": 2, "digest_scheme": DIGEST_SCHEME,
            "pool": None, "pool_outcome": None, "invokes": [],
        })
        raise AssertionError("bad version")
    except TraceInvalid:
        check("bad version is local", True)
    dup = sample_trace(
        pool=None, pool_outcome=None,
        invokes=[sample_invoke(steps=[sample_step(), sample_step()])],
    )
    try:
        validate_trace(dup)
        raise AssertionError("duplicate")
    except TraceInvalid as exc:
        check("duplicate coordinate is local", "duplicate" in str(exc))

    src = sample_trace()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "trace.json"
        write_trace(path, src)
        loaded = load_trace(path)
        check("write/load projection", projection(src) == projection(loaded))
        text = path.read_text()
        check("calls_limit json int", '"calls_limit": 40' in text)
        check("cost_limit json number", '"cost_limit": 1.25' in text)
        check("cost_used json number", '"cost_used": 1.25' in text)

    bind = {"name": "a", "kind": "var", "provenance": "repl", "tool_name": None, "value": 1}
    try:
        validate_trace(sample_trace(invokes=[sample_invoke(bindings=[bind, dict(bind)])]))
        raise AssertionError("dup bind")
    except TraceInvalid:
        check("duplicate binding names rejected", True)
    board = {"key": "k", "value": 1}
    try:
        validate_trace(sample_trace(invokes=[sample_invoke(blackboard=[board, dict(board)])]))
        raise AssertionError("dup board")
    except TraceInvalid:
        check("duplicate blackboard keys rejected", True)
    bad_stmt = {
        "stmt_index": Decimal("1.5"),
        "sql_digest": "b" * 32,
        "kind": "plain",
        "status": "done",
        "bind_name": None,
    }
    try:
        validate_trace(sample_trace(invokes=[sample_invoke(steps=[sample_step(statements=[bad_stmt])])]))
        raise AssertionError("stmt_index")
    except TraceInvalid:
        check("non-integer stmt_index rejected", True)
    validate_trace(sample_trace(invokes=[sample_invoke(steps=[
        sample_step(logical_digest=None, response_content=None, result_kind="continue"),
    ])]))
    check("empty digest null body legal", True)

    import v15.replay.replay as replay_mod
    connected = {"n": 0}
    orig = replay_mod.connect_worker

    def boom(*_a, **_k):
        connected["n"] += 1
        raise AssertionError("opened DB connection")

    replay_mod.connect_worker = boom
    try:
        extra = sample_trace(invokes=[dict(sample_invoke(), extra_key=1)])
        try:
            ReplayLLM("dsn", OWNER, extra)
            raise AssertionError("extra key")
        except TraceInvalid:
            check("closed-set keys before connect", connected["n"] == 0, connected)
        typed = sample_trace(invokes=[sample_invoke(depth="1")])
        try:
            ReplayLLM("dsn", OWNER, typed)
            raise AssertionError("bad type")
        except TraceInvalid:
            check("field type before connect", connected["n"] == 0, connected)
        llm = ReplayLLM("dsn", OWNER, sample_trace())
        try:
            llm.complete("a" * 32, 2, {"attempt_id": str(uuid.uuid4())})
            raise AssertionError("n!=1")
        except ReplayAttemptShape:
            check("n!=1 is local ReplayAttemptShape", connected["n"] == 0, connected)
        try:
            llm.complete("a" * 32, 1, {})
            raise AssertionError("missing attempt_id")
        except ReplayAttemptShape:
            check("missing attempt_id is local ReplayAttemptShape", connected["n"] == 0, connected)
    finally:
        replay_mod.connect_worker = orig

    typed = sample_trace(invokes=[sample_invoke(status="leased")])
    try:
        validate_trace(typed)
        raise AssertionError("status closed set")
    except TraceInvalid:
        check("status closed set is local", True)
    typed = sample_trace(invokes=[sample_invoke(fatal=1)])
    try:
        validate_trace(typed)
        raise AssertionError("fatal type")
    except TraceInvalid:
        check("fatal type error is local", True)
    slash = sample_trace(invokes=[sample_invoke(steps=[sample_step(statements=[{
        "stmt_index": 0,
        "sql_digest": "b" * 32,
        "kind": "bind_invoke",
        "status": "done",
        "bind_name": "kid/x",
    }])])])
    try:
        validate_trace(slash)
        raise AssertionError("slash bind_name")
    except TraceInvalid:
        check("slash bind_name is local", True)
    try:
        validate_trace(sample_trace(invokes=[sample_invoke(steps=[sample_step(response_content=None)])]))
        raise AssertionError("digest body")
    except TraceInvalid:
        check("non-empty digest requires str body", True)
    compact = dumps(one_step_trace()).replace(" ", "").replace("\n", "")
    check("recorded_cost_usd 1.25 is json number", '"recorded_cost_usd":1.25' in compact)
    check("cost not quoted str", '"recorded_cost_usd":"1.25"' not in compact)

    sentinel = "\x1eDEC0\x1e"
    colliding = sample_trace(invokes=[sample_invoke(
        return_value=sentinel,
        steps=[sample_step(recorded_cost_usd=Decimal("1.25"), response_content=sentinel)],
    )])
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "collide.json"
        write_trace(path, colliding)
        loaded = load_trace(path)
        check("placeholder string preserved", loaded["invokes"][0]["return_value"] == sentinel)
        check(
            "decimal beside placeholder string",
            loaded["invokes"][0]["steps"][0]["recorded_cost_usd"] == Decimal("1.25"),
        )
        check("placeholder write/load projection", projection(colliding) == projection(loaded))

    bind_bad = {"name": "x", "kind": "var", "provenance": "repl", "tool_name": None, "value": object()}
    try:
        validate_trace(sample_trace(invokes=[sample_invoke(bindings=[bind_bad])]))
        raise AssertionError("object value")
    except TraceInvalid:
        check("unsupported binding value object rejected", True)
    try:
        validate_trace(sample_trace(invokes=[sample_invoke(blackboard=[{"key": "k", "value": 1.25}])]))
        raise AssertionError("float value")
    except TraceInvalid:
        check("float blackboard value rejected", True)
    try:
        validate_trace(sample_trace(invokes=[sample_invoke(bindings=[{
            "name": "x", "kind": "var", "provenance": "repl", "tool_name": None,
            "value": {1: "x"},
        }])]))
        raise AssertionError("non-str key")
    except TraceInvalid:
        check("non-str dict key rejected", True)
    try:
        validate_trace(sample_trace(invokes=[sample_invoke(bindings=[{
            "name": "x", "kind": "var", "provenance": "repl", "tool_name": None,
            "value": Decimal("NaN"),
        }])]))
        raise AssertionError("nan")
    except TraceInvalid:
        check("NaN Decimal rejected", True)
    try:
        validate_trace(sample_trace(invokes=[sample_invoke(bindings=[{
            "name": "x", "kind": "var", "provenance": "repl", "tool_name": None,
            "value": Decimal("Infinity"),
        }])]))
        raise AssertionError("inf")
    except TraceInvalid:
        check("Infinity Decimal rejected", True)

    bind_z = {"name": "Z", "kind": "var", "provenance": "repl", "tool_name": None, "value": 1}
    bind_a = {"name": "a", "kind": "var", "provenance": "repl", "tool_name": None, "value": 2}
    validate_trace(sample_trace(invokes=[sample_invoke(bindings=[bind_z, bind_a])]))
    check("mixed-case binding byte order accepted", True)
    try:
        validate_trace(sample_trace(invokes=[sample_invoke(bindings=[bind_a, bind_z])]))
        raise AssertionError("binding order")
    except TraceInvalid:
        check("mixed-case binding reverse rejected", True)



def test_sqlstate_superset(cur) -> None:
    cur.execute("SELECT v15.v15_io_sqlstate('V15_PROVIDER_REJECTED')")
    check("P1539 kept", cur.fetchone()[0] == "P1539")
    cur.execute("SELECT v15.v15_io_sqlstate('V15_VALIDATION_FAILED')")
    check("io map still omits P1540", cur.fetchone()[0] is None)
    cur.execute("SELECT v15.v15_loop_sqlstate('V15_VALIDATION_FAILED')")
    check("P1540 stays on loop map", cur.fetchone()[0] == "P1540")
    cur.execute(
        "SELECT v15.v15_io_sqlstate('V15_REPLAY_DIVERGED'), v15.v15_io_sqlstate('V15_REPLAY_MISSING')"
    )
    check("P1541 P1542 mapped", cur.fetchone() == ("P1541", "P1542"))
    cur.execute(
        """
        SELECT v15.v15_govern_known_code('V15_VALIDATION_FAILED'),
               v15.v15_govern_known_code('V15_PROVIDER_REJECTED'),
               v15.v15_govern_known_code('V15_REPLAY_DIVERGED'),
               v15.v15_govern_known_code('V15_REPLAY_MISSING')
        """
    )
    check("known-code superset", cur.fetchone() == (True, True, True, True))
    cur.execute("SAVEPOINT p1541")
    try:
        cur.execute("DO $$ BEGIN RAISE EXCEPTION 'V15_REPLAY_DIVERGED' USING ERRCODE = 'P1541'; END $$")
        raise AssertionError("P1541 RAISE")
    except psycopg2.Error as exc:
        check("P1541 can RAISE", exc.pgcode == "P1541", exc.pgcode)
        cur.execute("ROLLBACK TO SAVEPOINT p1541")


def test_no_new_tables(cur) -> None:
    cur.execute(
        """
        SELECT c.relname FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'v15' AND c.relkind = 'r' ORDER BY 1
        """
    )
    names = {row[0] for row in cur.fetchall()}
    check("no new v15 tables", names == TABLES, names - TABLES)


def test_acl(admin, worker) -> None:
    cur = admin.cursor()
    worker_ok = {
        "v15.v15_replay_attempt_context(uuid)": True,
        "v15.v15_replay_assert_digest(uuid,text,text)": True,
        "v15.v15_replay_missing(uuid,text)": True,
        "v15.v15_replay_export(uuid)": True,
        "v15.v15_replay_invoke_path(uuid)": False,
        "v15.v15_replay_lock_attempt(uuid,text)": False,
    }
    for signature, allowed in worker_ok.items():
        cur.execute(
            """
            SELECT has_function_privilege('v15_worker', %s, 'EXECUTE'),
                   has_function_privilege('v15_repl', %s, 'EXECUTE'),
                   has_function_privilege('public', %s, 'EXECUTE')
            """,
            (signature, signature, signature),
        )
        got = cur.fetchone()
        check(f"ACL {signature}", got == (allowed, False, False), got)
        cur.execute(
            """
            SELECT pg_get_userbyid(p.proowner), p.prosecdef, p.proconfig
            FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE p.oid = %s::regprocedure
            """,
            (signature,),
        )
        owner, definer, config = cur.fetchone()
        check(f"owner {signature}", owner == "v15_owner" and definer is True, (owner, definer))
        check(f"search_path {signature}", config == ["search_path=pg_catalog"], config)
    worker.rollback()
    try:
        worker.cursor().execute("SELECT 1 FROM v15.invokes LIMIT 1")
        raise AssertionError("worker selected invokes")
    except psycopg2.Error as exc:
        check("worker cannot SELECT invokes", exc.pgcode == "42501", exc.pgcode)
    worker.rollback()
    worker.cursor().execute("SET ROLE v15_repl")
    try:
        worker.cursor().execute("SELECT v15.v15_replay_export(NULL)")
        raise AssertionError("repl executed export")
    except psycopg2.Error as exc:
        check("repl cannot execute export", exc.pgcode == "42501", exc.pgcode)
    finally:
        worker.rollback()


def test_same_txn_guards(server, admin, worker) -> None:
    iid = str(uuid.uuid4())
    open_invoke(worker, iid)
    wcur = worker.cursor()
    wcur.execute("SELECT v15.v15_claim(%s, %s, '30 seconds'::interval)", (iid, OWNER))
    fence = wcur.fetchone()[0]
    wcur.execute(
        "SELECT v15.v15_begin_llm(%s, %s, %s, %s::jsonb)",
        (iid, fence, OWNER, json.dumps(base_messages())),
    )
    opened = parse_json(wcur.fetchone()[0])
    attempt = opened["attempt_id"]
    digest = opened["logical_digest"]
    wrong = "0" * 32 if digest != "0" * 32 else "1" * 32
    try:
        wcur.execute(
            "SELECT v15.v15_replay_assert_digest(%s, %s, %s)",
            (attempt, OWNER, wrong),
        )
        raise AssertionError("bad digest")
    except psycopg2.Error as exc:
        check("bad digest P1541", exc.pgcode == "P1541", exc.pgcode)
        check("P1541 detail is two digests", digest in str(exc) and wrong in str(exc), str(exc))
    worker.rollback()
    acur = admin.cursor()
    acur.execute("SELECT count(*) FROM v15.llm_attempts WHERE attempt_id = %s", (attempt,))
    check("P1541 rolled back attempt", acur.fetchone()[0] == 0)
    acur.execute("SELECT status FROM v15.invokes WHERE invoke_id = %s", (iid,))
    check("P1541 left invoke unclaimed", acur.fetchone()[0] == "runnable")
    admin.commit()

    iid = str(uuid.uuid4())
    open_invoke(worker, iid)
    wcur = worker.cursor()
    wcur.execute("SELECT v15.v15_claim(%s, %s, '30 seconds'::interval)", (iid, OWNER))
    fence = wcur.fetchone()[0]
    wcur.execute(
        "SELECT v15.v15_begin_llm(%s, %s, %s, %s::jsonb)",
        (iid, fence, OWNER, json.dumps(base_messages())),
    )
    attempt = parse_json(wcur.fetchone()[0])["attempt_id"]
    try:
        wcur.execute("SELECT v15.v15_replay_missing(%s, %s)", (attempt, OWNER))
        raise AssertionError("missing")
    except psycopg2.Error as exc:
        check("same-txn direct v15_replay_missing P1542", exc.pgcode == "P1542", exc.pgcode)
    worker.rollback()
    acur.execute("SELECT count(*) FROM v15.llm_attempts WHERE attempt_id = %s", (attempt,))
    check("P1542 rolled back attempt", acur.fetchone()[0] == 0)
    acur.execute("SELECT status FROM v15.invokes WHERE invoke_id = %s", (iid,))
    check("P1542 left invoke unclaimed", acur.fetchone()[0] == "runnable")
    acur.execute("SELECT count(*) FROM v15.llm_requests WHERE invoke_id = %s", (iid,))
    check("P1542 rolled back request", acur.fetchone()[0] == 0)
    admin.commit()

    iid = str(uuid.uuid4())
    open_invoke(worker, iid)
    wcur = worker.cursor()
    wcur.execute("SELECT v15.v15_claim(%s, %s, '30 seconds'::interval)", (iid, OWNER))
    fence = wcur.fetchone()[0]
    wcur.execute(
        "SELECT v15.v15_begin_llm(%s, %s, %s, %s::jsonb)",
        (iid, fence, OWNER, json.dumps(base_messages())),
    )
    opened = parse_json(wcur.fetchone()[0])
    worker.commit()
    missing_trace = sample_trace(
        pool=None, pool_outcome=None,
        invokes=[sample_invoke(steps=[sample_step(logical_digest=None, response_content=None, result_kind="continue")])],
    )
    llm = ReplayLLM(server.get_uri(DB), OWNER, missing_trace)
    try:
        llm.complete(opened["logical_digest"], 1, {"attempt_id": opened["attempt_id"]})
        raise AssertionError("missing frame")
    except psycopg2.Error as exc:
        check("driver missing frame is P1542 not local shape", exc.pgcode == "P1542", exc.pgcode)
    park_open(admin.cursor())
    admin.commit()

    iid = str(uuid.uuid4())
    open_invoke(worker, iid)
    wcur = worker.cursor()
    wcur.execute("SELECT v15.v15_claim(%s, %s, '30 seconds'::interval)", (iid, OWNER))
    fence = wcur.fetchone()[0]
    wcur.execute(
        "SELECT v15.v15_begin_llm(%s, %s, %s, %s::jsonb)",
        (iid, fence, OWNER, json.dumps(base_messages())),
    )
    opened = parse_json(wcur.fetchone()[0])
    fails(
        wcur, "SELECT v15.v15_replay_assert_digest(%s, %s, %s)",
        (opened["attempt_id"], OWNER, "not-a-digest"), "P1524", "non-hex digest P1524",
    )
    fails(
        wcur, "SELECT v15.v15_replay_assert_digest(%s, %s, %s)",
        (opened["attempt_id"], "other-owner", opened["logical_digest"]),
        "P1523", "owner mismatch",
    )
    worker.rollback()
    fails(
        admin.cursor(), "SELECT v15.v15_replay_export(%s)", (str(uuid.uuid4()),),
        "P1522", "non-worker export P1522",
    )
    admin.rollback()


def test_settled_second_begin_and_export(server, admin, worker) -> None:
    park_open(admin.cursor())
    admin.commit()
    iid = str(uuid.uuid4())
    open_invoke(worker, iid)
    run_until_quiescent(server.get_uri(DB), RecordingLLM([paid(RET)]), OWNER)
    acur = admin.cursor()
    acur.execute("SELECT attempt_id FROM v15.llm_attempts a JOIN v15.llm_requests r ON r.request_id = a.request_id WHERE r.invoke_id = %s", (iid,))
    attempt = acur.fetchone()[0]
    admin.commit()
    fails(
        worker.cursor(), "SELECT v15.v15_replay_assert_digest(%s, %s, %s)",
        (attempt, OWNER, "a" * 32), "P1502", "settled assert P1502",
    )
    worker.rollback()
    wcur = worker.cursor()
    wcur.execute("SELECT v15.v15_claim(%s, %s, '30 seconds'::interval)", (iid, OWNER))
    check("completed invoke not claimable", wcur.fetchone()[0] is None)
    worker.commit()
    fails(
        worker.cursor(), "SELECT v15.v15_begin_llm(%s, 1, %s, %s::jsonb)",
        (iid, OWNER, json.dumps(base_messages())), "P1523", "second begin P1523",
    )
    worker.rollback()
    under = str(uuid.uuid4())
    open_invoke(worker, under)
    fails(
        worker.cursor(), "SELECT v15.v15_replay_export(%s)", (under,),
        "P1523", "export unterminated P1523",
    )
    worker.rollback()
    acur.execute(
        "UPDATE v15.llm_requests SET status = 'open' WHERE invoke_id = %s",
        (iid,),
    )
    admin.commit()
    fails(
        worker.cursor(), "SELECT v15.v15_replay_export(%s)", (iid,),
        "P1523", "export open request P1523",
    )
    worker.rollback()
    acur.execute(
        "UPDATE v15.llm_requests SET status = 'settled' WHERE invoke_id = %s",
        (iid,),
    )
    acur.execute(
        """
        UPDATE v15.llm_attempts a
        SET status = 'unknown'
        FROM v15.llm_requests r
        WHERE a.request_id = r.request_id AND r.invoke_id = %s
        """,
        (iid,),
    )
    admin.commit()
    fails(
        worker.cursor(), "SELECT v15.v15_replay_export(%s)", (iid,),
        "P1523", "export non-settled attempt P1523",
    )
    worker.rollback()
    acur.execute(
        """
        UPDATE v15.llm_attempts a
        SET status = 'settled'
        FROM v15.llm_requests r
        WHERE a.request_id = r.request_id AND r.invoke_id = %s
        """,
        (iid,),
    )
    admin.commit()
    acur.execute(
        """
        SELECT a.request_id, a.lease_owner, a.pool_id, a.reserved_calls, a.reserved_cost, a.request, a.response
        FROM v15.llm_attempts a JOIN v15.llm_requests r ON r.request_id = a.request_id
        WHERE r.invoke_id = %s AND a.n = 1
        """,
        (iid,),
    )
    req, owner, pool_id, calls, cost, request, response = acur.fetchone()
    extra = str(uuid.uuid4())
    acur.execute(
        """
        INSERT INTO v15.llm_attempts (
          attempt_id, request_id, n, status, fence, lease_owner, lease_until,
          pool_id, reserved_calls, reserved_cost, call_started, calls_charged, request, response
        ) VALUES (%s, %s, 2, 'settled', 1, NULL, NULL, %s, %s, %s, true, true, %s, %s)
        """,
        (extra, req, pool_id, calls, cost, Json(request), Json(response)),
    )
    admin.commit()
    fails(
        worker.cursor(), "SELECT v15.v15_replay_export(%s)", (iid,),
        "P1523", "export multi-attempt n<>1 P1523",
    )
    worker.rollback()
    acur.execute("DELETE FROM v15.llm_attempts WHERE attempt_id = %s", (extra,))
    admin.commit()


def test_supply_still_reserved(admin, worker) -> None:
    iid = str(uuid.uuid4())
    open_invoke(worker, iid)
    cur = admin.cursor()
    install_hook(
        cur,
        "bad_supply",
        "BEGIN RETURN jsonb_build_object('contract', 1, 'action', 'proceed', 'supply_llm_response', '1'::jsonb); END",
        iid,
    )
    admin.commit()
    phases = [
        ("invoke", "complete", {"outcome": "completed"}),
        ("llm_query", "enter", {"iteration": 0, "next_attempt_n": 1}),
        ("llm_query", "send", {
            "iteration": 0,
            "logical_digest": "a" * 32,
            "input_chars": 0,
            "enter_messages": None,
            "enter_overlay": None,
        }),
        ("llm_query", "complete", {"attempt_id": str(uuid.uuid4())}),
        ("llm_query", "exit", {"attempt_id": None}),
    ]
    for span, phase, io in phases:
        fails(
            admin.cursor(),
            "SELECT v15.v15_on_phase(%s, 0, %s, %s, %s::jsonb)",
            (iid, span, phase, json.dumps(io)),
            "P1506",
            f"supply_llm_response {span}/{phase} P1506",
        )
    admin.rollback()


def test_happy_and_idempotent(server) -> None:
    admin = connect(server)
    worker = connect(server, "v15_worker")
    try:
        admin.autocommit = False
        worker.autocommit = False
        pool_id = make_pool(admin.cursor())
        admin.commit()
        park_open(admin.cursor())
        admin.commit()
        root = str(uuid.uuid4())
        open_invoke(worker, root, pool_id)
        install_hook(admin.cursor(), "pin_happy", pin_hook_body("pin"), root)
        admin.commit()
        rec = RecordingLLM([paid("SELECT 1;"), paid(BIND_ONE), paid(RET)])
        run_until_quiescent(server.get_uri(DB), rec, OWNER)
        rec_trace = export_trace(worker, root)
        worker.commit()
        acur = admin.cursor()
        acur.execute(
            "SELECT calls_used, cost_used FROM v15.budget_pools WHERE pool_id = %s",
            (pool_id,),
        )
        rec_calls, rec_cost = acur.fetchone()
        check("recording cost_used > 0", rec_cost > 0, rec_cost)
        acur.execute(
            """
            SELECT a.n, a.status, a.call_started, a.calls_charged, a.cost_usd
            FROM v15.llm_attempts a JOIN v15.llm_requests r ON r.request_id = a.request_id
            WHERE r.invoke_id = %s ORDER BY r.iteration, a.n
            """,
            (root,),
        )
        rows = acur.fetchall()
        check("attempts settled n=1", all(r == (1, "settled", True, True, COST) for r in rows), rows)
        acur.execute(
            "SELECT provenance FROM v15.bindings WHERE invoke_id = %s AND name = 'kid'",
            (root,),
        )
        check("parent binding provenance delivery", acur.fetchone()[0] == "delivery")
        acur.execute("SELECT invoke_id FROM v15.invokes WHERE parent_invoke_id = %s", (root,))
        child = acur.fetchone()[0]
        for iid, label in ((root, "root"), (child, "child")):
            groups = llm_query_groups(acur, iid)
            check(
                f"{label} llm_query enter-send-complete-exit per iteration",
                bool(groups) and all(g == ["enter", "send", "complete", "exit"] for g in groups),
                groups,
            )
        root_inv = next(inv for inv in rec_trace["invokes"] if inv["path"] == "")
        check("completed status independent", root_inv["status"] == "completed")
        check("completed return_value independent", root_inv["return_value"] == {"ok": True})
        check("completed error_code independent", root_inv["error_code"] is None)
        acur.execute(
            "SELECT count(*) FROM v15.invoke_events WHERE payload->>'class' = 'provider_rejected' OR payload->>'op' ILIKE '%provider_rejected%'"
        )
        check("no provider_rejected events", acur.fetchone()[0] == 0)
        costs = [step["recorded_cost_usd"] for inv in rec_trace["invokes"] for step in inv["steps"] if step["logical_digest"]]
        check("exported recorded_cost_usd is Decimal", all(isinstance(c, Decimal) for c in costs), costs)
        check("recorded_cost_usd nonzero", any(c is not None and c != 0 for c in costs), costs)
        check("recorded_cost_usd equals COST", any(c == COST for c in costs), costs)
        with tempfile.TemporaryDirectory() as tmp:
            rec_path = Path(tmp) / "rec.json"
            write_trace(rec_path, rec_trace)
            loaded_rec = load_trace(rec_path)
            loaded_costs = [
                step["recorded_cost_usd"]
                for inv in loaded_rec["invokes"]
                for step in inv["steps"]
                if step["logical_digest"]
            ]
            check("recorded_cost_usd round-trip", loaded_costs == costs, loaded_costs)
            compact_export = dumps(loaded_rec).replace(" ", "").replace("\n", "")
            check("export recorded_cost_usd is json number", '"recorded_cost_usd":1.25' in compact_export)
            check("export cost not quoted str", '"recorded_cost_usd":"1.25"' not in compact_export)
        check("digest_scheme", rec_trace["digest_scheme"] == DIGEST_SCHEME)
        admin.commit()
    finally:
        worker.close()
        admin.close()

    create_loaded_db(server, PLAY)
    play_admin = connect(server, database=PLAY)
    play_worker = connect(server, "v15_worker", PLAY)
    try:
        play_admin.autocommit = False
        play_worker.autocommit = False
        pool2 = make_pool(play_admin.cursor())
        play_admin.commit()
        replay_llm = ReplayLLM(server.get_uri(PLAY), OWNER, rec_trace)
        open_invoke(play_worker, root, pool2)
        install_hook(play_admin.cursor(), "pin_happy", pin_hook_body("pin"), root)
        play_admin.commit()
        run_until_quiescent(server.get_uri(PLAY), replay_llm, OWNER)
        check("no leftover frames", replay_llm.leftover_llm() == [], replay_llm.leftover_llm())
        play_trace = export_trace(play_worker, root)
        play_worker.commit()
        rec_p = projection(rec_trace, drop_cost=True)
        play_p = projection(play_trace, drop_cost=True)
        check("replay projection matches", rec_p == play_p)
        pcur = play_admin.cursor()
        pcur.execute("SELECT calls_used, cost_used FROM v15.budget_pools WHERE pool_id = %s", (pool2,))
        play_calls, play_cost = pcur.fetchone()
        check("calls_used equal", play_calls == rec_calls, (play_calls, rec_calls))
        check("replay cost_used is 0", play_cost == 0, play_cost)
        kids = [inv for inv in play_trace["invokes"] if inv["path"] != ""]
        check("one child", len(kids) == 1, [k["path"] for k in kids])
        play_root = next(inv for inv in play_trace["invokes"] if inv["path"] == "")
        check("replay completed status independent", play_root["status"] == "completed")
        check("replay completed return_value independent", play_root["return_value"] == {"ok": True})
        check("replay completed error_code independent", play_root["error_code"] is None)
        play_admin.commit()
    finally:
        play_worker.close()
        play_admin.close()

    create_loaded_db(server, PLAY2)
    replay_llm2 = ReplayLLM(server.get_uri(PLAY2), OWNER, rec_trace)
    admin2 = connect(server, database=PLAY2)
    worker2 = connect(server, "v15_worker", PLAY2)
    try:
        admin2.autocommit = False
        worker2.autocommit = False
        pool3 = make_pool(admin2.cursor())
        admin2.commit()
        open_invoke(worker2, root, pool3)
        install_hook(admin2.cursor(), "pin_happy", pin_hook_body("pin"), root)
        admin2.commit()
        run_until_quiescent(server.get_uri(PLAY2), replay_llm2, OWNER)
        t2 = export_trace(worker2, root)
        worker2.commit()
        check("second replay idempotent", projection(play_trace, drop_cost=True) == projection(t2, drop_cost=True))
    finally:
        worker2.close()
        admin2.close()


def test_same_digest_two_children(server) -> None:
    admin = connect(server)
    worker = connect(server, "v15_worker")
    try:
        admin.autocommit = False
        worker.autocommit = False
        park_open(admin.cursor())
        admin.commit()
        root = str(uuid.uuid4())
        open_invoke(worker, root)
        rec = RecordingLLM([paid(BIND_TWO), paid(RET_A), paid(RET_B)])
        run_until_quiescent(server.get_uri(DB), rec, OWNER)
        trace = export_trace(worker, root)
        worker.commit()
        digests = [s["logical_digest"] for inv in trace["invokes"] if inv["path"] for s in inv["steps"]]
        check("two child digests", len(digests) == 2, digests)
        check("same digest two nodes", digests[0] == digests[1], digests)
        contents = {
            inv["path"]: inv["steps"][0]["response_content"]
            for inv in trace["invokes"] if inv["path"]
        }
        check("coordinate supply differs", len(set(contents.values())) == 2, contents)
    finally:
        worker.close()
        admin.close()
    play = "agent_v15_replay_twins"
    create_loaded_db(server, play)
    llm = ReplayLLM(server.get_uri(play), OWNER, trace)
    w = connect(server, "v15_worker", play)
    try:
        w.autocommit = False
        open_invoke(w, root)
        run_until_quiescent(server.get_uri(play), llm, OWNER)
        t2 = export_trace(w, root)
        w.commit()
        check(
            "twins replay by coordinate",
            projection(trace, drop_cost=True) == projection(t2, drop_cost=True),
        )
    finally:
        w.close()


def test_prose_continue(server, admin, worker) -> None:
    park_open(admin.cursor())
    admin.commit()
    root = str(uuid.uuid4())
    open_invoke(worker, root)
    rec = RecordingLLM([paid(""), paid(RET)])
    run_until_quiescent(server.get_uri(DB), rec, OWNER)
    trace = export_trace(worker, root)
    worker.commit()
    steps = trace["invokes"][0]["steps"]
    check("empty statements exported", any(s["statements"] == [] for s in steps), steps)
    play = "agent_v15_replay_prose"
    create_loaded_db(server, play)
    llm = ReplayLLM(server.get_uri(play), OWNER, trace)
    w = connect(server, "v15_worker", play)
    try:
        w.autocommit = False
        open_invoke(w, root)
        run_until_quiescent(server.get_uri(play), llm, OWNER)
        t2 = export_trace(w, root)
        w.commit()
        check("prose replay matches", projection(trace, drop_cost=True) == projection(t2, drop_cost=True))
    finally:
        w.close()


def test_extra_hook_diverges(server) -> None:
    admin = connect(server)
    worker = connect(server, "v15_worker")
    try:
        admin.autocommit = False
        worker.autocommit = False
        park_open(admin.cursor())
        admin.commit()
        root = str(uuid.uuid4())
        open_invoke(worker, root)
        rec = RecordingLLM([paid(RET)])
        run_until_quiescent(server.get_uri(DB), rec, OWNER)
        trace = export_trace(worker, root)
        worker.commit()
    finally:
        worker.close()
        admin.close()
    play = "agent_v15_replay_hook"
    create_loaded_db(server, play)
    llm = ReplayLLM(server.get_uri(play), OWNER, trace)
    a = connect(server, database=play)
    w = connect(server, "v15_worker", play)
    try:
        a.autocommit = False
        w.autocommit = False
        open_invoke(w, root)
        install_hook(a.cursor(), "extra_pin", pin_hook_body("extra"), root)
        a.commit()
        try:
            run_until_quiescent(server.get_uri(play), llm, OWNER)
            raised = None
        except psycopg2.Error as exc:
            raised = exc
        check("extra persistent message P1541", raised is not None and raised.pgcode == "P1541", raised)
    finally:
        w.close()
        a.close()


def test_leftover_frames(server) -> None:
    admin = connect(server)
    worker = connect(server, "v15_worker")
    try:
        admin.autocommit = False
        worker.autocommit = False
        park_open(admin.cursor())
        admin.commit()
        root = str(uuid.uuid4())
        open_invoke(worker, root)
        rec = RecordingLLM([paid(RET)])
        run_until_quiescent(server.get_uri(DB), rec, OWNER)
        trace = export_trace(worker, root)
        worker.commit()
    finally:
        worker.close()
        admin.close()
    extra = dict(trace["invokes"][0]["steps"][0])
    extra["iteration"] = 9
    extra["logical_digest"] = "c" * 32
    extra["response_content"] = "SELECT leftover;"
    padded = copy.deepcopy(trace)
    padded["invokes"][0]["steps"].append(extra)
    play = "agent_v15_replay_left"
    create_loaded_db(server, play)
    llm = ReplayLLM(server.get_uri(play), OWNER, padded)
    w = connect(server, "v15_worker", play)
    try:
        w.autocommit = False
        open_invoke(w, root)
        run_until_quiescent(server.get_uri(play), llm, OWNER)
        left = llm.leftover_llm()
        check("leftover frame detected", left == [("", 9)], left)
    finally:
        w.close()


def test_failed_terminal_expected(server) -> None:
    admin = connect(server)
    worker = connect(server, "v15_worker")
    try:
        admin.autocommit = False
        worker.autocommit = False
        park_open(admin.cursor())
        admin.commit()
        root = str(uuid.uuid4())
        open_invoke(worker, root)
        run_until_quiescent(server.get_uri(DB), RecordingLLM([paid(RAISE_SQL)]), OWNER)
        trace = export_trace(worker, root)
        worker.commit()
        inv = trace["invokes"][0]
        check("failed status independent", inv["status"] == "failed")
        check("failed error_code independent", inv["error_code"] == "V15_RAISE")
        check("failed return_value independent", inv["return_value"] is None)
        check("failed fatal independent", inv["fatal"] is False)
    finally:
        worker.close()
        admin.close()


def test_missing_frame_via_driver(server) -> None:
    admin = connect(server)
    worker = connect(server, "v15_worker")
    try:
        admin.autocommit = False
        worker.autocommit = False
        park_open(admin.cursor())
        admin.commit()
        root = str(uuid.uuid4())
        open_invoke(worker, root)
        run_until_quiescent(server.get_uri(DB), RecordingLLM([paid(RET)]), OWNER)
        trace = export_trace(worker, root)
        worker.commit()
    finally:
        worker.close()
        admin.close()
    stripped = copy.deepcopy(trace)
    stripped["invokes"][0]["steps"] = []
    play = "agent_v15_replay_miss"
    create_loaded_db(server, play)
    llm = ReplayLLM(server.get_uri(play), OWNER, stripped)
    w = connect(server, "v15_worker", play)
    try:
        w.autocommit = False
        open_invoke(w, root)
        try:
            run_until_quiescent(server.get_uri(play), llm, OWNER)
            raised = None
        except psycopg2.Error as exc:
            raised = exc
        check("driver missing frame P1542", raised is not None and raised.pgcode == "P1542", raised)
    finally:
        w.close()


PREC = Decimal("0.123456789012345678901234567890")


def test_export_precision_and_byte_order(server, admin, worker) -> None:
    park_open(admin.cursor())
    admin.commit()
    pool_id = make_pool(admin.cursor())
    admin.commit()
    root = str(uuid.uuid4())
    open_invoke(worker, root, pool_id)
    run_until_quiescent(server.get_uri(DB), RecordingLLM([paid(RET)]), OWNER)
    acur = admin.cursor()
    acur.execute(
        "UPDATE v15.budget_pools SET cost_used = %s WHERE pool_id = %s",
        (PREC, pool_id),
    )
    acur.execute(
        """
        INSERT INTO v15.bindings (
          invoke_id, name, kind, value, tool_id, show_in_prompt, provenance
        ) VALUES
          (%s, 'Z', 'var', '1'::jsonb, NULL, false, 'repl'),
          (%s, 'a', 'var', '2'::jsonb, NULL, false, 'repl')
        """,
        (root, root),
    )
    admin.commit()
    exported = export_trace(worker, root)
    worker.commit()
    check(
        "high-precision cost_used export",
        exported["pool_outcome"]["cost_used"] == PREC,
        exported["pool_outcome"]["cost_used"],
    )
    rec_cost = exported["invokes"][0]["steps"][0]["recorded_cost_usd"]
    check("exported recorded_cost_usd is Decimal", isinstance(rec_cost, Decimal), rec_cost)
    names = [b["name"] for b in exported["invokes"][0]["bindings"]]
    check("mixed-case binding export byte order", names == ["Z", "a"], names)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "precise.json"
        write_trace(path, exported)
        loaded = load_trace(path)
        check("export write/load projection", projection(exported) == projection(loaded))
        check(
            "loaded high-precision cost_used",
            loaded["pool_outcome"]["cost_used"] == PREC,
            loaded["pool_outcome"]["cost_used"],
        )
        check(
            "loaded recorded_cost_usd lossless",
            loaded["invokes"][0]["steps"][0]["recorded_cost_usd"] == rec_cost,
            loaded["invokes"][0]["steps"][0]["recorded_cost_usd"],
        )


def test_bind_name_slash_path(server, admin, worker) -> None:
    park_open(admin.cursor())
    admin.commit()
    root = str(uuid.uuid4())
    open_invoke(worker, root)
    run_until_quiescent(server.get_uri(DB), RecordingLLM([paid(BIND_ONE), paid(RET)]), OWNER)
    acur = admin.cursor()
    acur.execute(
        "UPDATE v15.statements SET bind_name = 'kid/x' WHERE invoke_id = %s AND bind_name = 'kid'",
        (root,),
    )
    admin.commit()
    fails(
        worker.cursor(), "SELECT v15.v15_replay_export(%s)", (root,),
        "P1524", "slash bind_name P1524",
    )
    worker.rollback()


def main() -> int:
    test_load_order()
    test_trace_local()
    setup_db()
    server = get_server()
    admin = connect(server)
    worker = connect(server, "v15_worker")
    try:
        admin.autocommit = False
        worker.autocommit = False
        test_sqlstate_superset(admin.cursor())
        admin.commit()
        test_no_new_tables(admin.cursor())
        test_acl(admin, worker)
        test_same_txn_guards(server, admin, worker)
        test_supply_still_reserved(admin, worker)
    finally:
        worker.close()
        admin.close()
    admin = connect(server)
    worker = connect(server, "v15_worker")
    try:
        admin.autocommit = False
        worker.autocommit = False
        test_settled_second_begin_and_export(server, admin, worker)
    finally:
        worker.close()
        admin.close()
    test_happy_and_idempotent(server)
    test_same_digest_two_children(server)
    admin = connect(server)
    worker = connect(server, "v15_worker")
    try:
        admin.autocommit = False
        worker.autocommit = False
        test_prose_continue(server, admin, worker)
    finally:
        worker.close()
        admin.close()
    test_extra_hook_diverges(server)
    test_leftover_frames(server)
    test_failed_terminal_expected(server)
    test_missing_frame_via_driver(server)
    admin = connect(server)
    worker = connect(server, "v15_worker")
    try:
        admin.autocommit = False
        worker.autocommit = False
        test_bind_name_slash_path(server, admin, worker)
        test_export_precision_and_byte_order(server, admin, worker)
    finally:
        worker.close()
        admin.close()
    admin = connect(server)
    worker = connect(server, "v15_worker")
    try:
        admin.autocommit = False
        worker.autocommit = False
        root = str(uuid.uuid4())
        p1 = make_pool(admin.cursor())
        p2 = make_pool(admin.cursor())
        admin.commit()
        park_open(admin.cursor())
        admin.commit()
        open_invoke(worker, root, p1)
        run_until_quiescent(server.get_uri(DB), RecordingLLM([paid(BIND_ONE), paid(RET)]), OWNER)
        acur = admin.cursor()
        acur.execute("SELECT invoke_id FROM v15.invokes WHERE parent_invoke_id = %s", (root,))
        child = acur.fetchone()[0]
        acur.execute("UPDATE v15.invokes SET pool_id = %s WHERE invoke_id = %s", (p2, child))
        admin.commit()
        fails(worker.cursor(), "SELECT v15.v15_replay_export(%s)", (root,), "P1524", "two pools P1524")
        worker.rollback()
        root_mix = str(uuid.uuid4())
        p_mix = make_pool(admin.cursor())
        admin.commit()
        park_open(admin.cursor())
        admin.commit()
        open_invoke(worker, root_mix, p_mix)
        run_until_quiescent(server.get_uri(DB), RecordingLLM([paid(BIND_ONE), paid(RET)]), OWNER)
        acur = admin.cursor()
        acur.execute("SELECT invoke_id FROM v15.invokes WHERE parent_invoke_id = %s", (root_mix,))
        child_mix = acur.fetchone()[0]
        acur.execute("UPDATE v15.invokes SET pool_id = NULL WHERE invoke_id = %s", (child_mix,))
        admin.commit()
        fails(
            worker.cursor(), "SELECT v15.v15_replay_export(%s)", (root_mix,),
            "P1524", "mixed null/non-null pools P1524",
        )
        worker.rollback()
    finally:
        worker.close()
        admin.close()
    print("ALL PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
