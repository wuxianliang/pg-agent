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


# ---------------------------------------------------------------------------
# 5. D7 — the terminal-transaction controlled abort at the three entries
# ---------------------------------------------------------------------------

def finished_session_fixture(conn, driver: str = DRIVER) -> dict:
    """A claimable session whose next step is finish_session (one closed
    decision_only turn)."""
    s = uuid.uuid4()
    turn = uuid.uuid4()
    create_session(conn, s, driver)
    entry = build_entry("user/message", {"text": "hi"}, schema_version=SV,
                        canonicalizer_version=CV, turn_id=turn,
                        semantic_input_ordinal=1)
    call_append_events(conn, s, f"usr-{u()[:8]}", driver, EPOCH, 1, [entry])
    r1 = claim_session(conn, s, driver)
    step, effect = uuid.uuid4(), uuid.uuid4()
    rh, ik = f"rh-{u()[:10]}", f"ik-{u()[:10]}"
    rs = prepare_step(conn, s, f"seal-{u()[:8]}", driver, EPOCH,
                      r1["session_fence"], step, turn, effect,
                      request_hash=rh, idempotency_key=ik)
    fence = rs["receipt"]["session_fence"]
    rd = dispatch_effect(conn, s, f"dsp-{u()[:8]}", effect, driver, EPOCH,
                         fence, rs["receipt"]["job_fence"])
    rc = complete_effect(
        conn, s, f"cmp-{u()[:8]}", effect, driver, EPOCH,
        dispatch_session_fence=r1["session_fence"],
        job_fence=rs["receipt"]["job_fence"], step_id=step,
        request_hash=rh, idempotency_key=ik,
        outcome="succeeded", message={"text": "done"}, tools=[],
        decision_only=True, final_tools=False, evidence=good_evidence())
    check("fx decision_only complete accepted", rc["outcome"] == "accepted",
          rc)
    r2 = claim_session(conn, s, driver)
    return {"session": s, "finish_fence": r2["session_fence"],
            "step": step, "effect": effect}


def assert_terminal_abort(conn, session, owner_fence_before: int,
                          label: str) -> None:
    row = one(conn, "SELECT status, abort_identity, owner_fence FROM"
                    " compactions WHERE session_id=%s AND status='aborted'"
                    " ORDER BY updated_at DESC LIMIT 1", (session,))
    check(f"{label}: locked row terminal-aborted in the same transaction",
          row is not None and row[0] == "aborted" and row[1] is not None, row)
    check(f"{label}: owner fence ADVANCED by the controlled abort",
          row is not None and row[2] == owner_fence_before + 1, row)
    aud = one(conn, "SELECT count(*) FROM internal_op_audits WHERE"
                    " parent_session_id=%s AND internal_op_kind="
                    "'compact_terminal_abort'", (session,))
    check(f"{label}: compact_terminal_abort audit row written", aud[0] == 1,
          aud)
    check(f"{label}: no compaction/end result event",
          one(conn, "SELECT count(*) FROM session_events WHERE session_id=%s"
                    " AND event_type='compaction/end'", (session,))[0] == 0)


def test_d7_terminal_abort(conn) -> None:
    from v8.cancel.client import request_cancel
    from v8.effect.client import finish_session

    # (i) finish_session
    fx = finished_session_fixture(conn)
    rl = compact_lock(conn, fx["session"], f"clk-{u()[:8]}", DRIVER, EPOCH,
                      "cmp-fin-abort")
    check("D7 lock accepted before finish", rl["outcome"] == "accepted", rl)
    rf = finish_session(conn, fx["session"], f"fin-{u()[:8]}", DRIVER,
                        EPOCH, fx["finish_fence"])
    check("D7 finish_session accepted", rf["outcome"] == "accepted", rf)
    assert_terminal_abort(conn, fx["session"],
                          rl["receipt"]["owner_fence"], "D7 finish")
    # the OLD owner stale-rejects afterwards
    rs = compact_finalize(conn, fx["session"], f"cfn-{u()[:8]}", DRIVER,
                          EPOCH, "cmp-fin-abort",
                          rl["receipt"]["owner_fence"])
    check("D7 old owner finalize stale-rejects after terminal abort",
          rs["outcome"] == "rejected_stale"
          and rs["code"] == "STALE_COMPACT_FENCE", rs)

    # (ii) request_cancel (three-window collapse on a waiting_event session)
    fx2 = idle_session(conn)
    rl2 = compact_lock(conn, fx2["session"], f"clk-{u()[:8]}", DRIVER,
                       EPOCH, "cmp-cancel-abort")
    rc2 = request_cancel(conn, fx2["session"], f"cxl-{u()[:8]}", DRIVER,
                         EPOCH)
    check("D7 request_cancel accepted", rc2["outcome"] == "accepted", rc2)
    assert_terminal_abort(conn, fx2["session"], rl2["receipt"]["owner_fence"],
                          "D7 cancel")

    # (iii) WORKSPACE_LOST failure drain (the shared drain core)
    fx3 = idle_session(conn)
    rl3 = compact_lock(conn, fx3["session"], f"clk-{u()[:8]}", DRIVER,
                       EPOCH, "cmp-wl-abort")
    one(conn, "SELECT (v_failure_drain_core(%s::uuid, 'WORKSPACE_LOST',"
              " 'd7 vector', 'wl:key', 'ws_lost_drain'))->>'outcome'",
        (fx3["session"],))
    assert_terminal_abort(conn, fx3["session"], rl3["receipt"]["owner_fence"],
                          "D7 drain")


