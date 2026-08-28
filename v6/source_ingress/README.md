# W3 · source_ingress

目标：以 worker 的只读 PostgreSQL 连接，把白名单表完整、有界地快照进当前 run 的 DuckDB 会话。

默认不用 DuckDB `postgres` extension；凭据只存在于 worker 配置，不进入 PGMQ、agent_steps 或工具结果。

通过门：bool/int/float/numeric/text/date/timestamp/timestamptz/uuid/bytea/jsonb/受支持数组的真实类型矩阵通过；未知类型结构化拒绝；超行数/字节/时间失败不留下半成品表；源后续更新不改变已注册快照。

失败即停止：静默字符串化、静默截断、凭据泄露、半成品 artifact 或类型语义无法说明。


**状态：✅ Gate 已通过（2026-08-28）。**
