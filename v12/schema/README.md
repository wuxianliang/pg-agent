# v12 G1 · schema —— 三平面基座

Gate: `uv run python v12/schema/test_schema.py`（退出码 0 = 通过）

## 内容

- **日志平面** `sessions` / `events`：append-only（触发器拒绝 UPDATE/DELETE）、
  无洞 seq（`v12_append_event` 在会话行锁内 max+1 分配）、`v12_set_status` 守护
  控制态（status 只有 `idle / awaiting_human / closed`）。
- **决策平面** `jev_batches` / `jev_questions` / `jev_decisions` / `thresholds`：
  问题与答案都是行；instructions/criteria **只允许 ASCII**（DDL 级 CHECK ——
  Jev 英文为主要训练语言，CJK 只允许出现在 state 里）；criteria 形状按题型约束
  （choice=非空对象、score=≥2 级数组、noul=空或对象）；thresholds 满足
  `act_min >= review_min`，fallback 默认 `human`。
- **行动平面** `tools` / `jobs`：目录 + effect 总线；`effect_id` 唯一（稳定逻辑
  身份）；status 闭合于 `queued/claimed/succeeded/failed/unknown/resolved_*`；
  `fence` 单调；lease 到期前完成才被接受。

## 信号语义（冻结，M2 的路由视图消费）

- `choice` / `score` → `answer.confidence`；`noul` → `answer.noul`。
- 裁决：`signal >= act_min → act`；`>= review_min → review`；否则 `fallback`。
- 逐题独立比对阈值；系统**永不**组合一个概率与其补（Jev 不保证跨题恒等式）。
