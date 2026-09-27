"""Stage 29 gate: goal stop/resume and spawn-batch governance.

Run: uv run python v13/govern/test_govern.py  (exit 0 = pass)
"""
from __future__ import annotations

import difflib
import hashlib
import json
import sys
import threading
import time
import uuid
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v13.load import STAGE_THROUGH
from v13.govern.setup_db import DB, PRE, main as setup_db

N = 0
VER = 200
FINISH = {"result_kind": "finish", "delivery_kind": "LOUD-BUT-BLIND"}
PROGRESS = {"result_kind": "progress"}
CALL = [{"id": "tc1", "name": "spawn_subsession", "args": {"task": "one"}}]
CALLS2 = [
    {"id": "tc1", "name": "spawn_subsession", "args": {"task": "one"}},
    {"id": "tc2", "name": "spawn_subsession", "args": {"task": "two"}},
]
HEX_BAD = "ab" * 32


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


def expect_42501(cur, role, sql, params, label):
    cur.execute("SAVEPOINT sp_acl")
    cur.execute(f"SET ROLE {role}")
    try:
        cur.execute(sql, params)
    except psycopg2.Error as exc:
        check(label, exc.pgcode == "42501", exc.pgcode)
        cur.execute("ROLLBACK TO SAVEPOINT sp_acl")
        cur.execute("RESET ROLE")
        return
    cur.execute("ROLLBACK TO SAVEPOINT sp_acl")
    cur.execute("RESET ROLE")
    raise AssertionError(f"{label}: expected 42501")


def open_session(cur, spec=None):
    return str(q1(cur, "SELECT v13_open_session(%s::jsonb)", (json.dumps(spec or {}),)))


def prefix(cur, sid, text="hello goal"):
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (sid, u(), json.dumps({"text": text})))


def snap_of(cur, sid, remaining=0, failed=False, include_failed=True):
    cur.execute("SELECT v13_probe(%s)", (sid,))
    probe = cur.fetchone()[0]
    probe["sid"] = sid
    snap = {"snap": probe, "envelope": {"sid": sid}, "remaining": remaining,
            "abandon": False}
    if include_failed:
        snap["failed"] = failed
    return snap


def advance(cur, sid, failed=False, role=None, snap=None, include_failed=True):
    cur.execute("RESET ROLE")
    if snap is None:
        cur.execute(
            "UPDATE sessions SET context_active_revision = v13_context_required(session_id) "
            "WHERE session_id=%s", (sid,))
        snap = snap_of(cur, sid, failed=failed, include_failed=include_failed)
    if role:
        cur.execute(f"SET ROLE {role}")
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid, json.dumps(snap)))
    word = cur.fetchone()[0]
    if role:
        cur.execute("RESET ROLE")
    return word


def n_events(cur, sid=None, etype=None):
    if sid is None:
        return int(q1(cur, "SELECT count(*) FROM events"))
    if etype is None:
        return int(q1(cur, "SELECT count(*) FROM events WHERE session_id=%s", (sid,)))
    return int(q1(
        cur, "SELECT count(*) FROM events WHERE session_id=%s AND type=%s", (sid, etype)))


def n_effects(cur, sid):
    return int(q1(cur, "SELECT count(*) FROM effects WHERE session_id=%s", (sid,)))


def n_children(cur, sid):
    return int(q1(cur, "SELECT count(*) FROM sessions WHERE parent_session_id=%s", (sid,)))


def status_of(cur, sid):
    return q1(cur, "SELECT status FROM sessions WHERE session_id=%s", (sid,))


def next_seq(cur, sid):
    return int(q1(cur, "SELECT next_seq FROM sessions WHERE session_id=%s", (sid,)))


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


def project_calls(cur, sid, reason, calls):
    eid = enqueue(cur, sid, "llm", {"route": {"action": "llm", "reason": reason}})
    cur.execute(
        "UPDATE effects SET status='claimed', attempt_no=1, fence=1, lease_owner='w', "
        "lease_until=clock_timestamp()+interval '1 hour' WHERE effect_id=%s "
        "RETURNING attempt_no, fence", (eid,))
    attempt, fence = cur.fetchone()
    cur.execute(
        "SELECT v13_complete(%s, %s, %s, 'succeeded', %s::jsonb)",
        (eid, attempt, fence, json.dumps({"text": "ok", "tool_calls": calls})))
    cur.fetchone()
    return eid


def insert_one(cur, parent, status="ready", sid=None):
    cid = sid or u()
    cur.execute("SET ROLE v13_spawn_owner")
    cur.execute(
        "INSERT INTO sessions (session_id, status, parent_session_id, spawn_kind) "
        "VALUES (%s, %s, %s, 'fresh_fork')",
        (cid, status, parent))
    cur.execute("RESET ROLE")
    return cid


def stop(cur, sid, reason="pause"):
    cur.execute("SELECT v13_goal_stop(%s, %s)", (sid, reason))
    return cur.fetchone()[0]


def resume(cur, sid, reason="go"):
    cur.execute("SELECT v13_goal_resume(%s, %s)", (sid, reason))
    return cur.fetchone()[0]


def fingerprint(cur, sid):
    return q1(cur, "SELECT v13_goal_fingerprint(%s)", (sid,))


def state_hash(cur, sid):
    return q1(cur, "SELECT v13_state_hash(%s)", (sid,))


def lifecycle(cur, sid):
    return q1(cur, "SELECT v13_goal_lifecycle(%s)", (sid,))


def fresh(cur):
    sid = open_session(cur)
    prefix(cur, sid)
    return sid


def legal_goal_payload(cur, sid, reason="pause"):
    return {
        "schema_version": 1,
        "fingerprint": fingerprint(cur, sid),
        "reason": reason,
    }


def alloc_insert(cur, sid, etype, payload, source=None, seq=None, turn=None, advance=True):
    if advance:
        cur.execute(
            "UPDATE sessions SET next_seq = next_seq + 1 "
            "WHERE session_id=%s RETURNING next_seq - 1, turn_no",
            (sid,))
        got_seq, got_turn = cur.fetchone()
        seq = got_seq if seq is None else seq
        turn = got_turn if turn is None else turn
    cur.execute(
        "INSERT INTO events (session_id, seq, event_id, type, turn_no, payload, "
        "payload_hash, source_effect_id) VALUES (%s, %s, %s, %s, %s, %s::jsonb, "
        "encode(digest(%s::jsonb::text, 'sha256'), 'hex'), %s)",
        (sid, seq, u(), etype, turn, json.dumps(payload), json.dumps(payload), source))


def only_inserts(old, new, label):
    matcher = difflib.SequenceMatcher(
        a=old.splitlines(keepends=True), b=new.splitlines(keepends=True))
    bad = [tag for tag, *_ in matcher.get_opcodes() if tag not in ("equal", "insert")]
    check(f"{label} diff is insertions only", not bad, bad)


def test_goal_fold_empty_row(cur):
    sid = open_session(cur)
    cur.execute("SELECT state, stop_fp FROM v13_goal_fold(%s)", (sid,))
    state, stop_fp = cur.fetchone()
    check("empty fold one row running", state == "running" and stop_fp is None, (state, stop_fp))
    check("empty lifecycle running", lifecycle(cur, sid) == "running")
    check("empty lifecycle not null", lifecycle(cur, sid) is not None)


