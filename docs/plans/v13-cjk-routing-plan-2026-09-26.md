# v13 CJK 路由重开计划（U3b，2026-09-26）

> **本计划正文自写重开句：本计划 supersedes DP9-OQ3 routing branch（CJK→superset 短路）。**
> 被重开的裁决：DP9 §1.3-OQ3「CJK 段→superset 六桶 ≥floor、routing asked=0」经 v2 计划
> R1 修订记录维持（`docs/plans/v13-dp9-mgraph-v2-plan-2026-09-24.md:55,:98`），OQ13=D
> （v2 计划 `:354`）把重开入口钉为三条夹具式触发。**三条已全部实测满足**
> （U3a 文书 `docs/investigations/v13-u3a-routing-triggers-measurement-2026-09-26.md`
> §6，基线 `010e10f`/jieba 词级；测量 commit=当前 HEAD，证据与目标代码基线一致）。
> 本计划 = 那个入口的兑现：CJK 路由升级为设计 B（中文意图锚词表 + 混合语言优先，
> CJK 调查 §3 推荐、§5 OQ-13 草案机制面）。
>
> 不重开的：`v13_query_segments` 冻结不动（`v13/recall/v13_recall.sql:13,70-72`）；
> `decisions.question` ASCII CHECK 不动；jieba/词级锚面不动（U3c 已落盘 `010e10f`）。

## 0. 前置核对（已做）

- U3a 三条「已满足」+ 证据绑定 HEAD ✓（同日，无漂移）。
- 与 U3c 无并行在飞（已落盘推送）；与任何在飞线无 `test_mgraph.py` 同区冲突。
- E 组 walk 夹具查询清单：latin `alpha beacon` 族（不受词表影响）+ 唯一 CJK walk
  `为什么部署失败`（E2 :1622，断言仅零 mem_route 行——翻转后仍成立）。
- 下游 gate（assembly/control/spawn/fanout/triage/usage）无 mgraph 策略版本/键数硬断言
  （assembly J4/seed_walk 全部动态取 active 版本）。

## 1. 机制合同（单一原子提交）

### 1.1 route 模式判定重排（`v13_mgraph.sql:1477-1534`）

检测序改为（CJK 调查 §5 机制面逐字）：

1. `routing_mode='jev'` → mode=jev（权重不作分配输入）——**不变**；
2. **意图锚链（对全查询执行，互斥序不变）**：`routing_intent_causal` 词表 ∪ latin
   `why` > `routing_intent_temporal` 词表 ∪ latin `when` > 大写实体
   （`v13_mgraph_entities`）→ mode=**deterministic**，命中桶 =floor+1；
   multi_hop/recency 点名加升（latin 关键词）**不变**；
3. 未命中 ∧ `v13_mgraph_script_cjk(q)` → mode=**superset**（六桶 floor）；
4. 未命中纯 ASCII → mode=deterministic、primary=semantic（现状）。

效果：`why Zephyr 无法登录`→deterministic causal；`为什么部署失败`→deterministic
causal（词表命中）；`数据库备份策略`（无锚纯 CJK）→superset；纯 ASCII 无锚→
semantic（现状）。substring 匹配语义沿 OQ3 英文先例（`'when'⊂'whenever'` 同阶）。
entity 桶**不做中文锚**（调查 §3-B：无大写形态学；候选面 `entity_jaccard` 已承载；
「谁/哪个」代词锚留 OQ 附件不进本包）。

### 1.2 P1-8 只读 script helper（新函数，mgraph-local）

`v13_mgraph_script_cjk(p_body text) returns boolean`——STABLE、零 IO、零 `==>`、
码点五区间表与 route 内联扫描（`:1491-1503`）及 `v13_query_segments`（`:34-44`）
同一权威表：12352-12543 / 13312-19903 / 19968-40959 / 44032-55215 / 63744-64255。
route 的内联字符循环删除，改调本 helper（消内联复制；单一真相）。**不改**
`v13_query_segments`。gate 验证边界一致（§1.5-G10）。

### 1.3 词表进策略行（v2→v3，43 键；不变量 12 合规）

- 键：`routing_intent_causal: text[]`、`routing_intent_temporal: text[]`（`entity_stopwords`
  先例——字符串数组进 mgraph 策略 JSON；函数体零词面）。
- 种子值（调查 §4 闭集）：
  - causal（9）：`为什么,为何,缘何,何以,原因,缘故,成因,怎么回事,怎么会`
  - temporal（7）：`何时,什么时候,啥时候,几点,哪天,哪一年,多久`
