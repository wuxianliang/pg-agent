# 第 15 章：版本门、观察与边界——收尾

> 前置：全部。产出：`meta` 版本门 + 观察视图族 + 扩展取舍台账（G1/G7 部分）。
> 对照上游：`v8` 插件世代域/audit 指纹的裁决（砍机器、留种子）。
> 设计对照：`docs/designs/v13-context-on-pg.md` §8（扩展取舍 / 元原则）、§12（YAGNI）。

## 15.1 版本门：meta 一行

v8 为插件热升级建了世代域七条协议（registry/依赖解析/generation digest/发布/
readiness/下线）。v13 的裁决：**单租户自用底座不需要世代，需要的是
「版本不匹配拒绝启动」**：

```sql
CREATE TABLE meta(key text PRIMARY KEY, value jsonb NOT NULL);
-- 迁移版本、worker bundle digest、prompt/策略指针、inline 阈值（第 7 章）
-- worker 启动检查：本地 bundle digest ≠ meta 记录 → 拒绝启动（fail-closed）
```

这就是 v8 世代族被砍后保留的种子。**升级触发器**（00 章清单）出现时再回来。

## 15.2 观察即视图：记账免费

RAGStat 式的分阶段记账（token/cost/时长）不需要新表——
events 自带 at、effects 自带 request/result、decisions 自带 usage 列：

```sql
CREATE VIEW v_turn_cost AS        -- 每 turn 的外部调用量/耗时
SELECT session_id, turn_no,
       count(*) FILTER (WHERE kind='llm')    AS llm_calls,
       count(*) FILTER (WHERE kind='tool')   AS tool_calls,
       count(*) FILTER (WHERE status='unknown') AS unknowns,
       max(at) - min(created_at)             AS span
FROM effects GROUP BY session_id, turn_no;

CREATE VIEW v_session_timeline AS -- 人读的时间线（dashboard 的数据面）
SELECT seq, type, payload, source_effect_id FROM events WHERE session_id = $1
UNION ALL SELECT ... FROM decisions/artifacts ... ORDER BY at;
```

v8 的三族 audit 指纹被砍后保留的种子：**稳定错误码**（error jsonb 里
`Type` 字段约定闭集）+ 原文落账。模型靠稳定码自纠错，人靠原文排障，
dashboard 靠视图渲染——三件事都不需要指纹机器。

## 15.3 扩展取舍台账与元原则三条

扩展进核心不是「好用就装」。**仅当三条全满足**才进——缺一条就停在台账上：

| # | 元原则 | 一句话 |
|---|---|---|
| **(a)** | 替代掉仓库否则要自己写并测试的代码 | 它得消掉一摊我们真会写的扫描 / 校验 / 索引，不是「有了更时髦」 |
| **(b)** | 保住 gate 的确定性与可 mock | 离线必须能绿；没有 `mock_response` 的库内 HTTP 进不来 |
| **(c)** | 不制造第二真相源或第二 IO 通道 | 索引可丢、行不可丢；生成 IO 只有 effect 这一条路 |

| 扩展 | 裁决 | 理由（对三条的用法） |
|---|---|---|
| **pg_jsonschema** | **P1 进** | (a) 替掉 effect args/result、decision answer、manifest 的手写校验；(b) schema 版本化不可变，fixture 可重复；(c) 不新增真相源 |
| **pg_cron** | **P1 进（扫地僧）** | (a) 替掉仓库否则要自己写的扫描恢复 / 投影构建 / verify_index 夜跑；(b) job 是行，测试可 `cron.schedule` 也可直接调同一函数；(c) **不是节拍器**——turn 推进仍靠 settle（第 13 章） |
| **pg_typesafe** | **P1 进（唯一库内 IO 例外）** | 纯判断、幂等、可缓存、可 `mock_response`。(b)(c) 同时成立。**库内 IO 例外有且仅有这一条** |
| **stannum** | **刻画后进 T0** | (a) 替掉自建词项索引；(b) 刻画 gate 先绿（第 10 章）；(c) 索引可丢，基础行不可丢（artifacts 是真相）。runbook：连接池预热、fold 毛刺、REINDEX 演练、AGPL 分发审查 |
| **pg_net / pgsql_http** | **P0 排除** | 第二 IO 通道 = effect 纪律旁路（无 fence / lease / unknown）；无 mock。v1 之死的复活形态。(b)(c) 双红 |
| **timescaledb** | 排除（台账） | 此规模无可替之物；(a) 不成立。触发：events 量级与保留窗口真实出现 |
| **age** | 排除（台账） | lineage / 目标树是递归 CTE 两行的事；第二查询语言的税。(a) 不成立 |
| **vectorchord** | T1 触发（台账） | 固定评估集证明 lexical 漏召才进（第 10 章）；嵌入仍是派生缓存行 |
| **psql_bm25s** | 被替代 | stannum 是其超集（索引化、事务一致）——再装是第二套词项 |

