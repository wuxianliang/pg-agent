# v6 DuckDB grammar-extension bootstrap

Date: 2026-08-29
Status: implementation-ready plan (no code in this change)
Scope: pg-agent v6 in-memory workbench connection lifecycle only

## Goal

定向改造现有 v6 临时 DuckDB 工作台的**连接创建 / bootstrap**，使 opt-in 的 unsigned `pipe_query_syntax` grammar extension 可以在每个受管连接上按固定顺序加载并激活；默认仍不加载扩展。不重构工作台、不改 in-memory 会话模型、不把 `run_schema`（PostgreSQL `session_mode`）改成 DuckDB schema，也不对 DuckDB 做 `INSTALL` 或持久化字段。

Done when:

- 默认关闭：无 `LOAD`、无 `allow_unsigned_extensions`、无 `active_grammar_extensions`、每个连接最终 `enable_external_access=false`。
- 启用成功：每个新受管连接按固定顺序 bootstrap，validator 与 executor 共用同一 `session.connection`，prompt 只在 live capability 确认 pipe 后才注入，且不泄漏 path/hash/unsigned。
- 启用失败：关闭半初始化连接，不返回可用 session，不静默降级。
- `temp` / `run_schema` 生命周期、PG metadata、queue 语义回归保持。

## Background

### 任务边界

- 本任务只改 **pg-agent v6 工作台连接生命周期**。`docs/plans/flock-rag-on-duckdb-*.md` 是 **v7 持久 RAG 平台**，要求与 v6 `DuckSessionManager` / `duck_heavy_requests` 隔离。
- `docs/analysis/v6-duckdb-workbench-2026-08-28.md` 已把 grammar-extension / `|>` 标为当时锁定 wheel 上不可用的未来 gate（`|>` ParserException，`INSTALL pipe` 404）。本计划就是那个 deferred spike。

### 目标 artifact（2026-08-29 实测）

| 层 | 当前 v6 生产锁 | 本任务目标 |
|---|---|---|
| Python 包 | `duckdb==1.6.0.dev365`（`pyproject.toml:10`，`uv.lock:390-391` PyPI 多平台 wheel） | `1.6.0.dev366+ga1f0ab1911` |
| engine 旧门 | `SELECT version() == v2.0.0-alpha38615`（`duckdb_runtime.py:139-141`，`test_duckdb_probe.py:12-13`） | 删除该门；改用 `pragma_version()` |
| source_id | 未单独校验 | `a1f0ab1911` |
| library_version | 未单独校验 | `v1.6.0-dev13823` |
| 平台 | macOS arm64 + CPython 3.12（`duckdb_runtime.py:93-95`） | 保持；目标 wheel 是 `cp312-cp312-macosx_26_0_arm64` |
| 扩展 | 不 LOAD | 本地 unsigned `loadable_grammar_extension_demo.duckdb_extension` |

实测文件（regular file，非 symlink）：

| Artifact | Path | SHA-256 | Size |
|---|---|---|---|
| Wheel | `/Users/wxl/Projects/duckdb-python-pgagent/dist-special-g1/duckdb-1.6.0.dev366+ga1f0ab1911-cp312-cp312-macosx_26_0_arm64.whl` | `fa4ba6fb193e98d9273d494d1255393a4df33b8d6890fbbcdd65b064b3c15ad9` | 17531134 |
| Extension | `/Users/wxl/Projects/duckdb-pgagent/build/reldebug/test/extension/loadable_grammar_extension_demo.duckdb_extension` | `fce89a46632a3ff3b98f75bc7f9bafb7c663e5b31d3cc0453d012ce4c8986393` | 8603398 |

原型 `DEFAULT_EXTENSION_SHA256` 与当前 extension 文件一致。实施时若 artifact 重建必须重算。不要把二进制复制进 pg-agent。`[tool.uv.sources]` 已有本地 path 先例（`pyproject.toml:18-19` 的 `pgembed`）。`pyproject.toml` 当前 unstaged 只多了 `streamlit>=1.62.0`，不要动它。

已验证启用协议（每个新连接都要重做）：`connect(allow_unsigned)` → identity → `LOAD` hashed path → `SET enable_external_access=false` → verify → `SET active_grammar_extensions=['pipe_query_syntax']` → metadata probe → 然后才 hydrate / `CREATE TEMP VIEW` / 用户 SQL。`active_grammar_extensions` 是连接级状态。

### 连接工厂与未接线原型

pg-agent 内全部 `duckdb.connect(` 落点：

| file:line | 角色 | 现状 |
|---|---|---|
| `v6/session_durability/duckdb_runtime.py:133-146` `DuckSessionManager._open_connection` | 唯一生产 session factory | 裸 `duckdb.connect()`；校验 `dev365` + `SELECT version()`；然后 autoinstall/autoload/external=false、`memory_limit`。**不调用** `bootstrap_connection` |
| `v6/session_durability/duckdb_grammar.py:129-167` `bootstrap_connection` | 未接线原型（untracked） | 启用时 unsigned → identity → LOAD → external=false → active grammar → probe；失败 `con.close()` |
| `v6/dialect_guardrails/duckdb_validation.py:63-66` | validator `con is None` fallback | 再建未激活 grammar 的连接。生产路径不走这里；W7 测试全部传入 `con`，该分支目前未覆盖 |
| `v6/duckdb_probe/test_duckdb_probe.py:34` | W2 `hardened_connection` | 独立 connect+SET 副本 |
| `v6/source_ingress/test_source_ingress.py` `hardened` | W3 | 同上 |
| `v6/dialect_guardrails/test_dialect_guardrails.py:19` | W7 | 裸 connect，把 `con` 传给 validator |

