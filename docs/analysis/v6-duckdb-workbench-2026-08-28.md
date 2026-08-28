# pg-agent v6: DuckDB 2.0 临时分析工作台 — 可行性 / 架构 / 实施难点报告

**Date:** 2026-08-28
**Status:** Investigation report only. No v6 code. No changes to v1–v5 or pgembed.
**Inputs:** Oracle plan `v6-duckdb-workbench-inve-17AC43` + three WIP notes (`_wip-v6-infinisql-functions.md`, `_wip-v6-pg-agent-seam.md`, `_wip-v6-duckdb20.md`, same directory).
**Runtime artifact:** **locked** `duckdb==1.6.0.dev365` in `pg-agent/.venv` (CPython 3.12.13, **macOS arm64 only**, wheel `cp312-cp312-macosx_11_0_arm64`). Engine `SELECT version()` = `v2.0.0-alpha38615` (Cyanoptera, git `16980de6d3`). Probes: `_probe_duckdb160dev365.py` / `_b.py` / `_c.py` / `_d.py` / `_probe_duckdb_postgres_ext.py`.
**Platform/version lock:** v6 只用这一版 Python 包,只做 macOS。不跟 1.5.5,不跟 2.0.0 GA,不做 Linux/Windows 矩阵。

---

## 1. Summary / Recommendation

**中文结论:**

v6 可行,但应该走 **"功能对齐 InfiniSQL,而非语法/架构复制"** 的路线。推荐架构现在按 **已安装的 2.0-dev 引擎实测** 写,不再按 8 月博客清单假设:

- **DuckDB 活在 v6 worker 进程内**,每个 run 一个独立的内存连接(`DuckSession` 按 `run_id` 键控)。
- **Postgres 是唯一事实源**:agent DB(或另一个 Postgres DB)里的表由 worker 以**快照方式**读入 DuckDB;DuckDB 永不持久化批量行数据。
- SQL 侧新增 `wb_duck_*` COMMENT 注册工具,**只做入队**(enqueue-only),真正的执行走新的 PGMQ 队列 `duck_heavy_requests` —— 与 v4 `sql_heavy` 先例同构(独立执行环境、看不到 sticky TEMP)。
- **MVP 用显式 `view_name` 参数 + worker 生成 `CREATE TEMP VIEW ... AS <query>`**。这不是因为 2.0 语法“还没发布”,而是因为在本引擎上尾置 `AS name` **只是表别名、不会建 view**;pipe `|>` 解析失败;`INSTALL pipe` 404。
- **Ingress 默认 Python `CREATE TABLE` + `executemany`**,查询会话**永不** `LOAD postgres`。
- **DuckDB `postgres` 核心扩展**(GitHub `duckdb/postgres_scanner`,SQL 里 `INSTALL postgres`)——**要考虑,但不当默认、不进查询会话、不给模型 SQL。** 已对着 pgembed PostgreSQL 18.4 活库测通。详见 §4.5。
- **不要**装 PostgreSQL 侧的 `pg_duckdb`(在 PG 里跑 DuckDB)——那要改 pgembed,破坏进程边界。
- **会话一打开就锁外部访问:** `autoinstall/autoload_known_extensions=false`,然后 `SET enable_external_access=false`。该设置运行中无法再打开。
- **只用 `duckdb==1.6.0.dev365` / macOS arm64。**
- **pgembed 改动:无。**

**MVP vs 后续 spike 划分:**

| 进入 MVP (W1–W9) | 仅作 spike / 未来 gate |
|---|---|
| worker 内进程 DuckDB,per-run session;打开时锁 `enable_external_access` | grammar-extension / 尾置 `AS view_name` — 本 wheel 上不可用(pipe 404,别名不是物化) |
| Python 侧快照 ingress(`executemany`;查询会话不 LOAD postgres) | 工作台会话里 ATTACH postgres 当 live catalog(已测会看见后续 UPDATE);模型 SQL 里的 `postgres_*` / `ATTACH` |
| 显式 `view_name` + 事务内 `CREATE TEMP VIEW`(ROLLBACK 可丢掉 view) | 每-run DuckDB 文件持久化(明确拒绝) |
| `temp` / `replayable`(Candidate B)两种会话模式 | 显式导出/归档、ET/ML、可视化、`DIRECT_QUERY`、LLM UDF、`CALL quack_serve` — 全部不在范围 |
| `duck_heavy_requests` 队列 + 通用 `apply_queue_result()` | 独立分析进程(本引擎 `interrupt()` 已能打断长查询;仅硬隔离不够时再考虑) |
| validator:`extract_statements` 计语句数/外层类型 **加上** 文本扫描拒绝 CTE 内 DML/COPY | 把 `extract_statements.type == SELECT` 当成只读证明 — **禁止**,已测伪阳性 |

**关键可行性事实(2026-08-28,安装后实测,不是网页推断):**

- DuckDB **2.0.0 仍未正式发布**(release calendar: fall 2026 upcoming;预览页称 v2.0 处于 early stage)。
- PyPI **有** 2.0-dev Python 包:`1.6.0.dev365`(2026-08-20 pre-release)。官方预览安装说明把 `pip install duckdb --pre --upgrade` 标为 Python v2.0-dev。稳定线仍是 **1.5.5**。
- 本机 pg-agent uv 环境已装上该包;引擎自报 `v2.0.0-alpha38615`。v6 **锁定这一版**,不是 2.0.0 GA,也不是 1.5.5。禁止静默换包。
- 平台锁定 **macOS arm64**(已测 wheel)。Linux / Windows / 其他 CPython 不在范围内。
- 实施 v6 时 `pyproject.toml` 应写死 `duckdb==1.6.0.dev365`;本调查仍不改依赖文件。bump 必须重跑探测脚本。

### 1.1 可行性判决(2026-08-28,对照 v5 代码 + 本引擎实测)

**核心功能循环(register → 命名 TEMP VIEW → 链式引用 → 有界预览)在「worker 内 DuckDB + SQL 只入队」这条路上是可行的。** 它不是一篇还没落地的愿望清单:引擎侧已经跑通,调度侧有 `wb_request_sql_heavy` 同构先例。