pg_cron 与 pg_net 的对比是元原则的教具：一个把「我们自己会写的扫地」收成行，
一个打开第二条 IO 路。扫地把 (a)(b)(c) 走一遍就进；HTTP 从库内出去，
三条里 (b)(c) 当场红。

## 15.4 YAGNI 台账：没有建的东西与回来的条件

底座边界（v8 已裁，机制可以后建，日志从一开始就是全的）：

| 没建 | 回来的条件 |
|---|---|
| grant/RLS/capability seam | 普通用户可直连数据库 |
| workspace 域 | 多租户/多工作区 |
| 插件世代域 | 第三方插件热升级 |
| 双授权门 + audit 指纹 | 合规审计/不可信插件 |
| canonical 字节合同 | 第二个运行时实现 |
| 八位锁序 | 表数显著增长（现在两级） |
| compact 协议 | 上下文实测断点（第 5 章练习的数据） |
| 事件内树列（parent_entry_id） | 会话内对话分支真需要时（ALTER 零破坏） |
| 第二队列/driver epoch/reconcile | 多 driver 竞争或热切换 |

上下文平面（第 13 章预取排序从这里能看见；完整触发条件以设计文 §12 为准）：

| 没建 | 回来的条件 |
|---|---|
| 预取排序（触点 6） | 长目标树落地 **且** 下一查询可预测；形态：SQL 有界候选、Jev 可选重排、预取仍由 worker 执行 |
| 更聪明的 tick（少扫空转） | 扫描恢复的空转成本实测超标——仍是扫地僧，不改回节拍器 |
| T1 vectorchord | 固定评估集证明 lexical 漏召 |
| CJK bigram 列 | kohaku fixture 漏召率超阈值 |
| 全集 Choice 重排 | 相对序本身成为问题的用例出现 |
| 语义决策缓存 | 判断缓存费用成为账单大头 |
| 工具目录检索 | 目录摘要装不进 decide 上下文那天 |
| boost 反馈环闭环 | 离线 held-out 证明收益 + 词项自查可用 |
| 效用遥测上线驱动策略（触点 4） | 反事实评估（section-removal 配对）证明信号质量 |
| Emergent 表 + 在线 triage | 首个真实 mid-turn producer 出现（triage 永远走确定性 admission） |
| 分片哈希 | 全量哈希下缓存损失实测超标 |
| timescaledb / age | events 规模 / 图遍历需求真实出现 |

每一条的验证方式都是同一个：**新的威胁模型出现时，先写 gate 断言它，
再把机制加回来。** 扩展还要再过 15.3 的三条元原则——台账触发不等于自动进核心。

## 15.5 九条不变量（全教程的收束）

1. PG 行是唯一真相；队列只是唤醒，扫描可恢复（第 3、13 章）
2. events 只追加，同会话 seq 无洞，行锁内分配（第 1 章）
3. 生成 IO 永远不进事务；纯判断 IO 可进解析事务，但必须离开会话锁（第 2、5 章）
4. 命令幂等：(session_id, command_id) 唯一（第 2 章）
5. 副作用有身份：稳定 effect_id + request_hash；settle 带 fence（第 2 章）
6. unknown 一等：不可证明即 unknown，只能显式 resolve（第 2、12 章）
7. 状态转移与事件同短事务；并行结果按预冻结序折叠（第 2、5 章）
8. 预算是版本化策略数据；context 装配走清单，revision 变化必须先过 fresh gate（第 5、10 章）
9. artifacts 不可变，produced_by 指向已结算 effect；chunks 是可重建投影，三纪律（第 7 章）

## 15.6 硬性规定与设计指针

上下文平面的设计权威是 **`docs/designs/v13-context-on-pg.md`**（草案；
§8 扩展取舍、§10 gate、§12 YAGNI、§13 教程映射）。教程是讲解，该文是设计；
两者冲突时以该文为准。实现规范尚未冻结——本章不指向一份还不存在的
冻结稿。

```text
扩展元原则（进核心的三门，缺一不可）：
✓ (a) 替代掉仓库否则要自己写并测试的代码
✓ (b) 保住 gate 的确定性与可 mock
✓ (c) 不制造第二真相源或第二 IO 通道
✓ pg_cron 是扫地僧：关掉它，settle 仍能把一个有界 turn 走完（第 13 章）
✓ pg_net / pgsql_http 不在核心；库内 IO 例外有且仅有 pg_typesafe 纯判断
✓ 台账项（预取排序 / vectorchord / bigram / 分片哈希 / …）在触发条件
  未满足时不得以「先建着」进 schema
```

## 15.7 检查点练习（毕业题）

