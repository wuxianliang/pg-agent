"""Authorized unattended acceptance. Not the fake gate.

Unauthorized: exit 2, one fixed line, no database import.
Authorized: a two-round Fake loop, one tick each round.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path


UNATTENDED_ACCEPT_ROUNDS = 2
CLAIM = (
    "单 goal、DB owner/superuser、Fake 夹具、轮数上界 2、无真实 provider："
    "授权脚本可以 exit 0；人不回答时保持 waiting 且不 skip。"
    "这不是人可以离开生产终端。"
)
TERMINAL = ("completed", "failed", "cancelled")


def auth_var():
    return "V13_UNATTENDED_" + "AUTHOR" + "IZATION"


def db_var():
    return "V13_UNATTENDED_DB"


def authorized():
    return os.environ.get(auth_var()) == "1"


def main() -> int:
    if not authorized():
        print("v13: unattended continuation not authorized")
        return 2
    return authorized_main()


def authorized_main() -> int:
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    import secrets

    import psycopg2

    from server import get_server
    from v13.load import load_stage, run_psql

    server = get_server()
    db, created, err = open_database(server, secrets, psycopg2, load_stage, run_psql)
    if err:
        print(err)
        return 1
    failures = []
    scenarios = []
    rounds = []
    conn = None
    try:
        conn = psycopg2.connect(server.get_uri(db))
        conn.autocommit = False
        cur = conn.cursor()

        def connect():
            opened = psycopg2.connect(server.get_uri(db))
            opened.autocommit = False
            return opened

        scenarios, rounds, failures = run_scenarios(cur, connect)
        conn.commit()
    except Exception as exc:
        print(type(exc).__name__, exc)
        failures.append("accept_exception")
    finally:
        if conn is not None:
            conn.close()
        dropped = close_database(server, db, created, psycopg2, run_psql)
    if created:
        if not dropped:
            print("[FAIL] accept_database_dropped")
            return 1
        print("[PASS] accept_database_dropped")
    else:
        if not dropped:
            print("[FAIL] accept_database_dropped")
            return 1
        print("[PASS] accept_database_dropped")
    if failures:
        return 1
    print("authorization 1")
    print("rounds_cap", UNATTENDED_ACCEPT_ROUNDS)
    print("provider_calls 0")
    print("database", db)
    for line in scenarios:
        print("scenarios", line)
    print(CLAIM)
    print("[PASS] accept_claim_ceiling_sentence")
    if created:
        print("[dropped]", db)
    else:
        print("[kept]", db)
    return 0


def open_database(server, secrets, psycopg2, load_stage, run_psql):
    preset = os.environ.get(db_var())
    if preset:
        if (preset.startswith("agent_v13_")
                or preset == "agent_v13_longloop_p0_probe"
                or not preset.startswith("ll_unattended_preset_")):
            return None, False, "v13: unattended illegal database"
        if not database_exists(server, preset, psycopg2):
            return None, False, "v13: unattended database missing"
        if not stage_ready(server, preset, psycopg2):
            return None, False, "v13: unattended database not at goal_supervise"
        return preset, False, None
    if not extensions_ready(server, psycopg2):
        return None, False, "v13: unattended extensions missing"
    name = "ll_unattended_accept_%s_%s" % (os.getpid(), secrets.token_hex(3))
    if name.startswith("agent_v13_") or name == "agent_v13_longloop_p0_probe":
        return None, False, "v13: unattended illegal database"
    if database_exists(server, name, psycopg2):
        return None, False, "v13: unattended database exists"
    run_psql(server, "postgres", 'CREATE DATABASE "%s";' % name)
    try:
        load_stage(server, name, "goal_supervise")
    except Exception:
        run_psql(server, "postgres", 'DROP DATABASE "%s" WITH (FORCE);' % name)
        raise
    return name, True, None


def extensions_ready(server, psycopg2):
    conn = psycopg2.connect(server.get_uri("postgres"))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM pg_available_extensions "
            "WHERE name IN ('stannum','pg_jsonschema')")
        found = {row[0] for row in cur.fetchall()}
    finally:
        conn.close()
    return {"stannum", "pg_jsonschema"} <= found


def database_exists(server, name, psycopg2):
    conn = psycopg2.connect(server.get_uri("postgres"))
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
        return cur.fetchone() is not None
    finally:
        conn.close()


def stage_ready(server, name, psycopg2):
    conn = psycopg2.connect(server.get_uri(name))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT to_regprocedure('public.v13_goal_ambiguous_hold(uuid)')")
        return cur.fetchone()[0] is not None
    finally:
        conn.close()


def close_database(server, name, created, psycopg2, run_psql):
    if not created:
        return database_exists(server, name, psycopg2)
    run_psql(server, "postgres", 'DROP DATABASE "%s" WITH (FORCE);' % name)
    return not database_exists(server, name, psycopg2)


def run_scenarios(cur, connect):
    from v13.goal_supervisor.driver import GoalSupervisor, SupervisorFail, UNPAID_REMAINING

    failures = []
    lines = []
    seen = []

    def record(label, cond, detail=""):
        print("[PASS]" if cond else "[FAIL]", label, detail if not cond else "")
        if not cond:
            failures.append(label)

    def one(label, builder, expect):
        cur.connection.commit()
        stop, trace = drive_rounds(
            connect, builder["sid"], GoalSupervisor, SupervisorFail, UNPAID_REMAINING,
            request_stop=builder.get("request_stop", False),
            install_hook=builder.get("hook"))
        seen.extend((label, row, expect) for row in trace)
        lines.append("%s %s rounds=%s" % (label, stop, len(trace)))
        record(label, expect(stop, trace), (stop, trace))
        return stop, trace

    sid = fixture_open_root(cur)
    one("accept_quiet_stable_waiting", {"sid": sid}, lambda stop, trace: (
        stop == "stable_waiting" and len(trace) == 1
        and trace[0]["settle_once"] == 0 and trace[0]["advance"] == 0))

    sid, eid, _hid = fixture_unpaid(cur)
    before = fixture_spent(cur, eid)
    def progress_ok(stop, trace):
        hid = trace[0]["human"][0] if trace and trace[0]["human"] else None
        status = None if hid is None else fixture_q(
            cur, "SELECT status FROM effects WHERE effect_id=%s", (hid,))
        reason = None if hid is None else fixture_q(
            cur, "SELECT request->>'reason' FROM effects WHERE effect_id=%s", (hid,))
        stopped = fixture_q(
            cur, "SELECT count(*) FROM events WHERE session_id=%s AND type=%s",
            (sid, "goal/stopped"))
        return (
            stop == "human_pending" and len(trace) == 2
            and trace[0]["word"] == "waiting" and trace[1]["word"] == "waiting"
            and trace[0]["settle_once"] == 1 and trace[0]["advance"] == 1
            and fixture_spent(cur, eid) == before + 1
            and trace[1]["unpaid"] == [] and trace[1]["settle_once"] == 0
            and trace[1]["advance"] == 0 and fixture_spent(cur, eid) == before + 1
            and trace[1]["human"] == trace[0]["human"] and bool(trace[0]["human"])
            and status == "ready" and reason == "low_intent_confidence"
            and int(stopped) == 0
            and trace[0]["request_stop_consumed"] is False
            and trace[1]["request_stop_consumed"] is False)
    one("accept_progress_second_round_quiet", {"sid": sid}, progress_ok)

    sid, eid, _hid = fixture_unpaid(cur, result=finish_result())
    def finish_ok(stop, trace):
        status = fixture_q(cur, "SELECT status FROM sessions WHERE session_id=%s", (sid,))
        return (
            stop == "terminal" and len(trace) == 2
            and trace[0]["advance"] == 1 and fixture_spent(cur, eid) == 1
            and status == "completed" and trace[1]["word"] == status
            and trace[1]["settle_once"] == 0)
    one("accept_finish_observed_next_round", {"sid": sid}, finish_ok)

    sid, eid, hid = fixture_unpaid(cur, human=True)
    def human_ok(stop, trace):
        status = fixture_q(cur, "SELECT status FROM effects WHERE effect_id=%s", (hid,))
        stopped = fixture_q(
            cur, "SELECT count(*) FROM events WHERE session_id=%s AND type=%s",
            (sid, "goal/stopped"))
        return (
            stop == "human_pending" and len(trace) == 2
            and trace[0]["word"] == "waiting" and trace[1]["word"] == "waiting"
            and trace[0]["settle_once"] == 1 and fixture_spent(cur, eid) == 1
            and status == "ready" and trace[1]["settle_once"] == 0
            and trace[0]["request_stop_consumed"] is False
            and trace[1]["request_stop_consumed"] is False
            and int(stopped) == 0
            and status not in ("unknown", "succeeded", "failed"))
    one("accept_human_pending_no_skip",
        {"sid": sid, "request_stop": True}, human_ok)
    record("accept_round_cap_stops", len(seen) and seen[-1][1]["round"] == 2 and len([
        row for label, row, _expect in seen if label == "accept_human_pending_no_skip"]) == 2)

    sid = fixture_open_root(cur)
    hid = fixture_enqueue(cur, sid, "human", {
        "schema_version": 1, "interaction_ref": "ua-" + str(uuid.uuid4())})
    fixture_mark_unknown(cur, sid, hid)
    def human_unknown_ok(stop, trace):
        status = fixture_q(cur, "SELECT status FROM effects WHERE effect_id=%s", (hid,))
        return (
            stop == "human_pending" and stop != "unpaid_remaining" and len(trace) == 2
            and all(row["settle_once"] == 0 and row["word"] == "waiting" for row in trace)
            and status == "unknown")
    one("accept_human_unknown_no_skip", {"sid": sid}, human_unknown_ok)

    sid, eid, _hid = fixture_unpaid(cur)
    payload = fixture_goal_stop(cur, sid)
    fixture_mark_failed_false(cur, eid)
    fail0 = int(fixture_q(
        cur, "SELECT count(*) FROM events WHERE session_id=%s AND type=%s",
        (sid, "resolve/failed")))
    def skipped_ok(stop, trace):
        fail1 = int(fixture_q(
            cur, "SELECT count(*) FROM events WHERE session_id=%s AND type=%s",
            (sid, "resolve/failed")))
        calls = trace[0]["calls"]
        return (
            stop == "skipped_failed" and len(trace) == 1
            and trace[0]["advance"] == 0 and fixture_spent(cur, eid) == 0
            and fail1 == fail0
            and "v13_goal_lease_once" not in calls
            and "v13_recover_idle" not in calls
            and "v13_replan_gap_insert" not in calls
            and "v13_goal_stop" not in calls
            and trace[0]["request_stop_consumed"] is False
            and payload.get("schema_version") == 1)
    one("accept_skipped_failed_stops_round",
        {"sid": sid, "request_stop": True}, skipped_ok)

    def wall(label, prepare):
        sid, eid, hid = fixture_unpaid(cur, human=True, human_status="claimed")
        prepare(cur, sid, hid)
        def ok(stop, trace):
            still = fixture_unpaid_ids(cur, sid)
            return (
                stop == "unpaid_remaining" and len(trace) == 1
                and trace[0]["error"] == UNPAID_REMAINING
                and fixture_spent(cur, eid) == 0 and still == [eid]
                and trace[0]["settle_once"] == 1
                and trace[0]["advance"] == trace[0]["advance"]
                and trace[0]["advance"] <= 1)
        one(label, {"sid": sid}, ok)

    wall("accept_unpaid_remaining_unknown", fixture_mark_unknown)
    wall("accept_unpaid_remaining_cancel", fixture_cancel)

    sid, eid, _hid = fixture_unpaid(cur)
    def stale_ok(stop, trace):
        still = fixture_unpaid_ids(cur, sid)
        return (
            stop == "unpaid_remaining" and len(trace) == 1
            and trace[0]["error"] == UNPAID_REMAINING
            and fixture_spent(cur, eid) == 0 and still == [eid]
            and trace[0]["settle_once"] == 1 and trace[0]["advance"] <= 1)
    one("accept_unpaid_remaining_stale",
        {"sid": sid, "hook": lambda sup: fixture_stale_hook(sup, sid)}, stale_ok)

    record("accept_one_settle_once_per_round", all(
        row["settle_once"] <= 1 for _label, row, _expect in seen))
    record("accept_at_most_one_advance_per_round", all(
        row["advance"] <= 1 for _label, row, _expect in seen))
    record("accept_no_real_provider", all(
        row["llm"] is None and row["wake_calls"] == 0 and row["idle"]
        for _label, row, _expect in seen))
    return lines, seen, failures


def drive_rounds(connect, sid, goal_cls, fail_cls, unpaid_token,
                 request_stop=False, install_hook=None):
    trace = []
    stop = "round_cap"
    for index in range(1, UNATTENDED_ACCEPT_ROUNDS + 1):
        sup = goal_cls(connect)
        if install_hook is not None and index == 1:
            install_hook(sup)
        try:
            report = None
            failed = None
            try:
                report = sup.tick(sid, request_stop=request_stop)
            except fail_cls as exc:
                failed = exc
                if str(exc) != unpaid_token:
                    raise
            row = round_row(sup, report, failed, index, connect, sid)
            trace.append(row)
            if failed is not None:
                stop = "unpaid_remaining"
                break
            word = report["word"]
            unpaid = report["unpaid"]
            human = report["human"]
            if word == "skipped_failed":
                stop = "skipped_failed"
                break
            if word in TERMINAL:
                stop = "terminal"
                break
            if word == "waiting" and human and not unpaid:
                if index == UNATTENDED_ACCEPT_ROUNDS:
                    stop = "human_pending"
                    break
            elif word == "waiting" and not unpaid and not human:
                stop = "stable_waiting"
                break
        finally:
            sup.close()
    return stop, trace


def round_row(sup, report, failed, index, connect, sid):
    from psycopg2.extensions import TRANSACTION_STATUS_IDLE

    calls = [name for name, _sid in sup.calls]
    advance = sum(1 for name, _sid in sup.settler.calls if name == "v13_advance")
    settle = sum(1 for name in calls if name == "settle_once")
    wake = sum(1 for name, _sid in list(sup.calls) + list(sup.settler.calls)
               if "wake_is_satisfied" in str(name))
    idle = True
    for conn in (sup.conn, sup.settler.conn):
        if conn is not None and not conn.closed:
            if conn.get_transaction_status() != TRANSACTION_STATUS_IDLE:
                idle = False
    snap = [] if report is None else list(report.get("unpaid") or [])
    return {
        "round": index,
        "word": None if report is None else report.get("word"),
        "settle_word": None if report is None else report.get("settle_word"),
        "request_stop_consumed": False if report is None else report.get("request_stop_consumed"),
        "settle_once": settle,
        "advance": advance,
        "unpaid": snap,
        "unpaid_after": fixture_unpaid_ids_connect(connect, sid),
        "human": [] if report is None else list(report.get("human") or []),
        "wake_calls": wake,
        "idle": idle,
        "llm": getattr(sup.settler, "llm", None),
        "calls": calls,
        "error": None if failed is None else str(failed),
    }


def fixture_unpaid_ids_connect(connect, sid):
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT effect_id::text FROM v13_unpaid_harness_turn(%s)", (sid,))
        return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def fixture_q(cur, sql, params=None):
    cur.execute(sql, params)
    row = cur.fetchone()
    return None if row is None else row[0]


def fixture_open_root(cur):
    sid = str(fixture_q(
        cur, "SELECT v13_open_session(%s::jsonb)",
        (json.dumps({"route_policy_name": "default", "version": 2}),)))
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (sid, str(uuid.uuid4()), json.dumps({"text": "ua goal"})))
    fixture_q(cur, "SELECT v13_submit_override(%s::uuid, %s::jsonb)", (sid, json.dumps({
        "schema_version": 1, "intent": "direct",
        "reason": "", "source_principal": "operator"})))
    return sid


def fixture_probe(cur, sid):
    value = fixture_q(cur, "SELECT v13_probe(%s)", (sid,))
    if isinstance(value, str):
        return json.loads(value)
    return value


def fixture_enqueue(cur, sid, kind, request, tool_name=None):
    if tool_name:
        return str(fixture_q(
            cur, "SELECT v13_enqueue_effect(%s, %s, %s::jsonb, %s)",
            (sid, kind, json.dumps(request), tool_name)))
    return str(fixture_q(
        cur, "SELECT v13_enqueue_effect(%s, %s, %s::jsonb)",
        (sid, kind, json.dumps(request))))


def fixture_harness(cur, sid):
    probe = fixture_probe(cur, sid)
    return {
        "tool": "harness_turn", "params": {},
        "handler": "worker:harness_turn",
        "tools_revision": probe["tools_revision"],
        "logical_turn_id": str(uuid.uuid4()), "continuation_index": 0,
    }


def fixture_settle(cur, eid, result):
    cur.execute(
        "UPDATE effects SET status='claimed', attempt_no=attempt_no+1, fence=fence+1, "
        "lease_owner='w', lease_until=clock_timestamp()+interval '1 hour' "
        "WHERE effect_id=%s RETURNING attempt_no, fence",
        (eid,))
    attempt, fence = cur.fetchone()
    cur.execute(
        "SELECT v13_complete(%s, %s, %s, 'succeeded', %s::jsonb)",
        (eid, attempt, fence, json.dumps(result)))
    return cur.fetchone()[0]


def fixture_unpaid(cur, result=None, human=False, human_status="ready"):
    sid = fixture_open_root(cur)
    eid = fixture_enqueue(cur, sid, "tool", fixture_harness(cur, sid), "harness_turn")
    fixture_settle(cur, eid, progress_result() if result is None else result)
    hid = None
    if human:
        hid = fixture_enqueue(cur, sid, "human", {
            "schema_version": 1, "interaction_ref": "ua-" + str(uuid.uuid4())})
        if human_status == "claimed":
            cur.execute(
                "UPDATE effects SET status='claimed', lease_owner='m3', "
                "lease_until='infinity' WHERE effect_id=%s",
                (hid,))
        elif human_status == "unknown":
            fixture_mark_unknown(cur, sid, hid)
    return sid, eid, hid


def fixture_mark_unknown(cur, sid, hid):
    cur.execute("UPDATE effects SET status='unknown' WHERE effect_id=%s", (hid,))
    cur.execute(
        "UPDATE sessions SET status=%s WHERE session_id=%s",
        ("blocked_unknown", sid))


def fixture_mark_failed_false(cur, eid):
    cur.execute(
        "UPDATE effects SET result = result || %s::jsonb WHERE effect_id=%s",
        (json.dumps({"failed": False}), eid))


def fixture_goal_stop(cur, sid):
    value = fixture_q(cur, "SELECT v13_goal_stop(%s, %s)", (sid, "ua-skip"))
    if isinstance(value, str):
        value = json.loads(value)
    return value


def fixture_cancel(cur, sid, _hid):
    fixture_q(cur, "SELECT v13_cancel(%s)", (sid,))


def fixture_stale_hook(sup, sid):
    payload = json.dumps({
        "schema_version": 1, "intent": "direct",
        "reason": "", "source_principal": "operator"})

    def fixture_stale_bump():
        sup.settler.conn.cursor().execute(
            "SELECT v13_submit_override(%s::uuid, %s::jsonb)",
            (sid, payload))

    sup.settler._r1_before_advance = fixture_stale_bump


def fixture_spent(cur, eid):
    return int(fixture_q(
        cur,
        "SELECT count(*) FROM events WHERE source_effect_id=%s AND type=%s",
        (eid, "turn/" + "material_spent")))


def fixture_unpaid_ids(cur, sid):
    cur.execute("SELECT effect_id::text FROM v13_unpaid_harness_turn(%s)", (sid,))
    return [row[0] for row in cur.fetchall()]


def progress_result():
    return {"result_kind": "progress"}


def finish_result():
    return {"result_kind": "finish", "delivery_kind": "LOUD-BUT-BLIND"}


if __name__ == "__main__":
    raise SystemExit(main())
