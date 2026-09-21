# v13 M3 · loop —— 变更相五步

Gate: `uv run python v13/loop/test_loop.py`（退出码 0 = 通过）

库名 `agent_v13_loop`。加载 core + resolve + `advance.sql`。

`v13_advance` 持会话锁毫秒级：①终态/未决 → failed/abandon → ② context_fresh
→ ⑤预算 → ③ judge → ④路由。sql 快路 reason=`in_db_handler`。

## 运维纪律

1. parse+advance 成对。
2. 周期调 `v13_requeue_stale`。
3. 哈希只用信封冻结 provider/model。
4. worker 出站携带 idempotency_key。
5. 双登录：判断面 resolve_login，建账面 route_login。
6. 调用 advance 前设 lock_timeout≈250ms / statement_timeout≈5s。