1. 写 `v_agent_health()`：一个函数回答「系统现在哪里不健康」——
   unknown 存量、超龄 lease、DLQ 深度、扫地延迟。这是运维的入口视图。
2. 72 小时浸泡（第 11 章）跑一次，把三个数（副作用计数/unknown 存量/恢复延迟）
   写进 `docs/reviews/v13-soak-*.md`。
3. 终极练习：给 v13 提一个「需要改核心 schema」的新需求，然后证明它其实不需要
   ——用第 13/14 章的缝。做不到时，把需求写进 15.4 的台账，并用 15.3 的
   (a)(b)(c) 走一遍：哪一条让它现在不能进核心？
4. 拿 `pg_net` 走一遍元原则：指出 (b)(c) 哪条红。再拿 `pg_cron` 走一遍：
   指出它消掉的是哪一段本仓库会自己写的代码。不要装 `pg_net`。

## 15.8 回到 vN 对照（终章）

十二轮实验在本教程的落点：

```text
v1/v2 → 工具即函数、错误信封、只读角色执法      （第 6 章）
v3   → 队列切分、worker 独占 IO、扫描恢复        （第 3 章）
v4/v5→ named tools、SQL 永不调模型 HTTP          （第 2、6 章）
v6   → enqueue-only、op_seq、fail-closed、有界   （第 6、9 章）
v7   → 教训：别建第二真相源、先跑通再冻结证据     （第 10 章）
v8   → effect 四件套 + kill-at-every-boundary    （第 2、11 章）
v9   → freshness 是谓词                          （第 5、10 章）
v12  → 三平面、判断即行、阈值是数据               （第 4 章）
v10/v11 的种子 → 内容寻址 artifact、O(1) fork     （第 7、14 章）
loopx/Dream-RSI → 目标树/quota/reward 的余量      （第 13、14 章）
```

上下文平面这一轮的落点不在新表堆里，在 `docs/designs/v13-context-on-pg.md`：
两阶段 advance（第 5 章）、chunks 三纪律（第 7 章）、召回是函数（第 10 章）、
扫地僧 tick（第 13 章）、ForkPrefix 与三种回放（第 14 章）、本章的扩展台账。

一句话收束（v13 的全部立场）：

> **让表做表的事，让 worker 做 IO 的事，让不变量住在 CHECK 和 UNIQUE 里
> 而不是评审文档里。扩展进核心只走 (a)(b)(c)，设计冲突以
> `docs/designs/v13-context-on-pg.md` 为准。**

## 15.9 内在合理性：前因后果

**作用力。** 崩溃可落在任何指令边界；外部 IO 与事务无原子性；队列
at-least-once。扩展若再开一条 HTTP 路，fence / lease / unknown 全被旁路——
这是 v1 用库内 HTTP 调模型死过的形状。扫描恢复、schema 校验、词项索引
是我们否则要自己写并测试的代码；cron job、jsonschema、stannum 能把它们
收成行。gate 必须离线可绿：没有 mock 的库内调用，确定性从第一天起就没了。
索引是投影，行才是真相——第二引擎当真相源是第 10 章已经拒绝过的双写。

**推导。** 三条元原则是过滤器，不是品味。(a) 挡住「时髦但我们不会自己写」；
(b) 挡住「能跑但不能测」；(c) 挡住「第二真相 / 第二 IO」。pg_cron 过了
因为扫地是我们必写的扫描，job 是行，主路径仍是 settle。pg_net 不过因为
它是第二 IO 通道且不可 mock。vectorchord / age / timescaledb 停在台账，
触发条件没出现时 (a) 不成立。YAGNI 与扩展台账是同一本账的两页：没建的
东西写回来的条件；想用扩展进来，还要再过 (a)(b)(c)。

**反事实。** 装 `pgsql_http` 让 parse 直接 POST：T0，判断调用不再走
`decisions` 行；T1，超时——库内事务还持不持锁？没有 fence，unknown 无处
可放；T2，重试再 POST 一次，钱花两遍，干预面可能还堵着（第 5 章 G-ctx1
要测的那条物理事实被绕开）。再把 timescaledb 提前焊进 events：一套新的
保留/压缩语义压在无洞 seq 上，第 1 章的 append-only 断言要为扩展改写——
(a) 此时仍不成立，账单先到。

**被拒替代。** **「先装着，用不到再关」**——扩展一旦成为第二 IO 或第二
真相源，关比装贵，gate 从第一天起就在测错的系统。**把元原则写成评审 checklist
而不写进本章**——下一次有人提 pg_net 时，没有行能指出 (b)(c) 红。
**发明一份尚未冻结的实现规范来压过设计文**——冲突的裁决权在
`docs/designs/v13-context-on-pg.md`，不在一份还不存在的冻结稿。
