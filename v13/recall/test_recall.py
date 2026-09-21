"""DP5 gate: T0 tsvector recall + TINQL + envelope/assemble wiring.

Run: uv run python v13/recall/test_recall.py  (exit 0 = pass)
"""
from __future__ import annotations

import json
import re
import sys
import threading
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
from v13.recall.setup_db import DB, main as setup_db
from v13.load import SQL_LOAD_ORDER, files_through

HEX64 = re.compile(r"^[0-9a-f]{64}$")
TOKEN9 = {
    "sem", "dec", "goal", "tools_rev", "asm_ver", "jdef_ver", "gen_ver",
    "corpus", "recall_ver",
}
ENV19 = {
    "sid", "ctx", "needed", "candidate_set_hash", "goal_hash",
    "provider", "model", "route_policy_name", "route_policy_version",
    "tools_revision", "tools_catalog", "candidate_generation_revision",
    "session_version", "max_event_seq", "needed_count",
    "templates", "groups", "timeout_ms", "budget",
}
ENV20 = ENV19 | {"candidates"}
CAND3 = {"content_hash", "bm25", "spans"}
CAND4 = {"content_hash", "bm25", "spans", "decision_id"}
PARA_V1 = {
    "chunker_version": "para_v1",
    "analyzer_version": "tsv_english_1",
    "mode": "para",
    "target_bytes": 3072,
    "max_chunk_bytes": 1048576,
    "max_doc_bytes": 1048576,
}

NORM_FIXTURE = """-- c==>y stannum.
SELECT 1;
/* b==>y stannum. */
x ==> y
SELECT concat('-- nc', (p ==> q));
stannum.highlight(z)
"""

DYN_EXEC = re.compile(r"(?is)(?<![A-Za-z0-9_-])EXECUTE\s*['$]")


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


def with_current_probe(cur, sid, snap):
    cur.execute("SELECT v13_probe(%s)", (sid,))
    probe = cur.fetchone()[0]
    out = json.loads(json.dumps(snap))
    out["snap"].update(probe)
    return out


def connect_as(server, user):
    uri = server.get_uri(DB)
    host = (parse_qs(urlparse(uri).query).get("host") or [None])[0]
    return psycopg2.connect(host=host, dbname=DB, user=user)


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


def next_policy_version(cur, name: str) -> int:
    cur.execute(
        "SELECT coalesce(max(version),0)+1 FROM v13_policies WHERE name=%s",
        (name,))
    return cur.fetchone()[0]


def bump_policy(cur, name: str, value: dict) -> int:
    ver = next_policy_version(cur, name)
    cur.execute(
        "INSERT INTO v13_policies (name, version, value, active) "
        "VALUES (%s,%s,%s::jsonb,false)",
        (name, ver, json.dumps(value)))
    cur.execute(
        "UPDATE v13_policies SET active=false WHERE name=%s AND active",
        (name,))
    cur.execute(
        "UPDATE v13_policies SET active=true WHERE name=%s AND version=%s",
        (name, ver))
    return ver


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


def parse_settle(server, conn, cur, sid, **over):
    snap = parse(cur, sid, **over) if over else answers_sql(cur, sid)
    a, eid, snap = hang_refresh(cur, sid, snap)
    if eid is None:
        cur.execute("SELECT v13_goal_hash(%s)", (sid,))
        gh = cur.fetchone()[0]
        cur.execute(
            "SELECT v13_enqueue_effect(%s, 'context_refresh', %s::jsonb)",
            (sid, json.dumps({"goal_hash": gh, "nonce": u()})))
        eid = cur.fetchone()[0]
        cur.execute("SELECT status FROM effects WHERE effect_id=%s", (eid,))
        st = cur.fetchone()[0]
        check("nonce refresh ready", st == "ready", st)
    else:
        check("refresh hung waiting", a == "waiting", a)
    out, ck = settle(cur, eid)
    check("settle accepted", out == "accepted", out)
    conn, cur = recycle(server, conn)
    return snap, eid, out, conn, cur


