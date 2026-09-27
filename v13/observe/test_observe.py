"""Stage 24 gate: authorized observe and session log.

Run: uv run python v13/observe/test_observe.py  (exit 0 = pass)
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v13.load import SQL_LOAD_ORDER, STAGE_THROUGH
from v13.observe.setup_db import DB, apply_observe, prepare

N = 0
OBS_DUP = "v13: observe duplicate"
OBS_ID = "v13: observe id"
LOG_CURSOR = "v13: session log cursor"
OBS_COLS = (
    "ordinal", "session_id", "parent_session_id", "status", "spawn_kind",
    "is_terminal", "turn_no", "last_event_seq", "last_event_type",
    "pending_human", "cancel_pending",
)
LOG_COLS = (
    "seq", "event_id", "type", "turn_no", "payload", "payload_hash",
    "source_effect_id", "at",
)
STAGE23 = (
    "v13_control_operator()",
    "v13_control_authorized(uuid,uuid)",
    "v13_cancel(uuid,uuid)",
    "v13_complete(uuid,uuid,integer,bigint,text,jsonb)",
    "v13_cancel(uuid)",
    "v13_complete(uuid,integer,bigint,text,jsonb)",
)
STAGE25 = (
    "v13_extract_handoff(uuid,uuid,bigint)",
    "v13_transcript_hash(uuid,bigint)",
    "v13_handoff_emit(uuid,jsonb)",
    "v13_handoff_event_guard()",
)


def check(label: str, condition: bool, detail: object = "") -> None:
    global N
    N += 1
    mark = "PASS" if condition else "FAIL"
    extra = f": {detail}" if detail != "" and (not condition or len(str(detail)) < 220) else ""
    print(f"[{mark}] {label}{extra}")
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def u() -> str:
    return str(uuid.uuid4())


def connect(server, db=DB):
    conn = psycopg2.connect(server.get_uri(db))
    conn.autocommit = False
    return conn


def raise_msg(cur, sql, params):
    cur.execute("SAVEPOINT sp")
    try:
        cur.execute(sql, params)
        cur.fetchall()
    except psycopg2.Error as exc:
        msg = exc.diag.message_primary
        cur.execute("ROLLBACK TO SAVEPOINT sp")
        return msg, exc.pgcode
    cur.execute("ROLLBACK TO SAVEPOINT sp")
    raise AssertionError(f"expected failure: {sql}")


def fails_exact(cur, sql, params, needle, label):
    msg, _code = raise_msg(cur, sql, params)
    check(label, msg == needle, msg)
    return msg


def fails_code(cur, sql, params, code, label):
    msg, got = raise_msg(cur, sql, params)
    check(label, got == code, (got, msg))
    return msg


def q1(cur, sql, params=None):
    cur.execute(sql, params)
    return cur.fetchone()[0]


def open_session(cur):
    cur.execute("SELECT v13_open_session('{}'::jsonb)")
    return str(cur.fetchone()[0])


def prefix(cur, sid, text="hello"):
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (sid, u(), json.dumps({"text": text})))
    return cur.fetchone()[0]


def insert_child(cur, parent, spawn_kind=None):
    sid = u()
    cur.execute("SET LOCAL ROLE v13_spawn_owner")
    if spawn_kind is None:
        cur.execute(
            "INSERT INTO sessions (session_id, parent_session_id) VALUES (%s, %s)",
            (sid, parent))
    else:
        cur.execute(
            "INSERT INTO sessions (session_id, parent_session_id, spawn_kind) "
            "VALUES (%s, %s, %s)",
            (sid, parent, spawn_kind))
    cur.execute("RESET ROLE")
    return sid


def enqueue_human(cur, sid, ref):
    cur.execute(
        "SELECT v13_enqueue_effect(%s, 'human', %s::jsonb)",
        (sid, json.dumps({"schema_version": 1, "interaction_ref": ref})))
    return str(cur.fetchone()[0])


def prosrc(cur, sig):
    return q1(cur, "SELECT prosrc FROM pg_proc WHERE oid = %s::regprocedure", (sig,))


def maps(cur):
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def observe(cur, actor, ids):
    if ids is None:
        cur.execute("SELECT * FROM v13_observe(%s::uuid, NULL::uuid[])", (actor,))
    else:
        cur.execute("SELECT * FROM v13_observe(%s::uuid, %s::uuid[])", (actor, ids))
    return maps(cur)


def s(value):
    return None if value is None else str(value)


def reality(cur, sid):
    cur.execute(
        "SELECT parent_session_id::text, status, spawn_kind, turn_no, "
        "status IN ('completed', 'failed', 'cancelled') "
        "FROM sessions WHERE session_id = %s",
        (sid,))
    parent, status, spawn, turn, terminal = cur.fetchone()
    cur.execute(
        "SELECT seq, type FROM events WHERE session_id = %s ORDER BY seq DESC LIMIT 1",
        (sid,))
    ev = cur.fetchone()
    seq, typ = (-1, None) if ev is None else ev
    return {
        "parent": parent,
        "status": status,
        "spawn": spawn,
        "turn": turn,
        "terminal": terminal,
        "seq": seq,
        "type": typ,
        "pending": q1(cur, "SELECT v13_pending_human(%s)", (sid,)),
        "cancel": q1(cur, "SELECT v13_unconsumed_cancel(%s)", (sid,)),
    }


def match_row(row, sid, ordinal, got):
    return (
        row["ordinal"] == ordinal
        and s(row["session_id"]) == sid
        and s(row["parent_session_id"]) == got["parent"]
        and row["status"] == got["status"]
        and row["spawn_kind"] == got["spawn"]
        and row["is_terminal"] is got["terminal"]
        and row["turn_no"] == got["turn"]
        and row["last_event_seq"] == got["seq"]
        and row["last_event_type"] == got["type"]
        and row["pending_human"] is got["pending"]
        and row["cancel_pending"] is got["cancel"]
    )


def log_text(cur, actor, sid, after, two_arg=False):
    if two_arg:
        cur.execute(
            "SELECT seq::text, event_id::text, type, coalesce(turn_no::text, ''), "
            "payload::text, payload_hash, coalesce(source_effect_id::text, ''), at::text "
            "FROM v13_session_log(%s, %s)",
            (actor, sid))
    else:
        cur.execute(
            "SELECT seq::text, event_id::text, type, coalesce(turn_no::text, ''), "
            "payload::text, payload_hash, coalesce(source_effect_id::text, ''), at::text "
            "FROM v13_session_log(%s, %s, %s)",
            (actor, sid, after))
    return cur.fetchall()


def direct_log(cur, sid, after=None):
    if after is None:
        cur.execute(
            "SELECT seq::text, event_id::text, type, coalesce(turn_no::text, ''), "
            "payload::text, payload_hash, coalesce(source_effect_id::text, ''), at::text "
            "FROM events WHERE session_id = %s ORDER BY seq",
            (sid,))
    else:
        cur.execute(
            "SELECT seq::text, event_id::text, type, coalesce(turn_no::text, ''), "
            "payload::text, payload_hash, coalesce(source_effect_id::text, ''), at::text "
            "FROM events WHERE session_id = %s AND seq > %s ORDER BY seq",
            (sid, after))
    return cur.fetchall()


def blob(rows):
    return "\n".join("|".join(col for col in row) for row in rows)


def main() -> int:
    sql_text = (ROOT / "v13_observe.sql").read_text()
    readme = (ROOT / "README.md").read_text()
    check("sql has no control_actor", "v13.control_actor" not in sql_text)
    check("sql has no current_setting", "current_setting" not in sql_text)
    check("readme has no control_actor", "v13.control_actor" not in readme)
    check("sql has no pg_terminate_backend", "pg_terminate_backend" not in sql_text)
    check("sql has no LISTEN", "LISTEN" not in sql_text)
    check("sql has no pg_sleep", "pg_sleep" not in sql_text)
    check("sql has no CREATE VIEW", "CREATE VIEW" not in sql_text)
    check("sql has no ALTER TABLE", "ALTER TABLE" not in sql_text)
    check("sql has no CREATE TABLE", "CREATE TABLE" not in sql_text)
    check("sql has no CREATE TRIGGER", "CREATE TRIGGER" not in sql_text)
    grants = [ln for ln in sql_text.splitlines() if ln.strip().upper().startswith("GRANT")]
    check("grant lines only route",
          grants != [] and all(
              "v13_route" in ln and "v13_recall" not in ln and "v13_worker" not in ln
              and "v13_resolve" not in ln and "v13_spawn_owner" not in ln
              for ln in grants), grants)
    check("load order observe is 24",
          STAGE_THROUGH.get("observe") == 24
          and SQL_LOAD_ORDER[STAGE_THROUGH["observe"] - 1].name == "v13_observe.sql"
          and STAGE_THROUGH.get("acl") == 23
          and SQL_LOAD_ORDER[STAGE_THROUGH["acl"] - 1].name == "v13_acl.sql")
    check("readme names driver contract",
          "waiter" in readme and "第一个 interesting" in readme and "v13_route" in readme)

    server = get_server()
    prepare(server)
    conn = connect(server)
    cur = conn.cursor()
    check("authorized identity",
          q1(cur, "SELECT pg_get_function_identity_arguments("
             "'public.v13_control_authorized(uuid,uuid)'::regprocedure)")
          == "p_actor uuid, p_target uuid")
    check("authorized boolean",
          q1(cur, "SELECT pg_get_function_result("
             "'public.v13_control_authorized(uuid,uuid)'::regprocedure)")
          == "boolean")
    check("pending human boolean",
          q1(cur, "SELECT pg_get_function_result('public.v13_pending_human(uuid)'::regprocedure)")
          == "boolean"
          and q1(cur, "SELECT pg_typeof(v13_pending_human(NULL::uuid))::text") == "boolean")
    advance = q1(cur, "SELECT pg_get_functiondef('public.v13_advance(uuid,jsonb)'::regprocedure)")
    check("advance names unconsumed cancel",
          "v13_unconsumed_cancel" in advance and "v13_cancel_pending" not in advance)
    check("unconsumed cancel boolean",
          q1(cur, "SELECT pg_get_function_result("
             "'public.v13_unconsumed_cancel(uuid)'::regprocedure)") == "boolean"
          and q1(cur, "SELECT pg_typeof(v13_unconsumed_cancel(NULL::uuid))::text") == "boolean")
    tree = q1(cur, "SELECT pg_get_functiondef('public.v_goal_tree(uuid)'::regprocedure)")
    check("terminal set from goal tree",
          "status IN ('completed', 'failed', 'cancelled')" in tree)
    check("observe absent before apply",
          q1(cur, "SELECT to_regprocedure('public.v13_observe(uuid,uuid[])') IS NULL") is True)
    check("session_log absent before apply",
          q1(cur, "SELECT to_regprocedure('public.v13_session_log(uuid,uuid,bigint)') IS NULL")
          is True)
    conn.rollback()
    conn.close()

    apply_observe(server)
    conn = connect(server)
    cur = conn.cursor()

    obs = prosrc(cur, "v13_observe(uuid,uuid[])")
    log = prosrc(cur, "v13_session_log(uuid,uuid,bigint)")
    split_at = min(obs.index("parent_session_id"), obs.index("events"))
    auth = obs[:split_at]
    snap = obs[split_at:]
    check("observe auth calls predicate", "v13_control_authorized" in auth)
    check("observe auth returns before snapshot", "RETURN;" in auth)
    check("observe auth does not read parent", "parent_session_id" not in auth)
    check("observe auth does not query events", "events" not in auth)
    check("observe auth does not call adapters",
          "v13_pending_human" not in auth and "v13_unconsumed_cancel" not in auth)
    check("observe snapshot outputs parent", "parent_session_id" in snap)
    check("observe snapshot reads events", "events" in snap)
    check("observe snapshot calls adapters",
          "v13_pending_human" in snap and "v13_unconsumed_cancel" in snap)
    check("session_log calls predicate", "v13_control_authorized" in log)
    check("session_log cursor before predicate",
          log.index(LOG_CURSOR) < log.index("v13_control_authorized"))
    check("session_log predicate before events",
          log.index("RETURN;") < log.index("events")
          and log.index("v13_control_authorized") < log.index("events"))
    check("session_log no parent_session_id", "parent_session_id" not in log)
    check("session_log no join effects",
          "effects" not in log.lower() and "join" not in log.lower())
    for sig, src in (
        ("v13_observe(uuid,uuid[])", obs),
        ("v13_session_log(uuid,uuid,bigint)", log),
    ):
        check(f"{sig} no control_actor", "v13.control_actor" not in src)
        check(f"{sig} no current_setting", "current_setting" not in src)
        check(f"{sig} no LISTEN", "LISTEN" not in src)
        check(f"{sig} no pg_sleep", "pg_sleep" not in src)
        check(f"{sig} no CREATE TABLE", "CREATE TABLE" not in src)
        check(f"{sig} stable",
              q1(cur, "SELECT provolatile FROM pg_proc WHERE oid = %s::regprocedure", (sig,))
              == "s")
        check(f"{sig} invoker",
              q1(cur, "SELECT prosecdef FROM pg_proc WHERE oid = %s::regprocedure", (sig,))
              is False)
        check(f"{sig} plpgsql",
              q1(cur, "SELECT l.lanname FROM pg_proc p JOIN pg_language l ON l.oid = p.prolang "
                 "WHERE p.oid = %s::regprocedure", (sig,)) == "plpgsql")
        cfg = q1(cur, "SELECT proconfig::text FROM pg_proc WHERE oid = %s::regprocedure", (sig,))
        check(f"{sig} search_path", cfg is not None and "search_path" in cfg, cfg)
    for sig in STAGE23:
        resolved = q1(cur, "SELECT to_regprocedure(%s)", (sig,))
        check(f"stage 23 resolved {sig}", resolved is not None)
        src = prosrc(cur, sig)
        check(f"{sig} no control_actor", "v13.control_actor" not in src)
        check(f"{sig} no current_setting", "current_setting" not in src)
    for sig in STAGE25:
        resolved = q1(cur, "SELECT to_regprocedure(%s)", (sig,))
        if resolved is None:
            continue
        src = prosrc(cur, sig)
        check(f"{sig} no control_actor", "v13.control_actor" not in src)
        check(f"{sig} no current_setting", "current_setting" not in src)
    check("session_log default null",
          "DEFAULT NULL" in q1(cur, "SELECT pg_get_function_arguments("
                              "'v13_session_log(uuid,uuid,bigint)'::regprocedure)"))
    check("observe columns",
          q1(cur, "SELECT pg_get_function_result('v13_observe(uuid,uuid[])'::regprocedure)")
          == "TABLE(ordinal integer, session_id uuid, parent_session_id uuid, status text, "
             "spawn_kind text, is_terminal boolean, turn_no integer, last_event_seq bigint, "
             "last_event_type text, pending_human boolean, cancel_pending boolean)")
    check("session_log columns",
          q1(cur, "SELECT pg_get_function_result('v13_session_log(uuid,uuid,bigint)'::regprocedure)")
          == "TABLE(seq bigint, event_id uuid, type text, turn_no integer, payload jsonb, "
             "payload_hash text, source_effect_id uuid, at timestamp with time zone)")

    for sig in ("v13_observe(uuid,uuid[])", "v13_session_log(uuid,uuid,bigint)"):
        check(f"route execute {sig}",
              q1(cur, "SELECT has_function_privilege('v13_route', %s, 'EXECUTE')", (sig,))
              is True)
        check(f"route_login execute {sig}",
              q1(cur, "SELECT has_function_privilege('v13_route_login', %s, 'EXECUTE')", (sig,))
              is True)
        for role in ("public", "v13_recall", "v13_worker", "v13_resolve", "v13_spawn_owner"):
            check(f"{role} no execute {sig}",
                  q1(cur, "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, sig))
                  is False)
    missing = u()
    for role in ("v13_recall", "v13_worker", "v13_resolve", "v13_spawn_owner"):
        cur.execute(f"SET ROLE {role}")
        fails_code(cur, "SELECT * FROM v13_observe(NULL::uuid, ARRAY[%s]::uuid[])", (missing,),
                   "42501", f"{role} observe 42501")
        fails_code(cur, "SELECT * FROM v13_session_log(NULL::uuid, %s)", (missing,),
                   "42501", f"{role} session_log 42501")
        cur.execute("RESET ROLE")

    parent = open_session(cur)
    child = insert_child(cur, parent, "fresh_fork")
    other = insert_child(cur, parent, "recompute")
    grand = insert_child(cur, child)
    unrelated = open_session(cur)
    rows = observe(cur, parent, [child])
    check("parent sees child one row", len(rows) == 1 and list(rows[0]) == list(OBS_COLS))
    got = reality(cur, child)
    check("no-event columns match",
          match_row(rows[0], child, 1, got) and got["seq"] == -1 and got["type"] is None
          and got["spawn"] == "fresh_fork" and got["turn"] == 0 and got["status"] == "ready"
          and got["terminal"] is False and got["pending"] is False and got["cancel"] is False,
          (rows[0], got))
    ordered = list(reversed(sorted([other, child])))
    pair = observe(cur, parent, ordered)
    check("input order not uuid order",
          len(pair) == 2
          and [s(r["session_id"]) for r in pair] == ordered
          and [r["ordinal"] for r in pair] == [1, 2]
          and ordered != sorted(ordered))
    check("second child columns", match_row(pair[0], ordered[0], 1, reality(cur, ordered[0])))
    check("first of pair still matches", match_row(pair[1], ordered[1], 2, reality(cur, ordered[1])))

    for label, ids in (
        ("child+unrelated", [child, unrelated]),
        ("child+grandchild", [child, grand]),
        ("self", [parent]),
        ("missing", [u()]),
        ("self mixed with child", [parent, child]),
    ):
        hidden = observe(cur, parent, ids)
        check(f"mixed zero {label}", hidden == [], hidden)
        again = observe(cur, parent, [child])
        check(f"later single child still one after {label}",
              len(again) == 1 and s(again[0]["session_id"]) == child and again[0]["ordinal"] == 1)
    cur.execute("SELECT * FROM v13_observe(%s, '{}'::uuid[])", (parent,))
    check("empty array zero", maps(cur) == [])
    check("null array zero", observe(cur, parent, None) == [])
    ghost = u()
    fails_exact(cur, "SELECT * FROM v13_observe(%s, ARRAY[%s::uuid, %s::uuid])",
                (parent, child, child), OBS_DUP, "duplicate existing")
    fails_exact(cur, "SELECT * FROM v13_observe(%s, ARRAY[%s::uuid, %s::uuid])",
                (parent, ghost, ghost), OBS_DUP, "duplicate missing same text")
    fails_exact(cur, "SELECT * FROM v13_observe(%s, ARRAY[%s::uuid, NULL]::uuid[])",
                (parent, child, ), OBS_ID, "null element")
    fails_exact(cur, "SELECT * FROM v13_observe(%s, ARRAY[%s::uuid, NULL]::uuid[])",
                (parent, ghost, ), OBS_ID, "null element missing same text")
    fails_exact(cur, "SELECT * FROM v13_observe(%s, ARRAY[%s::uuid, %s::uuid, NULL]::uuid[])",
                (parent, child, child), OBS_ID, "null element before duplicate")
    check("duplicate text has no uuid",
          child not in OBS_DUP and ghost not in OBS_DUP and "session" not in OBS_DUP)
    check("null element text has no uuid",
          child not in OBS_ID and ghost not in OBS_ID and "session" not in OBS_ID)
    still = observe(cur, parent, [child])
    check("child still observable after parameter errors",
          len(still) == 1 and s(still[0]["session_id"]) == child)

    admin = observe(cur, None, [unrelated, parent])
    check("admin null sees unrelated and parent",
          len(admin) == 2
          and [s(r["session_id"]) for r in admin] == [unrelated, parent]
          and [r["ordinal"] for r in admin] == [1, 2]
          and match_row(admin[0], unrelated, 1, reality(cur, unrelated))
          and match_row(admin[1], parent, 2, reality(cur, parent)))

    before_noise = observe(cur, parent, [child])
    cur.execute("SELECT set_config('v13.observe.probe', 'x', true)")
    after_noise = observe(cur, parent, [child])
    denied = observe(cur, parent, [unrelated])
    check("guc noise does not change result",
          after_noise == before_noise and len(after_noise) == 1
          and s(after_noise[0]["session_id"]) == child and denied == [])

    rich = insert_child(cur, parent)
    seq1 = prefix(cur, rich, "one")
    enqueue_human(cur, rich, "ix-obs")
    rich_row = observe(cur, parent, [rich])
    rich_got = reality(cur, rich)
    check("pending and last event match",
          len(rich_row) == 1 and match_row(rich_row[0], rich, 1, rich_got)
          and rich_got["pending"] is True and rich_got["seq"] == seq1
          and rich_got["type"] == "user/message" and rich_got["turn"] == 1,
          rich_got)
    cancelled = insert_child(cur, parent)
    cur.execute("SELECT v13_cancel(%s, %s)", (parent, cancelled))
    check("cancel accepted for pending flag", cur.fetchone()[0] == "accepted")
    cancel_row = observe(cur, parent, [cancelled])
    cancel_got = reality(cur, cancelled)
    check("cancel_pending matches adapter",
          len(cancel_row) == 1 and match_row(cancel_row[0], cancelled, 1, cancel_got)
          and cancel_got["cancel"] is True and cancel_got["pending"] is False,
          cancel_got)
    terminal = insert_child(cur, parent)
    cur.execute("UPDATE sessions SET status = 'cancelled' WHERE session_id = %s", (terminal,))
    term_row = observe(cur, parent, [terminal])
    term_got = reality(cur, terminal)
    check("terminal flag matches status",
          len(term_row) == 1 and match_row(term_row[0], terminal, 1, term_got)
          and term_got["terminal"] is True and term_got["status"] == "cancelled")

    logged = insert_child(cur, parent)
    prefix(cur, logged, "a")
    prefix(cur, logged, "b")
    full = direct_log(cur, logged)
    check("authorized log equals select",
          log_text(cur, parent, logged, None) == full and len(full) == 2)
    check("two-arg log equals null cursor",
          log_text(cur, parent, logged, None, two_arg=True) == full)
    check("cursor -1 is full log", log_text(cur, parent, logged, -1) == full)
    mx = int(full[-1][0])
    check("after max is zero", log_text(cur, parent, logged, mx) == [])
    check("unauth null cursor zero", log_text(cur, parent, unrelated, None) == [])
    check("unauth -1 cursor zero", log_text(cur, parent, unrelated, -1) == [])
    check("unauth legal cursor zero", log_text(cur, parent, grand, 0) == [])
    check("unknown null cursor zero", log_text(cur, parent, u(), None) == [])
    msg_unauth = fails_exact(
        cur, "SELECT * FROM v13_session_log(%s, %s, %s)",
        (parent, unrelated, -3), LOG_CURSOR, "unauth cursor < -2")
    msg_auth = fails_exact(
        cur, "SELECT * FROM v13_session_log(%s, %s, %s)",
        (parent, logged, -3), LOG_CURSOR, "auth cursor < -2")
    msg_auth_2 = fails_exact(
        cur, "SELECT * FROM v13_session_log(%s, %s, %s)",
        (parent, logged, -2), LOG_CURSOR, "auth cursor -2")
    msg_unauth_2 = fails_exact(
        cur, "SELECT * FROM v13_session_log(%s, %s, %s)",
        (parent, unrelated, -2), LOG_CURSOR, "unauth cursor -2 after auth")
    check("cursor texts identical both orders",
          msg_unauth == msg_auth == msg_auth_2 == msg_unauth_2 == LOG_CURSOR)
    check("cursor text has no uuid",
          logged not in LOG_CURSOR and unrelated not in LOG_CURSOR and grand not in LOG_CURSOR)
    seq3 = prefix(cur, logged, "c")
    moved = log_text(cur, parent, logged, mx)
    check("watermark moves exactly",
          moved == direct_log(cur, logged, mx)
          and len(moved) == 1 and int(moved[0][0]) == seq3 and moved[0][2] == "user/message")
    check("null and -1 still full after append",
          log_text(cur, parent, logged, None) == log_text(cur, parent, logged, -1)
          == direct_log(cur, logged))
    quiet_a = log_text(cur, parent, logged, None)
    quiet_b = log_text(cur, parent, logged, None)
    check("two no-write calls byte identical",
          quiet_a == quiet_b and blob(quiet_a) == blob(quiet_b) and blob(quiet_a) != "")
    conn.rollback()
    conn.close()

    setup = connect(server)
    sc = setup.cursor()
    route_parent = open_session(sc)
    route_child = insert_child(sc, route_parent, "fresh_fork")
    prefix(sc, route_child, "route")
    route_other = open_session(sc)
    setup.commit()
    setup.close()
    route = connect(server)
    rc = route.cursor()
    rc.execute("SET ROLE v13_route")
    rc.execute("SELECT * FROM v13_observe(%s, %s::uuid[])", (route_parent, [route_child]))
    route_rows = maps(rc)
    check("route observe one row",
          len(route_rows) == 1 and s(route_rows[0]["session_id"]) == route_child
          and route_rows[0]["ordinal"] == 1 and route_rows[0]["spawn_kind"] == "fresh_fork")
    rc.execute("SELECT count(*) FROM v13_session_log(%s, %s)", (route_parent, route_child))
    check("route session_log reads", rc.fetchone()[0] == 1)
    rc.execute("SELECT count(*) FROM v13_observe(NULL::uuid, %s::uuid[])", ([route_other],))
    check("route null actor observes unrelated", rc.fetchone()[0] == 1)
    route.commit()
    route.close()
    verify = connect(server)
    vc = verify.cursor()
    vc.execute("SET ROLE v13_route")
    vc.execute("SELECT session_id::text FROM v13_observe(%s, %s::uuid[])",
               (route_parent, [route_child]))
    check("route commit kept the read path", vc.fetchone()[0] == route_child)
    verify.commit()
    verify.close()

    print(f"[observe] ALL PASS ({N})")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"[observe] FAIL {exc}")
        raise SystemExit(1)
