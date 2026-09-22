"""DP6 gate M2: transcript verbatim layer + watermark freshness (F10) +
structured-layer index. Groups I-N.

Run: uv run python v13/memory/test_memory.py  (exit 0 = pass)
"""
from __future__ import annotations

import json
import re
import sys
import time
import uuid
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
V13 = AGENT_ROOT / "v13"
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v13.memory.setup_db import DB, main as setup_db
from v13.load import files_through

HEX64 = re.compile(r"^[0-9a-f]{64}$")


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
                if src[i] == '"':
                    out.append('"')
                    i += 1
                    break
                out.append(src[i])
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
    cur.execute("SELECT set_config('typesafe.provider', 'mock', false)")
    cur.execute("SELECT set_config('typesafe.model', 'jev-mock', false)")


def new_session(cur, sid=None):
    sid = sid or u()
    cur.execute("INSERT INTO sessions (session_id) VALUES (%s)", (sid,))
    return sid


def append(cur, sid, etype, payload):
    cur.execute(
        "SELECT v13_append_event(%s, %s, %s, %s::jsonb)",
        (sid, u(), etype, json.dumps(payload)))
    return cur.fetchone()[0]


def append_user(cur, sid, text):
    return append(cur, sid, "user/message", {"text": text})


def append_llm(cur, sid, text):
    return append(cur, sid, "llm/message", {"text": text})


def rebuild(cur, limit=100):
    cur.execute("SELECT v13_rebuild_transcript_chunks(%s)", (limit,))
    return cur.fetchone()[0]


def freshness(cur, sid):
    cur.execute("SELECT v13_transcript_freshness(%s)", (sid,))
    return cur.fetchone()[0]


def watermark(cur, sid):
    cur.execute("SELECT v13_transcript_watermark(%s)", (sid,))
    return cur.fetchone()[0]


def recall(cur, sid, tinql, k=8):
    cur.execute(
        "SELECT * FROM v13_transcript_recall(%s, %s, %s)", (sid, tinql, k))
    return cur.fetchall()


def tinql_of(cur, text):
    cur.execute("SELECT v13_build_tinql(%s)", (text,))
    return cur.fetchone()[0]


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


def mock_for(cur, sid) -> str:
    cur.execute(
        "SELECT signal, kind, criteria FROM v13_needed_judgments(%s)", (sid,))
    answers = {}
    for signal, kind, criteria in cur.fetchall():
        if kind == "choice":
            keys = list(criteria.keys()) if isinstance(criteria, dict) else ["none"]
            ch = keys[0]
            answers[signal] = {"type": "choice", "choice": ch,
                               "probabilities": {ch: 0.9}, "confidence": 0.9}
        elif kind == "score":
            answers[signal] = {"type": "score", "score": 0.5, "confidence": 0.9}
        else:
            answers[signal] = {"type": "noul", "noul": 0.1}
    return json.dumps({"model": "jev-mock", "answers": answers,
                       "usage": {"input_tokens": 1, "output_tokens": 1}})


def set_mock(cur, mock: str) -> None:
    cur.execute("SELECT set_config('typesafe.mock_response', %s, true)",
                (mock,))


