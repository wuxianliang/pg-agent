"""Phase C goal_supervisor gate.

Run: UV_FROZEN=1 uv run python v13/goal_supervisor/test_goal_supervisor.py

unattended_continuation is accepted as a trailing non-zero
`v13: supervisor: ask_user` after every other assert passes.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import psycopg2
from psycopg2.extensions import TRANSACTION_STATUS_IDLE

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v13.load import run_psql
from v13.goal_supervisor.setup_db import DB, main as setup_db
import v13.goal_supervisor.setup_db as setup_mod
from v13.goal_supervisor.driver import (
    ALLOWED_V13,
    GoalSupervisor,
    SupervisorFail,
    UNPAID_REMAINING,
)
from v13.loop_driver.driver import LoopDriver

N = 0
ASK_USER = "v13: supervisor: ask_user"
R1 = "93a49cdfbbb5293c956c53a385a772258636721b"
PROGRESS = {"result_kind": "progress"}
FINISH = {"result_kind": "finish", "delivery_kind": "LOUD-BUT-BLIND"}
WAITP = {
    "result_kind": "wait", "wait_reason": "evidence",
    "wake": {"kind": "not_before", "at": "2099-01-01T00:00:00Z"},
}
REJECT = {"result_kind": "reject"}


def check(label, condition, detail=""):
    global N
    N += 1
    mark = "PASS" if condition else "FAIL"
    extra = f": {detail}" if detail and (not condition or len(str(detail)) < 280) else ""
    print(f"[{mark}] {label}{extra}")
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def u():
    return str(uuid.uuid4())


def sha(text):
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def as_obj(value):
    if value is None:
        return None
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


def open_root(cur):
    sid = str(q1(
        cur, "SELECT v13_open_session(%s::jsonb)",
        (json.dumps({"route_policy_name": "default", "version": 2}),)))
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (sid, u(), json.dumps({"text": "m3 goal"})))
    q1(cur, "SELECT v13_submit_override(%s::uuid, %s::jsonb)",
       (sid, json.dumps({
           "schema_version": 1, "intent": "direct",
           "reason": "", "source_principal": "operator"})))
    ver = q1(cur, "SELECT route_policy_version FROM sessions WHERE session_id=%s", (sid,))
    if ver != 2:
        raise AssertionError(("root version", ver))
    return sid


def harness_req(cur, sid):
    probe = as_obj(q1(cur, "SELECT v13_probe(%s)", (sid,)))
    return {
        "tool": "harness_turn", "params": {},
        "handler": "worker:harness_turn",
        "tools_revision": probe["tools_revision"],
        "logical_turn_id": u(), "continuation_index": 0,
    }


def enqueue(cur, sid, kind, request, tool_name=None):
    if tool_name:
        return str(q1(cur, "SELECT v13_enqueue_effect(%s, %s, %s::jsonb, %s)",
                      (sid, kind, json.dumps(request), tool_name)))
    return str(q1(cur, "SELECT v13_enqueue_effect(%s, %s, %s::jsonb)",
                  (sid, kind, json.dumps(request))))


def settle(cur, eid, result):
    cur.execute(
        "UPDATE effects SET status='claimed', attempt_no=attempt_no+1, fence=fence+1, "
        "lease_owner='w', lease_until=clock_timestamp()+interval '1 hour' "
        "WHERE effect_id=%s RETURNING attempt_no, fence", (eid,))
    attempt, fence = cur.fetchone()
    cur.execute("SELECT v13_complete(%s, %s, %s, 'succeeded', %s::jsonb)",
                (eid, attempt, fence, json.dumps(result)))
    return cur.fetchone()[0]


def spent(cur, eid):
    return int(q1(
        cur,
        "SELECT count(*) FROM events WHERE source_effect_id=%s AND type=%s",
        (eid, "turn/" + "material_spent")))


def unpaid_ids(cur, sid):
    cur.execute("SELECT effect_id::text FROM v13_unpaid_harness_turn(%s)", (sid,))
    return [row[0] for row in cur.fetchall()]


def fixture_unpaid(cur, result=None, human=False, human_status="ready"):
    sid = open_root(cur)
    eid = enqueue(cur, sid, "tool", harness_req(cur, sid), "harness_turn")
    settle(cur, eid, PROGRESS if result is None else result)
    hid = None
    if human:
        hid = enqueue(
            cur, sid, "human",
            {"schema_version": 1, "interaction_ref": "m3-" + u()})
        if human_status == "claimed":
            cur.execute(
                "UPDATE effects SET status='claimed', lease_owner='m3', "
                "lease_until='infinity' WHERE effect_id=%s", (hid,))
        elif human_status == "unknown":
            cur.execute("UPDATE effects SET status='unknown' WHERE effect_id=%s", (hid,))
            cur.execute(
                "UPDATE sessions SET status=%s WHERE session_id=%s",
                ("blocked_unknown", sid))
    return sid, eid, hid


def make_sup(server):
    return GoalSupervisor(lambda: psycopg2.connect(server.get_uri(DB)))


def names(sup, sid):
    return [name for name, s in sup.calls if s == sid]


def settler_names(sup, sid):
    return [name for name, s in sup.settler.calls if s == sid]


def todo(tid, text=None, cls="advancement_task", status="runnable", verb="add_new",
         due=None):
    text = text or ("todo " + tid)
    return {
        "todo_id": tid, "text": text, "text_hash": sha(text),
        "task_class": cls, "status": status, "due": due, "verb": verb,
    }


def plan_body(todos, based, supersedes=None):
    return {
        "schema_version": 1, "call_kind": "plan_commit",
        "based_on_seq": based, "supersedes": supersedes, "todos": todos,
    }


def writer(cur, sid, canonical):
    cur.execute(
        "SELECT v13_plan_writer(%s::uuid, %s::uuid, %s::uuid, %s, %s::jsonb, %s::timestamptz)",
        (None, sid, u(), canonical["call_kind"], json.dumps(canonical), None))
    return as_obj(cur.fetchone()[0])


def max_seq(cur, sid):
    return q1(cur, "SELECT max(seq) FROM events WHERE session_id=%s", (sid,))


def sort_uuids(cur, ids):
    cur.execute("SELECT id::text FROM unnest(%s::uuid[]) AS id ORDER BY id", (ids,))
    return [row[0] for row in cur.fetchall()]


def plant_opener(cur, sid, status="claimed"):
    eid = enqueue(cur, sid, "tool", harness_req(cur, sid), "harness_turn")
    cur.execute(
        "UPDATE effects SET status=%s, attempt_no=1, fence=1, "
        "lease_owner='v13_workspace_opener', lease_until='infinity' "
        "WHERE effect_id=%s",
        (status, eid))
    return eid


def stripped_source(text):
    text = re.sub(r'""".*?"""', "", text, flags=re.S)
    text = re.sub(r"'''.*?'''", "", text, flags=re.S)
    text = re.sub(r"#.*", "", text)
    return text


def test_stage_bytes():
    from v13.plan_arm.test_plan_arm import r0_source_scope
    check("r0_source_scope",
          r0_source_scope() == "fb295ac6c7459bb98dac57e37883af549d2d8a4c")
    load = subprocess.check_output(
        ["git", "diff", R1, "--", "v13/load.py"], cwd=AGENT_ROOT)
    frozen = [
        "v13/schema", "v13/resolve", "v13/loop", "v13/twophase", "v13/envelope",
        "v13/manifest", "v13/chunks", "v13/recall", "v13/characterize", "v13/filter",
        "v13/memory", "v13/economy", "v13/summary", "v13/periphery", "v13/mgraph",
        "v13/mgraph_assembly", "v13/control", "v13/spawn", "v13/fanout", "v13/triage",
        "v13/seam", "v13/catalog", "v13/acl", "v13/observe", "v13/handoff",
        "v13/should_run", "v13/quota_window", "v13/attention", "v13/govern",
        "v13/workspace_admit", "v13/workspace_exec",
        "v13/plan_arm/v13_plan_arm.sql",
        "v13/loop_driver/driver.py", "v13/loop_driver/v13_loop_driver.sql",
        "v13/goal_supervise/v13_goal_supervise.sql",
        "v13/frontier_gap/v13_frontier_gap.sql",
    ]
    diff = subprocess.check_output(["git", "diff", R1, "--", *frozen], cwd=AGENT_ROOT)
    check("stage_bytes", load == b"" and diff == b"", (load, diff[:200]))


def test_static():
    import ast
    import inspect
    src = (ROOT / "driver.py").read_text()
    tests = (ROOT / "test_goal_supervisor.py").read_text()
    readme = (ROOT / "README.md").read_text()
    body = stripped_source(src)
    found = set(re.findall(r"v13_[a-z0-9_]+", body))
    extra = sorted(found - set(ALLOWED_V13))
    check("static_check", extra == [], extra)
    banned = [
        r"insert\s+into\s+(public\.)?effects",
        r"insert\s+into\s+(public\.)?events",
        r"insert\s+into\s+(public\.)?sessions",
        r"insert\s+into\s+(public\.)?artifacts",
        "turn/" + "material_spent",
        "pg_" + "cron",
        r"api[_-]?key",
    ]
    blob = re.sub(r"\s+", " ", src + "\n" + tests).lower()
    hits = [pat for pat in banned if re.search(pat, blob)]
    check("static_check", hits == [], hits)
    check("driver_does_not_write_material_spent",
          "turn/" + "material_spent" not in src)
    check("settle_once_not_run_turn",
          "run_turn" not in src
          and "v13_harness_settle" not in body
          and "v13_advance" not in body)
    check("named_entry_is_settle_once",
          "settle_once" in inspect.getsource(GoalSupervisor.tick)
          and list(inspect.signature(LoopDriver.settle_once).parameters) == ["self", "sid"])
    check("unattended_not_claimed_by_loop_alone",
          "loop_driver 的表不授权无人值守" in readme
          and "LoopDriver.settle_once" in readme)
    check("no_real_provider",
          not re.search(r"openai|anthropic|deepseek|requests\.(get|post)", src, re.I))
    parked = "prompt" + "-exports"
    parked_dir = "phase-c-m3-" + "parked"
    check("no_parked_draft_import",
          parked not in src and parked_dir not in src
          and parked not in tests)
    check("phase_a_prefix_has_no_unpaid_helper",
          "v13_unpaid_harness_turn" not in (AGENT_ROOT / "v13/loop_driver/driver.py").read_text()
          and "v13_harness_settle" not in (AGENT_ROOT / "v13/loop_driver/driver.py").read_text())
    check("recover_not_on_claim_path",
          "UPDATE effects SET status='claimed'" not in src
          and "v13_claim" not in body)
    section = readme.split("## B6", 1)[1].split("\n## ", 1)[0]
    rows = []
    for line in section.splitlines():
        if not line.startswith("|") or set(line.replace("|", "").strip()) <= set("- "):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and cells[0] not in ("职责",):
            rows.append(cells[0])
    need = [
        "identity", "enqueue", "receipt", "closeout", "projection",
        "cancel classification", "harness observation", "result_kind", "actor",
        "credentials and filesystem", "disposition write permission", "policy",
        "children_terminal observation", "pointer", "fourth-duty",
        "supervision", "lease", "ambiguous hold", "notification",
        "observation", "evidence", "replan obligation",
    ]
    check("b6_rows_present", rows == need, rows)
    fourth = [line for line in section.splitlines() if "| fourth-duty |" in line]
    check("fourth_duty_none_or_live_name",
          fourth and "none" in fourth[0]
          and "v13/plan_arm/v13_plan_arm.sql:332-804" in fourth[0],
          fourth)
    tree = ast.parse(src)
    imports = [n.names[0].name for n in tree.body if isinstance(n, ast.ImportFrom)
               for _ in n.names]
    check("no_parked_draft_import", "run_turn" not in imports)
    check("execute_vs_control_operator_separated",
          "产品 EXECUTE" in readme and "operator 显式 NULL" in readme)


def wait_blocked(server, waiter_pid, holder_pid, worker, timeout=10):
    deadline = time.monotonic() + timeout
    obs = psycopg2.connect(server.get_uri(DB))
    obs.autocommit = True
    try:
        cur = obs.cursor()
        while time.monotonic() < deadline:
            if not worker.is_alive():
                return False
            cur.execute("SELECT pg_blocking_pids(%s)", (waiter_pid,))
            blockers = list(cur.fetchone()[0] or [])
            if holder_pid in blockers:
                return True
            time.sleep(0.05)
        return False
    finally:
        obs.close()


def test_runtime(cur, server):
    src_drv = (AGENT_ROOT / "v13/loop_driver/driver.py").read_text()
    check("named_entry_is_settle_once", "def settle_once" in src_drv)
    ver = q1(cur, "SELECT version FROM v13_policies WHERE name='should_run' AND active")
    check("policy_version_still_3", ver == 3, ver)
    rec_src = q1(cur, "SELECT pg_get_functiondef('public.v13_recover_idle()'::regprocedure)")
    check("recover_not_on_claim_path",
          "INSERT INTO " + "effects" not in rec_src
          and "v13_advance" not in rec_src)

    sid0 = open_root(cur)
    lease_eid = enqueue(cur, sid0, "tool", harness_req(cur, sid0), "harness_turn")
    cur.execute(
        "UPDATE effects SET status='claimed', attempt_no=1, fence=1, "
        "lease_owner='worker', lease_until=clock_timestamp() + interval '5 seconds' "
        "WHERE effect_id=%s", (lease_eid,))
    until0 = q1(cur, "SELECT lease_until FROM effects WHERE effect_id=%s", (lease_eid,))
    cur.connection.commit()
    sup = make_sup(server)
    try:
        sup.tick(sid0, lease_effect_id=lease_eid)
        until1 = q1(cur, "SELECT lease_until FROM effects WHERE effect_id=%s", (lease_eid,))
        check("no_lease_loop",
              names(sup, sid0).count("v13_goal_lease_once") == 1
              and until1 is not None and until1 != until0,
              (until0, until1, names(sup, sid0)))
    finally:
        sup.close()
    cur.execute("UPDATE effects SET status='succeeded' WHERE effect_id=%s", (lease_eid,))
    ids = sort_uuids(cur, [u(), u()])
    carrier, target = ids[0], ids[1]
    first = writer(cur, sid0, plan_body([todo(i) for i in ids], max_seq(cur, sid0)))
    writer(cur, sid0, {
        "schema_version": 1, "call_kind": "todo_delta", "verb": "link_successor",
        "todo_id": carrier, "status_from": "runnable", "status_to": "runnable",
        "binding": None, "due": None, "quarantine": None,
        "text_hash": sha("todo " + carrier),
        "link": {"on": "successor", "id": target},
    })
    writer(cur, sid0, plan_body(
        [todo(carrier, verb="reuse")], max_seq(cur, sid0), supersedes=first["plan_id"]))
    n0 = int(q1(
        cur,
        "SELECT count(*) FROM events WHERE session_id=%s AND type='replan/required'",
        (sid0,)))
    cur.connection.commit()
    sup = make_sup(server)
    try:
        report = sup.tick(sid0, request_stop=True)
        seq = [n for n, s in sup.calls if s == sid0]
        writes = [n for n in seq if n in ("v13_replan_gap_insert", "v13_goal_stop")]
        n1 = int(q1(
            cur,
            "SELECT count(*) FROM events WHERE session_id=%s AND type='replan/required'",
            (sid0,)))
        check("replan_insert_before_stop_only",
              writes == ["v13_replan_gap_insert", "v13_goal_stop"]
              and n1 == n0 + 1
              and report["request_stop_consumed"] is True,
              (writes, n0, n1, report))
    finally:
        sup.close()

    sid_q = open_root(cur)
    cur.connection.commit()
    sup = make_sup(server)
    try:
        report = sup.tick(sid_q)
        check("quiet_does_not_call_advance",
              report["word"] == "waiting"
              and "v13_advance" not in settler_names(sup, sid_q)
              and "settle_once" not in names(sup, sid_q),
              (report["word"], names(sup, sid_q)))
        check("connection_idle_after_settle_once",
              sup.settler.connection().get_transaction_status() == TRANSACTION_STATUS_IDLE)
        check("notify_dto_no_event",
              isinstance(report.get("notify"), dict)
              and int(q1(cur, "SELECT count(*) FROM events WHERE session_id=%s AND type='notify/sent'",
                         (sid_q,))) == 0,
              report.get("notify"))
        check("observe_no_answer",
              isinstance(report.get("observe"), dict)
              and report["observe"].get("pending_human") is False,
              report.get("observe"))
        rec0 = q1(cur, "SELECT count(*) FROM effects WHERE session_id=%s", (sid_q,))
        check("recover_return_does_not_enqueue",
              report.get("recover") is not None
              and q1(cur, "SELECT count(*) FROM effects WHERE session_id=%s", (sid_q,)) == rec0)
        check("provider_word_does_not_start_second_machine",
              getattr(sup.settler, "llm", None) is None
              and sup.ticks_used == 1)
    finally:
        sup.close()

    sid_p, eid_p, _ = fixture_unpaid(cur)
    cur.connection.commit()
    spent0 = spent(cur, eid_p)
    sup = make_sup(server)
    try:
        report = sup.tick(sid_p)
        seq = settler_names(sup, sid_p)
        check("unpaid_progress_calls_advance_once",
              seq.count("v13_advance") == 1
              and spent(cur, eid_p) == spent0 + 1
              and names(sup, sid_p).count("settle_once") == 1,
              (report, seq, spent(cur, eid_p)))
        check("t0_same_txn_root_lock",
              seq.index("sessions_lock") < seq.index("v13_goal_lifecycle")
              and seq.index("v13_goal_lifecycle") < seq.index("v13_advance"),
              seq)
        nowait = psycopg2.connect(server.get_uri(DB))
        try:
            nc = nowait.cursor()
            nc.execute(
                "SELECT 1 FROM sessions WHERE session_id=%s FOR UPDATE NOWAIT",
                (sid_p,))
            check("connection_idle_after_settle_once", nc.fetchone()[0] == 1)
            nowait.rollback()
        finally:
            nowait.close()
        report2 = sup.tick(sid_p)
        check("second_settlement_no_second_receipt",
              spent(cur, eid_p) == spent0 + 1
              and settler_names(sup, sid_p).count("v13_advance") == 1
              and names(sup, sid_p).count("settle_once") == 1,
              (report2, spent(cur, eid_p)))
        check("fake_hop_persists_then_observed",
              unpaid_ids(cur, sid_p) == []
              and report2["unpaid"] == [],
              report2)
    finally:
        sup.close()

    sid_f, eid_f, _ = fixture_unpaid(cur, result=FINISH)
    cur.connection.commit()
    sup = make_sup(server)
    try:
        sup.tick(sid_f)
        check("unpaid_finish_calls_advance_once",
              settler_names(sup, sid_f).count("v13_advance") == 1
              and spent(cur, eid_f) == 1)
    finally:
        sup.close()

    for label, payload in (("wait", WAITP), ("reject", REJECT)):
        sid_w, eid_w, _ = fixture_unpaid(cur, result=payload)
        cur.connection.commit()
        sup = make_sup(server)
        try:
            word = sup.tick(sid_w)
            check("wait_reject_not_settled",
                  spent(cur, eid_w) == 0
                  and "v13_advance" not in settler_names(sup, sid_w)
                  and "settle_once" not in names(sup, sid_w),
                  (label, word, settler_names(sup, sid_w)))
        finally:
            sup.close()

    sid_t0, eid_t0, _ = fixture_unpaid(cur)
    q1(cur, "SELECT v13_goal_stop(%s, %s)", (sid_t0, "m3-t0"))
    cur.execute(
        "UPDATE effects SET result = result || %s::jsonb WHERE effect_id=%s",
        (json.dumps({"failed": False}), eid_t0))
    fail0 = int(q1(cur, "SELECT count(*) FROM events WHERE session_id=%s AND type='resolve/failed'",
                   (sid_t0,)))
    cur.connection.commit()
    sup = make_sup(server)
    try:
        report = sup.tick(sid_t0, request_stop=True, lease_effect_id=eid_t0)
        seq = names(sup, sid_t0)
        check("stopped_failed_snap_no_advance",
              report["word"] == "skipped_failed"
              and "v13_advance" not in settler_names(sup, sid_t0)
              and spent(cur, eid_t0) == 0
              and int(q1(cur, "SELECT count(*) FROM events WHERE session_id=%s AND type='resolve/failed'",
                         (sid_t0,))) == fail0)
        check("skipped_failed_safe_return_no_lease_recover_replan",
              "v13_goal_lease_once" not in seq
              and "v13_recover_idle" not in seq
              and "v13_replan_gap_insert" not in seq
              and "v13_goal_stop" not in seq
              and report["request_stop_consumed"] is False,
              seq)
    finally:
        sup.close()

    sid_nk, eid_nk, _ = fixture_unpaid(cur)
    q1(cur, "SELECT v13_goal_stop(%s, %s)", (sid_nk, "m3-nokey"))
    cur.connection.commit()
    sup = make_sup(server)
    try:
        report = sup.tick(sid_nk)
        check("stopped_without_failed_key_still_settles",
              report["settle_word"] != "skipped_failed"
              and spent(cur, eid_nk) == 1,
              report)
    finally:
        sup.close()

    sid_h, eid_h, hid_h = fixture_unpaid(cur, human=True, human_status="ready")
    st_h0 = q1(cur, "SELECT status FROM effects WHERE effect_id=%s", (hid_h,))
    cur.connection.commit()
    sup = make_sup(server)
    try:
        report = sup.tick(sid_h, request_stop=True)
        check("human_pending_does_not_skip_settlement",
              names(sup, sid_h).count("settle_once") == 1
              and spent(cur, eid_h) == 1
              and report["word"] == "waiting",
              report)
        check("human_ready_claimed_settles_then_waits",
              q1(cur, "SELECT status FROM effects WHERE effect_id=%s", (hid_h,)) == st_h0
              and report["word"] == "waiting")
        check("human_wait_no_skip",
              q1(cur, "SELECT status FROM effects WHERE effect_id=%s", (hid_h,)) == "ready")
        check("request_stop_not_consumed_on_human_wait",
              report["request_stop_consumed"] is False
              and int(q1(cur, "SELECT count(*) FROM events WHERE session_id=%s AND type='goal/stopped'",
                         (sid_h,))) == 0)
        check("request_stop_does_not_hop",
              getattr(sup.settler, "llm", None) is None
              and "run_turn" not in names(sup, sid_h))
    finally:
        sup.close()

    sid_c, eid_c, hid_c = fixture_unpaid(cur, human=True, human_status="claimed")
    cur.connection.commit()
    sup = make_sup(server)
    try:
        report = sup.tick(sid_c)
        check("human_ready_claimed_settles_then_waits",
              spent(cur, eid_c) == 1 and report["word"] == "waiting"
              and q1(cur, "SELECT status FROM effects WHERE effect_id=%s", (hid_c,)) == "claimed")
    finally:
        sup.close()

    sid_u = open_root(cur)
    hid_u = enqueue(
        cur, sid_u, "human",
        {"schema_version": 1, "interaction_ref": "m3-unk-" + u()})
    cur.execute("UPDATE effects SET status='unknown' WHERE effect_id=%s", (hid_u,))
    cur.execute(
        "UPDATE sessions SET status=%s WHERE session_id=%s",
        ("blocked_unknown", sid_u))
    cur.connection.commit()
    sup = make_sup(server)
    try:
        report = sup.tick(sid_u)
        check("human_unknown_does_not_count_as_success",
              report["word"] == "waiting"
              and "settle_once" not in names(sup, sid_u)
              and q1(cur, "SELECT status FROM effects WHERE effect_id=%s", (hid_u,)) == "unknown",
              report)
    finally:
        sup.close()

    walls = (
        ("unknown", lambda cur, sid, hid: (
            cur.execute("UPDATE effects SET status='unknown' WHERE effect_id=%s", (hid,)),
            cur.execute("UPDATE sessions SET status=%s WHERE session_id=%s",
                        ("blocked_unknown", sid)))),
        ("cancel", lambda cur, sid, hid: q1(cur, "SELECT v13_cancel(%s)", (sid,))),
    )
    for wall, prep in walls:
        sid_w, eid_w, hid_w = fixture_unpaid(cur, human=True, human_status="claimed")
        prep(cur, sid_w, hid_w)
        cur.connection.commit()
        sup = make_sup(server)
        raised = None
        try:
            try:
                sup.tick(sid_w)
            except SupervisorFail as exc:
                raised = str(exc)
            check("waiting_with_unpaid_remaining_is_failure",
                  raised == UNPAID_REMAINING
                  and spent(cur, eid_w) == 0
                  and unpaid_ids(cur, sid_w) == [eid_w],
                  (wall, raised, unpaid_ids(cur, sid_w)))
        finally:
            sup.close()

    sid_st, eid_st, _ = fixture_unpaid(cur)
    cur.connection.commit()
    sup = make_sup(server)
    try:
        def _bump():
            sup.settler.conn.cursor().execute(
                "SELECT v13_submit_override(%s::uuid, %s::jsonb)",
                (sid_st, json.dumps({
                    "schema_version": 1, "intent": "direct",
                    "reason": "", "source_principal": "operator"})))
        sup.settler._r1_before_advance = _bump
        raised = None
        try:
            sup.tick(sid_st)
        except SupervisorFail as exc:
            raised = str(exc)
        check("waiting_with_unpaid_remaining_is_failure",
              raised == UNPAID_REMAINING and spent(cur, eid_st) == 0,
              (raised, unpaid_ids(cur, sid_st)))
    finally:
        sup.close()

    sid_m1, first, _ = fixture_unpaid(cur)
    second = enqueue(cur, sid_m1, "tool", harness_req(cur, sid_m1), "harness_turn")
    settle(cur, second, PROGRESS)
    winner = str(q1(cur, "SELECT v13_harness_predecessor(%s)", (sid_m1,)))
    loser = first if winner == second else second
    cur.connection.commit()
    sup = make_sup(server)
    try:
        sup.tick(sid_m1)
        check("multiple_unpaid_candidates",
              spent(cur, winner) == 1 and spent(cur, loser) == 0,
              (winner, loser, spent(cur, winner), spent(cur, loser)))
    finally:
        sup.close()

    sid_plan = open_root(cur)
    writer(cur, sid_plan, plan_body([todo(u())], max_seq(cur, sid_plan)))
    cur.connection.commit()
    sup = make_sup(server)
    try:
        sup.tick(sid_plan)
        check("planning_does_not_call_advance",
              "v13_advance" not in settler_names(sup, sid_plan)
              and "settle_once" not in names(sup, sid_plan))
    finally:
        sup.close()

    sid_mon = open_root(cur)
    writer(cur, sid_mon, plan_body(
        [todo(u(), cls="continuous_monitor", status="waiting",
              due="2099-01-01T00:00:00Z")],
        max_seq(cur, sid_mon)))
    cur.connection.commit()
    sup = make_sup(server)
    try:
        sup.tick(sid_mon)
        check("monitor_quiet_does_not_call_advance",
              "v13_advance" not in settler_names(sup, sid_mon))
    finally:
        sup.close()

    sid_ws = open_root(cur)
    opener = plant_opener(cur, sid_ws)
    cur.execute(
        "UPDATE effects SET status='succeeded' WHERE effect_id=%s", (opener,))
    cur.connection.commit()
    sup = make_sup(server)
    try:
        sup.tick(sid_ws)
        check("workspace_complete_does_not_call_advance",
              "v13_advance" not in settler_names(sup, sid_ws))
    finally:
        sup.close()

    sid_cl, eid_cl, _ = fixture_unpaid(cur)
    opener_id = plant_opener(cur, sid_cl)
    st0 = q1(cur, "SELECT status FROM effects WHERE effect_id=%s", (opener_id,))
    calls0 = int(q1(
        cur,
        "SELECT count(*) FROM events WHERE session_id=%s AND type='tool/call' "
        "AND payload->>'effect_id' = %s",
        (sid_cl, opener_id)))
    cur.connection.commit()
    sup = make_sup(server)
    try:
        sup.tick(sid_cl)
        check("settlement_does_not_dispatch_claimed_workspace",
              spent(cur, eid_cl) == 1
              and q1(cur, "SELECT status FROM effects WHERE effect_id=%s", (opener_id,)) == st0
              and int(q1(
                  cur,
                  "SELECT count(*) FROM events WHERE session_id=%s AND type='tool/call' "
                  "AND payload->>'effect_id' = %s",
                  (sid_cl, opener_id))) == calls0,
              (st0, opener_id))
    finally:
        sup.close()

    sid_hold = open_root(cur)
    held_id = plant_opener(cur, sid_hold)
    cur.connection.commit()
    sup = make_sup(server)
    try:
        report = sup.tick(sid_hold, lease_effect_id=held_id)
        seq = names(sup, sid_hold)
        check("hold_skips_accept_recover_lease_hop",
              report["hold"] is True
              and "v13_recover_idle" not in seq
              and "v13_goal_lease_once" not in seq
              and "settle_once" not in seq
              and q1(cur, "SELECT status FROM effects WHERE effect_id=%s",
                     (held_id,)) == "claimed",
              (report, seq))
        dto = report.get("notify") or {}
        check("notify_dto_no_event",
              dto.get("deliver") is False and dto.get("reason") == "ambiguous_hold",
              dto)
    finally:
        sup.close()

    test_interleave_stop_wins(cur, server)
    test_interleave_settle_holds(cur, server)


def test_interleave_stop_wins(cur, server):
    sid, eid, _ = fixture_unpaid(cur)
    busy = int(q1(
        cur,
        "SELECT count(*) FROM effects WHERE session_id=%s "
        "AND status IN ('ready','claimed','unknown')", (sid,)))
    check("stop_advance_interleave_stop_wins", busy == 0, busy)
    cur.connection.commit()
    hold = psycopg2.connect(server.get_uri(DB))
    worker = None
    box = {}
    try:
        hc = hold.cursor()
        hc.execute("SELECT pg_backend_pid()")
        hpid = int(hc.fetchone()[0])
        hc.execute("SELECT 1 FROM sessions WHERE session_id=%s FOR UPDATE", (sid,))
        hc.fetchone()

        def work():
            sup = make_sup(server)
            try:
                conn = sup.settler.connection()
                was = conn.autocommit
                conn.autocommit = True
                try:
                    box["pid"] = int(q1(conn.cursor(), "SELECT pg_backend_pid()"))
                finally:
                    conn.autocommit = was
                box["report"] = sup.tick(sid)
                box["calls"] = list(sup.settler.calls)
            except Exception as exc:  # noqa: BLE001
                box["err"] = str(exc)
            finally:
                sup.close()

        worker = threading.Thread(target=work)
        worker.start()
        until = time.monotonic() + 10
        while time.monotonic() < until and box.get("pid") is None:
            if not worker.is_alive():
                break
            time.sleep(0.05)
        check("stop_advance_interleave_stop_wins", box.get("pid") is not None, box)
        blocked = wait_blocked(server, box["pid"], hpid, worker)
        check("stop_advance_interleave_stop_wins", blocked, box)
        payload = as_obj(q1(hc, "SELECT v13_goal_stop(%s, %s)", (sid, "m3-stop-wins")))
        check("stop_advance_interleave_stop_wins",
              isinstance(payload, dict) and payload.get("schema_version") == 1, payload)
        hc.execute(
            "UPDATE effects SET result = result || %s::jsonb WHERE effect_id=%s",
            (json.dumps({"failed": False}), eid))
        hold.commit()
        worker.join(20)
        check("stop_advance_interleave_stop_wins",
              not worker.is_alive()
              and box.get("err") is None
              and (box.get("report") or {}).get("word") == "skipped_failed"
              and "v13_advance" not in [n for n, _ in box.get("calls") or []]
              and spent(cur, eid) == 0,
              box)
    finally:
        if worker is not None and worker.is_alive():
            worker.join(5)
        try:
            hold.rollback()
        except Exception:
            pass
        hold.close()
        cur.connection.commit()


def test_interleave_settle_holds(cur, server):
    sid, eid, hid = fixture_unpaid(cur, human=True, human_status="ready")
    cur.connection.commit()
    held = threading.Event()
    go = threading.Event()
    box = {}
    stop_box = {}
    worker = None
    stopper = None

    def work():
        sup = make_sup(server)
        try:
            def pause():
                box["pid"] = int(q1(sup.settler.conn.cursor(), "SELECT pg_backend_pid()"))
                held.set()
                go.wait(20)
            sup.settler._r1_after_root_lock = pause
            box["report"] = sup.tick(sid)
            box["calls"] = list(sup.settler.calls)
        except Exception as exc:  # noqa: BLE001
            box["err"] = str(exc)
            held.set()
        finally:
            sup.close()

    def stop():
        conn = psycopg2.connect(server.get_uri(DB))
        try:
            cur2 = conn.cursor()
            cur2.execute("SELECT pg_backend_pid()")
            stop_box["pid"] = int(cur2.fetchone()[0])
            try:
                cur2.execute("SELECT v13_goal_stop(%s, %s)", (sid, "m3-settle-holds"))
                stop_box["payload"] = as_obj(cur2.fetchone()[0])
                conn.commit()
            except Exception as exc:  # noqa: BLE001
                diag = getattr(exc, "diag", None)
                stop_box["err"] = (
                    diag.message_primary
                    if diag is not None and diag.message_primary
                    else str(exc))
                conn.rollback()
        finally:
            conn.close()

    try:
        worker = threading.Thread(target=work)
        worker.start()
        if not held.wait(10):
            check("stop_advance_interleave_settle_holds", False, box)
            return
        stopper = threading.Thread(target=stop)
        stopper.start()
        blocked = False
        until = time.monotonic() + 10
        while time.monotonic() < until and stopper.is_alive():
            spid = stop_box.get("pid")
            bpid = box.get("pid")
            if spid and bpid and wait_blocked(server, spid, bpid, stopper):
                blocked = True
                break
            time.sleep(0.05)
        check("stop_advance_interleave_settle_holds", blocked, (box, stop_box))
        go.set()
        worker.join(20)
        stopper.join(20)
        check("stop_advance_interleave_settle_holds",
              not worker.is_alive() and not stopper.is_alive()
              and box.get("err") is None
              and "v13_advance" in [n for n, _ in box.get("calls") or []]
              and spent(cur, eid) == 1
              and q1(cur, "SELECT status FROM effects WHERE effect_id=%s", (hid,)) == "ready"
              and stop_box.get("err") is not None
              and "goal busy" in str(stop_box.get("err")),
              (box, stop_box))
    finally:
        go.set()
        for th in (worker, stopper):
            if th is not None and th.is_alive():
                th.join(10)
        cur.connection.commit()


def run(cur, server):
    test_static()
    test_runtime(cur, server)


def main() -> int:
    print("[db]", DB)
    test_stage_bytes()
    if setup_db() != 0:
        return 1
    server = get_server()
    conn = connect(server)
    failed = None
    try:
        cur = conn.cursor()
        run(cur, server)
        conn.commit()
    except Exception as exc:
        print("[fail]", type(exc).__name__, exc)
        failed = exc
    finally:
        conn.close()
        if setup_mod.CREATED:
            run_psql(server, "postgres", f'DROP DATABASE IF EXISTS "{DB}";')
            print("[dropped]", DB)
    if failed is not None:
        return 1
    print("[ok]", N, "checks")
    print("[FAIL] unattended_continuation:", ASK_USER)
    print(ASK_USER)
    raise SystemExit(ASK_USER)


if __name__ == "__main__":
    raise SystemExit(main())
