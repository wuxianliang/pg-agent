# W5 — session_durability

## Purpose

显式比较 connection-scoped TEMP 与 durable per-run schema。完成后默认仍是 `temp`。

## Pass gate

1. TEMP-mode view/KV 在 sticky close 后消失。
2. run-schema view/KV 在原连接 close 后仍在，新 worker 可 resume。
3. 其他 run 不能 resolve 第一 run 的 schema。
4. invalid mode 被拒绝。
5. `cleanup_run_session()` 只删目标、terminal check、幂等。
6. B 的 TEMP default 保持。
7. child 继承 session mode 且不共享 schema。
8. README 记录 no pgembed change。

**Evidence (2026-08-28)**

- Command: `uv run python -m v4.session_durability.test_session_durability`
- Database: `agent_v4_session_durability`
- Result: `20/20 passed`
- Failed gate numbers: none
- Schema names are derived as `agent_run_<32 hex>` from server-generated `run_id`; callers cannot pass a schema identifier.

## Fail gate

默认变成 `run_schema`、schema 名可注入、TEMP 在 close 后伪装存在、无边界 CASCADE。均未触发。

## pgembed change

No.

## Database

`agent_v4_session_durability`

## Status

`passed` (20/20)
