"""G9a gate: v8 stream foundation — session_events stream columns, the
minimal slice/grant stub, the assistant/chunk six-item attribution
completion (items (2)/(3)/(6)), and the stream_complete field matrix.

Run: uv run python v8/stream/test_stream.py  (exit 0 = pass)
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
from v8.canonical.keys import event_key_v1
from v8.effect.client import (
    claim_session,
    complete_effect,
    dispatch_effect,
    build_result_payload,
    prepare_step,
)
from v8.canonical.canonical import CanonicalizationError
from v8.events.client import (
    build_entry,
    canonical_payload,
    create_session,
)
from v8.stream.setup_db import DB, main as setup_db

SV, CV = "sv@1", "canon@1"
U64MAX = 9223372036854775807        # 2^63 - 1
N_MAX = 9223372036854775806         # 2^63 - 2
SAFE_MAX = 9007199254740991         # 2^53 - 1


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f": {detail}" if detail else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def u() -> str:
    return str(uuid.uuid4())


def _now(offset_seconds: int = 0):
    from datetime import datetime, timedelta, timezone
    return datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)


def _uri() -> str:
    return get_server().get_uri(DB)


def tagged(n: int) -> dict:
    """Wire form for integers beyond the 2^53-1 safe range (canonical profile)."""
    return {"$int": str(n)}


def fresh_session(conn, driver: str = "drv") -> str:
    s = u()
    create_session(conn, s, driver)
    return s


def expect_error(conn, label: str, fn) -> None:
    """Run fn; a database error is the expected (negative) outcome."""
    try:
        fn()
    except psycopg2.Error as exc:  # noqa: PERF203
        conn.rollback()
        check(label, True, type(exc).__name__)
        return
    conn.rollback()
    check(label, False, "expected a database rejection, none was raised")


# ---------------------------------------------------------------------------
# fixture: a grant-bindable chunk effect (mirrors the events stage fixture)
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
    """Direct v_command_gate + v_append_events call carrying the G9a caller
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
               constraints=None) -> str:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO grants(grant_id, workspace_id, slice_id, subject_kind,"
            " subject_id, capability, constraints, not_before, expires_at, revoked_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s,"
            " COALESCE(%s, now()), COALESCE(%s, now() + interval '1 hour'), %s)",
            (grant_id, ws, slice_id, subject_kind, subject_id, capability,
             json.dumps(constraints) if constraints is not None else None,
             not_before, expires_at, _now(0) if revoked else None))
    conn.commit()
    return grant_id


# ---------------------------------------------------------------------------
# 1. session_events stream columns (scope item 1)
# ---------------------------------------------------------------------------

def raw_event(conn, sid, seq, etype, eclass, **kw):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO session_events(seq, session_id, event_type, event_class,"
            " schema_version, canonicalizer_version, event_key, turn_id, payload,"
            " payload_hash, semantic_input_ordinal, stream_id, chunk_index,"
            " observation_ordinal)"
            " VALUES (%s, %s, %s, %s, 'sv@1', 'canon@1', %s, %s, %s, 'h', %s,"
            " %s, %s, %s)",
            (seq, sid, etype, eclass, kw.get("key", u()), kw.get("turn"),
             kw.get("payload", "{}"), kw.get("sio"), kw.get("stream_id"),
             kw.get("chunk_index"), kw.get("observation_ordinal")))


