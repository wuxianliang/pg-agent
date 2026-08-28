# W5 · queue_bridge

目标：新增 `duck_heavy_requests` / DLQ，并接入现有 generic `apply_queue_result()`。

本阶段必须原子落地：v6 `refresh_plugins()` overlay（合法 kind 加 `duck_heavy`）、queue handler、worker processor、幂等和 DLQ 测试。不能只建 SQL 队列而没有消费者。

通过门：嵌套 defer envelope 正确；generic dispatcher 无 duck 分支；同 msg 重放、同 request 新 msg、op_seq 乱序、读后崩溃、Duck commit 后 PG apply 前崩溃均有确定行为；最终只 resume 一次。


**状态：✅ Gate 已通过（2026-08-28）。**
