"""Stage 23 gate: control authorization for cancel and human complete.

Run: uv run python v13/acl/test_acl.py  (exit 0 = pass)
"""
from __future__ import annotations

import json
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v13.acl.setup_db import DB, apply_acl, prepare
from v13.load import SQL_LOAD_ORDER, STAGE_THROUGH

N = 0
UNIFIED = "v13: session not found"


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


def connect_obs(server, db=DB):
    conn = psycopg2.connect(server.get_uri(db))
    conn.autocommit = True
    return conn


def raise_msg(cur, sql, params):
    cur.execute("SAVEPOINT sp")
    try:
        cur.execute(sql, params)
    except psycopg2.Error as exc:
        msg = exc.diag.message_primary
        cur.execute("ROLLBACK TO SAVEPOINT sp")
        return msg, exc.pgcode
    cur.execute("ROLLBACK TO SAVEPOINT sp")
    raise AssertionError(f"expected failure: {sql}")


def fails_with(cur, sql, params, needle, label):
    msg, _code = raise_msg(cur, sql, params)
    check(label, msg is not None and needle in msg, msg)
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


def insert_child(cur, parent):
    sid = u()
    cur.execute("SET LOCAL ROLE v13_spawn_owner")
    cur.execute(
        "INSERT INTO sessions (session_id, parent_session_id) VALUES (%s, %s)",
        (sid, parent))
    cur.execute("RESET ROLE")
    return sid


def enqueue_tool(cur, sid, name="send_summary_email", request=None):
    body = request if request is not None else {
        "tool": name, "params": {}, "handler": "worker:" + name, "tools_revision": 1,
    }
    cur.execute(
        "SELECT v13_enqueue_effect(%s, 'tool', %s::jsonb, %s)",
        (sid, json.dumps(body), name))
    return str(cur.fetchone()[0])


def enqueue_human(cur, sid, ref):
    cur.execute(
        "SELECT v13_enqueue_effect(%s, 'human', %s::jsonb)",
        (sid, json.dumps({"schema_version": 1, "interaction_ref": ref})))
    return str(cur.fetchone()[0])


def claim(cur, eid):
    cur.execute(
        "UPDATE effects SET status='claimed', attempt_no=1, fence=1, "
        "lease_owner='w', lease_until=clock_timestamp()+interval '1 hour' "
        "WHERE effect_id=%s RETURNING attempt_no, fence", (eid,))
    return cur.fetchone()


def event_count(cur, sid, etype=None):
    if etype is None:
        cur.execute("SELECT count(*) FROM events WHERE session_id=%s", (sid,))
    else:
        cur.execute(
            "SELECT count(*) FROM events WHERE session_id=%s AND type=%s", (sid, etype))
    return cur.fetchone()[0]


def effect_status(cur, eid):
    cur.execute("SELECT status FROM effects WHERE effect_id=%s", (eid,))
    row = cur.fetchone()
    return None if row is None else row[0]


def effect_done(cur, eid):
    cur.execute(
        "SELECT count(*) FROM events WHERE source_effect_id=%s AND type='effect_done'", (eid,))
    return cur.fetchone()[0]


def human_payload(ref, extra=None):
    body = {"schema_version": 1, "interaction_ref": ref, "response": "yes"}
    if extra:
        body.update(extra)
    return body


def attrs(cur, sig):
    cur.execute(
        """
        SELECT pg_get_function_identity_arguments(p.oid),
               pg_get_function_arguments(p.oid),
               p.pronargdefaults, p.provolatile, p.prosecdef,
               p.proconfig::text, p.proparallel, p.proisstrict
          FROM pg_proc p
         WHERE p.oid = %s::regprocedure
        """, (sig,))
    return cur.fetchone()


def prosrc(cur, sig):
    return q1(cur, "SELECT prosrc FROM pg_proc WHERE oid = %s::regprocedure", (sig,))


def acl_of(cur, sig):
    cur.execute(
        """
        SELECT grantee::regrole::text
          FROM pg_proc p,
               aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) a
         WHERE p.oid = %s::regprocedure
         ORDER BY 1
        """, (sig,))
    return [r[0] for r in cur.fetchall()]


def expected_cancel(old):
    body = old.replace("  v_extra int;\n", "  v_extra int;\n  v_actor uuid;\n", 1)
    admit = (
        "  v_actor := p_actor;\n"
        "  IF v_actor IS NOT NULL THEN\n"
        "    IF NOT public.v13_control_authorized(v_actor, p_sid) THEN\n"
        "      RAISE EXCEPTION 'v13: session not found';\n"
        "    END IF;\n"
        "  ELSIF NOT public.v13_control_operator() THEN\n"
        "    RAISE EXCEPTION 'v13: session not found';\n"
        "  END IF;\n"
    )
    body = body.replace("BEGIN\n", "BEGIN\n" + admit, 1)
    recheck = (
        "  IF v_actor IS NOT NULL AND NOT public.v13_control_authorized(v_actor, p_sid) THEN\n"
        "    RAISE EXCEPTION 'v13: session not found';\n"
        "  END IF;\n"
    )
    anchor = "    RAISE EXCEPTION 'v13: cancel tree changed';\n  END IF;\n"
    return body.replace(anchor, anchor + recheck, 1)