def test_fingerprint_equals_state_hash(cur):
    plain = fresh(cur)
    check("no exclusion types equal", fingerprint(cur, plain) == state_hash(cur, plain))
    done = fresh(cur)
    cur.execute("SELECT v13_closeout(%s, 'completed', 'harness_finish', false)", (done,))
    check("session completed still equal", fingerprint(cur, done) == state_hash(cur, done))
    receipt = q1(
        cur, "SELECT payload FROM events WHERE session_id=%s AND type='session/completed'",
        (done,))
    only = open_session(cur)
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'session/completed', %s::jsonb)",
        (only, u(), json.dumps(receipt)))
    check("only session/completed equal", fingerprint(cur, only) == state_hash(cur, only))
    for etype, payload, source in (
        ("goal/stopped", None, None),
        ("goal/resumed", None, None),
        ("control/handoff", None, None),
        ("wake/satisfied", {"effect_id": u(), "wake_kind": "event"}, "need"),
        ("turn/material_spent", None, "need"),
    ):
        sid = fresh(cur)
        before_equal = fingerprint(cur, sid) == state_hash(cur, sid)
        check(f"{etype} baseline equal", before_equal)
        if etype == "goal/stopped":
            stop(cur, sid)
        elif etype == "goal/resumed":
            stop(cur, sid)
            resume(cur, sid)
        elif etype == "control/handoff":
            cur.execute("SELECT v13_extract_handoff(NULL::uuid, %s, NULL)", (sid,))
            cur.fetchone()
        elif etype == "wake/satisfied":
            eid = enqueue(cur, sid, "tool", {"tool": "x"}, "spawn_subsession")
            cur.execute("UPDATE effects SET status='succeeded' WHERE effect_id=%s", (eid,))
            cur.execute(
                "SELECT v13_append_event(%s, %s, %s, %s::jsonb, %s)",
                (sid, u(), etype, json.dumps({"effect_id": eid, "wake_kind": "event"}), eid))
        else:
            eid = enqueue(cur, sid, "tool", harness_request(u(), 0, trev(cur, sid)), "harness_turn")
            settle(cur, eid, PROGRESS)
            cur.execute(
                "SELECT v13_append_event(%s, %s, 'turn/material_spent', %s::jsonb, %s)",
                (sid, u(), json.dumps({"schema_version": 1, "effect_id": eid}), eid))
        check(f"{etype} makes hashes differ", fingerprint(cur, sid) != state_hash(cur, sid))


def test_stop_changes_state_hash_not_fingerprint(cur):
    sid = fresh(cur)
    h0 = state_hash(cur, sid)
    f0 = fingerprint(cur, sid)
    stop(cur, sid)
    h1 = state_hash(cur, sid)
    f1 = fingerprint(cur, sid)
    check("stop changes state_hash", h1 != h0)
    check("stop keeps fingerprint", f1 == f0)
    check("fingerprint differs from new state_hash", f1 != h1)


def test_stop_payload(cur):
    sid = fresh(cur)
    parents = int(q1(cur, "SELECT count(*) FROM sessions"))
    effects = n_effects(cur, sid)
    status = status_of(cur, sid)
    seq0 = next_seq(cur, sid)
    payload = stop(cur, sid, "hold")
    stored = q1(
        cur,
        "SELECT payload FROM events WHERE session_id=%s AND type='goal/stopped'",
        (sid,))
    check("stop return equals event", payload == stored, (payload, stored))
    check("stop keys three", sorted(payload.keys()) == ["fingerprint", "reason", "schema_version"])
    check("stop source null", q1(
        cur,
        "SELECT source_effect_id FROM events WHERE session_id=%s AND type='goal/stopped'",
        (sid,)) is None)
    check("stop schema number 1", payload["schema_version"] == 1 and not isinstance(payload["schema_version"], str))
    check("stop reason", payload["reason"] == "hold")
    check("stop session count", int(q1(cur, "SELECT count(*) FROM sessions")) == parents)
    check("stop effects unchanged", n_effects(cur, sid) == effects)
    check("stop status unchanged", status_of(cur, sid) == status)
    check("stop no cancel", n_events(cur, sid, "cancel/requested") == 0)
    check("stop no handoff", n_events(cur, sid, "control/handoff") == 0)
    check("stop next_seq +1", next_seq(cur, sid) == seq0 + 1)
    check("stop event seq", int(q1(
        cur, "SELECT seq FROM events WHERE session_id=%s AND type='goal/stopped'",
        (sid,))) == seq0)


def test_lifecycle_transitions(cur, server):
    sid = fresh(cur)
    stop(cur, sid)
    check("first stop stopped", lifecycle(cur, sid) == "stopped")
    events = n_events(cur, sid)
    fails_with(cur, "SELECT v13_goal_stop(%s, 'again')", (sid,),
               "v13: goal lifecycle", "repeat stop", exact=True)
    check("repeat stop zero events", n_events(cur, sid) == events)
    bare = fresh(cur)
    before = n_events(cur, bare)
    fails_with(cur, "SELECT v13_goal_resume(%s, 'early')", (bare,),
               "v13: goal lifecycle", "resume without stop", exact=True)
    check("early resume zero", n_events(cur, bare) == before)
    done = fresh(cur)
    cur.execute("SELECT v13_closeout(%s, 'completed', 'harness_finish', false)", (done,))
    fails_with(cur, "SELECT v13_goal_stop(%s, 'late')", (done,),
               "v13: goal lifecycle", "terminal stop", exact=True)
    fails_with(cur, "SELECT v13_goal_resume(%s, 'late')", (done,),
               "v13: goal lifecycle", "terminal resume", exact=True)
    drifted = fresh(cur)
    stop(cur, drifted)
    prefix(cur, drifted, "later")
    fails_with(cur, "SELECT v13_goal_resume(%s, 'back')", (drifted,),
               "v13: goal fingerprint", "drift resume", exact=True)
    check("drift no resumed", n_events(cur, drifted, "goal/resumed") == 0)
    check("drift still stopped", lifecycle(cur, drifted) == "stopped")
    clean = fresh(cur)
    stop(cur, clean, "pause")
    fp = fingerprint(cur, clean)
    resume(cur, clean, "go")
    check("resume running", lifecycle(cur, clean) == "running")
    check("resume two events", n_events(cur, clean, "goal/stopped") == 1
          and n_events(cur, clean, "goal/resumed") == 1)
    fps = q1(
        cur,
        "SELECT array_agg(payload->>'fingerprint' ORDER BY seq) FROM events "
        "WHERE session_id=%s AND type IN ('goal/stopped','goal/resumed')",
        (clean,))
    check("resume fingerprints match", fps == [fp, fp], fps)
    missing = u()
    msg = fails_with(cur, "SELECT v13_goal_stop(%s, 'x')", (missing,),
                     "v13: unknown session", "operator unknown", exact=False)
    check("unknown contains uuid", missing in msg, msg)


def test_non_operator_and_route(server):
    setup = connect(server)
    sid = fresh(setup.cursor())
    setup.commit()
    outsider = "v13_govern_outsider"
    admin = connect(server)
    admin.autocommit = True
    try:
        ac = admin.cursor()
        ac.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (outsider,))
        if ac.fetchone():
            ac.execute(
                "REVOKE ALL ON FUNCTION public.v13_goal_stop(uuid, text) FROM " + outsider)
            ac.execute(
                "REVOKE ALL ON FUNCTION public.v13_control_operator() FROM " + outsider)
            ac.execute(f"DROP ROLE IF EXISTS {outsider}")
        ac.execute(f"CREATE ROLE {outsider} NOLOGIN")
        ac.execute(
            "GRANT EXECUTE ON FUNCTION public.v13_goal_stop(uuid, text) TO " + outsider)
        ac.execute(
            "GRANT EXECUTE ON FUNCTION public.v13_control_operator() TO " + outsider)
        hold = connect(server)
        try:
            hc = hold.cursor()
            hc.execute(f"SET ROLE {outsider}")
            fails_with(hc, "SELECT v13_goal_stop(%s, 'nope')", (sid,),
                       "v13: session not found", "outsider stop", exact=True)
            check("outsider message has no uuid", True)
            hc.execute("RESET ROLE")
            check("outsider zero goal rows", n_events(hc, sid, "goal/stopped") == 0)
            hold.rollback()
        finally:
            hold.close()
        expect_conn = connect(server)
        try:
            ec = expect_conn.cursor()
            expect_42501(ec, "v13_worker", "SELECT v13_goal_stop(%s, 'nope')", (sid,),
                         "worker stop 42501")
            expect_conn.rollback()
        finally:
            expect_conn.close()
        route = connect(server)
        try:
            rc = route.cursor()
            rc.execute("SET ROLE v13_route")
            rc.execute("SELECT v13_goal_stop(%s, 'route')", (sid,))
            rc.fetchone()
            rc.execute("RESET ROLE")
            route.commit()
            check("route stop committed", n_events(rc, sid, "goal/stopped") == 1)
        finally:
            route.close()
    finally:
        ac = admin.cursor()
        ac.execute(
            "REVOKE ALL ON FUNCTION public.v13_goal_stop(uuid, text) FROM " + outsider)
        ac.execute(
            "REVOKE ALL ON FUNCTION public.v13_control_operator() FROM " + outsider)
        ac.execute(f"DROP ROLE IF EXISTS {outsider}")
        admin.close()


