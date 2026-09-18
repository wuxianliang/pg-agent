"""Cumulative SQL load order for v12 stages.

Plain CREATE statements without IF NOT EXISTS: every stage database is
dropped and reloaded from scratch by its setup_db.py. New stages append
their SQL file at the END of SQL_LOAD_ORDER only.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from pgembed import POSTGRES_BIN_PATH

V12_ROOT = Path(__file__).resolve().parent
AGENT_ROOT = V12_ROOT.parent

SQL_LOAD_ORDER: list[Path] = [
    # M1: the three planes — journal (sessions/events), decision
    # (jev_batches/jev_questions/jev_decisions/thresholds), action
    # (tools/jobs) — plus the append-only/no-hole-seq foundation.
    V12_ROOT / "schema" / "v12_schema.sql",
    # M2: batch lifecycle (open → ready/answered/cached), request_hash
    # idempotent cache, per-question answer validation, threshold routing.
    V12_ROOT / "decide" / "v12_decide.sql",
    # M3: effect discipline for real side effects only — idempotent
    # enqueue by stable effect_id, claim/fence/lease, CAS completion,
    # explicit unknown resolution.
    V12_ROOT / "act" / "v12_act.sql",
    # M4: the bounded turn pipeline — state fold (SQL computes derived
    # numbers), English question builders, deterministic routing policy,
    # guardrails, durable step budget, seeded demo tools + thresholds.
    V12_ROOT / "turn" / "v12_turn.sql",
    # M5: set-based fanout ranking (semantic_find pattern) — one Choice
    # over up to 255 line ids + existence Noul, two-pass windowing beyond.
    V12_ROOT / "fanout" / "v12_fanout.sql",
    # M6: the queue mode — pgmq wake-up queue, scan-based requeue, SQL-side
    # deterministic effect identity. Appended at the END of the order.
    V12_ROOT / "queue" / "v12_queue.sql",
]

STAGE_THROUGH = {
    "schema": 1,
    "decide": 2,
    "act": 3,
    "turn": 4,
    "fanout": 5,
    "queue": 6,
}


def files_through(stage: str) -> list[Path]:
    n = STAGE_THROUGH[stage]
    return SQL_LOAD_ORDER[:n]


def run_psql(server, database: str, sql: str, on_error_stop: bool = True) -> str:
    uri = server.get_uri(database)
    proc = subprocess.run(
        [str(POSTGRES_BIN_PATH / "psql"), uri, "-v",
         "ON_ERROR_STOP=" + ("1" if on_error_stop else "0"), "-q"],
        input=sql.encode(),
        capture_output=True,
    )
    out = proc.stdout.decode() + proc.stderr.decode()
    if proc.returncode != 0 and on_error_stop:
        raise RuntimeError(f"psql failed ({proc.returncode}):\n{out}")
    return out


def load_stage(server, database: str, stage: str) -> None:
    for path in files_through(stage):
        if not path.exists():
            raise FileNotFoundError(f"missing SQL in load order: {path}")
        out = run_psql(server, database, path.read_text(), on_error_stop=True)
        errors = [l for l in out.splitlines() if "ERROR" in l or "FATAL" in l]
        print(f"[loaded ] {database} <- {path.name}: {'FAIL' if errors else 'OK'}")
        for e in errors:
            print(f"          {e}")
        if errors:
            raise RuntimeError(f"errors loading {path}")
