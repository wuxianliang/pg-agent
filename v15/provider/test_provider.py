"""Stage 10 gate: provider SQL, DeepSeek adapter, pricing, and worker wiring.

Run with credentials removed and UV_NO_ENV_FILE=1. The adapter is constructed
only with an injected transport. Default opener construction is patched.
"""
from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import uuid
import urllib.error
import urllib.request
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch
from zoneinfo import ZoneInfo

import psycopg2
from psycopg2 import sql as psql
from psycopg2.extras import Json

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
import sys

sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v15.fake_llm import FakeLLM
from v15.load import SQL_LOAD_ORDER, files_through
from v15.provider.deepseek import DeepSeekProvider, StdlibTransport, build_opener as real_build_opener
from v15.provider.errors import ProviderRejected, ProviderUncertain
from v15.provider.pricing import compute_cost, is_peak
from v15.provider.setup_db import DB, main as setup_db
from v15.provider.support import FLASH_SCOPE, open_invoke as support_open, seed_flash_profile
from v15.protocol.render_prompt import render_system
from v15.worker import Worker, run_until_quiescent
import v15.provider.deepseek as deepseek
import v15.worker as worker_mod

SH = ZoneInfo("Asia/Shanghai")
OFF_PEAK = datetime(2026, 9, 28, 13, 0, tzinfo=SH)
RETURN_SQL = 'SELECT jaz."return"(\'{"ok":true}\'::jsonb);'
URL_OPENS = {"n": 0}

SCOPE = "00000000-0000-4000-8000-0000000000b1"
OWNER = "provider-owner"


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
    return json.loads(value) if isinstance(value, str) else value


def base_messages() -> list[dict]:
    return [{
        "message_id": "seed:system",
        "role": "system",
        "kind": "system",
        "content": render_system(recursion_available=True, bindings=[]),
    }]


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
    except psycopg2.Error as exc:
        conn.rollback()
        check(label, exc.pgcode == code, f"{exc.pgcode}: {str(exc).splitlines()[0]}")
        return
    conn.rollback()
    raise AssertionError(f"{label}: expected {code}")


def open_invoke(conn, invoke_id: str, *, max_io: int = 3, pool_id: str | None = None) -> None:
    cur = conn.cursor()
    cur.execute("SET LOCAL lock_timeout = '2s'")
    cur.execute("SET LOCAL statement_timeout = '30s'")
    cur.execute(
        """
        SELECT v15.v15_open_invoke(
          %s, %s, NULL, '[]'::jsonb, %s, %s::jsonb, %s, NULL
        )
        """,
        (
            invoke_id,
            SCOPE,
            pool_id,
            json.dumps({
                "max_iterations": 10,
                "max_depth": 8,
                "max_io_attempts": max_io,
                "max_statement_ms": 30000,
            }),
            render_system(recursion_available=True, bindings=[]),
        ),
    )
    conn.commit()


def claim(worker, invoke_id: str) -> int:
    fence = call(worker, "SELECT v15.v15_claim(%s, %s, '30 seconds'::interval)", (invoke_id, OWNER))
    worker.commit()
    return fence


def begin(worker, invoke_id: str, fence: int) -> dict:
    raw = call(
        worker,
        "SELECT v15.v15_begin_llm(%s, %s, %s, %s::jsonb)",
        (invoke_id, fence, OWNER, json.dumps(base_messages())),
    )
    worker.commit()
    return parse_json(raw)


def mark(worker, attempt_id: str, invoke_fence: int) -> None:
    call(
        worker,
        "SELECT v15.v15_mark_call_started(%s, 1, %s, %s)",
        (attempt_id, invoke_fence, OWNER),
    )
    worker.commit()


def detail(cls: str, http_status=None, finish_reason=None) -> dict:
    return {
        "class": cls,
        "http_status": http_status,
        "finish_reason": finish_reason,
    }


def row(cur, query: str, args=()):
    cur.execute(query, args)
    return cur.fetchone()


def pool(cur) -> str:
    pool_id = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO v15.budget_pools (pool_id) VALUES (%s)",
        (pool_id,),
    )
    return pool_id


def inflate_reservation(cur, attempt_id: str, pool_id: str) -> None:
    cur.execute(
        """
        UPDATE v15.llm_attempts
        SET reserved_calls = 3, reserved_cost = 0.5, revision = revision + 1
        WHERE attempt_id = %s
        """,
        (attempt_id,),
    )
    cur.execute(
        """
        UPDATE v15.budget_pools
        SET calls_reserved = 3, cost_reserved = 0.5, revision = revision + 1
        WHERE pool_id = %s
        """,
        (pool_id,),
    )


def test_prefix_shape() -> None:
    govern = files_through("govern")
    provider = files_through("provider")
    check("govern prefix has nine files", len(govern) == 9)
    check("govern prefix ends at govern", govern[-1].name == "v15_govern.sql")
    check("provider load has ten files", len(provider) == 10)
    check("provider load ends at provider", provider[-1].name == "v15_provider.sql")
    check("provider is append-only", provider[:9] == govern)
    check("provider is last SQL", SQL_LOAD_ORDER[-1].name == "v15_provider.sql")


def test_sql_shape() -> None:
    source = (ROOT / "v15_provider.sql").read_text()
    check("provider SQL has no role switching", "SET ROLE" not in source and "RESET ROLE" not in source)
    check("provider SQL has no session authorization", "SESSION AUTHORIZATION" not in source)
    check("provider SQL has exact three transitions", source.count("CREATE FUNCTION v15.v15_provider_") == 3)
    check("provider SQL carries P1539 mapping", "WHEN 'V15_PROVIDER_REJECTED' THEN 'P1539'" in source)


def test_unstarted(server, admin, worker) -> None:
    iid = str(uuid.uuid4())
    open_invoke(worker, iid)
    fence = claim(worker, iid)
    opened = begin(worker, iid, fence)
    call(
        worker,
        "SELECT v15.v15_provider_reject_unstarted(%s, %s, %s, %s, %s)",
        (opened["attempt_id"], 1, fence, OWNER, "credentials_absent"),
    )
    worker.commit()
    cur = admin.cursor()
    got = row(
        cur,
        """
        SELECT a.status, a.call_started, a.calls_charged,
               r.status, i.status, i.fatal, i.error->>'code', i.error->>'sqlstate',
               i.error->>'message'
        FROM v15.llm_attempts a
        JOIN v15.llm_requests r ON r.request_id = a.request_id
        JOIN v15.invokes i ON i.invoke_id = r.invoke_id
        WHERE a.attempt_id = %s
        """,
        (opened["attempt_id"],),
    )
    check("unstarted reject shape", got == ("failed", False, False, "exhausted", "failed", False, "V15_PROVIDER_REJECTED", "P1539", ""), got)
    check("unstarted does not charge calls", row(cur, "SELECT count(*) FROM v15.llm_attempts WHERE attempt_id = %s AND calls_charged", (opened["attempt_id"],))[0] == 0)
    check("unstarted has no assistant", row(cur, "SELECT count(*) FROM v15.llm_messages WHERE invoke_id = %s AND kind = 'assistant'", (iid,))[0] == 0)
    check("unstarted has no statements", row(cur, "SELECT count(*) FROM v15.statements WHERE invoke_id = %s", (iid,))[0] == 0)
    check("unstarted scratch dropped", row(cur, "SELECT count(*) FROM pg_namespace WHERE nspname = 's_' || replace(%s::text, '-', '')", (iid,))[0] == 0)
    audit = row(
        cur,
        "SELECT payload FROM v15.invoke_events WHERE invoke_id = %s AND payload->>'op' = 'provider_rejected'",
        (iid,),
    )
    payload = parse_json(audit[0])
    check("unstarted audit classification", payload == {"op": "provider_rejected", "attempt_id": opened["attempt_id"], "class": "credentials_absent", "call_started": False}, payload)