def test_guard_spawn_owner_insert(cur):
    sid = fresh(cur)
    payload = legal_goal_payload(cur, sid)
    events = n_events(cur, sid)
    seq0 = next_seq(cur, sid)
    cur.execute("SAVEPOINT owner_insert")
    cur.execute("SET ROLE v13_spawn_owner")
    cur.execute(
        "UPDATE sessions SET next_seq = next_seq + 1 WHERE session_id=%s "
        "RETURNING next_seq - 1, turn_no",
        (sid,))
    seq, turn = cur.fetchone()
    try:
        cur.execute(
            "INSERT INTO events (session_id, seq, event_id, type, turn_no, payload, "
            "payload_hash, source_effect_id) VALUES (%s, %s, %s, 'goal/stopped', %s, "
            "%s::jsonb, encode(digest(%s::jsonb::text, 'sha256'), 'hex'), NULL)",
            (sid, seq, u(), turn, json.dumps(payload), json.dumps(payload)))
        check("spawn_owner insert rejected", False, "inserted")
    except psycopg2.Error as exc:
        msg = exc.diag.message_primary
        check("spawn_owner guard session not found", msg == "v13: session not found", msg)
        check("spawn_owner message has no uuid", sid not in (msg or ""))
    cur.execute("ROLLBACK TO SAVEPOINT owner_insert")
    cur.execute("RESET ROLE")
    check("spawn_owner zero write events", n_events(cur, sid) == events)
    check("spawn_owner zero write seq", next_seq(cur, sid) == seq0)


def test_forged_negatives(cur):
    sid = fresh(cur)
    base = legal_goal_payload(cur, sid)

    def via_append(payload, source, needle, label):
        fails_with(
            cur,
            "SELECT v13_append_event(%s, %s, 'goal/stopped', %s::jsonb, %s)",
            (sid, u(), json.dumps(payload) if not isinstance(payload, str) else payload, source),
            needle, label, exact=True)

    bad = dict(base)
    via_append(bad, u(), "v13: goal source", "source nonempty")
    via_append({**base, "reason": ""}, None, "v13: goal payload", "empty reason")
    via_append({**base, "extra": 1}, None, "v13: goal payload", "extra key")
    via_append({**base, "schema_version": "1"}, None, "v13: goal payload", "schema string")
    via_append({**base, "schema_version": 2}, None, "v13: goal payload", "schema 2")
    via_append({**base, "reason": 1}, None, "v13: goal payload", "reason not string")
    via_append({**base, "fingerprint": "ZZ"}, None, "v13: goal payload", "fingerprint shape")
    fails_with(
        cur, "SELECT v13_append_event(%s, %s, 'goal/stopped', %s::jsonb)",
        (sid, u(), json.dumps(["nope"])), "v13: goal payload", "payload array", exact=True)
    fails_with(
        cur, "SELECT v13_append_event(%s, %s, 'goal/stopped', %s::jsonb)",
        (sid, u(), json.dumps("nope")), "v13: goal payload", "payload string", exact=True)
    fails_with(
        cur, "SELECT v13_append_event(%s, %s, 'goal/stopped', 'null'::jsonb)",
        (sid, u()), "v13: goal payload", "payload null", exact=True)
    via_append({**base, "fingerprint": HEX_BAD}, None, "v13: goal fingerprint",
               "fingerprint mismatch")
    events = n_events(cur, sid)
    seq0 = next_seq(cur, sid)
    cur.execute("SAVEPOINT bypass")
    try:
        cur.execute(
            "UPDATE sessions SET next_seq = next_seq + 1 WHERE session_id=%s "
            "RETURNING next_seq - 1, turn_no",
            (sid,))
        seq, turn = cur.fetchone()
        payload = {**base, "fingerprint": HEX_BAD}
        cur.execute(
            "INSERT INTO events (session_id, seq, event_id, type, turn_no, payload, "
            "payload_hash, source_effect_id) VALUES (%s, %s, %s, 'goal/stopped', %s, "
            "%s::jsonb, encode(digest(%s::jsonb::text, 'sha256'), 'hex'), NULL)",
            (sid, seq, u(), turn, json.dumps(payload), json.dumps(payload)))
        check("bypass insert rejected", False)
    except psycopg2.Error as exc:
        check("bypass fingerprint", exc.diag.message_primary == "v13: goal fingerprint",
              exc.diag.message_primary)
    cur.execute("ROLLBACK TO SAVEPOINT bypass")
    check("bypass seq restored", next_seq(cur, sid) == seq0)
    check("bypass events restored", n_events(cur, sid) == events)
    stop(cur, sid)
    prefix(cur, sid, "drift-bypass")
    events = n_events(cur, sid)
    seq0 = next_seq(cur, sid)
    cur.execute("SAVEPOINT resumed_bypass")
    try:
        cur.execute(
            "UPDATE sessions SET next_seq = next_seq + 1 WHERE session_id=%s "
            "RETURNING next_seq - 1, turn_no",
            (sid,))
        seq, turn = cur.fetchone()
        payload = legal_goal_payload(cur, sid, "back")
        cur.execute(
            "INSERT INTO events (session_id, seq, event_id, type, turn_no, payload, "
            "payload_hash, source_effect_id) VALUES (%s, %s, %s, 'goal/resumed', %s, "
            "%s::jsonb, encode(digest(%s::jsonb::text, 'sha256'), 'hex'), NULL)",
            (sid, seq, u(), turn, json.dumps(payload), json.dumps(payload)))
        check("resumed bypass rejected", False)
    except psycopg2.Error as exc:
        check("resumed bypass fingerprint",
              exc.diag.message_primary == "v13: goal fingerprint", exc.diag.message_primary)
    cur.execute("ROLLBACK TO SAVEPOINT resumed_bypass")
    check("resumed bypass restored seq", next_seq(cur, sid) == seq0)
    check("resumed bypass restored events", n_events(cur, sid) == events)


def test_seq_negatives(cur):
    sid = fresh(cur)
    payload = legal_goal_payload(cur, sid)
    body = json.dumps(payload)
    seq_now = next_seq(cur, sid)
    turn = q1(cur, "SELECT turn_no FROM sessions WHERE session_id=%s", (sid,))

    def raw(seq, turn_no, label):
        cur.execute("SAVEPOINT seqneg")
        try:
            cur.execute(
                "INSERT INTO events (session_id, seq, event_id, type, turn_no, payload, "
                "payload_hash, source_effect_id) VALUES (%s, %s, %s, 'goal/stopped', %s, "
                "%s::jsonb, encode(digest(%s::jsonb::text, 'sha256'), 'hex'), NULL)",
                (sid, seq, u(), turn_no, body, body))
            check(label, False, "inserted")
        except psycopg2.Error as exc:
            check(label, exc.diag.message_primary == "v13: goal seq", exc.diag.message_primary)
        cur.execute("ROLLBACK TO SAVEPOINT seqneg")

    raw(seq_now, turn, "seq equals next_seq")
    raw(9223372036854775807, turn, "seq bigint max")
    raw(None, turn, "seq null")
    raw(seq_now - 1, turn + 9, "turn_no misaligned")


def test_stop_blocks_enqueue(cur):
    control = fresh(cur)
    project_calls(cur, control, "answer", CALL)
    check("control would spawn", advance(cur, control, role="v13_route") == "progressed")
    sid = fresh(cur)
    project_calls(cur, sid, "answer", CALL)
    stop(cur, sid)
    effects = n_effects(cur, sid)
    word = advance(cur, sid)
    check("stopped advance waiting", word == "waiting", word)
    check("stopped effects unchanged", n_effects(cur, sid) == effects)
    check("stopped not terminal status", status_of(cur, sid) not in ("cancelled", "completed", "failed"))


