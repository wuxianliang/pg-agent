# W4 — subagent_fanout

## Purpose

用 flat PGMQ fan-out 取代 v2 同步 nested spawn。parent 创建 child 后进入 wait；全部 child terminal 后只唤醒 parent 一次。

## Pass gate

1. parent scripted run 创建至少两个 child；SQL 无 nested LLM loop。
2. 两个 worker 能并发处理 child（barrier，不靠 timing luck）。
3. parent 在所有 child terminal 前保持 `WAITING_QUEUE`。
4. child result 按 seq exactly once；child error 作为 parent data。
5. replayed child 不重复 parent wake-up。
6. depth / count / malformed / duplicate name / max-step limits 有 negative tests。
7. README 记录 no pgembed change。

**Evidence (2026-08-28)**

- Command: `uv run python -m v4.subagent_fanout.test_subagent_fanout`
- Database: `agent_v4_subagent_fanout`
- Result: `30/30 passed`
- Failed gate numbers: none

## Fail gate

Parent 在 SQL 内同步等 child、nested WHILE 调 model、duplicate replay 重复唤醒、结果顺序靠 wall-clock。均未触发。

## pgembed change

No — PGMQ groups and ordinary PostgreSQL constraints were sufficient.

## Database

`agent_v4_subagent_fanout`

## Status

`passed` (30/30)