但报告先前有两处写满了,实施时必须按代码而不是按摘要做:

1. **异步 envelope 不是顶层 JSON。** `invoke_named_llm_tool` 会把工具返回值包成 `{success:true, data:[{<tool_name>: <fn 返回值>}]}`。`apply_llm_response` 读的是 `data[0]` 的唯一键和嵌套对象里的 `defer`。函数本身应像 `wb_request_sql_heavy` 那样返回 `{success, defer, wait_kind, queue, request_id, ...}`,并在 COMMENT 里标 `async:true`。v5 调度可以零改动,**前提是形状抄 sql_heavy,不要自己发明顶层 defer。**
2. **`refresh_plugins()` 的 `queue_kind` 是封闭枚举**(`llm|embed|sql_heavy|human_inbox`,见 `v4/plugin_taxonomy/plugin_taxonomy.sql`)。新队列 `duck_heavy_requests` 不能直接写 `queue_kind: duck_heavy`——`SELECT refresh_plugins()` 会失败。v6 必须用**自己的 overlay 替换 `refresh_plugins()`**(扩枚举),或者 handler COMMENT 复用已有 kind(语义撒谎,不推荐)。这不是改 v4 文件,是 v6 SQL 覆盖同名函数,和 v5 overlay `apply_llm_response` 同类。`apply_queue_result()` 本身仍可保持无 kind 分支。
3. **v5 worker 的 `POLL_QUEUES` 写死了三队列。** v6 不能 import v5,必须有版本本地 worker 把 `duck_heavy_requests` 加进轮询。这是预期工作量,不是阻塞。
4. **`agent_start_run(..., p_session_mode)` 已经存在**(v4 `session_durability.sql`)。不必为模式字段再包一层猜测。
5. **Python 快照的 PG 类型矩阵未测。** `executemany` 只证明了整数/字符串。JSONB/数组/numeric/timestamptz 从 psycopg2 进 DuckDB 仍可能要拒绝。架构可行 ≠ ingress 已绿。
6. **可行性边界:** 单 worker、macOS arm64、`1.6.0.dev365` alpha、查询会话不 LOAD postgres、MVP 可先只做 `temp`(worker 丢了就 `DUCK_SESSION_LOST`)。`replayable`、sidecar 扩展拷贝、多 worker 亲和都不是这条路径的前置条件。

分层:**可以开工做 temp + Python 快照 + 显式 view_name;不能声称整包 W1–W9 已经证明。**

---

## 2. InfiniSQL Functional Mapping(register → named view → chain → bounded preview)

来源:Item 1 笔记(仅以**功能描述**为参考;不复制 InfiniSynapse 的 NestJS/SSE/task-folder/SQLite/delegate-merge 架构)。抓包修正后的功能循环:

```text
register/load a source
  → create a named result view
  → reference that view in a later statement
  → inspect columns / bounded preview (limit+1 probe, databaseReturnLimit=500)
```

映射到 v6:

| InfiniSQL 功能(抓包版) | v6 对应物 |
|---|---|
| `register_table(brief, database_name, table_name)` 独立工具 | `wb_duck_register(brief, source_id, schema_name, table_name, view_name)` — `source_id` 是 worker 配置里的不透明别名,LLM 永远见不到 DSN/凭据 |
| `execute_infinity_sql(brief, view_name, query)` 三参数契约 | `wb_duck_query(brief, view_name, query, replace_view=false)`,`query` 是普通 DuckDB SQL,worker 生成 `CREATE TEMP VIEW "<view_name>" AS <query>` |
| 尾置 `AS <view_name>` 自动追加(物化指令,非投影别名) | **功能等价、语法不同**:MVP 用显式 `view_name`。本引擎上 `SELECT ... FROM t AS named_out` 只是别名、不建 view;pipe 扩展 404。不要把尾置语法当第二执行路径,也不要在本 wheel 上排 grammar spike |
| 后续语句引用先前 temp view(链式) | 同一 `run_id` 的 `DuckSession` 内,后续 `wb_duck_query` 可直接引用既有 artifact;依赖边记录在 Postgres 元数据 |
| `list_tables` / `show_create` | `wb_duck_list` / `wb_duck_columns` |
| `limit+1` 截断探测(`databaseReturnLimit=500`) | 自动预览默认 500 行取 501;`wb_duck_brief_query` 显式预览默认 20、范围 1..50(与 v4 `wb_brief_query` 一致)|
| 四部分错误 `{Type, Phase, Problem, Solution}` | 沿用 pg-agent `WORKBENCH_ERROR` 同构 envelope,新增 `DUCK_*` Type 族 |
| `brief` 必填、CTE 允许、`LIMIT` 允许(抓包修正,推翻旧静态文档的拒绝结论) | v6 validator 同样允许 CTE/`LIMIT`;**本引擎确认 CTE 内 INSERT/UPDATE/DELETE/COPY 可执行**,且 `extract_statements` 在外层是 SELECT 时把 DML-in-CTE / COPY-in-CTE 标成 `SELECT` —— 必须外层类型检查 **加** 文本扫描,不能只看 API type |
| Candidate B 可重放持久化(存定义/血缘,不存批量行) | Postgres 元数据表(`duck_workbench_sessions` / `duck_artifacts` / `duck_operations`),重启时按依赖序重建;重放重读源数据,是**逻辑重放而非历史快照** |
| 明确排除:`DIRECT_QUERY`、ET/ML、可视化、LLM UDF、`SAVE` 任意路径 | 同样全部排除;导出如未来需要必须单独定义受控目的地 |

Dialect 策略沿用 Item 1 的 **Strategy B**:prompt 直接教 DuckDB 方言,不做 Spark→DuckDB 翻译层。进 prompt 的语句以本 alpha 实测为准:FROM-first、`EXCLUDE`/`QUALIFY`/`PIVOT`/`ASOF`、递归 CTE/`USING KEY`、`FETCH FIRST`、VARIANT/JSON 函数可以写;pipe `|>`、尾置 `AS view_name` 物化、`CONNECT 'postgres://...'` **不要**写进 prompt,因为它们在本引擎上不是宣传中的语义。

