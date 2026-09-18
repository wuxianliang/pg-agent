# v12 G2 · decide —— 批次生命周期、幂等缓存与阈值路由

Gate: `uv run python v12/decide/test_decide.py`（退出码 0 = 通过）

## 生命周期

```
open --add_question*--> open --seal--> ready | cached
ready --record_answers(校验, 单事务)--> answered
```

- `v12_request_payload(batch)` = 发给模型的精确对象（state + questions）；
  `request_hash` = 其 jsonb 文本的 sha256。
- **幂等缓存**：seal 时若同 hash 的批次已 answered/cached，直接复制决策
  （`status='cached'`、`cached_from` 指源、latency=0）——Jev 调用是纯函数，
  重放免费且可审计；不同 state 或不同问题集都会 miss。
- **答案校验**（`v12_record_answers` 单事务，任一失败整体回滚）：
  答案必须恰好覆盖全部问题（缺答/多答都拒）；choice 的选项必须在 criteria
  与 probabilities 里；score 必须落在级别区间；noul/confidence ∈ [0,1]；
  数值字段非数字一律拒。
- worker 侧 API 失败可把批次 UPDATE 为 `failed`（外部 IO 不进事务，落库只写结果）。

## 信号与路由（v12_routes 视图）

- 信号：choice/score → `confidence`；noul → `noul`（G1 冻结语义）。
- 裁决：`>= act_min → act`；`>= review_min → review`；否则 `fallback`（默认 human）。
- 逐题独立比对，永不组合互补概率。
