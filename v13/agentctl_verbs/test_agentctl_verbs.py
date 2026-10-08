"""Stage 41 gate: agentctl steer, answer, cancel.

Run: UV_FROZEN=1 uv run python v13/agentctl_verbs/test_agentctl_verbs.py

D-3 body consumption is openly unclosed. CONSUMER stays None.
Exit 0 means the producer is delivered and the body was not consumed.
Do not set CONSUMER. Do not claim D-3 is closed.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v13.agentctl_verbs.setup_db import DB, main as setup_db
import v13.agentctl_verbs.setup_db as setup_mod
from v13.load import run_psql
from v13.loop.test_loop import mock_from_needed, set_mock
from v13.plan_arm.test_plan_arm import r0_source_scope

N = 0
SQL = (ROOT / "v13_agentctl_verbs.sql").read_text()
STAGE40_REV = "a19aefc"
SPAWN_BASE = "fb295ac6c7459bb98dac57e37883af549d2d8a4c"
PHASE_D = "78e77c710bf06a0a1c771b822a3837c5db4c66d0"
CONSUMER = None
WRAPPERS = (
    "public.v13_agentctl_steer(p_sid uuid, p_spec jsonb)",
    "public.v13_agentctl_answer(p_sid uuid, p_spec jsonb)",
    "public.v13_agentctl_cancel(p_sid uuid, p_spec jsonb)",
)
FNS = {
    "steer": "public.v13_agentctl_steer(uuid,jsonb)",
    "answer": "public.v13_agentctl_answer(uuid,jsonb)",
    "cancel": "public.v13_agentctl_cancel(uuid,jsonb)",
    "append": "public.v13_append_event(uuid,uuid,text,jsonb,uuid)",
    "complete": "public.v13_complete(uuid,uuid,integer,bigint,text,jsonb)",
    "cancel2": "public.v13_cancel(uuid,uuid)",
    "auth": "public.v13_control_authorized(uuid,uuid)",
}
STEER_JSON = {"mutating": False, "write_targets": ["events", "sessions"]}
ANSWER_JSON = {"mutating": False, "write_targets": ["effects", "events", "sessions"]}
CANCEL_JSON = {"mutating": False, "write_targets": ["effects", "events", "sessions"]}
SPAWN_JSON = {
    "mutating": False,
    "write_targets": ["artifacts", "events", "latches", "sessions"],
}
SURFACE = {
    "schema_version": 1,
    "route_policy_name": "controller",
    "route_policy_version": 1,
    "tools": [
        "agentctl_observe",
        "agentctl_steer",
        "agentctl_answer",
        "agentctl_cancel",
    ],
}
TOOL_TEXT = {
    "agentctl_steer": {
        "description": "Inject steering text into an authorized child session.",
        "handler": "v13_agentctl_steer",
        "spec": {
            "target": {
                "question": "Which child session UUID should receive steering text?",
                "stated": "Does the user specify the child session UUID to steer?",
            },
            "text": {
                "question": "What steering text should be injected?",
                "stated": "Does the user specify the steering text?",
            },
        },
    },
    "agentctl_answer": {
        "description": "Answer a ready human interaction in an authorized child session.",
        "handler": "v13_agentctl_answer",
        "spec": {
            "target": {
                "question": "Which child session UUID contains the human interaction?",
                "stated": "Does the user specify the child session UUID to answer?",
            },
            "effect_id": {
                "question": "Which human effect UUID should be answered?",
                "stated": "Does the user specify the human effect UUID to answer?",
            },
            "response": {
                "question": "What response should be submitted to the human interaction?",
                "stated": "Does the user specify the response to the human interaction?",
            },
        },
    },
    "agentctl_cancel": {
        "description": "Request cancellation of an authorized child session.",
        "handler": "v13_agentctl_cancel",
        "spec": {
            "target": {
                "question": "Which child session UUID should be cancelled?",
                "stated": "Does the user specify the child session UUID to cancel?",
            },
        },
    },
}
NON_CONSUMERS = (
    "v13/control/test_control.py:516-524",
    "demo_v13/parity/g_steer.py:98",
    "v13/plan_contract/test_plan_contract.py:459-460",
    "v13/resolve/v13_resolve.sql canonical state",
    "v13/envelope/v13_envelope.sql:519,551",
    "v13/memory/v13_memory.sql:113-127",
    "v13/triage/v13_triage.sql:161-164",
    "v13/observe/v13_observe.sql:130-171 v13_session_log",
    "v13_triage_steer name collision",
)
BANNED = (
    "dblink", "pg_net", "copy program", "lo_import", "lo_export",
    "pg_read_file", "pg_write_file", "v13_claim", "13002", "13003",
)
STAGE40 = (
    "v13/agentctl/v13_agentctl.sql",
    "v13/agentctl/setup_db.py",
    "v13/agentctl/test_agentctl.py",
    "v13/agentctl/README.md",
)
CHAIN = []


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


def u():
    return str(uuid.uuid4())


def connect(server):
    conn = psycopg2.connect(server.get_uri(DB))
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute("SET track_functions = 'all'")
    cur.execute("SELECT set_config('typesafe.provider', 'mock', false)")
    cur.execute("SELECT set_config('typesafe.model', 'jev-mock', false)")
    cur.close()
    return conn


def q1(cur, sql, params=None):
    cur.execute(sql, params)
    row = cur.fetchone()
    return None if row is None else row[0]


def choice(value, confidence=0.9):
    return {
        "type": "choice",
        "choice": value,
        "probabilities": {value: confidence},
        "confidence": confidence,
    }


def open_session(cur, policy=None):
    spec = {} if policy is None else {
        "route_policy_name": policy[0],
        "version": policy[1],
    }
    cur.execute("SELECT v13_open_session(%s::jsonb)", (json.dumps(spec),))
    return str(cur.fetchone()[0])


def append_user(cur, sid, text="hello"):
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (sid, u(), json.dumps({"text": text})))
    return cur.fetchone()[0]


def spawn_one(cur, parent, task="child task"):
    cur.execute(
        "SELECT v13_spawn_subsession(%s, %s::jsonb)",
        (parent, json.dumps({
            "schema_version": 1,
            "children": [{"tool_call_id": "tc-" + u()[:8], "task": task}],
        })))
    spawned = as_obj(cur.fetchone()[0])
    check(
        "spawn return keys",
        set(spawned) == {"replay_kind", "parent_session_id", "children", "reservation"},
        list(spawned))
    return spawned


def enqueue_human(cur, sid, ref):
    cur.execute(
        "SELECT v13_enqueue_effect(%s, 'human', %s::jsonb)",
        (sid, json.dumps({"schema_version": 1, "interaction_ref": ref})))
    return str(cur.fetchone()[0])


def enqueue_human_raw(cur, sid, request):
    cur.execute(
        "SELECT v13_enqueue_effect(%s, 'human', %s::jsonb)",
        (sid, json.dumps(request)))
    return str(cur.fetchone()[0])


def shrink_catalog(cur, keep):
    cur.execute(
        "UPDATE tools SET enabled = false "
        "WHERE enabled AND kind IN ('sql', 'tool') AND NOT (name = ANY(%s))",
        (list(keep),))


def submit_override(cur, sid):
    cur.execute(
        "SELECT v13_submit_override(%s, %s::jsonb)",
        (sid, json.dumps({
            "intent": "direct",
            "reason": "",
            "schema_version": 1,
            "source_principal": "operator",
        })))
    cur.fetchone()


def controller_pair(cur, task="child task"):
    parent = open_session(cur, ("controller", 1))
    append_user(cur, parent, "parent")
    child = spawn_one(cur, parent, task)["children"][0]["session_id"]
    return parent, child


def fn_rows(cur):
    cur.execute(
        """
        SELECT n.nspname || '.' || p.proname
                 || '(' || pg_get_function_identity_arguments(p.oid) || ')',
               pg_get_functiondef(p.oid),
               r.rolname,
               p.prosecdef,
               p.proacl::text,
               p.provolatile,
               p.proconfig::text
          FROM pg_proc p
          JOIN pg_namespace n ON n.oid = p.pronamespace
          JOIN pg_roles r ON r.oid = p.proowner
         WHERE n.nspname = 'public'
           AND (p.proname LIKE 'v13\\_%' OR p.proname = 'v_goal_tree')
         ORDER BY 1
        """)
    rows = {}
    for sig, body, owner, secdef, acl, vol, config in cur.fetchall():
        rows[sig] = (
            hashlib.sha256(body.encode()).hexdigest(),
            owner,
            secdef,
            acl,
            vol,
            config,
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
        "SELECT indexname FROM pg_indexes WHERE schemaname = 'public' ORDER BY 1")
    indexes = [row[0] for row in cur.fetchall()]
    return rels, cols, triggers, indexes


def snapshot_window(cur):
    cur.execute("SELECT * FROM sessions ORDER BY session_id")
    sessions = cur.fetchall()
    cur.execute(
        "SELECT event_id::text, session_id::text, seq, type, payload::text "
        "FROM events ORDER BY session_id, seq, event_id")
    events = cur.fetchall()
    cur.execute(
        """
        SELECT effect_id::text, session_id::text, status, kind, attempt_no, fence,
               lease_owner, lease_until, result::text, error::text
          FROM effects
         ORDER BY effect_id
        """)
    effects = cur.fetchall()
    artifacts = q1(cur, "SELECT count(*) FROM artifacts")
    latches = q1(cur, "SELECT count(*) FROM latches")
    return {
        "sessions": sessions,
        "events": events,
        "effects": effects,
        "artifacts": artifacts,
        "latches": latches,
    }


def snapshot_target(cur, sid):
    cur.execute("SELECT * FROM sessions WHERE session_id = %s", (sid,))
    sessions = cur.fetchall()
    cur.execute(
        "SELECT event_id::text, session_id::text, seq, type, payload::text "
        "FROM events WHERE session_id = %s ORDER BY seq, event_id",
        (sid,))
    events = cur.fetchall()
    cur.execute(
        """
        SELECT effect_id::text, status, kind, attempt_no, fence, lease_owner,
               lease_until, result::text, error::text
          FROM effects
         WHERE session_id = %s
         ORDER BY effect_id
        """,
        (sid,))
    effects = cur.fetchall()
    return {
        "sessions": sessions,
        "events": events,
        "effects": effects,
        "artifacts": q1(cur, "SELECT count(*) FROM artifacts"),
        "latches": q1(cur, "SELECT count(*) FROM latches"),
    }


def changed_names(before, after):
    names = []
    for key in ("sessions", "events", "effects", "artifacts", "latches"):
        if before[key] != after[key]:
            names.append(key)
    return sorted(names)


def named_json(cur, handler):
    return as_obj(q1(cur, "SELECT public.v13_named_sql_writer(%s)", (handler,)))


def call_verb(cur, fn, actor, spec):
    cur.execute(
        f"SELECT public.{fn}(%s::uuid, %s::jsonb)",
        (actor, json.dumps(spec)))
    return as_obj(cur.fetchone()[0])


def spec_sql(spec):
    if spec is None:
        return "NULL::jsonb"
    if spec == "json-null":
        return "'null'::jsonb"
    return "'" + json.dumps(spec).replace("'", "''") + "'::jsonb"


def measured_reject(cur, fn, actor, spec, needle, label, target=None, effect=None):
    before_seq = before_steer = before_effect = None
    if target:
        before_seq = q1(cur, "SELECT next_seq FROM sessions WHERE session_id = %s", (target,))
        before_steer = q1(
            cur,
            "SELECT count(*) FROM events WHERE session_id = %s AND type = 'steer/injected'",
            (target,))
    if effect:
        before_effect = q1(cur, "SELECT status FROM effects WHERE effect_id = %s", (effect,))
    if not re.fullmatch(r"[0-9a-f-]{36}", actor):
        raise AssertionError("actor literal")
    if fn not in ("v13_agentctl_steer", "v13_agentctl_answer", "v13_agentctl_cancel"):
        raise AssertionError(fn)
    cur.execute(
        f"""
        DO $trap$
        DECLARE
          v_msg text := '';
          v_auth oid := 'public.v13_control_authorized(uuid,uuid)'::regprocedure;
          v_append oid := 'public.v13_append_event(uuid,uuid,text,jsonb,uuid)'::regprocedure;
          v_complete oid := 'public.v13_complete(uuid,uuid,integer,bigint,text,jsonb)'::regprocedure;
          v_cancel oid := 'public.v13_cancel(uuid,uuid)'::regprocedure;
          v_b bigint;
          v_a bigint;
          v_append_b bigint;
          v_complete_b bigint;
          v_cancel_b bigint;
          v_append_d bigint;
          v_complete_d bigint;
          v_cancel_d bigint;
        BEGIN
          SELECT coalesce(sum(calls), 0) INTO v_b
            FROM pg_stat_xact_user_functions WHERE funcid = v_auth;
          PERFORM public.v13_control_authorized(NULL::uuid, NULL::uuid);
          SELECT coalesce(sum(calls), 0) INTO v_a
            FROM pg_stat_xact_user_functions WHERE funcid = v_auth;
          IF v_a - v_b < 1 THEN
            RAISE EXCEPTION 'environment block: track_functions';
          END IF;
          SELECT coalesce(sum(calls), 0) INTO v_append_b
            FROM pg_stat_xact_user_functions WHERE funcid = v_append;
          SELECT coalesce(sum(calls), 0) INTO v_complete_b
            FROM pg_stat_xact_user_functions WHERE funcid = v_complete;
          SELECT coalesce(sum(calls), 0) INTO v_cancel_b
            FROM pg_stat_xact_user_functions WHERE funcid = v_cancel;
          BEGIN
            PERFORM public.{fn}('{actor}'::uuid, {spec_sql(spec)});
            v_msg := 'no-error';
          EXCEPTION WHEN OTHERS THEN
            GET STACKED DIAGNOSTICS v_msg = MESSAGE_TEXT;
          END;
          SELECT coalesce(sum(calls), 0) - v_append_b INTO v_append_d
            FROM pg_stat_xact_user_functions WHERE funcid = v_append;
          SELECT coalesce(sum(calls), 0) - v_complete_b INTO v_complete_d
            FROM pg_stat_xact_user_functions WHERE funcid = v_complete;
          SELECT coalesce(sum(calls), 0) - v_cancel_b INTO v_cancel_d
            FROM pg_stat_xact_user_functions WHERE funcid = v_cancel;
          CREATE TEMP TABLE IF NOT EXISTS actl_trap (
            message text, append_d bigint, complete_d bigint, cancel_d bigint
          ) ON COMMIT DROP;
          DELETE FROM actl_trap;
          INSERT INTO actl_trap VALUES (v_msg, v_append_d, v_complete_d, v_cancel_d);
        END
        $trap$
        """)
    cur.execute("SELECT message, append_d, complete_d, cancel_d FROM actl_trap")
    msg, append_d, complete_d, cancel_d = cur.fetchone()
    check(label, needle in (msg or ""), msg)
    check(label + " append", append_d == 0, append_d)
    check(label + " complete", complete_d == 0, complete_d)
    check(label + " cancel", cancel_d == 0, cancel_d)
    if target:
        check(
            label + " seq",
            q1(cur, "SELECT next_seq FROM sessions WHERE session_id = %s", (target,)) == before_seq)
        check(
            label + " steer",
            q1(cur,
               "SELECT count(*) FROM events WHERE session_id = %s AND type = 'steer/injected'",
               (target,)) == before_steer)
    if effect:
        check(
            label + " effect",
            q1(cur, "SELECT status FROM effects WHERE effect_id = %s", (effect,)) == before_effect)


def function_def(cur, sig):
    return q1(cur, "SELECT pg_get_functiondef(%s::regprocedure)", (sig,))


def spawn_row(cur):
    cur.execute(
        "SELECT name, description, kind, handler, param_spec::text, enabled "
        "FROM tools WHERE name = 'spawn_subsession'")
    return cur.fetchone()


def actl_spawn_enabled_true(cur, when, baseline=None):
    row = spawn_row(cur)
    check("actl_spawn_enabled_true " + when, row is not None and row[5] is True, row)
    if baseline is not None:
        check("spawn row unchanged " + when, row == baseline, row)
    return row


def actl_install_delta(cur, before_fns, after_fns, before_rels, before_events, before_effects):
    added = set(after_fns) - set(before_fns)
    check("three new functions", added == set(WRAPPERS), added)
    predicates = [
        sig for sig in before_fns
        if sig.startswith("public.v13_named_sql_writer(")
        or sig.startswith("public.v13_spawn_writer_ok(")]
    check("two predicates", len(predicates) == 2, predicates)
    for sig, row in before_fns.items():
        if sig in predicates:
            check(
                "predicate attrs " + sig,
                after_fns[sig][1:] == row[1:] and after_fns[sig][0] != row[0],
                (row[1:], after_fns[sig][1:]))
        else:
            check("function unchanged " + sig, after_fns[sig] == row)
    for sig in WRAPPERS:
        row = after_fns[sig]
        check("wrapper owner " + sig, row[1] == "v13_spawn_owner", row[1])
        check("wrapper definer " + sig, row[2] is True and row[4] == "v", (row[2], row[4]))
    check("relations unchanged", rel_rows(cur) == before_rels)
    check("no install events", q1(cur, "SELECT count(*) FROM events") == before_events)
    check("no install effects", q1(cur, "SELECT count(*) FROM effects") == before_effects)


def actl_catalog_rows(cur, before_tools, after_tools, before_meta, after_meta):
    before = {row[0]: row for row in before_tools}
    after = {row[0]: row for row in after_tools}
    added = set(after) - set(before)
    check("actl_catalog_rows", added == set(TOOL_TEXT), added)
    for name, row in before.items():
        check("tool unchanged " + name, after[name] == row)
    for name, expect in TOOL_TEXT.items():
        got_name, description, kind, handler, spec, enabled = after[name]
        parsed = json.loads(spec)
        check(
            "catalog " + name,
            kind == "sql" and handler == expect["handler"] and enabled is True
            and description == expect["description"] and parsed == expect["spec"],
            (description, kind, handler, parsed, enabled))
        check("no options " + name, all("options" not in parsed[key] for key in parsed))
    check("revision plus 3", after_meta[0] == before_meta[0] + 3, (before_meta, after_meta))
    check("candidate revision unchanged", after_meta[1] == before_meta[1], after_meta)
    catalog = as_obj(q1(cur, "SELECT v13_tools_catalog_frozen()"))
    names = {item["name"] for item in catalog}
    check(
        "frozen catalog verbs",
        {"agentctl_steer", "agentctl_answer", "agentctl_cancel", "agentctl_observe"} <= names,
        names)


def actl_controller_policy(cur, before_default, before_policies, before_routes):
    state = q1(
        cur,
        "SELECT state FROM v13_route_policies "
        "WHERE policy_name = 'controller' AND policy_version = 1")
    check("controller frozen", state == "frozen", state)
    added_routes = q1(cur, "SELECT count(*) FROM v13_route_policies") - before_routes
    check("one new route policy", added_routes == 1, added_routes)
    cur.execute(
        """
        SELECT signal, band_no, lo, hi, action
          FROM thresholds
         WHERE policy_name = 'default' AND policy_version = 2
         ORDER BY signal, band_no
        """)
    default_now = cur.fetchall()
    check("default/2 unchanged", default_now == before_default)
    cur.execute(
        """
        SELECT signal, band_no, lo, hi, action
          FROM thresholds
         WHERE policy_name = 'controller' AND policy_version = 1
         ORDER BY signal, band_no
        """)
    controller = cur.fetchall()
    extra = [row for row in controller if row not in set(default_now)]
    check("sixteen bands", len(extra) == 16 and len(controller) == len(default_now) + 16, len(extra))
    check("no triage band", all(row[0] != "triage" for row in controller))
    added_policies = q1(cur, "SELECT count(*) FROM v13_policies") - before_policies
    check("one new policy", added_policies == 1, added_policies)
    cur.execute(
        "SELECT version, active, value FROM v13_policies WHERE name = 'controller_surface'")
    version, active, value = cur.fetchone()
    got = as_obj(value)
    check(
        "controller_surface",
        version == 1 and active is True and got == SURFACE,
        got)


def actl_frozen_unchanged():
    for rev in (SPAWN_BASE, PHASE_D, STAGE40_REV):
        subprocess.check_call(["git", "cat-file", "-e", rev + "^{commit}"], cwd=AGENT_ROOT)
    old = subprocess.check_output(
        ["git", "show", SPAWN_BASE + ":v13/spawn/v13_spawn.sql"], cwd=AGENT_ROOT)
    check("spawn bytes", (AGENT_ROOT / "v13/spawn/v13_spawn.sql").read_bytes() == old)
    for path in STAGE40:
        committed = subprocess.check_output(
            ["git", "show", STAGE40_REV + ":" + path], cwd=AGENT_ROOT)
        check("a19aefc " + path, (AGENT_ROOT / path).read_bytes() == committed)


def actl_guard_closed(cur):
    check("observe named null", named_json(cur, "v13_agentctl_observe") is None)
    check("observe writer false", q1(cur, "SELECT public.v13_spawn_writer_ok('v13_agentctl_observe')") is False)
    for handler, expect in (
        ("v13_spawn_subsession", SPAWN_JSON),
        ("public.v13_spawn_subsession", SPAWN_JSON),
        ("v13_agentctl_steer", STEER_JSON),
        ("public.v13_agentctl_steer", STEER_JSON),
        ("v13_agentctl_answer", ANSWER_JSON),
        ("public.v13_agentctl_answer", ANSWER_JSON),
        ("v13_agentctl_cancel", CANCEL_JSON),
        ("public.v13_agentctl_cancel", CANCEL_JSON),
    ):
        check("named " + handler, named_json(cur, handler) == expect, named_json(cur, handler))
        check(
            "writer_ok " + handler,
            q1(cur, "SELECT public.v13_spawn_writer_ok(%s)", (handler,)) is True)
    body = function_def(cur, "public.v13_spawn_writer_ok(text)")
    for token in (
        "p.provolatile = 'v'", "p.prosecdef", "v13_spawn_owner",
        "search_path=pg_catalog,public", "aclexplode", "has_function_privilege",
        "position('dblink'", "position('pg_net'", "position('copy program'",
        "position('lo_import'", "position('lo_export'",
        "position('pg_read_file'", "position('pg_write_file'",
        '["artifacts","events","latches","sessions"]',
        '["events","sessions"]',
        '["effects","events","sessions"]',
    ):
        check("writer conjunction " + token, token in body)
    variants = {
        "v13_verbs_probe_named": """
            CREATE FUNCTION public.v13_verbs_probe_named(p_sid uuid, p_spec jsonb)
            RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER
            SET search_path = pg_catalog, public AS $probe$
            BEGIN RETURN '{}'::jsonb; END $probe$;
            ALTER FUNCTION public.v13_verbs_probe_named(uuid, jsonb) OWNER TO v13_spawn_owner;
            REVOKE EXECUTE ON FUNCTION public.v13_verbs_probe_named(uuid, jsonb) FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION public.v13_verbs_probe_named(uuid, jsonb) TO v13_route;
        """,
        "v13_verbs_probe_banned": """
            CREATE FUNCTION public.v13_verbs_probe_banned(p_sid uuid, p_spec jsonb)
            RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER
            SET search_path = pg_catalog, public AS $probe$
            BEGIN
              RETURN '{}'::jsonb; -- dblink
            END
            $probe$;
            ALTER FUNCTION public.v13_verbs_probe_banned(uuid, jsonb) OWNER TO v13_spawn_owner;
            REVOKE EXECUTE ON FUNCTION public.v13_verbs_probe_banned(uuid, jsonb) FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION public.v13_verbs_probe_banned(uuid, jsonb) TO v13_route;
        """,
        "v13_verbs_probe_owner": """
            CREATE FUNCTION public.v13_verbs_probe_owner(p_sid uuid, p_spec jsonb)
            RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER
            SET search_path = pg_catalog, public AS $probe$
            BEGIN RETURN '{}'::jsonb; END $probe$;
            REVOKE EXECUTE ON FUNCTION public.v13_verbs_probe_owner(uuid, jsonb) FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION public.v13_verbs_probe_owner(uuid, jsonb) TO v13_route;
        """,
        "v13_verbs_probe_vol": """
            CREATE FUNCTION public.v13_verbs_probe_vol(p_sid uuid, p_spec jsonb)
            RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
            SET search_path = pg_catalog, public AS $probe$
            BEGIN RETURN '{}'::jsonb; END $probe$;
            ALTER FUNCTION public.v13_verbs_probe_vol(uuid, jsonb) OWNER TO v13_spawn_owner;
            REVOKE EXECUTE ON FUNCTION public.v13_verbs_probe_vol(uuid, jsonb) FROM PUBLIC;
        """,
        "v13_verbs_probe_config": """
            CREATE FUNCTION public.v13_verbs_probe_config(p_sid uuid, p_spec jsonb)
            RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER AS $probe$
            BEGIN RETURN '{}'::jsonb; END $probe$;
            ALTER FUNCTION public.v13_verbs_probe_config(uuid, jsonb) OWNER TO v13_spawn_owner;
            REVOKE EXECUTE ON FUNCTION public.v13_verbs_probe_config(uuid, jsonb) FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION public.v13_verbs_probe_config(uuid, jsonb) TO v13_route;
        """,
        "v13_verbs_probe_public": """
            CREATE FUNCTION public.v13_verbs_probe_public(p_sid uuid, p_spec jsonb)
            RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER
            SET search_path = pg_catalog, public AS $probe$
            BEGIN RETURN '{}'::jsonb; END $probe$;
            ALTER FUNCTION public.v13_verbs_probe_public(uuid, jsonb) OWNER TO v13_spawn_owner;
            GRANT EXECUTE ON FUNCTION public.v13_verbs_probe_public(uuid, jsonb) TO PUBLIC;
            GRANT EXECUTE ON FUNCTION public.v13_verbs_probe_public(uuid, jsonb) TO v13_route;
        """,
        "v13_verbs_probe_route": """
            CREATE FUNCTION public.v13_verbs_probe_route(p_sid uuid, p_spec jsonb)
            RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER
            SET search_path = pg_catalog, public AS $probe$
            BEGIN RETURN '{}'::jsonb; END $probe$;
            ALTER FUNCTION public.v13_verbs_probe_route(uuid, jsonb) OWNER TO v13_spawn_owner;
            REVOKE EXECUTE ON FUNCTION public.v13_verbs_probe_route(uuid, jsonb) FROM PUBLIC;
        """,
        "v13_verbs_probe_sig": """
            CREATE FUNCTION public.v13_verbs_probe_sig(p_sid uuid)
            RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER
            SET search_path = pg_catalog, public AS $probe$
            BEGIN RETURN '{}'::jsonb; END $probe$;
            ALTER FUNCTION public.v13_verbs_probe_sig(uuid) OWNER TO v13_spawn_owner;
            REVOKE EXECUTE ON FUNCTION public.v13_verbs_probe_sig(uuid) FROM PUBLIC;
            GRANT EXECUTE ON FUNCTION public.v13_verbs_probe_sig(uuid) TO v13_route;
        """,
    }
    revision = q1(cur, "SELECT revision FROM v13_tools_meta")
    for name, ddl in variants.items():
        cur.execute("SAVEPOINT probe")
        cur.execute(ddl)
        ok = q1(cur, "SELECT public.v13_spawn_writer_ok(%s)", (name,))
        rejected = False
        cur.execute("SAVEPOINT ins")
        try:
            cur.execute(
                "INSERT INTO tools (name, description, kind, handler, param_spec, enabled) "
                "VALUES (%s, 'x', 'sql', %s, '{}'::jsonb, true)",
                ("zz_" + name[-12:], name))
        except psycopg2.Error:
            rejected = True
            cur.execute("ROLLBACK TO SAVEPOINT ins")
        cur.execute("ROLLBACK TO SAVEPOINT probe")
        check(name + " writer_ok false", ok is False, ok)
        check(name + " insert rejected", rejected)
    check("probe revision unchanged", q1(cur, "SELECT revision FROM v13_tools_meta") == revision)


def actl_no_io(cur):
    bodies = {
        "steer": function_def(cur, FNS["steer"]),
        "answer": function_def(cur, FNS["answer"]),
        "cancel": function_def(cur, FNS["cancel"]),
    }
    for name, body in bodies.items():
        norm = re.sub(r"\s+", " ", body.lower())
        for token in BANNED:
            present = token in norm
            if token == "v13_claim":
                present = "v13_claim(" in norm or "v13_claim " in norm
            check("actl_no_io " + name + " " + token, not present)
        check("actl_no_io " + name + " execute", re.search(r"\bEXECUTE\b", body) is None)
        check("actl_no_io " + name + " when", re.search(r"EXCEPTION\s+WHEN", body) is None)
        check("actl_no_io " + name + " raise", "RAISE EXCEPTION" in body)
    check("steer append", "v13_append_event" in bodies["steer"])
    check("answer no append", "v13_append_event" not in bodies["answer"])
    check("cancel no append", "v13_append_event" not in bodies["cancel"])
    check("cancel no closeout", "v13_closeout" not in bodies["cancel"])


def actl_owner_not_operator(cur):
    check(
        "rolsuper false",
        q1(cur, "SELECT rolsuper FROM pg_roles WHERE rolname = 'v13_spawn_owner'") is False)
    check(
        "no route usage",
        q1(cur, "SELECT pg_has_role('v13_spawn_owner', 'v13_route', 'USAGE')") is False)
    cur.execute("SET ROLE v13_spawn_owner")
    check("operator false", q1(cur, "SELECT public.v13_control_operator()") is False)
    cur.execute("RESET ROLE")
    check("no route grant", "GRANT v13_route TO v13_spawn_owner" not in SQL)


def actl_acl_closed(cur):
    for key in ("steer", "answer", "cancel"):
        sig = FNS[key]
        check(
            key + " route execute",
            q1(cur, "SELECT has_function_privilege('v13_route', %s, 'EXECUTE')", (sig,)) is True)
        for role in ("public", "v13_recall", "v13_worker", "v13_resolve"):
            check(
                key + " " + role + " no execute",
                q1(cur, "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, sig,)) is False)
    parent, child = controller_pair(cur)
    cur.execute("SET ROLE v13_route")
    got = call_verb(cur, "v13_agentctl_steer", parent, {"target": child, "text": "via route"})
    cur.execute("RESET ROLE")
    check("route steer event", "event_id" in got and got["caller"] == parent, got)
    cur.execute("SET ROLE v13_recall")
    cur.execute("SAVEPOINT recall")
    try:
        cur.execute(
            "SELECT public.v13_agentctl_steer(%s::uuid, %s::jsonb)",
            (parent, json.dumps({"target": child, "text": "no"})))
        cur.fetchall()
        cur.execute("ROLLBACK TO SAVEPOINT recall")
        raise AssertionError("recall should fail")
    except psycopg2.Error as exc:
        check("recall 42501", exc.pgcode == "42501", exc.pgcode)
        cur.execute("ROLLBACK TO SAVEPOINT recall")
    cur.execute("RESET ROLE")


def actl_shape_closed(cur):
    parent, child = controller_pair(cur)
    shared = [
        None, "json-null", [], "nope", 1, True, {},
        {"source_principal": "controller"},
    ]
    for spec in shared:
        measured_reject(cur, "v13_agentctl_steer", parent, spec, "v13: agentctl args",
                        "steer shape " + json.dumps(spec, default=str)[:60], child)
    steer_bad = [
        {"target": child},
        {"text": "hi"},
        {"target": child, "text": "hi", "source_principal": "controller"},
        {"target": 1, "text": "hi"},
        {"target": child.upper(), "text": "hi"},
        {"target": " " + child, "text": "hi"},
        {"target": child.replace("-", ""), "text": "hi"},
        {"target": "", "text": "hi"},
        {"target": child, "text": ""},
        {"target": child, "text": "   "},
        {"target": child, "text": "a" * 1025},
        {"target": child, "text": "字" * 1025},
        {"target": child, "text": 1},
        {"target": child, "text": None},
        {"target": child, "text": ["x"]},
    ]
    for spec in steer_bad:
        measured_reject(cur, "v13_agentctl_steer", parent, spec, "v13: agentctl args",
                        "steer bad " + json.dumps(spec, default=str)[:70], child)
    measured_reject(
        cur, "v13_agentctl_answer", parent,
        {"target": child, "effect_id": u(), "response": "ok", "skip": True},
        "v13: agentctl args", "answer skip", child)
    measured_reject(
        cur, "v13_agentctl_cancel", parent, {"target": child, "text": "x"},
        "v13: agentctl args", "cancel extra", child)


def actl_steer_reject_zero_event(cur):
    parent, child = controller_pair(cur)
    measured_reject(
        cur, "v13_agentctl_steer", parent, {"target": child, "text": ""},
        "v13: agentctl args", "reject shape", child)
    plain = open_session(cur)
    append_user(cur, plain, "plain")
    plain_child = spawn_one(cur, plain)["children"][0]["session_id"]
    measured_reject(
        cur, "v13_agentctl_steer", plain, {"target": plain_child, "text": "hi"},
        "v13: agentctl policy", "reject policy", plain_child)
    measured_reject(
        cur, "v13_agentctl_steer", parent, {"target": parent, "text": "hi"},
        "v13: session not found", "reject self", parent)
    other = open_session(cur, ("controller", 1))
    append_user(cur, other, "other")
    sibling = spawn_one(cur, other)["children"][0]["session_id"]
    measured_reject(
        cur, "v13_agentctl_steer", parent, {"target": sibling, "text": "hi"},
        "v13: session not found", "reject sibling-ish", sibling)
    append_user(cur, child, "child")
    grand = spawn_one(cur, child, "grand")["children"][0]["session_id"]
    measured_reject(
        cur, "v13_agentctl_steer", parent, {"target": grand, "text": "hi"},
        "v13: session not found", "reject grandchild", grand)
    measured_reject(
        cur, "v13_agentctl_steer", child, {"target": parent, "text": "hi"},
        "v13: session not found", "reject ancestor", parent)
    brother = spawn_one(cur, parent, "brother")["children"][0]["session_id"]
    measured_reject(
        cur, "v13_agentctl_steer", child, {"target": brother, "text": "hi"},
        "v13: session not found", "reject brother", brother)
    measured_reject(
        cur, "v13_agentctl_steer", parent, {"target": u(), "text": "hi"},
        "v13: session not found", "reject missing", child)


def actl_policy_fail_close(cur):
    for fn, spec_builder in (
        ("v13_agentctl_steer", lambda child, _eid: {"target": child, "text": "hi"}),
        ("v13_agentctl_answer", lambda child, eid: {
            "target": child, "effect_id": eid, "response": "ok"}),
        ("v13_agentctl_cancel", lambda child, _eid: {"target": child}),
    ):
        parent = open_session(cur)
        append_user(cur, parent, "default")
        child = spawn_one(cur, parent)["children"][0]["session_id"]
        eid = enqueue_human(cur, child, "ref-" + u()[:8])
        measured_reject(
            cur, fn, parent, spec_builder(child, eid),
            "v13: agentctl policy", "default " + fn, child, eid)
    cur.execute(
        "INSERT INTO v13_route_policies (policy_name, policy_version) VALUES ('controller', 2)")
    cur.execute(
        "UPDATE v13_route_policies SET state = 'frozen' "
        "WHERE policy_name = 'controller' AND policy_version = 2")
    parent = open_session(cur, ("controller", 2))
    append_user(cur, parent, "v2")
    child = spawn_one(cur, parent)["children"][0]["session_id"]
    measured_reject(
        cur, "v13_agentctl_steer", parent, {"target": child, "text": "hi"},
        "v13: agentctl policy", "controller v2", child)
    obs_parent, obs_child = controller_pair(cur)
    got = call_verb(cur, "v13_agentctl_observe", obs_parent, {"ids": obs_child})
    check("controller observe", got.get("ok") is True and got["rows"], got)
    plain = open_session(cur)
    append_user(cur, plain, "obs")
    plain_child = spawn_one(cur, plain)["children"][0]["session_id"]
    got = call_verb(cur, "v13_agentctl_observe", plain, {"ids": plain_child})
    check("default observe", got.get("ok") is True and got["rows"], got)


def actl_no_null_actor(cur, server):
    answer = function_def(cur, FNS["answer"])
    cancel = function_def(cur, FNS["cancel"])
    check("complete actor", "v13_complete(p_sid," in answer)
    check("cancel actor", "v13_cancel(p_sid," in cancel)
    check("no null complete", "v13_complete(NULL" not in answer)
    check("no null cancel", "v13_cancel(NULL" not in cancel)
    check("no one-arg cancel", re.search(r"v13_cancel\s*\(\s*[^,\)]+\s*\)", cancel) is None)
    check("no five-arg complete", "v13_complete(v_eid," not in answer)
    check("session super", q1(cur, "SELECT rolsuper FROM pg_roles WHERE rolname = current_user") is True)
    parent, child = controller_pair(cur)
    stranger = open_session(cur, ("controller", 1))
    measured_reject(
        cur, "v13_agentctl_cancel", parent, {"target": stranger},
        "v13: session not found", "super wrapper not operator", stranger)
    other = connect(server)
    ocur = other.cursor()
    fresh = open_session(ocur)
    ocur.execute("SELECT public.v13_cancel(NULL::uuid, %s)", (fresh,))
    word = ocur.fetchone()[0]
    check("null actor operator path", word == "accepted", word)
    other.rollback()
    other.close()


def direct_success(cur, fn, actor, spec, expect):
    caller_seq = q1(cur, "SELECT next_seq FROM sessions WHERE session_id = %s", (actor,))
    before = snapshot_window(cur)
    got = call_verb(cur, fn, actor, spec)
    after = snapshot_window(cur)
    names = changed_names(before, after)
    check("diff " + fn, names == expect, names)
    check(
        "caller seq " + fn,
        q1(cur, "SELECT next_seq FROM sessions WHERE session_id = %s", (actor,)) == caller_seq)
    return got


def actl_write_targets(cur):
    parent, child = controller_pair(cur)
    goals = q1(cur, "SELECT count(*) FROM v13_goals")
    turn = q1(cur, "SELECT turn_no FROM sessions WHERE session_id = %s", (child,))
    status = q1(cur, "SELECT status FROM sessions WHERE session_id = %s", (child,))
    seq = q1(cur, "SELECT next_seq FROM sessions WHERE session_id = %s", (child,))
    got = direct_success(
        cur, "v13_agentctl_steer", parent, {"target": child, "text": "  hi  "},
        ["events", "sessions"])
    check(
        "steer return keys",
        set(got) == {"schema_version", "caller", "target", "event_id", "seq"},
        got)
    check("steer caller", got["caller"] == parent and got["target"] == child, got)
    check("steer trimmed", True)
    cur.execute(
        "SELECT payload FROM events WHERE event_id = %s", (got["event_id"],))
    payload = as_obj(cur.fetchone()[0])
    check(
        "steer payload",
        set(payload) == {"schema_version", "text", "source_principal"}
        and payload["text"] == "hi" and payload["source_principal"] == "controller"
        and payload["schema_version"] == 1,
        payload)
    check("steer seq", got["seq"] == seq)
    check("goals unchanged", q1(cur, "SELECT count(*) FROM v13_goals") == goals)
    check(
        "turn status",
        q1(cur, "SELECT turn_no FROM sessions WHERE session_id = %s", (child,)) == turn
        and q1(cur, "SELECT status FROM sessions WHERE session_id = %s", (child,)) == status)
    again = call_verb(cur, "v13_agentctl_steer", parent, {"target": child, "text": "hi"})
    check("not idempotent", again["event_id"] != got["event_id"])
    long = call_verb(cur, "v13_agentctl_steer", parent, {"target": child, "text": "a" * 1024})
    check("1024", long["event_id"] != again["event_id"])
    multi = call_verb(cur, "v13_agentctl_steer", parent, {"target": child, "text": "字" * 1024})
    check("multibyte 1024", "event_id" in multi)
    cur.execute("UPDATE sessions SET status = 'cancelled' WHERE session_id = %s", (child,))
    terminal = call_verb(cur, "v13_agentctl_steer", parent, {"target": child, "text": "still"})
    check(
        "terminal steer not revived",
        q1(cur, "SELECT status FROM sessions WHERE session_id = %s", (child,)) == "cancelled"
        and terminal["event_id"] != multi["event_id"])

    parent, child = controller_pair(cur)
    eid = enqueue_human(cur, child, "ref-ok")
    seq = q1(cur, "SELECT next_seq FROM sessions WHERE session_id = %s", (child,))
    got = direct_success(
        cur, "v13_agentctl_answer", parent,
        {"target": child, "effect_id": eid, "response": "  yes  "},
        ["effects", "events", "sessions"])
    check(
        "answer return keys",
        set(got) == {"schema_version", "caller", "target", "effect_id", "outcome"}
        and got["outcome"] == "accepted" and got["caller"] == parent,
        got)
    check(
        "answer seq +2",
        q1(cur, "SELECT next_seq FROM sessions WHERE session_id = %s", (child,)) == seq + 2)
    responded = q1(
        cur,
        "SELECT count(*) FROM events WHERE session_id = %s AND type = 'human/responded'",
        (child,))
    check("one human responded", responded == 1, responded)
    cur.execute("SAVEPOINT second")
    try:
        call_verb(cur, "v13_agentctl_answer", parent, {
            "target": child, "effect_id": eid, "response": "again"})
        raise AssertionError("second answer should fail")
    except psycopg2.Error as exc:
        check("second answer", "v13: agentctl answer" in (exc.diag.message_primary or ""),
              exc.diag.message_primary)
        cur.execute("ROLLBACK TO SAVEPOINT second")
    check(
        "responded still one",
        q1(cur, "SELECT count(*) FROM events WHERE session_id = %s AND type = 'human/responded'",
           (child,)) == 1)

    parent, child = controller_pair(cur)
    enqueue_human(cur, child, "ref-cancel")
    got = direct_success(
        cur, "v13_agentctl_cancel", parent, {"target": child},
        ["effects", "events", "sessions"])
    check(
        "cancel return",
        set(got) == {"schema_version", "caller", "target", "outcome"}
        and got["outcome"] == "accepted" and got["caller"] == parent,
        got)
    parent, bare = controller_pair(cur)
    before = snapshot_window(cur)
    bare_got = call_verb(cur, "v13_agentctl_cancel", parent, {"target": bare})
    names = changed_names(before, snapshot_window(cur))
    check("bare cancel not the expected set", names == ["events", "sessions"] and names != CANCEL_JSON["write_targets"])
    check("bare cancel accepted", bare_got["outcome"] == "accepted", bare_got)
    check(
        "named still has effects",
        named_json(cur, "v13_agentctl_cancel") == CANCEL_JSON)


def actl_answer_effect_rejects(cur):
    parent, child = controller_pair(cur)
    other_parent, other = controller_pair(cur)
    missing = u()
    measured_reject(
        cur, "v13_agentctl_answer", parent,
        {"target": child, "effect_id": missing, "response": "x"},
        "v13: agentctl answer", "missing effect", child)
    eid_other = enqueue_human(cur, other, "other-ref")
    measured_reject(
        cur, "v13_agentctl_answer", parent,
        {"target": child, "effect_id": eid_other, "response": "x"},
        "v13: agentctl answer", "other target effect", child, eid_other)
    cur.execute(
        "SELECT v13_enqueue_effect(%s, 'tool', %s::jsonb, 'send_summary_email')",
        (child, json.dumps({"tool": "send_summary_email", "params": {}})))
    tool_eid = str(cur.fetchone()[0])
    measured_reject(
        cur, "v13_agentctl_answer", parent,
        {"target": child, "effect_id": tool_eid, "response": "x"},
        "v13: agentctl answer", "non human", child, tool_eid)
    cur.execute("UPDATE effects SET status = 'cancelled' WHERE effect_id = %s", (tool_eid,))
    human = enqueue_human(cur, child, "ready-ref")
    cur.execute(
        "UPDATE effects SET status = 'claimed', attempt_no = 1, fence = 1, "
        "lease_owner = 'w', lease_until = clock_timestamp() + interval '1 hour' "
        "WHERE effect_id = %s",
        (human,))
    measured_reject(
        cur, "v13_agentctl_answer", parent,
        {"target": child, "effect_id": human, "response": "x"},
        "v13: agentctl answer", "already claimed", child, human)
    cur.execute("UPDATE effects SET status = 'succeeded' WHERE effect_id = %s", (human,))
    measured_reject(
        cur, "v13_agentctl_answer", parent,
        {"target": child, "effect_id": human, "response": "x"},
        "v13: agentctl answer", "terminal effect", child, human)
    cur.execute("UPDATE effects SET status = 'cancelled' WHERE effect_id = %s", (human,))
    bare = enqueue_human_raw(cur, child, {"schema_version": 1})
    measured_reject(
        cur, "v13_agentctl_answer", parent,
        {"target": child, "effect_id": bare, "response": "x"},
        "v13: agentctl answer", "missing interaction_ref", child, bare)


def actl_approval_two_phase(cur, server):
    body = function_def(cur, FNS["answer"])
    check("claim update", "lease_owner = 'agentctl_answer'" in body)
    check("six arg", "public.v13_complete(p_sid, v_eid, v_attempt, v_fence, 'succeeded', v_result)" in body)
    check("literal succeeded", body.count("'succeeded'") >= 1)
    check("distinct accepted", "v_word IS DISTINCT FROM 'accepted'" in body)
    check("not accepted raise", "v13: agentctl answer not accepted" in body)
    check("no capture", re.search(r"EXCEPTION\s+WHEN", body) is None)
    check("one effect update", body.lower().count("update public.effects") == 1)
    check("arrow not text", "request->'interaction_ref'" in body and "request->>'interaction_ref'" not in body)

    parent, child = controller_pair(cur)
    eid = enqueue_human(cur, child, "stale-ref")
    before = q1(
        cur,
        "SELECT e.status, e.attempt_no, e.fence, s.next_seq FROM effects e "
        "JOIN sessions s ON s.session_id = e.session_id WHERE e.effect_id = %s",
        (eid,))
    cur.execute("SAVEPOINT stale")
    cur.execute(
        """
        UPDATE effects
           SET status = 'claimed', attempt_no = attempt_no + 1, fence = fence + 1,
               lease_owner = 'agentctl_answer',
               lease_until = clock_timestamp() + interval '1 hour'
         WHERE effect_id = %s AND session_id = %s AND status = 'ready' AND kind = 'human'
         RETURNING attempt_no, fence
        """,
        (eid, child))
    attempt, fence = cur.fetchone()
    cur.execute(
        "SELECT public.v13_complete(%s, %s, %s, %s, 'succeeded', %s::jsonb)",
        (parent, eid, attempt, fence + 1, json.dumps({
            "schema_version": 1, "interaction_ref": "stale-ref", "response": "x"})))
    word = cur.fetchone()[0]
    check("underlying stale", word == "stale", word)
    cur.execute("ROLLBACK TO SAVEPOINT stale")
    after = q1(
        cur,
        "SELECT e.status, e.attempt_no, e.fence, s.next_seq FROM effects e "
        "JOIN sessions s ON s.session_id = e.session_id WHERE e.effect_id = %s",
        (eid,))
    check("stale rolled back", after == before, (before, after))

    parent, child = controller_pair(cur)
    eid = enqueue_human_raw(cur, child, {"schema_version": 1, "interaction_ref": 1})
    cur.execute("SAVEPOINT num")
    try:
        call_verb(cur, "v13_agentctl_answer", parent, {
            "target": child, "effect_id": eid, "response": "x"})
        raise AssertionError("numeric ref should fail")
    except psycopg2.Error as exc:
        msg = exc.diag.message_primary or ""
        check("mismatch prefix", msg.startswith("v13: human interaction_ref mismatch"), msg)
        cur.execute("ROLLBACK TO SAVEPOINT num")
    check("numeric still ready", q1(cur, "SELECT status FROM effects WHERE effect_id = %s", (eid,)) == "ready")
    route_numeric_ref(server)

    before_ident = q1(
        cur,
        """
        SELECT pg_get_functiondef(p.oid), r.rolname, p.proacl::text, p.proconfig::text
          FROM pg_proc p JOIN pg_roles r ON r.oid = p.proowner
         WHERE p.oid = %s::regprocedure
        """,
        (FNS["answer"],))
    parent, child = controller_pair(cur)
    eid = enqueue_human(cur, child, "fault-ref")
    cur.execute("SAVEPOINT fault")
    faulty = body.replace(", v_fence, 'succeeded'", ", v_fence - 1, 'succeeded'", 1)
    check("fence token once", body.count(", v_fence, 'succeeded'") == 1)
    cur.execute(faulty)
    try:
        call_verb(cur, "v13_agentctl_answer", parent, {
            "target": child, "effect_id": eid, "response": "x"})
        raise AssertionError("fault should fail")
    except psycopg2.Error as exc:
        msg = exc.diag.message_primary or ""
        check("not accepted", "v13: agentctl answer not accepted" in msg, msg)
        cur.execute("ROLLBACK TO SAVEPOINT fault")
    check("fault effect ready", q1(cur, "SELECT status FROM effects WHERE effect_id = %s", (eid,)) == "ready")
    route_fence_fault(server, body)
    after_ident = q1(
        cur,
        """
        SELECT pg_get_functiondef(p.oid), r.rolname, p.proacl::text, p.proconfig::text
          FROM pg_proc p JOIN pg_roles r ON r.oid = p.proowner
         WHERE p.oid = %s::regprocedure
        """,
        (FNS["answer"],))
    check("fault def restored", after_ident == before_ident)


def route_numeric_ref(server):
    conn = connect(server)
    cur = conn.cursor()
    root, child, parsed, _eid = prepare_chain(
        cur, "agentctl_answer", True, numeric_ref=True)
    target_seq = q1(cur, "SELECT next_seq FROM sessions WHERE session_id = %s", (child,))
    caller_seq = q1(cur, "SELECT next_seq FROM sessions WHERE session_id = %s", (root,))
    cur.execute(
        "UPDATE sessions SET context_active_revision = v13_context_required(session_id) "
        "WHERE session_id = %s",
        (root,))
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (root, json.dumps(parsed)))
    status = cur.fetchone()[0]
    check("numeric arm progressed", status == "progressed", status)
    cur.execute(
        "SELECT status, error, result FROM effects WHERE session_id = %s AND tool_name = 'agentctl_answer'",
        (root,))
    effect_status, error, result = cur.fetchone()
    message = (as_obj(error) or {}).get("message", "")
    check(
        "numeric arm failed",
        effect_status == "failed" and result is None
        and message.startswith("v13: human interaction_ref mismatch"),
        error)
    check(
        "numeric arm no tool result",
        q1(cur, "SELECT count(*) FROM events WHERE session_id = %s AND type = 'tool/result'", (root,)) == 0)
    check(
        "numeric human ready",
        q1(cur, "SELECT status FROM effects WHERE session_id = %s AND kind = 'human'", (child,)) == "ready")
    check(
        "numeric caller +1",
        q1(cur, "SELECT next_seq FROM sessions WHERE session_id = %s", (root,)) == caller_seq + 1)
    check(
        "numeric target seq",
        q1(cur, "SELECT next_seq FROM sessions WHERE session_id = %s", (child,)) == target_seq)
    conn.close()


def route_fence_fault(server, body):
    conn = connect(server)
    cur = conn.cursor()
    faulty = body.replace(", v_fence, 'succeeded'", ", v_fence - 1, 'succeeded'", 1)
    cur.execute(faulty)
    root, child, parsed, eid = prepare_chain(cur, "agentctl_answer", True)
    target_seq = q1(cur, "SELECT next_seq FROM sessions WHERE session_id = %s", (child,))
    caller_seq = q1(cur, "SELECT next_seq FROM sessions WHERE session_id = %s", (root,))
    cur.execute(
        "UPDATE sessions SET context_active_revision = v13_context_required(session_id) "
        "WHERE session_id = %s",
        (root,))
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (root, json.dumps(parsed)))
    status = cur.fetchone()[0]
    check("fault arm progressed", status == "progressed", status)
    cur.execute(
        "SELECT status, error FROM effects WHERE session_id = %s AND tool_name = 'agentctl_answer'",
        (root,))
    effect_status, error = cur.fetchone()
    message = (as_obj(error) or {}).get("message", "")
    check(
        "fault arm message",
        effect_status == "failed" and "v13: agentctl answer not accepted" in message,
        error)
    check(
        "fault human ready",
        q1(cur, "SELECT status FROM effects WHERE effect_id = %s", (eid,)) == "ready")
    check(
        "fault caller +1",
        q1(cur, "SELECT next_seq FROM sessions WHERE session_id = %s", (root,)) == caller_seq + 1)
    check(
        "fault target seq",
        q1(cur, "SELECT next_seq FROM sessions WHERE session_id = %s", (child,)) == target_seq)
    conn.rollback()
    conn.close()


def prepare_chain(cur, verb, with_override, bad_target=False, numeric_ref=False):
    root = open_session(cur, ("controller", 1))
    append_user(cur, root, "route " + verb)
    spawned = spawn_one(cur, root, "routed child")
    child = spawned["children"][0]["session_id"]
    ready = q1(
        cur,
        "SELECT count(*) FROM effects WHERE session_id = %s AND status IN ('ready', 'claimed')",
        (root,))
    check("root no ready " + verb, ready == 0, ready)
    eid = None
    if verb in ("agentctl_answer", "agentctl_cancel"):
        if numeric_ref:
            eid = enqueue_human_raw(cur, child, {"schema_version": 1, "interaction_ref": 1})
        else:
            eid = enqueue_human(cur, child, "ref-" + u()[:8])
    if with_override:
        submit_override(cur, root)
    shrink_catalog(cur, ["spawn_subsession", verb])
    target_choice = "not-a-uuid" if bad_target else child
    overrides = {
        "intent": choice("sql_answer"),
        "tool": choice(verb),
        "gate_action": {"type": "noul", "noul": 0.9},
        "gate_off_topic": {"type": "noul", "noul": 0.1},
        "risk": {"type": "score", "score": 0.5, "confidence": 0.9},
    }
    keys = TOOL_TEXT[verb]["spec"]
    values = {"target": target_choice}
    if "text" in keys:
        values["text"] = "steer-text"
    if "response" in keys:
        values["response"] = "yes"
    if "effect_id" in keys:
        values["effect_id"] = eid or u()
    for key in keys:
        overrides["stated::" + verb + "::" + key] = {"type": "noul", "noul": 0.9}
        overrides["param::" + verb + "::" + key] = choice(values[key])
    mock = mock_from_needed(cur, root, **overrides)
    set_mock(cur, mock)
    cur.execute("SELECT v13_parse(%s)", (root,))
    parsed = as_obj(cur.fetchone()[0])
    check("parse remaining " + verb, parsed.get("remaining") == 0, parsed.get("remaining"))
    check("parse failed " + verb, parsed.get("failed") is False, parsed.get("failed"))
    check("parse abandon " + verb, parsed.get("abandon") is False, parsed.get("abandon"))
    snap = parsed.get("snap") or {}
    check(
        "parse policy " + verb,
        snap.get("route_policy_name") == "controller" and str(snap.get("route_policy_version")) == "1",
        snap)
    return root, child, parsed, eid


def actl_chain_full(server):
    roots = []
    for verb, expect in (
        ("agentctl_steer", ["events", "sessions"]),
        ("agentctl_answer", ["effects", "events", "sessions"]),
        ("agentctl_cancel", ["effects", "events", "sessions"]),
    ):
        conn = connect(server)
        cur = conn.cursor()
        root, child, parsed, _eid = prepare_chain(cur, verb, True)
        CHAIN.append((verb, root))
        roots.append(root)
        status_before = q1(cur, "SELECT status FROM sessions WHERE session_id = %s", (child,))
        before = snapshot_target(cur, child)
        cur.execute(
            "UPDATE sessions SET context_active_revision = v13_context_required(session_id) "
            "WHERE session_id = %s",
            (root,))
        cur.execute("SELECT v13_advance(%s, %s::jsonb)", (root, json.dumps(parsed)))
        status = cur.fetchone()[0]
        check("chain progressed " + verb, status == "progressed", status)
        cur.execute(
            """
            SELECT payload FROM events
             WHERE session_id = %s AND type = 'turn/route'
             ORDER BY seq DESC LIMIT 1
            """,
            (root,))
        route = as_obj(cur.fetchone()[0])
        check("route sql " + verb, route.get("action") == "sql" and route.get("tool") == verb, route)
        cur.execute(
            """
            SELECT status, error, request, result
              FROM effects
             WHERE session_id = %s AND tool_name = %s
            """,
            (root, verb))
        rows = cur.fetchall()
        check("one tool effect " + verb, len(rows) == 1, rows)
        effect_status, error, request, result = rows[0]
        request = as_obj(request)
        result = as_obj(result)
        check("effect succeeded " + verb, effect_status == "succeeded" and error is None, effect_status)
        check("params not empty " + verb, request.get("params") not in ({}, None), request)
        cur.execute(
            """
            SELECT payload FROM events
             WHERE session_id = %s AND type = 'tool/result'
             ORDER BY seq DESC LIMIT 1
            """,
            (root,))
        tool_result = as_obj(cur.fetchone()[0])
        check("result matches " + verb, as_obj(tool_result["result"]) == result, tool_result)
        overrides = q1(
            cur, "SELECT count(*) FROM events WHERE session_id = %s AND type = 'goal/override'", (root,))
        steer_on_root = q1(
            cur, "SELECT count(*) FROM events WHERE session_id = %s AND type = 'steer/injected'", (root,))
        check("one override " + verb, overrides == 1 and steer_on_root == 0, overrides)
        names = changed_names(before, snapshot_target(cur, child))
        check("target diff " + verb, names == expect, names)
        check(
            "child status " + verb,
            q1(cur, "SELECT status FROM sessions WHERE session_id = %s", (child,)) == status_before
            and status_before not in ("completed", "failed", "cancelled"))
        conn.close()
    check("three roots", len(set(roots)) == 3, roots)
    for verb in ("agentctl_steer", "agentctl_answer", "agentctl_cancel"):
        conn = connect(server)
        cur = conn.cursor()
        root, child, parsed, _eid = prepare_chain(cur, verb, False)
        cur.execute("SELECT public.v13_control_authorized(NULL::uuid, NULL::uuid)")
        cur.fetchone()
        cur.execute("SELECT funcid::text, calls FROM pg_stat_xact_user_functions")
        base = {row[0]: row[1] for row in cur.fetchall()}
        oid = q1(cur, "SELECT %s::regprocedure::oid::text", (FNS[{
            "agentctl_steer": "steer",
            "agentctl_answer": "answer",
            "agentctl_cancel": "cancel",
        }[verb]],))
        cur.execute(
            "UPDATE sessions SET context_active_revision = v13_context_required(session_id) "
            "WHERE session_id = %s",
            (root,))
        cur.execute("SELECT v13_advance(%s, %s::jsonb)", (root, json.dumps(parsed)))
        status = cur.fetchone()[0]
        check("no override waiting " + verb, status == "waiting", status)
        reason = q1(
            cur,
            "SELECT request->>'reason' FROM effects "
            "WHERE session_id = %s AND kind = 'human' AND status = 'ready'",
            (root,))
        check("triage_fail_closed " + verb, reason == "triage_fail_closed", reason)
        tools = q1(
            cur, "SELECT count(*) FROM effects WHERE session_id = %s AND tool_name = %s", (root, verb))
        cur.execute("SELECT funcid::text, calls FROM pg_stat_xact_user_functions")
        now = {row[0]: row[1] for row in cur.fetchall()}
        check("handler not called " + verb, tools == 0 and now.get(oid, 0) - base.get(oid, 0) == 0, tools)
        conn.close()
        conn = connect(server)
        cur = conn.cursor()
        root, child, parsed, _eid = prepare_chain(cur, verb, True, bad_target=True)
        before = snapshot_target(cur, child)
        caller_seq = q1(cur, "SELECT next_seq FROM sessions WHERE session_id = %s", (root,))
        cur.execute(
            "UPDATE sessions SET context_active_revision = v13_context_required(session_id) "
            "WHERE session_id = %s",
            (root,))
        cur.execute("SELECT v13_advance(%s, %s::jsonb)", (root, json.dumps(parsed)))
        status = cur.fetchone()[0]
        check("bad uuid progressed " + verb, status == "progressed", status)
        cur.execute(
            "SELECT status, error, result FROM effects WHERE session_id = %s AND tool_name = %s",
            (root, verb))
        effect_status, error, result = cur.fetchone()
        message = (as_obj(error) or {}).get("message", "")
        check(
            "bad uuid failed " + verb,
            effect_status == "failed" and result is None and "v13: agentctl args" in message,
            error)
        check(
            "bad uuid no tool result " + verb,
            q1(cur, "SELECT count(*) FROM events WHERE session_id = %s AND type = 'tool/result'",
               (root,)) == 0)
        check("bad uuid target " + verb, snapshot_target(cur, child) == before)
        check(
            "bad uuid caller +1 " + verb,
            q1(cur, "SELECT next_seq FROM sessions WHERE session_id = %s", (root,)) == caller_seq + 1)
        conn.close()


def actl_controller_observe_routed(server):
    conn = connect(server)
    cur = conn.cursor()
    root = open_session(cur, ("controller", 1))
    append_user(cur, root, "observe")
    child = spawn_one(cur, root, "observe me")["children"][0]["session_id"]
    submit_override(cur, root)
    shrink_catalog(cur, ["spawn_subsession", "agentctl_observe"])
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
            "param::agentctl_observe::ids": choice(child),
            "param::agentctl_observe::hint": choice("true"),
        })
    set_mock(cur, mock)
    cur.execute("SELECT v13_parse(%s)", (root,))
    parsed = as_obj(cur.fetchone()[0])
    check("observe parse remaining", parsed.get("remaining") == 0, parsed.get("remaining"))
    cur.execute(
        "UPDATE sessions SET context_active_revision = v13_context_required(session_id) "
        "WHERE session_id = %s",
        (root,))
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (root, json.dumps(parsed)))
    status = cur.fetchone()[0]
    check("observe progressed", status == "progressed", status)
    cur.execute(
        """
        SELECT payload FROM events
         WHERE session_id = %s AND type = 'turn/route'
         ORDER BY seq DESC LIMIT 1
        """,
        (root,))
    route = as_obj(cur.fetchone()[0])
    check(
        "observe sql",
        route.get("action") == "sql" and route.get("tool") == "agentctl_observe",
        route)
    request = as_obj(q1(
        cur,
        "SELECT request FROM effects WHERE session_id = %s AND tool_name = 'agentctl_observe'",
        (root,)))
    check("observe params", request.get("params") not in ({}, None), request)
    conn.close()


def actl_steer_watermark(cur):
    parent, child = controller_pair(cur)
    append_user(cur, child, "watermark")
    eid = enqueue_human(cur, child, "wm-ref")
    shrink_catalog(cur, ["spawn_subsession"])
    mock = mock_from_needed(cur, child, intent=choice("sql_answer"))
    set_mock(cur, mock)
    cur.execute("SELECT v13_parse(%s)", (child,))
    parsed = as_obj(cur.fetchone()[0])
    tokens = q1(
        cur,
        "SELECT request::text, request_hash, attempt_no, fence, lease_owner, lease_until::text "
        "FROM effects WHERE effect_id = %s",
        (eid,))
    seq = q1(cur, "SELECT next_seq FROM sessions WHERE session_id = %s", (child,))
    call_verb(cur, "v13_agentctl_steer", parent, {"target": child, "text": "watermark steer"})
    before = snapshot_window(cur)
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (child, json.dumps(parsed)))
    word = cur.fetchone()[0]
    check("watermark stale", word == "stale", word)
    check("watermark zero write", snapshot_window(cur) == before)
    check(
        "watermark seq +1",
        q1(cur, "SELECT next_seq FROM sessions WHERE session_id = %s", (child,)) == seq + 1)
    after = q1(
        cur,
        "SELECT request::text, request_hash, attempt_no, fence, lease_owner, lease_until::text "
        "FROM effects WHERE effect_id = %s",
        (eid,))
    check("watermark tokens", after == tokens, (tokens, after))


def actl_cancel_sticky(cur):
    parent, child = controller_pair(cur)
    enqueue_human(cur, child, "sticky")
    first = call_verb(cur, "v13_agentctl_cancel", parent, {"target": child})
    count = q1(
        cur, "SELECT count(*) FROM events WHERE session_id = %s AND type = 'cancel/requested'", (child,))
    seq = q1(cur, "SELECT next_seq FROM sessions WHERE session_id = %s", (child,))
    check("sticky first", first["outcome"] == "accepted" and count == 1, first)
    second = call_verb(cur, "v13_agentctl_cancel", parent, {"target": child})
    count2 = q1(
        cur, "SELECT count(*) FROM events WHERE session_id = %s AND type = 'cancel/requested'", (child,))
    check(
        "sticky second",
        second["outcome"] == "accepted" and second["outcome"] != "replay" and count2 == 1
        and q1(cur, "SELECT next_seq FROM sessions WHERE session_id = %s", (child,)) == seq,
        second)
    parent, child = controller_pair(cur)
    cur.execute("UPDATE sessions SET status = 'cancelled' WHERE session_id = %s", (child,))
    replay = call_verb(cur, "v13_agentctl_cancel", parent, {"target": child})
    check("terminal replay", replay["outcome"] == "replay", replay)
    check(
        "terminal replay no event",
        q1(cur, "SELECT count(*) FROM events WHERE session_id = %s AND type = 'cancel/requested'",
           (child,)) == 0)


def actl_steer_body_residual_open():
    expected = (
        "v13/control/test_control.py:516-524",
        "demo_v13/parity/g_steer.py:98",
        "v13/plan_contract/test_plan_contract.py:459-460",
        "v13/resolve/v13_resolve.sql canonical state",
        "v13/envelope/v13_envelope.sql:519,551",
        "v13/memory/v13_memory.sql:113-127",
        "v13/triage/v13_triage.sql:161-164",
        "v13/observe/v13_observe.sql:130-171 v13_session_log",
        "v13_triage_steer name collision",
    )
    readme = (ROOT / "README.md").read_text()
    check(
        "actl_steer_body_residual_open",
        CONSUMER is None
        and NON_CONSUMERS == expected
        and "正文消费未闭合" in readme
        and "不得退出 0" not in readme
        and "已取代 R11" not in readme
        and "取代 parity R11" not in readme,
        "residual must stay open; CONSUMER stays unset")


def main() -> int:
    server = get_server()
    conn = None
    try:
        r0_source_scope()
        actl_frozen_unchanged()
        if setup_db() != 0:
            return 1
        conn = connect(server)
        cur = conn.cursor()
        spawn_before = actl_spawn_enabled_true(cur, "before install")
        before_fns = fn_rows(cur)
        before_tools = tool_rows(cur)
        before_rels = rel_rows(cur)
        cur.execute("SELECT revision, candidate_generation_revision FROM v13_tools_meta")
        before_meta = cur.fetchone()
        before_events = q1(cur, "SELECT count(*) FROM events")
        before_effects = q1(cur, "SELECT count(*) FROM effects")
        before_policies = q1(cur, "SELECT count(*) FROM v13_policies")
        before_routes = q1(cur, "SELECT count(*) FROM v13_route_policies")
        cur.execute(
            """
            SELECT signal, band_no, lo, hi, action
              FROM thresholds
             WHERE policy_name = 'default' AND policy_version = 2
             ORDER BY signal, band_no
            """)
        before_default = cur.fetchall()
        conn.commit()
        cur.execute("SET track_functions = 'all'")
        run_psql(server, DB, SQL)
        after_fns = fn_rows(cur)
        actl_install_delta(cur, before_fns, after_fns, before_rels, before_events, before_effects)
        after_tools = tool_rows(cur)
        cur.execute("SELECT revision, candidate_generation_revision FROM v13_tools_meta")
        after_meta = cur.fetchone()
        actl_catalog_rows(cur, before_tools, after_tools, before_meta, after_meta)
        actl_controller_policy(cur, before_default, before_policies, before_routes)
        actl_spawn_enabled_true(cur, "after install", spawn_before)
        actl_guard_closed(cur)
        actl_no_io(cur)
        actl_owner_not_operator(cur)
        actl_acl_closed(cur)
        actl_shape_closed(cur)
        actl_steer_reject_zero_event(cur)
        actl_policy_fail_close(cur)
        actl_no_null_actor(cur, server)
        actl_write_targets(cur)
        actl_answer_effect_rejects(cur)
        actl_approval_two_phase(cur, server)
        actl_steer_watermark(cur)
        actl_cancel_sticky(cur)
        actl_spawn_enabled_true(cur, "after behavior", spawn_before)
        conn.rollback()
        actl_chain_full(server)
        actl_controller_observe_routed(server)
        actl_steer_body_residual_open()
        return 0
    finally:
        if conn is not None:
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