def test_stop_busy_matrix(cur):
    for status in ("ready", "claimed", "unknown"):
        sid = fresh(cur)
        eid = enqueue(cur, sid, "human", {"reason": "ask"})
        if status != "ready":
            cur.execute("UPDATE effects SET status=%s WHERE effect_id=%s", (status, eid))
        events = n_events(cur, sid)
        fails_with(cur, "SELECT v13_goal_stop(%s, 'busy')", (sid,),
                   "v13: goal busy", f"{status} busy", exact=True)
        check(f"{status} busy zero", n_events(cur, sid) == events)
    walled = fresh(cur)
    eid = enqueue(cur, walled, "tool", {"tool": "x"}, "spawn_subsession")
    cur.execute("UPDATE effects SET status='unknown' WHERE effect_id=%s", (eid,))
    cur.execute("UPDATE sessions SET status='blocked_unknown' WHERE session_id=%s", (walled,))
    fails_with(cur, "SELECT v13_goal_stop(%s, 'wall')", (walled,),
               "v13: goal busy", "blocked_unknown busy", exact=True)


def test_terminal_before_busy(cur):
    sid = fresh(cur)
    cur.execute("SELECT v13_closeout(%s, 'completed', 'harness_finish', false)", (sid,))
    fails_with(
        cur, "SELECT v13_append_event(%s, %s, 'goal/stopped', %s::jsonb)",
        (sid, u(), json.dumps(legal_goal_payload(cur, sid))),
        "v13: goal lifecycle", "terminal append", exact=True)
    eid = enqueue(cur, sid, "tool", {"tool": "x"}, "spawn_subsession")
    cur.execute("UPDATE effects SET status='unknown' WHERE effect_id=%s", (eid,))
    fails_with(
        cur, "SELECT v13_append_event(%s, %s, 'goal/stopped', %s::jsonb)",
        (sid, u(), json.dumps(legal_goal_payload(cur, sid))),
        "v13: goal lifecycle", "terminal before busy", exact=True)


def test_child_done_while_parent_stopped(cur):
    sid = fresh(cur)
    eid = enqueue(cur, sid, "tool", harness_request(u(), 0, trev(cur, sid)), "harness_turn")
    settle(cur, eid, PROGRESS)
    check("child fixture no ready", ready_claimed(cur, sid) == 0)
    stop(cur, sid)
    fp = fingerprint(cur, sid)
    materials = n_events(cur, sid, "turn/material_spent")
    word = advance(cur, sid, include_failed=False)
    check("stopped progress waiting", word == "waiting", word)
    check("material written while stopped", n_events(cur, sid, "turn/material_spent") == materials + 1)
    check("material does not drift fingerprint", fingerprint(cur, sid) == fp)
    resume(cur, sid)
    check("resume after material", lifecycle(cur, sid) == "running")


def test_stop_then_finish_settles(cur):
    sid = fresh(cur)
    eid = enqueue(cur, sid, "tool", harness_request(u(), 0, trev(cur, sid)), "harness_turn")
    settle(cur, eid, FINISH)
    stop(cur, sid)
    word = advance(cur, sid)
    check("finish despite stop terminal", word == "terminal", word)
    check("finish despite stop completed", status_of(cur, sid) == "completed")


def test_stop_max_cycles_not_failed(cur):
    cur.execute("SAVEPOINT maxcy")
    flip_policy(cur, "turn_budget", next_ver(), {"max_cycles": 0})
    sid = fresh(cur)
    eid = enqueue(cur, sid, "tool", harness_request(u(), 0, trev(cur, sid)), "harness_turn")
    settle(cur, eid, {"result_kind": "progress", "signals": ["repair/required"]})
    check("maxcy no children", n_children(cur, sid) == 0)
    check("maxcy no calls", n_events(cur, sid, "tool/call") == 0)
    stop(cur, sid)
    word = advance(cur, sid)
    check("maxcy waiting", word == "waiting", word)
    check("maxcy not failed", status_of(cur, sid) != "failed")
    check("maxcy no failed receipt", n_events(cur, sid, "session/failed") == 0)
    cur.execute("ROLLBACK TO SAVEPOINT maxcy")


def test_explore_raise_survives_gate(cur):
    cur.execute("SAVEPOINT explore")
    flip_policy(cur, "spawn_budget", next_ver(),
                {"max_nonterminal": 1, "max_depth": 4, "max_fanout": 8})
    sid = fresh(cur)
    insert_one(cur, sid, "ready")
    project_calls(cur, sid, "explore", CALL)
    effects = n_effects(cur, sid)
    routes = n_events(cur, sid, "turn/route")
    cur.execute(
        "UPDATE sessions SET context_active_revision = v13_context_required(session_id) "
        "WHERE session_id=%s", (sid,))
    fails_with(cur, "SELECT v13_advance(%s, %s::jsonb)",
               (sid, json.dumps(snap_of(cur, sid))),
               "v13: explore spawn", "explore still raises", exact=True)
    check("explore zero new effects", n_effects(cur, sid) == effects)
    check("explore zero new routes", n_events(cur, sid, "turn/route") == routes)
    cur.execute("ROLLBACK TO SAVEPOINT explore")


def test_stopped_cancel_liveness(cur):
    sid = fresh(cur)
    stop(cur, sid)
    cur.execute("SELECT v13_cancel(%s)", (sid,))
    check("cancel accepted", cur.fetchone()[0] == "accepted")
    check("hint run_now before closeout",
          q1(cur, "SELECT v13_scheduler_hint(%s)", (sid,)) == "run_now")
    word = advance(cur, sid)
    check("cancel closeout terminal", word == "terminal", word)
    check("cancel closeout status", status_of(cur, sid) == "cancelled")
    check("hint dont_notify after closeout",
          q1(cur, "SELECT v13_scheduler_hint(%s)", (sid,)) == "dont_notify")


def test_handoff_after_stop_resume(cur):
    sid = fresh(cur)
    cur.execute("SELECT v13_extract_handoff(NULL::uuid, %s, NULL)", (sid,))
    before = cur.fetchone()[0]
    fp = fingerprint(cur, sid)
    stop(cur, sid)
    check("stop keeps fingerprint across handoff", fingerprint(cur, sid) == fp)
    cur.execute("SELECT v13_extract_handoff(NULL::uuid, %s, NULL)", (sid,))
    after = cur.fetchone()[0]
    check("null cutoff hash changes", after["transcript_hash"] != before["transcript_hash"])
    check("null cutoff new delivery", after["delivery_id"] != before["delivery_id"])
    resume(cur, sid)
    check("resume after handoff", lifecycle(cur, sid) == "running")


def test_handoff_policy_regression(cur):
    sid = fresh(cur)
    seq0 = next_seq(cur, sid)
    cur.execute("SELECT v13_extract_handoff(NULL::uuid, %s, NULL)", (sid,))
    first = cur.fetchone()[0]
    check("unstopped extract", first["delivery_id"] is not None)
    handoffs = n_events(cur, sid, "control/handoff")
    stop(cur, sid, "pause")
    check("stop adds no handoff", n_events(cur, sid, "control/handoff") == handoffs)
    cutoff = int(q1(cur, "SELECT max(seq) FROM events WHERE session_id=%s", (sid,)))
    cur.execute("SAVEPOINT handoff_pol")
    flip_policy(cur, "handoff_policy", next_ver(), {"schema_version": 1, "enabled": False})
    seq_fail = next_seq(cur, sid)
    fails_with(
        cur, "SELECT v13_extract_handoff(NULL::uuid, %s, %s)",
        (sid, cutoff), "v13: handoff disabled", "disabled new cutoff", exact=True)
    cur.execute("SELECT v13_extract_handoff(NULL::uuid, %s, %s)", (sid, first["up_to_seq"]))
    replay = cur.fetchone()[0]
    check("disabled replay returns original", replay["delivery_id"] == first["delivery_id"])
    cur.execute(
        "UPDATE v13_policies SET active=false WHERE name='handoff_policy' AND active")
    fails_with(
        cur, "SELECT v13_extract_handoff(NULL::uuid, %s, %s)",
        (sid, cutoff), "v13: handoff policy", "no active handoff", exact=True)
    check("failed handoff calls zero seq", next_seq(cur, sid) == seq_fail)
    cur.execute("ROLLBACK TO SAVEPOINT handoff_pol")
    check("successful calls did bump seq", next_seq(cur, sid) > seq0)