没有连接池、没有 reconnect retry。`get_or_open()`（`duckdb_runtime.py:148-183`）只在无活 session 时调用 `_open_connection()`；`run_schema` 随后 `hydrate()`。`DuckSession`（`duckdb_runtime.py:33-39`）无 capability 字段。

`run_schema` / `temp` 是 PostgreSQL `duck_workbench_sessions.session_mode`，不是 DuckDB schema。连接是 in-memory。ingress 是 psycopg2 → `executemany`，不依赖 external access。关闭即销毁内存库。

### 原型缺口（必须修，不要新开平行模块）

`duckdb_grammar.py` 已有正确 seam，但：

1. `current_setting('active_grammar_extensions')` 被当成可迭代对象逐字符比较，VARCHAR 时永远对不上 `config.active_features`。目标 wheel 的真实返回形状必须在实施时确认；helper 需同时接受 sequence 与 VARCHAR list literal，禁止 `eval`。
2. 禁用路径也跑 `_build_identity()`（在旧 wheel 上会直接失败）。本计划决定：换轮后 **两种模式都做完整三字段 identity**，因为现有 `_open_connection` 本来就是每个连接硬门，且 wheel 锁是全局的。
3. `from_env()` 在 disabled 时仍填入机器绝对 `DEFAULT_EXTENSION_PATH` 与默认 hash。Disabled 必须是 `path=None, sha=None, features=()`。
4. 启用路径未设 `autoinstall/autoload=false`。
5. Hash 只在 connect 之后做一次；需要启动时一次 + 每个新连接 `LOAD` 前再一次。
6. 无 `enable_external_access=true` 配置拒绝。
7. `DuckSession` 不保存 capabilities；`prompt_text()` 零调用方。
8. 无测试。

v6 **没有** TOML/YAML DuckDB 配置。现有面是 env（`PG_AGENT_DUCK_SOURCES` 等）、dataclass 默认、硬编码 `SET`。

### Validator 与 prompt

- `validate_read_query(sql, con=None)`（`duckdb_validation.py:58`）。生产调用方已传同一 session 连接：`duckdb_processor.py:198`（query）、`duckdb_runtime.py:248`（hydrate）。
- 无 SELECT/WITH 前缀硬编码；FROM-first 已测。`_tokens` 不收集 `|>`。不需要 SQL 重写器。`FORBIDDEN_TOKENS` 已含 `LOAD`/`INSTALL`/`SET`/`PRAGMA`/`ATTACH`/`CREATE`。
- Prompt 是静态 `agent_system` v3（`duck_prompt.sql`），在 PostgreSQL 装配。v6 worker **不**组装 prompt。`process_message()` 的 `llm_requests` 分支（`worker.py:315-337`）直接把 `payload["messages"]` 送给 `llm_fn` / `call_llm`。同文件的 `_invoke_llm()`（`worker.py:212`）在 v6 **没有调用方**；真正路径是 inline 循环。静态 recipe 全局 first-writer-wins，不能 bump 进 pipe 广告。

### 构造点（默认关闭测试必须显式注入 disabled config）

`DuckSessionManager(`：`duckdb_processor.py:25`，`test_session_durability.py:44,74`。

`DuckDBWorkerProcessor(`：`worker.py:552`，`workbench_demo/app.py:70`，`integration/test_v6.py:26`，`test_queue_bridge.py:44,101,111,120`，`test_budget_observability.py:27`。

## Resolved decisions

| ID | Decision | Rationale |
|---|---|---|
| D1 Config surface | 权威面是 `PG_AGENT_DUCKDB_GRAMMAR_*` env。不加 TOML/YAML，不加新 CLI flag。 | v6 已有的 opt-in 面就是 env + argparse 镜像；grammar 原型已用这组名字。 |
| D2 Freeze point | `DuckSessionManager.__init__` 读一次（或接受注入的 `grammar_config`）并冻结。Processor 只往下传，自己不 `from_env()`。 | 唯一 session owner；生产在 `DuckDBWorkerProcessor` 构造时创建 manager，早于任何 queue 处理。 |
| D3 Disabled identity | 两种模式都做完整 package/source_id/library 校验。删除 `SELECT version()` 门。 | wheel 锁是全局的；现有 factory 已经对每个连接做 identity。fork 的 `SELECT version()` 不在合同里。 |
| D4 Prompt | worker 在送 LLM 前按 **已存在的 live session capability** 追加一条 system 消息。不改 `duck_prompt.sql`。不在 worker 启动时 probe，也不在第一次 LLM 时 eager `get_or_open`。 | PG recipe 看不见 DuckDB 状态；静态 bump 会跨 run 泄漏。Mid-flow 确认：接受首轮 LLM 可能看不到 `|>` 说明。 |
| D5 Validator fallback | 保留 `con=None` 参数，但改为 `DUCK_ARGUMENT_ERROR`；永不 `duckdb.connect()`。 | 禁止第二套连接；该分支目前未被测试覆盖。 |
| D6 Test style | 标准库 `main()` gate + fake `duckdb` 注入。不加 pytest。Native 用 `PG_AGENT_DUCKDB_GRAMMAR_NATIVE_TEST=1`。 | 与 W1–W9 gate 一致。`uv sync` 仍需要 fork wheel 文件；`.duckdb_extension` 仅 enabled/native 需要。 |
| D7 Session state | `DuckSession.capabilities` 为必填，来自 bootstrap 返回值。 | capability 必须绑在连接生命周期上。 |
| D8 `_open_connection` | 改为 instance method，返回 `(connection, capabilities)`，内部只调 `bootstrap_connection`。 | 单一调用方 `get_or_open`；manager 持有冻结 config。 |
| D9 External-access knob | `GrammarExtensionConfig.enable_external_access` 默认 false；env `PG_AGENT_DUCKDB_GRAMMAR_ENABLE_EXTERNAL_ACCESS` 为 true 时 **即使 grammar disabled 也拒绝**，不静默覆盖。`allow_unsigned_extensions` 永不成为配置字段。 | 满足“拒绝 true 而不是覆盖”。 |
| D10 Default enabled path | enabled 且未设 PATH env 时，使用源码中的 demo 默认绝对路径。disabled 不读该默认。 | 本机开发便利；路径仍须 hash 匹配才 LOAD。Mid-flow 确认。 |
| D11 Bootstrap vs queue | per-connection bootstrap 失败包成 `SessionError(DUCK_GRAMMAR_BOOTSTRAP_FAILED)`，processor 返回 envelope，worker `apply_queue_result` + archive。确定性配置/`LOAD`/identity 失败 **不 retry**。 | 现有 `SessionError` 路径已是 terminal；retry 只会重复同一 hash/file 错误。 |
| D12 LOAD hang | 不给 bootstrap 加 interrupt/timeout。文档写明它跑在 `_manager_lock` 内，现有 query `interrupt()` 覆盖不到。 | default-off 不 LOAD；enabled 是本地 demo。定向改造不新增取消原语。 |

