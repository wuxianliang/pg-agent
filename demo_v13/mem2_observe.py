"""Post-hoc read-only observations for the v2 rerun trial (corrected patterns).

树内实验文件(gitignored)。v13 signals 形如 'mem_rel::<h>::<h>::<rel>'
(冒号分隔);mem2_mgraph.py 里沿自 v1 memdrive_mgraph 的 'mem\_rel\_%'
(下划线转义)模式全部空结果——本脚本用正确模式重取,并补 T2↔T6 解剖、
contradicts 边明细、锚候选重构(STABLE 函数,零 ask)。

输出: demo_v13/memtrial2/observe_log.json + stdout。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGENT_ROOT = HERE.parent
sys.path.insert(0, str(AGENT_ROOT))

import server  # noqa: E402

server.get_server()

import psycopg2  # noqa: E402

DB = "agent_v13_demo_mem2"
URI = ("postgresql://postgres:@/%s?host=%s"
       % (DB, "/Users/wxl/Projects/pg-agent/.pgdata"))
OUT = HERE / "memtrial2" / "observe_log.json"
LOG: dict = {}


def rows(sql, params=None):
    conn = psycopg2.connect(URI)
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        conn.close()


def one(sql, params=None):
    conn = psycopg2.connect(URI)
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def main() -> int:
    sid = one("SELECT session_id FROM events WHERE type='user/message' "
              "GROUP BY session_id HAVING count(*) >= 8 "
              "ORDER BY max(at) DESC LIMIT 1")
    sid = str(sid)
    LOG["sid"] = sid
    print(f"[sid  ] {sid}")

    # ---- 类型判定(修正模式) ----
    LOG["type_winners"] = rows(
        "WITH t AS (SELECT split_part(signal,'::',2) AS hash, "
        "  split_part(signal,'::',3) AS slot, (answer->>'noul')::numeric AS v "
        "  FROM decisions WHERE session_id=%s AND signal LIKE 'mem_type::%%' "
        "  AND answer IS NOT NULL), "
        "r AS (SELECT hash, slot, v, row_number() OVER "
        "  (PARTITION BY hash ORDER BY v DESC, slot ASC) rn FROM t) "
        "SELECT slot, count(*) AS n FROM r WHERE rn=1 GROUP BY slot "
        "ORDER BY n DESC", (sid,))
    LOG["type_detail"] = rows(
        "WITH t AS (SELECT split_part(signal,'::',2) AS hash, "
        "  split_part(signal,'::',3) AS slot, (answer->>'noul')::numeric AS v "
        "  FROM decisions WHERE session_id=%s AND signal LIKE 'mem_type::%%'), "
        "r AS (SELECT hash, slot, v, row_number() OVER "
        "  (PARTITION BY hash ORDER BY v DESC, slot ASC) rn FROM t) "
        "SELECT left(n.body, 42) AS body_head, rr.slot, round(rr.v,3)::float8 AS noul "
        " FROM r rr JOIN memory_nodes n ON n.session_id=%s "
        " AND n.content_hash=rr.hash WHERE rr.rn=1 "
        " ORDER BY n.source_at", (sid, sid))
    LOG["mem_type_n"] = one(
        "SELECT count(*) FROM decisions WHERE session_id=%s "
        "AND signal LIKE 'mem_type::%%' AND answer IS NOT NULL", (sid,))

    # ---- 关系判定(修正模式) ----
    LOG["mem_rel_by_rel"] = rows(
        "SELECT split_part(signal,'::',4) AS rel, count(*) AS n, "
        "       round(avg((answer->>'noul')::numeric),3)::float8 AS avg_noul, "
        "       round(max((answer->>'noul')::numeric),3)::float8 AS max_noul, "
        "       count(*) FILTER (WHERE (answer->>'noul')::numeric >= 0.60) AS over_thr "
        "FROM decisions WHERE session_id=%s AND signal LIKE 'mem_rel::%%' "
        "  AND answer IS NOT NULL GROUP BY rel ORDER BY n DESC", (sid,))
    LOG["rel_pairs_asked"] = one(
        "SELECT count(DISTINCT split_part(signal,'::',2)||'>'||split_part(signal,'::',3)) "
        "FROM decisions WHERE session_id=%s AND signal LIKE 'mem_rel::%%'", (sid,))
    LOG["rel_direction_pairs"] = rows(
        "SELECT count(*) FILTER (WHERE split_part(signal,'::',2) < split_part(signal,'::',3)) AS canonical, "
        "       count(*) FILTER (WHERE split_part(signal,'::',2) > split_part(signal,'::',3)) AS reverse, "
        "       count(DISTINCT least(split_part(signal,'::',2),split_part(signal,'::',3)) || '>' || "
        "              greatest(split_part(signal,'::',2),split_part(signal,'::',3))) AS unordered_pairs "
        "FROM decisions WHERE session_id=%s AND signal LIKE 'mem_rel::%%'", (sid,))

    # ---- contradicts 全量明细 ----
    LOG["contradicts_decisions"] = rows(
        "SELECT split_part(signal,'::',2) AS src, split_part(signal,'::',3) AS dst, "
        "       round((answer->>'noul')::numeric,3)::float8 AS noul, decision_id "
        "FROM decisions WHERE session_id=%s "
        "  AND signal LIKE 'mem_rel::%%::contradicts' AND answer IS NOT NULL "
        "ORDER BY (answer->>'noul')::numeric DESC", (sid,))
    LOG["contradicts_edges"] = rows(
        "SELECT l.src_hash, l.dst_hash, l.decision_id, "
        "       left(a.body,36) AS src_body, left(b.body,36) AS dst_body "
        "FROM memory_links l "
        "JOIN memory_nodes a ON a.session_id=l.session_id AND a.content_hash=l.src_hash "
        "JOIN memory_nodes b ON b.session_id=l.session_id AND b.content_hash=l.dst_hash "
        "WHERE l.session_id=%s AND l.rel='contradicts'", (sid,))

    # ---- T2↔T6 解剖 ----
    t2h = one("SELECT content_hash FROM memory_nodes WHERE session_id=%s "
              "AND origin='episodic' AND body LIKE %s", (sid, '%初步统计约三万%'))
    t6h = one("SELECT content_hash FROM memory_nodes WHERE session_id=%s "
              "AND origin='episodic' AND body LIKE %s", (sid, '%实际只有八千%'))
    pair = {"t2_hash": t2h, "t6_hash": t6h}
    lo, hi = sorted([t2h, t6h])
    pair["t2_is_lo"] = (t2h == lo)
    pair["signals_lo_hi"] = rows(
        "SELECT split_part(signal,'::',4) AS rel, round((answer->>'noul')::numeric,3)::float8 AS noul "
        "FROM decisions WHERE signal LIKE %s AND answer IS NOT NULL",
        ("mem_rel::" + lo + "::" + hi + "::%",))
    pair["signals_hi_lo"] = rows(
        "SELECT split_part(signal,'::',4) AS rel, round((answer->>'noul')::numeric,3)::float8 AS noul "
        "FROM decisions WHERE signal LIKE %s AND answer IS NOT NULL",
        ("mem_rel::" + hi + "::" + lo + "::%",))
    pair["proximity_edge"] = rows(
        "SELECT src_hash, dst_hash, round(structural::numeric,3)::float8 AS structural "
        "FROM memory_links WHERE session_id=%s AND origin='proximity' "
        "AND ((src_hash=%s AND dst_hash=%s) OR (src_hash=%s AND dst_hash=%s))",
        (sid, t2h, t6h, t6h, t2h))
    pair["all_links_between"] = rows(
        "SELECT rel, origin FROM memory_links WHERE session_id=%s "
        "AND ((src_hash=%s AND dst_hash=%s) OR (src_hash=%s AND dst_hash=%s))",
        (sid, t2h, t6h, t6h, t2h))
    # 锚候选重构:两方向各取 top-5,看对方是否在池内(STABLE,零 ask)
    for label, h in (("t2", t2h), ("t6", t6h)):
        body = one("SELECT body FROM memory_nodes WHERE session_id=%s "
                   "AND content_hash=%s", (sid, h))
        tinql = one("SELECT v13_mgraph_anchor_tinql(%s)", (body,))
        cands = rows(
            "SELECT c.content_hash, round(c.lexical_norm::numeric,3)::float8 AS lexical, "
            "       (c.content_hash = %s) AS is_peer "
            "FROM v13_mgraph_candidates(%s, %s, 5) c", (h, sid, tinql))
        pair[f"anchor_{label}"] = {
            "tinql_head": tinql[:90],
            "n_terms": 0 if not tinql else tinql.count(" OR ") + 1,
            "candidates": [
                {"hash": c["content_hash"][:12], "lexical": c["lexical"],
                 "peer": c["is_peer"],
                 "body": (one("SELECT left(body,30) FROM memory_nodes "
                              "WHERE session_id=%s AND content_hash=%s",
                              (sid, c["content_hash"])) or "")}
                for c in cands]}
    LOG["pair_t2_t6"] = pair

    # ---- 图形状汇总 ----
    LOG["links_by_rel_origin"] = rows(
        "SELECT rel, origin, count(*) AS n FROM memory_links "
        "WHERE session_id=%s GROUP BY rel, origin ORDER BY n DESC", (sid,))
    LOG["proximity_structural"] = rows(
        "SELECT round(min(structural::numeric),3)::float8 AS min_s, "
        "       round(avg(structural::numeric),3)::float8 AS avg_s, "
        "       round(max(structural::numeric),3)::float8 AS max_s "
        "FROM memory_links WHERE session_id=%s AND origin='proximity'", (sid,))
    LOG["consolidations"] = rows(
        "SELECT consolidation_key, status, effect_id, body_hash "
        "FROM memory_consolidations WHERE session_id=%s", (sid,))
    LOG["cons_pairs_now"] = one(
        "SELECT count(*) FROM v13_mgraph_cons_pairs(%s)", (sid,))
    LOG["progress"] = one("SELECT v13_mgraph_progress(%s)", (sid,))
    LOG["policy"] = rows(
        "SELECT version, active, value->>'write_enabled' AS w, "
        "value->>'read_enabled' AS r FROM v13_policies "
        "WHERE name='mgraph' ORDER BY version")

    OUT.write_text(json.dumps(LOG, ensure_ascii=False, indent=1, default=str))
    print(f"[type ] winners={LOG['type_winners']} n={LOG['mem_type_n']}")
    print(f"[rel  ] by_rel={LOG['mem_rel_by_rel']}")
    print(f"[rel  ] pairs={LOG['rel_pairs_asked']} dirs={LOG['rel_direction_pairs']}")
    print(f"[contra] decisions={json.dumps(LOG['contradicts_decisions'], ensure_ascii=False)[:400]}")
    for e in LOG["contradicts_edges"]:
        print(f"[contra] edge {e['src_hash'][:10]}-> {e['dst_hash'][:10]} :: "
              f"{e['src_body']} || {e['dst_body']}")
    p = pair
    print(f"[t2t6 ] t2_is_lo={p['t2_is_lo']} lo_hi={[r['rel']+':'+str(r['noul']) for r in p['signals_lo_hi']]} "
          f"hi_lo={[r['rel']+':'+str(r['noul']) for r in p['signals_hi_lo']]}")
    print(f"[t2t6 ] links={p['all_links_between']} prox={p['proximity_edge']}")
    print(f"[t2t6 ] anchor_t2 peer_in_top5={any(c['peer'] for c in p['anchor_t2']['candidates'])}")
    print(f"[t2t6 ] anchor_t6 peer_in_top5={any(c['peer'] for c in p['anchor_t6']['candidates'])}")
    for c in p["anchor_t6"]["candidates"]:
        print(f"        t6 cand {c['hash']} lex={c['lexical']} peer={c['peer']} {c['body']}")
    print(f"[graph] links={LOG['links_by_rel_origin']}")
    print(f"[cons ] pairs_now={LOG['cons_pairs_now']} rows={LOG['consolidations']}")
    print(f"[log  ] {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
