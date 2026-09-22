# v13 recall —— T0 tsvector 召回与 TINQL 构造器（DP5 stage 8）

Gate: `uv run python v13/recall/test_recall.py`（退出码 0 = 通过）

库名 `agent_v13_recall`。加载 core + resolve + advance + twophase +
envelope + manifest + chunks + `v13_recall.sql`（`files_through('recall')`
八文件前缀）。**本 stage 零依赖 text-search 扩展**（不变量 7）。

## 机制

- 查询构造器三层：`v13_query_segments` → `v13_build_tinql` → `v13_tinql_terms`。
  输出=全语段引号包裹 AND 连接；注入免疫是构造性的（输出语法形状封闭）。
- `v13_recall` / `v13_recall_count` T0 走 `chunks.body_tsv` + `ts_rank`
  （**T0 的 bm25 列是词法排序值，不是 BM25 语义**）。
- `v13_recall_candidates` 是信封与装配的**单一来源**（哈希同源）。
- 语料 DML 经 `v13_chunks_generation_bump` 同时 +1 `generation` 与 `cgr`
  （DP1 #59）。
- token 第九键 `recall_ver` = 活动 `recall_k` 策略版本。

## 运维纪律

1. **k 策略 / 公式 / 硬上限 / 一页账**
   `recall_k` v1：`{"k_base":8,"widen_ratio":0.05,"k_max":64,"timeout_ms":800}`。
   公式：`k = least(k_max, greatest(k_base, ceil(matched × widen_ratio)))`。
   `k_max=64` 是 F5 首版硬上限。k_base 8=1 批全快路；k_max 64=2 批 1 往返。
   放宽 = 新版本行 + 同事务翻 active，且须 **DP7 重开一页账 + tier 快路超批裁决**
   （本 stage 不放宽）。

   | k | per-chunk 批数 ⌈k/32⌉（DP6 起） | 快路批 | 慢路批（effect 往返） | 量级（实测 1.3–1.6s/批） |
   |---|---|---|---|---|
   | 8（k_base） | 1 | 1 | 0 | 快路内，零往返 |
   | 32 | 1 | 1 | 0 | 同上 |
   | **64（k_max）** | 2 | 1 | 1 | ≈1 往返 |
   | 128（越界形态，仅示意） | 4 | 1 | 3 | ≈3 往返 |

2. **驱动契约（timeout）**：parse 驱动在调信封前
   `SET statement_timeout` ≤ `recall_k.timeout_ms`（引擎事实 #60：函数体内
   set_config 不治理嵌套语句）。超时 = `query_canceled` → 解析事务整体失败
   → G-ctx8 幂等重推。**零静默回落**。

3. **三禁纪律**（生产面冻结 DDL；gate fixture 测后即弃）：
   - 视图内嵌 bind 算子禁止
   - plpgsql 静态 bind 算子禁止
   - worker 预备语句直发 bind 算子禁止
   - worker 预备语句面 = v13 worker 契约文档；本库零 worker SQL

4. **T0 边界**：CJK 子串在 tsvector 路径零召回（既裁，走第 9 位刻画）；
   Latin-1 变音字母按分隔符归类；`ts_rank` 不虚标 BM25。

5. **注入免疫**：分段器只产词，操作符字符全是分隔符；发射全引号包裹；
   回析器只接受自产文法，异形 V3005。用户文本不得直接成为 TINQL。

6. **ACL**：六新函数 EXECUTE 授 `v13_recall` / `v13_resolve` / `v13_route`；
   `SELECT` ON `chunks` / `v13_sources` / `v13_chunks_meta` 授 resolve 与
   route（信封 parse 在 resolve 下、装配直调面在 route，授权随第一消费点）。

7. **退役源**：召回 `JOIN v13_sources … superseded_by IS NULL`。B5mix 垫层：
   被引用行可留在已退役源上，读侧必须靠 JOIN 过滤，不能靠行已删除。

8. **翻版 recall_k**：追加新版本行 + 同事务翻 active。禁删 active 行
   （策略行 append-only）。缺活动行 → token RAISE（与 `asm_ver` 同姿势）。

## 回退

删 `v13/recall/` + `v13/load.py` 两处注册（`SQL_LOAD_ORDER` 末项与
`STAGE_THROUGH['recall']`）+ DROP 库 `agent_v13_recall`。DP1–DP4 文件零改动。

## 台账

- **① validator 九键同步（实现必要缝）**：DP4 `v13_manifest_validate` 把
  `required_revision` 钉死八键。token 扩 `recall_ver` 后 settle 必 V3003。
  本文件 `CREATE OR REPLACE` 同签名换体，键集改为
  `asm_ver,corpus,dec,gen_ver,goal,jdef_ver,recall_ver,sem,tools_rev`
  并校验 `recall_ver≥1`。上游文件零改动。无此缝则 E1/I2 真实 refresh
  链路不可达。同型于 DP4 README ⑤ corpus 键缝（plan §1.1 封闭清单未列
  此换体，属实现必要缝，不改 plan）。
- **② timeout_ms NULLIF**：信封换体从加载态原文机械复制，保留 DP2
  `NULLIF(current_setting(…), '')`，不回退为 plan 草案的裸 `current_setting`。
- **③ I4 缺行**：策略行禁 DELETE；用 `active=false` 制造无活动行，语义等价。
- **④ L4 §5 P2 精选收口**（2026-09-22，
  `docs/reviews/v13-dp5-impl-l4-review-2026-09-22.md`，仅测试面 SQL 零改动）：
  B1 补 GIN belt——`enable_seqscan=off` 下 EXPLAIN 内层 `body_tsv @@` 谓词计划
  含 `ix_chunks_tsv`；B2 换必并列 fixture（`quasar alpha tiepad1/2`，查询词同位
  同长度同分）去 `if` 跳过，断言恰一对+分并列+hash 截断；I3 复用 C3 的 4000
  匹配语料（sid 改查 maxium）断言翻版前后 manifest 候选 64→16（原来只 <=16）。
