# W7 · dialect_guardrails

目标：允许有用的 DuckDB 只读分析 SQL，同时拒绝已知副作用和外部访问路径，并把真实方言差异写入 v6 prompt recipe。

允许：单条 SELECT、CTE、FROM-first、LIMIT/FETCH、窗口、聚合、QUALIFY、PIVOT 等已验证只读语法。

拒绝：DML、COPY、DDL、ATTACH/CONNECT、INSTALL/LOAD、CALL/PRAGMA/SET，以及 `postgres_*`、文件读取函数。

validator 是“已知副作用阻断 + 外部访问关闭”，不是任意 SQL 的形式化安全证明。
