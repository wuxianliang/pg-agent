# W8 · budget_observability

目标：限制 DuckDB 工作台的资源和返回体，并保留可审计、可脱敏的 operation 记录。

计划默认：自动预览 500（取 501 判断截断）；brief 默认 20、最大 50；query 16,000 字符；timeout 120 秒；memory 512 MiB；result summary 最大 256 KiB。源行数/字节上限由 worker 配置固定。

通过门：超时可 interrupt 并 rollback；内存和结果超限 fail closed；Decimal/时间/UUID/bytes/非有限浮点可安全 JSON 化；DSN、密码和 token 不进入错误或日志。


**状态：✅ Gate 已通过（2026-08-28）。**
