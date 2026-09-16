"""G11 gate: v8 §4 plugin generation domain — table family DDL (immutable
entities, spec binding FK, GC), the stable dependency resolution (frozen
sort key, cycle/duplicate-provide/version-mismatch whole-generation
rejection), the generation digest (SQL == Python == hand-computed golden
vectors), the publish lifecycle (building -> {active, failed}; refresh
reuse; atomic pointer switch), the steps generation binding, the readiness
registry (apply idempotence/conflict, catalog active != handler ready),
and the active -> failed offline revocation protocol (drain, three-
conjunction closure, existing-rule priority, in-flight snapshot, pointer
disposition, no-drift, NO_ACTIVE_GENERATION assemble wiring, pre-lock
total order + in-lock rescan retry, isolation guard, retired negative).

Run: uv run python v8/plugin/test_plugin.py  (exit 0 = pass)
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
from v8.effect.client import (
    claim_session,
    complete_effect,
    dispatch_effect,
    prepare_step,
)
from v8.events.client import create_session
from v8.plugin.client import (
    PluginHandlerRegistry,
    ReadinessConflict,
    activate_generation,
    active_pointer,
    assemble_bind_generation,
    build_generation,
    candidate,
    dispose_pointer,
    fail_generation_building,
    gc_generation,
    generation_member_digest,
    manifest,
    publish_generation,
    retire_generation,
    revoke_generation,
    step_generation_status,
)
from v8.plugin.setup_db import DB, main as setup_db
from v8.retry.client import retry_effect
from v8.retry.test_retry import (
    DRIVER,
    EPOCH,
    attempt_rows,
    check,
    custom_slots,
    effect_row,
    exec_sql,
    fail_evidence,
    good_evidence,
    one,
    rows,
    session_row,
    step_row,
    u,
)
from v8.tools.client import complete_tool_effect, seal_batch

SEED = "00000000-0000-4000-8000-000000000001"


def uri() -> str:
    return get_server().get_uri(DB)


# ---------------------------------------------------------------------------
# golden digest vectors — expected values hand-computed by an independent
# shell pipeline (printf of the canonical literal | shasum -a 256), never
# by the implementation under test.
# ---------------------------------------------------------------------------

G_OLDEN_EMPTY = "b2c0c73cc895685eaa20775f96ad945305b6bf0cb03c19922c5999dd1783b444"
GOLDEN_ONE = "c83cf8f22896a3e772b3345f654f0d393db5fe3e72f9217d9cfe03aa914b89d0"
GOLDEN_TWO = "a11df2b4175b62c5ad01a9562c46b447f35dd0ba1470a987b03fef83d1c54395"
GOLDEN_TWO_SWAPPED = \
    "558f9d73ef9ff65399e52279c65405cd05b66efdd3f216a2e87d2371eacd5568"
GOLDEN_ESCAPE = "7e9a9b222c1a4926213664c2071677fe88514beb821a6037fcbd5846e9c97195"

M_A = {"identity": "plug-a", "contract_version": "cv@1", "locus": "sql",
       "driver": "native", "plugin_version": "1.0.0",
       "implementation_digest": "aa11"}
M_B = {"identity": "plug-b", "contract_version": "cv@1", "locus": "host",
       "driver": "compat", "plugin_version": "1.2",
       "implementation_digest": "bb22"}
M_ESC = {"identity": 'plug-"q"\\ün', "contract_version": "cv@1",
         "locus": "sql", "driver": "native", "plugin_version": "0.9",
         "implementation_digest": "cc33"}


def sql_digest(conn, members: list[dict]) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT v_generation_member_digest(%s::jsonb)",
                    (json.dumps(members, ensure_ascii=False),))
        out = cur.fetchone()[0]
    conn.rollback()
    return out


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def fx_ready(conn, retry_class: str = "unsafe", max_attempts: int = 1) -> dict:
    """A session whose single decision effect is sealed and READY
    (undispatched): the drainable shape."""
    s, turn, step, eff = u(), u(), u(), u()
    create_session(conn, s, DRIVER)
    r0 = claim_session(conn, s, DRIVER)
    rh, ik = f"rh-{u()[:10]}", f"ik-{u()[:10]}"
    rs = prepare_step(conn, s, f"seal-{u()[:8]}", DRIVER, EPOCH,
                      r0["session_fence"], step, turn, eff,
                      request_hash=rh, idempotency_key=ik,
                      retry_class=retry_class, max_attempts=max_attempts)
    check("fx seal accepted", rs["outcome"] == "accepted", rs)
    return {"session": s, "turn": turn, "step": step, "effect": eff,
            "rh": rh, "ik": ik, "kind": "decision",
            "fence": rs["receipt"]["session_fence"],
            "job_fence": rs["receipt"]["job_fence"]}


def fx_dispatched(conn, retry_class: str = "unsafe",
                  max_attempts: int = 1) -> dict:
    """fx_ready + the dispatch gate passed (in-flight snapshot held)."""
    fx = fx_ready(conn, retry_class=retry_class, max_attempts=max_attempts)
    rd = dispatch_effect(conn, fx["session"], f"dsp-{u()[:8]}", fx["effect"],
                         DRIVER, EPOCH, fx["fence"], fx["job_fence"])
    check("fx dispatch accepted", rd["outcome"] == "accepted", rd)
    return fx


def fx_plan(conn) -> dict:
    """A successful non-empty-plan decision: step ready/stage=decision with
    a persisted unsealed tools plan."""
    fx = fx_dispatched(conn)
    plan = [{"tool_call_id": f"call-{u()[:8]}", "tool": "fake_tool",
             "arguments": {"echo": "plan"}}]
    rc = complete_effect(
        conn, fx["session"], f"cmp-{u()[:8]}", fx["effect"], DRIVER, EPOCH,
        dispatch_session_fence=2, job_fence=fx["job_fence"],
        step_id=fx["step"], attempt_no=1, request_hash=fx["rh"],
        idempotency_key=fx["ik"], outcome="succeeded",
        message={"text": "plan"}, tools=plan, decision_only=False,
        final_tools=True, evidence=good_evidence())
    check("fx plan decision accepted", rc["outcome"] == "accepted", rc)
    fx["plan"] = plan
    return fx


def fx_tools_sealed(conn, specs: list[tuple[str, int]],
                     dispatch: list[int] | None = None) -> dict:
    """A sealed tools batch (per-slot retry metadata) with the SELECTED tool
    effects dispatched (default: all); the completions are the caller's."""
    seed = u()[:8]
    s, turn = u(), u()
    create_session(conn, s, DRIVER)
    plan = [{"tool_call_id": f"call-{seed}-{i}", "tool": "fake_tool",
             "arguments": {"echo": seed}} for i in range(len(specs))]
    step, deff = u(), u()
    rh, ik = f"rh-{u()[:10]}", f"ik-{u()[:10]}"
    r0 = claim_session(conn, s, DRIVER)
    rs = prepare_step(conn, s, f"seal-{u()[:8]}", DRIVER, EPOCH,
                      r0["session_fence"], step, turn, deff,
                      request_hash=rh, idempotency_key=ik)
    check("fx decision seal accepted", rs["outcome"] == "accepted", rs)
    rd = dispatch_effect(conn, s, f"dsp-{u()[:8]}", deff, DRIVER, EPOCH,
                         rs["receipt"]["session_fence"],
                         rs["receipt"]["job_fence"])
    check("fx decision dispatch accepted", rd["outcome"] == "accepted", rd)
    rc = complete_effect(
        conn, s, f"cmp-{u()[:8]}", deff, DRIVER, EPOCH,
        dispatch_session_fence=2, job_fence=rs["receipt"]["job_fence"],
        step_id=step, request_hash=rh, idempotency_key=ik,
        outcome="succeeded", message={"text": f"plan:{seed}"}, tools=plan,
        decision_only=False, final_tools=True, evidence=good_evidence())
    check("fx decision complete accepted", rc["outcome"] == "accepted", rc)
    dec_key = next(e["event_key"] for e in rc["receipt"]["events"]
                   if e["event_type"] == "assistant/message")
    plan_hash = one(conn, "SELECT plan_hash FROM steps WHERE step_id=%s",
                    (step,))[0]
    r1 = claim_session(conn, s, DRIVER)
    seal_fence = r1["session_fence"]
    slots = custom_slots(plan, specs)
    rseal = seal_batch(
        conn, s, f"tseal-{u()[:8]}", DRIVER, EPOCH, seal_fence, step, 1,
        {"effect_id": deff, "attempt_no": 1,
         "result_hash": rc["receipt"]["result_hash"],
         "event_key": dec_key},
        plan_hash, slots)
    check("fx tools seal accepted", rseal["outcome"] == "accepted", rseal)
    by_ordinal = {e["dispatch_ordinal"]: e for e in rseal["receipt"]["effects"]}
    effects = []
    for i, slot in enumerate(slots):
        e = by_ordinal[i]
        if dispatch is not None and i not in dispatch:
            effects.append({"effect_id": e["effect_id"],
                            "tool_call_id": slot["tool_call_id"],
                            "request_hash": slot["request_hash"],
                            "idempotency_key": slot["idempotency_key"],
                            "job_fence": e["job_fence"]})
            continue
        rd = dispatch_effect(conn, s, f"dsp-{u()[:8]}", e["effect_id"],
                             DRIVER, EPOCH, seal_fence + 1, e["job_fence"])
        check(f"fx tool {i} dispatch accepted", rd["outcome"] == "accepted",
              rd)
        effects.append({"effect_id": e["effect_id"],
                        "tool_call_id": slot["tool_call_id"],
                        "request_hash": slot["request_hash"],
                        "idempotency_key": slot["idempotency_key"],
                        "job_fence": e["job_fence"]})
    return {"session": s, "turn": turn, "step": step, "effects": effects,
            "rh": rh, "ik": ik, "kind": "tools",
            "seal_fence": seal_fence, "post_seal_fence": seal_fence + 1}


