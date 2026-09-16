"""G3 gate: v8 events stage — public append_events, command gate, canonicalizer.

Run: uv run python v8/events/test_events.py  (exit 0 = pass)
"""
from __future__ import annotations

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
from v8.canonical.keys import event_key_v1, nonstream_event_key
from v8.events.canonicalizer import CanonicalizerError, normalize
from v8.events.client import (
    build_entry,
    call_append_events,
    canonical_payload,
    create_session,
)
from v8.events.setup_db import DB, main as setup_db

SV, CV = "sv@1", "canon@1"
U64MAX = 9223372036854775807  # 2^63 - 1
HASH_OF_EMPTY = hashlib.sha256(b"{}").hexdigest()


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f": {detail}" if detail else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def u() -> str:
    return str(uuid.uuid4())


def _uri() -> str:
    return get_server().get_uri(DB)


def counts(cur, session_id: str) -> tuple[int, int]:
    cur.execute("SELECT count(*) FROM session_events WHERE session_id=%s", (session_id,))
    events = cur.fetchone()[0]
    cur.execute("SELECT next_seq FROM sessions WHERE session_id=%s", (session_id,))
    return events, cur.fetchone()[0]


def sem(event_type: str, payload: dict, turn_id: str, ordinal: int, **extra) -> dict:
    e = build_entry(event_type, payload, schema_version=SV, canonicalizer_version=CV,
                    turn_id=turn_id, semantic_input_ordinal=ordinal)
    e.update(extra)
    return e


def hb(payload: dict | None = None) -> dict:
    return build_entry("session/heartbeat", payload or {"beat": 1},
                       schema_version=SV, canonicalizer_version=CV)


# ---------------------------------------------------------------------------
# Command gate / receipt binding judgment order
# ---------------------------------------------------------------------------

def test_gate_hash_mismatch(conn) -> None:
    s = fresh_session(conn)
    turn = u()
    entries = [sem("user/message", {"text": "x"}, turn, 1)]
    r = call_append_events(conn, s, "cmd-mm", "drv", 1, 1, entries,
                           declared_hash="0" * 64)
    check("gate mismatch outcome", r["outcome"] == "rejected_mismatch", r)
    check("gate mismatch code", r["code"] == "REQUEST_HASH_MISMATCH", r["code"])
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM session_events WHERE session_id=%s", (s,))
        check("gate mismatch: zero events", cur.fetchone()[0] == 0)
        cur.execute("SELECT first_outcome FROM command_bindings"
                    " WHERE session_id=%s AND command_id='cmd-mm'", (s,))
        check("gate mismatch occupies binding with rejected_mismatch",
              cur.fetchone()[0] == "rejected_mismatch")
    # Correcting the declared hash on the SAME command_id must still replay
    # the original rejection (binding occupied; new command_id required).
    r2 = call_append_events(conn, s, "cmd-mm", "drv", 1, 1, entries)
    check("mismatch retry replays rejection",
          r2["outcome"] == "rejected_mismatch" and r2["code"] == "REQUEST_HASH_MISMATCH",
          r2)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM session_events WHERE session_id=%s", (s,))
        check("mismatch retry: still zero events", cur.fetchone()[0] == 0)
    # A new command_id executes the same payload.
    r3 = call_append_events(conn, s, "cmd-mm2", "drv", 1, 1, entries)
    check("new command_id executes after mismatch", r3["outcome"] == "accepted", r3)


def test_gate_command_conflict(conn) -> None:
    s = fresh_session(conn)
    turn = u()
    good = [sem("user/message", {"text": "a"}, turn, 1)]
    r1 = call_append_events(conn, s, "cmd-cf", "drv", 1, 1, good)
    check("conflict fixture accepted", r1["outcome"] == "accepted", r1)
    other = [sem("user/message", {"text": "different"}, turn, 2)]
    r2 = call_append_events(conn, s, "cmd-cf", "drv", 1, 2, other)
    check("same command_id different payload -> IDEMPOTENCY_CONFLICT",
          r2["outcome"] == "rejected_mismatch" and r2["code"] == "IDEMPOTENCY_CONFLICT",
          r2)
    with conn.cursor() as cur:
        cur.execute("SELECT first_key_kind, first_outcome FROM command_bindings"
                    " WHERE session_id=%s AND command_id='cmd-cf'", (s,))
        row = cur.fetchone()
        check("conflict does not touch first binding",
              row == ("canonical_request_hash", "accepted"), row)
    # Original accepted receipt still replays for the original payload.
    r3 = call_append_events(conn, s, "cmd-cf", "drv", 1, 1, good)
    check("accepted binding replays after conflict",
          r3["outcome"] == "accepted" and r3["receipt"] == r1["receipt"])
    # The conflicting variant replays its own conflict receipt.
    r4 = call_append_events(conn, s, "cmd-cf", "drv", 1, 2, other)
    check("conflict variant replays its conflict receipt",
          r4["outcome"] == "rejected_mismatch" and r4["code"] == "IDEMPOTENCY_CONFLICT")
    with conn.cursor() as cur:
        events, next_seq = counts(cur, s)
        check("conflict batch zero events, one stored total",
              events == 1 and next_seq == 2, (events, next_seq))


def test_driver_epoch_guard(conn) -> None:
    s = fresh_session(conn)
    turn = u()
    r = call_append_events(conn, s, "cmd-ep", "wrong-driver", 1, 1,
                           [sem("user/message", {"t": 1}, turn, 1)])
    check("driver mismatch -> rejected_stale",
          r["outcome"] == "rejected_stale" and r["code"] == "DRIVER_EPOCH_STALE", r)
    r = call_append_events(conn, s, "cmd-ep2", "drv", 7, 1,
                           [sem("user/message", {"t": 1}, turn, 1)])
    check("epoch mismatch -> rejected_stale",
          r["outcome"] == "rejected_stale" and r["code"] == "DRIVER_EPOCH_STALE", r)
    # NULL envelope legs fail closed (L4-U03: every write command MUST carry
    # driver/driver_epoch; an omitted field is a mismatch, never a pass).
    r = call_append_events(conn, s, "cmd-ep3", "drv", None, 1,
                           [sem("user/message", {"t": 1}, turn, 1)])
    check("epoch omitted (NULL) -> rejected_stale",
          r["outcome"] == "rejected_stale" and r["code"] == "DRIVER_EPOCH_STALE", r)
    r = call_append_events(conn, s, "cmd-ep4", None, 1, 1,
                           [sem("user/message", {"t": 1}, turn, 1)])
    check("driver omitted (NULL) -> rejected_stale",
          r["outcome"] == "rejected_stale" and r["code"] == "DRIVER_EPOCH_STALE", r)
    # After an epoch bump, the stale writer cannot sneak through by OMITTING
    # driver_epoch (the pre-fix NULL-unsafe comparison let it pass).
    with conn.cursor() as cur:
        cur.execute("UPDATE sessions SET driver_epoch=5 WHERE session_id=%s", (s,))
    conn.commit()
    r = call_append_events(conn, s, "cmd-ep5", "drv", 1, 1,
                           [sem("user/message", {"t": 1}, turn, 1)])
    check("old epoch after bump -> rejected_stale",
          r["outcome"] == "rejected_stale" and r["code"] == "DRIVER_EPOCH_STALE", r)
    r = call_append_events(conn, s, "cmd-ep6", "drv", None, 1,
                           [sem("user/message", {"t": 1}, turn, 1)])
    check("epoch omitted (NULL) after bump -> rejected_stale",
          r["outcome"] == "rejected_stale" and r["code"] == "DRIVER_EPOCH_STALE", r)
    with conn.cursor() as cur:
        events, next_seq = counts(cur, s)
        check("NULL-epoch guards stored zero events",
              events == 0 and next_seq == 1, (events, next_seq))