def test_started_reject_and_validation(server, admin, worker) -> None:
    pool_id = pool(admin.cursor())
    admin.commit()
    iid = str(uuid.uuid4())
    open_invoke(worker, iid, pool_id=pool_id)
    fence = claim(worker, iid)
    opened = begin(worker, iid, fence)
    inflate_reservation(admin.cursor(), opened["attempt_id"], pool_id)
    admin.commit()
    mark(worker, opened["attempt_id"], fence)
    expect(
        worker,
        "SELECT v15.v15_provider_reject_started(%s, %s, %s, %s, %s::jsonb)",
        (opened["attempt_id"], 99, fence, OWNER, json.dumps(detail("http_status", 402))),
        "P1501",
        "started reject stale attempt fence",
    )
    expect(
        worker,
        "SELECT v15.v15_provider_reject_started(%s, %s, %s, %s, %s::jsonb)",
        (opened["attempt_id"], 1, fence, OWNER, json.dumps({"class": "http_status", "http_status": 402, "finish_reason": None, "extra": True})),
        "P1524",
        "started reject extra detail key",
    )
    cur = admin.cursor()
    check("bad detail leaves leased attempt", row(cur, "SELECT status, call_started, calls_charged FROM v15.llm_attempts WHERE attempt_id = %s", (opened["attempt_id"],)) == ("leased", True, False))
    call(
        worker,
        "SELECT v15.v15_provider_reject_started(%s, %s, %s, %s, %s::jsonb)",
        (opened["attempt_id"], 1, fence, OWNER, json.dumps(detail("http_status", 402))),
    )
    worker.commit()
    got = row(
        cur,
        """
        SELECT a.status, a.call_started, a.calls_charged, r.status,
               p.calls_used, p.calls_reserved, p.cost_used, p.cost_reserved,
               i.status, i.fatal, i.error->>'code', i.error->>'sqlstate', i.error->>'message'
        FROM v15.llm_attempts a
        JOIN v15.llm_requests r ON r.request_id = a.request_id
        JOIN v15.budget_pools p ON p.pool_id = a.pool_id
        JOIN v15.invokes i ON i.invoke_id = r.invoke_id
        WHERE a.attempt_id = %s
        """,
        (opened["attempt_id"],),
    )
    check("started reject charges stored calls only", got[:8] == ("unknown", True, True, "exhausted", 3, 0, 0, 0), got)
    check("started reject terminal", got[8:] == ("failed", False, "V15_PROVIDER_REJECTED", "P1539", ""), got)
    check("started reject no assistant", row(cur, "SELECT count(*) FROM v15.llm_messages WHERE invoke_id = %s AND kind = 'assistant'", (iid,))[0] == 0)
    audit = parse_json(row(cur, "SELECT payload FROM v15.invoke_events WHERE invoke_id = %s AND payload->>'op' = 'provider_rejected'", (iid,))[0])
    check("started reject audit keeps detail", audit["class"] == "http_status" and audit["http_status"] == 402 and audit["finish_reason"] is None and audit["call_started"] is True, audit)
    expect(
        worker,
        "SELECT v15.v15_provider_reject_started(%s, %s, %s, %s, %s::jsonb)",
        (opened["attempt_id"], 1, fence, OWNER, json.dumps(detail("http_status", 402))),
        "P1502",
        "started reject terminal attempt",
    )


def test_abandon_and_io_exhaustion(server, admin, worker) -> None:
    iid = str(uuid.uuid4())
    open_invoke(worker, iid, max_io=1)
    first_fence = claim(worker, iid)
    opened = begin(worker, iid, first_fence)
    mark(worker, opened["attempt_id"], first_fence)
    call(
        worker,
        "SELECT v15.v15_provider_abandon(%s, %s, %s, %s, %s::jsonb)",
        (opened["attempt_id"], 1, first_fence, OWNER, json.dumps(detail("http_status", 503))),
    )
    worker.commit()
    cur = admin.cursor()
    got = row(
        cur,
        """
        SELECT a.status, a.calls_charged, i.status, i.fence, i.lease_owner,
               r.status, count(*) OVER ()
        FROM v15.llm_attempts a
        JOIN v15.llm_requests r ON r.request_id = a.request_id
        JOIN v15.invokes i ON i.invoke_id = r.invoke_id
        WHERE a.attempt_id = %s
        """,
        (opened["attempt_id"],),
    )
    check("abandon leaves unknown and runnable", got[:6] == ("unknown", True, "runnable", first_fence + 1, None, "open"), got)
    check("abandon has one attempt", row(cur, "SELECT count(*) FROM v15.llm_attempts a JOIN v15.llm_requests r ON r.request_id = a.request_id WHERE r.invoke_id = %s", (iid,))[0] == 1)
    open_span = call(worker, "SELECT v15.v15_span_open(%s, 'llm_query')", (iid,))
    worker.commit()
    check("abandon keeps span open", open_span is True, open_span)
    retry = parse_json(row(cur, "SELECT payload FROM v15.invoke_events WHERE invoke_id = %s AND phase = 'retry'", (iid,))[0])
    check("abandon retry payload", retry["new_attempt_id"] is None and retry["provider"] == detail("http_status", 503), retry)
    retry_fence = claim(worker, iid)
    check("claim after abandon bumps fence once", retry_fence == first_fence + 2, retry_fence)
    exhausted = begin(worker, iid, retry_fence)
    check(
        "max io exhausts without new attempt",
        exhausted.get("action") == "abort"
        and exhausted.get("fatal") is False
        and exhausted.get("code") == "V15_IO_EXHAUSTED"
        and exhausted.get("attempt_id") is None,
        exhausted,
    )
    got = row(
        cur,
        """
        SELECT i.status, i.fatal, i.error->>'code', i.error->>'sqlstate', r.status,
               (SELECT count(*) FROM v15.llm_attempts a WHERE a.request_id = r.request_id)
        FROM v15.invokes i
        JOIN v15.llm_requests r ON r.invoke_id = i.invoke_id
        WHERE i.invoke_id = %s
        """,
        (iid,),
    )
    check("io exhausted terminal", got == ("failed", False, "V15_IO_EXHAUSTED", "P1513", "exhausted", 1), got)


