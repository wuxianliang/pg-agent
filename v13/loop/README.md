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

## 台账

- **`GRANT SELECT ON effects TO v13_route`**：INVOKER 读行所需的矩阵补正
  （Oracle ACCEPT；定义在 `v13_core.sql`）。
- **#45(b) 回退已激活**：见 `v13/resolve/README.md`。
- **P4d（tool_unavailable）** 是单快照信封下的防御性背板；M3-10 的信封内 `enabled=false` 变异是唯一合法构造，plan 原「活表 disable」措辞按 #38 后语义作废。
