# 第 1 章：日志平面——行是唯一真相

> 前置：第 00 章。产出：`v13/schema/core.sql` 的 `sessions`/`events` 两表 + `v13_append_event()`（G1 验收）。
> 对照上游：`v8/schema/v8_schema.sql`（双 ordinal + append-only 触发器）、`v12/schema`（三平面 DDL）。

## 1.1 这一章要做什么，为什么它是地基

多数 agent 框架的会话是**一个消息数组**：用户消息、模型回复 append 进去，
要上下文时直接读数组。v13 不这么做。它没有消息数组，只有：

1. **一条只追加的事件日志**（`events`）——「发生过什么」的完整事实；
2. **一行控制态**（`sessions`）——「现在怎样」的权威现在；
3. **一个投影函数**（`assemble_context`）——模型看到的对话历史，每次现算。

**日志记事实，控制行记现在，历史是投影。** 这个决定波及下游一切：
崩溃恢复（第 11 章）、fork 与回放（第 14 章）、观察（第 15 章）、RSI 余量，全部从它推导。

常规做法的三个短板，对应 v13 的三个优点：

| 消息数组 | 事件日志 + 投影 |
|---|---|
| 不可回放（压缩后旧消息没了） | 同一份日志可无限次重新投影 |
| UI/持久化/内存三份副本漂移 | 只有一份真相，其余都是视图 |
| 新事实要改核心结构 | 新事实 = 新事件类型（text 列，不闭集） |

核心信念：

> **模型可见 ⟺ 已落行。** 任何进入模型请求的内容，必须能从 `events` 重建。

## 1.2 最小形态

```sql
CREATE TABLE sessions (
  session_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  status      text NOT NULL CHECK (status IN
              ('ready','waiting','blocked_unknown','completed','failed','cancelled')),
  next_seq    bigint NOT NULL DEFAULT 0,      -- seq 分配器（行锁内自增）
  turn_no     int  NOT NULL DEFAULT 0,
  route_policy text NOT NULL,                 -- 决策用的策略名+版本（第 4 章）
  parent_session_id uuid REFERENCES sessions, -- 目标树（第 13 章）
  parent_cutoff_seq bigint,                   -- fork 边界（第 14 章）
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE events (
  session_id  uuid NOT NULL REFERENCES sessions,
  seq         bigint NOT NULL,
  event_id    uuid NOT NULL DEFAULT gen_random_uuid(),
  type        text NOT NULL,                  -- 开放词表：user/message/judge/route/
                                              -- effect_done/human_reward/...（第 13 章）
  turn_no     int,
  payload     jsonb NOT NULL,
  payload_hash text NOT NULL,
  source_effect_id uuid,                      -- 溯源：哪个 effect 产生了它（第 2 章）
  at          timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (session_id, seq),
  UNIQUE (event_id)
);
```

```sql
CREATE OR REPLACE FUNCTION v13_append_event(p_sid uuid, p_event_id uuid,
                                            p_type text, p_payload jsonb)
RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE v_seq bigint;
BEGIN
  UPDATE sessions SET next_seq = next_seq + 1 WHERE session_id = p_sid
    RETURNING next_seq - 1 INTO v_seq;          -- 行锁内分配：天然无洞
  INSERT INTO events(session_id, seq, event_id, type, payload, payload_hash)
  VALUES (p_sid, v_seq, p_event_id, p_type, p_payload,
          encode(digest(p_payload::text, 'sha256'), 'hex'));
  RETURN v_seq;
END $$;
```

## 1.3 逐段解释

- **`next_seq` 在 `sessions` 行上**：分配 seq 就是 UPDATE 控制行。
  行锁 = 会话级互斥 = 同一会话的并发 append 自动串行化，**不需要 advisory lock**。
  「seq 无洞」不是被触发器防守的性质，而是被分配方式保证的性质。
- **`type` 是 text 不是枚举**：这是留给未来的缝（第 13 章）。任何层——
  人工 reward、经验教训、handoff——都能追加自己的事件类型，零 DDL。
  代价是没有 CHECK 防拼写错误；用 gate 断言已知类型拼写正确。

已知事件类型登记（控制面新增，R2 终裁；词表照旧开放——新类型零 DDL，
已知类型由 gate 断言拼写）：

| `type` | 载荷要点 | 产生者 / 去向 |
|---|---|---|
| `repair/required` | 缺陷定位与描述 | harness 结算批的 fold 信号；下一格路由既有 `sql`（库内修复）或 `human`（超限） |
| `replan/required` | 重规划原因 | fold 信号；下一格路由既有 `llm`（重 triage/编排）或 `human`（超限） |
| `goal/override` | `intent ∈ {direct,decompose}` + `schema_version` + `source_principal`（仅 user/operator，模型不得自写）+ 可选 `reason`；同 type 按 seq 取最后一条 | 第 4 章 triage 阶梯的 override 输入；排序低于深度/预算硬安全 |
| `session/completed` / `session/failed` / `session/cancelled` | closeout 对账收据（第 5 章 5.3） | closeout 事务，与终态、预算终态同 commit |
| `forked` | fork/spawn 同一 primitive 的子侧出生事件（fork 边界 + prefix identity，第 14 章） | `v13_fork` / `v13_spawn_subsession` |
| `child-created` | 父侧回执：parent/child/replay_kind/reservation/source tool_call id | spawn 同事务；回执四件套之一 |
| `closeout/inbox_residual` | 终结时未消费输入的对账记录 | closeout 事务（fail-closed 的证据面） |
| `steer/injected` | 注入内容与水位 | 干预路径（第 12 章）；claimed 期间不缝进已冻结 request（第 5 章 G-ctx1 扩） |
| `explore/completed` | 探索证据摘要（证据本体是 evidence artifact，本事件可选） | 同会话 explore（第 13 章） |

