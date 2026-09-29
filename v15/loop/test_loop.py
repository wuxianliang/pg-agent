"""Stage 7 gate: single-invoke loop.

Run: uv run python v15/loop/test_loop.py  (exit 0 = pass)
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
from v15.loop.setup_db import DB, main as setup_db
from v15.protocol.render_prompt import render_system
from v15.worker import Worker, retryable_sqlstate, run_until_quiescent

SCOPE = "00000000-0000-4000-8000-0000000000b1"
OWNER = "loop-owner"
RETURN_SQL = 'SELECT jaz."return"(\'{"ok":true}\'::jsonb);'
RAISE_SQL = "SELECT jaz.\"raise\"('boom');"
PRINT_SQL = "SELECT jaz.print('seen');"
PROSE = "this is not sql"
UNCLOSED = "SELECT 'unterminated"
DO_AFTER = 'SELECT jaz."return"(\'1\'::jsonb); DO $$ BEGIN END $$;'
ORDERED = "SELECT 1; DO $$ BEGIN END $$; SELECT 2;"
SLOW = "-- timeout: 0.2\nSELECT count(*) FROM generate_series(1, 100000000);"


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


def open_invoke(conn, invoke_id: str, user: str | None = None) -> None:
    cur = conn.cursor()
    cur.execute("SET LOCAL lock_timeout = '2s'")
    cur.execute("SET LOCAL statement_timeout = '30s'")
    cur.execute(
        """
        SELECT v15.v15_open_invoke(%s, %s, NULL, '[]'::jsonb, NULL, NULL, %s, %s)
        """,
        (invoke_id, SCOPE, system_text(), user),
    )
    conn.commit()


def run(server, replies, worker_id: str = OWNER) -> Script:
    script = Script(replies)
    run_until_quiescent(server.get_uri(DB), script, worker_id)
    return script


def spans(cur, invoke_id: str):
    cur.execute(
        """
        SELECT span, phase, outcome
        FROM v15.invoke_events
        WHERE invoke_id = %s AND event_class = 'span'
        ORDER BY seq
        """,
        (invoke_id,),
    )
    return cur.fetchall()


def install_logger(cur) -> None:
    cur.execute(
        """
        CREATE TABLE public.v15_phase_log (
          id bigserial PRIMARY KEY,
          invoke_id uuid,
          iteration integer,
          span text,
          phase text,
          io jsonb
        )
        """
    )
    cur.execute(
        """
        CREATE FUNCTION public.v15_log_phase(
          invoke_id uuid,
          iteration integer,
          span text,
          phase text,
          io jsonb
        ) RETURNS jsonb
        LANGUAGE plpgsql
        AS $fn$
        BEGIN
          INSERT INTO public.v15_phase_log (invoke_id, iteration, span, phase, io)
          VALUES (invoke_id, iteration, span, phase, io);
          RETURN '{"contract":1,"action":"proceed"}'::jsonb;
        END
        $fn$
        """
    )
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
          SELECT public.v15_log_phase(invoke_id, iteration, span, phase, io)
        $fn$
        """
    )
    cur.execute("GRANT INSERT ON public.v15_phase_log TO v15_owner")
    cur.execute("GRANT USAGE, SELECT ON SEQUENCE public.v15_phase_log_id_seq TO v15_owner")
    cur.execute("GRANT EXECUTE ON FUNCTION public.v15_log_phase(uuid, integer, text, text, jsonb) TO v15_owner")
    cur.execute("GRANT USAGE ON SCHEMA public TO v15_owner")


def io_keys(cur, invoke_id: str, span: str, phase: str):
    cur.execute(
        """
        SELECT io
        FROM public.v15_phase_log
        WHERE invoke_id = %s AND span = %s AND phase = %s
        ORDER BY id
        """,
        (invoke_id, span, phase),
    )
    return [parse_json(row[0]) for row in cur.fetchall()]


