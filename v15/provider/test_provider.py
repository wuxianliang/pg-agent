"""Stage 10 gate: provider rejection and abandon SQL transitions.

Run with credentials removed and UV_NO_ENV_FILE=1. This M1 gate uses only
injected SQL state; it does not construct a real provider or open a socket.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import psycopg2
from psycopg2 import sql as psql
from psycopg2.extras import Json

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
import sys

sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v15.load import SQL_LOAD_ORDER, files_through
from v15.provider.setup_db import DB, main as setup_db
from v15.protocol.render_prompt import render_system

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


def run_tests() -> None:
    test_prefix_shape()
    test_sql_shape()
    test_keyless_skeleton()
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
    urllib.request.urlopen = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network"))
    try:
        run_tests()
    finally:
        urllib.request.urlopen = original_urlopen
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