def make_child_case(admin):
    parent = str(uuid.uuid4())
    child = str(uuid.uuid4())
    pscratch = "s_" + parent.replace("-", "")
    cscratch = "s_" + child.replace("-", "")
    cur = admin.cursor()
    cur.execute(psql.SQL("CREATE SCHEMA {} AUTHORIZATION v15_owner").format(psql.Identifier(pscratch)))
    cur.execute(psql.SQL("CREATE SCHEMA {} AUTHORIZATION v15_owner").format(psql.Identifier(cscratch)))
    manifest = row(cur, "SELECT v15.v15_manifest_digest(10, 8, 3, 30000)")[0]
    config = Json({"llm": {"model": "fake"}, "repl": {}, "protocol": {}, "depth": 1})
    child_config = Json({"llm": {"model": "fake"}, "repl": {}, "protocol": {}, "depth": 2})
    cur.execute(
        """
        INSERT INTO v15.invokes (
          invoke_id, root_invoke_id, depth, status, fatal, recursion_available,
          resolved_config, config_digest, manifest_digest, scratch_schema, fence,
          created_at, updated_at
        ) VALUES (%s, %s, 1, 'suspended', false, true, %s, 'parent', %s, %s, 1, clock_timestamp(), clock_timestamp())
        """,
        (parent, parent, config, manifest, pscratch),
    )
    cur.execute(
        """
        INSERT INTO v15.invokes (
          invoke_id, parent_invoke_id, parent_iteration, root_invoke_id, depth,
          status, fatal, error, recursion_available, resolved_config, config_digest,
          manifest_digest, scratch_schema, fence, lease_owner, lease_until,
          created_at, updated_at
        ) VALUES (%s, %s, 0, %s, 2, 'leased', false, NULL, true, %s, 'child', %s, %s, 2, %s, clock_timestamp() + interval '30 seconds', clock_timestamp(), clock_timestamp())
        """,
        (child, parent, parent, child_config, manifest, cscratch, OWNER),
    )
    cur.execute("INSERT INTO v15.iterations (invoke_id, iteration, status) VALUES (%s, 0, 'suspended')", (parent,))
    cur.execute("INSERT INTO v15.iterations (invoke_id, iteration, status) VALUES (%s, 0, 'llm')", (child,))
    cur.execute(
        """
        INSERT INTO v15.statements (
          invoke_id, iteration, stmt_index, sql, sql_digest, kind, bind_name,
          arg_sql, status, child_invoke_id
        ) VALUES (%s, 0, 0, %s, md5(%s), 'bind_invoke', 'kid', '{}'::text, 'running', %s)
        """,
        (parent, "SELECT jaz.bind_invoke('kid', '{}'::jsonb);", "SELECT jaz.bind_invoke('kid', '{}'::jsonb);", child),
    )
    cur.execute(
        """
        INSERT INTO v15.llm_requests (request_id, invoke_id, iteration, status, logical_digest)
        VALUES (%s, %s, 0, 'open', 'child-digest')
        """,
        (str(uuid.uuid4()), child),
    )
    request_id = row(cur, "SELECT request_id FROM v15.llm_requests WHERE invoke_id = %s", (child,))[0]
    attempt = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO v15.llm_attempts (
          attempt_id, request_id, n, status, fence, lease_owner, lease_until,
          request, call_started
        ) VALUES (%s, %s, 1, 'leased', 1, %s, clock_timestamp() + interval '30 seconds', %s, true)
        """,
        (attempt, request_id, OWNER, Json({"attempt_id": attempt, "messages": []})),
    )
    cur.execute(
        "INSERT INTO v15.invoke_events (invoke_id, seq, event_class, span, phase, payload, fence, created_at) VALUES (%s, 0, 'span', 'invoke', 'enter', '{}'::jsonb, 1, clock_timestamp())",
        (parent,),
    )
    admin.commit()
    return parent, child, attempt


def test_child_delivery(server, admin, worker) -> None:
    parent, child, attempt = make_child_case(admin)
    call(
        worker,
        "SELECT v15.v15_provider_reject_started(%s, 1, 2, %s, %s::jsonb)",
        (attempt, OWNER, json.dumps(detail("http_status", 402))),
    )
    worker.commit()
    cur = admin.cursor()
    child_row = row(cur, "SELECT status, fatal, error->>'code', error->>'sqlstate' FROM v15.invokes WHERE invoke_id = %s", (child,))
    parent_row = row(cur, "SELECT status, fatal FROM v15.invokes WHERE invoke_id = %s", (parent,))
    stmt_row = row(cur, "SELECT status, error->>'code', error->>'sqlstate' FROM v15.statements WHERE invoke_id = %s", (parent,))
    check("child keeps provider code", child_row == ("failed", False, "V15_PROVIDER_REJECTED", "P1539"), child_row)
    check("parent child delivery is nonfatal", parent_row == ("runnable", False), parent_row)
    check("parent receives child error", stmt_row == ("failed", "V15_CHILD_ERROR", "P1528"), stmt_row)


def test_acl_and_identity(server, admin, worker) -> None:
    cur = admin.cursor()
    for signature in (
        "v15.v15_provider_reject_unstarted(uuid,bigint,bigint,text,text)",
        "v15.v15_provider_reject_started(uuid,bigint,bigint,text,jsonb)",
        "v15.v15_provider_abandon(uuid,bigint,bigint,text,jsonb)",
    ):
        cur.execute("SELECT has_function_privilege('v15_worker', %s, 'EXECUTE'), has_function_privilege('v15_repl', %s, 'EXECUTE'), has_function_privilege('public', %s, 'EXECUTE')", (signature, signature, signature))
        privileges = cur.fetchone()
        check(f"ACL {signature}", privileges == (True, False, False), privileges)
    for query in (
        "SELECT v15.v15_provider_reject_unstarted(NULL, NULL, NULL, NULL, 'credentials_absent')",
        "SELECT v15.v15_provider_reject_started(NULL, NULL, NULL, NULL, '{}'::jsonb)",
        "SELECT v15.v15_provider_abandon(NULL, NULL, NULL, NULL, '{}'::jsonb)",
    ):
        worker.rollback()
        worker.cursor().execute("SET ROLE v15_repl")
        try:
            worker.cursor().execute(query)
        except psycopg2.Error as exc:
            check("repl identity denied", exc.pgcode == "42501", exc.pgcode)
        else:
            raise AssertionError("v15_repl unexpectedly executed provider transition")
        finally:
            worker.rollback()
    worker.commit()
    check("worker session identity", row(cur, "SELECT has_function_privilege('v15_worker', 'v15.v15_provider_abandon(uuid,bigint,bigint,text,jsonb)', 'EXECUTE')")[0] is True)


def install_hook(cur, key: str, body: str, invoke_id: str) -> None:
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
               d.hook_def_id, 'propagating', '{}'::jsonb, '{}'::jsonb
        FROM v15.hook_defs d
        WHERE d.hook_key = %s
        """,
        (invoke_id, invoke_id, key),
    )


