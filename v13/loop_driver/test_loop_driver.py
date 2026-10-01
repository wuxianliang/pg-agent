"""Phase A loop_driver gate.

Run: UV_FROZEN=1 uv run python v13/loop_driver/test_loop_driver.py
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import psycopg2
import psycopg2.extensions

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v13.load import run_psql
from v13.loop_driver.setup_db import DB, main as setup_db
import v13.loop_driver.setup_db as setup_mod
from v13.loop_driver.driver import (
    LoopDriver,
    decide_exit,
    t0_advance_blocked,
    NOT_EXIT_WORDS,
)

N = 0

PROGRESS = {"result_kind": "progress"}
FINISH = {"result_kind": "finish", "delivery_kind": "LOUD-BUT-BLIND"}
WAITP = {"result_kind": "wait", "wait_reason": "evidence",
         "wake": {"kind": "not_before", "at": "2099-01-01T00:00:00Z"}}

FIXTURE_LAYERS = {
    "assertion": "fixture assertion layer text",
    "assembly": "fixture assembly layer text",
    "judgment": "fixture judgment layer text",
    "workflow": "fixture workflow layer text",
}


def check(label, condition, detail=""):
    global N
    N += 1
    mark = "PASS" if condition else "FAIL"
    extra = f": {detail}" if detail and (not condition or len(str(detail)) < 240) else ""
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


def open_root(cur, version=1):
    spec = {"route_policy_name": "default", "version": version}
    return str(q1(cur, "SELECT v13_plan_commit_entry(%s::jsonb)", (json.dumps(spec),)))


def prefix(cur, sid, text="hello goal"):
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (sid, u(), json.dumps({"text": text})))


def max_seq(cur, sid):
    return q1(cur, "SELECT max(seq) FROM events WHERE session_id=%s", (sid,))


def todo(tid, text, cls, status, verb="add_new", due=None):
    return {"todo_id": tid, "text": text, "text_hash": sha(text),
            "task_class": cls, "status": status, "due": due, "verb": verb}


def plan_body(todos, based):
    return {"schema_version": 1, "call_kind": "plan_commit", "based_on_seq": based,
            "supersedes": None, "todos": todos}


def writer(cur, sid, canonical, now=None):
    cur.execute(
        "SELECT v13_plan_writer(%s::uuid, %s::uuid, %s::uuid, %s, %s::jsonb, %s::timestamptz)",
        (None, sid, u(), canonical["call_kind"], json.dumps(canonical), now))
    return as_obj(cur.fetchone()[0])


def seed(cur, specs, text="anchor"):
    sid = open_root(cur)
    prefix(cur, sid, text)
    ids = [spec[0] for spec in specs]
    cur.execute("SELECT id::text FROM unnest(%s::uuid[]) AS id ORDER BY id", (ids,))
    ordered = [row[0] for row in cur.fetchall()]
    by_id = {spec[0]: spec for spec in specs}
    body = plan_body([todo(*by_id[tid]) for tid in ordered], max_seq(cur, sid))
    writer(cur, sid, body)
    return sid, ordered


def fresh(cur):
    sid = open_root(cur)
    prefix(cur, sid)
    return sid


def snap_of(cur, sid):
    cur.execute(
        "UPDATE sessions SET context_active_revision = v13_context_required(session_id) "
        "WHERE session_id=%s", (sid,))
    cur.execute("SELECT v13_probe(%s)", (sid,))
    probe = cur.fetchone()[0]
    probe["sid"] = sid
    return {"snap": probe, "envelope": {"sid": sid}, "remaining": 0,
            "abandon": False, "failed": False}


def advance(cur, sid):
    snap = snap_of(cur, sid)
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid, json.dumps(snap)))
    return cur.fetchone()[0]


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


def bind(cur, sid, tid, text, effect_id, status="runnable"):
    canonical = {
        "schema_version": 1, "call_kind": "todo_delta", "verb": "update",
        "todo_id": tid, "status_from": status, "status_to": status,
        "binding": {"effect_id": effect_id, "child_session_id": None},
        "due": None, "quarantine": None, "text_hash": sha(text), "link": None,
    }
    writer(cur, sid, canonical)


def archive_done(cur, sid, tid, text, status_from="runnable"):
    canonical = {
        "schema_version": 1, "call_kind": "todo_delta", "verb": "update",
        "todo_id": tid, "status_from": status_from, "status_to": "done",
        "binding": None, "due": None, "quarantine": None,
        "text_hash": sha(text), "link": None,
    }
    writer(cur, sid, canonical)


def spec_text(specs, tid):
    for spec in specs:
        if spec[0] == tid:
            return spec[1]
    raise KeyError(tid)


def harness_req(cur, sid):
    probe = as_obj(q1(cur, "SELECT v13_probe(%s)", (sid,)))
    return {"tool": "harness_turn", "params": {}, "handler": "worker:harness_turn",
            "tools_revision": probe["tools_revision"], "logical_turn_id": u(),
            "continuation_index": 0}


def events_n(cur, sid):
    return q1(cur, "SELECT count(*) FROM events WHERE session_id=%s", (sid,))


def plan_n(cur, sid):
    return q1(
        cur,
        "SELECT count(*) FROM events WHERE session_id=%s "
        "AND type IN ('plan/committed','todo/delta')",
        (sid,))


def decisions_n(cur):
    return q1(cur, "SELECT count(*) FROM decisions")


class FakeLLM:
    def __init__(self, driver, answer="driver says ok"):
        self.driver = driver
        self.answer = answer
        self.txn_status = None
        self.calls_n = 0
        self.layer_names = None
        self.layer_texts = None

    def __call__(self, layers, peek):
        self.calls_n += 1
        self.txn_status = self.driver.conn.get_transaction_status()
        self.layer_names = [name for name, _ in layers]
        self.layer_texts = [text for _, text in layers]
        return {"text": self.answer}


def make_driver(server, layers=None, llm_answer="driver says ok", tools=None):
    drv = LoopDriver(lambda: psycopg2.connect(server.get_uri(DB)),
                     llm=None, tools=tools or {}, layers=layers or FIXTURE_LAYERS)
    fake = FakeLLM(drv, llm_answer)
    drv.llm = fake
    return drv, fake


def calls_for(drv, sid):
    return [name for name, s in drv.calls if s == sid]


# ----------------------------------------------------------------------

def test_static_and_readme():
    import re
    paths = sorted(str(p) for p in ROOT.glob("*.py"))
    paths += sorted(str(p) for p in (AGENT_ROOT / "v13" / "real_chain").glob("*.py"))
    check("static_scan_found_files", len(paths) >= 3, paths)
    patterns = [
        r"insert\s+into\s+(public\.)?" + "effects",
        r"insert\s+into\s+(public\.)?" + "events",
        r"insert\s+into\s+(public\.)?" + "sessions",
        r"insert\s+into\s+(public\.)?" + "artifacts",
        "turn/" + "material_spent",
        "pg_" + "cron" + "|cron" + ".schedule",
        r"api" + "[_-]?" + "key",
        "autho" + "rization",
        "system_" + "prompt",
        r"update\s+(public\.)?" + "sessions" + r"\s+set\s+" + "status",
    ]
    bad = []
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            src = re.sub(r"\s+", " ", fh.read()).lower()
        for pat in patterns:
            if re.search(pat, src):
                bad.append((path, pat))
    check("static_check", not bad, bad)
    with open(ROOT / "driver.py", encoding="utf-8") as fh:
        dsrc = re.sub(r"\s+", " ", fh.read()).lower()
    frozen_claim = dsrc.count("update effects set status='claimed', "
                              "attempt_no=attempt_no+1")
    check("claim_update_frozen_once", frozen_claim == 1, frozen_claim)
    check("no_sessions_status_write",
          ("update " + "sessions set " + "status") not in dsrc)
    nocalls = ["v13_recover_idle", "v13_spawn_subsession", "v13_child_pointer",
               "v13_workflow_resolve", "v13_open_session", "v13_insert_nudge",
               "v13_goal_resume", "v13_cancel", "v13_route("]
    hits = [pat for pat in nocalls if pat in dsrc]
    check("no_recover_idle", "v13_recover_idle" not in dsrc, hits)
    check("no_direct_spawn", "v13_spawn_subsession" not in dsrc, hits)
    check("no_closed_set_leak", not hits, hits)
    check("not_exit_words_pinned",
          set(NOT_EXIT_WORDS) == {"repair", "replan",
                                  "capability_adapter_handoff"},
          NOT_EXIT_WORDS)
    with open(ROOT / "README.md", encoding="utf-8") as fh:
        readme = fh.read()
    section = readme.split("## B6", 1)[1].split("\n## ", 1)[0]
    rows = []
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(c.startswith("-") for c in cells):
            continue
        if cells and cells[0] == "职责":
            continue
        rows.append(cells)
    duties = ["identity", "enqueue", "receipt", "closeout", "projection",
              "cancel classification", "harness observation", "result_kind",
              "actor", "credentials and filesystem",
              "disposition write permission", "policy",
              "children_terminal observation", "pointer", "fourth-duty"]
    first_cells = [r[0] for r in rows]
    check("b6_table_complete",
          len(rows) == 15 and all(len(r) == 4 for r in rows)
          and sorted(first_cells) == sorted(duties),
          (len(rows), first_cells))


def test_c7_sql(cur):
    def proj(payload):
        cur.execute("SELECT v13_harness_result_project(%s::jsonb)",
                    (json.dumps(payload),))
        return as_obj(cur.fetchone()[0])

    ok4 = []
    for p in (PROGRESS, FINISH, WAITP, {"result_kind": "reject"}):
        dto = proj(p)
        ok4.append(dto["ok"] is True and dto["result_kind"] == p["result_kind"]
                   and dto["harness"] == p)
    dw = proj(WAITP)
    check("c7_four_kinds_project",
          all(ok4) and dw["wait_reason"] == "evidence", ok4)
    bads = [proj("just prose, not an object"), proj({}),
            proj({"wait_reason": "evidence"}),
            proj({"result_kind": "wait", "wait_reason": "bogus",
                  "wake": WAITP["wake"]}),
            proj({"result_kind": "progress", "extra_key": 1})]
    check("c7_invalid_fail_no_reject",
          all(b["ok"] is False and b["harness"] is None
              and b["result_kind"] is None for b in bads), bads)
    dp = proj(PROGRESS)
    check("c7_wait_reason_absent_stays",
          dp["wait_reason"] is None and "wait_reason" not in dp["harness"], dp)
    cur.execute(
        "SELECT count(*), bool_and(p.provolatile = 's') FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'public' AND p.proname = 'v13_harness_result_project'")
    cnt, stable = cur.fetchone()
    check("c7_single_stable_function", cnt == 1 and stable is True, (cnt, stable))
    check("c7_key_layer_not_allof",
          proj({"result_kind": "wait"})["ok"] is True
          and proj({"result_kind": "progress", "wait_reason": "evidence"})["ok"] is True,
          None)


def test_unit_decide():
    check("unit_terminal",
          all(decide_exit(session_status=st) == "terminal"
              for st in ("completed", "failed", "cancelled")))
    check("unit_stopping",
          decide_exit(session_status="waiting", stop_requested=True) == "stopping")
    check("unit_user_action_fold",
          decide_exit(session_status="waiting", needs_human=True) == "user_action")
    check("unit_user_action_dispatch",
          decide_exit(session_status="waiting", dispatch="operator") == "user_action")
    check("unit_upstream_never_beats_order",
          decide_exit(session_status="completed", upstream_word="repair") == "terminal"
          and decide_exit(session_status="waiting", stop_requested=True,
                          upstream_word="repair") == "stopping"
          and decide_exit(session_status="waiting", needs_human=True,
                          upstream_word="repair") == "user_action"
          and decide_exit(session_status="waiting", plan_gate=True,
                          dispatch="provider", hint="run_now",
                          upstream_word="repair") == "wait")
    waits = [
        dict(session_status="waiting", plan_gate=False, dispatch="provider",
             hint="run_now"),
        dict(session_status="waiting", plan_gate=True, should_run=False,
             dispatch="provider", hint="run_now"),
        dict(session_status="waiting", plan_gate=True, dispatch="provider",
             hint="wait"),
        dict(session_status="waiting", plan_gate=True, dispatch="provider",
             hint="dont_notify"),
        dict(session_status="waiting", plan_gate=True, dispatch="provider",
             hint="run_now", human_pending=True),
        dict(session_status="waiting", plan_gate=True, dispatch=None,
             hint="run_now"),
    ]
    check("unit_wait_conditions",
          all(decide_exit(**kw) == "wait" for kw in waits))
    check("unit_provider",
          decide_exit(session_status="waiting", plan_gate=True, should_run=True,
                      dispatch="provider", hint="run_now") == "provider")
    check("unit_upstream_words",
          all(decide_exit(session_status="waiting", plan_gate=True,
                          dispatch="provider", hint="run_now", upstream_word=w) == "wait"
              for w in NOT_EXIT_WORDS))
    t0 = [t0_advance_blocked("stopped", {"failed": False}) is True,
          t0_advance_blocked("stopped", {"failed": 0}) is True,
          t0_advance_blocked("stopped", {"failed": "boom"}) is True,
          t0_advance_blocked("stopped", {"failed": None}) is False,
          t0_advance_blocked("stopped", {}) is False,
          t0_advance_blocked("active", {"failed": False}) is False]
    check("unit_t0_discipline", all(t0), t0)


def test_exits(cur, server):
    # ---- wait ---------------------------------------------------------
    sid = fresh(cur)
    cur.connection.commit()
    dec_before = decisions_n(cur)
    cur.connection.commit()
    drv, _fake = make_driver(server)
    word, _att = drv.run_turn(sid)
    check("exit_wait", word == "wait", word)
    check("exit_wait_no_requeue",
          calls_for(drv, sid).count("v13_advance:requeue") == 0
          and "v13_complete" not in calls_for(drv, sid), calls_for(drv, sid))
    drv.close()
    cur.connection.commit()
    check("decisions_row_count_unchanged", decisions_n(cur) == dec_before)

    # ---- override before parse ----------------------------------------
    sid2 = fresh(cur)
    cur.connection.commit()
    drv2, _f2 = make_driver(server)
    drv2.run_turn(sid2, first=True)
    ov = q1(cur, "SELECT min(seq) FROM events WHERE session_id=%s AND type='goal/override'", (sid2,))
    rt = q1(cur, "SELECT min(seq) FROM events WHERE session_id=%s AND type='turn/route'", (sid2,))
    seq2 = calls_for(drv2, sid2)
    check("override_before_parse",
          ov is not None and rt is not None and ov < rt
          and seq2.index("v13_submit_override") < seq2.index("v13_advance"),
          (ov, rt, seq2))
    drv2.close()
    cur.connection.commit()

    # ---- workflow_id does not spawn ------------------------------------
    layers = dict(FIXTURE_LAYERS)
    layers["workflow"] = ("fixture workflow layer; workflow_id "
                          "99999999-9999-9999-9999-999999999999 continues the chain")
    sid3 = fresh(cur)
    cur.connection.commit()
    drv3, _f3 = make_driver(server, layers=layers,
                            llm_answer="workflow_id 99999999-9999-9999-9999-999999999999 says continue")
    drv3.run_turn(sid3)
    children = q1(cur, "SELECT count(*) FROM sessions WHERE parent_session_id=%s", (sid3,))
    spawn_fx = q1(cur, "SELECT count(*) FROM effects WHERE session_id=%s AND tool_name='spawn_subsession'", (sid3,))
    check("workflow_id_does_not_spawn", children == 0 and spawn_fx == 0,
          (children, spawn_fx))
    drv3.close()
    cur.connection.commit()

    # ---- user_action ----------------------------------------------------
    tid = u()
    sid4, _ids4 = seed(cur, [(tid, "gate the user", "user_gate", "runnable")])
    cur.connection.commit()
    dec4 = decisions_n(cur)
    cur.connection.commit()
    drv4, _f4 = make_driver(server)
    word4, _a4 = drv4.run_turn(sid4)
    llm_fx = q1(cur, "SELECT count(*) FROM effects WHERE session_id=%s AND kind='llm'", (sid4,))
    human_st = q1(cur, "SELECT status FROM effects WHERE session_id=%s AND kind='human'", (sid4,))
    sess4 = q1(cur, "SELECT status FROM sessions WHERE session_id=%s", (sid4,))
    resp4 = q1(cur, "SELECT count(*) FROM events WHERE session_id=%s AND type='human/responded'", (sid4,))
    check("exit_user_action",
          word4 == "user_action" and llm_fx == 0 and human_st == "ready"
          and sess4 not in ("completed", "failed", "cancelled") and resp4 == 0
          and "v13_complete" not in calls_for(drv4, sid4),
          (word4, llm_fx, human_st, sess4, resp4))
    drv4.close()
    cur.connection.commit()
    check("user_action_decisions_unchanged", decisions_n(cur) == dec4)

    # ---- provider + exactly one requeue ---------------------------------
    tida, tidb = u(), u()
    specs5 = [(tida, "first jump", "advancement_task", "runnable"),
              (tidb, "second jump", "advancement_task", "runnable")]
    sid5, ids5 = seed(cur, specs5)
    archive_done(cur, sid5, ids5[0], spec_text(specs5, ids5[0]))
    cur.connection.commit()
    drv5, _f5 = make_driver(server)
    word5 = drv5.decide(sid5)
    check("exit_provider", word5 == "provider", word5)
    out5 = drv5.take_exit("provider", sid5)
    seq5 = calls_for(drv5, sid5)
    llm5 = q1(cur, "SELECT count(*) FROM effects WHERE session_id=%s AND kind='llm'", (sid5,))
    bfx = q1(cur, "SELECT effect_id IS NOT NULL FROM v13_plan_todo_fold(%s) WHERE todo_id=%s", (sid5, ids5[1]))
    check("provider_requeue_one_advance",
          out5 == "provider" and seq5.count("v13_advance:requeue") == 1
          and seq5.count("v13_advance") == 0 and llm5 == 1 and bfx is True,
          (out5, seq5, llm5, bfx))
    drv5.close()
    cur.connection.commit()

    # ---- terminal -------------------------------------------------------
    tidc = u()
    sid6, ids6 = seed(cur, [(tidc, "finish me", "advancement_task", "runnable")])
    eid6 = enqueue(cur, sid6, "tool", harness_req(cur, sid6), "harness_turn")
    settle(cur, eid6, FINISH)
    bind(cur, sid6, ids6[0], "finish me", eid6)
    word6 = advance(cur, sid6)
    cur.connection.commit()
    st6 = q1(cur, "SELECT status FROM sessions WHERE session_id=%s", (sid6,))
    ev6 = events_n(cur, sid6)
    cur.connection.commit()
    drv6, _f6 = make_driver(server)
    word, _a = drv6.run_turn(sid6)
    st6_after = q1(cur, "SELECT status FROM sessions WHERE session_id=%s", (sid6,))
    check("exit_terminal",
          word == "terminal" and st6 == "completed" and st6_after == "completed"
          and calls_for(drv6, sid6) == [] and events_n(cur, sid6) == ev6,
          (word, st6, st6_after, word6, calls_for(drv6, sid6)))
    drv6.close()
    cur.connection.commit()

    # ---- stopping -------------------------------------------------------
    sid7 = fresh(cur)
    cur.connection.commit()
    ev7 = events_n(cur, sid7)
    cur.connection.commit()
    drv7, _f7 = make_driver(server)
    word7, _a7 = drv7.run_turn(sid7, stop_requested=True)
    gs7 = q1(cur, "SELECT count(*) FROM events WHERE session_id=%s AND type='goal/stopped'", (sid7,))
    st7 = q1(cur, "SELECT status FROM sessions WHERE session_id=%s", (sid7,))
    check("exit_stopping",
          word7 == "stopping" and gs7 == 1 and st7 != "stopping"
          and calls_for(drv7, sid7) == ["v13_goal_stop"],
          (word7, gs7, st7, calls_for(drv7, sid7)))
    drv7.close()
    cur.connection.commit()

    # ---- unknown exit words collapse to wait, zero events ---------------
    tidd, tide = u(), u()
    specs8 = [(tidd, "hold a", "advancement_task", "runnable"),
              (tide, "hold b", "advancement_task", "runnable")]
    sid8, ids8 = seed(cur, specs8)
    archive_done(cur, sid8, ids8[0], spec_text(specs8, ids8[0]))
    cur.connection.commit()
    ev8 = events_n(cur, sid8)
    dec8 = decisions_n(cur)
    cur.connection.commit()
    drv8, _f8 = make_driver(server)
    outs = []
    for w in NOT_EXIT_WORDS:
        outs.append((drv8.take_exit(w, sid8), drv8.decide(sid8, upstream_word=w)))
    writes8 = [n for n in calls_for(drv8, sid8)
               if n.startswith("v13_advance") or n in ("v13_complete", "v13_goal_stop")]
    check("unknown_exit_words_map_to_wait",
          all(o == "wait" and d == "wait" for o, d in outs)
          and writes8 == [] and events_n(cur, sid8) == ev8,
          (outs, writes8))
    drv8.close()
    cur.connection.commit()
    check("unknown_words_decisions_unchanged", decisions_n(cur) == dec8)

    # ---- stopped root with failed snap ----------------------------------
    sid9 = fresh(cur)
    cur.execute("SELECT v13_goal_stop(%s, 'gate stop')", (sid9,))
    cur.connection.commit()
    ev9 = events_n(cur, sid9)
    cur.connection.commit()
    drv9, _f9 = make_driver(server)
    word9, _a9 = drv9.run_turn(sid9, snap_failed=False)
    adv9 = [n for n in calls_for(drv9, sid9) if n.startswith("v13_advance")]
    check("stopped_failed_snap",
          word9 == "wait" and adv9 == [] and events_n(cur, sid9) == ev9,
          (word9, adv9))
    drv9.close()
    cur.connection.commit()

    sid10 = fresh(cur)
    cur.execute("SELECT v13_goal_stop(%s, 'gate stop')", (sid10,))
    cur.connection.commit()
    drv10, _f10 = make_driver(server)
    drv10.run_turn(sid10)
    check("stopped_absent_failed_key_advances",
          any(n.startswith("v13_advance") for n in calls_for(drv10, sid10)),
          calls_for(drv10, sid10))
    drv10.close()
    cur.connection.commit()

    for label, failed_val, expect_advances in (
            ("zero", 0, False), ("text", "boom", False), ("null", None, True)):
        sidt = fresh(cur)
        cur.execute("SELECT v13_goal_stop(%s, 'gate stop')", (sidt,))
        cur.connection.commit()
        drvt, _ft = make_driver(server)
        if failed_val is None:
            snap_probe = drvt.snap_of(sidt, failed=None)
            check(f"stopped_failed_snap_null_snapkey",
                  "failed" in snap_probe and snap_probe["failed"] is None,
                  snap_probe.get("failed", "<absent>"))
        drvt.run_turn(sidt, snap_failed=failed_val)
        advt = [n for n in calls_for(drvt, sidt) if n.startswith("v13_advance")]
        check(f"stopped_failed_snap_{label}",
              (len(advt) >= 1) == expect_advances, (label, advt))
        drvt.close()
        cur.connection.commit()


def test_pump(cur, server):
    # ---- full provider jump: entry advance, IO outside txn, complete +
    #      settlement advance in one txn, wait exit, no requeue ------------
    tidp = u()
    sidp, _idsp = seed(cur, [(tidp, "pump me", "advancement_task", "runnable")])
    cur.connection.commit()
    decp = decisions_n(cur)
    cur.connection.commit()
    drvp, fakep = make_driver(server)
    wordp, _ap = drvp.run_turn(sidp)
    seqp = calls_for(drvp, sidp)
    completes = [i for i, n in enumerate(seqp) if n == "v13_complete"]
    settle_ok = all(i - 1 >= 0 and seqp[i - 1] == "v13_advance"
                    for i in completes)
    check("t0_settlement_advance",
          completes and settle_ok
          and seqp.count("v13_advance") == 1 + len(completes)
          and seqp.count("v13_advance:requeue") == 0,
          seqp)
    check("complete_settle_same_txn",
          bool(drvp.txids) and all(a == b for a, b in drvp.txids),
          drvp.txids)
    check("io_outside_txn",
          fakep.txn_status == psycopg2.extensions.TRANSACTION_STATUS_IDLE
          and fakep.calls_n >= 1 and fakep.layer_names ==
          ["assertion", "assembly", "judgment", "workflow"],
          (fakep.txn_status, fakep.calls_n, fakep.layer_names))
    stp = q1(cur, "SELECT status FROM effects WHERE session_id=%s AND kind='llm'", (sidp,))
    resp = as_obj(q1(cur, "SELECT result FROM effects WHERE session_id=%s AND kind='llm'", (sidp,)))
    check("pump_llm_completed", stp == "succeeded" and resp == {"text": "driver says ok"}, (stp, resp))
    check("pump_exit_wait", wordp == "wait", wordp)
    drvp.close()
    cur.connection.commit()
    check("pump_decisions_unchanged", decisions_n(cur) == decp)

    # ---- retry bound 2: harness prose fails projection, complete never
    #      called, attempts stop at 2 --------------------------------------
    tidq = u()
    sidq, idsq = seed(cur, [(tidq, "harness prose", "advancement_task", "runnable")])
    eidq = enqueue(cur, sidq, "tool", harness_req(cur, sidq), "harness_turn")
    bind(cur, sidq, idsq[0], "harness prose", eidq)
    cur.connection.commit()
    prose_calls = {"n": 0}

    prose_states = []

    def prose_tool(_peek):
        prose_states.append(drvq.conn.get_transaction_status())
        prose_calls["n"] += 1
        return "just prose, not an object"

    drvq, _fq = make_driver(server, tools={"harness_turn": prose_tool})
    wordq, attq = drvq.run_turn(sidq)
    stq = q1(cur, "SELECT status FROM effects WHERE effect_id=%s", (eidq,))
    check("retry_bound_2", attq == 2 and prose_calls["n"] == 2, (attq, prose_calls["n"]))
    check("c7_prose_missing_key_fail_no_complete",
          "v13_complete" not in calls_for(drvq, sidq) and stq == "ready" and wordq == "wait"
          and all(s == psycopg2.extensions.TRANSACTION_STATUS_IDLE
                  for s in prose_states),
          (stq, wordq, prose_states, calls_for(drvq, sidq)))
    drvq.close()
    cur.connection.commit()

    # ---- valid harness answer served through the projection -------------
    tidr = u()
    sidr, idsr = seed(cur, [(tidr, "harness ok", "advancement_task", "runnable")])
    eidr = enqueue(cur, sidr, "tool", harness_req(cur, sidr), "harness_turn")
    bind(cur, sidr, idsr[0], "harness ok", eidr)
    cur.connection.commit()
    tool_states = []

    def progress_tool(_peek):
        tool_states.append(drvr.conn.get_transaction_status())
        return dict(PROGRESS)

    drvr, _fr = make_driver(server, tools={"harness_turn": progress_tool})
    drvr.run_turn(sidr)
    strr = q1(cur, "SELECT status FROM v13_plan_todo_fold(%s) WHERE todo_id=%s", (sidr, idsr[0]))
    resr = as_obj(q1(cur, "SELECT result FROM effects WHERE effect_id=%s", (eidr,)))
    check("harness_project_served_archived",
          strr == "done" and resr == PROGRESS
          and "v13_complete" in calls_for(drvr, sidr)
          and drvr.attempts_used == 0
          and all(s == psycopg2.extensions.TRANSACTION_STATUS_IDLE
                  for s in tool_states),
          (strr, resr, drvr.attempts_used, tool_states))
    drvr.close()
    cur.connection.commit()

    # ---- wait final answer does not archive the todo ---------------------
    tidw = u()
    sidw, idsw = seed(cur, [(tidw, "harness wait", "advancement_task", "runnable")])
    eidw = enqueue(cur, sidw, "tool", harness_req(cur, sidw), "harness_turn")
    bind(cur, sidw, idsw[0], "harness wait", eidw)
    cur.connection.commit()
    drvw, _fw = make_driver(server, tools={"harness_turn": lambda peek: dict(WAITP)})
    drvw.run_turn(sidw)
    stw = q1(cur, "SELECT status FROM v13_plan_todo_fold(%s) WHERE todo_id=%s", (sidw, idsw[0]))
    resw = as_obj(q1(cur, "SELECT result FROM effects WHERE effect_id=%s", (eidw,)))
    check("harness_wait_not_archived",
          stw == "runnable" and resw == WAITP
          and "v13_complete" in calls_for(drvw, sidw),
          (stw, resw))
    drvw.close()
    cur.connection.commit()

    # ---- allOf seam: key layer ok, complete rejects, txn rolls back ------
    tids = u()
    sids, idss = seed(cur, [(tids, "allof seam", "advancement_task", "runnable")])
    eids = enqueue(cur, sids, "tool", harness_req(cur, sids), "harness_turn")
    bind(cur, sids, idss[0], "allof seam", eids)
    cur.connection.commit()
    plans_s = plan_n(cur, sids)
    cur.connection.commit()
    drvs, _fs = make_driver(
        server, tools={"harness_turn": lambda peek: {
            "result_kind": "progress", "wait_reason": "evidence"}})
    raised = None
    try:
        drvs.run_turn(sids)
    except Exception as exc:  # noqa: BLE001 - gate asserts the loud failure
        raised = exc
    sts = q1(cur, "SELECT status FROM effects WHERE effect_id=%s", (eids,))
    word_after = drvs.decide(sids)
    check("allof_seam_complete_rolls_back",
          raised is not None and "harness_result schema" in str(raised)
          and sts == "ready" and plan_n(cur, sids) == plans_s
          and "v13_complete" not in calls_for(drvs, sids) and word_after == "wait",
          (str(raised)[:120], sts, plans_s, word_after))
    drvs.close()
    cur.connection.commit()

    # ---- claim lost to a concurrent worker: driver gives up, no complete --
    tidc = u()
    sidc, idsc = seed(cur, [(tidc, "claim race", "advancement_task", "runnable")])
    cur.connection.commit()
    drvc = None

    def racing_llm(layers, peek):
        # Concurrent worker claims the effect between peek and driver claim.
        rconn = psycopg2.connect(server.get_uri(DB))
        rcur = rconn.cursor()
        rcur.execute(
            "UPDATE effects SET status='claimed', attempt_no=attempt_no+1, "
            "fence=fence+1, lease_owner='racer', "
            "lease_until=clock_timestamp()+interval '1 hour' "
            "WHERE effect_id=%s::uuid AND status='ready'", (peek["effect_id"],))
        rconn.commit()
        rconn.close()
        return {"text": "racing worker was here"}

    drvc = LoopDriver(lambda: psycopg2.connect(server.get_uri(DB)), llm=racing_llm,
                      tools={}, layers=dict(FIXTURE_LAYERS))
    wordc, _ac = drvc.run_turn(sidc)
    states_c = [n for n in calls_for(drvc, sidc) if n == "v13_complete"]
    stc = q1(cur, "SELECT status FROM effects WHERE session_id=%s AND kind='llm'", (sidc,))
    ownerc = q1(cur, "SELECT lease_owner FROM effects WHERE session_id=%s AND kind='llm'", (sidc,))
    check("claim_lost_gives_up_no_complete",
          states_c == [] and stc == "claimed" and ownerc == "racer" and wordc == "wait",
          (states_c, stc, ownerc, wordc))
    drvc.close()
    cur.connection.commit()

    # ---- four layers, fixture texts, no resolver, nothing written back ---
    drvx, _fx = make_driver(server)
    layers = drvx.four_layers()
    pol = q1(cur, "SELECT count(*) FROM v13_policies WHERE name='workflow_template'")
    check("four_layers",
          [n for n, _ in layers] == ["assertion", "assembly", "judgment", "workflow"]
          and [t for _, t in layers] == [FIXTURE_LAYERS[n] for n in
                                         ["assertion", "assembly", "judgment", "workflow"]]
          and all(isinstance(t, str) for _, t in layers) and pol == 0,
          (layers, pol))
    drvx.close()
    cur.connection.commit()


def r1_spent_kind():
    return "turn/" + "material_spent"


def r1_spent(cur, eid):
    return int(q1(
        cur,
        "SELECT count(*) FROM events WHERE source_effect_id=%s AND type=%s",
        (eid, r1_spent_kind())))


def r1_failed_n(cur, sid):
    return int(q1(
        cur,
        "SELECT count(*) FROM events WHERE session_id=%s AND type=%s",
        (sid, "resolve/" + "failed")))


def r1_unpaid_ids(cur, sid):
    cur.execute(
        "SELECT e.effect_id::text FROM effects e "
        "WHERE e.session_id=%s "
        "AND e.effect_id = v13_harness_predecessor(%s) "
        "AND e.kind='tool' "
        "AND v13_is_harness_tool(e.tool_name, e.kind) "
        "AND e.origin_user_seq = v13_last_user_seq(%s) "
        "AND v13_harness_request_ok(e.request) "
        "AND e.status='succeeded' "
        "AND (e.result->>'result_kind'='finish' "
        " OR (e.result->>'result_kind'='progress' AND NOT EXISTS ("
        "       SELECT 1 FROM events WHERE source_effect_id=e.effect_id "
        "         AND type IN ('repair/required','replan/required')))) "
        "AND NOT EXISTS ("
        "       SELECT 1 FROM events WHERE source_effect_id=e.effect_id "
        "         AND type=%s)",
        (sid, sid, sid, r1_spent_kind()))
    return [row[0] for row in cur.fetchall()]


def r1_fixture_unpaid(cur, result=None, human=False, human_status="ready"):
    sid = fresh(cur)
    eid = enqueue(cur, sid, "tool", harness_req(cur, sid), "harness_turn")
    settle(cur, eid, PROGRESS if result is None else result)
    hid = None
    if human:
        hid = enqueue(
            cur, sid, "human",
            {"schema_version": 1, "interaction_ref": "r1-" + u()})
        if human_status == "claimed":
            cur.execute(
                "UPDATE effects SET status='claimed', lease_owner='r1', "
                "lease_until='infinity' WHERE effect_id=%s", (hid,))
    return sid, eid, hid


def r1_advance_n(cur):
    cur.execute("SELECT pg_stat_force_next_flush()")
    cur.fetchone()
    obs = psycopg2.connect(cur.connection.dsn)
    obs.autocommit = True
    try:
        oc = obs.cursor()
        oc.execute("SELECT pg_stat_force_next_flush()")
        oc.fetchone()
        got = q1(
            oc,
            "SELECT coalesce((SELECT calls FROM pg_stat_user_functions "
            "WHERE funcid = 'public.v13_advance(uuid,jsonb)'::regprocedure), 0)")
        return int(got)
    finally:
        obs.close()


def r1_reset_advance(cur):
    cur.execute(
        "SELECT pg_stat_reset_single_function_counters("
        "'public.v13_advance(uuid,jsonb)'::regprocedure)")
    cur.fetchone()
    cur.connection.commit()


def r1_prepare_conn(conn):
    was = conn.autocommit
    conn.autocommit = True
    try:
        cur = conn.cursor()
        cur.execute("SET track_functions TO 'all'")
        cur.execute("SELECT pg_backend_pid()")
        return int(cur.fetchone()[0])
    finally:
        conn.autocommit = was


def r1_driver(server):
    drv, fake = make_driver(server)
    r1_prepare_conn(drv.connection())
    return drv, fake


def r1_wait_blocked(server, waiter_pid, holder_pid, worker):
    import time
    obs = psycopg2.connect(server.get_uri(DB))
    obs.autocommit = True
    try:
        cur = obs.cursor()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            blockers = q1(cur, "SELECT pg_blocking_pids(%s)", (waiter_pid,)) or []
            if holder_pid in list(blockers):
                return True
            if not worker.is_alive():
                return False
            time.sleep(0.05)
        return False
    finally:
        obs.close()


def r1_cancel_others(server):
    killer = psycopg2.connect(server.get_uri(DB))
    killer.autocommit = True
    try:
        killer.cursor().execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname=%s AND pid <> pg_backend_pid()", (DB,))
    finally:
        killer.close()


def r1_static_sentinel():
    import inspect
    from v13.plan_arm.test_plan_arm import r0_source_scope
    src = (ROOT / "driver.py").read_text()
    check("named_entry_is_settle_once",
          hasattr(LoopDriver, "settle_once")
          and list(inspect.signature(LoopDriver.settle_once).parameters) == ["self", "sid"])
    body = inspect.getsource(LoopDriver.settle_once)
    check("settle_once_not_run_turn",
          "run_turn" not in body
          and "v13_complete" not in body
          and "serve(" not in body)
    banned = ["v13_unpaid_harness_turn", "v13_harness_settle",
              "v13_observe_fold", "v13_notify_project",
              "v13_goal_ambiguous_hold", "v13_goal_lease_once",
              "v13_replan_gap_insert"]
    hits = [name for name in banned if name in src]
    check("phase_a_prefix_driver_has_no_unpaid_helper", hits == [], hits)
    sess = src.count("FROM sessions WHERE session_id = %s FOR UPDATE")
    outside = src.split("# R1_SETTLE_ONCE_BEGIN", 1)[0].count("FOR UPDATE")
    check("r1_sessions_for_update_once_in_sentinel",
          sess == 1 and outside == 0, (sess, outside))
    check("r0_source_scope",
          r0_source_scope() == "fb295ac6c7459bb98dac57e37883af549d2d8a4c")


def r1_runtime(cur, server):
    import inspect
    import threading
    from psycopg2.extensions import TRANSACTION_STATUS_IDLE

    cur.execute("SET track_functions TO 'all'")
    cur.connection.commit()

    absent = q1(
        cur,
        "SELECT to_regprocedure('public.v13_unpaid_harness_turn(uuid)') IS NULL "
        "AND to_regprocedure('public.v13_harness_settle(uuid,uuid,uuid,jsonb)') IS NULL")
    check("phase_a_prefix_has_no_unpaid_helper", absent is True, absent)

    sid_q = fresh(cur)
    cur.connection.commit()
    drv_q, _fq = r1_driver(server)
    word_q = drv_q.settle_once(sid_q)
    check("quiet_does_not_call_advance",
          word_q == "waiting"
          and "v13_advance" not in calls_for(drv_q, sid_q),
          (word_q, calls_for(drv_q, sid_q)))
    check("connection_idle_after_settle_once",
          drv_q.conn.get_transaction_status() == TRANSACTION_STATUS_IDLE)
    nowait = psycopg2.connect(server.get_uri(DB))
    try:
        nc = nowait.cursor()
        nc.execute(
            "SELECT 1 FROM sessions WHERE session_id=%s FOR UPDATE NOWAIT",
            (sid_q,))
        check("connection_idle_after_settle_once", nc.fetchone()[0] == 1)
        nowait.rollback()
    finally:
        nowait.close()
    drv_q.close()
    cur.connection.commit()

    sid_p, eid_p, _ = r1_fixture_unpaid(cur)
    aligned = r1_unpaid_ids(cur, sid_p)
    pred_p = str(q1(cur, "SELECT v13_harness_predecessor(%s)", (sid_p,)))
    check("r1_unpaid_predicate_matches_predecessor",
          aligned == [eid_p] and pred_p == eid_p, (aligned, pred_p, eid_p))
    cur.connection.commit()
    spent0 = r1_spent(cur, eid_p)
    drv_p, _fp = r1_driver(server)
    word_p = drv_p.settle_once(sid_p)
    seq_p = calls_for(drv_p, sid_p)
    spent1 = r1_spent(cur, eid_p)
    check("unpaid_progress_calls_advance_once",
          seq_p.count("v13_advance") == 1
          and spent1 == spent0 + 1,
          (word_p, seq_p, spent1))
    check("t0_same_txn_root_lock",
          seq_p.index("sessions_lock") < seq_p.index("v13_goal_lifecycle")
          and seq_p.index("v13_goal_lifecycle") < seq_p.index("v13_advance"),
          seq_p)
    word_p2 = drv_p.settle_once(sid_p)
    check("second_settlement_no_second_receipt",
          r1_spent(cur, eid_p) == spent1
          and calls_for(drv_p, sid_p).count("v13_advance") == 1,
          (word_p2, r1_spent(cur, eid_p)))
    drv_p.close()
    cur.connection.commit()

    sid_f, eid_f, _ = r1_fixture_unpaid(cur, result=FINISH)
    cur.connection.commit()
    drv_f, _ff = r1_driver(server)
    drv_f.settle_once(sid_f)
    check("unpaid_finish_calls_advance_once",
          calls_for(drv_f, sid_f).count("v13_advance") == 1
          and r1_spent(cur, eid_f) == 1)
    drv_f.close()
    cur.connection.commit()

    sid_w, eid_w, _ = r1_fixture_unpaid(
        cur, result={"result_kind": "wait", "wait_reason": "evidence",
                     "wake": {"kind": "not_before", "at": "2099-01-01T00:00:00Z"}})
    cur.connection.commit()
    drv_w, _fw = r1_driver(server)
    word_w = drv_w.settle_once(sid_w)
    check("wait_reject_not_settled",
          word_w == "waiting"
          and r1_spent(cur, eid_w) == 0
          and "v13_advance" not in calls_for(drv_w, sid_w),
          (word_w, calls_for(drv_w, sid_w)))
    drv_w.close()
    cur.connection.commit()

    sid_t0, eid_t0, _ = r1_fixture_unpaid(cur)
    q1(cur, "SELECT v13_goal_stop(%s, %s)", (sid_t0, "r1-t0"))
    cur.execute(
        "UPDATE effects SET result = result || %s::jsonb WHERE effect_id=%s",
        (json.dumps({"failed": False}), eid_t0))
    fail0 = r1_failed_n(cur, sid_t0)
    cur.connection.commit()
    drv_t0, _ft0 = r1_driver(server)
    word_t0 = drv_t0.settle_once(sid_t0)
    seq_t0 = calls_for(drv_t0, sid_t0)
    check("stopped_failed_snap_no_advance",
          word_t0 == "skipped_failed"
          and r1_spent(cur, eid_t0) == 0
          and r1_failed_n(cur, sid_t0) == fail0
          and "v13_advance" not in seq_t0
          and seq_t0.index("sessions_lock") < seq_t0.index("v13_goal_lifecycle"),
          (word_t0, seq_t0))
    drv_t0.close()
    cur.connection.commit()

    sid_nk, eid_nk, _ = r1_fixture_unpaid(cur)
    q1(cur, "SELECT v13_goal_stop(%s, %s)", (sid_nk, "r1-nokey"))
    cur.connection.commit()
    drv_nk, _fnk = r1_driver(server)
    word_nk = drv_nk.settle_once(sid_nk)
    check("stopped_without_failed_key_still_settles",
          word_nk != "skipped_failed" and r1_spent(cur, eid_nk) == 1,
          (word_nk, r1_spent(cur, eid_nk)))
    drv_nk.close()
    cur.connection.commit()

    sid_null, eid_null, _ = r1_fixture_unpaid(cur)
    q1(cur, "SELECT v13_goal_stop(%s, %s)", (sid_null, "r1-null"))
    cur.execute(
        "UPDATE effects SET result = result || %s::jsonb WHERE effect_id=%s",
        (json.dumps({"failed": None}), eid_null))
    cur.connection.commit()
    drv_null, _fn = r1_driver(server)
    word_null = drv_null.settle_once(sid_null)
    check("stopped_failed_null_still_settles",
          word_null != "skipped_failed" and r1_spent(cur, eid_null) == 1,
          (word_null, r1_spent(cur, eid_null)))
    drv_null.close()
    cur.connection.commit()

    sid_h, eid_h, hid_h = r1_fixture_unpaid(cur, human=True, human_status="ready")
    st_h0 = q1(cur, "SELECT status FROM effects WHERE effect_id=%s", (hid_h,))
    cur.connection.commit()
    drv_h, _fh = r1_driver(server)
    word_h = drv_h.settle_once(sid_h)
    check("human_ready_claimed_settles_then_waits",
          word_h == "waiting"
          and r1_spent(cur, eid_h) == 1
          and q1(cur, "SELECT status FROM effects WHERE effect_id=%s", (hid_h,)) == st_h0,
          (word_h, st_h0))
    drv_h.close()
    cur.connection.commit()

    sid_c, eid_c, hid_c = r1_fixture_unpaid(cur, human=True, human_status="claimed")
    st_c0 = q1(cur, "SELECT status FROM effects WHERE effect_id=%s", (hid_c,))
    cur.connection.commit()
    drv_c, _fc = r1_driver(server)
    word_c = drv_c.settle_once(sid_c)
    check("human_ready_claimed_settles_then_waits",
          word_c == "waiting"
          and r1_spent(cur, eid_c) == 1
          and q1(cur, "SELECT status FROM effects WHERE effect_id=%s", (hid_c,)) == st_c0,
          (word_c, st_c0))
    drv_c.close()
    cur.connection.commit()

    walls = (
        ("unknown", "waiting"),
        ("cancel", "waiting"),
        ("stale", "stale"),
    )
    for wall, expected in walls:
        sid_u, eid_u, hid_u = r1_fixture_unpaid(cur, human=True, human_status="claimed")
        if wall == "unknown":
            cur.execute("UPDATE effects SET status='unknown' WHERE effect_id=%s", (hid_u,))
            cur.execute(
                "UPDATE sessions SET " + "status=%s WHERE session_id=%s",
                ("blocked_unknown", sid_u))
        elif wall == "cancel":
            q1(cur, "SELECT v13_cancel(%s)", (sid_u,))
        cur.connection.commit()
        drv_u, _fu = r1_driver(server)
        if wall == "stale":
            def _bump():
                drv_u.conn.cursor().execute(
                    "SELECT v13_submit_override(%s::uuid, %s::jsonb)",
                    (sid_u, json.dumps({
                        "schema_version": 1, "intent": "direct",
                        "reason": "", "source_principal": "operator"})))
            drv_u._r1_before_advance = _bump
        word_u = drv_u.settle_once(sid_u)
        still = r1_unpaid_ids(cur, sid_u)
        check(
            "waiting_with_unpaid_remaining_" + wall,
            word_u == expected
            and r1_spent(cur, eid_u) == 0
            and still == [eid_u],
            (wall, word_u, still, r1_spent(cur, eid_u)))
        drv_u.close()
        cur.connection.commit()

    sid_tx = fresh(cur)
    cur.connection.commit()
    drv_tx, _ftx = r1_driver(server)
    drv_tx.connection().cursor().execute("SELECT 1")
    raised_tx = None
    try:
        drv_tx.settle_once(sid_tx)
    except RuntimeError as exc:
        raised_tx = str(exc)
    check("r1_open_transaction_fails_zero_sql",
          raised_tx is not None and "open transaction" in raised_tx
          and "v13_advance" not in calls_for(drv_tx, sid_tx),
          raised_tx)
    drv_tx.conn.rollback()
    drv_tx.close()
    cur.connection.commit()

    sid_rb, eid_rb, _ = r1_fixture_unpaid(cur)
    cur.connection.commit()
    drv_rb, _frb = r1_driver(server)
    def _boom():
        drv_rb.conn.cursor().execute("SELECT 1/0")
    drv_rb._r1_before_advance = _boom
    raised_rb = None
    try:
        drv_rb.settle_once(sid_rb)
    except Exception as exc:  # noqa: BLE001
        raised_rb = str(exc)
    check("r1_advance_raise_rolls_back_idle",
          raised_rb is not None
          and r1_spent(cur, eid_rb) == 0
          and drv_rb.conn.get_transaction_status() == TRANSACTION_STATUS_IDLE,
          raised_rb)
    del drv_rb._r1_before_advance
    word_rb = drv_rb.settle_once(sid_rb)
    check("r1_next_settle_relocks_after_rollback",
          r1_spent(cur, eid_rb) == 1 and word_rb != "skipped_failed",
          (word_rb, r1_spent(cur, eid_rb)))
    drv_rb.close()
    cur.connection.commit()

    sid_ch = fresh(cur)
    kids = as_obj(q1(
        cur, "SELECT v13_spawn_subsession(%s, %s::jsonb)",
        (sid_ch, json.dumps({
            "schema_version": 1,
            "children": [{"tool_call_id": "r1c1", "task": "one"}],
        }))))
    child = str(kids["children"][0]["session_id"])
    cur.connection.commit()
    drv_ch, _fch = r1_driver(server)
    raised_ch = None
    try:
        drv_ch.settle_once(child)
    except RuntimeError as exc:
        raised_ch = str(exc)
    check("r1_child_fails_zero_advance",
          raised_ch is not None and "not_root" in raised_ch
          and "v13_advance" not in calls_for(drv_ch, child),
          raised_ch)
    drv_ch.close()
    cur.connection.commit()

    r1_stop_advance_interleave_stop_wins(cur, server)
    r1_stop_advance_interleave_settle_holds(cur, server)

    check("settle_once_not_run_turn",
          "run_turn" not in inspect.getsource(LoopDriver.settle_once))


def r1_stop_advance_interleave_stop_wins(cur, server):
    import threading
    sid, eid, _ = r1_fixture_unpaid(cur)
    busy = int(q1(
        cur,
        "SELECT count(*) FROM effects WHERE session_id=%s "
        "AND status IN ('ready','claimed','unknown')", (sid,)))
    check("stop_advance_interleave_stop_wins_already_clear", busy == 0, busy)
    cur.connection.commit()
    hold = psycopg2.connect(server.get_uri(DB))
    worker = None
    box = {}
    try:
        hc = hold.cursor()
        hpid = r1_prepare_conn(hold)
        hc.execute("SELECT 1 FROM sessions WHERE session_id=%s FOR UPDATE", (sid,))
        hc.fetchone()

        def work():
            drv, _fake = make_driver(server)
            try:
                box["pid"] = r1_prepare_conn(drv.connection())
                box["word"] = drv.settle_once(sid)
                box["calls"] = list(drv.calls)
            except Exception as exc:  # noqa: BLE001
                box["err"] = str(exc)
            finally:
                drv.close()

        worker = threading.Thread(target=work)
        worker.start()
        import time
        until = time.monotonic() + 10
        while time.monotonic() < until and box.get("pid") is None:
            if not worker.is_alive():
                break
            time.sleep(0.05)
        check("stop_advance_interleave_stop_wins", box.get("pid") is not None, box)
        blocked = r1_wait_blocked(server, box["pid"], hpid, worker)
        check("stop_advance_interleave_stop_wins", blocked, box)
        payload = as_obj(q1(hc, "SELECT v13_goal_stop(%s, %s)", (sid, "r1-stop-wins")))
        check("stop_advance_interleave_stop_wins",
              isinstance(payload, dict) and payload.get("schema_version") == 1
              and payload.get("reason") == "r1-stop-wins",
              payload)
        gs = int(q1(
            hc,
            "SELECT count(*) FROM events WHERE session_id=%s AND type='goal/stopped'",
            (sid,)))
        check("stop_advance_interleave_stop_wins", gs == 1, gs)
        hc.execute(
            "UPDATE effects SET result = result || %s::jsonb WHERE effect_id=%s",
            (json.dumps({"failed": False}), eid))
        hold.commit()
        worker.join(20)
        check("stop_advance_interleave_stop_wins",
              not worker.is_alive()
              and box.get("err") is None
              and box.get("word") == "skipped_failed"
              and "v13_advance" not in [n for n, _ in box.get("calls") or []]
              and r1_spent(cur, eid) == 0,
              box)
    finally:
        if worker is not None and worker.is_alive():
            try:
                r1_cancel_others(server)
            except Exception as exc:
                print("[r1-cancel]", exc)
            worker.join(10)
        try:
            hold.rollback()
        except Exception:
            pass
        hold.close()
        cur.connection.commit()


def r1_stop_advance_interleave_settle_holds(cur, server):
    import threading
    import time
    sid, eid, hid = r1_fixture_unpaid(cur, human=True, human_status="ready")
    cur.connection.commit()
    held = threading.Event()
    go = threading.Event()
    box = {}
    stop_box = {}
    worker = None
    stopper = None

    def work():
        drv, _fake = make_driver(server)
        try:
            def pause():
                box["pid"] = int(q1(drv.conn.cursor(), "SELECT pg_backend_pid()"))
                held.set()
                go.wait(20)
            drv._r1_after_root_lock = pause
            r1_prepare_conn(drv.connection())
            box["word"] = drv.settle_once(sid)
            box["calls"] = list(drv.calls)
        except Exception as exc:  # noqa: BLE001
            box["err"] = str(exc)
            held.set()
        finally:
            drv.close()

    def stop():
        conn = psycopg2.connect(server.get_uri(DB))
        try:
            stop_box["pid"] = r1_prepare_conn(conn)
            cur2 = conn.cursor()
            try:
                cur2.execute("SELECT v13_goal_stop(%s, %s)", (sid, "r1-settle-holds"))
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
            if spid and bpid and r1_wait_blocked(server, spid, bpid, stopper):
                blocked = True
                break
            time.sleep(0.05)
        check("stop_advance_interleave_settle_holds", blocked, (box, stop_box))
        go.set()
        worker.join(20)
        stopper.join(20)
        check("stop_advance_interleave_settle_holds",
              not worker.is_alive()
              and not stopper.is_alive()
              and box.get("err") is None
              and "v13_advance" in [n for n, _ in box.get("calls") or []]
              and r1_spent(cur, eid) == 1
              and q1(cur, "SELECT status FROM effects WHERE effect_id=%s", (hid,)) == "ready"
              and stop_box.get("err") is not None
              and "goal busy" in str(stop_box.get("err")),
              (box, stop_box))
    finally:
        go.set()
        for th in (worker, stopper):
            if th is not None and th.is_alive():
                try:
                    r1_cancel_others(server)
                except Exception as exc:
                    print("[r1-cancel]", exc)
                th.join(10)
        cur.connection.commit()


def run(cur, server):
    test_static_and_readme()
    test_c7_sql(cur)
    test_unit_decide()
    test_exits(cur, server)
    test_pump(cur, server)
    r1_static_sentinel()
    r1_runtime(cur, server)
    cur.connection.commit()


def main() -> int:
    print("[db]", DB)
    if setup_db() != 0:
        return 1
    server = get_server()
    conn = connect(server)
    try:
        run(conn.cursor(), server)
    finally:
        conn.close()
        if setup_mod.CREATED:
            run_psql(server, "postgres", f'DROP DATABASE "{DB}" WITH (FORCE);')
            setup_mod.CREATED = False
            print("[dropped]", DB)
    print(f"[ok] {N} checks")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[FAIL] {exc}")
        if setup_mod.CREATED:
            try:
                run_psql(get_server(), "postgres", f'DROP DATABASE "{DB}" WITH (FORCE);')
                print("[dropped]", DB)
            except Exception as drop_exc:
                print("[cleanup-fail]", drop_exc)
        raise SystemExit(1)
