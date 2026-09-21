# 第 9 章：超级工作台——一个 duck bundle 的三层唯一性

> 前置：第 6、7、8 章。产出：`v13/workbench/`（bundle manifest + worker）（G6/G7 部分）。
> 对照上游：`v6`（DuckDB 工作台完全体）、`v6.1` 调研（ABI 墙、双平面结论）。

## 9.1 这一章要做什么

工具家族里最重的一族是 DuckDB 工作台：代码解析（sitting_duck，AST 即数据）、
文件块操作（duck_block_utils）、数据分析（duck SQL over PG 快照）、
RAG 向量投影（vss/fts）。问题是：**几个工作台？**

答案的三层拆解（本教程最重要的架构判断之一）：

| 层 | 唯一性 | 内容 |
|---|---|---|
| **镜像层（唯一）** | 一个 digest 钉住的 bundle | DuckDB 版本 + 插件全集（sitting_duck/duck_block_utils/vss/fts），登记 `meta`，worker 不匹配拒绝启动 |
| **合同层（唯一）** | 一个 `handler='duck'` | 目录行由 bundle manifest 生成；Jev 照常从目录选工具 |
| **实例层（每任务）** | fresh `:memory:` 实例 | 每个 effect 起新实例（扩展加载毫秒级），输入从 artifacts 水化，输出落 artifacts |

**「一个超级工作台」成立，但唯一性在镜像/合同层，不在进程层。**
字面意义的一个共享 DuckDB 进程会踩四条坑：单写者排队、跨会话状态渗漏
（v6 W4 专门 gate 过隔离）、一崩全崩、常驻服务器要人伺候——
而它唯一买到的东西（热缓存），会话亲和温实例在合同内部就能拿回。

**ABI 墙反而成全这个设计**：DuckDB 一个进程只能装一个精确版本
（v6.1 实测：`duckdb_version` 必须精确相等，`allow_unsigned_extensions` 不绕过）——
bundle 本来就是天然的部署单元。嵌入性买到的正是「实例近乎免费」：
毫秒起停、无服务器协商——**实例廉价到不值得共享**。

## 9.2 最小形态

```text
meta 行：
  workbench.bundle_digest = sha256(duckdb_version + 扩展集清单 + 扩展二进制 digest)
  workbench.tools_manifest = 由 bundle 自报的工具清单（生成 tools 目录行）

worker（duck handler）每次 effect：
  1. 校验本地 bundle digest == meta（否则拒绝启动，fail-closed）
  2. duckdb.connect(':memory:')，按需 LOAD 扩展
  3. 从 artifacts 水化输入（内容即值：parse_ast(code, lang) 吃内容不吃路径）
  4. 校验过的 duck 方言 SQL（v6 W7 validator）执行
  5. 有界结果（行/字节上限）→ settle + 落 artifact
  6. 实例丢弃（温实例：同 session 复用，仅作缓存）

会话亲和温实例（优化，非合同）：
  key = session_id，任何 worker 都能从 artifacts 重建；
  丢失 → DUCK_SESSION_LOST fail-closed（v6 纪律原样），不静默重建空 scratch
```

## 9.3 逐段解释

- **嵌入性的准确位置**：引擎（库+bundle）嵌在 worker **进程**里；
  实例归 **effect**；状态归 **PG**；**agent 层什么都没有**——它只有目录行和 Jev 的选择。
  「每个 agent 一个 duckdb」是错误心智模型；正确的是「实例廉价到按任务丢弃」。
- **为什么不是 pg_duckdb（嵌进 PG backend）**：v6 已明确不选——PG backend 崩溃
  连坐、扩展版本耦合进数据库服务器、绕开 worker 易失性。worker 侧嵌入是刻意选择。
- **四平面一个 bundle**：AST（sitting_duck）/文件块（duck_block_utils）/
  分析（duck SQL over PG 白名单快照——v6 核心：enqueue-only + op_seq + 有界结果）/
  RAG 投影（vss/fts，第 10 章 T2）。全部在 handler='duck' 后面——
  **超级工作台在 v13 里 = 一个 digest + 一个 handler + 一族目录行**，这就是它全部的重量。
- **链条走 artifacts**（第 7 章纪律）：view 链 = 定义 artifact + 结果 artifact，
  不走 sticky 会话状态。温实例丢了从 artifacts 重放——正确性不依赖缓存。
- **文件住在 PG 行**（tigerfs/artifacts）：duck 插件吃内容值，
  文件系统访问不是默认路径（`enable_external_access=false` 可逐字保留，v6 结论）。

## 9.4 硬性规定与 gate

```text
G6/G7 节选断言：
✓ bundle digest 不匹配：worker 拒绝启动（版本门，第 15 章）
✓ 温实例丢失 → DUCK_SESSION_LOST fail-closed → 重放后结果一致
✓ duck SQL 校验：DML/分号/注释被拒（v6 W7 validator 移植）
✓ 结果有界：超行/超字节截断且带标记
✓ 实例隔离：同 session 两个并发只读 effect 结果互不污染
```

## 9.5 检查点练习

1. 写 bundle manifest 的最小形态：JSON 清单（duckdb_version、扩展名+digest、
   工具声明）→ 生成 tools 目录行的 SQL。断言：manifest 换 digest，
   旧 worker 拒领新 effect。
2. 实现温实例缓存（session_id → 连接，TTL 10 分钟），压测有/无缓存的链式
   分析延迟差。把这个数字和第 7 章练习的数字放一起——它们共同决定
   「何时值得开温实例」。
3. 破坏性实验：两个 effect 共享一个实例（故意不隔离），构造状态渗漏用例，
   让 gate 红。（v6 W4 隔离 gate 的复刻。）

## 9.6 回到 vN 对照

- `v6/`：工作台完全体——白名单快照、临时 view 链、有界预览、方言护栏、
  op_seq/order/dup 全套。v13 保留其纪律，把「会话」降级为缓存。
- `v6.1` 调研：ABI 墙证明社区扩展与 fork 不能同载——本章「bundle 是部署单元」
  直接源于此；双平面建议在 v13 里简化为「duck worker 只是又一个 handler」。
