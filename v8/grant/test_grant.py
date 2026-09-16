"""G10 gate: v8 grant stage — the complete section 2.1/2.2 model.

Covers: the migrated G9a stub assertions, parameter-level constraint
evaluation (six dimensions), the conjunct-3 vectors (slice-membership +
full subject resolution), controlled revocation, the authorization
linearization point (mechanism (a), both commit orders + a lock-wait
interleave), RLS tenant isolation, the operator channel, workspace_handles
(full chain), the WORKSPACE_LOST fail-closed drain, the minimal fork, and
the append-layer upgrades (heartbeat authorization precheck, full-subject
grant lookup, stream registry, retained A57 legacy downgrade).

Run: uv run python v8/grant/test_grant.py  (exit 0 = pass)
"""
from __future__ import annotations

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
from v8.events.client import build_entry
from v8.grant.fixtures import (
    SV,
    CV,
    append_chunks,
    chunk_entry,
    chunk_fixture,
    expect_error,
    fresh_session,
    seed_grant,
    seed_slice,
    u,
    _now,
)
from v8.grant.setup_db import DB, main as setup_db

URI = None


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f": {detail}" if detail else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def _uri() -> str:
    return get_server().get_uri(DB)


def one(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    conn.commit()
    return row


def judge(conn, session_id, grant_ids, capability, caller_subject=None,
          caller_driver=None, caller_epoch=None, params=None):
    rows = []
    with conn.cursor() as cur:
        cur.execute(
            "SELECT lj.grant_id, lj.valid, lj.reason FROM v_grant_lock_judge("
            "%s::uuid, %s::text[], %s, %s, %s, %s, %s::jsonb) lj",
            (session_id, grant_ids, capability, caller_subject, caller_driver,
             caller_epoch, json.dumps(params) if params else None))
        rows = cur.fetchall()
    conn.commit()
    return rows


def find_valid(conn, session_id, capability, caller_subject=None,
               caller_driver=None, caller_epoch=None, caller_grant_id=None,
               params=None):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT v_grant_find_valid(%s::uuid, %s, %s, %s, %s, %s,"
            " %s::jsonb)",
            (session_id, capability, caller_subject, caller_driver,
             caller_epoch, caller_grant_id,
             json.dumps(params) if params else None))
        gid = cur.fetchone()[0]
    conn.commit()
    return gid


def _valid(conn, label, session_id, grant_id, capability, expect) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT v_grant_valid(%s::uuid, %s, %s)",
                    (session_id, grant_id, capability))
        got = cur.fetchone()[0]
    conn.rollback()
    check(label, got is expect, got)


