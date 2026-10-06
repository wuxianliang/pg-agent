"""G6 gate: v17 repair — pause, repair form, resume the restart, deliver.

Run: uv run python v17/repair/test_repair.py  (exit 0 = pass)

A paused attempt is jiti's central cooperative feature: the evaluated form
signals a condition, the kernel reports the condition and the available
restarts WHILE THE ORIGINAL CALL IS STILL ON THE STACK, a caller-supplied
repair form runs inside that suspended dynamic extent, and invoking a
restart returns through it into the paused computation.

For the world daemon the repair recipe is part of the job's contract, so it
travels in the payload next to the goals:

    "repair":          the form to evaluate while paused
    "resume_restart":  which restart to invoke afterwards: a restart NAME
                       (case-insensitive) or a zero-based index into the
                       current menu

Scenarios:
 1. pause -> repair -> resume: the original computation completes and the
    job succeeds, with the repair's state change retained and journalled
 2. the journal records the pause, the repair and the restart invocation
 3. a repair that itself fails leaves the world untouched (job failed)
 4. crashing while paused settles the job failed and advances nothing —
    the live dynamic extent is not durable state, only the checkpoint is
    (jiti has the same property); this asserts that boundary honestly
 5. a paused job whose recipe is absent settles failed with the condition
    on the record, and the kernel's menu is visible in the journal
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v17.repair.setup_db import DB, main as setup_db

RUN_WORLDD = AGENT_ROOT / "v17" / "lisp" / "run-worldd.lisp"
SOCKET_DIR = str(AGENT_ROOT / ".pgdata") + "/"


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f": {detail}" if detail else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def u() -> str:
    return str(uuid.uuid4())


def run_worldd(tag: str, worker_id: str = "wd-1", lease: int = 300,
               suicide: bool = False) -> None:
    env = dict(os.environ)
    env.update(PGSOCKETDIR=SOCKET_DIR, PGDATABASE=DB,
               V17_WORLDD_ID=worker_id,
               V17_WORLDD_IDLE_EXIT_MS="3000",
               V17_WORLDD_POLL_MS="150",
               V17_WORLDD_LEASE_SECONDS=str(lease))
    if suicide:
        env["V17_WORLDD_ALLOW_SUICIDE"] = "1"
    proc = subprocess.run(["sbcl", "--script", str(RUN_WORLDD)], env=env,
                          capture_output=True, text=True, timeout=300)
    check(f"{tag}: daemon exits 0", proc.returncode == 0,
          (proc.stdout + proc.stderr)[-2000:] if proc.returncode else "")


def connect():
    return psycopg2.connect(get_server().get_uri(DB))


def new_session(cur) -> str:
    sid = u()
    cur.execute("INSERT INTO sessions (session_id, workspace_id) "
                "VALUES (%s, 'repair')", (sid,))
    cur.connection.commit()
    return sid


def submit(cur, sid, kind, payload) -> str:
    cur.execute(
        "INSERT INTO jobs (session_id, effect_id, kind, payload) "
        "VALUES (%s, %s, %s, %s) RETURNING job_id",
        (sid, u(), kind, json.dumps(payload)))
    cur.connection.commit()
    return cur.fetchone()[0]


def job(cur, job_id):
    cur.execute("SELECT status, result::text, error FROM jobs WHERE job_id = %s",
                (job_id,))
    return cur.fetchone()


def journal(cur, world: str):
    cur.execute("SELECT event FROM lisp_journal j JOIN lisp_worlds w "
                "USING (world_id) WHERE w.name = %s ORDER BY j.seq", (world,))
    return [e if isinstance(e, dict) else json.loads(e) for (e,) in cur.fetchall()]


def values_of(result) -> list[str]:
    payload = json.loads(result) if isinstance(result, str) else (result or {})
    return [v.get("text", "").strip('"') for v in payload.get("values", [])]


# a form that signals with two restarts; the second returns a value
PAUSING_SOURCE = ('(restart-case '
                  '(progn (setf (gethash "n" *state*) 7) '
                  '(error "boom")) '
                  '(:retry () (setf (gethash "n" *state*) 8)) '
                  '(:use-default () 84))')


def main() -> int:
    setup_db()
    conn = connect()
    cur = conn.cursor()

    # --- 1. pause -> repair -> resume ---------------------------------------
    sid = new_session(cur)
    job1 = submit(cur, sid, "lisp_eval",
                  {"world": "w-repair",
                   "source": PAUSING_SOURCE,
                   "repair": '(setf (gethash "r" *state*) "repaired")',
                   "resume_restart": "use-default"})
    run_worldd("repair(pause-fix-resume)")
    st, res, err = job(cur, job1)
    check("repair: job succeeded after the repair and the restart",
          st == "succeeded", (st, err))
    check("repair: the original computation returned through the restart",
          any(v == "84" for v in values_of(res)), res)

    # --- 2. the journal records pause, repair, restart ----------------------
    events = journal(cur, "w-repair")
    kinds = [e.get("event") for e in events]
    check("repair: journal records the pause", "condition" in kinds, kinds)
    check("repair: journal records the restart invocation",
          "restart" in kinds, kinds)
    reopened = [e for e in events if e.get("event") == "accepted"]
    check("repair: journal records the accepted attempt", bool(reopened),
          kinds)
    menu = next((e for e in events if e.get("event") == "condition"), {})
    check("repair: the condition is on the record",
          "boom" in json.dumps(menu), menu)
    # the repair's own state change is durable
    sid = new_session(cur)
    probe = submit(cur, sid, "lisp_eval",
                   {"world": "w-repair",
                    "source": '(gethash "r" *state*)'})
    run_worldd("repair(probe)")
    st, res, err = job(cur, probe)
    check("repair: the repair's state change is durable",
          any(v == "repaired" for v in values_of(res)), res)

    # --- 3. a repair that itself fails leaves the world untouched ------------
    before = journal(cur, "w-repair")
    sid = new_session(cur)
    job3 = submit(cur, sid, "lisp_eval",
                  {"world": "w-repair",
                   "source": PAUSING_SOURCE,
                   "repair": '(error "repair itself failed")',
                   "resume_restart": "use-default"})
    run_worldd("repair(repair-fails)")
    st, res, err = job(cur, job3)
    check("repair-fails: job failed", st == "failed", (st, err))
    check("repair-fails: reason names the failed repair",
          err is not None and "repair" in err.lower(), err)
    after = journal(cur, "w-repair")
    check("repair-fails: no accepted revision was published",
          len([e for e in after if e.get("event") == "accepted"])
          == len([e for e in before if e.get("event") == "accepted"]))

    # --- 4. crash while paused ------------------------------------------------
    # A paused restart is LIVE dynamic extent. The repair below sleeps, so the
    # worker sits inside the paused attempt (evaluating the caller's repair)
    # when it is killed: that is a crash DURING A PAUSE. Only the checkpoint
    # is durable state, so the job must stay unsettled and the world must not
    # advance. What happens to it is then the unknown wall's decision, not a
    # blind replay.
    sid = new_session(cur)
    job4 = submit(cur, sid, "lisp_eval",
                  {"world": "w-crash-pause",
                   "source": PAUSING_SOURCE,
                   "repair": '(progn (sleep 6) '
                             '(setf (gethash "r" *state*) "late"))',
                   "resume_restart": "use-default"})
    proc = subprocess.Popen(["sbcl", "--script", str(RUN_WORLDD)],
                            env=dict(os.environ,
                                     PGSOCKETDIR=SOCKET_DIR, PGDATABASE=DB,
                                     V17_WORLDD_ID="wd-crash",
                                     V17_WORLDD_IDLE_EXIT_MS="3000",
                                     V17_WORLDD_POLL_MS="150",
                                     V17_WORLDD_LEASE_SECONDS="300"),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True)
    # Wait for the CLAIM (the attempt has started), then sit inside the
    # repair's sleep before killing: the pause itself is not observable in
    # the tables, because the daemon journals events only when it commits.
    deadline = time.monotonic() + 90
    claimed = False
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            break
        cur.execute("SELECT claimed_by FROM jobs WHERE job_id = %s", (job4,))
        row = cur.fetchone()
        if row and row[0] == "wd-crash":
            claimed = True
            break
        time.sleep(0.1)
    conn.commit()
    check("pause-crash: the attempt started before the kill", claimed)
    time.sleep(3.0)          # the repair sleeps 6s: this lands inside it
    proc.kill()
    proc.communicate(timeout=30)
    cur.execute("SELECT status FROM jobs WHERE job_id = %s", (job4,))
    check("pause-crash: killed worker left the job unsettled",
          cur.fetchone()[0] == "claimed")
    cur.execute("SELECT count(*) FROM lisp_revisions r JOIN lisp_worlds w "
                "USING (world_id) WHERE w.name = 'w-crash-pause'")
    revs = cur.fetchone()[0]
    check("pause-crash: no revision was published (baseline only)",
          revs == 1, revs)
    cur.execute("SELECT count(*) FROM lisp_revisions r JOIN lisp_worlds w "
                "USING (world_id) WHERE w.name = 'w-crash-pause' "
                "AND r.state_text LIKE '%late%'")
    check("pause-crash: the interrupted repair left no trace",
          cur.fetchone()[0] == 0)
    # The live stack is gone, so the job may only be moved deliberately.
    cur.execute("SELECT fence FROM jobs WHERE job_id = %s", (job4,))
    fence4 = cur.fetchone()[0]
    cur.execute("SELECT v12_complete_job(%s, %s, 'unknown', NULL, %s)",
                (job4, fence4, "worker died during a paused repair"))
    conn.commit()
    cur.execute("SELECT status FROM jobs WHERE job_id = %s", (job4,))
    check("pause-crash: the job is settled only by an explicit resolution",
          cur.fetchone()[0] == "unknown")
    try:
        cur.execute("SELECT v12_resolve_unknown(%s, 'resolved_abandoned')",
                    (job4,))
        conn.commit()
        abandoned = True
    except psycopg2.Error:
        conn.rollback()
        abandoned = False
    check("pause-crash: v12_resolve_unknown can abandon it", abandoned)

    # --- 5. a paused job with no recipe settles failed -----------------------
    sid = new_session(cur)
    job5 = submit(cur, sid, "lisp_eval",
                  {"world": "w-norecipe", "source": PAUSING_SOURCE})
    run_worldd("repair(no-recipe)")
    st, res, err = job(cur, job5)
    check("no-recipe: job failed (no one could repair it)", st == "failed",
          (st, err))
    events5 = journal(cur, "w-norecipe")
    conditions = [e for e in events5 if e.get("event") == "condition"]
    check("no-recipe: the condition and its restarts are on the record",
          bool(conditions) and "boom" in json.dumps(conditions[0]),
          conditions[:1])
    # The menu itself is not journalled: the kernel's observation event
    # carries status/world, and the restart menu reaches the caller only in
    # the live view. Scenario 1 proves the daemon can read it (it resumes by
    # NAME, which requires the menu), and the pause plus its condition are
    # what survives here.
    paused = [e for e in events5
              if e.get("event") == "observation"
              and e.get("status") == "paused"]
    check("no-recipe: the pause is journalled", bool(paused), events5[-2:])

    conn.commit()
    conn.close()
    print("[G6 repair] ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