def test_recover_skip(cur):
    parent = fresh(cur)
    child = insert_one(cur, parent, "completed")
    before = n_events(cur, parent, "recover/nudge")
    cur.execute("SELECT v13_recover_idle()")
    nudged = n_events(cur, parent, "recover/nudge") - before
    check("recover nudges before stop", nudged >= 1, nudged)
    stop(cur, parent)
    after = n_events(cur, parent, "recover/nudge")
    cur.execute("SELECT v13_recover_idle()")
    check("recover zero after stop", n_events(cur, parent, "recover/nudge") == after)
    cur.execute("SAVEPOINT duty0")
    flip_policy(cur, "triage", next_ver(), {"duty_cycle": 0})
    held = fresh(cur)
    advance(cur, held)
    check("duty hold written", n_events(cur, held, "triage/hold") == 1)
    repair_n = n_events(cur, held, "recover/nudge")
    src = enqueue(cur, held, "tool", {"tool": "repair"}, "spawn_subsession")
    cur.execute("UPDATE effects SET status='succeeded' WHERE effect_id=%s", (src,))
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'repair/required', %s::jsonb, %s)",
        (held, u(), json.dumps({"schema_version": 1}), src))
    cur.execute("SELECT v13_recover_idle()")
    check("duty 0 still skips recover", n_events(cur, held, "recover/nudge") == repair_n)
    cur.execute("ROLLBACK TO SAVEPOINT duty0")
    stopped = fresh(cur)
    stop(cur, stopped)
    advance(cur, stopped)
    check("stopped does not write hold", n_events(cur, stopped, "triage/hold") == 0)


def test_single_fold_body(cur):
    body = prosrc(cur, "v13_goal_lifecycle(uuid)")
    check("lifecycle thin wrapper", "v13_goal_fold(" in body and "ORDER BY" not in body, body)
    cur.execute(
        """
        SELECT p.proname
          FROM pg_proc p
          JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname = 'public'
           AND p.prosrc LIKE '%goal/stopped%'
           AND p.prosrc LIKE '%goal/resumed%'
           AND p.prosrc LIKE '%ORDER BY seq%'
           AND (p.prosrc LIKE '%type IN (%' OR p.prosrc LIKE '%= ANY%')
           AND p.prosrc NOT LIKE '%NOT IN%'
        """)
    names = [row[0] for row in cur.fetchall()]
    check("only fold scans lifecycle", names == ["v13_goal_fold"], names)
    empty = open_session(cur)
    check("no-event lifecycle running", lifecycle(cur, empty) == "running")
    fails_with(cur, "SELECT v13_goal_lifecycle(%s)", (u(),),
               "v13: unknown session", "unknown lifecycle", exact=False)


def test_attention_lifecycle_rank(cur):
    cur.execute("SAVEPOINT rank")
    flip_policy(cur, "quota_window", next_ver(), {
        "schema_version": 1, "window_hours": 8760, "slot_minutes": 0, "allowed": 1,
    })
    root = open_session(cur)
    stopped = insert_one(cur, root, "ready")
    prefix(cur, stopped)
    stop(cur, stopped)
    quota = insert_one(cur, root, "ready")
    prefix(cur, quota)
    eid = enqueue(cur, quota, "tool", harness_request(u(), 0, trev(cur, quota)), "harness_turn")
    settle(cur, eid, PROGRESS)
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'turn/material_spent', %s::jsonb, %s)",
        (quota, u(), json.dumps({"schema_version": 1, "effect_id": eid}), eid))
    cur.execute(
        "SELECT session_id::text, lifecycle, blocked_by, attention_rank "
        "FROM v13_attention(%s)",
        (root,))
    rows = {row[0]: row[1:] for row in cur.fetchall()}
    check("stopped lifecycle column", rows[stopped][0] == "stopped", rows.get(stopped))
    check("stopped blocked_by", rows[stopped][1] == "goal_stopped", rows.get(stopped))
    check("quota blocked_by", rows[quota][1] == "quota_window", rows.get(quota))
    check("stopped rank before quota", rows[stopped][2] < rows[quota][2],
          (rows.get(stopped), rows.get(quota)))
    cur.execute("ROLLBACK TO SAVEPOINT rank")


def test_hint_and_batch(cur):
    missing = u()
    snap_msg = fails_with(
        cur, "SELECT v13_spawn_budget_snapshot(%s, 1)", (missing,),
        "v13: unknown session", "snapshot unknown", exact=False)
    hint_msg = fails_with(
        cur, "SELECT v13_scheduler_hint(%s)", (missing,),
        "v13: unknown session", "hint unknown", exact=False)
    check("unknown sqlerrm match", snap_msg == hint_msg, (snap_msg, hint_msg))
    cur.execute("SAVEPOINT badpol")
    flip_policy(cur, "spawn_budget", next_ver(), {"max_nonterminal": 1})
    sid = fresh(cur)
    project_calls(cur, sid, "answer", CALL)
    snap_msg = fails_with(
        cur, "SELECT v13_spawn_budget_snapshot(%s, 1)", (sid,),
        "v13: spawn_budget policy", "snapshot bad policy", exact=True)
    hint_msg = fails_with(
        cur, "SELECT v13_scheduler_hint(%s)", (sid,),
        "v13: spawn_budget policy", "hint bad policy", exact=True)
    check("bad policy sqlerrm match", snap_msg == hint_msg)
    cur.execute("ROLLBACK TO SAVEPOINT badpol")
    root = open_session(cur)
    leaf = root
    for _ in range(65):
        leaf = insert_one(cur, leaf, "ready")
    prefix(cur, leaf)
    project_calls(cur, leaf, "answer", CALL)
    snap_msg = fails_with(
        cur, "SELECT v13_spawn_budget_snapshot(%s, 1)", (leaf,),
        "v13: spawn root cycle", "snapshot cycle", exact=True)
    hint_msg = fails_with(
        cur, "SELECT v13_scheduler_hint(%s)", (leaf,),
        "v13: spawn root cycle", "hint cycle", exact=True)
    check("cycle sqlerrm match", snap_msg == hint_msg)
    cur.execute("SAVEPOINT axes")
    flip_policy(cur, "spawn_budget", next_ver(),
                {"max_nonterminal": 1, "max_depth": 1, "max_fanout": 1})
    fan = fresh(cur)
    project_calls(cur, fan, "answer", CALLS2)
    check("fanout snapshot false",
          q1(cur, "SELECT v13_spawn_budget_snapshot(%s, 2)", (fan,)) is False)
    check("fanout hint wait", q1(cur, "SELECT v13_scheduler_hint(%s)", (fan,)) == "wait")
    deep = open_session(cur)
    mid = insert_one(cur, deep, "ready")
    prefix(cur, mid)
    project_calls(cur, mid, "answer", CALL)
    check("depth snapshot false",
          q1(cur, "SELECT v13_spawn_budget_snapshot(%s, 1)", (mid,)) is False)
    check("depth hint wait", q1(cur, "SELECT v13_scheduler_hint(%s)", (mid,)) == "wait")
    capped = fresh(cur)
    insert_one(cur, capped, "ready")
    project_calls(cur, capped, "answer", CALL)
    check("cap snapshot false",
          q1(cur, "SELECT v13_spawn_budget_snapshot(%s, 1)", (capped,)) is False)
    check("cap hint wait", q1(cur, "SELECT v13_scheduler_hint(%s)", (capped,)) == "wait")
    cur.execute("ROLLBACK TO SAVEPOINT axes")
    plain = fresh(cur)
    check("budget ok hint run_now",
          q1(cur, "SELECT v13_scheduler_hint(%s)", (plain,)) == "run_now")
    stopped = fresh(cur)
    stop(cur, stopped)
    check("stopped hint dont_notify",
          q1(cur, "SELECT v13_scheduler_hint(%s)", (stopped,)) == "dont_notify")
    resume(cur, stopped)
    check("resumed hint run_now",
          q1(cur, "SELECT v13_scheduler_hint(%s)", (stopped,)) == "run_now")
    parked = fresh(cur)
    project_calls(cur, parked, "answer", CALL)
    cur.execute("SAVEPOINT route_hint")
    cur.execute("SET ROLE v13_route")
    word = q1(cur, "SELECT v13_scheduler_hint(%s)", (parked,))
    cur.execute("RESET ROLE")
    check("route hint calls snapshot branch", word == "run_now", word)
    cur.execute("ROLLBACK TO SAVEPOINT route_hint")


