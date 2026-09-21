# 第 2 章：行动账本——effect 四件套与 worker 三步合同

> 前置：第 1 章。产出：`v13/schema/core.sql` 的 `effects`/`commands` + `v13/effect/claim.sql`
> （claim/complete）（G3 验收）。
> 对照上游：`v8/effect/v8_effect.sql`（本仓库最硬的知识资产）、`v12/act`（G3）。

## 2.1 这一章要做什么

agent 的每一步都产生**副作用**：调一次 LLM、跑一次工具、问一次人。
常规做法是直接调用 + 失败重试——三个固有灾难：

1. **重试风暴**：超时后重打 API，副作用可能已发生（双倍扣费、双发邮件）；
2. **崩溃失忆**：进程死在「外部已成功、本地未落账」的窗口，重启后无从得知；
3. **并发踩踏**：两个 worker 领到同一个任务，各执行一次。

v13 的解法是把每个副作用变成**账本上一行**，执行前后都在账上：

```text
claim（领）→ 事务外执行 → settle（结算）        worker 三步合同
    ↑ 递增 attempt_no / fence / lease
```

支撑它的是 **effect 纪律四件套**（v8 最重要的单点贡献）：

| 件 | 列 | 买什么 |
|---|---|---|
| 稳定 id | `effect_id`（SQL 生成的 uuid v5） | 同一逻辑动作永远同一身份，重试不换请求 |
| fence | `fence` 随 claim 递增 | 旧 worker 迟到的结算被 CAS 拒绝 |
| lease | `lease_owner/lease_until`（clock_timestamp） | worker 死了租约过期，别人接管 |
| **unknown** | 状态一等公民 | **无法证明副作用是否发生 → unknown**，永不自动重放 |

第 4 件是灵魂：v8 之前的所有版本都在这里失败——预算耗尽/租约到期就重试，
等于把「可能已发生」的副作用再发生一次。

## 2.2 最小形态

```sql
CREATE TABLE effects (
  effect_id    uuid PRIMARY KEY,               -- uuid v5(命名空间, 逻辑键)，SQL 生成
  session_id   uuid NOT NULL REFERENCES sessions,
  kind         text NOT NULL CHECK (kind IN
               ('judge','tool','llm','context_refresh','human')),
  tool_name    text,                            -- kind=tool 时必填（FK 到第 6 章目录）
  request      jsonb NOT NULL,                  -- 完整出站请求，创建时冻结
  request_hash text NOT NULL,
  idempotency_key text,                         -- provider 侧幂等键（有则传）
  attempt_no   int NOT NULL DEFAULT 0,
  fence        bigint NOT NULL DEFAULT 0,
  lease_owner  text, lease_until timestamptz,
  status       text NOT NULL DEFAULT 'ready' CHECK (status IN
               ('ready','claimed','succeeded','failed',
                'unknown','cancelled')),
  op_seq       int,                             -- 有顺序要求的变更序（第 8 章并行）
  mutation_scope text,                          -- 同域互斥的键
  result       jsonb, error jsonb,
  created_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (session_id, idempotency_key)
);
```

```sql
-- 领取：单事务、SKIP LOCKED、递增 fence、写租约
CREATE OR REPLACE FUNCTION v13_claim(p_worker text, p_handlers text[], p_lease_ms int)
RETURNS jsonb LANGUAGE sql AS $$
  UPDATE effects e SET status='claimed', attempt_no = attempt_no+1,
         fence = fence+1, lease_owner=p_worker,
         lease_until = now() + make_interval(ms=>p_lease_ms)
  WHERE effect_id = (
    SELECT effect_id FROM effects
    WHERE status='ready'
      AND (tool_name IS NULL OR tool_name IN (
           SELECT name FROM tools WHERE handler = ANY(p_handlers)))  -- 第 6 章
      AND (op_seq IS NULL OR op_seq = (                       -- 变更序最小未完成
           SELECT min(op_seq) FROM effects WHERE session_id=e.session_id
             AND mutation_scope=e.mutation_scope AND status<>'succeeded'))
    ORDER BY created_at
    FOR UPDATE SKIP LOCKED LIMIT 1)
  RETURNING jsonb_build_object('effect_id', effect_id, 'attempt_no', attempt_no,
                               'fence', fence, 'request', request);
$$;
```

