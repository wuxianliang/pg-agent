# v13 jieba 整包计划（U3c，2026-09-26）

> **本计划正文自写 OQ15 重开句：本计划正式 supersede OQ15。** OQ15（v2 计划轮 1，
> 2026-09-23）裁定的「CJK 锚 = 字符 3-gram 滑窗（`anchor_ngram_n=3`）」与结案
> `docs/plans/v13-stannum-0.4-m3-m6-closeout-2026-09-25.md:28-32` 的「不切生产索引」
> 就此重开。重开依据 = 利用方案 `docs/plans/v13-stannum-0.4-utilization-plan-2026-09-26.md`
> §6-2 裁决（逃逸口生效：U2b 已于 `69728df` 全绿落盘，U3a 未在飞、U3b 未动笔，无并行
> 在飞线）。重开的范围以结案 `:32` 四件为闭集：词级锚、L3 重写不放宽、highlight 绑定
> 断言（U2b 已先行交付 P5b，本包**扩展**之，不另起平行断言）、G6 同提交重写；外加
> 结案 `:30` 的生产索引切换与「`decisions.question` 永不切换」。四件缺一不可，
> 单一原子提交交付。

## 0. 输入与前置

- 探针（技术底料）：`docs/investigations/v13-jieba-canary-probe-2026-09-25.md`
  §2（分词对照）/§3（命中集）/§4.2（extract_spans 不对称）/§7（治理）/§9（整包裁决）。
- 结案：`docs/plans/v13-stannum-0.4-m3-m6-closeout-2026-09-25.md:28-32`（四件闭集）。
- 利用方案：`docs/plans/v13-stannum-0.4-utilization-plan-2026-09-26.md` §2①/§3.5/§6-2/§8-8。
- 前置核对（已做）：U2b=`69728df` 在 origin/main；无 U3a 在飞（无会话无文档）；
  `stannum.tokenize(text, tokenizer, …defaults)` / `stannum.bind_query(query, index)`
  签名已实测；全部 gate 夹具的 jieba 切分已实测（§2.1 表）。

## 1. 改动面（机制合同）

### 1.1 词级锚（`v13/mgraph/v13_mgraph.sql:3202-3238`）

`v13_mgraph_anchor_terms` 的 CJK 分支从字符 n-gram 滑窗改为
`stannum.tokenize(v_seg, 'jieba')` 词级：

- latin 段（`^[A-Za-z0-9]+$`）整项——**不变**；
- `anchor_ngram_n = 0`：CJK 段整项（全段 OR 退化）——**保留**（G1 语义不动）；
- `anchor_ngram_n > 0`：CJK 段 → jieba 词项，去重保序，超 `anchor_max_terms` 保序截断。
  `anchor_ngram_n` 的具体正值**不再改变 CJK 词形**（2/3/4 同词集）——键与读取器闭集
  原样保留（mgraph 策略行 v2 41 键字节不动，A2 不翻），语义降格为「0=全段 / >0=词级」
  两档；本计划正文就此宣布该键名义退役（ngram 名不副实），改形态只经本重开文书。
- `'jieba'` 字面量与 `ix_memory_nodes_stannum` 的 `tokenizer=jieba` reloption **同文件
  耦合**：G6 重写新增耦合锁（indexdef 含 `tokenizer=jieba` 且 anchor 函数体含
  `'jieba'`），分叉即红。匹配侧 `ql_parse` 用索引分析器对查询重切——词项粒度与
  tokenize 默认参数（`max_token_bytes=256` vs 索引 64）的小漂移不改命中集（短语语义
  跨切分对齐），只影响项粒度；锚段 ≤256B 在 tokenize 默认界内。
- 函数仍 STABLE、零 `==>`、零动态 EXECUTE、不访问表（tokenize 是纯 C 函数，无表 IO）。
  守卫 `v13_mgraph_anchor_guard` 文法**字节不动**（词项=段内子串，无空格、域内字符，
  引号短语 OR 闭集不变）。
- 头部注释块（:3186-3199）同步改写：n-gram 机制描述 → 词级 + OQ15 重开记载。

### 1.2 生产索引切换（三张，decisions 不切）

