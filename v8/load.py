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
    # G11: the §4 plugin generation domain (plugin_specs/implementations/
    # generations/generation_members, the stable dependency resolution, the
    # generation digest, the publish lifecycle, the shared generation-check
    # sub-operation for the G12 gates and the offline revocation drain).
    # It sits BEFORE the effect stage: steps gain catalog_generation + the
    # implementation binding column with the DEFAULT seed generation here,
    # consumed by the effect and later stages. The file also carries the
    # shared pre-dispatch cancel sync sub-operation: the G10 grant stage
    # hosts its own narrower variant (v_predispatch_cancel_sync, consumed
    # by the WORKSPACE_LOST drain); THIS file's v_pre_dispatch_cancel_sync
    # (the verbatim extraction from v_request_cancel + the authoritative
    # counter recompute + the generation scoping) is the one the cancel
    # path and the generation drain call. The single-implementation
    # unification lands with G12 (deviation A73); it depends only on the
    # schema family and its body resolves late, so the position carries no
    # call-order risk.
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
    # G15: the failure-drain stage's SQL — the §3.1.1 fail_session class (3)
    # INFRA closure entry. It sits AFTER the cancel stage and BEFORE compat.
    # The shared deterministic drain core and the class (3) closure used by
    # the completion path live in grant/v8_grant.sql (position 3): the
    # effect stage (position 7) must be able to take the same-transaction
    # INFRA closure on a DECISION_PLAN_INVALID rejection, and an effect-stage
    # database does not include this file. Bodies are late-bound, so the
    # drain file may reference anything loaded before it either way.
    V8_ROOT / "drain" / "v8_drain.sql",
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
    # G10 gate covers the append consumer (events stage) on top of its own
    # SQL, so its load set runs through events.
    "grant": 5,
    "events": 5,
    # G9a: the stream gate exercises the consumers of the new foundation —
    # the public append path (events stage) for the chunk six-item
    # attribution, v_complete_effect (effect stage) for the stream_complete
    # field matrix, and the known_failure settlement (retry stage) for the
    # non-known_success exemption negative vector — so its load set runs
    # through retry. The stream SQL itself sits at position 4 (after
    # grant, before events). Semantic note (merge reconciliation): the
    # pre-G10 count covered takeover; grant+plugin shifted the indices.
    # G12 correction: G9b (test_observation.py) calls v_recovery_takeover
    # for its takeover-settled observation vectors, so the stream stage
    # load set runs through takeover (11) — the merge-time assumption
    # "test_stream has no takeover dependency" held for test_stream.py
    # only, not for test_observation.py sharing the same stage database.
    "stream": 11,
    "effect": 7,
    "tools": 8,
    "retry": 11,
    # G5 (loop) adds no SQL: the runtime drives the effect-stage functions.
    "loop": 7,
    "repair": 12,
    "cancel": 13,
    # G11 plugin gate: the offline revocation drain consumes the effect
    # (late completion rejection), retry (aggregation rule closure
    # priority) and cancel (shared pre-dispatch sync caller) stages, so its
    # load set runs through the full pre-compat order (cancel last).
    "plugin": 13,
    # G13: compat loads the full pre-compat order plus its own file (the
    # G15 drain insertion shifted it from 14 to 15).
    "compat": 15,
    # G15 (drain) adds the class (3) INFRA closure; its load set runs through
    # its own file (the insertion point is after cancel), so every consumer
    # it exercises — the shared pre-dispatch sync, the aggregation counters
    # and the retry-stop-reason CAS — is loaded.
    "drain": 14,
    # G12 (gates) adds NO SQL of its own — it modifies the existing
    # effect/tools/retry/takeover files in place — but its gate exercises
    # the full pre-compat order (seal/dispatch/cohort/takeover/append).
    "gates": 13,
    # G14 (concurrency) also adds NO SQL: it reuses the frozen gates load
    # set and exercises the lock-wait interleavings of the delivered
    # gates, so it carries the same position as `gates`.
    "concurrency": 13,
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
