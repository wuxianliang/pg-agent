"""G7 gate: v12 indb stage — the decision plane asks Jev from inside SQL.

Run: uv run python v12/indb/test_indb.py  (exit 0 = pass)

Offline by construction: typesafe.mock_response pins the extension's
reply, so the gate exercises the real pg_typesafe C path (request packing,
response parsing) without any network. The manual v12/indb/probe_indb.py
does the same flow against live OpenRouter.
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v12.indb.setup_db import DB, main as setup_db


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f": {detail}" if detail else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def u() -> str:
    return str(uuid.uuid4())


def turn_mock(**kw):
    opts = dict(intent="sql_answer", intent_conf=0.9,
                gate_action=0.9, gate_off_topic=0.05,
                risk=0.5, risk_conf=0.9,
                tool="session_stats", tool_conf=0.9,
                tone="formal", tone_conf=0.9, tone_stated=0.1,
                audience="team", audience_conf=0.9, audience_stated=0.1)
    opts.update(kw)
    answers = {
        "intent": {"type": "choice", "choice": opts["intent"],
                   "probabilities": {opts["intent"]: opts["intent_conf"]},
                   "confidence": opts["intent_conf"]},
        "gate_action": {"type": "noul", "noul": opts["gate_action"]},
        "gate_off_topic": {"type": "noul", "noul": opts["gate_off_topic"]},
        "risk": {"type": "score", "score": opts["risk"],
                 "confidence": opts["risk_conf"]},
        "tool": {"type": "choice", "choice": opts["tool"],
                 "probabilities": {opts["tool"]: opts["tool_conf"]},
                 "confidence": opts["tool_conf"]},
        "param::send_summary_email::tone": {
            "type": "choice", "choice": opts["tone"],
            "probabilities": {opts["tone"]: opts["tone_conf"]},
            "confidence": opts["tone_conf"]},
        "stated::send_summary_email::tone": {
            "type": "noul", "noul": opts["tone_stated"]},
        "param::send_summary_email::audience": {
            "type": "choice", "choice": opts["audience"],
            "probabilities": {opts["audience"]: opts["audience_conf"]},
            "confidence": opts["audience_conf"]},
        "stated::send_summary_email::audience": {
            "type": "noul", "noul": opts["audience_stated"]},
    }
    return json.dumps({"model": "jev-mock", "answers": answers,
                       "usage": {"input_tokens": 312, "output_tokens": 48}})


def guard_mock(pii_free=0.98, on_topic=0.95, safe=0.97):
    return json.dumps({
        "model": "jev-mock",
        "answers": {"guard_pii_free": {"type": "noul", "noul": pii_free},
                    "guard_on_topic": {"type": "noul", "noul": on_topic},
                    "guard_safe": {"type": "noul", "noul": safe}},
        "usage": {"input_tokens": 90, "output_tokens": 9}})


def set_mock(cur, mock: str) -> None:
    cur.execute("SELECT set_config('typesafe.mock_response', %s, true)",
                (mock,))


def main() -> int:
    setup_db()
    server = get_server()
    conn = psycopg2.connect(server.get_uri(DB))
    cur = conn.cursor()

    def new_session() -> str:
        sid = u()
        cur.execute("INSERT INTO sessions (session_id, workspace_id) "
                    "VALUES (%s, 'indb')", (sid,))
        return sid

    # --- 1. one SQL call decides a whole turn --------------------------------
    sid = new_session()
    cur.execute("SELECT v12_append_event(%s, 'user/message', %s)",
                (sid, json.dumps({"text": "How many messages so far?"})))
    set_mock(cur, turn_mock())
    cur.execute("SELECT v12_decide_in_db(%s)", (sid,))
    route = cur.fetchone()[0]
    check("decide: returns route", route == "sql", route)
    cur.execute("SELECT payload FROM events WHERE session_id = %s "
                "AND type = 'turn/route'", (sid,))
    ev = cur.fetchone()[0]
    check("decide: route event durable with intent+tool",
          ev["intent"] == "sql_answer" and ev["tool"] == "session_stats", ev)
    cur.execute("SELECT status, usage->>'input_tokens', latency_ms "
                "FROM jev_batches WHERE session_id = %s", (sid,))
    row = cur.fetchone()
    check("decide: batch answered in-DB with usage+latency",
          row[0] == "answered" and row[1] == "312" and row[2] is not None, row)
    cur.execute("SELECT count(*) FROM jev_decisions d "
                "JOIN jev_batches b USING (batch_id) "
                "WHERE b.session_id = %s", (sid,))
    check("decide: all 9 answers recorded", cur.fetchone()[0] == 9)
    conn.commit()

    # --- 2. low confidence -> human, still one call ---------------------------
    sid = new_session()
    cur.execute("SELECT v12_append_event(%s, 'user/message', %s)",
                (sid, json.dumps({"text": "Ambiguous ask"})))
    set_mock(cur, turn_mock(intent_conf=0.4))
    cur.execute("SELECT v12_decide_in_db(%s)", (sid,))
    check("lowconf: routed human in-DB", cur.fetchone()[0] == "human")
    conn.commit()

    # --- 3. durable budget honored in-DB --------------------------------------
    sid = new_session()
    cur.execute("SELECT v12_append_event(%s, 'user/message', %s)",
                (sid, json.dumps({"text": "keep going"})))
    for _ in range(3):
        cur.execute("SELECT v12_append_event(%s, 'turn/route', "
                    "'{\"route\":\"llm\",\"reason\":\"filler\"}')", (sid,))
    conn.commit()
    cur.execute("SELECT v12_decide_in_db(%s)", (sid,))
    check("budget: in-DB decide forces human", cur.fetchone()[0] == "human")
    cur.execute("SELECT payload FROM events WHERE session_id = %s "
                "AND type = 'turn/end'", (sid,))
    check("budget: closed as budget_exhausted",
          cur.fetchone()[0]["reason"] == "budget_exhausted")
    cur.execute("SELECT count(*) FROM jev_batches WHERE session_id = %s",
                (sid,))
    check("budget: no batch spent on a doomed turn",
          cur.fetchone()[0] == 0)
    conn.commit()

    # --- 4. malformed answer -> whole decide rolls back ------------------------
    sid = new_session()
    cur.execute("SELECT v12_append_event(%s, 'user/message', %s)",
                (sid, json.dumps({"text": "broken"})))
    bad = json.loads(turn_mock())
    del bad["answers"]["intent"]["probabilities"]
    set_mock(cur, json.dumps(bad))
    try:
        cur.execute("SELECT v12_decide_in_db(%s)", (sid,))
        raise AssertionError("expected validation failure")
    except psycopg2.Error as exc:
        conn.rollback()
        check("malformed: validation rejects in-DB",
              "probabilities" in str(exc), str(exc).splitlines()[0])
    cur.execute("SELECT count(*) FROM jev_batches WHERE session_id = %s",
                (sid,))
    check("malformed: single-transaction decide leaves zero batches",
          cur.fetchone()[0] == 0)
    cur.execute("SELECT count(*) FROM events WHERE session_id = %s "
                "AND type = 'turn/route'", (sid,))
    check("malformed: no route event survived", cur.fetchone()[0] == 0)
    conn.commit()

    # --- 5. guardrail fully in-DB ----------------------------------------------
    sid = new_session()
    state = json.dumps({"messages": [{"seq": 1, "type": "user/message",
                                      "payload": {"text": "note please"}}],
                        "draft": "A safe closing note."})
    set_mock(cur, guard_mock())
    cur.execute("SELECT v12_guardrail_in_db(%s, %s)", (sid, state))
    check("guardrail: pass in-DB", cur.fetchone()[0] is True)
    conn.commit()

    set_mock(cur, guard_mock(pii_free=0.05))
    leaky_state = json.dumps({
        "messages": [{"seq": 1, "type": "user/message",
                      "payload": {"text": "note please"}}],
        "draft": "Contact john.doe@example.com for details."})
    cur.execute("SELECT v12_guardrail_in_db(%s, %s)", (sid, leaky_state))
    check("guardrail: fail in-DB (PII)", cur.fetchone()[0] is False)
    conn.commit()
    cur.execute("SELECT count(*) FROM jev_batches WHERE session_id = %s "
                "AND purpose = 'guardrail' AND status IN ('answered', 'cached')",
                (sid,))
    check("guardrail: two recorded batches (second is a fresh ask, "
          "identical state would have replayed the cache)",
          cur.fetchone()[0] == 2)

    # --- 6. second turn in the same session stays isolated ---------------------
    cur.execute("SELECT v12_append_event(%s, 'user/message', %s)",
                (sid, json.dumps({"text": "again"})))
    set_mock(cur, turn_mock())
    cur.execute("SELECT v12_decide_in_db(%s)", (sid,))
    check("multi-turn: decide works on the fresh turn",
          cur.fetchone()[0] == "sql")

    conn.commit()
    conn.close()
    print("[G7 indb] ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
