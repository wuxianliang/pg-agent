# 第 12 章：干预面——cancel、human 与 resolve_unknown

> 前置：第 2、5、11 章。产出：`v13_cancel` / `v13_resolve_unknown`（G4/G6 部分）。
> 对照上游：`v8` G8a/G8b（取消收束）与 `v12`（human 平面）的简化裁决。

## 12.1 这一章要做什么

agent 不是脱缰的：人要能取消、要能回答 human effect、要能裁决 unknown。
常规框架把干预做成 API 调用直接改内存状态——v13 里干预是**一行事件 + 一次幂等推进**，
和控制流走完全相同的平面：

| 干预 | 形态 | 机制 |
|---|---|---|
| 取消 | `cancel/requested` 事件 + advance | sticky cancel（粘性停止） |
| 回答 | human effect 的 settle | 队列里排队等人，lease 无限长 |
| 裁决 unknown | `resolve_unknown(effect_id, resolution, evidence)` | 唯一能关 unknown 的入口 |

## 12.2 最小形态

```sql
-- 取消：粘性——一旦请求，任何后续 advance 都收束，不追求立即停
-- advance 开头检查：存在 cancel/requested 事件 →
--   ready/claimed effect → cancelled（claimed 的等 settle 按 stale/cancel 收）
--   session → cancelled + 终结事件

CREATE OR REPLACE FUNCTION v13_resolve_unknown(p_effect uuid,
                                               p_resolution text,   -- confirmed|rolled_back|not_happened
                                               p_evidence jsonb)
RETURNS text LANGUAGE plpgsql AS $$
BEGIN
  -- 唯一允许把 unknown 改为终态的入口；resolution 与证据同事务落事件
  UPDATE effects SET status = CASE p_resolution
      WHEN 'confirmed'    THEN 'succeeded'   -- 外部确实发生了，采信已有结果
      WHEN 'not_happened' THEN 'failed'      -- 证明未发生，可安全重试（上层决定）
      WHEN 'rolled_back'  THEN 'failed'      -- 发生了但已补偿
    END
  WHERE effect_id = p_effect AND status = 'unknown';
  IF NOT FOUND THEN RETURN 'reject'; END IF;
  PERFORM v13_append_event(...'unknown_resolved'...);   -- 审计
  RETURN 'accepted';
END $$;
```

## 12.3 逐段解释

- **粘性取消（sticky cancel，v8 G8a 的极简版）**：不强制杀正在跑的 effect——
  cancel 是个**事实**（事件），advance 看到它就不再派新活、把可收的收掉。
  正在飞的外部调用落完 settle 时自然被 cancel 语境吸收（结果落账但 turn 不继续）。
  v8 的三窗口收束/五出口矩阵被砍成「检查点 + 吸收」，因为单活跃索引
  （第 5 章①）已把竞态面压到最小。
- **human effect 就是慢速 worker**：`kind='human'` 的 effect 领取者是「人」
  ——lease 给足，claim 语义照旧。回答 = settle。**没有为「人」发明第二种机制**；
  审批、确认、低置信弃权（第 4 章 human 兜底带）全部走这一条路。
- **resolve_unknown 是审计点不是技术点**：三种 resolution 对应三种现实
  （确实发生了/证明没发生/发生了但补偿了），必须带证据落事件——
  这是第 11 章 B4 窗口的唯一合法出口。
- **取消与 unknown 的交互**：mutating effect 在 unknown 时收到取消——
  仍必须先 resolve（副作用状态不明不能靠 cancel 掩埋）。
  gate 断言这条顺序不可绕过。

## 12.4 硬性规定与 gate

```text
✓ cancel 后新 effect 不可创建（advance 直接收束）
✓ 取消时已 claimed 的 effect：settle 仍被接受（结果留痕），turn 不继续
✓ unknown 只能被 resolve_unknown 关闭；任何超时/取消路径改写它 → gate 红
✓ resolve 不带 evidence → 拒绝
✓ human effect 从创建到回答跨小时：会话 waiting，无 lease 过期误接管
```

## 12.5 检查点练习

1. 实现 cancel 与 in-flight llm effect 的竞态 gate：cancel 落在 claim 后、
   settle 前，断言「结果事件存在 + turn 终结 + 无新 effect」。
2. 给 resolve_unknown 加 not_happened 后的自动重试选项（新 effect 复用
   逻辑键 → effect_id 相同，attempt 继续），断言外部计数仍 ≤1 时它才被允许。
3. 写 human 平面的超_simple UI：一个 psql 查询（待答 human effects）+
   一个函数调用（settle）。体会「dashboard 就是视图」（第 15 章预告）。

## 12.6 回到 vN 对照

- `v8/cancel/v8_closure.sql`：三窗口收束、五出口矩阵、effect 级取消 code 闭合映射——
  v8 把取消做成了协议；v13 的判断：单活跃索引 + 粘性检查点覆盖 90% 语义，
  竞态矩阵交给 chaos gate 验证而不是矩阵代码。
- `v12/act`：unknown 墙（拒重入、显式解决）的最小断言集，本章直接继承。