---

## 3. Feasibility of DuckDB 2.0(实测,不是公告复述)

来源:Item 3 笔记(已用 `duckdb==1.6.0.dev365` 重写) + 本节探测。核心判断:**DuckDB 作为 worker 侧临时分析引擎,在本 alpha 上已经能支撑 InfiniSQL 功能循环的务实等价物;但若干被宣传为 2.0 卖点的语句在本 wheel 上要么缺席,要么语义与博客不同。设计必须跟测量走。**

### 3.1 发布状态 vs 已安装产物

- 2026-08-17:官方博客 "A Preview of DuckDB v2.0"(预告,秋季发布)。Codename **Cyanoptera** —— 与本引擎 `PRAGMA version` 一致。
- 2026-08-20:PEG parser 公告。官方预览安装页把 Python v2.0-dev 标成 `pip install duckdb --pre --upgrade`,并写 v2.0 仍是 early stage。
- Release calendar(2026-08-28):**2.0.0 仍是 upcoming(fall 2026)**。稳定线 1.5.5 / 1.4.5 LTS。
- PyPI simple / project:**存在** pre-release `1.6.0.dev365`(2026-08-20,29 files)。这不是 `2.0.0` 包名。
- **本仓库实测安装:**

```text
uv pip install --prerelease=allow duckdb==1.6.0.dev365
# pg-agent/.venv  CPython 3.12.13
# wheel tag: cp312-cp312-macosx_11_0_arm64
SELECT version()  →  v2.0.0-alpha38615
PRAGMA version    →  v2.0.0-alpha38615 | 16980de6d3 | Cyanoptera
```

### 3.2 2.0 清单:宣传 → 本引擎结果 → v6 设计

| 2.0 特性 | 本引擎测量 | v6 设计 |
|---|---|---|
| PEG / FROM-first / 裸表达式 | `FROM t`、`FROM t SELECT x`、`1+2` 可执行;`extract_statements` 均标 `SELECT` | 允许 FROM-first 作为只读查询;prompt 可教 |
| pipe `|>` + grammar-extension | `ParserException`;`INSTALL pipe` HTTP 404;`allow_parser_override_extension` 只接受 `DEFAULT`/`FALLBACK` | **不可用**。不要做自定义语法 MVP,也不要在本 wheel 上排 grammar spike |
| 尾置 `AS named_out` | 语句成功,**不**创建 view/table;`duckdb_views()` 无此名 | **就是表别名**。InfiniSQL 物化指令必须用显式 `view_name` 参数 |
| `$x` / `SET VARIABLE` | 表达式与 `WHERE` 可用;`SELECT * FROM $rel` 解析失败 | 值绑定可用;标识符仍走 Python 校验拼接 |
| `$1` 与 named `$parameter` | `execute(sql, [2])`、`execute(sql, {"parameter": 7})` 成功 | worker 绑定走这条 API |
| `CONNECT 'postgres://...'` | `LOAD postgres` 之后仍报 `Cannot open file "postgres://..."` | **不是**远程 SoT。不要写进 ingress/prompt |
| `CONNECT ident` / `DISCONNECT` | 内存 `ATTACH` 的库 “does not support CONNECT”;`DISCONNECT`:“already on LOCAL” | CONNECT 是切到 *CONNECT-capable* 已 attach 库,不是打开 URI。MVP 不用 |
| `ATTACH ... (TYPE postgres)` / `postgres_scan` | `INSTALL`/`LOAD postgres` 成功;函数含 `postgres_scan`/`postgres_scan_pushdown`/`postgres_query`/`postgres_execute`;ATTACH 会对 dummy host 做真实 TCP(connection refused) | live-scan 的真实语法是 ATTACH/scan,不是 CONNECT-URI。未对 pgembed 活库验证。`postgres_execute` = 可写 → 永不给模型 |
| `enable_external_access=false` | 挡住 csv/parquet/json/glob/`COPY TO`/`INSTALL`/`LOAD`/`CREATE SECRET`。**不能在运行中再打开**。若先 `LOAD postgres` 再锁:`postgres_scan` **仍能出网**,ATTACH 被拒 | MVP:开连接后立刻关 autoload + 关 external access,**永不 LOAD postgres**。live-scan 必须用另一种 session 构造,不能中途 SET |
| VARIANT + `variant_*` | `::VARIANT`、`variant_type`/`variant_keys`/`variant_contains`、`JSON::VARIANT` 成功 | 分析类型,非架构依赖 |
| statement trigger | 博客 AFTER UPDATE `REFERENCING OLD/NEW TABLE FOR EACH STATEMENT` **成功**(audit 行匹配博客)。SQLite `BEGIN..END` 失败;`BEFORE FOR EACH ROW` not implemented | 工作台 SQL 拒绝 `CREATE TRIGGER` |
| DML-in-CTE | INSERT/UPDATE/DELETE/COPY 在 CTE 内都执行成功 | validator 见 §4.6 / §6 |
| nested schemas / MERGE / `COPY PARTITION BY` | 均可执行(COPY 在 external access 开启时写出 `p=x`/`p=y`) | MERGE/COPY/建 schema 全部拒绝 |
| JSON 2.0 函数 | `json_normalize`/`json_merge_patch_diff`/`json_deep_merge`/`json_strip_nulls`/`json_set`/`json_remove` 成功;`json_insert`/`json_replace` 需要 JSON 类型实参 | 分析方言,非架构依赖 |
| 递归 CTE / `USING KEY` / `FETCH FIRST` / `OVERLAY` / `AT TIME ZONE` / `COLLATE de` / `APPROX NEAREST` | 均成功 | 只读 SELECT 可允许 |
| `SELECT * EXCLUDE` / `QUALIFY` / `PIVOT` / `ASOF JOIN` | 成功 | prompt 可教;`CREATE MACRO` 是会话变异,query 工具拒绝 |
| Quack / DuckDB-as-server | `INSTALL quack` 成功;`CALL quack_serve` 函数存在(token < 4 报错) | 范围外。worker 不启服务器 |
| `CREATE EXTENSION REPOSITORY` | `syntax error at or near "EXTENSION"` | 本 wheel 无 |
| `extract_statements` / `interrupt` / `fetchmany` | 均可用;`range(1e9)` 可被 `interrupt()` 打成 `InterruptException` | 用作语句拆分、超时取消、有界预览 |
| `get_table_names` | 简单 FROM / 逗号 join / FROM-first 可用;`JOIN USING` 本会话 BinderException | 血缘辅助,不是完整 catalog |
| Python `register(list[dict])` | 失败,需要 pandas/arrow/numpy | MVP 快照用 `executemany`,不默认依赖这些 extra |
| `CREATE TEMP VIEW` 事务 | `BEGIN` 内创建,`ROLLBACK` 后 view 消失;`COMMIT` 后保留;`CREATE OR REPLACE TEMP VIEW` 成功;重复 CREATE 报已存在 | 双引擎原子性的 DuckDB 半边可以靠事务;见 §4.6 |

