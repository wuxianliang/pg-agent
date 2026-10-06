"""G3 gate: v17 queue — the Lisp queue worker against v12's queue contract.

Run: uv run python v17/queue/test_queue.py  (exit 0 = pass)

The Lisp worker (v17/lisp/run-worker.lisp -> sbcl) is a drop-in
QueueWorker replacement: same queue, same message shape, same constants,
same CAS/fence semantics. The QueueDriver stays Python (SQL-only).

Scenarios (v12 G6's seven, rerun against the Lisp worker, plus two):
 1. queue-mode e2e (tool route) + cross-mode effect id + all archived
 2. transient failure -> VT redelivery
 3. duplicate wake-up dedupe (one ask)
 4. deterministic answer failure -> batch failed, single attempt, human
 5. lost message -> v12_requeue_stale scan recovery
 6. llm + guardrail through the queue
 7. multi-turn batch filtering
 8. jsonb canary: nested/unicode payload round-trip through the echo tool
 9. mixed race: Python QueueWorker and the Lisp worker on the same queue —
    CAS keeps every batch single-answered, fence keeps every job
    single-executed
"""
from __future__ import annotations

import json
import os
import re
import subprocess
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
from v17.queue.setup_db import DB, main as setup_db
from v12.fake_jev import FakeJev
from v12.queue_driver import QueueDriver
from v12.queue_worker import QueueWorker

LISP = AGENT_ROOT / "v17" / "lisp"
RUN_WORKER = LISP / "run-worker.lisp"
RUN_QUEUE_SUITE = LISP / "tests" / "run-queue-suite.lisp"
SOCKET_DIR = str(AGENT_ROOT / ".pgdata") + "/"


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f": {detail}" if detail else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def u() -> str:
    return str(uuid.uuid4())


# --- fake-jev answer builders (same shapes as v12 G6's turn_script) -------
def _choice(c, conf):
    return {"type": "choice", "choice": c, "probabilities": {c: conf},
            "confidence": conf}


def _noul(v):
    return {"type": "noul", "noul": v}


def _score(v, conf):
    return {"type": "score", "score": v, "confidence": conf}


def turn_answers(**kw):
    opts = dict(intent="sql_answer", intent_conf=0.9,
                gate_action=0.9, gate_off_topic=0.05,
                risk=0.5, risk_conf=0.9,
                tool="session_stats", tool_conf=0.9,
                tone="formal", tone_conf=0.9, tone_stated=0.1,
                audience="team", audience_conf=0.9, audience_stated=0.1)
    opts.update(kw)
    return {
        "intent": _choice(opts["intent"], opts["intent_conf"]),
        "gate_action": _noul(opts["gate_action"]),
        "gate_off_topic": _noul(opts["gate_off_topic"]),
        "risk": _score(opts["risk"], opts["risk_conf"]),
        "tool": _choice(opts["tool"], opts["tool_conf"]),
        "param::send_summary_email::tone":
            _choice(opts["tone"], opts["tone_conf"]),
        "stated::send_summary_email::tone": _noul(opts["tone_stated"]),
        "param::send_summary_email::audience":
            _choice(opts["audience"], opts["audience_conf"]),
        "stated::send_summary_email::audience":
            _noul(opts["audience_stated"]),
    }


def guard_answers(pii_free=0.98, on_topic=0.95, safe=0.97):
    return {"guard_pii_free": _noul(pii_free),
            "guard_on_topic": _noul(on_topic),
            "guard_safe": _noul(safe)}


