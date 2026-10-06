"""G4 gate: v17 lisptools — `lisp:` tool jobs inside persistent SBCL worlds.

Run: uv run python v17/lisptools/test_lisptools.py  (exit 0 = pass)

The world daemon (v17/lisp/run-worldd.lisp) owns an effect class the
Python worker cannot express: developing and executing code inside a
SBCL world whose durability is Postgres. It finds work by scanning the
jobs table (no new queue, no new message kind, no new table, no v12
change) and settles it through v12's fence/lease discipline.

Scenarios (plan §5 G4):
 1. lisp_eval job end-to-end: effect settled, world advanced exactly one
    revision, values reported, operation journal complete
 2. lisp_develop job: a new function is durable (revision 2) and callable
    from a later process — the Postgres-is-the-recovery-surface claim
 3. preview job restores the world: no revision published at all
 4. goal failure rejects the develop (no revision, job failed, reason)
 5. invariant violation rejects and restores (no revision)
 6. crash between claim and settle: lease expiry -> second daemon
    reclaims -> visible effect exactly once (world advanced once)
 7. unknown wall: an EXTERNAL side effect happened, the daemon died before
    settling; the job may not be blind-replayed — only
    v12_resolve_unknown moves it, and it is never re-executed
 8. a `lisp:` tools.handler job: the params alist reaches the function
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
from v17.lisptools.setup_db import DB, main as setup_db

RUN_WORLDD = AGENT_ROOT / "v17" / "lisp" / "run-worldd.lisp"
SOCKET_DIR = str(AGENT_ROOT / ".pgdata") + "/"


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f": {detail}" if detail else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def u() -> str:
    return str(uuid.uuid4())


class Daemon:
    """One world-daemon process with its own identity and timing knobs."""

    def __init__(self, tag: str, worker_id: str = "wd-1", lease: int = 300,
                 suicide: bool = False):
        self.tag = tag
        self.worker_id = worker_id
        self.lease = lease
        self.suicide = suicide

    def env(self) -> dict:
        env = dict(os.environ)
        env.update(
            PGSOCKETDIR=SOCKET_DIR, PGDATABASE=DB,
            V17_WORLDD_ID=self.worker_id,
            V17_WORLDD_IDLE_EXIT_MS="3000",
            V17_WORLDD_POLL_MS="150",
            V17_WORLDD_LEASE_SECONDS=str(self.lease),
        )
        if self.suicide:
            env["V17_WORLDD_ALLOW_SUICIDE"] = "1"
        return env

    def run(self, timeout: int = 300) -> subprocess.CompletedProcess:
        return subprocess.run(["sbcl", "--script", str(RUN_WORLDD)],
                              env=self.env(), capture_output=True, text=True,
                              timeout=timeout)

    def run_dying(self, label: str) -> None:
        "The daemon is EXPECTED to die mid-job (unknown-wall scenario): "
        "a non-zero exit with the modelled-effect line on stderr passes."
        proc = self.run()
        check(f"{label}: daemon died without settling (exit != 0)",
              proc.returncode != 0, proc.returncode)
        check(f"{label}: daemon reports the modelled external effect",
              "modelled external effect" in (proc.stdout + proc.stderr),
              (proc.stderr or proc.stdout)[-400:])

    def run_successfully(self, label: str) -> str:
        proc = self.run()
        check(f"{label}: daemon exits 0", proc.returncode == 0,
              (proc.stdout + proc.stderr)[-2500:] if proc.returncode else "")
        m = re.search(r"WORLDD-HANDLED=(\d+)", proc.stdout)
        check(f"{label}: daemon reports handled count", m is not None,
              proc.stdout[-800:])
        return m.group(1)


def connect():
    server = get_server()
    return psycopg2.connect(server.get_uri(DB))


def new_session(cur) -> str:
    sid = u()
    cur.execute("INSERT INTO sessions (session_id, workspace_id) "
                "VALUES (%s, 'lisptools')", (sid,))
    cur.connection.commit()
    return sid


def enqueue_lisp_job(cur, sid, kind, payload) -> str:
    effect_id = u()
    cur.execute(
        "INSERT INTO jobs (session_id, effect_id, kind, payload) "
        "VALUES (%s, %s, %s, %s) RETURNING job_id",
        (sid, effect_id, kind, json.dumps(payload)))
    return cur.fetchone()[0]


def job_row(cur, job_id):
    cur.execute("SELECT status, fence, claimed_by, result::text, error "
                "FROM jobs WHERE job_id = %s", (job_id,))
    status, fence, claimed_by, result, error = cur.fetchone()
    return status, fence, claimed_by, (json.loads(result) if result else None), error


def revisions(cur, world_id):
    cur.execute("SELECT seq, state_text FROM lisp_revisions "
                "WHERE world_id = %s ORDER BY seq", (world_id,))
    return cur.fetchall()


def world_id_for(cur, name):
    cur.execute("SELECT world_id::text FROM lisp_worlds WHERE name = %s", (name,))
    row = cur.fetchone()
    return row[0] if row else None


def main() -> int:
    setup_db()
    conn = connect()
    cur = conn.cursor()
    # Gate scaffolding: the modelled-external-effect observation table
    # (shared with the G3 queue gate's tool), not part of SQL_LOAD_ORDER.
    cur.execute("CREATE TABLE IF NOT EXISTS gate_side_effects "
                "(id bigserial PRIMARY KEY, kind text, payload jsonb)")
    conn.commit()

    # --- 1. lisp_eval end-to-end -------------------------------------------
    sid = new_session(cur)
    enqueue_lisp_job(cur, sid, "lisp_eval",
                     {"world": "w-eval", "source": "(+ 2 3)"})
    conn.commit()
    handled = Daemon("s1").run_successfully("eval")
    check("eval: one job handled", handled == "1", handled)
    cur.execute("SELECT status, result::text FROM jobs WHERE session_id = %s", (sid,))
    st, res = cur.fetchone()
    check("eval: job succeeded", st == "succeeded", st)
    check("eval: values reported", json.loads(res)["echo"] if False else
          json.loads(res)["values"], json.loads(res))
    wid = world_id_for(cur, "w-eval")
    check("eval: world registered", wid is not None)
    revs = revisions(cur, wid)
    check("eval: exactly one revision (the baseline)", len(revs) == 1,
          [r[0] for r in revs])
    cur.execute("SELECT count(*) FROM lisp_journal WHERE world_id = %s", (wid,))
    check("eval: journal has the operation record", cur.fetchone()[0] >= 1)

    # --- 2. lisp_develop durability across processes ------------------------
    sid = new_session(cur)
    enqueue_lisp_job(cur, sid, "lisp_develop",
                     {"world": "w-dev",
                      "source": "(defun double (x) (* 2 x))"})
    conn.commit()
    Daemon("s2").run_successfully("develop")
    cur.execute("SELECT status FROM jobs WHERE session_id = %s", (sid,))
    check("develop: job succeeded", cur.fetchone()[0] == "succeeded")
    wid = world_id_for(cur, "w-dev")
    revs = revisions(cur, wid)
    check("develop: two revisions (baseline + accepted develop)",
          [r[0] for r in revs] == [1, 2], [r[0] for r in revs])
    # the export is *print-readably* text (uppercased symbols, char vectors)
    check("develop: revision 2 carries the definition",
          "defun double" in revs[1][1].lower(), revs[1][1][:200])
    # a fresh process calling it: Postgres is the recovery surface
    sid = new_session(cur)
    enqueue_lisp_job(cur, sid, "lisp_eval",
                     {"world": "w-dev", "source": "(double 21)"})
    conn.commit()
    Daemon("s2b").run_successfully("develop-recall")
    cur.execute("SELECT result::text FROM jobs WHERE session_id = %s", (sid,))
    values = json.loads(cur.fetchone()[0])["values"]
    check("develop-recall: fresh process evaluates the developed function",
          any(v.get("text") == "42" for v in values), values)

    # --- 3. preview restores: no revision at all -----------------------------
    before = len(revisions(cur, world_id_for(cur, "w-dev")))
    sid = new_session(cur)
    enqueue_lisp_job(cur, sid, "lisp_eval",
                     {"world": "w-dev", "source":
                      "(setf (gethash \"n\" *state*) 99)", "preview": True})
    conn.commit()
    Daemon("s3").run_successfully("preview")
    after = len(revisions(cur, world_id_for(cur, "w-dev")))
    cur.execute("SELECT result::text FROM jobs WHERE session_id = %s", (sid,))
    values = json.loads(cur.fetchone()[0])["values"]
    check("preview: value observed", any(v.get("text") == "99" for v in values),
          values)
    cur.execute("SELECT status FROM jobs WHERE session_id = %s", (sid,))
    check("preview: job still succeeded (an explicit preview is a success)",
          cur.fetchone()[0] == "succeeded")
    check("preview: no revision published", before == after, (before, after))
    sid = new_session(cur)
    enqueue_lisp_job(cur, sid, "lisp_eval",
                     {"world": "w-dev", "source":
                      "(gethash \"n\" *state*)"})
    conn.commit()
    Daemon("s3b").run_successfully("preview-verify")
    cur.execute("SELECT result::text FROM jobs WHERE session_id = %s", (sid,))
    values = json.loads(cur.fetchone()[0])["values"]
    check("preview: state restored (no 99 leaked)",
          any(v.get("text") in ("NIL", "nil") for v in values), values)

    # --- 4. unmet goal rejects the develop -----------------------------------
    before = len(revisions(cur, world_id_for(cur, "w-dev")))
    sid = new_session(cur)
    enqueue_lisp_job(cur, sid, "lisp_develop",
                     {"world": "w-dev",
                      "source": "(defun broken (x) (* x 3))",
                      "goals": ["(= (broken 2) 999)"]})
    conn.commit()
    Daemon("s4").run_successfully("goal-fail")
    cur.execute("SELECT status, error FROM jobs WHERE session_id = %s", (sid,))
    st4, err4 = cur.fetchone()
    check("goal-fail: job failed", st4 == "failed", st4)
    check("goal-fail: reason names the failing goal",
          err4 is not None and "goal" in err4.lower(), err4)
    check("goal-fail: no revision published",
          before == len(revisions(cur, world_id_for(cur, "w-dev"))))
    # and the failed definition did NOT survive
    sid = new_session(cur)
    enqueue_lisp_job(cur, sid, "lisp_eval",
                     {"world": "w-dev", "source": "(fboundp 'broken)"})
    conn.commit()
    Daemon("s4b").run_successfully("goal-fail-verify")
    cur.execute("SELECT result::text FROM jobs WHERE session_id = %s", (sid,))
    values = json.loads(cur.fetchone()[0])["values"]
    check("goal-fail: rejected definition is not in the world",
          any(v.get("text") in ("NIL", "nil") for v in values), values)

    # --- 5. invariant violation restores -------------------------------------
    before = len(revisions(cur, world_id_for(cur, "w-dev")))
    sid = new_session(cur)
    enqueue_lisp_job(cur, sid, "lisp_eval",
                     {"world": "w-dev",
                      "source": "(setf (gethash \"poison\" *state*) 1)",
                      "invariants": ["(null (gethash \"poison\" *state*))"]})
    conn.commit()
    Daemon("s5").run_successfully("invariant-fail")
    cur.execute("SELECT status, error FROM jobs WHERE session_id = %s", (sid,))
    st5, err5 = cur.fetchone()
    check("invariant-fail: job failed", st5 == "failed", st5)
    check("invariant-fail: reason names the invariant",
          err5 is not None and ("invariant" in err5.lower()
                                or "unsafe" in err5.lower()), err5)
    check("invariant-fail: no revision published",
          before == len(revisions(cur, world_id_for(cur, "w-dev"))))
    sid = new_session(cur)
    enqueue_lisp_job(cur, sid, "lisp_eval",
                     {"world": "w-dev",
                      "source": "(gethash \"poison\" *state*)"})
    conn.commit()
    Daemon("s5b").run_successfully("invariant-verify")
    cur.execute("SELECT result::text FROM jobs WHERE session_id = %s", (sid,))
    values = json.loads(cur.fetchone()[0])["values"]
    check("invariant-fail: poisoned key never landed",
          any(v.get("text") in ("NIL", "nil") for v in values), values)

    # --- 6. crash before settle -> reclaim -> visible effect exactly once -----
    # The first daemon is killed WHILE IT HOLDS THE CLAIM: the job's source
    # sleeps, so the claim is observable and the kill lands inside the
    # attempt (after the claim, before the settling commit).
    sid = new_session(cur)
    enqueue_lisp_job(cur, sid, "lisp_eval",
                     {"world": "w-crash", "source":
                      "(progn (sleep 5) (setf (gethash \"n\" *state*) 5))"})
    conn.commit()
    proc = subprocess.Popen(["sbcl", "--script", str(RUN_WORLDD)],
                            env=Daemon("s6", worker_id="wd-crash",
                                       lease=2).env(),
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    deadline = time.monotonic() + 90
    claimed = False
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            break
        cur.execute("SELECT status, claimed_by FROM jobs "
                    "WHERE session_id = %s", (sid,))
        st6, by = cur.fetchone()
        if st6 == "claimed":
            claimed = True
            break
        time.sleep(0.05)
    conn.commit()
    check("crash: job was claimed by the first daemon", claimed,
          (st6, proc.poll()))
    proc.kill()
    proc.communicate(timeout=30)
    cur.execute("SELECT status FROM jobs WHERE session_id = %s", (sid,))
    check("crash: killed daemon left the job unsettled",
          cur.fetchone()[0] == "claimed")
    cur.execute("SELECT count(*) FROM lisp_revisions r JOIN lisp_worlds w "
                "USING (world_id) WHERE w.name = 'w-crash'")
    revs_after_crash = cur.fetchone()[0]
    # The baseline publish races with the kill, so the exact count at kill
    # time is not deterministic; what matters is what the reclaim leaves.
    # the lease is already expired (2s): a second daemon may reclaim
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        cur.execute("SELECT lease_until < now(), status FROM jobs "
                    "WHERE session_id = %s", (sid,))
        expired, st6 = cur.fetchone()
        conn.commit()
        if st6 == "claimed" and expired:
            break
        time.sleep(0.2)
    Daemon("s6b", worker_id="wd-recover", lease=300).run_successfully(
        "crash-reclaim")
    cur.execute("SELECT status, result::text FROM jobs WHERE session_id = %s",
                (sid,))
    st6, res6 = cur.fetchone()
    check("crash-reclaim: job ultimately succeeded", st6 == "succeeded", st6)
    cur.execute("SELECT count(*) FROM jobs WHERE session_id = %s", (sid,))
    check("crash-reclaim: exactly one job row (no duplicate effect)",
          cur.fetchone()[0] == 1)
    cur.execute("SELECT count(*) FROM lisp_revisions r JOIN lisp_worlds w "
                "USING (world_id) WHERE w.name = 'w-crash'")
    # baseline (published by whichever daemon serves the world first) plus
    # exactly one revision carrying the effect: the killed attempt left no
    # trace and the replay published once.
    check("crash-reclaim: exactly two revisions (baseline + one effect)",
          cur.fetchone()[0] == 2, (revs_after_crash, cur.fetchone()))
    sid = new_session(cur)
    enqueue_lisp_job(cur, sid, "lisp_eval",
                     {"world": "w-crash", "source": "(gethash \"n\" *state*)"})
    conn.commit()
    Daemon("s6c").run_successfully("crash-verify")
    cur.execute("SELECT result::text FROM jobs WHERE session_id = %s", (sid,))
    values = json.loads(cur.fetchone()[0])["values"]
    check("crash-reclaim: effect applied exactly once (state is 5, not 10)",
          any(v.get("text") == "5" for v in values), values)

    # --- 7. unknown wall ------------------------------------------------------
    sid = new_session(cur)
    job7 = enqueue_lisp_job(cur, sid, "lisp_eval",
                           {"world": "w-unknown",
                            "source": "(setf (gethash \"n\" *state*) 7)",
                            "suicide_after_effect": True})
    conn.commit()
    Daemon("s7", worker_id="wd-suicide", suicide=True).run_dying("suicide")
    cur.execute("SELECT count(*) FROM gate_side_effects WHERE payload->>'job_id' = %s",
                (job7,))
    check("suicide: the external effect happened exactly once",
          cur.fetchone()[0] == 1)
    cur.execute("SELECT status FROM jobs WHERE job_id = %s", (job7,))
    st7 = cur.fetchone()[0]
    check("suicide: job is unsettled (claimed, not succeeded)", st7 == "claimed",
          st7)
    # A blind replay is refused by v12_enqueue_effect for unknown jobs;
    # the daemon must not have re-run the effect either.
    cur.execute("SELECT count(*) FROM gate_side_effects WHERE payload->>'job_id' = %s",
                (job7,))
    check("suicide: no replay happened while unsettled",
          cur.fetchone()[0] == 1)
    # The fate of the external effect is unknowable, so the supervisor
    # marks the job UNKNOWN through v12's own API (complete with the last
    # known fence). That is the wall: nothing may replay it blind.
    cur.execute("SELECT fence FROM jobs WHERE job_id = %s", (job7,))
    fence7 = cur.fetchone()[0]
    cur.execute("SELECT v12_complete_job(%s, %s, 'unknown', NULL, %s)",
                (job7, fence7, "worker died after the external effect"))
    conn.commit()
    cur.execute("SELECT status FROM jobs WHERE job_id = %s", (job7,))
    check("suicide: job recorded as unknown", cur.fetchone()[0] == "unknown")
    try:
        cur.execute("SELECT effect_id FROM jobs WHERE job_id = %s", (job7,))
        eff7 = cur.fetchone()[0]
        cur.execute("SELECT v12_enqueue_effect(%s, %s, 'lisp_eval', %s)",
                    (sid, eff7, json.dumps({})))
        conn.commit()
        replayed = True
    except psycopg2.Error:
        conn.rollback()
        replayed = False
    check("suicide: a blind re-enqueue of an unknown job is refused",
          not replayed)
    try:
        cur.execute("SELECT v12_resolve_unknown(%s, 'resolved_ok')", (job7,))
        conn.commit()
        resolved = True
    except psycopg2.Error:
        conn.rollback()
        resolved = False
    check("suicide: only an explicit resolution moves it (resolved_ok)",
          resolved)
    cur.execute("SELECT status FROM jobs WHERE job_id = %s", (job7,))
    check("suicide: job resolved explicitly", cur.fetchone()[0] == "resolved_ok")
    cur.execute("SELECT count(*) FROM gate_side_effects WHERE payload->>'job_id' = %s",
                (job7,))
    check("suicide: still exactly one effect after resolution",
          cur.fetchone()[0] == 1)

    # --- 8. `lisp:` tool handler ---------------------------------------------
    sid = new_session(cur)
    enqueue_lisp_job(cur, sid, "lisp_develop",
                     {"world": "w-tool",
                      "source": "(defun greet (params) "
                      "(format nil \"hi ~a\" (cdr (assoc :who params))))"})
    conn.commit()
    Daemon("s8").run_successfully("tool-develop")
    cur.execute("INSERT INTO tools (name, description, effect_class, handler) "
                "VALUES ('greet', 'greet someone', 'side_effect', "
                "'lisp:w-tool:greet')")
    conn.commit()
    cur.execute(
        "INSERT INTO jobs (session_id, effect_id, kind, payload) "
        "VALUES (%s, %s, 'greet', %s) RETURNING job_id",
        (sid, u(), json.dumps({"params": {"who": "团队"}})))
    job8 = cur.fetchone()[0]
    conn.commit()
    Daemon("s8b").run_successfully("tool-run")
    cur.execute("SELECT status, result::text FROM jobs WHERE job_id = %s", (job8,))
    st8, res8 = cur.fetchone()
    check("tool: job succeeded", st8 == "succeeded", st8)
    check("tool: params alist reached the Lisp function (unicode intact)",
          "hi 团队" in res8, res8)

    conn.commit()
    conn.close()
    print("[G4 lisptools] ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