### 3.3 MVP 的务实等价物(由测量锁定)

**显式 `view_name` + 事务内 `CREATE TEMP VIEW` + Python `executemany` 快照** 在本引擎上已经跑通功能循环(register 类物化为表、链式 TEMP VIEW、有界 `fetchmany`)。它不是“等 2.0 语法的临时替代”,而是本 wheel 上**唯一**与 InfiniSQL 命名产物契约相符的路径:

- 尾置 `AS` 不会建 view;
- pipe / grammar-extension 装不上;
- `CONNECT 'postgres://...'` 不是远程库。

worker 在 DuckDB 事务里生成:

```sql
CREATE TEMP VIEW "v_sales" AS
<已校验的单条 SELECT,可为 FROM-first>
```

预览成功则 `COMMIT` 并写 Postgres 元数据;失败则 `ROLLBACK`,不留半成品 view。`replace_view=false` 时让引擎的 “already exists” 变成结构化错误。`replace_view=true` 在实现前还要单独测 `CREATE OR REPLACE` 放进同一事务能否 ROLLBACK 回旧定义 —— 本调查只证明了**新建** TEMP VIEW 可回滚,没有声称 OR REPLACE 的回滚语义。

### 3.4 硬 gate(更新)

- **锁定包:** 只用 `duckdb==1.6.0.dev365`(引擎 `v2.0.0-alpha38615`)。禁止 1.5.5,也不等 2.0.0 再设计。
- **锁定平台:** 只做 macOS arm64 / CPython 3.12(已测 wheel)。不做 Linux/Windows 矩阵。
- **可以按本引擎实现** worker/session/validator/TEMP VIEW 契约。
- 实施时 pin 进 `pyproject.toml`;本调查不改该文件。bump 必须重跑探测脚本。

---

## 4. Architecture

来源:Oracle plan §3 + Item 2 笔记。

### 4.1 总体结构

```text
                Agent database (PostgreSQL 18.4 / pgembed / PGMQ)
                              │
       ┌──────────────────────┼──────────────────────┐
  agent_runs             agent_steps            pgmq queues
  duck_workbench_sessions  duck_artifacts   duck_operations
       │                      │                      │
       └─────────────── v6 worker(版本本地)─────────┘
                         │
              ┌──────────┴──────────┐
        LiteLLM call          DuckSessionManager
        (既有,SQL 外)         per run_id
                                    │
              ┌─────────────────────┼──────────────────┐
        DuckDB :memory:       PostgresSourceResolver  replay metadata
        temp relations        (allowlist source_id→DSN)  in Postgres
```

- **DuckDB 在 v6 worker 进程内**,与 `call_llm()` 并列但独立成件;绝不放进 SQL 函数、不用 PL/sh/pg_net 启动、不放进 Postgres TEMP schema、不跨 run 共享连接。
- 独立分析进程暂不需要:本引擎 `interrupt()` 已能把 `range(1e9)` 打成 `InterruptException`。仅在需要硬杀进程/内存隔离时再考虑。
- `get_or_open(run_id)` 必须按 §4.6 的打开顺序构造连接;不能先跑查询再锁 `enable_external_access`(该设置运行中无法再打开)。

### 4.2 `wb_duck_*`:enqueue-only 的 named tools

`wb_duck_register / wb_duck_query / wb_duck_brief_query / wb_duck_list / wb_duck_columns / wb_duck_drop` 注册为 `llm_tool` COMMENT 绑定(`async:true`,`capability: queue_submit`)。行为只有:校验参数 → 分配 `request_id` 与 per-run `op_seq` → 写 `duck_operations` → `pgmq.send('duck_heavy_requests', ...)` → 返回与 `wb_request_sql_heavy` **同构**的函数结果:

```json
{"success": true, "defer": true, "wait_kind": "duck_heavy",
 "queue": "duck_heavy_requests", "request_id": "<uuid>", "msg_id": 1}
```

`invoke_named_llm_tool` 会再包一层 `{success:true, data:[{"wb_duck_query": <上表>}]}`。`apply_llm_response` 认的是这一层,不是顶层 defer。**v5 文件仍零改动**,但 v6 工具必须抄这个形状,且 COMMENT 必须 `async:true`。同一函数不得同时声明 `llm_tool` 与 `queue_handler`。

`session_scope` 现有合法值只有 `current_session|run_connection`。DuckDB 实际在 worker 进程。MVP 用 `run_connection` 表示「这个 run 的工作台会话」(引擎是 DuckSession 不是 `pg_my_temp_schema`),不要发明未 overlay 的新枚举,除非同时 overlay `refresh_plugins()`。

### 4.3 `duck_heavy_requests` 队列

新队列 + DLQ + 一个 `apply_duck_heavy_result(p_run_id text, p_result jsonb)` 走 `_resume_from_queue_result`(可在 v6 overlay 里扩 wait_kind 标签,或直接调用现有函数)。不复用 `sql_heavy_requests` 队列。

**taxonomy:** `refresh_plugins()` 拒绝未知 `queue_kind`。v6 overlay 必须把 `'duck_heavy'` 加进 `v_legal_kind`,否则 COMMENT 注册失败。不要改 v4 文件。