Mid-flow（2026-08-29）确认 D3、D4、D10。Critique 后补 D11、D12。无未决设计问题。

## Current-state analysis

单一生产 factory：

```text
DuckDBWorkerProcessor
  └─ DuckSessionManager
       └─ get_or_open(run_id)
            └─ _open_connection()
                 └─ duckdb.connect()   # today: not bootstrap_connection
```

执行路径：

```text
wb_duck_* (enqueue-only)
  → duck_heavy_requests
  → AgentWorker.process_message()
  → DuckDBWorkerProcessor.process()
  → get_or_open(run_id)
  → validate_read_query(sql, session.connection)
  → session.create_view()   # same connection
```

`hydrate()` 对 `run_schema` 用同一连接重放 snapshot + view。不变量保持：validator 与 executor 共用 `session.connection`。

必须保留：macOS arm64 / CPython 3.12；in-memory DuckDB；PG-only metadata；per-run `RLock` + manager lock + processor `_run_locks`；queue 顺序/幂等/DLQ；每个成功返回的连接 `enable_external_access=false`；不改 v1–v5 SQL、pgembed、v7 Flock-RAG。

## Design

### Configuration

`GrammarExtensionConfig`（frozen dataclass，`duckdb_grammar.py`）增加冲突字段：

```text
enabled: bool = False
extension_path: Path | None = None
extension_sha256: str | None = None
active_features: tuple[str, ...] = ()
enable_external_access: bool = False
```

`allow_unsigned_extensions` 不是字段、不是 env、不是 CLI、不是 PG 列。只在 enabled 分支作为 `duckdb.connect(config=...)` 的内部 key。

| Env | Behavior |
|---|---|
| `PG_AGENT_DUCKDB_GRAMMAR_ENABLED` | 缺省 = disabled。接受 `1/true/yes/on` 与 `0/false/no/off`（大小写不敏感）。其它非空值是配置错误。 |
| `PG_AGENT_DUCKDB_GRAMMAR_EXTENSION_PATH` | 仅 enabled 使用。缺省则用源码默认 demo 路径。 |
| `PG_AGENT_DUCKDB_GRAMMAR_EXTENSION_SHA256` | 仅 enabled 使用。缺省则用源码常量（当前实测 `fce89a…6393`）。非缺省值必须是恰好 64 位十六进制（`validate()` 用现有 `_SHA256`，大小写不敏感）；格式错误是配置错误，不要等到 hash mismatch。 |
| `PG_AGENT_DUCKDB_GRAMMAR_FEATURES` | 仅 enabled 使用。缺省恰好 `pipe_query_syntax`；逗号分割后 trim；必须精确等于该单元素。空字符串非法。 |
| `PG_AGENT_DUCKDB_GRAMMAR_ENABLE_EXTERNAL_ACCESS` | 与 ENABLED 使用同一套 token（`1/true/yes/on` vs `0/false/no/off`，大小写不敏感）。缺省 = false。解析为 true **始终拒绝**（含 disabled）。其它非空值是配置错误，不是 false。 |
| `PG_AGENT_DUCKDB_GRAMMAR_NATIVE_TEST` | 仅测试。不是运行时配置。 |

`from_env()` 在 disabled 时的精确结果，即使 PATH/SHA/FEATURES env 存在：

```text
enabled=False, extension_path=None, extension_sha256=None, active_features=()
```

Disabled 不 stat、不 hash、不打开扩展文件。非法 path/hash 文本在 disabled 时忽略。`enable_external_access=true` 例外：显式不安全请求，disabled 也要 raise `GrammarExtensionError`。

Hash 生命周期：

1. `validate()`：纯配置 + external-access 冲突；enabled 时 SHA-256 必须匹配 `_SHA256`（64 hex）。
2. Manager `__init__` 在 enabled 时调用 `verified_path_and_hash()`：拒绝 symlink/非普通文件/错误后缀；canonicalize；流式 SHA-256；与 expected 精确比较（hex 大小写不敏感）。结果存 `_prepared_extension_path`，**不**放进 capabilities。
3. 每个 `bootstrap_connection` 在 `LOAD` 前再次校验非 symlink + canonical path 一致 + 再 hash，digest 必须同时等于配置 expected 与启动 digest。

