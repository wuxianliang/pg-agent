"""Stage 6 gate: LLM window, reclaim, FakeLLM.

Run: uv run python v15/io/test_io.py  (exit 0 = pass)
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import psycopg2
from psycopg2 import extensions as pgext
from psycopg2.extras import Json

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
import sys

sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v15.fake_llm import FakeLLM
from v15.io.setup_db import DB, main as setup_db
from v15.protocol.split_sql import SplitFailure, split_sql

OWNER = "io-owner"
LEASE = "10 minutes"


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


def classify_commit(sqlstate: str) -> str:
    if sqlstate in {"40001", "40P01"}:
        return "retry"
    return sqlstate


def call(conn, query: str, args=()):
    cur = conn.cursor()
    cur.execute("SET LOCAL lock_timeout = '2s'")
    cur.execute("SET LOCAL statement_timeout = '30s'")
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


def resolved(limit: int = 100000) -> dict:
    return {
        "llm": {"model": "fake"},
        "repl": {"timeout_ms": 30000},
        "protocol": {
            "max_invoke_input_length": limit,
            "truncation_prefix_ratio": 0.7,
            "max_repl_output_length": 4000,
        },
        "depth": 1,
    }


def seed(
    cur,
    invoke_id: str,
    *,
    iteration: int = 0,
    max_iter: int = 10,
    max_depth: int = 8,
    max_io: int = 3,
    max_stmt: int = 30000,
    pool_id: str | None = None,
    system: str = "SYSTEM",
    inputs: str | None = "inputs",
    limit: int = 100000,
    leased: bool = False,
    lease_past: bool = False,
    running_sql: str | None = None,
) -> str:
    scratch = scratch_for(invoke_id)
    cur.execute(
        "SELECT v15.v15_manifest_digest(%s, %s, %s, %s)",
        (max_iter, max_depth, max_io, max_stmt),
    )
    digest = cur.fetchone()[0]
    cur.execute(
        psycopg2.sql.SQL("CREATE SCHEMA {} AUTHORIZATION v15_owner").format(
            psycopg2.sql.Identifier(scratch)
        )
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
          %s, false, true, %s, 'cfg',
          %s, %s, %s, 1,
          CASE WHEN %s THEN %s ELSE NULL END,
          CASE
            WHEN NOT %s THEN NULL
            WHEN %s THEN clock_timestamp() - interval '1 second'
            ELSE clock_timestamp() + interval '10 minutes'
          END,
          clock_timestamp(), clock_timestamp()
        )
        """,
        (
            invoke_id, invoke_id, status, Json(resolved(limit)), pool_id,
            digest, scratch, leased, OWNER, leased, lease_past,
        ),
    )
    cur.execute(
        """
        INSERT INTO v15.iterations (invoke_id, iteration, status, resume_stmt, capture)
        VALUES (%s, %s, 'pending', 0, '')
        """,
        (invoke_id, iteration),
    )
    for ordinal, key, mx in (
        (0, "governance_iterations", max_iter),
        (1, "governance_depth", max_depth),
        (2, "governance_io", max_io),
        (3, "governance_statement", max_stmt),
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
    cur.execute(
        """
        INSERT INTO v15.llm_messages (
          invoke_id, msg_seq, message_id, iteration, role, kind, content
        ) VALUES (%s, 0, 'seed:system', NULL, 'system', 'seed', %s)
        """,
        (invoke_id, system),
    )
    if inputs is not None:
        cur.execute(
            """
            INSERT INTO v15.llm_messages (
              invoke_id, msg_seq, message_id, iteration, role, kind, content
            ) VALUES (%s, 1, 'seed:inputs', NULL, 'user', 'seed', %s)
            """,
            (invoke_id, inputs),
        )
    cur.execute(
        """
        INSERT INTO v15.invoke_events (
          invoke_id, seq, event_class, span, phase, outcome, payload, fence, created_at
        ) VALUES (
          %s, 0, 'span', 'invoke', 'enter', NULL, '{"depth":1}'::jsonb, 1,
          clock_timestamp()
        )
        """,
        (invoke_id,),
    )
    if running_sql is not None:
        cur.execute(
            """
            UPDATE v15.iterations
            SET status = 'executing'
            WHERE invoke_id = %s AND iteration = %s
            """,
            (invoke_id, iteration),
        )
        cur.execute(
            """
            INSERT INTO v15.statements (
              invoke_id, iteration, stmt_index, sql, sql_digest, kind, status
            ) VALUES (%s, %s, 0, %s, md5(%s), 'plain', 'running')
            """,
            (invoke_id, iteration, running_sql, running_sql),
        )
    return scratch


def base_messages(system: str = "SYSTEM", inputs: str | None = "inputs") -> list:
    rows = [{
        "message_id": "seed:system",
        "role": "system",
        "kind": "system",
        "content": system,
    }]
    if inputs is not None:
        rows.append({
            "message_id": "seed:inputs",
            "role": "user",
            "kind": "input",
            "content": inputs,
        })
    return rows


def claim(conn, invoke_id: str) -> int:
    fence = call(
        conn,
        "SELECT v15.v15_claim(%s, %s, %s::interval)",
        (invoke_id, OWNER, LEASE),
    )
    conn.commit()
    return fence


def begin(conn, invoke_id: str, fence: int, messages) -> dict:
    raw = call(
        conn,
        "SELECT v15.v15_begin_llm(%s, %s, %s, %s)",
        (invoke_id, fence, OWNER, Json(messages)),
    )
    conn.commit()
    return parse_json(raw)


def mark(conn, attempt_id: str, invoke_fence: int) -> None:
    call(
        conn,
        "SELECT v15.v15_mark_call_started(%s, %s, %s, %s)",
        (attempt_id, 1, invoke_fence, OWNER),
    )
    conn.commit()


def settle(conn, attempt_id: str, invoke_fence: int, response: dict, statements: list) -> None:
    call(
        conn,
        "SELECT v15.v15_settle_llm(%s, %s, %s, %s, %s, %s)",
        (attempt_id, 1, invoke_fence, OWNER, Json(response), Json(statements)),
    )
    conn.commit()


def expire_attempt(cur, attempt_id: str) -> None:
    cur.execute(
        """
        UPDATE v15.llm_attempts
        SET lease_until = clock_timestamp() - interval '1 second'
        WHERE attempt_id = %s
        """,
        (attempt_id,),
    )


def stmt_element(cur, sql: str, kind: str = "plain", bind_name=None, arg_sql=None, reject_code=None):
    cur.execute("SELECT md5(%s)", (sql,))
    return {
        "sql": sql,
        "sql_digest": cur.fetchone()[0],
        "kind": kind,
        "bind_name": bind_name,
        "arg_sql": arg_sql,
        "reject_code": reject_code,
    }


def failure_element(cur, source: str) -> dict:
    failed = split_sql(source)
    check("split failure", isinstance(failed, SplitFailure), type(failed))
    return stmt_element(
        cur, failed.sql, failed.kind, failed.bind_name, failed.arg_sql, failed.reject_code
    )


def pool(cur, *, calls_limit=None, calls_used=0, cost_limit=None) -> str:
    pool_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO v15.budget_pools (pool_id, calls_limit, calls_used, cost_limit)
        VALUES (%s, %s, %s, %s)
        """,
        (pool_id, calls_limit, calls_used, cost_limit),
    )
    return pool_id


def test_fake_and_worker() -> None:
    text = Path(FakeLLM.__module__.replace(".", "/") + ".py")
    src = (AGENT_ROOT / "v15" / "fake_llm.py").read_text()
    imports = "\n".join(
        line.strip()
        for line in src.splitlines()
        if line.startswith("import ") or line.startswith("from ")
    )
    for banned in ("socket", "random", "time", "urllib", "http"):
        check(f"fake_llm imports no {banned}", banned not in imports)
    sql = (ROOT / "v15_io.sql").read_text().lower()
    check("io sql has no set role", "set role" not in sql and "reset role" not in sql)
    check("io sql has no session authorization", "set session authorization" not in sql)
    llm = FakeLLM()
    llm.register("abc", 1, {"content": "x", "prompt_tokens": 1, "cost_usd": 0})
    first = llm.complete("abc", 1, {"attempt_id": "1", "messages": []})
    second = llm.complete("abc", 1, {"attempt_id": "2", "messages": []})
    check("fake same key same jsonb", first == second, (first, second))
    first["content"] = "mutated"
    third = llm.complete("abc", 1, {})
    check("fake copy is stable", third["content"] == "x", third)
    raised = False
    try:
        llm.complete("abc", 2, {})
    except KeyError:
        raised = True
    check("unregistered key fails", raised)
    check("40001 retries", classify_commit("40001") == "retry")
    check("40P01 retries", classify_commit("40P01") == "retry")
    check("40001 is not P1523", classify_commit("40001") != "P1523")
    check("40P01 is not P1523", classify_commit("40P01") != "P1523")
    check("P1523 stays", classify_commit("P1523") == "P1523")
    del text


def test_chain(server, scur, wconn) -> None:
    iid = str(uuid.uuid4())
    seed(scur, iid)
    scur.connection.commit()
    fence = claim(wconn, iid)
    check("claim fence", fence == 2, fence)
    opened = begin(wconn, iid, fence, base_messages())
    check("begin proceed", opened["action"] == "proceed", opened.get("action"))
    check("begin n", opened["n"] == 1, opened.get("n"))
    check("begin chars", opened["input_chars"] == len("SYSTEM") + len("inputs"), opened)
    expect(
        wconn,
        "SELECT v15.v15_begin_llm(%s, %s, %s, %s)",
        (iid, fence, OWNER, Json([])),
        "P1523",
        "second begin while leased attempt",
    )
    scur.execute(
        """
        SELECT count(*), bool_and(a.status = 'leased' AND NOT a.call_started)
        FROM v15.llm_attempts a
        JOIN v15.llm_requests r ON r.request_id = a.request_id
        WHERE r.invoke_id = %s
        """,
        (iid,),
    )
    count, leased = scur.fetchone()
    check("one leased attempt", count == 1 and leased, (count, leased))
    scur.execute(
        """
        SELECT payload
        FROM v15.invoke_events
        WHERE invoke_id = %s AND span = 'llm_query' AND phase = 'send'
        """,
        (iid,),
    )
    send = parse_json(scur.fetchone()[0])
    check("enter_messages null", send.get("enter_messages") is None, send)
    check("enter_overlay null", send.get("enter_overlay") is None, send)
    check("send digest is base", send.get("logical_digest") == opened["logical_digest"], send)
    scur.execute(
        """
        SELECT count(*) FROM v15.llm_messages
        WHERE invoke_id = %s AND kind = 'persistent_hook'
        """,
        (iid,),
    )
    check("begin does not insert hook messages", scur.fetchone()[0] == 0)
    mark(wconn, opened["attempt_id"], fence)
    expect(
        wconn,
        "SELECT v15.v15_mark_call_started(%s, %s, %s, %s)",
        (opened["attempt_id"], 1, fence, OWNER),
        "P1523",
        "repeat mark",
    )
    check(
        "fake call has no open transaction",
        wconn.get_transaction_status() == pgext.TRANSACTION_STATUS_IDLE,
        wconn.get_transaction_status(),
    )
    llm = FakeLLM()
    llm.register(opened["logical_digest"], opened["n"], {
        "content": "SELECT 1;",
        "prompt_tokens": 4,
        "cost_usd": 0,
    })
    response = llm.complete(opened["logical_digest"], opened["n"], opened["request"])
    element = stmt_element(scur, "SELECT 1")
    settle(wconn, opened["attempt_id"], fence, response, [element])
    scur.execute(
        """
        SELECT a.status, a.call_started, a.calls_charged, a.prompt_tokens, a.cost_usd,
               a.reserved_calls, a.reserved_cost, a.pool_id, r.status, r.logical_digest,
               i.status, i.resume_stmt, v.status, v.fence, v.fatal
        FROM v15.llm_attempts a
        JOIN v15.llm_requests r ON r.request_id = a.request_id
        JOIN v15.iterations i ON i.invoke_id = r.invoke_id AND i.iteration = r.iteration
        JOIN v15.invokes v ON v.invoke_id = r.invoke_id
        WHERE a.attempt_id = %s
        """,
        (opened["attempt_id"],),
    )
    row = scur.fetchone()
    check("settled flags", row[0] == "settled" and row[1] and row[2], row)
    check("tokens and cost", row[3] == 4 and row[4] == 0, row)
    check("default reserve", row[5] == 1 and row[6] == 0 and row[7] is None, row)
    check("request settled", row[8] == "settled" and row[9] == opened["logical_digest"], row)
    check("iteration executing", row[10] == "executing" and row[11] == 0, row)
    check("invoke still leased", row[12] == "leased" and row[13] == fence and row[14] is False, row)
    scur.execute(
        "SELECT md5((request - 'attempt_id')::text) FROM v15.llm_attempts WHERE attempt_id = %s",
        (opened["attempt_id"],),
    )
    check("stored digest matches request", scur.fetchone()[0] == opened["logical_digest"])
    scur.execute(
        """
        SELECT status, error, kind FROM v15.statements
        WHERE invoke_id = %s
        """,
        (iid,),
    )
    stmt = scur.fetchone()
    check("pending statement", stmt[0] == "pending" and stmt[1] is None and stmt[2] == "plain", stmt)
    scur.execute(
        """
        SELECT message_id, kind, content FROM v15.llm_messages
        WHERE invoke_id = %s AND role = 'assistant'
        """,
        (iid,),
    )
    assistant = scur.fetchone()
    check("assistant stored", assistant == (f"iter:0:assistant", "assistant", "SELECT 1;"), assistant)
    check("scratch remains", Path(scratch_for(iid)).name)
    scur.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (scratch_for(iid),))
    check("scratch still present", scur.fetchone() is not None)
    open_query = call(wconn, "SELECT v15.v15_span_open(%s, 'llm_query')", (iid,))
    wconn.commit()
    open_invoke = call(wconn, "SELECT v15.v15_span_open(%s, 'invoke')", (iid,))
    wconn.commit()
    check("llm_query closed", open_query is False, open_query)
    check("invoke span stays open", open_invoke is True, open_invoke)
    scur.execute(
        """
        SELECT phase, outcome FROM v15.invoke_events
        WHERE invoke_id = %s AND span = 'llm_query'
        ORDER BY seq
        """,
        (iid,),
    )
    phases = scur.fetchall()
    check(
        "llm events",
        phases == [("enter", None), ("send", None), ("complete", None), ("exit", "completed")],
        phases,
    )


def test_stale(server, scur, wconn) -> None:
    iid = str(uuid.uuid4())
    seed(scur, iid, inputs=None, system="S")
    scur.connection.commit()
    fence = claim(wconn, iid)
    expect(
        wconn,
        "SELECT v15.v15_begin_llm(%s, %s, %s, %s)",
        (iid, fence - 1, OWNER, Json(base_messages("S", None))),
        "P1501",
        "stale begin fence",
    )
    scur.execute(
        "SELECT status, fence FROM v15.invokes WHERE invoke_id = %s",
        (iid,),
    )
    check("stale begin wrote nothing", scur.fetchone() == ("leased", fence))
    scur.execute(
        """
        SELECT count(*) FROM v15.llm_attempts a
        JOIN v15.llm_requests r ON r.request_id = a.request_id
        WHERE r.invoke_id = %s
        """,
        (iid,),
    )
    check("stale begin no attempt", scur.fetchone()[0] == 0)
    opened = begin(wconn, iid, fence, base_messages("S", None))
    mark(wconn, opened["attempt_id"], fence)
    expect(
        wconn,
        "SELECT v15.v15_settle_llm(%s, %s, %s, %s, %s, %s)",
        (
            opened["attempt_id"], 99, fence, OWNER,
            Json({"content": "no"}), Json([]),
        ),
        "P1501",
        "stale attempt fence",
    )
    scur.execute(
        """
        SELECT status, call_started, response IS NULL
        FROM v15.llm_attempts WHERE attempt_id = %s
        """,
        (opened["attempt_id"],),
    )
    check("stale settle wrote nothing", scur.fetchone() == ("leased", True, True))


def test_unknown_and_failed(server, scur, wconn) -> None:
    unknown_pool = pool(scur)
    iid = str(uuid.uuid4())
    seed(scur, iid, pool_id=unknown_pool, system="U", inputs=None)
    scur.connection.commit()
    fence = claim(wconn, iid)
    opened = begin(wconn, iid, fence, base_messages("U", None))
    mark(wconn, opened["attempt_id"], fence)
    expire_attempt(scur, opened["attempt_id"])
    scur.connection.commit()
    n = call(wconn, "SELECT v15.v15_reclaim_expired()")
    wconn.commit()
    check("reclaim count", n == 1, n)
    scur.execute(
        """
        SELECT a.status, a.call_started, a.calls_charged,
               (SELECT count(*) FROM v15.llm_attempts x WHERE x.request_id = a.request_id)
        FROM v15.llm_attempts a
        WHERE a.attempt_id = %s
        """,
        (opened["attempt_id"],),
    )
    check("unknown no extra attempt", scur.fetchone() == ("unknown", True, True, 1))
    scur.execute(
        """
        SELECT calls_used, calls_reserved, cost_used, cost_reserved
        FROM v15.budget_pools WHERE pool_id = %s
        """,
        (unknown_pool,),
    )
    check("unknown charges calls only", scur.fetchone() == (1, 0, 0, 0))
    scur.execute(
        """
        SELECT payload FROM v15.invoke_events
        WHERE invoke_id = %s AND phase = 'retry'
        """,
        (iid,),
    )
    retry = parse_json(scur.fetchone()[0])
    check(
        "retry new_attempt_id null",
        retry["old_status"] == "unknown" and retry["new_attempt_id"] is None,
        retry,
    )
    still = call(wconn, "SELECT v15.v15_span_open(%s, 'llm_query')", (iid,))
    wconn.commit()
    check("reclaim leaves span open", still is True, still)
    expect(
        wconn,
        "SELECT v15.v15_settle_llm(%s, %s, %s, %s, %s, %s)",
        (opened["attempt_id"], 1, fence, OWNER, Json({"content": "late"}), Json([])),
        "P1502",
        "late settle rejected",
    )
    scur.execute(
        "SELECT count(*) FROM v15.llm_messages WHERE invoke_id = %s AND kind = 'assistant'",
        (iid,),
    )
    check("late settle wrote no transcript", scur.fetchone()[0] == 0)

    failed_pool = pool(scur)
    fid = str(uuid.uuid4())
    seed(scur, fid, pool_id=failed_pool, system="F", inputs=None)
    scur.connection.commit()
    ffence = claim(wconn, fid)
    fopened = begin(wconn, fid, ffence, base_messages("F", None))
    expect(
        wconn,
        "SELECT v15.v15_settle_llm(%s, %s, %s, %s, %s, %s)",
        (fopened["attempt_id"], 1, ffence, OWNER, Json({"content": "x"}), Json([])),
        "P1523",
        "settle before mark",
    )
    expire_attempt(scur, fopened["attempt_id"])
    scur.connection.commit()
    n = call(wconn, "SELECT v15.v15_reclaim_expired()")
    wconn.commit()
    check("failed reclaim count", n == 1, n)
    scur.execute(
        """
        SELECT a.status, a.call_started, a.calls_charged,
               p.calls_used, p.calls_reserved, p.cost_used
        FROM v15.llm_attempts a
        JOIN v15.budget_pools p ON p.pool_id = a.pool_id
        WHERE a.attempt_id = %s
        """,
        (fopened["attempt_id"],),
    )
    check("failed releases without charging", scur.fetchone() == ("failed", False, False, 0, 0, 0))
    expect(
        wconn,
        "SELECT v15.v15_settle_llm(%s, %s, %s, %s, %s, %s)",
        (fopened["attempt_id"], 1, ffence, OWNER, Json({"content": "late"}), Json([])),
        "P1502",
        "failed settle rejected",
    )


def test_retry_and_exhaust(server, scur, wconn) -> None:
    iid = str(uuid.uuid4())
    seed(scur, iid, system="R", inputs=None)
    scur.connection.commit()
    fence = claim(wconn, iid)
    opened = begin(wconn, iid, fence, base_messages("R", None))
    expire_attempt(scur, opened["attempt_id"])
    scur.connection.commit()
    call(wconn, "SELECT v15.v15_reclaim_expired()")
    wconn.commit()
    fence2 = claim(wconn, iid)
    check("reclaim bumped fence", fence2 == fence + 2, (fence, fence2))
    retried = begin(wconn, iid, fence2, [])
    check("retry proceed n+1", retried["action"] == "proceed" and retried["n"] == 2, retried)
    check("retry digest unchanged", retried["logical_digest"] == opened["logical_digest"])
    check("retry new attempt", retried["attempt_id"] != opened["attempt_id"])
    scur.execute(
        """
        SELECT phase FROM v15.invoke_events
        WHERE invoke_id = %s AND span = 'llm_query' AND phase IN ('enter', 'send')
        """,
        (iid,),
    )
    check("retry copies no enter/send", scur.fetchall() == [("enter",), ("send",)])
    scur.execute(
        """
        SELECT count(*) FROM v15.invoke_events
        WHERE invoke_id = %s AND event_class = 'audit'
          AND payload->>'op' = 'attempt_leased'
        """,
        (iid,),
    )
    check("two lease audits", scur.fetchone()[0] == 2)

    xid = str(uuid.uuid4())
    seed(scur, xid, max_io=1, system="X", inputs=None)
    scur.connection.commit()
    xfence = claim(wconn, xid)
    xopened = begin(wconn, xid, xfence, base_messages("X", None))
    expire_attempt(scur, xopened["attempt_id"])
    scur.connection.commit()
    call(wconn, "SELECT v15.v15_reclaim_expired()")
    wconn.commit()
    xfence2 = claim(wconn, xid)
    exhausted = begin(wconn, xid, xfence2, [])
    check(
        "io exhausted abort",
        exhausted["action"] == "abort"
        and exhausted["fatal"] is False
        and exhausted["code"] == "V15_IO_EXHAUSTED"
        and exhausted["attempt_id"] is None,
        exhausted,
    )
    scur.execute(
        """
        SELECT r.status, v.status, v.fatal, v.error->>'code', v.error->>'sqlstate',
               (SELECT count(*) FROM v15.llm_attempts a WHERE a.request_id = r.request_id)
        FROM v15.llm_requests r
        JOIN v15.invokes v ON v.invoke_id = r.invoke_id
        WHERE r.invoke_id = %s
        """,
        (xid,),
    )
    check("exhausted row", scur.fetchone() == ("exhausted", "failed", False, "V15_IO_EXHAUSTED", "P1513", 1))
    scur.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (scratch_for(xid),))
    check("exhausted drops scratch", scur.fetchone() is None)
    scur.execute(
        """
        SELECT outcome FROM v15.invoke_events
        WHERE invoke_id = %s AND span = 'llm_query' AND phase = 'exit'
        """,
        (xid,),
    )
    check("io exit failed", scur.fetchone()[0] == "failed")


def test_budget_and_iteration(server, scur, wconn) -> None:
    pid = pool(scur, calls_limit=1, calls_used=1)
    iid = str(uuid.uuid4())
    seed(scur, iid, pool_id=pid, system="B", inputs=None)
    scur.connection.commit()
    fence = claim(wconn, iid)
    aborted = begin(wconn, iid, fence, base_messages("B", None))
    check(
        "budget abort",
        aborted["action"] == "abort"
        and aborted["fatal"] is True
        and aborted["code"] == "V15_BUDGET_EXHAUSTED"
        and aborted["attempt_id"] is None,
        aborted,
    )
    scur.execute(
        """
        SELECT status, fatal, error->>'code', error->>'sqlstate', parent_invoke_id
        FROM v15.invokes WHERE invoke_id = %s
        """,
        (iid,),
    )
    check("self aborted", scur.fetchone() == ("aborted", True, "V15_BUDGET_EXHAUSTED", "P1514", None))
    scur.execute(
        "SELECT count(*) FROM v15.invokes WHERE status = 'aborted'"
    )
    check("no parent expansion", scur.fetchone()[0] == 1)
    scur.execute(
        """
        SELECT count(*) FROM v15.llm_attempts a
        JOIN v15.llm_requests r ON r.request_id = a.request_id
        WHERE r.invoke_id = %s
        """,
        (iid,),
    )
    check("budget inserts no attempt", scur.fetchone()[0] == 0)
    scur.execute(
        "SELECT calls_used, calls_reserved FROM v15.budget_pools WHERE pool_id = %s",
        (pid,),
    )
    check("reserve not left", scur.fetchone() == (1, 0))
    scur.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (scratch_for(iid),))
    check("budget drops scratch", scur.fetchone() is None)
    scur.execute(
        """
        SELECT phase, outcome FROM v15.invoke_events
        WHERE invoke_id = %s AND span = 'llm_query'
        ORDER BY seq
        """,
        (iid,),
    )
    check(
        "budget closed the opened span",
        scur.fetchall() == [("enter", None), ("send", None), ("exit", "aborted")],
    )
    scur.execute(
        "SELECT count(*) FROM v15.llm_messages WHERE invoke_id = %s AND kind <> 'seed'",
        (iid,),
    )
    check("budget wrote no hook message", scur.fetchone()[0] == 0)

    jid = str(uuid.uuid4())
    seed(scur, jid, iteration=10, system="I", inputs=None)
    scur.connection.commit()
    jfence = claim(wconn, jid)
    stopped = begin(wconn, jid, jfence, base_messages("I", None))
    check(
        "iteration abort",
        stopped["action"] == "abort"
        and stopped["fatal"] is False
        and stopped["code"] == "V15_ITERATION_EXCEEDED"
        and stopped["attempt_id"] is None,
        stopped,
    )
    scur.execute(
        """
        SELECT v.status, v.fatal, v.error->>'sqlstate', i.status, i.result_kind,
               h.repl_output, h.repl_exception->>'code'
        FROM v15.invokes v
        JOIN v15.iterations i ON i.invoke_id = v.invoke_id
        JOIN v15.repl_history h ON h.invoke_id = v.invoke_id AND h.iteration = i.iteration
        WHERE v.invoke_id = %s
        """,
        (jid,),
    )
    check(
        "iteration close shape",
        scur.fetchone() == ("failed", False, "P1520", "done", "continue", "", "V15_ITERATION_EXCEEDED"),
    )
    scur.execute(
        """
        SELECT count(*) FROM v15.invoke_events
        WHERE invoke_id = %s AND span = 'llm_query' AND phase = 'enter'
        """,
        (jid,),
    )
    check("iteration limit does not enter llm", scur.fetchone()[0] == 0)


def test_statements(server, scur, wconn) -> None:
    iid = str(uuid.uuid4())
    seed(scur, iid, system="V", inputs=None)
    scur.connection.commit()
    fence = claim(wconn, iid)
    opened = begin(wconn, iid, fence, base_messages("V", None))
    mark(wconn, opened["attempt_id"], fence)
    bad_digest = stmt_element(scur, "SELECT 1")
    bad_digest["sql_digest"] = "not-a-digest"
    bad_kind = stmt_element(scur, "SELECT 1")
    bad_kind["kind"] = "nope"
    bad_arg = stmt_element(scur, "SELECT 1", "bind_invoke", "child", None, None)
    for label, element in (
        ("bad digest", bad_digest),
        ("bad kind", bad_kind),
        ("bind_invoke missing arg_sql", bad_arg),
    ):
        expect(
            wconn,
            "SELECT v15.v15_settle_llm(%s, %s, %s, %s, %s, %s)",
            (opened["attempt_id"], 1, fence, OWNER, Json({"content": "x"}), Json([element])),
            "P1524",
            label,
        )
    scur.execute(
        """
        SELECT status, call_started,
               (SELECT count(*) FROM v15.statements s WHERE s.invoke_id = %s)
        FROM v15.llm_attempts WHERE attempt_id = %s
        """,
        (iid, opened["attempt_id"]),
    )
    check("validation left attempt leased", scur.fetchone() == ("leased", True, 0))

    did = str(uuid.uuid4())
    seed(scur, did, system="D", inputs=None)
    scur.connection.commit()
    dfence = claim(wconn, did)
    dopened = begin(wconn, did, dfence, base_messages("D", None))
    mark(wconn, dopened["attempt_id"], dfence)
    element = failure_element(scur, "select 'unterminated")
    check("dialect synthetic", element["reject_code"] == "V15_DIALECT")
    llm = FakeLLM()
    llm.register(dopened["logical_digest"], 1, {"content": element["sql"]})
    wconn.commit()
    check(
        "dialect fake idle",
        wconn.get_transaction_status() == pgext.TRANSACTION_STATUS_IDLE,
    )
    response = llm.complete(dopened["logical_digest"], 1, dopened["request"])
    settle(wconn, dopened["attempt_id"], dfence, response, [element])
    scur.execute(
        """
        SELECT a.status, s.status, s.kind, s.error->>'code', s.error->>'sqlstate', s.sql
        FROM v15.llm_attempts a
        JOIN v15.statements s ON s.invoke_id = %s
        WHERE a.attempt_id = %s
        """,
        (did, dopened["attempt_id"]),
    )
    row = scur.fetchone()
    check(
        "dialect row settled failed",
        row[:5] == ("settled", "failed", "plain", "V15_DIALECT", "P1511"),
        row,
    )
    check("dialect sql not executed", row[1] == "failed")

    nid = str(uuid.uuid4())
    seed(scur, nid, system="N", inputs=None)
    scur.connection.commit()
    nfence = claim(wconn, nid)
    nopened = begin(wconn, nid, nfence, base_messages("N", None))
    mark(wconn, nopened["attempt_id"], nfence)
    element = failure_element(scur, "has\x00nul")
    check("nul sanitized", "\\u0000" in element["sql"] and "\x00" not in element["sql"])
    check("nul reject", element["reject_code"] == "V15_VALUE_INVALID")
    rejected = False
    try:
        wconn.cursor().execute("SELECT %s::jsonb", (Json([{"sql": "has\x00nul"}]),))
        wconn.rollback()
    except (ValueError, psycopg2.Error):
        wconn.rollback()
        rejected = True
    check("raw nul stays out of settle args", rejected)
    llm = FakeLLM()
    llm.register(nopened["logical_digest"], 1, {"content": element["sql"]})
    response = llm.complete(nopened["logical_digest"], 1, nopened["request"])
    settle(wconn, nopened["attempt_id"], nfence, response, [element])
    scur.execute(
        """
        SELECT a.status, s.status, s.error->>'code', s.sql
        FROM v15.llm_attempts a
        JOIN v15.statements s ON s.invoke_id = %s
        WHERE a.attempt_id = %s
        """,
        (nid, nopened["attempt_id"]),
    )
    row = scur.fetchone()
    check("nul row settled failed", row[:3] == ("settled", "failed", "V15_VALUE_INVALID"), row)
    check("stored replacement", row[3] == element["sql"] and "\\u0000" in row[3], row)


def test_reclaim_invoke(server, scur, wconn) -> None:
    iid = str(uuid.uuid4())
    seed(scur, iid, leased=True, lease_past=True, running_sql="SELECT 1", system="Q", inputs=None)
    scur.connection.commit()
    n = call(wconn, "SELECT v15.v15_reclaim_expired()")
    wconn.commit()
    check("lease reclaim returns 0", n == 0, n)
    scur.execute(
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
        scur.fetchone() == ("runnable", 2, "pending", True, 0, "lease_reclaimed"),
    )
    fresh = str(uuid.uuid4())
    seed(scur, fresh, system="Z", inputs=None)
    scur.connection.commit()
    claim(wconn, fresh)
    n = call(wconn, "SELECT v15.v15_reclaim_expired()")
    wconn.commit()
    check("unexpired reclaim is empty", n == 0, n)


def test_input_chars(server, scur, wconn) -> None:
    iid = str(uuid.uuid4())
    seed(scur, iid, system="TOO-LONG", inputs=None, limit=3)
    scur.connection.commit()
    fence = claim(wconn, iid)
    expect(
        wconn,
        "SELECT v15.v15_begin_llm(%s, %s, %s, %s)",
        (iid, fence, OWNER, Json([])),
        "P1524",
        "bad base rolls back",
    )
    scur.execute("SELECT status FROM v15.invokes WHERE invoke_id = %s", (iid,))
    check("bad base still leased", scur.fetchone()[0] == "leased")
    stopped = begin(wconn, iid, fence, base_messages("TOO-LONG", None))
    check(
        "input_chars commits",
        stopped["action"] == "abort"
        and stopped["fatal"] is False
        and stopped["code"] == "V15_VALUE_INVALID",
        stopped,
    )
    scur.execute(
        "SELECT status, fatal, error->>'sqlstate' FROM v15.invokes WHERE invoke_id = %s",
        (iid,),
    )
    check("input_chars failed", scur.fetchone() == ("failed", False, "P1524"))


def main() -> int:
    setup_db()
    test_fake_and_worker()
    server = get_server()
    sconn = connect(server)
    wconn = connect(server, "v15_worker")
    sconn.autocommit = False
    wconn.autocommit = False
    try:
        scur = sconn.cursor()
        test_chain(server, scur, wconn)
        test_stale(server, scur, wconn)
        test_unknown_and_failed(server, scur, wconn)
        test_retry_and_exhaust(server, scur, wconn)
        test_budget_and_iteration(server, scur, wconn)
        test_statements(server, scur, wconn)
        test_reclaim_invoke(server, scur, wconn)
        test_input_chars(server, scur, wconn)
    finally:
        wconn.close()
        sconn.close()
    print("[ready] v15 io gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