v6 worker(版本本地,不 import v5)把 `duck_heavy_requests` 加入 `POLL_QUEUES`。处理流:解码 → `get_or_open(run_id)` → per-run 锁 → 必要时 hydrate → 幂等/顺序校验 → 执行 → 有界预览 → `apply_queue_result('duck_heavy_requests', msg_id, run_id, result)`(该函数仍无 kind 分支)→ 归档。幂等两层:`(queue_name, msg_id)` + `request_id` / `(run_id, op_seq)`。

### 4.4 Postgres as Source of Truth + Candidate B 可重放元数据

元数据表(在 v6 agent DB,**不是 SQLite、不是 DuckDB**),只存定义/状态/血缘/有界元数据,**永不存批量源行**:

- `duck_workbench_sessions`:`run_id` PK、`session_mode`(`temp`/`replayable`)、`status`、`next_op_seq`、`worker_id`、时间戳。
- `duck_artifacts`:`(run_id, artifact_name)` 唯一;`artifact_kind` ∈ `source|view`;`source_id/schema/table`、`ingest_mode`(MVP 仅 `snapshot`)、`source_sql` 定义、`depends_on` 血缘、`columns`、`definition_hash`、`generation`(显式替换 +1)。
- `duck_operations`:append-only 审计;`request_id` 唯一、`(run_id, op_seq)` 唯一;状态 `queued|running|succeeded|failed|replayed`;`result_summary` 只含有界预览;失败请求不得改动 artifact 元数据。

**会话模式从 v4 继承,不新建第二套:**

| v4 模式 | v6 DuckDB 映射 |
|---|---|
| `temp`(默认,连接级)| worker 进程内的内存连接;worker 丢失 → 后续操作返回 `DUCK_SESSION_LOST`(不静默给空会话),模型可重建 |
| durable per-run schema | 仍是内存 DuckDB,由 Postgres 中的定义按依赖序**重放重建**;重读源数据,标注为 rehydrated 而非历史快照 |
| 子 run 继承模式 | 子 run 同模式、全新 DuckDB 连接、独立 `(run_id, artifact_name)` 命名空间;**不自动见父 artifact,无 delegate merge** |

MVP **不做** per-run DuckDB 文件(那会引入第二个持久层、文件锁与 SoT 歧义)。

### 4.5 Ingress:MVP = Python 侧有界快照(API 已测)

**默认路径(本引擎已执行成功):**

```text
CREATE TABLE <quoted ident>(...)
executemany("INSERT INTO ... VALUES (?, ?)", batches)
```

`con.register(name, list[dict])` 在本环境失败(要求 pandas / pyarrow / numpy)。MVP **不**把这些 extra 当隐式依赖。Arrow 路径只有在额外 pin 并测过类型保真后才能作为优化,不能当默认。

步骤:

1. `source_id` → worker 配置/secret provider 解析(凭据永不进 SQL payload、`agent_steps`、PGMQ、工具结果);
2. 只读源事务,标识符经 client 的 identifier composition,不依赖 `search_path`;
3. 批量读取,成功后一次性提交 DuckDB 关系(**成功才物化**,失败不留半成品,也绝不静默截断后报成功);
4. 元数据只记源身份/schema/ingest_mode/列/定义 hash。

语义:注册时刻快照;源后续变更需显式重新注册;replayable 重放会读到新数据。预算:源行数/字节/时长、每 run artifact 数、`SET memory_limit`(本机默认曾是 12.7 GiB,必须显式下调)。类型保真按类型族显式测试(numeric 精度、timestamptz 时区、UUID、JSON/JSONB、数组、bytea、domain/range/composite、扩展类型——不达标即结构化拒绝,**禁止静默字符串化**)。G4 仍开放:Python `executemany` 路径还没有用 pgembed 真表跑完整类型矩阵(扩展路径的部分类型见下)。

### 4.5.1 要不要 DuckDB `postgres` 插件 — 结论

先分清三个名字,不要混:

| 名字 | 是什么 | v6 |
|---|---|---|
| DuckDB 核心扩展 `postgres` / `postgres_scanner`(仓库 `duckdb/postgres_scanner`,常被叫 duckdb-postgres) | 在 **DuckDB 进程内** `INSTALL postgres; LOAD postgres; ATTACH ... (TYPE postgres)` | **要考虑**,但是 worker 内部拷贝通道,不是工作台 catalog |
| 第三方 pip `duckdb-extension-postgres` | 同一扩展的离线包装 | **不必**。本 wheel 已能 `INSTALL postgres` |
| PostgreSQL 扩展 `pg_duckdb` | 在 **Postgres 里**跑 DuckDB | **否决**。要改 pgembed / `shared_preload_libraries`,破坏「DuckDB 只活在 worker」|

对着 **pgembed PostgreSQL 18.4**(unix socket) + `1.6.0.dev365` 的活库事实(`_probe_duckdb_postgres_ext.py`):

| 行为 | 结果 |
|---|---|
| `ATTACH conn AS pg (TYPE postgres, READ_ONLY)` | 成功;`SHOW TABLES FROM pg` 看到 `probe_src` |
| `SELECT` 附加表 | 成功。`NUMERIC(10,2)` → DuckDB `DECIMAL(10,2)`;`TEXT[]` → `VARCHAR[]`;`TIMESTAMPTZ` → `TIMESTAMP WITH TIME ZONE`;**`JSONB` → `VARCHAR`**(不是 JSON/VARIANT) |
| `EXPLAIN ... WHERE amount > 2` | 物理计划是 `Postgres Scan` 且带 `Filters: amount > 2.00`(filter pushdown 真的发生) |
| `CREATE TABLE snap AS SELECT * FROM pg.public.probe_src` | 成功,是注册时刻拷贝 |
| 随后在 PG 里 `UPDATE` | **附加表看到新值**;`snap` 仍是旧值。live ≠ snapshot |
| `INSERT` 进 READ_ONLY 附加库 | 拒绝:`attached in read-only mode` |
| `postgres_execute` 在 READ_ONLY 上 INSERT | 失败:`cannot execute INSERT in a read-only transaction`;PG 中无新行 |
| `postgres_scan` / `postgres_query` | 都能读到活数据 |
| `DETACH` 后 `snap` | 仍在 |
| 然后 `SET enable_external_access=false` | `snap` 仍可查;`ATTACH` 被拒 |
| **同一连接上 `postgres_scan` 在 DETACH+lock 之后** | **仍然成功出网**。没有可用的 `UNLOAD postgres`(语法错误) |
| 另一连接:先 lock 再 `LOAD postgres` | 被拒 |
| sidecar:LOAD → ATTACH → `CREATE TABLE local` → DETACH → lock → `CREATE TEMP VIEW` | 成功 |

