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
    # G10: the grant stage (complete section 2.1/2.2 model) sits at position
    # 3 — the G9a stub's replacement (the stub DDL migrated here from
    # v8_stream.sql §2–§4) — and MUST load BEFORE the events stage: the
    # public append path consumes the grant predicates (v_grant_find_valid,
    # the stream registry, the heartbeat authorization precheck). The
    # pre-dispatch dual-table atomic sync suboperation also moved here from
    # v8_cancel.sql (it depends only on the schema table family; function
    # bodies are late-bound, so its position before the cancel stage that
    # G11 rewires carries no call-order risk).
    V8_ROOT / "grant" / "v8_grant.sql",
    # G9a/G9b: the streaming foundation — now only the session_events stream
    # columns and the G9b observation path (the slice/grant stub moved to
    # grant/v8_grant.sql by G10). Loading it after the events stage would
    # leave the append path's INSERT and CHECK references unresolved.
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
]

STAGE_THROUGH = {
    "schema": 2,
    # G10 gate covers the append consumer (events stage) on top of its own
    # SQL, so its load set runs through events.
    "grant": 5,
    "events": 5,
    # G9a: the stream gate exercises the consumers of the new foundation —
    # the public append path (events stage) for the chunk six-item
    # attribution, v_complete_effect (effect stage) for the stream_complete
    # field matrix, and the known_failure settlement (retry stage) for the
    # non-known_success exemption negative vector — so its load set runs
    # through retry. The stream SQL itself sits at position 4 (after grant,
    # before events). Semantic note: the load set includes takeover.
    "stream": 10,
    "effect": 6,
    "tools": 7,
    "retry": 10,
    # G5 (loop) adds no SQL: the runtime drives the effect-stage functions.
    "loop": 6,
    "repair": 11,
    "cancel": 12,
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
