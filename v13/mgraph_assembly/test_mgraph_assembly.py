"""B2 gate (group J): mgraph assembly wiring, stage 16.

W1 J1-J3: identity & validation upgrade —
  J1 twelve-key token with mgraph_ver (narrow digest, C2): key-set string,
      64hex shape, generation-0 determinism, generation bump moves the hash,
      policy-only bump moves the hash, V3009 when the active row vanishes.
  J2 manifest v4: settle -> manifest_version=4, 12-key top level (no
      memory_graph section yet), validate passes, hand-forged version=3
      rejected, exact_replay body equals landed inline minus the replay
      block, two same-snapshot assembles byte-equal.
  J3 identity literals: prefix_identity pins manifest_version 4 (not 3),
      artifact prefix_identity equals the on-the-spot call, the new stage
      file redefines exactly the five adjudicated functions (zero table
      changes, zero function drops), and the first 15 SQL files are
      byte-frozen against plan start.

W2 J4-J7: section injection —
  J4 section shape & est: one memory_graph section from a stopped walk
      (LastResort/Session/blob ref/memory_inject applied), est inequality,
      refresh belt lands the blob, render body carries node text, t_used
      untouched (B-E2).
  J5 provenance: seven-key closed set over four fixtures (user-only,
      llm-only, mixed same-body, consolidation), evidence still three-key,
      rows ordered score DESC / hash ASC.
  J6 absence & filtering: no_walk, disabled (zero asks), degraded (one
      audit event, no self-excitation, history still present),
      kinds_disabled, retrieval cap zero (section dropped, settle still
      accepted, belt silent).
  J7 isolation kept (F7 spirit): recall candidates disjoint from graph
      nodes, needed_judgments without mem_, econ_ver untouched, prefix
      byte freeze re-asserted.

W3 J8-J9: worker driver & ACL (see J4/J5 blocks in main).

Run: uv run python v13/mgraph_assembly/test_mgraph_assembly.py
     (exit 0 = pass)
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import threading
import time
import uuid
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
V13 = AGENT_ROOT / "v13"
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v13.mgraph_assembly.setup_db import DB, main as setup_db
from v13.load import SQL_LOAD_ORDER

SQL_FILE = ROOT / "v13_mgraph_assembly.sql"
HEX64 = re.compile(r"^[0-9a-f]{64}$")

TWELVE_KEYS = ("asm_ver,corpus,dec,econ_ver,gen_ver,goal,ident_ver,jdef_ver,"
               "mgraph_ver,recall_ver,sem,tools_rev")
TOP_KEYS = ("economics,judgments,manifest_version,policy,prefix_identity,"
            "query_side,render,replay,required_revision,sections,session_id,"
            "turn_no")
FIVE_OR_REPLACE = {
    "v13_context_required", "v13_prefix_identity", "v13_assemble_manifest",
    "v13_manifest_validate", "v13_refresh_context",
}

# Byte freeze of the first 15 SQL files vs plan start (J3/J7; F7 spirit:
# the mgraph files are in this list). sha256 prefixes, hex.
PREFIX_FREEZE = {
    "v13_core.sql": "0514533c11a1394e",
    "v13_resolve.sql": "badaa6e8c925b1d0",
    "advance.sql": "e7c40c006c19228d",
    "v13_twophase.sql": "978ea40d42a37d13",
    "v13_envelope.sql": "d9286ceb6c4fff70",
    "v13_manifest.sql": "2620ea4c365985a2",
    "v13_chunks.sql": "6b4963c07bbc2e54",
    "v13_recall.sql": "982ea218015de48b",
    "v13_characterize.sql": "be1562ab2f2cb813",
    "v13_filter.sql": "416aadea57501588",
    "v13_memory.sql": "0fdd32d219f11f47",
    "v13_economy.sql": "494091769d27a93a",
    "v13_summary.sql": "6486017b51e3cba3",
    "v13_periphery.sql": "dbfa6ab032045933",
    "v13_mgraph.sql": "450bc7e4fb581148",
}


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    extra = f": {detail}" if detail and (not condition or len(str(detail)) < 220) else ""
    print(f"[{mark}] {label}{extra}")
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def u() -> str:
    return str(uuid.uuid4())


def fails_with(cur, sql, params, needle, label, pgcode=None):
    cur.execute("SAVEPOINT sp")
    try:
        cur.execute(sql, params)
    except psycopg2.Error as exc:
        msg_ok = needle.lower() in str(exc).lower() if needle else True
        code_ok = exc.pgcode == pgcode if pgcode else True
        check(label, msg_ok and code_ok,
              f"pgcode={exc.pgcode} {str(exc).splitlines()[0]}")
        cur.execute("ROLLBACK TO SAVEPOINT sp")
        return exc
    cur.execute("ROLLBACK TO SAVEPOINT sp")
    raise AssertionError(
        f"{label}: expected failure containing {needle!r} pgcode={pgcode!r}")


def append(cur, sid, etype, payload):
    cur.execute(
        "SELECT v13_append_event(%s, %s, %s, %s::jsonb)",
        (sid, u(), etype, json.dumps(payload)))
    return cur.fetchone()[0]


def refresh_n(cur, sid, goal_hash):
    """bump cycle (turn/route) + enqueue + claim + settle one
    context_refresh effect; returns (outcome, manifest, effect_id)."""
    append(cur, sid, "turn/route", {"action": "refresh"})
    cur.execute(
        "SELECT v13_enqueue_effect(%s,'context_refresh',"
        "jsonb_build_object('goal_hash',%s))", (sid, goal_hash))
    eff = cur.fetchone()[0]
    cur.execute("SELECT v13_claim('t')")
    cl = cur.fetchone()[0]
    cur.execute("SELECT v13_refresh_context(%s,%s,%s)",
                (eff, cl["attempt_no"], cl["fence"]))
    out = cur.fetchone()[0]
    cur.execute(
        "SELECT a.inline FROM artifacts a JOIN sessions s "
        "ON s.context_active_artifact=a.artifact_id WHERE s.session_id=%s",
        (sid,))
    return out, cur.fetchone()[0], eff


def bump_policy(cur, name, value):
    """append new version + flip active (append-only ritual); returns
    (new_version). Caller commits/rolls back."""
    cur.execute(
        "SELECT coalesce(max(version),0)+1 FROM v13_policies WHERE name=%s",
        (name,))
    ver = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO v13_policies (name, version, value, active) "
        "VALUES (%s,%s,%s::jsonb,false)", (name, ver, json.dumps(value)))
    cur.execute("UPDATE v13_policies SET active=false WHERE name=%s AND active",
                (name,))
    cur.execute("UPDATE v13_policies SET active=true WHERE name=%s AND version=%s",
                (name, ver))
    return ver


def restore_policy(cur, name, version):
    cur.execute("UPDATE v13_policies SET active=false WHERE name=%s AND active",
                (name,))
    cur.execute("UPDATE v13_policies SET active=true WHERE name=%s AND version=%s",
                (name, version))


def seed_node(cur, sid, body, origin="episodic", hashes=None):
    cur.execute("SELECT v13_body_hash(%s)", (body,))
    bh = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO memory_nodes (session_id, content_hash, body, origin,"
        " source_hashes, source_at, builder_version)"
        " VALUES (%s,%s,%s,%s,%s,%s::timestamptz,1)",
        (sid, bh, body, origin, hashes or [bh], "2026-09-24 10:00:00+00"))
    return bh


def seed_walk(cur, sid, frontier, gen=0, stop_reason="evidence"):
    """Seed a stopped walk matching (query, generation, active pver)."""
    cur.execute("SELECT v13_body_hash(v13_mgraph_turn_query(%s))", (sid,))
    qh = cur.fetchone()[0]
    cur.execute(
        "SELECT version FROM v13_policies WHERE name='mgraph' AND active")
    pver = cur.fetchone()[0]
    cur.execute("SELECT v13_mgraph_walk_id(%s,%s,%s,%s)", (sid, qh, gen, pver))
    wid = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO memory_walks (walk_id, session_id, query_hash,"
        " mgraph_generation, policy_version, frontier, budgets, calls_used,"
        " nodes_used, edges_used, depth, stop_reason, status)"
        " VALUES (%s,%s,%s,%s,%s,%s::jsonb,'{}'::jsonb,0,0,0,0,%s,'stopped')",
        (wid, sid, qh, gen, pver,
         json.dumps([{"content_hash": h, "score": s} for h, s in frontier]),
         stop_reason))
    return wid


def mem_section(manifest):
    for s in manifest["sections"]:
        if s["kind"] == "memory_graph":
            return s
    return None


def new_session(cur, last_text=None):
    sid = u()
    cur.execute("INSERT INTO sessions (session_id) VALUES (%s)", (sid,))
    if last_text is not None:
        append(cur, sid, "user/message", {"text": last_text})
    return sid


def chunk_of(cur, sid, body, etype):
    """append event + project transcript chunk; returns (seq, body_hash)."""
    seq = append(cur, sid, etype, {"text": body})
    cur.execute("SELECT v13_body_hash(%s)", (body,))
    bh = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO transcript_chunks (session_id, seq_from, seq_to, body,"
        " content_hash) VALUES (%s,%s,%s,%s,%s)", (sid, seq, seq, body, bh))
    return seq, bh


def main() -> int:
    setup_db()
    server = get_server()
    conn = psycopg2.connect(server.get_uri(DB))
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute("RESET ROLE")
    cur.execute("SET search_path TO public, pg_catalog")

    # ================= J1 twelve-key token (OQ-C=C2 narrow) ==============
    sid_j1 = u()
    cur.execute("INSERT INTO sessions (session_id) VALUES (%s)", (sid_j1,))
    cur.execute(
        "SELECT string_agg(k, ',' ORDER BY k) FROM "
        "jsonb_object_keys(v13_context_required(%s)) k", (sid_j1,))
    check("J1: context_required key set is the twelve-key string",
          cur.fetchone()[0] == TWELVE_KEYS)
    cur.execute("SELECT v13_context_required(%s)->>'mgraph_ver'", (sid_j1,))
    mv_j1 = cur.fetchone()[0]
    check("J1: mgraph_ver is 64hex", bool(HEX64.match(mv_j1 or "")), mv_j1)
    # no meta row -> generation 0 -> deterministic digest
    cur.execute("SELECT v13_mgraph_asm_ver(%s), v13_mgraph_asm_ver(%s)",
                (sid_j1, sid_j1))
    h_a, h_b = cur.fetchone()
    check("J1: asm_ver deterministic at generation 0 (no meta row)",
          h_a == h_b and bool(HEX64.match(h_a)))
    # generation 0 -> 1 moves the hash
    cur.execute(
        "INSERT INTO v13_mgraph_meta (session_id, generation) "
        "VALUES (%s, 1)", (sid_j1,))
    cur.execute("SELECT v13_mgraph_asm_ver(%s)", (sid_j1,))
    h_gen1 = cur.fetchone()[0]
    check("J1: generation 0->1 changes mgraph_ver", h_gen1 != h_a,
          (h_a, h_gen1))
    cur.execute("ROLLBACK")
    conn.commit()
    # policy-only bump (same value, new version) moves the hash; rollback
    cur.execute("SELECT value FROM v13_policies WHERE name='mgraph' AND active")
    val = cur.fetchone()[0]
    cur.execute(
        "SELECT coalesce(max(version),0)+1 FROM v13_policies WHERE name='mgraph'")
    ver_new = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO v13_policies (name, version, value, active) "
        "VALUES ('mgraph',%s,%s::jsonb,false)", (ver_new, json.dumps(val)))
    cur.execute("UPDATE v13_policies SET active=false "
                "WHERE name='mgraph' AND active")
    cur.execute("UPDATE v13_policies SET active=true "
                "WHERE name='mgraph' AND version=%s", (ver_new,))
    cur.execute("SELECT v13_mgraph_asm_ver(%s)", (sid_j1,))
    h_pver = cur.fetchone()[0]
    check("J1: policy-only bump (generation unchanged) changes mgraph_ver",
          h_pver != h_a, (h_a, h_pver))
    cur.execute("ROLLBACK")
    conn.commit()
    cur.execute("SELECT count(*) FROM v13_policies WHERE name='mgraph'")
    check("J1: mgraph fixtures rolled back (single v2 row)",
          cur.fetchone()[0] == 1)
    # active row gone (flip false, no successor) -> V3009 (rollback after)
    cur.execute("UPDATE v13_policies SET active=false "
                "WHERE name='mgraph' AND active")
    fails_with(cur, "SELECT v13_mgraph_asm_ver(%s)", (sid_j1,),
               "no active mgraph policy",
               "J1: no active mgraph row -> V3009", pgcode="V3009")
    cur.execute("ROLLBACK")
    conn.commit()

    # ================= J2 manifest v4 + frozen replay ====================
    sid_j2 = u()
    cur.execute("INSERT INTO sessions (session_id) VALUES (%s)", (sid_j2,))
    append(cur, sid_j2, "user/message", {"text": "hello memory plane"})
    cur.execute("SELECT v13_assemble_manifest(%s)", (sid_j2,))
    m_pre = cur.fetchone()[0]
    check("J2: pre-settle assemble yields version 4 already",
          m_pre["manifest_version"] == 4)
    check("J2: pre-settle assemble carries no memory_graph section",
          all(s["kind"] != "memory_graph" for s in m_pre["sections"]),
          [s["section_id"] for s in m_pre["sections"]])
    out_j2, m_j2, _ = refresh_n(cur, sid_j2, m_pre["required_revision"]["goal"])
    check("J2: refresh settles accepted", out_j2 == "accepted", out_j2)
    check("J2: settled manifest_version = 4", m_j2["manifest_version"] == 4)
    cur.execute(
        "SELECT string_agg(k, ',' ORDER BY k) FROM "
        "jsonb_object_keys(%s::jsonb) k", (json.dumps(m_j2),))
    check("J2: top-level key set is the 12 keys (no memory_graph key)",
          cur.fetchone()[0] == TOP_KEYS)
    cur.execute("SELECT v13_manifest_validate(%s::jsonb)", (json.dumps(m_j2),))
    cur.fetchone()
    check("J2: validate accepts the settled v4 manifest", True)
    forged = dict(m_j2)
    forged["manifest_version"] = 3
    fails_with(
        cur, "SELECT v13_manifest_validate(%s::jsonb)", (json.dumps(forged),),
        "manifest", "J2: hand-forged version=3 manifest rejected",
        pgcode="V3003")
    cur.execute("SELECT context_active_artifact FROM sessions "
                "WHERE session_id=%s", (sid_j2,))
    art_j2 = cur.fetchone()[0]
    cur.execute("SELECT v13_replay(%s)", (art_j2,))
    rep_j2 = cur.fetchone()[0]
    check("J2: replay mode is exact_replay",
          rep_j2["replay"]["mode"] == "exact_replay")
    check("J2: replay names its source artifact",
          rep_j2["replay"]["source_artifact"] == art_j2)
    rep_body = {k: v for k, v in rep_j2.items() if k != "replay"}
    man_body = {k: v for k, v in m_j2.items() if k != "replay"}
    check("J2: replay body equals landed inline minus the replay block",
          rep_body == man_body)
    cur.execute("SELECT v13_assemble_manifest(%s)::text", (sid_j2,))
    txt_a = cur.fetchone()[0]
    cur.execute("SELECT v13_assemble_manifest(%s)::text", (sid_j2,))
    txt_b = cur.fetchone()[0]
    check("J2: same-snapshot assembles byte-equal (::text)",
          txt_a == txt_b)
    conn.commit()  # keep the fixture: J3 compares on-the-spot identity


    # ================= J3 identity literal + closed sets + freeze =========
    cur.execute(
        "SELECT pg_get_functiondef('v13_prefix_identity(uuid)'::regprocedure)")
    fdef_j3 = cur.fetchone()[0]
    check("J3: prefix_identity pins manifest_version 4",
          "'manifest_version', 4" in fdef_j3)
    check("J3: prefix_identity no longer pins manifest_version 3",
          "'manifest_version', 3" not in fdef_j3)
    cur.execute("SELECT v13_prefix_identity(%s)", (sid_j2,))
    pid_now = cur.fetchone()[0]
    check("J3: artifact prefix_identity equals on-the-spot call",
          m_j2["prefix_identity"] == pid_now)

    src_j3 = SQL_FILE.read_text(encoding="utf-8")
    oras = set(re.findall(r"CREATE OR REPLACE FUNCTION (\w+)", src_j3))
    check("J3: new file redefines exactly the five adjudicated functions",
          oras == FIVE_OR_REPLACE, oras)
    check("J3: new file has zero ALTER TABLE",
          not re.findall(r"ALTER TABLE (\w+)", src_j3),
          re.findall(r"ALTER TABLE (\w+)", src_j3))
    check("J3: new file drops no function",
          "DROP FUNCTION" not in src_j3)
    check("J3: v13_lock_key mgraph-build advisory before assemble in refresh",
          src_j3.index("pg_advisory_xact_lock(public.v13_lock_key(v_sid, "
                       "'mgraph-build'))")
          < src_j3.index("v_manifest := public.v13_assemble_manifest(v_sid, "
                         "NULL);"))
    # first 15 SQL files byte-frozen vs plan start
    check("J3: load order has 16 files", len(SQL_LOAD_ORDER) == 16)
    for p in SQL_LOAD_ORDER[:15]:
        h = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        check(f"J3: prefix byte freeze {p.name}",
              PREFIX_FREEZE.get(p.name) == h,
              (p.name, PREFIX_FREEZE.get(p.name), h))

    # ================= J4 section shape & est (W2) ======================
    cur.execute("RESET ROLE")
    cur.execute("SET search_path TO public, pg_catalog")
    cur.execute(
        "SELECT version, value FROM v13_policies WHERE name='mgraph' AND active")
    mgraph_seed_ver, mgraph_seed_value = cur.fetchone()
    cur.execute(
        "SELECT version, value FROM v13_policies "
        "WHERE name='assemble_manifest' AND active")
    asm_seed_ver, asm_seed_value = cur.fetchone()
    bump_policy(cur, "mgraph", dict(mgraph_seed_value, read_enabled=True))
    conn.commit()

    sid_j4 = new_session(cur, "the payment service went live on Friday")
    bh_a = seed_node(cur, sid_j4,
                     "Alice deployed the payment service on Friday morning.")
    bh_b = seed_node(cur, sid_j4,
                     "Bob prefers morning deploys for payments.")
    cur.execute("SELECT v13_assemble_manifest(%s)", (sid_j4,))
    m_pre_j4 = cur.fetchone()[0]
    check("J4: pre-walk assemble has no memory_graph section",
          mem_section(m_pre_j4) is None)
    t_used_0 = m_pre_j4["economics"]["pressure"]["t_used"]
    seed_walk(cur, sid_j4, [(bh_a, 0.55), (bh_b, 0.9)])
    conn.commit()
    cur.execute("SELECT v13_assemble_manifest(%s)", (sid_j4,))
    m_j4 = cur.fetchone()[0]
    sec_j4 = mem_section(m_j4)
    check("J4: memory_graph section present exactly once",
          sum(1 for s in m_j4["sections"] if s["kind"] == "memory_graph") == 1
          and sec_j4 is not None)
    check("J4: section_id == kind == memory_graph",
          sec_j4["section_id"] == "memory_graph"
          and sec_j4["kind"] == "memory_graph")
    check("J4: cache_scope Session / priority LastResort",
          sec_j4["cache_scope"] == "Session"
          and sec_j4["priority"] == "LastResort")
    check("J4: payload_ref is blob pinned to section hash",
          sec_j4["payload_ref"] == {"kind": "blob",
                                    "content_hash": sec_j4["content_hash"]})
    check("J4: transform applied memory_inject",
          sec_j4["transform"] == {"applied": True, "name": "memory_inject"})
    cur.execute(
        "SELECT octet_length(v13_mgraph_section_material(%s)::text),"
        " (value->>'est_bytes_per_token')::int FROM v13_policies"
        " WHERE name='assemble_manifest' AND active", (sid_j4,))
    bytes_j4, div_j4 = cur.fetchone()
    est_j4 = sec_j4["est_tokens"]
    check("J4: est inequality holds (ceil division single-source)",
          est_j4 * div_j4 >= bytes_j4 and (est_j4 - 1) * div_j4 < bytes_j4,
          (est_j4, div_j4, bytes_j4))
    t_used_1 = m_j4["economics"]["pressure"]["t_used"]
    check("J4: t_used unchanged by the memory section (B-E2)",
          t_used_0 == t_used_1, (t_used_0, t_used_1))
    cur.execute("SELECT v13_manifest_validate(%s::jsonb)",
                (json.dumps(m_j4),))
    cur.fetchone()
    check("J4: validate accepts manifest with memory section", True)
    out_j4, m_set_j4, eff_j4 = refresh_n(
        cur, sid_j4, m_j4["required_revision"]["goal"])
    check("J4: refresh settles accepted with memory section",
          out_j4 == "accepted", out_j4)
    sec_set_j4 = mem_section(m_set_j4)
    check("J4: settled manifest still carries the memory section",
          sec_set_j4 is not None
          and sec_set_j4["content_hash"] == sec_j4["content_hash"])
    cur.execute(
        "SELECT count(*) FROM artifacts WHERE produced_by=%s"
        " AND kind='context_section' AND content_hash=%s",
        (eff_j4, sec_j4["content_hash"]))
    check("J4: memory blob landed with section hash",
          cur.fetchone()[0] == 1)
    cur.execute(
        "SELECT v13_render_section_body(%s, %s::jsonb)",
        (sid_j4, json.dumps(sec_set_j4)))
    body_j4 = cur.fetchone()[0]
    check("J4: render body carries node text",
          "Alice deployed the payment service" in (body_j4 or ""))
    conn.commit()

    # ================= J5 provenance (seven-key closed set) ==============
    sid_j5 = new_session(cur)
    seq_u, h_u = chunk_of(cur, sid_j5, "I prefer morning deploys", "user/message")
    seed_node(cur, sid_j5, "I prefer morning deploys")
    cur.execute("SELECT v13_mgraph_provenance(%s,%s)", (sid_j5, h_u))
    p = cur.fetchone()[0]
    check("J5: user-only projection",
          p["origin"] == "episodic" and p["speaker"] == "user"
          and p["conflict"] is False and p["seq_count"] == 1
          and p["seq_first"] == seq_u and p["seq_last"] == seq_u, p)
    seq_l, h_l = chunk_of(cur, sid_j5, "Deploy completed at noon", "llm/message")
    seed_node(cur, sid_j5, "Deploy completed at noon")
    cur.execute("SELECT v13_mgraph_provenance(%s,%s)", (sid_j5, h_l))
    p = cur.fetchone()[0]
    check("J5: llm-only projection", p["speaker"] == "llm"
          and p["conflict"] is False and p["seq_count"] == 1, p)
    mixed = "the deploy window is Saturday nine"
    seq_m1, h_m = chunk_of(cur, sid_j5, mixed, "user/message")
    seq_m2, _ = chunk_of(cur, sid_j5, mixed, "llm/message")
    seed_node(cur, sid_j5, mixed)
    cur.execute("SELECT v13_mgraph_provenance(%s,%s)", (sid_j5, h_m))
    p = cur.fetchone()[0]
    check("J5: same-body user+llm coalesced node is mixed+conflict",
          p["speaker"] == "mixed" and p["conflict"] is True
          and p["seq_count"] == 2 and p["seq_first"] == min(seq_m1, seq_m2)
          and p["seq_last"] == max(seq_m1, seq_m2)
          and p["seq_first"] < p["seq_last"], p)
    cons_hashes = sorted([h_u, h_l])
    cur.execute("SELECT v13_mgraph_pair_digest(%s,%s)", tuple(cons_hashes))
    cons_key = cur.fetchone()[0]
    cur.execute("SELECT v13_body_hash(%s)",
                ("morning deploys and noon deploys merged",))
    h_c = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO memory_nodes (session_id, content_hash, body, origin,"
        " source_hashes, source_at, builder_version, consolidation_key)"
        " VALUES (%s,%s,%s,'consolidation',%s,%s::timestamptz,1,%s)",
        (sid_j5, h_c, "morning deploys and noon deploys merged", cons_hashes,
         "2026-09-24 10:00:00+00", cons_key))
    cur.execute("SELECT v13_mgraph_provenance(%s,%s)", (sid_j5, h_c))
    p = cur.fetchone()[0]
    check("J5: consolidation node, parents not re-expanded",
          p["origin"] == "consolidation" and p["speaker"] == "consolidation"
          and p["conflict"] is False and p["seq_count"] == 0
          and p["seq_first"] is None and p["seq_last"] is None
          and p["source_hashes"] == cons_hashes, p)
    cur.execute("SELECT v13_mgraph_provenance(%s,%s)", (sid_j5, "f" * 64))
    p = cur.fetchone()[0]
    check("J5: unknown node -> belt shape",
          p["origin"] is None and p["speaker"] == "unknown"
          and p["conflict"] is False and p["seq_count"] == 0
          and p["source_hashes"] == [], p)
    fails_with(cur, "SELECT v13_mgraph_provenance(%s,%s)", (sid_j5, "zz"),
               "64 hex", "J5: malformed hash -> V3009", pgcode="V3009")
    # evidence shape & order on the J4 session (read on, walk stopped)
    cur.execute("SELECT v13_body_hash(v13_mgraph_turn_query(%s))", (sid_j4,))
    qh_j4 = cur.fetchone()[0]
    cur.execute("SELECT v13_mgraph_evidence(%s,%s)", (sid_j4, qh_j4))
    ev = cur.fetchone()[0]
    check("J5: evidence top-level keys remain rows/skipped/asks",
          sorted(ev.keys()) == ["asks", "rows", "skipped"], sorted(ev.keys()))
    check("J5: evidence rows ordered score DESC, hash ASC",
          [r["content_hash"] for r in ev["rows"]] == [bh_b, bh_a],
          [r["content_hash"] for r in ev["rows"]])
    check("J5: no provenance key inside evidence rows",
          all(sorted(r.keys()) == ["body", "content_hash", "score"]
              for r in ev["rows"]))
    cur.execute("SELECT v13_mgraph_section_material(%s)->'rows'", (sid_j4,))
    rows_j5 = cur.fetchone()[0]
    check("J5: material rows ordered score DESC, hash ASC",
          [r["content_hash"] for r in rows_j5] == [bh_b, bh_a])
    check("J5: material rows carry provenance",
          all("provenance" in r for r in rows_j5))
    conn.commit()

    # ================= J6 absence & filtering ===========================
    # (a) no walk
    sid_a = new_session(cur, "query with no walk at all")
    seed_node(cur, sid_a, "orphan memory body for no-walk case")
    cur.execute("SELECT v13_mgraph_section_status(%s)", (sid_a,))
    check("J6a: no matching walk -> no_walk",
          cur.fetchone()[0] == "no_walk")
    cur.execute("SELECT v13_assemble_manifest(%s)", (sid_a,))
    m_a = cur.fetchone()[0]
    check("J6a: no memory section without a walk",
          mem_section(m_a) is None)
    conn.commit()

    # (b) read disabled: zero asks, no section
    sid_b = new_session(cur, "query while read is disabled")
    seed_node(cur, sid_b, "body while read disabled")
    bump_policy(cur, "mgraph", dict(mgraph_seed_value, read_enabled=False))
    conn.commit()
    cur.execute("SELECT v13_mgraph_section_status(%s)", (sid_b,))
    check("J6b: read_enabled=false -> disabled", cur.fetchone()[0] == "disabled")
    cur.execute("SELECT v13_mgraph_next_action(%s,%s,0)",
                (sid_b, "query while read is disabled"))
    act_b = cur.fetchone()[0]
    check("J6b: next_action skips without asking (asks=0)",
          act_b["action"] == "skip", act_b)
    cur.execute("SELECT count(*) FROM judgment_calls WHERE session_id=%s",
                (sid_b,))
    check("J6b: zero judgment calls", cur.fetchone()[0] == 0)
    cur.execute("SELECT v13_assemble_manifest(%s)", (sid_b,))
    check("J6b: no memory section when disabled",
          mem_section(cur.fetchone()[0]) is None)
    bump_policy(cur, "mgraph", dict(mgraph_seed_value, read_enabled=True))
    conn.commit()

    # (c) degraded freshness: audit event, no self-excitation, history alive
    sid_c = new_session(cur, "degraded query")
    seed_node(cur, sid_c, "body under degraded freshness")
    for i in range(17):
        append(cur, sid_c, "user/message",
               {"text": f"unprojected filler number {i}"})
    cur.execute("SELECT v13_mgraph_section_status(%s)", (sid_c,))
    check("J6c: transcript lag -> degraded", cur.fetchone()[0] == "degraded")
    cur.execute("SELECT count(*) FROM events WHERE session_id=%s"
                " AND type IN ('user/message','llm/message')", (sid_c,))
    ev_before = cur.fetchone()[0]
    cur.execute("SELECT v13_assemble_manifest(%s)", (sid_c,))
    m_c = cur.fetchone()[0]
    out_c, m_set_c, eff_c = refresh_n(
        cur, sid_c, m_c["required_revision"]["goal"])
    check("J6c: degraded settle still accepted", out_c == "accepted", out_c)
    check("J6c: no memory section while degraded",
          mem_section(m_set_c) is None)
    check("J6c: history section still present (current turn never "
          "depends on the memory section)",
          any(s["kind"] == "history" for s in m_set_c["sections"]))
    cur.execute("SELECT count(*) FROM events WHERE session_id=%s"
                " AND type='audit/memory_degraded'", (sid_c,))
    check("J6c: exactly one audit/memory_degraded event",
          cur.fetchone()[0] == 1)
    cur.execute("SELECT count(*) FROM events WHERE session_id=%s"
                " AND type IN ('user/message','llm/message')", (sid_c,))
    check("J6c: no new curated events from the audit",
          cur.fetchone()[0] == ev_before)
    cur.execute("SELECT v13_context_fresh(%s)", (sid_c,))
    check("J6c: fresh after settle (audit event does not self-excite)",
          cur.fetchone()[0] is True)
    conn.commit()

    # (d) kinds_disabled carries memory_graph
    sid_d = new_session(cur, "query with kind disabled")
    bh_d = seed_node(cur, sid_d, "body while kind disabled")
    seed_walk(cur, sid_d, [(bh_d, 0.8)])
    conn.commit()
    bump_policy(cur, "assemble_manifest",
                dict(asm_seed_value, kinds_disabled=["memory_graph"]))
    conn.commit()
    cur.execute("SELECT v13_assemble_manifest(%s)", (sid_d,))
    m_d = cur.fetchone()[0]
    check("J6d: kinds_disabled drops the memory section",
          mem_section(m_d) is None)
    out_d, m_set_d, eff_d = refresh_n(
        cur, sid_d, m_d["required_revision"]["goal"])
    check("J6d: settle accepted, belt silent (P0-3)", out_d == "accepted")
    cur.execute(
        "SELECT count(*) FROM artifacts WHERE kind='context_section'"
        " AND content_hash = encode(digest(v13_mgraph_section_material(%s)::text,"
        " 'sha256'),'hex')", (sid_d,))
    check("J6d: memory material never lands as a blob",
          cur.fetchone()[0] == 0)
    conn.commit()

    # (e) retrieval cap ~0: budget-skipped section dropped from sections[]
    sid_e = new_session(cur, "query with zero retrieval cap")
    bh_e = seed_node(cur, sid_e, "body under zero retrieval cap")
    seed_walk(cur, sid_e, [(bh_e, 0.8)])
    conn.commit()
    cur.execute(
        "SELECT version, value FROM v13_policies "
        "WHERE name='context_budget' AND active")
    cbud_seed_ver, cbud_seed_value = cur.fetchone()
    buckets_e = dict(cbud_seed_value["buckets"], retrieval=0.0001,
                     history=0.5499)   # tiny-but-positive: refresh shape guard
                                      # requires every bucket > 0; sum still 1.0
    bump_policy(cur, "context_budget",
                dict(cbud_seed_value, buckets=buckets_e))
    conn.commit()
    cur.execute("SELECT v13_assemble_manifest(%s)", (sid_e,))
    m_e = cur.fetchone()[0]
    check("J6e: zero retrieval cap drops the memory section",
          mem_section(m_e) is None,
          [s["section_id"] for s in m_e["sections"]])
    out_e, m_set_e, eff_e = refresh_n(
        cur, sid_e, m_e["required_revision"]["goal"])
    check("J6e: settle accepted, belt silent (P0-3)", out_e == "accepted")
    cur.execute(
        "SELECT count(*) FROM artifacts WHERE kind='context_section'"
        " AND content_hash = encode(digest(v13_mgraph_section_material(%s)::text,"
        " 'sha256'),'hex')", (sid_e,))
    check("J6e: memory material never lands as a blob",
          cur.fetchone()[0] == 0)
    conn.commit()
    restore_policy(cur, "assemble_manifest", asm_seed_ver)
    restore_policy(cur, "context_budget", cbud_seed_ver)
    conn.commit()

    # ================= J7 isolation kept (F7 spirit) ====================
    sid_j7 = new_session(cur, "query for isolation checks")
    bh_j7 = seed_node(cur, sid_j7, "Alice deployed the payment service "
                                  "on Friday morning.")
    seq_g = append(cur, sid_j7, "goal/set",
                   {"text": "payment service deploy"})
    cur.execute(
        "INSERT INTO v13_goals (session_id, seq, content_hash, payload)"
        " VALUES (%s,%s,encode(digest(%s::jsonb::text,'sha256'),'hex'),%s::jsonb)",
        (sid_j7, seq_g, json.dumps({"text": "payment service deploy"}),
         json.dumps({"text": "payment service deploy"})))
    conn.commit()
    cur.execute("SELECT v13_recall_candidates(%s)", (sid_j7,))
    rc_j7 = cur.fetchone()[0]
    rc_hashes = {c["content_hash"] for c in rc_j7["candidates"]}
    cur.execute("SELECT content_hash FROM memory_nodes WHERE session_id=%s",
                (sid_j7,))
    graph_j7 = {r[0] for r in cur.fetchall()}
    check("J7: recall_candidates intersects no graph node hash",
          rc_hashes.isdisjoint(graph_j7), rc_hashes & graph_j7)
    cur.execute("SELECT v13_assemble_manifest(%s)", (sid_j7,))
    m_j7 = cur.fetchone()[0]
    qs_j7 = {c["content_hash"]
             for c in m_j7["query_side"]["candidates"]}
    check("J7: manifest query_side candidates disjoint from graph",
          qs_j7.isdisjoint(graph_j7), qs_j7 & graph_j7)
    check("J7: memory node is not a chunk candidate", bh_j7 not in qs_j7)
    cur.execute(
        "SELECT pg_get_functiondef('v13_needed_judgments(uuid)'::regprocedure)")
    check("J7: needed_judgments carries no mem_ face",
          "mem_" not in cur.fetchone()[0])
    cur.execute("SELECT pg_get_functiondef('v13_econ_ver()'::regprocedure)")
    econ_body = cur.fetchone()[0]
    check("J7: econ_ver still only names context_tiers and context_budget",
          "context_tiers" in econ_body and "context_budget" in econ_body
          and "mgraph" not in econ_body)
    for p_ in SQL_LOAD_ORDER[:15]:
        h_ = hashlib.sha256(p_.read_bytes()).hexdigest()[:16]
        check(f"J7: prefix byte freeze {p_.name}",
              PREFIX_FREEZE.get(p_.name) == h_,
              (p_.name, PREFIX_FREEZE.get(p_.name), h_))

    # ================= J8 driver timing (W3, §3.7 worker contract) =======
    def fresh_conn():
        c = psycopg2.connect(server.get_uri(DB))
        c.autocommit = False
        k = c.cursor()
        k.execute("SET search_path TO public, pg_catalog")
        k.execute("SELECT set_config('typesafe.provider', 'mock', false)")
        k.execute("SELECT set_config('typesafe.model', 'jev-mock', false)")
        return c, k

    def noul_mock(sigs, spec):
        answers = {}
        for s in sigs:
            v = spec.get(s, spec.get("*", 0.5))
            answers[s] = {"type": "noul", "noul": v}
        return json.dumps({"model": "jev-mock", "answers": answers,
                           "usage": {"input_tokens": 1, "output_tokens": 1}})

    ev_spec = {"*::sufficient": 0.95, "*::missing": 0.10,
               "*::contradiction": 0.10, "*::continue": 0.90, "*": 0.50}

    def worker_walk(sid, spec=ev_spec, elapsed=0, step_cap=None):
        """§3.7 worker contract: resolve-side loop, one transaction per
        round, query re-read via v13_mgraph_turn_query each round, step
        cap enforced worker-side (not in SQL). Returns round results."""
        wc, wk = fresh_conn()
        rounds = []
        steps = 0
        try:
            while True:
                if step_cap is not None and steps >= step_cap:
                    rounds.append({"capped": True})
                    break
                wk.execute("SELECT v13_mgraph_turn_query(%s)", (sid,))
                q = wk.fetchone()[0]
                wk.execute("SELECT v13_mgraph_next_action(%s,%s,%s)",
                           (sid, q, elapsed))
                act = wk.fetchone()[0]
                if act["action"] in ("done", "skip"):
                    rounds.append({"preview": act})
                    break
                if act["action"] == "ask":
                    wk.execute(
                        "SELECT current_setting('typesafe.provider', true),"
                        " current_setting('typesafe.model', true)")
                    pm = wk.fetchone()
                    if not pm[0] or not pm[1]:
                        # typesafe machinery DELETES provider/model on spent
                        # connections (mgraph README #17/#19); the reserved
                        # prefix forbids re-creating them via set_config on
                        # the same backend — the worker reconnects instead
                        wc.rollback()
                        wc.close()
                        wc, wk = fresh_conn()
                        pm = ("mock", "jev-mock")
                    wk.execute(
                        "SELECT v13_mgraph_envelope(%s,%s::jsonb,%s::jsonb,"
                        "%s,%s)",
                        (sid, json.dumps(act["state"]),
                         json.dumps(act["questions"]), pm[0], pm[1]))
                    env = wk.fetchone()[0]
                    wk.execute("SELECT v13_gap(%s::jsonb)", (json.dumps(env),))
                    gap = wk.fetchone()[0]
                    if gap:
                        wk.execute(
                            "SELECT set_config('typesafe.mock_response', %s,"
                            " true)",
                            (noul_mock([g["signal"] for g in gap], spec),))
                wk.execute("SELECT v13_mgraph_run_round(%s,%s,%s)",
                           (sid, q, elapsed))
                r = wk.fetchone()[0]
                wc.commit()                      # one transaction per round
                rounds.append(r)
                steps += 1
                if (r.get("status") in ("stopped", "skipped")
                        or r.get("action") in ("done", "skip")):
                    break
        finally:
            wc.rollback()
            wc.close()
        return rounds

    cur.execute("RESET ROLE")
    bump_policy(cur, "mgraph", dict(mgraph_seed_value, read_enabled=True))
    conn.commit()

    sid_j8 = new_session(cur, "alpha beacon")
    cur.execute("SELECT v13_body_hash(v13_mgraph_turn_query(%s))", (sid_j8,))
    qh_j8 = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO transcript_chunks (session_id, seq_from, seq_to, body,"
        " content_hash) SELECT %s, seq, seq, payload->>'text', v13_body_hash"
        "(payload->>'text') FROM events WHERE session_id=%s"
        " AND type='user/message'", (sid_j8, sid_j8))
    for i in range(5):
        seed_node(cur, sid_j8, f"alpha beacon j8 {i}")
    conn.commit()

    # route txn: enqueue + claim BEFORE the walk (§3.7)
    cur.execute("SELECT v13_goal_hash(%s)", (sid_j8,))
    gh_j8 = cur.fetchone()[0]
    append(cur, sid_j8, "turn/route", {"action": "refresh"})
    cur.execute(
        "SELECT v13_enqueue_effect(%s,'context_refresh',"
        "jsonb_build_object('goal_hash',%s))", (sid_j8, gh_j8))
    eff_j8 = cur.fetchone()[0]
    cur.execute("SELECT v13_claim('t')")
    cl_j8 = cur.fetchone()[0]
    conn.commit()

    rounds_j8 = worker_walk(sid_j8)
    check("J8: worker loop terminates without the step cap",
          not any(r.get("capped") for r in rounds_j8)
          and len(rounds_j8) >= 1)
    cur.execute("SELECT status, stop_reason FROM memory_walks"
                " WHERE session_id=%s", (sid_j8,))
    w_j8 = cur.fetchone()
    check("J8: walk stopped before refresh", w_j8[0] == "stopped", w_j8)

    cur.execute("SELECT v13_refresh_context(%s,%s,%s)",
                (eff_j8, cl_j8["attempt_no"], cl_j8["fence"]))
    out_j8 = cur.fetchone()[0]
    check("J8: refresh after walk settles accepted", out_j8 == "accepted",
          out_j8)
    cur.execute(
        "SELECT a.inline FROM artifacts a JOIN sessions s "
        "ON s.context_active_artifact=a.artifact_id WHERE s.session_id=%s",
        (sid_j8,))
    m_j8 = cur.fetchone()[0]
    sec_j8 = mem_section(m_j8)
    check("J8: memory section in the settled manifest", sec_j8 is not None)
    cur.execute("SELECT v13_mgraph_section_material(%s)->>'query_hash'",
                (sid_j8,))
    check("J8: section query_hash equals body_hash(turn_query)",
          cur.fetchone()[0] == qh_j8)
    conn.commit()

    # second worker loop: zero judgment_calls, section hash unchanged
    cur.execute("SELECT count(*) FROM judgment_calls WHERE session_id=%s",
                (sid_j8,))
    jc_0 = cur.fetchone()[0]
    worker_walk(sid_j8)
    cur.execute("SELECT count(*) FROM judgment_calls WHERE session_id=%s",
                (sid_j8,))
    jc_1 = cur.fetchone()[0]
    check("J8: second loop adds zero judgment calls (cached + done)",
          jc_1 == jc_0, (jc_0, jc_1))
    cur.execute("SELECT v13_assemble_manifest(%s)", (sid_j8,))
    m2_j8 = cur.fetchone()[0]
    sec2_j8 = mem_section(m2_j8)
    check("J8: memory section hash unchanged after second loop",
          sec2_j8 is not None
          and sec2_j8["content_hash"] == sec_j8["content_hash"])
    conn.commit()

    # walk holds no session row lock: append_event during a blocked round <5s
    sid_lock = new_session(cur)
    conn.commit()
    cur.execute(
        "SELECT v13_mgraph_stop_questions("
        " v13_mgraph_walk_id(%s, v13_body_hash(btrim(%s)),"
        "  (v13_mgraph_progress(%s)->>'generation')::bigint,"
        "  (SELECT version FROM v13_policies WHERE name='mgraph' AND active)),"
        " 1)",
        (sid_lock, "lock probe", sid_lock))
    stop_qs_j8 = cur.fetchone()[0]
    mock_lock = noul_mock([q["signal"] for q in stop_qs_j8], {"*": 0.2})
    lc, lk = fresh_conn()
    lk.execute("SELECT pg_advisory_lock(v13_lock_key(%s,'mgraph-build'))",
               (sid_lock,))
    box_j8 = {}

    def _j8_round():
        c_b, k_b = fresh_conn()
        try:
            k_b.execute(
                "SELECT set_config('typesafe.mock_response', %s, true)",
                (mock_lock,))
            k_b.execute("SELECT v13_mgraph_run_round(%s,%s,0)",
                        (sid_lock, "lock probe"))
            box_j8["res"] = k_b.fetchone()[0]
            c_b.commit()
        except Exception as exc:
            box_j8["err"] = repr(exc)
            c_b.rollback()
        finally:
            c_b.close()

    t_j8 = threading.Thread(target=_j8_round)
    t_j8.start()
    time.sleep(0.6)
    ac, ak = fresh_conn()
    t0_j8 = time.monotonic()
    ak.execute("SELECT v13_append_event(%s,%s,'user/message',%s::jsonb)",
               (sid_lock, u(), json.dumps({"text": "j8 probe"})))
    dt_j8 = time.monotonic() - t0_j8
    ac.commit()
    ac.close()
    check("J8: append_event while run_round waits on the advisory lock < 5s",
          dt_j8 < 5.0 and t_j8.is_alive(), (dt_j8, t_j8.is_alive()))
    lk.execute("SELECT pg_advisory_unlock(v13_lock_key(%s,'mgraph-build'))",
               (sid_lock,))
    lc.commit()
    lc.close()
    t_j8.join(timeout=20)
    check("J8: blocked run_round finished and did not raise",
          not t_j8.is_alive() and "res" in box_j8 and "err" not in box_j8,
          box_j8)
    conn.commit()

    # spend cap 0: loop skips, settle still accepted, session not failed
    cur.execute("SELECT version FROM v13_policies "
                "WHERE name='judge_spend_gate' AND active")
    spend_seed_ver = cur.fetchone()[0]
    bump_policy(cur, "judge_spend_gate",
                {"session_asks_cap": 0, "day_asks_cap": 8192,
                 "scope": "fast_path"})
    conn.commit()
    sid_sp = new_session(cur, "alpha beacon spend")
    cur.execute(
        "INSERT INTO transcript_chunks (session_id, seq_from, seq_to, body,"
        " content_hash) SELECT %s, seq, seq, payload->>'text',"
        " v13_body_hash(payload->>'text') FROM events WHERE session_id=%s"
        " AND type='user/message'", (sid_sp, sid_sp))
    seed_node(cur, sid_sp, "alpha beacon spend node")
    conn.commit()
    rounds_sp = worker_walk(sid_sp)
    check("J8: spend cap 0 -> loop stops on spend with zero asks",
          any(r.get("stop_reason") == "spend"
              or r.get("preview", {}).get("skipped") == "spend"
              for r in rounds_sp)
          and all(r.get("asks", 0) == 0 for r in rounds_sp), rounds_sp)
    restore_policy(cur, "judge_spend_gate", spend_seed_ver)
    conn.commit()
    cur.execute("SELECT v13_assemble_manifest(%s)", (sid_sp,))
    m_sp0 = cur.fetchone()[0]
    out_sp, m_sp, _eff_sp = refresh_n(cur, sid_sp,
                                      m_sp0["required_revision"]["goal"])
    check("J8: spend-skip settle returns accepted", out_sp == "accepted",
          out_sp)
    check("J8: no memory section after spend skip",
          mem_section(m_sp) is None)
    cur.execute("SELECT status FROM sessions WHERE session_id=%s", (sid_sp,))
    check("J8: session not failed by the memory fault",
          cur.fetchone()[0] != "failed")
    conn.commit()

    # closing assertions: fresh, dec includes mem rows, stable re-assemble
    cur.execute("SELECT v13_context_fresh(%s)", (sid_j8,))
    check("J8: fresh after settle", cur.fetchone()[0] is True)
    cur.execute("SELECT count(*) FROM decisions WHERE session_id=%s"
                " AND answer IS NOT NULL", (sid_j8,))
    dec_all = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM decisions WHERE session_id=%s"
                " AND signal ~ '^mem_' AND answer IS NOT NULL", (sid_j8,))
    dec_mem = cur.fetchone()[0]
    check("J8: required_revision.dec includes the walk's mem rows",
          dec_mem > 0 and m_j8["required_revision"]["dec"] == dec_all,
          (dec_mem, dec_all, m_j8["required_revision"]["dec"]))
    check("J8: re-assemble keeps mgraph_ver and section hash",
          m2_j8["required_revision"]["mgraph_ver"]
          == m_j8["required_revision"]["mgraph_ver"]
          and sec2_j8["content_hash"] == sec_j8["content_hash"])

    # OQ-E non-gating observation (A.5 trigger evidence; never a check)
    obs = {}
    for tag, with_edge in (("no_edge", False), ("with_edge", True)):
        sid_o = new_session(cur, "alpha beacon")
        cur.execute(
            "INSERT INTO transcript_chunks (session_id, seq_from, seq_to,"
            " body, content_hash) SELECT %s, seq, seq, payload->>'text',"
            " v13_body_hash(payload->>'text') FROM events"
            " WHERE session_id=%s AND type='user/message'", (sid_o, sid_o))
        hs_o = [seed_node(cur, sid_o, f"alpha beacon obs {tag} {i}")
                for i in range(5)]
        if with_edge:
            cur.execute(
                "INSERT INTO memory_links (session_id, src_hash, dst_hash,"
                " rel, origin, decision_id, structural, policy_version)"
                " VALUES (%s, %s, %s, 'contradicts', 'proximity', NULL,"
                " 0.9, 2)", (sid_o, min(hs_o[0], hs_o[1]),
                              max(hs_o[0], hs_o[1])))
        conn.commit()
        worker_walk(sid_o)
        cur.execute("SELECT edges_used, depth FROM memory_walks"
                    " WHERE session_id=%s AND status='stopped'", (sid_o,))
        row_o = cur.fetchone()
        cur.execute("SELECT v13_mgraph_section_material(%s)", (sid_o,))
        mat_o = cur.fetchone()[0]
        obs[tag] = {"edges_used": row_o[0] if row_o else None,
                    "depth": row_o[1] if row_o else None,
                    "section": mat_o is not None}
        conn.commit()
    print(f"[obs] J8 OQ-E no_edge={obs['no_edge']} with_edge={obs['with_edge']}"
          " (W4 only if section evidence differs between the two)")

    # ================= J9 permissions & locks (SET ROLE, P0-6) ==========
    sid_j9 = new_session(cur, "alpha beacon")
    cur.execute(
        "INSERT INTO transcript_chunks (session_id, seq_from, seq_to,"
        " body, content_hash) SELECT %s, seq, seq, payload->>'text',"
        " v13_body_hash(payload->>'text') FROM events WHERE session_id=%s"
        " AND type='user/message'", (sid_j9, sid_j9))
    for i in range(3):
        seed_node(cur, sid_j9, f"alpha beacon j9 {i}")
    conn.commit()
    worker_walk(sid_j9)
    cur.execute("SELECT status FROM memory_walks WHERE session_id=%s",
                (sid_j9,))
    check("J9: fixture walk stopped", cur.fetchone()[0] == "stopped")
    conn.commit()

    # route: assemble + claim + refresh (SET ROLE positive path)
    cur.execute("SET ROLE v13_route")
    cur.execute("SELECT v13_assemble_manifest(%s)", (sid_j9,))
    m_route = cur.fetchone()[0]
    check("J9: route can assemble (evidence EXECUTE present)",
          mem_section(m_route) is not None)
    cur.execute("SELECT v13_mgraph_section_material(%s) IS NOT NULL",
                (sid_j9,))
    check("J9: route can read section material", cur.fetchone()[0] is True)
    cur.execute("SELECT v13_enqueue_effect(%s,'context_refresh',"
                "jsonb_build_object('goal_hash',%s))",
                (sid_j9, m_route["required_revision"]["goal"]))
    eff_j9 = cur.fetchone()[0]
    cur.execute("SELECT v13_claim('t')")
    cl_j9 = cur.fetchone()[0]
    cur.execute("SELECT v13_refresh_context(%s,%s,%s)",
                (eff_j9, cl_j9["attempt_no"], cl_j9["fence"]))
    check("J9: route settles refresh (SET ROLE positive path)",
          cur.fetchone()[0] == "accepted")
    conn.commit()
    cur.execute("RESET ROLE")

    # resolve: run_round + assemble + material
    cur.execute("SET ROLE v13_resolve")
    cur.execute("SELECT v13_mgraph_run_round(%s,%s,0)",
                (sid_lock, "lock probe"))
    rr_j9 = cur.fetchone()[0]
    check("J9: resolve can run_round", "action" in rr_j9, rr_j9)
    cur.execute("SELECT v13_assemble_manifest(%s)", (sid_j9,))
    cur.fetchone()
    check("J9: resolve can assemble", True)
    cur.execute("SELECT v13_mgraph_section_material(%s) IS NOT NULL",
                (sid_j9,))
    check("J9: resolve can read section material",
          cur.fetchone()[0] is True)
    conn.commit()
    cur.execute("RESET ROLE")

    cur.execute("SET ROLE v13_recall")
    cur.execute("SELECT v13_assemble_manifest(%s)", (sid_j9,))
    cur.fetchone()
    check("J9: recall can assemble", True)
    cur.execute("SELECT v13_mgraph_section_material(%s) IS NOT NULL",
                (sid_j9,))
    check("J9: recall can read section material",
          cur.fetchone()[0] is True)
    conn.commit()
    cur.execute("RESET ROLE")
    conn.commit()

    # negatives + prose shape + source scan
    cur.execute("SELECT has_function_privilege('v13_route',"
                " 'v13_mgraph_run_round(uuid,text,int)', 'EXECUTE'),"
                " has_function_privilege('v13_recall',"
                " 'v13_refresh_context(uuid,int,bigint)', 'EXECUTE')")
    check("J9: route cannot run_round; recall cannot refresh",
          cur.fetchone() == (False, False))
    cur.execute(
        "SELECT proname, prosecdef FROM pg_proc WHERE proname IN ("
        "'v13_mgraph_asm_ver','v13_mgraph_turn_query','v13_mgraph_provenance',"
        "'v13_mgraph_section_plan','v13_mgraph_section_material',"
        "'v13_mgraph_section_status') ORDER BY proname")
    prose_j9 = cur.fetchall()
    check("J9: six new functions exist and none is SECURITY DEFINER",
          len(prose_j9) == 6 and not any(r[1] for r in prose_j9), prose_j9)

    src_lines_j9 = SQL_FILE.read_text(encoding="utf-8").split("\n")

    def fn_body(name):
        start = None
        for i, l_ in enumerate(src_lines_j9):
            if (l_.startswith("CREATE FUNCTION " + name + "(")
                    or l_.startswith("CREATE OR REPLACE FUNCTION " + name
                                      + "(")):
                start = i
                break
        assert start is not None, name
        dq = False
        for j in range(start, len(src_lines_j9)):
            l_ = src_lines_j9[j]
            if not dq:
                if "$$" in l_ and len(l_.split("$$")) == 2:
                    dq = True
            elif "$$;" in l_:
                return "\n".join(src_lines_j9[start:j + 1])
        raise AssertionError(name)

    for nm in ("v13_mgraph_asm_ver", "v13_mgraph_turn_query",
               "v13_mgraph_provenance", "v13_mgraph_section_plan",
               "v13_mgraph_section_material", "v13_mgraph_section_status"):
        body_j9 = fn_body(nm)
        check(f"J9: {nm} body has no FOR UPDATE / append_event / ask",
              "FOR UPDATE" not in body_j9
              and "v13_append_event" not in body_j9
              and "typesafe_ask" not in body_j9)
    refresh_body_j9 = fn_body("v13_refresh_context")
    check("J9: refresh copy takes the mgraph-build advisory before assemble",
          "v13_lock_key" in refresh_body_j9
          and "'mgraph-build'" in refresh_body_j9
          and refresh_body_j9.index(
              "pg_advisory_xact_lock(public.v13_lock_key(v_sid, "
              "'mgraph-build'))")
          < refresh_body_j9.index(
              "v_manifest := public.v13_assemble_manifest(v_sid, NULL);"))
    conn.commit()

    restore_policy(cur, "mgraph", mgraph_seed_ver)
    conn.commit()
    cur.execute("SELECT version, (value->>'read_enabled')::boolean"
                " FROM v13_policies WHERE name='mgraph' AND active")
    ver_end, read_end = cur.fetchone()
    check("J: mgraph policy restored to seed (v2, read off)",
          ver_end == mgraph_seed_ver and read_end is False,
          (ver_end, read_end))

    conn.close()
    print("ALL J GREEN (W1: J1-J3; W2: J4-J7; W3: J8-J9)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
