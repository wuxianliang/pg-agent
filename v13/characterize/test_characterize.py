"""DP5 gate: stannum characterize + T0 definition swap.

Run: uv run python v13/characterize/test_characterize.py  (exit 0 = pass)
"""
from __future__ import annotations

import json
import re
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
V13 = AGENT_ROOT / "v13"
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v13.characterize.setup_db import DB, main as setup_db
from v13.load import files_through

HEX64 = re.compile(r"^[0-9a-f]{64}$")
TOKEN9 = {
    "sem", "dec", "goal", "tools_rev", "asm_ver", "jdef_ver", "gen_ver",
    "corpus", "recall_ver",
}
CAND4 = {"content_hash", "bm25", "spans", "decision_id"}
DYN_EXEC = re.compile(r"(?is)(?<![A-Za-z0-9_-])EXECUTE\s*['$]")
NORM_FIXTURE = """-- c==>y stannum.
SELECT 1;
/* b==>y stannum. */
x ==> y
SELECT concat('-- nc', (p ==> q));
stannum.highlight(z)
"""


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    extra = f": {detail}" if detail and (not condition or len(str(detail)) < 240) else ""
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
    raise AssertionError(f"{label}: expected failure")


def strip_sql_comments(src: str) -> str:
    out = []
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        if ch == "$":
            j = i + 1
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            if j < n and src[j] == "$":
                tag = src[i:j + 1]
                k = src.find(tag, j + 1)
                if k < 0:
                    out.append(src[i:])
                    break
                out.append(src[i:k + len(tag)])
                i = k + len(tag)
                continue
        if ch == "'":
            out.append("'")
            i += 1
            while i < n:
                if src[i] == "'":
                    out.append("'")
                    if i + 1 < n and src[i + 1] == "'":
                        out.append("'")
                        i += 2
                        continue
                    i += 1
                    break
                out.append(src[i])
                i += 1
            continue
        if ch == '"':
            out.append('"')
            i += 1
            while i < n:
                out.append(src[i])
                if src[i] == '"':
                    i += 1
                    break
                i += 1
            continue
        if ch == "-" and i + 1 < n and src[i + 1] == "-":
            while i < n and src[i] != "\n":
                i += 1
            out.append(" ")
            continue
        if ch == "/" and i + 1 < n and src[i + 1] == "*":
            i += 2
            depth = 1
            while i < n and depth:
                if src[i] == "/" and i + 1 < n and src[i + 1] == "*":
                    depth += 1
                    i += 2
                    continue
                if src[i] == "*" and i + 1 < n and src[i + 1] == "/":
                    depth -= 1
                    i += 2
                    continue
                i += 1
            out.append(" ")
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def guc(cur):
    cur.execute("RESET ROLE")
    cur.execute("SET search_path TO public, pg_catalog")
    cur.execute("SELECT set_config('typesafe.provider', 'mock', true)")
    cur.execute("SELECT set_config('typesafe.model', 'jev-mock', true)")


def recycle(server, conn):
    try:
        conn.commit()
    except Exception:
        conn.rollback()
    conn.close()
    c = psycopg2.connect(server.get_uri(DB))
    c.autocommit = False
    k = c.cursor()
    guc(k)
    return c, k


def new_session(cur, sid=None):
    sid = sid or u()
    cur.execute("INSERT INTO sessions (session_id) VALUES (%s)", (sid,))
    return sid


def append_user(cur, sid, text="hello"):
    cur.execute(
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (sid, u(), json.dumps({"text": text})),
    )
    return cur.fetchone()[0]


def set_mock(cur, mock: str) -> None:
    cur.execute("SELECT set_config('typesafe.mock_response', %s, true)", (mock,))


def claim_pinned(cur, eid, worker="w1", lease_ms=60000):
    cur.execute(
        "UPDATE effects SET status='cancelled' "
        "WHERE status='ready' AND effect_id IS DISTINCT FROM %s",
        (eid,))
    cur.execute("SELECT v13_claim(%s, %s)", (worker, lease_ms))
    row = cur.fetchone()[0]
    check("claim pinned",
          row is not None and str(row["effect_id"]) == str(eid), row)
    return row


def mock_from_needed(cur, sid, **over) -> str:
    cur.execute(
        "SELECT signal, kind, criteria FROM v13_needed_judgments(%s)", (sid,))
    answers = {}
    for signal, kind, criteria in cur.fetchall():
        if signal in over:
            answers[signal] = over[signal]
            continue
        if kind == "choice":
            keys = list(criteria.keys()) if isinstance(criteria, dict) else ["none"]
            ch = keys[0]
            answers[signal] = {
                "type": "choice", "choice": ch,
                "probabilities": {ch: 0.9}, "confidence": 0.9,
            }
        elif kind == "score":
            answers[signal] = {"type": "score", "score": 0.5, "confidence": 0.9}
        else:
            answers[signal] = {"type": "noul", "noul": 0.1}
    answers.update(over)
    return json.dumps({"model": "jev-mock", "answers": answers,
                       "usage": {"input_tokens": 1, "output_tokens": 1}})