def expected_complete(old):
    prelock = (
        "  SELECT session_id, kind INTO v_sid, v_kind FROM effects WHERE effect_id = p_effect;\n"
        "  IF p_actor IS NOT NULL THEN\n"
        "    IF NOT FOUND OR v_kind IS DISTINCT FROM 'human' THEN\n"
        "      RAISE EXCEPTION 'v13: session not found';\n"
        "    END IF;\n"
        "    IF NOT public.v13_control_authorized(p_actor, v_sid) THEN\n"
        "      RAISE EXCEPTION 'v13: session not found';\n"
        "    END IF;\n"
        "  ELSIF NOT FOUND THEN\n"
        "    IF public.v13_control_operator() THEN\n"
        "      RAISE EXCEPTION 'v13: unknown effect %', p_effect;\n"
        "    END IF;\n"
        "    RAISE EXCEPTION 'v13: session not found';\n"
        "  ELSIF v_kind = 'human' AND NOT public.v13_control_operator() THEN\n"
        "    RAISE EXCEPTION 'v13: session not found';\n"
        "  END IF;\n"
    )
    postlock = (
        "  IF NOT FOUND THEN\n"
        "    IF p_actor IS NOT NULL OR NOT public.v13_control_operator() THEN\n"
        "      RAISE EXCEPTION 'v13: session not found';\n"
        "    END IF;\n"
        "    RAISE EXCEPTION 'v13: unknown effect %', p_effect;\n"
        "  END IF;\n"
        "  IF p_actor IS NOT NULL THEN\n"
        "    IF v_row.kind IS DISTINCT FROM 'human'\n"
        "       OR NOT public.v13_control_authorized(p_actor, v_row.session_id) THEN\n"
        "      RAISE EXCEPTION 'v13: session not found';\n"
        "    END IF;\n"
        "  ELSIF v_row.kind = 'human' AND NOT public.v13_control_operator() THEN\n"
        "    RAISE EXCEPTION 'v13: session not found';\n"
        "  END IF;\n"
    )
    body = old.replace(
        "  v_sid uuid; v_row effects;",
        "  v_sid uuid; v_kind text; v_row effects;", 1)
    body = body.replace(
        "  SELECT session_id INTO v_sid FROM effects WHERE effect_id = p_effect;\n",
        prelock, 1)
    body = body.replace(
        "  IF NOT FOUND THEN\n"
        "    RAISE EXCEPTION 'v13: unknown effect %', p_effect;\n"
        "  END IF;\n",
        postlock, 1)
    return body


def frozen_spawn_owner_calls():
    hits = []
    for path in (AGENT_ROOT / "v13").rglob("test_*.py"):
        if path.name == "test_acl.py":
            continue
        lines = path.read_text().splitlines()
        for i, line in enumerate(lines):
            if "v13_spawn_owner" not in line:
                continue
            if "SET ROLE" not in line and "SET LOCAL ROLE" not in line:
                continue
            window = "\n".join(lines[i:i + 40])
            if "v13_cancel(" in window or "v13_complete(" in window:
                hits.append(f"{path}:{i + 1}")
    return hits


def snapshot(cur, sid, eid=None):
    snap = {
        "events": event_count(cur, sid),
        "cancel": event_count(cur, sid, "cancel/requested"),
        "responded": event_count(cur, sid, "human/responded"),
    }
    if eid is not None:
        snap["status"] = effect_status(cur, eid)
        snap["done"] = effect_done(cur, eid)
    return snap