```text
bootstrap_connection(
    config: GrammarExtensionConfig,
    *,
    prepared_extension_path: Path | None = None,
) -> tuple[duckdb.DuckDBPyConnection, DuckDBGrammarCapabilities]
```

生产始终传入 manager 的 prepared path。测试可省略，由 bootstrap 自行 resolve。时间 O(extension size)，额外内存 O(1)。不在每条 query 前 hash。

### Connection bootstrap

`bootstrap_connection` 是改动后**唯一**调用 `duckdb.connect()` 的实现。失败关闭：

```text
con = duckdb.connect(...)
try:
    ...
    return con, capabilities
except Exception:
    con.close()
    raise
```

**Disabled sequence**

1. 纯配置校验；拒绝 `enable_external_access=true`。
2. `duckdb.connect(config={})` — 不得传 `allow_unsigned_extensions`，包括 false。
3. 完整 identity：`duckdb.__version__`、`pragma_version()` 的 `library_version`/`source_id`，精确匹配。
4. `SET autoinstall_known_extensions=false`
5. `SET autoload_known_extensions=false`
6. `SET enable_external_access=false` 并 `current_setting` 确认为 false。
7. 不 hash/stat/LOAD/`SET active_grammar_extensions`。
8. `SET memory_limit='512 MiB'`
9. 返回 `DuckDBGrammarCapabilities(False, False, (), package, source_id, library)`。

**Enabled sequence**

1. 纯配置校验（在 connect 之前）。
2. `duckdb.connect(config={"allow_unsigned_extensions": True})`
3. 完整 identity。
4. autoinstall/autoload=false（预 LOAD hardening；不改变 LOAD→external=false 的里程碑顺序）。
5. 再校验 + 再 hash prepared path。
6. quote-doubling 后 `LOAD '<canonical path>'`。无 `INSTALL`，不用 extension 名代替路径。
7. `SET enable_external_access=false` 并验证。
8. `SET active_grammar_extensions=['pipe_query_syntax']`。
9. 正确解析 `current_setting('active_grammar_extensions')`，必须恰好 `('pipe_query_syntax',)`。
10. `duckdb_grammar_extensions()` 必须包含该 feature。
11. `SET memory_limit='512 MiB'`
12. 返回 `enabled=True, loaded=True, active_features=('pipe_query_syntax',), ...`。

任一步失败：关连接，向上抛，不降级。

Identity 常量：

```text
EXPECTED_PACKAGE = "1.6.0.dev366+ga1f0ab1911"
EXPECTED_SOURCE_ID = "a1f0ab1911"
EXPECTED_LIBRARY_VERSION = "v1.6.0-dev13823"
```

`_build_identity()` 拒绝缺行或畸形 shape。缺行/无法识别即失败关闭，不用 substring。

Active-feature parser：若已是 sequence 则规范化为 `tuple[str, ...]`；否则解析目标 wheel 的 VARCHAR list 渲染（括号、引号、空白），保持顺序，拒绝畸形。单元素封闭集合，不要通用 SQL parser。`duckdb_grammar_extensions()` 是第二道 live 边界。列名以实施时实际 probe 为准；无法识别即失败。

私有 SQL literal helper：quote doubling，只用于 path 与 feature list。

### Session ownership

`DuckSession` 增加必填 `capabilities: DuckDBGrammarCapabilities`。无默认 disabled 值。与 connection 同生共死，不写 PG。

`DuckSessionManager.__init__(..., grammar_config: GrammarExtensionConfig | None = None)`：

1. 保留 darwin/arm64 门。
2. 用注入 config，否则 `from_env()` 一次。
3. `validate()`；enabled 则 startup hash。
4. 存冻结 config 与 `_prepared_extension_path`。之后不重读 env。

`_open_connection(self) -> tuple[connection, capabilities]` 只调用 `bootstrap_connection(self._grammar_config, prepared_extension_path=...)`。自己不再 `duckdb.connect()`。去掉 `dev365` / `SELECT version()`。

`get_or_open`：

```text
bootstrap
  → DuckSession(..., connection, capabilities)
  → self.sessions[run_id] = session
  → PG status OPEN
  → hydrate if run_schema
```

bootstrap 成功前不得插入 `self.sessions`。已有活 session 直接返回，不重 bootstrap。关闭后再开必须完整重跑。

```text
live_capabilities(run_id: str) -> DuckDBGrammarCapabilities | None
```

在 `_manager_lock` 下：无 session 或 closed → `None`。**禁止** `get_or_open`、禁止新建连接。

`DuckDBWorkerProcessor.__init__(..., grammar_config=None)` 原样传给 manager。

```text
prompt_text_for_run(run_id: str | None) -> str
```

缺 run_id / 无 live caps → `""`；否则 `capabilities.prompt_text()`。不 open/hydrate。

`_open_connection` 必须把 bootstrap 期间的 **所有** 失败（`GrammarExtensionError`、`duckdb.Error`、`OSError`、hash/LOAD/identity 失败）包成 `SessionError`：

```text
Type: DUCK_GRAMMAR_BOOTSTRAP_FAILED
Phase: Session
```

不得让原始异常逃出 `get_or_open`。`DuckDBWorkerProcessor.process` 已捕获 `SessionError` 并返回 envelope（`duckdb_processor.py:263-264`）。`AgentWorker.handle_row` 对无 `status=="retry"` 的返回值会 `apply_queue_result` + `pgmq.archive`（`worker.py:440-454`）。因此 bootstrap 失败对该 queue 消息是 **terminal structured failure**，不是 visibility-timeout retry，也不会只靠 DLQ 消化确定性配置错误。Solution 指向检查锁定 wheel、extension 文件、digest、native 环境。**不得**建议“继续无 grammar”，也 **不得** 设 `retryable=True`。

