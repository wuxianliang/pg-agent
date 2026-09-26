"""Phase 2 of the mgraph trial: read loop + consolidate + epilogue.

前置:memdrive_mgraph.py 已完成 P(投影)+ W(build)并翻到 v3(read on);
Q1 的 walk 已部分驱动(脚本在 evidence 明细处崩溃,walk 身份确定性可续)。

本脚本不重跑 build(红线:build 一次)。读循环幂等续跑(同 walk 身份)。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGENT_ROOT = HERE.parent
sys.path.insert(0, str(AGENT_ROOT))

import server  # noqa: E402

server.get_server()

import psycopg2  # noqa: E402
from psycopg2.extras import Json  # noqa: E402
from demo_v13 import deepseek  # noqa: E402
from demo_v13 import settings as S  # noqa: E402

DB = "agent_v13_demo_mem"
URI = ("postgresql://postgres:@/%s?host=%s"
       % (DB, "/Users/wxl/Projects/pg-agent/.pgdata"))
OUT = HERE / "memtrial" / "mgraph_log2.json"
SHIM_ENDPOINT = "http://127.0.0.1:8765"

QUERIES = [
    {"id": "Q1-causal", "text": "why Zephyr 无法登录",
     "expect": "T2 因果陈述(因为…所以…无法登录)"},
    {"id": "Q2-temporal", "text": "when 恢复 登录",
     "expect": "T3 时间线(周日下午三点全部恢复)"},
    {"id": "Q3-entity", "text": "Alice 决定 回滚",
     "expect": "T3 Alice 决定先回滚"},
    {"id": "Q4-negative", "text": "数据库备份策略",
     "expect": "无关查询——零候选/低分/空 evidence"},
]
CONS_SYSTEM = (
    "You merge two adjacent memory notes into ONE canonical note for an "
    "agent memory store. Reply with plain text only: one concise sentence "
    "(<=60 chars) in the language of the notes, no preamble, no lists, "
    "keeping names, numbers, and decisions verbatim."
)
LOG: dict = {"phases": {}}
KEY = None


def shim_key() -> str:
    p = HERE / "memtrial" / ".shimkey"
    if not p.exists():
        raise SystemExit("[stop] memtrial/.shimkey missing")
    return p.read_text().strip()


def conn_plain():
    return psycopg2.connect(URI)


def conn_ask():
    conn = psycopg2.connect(URI)
    cur = conn.cursor()
    cur.execute("SELECT set_config('typesafe.model', 'deepseek-chat', false)")
    cur.execute("SELECT set_config('typesafe.endpoint', %s, false)",
                (SHIM_ENDPOINT,))
    cur.execute("SELECT set_config('typesafe.api_key', %s, false)", (KEY,))
    conn.commit()
    return conn


def one(sql, params=None, *, ask=False):
    conn = conn_ask() if ask else conn_plain()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        row = cur.fetchone()
        conn.commit()
        return row[0] if row else None
    finally:
        conn.close()


def rows(sql, params=None):
    conn = conn_plain()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        conn.close()


def jc_count():
    return one("SELECT count(*) FROM judgment_calls")


def bump_policy(over: dict) -> int:
    conn = conn_plain()
    try:
        cur = conn.cursor()
        cur.execute("SELECT value FROM v13_policies WHERE name='mgraph' AND active")
        base = cur.fetchone()[0]
        cur.execute("SELECT coalesce(max(version),0)+1 FROM v13_policies "
                    "WHERE name='mgraph'")
        ver = cur.fetchone()[0]
        cur.execute("INSERT INTO v13_policies (name, version, value, active) "
                    "VALUES ('mgraph', %s, %s, false)", (ver, Json({**base, **over})))
        cur.execute("UPDATE v13_policies SET active=false WHERE name='mgraph' AND active")
        cur.execute("UPDATE v13_policies SET active=true WHERE name='mgraph' AND version=%s",
                    (ver,))
        conn.commit()
        return ver
    finally:
        conn.close()


def main() -> int:
    global KEY
    settings = S.Settings.load()
    if settings.mode != "real" or not settings.api_key:
        return 2
    KEY = shim_key()
    sid = one("SELECT session_id FROM events WHERE type='user/message' "
              "GROUP BY session_id HAVING count(*) >= 8 "
              "ORDER BY max(at) DESC LIMIT 1")
    sid = str(sid)
    print(f"[sid  ] {sid}")
    LOG["sid"] = sid
    jc0 = jc_count()

    # ---------- W 复盘(库内既有数据;build 已在前一脚本完成) ----------
    w = {
        "type_winners": rows(
            "WITH t AS (SELECT split_part(signal,'::',2) AS hash, "
            " split_part(signal,'::',3) AS slot, (answer->>'noul')::numeric AS v "
            " FROM decisions WHERE session_id=%s AND signal LIKE 'mem_type::%%' "
            " AND answer IS NOT NULL), "
            "r AS (SELECT hash, slot, v, row_number() OVER "
            " (PARTITION BY hash ORDER BY v DESC, slot ASC) rn FROM t) "
            "SELECT slot, count(*) AS n FROM r WHERE rn=1 GROUP BY slot "
            "ORDER BY n DESC", (sid,)),
        "mem_rel_decisions": rows(
            "SELECT count(*) AS n FROM decisions "
            "WHERE session_id=%s AND signal LIKE 'mem_rel::%%'", (sid,)),
        "type_examples": rows(
            "WITH t AS (SELECT split_part(signal,'::',2) AS hash, "
            " split_part(signal,'::',3) AS slot, (answer->>'noul')::numeric AS v "
            " FROM decisions WHERE session_id=%s AND signal LIKE 'mem_type::%%'), "
            "r AS (SELECT hash, slot, v, row_number() OVER "
            " (PARTITION BY hash ORDER BY v DESC, slot ASC) rn FROM t) "
            "SELECT rr.slot, left(n.body, 70) AS body_head "
            " FROM r rr JOIN memory_nodes n ON n.session_id=%s "
            " AND n.content_hash=rr.hash WHERE rr.rn=1 "
            " ORDER BY n.source_at LIMIT 12", (sid, sid)),
    }
    # 候选面复盘:锚 OR 形 tinql;空锚记 0、不调用 candidates
    node0 = one("SELECT content_hash FROM memory_nodes WHERE session_id=%s "
                "AND origin='episodic' ORDER BY source_at LIMIT 1", (sid,))
    if node0:
        body0 = one("SELECT body FROM memory_nodes WHERE session_id=%s "
                    "AND content_hash=%s", (sid, node0))
        tinql = one("SELECT v13_mgraph_anchor_tinql(%s)", (body0,))
        n_terms = 0 if not tinql else tinql.count(" OR ") + 1
        if n_terms == 0:
            cands = []
        else:
            cands = one("SELECT coalesce(jsonb_agg(jsonb_build_object("
                        "'content_hash', c.content_hash, 'score', c.score)), '[]') "
                        "FROM v13_mgraph_candidates(%s, %s, 10) c", (sid, tinql))
            cands = (cands if isinstance(cands, list) else json.loads(cands)
                     if isinstance(cands, str) else cands)
        w["candidates_probe"] = {
            "anchor_body": (body0 or "")[:80], "tinql": (tinql or "")[:120],
            "candidates": cands}
    LOG["phases"]["write_recap"] = w
    print(f"[W2   ] type_winners={w['type_winners']}")
    print(f"[W2   ] candidates_probe_n={len(w.get('candidates_probe', {}).get('candidates') or [])}")
    print(f"[W2   ] anchor_tinql={w.get('candidates_probe', {}).get('tinql')!r}")

    # ---------- R 读路径(幂等续跑 Q1) ----------
    t0 = time.time()
    r_log = {"queries": []}
    for q in QUERIES:
        qq = dict(q)
        t_q0 = time.time()
        qq["route"] = one("SELECT v13_mgraph_route(%s)", (q["text"],))
        jc_q0 = jc_count()
        steps = 0
        asks_n = 0
        elapsed = 0
        final_preview = None
        for i in range(80):
            act = one("SELECT v13_mgraph_next_action(%s,%s,%s)",
                      (sid, q["text"], elapsed), ask=True)
            final_preview = act
            if act.get("action") in ("done", "skip"):
                break
            s0 = time.time()
            step = one("SELECT v13_mgraph_run_round(%s,%s,%s)",
                       (sid, q["text"], elapsed), ask=True)
            elapsed += int((time.time() - s0) * 1000)
            steps += 1
            asks_n += (step.get("asks") or 0) if isinstance(step, dict) else 0
        qh = one("SELECT v13_body_hash(%s)", (q["text"],))
        ev = one("SELECT v13_mgraph_evidence(%s,%s)", (sid, qh)) or {}
        ev_rows = ev.get("rows") or []
        walk = rows("SELECT walk_id, status, stop_reason, calls_used, "
                    "frontier, budgets, query_hash FROM memory_walks "
                    "WHERE session_id=%s AND query_hash=%s", (sid, qh))
        wid = walk[-1]["walk_id"] if walk else None
        rounds = rows("SELECT round, asks, frontier_out, basis "
                      "FROM memory_rounds WHERE walk_id=%s ORDER BY round",
                      (str(wid),)) if wid else []
        qq.update({
            "steps": steps, "asks": asks_n,
            "final_preview": final_preview,
            "walk": walk[-1] if walk else None,
            "rounds_n": len(rounds), "rounds": rounds,
            "evidence": [
                {"score": round(float(e.get("score") or 0), 4),
                 "body": (e.get("body") or "")[:100]} for e in ev_rows],
            "evidence_skipped": ev.get("skipped"),
            "jc_batches": jc_count() - jc_q0,
            "wall_s": round(time.time() - t_q0, 1),
        })
        r_log["queries"].append(qq)
        w_row = qq["walk"] or {}
        print(f"[R {q['id']}] steps={steps} walk_status={w_row.get('status')} "
              f"stop={w_row.get('stop_reason')} calls_used={w_row.get('calls_used')} "
              f"batches={qq['jc_batches']} {qq['wall_s']}s")
        print(f"        route={json.dumps(qq['route'], ensure_ascii=False)}")
        for e in qq["evidence"][:5]:
            print(f"        - {e['score']:.3f} | {e['body'][:60]}")
    r_log["wall_s"] = round(time.time() - t0, 1)
    LOG["phases"]["read"] = r_log

    # ---------- C 固化 ----------
    t0 = time.time()
    c_log = {"steps": []}
    jc_c0 = jc_count()
    for i in range(24):
        ret = one("SELECT v13_mgraph_consolidate(%s, 10)", (sid,), ask=True)
        c_log["steps"].append(ret)
        if (ret.get("asks") or 0) == 0 or ret.get("eligible"):
            break
    c_log["jc_batches"] = jc_count() - jc_c0
    enq = one("SELECT v13_mgraph_consolidate_enqueue(%s)", (sid,))
    c_log["enqueue"] = str(enq)
    if enq:
        cl = one("SELECT v13_claim('memtrial-worker', 120000)")
        if cl:
            req = cl.get("request") or {}
            c_log["request_keys"] = sorted(req.keys())
            lh, rh = req.get("left_hash"), req.get("right_hash")
            lb = one("SELECT body FROM memory_nodes WHERE session_id=%s "
                     "AND content_hash=%s", (sid, lh)) if lh else None
            rb = one("SELECT body FROM memory_nodes WHERE session_id=%s "
                     "AND content_hash=%s", (sid, rh)) if rh else None
            c_log["pair"] = {"left": lb, "right": rb}
            t_g0 = time.time()
            gen = deepseek.chat_completion(
                [{"role": "system", "content": CONS_SYSTEM},
                 {"role": "user",
                  "content": (lb or "") + "\n---\n" + (rb or "")}],
                json_mode=False, timeout_s=S.GENERATION_HTTP_TIMEOUT_S,
                settings=settings)
            c_log["gen_wall_s"] = round(time.time() - t_g0, 1)
            c_log["generated_text"] = gen.get("text")
            comp = one("SELECT v13_complete(%s,%s,%s,'succeeded',%s::jsonb)",
                       (str(cl["effect_id"]), cl["attempt_no"], cl["fence"],
                        json.dumps({"text": gen.get("text") or ""})))
            c_log["complete"] = comp
            settle = one("SELECT v13_mgraph_consolidate_settle(%s)",
                         (str(cl["effect_id"]),), ask=True)
            c_log["settle"] = settle
    c_log["consolidations"] = rows(
        "SELECT consolidation_key, status, subtype, left_hash, right_hash, "
        "product_hash FROM memory_consolidations WHERE session_id=%s", (sid,))
    c_log["nodes_by_origin_after"] = rows(
        "SELECT origin, count(*) AS n FROM memory_nodes "
        "WHERE session_id=%s GROUP BY origin", (sid,))
    c_log["consolidation_edges"] = rows(
        "SELECT rel, count(*) AS n FROM memory_links "
        "WHERE session_id=%s AND origin='consolidation' GROUP BY rel", (sid,))
    c_log["wall_s"] = round(time.time() - t0, 1)
    LOG["phases"]["consolidate"] = c_log
    print(f"[C    ] steps={len(c_log['steps'])} batches={c_log['jc_batches']} "
          f"enqueue={c_log['enqueue'][:60] if c_log['enqueue'] else None} "
          f"{c_log['wall_s']}s")
    for st in c_log["steps"][:6]:
        print(f"        cons_step: eligible={st.get('eligible')} asks={st.get('asks')}")
    for row in c_log["consolidations"]:
        print(f"        cons status={row['status']} subtype={row.get('subtype')} "
              f"product={str(row.get('product_hash'))[:12]}")
    if c_log.get("generated_text"):
        print(f"        generated: {c_log['generated_text'][:80]}")
    if c_log.get("settle"):
        print(f"        settle: {json.dumps(c_log['settle'], ensure_ascii=False)[:200]}")

    # ---------- E 收尾 ----------
    ver = bump_policy({})
    LOG["phases"]["epilogue"] = {"policy_final": ver}
    LOG["totals"] = {"jc_batches_phase2": jc_count() - jc0}
    print(f"[E    ] policy flipped back to v{ver} (both false); "
          f"phase2 batches={LOG['totals']['jc_batches_phase2']}")

    OUT.write_text(json.dumps(LOG, ensure_ascii=False, indent=1, default=str))
    print(f"[log  ] {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