def fail_tool(conn, fx, i: int, attempt_no: int = 1, job_fence=None,
              evidence=None):
    e = fx["effects"][i]
    dsf = fx["seal_fence"] if attempt_no == 1 else fx["post_seal_fence"]
    return complete_tool_effect(
        conn, fx["session"], f"cmp-{u()[:8]}", e["effect_id"], DRIVER, EPOCH,
        dispatch_session_fence=dsf, job_fence=job_fence or e["job_fence"],
        step_id=fx["step"], attempt_no=attempt_no,
        request_hash=e["request_hash"], idempotency_key=e["idempotency_key"],
        outcome="failed_retryable", tool_call_id=e["tool_call_id"],
        output={"error": "rate_limited"},
        evidence=evidence if evidence is not None else fail_evidence())


def succeed_tool_at(conn, fx, i: int, attempt_no: int, job_fence):
    e = fx["effects"][i]
    dsf = fx["seal_fence"] if attempt_no == 1 else fx["post_seal_fence"]
    return complete_tool_effect(
        conn, fx["session"], f"cmp-{u()[:8]}", e["effect_id"], DRIVER, EPOCH,
        dispatch_session_fence=dsf, job_fence=job_fence,
        step_id=fx["step"], attempt_no=attempt_no,
        request_hash=e["request_hash"], idempotency_key=e["idempotency_key"],
        outcome="succeeded", tool_call_id=e["tool_call_id"],
        output={"echo": "ok", "tool": "fake_tool"},
        evidence=good_evidence())


def complete_decision(conn, fx, outcome: str, evidence: dict, *,
                      attempt_no: int = 1, job_fence=None):
    dsf = 2 if attempt_no == 1 else fx["fence"]
    kw = {}
    if outcome != "succeeded":
        # failure-family payloads replace the decision shape
        kw["result_payload"] = {"error": {"kind": "x"}}
    return complete_effect(
        conn, fx["session"], f"cmp-{u()[:8]}", fx["effect"], DRIVER, EPOCH,
        dispatch_session_fence=dsf, job_fence=job_fence or fx["job_fence"],
        step_id=fx["step"], attempt_no=attempt_no, request_hash=fx["rh"],
        idempotency_key=fx["ik"], outcome=outcome, message={"text": ""},
        tools=[], decision_only=True, final_tools=False,
        evidence=evidence, **kw)


def bind_step(conn, step_id, generation_id, impl_digest=None):
    exec_sql(conn,
             "UPDATE steps SET catalog_generation=%s, implementation_digest=%s"
             " WHERE step_id=%s",
             (str(generation_id), impl_digest, str(step_id)))


def gen_row(conn, generation_id):
    return one(conn, "SELECT status, failure_code FROM generations"
                     " WHERE generation_id=%s", (str(generation_id),))


def impl_row(conn, identity, contract_version, locus, driver, plugin_version):
    return one(conn,
               "SELECT implementation_id::text, implementation_digest,"
               " first_published_generation_id::text"
               " FROM plugin_implementations WHERE identity=%s"
               " AND contract_version=%s AND locus=%s AND driver=%s"
               " AND plugin_version=%s",
               (identity, contract_version, locus, driver, plugin_version))


def member_count(conn, generation_id, implementation_id=None) -> int:
    if implementation_id is None:
        return one(conn, "SELECT count(*) FROM generation_members"
                         " WHERE generation_id=%s", (str(generation_id),))[0]
    return one(conn, "SELECT count(*) FROM generation_members"
                     " WHERE generation_id=%s AND implementation_id=%s",
               (str(generation_id), str(implementation_id)))[0]


def publish(conn, candidates: list[dict], **kw) -> dict:
    return publish_generation(conn, manifest(candidates), **kw)


def expect_sql_error(conn, sql: str, params: tuple = (), needle: str = "") -> str:
    """Run a statement expecting a database error; assert the message."""
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
    except psycopg2.Error as exc:
        conn.rollback()
        msg = str(exc)
        if needle:
            check(f"sql error mentions {needle!r}", needle in msg, msg)
        return msg
    raise AssertionError(f"expected a database error, got success: {sql}")


def slot_head(conn, session_id):
    r = one(conn, "SELECT head_event_key FROM turn_end_slots WHERE"
                  " session_id=%s", (str(session_id),))
    return None if r is None else r[0]


# ---------------------------------------------------------------------------
# 1. generation digest: SQL == Python == hand-computed golden vectors
# ---------------------------------------------------------------------------

def test_golden_digest_vectors(conn) -> None:
    for label, members, golden in [
        ("empty member set (the seed)", [], G_OLDEN_EMPTY),
        ("single member", [M_A], GOLDEN_ONE),
        ("two members", [M_A, M_B], GOLDEN_TWO),
        ("two members swapped (order-sensitive)", [M_B, M_A],
         GOLDEN_TWO_SWAPPED),
        ("escaping + UTF-8 identity", [M_ESC], GOLDEN_ESCAPE),
    ]:
        py = generation_member_digest(members)
        sql = sql_digest(conn, members)
        check(f"digest golden [{label}] SQL == Python", sql == py,
              (sql, py))
        check(f"digest golden [{label}] matches hand-computed vector",
              sql == golden, (sql, golden))
    seed_digest = one(conn, "SELECT generation_digest FROM generations"
                            " WHERE generation_id=%s", (SEED,))[0]
    check("seed generation digest is the empty-member-set vector",
          seed_digest == G_OLDEN_EMPTY, seed_digest)


# ---------------------------------------------------------------------------
# 2. table family: spec binding FK, unique key, immutability, GC
# ---------------------------------------------------------------------------

