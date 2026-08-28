# W2 · duckdb_probe

目标：把 DuckDB 运行时事实变成自动化开工门，不凭博客或未来版本设计。

只接受：`duckdb==1.6.0.dev365`、engine `v2.0.0-alpha38615`、macOS arm64、CPython 3.12。

通过门：连接硬化、TEMP VIEW 事务、单语句抽取、DML/COPY-in-CTE 反例、`fetchmany`、`interrupt()`、内存限制均实测；查询连接从未加载 `postgres` 扩展。

失败即停止：版本/平台不符、external access 无法锁死、超时取消不可靠，或 validator 无法识别已知副作用语句。


**状态：✅ Gate 已通过（2026-08-28）。**
