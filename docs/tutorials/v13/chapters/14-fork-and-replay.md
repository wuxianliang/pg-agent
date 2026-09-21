# 第 14 章：fork 与回放——RSI 的余量

> 前置：第 1、7、10、13 章。产出：fork-from-prefix 视图 + 前缀身份哈希（G7 探针门）。
> 对照上游：`v11-dev.md`（Dream-RSI 映射的裁决：留种子、砍机器）。
> 设计对照：`docs/designs/v13-context-on-pg.md` §5.2（三种回放）、§5.6（ForkPrefix）。

## 14.1 这一章要做什么

RSI（recursive self-improvement）方向的设计——如 Dream-RSI 的
online → offline dreaming → redeploy 环——需要什么？

v13 的判据一句话：

> **RSI 层必须是「日志的读者 + 新会话的创建者」，永远不需要 ALTER 核心。**
> 任何需要改核心 schema 的 RSI 设计 = 过度设计（v11 的 15 张表就是栽在这里）。

核心已免费提供 dreaming 需要的全部 substrate：

| RSI 依赖 | 核心保证 | 出处 |
|---|---|---|
| 可重放 | append-only 无洞 seq + 入队前载荷冻结（request_hash）+ 内容寻址 artifacts——任何历史前缀可精确重建 | 第 1、2、7 章 |
| O(1) fork | `parent_session_id + parent_cutoff_seq` 两列：新会话上下文 = 父会话 `events ≤ cutoff` 的 UNION 视图——**指针不是拷贝**（v11 从 Dolt 捞出的 REFS-NOT-COPIES 裁决） | 第 1 章 DDL、本章 |
| 树即数据 | search tree（parent/序/payload/score/fail_class）是 RSI 层自建表，父指针指 sessions；frontier 是它身上的递归 CTE | 本章 14.5 |
| W（批上界） | 与 quota 同一条缝：持久策略属性 | 第 13 章 |
| redeploy | thresholds/tools 的 version 列 + meta 版本门 | 第 15 章 |
| 前缀缓存身份 | **ForkPrefix**：system blocks + tool schemas + model + latches 的 canonical bytes SHA-256；validate-spawn 拒破坏身份的 fork；cache probe 对账 | 本章 14.3 |
| 三种回放 | **exact replay / recompute / fresh fork** 不得混称 | 本章 14.4 |

两件不要焊在一起：**会话树 fork**（日志前缀，O(1) 指针）与 **ForkPrefix**
（provider 前缀缓存的身份）。同一 cutoff 的子会话，若 model / 工具 schema /
latch / thinking 预算档变了，日志前缀仍在，缓存身份已经死。

## 14.2 最小形态：会话树 fork

```sql
-- fork = 两列 + 一个视图，O(1)
CREATE OR REPLACE VIEW v_prefix_events AS
SELECT p.parent_session_id AS session_id, e.*
FROM sessions p JOIN events e
  ON e.session_id = p.parent_session_id
 AND e.seq <= p.parent_cutoff_seq        -- 父的前缀
UNION ALL
SELECT session_id, e.* FROM events e;    -- 自己的日志

-- assemble 读这个视图写 context artifact：fork 出的会话天然看见父历史前缀
-- 预算归属：fork 时从父会话继承剩余预算（第 13 章递归聚合的边界条件）
```

dreaming 的形状（全部住在核心之外）：

```text
离线 dream worker（就是第 8 章的一个 handler）：
  读日志 → 选历史前缀 → fork 新会话（两列，O(1)）
  → 声明回放种类（14.4）→ validate-spawn（14.3）
  → 注入变体 prompt/策略版本 → 跑 turn（正常 parse+advance）
  → 打分落自己表 / reward 落事件 → 对比策略版本 → redeploy = 新版本策略行
```

## 14.3 ForkPrefix：前缀身份哈希 / validate-spawn / cache probe

provider 前缀缓存按字节计费：一字节变化，后续前缀全部重算。
fork 继承父的 context artifact，不等于继承父的缓存命中。身份是这一串
canonical bytes 的 SHA-256：

```text
prefix_identity = sha256(canonical(
    system blocks
  + tool schemas
  + model
  + latches            -- INSERT once；UPDATE/DELETE 被拒（第 5 章 latch）
))
```

三件套，缺一不可：

1. **前缀身份哈希**落在子会话行上（或随 fork 事件）。assemble 的
   system / tools / model / latch 段必须能重放出同一串 bytes，否则 hash
   是谎言。
2. **validate-spawn** 在 `v13_fork` 提交前跑。声称要复用父缓存身份
   （exact replay，或任何「带着父 prefix_identity 走」的 spawn）时，
   子会话若把 thinking 预算 clamp 到不同档、换 model、换工具 schema、
   或触发新 latch——gate 拒，不落行。要换身份，必须显式声明 **fresh fork**。
3. **cache probe**：第一次 llm effect 回来后，对比实际 `cache_read`
   与携带的估计（按 prefix_identity 命中应有的字节）。差一截落一条
   审计事件——不是重试，是对账。估计错了翻的是账单归因，不翻正确性。