启动期（`DuckSessionManager.__init__` / `from_env`）配置错误仍直接 raise，worker 根本起不来，没有 queue 消息可失败。

`run_schema` hydrate 失败沿用现有路径（`duckdb_runtime.py:177-182`）：`session.close()`、从 `self.sessions` pop、再 raise。PG 行此时通常已是 `OPEN`（hydrate 在 stamp OPEN 之后）；现有代码 **不会** 把该行改成 `DEGRADED`/`LOST`。下一次 `get_or_open` 对 `run_schema` + `OPEN` 会新建连接、升 generation、再 stamp OPEN、再 hydrate。本计划不改这个既有状态机，只要求新的 `|>` + disabled hydrate 失败走同一条路。

### Validator

签名保持 `validate_read_query(sql, con=None)`。`con is None`：先做空/超长检查，再 `QueryValidationError(DUCK_ARGUMENT_ERROR)`，说明需要已 bootstrap 的 managed connection。不 connect、不 SET、不关调用方连接。

不加 grammar 参数、`supports_pipe` bool、静态 feature 检查、pipe token 规则、SQL 重写。`extract_statements()` 是 pipe 能否 parse 的唯一权威。现有 FORBIDDEN_* 继续拦截用户 `LOAD`/`INSTALL`/`SET`/`PRAGMA`。

增加测试：`validate_read_query(nonempty_sql, None)`。

### Prompt

`prompt_text()` 仅当 `enabled and loaded and "pipe_query_syntax" in active_features` 返回非空。内容可含当前连接支持 pipe、`FROM ... |> WHERE ... |> SELECT ...` 示例、仍是单条只读、禁止 LOAD/INSTALL/改安全设置。禁止 path、SHA-256、unsigned、wheel 文件名、source_id。

`AgentWorker._messages_for_llm(payload)`：

1. 复制 `payload["messages"]`（不原地改，retry/log 共用原 payload）。
2. `run_id = payload.get("run_id")`。
3. 无 `duck_processor` 或 fragment 空 → 返回副本。
4. 否则追加 `{"role":"system","content": fragment}`。

插入点：

- `AgentWorker._invoke_llm()`（`worker.py:212`；目前 v6 无调用方，仍要改，避免未来接上时漏）。
- `process_message()` 的 `llm_requests` 真路径（`worker.py:315-337` 两处 `payload["messages"]`：`llm_fn` 与 `call_llm`）。

在 retry 循环**之外**算一次 augmented list，循环内把 **同一 list 对象** 传给 `llm_fn` / `call_llm`（不是 `payload["messages"]`）。W8 用 identity 断言测这一点，这样日志/调用看到的就是模型实际收到的 messages。不用于 `duck_heavy_requests` / embed / sql_heavy。session 尚未创建时省略 fragment——有意避免 prompt 装配创建连接。

**不修改** `duck_prompt.sql` 与 `v6/load.py`。W7 断言静态 task 不含 `|>` 与 `pipe_query_syntax`。

### State and data flow

Startup（同步，尚无 DuckDB 连接）：

```text
worker.main()
  → DuckDBWorkerProcessor(...)
  → DuckSessionManager.__init__()
  → from_env() / injected config
  → validate
  → enabled-only startup hash
```

失败则 worker 构造失败；不改 PG session 行；不选 fallback。

New connection：manager lock 下 bootstrap → 建 session → 插入 dict → PG OPEN → `run_schema` 才 hydrate。hydrate 若因 `|>` + 新进程 disabled 失败：走现有 degraded 路径，不返回可用 session，不改写/跳过定义。

Close 丢弃 capability。另一 worker 打开 `run_schema` 必须对新连接完整 bootstrap 再 hydrate。Grammar 状态不写入 `duck_workbench_sessions` / `duck_artifacts`。

已有活连接不因磁盘上 extension 被替换而重 LOAD；下次新连接会再 hash 并失败。Prompt accessor 读不可变 capability，不查 DuckDB。

不新增异步任务、timer、线程、fd。现有 query `interrupt()` 超时不变，也 **不** 覆盖 bootstrap：`LOAD` 与启动/per-connection hash 跑在 `get_or_open` 的 `_manager_lock` 里、session 尚未存在，现有 `DuckSession.query_bounded` timer 碰不到它。hang 住的 `LOAD` 会挡住该 manager 上所有 `get_or_open`。本定向改造接受这一点：default-off 从不 `LOAD`；enabled 是 operator 控制的本地 demo artifact。不为 bootstrap 新增第二套 timeout/cancel。

### Errors and edge cases

| Failure | Behavior |
|---|---|
| 非法 ENABLED / EXTERNAL_ACCESS 布尔（同一 token 集） | Manager 构造 raise `GrammarExtensionError` |
| SHA-256 不是 64 hex | enabled 时 `validate()` 失败，不进入 hash 文件 |
| `enable_external_access=true` | 创建连接前拒绝，不覆盖 |
| per-connection bootstrap 失败 | `SessionError(DUCK_GRAMMAR_BOOTSTRAP_FAILED)` → processor envelope → `apply_queue_result` + archive；不 retry |
| features 不是恰好 `pipe_query_syntax` | 启动失败 |
| enabled path 缺失/symlink/非普通文件/不可读/错误后缀 | 启动失败，无连接 |
| 启动后文件被换 | `LOAD` 前再 hash，关新连接并失败 |
| hash mismatch | 不执行 `LOAD`，关连接 |
| identity mismatch | 关连接 |
| `LOAD` / 无法关掉 external / active 解析失败 / metadata 缺 feature | 关连接 |
| `validate_read_query(..., None)` | `DUCK_ARGUMENT_ERROR`，不建连接 |
| `run_schema` hydrate 遇到 pipe 定义但当前 disabled | hydrate 失败，无可用 session |
| 默认 disabled | 硬化连接，不碰文件 |
| 复用已有 session | 不重 hash/LOAD |
| 构造后改 env | 忽略直到新 manager/进程 |