```sql
-- 结算：先锁 session 后锁 effect（两级锁序），fence CAS
CREATE OR REPLACE FUNCTION v13_complete(p_effect uuid, p_attempt int, p_fence bigint,
                                        p_status text, p_result jsonb)
RETURNS text LANGUAGE plpgsql AS $$
DECLARE v_sid uuid; v_out text;
BEGIN
  SELECT session_id INTO v_sid FROM effects WHERE effect_id=p_effect FOR UPDATE; -- effect 锁
  PERFORM 1 FROM sessions WHERE session_id=v_sid FOR UPDATE;                     -- session 锁
  IF (SELECT attempt_no FROM effects WHERE effect_id=p_effect) <> p_attempt
     OR (SELECT fence FROM effects WHERE effect_id=p_effect) <> p_fence THEN
    RETURN 'stale';                              -- 旧租约迟到：零控制态修改
  END IF;
  IF (SELECT status FROM effects WHERE effect_id=p_effect) = 'succeeded' THEN
    RETURN 'replay';                             -- 已结算同 hash：幂等重放
  END IF;
  UPDATE effects SET status=p_status, result=p_result WHERE effect_id=p_effect;
  PERFORM v13_append_event(v_sid, gen_random_uuid(), 'effect_done',
        jsonb_build_object('effect_id', p_effect, 'status', p_status));
  RETURN 'accepted';
END $$;
```

## 2.3 逐段解释

- **`request` 创建即冻结**：worker 拿到什么就发什么，凭据在进程侧注入——
  数据库在入队前生成完整出站 JSON，worker 无权改请求（v12 `request_payload` 思想）。
- **`fence` 每次领取递增**：claim 是「写_fence」的 CAS。旧 worker 拿着旧 fence
  来结算，`v13_complete` 第一道检查即拒——它不知道自己已被接管。
- **结算四出口**：`accepted / stale / replay / conflict`。
  `replay` 让消息重复投递无害；`stale` 让迟到的旧执行无害；
  `conflict`（同 fence 异结果）在 gate 里构造，出现即人为 bug。
- **事件与结算同事务**：`effect_done` 事件和控制态同 commit——
  这就是「日志与现在永不分家」在行动平面的兑现。
- **锁序一行注释**：session → effect，两级。v8 的八位锁序在 9 张表的世界里
  塌缩成这一行；写进注释就是全部所需（00 章差异表）。
- **worker 三步合同**：claim 事务提交 → **进程内**执行全部 IO → complete。
  worker 申报结果但**不裁决** known/unknown——分类规则是 `v13_complete` 里
  可审计的 SQL，不是 worker 的自由心证。

## 2.4 硬性规定与 gate

不变量（G3 断言）：

1. 事务内无外部 IO——claim 与 complete 之间，数据库连接上没有开着的写事务；
2. 同一 effect 永远至多一次「外部已确认的执行」被账本接受（fence 保证）；
3. `unknown` 只能被显式 `resolve`（第 12 章）关闭，任何超时/预算路径不得改写它；
4. 重复 claim 同一 effect：第二次拿到新 fence，第一次的结算必 stale。

```text
G3（effect gate）节选断言：
✓ 双 worker 对打 claim：恰一个成功
✓ 旧 fence 结算返回 stale 且控制态零变化
✓ 同结果重复结算返回 replay
✓ kill 在 claim 后/complete 前：租约到期可被接管（第 11 章 chaos 展开）
```

## 2.5 检查点练习

1. 给 `v13_complete` 加 `conflict` 出口：同 attempt/fence 但 result hash 不同 → 拒绝并留一条
   `effect_conflict` 事件。断言：控制态不变、事件存在。