**设计决定:**

1. **MVP 不用这个扩展。** 查询会话打开即锁外部访问,永不 `LOAD postgres`。快照走已有 psycopg + `executemany`。这样 `postgres_scan` 根本不存在于该连接。
2. **要考虑它,但只作为可选的 worker 内部拷贝引擎**,且必须用**另一条一次性 DuckDB 连接**:拷完把行(或已物化的本地表内容)交给查询会话之后丢掉 ingress 连接。不要把 `pg` 附加库留在工作台 session 里。
3. **不要做 live-scan 默认路径。** 附加表会看见并发 UPDATE,和 InfiniSQL「register 时刻快照」不是同一契约。
4. **模型 SQL 一律拒绝** `ATTACH`/`DETACH`/`CONNECT`/`INSTALL`/`LOAD`/`postgres_scan`/`postgres_scan_pushdown`/`postgres_query`/`postgres_execute`。`READ_ONLY` 挡得住普通 INSERT 和 `postgres_execute` 写,但挡不住模型用 scan 把凭据/任意表读出去——所以拒绝必须在 validator,不能靠 ATTACH 选项。
5. **JSONB→VARCHAR** 说明扩展的类型映射不能当 SoT。若日后用扩展做拷贝,必须在 `CREATE TABLE AS` 时显式 CAST,不达标就结构化失败。
6. **`pg_duckdb` 不考虑。** pgembed 不改。

**Live-scan / CONNECT 对照:**

| 候选 | 本引擎事实 | 设计 |
|---|---|---|
| `CONNECT 'postgres://...'` | 当文件路径打开 | **删除** |
| `ATTACH ... (TYPE postgres, READ_ONLY)` | 活库成功;filter pushdown 成功;看见后续 UPDATE | 只允许 worker sidecar 拷贝,不进查询会话 |
| `postgres_scan` 在已 LOAD 的连接上 | lock 之后仍能扫 | 查询会话禁止 LOAD;validator 仍拒绝该函数名 |
| `postgres_execute` + READ_ONLY | 写失败 | 仍永不暴露 |

### 4.6 工具语义要点(按 API 能力写)

**`DuckSession` 打开顺序(测过,且 `enable_external_access` 不能再打开):**

```text
con = duckdb.connect()                 # :memory:
SET autoinstall_known_extensions=false
SET autoload_known_extensions=false    # 默认均为 true,会自己上网装扩展
SET enable_external_access=false
SET memory_limit='<budget>'
-- 不要 INSTALL/LOAD postgres,不要 INSTALL quack,不要 CALL quack_serve
```

**`wb_duck_query` 执行顺序:**

1. `stmts = con.extract_statements(query)`;必须恰好 1 条。
2. 外层 `stmts[0].type` 必须是 `SELECT`(FROM-first / 裸 SELECT 也是这个 type)。
3. **再**对语句文本做字面量/注释外的扫描,拒绝:`INSERT` `UPDATE` `DELETE` `MERGE` `COPY` `ATTACH` `CONNECT` `DISCONNECT` `INSTALL` `LOAD` `CREATE` `CALL` `SET` `USE` `PIVOT`(语句级) `MACRO` `TRIGGER` `SECRET`。依据:DML-in-CTE 与 COPY-in-CTE 的 `extract_statements.type` 仍是 `SELECT`。
4. `BEGIN`
5. `CREATE TEMP VIEW "<view_name>" AS <query>`(标识符由 Python 校验后引用,不用 `$var`)
6. `SELECT * FROM "<view_name>" LIMIT n+1`,用 `fetchmany` 取有界预览
7. 成功 `COMMIT` 并写 Postgres 元数据;失败 `ROLLBACK`(本引擎上新建 TEMP VIEW 回滚后 `duckdb_views()` 不再有该名)

其它:

- 默认拒绝重名(引擎报 `View with name ... already exists`)。`replace_view=true` 在实现前必须单测事务内 `CREATE OR REPLACE` 的回滚是否恢复旧定义;未测之前不要假设。
- `drop`:规范化名、run 内解析、有依赖即拒绝、无 CASCADE。
- 血缘:`get_table_names` 对简单 FROM/逗号 join 可用,对 `JOIN USING` 本会话失败。把它当辅助;主路径仍是对已知 artifact 名的保守扫描(排除字符串与注释;假阳性只会让 drop/replace 更严)。
- 预览:双层 limit(自动 500 / brief 1..50 默认 20),均 `limit+1`;`interrupt()` 作为超时取消(已测能打断 `range(1e9)`)。
- 注释(`--`、`/* */`)引擎允许;`extract_statements` 能正确切分字符串里的分号。允许注释,仍拒绝多语句。这与 v4 Postgres validator 拒注释不同,按 DuckDB 实测放宽。
- 全量结果只存在于临时 DuckDB 关系,run history 只收有界预览+列+计数。MVP 不加 task-folder 归档/JSONL/SQLite 结果存储/自动导出。

---

## 5. How This Attaches to v5

来源:Item 2 笔记 + Oracle plan §2/§3.12。

