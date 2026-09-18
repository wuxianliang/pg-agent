"""G1 gate: v12 schema stage — three planes, append-only journal, DDL invariants.

Run: uv run python v12/schema/test_schema.py  (exit 0 = pass)
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
from v12.schema.setup_db import DB, main as setup_db


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
        check(label, needle in msg, exc)
        cur.execute("ROLLBACK TO SAVEPOINT sp")
        return
    cur.execute("ROLLBACK TO SAVEPOINT sp")
    raise AssertionError(f"{label}: expected failure containing {needle!r}, got success")


def main() -> int:
    setup_db()
    server = get_server()
    conn = psycopg2.connect(server.get_uri(DB))
    cur = conn.cursor()

    # --- journal plane -----------------------------------------------------
    sid = u()
    cur.execute(
        "INSERT INTO sessions (session_id, workspace_id) VALUES (%s, 'w1')", (sid,))
    seqs = []
    for i in range(3):
        cur.execute("SELECT v12_append_event(%s, %s, %s)",
                    (sid, "user/message", json.dumps({"i": i})))
        seqs.append(cur.fetchone()[0])
    check("journal: seq 1,2,3 no holes", seqs == [1, 2, 3], seqs)

    fails_with(cur, "SELECT v12_append_event(%s, 'x', '{}')", (u(),),
               "unknown session", "journal: append to unknown session rejected")

    fails_with(cur, "UPDATE events SET payload = '{}' WHERE session_id = %s", (sid,),
               "append-only", "journal: UPDATE events rejected")
    fails_with(cur, "DELETE FROM events WHERE session_id = %s", (sid,),
               "append-only", "journal: DELETE events rejected")

    cur.execute("SELECT v12_set_status(%s, 'awaiting_human')", (sid,))
    cur.execute("SELECT status FROM sessions WHERE session_id = %s", (sid,))
    check("journal: status setter works", cur.fetchone()[0] == "awaiting_human")
    fails_with(cur, "SELECT v12_set_status(%s, 'bogus')", (sid,),
               "check constraint", "journal: invalid status rejected")

    # payload default '{}'
    sid2 = u()
    cur.execute(
        "INSERT INTO sessions (session_id, workspace_id) VALUES (%s, 'w1')", (sid2,))
    cur.execute("SELECT v12_append_event(%s, 'system/note')", (sid2,))
    cur.execute(
        "SELECT payload FROM events WHERE session_id = %s AND seq = 1", (sid2,))
    check("journal: payload defaults to {}", cur.fetchone()[0] == {})

    # --- decision plane ----------------------------------------------------
    sid3 = u()
    cur.execute(
        "INSERT INTO sessions (session_id, workspace_id) VALUES (%s, 'w1')", (sid3,))
    cur.execute(
        "INSERT INTO jev_batches (session_id, purpose, state) "
        "VALUES (%s, 'adhoc', '{}') RETURNING batch_id", (sid3,))
    batch = cur.fetchone()[0]

    cur.execute(
        "INSERT INTO jev_questions (batch_id, question_id, kind, instructions, criteria) "
        "VALUES (%s, 'q_choice', 'choice', 'Pick one.', %s)",
        (batch, json.dumps({"a": "option a", "b": None})))
    cur.execute(
        "INSERT INTO jev_questions (batch_id, question_id, kind, instructions, criteria) "
        "VALUES (%s, 'q_score', 'score', 'Rate it.', %s)",
        (batch, json.dumps(["low", "mid", "high"])))
    cur.execute(
        "INSERT INTO jev_questions (batch_id, question_id, kind, instructions) "
        "VALUES (%s, 'q_noul', 'noul', 'Is it true?')", (batch,))
    check("decision: valid questions accepted", True)

    fails_with(cur,
               "INSERT INTO jev_questions (batch_id, question_id, kind, instructions, criteria) "
               "VALUES (%s, 'bad1', 'choice', 'Pick.', %s)",
               (batch, json.dumps(["a", "b"])),
               "choice_shape", "decision: choice with array criteria rejected")
    fails_with(cur,
               "INSERT INTO jev_questions (batch_id, question_id, kind, instructions, criteria) "
               "VALUES (%s, 'bad2', 'score', 'Rate.', %s)",
               (batch, json.dumps(["only"])),
               "score_shape", "decision: score with one level rejected")
    fails_with(cur,
               "INSERT INTO jev_questions (batch_id, question_id, kind, instructions) "
               "VALUES (%s, 'bad3', 'noul', '真的吗？')",
               (batch,), "instructions_check",
               "decision: non-ASCII (CJK) instructions rejected")
    fails_with(cur,
               "INSERT INTO jev_questions (batch_id, question_id, kind, instructions, criteria) "
               "VALUES (%s, 'bad4', 'choice', 'Pick.', %s)",
               (batch, json.dumps({"a": "描述"})),
               "criteria_ascii", "decision: non-ASCII criteria rejected")
    fails_with(cur,
               "INSERT INTO jev_batches (session_id, purpose, state) "
               "VALUES (%s, 'nope', '{}')", (sid3,),
               "check constraint", "decision: unknown purpose rejected")

    # thresholds: act_min >= review_min, fallback default
    cur.execute(
        "INSERT INTO thresholds (purpose, question_id, act_min, review_min) "
        "VALUES ('adhoc', 'q_choice', 0.8, 0.5)")
    cur.execute("SELECT fallback FROM thresholds "
                "WHERE purpose = 'adhoc' AND question_id = 'q_choice'")
    check("decision: threshold fallback defaults to human",
          cur.fetchone()[0] == "human")
    fails_with(cur,
               "INSERT INTO thresholds (purpose, question_id, act_min, review_min) "
               "VALUES ('adhoc', 'q_score', 0.3, 0.5)",
               (), "thresholds_check", "decision: act_min < review_min rejected")

    # --- action plane ------------------------------------------------------
    cur.execute(
        "INSERT INTO tools (name, description, effect_class, handler) "
        "VALUES ('demo', 'A demo tool.', 'side_effect', 'demo_handler')")
    check("action: tool catalog insert", True)
    fails_with(cur,
               "INSERT INTO tools (name, description, effect_class, handler) "
               "VALUES ('bad', '描述', 'side_effect', 'h')",
               (), "check", "action: non-ASCII tool description rejected")

    eff = u()
    cur.execute(
        "INSERT INTO jobs (session_id, effect_id, kind) VALUES (%s, %s, 'demo')",
        (sid3, eff))
    fails_with(cur,
               "INSERT INTO jobs (session_id, effect_id, kind) VALUES (%s, %s, 'demo')",
               (sid3, eff), "duplicate key",
               "action: duplicate effect_id rejected (stable identity)")
    fails_with(cur,
               "INSERT INTO jobs (session_id, effect_id, kind, status) "
               "VALUES (%s, %s, 'demo', 'weird')",
               (sid3, u()), "check constraint",
               "action: unknown job status rejected")

    conn.commit()
    conn.close()
    print("[G1 schema] ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
