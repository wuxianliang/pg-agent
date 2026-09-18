"""G2 gate: v12 decide stage — batch lifecycle, hash cache, validation, routing.

Run: uv run python v12/decide/test_decide.py  (exit 0 = pass)
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
from v12.decide.setup_db import DB, main as setup_db


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


CRITERIA = json.dumps({"a": "option a", "b": "option b"})
LEVELS = json.dumps(["low", "mid", "high"])


def open_batch(cur, sid: str, state: dict, questions: list[tuple]) -> str:
    """questions: (qid, kind, instructions, criteria_json_or_None)"""
    cur.execute("SELECT v12_open_batch(%s, 'adhoc', %s)", (sid, json.dumps(state)))
    batch = cur.fetchone()[0]
    for qid, kind, instr, crit in questions:
        cur.execute("SELECT v12_add_question(%s, %s, %s, %s, %s)",
                    (batch, qid, kind, instr,
                     json.dumps(crit) if crit is not None else None))
    return batch


def good_answers() -> dict:
    return {
        "pick": {"type": "choice", "choice": "a",
                 "probabilities": {"a": 0.9, "b": 0.1}, "confidence": 0.9},
        "rate": {"type": "score", "score": 1.5, "confidence": 0.8},
        "yes": {"type": "noul", "noul": 0.95},
    }


def main() -> int:
    setup_db()
    server = get_server()
    conn = psycopg2.connect(server.get_uri(DB))
    cur = conn.cursor()
    sid = u()
    cur.execute("INSERT INTO sessions (session_id, workspace_id) VALUES (%s, 'w1')",
                (sid,))
    cur.execute(
        "INSERT INTO thresholds (purpose, question_id, act_min, review_min) VALUES "
        "('adhoc', 'pick', 0.8, 0.5), "
        "('adhoc', 'rate', 0.8, 0.5), "
        "('adhoc', 'yes', 0.8, 0.5)")

    qs = [("pick", "choice", "Pick one.", json.loads(CRITERIA)),
          ("rate", "score", "Rate it.", json.loads(LEVELS)),
          ("yes", "noul", "Is it true?", None)]

    # --- lifecycle: open -> ready -----------------------------------------
    b1 = open_batch(cur, sid, {"ticket": "payouts failing"}, qs)
    cur.execute("SELECT v12_seal_batch(%s)", (b1,))
    check("lifecycle: seal open batch -> ready", cur.fetchone()[0] == "ready")

    fails_with(cur, "SELECT v12_seal_batch(%s)", (b1,),
               "open batch", "lifecycle: re-seal rejected")

    b_empty = open_batch(cur, sid, {"x": 1}, [])
    fails_with(cur, "SELECT v12_seal_batch(%s)", (b_empty,),
               "empty batch", "lifecycle: empty batch cannot be sealed")

    fails_with(cur, "SELECT v12_add_question(%s, 'late', 'noul', 'Too late.')",
               (b1,), "not open", "lifecycle: add question after seal rejected")

    # --- record: validation -------------------------------------------------
    fails_with(cur, "SELECT v12_record_answers(%s, %s)",
               (b1, json.dumps({})),
               "missing answer", "record: incomplete answer set rejected")
    cur.execute("SELECT status FROM jev_batches WHERE batch_id = %s", (b1,))
    check("record: failed record leaves batch ready", cur.fetchone()[0] == "ready")

    bad = good_answers()
    del bad["pick"]["probabilities"]
    fails_with(cur, "SELECT v12_record_answers(%s, %s)",
               (b1, json.dumps(bad)),
               "probabilities", "record: choice without probabilities rejected")

    bad = good_answers()
    bad["pick"]["choice"] = "zzz"
    bad["pick"]["probabilities"] = {"a": 0.5, "b": 0.2, "zzz": 0.3}
    fails_with(cur, "SELECT v12_record_answers(%s, %s)",
               (b1, json.dumps(bad)),
               "not in criteria", "record: option outside criteria rejected")

    bad = good_answers(); bad["yes"]["noul"] = 1.5
    fails_with(cur, "SELECT v12_record_answers(%s, %s)",
               (b1, json.dumps(bad)),
               "out of [0,1]", "record: noul out of range rejected")

    bad = good_answers(); bad["rate"]["score"] = 9
    fails_with(cur, "SELECT v12_record_answers(%s, %s)",
               (b1, json.dumps(bad)),
               "outside level range", "record: score outside levels rejected")

    bad = good_answers(); del bad["rate"]["confidence"]
    fails_with(cur, "SELECT v12_record_answers(%s, %s)",
               (b1, json.dumps(bad)),
               "confidence", "record: score without confidence rejected")

    bad = good_answers(); bad["ghost"] = {"type": "noul", "noul": 0.1}
    fails_with(cur, "SELECT v12_record_answers(%s, %s)",
               (b1, json.dumps(bad)),
               "unknown question", "record: unknown question id rejected")

    b_open = open_batch(cur, sid, {"y": 2}, qs)
    fails_with(cur, "SELECT v12_record_answers(%s, %s)",
               (b_open, json.dumps(good_answers())),
               "ready batch", "record: non-ready batch rejected")

    cur.execute("SELECT v12_record_answers(%s, %s, %s, 114)",
                (b1, json.dumps(good_answers()), json.dumps({"input_tokens": 312})))
    check("record: valid answers recorded", cur.fetchone()[0] == 3)
    cur.execute("SELECT status, usage->>'input_tokens', latency_ms "
                "FROM jev_batches WHERE batch_id = %s", (b1,))
    row = cur.fetchone()
    check("record: usage/latency persisted", row == ("answered", "312", 114), row)

    # --- hash cache: identical payload replays for free ---------------------
    b2 = open_batch(cur, sid, {"ticket": "payouts failing"}, qs)
    cur.execute("SELECT v12_seal_batch(%s)", (b2,))
    check("cache: identical payload seals as cached", cur.fetchone()[0] == "cached")
    cur.execute("SELECT cached_from, latency_ms FROM jev_batches WHERE batch_id = %s",
                (b2,))
    row = cur.fetchone()
    check("cache: points at source with zero latency", row == (b1, 0), row)
    cur.execute(
        "SELECT count(*) FROM jev_decisions d1 JOIN jev_decisions d2 "
        "USING (question_id) WHERE d1.batch_id = %s AND d2.batch_id = %s "
        "AND d1.answer = d2.answer", (b1, b2))
    check("cache: decisions copied verbatim", cur.fetchone()[0] == 3)

    b3 = open_batch(cur, sid, {"ticket": "different ticket"}, qs)
    cur.execute("SELECT v12_seal_batch(%s)", (b3,))
    cur.execute("SELECT status FROM jev_batches WHERE batch_id = %s", (b3,))
    check("cache: different state misses cache", cur.fetchone()[0] == "ready")

    b4 = open_batch(cur, sid, {"ticket": "payouts failing"},
                    qs + [("extra", "noul", "One more?", None)])
    cur.execute("SELECT v12_seal_batch(%s)", (b4,))
    cur.execute("SELECT status FROM jev_batches WHERE batch_id = %s", (b4,))
    check("cache: different question set misses cache", cur.fetchone()[0] == "ready")

    # --- routing view --------------------------------------------------------
    cur.execute(
        "SELECT question_id, signal, verdict FROM v12_routes "
        "WHERE batch_id = %s ORDER BY question_id", (b1,))
    rows = {r[0]: (float(r[1]), r[2]) for r in cur.fetchall()}
    check("routes: choice act (conf 0.9 >= 0.8)", rows["pick"] == (0.9, "act"), rows)
    check("routes: score act (score 1.5 >= 0.8; signal is the score value)",
          rows["rate"] == (1.5, "act"), rows)
    check("routes: noul signal uses noul value (0.95)",
          rows["yes"] == (0.95, "act"), rows)

    b5 = open_batch(cur, sid, {"ticket": "band test"}, qs)
    mid = good_answers()
    mid["pick"]["confidence"] = 0.6   # choice: review band (signal = confidence)
    mid["rate"]["score"] = 0.2        # score: below review (signal = score value)
    mid["yes"]["noul"] = 0.55         # noul: review band
    cur.execute("SELECT v12_seal_batch(%s)", (b5,))
    cur.execute("SELECT v12_record_answers(%s, %s)", (b5, json.dumps(mid)))
    cur.execute(
        "SELECT question_id, verdict FROM v12_routes "
        "WHERE batch_id = %s ORDER BY question_id", (b5,))
    rows = dict(cur.fetchall())
    check("routes: review band", rows["pick"] == "review", rows)
    check("routes: below review falls back to human", rows["rate"] == "human", rows)
    check("routes: noul review band", rows["yes"] == "review", rows)

    conn.commit()
    conn.close()
    print("[G2 decide] ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
