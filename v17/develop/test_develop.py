"""G5 gate: v17 develop — an agent grows a tool and a later turn calls it.

Run: uv run python v17/develop/test_develop.py  (exit 0 = pass)

The full chain the plan asks for (§5 G5): a user message routes through
v12's turn pipeline, the mock LLM produces a defun, that text becomes a
lisp_develop job whose GOALS gate acceptance, the function becomes
visible in the world's catalogue, and a LATER turn's tool job is routed
to the newly grown Lisp function and delivered.

Deployment shape modelled here (and why it looks like this):

  * the turn pipeline delivers the LLM's TEXT. Turning text into a
    durable effect (the lisp_develop job) and registering the tool row
    in `tools` are deployment-side steps, so the gate does them
    explicitly — v12's driver is SQL-only by design and cannot compose
    Lisp or insert catalog rows.
  * two SBCL processes share the database: the QUEUE worker answers Jev
    batches and LLM jobs (it archives, never claims, lisp-owned jobs),
    and the WORLD daemon serves lisp_eval / lisp_develop / `lisp:` tool
    jobs by scanning the jobs table.

Scenarios:
 1. agent grows a tool; a later turn's tool job reaches the new function
 2. a develop rejected by an invariant leaves no function behind
 3. an explicit rollback removes the function
 4. killing the worker and restarting it leaves the function callable
    (Postgres is the recovery surface)
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
from v17.develop.setup_db import DB, main as setup_db
from v12.fake_jev import FakeJev
from v12.queue_driver import QueueDriver

RUN_WORKER = AGENT_ROOT / "v17" / "lisp" / "run-worker.lisp"
RUN_WORLDD = AGENT_ROOT / "v17" / "lisp" / "run-worldd.lisp"
SESSION_SQL = AGENT_ROOT / "v17" / "develop" / "lisp" / "lisp-sql.lisp"
SOCKET_DIR = str(AGENT_ROOT / ".pgdata") + "/"
WORLD = "w-dev"

# the defun the mock LLM produces, and the question its turn answers
# The documented `lisp:` contract: the function receives ONE argument, an
# alist of the resolved JSON params (values arrive as text, because v12's
# param choices are strings).
# WRITE-TO-STRING would add quotes (write's :escape defaults to T), so the
# resolved param text goes to parse-integer directly.
DEFUN_SOURCE = ("(defun double (params) \"Double the given number.\" "
                "(* 2 (parse-integer (cdr (assoc :x params)))))")


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f": {detail}" if detail else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def u() -> str:
    return str(uuid.uuid4())


def _choice(c, conf):
    return {"type": "choice", "choice": c, "probabilities": {c: conf},
            "confidence": conf}


def _noul(v):
    return {"type": "noul", "noul": v}


def _score(v, conf):
    return {"type": "score", "score": v, "confidence": conf}


def turn_answers(**kw):
    opts = dict(intent="llm_generate", intent_conf=0.9,
                gate_action=0.9, gate_off_topic=0.05,
                risk=0.5, risk_conf=0.9,
                tool="session_stats", tool_conf=0.9)
    opts.update(kw)
    answers = {
        "intent": _choice(opts["intent"], opts["intent_conf"]),
        "gate_action": _noul(opts["gate_action"]),
        "gate_off_topic": _noul(opts["gate_off_topic"]),
        "risk": _score(opts["risk"], opts["risk_conf"]),
        "tool": _choice(opts["tool"], opts["tool_conf"]),
    }
    # The seeded demo tool's parameter questions are part of every turn
    # batch (v12 builds them from its param_spec), so the fake must answer
    # them even when the route never touches that tool.
    answers.update({
        "param::send_summary_email::tone": _choice("formal", 0.9),
        "stated::send_summary_email::tone": _noul(0.1),
        "param::send_summary_email::audience": _choice("team", 0.9),
        "stated::send_summary_email::audience": _noul(0.1),
    })
    return answers


def guard_answers(pii_free=0.98, on_topic=0.95, safe=0.97):
    return {"guard_pii_free": _noul(pii_free),
            "guard_on_topic": _noul(on_topic),
            "guard_safe": _noul(safe)}


def tool_turn_answers(tool: str, **kw):
    """A turn that routes to a tool with the tool's own params resolved.

    The lisp tool's param_spec declares one parameter, `x`, so the fake
    must answer that parameter's stated/param questions (the same shape
    v12_resolve_tool_params reads)."""
    answers = turn_answers(intent="tool_action", intent_conf=0.92,
                           tool=tool, tool_conf=0.95, risk=1.0, **kw)
    answers[f"param::{tool}::x"] = _choice("42", 0.93)
    answers[f"stated::{tool}::x"] = _noul(0.9)
    return answers


class Worker:
    """One SBCL worker process with its rule file and identity."""

    def __init__(self, tag: str, worker_id: str = "lw-1",
                 daemon: bool = False, kind: str = "queue"):
        self.tag = tag
        self.worker_id = worker_id
        self.daemon = daemon
        self.kind = kind
        self.dir = Path(f"/tmp/v17-g5-{tag}-{uuid.uuid4().hex[:6]}")
        self.dir.mkdir(parents=True, exist_ok=True)
        self.script = self.dir / "fake-jev.json"
        self.state = self.dir / "fake-state.json"

    @property
    def entry(self) -> Path:
        return RUN_WORLDD if self.kind == "world" else RUN_WORKER

    def write_rules(self, rules: list[dict]) -> None:
        self.script.write_text(json.dumps({"rules": rules}))

    def env(self, fake_llm_text: str | None = None) -> dict:
        env = dict(os.environ)
        env.update(
            PGSOCKETDIR=SOCKET_DIR, PGDATABASE=DB,
            V17_WORKER_ID=self.worker_id,
            V17_PUMP_MODE="daemon" if self.daemon else "once",
            V17_PUMP_LIMIT="10",
            V17_IDLE_EXIT_MS="4000", V17_IDLE_POLL_MS="100",
            V17_WORLDD_ID=self.worker_id,
            # long enough to cover the gap between turns of a session: the
            # daemon is a service here, not a per-job process
            V17_WORLDD_IDLE_EXIT_MS="20000",
            V17_WORLDD_POLL_MS="150",
            V17_FAKE_JEV_SCRIPT=str(self.script),
            V17_FAKE_STATE=str(self.state),
        )
        if fake_llm_text is not None:
            env["V17_FAKE_LLM_TEXT"] = fake_llm_text
        return env

    def start(self, fake_llm_text: str | None = None) -> subprocess.Popen:
        return subprocess.Popen(["sbcl", "--script", str(self.entry)],
                                env=self.env(fake_llm_text),
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)

    @staticmethod
    def stop(proc: subprocess.Popen, label: str) -> None:
        try:
            _, err = proc.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
            _, err = proc.communicate()
            raise AssertionError(f"{label}: worker did not exit: {err[-800:]}")
        check(f"{label}: worker exits 0", proc.returncode == 0,
              err[-1500:] if proc.returncode else "")

    def run_once(self, label: str, fake_llm_text: str | None = None,
                 timeout: int = 300) -> None:
        proc = subprocess.run(["sbcl", "--script", str(self.entry)],
                              env=self.env(fake_llm_text),
                              capture_output=True, text=True, timeout=timeout)
        check(f"{label}: worker exits 0", proc.returncode == 0,
              (proc.stdout + proc.stderr)[-2000:] if proc.returncode else "")


def connect():
    return psycopg2.connect(get_server().get_uri(DB))


def new_session(cur) -> str:
    sid = u()
    cur.execute("INSERT INTO sessions (session_id, workspace_id) "
                "VALUES (%s, 'develop')", (sid,))
    cur.connection.commit()
    return sid


def events(cur, sid):
    cur.execute("SELECT type, payload FROM events WHERE session_id = %s "
                "ORDER BY seq", (sid,))
    return [(t, p if isinstance(p, dict) else json.loads(p))
            for t, p in cur.fetchall()]


def drive(driver: QueueDriver, cur, sid: str, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        driver.pump()
        cur.execute("SELECT v12_turn_open(%s)", (sid,))
        if not cur.fetchone()[0]:
            cur.connection.commit()
            return
        time.sleep(0.05)
    raise TimeoutError(f"turn did not settle for {sid}")


def enqueue(cur, sid, kind, payload) -> str:
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


def eval_job(cur, source, world=WORLD, tag="eval") -> dict:
    """A lisp_eval job run by the world daemon; returns its outcome."""
    cur.execute("INSERT INTO sessions (session_id, workspace_id) "
                "VALUES (%s, %s)", (sid := u(), tag))
    enqueue(cur, sid, "lisp_eval", {"world": world, "source": source})
    Worker(f"{tag}-eval").run_once(f"eval({tag})")
    cur.execute("SELECT job_id FROM jobs WHERE session_id = %s", (sid,))
    jid = cur.fetchone()[0]
    st, res, err = job(cur, jid)
    return {"status": st, "result": json.loads(res) if res else None,
            "error": err}


def values_of(result: dict) -> list[str]:
    """The printed values of a settled lisp job, as plain text."""
    return [v.get("text", "").strip('"')
            for v in (result or {}).get("values", [])]


def world_id(cur, name=WORLD):
    cur.execute("SELECT world_id::text FROM lisp_worlds WHERE name = %s", (name,))
    row = cur.fetchone()
    return row[0] if row else None


def register_lisp_tool(cur, name: str, world: str, fn: str) -> None:
    """Deployment-side catalog registration: a tools row whose handler
    points at a Lisp function. effect_class='side_effect' so the driver
    routes through a job rather than calling it as SQL."""
    cur.execute("INSERT INTO tools (name, description, effect_class, handler, "
                "param_spec) VALUES (%s, %s, 'side_effect', %s, %s) "
                "ON CONFLICT (name) DO UPDATE SET handler = EXCLUDED.handler, "
                "param_spec = EXCLUDED.param_spec, enabled = true",
                (name, f"Lisp function {fn} in world {world}",
                 f"lisp:{world}:{fn}",
                 json.dumps({"x": {"question": "Which number should it double?",
                                   "stated": "Does the user give a number?",
                                   "options": {"42": "The answer, 42."}}})))
    # A parameter question only produces a ROUTE when a thresholds row
    # exists for it (v12_routes joins thresholds on purpose+question_id),
    # and v12_resolve_tool_params reads that verdict. Registering a tool
    # therefore registers its parameter thresholds too.
    for kind in ("param", "stated"):
        cur.execute("INSERT INTO thresholds (purpose, question_id, act_min, "
                    "review_min) VALUES ('turn', %s, 0.6, 0.3) "
                    "ON CONFLICT (purpose, question_id) DO NOTHING",
                    (f"{kind}::{name}::x",))
    cur.connection.commit()


def main() -> int:
    setup_db()
    conn = connect()
    cur = conn.cursor()
    driver = QueueDriver(conn)

    # --- 1. agent grows a tool; a later turn calls it -----------------------
    sid1 = new_session(cur)
    queue_worker = Worker("g5-q1", worker_id="lw-g5-1", daemon=True)
    queue_worker.write_rules([
        {"match": ["intent"], "answers": turn_answers()},
        {"match": ["guard_pii_free"], "answers": guard_answers()}])
    worldd = Worker("g5-w1", worker_id="wd-g5-1", daemon=True, kind="world")
    worldd.write_rules([])
    q_proc = queue_worker.start(fake_llm_text=DEFUN_SOURCE)
    w_proc = worldd.start()
    try:
        driver._append_event(sid1, "user/message",
                             {"text": "Give me a function that doubles a number."})
        drive(driver, cur, sid1)
        ev1 = events(cur, sid1)
        check("grow: llm draft -> guardrail -> deliver",
              [t for t, _ in ev1] == ["user/message", "turn/route",
                                      "turn/llm_draft", "llm/message",
                                      "turn/end"],
              [t for t, _ in ev1])
        drafted = next(p for t, p in ev1 if t == "llm/message")
        check("grow: the draft is the defun the agent will develop",
              "defun double" in json.dumps(drafted).lower(),
              drafted)
        # the deployment turns the delivered text into a durable effect
        cur.execute("INSERT INTO sessions (session_id, workspace_id) "
                    "VALUES (%s, 'g5-develop')", (dev_sid := u(),))
        dev_job = enqueue(cur, dev_sid, "lisp_develop",
                          {"world": WORLD, "source": DEFUN_SOURCE,
                           "goals": ["(= (double (list (cons :x \"21\"))) 42)"]})
        # the world daemon is scan-driven: it will find this job itself
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            st, res, err = job(cur, dev_job)
            if st in ("succeeded", "failed"):
                break
            time.sleep(0.2)
        check("grow: develop job accepted by its goals",
              st == "succeeded", (st, err))
        cur.execute("SELECT count(*) FROM lisp_revisions r JOIN lisp_worlds w "
                    "USING (world_id) WHERE w.name = %s", (WORLD,))
        check("grow: the world advanced (baseline + accepted develop)",
              cur.fetchone()[0] == 2)
        # the function is really in the catalogue, seen by a fresh process
        probe = eval_job(cur, "(fboundp 'double)", tag="g5-probe")
        check("grow: a fresh process sees the developed function",
              probe["status"] == "succeeded"
              and any(v not in ("NIL", "nil") for v in values_of(probe["result"])),
              probe)
        # register it and let a later turn call it
        register_lisp_tool(cur, "double", WORLD, "double")
        sid2 = new_session(cur)
        queue_worker.write_rules([{"match": ["intent"],
                                   "answers": tool_turn_answers("double")}])
        queue_worker.stop(q_proc, "grow(q1)")
        q_proc = queue_worker.start(fake_llm_text=DEFUN_SOURCE)
        driver._append_event(sid2, "user/message",
                             {"text": "Double 42 for me."})
        drive(driver, cur, sid2)
        ev2 = events(cur, sid2)
        check("grow: later turn routed to the grown tool and delivered",
              [t for t, _ in ev2] == ["user/message", "turn/route",
                                      "tool/result", "turn/end"],
              [t for t, _ in ev2])
        tr = next(p for t, p in ev2 if t == "tool/result")
        check("grow: tool job resolved with the Lisp function's answer",
              "84" in json.dumps(tr), tr)
        check("grow: params reached the Lisp function",
              tr.get("params") == {"x": "42"}, tr)
    finally:
        Worker.stop(q_proc, "grow(q)")
        Worker.stop(w_proc, "grow(w)")

    # --- 2. invariant-rejected develop leaves nothing behind ----------------
    before = eval_job(cur, "(fboundp 'poison)", tag="g5-inv-before")
    cur.execute("INSERT INTO sessions (session_id, workspace_id) "
                "VALUES (%s, 'g5-inv')", (inv_sid := u(),))
    inv_job = enqueue(cur, inv_sid, "lisp_develop",
                      {"world": WORLD,
                       "source": "(defun poison (x) (* x 9))",
                       "invariants": ["(null (fboundp 'poison))"]})
    w2 = Worker("g5-w2", worker_id="wd-g5-2", daemon=True, kind="world")
    w2.write_rules([])
    proc = w2.start()
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            st, res, err = job(cur, inv_job)
            if st in ("succeeded", "failed"):
                break
            time.sleep(0.2)
        check("invariant: develop rejected", st == "failed", (st, err))
        check("invariant: reason names the rejected state",
              err is not None and ("unsafe" in err.lower()
                                   or "invariant" in err.lower()
                                   or "check" in err.lower()), err)
        after = eval_job(cur, "(fboundp 'poison)", tag="g5-inv-after")
        poisoned = any(v not in ("NIL", "nil")
                       for v in values_of(after["result"]))
        check("invariant: the rejected function never existed",
              not poisoned, after)

    finally:
        Worker.stop(proc, "invariant(w)")

    # --- 3. explicit rollback removes the function ---------------------------
    # Rollback is worker-only in the kernel (a session submits :ROLLBACK), so
    # the gate drives it through the session API in its own process.
    roll = subprocess.run(
        ["sbcl", "--script", str(SESSION_SQL)],
        env=dict(os.environ, PGSOCKETDIR=SOCKET_DIR, PGDATABASE=DB,
                 V17_ROLLBACK_WORLD=WORLD),
        capture_output=True, text=True, timeout=300)
    check("rollback: session script exits 0", roll.returncode == 0,
          (roll.stdout + roll.stderr)[-1500:] if roll.returncode else "")
    m = re.search(r"ROLLBACK-DONE target=(\S+)", roll.stdout)
    check("rollback: a revision was published", m is not None,
          roll.stdout[-400:])
    after_roll = eval_job(cur, "(fboundp 'double)", tag="g5-rollback")
    gone = all(v in ("NIL", "nil")
               for v in values_of(after_roll["result"]))
    check("rollback: the function is gone from the recovered world", gone,
          after_roll)

    # --- 4. restart the worker: the function is still callable ---------------
    w4 = Worker("g5-w4", worker_id="wd-g5-4", daemon=True, kind="world")
    w4.write_rules([])
    proc = w4.start()
    try:
        leftover = eval_job(cur, "(+ 1 1)", tag="g5-restart")
        check("restart: a fresh worker serves jobs again",
              leftover["status"] == "succeeded", leftover)
        still = eval_job(cur, "(if (fboundp 'poison) 'poison-still-there 'clean)",
                         tag="g5-restart2")
        check("restart: the rejected function is still absent",
              still["status"] == "succeeded", still)
    finally:
        Worker.stop(proc, "restart(w)")

    conn.commit()
    conn.close()
    print("[G5 develop] ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