# ---------------------------------------------------------------------------
# 6. D9 — the lock-order probe: session (position 1) before compact
#    (position 8); the terminal abort stacks AFTER the slot-touching set
# ---------------------------------------------------------------------------

def test_d9_lock_order_probe(conn) -> None:
    import threading
    import time as _time

    fx = idle_session(conn)
    rl = compact_lock(conn, fx["session"], f"clk-{u()[:8]}", DRIVER, EPOCH,
                      "cmp-probe")
    fence = rl["receipt"]["owner_fence"]

    holder = psycopg2.connect(_uri())
    try:
        with holder.cursor() as cur:
            cur.execute("SELECT 1 FROM compactions WHERE session_id=%s"
                        " AND compaction_id='cmp-probe' FOR UPDATE",
                        (str(fx["session"]),))
        result: dict = {}

        def run_finalize():
            c2 = psycopg2.connect(_uri())
            try:
                result["r"] = compact_finalize(
                    c2, fx["session"], f"cfn-{u()[:8]}", DRIVER, EPOCH,
                    "cmp-probe", fence)
            except Exception as exc:  # noqa: BLE001
                result["err"] = repr(exc)
            finally:
                c2.close()

        t = threading.Thread(target=run_finalize)
        t.start()
        _time.sleep(0.8)
        alive = t.is_alive()
        # pg_locks: the finalize holds the SESSION row lock (granted) and
        # waits on the compactions row — session strictly before compact.
        # A row-lock wait surfaces in pg_locks as a non-granted
        # transactionid wait (the blocked tx waits on the HOLDER's xact),
        # not as a non-granted relation lock — probe both facts: the
        # session row lock is granted (position 1 taken first) and the
        # only blocking edge points at the holder's transaction (the
        # compact row it owns).
        locks = rows(holder,
            "SELECT (SELECT count(*) FROM pg_locks l JOIN pg_class c ON"
            " c.oid=l.relation WHERE c.relname='sessions' AND l.granted),"
            " (SELECT count(*) FROM pg_locks WHERE locktype='transactionid'"
            " AND NOT granted),"
            " (SELECT count(*) FROM pg_locks l JOIN pg_class c ON"
            " c.oid=l.relation WHERE c.relname='compactions' AND l.granted"
            " AND l.pid = (SELECT pid FROM pg_stat_activity a"
            "  WHERE a.wait_event_type='Lock' AND a.query LIKE %s"
            "  LIMIT 1))",
            ('%compact_finalize%',))
        holder.rollback()
        holder.commit()
        check("D9 the finalize blocked on the compact row", alive, "no wait")
        check("D9 session row lock GRANTED while blocked on the compact"
              " row (transactionid wait)",
              locks[0][0] >= 1 and locks[0][1] >= 1, locks)
        check("D9 the blocked finalize holds the compact relation lock it"
              " needs (acquired after the session row)",
              locks[0][2] >= 1, locks)
        t.join(timeout=30)
        check("D9 thread completed", not t.is_alive(), "hung")
        r = result.get("r")
        check("D9 finalize completed after release",
              r is not None and r["outcome"] == "accepted", result)
    finally:
        holder.close()


# ---------------------------------------------------------------------------
# 7. D11 — the five byte-level algorithms + goldens + SQL==Python
# ---------------------------------------------------------------------------