def test_session_event_columns(conn) -> None:
    s = fresh_session(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM session_events WHERE session_id=%s", (s,))
        check("fresh session has no events", cur.fetchone()[0] == 0)

    # Negative: an assistant/chunk row missing the stream columns.
    expect_error(conn, "chunk row without stream_id/chunk_index -> CHECK",
                 lambda: raw_event(conn, s, 1, "assistant/chunk", "observational"))
    # Negative: a non-chunk row carrying the stream columns.
    expect_error(conn, "semantic row carrying stream_id -> CHECK",
                 lambda: raw_event(conn, s, 1, "user/message", "semantic",
                                   sio=1, stream_id="s1"))
    # Negative: chunk_index out of domain (negative).
    expect_error(conn, "chunk row with negative chunk_index -> CHECK",
                 lambda: raw_event(conn, s, 1, "assistant/chunk", "observational",
                                   stream_id="s1", chunk_index=-1))
    # Negative: chunk row with a NULL chunk_index.
    expect_error(conn, "chunk row with NULL chunk_index -> CHECK",
                 lambda: raw_event(conn, s, 1, "assistant/chunk", "observational",
                                   stream_id="s1"))

    # Positive: a well-formed chunk row in domain.
    raw_event(conn, s, 1, "assistant/chunk", "observational",
              stream_id="s1", chunk_index=0)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SELECT stream_id, chunk_index FROM session_events"
                    " WHERE session_id=%s AND seq=1", (s,))
        check("well-formed chunk row stores the four-tuple stream columns",
              cur.fetchone() == ("s1", 0))

    # observation_ordinal: misuse on a non-repeatable / non-observational row.
    expect_error(conn, "observation_ordinal on a semantic row -> CHECK",
                 lambda: raw_event(conn, s, 2, "user/message", "semantic",
                                   sio=2, observation_ordinal=1))
    expect_error(conn, "observation_ordinal on session/heartbeat -> CHECK",
                 lambda: raw_event(conn, s, 2, "session/heartbeat",
                                   "observational", observation_ordinal=1))
    expect_error(conn, "observation_ordinal = 0 -> CHECK",
                 lambda: raw_event(conn, s, 2, "stream_progress",
                                   "observational", observation_ordinal=0))
    # Positive: a repeatable observation row with ordinal >= 1.
    raw_event(conn, s, 2, "stream_progress", "observational", observation_ordinal=1)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SELECT observation_ordinal FROM session_events"
                    " WHERE session_id=%s AND seq=2", (s,))
        check("repeatable observation row carries its ordinal",
              cur.fetchone()[0] == 1)


# ---------------------------------------------------------------------------
# 2. minimal grant stub (scope item 2)
# ---------------------------------------------------------------------------