shadow 演出是同一组零件上的查询：新旧策略双跑 assemble，diff 两份
manifest，零 diff N turn 后 flip。清单是行，不需要第二套 runtime。

## 14.4 三种回放，不得混称

「回放」在日志上只有一种（append-only 前缀可重建）。在 **context /
manifest** 上有三种，混称会把缓存命中、判断复用、语料新鲜度焊成一笔糊涂账：

| 种类 | 策略 | 语料 | 读什么 | 前缀身份 |
|---|---|---|---|---|
| **exact replay** | 当时 | 当时 | 旧 manifest / 旧 context artifact，**不重跑 assemble** | 必须与当时相同；validate-spawn 按父 hash 执法 |
| **recompute** | 旧 | **新** | 旧策略 × 当下 chunks，再 assemble | 策略没变，语料变了：清单 content_hash 会变，前缀身份（system/tools/model/latches）仍可继承 |
| **fresh fork** | **新** | 当下 | 新策略 × 当下语料，新 context | 新 hash；cache miss 是声明，不是事故 |

exact replay 用清单里的旧 verdict，不拿新阈值重释 raw answer
（那是 shadow reroute，§6.1）。recompute 可以复用 per-chunk 判断缓存
（第 10 章 `content_hash` 键），但必须重新装跨度——语料已经不是当时。
fresh fork 两头都新：新策略行、当下投影、新 prefix_identity。

G7 那句「同前缀 fork 两次 → fold_state 逐字节相同」只对 **exact replay**
成立。recompute / fresh fork 若也字节相同，要么语料与策略其实没变
（种类标错），要么 gate 没把三种分开。

## 14.5 逐段解释

- **「前缀-only」是会话树 fork 的语义硬边界**：子会话看得见 `seq ≤ cutoff`
  的父历史，看不见之后发生的——保证日志侧重放确定性（Dream-RSI 的前缀
  硬约束在 v11 的映射）。`parent_cutoff_seq` 记录在子会话行上，一次写入永不改。
- **ForkPrefix 是另一条前缀**：日志前缀管「看见哪些事件」；身份哈希管
  「发给模型的 system/tools/model/latch 字节有没有变」。两条前缀一起绿，
  provider 缓存才有资格命中。
- **为什么事件内树（`events.parent_entry_id`）现在不建**：它服务「会话内对话分支」
  （v11/pi 的树形会话），与 fork（会话间派生）语义不同；append-only 表以后
  ALTER 加可空列零破坏——**余量可以后付的就不预付**。现在付的只有会话树两列，
  因为身份/预算语义会漂。latch 行参与身份哈希，所以它是 P1（保护 prefix
  identity），不是后付余量。
- **评估/reward 对比 = 读两个策略版本的日志**：核心不需要 evaluations 表——
  RSI 层要建就自己建（它的表、它的锁、它的视图），父指针指向 sessions/events。
  核心的义务只是把日志写全、把载荷冻结、把会话树 fork 变成 O(1)、把三种
  回放和前缀身份变成可断言的行——全部已兑现。
- **redeploy 的安全绳**：新策略 = thresholds 新版本行；进行中会话继续旧版本
  （第 4 章），新会话拿新版本——**热切换不需要 quiesce**（v8 的 driver epoch
  被砍后，这里就是它的极简替身）。拿新版本走的那条是 fresh fork，不是
  exact replay。
- **预取会污染身份**（第 13 章思考题的答案）：未声明的预取 section 进
  assemble，payload_ref 变、churn 变，manifest 不再是 exact replay 的那一份；
  若还动了 latch 或工具 schema，prefix_identity 一起变。所以预取停在台账上。

## 14.6 硬性规定与探针门

G7 的形状（注意：这是**探针**不是功能——用最小断言证明余量成立，不实现 RSI）：

```text
G7 节选断言：
✓ fork O(1)：10k 事件的父会话，fork 耗时与事件数无关（两列写入）
✓ 读穿透：子会话 assemble 看到父前缀，cutoff 后的父事件不可见
✓ 预算继承：子会话消耗计入父 goal 配额（第 13 章视图）
✓ 父子并行：两个子会话并发跑 turn 互不干扰（无共享可变状态）
✓ ALTER 探针：对 events 加一列可空 parent_entry_id，全部既有 gate 仍绿
  （证明「后付余量」的承诺是真的）

ForkPrefix：
✓ 前缀身份哈希 = sha256(canonical(system blocks + tool schemas + model + latches))
✓ validate-spawn：破坏缓存身份的 fork 被拒
  （thinking 预算 clamp 到不同档 / 换 model / 换工具 schema / 新 latch
   且未声明 fresh fork → 不落行）
✓ cache probe：第一次 llm 返回后，实际 cache_read 与携带估计对比，
  差一截落审计事件；估计错不改正确性

三种回放：
✓ exact replay / recompute / fresh fork 在 spawn 行上可区分，不得混称
✓ exact replay：读旧 manifest / context，不重跑 assemble；
  同前缀两次 exact replay → fold_state 与 context artifact 逐字节相同
✓ recompute：旧策略 × 当下语料，清单 content_hash 随投影变，
  前缀身份（system/tools/model/latches）可继承
✓ fresh fork：新策略 × 当下语料，新 prefix_identity；cache miss 是声明
```

