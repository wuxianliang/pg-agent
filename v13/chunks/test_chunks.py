"""DP4 gate: chunks projection & span assembly.

Run: uv run python v13/chunks/test_chunks.py  (exit 0 = pass)
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
from v13.chunks.setup_db import DB, main as setup_db
from v13.load import SQL_LOAD_ORDER, files_through

HEX64 = re.compile(r"^[0-9a-f]{64}$")
TOKEN8 = {"sem", "dec", "goal", "tools_rev", "asm_ver", "jdef_ver", "gen_ver", "corpus"}
INGEST_KEYS = {
    "source_hash", "artifact_id", "chunk_count", "locked", "unchanged", "generation",
}
REBUILD_KEYS = {"sources", "reprojected", "locked", "rows_inserted", "chunker_version"}
GC_DRY_KEYS = {"mode", "deletable_by_corpus"}
GC_DEL_KEYS = {"mode", "deleted_rows"}
PARA_V1 = {
    "chunker_version": "para_v1",
    "analyzer_version": "tsv_english_1",
    "mode": "para",
    "target_bytes": 3072,
    "max_chunk_bytes": 1048576,
    "max_doc_bytes": 1048576,
}
WHOLE_V1 = {
    "chunker_version": "whole_v1",
    "analyzer_version": "tsv_english_1",
    "mode": "whole",
    "target_bytes": 3072,
    "max_chunk_bytes": 1048576,
    "max_doc_bytes": 1048576,
}


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    extra = f": {detail}" if detail and (not condition or len(str(detail)) < 200) else ""
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


_SQL_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_SQL_LINE_COMMENT = re.compile(r"--[^\n]*")


def strip_sql_comments(src: str) -> str:
    return _SQL_LINE_COMMENT.sub(" ", _SQL_BLOCK_COMMENT.sub(" ", src))


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
    cur.execute("SET search_path TO public, pg_catalog")
    cur.execute("SELECT set_config('typesafe.provider', 'mock', false)")
    cur.execute("SELECT set_config('typesafe.model', 'jev-mock', false)")


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


def poison(cur) -> None:
    cur.execute("SELECT set_config('typesafe.mock_response', NULL, true)")
    cur.execute("SELECT set_config('typesafe.endpoint', 'http://127.0.0.1:1/', true)")
    cur.execute("SELECT set_config('typesafe.api_key', 'probe', true)")
    cur.execute("SELECT set_config('typesafe.timeout_ms', '200', true)")


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


def seed_asm():
    return {
        "budget_tokens": 8192, "est_bytes_per_token": 4,
        "priority_overrides": {}, "kinds_disabled": [],
        "inline_max_bytes": 1048576, "blob_retention": "referenced-forever",
    }


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


def wait_ungranted_advisory(watch, pid, timeout=8.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        watch.execute(
            "SELECT bool_or(NOT granted) FROM pg_locks "
            "WHERE locktype='advisory' AND pid=%s", (pid,))
        row = watch.fetchone()
        if row and row[0] is True:
            return True
        time.sleep(0.02)
    return False


def wait_box_advisory(watch, box, key="pid", timeout=8.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        pid = box.get(key)
        if pid and wait_ungranted_advisory(watch, pid, timeout=0.12):
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


def run_j1(cur, conn, corpus, tag):
    body = para_doc(10, 40, f"{tag}-quasar")
    out, _, _ = ingest_doc(cur, body, corpus)
    conn.commit()
    src = out["source_hash"]
    cur.execute(
        "SELECT content_hash FROM chunks WHERE source_hash=%s "
        "ORDER BY chunk_no LIMIT 1", (src,))
    h = cur.fetchone()[0]
    land_context(cur, h)
    conn.commit()
    cur.execute("SELECT v13_rebuild_chunks(%s)", (corpus,))
    rb = cur.fetchone()[0]
    cur.execute(
        "SELECT count(*) FROM chunks WHERE source_hash=%s AND content_hash=%s",
        (src, h))
    check(f"{tag}: referenced row survives rebuild", cur.fetchone()[0] >= 1)
    check(f"{tag}: locked incremented", rb["locked"] >= 1, rb)
    conn.commit()


def run_j2(server, cur, conn, corpus, tag):
    body = para_doc(8, 30, f"{tag}-quasar")
    out, eid, _ = ingest_doc(cur, body, corpus)
    conn.commit()
    src = out["source_hash"]
    cur.execute(
        "SELECT content_hash FROM chunks WHERE source_hash=%s "
        "ORDER BY chunk_no LIMIT 1", (src,))
    h = cur.fetchone()[0]
    box = {}

    def hold_ref():
        c = psycopg2.connect(server.get_uri(DB))
        c.autocommit = False
        k = c.cursor()
        guc(k)
        k.execute("SELECT pg_backend_pid()")
        box["hold_pid"] = k.fetchone()[0]
        inline = {"query_side": {"candidates": [{"content_hash": h}]}}
        k.execute("SELECT v13_artifact_land(%s,'context',%s::jsonb)",
                  (eid, json.dumps(inline)))
        k.fetchone()
        box["held"] = True
        while not box.get("release"):
            time.sleep(0.02)
        c.commit()
        c.close()

    def run_rebuild():
        c = psycopg2.connect(server.get_uri(DB))
        c.autocommit = False
        k = c.cursor()
        guc(k)
        k.execute("SELECT pg_backend_pid()")
        box["pid"] = k.fetchone()[0]
        try:
            k.execute("SELECT v13_rebuild_chunks(%s)", (corpus,))
            box["rb"] = k.fetchone()[0]
            c.commit()
            box["ok"] = True
        except Exception as exc:
            box["err"] = str(exc)
            c.rollback()
        c.close()

    t_hold = threading.Thread(target=hold_ref)
    t_hold.start()
    t0 = time.time()
    while time.time() - t0 < 5 and not box.get("held"):
        time.sleep(0.02)
    check(f"{tag}: holder acquired", box.get("held") is True, box)
    t_rb = threading.Thread(target=run_rebuild)
    t_rb.start()
    blocked = wait_box_advisory(cur, box, timeout=6)
    aux = False
    pid = box.get("pid")
    if pid:
        cur.execute(
            "SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s", (pid,))
        row = cur.fetchone()
        aux = bool(row and row[0] == "Lock")
    check(f"{tag}: rebuild pid ungranted advisory", blocked,
          {"box": box, "aux_Lock": aux})
    box["release"] = True
    t_hold.join(8)
    t_rb.join(15)
    check(f"{tag}: rebuild finished", box.get("ok") is True, box)
    cur.execute(
        "SELECT count(*) FROM chunks WHERE source_hash=%s AND content_hash=%s",
        (src, h))
    check(f"{tag}: row survived TOCTOU window", cur.fetchone()[0] >= 1)
    conn.commit()


def run_j3(server, cur, conn, corpus, tag, reverse=False):
    body = para_doc(6, 25, f"{tag}-quasar")
    out, eid, _ = ingest_doc(cur, body, corpus)
    conn.commit()
    src = out["source_hash"]
    box = {}

    def hold_rebuild():
        c = psycopg2.connect(server.get_uri(DB))
        c.autocommit = False
        k = c.cursor()
        guc(k)
        k.execute("SELECT pg_backend_pid()")
        box["hold_pid"] = k.fetchone()[0]
        k.execute("SELECT v13_rebuild_chunks(%s)", (corpus,))
        k.fetchone()
        box["held"] = True
        while not box.get("release"):
            time.sleep(0.02)
        c.commit()
        c.close()

    def hold_ingest():
        c = psycopg2.connect(server.get_uri(DB))
        c.autocommit = False
        k = c.cursor()
        guc(k)
        k.execute("SELECT pg_backend_pid()")
        box["hold_pid"] = k.fetchone()[0]
        try:
            k.execute("SELECT v13_ingest_document(%s,%s,%s)",
                      (eid, corpus, body))
            box["out"] = k.fetchone()[0]
            box["held"] = True
            while not box.get("release"):
                time.sleep(0.02)
            c.commit()
        except Exception as exc:
            box["err"] = str(exc)
            box["pgcode"] = getattr(exc, "pgcode", None)
            c.rollback()
        c.close()

    def run_ingest():
        c = psycopg2.connect(server.get_uri(DB))
        c.autocommit = False
        k = c.cursor()
        guc(k)
        k.execute("SELECT pg_backend_pid()")
        box["pid"] = k.fetchone()[0]
        try:
            k.execute("SELECT v13_ingest_document(%s,%s,%s)",
                      (eid, corpus, body))
            box["out"] = k.fetchone()[0]
            c.commit()
            box["ok"] = True
        except Exception as exc:
            box["err"] = str(exc)
            box["pgcode"] = getattr(exc, "pgcode", None)
            c.rollback()
        c.close()

    def run_rebuild():
        c = psycopg2.connect(server.get_uri(DB))
        c.autocommit = False
        k = c.cursor()
        guc(k)
        k.execute("SELECT pg_backend_pid()")
        box["pid"] = k.fetchone()[0]
        try:
            k.execute("SELECT v13_rebuild_chunks(%s)", (corpus,))
            box["rb"] = k.fetchone()[0]
            c.commit()
            box["ok"] = True
        except Exception as exc:
            box["err"] = str(exc)
            box["pgcode"] = getattr(exc, "pgcode", None)
            c.rollback()
        c.close()

    if reverse:
        t_h = threading.Thread(target=hold_ingest)
        t_w = threading.Thread(target=run_rebuild)
        hold_lbl = f"{tag}: ingest holding"
        wait_lbl = f"{tag}: rebuild queued behind ingest"
        done_lbl = f"{tag}: rebuild done no 23505"
    else:
        t_h = threading.Thread(target=hold_rebuild)
        t_w = threading.Thread(target=run_ingest)
        hold_lbl = f"{tag}: rebuild holding"
        wait_lbl = f"{tag}: ingest queued behind rebuild"
        done_lbl = f"{tag}: ingest done no 23505"

    t_h.start()
    t0 = time.time()
    while time.time() - t0 < 8 and not box.get("held"):
        time.sleep(0.02)
    check(hold_lbl, box.get("held") is True, box)
    t_w.start()
    blocked = wait_box_lock(cur, box, timeout=6)
    check(wait_lbl, blocked, box)
    box["release"] = True
    t_h.join(8)
    t_w.join(15)
    check(done_lbl,
          box.get("ok") is True and box.get("pgcode") != "23505", box)
    cur.execute(
        "SELECT count(*), count(DISTINCT chunker_version), "
        "bool_and(content_hash = v13_body_hash(body)) "
        "FROM chunks WHERE source_hash=%s", (src,))
    nj, nver, selfc = cur.fetchone()
    cur.execute("SELECT v13_chunker_slice(%s, %s::jsonb)",
                (body, json.dumps(PARA_V1)))
    expect_n = len(cur.fetchone()[0])
    check(f"{tag}: one generation of slices",
          nj == expect_n and nver == 1, (nj, nver, expect_n))
    check(f"{tag}: self-cert", selfc is True)
    cur.execute("SELECT v13_verify_chunks(false)")
    check(f"{tag}: verify green", cur.fetchone()[0]["all_ok"] is True)
    conn.commit()


def para_doc(n=20, width=80, tag="quasar"):
    parts = [f"{tag} paragraph {i:04d} " + ("x" * width) for i in range(n)]
    return "\n\n".join(parts)


def p99_ms(cur, n=2000) -> float:
    sid = new_session(cur)
    times = []
    for i in range(n):
        t0 = time.perf_counter()
        cur.execute(
            "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
            (sid, u(), json.dumps({"text": f"m{i}"})))
        cur.fetchone()
        times.append((time.perf_counter() - t0) * 1000.0)
    times.sort()
    return times[int(n * 0.99) - 1]


def median3(vals):
    s = sorted(vals)
    return s[1]


def keys_of(obj) -> set:
    if isinstance(obj, str):
        obj = json.loads(obj)
    return set(obj)


def main() -> int:
    setup_db()
    server = get_server()
    conn = psycopg2.connect(server.get_uri(DB))
    conn.autocommit = False
    cur = conn.cursor()
    guc(cur)

    p99_base_rounds = []
    for _ in range(3):
        p99_base_rounds.append(p99_ms(cur, 2000))
        conn.commit()
    p99_base = median3(p99_base_rounds)

    # ----- A -----
    body_a = para_doc(8, 40, "quasar")
    out_a, eid_a, sid_a = ingest_doc(cur, body_a, "docs")
    conn.commit()
    check("B1: ingest keys", keys_of(out_a) == INGEST_KEYS, keys_of(out_a))
    check("B1: not locked", out_a["locked"] is False, out_a)
    check("B1: hex source", bool(HEX64.match(out_a["source_hash"])), out_a["source_hash"])

    cur.execute(
        "SELECT bool_and(content_hash = v13_body_hash(body)), count(*) FROM chunks")
    ok_hash, n_chunks = cur.fetchone()
    check("A1: full table self-cert", ok_hash is True and n_chunks > 0, (ok_hash, n_chunks))

    cur.execute(
        "SELECT bool_and(EXISTS (SELECT 1 FROM artifacts a "
        "WHERE a.content_hash = c.content_hash AND a.kind='chunk')) FROM chunks c")
    check("A3: exists chunk artifact", cur.fetchone()[0] is True)

    cur.execute("SELECT source_hash, chunk_no, content_hash FROM chunks LIMIT 1")
    sh, cno, ch = cur.fetchone()
    fails_with(cur,
               "INSERT INTO chunks (source_hash, chunk_no, body, content_hash, "
               "chunk_offset, corpus, chunker_version, analyzer_version) "
               "VALUES (%s, 9999, 'other-body', %s, 0, 'docs', 'para_v1', 'tsv_english_1')",
               (sh, ch),
               "v13_chunks_hash_selfcheck",
               "A2: bad hash rejected", pgcode="23514")
    cur.execute("SELECT v13_body_hash(%s)", ("no-artifact-body",))
    ghost = cur.fetchone()[0]
    fails_with(cur,
               "INSERT INTO chunks (source_hash, chunk_no, body, content_hash, "
               "chunk_offset, corpus, chunker_version, analyzer_version) "
               "VALUES (%s, 9998, 'no-artifact-body', %s, 0, 'docs', 'para_v1', "
               "'tsv_english_1')",
               (sh, ghost),
               "kind='chunk' artifact",
               "A2: missing artifact rejected", pgcode="V3004")

    fails_with(cur, "UPDATE chunks SET corpus='x' WHERE source_hash=%s",
               (sh,), "immutable", "A4: UPDATE rejected", pgcode="V3004")
    fails_with(cur, "TRUNCATE chunks", (), "TRUNCATE chunks is forbidden",
               "A4: TRUNCATE rejected", pgcode="V3004")

    bump_policy(cur, "chunks_ingest", WHOLE_V1)
    whole_body = "quasar whole document body"
    out_w, _, _ = ingest_doc(cur, whole_body, "whole-corpus")
    cur.execute(
        "SELECT content_hash, source_hash, chunk_no, chunk_offset, count(*) OVER () "
        "FROM chunks WHERE source_hash=%s", (out_w["source_hash"],))
    row_w = cur.fetchone()
    check("A5: single chunk 0", row_w[2] == 0 and row_w[4] == 1, row_w)
    check("A5: content_hash = source_hash", row_w[0] == row_w[1], row_w)
    check("A5: chunk_offset=0", row_w[3] == 0, row_w)
    bump_policy(cur, "chunks_ingest", PARA_V1)
    conn.commit()

    # ----- B -----
    conn, cur = recycle(server, conn)
    cur.execute("SET enable_seqscan = off")
    cur.execute(
        "EXPLAIN (COSTS OFF) SELECT 1 FROM chunks "
        "WHERE body_tsv @@ websearch_to_tsquery('english'::regconfig, 'quasar')")
    plan_b2 = "\n".join(r[0] for r in cur.fetchall())
    check("B2: insert-visible index", "ix_chunks_tsv" in plan_b2, plan_b2)
    cur.execute(
        "SELECT count(*) FROM chunks WHERE body_tsv @@ "
        "websearch_to_tsquery('english'::regconfig, 'quasar')")
    check("B2: quasar hits", cur.fetchone()[0] > 0)
    cur.execute("SET enable_seqscan = on")

    cur.execute("SELECT count(*) FROM chunks")
    n_before = cur.fetchone()[0]
    cur.execute("SELECT generation FROM v13_chunks_meta WHERE singleton")
    gen_before = cur.fetchone()[0]
    cA = psycopg2.connect(server.get_uri(DB))
    cA.autocommit = False
    kA = cA.cursor()
    guc(kA)
    ingest_doc(kA, "quasar rollback-only document", "rb")
    cB = psycopg2.connect(server.get_uri(DB))
    cB.autocommit = False
    kB = cB.cursor()
    kB.execute("SELECT count(*) FROM chunks")
    check("B3: other conn sees old count", kB.fetchone()[0] == n_before)
    cA.rollback()
    cA.close()
    conn, cur = recycle(server, conn)
    cur.execute("SELECT count(*) FROM chunks")
    check("B3: rollback zero residue", cur.fetchone()[0] == n_before)
    cur.execute("SELECT generation FROM v13_chunks_meta WHERE singleton")
    check("B3: generation no drift", cur.fetchone()[0] == gen_before)
    cB.close()

    snap_rows = None
    cur.execute(
        "SELECT array_agg(to_jsonb(c) ORDER BY source_hash, chunk_no) FROM chunks c "
        "WHERE source_hash=%s", (out_a["source_hash"],))
    snap_rows = cur.fetchone()[0]
    out_idem, _, _ = ingest_doc(cur, body_a, "docs")
    cur.execute(
        "SELECT array_agg(to_jsonb(c) ORDER BY source_hash, chunk_no) FROM chunks c "
        "WHERE source_hash=%s", (out_a["source_hash"],))
    check("B4: unreferenced reingest same rows", cur.fetchone()[0] == snap_rows)
    check("B4: generation may bump", "generation" in out_idem, out_idem)
    conn.commit()

    body_v1 = para_doc(12, 50, "alpha")
    out_v1, _, _ = ingest_doc(cur, body_v1, "docs")
    old_src = out_v1["source_hash"]
    body_v2 = para_doc(12, 50, "beta")
    out_v2, _, _ = ingest_doc(cur, body_v2, "docs", supersedes=old_src)
    new_src = out_v2["source_hash"]
    check("B5: new source different", new_src != old_src)
    cur.execute("SELECT count(*) FROM chunks WHERE source_hash=%s", (old_src,))
    check("B5: old unreferenced rows gone", cur.fetchone()[0] == 0)
    cur.execute("SELECT count(*) FROM chunks WHERE source_hash=%s", (new_src,))
    check("B5: new source rows present", cur.fetchone()[0] > 0)
    cur.execute(
        "SELECT superseded_by FROM v13_sources WHERE source_hash=%s", (old_src,))
    check("B5: lineage marked", cur.fetchone()[0] == new_src)
    conn.commit()

    cur.execute("SELECT v13_rebuild_chunks()")
    cur.fetchone()
    cur.execute("SELECT count(*) FROM chunks WHERE source_hash=%s", (old_src,))
    check("B5b: rebuild does not resurrect", cur.fetchone()[0] == 0)
    bump_policy(cur, "chunk_gc", {"mode": "delete-unreferenced"})
    cur.execute("SELECT v13_chunk_gc(false)")
    gc_del = cur.fetchone()[0]
    check("B5b: gc delete keys", keys_of(gc_del) == GC_DEL_KEYS, keys_of(gc_del))
    cur.execute("SELECT count(*) FROM chunks WHERE source_hash=%s", (old_src,))
    check("B5b: gc skips retired source", cur.fetchone()[0] == 0)
    bump_policy(cur, "chunk_gc", {"mode": "dry-run-only"})
    fails_with(cur, "UPDATE v13_sources SET corpus='x' WHERE source_hash=%s",
               (old_src,), "append-only", "B5b: corpus mutate rejected",
               pgcode="V3004")
    fails_with(cur, "UPDATE v13_sources SET superseded_by=%s WHERE source_hash=%s",
               (u().replace("-", ""), old_src), "append-only",
               "B5b: superseded_by rewrite rejected", pgcode="V3004")
    fails_with(cur, "DELETE FROM v13_sources WHERE source_hash=%s",
               (old_src,), "append-only", "B5b: DELETE rejected",
               pgcode="V3004")
    conn.commit()

    body_mix = para_doc(24, 200, "mix-quasar")
    out_mix, _, _ = ingest_doc(cur, body_mix, "mix")
    old_mix = out_mix["source_hash"]
    cur.execute(
        "SELECT content_hash FROM chunks WHERE source_hash=%s ORDER BY chunk_no",
        (old_mix,))
    mix_hashes = [r[0] for r in cur.fetchall()]
    check("B5mix: multiple chunks", len(mix_hashes) >= 2, len(mix_hashes))
    href, hdead = mix_hashes[0], mix_hashes[1]
    land_context(cur, href)
    conn.commit()
    body_mix2 = para_doc(24, 200, "mix-beta")
    ingest_doc(cur, body_mix2, "mix", supersedes=old_mix)
    cur.execute(
        "SELECT count(*) FROM chunks WHERE source_hash=%s AND content_hash=%s",
        (old_mix, href))
    check("B5mix: referenced row lives", cur.fetchone()[0] == 1)
    cur.execute(
        "SELECT count(*) FROM chunks WHERE source_hash=%s AND content_hash=%s",
        (old_mix, hdead))
    check("B5mix: unreferenced sibling gone", cur.fetchone()[0] == 0)
    cur.execute("SELECT count(*) FROM chunks WHERE source_hash=%s", (old_mix,))
    n_left = cur.fetchone()[0]
    check("B5mix: only referenced remain", n_left >= 1, n_left)
    bump_policy(cur, "chunks_ingest", {**PARA_V1, "target_bytes": 512})
    cur.execute("SELECT v13_rebuild_chunks()")
    cur.fetchone()
    cur.execute("SELECT count(*) FROM chunks WHERE source_hash=%s", (old_mix,))
    check("B5mix: rebuild adds no rows to retired", cur.fetchone()[0] == n_left)
    bump_policy(cur, "chunks_ingest", PARA_V1)
    conn.commit()

    fails_with(cur, "SELECT v13_ingest_document(%s,%s,%s)",
               (eid_a, "other-corpus", body_a),
               "already bound to another corpus", "B6: corpus conflict",
               pgcode="V3004")

    # ----- C -----
    cjk = "前quasar后"
    cur.execute("SELECT v13_extract_spans(%s, %s::jsonb)",
                (cjk, json.dumps(["quasar"])))
    ext = cur.fetchone()[0]
    check("C1a: offsets array", isinstance(ext, list) and ext and isinstance(ext[0], list), ext)
    check("C1a: no doc key", all(not isinstance(x, dict) for x in ext), ext)
    cur.execute("SELECT octet_length(left(%s, 1)) + 1", (cjk,))
    expect_start = cur.fetchone()[0]
    check("C1a: CJK byte start", ext[0][0] == expect_start, (ext, expect_start))
    check("C1a: sorted 1-based", ext[0][0] >= 1 and ext[0][1] >= ext[0][0], ext)

    cur.execute("SELECT v13_body_hash(%s)", (cjk,))
    cjk_h = cur.fetchone()[0]
    units = [{"content_hash": cjk_h, "body": cjk, "spans": ext}]
    cur.execute("SELECT v13_assemble_spans(%s::jsonb, %s::jsonb)",
                (json.dumps(units), json.dumps({"mode": "span", "boundary": "none",
                                                 "context_bytes": 0, "merge_gap_bytes": 0,
                                                 "fence_aware": False, "table_aware": False})))
    assembled = cur.fetchone()[0]
    check("C1b: keys {doc,offsets}",
          all(set(x.keys()) == {"doc", "offsets"} for x in assembled), assembled)
    check("C1b: doc hex", all(HEX64.match(x["doc"]) for x in assembled), assembled)
    blob = json.dumps(assembled)
    check("C1b: no source_hash/chunk_no",
          "source_hash" not in blob and "chunk_no" not in blob, blob)

    cur.execute("SELECT v13_rebuild_chunks(NULL)")
    rb = cur.fetchone()[0]
    check("C2: rebuild keys", keys_of(rb) == REBUILD_KEYS, keys_of(rb))
    cur.execute("SELECT v13_chunk_gc(true)")
    gcd = cur.fetchone()[0]
    check("C2: gc dry keys", keys_of(gcd) == GC_DRY_KEYS, keys_of(gcd))
    check("C2: ingest keys whitelist", keys_of(out_a) == INGEST_KEYS)

    fake = [{"source_hash": "x", "chunk_no": 0}]
    cur.execute("SELECT v13_assemble_spans(%s::jsonb, '{}'::jsonb)",
                (json.dumps([{"content_hash": cjk_h, "body": "abc",
                              "spans": [[1, 2]]}]),))
    produced = json.dumps(cur.fetchone()[0])
    check("C3: assemble cannot emit source_hash/chunk_no",
          "source_hash" not in produced and "chunk_no" not in produced, produced)
    check("C3: fake inventory is not assemble output", fake != json.loads(produced) if produced else True)

    # ----- D -----
    body_da = para_doc(24, 90, "docA-quasar")
    body_db = para_doc(24, 90, "docB-quasar")
    out_da, _, _ = ingest_doc(cur, body_da, "replay")
    out_db, _, _ = ingest_doc(cur, body_db, "replay")
    src_da, src_db = out_da["source_hash"], out_db["source_hash"]
    cur.execute(
        "SELECT content_hash FROM chunks WHERE source_hash=%s ORDER BY chunk_no LIMIT 1",
        (src_da,))
    h1 = cur.fetchone()[0]
    cur.execute(
        "SELECT count(*), array_agg(to_jsonb(c) ORDER BY chunk_no) "
        "FROM chunks c WHERE source_hash=%s", (src_db,))
    n_db1, rows_db1 = cur.fetchone()
    art_id, _ = land_context(cur, h1)
    conn.commit()
    cur.execute("SELECT v13_chunk_referenced(%s)", (h1,))
    check("D1: referenced true", cur.fetchone()[0] is True)
    cur.execute("SELECT v13_body_hash(%s)", ("never-referenced",))
    cur.execute("SELECT v13_chunk_referenced(%s)", (cur.fetchone()[0],))
    check("D1: unreferenced false", cur.fetchone()[0] is False)

    fails_with(cur, "DELETE FROM chunks WHERE content_hash=%s", (h1,),
               "referenced", "D2: referenced delete rejected", pgcode="V3004")
    out_del, _, _ = ingest_doc(cur, "quasar disposable-delete", "tmp")
    cur.execute("DELETE FROM chunks WHERE source_hash=%s", (out_del["source_hash"],))
    check("D2: unreferenced delete ok", cur.rowcount > 0)
    conn.commit()

    cur.execute("SELECT v13_chunk_gc(true)")
    dry = cur.fetchone()[0]
    cur.execute(
        "SELECT corpus, count(*) FROM chunks c "
        "WHERE NOT v13_chunk_referenced(c.content_hash) GROUP BY corpus")
    expect_dry = {r[0]: r[1] for r in cur.fetchall()}
    got_dry = {k: int(v) for k, v in (dry.get("deletable_by_corpus") or {}).items()}
    check("D3: dry-run matches unreferenced", got_dry == expect_dry, (got_dry, expect_dry))
    cur.execute("SELECT count(*) FROM chunks")
    n_pre_gc = cur.fetchone()[0]
    cur.execute("SELECT v13_chunk_gc(false)")
    cur.fetchone()
    cur.execute("SELECT count(*) FROM chunks")
    check("D3: dry-run-only gc(false) deletes zero", cur.fetchone()[0] == n_pre_gc)

    cur.execute("SELECT v13_chunk_referenced(%s)", (h1,))
    check("D4: lock established", cur.fetchone()[0] is True)
    cur.execute("SELECT inline::text FROM artifacts WHERE content_hash=%s AND kind='chunk'",
                (h1,))
    inline_before = cur.fetchone()[0]
    cur.execute("SELECT v13_replay(%s)", (art_id,))
    replay_before = cur.fetchone()[0]
    v2 = dict(PARA_V1)
    v2["target_bytes"] = 512
    bump_policy(cur, "chunks_ingest", v2)
    cur.execute("SELECT v13_rebuild_chunks()")
    rb4 = cur.fetchone()[0]
    check("D4(i): docA locked", rb4["locked"] >= 1, rb4)
    cur.execute(
        "SELECT content_hash FROM chunks WHERE source_hash=%s ORDER BY chunk_no LIMIT 1",
        (src_da,))
    check("D4(i): docA hash unchanged", cur.fetchone()[0] == h1)
    cur.execute("SELECT v13_replay(%s)", (art_id,))
    check("D4(ii): replay bytes unchanged", cur.fetchone()[0] == replay_before)
    cur.execute("SELECT inline::text FROM artifacts WHERE content_hash=%s AND kind='chunk'",
                (h1,))
    check("D4(iii): artifact bytes unchanged", cur.fetchone()[0] == inline_before)
    cur.execute(
        "SELECT count(*), bool_and(chunker_version='para_v1'), "
        "array_agg(to_jsonb(c) ORDER BY chunk_no) "
        "FROM chunks c WHERE source_hash=%s", (src_db,))
    n_db2, all_para, rows_db2 = cur.fetchone()
    check("D4(iv): docB recut count>", n_db2 > n_db1, (n_db2, n_db1))
    check("D4(iv): rows differ", rows_db2 != rows_db1)
    check("D4(iv): chunker still para_v1", all_para is True)
    cur.execute(
        "SELECT (a.inline #>> '{}') FROM v13_sources s "
        "JOIN artifacts a ON a.artifact_id=s.artifact_id WHERE s.source_hash=%s",
        (src_db,))
    db_body = cur.fetchone()[0]
    cur.execute("SELECT v13_policy('chunks_ingest')")
    pol_v2 = cur.fetchone()[0]
    cur.execute("SELECT v13_chunker_slice(%s, %s::jsonb)", (db_body, json.dumps(pol_v2)))
    sliced = cur.fetchone()[0]
    cur.execute(
        "SELECT jsonb_agg(jsonb_build_object('chunk_no', chunk_no, 'body', body, "
        "'chunk_offset', chunk_offset) ORDER BY chunk_no) FROM chunks WHERE source_hash=%s",
        (src_db,))
    got_slice = cur.fetchone()[0]
    check("D4(iv): matches chunker_slice", got_slice == sliced, (got_slice, sliced))
    conn.commit()

    fails_with(cur, "SELECT v13_ingest_document(%s,%s,%s)",
               (eid_a, "replay", body_da),
               "retention-locked", "D5: locked rejects different slice",
               pgcode="V3004")
    bump_policy(cur, "chunks_ingest", PARA_V1)
    conn.commit()

    # ----- E -----
    cur.execute("SELECT v13_rebuild_chunks()")
    r1 = cur.fetchone()[0]
    cur.execute(
        "SELECT array_agg(to_jsonb(c) ORDER BY source_hash, chunk_no) FROM chunks c")
    snap1 = cur.fetchone()[0]
    cur.execute("SELECT v13_rebuild_chunks()")
    r2 = cur.fetchone()[0]
    cur.execute(
        "SELECT array_agg(to_jsonb(c) ORDER BY source_hash, chunk_no) FROM chunks c")
    snap2 = cur.fetchone()[0]
    check("E1: rebuild twice byte-equal", snap1 == snap2)
    check("E1: locked count stable", r1["locked"] == r2["locked"], (r1, r2))

    cur.execute("SELECT v13_rebuild_chunks(%s)", ("no-such-corpus",))
    empty_rb = cur.fetchone()[0]
    check("E2: unmatched corpus sources=0", empty_rb["sources"] == 0, empty_rb)

    cur.execute("SELECT v13_verify_chunks(false)")
    ver = cur.fetchone()[0]
    names = [c["name"] for c in ver["checks"]]
    check("E3: seven checks", len(ver["checks"]) == 7, names)
    check("E3: all_ok", ver["all_ok"] is True, ver)
    check("E3: version 1", ver["version"] == 1, ver)
    check("E3: every ok", all(c["ok"] is True for c in ver["checks"]), ver)
    sid_echo = new_session(cur)
    append_user(cur, sid_echo, "goal echo only")
    _, eid_echo, _, conn, cur = parse_settle(server, conn, cur, sid_echo)
    cur.execute("SELECT v13_verify_chunks(false)")
    ver_echo = cur.fetchone()[0]
    check("E3: goal-echo verify green", ver_echo["all_ok"] is True, ver_echo)
    check("E5: version key present", "version" in ver)

    cur.execute("SAVEPOINT e4")
    ghost_body = "orphan-chunk-body-e4"
    cur.execute("SELECT v13_body_hash(%s)", (ghost_body,))
    gh4 = cur.fetchone()[0]
    eid4, _ = succeed_tool(cur)
    cur.execute(
        "INSERT INTO artifacts (content_hash, kind, inline, size, produced_by) "
        "VALUES (%s, 'chunk', to_jsonb(%s::text), octet_length(to_jsonb(%s::text)::text), %s)",
        (gh4, ghost_body, ghost_body, eid4))
    land_context(cur, gh4, eid4)
    cur.execute("SELECT v13_verify_chunks(false)")
    ver4 = cur.fetchone()[0]
    byn = {c["name"]: c["ok"] for c in ver4["checks"]}
    check("E4: reference_resolvable red", byn.get("reference_resolvable") is False, byn)
    check("E4: artifact_backref red", byn.get("artifact_backref") is False, byn)
    fails_with(cur, "SELECT v13_verify_chunks(true)", (),
               "verify_chunks failed", "E4: p_raise V3004", pgcode="V3004")
    cur.execute("ROLLBACK TO SAVEPOINT e4")
    conn.commit()

    # ----- F -----
    cur.execute("SET enable_seqscan = off")
    cur.execute(
        "EXPLAIN (COSTS OFF) SELECT 1 FROM chunks "
        "WHERE body_tsv @@ websearch_to_tsquery('english'::regconfig, 'quasar')")
    plan_f1 = "\n".join(r[0] for r in cur.fetchall())
    check("F1: Bitmap/Index on ix_chunks_tsv", "ix_chunks_tsv" in plan_f1, plan_f1)
    cur.execute("SET enable_seqscan = on")

    cur.execute(
        "SELECT count(*) FROM chunks WHERE body_tsv @@ "
        "websearch_to_tsquery('english'::regconfig, 'quasar')")
    n_q = cur.fetchone()[0]
    check("F2: english hits", n_q > 0, n_q)
    ingest_doc(cur, "中文语料没有英文词", "cjk")
    conn.commit()
    cur.execute(
        "SELECT count(*) FROM chunks WHERE corpus='cjk' AND body_tsv @@ "
        "websearch_to_tsquery('english'::regconfig, '中文')")
    check("F2: CJK english tsquery zero", cur.fetchone()[0] == 0)

    conn, cur = recycle(server, conn)
    cur.execute("SET enable_seqscan = off")
    cur.execute(
        "EXPLAIN (COSTS OFF) SELECT 1 FROM chunks "
        "WHERE body_tsv @@ websearch_to_tsquery('english'::regconfig, 'quasar')")
    plan_f3 = "\n".join(r[0] for r in cur.fetchall())
    check("F3: committed index usable", "ix_chunks_tsv" in plan_f3, plan_f3)
    cur.execute("SET enable_seqscan = on")

    ingest_doc(cur, "quasar file-one unique aaa", "file")
    ingest_doc(cur, "quasar generated-one unique bbb", "generated")
    conn.commit()
    cur.execute(
        "SELECT count(*) FROM chunks WHERE corpus='file' AND body_tsv @@ "
        "websearch_to_tsquery('english'::regconfig, 'aaa')")
    n_file = cur.fetchone()[0]
    cur.execute(
        "SELECT count(*) FROM chunks WHERE corpus='generated' AND body_tsv @@ "
        "websearch_to_tsquery('english'::regconfig, 'aaa')")
    n_gen = cur.fetchone()[0]
    check("F4: corpus isolation file hits", n_file > 0, n_file)
    check("F4: corpus isolation generated misses aaa", n_gen == 0, n_gen)

    # ----- G -----
    sid_g = new_session(cur)
    append_user(cur, sid_g, "token")
    cur.execute("SELECT v13_context_required(%s)", (sid_g,))
    tok = cur.fetchone()[0]
    check("G1: eight keys", set(tok) == TOKEN8, set(tok) ^ TOKEN8)
    check("G1: corpus int", isinstance(tok["corpus"], int), tok)

    sid_g2 = new_session(cur)
    append_user(cur, sid_g2, "fresh-cycle")
    _, _, _, conn, cur = parse_settle(server, conn, cur, sid_g2)
    cur.execute("SELECT v13_context_fresh(%s)", (sid_g2,))
    check("G2: fresh after settle", cur.fetchone()[0] is True)
    ingest_doc(cur, "quasar freshness bump " + u(), "docs")
    conn.commit()
    cur.execute("SELECT v13_context_fresh(%s)", (sid_g2,))
    check("G2: ingest makes not fresh", cur.fetchone()[0] is False)
    _, _, _, conn, cur = parse_settle(server, conn, cur, sid_g2)
    cur.execute("SELECT v13_context_fresh(%s)", (sid_g2,))
    check("G2: second settle fresh", cur.fetchone()[0] is True)
    cur.execute("SELECT v13_context_fresh(%s)", (sid_g2,))
    check("G2: no-change stays fresh", cur.fetchone()[0] is True)

    cur.execute("SELECT generation FROM v13_chunks_meta WHERE singleton")
    g0 = cur.fetchone()[0]
    cur.execute(
        "SELECT source_hash, content_hash FROM chunks "
        "WHERE NOT v13_chunk_referenced(content_hash) LIMIT 1")
    drow = cur.fetchone()
    check("G3: have unreferenced row", drow is not None)
    cur.execute("DELETE FROM chunks WHERE source_hash=%s AND content_hash=%s",
                drow)
    conn.commit()
    cur.execute("SELECT generation FROM v13_chunks_meta WHERE singleton")
    g1 = cur.fetchone()[0]
    check("G3: delete bumps generation", g1 == g0 + 1, (g0, g1))
    cur.execute("SELECT v13_context_fresh(%s)", (sid_g2,))
    check("G3: not fresh after DML", cur.fetchone()[0] is False)

    cur.execute("UPDATE v13_policies SET active=false WHERE name='assemble_manifest' AND active")
    fails_with(cur, "SELECT v13_context_required(%s)", (sid_g,),
               "no active assemble_manifest policy (seed lost?)",
               "G4: assemble RAISE retained", pgcode="P0001")
    bump_policy(cur, "assemble_manifest", seed_asm())
    fails_with(cur, "DELETE FROM v13_chunks_meta WHERE singleton", (),
               "cannot be deleted", "G4: meta DELETE rejected", pgcode="V3004")
    fails_with(cur, "UPDATE v13_chunks_meta SET generation = generation - 1 WHERE singleton",
               (), "monotonic", "G4: generation lower rejected", pgcode="V3004")
    conn.commit()

    g5_fix = "-- v13_probe hidden\nSELECT 1 /* v13_advance */"
    g5_stripped = strip_sql_comments(g5_fix)
    check("G5: strip drops comment identifiers",
          "v13_probe" not in g5_stripped and "v13_advance" not in g5_stripped,
          g5_stripped)
    src_sql = strip_sql_comments((V13 / "chunks" / "v13_chunks.sql").read_text())
    check("G5: no v13_probe", "v13_probe" not in src_sql)
    check("G5: no v13_judgment_envelope", "v13_judgment_envelope" not in src_sql)
    check("G5: no v13_advance", "v13_advance" not in src_sql)

    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='pg_cron')")
    has_cron = cur.fetchone()[0]
    if has_cron:
        cur.execute("SELECT jobname, command FROM cron.job")
        jobs = cur.fetchall()
        check("G6: exactly one verify job",
              len(jobs) == 1 and jobs[0][0] == "v13-verify-chunks", jobs)
        check("G6: command is verify", "v13_verify_chunks" in jobs[0][1], jobs)
    else:
        cur.execute("SELECT v13_verify_chunks(false)")
        check("G6: verify callable without cron", cur.fetchone()[0]["all_ok"] is True)

    eid_bulk, _ = succeed_tool(cur)
    conn.commit()
    cur.execute(
        "DO $b$ DECLARE i int; BEGIN "
        "FOR i IN 1..2000 LOOP "
        "PERFORM v13_ingest_document(%s::uuid, 'bulk', "
        "'quasar bulk ' || i::text || ' ' || repeat('word ', 40)); "
        "END LOOP; END $b$;",
        (str(eid_bulk),))
    conn.commit()
    sid_cost = new_session(cur)
    t0 = time.perf_counter()
    cur.execute("SELECT v13_context_required(%s)", (sid_cost,))
    cur.fetchone()
    dt = (time.perf_counter() - t0) * 1000.0
    check("G7: token <5ms after 2k docs", dt < 5.0, dt)

    def bad_ingest(val, needle, label):
        bump_policy(cur, "chunks_ingest", val)
        fails_with(cur, "SELECT v13_ingest_document(%s,%s,%s)",
                   (eid_bulk, "docs", "quasar x"), needle, label, pgcode="V3004")
        bump_policy(cur, "chunks_ingest", PARA_V1)

    bad_ingest({**PARA_V1, "mode": 1}, "invalid chunks_ingest",
               "G8: mode number rejected")
    bad_ingest({**PARA_V1, "chunker_version": "para_v2"}, "invalid chunks_ingest",
               "G8: unknown chunker_version rejected")
    missing_an = dict(PARA_V1)
    missing_an.pop("analyzer_version")
    bad_ingest(missing_an, "invalid chunks_ingest",
               "G8: missing analyzer_version rejected")
    bad_ingest({**PARA_V1, "max_doc_bytes": "big"}, "invalid chunks_ingest",
               "G8: max_doc_bytes string rejected")
    missing_tgt = dict(PARA_V1)
    missing_tgt.pop("target_bytes")
    fails_with(cur, "SELECT v13_chunker_slice(%s, %s::jsonb)",
               ("hello", json.dumps(missing_tgt)),
               "invalid chunks_ingest", "G8: missing target_bytes rejected",
               pgcode="V3004")
    fails_with(cur, "SELECT v13_span_unit(%s,%s,1,2,%s::jsonb)",
               ("ab" * 32, "abcd", json.dumps({"boundary": "word"})),
               "invalid span opts", "G8: boundary word rejected", pgcode="V3004")
    fails_with(cur, "SELECT v13_assemble_spans(%s::jsonb, %s::jsonb)",
               (json.dumps([{"content_hash": "a"*64, "body": "x", "spans": [[1, 1]]}]),
                json.dumps({"context_bytes": "wide"})),
               "invalid span_assembly", "G8: context_bytes string rejected",
               pgcode="V3004")
    conn.commit()

    # ----- H -----
    p99_load_rounds = []
    for _ in range(3):
        p99_load_rounds.append(p99_ms(cur, 2000))
        conn.commit()
    p99_loaded = median3(p99_load_rounds)
    cap = max(p99_base * 1.25, p99_base + 0.5)
    check("H1: p99 loaded within cap", p99_loaded <= cap,
          {"base": p99_base, "loaded": p99_loaded, "cap": cap})

    sid_h2 = new_session(cur)
    append_user(cur, sid_h2, "h2")
    snap_h2 = answers_sql(cur, sid_h2)
    conn.commit()
    cHold = psycopg2.connect(server.get_uri(DB))
    cHold.autocommit = False
    kHold = cHold.cursor()
    guc(kHold)
    ingest_doc(kHold, "quasar hold-open " + u(), "hold")
    box_h2 = {}

    def run_h2():
        c = psycopg2.connect(server.get_uri(DB))
        c.autocommit = False
        k = c.cursor()
        guc(k)
        k.execute("SELECT pg_backend_pid()")
        box_h2["pid"] = k.fetchone()[0]
        k.execute("SET lock_timeout = '2s'")
        try:
            live = with_current_probe(k, sid_h2, snap_h2)
            k.execute("SELECT v13_advance(%s, %s::jsonb)",
                      (sid_h2, json.dumps(live)))
            box_h2["act"] = k.fetchone()[0]
            box_h2["ok"] = True
        except Exception as exc:
            box_h2["err"] = str(exc)
            box_h2["ok"] = False
        c.rollback()
        c.close()

    th = threading.Thread(target=run_h2)
    th.start()
    twait = time.time()
    while time.time() - twait < 1 and "pid" not in box_h2:
        time.sleep(0.02)
    blocked = wait_box_lock(cur, box_h2, timeout=0.4)
    check("H2: advance not blocked by ingest txn",
          blocked is False, {"blocked": blocked, "box": box_h2})
    cHold.commit()
    cHold.close()
    th.join(8)
    check("H2: advance succeeded", box_h2.get("ok") is True, box_h2)
    check("H2: advance returned", box_h2.get("act") is not None, box_h2)

    cur.execute("SET ROLE v13_recall")
    cur.execute("SELECT count(*) FROM chunks")
    check("H3: recall SELECT chunks", cur.fetchone()[0] >= 0)
    cur.execute("SELECT count(*) FROM v13_sources")
    cur.fetchone()
    cur.execute("SELECT count(*) FROM v13_chunks_meta")
    cur.fetchone()
    cur.execute("RESET ROLE")
    cur.execute(
        "SELECT has_table_privilege('v13_recall','chunks','INSERT')")
    check("H3: recall no INSERT", cur.fetchone()[0] is False)
    cur.execute(
        "SELECT has_table_privilege('v13_recall','chunks','UPDATE')")
    check("H3: recall no UPDATE", cur.fetchone()[0] is False)
    cur.execute(
        "SELECT has_table_privilege('v13_recall','chunks','DELETE')")
    check("H3: recall no DELETE", cur.fetchone()[0] is False)
    cur.execute(
        "SELECT has_table_privilege('v13_recall','chunks','TRUNCATE')")
    check("H3: recall no TRUNCATE", cur.fetchone()[0] is False)
    cur.execute(
        "SELECT has_function_privilege('v13_recall',"
        "'v13_ingest_document(uuid,text,text,text)','EXECUTE')")
    check("H3: recall no ingest", cur.fetchone()[0] is False)
    cur.execute(
        "SELECT has_function_privilege('v13_recall',"
        "'v13_rebuild_chunks(text)','EXECUTE')")
    check("H3: recall no rebuild", cur.fetchone()[0] is False)
    cur.execute(
        "SELECT has_function_privilege('v13_recall',"
        "'v13_chunk_gc(boolean)','EXECUTE')")
    check("H3: recall no gc", cur.fetchone()[0] is False)
    cur.execute(
        "SELECT has_function_privilege('v13_recall',"
        "'v13_verify_chunks(boolean)','EXECUTE')")
    check("H3: recall no verify", cur.fetchone()[0] is False)
    cur.execute(
        "SELECT has_table_privilege('v13_resolve','chunks','SELECT')")
    check("H3: resolve no SELECT chunks", cur.fetchone()[0] is False)

    tp = files_through("twophase")
    check("H4: twophase prefix 4 files", len(tp) == 4, len(tp))
    check("H4: chunks is 7th",
          SQL_LOAD_ORDER[6].name == "v13_chunks.sql" and len(files_through("chunks")) == 7)
    for p in tp:
        txt = p.read_text()
        check(f"H4: {p.name} has no CREATE TABLE chunks",
              "CREATE TABLE chunks" not in txt)
    man = (V13 / "manifest" / "v13_manifest.sql").read_text()
    check("H4: manifest token has no corpus key",
          "'corpus'" not in man.split("CREATE FUNCTION v13_context_required")[1].split(
              "CREATE FUNCTION")[0])

    shared = "shared-hash-body-quasar"
    ingest_doc(cur, shared + "\n\n" + ("a" * 4000), "c1")
    ingest_doc(cur, shared + "\n\n" + ("b" * 4000), "c2")
    conn.commit()
    cur.execute("SELECT v13_body_hash(%s)", (shared,))
    thash = cur.fetchone()[0]
    cur.execute(
        "SELECT count(DISTINCT source_hash), count(DISTINCT content_hash) "
        "FROM chunks WHERE content_hash=%s", (thash,))
    ns, nh = cur.fetchone()
    check("H5: two sources one hash", ns == 2 and nh == 1, (ns, nh))
    cur.execute(
        "SELECT count(*) FROM artifacts WHERE content_hash=%s AND kind='chunk'",
        (thash,))
    check("H5: single artifact", cur.fetchone()[0] == 1)
    cur.execute("SELECT v13_body_hash('')")
    h_fn = cur.fetchone()[0]
    cur.execute("SELECT encode(digest(to_jsonb(''::text)::text,'sha256'),'hex')")
    h_manual = cur.fetchone()[0]
    check("H5: empty hash matches manual", h_fn == h_manual)

    # ----- I -----
    sent = "Hello world. Next sentence here."
    cur.execute("SELECT v13_body_hash(%s)", (sent,))
    shash = cur.fetchone()[0]
    cur.execute("SELECT v13_extract_spans(%s, %s::jsonb)",
                (sent, json.dumps(["world"])))
    sp_w = cur.fetchone()[0]
    cur.execute(
        "SELECT v13_assemble_spans(%s::jsonb, %s::jsonb)",
        (json.dumps([{"content_hash": shash, "body": sent, "spans": sp_w}]),
         json.dumps({"mode": "span", "boundary": "sentence", "context_bytes": 0,
                     "merge_gap_bytes": 0, "fence_aware": False, "table_aware": False})))
    a_sent = cur.fetchone()[0]
    off = a_sent[0]["offsets"][0]
    check("I1: sentence contains Hello..period",
          off[0] == 1 and sent[off[1] - 1:off[1]] == ".", (off, a_sent))
    sent_cjk = "你好世界。下一句。"
    cur.execute("SELECT v13_body_hash(%s)", (sent_cjk,))
    chash = cur.fetchone()[0]
    cur.execute("SELECT v13_extract_spans(%s, %s::jsonb)",
                (sent_cjk, json.dumps(["世界"])))
    sp_c = cur.fetchone()[0]
    cur.execute(
        "SELECT v13_assemble_spans(%s::jsonb, %s::jsonb)",
        (json.dumps([{"content_hash": chash, "body": sent_cjk, "spans": sp_c}]),
         json.dumps({"mode": "span", "boundary": "sentence", "context_bytes": 0,
                     "merge_gap_bytes": 0, "fence_aware": False, "table_aware": False})))
    a_cjk = cur.fetchone()[0]
    check("I1: CJK sentence terminator", len(a_cjk) >= 1 and a_cjk[0]["offsets"][0][0] == 1, a_cjk)

    fence_doc = "pre\n```\nquasar inside\n```\npost"
    cur.execute("SELECT v13_body_hash(%s)", (fence_doc,))
    fhash = cur.fetchone()[0]
    cur.execute("SELECT v13_extract_spans(%s, %s::jsonb)",
                (fence_doc, json.dumps(["quasar"])))
    sp_f = cur.fetchone()[0]
    cur.execute(
        "SELECT v13_assemble_spans(%s::jsonb, %s::jsonb)",
        (json.dumps([{"content_hash": fhash, "body": fence_doc, "spans": sp_f}]),
         json.dumps({"mode": "span", "boundary": "none", "context_bytes": 0,
                     "merge_gap_bytes": 0, "fence_aware": True, "table_aware": False})))
    a_f = cur.fetchone()[0]
    fs, fe = a_f[0]["offsets"][0]
    chunk = fence_doc.encode("utf-8")[fs - 1:fe]
    check("I2: fence expands to block", b"```" in chunk and b"quasar inside" in chunk, chunk)

    open_fence = "head\n```\nquasar open"
    cur.execute("SELECT v13_span_unit(%s,%s,%s,%s,%s::jsonb)",
                ("h"*64, open_fence, 10, 16,
                 json.dumps({"fence_aware": True, "boundary": "none", "context_bytes": 0})))
    of = cur.fetchone()[0]
    check("I2: unclosed fence to EOF", of[0]["offsets"][0][1] == len(open_fence.encode()), of)

    table_doc = "intro\n| a | b |\n| 1 | 2 |\nend"
    cur.execute("SELECT v13_extract_spans(%s, %s::jsonb)",
                (table_doc, json.dumps(["1"])))
    sp_t = cur.fetchone()[0]
    cur.execute("SELECT v13_body_hash(%s)", (table_doc,))
    t_hash = cur.fetchone()[0]
    cur.execute(
        "SELECT v13_assemble_spans(%s::jsonb, %s::jsonb)",
        (json.dumps([{"content_hash": t_hash, "body": table_doc, "spans": sp_t}]),
         json.dumps({"mode": "span", "boundary": "none", "context_bytes": 0,
                     "merge_gap_bytes": 0, "fence_aware": False, "table_aware": True})))
    a_t = cur.fetchone()[0]
    ts, te = a_t[0]["offsets"][0]
    tchunk = table_doc.encode("utf-8")[ts - 1:te]
    check("I3: table expands whole segment", tchunk.startswith(b"|") and b"| 1 | 2 |" in tchunk, tchunk)

    mixed = "```\n| a | b |\nquasar\n```"
    cur.execute("SELECT v13_extract_spans(%s, %s::jsonb)",
                (mixed, json.dumps(["quasar"])))
    sp_m = cur.fetchone()[0]
    cur.execute("SELECT v13_body_hash(%s)", (mixed,))
    mhash = cur.fetchone()[0]
    cur.execute(
        "SELECT v13_assemble_spans(%s::jsonb, %s::jsonb)",
        (json.dumps([{"content_hash": mhash, "body": mixed, "spans": sp_m}]),
         json.dumps({"mode": "span", "boundary": "none", "context_bytes": 0,
                     "merge_gap_bytes": 0, "fence_aware": True, "table_aware": True})))
    a_m = cur.fetchone()[0]
    ms, me = a_m[0]["offsets"][0]
    mchunk = mixed.encode("utf-8")[ms - 1:me]
    check("I3: fence wins over table", mchunk.startswith(b"```") and mchunk.endswith(b"```"), mchunk)

    utf_doc = "ab世界cd"
    p_s, p_e, ctx = 6, 6, 1
    raw = utf_doc.encode("utf-8")
    win_start = p_s - ctx
    check("I4: fixture start window is continuation",
          128 <= raw[win_start - 1] <= 191, raw[win_start - 1])
    cur.execute("SELECT octet_length(%s)", (utf_doc,))
    blen = cur.fetchone()[0]
    cur.execute(
        "SELECT v13_span_unit(%s,%s,%s,%s,%s::jsonb)",
        ("u"*64, utf_doc, p_s, p_e,
         json.dumps({"context_bytes": ctx, "boundary": "none",
                     "fence_aware": False, "table_aware": False})))
    uout = cur.fetchone()[0]
    us, ue = uout[0]["offsets"][0]
    cur.execute("SELECT get_byte(convert_to(%s,'UTF8'), %s)", (utf_doc, us - 1))
    lead = cur.fetchone()[0]
    check("I4: start adsorbed off continuation", us != win_start, (us, win_start))
    check("I4: start not continuation", not (128 <= lead <= 191), (us, ue, lead, blen))
    check("I4: has byte after end", ue < blen, (us, ue, blen))
    cur.execute("SELECT get_byte(convert_to(%s,'UTF8'), %s)", (utf_doc, ue))
    nxt = cur.fetchone()[0]
    check("I4: end not mid-char leftover", not (128 <= nxt <= 191), nxt)

    cur.execute(
        "SELECT v13_assemble_spans(%s::jsonb, %s::jsonb)",
        (json.dumps([{"content_hash": "e"*64, "body": "", "spans": []}]),
         json.dumps({"mode": "whole_chunk"})))
    empty_whole = cur.fetchone()[0]
    check("I: whole_chunk empty body skipped", empty_whole == [], empty_whole)

    # ----- J -----
    run_j1(cur, conn, "j", "J1")

    run_j2(server, cur, conn, "j2", "J2")

    run_j3(server, cur, conn, "j3", "J3", reverse=False)
    run_j3(server, cur, conn, "j3r", "J3-rev", reverse=True)

    for i in range(3):
        run_j1(cur, conn, f"j4j1{i}", f"J4.J1[{i}]")
        run_j2(server, cur, conn, f"j4j2{i}", f"J4.J2[{i}]")
        run_j3(server, cur, conn, f"j4j3{i}", f"J4.J3[{i}]", reverse=False)

    def j4_round():
        box = {"err": None}

        def ing(tag):
            try:
                c = psycopg2.connect(server.get_uri(DB))
                c.autocommit = False
                k = c.cursor()
                guc(k)
                ingest_doc(k, f"quasar j4 {tag} {u()}", f"j4{tag}")
                c.commit()
                c.close()
            except Exception as exc:
                box["err"] = str(exc)

        t1 = threading.Thread(target=ing, args=("a",))
        t2 = threading.Thread(target=ing, args=("b",))
        t1.start(); t2.start()
        t1.join(20); t2.join(20)
        return box["err"]

    for i in range(3):
        err = j4_round()
        check(f"J4: parallel ingest round {i} no deadlock", err is None, err)
    conn.commit()

    conn.close()
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