def wait_lock(watch, pid, timeout=8.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        watch.execute(
            "SELECT wait_event_type, wait_event FROM pg_stat_activity "
            "WHERE pid=%s", (pid,))
        row = watch.fetchone()
        if row and row[0] == "Lock":
            return True
        watch.execute(
            "SELECT bool_or(NOT granted) FROM pg_locks "
            "WHERE locktype='advisory' AND pid=%s", (pid,))
        row = watch.fetchone()
        if row and row[0] is True:
            return True
        time.sleep(0.02)
    return False


def wait_box_lock(watch, box, key="pid", timeout=8.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        pid = box.get(key)
        if pid and wait_lock(watch, pid, timeout=0.12):
            return True
        time.sleep(0.02)
    return False


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


def spans_ok(spans) -> bool:
    if not isinstance(spans, list):
        return False
    prev_e = 0
    for sp in spans:
        if not (isinstance(sp, list) and len(sp) == 2):
            return False
        s, e = int(sp[0]), int(sp[1])
        if s < 1 or e < s or s < prev_e:
            return False
        prev_e = e
    return True


def cand_sorted(cands):
    return list(cands) == sorted(
        cands, key=lambda c: (-float(c["bm25"]), c["content_hash"]))


def main() -> int:
    setup_db()
    server = get_server()
    conn = psycopg2.connect(server.get_uri(DB))
    conn.autocommit = False
    cur = conn.cursor()
    guc(cur)

    # ----- A TINQL -----
    for q in (None, "", "   ", "\t\n"):
        cur.execute("SELECT v13_query_segments(%s), v13_build_tinql(%s)", (q, q))
        segs, built = cur.fetchone()
        check(f"A1: empty {q!r} segments", segs == [], segs)
        check(f"A1: empty {q!r} tinql", built == "", built)

    cur.execute("SELECT v13_build_tinql(%s)", ("how do quasars form",))
    a2 = cur.fetchone()[0]
    check("A2: english shape",
          a2 == '"how" AND "do" AND "quasars" AND "form"', a2)

    cur.execute("SELECT v13_build_tinql(%s)", ("東京タワーの高さ quasar",))
    a3 = cur.fetchone()[0]
    check("A3: kohaku mixed",
          a3 == '"東京タワーの高さ" AND "quasar"', a3)

    roundtrip_qs = [
        "how do quasars form",
        "東京タワーの高さ quasar",
        "東京タワー",
        "quasar quasar",
        "alpha beta gamma",
    ]
    for q in roundtrip_qs:
        cur.execute(
            "SELECT v13_tinql_terms(v13_build_tinql(%s)), v13_query_segments(%s)",
            (q, q))
        terms, segs = cur.fetchone()
        check(f"A4: roundtrip {q!r}", terms == segs, (terms, segs))

    inj = [
        ('x" OR 1=1 --', '"x" AND "OR" AND "1" AND "1"'),
        ("a AND b", '"a" AND "AND" AND "b"'),
        ("a*b /re/ ~fuzzy", '"a" AND "b" AND "re" AND "fuzzy"'),
    ]
    for src, expect in inj:
        cur.execute("SELECT v13_build_tinql(%s)", (src,))
        got = cur.fetchone()[0]
        check(f"A5: inject {src!r}", got == expect, got)

    fails_with(cur, "SELECT v13_query_segments(%s)", ("a" * 4097,),
               "exceeds max bytes (4096)", "A6: 4097B query", pgcode="V3005")
    fails_with(cur, "SELECT v13_query_segments(%s)", ("a" * 257,),
               "segment exceeds max bytes (256)", "A6: 257B segment",
               pgcode="V3005")
    sixty_five = " ".join(f"w{i}" for i in range(65))
    fails_with(cur, "SELECT v13_query_segments(%s)", (sixty_five,),
               "exceeds max segments (64)", "A6: 65 segments", pgcode="V3005")
    fails_with(cur, "SELECT v13_tinql_terms(%s)", ("bare",),
               "emitted grammar", "A6: bare word", pgcode="V3005")
    fails_with(cur, "SELECT v13_tinql_terms(%s)", ('"a" OR "b"',),
               "emitted grammar", "A6: OR form", pgcode="V3005")
    fails_with(cur, "SELECT v13_tinql_terms(%s)", ('"a',),
               "emitted grammar", "A6: unclosed", pgcode="V3005")
    fails_with(cur, "SELECT v13_tinql_terms(%s)", ('"a"b"',),
               "emitted grammar", "A6: inner quote", pgcode="V3005")
    fails_with(cur, "SELECT v13_tinql_terms(%s)", (None,),
               "must not be NULL", "A6: NULL tinql", pgcode="V3005")

    cur.execute("SELECT v13_build_tinql(%s)", ("how do quasars form",))
    t1 = cur.fetchone()[0]
    cur.execute("SELECT v13_build_tinql(%s)", ("how do quasars form",))
    t2 = cur.fetchone()[0]
    cur.execute("SELECT v13_build_tinql(%s)", ("how do quasars form",))
    t3 = cur.fetchone()[0]
    check("A7: deterministic triple", t1 == t2 == t3, (t1, t2, t3))
    ops = "\"()/*~^<>[]{}!@#$%\\|=+?;:"
    cur.execute("SELECT v13_query_segments(%s)", ("quasar " + ops + " redshift",))
    segs_ops = "".join(cur.fetchone()[0])
    check("A7: operators absent from segments",
          not any(ch in segs_ops for ch in ops), segs_ops)

    # ----- B recall v1 -----
    eid_ops, _ = succeed_tool(cur)
    conn.commit()
    bodies_b = [
        "quasar formation in high redshift surveys and galaxies",
        "redshift surveys map quasar populations across cosmic time",
        "galaxies without the marker term sit apart from the set",
    ]
    hashes_q = []
    for b in bodies_b:
        out, _, _ = ingest_doc(cur, b, "docs", eid=eid_ops)
        conn.commit()
    tinql_q = tinql_of(cur, "quasar")
    rows = recall_rows(cur, tinql_q, 8)
    cur.execute(
        "SELECT c.content_hash FROM chunks c "
        "JOIN v13_sources src ON src.source_hash=c.source_hash "
        "AND src.superseded_by IS NULL "
        "WHERE c.body_tsv @@ phraseto_tsquery('english'::regconfig, 'quasar') "
        "ORDER BY 1")
    expect = {r[0] for r in cur.fetchall()}
    got = {r[0] for r in rows}
    check("B1: hit set equals tsv", got == expect, (got, expect))
    for h, bm, sp in rows:
        check("B1: hash 64hex", bool(HEX64.match(h)), h)
        check("B1: spans shape", spans_ok(sp), sp)
        cur.execute("SELECT body FROM chunks WHERE content_hash=%s LIMIT 1", (h,))
        body = cur.fetchone()[0]
        for s, e in sp:
            cur.execute("SELECT octet_length(left(%s, %s))+1", (body, s - 1))
            check("B1: start byte", cur.fetchone()[0] == s, (s, e))
            check("B1: end within body", e <= len(body.encode("utf-8")), (s, e, body))

    ingest_doc(cur, "quasar alpha tiebreak aaa", "docs", eid=eid_ops)
    ingest_doc(cur, "alpha quasar tiebreak bbb", "docs", eid=eid_ops)
    conn.commit()
    tinql_tie = tinql_of(cur, "quasar alpha")
    r1 = recall_rows(cur, tinql_tie, 8)
    r2 = recall_rows(cur, tinql_tie, 8)
    check("B2: dual run equal", r1 == r2, (r1, r2))
    hashes = [h for h, _, _ in r1]
    scores = [float(s) for _, s, _ in r1]
    check("B2: score desc, hash asc",
          hashes == [h for h, _, _ in sorted(
              r1, key=lambda x: (-float(x[1]), x[0]))],
          list(zip(scores, hashes)))
    rlim = recall_rows(cur, tinql_tie, 1)
    if len(r1) >= 2 and float(r1[0][1]) == float(r1[1][1]):
        check("B2: limit tie uses hash", rlim[0][0] == min(r1[0][0], r1[1][0]),
              rlim)

    ingest_doc(cur, "東京タワーは電波塔である", "docs", eid=eid_ops)
    conn.commit()
    tinql_kyou = tinql_of(cur, "京")
    check("B3: substring 京 tinql", tinql_kyou == '"京"', tinql_kyou)
    miss = recall_rows(cur, tinql_kyou, 8)
    check("B3: CJK substring zero hits", miss == [], miss)
    tinql_tower = tinql_of(cur, "東京タワー")
    hit_tower = recall_rows(cur, tinql_tower, 8)
    cur.execute(
        "SELECT count(*) FROM chunks c "
        "JOIN v13_sources src ON src.source_hash=c.source_hash "
        "AND src.superseded_by IS NULL "
        "WHERE c.body_tsv @@ phraseto_tsquery('english'::regconfig, %s)",
        ("東京タワー",))
    tsv_n = cur.fetchone()[0]
    check("B3: whole-run matches tsv parser", len(hit_tower) == tsv_n,
          (len(hit_tower), tsv_n, tinql_tower))

    out_old, _, _ = ingest_doc(
        cur, "kryptonite unique retired token lives here " + u(),
        "retire", eid=eid_ops)
    conn.commit()
    old_src = out_old["source_hash"]
    cur.execute(
        "SELECT content_hash FROM chunks WHERE source_hash=%s "
        "ORDER BY chunk_no LIMIT 1", (old_src,))
    href = cur.fetchone()[0]
    land_context(cur, href)
    conn.commit()
    ingest_doc(cur, "replacement document without the unique token " + u(),
               "retire", supersedes=old_src, eid=eid_ops)
    conn.commit()
    cur.execute(
        "SELECT count(*) FROM chunks c JOIN v13_sources s "
        "ON s.source_hash=c.source_hash "
        "WHERE c.content_hash=%s AND s.superseded_by IS NOT NULL", (href,))
    check("B4: retired chunk still on disk", cur.fetchone()[0] == 1)
    tinql_k = tinql_of(cur, "kryptonite")
    rec_k = recall_rows(cur, tinql_k, 8)
    check("B4: recall skips superseded", rec_k == [], rec_k)
    sid_b4 = new_session(cur)
    append_user(cur, sid_b4, "kryptonite")
    cur.execute("SELECT v13_recall_candidates(%s)", (sid_b4,))
    rc_b4 = cur.fetchone()[0]
    check("B4: envelope-source candidates empty",
          rc_b4["candidates"] == [], rc_b4)
    guc(cur)
    cur.execute("SELECT v13_judgment_envelope(%s)->'candidates'", (sid_b4,))
    check("B4: envelope candidates empty", cur.fetchone()[0] == [])
    snap_b4, _, _, conn, cur = parse_settle(server, conn, cur, sid_b4)
    man_b4 = active_manifest(cur, sid_b4)
    check("B4: manifest candidates empty",
          man_b4["query_side"]["candidates"] == [],
          man_b4["query_side"]["candidates"])

    fails_with(cur, "SELECT * FROM v13_recall(%s,%s)", (None, 8),
               "out of bounds", "B5: NULL tinql", pgcode="V3005")
    cur.execute("SELECT count(*) FROM v13_recall(%s,%s)", ("", 8))
    check("B5: empty tinql zero rows", cur.fetchone()[0] == 0)
    fails_with(cur, "SELECT * FROM v13_recall(%s,%s)", (tinql_q, 0),
               "out of bounds", "B5: k=0", pgcode="V3005")
    fails_with(cur, "SELECT * FROM v13_recall(%s,%s)", (tinql_q, 1025),
               "out of bounds", "B5: k=1025", pgcode="V3005")
    fails_with(cur, "SELECT * FROM v13_recall(%s,%s)", ("not-grammar", 8),
               "emitted grammar", "B5: non-emitted tinql", pgcode="V3005")
    cur.execute("SELECT v13_recall_count(%s)", ("",))
    check("B5: count empty=0", cur.fetchone()[0] == 0)

    ingest_doc(cur, "nebulium only lives in docs corpus " + u(),
               "docs", eid=eid_ops)
    ingest_doc(cur, "thulium only lives in mem corpus " + u(),
               "mem", eid=eid_ops)
    conn.commit()
    rec_n = recall_rows(cur, tinql_of(cur, "nebulium"), 8)
    rec_t = recall_rows(cur, tinql_of(cur, "thulium"), 8)
    check("B6: nebulium hits", len(rec_n) >= 1, rec_n)
    check("B6: thulium hits", len(rec_t) >= 1, rec_t)
    check("B6: corpora do not cross",
          {h for h, _, _ in rec_n}.isdisjoint({h for h, _, _ in rec_t}))

    # ----- C k adaptive -----
    for i in range(3):
        ingest_doc(cur, f"neonium matching document {i} {u()}",
                   "c1", eid=eid_ops)
    conn.commit()
    sid_c1 = new_session(cur)
    append_user(cur, sid_c1, "neonium")
    cur.execute("SELECT v13_recall_candidates(%s)", (sid_c1,))
    c1 = cur.fetchone()[0]
    check("C1: k=k_base", c1["k"] == 8, c1)
    check("C1: matched=3", c1["matched"] == 3, c1)

    print("[info] C2 ingest 400 widenium docs")
    cur.execute(
        "DO $b$ DECLARE i int; BEGIN "
        "FOR i IN 1..400 LOOP "
        "PERFORM v13_ingest_document(%s::uuid, 'c2', "
        "'widenium doc ' || i::text || ' ' || %s); "
        "END LOOP; END $b$;",
        (str(eid_ops), u()))
    conn.commit()
    sid_c2 = new_session(cur)
    append_user(cur, sid_c2, "widenium")
    cur.execute("SELECT v13_recall_candidates(%s)", (sid_c2,))
    c2 = cur.fetchone()[0]
    check("C2: k=20", c2["k"] == 20, c2)
    check("C2: matched=400", c2["matched"] == 400, c2)
    check("C2: candidate count", len(c2["candidates"]) == 20, len(c2["candidates"]))
    check("C2: order", cand_sorted(c2["candidates"]), c2["candidates"][:3])

    print("[info] C3 ingest 4000 maxium docs")
    cur.execute(
        "DO $b$ DECLARE i int; BEGIN "
        "FOR i IN 1..4000 LOOP "
        "PERFORM v13_ingest_document(%s::uuid, 'c3', "
        "'maxium doc ' || i::text || ' ' || %s); "
        "END LOOP; END $b$;",
        (str(eid_ops), u()))
    conn.commit()
    sid_c3 = new_session(cur)
    append_user(cur, sid_c3, "maxium")
    cur.execute("SELECT v13_recall_candidates(%s)", (sid_c3,))
    c3 = cur.fetchone()[0]
    check("C3: k=k_max 64", c3["k"] == 64, c3)
    check("C3: matched=4000", c3["matched"] == 4000, c3)
    check("C3: candidate count 64", len(c3["candidates"]) == 64, len(c3["candidates"]))

    cur.execute("SELECT value FROM v13_policies WHERE name='recall_k' AND active")
    rk = cur.fetchone()[0]
    bump_policy(cur, "recall_k", {**rk, "k_max": 16})
    cur.execute("SELECT v13_recall_candidates(%s)", (sid_c3,))
    c4 = cur.fetchone()[0]
    check("C4: k_max 16 binds", c4["k"] == 16, c4)
    bump_policy(cur, "recall_k", rk)
    conn.commit()
    def bad_rk(val, label):
        bump_policy(cur, "recall_k", val)
        fails_with(cur, "SELECT v13_recall_candidates(%s)", (sid_c3,),
                   "invalid recall_k", label, pgcode="V3005")
        bump_policy(cur, "recall_k", rk)
    bad_rk({**rk, "k_base": "8"}, "C4: k_base string")
    bad_rk({**rk, "k_max": 1, "k_base": 8}, "C4: k_max < k_base")
    missing = dict(rk)
    missing.pop("timeout_ms")
    bad_rk(missing, "C4: missing timeout_ms")
    bad_rk({**rk, "widen_ratio": -0.1}, "C4: negative widen")
    conn.commit()

    # ----- D envelope -----
    sid_d = new_session(cur)
    append_user(cur, sid_d, "cshdriftium uniquequery")
    guc(cur)
    cur.execute("SELECT v13_judgment_envelope(%s)", (sid_d,))
    env = cur.fetchone()[0]
    check("D1: 20 keys", keys_of(env) == ENV20, keys_of(env))
    check("D1: 19 retained", ENV19 <= keys_of(env))
    cur.execute("SELECT v13_goal_hash(%s)", (sid_d,))
    check("D1: goal_hash", env["goal_hash"] == cur.fetchone()[0])
    check("D1: csh hex", bool(HEX64.match(env["candidate_set_hash"])),
          env["candidate_set_hash"])

    snap_d = answers_sql(cur, sid_d)
    env1 = snap_d["envelope"]
    ingest_doc(cur, "cshdriftium uniquequery extra unique " + u(), "docs", eid=eid_ops)
    conn, cur = recycle(server, conn)
    snap_d2 = answers_sql(cur, sid_d)
    env2 = snap_d2["envelope"]
    check("D2: ingest changes csh",
          env1["candidate_set_hash"] != env2["candidate_set_hash"],
          (env1["candidate_set_hash"], env2["candidate_set_hash"]))
    conn, cur = recycle(server, conn)
    snap_d3 = answers_sql(cur, sid_d)
    check("D2: same world csh stable",
          snap_d2["envelope"]["candidate_set_hash"]
          == snap_d3["envelope"]["candidate_set_hash"])
    conn, cur = recycle(server, conn)

    cands = env2["candidates"]
    check("D3: candidates is array", isinstance(cands, list), cands)
    if cands:
        check("D3: three keys", keys_of(cands[0]) == CAND3, cands[0])
        check("D3: order", cand_sorted(cands), cands[:3])
    frozen = json.loads(json.dumps(cands))
    ingest_doc(cur, "cshdriftium uniquequery freeze extra " + u(), "docs", eid=eid_ops)
    conn.commit()
    check("D3: frozen snapshot unchanged", cands == frozen)
    guc(cur)
    cur.execute("SELECT v13_judgment_envelope(%s)->'candidates'", (sid_d,))
    env_new = cur.fetchone()[0]
    check("D3: new parse candidates moved", env_new != frozen,
          (len(env_new or []), len(frozen)))

    sid_empty = new_session(cur)
    cur.execute("SELECT v13_recall_candidates(%s)", (sid_empty,))
    empty_rc = cur.fetchone()[0]
    check("D4: empty k=0", empty_rc["k"] == 0 and empty_rc["matched"] == 0,
          empty_rc)
    guc(cur)
    cur.execute("SELECT v13_judgment_envelope(%s)", (sid_empty,))
    env_e = cur.fetchone()[0]
    check("D4: empty candidates", env_e["candidates"] == [], env_e["candidates"])
    check("D4: csh present", bool(HEX64.match(env_e["candidate_set_hash"])))

    tinql_d = tinql_of(cur, "cshdriftium uniquequery")
    check("D5: envelope has no tinql", tinql_d not in json.dumps(env2), tinql_d)

    # ----- E assemble -----
    sid_e = new_session(cur)
    append_user(cur, sid_e, "quasar")
    _, _, _, conn, cur = parse_settle(server, conn, cur, sid_e)
    man = active_manifest(cur, sid_e)
    cands_e = man["query_side"]["candidates"]
    check("E1: not goal echo",
          not (len(cands_e) == 1 and cands_e[0].get("bm25") is None),
          cands_e[:1])
    if cands_e:
        check("E1: four keys", keys_of(cands_e[0]) == CAND4, cands_e[0])
        check("E1: decision_id null",
              all(c["decision_id"] is None for c in cands_e))
    cur.execute("SELECT v13_manifest_validate(%s::jsonb)", (json.dumps(man),))
    check("E1: validator ok", True)
    check("E2: manifest order", cand_sorted(cands_e) if cands_e else True, cands_e[:3])
    man2 = active_manifest(cur, sid_e)
    check("E2: dual read equal", man == man2)
    check("E3: judgments empty", man["judgments"] == [])
    check("E3: no tinql in manifest", tinql_q not in json.dumps(man), tinql_q)
    art_old = None
    cur.execute("SELECT context_active_artifact FROM sessions WHERE session_id=%s",
                (sid_e,))
    art_old = cur.fetchone()[0]
    ingest_doc(cur, "quasar brand new token " + u(), "docs", eid=eid_ops)
    conn.commit()
    cur.execute("SELECT v13_context_fresh(%s)", (sid_e,))
    check("E4: not fresh after ingest", cur.fetchone()[0] is False)
    _, _, _, conn, cur = parse_settle(server, conn, cur, sid_e)
    man_new = active_manifest(cur, sid_e)
    check("E4: new manifest differs",
          man_new["query_side"]["candidates"] != cands_e
          or man_new["required_revision"] != man["required_revision"])
    cur.execute("SELECT v13_replay(%s)", (art_old,))
    replayed = cur.fetchone()[0]
    check("E4: exact replay candidates frozen",
          replayed["query_side"]["candidates"] == cands_e)

    sid_e5 = new_session(cur)
    append_user(cur, sid_e5, "   ")
    _, _, _, conn, cur = parse_settle(server, conn, cur, sid_e5)
    man_e5 = active_manifest(cur, sid_e5)
    check("E5: empty candidates legal",
          man_e5["query_side"]["candidates"] == [])
    cur.execute("SELECT v13_manifest_validate(%s::jsonb)", (json.dumps(man_e5),))
    check("E5: validator ok", True)

    # ----- F cgr -----
    cur.execute(
        "SELECT generation, "
        "(SELECT candidate_generation_revision FROM v13_tools_meta WHERE singleton) "
        "FROM v13_chunks_meta WHERE singleton")
    g0, cgr0 = cur.fetchone()
    ingest_doc(cur, "cgr sync one paragraph " + u(), "f1", eid=eid_ops)
    conn.commit()
    cur.execute(
        "SELECT generation, "
        "(SELECT candidate_generation_revision FROM v13_tools_meta WHERE singleton) "
        "FROM v13_chunks_meta WHERE singleton")
    g1, cgr1 = cur.fetchone()
    check("F1: generation bumped", g1 > g0, (g0, g1))
    check("F1: cgr bumped equally", (g1 - g0) == (cgr1 - cgr0), (g0, g1, cgr0, cgr1))
    cur.execute(
        "SELECT generation, "
        "(SELECT candidate_generation_revision FROM v13_tools_meta WHERE singleton) "
        "FROM v13_chunks_meta WHERE singleton")
    g0, cgr0 = cur.fetchone()
    body_own = "owner insert body " + u()
    cur.execute("SELECT v13_body_hash(%s)", (body_own,))
    oh = cur.fetchone()[0]
    cur.execute("SELECT source_hash FROM v13_sources WHERE superseded_by IS NULL LIMIT 1")
    osh = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO artifacts (content_hash, kind, inline, size, produced_by) "
        "VALUES (%s,'chunk', to_jsonb(%s::text), octet_length(to_jsonb(%s::text)::text), %s)",
        (oh, body_own, body_own, eid_ops))
    cur.execute(
        "SELECT coalesce(max(chunk_no),-1)+1 FROM chunks WHERE source_hash=%s",
        (osh,))
    nno = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO chunks (source_hash, chunk_no, body, content_hash, "
        "chunk_offset, corpus, chunker_version, analyzer_version) "
        "VALUES (%s,%s,%s,%s,0,'docs','para_v1','tsv_english_1')",
        (osh, nno, body_own, oh))
    conn.commit()
    cur.execute(
        "SELECT generation, "
        "(SELECT candidate_generation_revision FROM v13_tools_meta WHERE singleton) "
        "FROM v13_chunks_meta WHERE singleton")
    g1, cgr1 = cur.fetchone()
    check("F1: owner insert dual bump",
          g1 == g0 + 1 and cgr1 == cgr0 + 1, (g0, g1, cgr0, cgr1))

    sid_f2 = new_session(cur)
    append_user(cur, sid_f2, "quasar")
    snap_f2 = answers_sql(cur, sid_f2)
    conn, cur = recycle(server, conn)
    ingest_doc(cur, "quasar f2 drift " + u(), "docs", eid=eid_ops)
    conn.commit()
    cur.execute("SELECT v13_advance(%s, %s::jsonb)",
                (sid_f2, json.dumps(snap_f2)))
    check("F2: advance stale after ingest", cur.fetchone()[0] == "stale")
    snap_f2b = answers_sql(cur, sid_f2)
    conn, cur = recycle(server, conn)
    cur.execute("SELECT v13_advance(%s, %s::jsonb)",
                (sid_f2, json.dumps(snap_f2b)))
    act_f2 = cur.fetchone()[0]
    check("F2: reparse not stale", act_f2 != "stale", act_f2)
    sid_f2c = new_session(cur)
    append_user(cur, sid_f2c, "quasar")
    snap_f2c = answers_sql(cur, sid_f2c)
    conn, cur = recycle(server, conn)
    cur.execute("SELECT v13_advance(%s, %s::jsonb)",
                (sid_f2c, json.dumps(snap_f2c)))
    check("F2: baseline not stale", cur.fetchone()[0] != "stale")

    sid_f3 = new_session(cur)
    append_user(cur, sid_f3, "quasar")
    _, _, _, conn, cur = parse_settle(server, conn, cur, sid_f3)
    cur.execute("SELECT v13_context_fresh(%s)", (sid_f3,))
    check("F3: fresh after settle", cur.fetchone()[0] is True)
    ingest_doc(cur, "quasar f3 " + u(), "docs", eid=eid_ops)
    conn.commit()
    cur.execute("SELECT v13_context_fresh(%s)", (sid_f3,))
    check("F3: not fresh after ingest", cur.fetchone()[0] is False)
    _, _, _, conn, cur = parse_settle(server, conn, cur, sid_f3)
    cur.execute("SELECT v13_context_fresh(%s)", (sid_f3,))
    check("F3: fresh again once", cur.fetchone()[0] is True)
    cur.execute("SELECT v13_context_fresh(%s)", (sid_f3,))
    check("F3: still fresh no livelock", cur.fetchone()[0] is True)

    cur.execute("SELECT revision, candidate_generation_revision "
                "FROM v13_tools_meta WHERE singleton")
    rev0, cgrt0 = cur.fetchone()
    cur.execute(
        "INSERT INTO tools (name, description, kind, handler) "
        "VALUES (%s,'F4 tool.', 'tool', 'worker:f4')",
        ("f4tool",))
    cur.execute("SELECT revision, candidate_generation_revision "
                "FROM v13_tools_meta WHERE singleton")
    rev1, cgrt1 = cur.fetchone()
    check("F4: tools insert bumps revision", rev1 == rev0 + 1, (rev0, rev1))
    check("F4: tools insert does not bump cgr", cgrt1 == cgrt0, (cgrt0, cgrt1))
    cur.execute(
        "SELECT pg_get_functiondef('v13_needed_judgments(uuid)'::regprocedure)")
    defn = cur.fetchone()[0]
    cur.execute("SELECT candidate_generation_revision FROM v13_tools_meta WHERE singleton")
    cgr_n0 = cur.fetchone()[0]
    cur.execute(defn)
    cur.execute("SELECT candidate_generation_revision FROM v13_tools_meta WHERE singleton")
    cgr_n1 = cur.fetchone()[0]
    check("F4: needed replace bumps cgr", cgr_n1 == cgr_n0 + 1, (cgr_n0, cgr_n1))
    conn.commit()

    sid_f5 = new_session(cur)
    append_user(cur, sid_f5, "quasar")
    snap_f5 = answers_sql(cur, sid_f5)
    conn, cur = recycle(server, conn)
    c_hold = psycopg2.connect(server.get_uri(DB))
    c_hold.autocommit = False
    k_hold = c_hold.cursor()
    guc(k_hold)
    ingest_doc(k_hold, "quasar hold-open " + u(), "hold")
    box_f5 = {}

    def run_f5_adv():
        c = psycopg2.connect(server.get_uri(DB))
        c.autocommit = False
        k = c.cursor()
        guc(k)
        k.execute("SELECT pg_backend_pid()")
        box_f5["pid"] = k.fetchone()[0]
        k.execute("SET lock_timeout = '2s'")
        try:
            live = with_current_probe(k, sid_f5, snap_f5)
            k.execute("SELECT v13_advance(%s, %s::jsonb)",
                      (sid_f5, json.dumps(live)))
            box_f5["act"] = k.fetchone()[0]
            box_f5["ok"] = True
        except Exception as exc:
            box_f5["err"] = str(exc)
            box_f5["ok"] = False
        c.rollback()
        c.close()

    th = threading.Thread(target=run_f5_adv)
    th.start()
    t0 = time.time()
    while time.time() - t0 < 1 and "pid" not in box_f5:
        time.sleep(0.02)
    blocked = wait_box_lock(cur, box_f5, timeout=0.4)
    check("F5: probe not blocked by ingest", blocked is False,
          {"blocked": blocked, "box": box_f5})
    c_hold.commit()
    c_hold.close()
    th.join(8)
    check("F5: advance completed", box_f5.get("ok") is True, box_f5)

    sid_s = new_session(cur)
    append_user(cur, sid_s, "quasar")
    snap_s = answers_sql(cur, sid_s)
    conn, cur = recycle(server, conn)
    c_hold2 = psycopg2.connect(server.get_uri(DB))
    c_hold2.autocommit = False
    k_hold2 = c_hold2.cursor()
    guc(k_hold2)
    ingest_doc(k_hold2, "quasar settle-hold " + u(), "hold2")
    box_s = {}

    def run_settle_hold():
        c = psycopg2.connect(server.get_uri(DB))
        c.autocommit = False
        k = c.cursor()
        guc(k)
        k.execute("SELECT pg_backend_pid()")
        box_s["pid"] = k.fetchone()[0]
        k.execute("SET statement_timeout = '8s'")
        try:
            a, eid, _ = hang_refresh(k, sid_s, snap_s)
            if eid is None:
                k.execute("SELECT v13_goal_hash(%s)", (sid_s,))
                gh = k.fetchone()[0]
                k.execute(
                    "SELECT v13_enqueue_effect(%s,'context_refresh',%s::jsonb)",
                    (sid_s, json.dumps({"goal_hash": gh, "nonce": u()})))
                eid = k.fetchone()[0]
            out, _ = settle(k, eid)
            box_s["out"] = out
            c.commit()
            box_s["ok"] = True
        except Exception as exc:
            box_s["err"] = str(exc)
            box_s["ok"] = False
            c.rollback()
        c.close()

    ths = threading.Thread(target=run_settle_hold)
    ths.start()
    t1 = time.time()
    while time.time() - t1 < 1 and "pid" not in box_s:
        time.sleep(0.02)
    wait_box_lock(cur, box_s, timeout=0.8)
    c_hold2.commit()
    c_hold2.close()
    ths.join(12)
    check("F5: settle vs ingest no deadlock", box_s.get("ok") is True, box_s)

    # ----- G source scan -----
    normed_fix = strip_sql_comments(NORM_FIXTURE)
    check("G1: fixture comments gone",
          "c==>y" not in normed_fix and "b==>y" not in normed_fix, normed_fix)
    check("G1: fixture ==> count",
          normed_fix.count("==>") == 2, normed_fix)
    check("G1: fixture stannum. count",
          normed_fix.count("stannum.") == 1, normed_fix)
    check("G1: string -- kept", "-- nc" in normed_fix, normed_fix)

    files8 = files_through("recall")
    check("G1: eight files", len(files8) == 8, len(files8))
    for path in files8:
        text = strip_sql_comments(path.read_text())
        check(f"G1: {path.name} zero ==>", text.count("==>") == 0, path.name)
        check(f"G1: {path.name} zero stannum.",
              text.count("stannum.") == 0, path.name)
    rec_sql = (V13 / "recall" / "v13_recall.sql").read_text()
    check("G1: file8 raw zero ==>", rec_sql.count("==>") == 0)
    check("G1: file8 raw zero stannum.", rec_sql.count("stannum.") == 0)

    rec_norm = strip_sql_comments(rec_sql)
    check("G2: no dynamic EXECUTE literals",
          DYN_EXEC.search(rec_norm) is None, rec_norm[DYN_EXEC.search(rec_norm).start():] if DYN_EXEC.search(rec_norm) else "")

    readme = (V13 / "recall" / "README.md").read_text()
    for needle in ("视图内嵌", "plpgsql 静态", "预备语句", "worker 契约"):
        check(f"G3: README has {needle}", needle in readme)

    # ----- H ACL -----
    sid_h = new_session(cur)
    append_user(cur, sid_h, "quasar")
    conn.commit()
    cur.execute("SET ROLE v13_recall")
    cur.execute("SELECT v13_build_tinql(%s)", ("quasar",))
    cur.fetchone()
    cur.execute("SELECT count(*) FROM v13_recall(%s,8)", (tinql_q,))
    cur.fetchone()
    cur.execute("SELECT count(*) FROM chunks")
    check("H1: recall SELECT chunks", cur.fetchone()[0] >= 0)
    cur.execute("RESET ROLE")
    cur.execute("SELECT has_table_privilege('v13_recall','chunks','INSERT')")
    check("H1: recall no INSERT", cur.fetchone()[0] is False)
    cur.execute("SELECT has_table_privilege('v13_recall','chunks','UPDATE')")
    check("H1: recall no UPDATE", cur.fetchone()[0] is False)

    guc(cur)
    cur.execute("SET ROLE v13_resolve")
    cur.execute("SELECT v13_recall_candidates(%s)", (sid_h,))
    cur.fetchone()
    cur.execute("SELECT v13_judgment_envelope(%s)", (sid_h,))
    cur.fetchone()
    cur.execute("SELECT count(*) FROM chunks")
    check("H2: resolve SELECT chunks", cur.fetchone()[0] >= 0)
    cur.execute("RESET ROLE")
    cur.execute("SELECT has_table_privilege('v13_resolve','chunks','INSERT')")
    check("H2: resolve no INSERT", cur.fetchone()[0] is False)

    cur.execute("SET ROLE v13_route")
    cur.execute("SELECT v13_recall_candidates(%s)", (sid_h,))
    cur.fetchone()
    cur.execute("SELECT v13_assemble_manifest(%s)", (sid_h,))
    cur.fetchone()
    cur.execute("RESET ROLE")
    cur.execute("SELECT has_table_privilege('v13_route','chunks','INSERT')")
    check("H3: route no INSERT", cur.fetchone()[0] is False)
    for sig in (
        "v13_query_segments(text)",
        "v13_build_tinql(text)",
        "v13_tinql_terms(text)",
        "v13_recall(text,int)",
        "v13_recall_count(text)",
        "v13_recall_candidates(uuid)",
    ):
        cur.execute("SELECT has_function_privilege('public', %s, 'EXECUTE')", (sig,))
        check(f"H3: PUBLIC no {sig}", cur.fetchone()[0] is False)

    cur.execute("SET ROLE v13_resolve")
    cur.execute("SELECT v13_context_required(%s)", (sid_h,))
    tok = cur.fetchone()[0]
    cur.execute("RESET ROLE")
    check("H4: token nine keys", keys_of(tok) == TOKEN9, keys_of(tok))

    # ----- I load boundary -----
    check("I1: chunks prefix 7", len(files_through("chunks")) == 7)
    check("I1: recall prefix 8", len(files_through("recall")) == 8)
    check("I1: recall not in chunks prefix",
          all("recall" not in p.name for p in files_through("chunks")))
    cur.execute("SELECT 1 FROM pg_database WHERE datname='agent_v13_chunks'")
    if cur.fetchone():
        cch = psycopg2.connect(server.get_uri("agent_v13_chunks"))
        kch = cch.cursor()
        kch.execute(
            "SELECT count(*) FROM pg_proc WHERE proname='v13_recall'")
        check("I1: chunks db has no v13_recall", kch.fetchone()[0] == 0)
        kch.execute("SELECT v13_context_required(%s)", (str(uuid.uuid4()),))
        try:
            kch.execute("INSERT INTO sessions (session_id) VALUES (%s) RETURNING session_id",
                        (str(uuid.uuid4()),))
            sid_ch = kch.fetchone()[0]
            kch.execute("SELECT v13_context_required(%s)", (sid_ch,))
            tok8 = kch.fetchone()[0]
            check("I1: chunks token eight keys",
                  "recall_ver" not in tok8 and len(tok8) == 8, tok8)
        finally:
            cch.rollback()
            cch.close()

    sid_i2 = new_session(cur)
    append_user(cur, sid_i2, "quasar")
    cur.execute("SELECT v13_context_required(%s)", (sid_i2,))
    tok9 = cur.fetchone()[0]
    eight = {k: tok9[k] for k in tok9 if k != "recall_ver"}
    cur.execute(
        "UPDATE sessions SET context_active_revision=%s::jsonb WHERE session_id=%s",
        (json.dumps(eight), sid_i2))
    cur.execute("SELECT v13_context_fresh(%s)", (sid_i2,))
    check("I2: eight-key token not fresh", cur.fetchone()[0] is False)
    _, _, _, conn, cur = parse_settle(server, conn, cur, sid_i2)
    cur.execute("SELECT v13_context_fresh(%s)", (sid_i2,))
    check("I2: fresh after one settle", cur.fetchone()[0] is True)
    cur.execute("SELECT context_active_revision FROM sessions WHERE session_id=%s",
                (sid_i2,))
    stored = cur.fetchone()[0]
    check("I2: stored nine keys", keys_of(stored) == TOKEN9, stored)

    cur.execute("SELECT value FROM v13_policies WHERE name='recall_k' AND active")
    rk_now = cur.fetchone()[0]
    bump_policy(cur, "recall_k", {**rk_now, "k_max": 16})
    conn.commit()
    cur.execute("SELECT v13_context_fresh(%s)", (sid_i2,))
    check("I3: recall_ver flip not fresh", cur.fetchone()[0] is False)
    _, _, _, conn, cur = parse_settle(server, conn, cur, sid_i2)
    man_i3 = active_manifest(cur, sid_i2)
    check("I3: candidates truncated",
          len(man_i3["query_side"]["candidates"]) <= 16,
          len(man_i3["query_side"]["candidates"]))
    bump_policy(cur, "recall_k", rk_now)
    conn.commit()

    cur.execute(
        "UPDATE v13_policies SET active=false WHERE name='recall_k' AND active")
    fails_with(cur, "SELECT v13_context_required(%s)", (sid_i2,),
               "no active recall_k policy", "I4: missing recall_k",
               pgcode="P0001")
    cur.execute(
        "UPDATE v13_policies SET active=true WHERE name='recall_k' AND version=1")
    conn.commit()

    # ----- J k cap ledger -----
    sid_j = new_session(cur)
    append_user(cur, sid_j, "maxium")
    cur.execute("SELECT v13_recall_candidates(%s)", (sid_j,))
    j1 = cur.fetchone()[0]
    check("J1: matched=4000", j1["matched"] == 4000, j1)
    check("J1: k stays 64", j1["k"] == 64, j1)
    for line in ("k_base", "k_max", "1 批", "2 批", "DP7"):
        check(f"J2: README ledger {line}", line in readme)

    conn.close()
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
