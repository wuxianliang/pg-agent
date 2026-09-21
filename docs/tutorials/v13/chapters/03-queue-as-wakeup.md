# 第 3 章：队列只是唤醒——PGMQ、扫描与恢复

> 前置：第 2 章。产出：`v13/queue/wake.sql`（入队同事务、requeue 扫描）（G2 部分）。
> 对照上游：`v3/pg_agent_pgmq.sql`（全仓库最承重的一刀）、`v12/queue`（G6）。

## 3.1 这一章要做什么

第 2 章的 effect 落账了，谁来执行？答案分两半：

1. **唤醒**：effect 创建的同事务里 `pgmq.send('v13_work', effect_id)`，
   让常驻 worker 立刻被叫醒；
2. **恢复**：消息丢了/堆了都没关系——`v13_requeue_stale()` 从**表**重建积压。

全仓库十二轮实验里最被反复验证的一条裁决：

> **队列只是唤醒，不是事实源。** 消息可丢、可重、可乱序；
> 只要表在，扫描就能恢复一切。

为什么不让队列当事实源？因为它做不到：PGMQ 消息消费后进 archive，
visibility timeout 到期重放的是**旧消息**，跨 worker 的消费竞态需要 read_ct 上限和 DLQ
兜底——所有这些机制在「表 + 效果账本」面前都是冗余的。队列唯一的优点是「快」：
不用轮询。那就只用它这个优点。

## 3.2 最小形态

```sql
-- 入队与落账同一事务：要么都在，要么都不在
CREATE OR REPLACE FUNCTION v13_enqueue_effect(p_effect uuid) RETURNS void
LANGUAGE sql AS $$
  SELECT pgmq.send('v13_work', jsonb_build_object('effect_id', p_effect)::text);
$$;
-- v13_advance（第 5 章）在创建 effect 后同事务调用它

-- 扫描恢复：从表重建积压（driver 周期调用 / worker 启动时调用）
CREATE OR REPLACE FUNCTION v13_requeue_stale(p_limit int DEFAULT 100)
RETURNS int LANGUAGE plpgsql AS $$
DECLARE v_n int := 0;
BEGIN
  PERFORM v13_recover_expired(p_limit);           -- 第 2 章练习：租约过期处理
  INSERT INTO pgmq.v13_work (vt, read_ct, payload)
  SELECT now(), 0, jsonb_build_object('effect_id', effect_id)::text
  FROM effects WHERE status='ready'
  ORDER BY created_at LIMIT p_limit;
  GET DIAGNOSTICS v_n = ROW_COUNT;
  RETURN v_n;
END $$;
```

worker 主循环（库外 Python，也是任何语言的模板）：

```python
while True:
    msgs = pgmq.read("v13_work", vt=30, qty=10)   # visibility timeout 30s
    for m in msgs:
        job = v13_claim(worker_id, my_handlers, lease_ms=60000)  # 只认表！
        if job is None or job["effect_id"] != m.msg["effect_id"]:
            continue                               # 消息过期/已被接管：丢弃
        result = execute_outside_tx(job)           # 全部 IO 在这里
        v13_complete(job["effect_id"], job["attempt_no"],
                    job["fence"], *classify(result))
        pgmq.archive("v13_work", m.msg_id)
```

## 3.3 逐段解释

- **入队同事务**：effect 行和唤醒消息原子出现。若先 send 后落账，
  worker 可能 claim 一个不存在的 effect；反过来则可能落账却无人知晓
  （扫描会救，但延迟一个周期）。同事务消灭这两个窗口。
- **claim 只认表**：`v13_claim` 的 WHERE 是 `effects.status='ready'`，
  消息里那个 effect_id 只是提示。重复投递 → 第二次 claim 拿不到（或拿到别的）→ 丢弃；
  消息丢失 → 扫描补发。**正确性完全住在表里，消息只是提速器。**
- **archive 失败无害**：`v13_complete` 已提交后再 archive 失败，
  消息会在 visibility timeout 后重投——下一轮 claim 拿不到（已 claimed/succeeded），
  丢弃即可。幂等消化了队列的一切毛刺。
- **为什么不用 NOTIFY/LISTEN**：NOTIFY 不持久、断连即丢。可以作**可选**的
  低延迟提示（v8 裁决：NOTIFY 仅 hint），但扫描循环是底线，两者不互斥。

## 3.4 硬性规定与 gate

不变量：