def parse(cur, sid, **over):
    guc(cur)
    set_mock(cur, mock_from_needed(cur, sid, **over))
    cur.execute("SELECT v13_parse(%s)", (sid,))
    return cur.fetchone()[0]


def answers_sql(cur, sid):
    return parse(
        cur, sid,
        intent={"type": "choice", "choice": "sql_answer",
                "probabilities": {"sql_answer": 0.9}, "confidence": 0.9},
        gate_action={"type": "noul", "noul": 0.9},
        gate_off_topic={"type": "noul", "noul": 0.1},
        risk={"type": "score", "score": 0.5, "confidence": 0.9},
        tool={"type": "choice", "choice": "session_stats",
              "probabilities": {"session_stats": 0.9}, "confidence": 0.9})


def hang_refresh(cur, sid, snap=None):
    if snap is None:
        snap = answers_sql(cur, sid)
    cur.execute("SELECT v13_advance(%s, %s::jsonb)", (sid, json.dumps(snap)))
    a = cur.fetchone()[0]
    cur.execute(
        "SELECT effect_id FROM effects WHERE session_id=%s "
        "AND kind='context_refresh' AND status='ready'", (sid,))
    row = cur.fetchone()
    return a, (row[0] if row else None), snap


def settle(cur, eid):
    ck = claim_pinned(cur, eid)
    cur.execute(
        "SELECT v13_refresh_context(%s, %s, %s)",
        (eid, ck["attempt_no"], ck["fence"]))
    return cur.fetchone()[0], ck


def parse_settle(server, conn, cur, sid):
    snap = answers_sql(cur, sid)
    a, eid, snap = hang_refresh(cur, sid, snap)
    if eid is None:
        cur.execute("SELECT v13_goal_hash(%s)", (sid,))
        gh = cur.fetchone()[0]
        cur.execute(
            "SELECT v13_enqueue_effect(%s, 'context_refresh', %s::jsonb)",
            (sid, json.dumps({"goal_hash": gh, "nonce": u()})))
        eid = cur.fetchone()[0]
    else:
        check("refresh hung waiting", a == "waiting", a)
    out, ck = settle(cur, eid)
    check("settle accepted", out == "accepted", out)
    return recycle(server, conn)


def succeed_tool(cur, sid=None):
    sid = sid or new_session(cur)
    append_user(cur, sid, "ingest-op")
    cur.execute(
        "SELECT v13_enqueue_effect(%s, 'tool', %s::jsonb, 'v13_ingest_corpus')",
        (sid, json.dumps({"plan": "ingest", "nonce": u()})))
    eid = cur.fetchone()[0]
    ck = claim_pinned(cur, eid)
    cur.execute(
        "SELECT v13_complete(%s,%s,%s,'succeeded', '{}'::jsonb)",
        (eid, ck["attempt_no"], ck["fence"]))
    check("tool complete accepted", cur.fetchone()[0] == "accepted")
    return eid, sid


def ingest_doc(cur, body, corpus="docs", supersedes=None, eid=None, sid=None):
    if eid is None:
        eid, sid = succeed_tool(cur, sid)
    if supersedes is None:
        cur.execute("SELECT v13_ingest_document(%s,%s,%s)", (eid, corpus, body))
    else:
        cur.execute("SELECT v13_ingest_document(%s,%s,%s,%s)",
                    (eid, corpus, body, supersedes))
    return cur.fetchone()[0], eid, sid


def land_context(cur, content_hash, eid=None, sid=None):
    if eid is None:
        eid, sid = succeed_tool(cur, sid)
    inline = {"query_side": {"candidates": [{"content_hash": content_hash}]}}
    cur.execute(
        "SELECT v13_artifact_land(%s, 'context', %s::jsonb)",
        (eid, json.dumps(inline)))
    return cur.fetchone()[0], eid


def active_manifest(cur, sid):
    cur.execute(
        "SELECT a.inline FROM sessions s JOIN artifacts a "
        "ON a.artifact_id = s.context_active_artifact "
        "WHERE s.session_id=%s", (sid,))
    row = cur.fetchone()
    return row[0] if row else None


def tinql_of(cur, text):
    cur.execute("SELECT v13_build_tinql(%s)", (text,))
    return cur.fetchone()[0]


def recall_rows(cur, tinql, k=8):
    cur.execute("SELECT content_hash, bm25, spans FROM v13_recall(%s,%s)",
                (tinql, k))
    return cur.fetchall()


def keys_of(obj) -> set:
    if isinstance(obj, str):
        obj = json.loads(obj)
    return set(obj)