GOLDEN = {
    # fixture A (public input + tool/call + known end, fixed values)
    "A_logical": "71bb665236c71011c820bf0358df7d9a3010a9e826bcdaf634c7ae3fe8fd6c84",
    "A_replace": "79fe46dc4c03fd8f4d905c50d46e17d5ea8e534e8e6c632a3506edb2e520a25b",
    "A_identity": "36c8efef9184f397dcf722926a1e1bfab0c7e8d083737f800d31dd5771513967",
    # fixture C (provisional end, two-effect unknown set)
    "C_logical": "cd2af579834eab250cae2d099f4fd1c069cef766937b17a10d0bcb7318f162ef",
    "C_replace": "cd2af579834eab250cae2d099f4fd1c069cef766937b17a10d0bcb7318f162ef",
    "C_identity": "a06c95f07854db912ba7c7c11c880c73bdf72e573a47a538c3857f9b90c2be24",
    "C_set": "904817aa7e22ffba39cc62fb44b12680b2b2056b14d2c9d7a2cccae9fee0be98",
    # fixture D: same digests, different session -> identity differs (O02:
    # session enters the identity; compaction_id/base_seq never do)
    "D_identity": "39a46d206afe3e8436a3d1e55d441496dbb0828896f1118393a437538f56f0a7",
    # fixture E: same payload, different event_type -> both digests differ
    "E_logical": "28f240a33cd71726fec2b9318bbf38cd1004b21ce22410e241df46612c04ec53",
    "E_replace": "28f240a33cd71726fec2b9318bbf38cd1004b21ce22410e241df46612c04ec53",
}


def test_d11_goldens(conn) -> None:
    from v8.compact.digests import digests, unknown_set_digest, _seg, _sha_hex
    T = uuid.UUID("11111111-1111-4111-8111-111111111111")
    S = uuid.UUID("22222222-2222-4222-8222-222222222222")
    E1 = uuid.UUID("33333333-3333-4333-8333-333333333333")
    E2 = uuid.UUID("44444444-4444-4444-8444-444444444444")
    PH1, PH2 = _sha_hex(b"payload-one"), _sha_hex(b"payload-two")
    PH3 = _sha_hex(b'{"outcome":"unknown"}')
    sess = uuid.UUID("00000000-0000-4000-8000-0000000000aa")

    elems = [
        {"event_type": "user/message", "turn_id": T, "step_id": None,
         "dispatch_ordinal": None, "occurrence": _seg(b"1"),
         "payload_hash": PH1},
        {"event_type": "tool/call", "turn_id": T, "step_id": S,
         "dispatch_ordinal": "0", "occurrence": _seg(b"0"),
         "payload_hash": PH2},
        {"event_type": "turn/end", "turn_id": T, "step_id": None,
         "dispatch_ordinal": None, "occurrence": _seg(T.bytes),
         "payload_hash": PH1},
    ]
    a, b, i = digests(elems, sess)
    check("D11 golden A logical", a == GOLDEN["A_logical"], a)
    check("D11 golden A replace", b == GOLDEN["A_replace"], b)
    check("D11 golden A identity", i == GOLDEN["A_identity"], i)
    a2, b2, i2 = digests(list(reversed(elems)), sess)
    check("D11 full-order determinism: input order never affects digests",
          (a2, b2, i2) == (a, b, i), (a2, b2))

    usd = unknown_set_digest([E1, E2])
    check("D11 golden provisional unknown-set digest", usd == GOLDEN["C_set"],
          usd)
    prov = [
        {"event_type": "user/message", "turn_id": T, "step_id": None,
         "dispatch_ordinal": None, "occurrence": _seg(b"1"),
         "payload_hash": PH1},
        {"event_type": "turn/end", "turn_id": T, "step_id": None,
         "dispatch_ordinal": None,
         "occurrence": _seg(T.bytes) + _seg(usd.encode()),
         "payload_hash": PH3},
    ]
    ca, cb, ci = digests(prov, sess)
    check("D11 golden C logical", ca == GOLDEN["C_logical"], ca)
    check("D11 golden C identity", ci == GOLDEN["C_identity"], ci)
    _, _, di = digests(prov,
                       uuid.UUID("00000000-0000-4000-8000-0000000000bb"))
    check("D11 O02: session enters the identity (same digests, other "
          "session -> other identity)",
          di == GOLDEN["D_identity"] and di != ci, di)

    tf = [
        {"event_type": "assistant/message", "turn_id": T, "step_id": None,
         "dispatch_ordinal": None, "occurrence": _seg(E1.bytes),
         "payload_hash": PH2},
        {"event_type": "turn/end", "turn_id": T, "step_id": None,
         "dispatch_ordinal": None, "occurrence": _seg(T.bytes),
         "payload_hash": PH1},
    ]
    ea, eb, _ = digests(tf, sess)
    check("D11 O03 type fidelity: same payload under another event_type "
          "changes BOTH digests",
          ea == GOLDEN["E_logical"] and eb == GOLDEN["E_replace"]
          and ea != a, (ea, eb))

    # SQL side: the identity function on the same inputs equals the mirror.
    sql_i = one(conn, "SELECT v_compact_result_identity(%s::uuid, %s, %s)",
                (sess, ca, cb))[0]
    check("D11 SQL==Python identity", sql_i == ci, (sql_i, ci))
    sql_set = one(conn, "SELECT v_compact_unknown_set_digest(ARRAY[%s::uuid,"
                        " %s::uuid]::uuid[])", (E1, E2))[0]
    check("D11 SQL==Python unknown-set digest", sql_set == usd,
          (sql_set, usd))