def test_cap_skips_spawn(cur):
    cur.execute("SAVEPOINT cap")
    flip_policy(cur, "spawn_budget", next_ver(),
                {"max_nonterminal": 1, "max_depth": 4, "max_fanout": 8})
    sid = fresh(cur)
    insert_one(cur, sid, "ready")
    project_calls(cur, sid, "answer", CALL)
    other = open_session(cur)
    other_status = status_of(cur, other)
    check("cap no ready/claimed", ready_claimed(cur, sid) == 0)
    kids = n_children(cur, sid)
    effects = n_effects(cur, sid)
    calls = n_events(cur, sid, "tool/call")
    word = advance(cur, sid, role="v13_route")
    check("cap waiting", word == "waiting", word)
    check("cap status waiting", status_of(cur, sid) == "waiting")
    check("cap no hold", n_events(cur, sid, "triage/hold") == 0)
    check("cap unrelated status", status_of(cur, other) == other_status)
    check("cap children unchanged", n_children(cur, sid) == kids)
    check("cap no fanout", n_events(cur, sid, "turn/route") == 0
          or q1(cur, "SELECT count(*) FROM events WHERE session_id=%s AND type='turn/route' "
                "AND payload->>'reason'='spawn_fanout'", (sid,)) == 0)
    check("cap tool/call remains", n_events(cur, sid, "tool/call") == calls)
    check("cap effects unchanged", n_effects(cur, sid) == effects)
    fails_with(
        cur, "SELECT v13_spawn_subsession(%s, %s::jsonb)",
        (sid, json.dumps({"schema_version": 1, "children": [{"tool_call_id": "over", "task": "nope"}]})),
        "v13: spawn budget cap", "direct spawn still raises", exact=True)
    cur.execute("ROLLBACK TO SAVEPOINT cap")


def test_fanout_and_depth_skip(cur):
    cur.execute("SAVEPOINT fan")
    flip_policy(cur, "spawn_budget", next_ver(),
                {"max_nonterminal": 8, "max_depth": 4, "max_fanout": 1})
    sid = fresh(cur)
    project_calls(cur, sid, "answer", CALLS2)
    check("fanout no ready", ready_claimed(cur, sid) == 0)
    word = advance(cur, sid, role="v13_route")
    check("fanout waiting", word == "waiting", word)
    check("fanout no children", n_children(cur, sid) == 0)
    check("fanout status waiting", status_of(cur, sid) == "waiting")
    cur.execute("ROLLBACK TO SAVEPOINT fan")
    cur.execute("SAVEPOINT depth")
    flip_policy(cur, "spawn_budget", next_ver(),
                {"max_nonterminal": 8, "max_depth": 1, "max_fanout": 8})
    root = open_session(cur)
    leaf = insert_one(cur, root, "ready")
    prefix(cur, leaf)
    project_calls(cur, leaf, "answer", CALL)
    check("depth no ready", ready_claimed(cur, leaf) == 0)
    word = advance(cur, leaf, role="v13_route")
    check("depth waiting", word == "waiting", word)
    check("depth no children", n_children(cur, leaf) == 0)
    check("depth status waiting", status_of(cur, leaf) == "waiting")
    fails_with(
        cur, "SELECT v13_spawn_subsession(%s, %s::jsonb)",
        (leaf, json.dumps({"schema_version": 1, "children": [{"tool_call_id": "d", "task": "nope"}]})),
        "v13: spawn budget depth", "direct depth still raises", exact=True)
    cur.execute("ROLLBACK TO SAVEPOINT depth")


def test_bad_policy_still_raises(cur):
    cur.execute("SAVEPOINT badadv")
    flip_policy(cur, "spawn_budget", next_ver(), {"max_nonterminal": 1})
    sid = fresh(cur)
    project_calls(cur, sid, "answer", CALL)
    check("bad policy no ready", ready_claimed(cur, sid) == 0)
    cur.execute(
        "UPDATE sessions SET context_active_revision = v13_context_required(session_id) "
        "WHERE session_id=%s", (sid,))
    fails_with(
        cur, "SELECT v13_advance(%s, %s::jsonb)",
        (sid, json.dumps(snap_of(cur, sid))),
        "v13: spawn_budget policy", "bad policy raises", exact=True)
    cur.execute("ROLLBACK TO SAVEPOINT badadv")


def test_defer_with_finish(cur):
    cur.execute("SAVEPOINT defer")
    sid = fresh(cur)
    eid = enqueue(cur, sid, "tool", harness_request(u(), 0, trev(cur, sid)), "harness_turn")
    settle(cur, eid, FINISH)
    project_calls(cur, sid, "answer", CALL)
    stop(cur, sid)
    other = open_session(cur)
    other_status = status_of(cur, other)
    effects = n_effects(cur, sid)
    calls = n_events(cur, sid, "tool/call")
    word = advance(cur, sid)
    check("defer waiting", word == "waiting", word)
    check("defer status waiting", status_of(cur, sid) == "waiting")
    check("defer no hold", n_events(cur, sid, "triage/hold") == 0)
    check("defer unrelated", status_of(cur, other) == other_status)
    check("defer not terminal", status_of(cur, sid) not in ("completed", "failed", "cancelled"))
    check("defer no closeout", n_events(cur, sid, "session/completed") == 0)
    check("defer calls remain", n_events(cur, sid, "tool/call") == calls)
    check("defer effects unchanged", n_effects(cur, sid) == effects)
    cur.execute("ROLLBACK TO SAVEPOINT defer")


def test_cap_defer_continuation(cur):
    cur.execute("SAVEPOINT capcont")
    flip_policy(cur, "spawn_budget", next_ver(),
                {"max_nonterminal": 8, "max_depth": 4, "max_fanout": 1})
    sid = fresh(cur)
    eid = enqueue(cur, sid, "tool", harness_request(u(), 0, trev(cur, sid)), "harness_turn")
    settle(cur, eid, {"result_kind": "progress", "signals": ["repair/required"]})
    project_calls(cur, sid, "answer", CALLS2)
    check("capcont should_run", q1(cur, "SELECT v13_should_run(%s)", (sid,)) is True)
    check("capcont no ready", ready_claimed(cur, sid) == 0)
    routes = n_events(cur, sid, "turn/route")
    word = advance(cur, sid)
    check("capcont waiting", word == "waiting", word)
    check("capcont status waiting", status_of(cur, sid) == "waiting")
    check("capcont no continuation route", n_events(cur, sid, "turn/route") == routes)
    check("capcont no closeout", n_events(cur, sid, "session/failed") == 0)
    check("capcont no fanout", q1(
        cur,
        "SELECT count(*) FROM events WHERE session_id=%s AND payload->>'reason'='spawn_fanout'",
        (sid,)) == 0)
    cur.execute("ROLLBACK TO SAVEPOINT capcont")


def test_stale_then_waiting(cur):
    sid = fresh(cur)
    cur.execute(
        "UPDATE sessions SET context_active_revision = v13_context_required(session_id) "
        "WHERE session_id=%s", (sid,))
    old = snap_of(cur, sid)
    stop(cur, sid)
    word = advance(cur, sid, snap=old)
    check("old snap stale", word == "stale", word)
    effects = n_effects(cur, sid)
    word = advance(cur, sid)
    check("retry waiting", word == "waiting", word)
    check("retry zero new effects", n_effects(cur, sid) == effects)