def test_envelopes(cur, wconn) -> None:
    iid = str(uuid.uuid4())
    scratch = "s_" + iid.replace("-", "")
    cur.execute(
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
        (iid, iid, scratch),
    )
    cur.execute(
        """
        INSERT INTO v15.iterations (invoke_id, iteration, status, resume_stmt, capture)
        VALUES (%s, 0, 'pending', 0, '')
        """,
        (iid,),
    )
    for seq, span in ((0, "invoke"), (1, "llm_query"), (2, "repl_exec")):
        cur.execute(
            """
            INSERT INTO v15.invoke_events (
              invoke_id, seq, event_class, span, phase, payload, created_at
            ) VALUES (%s, %s, 'span', %s, 'enter', '{}'::jsonb, clock_timestamp())
            """,
            (iid, seq, span),
        )
    cur.execute(
        "GRANT EXECUTE ON FUNCTION v15.v15_repl_fatal_expand(uuid, text, text) TO v15_worker"
    )
    cur.connection.commit()
    wcur = wconn.cursor()
    wcur.execute("SET LOCAL lock_timeout = '2s'")
    wcur.execute("SET LOCAL statement_timeout = '30s'")
    wcur.execute(
        "SELECT v15.v15_repl_fatal_expand(%s, 'V15_BUDGET_EXHAUSTED', '')",
        (iid,),
    )
    wconn.commit()
    logged = io_keys(cur, iid, "llm_query", "exit")
    check("fatal llm_query exit io", logged == [{"attempt_id": None}], logged)
    check(
        "fatal repl_exec exit io",
        io_keys(cur, iid, "repl_exec", "exit") == [{"outcome": "aborted"}],
    )
    check(
        "fatal invoke exit io",
        io_keys(cur, iid, "invoke", "exit") == [{"outcome": "aborted"}],
    )
    cur.execute(
        """
        SELECT payload
        FROM v15.invoke_events
        WHERE invoke_id = %s AND span = 'llm_query' AND phase = 'exit'
        """,
        (iid,),
    )
    payload = parse_json(cur.fetchone()[0])
    check("llm_query exit event keeps outcome", payload.get("outcome") == "aborted", payload)


def test_retry(server) -> None:
    check("40001 classified retry", retryable_sqlstate("40001"))
    check("40P01 classified retry", retryable_sqlstate("40P01"))
    check("55P03 not retry", not retryable_sqlstate("55P03"))
    conn = connect(server)
    cur = conn.cursor()
    cur.execute("CREATE SEQUENCE public.v15_retry_seq")
    cur.execute(
        """
        CREATE FUNCTION public.v15_raise_once() RETURNS integer
        LANGUAGE plpgsql
        AS $fn$
        BEGIN
          IF nextval('public.v15_retry_seq') = 1 THEN
            RAISE EXCEPTION 'ser' USING ERRCODE = '40001';
          END IF;
          RETURN 7;
        END
        $fn$
        """
    )
    cur.execute("GRANT USAGE ON SEQUENCE public.v15_retry_seq TO v15_worker")
    cur.execute("GRANT EXECUTE ON FUNCTION public.v15_raise_once() TO v15_worker")
    conn.commit()
    worker = Worker(server.get_uri(DB), None, "retry-owner")
    try:
        got = worker._run(lambda c: worker._fetch(c, "SELECT public.v15_raise_once()"))
    finally:
        worker.close()
    check("40001 retried whole transfer", got == 7)