def test_grant_stub(conn) -> None:
    ws = u()
    sl = seed_slice(conn, ws, "corpus-a", kind="corpus",
                    spec={"paths": ["/data/x"]})

    # slices UNIQUE(workspace_id, name).
    expect_error(conn, "duplicate slice name in a workspace -> UNIQUE",
                 lambda: seed_slice(conn, ws, "corpus-a"))
    # slices kind closed set.
    expect_error(conn, "slice kind outside the closed set -> CHECK",
                 lambda: seed_slice(conn, ws, "corpus-b", kind="nonsense"))
    # slices spec immutability.
    expect_error(conn, "slice spec UPDATE -> rejected",
                 lambda: _update(conn, "UPDATE slices SET spec='{}' WHERE slice_id=%s",
                                 (sl,)))
    # slices revoked_at monotonic.
    seed_slice(conn, ws, "corpus-rev", slice_id=u(), revoked=True)
    expect_error(conn, "slice revoked_at cannot be cleared",
                 lambda: _update(
                     conn, "UPDATE slices SET revoked_at=NULL WHERE name='corpus-rev'"))

    # grants closed sets.
    expect_error(conn, "grant subject_kind outside the closed set -> CHECK",
                 lambda: seed_grant(conn, u(), ws, sl, "team", "t1", "recall"))
    expect_error(conn, "grant capability outside the 13-value set -> CHECK",
                 lambda: seed_grant(conn, u(), ws, sl, "session", "x", "root"))
    # grants tenant consistency (composite FK): a workspace_id that does not
    # match the slice's.
    expect_error(conn, "grant workspace != slice workspace -> composite FK",
                 lambda: seed_grant(conn, u(), u(), sl, "session", "x", "recall"))
    # grants constraints immutability.
    g_imm = seed_grant(conn, "gr-imm", ws, sl, "session", "x", "recall",
                       constraints={"max_rows": 1})
    expect_error(conn, "grant constraints UPDATE -> rejected",
                 lambda: _update(
                     conn, "UPDATE grants SET constraints='{\"max_rows\":9}'"
                           " WHERE grant_id='gr-imm'"))

    # ---- v_grant_valid full conjunction (session-bound subject) ----
    s = fresh_session(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT driver FROM sessions WHERE session_id=%s", (s,))
        drv = cur.fetchone()[0]
    base = dict(subject_kind="session", subject_id=s, capability="event_append")

    g_ok = seed_grant(conn, "g-ok", ws, sl, **base)
    _valid(conn, "valid grant -> true", s, g_ok, "event_append", True)
    _valid(conn, "wrong capability -> false", s, g_ok, "stream_ingest", False)

    g_rev = seed_grant(conn, "g-rev", ws, sl, **base, revoked=True)
    _valid(conn, "grant revoked -> false", s, g_rev, "event_append", False)

    g_future = seed_grant(conn, "g-fut", ws, sl, **base,
                          not_before=_now(3600), expires_at=_now(7200))
    _valid(conn, "not_before in the future -> false", s, g_future,
           "event_append", False)

    g_exp = seed_grant(conn, "g-exp", ws, sl, **base,
                       not_before=_now(-7200), expires_at=_now(-3600))
    _valid(conn, "expires_at in the past -> false", s, g_exp, "event_append", False)

    g_other = seed_grant(conn, "g-oth", ws, sl, "session", u(), "event_append")
    _valid(conn, "subject mismatch -> false", s, g_other, "event_append", False)

    # slice revocation propagation: slice revoked, grant NOT revoked -> invalid.
    sl_rev = seed_slice(conn, ws, "corpus-rev2", revoked=True)
    g_prop = seed_grant(conn, "g-prop", ws, sl_rev, **base)
    _valid(conn, "slice revoked propagates (grant itself unrevoked) -> false",
           s, g_prop, "event_append", False)

    # driver-bound subject leg.
    g_drv = seed_grant(conn, "g-drv", ws, sl, "driver", drv, "event_append")
    _valid(conn, "driver-bound subject matches the session -> true",
           s, g_drv, "event_append", True)

    # unknown grant id.
    _valid(conn, "unknown grant_id -> false", s, "g-missing", "event_append", False)


def _update(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
    conn.commit()


def _valid(conn, label, session_id, grant_id, capability, expect) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT v_grant_valid(%s::uuid, %s, %s)",
                    (session_id, grant_id, capability))
        got = cur.fetchone()[0]
    conn.rollback()
    check(label, got is expect, got)


# ---------------------------------------------------------------------------
# 3. assistant/chunk six-item attribution (items (2)/(3)/(6))
# ---------------------------------------------------------------------------

def test_chunk_attribution(conn) -> None:
    # (1) unknown effect.
    s = fresh_session(conn)
    r = append_chunks(conn, s, "c-1", [chunk_entry(u(), "x", 0)], expected_seq=1)
    check("chunk unknown effect -> CHUNK_ATTRIBUTION_INVALID",
          r["code"] == "CHUNK_ATTRIBUTION_INVALID", r["code"])

    # (4) not yet dispatched.
    s2, _, _, e2 = chunk_fixture(conn, dispatched=False)
    r = append_chunks(conn, s2, "c-4", [chunk_entry(e2, "x", 0)], expected_seq=1)
    check("chunk before dispatch -> CHUNK_ATTRIBUTION_INVALID",
          r["code"] == "CHUNK_ATTRIBUTION_INVALID", r["code"])

    # (2) attempt that is neither the current max nor an accepted-settled one.
    s3, _, _, e3 = chunk_fixture(conn)
    r = append_chunks(conn, s3, "c-2", [chunk_entry(e3, "x", 0, attempt=2)],
                      expected_seq=1)
    check("chunk wrong attempt_no -> CHUNK_ATTRIBUTION_INVALID",
          r["code"] == "CHUNK_ATTRIBUTION_INVALID", r["code"])

    # (5) chunk_index domain: negative.
    s5, _, _, e5 = chunk_fixture(conn)
    r = append_chunks(conn, s5, "c-5", [chunk_entry(e5, "x", -1)], expected_seq=1)
    check("chunk negative chunk_index -> CHUNK_ATTRIBUTION_INVALID",
          r["code"] == "CHUNK_ATTRIBUTION_INVALID", r["code"])

    # Value-domain boundary four points on the unbounded (legacy) path.
    sb, _, _, eb = chunk_fixture(conn)
    rb = append_chunks(conn, sb, "c-b1",
                       [chunk_entry(eb, "a", SAFE_MAX)], expected_seq=1)
    check("chunk_index 2^53-1 (number) accepted", rb["outcome"] == "accepted", rb)
    rb2 = append_chunks(conn, sb, "c-b2",
                        [chunk_entry(eb, "b", U64MAX)], expected_seq=2)
    check("chunk_index 2^63-1 (tagged $int) accepted", rb2["outcome"] == "accepted",
          rb2)
    # 2^53 bare number is rejected by the canonical schema pre-check; the
    # tagged form is accepted (client tags it).
    try:
        canonical_payload({"text": "x", "chunk_index": 2 ** 53})
        check("bare 2^53 number rejected by canonical schema", False, "no error")
    except CanonicalizationError as exc:
        check("bare 2^53 number rejected by canonical schema",
              exc.code == "UNSAFE_NUMBER", exc.code)
    rb3 = append_chunks(conn, sb, "c-b3",
                        [chunk_entry(eb, "c", 2 ** 53)], expected_seq=3)
    check("chunk_index 2^53 tagged form accepted", rb3["outcome"] == "accepted", rb3)
    rb4 = append_chunks(conn, sb, "c-b4",
                        [chunk_entry(eb, "d", U64MAX + 1)], expected_seq=4)
    check("chunk_index 2^63 -> CHUNK_ATTRIBUTION_INVALID",
          rb4["code"] == "CHUNK_ATTRIBUTION_INVALID", rb4["code"])

    # Out-of-order with a gap (2,0,1) accepted.
    so, _, _, eo = chunk_fixture(conn)
    r1 = append_chunks(conn, so, "c-o1", [chunk_entry(eo, "A", 2)], expected_seq=1)
    r2 = append_chunks(conn, so, "c-o2", [chunk_entry(eo, "B", 0)], expected_seq=2)
    r3 = append_chunks(conn, so, "c-o3", [chunk_entry(eo, "C", 1)], expected_seq=3)
    check("out-of-order chunk with a gap accepted",
          r1["outcome"] == r2["outcome"] == r3["outcome"] == "accepted",
          (r1["outcome"], r2["outcome"], r3["outcome"]))

    # Four-tuple derivation dedup (SQL == Python key; idempotent; conflict).
    with conn.cursor() as cur:
        cur.execute("SELECT event_key, seq, payload FROM session_events"
                    " WHERE session_id=%s AND stream_id='s1' AND chunk_index=2",
                    (so,))
        ek, seq, payload = cur.fetchone()
    py_key = event_key_v1(eo, 1, "s1", 2)
    check("stored streaming event_key == keys.event_key_v1 (byte parity)",
          ek == py_key, (ek, py_key))
    rr = append_chunks(conn, so, "c-o4", [chunk_entry(eo, "A", 2)], expected_seq=4)
    check("same four-tuple same content -> idempotent",
          rr["outcome"] == "accepted" and rr["receipt"]["inserted"] is None, rr)
    rc = append_chunks(conn, so, "c-o5", [chunk_entry(eo, "DIFF", 2)], expected_seq=4)
    check("same four-tuple different content -> CANONICALIZER_CONFLICT",
          rc["code"] == "CANONICALIZER_CONFLICT", rc["code"])

    # ---- (3)/(6): grant-chain caller attribution ----
    ws = u()
    sl = seed_slice(conn, ws, "chunk-corpus")
    sc = fresh_session(conn)
    # effect bound to a provider grant whose subject is the session itself.
    g_eff = seed_grant(conn, "g-eff", ws, sl, "session", sc, "event_append")
    seed_grant(conn, "g-si", ws, sl, "session", sc, "stream_ingest")
    sA, _, _, eA = chunk_fixture(conn, session_id=sc, grant_id=g_eff)
    r_ok = append_chunks(conn, sA, "cA-ok", [chunk_entry(eA, "ok", 0)],
                         expected_seq=1, caller_subject=sc)
    check("grant-bound chunk with both grants + identity match accepted",
          r_ok["outcome"] == "accepted", r_ok)

    # (3) foreign stream owner: another effect bound to a different provider
    # (in a different session) tries to reuse stream 's1' already owned by eA.
    g_other = seed_grant(conn, "g-prov2", ws, sl, "plugin_identity", "provider-2",
                         "event_append")
    sB, _, _, eB = chunk_fixture(conn, grant_id=g_other)
    r_foreign = append_chunks(conn, sB, "cB-foreign",
                              [chunk_entry(eB, "x", 0, stream="s1")],
                              expected_seq=1, caller_subject="provider-2")
    check("chunk on a foreign provider's stream -> CHUNK_ATTRIBUTION_INVALID",
          r_foreign["code"] == "CHUNK_ATTRIBUTION_INVALID", r_foreign["code"])

    # (6)(i) missing event_append grant (only stream_ingest held).
    ws2 = u()
    sl2 = seed_slice(conn, ws2, "si-only")
    sD = fresh_session(conn)
    g_d_eff = seed_grant(conn, "g-deff", ws2, sl2, "session", sD, "stream_ingest")
    seed_grant(conn, "g-dsi", ws2, sl2, "session", sD, "stream_ingest")
    sD2, _, _, eD = chunk_fixture(conn, session_id=sD, grant_id=g_d_eff)
    r_no_ea = append_chunks(conn, sD2, "cD-noea", [chunk_entry(eD, "x", 0)],
                            expected_seq=1, caller_subject=sD)
    check("no event_append grant -> CHUNK_ATTRIBUTION_INVALID",
          r_no_ea["code"] == "CHUNK_ATTRIBUTION_INVALID", r_no_ea["code"])

    # (6)(ii) dual-grant contrast: holds stream_ingest (passed as the caller
    # grant) but no event_append -> still rejected.
    ws3 = u()
    sl3 = seed_slice(conn, ws3, "si-only-2")
    sE = fresh_session(conn)
    seed_grant(conn, "g-eeff", ws3, sl3, "session", sE, "stream_ingest")
    g_e_si = seed_grant(conn, "g-esi", ws3, sl3, "session", sE, "stream_ingest")
    sE2, _, _, eE = chunk_fixture(conn, session_id=sE, grant_id="g-eeff")
    r_si_only = append_chunks(conn, sE2, "cE-si", [chunk_entry(eE, "x", 0)],
                              expected_seq=1, caller_grant_id=g_e_si)
    check("holds stream_ingest but not event_append -> CHUNK_ATTRIBUTION_INVALID",
          r_si_only["code"] == "CHUNK_ATTRIBUTION_INVALID", r_si_only["code"])

    # (6)(iii) non-owner caller: both capabilities exist for a FOREIGN subject,
    # and the caller declares that foreign subject -> identity mismatch.
    ws4 = u()
    sl4 = seed_slice(conn, ws4, "idm")
    sF = fresh_session(conn)
    foreign_subj = f"prov-{u()[:8]}"
    seed_grant(conn, "g-fea", ws4, sl4, "session", foreign_subj, "event_append")
    seed_grant(conn, "g-fsi", ws4, sl4, "session", foreign_subj, "stream_ingest")
    g_f_eff = seed_grant(conn, "g-feff", ws4, sl4, "session", sF, "event_append")
    seed_grant(conn, "g-feff2", ws4, sl4, "session", sF, "stream_ingest")
    sF2, _, _, eF = chunk_fixture(conn, session_id=sF, grant_id=g_f_eff)
    r_nonowner = append_chunks(conn, sF2, "cF-nonowner", [chunk_entry(eF, "x", 0)],
                               expected_seq=1, caller_subject=foreign_subj)
    check("non-owner caller (identity mismatch) -> CHUNK_ATTRIBUTION_INVALID",
          r_nonowner["code"] == "CHUNK_ATTRIBUTION_INVALID", r_nonowner["code"])


# ---------------------------------------------------------------------------
# 4. stream_complete field matrix + count ABI (scope item 4)
# ---------------------------------------------------------------------------

def stream_fixture(conn, *, max_attempts: int = 1,
                   retry_class: str = "unsafe", driver: str = "drv"):
    """create -> claim -> seal(streaming) -> dispatch. Returns a context dict."""
    s = fresh_session(conn, driver)
    turn, step, effect = u(), u(), u()
    rh, ik = f"rh-{u()[:8]}", f"ik-{u()[:8]}"
    r0 = claim_session(conn, s, driver)
    dispatch_fence = r0["session_fence"]
    rs = prepare_step(conn, s, f"seal-{u()[:8]}", driver, 1,
                      r0["session_fence"], step, turn, effect,
                      execution_mode="streaming", retry_class=retry_class,
                      max_attempts=max_attempts, request_hash=rh,
                      idempotency_key=ik)
    if rs["outcome"] != "accepted":
        raise AssertionError(f"stream seal failed: {rs}")
    rd = dispatch_effect(conn, s, f"dsp-{u()[:8]}", effect, driver, 1,
                         rs["receipt"]["session_fence"], rs["receipt"]["job_fence"])
    if rd["outcome"] != "accepted":
        raise AssertionError(f"stream dispatch failed: {rd}")
    return {"s": s, "step": step, "effect": effect, "dispatch_fence": dispatch_fence,
            "job_fence": rs["receipt"]["job_fence"], "rh": rh, "ik": ik,
            "driver": driver}


def stream_complete(conn, fx, result_extra, *, outcome="succeeded",
                    evidence=None, message=None, decision_only=True,
                    final_tools=False, tools=None) -> dict:
    message = {"text": "final"} if message is None else message
    payload = build_result_payload(message, tools or [], decision_only, final_tools)
    if result_extra is not None:
        payload.update(result_extra)
    return complete_effect(
        conn, fx["s"], f"cmp-{u()[:8]}", fx["effect"], fx["driver"], 1,
        dispatch_session_fence=fx["dispatch_fence"], job_fence=fx["job_fence"],
        step_id=fx["step"], request_hash=fx["rh"], idempotency_key=fx["ik"],
        outcome=outcome, message=message, tools=tools or [],
        decision_only=decision_only, final_tools=final_tools,
        evidence=evidence or {"class": "known_success",
                              "provider_receipt": {"receipt_id": f"pr-{u()[:8]}"}},
        result_payload=payload)


def test_field_matrix(conn) -> None:
    # (0)(i) stream_complete=true with a single count -> complete flow.
    fx = stream_fixture(conn)
    r = stream_complete(conn, fx, {"stream_complete": True, "final_chunk_index": 2})
    check("(0)(i) true + final_chunk_index -> accepted known_success",
          r["outcome"] == "accepted"
          and r["receipt"]["classification"] == "known_success", r)
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM effect_requests WHERE effect_id=%s",
                    (fx["effect"],))
        check("(0)(i) effect settled succeeded", cur.fetchone()[0] == "succeeded")

    # (0)(i) coexistence C = N+1 accepted.
    fx2 = stream_fixture(conn)
    r = stream_complete(conn, fx2,
                        {"stream_complete": True, "final_chunk_index": 1,
                         "chunk_count": 2})
    check("(0)(i) N=1 / C=2 coexistence accepted", r["outcome"] == "accepted", r)

    # (0)(i) only chunk_count.
    fx3 = stream_fixture(conn)
    r = stream_complete(conn, fx3, {"stream_complete": True, "chunk_count": 3})
    check("(0)(i) chunk_count only accepted", r["outcome"] == "accepted", r)

    # (0)(ii) stream_complete missing -> schema reject (with and without counts).
    fx4 = stream_fixture(conn)
    r = stream_complete(conn, fx4, {})
    check("(0)(ii) missing stream_complete -> RESULT_PAYLOAD_INVALID",
          r["outcome"] == "rejected_mismatch"
          and r["code"] == "RESULT_PAYLOAD_INVALID", (r["outcome"], r["code"]))
    fx5 = stream_fixture(conn)
    r = stream_complete(conn, fx5, {"final_chunk_index": 0})
    check("(0)(ii) missing stream_complete with a count -> schema reject",
          r["code"] == "RESULT_PAYLOAD_INVALID", r["code"])
    fx5b = stream_fixture(conn)
    r = stream_complete(conn, fx5b, {"stream_complete": None, "chunk_count": 1})
    check("(0)(ii) explicit null stream_complete -> schema reject",
          r["code"] == "RESULT_PAYLOAD_INVALID", r["code"])

    # (0)(v) stream_complete=true with no count -> schema reject.
    fx6 = stream_fixture(conn)
    r = stream_complete(conn, fx6, {"stream_complete": True})
    check("(0)(v) true without a count -> RESULT_PAYLOAD_INVALID",
          r["code"] == "RESULT_PAYLOAD_INVALID", r["code"])

    # (0)(iii)/(iv) stream_complete=false -> pending observation.
    for extra, label in (
        ({"stream_complete": False, "final_chunk_index": 1}, "(0)(iii) false+count"),
        ({"stream_complete": False}, "(0)(iv) false, no count"),
    ):
        fx7 = stream_fixture(conn)
        r = stream_complete(conn, fx7, extra)
        with conn.cursor() as cur:
            cur.execute("SELECT status, result_hash FROM effect_requests"
                        " WHERE effect_id=%s", (fx7["effect"],))
            eff = cur.fetchone()
            cur.execute("SELECT count(*), max(observation_ordinal)"
                        " FROM session_events WHERE session_id=%s"
                        " AND event_type='stream_progress'", (fx7["s"],))
            obs = cur.fetchone()
        check(f"{label} -> pending observation, zero control-state change",
              r["outcome"] == "accepted" and r["receipt"]["kind"] == "stream_pending"
              and eff == ("dispatch_started", None) and obs[0] == 1
              and obs[1] == 1, (r, eff, obs))

    # Count-domain rejects.
    for extra, label in (
        ({"stream_complete": True, "final_chunk_index": -1},
         "negative final_chunk_index"),
        ({"stream_complete": True, "chunk_count": -1}, "negative chunk_count"),
        ({"stream_complete": True, "final_chunk_index": tagged(N_MAX + 1)},
         "final_chunk_index 2^63-1 (over the 2^63-2 bound)"),
        ({"stream_complete": True, "chunk_count": tagged(U64MAX + 1)},
         "chunk_count 2^63"),
        ({"stream_complete": True, "final_chunk_index": 1, "chunk_count": 5},
         "coexistence C != N+1"),
        ({"stream_complete": True, "chunk_count": 0}, "chunk_count zero"),
        ({"stream_complete": True, "final_chunk_index": 1.5},
         "non-integer final_chunk_index"),
    ):
        fx8 = stream_fixture(conn)
        r = stream_complete(conn, fx8, extra)
        check(f"count domain: {label} -> RESULT_PAYLOAD_INVALID",
              r["code"] == "RESULT_PAYLOAD_INVALID", (extra, r["code"]))

    # Count boundary positives: N=2^63-2 with C=2^63-1; C=2^63-1 alone.
    fx9 = stream_fixture(conn)
    r = stream_complete(conn, fx9, {"stream_complete": True,
                                    "final_chunk_index": tagged(N_MAX),
                                    "chunk_count": tagged(U64MAX)})
    check("boundary N=2^63-2 / C=2^63-1 coexist accepted",
          r["outcome"] == "accepted", r)
    fx10 = stream_fixture(conn)
    r = stream_complete(conn, fx10, {"stream_complete": True,
                                     "chunk_count": tagged(U64MAX)})
    check("boundary chunk_count=2^63-1 alone accepted", r["outcome"] == "accepted", r)

    # Applicability: a non-streaming success without stream facts settles.
    s = fresh_session(conn)
    turn, step, effect = u(), u(), u()
    ns_rh, ns_ik = f"rh-{u()[:8]}", f"ik-{u()[:8]}"
    r0 = claim_session(conn, s, "drv")
    rs = prepare_step(conn, s, f"seal-{u()[:8]}", "drv", 1,
                      r0["session_fence"], step, turn, effect,
                      execution_mode="non_streaming", request_hash=ns_rh,
                      idempotency_key=ns_ik)
    rd = dispatch_effect(conn, s, f"dsp-{u()[:8]}", effect, "drv", 1,
                         rs["receipt"]["session_fence"], rs["receipt"]["job_fence"])
    rns = complete_effect(conn, s, f"cmp-{u()[:8]}", effect, "drv", 1,
                          dispatch_session_fence=r0["session_fence"],
                          job_fence=rs["receipt"]["job_fence"], step_id=step,
                          request_hash=ns_rh, idempotency_key=ns_ik,
                          outcome="succeeded", message={"text": "ns"}, tools=[],
                          decision_only=True, final_tools=False,
                          evidence={"class": "known_success",
                                    "provider_receipt": {"receipt_id": "pr"}})
    check("non-streaming success without stream facts -> normal succeeded",
          rns["outcome"] == "accepted"
          and rns["receipt"]["classification"] == "known_success", rns)

    # Applicability: a streaming known_failure missing stream_complete MUST NOT
    # schema reject (F3/W02 exemption).
    fx11 = stream_fixture(conn, retry_class="verifiable_no_effect", max_attempts=3)
    rf = stream_complete(
        conn, fx11, {}, outcome="failed_retryable",
        evidence={"class": "known_failure",
                  "provider_receipt": {"receipt_id": f"fr-{u()[:8]}"},
                  "no_side_effect_proof": {"checked": True}})
    check("streaming known_failure missing stream_complete -> not schema reject",
          rf["outcome"] == "accepted"
          and rf["receipt"]["classification"] == "known_failure",
          (rf["outcome"], rf["code"], rf.get("receipt", {}).get("classification")))

    # Mode perturbation: a streaming effect's result self-reporting
    # non-streaming still gets the matrix; a non-streaming effect's
    # self-report is ignored (already covered above).
    fx12 = stream_fixture(conn)
    r = stream_complete(conn, fx12, {"stream_complete": True,
                                     "mode_self_report": "non_streaming"})
    check("mode self-report never changes matrix applicability",
          r["code"] == "RESULT_PAYLOAD_INVALID", r["code"])


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--no-setup":
        pass
    else:
        setup_db()
    conn = psycopg2.connect(_uri())
    conn.autocommit = False
    try:
        test_session_event_columns(conn)
        test_grant_stub(conn)
        test_chunk_attribution(conn)
        test_field_matrix(conn)
    finally:
        conn.close()
    print("[G9a] all gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
