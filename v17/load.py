"""Cumulative SQL load order for v17 stages.

Modeled on v12/load.py (same run_psql/load_stage pattern, reimplemented
here so v17 does not import across version lines). v12's seven SQL files
are referenced by relative path and loaded READ-ONLY (Lineage convention:
v12 is never modified); v17's own store/world SQL is appended at the END.
Plain CREATE statements without IF NOT EXISTS: every stage database is
dropped and reloaded from scratch by its setup_db.py.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from pgembed import POSTGRES_BIN_PATH

V17_ROOT = Path(__file__).resolve().parent
AGENT_ROOT = V17_ROOT.parent
V12_ROOT = AGENT_ROOT / "v12"

SQL_LOAD_ORDER: list[Path] = [
    # --- v12 lineage, loaded read-only (same order as v12/load.py) ---
    V12_ROOT / "schema" / "v12_schema.sql",   # M1: three planes + append-only foundation
    V12_ROOT / "decide" / "v12_decide.sql",   # M2: batch lifecycle / request_hash cache
    V12_ROOT / "act" / "v12_act.sql",         # M3: effect discipline (claim/fence/lease)
    V12_ROOT / "turn" / "v12_turn.sql",       # M4: bounded turn pipeline
    V12_ROOT / "fanout" / "v12_fanout.sql",   # M5: set-based fanout ranking
    V12_ROOT / "queue" / "v12_queue.sql",     # M6: pgmq wake-up queue + requeue_stale
    V12_ROOT / "indb" / "v12_indb.sql",       # M7: decision plane in-DB (pg_typesafe)
    # --- v17's own surface (plan §3), appended at the END ---
    V17_ROOT / "store" / "v17_store.sql",     # G1: jiti file store as Postgres tables
    V17_ROOT / "world" / "v17_world.sql",     # G2: world ops enter the effect bus
]

# Later stages (queue/lisptools/develop/repair) add no SQL of their own;
# they gate on the full order loaded by the world stage.
STAGE_THROUGH = {
    "store": 8,
    "world": 9,
    "queue": 9,
    "lisptools": 9,
    "develop": 9,
    "repair": 9,
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