### Dependency lock

`pyproject.toml`：

```text
duckdb==1.6.0.dev366+ga1f0ab1911
```

`[tool.uv.sources]` 增加仓库相对路径：

```text
duckdb = { path = "../duckdb-python-pgagent/dist-special-g1/duckdb-1.6.0.dev366+ga1f0ab1911-cp312-cp312-macosx_26_0_arm64.whl" }
```

用 uv 重新生成 `uv.lock`，不要手改 version 字符串。确认：requires-dist 是新精确版本；源是该本地 wheel；`1.6.0.dev365` 的 registry URL/hash 全部消失。`uv sync --locked` 在 macOS arm64 / CPython 3.12 上验证。

Wheel digest `fa4ba6fb…5ad9` 写入 v6 README。Extension digest 写入 `DEFAULT_EXTENSION_SHA256`。artifact 重建必须更新二者并重跑 native 测试。

## File-by-file impact

### `v6/session_durability/duckdb_grammar.py`

修原型：identity 常量；`enable_external_access` 字段；`from_env()` disabled 为 None/空 tuple；严格布尔解析；启动 hash vs per-connect rehash；`prepared_extension_path`；实测 extension SHA-256；SQL literal helper；enabled 也设 autoinstall/autoload；修好 active-feature 解析；失败关闭；**本文件是唯一 `duckdb.connect()` 实现点**。

### `v6/session_durability/duckdb_runtime.py`

Import grammar 类型与 `bootstrap_connection`。`DuckSession.capabilities` 必填。Manager 冻结 config。`_open_connection` 改为实例方法。去掉 `dev365`/`SELECT version()`。`get_or_open` unpack 后构造 session。`live_capabilities()`。hydrate/close/锁/无 DuckDB schema 语义不变。bootstrap 错误包成 `DUCK_GRAMMAR_BOOTSTRAP_FAILED`。依赖 grammar 模块先改完。

### `v6/queue_bridge/duckdb_processor.py`

可选 `grammar_config` 下传。`prompt_text_for_run()`。query 仍 `validate_read_query(..., session.connection)`。不给 operations/artifacts 加 capability 列。

### `v6/kernel_freeze/worker.py`

`_messages_for_llm()`；用于 `_invoke_llm` 与 `process_message` llm 真路径。不加 grammar CLI。`main()` 继续 `DuckDBWorkerProcessor(...)` 无 flag，靠 env。demo `workbench_demo/app.py:70` 同样走 manager `from_env()`。

### `v6/dialect_guardrails/duckdb_validation.py`

删除 fallback `duckdb.connect()`。`con is None` → `DUCK_ARGUMENT_ERROR`。保留 FORBIDDEN_* 与 `extract_statements`。

### 测试

| File | Change |
|---|---|
| **new** `v6/session_durability/test_duckdb_grammar.py` | `main()` fake-connector：用 `unittest.mock` patch **`v6.session_durability.duckdb_grammar.duckdb`**（模块顶层 `import duckdb`，不要 patch 全局 `sys.modules['duckdb']` 当唯一手段）。覆盖 disabled/enabled 顺序、失败关闭、hash mismatch、64-hex 格式错误、external-access 拒绝（含 disabled）、`duckdb.Error`/`OSError` 也被包成 `DUCK_GRAMMAR_BOOTSTRAP_FAILED`、prompt 门控；native 段由 `PG_AGENT_DUCKDB_GRAMMAR_NATIVE_TEST` 守卫 |
| `v6/duckdb_probe/test_duckdb_probe.py` | 新 identity；`hardened_connection()` → `bootstrap_connection(GrammarExtensionConfig())`；保留 hardening/`INSTALL`/`LOAD postgres`/`read_csv_auto`/interrupt 断言；显式 disabled，不受开发者 shell env 影响 |
| `v6/source_ingress/test_source_ingress.py` | `hardened()` 同上 |
| `v6/dialect_guardrails/test_dialect_guardrails.py` | bootstrap disabled 连接；`con=None` 测试；把该测试接受的错误类型集合扩到包含 `DUCK_ARGUMENT_ERROR`；静态 recipe 不含 `|>` / `pipe_query_syntax` |
| `v6/session_durability/test_session_durability.py` | 注入 `GrammarExtensionConfig()`；断言 capabilities disabled；保留 temp/run_schema 回归 |
| `v6/queue_bridge/test_queue_bridge.py` | 各 processor 注入 disabled config |
| `v6/budget_observability/test_budget_observability.py:27` | 注入 disabled config |
| `v6/integration/test_v6.py:26` | 注入 disabled config |
| `v6/workbench_demo/app.py:70` | 不注入则走 env；文档说明 demo 默认关闭 |

Fake connector 必须记录：connect config、identity 查询、hardening SET、LOAD、external verify、active SET、active verify、metadata probe、close。顺序断言：

