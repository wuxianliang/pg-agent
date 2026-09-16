"""v8/grant/fixtures.py — shared grant-seeded test fixtures (G10).

Extracted from v8/stream/test_stream.py during the G10 test_grant_stub
migration so that G12 (and any later gate) can reuse the grant-seeded
chunk fixture and the slice/grant seeders against any stage database that
loads through the grant stage.

Capability API boundary (Conformance 13, database half): these helpers are
the ONLY shape in which test code touches grant rows directly — the raw
database connection never leaves the capability surface in production
code (see client.py), and credential-bearing payloads never enter
session_events (asserted by the G10 gate).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import psycopg2

from v8.events.client import build_entry

SV, CV = "sv@1", "canon@1"


def u() -> str:
    return str(uuid.uuid4())


def _now(offset_seconds: int = 0):
    return datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)


def fresh_session(conn, driver: str = "drv", workspace_id: str | None = None) -> str:
    s = u()
    # Calls the SQL bootstrap directly (the SQL function gained the optional
    # workspace leg in G10; the shared Python client wrapper is untouched).
    with conn.cursor() as cur:
        cur.execute("SELECT v_create_session(%s::uuid, %s, %s::uuid)",
                    (s, driver, workspace_id))
    conn.commit()
    return s


def expect_error(conn, label: str, fn, check_fn=None) -> None:
    """Run fn; a database error is the expected (negative) outcome."""
    try:
        fn()
    except psycopg2.Error as exc:  # noqa: PERF203
        conn.rollback()
        if check_fn is not None:
            check_fn(label, str(exc))
        return
    conn.rollback()
    raise AssertionError(f"{label}: expected a database rejection, none was raised")


# ---------------------------------------------------------------------------
# a grant-bindable chunk effect (mirrors the events stage fixture)
# ---------------------------------------------------------------------------

def chunk_fixture(conn, *, session_id: str | None = None, dispatched: bool = True,
                  grant_id: str | None = None, driver: str = "drv"):
    s = session_id or fresh_session(conn, driver)
    with conn.cursor() as cur:
        turn, step, batch, effect = u(), u(), u(), u()
        cur.execute(
            "INSERT INTO steps(step_id, session_id, turn_id, status, stage)"
            " VALUES (%s, %s, %s, 'waiting_effect', 'decision')", (step, s, turn))
        cur.execute(
            "INSERT INTO batches(batch_id, session_id, step_id, sealed_batch_no,"
            " kind, sealed) VALUES (%s, %s, %s, 1, 'decision', true)",
            (batch, s, step))
        cur.execute(
            "INSERT INTO effect_requests(effect_id, session_id, step_id, batch_id,"
            " dispatch_ordinal, effect_kind, execution_mode, driver, driver_epoch,"
            " session_fence, dispatch_session_fence, current_job_fence,"
            " request_hash, idempotency_key, status, retry_class, max_attempts,"
            " dispatched_at, grant_id)"
            " VALUES (%s, %s, %s, %s, 0, 'llm_decision', 'streaming', %s, 1,"
            " 1, 1, 1, 'rh', 'ik', %s, 'unsafe', 1, %s, %s)",
            (effect, s, step, batch, driver,
             "dispatch_started" if dispatched else "ready",
             _now(0) if dispatched else None, grant_id))
        cur.execute(
            "INSERT INTO effect_attempts(effect_id, attempt_no, session_id,"
            " step_id, dispatch_job_fence, driver, driver_epoch, session_fence,"
            " dispatch_session_fence, request_hash, idempotency_key,"
            " execution_mode, status)"
            " VALUES (%s, 1, %s, %s, 1, %s, 1, 1, 1, 'rh', 'ik',"
            " 'streaming', %s)",
            (effect, s, step, driver, "dispatch_started" if dispatched else "ready"))
    conn.commit()
    return s, turn, step, effect


def chunk_entry(effect: str, text: str, index, attempt: int = 1,
                stream: str = "s1") -> dict:
    return build_entry("assistant/chunk", {"text": text}, schema_version=SV,
                       canonicalizer_version=CV, effect_id=effect,
                       attempt_no=attempt, stream_id=stream, chunk_index=index)


def append_chunks(conn, session_id, command_id, entries, *, expected_seq,
                  caller_subject=None, caller_driver=None, caller_epoch=None,
                  caller_grant_id=None, driver="drv", driver_epoch=1) -> dict:
    """Direct v_command_gate + v_append_events call carrying the caller
    identity legs (the shared client predates them)."""
    from v8.events.client import build_request
    session_id = str(session_id)
    canonical_text, computed = build_request(
        "append_events", session_id, command_id, driver, driver_epoch,
        expected_seq, entries)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT outcome, code, receipt_json, executable"
            " FROM v_command_gate(%s::uuid, %s, %s, %s, %s)",
            (session_id, command_id, "append_events", canonical_text, computed))
        _g_out, _g_code, _g_rec, executable = cur.fetchone()
        if not executable:
            conn.rollback()
            raise AssertionError("gate not executable")
        cur.execute(
            "SELECT outcome, code, receipt_json FROM v_append_events("
            "%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (session_id, command_id, driver, driver_epoch, expected_seq, computed,
             canonical_text, json.dumps(entries, ensure_ascii=False,
                                        separators=(",", ":")),
             caller_subject, caller_driver, caller_epoch, caller_grant_id))
        outcome, code, receipt = cur.fetchone()
    conn.commit()
    return {"outcome": outcome, "code": code, "receipt": receipt}


def seed_slice(conn, ws, name, *, kind="corpus", spec=None, slice_id=None,
               revoked=False) -> str:
    sid = slice_id or u()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO slices(slice_id, workspace_id, name, kind, spec, revoked_at)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (sid, ws, name, kind, json.dumps(spec or {}),
             _now(0) if revoked else None))
    conn.commit()
    return sid


def seed_grant(conn, grant_id, ws, slice_id, subject_kind, subject_id,
               capability, *, not_before=None, expires_at=None, revoked=False,
               constraints=None, delegable=False) -> str:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO grants(grant_id, workspace_id, slice_id, subject_kind,"
            " subject_id, capability, constraints, not_before, expires_at,"
            " revoked_at, delegable)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s,"
            " COALESCE(%s, now()), COALESCE(%s, now() + interval '1 hour'), %s,"
            " %s)",
            (grant_id, ws, slice_id, subject_kind, subject_id, capability,
             json.dumps(constraints) if constraints is not None else None,
             not_before, expires_at, _now(0) if revoked else None, delegable))
    conn.commit()
    return grant_id


# ---------------------------------------------------------------------------
# G12 stage seeding: with the seal/dispatch/cohort gates live, every
# positive-path test session needs valid authorize_effect + effect_submit
# grants (seal member creation + dispatch revalidation) and the append-side
# capabilities for chunk tests. Sessions in the legacy tests carry
# workspace_id NULL, which skips the tenant conjunct on both sides, so one
# permissive slice covers the stage; subject matching goes through the
# session's driver (subject_kind='driver').
# ---------------------------------------------------------------------------

STAGE_CAPABILITIES = (
    "authorize_effect",
    "effect_submit",
    "event_append",
    "stream_ingest",
)

STAGE_WORKSPACE = "00000012-0012-4012-8012-000000000012"


def seed_stage_grants(conn, *, ws=STAGE_WORKSPACE, drivers=("drv",),
                      capabilities=STAGE_CAPABILITIES,
                      slice_id=None) -> str:
    """Seed one permissive slice + one grant per (driver, capability).

    The slice spec carries NO 'resources' key, so slice-membership passes
    for any target; the grants carry no constraints. Gates that need
    negative vectors seed their own constrained rows in the test body.
    """
    sid = seed_slice(conn, ws, f"stage-slice-{drivers[0]}-{u()[:8]}",
                     kind="tool_set", spec={}, slice_id=slice_id)
    for drv in drivers:
        for cap in capabilities:
            seed_grant(conn, f"g-stage-{drv}-{cap}", ws, sid,
                       "driver", drv, cap)
    return sid


# ---------------------------------------------------------------------------
# G12 chunk-fixture migration helper: with the A57 legacy downgrade removed,
# an accepted chunk append needs the full (3)/(6) conjunction — bind the
# fixture effect to a provider identity (grant_id -> the provider's
# event_append grant) and seed the dual grants (event_append +
# stream_ingest). The caller identity then resolves through the default
# legs (v_caller := the effect's bound subject), so existing call sites
# that pass no caller legs keep working.
# ---------------------------------------------------------------------------

CHUNK_PROVIDER = "provider-1"


def bind_chunk_provider(conn, session_id, effect, *,
                        provider=CHUNK_PROVIDER, ws=STAGE_WORKSPACE) -> str:
    """Seed the provider's dual grants and bind the chunk effect to them.

    Returns the bound grant_id. Slice-membership is permissive (no
    'resources' key), matching the stage seed shape.
    """
    sid = seed_slice(conn, ws, f"chunk-slice-{session_id}", kind="tool_set",
                     spec={})
    g_ea = seed_grant(conn, f"g-chunk-{session_id}-ea", ws, sid,
                      "plugin_identity", provider, "event_append")
    seed_grant(conn, f"g-chunk-{session_id}-si", ws, sid,
               "plugin_identity", provider, "stream_ingest")
    with conn.cursor() as cur:
        cur.execute("UPDATE effect_requests SET grant_id=%s"
                    " WHERE effect_id=%s", (g_ea, effect))
    conn.commit()
    return g_ea


__all__ = [
    "SV", "CV", "u", "_now", "fresh_session", "expect_error",
    "chunk_fixture", "chunk_entry", "append_chunks",
    "seed_slice", "seed_grant", "seed_stage_grants", "STAGE_CAPABILITIES",
    "STAGE_WORKSPACE", "CHUNK_PROVIDER", "bind_chunk_provider",
]
