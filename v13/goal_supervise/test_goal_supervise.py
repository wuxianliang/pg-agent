"""Phase C goal_supervise gate.

Run: UV_FROZEN=1 uv run python v13/goal_supervise/test_goal_supervise.py
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_REPEATABLE_READ

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v13.load import run_psql
from v13.goal_supervise.setup_db import DB, main as setup_db
import v13.goal_supervise.setup_db as setup_mod

N = 0
SQL = (ROOT / "v13_goal_supervise.sql").read_text()
README = (ROOT / "README.md").read_text()
HASH_FNS = (
    "public.v13_advance(uuid,jsonb)",
    "public.v13_goal_fingerprint(uuid)",
    "public.v13_recover_idle()",
    "public.v13_should_run(uuid)",
    "public.v13_scheduler_hint(uuid)",
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


def fn_src(cur, sig):
    return q1(
        cur,
        "SELECT pg_get_functiondef(%s::regprocedure)",
        (sig,))


def n_events(cur, sid=None, typ=None):
    if sid and typ:
        return int(q1(
            cur,
            "SELECT count(*) FROM events WHERE session_id=%s AND type=%s",
            (sid, typ)))
    if sid:
        return int(q1(cur, "SELECT count(*) FROM events WHERE session_id=%s", (sid,)))
    return int(q1(cur, "SELECT count(*) FROM events"))


def n_effects(cur, sid=None):
    if sid:
        return int(q1(cur, "SELECT count(*) FROM effects WHERE session_id=%s", (sid,)))
    return int(q1(cur, "SELECT count(*) FROM effects"))


def n_artifacts(cur):
    return int(q1(cur, "SELECT count(*) FROM artifacts"))


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


def settle_complete(cur, eid, result):
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


def offer_body(apply_id, ref, kind="approval", source=None, options=None,
               deadline=None):
    return {
        "schema_version": 1,
        "apply_id": apply_id,
        "interaction_ref": ref,
        "offer_kind": kind,
        "source_effect_id": source or u(),
        "options": options if options is not None else [],
        "deadline": deadline,
    }


def offer_sql():
    return "SELECT v13_interaction_offer(%s::uuid, %s::uuid, %s::uuid, %s::jsonb)"


def do_offer(cur, sid, body, actor=None, apply=None):
    apply = apply or body["apply_id"]
    cur.execute(offer_sql(), (actor, sid, apply, json.dumps(body)))
    return str(cur.fetchone()[0])


def request(tool, paths, payload, label="read_only", key=None):
    return {
        "schema_version": 1,
        "tool": tool,
        "label": label,
        "paths": paths,
        "attempt_key": key or u(),
        "payload": payload,
    }


def opened(cur, sid, label, req, root="/tmp/ws", roots=None):
    cur.execute(
        "SELECT v13_tool_effect_open(%s::uuid, %s::uuid, %s, %s, %s::text[], %s::jsonb)",
        (None, sid, label, root, roots or [root, "/tmp/ws/sub"], json.dumps(req)))
    return as_obj(cur.fetchone()[0])


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
        "v13/plan_contract", "v13/plan_read", "v13/frontier_gap",
    ]
    diff = subprocess.check_output(["git", "diff", "HEAD", "--", *paths], cwd=AGENT_ROOT)
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
        order.rfind("frontier_gap") < order.rfind("goal_supervise")
        and through.rfind('"frontier_gap": 37') < through.rfind('"goal_supervise": 38')
        and "goal_supervise" not in order[:order.rfind("frontier_gap")]
    )
    if load.strip():
        load_ok = "goal_supervise" in load and removed == [] and tail_ok
    else:
        load_ok = tail_ok and "goal_supervise" in text
    check("stage_bytes", diff == b"" and load_ok, (removed, tail_ok, bool(load.strip())))
    check(
        "no_second_advance_replace",
        "CREATE OR REPLACE FUNCTION public.v13_advance" not in SQL
        and "CREATE OR REPLACE FUNCTION v13_advance" not in SQL,
        None)
    opener = subprocess.check_output(
        ["git", "diff", "HEAD", "--", "v13/workspace_admit", "v13/workspace_exec"],
        cwd=AGENT_ROOT)
    check("opener_files_unmodified", opener == b"")


def test_static(cur, before_hashes):
    after = tuple(fn_hash(cur, sig) for sig in HASH_FNS)
    check("recover_idle_unmodified", after[2] == before_hashes[2], (after[2], before_hashes[2]))
    check("hint_function_unmodified", after[4] == before_hashes[4], (after[4], before_hashes[4]))
    check("no_second_advance_replace", after[0] == before_hashes[0])
    ver = q1(
        cur,
        "SELECT version FROM v13_policies WHERE name='should_run' AND active "
        "ORDER BY version DESC LIMIT 1")
    check("policy_version_still_3", ver == 3, ver)
    pol = as_obj(q1(
        cur,
        "SELECT value FROM v13_policies WHERE name='notify_policy' AND version=1 AND active"))
    check("notify_policy_idempotent", pol is not None
        and pol.get("schema_version") == 1
        and pol.get("notify_on_user_gate") is True
        and pol.get("notify_on_human_pending") is True,
        pol)
    cur.execute(SQL.split("CREATE OR REPLACE")[0])
    pol2 = as_obj(q1(
        cur,
        "SELECT value FROM v13_policies WHERE name='notify_policy' AND version=1 AND active"))
    check("notify_policy_idempotent", pol2 == pol, pol2)
    wt = as_obj(q1(
        cur,
        "SELECT value FROM v13_policies WHERE name='workspace_tool_subset' AND version=1 AND active"))
    check("workspace_subset_v1_unchanged", wt is not None and "workspace_tool_subset" not in SQL)
    wf = as_obj(q1(
        cur,
        "SELECT value FROM v13_policies WHERE name='workflow_template' AND version=1 AND active"))
    check("workflow_template_v1_unchanged", wf is not None and "workflow_template" not in SQL)
    check("judgment_templates_untouched", "judgment_templates" not in SQL)
    check(
        "v11_not_marked_closed",
        "V11 未读" in README and "不得声称 auto-wake 已闭合" in README)
    check(
        "no_link_table_no_send_ledger",
        "CREATE TABLE" not in SQL and "send_ledger" not in SQL and "link_table" not in SQL)
    check("no_advisory_lock", "pg_advisory" not in SQL)
    check(
        "no_renewal_loop_in_sql",
        "pg_cron" not in SQL and "pg_sleep" not in SQL.lower())
    idx = q1(
        cur,
        "SELECT count(*) FROM pg_indexes WHERE tablename='events' "
        "AND indexdef ILIKE '%UNIQUE%' AND indexdef ILIKE '%interaction%'")
    check("no_offer_unique_index", int(idx) == 0, idx)
    schema = as_obj(q1(
        cur,
        "SELECT value FROM v13_policies WHERE name='harness_result_schema' AND active "
        "ORDER BY version DESC LIMIT 1"))
    props = ((schema or {}).get("schema") or {}).get("properties") or {}
    check(
        "evidence_not_in_harness_result",
        "evidence" not in props and "evidence_refs" not in props,
        list(props))
    ev_src = fn_src(cur, "public.v13_evidence_check(uuid,uuid,jsonb)")
    wake_src = fn_src(cur, "public.v13_wake_is_satisfied_v1(uuid,uuid,jsonb)")
    check(
        "evidence_not_welded_to_wake",
        "v13_wake_is_satisfied" not in ev_src and "v13_evidence_check" not in wake_src)
    adv = fn_src(cur, "public.v13_advance(uuid,jsonb)")
    check("offer_not_wired_into_advance", "v13_interaction_offer" not in adv)
    check(
        "two_key_request_unchanged",
        "'schema_version', 1" in adv and "'interaction_ref'" in adv)
    unpaid = fn_src(cur, "public.v13_unpaid_harness_turn(uuid)")
    pred = fn_src(cur, "public.v13_harness_predecessor(uuid)")
    settle = fn_src(cur, "public.v13_harness_settle(uuid,uuid,uuid,jsonb)")
    check(
        "unpaid_predicate_matches_live_arm",
        "v13_is_harness_tool" in unpaid
        and "v13_harness_request_ok" in unpaid
        and "v13_last_user_seq" in unpaid
        and "v13_harness_predecessor" in unpaid
        and "LIMIT 1" not in unpaid
        and "ORDER BY" not in unpaid
        and "v13_is_harness_tool" in pred,
        unpaid)
    check(
        "settle_selector_matches_live_predecessor",
        "v13_harness_predecessor" in settle
        and "ORDER BY" not in settle
        and "LIMIT 1" not in settle
        and "v_stored IS DISTINCT FROM p_snap" in settle,
        settle)
    rq_hash = fn_hash(cur, "public.v13_requeue_stale()")
    print("[requeue_hash]", rq_hash)
    lease_src = fn_src(cur, "public.v13_goal_lease_once(uuid,uuid,uuid)")
    sess_at = lease_src.find("FROM public.sessions")
    eff_at = lease_src.find("FROM public.effects")
    check(
        "lease_lock_session_then_effect",
        sess_at != -1 and eff_at != -1 and sess_at < eff_at,
        (sess_at, eff_at))
    hint = q1(
        cur,
        "SELECT pg_get_function_identity_arguments("
        "'public.v13_scheduler_hint(uuid)'::regprocedure)")
    check("hint_function_unmodified", hint == "p_sid uuid" or "uuid" in (hint or ""), hint)
    revoked = q1(
        cur,
        "SELECT NOT has_function_privilege('public', "
        "'public.v13_interaction_offer(uuid,uuid,uuid,jsonb)', 'EXECUTE')")
    check("no_second_advance_replace", revoked is True, revoked)
    check(
        "recover_idle_unmodified",
        "v13_recover_idle" not in SQL and rq_hash in README,
        rq_hash)


def test_waiting_and_explore(cur, sid):
    before_st = q1(cur, "SELECT status FROM sessions WHERE session_id=%s", (sid,))
    eid = enqueue(
        cur, sid, "human",
        {"schema_version": 1, "interaction_ref": "ix-wait"})
    st = q1(cur, "SELECT status FROM effects WHERE effect_id=%s", (eid,))
    cur.execute(
        "UPDATE sessions SET status='waiting' WHERE session_id=%s AND status IN ('ready','waiting')",
        (sid,))
    sess = q1(cur, "SELECT status FROM sessions WHERE session_id=%s", (sid,))
    check(
        "waiting_not_terminal",
        sess == "waiting" and sess not in ("completed", "failed", "cancelled")
        and st in ("ready", "claimed"),
        (sess, st, before_st))
    cur.execute("UPDATE effects SET status='succeeded' WHERE effect_id=%s", (eid,))
    cur.execute("SAVEPOINT explore")
    llm = q1(
        cur,
        "SELECT v13_enqueue_effect(%s, 'llm', %s::jsonb)",
        (sid, json.dumps({"route": {"action": "llm", "reason": "explore"}})))
    cur.execute(
        "UPDATE effects SET status='claimed', attempt_no=1, fence=1, lease_owner='w', "
        "lease_until=clock_timestamp()+interval '1 hour' WHERE effect_id=%s "
        "RETURNING attempt_no, fence",
        (llm,))
    attempt, fence = cur.fetchone()
    cur.execute(
        "SELECT v13_complete(%s, %s, %s, 'succeeded', %s::jsonb)",
        (llm, attempt, fence, json.dumps({
            "text": "ok",
            "tool_calls": [{
                "id": "tc1", "name": "spawn_subsession", "args": {"task": "one"}}],
        })))
    cur.fetchone()
    fails(
        cur, "SELECT v13_triage_block_explore_spawn(%s)", (sid,),
        "v13: explore spawn", "explore_spawn_still_raises")
    cur.execute("ROLLBACK TO SAVEPOINT explore")


def test_offer_payload(cur, sid):
    apply = u()
    ref = "ref-" + apply
    body = offer_body(apply, ref)
    eid = do_offer(cur, sid, body, apply=apply)
    check("offer_replay", eid == apply, eid)
    eid2 = do_offer(cur, sid, body, apply=apply)
    check("offer_replay", eid2 == eid, (eid2, eid))
    n1 = n_events(cur, sid, "interaction/offered")
    check("offer_replay", n1 == 1, n1)

    bad = dict(body)
    bad["extra"] = True
    fails(cur, offer_sql(), (None, sid, apply, json.dumps(bad)),
          "v13: interaction offer: canonical", "offer_replay")
    missing = {k: v for k, v in body.items() if k != "options"}
    fails(cur, offer_sql(), (None, sid, apply, json.dumps(missing)),
          "v13: interaction offer: canonical", "offer_replay")
    sv = dict(body, schema_version=2)
    fails(cur, offer_sql(), (None, sid, apply, json.dumps(sv)),
          "v13: interaction offer: canonical", "offer_replay")
    no_src = dict(body)
    no_src.pop("source_effect_id")
    no_src["source_effect_id"] = None
    fails(cur, offer_sql(), (None, sid, apply, json.dumps(no_src)),
          "v13: interaction offer: canonical", "offer_replay")
    absent_src = {k: v for k, v in body.items() if k != "source_effect_id"}
    fails(cur, offer_sql(), (None, sid, apply, json.dumps(absent_src)),
          "v13: interaction offer: canonical", "offer_replay")
    not_uuid = dict(body, source_effect_id="not-a-uuid")
    fails(cur, offer_sql(), (None, sid, apply, json.dumps(not_uuid)),
          "v13: interaction offer: canonical", "offer_replay")
    mismatch = dict(body, apply_id=u())
    fails(cur, offer_sql(), (None, sid, apply, json.dumps(mismatch)),
          "v13: interaction offer: canonical", "offer_replay")
    kind = dict(body, offer_kind="skip")
    fails(cur, offer_sql(), (None, sid, apply, json.dumps(kind)),
          "v13: interaction offer: canonical", "offer_replay")
    opts = dict(body, options=[1, 2])
    fails(cur, offer_sql(), (None, sid, apply, json.dumps(opts)),
          "v13: interaction offer: canonical", "offer_replay")
    too_many = dict(body, options=["a", "b", "c", "d", "e"])
    fails(cur, offer_sql(), (None, sid, apply, json.dumps(too_many)),
          "v13: interaction offer: canonical", "offer_replay")
    dead = dict(body, deadline="not-a-time")
    fails(cur, offer_sql(), (None, sid, apply, json.dumps(dead)),
          "v13: interaction offer: canonical", "offer_replay")
    other = dict(body, offer_kind="question")
    fails(cur, offer_sql(), (None, sid, apply, json.dumps(other)),
          "v13: interaction offer: replay_conflict", "offer_replay")

    past = offer_body(u(), "past-" + u(), deadline="2000-01-01T00:00:00Z")
    n_skip = n_events(cur, sid, "human/responded")
    peid = do_offer(cur, sid, past, apply=past["apply_id"])
    n_skip2 = n_events(cur, sid, "human/responded")
    check(
        "deadline_does_not_skip",
        peid == past["apply_id"] and n_skip2 == n_skip
        and "v13_complete" not in SQL,
        (peid, n_skip, n_skip2))


def test_offer_auth_stop_terminal(cur, sid):
    apply = u()
    body = offer_body(apply, "auth-" + apply)
    first = do_offer(cur, sid, body, apply=apply)
    fails(
        cur, offer_sql(), (sid, sid, apply, json.dumps(body)),
        "v13: interaction offer: auth", "offer_auth_before_replay")
    still = n_events(cur, sid, "interaction/offered")
    check("offer_auth_before_replay", still >= 1 and first == apply, still)

    cur.execute("SAVEPOINT stop_offer")
    q1(cur, "SELECT v13_goal_stop(%s, %s)", (sid, "pause"))
    replay = do_offer(cur, sid, body, apply=apply)
    check("offer_replay_after_stop", replay == first, replay)
    fresh = offer_body(u(), "stopped-first-" + u())
    fails(
        cur, offer_sql(), (None, sid, fresh["apply_id"], json.dumps(fresh)),
        "v13: interaction offer: stopped", "offer_first_write_stopped_refused")
    cur.execute("ROLLBACK TO SAVEPOINT stop_offer")

    cur.execute("SAVEPOINT term_offer")
    cur.execute("UPDATE sessions SET status='completed' WHERE session_id=%s", (sid,))
    term = offer_body(u(), "term-" + u())
    fails(
        cur, offer_sql(), (None, sid, term["apply_id"], json.dumps(term)),
        "v13: interaction offer: terminal", "offer_first_write_terminal_refused")
    cur.execute("ROLLBACK TO SAVEPOINT term_offer")


def test_offer_isolation(server, sid):
    conn = connect(server)
    try:
        conn.set_isolation_level(ISOLATION_LEVEL_REPEATABLE_READ)
        cur = conn.cursor()
        before = n_events(cur, sid, "interaction/offered")
        body = offer_body(u(), "iso-" + u())
        try:
            cur.execute(offer_sql(), (None, sid, body["apply_id"], json.dumps(body)))
            raise AssertionError("isolation offer succeeded")
        except psycopg2.Error as exc:
            msg = exc.diag.message_primary or str(exc).splitlines()[0]
            check(
                "offer_isolation_rejected",
                "v13: interaction offer: canonical" in msg,
                msg)
        conn.rollback()
        check("offer_isolation_rejected", n_events(cur, sid, "interaction/offered") == before)
    finally:
        conn.close()


def test_offer_race(server, sid):
    apply = u()
    body = offer_body(apply, "race-" + apply)
    conn1 = connect(server)
    conn2 = connect(server)
    box = {}
    try:
        cur1 = conn1.cursor()
        cur1.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        cur1.execute(offer_sql(), (None, sid, apply, json.dumps(body)))
        eid_a = str(cur1.fetchone()[0])

        def second():
            try:
                cur2 = conn2.cursor()
                cur2.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
                cur2.execute("SET lock_timeout = '15s'")
                cur2.execute(offer_sql(), (None, sid, apply, json.dumps(body)))
                box["eid"] = str(cur2.fetchone()[0])
                conn2.commit()
            except Exception as exc:
                box["err"] = str(exc)
                conn2.rollback()

        worker = threading.Thread(target=second)
        worker.start()
        time.sleep(0.4)
        check("offer_race_one_event", worker.is_alive() and "eid" not in box, box)
        conn1.commit()
        worker.join(15)
        n = None
        cur = conn1.cursor()
        n = q1(
            cur,
            "SELECT count(*) FROM events WHERE session_id=%s AND type='interaction/offered' "
            "AND payload->>'interaction_ref'=%s",
            (sid, body["interaction_ref"]))
        check(
            "offer_race_one_event",
            not worker.is_alive()
            and box.get("eid") == eid_a
            and int(n) == 1
            and "err" not in box,
            (box, n, eid_a))
    finally:
        conn1.close()
        conn2.close()


def test_observe(cur, sid):
    before_ev = n_events(cur)
    before_ef = n_effects(cur)
    fold = as_obj(q1(cur, "SELECT v13_observe_fold(%s::uuid, %s::uuid)", (None, sid)))
    check(
        "observe_zero_write",
        n_events(cur) == before_ev and n_effects(cur) == before_ef
        and fold["schema_version"] == 1
        and fold["root_session_id"] == sid,
        fold)
    fails(
        cur, "SELECT v13_observe_fold(%s::uuid, %s::uuid)", (sid, sid),
        "v13: observe fold: auth", "observe_auth_raises")
    human = enqueue(cur, sid, "human", {"schema_version": 1, "interaction_ref": "obs"})
    after_h = n_effects(cur)
    fold2 = as_obj(q1(cur, "SELECT v13_observe_fold(%s::uuid, %s::uuid)", (None, sid)))
    check(
        "observer_does_not_answer",
        fold2["pending_human"] is True
        and q1(cur, "SELECT status FROM effects WHERE effect_id=%s", (human,)) in ("ready", "claimed")
        and n_effects(cur) == after_h
        and "v13_complete" not in fn_src(cur, "public.v13_observe_fold(uuid,uuid)"),
        fold2)
    kids = as_obj(q1(
        cur,
        "SELECT v13_spawn_subsession(%s, %s::jsonb)",
        (sid, json.dumps({
            "schema_version": 1,
            "children": [
                {"tool_call_id": "c1", "task": "one"},
                {"tool_call_id": "c2", "task": "two"},
                {"tool_call_id": "c3", "task": "three"},
                {"tool_call_id": "c4", "task": "four"},
            ],
        }))))
    check("observe_cap_omitted", kids is not None and len(kids.get("children") or []) == 4, kids)
    fold3 = as_obj(q1(cur, "SELECT v13_observe_fold(%s::uuid, %s::uuid)", (None, sid)))
    check(
        "observe_cap_omitted",
        fold3["omitted_count"] == 1
        and fold3["omitted_complete"] is False
        and fold3["obligation_open_count"] == 0
        and n_events(cur) >= before_ev,
        fold3)
    check(
        "observe_zero_write",
        n_effects(cur) == after_h)


def test_notify(cur, sid):
    hint_src = fn_src(cur, "public.v13_scheduler_hint(uuid)")
    check("dont_notify_not_a_mute", "mute" not in hint_src.lower())
    dto = as_obj(q1(cur, "SELECT v13_notify_project(%s)", (sid,)))
    ev0 = n_events(cur)
    check(
        "notify_eligible_inserts_nothing",
        n_events(cur) == ev0,
        dto)
    tid = u()
    writer(cur, sid, plan_body([todo(tid, cls="user_gate")], max_seq(cur, sid)))
    ev1 = n_events(cur)
    dto2 = as_obj(q1(cur, "SELECT v13_notify_project(%s)", (sid,)))
    check(
        "notify_eligible_inserts_nothing",
        dto2["deliver"] is True and dto2["reason"] == "eligible"
        and n_events(cur) == ev1,
        dto2)
    cur.execute("SAVEPOINT nwait")
    try:
        writer(cur, sid, {
            "schema_version": 1, "call_kind": "todo_delta", "verb": "update",
            "todo_id": tid, "status_from": "runnable", "status_to": "waiting",
            "binding": None, "due": None, "quarantine": None,
            "text_hash": sha(ttext(tid)), "link": None,
        })
        wait_ev = n_events(cur)
        dto_wait = as_obj(q1(cur, "SELECT v13_notify_project(%s)", (sid,)))
        check("notify_waiting_user_gate", dto_wait["deliver"] is True
              and dto_wait["reason"] == "eligible" and n_events(cur) == wait_ev, dto_wait)
        waiting_id = u()
        writer(cur, sid, plan_body([todo(waiting_id, cls="user_gate", status="blocked")], max_seq(cur, sid)))
        dto_wait = as_obj(q1(cur, "SELECT v13_notify_project(%s)", (sid,)))
        check(
            "notify_blocked_user_gate",
            dto_wait["deliver"] is True and dto_wait["reason"] == "eligible",
            dto_wait)
    finally:
        cur.execute("ROLLBACK TO SAVEPOINT nwait")
    cur.execute("SAVEPOINT nstop")
    q1(cur, "SELECT v13_goal_stop(%s, %s)", (sid, "n"))
    dto3 = as_obj(q1(cur, "SELECT v13_notify_project(%s)", (sid,)))
    check(
        "dont_notify_not_a_mute",
        dto3["deliver"] is False and dto3["reason"] == "stopped_dont_notify",
        dto3)
    cur.execute("ROLLBACK TO SAVEPOINT nstop")


def test_evidence(cur, sid):
    ids = [u() for _ in range(3)]
    cur.execute("SELECT id::text FROM unnest(%s::uuid[]) AS id ORDER BY id", (ids,))
    tid_a, tid_g, tid_m = [row[0] for row in cur.fetchall()]
    mon = todo(tid_m, cls="continuous_monitor", status="waiting")
    mon["due"] = "2026-09-29 00:00:00+00"
    writer(cur, sid, plan_body([
        todo(tid_a, cls="advancement_task"),
        todo(tid_g, cls="user_gate"),
        mon,
    ], max_seq(cur, sid)))
    eid = enqueue(cur, sid, "tool", harness_req(cur, sid), "harness_turn")
    complete_word = settle_complete(cur, eid, {"result_kind": "progress"})
    check("evidence_absent_complete_result", complete_word == "accepted"
          and q1(cur, "SELECT status FROM effects WHERE effect_id=%s", (eid,)) == "succeeded",
          complete_word)
    before_absent_art = n_artifacts(cur)
    before_absent_ev = n_events(cur)
    ok_null = q1(
        cur, "SELECT v13_evidence_check(%s::uuid, %s::uuid, %s::jsonb)",
        (sid, tid_a, None))
    check(
        "evidence_absent_complete_works",
        ok_null == "ok"
        and n_artifacts(cur) == before_absent_art
        and n_events(cur) == before_absent_ev)
    check("evidence_null_ok_for_advancement", ok_null == "ok", ok_null)
    n_art = n_artifacts(cur)
    n_ev = n_events(cur)
    fails(
        cur, "SELECT v13_evidence_check(%s::uuid, %s::uuid, %s::jsonb)",
        (sid, tid_a, json.dumps([u()])),
        "v13: evidence: bad_ref", "evidence_bad_ref_no_write")
    check("evidence_bad_ref_no_write", n_artifacts(cur) == n_art and n_events(cur) == n_ev)
    fails(
        cur, "SELECT v13_evidence_check(%s::uuid, %s::uuid, %s::jsonb)",
        (sid, tid_g, json.dumps([u()])),
        "v13: evidence: wrong_class", "evidence_wrong_class_user_gate")
    fails(
        cur, "SELECT v13_evidence_check(%s::uuid, %s::uuid, %s::jsonb)",
        (sid, tid_m, json.dumps([u()])),
        "v13: evidence: wrong_class", "evidence_wrong_class_monitor")
    try:
        art = str(q1(
            cur, "SELECT v13_artifact_land(%s::uuid, 'context', %s::jsonb)",
            (eid, json.dumps({"schema_version": 1, "note": "evidence"}))))
    except psycopg2.Error as exc:
        print("v13: evidence: ask_user")
        raise SystemExit(1) from exc
    if not art:
        print("v13: evidence: ask_user")
        raise SystemExit(1)
    got = q1(
        cur, "SELECT v13_evidence_check(%s::uuid, %s::uuid, %s::jsonb)",
        (sid, tid_a, json.dumps([art])))
    check("evidence_good_ref", got == "ok", got)


def test_settle_snap_binding(cur, sid):
    cur.execute("SAVEPOINT failed_snap")
    try:
        prefix(cur, sid, "failed snap")
        q1(cur, "SELECT v13_goal_stop(%s, %s)", (sid, "failed-snap"))
        eid = enqueue(cur, sid, "tool", harness_req(cur, sid), "harness_turn")
        settle_complete(cur, eid, {"result_kind": "progress"})
        cur.execute(
            "UPDATE effects SET result = result || %s::jsonb WHERE effect_id=%s",
            (json.dumps({"failed": False}), eid))
        stored = as_obj(q1(cur, "SELECT result FROM effects WHERE effect_id=%s", (eid,)))
        before_ev = n_events(cur, sid)
        before_spent = n_events(cur, sid, "turn/material_spent")
        forged = dict(stored)
        forged.pop("failed", None)
        fails(
            cur,
            "SELECT v13_harness_settle(%s::uuid, %s::uuid, %s::uuid, %s::jsonb)",
            (None, sid, eid, json.dumps(forged)),
            "v13: harness settle: canonical",
            "stopped_failed_snap_binding")
        fails(
            cur,
            "SELECT v13_harness_settle(%s::uuid, %s::uuid, %s::uuid, %s::jsonb)",
            (None, sid, eid, json.dumps(dict(stored, failed=None))),
            "v13: harness settle: canonical",
            "stopped_failed_null_forgery_rejected")
        check(
            "stopped_failed_snap_binding",
            n_events(cur, sid) == before_ev
            and n_events(cur, sid, "turn/material_spent") == before_spent)
        word = q1(
            cur,
            "SELECT v13_harness_settle(%s::uuid, %s::uuid, %s::uuid, %s::jsonb)",
            (None, sid, eid, json.dumps(stored)))
        check(
            "stopped_failed_snap_no_advance",
            word == "skipped_failed"
            and n_events(cur, sid) == before_ev
            and n_events(cur, sid, "turn/material_spent") == before_spent,
            word)
    finally:
        cur.execute("ROLLBACK TO SAVEPOINT failed_snap")

    cur.execute("SAVEPOINT null_failed")
    try:
        prefix(cur, sid, "null failed")
        q1(cur, "SELECT v13_goal_stop(%s, %s)", (sid, "null-failed"))
        eid = enqueue(cur, sid, "tool", harness_req(cur, sid), "harness_turn")
        settle_complete(cur, eid, {"result_kind": "progress"})
        cur.execute(
            "UPDATE effects SET result = result || %s::jsonb WHERE effect_id=%s",
            (json.dumps({"failed": None}), eid))
        stored = as_obj(q1(cur, "SELECT result FROM effects WHERE effect_id=%s", (eid,)))
        before_spent = n_events(cur, sid, "turn/material_spent")
        word = q1(
            cur,
            "SELECT v13_harness_settle(%s::uuid, %s::uuid, %s::uuid, %s::jsonb)",
            (None, sid, eid, json.dumps(stored)))
        check(
            "stopped_failed_null_still_settles",
            word != "skipped_failed"
            and n_events(cur, sid, "turn/material_spent") == before_spent + 1,
            (word, before_spent))
    finally:
        cur.execute("ROLLBACK TO SAVEPOINT null_failed")


def test_multiple_unpaid_selector(cur, sid):
    cur.execute("SAVEPOINT multiple_unpaid")
    try:
        prefix(cur, sid, "multiple unpaid")
        first = enqueue(cur, sid, "tool", harness_req(cur, sid), "harness_turn")
        settle_complete(cur, first, {"result_kind": "progress"})
        second = enqueue(cur, sid, "tool", harness_req(cur, sid), "harness_turn")
        settle_complete(cur, second, {"result_kind": "progress"})
        cur.execute("SELECT effect_id::text FROM v13_unpaid_harness_turn(%s)", (sid,))
        rows = [r[0] for r in cur.fetchall()]
        winner = str(q1(cur, "SELECT v13_harness_predecessor(%s)", (sid,)))
        loser = first if winner == second else second
        physical_unpaid = int(q1(cur,
            "SELECT count(*) FROM effects e WHERE e.effect_id = ANY(%s::uuid[]) "
            "AND NOT EXISTS (SELECT 1 FROM events ev WHERE ev.source_effect_id=e.effect_id "
            "AND ev.type='turn/material_spent')", ([first, second],)))
        check("multiple_unpaid_candidates", physical_unpaid == 2 and rows == [winner],
              (physical_unpaid, rows, winner))
        stored = q1(cur, "SELECT result FROM effects WHERE effect_id=%s", (loser,))
        before_spent = n_events(cur, sid, "turn/material_spent")
        fails(
            cur,
            "SELECT v13_harness_settle(%s::uuid, %s::uuid, %s::uuid, %s::jsonb)",
            (None, sid, loser, json.dumps(stored)),
            "v13: harness settle: canonical",
            "multiple_unpaid_candidates")
        check(
            "multiple_unpaid_candidates",
            n_events(cur, sid, "turn/material_spent") == before_spent)
        stored_winner = q1(cur, "SELECT result FROM effects WHERE effect_id=%s", (winner,))
        q1(
            cur,
            "SELECT v13_harness_settle(%s::uuid, %s::uuid, %s::uuid, %s::jsonb)",
            (None, sid, winner, json.dumps(stored_winner)))
        source = q1(
            cur,
            "SELECT count(*) FROM events WHERE session_id=%s AND type='turn/material_spent' "
            "AND payload->>'effect_id'=%s",
            (sid, winner))
        loser_spent = int(q1(cur,
            "SELECT count(*) FROM events WHERE source_effect_id=%s AND type='turn/material_spent'",
            (loser,)))
        check("multiple_unpaid_candidates", int(source) == 1 and loser_spent == 0,
              (source, loser_spent))
        check("settled_predecessor_does_not_fall_back",
              q1(cur, "SELECT count(*) FROM v13_unpaid_harness_turn(%s)", (sid,)) == 0)
        fails(cur, "SELECT v13_harness_settle(%s::uuid,%s::uuid,%s::uuid,%s::jsonb)",
              (None, sid, loser, json.dumps(stored)), "v13: harness settle: canonical",
              "settled_predecessor_does_not_fall_back")
    finally:
        cur.execute("ROLLBACK TO SAVEPOINT multiple_unpaid")


def test_unpaid_settle(cur, sid, server, conn):
    wait_id = enqueue(cur, sid, "tool", harness_req(cur, sid), "harness_turn")
    settle_complete(cur, wait_id, {
        "result_kind": "wait",
        "wait_reason": "evidence",
        "wake": {"kind": "not_before", "at": "2099-01-01T00:00:00Z"},
    })
    n_wait = int(q1(cur, "SELECT count(*) FROM v13_unpaid_harness_turn(%s)", (sid,)))
    check("unpaid_predicate_matches_live_arm", n_wait == 0, n_wait)

    prefix(cur, sid, "next turn")
    q1(cur, "SELECT v13_goal_stop(%s, %s)", (sid, "settle"))
    eid = enqueue(cur, sid, "tool", harness_req(cur, sid), "harness_turn")
    settle_complete(cur, eid, {"result_kind": "progress"})
    snap = as_obj(q1(cur, "SELECT result FROM effects WHERE effect_id=%s", (eid,)))
    cur.execute("SELECT effect_id::text FROM v13_unpaid_harness_turn(%s)", (sid,))
    rows = [r[0] for r in cur.fetchall()]
    check("unpaid_predicate_matches_live_arm", rows == [eid], rows)
    fp0 = q1(cur, "SELECT v13_goal_fingerprint(%s)", (sid,))
    n_fail0 = n_events(cur, sid, "resolve/failed")
    spent0 = n_events(cur, sid, "turn/material_spent")
    conn.commit()
    conn2 = connect(server)
    try:
        cur2 = conn2.cursor()
        cur2.execute(
            "SELECT v13_harness_settle(%s::uuid, %s::uuid, %s::uuid, %s::jsonb)",
            (None, sid, eid, json.dumps(snap)))
        word = cur2.fetchone()[0]
        conn2.commit()
        n_fail1 = n_events(cur, sid, "resolve/failed")
        fp1 = q1(cur, "SELECT v13_goal_fingerprint(%s)", (sid,))
        spent1 = n_events(cur, sid, "turn/material_spent")
        source = q1(
            cur,
            "SELECT count(*) FROM events WHERE session_id=%s AND type='turn/material_spent' "
            "AND payload->>'effect_id'=%s",
            (sid, eid))
        check(
            "stop_before_settle_no_resolve_failed",
            n_fail1 == n_fail0 and fp1 == fp0
            and spent1 == spent0 + 1 and int(source) == 1,
            (word, n_fail0, n_fail1, fp0, fp1, spent1, source))
    finally:
        conn2.close()


def test_hold_lease(cur, sid):
    writer(cur, sid, plan_body([todo(u())], max_seq(cur, sid)))
    before_ev = n_events(cur)
    before_ef = n_effects(cur)
    holds = q1(cur, "SELECT count(*) FROM v13_goal_ambiguous_hold(%s)", (sid,))
    check("ambiguous_hold_zero_write", int(holds) == 0 and n_events(cur) == before_ev)
    row = opened(cur, sid, "read_only", request("ls", ["dir"], {"path": "dir"}))
    cur.execute("SELECT effect_id::text, tool_name FROM v13_goal_ambiguous_hold(%s)", (sid,))
    got = cur.fetchall()
    st = q1(cur, "SELECT status FROM effects WHERE effect_id=%s", (row["effect_id"],))
    check(
        "ambiguous_stays_claimed",
        st == "claimed" and len(got) == 1 and got[0][0] == row["effect_id"]
        and got[0][1] == "ls",
        (st, got))
    check("ambiguous_hold_zero_write", n_events(cur) == before_ev)
    inf = q1(
        cur, "SELECT v13_goal_lease_once(%s::uuid, %s::uuid, %s::uuid)",
        (None, sid, row["effect_id"]))
    until = q1(cur, "SELECT lease_until FROM effects WHERE effect_id=%s", (row["effect_id"],))
    check("lease_infinity_unchanged", inf == "infinite_unchanged" and until is not None)

    cur.execute(
        "UPDATE effects SET status='succeeded' WHERE effect_id=%s", (row["effect_id"],))
    tool = enqueue(cur, sid, "tool", harness_req(cur, sid), "harness_turn")
    cur.execute(
        "UPDATE effects SET status='claimed', attempt_no=1, fence=1, "
        "lease_owner='worker', lease_until=clock_timestamp() + interval '5 seconds' "
        "WHERE effect_id=%s RETURNING attempt_no, lease_until",
        (tool,))
    attempt, old_until = cur.fetchone()
    word = q1(
        cur, "SELECT v13_goal_lease_once(%s::uuid, %s::uuid, %s::uuid)",
        (None, sid, tool))
    new_until, new_attempt = q1(
        cur,
        "SELECT lease_until FROM effects WHERE effect_id=%s", (tool,)), q1(
        cur, "SELECT attempt_no FROM effects WHERE effect_id=%s", (tool,))
    check("lease_once_extends_finite", word == "extended" and new_until > old_until, word)
    check("lease_once_does_not_bump_attempt", int(new_attempt) == int(attempt), new_attempt)
    fails(
        cur, "SELECT v13_goal_lease_once(%s::uuid, %s::uuid, %s::uuid)",
        (sid, sid, tool),
        "v13: goal lease: auth", "lease_auth_rejected")
    cur.execute(
        "UPDATE effects SET lease_until=NULL WHERE effect_id=%s", (tool,))
    null_w = q1(
        cur, "SELECT v13_goal_lease_once(%s::uuid, %s::uuid, %s::uuid)",
        (None, sid, tool))
    check("lease_infinity_unchanged", null_w == "infinite_unchanged", null_w)

    cur.execute(
        "UPDATE effects SET lease_until='infinity'::timestamptz WHERE effect_id=%s", (tool,))
    inf_attempt = q1(cur, "SELECT attempt_no FROM effects WHERE effect_id=%s", (tool,))
    inf_tool = q1(
        cur,
        "SELECT v13_goal_lease_once(%s::uuid, %s::uuid, %s::uuid)",
        (None, sid, tool))
    check(
        "lease_infinity_unchanged",
        inf_tool == "infinite_unchanged"
        and q1(cur, "SELECT attempt_no FROM effects WHERE effect_id=%s", (tool,)) == inf_attempt)

    before_lstop_ev = n_events(cur)
    cur.execute("SAVEPOINT lstop")
    cur.execute(
        "UPDATE effects SET status='succeeded' WHERE effect_id=%s", (tool,))
    q1(cur, "SELECT v13_goal_stop(%s, %s)", (sid, "lease"))
    fails(
        cur, "SELECT v13_goal_lease_once(%s::uuid, %s::uuid, %s::uuid)",
        (None, sid, tool),
        "v13: goal lease: stopped", "lease_stopped_refused")
    cur.execute("ROLLBACK TO SAVEPOINT lstop")
    check(
        "ambiguous_hold_zero_write",
        n_events(cur) == before_lstop_ev
        and q1(cur, "SELECT status FROM effects WHERE effect_id=%s", (tool,)) == "claimed")


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
        test_static(cur, before_hashes)
        sid = open_root(cur)
        prefix(cur, sid)
        isolated(cur, lambda: test_waiting_and_explore(cur, sid))
        isolated(cur, lambda: test_offer_payload(cur, sid))
        isolated(cur, lambda: test_offer_auth_stop_terminal(cur, sid))
        isolated(cur, lambda: test_observe(cur, sid))
        isolated(cur, lambda: test_notify(cur, sid))
        isolated(cur, lambda: test_evidence(cur, sid))
        isolated(cur, lambda: test_hold_lease(cur, sid))
        conn.commit()
        test_offer_isolation(server, sid)
        test_offer_race(server, sid)
        test_settle_snap_binding(cur, sid)
        test_multiple_unpaid_selector(cur, sid)
        test_unpaid_settle(cur, sid, server, conn)
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