def test_source_and_acl(cur):
    src = prosrc(cur, "v13_advance(uuid,jsonb)")
    old = (PRE / "advance.prosrc").read_text()
    only_inserts(old, src, "advance")
    share = src.find("v13_policy_share()")
    calls_if = src.find("IF jsonb_array_length(v_calls) > 0")
    should = src.find("v13_should_run(")
    check("policy_share outside calls if", 0 <= share < calls_if)
    check("policy_share before should_run", share < should)
    check("audit precheck before prework",
          src.find("v13_triage_duty()<>0") < src.find("v13_triage_prework(p_sid)"))
    check("spawn_fanout object once",
          src.count("jsonb_build_object('action', 'sql', 'reason', 'spawn_fanout'") == 1
          or src.count("'spawn_fanout'") == 1)
    route_oid = (PRE / "route.prosrc.oid").read_text().strip()
    live_oid = str(q1(cur, "SELECT oid FROM pg_proc WHERE oid = 'v13_route(uuid,jsonb)'::regprocedure"))
    live_hash = hashlib.sha256(prosrc(cur, "v13_route(uuid,jsonb)").encode()).hexdigest()
    old_hash = hashlib.sha256((PRE / "route.prosrc").read_text().encode()).hexdigest()
    check("route oid unchanged", live_oid == route_oid, (live_oid, route_oid))
    check("route hash unchanged", live_hash == old_hash)
    wrap = prosrc(cur, "v13_spawn_batch_allowed(uuid,integer)")
    check("wrapper one policy_share", wrap.count("v13_policy_share(") == 1)
    check("wrapper no FOR SHARE", "FOR SHARE" not in wrap)
    check("sql file has no pg_sleep", "pg_sleep" not in (ROOT / "v13_govern.sql").read_text())
    check("index def", "seq DESC" in q1(
        cur, "SELECT pg_get_indexdef('ix_events_goal_lifecycle'::regclass)")
          and "goal/stopped" in q1(cur, "SELECT pg_get_indexdef('ix_events_goal_lifecycle'::regclass)"))
    check("route lifecycle", q1(
        cur, "SELECT has_function_privilege('v13_route', 'v13_goal_lifecycle(uuid)', 'EXECUTE')") is True)
    check("worker lifecycle denied", q1(
        cur, "SELECT has_function_privilege('v13_worker', 'v13_goal_lifecycle(uuid)', 'EXECUTE')") is False)
    check("route fingerprint", q1(
        cur, "SELECT has_function_privilege('v13_route', 'v13_goal_fingerprint(uuid)', 'EXECUTE')") is True)
    check("public snapshot denied", q1(
        cur,
        "SELECT has_function_privilege('public', "
        "'v13_spawn_budget_snapshot(uuid,integer,uuid)', 'EXECUTE')") is False)
    check("route snapshot", q1(
        cur,
        "SELECT has_function_privilege('v13_route', "
        "'v13_spawn_budget_snapshot(uuid,integer,uuid)', 'EXECUTE')") is True)
    check("govern registered 29", STAGE_THROUGH["govern"] == 29)
    check("attention still 28", STAGE_THROUGH["attention"] == 28)
    check("default attention arg", "512" in q1(
        cur, "SELECT pg_get_function_arguments('v13_attention(uuid,integer)'::regprocedure)"))
    fails_with(cur, "SELECT count(*) FROM v13_attention(%s, 1025)", (u(),),
               "v13: attention limit", "attention 1025", exact=True)


def test_terminal_gate_priority(cur):
    sid = fresh(cur)
    stop(cur, sid)
    cur.execute("SELECT v13_cancel(%s)", (sid,))
    cur.fetchone()
    advance(cur, sid)
    check("terminal gate not goal_stopped",
          q1(cur, "SELECT v13_should_run_gate(%s)", (sid,)) != "goal_stopped")
    cur.execute(
        "SELECT blocked_by FROM v13_attention(%s) WHERE session_id=%s", (sid, sid))
    check("terminal attention blocked_by null", cur.fetchone()[0] is None)


def test_double_stop(server):
    conn = connect(server)
    cur = conn.cursor()
    sid = fresh(cur)
    conn.commit()
    box = {"err": None, "done": False}
    hold = connect(server)
    hc = hold.cursor()
    hc.execute("SELECT v13_goal_stop(%s, 'first')", (sid,))
    hc.fetchone()

    def second():
        c = connect(server)
        k = c.cursor()
        try:
            k.execute("SET lock_timeout = '8s'")
            k.execute("SELECT v13_goal_stop(%s, 'second')", (sid,))
            k.fetchone()
            box["done"] = True
            c.rollback()
        except psycopg2.Error as exc:
            box["err"] = exc.diag.message_primary
            c.rollback()
        finally:
            c.close()

    thread = threading.Thread(target=second)
    thread.start()
    time.sleep(0.3)
    hold.commit()
    thread.join(timeout=15)
    check("second stop lifecycle", box["err"] == "v13: goal lifecycle", box)
    check("double stop one event", n_events(cur, sid, "goal/stopped") == 1)
    conn.close()
    hold.close()


def test_policy_flip_blocks(server):
    hold = connect(server)
    hc = hold.cursor()
    sid = fresh(hc)
    hold.commit()
    a = connect(server)
    ac = a.cursor()
    ac.execute("SET ROLE v13_route")
    ac.execute("SELECT v13_spawn_batch_allowed(%s, 1)", (sid,))
    ac.fetchone()
    a_pid = q1(ac, "SELECT pg_backend_pid()")
    b = connect(server)
    bc = b.cursor()
    ver = next_ver()
    bc.execute(
        "INSERT INTO v13_policies (name, version, value, active) "
        "VALUES ('spawn_budget', %s, %s::jsonb, false)",
        (ver, json.dumps({"max_nonterminal": 1, "max_depth": 4, "max_fanout": 8})))
    box = {"err": None, "done": False}

    def run_b():
        try:
            bc.execute("SET lock_timeout = '12s'")
            bc.execute(
                "UPDATE v13_policies SET active=false WHERE name='spawn_budget' AND active")
            box["done"] = True
        except psycopg2.Error as exc:
            box["err"] = exc.diag.message_primary

    thread = threading.Thread(target=run_b)
    thread.start()
    seen = False
    obs = connect(server)
    obs.autocommit = True
    for _ in range(40):
        blockers = q1(obs.cursor(), "SELECT pg_blocking_pids(%s)", (
            q1(obs.cursor(), "SELECT pid FROM pg_stat_activity WHERE query LIKE %s AND pid <> %s",
               ("%spawn_budget%", a_pid)) or 0,)) or []
        if a_pid in blockers:
            seen = True
            break
        if box["done"] or box["err"]:
            break
        time.sleep(0.1)
    check("flip update blocked by share", seen, box)
    ac.execute(
        "SELECT v13_spawn_subsession(%s, %s::jsonb)",
        (sid, json.dumps({"schema_version": 1, "children": [{"tool_call_id": "ok", "task": "yes"}]})))
    ac.fetchone()
    a.commit()
    thread.join(timeout=15)
    check("flip update succeeds after commit", box["done"] and not box["err"], box)
    b.rollback()
    b.close()
    a.close()
    hold.close()
    obs.close()


def test_client_cancel(server):
    conn = connect(server)
    cur = conn.cursor()
    sid = fresh(cur)
    conn.commit()
    seq0 = next_seq(cur, sid)
    events = n_events(cur, sid)
    cur.execute(
        """
        CREATE FUNCTION public.v13_govern_sleep_guard() RETURNS trigger
        LANGUAGE plpgsql AS $fn$
        BEGIN
          PERFORM pg_sleep(30);
          RETURN NEW;
        END
        $fn$
        """)
    cur.execute(
        """
        CREATE TRIGGER trg_v13_govern_sleep
          BEFORE INSERT ON public.events
          FOR EACH ROW
          WHEN (NEW.type IN ('goal/stopped', 'goal/resumed'))
          EXECUTE FUNCTION public.v13_govern_sleep_guard()
        """)
    conn.commit()
    box = {"err": None, "pid": None}

    def run():
        c = connect(server)
        k = c.cursor()
        try:
            k.execute("SET statement_timeout = '15s'")
            k.execute("SELECT pg_backend_pid()")
            box["pid"] = k.fetchone()[0]
            k.execute("SELECT v13_goal_stop(%s, 'sleep')", (sid,))
            k.fetchone()
            c.rollback()
        except psycopg2.Error as exc:
            box["err"] = exc.diag.message_primary or exc.pgcode
            c.rollback()
        finally:
            c.close()

    thread = threading.Thread(target=run)
    thread.start()
    try:
        cancelled = False
        for _ in range(40):
            if box["pid"]:
                sleeping = q1(
                    cur,
                    "SELECT 1 FROM pg_stat_activity WHERE pid=%s AND wait_event='PgSleep'",
                    (box["pid"],))
                if sleeping:
                    cur.execute("SELECT pg_cancel_backend(%s)", (box["pid"],))
                    cancelled = True
                    break
            time.sleep(0.1)
        thread.join(timeout=20)
        check("client cancel fired", cancelled and box["err"] is not None, box)
        check("cancel restored seq", next_seq(cur, sid) == seq0)
        check("cancel restored events", n_events(cur, sid) == events)
    finally:
        try:
            conn.rollback()
        except psycopg2.Error:
            pass
        cur.execute("DROP TRIGGER IF EXISTS trg_v13_govern_sleep ON public.events")
        cur.execute("DROP FUNCTION IF EXISTS public.v13_govern_sleep_guard()")
        conn.commit()
        conn.close()


