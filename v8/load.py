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
    # G11: the §4 plugin generation domain (plugin_specs/implementations/
    # generations/generation_members, the stable dependency resolution, the
    # generation digest, the publish lifecycle, the shared generation-check
    # sub-operation for the G12 gates and the offline revocation drain).
    # It sits BEFORE the effect stage: steps gain catalog_generation + the
    # implementation binding column with the DEFAULT seed generation here,
    # consumed by the effect and later stages. The file also carries the
    # shared pre-dispatch cancel sync sub-operation whose final home (after
    # the G10 merge) is grant/v8_grant.sql — on this branch it is defined
    # here with CREATE OR REPLACE so the cancel stage's call resolves
    # (deviation A62); it depends only on the schema family and its body
    # resolves late, so the position carries no call-order risk.
    V8_ROOT / "plugin" / "v8_plugin.sql",
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
    "events": 4,
    # G9a: the stream gate exercises the consumers of the new foundation —
    # the public append path (events stage) for the chunk six-item
    # attribution, v_complete_effect (effect stage) for the stream_complete
    # field matrix, and the known_failure settlement (retry stage) for the
    # non-known_success exemption negative vector — so its load set runs
    # through retry. The stream SQL itself sits at position 3 (before
    # events). G11 inserted plugin/v8_plugin.sql after events, so every
    # stage loading from effect onwards counts one more file (branch-local
    # in-place +1; the merge commit reconciles across the G10/G13 branches).
    "stream": 10,
    "effect": 6,
    "tools": 7,
    "retry": 10,
    # G5 (loop) adds no SQL: the runtime drives the effect-stage functions.
    "loop": 6,
    "repair": 11,
    "cancel": 12,
    # G11 plugin gate: the offline revocation drain consumes the effect
    # (late completion rejection), retry (aggregation rule closure
    # priority) and cancel (shared pre-dispatch sync caller) stages, so its
    # load set runs through the full order.
    "plugin": 12,
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