同名消歧先钉一条：`sessions.status='waiting'`（会话等外部）与信封
`result_kind=wait`（本格不建下一执行 effect）不是一回事——三层 wait 的
对照表在第 5 章 5.2。
- **`source_effect_id` 可空**：用户消息没有来源 effect；工具结果、LLM 输出、
  判断答案都指向产生它们的 effect——这是第 15 章「观察即视图」的锚点。
- **`payload_hash`**：事件内容指纹。第 14 章回放时比对「重放的输入逐字节一致」。

## 1.4 硬性规定与 gate

不变量（G1 断言）：

1. `events` 只有 INSERT 能进——UPDATE/DELETE 被触发器拒绝（append-only 触发器，
   抄 `v8/schema` 的先例即可，五行的规则触发器）。
2. 同一 session 的 seq 从 0 连续无洞；并发 10 路 append 仍无洞（开两个事务对打）。
3. `event_id` 幂等：同 id 重复 append 不产生第二行（INSERT 冲突即拒绝，不静默吞）。

```text
G1（schema gate）节选断言：
✓ 对 events 的 UPDATE/DELETE 抛错
✓ 并发 append 后 max(seq) = count(*) - 1
✓ 重复 event_id 被拒
✓ 已知事件类型（1.3 登记表）逐 type 精确可查（seed 断言，防开放词表拼写漂移）
✓ goal/override 授权 gate（G1 扩，A20）：source_principal 为 model/handler
  （或任何非 user/operator principal）的 goal/override 事件写入被拒——
  override 只收 user/operator，模型不得自写（1.3 载荷纪律的执法面）
✓ 恰 9 张产品表（第 7 章后验收）
```

## 1.5 检查点练习

1. 给 `events` 加 `turn_no` 自动维护：`v13_append_event` 里从 sessions 行带出。
   断言：turn 边界事件（`turn/start`）之后的所有事件 turn_no 正确。
2. 写视图 `v_context_tail(p_sid, n)`：最近 n 条事件按 seq 正序。
   这是第 5 章 `assemble_context` 的第一块砖。
3. 破坏性实验：注释掉行锁分配，改用 `max(seq)+1`，写一个并发测试让它出洞。
   （体会 v8 为什么把 ordinal 分配器钉在 append 函数里。）

## 1.6 回到 vN 对照

- `v8/schema/v8_schema.sql:135-199`：`session_events` + append-only 触发器 + 双 ordinal。
  v8 用了**两个** ordinal（语义序 + 内部序）服务并行 effect 折叠；v13 单 ordinal 起步，
  并行工具的「完成顺序不改语义」在第 2 章用 op_seq 解决，不在日志层。
- `v12/schema`：三平面里的日志平面就是这两张表的最小形态。
  v13 的增量是 `source_effect_id` 溯源列和 `parent_*` 保留缝。

## 1.7 内在合理性：前因后果

**作用力。** 四条。一：**两个存储无法共享事务**——会话历史一旦同时存在于 UI、
持久化、内存三个副本，任何一条写路径少更新一个副本就静默漂移，没有协议能让
三方原子地一起变。二：**崩溃可发生在任何指令边界**——进程里持有的「对话
历史」在 kill 面前为零，重启后唯一幸存的是已提交的持久行。三：**结构性变更
的成本随事实种类递增**——新事实类型若要求改表结构，每次扩展都是一次迁移
协调；追加一行开放词表的事件是 O(1)。四（PG 性质）：**行锁只在事务内存在，
UPDATE 计数器即互斥**——对控制行的一次 UPDATE 就是免费的会话级串行化器，
提交/回滚自动释放，不需要任何独立于事务的锁原语。

**推导。** 三件套是同时消解四条力的形状：事实放进只追加的 `events`——事实
发生之后不可变，「更正一个事实」本身是一个新事实；「现在怎样」放进单独的
控制行——现在态高频变化，混进日志会让「读当前态」变成对全历史的折叠，语义
含混；模型看到的对话历史不做存储、每次投影——存下来就是第四个副本，回到
漂移力。「seq 无洞」直接从性质四获得：分配 seq 就是 UPDATE `next_seq`，行锁
在事务内天然互斥，并发 append 自动串行——无洞是分配方式保证的性质，不是被
触发器看防的性质。advisory lock 被排除，因为它存活于会话而非事务：崩溃后锁
的释放与序号的回收都要另行处理，等于把事务已经免费提供的保证重造一遍。
「模型可见 ⟺ 已落行」是投影的可检验形式：进入模型请求的内容都能从
`events` 重建，否则行为依赖了无据可查的状态，回放与调试在此断裂。

**反事实：消息数组的三种死法。** 压缩——第 40 轮触发摘要，worker 在 t1 原地
重写消息数组；t2 用户追问早前原话，数组里已不存在；不同时刻的两次压缩产生
两个无法互证的历史，「当时模型看到什么」永久不可知。崩溃——外部生成调用
成功与数组 append 之间被 kill（这个窗口物理上无法关死）：提供方账单里有这次
调用，会话里没有这次回复；没有账本行，连「不可证明」都无处登记。扩展——
新事实（人工反馈）到达，消息数组的角色集合是闭集：要么塞进文本列丢失证据
结构，要么热表迁移。三种死法恰好对应三件套的三个部件，一一抵消。

**被拒替代。** 「消息数组 + 周期快照」：快照滞后留下崩溃窗口，快照与数组是
两个副本，回到漂移力。「当前对话表 + 独立审计表」：两张表无共享事务，分歧
只是被搬家；且「当前」本可从事实推出，冗余状态即第二真相。两案输给同一个
事实：副本数不为一的地方就有对账。
