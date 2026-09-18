# v12 G3 · act —— effect 纪律（仅真副作用与 LLM 生成）

Gate: `uv run python v12/act/test_act.py`（退出码 0 = 通过）

## 继承自 v8 不变量 5–7 的极简内核

- **稳定身份**：`v12_enqueue_effect` 以 `effect_id` 幂等——
  queued/claimed 去重返回、succeeded/resolved_ok 纯重放、
  failed/resolved_abandoned 复用身份重置为 queued（重试不换身份）。
- **fence CAS**：`v12_claim_job` 每次 claim 递增 fence；
  `v12_complete_job` 要求 (job, fence, claimed, **未过期 lease**) 同时成立。
- **lease 用真实时钟**：lease 的设置与比较都用 `clock_timestamp()`——
  `now()` 在事务内固定为事务开始时间，长事务会让 lease 永不过期
  （G3 开发中实测踩中，已固化）。
- **unknown 是墙**：worker 无法判断外部副作用是否发生时记 `unknown`；
  再入队、再 claim 都被拒，唯一出口是显式 `v12_resolve_unknown`
  （resolved_ok=确认已发生 → 之后 enqueue 纯重放；
  resolved_abandoned=确认未发生 → 允许复用身份重试）。

## 明确不做（相对 v8）

无 driver_epoch、无接管授权操作、无 cohort/共享子操作——单一 jobs 表 +
三个函数即覆盖「本地至多一次 + unknown 不盲目重放」。