- 语义纪律（调查 §4 逐条）：`怎么`/`何`/`会` 单字禁独立成锚；`几点⊂以下几点`
  接受（代价=wrong-bucket 一格升权，floor+1 与 floor 之差，轻）；空数组=回退现状
  （superset）——词表回滚只需策略翻版不需代码。
- 读取器 `v13_mgraph_policy()`：键集全等串 +2；域校验：两键均 text[]、元素非空且
  octet_length≤256、每桶 cardinality≤16（域界常数，非动作阈）。
- 种子行就地升版 v2→v3（单行纪律；v1/v2 语义记载保留在注释与 README）。
  其余 41 键逐字不动。翻版 → `policy_version=3` 进 walk 身份与 `mgraph_ver` digest
  （by design；asm_ver 无版本值断言）。

### 1.4 gate 面（同提交）

| 面 | 改法 |
|---|---|
| `EXPECTED_POLICY`（test_mgraph :53-99） | +2 键（v3 形状）；全部 bump/set_active 随之 |
| `set_active("mgraph", 2)` ×19 处 | → 3（机械替换，逐处核对语义为「翻回种子版」） |
| A2（:364 起） | `ver==3`、43 键逐键全等；标签 v2→v3 |
| E2 :1610-1614 | 分句替换：`为什么部署失败`→deterministic 且 causal 严格最大（与英文 WHY 断言同形）；**新增**无锚纯 CJK `数据库备份策略`→superset+全桶≥floor+allocate 每桶≥1（原断言平移）；**新增**混合 `why Zephyr 无法登录`→deterministic causal |
| E2 walk :1622-1627 | 零 mem_route 行断言保留（deterministic 仍零 ask；标签语义更新） |
| G9 :2810-2814,:2846 | 键集 43、routing_intent 两键**在闭集内**（text[] 域）；数值注入 `routing_intent_causal=0.8` 仍 V3009（**类型**拒绝，非键拒绝——标签改写）；新增词表键在策略形状断言 |
| **G10（新）**：route 词表行为 | ①`为什么部署失败`/`何时发布`→deterministic causal/temporal；②`怎么用这个工具`（无锚纯 CJK）→superset；③`why Zephyr 无法登录`→causal；④空数组翻版→`为什么部署失败`回退 superset（回滚语义执法）；⑤词表优先级：`为什么何时`→causal（互斥序） |
| **G11（新）**：script helper 边界 | 五区间 10 个端点码点 ±1 逐个：helper 真/假与区间一致；与 `v13_query_segments(chr)` 分类一致（区间内→非 latin 段；区间外邻点→空段或 latin 段）；`为什么`→true、`abc`→false、`''`→false |
| PREFIX_FREEZE（assembly） | `v13_mgraph.sql` 哈希再重钉（第三次），比较式不宽化 |
| mgraph README 机制 16 | 重写：新检测序、词表键、helper、supersede 记载（R1 撤回的「16 句不改」随本 supersede 失效）；运维纪律补一条：词表维护=策略翻版不是代码 |

### 1.5 不动面

- E1（全零权重→superset 分布）、E4 calls_used=6、E9/D12、shadow、E3 全等、E5-E7、
  D/F/G/H 组全部行为断言（夹具查询无词表命中面）；
- `v13_mgraph_allocate`/`bucket_rels`/`neighbors`/expand——只消费 weights，不改；
- usage gate（不触 mgraph 策略与 route）；`v13/load.py`；12 份 setup_db；
  decisions 索引；`v13_query_segments`。

## 2. 回退

单提交 revert：route 回 v2 判定序、helper 删除、种子回 v2（41 键）、读取器键集回、
gate 回退、哈希回钉。已开的 v3 walk 身份作废（policy_version 回 2 → walk_id 换新），
无数据迁移。词表级回滚不需 revert：翻版空数组即回 superset（G10-④执法的就是这条）。

## 3. 回归

```bash
uv run python v13/mgraph/test_mgraph.py          # A2/E2/G9/G10/G11 + 全组
uv run python v13/mgraph/test_stannum_usage.py   # 共用库，串行
uv run python v13/mgraph_assembly/test_mgraph_assembly.py  # PREFIX_FREEZE + J 族
# 全绿后：characterize/memory/recall/filter/economy/periphery + control/spawn/fanout/triage
```

## 4. 明确不做

- 「谁/哪个」代词锚→entity（OQ 附件可选支）；图内容词法命中（设计 C，调查已否决）；
- routing_mode='jev' 面任何改动；multi_hop/recency 关键词表化；
- 中文锚进函数体（违反不变量 12）；`v13_query_segments` 任何编辑。
