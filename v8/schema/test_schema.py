"""G2 gate: v8 schema stage — frozen DDL, CHECKs, immutability triggers, key derivation.

Run: uv run python v8/schema/test_schema.py  (exit 0 = pass)

The golden hex vectors below were computed independently with python3's
hashlib (one-off shell runs during development) and hardcoded here on
purpose; the test must not reimplement the formulas in Python.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v8.schema.setup_db import DB, main as setup_db

# --- golden vectors (hand-computed with python3 -c hashlib, see docstring) ---
# v_event_key_streaming('11111111-2222-3333-4444-555555555555', 7, 'stream-abc', 42)
GOLDEN_STREAMING = "ca8b9ea920ae97be7d27ae6a858d406c145312911e27c5459edc2318fe54cab2"
# v_turn_end_key('3f1d2c90-7a44-4b8e-9f2a-6c0d1e5a7b92', 'd4c3b2a1-1234-5678-9abc-def012345678')
GOLDEN_TURN_END = "1269af6cde48a36c1ac4e32de7de37b042218a57b8f24715cf993883823d89be"
# v_nonstream_event_key(SID, 'user/message', 'cmd-9f', 13, 'a1b2c3d4')
GOLDEN_NONSTREAM = "c2fcc7c1525cddb0ff037eaedce1e3b564b9b007dec669ce21bac0166b9efd34"
# v_canonical_integer_bytes: 0 -> 0x30, 12345 -> b'12345', 2**62 -> b'4611686018427387904'
GOLDEN_CIB = {0: "30", 12345: "3132333435", 2**62: "34363131363836303138343237333837393034"}

SID = "3f1d2c90-7a44-4b8e-9f2a-6c0d1e5a7b92"
TID = "d4c3b2a1-1234-5678-9abc-def012345678"
EID = "11111111-2222-3333-4444-555555555555"


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f": {detail}" if detail else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def u() -> str:
    return str(uuid.uuid4())


def ok(cur, sql: str, params: tuple, label: str):
    cur.execute(sql, params)
    check(label, True)


def fails_with(cur, sql: str, params: tuple, needle: str, label: str) -> None:
    try:
        cur.execute(sql, params)
    except psycopg2.Error as exc:
        check(label, needle in str(exc).lower(), exc)
        return
    check(label, False, "statement unexpectedly succeeded")


def new_session(cur) -> str:
    s = u()
    cur.execute("INSERT INTO sessions(session_id, driver) VALUES (%s, 'drv')", (s,))
    return s


def new_step(cur, session_id: str, turn_id: str | None = None, status: str = "waiting_effect") -> str:
    st = u()
    t = turn_id or u()
    cur.execute(
        "INSERT INTO steps(step_id, session_id, turn_id, status, stage)"
        " VALUES (%s, %s, %s, %s, 'decision')",
        (st, session_id, t, status),
    )
    return st


def test_sessions(cur) -> None:
    ok(cur, "INSERT INTO sessions(session_id, driver) VALUES (%s, 'drv')", (SID,),
       "sessions minimal insert (defaults satisfy frozen initial state)")
    # Closed-set CHECKs are exercised via UPDATE: the BEFORE INSERT
    # initial-state trigger fires first on INSERT, so a bad state would be
    # reported as an initial-state violation rather than a CHECK violation.
    fails_with(
        cur,
        "UPDATE sessions SET state='RUNNING' WHERE session_id=%s",
        (SID,), "sessions_state_check", "sessions rejects closed-set state",
    )
    fails_with(
        cur,
        "UPDATE sessions SET driver_mode='paused' WHERE session_id=%s",
        (SID,), "sessions_driver_mode_check", "sessions rejects closed-set driver_mode",
    )
    fails_with(
        cur,
        "INSERT INTO sessions(session_id, driver, state) VALUES (%s, 'drv', 'claimed')",
        (u(),), "frozen initial state", "sessions rejects insert with non-ready state",
    )
    fails_with(
        cur,
        "INSERT INTO sessions(session_id, driver, next_seq) VALUES (%s, 'drv', 5)",
        (u(),), "frozen initial state", "sessions rejects insert with next_seq != 1",
    )
    fails_with(
        cur,
        "INSERT INTO sessions(session_id, driver, lease_owner) VALUES (%s, 'drv', 'w1')",
        (u(),), "frozen initial state", "sessions rejects insert holding a lease",
    )
    ok(cur, "UPDATE sessions SET state='claimed', lease_owner='w1', session_fence=2"
       " WHERE session_id=%s", (SID,), "sessions UPDATE state/lease/fence allowed")


def test_steps(cur) -> None:
    s = new_session(cur)
    st1 = new_step(cur, s)
    fails_with(
        cur,
        "INSERT INTO steps(step_id, session_id, turn_id, status, stage)"
        " VALUES (%s, %s, %s, 'running', 'decision')",
        (u(), s, u()), "steps_status_check", "steps rejects closed-set status",
    )
    fails_with(
        cur,
        "INSERT INTO steps(step_id, session_id, turn_id, status, stage)"
        " VALUES (%s, %s, %s, 'waiting_effect', 'sealed')",
        (u(), s, u()), "steps_stage_check", "steps rejects closed-set stage",
    )
    fails_with(
        cur,
        "INSERT INTO steps(step_id, session_id, turn_id, status, stage)"
        " VALUES (%s, %s, %s, 'ready', 'decision')",
        (u(), s, u()), "steps_one_active_per_session",
        "steps rejects a second non-terminal step per session",
    )
    ok(cur, "UPDATE steps SET status='succeeded', closed_at=now() WHERE step_id=%s",
       (st1,), "steps terminal update allowed")
    st2 = new_step(cur, s)
    check("steps new step allowed after previous one is terminal", bool(st2))


def test_session_events(cur) -> None:
    s = new_session(cur)
    ok(cur,
       "INSERT INTO session_events(seq, session_id, event_type, event_class,"
       " schema_version, canonicalizer_version, event_key, payload, payload_hash)"
       " VALUES (1, %s, 'assistant/chunk', 'observational', 'sv1', 'cv1', 'k1', '{}', 'h1')",
       (s,), "session_events observational insert")
    fails_with(
        cur, "UPDATE session_events SET payload='x' WHERE session_id=%s AND seq=1",
        (s,), "append-only", "session_events UPDATE rejected",
    )
    fails_with(
        cur, "DELETE FROM session_events WHERE session_id=%s AND seq=1",
        (s,), "append-only", "session_events DELETE rejected",
    )
    fails_with(
        cur,
        "INSERT INTO session_events(seq, session_id, event_type, event_class,"
        " schema_version, canonicalizer_version, event_key, payload, payload_hash)"
        " VALUES (2, %s, 'assistant/chunk', 'observational', 'sv1', 'cv1', 'k1', '{}', 'h1')",
        (s,), "duplicate", "session_events duplicate event_key rejected",
    )
    fails_with(
        cur,
        "INSERT INTO session_events(seq, session_id, event_type, event_class,"
        " schema_version, canonicalizer_version, event_key, payload, payload_hash)"
        " VALUES (1, %s, 'assistant/chunk', 'observational', 'sv1', 'cv1', 'k2', '{}', 'h1')",
        (s,), "duplicate", "session_events duplicate seq (PK) rejected",
    )
    fails_with(
        cur,
        "INSERT INTO session_events(seq, session_id, event_type, event_class,"
        " schema_version, canonicalizer_version, event_key, payload, payload_hash)"
        " VALUES (2, %s, 'user/message', 'semantic', 'sv1', 'cv1', 'k2', '{}', 'h1')",
        (s,), "session_events_ordinal_class_check",
        "session_events semantic row without either ordinal rejected",
    )
    fails_with(
        cur,
        "INSERT INTO session_events(seq, session_id, event_type, event_class,"
        " schema_version, canonicalizer_version, event_key, payload, payload_hash,"
        " semantic_input_ordinal, internal_semantic_ordinal)"
        " VALUES (2, %s, 'user/message', 'semantic', 'sv1', 'cv1', 'k2', '{}', 'h1', 1, 1)",
        (s,), "session_events_ordinal_class_check",
        "session_events semantic row with both ordinals rejected",
    )
    fails_with(
        cur,
        "INSERT INTO session_events(seq, session_id, event_type, event_class,"
        " schema_version, canonicalizer_version, event_key, payload, payload_hash,"
        " semantic_input_ordinal)"
        " VALUES (2, %s, 'assistant/chunk', 'observational', 'sv1', 'cv1', 'k2', '{}', 'h1', 1)",
        (s,), "session_events_ordinal_class_check",
        "session_events observational row with public ordinal rejected",
    )
    fails_with(
        cur,
        "INSERT INTO session_events(seq, session_id, event_type, event_class,"
        " schema_version, canonicalizer_version, event_key, payload, payload_hash,"
        " semantic_input_ordinal)"
        " VALUES (2, %s, 'user/message', 'semantic', 'sv1', 'cv1', 'k2', '{}', 'h1', 0)",
        (s,), "session_events_public_ordinal_range",
        "session_events public ordinal 0 rejected (range [1, 2^63-1])",
    )
    ok(cur,
       "INSERT INTO session_events(seq, session_id, event_type, event_class,"
       " schema_version, canonicalizer_version, event_key, payload, payload_hash,"
       " internal_semantic_ordinal)"
       " VALUES (2, %s, 'assistant/message', 'semantic', 'sv1', 'cv1', 'k2', '{}', 'h1', 1)",
       (s,), "session_events internal semantic row (internal ordinal only) accepted")
    ok(cur,
       "INSERT INTO session_events(seq, session_id, event_type, event_class,"
       " schema_version, canonicalizer_version, event_key, payload, payload_hash,"
       " semantic_input_ordinal, command_id, batch_item_ordinal)"
       " VALUES (3, %s, 'user/message', 'semantic', 'sv1', 'cv1', 'k3', '{}', 'h1', 1, 'c1', 0)",
       (s,), "session_events public semantic row (public ordinal only) accepted")
    fails_with(
        cur,
        "INSERT INTO session_events(seq, session_id, event_type, event_class,"
        " schema_version, canonicalizer_version, event_key, payload, payload_hash,"
        " semantic_input_ordinal)"
        " VALUES (4, %s, 'agent/inject', 'semantic', 'sv1', 'cv1', 'k4', '{}', 'h1', 1)",
        (s,), "session_events_public_ordinal",
        "session_events duplicate public ordinal rejected",
    )
    fails_with(
        cur,
        "INSERT INTO session_events(seq, session_id, event_type, event_class,"
        " schema_version, canonicalizer_version, event_key, payload, payload_hash,"
        " internal_semantic_ordinal)"
        " VALUES (4, %s, 'tool/result', 'semantic', 'sv1', 'cv1', 'k5', '{}', 'h1', 1)",
        (s,), "session_events_internal_ordinal",
        "session_events duplicate internal ordinal rejected",
    )


def test_batches(cur) -> None:
    s = new_session(cur)
    st = new_step(cur, s)
    b = u()
    ok(cur,
       "INSERT INTO batches(batch_id, session_id, step_id, sealed_batch_no, kind, sealed)"
       " VALUES (%s, %s, %s, 1, 'decision', true)",
       (b, s, st), "batches insert")
    fails_with(
        cur,
        "INSERT INTO batches(batch_id, session_id, step_id, sealed_batch_no, kind)"
        " VALUES (%s, %s, %s, 1, 'other')",
        (u(), s, st), "batches_kind_check", "batches rejects closed-set kind",
    )
    fails_with(
        cur,
        "INSERT INTO batches(batch_id, session_id, step_id, sealed_batch_no, kind)"
        " VALUES (%s, %s, %s, 1, 'tools')",
        (u(), s, st), "duplicate",
        "batches duplicate (session_id, step_id, sealed_batch_no) rejected",
    )


def _effect_fixture(cur) -> tuple[str, str, str, str]:
    s = new_session(cur)
    st = new_step(cur, s)
    b = u()
    cur.execute(
        "INSERT INTO batches(batch_id, session_id, step_id, sealed_batch_no, kind, sealed)"
        " VALUES (%s, %s, %s, 1, 'decision', true)",
        (b, s, st),
    )
    return s, st, b, u()


def _insert_effect(cur, s, st, b, e, ordinal=0, tool_call_id=None, **overrides):
    cols = {
        "execution_mode": "non_streaming",
        "driver": "drv",
        "driver_epoch": 1,
        "session_fence": 1,
        "dispatch_session_fence": 1,
        "current_job_fence": 1,
        "request_hash": "rh",
        "idempotency_key": "ik",
        "status": "ready",
        "retry_class": "unsafe",
        "max_attempts": 1,
        "effect_kind": "llm_decision",
    }
    cols.update(overrides)
    names = ["effect_id", "session_id", "step_id", "batch_id", "dispatch_ordinal"] + list(cols)
    vals = [e, s, st, b, ordinal] + list(cols.values())
    if tool_call_id is not None:
        names.append("tool_call_id")
        vals.append(tool_call_id)
    sql = "INSERT INTO effect_requests(" + ",".join(names) + ") VALUES (" + ",".join(["%s"] * len(vals)) + ")"
    cur.execute(sql, tuple(vals))


def test_effect_requests(cur) -> None:
    s, st, b, e1 = _effect_fixture(cur)
    _insert_effect(cur, s, st, b, e1)
    check("effect_requests insert", True)
    fails_with(
        cur,
        "INSERT INTO effect_requests(effect_id, session_id, step_id, batch_id,"
        " dispatch_ordinal, effect_kind, execution_mode, driver, driver_epoch,"
        " session_fence, dispatch_session_fence, current_job_fence, request_hash,"
        " idempotency_key, status, retry_class, max_attempts)"
        " VALUES (%s, %s, %s, %s, 0, 'llm_decision', 'non_streaming', 'drv', 1, 1, 1, 1,"
        " 'rh', 'ik', 'running', 'unsafe', 1)",
        (u(), s, st, b), "effect_requests_status_check",
        "effect_requests rejects closed-set status",
    )
    fails_with(
        cur,
        "INSERT INTO effect_requests(effect_id, session_id, step_id, batch_id,"
        " dispatch_ordinal, effect_kind, execution_mode, driver, driver_epoch,"
        " session_fence, dispatch_session_fence, current_job_fence, request_hash,"
        " idempotency_key, status, retry_class, max_attempts)"
        " VALUES (%s, %s, %s, %s, 0, 'llm_decision', 'async', 'drv', 1, 1, 1, 1,"
        " 'rh', 'ik', 'ready', 'unsafe', 1)",
        (u(), s, st, b), "effect_requests_execution_mode_check",
        "effect_requests rejects closed-set execution_mode",
    )
    fails_with(
        cur,
        "INSERT INTO effect_requests(effect_id, session_id, step_id, batch_id,"
        " dispatch_ordinal, effect_kind, execution_mode, driver, driver_epoch,"
        " session_fence, dispatch_session_fence, current_job_fence, request_hash,"
        " idempotency_key, status, retry_class, max_attempts)"
        " VALUES (%s, %s, %s, %s, 0, 'llm_decision', 'non_streaming', 'drv', 1, 1, 1, 1,"
        " 'rh', 'ik', 'ready', 'sometimes', 1)",
        (u(), s, st, b), "effect_requests_retry_class_check",
        "effect_requests rejects closed-set retry_class",
    )
    fails_with(
        cur, "UPDATE effect_requests SET execution_mode='streaming' WHERE effect_id=%s",
        (e1,), "immutable", "effect_requests frozen execution_mode UPDATE rejected",
    )
    fails_with(
        cur, "UPDATE effect_requests SET max_attempts=3 WHERE effect_id=%s",
        (e1,), "immutable", "effect_requests frozen max_attempts UPDATE rejected",
    )
    fails_with(
        cur, "UPDATE effect_requests SET request_hash='rh2' WHERE effect_id=%s",
        (e1,), "immutable", "effect_requests frozen request_hash UPDATE rejected",
    )
    ok(cur, "UPDATE effect_requests SET status='dispatch_started', dispatch_count=1"
       " WHERE effect_id=%s", (e1,), "effect_requests status/dispatch_count UPDATE allowed")
    fails_with(
        cur,
        "INSERT INTO effect_requests(effect_id, session_id, step_id, batch_id,"
        " dispatch_ordinal, effect_kind, execution_mode, driver, driver_epoch,"
        " session_fence, dispatch_session_fence, current_job_fence, request_hash,"
        " idempotency_key, status, retry_class, max_attempts)"
        " VALUES (%s, %s, %s, %s, 0, 'llm_decision', 'non_streaming', 'drv', 1, 1, 1, 1,"
        " 'rh', 'ik', 'ready', 'unsafe', 1)",
        (u(), s, st, b), "duplicate",
        "effect_requests duplicate slot (session, step, batch, dispatch_ordinal) rejected",
    )
    _insert_effect(cur, s, st, b, u(), ordinal=1, tool_call_id="tc1")
    fails_with(
        cur,
        "INSERT INTO effect_requests(effect_id, session_id, step_id, batch_id,"
        " dispatch_ordinal, tool_call_id, effect_kind, execution_mode, driver,"
        " driver_epoch, session_fence, dispatch_session_fence, current_job_fence,"
        " request_hash, idempotency_key, status, retry_class, max_attempts)"
        " VALUES (%s, %s, %s, %s, 2, 'tc1', 'tool_call', 'non_streaming', 'drv', 1, 1, 1, 1,"
        " 'rh', 'ik', 'ready', 'unsafe', 1)",
        (u(), s, st, b), "effect_requests_tool_slot",
        "effect_requests duplicate tool_call_id within batch rejected",
    )
    _insert_effect(cur, s, st, b, u(), ordinal=2, tool_call_id=None)
    check("effect_requests decision slot without tool_call_id accepted", True)


def _insert_attempt(cur, e, s, st, no, fence, **overrides):
    cols = {
        "driver": "drv",
        "driver_epoch": 1,
        "session_fence": 1,
        "dispatch_session_fence": 1,
        "request_hash": "rh",
        "idempotency_key": "ik",
        "execution_mode": "non_streaming",
        "status": "ready",
    }
    cols.update(overrides)
    names = ["effect_id", "attempt_no", "session_id", "step_id", "dispatch_job_fence"] + list(cols)
    vals = [e, no, s, st, fence] + list(cols.values())
    sql = "INSERT INTO effect_attempts(" + ",".join(names) + ") VALUES (" + ",".join(["%s"] * len(vals)) + ")"
    cur.execute(sql, tuple(vals))


def test_effect_attempts(cur) -> None:
    s, st, b, e = _effect_fixture(cur)
    _insert_effect(cur, s, st, b, e)
    _insert_attempt(cur, e, s, st, 1, 1)
    check("effect_attempts first attempt insert", True)
    fails_with(
        cur, "INSERT INTO effect_attempts(effect_id, attempt_no, session_id, step_id,"
        " dispatch_job_fence, driver, driver_epoch, session_fence, dispatch_session_fence,"
        " request_hash, idempotency_key, execution_mode, status)"
        " VALUES (%s, 0, %s, %s, 1, 'drv', 1, 1, 1, 'rh', 'ik', 'non_streaming', 'ready')",
        (e, s, st), "check", "effect_attempts rejects attempt_no = 0",
    )
    fails_with(
        cur, "INSERT INTO effect_attempts(effect_id, attempt_no, session_id, step_id,"
        " dispatch_job_fence, driver, driver_epoch, session_fence, dispatch_session_fence,"
        " request_hash, idempotency_key, execution_mode, status)"
        " VALUES (%s, 2, %s, %s, 2, 'drv', 1, 1, 1, 'rh', 'ik', 'non_streaming', 'weird')",
        (e, s, st), "effect_attempts_status_check",
        "effect_attempts rejects closed-set status",
    )
    # Composite FK: same effect_id but a session that does not own it.
    s_other = new_session(cur)
    st_other = new_step(cur, s_other)
    fails_with(
        cur, "INSERT INTO effect_attempts(effect_id, attempt_no, session_id, step_id,"
        " dispatch_job_fence, driver, driver_epoch, session_fence, dispatch_session_fence,"
        " request_hash, idempotency_key, execution_mode, status)"
        " VALUES (%s, 2, %s, %s, 2, 'drv', 1, 1, 1, 'rh', 'ik', 'non_streaming', 'ready')",
        (e, s_other, st_other), "foreign key",
        "effect_attempts cross effect-session-step ownership rejected",
    )
    fails_with(
        cur, "INSERT INTO effect_attempts(effect_id, attempt_no, session_id, step_id,"
        " dispatch_job_fence, superseded_by_attempt_no, driver, driver_epoch,"
        " session_fence, dispatch_session_fence, request_hash, idempotency_key,"
        " execution_mode, status)"
        " VALUES (%s, 2, %s, %s, 2, 2, 'drv', 1, 1, 1, 'rh', 'ik', 'non_streaming', 'ready')",
        (e, s, st), "effect_attempts_superseded_gt",
        "effect_attempts rejects superseded_by_attempt_no <= attempt_no",
    )
    # Deferred self-FK: successor attempt does not exist yet at commit time.
    fails_with(
        cur, "INSERT INTO effect_attempts(effect_id, attempt_no, session_id, step_id,"
        " dispatch_job_fence, superseded_by_attempt_no, driver, driver_epoch,"
        " session_fence, dispatch_session_fence, request_hash, idempotency_key,"
        " execution_mode, status)"
        " VALUES (%s, 2, %s, %s, 2, 5, 'drv', 1, 1, 1, 'rh', 'ik', 'non_streaming', 'ready')",
        (e, s, st), "foreign key",
        "effect_attempts superseded marker must reference a real successor attempt",
    )
    _insert_attempt(cur, e, s, st, 2, 2)
    check("effect_attempts second attempt insert", True)
    fails_with(
        cur, "INSERT INTO effect_attempts(effect_id, attempt_no, session_id, step_id,"
        " dispatch_job_fence, driver, driver_epoch, session_fence, dispatch_session_fence,"
        " request_hash, idempotency_key, execution_mode, status)"
        " VALUES (%s, 3, %s, %s, 2, 'drv', 1, 1, 1, 'rh', 'ik', 'non_streaming', 'ready')",
        (e, s, st), "duplicate",
        "effect_attempts duplicate (effect_id, dispatch_job_fence) rejected",
    )
    fails_with(
        cur, "UPDATE effect_attempts SET superseded_by_attempt_no=1"
        " WHERE effect_id=%s AND attempt_no=1",
        (e,), "effect_attempts_superseded_gt",
        "effect_attempts UPDATE superseded <= attempt_no rejected",
    )
    ok(cur, "UPDATE effect_attempts SET superseded_by_attempt_no=2"
       " WHERE effect_id=%s AND attempt_no=1", (e,),
       "effect_attempts first superseded write (NULL -> 2) allowed")
    fails_with(
        cur, "UPDATE effect_attempts SET superseded_by_attempt_no=3"
        " WHERE effect_id=%s AND attempt_no=1",
        (e,), "write-once",
        "effect_attempts superseded marker rewrite rejected (write-once)",
    )
    fails_with(
        cur, "UPDATE effect_attempts SET superseded_by_attempt_no=99"
        " WHERE effect_id=%s AND attempt_no=2",
        (e,), "foreign key",
        "effect_attempts superseded UPDATE to missing successor rejected",
    )
    fails_with(
        cur, "UPDATE effect_attempts SET dispatch_job_fence=9"
        " WHERE effect_id=%s AND attempt_no=2",
        (e,), "immutable",
        "effect_attempts frozen dispatch_job_fence UPDATE rejected",
    )
    fails_with(
        cur, "UPDATE effect_attempts SET execution_mode='streaming'"
        " WHERE effect_id=%s AND attempt_no=2",
        (e,), "immutable",
        "effect_attempts frozen execution_mode UPDATE rejected",
    )
    ok(cur, "UPDATE effect_attempts SET status='dispatch_started', dispatched_at=now()"
       " WHERE effect_id=%s AND attempt_no=2", (e,),
       "effect_attempts execution-authority UPDATE (status/dispatched_at) allowed")


def test_command_tables(cur) -> None:
    s = new_session(cur)
    ok(cur,
       "INSERT INTO command_receipts(session_id, command_id, command_kind,"
       " receipt_key_kind, receipt_key_value, outcome)"
       " VALUES (%s, 'cmd-1', 'append_events', 'canonical_request_hash', 'h1', 'accepted')",
       (s,), "command_receipts insert")
    fails_with(
        cur,
        "INSERT INTO command_receipts(session_id, command_id, receipt_key_kind,"
        " receipt_key_value, outcome)"
        " VALUES (%s, 'cmd-1', 'canonical_request_hash', 'h1', 'rejected_stale')",
        (s,), "duplicate",
        "command_receipts duplicate (session, command, key kind, key value) rejected",
    )
    fails_with(
        cur,
        "INSERT INTO command_receipts(session_id, command_id, receipt_key_kind,"
        " receipt_key_value, outcome)"
        " VALUES (%s, 'cmd-2', 'canonical_request_hash', 'h2', 'maybe')",
        (s,), "command_receipts_outcome_check",
        "command_receipts rejects closed-set outcome",
    )
    fails_with(
        cur,
        "INSERT INTO command_receipts(session_id, command_id, receipt_key_kind,"
        " receipt_key_value, outcome)"
        " VALUES (%s, 'cmd-3', 'magic_key', 'h3', 'accepted')",
        (s,), "command_receipts_key_kind_check",
        "command_receipts rejects closed-set receipt_key_kind",
    )
    ok(cur,
       "INSERT INTO command_bindings(session_id, command_id, first_key_kind,"
       " first_key_value, first_outcome)"
       " VALUES (%s, 'cmd-1', 'canonical_request_hash', 'h1', 'accepted')",
       (s,), "command_bindings insert")
    fails_with(
        cur,
        "INSERT INTO command_bindings(session_id, command_id, first_key_kind,"
        " first_key_value, first_outcome)"
        " VALUES (%s, 'cmd-1', 'canonical_request_hash', 'h9', 'rejected_mismatch')",
        (s,), "duplicate",
        "command_bindings duplicate (session, command) PK rejected",
    )
    fails_with(
        cur,
        "INSERT INTO command_bindings(session_id, command_id, first_key_kind,"
        " first_key_value, first_outcome)"
        " VALUES (%s, 'cmd-4', 'canonical_request_hash', 'h4', 'maybe')",
        (s,), "command_bindings_outcome_check",
        "command_bindings rejects closed-set first_outcome",
    )
    fails_with(
        cur,
        "INSERT INTO command_bindings(session_id, command_id, first_key_kind,"
        " first_key_value, first_outcome)"
        " VALUES (%s, 'cmd-5', 'magic_key', 'h5', 'accepted')",
        (s,), "command_bindings_key_kind_check",
        "command_bindings rejects closed-set first_key_kind",
    )


def test_turn_end_slots(cur) -> None:
    s = new_session(cur)
    ok(cur,
       "INSERT INTO turn_end_slots(session_id, turn_id, turn_end_key, head_event_key,"
       " slot_status, version)"
       " VALUES (%s, %s::uuid, v_turn_end_key(%s::uuid, %s::uuid), 'k1', 'provisional', 1)",
       (s, TID, s, TID), "turn_end_slots insert")
    fails_with(
        cur,
        "INSERT INTO turn_end_slots(session_id, turn_id, turn_end_key, head_event_key,"
        " slot_status, version)"
        " VALUES (%s, %s::uuid, v_turn_end_key(%s::uuid, %s::uuid), 'k2', 'provisional', 1)",
        (s, TID, s, TID), "duplicate",
        "turn_end_slots duplicate (session_id, turn_id) rejected",
    )
    fails_with(
        cur,
        "INSERT INTO turn_end_slots(session_id, turn_id, turn_end_key, head_event_key,"
        " slot_status, version)"
        " VALUES (%s, %s::uuid, v_turn_end_key(%s::uuid, %s::uuid), 'k2', 'open', 1)",
        (s, u(), s, u()), "turn_end_slots_status_check",
        "turn_end_slots rejects closed-set slot_status",
    )
    fails_with(
        cur, "UPDATE turn_end_slots SET version=2 WHERE session_id=%s", (s,),
        "protected slot update function",
        "turn_end_slots protected version UPDATE rejected",
    )
    fails_with(
        cur, "UPDATE turn_end_slots SET head_event_key='k9' WHERE session_id=%s", (s,),
        "protected slot update function",
        "turn_end_slots protected head_event_key UPDATE rejected",
    )
    fails_with(
        cur, "UPDATE turn_end_slots SET turn_end_key='other' WHERE session_id=%s", (s,),
        "immutable", "turn_end_slots turn_end_key UPDATE rejected",
    )
    cur.execute("SELECT set_config('v8.slot_protected_write', 'on', false)")
    cur.execute(
        "UPDATE turn_end_slots SET version=version+1, slot_status='known',"
        " head_event_key='k2' WHERE session_id=%s", (s,))
    cur.execute("SELECT set_config('v8.slot_protected_write', 'off', false)")
    check("turn_end_slots protected columns updatable under the protected-write GUC", True)


def test_effect_audit(cur) -> None:
    s = new_session(cur)
    base = (
        "INSERT INTO effect_audit(audit_context_session_id, audit_key_kind,"
        " audit_key_value, result_fingerprint, reason) "
    )
    ok(cur, base + "VALUES (%s, 'canonical_binding', 'kv1', 'fp1', 'why')", (s,),
       "effect_audit plain row (all attribution NULL) insert")
    fails_with(cur, base + "VALUES (%s, 'canonical_binding', 'kv1', 'fp1', 'why')", (s,),
               "duplicate",
               "effect_audit identical row with NULLs deduplicated (NULLS NOT DISTINCT)")
    fails_with(
        cur,
        "INSERT INTO effect_audit(audit_context_session_id, session_id, audit_key_kind,"
        " audit_key_value, result_fingerprint, reason)"
        " VALUES (%s, %s, 'canonical_binding', 'kv2', 'fp2', 'why')",
        (s, s), "effect_audit_attribution_all_or_none",
        "effect_audit partial attribution rejected",
    )
    fails_with(cur, base + "VALUES (%s, 'weird_binding', 'kv3', 'fp3', 'why')", (s,),
               "effect_audit_key_kind_check", "effect_audit rejects closed-set audit_key_kind")
    fails_with(
        cur,
        "INSERT INTO effect_audit(audit_context_session_id, audit_key_kind,"
        " audit_key_value, result_fingerprint, reason, internal_op_kind,"
        " parent_command_id, internal_op_ordinal)"
        " VALUES (%s, 'canonical_binding', 'kv4', 'fp4', 'why', 'failure_drain', 'pc', 0)",
        (s,), "effect_audit_internal_needs_attribution",
        "effect_audit internal row without full effect attribution rejected",
    )
    fails_with(
        cur,
        "INSERT INTO effect_audit(audit_context_session_id, session_id, step_id,"
        " effect_id, attempt_no, audit_key_kind, audit_key_value, result_fingerprint,"
        " reason, internal_op_kind)"
        " VALUES (%s, %s, %s, %s, 1, 'canonical_binding', 'kv5', 'fp5', 'why', 'infra_closure')",
        (s, s, u(), u()), "effect_audit_internal_triple_all_or_none",
        "effect_audit partial internal triple rejected",
    )
    fails_with(
        cur,
        "INSERT INTO effect_audit(audit_context_session_id, session_id, step_id,"
        " effect_id, attempt_no, audit_key_kind, audit_key_value, result_fingerprint,"
        " reason, internal_op_kind, parent_command_id, internal_op_ordinal)"
        " VALUES (%s, %s, %s, %s, 1, 'canonical_binding', 'kv6', 'fp6', 'why',"
        " 'infra_closure', 'pc', -1)",
        (s, s, u(), u()), "effect_audit_internal_triple_all_or_none",
        "effect_audit negative internal_op_ordinal rejected",
    )
    ok(cur,
       "INSERT INTO effect_audit(audit_context_session_id, session_id, step_id,"
       " effect_id, attempt_no, audit_key_kind, audit_key_value, result_fingerprint,"
       " reason, internal_op_kind, parent_command_id, internal_op_ordinal)"
       " VALUES (%s, %s, %s, %s, 1, 'canonical_binding', 'kv7', 'fp7', 'why',"
       " 'infra_closure', 'pc', 0)",
       (s, s, u(), u()), "effect_audit full internal row accepted")


def test_key_functions(cur) -> None:
    cur.execute("SELECT v_event_key_streaming(%s::uuid, %s, %s, %s)",
                (EID, 7, "stream-abc", 42))
    check("v_event_key_streaming golden vector", cur.fetchone()[0] == GOLDEN_STREAMING)

    cur.execute("SELECT v_turn_end_key(%s::uuid, %s::uuid)", (SID, TID))
    check("v_turn_end_key golden vector", cur.fetchone()[0] == GOLDEN_TURN_END)

    cur.execute("SELECT v_nonstream_event_key(%s::uuid, %s, %s, %s, %s)",
                (SID, "user/message", "cmd-9f", 13, "a1b2c3d4"))
    check("v_nonstream_event_key golden vector", cur.fetchone()[0] == GOLDEN_NONSTREAM)

    cur.execute("SELECT v_canonical_integer_bytes(0), v_canonical_integer_bytes(12345),"
                " v_canonical_integer_bytes(%s)", (2**62,))
    row = cur.fetchone()
    check("v_canonical_integer_bytes golden vectors",
          bytes(row[0]).hex() == GOLDEN_CIB[0]
          and bytes(row[1]).hex() == GOLDEN_CIB[12345]
          and bytes(row[2]).hex() == GOLDEN_CIB[2**62])

    cur.execute("SELECT v_u64be(1), v_len8('\\x00000000000000000000000000000000'::bytea),"
                " v_uuid16(%s::uuid), v_sha256_hex('abc')", (EID,))
    row = cur.fetchone()
    check("v_u64be(1) is 8-byte big-endian one", bytes(row[0]) == bytes.fromhex("0000000000000001"))
    check("v_len8 of 16-byte value is 8-byte big-endian sixteen",
          bytes(row[1]) == bytes.fromhex("0000000000000010"))
    check("v_uuid16 decodes RFC 9562 hex without hyphens",
          bytes(row[2]) == bytes.fromhex("11111111222233334444555555555555"))
    check("v_sha256_hex('abc') matches the standard SHA-256 vector",
          row[3] == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


def main() -> int:
    check("setup", setup_db() == 0)
    conn = psycopg2.connect(get_server().get_uri(DB))
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            test_sessions(cur)
            test_steps(cur)
            test_session_events(cur)
            test_batches(cur)
            test_effect_requests(cur)
            test_effect_attempts(cur)
            test_command_tables(cur)
            test_turn_end_slots(cur)
            test_effect_audit(cur)
            test_key_functions(cur)
    finally:
        conn.close()
    print("[G2] all gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
