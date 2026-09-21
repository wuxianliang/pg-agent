# v13 M2 · resolve —— 解析相

Gate: `uv run python v13/resolve/test_resolve.py`（退出码 0 = 通过）

库名 `agent_v13_resolve`。加载 `v13_core.sql` + `v13_resolve.sql`。

setup 探针：typesafe_ask ACL（PUBLIC 无 / v13_resolve 有）；坏 endpoint 契约
码写入 `v13_remote_sqlstates`。

## 台账（冻结）

- **#45(b) 回退已激活**：本仓 pg_typesafe HTTP 层不可被 `statement_timeout` /
  `pg_cancel_backend` 中断，等不到 57014。DP1 永久走 #45(b) V3001 mock 承担
  `failed=true` 断言（K1(ii)/K2/K6/M2-7 超时形态）。升回条件=pg_typesafe 支持
  可中断 HTTP。setup `probe_timeout` 是契约注记，不是绿探针。
- **`GRANT SELECT ON effects TO v13_route`** 是 INVOKER 读行所需的矩阵补正
  （Oracle ACCEPT；定义在 `v13_core.sql`）。

## 运维纪律

1. 调用者 parse+advance 成对。
2. 驱动周期调 `v13_requeue_stale`。
3. 哈希只用信封冻结 provider/model；mock/timeout GUC 仅测试。
4. worker 出站携带 `idempotency_key`。
5. 双登录：判断面走 `v13_resolve_login`，建账面走 `v13_route_login`。
6. 调用 advance 前设 lock_timeout/statement_timeout；cap 翻新含全五键。
