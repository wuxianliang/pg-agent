"""Stage 27 gate: quota window, capabilities, material time honesty.

Run: uv run python v13/quota_window/test_quota_window.py  (exit 0 = pass)
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
from v13.load import STAGE_THROUGH
from v13.quota_window.setup_db import DB, PRE, main as setup_db

N = 0
VER = 10
SEED_GATES = [
    {"id": "human_pending", "effect": "block"},
    {"id": "unknown_wall", "effect": "block"},
    {"id": "unconsumed_cancel", "effect": "block"},
    {"id": "duty_cycle", "effect": "shadow"},
]
V2_GATES = SEED_GATES + [
    {"id": "quota_window", "effect": "block"},
    {"id": "capabilities", "effect": "block"},
]
QUOTA_SEED = {
    "schema_version": 1,
    "window_hours": 8760,
    "slot_minutes": 0,
    "allowed": 1000000,
}
CAP_SEED = {"schema_version": 1, "required": []}
FINISH = {"result_kind": "finish", "delivery_kind": "LOUD-BUT-BLIND"}
TIME_EXPR = "NEW.at >= v_wall - interval '60 seconds' AND NEW.at <= v_txn"


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


def next_ver():
    global VER
    VER += 1
    return VER


def connect(server, db=DB):
    conn = psycopg2.connect(server.get_uri(db))
    conn.autocommit = False
    return conn


def q1(cur, sql, params=None):
    cur.execute(sql, params)
    row = cur.fetchone()
    return None if row is None else row[0]


def qall(cur, sql, params=None):
    cur.execute(sql, params)
    return cur.fetchall()


def fails_with(cur, sql, params, needle, label, exact=False):
    cur.execute("SAVEPOINT sp")
    try:
        cur.execute(sql, params)
    except psycopg2.Error as exc:
        msg = exc.diag.message_primary or str(exc).splitlines()[0]
        ok = msg == needle if exact else needle in msg
        check(label, ok, msg)
        cur.execute("ROLLBACK TO SAVEPOINT sp")
        return msg
    cur.execute("ROLLBACK TO SAVEPOINT sp")
    raise AssertionError(f"{label}: expected failure")


def open_session(cur, spec=None):
    return str(q1(cur, "SELECT v13_open_session(%s::jsonb)", (json.dumps(spec or {}),)))


def prefix(cur, sid, text="hello goal"):
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (sid, u(), json.dumps({"text": text})))


def snap_of(cur, sid, remaining=0, failed=False):
    cur.execute("SELECT v13_probe(%s)", (sid,))
    probe = cur.fetchone()[0]
    probe["sid"] = sid
    return {"snap": probe, "envelope": {"sid": sid}, "remaining": remaining,
            "failed": failed, "abandon": False}


def advance(cur, sid, failed=False, role=None):
    cur.execute("RESET ROLE")
    cur.execute(
        "UPDATE sessions SET context_active_revision = v13_context_required(session_id) "
        "WHERE session_id=%s", (sid,))
    snap = snap_of(cur, sid, failed=failed)
    if role:
        cur.execute(f"SET ROLE {role}")
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid, json.dumps(snap)))
    word = cur.fetchone()[0]
    if role:
        cur.execute("RESET ROLE")
    return word


def n_events(cur, sid, etype):
    return int(q1(
        cur, "SELECT count(*) FROM events WHERE session_id=%s AND type=%s", (sid, etype)))


def n_effects(cur, sid):
    return int(q1(cur, "SELECT count(*) FROM effects WHERE session_id=%s", (sid,)))


def n_effects_all(cur):
    return int(q1(cur, "SELECT count(*) FROM effects"))


def n_decisions(cur):
    return int(q1(cur, "SELECT count(*) FROM decisions"))


def status_of(cur, sid):
    return q1(cur, "SELECT status FROM sessions WHERE session_id=%s", (sid,))


def ready_claimed(cur, sid):
    return int(q1(
        cur,
        "SELECT count(*) FROM effects WHERE session_id=%s AND status IN ('ready','claimed')",
        (sid,)))


def flip_policy(cur, name, version, value):
    cur.execute(
        "INSERT INTO v13_policies (name, version, value, active) "
        "VALUES (%s, %s, %s::jsonb, false)",
        (name, version, json.dumps(value)))
    cur.execute(
        "UPDATE v13_policies SET active=false WHERE name=%s AND version<>%s",
        (name, version))
    cur.execute(
        "UPDATE v13_policies SET active=true WHERE name=%s AND version=%s",
        (name, version))


def prosrc(cur, sig):
    return q1(cur, "SELECT prosrc FROM pg_proc WHERE oid = %s::regprocedure", (sig,))


def trev(cur, sid):
    return int(q1(cur, "SELECT (v13_probe(%s)->>'tools_revision')::bigint", (sid,)))


def harness_request(ltid, index, revision):
    return {
        "tool": "harness_turn",
        "params": {},
        "handler": "worker:harness_turn",
        "tools_revision": revision,
        "logical_turn_id": ltid,
        "continuation_index": index,
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
        "WHERE effect_id=%s RETURNING attempt_no, fence", (eid,))
    attempt, fence = cur.fetchone()
    cur.execute(
        "SELECT v13_complete(%s, %s, %s, 'succeeded', %s::jsonb)",
        (eid, attempt, fence, json.dumps(result)))
    return cur.fetchone()[0]


def gate(cur, sid):
    return q1(cur, "SELECT v13_should_run_gate(%s)", (sid,))


def eligible(cur, sid):
    return q1(cur, "SELECT v13_quota_eligible(%s)", (sid,))


def missing(cur, sid):
    cur.execute("SELECT name FROM v13_missing_capabilities(%s) ORDER BY name", (sid,))
    return [row[0] for row in cur.fetchall()]


def quota_of(**over):
    val = dict(QUOTA_SEED)
    val.update(over)
    return val


def fresh_pair(cur):
    sid = open_session(cur)
    prefix(cur, sid)
    return sid


def harness_effect(cur, sid, result=None):
    eid = enqueue(cur, sid, "tool", harness_request(u(), 0, trev(cur, sid)), "harness_turn")
    settle(cur, eid, result or FINISH)
    return eid


def alloc_seq(cur, sid):
    cur.execute(
        "UPDATE sessions SET next_seq = next_seq + 1 WHERE session_id=%s "
        "RETURNING next_seq - 1, turn_no",
        (sid,))
    return cur.fetchone()


def insert_material(cur, sid, eid, at_expr=None):
    seq, turn = alloc_seq(cur, sid)
    payload = json.dumps({"effect_id": eid, "schema_version": 1})
    if at_expr is None:
        cur.execute(
            """
            INSERT INTO events (
              session_id, seq, event_id, type, turn_no, payload, payload_hash, source_effect_id)
            SELECT %s, %s, gen_random_uuid(), 'turn/material_spent', %s, p.payload,
                   encode(digest(p.payload::text, 'sha256'), 'hex'), %s
              FROM (SELECT %s::jsonb AS payload) p
            """,
            (sid, seq, turn, eid, payload))
    else:
        cur.execute(
            f"""
            INSERT INTO events (
              session_id, seq, event_id, type, turn_no, payload, payload_hash,
              source_effect_id, at)
            SELECT %s, %s, gen_random_uuid(), 'turn/material_spent', %s, p.payload,
                   encode(digest(p.payload::text, 'sha256'), 'hex'), %s, {at_expr}
              FROM (SELECT %s::jsonb AS payload) p
            """,
            (sid, seq, turn, eid, payload))
    return seq


def super_receipt(cur, sid, at_expr):
    eid = harness_effect(cur, sid)
    insert_material(cur, sid, eid, at_expr)
    stayed = int(q1(
        cur,
        "SELECT count(*) FROM events WHERE session_id=%s AND type='turn/material_spent' "
        "AND source_effect_id=%s",
        (sid, eid)))
    check("superuser receipt stayed", stayed == 1, stayed)
    return eid


def test_seed_shape(cur):
    quota = q1(cur, "SELECT value FROM v13_policies WHERE name='quota_window' AND active")
    caps = q1(cur, "SELECT value FROM v13_policies WHERE name='capabilities' AND active")
    should = q1(cur, "SELECT value FROM v13_policies WHERE name='should_run' AND active")
    check("quota seed", quota == QUOTA_SEED, quota)
    check("quota four keys",
          q1(cur, "SELECT v13_json_keys(value) FROM v13_policies WHERE name='quota_window' AND active")
          == ["allowed", "schema_version", "slot_minutes", "window_hours"])
    check("capabilities empty required", caps == CAP_SEED, caps)
    check("should_run first four", should["gates"][:4] == SEED_GATES, should["gates"][:4])
    check("should_run tail blocks", should["gates"][-2:] == V2_GATES[-2:], should["gates"][-2:])
    check("should_run six gates", should["gates"] == V2_GATES, should["gates"])


def test_eligible_zero_receipts(cur):
    sid = fresh_pair(cur)
    check("zero receipts eligible", eligible(cur, sid) is True)


def test_allowed_zero(cur):
    cur.execute("SAVEPOINT allowed0")
    sid = fresh_pair(cur)
    before = n_events(cur, sid, "user/message")
    flip_policy(cur, "quota_window", next_ver(), quota_of(allowed=0))
    check("allowed 0 false", eligible(cur, sid) is False)
    check("allowed 0 no new events", n_events(cur, sid, "user/message") == before)
    cur.execute("ROLLBACK TO SAVEPOINT allowed0")
    sid = fresh_pair(cur)
    check("rollback restores eligible", eligible(cur, sid) is True)


def test_count_uses_events_at(cur):
    cur.execute("SAVEPOINT slide")
    sid = fresh_pair(cur)
    super_receipt(cur, sid, "transaction_timestamp() - interval '30 hours'")
    at_before = q1(
        cur, "SELECT at FROM events WHERE session_id=%s AND type='turn/material_spent'", (sid,))
    flip_policy(cur, "quota_window", next_ver(), quota_of(window_hours=48, allowed=1))
    check("48h window counts 30h receipt", eligible(cur, sid) is False)
    flip_policy(cur, "quota_window", next_ver(), quota_of(window_hours=24, allowed=1))
    check("24h window slides receipt out", eligible(cur, sid) is True)
    at_after = q1(
        cur, "SELECT at FROM events WHERE session_id=%s AND type='turn/material_spent'", (sid,))
    check("slide does not rewrite at", at_after == at_before)
    other = fresh_pair(cur)
    super_receipt(cur, other, "transaction_timestamp()")
    super_receipt(cur, other, "transaction_timestamp()")
    flip_policy(cur, "quota_window", next_ver(), quota_of(window_hours=48, allowed=2))
    check("two in-window receipts at allowed=2", eligible(cur, other) is False)
    check("count is two", n_events(cur, other, "turn/material_spent") == 2)
    cur.execute("ROLLBACK TO SAVEPOINT slide")


def test_slot_spacing(cur):
    cur.execute("SAVEPOINT slot")
    sid = fresh_pair(cur)
    eid = harness_effect(cur, sid)
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'turn/material_spent', %s::jsonb, %s)",
        (sid, u(), json.dumps({"schema_version": 1, "effect_id": eid}), eid))
    check("just-written receipt stored", n_events(cur, sid, "turn/material_spent") == 1)
    flip_policy(cur, "quota_window", next_ver(), quota_of(slot_minutes=60, allowed=1000000))
    check("slot 60 blocks fresh receipt", eligible(cur, sid) is False)
    flip_policy(cur, "quota_window", next_ver(), quota_of(slot_minutes=0, allowed=1000000))
    check("slot 0 ignores spacing", eligible(cur, sid) is True)
    bound = fresh_pair(cur)
    super_receipt(cur, bound, "transaction_timestamp() - interval '60 minutes'")
    hit = q1(
        cur,
        "SELECT at = transaction_timestamp() - interval '60 minutes' "
        "FROM events WHERE session_id=%s AND type='turn/material_spent'",
        (bound,))
    check("lower bound at stored", hit is True, hit)
    flip_policy(cur, "quota_window", next_ver(), quota_of(slot_minutes=60, allowed=1000000))
    check("closed slot lower bound blocks", eligible(cur, bound) is False)
    cur.execute("ROLLBACK TO SAVEPOINT slot")


def test_slot_longer_than_window_rejected(cur):
    cur.execute("SAVEPOINT slotlong")
    sid = fresh_pair(cur)
    before = int(q1(cur, "SELECT count(*) FROM events"))
    flip_policy(cur, "quota_window", next_ver(), quota_of(window_hours=1, slot_minutes=61, allowed=1))
    fails_with(cur, "SELECT v13_quota_eligible(%s)", (sid,), "v13: quota policy",
               "slot longer than window", exact=True)
    check("slot policy writes no events", int(q1(cur, "SELECT count(*) FROM events")) == before)
    cur.execute("ROLLBACK TO SAVEPOINT slotlong")


def test_json_one_point_zero(cur):
    cur.execute("SAVEPOINT json10")
    sid = fresh_pair(cur)
    flip_policy(cur, "quota_window", next_ver(), quota_of(window_hours=1.0))
    fails_with(cur, "SELECT v13_quota_eligible(%s)", (sid,), "v13: quota policy",
               "json 1.0 rejected", exact=True)
    cur.execute("ROLLBACK TO SAVEPOINT json10")


def test_other_session_not_counted(cur):
    cur.execute("SAVEPOINT other")
    a = fresh_pair(cur)
    b = fresh_pair(cur)
    flip_policy(cur, "quota_window", next_ver(), quota_of(allowed=1))
    check("A true before B receipt", eligible(cur, a) is True)
    super_receipt(cur, b, "transaction_timestamp()")
    check("A unchanged by B receipt", eligible(cur, a) is True)
    check("B counts own receipt", eligible(cur, b) is False)
    cur.execute("ROLLBACK TO SAVEPOINT other")


def test_no_tree_rollup(cur):
    cur.execute("SAVEPOINT tree")
    parent = fresh_pair(cur)
    child = str(q1(cur, "SELECT v13_fork(%s, 0, 'fresh_fork', NULL)", (parent,)))
    prefix(cur, child, "child goal")
    for _ in range(3):
        super_receipt(cur, child, "transaction_timestamp()")
    check("child has three receipts", n_events(cur, child, "turn/material_spent") == 3)
    check("parent loose seed still true", eligible(cur, parent) is True)
    flip_policy(cur, "quota_window", next_ver(), quota_of(allowed=1))
    check("parent ignores child receipts", eligible(cur, parent) is True)
    check("child counts own receipts", eligible(cur, child) is False)
    cur.execute("ROLLBACK TO SAVEPOINT tree")


def test_missing_policy(cur):
    cur.execute("SAVEPOINT misspol")
    sid = fresh_pair(cur)
    before = int(q1(cur, "SELECT count(*) FROM events"))
    cur.execute("UPDATE v13_policies SET active=false WHERE name='quota_window' AND active")
    fails_with(cur, "SELECT v13_quota_eligible(%s)", (sid,), "v13: quota policy",
               "missing quota policy", exact=True)
    check("missing quota writes nothing", int(q1(cur, "SELECT count(*) FROM events")) == before)
    cur.execute(
        "UPDATE v13_policies SET active=true WHERE name='quota_window' AND version=1")
    cur.execute("UPDATE v13_policies SET active=false WHERE name='capabilities' AND active")
    fails_with(cur, "SELECT name FROM v13_missing_capabilities(%s)", (sid,),
               "v13: capabilities policy", "missing capabilities policy", exact=True)
    check("missing capabilities writes nothing", int(q1(cur, "SELECT count(*) FROM events")) == before)
    cur.execute("ROLLBACK TO SAVEPOINT misspol")


def test_capabilities_policy_shape(cur):
    cur.execute("SAVEPOINT capshape")
    sid = fresh_pair(cur)
    cases = (
        ("extra key", {"schema_version": 1, "required": [], "extra": 1}),
        ("schema_version 2", {"schema_version": 2, "required": []}),
        ("required string", {"schema_version": 1, "required": "session_stats"}),
        ("required object", {"schema_version": 1, "required": {"name": "session_stats"}}),
        ("element not string", {"schema_version": 1, "required": [1]}),
        ("empty element", {"schema_version": 1, "required": [""]}),
        ("double colon", {"schema_version": 1, "required": ["a::b"]}),
    )
    for label, value in cases:
        before = int(q1(cur, "SELECT count(*) FROM events"))
        flip_policy(cur, "capabilities", next_ver(), value)
        fails_with(cur, "SELECT name FROM v13_missing_capabilities(%s)", (sid,),
                   "v13: capabilities policy", label, exact=True)
        check(f"{label} zero writes", int(q1(cur, "SELECT count(*) FROM events")) == before)
    cur.execute("ROLLBACK TO SAVEPOINT capshape")


def test_capabilities_empty_required(cur):
    sid = fresh_pair(cur)
    check("empty required zero rows", missing(cur, sid) == [])


def test_capabilities_difference(cur):
    cur.execute("SAVEPOINT capdiff")
    sid = fresh_pair(cur)
    enabled = q1(cur, "SELECT enabled FROM tools WHERE name='spawn_subsession'")
    check("spawn_subsession enabled", enabled is True, enabled)
    flip_policy(cur, "capabilities", next_ver(), {
        "schema_version": 1,
        "required": ["spawn_subsession", "no_such_tool", "session_stats"],
    })
    got = missing(cur, sid)
    check("difference is only missing name", got == ["no_such_tool"], got)
    check("enabled tool not returned", "spawn_subsession" not in got and "session_stats" not in got)
    cur.execute("ROLLBACK TO SAVEPOINT capdiff")


def test_capabilities_duplicate_rejected(cur):
    cur.execute("SAVEPOINT capdup")
    sid = fresh_pair(cur)
    flip_policy(cur, "capabilities", next_ver(), {
        "schema_version": 1, "required": ["session_stats", "session_stats"],
    })
    fails_with(cur, "SELECT name FROM v13_missing_capabilities(%s)", (sid,),
               "v13: capabilities policy", "duplicate required", exact=True)
    cur.execute("ROLLBACK TO SAVEPOINT capdup")


def test_human_reward_does_not_mutate(cur):
    cur.execute("SAVEPOINT reward")
    sid = fresh_pair(cur)
    flip_policy(cur, "capabilities", next_ver(), {
        "schema_version": 1, "required": ["human_reward"],
    })
    effects = n_effects_all(cur)
    decisions = n_decisions(cur)
    got = missing(cur, sid)
    check("human_reward missing", got == ["human_reward"], got)
    check("effects unchanged", n_effects_all(cur) == effects)
    check("decisions unchanged", n_decisions(cur) == decisions)
    for sig in ("v13_quota_eligible(uuid)", "v13_missing_capabilities(uuid)",
                "v13_material_time_honest()"):
        check(f"{sig} lacks human_reward", "human_reward" not in prosrc(cur, sig))
    seed = q1(cur, "SELECT value::text FROM v13_policies WHERE name='capabilities' AND version=1")
    quota = q1(cur, "SELECT value::text FROM v13_policies WHERE name='quota_window' AND version=1")
    check("seed lacks human_reward", "human_reward" not in seed and "human_reward" not in quota)
    cur.execute("ROLLBACK TO SAVEPOINT reward")


def test_shadow_falls_through(cur):
    cur.execute("SAVEPOINT shadow")
    sid = fresh_pair(cur)
    flip_policy(cur, "triage", next_ver(), {"duty_cycle": 0})
    flip_policy(cur, "quota_window", next_ver(), quota_of(allowed=0))
    check("shadow duty falls through to quota", gate(cur, sid) == "quota_window", gate(cur, sid))
    cur.execute("ROLLBACK TO SAVEPOINT shadow")


def test_quota_blocks_route_enqueue(cur):
    cur.execute("SAVEPOINT routeq")
    sid = fresh_pair(cur)
    decide = q1(cur, "SELECT v13_triage_decide(v13_triage_project(%s))", (sid,))
    check("route fixture decide none", decide == "none", decide)
    check("route fixture no predecessor",
          q1(cur, "SELECT v13_harness_predecessor(%s)", (sid,)) is None)
    check("route fixture no ready", ready_claimed(cur, sid) == 0)
    loose_effects = n_effects(cur, sid)
    word = advance(cur, sid)
    check("loose route enqueues", n_effects(cur, sid) > loose_effects, word)
    cur.execute("ROLLBACK TO SAVEPOINT routeq")
    sid = fresh_pair(cur)
    effects = n_effects(cur, sid)
    routes = n_events(cur, sid, "turn/route")
    flip_policy(cur, "quota_window", next_ver(), quota_of(allowed=0))
    word = advance(cur, sid, role="v13_route")
    check("quota blocks route enqueue", word == "waiting", word)
    check("route block zero new effects", n_effects(cur, sid) == effects)
    check("route block no turn/route", n_events(cur, sid, "turn/route") == routes)
    cur.execute("ROLLBACK TO SAVEPOINT routeq")


def build_fold_cap(cur, signal):
    sid = fresh_pair(cur)
    eid = harness_effect(cur, sid, {"result_kind": "progress", "signals": [signal]})
    prefix(cur, sid, "next turn")
    return sid, eid


def test_quota_blocks_repair_replan_enqueue(cur):
    cur.execute("SAVEPOINT caps")
    for signal, reason in (("repair/required", "repair_cap"), ("replan/required", "replan_cap")):
        cur.execute("SAVEPOINT one_cap")
        sid, _eid = build_fold_cap(cur, signal)
        pred = q1(cur, "SELECT v13_harness_predecessor(%s)", (sid,))
        decide = q1(cur, "SELECT v13_triage_decide(v13_triage_project(%s))", (sid,))
        check(f"{reason} predecessor detached", pred is None, pred)
        check(f"{reason} decide none", decide == "none", decide)
        before = n_effects(cur, sid)
        word = advance(cur, sid)
        check(f"{reason} loose enqueues", n_effects(cur, sid) == before + 1, word)
        got = q1(
            cur,
            "SELECT request FROM effects WHERE session_id=%s AND kind='human' "
            "ORDER BY created_at DESC LIMIT 1",
            (sid,))
        check(f"{reason} human request", got == {"reason": reason}, got)
        cur.execute("ROLLBACK TO SAVEPOINT one_cap")
        sid, _eid = build_fold_cap(cur, signal)
        effects = n_effects(cur, sid)
        holds = n_events(cur, sid, "triage/hold")
        flip_policy(cur, "quota_window", next_ver(), quota_of(allowed=0))
        word = advance(cur, sid, role="v13_route")
        check(f"{reason} blocked waiting", word == "waiting", word)
        check(f"{reason} zero new effects", n_effects(cur, sid) == effects)
        check(f"{reason} no hold", n_events(cur, sid, "triage/hold") == holds)
        cur.execute("ROLLBACK TO SAVEPOINT one_cap")
    cur.execute("ROLLBACK TO SAVEPOINT caps")


def test_unknown_session(cur):
    missing_sid = u()
    fails_with(cur, "SELECT v13_quota_eligible(%s)", (missing_sid,),
               f"v13: unknown session {missing_sid}", "quota unknown session", exact=True)
    fails_with(cur, "SELECT name FROM v13_missing_capabilities(%s)", (missing_sid,),
               f"v13: unknown session {missing_sid}", "capabilities unknown session", exact=True)


def test_quota_blocks_prework_enqueue(cur):
    cur.execute("SAVEPOINT prework")
    sid = fresh_pair(cur)
    cur.execute(
        "SELECT v13_submit_override(%s, %s::jsonb)",
        (sid, json.dumps({
            "schema_version": 1,
            "intent": "decompose",
            "reason": "split",
            "source_principal": "user",
        })))
    cur.execute("SAVEPOINT blocked")
    effects = n_effects(cur, sid)
    routes = n_events(cur, sid, "turn/route")
    holds = n_events(cur, sid, "triage/hold")
    flip_policy(cur, "quota_window", next_ver(), quota_of(allowed=0))
    word = advance(cur, sid, role="v13_route")
    check("prework block waiting", word == "waiting", word)
    check("prework block zero effects", n_effects(cur, sid) == effects)
    check("prework block no turn/route", n_events(cur, sid, "turn/route") == routes)
    check("prework block no hold", n_events(cur, sid, "triage/hold") == holds)
    check("prework duty not zero", int(q1(cur, "SELECT v13_triage_duty()")) != 0)
    cur.execute("ROLLBACK TO SAVEPOINT blocked")
    before = n_effects(cur, sid)
    word = advance(cur, sid)
    check("prework rollback enqueues", n_effects(cur, sid) > before, word)
    cur.execute("ROLLBACK TO SAVEPOINT prework")


def test_quota_does_not_block_finish(cur):
    cur.execute("SAVEPOINT finish")
    sid = fresh_pair(cur)
    harness_effect(cur, sid)
    flip_policy(cur, "quota_window", next_ver(), quota_of(allowed=0))
    check("finish no ready", ready_claimed(cur, sid) == 0)
    word = advance(cur, sid)
    check("finish still terminal", word == "terminal", word)
    check("finish completed", status_of(cur, sid) == "completed")
    cur.execute("ROLLBACK TO SAVEPOINT finish")


def test_quota_sees_receipt_same_advance(cur):
    cur.execute("SAVEPOINT sameadv")
    sid = fresh_pair(cur)
    harness_effect(cur, sid, {"result_kind": "progress"})
    flip_policy(cur, "quota_window", next_ver(), quota_of(allowed=1, slot_minutes=0))
    check("eligible before material write", eligible(cur, sid) is True)
    effects = n_effects(cur, sid)
    routes = n_events(cur, sid, "turn/route")
    word = advance(cur, sid)
    check("same advance wrote material", n_events(cur, sid, "turn/material_spent") == 1)
    check("same advance did not enqueue", n_effects(cur, sid) == effects, word)
    check("same advance no route", n_events(cur, sid, "turn/route") == routes)
    check("eligible after material write", eligible(cur, sid) is False)
    adv = prosrc(cur, "v13_advance(uuid,jsonb)")
    gate_src = prosrc(cur, "v13_should_run_gate(uuid)")
    check("advance still calls should_run", adv.count("v13_should_run(") == 4)
    check("gate calls quota live", "v13_quota_eligible(p_sid)" in gate_src)
    check("advance does not cache quota", "v13_quota_eligible" not in adv)
    cur.execute("ROLLBACK TO SAVEPOINT sameadv")


def test_order_data_not_body(cur):
    cur.execute("SAVEPOINT gate_order")
    sid = fresh_pair(cur)
    oid_before = q1(cur, "SELECT oid FROM pg_proc WHERE oid = 'v13_should_run_gate(uuid)'::regprocedure")
    flip_policy(cur, "quota_window", next_ver(), quota_of(allowed=0))
    flip_policy(cur, "capabilities", next_ver(), {
        "schema_version": 1, "required": ["no_such_tool"],
    })
    check("default order quota wins", gate(cur, sid) == "quota_window", gate(cur, sid))
    swapped = {
        "schema_version": 1,
        "gates": SEED_GATES + [
            {"id": "capabilities", "effect": "block"},
            {"id": "quota_window", "effect": "block"},
        ],
    }
    flip_policy(cur, "should_run", next_ver(), swapped)
    check("swapped order capabilities wins", gate(cur, sid) == "capabilities", gate(cur, sid))
    oid_after = q1(cur, "SELECT oid FROM pg_proc WHERE oid = 'v13_should_run_gate(uuid)'::regprocedure")
    check("gate oid unchanged", oid_before == oid_after, (oid_before, oid_after))
    cur.execute("ROLLBACK TO SAVEPOINT gate_order")


def test_index(cur):
    defn = q1(cur, "SELECT pg_get_indexdef('ix_events_material_spent_at'::regclass)")
    check("index names material", "turn/material_spent" in defn, defn)
    check("index names session_id", "session_id" in defn, defn)
    check("index names at", "(session_id, at)" in defn, defn)
    unique = q1(
        cur, "SELECT indisunique FROM pg_index WHERE indexrelid = 'ix_events_material_spent_at'::regclass")
    check("index non-unique", unique is False, unique)
    sql = (ROOT / "v13_quota_window.sql").read_text()
    for banned in ("quota/spent", "quota/voided"):
        check(f"sql lacks {banned}", banned not in sql)
        for sig in ("v13_quota_eligible(uuid)", "v13_missing_capabilities(uuid)",
                    "v13_should_run_gate(uuid)", "v13_material_time_honest()"):
            check(f"{sig} lacks {banned}", banned not in prosrc(cur, sig))


def test_future_at_not_counted(cur):
    cur.execute("SAVEPOINT future")
    sid = fresh_pair(cur)
    super_receipt(cur, sid, "now() + interval '1 hour'")
    seq = int(q1(
        cur, "SELECT seq FROM events WHERE session_id=%s AND type='turn/material_spent'", (sid,)))
    next_after = int(q1(cur, "SELECT next_seq FROM sessions WHERE session_id=%s", (sid,)))
    check("future seq allocated", seq + 1 == next_after, (seq, next_after))
    future = q1(
        cur,
        "SELECT at > transaction_timestamp() FROM events "
        "WHERE session_id=%s AND type='turn/material_spent'",
        (sid,))
    check("future at stored", future is True, future)
    flip_policy(cur, "quota_window", next_ver(), quota_of(allowed=1, slot_minutes=60))
    check("future at not counted and not slotted", eligible(cur, sid) is True)
    cur.execute("ROLLBACK TO SAVEPOINT future")


def test_acl(cur):
    for role, expect in (
        ("v13_worker", False), ("public", False), ("v13_recall", False),
        ("v13_resolve", False), ("v13_spawn_owner", False), ("v13_route", True),
    ):
        for sig in ("v13_quota_eligible(uuid)", "v13_missing_capabilities(uuid)"):
            got = q1(cur, "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, sig))
            check(f"{sig} {role}", got is expect, got)
    honest = q1(
        cur, "SELECT has_function_privilege('v13_route', 'v13_material_time_honest()', 'EXECUTE')")
    check("route cannot execute time trigger", honest is False, honest)
    sid = fresh_pair(cur)
    cur.execute("SET ROLE v13_route")
    got = q1(cur, "SELECT v13_quota_eligible(%s)", (sid,))
    cur.execute("RESET ROLE")
    check("route quota call", got is True, got)


def prefix_clear(cur, sid):
    check("not blocked_unknown", status_of(cur, sid) != "blocked_unknown", status_of(cur, sid))
    check("no unknown effect",
          int(q1(cur, "SELECT count(*) FROM effects WHERE session_id=%s AND status='unknown'", (sid,))) == 0)
    check("no unconsumed cancel", q1(cur, "SELECT v13_unconsumed_cancel(%s)", (sid,)) is False)
    check("no ready/claimed", ready_claimed(cur, sid) == 0)
    check("duty not zero", int(q1(cur, "SELECT v13_triage_duty()")) != 0)


def test_resolve_failed_positive_arm(cur):
    cur.execute("SAVEPOINT pos")
    sid = fresh_pair(cur)
    prefix_clear(cur, sid)
    flip_policy(cur, "quota_window", next_ver(), quota_of(allowed=0))
    check("positive arm quota block id", gate(cur, sid) == "quota_window", gate(cur, sid))
    check("positive arm should_run false", q1(cur, "SELECT v13_should_run(%s)", (sid,)) is False)
    effects = n_effects(cur, sid)
    word = advance(cur, sid, failed=True, role="v13_route")
    check("positive arm waiting", word == "waiting", word)
    check("positive arm wrote resolve/failed", n_events(cur, sid, "resolve/failed") == 1)
    check("positive arm zero effects", n_effects(cur, sid) == effects)
    check("positive arm no hold", n_events(cur, sid, "triage/hold") == 0)
    last = q1(cur, "SELECT type FROM events WHERE session_id=%s ORDER BY seq DESC LIMIT 1", (sid,))
    check("resolve/failed is last event", last == "resolve/failed", last)
    cur.execute("ROLLBACK TO SAVEPOINT pos")
    sid = fresh_pair(cur)
    prefix_clear(cur, sid)
    flip_policy(cur, "capabilities", next_ver(), {
        "schema_version": 1, "required": ["no_such_tool"],
    })
    check("positive arm capability block id", gate(cur, sid) == "capabilities", gate(cur, sid))
    effects = n_effects(cur, sid)
    word = advance(cur, sid, failed=True, role="v13_route")
    check("capability arm waiting", word == "waiting", word)
    check("capability arm wrote resolve/failed", n_events(cur, sid, "resolve/failed") == 1)
    check("capability arm zero effects", n_effects(cur, sid) == effects)
    check("capability arm no hold", n_events(cur, sid, "triage/hold") == 0)
    cur.execute("ROLLBACK TO SAVEPOINT pos")
    sid = fresh_pair(cur)
    flip_policy(cur, "quota_window", next_ver(), quota_of(allowed=0))
    cur.execute("RESET ROLE")
    cur.execute(
        "UPDATE sessions SET context_active_revision = v13_context_required(session_id) "
        "WHERE session_id=%s", (sid,))
    snap = snap_of(cur, sid, failed=False)
    snap.pop("failed")
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid, json.dumps(snap)))
    word = cur.fetchone()[0]
    check("null failed does not prewrite", word == "waiting", word)
    check("null failed zero resolve/failed", n_events(cur, sid, "resolve/failed") == 0)
    adv = prosrc(cur, "v13_advance(uuid,jsonb)")
    call_at = adv.index("v_triage := v13_triage_prework(p_sid)")
    head = adv[:call_at]
    check("precheck still before prework", "resolve/failed" in head and "v13_should_run(" in head)
    cur.execute("ROLLBACK TO SAVEPOINT pos")


def test_source(cur):
    old_gate = (PRE / "gate.prosrc").read_text()
    new_gate = prosrc(cur, "v13_should_run_gate(uuid)")
    old_line = "OR v_id NOT IN ('human_pending', 'unknown_wall', 'unconsumed_cancel', 'duty_cycle')"
    new_line = ("OR v_id NOT IN ('human_pending', 'unknown_wall', 'unconsumed_cancel', "
                "'duty_cycle', 'quota_window', 'capabilities')")
    check("closed set line replaced", old_line in old_gate and old_line not in new_gate and new_line in new_gate)
    for needle in (
        "v_id = 'human_pending'",
        "v_id = 'unknown_wall'",
        "v_id = 'unconsumed_cancel'",
        "v_id = 'duty_cycle'",
    ):
        check(f"kept {needle}", needle in old_gate and needle in new_gate)
    check("quota branch added", "v_id = 'quota_window' AND NOT public.v13_quota_eligible(p_sid)" in new_gate)
    check("capabilities branch added", "v_id = 'capabilities' AND EXISTS (" in new_gate)
    for dest, sig in (
        ("advance.prosrc", "v13_advance(uuid,jsonb)"),
        ("prework.prosrc", "v13_triage_prework(uuid)"),
        ("wrap.prosrc", "v13_should_run(uuid)"),
    ):
        check(f"{sig} body unchanged", prosrc(cur, sig) == (PRE / dest).read_text())
        oid = q1(cur, "SELECT oid::text FROM pg_proc WHERE oid = %s::regprocedure", (sig,))
        check(f"{sig} oid unchanged", oid == (PRE / (dest + ".oid")).read_text().strip())
    gate_oid = q1(cur, "SELECT oid::text FROM pg_proc WHERE oid = 'v13_should_run_gate(uuid)'::regprocedure")
    check("replace kept gate oid", gate_oid == (PRE / "gate.prosrc.oid").read_text().strip())
    for sig, volatile in (
        ("v13_quota_eligible(uuid)", "s"),
        ("v13_missing_capabilities(uuid)", "s"),
        ("v13_material_time_honest()", "v"),
    ):
        cur.execute(
            "SELECT provolatile, prosecdef, proconfig::text FROM pg_proc WHERE oid = %s::regprocedure",
            (sig,))
        got_v, secdef, config = cur.fetchone()
        check(f"{sig} volatility", got_v == volatile and secdef is False, (got_v, secdef))
        check(f"{sig} search_path", "search_path=pg_catalog, public" in config, config)
    quota_src = prosrc(cur, "v13_quota_eligible(uuid)")
    check("single txn clock", quota_src.count("transaction_timestamp()") == 1)
    check("no wall clock in quota", "clock_timestamp()" not in quota_src and "now()" not in quota_src)
    for banned in ("INSERT", "UPDATE", "DELETE", "effects.created_at", "turn_no"):
        check(f"quota lacks {banned}", banned not in quota_src)
    check("capabilities no writes",
          all(word not in prosrc(cur, "v13_missing_capabilities(uuid)")
              for word in ("INSERT", "UPDATE", "DELETE")))
    honest = prosrc(cur, "v13_material_time_honest()")
    check("time expr executable", TIME_EXPR in honest and "--" not in honest)
    check("time clocks once",
          honest.count("v_wall :=") == 1 and honest.count("v_txn :=") == 1
          and honest.count("clock_timestamp()") == 1
          and honest.count("transaction_timestamp()") == 1)
    check("time trigger does not rewrite at", "NEW.at :=" not in honest)
    sql = (ROOT / "v13_quota_window.sql").read_text()
    for banned in ("CREATE TABLE", "CREATE VIEW", "MATERIALIZED", "ALTER TABLE",
                   "LISTEN", "pg_terminate_backend", "pg_sleep"):
        check(f"sql lacks {banned}", banned not in sql)
    cur.execute("SAVEPOINT badid")
    sid = fresh_pair(cur)
    bad = {
        "schema_version": 1,
        "gates": V2_GATES + [{"id": "not_a_gate", "effect": "block"}],
    }
    flip_policy(cur, "should_run", next_ver(), bad)
    fails_with(cur, "SELECT v13_should_run_gate(%s)", (sid,), "v13: should_run gate",
               "unknown id still raises", exact=True)
    cur.execute("ROLLBACK TO SAVEPOINT badid")


def test_regression_note(cur):
    check("quota_window registered 27", STAGE_THROUGH["quota_window"] == 27)
    check("should_run still 26", STAGE_THROUGH["should_run"] == 26)
    print("[note] regression 1-26 is run by the implementer, not this script")


def route_reject(server, at_expr, label, sleep_s=None):
    conn = connect(server)
    cur = conn.cursor()
    try:
        sid = fresh_pair(cur)
        eid = harness_effect(cur, sid)
        cur.execute("SAVEPOINT arm")
        cur.execute("SET ROLE v13_route")
        cur.execute("SET LOCAL statement_timeout = 0")
        if sleep_s:
            cur.execute("SELECT pg_sleep(%s)", (sleep_s,))
        try:
            insert_material(cur, sid, eid, at_expr)
        except psycopg2.Error as exc:
            msg = exc.diag.message_primary or ""
            cur.execute("ROLLBACK TO SAVEPOINT arm")
            cur.execute("RESET ROLE")
            left = n_events(cur, sid, "turn/material_spent")
            check(label, msg == "v13: material time", msg)
            check(f"{label} zero rows", left == 0, left)
            return
        cur.execute("RESET ROLE")
        raise AssertionError(f"{label}: expected v13: material time")
    finally:
        conn.rollback()
        conn.close()


def test_material_backfill_rejected(server):
    conn = connect(server)
    cur = conn.cursor()
    try:
        honest = prosrc(cur, "v13_material_time_honest()")
        check("backfill source expr", TIME_EXPR in honest)
        if_at = honest.index("IF NOT EXISTS")
        expr_at = honest.index(TIME_EXPR)
        then_at = honest.index("THEN", expr_at)
        check("expr inside the raising IF", if_at < expr_at < then_at)
    finally:
        conn.rollback()
        conn.close()
    route_reject(server, "transaction_timestamp() - interval '30 hours'", "route 30h")
    route_reject(server, "clock_timestamp() + interval '60 seconds'", "route clock+60s")
    conn = connect(server)
    cur = conn.cursor()
    try:
        sid = fresh_pair(cur)
        eid = harness_effect(cur, sid)
        cur.execute("SET ROLE v13_route")
        insert_material(cur, sid, eid, None)
        cur.execute("RESET ROLE")
        eq = q1(
            cur,
            "SELECT at = transaction_timestamp() FROM events "
            "WHERE session_id=%s AND type='turn/material_spent' AND source_effect_id=%s",
            (sid, eid))
        check("route omit at lands", eq is True, eq)
        check("route omit at one row", n_events(cur, sid, "turn/material_spent") == 1)
    finally:
        conn.rollback()
        conn.close()
    route_reject(server, "clock_timestamp() - interval '90 seconds'", "route clock-90s")
    route_reject(
        server, "transaction_timestamp() + interval '1 second'", "route txn seam", sleep_s=5)
    conn = connect(server)
    cur = conn.cursor()
    try:
        sid = fresh_pair(cur)
        super_receipt(cur, sid, "transaction_timestamp() - interval '30 hours'")
        same = q1(
            cur,
            "SELECT at = transaction_timestamp() - interval '30 hours' FROM events "
            "WHERE session_id=%s AND type='turn/material_spent'",
            (sid,))
        check("superuser 30h at unchanged", same is True, same)
    finally:
        conn.rollback()
        conn.close()
    route_reject(server, "transaction_timestamp()", "route long txn", sleep_s=61)


def main() -> int:
    global N
    setup_db()
    server = get_server()
    conn = connect(server)
    cur = conn.cursor()
    try:
        test_seed_shape(cur)
        test_eligible_zero_receipts(cur)
        test_allowed_zero(cur)
        test_count_uses_events_at(cur)
        test_slot_spacing(cur)
        test_slot_longer_than_window_rejected(cur)
        test_json_one_point_zero(cur)
        test_other_session_not_counted(cur)
        test_no_tree_rollup(cur)
        test_missing_policy(cur)
        test_capabilities_policy_shape(cur)
        test_capabilities_empty_required(cur)
        test_capabilities_difference(cur)
        test_capabilities_duplicate_rejected(cur)
        test_human_reward_does_not_mutate(cur)
        test_shadow_falls_through(cur)
        test_quota_blocks_route_enqueue(cur)
        test_quota_blocks_repair_replan_enqueue(cur)
        test_unknown_session(cur)
        test_quota_blocks_prework_enqueue(cur)
        test_quota_does_not_block_finish(cur)
        test_quota_sees_receipt_same_advance(cur)
        test_order_data_not_body(cur)
        test_index(cur)
        test_future_at_not_counted(cur)
        test_acl(cur)
        test_resolve_failed_positive_arm(cur)
        test_source(cur)
        test_regression_note(cur)
        conn.rollback()
    finally:
        conn.close()
    test_material_backfill_rejected(server)
    print(f"[quota_window] ALL PASS ({N})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