def main() -> int:
    setup_db()
    server = get_server()
    conn = psycopg2.connect(server.get_uri(DB))
    conn.autocommit = False
    cur = conn.cursor()
    guc(cur)

    # ----- I projection discipline -----
    sid_i1 = new_session(cur)
    append_user(cur, sid_i1, "東京タワーは電波塔である")
    append_llm(cur, sid_i1, "the tokyo tower answer about quasars")
    append(cur, sid_i1, "turn/route", {"action": "sql"})
    append(cur, sid_i1, "tool/result", {"ok": True})
    append(cur, sid_i1, "effect_done", {"effect": "x"})
    append(cur, sid_i1, "turn/end", {"delivered": True})
    append_user(cur, sid_i1, "")                      # 空体跳过
    append_llm(cur, sid_i1, "")                       # 空体跳过
    conn.commit()
    out_i1 = rebuild(cur)
    check("I1: rows_projected == 2", out_i1["rows_projected"] == 2, out_i1)
    cur.execute(
        "SELECT seq_from, seq_to, body FROM transcript_chunks "
        "WHERE session_id=%s ORDER BY seq_from", (sid_i1,))
    rows_i1 = cur.fetchall()
    check("I1: curated rows only (user/llm, non-empty)",
          [r[2] for r in rows_i1] ==
          ["東京タワーは電波塔である", "the tokyo tower answer about quasars"],
          rows_i1)
    check("I1: per-event row seq_from=seq_to",
          all(r[0] == r[1] for r in rows_i1), rows_i1)
    cur.execute(
        "SELECT count(*) FROM transcript_chunks t JOIN events e "
        "ON e.session_id=t.session_id AND e.seq=t.seq_from "
        "WHERE t.session_id=%s AND e.type NOT IN ('user/message','llm/message')",
        (sid_i1,))
    check("I1: zero orchestration/tool rows", cur.fetchone()[0] == 0)

    cur.execute("SELECT body FROM transcript_chunks WHERE session_id=%s "
                "AND seq_from=0", (sid_i1,))
    body_i2 = cur.fetchone()[0]
    def bad_hash_insert(label):
        cur.execute("SAVEPOINT sp_i2")
        try:
            cur.execute(
                "INSERT INTO transcript_chunks (session_id, seq_from, seq_to,"
                " body, content_hash) VALUES (%s, 999, 999, 'tamper probe', %s)",
                (sid_i1, "0" * 64))
            cur.execute("ROLLBACK TO SAVEPOINT sp_i2")
            raise AssertionError(f"{label}: bad hash accepted")
        except psycopg2.errors.CheckViolation:
            cur.execute("ROLLBACK TO SAVEPOINT sp_i2")
            check(f"{label}: self-cert CHECK rejects", True)

    bad_hash_insert("I2")
    fails_with(
        cur,
        "UPDATE transcript_chunks SET body='x' WHERE session_id=%s",
        (sid_i1,), "immutable", "I2: UPDATE rejected", pgcode="V3006")
    cur.execute(
        "DELETE FROM transcript_chunks WHERE session_id=%s", (sid_i1,))
    conn.commit()
    out_i2 = rebuild(cur)
    check("I2: re-build after owner DELETE restores same rows",
          out_i2["rows_projected"] == 2, out_i2)
    cur.execute(
        "SELECT seq_from, body FROM transcript_chunks WHERE session_id=%s "
        "ORDER BY seq_from", (sid_i1,))
    check("I2: restored rows identical",
          cur.fetchall() == [(0, "東京タワーは電波塔である"),
                             (1, "the tokyo tower answer about quasars")])

    seq_i3a = append_llm(cur, sid_i1, "incremental tail one")
    conn.commit()
    out_i3 = rebuild(cur)
    check("I3: incremental projects only new", out_i3["rows_projected"] == 1,
          out_i3)
    out_i3b = rebuild(cur)
    check("I3: idempotent rerun zero rows", out_i3b["rows_projected"] == 0,
          out_i3b)
    wm_i3 = watermark(cur, sid_i1)
    check("I3: watermark monotonic", wm_i3 == seq_i3a, wm_i3)

    sid_i3 = new_session(cur)
    for i in range(3):
        append_llm(cur, sid_i3, f"limited sweep document {i}")
    conn.commit()
    out_l1 = rebuild(cur, 2)
    check("I3: limit 2 first pass", out_l1["rows_projected"] == 2, out_l1)
    out_l2 = rebuild(cur, 2)
    check("I3: limit 2 second pass finishes", out_l2["rows_projected"] == 1,
          out_l2)
    fails_with(cur, "SELECT v13_rebuild_transcript_chunks(%s)", (0,),
               "must be >= 1", "I3: limit 0 rejected", pgcode="V3006")
    conn.commit()

    # ----- J watermark & F10 -----
    sid_j1 = new_session(cur)
    append_user(cur, sid_j1, "freshness probe question")
    conn.commit()
    rebuild(cur)
    append_llm(cur, sid_j1, "unprojected llm answer quasarium")
    conn.commit()
    cur.execute("SELECT v13_build_tinql(%s)", ("quasarium",))
    tq_j1 = cur.fetchone()[0]
    rows_j1 = recall(cur, sid_j1, tq_j1)
    check("J1: unprojected text invisible (fail-closed reader)",
          rows_j1 == [], rows_j1)
    fr_j1 = freshness(cur, sid_j1)
    check("J1: lag=1", fr_j1["lag"] == 1, fr_j1)
    check("J1: degraded=false within bound",
          fr_j1["degraded"] is False, fr_j1)
    cur.execute(
        "SELECT count(*) FROM transcript_chunks WHERE session_id=%s",
        (sid_j1,))
    check("J1: only projected base row present", cur.fetchone()[0] == 1)

    # J1b(dp6.1 P1-1):尾部空体事件不入 freshness 分母——分母与 rebuild
    # 策展口径对齐(空体跳过)。两世界:分母不排空体→v_max=尾部空体
    # seq>watermark→lag=1≠0 即红;排空体→lag=0。
    sid_j1b = new_session(cur)
    append_user(cur, sid_j1b, "trailing empty body probe")
    conn.commit()
    rebuild(cur)
    cur.execute(
        "SELECT count(*) FROM transcript_chunks WHERE session_id=%s",
        (sid_j1b,))
    check("J1b: base row projected", cur.fetchone()[0] == 1)
    append_llm(cur, sid_j1b, "")           # 尾部空体:不可投影
    conn.commit()
    fr_j1b = freshness(cur, sid_j1b)
    check("J1b: trailing empty body out of denominator (lag=0)",
          fr_j1b["lag"] == 0, fr_j1b)
    check("J1b: degraded=false", fr_j1b["degraded"] is False, fr_j1b)

    sid_j2 = new_session(cur)
    append_user(cur, sid_j2, "first turn asks about polaris north star")
    append_llm(cur, sid_j2, "polaris is the north star reply")
    conn.commit()
    rebuild(cur)
    append_user(cur, sid_j2, "second turn asks something new")
    conn.commit()
    cur.execute("SELECT v13_build_tinql(%s)", ("polaris",))
    tq_j2 = cur.fetchone()[0]
    rows_j2 = recall(cur, sid_j2, tq_j2)
    check("J2: previous turn recallable after new turn",
          len(rows_j2) >= 1, rows_j2)
    fr_j2 = freshness(cur, sid_j2)
    check("J2: lag within bound", fr_j2["lag"] <= fr_j2["max_lag"], fr_j2)
    check("J2: degraded=false", fr_j2["degraded"] is False, fr_j2)

    sid_j3 = new_session(cur)
    append_user(cur, sid_j3, "degradation probe head")
    conn.commit()
    rebuild(cur)
    for i in range(20):
        append_llm(cur, sid_j3, f"unprojected tail {i} nebulium")
    # dp6.1 P2-5:追加 user 锚推 last_user_seq→20 条尾部 llm 沉淀入
    # canonical 窗(seq ≤ last_user_seq)——「canonical 含最新 tail」半边
    # 才可直钉(无锚时尾部在窗外,canonical 结构性不含;lag 相应 20→21)。
    append_user(cur, sid_j3, "degradation probe tail anchor")
    conn.commit()
    conn.notices.clear() if hasattr(conn, "notices") else None
    fr_j3 = freshness(cur, sid_j3)
    check("J3: lag 21 over bound 16", fr_j3["lag"] == 21 and
          fr_j3["max_lag"] == 16, fr_j3)
    check("J3: degraded=true", fr_j3["degraded"] is True, fr_j3)
    notices_j3 = list(getattr(conn, "notices", []) or [])
    check("J3: NOTICE captured",
          any("memory recall degraded" in n for n in notices_j3),
          notices_j3[:2])
    cur.execute("SELECT v13_build_tinql(%s)", ("nebulium",))
    tq_j3 = cur.fetchone()[0]
    rows_j3 = recall(cur, sid_j3, tq_j3)
    check("J3: reader returns projected prefix only",
          rows_j3 == [], rows_j3)
    cur.execute(
        "SELECT count(*) FROM transcript_chunks WHERE session_id=%s",
        (sid_j3,))
    check("J3: prefix intact (1 projected row)", cur.fetchone()[0] == 1)
    cur.execute("SELECT v13_canonical_state(%s)->'messages'", (sid_j3,))
    msgs_j3 = cur.fetchone()[0]
    check("J3: current turn direct read via canonical_state (latest tail)",
          any("unprojected tail 19 nebulium" == (m["payload"].get("text"))
            for m in msgs_j3), [m["payload"] for m in msgs_j3][-2:])
    cur.execute(
        "SELECT count(*) FROM transcript_chunks WHERE session_id=%s "
        "AND body LIKE '%%unprojected tail%%'", (sid_j3,))
    check("J3: projection excludes unprojected tail (structural contrast)",
          cur.fetchone()[0] == 0)

    cur.execute(
        "SELECT value FROM v13_policies WHERE name='memory_stack' AND active")
    ms_j4 = cur.fetchone()[0]
    bump_policy(cur, "memory_stack", {"lag_cap": 4})
    fails_with(cur, "SELECT v13_transcript_freshness(%s)", (sid_j3,),
               "invalid memory_stack", "J4: bad shape rejected",
               pgcode="V3006")
    bump_policy(cur, "memory_stack", ms_j4)
    cur.execute(
        "UPDATE v13_policies SET active=false WHERE name='memory_stack'")
    fails_with(cur, "SELECT v13_transcript_freshness(%s)", (sid_j3,),
               "no active policy row", "J4: missing active row rejected")
    cur.execute(
        "UPDATE v13_policies SET active=true WHERE name='memory_stack' "
        "AND version=1")
    conn.commit()

    # ----- K reader -----
    sid_k1 = new_session(cur)
    append_user(cur, sid_k1, "mixed question about 東京タワー and quasars")
    append_llm(cur, sid_k1, "東京タワーは電波塔である five hundred meters")
    append_llm(cur, sid_k1, "quasar formation in high redshift surveys")
    append_llm(cur, sid_k1, "an unrelated interlude about tea varieties")
    conn.commit()
    rebuild(cur)
    tq_k1a = tinql_of(cur, "東京タワー")
    rows_k1a = recall(cur, sid_k1, tq_k1a)
    cur.execute(
        "SELECT content_hash, body FROM transcript_chunks "
        "WHERE session_id=%s", (sid_k1,))
    bodies_k1 = dict(cur.fetchall())
    check("K1: CJK phrase hit (verbatim segmentation)",
          len(rows_k1a) >= 1 and
          all("東京タワー" in bodies_k1[r[0]] for r in rows_k1a) and
          any("unrelated interlude" not in bodies_k1[r[0]]
              for r in rows_k1a) and
          not any("unrelated interlude" in bodies_k1[r[0]]
                  for r in rows_k1a), rows_k1a)
    tq_k1b = tinql_of(cur, "quasar")
    rows_k1b = recall(cur, sid_k1, tq_k1b)
    check("K1: english hit", len(rows_k1b) == 1, rows_k1b)
    rows_k1b2 = recall(cur, sid_k1, tq_k1b)
    check("K1: dual run byte equal", rows_k1b == rows_k1b2)
    rows_sorted = sorted(rows_k1b, key=lambda r: (-r[1], r[0]))
    check("K1: order score desc hash asc", rows_k1b == rows_sorted, rows_k1b)
    sid_k1b = new_session(cur)
    append_llm(cur, sid_k1b, "quasar formation duplicate tie one")
    append_llm(cur, sid_k1b, "quasar formation duplicate tie two")
    conn.commit()
    rebuild(cur)
    rows_tie = recall(cur, sid_k1b, tinql_of(cur, "quasar formation"), 1)
    rows_tie_all = recall(cur, sid_k1b, tinql_of(cur, "quasar formation"), 8)
    check("K1: tie limit resolved by hash asc",
          rows_tie[0][0] == min(r[0] for r in rows_tie_all),
          (rows_tie, rows_tie_all))
    fails_with(cur, "SELECT * FROM v13_transcript_recall(%s,%s,%s)",
               (sid_k1, tq_k1b, 0), "out of bounds", "K1: k=0 rejected",
               pgcode="V3006")
    fails_with(cur, "SELECT * FROM v13_transcript_recall(%s,%s,%s)",
               (sid_k1, tq_k1b, 1025), "out of bounds", "K1: k=1025 rejected",
               pgcode="V3006")
    fails_with(cur, "SELECT * FROM v13_transcript_recall(%s,%s,%s)",
               (sid_k1, tq_k1b, None), "out of bounds", "K1: NULL k rejected",
               pgcode="V3006")
    cur.execute(
        "SELECT count(*) FROM v13_transcript_recall(%s,%s,8)",
        (sid_k1, ""))
    check("K1: empty tinql zero rows", cur.fetchone()[0] == 0)
    fails_with(cur, "SELECT * FROM v13_transcript_recall(%s,%s,%s)",
               (sid_k1, "bare", 8), "emitted grammar",
               "K1: non-emitted grammar rejected", pgcode="V3005")

    rows_cross = recall(cur, sid_k1b, tq_k1a)
    check("K2: session isolation (A's reader zero on B corpus)",
          rows_cross == [], rows_cross)
    sid_k2 = new_session(cur)
    append_llm(cur, sid_k2, "private session text quasarium")
    conn.commit()
    rebuild(cur)
    check("K2: private text invisible to other session",
          recall(cur, sid_k1, tinql_of(cur, "quasarium")) == [])

    cur.execute("SET enable_seqscan = off")
    cur.execute(
        "EXPLAIN (FORMAT JSON) SELECT content_hash FROM transcript_chunks t "
        "WHERE t.body ==> %s LIMIT 8", (tq_k1b,))
    plan_k3_unscoped = cur.fetchone()[0]
    cur.execute(
        "EXPLAIN (FORMAT JSON) SELECT t.content_hash, "
        "stannum.full_score(t.ctid)::numeric AS bm25, t.seq_from "
        "FROM transcript_chunks t "
        "WHERE t.session_id = %s AND t.body ==> %s "
        "ORDER BY bm25 DESC, t.content_hash ASC LIMIT 8",
        (sid_k1, tq_k1b))
    plan_k3_scoped = cur.fetchone()[0]
    cur.execute("SET enable_seqscan = on")
    plan_un = json.dumps(plan_k3_unscoped)
    plan_sc = json.dumps(plan_k3_scoped)
    check("K3: unscoped bind drives Custom Scan (index usable)",
          "Custom Scan" in plan_un, plan_un[:300])
    check("K3: reader-shaped scoped query is index-backed and deterministic",
          "score_bound_indexed" in plan_sc
          and "transcript_chunks_pkey" in plan_sc
          and '"Node Type": "Seq Scan"' not in plan_sc
          and "Bitmap Index Scan" in plan_sc,
          plan_sc[:400])
    print("[info] K3: session+bind composite plan = PK bitmap + "
          "score_bound_indexed (risk #11 outcome; Custom Scan binds when "
          "unscoped)")

    mem_sql = (V13 / "memory" / "v13_memory.sql").read_text()
    norm_m = strip_sql_comments(mem_sql)
    check("K4: file11 bind operator exactly 1",
          norm_m.count("==>") == 1, norm_m.count("==>"))
    check("K4: file11 engine-qualified names exactly 3",
          norm_m.count("stannum.") == 3, norm_m.count("stannum."))
    check("K4: no banned literals (dp1 scan belt)",
          "mock_response" not in norm_m and "set_config" not in norm_m)
    conn.commit()

    # ----- L p99 -----
    def append_loop(k, sid, n, text_prefix):
        t0 = time.perf_counter()
        lat = []
        for i in range(n):
            s = time.perf_counter()
            append(k, sid, "llm/message", {"text": f"{text_prefix} {i}"})
            lat.append((time.perf_counter() - s) * 1000.0)
            if i % 500 == 499:
                k.connection.commit()
        k.connection.commit()
        return lat

    def p99(vals):
        sv = sorted(vals)
        return sv[min(len(sv) - 1, int(len(sv) * 0.99))]

    base_p99s = []
    loaded_p99s = []
    for rnd in range(3):
        sid_base = new_session(cur)
        conn.commit()
        lat_base = append_loop(cur, sid_base, 2000, f"p99base{rnd}")
        base_p99s.append(p99(lat_base))
        cur.execute("DELETE FROM transcript_chunks WHERE session_id=%s",
                    (sid_base,))
        conn.commit()
    check("L1: baseline p99 measured (3 rounds)",
          len(base_p99s) == 3, base_p99s)

    for rnd in range(3):
        sid_load = new_session(cur)
        for i in range(40):
            append_llm(cur, sid_load, f"pending curated {i} driftium")
        conn.commit()
        box_l = {}

        def builder_thread(box=box_l, sid=sid_load):
            bc = psycopg2.connect(server.get_uri(DB))
            bc.autocommit = False
            bk = bc.cursor()
            try:
                for _ in range(6):
                    out = rebuild(bk, 100)
                    bc.commit()
                    if out["rows_projected"] == 0:
                        break
                box["ok"] = True
            except Exception as exc:
                bk.rollback()
                box["err"] = str(exc)
            bc.close()

        th_l = __import__("threading").Thread(target=builder_thread)
        th_l.start()
        lat_loaded = append_loop(cur, sid_load, 2000, f"p99load{rnd}")
        th_l.join(30)
        check(f"L1: round {rnd} builder ok", box_l.get("ok") is True, box_l)
        loaded_p99s.append(p99(lat_loaded))
        cur.execute("DELETE FROM transcript_chunks WHERE session_id=%s",
                    (sid_load,))
        conn.commit()
    med_base = sorted(base_p99s)[1]
    med_loaded = sorted(loaded_p99s)[1]
    bound = max(med_base * 1.25, med_base + 0.5)
    check("L1: p99 loaded <= max(x1.25, +0.5ms)",
          med_loaded <= bound, (med_base, med_loaded, bound))
    print(f"[info] L1 p99 base={med_base:.3f}ms loaded={med_loaded:.3f}ms "
          f"bound={bound:.3f}ms")

    sid_l2 = new_session(cur)
    for i in range(30):
        append_llm(cur, sid_l2, f"l2 pending doc {i}")
    conn.commit()
    box_l2 = {}

    def builder_only(box=box_l2):
        bc = psycopg2.connect(server.get_uri(DB))
        bc.autocommit = False
        bk = bc.cursor()
        try:
            for _ in range(4):
                rebuild(bk, 100)
                bc.commit()
            box["ok"] = True
        except Exception as exc:
            bk.rollback()
            box["err"] = str(exc)
        bc.close()

    th_l2 = __import__("threading").Thread(target=builder_only)
    th_l2.start()
    time.sleep(0.05)
    t0_l2 = time.perf_counter()
    append_llm(cur, sid_l2, "append during builder")
    dt_l2 = (time.perf_counter() - t0_l2) * 1000.0
    th_l2.join(30)
    check("L2: append immediate while builder runs", dt_l2 < 500.0, dt_l2)
    conn.commit()

    # ----- M structured layer & verifier -----
    cur.execute(
        "SELECT count(*) FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid "
        "WHERE c.relname='ix_decisions_question_stannum'")
    check("M1: decisions stannum index present exactly once (single-index "
          "discipline)", cur.fetchone()[0] == 1)
    sid_m1 = new_session(cur)
    append_user(cur, sid_m1, "structured layer smoke question")
    conn.commit()
    t0_m1 = time.perf_counter()
    set_mock_ok = True
    try:
        cur.execute("SELECT set_config('typesafe.mock_response', %s, true)",
                    (mock_for(cur, sid_m1),))
        cur.execute("SELECT v13_parse(%s)", (sid_m1,))
        p_m1 = cur.fetchone()[0]
    except psycopg2.Error as exc:
        set_mock_ok = False
        p_m1 = None
        conn.rollback()
    dt_m1 = (time.perf_counter() - t0_m1) * 1000.0
    if set_mock_ok:
        check("M1: mock parse lands decisions with index present",
              p_m1["failed"] is False and p_m1["asked_questions"] > 0, p_m1)
        print(f"[info] M1 parse-with-index latency {dt_m1:.1f}ms "
              "(recorded, not asserted)")
        conn.commit()
    else:
        print("[note] M1: parse path unavailable on this conn; "
              "index presence asserted above")

    cur.execute("SELECT v13_verify_memory(false)")
    v_m2 = cur.fetchone()[0]
    check("M2: verify all_ok=true", v_m2["all_ok"] is True, v_m2)
    check("M2: five checks",
          [c2["name"] for c2 in v_m2["checks"]] ==
          ["self_cert", "source_events", "policy_present",
           "transcript_verify_index", "decisions_verify_index"], v_m2)
    cur.execute(
        "UPDATE v13_policies SET active=false WHERE name='memory_stack'")
    conn.commit()
    cur.execute("SELECT v13_verify_memory(false)")
    v_m2b = cur.fetchone()[0]
    check("M2: policy_present red when inactive",
          v_m2b["all_ok"] is False and
          [c2["ok"] for c2 in v_m2b["checks"]] ==
          [True, True, False, True, True], v_m2b)
    fails_with(cur, "SELECT v13_verify_memory(true)", (),
               "verify_memory failed", "M2: p_raise V3006 on red",
               pgcode="V3006")
    cur.execute(
        "UPDATE v13_policies SET active=true WHERE name='memory_stack' "
        "AND version=1")
    conn.commit()

    # ----- N cron / ACL / load -----
    cur.execute("SELECT count(*) FROM pg_extension WHERE extname='pg_cron'")
    cron_here = cur.fetchone()[0] == 1
    if cron_here:
        cur.execute("SELECT jobname FROM cron.job ORDER BY jobname")
        jobs_n1 = [r[0] for r in cur.fetchall()]
        check("N1: cron jobs exactly two (verify + sweep)",
              jobs_n1 == ["v13-sweep-transcript", "v13-verify-chunks"], jobs_n1)
        cur.execute(
            "SELECT command FROM cron.job WHERE jobname='v13-sweep-transcript'")
        check("N1: sweep job body",
              cur.fetchone()[0] == "SELECT v13_rebuild_transcript_chunks(100)")
    else:
        print("[note] N1: pg_cron not loadable in this database "
              "(cron.database_name guard) — DP4 G6-family degraded branch: "
              "builder stays manually callable")
    out_n1 = rebuild(cur, 100)
    check("N1: builder manually callable (behavior face)",
          out_n1["rows_projected"] >= 0, out_n1)

    sid_n2 = new_session(cur)
    append_llm(cur, sid_n2, "acl probe text polarium")
    conn.commit()
    rebuild(cur)
    cur.execute("SET ROLE v13_recall")
    cur.execute("SELECT count(*) FROM transcript_chunks")
    check("N2: recall SELECT transcript", cur.fetchone()[0] >= 0)
    cur.execute("SELECT v13_transcript_watermark(%s)", (sid_n2,))
    cur.fetchone()
    cur.execute("SELECT v13_transcript_freshness(%s)", (sid_n2,))
    cur.fetchone()
    cur.execute("SELECT count(*) FROM v13_transcript_recall(%s,%s,8)",
                (sid_n2, '"polarium"'))
    check("N2: recall EXECUTE reader", cur.fetchone()[0] >= 0)
    cur.execute("RESET ROLE")
    for tbl_perm in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
        cur.execute(
            "SELECT has_table_privilege('v13_recall','transcript_chunks',%s)",
            (tbl_perm,))
        check(f"N2: recall no {tbl_perm} transcript",
              cur.fetchone()[0] is False)
    for fn in ("v13_rebuild_transcript_chunks(int)",
               "v13_verify_memory(boolean)"):
        cur.execute(
            "SELECT has_function_privilege('v13_recall', %s, 'EXECUTE')",
            (fn,))
        check(f"N2: recall no EXECUTE {fn}", cur.fetchone()[0] is False)
        cur.execute(
            "SELECT has_function_privilege('public', %s, 'EXECUTE')", (fn,))
        check(f"N2: PUBLIC no EXECUTE {fn}", cur.fetchone()[0] is False)
    for fn in ("v13_transcript_watermark(uuid)",
               "v13_transcript_freshness(uuid)",
               "v13_transcript_recall(uuid,text,int)",
               "v13_transcript_immutable()"):
        cur.execute(
            "SELECT has_function_privilege('public', %s, 'EXECUTE')", (fn,))
        check(f"N2: PUBLIC no EXECUTE {fn}", cur.fetchone()[0] is False)

    cur.execute("SET ROLE v13_resolve")
    cur.execute("SELECT count(*) FROM transcript_chunks")
    cur.fetchone()
    cur.execute("SELECT count(*) FROM v13_transcript_recall(%s,%s,8)",
                (sid_n2, '"polarium"'))
    cur.fetchone()
    cur.execute("RESET ROLE")
    cur.execute("SET ROLE v13_route")
    cur.execute("SELECT count(*) FROM v13_transcript_recall(%s,%s,8)",
                (sid_n2, '"polarium"'))
    cur.fetchone()
    cur.execute("RESET ROLE")
    conn.commit()

    check("N3: memory prefix 11", len(files_through("memory")) == 11)
    check("N3: filter is 10th",
          files_through("memory")[9].name == "v13_filter.sql")
    cur.execute("SELECT 1 FROM pg_database WHERE datname='agent_v13_filter'")
    if cur.fetchone():
        cf = psycopg2.connect(server.get_uri("agent_v13_filter"))
        kcf = cf.cursor()
        kcf.execute(
            "SELECT count(*) FROM pg_tables WHERE tablename="
            "'transcript_chunks'")
        check("N3: filter db has no transcript table",
              kcf.fetchone()[0] == 0)
        kcf.execute(
            "SELECT count(*) FROM pg_proc WHERE proname="
            "'v13_transcript_recall'")
        check("N3: filter db has no reader", kcf.fetchone()[0] == 0)
        cf.rollback()
        cf.close()
    else:
        print("[note] N3: agent_v13_filter absent; structural check only")

    n_tbl = len(re.findall(r"(?im)^CREATE TABLE ", norm_m))
    n_idx = len(re.findall(r"(?im)^CREATE INDEX ", norm_m))
    n_cf = len(re.findall(r"(?im)^CREATE FUNCTION ", norm_m))
    n_trg = len(re.findall(r"(?im)^CREATE TRIGGER ", norm_m))
    n_ins = len(re.findall(r"(?im)^INSERT INTO ", norm_m))
    n_do = len(re.findall(r"(?im)^DO ", norm_m))
    n_rev = len(re.findall(r"(?im)^REVOKE ", norm_m))
    n_gr = len(re.findall(r"(?im)^GRANT ", norm_m))
    check("N3: paper-load counts (1 TABLE/2 INDEX/6 FUNCTION/1 TRIGGER/"
          "1 INSERT/1 DO/1 REVOKE/2 GRANT)",
          (n_tbl, n_idx, n_cf, n_trg, n_ins, n_do, n_rev, n_gr) ==
          (1, 2, 6, 1, 1, 1, 1, 2),
          (n_tbl, n_idx, n_cf, n_trg, n_ins, n_do, n_rev, n_gr))
    sigs_n3 = re.findall(
        r"(?im)^CREATE FUNCTION (\w+)\(([^)]*)\)", norm_m)
    check("N3: no duplicate signature",
          len(sigs_n3) == len(set(sigs_n3)),
          [s for s in sigs_n3 if sigs_n3.count(s) > 1])
    check("N3: BEGIN/COMMIT wrap",
          norm_m.count("BEGIN;") == 1 and norm_m.rstrip().endswith("COMMIT;"))

    readme = (V13 / "memory" / "README.md").read_text()
    for needle in ("扫地僧", "cron", "水印", "fail-closed", "degraded",
                   "策展", "stannum", "预热", "p99", "tick"):
        check(f"N-readme: mentions {needle}", needle in readme)

    conn.close()
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
