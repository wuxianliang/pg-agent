"""Cumulative SQL load order for v8 stages.

Entry 1-2 are the G2 schema foundation (tables + SQL key functions). Later
stages append their SQL files to SQL_LOAD_ORDER; every stage database is
dropped and reloaded from scratch by its setup_db.py, so files are plain
CREATE statements without IF NOT EXISTS.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from pgembed import POSTGRES_BIN_PATH

V8_ROOT = Path(__file__).resolve().parent
AGENT_ROOT = V8_ROOT.parent

SQL_LOAD_ORDER: list[Path] = [
    V8_ROOT / "schema" / "v8_schema.sql",
    V8_ROOT / "schema" / "v8_keys.sql",
    # G9a: the streaming foundation MUST load BEFORE the events stage. It adds
    # the session_events stream columns (stream_id/chunk_index/
    # observation_ordinal) with their column-level CHECKs and creates the
    # minimal slice/grant stub + v_grant_valid that the public append path's
    # assistant/chunk six-item attribution validation consumes. Loading it
    # after the events stage would leave the append path's INSERT and CHECK
    # references unresolved.
    V8_ROOT / "stream" / "v8_stream.sql",
    V8_ROOT / "events" / "v8_append.sql",
    V8_ROOT / "effect" / "v8_effect.sql",
    V8_ROOT / "tools" / "v8_tools.sql",
    # G8b: the shared cancel closure sub-operation (five exits / cancel code
    # map / shared turn-end derivation). It is the cancel stage's artifact
    # but sits BEFORE the retry stage because the retry-stage ledger
    # (aggregation rule 3 judgment + applier), the recovery takeover and the
    # repair command all consume it; it depends only on the
    # schema/keys/events/effect foundations.
    V8_ROOT / "cancel" / "v8_closure.sql",
    V8_ROOT / "retry" / "v8_retry.sql",
    V8_ROOT / "retry" / "v8_takeover.sql",
    V8_ROOT / "repair" / "v8_repair.sql",
    V8_ROOT / "cancel" / "v8_cancel.sql",
    # G13: the P0C dsh-compat host-agnostic contract surface, appended at
    # the END of the load order (no mid-order insertion — every existing
    # stage keeps its file set and count). It depends only on the
    # schema/keys/events foundations and the slice/grant stub surface, so
    # appending is safe for all earlier stages (their load sets stop
    # before this entry).
    V8_ROOT / "compat" / "v8_compat.sql",
]

STAGE_THROUGH = {
    "schema": 2,
    "events": 4,
    # G9a: the stream gate exercises the consumers of the new foundation —
    # the public append path (events stage) for the chunk six-item
    # attribution, v_complete_effect (effect stage) for the stream_complete
    # field matrix, and the known_failure settlement (retry stage) for the
    # non-known_success exemption negative vector — so its load set runs
    # through retry. The stream SQL itself sits at position 3 (before events).
    "stream": 9,
    "effect": 5,
    "tools": 6,
    "retry": 9,
    # G5 (loop) adds no SQL: the runtime drives the effect-stage functions.
    "loop": 5,
    "repair": 10,
    "cancel": 11,
    # G13: compat loads the full 12-file set (branch-local count; the
    # merge-order reconciliation lifts this to 14 once G10/G11 insert
    # grant/plugin ahead of it — existing stage counts are untouched on
    # this branch).
    "compat": 12,
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