def test_hook_normalizes_provider_code(server, admin, worker) -> None:
    iid = str(uuid.uuid4())
    open_invoke(worker, iid)
    hook = connect(server)
    hook.autocommit = True
    try:
        install_hook(
            hook.cursor(),
            "p1539_norm",
            """
            BEGIN
              IF p_snapshot->>'phase' = 'exit' THEN
                RETURN jsonb_build_object('contract', 1, 'action', 'proceed');
              END IF;
              RETURN jsonb_build_object(
                'contract', 1, 'action', 'abort', 'fatal', false,
                'error', jsonb_build_object(
                  'code', 'V15_PROVIDER_REJECTED', 'message', 'x'
                )
              );
            END
            """,
            iid,
        )
    finally:
        hook.close()
    fence = claim(worker, iid)
    opened = begin(worker, iid, fence)
    check(
        "provider code normalizes to hook abort",
        opened.get("action") == "abort"
        and opened.get("code") == "V15_HOOK_ABORT"
        and opened.get("fatal") is False,
        opened,
    )
    got = row(
        admin.cursor(),
        """
        SELECT status, fatal, error->>'code', error->>'sqlstate', error->>'message'
        FROM v15.invokes WHERE invoke_id = %s
        """,
        (iid,),
    )
    check(
        "normalized abort is committed",
        got == ("failed", False, "V15_HOOK_ABORT", "P1538", ""),
        got,
    )


def test_keyless_skeleton() -> None:
    for key in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "OPENAI_API_URI", "OPENAI_MODEL"):
        check(f"keyless skeleton pops {key}", key not in os.environ)
    import urllib.request
    try:
        urllib.request.urlopen("https://example.invalid")
    except AssertionError as exc:
        check("keyless skeleton patches urlopen", str(exc) == "network")
    else:
        raise AssertionError("urlopen was not blocked")


def shanghai(day: int, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 9, day, hour, minute, second, tzinfo=SH)


def test_pricing() -> None:
    monday_peak = shanghai(28, 10)
    monday_off = shanghai(28, 13)
    check("monday 09:00 peak", is_peak(shanghai(28, 9)) is True)
    check("monday 08:59 off", is_peak(shanghai(28, 8, 59)) is False)
    check("monday 10:00 peak", is_peak(monday_peak) is True)
    check("monday 11:59 peak", is_peak(shanghai(28, 11, 59)) is True)
    check("monday 12:00 off", is_peak(shanghai(28, 12)) is False)
    check("monday 13:00 off", is_peak(monday_off) is False)
    check("monday 14:00 peak", is_peak(shanghai(28, 14)) is True)
    check("monday 17:59 peak", is_peak(shanghai(28, 17, 59)) is True)
    check("monday 18:00 off", is_peak(shanghai(28, 18)) is False)
    check("saturday 10:00 off", is_peak(datetime(2026, 10, 3, 10, 0, tzinfo=SH)) is False)
    utc_peak = datetime(2026, 9, 28, 2, 0, tzinfo=ZoneInfo("UTC"))
    check("utc monday 02:00 is shanghai peak", is_peak(utc_peak) is True)
    check(
        "off-peak miss exact",
        compute_cost("deepseek-flash", prompt_cache_miss_tokens=1_000_000, prompt_cache_hit_tokens=0, completion_tokens=0, at=monday_off) == Decimal("0.15"),
    )
    check(
        "off-peak hit exact",
        compute_cost("deepseek-flash", prompt_cache_miss_tokens=0, prompt_cache_hit_tokens=1_000_000, completion_tokens=0, at=monday_off) == Decimal("0.003"),
    )
    check(
        "off-peak output exact",
        compute_cost("deepseek-flash", prompt_cache_miss_tokens=0, prompt_cache_hit_tokens=0, completion_tokens=1_000_000, at=monday_off) == Decimal("0.60"),
    )
    check(
        "peak miss exact",
        compute_cost("deepseek-flash", prompt_cache_miss_tokens=1_000_000, prompt_cache_hit_tokens=0, completion_tokens=0, at=monday_peak) == Decimal("0.30"),
    )
    check(
        "zero tokens are zero",
        compute_cost("deepseek-flash", prompt_cache_miss_tokens=0, prompt_cache_hit_tokens=0, completion_tokens=0, at=monday_off) == Decimal("0"),
    )
    check("pro unpriced", compute_cost("deepseek-v4-pro", prompt_cache_miss_tokens=1, prompt_cache_hit_tokens=0, completion_tokens=0, at=monday_off) is None)
    check("unknown unpriced", compute_cost("other", prompt_cache_miss_tokens=1, prompt_cache_hit_tokens=0, completion_tokens=0, at=monday_off) is None)
    check("naive unpriced", compute_cost("deepseek-flash", prompt_cache_miss_tokens=1, prompt_cache_hit_tokens=0, completion_tokens=0, at=datetime(2026, 9, 28, 13, 0)) is None)


def test_credentials_and_import() -> None:
    src = Path(deepseek.__file__).read_text()
    visitor = _EnvVisitor()
    visitor.visit(ast.parse(src))
    check("import does not read env", not visitor.bad)
    os.environ["DEEPSEEK_API_KEY"] = "deep-key"
    os.environ["OPENAI_API_KEY"] = "openai-key"
    os.environ["OPENAI_API_URI"] = "https://env.example/v1/"
    try:
        explicit = DeepSeekProvider(api_key="explicit-key", base_url="https://explicit.example/v1/")
        check("explicit key wins", explicit.api_key == "explicit-key")
        check("explicit base wins", explicit.base_url == "https://explicit.example/v1")
        from_deep = DeepSeekProvider()
        check("deepseek key beats openai", from_deep.api_key == "deep-key")
        check("env base used", from_deep.base_url == "https://env.example/v1")
        os.environ.pop("DEEPSEEK_API_KEY")
        from_openai = DeepSeekProvider()
        check("openai key fallback", from_openai.api_key == "openai-key")
        os.environ.pop("OPENAI_API_KEY")
        os.environ.pop("OPENAI_API_URI")
        absent = DeepSeekProvider()
        check("missing key is empty", absent.api_key == "")
        check("default base", absent.base_url == "https://api.deepseek.com/v1")
        check("absent preflight", absent.preflight({"model": "deepseek-flash"})["class"] == "credentials_absent")
    finally:
        for key in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "OPENAI_API_URI", "OPENAI_MODEL"):
            os.environ.pop(key, None)


