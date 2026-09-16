"""G17 gate: v8 compact — the three controlled commands (§3.3).

Run: uv run python v8/compact/test_compact.py  (exit 0 = pass)
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
from v8.compact.client import compact_abort, compact_finalize, compact_lock
from v8.compact.setup_db import DB, main as setup_db
from v8.effect.client import (
    claim_session,
    complete_effect,
    dispatch_effect,
    prepare_step,
)
from v8.events.client import build_entry, call_append_events, create_session
from v8.grant.fixtures import seed_stage_grants, u

SV, CV = "sv@1", "canon@1"
EPOCH = 1
DRIVER = "drv"


def _uri() -> str:
    return get_server().get_uri(DB)


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f": {detail}" if detail else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def _p(params):
    # psycopg2 does not adapt a bare uuid.UUID; the stage fixtures pass the
    # textual form, so coerce here.
    return tuple(str(x) if isinstance(x, uuid.UUID) else x for x in params)


def one(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, _p(params))
        row = cur.fetchone()
    conn.commit()
    return row


def rows(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, _p(params))
        out = cur.fetchall()
    conn.commit()
    return out


def exec_sql(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, _p(params))
    conn.commit()


def good_evidence() -> dict:
    return {"class": "known_success",
            "provider_receipt": {"receipt_id": f"rc-{u()[:8]}"}}


def idle_session(conn, driver: str = DRIVER) -> dict:
    """A claimed session with NO non-terminal effect (compact-eligible)."""
    s = uuid.uuid4()
    create_session(conn, s, driver)
    r0 = claim_session(conn, s, driver)
    check("fx claim ok", r0["outcome"] == "claimed", r0)
    return {"session": s, "fence": r0["session_fence"]}


def busy_session(conn, driver: str = DRIVER) -> dict:
    """A session with an in-flight (dispatch_started) LLM effect."""
    s = uuid.uuid4()
    turn, step, eff = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    rh, ik = f"rh-{u()[:10]}", f"ik-{u()[:10]}"
    create_session(conn, s, driver)
    r0 = claim_session(conn, s, driver)
    rs = prepare_step(conn, s, f"seal-{u()[:8]}", driver, EPOCH,
                      r0["session_fence"], step, turn, eff,
                      request_hash=rh, idempotency_key=ik)
    check("fx decision seal accepted", rs["outcome"] == "accepted", rs)
    rd = dispatch_effect(conn, s, f"dsp-{u()[:8]}", eff, driver, EPOCH,
                         rs["receipt"]["session_fence"],
                         rs["receipt"]["job_fence"])
    check("fx dispatch accepted", rd["outcome"] == "accepted", rd)
    return {"session": s, "fence": r0["session_fence"], "step": step,
            "effect": eff, "rh": rh, "ik": ik,
            "seal_fence": rs["receipt"]["session_fence"],
            "job_fence": rs["receipt"]["job_fence"]}


# ---------------------------------------------------------------------------
# 1. D1 — the frozen compactions DDL
# ---------------------------------------------------------------------------

def test_table_shape(conn) -> None:
    # Frozen column set, verbatim (digest s33 §1.1).
    cols = [r[0] for r in rows(conn,
        "SELECT column_name FROM information_schema.columns"
        " WHERE table_name='compactions' ORDER BY ordinal_position")]
    check("D1 frozen column list",
          cols == ["session_id", "compaction_id", "base_seq", "through_seq",
                   "status", "owner_fence", "lease_owner", "lease_until",
                   "result_identity", "abort_identity", "created_at",
                   "updated_at"], cols)

    fx = idle_session(conn)
    # State-condition binding: finalized requires result_identity and forbids
    # abort_identity; a locked row forbids both.
    try:
        exec_sql(conn,
            "INSERT INTO compactions(session_id, compaction_id, base_seq,"
            " through_seq, status, owner_fence, result_identity)"
            " VALUES (%s, 'bad-fin', 0, 0, 'finalized', 1, NULL)",
            (fx["session"],))
        ok = False
    except psycopg2.Error:
        conn.rollback()
        ok = True
    check("D1 state binding: finalized without result_identity rejected", ok)

    try:
        exec_sql(conn,
            "INSERT INTO compactions(session_id, compaction_id, base_seq,"
            " through_seq, status, owner_fence, result_identity,"
            " abort_identity) VALUES (%s, 'bad-both', 0, 0, 'finalized', 1,"
            " 'r', 'a')", (fx["session"],))
        ok = False
    except psycopg2.Error:
        conn.rollback()
        ok = True
    check("D1 state binding: finalized with abort_identity rejected", ok)

    # Partial unique index: at most one locked row per session.
    exec_sql(conn,
        "INSERT INTO compactions(session_id, compaction_id, base_seq,"
        " through_seq, status, owner_fence) VALUES (%s, 'lock-1', 0, 0,"
        " 'locked', 1)", (fx["session"],))
    try:
        exec_sql(conn,
            "INSERT INTO compactions(session_id, compaction_id, base_seq,"
            " through_seq, status, owner_fence) VALUES (%s, 'lock-2', 0, 0,"
            " 'locked', 1)", (fx["session"],))
        ok = False
    except psycopg2.Error:
        conn.rollback()
        ok = True
    check("D1 one locked row per session (partial unique index)", ok)

    # base_seq/through_seq are frozen after creation.
    try:
        exec_sql(conn, "UPDATE compactions SET through_seq = 99"
                       " WHERE session_id=%s AND compaction_id='lock-1'",
                 (fx["session"],))
        ok = False
    except psycopg2.Error:
        conn.rollback()
        ok = True
    check("D1 base_seq/through_seq immutable after creation", ok)

    # Rows MUST NOT be deleted (replay locator).
    try:
        exec_sql(conn, "DELETE FROM compactions WHERE session_id=%s",
                 (fx["session"],))
        ok = False
    except psycopg2.Error:
        conn.rollback()
        ok = True
    check("D1 terminal/locked rows MUST NOT be deleted", ok)


# ---------------------------------------------------------------------------
# 2. D2 — compact_lock
# ---------------------------------------------------------------------------

def test_compact_lock(conn) -> None:
    # (a) an active non-terminal LLM effect rejects with COMPACT_BUSY_EFFECTS
    # and zero control state.
    fx = busy_session(conn)
    r = compact_lock(conn, fx["session"], f"clk-{u()[:8]}", DRIVER, EPOCH,
                     "cmp-busy")
    check("D2 lock with in-flight LLM effect -> COMPACT_BUSY_EFFECTS",
          r["outcome"] == "rejected_mismatch"
          and r["code"] == "COMPACT_BUSY_EFFECTS", r)
    check("D2 rejection leaves zero control state",
          rows(conn, "SELECT count(*) FROM compactions WHERE session_id=%s",
               (fx["session"],))[0][0] == 0)

    # (b) happy path: idle -> locked, freezes the range, returns identity.
    fx2 = idle_session(conn)
    r2 = compact_lock(conn, fx2["session"], f"clk-{u()[:8]}", DRIVER, EPOCH,
                      "cmp-ok")
    check("D2 idle -> locked accepted",
          r2["outcome"] == "accepted"
          and r2["receipt"]["compaction_id"] == "cmp-ok", r2)
    check("D2 lock row is locked with both identity columns NULL",
          one(conn, "SELECT status, result_identity, abort_identity"
                    " FROM compactions WHERE session_id=%s",
              (fx2["session"],)) == ("locked", None, None))
    check("D2 compaction/start audit event written",
          one(conn, "SELECT count(*) FROM session_events WHERE session_id=%s"
                    " AND event_type='compaction/start'"
                    " AND event_class='audit'",
              (fx2["session"],))[0] == 1)

    # (c) a second lock with the SAME compaction_id is an idempotent
    # re-entry; a different one is a parameter conflict.
    r3 = compact_lock(conn, fx2["session"], f"clk-{u()[:8]}", DRIVER, EPOCH,
                      "cmp-ok")
    check("D2 same compaction_id re-entry returns the held lock",
          r3["outcome"] == "accepted"
          and r3["receipt"]["compaction_id"] == "cmp-ok", r3)
    r4 = compact_lock(conn, fx2["session"], f"clk-{u()[:8]}", DRIVER, EPOCH,
                      "cmp-other")
    check("D2 different compaction_id while locked -> IDEMPOTENCY_CONFLICT",
          r4["outcome"] == "rejected_mismatch"
          and r4["code"] == "IDEMPOTENCY_CONFLICT", r4)

    # (d) same command_id replays the original receipt (step 3).
    cmd = f"clk-{u()[:8]}"
    r5 = compact_lock(conn, fx2["session"], cmd, DRIVER, EPOCH, "cmp-idem")
    r6 = compact_lock(conn, fx2["session"], cmd, DRIVER, EPOCH, "cmp-idem")
    check("D2 same command_id replays the original receipt",
          r6["outcome"] == r5["outcome"]
          and r6["receipt"] == r5["receipt"], r6)


# ---------------------------------------------------------------------------
# 3. D3/D4 — finalize / abort and the terminal replay
# ---------------------------------------------------------------------------

def test_finalize_and_abort(conn) -> None:
    # finalize: locked -> finalized with a frozen result identity and the
    # compaction/end audit event.
    fx = idle_session(conn)
    rl = compact_lock(conn, fx["session"], f"clk-{u()[:8]}", DRIVER, EPOCH,
                      "cmp-fin")
    fence = rl["receipt"]["owner_fence"]
    rf = compact_finalize(conn, fx["session"], f"cfn-{u()[:8]}", DRIVER, EPOCH,
                          "cmp-fin", fence)
    check("D3 finalize accepted", rf["outcome"] == "accepted", rf)
    row = one(conn, "SELECT status, result_identity FROM compactions"
                    " WHERE session_id=%s AND compaction_id='cmp-fin'",
              (fx["session"],))
    check("D3 row finalized with result_identity",
          row[0] == "finalized" and row[1] == rf["receipt"]["result_identity"],
          row)
    check("D3 compaction/end audit event written once",
          one(conn, "SELECT count(*) FROM session_events WHERE session_id=%s"
                    " AND event_type='compaction/end'",
              (fx["session"],))[0] == 1)
    check("D3 the end event key is the frozen identity input",
          rf["receipt"]["end_event_key"] is not None)

    # terminal replay: a fresh command_id with the same frozen parameters
    # returns the historical identity read-only.
    rr = compact_finalize(conn, fx["session"], f"cfn-{u()[:8]}", DRIVER, EPOCH,
                          "cmp-fin", fence)
    check("D3 terminal replay returns the frozen identity read-only",
          rr["outcome"] == "accepted"
          and rr["receipt"].get("read_only_replay") is True
          and rr["receipt"]["result_identity"] == rf["receipt"]["result_identity"],
          rr)
    check("D3 replay produced no second compaction/end event",
          one(conn, "SELECT count(*) FROM session_events WHERE session_id=%s"
                    " AND event_type='compaction/end'",
              (fx["session"],))[0] == 1)

    # stale owner fence takes priority over parameters.
    rs = compact_finalize(conn, fx["session"], f"cfn-{u()[:8]}", DRIVER, EPOCH,
                          "cmp-fin", fence + 1)
    check("D3 stale owner fence -> STALE_COMPACT_FENCE",
          rs["outcome"] == "rejected_stale"
          and rs["code"] == "STALE_COMPACT_FENCE", rs)

    # abort: locked -> aborted, internal_op_audits row, abort_identity, and
    # NEVER a result event.
    fx2 = idle_session(conn)
    rl2 = compact_lock(conn, fx2["session"], f"clk-{u()[:8]}", DRIVER, EPOCH,
                       "cmp-ab")
    ra = compact_abort(conn, fx2["session"], f"cab-{u()[:8]}", DRIVER, EPOCH,
                       "cmp-ab", rl2["receipt"]["owner_fence"])
    check("D4 abort accepted", ra["outcome"] == "accepted", ra)
    row2 = one(conn, "SELECT status, abort_identity FROM compactions"
                     " WHERE session_id=%s AND compaction_id='cmp-ab'",
               (fx2["session"],))
    check("D4 row aborted with abort_identity",
          row2[0] == "aborted" and row2[1] == ra["receipt"]["abort_identity"],
          row2)
    check("D4 internal_op_audits compact_terminal_abort row written",
          one(conn, "SELECT count(*) FROM internal_op_audits"
                    " WHERE parent_session_id=%s AND internal_op_kind="
                    "'compact_terminal_abort'",
              (fx2["session"],))[0] == 1)
    check("D4 abort produced NO compaction/end event",
          one(conn, "SELECT count(*) FROM session_events WHERE session_id=%s"
                    " AND event_type='compaction/end'",
              (fx2["session"],))[0] == 0)
    check("D4 abort released the lock back to idle",
          one(conn, "SELECT count(*) FROM compactions WHERE session_id=%s"
                    " AND status='locked'", (fx2["session"],))[0] == 0)

    # after abort the session can lock again (a fresh row / new identity).
    rl3 = compact_lock(conn, fx2["session"], f"clk-{u()[:8]}", DRIVER, EPOCH,
                       "cmp-ab-2")
    check("D4 idle re-entry after abort accepted",
          rl3["outcome"] == "accepted"
          and rl3["receipt"]["compaction_id"] == "cmp-ab-2", rl3)


# ---------------------------------------------------------------------------
# 4. D10 — the compact x LLM-effect conflict matrix
# ---------------------------------------------------------------------------

def test_conflict_matrix(conn) -> None:
    # Item (2): with an active compact lock, the seal and dispatch paths
    # reject new LLM effect work with COMPACT_IN_PROGRESS.
    fx = idle_session(conn)
    rl = compact_lock(conn, fx["session"], f"clk-{u()[:8]}", DRIVER, EPOCH,
                      "cmp-guard")
    check("D10 lock accepted on the idle session",
          rl["outcome"] == "accepted", rl)

    turn, step, eff = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    rs = prepare_step(conn, fx["session"], f"seal-{u()[:8]}", DRIVER, EPOCH,
                      fx["fence"], step, turn, eff,
                      request_hash=f"rh-{u()[:10]}",
                      idempotency_key=f"ik-{u()[:10]}")
    check("D10 initial decision seal under an active lock ->"
          " COMPACT_IN_PROGRESS",
          rs["outcome"] == "rejected_mismatch"
          and rs["code"] == "COMPACT_IN_PROGRESS", rs)
    check("D10 seal rejection created zero control state",
          rows(conn, "SELECT count(*) FROM steps WHERE session_id=%s",
               (fx["session"],))[0][0] == 0)

    # After the lock is aborted, the same seal succeeds.
    compact_abort(conn, fx["session"], f"cab-{u()[:8]}", DRIVER, EPOCH,
                  "cmp-guard", rl["receipt"]["owner_fence"])
    rs2 = prepare_step(conn, fx["session"], f"seal-{u()[:8]}", DRIVER, EPOCH,
                       fx["fence"], step, turn, eff,
                       request_hash=f"rh-{u()[:10]}",
                       idempotency_key=f"ik-{u()[:10]}")
    check("D10 seal succeeds once the lock is released",
          rs2["outcome"] == "accepted", rs2)


def main() -> int:
    setup_db()
    conn = psycopg2.connect(_uri())
    conn.autocommit = False
    try:
        # setup_db already seeded the stage grants (including the `compact`
        # capability grant for DRIVER); re-seeding here would collide.
        test_table_shape(conn)
        test_compact_lock(conn)
        test_finalize_and_abort(conn)
        test_conflict_matrix(conn)
    finally:
        conn.close()
    print("[G17] all gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