| 索引 | 文件:行 | 改动 |
|---|---|---|
| `ix_chunks_stannum` | `v13/characterize/v13_characterize.sql:29` | `WITH (tokenizer=jieba)` |
| `ix_transcript_stannum` | `v13/memory/v13_memory.sql:32` | `WITH (tokenizer=jieba)` |
| `ix_memory_nodes_stannum` | `v13/mgraph/v13_mgraph.sql:49` | `WITH (tokenizer=jieba)` |
| `ix_decisions_question_stannum` | `v13/memory/v13_memory.sql:161` | **不动**（ASCII 列零收益，结案 :30） |
| `ix_v13_canary` | `v13/characterize/v13_characterize.sql:26` | **不动**（诊断夹具，`long_tokens`/`max_token_bytes` 语义照旧） |

stage 库每次 DROP/CREATE 重建，无在库 REINDEX 动作；生产部署语义 = 改 SQL + REINDEX，
写进 README。

### 1.3 `v13_extract_spans` 换体（characterize swap 处）

`v13/characterize/v13_characterize.sql:31-79` 的 CREATE OR REPLACE 换体（chunk 期
:608 的原定义**不动**——stage 7 无扩展无索引，绑定不可用）：

- `:59` 调用形状改为
  `stannum.highlight(p_body, v_open, v_close, stannum.bind_query(v_tinql, 'ix_chunks_stannum'::regclass))`
  ——spans 跟随生产索引 analyzer（jieba），消「召回有、spans 空」（探针 §4.2）。
- 挥发性保持 IMMUTABLE：`bind_query(query, index)` 本身 IMMUTABLE（实测 pg_proc），
  regclass 解析模式与 planner 支持函数自身改写式同款。
- 唯一生产消费者 = chunks 检索（v13_recall 内联调用，P0a 期望 SQL 文本不变）；
  recall 期（stage 8）走 chunk 原定义不绑索引，B3/K 族不受影响（探针 §8）。

### 1.4 GRANT 面（tokenize 进正本与镜像）

锚函数（INVOKER）在 build/anchors/transition_score 链上被 `v13_resolve` 调起 → 需要
`stannum.tokenize(text,text,text,text,text,integer,text,text)` EXECUTE。canonical
GRANTS 块（`v13/mgraph/setup_db.py:41-47`）追加该函数，授予
`v13_recall, v13_resolve, v13_route`（镜像 score_bound 形状——锚函数 ACL 面本就三角色）。
**12 份 stage `setup_db.py` 全部同提交同步**（R21 比对全等），外加 **3 份
`demo_v13/setup_db*.py` 镜像**（U1a 已核镜像一致性，锚实路径 demo 链同样需要）。

### 1.5 usage gate 断言面

| 断言 | 现文 | 改法 |
|---|---|---|
| P4（:780） | `n_ka == 0` | `n_ka >= 1`——单字片假名**过召回命中**（`タ` 命中 `タワー` 拆字），注明是过召回不是质量提升；禁 OR 兼容旧值 |
| P5b（:835） | 短语区间相等（unicode 现状锁） | **扩展为 jieba 形态**：保留 `"東京タワー"` 短语 extract_spans↔绑定哨兵区间相等；新增 `"タ"` 单字 case——extract_spans 非空且与绑定哨兵区间相等（索引回退 unicode 时该行不命中→空→红，即「能区分 jieba 与默认 unicode」的实现） |
| P12（:1025） | 生产四索引无 tokenizer/jieba 字样 | chunks/transcript/memory_nodes 恰 `tokenizer=jieba`；decisions 无 tokenizer；canary 闭集不动 |
| F6（:1107） | `no_jieba`（五索引无 jieba） | 三索引有 jieba、decisions/canary 无 |
| F14（:1170） | `tokenize` 在 ZERO_FUNCS + 限定名源码扫描 | `tokenize` 移出 ZERO_FUNCS/ZERO_QUALIFIED；新增限定断言：`stannum.tokenize` 在 files_through("mgraph") 去注释源码恰出现 1 次（锚调用点）；P2 测量窗内 tokenize 调用增量仍为 0（recall 路径不触锚） |
| R19/R20 | score_bound 特权矩阵 | 不动（tokenize 特权由 GRANTS+R21 承载） |

### 1.6 characterize/mgraph gate 断言面