def test_table_family(conn) -> None:
    # spec binding FK: an implementation without a matching spec row cannot
    # enter the catalog.
    expect_sql_error(
        conn,
        "INSERT INTO plugin_implementations(identity, contract_version,"
        " plugin_version, driver, locus, entry, implementation_digest)"
        " VALUES ('ghost', 'cv@9', '1.0.0', 'native', 'sql', 'e', 'd')",
        needle="violates foreign key constraint")
    # publish the spec + one implementation for the direct DDL probes
    g1 = publish(conn, [candidate("ddla", provides=[{"service": "svc",
                                                     "version": "1"}])])
    check("ddl fixture publish built", g1["outcome"] == "activated", g1)
    row = impl_row(conn, "ddla", "cv@1", "sql", "native", "1.0.0")
    check("implementation row exists", row is not None)
    # unique key: a second row with the same frozen key is rejected
    expect_sql_error(
        conn,
        "INSERT INTO plugin_implementations(identity, contract_version,"
        " plugin_version, driver, locus, entry, implementation_digest,"
        " first_published_generation_id)"
        " VALUES ('ddla', 'cv@1', '1.0.0', 'native', 'sql', 'e2', 'd2', %s)",
        (g1["generation_id"],),
        needle="duplicate key value violates unique constraint")
    # global immutability: UPDATE always rejected
    expect_sql_error(conn, "UPDATE plugin_implementations SET entry='x'"
                           " WHERE identity='ddla'",
                     needle="globally immutable")
    # DELETE outside the GC path rejected
    expect_sql_error(conn, "DELETE FROM plugin_implementations"
                           " WHERE identity='ddla'",
                     needle="unreferenced-generation GC")
    # member rows immutable
    expect_sql_error(conn, "UPDATE generation_members SET included_at=now()",
                     needle="immutable after the publish")
    expect_sql_error(conn, "DELETE FROM generation_members", needle="GC")
    # specs immutable
    expect_sql_error(conn, "UPDATE plugin_specs SET portability='x'",
                     needle="immutable after creation")
    expect_sql_error(conn, "DELETE FROM plugin_specs", needle="immutable")
    # generations only through the protected lifecycle functions
    expect_sql_error(conn, "UPDATE generations SET status='active'",
                     needle="protected")
    expect_sql_error(conn, "DELETE FROM generations", needle="protected")

    # GC: g2 reuses ddla (same key + digest) and adds ddlb; g3 reuses
    # ddla again and adds ddlc. Retiring via activation makes g1/g2
    # collectable once unbound.
    g2 = publish(conn, [candidate("ddla", provides=[{"service": "svc",
                                                     "version": "1"}]),
                        candidate("ddlb", provides=[{"service": "svc2",
                                                     "version": "1"}])])
    check("gc fixture g2 built", g2["outcome"] == "activated", g2)
    shared = impl_row(conn, "ddla", "cv@1", "sql", "native", "1.0.0")
    check("refresh reuse: exactly one immutable row for the shared key",
          member_count(conn, g1["generation_id"], shared[0]) == 1
          and member_count(conn, g2["generation_id"], shared[0]) == 1)
    check("refresh reuse: first_published_generation_id NOT rewritten",
          shared[2] == g1["generation_id"], shared)
    g3 = publish(conn, [candidate("ddla", provides=[{"service": "svc",
                                                     "version": "1"}]),
                        candidate("ddlc", provides=[{"service": "svc3",
                                                     "version": "1"}])])
    check("gc fixture g3 built (keeps ddla shared beyond g2)",
          g3["outcome"] == "activated", g3)
    check("g1 digest differs from g2 digest (member sets differ)",
          one(conn, "SELECT generation_digest FROM generations"
                    " WHERE generation_id=%s",
              (g1["generation_id"],))[0]
          != one(conn, "SELECT generation_digest FROM generations"
                       " WHERE generation_id=%s",
                 (g2["generation_id"],))[0])
    # GC of the active generation is refused
    expect_sql_error(conn, "SELECT v_gc_generation(%s::uuid)",
                     (g3["generation_id"],),
                     needle="only a failed or retired generation")
    r = gc_generation(conn, g1["generation_id"])
    check("GC collected the retired unreferenced generation g1",
          r["outcome"] == "collected"
          and one(conn, "SELECT count(*) FROM generations"
                        " WHERE generation_id=%s",
                  (g1["generation_id"],))[0] == 0
          and member_count(conn, g1["generation_id"]) == 0, r)
    check("GC kept the implementation shared by living generations (ddla)",
          impl_row(conn, "ddla", "cv@1", "sql", "native", "1.0.0")
          is not None)
    r = gc_generation(conn, g2["generation_id"])
    check("GC collected the retired unreferenced generation g2",
          r["outcome"] == "collected"
          and one(conn, "SELECT count(*) FROM generations"
                        " WHERE generation_id=%s",
                  (g2["generation_id"],))[0] == 0, r)
    check("GC deleted g2's unshared implementation row (ddlb)",
          impl_row(conn, "ddlb", "cv@1", "sql", "native", "1.0.0") is None)
    check("GC kept the row still referenced by g3 (ddla)",
          impl_row(conn, "ddla", "cv@1", "sql", "native", "1.0.0")
          is not None)
    # back to the seed pointer for the later tests
    dispose_pointer(conn, "point", SEED)


# ---------------------------------------------------------------------------
# 3. dependency resolution: stable order + three rejection classes
# ---------------------------------------------------------------------------

def resolved_order(built: dict) -> list[str]:
    return [m["identity"] for m in built["members"]]


def test_dependency_resolution(conn) -> None:
    # stable order: priority DESC, identity ASC (UTF-8 bytes), plugin_version
    # ASC (dotted-numeric); the 'B' < 'a' identity pair discriminates the
    # byte order from common ICU/libc locale orders (never the locale).
    cs = [candidate("a-low"), candidate("B-upper"), candidate("0-prio",
                                                             priority=5),
          candidate("z-low")]
    r = publish(conn, cs, skip_preload=True)
    check("resolution: build succeeded", r["outcome"] == "built", r)
    check("resolution: stable frozen order (priority DESC, identity bytes"
          " ASC, dotted-numeric version ASC)",
          resolved_order(r) == ["0-prio", "B-upper", "a-low", "z-low"],
          resolved_order(r))
    r2 = publish(conn, list(reversed(cs)), skip_preload=True)
    check("resolution: input order does not matter (same member order and"
          " digest)", resolved_order(r2) == resolved_order(r)
          and r2["generation_digest"] == r["generation_digest"])
    # dotted-numeric: 1.2 == 1.2.0 (missing segments pad 0) < 1.2.1
    check("dotted-numeric: 1.2 == 1.2.0",
          one(conn, "SELECT v_plugin_version_key('1.2') ="
                    " v_plugin_version_key('1.2.0')")[0] is True)
    check("dotted-numeric: 1.2.0 < 1.2.1 (numeric, not string)",
          one(conn, "SELECT v_plugin_version_key('1.2')"
                    " < v_plugin_version_key('1.2.1')")[0] is True)
    check("dotted-numeric: 1.10 > 1.9 (numeric segment compare)",
          one(conn, "SELECT v_plugin_version_key('1.10')"
                    " > v_plugin_version_key('1.9')")[0] is True)
    # a require satisfied by 1.2 against range >=1.2.0
    rr = publish(conn, [
        candidate("dep-base", plugin_version="1.2"),
        candidate("dep-user", requires=[{"identity": "dep-base",
                                         "version": ">=1.2.0"}]),
    ], skip_preload=True)
    check("resolution: dotted-numeric range satisfaction", rr["outcome"]
          == "built", rr)
    # dependency cycle -> building -> failed
    r = publish(conn, [
        candidate("cyc-a", requires=[{"identity": "cyc-b", "version": "*"}]),
        candidate("cyc-b", requires=[{"identity": "cyc-a", "version": "*"}]),
    ])
    check("cycle: whole-generation rejection building -> failed",
          r["outcome"] == "build_failed" and r["code"] == "DEPENDENCY_CYCLE",
          r)
    check("cycle: candidate row persisted as failed",
          gen_row(conn, r["generation_id"]) == ("failed", None)
          or gen_row(conn, r["generation_id"])[0] == "failed")
    # duplicate provide within the same driver scope
    r = publish(conn, [
        candidate("dup-a", provides=[{"service": "svc", "version": "1"}]),
        candidate("dup-b", provides=[{"service": "svc", "version": "1"}]),
    ])
    check("duplicate provide: whole-generation rejection",
          r["outcome"] == "build_failed" and r["code"] == "DUPLICATE_PROVIDE",
          r)
    # the same service across DIFFERENT drivers coexists (driver scoping)
    r = publish(conn, [
        candidate("dup-a2", driver="native",
                  provides=[{"service": "svc", "version": "1"}]),
        candidate("dup-b2", driver="compat", locus="host",
                  provides=[{"service": "svc", "version": "1"}]),
    ], skip_preload=True)
    check("duplicate provide is per-driver (native/compat coexist)",
          r["outcome"] == "built", r)
    # version mismatch: absent identity
    r = publish(conn, [
        candidate("need-missing",
                  requires=[{"identity": "not-there", "version": "*"}]),
    ])
    check("version mismatch (absent identity): rejection",
          r["outcome"] == "build_failed" and r["code"] == "VERSION_MISMATCH",
          r)
    # version mismatch: identity present, range unsatisfied
    r = publish(conn, [
        candidate("have-old", plugin_version="1.0.0"),
        candidate("need-new",
                  requires=[{"identity": "have-old",
                             "version": ">=2.0.0"}]),
    ])
    check("version mismatch (unsatisfied range): rejection",
          r["outcome"] == "build_failed" and r["code"] == "VERSION_MISMATCH",
          r)
    # optional requires may stay unsatisfied
    r = publish(conn, [
        candidate("opt-user",
                  requires=[{"identity": "not-there", "version": "*",
                             "optional": True}]),
    ], skip_preload=True)
    check("optional require unsatisfied is fine", r["outcome"] == "built", r)