def main() -> int:
    sql_text = (ROOT / "v13_acl.sql").read_text()
    readme = (ROOT / "README.md").read_text()
    check("sql has no control_actor", "v13.control_actor" not in sql_text)
    check("readme has no control_actor", "v13.control_actor" not in readme)
    check("sql has no pg_terminate_backend", "pg_terminate_backend" not in sql_text)
    check("sql has no LISTEN", "LISTEN" not in sql_text)
    check("sql has no CREATE VIEW", "CREATE VIEW" not in sql_text)
    check("sql has no ALTER TABLE", "ALTER TABLE" not in sql_text)
    check("sql has no bare CREATE TABLE",
          "CREATE TABLE" not in sql_text.replace("CREATE TEMP TABLE", ""))
    check("readme names both yellow cells",
          "合同已证明" in readme and "未交付" in readme)
    check("load order acl is 23",
          STAGE_THROUGH.get("acl") == 23
          and SQL_LOAD_ORDER[STAGE_THROUGH["acl"] - 1].name == "v13_acl.sql"
          and STAGE_THROUGH.get("catalog") == 22)
    check("no frozen spawn_owner cancel/complete",
          frozen_spawn_owner_calls() == [], frozen_spawn_owner_calls())

    server = get_server()
    prepare(server)
    conn = connect(server)
    cur = conn.cursor()

    check("F1 cancel identity",
          attrs(cur, "v13_cancel(uuid)")[:5] == (
              "p_sid uuid", "p_sid uuid", 0, "v", False))
    pre_complete = attrs(cur, "v13_complete(uuid,integer,bigint,text,jsonb)")
    check("F1 complete identity",
          pre_complete[0] == "p_effect uuid, p_attempt integer, p_fence bigint, p_status text, p_result jsonb"
          and pre_complete[2] == 1 and pre_complete[3] == "v" and pre_complete[4] is False
          and "DEFAULT NULL::jsonb" in pre_complete[1], pre_complete)
    cancel_src = prosrc(cur, "v13_cancel(uuid)")
    complete_src = prosrc(cur, "v13_complete(uuid,integer,bigint,text,jsonb)")
    check("F2 no EXCEPTION WHEN",
          "EXCEPTION WHEN" not in cancel_src and "EXCEPTION WHEN" not in complete_src)
    for needle in ("v13: goal tree cycle", "v13: goal tree depth", "v13: cancel tree changed",
                   "v13: unknown session", "RETURN 'replay'"):
        check(f"cancel marker {needle}", needle in cancel_src)
    for needle in ("v13: unknown effect", "v13: human channel one-of",
                   "v13: human interaction_ref mismatch", "v13: cancel not pending",
                   "v13_record_worktree_released"):
        check(f"complete marker {needle}", needle in complete_src)
    check("D12 once before replace", complete_src.count("v13_record_worktree_released") == 1)
    cur.execute("SET ROLE v13_worker")
    cur.execute(
        "SELECT current_user, pg_has_role(current_user, 'v13_route', 'USAGE'), "
        "pg_has_role('v13_worker', 'v13_route', 'MEMBER')")
    row = cur.fetchone()
    cur.execute("RESET ROLE")
    check("F3 worker USAGE false", row[0] == "v13_worker" and row[1] is False and row[2] is True, row)
    cur.execute(
        "SELECT atttypid::regtype::text FROM pg_attribute "
        "WHERE attrelid = 'sessions'::regclass AND attname = 'parent_session_id' AND NOT attisdropped")
    check("F4 parent_session_id uuid", cur.fetchone()[0] == "uuid")
    cur.execute(
        "SELECT count(*) FROM pg_proc WHERE proname IN ("
        "'v13_control_authorized','v13_control_operator','v13_observe','v13_session_log',"
        "'v13_extract_handoff','v13_transcript_hash','v13_handoff_emit')")
    check("F5 new names absent", cur.fetchone()[0] == 0)
    check("cancel proacl mirror",
          set(acl_of(cur, "v13_cancel(uuid)")) >= {"postgres", "v13_route", "v13_spawn_owner"})
    check("complete proacl mirror",
          set(acl_of(cur, "v13_complete(uuid,integer,bigint,text,jsonb)"))
          >= {"postgres", "v13_route", "v13_spawn_owner"})
    pre_cancel_attrs = attrs(cur, "v13_cancel(uuid)")
    pre_cancel_acl = acl_of(cur, "v13_cancel(uuid)")
    pre_complete_acl = acl_of(cur, "v13_complete(uuid,integer,bigint,text,jsonb)")
    conn.rollback()
    conn.close()

    apply_acl(server)
    conn = connect(server)
    cur = conn.cursor()

    check("cancel body diff is admission+recheck",
          prosrc(cur, "v13_cancel(uuid,uuid)") == expected_cancel(cancel_src))
    check("complete body diff is the four segments",
          prosrc(cur, "v13_complete(uuid,uuid,integer,bigint,text,jsonb)") == expected_complete(complete_src))
    c1 = prosrc(cur, "v13_cancel(uuid)")
    c5 = prosrc(cur, "v13_complete(uuid,integer,bigint,text,jsonb)")
    check("cancel wrapper pure delegate",
          "RETURN v13_cancel(NULL::uuid, p_sid);" in c1
          and "v13_append_event" not in c1 and "CREATE TEMP" not in c1
          and "v13_control_authorized" not in c1 and "v13_control_operator" not in c1)
    check("complete wrapper pure delegate",
          "RETURN v13_complete(NULL::uuid, p_effect, p_attempt, p_fence, p_status, p_result);" in c5
          and "v13_append_event" not in c5 and "v13_control_authorized" not in c5
          and "v13_control_operator" not in c5 and "unknown effect" not in c5)
    for sig in ("v13_cancel(uuid,uuid)", "v13_complete(uuid,uuid,integer,bigint,text,jsonb)",
                "v13_cancel(uuid)", "v13_complete(uuid,integer,bigint,text,jsonb)"):
        src = prosrc(cur, sig)
        check(f"{sig} no control_actor", "v13.control_actor" not in src and "current_setting" not in src)
    check("wrapper cancel attrs preserved", attrs(cur, "v13_cancel(uuid)") == pre_cancel_attrs)
    check("wrapper complete attrs preserved",
          attrs(cur, "v13_complete(uuid,integer,bigint,text,jsonb)") == pre_complete)
    check("wrapper cancel acl preserved", acl_of(cur, "v13_cancel(uuid)") == pre_cancel_acl)
    check("wrapper complete acl preserved",
          acl_of(cur, "v13_complete(uuid,integer,bigint,text,jsonb)") == pre_complete_acl)
    op = prosrc(cur, "v13_control_operator()")
    auth = prosrc(cur, "v13_control_authorized(uuid,uuid)")
    check("operator USAGE not MEMBER", "USAGE" in op and "MEMBER" not in op)
    check("v13_route literal only in operator",
          "v13_route" in op and "v13_route" not in auth
          and "v13_route" not in prosrc(cur, "v13_cancel(uuid,uuid)")
          and "v13_route" not in prosrc(cur, "v13_complete(uuid,uuid,integer,bigint,text,jsonb)")
          and "v13_route" not in c1 and "v13_route" not in c5)
    for banned in ("current_setting", "request", "status", "payload"):
        check(f"authorized prosrc has no {banned}", banned not in auth)
    check("authorized reads parent_session_id", "parent_session_id" in auth)
    check("authorized does not lock", "FOR UPDATE" not in auth)
    c6 = prosrc(cur, "v13_complete(uuid,uuid,integer,bigint,text,jsonb)")
    d12_exists = q1(cur, "SELECT to_regprocedure('v13_record_worktree_released(uuid,uuid)') IS NOT NULL")
    d12_count = c6.count("v13_record_worktree_released")
    check("D12 iff one call", (d12_exists and d12_count == 1) or (not d12_exists and d12_count == 0),
          (d12_exists, d12_count))
    check("D12 stays after replay",
          c6.index("v13_record_worktree_released") > c6.index("RETURN 'replay'"))
    for sig, want_path in (
        ("v13_control_operator()", True),
        ("v13_control_authorized(uuid,uuid)", True),
        ("v13_cancel(uuid,uuid)", True),
        ("v13_complete(uuid,uuid,integer,bigint,text,jsonb)", True),
    ):
        cfg = q1(cur, "SELECT proconfig::text FROM pg_proc WHERE oid = %s::regprocedure", (sig,))
        check(f"{sig} search_path", want_path and cfg is not None and "search_path" in cfg, cfg)
        check(f"{sig} invoker volatile-or-stable",
              q1(cur, "SELECT prosecdef FROM pg_proc WHERE oid = %s::regprocedure", (sig,)) is False)
    for role in ("v13_route", "v13_spawn_owner"):
        for sig in ("v13_control_operator()", "v13_control_authorized(uuid,uuid)",
                    "v13_cancel(uuid,uuid)", "v13_complete(uuid,uuid,integer,bigint,text,jsonb)"):
            check(f"{role} execute {sig}",
                  q1(cur, "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, sig)) is True)
    for role in ("public", "v13_worker", "v13_recall", "v13_resolve"):
        for sig in ("v13_control_operator()", "v13_control_authorized(uuid,uuid)",
                    "v13_cancel(uuid,uuid)", "v13_complete(uuid,uuid,integer,bigint,text,jsonb)"):
            check(f"{role} no execute {sig}",
                  q1(cur, "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, sig)) is False)
    check("recall still cannot select effects",
          q1(cur, "SELECT has_table_privilege('v13_recall', 'effects', 'SELECT')") is False)

    sid = open_session(cur)
    check("superuser operator", q1(cur, "SELECT v13_control_operator()") is True)
    check("superuser null actor true",
          q1(cur, "SELECT v13_control_authorized(NULL, %s)", (sid,)) is True)
    cur.execute("SET ROLE v13_route")
    check("route operator", q1(cur, "SELECT v13_control_operator()") is True)
    check("route null actor true",
          q1(cur, "SELECT v13_control_authorized(NULL, %s)", (sid,)) is True)
    cur.execute("RESET ROLE")
    cur.execute("SET ROLE v13_route_login")
    check("route_login in band", q1(cur, "SELECT v13_control_operator()") is True)
    cur.execute("RESET ROLE")
    parent = open_session(cur)
    child = insert_child(cur, parent)
    grand = insert_child(cur, child)
    other = open_session(cur)
    sib = insert_child(cur, parent)
    missing = u()
    missing_actor = u()
    check("parent of child true",
          q1(cur, "SELECT v13_control_authorized(%s, %s)", (parent, child)) is True)
    check("self false", q1(cur, "SELECT v13_control_authorized(%s, %s)", (child, child)) is False)
    check("grandchild false",
          q1(cur, "SELECT v13_control_authorized(%s, %s)", (parent, grand)) is False)
    check("sibling false",
          q1(cur, "SELECT v13_control_authorized(%s, %s)", (child, sib)) is False)
    check("unrelated false",
          q1(cur, "SELECT v13_control_authorized(%s, %s)", (parent, other)) is False)
    check("unknown target false",
          q1(cur, "SELECT v13_control_authorized(%s, %s)", (parent, missing)) is False)
    check("unknown actor false",
          q1(cur, "SELECT v13_control_authorized(%s, %s)", (missing_actor, child)) is False)
    cur.execute("UPDATE sessions SET status='completed' WHERE session_id=%s", (sib,))
    check("terminal direct child still true",
          q1(cur, "SELECT v13_control_authorized(%s, %s)", (parent, sib)) is True)
    for role in ("v13_resolve", "v13_recall", "v13_worker"):
        cur.execute(f"SET ROLE {role}")
        fails_code(cur, "SELECT v13_control_operator()", (), "42501", f"{role} operator 42501")
        fails_code(cur, "SELECT v13_control_authorized(NULL, %s)", (sid,), "42501",
                   f"{role} authorized 42501")
        fails_code(cur, "SELECT v13_cancel(%s)", (sid,), "42501", f"{role} cancel 42501")
        fails_code(cur, "SELECT v13_complete(%s, 1, 1, 'failed')", (u(),), "42501",
                   f"{role} complete 42501")
        cur.execute("RESET ROLE")
    conn.rollback()

    root = open_session(cur)
    prefix(cur, root)
    cur.execute("SET ROLE v13_route")
    cur.execute("SELECT v13_cancel(%s)", (root,))
    check("route 1-arg cancel accepted", cur.fetchone()[0] == "accepted")
    check("route 1-arg one cancel event", event_count(cur, root, "cancel/requested") == 1)
    cur.execute("RESET ROLE")
    conn.commit()

    parent = open_session(cur)
    child = insert_child(cur, parent)
    grand = insert_child(cur, child)
    ge = enqueue_tool(cur, grand)
    before_g = event_count(cur, grand, "cancel/requested")
    cur.execute("SELECT v13_cancel(%s, %s)", (parent, child))
    check("parent 2-arg cancel accepted", cur.fetchone()[0] == "accepted")
    check("target cancel/requested exactly one", event_count(cur, child, "cancel/requested") == 1)
    check("grandchild ready effect fanned out", effect_status(cur, ge) == "cancelled")
    check("grandchild got fanout cancel event", event_count(cur, grand, "cancel/requested") == before_g + 1)
    check("actor session not cancelled", event_count(cur, parent, "cancel/requested") == 0)
    cur.execute("SELECT v13_cancel(%s, %s)", (parent, child))
    check("second 2-arg cancel does not write another",
          cur.fetchone()[0] == "accepted" and event_count(cur, child, "cancel/requested") == 1)
    conn.commit()

    parent = open_session(cur)
    child = insert_child(cur, parent)
    cur.execute("UPDATE sessions SET status='cancelled' WHERE session_id=%s", (child,))
    cur.execute("SELECT v13_cancel(%s, %s)", (parent, child))
    check("terminal direct child replay", cur.fetchone()[0] == "replay")
    check("terminal replay wrote nothing", event_count(cur, child, "cancel/requested") == 0)
    conn.rollback()

    parent = open_session(cur)
    child = insert_child(cur, parent)
    decoy = u()
    cur.execute(
        "SELECT v13_cancel(%s, %s)", (parent, child))
    cur.fetchone()
    check("bound actor not replaced by a decoy uuid",
          event_count(cur, child, "cancel/requested") == 1)
    conn.rollback()
    check("decoy unused", decoy not in child)

    parent = open_session(cur)
    child = insert_child(cur, parent)
    ref = "ix-acl-ok"
    hid = enqueue_human(cur, child, ref)
    attempt, fence = claim(cur, hid)
    payload = human_payload(ref)
    cur.execute(
        "SELECT v13_complete(%s, %s, %s, %s, 'succeeded', %s::jsonb)",
        (parent, hid, attempt, fence, json.dumps(payload)))
    check("parent 6-arg human accepted", cur.fetchone()[0] == "accepted")
    check("human/responded one", event_count(cur, child, "human/responded") == 1)
    check("human effect succeeded", effect_status(cur, hid) == "succeeded")
    conn.commit()

    parent = open_session(cur)
    child = insert_child(cur, parent)
    ref = "ix-acl-route"
    hid = enqueue_human(cur, child, ref)
    attempt, fence = claim(cur, hid)
    cur.execute("SET ROLE v13_route")
    cur.execute(
        "SELECT v13_complete(%s, %s, %s, %s, 'succeeded', %s::jsonb)",
        (parent, hid, attempt, fence, json.dumps(human_payload(ref))))
    check("route 6-arg human accepted", cur.fetchone()[0] == "accepted")
    cur.execute("RESET ROLE")
    conn.commit()

    parent = open_session(cur)
    child = insert_child(cur, parent)
    ref = "ix-acl-5"
    hid = enqueue_human(cur, child, ref)
    attempt, fence = claim(cur, hid)
    cur.execute("SET ROLE v13_route")
    cur.execute(
        "SELECT v13_complete(%s, %s, %s, 'succeeded', %s::jsonb)",
        (hid, attempt, fence, json.dumps(human_payload(ref))))
    check("route 5-arg human accepted", cur.fetchone()[0] == "accepted")
    cur.execute("RESET ROLE")
    conn.rollback()

    parent = open_session(cur)
    child = insert_child(cur, parent)
    ref = "ix-acl-bad"
    hid = enqueue_human(cur, child, ref)
    attempt, fence = claim(cur, hid)
    before = snapshot(cur, child, hid)
    fails_with(
        cur, "SELECT v13_complete(%s, %s, %s, %s, 'succeeded', %s::jsonb)",
        (parent, hid, attempt, fence, json.dumps(human_payload("nope"))),
        "v13: human interaction_ref mismatch", "authorized wrong ref keeps C4")
    check("wrong ref zero write", snapshot(cur, child, hid) == before)
    fails_with(
        cur, "SELECT v13_complete(%s, %s, %s, %s, 'succeeded', %s::jsonb)",
        (child, hid, attempt, fence, json.dumps(human_payload("nope"))),
        UNIFIED, "unauthorized does not see C4")
    check("unauthorized C4 zero write", snapshot(cur, child, hid) == before)
    conn.rollback()

    parent = open_session(cur)
    child = insert_child(cur, parent)
    te = enqueue_tool(cur, child)
    attempt, fence = claim(cur, te)
    before = snapshot(cur, child, te)
    fails_with(
        cur, "SELECT v13_complete(%s, %s, %s, %s, 'cancelled', NULL)",
        (parent, te, attempt, fence),
        UNIFIED, "actor tool cancelled rejected before write")
    after = snapshot(cur, child, te)
    check("tool cancelled zero effect_done",
          after == before and after["status"] == "claimed" and after["done"] == 0, after)
    conn.rollback()

    parent = open_session(cur)
    child = insert_child(cur, parent)
    te = enqueue_tool(cur, child)
    attempt, fence = claim(cur, te)
    fails_with(
        cur, "SELECT v13_complete(%s, %s, %s, %s, 'succeeded', %s::jsonb)",
        (parent, te, attempt, fence, json.dumps({"ok": True})),
        UNIFIED, "superuser actor on tool effect rejected")
    check("superuser actor tool zero effect_done", effect_done(cur, te) == 0)
    conn.rollback()

    sid = open_session(cur)
    unrelated = open_session(cur)
    cur.execute("SET ROLE v13_route")
    before = event_count(cur, sid)
    fails_with(cur, "SELECT v13_cancel(%s, %s)", (unrelated, sid),
               UNIFIED, "route actor does not escalate")
    cur.execute("RESET ROLE")
    check("route actor zero write", event_count(cur, sid) == before)
    conn.rollback()

    parent = open_session(cur)
    child = insert_child(cur, parent)
    ref = "ix-acl-stale"
    hid = enqueue_human(cur, child, ref)
    attempt, fence = claim(cur, hid)
    cur.execute(
        "SELECT v13_complete(%s, %s, %s, %s, 'succeeded', %s::jsonb)",
        (parent, hid, attempt, fence - 1, json.dumps(human_payload(ref))))
    check("authorized 6-arg wrong fence stale", cur.fetchone()[0] == "stale")
    cur.execute(
        "SELECT v13_complete(%s, %s, %s, 'succeeded', %s::jsonb)",
        (hid, attempt, fence, json.dumps(human_payload(ref))))
    check("5-arg human accepted", cur.fetchone()[0] == "accepted")
    cur.execute(
        "SELECT v13_complete(%s, %s, %s, 'succeeded', %s::jsonb)",
        (hid, attempt, fence, json.dumps(human_payload(ref))))
    check("5-arg replay", cur.fetchone()[0] == "replay")
    conn.rollback()

    msgs = []
    parent = open_session(cur)
    child = insert_child(cur, parent)
    grand = insert_child(cur, child)
    other = open_session(cur)
    ge = enqueue_tool(cur, grand)
    cases = [
        ("self", "SELECT v13_cancel(%s, %s)", (child, child), child),
        ("grandchild", "SELECT v13_cancel(%s, %s)", (parent, grand), grand),
        ("unrelated", "SELECT v13_cancel(%s, %s)", (parent, other), other),
        ("missing target", "SELECT v13_cancel(%s, %s)", (parent, missing), missing),
        ("missing actor", "SELECT v13_cancel(%s, %s)", (missing_actor, child), missing_actor),
    ]
    for label, sql, params, banned in cases:
        before = event_count(cur, params[1]) if label != "missing target" else 0
        msg = fails_with(cur, sql, params, UNIFIED, f"cancel {label}")
        msgs.append(msg)
        check(f"{label} message has no uuid", banned not in msg, msg)
        if label != "missing target":
            check(f"{label} zero events", event_count(cur, params[1]) == before)
    check("grandchild effect untouched", effect_status(cur, ge) == "ready")
    cur.execute("SET ROLE v13_spawn_owner")
    msg = fails_with(cur, "SELECT v13_cancel(%s)", (child,), UNIFIED, "spawn_owner empty actor")
    cur.execute("RESET ROLE")
    msgs.append(msg)
    check("empty-actor message has no uuid", child not in msg, msg)
    check("six messages identical", len(set(msgs)) == 1 and msgs[0] == UNIFIED, msgs)
    conn.rollback()

    parent = open_session(cur)
    missing_effect = u()
    msg = fails_with(
        cur, "SELECT v13_complete(%s, %s, 1, 1, 'succeeded', '{}'::jsonb)",
        (parent, missing_effect), UNIFIED, "6-arg missing effect unified")
    check("missing effect hides unknown effect",
          "unknown effect" not in msg and missing_effect not in msg, msg)
    cur.execute("SET ROLE v13_spawn_owner")
    msg = fails_with(
        cur, "SELECT v13_complete(%s, 1, 1, 'succeeded', '{}'::jsonb)",
        (missing_effect,), UNIFIED, "spawn_owner missing effect unified")
    cur.execute("RESET ROLE")
    check("spawn_owner missing effect hides unknown effect",
          "unknown effect" not in msg and missing_effect not in msg, msg)
    msg = fails_with(cur, "SELECT v13_cancel(%s)", (missing,), "v13: unknown session",
                     "superuser missing session keeps needle")
    check("superuser missing session is not unified", UNIFIED not in msg and missing in msg, msg)
    msg = fails_with(
        cur, "SELECT v13_complete(%s, 1, 1, 'failed')", (missing_effect,),
        "v13: unknown effect", "superuser missing effect keeps needle")
    check("superuser missing effect interpolates", missing_effect in msg, msg)
    conn.rollback()

    parent = open_session(cur)
    child = insert_child(cur, parent)
    ref = "ix-acl-self"
    hid = enqueue_human(cur, child, ref)
    attempt, fence = claim(cur, hid)
    forged = u()
    before = snapshot(cur, child, hid)
    msg = fails_with(
        cur, "SELECT v13_complete(%s, %s, %s, %s, 'succeeded', %s::jsonb)",
        (child, hid, attempt, fence, json.dumps(human_payload(ref, {"actor": forged}))),
        UNIFIED, "self human plus forged actor key")
    check("forged key not in message", forged not in msg and child not in msg, msg)
    check("self human zero write", snapshot(cur, child, hid) == before)
    check("forged key did not reach unknown-key", "unknown key" not in msg, msg)
    conn.rollback()

    parent = open_session(cur)
    child = insert_child(cur, parent)
    other = open_session(cur)
    ref = "ix-acl-term2"
    hid = enqueue_human(cur, child, ref)
    attempt, fence = claim(cur, hid)
    cur.execute(
        "SELECT v13_complete(%s, %s, %s, 'succeeded', %s::jsonb)",
        (hid, attempt, fence, json.dumps(human_payload(ref))))
    check("admin sealed human", cur.fetchone()[0] == "accepted")
    msg = fails_with(
        cur, "SELECT v13_complete(%s, %s, %s, %s, 'succeeded', %s::jsonb)",
        (other, hid, attempt, fence, json.dumps(human_payload(ref))),
        UNIFIED, "unauthorized terminal human is not replay")
    check("terminal negative is not replay", "replay" not in msg and "stale" not in msg, msg)
    conn.rollback()

    left = open_session(cur)
    right = open_session(cur)
    for who, label in ((left, "superuser"),):
        eid = enqueue_tool(cur, who, request={
            "tool": "send_summary_email", "params": {"n": label},
            "handler": "worker:send_summary_email", "tools_revision": 1,
        })
        attempt, fence = claim(cur, eid)
        cur.execute("SELECT v13_complete(%s, %s, %s, 'failed')", (eid, attempt, fence))
        word = cur.fetchone()[0]
        done = effect_done(cur, eid)
        check("4-arg default still resolves", word == "accepted", word)
        check("4-arg wrote effect_done", done == 1, done)
    eid = enqueue_tool(cur, right, request={
        "tool": "send_summary_email", "params": {"n": "owner"},
        "handler": "worker:send_summary_email", "tools_revision": 1,
    })
    attempt, fence = claim(cur, eid)
    cur.execute("SELECT v13_complete(%s, %s, %s, 'failed', NULL)", (eid, attempt, fence))
    super_word = cur.fetchone()[0]
    super_done = effect_done(cur, eid)
    eid2 = enqueue_tool(cur, right, request={
        "tool": "send_summary_email", "params": {"n": "owner2"},
        "handler": "worker:send_summary_email", "tools_revision": 1,
    })
    conn.rollback()

    a = open_session(cur)
    b = open_session(cur)
    ea = enqueue_tool(cur, a, request={
        "tool": "send_summary_email", "params": {"n": "su"},
        "handler": "worker:send_summary_email", "tools_revision": 1,
    })
    eb = enqueue_tool(cur, b, request={
        "tool": "send_summary_email", "params": {"n": "so"},
        "handler": "worker:send_summary_email", "tools_revision": 1,
    })
    aa, af = claim(cur, ea)
    ba, bf = claim(cur, eb)
    cur.execute("SELECT v13_complete(%s, %s, %s, 'failed', NULL)", (ea, aa, af))
    super_word = cur.fetchone()[0]
    super_done = effect_done(cur, ea)
    cur.execute("SET ROLE v13_spawn_owner")
    cur.execute("SELECT v13_complete(%s, %s, %s, 'failed', NULL)", (eb, ba, bf))
    owner_word = cur.fetchone()[0]
    cur.execute("RESET ROLE")
    owner_done = effect_done(cur, eb)
    check("non-human predicate not applied",
          super_word == owner_word == "accepted" and super_done == owner_done == 1
          and super_word not in ("stale", "replay"),
          (super_word, owner_word, super_done, owner_done))
    conn.rollback()

    sid = open_session(cur)
    prefix(cur, sid)
    bid = u()
    rev = q1(cur, "SELECT (v13_probe(%s)->>'tools_revision')::bigint", (sid,))
    pe = enqueue_tool(cur, sid, "worktree_prepare", {
        "tool": "worktree_prepare",
        "params": {"binding_artifact_id": bid},
        "handler": "worker:worktree_prepare",
        "tools_revision": rev,
    })
    pa, pf = claim(cur, pe)
    cur.execute(
        "SELECT v13_complete(%s, %s, %s, 'succeeded', %s::jsonb)",
        (pe, pa, pf, json.dumps({"schema_version": 1, "root_path": "/tmp/wt", "base_ref": "main"})))
    check("worktree prepare accepted", cur.fetchone()[0] == "accepted")
    cur.execute("SELECT v13_bind_worktree_from_prepare(%s)", (sid,))
    cur.fetchone()
    rev = q1(cur, "SELECT (v13_probe(%s)->>'tools_revision')::bigint", (sid,))
    rel = enqueue_tool(cur, sid, "worktree_release", {
        "tool": "worktree_release",
        "params": {"binding_artifact_id": bid},
        "handler": "worker:worktree_release",
        "tools_revision": rev,
    })
    ra, rf = claim(cur, rel)
    cur.execute(
        "SELECT v13_complete(%s, %s, %s, 'succeeded', %s::jsonb)",
        (rel, ra, rf, json.dumps({"schema_version": 1})))
    check("old 5-arg release still accepted", cur.fetchone()[0] == "accepted")
    check("D12 event still emitted", event_count(cur, sid, "worktree/released") == 1)
    conn.rollback()

    cur.execute("ALTER TABLE sessions DISABLE TRIGGER trg_sessions_fork_cols_immutable")
    conn.commit()
    try:
        run_races(server)
    finally:
        cur.execute("ALTER TABLE sessions ENABLE TRIGGER trg_sessions_fork_cols_immutable")
        conn.commit()
    conn.close()
    print(f"[acl] ALL PASS ({N})")
    return 0


def run_races(server):
    obs = connect_obs(server)

    def blocked(pid):
        obs_cur = obs.cursor()
        obs_cur.execute("SELECT count(*) FROM pg_locks WHERE pid=%s AND NOT granted", (pid,))
        return obs_cur.fetchone()[0] >= 1

    def race(sql, params, target, unrelated, expect_fail):
        hold = connect(server)
        h = hold.cursor()
        h.execute(
            "UPDATE sessions SET parent_session_id=%s WHERE session_id=%s",
            (unrelated, target))
        box = {"pid": None, "msg": None, "word": None}
        ready = threading.Event()

        def _run():
            c = connect(server)
            k = c.cursor()
            try:
                k.execute("SET statement_timeout = '20000'")
                k.execute("SELECT pg_backend_pid()")
                box["pid"] = k.fetchone()[0]
                ready.set()
                k.execute(sql, params)
                box["word"] = k.fetchone()[0]
                if expect_fail:
                    c.rollback()
                else:
                    c.commit()
            except psycopg2.Error as exc:
                box["msg"] = exc.diag.message_primary
                c.rollback()
            finally:
                c.close()

        thread = threading.Thread(target=_run)
        thread.start()
        check("race backend started", ready.wait(5), box)
        seen = False
        for _ in range(50):
            if box["pid"] is not None and blocked(box["pid"]):
                seen = True
                break
            if box["msg"] is not None or box["word"] is not None:
                break
            time.sleep(0.1)
        check("race blocked on lock", seen, box)
        if expect_fail:
            hold.commit()
        else:
            hold.rollback()
        thread.join(timeout=20)
        hold.close()
        return box

    parent = None
    child = None
    setup = connect(server)
    s = setup.cursor()
    parent = open_session(s)
    child = insert_child(s, parent)
    unrelated = open_session(s)
    ge = enqueue_tool(s, child)
    setup.commit()
    before_events = event_count(s, child)
    before_status = effect_status(s, ge)
    setup.close()
    box = race(
        "SELECT v13_cancel(%s, %s)", (parent, child), child, unrelated, True)
    check("cancel commit race unified", box["msg"] == UNIFIED, box)
    setup = connect(server)
    s = setup.cursor()
    check("cancel commit race zero events", event_count(s, child) == before_events)
    check("cancel commit race effect unchanged", effect_status(s, ge) == before_status)
    setup.close()

    setup = connect(server)
    s = setup.cursor()
    parent = open_session(s)
    child = insert_child(s, parent)
    unrelated = open_session(s)
    setup.commit()
    setup.close()
    box = race(
        "SELECT v13_cancel(%s, %s)", (parent, child), child, unrelated, False)
    check("cancel rollback race accepted", box["word"] == "accepted" and box["msg"] is None, box)
    setup = connect(server)
    s = setup.cursor()
    check("cancel rollback race wrote event", event_count(s, child, "cancel/requested") == 1)
    setup.close()

    ref = "ix-acl-race"
    payload = human_payload(ref)
    setup = connect(server)
    s = setup.cursor()
    parent = open_session(s)
    child = insert_child(s, parent)
    unrelated = open_session(s)
    hid = enqueue_human(s, child, ref)
    attempt, fence = claim(s, hid)
    setup.commit()
    before_events = event_count(s, child)
    setup.close()
    box = race(
        "SELECT v13_complete(%s, %s, %s, %s, 'succeeded', %s::jsonb)",
        (parent, hid, attempt, fence, json.dumps(payload)),
        child, unrelated, True)
    check("complete commit race unified", box["msg"] == UNIFIED, box)
    setup = connect(server)
    s = setup.cursor()
    check("complete commit race zero responded", event_count(s, child, "human/responded") == 0)
    check("complete commit race still claimed", effect_status(s, hid) == "claimed")
    check("complete commit race event count", event_count(s, child) == before_events)
    setup.close()

    setup = connect(server)
    s = setup.cursor()
    parent = open_session(s)
    child = insert_child(s, parent)
    unrelated = open_session(s)
    hid = enqueue_human(s, child, ref)
    attempt, fence = claim(s, hid)
    setup.commit()
    setup.close()
    box = race(
        "SELECT v13_complete(%s, %s, %s, %s, 'succeeded', %s::jsonb)",
        (parent, hid, attempt, fence, json.dumps(payload)),
        child, unrelated, False)
    check("complete rollback race accepted", box["word"] == "accepted" and box["msg"] is None, box)
    setup = connect(server)
    s = setup.cursor()
    check("complete rollback race responded", event_count(s, child, "human/responded") == 1)
    setup.close()
    obs.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"[acl] FAIL {exc}")
        raise SystemExit(1)
