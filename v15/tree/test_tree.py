"""Stage 8 gate: invoke tree, suspend, and child delivery.

Run: uv run python v15/tree/test_tree.py  (exit 0 = pass)
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
from v15.tree.setup_db import DB, main as setup_db
from v15.protocol.render_prompt import render_system
from v15.worker import Worker, run_until_quiescent

SCOPE = "00000000-0000-4000-8000-0000000000b1"
OWNER = "tree-owner"


class StopScript(Exception):
    pass


class Script:
    def __init__(self, replies: list) -> None:
        self.replies = list(replies)
        self.calls = []

    def complete(self, logical_digest: str, n: int, request: dict, llm_config=None) -> dict:
        self.calls.append((logical_digest, n, request))
        if not self.replies:
            raise StopScript("no reply")
        content = self.replies.pop(0)
        if content is StopScript:
            raise StopScript("stop")
        return {"content": content}


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


def open_invoke(
    conn,
    invoke_id: str,
    inputs=None,
    pool_id: str | None = None,
    ceilings=None,
    local_layer: str | None = None,
    user: str | None = None,
) -> None:
    cur = conn.cursor()
    cur.execute("SET LOCAL lock_timeout = '2s'")
    cur.execute("SET LOCAL statement_timeout = '30s'")
    cur.execute(
        """
        SELECT v15.v15_open_invoke(
          %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s, %s
        )
        """,
        (
            invoke_id,
            SCOPE,
            local_layer,
            json.dumps(inputs or []),
            pool_id,
            None if ceilings is None else json.dumps(ceilings),
            system_text(),
            user,
        ),
    )
    conn.commit()


def run(server, replies, worker_id: str = OWNER) -> Script:
    script = Script(replies)
    run_until_quiescent(server.get_uri(DB), script, worker_id)
    return script


def one(cur, query: str, args=()):
    cur.execute(query, args)
    return cur.fetchone()


def attempts(cur, invoke_id: str) -> int:
    return one(
        cur,
        """
        SELECT count(*)
        FROM v15.llm_attempts a
        JOIN v15.llm_requests r ON r.request_id = a.request_id
        WHERE r.invoke_id = %s
        """,
        (invoke_id,),
    )[0]


def children(cur, parent: str) -> list[str]:
    cur.execute(
        """
        SELECT invoke_id::text
        FROM v15.invokes
        WHERE parent_invoke_id = %s
        ORDER BY depth, invoke_id
        """,
        (parent,),
    )
    return [row[0] for row in cur.fetchall()]


def stmt(cur, invoke_id: str, index: int, iteration: int = 0):
    return one(
        cur,
        """
        SELECT status, error->>'code', error->>'sqlstate'
        FROM v15.statements
        WHERE invoke_id = %s AND iteration = %s AND stmt_index = %s
        """,
        (invoke_id, iteration, index),
    )


def running_count(cur) -> int:
    return one(cur, "SELECT count(*) FROM v15.statements WHERE status = 'running'")[0]


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


def register_tool(server, cur, name: str) -> str:
    role = "v15_tool_" + name
    ensure_role(server, role)
    fn = "tree_" + name
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


def binding(cur, invoke_id: str, name: str):
    return one(
        cur,
        """
        SELECT kind, value, provenance
        FROM v15.bindings
        WHERE invoke_id = %s AND name = %s
        """,
        (invoke_id, name),
    )


def test_same_iteration(server, wconn, cur) -> None:
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    parent = (
        "SELECT jaz.bind_invoke('out', '{\"n\":1}'::jsonb);\n"
        "SELECT jaz.\"return\"(jaz.var('out'));"
    )
    child = "SELECT jaz.\"return\"('{\"n\":7}'::jsonb);"
    script = run(server, [parent, child])
    check("parent llm calls during tree", len(script.calls) == 2, len(script.calls))
    check("parent attempts stay one", attempts(cur, iid) == 1, attempts(cur, iid))
    kids = children(cur, iid)
    check("one child", len(kids) == 1, kids)
    check("child attempts", attempts(cur, kids[0]) == 1)
    row = one(
        cur,
        """
        SELECT status, return_value, fatal
        FROM v15.invokes WHERE invoke_id = %s
        """,
        (iid,),
    )
    check("parent completed", row[0] == "completed" and row[2] is False, row)
    check("parent sees child value", parse_json(row[1]) == {"n": 7}, row[1])
    check("bind done", stmt(cur, iid, 0)[0] == "done")
    check("return done same iteration", stmt(cur, iid, 1)[0] == "done")
    iters = one(
        cur,
        """
        SELECT count(*), max(iteration),
               bool_or(iteration = 0 AND result_kind = 'return')
        FROM v15.iterations WHERE invoke_id = %s
        """,
        (iid,),
    )
    check("no extra parent iteration", iters == (1, 0, True), iters)
    cur.execute(
        """
        SELECT payload->>'op'
        FROM v15.invoke_events
        WHERE invoke_id = %s AND event_class = 'audit'
        ORDER BY seq
        """,
        (iid,),
    )
    ops = [row[0] for row in cur.fetchall()]
    check("suspend then deliver", "suspend" in ops and "deliver" in ops, ops)
    cur.execute(
        """
        SELECT seq, span, phase
        FROM v15.invoke_events
        WHERE invoke_id = %s AND event_class = 'span' AND span = 'repl_exec'
        ORDER BY seq
        """,
        (iid,),
    )
    spans = cur.fetchall()
    suspend_seq = one(
        cur,
        """
        SELECT seq FROM v15.invoke_events
        WHERE invoke_id = %s AND payload->>'op' = 'suspend'
        """,
        (iid,),
    )[0]
    deliver_seq = one(
        cur,
        """
        SELECT seq FROM v15.invoke_events
        WHERE invoke_id = %s AND payload->>'op' = 'deliver'
        """,
        (iid,),
    )[0]
    exits_between = [
        row for row in spans
        if row[2] == "exit" and suspend_seq < row[0] < deliver_seq
    ]
    check("repl_exec stays open while waiting", exits_between == [], spans)
    check("child not claimable while it ran", one(
        cur,
        "SELECT status FROM v15.invokes WHERE invoke_id = %s",
        (kids[0],),
    )[0] == "completed")


def test_grandchild(server, wconn, cur) -> None:
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    parent = (
        "SELECT jaz.bind_invoke('kid', '{\"label\":\"g\"}'::jsonb);\n"
        "SELECT jaz.\"return\"(jaz.var('kid'));"
    )
    child = (
        "SELECT jaz.bind_invoke('gk', '{}'::jsonb);\n"
        "SELECT jaz.\"return\"(jaz.var('gk'));"
    )
    grand = "SELECT jaz.\"return\"('{\"n\":3}'::jsonb);"
    run(server, [parent, child, grand])
    kids = children(cur, iid)
    check("child exists", len(kids) == 1)
    grands = children(cur, kids[0])
    check("grandchild exists", len(grands) == 1, grands)
    check("three attempt counts", (
        attempts(cur, iid),
        attempts(cur, kids[0]),
        attempts(cur, grands[0]),
    ) == (1, 1, 1))
    value = parse_json(one(
        cur, "SELECT return_value FROM v15.invokes WHERE invoke_id = %s", (iid,)
    )[0])
    check("grandchild value reaches parent", value == {"n": 3}, value)
    seed = one(
        cur,
        """
        SELECT content FROM v15.llm_messages
        WHERE invoke_id = %s AND message_id = 'seed:inputs'
        """,
        (kids[0],),
    )[0]
    check("child inputs seed", "label:" in seed, seed)


def test_scope(server, wconn, cur) -> None:
    scope_tool = register_tool(server, cur, "echo")
    explicit_tool = register_tool(server, cur, "hidden")
    layer = str(uuid.uuid4())
    prop = str(uuid.uuid4())
    cur.execute(
        """
        SELECT v15.v15_add_layer(
          %s, %s, 0, 'plain', NULL, NULL, NULL, NULL, %s::jsonb
        )
        """,
        (
            prop,
            SCOPE,
            json.dumps([{"hook_key": "governance_io", "config": {"copied": True}}]),
        ),
    )
    cur.execute(
        """
        SELECT v15.v15_add_layer(
          %s, NULL, 0, 'plain', %s::jsonb, NULL, NULL, NULL, %s::jsonb
        )
        """,
        (
            layer,
            json.dumps({"model": "local-model"}),
            json.dumps([{"hook_key": "governance_iterations", "config": {"local": True}}]),
        ),
    )
    cur.connection.commit()
    iid = str(uuid.uuid4())
    open_invoke(
        wconn,
        iid,
        inputs=[
            {
                "name": "topic",
                "kind": "input",
                "value": "alpha",
                "show_in_prompt": True,
                "provenance": "explicit",
            },
            {
                "name": "shared",
                "kind": "scope",
                "value": {"n": 1},
                "show_in_prompt": True,
                "provenance": "scope",
            },
            {
                "name": "echo",
                "kind": "tool",
                "value": {},
                "show_in_prompt": True,
                "tool_id": scope_tool,
                "provenance": "scope",
            },
            {
                "name": "hidetool",
                "kind": "tool",
                "value": {},
                "show_in_prompt": False,
                "tool_id": explicit_tool,
                "provenance": "explicit",
            },
        ],
        local_layer=layer,
    )
    parent = (
        "SELECT jaz.bind_invoke('out', '{\"fresh\":true}'::jsonb);\n"
        "SELECT jaz.\"return\"(jaz.var('out'));"
    )
    child = (
        "SELECT jaz.assign('child_only', '\"set\"'::jsonb);\n"
        "SELECT jaz.\"return\"(jaz.var('shared'));"
    )
    run(server, [parent, child])
    kid = children(cur, iid)[0]
    check("parent scope unchanged", parse_json(binding(cur, iid, "shared")[1]) == {"n": 1})
    check("parent has no child var", binding(cur, iid, "child_only") is None)
    check("child copied scope", parse_json(binding(cur, kid, "shared")[1]) == {"n": 1})
    check("child assign stayed local", binding(cur, kid, "child_only")[0] == "var")
    check("input not copied", binding(cur, kid, "topic") is None)
    check("child got its own input", binding(cur, kid, "fresh")[0] == "input")
    check("explicit tool not copied", binding(cur, kid, "hidetool") is None)
    copied = binding(cur, kid, "echo")
    check("scope tool copied", copied is not None and copied[0] == "tool", copied)
    grant = one(
        cur,
        """
        SELECT count(*)
        FROM v15.tool_grants g
        JOIN v15.bindings b ON b.invoke_id = g.invoke_id AND b.tool_id = g.tool_id
        WHERE g.invoke_id = %s AND b.name = 'echo'
        """,
        (kid,),
    )[0]
    check("scope tool grant copied", grant == 1, grant)
    explicit_grant = one(
        cur,
        "SELECT count(*) FROM v15.tool_grants WHERE invoke_id = %s AND tool_id = %s",
        (kid, explicit_tool),
    )[0]
    check("explicit tool grant not copied", explicit_grant == 0, explicit_grant)
    child_cfg = parse_json(one(
        cur, "SELECT resolved_config FROM v15.invokes WHERE invoke_id = %s", (kid,)
    )[0])
    parent_cfg = parse_json(one(
        cur, "SELECT resolved_config FROM v15.invokes WHERE invoke_id = %s", (iid,)
    )[0])
    check("parent kept local model", parent_cfg["llm"]["model"] == "local-model", parent_cfg)
    check("child refolded without local", child_cfg["llm"]["model"] == "fake", child_cfg)
    check("child depth in config", child_cfg["depth"] == 2, child_cfg)
    check(
        "child local layer empty",
        one(cur, "SELECT local_layer_id FROM v15.invokes WHERE invoke_id = %s", (kid,))[0] is None,
    )
    cur.execute(
        """
        SELECT channel, count(*)
        FROM v15.invoke_hooks
        WHERE invoke_id = %s
        GROUP BY channel
        ORDER BY channel
        """,
        (kid,),
    )
    channels = cur.fetchall()
    check("child hooks skip local", ("local",) not in [(row[0],) for row in channels], channels)
    check(
        "propagating copied",
        any(row[0] == "propagating" and row[1] >= 1 for row in channels),
        channels,
    )
    value = parse_json(one(
        cur, "SELECT return_value FROM v15.invokes WHERE invoke_id = %s", (iid,)
    )[0])
    check("parent return is copied scope", value == {"n": 1}, value)


def test_child_raise(server, wconn, cur) -> None:
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    parent = (
        "SELECT jaz.bind_invoke('out', '{}'::jsonb);\n"
        "SELECT jaz.\"return\"(jaz.var('out'));"
    )
    child = "SELECT jaz.\"raise\"('boom');"
    follow = "SELECT jaz.\"return\"('{\"later\":true}'::jsonb);"
    run(server, [parent, child, follow])
    kid = children(cur, iid)[0]
    check("child keeps raise", one(
        cur, "SELECT status, fatal, error->>'code' FROM v15.invokes WHERE invoke_id = %s", (kid,)
    ) == ("failed", False, "V15_RAISE"))
    check("parent statement child error", stmt(cur, iid, 0) == ("failed", "V15_CHILD_ERROR", "P1528"))
    check("later parent statement skipped", stmt(cur, iid, 1)[0] == "skipped")
    kind = one(
        cur,
        """
        SELECT result_kind FROM v15.iterations
        WHERE invoke_id = %s AND iteration = 0
        """,
        (iid,),
    )[0]
    check("parent iteration continue", kind == "continue", kind)
    check("parent attempts on bind iteration", one(
        cur,
        """
        SELECT count(*)
        FROM v15.llm_attempts a
        JOIN v15.llm_requests r ON r.request_id = a.request_id
        WHERE r.invoke_id = %s AND r.iteration = 0
        """,
        (iid,),
    )[0] == 1)


def test_delivery_conflict(server, wconn, cur) -> None:
    iid = str(uuid.uuid4())
    open_invoke(
        wconn,
        iid,
        inputs=[{
            "name": "out",
            "kind": "scope",
            "value": {"kept": True},
            "show_in_prompt": True,
            "provenance": "scope",
        }],
    )
    parent = (
        "SELECT jaz.bind_invoke('out', '{}'::jsonb);\n"
        "SELECT 1;"
    )
    child = "SELECT jaz.\"return\"('{\"n\":1}'::jsonb);"
    follow = "SELECT jaz.\"return\"('null'::jsonb);"
    run(server, [parent, child, follow])
    kid = children(cur, iid)[0]
    check("child stays completed", one(
        cur, "SELECT status, error FROM v15.invokes WHERE invoke_id = %s", (kid,)
    )[0] == "completed")
    check(
        "name conflict code",
        stmt(cur, iid, 0) == ("failed", "V15_DELIVERY_CONFLICT", "P1527"),
    )
    check("later skipped", stmt(cur, iid, 1)[0] == "skipped")
    check("scope not overwritten", parse_json(binding(cur, iid, "out")[1]) == {"kept": True})


def test_fatal(server, wconn, cur) -> None:
    pool = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO v15.budget_pools (pool_id, calls_limit) VALUES (%s, 2)",
        (pool,),
    )
    cur.connection.commit()
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid, pool_id=pool)
    parent = (
        "SELECT jaz.bind_invoke('c', '{}'::jsonb);\n"
        "SELECT jaz.\"return\"(jaz.var('c'));"
    )
    child = (
        "SELECT jaz.bind_invoke('g', '{}'::jsonb);\n"
        "SELECT jaz.\"return\"(jaz.var('g'));"
    )
    run(server, [parent, child])
    kid = children(cur, iid)[0]
    grand = children(cur, kid)[0]
    for label, target in (("parent", iid), ("child", kid), ("grandchild", grand)):
        row = one(
            cur,
            "SELECT status, fatal, error->>'code' FROM v15.invokes WHERE invoke_id = %s",
            (target,),
        )
        check(f"{label} aborted", row == ("aborted", True, "V15_BUDGET_EXHAUSTED"), row)
    check("parent bind failed with fatal code", stmt(cur, iid, 0) == (
        "failed", "V15_BUDGET_EXHAUSTED", "P1514"
    ))
    check("parent later skipped", stmt(cur, iid, 1)[0] == "skipped")
    check("child bind failed with fatal code", stmt(cur, kid, 0)[0] == "failed")
    check("child later skipped", stmt(cur, kid, 1)[0] == "skipped")
    check("no running statements", running_count(cur) == 0, running_count(cur))
    check("grandchild never called the model", attempts(cur, grand) == 0)


def test_depth_guard(server, wconn, cur) -> None:
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)

    class Tighten(Script):
        def complete(self, logical_digest, n, request, llm_config=None):
            conn = connect(server)
            conn.autocommit = True
            try:
                conn.cursor().execute(
                    """
                    UPDATE v15.governance_manifest
                    SET max_depth = 1,
                        manifest_digest = v15.v15_manifest_digest(
                          max_iterations, 1, max_io_attempts, max_statement_ms
                        )
                    WHERE manifest_id = 1
                    """
                )
            finally:
                conn.close()
            return super().complete(logical_digest, n, request, llm_config)

    parent = "SELECT jaz.bind_invoke('out', '{}'::jsonb);"
    follow = "SELECT jaz.\"return\"('null'::jsonb);"
    script = Tighten([parent, follow])
    try:
        run_until_quiescent(server.get_uri(DB), script, OWNER)
        kid = children(cur, iid)[0]
        row = one(
            cur,
            "SELECT status, fatal, error->>'code' FROM v15.invokes WHERE invoke_id = %s",
            (kid,),
        )
        check("born terminal child", row == ("failed", False, "V15_RECURSION_EXCEEDED"), row)
        check("same-tx child error", stmt(cur, iid, 0) == ("failed", "V15_CHILD_ERROR", "P1528"))
        check("child never leased an attempt", attempts(cur, kid) == 0)
        check(
            "parent not left suspended",
            one(cur, "SELECT status FROM v15.invokes WHERE invoke_id = %s", (iid,))[0] != "suspended",
        )
        scratch = one(
            cur, "SELECT scratch_schema FROM v15.invokes WHERE invoke_id = %s", (kid,)
        )[0]
        check(
            "child scratch dropped",
            one(
                cur,
                "SELECT count(*) FROM pg_namespace WHERE nspname = %s",
                (scratch,),
            )[0] == 0,
        )
    finally:
        cur.execute(
            """
            UPDATE v15.governance_manifest
            SET max_iterations = 10,
                max_depth = 8,
                max_io_attempts = 3,
                max_statement_ms = 30000,
                manifest_digest = v15.v15_manifest_digest(10, 8, 3, 30000)
            WHERE manifest_id = 1
            """
        )
        cur.connection.commit()


def test_enter_abort(server, wconn, cur) -> None:
    cur.execute(
        """
        CREATE OR REPLACE FUNCTION v15.v15_on_phase(
          invoke_id uuid,
          iteration integer,
          span text,
          phase text,
          io jsonb
        ) RETURNS jsonb
        LANGUAGE plpgsql
        VOLATILE
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $fn$
        BEGIN
          IF span = 'invoke' AND phase = 'enter'
             AND coalesce((io->>'depth')::integer, 1) >= 2 THEN
            RETURN '{"contract":1,"action":"abort","fatal":false,"code":"V15_HOOK_ABORT"}'::jsonb;
          END IF;
          RETURN '{"contract":1,"action":"proceed"}'::jsonb;
        END
        $fn$
        """
    )
    cur.connection.commit()
    iid = str(uuid.uuid4())
    try:
        open_invoke(wconn, iid)
        parent = "SELECT jaz.bind_invoke('out', '{}'::jsonb);"
        follow = "SELECT jaz.\"return\"('null'::jsonb);"
        run(server, [parent, follow])
        kid = children(cur, iid)[0]
        row = one(
            cur,
            "SELECT status, fatal, error->>'code' FROM v15.invokes WHERE invoke_id = %s",
            (kid,),
        )
        check("enter abort child failed", row == ("failed", False, "V15_HOOK_ABORT"), row)
        check("enter abort delivered", stmt(cur, iid, 0) == ("failed", "V15_CHILD_ERROR", "P1528"))
        check(
            "parent not suspended after enter abort",
            one(cur, "SELECT status FROM v15.invokes WHERE invoke_id = %s", (iid,))[0] != "suspended",
        )
    finally:
        cur.execute(
            """
            CREATE OR REPLACE FUNCTION v15.v15_on_phase(
              invoke_id uuid,
              iteration integer,
              span text,
              phase text,
              io jsonb
            ) RETURNS jsonb
            LANGUAGE sql
            VOLATILE
            SECURITY DEFINER
            SET search_path = pg_catalog
            AS $fn$
              SELECT '{"contract":1,"action":"proceed"}'::jsonb
            $fn$
            """
        )
        cur.connection.commit()


def test_crash_and_claim(server, wconn, cur) -> None:
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    parent = (
        "SELECT jaz.bind_invoke('out', '{}'::jsonb);\n"
        "SELECT jaz.\"return\"(jaz.var('out'));"
    )
    worker = Worker(server.get_uri(DB), Script([parent]), "crash-1")
    try:
        worker.reclaim()
        fence = worker.claim(iid)
        worker.drive(iid, fence)
    finally:
        worker.close()
    check(
        "parent suspended",
        one(cur, "SELECT status, lease_owner FROM v15.invokes WHERE invoke_id = %s", (iid,))
        == ("suspended", None),
    )
    wcur = wconn.cursor()
    wcur.execute(
        "SELECT v15.v15_claim(%s, %s, '30 seconds'::interval)",
        (iid, "other"),
    )
    check("suspended parent not claimed", wcur.fetchone()[0] is None)
    wcur.execute("SELECT v15.v15_next_runnable()")
    runnable = [str(row[0]) for row in wcur.fetchall() if row[0] is not None]
    wconn.commit()
    check("scan skips suspended parent", iid not in runnable, runnable)
    check("scan sees child", len(runnable) == 1, runnable)
    run(server, ["SELECT jaz.\"return\"('{\"n\":9}'::jsonb);"], "crash-2")
    row = one(
        cur,
        "SELECT status, return_value FROM v15.invokes WHERE invoke_id = %s",
        (iid,),
    )
    check("resumed parent completed", row[0] == "completed", row)
    check("resumed parent read child", parse_json(row[1]) == {"n": 9}, row[1])
    check("resume consumed the next statement", stmt(cur, iid, 1)[0] == "done")
    check("no second parent llm", attempts(cur, iid) == 1)


def test_reclaim_repair(server, wconn, cur) -> None:
    parent = str(uuid.uuid4())
    child = str(uuid.uuid4())
    scratch = "s_" + parent.replace("-", "")
    cur.execute(psql.SQL("CREATE SCHEMA {} AUTHORIZATION v15_owner").format(psql.Identifier(scratch)))
    cur.execute(
        """
        INSERT INTO v15.invokes (
          invoke_id, parent_invoke_id, parent_iteration, root_invoke_id, depth,
          status, fatal, recursion_available, resolved_config, config_digest,
          manifest_digest, scratch_schema, fence, lease_owner, lease_until,
          created_at, updated_at
        ) VALUES (
          %s, NULL, NULL, %s, 1,
          'leased', false, true, '{"llm":{"model":"fake"},"repl":{},"protocol":{},"depth":1}'::jsonb,
          'cfg', 'md', %s, 4, 'old', clock_timestamp() - interval '1 minute',
          clock_timestamp(), clock_timestamp()
        )
        """,
        (parent, parent, scratch),
    )
    cur.execute(
        """
        INSERT INTO v15.invokes (
          invoke_id, parent_invoke_id, parent_iteration, root_invoke_id, depth,
          status, fatal, recursion_available, return_value, resolved_config,
          config_digest, manifest_digest, scratch_schema, fence,
          created_at, updated_at
        ) VALUES (
          %s, %s, 0, %s, 2,
          'completed', false, false, '{"ok":1}'::jsonb,
          '{"llm":{"model":"fake"},"repl":{},"protocol":{},"depth":2}'::jsonb,
          'cfg2', 'md', %s, 1,
          clock_timestamp(), clock_timestamp()
        )
        """,
        (child, parent, parent, "s_" + child.replace("-", "")),
    )
    cur.execute(
        """
        INSERT INTO v15.invoke_hooks (
          invoke_id, ordinal, hook_def_id, channel, config, state
        )
        SELECT %s,
               CASE d.hook_key
                 WHEN 'governance_iterations' THEN 0
                 WHEN 'governance_depth' THEN 1
                 WHEN 'governance_io' THEN 2
                 ELSE 3
               END,
               d.hook_def_id,
               'baseline',
               pg_catalog.jsonb_build_object(
                 'max',
                 CASE d.hook_key
                   WHEN 'governance_statement' THEN 30000
                   WHEN 'governance_iterations' THEN 10
                   WHEN 'governance_depth' THEN 8
                   ELSE 3
                 END
               ),
               '{}'::jsonb
        FROM v15.hook_defs d
        WHERE d.hook_key IN (
          'governance_iterations', 'governance_depth',
          'governance_io', 'governance_statement'
        )
        """,
        (parent,),
    )
    cur.execute(
        """
        INSERT INTO v15.iterations (invoke_id, iteration, status, resume_stmt, capture)
        VALUES (%s, 0, 'executing', 0, '')
        """,
        (parent,),
    )
    bind_sql = "SELECT jaz.bind_invoke('out', '{}'::jsonb);"
    ret_sql = "SELECT jaz.\"return\"(jaz.var('out'));"
    cur.execute(
        """
        INSERT INTO v15.statements (
          invoke_id, iteration, stmt_index, sql, sql_digest, kind, bind_name,
          arg_sql, status, child_invoke_id
        ) VALUES
          (%s, 0, 0, %s, md5(%s), 'bind_invoke', 'out', '{}'::text, 'running', %s),
          (%s, 0, 1, %s, md5(%s), 'return', NULL, 'jaz.var(''out'')', 'pending', NULL)
        """,
        (parent, bind_sql, bind_sql, child, parent, ret_sql, ret_sql),
    )
    cur.execute(
        """
        INSERT INTO v15.invoke_events (
          invoke_id, seq, event_class, span, phase, payload, fence, created_at
        ) VALUES
          (%s, 0, 'span', 'invoke', 'enter', '{}'::jsonb, 4, clock_timestamp()),
          (%s, 1, 'span', 'repl_exec', 'enter', '{}'::jsonb, 4, clock_timestamp())
        """,
        (parent, parent),
    )
    cur.connection.commit()
    wcur = wconn.cursor()
    wcur.execute("SELECT v15.v15_reclaim_expired()")
    wconn.commit()
    row = one(
        cur,
        "SELECT status, fence, lease_owner FROM v15.invokes WHERE invoke_id = %s",
        (parent,),
    )
    check("reclaim did not bump fence", row == ("runnable", 4, None), row)
    check("repaired statement done", stmt(cur, parent, 0)[0] == "done")
    delivered = binding(cur, parent, "out")
    check("reclaim delivered var", delivered is not None and delivered[0] == "var", delivered)
    check(
        "resume points at next statement",
        one(
            cur,
            "SELECT resume_stmt, status FROM v15.iterations WHERE invoke_id = %s AND iteration = 0",
            (parent,),
        ) == (1, "executing"),
    )
    run(server, [], "reclaim-owner")
    done = one(
        cur,
        "SELECT status, return_value FROM v15.invokes WHERE invoke_id = %s",
        (parent,),
    )
    check("reclaim resume finished return", done[0] == "completed", done)
    check("reclaim resume value", parse_json(done[1]) == {"ok": 1}, done[1])


def test_eval_failures(server, wconn, cur) -> None:
    cases = [
        (
            "recursion disabled",
            {"max_depth": 1},
            [],
            "SELECT jaz.bind_invoke('out', '{}'::jsonb);",
            "P1518",
            "V15_RECURSION_DISABLED",
        ),
        (
            "scope conflict",
            None,
            [{
                "name": "s",
                "kind": "scope",
                "value": 1,
                "show_in_prompt": True,
                "provenance": "scope",
            }],
            "SELECT jaz.bind_invoke('out', '{\"s\":1}'::jsonb);",
            "P1509",
            "V15_SCOPE_CONFLICT",
        ),
        (
            "assign in arg",
            None,
            [],
            "SELECT jaz.bind_invoke('out', jaz.assign('n', '1'::jsonb));",
            "P1503",
            "V15_INVOKE_FORM",
        ),
        (
            "div zero",
            None,
            [],
            "SELECT jaz.bind_invoke('out', (1/0)::text::jsonb);",
            "22012",
            "22012",
        ),
        (
            "zero rows",
            None,
            [],
            "SELECT jaz.bind_invoke('out', jsonb_array_elements('[]'::jsonb));",
            "P1524",
            "V15_VALUE_INVALID",
        ),
    ]
    for label, ceilings, inputs, sql, state, code in cases:
        iid = str(uuid.uuid4())
        open_invoke(wconn, iid, inputs=inputs, ceilings=ceilings)
        run(server, [sql, "SELECT jaz.\"return\"('null'::jsonb);"])
        check(label, stmt(cur, iid, 0) == ("failed", code, state), stmt(cur, iid, 0))
        check(label + " no child", children(cur, iid) == [], children(cur, iid))

    cur.execute(
        """
        CREATE FUNCTION public.sneaky() RETURNS jsonb
        LANGUAGE plpgsql
        AS $fn$
        BEGIN
          INSERT INTO t VALUES (1);
          RETURN '{}'::jsonb;
        END
        $fn$
        """
    )
    cur.connection.commit()
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    run(
        server,
        [
            "CREATE TABLE t (n int);\nSELECT jaz.bind_invoke('out', public.sneaky());",
            "SELECT jaz.\"return\"('null'::jsonb);",
        ],
    )
    check("scratch write", stmt(cur, iid, 1) == ("failed", "V15_INVOKE_FORM", "P1503"), stmt(cur, iid, 1))
    check("scratch write no child", children(cur, iid) == [])
    check("create stayed committed", stmt(cur, iid, 0)[0] == "done")


def main() -> int:
    server = get_server()
    setup_db()
    conn = connect(server)
    cur = conn.cursor()
    wconn = connect(server, "v15_worker")
    test_same_iteration(server, wconn, cur)
    test_grandchild(server, wconn, cur)
    test_scope(server, wconn, cur)
    test_child_raise(server, wconn, cur)
    test_delivery_conflict(server, wconn, cur)
    test_fatal(server, wconn, cur)
    test_depth_guard(server, wconn, cur)
    test_enter_abort(server, wconn, cur)
    test_crash_and_claim(server, wconn, cur)
    test_reclaim_repair(server, wconn, cur)
    test_eval_failures(server, wconn, cur)
    check("still no running residue", running_count(cur) == 0, running_count(cur))
    wconn.close()
    conn.close()
    print("ALL PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