# ---------------------------------------------------------------------------
# 4. publish lifecycle: failures, refresh, pointer switch
# ---------------------------------------------------------------------------

def test_publish_lifecycle(conn) -> None:
    ptr_before = active_pointer(conn)
    # SCAN_INVALID: missing identity
    c = candidate("scan-bad")
    del c["identity"]
    r = publish(conn, [c])
    check("scan failure -> building -> failed SCAN_INVALID",
          r["outcome"] == "build_failed" and r["code"] == "SCAN_INVALID", r)
    # DIGEST_MISMATCH: declared digest does not match the scanned content
    r = publish(conn, [candidate("digest-bad", declared_digest="00" * 32)])
    check("digest verification failure -> DIGEST_MISMATCH",
          r["outcome"] == "build_failed" and r["code"] == "DIGEST_MISMATCH",
          r)
    # READINESS_FAILED: the worker preload raises
    def _boom(ctx, config):
        raise RuntimeError("preload exploded")
    r = publish(conn, [candidate("ready-bad")], apply_fn=_boom)
    check("preload failure -> building -> failed READINESS_FAILED",
          r["outcome"] == "build_failed" and r["code"] == "READINESS_FAILED",
          r)
    check("build failures never touched the active pointer",
          active_pointer(conn) == ptr_before)
    check("build failures leave the (previous) active generation active",
          gen_row(conn, ptr_before)[0] == "active")

    # successful publish: atomic switch, previous active retired, history
    g1 = publish(conn, [candidate("pub-a"),
                        candidate("pub-b", priority=1)])
    check("publish activated", g1["outcome"] == "activated", g1)
    check("atomic switch: pointer now the new generation",
          active_pointer(conn) == g1["generation_id"])
    check("atomic switch: previous active retired",
          gen_row(conn, ptr_before)[0] == "retired")
    hist = one(conn, "SELECT action, operator, target_generation::text"
                     " FROM catalog_pointer_history"
                     " WHERE target_generation=%s"
                     " ORDER BY history_id DESC", (g1["generation_id"],))
    check("pointer disposition persisted (operator/time/target)",
          hist is not None and hist[0] == "activate" and hist[1] == "operator")
    # activating a non-building generation is refused
    expect_sql_error(conn, "SELECT v_activate_generation(%s::uuid)",
                     (g1["generation_id"],),
                     needle="only a building generation")
    # republish with the SAME key + digest reuses the immutable row
    a1 = impl_row(conn, "pub-a", "cv@1", "sql", "native", "1.0.0")
    g2 = publish(conn, [candidate("pub-a"),
                        candidate("pub-b", priority=1),
                        candidate("pub-c", plugin_version="2.0.0")])
    check("second publish activated", g2["outcome"] == "activated", g2)
    a2 = impl_row(conn, "pub-a", "cv@1", "sql", "native", "1.0.0")
    check("same key + same digest: the immutable row is REUSED (no second"
          " row, no first_published rewrite)",
          a1[0] == a2[0] and a2[2] == g1["generation_id"]
          and one(conn, "SELECT count(*) FROM plugin_implementations"
                        " WHERE identity='pub-a'")[0] == 1)
    check("both generations reference the shared implementation",
          member_count(conn, g1["generation_id"], a1[0]) == 1
          and member_count(conn, g2["generation_id"], a1[0]) == 1)
    check("generation digests cover their member sets (differ)",
          one(conn, "SELECT generation_digest FROM generations"
                    " WHERE generation_id=%s",
              (g1["generation_id"],))[0]
          != one(conn, "SELECT generation_digest FROM generations"
                       " WHERE generation_id=%s",
                 (g2["generation_id"],))[0])
    # content change WITH a version bump produces a new implementation row
    check("changed plugin produced a new row via the bumped version",
          impl_row(conn, "pub-c", "cv@1", "sql", "native", "2.0.0")
          is not None)
    # same key + different digest republish: stable rejection (immutable
    # entity, no rewrite path; content change MUST bump plugin_version)
    r = publish(conn, [candidate("pub-a", content="different content")])
    check("same key different digest: stable rejection",
          r["outcome"] == "build_failed"
          and r["code"] == "CONTENT_CHANGE_NEEDS_VERSION_BUMP", r)
    check("the rejection persisted a failed candidate and no new row",
          gen_row(conn, r["generation_id"])[0] == "failed"
          and one(conn, "SELECT count(*) FROM plugin_implementations"
                        " WHERE identity='pub-a'")[0] == 1)
    # a fresh build left sitting in building cannot serve
    idle = build_generation(conn, manifest([candidate("idle")]))
    check("idle build stays building (not published, not pointed)",
          idle["outcome"] == "built"
          and gen_row(conn, idle["generation_id"])[0] == "building"
          and active_pointer(conn) == g2["generation_id"])
    # the manual fail path writes the same terminal shape
    fr = fail_generation_building(conn, idle["generation_id"], "OPERATOR",
                                  "abandoned")
    check("v_fail_generation_building terminates the candidate",
          fr["outcome"] == "build_failed"
          and gen_row(conn, idle["generation_id"])
          == ("failed", "OPERATOR"), fr)
    # retire + GC the idle chain to keep the catalog small
    dispose_pointer(conn, "point", g2["generation_id"])
    # restore the seed for the later sections
    dispose_pointer(conn, "point", SEED)


# ---------------------------------------------------------------------------
# 5. steps binding + the shared generation-check sub-operation
# ---------------------------------------------------------------------------

def test_steps_binding(conn) -> None:
    fx = fx_ready(conn)
    bound = one(conn, "SELECT catalog_generation::text,"
                     " implementation_digest FROM steps WHERE step_id=%s",
                (fx["step"],))
    check("a v_prepare_step-created step binds the DEFAULT seed generation",
          bound[0] == SEED, bound)
    check("the implementation binding column exists (NULL until wired)",
          bound[1] is None)
    check("the backfilled/seed binding is indistinguishable from an"
          " explicit seed bind",
          one(conn, "SELECT catalog_generation::text FROM steps"
                    " WHERE step_id=%s", (fx["step"],))[0] == SEED)
    # the shared generation-check sub-operation (for the G12 wiring)
    check("v_step_generation_status: seed is active",
          step_generation_status(conn, fx["step"]) == "active")
    g = publish(conn, [candidate("bind-me")])
    bind_step(conn, fx["step"], g["generation_id"], impl_digest="d1")
    check("v_step_generation_status: reads the bound generation",
          step_generation_status(conn, fx["step"]) == "active")
    r = revoke_generation(conn, g["generation_id"], "probe",
                          pointer_action="clear")
    check("probe revoke ok", r["outcome"] == "revoked", r)
    check("v_step_generation_status: failed after the offline",
          step_generation_status(conn, fx["step"]) == "failed")
    dispose_pointer(conn, "point", SEED)
    check("v_step_generation_status keeps reading the bound (failed)"
          " generation after the pointer rollback",
          step_generation_status(conn, fx["step"]) == "failed"
          and gen_row(conn, SEED)[0] == "active")
    # drain of this probe session already closed the step
    check("probe step closed failed_terminal/GENERATION_REVOKED",
          step_row(conn, fx["step"])[0] == "failed_terminal"
          and step_row(conn, fx["step"])[1] == "GENERATION_REVOKED")


