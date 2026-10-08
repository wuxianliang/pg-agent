"""Stage 40 gate: agentctl_observe.

Run: UV_FROZEN=1 uv run python v13/agentctl/test_agentctl.py
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import uuid
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v13.agentctl.setup_db import DB, main as setup_db
import v13.agentctl.setup_db as setup_mod
from v13.load import run_psql
from v13.loop.test_loop import mock_from_needed, set_mock
from v13.plan_arm.test_plan_arm import r0_source_scope

N = 0
SQL = (ROOT / "v13_agentctl.sql").read_text()
SIG = "public.v13_agentctl_observe(uuid,jsonb)"
IDENT = "public.v13_agentctl_observe(p_sid uuid, p_spec jsonb)"
SHAPE = {
    "schema_version": 1,
    "ok": False,
    "reason": "shape",
    "rows": [],
    "hints": [],
    "pointers": [],
}
ROW_KEYS = (
    "ordinal", "session_id", "parent_session_id", "status", "spawn_kind",
    "is_terminal", "turn_no", "last_event_seq", "last_event_type",
    "pending_human", "cancel_pending",
)
FUNCS = {
    "wrap": SIG,
    "observe": "public.v13_observe(uuid,uuid[])",
    "hint": "public.v13_scheduler_hint(uuid)",
    "pointer": "public.v13_child_pointer(uuid,uuid,uuid,uuid,bigint)",
    "append": "public.v13_append_event(uuid,uuid,text,jsonb,uuid)",
    "auth": "public.v13_control_authorized(uuid,uuid)",
}
BANNED = (
    "dblink", "pg_net", "lo_import", "lo_export", "pg_read_file", "pg_write_file",
    "copy program", "v13_append_event", "v13_child_pointer",
    "v13_claim_fair", "v13_claim", "v13_wake_is_satisfied_v1", "13002", "13003",
)


def check(label, condition, detail=""):
    global N
    N += 1
    mark = "PASS" if condition else "FAIL"
    extra = f": {detail}" if detail != "" and (not condition or len(str(detail)) < 240) else ""
    print(f"[{mark}] {label}{extra}")
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def as_obj(value):
    if isinstance(value, str):
        return json.loads(value)
    return value


def connect(server):
    conn = psycopg2.connect(server.get_uri(DB))
    conn.autocommit = False
    return conn


def q1(cur, sql, params=None):
    cur.execute(sql, params)
    row = cur.fetchone()
    return None if row is None else row[0]


def fails_code(cur, sql, params, code, label):
    cur.execute("SAVEPOINT sp")
    try:
        cur.execute(sql, params)
        cur.fetchall()
    except psycopg2.Error as exc:
        check(label, exc.pgcode == code, exc.pgcode)
        cur.execute("ROLLBACK TO SAVEPOINT sp")
        return
    cur.execute("ROLLBACK TO SAVEPOINT sp")
    raise AssertionError(f"{label}: expected {code}")


def fails_msg(cur, sql, params, needle, label):
    cur.execute("SAVEPOINT sp")
    try:
        cur.execute(sql, params)
        cur.fetchall()
    except psycopg2.Error as exc:
        msg = exc.diag.message_primary or ""
        check(label, needle in msg, msg)
        cur.execute("ROLLBACK TO SAVEPOINT sp")
        return msg
    cur.execute("ROLLBACK TO SAVEPOINT sp")
    raise AssertionError(f"{label}: expected failure")


def u():
    return str(uuid.uuid4())


def observe_direct(cur, actor, spec):
    if spec is None:
        cur.execute(
            "SELECT public.v13_agentctl_observe(%s::uuid, NULL::jsonb)",
            (actor,))
    else:
        cur.execute(
            "SELECT public.v13_agentctl_observe(%s::uuid, %s::jsonb)",
            (actor, json.dumps(spec)))
    return as_obj(cur.fetchone()[0])


def oid_of(cur, sig):
    return q1(cur, "SELECT %s::regprocedure::oid::text", (sig,))


def function_call_counts(cur):
    cur.execute("SELECT funcid::text, calls FROM pg_stat_xact_user_functions")
    return {row[0]: row[1] for row in cur.fetchall()}


def probe_counter(cur):
    before = function_call_counts(cur)
    cur.execute("SELECT public.v13_control_authorized(NULL::uuid, NULL::uuid)")
    cur.fetchone()
    after = function_call_counts(cur)
    oid = oid_of(cur, FUNCS["auth"])
    delta = after.get(oid, 0) - before.get(oid, 0)
    check("track_functions probe", delta >= 1, delta)
    return after


def calls_since(cur, baseline, key):
    oid = oid_of(cur, FUNCS[key])
    now = function_call_counts(cur)
    return now.get(oid, 0) - baseline.get(oid, 0)


def open_session(cur, policy=None):
    spec = {} if policy is None else {
        "route_policy_name": policy[0],
        "version": policy[1],
    }
    cur.execute("SELECT v13_open_session(%s::jsonb)", (json.dumps(spec),))
    return str(cur.fetchone()[0])


def insert_child(cur, parent):
    sid = u()
    cur.execute("SET LOCAL ROLE v13_spawn_owner")
    cur.execute(
        "INSERT INTO sessions (session_id, parent_session_id, status) "
        "VALUES (%s, %s, 'ready')",
        (sid, parent))
    cur.execute("RESET ROLE")
    return sid


def append_user(cur, sid, text="observe this"):
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (sid, u(), json.dumps({"text": text})))
    return cur.fetchone()[0]


def snapshot_read_window(cur):
    cur.execute(
        "SELECT session_id::text, status, next_seq, parent_session_id::text "
        "FROM sessions ORDER BY session_id")
    sessions = cur.fetchall()
    cur.execute(
        "SELECT event_id::text, session_id::text, seq, type, payload::text "
        "FROM events ORDER BY session_id, seq, event_id")
    events = cur.fetchall()
    cur.execute(
        "SELECT effect_id::text, session_id::text, status, kind, tool_name "
        "FROM effects ORDER BY effect_id")
    effects = cur.fetchall()
    cur.execute("SELECT count(*) FROM artifacts")
    artifacts = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM latches")
    latches = cur.fetchone()[0]
    cur.execute(
        "SELECT revision, candidate_generation_revision FROM v13_tools_meta")
    meta = cur.fetchone()
    cur.execute(
        "SELECT name, version, active, value::text FROM v13_policies "
        "ORDER BY name, version")
    policies = cur.fetchall()
    cur.execute(
        "SELECT policy_name, policy_version, state FROM v13_route_policies "
        "ORDER BY 1, 2")
    routes = cur.fetchall()
    return sessions, events, effects, artifacts, latches, meta, policies, routes


def fn_rows(cur):
    cur.execute(
        """
        SELECT n.nspname || '.' || p.proname
                 || '(' || pg_get_function_identity_arguments(p.oid) || ')',
               pg_get_functiondef(p.oid),
               r.rolname,
               p.prosecdef,
               p.proacl::text,
               p.provolatile
          FROM pg_proc p
          JOIN pg_namespace n ON n.oid = p.pronamespace
          JOIN pg_roles r ON r.oid = p.proowner
         WHERE n.nspname = 'public'
           AND (p.proname LIKE 'v13\\_%' OR p.proname = 'v_goal_tree')
         ORDER BY 1
        """)
    rows = {}
    for sig, body, owner, secdef, acl, vol in cur.fetchall():
        rows[sig] = (
            hashlib.sha256(body.encode()).hexdigest(),
            owner,
            secdef,
            acl,
            vol,
        )
    return rows


def tool_rows(cur):
    cur.execute(
        "SELECT name, description, kind, handler, param_spec::text, enabled "
        "FROM tools ORDER BY name")
    return cur.fetchall()


def rel_rows(cur):
    cur.execute(
        """
        SELECT c.relname, c.relkind
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public'
         ORDER BY 1, 2
        """)
    rels = cur.fetchall()
    cur.execute(
        """
        SELECT table_name, column_name
          FROM information_schema.columns
         WHERE table_schema = 'public'
         ORDER BY 1, 2
        """)
    cols = cur.fetchall()
    cur.execute(
        """
        SELECT tgname, tgrelid::regclass::text
          FROM pg_trigger
         WHERE NOT tgisinternal
         ORDER BY 1, 2
        """)
    triggers = cur.fetchall()
    cur.execute(
        """
        SELECT indexname
          FROM pg_indexes
         WHERE schemaname = 'public'
         ORDER BY 1
        """)
    indexes = [row[0] for row in cur.fetchall()]
    return rels, cols, triggers, indexes


def choice(value, confidence=0.9):
    return {
        "type": "choice",
        "choice": value,
        "probabilities": {value: confidence},
        "confidence": confidence,
    }


def freeze_probe_policy(cur):
    cur.execute(
        "INSERT INTO v13_route_policies (policy_name, policy_version) "
        "VALUES ('agentctl_observe_probe', 1)")
    cur.execute(
        """
        INSERT INTO thresholds (policy_name, policy_version, signal, band_no, lo, hi, action)
        SELECT 'agentctl_observe_probe', 1, signal, band_no, lo, hi, action
          FROM thresholds
         WHERE policy_name = 'default' AND policy_version = 2
        """)
    extra = (
        "param::agentctl_observe::ids",
        "stated::agentctl_observe::ids",
        "param::agentctl_observe::hint",
        "stated::agentctl_observe::hint",
    )
    for signal in extra:
        cur.execute(
            """
            INSERT INTO thresholds
              (policy_name, policy_version, signal, band_no, lo, hi, action)
            VALUES ('agentctl_observe_probe', 1, %s, 1, 0.60, 'Infinity', 'pass')
            """,
            (signal,))
    cur.execute(
        """
        SELECT signal, band_no, lo, hi, action
          FROM thresholds
         WHERE policy_name = 'default' AND policy_version = 2
         ORDER BY signal, band_no
        """)
    source = cur.fetchall()
    cur.execute(
        """
        SELECT signal, band_no, lo, hi, action
          FROM thresholds
         WHERE policy_name = 'agentctl_observe_probe' AND policy_version = 1
         ORDER BY signal, band_no
        """)
    got = cur.fetchall()
    source_signals = {row[0] for row in source}
    added = [row for row in got if row[0] not in source_signals]
    check("probe copies default v2", set(source) <= set(got), len(got) - len(source))
    check(
        "probe four bands",
        {row[0] for row in added} == set(extra) and len(added) == 4,
        added)
    check("probe no triage", all(row[0] != "triage" for row in got))
    cur.execute(
        "UPDATE v13_route_policies SET state = 'frozen' "
        "WHERE policy_name = 'agentctl_observe_probe' AND policy_version = 1")
    check(
        "probe frozen",
        q1(cur,
           "SELECT state FROM v13_route_policies "
           "WHERE policy_name = 'agentctl_observe_probe' AND policy_version = 1")
        == "frozen")


def prepare_routed_case(cur, with_override):
    root = open_session(cur, ("agentctl_observe_probe", 1))
    append_user(cur, root)
    cur.execute(
        "SELECT v13_spawn_subsession(%s, %s::jsonb)",
        (root, json.dumps({
            "schema_version": 1,
            "children": [{"tool_call_id": "tc-" + u()[:8], "task": "observe me"}],
        })))
    spawned = as_obj(cur.fetchone()[0])
    check(
        "spawn return keys",
        set(spawned) == {"replay_kind", "parent_session_id", "children", "reservation"},
        spawned.keys())
    child = spawned["children"][0]["session_id"]
    ready = q1(
        cur,
        "SELECT count(*) FROM effects "
        "WHERE session_id = %s AND status IN ('ready', 'claimed')",
        (root,))
    check("caller has no ready effect", ready == 0, ready)
    if with_override:
        cur.execute(
            "SELECT v13_submit_override(%s, %s::jsonb)",
            (root, json.dumps({
                "intent": "direct",
                "reason": "",
                "schema_version": 1,
                "source_principal": "operator",
            })))
        cur.fetchone()
    return root, child


def parse_observe_case(cur, root, ids_choice, hint_choice):
    mock = mock_from_needed(
        cur, root,
        intent=choice("sql_answer"),
        tool=choice("agentctl_observe"),
        gate_action={"type": "noul", "noul": 0.9},
        gate_off_topic={"type": "noul", "noul": 0.1},
        risk={"type": "score", "score": 0.5, "confidence": 0.9},
        **{
            "stated::agentctl_observe::ids": {"type": "noul", "noul": 0.9},
            "stated::agentctl_observe::hint": {"type": "noul", "noul": 0.9},
            "param::agentctl_observe::ids": choice(ids_choice),
            "param::agentctl_observe::hint": choice(hint_choice),
        })
    set_mock(cur, mock)
    check("mock response set", q1(cur, "SELECT current_setting('typesafe.mock_response', true)") not in (None, ""))
    cur.execute("SELECT v13_parse(%s)", (root,))
    parsed = as_obj(cur.fetchone()[0])
    check("parse remaining", parsed.get("remaining") == 0, parsed.get("remaining"))
    check("parse failed", parsed.get("failed") is False, parsed.get("failed"))
    check("parse abandon", parsed.get("abandon") is False, parsed.get("abandon"))
    snap = parsed.get("snap") or {}
    check(
        "parse policy",
        snap.get("route_policy_name") == "agentctl_observe_probe"
        and str(snap.get("route_policy_version")) == "1",
        (snap.get("route_policy_name"), snap.get("route_policy_version")))
    return parsed


def actl_catalog_rows(cur, before_tools, after_tools, before_meta, after_meta):
    before = {row[0]: row for row in before_tools}
    after = {row[0]: row for row in after_tools}
    added = set(after) - set(before)
    check("actl_catalog_rows one name", added == {"agentctl_observe"}, added)
    for name, row in before.items():
        check(f"tool unchanged {name}", after[name] == row)
    name, description, kind, handler, spec, enabled = after["agentctl_observe"]
    check("catalog kind", kind == "sql" and handler == "v13_agentctl_observe" and enabled is True)
    check("catalog description", "scheduler hints" in description)
    parsed = json.loads(spec)
    check("param_spec keys", set(parsed) == {"ids", "hint"}, parsed)
    check("no options", all("options" not in parsed[key] for key in parsed), parsed)
    check(
        "questions",
        parsed["ids"]["question"] == "Which session UUID or UUIDs should be observed?"
        and parsed["hint"]["stated"] == "Does the user explicitly request scheduler hints?")
    catalog = as_obj(q1(cur, "SELECT v13_tools_catalog_frozen()"))
    entry = next(item for item in catalog if item["name"] == "agentctl_observe")
    check("frozen handler", "v13_agentctl_observe" in entry["handler"], entry["handler"])
    check("frozen digest", bool(re.fullmatch(r"[0-9a-f]{64}", entry.get("handler_digest", ""))))
    check("revision plus one", after_meta[0] == before_meta[0] + 1, (before_meta, after_meta))
    check("candidate revision unchanged", after_meta[1] == before_meta[1], after_meta)


def actl_shape_closed(cur, actor):
    dup = u()
    specs = [
        None,
        "json-null",
        [],
        "nope",
        1,
        True,
        {},
        {"hint": True},
        {"ids": u(), "source_principal": "controller"},
        {"ids": None},
        {"ids": []},
        {"ids": 1},
        {"ids": True},
        {"ids": {}},
        {"ids": [None]},
        {"ids": [1]},
        {"ids": [True]},
        {"ids": [{}]},
        {"ids": [[u()]]},
        {"ids": "not-a-uuid"},
        {"ids": ""},
        {"ids": u().upper()},
        {"ids": " " + u()},
        {"ids": u().replace("-", "")},
        {"ids": [dup, dup]},
        {"ids": u(), "hint": None},
        {"ids": u(), "hint": 1},
        {"ids": u(), "hint": []},
        {"ids": u(), "hint": {}},
        {"ids": u(), "hint": "TRUE"},
        {"ids": u(), "hint": "False"},
        {"ids": u(), "hint": "yes"},
        {"ids": u(), "hint": ""},
        {"ids": '["' + u() + '"]'},
    ]
    base = probe_counter(cur)
    for spec in specs:
        if spec is None:
            got = observe_direct(cur, actor, None)
        elif spec == "json-null":
            cur.execute(
                "SELECT public.v13_agentctl_observe(%s::uuid, 'null'::jsonb)",
                (actor,))
            got = as_obj(cur.fetchone()[0])
        else:
            got = observe_direct(cur, actor, spec)
        check("shape " + json.dumps(spec, default=str)[:80], got == SHAPE, got)
    check("shape observe calls", calls_since(cur, base, "observe") == 0)
    check("shape hint calls", calls_since(cur, base, "hint") == 0)
    one = u()
    single = observe_direct(cur, actor, {"ids": one})
    listed = observe_direct(cur, actor, {"ids": [one]})
    check("single equals one-element", single == listed, (single, listed))


def actl_actor_gate(cur):
    root = open_session(cur)
    parent = insert_child(cur, root)
    child_a = insert_child(cur, parent)
    child_b = insert_child(cur, parent)
    grandchild = insert_child(cur, child_a)
    sibling = insert_child(cur, root)
    base = probe_counter(cur)
    got = observe_direct(cur, parent, {"ids": [child_b, child_a]})
    check("actl_actor_gate order", [row["session_id"] for row in got["rows"]] == [child_b, child_a], got)
    check("row keys", set(got["rows"][0]) == set(ROW_KEYS), list(got["rows"][0]))
    check("authorized observe calls", calls_since(cur, base, "observe") == 1)
    for label, actor, target in (
        ("self", parent, parent),
        ("sibling", child_a, sibling),
        ("ancestor", child_a, parent),
        ("grandchild", parent, grandchild),
        ("missing target", parent, u()),
        ("missing actor", u(), child_a),
    ):
        window = probe_counter(cur)
        empty = observe_direct(cur, actor, {"ids": target, "hint": True})
        check(label + " empty", empty["ok"] is True and empty["rows"] == [] and empty["hints"] == [], empty)
        check(label + " observe called", calls_since(cur, window, "observe") == 1)
        check(label + " no hint", calls_since(cur, window, "hint") == 0)
    window = probe_counter(cur)
    mixed = observe_direct(cur, parent, {"ids": [child_a, parent]})
    check("mixed hidden", mixed["rows"] == [] and mixed["ok"] is True, mixed)
    check("mixed observe called", calls_since(cur, window, "observe") == 1)
    again = observe_direct(cur, parent, {"ids": child_a})
    check("later single still readable", again["rows"] and again["rows"][0]["session_id"] == child_a, again)


def actl_hint_and_pointer(cur):
    root = open_session(cur)
    parent = insert_child(cur, root)
    child_a = insert_child(cur, parent)
    child_b = insert_child(cur, parent)
    other = insert_child(cur, root)
    other_child = insert_child(cur, other)
    todo = u()
    cur.execute(
        "SELECT public.v13_child_pointer(%s, %s, public.v13_plan_map_root(%s), %s, 0)",
        (child_a, parent, child_a, todo))
    pointer_id = str(cur.fetchone()[0])
    cur.execute(
        "SELECT public.v13_child_pointer(%s, %s, public.v13_plan_map_root(%s), %s, 0)",
        (other_child, other, other_child, u()))
    cur.fetchone()
    cur.execute(
        "SELECT session_id::text, event_id::text, seq, payload "
        "FROM events WHERE event_id = %s",
        (pointer_id,))
    stored = cur.fetchone()
    direct = {}
    for sid in (child_a, child_b):
        cur.execute("SELECT public.v13_scheduler_hint(%s)", (sid,))
        direct[sid] = cur.fetchone()[0]
    for spec in (
        {"ids": [child_a, child_b]},
        {"ids": [child_a, child_b], "hint": False},
        {"ids": [child_a, child_b], "hint": "false"},
    ):
        window = probe_counter(cur)
        got = observe_direct(cur, parent, spec)
        check("hint omitted " + json.dumps(spec["hint"] if "hint" in spec else "absent"),
              got["hints"] == [] and calls_since(cur, window, "hint") == 0, got["hints"])
    for flag in (True, "true"):
        window = probe_counter(cur)
        got = observe_direct(cur, parent, {"ids": [child_b, child_a], "hint": flag})
        check(
            "hint objects " + str(flag),
            got["hints"] == [
                {"session_id": child_b, "hint": direct[child_b]},
                {"session_id": child_a, "hint": direct[child_a]},
            ],
            got["hints"])
        check("hint call count " + str(flag), calls_since(cur, window, "hint") == 2)
    window = probe_counter(cur)
    got = observe_direct(cur, parent, {"ids": child_a, "hint": False})
    check("actl_observe_no_pointer writer", calls_since(cur, window, "pointer") == 0)
    check(
        "pointer row",
        got["pointers"] == [{
            "session_id": stored[0],
            "event_id": stored[1],
            "seq": stored[2],
            "payload": as_obj(stored[3]),
        }],
        got["pointers"])
    other_only = observe_direct(cur, other, {"ids": other_child})
    check("other pointer not leaked into first", all(
        item["session_id"] != other_child for item in got["pointers"]))
    check("other pointer present", any(
        item["session_id"] == other_child for item in other_only["pointers"]), other_only)
    bare = insert_child(cur, parent)
    window = probe_counter(cur)
    none = observe_direct(cur, parent, {"ids": bare})
    check("no pointer placeholder", none["pointers"] == [])
    check("no writer on empty pointer", calls_since(cur, window, "pointer") == 0)


def actl_acl_closed(cur):
    sig = SIG
    check(
        "route execute",
        q1(cur, "SELECT has_function_privilege('v13_route', %s, 'EXECUTE')", (sig,)) is True)
    for role in ("public", "v13_recall", "v13_worker", "v13_resolve", "v13_spawn_owner"):
        check(
            role + " no execute",
            q1(cur, "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, sig,)) is False)
    root = open_session(cur)
    parent = insert_child(cur, root)
    child = insert_child(cur, parent)
    cur.execute("SET ROLE v13_route")
    got = observe_direct(cur, parent, {"ids": child, "hint": True})
    cur.execute("RESET ROLE")
    check("route authorized observe", got["ok"] is True and len(got["rows"]) == 1 and len(got["hints"]) == 1, got)
    cur.execute("SET ROLE v13_recall")
    fails_code(
        cur,
        "SELECT public.v13_agentctl_observe(%s::uuid, %s::jsonb)",
        (parent, json.dumps({"ids": child})),
        "42501",
        "recall 42501")
    cur.execute("RESET ROLE")


def actl_read_zero_write(cur):
    root = open_session(cur)
    parent = insert_child(cur, root)
    child = insert_child(cur, parent)
    before = snapshot_read_window(cur)
    first = observe_direct(cur, parent, {"ids": child, "hint": False})
    empty = observe_direct(cur, parent, {"ids": parent})
    bad = observe_direct(cur, parent, {"ids": "nope"})
    second = observe_direct(cur, parent, {"ids": child, "hint": False})
    after = snapshot_read_window(cur)
    check("actl_read_zero_write", before == after)
    check("repeat observe", first == second, (first, second))
    check("empty and shape in window", empty["ok"] is True and bad == SHAPE)


def actl_no_io(cur):
    body = q1(cur, "SELECT pg_get_functiondef(%s::regprocedure)", (SIG,))
    norm = re.sub(r"\s+", " ", body.lower())
    for token in BANNED:
        present = token in norm
        if token == "v13_claim":
            present = "v13_claim(" in norm or "v13_claim " in norm
        check("actl_no_io " + token, not present)


def actl_guard_closed(cur):
    check(
        "not named writer",
        q1(cur, "SELECT public.v13_named_sql_writer('v13_agentctl_observe')") is None)
    check(
        "spawn writer still ok",
        q1(cur, "SELECT public.v13_spawn_writer_ok('v13_spawn_subsession')") is True)
    fails_msg(
        cur,
        "INSERT INTO tools (name, description, kind, handler, param_spec, enabled) "
        "VALUES ('agentctl_missing', 'x', 'sql', 'v13_no_such_handler', '{}'::jsonb, true)",
        None,
        "not found",
        "missing handler rejected")


def actl_spawn_enabled(cur, when):
    row = q1(
        cur,
        "SELECT enabled FROM tools WHERE name = 'spawn_subsession'")
    check("actl_spawn_enabled_true " + when, row is True, row)


def arm_parse_guc(cur):
    cur.execute("SELECT set_config('typesafe.provider', 'mock', false)")
    cur.execute("SELECT set_config('typesafe.model', 'jev-mock', false)")
    cur.execute("SET track_functions = 'all'")


def actl_observe_routed(server):
    for hint in ("true", "false"):
        conn = connect(server)
        cur = conn.cursor()
        arm_parse_guc(cur)
        root, child = prepare_routed_case(cur, True)
        child_seq = q1(cur, "SELECT next_seq FROM sessions WHERE session_id = %s", (child,))
        parsed = parse_observe_case(cur, root, child, hint)
        window = probe_counter(cur)
        cur.execute(
            "UPDATE sessions SET context_active_revision = v13_context_required(session_id) "
            "WHERE session_id = %s",
            (root,))
        cur.execute("SELECT v13_advance(%s, %s::jsonb)", (root, json.dumps(parsed)))
        status = cur.fetchone()[0]
        check("advance " + hint, status == "progressed", status)
        cur.execute(
            """
            SELECT payload
              FROM events
             WHERE session_id = %s AND type = 'turn/route'
             ORDER BY seq DESC LIMIT 1
            """,
            (root,))
        route = as_obj(cur.fetchone()[0])
        check("route action " + hint, route.get("action") == "sql" and route.get("tool") == "agentctl_observe", route)
        cur.execute(
            """
            SELECT status, error, request, result
              FROM effects
             WHERE session_id = %s AND tool_name = 'agentctl_observe'
            """,
            (root,))
        rows = cur.fetchall()
        check("one tool effect " + hint, len(rows) == 1, rows)
        effect_status, error, request, result = rows[0]
        request = as_obj(request)
        result = as_obj(result)
        check("effect succeeded " + hint, effect_status == "succeeded" and error is None, effect_status)
        params = request["params"]
        check("params uuid text " + hint, params.get("ids") == child and params.get("hint") == hint, params)
        check("result sees child " + hint, result["rows"][0]["session_id"] == child, result)
        cur.execute(
            """
            SELECT payload
              FROM events
             WHERE session_id = %s AND type = 'tool/result'
             ORDER BY seq DESC LIMIT 1
            """,
            (root,))
        tool_result = as_obj(cur.fetchone()[0])
        check("tool result matches " + hint, as_obj(tool_result["result"]) == result, tool_result)
        overrides = q1(
            cur,
            "SELECT count(*) FROM events WHERE session_id = %s AND type = 'goal/override'",
            (root,))
        humans = q1(
            cur,
            "SELECT count(*) FROM effects WHERE session_id = %s AND kind = 'human'",
            (root,))
        pointers = q1(
            cur,
            "SELECT count(*) FROM events WHERE session_id = %s AND type = 'workflow/pointer'",
            (child,))
        after_seq = q1(cur, "SELECT next_seq FROM sessions WHERE session_id = %s", (child,))
        check("one override " + hint, overrides == 1, overrides)
        check("no human " + hint, humans == 0, humans)
        check("no new pointer " + hint, pointers == 0, pointers)
        check("child seq unchanged " + hint, after_seq == child_seq, (child_seq, after_seq))
        check("handler called " + hint, calls_since(cur, window, "wrap") >= 1)
        conn.close()
    conn = connect(server)
    cur = conn.cursor()
    arm_parse_guc(cur)
    root, child = prepare_routed_case(cur, False)
    parsed = parse_observe_case(cur, root, child, "false")
    window = probe_counter(cur)
    cur.execute(
        "UPDATE sessions SET context_active_revision = v13_context_required(session_id) "
        "WHERE session_id = %s",
        (root,))
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (root, json.dumps(parsed)))
    status = cur.fetchone()[0]
    check("actl_routed_without_override waiting", status == "waiting", status)
    reason = q1(
        cur,
        "SELECT request->>'reason' FROM effects "
        "WHERE session_id = %s AND kind = 'human' AND status = 'ready'",
        (root,))
    check("triage_fail_closed", reason == "triage_fail_closed", reason)
    tools = q1(
        cur,
        "SELECT count(*) FROM effects WHERE session_id = %s AND tool_name = 'agentctl_observe'",
        (root,))
    check("handler not called", calls_since(cur, window, "wrap") == 0 and tools == 0, tools)
    conn.close()
    conn = connect(server)
    cur = conn.cursor()
    arm_parse_guc(cur)
    root, child = prepare_routed_case(cur, True)
    parsed = parse_observe_case(cur, root, "not-a-uuid", "false")
    window = probe_counter(cur)
    cur.execute(
        "UPDATE sessions SET context_active_revision = v13_context_required(session_id) "
        "WHERE session_id = %s",
        (root,))
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (root, json.dumps(parsed)))
    status = cur.fetchone()[0]
    check("actl_shape_routed progressed", status == "progressed", status)
    cur.execute(
        """
        SELECT status, result
          FROM effects
         WHERE session_id = %s AND tool_name = 'agentctl_observe'
        """,
        (root,))
    effect_status, result = cur.fetchone()
    check("shape effect succeeded", effect_status == "succeeded" and as_obj(result) == SHAPE, result)
    check("shape routed no observe", calls_since(cur, window, "observe") == 0)
    check("shape routed no hint", calls_since(cur, window, "hint") == 0)
    conn.close()


def main() -> int:
    r0_source_scope()
    check("load append", '"agentctl": 40' in (AGENT_ROOT / "v13/load.py").read_text())
    if setup_db() != 0:
        return 1
    server = get_server()
    conn = connect(server)
    try:
        cur = conn.cursor()
        cur.execute("SET track_functions = 'all'")
        cur.execute("SELECT set_config('typesafe.provider', 'mock', false)")
        cur.execute("SELECT set_config('typesafe.model', 'jev-mock', false)")
        before_fns = fn_rows(cur)
        before_tools = tool_rows(cur)
        before_rels = rel_rows(cur)
        cur.execute("SELECT revision, candidate_generation_revision FROM v13_tools_meta")
        before_meta = cur.fetchone()
        cur.execute("SELECT count(*) FROM events")
        before_events = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM effects")
        before_effects = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM v13_policies")
        before_policies = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM v13_route_policies")
        before_routes = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM thresholds")
        before_thresholds = cur.fetchone()[0]
        conn.commit()
        run_psql(server, DB, SQL)
        after_fns = fn_rows(cur)
        added = set(after_fns) - set(before_fns)
        check("one new function", added == {IDENT}, added)
        for sig, row in before_fns.items():
            check("function unchanged " + sig, after_fns[sig] == row)
        check(
            "wrapper stable invoker",
            after_fns[IDENT][4] == "s" and after_fns[IDENT][2] is False,
            after_fns[IDENT])
        after_tools = tool_rows(cur)
        cur.execute("SELECT revision, candidate_generation_revision FROM v13_tools_meta")
        after_meta = cur.fetchone()
        actl_catalog_rows(cur, before_tools, after_tools, before_meta, after_meta)
        check("relations unchanged", rel_rows(cur) == before_rels)
        cur.execute("SELECT count(*) FROM events")
        check("no install events", cur.fetchone()[0] == before_events)
        cur.execute("SELECT count(*) FROM effects")
        check("no install effects", cur.fetchone()[0] == before_effects)
        cur.execute("SELECT count(*) FROM v13_policies")
        check("policies unchanged", cur.fetchone()[0] == before_policies)
        cur.execute("SELECT count(*) FROM v13_route_policies")
        check("route policies unchanged", cur.fetchone()[0] == before_routes)
        cur.execute("SELECT count(*) FROM thresholds")
        check("thresholds unchanged", cur.fetchone()[0] == before_thresholds)
        check(
            "no controller",
            q1(cur, "SELECT count(*) FROM v13_route_policies WHERE policy_name = 'controller'") == 0)
        actl_spawn_enabled(cur, "after install")
        actl_no_io(cur)
        actl_guard_closed(cur)
        freeze_probe_policy(cur)
        conn.commit()
        cur.execute("SET track_functions = 'all'")
        parent = open_session(cur)
        child = insert_child(cur, parent)
        actl_shape_closed(cur, parent)
        one = u()
        listed = observe_direct(cur, parent, {"ids": [one]})
        single = observe_direct(cur, parent, {"ids": one})
        check("string matches array", single == listed)
        actl_actor_gate(cur)
        actl_hint_and_pointer(cur)
        actl_acl_closed(cur)
        actl_read_zero_write(cur)
        actl_spawn_enabled(cur, "after behavior")
        conn.commit()
        actl_observe_routed(server)
        print(f"[ok] {N} checks")
        return 0
    finally:
        conn.close()
        if setup_mod.CREATED:
            try:
                run_psql(server, "postgres", f'DROP DATABASE "{DB}" WITH (FORCE);')
                setup_mod.CREATED = False
                print("[dropped]", DB)
            except Exception as exc:
                print("[cleanup-fail]", exc)
                raise SystemExit(1)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[FAIL] {exc}")
        raise SystemExit(1)