# ---------------------------------------------------------------------------
# Whitelist (digest 2.7)
# ---------------------------------------------------------------------------

def test_whitelist(conn) -> None:
    s = fresh_session(conn)
    turn = u()
    restricted = ["assistant/message", "tool/result", "heartbeat",
                  "attempt/heartbeat", "compat/unmapped"]
    for i, et in enumerate(restricted, start=1):
        entry = dict(sem("user/message", {"text": "x"}, turn, 1))
        entry["event_type"] = et
        r = call_append_events(conn, s, f"cmd-wl{i}", "drv", 1, i, [entry])
        check(f"restricted type {et} -> EVENT_TYPE_RESTRICTED",
              r["outcome"] == "rejected_mismatch" and r["code"] == "EVENT_TYPE_RESTRICTED",
              (r["outcome"], r["code"]))
    with conn.cursor() as cur:
        events, next_seq = counts(cur, s)
        check("all restricted batches: zero events, next_seq untouched",
              events == 0 and next_seq == 1, (events, next_seq))


# ---------------------------------------------------------------------------
# Attribution matrix X03 (envelope structural rejection, never a conflict)
# ---------------------------------------------------------------------------

def test_attribution_matrix(conn) -> None:
    s = fresh_session(conn)
    turn = u()
    step = u()
    cases = [
        ("no turn_id", {"turn_id": None}),
        ("step_id non-NULL", {"step_id": step}),
        ("effect_id non-NULL", {"effect_id": u()}),
    ]
    for i, (label, override) in enumerate(cases, start=1):
        entry = sem("user/message", {"text": "x"}, turn, i)
        entry.update(override)
        r = call_append_events(conn, s, f"cmd-am{i}", "drv", 1, i, [entry])
        check(f"attribution violation ({label}) -> ATTRIBUTION_MATRIX_VIOLATION",
              r["outcome"] == "rejected_mismatch"
              and r["code"] == "ATTRIBUTION_MATRIX_VIOLATION",
              (r["outcome"], r["code"]))
    with conn.cursor() as cur:
        events, next_seq = counts(cur, s)
        check("attribution violations: zero events, next_seq untouched",
              events == 0 and next_seq == 1, (events, next_seq))


# ---------------------------------------------------------------------------
# semantic_input_ordinal domain (L4-U01)
# ---------------------------------------------------------------------------

def test_ordinal_domain(conn) -> None:
    s = fresh_session(conn)
    turn = u()
    # missing ordinal -> envelope rejection
    entry = build_entry("user/message", {"text": "x"}, schema_version=SV,
                        canonicalizer_version=CV, turn_id=turn)
    entry.pop("semantic_input_ordinal")
    r = call_append_events(conn, s, "cmd-o0", "drv", 1, 1, [entry])
    check("missing semantic_input_ordinal rejected",
          r["code"] == "SEMANTIC_ORDINAL_MISSING", r["code"])
    # 0 -> out of range
    r = call_append_events(conn, s, "cmd-o00", "drv", 1, 1,
                           [sem("user/message", {"t": 0}, turn, 0)])
    check("ordinal 0 rejected", r["code"] == "SEMANTIC_ORDINAL_OUT_OF_RANGE",
          r["code"])
    # 2^63 -> out of range (beyond the canonical profile's tagged range, so
    # the request is hand-built and v_append_events called directly).
    with conn.cursor() as cur:
        big_entries = json.dumps([{
            "event_type": "user/message", "schema_version": SV,
            "canonicalizer_version": CV, "payload_canonical": '{"t":1}',
            "turn_id": turn, "step_id": None, "effect_id": None,
            "semantic_input_ordinal": U64MAX + 1}])
        cur.execute("SELECT outcome, code FROM v_append_events("
                    "%s::uuid, 'cmd-obig', 'drv', 1, 1, %s, '{}', %s::jsonb)",
                    (s, HASH_OF_EMPTY, big_entries))
        outcome, code = cur.fetchone()
        check("ordinal 2^63 rejected", outcome == "rejected_mismatch"
              and code == "SEMANTIC_ORDINAL_OUT_OF_RANGE", (outcome, code))
    # 1 accepted
    r = call_append_events(conn, s, "cmd-o1", "drv", 1, 1,
                           [sem("user/message", {"t": 1}, turn, 1)])
    check("ordinal 1 accepted", r["outcome"] == "accepted", r["outcome"])
    # 2^63-1 accepted via the tagged $int wire form
    r = call_append_events(conn, s, "cmd-omax", "drv", 1, 2,
                           [sem("user/message", {"t": 2}, turn, U64MAX)])
    check("ordinal 2^63-1 accepted", r["outcome"] == "accepted", r["outcome"])
    with conn.cursor() as cur:
        cur.execute("SELECT semantic_input_ordinal FROM session_events"
                    " WHERE session_id=%s AND semantic_input_ordinal=%s",
                    (s, U64MAX))
        check("ordinal 2^63-1 stored verbatim (caller value, never reassigned)",
              cur.fetchone() is not None)
        events, next_seq = counts(cur, s)
        check("ordinal domain: exactly two events", events == 2 and next_seq == 3,
              (events, next_seq))


# ---------------------------------------------------------------------------
# Idempotency: command-level replay, event-level dedup, merge, conflicts
# ---------------------------------------------------------------------------