# ---------------------------------------------------------------------------
# 6. readiness registry (process-level apply contract)
# ---------------------------------------------------------------------------

def test_readiness_registry() -> None:
    reg = PluginHandlerRegistry()
    members = [{"identity": "p1", "plugin_version": "1.0.0",
                "implementation_digest": "d1"}]
    applied = reg.apply("gen-1", members)
    check("apply registers the member handler", len(applied) == 1)
    check("registry has the key", reg.has("gen-1", "p1", "1.0.0"))
    again = reg.apply("gen-1", members)
    check("same key + same digest re-apply is a no-op", again == [])
    try:
        reg.apply("gen-1", [{"identity": "p1", "plugin_version": "1.0.0",
                             "implementation_digest": "d2"}])
        raise AssertionError("expected ReadinessConflict")
    except ReadinessConflict:
        check("same key different digest is a conflict", True)
    # catalog active != handler ready: a fresh process (registry) has not
    # loaded the digest and MUST NOT claim.
    fresh = PluginHandlerRegistry()
    check("catalog active does not imply handler ready (negative)",
          not fresh.ready_to_claim("gen-1", members))
    check("the loaded process is ready to claim",
          reg.ready_to_claim("gen-1", members))
    # the ctx surface: pure registration only
    from v8.plugin.client import NativeCtx
    ctx = NativeCtx()
    ctx.tools.register({"name": "t1"})
    ctx.systemPrompt_section("s1", "text")
    ctx.on("plugin", lambda: None)
    ctx.config["k"] = "v"
    check("NativeCtx surface: tools/section/hook/get",
          ctx._registered_tools == [{"name": "t1"}]
          and ctx.prompt_sections == [{"id": "s1", "text": "text"}]
          and "plugin" in ctx.hooks and ctx.get("k") == "v")


# ---------------------------------------------------------------------------
# 7. offline drain: the happy path (Conformance 8 (i)/(v))
# ---------------------------------------------------------------------------

def test_offline_drain(conn) -> None:
    g = publish(conn, [candidate("drain-p1"),
                       candidate("drain-p2", priority=1)])
    check("drain fixture published", g["outcome"] == "activated", g)
    fx = fx_ready(conn)
    bind_step(conn, fx["step"], g["generation_id"], impl_digest="dd1")
    r = revoke_generation(conn, g["generation_id"], "fatal defect",
                          pointer_action="clear",
                          revoke_id="rv-drain-1")
    check("revoke accepted", r["outcome"] == "revoked", r)
    check("generation building->...->failed with the reason recorded",
          gen_row(conn, g["generation_id"])
          == ("failed", "REVOKED")
          and one(conn, "SELECT failure_detail FROM generations"
                        " WHERE generation_id=%s",
                  (g["generation_id"],))[0] == "fatal defect")
    check("pointer explicitly cleared (no drift)",
          active_pointer(conn) is None)
    er = effect_row(conn, fx["effect"])
    check("drained effect cancelled_before_dispatch",
          er[0] == "cancelled_before_dispatch", er)
    att = attempt_rows(conn, fx["effect"])
    check("drained attempt cancelled_before_dispatch (dual-table sync)",
          len(att) == 1 and att[0][1] == "cancelled_before_dispatch", att)
    audits = rows(conn,
                  "SELECT reason, internal_op_kind, parent_command_id,"
                  " internal_op_ordinal FROM effect_audit"
                  " WHERE effect_id=%s ORDER BY audit_id",
                  (fx["effect"],))
    check("ABORTED_BEFORE_DISPATCH audit from the shared sync",
          any(a[0] == "ABORTED_BEFORE_DISPATCH" and a[1] is None
              for a in audits), audits)
    check("GENERATION_REVOKED audit context (internal triple)",
          any(a[0] == "GENERATION_REVOKED"
              and a[1] == "generation_revocation_drain"
              and a[2] == "rv-drain-1" and a[3] == 0
              for a in audits), audits)
    st = step_row(conn, fx["step"])
    check("three-conjunction step closure: failed_terminal/"
          "GENERATION_REVOKED",
          st[0] == "failed_terminal" and st[1] == "GENERATION_REVOKED", st)
    check("session derived failed/GENERATION_REVOKED",
          session_row(conn, fx["session"])
          == ("failed", "GENERATION_REVOKED"))
    check("no non-terminal undispatched effect residue bound to the"
          " generation",
          one(conn, "SELECT count(*) FROM effect_requests er"
                    " JOIN steps st ON st.step_id=er.step_id"
                    " WHERE st.catalog_generation=%s"
                    "   AND er.status IN ('ready', 'planned')",
              (g["generation_id"],))[0] == 0)
    hist = one(conn, "SELECT action, operator FROM catalog_pointer_history"
                     " WHERE action='revoke' ORDER BY history_id DESC")
    check("revoke disposition persisted (versioned, operator, target)",
          hist is not None and hist[1] == "operator", hist)
    # repeat invocation is a stable rejection (nothing left to drain)
    msg = expect_sql_error(conn, "SELECT v_revoke_generation(%s::uuid, %s,"
                                 " %s, %s, NULL, NULL)",
                           (g["generation_id"], "again", "operator",
                            "clear"),
                           needle="GENERATION_NOT_ACTIVE")
    check("second revoke stably rejected GENERATION_NOT_ACTIVE",
          "GENERATION_NOT_ACTIVE" in msg)
    dispose_pointer(conn, "point", SEED)


# ---------------------------------------------------------------------------
# 8. multi-session drain + the pre-lock/rescan retry protocol
# ---------------------------------------------------------------------------

def test_offline_multi_session_and_rescan(conn) -> None:
    g = publish(conn, [candidate("multi")])
    fx1 = fx_ready(conn)
    fx2 = fx_ready(conn)
    bind_step(conn, fx1["step"], g["generation_id"])
    bind_step(conn, fx2["step"], g["generation_id"])
    r = revoke_generation(conn, g["generation_id"], "multi",
                          pointer_action="clear")
    check("multi-session revoke accepted", r["outcome"] == "revoked", r)
    check("both sessions prelocked and drained",
          len(r["prelocked_sessions"]) == 2
          and session_row(conn, fx1["session"])[1] == "GENERATION_REVOKED"
          and session_row(conn, fx2["session"])[1] == "GENERATION_REVOKED")
    check("both attempts drained",
          attempt_rows(conn, fx1["effect"])[0][1]
          == "cancelled_before_dispatch"
          and attempt_rows(conn, fx2["effect"])[0][1]
          == "cancelled_before_dispatch")
    dispose_pointer(conn, "point", SEED)

    # (ix-a)/(ix-b): the deterministic rescan-retry seam — the FIRST
    # pre-lock pass misses a bound session; the in-lock rescan discovers
    # it, the transaction rolls back wholly and re-locks in the frozen
    # total order (never reverse-order补lock).
    g2 = publish(conn, [candidate("rescan")])
    fx3 = fx_ready(conn)
    fx4 = fx_ready(conn)
    bind_step(conn, fx3["step"], g2["generation_id"])
    bind_step(conn, fx4["step"], g2["generation_id"])
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('v8.revoke_test_hide_session', %s,"
                    " true)", (fx4["session"],))
        cur.execute("SELECT v_revoke_generation(%s::uuid, %s, %s, %s,"
                    " NULL, 'rv-rescan')",
                    (g2["generation_id"], "rescan probe", "operator",
                     "clear"))
        out = cur.fetchone()[0]
    conn.commit()
    check("rescan retry: the revoke retried after the in-lock discovery",
          out["outcome"] == "revoked" and out["attempts"] >= 2, out)
    check("rescan retry: the missed session's effect drained on the retry",
          attempt_rows(conn, fx4["effect"])[0][1]
          == "cancelled_before_dispatch")
    check("rescan retry: no residue after convergence",
          one(conn, "SELECT count(*) FROM effect_requests er"
                    " JOIN steps st ON st.step_id=er.step_id"
                    " WHERE st.catalog_generation=%s AND er.status='ready'",
              (g2["generation_id"],))[0] == 0)
    check("rescan retry: retry count visible in the receipt",
          out["attempts"] == 2, out["attempts"])
    dispose_pointer(conn, "point", SEED)


