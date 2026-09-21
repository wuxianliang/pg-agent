# v13 M1 · schema —— 核心切片 + 脚手架

Gate: `uv run python v13/schema/test_schema.py`（退出码 0 = 通过）

库名 `agent_v13_schema`。`setup_db.py` DROP-CREATE 后按 `v13/load.py` 前缀加载
`v13_core.sql`。CREATE EVENT TRIGGER / CREATE ROLE 需超级用户；dev 以 pgembed
超级用户连接，生产同前置。

## 内容

- 日志平面 `sessions` / `events`：append-only、无洞 seq、`v13_append_event`
- effect 账本 `effects`：enqueue/claim/complete、单活跃、attempt cap
- 决策平面 `decisions` + `thresholds` + `v13_route_policies`（draft/frozen）
- 工具目录 `tools` + `v13_tools_meta`（revision / candidate_generation_revision）
- 策略行 `v13_policies`（四行 v1 active）+ 三角色 / 双登录

## 运维纪律

1. 调用者 `v13_parse` + `v13_advance` 成对（解析失败审计由变更相落）。
2. 驱动周期调 `v13_requeue_stale`（judge 重放 / 其余 kind 转墙；lease 耗竭
   终态 settle 唤醒）。
3. driver/worker GUC 一致性：哈希只用信封冻结 provider/model；mock/timeout
   GUC 仅测试。
4. worker 出站调用携带 `idempotency_key`。
5. 登录角色：三个 ACL 角色均 NOLOGIN。生产强制双登录——`v13_resolve_login`
   只入 resolve 组 / `v13_route_login` 只入 route 组。跨平面进程双连接池：
   判断面走 resolve_login，建账结算面走 route_login。SET ROLE 越面被 DB
   拒绝。`v13_worker` LOGIN NOINHERIT 双成员是退化替代，无 DB 执法，不推荐。
6. 驱动侧时间护栏：调用 advance 前设 `lock_timeout` / `statement_timeout`
   （建议起点 250ms / 5s）。sql 快路 handler 阻塞的执法点在调用层。
   `effect_attempt_cap` 翻新：新版本必含全五键，降 cap 需清场。
