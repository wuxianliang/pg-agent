# W1 · kernel_freeze

目标：证明 v6 可以只读加载 v5 的完整 17 文件基线，而不复制、修改或运行时 import v4/v5。

计划产物：`v6/load.py`、v6-local `worker.py`、setup/test。

通过门：
- v6 前 17 个 SQL 路径与 v5 完全一致并仍指向 v3/v4/v5；
- v5 prompt assembly、可见缺件生成、named tools、generic queue apply 仍工作；
- SQL-side model HTTP guard 仍生效；
- v1–v5 与 pgembed 无 diff。

失败即停止：路径被复制、import v5 runtime、基线测试失败或需要修改旧版本。


**状态：✅ Gate 已通过（2026-08-28）。**