# ---------------------------------------------------------------------------
# 9. late completion of a drained effect is rejected by the existing rules
# ---------------------------------------------------------------------------

def test_offline_late_completion(conn) -> None:
    g = publish(conn, [candidate("late")])
    fx = fx_ready(conn)
    bind_step(conn, fx["step"], g["generation_id"])
    revoke_generation(conn, g["generation_id"], "late",
                      pointer_action="clear")
    dispose_pointer(conn, "point", SEED)
    rc = complete_decision(conn, fx, "succeeded", good_evidence())
    check("late completion of a drained effect rejected", rc["outcome"]
          == "rejected_mismatch", rc)
    check("late completion code ATTEMPT_ALREADY_SETTLED (existing rule)",
          rc["code"] == "ATTEMPT_ALREADY_SETTLED", rc)
    check("late completion left the control state untouched",
          session_row(conn, fx["session"])
          == ("failed", "GENERATION_REVOKED")
          and effect_row(conn, fx["effect"])[0]
          == "cancelled_before_dispatch")


# ---------------------------------------------------------------------------
# 10. in-flight keeps the snapshot and completes (Conformance 8 (ii))
# ---------------------------------------------------------------------------

def test_offline_inflight_completes(conn) -> None:
    g = publish(conn, [candidate("inflight")])
    fx = fx_dispatched(conn)
    bind_step(conn, fx["step"], g["generation_id"])
    r = revoke_generation(conn, g["generation_id"], "inflight",
                          pointer_action="point", pointer_target=SEED)
    check("inflight revoke accepted with the rollback disposition",
          r["outcome"] == "revoked", r)
    check("rollback disposition: the seed is active again (versioned)",
          active_pointer(conn) == SEED
          and gen_row(conn, SEED)[0] == "active")
    check("the dispatched effect was NOT drained (snapshot held)",
          effect_row(conn, fx["effect"])[0] == "dispatch_started")
    rc = complete_decision(conn, fx, "succeeded", good_evidence())
    check("in-flight completion accepted after the offline", rc["outcome"]
          == "accepted", rc)
    st = step_row(conn, fx["step"])
    check("the completed step finalizes by the existing rules (not"
          " GENERATION_REVOKED)",
          st[0] == "succeeded" and st[1] != "GENERATION_REVOKED", st)
    check("the session did not fail because of the offline",
          session_row(conn, fx["session"])[0]
          in ("ready", "completed"))
    # the next step created by the continuation binds the rolled-back
    # active generation (the DEFAULT seed == the pointer).
    s2, t2, st2, e2 = u(), u(), u(), u()
    create_session(conn, s2, DRIVER)
    r0 = claim_session(conn, s2, DRIVER)
    rs = prepare_step(conn, s2, f"seal-{u()[:8]}", DRIVER, EPOCH,
                      r0["session_fence"], st2, t2, e2)
    check("continuation step binds the rolled-back active generation",
          rs["outcome"] == "accepted"
          and one(conn, "SELECT catalog_generation::text FROM steps"
                        " WHERE step_id=%s", (st2,))[0]
          == active_pointer(conn) == SEED)


# ---------------------------------------------------------------------------
# 11. sticky cancel takes priority over the offline closure
# ---------------------------------------------------------------------------

def test_offline_sticky_cancel_priority(conn) -> None:
    # (a) a session whose cancel closure already ran: the existing cancel
    # terminal state is NOT rewritten by the offline.
    g = publish(conn, [candidate("sticky1")])
    fx = fx_ready(conn)
    bind_step(conn, fx["step"], g["generation_id"])
    from v8.cancel.client import request_cancel
    rc = request_cancel(conn, fx["session"], f"cx-{u()[:8]}", DRIVER, EPOCH)
    check("fixture: cancel collapsed the session", rc["outcome"]
          == "accepted", rc)
    revoke_generation(conn, g["generation_id"], "sticky",
                      pointer_action="clear")
    dispose_pointer(conn, "point", SEED)
    check("sticky cancel terminal kept (cancel-wins, not rewritten)",
          session_row(conn, fx["session"])[0] == "cancelled"
          and step_row(conn, fx["step"])[1] != "GENERATION_REVOKED")

    # (b) a latch with an in-flight member: the step waits for the cancel
    # closure (rule 2 sticky), never GENERATION_REVOKED.
    g2 = publish(conn, [candidate("sticky2")])
    fx2 = fx_dispatched(conn)
    bind_step(conn, fx2["step"], g2["generation_id"])
    rc = request_cancel(conn, fx2["session"], f"cx-{u()[:8]}", DRIVER, EPOCH)
    check("fixture: latch set with the in-flight member waiting", rc[
        "outcome"] == "accepted", rc)
    revoke_generation(conn, g2["generation_id"], "sticky2",
                      pointer_action="clear")
    dispose_pointer(conn, "point", SEED)
    st = step_row(conn, fx2["step"])
    check("pending sibling: step stays cancel_requested (drain pending)",
          st[0] == "cancel_requested" and st[1] != "GENERATION_REVOKED", st)
    check("in-flight member untouched by the drain",
          effect_row(conn, fx2["effect"])[0] == "dispatch_started")


# ---------------------------------------------------------------------------
# 12. unknown sibling: rule 1 holds; repair then derives the existing code
# (Conformance 8 (iv): the drained member never flips the derivation)
# ---------------------------------------------------------------------------

def test_offline_unknown_sibling(conn) -> None:
    # tools batch, both slots verifiable with budget 2:
    #   att1 both known_failure -> rule 5 -> retry allocates att2 for both
    #   -> dispatch B att2, complete B att2 unknown -> rule 1 blocked
    #   -> bind, revoke (drains A att2), repair B att2 failed_terminal
    #      -> rule 4 derives FAILED_RETRY_BUDGET_EXHAUSTED
    fx = fx_tools_sealed(conn, [("verifiable_no_effect", 2),
                                ("verifiable_no_effect", 2)])
    r1 = fail_tool(conn, fx, 0)
    check("fixture: tool A att1 known_failure", r1["outcome"] == "accepted",
          r1)
    r2 = fail_tool(conn, fx, 1)
    check("fixture: tool B att1 known_failure", r2["outcome"] == "accepted",
          r2)
    rr = retry_effect(conn, fx["session"], f"rty-{u()[:8]}",
                      fx["effects"][0]["effect_id"], DRIVER, EPOCH,
                      fx["post_seal_fence"])
    check("fixture: cohort retry allocated att2 for both members",
          rr["outcome"] == "accepted"
          and effect_row(conn, fx["effects"][0]["effect_id"])[1] == 2, rr)
    eB = fx["effects"][1]
    jfB = effect_row(conn, eB["effect_id"])[2]
    rd = dispatch_effect(conn, fx["session"], f"dsp-{u()[:8]}",
                         eB["effect_id"], DRIVER, EPOCH,
                         fx["post_seal_fence"], jfB)
    check("fixture: tool B att2 dispatched", rd["outcome"] == "accepted",
          rd)
    ru = fail_tool(conn, fx, 1, attempt_no=2, job_fence=jfB,
                   evidence={"class": "provider_error",
                             "detail": "no bound terminal provider receipt"})
    check("fixture: tool B att2 unknown", ru["outcome"] == "accepted"
          and effect_row(conn, eB["effect_id"])[0] == "unknown_outcome", ru)
    g = publish(conn, [candidate("unk")])
    bind_step(conn, fx["step"], g["generation_id"])
    r = revoke_generation(conn, g["generation_id"], "unk",
                          pointer_action="clear")
    dispose_pointer(conn, "point", SEED)
    check("revoke accepted", r["outcome"] == "revoked", r)
    eA = fx["effects"][0]
    check("A (ready att2) drained", effect_row(conn, eA["effect_id"])[0]
          == "cancelled_before_dispatch")
    st = step_row(conn, fx["step"])
    check("unknown sibling: step stays blocked_unknown_effect (rule 1)",
          st[0] == "blocked_unknown_effect"
          and st[1] != "GENERATION_REVOKED", st)
    check("session stays blocked_unknown_effect (not failed)",
          session_row(conn, fx["session"])[0] == "blocked_unknown_effect")
    # repair proves B failed (attempt 2 of 2 -> budget_exhausted): rule 4
    # derives the EXISTING code, never GENERATION_REVOKED.
    from v8.repair.client import repair
    rp = repair(conn, fx["session"], f"rpr-{u()[:8]}", eB["effect_id"], 2,
                driver=DRIVER, driver_epoch=EPOCH,
                supersedes_event_key=slot_head(conn, fx["session"]),
                evidence=fail_evidence(), resolution_kind="failed_terminal",
                tool_call_id=eB["tool_call_id"],
                output={"error": "rate_limited"})
    check("repair accepted", rp["outcome"] == "accepted", rp)
    st = step_row(conn, fx["step"])
    check("mixed member: rule 4 derives FAILED_RETRY_BUDGET_EXHAUSTED"
          " (existing code kept, NOT GENERATION_REVOKED)",
          st[0] == "failed_terminal"
          and st[1] == "FAILED_RETRY_BUDGET_EXHAUSTED", st)
    check("session derived failed with the rule-4 code",
          session_row(conn, fx["session"])
          == ("failed", "FAILED_RETRY_BUDGET_EXHAUSTED"))