```text
connect
  < identity
  < autoinstall/autoload
  < LOAD
  < SET enable_external_access=false
  < verify external false
  < SET active_grammar_extensions
  < verify active list
  < metadata probe
```

Disabled fake：无 unsigned key、无文件校验、无 LOAD、无 `SET active_grammar_extensions`。

Native 段：marker 缺省则 skip 成功；marker 在而 artifact/配置缺则 **硬失败**。覆盖：精确 identity、managed session capability、`|>` 经 `validate_read_query(session.connection)`、prompt 非空且无 path/hash/unsigned、两个独立连接各自激活、关一个不影响另一个、disabled 连接不报 feature、temp/run_schema 隔离仍在。

实施时再搜一遍 `DuckSessionManager(`、`DuckDBWorkerProcessor(`、`_open_connection(`、`DuckSession(`，确认无漏网构造点、无绕过 bootstrap 的 classmethod 调用。当前 `DuckSession(` 只出现在 `duckdb_runtime.py` 的 `get_or_open`；测试不得直接构造而不带 capabilities。

### 依赖与文档

- `pyproject.toml` / `uv.lock`：如上。不动 streamlit。不加 pytest。
- `v6/README.md`：新包版本、source/library、default-off、env 表、freeze、双次 hash、无 INSTALL、条件 prompt、unsigned 风险、demo 非生产插件、关闭步骤、wheel 回滚、两个实测 digest。明确 `run_schema` 仍是 PG `session_mode`。
- `v6/dialect_guardrails/README.md`：pipe 仅 live capability；validator 不再自建连接；静态 prompt 故意中性。
- `v6/session_durability/README.md`：capability 在内存、不持久化、每次 `run_schema` reopen 重建立。
- **不改** `v6/load.py`、`duck_prompt.sql`、`duck_sources.sql`。

## Risks and migration

**Wheel lock 是 breaking。** 新代码在 grammar disabled 时也拒绝旧包。实施后必须 import + `pragma_version()` + 重跑 W2 hardening/interrupt。不要用 `SELECT version()` 做兼容条件。

**Wheel 文件是 v6 环境前置条件，不是可选 CI 开关。** `[tool.uv.sources]` 把 `duckdb` 指到兄弟仓库里的本地 wheel 后，`uv sync --locked` 在缺少该文件的机器上会直接失败。不存在“没有 wheel 还能跑 default-off 测试”的配置。正确分层：

- **Fork wheel 文件**：所有要 `uv sync --locked` 的 v6 环境都必须有（含只跑 fake/default-off 的机器）。
- **`.duckdb_extension` 文件**：仅 `enabled=true` 或 `PG_AGENT_DUCKDB_GRAMMAR_NATIVE_TEST=1` 才需要。缺省 skip native 段；marker 打开而 extension 缺失则硬失败。
- Fake-connector 测的是 `bootstrap_connection` 顺序，仍依赖已安装的 `duckdb` 包可 import，然后 patch `v6.session_durability.duckdb_grammar.duckdb`。

**Unsigned native code。** SHA-256 只保证与 pinned bytes 一致，不是签名。文档必须写：demo extension 是本地开发产物、不是生产插件、启用即在 worker 进程加载 native code、必须默认关闭。关掉 DuckDB external access **不能**抵消 extension 里已有的任意行为。

**TOCTOU。** 拒绝 symlink；canonical regular file；每个新连接 LOAD 前再 hash；LOAD 与 hash 之间不插入用户逻辑。同机恶意写者超出本计划。

**Prompt 时机。** Live session 之前不广告 pipe。第一次 LLM 通常发生在任何 `duck_heavy` 之前，因此首轮可能没有 pipe 说明；该 run 的后续 LLM 在 session 存在后才会追加。这是 D4 的后果，不是疏忽。补偿办法见 Open Questions。

**`run_schema` 切换。** 若定义里有 `|>` 而新 worker disabled，hydrate 失败是正确行为。改 env 必须重启 worker。

**Rollback**

只关 grammar、保留 fork wheel：

1. 停 worker。
2. `PG_AGENT_DUCKDB_GRAMMAR_ENABLED=0` 或 unset。
3. 清 path/hash/features/native-test；external-access 保持 false。
4. 重启。Disabled 不碰文件、不传 unsigned、不 LOAD、不 SET active grammar。

恢复旧 wheel：只关 env **不够**，因为 identity 在 disabled 也强制新 fork。

1. 停所有 v6 worker。
2. 恢复 `pyproject.toml` `duckdb==1.6.0.dev365` 与对应 `uv.lock`。
3. 恢复 identity 常量与 W2 期望，或整份 pre-change revision。
4. `uv sync --locked`。
5. 重跑 W2–W9。

无 PG/DuckDB schema 迁移。若旧代码对未知 env 无感知，回滚代码本身即可；本计划不改严格 TOML 解析器。

## Implementation order

1. **Verify artifacts** — 再算一遍 wheel/extension SHA-256；确认包版本与 `pragma_version()`。不要提交未核对 digest。
2. **Lock wheel atomically** — `pyproject.toml` + uv source + `uv.lock` + `uv sync --locked` + 新 identity 常量与 W2 期望一起落地。
3. **Correct `duckdb_grammar.py` + fake tests** — 在接线 manager 前锁住顺序合同。
4. **Wire `DuckSessionManager`** — capabilities、冻结 config、bootstrap 委托、`live_capabilities`。与 grammar 模块作为同一生产接线单元。
5. **Pass config through processor** — `prompt_text_for_run`；所有 default-off 测试构造点注入 `GrammarExtensionConfig()`。
6. **Remove validator fallback** — 在改测试 helper 之前落地，避免测试偷偷建未 bootstrap 连接。
7. **Unify W2/W3/W7 helpers** — 全部 `bootstrap_connection(GrammarExtensionConfig())`。
8. **Conditional prompt** — `_messages_for_llm` 两条 LLM 路径；覆盖 enabled/disabled/absent-session/不修改 payload/retry 不重复；断言传给 `llm_fn`/`call_llm` 的是同一 augmented list 对象。
9. **Native integration section** — marker 守卫。
10. **Docs** — README 三处。
11. **Two-mode verification** — default-off 与 native opt-in。
12. **Final audit** of `duckdb.connect(`、`validate_read_query(`、`_open_connection(`、`DuckSession(`。

