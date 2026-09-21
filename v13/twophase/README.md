# v13 M4 · twophase —— G-ctx1 + 慢路

Gate: `uv run python v13/twophase/test_twophase.py`（退出码 0 = 通过）

库名 `agent_v13_twophase`。加载 core + resolve + advance + `v13_twophase.sql`
（`v13_requeue_stale` / `v13_renew_lease`）。

生产 `typesafe.mock_response` 不得下发。判断面 `v13_resolve_login`，建账面
`v13_route_login`。

## 运维纪律

1. parse+advance 成对。
2. 周期调 `v13_requeue_stale`（judge 重放 / 其余 kind 转墙；lease 耗竭 settle）。
3. 哈希只用信封冻结 provider/model；mock/timeout GUC 仅测试。
4. worker 出站携带 idempotency_key。
5. 双登录双连接池；SET ROLE 越面被拒。v13_worker 是退化替代。
6. 调用 advance 前设 lock_timeout≈250ms / statement_timeout≈5s。
   effect_attempt_cap 翻新必含全五键，降 cap 需清场。

## 台账

- **`GRANT SELECT ON effects TO v13_route`**：INVOKER 读行所需的矩阵补正
  （Oracle ACCEPT）。
- **#45(b) 回退已激活**：本仓 pg_typesafe HTTP 层不可中断，K1(ii)/K2/K6
  失败源走 V3001 mock。升回条件见 `v13/resolve/README.md`。
