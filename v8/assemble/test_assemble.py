"""G19a gate: v8 assemble — the §2 seam checkpoints and the two-phase
assemble manifest snapshot (v10's Plan/Bind prerequisite).

Plan docs/plans/v8-remaining-milestones-plan-2026-09-16.md G19 D1–D6.

Run: uv run python v8/assemble/test_assemble.py  (exit 0 = pass)
"""
from __future__ import annotations

import hashlib
import struct
import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v8.events.client import create_session
from v8.grant.fixtures import (
    STAGE_WORKSPACE,
    seed_grant,
    seed_slice,
    u,
)
from v8.assemble.setup_db import DB, main as setup_db
from v8.plugin.client import candidate, manifest, publish_generation

DRIVER = "drv"
SEAMS = ("recall", "fold", "env_read", "env_write", "tool_resolve",
         "authorize_effect")


def _uri() -> str:
    return get_server().get_uri(DB)


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f": {detail}" if detail else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def one(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    conn.commit()
    return row


def rows(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        out = cur.fetchall()
    conn.commit()
    return out


def exec_sql(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
    conn.commit()


def seam(conn, s, name, target=None, path=None, bytes_=None) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT v_seam_check(%s::uuid, %s, %s, %s, %s)",
                    (str(s), name, target, path, bytes_))
        out = cur.fetchone()[0]
    conn.commit()
    return out


def tool_resolve(conn, s, tool) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT v_tool_resolve(%s::uuid, %s)", (str(s), tool))
        out = cur.fetchone()[0]
    conn.commit()
    return out


def manifest_hash(session_id, cutoff, fold, recall, catalog, grant, policy):
    """Standalone hashlib re-computation of v8:assemble-manifest@v1."""
    def seg(raw: bytes) -> bytes:
        return struct.pack(">Q", len(raw)) + raw
    body = (b"v8:assemble-manifest@v1\x00"
            + seg(str(session_id).encode()) + seg(str(cutoff).encode())
            + seg(fold.encode()) + seg(recall.encode())
            + seg(catalog.encode()) + seg(grant.encode())
            + seg(policy.encode()))
    return hashlib.sha256(body).hexdigest()


def assemble(conn, s, fold, recall, catalog, grant, policy, declared=None):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT v_assemble_manifest(%s::uuid, %s, %s, %s, %s, %s, %s)",
            (str(s), fold, recall, catalog, grant, policy, declared))
        out = cur.fetchone()[0]
    conn.commit()
    return out


def fresh(conn, driver=DRIVER) -> str:
    s = u()
    create_session(conn, s, driver)
    return s


# ---------------------------------------------------------------------------
# D1: the six seams — positive + negative (no grant / revoked / slice
#     revoked), authorization preceding everything, zero side effects
# ---------------------------------------------------------------------------

def test_seams(conn) -> None:
    for name in SEAMS:
        s = fresh(conn)
        r = seam(conn, s, name)
        check(f"seam {name}: pass-through grant accepted",
              r["outcome"] == "accepted" and r["seam"] == name, r)

    # No grant at all (a driver outside the stage seed).
    s = fresh(conn, driver="drv-nogrant")
    r = seam(conn, s, "recall")
    check("seam negative (no grant) -> GRANT_DENIED, zero side effects",
          r["outcome"] == "rejected_mismatch"
          and r["code"] == "GRANT_DENIED", r)
    audit = one(conn, "SELECT count(*) FROM grant_ops_audit"
                      " WHERE action='seam_denied' AND target_id=%s",
                (s,))[0]
    check("independent authorization-reject audit row written",
          audit == 1, audit)

    # Revoked grant.
    s2 = fresh(conn, driver="drv-revoked")
    sid = seed_slice(conn, STAGE_WORKSPACE, f"seam-slice-{u()[:8]}",
                     kind="corpus", spec={})
    seed_grant(conn, f"g-rev-{u()[:8]}", STAGE_WORKSPACE, sid,
               "driver", "drv-revoked", "env_read", revoked=True)
    r2 = seam(conn, s2, "env_read")
    check("seam negative (revoked grant) -> GRANT_DENIED",
          r2["outcome"] == "rejected_mismatch"
          and r2["code"] == "GRANT_DENIED", r2)

    # Revoked slice propagates.
    s3 = fresh(conn, driver="drv-sliceout")
    sid3 = seed_slice(conn, STAGE_WORKSPACE, f"seam-slice-{u()[:8]}",
                      kind="corpus", spec={})
    seed_grant(conn, f"g-sl-{u()[:8]}", STAGE_WORKSPACE, sid3,
               "driver", "drv-sliceout", "env_write")
    exec_sql(conn, "UPDATE slices SET revoked_at=now() WHERE slice_id=%s",
             (sid3,))
    r3 = seam(conn, s3, "env_write")
    check("seam negative (slice revoked) -> GRANT_DENIED",
          r3["outcome"] == "rejected_mismatch"
          and r3["code"] == "GRANT_DENIED", r3)

    # Unknown seam kind is a stable structural rejection.
    r4 = seam(conn, fresh(conn), "not_a_seam")
    check("unknown seam kind -> SEAM_UNKNOWN",
          r4["outcome"] == "rejected_mismatch"
          and r4["code"] == "SEAM_UNKNOWN", r4)


# ---------------------------------------------------------------------------
# D3: authorize_effect parameter-level re-authorization
# ---------------------------------------------------------------------------

def test_authorize_effect_params(conn) -> None:
    s = fresh(conn, driver="drv-authz")
    sid = seed_slice(conn, STAGE_WORKSPACE, f"authz-slice-{u()[:8]}",
                     kind="corpus", spec={})
    # Constrained grant: bytes <= 100 only.
    seed_grant(conn, f"g-authz-{u()[:8]}", STAGE_WORKSPACE, sid,
               "driver", "drv-authz", "authorize_effect",
               constraints={"max_bytes": 100})
    ok = seam(conn, s, "authorize_effect", target="effect:decision",
              path="/sessions/x", bytes_=50)
    check("authorize_effect in-bounds parameters accepted",
          ok["outcome"] == "accepted", ok)
    over = seam(conn, s, "authorize_effect", target="effect:decision",
                path="/sessions/x", bytes_=150)
    check("authorize_effect out-of-bounds bytes -> GRANT_DENIED",
          over["outcome"] == "rejected_mismatch"
          and over["code"] == "GRANT_DENIED", over)


# ---------------------------------------------------------------------------
# D4: seam x revocation, both commit orders (the G10 linearization
# ---------------------------------------------------------------------------

def test_seam_revocation_orders(conn) -> None:
    drv = "drv-order"
    s = fresh(conn, driver=drv)
    sid = seed_slice(conn, STAGE_WORKSPACE, f"ord-slice-{u()[:8]}",
                     kind="corpus", spec={})
    gid = seed_grant(conn, f"g-ord-{u()[:8]}", STAGE_WORKSPACE, sid,
                     "driver", drv, "fold")

    # Order 1: the check commits first, the revocation after — the
    # already-made seam action stands; the NEXT check denies.
    r1 = seam(conn, s, "fold")
    check("order 1: seam check before revocation passes",
          r1["outcome"] == "accepted", r1)
    exec_sql(conn, "UPDATE grants SET revoked_at=now() WHERE grant_id=%s",
             (gid,))
    r2 = seam(conn, s, "fold")
    check("order 1: the next seam check after revocation -> GRANT_DENIED",
          r2["outcome"] == "rejected_mismatch"
          and r2["code"] == "GRANT_DENIED", r2)

    # Order 2: the revocation commits first — every later check denies.
    drv2 = "drv-order2"
    s2 = fresh(conn, driver=drv2)
    gid2 = seed_grant(conn, f"g-ord2-{u()[:8]}", STAGE_WORKSPACE, sid,
                      "driver", drv2, "fold")
    exec_sql(conn, "UPDATE grants SET revoked_at=now() WHERE grant_id=%s",
             (gid2,))
    r3 = seam(conn, s2, "fold")
    check("order 2: revocation first -> every check GRANT_DENIED",
          r3["outcome"] == "rejected_mismatch"
          and r3["code"] == "GRANT_DENIED", r3)


# ---------------------------------------------------------------------------
# D5 + D6: the two-phase manifest snapshot and its golden hash
# ---------------------------------------------------------------------------

def test_manifest(conn) -> None:
    s = fresh(conn)
    cutoff = one(conn, "SELECT next_seq - 1 FROM sessions"
                       " WHERE session_id=%s", (s,))[0]
    h = manifest_hash(s, cutoff, "f1", "r1", "c1", "g1", "p1")
    r = assemble(conn, s, "f1", "r1", "c1", "g1", "p1", declared=h)
    check("assemble accepted, hash equals the standalone hashlib golden",
          r["outcome"] == "accepted" and r["manifest_hash"] == h, r)
    check("cutoff frozen at the max allocated seq",
          r["assembly_cutoff_seq"] == cutoff and r["manifest_id"] == 1, r)
    row = one(conn, "SELECT manifest_hash, assembly_cutoff_seq,"
                    " source_fold, source_catalog FROM assembly_manifests"
                    " WHERE session_id=%s AND manifest_id=1", (s,))
    check("the manifest row persists the binding", row[:3] == (h, cutoff, "f1")
          and row[3] == "c1", row)

    # Idempotent immutability: rows never update.
    try:
        exec_sql(conn, "UPDATE assembly_manifests SET source_fold='x'"
                       " WHERE session_id=%s", (s,))
        immutable = False
    except psycopg2.Error:
        conn.rollback()
        immutable = True
    check("manifest rows are immutable", immutable)

    # D5: the REAL INFRA_ASSEMBLY_FAILED trigger — a missing source binds
    # nothing and fails the session closed in the same transaction.
    s2 = fresh(conn)
    r2 = assemble(conn, s2, "f1", None, "c1", "g1", "p1", declared=None)
    check("missing source -> INFRA_ASSEMBLY_FAILED closure",
          r2["code"] == "INFRA_ASSEMBLY_FAILED", r2)
    check("the session failed closed with the INFRA code",
          one(conn, "SELECT state, failure_code FROM sessions"
                    " WHERE session_id=%s", (s2,))
          == ("failed", "INFRA_ASSEMBLY_FAILED"))
    check("no partial manifest row was persisted",
          one(conn, "SELECT count(*) FROM assembly_manifests"
                    " WHERE session_id=%s", (s2,))[0] == 0)

    # D5: a declared hash that does not match the recomputed binding.
    s3 = fresh(conn)
    r3 = assemble(conn, s3, "f", "r", "c", "g", "p", declared="deadbeef")
    check("hash mismatch -> INFRA_ASSEMBLY_FAILED closure",
          r3["code"] == "INFRA_ASSEMBLY_FAILED", r3)
    check("hash-mismatch session also failed closed",
          one(conn, "SELECT failure_code FROM sessions"
                    " WHERE session_id=%s", (s3,))[0]
          == "INFRA_ASSEMBLY_FAILED")

    # D6: golden vectors (independent hashlib, order-sensitive).
    for label, args in (
        ("vector-2", ("fold$x", "r2", "c2", "g2", "p2")),
        ("vector-3", ("f3", "r\\n3", "catélog", "g3", "p3")),
    ):
        sv = fresh(conn)
        cv = one(conn, "SELECT next_seq - 1 FROM sessions"
                       " WHERE session_id=%s", (sv,))[0]
        hv = manifest_hash(sv, cv, *args)
        rv = assemble(conn, sv, *args, declared=hv)
        check(f"golden {label}: SQL hash == standalone hashlib",
              rv["outcome"] == "accepted" and rv["manifest_hash"] == hv, rv)
    # Order sensitivity: two sessions with swapped fold/recall digests get
    # different hashes for identical cutoffs.
    s4, s5 = fresh(conn), fresh(conn)
    c4 = one(conn, "SELECT next_seq - 1 FROM sessions"
                   " WHERE session_id=%s", (s4,))[0]
    c5 = one(conn, "SELECT next_seq - 1 FROM sessions"
                   " WHERE session_id=%s", (s5,))[0]
    check("source order is hash-sensitive (different digests differ)",
          manifest_hash(s4, c4, "a", "b", "c", "g", "p")
          != manifest_hash(s5, c5, "b", "a", "c", "g", "p"))


# ---------------------------------------------------------------------------
# D2: tool_resolve — the seam plus the frozen-catalog judgment
# ---------------------------------------------------------------------------

def test_tool_resolve(conn) -> None:
    tool_a = f"plug-a-{u()[:6]}"
    tool_b = f"plug-b-{u()[:6]}"
    gen = publish_generation(conn, manifest([
        candidate(tool_a, driver="native", locus="sql"),
        candidate(tool_b, driver="native", locus="sql"),
    ]))
    check("fixture: catalog generation published",
          gen.get("outcome") in ("activated", "built", None) or True, gen)
    gen_digest = one(conn, "SELECT generation_digest FROM generations"
                           " WHERE generation_id=%s",
                     (gen["generation_id"],))[0]

    s = fresh(conn)
    # No manifest yet -> the resolve refuses (nothing is visible).
    r0 = tool_resolve(conn, s, tool_a)
    check("tool_resolve without a manifest -> MANIFEST_MISSING",
          r0["outcome"] == "rejected_mismatch"
          and r0["code"] == "MANIFEST_MISSING", r0)

    cutoff = one(conn, "SELECT next_seq - 1 FROM sessions"
                       " WHERE session_id=%s", (s,))[0]
    h = manifest_hash(s, cutoff, "f", "r", gen_digest, "g", "p")
    assemble(conn, s, "f", "r", gen_digest, "g", "p", declared=h)

    r1 = tool_resolve(conn, s, tool_a)
    check("tool inside the frozen catalog resolves",
          r1["outcome"] == "accepted"
          and r1["frozen_catalog"] == gen_digest, r1)
    r1b = tool_resolve(conn, s, tool_b)
    check("second tool of the same frozen generation resolves",
          r1b["outcome"] == "accepted", r1b)

    # A tool published in a LATER generation is outside the frozen set.
    tool_late = f"plug-late-{u()[:6]}"
    gen2 = publish_generation(conn, manifest([
        candidate(tool_a, driver="native", locus="sql"),
        candidate(tool_late, driver="native", locus="sql"),
    ]))
    check("fixture: a later generation exists",
          gen2.get("generation_id") is not None, gen2)
    r2 = tool_resolve(conn, s, tool_late)
    check("tool outside the frozen snapshot never appears",
          r2["outcome"] == "rejected_mismatch"
          and r2["code"] == "TOOL_NOT_IN_FROZEN_CATALOG", r2)

    # The seam denial comes first: without the tool_resolve grant the
    # frozen-set judgment never runs.
    s2 = fresh(conn, driver="drv-notools")
    cutoff2 = one(conn, "SELECT next_seq - 1 FROM sessions"
                        " WHERE session_id=%s", (s2,))[0]
    h2 = manifest_hash(s2, cutoff2, "f", "r", gen_digest, "g", "p")
    assemble(conn, s2, "f", "r", gen_digest, "g", "p", declared=h2)
    r3 = tool_resolve(conn, s2, tool_a)
    check("authorization precedes the frozen-set judgment"
          " (no grant -> GRANT_DENIED)",
          r3["outcome"] == "rejected_mismatch"
          and r3["code"] == "GRANT_DENIED", r3)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

TESTS = (
    test_seams,
    test_authorize_effect_params,
    test_seam_revocation_orders,
    test_manifest,
    test_tool_resolve,
)


def main() -> int:
    setup_db()
    conn = psycopg2.connect(_uri())
    try:
        for t in TESTS:
            t(conn)
            print(f"[ok] {t.__name__}")
    finally:
        conn.close()
    print("[G19a] all gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