def test_revive_race(server):
    conn = connect(server)
    cur = conn.cursor()
    saved = q1(cur, "SELECT pg_get_functiondef('public.v13_spawn_occupancy(uuid)'::regprocedure)")
    cur.execute(
        """
        CREATE TABLE public.v13_occ_probe (n integer);
        GRANT ALL ON public.v13_occ_probe TO v13_spawn_owner, v13_route;
        """)
    flip_policy(cur, "spawn_budget", next_ver(),
                {"max_nonterminal": 1, "max_depth": 4, "max_fanout": 8})
    sid = fresh(cur)
    child = insert_one(cur, sid, "completed")
    project_calls(cur, sid, "answer", CALL)
    calls = n_events(cur, sid, "tool/call")
    kids = n_children(cur, sid)
    conn.commit()
    cur.execute(
        """
        CREATE OR REPLACE FUNCTION public.v13_spawn_occupancy(p_root uuid) RETURNS integer
        LANGUAGE plpgsql VOLATILE AS $fn$
        DECLARE
          v_n integer;
          v_cyc boolean;
          v_deep boolean;
        BEGIN
          SELECT count(*) FILTER (
                   WHERE NOT t.cyc AND s.status NOT IN ('completed', 'failed', 'cancelled')),
                 coalesce(bool_or(t.cyc), false),
                 coalesce(bool_or(t.d > 64), false)
            INTO v_n, v_cyc, v_deep
            FROM (
              WITH RECURSIVE tree AS (
                SELECT session_id, 1 AS d, ARRAY[session_id] AS path, false AS cyc
                  FROM sessions WHERE parent_session_id = p_root
                UNION ALL
                SELECT c.session_id, t.d + 1, t.path || c.session_id,
                       c.session_id = ANY (t.path)
                  FROM sessions c
                  JOIN tree t ON c.parent_session_id = t.session_id
                 WHERE NOT t.cyc AND t.d < 65
              )
              SELECT * FROM tree
            ) t
            JOIN sessions s ON s.session_id = t.session_id;
          IF coalesce(v_cyc, false) OR coalesce(v_deep, false) THEN
            RAISE EXCEPTION 'v13: spawn root cycle';
          END IF;
          IF NOT EXISTS (SELECT 1 FROM public.v13_occ_probe) THEN
            INSERT INTO public.v13_occ_probe VALUES (1);
            PERFORM pg_catalog.pg_advisory_xact_lock(13029, 29001);
            PERFORM pg_catalog.pg_advisory_xact_lock(13029, 29002);
            RETURN coalesce(v_n, 0);
          END IF;
          RETURN coalesce(v_n, 0);
        END
        $fn$
        """)
    conn.commit()
    coord = connect(server)
    coord.autocommit = True
    coord.cursor().execute("SELECT pg_advisory_lock(13029, 29002)")
    box = {"err": None, "word": None}
    a = {"pid": None}

    def run_a():
        c = connect(server)
        k = c.cursor()
        try:
            k.execute("SET statement_timeout = '20s'")
            k.execute("SET ROLE v13_route")
            k.execute("SELECT pg_backend_pid()")
            a["pid"] = k.fetchone()[0]
            k.execute(
                "UPDATE sessions SET context_active_revision = v13_context_required(session_id) "
                "WHERE session_id=%s", (sid,))
            k.execute("SELECT v13_probe(%s)", (sid,))
            probe = k.fetchone()[0]
            probe["sid"] = sid
            snap = {"snap": probe, "envelope": {"sid": sid}, "remaining": 0,
                    "failed": False, "abandon": False}
            k.execute("SELECT v13_advance(%s, %s::jsonb)", (sid, json.dumps(snap)))
            box["word"] = k.fetchone()[0]
            c.rollback()
        except psycopg2.Error as exc:
            box["err"] = exc.diag.message_primary
            c.rollback()
        finally:
            c.close()

    thread = threading.Thread(target=run_a)
    thread.start()
    try:
        seen = False
        for _ in range(50):
            if a["pid"]:
                granted = q1(
                    coord.cursor(),
                    "SELECT count(*) FROM pg_locks WHERE pid=%s AND locktype='advisory' "
                    "AND classid=13029 AND objid=29001 AND granted",
                    (a["pid"],))
                waiting = q1(
                    coord.cursor(),
                    "SELECT count(*) FROM pg_locks WHERE pid=%s AND locktype='advisory' "
                    "AND classid=13029 AND objid=29002 AND NOT granted",
                    (a["pid"],))
                if granted and waiting:
                    seen = True
                    break
            if box["err"] or box["word"]:
                break
            time.sleep(0.1)
        check("revive reached barrier", seen, box)
        b = connect(server)
        bc = b.cursor()
        bc.execute(
            "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
            (child, u(), json.dumps({"text": "revive"})))
        b.commit()
        b.close()
        coord.cursor().execute("SELECT pg_advisory_unlock(13029, 29002)")
        thread.join(timeout=20)
        check("revive raises cap", box["err"] == "v13: spawn budget cap", box)
        check("revive not swallowed", box["word"] != "waiting")
        check("revive children unchanged", n_children(cur, sid) == kids)
        check("revive calls unchanged", n_events(cur, sid, "tool/call") == calls)
    finally:
        try:
            coord.cursor().execute("SELECT pg_advisory_unlock(13029, 29002)")
        except psycopg2.Error:
            pass
        coord.close()
        thread.join(timeout=5)
        restore = connect(server)
        rc = restore.cursor()
        rc.execute(saved)
        rc.execute("DROP TABLE IF EXISTS public.v13_occ_probe")
        restore.commit()
        vol = q1(rc, "SELECT provolatile FROM pg_proc WHERE oid='public.v13_spawn_occupancy(uuid)'::regprocedure")
        check("occupancy restored stable", vol == "s", vol)
        restore.close()
        conn.close()


def test_spawn_still_progresses(cur):
    sid = fresh(cur)
    project_calls(cur, sid, "answer", CALL)
    word = advance(cur, sid, role="v13_route")
    check("budget ok still progressed", word == "progressed", word)
    check("budget ok has child", n_children(cur, sid) == 1)


def main() -> int:
    setup_db()
    server = get_server()
    conn = connect(server)
    cur = conn.cursor()
    try:
        test_goal_fold_empty_row(cur)
        test_fingerprint_equals_state_hash(cur)
        test_stop_changes_state_hash_not_fingerprint(cur)
        test_stop_payload(cur)
        test_lifecycle_transitions(cur, server)
        test_guard_spawn_owner_insert(cur)
        test_forged_negatives(cur)
        test_seq_negatives(cur)
        test_stop_blocks_enqueue(cur)
        test_stop_busy_matrix(cur)
        test_terminal_before_busy(cur)
        test_child_done_while_parent_stopped(cur)
        test_stop_then_finish_settles(cur)
        test_stop_max_cycles_not_failed(cur)
        test_explore_raise_survives_gate(cur)
        test_stopped_cancel_liveness(cur)
        test_handoff_after_stop_resume(cur)
        test_handoff_policy_regression(cur)
        test_recover_skip(cur)
        test_single_fold_body(cur)
        test_attention_lifecycle_rank(cur)
        test_hint_and_batch(cur)
        test_cap_skips_spawn(cur)
        test_fanout_and_depth_skip(cur)
        test_bad_policy_still_raises(cur)
        test_defer_with_finish(cur)
        test_cap_defer_continuation(cur)
        test_stale_then_waiting(cur)
        test_source_and_acl(cur)
        test_terminal_gate_priority(cur)
        test_spawn_still_progresses(cur)
        conn.rollback()
    finally:
        conn.close()
    test_non_operator_and_route(server)
    test_double_stop(server)
    test_policy_flip_blocks(server)
    test_client_cancel(server)
    test_revive_race(server)
    print(f"[govern] ALL PASS ({N})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