| 断言 | 现文 | 改法 |
|---|---|---|
| L3（`test_characterize.py:495-503`） | 短语命中 ✓ + `タ` miss | 短语两条不动；`タ` miss → `タ` **命中 ≥1 且每行含 `タ` 字**（jieba 拆字过召回，注明非质量提升；禁 OR 兼容） |
| R2（:845-860） | file9 `stannum.` 计数 3（norm+raw） | bind_query 入 extract_spans → 计数 +1，两处期望同步实算值；`==>` 计数 2 不变 |
| G1 flip（`test_mgraph.py:2572-2578`） | n 3→2 改变形状（硬编码 gram 集） | 改为 n 3→0 改变形状（全段 vs 词级）；**新增** n=2 词集 == n=3 词集断言（键退役的显式记载） |
| G2（:2600-2626） | n-gram 边界族 | 词级重写：CJK 段→jieba 词集（用已实测夹具）、去重、混排 latin 整项、255B 段 48 截断、>256B V3005、分隔符空锚——后四条原样保留，边界三条按词级语义改写 |
| G4（:2670+） | 共享 3-gram 唤醒 | 夹具不动（GA/GB 共享 jieba 词 `受/影响/用户`，实测切分表已证）；注释 3-gram→共享词 |
| G5/G6/G7（:2709-2775） | 锚池驱动/纪律复扫 | G5 夹具不动（词级下两断言方向均成立，实测）；G6 四件不动 + 新增耦合锁（§1.1）；G7 不动 |
| E/H/D/A 组 | 行为面 | 断言不动，跑绿为准（词级改变池内容不改变确定性/闭集断言） |

### 1.7 冻结哈希与 README

- `PREFIX_FREEZE`（`v13/mgraph_assembly/test_mgraph_assembly.py`）：characterize/
  memory/mgraph 三哈希同提交重钉，比较式不宽化。
- `v13/mgraph/README.md`：机制 11 条改词级 + OQ15 重开记载 + `anchor_ngram_n` 两档语义
  + jieba 耦合锁 + F14 rescope。
- `v13/characterize/README.md`：追加 jieba 治理三条（预热 ≈200ms/≈95MB RSS 按探针实测
  写，不按底稿「数 MB」；漂移看 `index_stats.analysis_detail`/`index_analysis`，不看
  `\d`；`strict_analysis` 只在 Custom Scan 路径 fail-closed，小表 Seq Scan 不执法——
  探针 §7）+ extract_spans 绑定换体记载。
- `v13/memory/README.md`：transcript 索引 jieba 切换一行。

## 2. 明确不做

- 不改 `v13_mgraph_route`/E2/G9 闭集（DP9-OQ3 不在本包重开范围）。
- 不切 `ix_decisions_question_stannum`、不动 `ix_v13_canary`。
- 不动 mgraph 策略行 v2（41 键字节不变，A2 不翻）；`anchor_ngram_n` 只经本重开文书
  宣布语义降格，不改键名不改值域。
- 不动 `v13_query_segments`（冻结）；不动 `v13/recall/v13_recall.sql`、
  `v13/chunks/v13_chunks.sql` 的 extract_spans 原定义。
- 不设 `score_stop_words`、不改三处 `full_score`（利用方案 §4-5 维持不做）。
- 不写死 usage gate 断言条数。

## 3. 执行序与回归

单一原子提交（四件闭集 + 索引切换 + GRANTS + 断言同步 + README + 冻结哈希重钉）。

```bash
uv run python v13/mgraph/test_stannum_usage.py   # P4/P5b/P12/F6/F14
uv run python v13/mgraph/test_mgraph.py          # G1/G2/G4/G5/G6 + A/D/E/F/H 回归
uv run python v13/characterize/test_characterize.py  # L3/R2 + K/M/N/P/R
uv run python v13/memory/test_memory.py          # transcript 索引 + N 族
uv run python v13/mgraph_assembly/test_mgraph_assembly.py  # PREFIX_FREEZE + J 族
# 全绿后总集成：八命令 + control/spawn/fanout/triage + test_chunks（stage-7 面）
```

`test_stannum_usage.py` 与 `test_mgraph.py` 共用 `agent_v13_mgraph`，串行。

## 4. 回退

单提交 revert：三索引回 unicode、锚回 3-gram、extract_spans 回 4 参 text、GRANTS 回
canonical 块、断言回退、三哈希回钉。stage 库 DROP/CREATE 即重建，无数据迁移面。
生产面 = REINDEX 回 unicode（README 记载）。回退不保留任何 jieba 形态断言。
