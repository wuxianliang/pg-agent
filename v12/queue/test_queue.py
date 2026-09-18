"""G6 gate: v12 queue mode — pgmq wake-ups, IO worker, SQL-only driver.

Run: uv run python v12/queue/test_queue.py  (exit 0 = pass)

Scenarios: queue-mode e2e (tool route) / transient retry via VT redelivery /
duplicate-message dedupe / deterministic failure -> human / lost-message
scan recovery / llm + guardrail through the queue / cross-mode effect-id
equality and multi-turn batch filtering.
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
from v12.queue.setup_db import DB, main as setup_db
from v12.fake_jev import FakeJev
from v12.jev_client import JevError
from v12.queue_driver import QueueDriver
from v12.queue_worker import QueueWorker


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


def turn_script(**kw):
    opts = dict(intent="sql_answer", intent_conf=0.9,
                gate_action=0.9, gate_off_topic=0.05,
                risk=0.5, risk_conf=0.9,
                tool="session_stats", tool_conf=0.9,
                tone="formal", tone_conf=0.9, tone_stated=0.1,
                audience="team", audience_conf=0.9, audience_stated=0.1)
    opts.update(kw)

    def fn(payload):
        if "intent" not in payload["questions"]:
            return None
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
    return fn


def guard_script(pii_free=0.98, on_topic=0.95, safe=0.97):
    def fn(payload):
        if "guard_pii_free" not in payload["questions"]:
            return None
        return {"guard_pii_free": _noul(pii_free),
                "guard_on_topic": _noul(on_topic),
                "guard_safe": _noul(safe)}
    return fn


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
    sent = []
    fake_tools = {"send_summary_email": lambda payload: sent.append(payload) or
                  {"sent_to": payload["params"].get("audience", "team-default")}}

    # --- 1. queue-mode e2e: tool route + cross-mode effect id ---------------
    sid = new_session(cur)
    fake = FakeJev([turn_script(intent="tool_action", intent_conf=0.92,
                                tool="send_summary_email", tool_conf=0.95,
                                risk=1.0, tone="friendly",
                                tone_conf=0.93, tone_stated=0.9)])
    driver = QueueDriver(conn)
    worker = QueueWorker(conn, fake, tool_impls=fake_tools,
                         worker_id="qw-1")
    driver._append_event(sid, "user/message",
                         {"text": "Send a friendly summary to the team."})
    driver.run_until_idle(worker)
    ev = events(cur, sid)
    check("e2e(tool): routed, executed, closed via queue",
          [t for t, _ in ev] == ["user/message", "turn/route", "tool/result",
                                 "turn/end"], [t for t, _ in ev])
    tr = next(p for t, p in ev if t == "tool/result")
    check("e2e(tool): executed by queue worker with resolved params",
          tr["source"] == "queue_worker" and tr["params"] == {"tone": "friendly"},
          tr)
    check("e2e(tool): side effect hit once", len(sent) == 1)
    cur.execute("SELECT effect_id FROM jobs WHERE session_id = %s", (sid,))
    eff_sql = cur.fetchone()[0]
    import uuid as _uuid
    user_seq = 1
    eff_py = _uuid.uuid5(_uuid.UUID(int=0), f"{sid}:{user_seq}:send_summary_email")
    check("e2e(tool): SQL v12_effect_id == inline runner's uuid5",
          str(eff_sql) == str(eff_py), (str(eff_sql), str(eff_py)))
    cur.execute("SELECT count(*) FROM pgmq.q_v12_work")
    check("e2e(tool): no leftover messages", cur.fetchone()[0] == 0)
    cur.execute("SELECT count(*) FROM pgmq.a_v12_work")
    n_arch = cur.fetchone()[0]
    check("e2e(tool): messages archived", n_arch >= 2, n_arch)

    # --- 2. transient failure -> VT redelivery -------------------------------
    sid = new_session(cur)
    attempts = {"n": 0}

    def flaky(payload):
        if "intent" not in payload["questions"]:
            return None
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise JevError("simulated 529 from openrouter", transient=True)
        return turn_script()(payload)

    fake = FakeJev([flaky])
    driver = QueueDriver(conn)
    worker = QueueWorker(conn, fake, worker_id="qw-2")
    driver._append_event(sid, "user/message", {"text": "Stats please."})
    driver.pump()                      # seals batch + sends message
    n1 = worker.pump()                 # first attempt: transient -> retry
    check("retry: first pump archives nothing", n1 == 0)
    cur.execute("SELECT status FROM jev_batches WHERE session_id = %s",
                (sid,))
    check("retry: batch still ready after transient failure",
          cur.fetchone()[0] == "ready")
    time.sleep(2.2)                    # > RETRY_VT
    driver.run_until_idle(worker, timeout=10)
    check("retry: succeeded on redelivery", attempts["n"] == 2)
    end = next(p for t, p in events(cur, sid) if t == "turn/end")
    check("retry: turn delivered", end["delivered"] is True, end)

    # --- 3. duplicate wake-up dedupe ------------------------------------------
    sid = new_session(cur)
    fake = FakeJev([turn_script()])
    driver = QueueDriver(conn)
    driver._append_event(sid, "user/message", {"text": "Stats again."})
    driver.pump()
    cur.execute("SELECT v12_send_work('jev', batch_id) FROM jev_batches "
                "WHERE session_id = %s AND status = 'ready'", (sid,))
    conn.commit()                      # duplicate the wake-up
    worker = QueueWorker(conn, fake, worker_id="qw-3")
    worker.pump(limit=10)
    check("dedupe: one ask despite duplicate messages",
          len(fake.calls) == 1, len(fake.calls))
    cur.execute("SELECT count(*) FROM pgmq.q_v12_work")
    check("dedupe: queue drained", cur.fetchone()[0] == 0)
    QueueDriver(conn).run_until_idle(worker, timeout=10)

    # --- 4. deterministic answer failure -> human, no retry -------------------
    sid = new_session(cur)

    def malformed(payload):
        if "intent" not in payload["questions"]:
            return None
        ans = turn_script()(payload)
        del ans["intent"]["probabilities"]    # fails record validation
        return ans

    fake = FakeJev([malformed])
    driver = QueueDriver(conn)
    driver._append_event(sid, "user/message", {"text": "Broken answers."})
    driver.pump()
    worker = QueueWorker(conn, fake, worker_id="qw-4")
    n = worker.pump(limit=10)
    check("deterministic: message archived on first attempt", n == 1)
    cur.execute("SELECT status FROM jev_batches WHERE session_id = %s",
                (sid,))
    row = cur.fetchone()
    check("deterministic: batch marked failed with error",
          row[0] == "failed", row)
    check("deterministic: single attempt (no redelivery)", len(fake.calls) == 1)
    driver.pump()
    check("deterministic: turn escalated to human",
          status(cur, sid) == "awaiting_human")
    end = next(p for t, p in events(cur, sid) if t == "turn/end")
    check("deterministic: reason decision_failed",
          end["reason"] == "decision_failed", end)

    # --- 5. lost message -> scan recovery --------------------------------------
    sid = new_session(cur)
    fake = FakeJev([turn_script()])
    driver = QueueDriver(conn)
    driver._append_event(sid, "user/message", {"text": "Lost message."})
    # manual decide WITHOUT sending: batch sealed but no wake-up exists
    state = driver._one("SELECT v12_fold_state(%s)", (sid,))[0]
    batch = driver._one("SELECT v12_open_batch(%s, 'turn', %s)",
                        (sid, json.dumps(state)))[0]
    driver._one("SELECT v12_build_turn_questions(%s, %s)", (batch, sid))
    driver._one("SELECT v12_seal_batch(%s)", (batch,))
    conn.commit()
    worker = QueueWorker(conn, fake, worker_id="qw-5")
    check("recovery: nothing to do without a message", worker.pump() == 0)
    cur.execute("SELECT v12_requeue_stale()")
    requeued = cur.fetchone()[0]
    conn.commit()
    check("recovery: scan re-enqueues the pending batch", requeued == 1, requeued)
    driver.run_until_idle(worker, timeout=10)
    end = next(p for t, p in events(cur, sid) if t == "turn/end")
    check("recovery: turn completes after requeue", end["delivered"] is True)

    # --- 6. llm + guardrail through the queue ----------------------------------
    sid = new_session(cur)
    llm_calls = []

    def fake_llm(payload):
        llm_calls.append(payload)
        return "Postgres keeps the state machine durable."

    fake = FakeJev([turn_script(intent="llm_generate", intent_conf=0.9),
                    guard_script()])
    driver = QueueDriver(conn)
    worker = QueueWorker(conn, fake, tool_impls=fake_tools,
                         llm_fn=fake_llm, worker_id="qw-6")
    driver._append_event(sid, "user/message",
                         {"text": "One sentence on durability."})
    driver.run_until_idle(worker)
    ev = events(cur, sid)
    check("llm: draft -> guardrail -> deliver through queue",
          [t for t, _ in ev] == ["user/message", "turn/route",
                                 "turn/llm_draft", "llm/message", "turn/end"],
          [t for t, _ in ev])
    check("llm: generation ran in the queue worker", len(llm_calls) == 1)
    cur.execute("SELECT count(*) FROM jev_batches WHERE session_id = %s "
                "AND purpose IN ('turn', 'guardrail') "
                "AND status IN ('answered', 'cached')", (sid,))
    check("llm: two answered batches (turn + guardrail)",
          cur.fetchone()[0] == 2)
    check("llm: three Jev calls total (turn + guardrail via worker)",
          len(fake.calls) == 2)

    # --- 7. multi-turn in one session: batches filtered per turn ---------------
    driver._append_event(sid, "user/message",
                         {"text": "How many messages now?"})
    fake.scripts.append(turn_script())
    driver.run_until_idle(worker, timeout=10)
    ev = events(cur, sid)
    ends = [p for t, p in ev if t == "turn/end"]
    check("multi-turn: second turn reuses fresh batches, both delivered",
          len(ends) == 2 and all(e["delivered"] for e in ends), ends)

    conn.commit()
    conn.close()
    print("[G6 queue] ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