### Work items (execution index)

| ID | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| W1 Artifacts | 锁定真实 digest 与 pragma identity | 两个 SHA-256 与三字段 identity 写入计划/常量所用值已复测 | 外部 wheel/extension | none | S |
| W2 Lock | 权威依赖改为 fork wheel | `uv sync --locked` 安装 `1.6.0.dev366+ga1f0ab1911`；lock 无 dev365 | `pyproject.toml`, `uv.lock` | W1 | M |
| W3 Grammar module | 可独立测试的 bootstrap | fake 测试证明 enabled/disabled 顺序、失败关闭、hash mismatch | `duckdb_grammar.py`, `test_duckdb_grammar.py` | W1 | L |
| W4 Session wire | 生产 factory 走 bootstrap 并保存 capabilities | `get_or_open` 返回带 capabilities 的 session；失败无半开 session | `duckdb_runtime.py` | W3 | M |
| W5 Processor + tests inject | 配置下传；回归不受 shell env 影响 | 所有列出的构造点显式 disabled 或文档化走 env | `duckdb_processor.py`, session/queue/budget/integration tests, demo | W4 | M |
| W6 Validator | 禁止自建连接 | `con=None` 测过；生产仍传 `session.connection` | `duckdb_validation.py`, W7 test | W3 | S |
| W7 Helper unify | 测试连接与生产同一 factory | W2/W3/W7 无直接 `duckdb.connect(` | probe/ingress/guardrail tests | W3, W6 | S |
| W8 Prompt | 条件广告且不改静态 recipe | 两条 LLM 路径把同一 augmented list 对象传给 `llm_fn`/`call_llm`；`duck_prompt.sql` 无 pipe | `worker.py` | W5 | M |
| W9 Native | 真 artifact 上 pipe 可跑 | marker 开则硬失败于缺文件；`|>` validate+execute 过 | `test_duckdb_grammar.py` native 段 | W2–W8 | L |
| W10 Docs | 操作者能启用/关闭/回滚 | README 含 digest、unsigned 警告、回滚 | `v6/README.md` 等 | W2, W9 | S |
| W11 Audit | 无遗漏 connect/validator/factory 路径 | `duckdb.connect(`、`validate_read_query(`、`_open_connection(`、`DuckSession(` 搜索与最终表一致 | 全 v6 | W4–W9 | S |

## Verification

Default-off（无 native marker，显式 `GrammarExtensionConfig()`）：

- fake 不访问 extension 文件。
- W2–W9 回归通过。
- 静态 prompt 无 pipe 广告。
- `validate_read_query(..., None)` 不建连接。
- 最终 `duckdb.connect(` 只出现在 `bootstrap_connection`；`_open_connection(` 无 class-level 调用；无测试直接 `DuckSession(` 而不带 capabilities。

Native opt-in（marker + 真实 PATH/SHA）：

- 启动 hash 与 per-connection rehash。
- 精确 fork identity。
- enabled 顺序与 metadata。
- `FROM ... |> WHERE ... |> SELECT ...` 在同一 session 上 validate 并 `CREATE TEMP VIEW`。
- prompt 有 pipe、无 path/hash/unsigned。
- 连接隔离；失败关闭。
- temp/run_schema 语义未变；无 `INSTALL`；无新 PG/DuckDB 列。

最终 connect 表：

| 原站点 | 最终 |
|---|---|
| `_open_connection` | 不直接 connect；委托 bootstrap |
| `bootstrap_connection` | 唯一生产 connect |
| validator fallback | 删除 |
| W2/W3/W7 helpers | 委托 bootstrap(disabled) |

生产 `validate_read_query(` 必须继续传入执行用的那个 `session.connection`。

## Open Questions

None remaining.

Mid-flow (2026-08-29): D3 full identity both modes; D4 late advertising; D10 machine-local default path.

Critique (2026-08-29): D11 bootstrap failures are terminal queue envelopes, not retries; D12 hung `LOAD` is documented and out of interrupt coverage. Wheel file is required for `uv sync --locked`; only the extension binary is optional for default-off.

## References

- User spec: v6 临时 DuckDB 工作台连接生命周期定向改造
- `docs/analysis/v6-duckdb-workbench-2026-08-28.md` — 原可行性报告；grammar 为未来 gate
- `docs/plans/flock-rag-on-duckdb-final-plan-v4.1.md` — 不同任务，仅隔离边界
- `v6/session_durability/duckdb_runtime.py`, `duckdb_grammar.py`
- `v6/dialect_guardrails/duckdb_validation.py`, `duck_prompt.sql`
- `v6/queue_bridge/duckdb_processor.py`
- `v6/kernel_freeze/worker.py` — `_invoke_llm` 无调用方；真路径 `process_message` llm 循环
- `pyproject.toml`, `uv.lock`
- Oracle export (preservation baseline): `prompt-exports/oracle-plan-2026-08-29-180628-v6-grammar-bootstrap-17c1.md`