class _EnvVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.fn = 0
        self.bad = False

    def visit_FunctionDef(self, node):
        self.fn += 1
        self.generic_visit(node)
        self.fn -= 1

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Attribute(self, node):
        if self.fn == 0 and isinstance(node.value, ast.Name) and node.value.id == "os" and node.attr == "environ":
            self.bad = True
        self.generic_visit(node)


class ScriptTransport:
    def __init__(self, items) -> None:
        self.items = list(items)
        self.calls = []

    def post(self, url, body, headers, deadline):
        self.calls.append((url, body, headers, deadline))
        item = self.items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def off_peak():
    return OFF_PEAK


def flash_provider(transport, clock=None, **kwargs):
    kwargs.setdefault("api_key", "test-key")
    kwargs.setdefault("base_url", "https://api.deepseek.com/v1")
    return DeepSeekProvider(transport=transport, clock=clock or off_peak, **kwargs)


def ok_body(content="", *, miss=0, hit=0, completion=0, model="deepseek-flash", finish="stop", reasoning=None, ident="chatcmpl_test"):
    message = {"role": "assistant", "content": content}
    if reasoning is not None:
        message["reasoning_content"] = reasoning
    return json.dumps({
        "id": ident,
        "model": model,
        "choices": [{"finish_reason": finish, "message": message}],
        "usage": {
            "prompt_tokens": hit + miss,
            "completion_tokens": completion,
            "prompt_cache_hit_tokens": hit,
            "prompt_cache_miss_tokens": miss,
        },
    }).encode()


def drive_complete(status, raw, *, clock=None, llm=None, messages=None, raise_instead=None):
    item = raise_instead if raise_instead is not None else (status, raw)
    transport = ScriptTransport([item])
    provider = flash_provider(transport, clock=clock)
    if messages is None:
        messages = [{"role": "user", "content": "hi", "message_id": "m", "kind": "input", "seq": 1}]
    if llm is None:
        llm = {"model": "deepseek-flash", "temperature": 0.2}
    try:
        result = provider.complete("digest", 1, {"messages": messages}, llm)
    except Exception as exc:
        return transport, exc
    return transport, result


def test_preflight() -> None:
    bare = DeepSeekProvider(transport=ScriptTransport([]))
    check("no key ignores model", bare.preflight(None)["class"] == "credentials_absent")
    keyed = DeepSeekProvider(api_key="k", base_url="https://api.deepseek.com/v1", transport=ScriptTransport([]))
    check("missing model", keyed.preflight({})["class"] == "model_missing")
    check("blank model", keyed.preflight({"model": ""})["class"] == "model_missing")
    for name in ("fake", "deepseek-chat", "deepseek-reasoner", "deepseek-v4-pro"):
        check(f"{name} not allowlisted", keyed.preflight({"model": name})["class"] == "model_not_allowlisted")
    http = DeepSeekProvider(api_key="k", base_url="http://api.deepseek.com/v1", transport=ScriptTransport([]))
    check("http endpoint rejected", http.preflight({"model": "deepseek-flash"})["class"] == "endpoint_rejected")
    check("flash preflight passes", keyed.preflight({"model": "deepseek-flash"}) is None)
    try:
        DeepSeekProvider(api_key="k", timeout_s=600)
    except ValueError:
        check("timeout ceiling rejected", True)
    else:
        raise AssertionError("timeout 600 accepted")
    try:
        Worker("dbname=unused", keyed, "w", lease="30 seconds")
    except ValueError:
        check("short lease rejected before connect", True)
    else:
        raise AssertionError("short lease accepted")


