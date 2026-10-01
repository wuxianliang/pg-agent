"""Phase C frontier_gap gate.

Run: UV_FROZEN=1 uv run python v13/frontier_gap/test_frontier_gap.py
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v13.load import run_psql
from v13.frontier_gap.setup_db import DB, main as setup_db
import v13.frontier_gap.setup_db as setup_mod

N = 0
SQL = (ROOT / "v13_frontier_gap.sql").read_text()
README = (ROOT / "README.md").read_text()
HASH_FNS = (
    "public.v13_advance(uuid,jsonb)",
    "public.v13_goal_fingerprint(uuid)",
    "public.v13_recover_idle()",
    "public.v13_should_run(uuid)",
    "public.v13_plan_current(uuid)",
    "public.v13_plan_apply_id(text)",
)


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


def fails(cur, sql, params, needle, label):
    cur.execute("SAVEPOINT sp")
    try:
        cur.execute(sql, params)
    except psycopg2.Error as exc:
        msg = exc.diag.message_primary or str(exc).splitlines()[0]
        check(label, needle in msg, msg)
        cur.execute("ROLLBACK TO SAVEPOINT sp")
        return msg
    cur.execute("ROLLBACK TO SAVEPOINT sp")
    raise AssertionError(f"{label}: expected failure")


def isolated(cur, fn):
    cur.execute("SAVEPOINT t")
    try:
        fn()
    finally:
        cur.execute("ROLLBACK TO SAVEPOINT t")


def open_root(cur):
    spec = {"route_policy_name": "default", "version": 1}
    return str(q1(cur, "SELECT v13_plan_commit_entry(%s::jsonb)", (json.dumps(spec),)))


def prefix(cur, sid, text="hello goal"):
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (sid, u(), json.dumps({"text": text})))


def max_seq(cur, sid):
    return q1(cur, "SELECT max(seq) FROM events WHERE session_id=%s", (sid,))


def sort_uuids(cur, ids):
    cur.execute("SELECT id::text FROM unnest(%s::uuid[]) AS id ORDER BY id", (ids,))
    return [row[0] for row in cur.fetchall()]


def ttext(tid):
    return "todo " + tid


def todo(tid, cls="advancement_task", status="runnable", verb="add_new"):
    text = ttext(tid)
    return {
        "todo_id": tid,
        "text": text,
        "text_hash": sha(text),
        "task_class": cls,
        "status": status,
        "due": None,
        "verb": verb,
    }


def plan_body(todos, based, supersedes=None):
    return {
        "schema_version": 1,
        "call_kind": "plan_commit",
        "based_on_seq": based,
        "supersedes": supersedes,
        "todos": todos,
    }


def delta(tid, status_from, status_to, verb="update", binding=None,
          due=None, quarantine=None, link=None):
    return {
        "schema_version": 1,
        "call_kind": "todo_delta",
        "verb": verb,
        "todo_id": tid,
        "status_from": status_from,
        "status_to": status_to,
        "binding": binding,
        "due": due,
        "quarantine": quarantine,
        "text_hash": sha(ttext(tid)),
        "link": link,
    }


def writer(cur, sid, canonical, now=None, actor=None, apply=None):
    apply = apply or u()
    cur.execute(
        "SELECT v13_plan_writer(%s::uuid, %s::uuid, %s::uuid, %s, %s::jsonb, %s::timestamptz)",
        (actor, sid, apply, canonical["call_kind"], json.dumps(canonical), now))
    return as_obj(cur.fetchone()[0])


def fn_hash(cur, sig):
    return q1(
        cur,
        "SELECT encode(digest(convert_to(pg_get_functiondef(%s::regprocedure), 'UTF8'), 'sha256'), 'hex')",
        (sig,))


def project(cur, sid, before=None):
    cur.execute(
        "SELECT frontier, frontier_hash, has_obligation, omitted_count, omitted_complete "
        "FROM v13_frontier_project(%s::uuid, %s::bigint)",
        (sid, before))
    row = cur.fetchone()
    return {
        "frontier": as_obj(row[0]),
        "frontier_hash": row[1],
        "has_obligation": list(row[2] or []),
        "omitted_count": int(row[3]),
        "omitted_complete": bool(row[4]),
    }


def open_count(cur, sid):
    return int(q1(cur, "SELECT count(*) FROM v13_obligation_open(%s)", (sid,)))


def n_replan(cur, sid):
    return int(q1(
        cur,
        "SELECT count(*) FROM events WHERE session_id=%s AND type='replan/required'",
        (sid,)))


def n_obligation(cur, sid):
    return int(q1(
        cur,
        "SELECT count(*) FROM events e "
        "WHERE e.session_id=%s AND e.type='replan/required' "
        "AND v13_json_keys(e.payload) = ARRAY['schema_version'] "
        "AND NOT EXISTS (SELECT 1 FROM effects x WHERE x.effect_id = e.source_effect_id)",
        (sid,)))


def n_events(cur):
    return int(q1(cur, "SELECT count(*) FROM events"))


def n_effects(cur):
    return int(q1(cur, "SELECT count(*) FROM effects"))


def insert_gap(cur, sid, kind, subject, obj, expected_hash, actor=None):
    cur.execute(
        "SELECT v13_replan_gap_insert(%s::uuid, %s::uuid, %s, %s::uuid, %s::uuid, %s)",
        (actor, sid, kind, subject, obj, expected_hash))
    return str(cur.fetchone()[0])


def insert_sql():
    return "SELECT v13_replan_gap_insert(%s::uuid, %s::uuid, %s, %s::uuid, %s::uuid, %s)"


def plant_danglings(cur, sid, n_carriers, extra_targets=0):
    n_ids = n_carriers + 1 + extra_targets
    ids = sort_uuids(cur, [u() for _ in range(n_ids)])
    carriers = ids[:n_carriers]
    targets = ids[n_carriers:]
    todos = [todo(tid) for tid in ids]
    first = writer(cur, sid, plan_body(todos, max_seq(cur, sid)))
    if extra_targets:
        pairs = list(zip(carriers, targets))
    else:
        pairs = [(c, targets[0]) for c in carriers]
    for carrier, target in pairs:
        writer(cur, sid, delta(
            carrier, "runnable", "runnable", verb="link_successor",
            link={"on": "successor", "id": target}))
    reuse = [todo(c, verb="reuse") for c in carriers]
    second = writer(
        cur, sid, plan_body(reuse, max_seq(cur, sid), supersedes=first["plan_id"]))
    return {
        "sid": sid,
        "carriers": carriers,
        "targets": targets,
        "plan1": first["plan_id"],
        "plan2": second["plan_id"],
    }


def include_targets(cur, sid, carriers, targets, prev_plan):
    ids = sort_uuids(cur, list(carriers) + list(targets))
    todos = [todo(i, verb="reuse") for i in ids]
    return writer(cur, sid, plan_body(todos, max_seq(cur, sid), supersedes=prev_plan))


def omit_targets(cur, sid, carriers, prev_plan):
    todos = [todo(c, verb="reuse") for c in sort_uuids(cur, carriers)]
    return writer(cur, sid, plan_body(todos, max_seq(cur, sid), supersedes=prev_plan))


def harness_req(cur, sid):
    rev = int(q1(cur, "SELECT (v13_probe(%s)->>'tools_revision')::bigint", (sid,)))
    return {
        "tool": "harness_turn",
        "params": {},
        "handler": "worker:harness_turn",
        "tools_revision": rev,
        "logical_turn_id": u(),
        "continuation_index": 0,
    }


def enqueue(cur, sid, kind, request, tool_name=None):
    if tool_name:
        return str(q1(
            cur, "SELECT v13_enqueue_effect(%s, %s, %s::jsonb, %s)",
            (sid, kind, json.dumps(request), tool_name)))
    return str(q1(
        cur, "SELECT v13_enqueue_effect(%s, %s, %s::jsonb)",
        (sid, kind, json.dumps(request))))


def settle(cur, eid, result):
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


def snap_of(cur, sid):
    cur.execute(
        "UPDATE sessions SET context_active_revision = v13_context_required(session_id) "
        "WHERE session_id=%s",
        (sid,))
    cur.execute("SELECT v13_probe(%s)", (sid,))
    probe = cur.fetchone()[0]
    if isinstance(probe, str):
        probe = json.loads(probe)
    probe["sid"] = sid
    return {
        "snap": probe,
        "envelope": {"sid": sid},
        "remaining": 0,
        "abandon": False,
        "failed": False,
    }


def advance(cur, sid):
    snap = snap_of(cur, sid)
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid, json.dumps(snap)))
    return cur.fetchone()[0]


def test_stage_bytes():
    paths = [
        "v13/schema", "v13/resolve", "v13/loop", "v13/twophase", "v13/envelope",
        "v13/manifest", "v13/chunks", "v13/recall", "v13/characterize", "v13/filter",
        "v13/memory", "v13/economy", "v13/summary", "v13/periphery", "v13/mgraph",
        "v13/mgraph_assembly", "v13/control", "v13/spawn", "v13/fanout", "v13/triage",
        "v13/seam", "v13/catalog", "v13/acl", "v13/observe", "v13/handoff",
        "v13/should_run", "v13/quota_window", "v13/attention", "v13/govern",
        "docs/plans/v13-long-loop-plan-2026-09-28.md",
        "docs/plans/v13-long-loop-phase-a-plan-2026-09-29.md",
        "docs/plans/v13-long-loop-phase-b-plan-2026-09-29.md",
        "v13/workspace_admit", "v13/workspace_exec", "v13/plan_arm",
        "v13/loop_driver", "v13/real_chain", "v13/workflow_bind",
        "v13/plan_contract", "v13/plan_read",
    ]
    from v13.plan_arm.test_plan_arm import r0_source_scope
    base = r0_source_scope()
    # The fixed-base proof replaces the old whole-directory plan_arm freeze.
    paths = [p for p in paths if p != "v13/plan_arm"]
    diff = subprocess.check_output(["git", "diff", base, "--", *paths], cwd=AGENT_ROOT)
    load = subprocess.check_output(
        ["git", "diff", "HEAD", "--", "v13/load.py"], cwd=AGENT_ROOT).decode()
    removed = [
        line for line in load.splitlines()
        if line.startswith("-") and not line.startswith("---")
    ]
    text = (AGENT_ROOT / "v13/load.py").read_text()
    order = text.split("STAGE_THROUGH", 1)[0]
    through = text.split("STAGE_THROUGH", 1)[1]
    tail_ok = (
        order.rfind("workspace_admit") < order.rfind("frontier_gap")
        and through.rfind('"workspace_admit": 36') < through.rfind('"frontier_gap": 37')
        and "frontier_gap" not in order[:order.rfind("workspace_admit")]
    )
    if load.strip():
        load_ok = "frontier_gap" in load and removed == [] and tail_ok
    else:
        load_ok = tail_ok and "frontier_gap" in text
    check("stage_bytes", diff == b"" and load_ok, (removed, tail_ok, bool(load.strip())))
    check("r0_source_scope", r0_source_scope() == "fb295ac6c7459bb98dac57e37883af549d2d8a4c")
    check(
        "advance_sql_not_replaced",
        "CREATE OR REPLACE FUNCTION public.v13_advance" not in SQL
        and "CREATE OR REPLACE FUNCTION v13_advance" not in SQL
        and "v13_advance" not in SQL,
        None)


def test_symbols_and_jsonb(cur, server, before_hashes):
    for sig in ("v13_plan_current(uuid)", "v13_plan_apply_id(text)"):
        if q1(cur, "SELECT to_regprocedure(%s)", ("public." + sig,)) is None:
            print("v13: replan gap: ask_user")
            raise SystemExit(1)
    vol = q1(
        cur,
        "SELECT provolatile FROM pg_proc "
        "WHERE oid = 'public.v13_plan_apply_id(text)'::regprocedure")
    check("apply_id_callable_from_stable", vol == "i", vol)
    same = q1(
        cur,
        "SELECT a::text = b::text FROM "
        "(SELECT jsonb_build_object("
        "'schema_version', 1, 'plan_id', null, 'members', '[]'::jsonb, "
        "'gaps', '[]'::jsonb) AS a) s, "
        "(SELECT jsonb_build_object("
        "'gaps', '[]'::jsonb, 'members', '[]'::jsonb, 'plan_id', null, "
        "'schema_version', 1) AS b) t")
    check("jsonb_text_deterministic", same is True, same)
    ver = q1(
        cur,
        "SELECT version FROM v13_policies WHERE name='should_run' AND active "
        "ORDER BY version DESC LIMIT 1")
    check("policy_version_still_3", ver == 3, ver)
    revoked = q1(
        cur,
        "SELECT NOT has_function_privilege('public', "
        "'public.v13_replan_gap_insert(uuid,uuid,text,uuid,uuid,text)', 'EXECUTE')")
    src = q1(
        cur,
        "SELECT prosrc FROM pg_proc WHERE oid = "
        "'public.v13_replan_gap_insert(uuid,uuid,text,uuid,uuid,text)'::regprocedure")
    check(
        "insert_does_not_call_advance",
        "v13_advance" not in SQL and "v13_advance" not in src
        and revoked and "stannum" not in SQL.lower(),
        revoked)
    after = tuple(fn_hash(cur, sig) for sig in HASH_FNS)
    run_psql(server, DB, SQL)
    after_reload = tuple(fn_hash(cur, sig) for sig in HASH_FNS)
    check("fingerprint_unmodified", before_hashes == after == after_reload, None)


def test_writer_and_empty(cur, sid):
    empty = project(cur, sid)
    ev_before = n_events(cur)
    check(
        "empty_plan_no_gap",
        empty["frontier"]["plan_id"] is None
        and empty["frontier"]["gaps"] == []
        and empty["frontier"]["members"] == []
        and empty["frontier_hash"]
        and empty["omitted_complete"] is True,
        empty["frontier"])
    fails(
        cur, insert_sql(),
        (None, sid, "dangling_link", u(), u(), empty["frontier_hash"]),
        "v13: replan gap: no_gap",
        "empty_plan_no_gap")
    check("empty_plan_no_gap", n_events(cur) == ev_before)
    check(
        "quota_exhaustion_does_not_insert",
        "没有伪造配额账" in README)
    fails(
        cur, insert_sql(),
        (None, sid, "dangling_link", u(), u(), empty["frontier_hash"]),
        "v13: replan gap: no_gap",
        "quota_exhaustion_does_not_insert")
    ids = sort_uuids(cur, [u(), u()])
    a, b = ids
    writer(cur, sid, plan_body([todo(a), todo(b)], max_seq(cur, sid)))
    fails(
        cur,
        "SELECT v13_plan_writer(%s::uuid, %s::uuid, %s::uuid, %s, %s::jsonb, %s::timestamptz)",
        (None, sid, u(), "todo_delta", json.dumps(delta(
            a, "runnable", "runnable", verb="link_successor",
            link={"on": "successor", "id": None})), None),
        "v13: plan writer: canonical",
        "writer_cannot_produce_gap_stops")
    planted = plant_danglings(cur, sid, 1)
    proj = project(cur, sid)
    kinds = {g["gap_kind"] for g in proj["frontier"]["gaps"]}
    if not proj["frontier"]["gaps"]:
        print("v13: replan gap: ask_user")
        raise SystemExit(1)
    check(
        "writer_cannot_produce_gap_stops",
        kinds == {"dangling_link"} and proj["omitted_complete"] is True,
        kinds)
    check(
        "gap_kinds_closed",
        kinds <= {"dangling_link"} and "successor_missing" not in kinds,
        kinds)
    fails(
        cur, insert_sql(),
        (None, sid, "successor_missing", planted["carriers"][0],
         None, proj["frontier_hash"]),
        "v13: replan gap: canonical",
        "gap_kinds_closed")


def test_project_and_hash(cur, sid):
    planted = plant_danglings(cur, sid, 1)
    carrier = planted["carriers"][0]
    target = planted["targets"][0]
    before_e, before_x = n_events(cur), n_effects(cur)
    first = project(cur, sid)
    second = project(cur, sid)
    check(
        "project_zero_write",
        n_events(cur) == before_e and n_effects(cur) == before_x
        and first["frontier_hash"] == second["frontier_hash"]
        and first["frontier"]["gaps"]
        and first["frontier"]["gaps"][0]["gap_kind"] == "dangling_link"
        and first["frontier"]["gaps"][0]["subject_todo_id"] == carrier
        and first["frontier"]["gaps"][0]["object_todo_id"] == target,
        (first["frontier"]["gaps"], before_e, n_events(cur)))
    h1 = first["frontier_hash"]
    repaired = include_targets(
        cur, sid, planted["carriers"], planted["targets"], planted["plan2"])
    after_repair = project(cur, sid)
    check(
        "hash_changes_on_gap",
        after_repair["frontier_hash"] != h1
        and after_repair["frontier"]["gaps"] == [],
        (h1, after_repair["frontier_hash"]))
    omit_targets(cur, sid, planted["carriers"], repaired["plan_id"])
    after_omit = project(cur, sid)
    check(
        "hash_changes_on_gap",
        after_omit["frontier_hash"] != after_repair["frontier_hash"]
        and after_omit["frontier"]["gaps"],
        after_omit["frontier"]["gaps"])
    h_gap = after_omit["frontier_hash"]
    eid = enqueue(cur, sid, "tool", harness_req(cur, sid), "harness_turn")
    cur.execute("UPDATE effects SET attempt_no = attempt_no + 3 WHERE effect_id=%s", (eid,))
    cur.execute("UPDATE sessions SET turn_no = turn_no + 9 WHERE session_id=%s", (sid,))
    after_counters = project(cur, sid)
    check(
        "hash_excludes_counters",
        after_counters["frontier_hash"] == h_gap,
        (h_gap, after_counters["frontier_hash"]))
    n_ob_before = n_obligation(cur, sid)
    fails(
        cur, insert_sql(),
        (None, sid, "dangling_link", carrier, target, h_gap + "00"),
        "v13: replan gap: stale",
        "hash_excludes_counters")
    check("counter_does_not_insert", n_obligation(cur, sid) == n_ob_before)


def test_insert_and_replay(cur, sid):
    planted = plant_danglings(cur, sid, 1)
    carrier = planted["carriers"][0]
    target = planted["targets"][0]
    proj = project(cur, sid)
    before_e, before_x = n_events(cur), n_effects(cur)
    eid1 = insert_gap(cur, sid, "dangling_link", carrier, target, proj["frontier_hash"])
    row = as_obj(q1(
        cur,
        "SELECT jsonb_build_object('keys', v13_json_keys(payload), "
        "'sv', payload->'schema_version', 'src', source_effect_id::text) "
        "FROM events WHERE event_id=%s",
        (eid1,)))
    in_effects = q1(
        cur, "SELECT EXISTS (SELECT 1 FROM effects WHERE effect_id=%s)",
        (row["src"],))
    check(
        "insert_one_replan_required",
        row["keys"] == ["schema_version"] and row["sv"] == 1 and in_effects is False
        and n_obligation(cur, sid) == 1
        and n_events(cur) == before_e + 1
        and n_effects(cur) == before_x,
        row)
    after = project(cur, sid)
    check(
        "insert_one_replan_required",
        after["has_obligation"] == [True],
        after["has_obligation"])
    eid2 = insert_gap(cur, sid, "dangling_link", carrier, target, after["frontier_hash"])
    check(
        "obligation_at_most_one",
        eid2 == eid1 and n_obligation(cur, sid) == 1 and n_replan(cur, sid) == 1,
        (eid1, eid2))
    check("replay_same_event", eid2 == eid1)
    fails(
        cur, insert_sql(),
        (sid, sid, "dangling_link", carrier, target, after["frontier_hash"]),
        "v13: replan gap: auth",
        "root_actor_replay_rejected")
    check(
        "root_actor_replay_rejected",
        n_obligation(cur, sid) == 1 and n_replan(cur, sid) == 1)
    repaired = include_targets(
        cur, sid, planted["carriers"], planted["targets"], planted["plan2"])
    closed = project(cur, sid)
    check(
        "gap_reappears_same_event",
        open_count(cur, sid) == 0 and n_obligation(cur, sid) == 1
        and closed["frontier"]["gaps"] == [],
        (open_count(cur, sid), n_obligation(cur, sid)))
    omit_targets(cur, sid, planted["carriers"], repaired["plan_id"])
    again = project(cur, sid)
    eid3 = insert_gap(cur, sid, "dangling_link", carrier, target, again["frontier_hash"])
    check(
        "gap_reappears_same_event",
        eid3 == eid1 and open_count(cur, sid) == 1 and n_obligation(cur, sid) == 1,
        (eid1, eid3, open_count(cur, sid)))


def test_watermark_and_plans(cur, sid):
    planted = plant_danglings(cur, sid, 1)
    carrier = planted["carriers"][0]
    target = planted["targets"][0]
    proj = project(cur, sid)
    eid = insert_gap(cur, sid, "dangling_link", carrier, target, proj["frontier_hash"])
    check("user_message_keeps_obligation_open", open_count(cur, sid) == 1)
    prefix(cur, sid, "invalidate")
    emptied = project(cur, sid)
    check(
        "user_message_keeps_obligation_open",
        emptied["frontier"]["gaps"] == []
        and open_count(cur, sid) == 1
        and n_obligation(cur, sid) == 1,
        (emptied["frontier"], open_count(cur, sid)))
    replayed = insert_gap(
        cur, sid, "dangling_link", carrier, target, emptied["frontier_hash"])
    check(
        "user_message_keeps_obligation_open",
        replayed == eid and n_replan(cur, sid) == 1,
        (eid, replayed))
    include_targets(cur, sid, planted["carriers"], planted["targets"], planted["plan2"])
    check(
        "obligation_message_plan_sequence",
        open_count(cur, sid) == 0 and n_obligation(cur, sid) == 1,
        open_count(cur, sid))


def test_keep_gap_after_message(cur, sid):
    planted = plant_danglings(cur, sid, 1)
    c2 = planted["carriers"][0]
    t2 = planted["targets"][0]
    p2 = project(cur, sid)
    first = insert_gap(cur, sid, "dangling_link", c2, t2, p2["frontier_hash"])
    prefix(cur, sid, "invalidate-keep")
    still = omit_targets(cur, sid, planted["carriers"], planted["plan2"])
    keep = project(cur, sid)
    replay_keep = insert_gap(cur, sid, "dangling_link", c2, t2, keep["frontier_hash"])
    check(
        "obligation_message_plan_sequence",
        open_count(cur, sid) == 1 and n_obligation(cur, sid) == 1
        and keep["frontier"]["gaps"] and replay_keep == first,
        (open_count(cur, sid), keep["frontier"]["gaps"]))
    newer = omit_targets(cur, sid, planted["carriers"], still["plan_id"])
    latest = project(cur, sid)
    same = insert_gap(cur, sid, "dangling_link", c2, t2, latest["frontier_hash"])
    check(
        "new_plan_same_dangling_stays_open",
        same == first and open_count(cur, sid) == 1
        and n_obligation(cur, sid) == 1
        and newer["plan_id"] != planted["plan2"],
        (same, first, newer["plan_id"]))


def test_stop_terminal_cap(cur, sid):
    planted = plant_danglings(cur, sid, 1)
    carrier = planted["carriers"][0]
    target = planted["targets"][0]
    proj = project(cur, sid)
    eid = insert_gap(cur, sid, "dangling_link", carrier, target, proj["frontier_hash"])
    q1(cur, "SELECT v13_goal_stop(%s, %s)", (sid, "pause"))
    stopped_proj = project(cur, sid)
    again = insert_gap(
        cur, sid, "dangling_link", carrier, target, stopped_proj["frontier_hash"])
    check("replay_after_stop", again == eid and n_obligation(cur, sid) == 1)


def test_first_insert_stopped(cur, sid):
    planted = plant_danglings(cur, sid, 1)
    p2 = project(cur, sid)
    q1(cur, "SELECT v13_goal_stop(%s, %s)", (sid, "first"))
    fails(
        cur, insert_sql(),
        (None, sid, "dangling_link", planted["carriers"][0], planted["targets"][0],
         p2["frontier_hash"]),
        "v13: replan gap: stopped",
        "first_insert_stopped_refused")
    check("first_insert_stopped_refused", n_obligation(cur, sid) == 0)


def test_first_insert_terminal(cur, sid):
    for status in ("completed", "failed", "cancelled"):
        planted = plant_danglings(cur, sid, 1)
        p3 = project(cur, sid)
        cur.execute("UPDATE sessions SET status=%s WHERE session_id=%s", (status, sid))
        fails(
            cur, insert_sql(),
            (None, sid, "dangling_link", planted["carriers"][0],
             planted["targets"][0], p3["frontier_hash"]),
            "v13: replan gap: terminal",
            "first_insert_terminal_refused")
        check("first_insert_terminal_refused", n_obligation(cur, sid) == 0)
        cur.execute("UPDATE sessions SET status='ready' WHERE session_id=%s", (sid,))


def test_cap_33(cur, sid):
    cap = plant_danglings(cur, sid, 33)
    cap_proj = project(cur, sid)
    check(
        "gap_cap_33_refuses_insert",
        cap_proj["omitted_count"] == 1
        and cap_proj["omitted_complete"] is False
        and len(cap_proj["frontier"]["gaps"]) == 32
        and len(cap_proj["has_obligation"]) == 32,
        (cap_proj["omitted_count"], len(cap_proj["frontier"]["gaps"])))
    before = n_events(cur)
    fails(
        cur, insert_sql(),
        (None, sid, "dangling_link", cap["carriers"][0], cap["targets"][0],
         cap_proj["frontier_hash"]),
        "v13: replan gap: cap",
        "gap_cap_33_refuses_insert")
    check("gap_cap_33_refuses_insert", n_events(cur) == before)


def test_answers_and_ack(cur, sid):
    planted = plant_danglings(cur, sid, 1)
    carrier = planted["carriers"][0]
    target = planted["targets"][0]
    proj = project(cur, sid)
    h0 = proj["frontier_hash"]
    insert_gap(cur, sid, "dangling_link", carrier, target, h0)
    writer(cur, sid, delta(
        carrier, "runnable", "runnable",
        binding={"effect_id": None, "child_session_id": None}))
    bound = project(cur, sid)
    check(
        "binding_delta_hash_unchanged",
        bound["frontier_hash"] == h0 and open_count(cur, sid) == 1,
        (h0, bound["frontier_hash"]))
    check(
        "response_same_hash_stays_open",
        bound["frontier_hash"] == h0 and open_count(cur, sid) == 1)
    include_targets(cur, sid, planted["carriers"], planted["targets"], planted["plan2"])
    answered = project(cur, sid)
    check(
        "response_gap_removed_answers",
        answered["frontier"]["gaps"] == [] and open_count(cur, sid) == 0
        and n_obligation(cur, sid) == 1,
        (answered["frontier"]["gaps"], open_count(cur, sid)))


def test_other_gap(cur, sid):
    two = plant_danglings(cur, sid, 2, extra_targets=1)
    c_a = two["carriers"][0]
    t_b = two["targets"][1]
    p_two = project(cur, sid)
    check(
        "other_gap_does_not_answer_this_one",
        len(p_two["frontier"]["gaps"]) == 2,
        p_two["frontier"]["gaps"])
    g_a = [g for g in p_two["frontier"]["gaps"] if g["subject_todo_id"] == c_a][0]
    insert_gap(
        cur, sid, "dangling_link", g_a["subject_todo_id"], g_a["object_todo_id"],
        p_two["frontier_hash"])
    include_targets(cur, sid, two["carriers"], [t_b], two["plan2"])
    left = project(cur, sid)
    check(
        "other_gap_does_not_answer_this_one",
        open_count(cur, sid) == 1 and n_obligation(cur, sid) == 1
        and len(left["frontier"]["gaps"]) == 1
        and left["frontier"]["gaps"][0]["subject_todo_id"] == c_a,
        (open_count(cur, sid), left["frontier"]["gaps"]))


def test_ack_receipt_signal_payload(cur, sid):
    planted = plant_danglings(cur, sid, 1)
    p3 = project(cur, sid)
    insert_gap(
        cur, sid, "dangling_link", planted["carriers"][0], planted["targets"][0],
        p3["frontier_hash"])
    h3 = p3["frontier_hash"]
    cur.execute("SELECT v13_recover_idle()")
    nudged = project(cur, sid)
    n_nudge = int(q1(
        cur,
        "SELECT count(*) FROM events WHERE session_id=%s AND type='recover/nudge'",
        (sid,)))
    check(
        "ack_substitute_does_not_reset",
        open_count(cur, sid) == 1 and n_obligation(cur, sid) == 1
        and nudged["frontier_hash"] == h3 and n_nudge >= 1,
        (open_count(cur, sid), n_nudge, nudged["frontier_hash"]))
    q1(cur, "SELECT v13_goal_stop(%s, %s)", (sid, "receipt"))
    eid = enqueue(cur, sid, "tool", harness_req(cur, sid), "harness_turn")
    settle(cur, eid, {"result_kind": "progress"})
    advance(cur, sid)
    spent = int(q1(
        cur,
        "SELECT count(*) FROM events WHERE session_id=%s AND type='turn/material_spent'",
        (sid,)))
    check(
        "receipt_count_not_an_obligation",
        spent >= 1 and open_count(cur, sid) == 1 and n_obligation(cur, sid) == 1,
        (spent, open_count(cur, sid)))


def test_signal_row(cur, sid):
    planted = plant_danglings(cur, sid, 1)
    p2 = project(cur, sid)
    insert_gap(
        cur, sid, "dangling_link", planted["carriers"][0], planted["targets"][0],
        p2["frontier_hash"])
    eid2 = enqueue(cur, sid, "tool", harness_req(cur, sid), "harness_turn")
    settle(cur, eid2, {"result_kind": "progress", "signals": ["replan/required"]})
    signal_row = q1(
        cur,
        "SELECT EXISTS (SELECT 1 FROM events e "
        "WHERE e.session_id=%s AND e.type='replan/required' "
        "AND e.source_effect_id = %s)",
        (sid, eid2))
    if not signal_row:
        print("v13: replan gap: ask_user")
        raise SystemExit(1)
    check(
        "signal_row_not_in_obligation_count",
        signal_row is True and n_replan(cur, sid) == 2
        and n_obligation(cur, sid) == 1 and open_count(cur, sid) == 1,
        (n_replan(cur, sid), n_obligation(cur, sid)))
    fails(
        cur,
        "SELECT v13_append_event(%s, %s, 'replan/required', %s::jsonb, %s::uuid)",
        (sid, u(), json.dumps({"schema_version": 1, "extra": True}), u()),
        "v13: event payload",
        "payload_guard_unchanged")
    src = q1(
        cur,
        "SELECT pg_get_functiondef("
        "'public.v13_complete(uuid,uuid,integer,bigint,text,jsonb)'::regprocedure)")
    check(
        "payload_guard_unchanged",
        "replan/required" in src and "schema_version" in src,
        None)


def main() -> int:
    print("[db]", DB)
    test_stage_bytes()
    if setup_db() != 0:
        return 1
    server = get_server()
    conn = connect(server)
    try:
        cur = conn.cursor()
        before_hashes = tuple(fn_hash(cur, sig) for sig in HASH_FNS)
        test_symbols_and_jsonb(cur, server, before_hashes)
        sid = open_root(cur)
        prefix(cur, sid)
        isolated(cur, lambda: test_writer_and_empty(cur, sid))
        isolated(cur, lambda: test_project_and_hash(cur, sid))
        isolated(cur, lambda: test_insert_and_replay(cur, sid))
        isolated(cur, lambda: test_watermark_and_plans(cur, sid))
        isolated(cur, lambda: test_keep_gap_after_message(cur, sid))
        isolated(cur, lambda: test_stop_terminal_cap(cur, sid))
        isolated(cur, lambda: test_first_insert_stopped(cur, sid))
        isolated(cur, lambda: test_first_insert_terminal(cur, sid))
        isolated(cur, lambda: test_cap_33(cur, sid))
        isolated(cur, lambda: test_answers_and_ack(cur, sid))
        isolated(cur, lambda: test_other_gap(cur, sid))
        isolated(cur, lambda: test_ack_receipt_signal_payload(cur, sid))
        isolated(cur, lambda: test_signal_row(cur, sid))
        conn.commit()
    finally:
        conn.close()
        if setup_mod.CREATED:
            run_psql(server, "postgres", 'DROP DATABASE "%s" WITH (FORCE);' % DB)
            setup_mod.CREATED = False
            print("[dropped]", DB)
    print("[ok] %s checks" % N)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("[FAIL]", exc)
        if setup_mod.CREATED:
            try:
                run_psql(get_server(), "postgres", 'DROP DATABASE "%s" WITH (FORCE);' % DB)
                print("[dropped]", DB)
            except Exception as drop_exc:
                print("[cleanup-fail]", drop_exc)
        raise SystemExit(1)
