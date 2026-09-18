"""G5 gate: v12 fanout stage — set-based row ranking via one Choice + Noul.

Run: uv run python v12/fanout/test_fanout.py  (exit 0 = pass)

The FakeJev scripts mimic the model semantically: they search the payload's
own state for the marker text and answer accordingly — window pass picks the
window containing the marker, line pass ranks the marker line top.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v12.fanout.setup_db import DB, main as setup_db
from v12.fake_jev import FakeJev
from v12.worker import TurnRunner


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f": {detail}" if detail else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


MARKER = "REFUND WINDOW IS 30 DAYS"
QUERY = "How long do refunds take?"


def load_doc(cur, doc_id: str, n_lines: int, marker_at: int):
    for i in range(n_lines):
        text = (f"Section {i}: general policy clause about billing."
                if i != marker_at else
                f"Section {i}: {MARKER} from purchase date.")
        cur.execute(
            "INSERT INTO fanout_docs (doc_id, line_no, line) VALUES (%s, %s, %s)",
            (doc_id, i, text))
    cur.connection.commit()


def window_script(marker: str):
    """Answers the window pass: the window whose text contains the marker."""
    def fn(payload):
        if "window" not in payload["questions"]:
            return None
        windows = payload["state"]["windows"]
        hit = next(w for w, v in windows.items() if marker in v["text"])
        probs = {w: (0.85 if w == hit else 0.15 / (len(windows) - 1))
                 for w in windows}
        return {"window": {"type": "choice", "choice": hit,
                           "probabilities": probs, "confidence": 0.9}}
    return fn


def line_script(marker: str, exists: float = 0.95):
    """Answers the line pass: ranks the marker line top; existence via Noul."""
    def fn(payload):
        if "where" not in payload["questions"]:
            return None
        lines = payload["state"]["lines"]
        hit = next(l for l, t in lines.items() if marker in t)
        probs = {l: (0.8 if l == hit else 0.2 / (len(lines) - 1))
                 for l in lines}
        return {
            "where": {"type": "choice", "choice": hit,
                      "probabilities": probs, "confidence": 0.9},
            "exists": {"type": "noul", "noul": exists},
        }
    return fn


def ask(conn, fake, batch):
    cur = conn.cursor()
    cur.execute("SELECT v12_seal_batch(%s)", (batch,))
    conn.commit()
    TurnRunner(conn, fake)._ask_batch(batch)


def main() -> int:
    setup_db()
    server = get_server()
    conn = psycopg2.connect(server.get_uri(DB))
    cur = conn.cursor()

    # --- 1. small doc: single-pass line ranking ------------------------------
    load_doc(cur, "small", 40, 37)
    fake = FakeJev([line_script(MARKER)])
    cur.execute("SELECT v12_fanout_open_lines('small', %s, 0, 39)", (QUERY,))
    b = cur.fetchone()[0]
    ask(conn, fake, b)
    cur.execute("SELECT line_no, round(probability, 3) FROM v12_fanout_top(%s, 3)",
                (b,))
    top = cur.fetchall()
    check("single-pass: marker line ranks first", top[0][0] == 37, top)
    cur.execute("SELECT v12_fanout_verdict(%s)", (b,))
    check("single-pass: verdict found", cur.fetchone()[0] == "found")
    cur.execute("SELECT count(*) FROM jev_questions WHERE batch_id = %s", (b,))
    check("single-pass: 2 questions rank 40 rows", cur.fetchone()[0] == 2)
    check("single-pass: one Jev call", len(fake.calls) == 1)

    # ranking comes from the probability distribution, not the seq order
    cur.execute("SELECT count(*) FROM v12_fanout_top(%s, 40)", (b,))
    check("single-pass: full ranking materialized for every row",
          cur.fetchone()[0] == 40)

    # --- 2. big doc: two-pass window -> line ----------------------------------
    load_doc(cur, "big", 600, 456)
    fake = FakeJev([window_script(MARKER), line_script(MARKER)])
    cur.execute("SELECT v12_fanout_open_windows('big', %s, 200)", (QUERY,))
    wb = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM jsonb_object_keys("
                "(SELECT state -> 'windows' FROM jev_batches WHERE batch_id = %s))",
                (wb,))
    check("two-pass: 3 windows built", cur.fetchone()[0] == 3)
    ask(conn, fake, wb)
    cur.execute("SELECT v12_fanout_narrow(%s)", (wb,))
    lb = cur.fetchone()[0]
    check("two-pass: narrow opened a line batch", lb is not None)
    cur.execute(
        "SELECT count(*) FROM jsonb_object_keys("
        "(SELECT state -> 'lines' FROM jev_batches WHERE batch_id = %s))",
        (lb,))
    n_lines = cur.fetchone()[0]
    check("two-pass: line batch covers exactly the winning window",
          n_lines == 200, n_lines)
    ask(conn, fake, lb)
    cur.execute("SELECT line_no FROM v12_fanout_top(%s, 1)", (lb,))
    check("two-pass: marker found through both passes", cur.fetchone()[0] == 456)
    cur.execute("SELECT v12_fanout_verdict(%s)", (lb,))
    check("two-pass: verdict found", cur.fetchone()[0] == "found")
    check("two-pass: exactly two Jev calls", len(fake.calls) == 2)

    # --- 3. absent query: existence Noul overrides the ranking ---------------
    load_doc(cur, "absent", 10, 5)
    fake = FakeJev([line_script(MARKER, exists=0.05)])
    cur.execute("SELECT v12_fanout_open_lines('absent', %s, 0, 9)", (QUERY,))
    ab = cur.fetchone()[0]
    ask(conn, fake, ab)
    cur.execute("SELECT v12_fanout_verdict(%s)", (ab,))
    check("absent: existence Noul below band -> absent despite ranking",
          cur.fetchone()[0] == "absent")

    # --- 4. guards -------------------------------------------------------------
    # window >255 rejected
    try:
        cur.execute("SELECT v12_fanout_open_lines('big', 'q', 0, 599)")
        raise AssertionError("expected 255-option limit rejection")
    except psycopg2.Error as exc:
        conn.rollback()
        check("guard: >255 options rejected",
              "255" in str(exc), str(exc).splitlines()[0])
    # empty range rejected
    try:
        cur.execute("SELECT v12_fanout_open_lines('small', 'q', 100, 200)")
        raise AssertionError("expected empty range rejection")
    except psycopg2.Error as exc:
        conn.rollback()
        check("guard: empty range rejected",
              "empty range" in str(exc).lower(), str(exc).splitlines()[0])

    conn.close()
    print("[G5 fanout] ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