def test_idempotency(conn) -> None:
    s = fresh_session(conn)
    turn = u()
    e1 = sem("turn/start", {"n": 1}, turn, 1)
    e2 = sem("user/message", {"text": "hi"}, turn, 2)

    r1 = call_append_events(conn, s, "cmd-a", "drv", 1, 1, [e1, e2])
    check("first batch accepted", r1["outcome"] == "accepted", r1["outcome"])
    check("first batch interval", r1["receipt"]["inserted"] ==
          {"first_seq": 1, "last_seq": 2, "count": 2}, r1["receipt"]["inserted"])

    # Same command_id retry: receipt (1) hit returns the ORIGINAL receipt.
    r2 = call_append_events(conn, s, "cmd-a", "drv", 1, 1, [e1, e2])
    check("same command_id retry replays original receipt",
          r2["outcome"] == "accepted" and r2["receipt"] == r1["receipt"])
    with conn.cursor() as cur:
        events, next_seq = counts(cur, s)
        check("retry stores nothing new", events == 2 and next_seq == 3,
              (events, next_seq))

    # New command_id, same ordinals, same content -> event-level idempotent,
    # existing seqs returned, no second row, next_seq not advanced.
    r3 = call_append_events(conn, s, "cmd-b", "drv", 1, 1, [e1, e2])
    check("cross-command duplicate batch accepted", r3["outcome"] == "accepted")
    check("duplicate batch maps to existing seqs",
          [it["seq"] for it in r3["receipt"]["items"]] == [1, 2]
          and all(it["disposition"] == "existing" for it in r3["receipt"]["items"]),
          r3["receipt"]["items"])
    check("duplicate batch inserts nothing (empty interval)",
          r3["receipt"]["inserted"] is None, r3["receipt"]["inserted"])

    # Same ordinal, different content (same payload but different event_type;
    # different payload; different schema_version) -> whole-batch conflict.
    for i, mutant in enumerate([
        sem("agent/inject", {"text": "hi"}, turn, 2),
        sem("user/message", {"text": "CHANGED"}, turn, 2),
        {**sem("user/message", {"text": "hi"}, turn, 2), "schema_version": "sv@2"},
    ], start=1):
        r = call_append_events(conn, s, f"cmd-c{i}", "drv", 1, 3, [mutant])
        check(f"same-ordinal mutant #{i} -> IDEMPOTENCY_CONFLICT",
              r["outcome"] == "rejected_mismatch" and r["code"] == "IDEMPOTENCY_CONFLICT",
              (r["outcome"], r["code"]))

    # In-batch merge: same ordinal, identical five-part domain -> one event,
    # both input positions map to the same new event_key/seq (F2).
    m1 = sem("user/message", {"text": "merged"}, turn, 3)
    m2 = sem("user/message", {"text": "merged"}, turn, 3)
    r4 = call_append_events(conn, s, "cmd-d", "drv", 1, 3, [m1, m2])
    check("in-batch merge accepted", r4["outcome"] == "accepted", r4["outcome"])
    items = r4["receipt"]["items"]
    check("merge maps both positions to the same seq",
          len(items) == 2 and items[0]["seq"] == items[1]["seq"]
          and items[0]["event_key"] == items[1]["event_key"]
          and items[1]["disposition"] == "merged", items)
    check("merge counts one inserted event",
          r4["receipt"]["inserted"] == {"first_seq": 3, "last_seq": 3, "count": 1},
          r4["receipt"]["inserted"])
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM session_events WHERE session_id=%s"
                    " AND semantic_input_ordinal=3", (s,))
        check("merge stored exactly one row for ordinal 3", cur.fetchone()[0] == 1)

    # Mixed batch: existing hit + in-batch merge + brand new — atomic, with a
    # contiguous no-hole interval.
    mixed = [
        sem("turn/start", {"n": 1}, turn, 1),           # existing (seq 1)
        sem("user/message", {"text": "x"}, turn, 4),    # new (rep)
        sem("user/message", {"text": "x"}, turn, 4),    # merged onto rep
        sem("user/message", {"text": "y"}, turn, 5),    # new
    ]
    r5 = call_append_events(conn, s, "cmd-e", "drv", 1, 4, mixed)
    check("mixed batch accepted", r5["outcome"] == "accepted", r5["outcome"])
    seqs = [it["seq"] for it in r5["receipt"]["items"]]
    check("mixed batch: existing seq + contiguous new interval",
          seqs[0] == 1 and seqs[1] == seqs[2] == 4 and seqs[3] == 5, seqs)
    check("mixed batch interval count 2",
          r5["receipt"]["inserted"] == {"first_seq": 4, "last_seq": 5, "count": 2},
          r5["receipt"]["inserted"])

    # Mid-batch conflict: a valid new entry followed by two same-ordinal
    # entries with different content -> whole batch rejected atomically,
    # next_seq untouched.
    before_events, before_next = None, None
    with conn.cursor() as cur:
        before_events, before_next = counts(cur, s)
    bad_batch = [
        sem("user/message", {"text": "ok"}, turn, 6),
        sem("user/message", {"text": "clash-a"}, turn, 7),
        sem("user/message", {"text": "clash-b"}, turn, 7),
    ]
    r6 = call_append_events(conn, s, "cmd-f", "drv", 1, before_next, bad_batch)
    check("mid-batch conflict -> whole-batch IDEMPOTENCY_CONFLICT",
          r6["outcome"] == "rejected_mismatch" and r6["code"] == "IDEMPOTENCY_CONFLICT",
          (r6["outcome"], r6["code"]))
    with conn.cursor() as cur:
        events, next_seq = counts(cur, s)
        check("mid-batch conflict: zero rows, next_seq unchanged",
              events == before_events and next_seq == before_next,
              (events, next_seq))


# ---------------------------------------------------------------------------
# expected seq special case (L4-U-R01)
# ---------------------------------------------------------------------------

def test_expected_seq(conn) -> None:
    s = fresh_session(conn)
    turn = u()
    e1 = sem("user/message", {"text": "1"}, turn, 1)
    r = call_append_events(conn, s, "cmd-s1", "drv", 1, 1, [e1])
    check("expected-seq fixture accepted", r["outcome"] == "accepted")

    # All-duplicate batch with a stale expected seq: NOT checked, accepted,
    # next_seq not advanced.
    r2 = call_append_events(conn, s, "cmd-s2", "drv", 1, 1, [e1])
    check("all-duplicate batch skips expected-seq check",
          r2["outcome"] == "accepted", (r2["outcome"], r2["code"]))

    # Batch containing a NEW entry with a wrong expected seq -> rejected_stale.
    r3 = call_append_events(conn, s, "cmd-s3", "drv", 1, 99,
                            [e1, sem("user/message", {"text": "2"}, turn, 2)])
    check("new-entry batch with stale expected seq -> rejected_stale",
          r3["outcome"] == "rejected_stale" and r3["code"] == "EXPECTED_SEQ_MISMATCH",
          (r3["outcome"], r3["code"]))
    with conn.cursor() as cur:
        events, next_seq = counts(cur, s)
        check("stale batch: zero new rows, next_seq unchanged",
              events == 1 and next_seq == 2, (events, next_seq))


# ---------------------------------------------------------------------------
# Batch staging table isolation (pg_temp qualification)
# ---------------------------------------------------------------------------

