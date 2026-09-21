# v13 M2 · resolve —— 解析相

Gate: `uv run python v13/resolve/test_resolve.py`（退出码 0 = 通过）

库名 `agent_v13_resolve`。加载 `v13_core.sql` + `v13_resolve.sql`。

setup 探针：typesafe_ask ACL（PUBLIC 无 / v13_resolve 有）；坏 endpoint 契约
码写入 `v13_remote_sqlstates`；超时可交付性（57014）。若 HTTP 等待不可被
`statement_timeout` 中断，按 turn 7 #45(b) 回退：failed=true 用 V3001 mock。

## 运维纪律

1. 调用者 parse+advance 成对。
2. 驱动周期调 `v13_requeue_stale`。
3. 哈希只用信封冻结 provider/model；mock/timeout GUC 仅测试。
4. worker 出站携带 `idempotency_key`。
5. 双登录：判断面走 `v13_resolve_login`，建账面走 `v13_route_login`。
6. 调用 advance 前设 lock_timeout/statement_timeout；cap 翻新含全五键。
