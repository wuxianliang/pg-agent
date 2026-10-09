"""stage 44 ce_map gate.

Run: UV_FROZEN=1 uv run python v13/ce_map/test_ce_map.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v13.ce_map.setup_db import DB, main as setup_db
import v13.ce_map.setup_db as setup_mod
from v13.load import run_psql

SQL_PATH = ROOT / "v13_ce_map.sql"
SQL = SQL_PATH.read_text()
SETUP_SRC = (ROOT / "setup_db.py").read_text()
TEST_SRC = Path(__file__).read_text()
COMMENT = (
    "STABLE read; returns the closed static CE primitive map; "
    "does not execute or query; not a tools row; does not raise."
)
EXPECTED = {
    "schema_version": 1,
    "map": {
        "observe_poll": "v13_agentctl_observe(uuid,jsonb)",
        "startOrResume": "v13_enqueue_effect(uuid,text,jsonb,text)",
        "sendUserMessage": "v13_append_event(uuid,uuid,text,jsonb,uuid)",
        "steerUserTurn": "v13_agentctl_steer(uuid,jsonb)",
        "interruptTurn": "v13_cancel(uuid,uuid)",
        "respondToPermissionRequest": "v13_complete(uuid,uuid,integer,bigint,text,jsonb)",
        "shutdown": "unsupported",
    },
    "lease_columns": ["lease_owner", "lease_until"],
    "chains": [
        {
            "id": "agent_run_poll",
            "call": "executeWait",
            "forcePoll": True,
            "file": "repoprompt-ce/Sources/RepoPrompt/Infrastructure/MCP/Agent/AgentRunMCPToolService.swift",
            "lines": "425-426",
        },
        {
            "id": "session_link_poll",
            "call": "executePoll",
            "file": "repoprompt-ce/Sources/RepoPrompt/Infrastructure/MCP/Agent/AgentSessionLinkMCPToolService.swift",
            "call_line": 124,
            "def_line": 366,
        },
    ],
    "notes": {
        "observe_poll": "pg_readonly_state_observe; hint_is_not_wake",
        "startOrResume": "not_stage42_session_create_path; lease_columns_are_not_task_lease",
    },
    "not_claimed": [
        "worktree_bind",
        "worktree_merge",
        "auto_wake",
        "oracle_lanes",
        "claimedProcessID",
        "request_attention",
        "v13_ce_shutdown",
        "v13_requeue_stale",
        "v13_renew_lease",
    ],
}
TOP_KEYS = [
    "chains",
    "lease_columns",
    "map",
    "not_claimed",
    "notes",
    "schema_version",
]
MAP_KEYS = [
    "interruptTurn",
    "observe_poll",
    "respondToPermissionRequest",
    "sendUserMessage",
    "shutdown",
    "startOrResume",
    "steerUserTurn",
]
SIG_KEYS = (
    "observe_poll",
    "startOrResume",
    "sendUserMessage",
    "steerUserTurn",
    "interruptTurn",
    "respondToPermissionRequest",
)
NOTE_SEMIS = (
    "pg_readonly_state_observe; hint_is_not_wake",
    "not_stage42_session_create_path; lease_columns_are_not_task_lease",
)
TABLES = ("events", "effects", "sessions", "tools", "v13_policies")
CLOSED = (
    "cmap_install_function_delta",
    "cmap_regprocedure",
    "cmap_one_zero_arg",
    "cmap_return_jsonb",
    "cmap_language_sql",
    "cmap_stable",
    "cmap_invoker",
    "cmap_not_strict",
    "cmap_search_path",
    "cmap_owner_current_user",
    "cmap_acl_public_revoked",
    "cmap_acl_route_granted",
    "cmap_acl_recall_denied",
    "cmap_acl_resolve_denied",
    "cmap_execute_grantees_closed",
    "cmap_comment_exact",
    "cmap_source_install_sequence",
    "cmap_json_equal",
    "cmap_top_keys",
    "cmap_map_keys",
    "cmap_shutdown_typeof",
    "cmap_shutdown_unsupported",
    "cmap_signatures_no_space",
    "cmap_chains_equal",
    "cmap_notes_equal",
    "cmap_not_claimed_equal",
    "cmap_answer_absent",
    "cmap_observe_regproc",
    "cmap_enqueue_regproc",
    "cmap_append_event_regproc",
    "cmap_steer_regproc",
    "cmap_cancel_two_regproc",
    "cmap_cancel_one_exists",
    "cmap_cancel_one_unmapped",
    "cmap_complete_six_regproc",
    "cmap_complete_five_exists",
    "cmap_complete_five_unmapped",
    "cmap_lease_owner_column",
    "cmap_lease_until_column",
    "cmap_no_ce_shutdown_proc",
    "cmap_not_a_tool",
    "cmap_no_ce_map_policy",
    "cmap_classify_present",
    "cmap_executor_policy_present",
    "cmap_prosrc_one_select",
    "cmap_install_events_unchanged",
    "cmap_install_effects_unchanged",
    "cmap_install_sessions_unchanged",
    "cmap_install_tools_unchanged",
    "cmap_install_policies_unchanged",
    "cmap_call_events_unchanged",
    "cmap_call_effects_unchanged",
    "cmap_call_sessions_unchanged",
    "cmap_call_tools_unchanged",
    "cmap_call_policies_unchanged",
    "cmap_repeat_json_equal",
    "cmap_def_prints_or_replace",
    "cmap_def_forbidden",
    "cmap_source_forbidden",
    "cmap_extra_arg_rejected",
    "cmap_second_create_fails",
    "cmap_test_no_network",
    "cmap_names_closed",
)
RECORDED = []


def piece(*parts):
    return "".join(parts)


def net_banned():
    return (
        piece("soc", "ket."),
        piece("url", "lib"),
        piece("http", ".client"),
        piece("re", "quests"),
        piece("htt", "px"),
        piece("db", "link"),
    )


def lower_banned():
    return net_banned()[5:] + (
        "pg_net",
        "lo_import",
        "lo_export",
        "pg_read_file",
        "pg_write_file",
        "copy program",
        "13002",
        "13003",
        "security definer",
    )


def exact_banned():
    return (
        "CREATE OR REPLACE FUNCTION public.v13_claim(",
        "v13_external_exec_classify",
        "external_executor",
    )


def check(name, ok, detail=""):
    RECORDED.append(name)
    mark = "PASS" if ok else "FAIL"
    extra = ""
    if detail != "" and not ok:
        extra = ": %s" % (detail,)
    print("[%s] %s%s" % (mark, name, extra))
    if not ok:
        raise AssertionError("%s: %s" % (name, detail))


def q1(cur, sql, params=None):
    cur.execute(sql, params)
    row = cur.fetchone()
    return None if row is None else row[0]


def counts(cur):
    return {name: q1(cur, "SELECT count(*) FROM " + name) for name in TABLES}


def identities(cur):
    cur.execute(
        """
        SELECT n.nspname || '.' || p.proname || '('
               || pg_get_function_identity_arguments(p.oid) || ')'
          FROM pg_proc p
          JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname = 'public'
        """)
    return {row[0] for row in cur.fetchall()}


def json_text(value):
    if isinstance(value, str):
        return value
    return json.dumps(value)


def parse_json(value):
    if isinstance(value, str):
        return json.loads(value)
    return value


def jsonb_equal(cur, left, right):
    return q1(cur, "SELECT %s::jsonb = %s::jsonb", (json_text(left), json_text(right))) is True


def show_pair(actual, expected):
    return "actual=%s expected=%s" % (
        json.dumps(parse_json(actual), ensure_ascii=False, sort_keys=True),
        json.dumps(expected, ensure_ascii=False, sort_keys=True),
    )


def split_statements(text):
    parts = []
    buf = []
    i = 0
    n = len(text)
    in_single = False
    dollar = None
    while i < n:
        if dollar is not None:
            if text.startswith(dollar, i):
                buf.append(dollar)
                i += len(dollar)
                dollar = None
            else:
                buf.append(text[i])
                i += 1
            continue
        if in_single:
            buf.append(text[i])
            if text[i] == "'":
                if i + 1 < n and text[i + 1] == "'":
                    buf.append("'")
                    i += 2
                    continue
                in_single = False
            i += 1
            continue
        if text.startswith("--", i):
            nl = text.find("\n", i)
            i = n if nl < 0 else nl + 1
            continue
        if text[i] == "'":
            in_single = True
            buf.append(text[i])
            i += 1
            continue
        if text[i] == "$":
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] == "_"):
                j += 1
            if j < n and text[j] == "$":
                dollar = text[i:j + 1]
                buf.append(dollar)
                i = j + 1
                continue
        if text[i] == ";":
            stmt = "".join(buf).strip()
            if stmt:
                parts.append(stmt)
            buf = []
            i += 1
            continue
        buf.append(text[i])
        i += 1
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def norm_sql(text):
    return re.sub(r"\s+", " ", text).strip()


def source_sequence_ok(text):
    if "INSERT" in text.upper():
        return False
    if "IF NOT EXISTS" in text.upper():
        return False
    if "CREATE OR REPLACE FUNCTION public.v13_ce_map" in text:
        return False
    parts = split_statements(text)
    if len(parts) != 6:
        return False
    if norm_sql(parts[0]) != "BEGIN":
        return False
    if not parts[1].lstrip().startswith("CREATE FUNCTION public.v13_ce_map()"):
        return False
    if norm_sql(parts[2]) != "REVOKE EXECUTE ON FUNCTION public.v13_ce_map() FROM PUBLIC":
        return False
    if norm_sql(parts[3]) != "GRANT EXECUTE ON FUNCTION public.v13_ce_map() TO v13_route":
        return False
    if not parts[4].lstrip().startswith("COMMENT ON FUNCTION public.v13_ce_map() IS"):
        return False
    if norm_sql(parts[5]) != "COMMIT":
        return False
    return True


def forbidden_ok(text):
    low = text.lower()
    for token in lower_banned():
        if token in low:
            return False
    for token in exact_banned():
        if token in text:
            return False
    return True


def prosrc_one_select(src):
    body = src.strip()
    if not body.startswith("SELECT"):
        return False
    if "::jsonb" not in body:
        return False
    rest = body
    for semi in NOTE_SEMIS:
        if semi not in rest:
            return False
        rest = rest.replace(semi, "", 1)
    if ";" in rest:
        return False
    norm = re.sub(r"\s+", " ", body.lower())
    for token in (" from ", "insert", "update", "delete", "pg_proc", "v13_policies"):
        if token in norm:
            return False
    return True


def reg_present(cur, sig):
    return q1(cur, "SELECT to_regprocedure(%s) IS NOT NULL", (sig,)) is True


def fn_count(cur):
    return q1(
        cur,
        """
        SELECT count(*)
          FROM pg_proc p
          JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname = 'public'
           AND p.proname = 'v13_ce_map'
           AND p.pronargs = 0
        """)


def execute_grantees(cur):
    cur.execute(
        """
        SELECT a.grantee::regrole::text
          FROM pg_proc p
          CROSS JOIN LATERAL aclexplode(p.proacl) a
         WHERE p.oid = 'public.v13_ce_map()'::regprocedure
           AND a.privilege_type = 'EXECUTE'
        """)
    return {row[0] for row in cur.fetchall()}


def privilege_absent(cur, role):
    return q1(
        cur,
        """
        SELECT NOT EXISTS (
          SELECT 1
            FROM pg_proc p
            CROSS JOIN LATERAL aclexplode(p.proacl) a
           WHERE p.oid = 'public.v13_ce_map()'::regprocedure
             AND a.grantee = %s::regrole
             AND a.privilege_type = 'EXECUTE'
        )
        """,
        (role,),
    ) is True


def main():
    server = get_server()
    conn = None
    try:
        if setup_db() != 0:
            return 1
        conn = psycopg2.connect(server.get_uri(DB))
        conn.autocommit = False
        cur = conn.cursor()
        before_ids = identities(cur)
        before_counts = counts(cur)
        conn.commit()
        run_psql(server, DB, SQL)
        after_ids = identities(cur)
        install_after = counts(cur)
        call_before = counts(cur)
        first = q1(cur, "SELECT public.v13_ce_map()")
        call_mid = counts(cur)
        second = q1(cur, "SELECT public.v13_ce_map()")
        call_after = counts(cur)
        first_obj = parse_json(first)
        added = after_ids - before_ids
        removed = before_ids - after_ids
        check(
            "cmap_install_function_delta",
            added == {"public.v13_ce_map()"} and not removed,
            (sorted(added), sorted(removed)),
        )
        check("cmap_regprocedure", reg_present(cur, "public.v13_ce_map()"))
        row = q1(
            cur,
            """
            SELECT count(*)
              FROM pg_proc p
              JOIN pg_namespace n ON n.oid = p.pronamespace
             WHERE n.nspname = 'public' AND p.proname = 'v13_ce_map'
            """)
        args = q1(
            cur,
            """
            SELECT p.pronargs
              FROM pg_proc p
              JOIN pg_namespace n ON n.oid = p.pronamespace
             WHERE n.nspname = 'public' AND p.proname = 'v13_ce_map'
            """)
        check("cmap_one_zero_arg", row == 1 and args == 0, (row, args))
        check(
            "cmap_return_jsonb",
            q1(
                cur,
                """
                SELECT p.prorettype = 'jsonb'::regtype
                  FROM pg_proc p
                 WHERE p.oid = 'public.v13_ce_map()'::regprocedure
                """,
            ) is True,
        )
        check(
            "cmap_language_sql",
            q1(
                cur,
                """
                SELECT l.lanname
                  FROM pg_proc p
                  JOIN pg_language l ON l.oid = p.prolang
                 WHERE p.oid = 'public.v13_ce_map()'::regprocedure
                """,
            ) == "sql",
        )
        check(
            "cmap_stable",
            q1(
                cur,
                "SELECT provolatile FROM pg_proc WHERE oid = 'public.v13_ce_map()'::regprocedure",
            ) == "s",
        )
        check(
            "cmap_invoker",
            q1(
                cur,
                "SELECT prosecdef FROM pg_proc WHERE oid = 'public.v13_ce_map()'::regprocedure",
            ) is False,
        )
        check(
            "cmap_not_strict",
            q1(
                cur,
                "SELECT proisstrict FROM pg_proc WHERE oid = 'public.v13_ce_map()'::regprocedure",
            ) is False,
        )
        check(
            "cmap_search_path",
            q1(
                cur,
                """
                SELECT cardinality(proconfig) = 1
                   AND replace(proconfig[1], ' ', '') = 'search_path=pg_catalog,public'
                  FROM pg_proc
                 WHERE oid = 'public.v13_ce_map()'::regprocedure
                """,
            ) is True,
        )
        check(
            "cmap_owner_current_user",
            q1(
                cur,
                """
                SELECT r.rolname = current_user
                  FROM pg_proc p
                  JOIN pg_roles r ON r.oid = p.proowner
                 WHERE p.oid = 'public.v13_ce_map()'::regprocedure
                """,
            ) is True,
        )
        check(
            "cmap_acl_public_revoked",
            q1(
                cur,
                """
                SELECT p.proacl IS NOT NULL
                   AND NOT EXISTS (
                     SELECT 1
                       FROM aclexplode(p.proacl) a
                      WHERE a.grantee = 0
                        AND a.privilege_type = 'EXECUTE'
                   )
                  FROM pg_proc p
                 WHERE p.oid = 'public.v13_ce_map()'::regprocedure
                """,
            ) is True,
        )
        check(
            "cmap_acl_route_granted",
            q1(
                cur,
                """
                SELECT EXISTS (
                  SELECT 1
                    FROM pg_proc p
                    CROSS JOIN LATERAL aclexplode(p.proacl) a
                   WHERE p.oid = 'public.v13_ce_map()'::regprocedure
                     AND a.grantee = 'v13_route'::regrole
                     AND a.privilege_type = 'EXECUTE'
                )
                """,
            ) is True,
        )
        check("cmap_acl_recall_denied", privilege_absent(cur, "v13_recall"))
        check("cmap_acl_resolve_denied", privilege_absent(cur, "v13_resolve"))
        grantees = execute_grantees(cur)
        owner = q1(cur, "SELECT current_user::regrole::text")
        route = q1(cur, "SELECT 'v13_route'::regrole::text")
        check(
            "cmap_execute_grantees_closed",
            grantees == {owner, route},
            sorted(grantees),
        )
        check(
            "cmap_comment_exact",
            q1(
                cur,
                "SELECT obj_description('public.v13_ce_map()'::regprocedure, 'pg_proc')",
            ) == COMMENT,
        )
        check("cmap_source_install_sequence", source_sequence_ok(SQL), split_statements(SQL))
        json_ok = jsonb_equal(cur, first, EXPECTED)
        check("cmap_json_equal", json_ok, "" if json_ok else show_pair(first, EXPECTED))
        top = q1(
            cur,
            """
            SELECT coalesce(array_agg(k ORDER BY k), ARRAY[]::text[])
              FROM jsonb_object_keys(%s::jsonb) AS k
            """,
            (json_text(first),),
        )
        check("cmap_top_keys", list(top) == TOP_KEYS, list(top))
        map_keys = q1(
            cur,
            """
            SELECT coalesce(array_agg(k ORDER BY k), ARRAY[]::text[])
              FROM jsonb_object_keys((%s::jsonb)->'map') AS k
            """,
            (json_text(first),),
        )
        check("cmap_map_keys", list(map_keys) == MAP_KEYS, list(map_keys))
        check(
            "cmap_shutdown_typeof",
            q1(
                cur,
                "SELECT jsonb_typeof((%s::jsonb)->'map'->'shutdown')",
                (json_text(first),),
            ) == "string",
        )
        check(
            "cmap_shutdown_unsupported",
            q1(
                cur,
                "SELECT (%s::jsonb)->'map'->>'shutdown'",
                (json_text(first),),
            ) == "unsupported",
        )
        sigs = [first_obj["map"][key] for key in SIG_KEYS]
        check(
            "cmap_signatures_no_space",
            all(" " not in sig and not sig.startswith("public.") for sig in sigs),
            sigs,
        )
        chains_ok = jsonb_equal(cur, first_obj["chains"], EXPECTED["chains"])
        check(
            "cmap_chains_equal",
            chains_ok,
            "" if chains_ok else show_pair(first_obj["chains"], EXPECTED["chains"]),
        )
        notes_ok = jsonb_equal(cur, first_obj["notes"], EXPECTED["notes"])
        check(
            "cmap_notes_equal",
            notes_ok,
            "" if notes_ok else show_pair(first_obj["notes"], EXPECTED["notes"]),
        )
        claimed_ok = jsonb_equal(cur, first_obj["not_claimed"], EXPECTED["not_claimed"])
        check(
            "cmap_not_claimed_equal",
            claimed_ok,
            "" if claimed_ok else show_pair(first_obj["not_claimed"], EXPECTED["not_claimed"]),
        )
        returned = q1(cur, "SELECT (%s::jsonb)::text", (json_text(first),))
        check(
            "cmap_answer_absent",
            "v13_agentctl_answer" not in returned and "v13_agentctl_answer" not in SQL,
        )
        check("cmap_observe_regproc", reg_present(cur, "public.v13_agentctl_observe(uuid,jsonb)"))
        check("cmap_enqueue_regproc", reg_present(cur, "public.v13_enqueue_effect(uuid,text,jsonb,text)"))
        check("cmap_append_event_regproc", reg_present(cur, "public.v13_append_event(uuid,uuid,text,jsonb,uuid)"))
        check("cmap_steer_regproc", reg_present(cur, "public.v13_agentctl_steer(uuid,jsonb)"))
        check("cmap_cancel_two_regproc", reg_present(cur, "public.v13_cancel(uuid,uuid)"))
        check("cmap_cancel_one_exists", reg_present(cur, "public.v13_cancel(uuid)"))
        check("cmap_cancel_one_unmapped", first_obj["map"]["interruptTurn"] != "v13_cancel(uuid)")
        check(
            "cmap_complete_six_regproc",
            reg_present(cur, "public.v13_complete(uuid,uuid,integer,bigint,text,jsonb)"),
        )
        check(
            "cmap_complete_five_exists",
            reg_present(cur, "public.v13_complete(uuid,integer,bigint,text,jsonb)"),
        )
        check(
            "cmap_complete_five_unmapped",
            first_obj["map"]["respondToPermissionRequest"]
            != "v13_complete(uuid,integer,bigint,text,jsonb)",
        )
        owner_type = q1(
            cur,
            """
            SELECT data_type FROM information_schema.columns
             WHERE table_schema = 'public'
               AND table_name = 'effects'
               AND column_name = 'lease_owner'
            """,
        )
        until_type = q1(
            cur,
            """
            SELECT data_type FROM information_schema.columns
             WHERE table_schema = 'public'
               AND table_name = 'effects'
               AND column_name = 'lease_until'
            """,
        )
        check("cmap_lease_owner_column", owner_type == "text", owner_type)
        check("cmap_lease_until_column", until_type == "timestamp with time zone", until_type)
        check(
            "cmap_no_ce_shutdown_proc",
            q1(cur, "SELECT count(*) FROM pg_proc WHERE proname = 'v13_ce_shutdown'") == 0,
        )
        check(
            "cmap_not_a_tool",
            q1(
                cur,
                """
                SELECT count(*) FROM tools
                 WHERE name IN ('ce_map', 'v13_ce_map')
                    OR handler IN ('ce_map', 'v13_ce_map')
                """,
            ) == 0,
        )
        check(
            "cmap_no_ce_map_policy",
            q1(cur, "SELECT count(*) FROM v13_policies WHERE name = 'ce_map'") == 0,
        )
        check(
            "cmap_classify_present",
            reg_present(cur, "public.v13_external_exec_classify(uuid,jsonb)"),
        )
        check(
            "cmap_executor_policy_present",
            q1(
                cur,
                """
                SELECT EXISTS (
                  SELECT 1 FROM v13_policies
                   WHERE name = 'external_executor' AND active AND version = 1
                )
                """,
            ) is True,
        )
        prosrc = q1(
            cur,
            "SELECT prosrc FROM pg_proc WHERE oid = 'public.v13_ce_map()'::regprocedure",
        )
        check("cmap_prosrc_one_select", prosrc_one_select(prosrc), prosrc)
        for table in TABLES:
            check(
                "cmap_install_%s_unchanged" % ("policies" if table == "v13_policies" else table),
                before_counts[table] == install_after[table],
                (before_counts[table], install_after[table]),
            )
        call_names = {
            "events": "cmap_call_events_unchanged",
            "effects": "cmap_call_effects_unchanged",
            "sessions": "cmap_call_sessions_unchanged",
            "tools": "cmap_call_tools_unchanged",
            "v13_policies": "cmap_call_policies_unchanged",
        }
        for table, name in call_names.items():
            same = call_before[table] == call_mid[table] == call_after[table]
            check(
                name,
                same,
                "" if same else (call_before[table], call_mid[table], call_after[table]),
            )
        repeat_ok = jsonb_equal(cur, first, second)
        check(
            "cmap_repeat_json_equal",
            repeat_ok,
            "" if repeat_ok else show_pair(first, parse_json(second)),
        )
        definition = q1(cur, "SELECT pg_get_functiondef('public.v13_ce_map()'::regprocedure)")
        check(
            "cmap_def_prints_or_replace",
            "CREATE OR REPLACE FUNCTION public.v13_ce_map()" in definition,
            definition,
        )
        check("cmap_def_forbidden", forbidden_ok(definition), definition)
        check(
            "cmap_source_forbidden",
            forbidden_ok(SQL)
            and "CREATE FUNCTION public.v13_ce_map()" in SQL
            and "CREATE OR REPLACE FUNCTION public.v13_ce_map" not in SQL,
        )
        cur.execute("SAVEPOINT cmap_extra_arg")
        rejected = False
        try:
            cur.execute("SELECT public.v13_ce_map(NULL)")
            cur.fetchone()
        except psycopg2.Error:
            rejected = True
        cur.execute("ROLLBACK TO SAVEPOINT cmap_extra_arg")
        check("cmap_extra_arg_rejected", rejected and fn_count(cur) == 1, (rejected, fn_count(cur)))
        raised = False
        try:
            run_psql(server, DB, SQL)
        except RuntimeError:
            raised = True
        still = fn_count(cur)
        same_json = q1(
            cur,
            "SELECT public.v13_ce_map() = %s::jsonb",
            (json.dumps(EXPECTED),),
        ) is True
        check("cmap_second_create_fails", raised and still == 1 and same_json, (raised, still, same_json))
        banned = net_banned()
        net_ok = all(token not in TEST_SRC and token not in SETUP_SRC for token in banned)
        check("cmap_test_no_network", net_ok, [token for token in banned if token in TEST_SRC or token in SETUP_SRC])
        recorded = list(RECORDED)
        missing = [name for name in CLOSED if name != "cmap_names_closed" and name not in recorded]
        extra = [name for name in recorded if name not in CLOSED]
        dupes = sorted({name for name in recorded if recorded.count(name) > 1})
        check(
            "cmap_names_closed",
            not missing and not extra and not dupes and len(recorded) == len(CLOSED) - 1,
            {"missing": missing, "extra": extra, "dupes": dupes},
        )
    finally:
        try:
            if conn is not None:
                conn.close()
        finally:
            if setup_mod.CREATED:
                try:
                    if DB != setup_mod.DB or not DB.startswith("ll_ce_map_"):
                        raise RuntimeError("refuse drop " + DB)
                    run_psql(server, "postgres", 'DROP DATABASE "%s" WITH (FORCE);' % DB)
                    setup_mod.CREATED = False
                    print("[dropped]", DB)
                except Exception as exc:
                    print("[cleanup-fail]", exc)
                    raise SystemExit(1)
    print("[ok] %s checks" % len(RECORDED))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        print("[FAIL]", exc)
        raise SystemExit(1)