2. 写 `v13_recover_expired()`：扫 `status='claimed' AND lease_until < now()`，
   效果不可证明的回 `ready`（可重试的工具）或 `unknown`（mutating 工具）。
   练习点：**为什么这一行代码必须知道工具是否 mutating**？
3. uuid v5 一致性：用 `tools` 目录里的逻辑键（session+turn+tool+args hash）生成
   effect_id，断言同一逻辑键两次推导同 id（第 8 章跨语言一致性的地基）。

## 2.6 回到 vN 对照

- `v8/effect/v8_effect.sql`：四件套的完整形态 + attempt 双表（history 与 control 分离的
  极致版）。v13 的减法：attempt 历史不单列表——每次 claim/settle 都写事件，
  证据链由日志承载，effect 行只存当前态。
- `v12/act/test_act.py`：effect_id 幂等 / fence CAS / unknown 墙的最小断言集，
  v13 的 G3 直接继承它的形状。

## 2.7 内在合理性：前因后果

**作用力。** 三条不可协商的事实。一：**外部 IO 与数据库事务之间无原子性**——
不存在能把「外部已发生」与「本地已落账」一起提交的协议；「外部已发生、本地
未落账」的窗口必然存在，是物理前提而非实现缺陷，设计只能承认并命名它。
二：**超时 ≠ 失败**——超时只说明期限内没有答案，与外部侧已成功、已失败两种
现实都相容，本地观测原理上无法区分。三：**worker 死亡不可观测，且接管发生时
原 worker 可能没死**——租约到期被接管的一方，可能只是停顿了几十秒，它还会
醒来并带着结果回来；两个执行者可以短暂共存。

**推导。** 四件套每件消一条力。**稳定 id**：effect_id 由逻辑键确定性推导——
重试不得改变动作身份，否则同一逻辑动作在提供方侧变成两次调用。**fence**：
每次领取递增的令牌，结算时 CAS 比对——两个执行者不可判真伪时只认最新一代，
迟到结算被拒且控制态零改动。**lease**：死亡不可观测 ⇒ 活性只能用时间定义，
租约把「可能死了」转化为「期限后可收回」。**unknown**：超时 ≠ 失败 ⇒ 结果
空间必须三值；不可证明的状态禁止自动重试——重试等于把「可能已发生」重放
一次，只有显式 resolve 能关闭它。三步合同（claim → 事务外执行 → settle）把
必然存在的窗口圈进两行之间：账本任何时刻都能回答「谁持有、第几代、结算是否
已被接收」。

**反事实一：去掉 fence。** 10:00:00 worker A 领取（租约 60 秒）后陷入 70 秒
GC 停顿；10:01:10 回收扫描判定租约过期，worker B 接管并执行完毕；10:01:30
A 苏醒——它的外部调用其实在 10:00:50 已成功，提供方已计费。无 fence 时 A 的
结算直接改写行：若 B 写 succeeded 而 A 随后写 failed，最后写者获胜，账面呈现
一个干净的失败，双倍执行的证据被抹掉。有 fence 时 A 的结算返回 stale，控制态
分毫不动，异常留在可观测处。

**反事实二：去掉 unknown。** 10:00:30 工具调用超时，外部侧实际已提交（邮件
已发出）；系统把「不知道」当「失败」自动重试，10:02 用户收到第二封。账本
声称知道了自己不可能知道的事，并把不知情兑换成一次副作用重放。

**被拒替代。** 分布式锁服务：锁过期与操作时长的赛跑就是租约问题的原样输入，
只是搬进第二个有状态系统——它与表无共享事务，状态无法用一条 SQL 扫描恢复，
可观测的故障换成不可观测的。两阶段提交：外部提供方不参加你的事务协议，物理
前提缺席。单线程执行：消灭了并发，却把全部吞吐绑在一个进程的活性上，一次
停顿停摆一切；且崩溃仍会落在 claim 与 settle 之间，unknown 一件都不能少——
用容量上限换掉了一个已解的问题。