def test_wire_and_http() -> None:
    transport = ScriptTransport([(200, ok_body("SELECT 1;"))])
    provider = flash_provider(transport)
    messages = [
        {"role": "system", "content": "sys", "message_id": "s", "kind": "system", "seq": 0},
        {"role": "user", "content": "usr", "message_id": "u", "kind": "input", "seq": 1},
    ]
    provider.complete(
        "digest", 1, {"messages": messages},
        {"model": "deepseek-flash", "temperature": 0.1, "top_p": 1, "max_output_tokens": 10.0},
    )
    body = json.loads(transport.calls[0][1])
    check("wire keys", set(body) == {"model", "messages", "stream", "max_tokens"}, body)
    check("stream false", body["stream"] is False)
    check("max_tokens int", body["max_tokens"] == 10 and type(body["max_tokens"]) is int)
    check("message order", body["messages"] == [{"role": "system", "content": "sys"}, {"role": "user", "content": "usr"}])
    check("no temperature", "temperature" not in body and "top_p" not in body and "thinking" not in body)
    bool_transport = ScriptTransport([(200, ok_body(""))])
    flash_provider(bool_transport).complete(
        "d", 1, {"messages": [{"role": "user", "content": "hi"}]}, {"model": "deepseek-flash", "max_output_tokens": True},
    )
    check("bool max tokens dropped", "max_tokens" not in json.loads(bool_transport.calls[0][1]))
    _, bad_role = drive_complete(200, b"{}", messages=[{"role": "tool", "content": "x"}])
    check("bad role rejected", isinstance(bad_role, ProviderRejected) and bad_role.detail["class"] == "request_invalid")
    try:
        flash_provider(ScriptTransport([])).complete("d", 1, {"messages": []}, None)
    except ProviderRejected as exc:
        check("missing llm_config rejected", exc.detail["class"] == "request_invalid" and str(exc) == "ProviderRejected")
    else:
        raise AssertionError("missing llm_config returned")
    for status in (402, 401, 422, 404, 403, 400, 499):
        raw = b"<html>not-json</html>" if status != 400 else b'{"error":{"message":"invalid"}}'
        _, got = drive_complete(status, raw)
        check(
            f"{status} reject",
            isinstance(got, ProviderRejected) and got.detail == {"class": "http_status", "http_status": status, "finish_reason": None},
            getattr(got, "detail", got),
        )
    transient = json.dumps({"error": {"message": "Could not parse the JSON body"}}).encode()
    _, got = drive_complete(400, transient)
    check("transient 400 abandon", isinstance(got, ProviderUncertain) and got.detail == {"class": "transport", "http_status": 400, "finish_reason": None}, getattr(got, "detail", got))
    for status in (429, 503):
        _, got = drive_complete(status, b"busy")
        check(f"{status} abandon", isinstance(got, ProviderUncertain) and got.detail == {"class": "http_status", "http_status": status, "finish_reason": None})
    _, got = drive_complete(0, b"", raise_instead=TimeoutError("slow"))
    check("timeout abandon", isinstance(got, ProviderUncertain) and got.detail["class"] == "transport" and "slow" not in str(got))
    _, got = drive_complete(0, b"", raise_instead=urllib.error.URLError("sk-live-secret"))
    check("urlerror abandon", isinstance(got, ProviderUncertain) and str(got) == "ProviderUncertain" and "sk-live-secret" not in str(got))
    _, got = drive_complete(200, ok_body("LEAKED-CONTENT", finish="content_filter"))
    check("content_filter reject", isinstance(got, ProviderRejected) and got.detail["finish_reason"] == "content_filter" and "LEAKED-CONTENT" not in str(got))
    _, got = drive_complete(200, ok_body("x", finish="insufficient_system_resource"))
    check("resource abandon", isinstance(got, ProviderUncertain) and got.detail["finish_reason"] == "insufficient_system_resource")
    _, got = drive_complete(200, ok_body("x", finish="aborted"))
    check("aborted abandon", isinstance(got, ProviderUncertain) and got.detail["finish_reason"] == "aborted")
    _, got = drive_complete(200, b'{"choices":"nope"}')
    check("malformed abandon", isinstance(got, ProviderUncertain) and got.detail["finish_reason"] == "other")
    _, got = drive_complete(201, b"{}")
    check("non-200 2xx abandon", isinstance(got, ProviderUncertain) and got.detail == {"class": "finish_reason", "http_status": None, "finish_reason": "other"})
    _, got = drive_complete(302, b"")
    check("3xx abandon", isinstance(got, ProviderUncertain) and got.detail == {"class": "transport", "http_status": 302, "finish_reason": None})
    _, got = drive_complete(200, ok_body("x", model="deepseek-v4-pro"))
    check("model mismatch reject", isinstance(got, ProviderRejected) and got.detail["finish_reason"] == "model_mismatch")
    _, got = drive_complete(200, ok_body(""))
    check("empty content settles", isinstance(got, dict) and got["content"] == "" and got["cost_usd"] == Decimal("0") and got["prompt_tokens"] == 0)
    _, got = drive_complete(200, ok_body("SELECT 1;", finish="length"))
    check("length settles", isinstance(got, dict) and got["content"] == "SELECT 1;")
    _, got = drive_complete(200, ok_body("SELECT 1;", reasoning="secret-thought"))
    check("reasoning dropped", isinstance(got, dict) and got["content"] == "SELECT 1;" and "secret-thought" not in json.dumps(got["provider"]) and got["provider"]["reasoning_chars"] == len("secret-thought"))
    mismatch = {"model": "deepseek-flash", "choices": [{"message": {"content": "x"}}], "usage": {"prompt_tokens": 3, "completion_tokens": 0, "prompt_cache_hit_tokens": 1, "prompt_cache_miss_tokens": 1}}
    _, got = drive_complete(200, json.dumps(mismatch).encode())
    check("usage mismatch abandon", isinstance(got, ProviderUncertain) and got.detail["class"] == "usage_invalid")
    _, got = drive_complete(200, json.dumps({"model": "deepseek-flash", "choices": [{"message": {"content": "x"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 0, "prompt_cache_miss_tokens": 1}}).encode())
    check("missing hit abandon", isinstance(got, ProviderUncertain) and got.detail["class"] == "usage_invalid")
    huge = {"model": "deepseek-flash", "choices": [{"message": {"content": "x"}}], "usage": {"prompt_tokens": 2147483648, "completion_tokens": 0, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 2147483648}}
    _, got = drive_complete(200, json.dumps(huge).encode())
    check("int4 abandon", isinstance(got, ProviderUncertain) and got.detail["class"] == "usage_invalid")
    flagged = {"model": "deepseek-flash", "choices": [{"message": {"content": "x"}}], "usage": {"prompt_tokens": True, "completion_tokens": 0, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 0}}
    _, got = drive_complete(200, json.dumps(flagged).encode())
    check("bool usage abandon", isinstance(got, ProviderUncertain) and got.detail["class"] == "usage_invalid")
    _, got = drive_complete(200, ok_body("x", miss=1), clock=lambda: datetime(2026, 9, 28, 13, 0))
    check("unpriced abandon", isinstance(got, ProviderUncertain) and got.detail["class"] == "unpriced")
    _, got = drive_complete(200, ok_body("stop", finish="stop\x00\n", ident="ab\x00c\n"))
    check("metadata nul sanitized", isinstance(got, dict) and got["provider"]["finish_reason"] == "stop\\u0000" and "\x00" not in got["provider"]["finish_reason"] and "id" not in got["provider"])


class _Clock:
    def __init__(self, now=0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class _Resp:
    def __init__(self, chunks, clock, step=0.0, status=200) -> None:
        self.chunks = list(chunks)
        self.clock = clock
        self.step = step
        self.status = status
        self.closed = False
        self.reads = []

    def read(self, n):
        self.reads.append(n)
        self.clock.now += self.step
        if not self.chunks:
            return b""
        return self.chunks.pop(0)

    def close(self) -> None:
        self.closed = True

    def getcode(self):
        return self.status


class _Opener:
    def __init__(self, resp, clock=None, advance=0.0) -> None:
        self.resp = resp
        self.clock = clock
        self.advance = advance
        self.calls = 0

    def open(self, request, timeout=None):
        self.calls += 1
        if self.clock is not None:
            self.clock.now += self.advance
        return self.resp


def _post(clock, opener, deadline):
    transport = StdlibTransport(monotonic=clock, opener_factory=lambda: opener)
    return transport.post("https://api.deepseek.com/v1/chat/completions", b"{}", {}, deadline)


def test_transport_edges() -> None:
    opener = real_build_opener()
    check("empty proxy handler", opener.v15_proxy.proxies == {})
    check("redirect does not follow", type(opener.v15_redirect).__name__ == "_NoRedirect")
    check("default redirector absent", not any(type(h) is urllib.request.HTTPRedirectHandler for h in opener.handlers))
    start = URL_OPENS["n"]
    boundary = DeepSeekProvider(api_key="k", base_url="https://api.deepseek.com/v1", clock=off_peak)
    try:
        boundary.complete("d", 1, {"messages": [{"role": "user", "content": "hi"}]}, {"model": "deepseek-flash"})
    except AssertionError as exc:
        check("boundary is opener", str(exc) == "transport-boundary", str(exc))
    else:
        raise AssertionError("boundary patch did not fire")
    check("boundary skipped urlopen", URL_OPENS["n"] == start)
    clock = _Clock(10)
    opener = _Opener(_Resp([b"x"], clock))
    try:
        _post(clock, opener, 5)
    except ProviderUncertain as exc:
        check("pre-http abandon", exc.detail["class"] == "transport" and opener.calls == 0)
    else:
        raise AssertionError("pre-http returned")
    clock = _Clock(0)
    resp = _Resp([b"hdr"], clock)
    opener = _Opener(resp, clock, advance=8)
    try:
        _post(clock, opener, 5)
    except ProviderUncertain:
        check("delayed headers closed", resp.closed and resp.reads == [])
    else:
        raise AssertionError("delayed headers returned")
    clock = _Clock(0)
    resp = _Resp([b"a", b"b"], clock, step=3)
    try:
        _post(clock, _Opener(resp), 5)
    except ProviderUncertain:
        check("drip closed", resp.closed and resp.reads != [])
    else:
        raise AssertionError("drip returned")
    clock = _Clock(0)
    resp = _Resp([b"late"], clock, step=10)
    try:
        _post(clock, _Opener(resp), 5)
    except ProviderUncertain:
        check("late body closed", resp.closed)
    else:
        raise AssertionError("late body returned")
    clock = _Clock(0)
    resp = _Resp([b"ok"], clock)
    status, raw = _post(clock, _Opener(resp), 100)
    check("within deadline", status == 200 and raw == b"ok" and resp.closed and resp.reads[0] == 65536, (status, raw, resp.closed, resp.reads))
    clock = _Clock(0)
    resp = _Resp([b"x" * (10 * 1024 * 1024 + 1)], clock)
    try:
        _post(clock, _Opener(resp), 100)
    except ProviderUncertain:
        check("byte cap closed", resp.closed)
    else:
        raise AssertionError("oversize body returned")


def _open_worker(server, invoke_id, **kwargs):
    conn = connect(server, "v15_worker")
    try:
        if "scope_id" in kwargs:
            support_open(conn, invoke_id, **kwargs)
        else:
            open_invoke(conn, invoke_id, max_io=kwargs.get("max_io", 3), pool_id=kwargs.get("pool_id"))
    finally:
        conn.close()


def _attempt(cur, invoke_id):
    return row(
        cur,
        """
        SELECT a.status, a.call_started, a.n, a.cost_usd, a.prompt_tokens, a.response->>'content'
        FROM v15.llm_attempts a
        JOIN v15.llm_requests r ON r.request_id = a.request_id
        WHERE r.invoke_id = %s
        ORDER BY a.n
        """,
        (invoke_id,),
    )


def _run_one(server, admin, provider, invoke_id, lease="30 seconds") -> None:
    admin.cursor().execute(
        "UPDATE v15.invokes SET status = 'suspended' WHERE status = 'runnable' AND invoke_id <> %s",
        (invoke_id,),
    )
    admin.commit()
    run_until_quiescent(server.get_uri(DB), provider, OWNER, lease=lease)


def test_worker_paths(server, admin) -> None:
    seed_flash_profile(admin.cursor())
    admin.commit()
    iid = str(uuid.uuid4())
    _open_worker(server, iid)

    class Recorder(FakeLLM):
        def complete(self, logical_digest, n, request, llm_config=None):
            self.seen = llm_config
            return {"content": RETURN_SQL, "prompt_tokens": 1, "cost_usd": 0}

    recorder = Recorder()
    _run_one(server, admin, recorder, iid)
    cur = admin.cursor()
    check("fake return completed", row(cur, "SELECT status FROM v15.invokes WHERE invoke_id = %s", (iid,)) == ("completed",))
    check("worker passed llm", recorder.seen["model"] == "fake", recorder.seen)
    nul = str(uuid.uuid4())
    _open_worker(server, nul)

    class NulLLM:
        def complete(self, logical_digest, n, request, llm_config=None):
            return {"content": "has\x00nul", "prompt_tokens": 1, "cost_usd": 0}

    _run_one(server, admin, NulLLM(), nul)
    stored = row(
        cur,
        """
        SELECT a.status, a.response->>'content', s.status, s.error->>'code', s.sql
        FROM v15.llm_attempts a
        JOIN v15.llm_requests r ON r.request_id = a.request_id
        JOIN v15.statements s ON s.invoke_id = r.invoke_id
        WHERE r.invoke_id = %s
        """,
        (nul,),
    )
    check("nul settled", stored[0] == "settled" and "\\u0000" in stored[1] and "\x00" not in stored[1], stored)
    check("nul statement", stored[2:] == ("failed", "V15_VALUE_INVALID", stored[1]) and "\x00" not in stored[4], stored)
    raised = False
    keyless_id = str(uuid.uuid4())
    _open_worker(server, keyless_id)
    try:
        _run_one(server, admin, FakeLLM(), keyless_id)
    except KeyError:
        raised = True
    check("keyerror propagates", raised)
    check("keyerror not settled", row(cur, "SELECT a.status, a.call_started FROM v15.llm_attempts a JOIN v15.llm_requests r ON r.request_id = a.request_id WHERE r.invoke_id = %s", (keyless_id,)) == ("leased", True))
    absent = str(uuid.uuid4())
    _open_worker(server, absent)
    _run_one(server, admin, DeepSeekProvider(transport=ScriptTransport([])), absent, lease="300 seconds")
    check(
        "unstarted credentials",
        row(cur, "SELECT a.status, a.call_started, i.error->>'code' FROM v15.llm_attempts a JOIN v15.llm_requests r ON r.request_id = a.request_id JOIN v15.invokes i ON i.invoke_id = r.invoke_id WHERE r.invoke_id = %s", (absent,)) == ("failed", False, "V15_PROVIDER_REJECTED"),
    )
    pool_id = pool(cur)
    admin.commit()
    priced = str(uuid.uuid4())
    transport = ScriptTransport([(200, ok_body(RETURN_SQL, miss=1_000_000))])
    _open_worker(server, priced, scope_id=FLASH_SCOPE, pool_id=pool_id)
    _run_one(server, admin, flash_provider(transport), priced, lease="300 seconds")
    cost = row(cur, "SELECT a.cost_usd, a.prompt_tokens, p.cost_used FROM v15.llm_attempts a JOIN v15.llm_requests r ON r.request_id = a.request_id JOIN v15.budget_pools p ON p.pool_id = a.pool_id WHERE r.invoke_id = %s", (priced,))
    check("decimal settle", cost == (Decimal("0.15"), 1000000, Decimal("0.15")), cost)
    check("priced completed", row(cur, "SELECT status FROM v15.invokes WHERE invoke_id = %s", (priced,)) == ("completed",))
    rejected = str(uuid.uuid4())
    reject_transport = ScriptTransport([(402, b"<html>pay</html>")])
    pool_reject = pool(cur)
    admin.commit()
    _open_worker(server, rejected, scope_id=FLASH_SCOPE, pool_id=pool_reject)
    _run_one(server, admin, flash_provider(reject_transport), rejected, lease="300 seconds")
    _run_one(server, admin, flash_provider(reject_transport), rejected, lease="300 seconds")
    check("402 called once", len(reject_transport.calls) == 1, len(reject_transport.calls))
    check(
        "402 terminal",
        row(cur, "SELECT i.error->>'code', p.calls_used, p.cost_used FROM v15.invokes i JOIN v15.budget_pools p ON p.pool_id = %s WHERE i.invoke_id = %s", (pool_reject, rejected)) == ("V15_PROVIDER_REJECTED", 1, Decimal("0")),
    )
    mismatch = str(uuid.uuid4())
    mismatch_transport = ScriptTransport([(200, ok_body("LEAK", model="deepseek-v4-pro"))])
    _open_worker(server, mismatch, scope_id=FLASH_SCOPE)
    _run_one(server, admin, flash_provider(mismatch_transport), mismatch, lease="300 seconds")
    check("mismatch committed", row(cur, "SELECT error->>'code' FROM v15.invokes WHERE invoke_id = %s", (mismatch,)) == ("V15_PROVIDER_REJECTED",))
    check("mismatch no assistant", row(cur, "SELECT count(*) FROM v15.llm_messages WHERE invoke_id = %s AND kind = 'assistant'", (mismatch,))[0] == 0)
    exhausted = str(uuid.uuid4())
    once = ScriptTransport([(503, b"down")])
    _open_worker(server, exhausted, scope_id=FLASH_SCOPE, max_io=1)
    _run_one(server, admin, flash_provider(once), exhausted, lease="300 seconds")
    check("max io one call", len(once.calls) == 1)
    check("max io exhausted", row(cur, "SELECT error->>'code', (SELECT count(*) FROM v15.llm_attempts a JOIN v15.llm_requests r ON r.request_id = a.request_id WHERE r.invoke_id = i.invoke_id) FROM v15.invokes i WHERE invoke_id = %s", (exhausted,)) == ("V15_IO_EXHAUSTED", 1))
    retry = str(uuid.uuid4())
    retry_pool = pool(cur)
    admin.commit()
    retry_transport = ScriptTransport([(429, b"slow"), (200, ok_body(RETURN_SQL, miss=1_000_000))])
    slept = []
    real_sleep = worker_mod._sleep
    worker_mod._sleep = lambda seconds: slept.append(seconds)
    try:
        _open_worker(server, retry, scope_id=FLASH_SCOPE, pool_id=retry_pool, max_io=3)
        _run_one(server, admin, flash_provider(retry_transport), retry, lease="300 seconds")
    finally:
        worker_mod._sleep = real_sleep
    check("429 slept one second", slept == [1], slept)
    costs = row(cur, "SELECT p.calls_used, p.cost_used FROM v15.budget_pools p WHERE p.pool_id = %s", (retry_pool,))
    check("retry cost is second only", costs == (2, Decimal("0.15")), costs)
    check("second settled", row(cur, "SELECT a.n, a.status FROM v15.llm_attempts a JOIN v15.llm_requests r ON r.request_id = a.request_id WHERE r.invoke_id = %s AND a.n = 2", (retry,)) == (2, "settled"))


def test_smoke_exits() -> None:
    import v15.provider.smoke as smoke

    for key in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "OPENAI_API_URI", "OPENAI_MODEL"):
        check(f"smoke env has no {key}", key not in os.environ)
    out = io.StringIO()
    err = io.StringIO()
    code = None
    with patch.object(deepseek.DeepSeekProvider, "__init__", side_effect=AssertionError) as init, \
            patch.object(deepseek.DeepSeekProvider, "complete", side_effect=AssertionError) as complete, \
            patch.object(deepseek, "build_opener", side_effect=AssertionError) as boundary, \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = smoke.main([])
        except AssertionError:
            code = "raised"
    check("smoke no flag exits 0", code == 0, code)
    check("smoke no flag does not construct", init.call_count == 0, init.call_count)
    check("smoke no flag does not complete", complete.call_count == 0, complete.call_count)
    check("smoke no flag does not open", boundary.call_count == 0, boundary.call_count)
    check("smoke no flag text", out.getvalue() == "not_requested\n")
    check("smoke no flag stderr", err.getvalue() == "")
    before = URL_OPENS["n"]
    out = io.StringIO()
    err = io.StringIO()
    code = None
    with patch.object(deepseek.DeepSeekProvider, "complete", side_effect=AssertionError) as complete, \
            patch.object(deepseek, "build_opener", side_effect=AssertionError) as boundary, \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = smoke.main(["--real-provider-smoke"])
        except AssertionError:
            code = "raised"
    check("smoke boundary side_effect", boundary.side_effect is AssertionError)
    check("smoke no key exits 2", code == 2, code)
    check("smoke no key does not complete", complete.call_count == 0, complete.call_count)
    check("smoke no key boundary not crossed", boundary.call_count == 0, boundary.call_count)
    check("smoke no key text", out.getvalue() == "credentials_absent\n")
    check("smoke no key stderr", err.getvalue() == "")
    check("smoke no key did not urlopen", URL_OPENS["n"] == before, URL_OPENS["n"])


def run_tests() -> None:
    test_prefix_shape()
    test_sql_shape()
    test_keyless_skeleton()
    before = URL_OPENS["n"]
    test_pricing()
    test_credentials_and_import()
    test_preflight()
    test_wire_and_http()
    test_transport_edges()
    test_smoke_exits()
    check("adapter did not call urlopen", URL_OPENS["n"] == before, URL_OPENS["n"])
    setup_db()
    server = get_server()
    admin = connect(server)
    worker = connect(server, "v15_worker")
    try:
        admin.autocommit = False
        worker.autocommit = False
        test_unstarted(server, admin, worker)
        test_started_reject_and_validation(server, admin, worker)
        test_abandon_and_io_exhaustion(server, admin, worker)
        test_child_delivery(server, admin, worker)
        test_hook_normalizes_provider_code(server, admin, worker)
        test_acl_and_identity(server, admin, worker)
        test_worker_paths(server, admin)
        check("worker paths did not call urlopen", URL_OPENS["n"] == before)
    finally:
        worker.close()
        admin.close()


def main() -> int:
    os.environ.pop("DEEPSEEK_API_KEY", None)
    os.environ.pop("OPENAI_API_KEY", None)
    os.environ.pop("OPENAI_API_URI", None)
    os.environ.pop("OPENAI_MODEL", None)
    import urllib.request

    original_urlopen = urllib.request.urlopen

    def blocked_urlopen(*args, **kwargs):
        URL_OPENS["n"] += 1
        raise AssertionError("network")

    urllib.request.urlopen = blocked_urlopen
    original_opener = deepseek.build_opener
    deepseek.build_opener = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("transport-boundary"))
    try:
        run_tests()
    finally:
        urllib.request.urlopen = original_urlopen
        deepseek.build_opener = original_opener
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