# --- Lisp worker process management ---------------------------------------
class LispWorker:
    """Run the Lisp worker as a subprocess with a scripted fake Jev/LLM.

    The fake's script file holds rules (answers are plain dicts in the
    HTTP API shape); its state file accumulates call counts across
    processes so gate assertions work per-scenario in fresh tmp paths.
    """

    def __init__(self, tag: str):
        self.dir = Path(f"/tmp/v17-g3-{tag}-{uuid.uuid4().hex[:8]}")
        self.dir.mkdir(parents=True, exist_ok=True)
        self.script = self.dir / "fake-jev.json"
        self.state = self.dir / "fake-state.json"

    def write_script(self, rules: list[dict]) -> None:
        self.script.write_text(json.dumps({"rules": rules}))

    def read_state(self) -> dict:
        if not self.state.exists():
            return {}
        return json.loads(self.state.read_text())

    def env(self, mode: str, limit: int = 10, worker_id: str = "lw-1",
            fake_llm_text: str | None = None) -> dict:
        env = dict(os.environ)
        env.update(PGSOCKETDIR=SOCKET_DIR, PGDATABASE=DB,
                   V17_WORKER_ID=worker_id,
                   V17_PUMP_MODE=mode, V17_PUMP_LIMIT=str(limit),
                   V17_IDLE_EXIT_MS="4000", V17_IDLE_POLL_MS="100",
                   V17_FAKE_JEV_SCRIPT=str(self.script),
                   V17_FAKE_STATE=str(self.state))
        if fake_llm_text is not None:
            env["V17_FAKE_LLM_TEXT"] = fake_llm_text
        return env

    def run_once(self, limit: int = 10, worker_id: str = "lw-1",
                 fake_llm_text: str | None = None) -> int:
        proc = subprocess.run(
            ["sbcl", "--script", str(RUN_WORKER)],
            env=self.env("once", limit, worker_id, fake_llm_text),
            capture_output=True, text=True, timeout=300)
        check("lisp worker exits 0 (once)", proc.returncode == 0,
              proc.stderr[-2000:] if proc.returncode else "")
        m = re.search(r"ARCHIVED=(\d+)", proc.stdout)
        check("lisp worker reports ARCHIVED", m is not None, proc.stdout[-500:])
        return int(m.group(1))

    def start_daemon(self, worker_id: str = "lw-1",
                     fake_llm_text: str | None = None) -> subprocess.Popen:
        return subprocess.Popen(
            ["sbcl", "--script", str(RUN_WORKER)],
            env=self.env("daemon", 10, worker_id, fake_llm_text),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    @staticmethod
    def stop_daemon(proc: subprocess.Popen, label: str) -> None:
        try:
            _, err = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            _, err = proc.communicate()
            raise AssertionError(f"{label}: daemon did not idle-exit: {err[-1000:]}")
        check(f"{label}: daemon exits 0", proc.returncode == 0,
              err[-2000:] if proc.returncode else "")


def drive_until_settled(driver: QueueDriver, cur, sid: str,
                        timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        driver.pump()
        cur.execute("SELECT v12_turn_open(%s)", (sid,))
        if not cur.fetchone()[0]:
            cur.connection.commit()
            return
        time.sleep(0.05)
    raise TimeoutError(f"turn did not settle for {sid}")


def events(cur, sid):
    cur.execute("SELECT type, payload FROM events WHERE session_id = %s "
                "ORDER BY seq", (sid,))
    return [(t, p if isinstance(p, dict) else json.loads(p))
            for t, p in cur.fetchall()]


def status(cur, sid):
    cur.execute("SELECT status FROM sessions WHERE session_id = %s", (sid,))
    return cur.fetchone()[0]


def new_session(cur) -> str:
    sid = u()
    cur.execute("INSERT INTO sessions (session_id, workspace_id) "
                "VALUES (%s, 'queue')", (sid,))
    cur.connection.commit()
    return sid


def main() -> int:
    setup_db()
    server = get_server()
    conn = psycopg2.connect(server.get_uri(DB))
    cur = conn.cursor()
    # Gate-side observation table for the Lisp demo tool's side effects
    # (test scaffolding, not part of SQL_LOAD_ORDER).
    cur.execute("CREATE TABLE IF NOT EXISTS gate_side_effects "
                "(id bigserial PRIMARY KEY, kind text, payload jsonb)")
    conn.commit()

    # --- 1. queue-mode e2e: tool route + cross-mode effect id ---------------
    sid = new_session(cur)
    w1 = LispWorker("s1")
    w1.write_script([{"match": ["intent"], "answers": turn_answers(
        intent="tool_action", intent_conf=0.92,
        tool="send_summary_email", tool_conf=0.95,
        risk=1.0, tone="friendly", tone_conf=0.93, tone_stated=0.9)}])
    driver = QueueDriver(conn)
    driver._append_event(sid, "user/message",
                         {"text": "Send a friendly summary to the team."})
    driver.pump()
    daemon = w1.start_daemon()
    drive_until_settled(driver, cur, sid)
    ev = events(cur, sid)
    check("e2e(tool): routed, executed, closed via queue",
          [t for t, _ in ev] == ["user/message", "turn/route", "tool/result",
                                 "turn/end"], [t for t, _ in ev])
    tr = next(p for t, p in ev if t == "tool/result")
    check("e2e(tool): resolved params",
          tr["params"] == {"tone": "friendly"}, tr)
    cur.execute("SELECT count(*) FROM gate_side_effects")
    check("e2e(tool): side effect hit exactly once (cross-process)",
          cur.fetchone()[0] == 1)
    cur.execute("SELECT effect_id FROM jobs WHERE session_id = %s", (sid,))
    eff_sql = cur.fetchone()[0]
    eff_py = uuid.uuid5(uuid.UUID(int=0), f"{sid}:1:send_summary_email")
    check("e2e(tool): SQL v12_effect_id == inline runner's uuid5",
          str(eff_sql) == str(eff_py), (str(eff_sql), str(eff_py)))
    LispWorker.stop_daemon(daemon, "s1")
    cur.execute("SELECT count(*) FROM pgmq.q_v12_work")
    check("e2e(tool): no leftover messages", cur.fetchone()[0] == 0)
    cur.execute("SELECT count(*) FROM pgmq.a_v12_work")
    check("e2e(tool): messages archived", cur.fetchone()[0] >= 2)

    # --- 2. transient failure -> VT redelivery -------------------------------
    sid = new_session(cur)
    w2 = LispWorker("s2")
    w2.write_script([{"match": ["intent"], "transient_failures": 1,
                      "answers": turn_answers()}])
    driver = QueueDriver(conn)
    driver._append_event(sid, "user/message", {"text": "Stats please."})
    driver.pump()
    n1 = w2.run_once()
    check("retry: first pump archives nothing", n1 == 0, n1)
    cur.execute("SELECT status FROM jev_batches WHERE session_id = %s", (sid,))
    check("retry: batch still ready after transient failure",
          cur.fetchone()[0] == "ready")
    time.sleep(2.2)                    # > RETRY_VT
    daemon = w2.start_daemon()
    drive_until_settled(driver, cur, sid)
    LispWorker.stop_daemon(daemon, "s2")
    state = w2.read_state()
    check("retry: succeeded on redelivery (two asks total)",
          state.get("total_calls") == 2, state)
    end = next(p for t, p in events(cur, sid) if t == "turn/end")
    check("retry: turn delivered", end["delivered"] is True, end)

    # --- 3. duplicate wake-up dedupe ------------------------------------------
    sid = new_session(cur)
    w3 = LispWorker("s3")
    w3.write_script([{"match": ["intent"], "answers": turn_answers()}])
    driver = QueueDriver(conn)
    driver._append_event(sid, "user/message", {"text": "Stats again."})
    driver.pump()
    cur.execute("SELECT v12_send_work('jev', batch_id) FROM jev_batches "
                "WHERE session_id = %s AND status = 'ready'", (sid,))
    conn.commit()                      # duplicate the wake-up
    n = w3.run_once(limit=10)
    check("dedupe: both messages archived", n == 2, n)
    check("dedupe: one ask despite duplicate messages",
          w3.read_state().get("total_calls") == 1, w3.read_state())
    cur.execute("SELECT count(*) FROM pgmq.q_v12_work")
    check("dedupe: queue drained", cur.fetchone()[0] == 0)
    drive_until_settled(driver, cur, sid)

    # --- 4. deterministic answer failure -> human, no retry -------------------
    sid = new_session(cur)
    bad = turn_answers()
    del bad["intent"]["probabilities"]   # fails record validation
    w4 = LispWorker("s4")
    w4.write_script([{"match": ["intent"], "answers": bad}])
    driver = QueueDriver(conn)
    driver._append_event(sid, "user/message", {"text": "Broken answers."})
    driver.pump()
    n = w4.run_once(limit=10)
    check("deterministic: message archived on first attempt", n == 1, n)
    cur.execute("SELECT status FROM jev_batches WHERE session_id = %s", (sid,))
    check("deterministic: batch marked failed", cur.fetchone()[0] == "failed")
    check("deterministic: single attempt (no redelivery)",
          w4.read_state().get("total_calls") == 1, w4.read_state())
    driver.pump()
    check("deterministic: turn escalated to human",
          status(cur, sid) == "awaiting_human")
    end = next(p for t, p in events(cur, sid) if t == "turn/end")
    check("deterministic: reason decision_failed",
          end["reason"] == "decision_failed", end)

    # --- 5. lost message -> scan recovery --------------------------------------
    sid = new_session(cur)
    w5 = LispWorker("s5")
    w5.write_script([{"match": ["intent"], "answers": turn_answers()}])
    driver = QueueDriver(conn)
    driver._append_event(sid, "user/message", {"text": "Lost message."})
    state_row = driver._one("SELECT v12_fold_state(%s)", (sid,))
    batch = driver._one("SELECT v12_open_batch(%s, 'turn', %s)",
                        (sid, json.dumps(state_row[0])))[0]
    driver._one("SELECT v12_build_turn_questions(%s, %s)", (batch, sid))
    driver._one("SELECT v12_seal_batch(%s)", (batch,))
    conn.commit()
    check("recovery: nothing to do without a message", w5.run_once() == 0)
    cur.execute("SELECT v12_requeue_stale()")
    requeued = cur.fetchone()[0]
    conn.commit()
    check("recovery: scan re-enqueues the pending batch", requeued == 1,
          requeued)
    daemon = w5.start_daemon()
    drive_until_settled(driver, cur, sid)
    LispWorker.stop_daemon(daemon, "s5")
    end = next(p for t, p in events(cur, sid) if t == "turn/end")
    check("recovery: turn completes after requeue", end["delivered"] is True)

    # --- 6. llm + guardrail through the queue ----------------------------------
    sid = new_session(cur)
    w6 = LispWorker("s6")
    w6.write_script([
        {"match": ["intent"],
         "answers": turn_answers(intent="llm_generate", intent_conf=0.9)},
        {"match": ["guard_pii_free"], "answers": guard_answers()}])
    driver = QueueDriver(conn)
    driver._append_event(sid, "user/message",
                         {"text": "One sentence on durability."})
    daemon = w6.start_daemon(fake_llm_text="Postgres keeps it durable.")
    drive_until_settled(driver, cur, sid)
    LispWorker.stop_daemon(daemon, "s6")
    ev = events(cur, sid)
    check("llm: draft -> guardrail -> deliver through queue",
          [t for t, _ in ev] == ["user/message", "turn/route",
                                 "turn/llm_draft", "llm/message", "turn/end"],
          [t for t, _ in ev])
    check("llm: generation ran once in the lisp worker",
          w6.read_state().get("llm_calls") == 1, w6.read_state())
    cur.execute("SELECT count(*) FROM jev_batches WHERE session_id = %s "
                "AND purpose IN ('turn', 'guardrail') "
                "AND status IN ('answered', 'cached')", (sid,))
    check("llm: two answered batches (turn + guardrail)",
          cur.fetchone()[0] == 2)
    check("llm: two Jev asks total",
          w6.read_state().get("total_calls") == 2, w6.read_state())

    # --- 7. multi-turn in one session ------------------------------------------
    driver._append_event(sid, "user/message",
                         {"text": "How many messages now?"})
    daemon = w6.start_daemon(fake_llm_text="Still durable.")
    drive_until_settled(driver, cur, sid)
    LispWorker.stop_daemon(daemon, "s6b")
    ends = [p for t, p in events(cur, sid) if t == "turn/end"]
    check("multi-turn: second turn delivered too",
          len(ends) == 2 and all(e["delivered"] for e in ends), ends)

    # --- 8. jsonb canary --------------------------------------------------------
    cur.execute("INSERT INTO sessions (session_id, workspace_id) "
                "VALUES (%s, 'canary')", (sid8 := u(),))
    payload = {"params": {"audience": "团队", "tags": ["a", "b", "c"],
                          "nested": {"x": 1, "y": True, "z": None,
                                     "snowman": "☃"}},
               "note": "深度嵌套"}
    cur.execute(
        "INSERT INTO jobs (session_id, effect_id, kind, payload) "
        "VALUES (%s, %s, 'echo', %s) RETURNING job_id",
        (sid8, str(uuid.uuid4()), json.dumps(payload)))
    job8 = cur.fetchone()[0]
    cur.execute("SELECT v12_send_work('job', %s)", (job8,))
    conn.commit()
    w8 = LispWorker("s8")
    w8.write_script([])
    check("canary: echo job archived", w8.run_once() == 1)
    cur.execute("SELECT status, result FROM jobs WHERE job_id = %s", (job8,))
    st8, res8 = cur.fetchone()
    check("canary: echo job succeeded", st8 == "succeeded", st8)
    check("canary: jsonb round-trip is byte-faithful (unicode/CJK/nesting)",
          (res8 if isinstance(res8, dict) else json.loads(res8))
          == {"echo": payload}, res8)

    # --- 9. mixed race: Python worker vs Lisp worker on one queue --------------
    race_sids = [new_session(cur) for _ in range(3)]
    w9 = LispWorker("s9")
    w9.write_script([
        {"match": ["intent"], "answers": turn_answers(
            intent="tool_action", intent_conf=0.92,
            tool="send_summary_email", tool_conf=0.95, risk=1.0,
            tone="formal", tone_conf=0.9, tone_stated=0.9)}])
    py_sent = []

    def py_tool(payload):
        py_sent.append(payload)
        return {"sent_to": payload["params"].get("audience", "team-default")}

    # Python worker shares the same answers via the in-process FakeJev.
    from v12.queue.test_queue import turn_script  # reuse v12's exact script
    py_fake = FakeJev([turn_script(
        intent="tool_action", intent_conf=0.92,
        tool="send_summary_email", tool_conf=0.95, risk=1.0,
        tone="formal", tone_conf=0.9, tone_stated=0.9)])
    py_conn = psycopg2.connect(server.get_uri(DB))
    py_worker = QueueWorker(py_conn, py_fake, tool_impls={"send_summary_email": py_tool},
                            worker_id="qw-race")
    stop_py = threading.Event()

    def py_loop():
        while not stop_py.is_set():
            try:
                py_worker.pump(limit=4)
            except psycopg2.Error:
                if stop_py.is_set():
                    break
                try:
                    py_conn.rollback()
                except psycopg2.Error:
                    break
            time.sleep(0.05)

    cur.execute("DELETE FROM gate_side_effects")
    conn.commit()
    for rsid in race_sids:
        driver._append_event(rsid, "user/message",
                             {"text": "Race me to the team."})
    driver.pump()
    daemon = w9.start_daemon(worker_id="lw-race")
    thread = threading.Thread(target=py_loop, daemon=True)
    thread.start()
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        driver.pump()
        cur.execute("SELECT count(*) FROM sessions s "
                    "WHERE s.session_id = ANY(%s::uuid[]) AND v12_turn_open(s.session_id)",
                    (race_sids,))
        if cur.fetchone()[0] == 0:
            break
        time.sleep(0.1)
    stop_py.set()
    thread.join(timeout=10)
    LispWorker.stop_daemon(daemon, "s9")
    py_conn.close()
    cur.execute("SELECT count(*) FROM sessions s "
                "WHERE s.session_id = ANY(%s::uuid[]) AND v12_turn_open(s.session_id)",
                (race_sids,))
    check("race: all three turns settled", cur.fetchone()[0] == 0)
    cur.execute("SELECT count(*), count(*) FILTER (WHERE status = 'answered' "
                "OR status = 'cached') FROM jev_batches "
                "WHERE session_id = ANY(%s::uuid[])", (race_sids,))
    total_b, answered_b = cur.fetchone()
    check("race: every batch answered exactly once (CAS, no double-record)",
          total_b == answered_b and total_b == 3, (total_b, answered_b))
    cur.execute("SELECT count(*) FROM gate_side_effects")
    lisp_effects = cur.fetchone()[0]
    total_effects = lisp_effects + len(py_sent)
    cur.execute("SELECT count(*) FROM jobs WHERE session_id = ANY(%s::uuid[]) "
                "AND status = 'succeeded'", (race_sids,))
    succeeded = cur.fetchone()[0]
    check("race: every job side-effected exactly once across both workers",
          total_effects == succeeded == 3,
          {"lisp": lisp_effects, "python": len(py_sent), "jobs": succeeded})
    for rsid in race_sids:
        end = next(p for t, p in events(cur, rsid) if t == "turn/end")
        check(f"race: delivered {rsid[:8]}", end["delivered"] is True)

    # --- fiveam queue suite -----------------------------------------------------
    proc = subprocess.run(
        ["sbcl", "--script", str(RUN_QUEUE_SUITE)],
        env={**os.environ, "PGSOCKETDIR": SOCKET_DIR, "PGDATABASE": DB},
        capture_output=True, text=True, timeout=300)
    check("fiveam: queue suite green (fake jev/llm, json round-trip)",
          proc.returncode == 0,
          (proc.stdout + proc.stderr)[-2000:] if proc.returncode else "")

    conn.commit()
    conn.close()
    print("[G3 queue] ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