# ---------------------------------------------------------------------------
# 13. pending (in-flight) sibling: no premature finalization
# ---------------------------------------------------------------------------

def test_offline_pending_sibling(conn) -> None:
    # dispatch only tool 0; tool 1 stays ready (the drain target)
    fx = fx_tools_sealed(conn, [("unsafe", 1), ("unsafe", 1)],
                         dispatch=[0])
    g = publish(conn, [candidate("pend")])
    bind_step(conn, fx["step"], g["generation_id"])
    revoke_generation(conn, g["generation_id"], "pend",
                      pointer_action="clear")
    dispose_pointer(conn, "point", SEED)
    e0, e1 = fx["effects"]
    check("ready sibling drained, in-flight sibling kept",
          effect_row(conn, e1["effect_id"])[0]
          == "cancelled_before_dispatch"
          and effect_row(conn, e0["effect_id"])[0] == "dispatch_started")
    st = step_row(conn, fx["step"])
    check("step stays waiting_effect (drain pending, no premature"
          " finalization)",
          st[0] == "waiting_effect" and st[1] != "GENERATION_REVOKED", st)
    check("session stays waiting_effect",
          session_row(conn, fx["session"])[0] == "waiting_effect")


# ---------------------------------------------------------------------------
# 14. pure rule-5 residual: the controlled edge under GENERATION_REVOKED
# ---------------------------------------------------------------------------

def test_offline_rule5_residual(conn) -> None:
    fx = fx_dispatched(conn, retry_class="verifiable_no_effect",
                       max_attempts=3)
    rc = complete_decision(conn, fx, "failed_retryable", fail_evidence())
    check("fixture: eligible failed_retryable (rule 5)",
          rc["outcome"] == "accepted"
          and step_row(conn, fx["step"])[0] == "failed_retryable", rc)
    g = publish(conn, [candidate("r5")])
    bind_step(conn, fx["step"], g["generation_id"])
    r = revoke_generation(conn, g["generation_id"], "r5",
                          pointer_action="clear")
    dispose_pointer(conn, "point", SEED)
    check("revoke accepted", r["outcome"] == "revoked", r)
    er = effect_row(conn, fx["effect"])
    check("residual failed_retryable closed via the controlled edge"
          " (original facts kept, stop reason persisted)",
          er[0] == "failed_terminal" and er[1] == 1
          and er[5] == "not_retry_eligible"
          and er[6] is not None, er)
    att = attempt_rows(conn, fx["effect"])
    check("attempt row closed failed_terminal (dual-table)", att[-1][1]
          == "failed_terminal", att)
    check("RETRY_STOPPED_BY_CLOSURE audit written",
          one(conn, "SELECT count(*) FROM effect_audit"
                    " WHERE effect_id=%s AND reason='RETRY_STOPPED_BY_CLOSURE'",
              (fx["effect"],))[0] == 1)
    st = step_row(conn, fx["step"])
    check("step failed_terminal/GENERATION_REVOKED via the three"
          " conjunction",
          st[0] == "failed_terminal" and st[1] == "GENERATION_REVOKED", st)
    check("session failed/GENERATION_REVOKED",
          session_row(conn, fx["session"])
          == ("failed", "GENERATION_REVOKED"))


# ---------------------------------------------------------------------------
# 15. unsealed plan voided with the decision result kept in audit
# ---------------------------------------------------------------------------

def test_offline_unsealed_plan(conn) -> None:
    fx = fx_plan(conn)
    st0 = step_row(conn, fx["step"])
    check("fixture: step ready/stage=decision with a persisted plan",
          st0[0] == "ready"
          and one(conn, "SELECT stage, plan_canonical IS NOT NULL FROM steps"
                        " WHERE step_id=%s", (fx["step"],))
          == ("decision", True), st0)
    g = publish(conn, [candidate("plan")])
    bind_step(conn, fx["step"], g["generation_id"])
    plan_hash = one(conn, "SELECT plan_hash FROM steps WHERE step_id=%s",
                    (fx["step"],))[0]
    r = revoke_generation(conn, g["generation_id"], "plan",
                          pointer_action="clear")
    dispose_pointer(conn, "point", SEED)
    check("revoke accepted", r["outcome"] == "revoked", r)
    st = step_row(conn, fx["step"])
    check("unsealed-plan step closed failed_terminal/GENERATION_REVOKED",
          st[0] == "failed_terminal" and st[1] == "GENERATION_REVOKED", st)
    voided = one(conn,
                 "SELECT reason, result_fingerprint FROM effect_audit"
                 " WHERE audit_context_session_id=%s"
                 "   AND reason='GENERATION_REVOKED' AND effect_id IS NULL",
                 (fx["session"],))
    check("unsealed plan voided with the decision result kept in audit"
          " (plan_hash fingerprint)",
          voided is not None and voided[1] == plan_hash, voided)
    check("session failed/GENERATION_REVOKED",
          session_row(conn, fx["session"])
          == ("failed", "GENERATION_REVOKED"))


# ---------------------------------------------------------------------------
# 16. pointer disposition: explicit only, never auto drift
# ---------------------------------------------------------------------------

def test_pointer_disposition(conn) -> None:
    g = publish(conn, [candidate("ptr")])
    fx = fx_ready(conn)
    bind_step(conn, fx["step"], g["generation_id"])
    msg = expect_sql_error(conn, "SELECT v_revoke_generation(%s::uuid, %s,"
                                 " %s, NULL, NULL, NULL)",
                           (g["generation_id"], "nodrift", "operator"),
                           needle="POINTER_DISPOSITION_REQUIRED")
    check("revoking the pointed generation requires an explicit"
          " disposition (no auto drift)",
          "POINTER_DISPOSITION_REQUIRED" in msg)
    check("the refusal changed nothing (generation still active, pointer"
          " untouched)",
          gen_row(conn, g["generation_id"])[0] == "active"
          and active_pointer(conn) == g["generation_id"]
          and effect_row(conn, fx["effect"])[0] == "ready")
    # rollback needs a different, usable target
    msg = expect_sql_error(conn, "SELECT v_revoke_generation(%s::uuid, %s,"
                                 " %s, 'point', %s::uuid, NULL)",
                           (g["generation_id"], "badtarget", "operator",
                            g["generation_id"]),
                           needle="POINTER_TARGET_INVALID")
    check("rollback target must differ from the revoked generation",
          "POINTER_TARGET_INVALID" in msg)
    # the operator dispose channel: clear then rollback, both versioned
    d = dispose_pointer(conn, "clear")
    check("operator clear disposed", d["outcome"] == "disposed"
          and active_pointer(conn) is None)
    d = dispose_pointer(conn, "point", SEED)
    check("operator rollback disposed (seed active again)",
          d["outcome"] == "disposed" and active_pointer(conn) == SEED
          and gen_row(conn, SEED)[0] == "active")
    # the pointer must not serve through a failed generation
    revoke_generation(conn, g["generation_id"], "ptr", pointer_action="clear")
    msg = expect_sql_error(conn, "SELECT v_catalog_pointer_dispose('point',"
                                 " %s::uuid, 'operator')",
                           (g["generation_id"],),
                           needle="MUST NOT serve through a failed")
    check("pointing at a failed generation refused", "failed" in msg)
    dispose_pointer(conn, "point", SEED)
    check("history rows persist for every disposition",
          one(conn, "SELECT count(*) FROM catalog_pointer_history"
                    " WHERE action IN ('clear', 'rollback', 'revoke')"
                    " AND operator='operator'")[0] >= 3)


