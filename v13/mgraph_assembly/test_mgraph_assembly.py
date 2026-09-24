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

W2 will add J4-J7 (section injection); W3 adds J8-J9 (driver & ACL).

Run: uv run python v13/mgraph_assembly/test_mgraph_assembly.py
     (exit 0 = pass)
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
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
    "v13_characterize.sql": "b9de1b8618e125e1",
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
    context_refresh effect; returns (outcome, manifest)."""
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
    return out, cur.fetchone()[0]


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
    out_j2, m_j2 = refresh_n(cur, sid_j2, m_pre["required_revision"]["goal"])
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

    conn.close()
    print("ALL J GREEN (W1: J1-J3)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