def walk_plans(node, acc=None):
    acc = acc if acc is not None else []
    if isinstance(node, list):
        for x in node:
            walk_plans(x, acc)
    elif isinstance(node, dict):
        if "Plan" in node:
            walk_plans(node["Plan"], acc)
        else:
            acc.append(node)
            for v in node.values():
                if isinstance(v, (dict, list)):
                    walk_plans(v, acc)
    return acc


def p99(times):
    s = sorted(times)
    if not s:
        return 0.0
    idx = max(0, int(round(0.99 * (len(s) - 1))))
    return s[idx]


def main() -> int:
    setup_db()
    server = get_server()
    conn = psycopg2.connect(server.get_uri(DB))
    conn.autocommit = False
    cur = conn.cursor()
    guc(cur)

    eid_ops, _ = succeed_tool(cur)
    conn.commit()
    for b in (
        "quasar formation in high redshift surveys and galaxies",
        "redshift surveys map quasar populations across cosmic time",
        "alpha quasar tiebreak aaa",
        "quasar alpha tiebreak bbb",
    ):
        ingest_doc(cur, b, "docs", eid=eid_ops)
    ingest_doc(cur, "東京タワーは電波塔である kohaku", "docs", eid=eid_ops)
    conn.commit()
    tinql_q = tinql_of(cur, "quasar")

    # ----- K bind matrix -----
    cur.execute("SET enable_seqscan = off")
    cur.execute(
        "EXPLAIN (FORMAT JSON) SELECT c.content_hash FROM chunks c "
        "WHERE c.body ==> %s", (tinql_q,))
    plan = cur.fetchone()[0]
    cur.execute("SET enable_seqscan = on")
    nodes = walk_plans(plan)
    custom = [n for n in nodes
              if n.get("Node Type") == "Custom Scan"
              and n.get("Custom Plan Provider") == "Stannum Text Search Scan"]
    check("K1: Custom Scan provider", len(custom) >= 1, custom[:1])
    check("K1: index name",
          any(n.get("Index") == "ix_chunks_stannum" for n in custom), custom[:1])
    seq = [n for n in nodes if n.get("Node Type") == "Seq Scan"
           and n.get("Relation Name") == "chunks"]
    check("K1: no chunks Seq Scan", seq == [], seq)

    for i in range(8):
        rows = recall_rows(cur, tinql_q, 8)
        check(f"K2: recall hit {i}", len(rows) >= 1, len(rows))
    cur.execute(
        "SELECT doc_no FROM v13_canary_docs WHERE body ==> %s",
        (tinql_of(cur, "redshift"),))
    can_hits = [r[0] for r in cur.fetchall()]
    check("K2: canary english hit", 2 in can_hits, can_hits)
    cur.execute("REINDEX INDEX ix_chunks_stannum")
    cur.execute("REINDEX INDEX ix_v13_canary")
    rows_re = recall_rows(cur, tinql_q, 8)
    check("K2: after REINDEX still hits", len(rows_re) >= 1, len(rows_re))
    conn.commit()

    blk = "z" * 64
    cur.execute(
        "SELECT (SELECT body FROM v13_canary_docs WHERE doc_no=1) ==> %s",
        ('"' + blk + '"',))
    # default comparator on a literal (no index) vs bound canary
    cur.execute(
        "SELECT doc_no FROM v13_canary_docs WHERE body ==> %s",
        ('"' + blk + '"',))
    bound = [r[0] for r in cur.fetchall()]
    check("K3/L1: bound 64B hits doc 1", 1 in bound, bound)
    cur.execute(
        "SELECT repeat('z', 200) ==> %s", ('"' + blk + '"',))
    fallback = cur.fetchone()[0]
    check("K3/L2: default comparator misses 64B block", fallback is False, fallback)

    cur.execute("SET enable_seqscan = off")
    cur.execute(
        "EXPLAIN (FORMAT JSON) SELECT doc_no FROM v13_canary_docs "
        "WHERE body ==> %s", ('"' + blk + '"',))
    cplan = walk_plans(cur.fetchone()[0])
    cur.execute("SET enable_seqscan = on")
    check("L1: EXPLAIN binds ix_v13_canary",
          any(n.get("Index") == "ix_v13_canary" for n in cplan), cplan[:2])

    cur.execute(
        "CREATE INDEX ix_v13_canary_default ON v13_canary_docs USING stannum (body)")
    cur.execute("SET enable_seqscan = off")
    cur.execute(
        "EXPLAIN (FORMAT JSON) SELECT doc_no FROM v13_canary_docs "
        "WHERE body ==> %s", ('"' + blk + '"',))
    dplan = walk_plans(cur.fetchone()[0])
    cur.execute("SET enable_seqscan = on")
    idxs = [n.get("Index") for n in dplan if n.get("Index")]
    check("K4: planner binds exactly one index", len(set(idxs)) == 1, idxs)
    bound_idx = idxs[0]
    check("K4: bound index is canary or default",
          bound_idx in ("ix_v13_canary", "ix_v13_canary_default"), bound_idx)
    cur.execute("SET enable_seqscan = off")
    cur.execute("SELECT doc_no FROM v13_canary_docs WHERE body ==> %s",
                ('"' + blk + '"',))
    k4_hits = [r[0] for r in cur.fetchall()]
    if bound_idx == "ix_v13_canary_default":
        check("K4: default-bound result misses split doc 1",
              1 not in k4_hits, (bound_idx, k4_hits))
    else:
        check("K4: split-bound result hits doc 1",
              1 in k4_hits, (bound_idx, k4_hits))
    cur.execute("SET enable_seqscan = on")
    cur.execute("DROP INDEX ix_v13_canary_default")
    conn.commit()

    tinql_red = tinql_of(cur, "redshift")
    cur.execute(
        "CREATE VIEW v13_gate_view_bind AS "
        "SELECT doc_no FROM v13_canary_docs WHERE body ==> %s",
        (tinql_red,))
    cur.execute("SELECT doc_no FROM v13_gate_view_bind")
    view_hits = sorted(r[0] for r in cur.fetchall())
    cur.execute(
        "SELECT doc_no FROM v13_canary_docs WHERE body ==> %s ORDER BY 1",
        (tinql_red,))
    exec_hits = [r[0] for r in cur.fetchall()]
    check("K5: view consistent with EXECUTE", view_hits == exec_hits,
          (view_hits, exec_hits))
    cur.execute("DROP VIEW v13_gate_view_bind")
    cur.execute(
        "CREATE FUNCTION v13_gate_static_bind(p text) RETURNS SETOF int "
        "LANGUAGE plpgsql STABLE AS $f$ "
        "BEGIN RETURN QUERY SELECT doc_no FROM v13_canary_docs WHERE body ==> p; "
        "END $f$")
    static_hits = []
    for _ in range(8):
        cur.execute("SELECT * FROM v13_gate_static_bind(%s)", (tinql_red,))
        static_hits.append(sorted(r[0] for r in cur.fetchall()))
    check("K5: static plpgsql consistent",
          all(h == exec_hits for h in static_hits), static_hits[:1])
    cur.execute("DROP FUNCTION v13_gate_static_bind(text)")
    cur.execute(
        "PREPARE v13_gate_prep AS SELECT doc_no FROM v13_canary_docs WHERE body ==> $1")
    prep_hits = []
    for _ in range(8):
        cur.execute("EXECUTE v13_gate_prep(%s)", (tinql_red,))
        prep_hits.append(sorted(r[0] for r in cur.fetchall()))
    check("K5: PREPARE consistent",
          all(h == exec_hits for h in prep_hits), prep_hits[:1])
    cur.execute("DEALLOCATE v13_gate_prep")
    conn.commit()

    tinql_tower = tinql_of(cur, "東京タワー")
    rec_cjk = recall_rows(cur, tinql_tower, 8)
    check("L3: CJK phrase hits production", len(rec_cjk) >= 1, rec_cjk)
    cur.execute(
        "SELECT doc_no FROM v13_canary_docs WHERE body ==> %s", (tinql_tower,))
    check("L3: CJK phrase hits canary doc 3", 3 in [r[0] for r in cur.fetchall()])
    tinql_ta = tinql_of(cur, "タ")
    rec_ta = recall_rows(cur, tinql_ta, 8)
    check("L3: single Katakana miss", rec_ta == [], rec_ta)

    # ----- M fold -----
    def seg_rows():
        try:
            cur.execute(
                "SELECT * FROM stannum.segment_info('ix_v13_canary'::regclass)")
        except psycopg2.Error as exc:
            conn.rollback()
            guc(cur)
            raise AssertionError(f"M2: segment_info unreadable: {exc}") from exc
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    cur.execute(
        "SELECT count(*) FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE p.proname = 'segment_info' AND n.nspname = 'stannum'")
    check("M2: stannum.segment_info present", cur.fetchone()[0] == 1)
    cur.execute("SELECT count(*) FROM v13_canary_docs")
    n_can0 = cur.fetchone()[0]
    info0 = seg_rows()
    gen0 = max(r["generation"] for r in info0)
    kinds0 = {r["kind"] for r in info0}
    print("[info] M2 segment_info initial", info0)

    times_base = []
    for i in range(500):
        t0 = time.perf_counter()
        cur.execute(
            "INSERT INTO v13_canary_docs VALUES (%s, %s) "
            "ON CONFLICT (doc_no) DO UPDATE SET body = EXCLUDED.body",
            (1000 + i, f"folddoc {i} " + ("z" * 80)))
        times_base.append((time.perf_counter() - t0) * 1000)
    conn.commit()
    info1 = seg_rows()
    gen1 = max(r["generation"] for r in info1)
    kinds1 = {r["kind"] for r in info1}
    print("[info] M2 segment_info after 500", info1)
    check("M2: generation increments with inserts", gen1 > gen0, (gen0, gen1))
    extra = 0
    while "mutable" not in kinds1 and extra < 4000:
        cur.execute(
            "INSERT INTO v13_canary_docs VALUES (%s, %s) "
            "ON CONFLICT (doc_no) DO UPDATE SET body = EXCLUDED.body",
            (2000 + extra, f"foldmore {extra} " + ("y" * 80)))
        extra += 1
        if extra % 500 == 0:
            conn.commit()
            info1 = seg_rows()
            gen1 = max(r["generation"] for r in info1)
            kinds1 = {r["kind"] for r in info1}
    conn.commit()
    info1 = seg_rows()
    gen1 = max(r["generation"] for r in info1)
    kinds1 = {r["kind"] for r in info1}
    check("M2: mutable segment active (fold face loaded)",
          "mutable" in kinds1, {"kinds": sorted(kinds1), "extra": extra})
    print(f"[info] M2 mutable activation extra={extra} "
          f"gen={gen1} kinds={sorted(kinds1)}")
    cur.execute(
        "SELECT count(*) FROM stannum.verify_index('ix_v13_canary'::regclass, true) "
        "WHERE severity IN ('error','warning')")
    check("M2: verify green before fold batch", cur.fetchone()[0] == 0)

    times_fold = []
    for i in range(500):
        t0 = time.perf_counter()
        cur.execute(
            "INSERT INTO v13_canary_docs VALUES (%s, %s) "
            "ON CONFLICT (doc_no) DO UPDATE SET body = EXCLUDED.body",
            (9000 + i, f"foldp99 {i} " + ("x" * 80)))
        times_fold.append((time.perf_counter() - t0) * 1000)
    conn.commit()
    info2 = seg_rows()
    gen2 = max(r["generation"] for r in info2)
    kinds2 = {r["kind"] for r in info2}
    print("[info] M2 segment_info after fold batch", info2)
    check("M2: generation increments across fold batch", gen2 > gen1,
          (gen1, gen2))
    check("M2: immutable and mutable segments coexist after fold",
          {"immutable", "mutable"} <= kinds2, sorted(kinds2))
    cur.execute(
        "SELECT count(*) FROM stannum.verify_index('ix_v13_canary'::regclass, true) "
        "WHERE severity IN ('error','warning')")
    check("M2: verify green after fold batch", cur.fetchone()[0] == 0)
    p99_base = p99(times_base)
    p99_fold = p99(times_fold)
    cap = max(p99_base * 10, 200.0)
    print(f"[info] M1 p99_base={p99_base:.3f} p99_fold={p99_fold:.3f} cap={cap:.3f}")
    check("M1: fold p99 within loose cap", p99_fold <= cap,
          {"base": p99_base, "fold": p99_fold, "cap": cap})
    cur.execute("SELECT count(*) FROM v13_canary_docs")
    n_can = cur.fetchone()[0]
    expected_can = n_can0 + 500 + extra + 500
    check("M3: canary count equals inserts after fold", n_can == expected_can,
          {"count": n_can, "expected": expected_can, "extra": extra})

    # ----- N verify + REINDEX -----
    cur.execute(
        "SELECT count(*) FROM stannum.verify_index('ix_chunks_stannum'::regclass, true) "
        "WHERE severity IN ('error','warning')")
    check("N1: production verify clean", cur.fetchone()[0] == 0)
    cur.execute(
        "SELECT count(*) FROM stannum.verify_index('ix_v13_canary'::regclass, true) "
        "WHERE severity IN ('error','warning')")
    check("N1: canary verify clean", cur.fetchone()[0] == 0)
    cur.execute(
        "SELECT severity FROM stannum.verify_index('ix_chunks_stannum'::regclass, true)")
    sev = [r[0] for r in cur.fetchall()]
    print("[info] N1 severity", sev)
    cur.execute("REINDEX INDEX ix_chunks_stannum")
    cur.execute("REINDEX INDEX ix_v13_canary")
    check("N2: recall after REINDEX", len(recall_rows(cur, tinql_q, 8)) >= 1)
    cur.execute(
        "SELECT count(*) FROM stannum.verify_index('ix_chunks_stannum'::regclass, true) "
        "WHERE severity IN ('error','warning')")
    check("N2: verify green after REINDEX", cur.fetchone()[0] == 0)

    cur.execute("SELECT v13_verify_chunks(false)")
    v2 = cur.fetchone()[0]
    check("N3: version=2", v2["version"] == 2, v2)
    names = [c["name"] for c in v2["checks"]]
    check("N3: eight checks", len(v2["checks"]) == 8, names)
    check("N3: all_ok", v2["all_ok"] is True, v2)
    eighth = [c for c in v2["checks"] if c["name"] == "stannum_verify_index"][0]
    check("N3: eighth detail",
          eighth["ok"] is True and eighth["detail"]["index"] == "ix_chunks_stannum"
          and eighth["detail"]["findings"] == 0, eighth)
    cur.execute("SAVEPOINT n3")
    ghost_body = "orphan-chunk-body-n3"
    cur.execute("SELECT v13_body_hash(%s)", (ghost_body,))
    gh4 = cur.fetchone()[0]
    eid4, _ = succeed_tool(cur)
    cur.execute(
        "INSERT INTO artifacts (content_hash, kind, inline, size, produced_by) "
        "VALUES (%s, 'chunk', to_jsonb(%s::text), octet_length(to_jsonb(%s::text)::text), %s)",
        (gh4, ghost_body, ghost_body, eid4))
    land_context(cur, gh4, eid4)
    cur.execute("SELECT v13_verify_chunks(false)")
    broken = cur.fetchone()[0]
    byn = {c["name"]: c["ok"] for c in broken["checks"]}
    check("N3: reference_resolvable red", byn.get("reference_resolvable") is False, byn)
    check("N3: all_ok false", broken["all_ok"] is False, broken)
    fails_with(cur, "SELECT v13_verify_chunks(true)", (),
               "verify_chunks failed", "N3: p_raise V3004", pgcode="V3004")
    cur.execute("ROLLBACK TO SAVEPOINT n3")
    conn.commit()
    guc(cur)
    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='pg_cron')")
    has_cron = cur.fetchone()[0]
    if has_cron:
        cur.execute("SELECT jobname FROM cron.job")
        jobs = [r[0] for r in cur.fetchall()]
        check("N4: exactly one verify job",
              jobs == ["v13-verify-chunks"], jobs)
    else:
        cur.execute("SELECT v13_verify_chunks(false)")
        check("N4: verify callable without cron",
              cur.fetchone()[0]["all_ok"] is True)

    # ----- O expand -----
    fails_with(cur, "SELECT v13_query_segments(%s)",
               (" ".join(f"w{i}" for i in range(65)),),
               "exceeds max segments", "O1: 65 segs", pgcode="V3005")
    fails_with(cur, "SELECT v13_query_segments(%s)",
               (" ".join(f"w{i}" for i in range(200)),),
               "exceeds max segments", "O1: 200 segs", pgcode="V3005")
    long_terms = [f"o2k{i}word" for i in range(1030)]
    o2_doc = 500001
    cur.execute("INSERT INTO v13_canary_docs VALUES (%s, %s)",
                (o2_doc, " ".join(long_terms)))
    long_and = " AND ".join(f'"{t}"' for t in long_terms)
    t0 = time.perf_counter()
    cur.execute(
        "SELECT doc_no FROM v13_canary_docs WHERE body ==> %s", (long_and,))
    hits_long = sorted(r[0] for r in cur.fetchall())
    dt_long = time.perf_counter() - t0
    print(f"[info] O2 1030-term hits={hits_long} dt={dt_long:.3f}s")
    cur.execute("SELECT doc_no, body FROM v13_canary_docs")
    direct_long = sorted(
        d for d, b in cur.fetchall()
        if all(t in b.split() for t in long_terms))
    check("O2: 1030-term known doc hit", o2_doc in hits_long,
          (hits_long, direct_long))
    check("O2: hit set equals direct scan", hits_long == direct_long,
          (hits_long, direct_long))

    # ----- P v2 chain -----
    rows_p = recall_rows(cur, tinql_q, 8)
    check("P1: production hits", len(rows_p) >= 1, len(rows_p))
    hashes = [h for h, _, _ in rows_p]
    check("P1: order hash/score",
          hashes == [h for h, _, _ in sorted(rows_p, key=lambda x: (-float(x[1]), x[0]))])
    r1 = recall_rows(cur, tinql_q, 8)
    r2 = recall_rows(cur, tinql_q, 8)
    check("P1: dual run equal", r1 == r2)
    for h, bm, sp in rows_p:
        check("P2: bm25 in [0,1]", 0 <= float(bm) <= 1, bm)
        check("P1: hash 64hex", bool(HEX64.match(h)), h)
    sid_p = new_session(cur)
    append_user(cur, sid_p, "quasar")
    conn, cur = parse_settle(server, conn, cur, sid_p)
    man = active_manifest(cur, sid_p)
    cands = man["query_side"]["candidates"]
    check("P1: manifest candidates", len(cands) >= 1, cands[:1])
    check("P1: four keys", keys_of(cands[0]) == CAND4, cands[0])

    cur.execute(
        "SELECT v13_extract_spans(%s, %s::jsonb)",
        ("the quasar shines", json.dumps({"tinql": tinql_q})))
    sp_v2 = cur.fetchone()[0]
    check("P3: spans array", isinstance(sp_v2, list), sp_v2)
    if sp_v2:
        s, e = sp_v2[0]
        check("P3: ordered pair", s <= e, sp_v2)
    poisoned = "".join(chr(i) for i in range(1, 9)) + " quasar"
    fails_with(cur, "SELECT v13_extract_spans(%s, %s::jsonb)",
               (poisoned, json.dumps({"tinql": tinql_q})),
               "highlight sentinels", "P3: sentinel conflict", pgcode="V3005")

    rec_cjk2 = recall_rows(cur, tinql_tower, 8)
    check("P4: CJK phrase hits v2", len(rec_cjk2) >= 1, rec_cjk2)
    check("P4: Katakana miss v2", recall_rows(cur, tinql_ta, 8) == [])
    cur.execute("SELECT v13_recall_count(%s)", (tinql_tower,))
    cnt_cjk = cur.fetchone()[0]
    check("P4: count v2 CJK > 0", cnt_cjk > 0, cnt_cjk)

    cur.execute("SELECT v13_context_required(%s)", (sid_p,))
    tok = cur.fetchone()[0]
    check("P5: token still nine keys", keys_of(tok) == TOKEN9, keys_of(tok))
    cur.execute("SELECT value FROM v13_policies WHERE name='recall_boosts' AND active")
    boosts = cur.fetchone()[0]
    check("P5: boosts seed empty", boosts.get("boosts") == [], boosts)
    empty_rows = recall_rows(cur, tinql_q, 8)
    check("P5: empty boosts no-op", empty_rows == r1)
    cur.execute(
        "UPDATE v13_policies SET active=false WHERE name='recall_boosts' AND active")
    cur.execute(
        "INSERT INTO v13_policies (name, version, value, active) VALUES "
        "('recall_boosts', 99, %s::jsonb, true)",
        (json.dumps({"boosts": ["x"]}),))
    fails_with(cur, "SELECT * FROM v13_recall(%s,8)", (tinql_q,),
               "must stay empty", "P5: nonempty boosts V3005", pgcode="V3005")
    cur.execute(
        "UPDATE v13_policies SET active=false WHERE name='recall_boosts' AND active")
    cur.execute(
        "UPDATE v13_policies SET active=true WHERE name='recall_boosts' AND version=1")
    conn.commit()

    out_old, _, _ = ingest_doc(
        cur, "kryptonite unique retired token " + u(), "retire", eid=eid_ops)
    conn.commit()
    old_src = out_old["source_hash"]
    cur.execute(
        "SELECT content_hash FROM chunks WHERE source_hash=%s LIMIT 1", (old_src,))
    href = cur.fetchone()[0]
    land_context(cur, href)
    conn.commit()
    ingest_doc(cur, "replacement without unique token " + u(),
               "retire", supersedes=old_src, eid=eid_ops)
    conn.commit()
    rec_k = recall_rows(cur, tinql_of(cur, "kryptonite"), 8)
    check("P6: v2 skips superseded", rec_k == [], rec_k)
    cur.execute(
        "SELECT generation, "
        "(SELECT candidate_generation_revision FROM v13_tools_meta WHERE singleton) "
        "FROM v13_chunks_meta WHERE singleton")
    g0, cgr0 = cur.fetchone()
    ingest_doc(cur, "cgr v2 sample " + u(), "docs", eid=eid_ops)
    conn.commit()
    cur.execute(
        "SELECT generation, "
        "(SELECT candidate_generation_revision FROM v13_tools_meta WHERE singleton) "
        "FROM v13_chunks_meta WHERE singleton")
    g1, cgr1 = cur.fetchone()
    check("P6: cgr still dual-bumps", (g1 - g0) == (cgr1 - cgr0) and g1 > g0,
          (g0, g1, cgr0, cgr1))

    # ----- Q size characterization -----
    print("[info] Q1 size table (word buried mid-body; avg_rank = mean "
          "start byte of target word inside each result chunk)")
    print("size\thits\tbm25_mean\tavg_rank")
    for size, tag in ((512, "s512"), (1024, "s1k"), (2048, "s2k"),
                      (4096, "s4k"), (8192, "s8k"), (16384, "s16k")):
        word = f"size{tag}"
        for i in range(20):
            tail = f" {i}"
            half = max(0, (size - len(word) - len(tail)) // 2)
            front = "p" * half
            back = "q" * max(0, size - half - 1 - len(word) - len(tail))
            body = f"{front} {word}{tail}{back}"
            if len(body) < size:
                body += "r" * (size - len(body))
            ingest_doc(cur, body, "qsize", eid=eid_ops)
        conn.commit()
        tq = tinql_of(cur, word)
        rec = recall_rows(cur, tq, 64)
        hits = len(rec)
        mean = (sum(float(s) for _, s, _ in rec) / hits) if hits else 0.0
        starts = [sp[0][0] for _, _, sp in rec if sp]
        avg_rank = (sum(starts) / len(starts)) if starts else 0.0
        print(f"{size}\t{hits}\t{mean:.4f}\t{avg_rank:.1f}")
        check(f"Q1: {size}B hits 20 docs", hits == 20, hits)
        check(f"Q1: {size}B spans present on all rows",
              len(starts) == hits, (len(starts), hits))
        check(f"Q1: {size}B word buried mid-chunk",
              size * 0.3 < avg_rank < size * 0.7, avg_rank)
    readme = (V13 / "characterize" / "README.md").read_text()
    check("Q2: flip procedure in README",
          "v13_rebuild_chunks" in readme and "不自动翻策略" in readme)

    # ----- R structure -----
    cur.execute(
        "SELECT count(*) FROM pg_index i "
        "JOIN pg_class idx ON idx.oid = i.indexrelid "
        "JOIN pg_class tbl ON tbl.oid = i.indrelid "
        "JOIN pg_am a ON a.oid = idx.relam "
        "WHERE tbl.relname='chunks' AND a.amname='stannum'")
    check("R1: chunks exactly one stannum index", cur.fetchone()[0] == 1)
    cur.execute(
        "SELECT count(*) FROM pg_index i "
        "JOIN pg_class idx ON idx.oid = i.indexrelid "
        "JOIN pg_class tbl ON tbl.oid = i.indrelid "
        "JOIN pg_am a ON a.oid = idx.relam "
        "WHERE tbl.relname='v13_canary_docs' AND a.amname='stannum'")
    check("R1: canary exactly one stannum index", cur.fetchone()[0] == 1)
    cur.execute(
        "SELECT tbl.relname FROM pg_index i "
        "JOIN pg_class idx ON idx.oid = i.indexrelid "
        "JOIN pg_class tbl ON tbl.oid = i.indrelid "
        "JOIN pg_am a ON a.oid = idx.relam "
        "WHERE a.amname='stannum'")
    rels = {r[0] for r in cur.fetchall()}
    check("R1: different tables", rels == {"chunks", "v13_canary_docs"}, rels)

    normed_fix = strip_sql_comments(NORM_FIXTURE)
    check("R2: fixture ==> count", normed_fix.count("==>") == 2)
    check("R2: fixture stannum. count", normed_fix.count("stannum.") == 1)
    files9 = files_through("characterize")
    check("R2: nine files", len(files9) == 9, len(files9))
    for i, path in enumerate(files9, 1):
        text = strip_sql_comments(path.read_text())
        n_op = text.count("==>")
        n_qn = text.count("stannum.")
        if i <= 8:
            check(f"R2: {path.name} ==> 0", n_op == 0, n_op)
            check(f"R2: {path.name} stannum. 0", n_qn == 0, n_qn)
        else:
            check(f"R2: {path.name} ==> 2", n_op == 2, n_op)
            check(f"R2: {path.name} stannum. 3", n_qn == 3, n_qn)
    raw9 = (V13 / "characterize" / "v13_characterize.sql").read_text()
    check("R2: file9 raw ==> 2", raw9.count("==>") == 2, raw9.count("==>"))
    check("R2: file9 raw stannum. 3", raw9.count("stannum.") == 3, raw9.count("stannum."))
    raw8 = (V13 / "recall" / "v13_recall.sql").read_text()
    check("R2: file8 raw ==> 0", raw8.count("==>") == 0)
    check("R2: file8 raw stannum. 0", raw8.count("stannum.") == 0)

    cur.execute("SET ROLE v13_recall")
    fails_with(cur, "SELECT count(*) FROM v13_canary_docs", (),
               "", "R3: recall SELECT canary denied")
    cur.execute("RESET ROLE")
    cur.execute("SET ROLE v13_resolve")
    fails_with(cur, "SELECT count(*) FROM v13_canary_docs", (),
               "", "R3: resolve SELECT canary denied")
    cur.execute("RESET ROLE")
    cur.execute("SET ROLE v13_route")
    fails_with(cur, "SELECT count(*) FROM v13_canary_docs", (),
               "", "R3: route SELECT canary denied")
    cur.execute("RESET ROLE")

    for needle in (
        "索引可丢基础行不可丢",
        "连接池预热",
        "fold 毛刺",
        "升级",
        "REINDEX",
        "AGPL",
    ):
        check(f"R4: README {needle}", needle in readme)

    check("R5: through characterize is 9", len(files_through("characterize")) == 9)
    check("R5: v2 recall still works", len(recall_rows(cur, tinql_q, 8)) >= 1)
    cur.execute("SELECT v13_build_tinql(%s)", ("how do quasars form",))
    check("R5: tinql compiler unchanged",
          cur.fetchone()[0] == '"how" AND "do" AND "quasars" AND "form"')

    conn.close()
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
