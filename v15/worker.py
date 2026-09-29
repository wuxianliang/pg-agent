"""v15 worker loop. Provider calls run only between committed transactions.

Three clocks stay apart. _begin statement_timeout is 30s and covers transfer
SQL only. FakeLLM lease defaults to 30s so crash recovery stays short. A real
provider timeout_s (120s) is a monotonic total deadline; that Worker's lease
must be at least timeout_s + 60s so a slow success can still settle.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import psycopg2
from psycopg2 import extensions as pgext
from psycopg2 import sql
from psycopg2.extras import Json

from v15.protocol.render_prompt import render_inputs, render_system, truncate_base
from v15.protocol.split_sql import SplitFailure, classify_statement, split_sql, sql_without_timeout_pragma
from v15.provider.errors import ProviderPreflight, ProviderRejected, ProviderUncertain

RETRYABLE = frozenset({"40001", "40P01"})
LEASE = "30 seconds"
_LEASE_RE = re.compile(r"(\d+(?:\.\d+)?)\s+seconds?")
CAP = 256
BIND_FAIL = {
    "P1503": "V15_INVOKE_FORM",
    "P1505": "V15_GOVERNANCE_RAISE",
    "P1509": "V15_SCOPE_CONFLICT",
    "P1518": "V15_RECURSION_DISABLED",
    "P1524": "V15_VALUE_INVALID",
}


def retryable_sqlstate(sqlstate: str | None) -> bool:
    return sqlstate in RETRYABLE


def _lease_seconds(lease: str) -> float | None:
    matched = _LEASE_RE.fullmatch(lease.strip())
    if matched is None:
        return None
    return float(matched.group(1))


def _integral_token(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value >= 1 else None
    if isinstance(value, float) and value.is_integer() and 1 <= value <= 2147483647:
        return int(value)
    return None


def normalize_llm(llm_config):
    if not isinstance(llm_config, dict):
        return llm_config
    out = dict(llm_config)
    if "max_output_tokens" in out:
        normalized = _integral_token(out["max_output_tokens"])
        if normalized is not None:
            out["max_output_tokens"] = normalized
    return out


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def response_arg(response: dict):
    body = dict(response)
    content = body.get("content")
    if isinstance(content, str):
        body["content"] = content.replace("\x00", "\\u0000")
    cost = body.get("cost_usd")
    if isinstance(cost, Decimal):
        body.pop("cost_usd")
        text = json.dumps(body, ensure_ascii=False)
        cost_text = format(cost, "f")
        if text == "{}":
            return '{"cost_usd":' + cost_text + "}", True
        return text[:-1] + ',"cost_usd":' + cost_text + "}", True
    return body, False


def connect_worker(db_dsn: str):
    parsed = urlparse(db_dsn)
    qs = parse_qs(parsed.query)
    host = (qs.get("host") or [None])[0]
    dbname = parsed.path.lstrip("/") or (qs.get("dbname") or [None])[0]
    if host and dbname:
        conn = psycopg2.connect(host=host, dbname=dbname, user="v15_worker")
    else:
        conn = psycopg2.connect(db_dsn)
    conn.autocommit = False
    return conn


def parse_json(value):
    if isinstance(value, str):
        return json.loads(value)
    return value


def _element(text: str, kind: str, bind_name, arg_sql, reject_code) -> dict:
    return {
        "sql": text,
        "sql_digest": hashlib.md5(text.encode("utf-8")).hexdigest(),
        "kind": kind,
        "bind_name": bind_name,
        "arg_sql": arg_sql,
        "reject_code": reject_code,
    }


def statement_payload(content: str) -> list[dict]:
    split = split_sql(content)
    if isinstance(split, SplitFailure):
        return [
            _element(split.sql, split.kind, split.bind_name, split.arg_sql, split.reject_code)
        ]
    out = []
    for text in split:
        classified = classify_statement(text)
        out.append(
            _element(
                text,
                classified.kind,
                classified.bind_name,
                classified.arg_sql,
                classified.reject_code,
            )
        )
    return out


def error_of(exc: psycopg2.Error, *, timeout: bool) -> dict:
    if timeout:
        return {
            "sqlstate": "P1526",
            "code": "V15_STATEMENT_TIMEOUT",
            "message": (str(exc).splitlines() or [""])[0][:1024],
        }
    code = exc.pgcode or "XX000"
    line = (str(exc).splitlines() or [""])[0][:1024]
    return {"sqlstate": code, "code": code, "message": line}


def build_base(snap: dict) -> list[dict]:
    bindings = snap["bindings"]
    protocol = snap["resolved_config"]["protocol"]
    messages = []
    for row in snap["messages"]:
        message_id = row["message_id"]
        if message_id == "seed:system":
            kind = "system"
            content = render_system(
                recursion_available=bool(snap["recursion_available"]),
                bindings=bindings,
            )
        elif message_id == "seed:inputs":
            kind = "input"
            content = row["content"]
        else:
            kind = row["kind"]
            content = row["content"]
        messages.append(
            {
                "message_id": message_id,
                "role": row["role"],
                "kind": kind,
                "content": content,
            }
        )
    return truncate_base(messages, protocol)


class Worker:
    def __init__(self, db_dsn: str, fakellm, worker_id: str, *, lease: str = LEASE) -> None:
        if not isinstance(worker_id, str) or not 1 <= len(worker_id) <= 200:
            raise TypeError("worker_id")
        timeout_s = getattr(fakellm, "timeout_s", None)
        if timeout_s is not None:
            seconds = _lease_seconds(lease)
            if seconds is None or seconds < float(timeout_s) + 60:
                raise ValueError("lease")
        self.db_dsn = db_dsn
        self.fakellm = fakellm
        self.worker_id = worker_id
        self.lease = lease
        self.conn = connect_worker(db_dsn)

    def close(self) -> None:
        try:
            closer = getattr(self.fakellm, "close", None)
            if closer is not None:
                closer()
        finally:
            if self.conn is not None and not self.conn.closed:
                self.conn.close()

    def _replace_conn(self) -> None:
        if self.conn is not None and not self.conn.closed:
            try:
                self.conn.close()
            except psycopg2.Error:
                pass
        self.conn = connect_worker(self.db_dsn)

    def _begin(self, conn) -> None:
        cur = conn.cursor()
        cur.execute("SET LOCAL lock_timeout = '2s'")
        cur.execute("SET LOCAL statement_timeout = '30s'")

    def _run(self, fn):
        while True:
            try:
                self._begin(self.conn)
                result = fn(self.conn)
                self.conn.commit()
                return result
            except psycopg2.Error as exc:
                self.conn.rollback()
                if retryable_sqlstate(exc.pgcode):
                    continue
                raise

    def _fetch(self, conn, query: str, args=()):
        cur = conn.cursor()
        cur.execute(query, args)
        row = cur.fetchone()
        return None if row is None else row[0]

    def reclaim(self) -> None:
        self._run(lambda conn: self._fetch(conn, "SELECT v15.v15_reclaim_expired()"))

    def next_runnable(self) -> list[str]:
        def read(conn):
            cur = conn.cursor()
            cur.execute("SELECT v15.v15_next_runnable()")
            return [str(row[0]) for row in cur.fetchall() if row[0] is not None]

        return self._run(read)

    def claim(self, invoke_id: str):
        def read(conn):
            return self._fetch(
                conn,
                "SELECT v15.v15_claim(%s, %s, %s::interval)",
                (invoke_id, self.worker_id, self.lease),
            )

        fence = self._run(read)
        return None if fence is None else int(fence)

    def snapshot(self, invoke_id: str) -> dict:
        raw = self._run(
            lambda conn: self._fetch(
                conn, "SELECT v15.v15_loop_snapshot(%s)", (invoke_id,)
            )
        )
        return parse_json(raw)

    def drive(self, invoke_id: str, fence: int) -> None:
        while True:
            snap = self.snapshot(invoke_id)
            if snap["status"] != "leased" or snap["lease_owner"] != self.worker_id:
                return
            if int(snap["fence"]) != fence:
                return
            status = snap["iter_status"]
            attempt = snap["attempt"]
            if attempt and attempt.get("status") == "leased" and attempt.get("call_started"):
                return
            if status == "pending" or (
                status == "llm" and not (attempt and attempt.get("status") == "leased")
            ):
                self._llm(invoke_id, fence, snap, attempt)
                continue
            if attempt and attempt.get("status") == "leased" and not attempt.get("call_started"):
                self._mark_and_settle(invoke_id, fence, attempt, snap["resolved_config"]["llm"])
                continue
            if status == "executing" and not snap["repl_exec_open"]:
                self._run(
                    lambda conn: self._fetch(
                        conn,
                        "SELECT v15.v15_begin_exec(%s, %s, %s)",
                        (invoke_id, fence, self.worker_id),
                    )
                )
                continue
            if status == "executing" and snap["repl_exec_open"]:
                if self._exec_until_boundary(invoke_id, fence, snap):
                    self._finish(invoke_id, fence)
                    return
                continue
            return

    def _llm(self, invoke_id: str, fence: int, snap: dict, attempt) -> None:
        if attempt and attempt.get("status") == "leased" and not attempt.get("call_started"):
            self._mark_and_settle(invoke_id, fence, attempt, snap["resolved_config"]["llm"])
            return
        base = build_base(snap)

        def begin(conn):
            return parse_json(
                self._fetch(
                    conn,
                    "SELECT v15.v15_begin_llm(%s, %s, %s, %s)",
                    (invoke_id, fence, self.worker_id, Json(base)),
                )
            )

        opened = self._run(begin)
        if opened["action"] != "proceed":
            return
        attempt = {
            "attempt_id": opened["attempt_id"],
            "n": opened["n"],
            "fence": 1,
            "logical_digest": opened["logical_digest"],
            "request": opened["request"],
            "call_started": False,
            "status": "leased",
        }
        self._mark_and_settle(invoke_id, fence, attempt, snap["resolved_config"]["llm"])

    def _assert_idle(self) -> None:
        if self.conn.get_transaction_status() != pgext.TRANSACTION_STATUS_IDLE:
            raise RuntimeError("provider requires no open transaction")

    def _run_provider(self, fn) -> None:
        try:
            self._run(fn)
        except psycopg2.Error as exc:
            if exc.pgcode == "P1502":
                return
            raise

    def _lease_covers(self, invoke_id: str) -> bool:
        timeout_s = getattr(self.fakellm, "timeout_s", None)
        if timeout_s is None:
            return True
        remaining = self._run(
            lambda conn: self._fetch(
                conn,
                "SELECT v15.v15_invoke_lease_seconds(%s)",
                (invoke_id,),
            )
        )
        if remaining is None:
            return False
        return float(remaining) >= float(timeout_s) + 60

    def _mark_and_settle(self, invoke_id: str, fence: int, attempt: dict, llm_config) -> None:
        provider = self.fakellm
        llm_config = normalize_llm(llm_config)
        attempt_id = str(attempt["attempt_id"])
        attempt_fence = int(attempt["fence"])
        if hasattr(provider, "preflight"):
            preflight = provider.preflight(llm_config)
            if preflight is not None:
                self._run_provider(
                    lambda conn: self._fetch(
                        conn,
                        "SELECT v15.v15_provider_reject_unstarted(%s, %s, %s, %s, %s)",
                        (
                            attempt_id,
                            attempt_fence,
                            fence,
                            self.worker_id,
                            preflight["class"],
                        ),
                    )
                )
                return

        def mark(conn):
            self._fetch(
                conn,
                "SELECT v15.v15_mark_call_started(%s, %s, %s, %s)",
                (attempt_id, attempt_fence, fence, self.worker_id),
            )

        self._run(mark)
        self._assert_idle()
        if not self._lease_covers(invoke_id):
            return
        try:
            response = provider.complete(
                attempt["logical_digest"],
                int(attempt["n"]),
                attempt["request"],
                llm_config,
            )
        except ProviderRejected as exc:
            self._assert_idle()
            self._run_provider(
                lambda conn: self._fetch(
                    conn,
                    "SELECT v15.v15_provider_reject_started(%s, %s, %s, %s, %s)",
                    (
                        attempt_id,
                        attempt_fence,
                        fence,
                        self.worker_id,
                        Json(exc.detail),
                    ),
                )
            )
            return
        except ProviderUncertain as exc:
            self._assert_idle()
            http_status = exc.detail.get("http_status")
            self._run_provider(
                lambda conn: self._fetch(
                    conn,
                    "SELECT v15.v15_provider_abandon(%s, %s, %s, %s, %s)",
                    (
                        attempt_id,
                        attempt_fence,
                        fence,
                        self.worker_id,
                        Json(exc.detail),
                    ),
                )
            )
            if http_status == 429:
                _sleep(1)
            return
        except ProviderPreflight:
            raise
        raw = response["content"]
        payload = statement_payload(raw)
        encoded, as_text = response_arg(response)

        def settle(conn):
            if as_text:
                self._fetch(
                    conn,
                    "SELECT v15.v15_settle_llm(%s, %s, %s, %s, %s::jsonb, %s)",
                    (
                        attempt_id,
                        attempt_fence,
                        fence,
                        self.worker_id,
                        encoded,
                        Json(payload),
                    ),
                )
            else:
                self._fetch(
                    conn,
                    "SELECT v15.v15_settle_llm(%s, %s, %s, %s, %s, %s)",
                    (
                        attempt_id,
                        attempt_fence,
                        fence,
                        self.worker_id,
                        Json(encoded),
                        Json(payload),
                    ),
                )

        self._run(settle)

    def _finish(self, invoke_id: str, fence: int) -> None:
        self._run(
            lambda conn: self._fetch(
                conn,
                "SELECT v15.v15_finish_exec(%s, %s, %s)",
                (invoke_id, fence, self.worker_id),
            )
        )

    def _exec_until_boundary(self, invoke_id: str, fence: int, snap: dict) -> bool:
        statements = snap["statements"]
        if any(
            row["kind"] in {"return", "raise"} and row["status"] == "done"
            for row in statements
        ):
            return True
        resume = int(snap["resume_stmt"])
        current = next((row for row in statements if row["stmt_index"] == resume), None)
        if current is None or current["status"] == "failed" or current["error"] is not None:
            return True
        if current["status"] != "pending":
            return True
        if current["kind"] == "bind_invoke":
            self._bind_invoke(invoke_id, fence, index=int(current["stmt_index"]))
            return False
        self._execute_one(invoke_id, fence, current)
        return False

    def _bind_error(self, exc: psycopg2.Error) -> dict:
        code = exc.pgcode or "XX000"
        if code in BIND_FAIL:
            line = (str(exc).splitlines() or [""])[0][:1024]
            return {"sqlstate": code, "code": BIND_FAIL[code], "message": line}
        return error_of(exc, timeout=False)

    def _value_invalid(self) -> dict:
        return {
            "sqlstate": "P1524",
            "code": "V15_VALUE_INVALID",
            "message": "bind argument must be one jsonb object",
        }

    def _jsonb_text(self, cur, obj, key: str) -> str:
        cur.execute("SELECT ((%s::jsonb) -> %s)::text", (Json(obj), key))
        return cur.fetchone()[0]

    def _child_seed(self, cur, facts: dict, child_inputs) -> tuple[str, str | None]:
        depth = int(facts["depth"]) + 1
        limit = min(int(facts["max_depth"]), int(facts["manifest_max_depth"]))
        bindings = [dict(row) for row in facts["bindings"]]
        if isinstance(child_inputs, dict):
            for name in child_inputs:
                bindings.append(
                    {
                        "name": name,
                        "kind": "input",
                        "show_in_prompt": True,
                        "value_text": self._jsonb_text(cur, child_inputs, name),
                    }
                )
        system = render_system(recursion_available=depth < limit, bindings=bindings)
        return system, render_inputs(bindings)

    def _complete_failed(self, cur, invoke_id: str, fence: int, index: int, info: dict, err: dict) -> None:
        cur.execute("ROLLBACK TO SAVEPOINT model_stmt")
        cur.execute("RESET ROLE")
        cur.execute(
            """
            SELECT v15.v15_complete_statement(
              %s, %s, %s, %s, %s, 'failed', %s
            )
            """,
            (
                invoke_id,
                fence,
                self.worker_id,
                index,
                int(info["statement_fence"]),
                Json(err),
            ),
        )

    def _bind_invoke(self, invoke_id: str, fence: int, index: int) -> None:
        while True:
            fired = {"done": False, "hit": False}
            timer = None
            try:
                self._begin(self.conn)
                cur = self.conn.cursor()
                cur.execute("SELECT pg_backend_pid()")
                pid = cur.fetchone()[0]
                cur.execute(
                    "SELECT v15.v15_prepare_statement(%s, %s, %s, %s)",
                    (invoke_id, fence, self.worker_id, index),
                )
                info = parse_json(cur.fetchone()[0])
                cur.execute(
                    "SELECT v15.v15_tree_bind_context(%s, %s)",
                    (invoke_id, index),
                )
                facts = parse_json(cur.fetchone()[0])
                timeout_ms = int(info["timeout_ms"])
                timer = threading.Timer(
                    timeout_ms / 1000.0,
                    self._cancel,
                    args=(pid, fired),
                )
                timer.daemon = True
                timer.start()
                cur.execute(
                    sql.SQL("SET LOCAL search_path TO {}, pg_catalog").format(
                        sql.Identifier(info["scratch_schema"])
                    )
                )
                cur.execute(
                    f"SET LOCAL statement_timeout = '{timeout_ms + 1000}ms'"
                )
                cur.execute("SAVEPOINT model_stmt")
                if not facts.get("arg_sql"):
                    fired["done"] = True
                    timer.cancel()
                    self._complete_failed(
                        cur, invoke_id, fence, index, info, self._value_invalid()
                    )
                    self.conn.commit()
                    return
                cur.execute("SET LOCAL ROLE v15_repl")
                phase = "eval"
                try:
                    cur.execute(f"SELECT ({facts['arg_sql']})")
                    rows = cur.fetchall() if cur.description else []
                    value = rows[0][0] if len(rows) == 1 else None
                    if isinstance(value, str):
                        try:
                            value = json.loads(value)
                        except json.JSONDecodeError:
                            value = None
                    if len(rows) != 1 or not isinstance(value, dict):
                        fired["done"] = True
                        timer.cancel()
                        self._complete_failed(
                            cur, invoke_id, fence, index, info, self._value_invalid()
                        )
                        self.conn.commit()
                        return
                    cur.execute("RESET ROLE")
                    system, user = self._child_seed(cur, facts, value)
                    phase = "suspend"
                    cur.execute(
                        """
                        SELECT v15.v15_suspend_for_child(
                          %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        """,
                        (
                            invoke_id,
                            fence,
                            self.worker_id,
                            index,
                            int(info["statement_fence"]),
                            Json(value),
                            system,
                            user,
                        ),
                    )
                except psycopg2.Error as exc:
                    if exc.pgcode == "57014":
                        raise
                    if phase == "suspend" and exc.pgcode not in BIND_FAIL:
                        raise
                    fired["done"] = True
                    timer.cancel()
                    self._complete_failed(
                        cur, invoke_id, fence, index, info, self._bind_error(exc)
                    )
                    self.conn.commit()
                    return
                fired["done"] = True
                timer.cancel()
                self.conn.commit()
                return
            except psycopg2.Error as exc:
                fired["done"] = True
                if timer is not None:
                    timer.cancel()
                try:
                    self.conn.rollback()
                except psycopg2.Error:
                    pass
                if retryable_sqlstate(exc.pgcode):
                    continue
                if exc.pgcode == "57014" or fired["hit"]:
                    self._replace_conn()
                    self._fail_cancelled(invoke_id, fence, index, exc, timeout=True)
                    return
                raise

    def _execute_one(self, invoke_id: str, fence: int, stmt: dict) -> None:
        index = int(stmt["stmt_index"])
        text = sql_without_timeout_pragma(stmt["sql"])
        while True:
            fired = {"done": False, "hit": False}
            timer = None
            try:
                self._begin(self.conn)
                cur = self.conn.cursor()
                cur.execute("SELECT pg_backend_pid()")
                pid = cur.fetchone()[0]
                cur.execute(
                    "SELECT v15.v15_prepare_statement(%s, %s, %s, %s)",
                    (invoke_id, fence, self.worker_id, index),
                )
                info = parse_json(cur.fetchone()[0])
                timeout_ms = int(info["timeout_ms"])
                timer = threading.Timer(
                    timeout_ms / 1000.0,
                    self._cancel,
                    args=(pid, fired),
                )
                timer.daemon = True
                timer.start()
                cur.execute(
                    sql.SQL("SET LOCAL search_path TO {}, pg_catalog").format(
                        sql.Identifier(info["scratch_schema"])
                    )
                )
                cur.execute(
                    f"SET LOCAL statement_timeout = '{timeout_ms + 1000}ms'"
                )
                cur.execute("SAVEPOINT model_stmt")
                cur.execute("SET LOCAL ROLE v15_repl")
                try:
                    cur.execute(text)
                    if cur.description:
                        cur.fetchall()
                except psycopg2.Error as exc:
                    if exc.pgcode == "57014":
                        raise
                    fired["done"] = True
                    if timer is not None:
                        timer.cancel()
                    cur.execute("ROLLBACK TO SAVEPOINT model_stmt")
                    cur.execute("RESET ROLE")
                    cur.execute(
                        """
                        SELECT v15.v15_complete_statement(
                          %s, %s, %s, %s, %s, 'failed', %s
                        )
                        """,
                        (
                            invoke_id,
                            fence,
                            self.worker_id,
                            index,
                            int(info["statement_fence"]),
                            Json(error_of(exc, timeout=False)),
                        ),
                    )
                    self.conn.commit()
                    return
                fired["done"] = True
                if timer is not None:
                    timer.cancel()
                cur.execute("RESET ROLE")
                cur.execute("RELEASE SAVEPOINT model_stmt")
                cur.execute(
                    """
                    SELECT v15.v15_complete_statement(
                      %s, %s, %s, %s, %s, 'done', NULL
                    )
                    """,
                    (
                        invoke_id,
                        fence,
                        self.worker_id,
                        index,
                        int(info["statement_fence"]),
                    ),
                )
                self.conn.commit()
                return
            except psycopg2.Error as exc:
                fired["done"] = True
                if timer is not None:
                    timer.cancel()
                try:
                    self.conn.rollback()
                except psycopg2.Error:
                    pass
                if retryable_sqlstate(exc.pgcode):
                    continue
                if exc.pgcode == "57014" or fired["hit"]:
                    self._replace_conn()
                    timeout = fired["hit"] or True
                    self._fail_cancelled(invoke_id, fence, index, exc, timeout=timeout)
                    return
                raise

    def _cancel(self, pid: int, fired: dict) -> None:
        if fired["done"]:
            return
        fired["hit"] = True
        conn = connect_worker(self.db_dsn)
        try:
            conn.autocommit = True
            conn.cursor().execute("SELECT pg_cancel_backend(%s)", (pid,))
        finally:
            conn.close()

    def _fail_cancelled(self, invoke_id: str, fence: int, index: int, exc, *, timeout: bool) -> None:
        err = error_of(exc, timeout=timeout)
        self._run(
            lambda conn: self._fetch(
                conn,
                "SELECT v15.v15_fail_statement(%s, %s, %s, %s, %s)",
                (invoke_id, fence, self.worker_id, index, Json(err)),
            )
        )


def run_until_quiescent(db_dsn: str, fakellm, worker_id: str, *, lease: str = LEASE) -> None:
    worker = Worker(db_dsn, fakellm, worker_id, lease=lease)
    try:
        steps = 0
        while True:
            worker.reclaim()
            ids = worker.next_runnable()
            if not ids:
                return
            progressed = False
            for invoke_id in ids:
                fence = worker.claim(invoke_id)
                if fence is None:
                    continue
                worker.drive(invoke_id, fence)
                progressed = True
                break
            if not progressed:
                return
            steps += 1
            if steps > CAP:
                raise RuntimeError("quiescent cap")
    finally:
        worker.close()