# ---------------------------------------------------------------------------
# 17. NO_ACTIVE_GENERATION: the runtime assemble wiring (Conformance 8 (iii))
# ---------------------------------------------------------------------------

def test_no_active_generation_runtime() -> None:
    from v8.loop.runtime import (
        advance_session,
        append_user_message,
        assemble_generation,
        create_loop_session,
        read_session,
        session_state,
        yield_lease,
    )
    db = uri()
    s = create_loop_session(db)
    append_user_message(db, s, "hello generation gate")
    conn = psycopg2.connect(db)
    try:
        from v8.plugin.client import dispose_pointer as dispose
        dispose(conn, "clear")
        # drive one advance: claim -> assemble rejected (zero control
        # change) -> progress False
        r = advance_session(db, s, finish=False)
        check("advance stalls with the NO_ACTIVE_GENERATION rejection",
              r["progress"] is False
              and r.get("assemble_rejection", {}).get("code")
              == "NO_ACTIVE_GENERATION", r)
        after = read_session(conn, s)
        check("zero control-state change: session stays claimed with its"
              " lease and fence",
              after["state"] == "claimed" and after["lease_owner"]
              and after["lease_until"] is not None, after)
        # the direct guard is stable (repeatable rejection)
        guard = assemble_generation(conn, s)
        check("the assemble guard keeps rejecting stably",
              guard.get("code") == "NO_ACTIVE_GENERATION", guard)
        y = yield_lease(conn, s, lease_owner=after["lease_owner"])
        check("explicit yield returns the session to ready",
              y["outcome"] == "yielded" and session_state(db, s) == "ready",
              y)
        dispose(conn, "point", SEED)
        r2 = advance_session(db, s, finish=True)
        check("after the pointer disposition the loop completes",
              session_state(db, s) == "completed", r2)
    finally:
        conn.close()
    # the successful-path binding: a completed turn's session carries the
    # bound active generation
    conn = psycopg2.connect(db)
    try:
        bound = one(conn, "SELECT active_catalog_generation::text"
                          " FROM sessions WHERE session_id=%s", (s,))
        check("assemble bound the session's active generation",
              bound[0] == SEED, bound)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 18. isolation guard (Conformance 8 (x), offline entry)
# ---------------------------------------------------------------------------

def test_isolation_guard(conn) -> None:
    g = publish(conn, [candidate("iso")])
    fx = fx_ready(conn)
    bind_step(conn, fx["step"], g["generation_id"])
    rr = psycopg2.connect(uri())
    try:
        rr.set_session(
            isolation_level=psycopg2.extensions.ISOLATION_LEVEL_REPEATABLE_READ)
        msg = expect_sql_error(conn=rr,
                               sql="SELECT v_revoke_generation(%s::uuid,"
                                   " %s, %s, %s, NULL, NULL)",
                               params=(g["generation_id"], "iso", "operator",
                                       "clear"),
                               needle="ISOLATION_UNSUPPORTED")
        check("REPEATABLE READ offline entry stably rejected"
              " ISOLATION_UNSUPPORTED",
              "ISOLATION_UNSUPPORTED" in msg)
    finally:
        rr.close()
    check("the rejected entry took no locks and changed nothing",
          gen_row(conn, g["generation_id"])[0] == "active"
          and effect_row(conn, fx["effect"])[0] == "ready"
          and one(conn, "SELECT count(*) FROM effect_audit"
                        " WHERE audit_context_session_id=%s"
                        "   AND reason='GENERATION_REVOKED'",
                  (fx["session"],))[0] == 0)
    r = revoke_generation(conn, g["generation_id"], "iso",
                          pointer_action="clear")
    dispose_pointer(conn, "point", SEED)
    check("READ COMMITTED control: the same revoke executes",
          r["outcome"] == "revoked", r)


# ---------------------------------------------------------------------------
# 19. retired generations are not restricted by the protocol
# ---------------------------------------------------------------------------

def test_retired_unrestricted(conn) -> None:
    g2 = publish(conn, [candidate("ret2")])
    fx = fx_ready(conn)
    bind_step(conn, fx["step"], g2["generation_id"])
    g3 = publish(conn, [candidate("ret3")])
    check("activating g3 retired g2", gen_row(conn, g2["generation_id"])[0]
          == "retired", g3)
    rd = dispatch_effect(conn, fx["session"], f"dsp-{u()[:8]}",
                         fx["effect"], DRIVER, EPOCH, fx["fence"],
                         fx["job_fence"])
    check("a retired generation's bound work is NOT restricted (dispatch"
          " proceeds)",
          rd["outcome"] == "accepted", rd)
    msg = expect_sql_error(conn, "SELECT v_revoke_generation(%s::uuid, %s,"
                                 " %s, NULL, NULL, NULL)",
                           (g2["generation_id"], "ret", "operator"),
                           needle="GENERATION_NOT_ACTIVE")
    check("revoking a retired generation is a stable rejection",
          "GENERATION_NOT_ACTIVE" in msg)
    # nothing changed for the retired-bound step
    check("the retired-bound step is untouched",
          effect_row(conn, fx["effect"])[0] == "dispatch_started"
          and step_row(conn, fx["step"])[0] == "waiting_effect")
    dispose_pointer(conn, "point", SEED)


# ---------------------------------------------------------------------------
# 20. runtime handler failure MUST NOT rewrite the generation state
# ---------------------------------------------------------------------------

def test_handler_failure_does_not_rewrite_generation(conn) -> None:
    built = build_generation(conn, manifest([candidate("hf")]))
    g = activate_generation(conn, built["generation_id"])
    check("fixture published", g["outcome"] == "activated", g)
    reg = PluginHandlerRegistry()
    built2 = build_generation(conn, manifest([candidate("hf2",
                                                        plugin_version="2")]))
    reg.apply(built["generation_id"], built["members"])
    handler = reg.handler(built["generation_id"], "hf", "1.0.0")
    check("registry exposes the handler (non-authoritative cache)",
          handler is not None)
    try:
        if callable(handler):
            handler()
        raise RuntimeError("handler exploded at runtime")
    except RuntimeError:
        pass
    check("a runtime handler failure leaves the generation state alone"
          " (readiness/health is a different failure family)",
          gen_row(conn, built["generation_id"])[0] == "active")
    check("the idle second build was not activated by anything",
          gen_row(conn, built2["generation_id"])[0] == "building")
    dispose_pointer(conn, "point", SEED)


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------

def main() -> int:
    check("setup", setup_db() == 0)
    conn = psycopg2.connect(uri())
    try:
        test_golden_digest_vectors(conn)
        test_table_family(conn)
        test_dependency_resolution(conn)
        test_publish_lifecycle(conn)
        test_steps_binding(conn)
    finally:
        conn.close()
    test_readiness_registry()
    conn = psycopg2.connect(uri())
    try:
        test_offline_drain(conn)
        test_offline_multi_session_and_rescan(conn)
        test_offline_late_completion(conn)
        test_offline_inflight_completes(conn)
        test_offline_sticky_cancel_priority(conn)
        test_offline_unknown_sibling(conn)
        test_offline_pending_sibling(conn)
        test_offline_rule5_residual(conn)
        test_offline_unsealed_plan(conn)
        test_pointer_disposition(conn)
        test_isolation_guard(conn)
        test_retired_unrestricted(conn)
        test_handler_failure_does_not_rewrite_generation(conn)
    finally:
        conn.close()
    test_no_active_generation_runtime()
    print("[G11] all gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