1. effect 创建 + `pgmq.send` 同事务（断言：不存在「有消息无行」/「有行长期无消息且非 ready」）；
2. 删掉整个队列再 `v13_requeue_stale()`，系统继续推进（G6 断言：
   `DROP` 队列 → 重建 → 扫描 → 全部 ready effect 被补发）;
3. 同一消息投递 N 次，外部副作用至多发生一次（第 2 章 fence + 本章 claim 过滤合买）。

```text
G2/G6 节选断言：
✓ 消息丢失注入（archive 前杀 worker）→ 扫描恢复
✓ 重复消息注入 → 外部调用计数 == 1
✓ DLQ：毒消息 read_ct 超限进 dlq，fail 封闭（失败不上抛为崩溃）
```

## 3.5 检查点练习

1. 把 `pgmq.read` 的 `vt` 调到比 lease 短，构造「消息重投但 effect 仍 claimed」——
   断言 worker 丢弃消息且不产生第二次外部调用。
2. 写 `v13_drain_cancelled()`：已 cancel 的 session 名下 ready effect 直接终态化
   `cancelled`（第 12 章取消收束的地基）。
3. 压测：灌 1000 个 ready effect，删队列，量扫描恢复的总时长。
   记录数字——第 15 章观察视图会用到。

## 3.6 回到 vN 对照

- `v3/pg_agent_pgmq.sql` + `v3/worker.py`：2016 天前的第一刀。
  v3 的教训也在：它的 `apply_llm_response` 按内容 hash 幂等，但幂等键住在**消息**里；
  v13 把幂等身份上收到 effect 行，队列进一步退化为纯唤醒。
- `v12/queue/test_queue.py`：`v12_requeue_stale` 从表重建积压的最小验证，
  v13 直接继承；G6 还断言了 inline/queue 两模式 effect_id 逐字节一致。

## 3.7 内在合理性：前因后果

**作用力。** 队列的物理本质：投递需要 broker 与消费者两个独立可故障的系统
协作，「处理完成」与「确认送达」之间必然存在窗口——确认可在处理完成后丢失，
这就是 at-least-once 的来源。持久化、可见性超时、重试策略都只降低可丢、可重、
可乱序的**概率**，没有任何配置能把它们降为零：丢失（broker 在消费前重启）、
重复（确认在消费后丢失）、乱序（并行消费者）是队列的三种常态而非故障。
另一侧：只要每个待办都有一行带可查询状态的表，待办集合永远可以由一次
SELECT 重建——表 + 扫描对消息层的任何形态故障免疫。

**推导。** 「队列只是唤醒」由此得出：正确性必须完全住在表里，队列只保留它
唯一的优势——低延迟（免轮询）。入队与落账同事务，消灭两个窗口：先消息后
行，worker 领取不到；先行后消息，工作空等一个扫描周期。这之所以免费，恰因
消息与表同库，send 就是一次行插入。worker 领取只认表：claim 的 WHERE 是
`status='ready'`，消息里的 effect_id 仅是提示——重复投递，第二次领取被状态
过滤挡住，丢弃；消息丢失，扫描从表补发。settle 提交后 archive 失败也无害：
可见性超时后消息重投，撞上非 ready 的行即被丢弃——幂等消化队列的一切毛刺。

**反事实：队列作事实源的三种死法。** 丢失——10:00 broker 异常重启，09:55
至 10:00 入队的消息消失；若队列是唯一记录，这批工作无人知晓：没有行可扫描、
没有状态可查，会话静默停摆，直到用户（或永远不）发现。重复——消费者处理
完成、确认送达前崩溃，30 秒后消息重投；若执行器把消息当「此事需要做」的
授权，缺少表侧状态过滤，第二次外部调用发生，计费翻倍。乱序——A、B 两个
effect 有完成顺序依赖，两个消费者同时取到；若顺序语义住在消息到达序上，B
先于 A 执行，读到过期状态；表侧的「同域最小未完成变更序」门槛让 B 在 A
结算前根本不可领取。三种故障在表侧各有一行可观测的证据，在消息侧只有沉默。

**被拒替代。** 「队列即真相」：要在消息之上重建正确性，需要消息内幂等键、
消息内序号、死信策略——把表用 CHECK、UNIQUE、状态列声明式拥有的执法，重写
成应用侧约定；且消息无法承载外键与 CAS。「NOTIFY/LISTEN 驱动」：NOTIFY 不
持久、断连即丢，撑不起承重——它至多是扫描循环之上的可选低延迟提示。外部
调度器周期扫表：等于把扫描循环搬进第二个系统，多一个故障域而无新能力；库内
扫描是一条 SQL，不引入任何库外组件。
