"""G3 gate: v12 act stage — effect discipline: identity, fence, lease, unknown.

Run: uv run python v12/act/test_act.py  (exit 0 = pass)
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v12.act.setup_db import DB, main as setup_db


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f": {detail}" if detail else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def u() -> str:
    return str(uuid.uuid4())


def fails_with(cur, sql: str, params: tuple, needle: str, label: str) -> None:
    cur.execute("SAVEPOINT sp")
    try:
        cur.execute(sql, params)
    except psycopg2.Error as exc:
        msg = str(exc).lower()
        check(label, needle in msg, str(exc).splitlines()[0])
        cur.execute("ROLLBACK TO SAVEPOINT sp")
        return
    cur.execute("ROLLBACK TO SAVEPOINT sp")
    raise AssertionError(f"{label}: expected failure containing {needle!r}, got success")


def status(cur, job) -> str:
    cur.execute("SELECT status FROM jobs WHERE job_id = %s", (job,))
    return cur.fetchone()[0]


def main() -> int:
    setup_db()
    server = get_server()
    conn = psycopg2.connect(server.get_uri(DB))
    cur = conn.cursor()
    sid = u()
    cur.execute("INSERT INTO sessions (session_id, workspace_id) VALUES (%s, 'w1')",
                (sid,))

    # --- identity: enqueue is idempotent by effect_id -----------------------
    eff = u()
    j1 = None
    cur.execute("SELECT v12_enqueue_effect(%s, %s, 'email', %s)",
                (sid, eff, json.dumps({"to": "a@b.c"})))
    j1 = cur.fetchone()[0]
    cur.execute("SELECT v12_enqueue_effect(%s, %s, 'email', %s)",
                (sid, eff, json.dumps({"to": "a@b.c"})))
    check("identity: re-enqueue while queued returns same job",
          cur.fetchone()[0] == j1)
    cur.execute("SELECT count(*) FROM jobs WHERE effect_id = %s", (eff,))
    check("identity: exactly one job row", cur.fetchone()[0] == 1)

    # --- claim / fence / lease ----------------------------------------------
    fails_with(cur, "SELECT v12_claim_job(%s, 'w2', 60)", (u(),),
               "not claimable", "claim: unknown job rejected")

    f1 = None
    cur.execute("SELECT v12_claim_job(%s, 'w1', 60)", (j1,))
    f1 = cur.fetchone()[0]
    check("claim: first claim -> fence 1", f1 == 1)
    fails_with(cur, "SELECT v12_claim_job(%s, 'w2', 60)", (j1,),
               "not claimable", "claim: live lease blocks second claim")

    fails_with(cur, "SELECT v12_complete_job(%s, %s, 'succeeded')", (j1, f1 + 7),
               "rejected", "complete: wrong fence rejected")
    cur.execute("SELECT v12_complete_job(%s, %s, 'succeeded', %s)",
                (j1, f1, json.dumps({"sent": True})))
    check("complete: correct fence settles", status(cur, j1) == "succeeded")
    fails_with(cur, "SELECT v12_complete_job(%s, %s, 'failed')", (j1, f1),
               "rejected", "complete: settling twice rejected")

    cur.execute("SELECT v12_enqueue_effect(%s, %s, 'email', %s)",
                (sid, eff, json.dumps({"to": "a@b.c"})))
    check("identity: re-enqueue after succeeded replays same job",
          cur.fetchone()[0] == j1 and status(cur, j1) == "succeeded")

    # --- retry after failure reuses identity ---------------------------------
    eff2 = u()
    cur.execute("SELECT v12_enqueue_effect(%s, %s, 'email', '{}')", (sid, eff2))
    j2 = cur.fetchone()[0]
    cur.execute("SELECT v12_claim_job(%s, 'w1', 60)", (j2,))
    f2 = cur.fetchone()[0]
    cur.execute("SELECT v12_complete_job(%s, %s, 'failed', NULL, 'smtp 500')",
                (j2, f2))
    check("retry: failed job recorded", status(cur, j2) == "failed")
    cur.execute("SELECT v12_enqueue_effect(%s, %s, 'email', '{}')", (sid, eff2))
    j2b = cur.fetchone()[0]
    check("retry: re-enqueue after failure reuses job", j2b == j2)
    check("retry: job back to queued", status(cur, j2) == "queued")

    # --- lease expiry takeover ------------------------------------------------
    eff3 = u()
    cur.execute("SELECT v12_enqueue_effect(%s, %s, 'email', '{}')", (sid, eff3))
    j3 = cur.fetchone()[0]
    cur.execute("SELECT v12_claim_job(%s, 'slow-worker', 1)", (j3,))
    f3a = cur.fetchone()[0]
    time.sleep(1.2)
    cur.execute("SELECT v12_claim_job(%s, 'fast-worker', 60)", (j3,))
    f3b = cur.fetchone()[0]
    check("takeover: expired lease can be reclaimed (fence bumped)",
          f3b == f3a + 1, (f3a, f3b))
    fails_with(cur, "SELECT v12_complete_job(%s, %s, 'succeeded')", (j3, f3a),
               "rejected", "takeover: stale worker cannot complete")
    cur.execute("SELECT v12_complete_job(%s, %s, 'succeeded', %s)",
                (j3, f3b, json.dumps({"ok": 1})))
    check("takeover: new fence settles", status(cur, j3) == "succeeded")

    # lease expired but nobody took over: completion is still refused —
    # the worker lost its mandate when the lease lapsed.
    eff4 = u()
    cur.execute("SELECT v12_enqueue_effect(%s, %s, 'email', '{}')", (sid, eff4))
    j4 = cur.fetchone()[0]
    cur.execute("SELECT v12_claim_job(%s, 'w1', 1)", (j4,))
    f4 = cur.fetchone()[0]
    time.sleep(1.2)
    fails_with(cur, "SELECT v12_complete_job(%s, %s, 'succeeded')", (j4, f4),
               "rejected", "lease: completing after own lease lapsed is rejected")
    check("lease: job still claimed for the next claimant", status(cur, j4) == "claimed")

    # --- unknown is a wall -----------------------------------------------------
    eff5 = u()
    cur.execute("SELECT v12_enqueue_effect(%s, %s, 'email', '{}')", (sid, eff5))
    j5 = cur.fetchone()[0]
    cur.execute("SELECT v12_claim_job(%s, 'w1', 60)", (j5,))
    f5 = cur.fetchone()[0]
    cur.execute("SELECT v12_complete_job(%s, %s, 'unknown', NULL, 'timeout mid-send')",
                (j5, f5))
    check("unknown: recorded as unknown", status(cur, j5) == "unknown")

    fails_with(cur, "SELECT v12_enqueue_effect(%s, %s, 'email', '{}')", (sid, eff5),
               "unknown", "unknown: blind re-enqueue rejected")
    fails_with(cur, "SELECT v12_claim_job(%s, 'w2', 60)", (j5,),
               "not claimable", "unknown: not claimable either")
    fails_with(cur, "SELECT v12_resolve_unknown(%s, 'retry_it')", (j5,),
               "bad resolution", "unknown: invalid resolution rejected")
    fails_with(cur, "SELECT v12_resolve_unknown(%s, 'resolved_ok')", (j3,),
               "only unknown", "unknown: cannot resolve a non-unknown job")

    cur.execute("SELECT v12_resolve_unknown(%s, 'resolved_ok', 'confirmed sent')",
                (j5,))
    check("unknown: explicit resolution works", status(cur, j5) == "resolved_ok")
    cur.execute("SELECT v12_enqueue_effect(%s, %s, 'email', '{}')", (sid, eff5))
    check("unknown: after resolved_ok, enqueue replays (no double send)",
          status(cur, j5) == "resolved_ok")

    # resolved_abandoned -> retry path reuses identity
    eff6 = u()
    cur.execute("SELECT v12_enqueue_effect(%s, %s, 'email', '{}')", (sid, eff6))
    j6 = cur.fetchone()[0]
    cur.execute("SELECT v12_claim_job(%s, 'w1', 60)", (j6,))
    f6 = cur.fetchone()[0]
    cur.execute("SELECT v12_complete_job(%s, %s, 'unknown', NULL, 'unclear')",
                (j6, f6))
    cur.execute("SELECT v12_resolve_unknown(%s, 'resolved_abandoned', 'not sent')",
                (j6,))
    cur.execute("SELECT v12_enqueue_effect(%s, %s, 'email', '{}')", (sid, eff6))
    check("unknown: resolved_abandoned allows retry with same identity",
          status(cur, j6) == "queued")

    # bad outcome
    cur.execute("SELECT v12_enqueue_effect(%s, %s, 'email', '{}')", (sid, u()))
    fails_with(cur, "SELECT v12_complete_job(%s, 1, 'exploded')", (u(),),
               "bad outcome", "complete: invalid outcome rejected")

    conn.commit()
    conn.close()
    print("[G3 act] ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
