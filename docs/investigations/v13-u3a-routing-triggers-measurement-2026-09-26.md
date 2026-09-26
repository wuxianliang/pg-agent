# v13 U3a 路由触发测量（2026-09-26）

> 只读测量文书（利用方案 `docs/plans/v13-stannum-0.4-utilization-plan-2026-09-26.md` §3.5 U3a 行）。
> **基线绑定**：测量 commit = `010e10f`（U3c 已落地），tokenizer 形态 = **jieba 词级锚**
> （`v13_mgraph_anchor_terms` CJK 分支经 `stannum.tokenize(seg,'jieba')`；三生产索引
> `tokenizer=jieba`）。本文件不改任何 `v13/**`；测量库为 stage 夹具库
> `agent_v13_mgraph`（DROP/CREATE 重建，测量用 GUC mock 判断、真实 build/apply 机制）。
> 对照历史：2026-09-24 重跑（`docs/investigations/v13-dp9-mgraph-v2-demo-rerun-2026-09-24.md`
> ：33-:56，unicode 3-gram 基线）在本文件只作对照数字，**不**据其判任何触发已满足
> （M3-stop 十行之 2）；其 `edges_used=0` 台账维持原状。

## 0. 「可遍历」定义（先定义，后测量）

触发①原文（v2 计划 `:354`）用了未定义的「实际可遍历边」（M3-stop F1）。本文件定义：

**可遍历边**（traversable edge，按 rel 逐个判定，谓词即断言名）：
1. `memory_links` 存在该 rel 的 ≥1 行，且该行由**写路径**落图（`v13_mgraph_build`
   ×mock 判断 → `v13_mgraph_apply_relations` 产物；非测试直插——H4 夹具
   `test_mgraph.py:2970-2975`）不构成）；
2. **读侧一跳可跟**：对该边 src 调 `v13_mgraph_neighbors(sid, src, ARRAY[rel], 10)`
   返回该边 dst 且 rel 匹配。

**触发①读法 = 合取**：`causes`、`entity`、`contradicts` 三 rel 各自满足 1+2。
依据：原文把三 rel 写成封闭列举；②的意图差（causal/entity/semantic 路径）恰好
消费这三族 rel。`caused_by` 不顶替 `causes`（十行之 3）；**消费记账**
（`edges_used>0`）单独记录（§3），不进①谓词。

## 1. 夹具（写路径落图，全部真实机制）

一个会话 7 节点（5 CJK 密集组 + 2 latin 实体对），逐节点 stepper
（`write_enabled=true`，`write_max_batches=1` 每 tick，GUC mock 精确键匹配；
mem_type 默认 0.9=episodic，mem_rel 默认 0.9 全 TRUE——密集落边）：

```
N1 本次发布会到场人数约为三千二百人
N2 实际统计的到场人数只有九百人
N3 签到系统记录的到场人数是一千零五十人
N4 主办方通报的到场人数接近三千人
N5 现场估算的到场人数不超过一千二百人
E1 Alice shipped the crate.
E2 Bob ferried the drum.
```

词级锚下密集组内 5×4 对全部唤醒（共享 jieba 词 到场/人数）；E1↔E2 经 entity 闸
（不相交实体 Alice/Bob）唤醒。build 29 tick 完成。

## 2. 触发①测量（逐 rel，图上）

| rel | 落图边数 | 一跳可跟 | 判定 |
|---|---|---|---|
| `causes` | 22 | 22/22 | **可遍历** |
| `entity` | 2 | 2/2 | **可遍历** |
| `contradicts` | 11 | 11/11 | **可遍历** |

全图：caused_by=22、causes=22、contradicts=11、entity=2、proximity=11、
semantic=22、temporal=6（7 节点）。**触发①：已满足**（合取三 rel 全过，
基线 `010e10f`/词级 jieba）。

对照 09-24 重跑（unicode 3-gram、DeepSeek 活体）：`causes 0(0 过阈)`、
`entity 0`、`contradicts 2`、四 walk 全 `edges_used=0`（重跑 `:33,:37,:56`）。
差异主因=U3c 词级锚唤醒池（3-gram 滑窗下密集中文组共享 gram 的对多数不进
top-5 候选池；词级下 到场/人数 两词即全组互联）。旧重跑数字维持台账原状。

## 3. 消费记账（独立于①）

本基线上 live walk（§5）实测 `edges_used=5`、`depth=3`、`nodes_used=6`、
`calls_used=9`、`stop_reason=depth`。这是**本次**测量值，不回写 09-24 重跑的
`edges_used=0` 台账。触发①的判定不含本项。

## 4. 触发②测量（配额 + 扩展节点）

机制链（全 stage-15）：`route(q)→weights→allocate(weights)→六桶整数配额；
expand 相位按配额×`bucket_rels`×`neighbors` 扩展 pending`（`v13_mgraph.sql`
route :1477-1534 / allocate :1540-1629 / expand :2288-2350）。

**查询 A（全域）**`why 发布会到场人数统计不一致`：anchors n=5（beam=5 全组入
frontier）→ 扩展面剩 1 节点，配额未绑定 → 两 routing pending 相同。
（负对照，如实记录：配额差异仍成立，扩展差异在配额不绑定时不可见。）

**查询 B（定向，触发②主张面）**`why 签到口径是一千零五十人`：anchors n=1
（词级锚只命中 N3——签到/一千零五十 为 N3 独有词）。同一查询、两种 routing：

