# W6 — observability_budget

## Purpose

为每个 execution step 增加 bounded non-secret metadata，并在 SQL 中执行 token/cost budget gate。model routing 仍归 Python worker。

## Pass gate

1. LLM/SQL/embedding/human-related metadata bounded，无 secret/full prompt。
2. synthetic usage 写出正确 budget row；`run_budget()` 相符。
3. token/cost exceed terminal error，不留下下一条 queue message。
4. active budget + missing usage fail closed。
5. retry attempts 进入 metadata，不重复 logical LLM step。
6. SQL 中无 model/provider routing。
7. README 记录 no pgembed change。

**Evidence (2026-08-28)**

- Command: `uv run python -m v4.observability_budget.test_observability_budget`
- Database: `agent_v4_observability`
- Result: `21/21 passed`
- Failed gate numbers: none
- Secrets in scripted metrics (`api_key`, `prompt`) were stripped by `sanitize_step_metrics()`.

## Fail gate

Secret/full prompt 落库、unknown usage 当 zero、exceed 后仍执行 tool/enqueue、SQL 按 budget 选 provider。均未触发。

## pgembed change

No.

## Database

`agent_v4_observability`

## Status

`passed` (21/21)