def test_permanent_table_shadow(conn) -> None:
    # A same-named PERMANENT table must survive append_events: the batch
    # staging table is pg_temp-qualified in DROP/CREATE/INSERT/SELECT, so
    # the leading DROP TABLE IF EXISTS can never resolve through
    # search_path to (and silently destroy) public.v8_batch_items.
    with conn.cursor() as cur:
        cur.execute("CREATE TABLE public.v8_batch_items (marker text)")
        cur.execute("INSERT INTO public.v8_batch_items VALUES ('keep-me')")
    conn.commit()
    try:
        s = fresh_session(conn)
        turn = u()
        r = call_append_events(conn, s, "cmd-sh1", "drv", 1, 1,
                               [sem("user/message", {"text": "shadow"}, turn, 1)])
        check("append works with a permanent v8_batch_items present",
              r["outcome"] == "accepted", r)
        # Second call on the SAME connection: the ON COMMIT DROP staging
        # table is gone again, so the DROP re-runs against an empty temp
        # schema — exactly the state where the unqualified form was
        # destructive.
        r2 = call_append_events(conn, s, "cmd-sh2", "drv", 1, 2, [hb({"n": 1})])
        check("second append (heartbeat) accepted", r2["outcome"] == "accepted", r2)
        with conn.cursor() as cur:
            cur.execute("SELECT count(*), min(marker) FROM public.v8_batch_items")
            check("permanent v8_batch_items untouched (row survives)",
                  cur.fetchone() == (1, "keep-me"))
            cur.execute("SELECT count(*) FROM session_events WHERE session_id=%s", (s,))
            check("both appends stored their events", cur.fetchone()[0] == 2)
        conn.commit()
    finally:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS public.v8_batch_items")
        conn.commit()


# ---------------------------------------------------------------------------
# Defensive unique-index escape: in-lock re-read and (4)/(5) classification
# ---------------------------------------------------------------------------

# Session-level advisory lock key parking connection B's first insert.
_ESC_LOCK_KEY = 87254177