def test_d11_sql_python_live(conn) -> None:
    """SQL==Python byte-level cross-check on a live finalized session."""
    from v8.compact.digests import covered_elements, digests

    fx = finished_session_fixture(conn)
    rl = compact_lock(conn, fx["session"], f"clk-{u()[:8]}", DRIVER, EPOCH,
                      "cmp-live")
    through = rl["receipt"]["through_seq"]
    rf = compact_finalize(conn, fx["session"], f"cfn-{u()[:8]}", DRIVER,
                          EPOCH, "cmp-live", rl["receipt"]["owner_fence"])
    check("D11 live finalize accepted", rf["outcome"] == "accepted", rf)
    sql = one(conn, "SELECT logical_cutoff_digest, replacement_set_digest,"
                    " compact_result_identity FROM v_compact_digests(%s::uuid,"
                    " %s)", (fx["session"], through))
    # mirror: fetch the raw rows (through_seq) with the closer resolution
    evs = [dict(zip(
        ("seq", "event_type", "event_class", "turn_id", "step_id",
         "effect_id", "payload", "payload_hash", "semantic_input_ordinal"),
        r))
        for r in rows(conn,
            "SELECT seq, event_type, event_class, turn_id, step_id,"
            " effect_id, payload, payload_hash, semantic_input_ordinal"
            " FROM session_events WHERE session_id=%s AND seq <= %s",
            (fx["session"], through))]
    py_a, py_b, py_i = digests(covered_elements(evs), fx["session"])
    check("D11 SQL==Python logical_cutoff_digest (live)",
          sql[0] == py_a, (sql[0], py_a))
    check("D11 SQL==Python replacement_set_digest (live)",
          sql[1] == py_b, (sql[1], py_b))
    check("D11 SQL==Python compact_result_identity (live)",
          sql[2] == py_i and rf["receipt"]["result_identity"] == py_i,
          (sql[2], py_i))
    # truncation boundary (S03): through_seq BEFORE the assistant message
    # changes both digests; the finalize payload frozen the in-range values.
    sql_pre = one(conn, "SELECT logical_cutoff_digest FROM"
                        " v_compact_digests(%s::uuid, %s)",
                  (fx["session"], 1))
    check("D11 truncation boundary: a narrower range changes the digest",
          sql_pre[0] != sql[0], (sql_pre[0], sql[0]))


# ---------------------------------------------------------------------------
# 8. D12 — normalize extracts the compact semantic result verbatim
# ---------------------------------------------------------------------------

def test_d12_normalize_projection(conn) -> None:
    from v8.events.canonicalizer import normalize

    fx = finished_session_fixture(conn)
    rl = compact_lock(conn, fx["session"], f"clk-{u()[:8]}", DRIVER, EPOCH,
                      "cmp-norm")
    rf = compact_finalize(conn, fx["session"], f"cfn-{u()[:8]}", DRIVER,
                          EPOCH, "cmp-norm", rl["receipt"]["owner_fence"])
    check("D12 finalize accepted", rf["outcome"] == "accepted", rf)
    evs = [dict(zip(("event_type", "payload", "turn_id", "step_id",
                     "effect_id", "event_class"), r))
           for r in rows(conn,
               "SELECT event_type, payload::jsonb, turn_id, step_id,"
               " effect_id, event_class FROM session_events"
               " WHERE session_id=%s", (fx["session"],))]
    out = normalize(evs)
    comps = [e for e in out if e["event_type"] == "compaction/result"]
    check("D12 normalize carries exactly one compaction/result element",
          len(comps) == 1, [e["event_type"] for e in out])
    p = comps[0]["payload"] if comps else {}
    check("D12 the three logical fields extracted VERBATIM",
          set(p) == {"logical_cutoff_digest", "replacement_set_digest",
                     "compact_result_identity"}, p)
    check("D12 fields equal the finalize record's frozen digests",
          p.get("compact_result_identity")
          == rf["receipt"]["result_identity"]
          and len(p.get("logical_cutoff_digest", "")) == 64
          and len(p.get("replacement_set_digest", "")) == 64, p)
    # the raw audit event never enters the semantic trace.
    types = [e["event_type"] for e in out]
    check("D12 the raw compaction/end audit event stays out of the trace",
          "compaction/end" not in types, types)


def main() -> int:
    setup_db()
    conn = psycopg2.connect(_uri())
    conn.autocommit = False
    try:
        test_table_shape(conn)
        test_compact_lock(conn)
        test_finalize_and_abort(conn)
        test_conflict_matrix(conn)
        test_d7_terminal_abort(conn)
        test_d9_lock_order_probe(conn)
        test_d11_goldens(conn)
        test_d11_sql_python_live(conn)
        test_d12_normalize_projection(conn)
    finally:
        conn.close()
    print("[G17] all gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