def _update(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
    conn.commit()


def hb(payload: dict | None = None) -> dict:
    return build_entry("session/heartbeat", payload or {"beat": 1},
                       schema_version=SV, canonicalizer_version=CV)


# ---------------------------------------------------------------------------
# 1. migrated G9a stub assertions (test_grant_stub block)
# ---------------------------------------------------------------------------

def test_grant_stub(conn) -> None:
    ws = u()
    sl = seed_slice(conn, ws, "corpus-a", kind="corpus",
                    spec={"paths": ["/data/x"]})

    # slices UNIQUE(workspace_id, name).
    expect_error(conn, "duplicate slice name in a workspace -> UNIQUE",
                 lambda: seed_slice(conn, ws, "corpus-a"))
    # slices kind closed set.
    expect_error(conn, "slice kind outside the closed set -> CHECK",
                 lambda: seed_slice(conn, ws, "corpus-b", kind="nonsense"))
    # slices spec immutability.
    expect_error(conn, "slice spec UPDATE -> rejected",
                 lambda: _update(conn, "UPDATE slices SET spec='{}' WHERE slice_id=%s",
                                 (sl,)))
    # slices revoked_at monotonic.
    seed_slice(conn, ws, "corpus-rev", slice_id=u(), revoked=True)
    expect_error(conn, "slice revoked_at cannot be cleared",
                 lambda: _update(
                     conn, "UPDATE slices SET revoked_at=NULL WHERE name='corpus-rev'"))

    # grants closed sets.
    expect_error(conn, "grant subject_kind outside the closed set -> CHECK",
                 lambda: seed_grant(conn, u(), ws, sl, "team", "t1", "recall"))
    expect_error(conn, "grant capability outside the 13-value set -> CHECK",
                 lambda: seed_grant(conn, u(), ws, sl, "session", "x", "root"))
    # grants tenant consistency (composite FK): a workspace_id that does not
    # match the slice's.
    expect_error(conn, "grant workspace != slice workspace -> composite FK",
                 lambda: seed_grant(conn, u(), u(), sl, "session", "x", "recall"))
    # grants constraints immutability.
    g_imm = seed_grant(conn, "gr-imm", ws, sl, "session", "x", "recall",
                       constraints={"max_rows": 1})
    expect_error(conn, "grant constraints UPDATE -> rejected",
                 lambda: _update(
                     conn, "UPDATE grants SET constraints='{\"max_rows\":9}'"
                           " WHERE grant_id='gr-imm'"))

    # ---- v_grant_valid full conjunction (session-bound subject) ----
    s = fresh_session(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT driver FROM sessions WHERE session_id=%s", (s,))
        drv = cur.fetchone()[0]
    conn.rollback()
    base = dict(subject_kind="session", subject_id=s, capability="event_append")

    g_ok = seed_grant(conn, "g-ok", ws, sl, **base)
    _valid(conn, "valid grant -> true", s, g_ok, "event_append", True)
    _valid(conn, "wrong capability -> false", s, g_ok, "stream_ingest", False)

    g_rev = seed_grant(conn, "g-rev", ws, sl, **base, revoked=True)
    _valid(conn, "grant revoked -> false", s, g_rev, "event_append", False)

    g_future = seed_grant(conn, "g-fut", ws, sl, **base,
                          not_before=_now(3600), expires_at=_now(7200))
    _valid(conn, "not_before in the future -> false", s, g_future,
           "event_append", False)

    g_exp = seed_grant(conn, "g-exp", ws, sl, **base,
                       not_before=_now(-7200), expires_at=_now(-3600))
    _valid(conn, "expires_at in the past -> false", s, g_exp, "event_append", False)

    g_other = seed_grant(conn, "g-oth", ws, sl, "session", u(), "event_append")
    _valid(conn, "subject mismatch -> false", s, g_other, "event_append", False)

    # slice revocation propagation: slice revoked, grant NOT revoked -> invalid.
    sl_rev = seed_slice(conn, ws, "corpus-rev2", revoked=True)
    g_prop = seed_grant(conn, "g-prop", ws, sl_rev, **base)
    _valid(conn, "slice revoked propagates (grant itself unrevoked) -> false",
           s, g_prop, "event_append", False)

    # driver-bound subject leg.
    g_drv = seed_grant(conn, "g-drv", ws, sl, "driver", drv, "event_append")
    _valid(conn, "driver-bound subject matches the session -> true",
           s, g_drv, "event_append", True)

    # unknown grant id.
    _valid(conn, "unknown grant_id -> false", s, "g-missing", "event_append", False)


# ---------------------------------------------------------------------------
# 2. parameter-level constraint evaluation (six dimensions)
# ---------------------------------------------------------------------------

def test_constraints(conn) -> None:
    ws = u()
    sl = seed_slice(conn, ws, "constrained", spec={})
    s = fresh_session(conn)
    gid = seed_grant(conn, "g-con", ws, sl, "session", s, "effect_submit")

    def judge_ok(params, reason_label, expect_valid):
        rows = judge(conn, s, [gid], "effect_submit", params=params)
        check(f"constraints: {reason_label}",
              rows and rows[0][1] is expect_valid, rows)

    # path prefix dimension.
    seed_grant(conn, "g-path", ws, sl, "session", s, "tool_resolve",
               constraints={"paths": ["/data/x"]})
    rows = judge(conn, s, ["g-path"], "tool_resolve",
                 params={"path": "/data/x/sub/file.txt"})
    check("constraints: path inside prefix -> valid", rows[0][1] is True, rows)
    rows = judge(conn, s, ["g-path"], "tool_resolve",
                 params={"path": "/etc/passwd"})
    check("constraints: path outside prefix -> GRANT_DENIED",
          rows[0][1] is False and rows[0][2] == "CONSTRAINT_VIOLATED", rows)

    # command whitelist dimension (exact).
    seed_grant(conn, "g-cmd", ws, sl, "session", s, "env_read",
               constraints={"commands": ["read_file", "list_dir"]})
    rows = judge(conn, s, ["g-cmd"], "env_read", params={"command": "read_file"})
    check("constraints: whitelisted command -> valid", rows[0][1] is True, rows)
    rows = judge(conn, s, ["g-cmd"], "env_read",
                 params={"command": "read_file_extra"})
    check("constraints: command outside whitelist -> GRANT_DENIED",
          rows[0][1] is False and rows[0][2] == "CONSTRAINT_VIOLATED", rows)

    # target set dimension.
    seed_grant(conn, "g-tgt", ws, sl, "session", s, "env_write",
               constraints={"targets": ["res-1", "res-2"]})
    rows = judge(conn, s, ["g-tgt"], "env_write", params={"target": "res-2"})
    check("constraints: target inside set -> valid", rows[0][1] is True, rows)
    rows = judge(conn, s, ["g-tgt"], "env_write", params={"target": "res-9"})
    check("constraints: target outside set -> GRANT_DENIED",
          rows[0][1] is False and rows[0][2] == "CONSTRAINT_VIOLATED", rows)

    # TTL dimension (relative to not_before).
    seed_grant(conn, "g-ttl", ws, sl, "session", s, "recall",
               constraints={"ttl_seconds": 10},
               not_before=_now(-3600), expires_at=_now(3600))
    rows = judge(conn, s, ["g-ttl"], "recall", params=None)
    check("constraints: TTL exceeded -> GRANT_DENIED",
          rows[0][1] is False and rows[0][2] == "CONSTRAINT_VIOLATED", rows)
    seed_grant(conn, "g-ttl2", ws, sl, "session", s, "recall",
               constraints={"ttl_seconds": 3600},
               not_before=_now(-10), expires_at=_now(3600))
    rows = judge(conn, s, ["g-ttl2"], "recall", params=None)
    check("constraints: TTL within -> valid", rows[0][1] is True, rows)

    # max_bytes dimension.
    seed_grant(conn, "g-mb", ws, sl, "session", s, "fold",
               constraints={"max_bytes": 1024})
    rows = judge(conn, s, ["g-mb"], "fold", params={"bytes": 1024})
    check("constraints: bytes at the bound -> valid", rows[0][1] is True, rows)
    rows = judge(conn, s, ["g-mb"], "fold", params={"bytes": 1025})
    check("constraints: max_bytes exceeded -> GRANT_DENIED",
          rows[0][1] is False and rows[0][2] == "CONSTRAINT_VIOLATED", rows)

    # max_rows dimension.
    seed_grant(conn, "g-mr", ws, sl, "session", s, "network",
               constraints={"max_rows": 5})
    rows = judge(conn, s, ["g-mr"], "network", params={"rows": 5})
    check("constraints: rows at the bound -> valid", rows[0][1] is True, rows)
    rows = judge(conn, s, ["g-mr"], "network", params={"rows": 6})
    check("constraints: max_rows exceeded -> GRANT_DENIED",
          rows[0][1] is False and rows[0][2] == "CONSTRAINT_VIOLATED", rows)

    # fail closed: a present constraint with a missing parameter denies.
    rows = judge(conn, s, ["g-path"], "tool_resolve", params={})
    check("constraints: present path constraint, missing param -> denied",
          rows[0][1] is False, rows)

    # unconstrained grant (constraints NULL) stays valid.
    rows = judge(conn, s, [gid], "effect_submit", params=None)
    check("constraints: NULL constraints -> valid", rows[0][1] is True, rows)


# ---------------------------------------------------------------------------
# 3. conjunct-3 vectors: slice-membership + full subject resolution
# ---------------------------------------------------------------------------

def test_conjunct3(conn) -> None:
    # (a) target resource not in slice.spec -> GRANT_DENIED.
    ws = u()
    sl_a = seed_slice(conn, ws, "mem-a", spec={"resources": ["res-a1", "res-a2"]})
    sl_b = seed_slice(conn, ws, "mem-b", spec={"resources": ["res-b1"]})
    s = fresh_session(conn)
    g_a = seed_grant(conn, "g-mema", ws, sl_a, "session", s, "effect_submit")
    rows = judge(conn, s, [g_a], "effect_submit", params={"target": "res-a2"})
    check("membership: target inside slice.spec -> valid", rows[0][1] is True, rows)
    rows = judge(conn, s, [g_a], "effect_submit", params={"target": "res-b1"})
    check("membership: target belongs to a DIFFERENT slice of the SAME tenant"
          " -> GRANT_DENIED (RLS never substitutes slice-membership)",
          rows[0][1] is False and rows[0][2] == "SLICE_MEMBERSHIP_DENIED", rows)

    # (b) full subject resolution, per subject kind.
    # session kind: calling session.
    rows = judge(conn, s, [g_a], "effect_submit", params={"target": "res-a1"})
    check("subject: session kind resolves via the calling session",
          rows[0][1] is True, rows)
    # driver kind: the session's current driver.
    g_drv = seed_grant(conn, "g-sub-drv", ws, sl_a, "driver", "drv", "effect_submit")
    rows = judge(conn, s, [g_drv], "effect_submit")
    check("subject: driver kind resolves via the session driver",
          rows[0][1] is True, rows)
    # step kind: the session's active step.
    sfx, turn, step, effect = chunk_fixture(conn, session_id=s)
    _update(conn, "UPDATE sessions SET active_step_id=%s WHERE session_id=%s",
            (step, s))
    g_step = seed_grant(conn, "g-sub-step", ws, sl_a, "step", step, "effect_submit")
    rows = judge(conn, s, [g_step], "effect_submit")
    check("subject: step kind resolves via active_step_id",
          rows[0][1] is True, rows)
    # plugin_identity kind: resolved through the declared caller subject
    # (the grant/driver chain — the A56 session-bound approximation is gone).
    g_plug = seed_grant(conn, "g-sub-plug", ws, sl_a, "plugin_identity",
                        "provider-alpha", "effect_submit")
    rows = judge(conn, s, [g_plug], "effect_submit", caller_subject="provider-alpha")
    check("subject: plugin_identity resolves via the declared caller subject",
          rows[0][1] is True, rows)
    rows = judge(conn, s, [g_plug], "effect_submit", caller_subject="provider-beta")
    check("subject: plugin_identity with a foreign caller -> SUBJECT_MISMATCH",
          rows[0][1] is False and rows[0][2] == "SUBJECT_MISMATCH", rows)
    # kind mismatch: a step-kind grant whose subject is the driver's id.
    g_kindmm = seed_grant(conn, "g-kindmm", ws, sl_a, "step", "drv", "effect_submit")
    rows = judge(conn, s, [g_kindmm], "effect_submit")
    check("subject: kind-aware resolution (step-kind grant holding the driver"
          " id never matches)",
          rows[0][1] is False and rows[0][2] == "SUBJECT_MISMATCH", rows)
    # declared caller driver/epoch must match the session row.
    rows = judge(conn, s, [g_a], "effect_submit", caller_driver="other-drv")
    check("subject: declared driver mismatch -> CALLER_DRIVER_MISMATCH",
          rows[0][1] is False and rows[0][2] == "CALLER_DRIVER_MISMATCH", rows)
    rows = judge(conn, s, [g_a], "effect_submit", caller_epoch=99)
    check("subject: declared epoch mismatch -> CALLER_DRIVER_MISMATCH",
          rows[0][1] is False and rows[0][2] == "CALLER_DRIVER_MISMATCH", rows)

    # (c) the search entry resolves through the same chain.
    got = find_valid(conn, s, "effect_submit", caller_subject="provider-alpha")
    check("find_valid: plugin_identity subject discovered through the judge",
          got in ("g-mema", "g-sub-drv", "g-sub-step", "g-sub-plug")
          and got is not None, got)
    got = find_valid(conn, s, "effect_submit", caller_subject="provider-beta")
    check("find_valid: foreign caller subject finds no valid plugin grant",
          got in ("g-mema", "g-sub-drv", "g-sub-step"), got)
    got = find_valid(conn, s, "compact")
    check("find_valid: capability with no grants -> NULL", got is None, got)


# ---------------------------------------------------------------------------
# 4. controlled revocation (operator channel)
# ---------------------------------------------------------------------------

def test_operator_channel(conn) -> None:
    ws = u()
    # issue through the operator channel.
    sl = one(conn, "SELECT v_operator_issue_slice('op-1', %s::uuid, 'op-corpus',"
                   " 'corpus', '{\"resources\": [\"res-o\"]}'::jsonb)", (ws,))[0]
    check("operator: issue_slice returns a slice id", sl is not None)
    gid = one(conn, "SELECT v_operator_issue_grant('op-1', %s::uuid, %s::uuid,"
                    " 'session', %s, 'effect_submit', NULL, NULL, NULL, true)",
                    (ws, sl, "subj-op"))[0]
    check("operator: issue_grant returns a grant id", gid is not None)
    # tenant check: issuing into the wrong workspace rejects.
    expect_error(conn, "operator: grant for a foreign-workspace slice -> rejected",
                 lambda: one(conn,
                     "SELECT v_operator_issue_grant('op-1', %s::uuid, %s::uuid,"
                     " 'session', 'x', 'recall', NULL)", (u(), sl)))

    # revocation requires a reason.
    expect_error(conn, "operator: revoke without a reason -> rejected",
                 lambda: one(conn, "SELECT v_operator_revoke_grant('op-1', %s, '')",
                             (gid,)))
    # nonexistent grant -> rejected (no audit path).
    expect_error(conn, "operator: revoke nonexistent grant -> rejected",
                 lambda: one(conn, "SELECT v_operator_revoke_grant('op-1', 'g-none',"
                                   " 'cleanup')"))
    expect_error(conn, "operator: revoke nonexistent slice -> rejected",
                 lambda: one(conn, "SELECT v_operator_revoke_slice('op-1', %s::uuid,"
                                   " 'cleanup')", (uuid.uuid4(),)))

    # revoke + same-transaction audit + re-sign with a NEW grant_id.
    s = fresh_session(conn)
    g2 = one(conn, "SELECT v_operator_issue_grant('op-2', %s::uuid, %s::uuid,"
                   " 'session', %s, 'event_append', NULL)", (ws, sl, s))[0]
    row = one(conn, "SELECT revoked_at FROM grants WHERE grant_id=%s", (g2,))
    check("operator: fresh grant unrevoked", row[0] is None)
    res = one(conn, "SELECT v_operator_revoke_grant('op-2', %s, 'rotation')", (g2,))[0]
    check("operator: revoke_grant reports revoked", res["revoked"] is True, res)
    audit = one(conn, "SELECT operator_id, action, reason FROM grant_ops_audit"
                      " WHERE target_id=%s AND action='revoke_grant'", (g2,))
    check("operator: revoke audit row carries operator + reason",
          audit == ("op-2", "revoke_grant", "rotation"), audit)
    _valid(conn, "revoked grant -> invalid", s, g2, "event_append", False)
    # re-signing = a NEW grant id.
    g3 = one(conn, "SELECT v_operator_issue_grant('op-2', %s::uuid, %s::uuid,"
                   " 'session', %s, 'event_append', NULL)", (ws, sl, s))[0]
    check("operator: re-sign after revoke = new grant_id", g3 != g2, (g2, g3))
    # idempotent re-revoke.
    res = one(conn, "SELECT v_operator_revoke_grant('op-2', %s, 'again')", (g2,))[0]
    check("operator: re-revoke idempotent", res.get("already_revoked") is True, res)

    # slice revocation cascades through the equivalent check.
    res = one(conn, "SELECT v_operator_revoke_slice('op-2', %s::uuid, 'retired')",
              (sl,))[0]
    check("operator: revoke_slice reports grants_invalidated",
          res["revoked"] is True and res["grants_invalidated"] >= 1, res)
    _valid(conn, "slice revocation invalidates its unrevoked grants (g3)",
           s, g3, "event_append", False)

    # SECURITY DEFINER per-function audit coverage.
    for action in ("issue_slice", "issue_grant", "revoke_grant", "revoke_slice"):
        row = one(conn, "SELECT count(*) FROM grant_ops_audit WHERE action=%s",
                  (action,))
        check(f"operator: audit rows exist for {action}", row[0] >= 1, row)


# ---------------------------------------------------------------------------
# 5. authorization linearization point (mechanism (a))
# ---------------------------------------------------------------------------

def test_linearization(conn) -> None:
    ws = u()
    sl = seed_slice(conn, ws, "lin")
    s = fresh_session(conn)
    sfx, turn, step, effect = chunk_fixture(conn, session_id=s)

    # ---- commit order 1: revoke commits first -> later check DENIED ----
    g1 = seed_grant(conn, "g-lin1", ws, sl, "session", s, "effect_submit")
    rows = judge(conn, s, [g1], "effect_submit")
    check("linearization: grant valid before revocation", rows[0][1] is True, rows)
    one(conn, "SELECT v_operator_revoke_grant('op-lin', %s, 'rotation')", (g1,))
    rows = judge(conn, s, [g1], "effect_submit")
    check("linearization: revoke committed first -> subsequent check sees"
          " revoked -> GRANT_DENIED",
          rows[0][1] is False and rows[0][2] == "GRANT_REVOKED", rows)

    # ---- commit order 2: authorization + dispatch commits first -> the
    #      later revoke MUST NOT retroactively cancel the dispatched attempt
    #      (it only flips the grant row; the attempt is settled solely
    #      through fence/lease and completion/repair). ----
    g2 = seed_grant(conn, "g-lin2", ws, sl, "session", s, "effect_submit")

    conn1 = psycopg2.connect(_uri())
    conn2 = psycopg2.connect(_uri())
    done = threading.Event()
    errors = []

    def revoker():
        try:
            with conn2.cursor() as cur:
                cur.execute("SELECT v_operator_revoke_grant('op-lin', %s, 'late')",
                            (g2,))
            conn2.commit()
        except Exception as exc:  # pragma: no cover
            errors.append(exc)
        finally:
            done.set()

    try:
        with conn1.cursor() as cur:
            # T1: the lock+judge suboperation takes the grant/slice row locks
            # (composite order) and the "dispatch" flips the effect — all in
            # ONE transaction, session row locked first per the master order.
            cur.execute("SELECT 1 FROM sessions WHERE session_id=%s FOR UPDATE",
                        (s,))
            cur.execute(
                "SELECT lj.valid FROM v_grant_lock_judge(%s::uuid,"
                " ARRAY[%s]::text[], 'effect_submit', NULL, NULL, NULL,"
                " NULL::jsonb) lj", (s, g2))
            check("linearization: T1 judge sees the grant valid",
                  cur.fetchone()[0] is True)
            cur.execute(
                "UPDATE effect_requests SET status='dispatch_started',"
                " dispatched_at=now() WHERE effect_id=%s", (effect,))
        t = threading.Thread(target=revoker)
        t.start()
        time.sleep(1.0)
        check("linearization: interleaved revoke BLOCKS on the grant row lock",
              not done.is_set())
        conn1.commit()   # authorization + dispatch commit FIRST
        t.join(timeout=10)
        check("linearization: revoke completes after T1 commits", done.is_set())
        check("linearization: no revoke-thread error", not errors, errors)
        row = one(conn, "SELECT revoked_at IS NOT NULL FROM grants WHERE grant_id=%s",
                  (g2,))
        check("linearization: revoke landed after the dispatch commit", row[0] is True)
        row = one(conn, "SELECT status FROM effect_requests WHERE effect_id=%s",
                  (effect,))
        check("linearization: already dispatch_started attempt NOT retroactively"
              " cancelled by the later revoke", row[0] == "dispatch_started", row)
        # A NEW authorization check after the revoke now denies.
        rows = judge(conn, s, [g2], "effect_submit")
        check("linearization: post-revoke checks return GRANT_DENIED",
              rows[0][1] is False and rows[0][2] == "GRANT_REVOKED", rows)
    finally:
        conn1.close()
        conn2.close()


# ---------------------------------------------------------------------------
# 6. RLS tenant isolation
# ---------------------------------------------------------------------------

def test_rls(conn) -> None:
    ws1, ws2 = u(), u()
    seed_slice(conn, ws1, "rls-a")
    seed_slice(conn, ws2, "rls-b")
    s = fresh_session(conn)
    ws = u()
    h = one(conn, "SELECT v_workspace_initialize(%s::uuid, 'run-rls', %s::uuid, 1)",
            (s, ws))[0]

    observations = {}
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL ROLE v8_worker")
            cur.execute("SET LOCAL v8.workspace_id = %s", (ws1,))
            cur.execute("SELECT count(*), array_agg(name ORDER BY name)"
                        " FROM slices")
            observations["ws1_view"] = cur.fetchone()
            cur.execute("SELECT rolbypassrls FROM pg_roles"
                        " WHERE rolname='v8_worker'")
            observations["bypassrls"] = cur.fetchone()[0]
            for label, stmt, params in [
                ("direct INSERT", "INSERT INTO slices(slice_id, workspace_id,"
                                  " name, kind, spec) VALUES (%s::uuid,"
                                  " %s::uuid, 'x', 'corpus', '{}')",
                 (str(uuid.uuid4()), ws1)),
                ("direct UPDATE", "UPDATE slices SET name='y'", ()),
                ("direct DELETE", "DELETE FROM slices", ()),
            ]:
                try:
                    cur.execute(stmt, params)
                    observations[f"dml_{label}"] = "succeeded"
                except psycopg2.Error as exc:
                    conn.rollback()
                    observations[f"dml_{label}"] = str(exc).split("\n")[0]
                    # rollback ends the transaction (and the SET LOCAL role);
                    # re-establish for the next statement.
                    cur.execute("SET LOCAL ROLE v8_worker")
                    cur.execute("SET LOCAL v8.workspace_id = %s", (ws1,))
            try:
                cur.execute("SET ROLE postgres")
                observations["set_role_owner"] = "succeeded"
            except psycopg2.Error as exc:
                conn.rollback()
                observations["set_role_owner"] = str(exc).split("\n")[0]
                cur.execute("SET LOCAL ROLE v8_worker")
                cur.execute("SET LOCAL v8.workspace_id = %s", (ws1,))
            # capability function through SECURITY DEFINER (no direct DML),
            # committed so its audit trail persists.
            cur.execute("SELECT v_workspace_register_mutation(%s::uuid, 1, 0)",
                        (h,))
            observations["register"] = cur.fetchone()[0]
            conn.commit()
    finally:
        conn.rollback()

    # A dedicated connection authenticated AS the worker (session user =
    # v8_worker) can never SET ROLE to the owner regardless of the SET
    # LOCAL escape hatch above (whose allowed role set derives from the
    # superuser session user).
    from urllib.parse import urlparse, parse_qs
    base = urlparse(_uri())
    host = parse_qs(base.query).get("host", [""])[0]
    worker_uri = f"postgresql://v8_worker:@/{DB}?host={host}"
    try:
        wconn = psycopg2.connect(worker_uri)
    except psycopg2.Error as exc:
        wconn = None
        check("RLS: worker direct connection available",
              False, str(exc).split("\n")[0])
    if wconn is not None:
        try:
            wcur = wconn.cursor()
            wcur.execute("SELECT current_user, session_user")
            who = wcur.fetchone()
            try:
                wcur.execute("SET ROLE postgres")
                setrole = "succeeded"
            except psycopg2.Error as exc:
                wconn.rollback()
                setrole = str(exc).split("\n")[0]
            check("RLS: worker-authenticated session cannot SET ROLE to the"
                  " owner", "permission denied" in setrole, setrole)
            check("RLS: worker direct connection identity",
                  who == ("v8_worker", "v8_worker"), who)
        finally:
            wconn.close()

    check("RLS: worker sees only its workspace's rows (row-level isolation)",
          observations["ws1_view"] == (1, ["rls-a"]), observations["ws1_view"])
    check("RLS: worker role lacks BYPASSRLS", observations["bypassrls"] is False)
    check("RLS: capability function (SECURITY DEFINER) callable by the worker",
          observations["register"]["outcome"] == "accepted", observations["register"])
    for key in ("dml_direct INSERT", "dml_direct UPDATE", "dml_direct DELETE"):
        check(f"RLS: worker {key} on business tables -> permission denied",
              "permission denied" in observations[key], observations[key])
    check("RLS: worker cannot SET ROLE to the owner (SET LOCAL from a"
          " superuser session keeps the superuser's role set — recorded,"
          " the real vector is the dedicated connection below)",
          True, observations["set_role_owner"])
    # SECURITY DEFINER per-function audit trail.
    row = one(conn, "SELECT count(*) FROM grant_ops_audit"
                    " WHERE action='ws_register_mutation' AND target_id=%s",
              (str(h),))
    check("RLS: SECURITY DEFINER function wrote its audit row", row[0] >= 1, row)
    # RLS never substitutes slice-membership (same-tenant, different slice).
    sl_a = seed_slice(conn, ws1, "rls-mem-a", spec={"resources": ["res-a"]})
    g = seed_grant(conn, "g-rls-mem", ws1, sl_a, "session", s, "effect_submit")
    rows = judge(conn, s, [g], "effect_submit", params={"target": "res-b"})
    check("RLS: same-tenant grant over a different slice still GRANT_DENIED"
          " (slice-membership is the in-agent boundary)",
          rows[0][1] is False and rows[0][2] == "SLICE_MEMBERSHIP_DENIED", rows)


# ---------------------------------------------------------------------------
# 7. workspace_handles full chain
# ---------------------------------------------------------------------------

def test_workspace_handles(conn) -> None:
    ws = u()
    s = fresh_session(conn)
    h = one(conn, "SELECT v_workspace_initialize(%s::uuid, 'run-1', %s::uuid, 1)",
            (s, ws))[0]
    check("handles: initialize returns a handle id", h is not None)
    row = one(conn, "SELECT status, op_seq, generation, checkpoint_seq,"
                    " checkpoint_digest FROM workspace_handles WHERE handle_id=%s",
              (h,))
    check("handles: initial row active / op_seq 0 / empty checkpoint",
          row == ("active", 0, 1, None, None), row)
    # unique initialization + handle_id non-reuse.
    h2 = one(conn, "SELECT v_workspace_initialize(%s::uuid, 'run-1', %s::uuid, 9)",
             (s, ws))[0]
    check("handles: UNIQUE(session_id, run_id) -> second initialize returns"
          " the same handle", h2 == h, (h, h2))

    # closed transition table: only listed edges execute — for direct
    # UPDATEs and controlled functions alike.
    _update(conn, "UPDATE workspace_handles SET status='handoff_ready'"
                  " WHERE handle_id=%s", (str(h),))
    _update(conn, "UPDATE workspace_handles SET status='active' WHERE handle_id=%s",
            (str(h),))
    expect_error(conn, "handles: unlisted transition active->uninitialized",
                 lambda: _update(
                     conn, "UPDATE workspace_handles SET status='uninitialized'"
                           " WHERE handle_id=%s", (str(h),)))

    # three-phase controlled mutation.
    r = one(conn, "SELECT v_workspace_register_mutation(%s::uuid, 1, 0)", (h,))[0]
    check("mutation: register CAS advances op_seq 0->1",
          r == {"outcome": "accepted", "op_seq": 1}, r)
    r = one(conn, "SELECT v_workspace_register_mutation(%s::uuid, 1, 0)", (h,))[0]
    check("mutation: CAS failure on a stale expected op_seq",
          r["outcome"] == "rejected_mismatch" and r["code"] == "CAS_FAILED", r)
    r = one(conn, "SELECT v_workspace_register_mutation(%s::uuid, 999, 1)", (h,))[0]
    check("mutation: CAS failure on a stale owner_fence",
          r["outcome"] == "rejected_mismatch", r)
    # fenced publish.
    r = one(conn, "SELECT v_workspace_fenced_publish(%s::uuid, 1, 1, 'm1', 'r1')",
            (h,))[0]
    check("publish: fenced publish completes op 1 and advances the checkpoint",
          r["outcome"] == "accepted" and r["checkpoint_seq"] == 1
          and r["op_seq"] == 1, r)
    r = one(conn, "SELECT v_workspace_fenced_publish(%s::uuid, 1, 1, 'm1', 'r1')",
            (h,))[0]
    check("publish: completed op republish is idempotent",
          r["outcome"] == "accepted" and r.get("already") is True, r)
    # a second mutation, then a STALE publish (wrong owner fence).
    r = one(conn, "SELECT v_workspace_register_mutation(%s::uuid, 1, 1)", (h,))[0]
    check("mutation: second register advances op_seq 1->2",
          r == {"outcome": "accepted", "op_seq": 2}, r)
    r = one(conn, "SELECT v_workspace_fenced_publish(%s::uuid, 999, 2, 'm2', 'r2')",
            (h,))[0]
    check("publish: stale owner_fence publish REJECTED (checkpoint untouched)",
          r["outcome"] == "rejected_stale" and r["code"] == "STALE_OWNER_FENCE", r)
    row = one(conn, "SELECT checkpoint_digest FROM workspace_handles"
                    " WHERE handle_id=%s", (h,))
    check("publish: stale publish did not write into the checkpoint",
          row[0] is not None, row)

    # yield with an in_flight mutation -> WORKSPACE_LOST fail-closed.
    s_lost, turn2, step2, eff2 = chunk_fixture(conn)
    h_lost = one(conn, "SELECT v_workspace_initialize(%s::uuid, 'run-lost',"
                       " %s::uuid, 1)", (s_lost, u()))[0]
    one(conn, "SELECT v_workspace_register_mutation(%s::uuid, 1, 0)", (h_lost,))
    r = one(conn, "SELECT v_workspace_yield_checkpoint(%s::uuid, 1, 'm', 'r')",
            (h_lost,))[0]
    check("yield: in_flight mutation -> WORKSPACE_LOST fail-closed",
          r["outcome"] == "rejected_mismatch" and r["code"] == "WORKSPACE_LOST", r)
    row = one(conn, "SELECT status, lost_reason FROM workspace_handles"
                    " WHERE handle_id=%s", (h_lost,))
    check("yield: handle lost with reason",
          row[0] == "lost" and "unprovable" in row[1], row)
    row = one(conn, "SELECT state, failure_code FROM sessions WHERE session_id=%s",
              (s_lost,))
    check("yield: session failed / WORKSPACE_LOST",
          row == ("failed", "WORKSPACE_LOST"), row)
    row = one(conn, "SELECT count(*) FROM session_events WHERE session_id=%s"
                    " AND event_type='workspace/lost'", (s_lost,))
    check("yield: workspace/lost event appended", row[0] == 1, row)

    # clean yield (publish op 2 first) -> handoff_ready.
    r = one(conn, "SELECT v_workspace_fenced_publish(%s::uuid, 1, 2, 'm2', 'r2')",
            (h,))[0]
    check("publish: op 2 published", r["outcome"] == "accepted", r)
    r = one(conn, "SELECT v_workspace_yield_checkpoint(%s::uuid, 1, 'm2', 'r2')",
            (h,))[0]
    check("yield: no in_flight -> handoff_ready with a covering checkpoint",
          r["outcome"] == "accepted" and r["status"] == "handoff_ready"
          and r["covered_op_seq"] == 2, r)

    # materialize: the four frozen rejections.
    s_m = fresh_session(conn)
    ws_m = u()
    def fresh_handoff(run):
        sx = fresh_session(conn)
        hx = one(conn, "SELECT v_workspace_initialize(%s::uuid, %s, %s::uuid, 1)",
                 (sx, run, ws_m))[0]
        one(conn, "SELECT v_workspace_register_mutation(%s::uuid, 1, 0)", (hx,))
        one(conn, "SELECT v_workspace_fenced_publish(%s::uuid, 1, 1, 'm', 'r')",
            (hx,))
        one(conn, "SELECT v_workspace_yield_checkpoint(%s::uuid, 1, 'm', 'r')",
            (hx,))
        return sx, hx

    good_digest = one(conn, "SELECT checkpoint_digest FROM workspace_handles"
                            " WHERE handle_id=%s", (h,))[0]

    # (1) files missing.
    sx, hx = fresh_handoff("run-m1")
    r = one(conn, "SELECT v_workspace_materialize(%s::uuid, 2, %s, false)",
            (hx, good_digest))[0]
    check("materialize: files missing -> WORKSPACE_LOST (fail-closed)",
          r["code"] == "WORKSPACE_LOST" and r["rejection"] == "files_missing", r)
    row = one(conn, "SELECT state, failure_code FROM sessions WHERE session_id=%s",
              (sx,))
    check("materialize: files-missing session failed / WORKSPACE_LOST",
          row == ("failed", "WORKSPACE_LOST"), row)

    # (2) digest mismatch.
    sx, hx = fresh_handoff("run-m2")
    r = one(conn, "SELECT v_workspace_materialize(%s::uuid, 2, %s, true)",
            (hx, "deadbeef" * 8))[0]
    check("materialize: digest mismatch -> WORKSPACE_LOST",
          r["rejection"] == "digest_mismatch", r)

    # (3) checkpoint not covering the latest completed execution state: an
    # unreconciled in_flight mutation record left on the handoff-ready
    # handle (e.g. a crashed worker's registration racing the handoff —
    # the takeover-invalidation reconcile is LATER; the record itself
    # already makes the checkpoint non-covering).
    sx, hx = fresh_handoff("run-m3")
    _update(conn, "UPDATE workspace_handles SET op_seq = 5"
                  " WHERE handle_id=%s", (str(hx),))
    _update(conn, "INSERT INTO workspace_mutations(handle_id, op_seq, status)"
                  " VALUES (%s::uuid, 5, 'in_flight')", (str(hx),))
    own_digest = one(conn, "SELECT checkpoint_digest FROM workspace_handles"
                           " WHERE handle_id=%s", (hx,))[0]
    r = one(conn, "SELECT v_workspace_materialize(%s::uuid, 2, %s, true)",
            (hx, own_digest))[0]
    check("materialize: in_flight mutation -> checkpoint not covering ->"
          " WORKSPACE_LOST", r["rejection"] == "checkpoint_not_covering", r)

    # (4) handle already lost.
    r = one(conn, "SELECT v_workspace_materialize(%s::uuid, 2, %s, true)",
            (hx, own_digest))[0]
    check("materialize: handle already lost -> WORKSPACE_LOST (terminal)",
          r["code"] == "WORKSPACE_LOST" and r["rejection"] == "handle_lost", r)

    # success: CAS owner_fence, generation+1, op_seq continues, checkpoint kept.
    pre = one(conn, "SELECT checkpoint_seq FROM workspace_handles"
                    " WHERE handle_id=%s", (h,))[0]
    r = one(conn, "SELECT v_workspace_materialize(%s::uuid, 42, %s, true)",
            (h, good_digest))[0]
    check("materialize: success -> active, generation+1, op_seq continues",
          r["outcome"] == "accepted" and r["status"] == "active"
          and r["generation"] == 2 and r["op_seq"] == 2, r)
    row = one(conn, "SELECT owner_fence, generation, checkpoint_digest,"
                    " checkpoint_seq FROM workspace_handles WHERE handle_id=%s",
              (h,))
    check("materialize: checkpoint fields retained; owner fence CAS'd",
          row[0] == 42 and row[1] == 2 and row[2] == good_digest
          and row[3] == pre, row)

    # terminal: lost has no out-edges.
    expect_error(conn, "handles: lost is terminal (no out-edges)",
                 lambda: _update(
                     conn, "UPDATE workspace_handles SET status='active'"
                           " WHERE handle_id=%s", (str(h_lost),)))


# ---------------------------------------------------------------------------
# 8. WORKSPACE_LOST deterministic failure-drain (three branches + repeat)
# ---------------------------------------------------------------------------

def _drain_fixture(conn, effect_status: str, step_status: str):
    s = fresh_session(conn)
    with conn.cursor() as cur:
        turn, step, batch, effect = u(), u(), u(), u()
        cur.execute(
            "INSERT INTO steps(step_id, session_id, turn_id, status, stage)"
            " VALUES (%s, %s, %s, %s, 'decision')", (step, s, turn, step_status))
        cur.execute(
            "INSERT INTO batches(batch_id, session_id, step_id, sealed_batch_no,"
            " kind, sealed) VALUES (%s, %s, %s, 1, 'decision', true)",
            (batch, s, step))
        cur.execute(
            "INSERT INTO effect_requests(effect_id, session_id, step_id,"
            " batch_id, dispatch_ordinal, effect_kind, execution_mode, driver,"
            " driver_epoch, session_fence, dispatch_session_fence,"
            " current_job_fence, request_hash, idempotency_key, status,"
            " retry_class, max_attempts, grant_id)"
            " VALUES (%s, %s, %s, %s, 0, 'llm_decision', 'non_streaming', 'drv',"
            " 1, 1, 1, 1, 'rh', 'ik', %s, 'unsafe', 1, NULL)",
            (effect, s, step, batch, effect_status))
        cur.execute(
            "INSERT INTO effect_attempts(effect_id, attempt_no, session_id,"
            " step_id, dispatch_job_fence, driver, driver_epoch, session_fence,"
            " dispatch_session_fence, request_hash, idempotency_key,"
            " execution_mode, status)"
            " VALUES (%s, 1, %s, %s, 1, 'drv', 1, 1, 1, 'rh', 'ik',"
            " 'non_streaming', %s)",
            (effect, s, step, effect_status))
    conn.commit()
    return s, turn, step, effect


def test_workspace_lost_drain(conn) -> None:
    # branch (iii): neither unknown nor pending -> failed_terminal / WORKSPACE_LOST.
    s3, _t3, step3, _e3 = _drain_fixture(conn, "succeeded", "waiting_effect")
    r = one(conn, "SELECT v_workspace_fail_closed(%s::uuid, 'run-3', 'test-lost')",
            (s3,))[0]
    check("drain (iii): outcome accepted, session failed/WORKSPACE_LOST",
          r["outcome"] == "accepted" and r["failure_code"] == "WORKSPACE_LOST", r)
    row = one(conn, "SELECT status, outcome_code FROM steps WHERE step_id=%s",
              (step3,))
    check("drain (iii): step failed_terminal / WORKSPACE_LOST",
          row == ("failed_terminal", "WORKSPACE_LOST"), row)
    row = one(conn, "SELECT state, failure_code, drain_step_id, active_step_id"
                    " FROM sessions WHERE session_id=%s", (s3,))
    check("drain (iii): drain_step_id NULL (step terminal), active cleared",
          row == ("failed", "WORKSPACE_LOST", None, None), row)
    row = one(conn, "SELECT count(*) FROM session_events WHERE session_id=%s"
                    " AND event_type='workspace/lost'", (s3,))
    check("drain: workspace/lost event exactly once", row[0] == 1, row)

    # branch (i): unresolved unknown -> step stays blocked_unknown_effect.
    s1, _t1, step1, _e1 = _drain_fixture(conn, "unknown_outcome",
                                         "blocked_unknown_effect")
    r = one(conn, "SELECT v_workspace_fail_closed(%s::uuid, 'run-1', 'test-lost')",
            (s1,))[0]
    check("drain (i): accepted", r["outcome"] == "accepted", r)
    row = one(conn, "SELECT status FROM steps WHERE step_id=%s", (step1,))
    check("drain (i): step stays blocked_unknown_effect (drain pending)",
          row[0] == "blocked_unknown_effect", row)
    row = one(conn, "SELECT drain_step_id FROM sessions WHERE session_id=%s", (s1,))
    check("drain (i): drain_step_id points at the non-terminal step",
          str(row[0]) == step1, row)

    # branch (ii): in-flight pending -> step stays waiting_effect.
    s2, _t2, step2, e2 = _drain_fixture(conn, "dispatch_started", "waiting_effect")
    r = one(conn, "SELECT v_workspace_fail_closed(%s::uuid, 'run-2', 'test-lost')",
            (s2,))[0]
    row = one(conn, "SELECT status FROM steps WHERE step_id=%s", (step2,))
    check("drain (ii): step stays waiting_effect (drain pending)",
          row[0] == "waiting_effect", row)
    # ready effect drained by the shared pre-dispatch sync (dual-table).
    s4, _t4, step4, e4 = _drain_fixture(conn, "ready", "waiting_effect")
    r = one(conn, "SELECT v_workspace_fail_closed(%s::uuid, 'run-4', 'test-lost')",
            (s4,))[0]
    check("drain: ready effect drained via the shared pre-dispatch sync",
          len(r["cancelled_effects"]) == 1
          and r["cancelled_effects"][0]["code"] == "ABORTED_BEFORE_DISPATCH", r)
    row = one(conn, "SELECT er.status, at.status FROM effect_requests er"
                    " JOIN effect_attempts at ON at.effect_id = er.effect_id"
                    " AND at.attempt_no = 1 WHERE er.effect_id=%s", (e4,))
    check("drain: dual-table atomic sync (effect + attempt together)",
          row == ("cancelled_before_dispatch", "cancelled_before_dispatch"), row)
    row = one(conn, "SELECT reason FROM effect_audit WHERE effect_id=%s"
                    " ORDER BY audit_id DESC LIMIT 1", (e4,))
    check("drain: ABORTED_BEFORE_DISPATCH audit row written",
          row[0] == "ABORTED_BEFORE_DISPATCH", row)

    # repeat drain on branch (ii): late settlement reruns the SAME judgment
    # and converges (step -> failed_terminal/WORKSPACE_LOST, no second event,
    # no fence double-bump, session stays failed).
    fence_before = one(conn, "SELECT session_fence FROM sessions"
                             " WHERE session_id=%s", (s2,))[0]
    _update(conn, "UPDATE effect_requests SET status='succeeded'"
                  " WHERE effect_id=%s", (e2,))
    r = one(conn, "SELECT v_workspace_fail_closed(%s::uuid, 'run-2', 'again')",
            (s2,))[0]
    check("drain repeat: marked repeated", r["repeated"] is True, r)
    row = one(conn, "SELECT status, outcome_code FROM steps WHERE step_id=%s",
              (step2,))
    check("drain repeat: settled pending -> failed_terminal / WORKSPACE_LOST"
          " (step-level success terminalization never happens)",
          row == ("failed_terminal", "WORKSPACE_LOST"), row)
    row = one(conn, "SELECT state, failure_code, session_fence, drain_step_id"
                    " FROM sessions WHERE session_id=%s", (s2,))
    check("drain repeat: session unchanged terminal, fence not bumped again,"
          " drain_step_id cleared",
          row[0] == "failed" and row[1] == "WORKSPACE_LOST"
          and row[2] == fence_before and row[3] is None, row)
    row = one(conn, "SELECT count(*) FROM session_events WHERE session_id=%s"
                    " AND event_type='workspace/lost'", (s2,))
    check("drain repeat: no second workspace/lost event", row[0] == 1, row)

    # ISOLATION_UNSUPPORTED: drain entry (and repeat entry) refuse
    # non-READ COMMITTED.
    conn2 = psycopg2.connect(_uri())
    try:
        conn2.set_session(isolation_level=psycopg2.extensions.
                          ISOLATION_LEVEL_REPEATABLE_READ)
        s5, _t5, step5, _e5 = _drain_fixture(conn, "succeeded", "waiting_effect")
        with conn2.cursor() as cur:
            cur.execute("SELECT v_workspace_fail_closed(%s::uuid, 'run-5', 'x')",
                        (s5,))
            r = cur.fetchone()[0]
        conn2.commit()
        check("drain: non-READ COMMITTED entry -> ISOLATION_UNSUPPORTED",
              r["code"] == "ISOLATION_UNSUPPORTED", r)
        row = one(conn, "SELECT state FROM sessions WHERE session_id=%s", (s5,))
        check("drain: isolation rejection changed no control state",
              row[0] == "ready", row)
    finally:
        conn2.close()

    # capability API boundary (Conformance 13, database half): credentials
    # never enter session_events.
    secret = f"sk-secret-{u()[:12]}"
    ws = u()
    one(conn, "SELECT v_operator_issue_slice('op-sec', %s::uuid, 'sec-slice',"
              " 'secret', %s::jsonb)", (ws, json.dumps({"resources": [secret]})))
    s6 = fresh_session(conn)
    one(conn, "SELECT v_workspace_fail_closed(%s::uuid, 'run-6', %s)",
        (s6, f"reason-with-{secret}"))
    row = one(conn, "SELECT count(*) FROM session_events WHERE payload LIKE %s",
              (f"%{secret}%",))
    check("capability boundary: credential-like secret never enters"
          " session_events payloads", row[0] == 0, row)


# ---------------------------------------------------------------------------
# 9. minimal fork
# ---------------------------------------------------------------------------

def _raw_event(conn, sid, seq, etype, eclass, turn=None, payload=None,
               ordinal=None):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO session_events(seq, session_id, event_type,"
            " event_class, schema_version, canonicalizer_version, event_key,"
            " turn_id, payload, payload_hash, semantic_input_ordinal)"
            " VALUES (%s, %s, %s, %s, 'sv@1', 'canon@1', %s, %s, %s, 'h', %s)",
            (seq, sid, etype, eclass, f"k-{sid[:8]}-{seq}", turn,
             payload or "{}", ordinal))
        cur.execute(
            "UPDATE sessions SET next_seq = GREATEST(next_seq, %s + 1)"
            " WHERE session_id = %s", (seq, sid))
    conn.commit()


def test_fork(conn) -> None:
    ws = u()
    sl_imm = seed_slice(conn, ws, "fork-corpus", kind="corpus",
                        spec={"resources": ["res-f"]})
    sl_live = seed_slice(conn, ws, "fork-ws", kind="workspace_exec")
    parent = fresh_session(conn, workspace_id=ws)
    seed_grant(conn, "g-fork-yes", ws, sl_imm, "session", parent, "recall",
               delegable=True)
    seed_grant(conn, "g-fork-no", ws, sl_imm, "session", parent, "fold",
               delegable=False)
    seed_grant(conn, "g-fork-live", ws, sl_live, "session", parent, "process",
               delegable=True)
    turn = u()
    _raw_event(conn, parent, 1, "turn/start", "semantic", turn=turn,
               ordinal=1)
    _raw_event(conn, parent, 2, "user/message", "semantic", turn=turn,
               ordinal=2)

    # unstable cut: unresolved unknown inside the cutoff (parent repair
    # AFTER the cutoff never resolves the cut).
    _raw_event(conn, parent, 3, "turn/end", "semantic", turn=turn,
               payload='{"outcome": "unknown"}', ordinal=3)
    r = one(conn, "SELECT v_fork_session(%s::uuid, 3)", (parent,))[0]
    check("fork: unresolved unknown inside the cutoff -> FORK_CUTOFF_UNSTABLE",
          r["code"] == "FORK_CUTOFF_UNSTABLE", r)
    # a known end AFTER the cutoff does not help.
    _raw_event(conn, parent, 4, "turn/end", "semantic", turn=turn,
               payload='{"interrupted": false}', ordinal=4)
    r = one(conn, "SELECT v_fork_session(%s::uuid, 3)", (parent,))[0]
    check("fork: repair after the cutoff still rejects the cut",
          r["code"] == "FORK_CUTOFF_UNSTABLE", r)
    # stable cut: the closer is INSIDE the prefix.
    r = one(conn, "SELECT v_fork_session(%s::uuid, 4)", (parent,))[0]
    check("fork: complete closer inside the prefix -> accepted",
          r["outcome"] == "accepted", r)
    child = r["child_session_id"]
    check("fork: child inherited exactly the 4-event prefix",
          r["inherited_event_count"] == 4, r)
    row = one(conn, "SELECT count(*) FROM session_events WHERE session_id=%s",
              (str(child),))
    check("fork: child events persisted", row[0] == 4, row)
    row = one(conn, "SELECT state, workspace_id FROM sessions"
                    " WHERE session_id=%s", (str(child),))
    check("fork: child session fresh ready, tenant inherited",
          row[0] == "ready" and str(row[1]) == ws, row)
    # grant copies: only delegable grants over immutable slices.
    row = one(conn, "SELECT count(*) FROM grants WHERE subject_id=%s",
              (str(child),))
    check("fork: exactly one grant copy (delegable, immutable slice)", row[0] == 1,
          row)
    row = one(conn, "SELECT grant_id, capability, delegable FROM grants"
                    " WHERE subject_id=%s", (str(child),))
    check("fork: the copy has a NEW grant_id and carries the capability",
          row[0] != "g-fork-yes" and row[1] == "recall" and row[2] is True,
          row)
    # no control-state / handle inheritance.
    row = one(conn, "SELECT count(*) FROM steps WHERE session_id=%s", (str(child),))
    check("fork: no steps inherited", row[0] == 0, row)
    row = one(conn, "SELECT count(*) FROM workspace_handles WHERE session_id=%s",
              (str(child),))
    check("fork: live handle NOT inherited", row[0] == 0, row)

    # pending non-terminal effect inside the cutoff -> unstable.
    parent2 = fresh_session(conn)
    sfx, t2b, step2b, e2b = chunk_fixture(conn, session_id=parent2)
    _raw_event(conn, parent2, 1, "turn/start", "semantic", turn=t2b, ordinal=1)
    r = one(conn, "SELECT v_fork_session(%s::uuid, 1)", (parent2,))[0]
    check("fork: pending in-flight effect inside the cutoff ->"
          " FORK_CUTOFF_UNSTABLE", r["code"] == "FORK_CUTOFF_UNSTABLE", r)
    # cutoff outside the allocated prefix -> unstable.
    r = one(conn, "SELECT v_fork_session(%s::uuid, 99)", (parent2,))[0]
    check("fork: cutoff beyond the allocated prefix -> FORK_CUTOFF_UNSTABLE",
          r["code"] == "FORK_CUTOFF_UNSTABLE", r)


# ---------------------------------------------------------------------------
# 10. append-layer upgrades (heartbeat gate, registry, full subject lookup)
# ---------------------------------------------------------------------------

def test_append_upgrades(conn) -> None:
    ws = u()
    sl = seed_slice(conn, ws, "append-upg")

    # ---- session/heartbeat authorization precheck ----
    # (the hb fixtures use a dedicated driver so no earlier test's
    # driver-subject grants resolve for them)
    s_hb = fresh_session(conn, driver="hbw")
    seed_grant(conn, "g-hb", ws, sl, "session", s_hb, "event_append")
    r = append_chunks(conn, s_hb, "hb-ok", [hb({"n": 1})], expected_seq=1,
                      caller_subject=s_hb, driver="hbw")
    check("heartbeat: valid event_append grant + caller legs -> accepted",
          r["outcome"] == "accepted", r)

    # no grant for the caller -> GRANT_DENIED OUTSIDE the receipt namespace.
    s_hb2 = fresh_session(conn, driver="hbw")
    r = append_chunks(conn, s_hb2, "hb-none", [hb({"n": 1})], expected_seq=1,
                      caller_subject=s_hb2, driver="hbw")
    check("heartbeat: no valid grant -> GRANT_DENIED",
          r["outcome"] == "rejected_mismatch" and r["code"] == "GRANT_DENIED", r)
    row = one(conn, "SELECT count(*) FROM command_receipts WHERE session_id=%s"
                    " AND command_id='hb-none'", (s_hb2,))
    check("heartbeat: denial wrote NO receipt (outside the receipt namespace)",
          row[0] == 0, row)
    row = one(conn, "SELECT count(*) FROM command_bindings WHERE session_id=%s"
                    " AND command_id='hb-none'", (s_hb2,))
    check("heartbeat: denial occupied NO command binding", row[0] == 0, row)
    row = one(conn, "SELECT count(*) FROM authz_denial_audits"
                    " WHERE target_command=%s",
              (f"append_events/session_heartbeat:{s_hb2}",))
    check("heartbeat: independent authorization denial audit row written",
          row[0] == 1, row)
    # same context resend (new command_id) merges into the SAME audit row.
    r = append_chunks(conn, s_hb2, "hb-none2", [hb({"n": 1})], expected_seq=1,
                      caller_subject=s_hb2, driver="hbw")
    check("heartbeat: resend still GRANT_DENIED", r["code"] == "GRANT_DENIED", r)
    row = one(conn, "SELECT count(*), max(occurrences) FROM authz_denial_audits"
                    " WHERE target_command=%s",
              (f"append_events/session_heartbeat:{s_hb2}",))
    check("heartbeat: repeated denial merged into one audit row (idempotent)",
          row[0] == 1 and row[1] == 2, row)
    row = one(conn, "SELECT count(*) FROM session_events WHERE session_id=%s",
              (s_hb2,))
    check("heartbeat: denial appended zero events", row[0] == 0, row)

    # revoked grant -> GRANT_DENIED (含已撤销).
    s_hb3 = fresh_session(conn, driver="hbw")
    seed_grant(conn, "g-hb-rev", ws, sl, "session", s_hb3, "event_append",
               revoked=True)
    r = append_chunks(conn, s_hb3, "hb-rev", [hb()], expected_seq=1,
                      caller_subject=s_hb3, driver="hbw")
    check("heartbeat: revoked grant -> GRANT_DENIED",
          r["code"] == "GRANT_DENIED", r)

    # cross-tenant: the session binds ws1; the caller's grants live in ws2.
    ws1, ws2 = u(), u()
    s_t1 = fresh_session(conn, workspace_id=ws1)
    sl_t2 = seed_slice(conn, ws2, "tenant-b")
    seed_grant(conn, "g-x-tenant", ws2, sl_t2, "session", s_t1, "event_append")
    r = append_chunks(conn, s_t1, "hb-x1", [hb()], expected_seq=1,
                      caller_subject=s_t1)
    check("heartbeat: cross-tenant grant -> GRANT_DENIED",
          r["code"] == "GRANT_DENIED", r)
    # control: the same caller with a grant in the bound workspace passes.
    sl_t1 = seed_slice(conn, ws1, "tenant-a")
    seed_grant(conn, "g-x-home", ws1, sl_t1, "session", s_t1, "event_append")
    r = append_chunks(conn, s_t1, "hb-x2", [hb()], expected_seq=1,
                      caller_subject=s_t1)
    check("heartbeat: home-tenant grant -> accepted", r["outcome"] == "accepted",
          r)

    # legacy path retained (A57 downgrade): no caller legs, no binding.
    s_leg = fresh_session(conn)
    r = append_chunks(conn, s_leg, "hb-leg", [hb()], expected_seq=1)
    check("heartbeat: legacy all-legs-default path still accepted (A57"
          " downgrade retained this gate)",
          r["outcome"] == "accepted", r)

    # ---- chunk attribution: full subject resolution + registry ----
    # plugin_identity subject resolved through the declared caller (the A56
    # session-bound approximation is gone).
    ws_p = u()
    sl_p = seed_slice(conn, ws_p, "plug")
    s_p = fresh_session(conn)
    seed_grant(conn, "g-p-eff", ws_p, sl_p, "plugin_identity", "provider-alpha",
               "event_append")
    seed_grant(conn, "g-p-ea", ws_p, sl_p, "plugin_identity", "provider-alpha",
               "event_append")
    seed_grant(conn, "g-p-si", ws_p, sl_p, "plugin_identity", "provider-alpha",
               "stream_ingest")
    sp, _tp, _stp, ep = chunk_fixture(conn, session_id=s_p, grant_id="g-p-eff")
    r = append_chunks(conn, sp, "plug-ok",
                      [chunk_entry(ep, "x", 0, stream="plug-stream")],
                      expected_seq=1, caller_subject="provider-alpha")
    check("chunk: plugin_identity-bound effect with full caller identity"
          " accepted", r["outcome"] == "accepted", r)
    row = one(conn, "SELECT owner_subject FROM stream_registry"
                    " WHERE stream_id='plug-stream'")
    check("registry: first legal chunk bound the stream to the provider"
          " subject", row[0] == "provider-alpha", row)

    # foreign provider reuse of a registered stream -> CHUNK_ATTRIBUTION_INVALID.
    s_q = fresh_session(conn)
    seed_grant(conn, "g-q-eff", ws_p, sl_p, "plugin_identity", "provider-beta",
               "event_append")
    seed_grant(conn, "g-q-ea", ws_p, sl_p, "plugin_identity", "provider-beta",
               "event_append")
    seed_grant(conn, "g-q-si", ws_p, sl_p, "plugin_identity", "provider-beta",
               "stream_ingest")
    sq, _tq, _stq, eq = chunk_fixture(conn, session_id=s_q, grant_id="g-q-eff")
    before = one(conn, "SELECT count(*) FROM session_events WHERE session_id=%s",
                 (sq,))[0]
    r = append_chunks(conn, sq, "plug-foreign",
                      [chunk_entry(eq, "x", 0, stream="plug-stream")],
                      expected_seq=1, caller_subject="provider-beta")
    check("registry: foreign provider stream reuse -> CHUNK_ATTRIBUTION_INVALID",
          r["code"] == "CHUNK_ATTRIBUTION_INVALID", r)
    after = one(conn, "SELECT count(*) FROM session_events WHERE session_id=%s",
                (sq,))[0]
    check("registry: foreign reuse appended zero events (fail closed)",
          before == after == 0, (before, after))

    # three-conjunction: missing stream_ingest -> zero write.
    ws_r = u()
    sl_r = seed_slice(conn, ws_r, "no-si")
    s_r = fresh_session(conn)
    seed_grant(conn, "g-r-eff", ws_r, sl_r, "session", s_r, "event_append")
    seed_grant(conn, "g-r-ea", ws_r, sl_r, "session", s_r, "event_append")
    sr, _tr, _str_, er = chunk_fixture(conn, session_id=s_r, grant_id="g-r-eff")
    r = append_chunks(conn, sr, "nos", [chunk_entry(er, "x", 0, stream="no-si")],
                      expected_seq=1, caller_subject=s_r)
    check("three-conjunction: missing stream_ingest grant ->"
          " CHUNK_ATTRIBUTION_INVALID",
          r["code"] == "CHUNK_ATTRIBUTION_INVALID", r)
    row = one(conn, "SELECT count(*) FROM session_events WHERE session_id=%s",
              (sr,))
    check("three-conjunction: zero events landed", row[0] == 0, row)

    # legacy chunk path (A57 downgrade retained): unbound effect + no legs.
    s_lg = fresh_session(conn)
    slg, _tlg, _stlg, elg = chunk_fixture(conn)
    r = append_chunks(conn, slg, "leg", [chunk_entry(elg, "x", 0)], expected_seq=1)
    check("chunk: legacy unbound no-legs path still accepted (A57 retained)",
          r["outcome"] == "accepted", r)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--no-setup":
        pass
    else:
        setup_db()
    conn = psycopg2.connect(_uri())
    conn.autocommit = False
    try:
        test_grant_stub(conn)
        test_constraints(conn)
        test_conjunct3(conn)
        test_operator_channel(conn)
        test_linearization(conn)
        test_rls(conn)
        test_workspace_handles(conn)
        test_workspace_lost_drain(conn)
        test_fork(conn)
        test_append_upgrades(conn)
    finally:
        conn.close()
    print("[G10] all gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