def test_scan_order(server, wconn) -> None:
    left = "00000000-0000-4000-8000-000000000101"
    right = "00000000-0000-4000-8000-000000000102"
    open_invoke(wconn, right)
    open_invoke(wconn, left)
    worker = Worker(server.get_uri(DB), Script([]), OWNER)
    try:
        order = worker.next_runnable()
    finally:
        worker.close()
    check("next_runnable orders invoke_id", order[:2] == [left, right], order)
    run(server, [RETURN_SQL, RETURN_SQL], "scan-owner")
    conn = connect(server)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT invoke_id::text
        FROM v15.invoke_events
        WHERE payload->>'op' = 'claim'
          AND invoke_id IN (%s, %s)
        ORDER BY created_at, invoke_id
        """,
        (left, right),
    )
    claimed = [row[0] for row in cur.fetchall()]
    check("lost notify still scanned", claimed == [left, right], claimed)
    conn.close()


def assert_closed(cur, invoke_id: str) -> None:
    rows = spans(cur, invoke_id)
    stack = []
    for span, phase, _outcome in rows:
        if phase == "enter":
            stack.append(span)
        elif phase == "exit":
            if not stack or stack[-1] != span:
                check("exit closes enter", False, rows)
            stack.pop()
    check("spans closed", stack == [], rows)
    cur.execute(
        "SELECT status, fatal, error IS NULL FROM v15.invokes WHERE invoke_id = %s",
        (invoke_id,),
    )
    check("return completed", cur.fetchone() == ("completed", False, True))
    cur.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", ("s_" + invoke_id.replace("-", ""),))
    check("scratch dropped", cur.fetchone() is None)


def test_return(server, wconn, cur) -> None:
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    script = run(server, [RETURN_SQL])
    check("one llm call", len(script.calls) == 1, len(script.calls))
    check(
        "return span shape",
        spans(cur, iid)
        == [
            ("invoke", "enter", None),
            ("llm_query", "enter", None),
            ("llm_query", "send", None),
            ("llm_query", "complete", None),
            ("llm_query", "exit", "completed"),
            ("repl_exec", "enter", None),
            ("repl_exec", "send", None),
            ("repl_exec", "complete", None),
            ("repl_exec", "exit", "completed"),
            ("invoke", "complete", None),
            ("invoke", "exit", "completed"),
        ],
        spans(cur, iid),
    )
    query_io = io_keys(cur, iid, "llm_query", "exit")
    check(
        "settle llm_query exit envelope",
        len(query_io) == 1 and set(query_io[0]) == {"attempt_id"} and query_io[0]["attempt_id"],
        query_io,
    )
    check(
        "repl_exec exit envelope",
        io_keys(cur, iid, "repl_exec", "exit") == [{"outcome": "completed"}],
    )
    check(
        "invoke exit envelope",
        io_keys(cur, iid, "invoke", "exit") == [{"outcome": "completed"}],
    )
    assert_closed(cur, iid)
    cur.execute(
        """
        SELECT it.result_kind, h.repl_output, h.repl_exception IS NULL
        FROM v15.repl_history h
        JOIN v15.iterations it
          ON it.invoke_id = h.invoke_id AND it.iteration = h.iteration
        WHERE h.invoke_id = %s
        """,
        (iid,),
    )
    check("return history", cur.fetchone() == ("return", "", True))


def test_raise(server, wconn, cur) -> None:
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    run(server, [RAISE_SQL])
    cur.execute(
        """
        SELECT status, fatal, error->>'code', error->>'sqlstate'
        FROM v15.invokes WHERE invoke_id = %s
        """,
        (iid,),
    )
    check("raise terminal", cur.fetchone() == ("failed", False, "V15_RAISE", "P1529"))
    cur.execute(
        """
        SELECT it.result_kind, h.repl_output, h.repl_exception->>'code'
        FROM v15.repl_history h
        JOIN v15.iterations it
          ON it.invoke_id = h.invoke_id AND it.iteration = h.iteration
        WHERE h.invoke_id = %s
        """,
        (iid,),
    )
    check("raise history", cur.fetchone() == ("raise", "", "V15_RAISE"))
    rows = spans(cur, iid)
    check("raise has no invoke complete", ("invoke", "complete", None) not in rows, rows)
    check(
        "raise exits",
        ("repl_exec", "exit", "failed") in rows and ("invoke", "exit", "failed") in rows,
        rows,
    )


def test_continue_paths(server, wconn, cur) -> None:
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    try:
        run(server, [PRINT_SQL, StopScript])
        check("print should stop", False)
    except StopScript:
        pass
    cur.execute(
        """
        SELECT i.status, h.iteration, h.repl_output, it.result_kind
        FROM v15.invokes i
        JOIN v15.repl_history h ON h.invoke_id = i.invoke_id
        JOIN v15.iterations it ON it.invoke_id = h.invoke_id AND it.iteration = h.iteration
        WHERE i.invoke_id = %s
        ORDER BY h.iteration
        """,
        (iid,),
    )
    rows = cur.fetchall()
    check("current round absent from history", rows == [("leased", 0, "seen", "continue")], rows)
    wconn2 = connect(server, "v15_worker")
    wcur = wconn2.cursor()
    wcur.execute("SELECT pg_backend_pid()")
    pid = wcur.fetchone()[0]
    cur.execute(
        """
        INSERT INTO v15.exec_context (
          backend_pid, invoke_id, iteration, stmt_index, scratch_schema, revision
        )
        SELECT %s, invoke_id, 1, 0, scratch_schema, 0
        FROM v15.invokes WHERE invoke_id = %s
        """,
        (pid, iid),
    )
    cur.connection.commit()
    wcur.execute("SET ROLE v15_repl")
    wcur.execute("SELECT iteration FROM jaz.history ORDER BY iteration")
    check("view hides current round", wcur.fetchall() == [(0,)])
    wcur.execute("RESET ROLE")
    wconn2.close()

    empty = str(uuid.uuid4())
    open_invoke(wconn, empty)
    try:
        run(server, ["", StopScript])
    except StopScript:
        pass
    cur.execute(
        """
        SELECT it.result_kind, h.repl_output,
               (SELECT count(*) FROM v15.statements s
                WHERE s.invoke_id = it.invoke_id AND s.iteration = 0),
               i.status
        FROM v15.iterations it
        JOIN v15.repl_history h
          ON h.invoke_id = it.invoke_id AND h.iteration = it.iteration
        JOIN v15.invokes i ON i.invoke_id = it.invoke_id
        WHERE it.invoke_id = %s AND it.iteration = 0
        """,
        (empty,),
    )
    check("empty message continues", cur.fetchone() == ("continue", "", 0, "leased"))
    check(
        "empty repl_exec exit completed",
        ("repl_exec", "exit", "completed") in spans(cur, empty),
    )

    prose = str(uuid.uuid4())
    open_invoke(wconn, prose)
    try:
        run(server, [PROSE, StopScript])
    except StopScript:
        pass
    cur.execute(
        """
        SELECT s.status, s.error->>'sqlstate', s.error->>'code', it.result_kind, i.status
        FROM v15.statements s
        JOIN v15.iterations it
          ON it.invoke_id = s.invoke_id AND it.iteration = s.iteration
        JOIN v15.invokes i ON i.invoke_id = s.invoke_id
        WHERE s.invoke_id = %s AND s.iteration = 0
        """,
        (prose,),
    )
    row = cur.fetchone()
    check("prose continues invoke", row[0] == "failed" and row[1] == row[2] == "42601", row)
    check("prose result continue", row[3] == "continue" and row[4] == "leased", row)
    check(
        "prose repl_exec exit completed",
        ("repl_exec", "exit", "completed") in spans(cur, prose),
    )

    split = str(uuid.uuid4())
    open_invoke(wconn, split)
    try:
        run(server, [UNCLOSED, StopScript])
    except StopScript:
        pass
    cur.execute(
        """
        SELECT s.status, s.error->>'code', a.status, it.result_kind, i.status
        FROM v15.statements s
        JOIN v15.iterations it
          ON it.invoke_id = s.invoke_id AND it.iteration = s.iteration
        JOIN v15.invokes i ON i.invoke_id = s.invoke_id
        JOIN v15.llm_requests r ON r.invoke_id = s.invoke_id AND r.iteration = 0
        JOIN v15.llm_attempts a ON a.request_id = r.request_id
        WHERE s.invoke_id = %s
        """,
        (split,),
    )
    check(
        "split failure continues",
        cur.fetchone() == ("failed", "V15_DIALECT", "settled", "continue", "leased"),
    )

    ordered = str(uuid.uuid4())
    open_invoke(wconn, ordered)
    try:
        run(server, [ORDERED, StopScript])
    except StopScript:
        pass
    cur.execute(
        """
        SELECT stmt_index, status, error->>'code'
        FROM v15.statements
        WHERE invoke_id = %s AND iteration = 0
        ORDER BY stmt_index
        """,
        (ordered,),
    )
    ordered_rows = cur.fetchall()
    check(
        "ordered first error skips the rest",
        ordered_rows == [(0, "done", None), (1, "failed", "V15_DIALECT"), (2, "skipped", None)],
        ordered_rows,
    )

    skipped = str(uuid.uuid4())
    open_invoke(wconn, skipped)
    run(server, [DO_AFTER])
    cur.execute(
        """
        SELECT stmt_index, status, error->>'code'
        FROM v15.statements
        WHERE invoke_id = %s AND iteration = 0
        ORDER BY stmt_index
        """,
        (skipped,),
    )
    check(
        "return skips later failed",
        cur.fetchall() == [(0, "done", None), (1, "skipped", "V15_DIALECT")],
    )
    cur.execute("SELECT status FROM v15.invokes WHERE invoke_id = %s", (skipped,))
    check("return after skip completed", cur.fetchone()[0] == "completed")


def test_timeout(server, wconn, cur) -> None:
    iid = str(uuid.uuid4())
    open_invoke(wconn, iid)
    try:
        run(server, [SLOW, StopScript])
    except StopScript:
        pass
    cur.execute(
        """
        SELECT error->>'code', error->>'sqlstate', status
        FROM v15.statements
        WHERE invoke_id = %s AND iteration = 0
        """,
        (iid,),
    )
    check("statement deadline", cur.fetchone() == ("V15_STATEMENT_TIMEOUT", "P1526", "failed"))


def main() -> int:
    server = get_server()
    setup_db()
    conn = connect(server)
    cur = conn.cursor()
    install_logger(cur)
    conn.commit()
    wconn = connect(server, "v15_worker")
    test_envelopes(cur, wconn)
    conn.commit()
    test_retry(server)
    test_scan_order(server, wconn)
    test_return(server, wconn, cur)
    test_raise(server, wconn, cur)
    test_continue_paths(server, wconn, cur)
    test_timeout(server, wconn, cur)
    wconn.close()
    conn.close()
    print("ALL PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
