# W9 · integration

目标：在全新 `agent_v6_integration` 数据库证明核心功能闭环，而不是只证明单个模块能运行。

最终门至少覆盖：可见 prompt 缺件生成、按名工具调用、PG 表注册、DuckDB 命名 view、链式引用、brief/list/columns/show-create/drop、依赖保护、跨 run 隔离、TEMP/工作台隔离、temp loss、run_schema 重放、重复/乱序/重试/DLQ、类型拒绝、超时/内存，以及 v1–v5/pgembed 无修改。

只有所有阶段门与最终门通过，才能把 v6 标记为“核心功能完成”。