- **Named tools**:走 v5 `invoke_named_llm_tool()` 既有异步路径,`plugin_bindings` COMMENT 元数据不变,**v5 文件零改动**。
- **sql_heavy 隔离先例**:v4 已证明独立执行环境(哪怕同在 Postgres)看不到 sticky TEMP;DuckDB 是更强的隔离边界。规则必须保留:`Postgres sticky TEMP VIEW/KV ≠ worker DuckDB session`,两边互不可见,亦不尝试打通。
- **session_durability**:`agent_start_run(..., p_session_mode text DEFAULT 'temp')` 已存在,合法值 `temp|run_schema`。v6 映射 `temp`→内存 DuckDB、`run_schema`→replayable(仍是内存 DuckDB + PG 定义重放)。子 run 继承模式、不共享 DuckSession。MVP 可只实现 `temp`。
- **load.py**:v6 `load.py` 按 v5 模式,17 个 v3/v4/v5 文件**按路径直读**、只读加载,后接 v6 文件;每个 COMMENT plugin 文件后 `SELECT refresh_plugins()`;`STAGE_THROUGH` 每 stage 一个独立数据库;`ON_ERROR_STOP` 失败即停。
- **五过程不变量全保**:每 stage 独立 DB;失败停序;v1–v5 只读;COMMENT 后必 refresh;SQL 永不发模型 HTTP;worker 版本本地、**运行时不 import v5/v4**;`apply_queue_result()` 保持通用无分支。
- **不在 SQL 侧的东西**:DuckDB 执行/连接管理/会话状态、源凭据、LLM HTTP、批量数据存储、DuckDB 内存/超时配置、parser/AST 操作——全部 worker-only。
- **回滚边界**:v6 用独立 `agent_v6_*` 数据库;回滚=停 v6 worker、起 v5 worker 对 v5 库;v5 不需要理解 `duck_heavy_requests`。活跃 v6 run 不能透明交给 v5 worker,这是显式的版本边界。

---

## 6. Implementation Difficulties and Open Gates

### 6.1 难点(若干已从未知变成已测约束)

1. **跨双引擎原子性**:DuckDB 变更与 Postgres 元数据提交仍是两个运行时。本引擎上 **新建 `CREATE TEMP VIEW` 可放进 `BEGIN`/`ROLLBACK`**(回滚后 view 消失)。因此失败查询可以不留新 view。`replace_view` 若走 `CREATE OR REPLACE`,回滚是否恢复旧定义**尚未测**——未测之前替换应关掉,或用“候选 view → 成功再改名”而不是 OR REPLACE。Postgres 元数据仍在 DuckDB `COMMIT` 之后提交;若元数据失败,worker 必须再丢 DuckDB view 或把会话标脏。`request_id` / `op_seq` / 通用队列重放仍然需要。
2. **DML-in-CTE 与 COPY-in-CTE**:已确认可执行。`extract_statements` 在外层 SELECT 时把它们标成 `SELECT`;外层 INSERT 时标成 `INSERT`。**不能**用 `type == SELECT` 或 “以 WITH 开头”当只读证明。必须外层类型 + 文本扫描。也**不能**靠执行后回滚当安全边界(COPY-in-CTE 在扫描漏过时会写文件系统;若 session 已锁 `enable_external_access` 则 COPY 会 PermissionException,这是第二层,不是第一层)。
3. **Validator 不是沙箱,但本引擎有真实旋钮:** 默认 `autoinstall/autoload_known_extensions=true` 会自己上网。MVP 必须关掉它们再关 `enable_external_access`。这挡住 csv/parquet/json/glob/COPY/INSTALL/LOAD。它**挡不住**已经 LOAD 的 `postgres_scan` 出网。所以 MVP session 根本不 LOAD postgres,模型 SQL 仍拒绝这些名字。
4. **temp 模式的 worker 亲和**:TEMP DuckDB 会话只在同一 worker 进程持有该 run 时安全。多 worker 部署要么 run-affine 路由,要么强制 `replayable`;不能假装 PGMQ group 元数据自带内存亲和。
5. **乱序/重复**:per-run 行锁分配 `op_seq`,worker 要求严格递增;前驱未到不执行、不推进 `next_op_seq`。正常异步流不会乱序,但队列重放/worker 故障必须测。
6. **类型保真与源漂移**:timestamptz、numeric 精度、数组/JSON、扩展类型、注册后源 schema 变更——都要显式映射或诊断,重放结果必须标注为"按当前源数据重建"。Python `executemany` 已证明能进整数/字符串。扩展路径已测:`JSONB` 变成 `VARCHAR`,`NUMERIC` 变成 `DECIMAL(10,2)`——若走扩展拷贝必须显式 CAST,不能当默认可接受映射。
7. **凭据卫生**:DSN/密码绝不能出现在 LLM 可见参数、队列 payload、错误 `Problem`、指标里;engine 报错要限长并脱敏。尤其不要把失败的 `postgres_scan` 连接串原文回传(本探测的 IOException 含 host/port)。
8. **血缘的准确性:** `get_table_names` 不是完整依赖 API(`JOIN USING` 失败)。保守扫描的假阳性会过度限制 drop/replace——可接受但要在文档里说明。
9. **超时:** `con.interrupt()` 已能把长查询打成 `InterruptException`。独立分析进程不再是取消的前置条件。

### 6.2 Open gates(实现前必须关闭)

| Gate | 内容 | 本调查后 |
|---|---|---|
| G1 接口冻结 | v5 SQL 17 个文件已核对;`apply_queue_result(queue, msg_id, run_id, result)`;defer 包在 `data[0][tool]`;`agent_start_run` 已有 `session_mode`。剩余:v6 overlay `refresh_plugins` 扩 `queue_kind` | **大部分关闭。** 枚举 overlay 是实施第一件 SQL 事 |
| G2 发布/wheel | 锁定 `duckdb==1.6.0.dev365` + macOS arm64 | **关闭。** 已安装运行。不做 Linux/其他版本。实施时 pin 进 pyproject |
| G3 核心运行时 | 独立连接、TEMP VIEW、事务、参数绑定、内存限制、中断、`limit+1`、DML-in-CTE 检测 | **对本包已测子集关闭**(见 §3.2) |
| G4 快照 ingress | 对 pgembed PG 18.4,Python `executemany` 有界 fetch/load 与类型映射 | **开放。** 孤立 `executemany` 成功;完整 PG 类型矩阵未跑 |
| G5 Postgres 扩展 | 已活库测通。决策见 §4.5.1:查询会话不 LOAD;sidecar 拷贝可选;禁止 live catalog / `pg_duckdb` | **决策关闭,实现可选。** `CONNECT 'postgres://...'` 除名 |
| G6 Grammar(spike)| 尾置 `AS view_name` | **本 wheel 失败关闭:** 别名不是物化;pipe 404;parser override 只有 DEFAULT/FALLBACK。等有可加载的 extension 再开 |
| G7 MVP 契约 | 显式 `view_name` + 生成 `CREATE TEMP VIEW` | **可以按本引擎开工**(仍是调查:本报告不写 v6 代码) |
| 依赖声明 | `duckdb==1.6.0.dev365` | **设计已锁。** 实施时写入 pyproject;禁止其他版本 |