| | live `route()` | 配额 | 扩展（expand 语义复刻） |
|---|---|---|---|
| **superset（现行为）** | mode=superset，六桶全 1 | {causal:4, entity:4, recency:3, semantic:3, temporal:3, multi_hop:3} | pending=**3**，rels={caused_by, temporal} |
| **deterministic（counterfactual）** | —— | {causal:7, entity:3, recency:3, semantic:2, temporal:2, multi_hop:3} | pending=**4**，rels={caused_by} |

- superset 侧 weights/quota 为 **live 调用**实测；deterministic 侧权重向量 =
  deterministic 分支算术（floor=1 六桶 + primary=causal 得 2——latin 孪生查询
  `why did the checkin count say one thousand and fifty` **live 调用**返回
  mode=deterministic、weights 同值，交叉验证）；配额经 **live** `allocate()`。
  counterfactual 主张的依据：route 的 CJK 短路（`:1506-1507`）先于意图链
  （`:1513-1518`），短路不开则该查询含 `why` 必走 causal 主桶。
- **配额差异**：4 桶不同（causal 7v4、entity 3v4、semantic 2v3、temporal 2v3）。
- **扩展节点差异**：pending 集合不同（`sets_equal=False`；deterministic 独有
  扩展 1 节点 `b9cccff5…`，superset 配额花在 temporal 桶）。

**触发②：已满足**（同一中文意图查询，两种 routing 配额不同且扩展节点集合不同；
基线 `010e10f`）。

## 5. 触发③测量（不依赖 B2 装配的 walk gate 观测）

测量所用符号全部 stage-15（`v13_mgraph.sql`）：`v13_mgraph_route` /
`v13_mgraph_allocate` / `v13_mgraph_anchors` / `v13_mgraph_bucket_rels` /
`v13_mgraph_neighbors` / `v13_mgraph_next_action` / `v13_mgraph_run_round` /
`memory_walks`。零 stage-16（mgraph_assembly：manifest v4 / memory_graph 段 /
`mgraph_ver`）符号参与。

**live walk**（查询 B，真实 `run_round` 步进至 done，mock 判断）：round 1
traverse N3 → close → **expand 真实执行**（step9 pending=1 入列）→ round 2/3
→ `{'action':'done'}`；终态 walk 行 = `frontier` 5 节点、`nodes_used=6`、
**`edges_used=5`**、`depth=3`、`stop_reason=depth`、`calls_used=9`。§4 的
deterministic 侧扩展差异用同一组 stage-15 符号可观测（同 SQL、不同配额向量）。

**触发③：已满足**（差异在 stage-15 walk 面可观测，B2 装配零参与；基线 `010e10f`）。

## 6. 结论与 U3b 解锁

| 触发 | 判定 | 证据节 |
|---|---|---|
| ① causes/entity/contradicts 可遍历边（合取，先定义后测） | **已满足** | §0/§2 |
| ② 同一中文意图查询 superset vs deterministic 配额/扩展节点不同 | **已满足** | §4 |
| ③ 差异在不依赖 B2 的 walk gate 可观测 | **已满足** | §5 |

三条均「已满足」且证据与目标代码基线一致（本文件测量基线 = 当前 HEAD
`010e10f`）。**U3b（CJK 路由实现计划）获得动笔资格**（利用方案 §8-9）。
U3b 动笔时必须（M3-stop 十行之 1/5/7/8，v2 计划 `:354`）：

1. 正文自写 **`supersedes DP9-OQ3`**；
2. P1-8：新增只读 script 判定 helper（码点五区间与 route `:1493-1498` /
   segments 同表），禁改冻结的 `v13_query_segments`（`v13_recall.sql:13,70-72`）；
3. 同提交改 CJK 短路（`v13_mgraph.sql:1506-1507`）、E2（`test_mgraph.py:1610-1614`
   现锁反面）、G9 闭集（`:2813-2814,:2846`）；
4. 与 U3c 无并行在飞问题（U3c 已落盘 `010e10f`；两线不同改 `test_mgraph.py`
   的同区——E2/G9 与 G1/G2/G6 区段无重叠，仍建议串行提交）。

## 7. 复现要点（附录）

测量脚本形态（scratch，未提交；关键 SQL 逐字如下，psycopg2 驱动、每 tick 新连接
——README #8 的 GUC 占位符纪律）：

- 落图：`mk_session`（7 正文经 `v13_append_event`+`v13_rebuild_transcript_chunks`）
  → stepper 循环（`v13_gap` 找缺口信号 → `typesafe.mock_response` GUC 喂
  `{signal: noul 0.9}` → `SELECT v13_mgraph_build(sid, 100)` 至无缺口）。
- ①：`SELECT rel, count(*) FROM memory_links WHERE session_id=:sid GROUP BY rel`
  + 逐边 `SELECT count(*) FROM v13_mgraph_neighbors(:sid,:src,ARRAY[:rel],10)
  WHERE dst_hash=:dst AND rel=:rel`。
- ②：`SELECT v13_mgraph_route(:q)` / `SELECT v13_mgraph_allocate(:weights)` /
  `SELECT v13_mgraph_anchors(:sid,:q,'semantic')`；扩展=expand 相位同语义
  （逐桶 `bucket_rels`×`neighbors(...,left)`，frontier=anchors、跳 visited）。
- ③：`next_action→(envelope→gap→mock)→run_round` 循环至 done；
  `SELECT frontier,nodes_used,edges_used,depth,stop_reason,status,calls_used
  FROM memory_walks WHERE session_id=:sid`。