## 14.7 检查点练习

1. 实现 `v13_fork(p_sid, p_cutoff, p_kind)`：建子会话行 + 继承策略/预算 +
   `forked` 事件 + 写入 `prefix_identity`。断言 O(1)（用 10k 事件父会话计时）。
   `p_kind ∈ {exact_replay, recompute, fresh_fork}`。
2. validate-spawn：同一 cutoff 上把 thinking 预算 clamp 到不同档。
   声明 exact replay → 拒。声明 fresh fork → 过，且新 hash ≠ 父 hash。
   第一次 llm 后跑 cache probe：fresh fork 允许 miss；exact replay 若
   `cache_read` 与估计差一截，必须有审计事件。
3. 做一个最小 dream 演示（纯 SQL + fakes）：同一前缀 fork 三个会话，
   三种 `p_kind`，注入三种 route_policy 版本。断言三种清单可区分
   （exact replay 的 context artifact 与父逐字节相同；recompute 的
   策略版本相同、候选 hash 随语料变；fresh fork 两边都新）。
   ——这就是「策略实验」的雏形，全程没碰核心 schema。
4. 破坏性实验：让 fork 后父会话继续追加事件，断言子会话的日志前缀
   **不变**（会话树语义不被时间穿透）。再改父的 latch——已 fork 的
   子会话身份不跟着漂（latch 按会话冻结）。

## 14.8 回到 vN 对照

- `v11-dev.md`：Dream-RSI 全套映射（两阶段 loop、树即数据、批约束 W、前缀-only）
  及其裁决——采纳思想、拒绝 15 张表。本章是那份裁决的 v13 兑现：
  同样的 substrate 承诺，两列的成本。
- `v8/grant/v8_grant.sql` 的 `v_fork_session`：copy 式 fork 的重型前例
  （拷贝 grant、无 live handle 检查）；v13 用指针视图替代拷贝。
- 第 10 章 G-ctx5 要求清单让三种回放可区分；本章给出三种的语义。
  第 13 章预取停在台账上，是因为它会改清单甚至改 prefix_identity。

## 14.9 内在合理性：前因后果

**作用力。** append-only 无洞 seq 让任何 cutoff 都可重建日志前缀。
行锁只在事务内活着，fork 不能靠「暂停父会话再拷贝」。provider 前缀
缓存按字节计费，一字节变化后续全部重算；latch / model / 工具 schema /
thinking 档都是那一字节的来源。判断有成本且按 `content_hash` 缓存——
语料变了清单该变，策略没变前缀身份可以留。崩溃与外部 IO 无原子性，
所以「声称命中」必须能对账（cache probe），不能靠 provider 口头保证。

**推导。** 日志前缀用两列指针即可（O(1)，REFS-NOT-COPIES）——这是会话树
fork。发给模型的 system 段是另一条前缀，必须有自己的身份哈希，否则
fork 看起来免费、账单按 fresh 走。validate-spawn 把「破坏身份却声称
复用」拒在落行前：thinking 预算被 clamp 到不同档是典型的静默 cache-break。
cache probe 把估计与实际 `cache_read` 落成审计事件，归因是 SQL 不是启发式。
context 侧的「回放」有三种输入组合（策略 × 语料），不拆开就会拿
exact replay 的字节断言去卡 fresh fork，或拿 fresh fork 的 cache miss
去判 exact replay 失败。shadow 只是对两份清单行做 diff，零 diff 再 flip。

**反事实。** 只做会话树 fork、不打 prefix_identity：T0，子会话继承父
context artifact 并换了一个 thinking 档；T1，provider 按字节把后续前缀
全部当 fresh 计费；T2，账本上这仍是一次「fork 命中」——没有行能指出
是哪一字节打碎了身份。三种回放混称：T0'，dream worker 对同一 cutoff
「回放」三次，其中一次换了策略、一次语料已重摄取；T1'，gate 用
fold_state 逐字节相同去断言「回放成功」——两次该红的绿了，一次该绿的
红了，策略实验的对比从第一天起就在比错东西。

**被拒替代。** **拷贝式 fork**（v8 `v_fork_session`）——事件数线性税，
还复制一份会漂的 grant。**应用层在 fork 后改 system prompt 却沿用父
缓存标记**——静默 cache-break，validate-spawn 就是对它的拒绝。
**用新阈值重释旧 raw answer 还叫 exact replay**——那是 shadow reroute，
旧 verdict 在清单里，新阈值只许另跑一份 assemble 再 diff。
**为 RSI 建 15 张核心表**——v11 已裁；RSI 是读者 + 创建者，身份哈希
与三种回放都是行上的标签，不是新平面。
