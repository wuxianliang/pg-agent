"""Cumulative SQL load order for v13 stages.

Plain CREATE statements without IF NOT EXISTS: every stage database is
dropped and reloaded from scratch by its setup_db.py. New stages append
their SQL file at the END of SQL_LOAD_ORDER only.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from pgembed import POSTGRES_BIN_PATH

V13_ROOT = Path(__file__).resolve().parent
AGENT_ROOT = V13_ROOT.parent

SQL_LOAD_ORDER: list[Path] = [
    V13_ROOT / "schema" / "v13_core.sql",
    V13_ROOT / "resolve" / "v13_resolve.sql",
    V13_ROOT / "loop" / "advance.sql",
    V13_ROOT / "twophase" / "v13_twophase.sql",
    V13_ROOT / "envelope" / "v13_envelope.sql",
    V13_ROOT / "manifest" / "v13_manifest.sql",
    V13_ROOT / "chunks" / "v13_chunks.sql",
    V13_ROOT / "recall" / "v13_recall.sql",
    V13_ROOT / "characterize" / "v13_characterize.sql",
    V13_ROOT / "filter" / "v13_filter.sql",
    V13_ROOT / "memory" / "v13_memory.sql",
    V13_ROOT / "economy" / "v13_economy.sql",
    V13_ROOT / "summary" / "v13_summary.sql",
    V13_ROOT / "periphery" / "v13_periphery.sql",
    V13_ROOT / "mgraph" / "v13_mgraph.sql",
    V13_ROOT / "mgraph_assembly" / "v13_mgraph_assembly.sql",
    V13_ROOT / "control" / "v13_control.sql",
    V13_ROOT / "spawn" / "v13_spawn.sql",
    V13_ROOT / "fanout" / "v13_fanout.sql",
    V13_ROOT / "triage" / "v13_triage.sql",
    V13_ROOT / "seam" / "v13_seam.sql",
]

STAGE_THROUGH = {
    "schema": 1,
    "resolve": 2,
    "loop": 3,
    "twophase": 4,
    "envelope": 5,
    "manifest": 6,
    "chunks": 7,
    "recall": 8,
    "characterize": 9,
    "filter": 10,
    "memory": 11,
    "economy": 12,
    "summary": 13,
    "periphery": 14,
    "mgraph": 15,
    "mgraph_assembly": 16,
    "control": 17,
    "spawn": 18,
    "fanout": 19,
    "triage": 20,
    "seam": 21,
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