---

## 7. Suggested v6 Stage Order(未来实施索引 — 现在不做)

来自 Oracle plan §3.12/§6。**以下仅为将来实施时的顺序索引,本次调查不产生任何代码。**

| Stage | Database | 职责 | 依赖 gate |
|---|---|---|---|
| W1 `kernel_freeze` | `agent_v6_kernel_freeze` | 17 个 v5 文件按路径直读,证明 v5 基线无需改动即绿 | G1 |
| W2 `duckdb_probe` | `agent_v6_duckdb_probe` | 固化门:包必须是 `1.6.0.dev365` / 引擎 `v2.0.0-alpha38615`、TEMP VIEW 事务、`extract_statements`+DML-in-CTE 伪阳性、查询会话不 LOAD postgres、`interrupt` | G2, G3 |
| W3 `source_ingress` | `agent_v6_source_ingress` | 源元数据 + 有界快照摄取 + 类型映射 | G4 |
| W4 `session_durability` | `agent_v6_session_durability` | `temp`/`replayable` 映射、hydrate、清理、跨 run 隔离 | W3 |
| W5 `queue_bridge` | `agent_v6_queue_bridge` | `duck_heavy_requests` + DLQ + 幂等 + queue_handler(**须与 worker 队列处理器同批落地**,否则 run 滞留 WAITING_QUEUE)| W4 |
| W6 `duck_tools` | `agent_v6_duck_tools` | `wb_duck_*` enqueue-only 工具 + COMMENT 注册 + refresh | W5 |
| W7 `dialect_guardrails` | `agent_v6_dialect_guardrails` | DuckDB validator + 2.0 方言 prompt(新 `agent_system` recipe 版本,不改 v5 recipe)+ 接受/拒绝语料 | W6,G3 |
| W8 `budget_observability` | `agent_v6_budget_observability` | 源/查询预算、超时、有界指标、清理 | W7 |
| W9 `integration` | `agent_v6_integration` | register→query→链式→brief→final;重启/重复/失败/隔离全量门 | W8 |

实施序要点:先冻结接口(G1)→ kernel freeze → 把已测 DuckSession 打开顺序写成 W2 门(包版本锁死 `1.6.0.dev365`)→ Python 快照缝(G4)→ 元数据/会话 → 队列+handler → 工具 → validator → prompt → 预算 → 集成。**不要**把 `postgres` 扩展 ATTACH 进查询会话。sidecar 拷贝只在 G4 证明 Python 太慢之后才做。G6 不排期。`pg_duckdb` 不做。

---

## 8. pgembed Change: **No**

默认无改动,本报告确认该默认成立。pgembed 已提供 v6 所需的全部 Postgres 侧能力(18.4 运行时、pgmq、`get_server()` 生命周期、`POSTGRES_BIN_PATH`);DuckDB 作为 **pg-agent v6 worker 的 Python 依赖**在进程内运行,源库可以是 pgembed agent 库或任何 operator 配置的外部 Postgres。MVP 不需要任何新 Postgres 扩展。**不要**把 `pg_duckdb` 打进 pgembed。DuckDB 的 `postgres` 扩展是 worker 侧客户端,不是 server 扩展。

**例外清单**(仅当以下之一被证明时才重新评估,且需显式论证):

1. 要求把 DuckDB 打进 pgembed 发行物本身(而非 pg-agent 依赖);
2. 要求通过新的 server extension 在 Postgres 内部执行 DuckDB;
3. DuckDB Postgres extension 需要 pgembed 特定的 server patch;
4. 目标平台打包只有改 bundle 才能满足依赖。

四种情形当前均不成立。**特别地:不得为了启动/通信 DuckDB 而动 PL/sh、`pg_net`、`pgsql-http` 或新增 Postgres 扩展** —— 那会破坏既有进程边界,且不改善工作台契约。

---

## Appendix: Source Documents

- Oracle plan export:`pgembed/prompt-exports/oracle-plan-2026-08-28-195721-v6-duckdb-workbench-e390.md`(chat `v6-duckdb-workbench-inve-17AC43`)
- Item 1:`pg-agent/docs/analysis/_wip-v6-infinisql-functions.md`(InfiniSQL 功能清单,抓包修正版)
- Item 2:`pg-agent/docs/analysis/_wip-v6-pg-agent-seam.md`(v5/v4 接缝侦察)
- Item 3:`pg-agent/docs/analysis/_wip-v6-duckdb20.md`(DuckDB 2.0 可行性,**2026-08-28 以 `1.6.0.dev365` 实测重写**)
- Runtime probes:`_probe_duckdb160dev365.py`, `_probe_duckdb160dev365_b.py`, `_probe_duckdb160dev365_c.py`, `_probe_duckdb160dev365_d.py`, `_probe_duckdb_postgres_ext.py`(pgembed 18.4 活库)
- InfiniSQL 功能参考(仅功能):`ghidra-projects/docs/design/infinisql-standalone-duckdb/01/02/03/06`,`docs/design/unified-temp-workbench/SYNTHESIS-BRIEF.md`,`docs/research/infinisql-duckdb-production/*`,`docs/research/infinisql-language-reverse/*`

官方对照(只作宣传清单,不以博客代替测量):

- <https://duckdb.org/2026/08/17/duckdb-20-highlights>
- <https://duckdb.org/2026/08/20/duckdb-20-peg-parser>
- <https://duckdb.org/install/preview.html>
- <https://pypi.org/simple/duckdb/> / <https://pypi.org/project/duckdb/1.6.0.dev365/>