def _wait_for_advisory_waiter(conn, pid: int, timeout: float = 10.0) -> bool:
    """True once backend `pid` is blocked waiting on an advisory lock."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT wait_event IS NOT NULL AND wait_event = 'advisory'"
                " FROM pg_stat_activity WHERE pid = %s", (pid,))
            row = cur.fetchone()
        conn.rollback()
        if row and row[0]:
            return True
        time.sleep(0.05)
    return False


def _run_unique_escape(conn, uri: str, entry: dict, session_id: str,
                       racer_payload: str) -> dict:
    """One two-connection unique-index escape repro.

    The lock+FK discipline hermetically closes the escape window for
    well-formed writers (every session_events insert takes a KEY SHARE on
    the sessions row that the in-flight append's FOR UPDATE blocks), so the
    abnormal-timing writer is manufactured deliberately: the FK is dropped
    for the duration of the repro, connection B (thread) runs
    append_events for the entry while a BEFORE INSERT trigger parks B's
    first insert on the session-level advisory lock held by the driver,
    and the driver then commits — WITHOUT the session row lock — a
    conflicting row for the same ordinal (payload ``racer_payload``)
    before releasing the park. B's insert hits
    UNIQUE(session_id, semantic_input_ordinal): the in-function escape.
    The FK is restored (validated) in cleanup.
    """
    holder: dict = {}
    bconn = psycopg2.connect(uri)

    def run_b():
        try:
            with bconn.cursor() as cur:
                cur.execute("SELECT pg_backend_pid()")
                holder["pid"] = cur.fetchone()[0]
            bconn.commit()
            holder["result"] = call_append_events(
                bconn, session_id, "cmd-esc", "drv", 1, 1, [entry])
        except BaseException as exc:  # surfaced in the main thread
            holder["error"] = exc
        finally:
            bconn.close()

    # Park B's insert of the cmd-esc row on the advisory lock; drop the FK
    # so the racer can write past B's held session row lock.
    with conn.cursor() as cur:
        cur.execute("ALTER TABLE session_events"
                    " DROP CONSTRAINT session_events_session_id_fkey")
        cur.execute("""
            CREATE OR REPLACE FUNCTION v8_test_esc_block() RETURNS trigger
            LANGUAGE plpgsql AS $fn$
            BEGIN
                IF NEW.command_id = 'cmd-esc' THEN
                    PERFORM pg_advisory_lock(%d);
                END IF;
                RETURN NEW;
            END
            $fn$;""" % _ESC_LOCK_KEY)
        cur.execute("CREATE TRIGGER trg_v8_test_esc BEFORE INSERT ON session_events"
                    " FOR EACH ROW EXECUTE FUNCTION v8_test_esc_block()")
        cur.execute("SELECT pg_advisory_lock(%s)", (_ESC_LOCK_KEY,))
    conn.commit()

    thread = threading.Thread(target=run_b, daemon=True)
    thread.start()
    parked = False
    pid = None
    try:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and pid is None:
            pid = holder.get("pid")
            if pid is None:
                time.sleep(0.02)
        parked = pid is not None and _wait_for_advisory_waiter(conn, pid)
        if parked:
            racer_hash = hashlib.sha256(racer_payload.encode()).hexdigest()
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO session_events("
                    " seq, session_id, event_type, event_class, schema_version,"
                    " canonicalizer_version, event_key, turn_id, step_id, effect_id,"
                    " payload, payload_hash, semantic_input_ordinal,"
                    " internal_semantic_ordinal, attempt_no, command_id,"
                    " batch_item_ordinal)"
                    " VALUES (1, %s::uuid, 'user/message', 'semantic', %s, %s,"
                    "  v_nonstream_event_key(%s::uuid, 'user/message',"
                    "  'esc-other', 0, %s),"
                    "  %s::uuid, NULL, NULL, %s, %s, 1, NULL, NULL, 'esc-other', 0)",
                    (session_id, entry["schema_version"],
                     entry["canonicalizer_version"], session_id, racer_hash,
                     entry["turn_id"], racer_payload, racer_hash))
            conn.commit()
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", (_ESC_LOCK_KEY,))
            conn.commit()
    finally:
        # Release the park FIRST so B can always run to completion (dropping
        # the trigger while B is parked deadlocks: DROP TRIGGER needs
        # AccessExclusiveLock on session_events, which B's in-flight INSERT
        # holds); join B; then clean up and RESTORE the FK (validated).
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (_ESC_LOCK_KEY,))
        conn.commit()
        thread.join(timeout=30)
        with conn.cursor() as cur:
            cur.execute("DROP TRIGGER IF EXISTS trg_v8_test_esc ON session_events")
            cur.execute("DROP FUNCTION IF EXISTS v8_test_esc_block()")
            cur.execute(
                "ALTER TABLE session_events ADD CONSTRAINT"
                " session_events_session_id_fkey"
                " FOREIGN KEY (session_id) REFERENCES sessions(session_id)")
        conn.commit()
    check("escape fixture: B parked on the advisory lock", parked, pid)
    check("escape fixture: B finished without error", "error" not in holder,
          holder.get("error"))
    return holder["result"]


def test_unique_escape_idempotent(conn) -> None:
    # Identical five-part form: the escape re-reads the racer's row inside
    # the lock and returns the EXISTING identity/seq — not a conflict.
    s = fresh_session(conn)
    turn = u()
    entry = sem("user/message", {"text": "race"}, turn, 1)
    r = _run_unique_escape(conn, _uri(), entry, s, entry["payload_canonical"])
    check("identical racer: escape returns accepted (idempotent)",
          r["outcome"] == "accepted", r)
    item = r["receipt"]["items"][0]
    check("receipt maps the input to the EXISTING identity",
          item["disposition"] == "existing" and item["seq"] == 1, item)
    check("identical racer: empty inserted interval",
          r["receipt"]["inserted"] is None, r["receipt"]["inserted"])
    with conn.cursor() as cur:
        cur.execute("SELECT event_key FROM session_events WHERE session_id=%s", (s,))
        stored_key = cur.fetchone()[0]
        check("existing identity is the racer's stored event_key",
              item["event_key"] == stored_key, (item["event_key"], stored_key))
        events, next_seq = counts(cur, s)
        check("identical racer: exactly one event, next_seq untouched",
              events == 1 and next_seq == 1, (events, next_seq))
        cur.execute("SELECT first_outcome FROM command_bindings"
                    " WHERE session_id=%s AND command_id='cmd-esc'", (s,))
        check("identical racer: binding occupied with accepted",
              cur.fetchone()[0] == "accepted")
    conn.commit()


def test_unique_escape_conflict(conn) -> None:
    # Different five-part form (payload differs): the escape classifies
    # IDEMPOTENCY_CONFLICT, zero new events, first binding free for this
    # command_id to record the rejection.
    s = fresh_session(conn)
    turn = u()
    entry = sem("user/message", {"text": "race"}, turn, 1)
    racer_payload = json.dumps({"text": "DIFFERENT"}, separators=(",", ":"))
    r = _run_unique_escape(conn, _uri(), entry, s, racer_payload)
    check("differing racer: escape classifies IDEMPOTENCY_CONFLICT",
          r["outcome"] == "rejected_mismatch" and r["code"] == "IDEMPOTENCY_CONFLICT",
          (r["outcome"], r["code"]))
    with conn.cursor() as cur:
        events, next_seq = counts(cur, s)
        check("differing racer: only the racer's event, next_seq untouched",
              events == 1 and next_seq == 1, (events, next_seq))
        cur.execute("SELECT first_outcome FROM command_bindings"
                    " WHERE session_id=%s AND command_id='cmd-esc'", (s,))
        check("differing racer: binding occupied with rejected_mismatch",
              cur.fetchone()[0] == "rejected_mismatch")
    conn.commit()


# ---------------------------------------------------------------------------
# seq no-hole invariant across batches
# ---------------------------------------------------------------------------

def test_seq_no_holes(conn) -> None:
    s = fresh_session(conn)
    turn = u()
    expected = 1
    for i in range(1, 6):
        r = call_append_events(conn, s, f"cmd-h{i}", "drv", 1, expected,
                               [sem("user/message", {"i": i}, turn, i),
                                hb({"i": i})])
        check(f"no-hole batch {i} accepted", r["outcome"] == "accepted",
              (r["outcome"], r["code"]))
        expected += 2
    with conn.cursor() as cur:
        cur.execute("SELECT seq FROM session_events WHERE session_id=%s"
                    " ORDER BY seq", (s,))
        seqs = [row[0] for row in cur.fetchall()]
        check("seq continuity 1..10 with no holes",
              seqs == list(range(1, 11)), seqs)


# ---------------------------------------------------------------------------
# SQL/Python byte-level cross-checks
# ---------------------------------------------------------------------------

def test_cross_check_keys(conn) -> None:
    s = fresh_session(conn)
    turn = u()
    entries = [sem("user/message", {"text": "cross"}, turn, 1)]
    r = call_append_events(conn, s, "cmd-x1", "drv", 1, 1, entries)
    check("cross-check fixture accepted", r["outcome"] == "accepted")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT session_id::text, event_type, command_id, batch_item_ordinal,"
            " payload_hash, payload FROM session_events WHERE session_id=%s", (s,))
        row_sid, row_type, row_cmd, row_ord, row_hash, row_payload = cur.fetchone()
        cur.execute("SELECT v_nonstream_event_key(%s::uuid, %s, %s, %s, %s)",
                    (row_sid, row_type, row_cmd, row_ord, row_hash))
        sql_key = cur.fetchone()[0]
        cur.execute("SELECT v_sha256_hex(%s)", (row_payload,))
        sql_hash = cur.fetchone()[0]
    py_key = nonstream_event_key(row_sid, row_type, row_cmd, row_ord, row_hash)
    check("v_nonstream_event_key == keys.nonstream_event_key (byte parity)",
          sql_key == py_key, (sql_key, py_key))
    check("stored event_key equals the derived key",
          r["receipt"]["items"][0]["event_key"] == py_key)
    py_text, py_hash = canonical_payload({"text": "cross"})
    check("SQL v_sha256_hex(payload) == Python canonicalize hash",
          sql_hash == py_hash and row_payload == py_text, (sql_hash, py_hash))

    # Streaming key parity on an appended chunk.
    s2, _, effect = chunk_fixture(conn, dispatched=True)
    entry = build_entry("assistant/chunk", {"text": "ab"}, schema_version=SV,
                        canonicalizer_version=CV, effect_id=effect, attempt_no=1,
                        stream_id="stream-x", chunk_index=0)
    r2 = call_append_events(conn, s2, "cmd-x2", "drv", 1, 1, [entry])
    check("chunk fixture accepted", r2["outcome"] == "accepted", r2)
    with conn.cursor() as cur:
        cur.execute("SELECT event_key FROM session_events WHERE session_id=%s",
                    (s2,))
        sql_key2 = cur.fetchone()[0]
    check("stored streaming event_key == keys.event_key_v1",
          sql_key2 == event_key_v1(effect, 1, "stream-x", 0), sql_key2)


# ---------------------------------------------------------------------------
# assistant/chunk: six-item validation (reachable items) + idempotency
# ---------------------------------------------------------------------------

def chunk_fixture(conn, dispatched: bool = True) -> tuple[str, str, str]:
    s = u()
    with conn.cursor() as cur:
        cur.execute("SELECT v_create_session(%s::uuid, 'drv')", (s,))
        turn, step, batch, effect = u(), u(), u(), u()
        cur.execute(
            "INSERT INTO steps(step_id, session_id, turn_id, status, stage)"
            " VALUES (%s, %s, %s, 'waiting_effect', 'decision')", (step, s, turn))
        cur.execute(
            "INSERT INTO batches(batch_id, session_id, step_id, sealed_batch_no,"
            " kind, sealed) VALUES (%s, %s, %s, 1, 'decision', true)",
            (batch, s, step))
        cur.execute(
            "INSERT INTO effect_requests(effect_id, session_id, step_id, batch_id,"
            " dispatch_ordinal, effect_kind, execution_mode, driver, driver_epoch,"
            " session_fence, dispatch_session_fence, current_job_fence,"
            " request_hash, idempotency_key, status, retry_class, max_attempts,"
            " dispatched_at)"
            " VALUES (%s, %s, %s, %s, 0, 'llm_decision', 'streaming', 'drv', 1,"
            " 1, 1, 1, 'rh', 'ik', %s, 'unsafe', 1, %s)",
            (effect, s, step, batch,
             "dispatch_started" if dispatched else "ready",
             "now()" if dispatched else None))
        cur.execute(
            "INSERT INTO effect_attempts(effect_id, attempt_no, session_id,"
            " step_id, dispatch_job_fence, driver, driver_epoch, session_fence,"
            " dispatch_session_fence, request_hash, idempotency_key,"
            " execution_mode, status)"
            " VALUES (%s, 1, %s, %s, 1, 'drv', 1, 1, 1, 'rh', 'ik',"
            " 'streaming', %s)",
            (effect, s, step, "dispatch_started" if dispatched else "ready"))
    conn.commit()
    return s, turn, effect


def chunk_entry(effect: str, text: str, index: int, attempt: int = 1,
                stream: str = "s1") -> dict:
    return build_entry("assistant/chunk", {"text": text}, schema_version=SV,
                       canonicalizer_version=CV, effect_id=effect,
                       attempt_no=attempt, stream_id=stream, chunk_index=index)


def test_chunks(conn) -> None:
    # Unknown effect -> item (1) rejection.
    s = fresh_session(conn)
    r = call_append_events(conn, s, "cmd-ch0", "drv", 1, 1,
                           [chunk_entry(u(), "x", 0)])
    check("chunk with unknown effect -> CHUNK_ATTRIBUTION_INVALID",
          r["code"] == "CHUNK_ATTRIBUTION_INVALID", r["code"])

    # Effect not yet dispatched -> item (4) rejection.
    s2, _, effect2 = chunk_fixture(conn, dispatched=False)
    r = call_append_events(conn, s2, "cmd-ch4", "drv", 1, 1,
                           [chunk_entry(effect2, "x", 0)])
    check("chunk before dispatch -> CHUNK_ATTRIBUTION_INVALID",
          r["code"] == "CHUNK_ATTRIBUTION_INVALID", r["code"])

    # Wrong attempt_no -> item (2) rejection.
    s3, _, effect3 = chunk_fixture(conn, dispatched=True)
    r = call_append_events(conn, s3, "cmd-ch2", "drv", 1, 1,
                           [chunk_entry(effect3, "x", 0, attempt=2)])
    check("chunk with non-current attempt -> CHUNK_ATTRIBUTION_INVALID",
          r["code"] == "CHUNK_ATTRIBUTION_INVALID", r["code"])

    # Happy path + idempotency + conflict on the dispatched fixture.
    s4, _, effect4 = chunk_fixture(conn, dispatched=True)
    r1 = call_append_events(conn, s4, "cmd-ch1", "drv", 1, 1,
                            [chunk_entry(effect4, "Hel", 0),
                             chunk_entry(effect4, "lo", 1)])
    check("chunk batch accepted", r1["outcome"] == "accepted", r1)
    check("chunk batch interval",
          r1["receipt"]["inserted"]["count"] == 2, r1["receipt"]["inserted"])

    # Same four-tuple, same content, NEW command_id -> idempotent dedup.
    r2 = call_append_events(conn, s4, "cmd-ch1b", "drv", 1, 3,
                            [chunk_entry(effect4, "Hel", 0)])
    check("same four-tuple same content -> idempotent",
          r2["outcome"] == "accepted"
          and [it["seq"] for it in r2["receipt"]["items"]] == [1]
          and r2["receipt"]["inserted"] is None, r2["receipt"])

    # Same four-tuple, different content -> CANONICALIZER_CONFLICT.
    r3 = call_append_events(conn, s4, "cmd-ch1c", "drv", 1, 3,
                            [chunk_entry(effect4, "DIFFERENT", 0)])
    check("same four-tuple different content -> CANONICALIZER_CONFLICT",
          r3["outcome"] == "rejected_mismatch"
          and r3["code"] == "CANONICALIZER_CONFLICT", (r3["outcome"], r3["code"]))
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM session_events WHERE session_id=%s", (s4,))
        check("chunk conflict: no second row", cur.fetchone()[0] == 2)

    # In-batch duplicate four-tuple with equal content merges.
    r4 = call_append_events(conn, s4, "cmd-ch1d", "drv", 1, 3,
                            [chunk_entry(effect4, "lo", 1),
                             chunk_entry(effect4, "lo", 1)])
    check("in-batch identical chunk merges",
          r4["outcome"] == "accepted"
          and r4["receipt"]["items"][0]["seq"] == r4["receipt"]["items"][1]["seq"]
          and r4["receipt"]["inserted"] is None, r4["receipt"])

    # Out-of-order arrival with gaps is legal (2,0 accepted after 1).
    r5 = call_append_events(conn, s4, "cmd-ch1e", "drv", 1, 3,
                            [chunk_entry(effect4, "x", 2)])
    check("out-of-order chunk accepted", r5["outcome"] == "accepted", r5["outcome"])
    with conn.cursor() as cur:
        cur.execute("SELECT turn_id IS NOT NULL, step_id IS NOT NULL,"
                    " effect_id IS NOT NULL, semantic_input_ordinal IS NULL,"
                    " attempt_no FROM session_events WHERE session_id=%s"
                    " ORDER BY seq LIMIT 1", (s4,))
        row = cur.fetchone()
        check("chunk rows carry effect-derived turn/step attribution and no"
              " public ordinal",
              row == (True, True, True, True, 1), row)


# ---------------------------------------------------------------------------
# session/heartbeat
# ---------------------------------------------------------------------------

def test_heartbeat(conn) -> None:
    s = fresh_session(conn)
    r = call_append_events(conn, s, "cmd-hb", "drv", 1, 1, [hb({"n": 1})])
    check("session/heartbeat accepted", r["outcome"] == "accepted", r["outcome"])
    with conn.cursor() as cur:
        cur.execute(
            "SELECT event_class, turn_id, step_id, effect_id,"
            " semantic_input_ordinal FROM session_events WHERE session_id=%s",
            (s,))
        row = cur.fetchone()
        check("heartbeat row: observational, all attribution NULL,"
              " no semantic ordinal",
              row == ("observational", None, None, None, None), row)
        cur.execute("SELECT next_seq FROM sessions WHERE session_id=%s", (s,))
        check("heartbeat advanced next_seq", cur.fetchone()[0] == 2)


# ---------------------------------------------------------------------------
# Terminal session (Q03, this stage's simplified terminal set)
# ---------------------------------------------------------------------------

def test_terminal(conn) -> None:
    s = fresh_session(conn)
    turn = u()
    call_append_events(conn, s, "cmd-t0", "drv", 1, 1,
                       [sem("user/message", {"t": 1}, turn, 1)])
    with conn.cursor() as cur:
        cur.execute("UPDATE sessions SET state='completed' WHERE session_id=%s", (s,))
    conn.commit()

    r = call_append_events(conn, s, "cmd-t1", "drv", 1, 2,
                           [sem("user/message", {"t": 2}, turn, 2)])
    check("semantic append on terminal -> SESSION_TERMINAL",
          r["outcome"] == "rejected_mismatch" and r["code"] == "SESSION_TERMINAL",
          (r["outcome"], r["code"]))
    r = call_append_events(conn, s, "cmd-t2", "drv", 1, 2, [hb()])
    check("heartbeat on terminal -> SESSION_TERMINAL",
          r["code"] == "SESSION_TERMINAL", r["code"])

    # Matrix (c): a late, validly-attributed assistant/chunk still lands.
    s2, _, effect = chunk_fixture(conn, dispatched=True)
    with conn.cursor() as cur:
        cur.execute("UPDATE sessions SET state='cancelled' WHERE session_id=%s", (s2,))
    conn.commit()
    r = call_append_events(conn, s2, "cmd-t3", "drv", 1, 1,
                           [chunk_entry(effect, "tail", 5)])
    check("late valid chunk on terminal accepted (matrix (c))",
          r["outcome"] == "accepted", (r["outcome"], r["code"]))
    with conn.cursor() as cur:
        events, _ = counts(cur, s)
        check("terminal semantic rejection stored nothing new", events == 1)


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def fresh_session(conn) -> str:
    s = u()
    create_session(conn, s, "drv")
    return s


def test_create_session(conn) -> None:
    s = u()
    check("create_session creates", create_session(conn, s, "drv2") is True)
    check("create_session idempotent", create_session(conn, s, "drv2") is False)
    with conn.cursor() as cur:
        cur.execute("SELECT state, driver_mode, session_fence, driver_epoch,"
                    " next_seq, cancellation_epoch FROM sessions WHERE session_id=%s",
                    (s,))
        check("frozen initial state row",
              cur.fetchone() == ("ready", "active", 1, 1, 1, 0))
        try:
            cur.execute("INSERT INTO sessions(session_id, driver, next_seq)"
                        " VALUES (%s, 'd', 9)", (u(),))
            check("trigger still rejects non-initial rows", False, "insert succeeded")
        except psycopg2.Error as exc:
            check("trigger still rejects non-initial rows",
                  "frozen initial state" in str(exc))
        finally:
            conn.rollback()


# ---------------------------------------------------------------------------
# Canonicalizer (pure Python)
# ---------------------------------------------------------------------------

def ends_of(trace: list[dict]) -> list[dict]:
    return [e for e in trace if e["event_type"] == "turn/end"]


def test_canonicalizer_normal_turn() -> None:
    t = "turn-1"
    trace = normalize([
        {"event_type": "turn/start", "payload": {"n": 1}, "turn_id": t,
         "semantic_input_ordinal": 1},
        {"event_type": "user/message", "payload": {"text": "hi"}, "turn_id": t,
         "semantic_input_ordinal": 2},
        {"event_type": "assistant/message", "payload": {"text": "yo"},
         "turn_id": t, "effect_id": "e1", "effect_status": "succeeded"},
        {"event_type": "turn/end", "payload": {"interrupted": False}, "turn_id": t},
    ])
    ends = ends_of(trace)
    check("normal turn: exactly one end", len(ends) == 1, trace)
    check("normal turn: end payload {interrupted:false}",
          ends and ends[0]["payload"] == {"interrupted": False}, ends)
    check("normal turn: semantic order (start, user, assistant)",
          [e["event_type"] for e in trace] ==
          ["turn/start", "user/message", "assistant/message", "turn/end"],
          [e["event_type"] for e in trace])


def test_canonicalizer_unknown_provisional() -> None:
    t = "turn-2"
    trace = normalize([
        {"event_type": "user/message", "payload": {"text": "?"},
         "turn_id": t, "semantic_input_ordinal": 1},
        {"event_type": "tool/result", "payload": {"output": None},
         "turn_id": t, "effect_id": "e9", "effect_status": "unknown_outcome",
         "code": "UNKNOWN_AFTER_DISPATCH"},
        {"event_type": "turn/end", "payload": {"outcome": "unknown"}, "turn_id": t},
    ])
    ends = ends_of(trace)
    check("unknown: exactly one end", len(ends) == 1)
    check("unknown: provisional end payload",
          ends and ends[0]["payload"] ==
          {"outcome": "unknown", "reason": "unknown_after_dispatch"}, ends)
    check("unknown: effect-level unknown representation retained",
          any(e["event_type"] == "tool/result" and
              e["payload"].get("output") is None for e in trace))


def test_canonicalizer_eligibility_guard() -> None:
    t = "turn-3"
    trace = normalize([
        {"event_type": "user/message", "payload": {"text": "g"},
         "turn_id": t, "semantic_input_ordinal": 1},
        {"event_type": "assistant/message", "payload": {"text": "done"},
         "turn_id": t, "effect_id": "e1", "effect_status": "succeeded"},
        {"event_type": "tool/call", "payload": {"tool": "t"},
         "turn_id": t, "effect_id": "e2", "effect_status": "pending"},
        {"event_type": "turn/end", "payload": {"interrupted": False}, "turn_id": t},
    ])
    check("guard: pending effect suppresses the known end",
          ends_of(trace) == [], trace)
    trace2 = normalize([
        {"event_type": "user/message", "payload": {"text": "g"},
         "turn_id": t, "semantic_input_ordinal": 1},
        {"event_type": "assistant/message", "payload": {"text": "done"},
         "turn_id": t, "effect_id": "e1", "effect_status": "succeeded",
         "unsealed_tools_plan": True},
        {"event_type": "turn/end", "payload": {"interrupted": False}, "turn_id": t},
    ])
    check("guard: unsealed tools plan suppresses the known end",
          ends_of(trace2) == [], trace2)


def test_canonicalizer_reason_priority() -> None:
    t = "turn-4"
    trace = normalize([
        {"event_type": "user/message", "payload": {"text": "p"},
         "turn_id": t, "semantic_input_ordinal": 1},
        {"event_type": "assistant/message", "payload": {"text": "partial"},
         "turn_id": t, "effect_id": "e1", "effect_status": "cancelled_after_dispatch",
         "code": "CANCELLED_BY_PROVIDER"},
        {"event_type": "tool/result", "payload": {}, "turn_id": t,
         "effect_id": "e2", "effect_status": "cancelled_after_dispatch",
         "code": "CANCELLED_BY_REQUEST_AFTER_DISPATCH"},
    ])
    ends = ends_of(trace)
    check("sticky beats provider cancellation",
          len(ends) == 1 and ends[0]["payload"] ==
          {"interrupted": True, "reason": "cancelled_by_request_after_dispatch"},
          ends)

    t2 = "turn-5"
    trace2 = normalize([
        {"event_type": "user/message", "payload": {}, "turn_id": t2,
         "semantic_input_ordinal": 1, "sticky_cancel": True},
        {"event_type": "tool/call", "payload": {}, "turn_id": t2,
         "effect_id": "e3", "effect_status": "cancelled_before_dispatch",
         "code": "ABORTED_BEFORE_DISPATCH"},
    ])
    ends2 = ends_of(trace2)
    check("pre-dispatch sticky cancel -> cancelled_by_request_before_dispatch",
          len(ends2) == 1 and ends2[0]["payload"] ==
          {"interrupted": True, "reason": "cancelled_by_request_before_dispatch"},
          ends2)

    t3 = "turn-6"
    trace3 = normalize([
        {"event_type": "user/message", "payload": {}, "turn_id": t3,
         "semantic_input_ordinal": 1},
        {"event_type": "tool/result", "payload": {}, "turn_id": t3,
         "effect_id": "e4", "effect_status": "failed_terminal"},
    ])
    ends3 = ends_of(trace3)
    check("terminal failure -> {interrupted:true, reason:failed}",
          len(ends3) == 1 and ends3[0]["payload"] ==
          {"interrupted": True, "reason": "failed"}, ends3)


def test_canonicalizer_chunk_merge() -> None:
    t = "turn-7"
    chunks = [
        {"event_type": "assistant/chunk", "payload": {"text": "C"},
         "turn_id": t, "effect_id": "e5", "attempt_no": 1, "stream_id": "s1",
         "chunk_index": 2},
        {"event_type": "assistant/chunk", "payload": {"text": "A"},
         "turn_id": t, "effect_id": "e5", "attempt_no": 1, "stream_id": "s1",
         "chunk_index": 0},
        {"event_type": "assistant/chunk", "payload": {"text": "B"},
         "turn_id": t, "effect_id": "e5", "attempt_no": 1, "stream_id": "s1",
         "chunk_index": 1},
    ]
    # No final, succeeded closing decision (decision_only) -> merged prefix
    # plus the missing_final candidate.
    trace = normalize(chunks + [
        {"event_type": "user/message", "payload": {"text": "m"},
         "turn_id": t, "semantic_input_ordinal": 1},
        {"event_type": "tool/result", "payload": {}, "turn_id": t,
         "effect_id": "e5", "effect_status": "succeeded",
         "decision_only": True},
    ])
    partials = [e for e in trace if e["event_type"] == "assistant/partial"]
    check("out-of-order chunks merge in chunk_index order",
          len(partials) == 1 and partials[0]["payload"]["text"] == "ABC",
          partials)
    ends = ends_of(trace)
    check("missing_final candidate end",
          len(ends) == 1 and ends[0]["payload"] ==
          {"incomplete": True, "reason": "missing_final"}, ends)

    # With a final assistant/message present the chunks drop entirely.
    trace2 = normalize(chunks + [
        {"event_type": "assistant/message", "payload": {"text": "ABC"},
         "turn_id": t, "effect_id": "e5", "effect_status": "succeeded"},
    ])
    check("chunks dropped when a final assistant/message exists",
          not any(e["event_type"] == "assistant/partial" for e in trace2)
          and any(e["event_type"] == "assistant/message" for e in trace2),
          trace2)


def test_canonicalizer_fail_closed() -> None:
    for label, events, code in [
        ("unknown event_type",
         [{"event_type": "misc/other", "payload": {}, "turn_id": "t"}],
         "CANONICALIZER_UNSUPPORTED"),
        ("two streams in one attempt",
         [{"event_type": "assistant/chunk", "payload": {"text": "a"},
           "turn_id": "t", "effect_id": "e", "attempt_no": 1,
           "stream_id": "s1", "chunk_index": 0},
          {"event_type": "assistant/chunk", "payload": {"text": "b"},
           "turn_id": "t", "effect_id": "e", "attempt_no": 1,
           "stream_id": "s2", "chunk_index": 0}],
         "CANONICALIZER_UNSUPPORTED"),
        ("same four-tuple different content",
         [{"event_type": "assistant/chunk", "payload": {"text": "a"},
           "turn_id": "t", "effect_id": "e", "attempt_no": 1,
           "stream_id": "s1", "chunk_index": 0},
          {"event_type": "assistant/chunk", "payload": {"text": "ZZ"},
           "turn_id": "t", "effect_id": "e", "attempt_no": 1,
           "stream_id": "s1", "chunk_index": 0}],
         "CANONICALIZER_CONFLICT"),
    ]:
        try:
            normalize(events)
            check(f"fail-closed: {label}", False, "normalize succeeded")
        except CanonicalizerError as exc:
            check(f"fail-closed: {label}", exc.code == code, exc.code)

    # Uniqueness: identical logical input in a different raw arrival order
    # still normalizes to the same trace (chunks reorder; heartbeats tag along).
    base = [
        {"event_type": "turn/start", "payload": {}, "turn_id": "t",
         "semantic_input_ordinal": 1},
        {"event_type": "user/message", "payload": {"text": "q"},
         "turn_id": "t", "semantic_input_ordinal": 2},
        {"event_type": "assistant/message", "payload": {"text": "r"},
         "turn_id": "t", "effect_id": "e", "effect_status": "succeeded"},
        {"event_type": "turn/end", "payload": {"interrupted": False},
         "turn_id": "t"},
        {"event_type": "session/heartbeat", "payload": {"n": 1}},
    ]
    t1 = normalize(base)
    t2 = normalize(list(reversed(base)))
    check("normalize: arrival-order independence for the logical input",
          t1 == t2, (t1, t2))


def main() -> int:
    check("setup", setup_db() == 0)
    conn = psycopg2.connect(get_server().get_uri(DB))
    try:
        test_create_session(conn)
        test_gate_hash_mismatch(conn)
        test_gate_command_conflict(conn)
        test_driver_epoch_guard(conn)
        test_whitelist(conn)
        test_attribution_matrix(conn)
        test_ordinal_domain(conn)
        test_idempotency(conn)
        test_expected_seq(conn)
        test_permanent_table_shadow(conn)
        test_unique_escape_idempotent(conn)
        test_unique_escape_conflict(conn)
        test_seq_no_holes(conn)
        test_cross_check_keys(conn)
        test_chunks(conn)
        test_heartbeat(conn)
        test_terminal(conn)
    finally:
        conn.close()

    test_canonicalizer_normal_turn()
    test_canonicalizer_unknown_provisional()
    test_canonicalizer_eligibility_guard()
    test_canonicalizer_reason_priority()
    test_canonicalizer_chunk_merge()
    test_canonicalizer_fail_closed()

    print("[G3] all gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
