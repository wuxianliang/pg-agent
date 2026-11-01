# v24 Chainlit Agent Runtime — 实施计划（2026-11-01）

> 目标：在 v24 冻结内核之上交付一个长期可维护的 agent 产品切片——Chainlit 页面驱动真实 v24 run + DeepSeek，Pi 基础工具与 RepoPrompt-CE 风格工具以 **v2 `ApprovedPlugin`** 装入，两个**族级 artifact** 承载 11 个工具，markdown 技能把两族工具串起来。

状态：待实施。ABI 走 v2 + 前置里程碑 W9（§12）；"薄切片"目标作废，第一判据是长期可维护。
分支：`v24/ui-chainlit`（本地，不 push）。
门：`uv run python v24/ui/test_ui_gate.py`（无 socket、无 key、无需 Chainlit）；协议扩展门 `uv run python v24/s13/test_renderers.py`（§12）。

---

## 1. 目标与范围

### 1.1 要交付什么

1. **W9 协议扩展**（§12，先于一切 UI 工作）：新增通用 renderer `v24.text.plain` v1，11 个工具全部绑定它；现有 3 个 renderer 与 golden 一个字节不动。
2. 一个**持久**的 v24 运行环境（`agent_v24_ui` 库 + `.uidata/` 运行时目录），带 `--init` / `--status` / `--migrate` / `--reset --yes` 与启动漂移检测。
3. 一个同步的 `AgentRuntime` 控制面：两族装机、建 scope、起 run、bounded-round 驱动 worker、cancel/steer/respond、增量时间线。
4. 一个零 Chainlit 依赖的渲染层：把 v24 的 durable effect 投射成中性 step 记录，工具文本与模型看到的 `model_text` 逐字节相同。
5. 一个 Chainlit app：hub-and-replay、非流式、`cl.Step` 时间线、`/resume` `/cancel` `/steer` `/close` `/tools` `/skills`，会话与历史跨刷新持久。
6. **2 个**单文件、仅标准库的族级 v2 artifact：`pi_tools.py`（`read write edit bash grep find ls`）与 `rp_tools.py`（`read_file file_search get_file_tree apply_edits`）。
7. 2 个技能：`repo-recon`（RPCE 族）与 `surgical-edit`（Pi 族），经虚拟只读挂载暴露，**不复制进工作区**。
8. 一个 scripted-transport、无网络的验收门；一个真实 DeepSeek 的 opt-in 手动入口（第四个受控 socket 入口）。

### 1.2 明确不做（本计划范围外）

不加 `v24.host_run_events`（§13 W10）；不做 token 级流式（W11）；不做子代理/`agent.spawn`；不做 compaction；不做多工作区/worktree；不移植 RPCE 的 `manage_selection` / `workspace_context` / oracle / `ask_user` 工具 / session admin；不建第 11 张表；**不改任何 SQL**；不做 per-call 工具审批（§D6）；不做热迁移、不在活动 run 上热升级 catalog；不做真实 provider 的 ask-user（adapter 不产出 `interaction`，见 W13）。

`v24/host/*` 默认零改动，**唯一例外是 W9 白名单**（§12.7）：`renderers.py`、`tool_pages.py`，以及 `tool_pages.py` 的 import 断言、`s13/test_renderers.py` 的计数、`s13/test_pages.py` 的一行 import + 两行集合断言扩写。UI 的 M1–M5 不改这些文件。

---

## 2. 当前状态（已核实）

### 2.1 v24 是 run 级 agent runtime，不是会话运行时

- **权威在 SQL**。`v24/sql/30_advance.sql:85` 的 `v24.advance` 是唯一可写 `SECURITY DEFINER`；`start/steer/respond/cancel` 只创建 command effect，由 `advance` 应用。
- **Python host 是单写者 external-effect executor**。`v24/host/worker.py:83` `HostWorker`；`run_once(scope)`（`:651`）一轮 = `_reconcile` → `_resume_prepared` → `_orphan_state` → `_recover` → `_discover_ready`（翻页至 `has_more=false`）→ `_claim_and_execute` 一个 effect。
- `run_until_idle(scope, max_rounds=16)`（`:107`）逐轮 `run_once` 并 merge，`progress == 0` 即 `idle=True` 提前返回。**UI 不用它**——需要每轮之间有回调边界（§4.3）。
- `run_scopes_until_idle`（`:122`）的公平游标是**进程内**状态（`_fair_cursors`，`:100`、`:366-369`）。两个 UI 进程会互相饿死，**禁止使用**。
- `HostDB(control, service)`（`v24/host/db.py:87`）恰好两条连接，每次 RPC 提交，外部 IO 前 `assert_all_idle()`。**不新增第三条连接**。
- 十个表封闭集（`v24/sql/10_schema.sql`，断言于 `v24/s1/setup_db.py:540`）：`scopes, runs, effects, pins, episodes, fibers, slots, installs, events, requests`。无视图、无扩展、无元数据表。
- SQL 加载是 canonical 前缀：`v24/load.py:24-37` `SQL_LOAD_ORDER` 12 个文件，`50_permissions.sql` 必须最后；`load_stage(conn)` 要求调用方事务、拒绝 autocommit（`:71-86`）。
- 循环语义冻结（`v24/s4/README.md`，C17–C23）：model effect 最多 16 个 tool children、单一 continuation、`interaction → waiting → respond`、`pending_steer` latest-wins、turn/budget/seal、`unknown` 墙。
- **effect 状态闭集**：`ready / claimed / succeeded / failed / unknown / cancelled`（`10_schema.sql:94`）；run 状态闭集 `running / waiting / completed / failed / cancelled / blocked_unknown`（`:50`）。

### 2.2 读面与它们的真实语义

- `v24.poll(p_run_id, p_after_revision)`（`47_verbs.sql:35`）返回 `run_projection` + **前 64 条** run events；`p_after_revision` **只**驱动 `changed` 布尔，**不是事件 cursor**。
- `run_projection(p_run)`（`47_verbs.sql:14`）字段固定：`status / epoch_no / turn_no / driving_generation / interaction / pending_steer / close_intent / result / remaining_{steps,tokens,tool_calls,wall_ms} / revision / timestamps / owner_*`。`result.final_text` 由 `48_loop.sql:991-1004` 写入。
- `v24.host_run_effects(p_run, p_after_created_at, p_after_effect_id, p_limit)`（`49_host_reads.sql:209`）：
  - 复合 `(created_at, effect_id)` cursor，limit 上限 64，返回 `items / limit / has_more / next_cursor`；
  - **只投影 `kind IN ('model_call','tool_call')`**——install/prepare/release 噪音天然被过滤；
  - 字段含 `effect_id / kind / status / ordinal / parent_effect_id / request / outcome / created_at / settled_at / lease_until / cancel_requested`；
  - **最后一面 `next_cursor` 是 `NULL`**（`:285`），不是"上一页末尾"。要续读必须自己记住最后一条 item 的 `(created_at, effect_id)`；
  - **cursor 是"插入序"的**：已创建 effect 的 `ready → claimed → succeeded` 状态变化不会再次被 cursor 检出。所以"增量读新插入"+"按 id 刷新状态"必须成对使用（§4.3）。
- `v24.host_effect(p_effect)`（`49_host_reads.sql:289`）按 id 返回单个 effect，形状 `{"v":1,"effect":{...}}`，字段与 `host_run_effects` 的 item 相同。**这是刷新单个 active effect 的读面**，不需要新 SQL。
- 其余 host reader：`host_scopes:23`、`host_runs:76`、`host_effects:129`、`host_scope_installs:349`、`host_install_fibers:415`、`host_run_pins:480`、`host_request:550`；全部 `STABLE` + 固定 `search_path` + 经 `host_scope_allowed()` 授权。
- `v24.events`（`10_schema.sql:231`）有 per-`(entity_type, entity_id)` 的 `seq`（`:234`），唯一约束 `u_events_cursor (entity_type, entity_id, seq)`（`:243`）、`u_events_once`（`:244`）。**`seq` 不是全局 cursor**；`event_id` 是 identity，但分配序不等于提交序，也不能直接当 cursor（§13 W10）。

### 2.3 插件 ABI 两代，选 v2 + W9

| | v1 旧 ABI（已弃用，仅历史） | v2 **`ApprovedPlugin`** |
|---|---|---|
| 工具数 | **恰好 1**（`tool_key` 单值，不匹配即 `tool_key_mismatch`） | 1..16（`tools` 元组） |
| descriptor | 两键 `{"v":1,"tool":{description,parameters}}` | 九键闭集，含 `output_schema` / `render` / `limits` / `concurrency` / `replay_class` / `annotations` |
| 输出校验 | 无 | `validate_page()` + `output_check`，未知 renderer id **fail closed** |
| renderer | 无 | 必须是 `RENDERERS` 里的 `(id, version, digest)` 三元组 |
| `workspace_root` 字段 | **没有** | 有，且构造时校验"绝对路径 + realpath 等于自身 + 是目录"（`registry.py:301-304`） |
| host 侧 schema 校验 | 无（只做 `require_artifact` + spawn） | 有（args 尺寸、schema、page、render、content/meta 预算） |
| manifest 解析 | 手写 | 构造器强制九键/1..16/workspace_root；`from_manifest` 存在但与 SQL 的 `\x` 前缀不兼容（A2） |

**结论：11 个工具全部走 v2 `ApprovedPlugin`，2 个族级 artifact，并先做 W9。**

理由不是"v2 更先进"，而是三条硬事实：

1. v2 的 `render` + `output_schema` + page contract 让 host 在**进模型上下文之前**就能拒绝坏输出；v1 把全部预算与校验责任推给 artifact，长期维护会不断漂移。
2. v2 的 `workspace_root` 是字段，由 `registry.environment()` 注入（`registry.py:85-94`），不需要在进程里改 `V24_WORKSPACE_ROOT`；v1 没有这个字段，只能靠全局赋值（旧版 A1，已删除）。
3. v2 允许一个 install 提供最多 16 个 key（`registry.py:293-298`），这是"族级 artifact"的前提；v1 的 `tool_key` 单值使 11 个工具必然是 11 个 install。

被否：
- **继续走 v1**：不需要 W9，但每个工具一个 install、无 host 侧 schema/渲染/预算校验，11 份重复的路径栅栏与截断逻辑——与"长期可维护"直接冲突。
- **每工具一个 v2 artifact**：11 个 install、11 份共享区，仍然重复；且 install 步骤会从 2 条涨到 11 条。
- **等 W9 之后再做 UI**：就是本计划，W9 是前置里程碑（§12.10）。

v2 帧协议（`v24/host/line_json.py:184-330`）：

- 请求（一行 stdin）：`{"v":2,"operation":"invoke","reservation":"v24:tool_call:<effect_id>","args":{...},"tool":"<key>"}`；`prepare`/`release`/`inspect` 不带 `tool`。
- 成功（exit 0）：`{"ok":true,"v":2,"result":{"value":{...},"meta":{}}}`；`invoke` 必须有 `value`，`meta` 可省。
- 已知失败（exit 3）：`{"ok":false,"v":2,"error":{"code":"<code>","message":"<text>"}}`。
- stdout 必须是**恰好一行、以 LF 结尾**；多行、BOM、非 UTF-8、非 0/3 退出码 → effect `unknown`。
- `error.code` 必须匹配 `[a-z][a-z0-9_]{0,63}`；`message` ≤1024 UTF-8 字节，**不得含 NUL、`Traceback (`、或以 `/` 开头的 token**（`tool_results.py:128-157`）。违反的 failure 帧会被判 `bad_frame` → `unknown`，比"报错"更糟。

### 2.4 DeepSeek adapter 的冻结契约

`v24/host/deepseek.py`：

- `MODEL = "deepseek-flash"`（`:39`），`ENDPOINT = https://api.deepseek.com/chat/completions`（`:41`）。
- **`stream: false` 永远**；从不发 `tool_choice`；从不读 `OPENAI_API_URI`；`0 < timeout_s <= 239`；lease `min((ceil(t)+60)*1000, 300000)`（`:200`）。
- `build(effect, history, pins)`（`:209`）：`cause in ('start','steer','respond','continuation','spawn')`；`start` 读 `request['input']['messages']`，**只接受 `role in ('system','user')` 且 `content` 必须是 `str`**，否则 `AdapterFailure("input_messages_invalid")`。
- `_tools(pins)`（`:355-406`）把 live run pins 投影成 provider function 定义；v2 名字经 `_v2_provider_name()`（`:130-140`），合法 key **原样**出现，不加哈希后缀。descriptor 的 `tool.key` 必须与 pin key 相等（`:378-381`）。
- `DEFAULT_COMPLETION_CAP = 256`、`MAX_COMPLETION_CAP = 512`（`:43-44`）；`max_output_tokens` 从 `request['input']` 读，不是 message。
- `build()` 把 `cap = max(1, min(cap, MAX_COMPLETION_CAP))`（`:233-240`）——这是对**请求值**的静默截断（clamp）：只把超过硬上限的请求压回上限，无害、不改语义、不碰任何内容；真正的内容截断在响应侧（下一条）。
- **超限的后果在响应侧（已核实 `:508-510`）**：provider 在硬上限处截断回复并给 `finish_reason="length"`；`interpret()` 的 `finish in ("length","aborted","insufficient_system_resource","other",None)` 分支 → `_unknown("finish_length")` → effect `unknown` → run 终止（`blocked_unknown`）。**这不是"把回答截短后当成 final"**，也不是"参数被截断后照常执行"——整轮失败。§4.6、§11、§13 的文案与验收按这个事实写。
- API key：`DEEPSEEK_API_KEY` → `OPENAI_API_KEY`（`:172-174`）。
- **`interpret()` 从不产出 `interaction`**（模块内 grep 零命中）：它只返回 `final` 或 `tool_calls`。v24 的 `waiting` 只能由 model outcome 的 `interaction` 键触发（`48_loop.sql:326-360` 要求 `schema_digest`/`prompt_digest`/`payload` 三键）。**因此真实 provider 下 `waiting` 不可达**；本计划用 `ScriptedUiAdapter`（§4.3）覆盖该分支，并把“真实 provider 的 interaction”记为 W13（§13）。
- `_tools` 的 `parameters` 只要求 `type: "object"`（`:384-386`）；v2 descriptor 的十三键 schema 子集对 provider 是兼容的。

### 2.5 关键约束（计划必须绕开的）

1. **所有现有 v24 DB helper 都是 disposable**：`v24/s1/setup_db.py:555` `setup_db()` 用 `_new_name()`（`:266`）生成 `v24_s1_<pid>_<hex>`，`_validate_name()`（`:270`）拒绝别的名字，退出即 OID 校验后 DROP。持久库只有根 `server.py:14` 的 `pgembed.get_server(PGDATA)`。
2. **AGENTS.md 只授权 3 个真实 socket 入口**（`v15/provider/smoke.py`、`demo_v15/drive.py` + `DEMO_MODE=real`、`v24/host/smoke.py`）。Chainlit 会是第四个 → §9 显式增补。
3. **AGENTS.md 要求每里程碑 commit + push `main`**；用户要求用分支 → §9 显式 deviation。
4. **不能 token streaming**：`stream:false` 是冻结契约，改它破坏 W 系列字节基线；流式另立 W11（§13）。
5. **事件面没有全局 cursor**（§2.2）。
6. **artifact 必须单文件、仅标准库、不能 import 仓库代码**（`v24/s13/plugins/fs_read.py` docstring + `registry.require_artifact` 的 digest 复核）。
7. **`registry.py` 没有 artifact 行数/字节上限**：`require_artifact()`（`:57-83`）只检查"regular file、在 `cwd` 内、sha256 匹配"；`stdout_limit / stderr_limit` 是**每次帧**的传输预算（`:10-11`），不是文件尺寸。族级 artifact 的尺寸上限因此是待验证项（§4.7）。
8. `v24.start(p_scope_id, p_owner_fiber_id, p_input, p_budget, p_request_key)`（`47_verbs.sql:198`）：`p_input` 是 object，`requires` 放在 `p_input.requires`（`40_interpreters.sql:2748`），最多 16 项、每项**恰好** `{"key": str}`、不得重复（`:2775-2791`）；`requires` 非空时 `owner_fiber_id` 不得为 NULL（`:2789`）。budget 至少含 `steps` 与 `tool_calls`。
9. **不存在 session 对象**：`scope` 是生命周期/能力分组，`run` 是一次执行。Chainlit thread（conversation）= 一个 scope + 多个 run；持久化靠文件，不靠新表。
10. **`v24.resolve` 只按 `(realm, key)` join slots，不按 scope 过滤**（`45_capability.sql:50-59`）。两个 scope 共用 realm 会让同一 key 命中两个 slot。**每个 scope 必须有唯一 realm**，manifest 的 `provides[].realm` 必须等于该 realm；`v24/s11/plugin_fixtures.py:288` 的 `self.realm = realm or f"g10-{uuid4().hex[:8]}"` 就是先例。`smoke.py` 用固定 `"default"` 只因为它不装机（`smoke.py:155-176`），不能照抄到多 scope 场景。
11. 顺序已定：`docs/investigations/v24-plugin-vs-agent-sequencing-brief-2026-10-29.md` 选 protocol-first，ABI 设计（`v24-tool-plugin-abi-v1-2026-10-30.md`）已 acceptance（`v24-tool-plugin-abi-w8-v1-acceptance-2026-11-01.md`）。本计划是在冻结 ABI 之上的**加性**产品切片，不是第二轮协议重写。

---

## 3. 关键决策与理由

> D1–D9 由 `context_builder` 的 Oracle lane 裁决（2026-11-01），A2–A4 由代码复核得出；本版按"长期可维护优先"重写，v1 相关论证已删除。裁决依据写在每条下面，用户可逐条审计与推翻。

### D1 · 持久环境：`v24/ui/env.py` 自己拥有命名库

**决定**：库名 `agent_v24_ui`，跑在仓库根 `.pgdata` 的同一个 pgembed server 上；运行时状态放 `<repo>/.uidata/`（新增到 `.gitignore`）。

复用：`server.get_server()`、`v24.load.validate_manifest/load_stage/SQL_LOAD_ORDER`、`v24/s1/setup_db.py` 的 `validate_local_dsn`、`_GROUPS`、`_ROLE_GROUPS`、`_create_or_check_group`、`_database_oid`、`_role_state`、`_drop_database_exact`。**不 import `setup_db()` 本体。****不假设 `load_stage` 幂等**：只在确认"库不存在或库为空"时调用一次；已初始化由 `loaded.json` + 指纹比对判定，不靠重跑 DDL。

被否：
- 复用 `setup_db()` —— 名字校验直接拒绝，且退出即 DROP。
- 第二个 PGDATA —— 双份磁盘/双 postgres，"仅 unix socket" 纪律要复制两遍。
- 每会话一个库 —— 违背"conversation = scope + run"，scope 本就是这个边界。

### D2 · 依赖放置：`v24/ui/pyproject.toml` 独立 uv project

**决定**：照抄 `demo_v13/pyproject.toml` 的形状：

```toml
[project]
name = "v24-ui"
requires-python = ">=3.12"
dependencies = ["chainlit==2.12.0", "psycopg2-binary>=2.9.12", "pgembed>=0.3.0rc1"]

[tool.uv]
prerelease = "allow"

[tool.uv.sources]
pgembed = { path = "../../../pgembed", editable = true }
```

被否：加进根 `pyproject.toml`。根环境已为本地 duckdb wheel 挂了 `[tool.uv.sources]`，所有 v24 gate 都用它跑；把 chainlit（datasette/starlette 依赖树）塞进去会放大每个 gate 的解析面。`demo_v13` 已建立"独立 project"先例。

注意：`app.py` 与 `test_ui_gate.py` 都要把仓库根放进 `sys.path`（`Path(__file__).resolve().parents[2]`），否则 `import v24.host...` 失败。**gate 必须在根 uv 环境跑**（那里没有 chainlit）。

### D3 · App 位置：`v24/ui/`（tracked）

**决定**：`v24/ui/`。被否：`demo_v24/`——`.gitignore` 已有 `/demo_v13/`、`/demo_v15/`，新建 demo 目录要么被忽略（不可追踪），要么再加一行忽略规则把产品代码标成"永不提交"。用户明确要可扩展的 `v24/` 结构。

### D4 · 工具族：v2、2 个族级 artifact、11 个工具、Pi 名与 RPCE 名都暴露、不 alias

**决定**：

| 族 | 文件 | identity | tool keys |
|---|---|---|---|
| Pi | `v24/ui/plugins/pi_tools.py` | `v24.ui.pi_tools` | `read write edit bash grep find ls` |
| RPCE | `v24/ui/plugins/rp_tools.py` | `v24.ui.rp_tools` | `read_file file_search get_file_tree apply_edits` |

每个 artifact 是**一个 install**，`provides` 7 项 / 4 项（都 ≤16）。manifest 的 `requires` 恒为 `[]`（插件之间无依赖，全部标准库）；**注意区分**：`manifest.requires` 是插件间依赖，`start.input.requires` 才是 pin 集合（D4 的能力分层）。

**逐工具 descriptor 真实取值**（全部通过 `descriptor.py` 的封闭词表与跨字段规则）：

公共 `limits`：`max_value_bytes=40960`、`max_content_bytes=41984`、`max_meta_bytes=4096`（`LIMIT_RANGES`：value ≤49152、content ≤65536、meta ≥2；40960/41984 与 `v24/s13/plugins/fs_read.py:24-26` 同源）。

| key | 族 | `timeout_ms` | `concurrency` | `replay_class` | `annotations` R/D/I/O | `max_args_bytes` |
|---|---|---:|---|---|---|---:|
| `read` | pi | 5000 | `parallel` | `read_only` | T/F/T/F | 8192 |
| `grep` | pi | 15000 | `parallel` | `read_only` | T/F/T/F | 16384 |
| `find` | pi | 15000 | `parallel` | `read_only` | T/F/T/F | 8192 |
| `ls` | pi | 5000 | `parallel` | `read_only` | T/F/T/F | 8192 |
| `write` | pi | 5000 | `exclusive` | `mutating` | F/T/F/F | 65536 |
| `edit` | pi | 5000 | `exclusive` | `mutating` | F/T/F/F | 65536 |
| `bash` | pi | 20000 | `exclusive` | `external` | F/T/F/T | 65536 |
| `read_file` | rp | 5000 | `parallel` | `read_only` | T/F/T/F | 8192 |
| `file_search` | rp | 15000 | `parallel` | `read_only` | T/F/T/F | 16384 |
| `get_file_tree` | rp | 5000 | `parallel` | `read_only` | T/F/T/F | 8192 |
| `apply_edits` | rp | 5000 | `exclusive` | `mutating` | F/T/F/F | 65536 |

逐条核对（`descriptor.py:202-214`）：
- `read_only` 的 7 个工具必须 `read_only=T, destructive=F, idempotent=T`——表格满足；
- `concurrency=parallel` 必须 `read_only=T`——只有只读 7 个用 parallel；
- 写工具全部 `exclusive`；`write` 因可选 `append` 不是幂等操作，故 `idempotent=F`；
- 词表里的 `idempotent` replay class **本计划未使用**，理由同上（`write.append` 与 `edit.oldText` 都不幂等）；词表允许未使用值。

**`replay_class` 与 `concurrency` 是"仅声明、零行为"**（`docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md:34`，R6：metadata only）。它们**不是**授权、并发控制或安全机制；谁把 `parallel` 当"可以并发跑"或用 `read_only` 当"只读保证"，谁就错了。能力收敛只靠 `requires` → pin 集合（见下）。

**能力分层（替代 per-call 审批）**：

| toolset | `requires`（= effective toolset，即请求 ∩ 已落地） |
|---|---|
| `read` | `read grep find ls read_file file_search get_file_tree` |
| `write` | `read` 的 7 个 + `write edit apply_edits` |
| `exec` | `write` 的 10 个 + `bash` |

- 默认：工作区根是 `.uidata/workspace`（scratch）→ `exec`；`V24_UI_WORKSPACE_ROOT` 指向真实仓库 → `read`。`V24_UI_TOOLSET=read|write|exec` 可显式覆盖。
- **effective toolset** = 请求 toolset ∩ 当前 catalog 已落地条目；`requires` 由 effective 集合生成。M1 的默认 `exec` 只得到 `{read}`、M2 得到 `{read,file_search}`——这是有意的里程碑形状，不是降级。若 effective 里的某个 key 已请求但 install/slot 未就绪，`start` 以 `dependency_unresolved` 硬失败（`40_interpreters.sql:3213-3219`）；**不要**把「catalog 还没实现某工具」当成这种失败。
- 未 pin 的调用有两道拒绝，**都不是** `match_pin`：
  1. SQL 层：`interpret_model` 为每个 tool_call 按 `(run_id, key, released_at IS NULL)` 找 pin，找不到直接 `invalid_outcome`，**不会创建 tool_call effect**（`48_loop.sql:1116-1126`）；
  2. dispatcher 层：`registry.match_tool()` 用 pin 里的 descriptor/digest 与 install 五元组比对，不匹配即 `AdapterNotFound`（`registry.py:437-462`）。
  `match_pin()` 对 `ApprovedPlugin` 直接 `protocol_mismatch`（`registry.py:464-467`），v2 不走它。

被否：
- 每族一个 v1 artifact —— 不可能，v1 单 install 单 key。
- Pi 名与 RPCE 名 alias 到同一实现 —— alias 要一个 install 提供两个 key；v2 可以，但会让 `_tools(pins)` 出现两个名字、模型选择更乱，且 descriptor 语义无法同时满足两族。**不 alias**。
- per-call 审批 —— v24 内核没有工具审批原语（`interaction` 只由 model success 产生），要做就得在 host 与 dispatcher 之间插第二相，超出本计划。用 toolset/pins 把能力面收窄，比事后逐调用审批更可靠，也更符合长期维护。

**重叠名裁决**（descriptor description 里写死，技能层再强化）：

| 重叠 | Pi 版 | RPCE 版 | 必须写清的差别 |
|---|---|---|---|
| `read` vs `read_file` | verbatim，**不加行号**；2000 行/32 KiB head；notice `[Showing lines a-b of n. Use offset=… to continue.]` | 1-based `start_line`；`start_line=-N` = tail；负 start + limit 非法；`start_line=0` 非法；超长 ⇒ 截断 + notice | `read` 用 `offset` 翻页；`read_file` 用 `start_line`，负数取尾 |
| `grep` vs `file_search` | `pattern` + `glob` + `ignoreCase` + `literal` + `context` + `limit`(默认 100)；500 字符行帽；`path:line:` | `pattern` + `mode`(auto/path/content/both) + `regex` + `whole_word` + `context_lines` + `max_results`(默认 50) + `count_only` + `filter{extensions,paths,exclude}`；按文件分组 | `grep` 要 glob 与字面量开关；`file_search` 要 mode 与 filter |
| `edit` vs `apply_edits` | `edits[{oldText,newText}]`，全部对**同一份原文**匹配、逆序 apply；精确失败后退化 NFKC/空白/引号/破折号归一化 | **三选一**：`rewrite` / `search`+`replace` / `edits[]`；`on_missing` 只对 rewrite 有效；状态 `success\|partial\|failed\|no_change` | `edit` 只有一种模式；`apply_edits` 必须说明"恰好一个模式" |

**`apply_edits` 的三选一在十三键子集里表达不了**（`oneOf`/`anyOf`/`const`/`default` 全在 `DENIED_KEYWORDS`，`tool_schema.py:31-39`）。落地：

- `parameters` 把 `rewrite`/`search`/`replace`/`edits`/`on_missing` 全声明为 optional，`required: []`；
- `description` 用自然语言把规则写死（"Provide exactly one of: (a) `rewrite` …; (b) `search` + `replace` …; (c) `edits` … `on_missing` is only valid with `rewrite`. Any other combination returns `mode_conflict` (multiple modes) or `invalid_mode` (no mode)."）；
- **artifact runtime 做恰好其一校验**：同时给多种模式（如 `rewrite` + `edits`、`edits` + `search/replace`）→ exit 3 `mode_conflict`；一种都没给（含 `edits=[]`）→ exit 3 `invalid_mode`；`on_missing` 与非 rewrite 模式同用 → exit 3 `invalid_mode`；
- `additionalProperties:false` 保留（`assert_supported` 对 parameters 根强制），模式选择不能靠隐藏字段。

**`apply_edits.status` 的语义**（闭集四值，全部是**成功 value**，exit 0）：
- `success`：全部编辑生效（rewrite 写入了不同内容）；
- `partial`：至少一条生效、至少一条 `oldText` 未命中；
- `failed`：一条也没命中（0 条生效）——这是**数据**，不是协议错误；
- `no_change`：rewrite 写入内容与原文件逐字节相同，或全部编辑都是空操作。

请求级/不安全错误仍是 exit 3：`invalid_arguments`、`mode_conflict`、`invalid_mode`、`path_*`、`not_found`、`not_a_file`、`binary_file`、`not_utf8`、`file_too_large`、`edit_ambiguous`（同一 `oldText` 多处命中）、`match_not_unique`（search 多处命中）、`io_error`。**`edit_not_found` 只属于 Pi `edit`**；`apply_edits` 不用它。

**Pi `grep`/`find` 的兼容子集**：Pi 原生实现 shell out 到 ripgrep/fd 并尊重 `.gitignore`；单文件仅标准库做不到。落地：`re` + `os.scandir` 自走树，`.gitignore` 用纯函数子集（前缀作用域、`!` 否定、行首 `/` 锚定、`.gitignore`/`.ignore`/`.fdignore`、跳过 `.git` 与 dotfile），`find` 用 `fnmatch` + 同一 ignore 层。明确记录：**兼容子集，不是字节等价物**；`fs_tools.js` 已建立先例。

**错误码闭集（全族共用，exit 3）**：

```text
root_unavailable invalid_arguments path_escape path_excluded symlink_denied
not_found permission_denied not_a_file binary_file not_utf8 file_too_large
line_too_long output_too_large io_error timeout spill_write_failed
mode_conflict invalid_mode edit_not_found edit_ambiguous edit_overlap
edit_noop edit_empty_old match_not_unique match_not_found
```

`invalid_arguments` 必须由 artifact 自己做——**v2 host 会先做 schema 校验**（`plugins.py:158-162`），但 artifact 仍要拒绝 schema 表达不了的组合（如 apply_edits 恰好其一）。错误 `message` 不得含绝对路径（§2.3 的 leak 规则）。

**artifact 尺寸**：删除旧的"每 artifact ≤600 行 / ≤24 KiB"。`registry.py` 没有尺寸限制（§2.5 #7），因此给一个**待验证**上限：每个族级 artifact **≤3000 行、≤160 KiB**（预计 1000–3000 行（pi 7 工具较长，rp 4 工具较短））。M4 用实测值替换该上限并在 gate 里钉死。

> 待验证：族级 artifact 的实际行数与字节数。验证办法：M4 完成后 `wc -l -c v24/ui/plugins/*.py`，把实测值上浮 20% 写进 gate 常量；若超过 3000 行，先把共享区与工具实现分离评审，再决定拆分，不静默放宽。

**运行预算（gate 断言）**：
- artifact 常量：`MAX_VALUE_BYTES=40960`、`MAX_CONTENT_BYTES=41984`、`MAX_META_BYTES=4096`、`MAX_TEXT_LINES=2000`、`MAX_TEXT_BYTES=32768`、`MAX_FILE_BYTES=1 MiB`、`MAX_SPILL_BYTES=8 MiB`。
- `ApprovedPlugin(timeout_ms=5000, timeout_cap_ms=25000)`；entry 级 timeout 只管 `prepare`/`release`/`inspect`，`invoke` 用 per-tool timeout（`line_json.py:250-259`）。
- `HostWorker(adapter=adapter, default_lease_ms=30000, tool_handler=dispatcher.tool_handler, resource_handler=dispatcher.resource_handler)`：lease 必须 ≥ `max(tool.timeout_ms)+5000`（`plugins.py:168-178` 的 `lease_insufficient`）。bash 20000 + 5000 = 25000 ≤ 30000。**两个 handler 都不是可选项**：缺 `resource_handler`，install 的 `host_prepare` 以 `resource_handler_absent` 结算成 `unknown`，install 永远停在 `preparing`，`fiber_control(on)` 不可能成功（`worker.py:1103-1115`）；缺 `tool_handler`，`tool_call` 没有执行者。

### D5 · 时间线：增量发现 + active 刷新，不新增 SQL

**决定**：UI 只读两个既有函数——`v24.poll` 取投影，`v24.host_run_effects` 取时间线，`v24.host_effect` 刷新单个 active effect。

**算法**：

1. **首次或 `/resume`**：从 `(NULL, NULL)` 开始全量分页，直到 `has_more=false`；把每条 item 交给渲染层（终态直接发最终记录，非终态进 `active`）。**记住最后一条 item 的 `(created_at, effect_id)` 作为 `discovery_cursor`**——不能用 `next_cursor`，它在最后一面是 `NULL`（`49_host_reads.sql:285`）。
2. 之后每轮只读 `host_run_effects(run, cursor_at, cursor_id, 64)`：只返回新插入的 effect；同样更新 cursor。
3. 每轮对 `active` 中每个 id 调 `host_effect(id)`；`status in ('succeeded','failed','cancelled','unknown')` → 发**一次**最终记录，从 `active` 移除并记入 `finalized`。
4. batch children 全部进 `active`（一个 model 可产生 ≤16 个 tool children）。
5. 复杂度 `O(N + Σ每轮|active|)`。

**为什么不需要指纹**：旧版的"每轮从 cursor 0 全量重读 + `(status,outcome,settled_at,…)` 指纹去重"是为了弥补"cursor 不反映状态变化"。增量读负责**发现**，`host_effect` 负责**状态**，两者合起来已经覆盖全部转移；终态只发一次由 `finalized` 保证。中间态（`ready→claimed`）不上屏，因此不需要中间指纹。

**代价**：UI 看不到 `host_prepare`/`host_release` 与 scope/fiber 事件。可接受——那是装机噪音，`--status` 覆盖。

被否：
- 新增 `v24.host_run_events(p_run, p_after_seq, p_limit)`：要动 SQL + GRANT + conformance matrix，且要重新定义 `v24.events` 的翻页语义。**记为 W10**（§13），不是本计划。
- 保留"每轮都从 cursor 0 重读全部 effect"：N 个 effect 的 run 在 T 轮里是 O(N·T)；一旦有 batch children 或长会话就不可接受。

### D6 · 变更安全：工作区栅栏 + 敏感路径 + toolset，不做 per-call approval

**决定**：安全模型五条：

1. 默认工作区根 = `.uidata/workspace/` 一次性 scratch → `exec` toolset；指向活仓库（`V24_UI_WORKSPACE_ROOT`）→ `read`，要写必须显式 `V24_UI_TOOLSET=write|exec`。
2. 所有文件工具复用 `fs_read.py` 的路径栅栏：无 `..`、绝对路径必须在根内、symlink 拒绝、`O_NOFOLLOW`、仅 regular file。
3. **敏感路径默认拒绝 → `path_excluded`**：`.env*`、`*.pem`、`id_rsa*`、`id_ed25519*`、`.uidata/`、`.git/`。大小写不敏感；对**相对 workspace root 的路径**的每一段匹配，不只 basename——先 `realpath` 再 `relative_to(root)`，**不要**拿绝对路径匹配，否则 scratch 根 `.uidata/workspace` 会把每个文件都判成 `.uidata/`。
4. `.v24/` 是**虚拟只读挂载**：`.v24/spill/**` → `V24_SPILL_ROOT`、`.v24/skills/**` → `V24_SKILLS_ROOT`，只读；写操作命中 `.v24/` → `path_excluded`；读操作只允许这两个前缀，其它 `.v24/**` → `path_excluded`。**不是符号链接、不是 OS mount**——macOS 上 bind mount 要 root，symlink 又被栅栏拒绝；虚拟映射是唯一自洽的实现。
5. `bash` 的 cwd = 工作区根、进程组 kill on timeout、合并 stdout+stderr、tail 截断 + spill；非零退出是**成功 value**（§12.5），不是失败帧。每条命令全文作为一个 `cl.Step(type="tool")` 上屏，且进 journal。

**被否 per-call approval，决定性理由**：v24 内核**没有工具审批原语**。`interaction` 只由"模型 success 且携带 `interaction`"产生（`v24/s4/README.md`），工具调用没有 ask 通道；line-JSON 是一帧进一帧出，插件无法在执行中回头问人。要做审批就得在 host 与 dispatcher 之间插第二相——那是对 ABI 的改动。`demo_v13` 的 `AskUserMessage` 能工作，是因为 v13 有 `human` effect 与 `_do_human` 结算路径；v24 没有对应物。

**记录为已接受风险**：路径栅栏与敏感路径拒绝是**模型面**约束，不是安全边界；`bash` 与任何同 uid 进程都能读写工作区外的东西。写进 deviation ledger 与 README 风险节，不粉饰。

### D7 · 分支策略：本地 `v24/ui-chainlit`，不 push

**决定**：从 `main` 切本地分支 `v24/ui-chainlit`；每里程碑恰好一次提交；按路径逐项 `git add`；提交信息 `<版本>: <祈使句摘要>`（如 `v24: add v24/ui persistent environment and control plane`）；**不 push**，直到用户明确要求。

被否 push 到 `origin/v24/ui`：AGENTS.md 的推送规则全文围绕 `main` 写（`git push origin main`、禁 force、被拒先 fetch/rebase、分叉就停下来问人）；推 feature 分支会造出仓库从未有过的第二条远程线。"每里程碑 push"的意图在有分支时已由"每里程碑 commit"满足。

### D8 · Selection 语义：完全推迟

**决定**：不移植 `manage_selection` / `workspace_context`。上下文面 = `file_search` + `get_file_tree` + `read`/`read_file`。

被否：selection 是 per-tab 可变状态、被其他每个工具消费。v24 没有 session/tab 对象；建模它要么建第 11 张表（违反约束），要么用进程内 dict（刷新即丢，且 RPCE 的"read 自动加 slice"副作用无对应物）。

### D9 · 线程模型、连接归属与会话文件

**决定**：严格照抄 `demo_v13` 的 hub-and-replay。

- 模块级：`_HUB_TASK` / `_DISPATCH: asyncio.Queue` / `SESSIONS: dict[sid, ThreadState]`；`on_message` 入队并 `await _consume(st)`；busy 时新消息走 steer 而非拒绝。
- `HostWorker` 是同步阻塞的（psycopg2 + 子进程 + HTTP），跑在**一个专用的单线程 executor**（`ThreadPoolExecutor(max_workers=1)` 或显式 `threading.Thread` + queue）里，绝不在事件循环上；**不要用默认的 `asyncio.to_thread`**——它跨调用可能换线程，psycopg2 连接会以难复现的方式炸。`HostDB`、`HostJournal`、`HostWorker` 的构造、使用、关闭都在同一个线程上。
- **`HostDB(control, service)` 两条连接只归 worker 线程**。UI 的所有读（`host_run_effects`、`host_effect`、`poll`）都在 worker 线程、两轮 `run_once` 之间做。
- `steer`/`respond`/`cancel` 全部进 hub inbox，由 worker 在轮隙执行。这与 v24 语义一致：`steer` 打到 claimed business effect 上只写 `pending_steer`，等最后一个 old-generation effect settle 才消费——在飞期间延迟投递**不丢语义**。
- 取消：`@cl.on_stop` 只置 `threading.Event`；worker 在轮隙检查并 `v24.cancel(run, driving_generation, key)`。协作式，与 `cancel_requested` + 迟到结算同构。
- **会话文件写入（`sessions.json`/`turns.jsonl`）也在同一个专用 worker 线程上**：Chainlit 回调只投递不可变记录，不在事件循环里做 fsync/rename。
- 一个进程一个 worker：`run_scopes_until_idle` 的公平游标是进程内状态，两个进程会互相饿死（与 D1 的文件锁互相印证）。

### A2 · manifest 一次构造，三处 digest 对齐（`from_manifest` 不能用于 SQL-valid manifest）

**已核实的 ABI 缝隙**：

- SQL 的 `interpret_install` 要求 manifest 的 `adapter_digest` 匹配 `^\x([0-9a-fA-F]{2})*$`，并存成 bytea（`40_interpreters.sql:2946-2950`）；`host_install` 回读时用 `encode(adapter_digest,'hex')`，即**裸 64-hex**（`49_host_reads.sql:388`）。
- `ApprovedPlugin.from_manifest` 要求 manifest 里的 `adapter_digest` 是**裸 64-hex**，且等于 `adapter_declaration_digest(language)`（`registry.py:364-366`）；`_hex64` 拒绝 `\x` 前缀（`registry.py:39-44`，由 `__post_init__` 调用）。

同一串字节不可能同时满足两边。**因此 v2 装机不能走 `from_manifest`。**

**决定**：

- 给 SQL 的 manifest JSON 用 `adapter_digest = "\\x" + adapter_declaration_digest("python")`。
- 进程内 entry 直接构造：

```python
raw = compact_json(manifest)
plugin = ApprovedPlugin(
    adapter_id=f"{identity}.{realm}",
    language="python",
    identity=identity,
    version="1",
    manifest_digest=hashlib.sha256(raw).hexdigest(),   # 与 SQL 同一串字节
    artifact_digest=hashlib.sha256(artifact_bytes).hexdigest(),
    adapter_digest=adapter_declaration_digest("python"),  # 裸 hex，匹配 host_install
    argv=(sys.executable, str(artifact.resolve()), "serve"),
    cwd=str(plugins_dir),
    environment_allowlist=(...),
    tools=tuple(ApprovedTool.from_descriptor(p["descriptor"], key=p["key"])
                for p in manifest["provides"]),
    workspace_root=realpath(workspace_root),
    timeout_ms=5000,
    timeout_cap_ms=25000,
)
```

- 三个断言（gate 必跑）：
  1. `plugin.manifest_digest == sha256(raw).hexdigest()`——**辅助**：同一进程里刚算过 `raw`，这条近似同义反复，只防手写常量；它**证明不了** SQL 侧与 host 侧对齐，别把它当主断言；
  2. `"\\x" + plugin.adapter_digest == manifest["adapter_digest"]`；
  3. **主断言**：对 `host_scope_installs(scope)` **从 DB 回读**的每一行（`install_id`/`identity`/`version`/`manifest`/`manifest_digest`/`artifact_digest`/`adapter_digest`/`provides`）与 `host_install_fibers(install_id)` 回读的 fiber 行调 `lookup_install(row)`，逐字段比对；`provides[]` 里没有 digest 列（只有 `realm`/`key`/`descriptor`），所以对每个 provide 用 `pg_jsonb_text(descriptor)` 与重建 manifest 的对应字节比对，再复算 `descriptor_digest` 与重建的 `ApprovedTool` 相等；**每个 scope 的每一个族都要跑**，不是只跑第一个。
- **负控制（断言必须真的能失败）**：把 artifact 改一个字节 → **用改后的字节重建 `ApprovedPlugin`** 再 `lookup_install`，返回空；把 manifest 的 `realm` 改一个字符 → 重建后 `lookup_install`/`match_tool` 走空 → `AdapterNotFound`。**只改磁盘文件不会让已构造对象里的 digest 变化**，不重建等于没测。两条都在 gate 里以"预期失败"各跑一次，`finally` 恢复原字节——否则断言只是装饰。
- `manifest` 由 `catalog.py` 生成，所以 provide 形状、1..16 个 key、唯一 key、v2 descriptor 由构造器保证；`ApprovedPlugin.__post_init__` 仍强制 tools 数量/类型、`workspace_root`、timeout 与 protocol=2（`registry.py:263-311`）。
- `descriptor_digest` 由 `ApprovedTool.from_descriptor` 算成 `sha256(pg_jsonb_text(descriptor))`（`registry.py:228-244`），与 SQL 的 `descriptor_digest` 同源；不要手算。
- 旧版"A1 + 手写 declaration digest"整段删除。`ApprovedPlugin` 没有 A1 描述的注入缺口：`workspace_root` 是字段，`_ApprovedEntry.environment()` 直接把它写进 `V24_WORKSPACE_ROOT`（`registry.py:90-94`；前提是 allowlist 含 `V24_WORKSPACE_ROOT`，§4.7 的清单已含）。

> 这不是"绕过校验"，而是绕开一个**表示层不兼容**：SQL 要 `\x` 前缀、host 要裸 hex。把 `from_manifest` 留给纯 host 场景（`s13` 用它自测），装机路径用上面的直接构造。M1 gate 必须证明两侧 digest 一致，否则整条 v2 装机不可用。

### A3 · 用 `run_once`，不用 `run_until_idle`

`run_until_idle` 在 idle 时提前返回，但也会在 `max_rounds` 内连续跑完多轮而**不给轮隙插话的机会**。`drive()` 自己写外层循环，每轮调 `run_once(scope)`，轮隙读时间线、清 inbox。这样才能在飞行中 steer/cancel。

### A4 · owner fiber 从已激活 install 取，不造 fixture

`v24/s2/test_g3a.py:143` 的 `provider()` 是**测试 fixture 的裸 INSERT**（installs/fibers/episodes/slots），不是公开 SQL verb，UI 不能用。

正确做法：`start` 的 `p_owner_fiber_id` 用**已经 `fiber_control(on)` 的第一个族级 install 的 fiber id**——这正是 `v24/s11/plugin_fixtures.py:429-441` 的做法（`execute_single` 取 `fiber["fiber_id"]` 作为 owner）。owner 只负责给 pin 提供宿主；`requires` 里的其余 key 仍由内核按 scope/realm/key 解析（`v24.resolve`），所以 owner 不必是每个 key 的提供者。

固定 owner = `pi_tools` 的 install fiber（catalog 顺序首个），`requires` = 当前 toolset 的全部 key。**owner 与 requires 分开构造**：owner 只负责给 pin 找宿主，不要求它提供全部 key。

验收：M1 断言 pin 集合 == `{read}`；**M2 是 A4 的第一个真正检验**（2 个 requires，owner 只提供其中 1 个），断言集合恰为 `{read, file_search}`；M4 在**同一个 run** 里断言 toolset 的全部 key（`exec` 时 11 个）。

若 M2 的 pin 集合小于 requires 集合，**gate 直接失败并保留诊断，不静默切换 owner 策略**。备选 C（为 run 单独 admit+activate 一个 driver install）需要独立的 manifest、生命周期与验收设计，是一次显式重做，不是兜底路径；任何情况下都不去 seed `v24/s2/test_g3a.py:143` 那样的私有表。

> M1 实测：`start` 的 `owner_fiber_id` 必须非空（`40_interpreters.sql:2789`），且 owner 必须属于 run 所在 scope。M1 selftest 会实测"同 scope 二次 start"；结果直接决定 M3 的会话模型（§10）。

---

## 4. 组件规格

### 4.1 `v24/ui/env.py`

```text
class UiEnv:  # frozen dataclass
    repo_root: Path; data_dir: Path; db_name: str
    socket_dir: Path; port: int
    maintenance_dsn: str; admin_dsn: str; service_dsn: str
    journal_path: Path; spawn_dir: Path; workspace_root: Path
    spill_root: Path; skills_root: Path

def open_env(*, init: bool = False, root: Path | None = None) -> UiEnv
def acquire_lock(data_dir: Path) -> int          # fd；失败抛 AlreadyRunning(pid)
def release_lock(fd: int) -> None
def init_env(env: UiEnv) -> list[str]            # 返回 loaded_files；已初始化则 already_initialized
def migrate_env(env: UiEnv) -> None              # 见 §4.1.2
def drop_env(env: UiEnv, *, yes: bool) -> None
def status_env(env: UiEnv) -> dict
def main(argv: list[str]) -> int                 # --init / --status / --migrate / --reset --yes
```

数据目录：

```text
.uidata/
  lock            # flock 文件，防第二个 UI 进程
  loaded.json     # 见下
  journal.jsonl   # HostJournal
  spawn/          # 插件 --spawn-log
  workspace/      # 默认工作区根
  spill/          # 虚拟挂载为 .v24/spill
  sessions.json   # 会话与 bindings
  turns.jsonl     # 每轮 user 文本
v24/ui/skills/    # 技能 source of truth，虚拟挂载为 .v24/skills
```

#### 4.1.1 `loaded.json`（`format_version=2`）

```json
{
  "format_version": 2,
  "db_name": "agent_v24_ui",
  "database_oid": 16384,
  "file_digests": {"00_schema.sql": "<hex>", "...": "<hex>"},
  "sql_manifest_digest": "<hex>",
  "db_fingerprint": "<hex>",
  "ui_state_version": 1,
  "w9_required": "v24.text.plain/v1",
  "initialized_at": "2026-11-01T00:00:00Z"
}
```

- `file_digests`：`SQL_LOAD_ORDER` 的**每一个**文件的 sha256；多一个/少一个都算 drift。
- `sql_manifest_digest`：`canonical_json([[name, sha256_hex], …])` 的 sha256，顺序 = `SQL_LOAD_ORDER`。
- `db_fingerprint`：**只读** catalog 查询，`v24` schema 的函数与表列的排序摘要：
  - 函数：`(proname, pg_get_function_identity_arguments, pg_get_function_result, md5(prosrc))`；
  - 表：`(relname, attname, format_type, attnotnull, md5(coalesce(pg_get_expr(adbin, adrelid), '')))`，`attnum > 0 AND NOT attisdropped`；
  - 两个列表各按名字/列序排序，整体 `canonical_json` 后 sha256。
  不含 OID、owner、ACL——那些会引入假阳性。
- `ui_state_version`：`sessions.json`/`turns.jsonl` 的格式版本；与文件里的 `format_version` 不一致 → 拒绝加载，改名 `.incompatible`，起新会话并横幅说明。
- `w9_required`：**这个环境要求 host 至少提供 `v24.text.plain` v1**。启动时断言 registry 里有该条目且字符串相等；旧环境（没有该字段）→ `migration_required`。

启动时**重算并逐项比对**：`db_name`、`database_oid`、`file_digests`、`sql_manifest_digest`、`db_fingerprint`、`w9_required`、`v24` schema 恰好十张表。任一不一致 → 退出 2，reason `schema_drift`（`loaded.json` 存在但 host 版本更低/更高时用 `migration_required`），stderr 只打**差异项名称**，不打 DSN/路径/值，并提示 `--reset --yes` 或 `--migrate`。

#### 4.1.2 `v24/ui/migrations.py`：机制存在，当前零迁移

```text
@dataclass(frozen=True)
class Migration:
    from_version: int; to_version: int
    describe: str
    apply: Callable[[UiEnv], None]

MIGRATIONS: tuple[Migration, ...] = ()     # 当前为空

def plan(env: UiEnv, loaded: dict, current: dict) -> list[Migration]
def run_migrations(env: UiEnv, plan_: list[Migration]) -> None
```

- 注册表机制存在，**当前没有任何登记路径**。`--migrate` 在 `plan()` 为空时返回 `migration_unsupported`，退出 2，**不假装迁移成功**。
- **v24 没有迁移机制**：schema/协议变更（catalog、descriptor、renderer、SQL）一律要求活动 run **先收敛**（terminal / `blocked_unknown`），然后 `--reset --yes` 重建；不做热升级，不在活动 run 上换 catalog。
- `--init` **只创建**：`loaded.json` 与指纹都对得上 → `already_initialized`、退出 0，**不重跑 `load_stage`**；`loaded.json` 缺失但库已存在 → `schema_drift`（拒绝祝福一个来历不明的库）；库不存在 → 建角色/建库/单次 `load_stage`/校验十表/写 `loaded.json`。

#### 4.1.3 初始化步骤（唯一写路径）

1. 取 `.uidata/lock` 的 `LOCK_EX|LOCK_NB`；失败 → `already_running` + pid，退出 3。
2. 幂等创建/校验四个 NOLOGIN 组（`v24_owner`、`v24_admin`、`v24_service`、`v24_operator`）。
3. 用 autocommit 连接 `CREATE DATABASE agent_v24_ui TEMPLATE template0`（不存在时）；DDL 不在 `load_stage` 的事务里。
4. `GRANT CREATE ON DATABASE agent_v24_ui TO v24_owner`。
5. 只建两个 LOGIN role：`agent_v24_ui_admin`（GRANT `v24_admin`）、`agent_v24_ui_service`（GRANT `v24_service`）。**不建 owner/operator LOGIN**。
6. 以 admin DSN 连接 → `SET ROLE v24_owner` → `load_stage(conn)`（一个非 autocommit 事务）→ commit。
7. 建 `.uidata/{workspace,spawn,spill}`，`realpath` 后写回；`.uidata` 权限 0700。
8. **事务提交后**才写 `loaded.json`（临时文件 + fsync + rename + fsync(dir)）。

不变量：

- 所有 DSN 过 `validate_local_dsn(dsn, socket_dir)`：host 必须是以 `/` 开头的目录、无 `hostaddr`/`service`/`servicefile`、无多 host/多 port。
- `load_stage` 前 `conn.autocommit is False`；任何 SQL 失败整体回滚，`loaded.json` 保持旧状态。
- **不在 `v24` schema 建任何元数据表/视图/扩展**（`setup_db._assert_closed_catalog` 断言十张表封闭集）。

CLI 与退出码：

```text
uv run python -m v24.ui.env --init [--root <path>]
uv run python -m v24.ui.env --status
uv run python -m v24.ui.env --migrate
uv run python -m v24.ui.env --reset --yes
```

0 成功 / 1 运行失败 / 2 未初始化、缺凭据、`schema_drift`、`migration_required`、`migration_unsupported` / 3 已被另一进程持有。失败只打稳定 reason code 与异常类名，**不打 DSN、key、异常全文**（沿用 `smoke.py` 纪律）。

`--root` **只属于 env CLI**。app 不解析命令行参数（Chainlit 的 `run` 不接受自定义参数），只读环境变量（§4.5）。

### 4.2 `v24/ui/catalog.py`

```text
@dataclass(frozen=True)
class ToolSpec:
    key: str; description: str; parameters: dict; output_schema: dict
    timeout_ms: int; limits: dict
    concurrency: str; replay_class: str; annotations: dict

@dataclass(frozen=True)
class FamilySpec:
    identity: str; version: str; artifact: Path
    realm: str; tools: tuple[ToolSpec, ...]

def families(realm: str, toolset: str) -> tuple[FamilySpec, ...]  # 已落地 ∩ toolset，跳过空族
def manifest(family: FamilySpec) -> dict
def build_plugin(family: FamilySpec, env: UiEnv) -> ApprovedPlugin
def build_registry(plugins):    # → registry.py:391 的注册表对象
def catalog_digest(families) -> str
def toolset_keys(toolset: str, families) -> tuple[str, ...]

MAX_SAFE_ARGS_BYTES: int | None = None
# 单次回复里 tool call args 的安全上限，单一来源；None = 未实测（M5 前）。
# 页脚、README、system prompt 都从这里取；别处不许写数字（§4.7、§11、§13 W12）。
```

构造顺序：

1. 读 artifact 字节 → `artifact_digest = sha256(bytes)`。
2. `descriptor = {"v":2,"tool":{九键}}`；`render` 的 digest 从 `RENDERERS.by_id("v24.text.plain",1).ref.digest` 读，**不写死**。
3. `manifest = {"identity","version","requires":[],"provides":[{realm,key,descriptor}...],"adapter_digest":"\\x"+adapter_declaration_digest("python")}`（`\x` 前缀只给 SQL）。
4. `raw = compact_json(manifest)`；直接构造 `ApprovedPlugin`，断言三处 digest 对齐（A2）。
5. 汇总成 `registry.py:391` 的注册表对象。

**realm 规则（硬要求，§2.5 #10）**：`realm` 每 scope 唯一（`ui-<uuid4().hex[:8]>`），manifest 的 `provides[].realm` 必须等于它。因此 registry 条目按 `(family, realm)` 构造并缓存，**不能**全进程只建一份 manifest。`workspace_root` 全进程一致（来自 `UiEnv`），不随 realm 变。

`catalog_digest` **不含 realm**：对 `[{identity, version, artifact_digest, tools:[{key, descriptor_digest}]}]` 排序后取 sha256。否则每个新 scope 都会让 `/resume` 误判"catalog 变了"。

`families(realm, toolset)` = 已落地工具 ∩ `toolset`，按族分组，**空族不返回**（否则会在 artifact 尚未落地的里程碑上构造不存在的 plugin）。里程碑形状：W9 通过后 M1 = `pi_tools{read}`（默认 `exec` 也只得到这一个）；M2 = `pi_tools{read}` + `rp_tools{file_search}`；M4 = 两个 artifact 分别 7/4 个 key。构造 plugin 要读 artifact 字节，所以**不能**为尚未落地的工具预留条目。M4 的门断言 key 集合等于 §D4 表、且 `len(provides)` 为 7/4。

### 4.3 `v24/ui/control.py`

```text
class AgentRuntime:
    def __init__(self, env: UiEnv, *, mode: str = "fake", adapter=None,
                 workspace_root: str | None = None, max_rounds_per_turn: int = 64)

    # 装机（幂等，按 (scope_id, identity) 缓存 install_id/fiber_id）
    def install_tools(self, scope, families) -> dict[str, str]   # identity -> install_id
    def fiber_for(self, scope, identity: str) -> str            # 已 on 的 install fiber；缺失即 bug
    def uninstall_tools(self, scope, identities) -> None        # 只 off+dispose，不 close
    def close_scope(self, scope) -> None                        # 只由 /close、容量回收、--reset 调用

    # 跨进程恢复（步骤见下，五步写死）
    def rehydrate(self, scope, realm, workspace_root, toolset) -> None

    # 会话（conversation = scope + 多个 run）
    def create_scope(self, realm: str) -> str
    def start_run(self, scope, owner_fiber_id, messages, *, toolset,
                  budget, key) -> tuple[str, str]
    def drive(self, scope, *, stop=None, on_effect=None, on_state=None) -> DriveReport
    def cancel(self, run_id, key) -> dict
    def steer(self, run_id, instruction, key) -> dict
    def respond(self, run_id, interaction_id, response: dict, key) -> dict  # interaction_id = projection.interaction.interaction_id (uuid)

    # 时间线
    def discovery(self, run_id) -> Discovery          # cursor + active + finalized
    def advance(self, discovery, *, on_effect=None) -> Discovery
    def replay(self, run_id) -> list[StepRecord]

    def run_state(self, run_id, after_revision=0) -> dict
    def close(self) -> None   # 只关连接/journal/线程/锁；**不** close scope、不 off/dispose
```

`v24/ui/fake.py` 提供 `ScriptedUiAdapter(DeepSeekAdapter)`——**落点只在这里**（`control.py` 不定义它），`control --selftest` 与 gate 的交互场景都从 `fake` import；它绝不进 real 路径。

`DriveReport`（frozen）：`rounds / status / idle / stalled / cancelled / waiting_interaction / last_revision / final_text`。

运行时拥有：一个 `HostDB`、一个 `HostJournal`、一个 `HostWorker`、一个 `PluginDispatcher`、scope→session 映射、`(scope_id, identity)`→install/fiber 缓存、每 run 的 `Discovery`、请求序号。

`ScriptedUiAdapter` 的契约：

- `send()` 固定返回 `(200, b"{}", 1)`；`interpret()` 从 `outcomes` 顺序取一条，取空即 `AdapterFailure("script_exhausted")`，不返回默认成功。
- 结果形状：`{"class":"success","result":{...},"reply":None,"assistant_message":...,"tool_calls":...,"reason":None}`；`result` 里 `final` / `interaction` / `tool_calls` 三选一，并附 `usage`。`usage` 是**内核形状** `{"tokens": <int>, "wall_ms": <int>}`（`48_loop.sql:364-374` 只允许这两个键、必须非负整数），**不是** provider 的 `prompt_tokens/completion_tokens`；`ScriptedUiAdapter` 必须照这个形状构造。
- `tool_calls` 用**内核形状** `[{"key":..., "args":{...}}]`（`48_loop.sql:302-309` 只允许这两个键）；同时 `assistant_message` 必须是**journal 归一化形状**：`role=assistant`、`content=null`、`reasoning_content` 为非空字符串、`tool_calls` 每项含 `id`/`name`/`arguments`（`arguments` 是 JSON 字符串）。少了 `reasoning_content`，下一次 `build()` 的 `_validate_history` 会以 `history_missing_reasoning` 拒绝（`deepseek.py:327-334`）。
- `interaction` 用 `{"schema_digest":"<64hex>","prompt_digest":"<64hex>","payload":{"prompt":...}}`。
- `build()` 继承真实实现，仍校验 `reserve.tokens`、history 与 `max_output_tokens`——假模式不绕过这些契约。

**install 是 scope 级的**（`command_install` 的 payload 带 `scope_id`），owner fiber 也必须来自 run 所在的 scope。缓存键必须带 `scope_id`——否则第二个 scope 会命中第一个 scope 的 install_id/fiber_id，静默用错 owner。新 scope 重新走完整装机（多 N 个 prepare effect）；这条路径已被 `plugin_fixtures` 证明可行。

**所有触碰 `HostDB`/`HostWorker`/`HostJournal`/会话文件的方法都在同一个专用线程执行**；Chainlit 回调不直接碰这些对象。

**verb 的 generation 契约**（`47_verbs.sql:73,147,172`）：`cancel` / `steer` / `respond` 都要求 `p_expected_generation`。调用方**不传** generation——`AgentRuntime` 在专用线程上、发 verb 之前立刻读 `run_projection.driving_generation`，避免把过期的代次带进来。`respond` 的 `p_response` 必须是非空 JSON **对象**，UI 侧固定 `{"text": "<回答>"}`；空回答不调 `respond`，保持 waiting。`stale_generation` / `interaction_mismatch` / `already_terminal` 都是可恢复的拒绝：更新投影、上屏说明、**不重试**。

`drive()` 契约：

1. 循环上界 `max_rounds_per_turn`（默认 64）。
2. 每轮：先清空 inbox（按 `seq` 顺序应用 `cancel`/`steer`/`respond`），再 `worker.run_once(scope)`。
3. 每轮之后：`advance(discovery)`——增量读新 effect、刷新 active、发终态；`run_state(run_id, last_revision)`，revision 变化才回调 `on_state`。
4. 停止条件（任一）：terminal（`completed/failed/cancelled/blocked_unknown`）；`status == 'waiting'` 且有 `interaction`；`stop.is_set()`（发 cancel 后再跑一轮收尾）；`run_once` 无进展且 run 仍 `running` → 报 `stalled`，**不假装完成**。
5. 请求键确定性可重放：`f"{scope}-{run}-{verb}-{seq}"`，`seq` 单调；`v24.requests` 主键 `(principal_id, request_key)` 保证重复键命中已有 receipt。

默认 budget：

```json
{"steps": 24, "tool_calls": 24, "tokens": 20000, "wall_ms": 600000}
```

`start.input` 另带 `max_output_tokens: 512`（**UI 显式取硬上限**；adapter 默认 256，`build()` 对超过 512 的值静默 clamp，`deepseek.py:43-44,233-240`。UI 不依赖默认值，避免「以为 512、实际 256」）。

**装机步骤**（`install_tools`，幂等 + 部分失败回滚）：

1. 每个 `FamilySpec` 构造 manifest + payload（同一串 `raw` 字节），并把 `ApprovedPlugin` 条目并入 `dispatcher.registry`（见下）。
2. 调 `v24.install(scope_id, NULL, raw, artifact_digest_bytea, key)`（`40_interpreters.sql:4113-4122`；wrapper 内部已经 `advance`，**不要**手拼 `command_install` 帧）→ `disposition='committed'`，`emitted[0]` 是 `install_id`。
3. 驱动 `host_prepare` effect，直到 install `state == "installed"`。
4. `host_install_fibers(install_id)` 取 fiber。
5. `v24.fiber_control(fiber_id, 'on', control_seq, key)`。
6. 缓存 install_id 与 fiber_id。

**registry 的替换点**：不可变 registry 是只读集合（`registry.py:391-417`），但 `PluginDispatcher.registry` 是普通属性，可在专用线程内整体替换。`install_tools` 必须**先**把该 scope 的 `(family, realm)` 条目并入一个新 registry 并赋给 dispatcher，**再**发 `v24.install`——`host_prepare` 的 `resource_handler` 要靠它查插件。`close_scope` 后移除该 realm 的条目并替换。所有替换都在专用线程、`run_once` 之外；**绝不**在每个 effect 前按 scope 切换 registry，否则交错驱动两个 scope 时会把 A 的 install 查成 B 的 entry。

`HostWorker` 的 `resource_handler` 必须指向 `PluginDispatcher.resource_handler`（`plugins.py:91`）；它对 `host_prepare`/`host_release`/`inspect_resource` 分别发 v2 的 `prepare`/`release`/`inspect` 帧（不带 `tool`，`line_json.py:250-259`），把结果结算回 `advance`。这条链不通，装机就是死的——M1 的第一个断言就该是 install 到达 `installed`。

任何一步失败：dispose 新 admit 的 install，驱动到完成，缓存保持原状。

`uninstall_tools`：`fiber_control('off')` → `dispose` → bounded rounds，直到 install/fiber `disposed_at` 非空、无未释放 slot。**这里不 close scope**——close 是不可逆的（之后 `install`/`start` 都报 `scope_closed`），只能由 `close_scope` 在 `/close`、容量回收（§4.5）、`--reset --yes` 时调用，且要在该 scope 的 install 与 run 全部结束之后。`close_scope` 之后立刻清掉该 scope 的缓存条目；重新进入必须用**新 scope + 重新装机**。

**跨进程恢复（`rehydrate`）**：binding 必须持久化 `realm`、`workspace_root`（realpath 后的绝对路径）、`toolset`（§4.5.1）——新进程只有这三项 + `scope_id` 才能重建同一个 install。`rehydrate` 五步写死：

1. 用**原 realm** 重建 `ApprovedPlugin`：`catalog.families(realm, toolset)` → `build_plugin`，再与 `host_scope_installs(scope)` 回读的 `manifest` / `manifest_digest` / `artifact_digest` / `adapter_digest` 逐项比对，并对每个 provide 用 `pg_jsonb_text(descriptor)` 比对字节（`provides[]` 无 digest 列，`descriptor_digest` 由 SQL 现算）；不一致 → `catalog_changed`（处置同第 4 步：只回放、不 drive），**不**用新 digest 覆盖旧行、不重建 install。
2. `host_scope_installs(scope)` 与 `host_install_fibers(install_id)` 回填 `(scope_id, identity) → (install_id, fiber_id)` 缓存；install 必须 `state == "installed"`、fiber `disposed_at IS NULL`，否则 `catalog_changed`。
3. 对**回读的每一行**执行 §A2 的断言 3（不是对内存对象），且每个 scope 的每个族都跑。
4. `workspace_root` 或 `toolset` 与 binding 不一致 → `catalog_changed`：**只回放，不 drive**（pin 集合或路径栅栏已经变了，继续跑会把结果写进错误的栅栏）。
5. **不得重新发 `install`**：同 `(scope, identity, version)` 且 digest 相同的重复 `install` 虽有 `existing` 分支、返回**已存在的** `install_id`（`40_interpreters.sql:2984-2996`，不插第二行），但随后还会再跑一遍 `fiber_control('on')` 与 `host_prepare`，多出 install/prepare effects 并重复 prepare 资源；digest 一旦不同则直接 `install_identity_conflict`（`:2989`）。rehydrate 只回填缓存、复用原 `install_id`，不产生任何 install effect。

`HostJournal.open()` 会 `_load` 已存在的 `.uidata/journal.jsonl`（`journal.py:117-140`），`worker._history(run)` 因此能重建 provider 历史；rehydrate 只要打开**同一个** journal 路径，不重放、不截断、不换文件。缓存回填与断言都在专用线程、`run_once` 之外做。

**`close()` 与 scope 生命周期**：`AgentRuntime.close()`（进程退出、测试收尾、单进程重启）**只**关闭 `HostDB` 的两条连接、`HostJournal` 的文件与锁、专用 worker 线程与进程锁；**不 close scope、不 `off`/`dispose` install、不 cancel run**。scope 只由 `/close`、容量回收、`--reset --yes` 销毁。任何要求"进程一退出就销毁 scope"的写法都作废——它会让跨进程 `/resume` 失去前提。

**起 run**：`requires = [{"key": k} for k in toolset_keys]`；`owner_fiber_id = fiber_for(scope, "pi_tools")`（A4；`install_tools` 在第 4-6 步已缓存它，`fiber_for` 只是读缓存，不重新装机）；`start` 必须返回两个 emitted id。`requires` 超过 16 或含重复 key 会在 SQL 层直接 `invalid_args`，gate 要断言 `len(requires) <= 16`。

### 4.4 `v24/ui/render.py`（零 Chainlit 依赖）

```text
@dataclass(frozen=True)
class StepRecord:
    name: str; type: str; output: str; effect_id: str | None = None

def render_effect(effect: dict) -> StepRecord | None
def render_state(state: dict, *, seen: frozenset[str]) -> list[StepRecord]
def render_run_start(*, scope, run_id, budget, requires) -> StepRecord
def render_generating() -> StepRecord
```

`app.py` 只做：

```python
step = cl.Step(name=record.name, type=record.type)
step.output = record.output
await step.send()
```

映射表（**v2 的 tool 文本直接取 outcome 里的 `content`，不重新渲染**）：

| effect.kind | status / outcome | name | type | output |
|---|---|---|---|---|
| `model_call` | succeeded + `result.final` | `model · final` | `llm` | `result.final.text`（全文；step 与助手气泡都**不**截断） |
| `model_call` | succeeded + `result.tool_calls` | `model · tools (n)` | `llm` | 每行 `key {args-json}`；args JSON 单独截到 500 字符，整段适用 2000 字符帽 |
| `model_call` | succeeded 且两者都无 | `model · empty` | `error` | reason |
| `model_call` | failed | `model · failed` | `error` | class + reason（`http_status`/`content_filter`/`zero_tool_calls`/`unknown_tool_name`） |
| `model_call` | unknown | `model · unknown` | `error` | reason（`http_5xx`/`transport`/`usage_invalid`/`lease_insufficient`） |
| `tool_call` | succeeded | `tool · <key>` | `tool` | `join_content(outcome.body.result.output.content)` —— 与 `worker.py:1066-1068` 喂给模型的 `model_text` **逐字节相同** |
| `tool_call` | failed | `tool · <key> (error)` | `tool` | 同样的 `content` join（`Error [code]: message`），不是从 `error` 重新拼 |
| `tool_call` | unknown | `tool · <key> · unknown` | `error` | host `reason` 全文（短码，不截断）；`output` 没有 content，不编造 |
| 任意 | cancelled | `<kind> · cancelled` | `error` | `cancelled`（outcome 为 NULL，不编造） |
| 任意 | ready / claimed（drive 结束仍未定） | — | — | 不上屏；由 `render_state` 收尾说明 |

非 effect step：

- `install · pi_tools` / `install · rp_tools`（`run`）：**每个族一次**，在 fiber `on` 之后；名字用 artifact 的 file stem。
- `run · started`（`run`）：scope/run 短 id、budget、requires 的 key 列表。
- `run · waiting`（`run`）：显示 `interaction_id` 短 id；调用 `respond` 时传**完整 uuid**——它是 `run_projection.interaction.interaction_id`，也就是产生该 interaction 的 model effect id（`48_loop.sql:1034-1035`），不是另造的业务 id。fake/scripted 路径随即 `cl.AskUserMessage` 取回答；**real 路径不可达**（§2.4），若出现则上屏 `waiting_unsupported` 并只给 `/cancel`。
- `run · steer superseded`（`error`）：明确告知"上一条 steer 被覆盖，未送达模型"——latest-wins，UI 不许装作两条都送达。
- `run · completed` / `failed` / `cancelled` / `blocked_unknown`（`run`/`error`）：投影 `status` + `turn_no` + `remaining_*`。
- `generating`（`llm`）：**每 turn 恰好一条**，不是每个 model_call 一条。

**"生成中"的诚实语义**：一条 `cl.Step(name="model", type="llm")`，output 固定 `生成中…（完成后一次性给出回答）`，**发出后永不更新**。理由：`stream:false` 是冻结契约；一个会动的进度条等于撒谎（模型可能已经崩了）。model_call settle 后发**新的** `model · final` step，占位作为历史标记留在时间线上。这是 `demo_v13` D6 的既定取舍。

**截断与泄漏**：**tool step 的 `output` 逐字节等于 host 的 `join_content(...)`，不做任何字符级截断**；`succeeded`/`failed` 都取 `content` 的 join（`failed` 的 content 就是 `Error [code]: message`），`unknown` 取 host `reason`（内核 reason 是短码，远小于 2000 字符）。工具文本的体积由 artifact/page 的 **2000 行 + 32 KiB + 40960 序列化预算**约束（§4.7、§12.4），UI 再截一次只会让"模型看到的"与"人看到的"不一致——这正是要禁止的。

2000 字符帽**只**用于三类说明性文本：`model · tools (n)` 的每行 `key {args-json}`（args JSON 另单独截到 500 字符）、`run · …` 的说明性文字、错误 `reason`；超出追加 `\n…[truncated, <n> chars total]`。助手的 final 文本**不截断**。绝不在 step 里打 API key/Authorization/DSN——渲染层加一道 `_SECRET_KEYS` 复查（照抄 `journal` 的 secret 扫描思路）。

### 4.5 `v24/ui/app.py`

模块级拥有：一个环境锁、一个串行 hub task、一个 dispatch queue、`SESSIONS: dict[sid, ThreadState]`、一个 `AgentRuntime`、一个 worker 线程、一个 `SessionStore`。

`ThreadState`：Chainlit session id、conversation_id、scope、当前 run、install ids、command queue、stop event、busy flag、每个 run 的 `Discovery`、last revision。

**`V24_UI_MODE=fake` 的脚本**（`ScriptedUiAdapter`，只在 fake 路径构造）：

- 普通消息 → `[{"tool_calls":[{"key":"read","args":{"path":"README.md","limit":5}}]}, {"final":{"text":"<echo>"}}]`；
- 消息含 `interaction` → `[{"interaction":{...prompt...}}, {"final":{"text":"answered"}}]`；
- 两者都带 `usage`，否则 `interpret_model` 的 token 记账会缺数。

`init_env()` 在 `.uidata/workspace/README.md` 不存在时写入 `# v24 ui scratch\n`，让 fake 的 `read` 有确定目标（也让人工检查能看到一个非空工作区）。

**启动输入只有环境变量**（`chainlit run` 不接受自定义命令行参数）：

| 变量 | 取值 | 默认/校验 |
|---|---|---|
| `V24_UI_MODE` | `fake` / `real` | `fake`；其它值 → `invalid_mode` 退出 2 |
| `V24_UI_WORKSPACE_ROOT` | 绝对目录 | 缺省 `<repo>/.uidata/workspace`；必须 `realpath == 自身` 且是目录，否则 `workspace_invalid` 退出 2 |
| `V24_UI_TOOLSET` | `read` / `write` / `exec` | 缺省按工作区根推断（默认 scratch → `exec`，外部路径 → `read`）；非法值 → `invalid_toolset` 退出 2 |
| `V24_SPILL_ROOT` | 绝对目录 | `open_env` 写进进程环境（未设置时）为 `.uidata/spill`；缺失时 artifact 拒绝截断（fail closed） |
| `V24_SKILLS_ROOT` | 绝对目录 | `open_env` 写进进程环境（未设置时）为 `v24/ui/skills`；缺失时技能块为空 |

`V24_SPILL_ROOT` / `V24_SKILLS_ROOT` 必须由 `open_env()` 写进**当前进程环境**，因为 `registry.environment()` 只复制 allowlist 里**已经存在**的变量，再注入 `workspace_root`（`registry.py:85-94`）。`V24_WORKSPACE_ROOT` 只由 `ApprovedPlugin.workspace_root` 字段注入（且 allowlist 必须含这个键，`registry.py:90-92`），app 从不对它赋值——这是 A2 与旧版 A1 的分界。

`@cl.on_chat_start`（**只准备环境，不起 run**——此时还没有用户消息）：

1. 取进程锁（失败 → 页内横幅 `already_running`，返回）。
2. 读 `V24_UI_MODE`；real 模式：验 `DEEPSEEK_API_KEY` / `OPENAI_API_KEY` → 构造 `DeepSeekAdapter` → `preflight()`。fake 模式：构造 `ScriptedUiAdapter`（脚本见上）。**全部在 `open_env()` 与任何 `HostDB` 之前**；real 无 key 则页内横幅 `credentials_absent` 并返回（进程不退出——它已经在服务了；退出码 2 只属于 M5 的 CLI 入口）。
3. `open_env()`；跑 §4.1.1 的漂移比对。不一致 → 横幅 `schema_drift`/`migration_required` + 提示命令，**不建 scope、不起 worker**。
4. 构造 catalog/registry（`workspace_root` 与 `realm` 见 §4.2）。
5. `SessionStore.new_conversation()`：生成 `conversation_id` 与 `resume_token`（32 bytes urlsafe），只存 `sha256(resume_token)`；页脚打印 token **一次**。
6. `create_scope(realm=f"ui-{uuid4().hex[:8]}")`——**scope 必须先于 install**，因为 `command_install` 的 payload 带 `scope_id`。
7. `install_tools(scope, families(realm, toolset))` → 每条 `install · <stem>` step。
8. 页脚：mode、db 名、workspace 根、`toolset=<请求值> (effective <已装数>)`、`max_out=512 token（含推理；超限本轮失败）`、safe-args 常量（`MAX_SAFE_ARGS_BYTES`，未实测时显示 `unmeasured` 而不是编一个数）、scope 短 id、resume token、命令表，并注明"发第一条消息即开始 run"。

首条普通消息（thread 尚无 run）：

1. `start_run(scope, owner_fiber_id=fiber_for(scope, "pi_tools"), messages=[{"role":"user","content": text}], toolset=toolset, budget=DEFAULT_BUDGET, key=...)`；`requires` 由 effective toolset（`toolset ∩ 已落地`）在内部生成（§4.3）。
2. 发 `run · started`（在 install step 之后——因果如此，gate 也这样断言）。
3. `drive()`。

`@cl.on_message`：

| 输入 | 行为 |
|---|---|
| 空 | 忽略 |
| `/resume <run_id>` | 只接受**当前 conversation** 的 binding；否则 `not_found_or_denied`，一个 step 都不发 |
| `/resume <run_id> <token>` | 用 `sha256(token)` 在 `sessions.json` 里找 conversation，且 `run_id` 必须在该 conversation 的 bindings 里；否则统一 `not_found_or_denied`（不泄漏别的 scope）。成功后按下表分派 |
| `/close` | 取消并收敛当前 run → `off`/`dispose` → `close scope` → 从 bindings 移除；未收敛则 `close_incomplete`，不 close |
| `/cancel` | 入 inbox；worker 轮隙读 `driving_generation` 后发 `v24.cancel(run, gen, key)` |
| `/steer <text>` | 入 inbox；busy 时也接受（内核写 `pending_steer`），同时本地记录 `(seq, text, generation_at_submit)` 供 §4.4 判定被覆盖 |
| `/tools` | 打印当前 toolset 的 key + 一行 description |
| `/skills` | 打印当前 `<available_skills>` |
| 其它，本 conversation 尚无 run | `start_run` + `run · started` + `drive()` |
| 其它，busy | 作为 steer 入队并告知 |
| 其它，idle 且已有 run | **同 scope 新 run**（M1 selftest 证明可行后启用；见 §10）；换 `run_id`，不换 scope |

`@cl.on_stop`：只置 `threading.Event`，回一条"已请求停止…"，**不声称已停止**（迟到结算仍可写入事实与成本）。

`@cl.on_chat_end`：**只解除附着**——`active_binding = null`，flush `sessions.json`；**不销毁**可恢复的 scope/bindings。Chainlit 刷新 = 新 thread；旧 conversation 仍可由 `/resume <run_id> <token>` 接回。

`/resume` 的状态分派（**不重建 scope、不重发 install**；terminal 只回放，running/waiting 先 `rehydrate`）：

| `run_projection.status` | 行为 |
|---|---|
| `completed` / `failed` / `cancelled` | 从 `(NULL,NULL)` 全量回放 effects；`result.final_text` 进最后一条 `model · final`。**不需要 `rehydrate`**（只读）；不再 `run_once`。 |
| `blocked_unknown` | 只回放 + 上屏 reason；**不重试**、不创建新 run。不需要 `rehydrate`。 |
| `running` | **先 `rehydrate(scope, realm, workspace_root, toolset)`**（§4.3 五步），再全量回放 → `worker._reconcile(scope)` → 继续 `drive()`。rehydrate 报 `catalog_changed` 时只回放、不 drive。若 reconcile 后仍无进展 → `stalled`，显示并停，不假装完成。 |
| `waiting` 且有 `interaction` | **先 `rehydrate`**，再全量回放 → 用 `interaction.payload.prompt` 重新提问 → 回答后 `respond`。若 `respond` 返回 `already_terminal`/`interaction_mismatch`，改为按新投影回放。**real 模式下该状态不可达**（§2.4），出现即上屏 `waiting_unsupported` 并提示 `/cancel`。 |
| `catalog_digest` 不匹配，或 `rehydrate` 第 1/2/4 步不一致 | 只回放，拒绝 `drive`/`respond`，reason `catalog_changed`。 |

**容量与回收**：`sessions.json` 最多保留 32 个 conversation。chats 超限时，只关闭"所有绑定 run 均已 terminal"的最旧 conversation（cancel→converge→off→dispose→close），其余保留；没有可关闭的就保留全部并横幅 `session_capacity`。**绝不为了腾位置丢活动 run。**

worker → UI 的回调用 `loop.call_soon_threadsafe`，载荷是不可变 `StepRecord`。

#### 4.5.1 会话与历史（`v24/ui/sessions.py`）

```text
class SessionStore:
    def new_conversation(self) -> Conversation
    def load(self) -> None                       # 损坏则改名 .corrupt-<ts>，起新会话
    def bind(self, conversation_id, scope_id, run_id, *, realm,
             workspace_root, toolset, catalog_digest) -> None
    def detach(self, conversation_id) -> None
    def find_by_token(self, token: str) -> Conversation | None
    def append_turn(self, *, conversation_id, run_id, seq, user_text) -> None
    def history(self, conversation_id, *, k=6) -> list[dict]
```

`<repo>/.uidata/sessions.json`（**per-record 字段被包在 collection 里**，否则跨刷新 `/resume <token>` 找不到旧 token）：

```json
{
  "format_version": 1,
  "active_conversation_id": "…",
  "conversations": [
    {
      "conversation_id": "…",
      "resume_token_hash": "<sha256 hex>",
      "created_at": "…", "updated_at": "…",
      "bindings": [{"scope_id": "…", "run_id": "…", "realm": "ui-1a2b3c4d",
                    "workspace_root": "/abs/realpath", "toolset": "exec",
                    "catalog_digest": "…"}],
      "active_binding": {"scope_id": "…", "run_id": "…"}
    }
  ]
}
```

- `realm` / `workspace_root` / `toolset` 是 `rehydrate` 的唯一依据，必须与写 binding 时同源（`workspace_root` 存 realpath 后的绝对路径）；缺这三项的旧 binding，或它们与当前进程的取值不一致 → `/resume` 只回放，reason `catalog_changed`，**不猜**、不用当前进程的 workspace/toolset 顶替。
- 原子写：同目录 `sessions.json.tmp` → `flush` → `os.fsync` → `os.replace` → fsync(dir)；权限 0600；**在专用 worker 线程**。
- 每 conversation 最多 200 条 binding，超出丢最旧的；被丢的 run 仍在 DB 里，但不再可 `/resume`（有界保留，不是数据丢失）。
- `.uidata/turns.jsonl` 追加 `{conversation_id, run_id, seq, user_text, created_at}`；assistant final **不落文件**，从 `run_projection.result.final_text` 读。每 conversation 最多 200 条 turn，超出重写文件（同样原子替换）。追加用 `O_APPEND` + fsync。
- 历史注入：新 run 的 system message 末尾

```text
<conversation_so_far>
[older turns omitted]
user: …            # ≤600 字符
assistant: …       # ≤800 字符（final 文本）
…
</conversation_so_far>
```

最近 `K=6` 轮；user ≤600 字符、assistant final ≤800 字符、**总计 ≤4000 字符**；超出逐条省略并留 `[…truncated]` / `[older turns omitted]` 标记；只带 user 与 final，**不带工具输出、不带 reasoning**。

### 4.6 技能层

格式（照抄 Pi 的约束）：

```markdown
---
name: repo-recon            # ≤64, ^[a-z0-9-]+$
description: Map an unfamiliar repository before changing it.   # ≤1024
---

# Repo recon
...正文，用 `read` / `get_file_tree` / `file_search` 的名字引用工具...
```

- **语言**：frontmatter、`description`、正文**全英文**，与 descriptor / system prompt / 工具错误信息一致；`v24/ui/README.md` 为每个技能给一行中文摘要。这是可逆的偏好默认，改语言不影响任何 artifact digest（技能不进 catalog）。
- `v24/ui/skills/` 是 source of truth；**不复制进工作区**。`V24_SKILLS_ROOT` 指向它，artifact 把 `.v24/skills/**` 虚拟映射过去（只读）。catalog 里的 `location` 填**根相对路径** `.v24/skills/<name>/SKILL.md`。
- 注入点：`start` 的 `p_input.messages[0] = {"role":"system","content": system_prompt}`；`content` 必须是 `str`（§2.4），不能塞结构化对象。
- 块形状（只三项）：

```xml
<available_skills>
  <skill>
    <name>repo-recon</name>
    <description>…</description>
    <location>.v24/skills/repo-recon/SKILL.md</location>
  </skill>
</available_skills>
```

- 历史注入：**同一个 system message 的末尾**追加 ` <conversation_so_far>`（§4.5.1），不是新消息。
- system prompt 还要写死四件事：(a) `stream:false`，一次回复就是完整回答；(b) **"Reply in the user's language"**；(c) 工具选择裁决表（`read`/`read_file`、`grep`/`file_search`、`edit`/`apply_edits`）；(d) **单次回复上限 512 token（含推理），超限本轮失败**——provider 在硬上限处给 `finish_reason="length"`，内核走 `_unknown("finish_length")` 终止 run，**不是**把回答或参数截短。因此 tool call 参数必须小步（`write.append`）；安全上限是单一常量 `MAX_SAFE_ARGS_BYTES`（§4.2 的 `catalog.py`，M5 实测后回填；`None` 时系统提示不写数字）。

两个样例技能：

1. `repo-recon` — "在不熟的仓库里动代码前先建立地图"。步骤：`get_file_tree(max_depth=2)` → `file_search(mode='path')` 定位 → `read_file` 读 3-5 个关键文件 → 用 `read` 翻页读长文件 → 输出 **≤120 words** 的结构摘要（`max_output_tokens` 由 UI 显式设到硬上限 512；超限是整轮 `finish_length` 失败，不是截断，字数上限要留余量）。教 RPCE 族，也教 `read_file` 的 `start_line=-N` 取尾。
2. `surgical-edit` — "在一个文件里做多处精确修改"。步骤：`read(path, limit=…)` 取原文 → 用**一次** `edit` 带全部 `edits[{oldText,newText}]`（对原文匹配、不重叠）→ `edit_ambiguous` 就扩大 `oldText` 重试。明确禁止用 `apply_edits.rewrite` 做小改。**大段新内容拆成多次 `write.append`**，每次只写一小段（以页脚/README 的 `MAX_SAFE_ARGS_BYTES` 为上限），避免 `finish_length` 让整轮失败。

### 4.7 插件 artifact 统一契约

每个 artifact 必须：

- `argv[1] == "serve"`，可选 `--spawn-log <abs path>`；单进程一次 serve，一行 stdin 一帧、一行 stdout 一帧。
- 仅标准库、无网络 import、无仓库 import、无跨 artifact import；`sys.stdlib_module_names` 可验证。
- 工作区根从 `V24_WORKSPACE_ROOT` 读（由 `ApprovedPlugin.workspace_root` 注入，A2）；缺失/非目录/非规范 realpath → `root_unavailable`。`V24_SPILL_ROOT`/`V24_SKILLS_ROOT` 只由 allowlist 透传。
- `environment_allowlist = ("PATH","HOME","LANG","LC_ALL","V24_WORKSPACE_ROOT","V24_SPILL_ROOT","V24_SKILLS_ROOT")`——**不含** `DEEPSEEK_API_KEY`/`OPENAI_API_KEY`/`PG*`；gate 要断言子进程环境里没有它们。
- 路径栅栏：拒绝 `..`、根外绝对路径、symlink、非 regular file；`O_NOFOLLOW`；`.git/` 与敏感路径 → `path_excluded`；`.v24/**` 按 D6 的虚拟挂载规则处理。
- 自己做参数校验（host 已做 schema，但 artifact 还要拒绝 schema 表达不了的组合）与尺寸预算（host 的 `max_value_bytes` 是最后一道，不是唯一一道）。
- **`text` 里不得出现 U+0000**：PostgreSQL 的 jsonb 不接受 `\u0000`，而 `v24.advance` 的 `outcome` 是 jsonb；NUL 一旦进 text，结算会抛 SQL 异常、effect 卡在 claimed，而不是干净的失败（`_check_safe_domain` 只查整数与 key，**不查字符串内容**，`tool_pages.py:58-76`）。共享区统一出口，二选一写死、不许各工具自定义：
  - **文件内容直读**（`read`/`read_file`/`edit`/`apply_edits`）：命中 NUL → exit 3 `binary_file`；
  - **搜索类**（`grep`/`file_search`）：含 NUL 的文件跳过并计数，不把该行放进 `text`（不报错）；
  - **`bash`**：`errors="replace"` 仍可能保留 NUL，出口统一 `text.replace("\x00", "\ufffd")`，**在截断与写 spill 之前**做（spill 因此同样无 NUL）；命令不因输出含 NUL 而失败，`exit_code` 照旧。
  共享区在两个出口（`finish_text` / `finish_command`）末尾各断言一次 `"\x00" not in text`，命中即 exit 3 `binary_file`——这是最后一道，不是主要手段。
- `prepare`/`release`/`inspect` 最小实现：v2 成功帧分别是 `{"ok":true,"v":2,"result":{"prepared":true}}` / `{"released":true}` / `{"observed":"known"|"absent"}`。
- **共享区**：每个 artifact 有一段用注释界定、**字节一致**的核心：

```python
# ==== BEGIN SHARED CORE (v24-ui-family-v1) ====
# 帧循环 / 路径栅栏 / 虚拟挂载 / 敏感路径 / ignore 匹配 / 截断与 spill / NUL 出口 / UTF-8 / canonical JSON
# ==== END SHARED CORE ====
```

gate 提取两个标记之间的全部字节（含标记）比较相等，且每个文件恰好出现一次。

共享区里的 `canonical_json` 必须与 `v24.host.canonical.compact_json` **逐字节一致**（对象键按 **UTF-8 字节序**排序——不是 Python `sorted(str)`，非 ASCII 键会不同；`ensure_ascii=False`；`(",", ":")`；拒绝 NaN/Inf；孤立代理项抛错）。artifact 不能直接用 `json.dumps` 默认参数：空格、`ensure_ascii=True`、插入序任何一个都会让 `max_value_bytes=40960` 的预算与 host 漂移。gate 用 12 组值（控制字符、非 ASCII、嵌套、空串、长串、`True`/`None`）对拍两边的字节长度与内容。

逐工具语义：

- `read`：`{path, offset?, limit?}`；verbatim 文本、**不加行号**；2000 行/32 KiB head 截断；notice 照 Pi。
- `write`：`{path, content, append?}`；递归建父目录；`append=true` 时追加（不存在则创建）；返回 `wrote N bytes`。
- `edit`：`{path, edits:[{oldText,newText}]}`；全部对**原文**匹配；空/歧义/重叠/no-op 分别报专属码；逆序 apply；精确失败后走 NFKC/空白/引号/破折号归一化。
- `bash`：`{command, timeout_ms?}`；cwd = 工作区根；合并 stdout+stderr；超时杀进程组；tail 截断 2000 行/32 KiB；全文 spill；**非零退出是成功 value**（§12.5）；超时/无法启动才 exit 3。
- `grep`：`{pattern, path?, glob?, ignoreCase?, literal?, context?, limit?}`；`re` + `scandir`；`.gitignore` 兼容子集；100 命中默认、500 字符行帽、`path:line:`。
- `find`：`{pattern, path?, limit?}`；`fnmatch` + 同一 ignore 层；1000 结果帽；相对 POSIX 路径。
- `ls`：`{path?, limit?}`；字母序、目录加 `/`、500 条目帽。
- `read_file`：`{path, start_line?, limit?}`；1-based；负 start = tail；`start_line=0` 非法；负 start + limit 非法；超长 ⇒ 截断 + notice。
- `file_search`：mode 推断、regex/literal、whole_word、context、按文件分组、filters、count_only、50 默认、**32 KiB 文本预算**。
- `get_file_tree`：`{path?, max_depth?, mode: auto|full|folders|selected}`；ASCII tree；`selected` 在无 selection 时等价 `full` 并在 output 里注明。
- `apply_edits`：三选一 runtime 校验（§D4）；`on_missing` 只对 rewrite；状态四值。

**统一文本预算**：所有工具的 `text` ≤2000 行且 ≤32768 UTF-8 字节；行数两边都用 `len(text.splitlines())`，不许一个用 `count("\n")+1`、一个用 `splitlines()`。超出部分进 spill，`truncated=true` + `spill_path`。旧文案里的 50 KB / 48 000 字符预算**删除**——它们会让 host 以 `output_too_large` 拒绝（`max_value_bytes=40960`）。

**40960 适配算法（顺序固定，不许"先序列化再看 host 拒"）**：

1. 先按方向截到 `MAX_TEXT_LINES=2000` 行且 `MAX_TEXT_BYTES=32768` 字节：`read`/`read_file`/`get_file_tree`/`ls`/`find`/`grep`/`file_search`/`edit` 取 **head**，`bash` 取 **tail**（尾部才是最近输出）。
2. 再循环缩短，直到 `len(compact_json(value)) <= MAX_VALUE_BYTES - SPILL_RESERVE`：`MAX_VALUE_BYTES=40960`、`SPILL_RESERVE=128`（覆盖 `truncated` 与 `spill_path` 的键值/转义开销）。每轮按剩余比例砍 `text`（至少砍 1 行或 64 字节），**重新用 canonical 编码器量整个 value**，最多 64 轮；收敛后 `truncated=true` + 合法 `spill_path`。
3. 只有第 2 步收敛后才写 spill（全文、NUL-free）；spill 失败 → exit 3 `spill_write_failed`，不返回半截。
4. `MAX_VALUE_BYTES` 管**工具返回**，`MAX_SAFE_ARGS_BYTES` 管**模型请求参数**，两者不是同一个数、也不同源：前者是 host 的硬预算常量，后者是 §4.2 的单来源常量，M5 实测后回填；`None` 时所有文案不写数字。

**UTF-8**：文件读取遇到非法 UTF-8 → `not_utf8`（或二进制 → `binary_file`）；`bash` 输出用 `errors="replace"` 转成合法 UTF-8，绝不把孤立代理项塞进 JSON。

---

## 5. 一次 turn 的数据流

```text
Chainlit on_message
  → hub 入队（busy 则 steer）
  → 提交给专用单线程 executor（不是 `asyncio.to_thread`）
      轮隙：清 inbox（cancel/steer/respond）
      → worker.run_once(scope)
          → claim model_call / tool_call
          → DeepSeekAdapter.build(effect, history, pins)
              history 来自 journal（worker._history）
              pins 来自 host_run_pins（requires 解析结果）
          → send（stream:false，一次完整响应）
          → interpret → settle → v24.advance
          → 下一个 effect 被 publish（tool children 或 continuation）
      → host_run_effects 增量读（cursor = 上页最后一条的 (created_at, effect_id)）
      → 新 effect：终态直接发，非终态进 active
      → active: host_effect(id) 刷新 → 终态发一次并移出
      → render_effect → StepRecord
      → loop.call_soon_threadsafe → cl.Step.send()
  终止：terminal / waiting / stopped / stalled
```

关键点：**模型看到的工具定义完全由 live run pins 决定**。装机 = fiber `on` + `start.requires` 列出 key；`replay_class`/`concurrency` 不参与。`start` 的 `input.messages` 是技能块与历史块的唯一注入点；`continuation`/`steer`/`respond` 都走 journal history，不再读 input。

---

## 6. 验证

### 6.1 主门：`v24/ui/test_ui_gate.py`

```bash
uv run python v24/ui/test_ui_gate.py
```

- 退出码 0 = 通过；末行 `[passed] v24 UI gate; steps=<n>; effects=<m>; artifacts=2; families=2`。
- 1 = 失败；2 = 环境不该跑（缺 psycopg2 等）。
- **隔离**：gate 跑在**自己的 disposable 数据库**（`s11` 式临时库）与 `tempfile.mkdtemp()` 下的 journal/workspace/spawn/spill 目录上；workspace 里先写一个固定的 `README.md`（含 `v24` 字样），否则 `read`/`file_search` 会变成错误 step，10 行序列对不上，**绝不复用 `agent_v24_ui` 或 `.uidata/`**；`finally` 里恢复被改的 artifact 字节、`V24_WORKSPACE_ROOT`/`V24_UI_*` 与其他环境变量，并删临时目录。
- 用 `plugin_fixtures.ScriptedTransport` + `model_adapter(script)`；脚本固定为：
  1. `tool_reply("call_1", "read", {"path": "README.md", "limit": 5})`
  2. `tool_reply("call_2", "file_search", {"pattern": "v24", "mode": "content", "max_results": 3})`
  3. `final_reply("done")`

断言 step 序列（name, type）**精确等于**：

```text
install · pi_tools          run
install · rp_tools          run
run · started               run
generating                  llm
model · tools (1)           llm
tool · read                 tool
model · tools (1)           llm
tool · file_search          tool
model · final               llm
run · completed             run
```

`install` 前缀不是字面量，而是由 `families()` 按 catalog 顺序生成；M2 恰好两行。

不变量（每条显式断言）：

1. **无 socket**：`install_no_network()` 把 `socket.socket.connect` / `socket.create_connection` / `urllib.request.urlopen` 打成 `AssertionError`（照抄 `plugin_smoke.py`）。
2. **SQL 零改动**：`validate_manifest()` 与 `SQL_LOAD_ORDER` 一致；跑完 `v24` schema 恰好 10 张表、零视图、零扩展。
3. **scripted transport 恰好耗尽**：`transport.script == []` 且 `len(transport.calls) == 3`；每个请求 `model == "deepseek-flash"`、`stream is False`、无 `tool_choice` 键、无 `OPENAI_API_URI` 痕迹。
4. **journal 闭集未变**：六种事件类型；每条 `dispatch_started` 都有配对 `dispatch_finished`。
5. **run 达成 terminal**：`status == 'completed'`、`result.final_text == "done"`、`turn_no >= 3`。
6. **manifest/digest 三处对齐**（不经 `from_manifest`，A2）：断言 1（`plugin.manifest_digest == sha256(raw)`）只是**辅助**（同义反复）；**主断言**是对 `host_scope_installs(scope)` / `host_install_fibers(install_id)` **从 DB 回读**的每一行调 `lookup_install`，逐字段比对 `manifest_digest` / `artifact_digest` / `adapter_digest`，并对每个 provide 用 `pg_jsonb_text(descriptor)` 比对字节、复算 `descriptor_digest`；**每个 scope 的每个族都跑**，不是只跑第一个。负控制各跑一次（`finally` 恢复原字节）：artifact 改一字节 → `lookup_install` 返回空；manifest 的 `realm` 改一字符 → `AdapterNotFound`。
7. **共享区字节一致**：两个 artifact 的 `SHARED CORE` 区逐字节相等；每个文件恰好一段；共享区里的 `canonical_json` 与 `v24.host.canonical.compact_json` 在 12 组值上逐字节相同（含非 ASCII 键、控制字符、嵌套；否则 40960 预算会漂移）。
8. **descriptor 合法**：每个 provide 的 `set(tool) == TOOL_KEYS` 九键；取值在 `LIMIT_RANGES`/`CONCURRENCY`/`REPLAY_CLASSES`/`ANNOTATION_KEYS` 内；`read_only`/`parallel` 的跨字段规则成立（用 `validate_descriptor` + 一份**独立**的词表断言，不只信 host）。
9. **pin 分层**：`V24_UI_TOOLSET=read` 时 `host_run_pins` 的 key 集合 == `read` toolset ∩ 当前 catalog（M2 为 `{read,file_search}`，M4 为 7 个只读 key）；当前 catalog 里没有的 `write`/`edit`/`bash` 不在集合里，也不出现在 `build()` 产出的 `body.tools` 里。另设一个**独立负例 run**（不放进主序列）：脚本强制调用一个未 pin 的 key → 在 SQL 层 `invalid_outcome`（`48_loop.sql:1116-1126`），**没有 tool_call effect、没有子进程**。
10. **敏感路径拒绝**：`read`/`file_search` 对 `.env`、`a.pem`、`id_rsa`、`.git/config`、`.uidata/x` → `path_excluded`；不存在的路径也先过栅栏，不能用来探测存在性（M4 再把 `write`/`grep`/`find`/`ls`/`read_file` 纳入）。
11. **spill 可经挂载读回**：构造超限 `read` 输出（M4 再加 `bash`）→ `truncated:true` + `.v24/spill/<32hex>.txt`；用 `read` **分页**读回（每页 ≤2000 行/32 KiB，拼起来与 spill 文件逐字节相同）；直接 `read .uidata/spill/<id>.txt` → `path_excluded`。
12. **增量时间线 == 全量**：每轮记录增量视图，末尾从 `(NULL,NULL)` 全量回放一次；两个 `effect_id → 终态记录` 映射相等；`finalized` 无重复。
13. **旧的 claimed effect 结算不漏报**：用 `HostWorker(..., crash_after='started', default_lease_ms=1)` 造一个"发现时已 claimed、之后才终态"的 effect（`worker.py:86-96`；`s13/test_lifecycle.py:430-443` 同手法），断言它进 active 且终态恰好发一次。
14. **漂移检测**：改一个 SQL 文件的字节 → `schema_drift` 退出 2；改 `loaded.json` 的 `database_oid`/`sql_manifest_digest` → 同样；删一张表 → `db_fingerprint` 漂移。
15. **schema 与跨字段两层分别断言**：未知键在 host 的 `output_check` 层 → `invalid_tool_output`（`plugins.py:200-206` 把 `InstanceError` 归一成该码）；`truncated=false + spill_path≠""` 能过 schema、在 page 层 → `invalid_tool_output`。`exit_code+status` **没有**任何真实工具 schema 同时允许，host 路径到不了 page，故只在 §12.9 的 renderer/page 单测里覆盖——不要为了它伪造一个宽松 schema 的工具。
16. **工具文本 == 模型文本（逐字节，UI 不二次截断）**：`tool_call` 的 `succeeded`/`failed` step output == `join_content(outcome.body.result.output.content)`；`unknown` 的 output == host `reason`；**大文本场景**见下（远超说明文本帽也必须逐字节相同）。
17. **子进程环境**：artifact 看到的 `V24_WORKSPACE_ROOT` == `ApprovedPlugin.workspace_root`（即使 gate 进程里另设了一个假值）；环境里没有 `DEEPSEEK_API_KEY`/`OPENAI_API_KEY`/`PG*`。
18. **无凭据泄漏**：所有 step output 拼起来不含 `Authorization` / `Bearer ` / `postgres://`。
19. **技能块形状**：`<available_skills>` 只有 name/description/location；`.v24/skills/<name>/SKILL.md` 可读；`ls('.')` **不出现** `.v24`（虚拟挂载不是真实目录）。
20. **apply_edits 模式冲突**：同时给 `rewrite` 与 `edits` → artifact exit 3 `mode_conflict`（host 归一成 tool failure，不是 CLI 退出码）；全部旧文本未命中 → artifact exit 0 + success value `status=failed`。
21. **bash 非零退出**：`sh -c 'exit 2'` → `status ok`、`value.exit_code == 2`、text 含 `Command exited with code 2`；**不是** failure 帧。
22. **无第 11 张表**：全量 SQL 跑完后 catalog 仍是十张表。
23. **NUL durable 链路干净**：`bash` 执行 `printf 'a\0b'` → effect **`succeeded`**（不是 `unknown`、不是失败帧），`value.text` 含 `a\ufffdb` 且**不含 U+0000**，`exit_code == 0`；随后 `host_effect(effect_id)` 能回读完整 outcome（jsonb 无 SQL 异常），run 继续到 terminal。这条证明的不是 renderer，而是**结算链路**。
24. **跨进程 rehydrate**：runtime#1 装机 + `start` + 跑到 `running`/`waiting` → `close()`（**不** close scope）→ 新 runtime#2 → `rehydrate(scope, realm, workspace_root, toolset)` → `/resume` 同一 run 继续到 terminal；断言 `host_scope_installs(scope)` 行数与 `install_id` 不变（没有第二次 install）、`host_run_pins` 集合不变；**"同 scope 随后还能再 `start` 一次"只在 M1 selftest 已证实该行为时才断言**，否则只断言前两条，并按 §10 退回"每轮新 scope"、记入 ledger。

不变量按里程碑分配（**不是**全部在 M2 通过）：

| 不变量 | 落点 |
|---|---|
| 1–8、16–18、22 | M2 |
| 9（pin 分层） | M2 断言 `{read,file_search}` 与 `read` toolset；M4 断言 `exec` 的 11 个 |
| 10（敏感路径） | M2 用 `read`/`file_search`；M4 覆盖其余 5 个文件工具 |
| 11（spill） | M2 用 `read` 的截断；M4 补 `bash` 与其余 |
| 12–13（时间线性质） | M2 |
| 14（漂移） | M1（`--status`），M2 纳入 gate |
| 15（两层校验） | M2（page 层）；M4（11 个 tools 的 schema 层全覆盖） |
| 19（技能挂载） | M4 |
| 20（apply_edits） | M4 |
| 21（bash 非零退出） | M4（M2 的 catalog 里没有 `bash`；W9 只覆盖 renderer 语义） |
| 23（NUL durable） | M4（需要 `bash`） |
| 24（跨进程 rehydrate） | M3 |
| catalog == 7/4、key 集合正确 | M4 |

**M4 追加两个独立场景**（不破坏主场景的精确 step 序列）：

- (a) 技能加载：脚本里加一次 `read` 读 `.v24/skills/repo-recon/SKILL.md`，断言读到 frontmatter，证明虚拟挂载可读；
- (b) 同一个 run 里 `exec` toolset 的全部 key 都被 pinned（11 个）。

**大文本场景（独立 run，M2 起）**：workspace 预置 `long.txt`（3001 个 ASCII 字符），脚本 `read {"path":"long.txt"}` → 断言该 step output 与 `build()` 产出的 tool message `content` **逐字节相同**、长度 >2000、且不含 `[truncated`；同场景再断言 `model · tools (n)` 的 args 摘要仍受 §4.4 的说明文本帽约束、`run · …` 说明文本同样受限——证明帽子还在，只是不落在 tool step 上。

**交互场景（独立 run，M2 起，用 `ScriptedUiAdapter`）**：脚本先返回 `interaction` → 断言 `status == 'waiting'`、`interaction.payload` 可读、出现 `run · waiting`；空回答 → 仍 waiting，不调 `respond`；`{"text":"ok"}` → 恢复并跑到终止；token-0 的 respond → 内核转 budget seal，UI 显示对应终止态而不是"完成"。**不要**用 `plugin_fixtures.model_adapter` 构造该场景：真实 `DeepSeekAdapter.interpret` 不产出 `interaction`（§2.4）。

**帧与输出形状（gate 必断言）**：v2 成功帧是 `{"ok":true,"v":2,"result":{"value":…,"meta":{}}}`，失败帧是 `{"ok":false,"v":2,"error":{"code","message"}}`，host 做唯一一次 decode（`line_json.py:199-245`）。失败帧的 `message` 不得含绝对路径，否则整帧被判 `bad_frame` → `unknown`。技能 frontmatter 校验：`name` 匹配 `^[a-z0-9-]{1,64}$`、`description` 非空且 ≤1024，违反即 gate 失败。

M1 的端到端证明走 `uv run python -m v24.ui.control --selftest`：不依赖 `render.py`，直接断言 durable effect 与 run projection，并打印实测 tokens 预算、`build()` 产出的 `body.tools` 名字、同 scope 二次 `start` 的结果；假 adapter 从 `v24/ui/fake.py` import（§4.3），`fake.py` 因此属 M1 文件。

### 6.2 opt-in 真实 provider

```bash
cd v24/ui && DEEPSEEK_API_KEY=... V24_UI_MODE=real V24_UI_WORKSPACE_ROOT=/abs/scratch \
  uv run chainlit run app.py --host 127.0.0.1 --port 8000 --headless
```

纪律照抄 `v24/host/smoke.py`：

- 无 key → `credentials_absent`、退出 2，**不构造 adapter、不开数据库事务**。
- `preflight()` 在 adapter 构造后、任何 DB 事务打开前。
- 失败保留 journal 不删。
- summary 不出现 key/Authorization/prompt/content/reasoning。
- **不是 gate，不是合运行时证明**。

`chainlit run` 只接受它自己的 `--host/--port/--headless` 等参数；**不要**给 app 传 `--root`（app 只读 `V24_UI_WORKSPACE_ROOT`）。`--root` 只属于 `python -m v24.ui.env`。

### 6.3 人工清单（M3）

1. 起页 → 页脚显示 FAKE、db 名、workspace 根、toolset、scope 短 id、resume token。
2. 发一条消息 → 依次出现 `install · pi_tools`、`install · rp_tools`、`run · started`、`generating`、`model · tools`、`tool · …`、`model · final`、`run · completed`。
3. `/tools` 列出当前 toolset 的 key；`/skills` 打印技能块。
4. busy 时发普通文本 → 变成 steer，且时间线上有对应说明。
5. `/cancel` → 收到"已请求停止"，最终状态是 `cancelled`（迟到结算不编造）。
6. 刷新页面 → 新 conversation；用 `/resume <旧 run_id> <旧 token>` → 历史 step 重放；用错 token 或别的 run → `not_found_or_denied`。
7. fake 模式下，发一条含 `interaction` 的消息 → 出现 `run · waiting` 与提问 → 回答后继续；不回答则一直 waiting。（real 模式不提供该流程，见 §2.4 与 W13。）
8. `/close` → 依次出现收敛、`off`/`dispose`、close 的说明；再对该 run `/resume` → `not_found_or_denied`。

---

## 7. 文件影响

### 7.1 W9（先做，§12）

```text
v24/host/renderers.py                    # 修改：新增 _text + 第 4 条 _BUILTIN_SPECS
v24/host/tool_pages.py                   # 修改：TEXT_PAGE_CONTRACTS + validate_page 分派
v24/s13/test_renderers.py                # 修改：计数 3→4、id 集合改四 id 并集、加载 text_plain_v1.json、摘要追加
v24/s13/test_pages.py                    # 修改：一行 import；两行 RENDERERS 集合相等 → 与 TEXT_PAGE_CONTRACTS 求并集
v24/s13/vectors/text_plain_v1.json       # 新增：正例/反例基线，W9 唯一新向量文件
v24/s13/README.md                        # 修改：gate 索引与合同描述（收尾工件）
docs/reviews/v24-tool-plugin-abi-w9-text-plain-2026-11-02.md   # 新增：W9 记录
docs/reviews/v24-conformance-matrix-2026-10-23.md               # 修改：追加 W9 节（收尾工件）
```

**零 diff（git diff 必须为空）**：`v24/s13/vectors/renderers.json`、`v24/s13/vectors/design_conformance.json`、`v24/s13/test_contracts.py`、`v24/s13/test_vectors.py`、`docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md`。

### 7.2 UI（M1–M5）

```text
v24/ui/__init__.py                 # 空包标记，不 import 任何东西
v24/ui/env.py
v24/ui/migrations.py
v24/ui/catalog.py
v24/ui/control.py
v24/ui/render.py
v24/ui/sessions.py
v24/ui/fake.py
v24/ui/app.py
v24/ui/pyproject.toml
v24/ui/README.md
v24/ui/test_ui_gate.py
v24/ui/plugins/pi_tools.py
v24/ui/plugins/rp_tools.py
v24/ui/skills/repo-recon/SKILL.md
v24/ui/skills/surgical-edit/SKILL.md
```

修改：`.gitignore`（加 `/.uidata/`）；`AGENTS.md`（分支例外 + 第四个真实 socket 入口）；新增 `docs/reviews/v24-ui-deviation-ledger-2026-11-01.md`、`docs/reviews/v24-ui-conformance-matrix-2026-11-01.md`。

### 7.3 硬边界

- **W9 之外**：`v24/load.py`、`v24/sql/*`、`v24/host/*`（除 §7.1 列出的文件）、`v24/s1/*`、`v24/s2/*`、`v24/s4/README.md`、`v24/s11/*`、`v24/s13/*`（除 §7.1 的四个文件与新向量）、`v24/s13/vectors/renderers.json`、`v24/s13/test_contracts.py`、`v24/s13/test_vectors.py`、`v24/s13/test_tools.py`、`v24/s13/capture_vectors.py`、`docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md`、根 `pyproject.toml`、`server.py`、`demo_v13/**`、`pi/**`、`repoprompt-ce/**` —— **一个字节都不改**。
- **设计文档不能改**：`test_contracts.py:10` 的 `DESIGN_SHA256` 会立刻失败。
- **不能跑 `capture_vectors.py`**：它会重写全部冻结向量。

---

## 8. 错误与边界情形（逐条要有归宿）

1. `.uidata/lock` 被占 → 退出 3，消息带 pid 与路径；不起 worker、不连库。
2. 库未初始化 → 退出 2，提示 `--init`。
3. `loaded.json`/指纹不一致 → 退出 2 `schema_drift`；host 版本与 `w9_required` 不匹配 → `migration_required`；两者都提示 `--reset --yes` 或 `--migrate`。
4. `--migrate` 无登记路径 → `migration_unsupported` 退出 2，不假装迁移。
5. real 模式无 key → `credentials_absent` 退出 2，在任何 DB 事务之前。
6. `lease_insufficient` → `default_lease_ms` 设到 `max(timeout_ms)+10000`；仍发生则上屏 `model · unknown` 并停，**不重试**（S4 不做第二次尝试）。
7. `interaction` 到达 → `status='waiting'`，`cl.AskUserMessage` 取回答，`respond(run, interaction_id, response, key)`——**generation 由 runtime 内部读**（§4.3 的 verb 契约，调用方不传）；空回答 → 继续等；token-0 的 respond 会被内核转为 budget seal，UI 要能显示。
8. `pending_steer` 被覆盖 → 上屏 `run · steer superseded`。**不能**靠 `pending_steer.generation < driving_generation` 判断：每次 steer 都把 pending 的 generation 设成 `old+1`、同时把 driving 也推到同一个值（`40_interpreters.sql:916-923`），所以该谓词永远是 false。必须由 `AgentRuntime` 本地记录 `(seq, text, generation_at_submit)`，当一条更新的 steer 在旧指令被消费前落地时，把旧条目标 superseded。
9. `blocked_unknown` → 上屏 reason，**不自动重试**；`/resume` 让人看现场（只回放，不重试）。
10. `unknown_tool_name` / `zero_tool_calls` / `too_many_tool_calls` → `model · failed` + reason，run 终止。
11. batch barrier：一次 model 可能给 ≤16 个 tool children；渲染层不许假设"一模型一工具"，step 名带 count 或 ordinal，所有 child 都进 `active`。
12. 64 行分页：`host_run_effects` 的 `next_cursor` 在最后一面是 `NULL`；cursor 必须由调用方记住最后一条 item 的 `(created_at, effect_id)`。`host_effect` 的刷新也按 64 条/轮上限控制。
13. `output_too_large`：artifact 先按 32 KiB/2000 行/40960 字节截断并 spill；host 的 `max_value_bytes` 是最后一道。两层都可能触发，报错文本不同（artifact `output_too_large` exit 3；host `output_too_large` failure）。
14. `spill_write_failed`：spill 落盘失败时**不返回**截断文本，直接 exit 3，避免给出一个读不回的 `spill_path`。
15. 刷新 → 新 conversation；`/resume <run_id> <token>` 是唯一回接路径；旧 conversation 的 bindings 不会被 `on_chat_end` 销毁。
16. 两个 Chainlit 进程 → 第二个 `already_running` 退出 3。
17. `apply_edits` 模式冲突 → `mode_conflict`（多种模式）或 `invalid_mode`（一种都没有），artifact exit 3；全部未命中 → exit 0 `status=failed`。
18. `V24_WORKSPACE_ROOT` 缺失/非目录 → 所有 artifact `root_unavailable` fail closed；这是预期行为，不是 bug。
19. `V24_SPILL_ROOT` 缺失 → artifact 不截断，`output_too_large` 或 `spill_write_failed`，不返回无主的 `spill_path`。
20. 错误 `message` 含绝对路径/NUL/`Traceback (` → 整帧 `bad_frame` → `unknown`。artifact 的错误文案只用相对路径。
21. 会话文件损坏 → 改名 `sessions.json.corrupt-<ts>`，起新 conversation，横幅提示；`turns.jsonl` 坏行跳过并计数，不崩。
22. 绑定 run 的 `catalog_digest` 与当前 catalog 不一致 → `/resume` 允许回放，拒绝继续 drive/respond，reason `catalog_changed`。
23. `/close` 未收敛 → `close_incomplete`，不 close scope，保留可恢复状态。
24. 同 scope 二次 `start` 若失败 → M1 记录证据、M3 不启用"同 scope 多 run"，改为每轮新 scope + 新 binding（显式回退并写 ledger，不静默）。
25. **NUL 文本 → 已知工具失败，不是结算崩溃**：artifact 出口保证 `text` 无 U+0000（文件内容直读 → `binary_file`；`grep`/`file_search` 跳过含 NUL 文件并计数；`bash` 替换 U+FFFD）；万一漏到 host，page 的 `_check_text` → `invalid_tool_output`、renderer 的 `_text` → `render_failed`。任何路径都不允许 NUL 进 `v24.advance` 的 jsonb——PostgreSQL 拒绝 `\u0000`，那会是 SQL 异常而不是 effect 失败（§4.7、§12.3、§12.4、§6.1-23）。

---

## 9. 分支、提交与 AGENTS.md 偏差

### 9.1 执行顺序（不可颠倒）

```text
切分支 v24/ui-chainlit
→ W9 实现 + 跑 s13 全部门
→ W9 全绿（否则不开始 M1）
→ 实现 M<n> + 跑门
→ 门全绿
→ 更新收尾工件（ledger / matrix / README）
→ git add <逐路径>
→ git commit
（不 push）
```

- 每里程碑恰好一次提交；**不把多个里程碑积压成一次提交**。
- **不 `git add -A` / `git add .`**；按路径逐项加，提交前 `git status` 复查暂存区。
- 不提交 `.uidata/`、journal、spawn log、`.env`、任何含 key 的文件。
- 不用 `--no-verify`，不跳过 hook。
- `main` 零改动；不 force-push 任何东西。

### 9.2 显式 deviation（写进 ledger，不粉饰）

- **D-UI-1 分支**：AGENTS.md 要求"里程碑完成后 MUST 立即提交并推送到 `main`"。本任务按用户要求改用专用分支 `v24/ui-chainlit`，**只 commit 不 push**，`main` 零改动。`git add -A`、force-push、`--no-verify` 的禁令**继续有效**。
- **D-UI-2 第四个真实 socket 入口**：新增 `v24/ui/app.py` 的 `V24_UI_MODE=real` 路径；必须继承同一纪律——不是 gate、不是合运行时证明，无 key 时 `credentials_absent` 退出 2 且不构造 adapter 不开事务，调用当时不得有打开的 DB 事务，不打印 prompt/content/reasoning/key。
- **D-UI-3 已接受风险**：`bash` 的禁闭是运维性（scratch 根）而非强制性；路径栅栏与敏感路径拒绝是模型面约束，不是安全边界；不做 per-call approval，因为 v24 没有工具审批原语。
- **D-UI-4 兼容子集**：`pi_tools` 的 `grep`/`find` 是 ripgrep/fd 的兼容子集而非字节等价物（标准库限制）。
- **D-UI-5 冻结 ABI 的加性扩展**：W9 修改 `v24/host/renderers.py` 与 `tool_pages.py`，是对冻结 ABI 的一次**显式加性扩展**。约束是：既有 3 个 renderer 的 id/digest/golden 一个字节不动、`renderers.json` 与 71 例 W1 清单不动、`design_conformance.json`/`test_contracts.py`/`test_vectors.py` 零 diff、设计文档 SHA 不动；只新增 `v24.text.plain` 与它的向量（新 manifest 例只落 `text_plain_v1.json`）。这是本计划唯一的 host 改动，越界即回退重规划。断言改动是同一件事的三面：`test_renderers.py` 把计数 3 改成 4、id 集合改四 id 并集；`tool_pages.py` 的 import 断言把"renderer 集合 == 3 条合同"改成"两张合同的并集"（并让 `validate_page` 先查 BUILTIN 再查 TEXT）；`test_pages.py` 做同样的并集。

`docs/reviews/v24-ui-conformance-matrix-2026-11-01.md` 覆盖：§2.5 十一条约束逐条的实现位置、§3 全部 decision 的落点、每条 gate 命令与退出码、W9 的加性证据。

---

## 10. 里程碑

| # | Goal | Done when | Key files | Deps | Size |
|---|---|---|---|---|---|
| **W9** | 协议扩展：`v24.text.plain` v1（§12） | §12.9 的 13 条 s13 gate 全绿；旧 3 个 renderer 的 golden/digest 逐字节不变；`renderers.json`/`design_conformance.json`/`test_contracts.py`/`test_vectors.py` 零 diff；新向量表全过。Node 缺失时 `--node` 为 `[SKIP]`，ledger 记 `toolchain absent`，W9 记为 **`passed-with-unverified`**，不冒充通过。**W9 未过，不开始 M1** | `v24/host/{renderers,tool_pages}.py`、`v24/s13/{test_renderers,test_pages}.py`、`vectors/text_plain_v1.json`、W9 记录 | 无 | L |
| **M1** | 持久环境 + 控制面 + 首个真实工具闭环（scripted，无 Chainlit） | `python -m v24.ui.env --init` 建出十表库并写 `loaded.json`；`--status` 可用；`--migrate` 以 `migration_unsupported` 退出 2（零迁移，不假装成功）；`--reset --yes` 可用；漂移检测按预期退出 2；`python -m v24.ui.control --selftest` 退出 0（adapter 从 `fake.py` import），打印完整 effect 时间线，`host_run_pins` 恰好 `{read}`，`build()` 的 `body.tools` 名字恰为 `{"read"}`，tokens 预算扣减单调，**断言 3 对 DB 回读的 install 行执行**，**同 scope 二次 `start` 的实测结果写进 README** | `v24/ui/{__init__,env,migrations,catalog,control,fake}.py`、`plugins/pi_tools.py`（只含 `read`）、`.gitignore`、`README.md` | W9 | L |
| **M2** | 第二个工具 + 渲染映射 + UI 门；A4 的第一次真正检验 | `uv run python v24/ui/test_ui_gate.py` 退出 0；§6.1 的 10 行 step 序列精确；pin 集合恰为 `{read, file_search}`（2 requires / 1 个非 owner 提供者）；时间线性质（12–13）、两层校验（15）、大文本逐字节（16）通过；`text.plain` 在 `read`/`file_search` 上的 W9 语义在 gate 中复验 | `plugins/rp_tools.py`（只含 `file_search`）、`render.py`、`fake.py`（扩展 big-text/interaction 脚本）、`test_ui_gate.py` | M1 | L |
| **M3** | Chainlit 端到端（fake）+ 持久会话/历史/toolset + 跨进程恢复 | §6.3 人工 8 项全过；M2 门仍绿；刷新后 `/resume <run_id> <token>` 可回放；`/close` 顺序正确；**丢弃 runtime#1 → runtime#2 `rehydrate` → `/resume` 同一 `running`/`waiting` run 可继续，install 不重复，同 scope 可再 `start`**（不变量 24） | `app.py`、`sessions.py`、`pyproject.toml`、`README.md` | M1（同 scope 二次 start 证据） | L |
| **M4** | 补齐 11 工具 + 技能挂载 + 安全默认 + 完整 gate | 同一 run 里 `exec` toolset 的 11 个 key 全部 pinned；每族至少调用一次；`.v24/skills/...` 可读且 `ls('.')` 无 `.v24`；catalog 恰好 7/4；敏感路径/尺寸/共享区/环境隔离不变量全过；族级 artifact 实测尺寸写进 gate | 两个 artifact 补齐、两个 `SKILL.md`、`test_ui_gate.py` | M3 | L |
| **M5** | 真实 provider 入口 + 收尾工件 | `DEEPSEEK_API_KEY` 手动跑通；ledger/matrix 落盘；AGENTS.md 两处增补；**实测 `finish_length` 的出现条件、把 `MAX_SAFE_ARGS_BYTES` 常量回填并同步 README/页脚/system prompt** | `AGENTS.md`、两个 reviews、`README.md` | M4 | M |

W9 与 M1–M2 都**不需要真实 key**；M3–M4 用 `V24_UI_MODE=fake` 的 scripted transport，页面可完整走一遍。

**M2 是 owner fiber 决策的判定点**：若 `host_run_pins` 只有 `{read}` 或 `start` 拒绝多 requires，**M2 失败、保留诊断、停下来重新设计**（备选 C 是显式重做，不是自动回退）。不要为了过门把 requires 降成 1 个。

**M1 的"同 scope 二次 start"是 M3 的入场证据，不是 M1 的通过条件**：实测失败时 M1 仍可过，但 M3 不得启用"同 scope 多 run"，退回每轮新 scope + 新 binding，并在 ledger 记录。

---

## 11. 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| W9 误动冻结基线 | 3 个 renderer 的 digest 变化 → B0/W 系列全红 | `_GOLDEN` 前三条与 `_BUILTIN_SPECS` 前三条**不编辑**；`renderers.json`/`test_contracts.py`/设计文档零 diff；s13 全量回归；ledger 记 D-UI-5 |
| 族级 artifact 体积 | 单文件 1000–3000 行，共享区复制后漂移 | `SHARED CORE` 标记 + gate 逐字节比较；`wc -l -c` 上限钉死；只在边界内加工具 |
| `text.plain` 校验弱于专用 renderer | 结构上无法验证 text 与 value 的对应关系（没有结构） | 逐工具闭合 `output_schema` + page 只做关系/尺寸 + artifact 侧构造 + 全量向量；风险如实写进 README |
| 漂移假阳性 | 无辜改动被 `schema_drift` 拦住 | 指纹只含函数名/签名/结果/prosrc 与表列名/类型/notnull/default，不含 OID/owner/ACL；`--status` 打印**逐项差异**；`--reset --yes` 是逃生门；`--init` 绝不静默祝福 |
| 会话文件损坏 | 刷新后接不回历史 | 原子写（tmp+fsync+rename+fsync(dir)）；坏文件改名保留；`turns.jsonl` 坏行跳过计数；gate 覆盖损坏场景 |
| 512 completion 上限（含推理） | 超过 512 token 时 provider 给 `finish_reason="length"` → `_unknown("finish_length")` → **整轮失败**；不是把回答或参数截短，也不会落成假的 final | 参数小步（`write.append`）；技能教小步；页脚/README 写"超限本轮失败"；`MAX_SAFE_ARGS_BYTES` 单一常量；M5 实测回填（§13 W12） |
| `bash` 非强制沙箱 | 可写出工作区 | 默认 scratch 根 + 审计 + README 显式风险声明；指向活仓库默认 `read` |
| 两个 UI 进程 | 抢 claim / 公平游标互饿 | `.uidata/lock` 退出 3 |
| artifact 改动 | digest 失配 → `AdapterNotFound` | `require_artifact` 每次 spawn 复核；gate 逐条断言；改完重建 catalog |
| manifest 的 `\x` 表示 | host 要 bare hex、SQL 要 `\x` 前缀，同一串字节满足不了两边 | A2：manifest JSON 用 `"\\x"+bare`，`ApprovedPlugin` 直接构造；gate 三处断言（§6.1-6） |
| per-scope registry 替换 | 交错驱动两个 scope 时把 A 的 install 查成 B 的 entry | registry 只在专用线程、`run_once` 之外整体替换，且包含所有 live scope 的条目；M3 用两个 scope 交错装/调一次 |
| `pending_steer` latest-wins | 用户以为两条都送达 | `run · steer superseded` step |
| `blocked_unknown` | 无自动恢复 | 上屏 reason + `/resume` 只回放，不重试 |
| 真实 provider 的 `interaction` 不可达 | `waiting`/ask-user 只在 fake 模式与 gate 里可用 | §2.4 写明；W13 跟踪 provider 合同；real 模式遇到 `waiting` 只提示 `/cancel`，不假装能答 |
| owner fiber 解析 | requires 不生效 → 工具不可见 | 按里程碑断言 pin 集合；失败即停并显式重做（A4），不自动回退 |
| 会话/scope 累积 | 每次刷新新建 scope，install 与 slot 增长 | 32 conversation 上限 + 只回收全 terminal 的会话；`/close` 与 `--reset` 是显式清理 |

无 SQL schema migration，无对既有 v24 调用方的兼容性变化。`--reset --yes` 可移除持久库。

> 待实测（代码事实已核实，不再"待验证"）：**不触发 `finish_length` 的最大 tool-args 字节数**。验证办法：M5 用真实 provider 跑 10 次不同大小的 `write` 参数，记录第一次出现 `finish_length` 的边界，把保守值写进 `catalog.MAX_SAFE_ARGS_BYTES`，README/页脚/system prompt 全部从该常量渲染。常量仍为 `None` 时，**任何文案都不写具体数字**，技能只说"小步、以页脚常量为上限"。

---

## 12. W9：`v24.text.plain` v1（前置里程碑）

> **W9 未通过，不开始 UI 的 M1。** 它是 §10 的 M0 行，也是 §7.1 的唯一 host 改动。

### 12.1 目标与边界

- 新增一个**通用文本 renderer** `v24.text.plain`，version 1，projection 1。
- 11 个工具**全部**绑定它；不新增第二个 renderer。
- 现有 `v24.fs.read.text` / `v24.fs.list.text` / `v24.fs.search.text` 的 id、version、digest、21 条 embedded golden、3 个 manifest 字节**一个字节不动**。
- `value` 是**严格文本投影**，不是"任意 JSON 转字符串"：host 侧有闭合 `output_schema`，renderer 只做结构校验与原样返回。

### 12.2 `value` 合同（逐工具闭合 schema）

公共三键，`additionalProperties:false`，全部 required：

| 键 | 类型 | 约束 |
|---|---|---|
| `text` | string | 原样上屏；artifact 侧 ≤2000 行且 ≤32768 UTF-8 字节 |
| `truncated` | boolean | `true` 表示全文在 spill |
| `spill_path` | string | 未截断时必须为 `""`；截断时必须匹配 `\.v24/spill/[0-9a-f]{32}\.txt` |

仅 `bash` 额外 required：

| 键 | 类型 | 约束 |
|---|---|---|
| `exit_code` | integer | 0..255；**显式拒绝 bool 与 float**（`tool_schema.py:284-287,341-344` 的 `type(instance) is int`） |

仅 `apply_edits` 额外 required：

| 键 | 类型 | 约束 |
|---|---|---|
| `status` | string | 闭集 `success\|partial\|failed\|no_change` |

其余 9 个工具只有公共三键。`bash` 的 schema **不得**声明 `status`；`apply_edits` 的 schema **不得**声明 `exit_code`。两层分工：

- **schema 层**（host `output_check`）：拒绝未知键、缺 required、类型错、`exit_code` 越界；
- **page 层**（`validate_page`）：拒绝 `truncated`/`spill_path` 关系错、`exit_code` 与 `status` 同时出现、`text` 超行/超字节/含 U+0000、`spill_path` 命名空间/形状错；
- **renderer 层**（`_text`）：拒绝未知键、`exit_code` 与 `status` 同时出现、类型/范围/关系错（深度防御；host 流程里 schema/page 会先拒）。

示例（`bash`；`render.digest` 从 registry 读，**不写死**）：

```python
render = {"id": "v24.text.plain", "version": 1,
          "digest": RENDERERS.by_id("v24.text.plain", 1).ref.digest}

descriptor = {
    "v": 2,
    "tool": {
        "key": "bash",
        "description": "Run a shell command in the workspace root; "
                       "non-zero exit is a successful result with exit_code.",
        "parameters": {"type": "object", "additionalProperties": False,
                       "required": ["command"],
                       "properties": {"command": {"type": "string"},
                                      "timeout_ms": {"type": "integer",
                                                     "minimum": 1,
                                                     "maximum": 20000}}},
        "output_schema": {
            "type": "object", "additionalProperties": False,
            "required": ["text", "truncated", "spill_path", "exit_code"],
            "properties": {
                "text": {"type": "string"},
                "truncated": {"type": "boolean"},
                "spill_path": {"type": "string", "maxLength": 128},
                "exit_code": {"type": "integer", "minimum": 0, "maximum": 255},
            },
        },
        "render": render,
        "limits": {"timeout_ms": 20000, "max_args_bytes": 65536,
                   "max_value_bytes": 40960, "max_content_bytes": 41984,
                   "max_meta_bytes": 4096},
        "concurrency": "exclusive",
        "replay_class": "external",
        "annotations": {"read_only": False, "destructive": True,
                        "idempotent": False, "open_world": True},
    },
}
```

`apply_edits` 把 `exit_code` 换成 `"status": {"type": "string", "enum": [...]}`；其余 9 个工具去掉第四键。九键闭集由 `TOOL_KEYS` 断言（`descriptor.py:41-44`）。

### 12.3 渲染函数

```python
_TEXT_KEYS = frozenset({"text", "truncated", "spill_path", "exit_code", "status"})
_TEXT_STATUS = ("success", "partial", "failed", "no_change")

def _text(args, value):
    if type(value) is not dict or not set(value) <= _TEXT_KEYS:
        raise RendererError("render_failed")
    text = value.get("text")
    truncated = value.get("truncated")
    spill = value.get("spill_path")
    if not isinstance(text, str) or type(truncated) is not bool \
            or not isinstance(spill, str):
        raise RendererError("render_failed")
    if truncated is False and spill != "":
        raise RendererError("render_failed")
    if truncated is True and spill == "":
        raise RendererError("render_failed")
    if "exit_code" in value:
        code = value["exit_code"]
        if type(code) is not int or not 0 <= code <= 255:
            raise RendererError("render_failed")
    if "status" in value and value["status"] not in _TEXT_STATUS:
        raise RendererError("render_failed")
    if "exit_code" in value and "status" in value:
        raise RendererError("render_failed")
    if "\x00" in text:                      # jsonb 不接受 \u0000（见下）
        raise RendererError("render_failed")
    return [{"type": "text", "text": text}], {}
```

- **原样返回 `value["text"]`**：不 `str(value)`、不格式化、不补换行、不截断。
- 空字符串是合法 render（`read.empty_line` 已有先例）；`_validate_result` 要求恰好 1 个 text block、`meta` 是 `{}`。
- renderer 抛任何异常都会被 `RendererRegistry.render` 归一成 `render_failed`（`renderers.py:237-246`）；**孤立代理项**在 `compact_json(content)` 处失败 → `invalid_tool_content`（`renderers.py:189-195`）。两者都是 failure，不是 unknown。
- 渲染不读文件、不 stat：`spill_path` 的 symlink/regular-file 检查在 artifact 写入时与 UI 读回时做，**不在纯 renderer 里做**。
- **NUL 是反例，不是正例**：`_text` 拒绝含 U+0000 的 `text`。理由不是"渲染不好看"，而是 `v24.advance` 的 `outcome` 是 jsonb、PostgreSQL 不接受 `\u0000`；放过去会变成 SQL 异常（effect 卡在 claimed），而不是干净的 `render_failed`。`_check_safe_domain` 只查整数是否 safe、key 是否 str，**不查字符串内容**（`tool_pages.py:58-76`），所以这道拒必须在 `_text` 与 `_check_text` 各写一次。既有三个 renderer 的 NUL golden（`render.read.golden`/`render.search.golden` 里 `…\u0000😀` 的用例）**一个字节不动**——它们证明的是 host 编码器，不是 durable 结算，两者不能类比。

**新条目怎么填**：`_BUILTIN_SPECS` 第 4 项是
`("v24.text.plain", _text, _GOLDEN["text"], golden_digest(_GOLDEN["text"]), render_digest("v24.text.plain", 1, 1, _GOLDEN["text"]))`；
两个 hex 由函数**现算后粘回源码**，import 时的漂移检查会再验一次（`renderers.py:284-288`）。`_GOLDEN["text"]` 与 `text_plain_v1.json` 的 **9 个**正例必须同值（`id/args/value/content/meta` 五键），但一个是源码常量、一个是测试输入，**不能互相读取**——否则改向量表就能悄悄改 renderer 身份。反例（含 `text.plain.nul`）不进 `_GOLDEN`：golden 只定义"成功长什么样"。

### 12.4 尺寸预算

host 的处理顺序是：`args` 尺寸 → `parameters` schema → `lease` → invoke → **value 字节数** → `output_schema` → page → renderer → `content`/`meta` 预算（`plugins.py:137-236`）。因此下面两层都必须过，且**谁先拒是确定的**。

| 层 | 预算 | 触发 |
|---|---|---|
| artifact `text` | ≤2000 行且 ≤32768 UTF-8 字节 | 超出 → 截断 + spill + `truncated:true`（方向与 40960 适配循环见 §4.7） |
| host `value` | `len(compact_json(value)) ≤ 40960`（`max_value_bytes`） | 40961 → `output_too_large`（先于 schema/page） |
| page | `text` 行数 ≤`default_limit`(2000)、字节 ≤32768 | 超限 → `invalid_tool_output`（value 在预算内也照样拒） |
| host `content` | `len(compact_json(content)) ≤ 41984` | 理论不可达（content ≈ value + 27） |
| host `meta` | ≤4096 | `{}` → 2 |

32 KiB 是 `text` 的原始字节帽；**硬帽是序列化 value ≤40960**——控制字符多的文本会先撞后者（JSON 转义膨胀）。artifact 必须用与 host 相同的 canonical 编码器测长度，不能只数字符。

**page contract 的形状**（`PageContract(renderer_id, kind, default_limit)`，`tool_pages.py:36-47`）：

```python
MAX_TEXT_BYTES = 32768
TEXT_PAGE_CONTRACTS = {
    "v24.text.plain": PageContract("v24.text.plain", "text", 2000),
}
```

`validate_page` 的改动**只在查表与分派**：

```python
contract = (BUILTIN_PAGE_CONTRACTS.get(render.id)
            or TEXT_PAGE_CONTRACTS.get(render.id))
if contract is None:
    _fail()
try:
    RENDERERS.lookup(render)
except Exception:
    _fail()
if contract.kind == "text":
    _check_text(value, contract.default_limit)
    return
offset, limit = _check_args(args, contract)      # 原路径
...
```

`_check_text(value, limit)` 不看 `args`（`bash` 没有 `limit`，`apply_edits` 也没有），只查：

- 先要求 `type(value) is dict`（非 dict 直接 `_fail()`，别让 `.get` 抛 `AttributeError`）；
- `text` 是 `str`、`truncated` 是 `bool`、`spill_path` 是 `str`；
- **`"\x00" in text` → `_fail()`**：jsonb 不接受 `\u0000`，而 `_check_safe_domain` 只管整数与 key（不查字符串）；这条与 `_text` 的同名检查是深度防御的两层，谁都不能省。`text.plain.nul` 因此在 page 层是 `invalid_tool_output`；
- `len(text.splitlines()) <= limit`（=2000）且 `len(text.encode("utf-8")) <= MAX_TEXT_BYTES`（=32768）（与 artifact 同一算法；尾随换行不算新行，空串算 0 行）；`encode` 抛 `UnicodeEncodeError`（lone surrogate）→ `_fail()`——host 先跑 page 再跑 renderer，别让它变成未捕获异常；
- `truncated is False` → `spill_path == ""`；`truncated is True` → `re.fullmatch(r"\.v24/spill/[0-9a-f]{32}\.txt", spill_path)`；
- 允许 `exit_code` / `status` 作为额外键（schema 已闭集），但两者同时出现 → `_fail()`。

`_check_safe_domain(value)` 仍先跑（`exit_code` 是 0..255，安全；但它**不拒绝 U+0000**，NUL 由上面那条显式拒）。`test_pages.py:201` 的 `contracts=3` 与 limit 映射断言只覆盖 `BUILTIN_PAGE_CONTRACTS`，所以仍是 3；`TEXT_PAGE_CONTRACTS` 的 limit 由 `_check_text` 的常量断言，不进那张 map。

### 12.5 `bash`：非零退出是成功 value

- `subprocess` 正常返回、`returncode != 0` → **exit 0 成功帧**，`value.exit_code = returncode & 0xFF`，`text` 末尾追加一行 `Command exited with code N`（与输出之间恰好一个空行）；footer 计入 32 KiB 预算，先算 footer 再截断 body。
- 超时（进程组被杀）→ exit 3 `timeout`。
- 无法启动（`OSError`）→ exit 3 `io_error`。
- 合并 stdout+stderr，按 UTF-8 `errors="replace"` 解码。
- 这条**替换**旧计划的 `command_failed` 失败帧：非零退出不是协议失败，是命令结果；模型必须看到真实退出码才能继续推理。

### 12.6 spill

- 落 `<repo>/.uidata/spill/<uuid4().hex>.txt`；`V24_SPILL_ROOT` 指向它，artifact 把 `.v24/spill/` 虚拟映射过去。
- **先落盘再返回成功帧**：临时文件 → fsync → rename → fsync(dir)；失败 → exit 3 `spill_write_failed`，**不返回**带 `spill_path` 的截断文本。
- 路径只允许该命名空间：拒绝绝对路径、`..`、symlink、非 regular file。artifact 写时校验；UI 读回时用 `os.lstat` 再校验一次（`stat.S_ISREG` + `realpath` 在 `V24_SPILL_ROOT` 内）。
- 保留最近 **50 个或 50 MiB**，每次写入后按 mtime 从旧到新删除，直到两个上限都满足。
- spill 文件名用 uuid4 而非 effect_id：artifact 不该解析 reservation 格式；重复执行同一 effect 最多多留一个文件，由保留策略兜底。

### 12.7 允许改的文件（**仅**这些）

```text
v24/host/renderers.py          # 新增 _text、_GOLDEN["text"]、第 4 条 _BUILTIN_SPECS
v24/host/tool_pages.py         # 新增 TEXT_PAGE_CONTRACTS、_check_text、validate_page 分派、import 断言改并集
v24/s13/test_renderers.py      # 计数 3→4；id 集合改四 id 并集；加载 text_plain_v1.json
v24/s13/test_pages.py          # 一行 import；集合相等断言（第 203-204 行）→ 并集
v24/s13/vectors/text_plain_v1.json   # 新增，W9 唯一的新向量文件
```

**收尾工件（文档，不改任何断言）**：`v24/s13/README.md`、`docs/reviews/v24-tool-plugin-abi-w9-text-plain-2026-11-02.md`（新增，即 W9 记录）、`docs/reviews/v24-conformance-matrix-2026-10-23.md`（追加 W9 节）。

**禁止改**：`v24/sql/*`、`v24/host/registry.py`、`v24/host/descriptor.py`、`v24/host/plugins.py`、`v24/host/worker.py`、`v24/host/deepseek.py`、现有 renderer 的 id/digest、`v24/s13/vectors/renderers.json`、`v24/s13/vectors/design_conformance.json`、`v24/s13/test_contracts.py`、`v24/s13/test_vectors.py`、`v24/s13/test_tools.py`、`v24/s13/capture_vectors.py`、`docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md`。

**新 renderer 的向量只进 `text_plain_v1.json`**：`test_contracts.py:69` 是 `set(local) == REQUIRED[name]`（严格相等）、`:62` 是 `inventory == REQUIRED`、`:77` 是 `len(allcases) == 71`，所以往 `renderers.json` 追加一条会强制改 `test_contracts.py` 与 `design_conformance.json`——两者都在上面禁止改。`renderers.json` 连同 `render.read/list/search` 的 golden 与三个 `render.manifest.*`、`render.digest.provisional_values` **一个字节不动**；`render.manifest.text` 这类新条目由 `text_plain_v1.json` 承载（见 §12.9）。

**`test_renderers.py` 的 id 集合**：它在 `:65-67` 断言 `{entry.ref.id …}` 恰为三个旧 id。加了第 4 条后，改成**显式列出四个 id 的并集**（`{"v24.fs.read.text","v24.fs.list.text","v24.fs.search.text","v24.text.plain"}`），仍在该文件白名单内；**不要**改成从 `renderers.json` 读取——那会让测试依赖被冻结的向量表。

**为什么 page contract 放兄弟表，但两个文件仍必须改**：`test_pages.py:201` 断言 `BUILTIN_PAGE_CONTRACTS` 恰好是 3 个只读 renderer，`test_tools.py:1695` 断言 `len(...) == 3`；新增第 4 个 `TEXT_PAGE_CONTRACTS` 不会破坏这两个数。但有两处**无法靠兄弟表绕开**的相等断言：

1. `tool_pages.py:249-250` 在 **import 时**要求 `set(BUILTIN_PAGE_CONTRACTS) == {entry.ref.id for entry in RENDERERS.entries}`；第 4 个 renderer 一进 registry，`import v24.host.tool_pages` 就直接 `RuntimeError: page contract drift`，轮不到任何测试。
2. `test_pages.py:203-204` 有同一断言。

因此 `tool_pages.py` 的 `validate_page` 改成先查 `BUILTIN_PAGE_CONTRACTS` 再查 `TEXT_PAGE_CONTRACTS`，并把 import 断言改成两张表的并集；`test_pages.py` 的这两行改成：

```python
_CONTRACTS = set(BUILTIN_PAGE_CONTRACTS) | set(TEXT_PAGE_CONTRACTS)
assert {entry.ref.id for entry in RENDERERS.entries} == _CONTRACTS
```

这是**加强**（要求每个 renderer 在两张表里恰好有一条合同），不是放松；`contracts=3`、kind 映射、limit 映射三处断言一字不动。`test_tools.py` 完全不动，`BUILTIN_PAGE_CONTRACTS` 也仍是 3 条。

### 12.8 前置检查（全树，已执行）与 spike 顺序

**第一段：renderer id 不进 SQL。**

```bash
grep -rn "v24\.fs\.read\.text\|v24\.fs\.list\.text\|v24\.fs\.search\.text\|v24\.text\.plain" v24/sql/
# 零命中，exit 1
```

`v24/sql/` 里没有任何 renderer id，说明 renderer 只活在 host 层：**W9 不需要动 SQL**。若未来 grep 命中，**停下重新规划**，不要自动把 SQL 纳入白名单。

**第二段：全树枚举会因第 4 条 registry 而改变行为的点。** 前置检查从 `v24/sql/` 扩到 `v24/` 全树与 Node 相关文件：

```bash
grep -rn "RENDERERS\.entries\|len(RENDERERS\|len(renderers\.RENDERERS\|BUILTIN_PAGE_CONTRACTS" v24/
grep -rn "v24\.fs\." v24/ --include=*.py --include=*.json --include=*.md --include=*.js --include=*.ts
grep -rn "render\.manifest" v24/
grep -rn "test_contracts\|DESIGN_SHA256\|sha256_at_review" v24/ docs/
```

已核实的命中清单（W9 记录里逐条归档）：

| 命中 | 位置 | 处置 |
|---|---|---|
| `len(renderers.RENDERERS) == 3` | `v24/s13/test_renderers.py:63` | 白名单内，改 4 |
| `{entry.ref.id …} == {3 ids}` | `test_renderers.py:65-67` | 白名单内，改四 id 并集（§12.7） |
| `set(BUILTIN_PAGE_CONTRACTS) == {3 ids}` | `test_pages.py:203-204`、`tool_pages.py:249-250` | 白名单内，改两张表并集 |
| `len(BUILTIN_PAGE_CONTRACTS) == 3` | `v24/s13/test_tools.py:1695` | **不动**（兄弟表 `TEXT_PAGE_CONTRACTS` 不改变这个数） |
| `BUILTIN_PAGE_CONTRACTS` 的 limit 映射 | `tool_pages.py:251-255`、`test_pages.py:209-213` | **不动** |
| `v24.fs.<kind>.text` | `renderers.py`、`tool_pages.py`、`s13/*`、`vectors/renderers.json` | **不动**（旧 3 条身份） |
| `render.manifest.<kind>` | `test_vectors.py:119,126,150,275`（固定三元组）、`test_contracts.py:25-26`、`vectors/*.json` | **不动**；新条目不进这些文件 |
| `for kind in ('read','list','search')` | `test_vectors.py:105` | **不动**（固定三元组，第 4 个 renderer **不会**让它失败） |
| `DESIGN_SHA256` / `sha256_at_review` | `test_contracts.py:10`、`vectors/design_conformance.json` | **不动**（结论见第三段） |
| Node 入口 | `v24/s13/test_node.py`（`:1-5` docstring、`:76`） | 缺失即 `[SKIP]` 退出 2，按第四段处理 |

**第三段：`test_contracts.py` 的键集与设计文档 SHA 允不允许追加——结论（写进 W9 记录）：**

- **`renderers.json` 键集不允许追加。** `test_contracts.py:69` 是 `set(local) == REQUIRED[name]`（严格相等，不是子集），`:62` 是 `inventory == REQUIRED`，`:77` 是 `len(allcases) == 71`；追加一例立刻红，而 `test_contracts.py` 在禁止改清单里。→ 新 renderer 的向量**只进** `text_plain_v1.json`。
- 已核实 `test_renderers.py:65-67` 的 id 集合是**字面量三 id**，不是从 `renderers.json` 读取的，所以不存在"改 registry 就把 `renderers.json` 拖进 diff"的联动；改成四 id 并集即可。W9 记录仍要写明"新 renderer 的 manifest 不在 `renderers.json`，由 `text_plain_v1.json` 承载"。
- **设计文档不允许追加。** C.18 确实有"只追加、旧字节是精确前缀、25 处引用到 23 个 pinned span 的行号与 SHA 不变"的先例（`v24/s13/README.md:155`），但每次追加都要同步改 `test_contracts.py:10` 的 `DESIGN_SHA256` 与 `design_conformance.json` 的 `sha256_at_review`，两者都在禁止改清单里。→ W9 **不碰设计文档正文**。
- 因此 `render.manifest.text` 的落点是 `text_plain_v1.json`，不是 `renderers.json`；`test_vectors.py` 的固定三元组不加载它，由 `test_renderers.py` 的新段消费。若 spike 证明连 `test_renderers.py` 也必须读 `renderers.json` 才能登记 manifest 例，**缩小 W9 范围**：只登记 renderer + golden，manifest 例移出 W9 并在 ledger 记一条——不扩白名单。

**第四段：spike 先于向量，顺序写死、不可颠倒：**

1. 只在 `v24/host/renderers.py` 加第 4 条（`_text` + `_GOLDEN["text"]` + `_BUILTIN_SPECS` 第 4 项）；
2. 跑 §12.9 的**完整** s13 gate 清单（13 条，含 `--node`）；
3. 记录每条失败属于哪一类：计数（`len(RENDERERS)`）、键集（`set(entries)`）、还是循环（`test_vectors.py:105` 的固定三元组，**预期不失败**）；`import v24.host.tool_pages` 会在第 4 条加入后立刻 `page contract drift`，这是预期失败，不是回归；
4. 按白名单修 `tool_pages.py`、`test_renderers.py`、`test_pages.py` 后重跑，直到全绿；
5. **再**写 `text_plain_v1.json`。先写向量会掩盖真实的计数/键集失败，把"应该被断言抓住的"变成"看起来已经通过"；
6. 任何需要改白名单外文件的失败 → 按 §12.10 回退重规划，不在 W9 里扩权。

**Node 规则**：`uv run python v24/s13/test_node.py --node` 在 Node 缺失时是 `[SKIP]` 退出 2，`test_node.py` 的 docstring 明写"never recorded as a pass"。因此**不能**算 W9 通过：ledger 记 `toolchain absent`，把它列为未验证项，**W9 状态写 `passed-with-unverified`**，并在 W9 记录里列出"哪些断言依赖 Node 才可见"。

### 12.9 验收：加性

**加性的定义**：既有 8 个契约向量文件（`descriptor_v2` / `frames_v2` / `manifest_adapter_v2` / `provider_projection_v2` / `results_v2` / `schema_v2` / `tool_contracts` 这 7 个 + `renderers.json`）全部**逐字节不变**；`design_conformance.json`、`test_contracts.py`、`test_vectors.py` **零 diff**。只允许 §12.7 列出的 registry 计数、id 集合与 page 集合断言扩写。

**必须逐字节不变的**：

- `v24/s13/vectors/renderers.json`（git diff 为空；含 `render.read/list/search` 的 golden 与三个 `render.manifest.*`、`render.digest.provisional_values`）→ `test_contracts.py` 的 71 例清单与设计 SHA 不受影响，`test_vectors.py` 不变；
- `v24/s13/vectors/design_conformance.json` 与 `v24/s13/test_contracts.py`（`DESIGN_SHA256` 不变）、`v24/s13/test_vectors.py`（固定三元组不动）；
- 3 个 renderer 的 21 条 embedded golden 与 3 个 `render_digest`/`golden_digest`（`_GOLDEN` 前三条与 `_BUILTIN_SPECS` 前三项不编辑），连同它们含 NUL 的 golden 用例；
- `test_pages.py` 的 `contracts=3`、kind 映射与 limit 映射，以及 `test_tools.py` 的 `len == 3`（文件本身只改上述两行集合断言 + 一行 import）；
- `tool_pages.py` 的 `BUILTIN_PAGE_CONTRACTS` 三条合同内容与 limit 映射；只改 `:249-250` 的 import 断言与 `validate_page` 的查表顺序。

**仅允许的既有断言变化**：新增 `v24.text.plain` 一条 registry 条目与它的 golden/manifest digest；`test_renderers.py` 的 registry 计数（3 → 4）与 id 集合（三 id → 四 id 并集，见 §12.7，**不**改成读 `renderers.json`）；`test_pages.py` 的一处 `RENDERERS == BUILTIN_PAGE_CONTRACTS`（第 203-204 行）改为与 `TEXT_PAGE_CONTRACTS` 求并集；`tool_pages.py:249-250` 的 import 断言同样改为并集（否则第 4 个 renderer 一 import 就炸）。`test_renderers.py` 的摘要行按**追加**方式扩展，冻结子串 `cases=7; golden_cases=21; digest_pairs=3` 逐字保留。

> 实际结果：三个既有 `render.manifest.*` 的 digest **也不变**，`renderers.json` 未改；没有"聚合 digest 变化"；代价是 `tool_pages.py` 的 import 断言、`test_renderers.py` 的计数与 id 集合、`test_pages.py` 的两行集合断言必须跟着 registry 扩写（否则第 4 个 renderer 连 import 都过不了）。这三处都在 W9 白名单内，已记入 D-UI-5。

**W9 记录（`docs/reviews/v24-tool-plugin-abi-w9-text-plain-2026-11-02.md`）必须声明**：这是 **ABI v1 的加性修订**；设计文档正文**不改**（受 `DESIGN_SHA256` 与逐 span SHA 约束）；`renderers.json` 未改、`design_conformance.json` 未改；代码与设计文档的差异（多一个通用文本 renderer、`render.manifest.text` 落在 `text_plain_v1.json`）在 deviation ledger 记**一条**，不粉饰成"文档已覆盖"。

**消费方式**：`test_renderers.py` 的新段加载 `text_plain_v1.json`；正例**同时**跑 `RENDERERS.render` 与 `validate_page(RENDERERS.by_id("v24.text.plain", 1).ref, args, value)`，反例按「层」列只跑对应层（`renderer` / `page`）。这样 `test_pages.py` 只需改两行集合断言，不必新增正文。

`text_plain_v1.json` 的形状：顶层 `{format:"v24-text-plain-1", cases:[...]}`；每个 case 含 `id`、`layer`（`renderer`/`page`）、`args`、`value`、`expect`（`ok`/`render_failed`/`invalid_tool_output`/`invalid_tool_content`）；`expect="ok"` 的正例另带 `content`/`meta`（与 `_GOLDEN["text"]` 同值）。

**正例向量**（`text_plain_v1.json` 的 `cases`）：

| id | 内容 | 期望 |
|---|---|---|
| `text.plain.verbatim` | `"a\nb"` | content text 原样；meta `{}` |
| `text.plain.empty` | `""` | 1 个空 text block |
| `text.plain.unicode` | emoji + U+2028/U+2029 + 组合字符 | 原样 |
| `text.plain.bash_nonzero` | `exit_code=2` + footer | 原样；`exit_code` 保留 |
| `text.plain.apply_partial` | `status="partial"` | 原样 |
| `text.plain.spill` | `truncated=true` + `.v24/spill/<32hex>.txt` | 原样 |
| `text.plain.lines_2000` | 2000 行 | renderer OK；page OK |
| `text.plain.text_32768` | 恰好 32768 字节 | renderer OK；page OK |
| `text.plain.value_40960` | 用控制字符把**序列化后**的 value 精确撑到 40960（`text` 原始字节仍 ≤32768，故 page 也过） | 预算接受 |

**反例向量**：

| id | 层 | 期望 |
|---|---|---|
| `text.plain.nul` | renderer + page | `render_failed` / `invalid_tool_output`（jsonb 拒绝 `\u0000`；`_check_safe_domain` 不查字符串，故两层各拒一次） |
| `text.plain.exit_code_256` / `_neg1` | renderer | `render_failed`（schema 层也拒：`maximum`/`minimum`） |
| `text.plain.exit_code_true` / `_float` | renderer | `render_failed`（`type is int` 拒绝 bool/float） |
| `text.plain.both_exit_status` | renderer + page | `render_failed` / `invalid_tool_output` |
| `text.plain.unknown_key` | renderer（schema 层由 M2 的真实工具路径覆盖） | `render_failed` |
| `text.plain.lone_surrogate` | renderer | `invalid_tool_content`（`compact_json` 失败） |
| `text.plain.spill_absolute` | page | `invalid_tool_output` |
| `text.plain.spill_dotdot` | page | `invalid_tool_output` |
| `text.plain.spill_wrong_namespace` | page | `invalid_tool_output` |
| `text.plain.spill_wrong_ext` / `_nonhex` | page | `invalid_tool_output` |
| `text.plain.spill_empty_when_truncated` | renderer + page | 拒绝 |
| `text.plain.spill_nonempty_when_plain` | renderer + page | 拒绝 |
| `text.plain.lines_2001` | page | `invalid_tool_output` |
| `text.plain.text_32769` | page | `invalid_tool_output` |

40960、32768/32769、2000/2001 的精确字节由生成器用 canonical 编码器构造并冻结，**不在计划里手写 padding**。host 的 `40960`/`41984` 预算已由 `test_tools.py:943-961` 覆盖；W9 不重复造 stub，`text_plain_v1.json` 只承载 renderer/page 能直接判定的用例。

**W9 gate 命令**：

```bash
uv run python v24/s13/test_contracts.py
uv run python v24/s13/test_descriptor.py
uv run python v24/s13/test_pages.py
uv run python v24/s13/test_registry.py
uv run python v24/s13/test_renderers.py
uv run python v24/s13/test_results.py
uv run python v24/s13/test_schema.py
uv run python v24/s13/test_tools.py
uv run python v24/s13/test_vectors.py
uv run python v24/s13/test_line_json.py
uv run python v24/s13/test_lifecycle.py
uv run python v24/s13/test_wiring.py
uv run python v24/s13/test_node.py --node    # Node 缺失 → [SKIP] 退出 2；ledger 记 toolchain absent，W9 状态 passed-with-unverified，不得算通过
```

### 12.10 对 UI 的约束

- **W9 未通过，不开始 M1。** 没有 `v24.text.plain` 就没有合法 renderer，11 个工具的 descriptor 会 `renderer_not_approved`，整条 v2 路径不可用。
- W9 通过后，UI 只从 `RENDERERS.by_id("v24.text.plain", 1).ref.digest` 取 digest，**不硬编码** 64 位十六进制；catalog 的 `render` 三元组从 registry 复制。
- 如果 W9 需要动 SQL、`registry.py`、`descriptor.py` 或既有 renderer 的 id/digest，**回退重规划**：那说明设计越界，不是实现细节。

---

## 13. 命名后续里程碑与残留问题

1. **`get_file_tree` 的 `selected` 模式**：无 selection 时等价 `full` 并在 output 注明；若用户需要真正的 selected，回到 D8 重新评估。这是本计划唯一的"功能残项"，不是无边界悬案。
2. **W10 · effect-version 读面**：新增 `v24.host_run_event_versions(p_run, p_after_event_id, p_limit)`（或等价物），把 install/prepare/release 与 `interaction_created/responded` 纳入时间线，并允许按"版本"刷新而非逐个 `host_effect`。触发条件（任一）：单 run >64 个 effect 且增量页频繁溢出；需要展示 install 生命周期；实测 `host_effect` 刷新 p95 >50 ms（`|active|>20`）。注意：`v24.events.seq` 是 per-`(entity_type,entity_id)` 的（`10_schema.sql:234,243`），**不能**当全局 cursor；`event_id` 是 identity，但分配序 ≠ 提交序，必须留 look-back 窗口，这正是它要单独立项的原因。
3. **W11 · adapter 流式**：把 `stream:false` 换成增量 SSE，需要新的 transport、累积器、journal 语义与 `generating` 的替换；入口条件：provider 合同支持增量、帧预算重新测量、W 系列基线有升级方案。
4. **W12 · completion 上限**：把 `MAX_COMPLETION_CAP` 从 512 抬到 provider 允许的上限，重测 `FRAMING_MARGIN`、`max_args_bytes` 与 `MAX_SAFE_ARGS_BYTES`；入口条件：M5 的真实 run 里可量化的 `finish_length` 发生率（例如 >5% 的轮次因长度截断终止），**不是**"参数被截断率"——参数不会被截断，超限是整轮失败。
5. **W13 · 真实 provider 的 interaction**：让 adapter 能产出 `interaction`（需要 provider 合同支持“结构化提问”或一次显式 tool-like 交互）；在那之前 UI 的 ask-user 只有 fake 路径，README 必须写明。入口条件：provider 合同明确、`schema_digest`/`prompt_digest` 的生成规则确定。
6. **同 scope 连续多 run（含 `start.owner_fiber_id` 非空、且 owner 属于同 scope）**：M1 selftest 实测；成功则 M3 直接复用 scope，失败则 M3 退回每轮新 scope + 新 binding（§8.24）。跨进程恢复另由 `rehydrate` 覆盖（§4.3、不变量 24），不依赖这条。

**已定默认值（保守取值，用户可推翻）**：

- **scope 生命周期**：一个 conversation 一个 scope；scope 只由 `/close`、容量回收（只回收所有绑定 run 均已 terminal 的最旧会话）与 `--reset --yes` 销毁，且必须在 install 与 run 全部结束之后（`scope_control('close')` 之后 `install`/`start` 都会报 `scope_closed`，`40_interpreters.sql:2817-2818,2981-2982`）。`AgentRuntime.close()`（进程退出、测试收尾）**只**关连接/journal/线程/锁，**不 close scope**——这就是跨进程 `/resume` 能成立的前提（§4.3、不变量 24）。刷新 = 新 conversation = 新 scope；旧 scope 不自动回收，靠 `/close` 或 32 会话上限的 terminal-only 回收。
- **workspace 共享**：`.uidata/workspace/` 默认被所有 scope 与重启共享，是"一次性 scratch"但**不做 per-scope 隔离**；README 要写明它会累积、不要放敏感内容；需要隔离就用 `V24_UI_WORKSPACE_ROOT` 指一个空目录。
- **无 key 的 real 模式**：页面已启动时用横幅 `credentials_absent`，**进程不退出**（还要服务其他 thread）；"退出码 2"只属于 M5 的 CLI 入口。两者不矛盾：一个是一次性命令，一个是长期服务。
- **技能语言**：英文正文 + README 一行中文摘要；属可逆偏好，用户可随时推翻。

**待验证清单（全计划唯一汇总）**：

1. 族级 artifact 的行数/字节上限（§4.7）——M4 `wc -l -c` 实测后钉死。
2. `db_fingerprint` 的精确 SQL 与 `prosrc` 在目标 PostgreSQL 版本上的可读性（§4.1）——M1 `--status` 实测。
3. 不触发 `finish_length` 的最大 tool-args 字节数（§11）——M5 实测后写进 `catalog.MAX_SAFE_ARGS_BYTES`；**不是** 1.5KB 估算，也不再写"512 截断"。
4. `chainlit==2.12` 的 `cl.Step.send()` / `on_chat_end` 行为（§4.5）——M3 实测。
5. `crash_after='started'` + `default_lease_ms=1` 的结算路径（§6.1-13）——M2 实测。
6. 真实 provider 的 `interaction` 可达性（§2.4）——W13。
7. `start.owner_fiber_id` 非空且属于同 scope，以及同 scope 二次 `start`（§4.2、§8.24）——M1 selftest；失败则 M3 每轮新 scope。

---

## 14. 参考

- `docs/reviews/v24-chainlit-agent-runtime-critique-2026-11-01.md` — 对**第一版（v1 ABI）**草案的五项 bounded critique。v2 + W9 改写后，其中 v1 专有项随 ABI 变更消失，启动顺序、时间线、会话、gate 隔离等条目已被吸收；读它时请注意它评论的不是当前版本。
- `v24/s4/README.md` — C17–C23、settlement matrix、batch barrier。
- `v24/s11/plugin_fixtures.py` — `manifest_bytes`/`PluginHarness`/`ScriptedTransport`/`execute_single`（`:108-176`、`:276-441`）。
- `v24/host/renderers.py` — `_BUILTIN_SPECS` 元组形状（`:249-270`）、`golden_digest`（`:151`）、`render_digest`（`:164`）、`_GOLDEN_BY_ID`（`:142`）、import 时漂移检查（`:284-288`）。
- `v24/host/tool_pages.py` — `PageContract`（`:36-47`）、`validate_page`（`:219-243`）、import 时一致性断言（`:249-255`）。
- `v24/host/descriptor.py` — `TOOL_KEYS`（`:41-44`）、`ANNOTATION_KEYS`（`:60-62`）、`CONCURRENCY`（`:63`）、`REPLAY_CLASSES`（`:64`）、`LIMIT_RANGES`（`:53-59`）、`_check_implications`（`:202-214`）。
- `v24/host/registry.py` — `require_artifact`（`:57-83`）、`environment`（`:85-94`）、`from_manifest`（`:317-375`）、`lookup_install`（`:422-435`）、`match_tool`（`:437-462`）、`match_pin`（`:464-477`）。
- `v24/host/plugins.py` — v2 dispatch 全流程（`:137-236`）、`lease_insufficient`（`:168-178`）、`validate_page`（`:208-213`）、`measure` 预算（`:223-229`）。
- `v24/host/tool_schema.py:24-39`（十三键/拒绝词表）、`:278-287`（bool 不是 integer）。
- `v24/host/tool_results.py:128-157`（message leak 规则）、`:252-268`（`measure`）。
- `v24/sql/49_host_reads.sql` — `host_run_effects:209`、`host_effect:289`、末页 `next_cursor NULL:285`。
- `v24/sql/45_capability.sql:50-59` — `(realm, key)` join，无 scope 过滤。
- `v24/sql/48_loop.sql:1116-1126` — 未 pin 的 tool_call → `invalid_outcome`。
- `v24/sql/40_interpreters.sql:2748-2791` — `requires` 形状、≤16、owner 非空；`:3035` — manifest digest。
- `v24/s1/setup_db.py:540` — 十表封闭集；`:555` — disposable `setup_db()`。
- `v24/host/smoke.py:155-196` — 真实 provider boot recipe（注意：固定 realm、无 installs）。
- `v24/s13/test_renderers.py` — golden 向量的组织方式（5 键相等 + measures + 27+E(T)）。
- `v24/s13/test_contracts.py:10` — 设计 SHA；`:14-39` — 71 例独立清单。
- `docs/investigations/deepseek-harness-design-vs-v24-2026-10-29.md` — run vs session 边界、三条可迁移不变量。
- `docs/investigations/v24-plugin-vs-agent-sequencing-brief-2026-10-29.md` — protocol-first 裁决。
- `v24/s13/plugins/fs_read.py` — 单文件 stdlib artifact 范本与预算常量（`:24-26`）。
- `docs/plans/v13-minimal-agent-loop-demo-2026-09-23.md:172-241,394-405` — hub-and-replay 先例。
- `demo_v13/app.py`、`demo_v13/pyproject.toml` — 唯一可用的 Chainlit 前端（gitignored）。
- `/Users/wxl/Projects/pi/packages/coding-agent/src/core/tools/*.ts`、`core/skills.ts:1-20,340-395` — Pi 工具与技能语义。
- `/Users/wxl/Projects/repoprompt-ce/Sources/RepoPromptMCPCore/`、`Sources/RepoPromptDomainRuntime/MCPDomainCanonicalToolDefinitions.swift` — headless RPCE 参考。
- `/Users/wxl/Projects/pgembed` — 嵌入式 PostgreSQL（PG 18.4）。

---

## 本轮修订记录

1. **ABI 改为 v2 `ApprovedPlugin` + 2 个族级 artifact**；删除 v1 路线、旧 A1 与手写 declaration digest，改为一次构造 + 三处 digest 断言（`from_manifest` 要裸 hex、SQL 要 `\x` 前缀，同一串字节无法两全；§2.3、§3 A2、§7）。`HostWorker` 必须带 `tool_handler`/`resource_handler`，否则 `host_prepare` 与 `tool_call` 都没有执行者；per-scope 的 `(family, realm)` 条目并入一个新的不可变 registry（`registry.py:391-417`）后整体替换 `dispatcher.registry`，只在专用线程、`run_once` 之外做。
2. **新增 W9 前置里程碑**（§12）：`v24.text.plain` v1，11 个工具共用；明确 W9 未过不进 M1，并给出加性验收与允许改的文件白名单。
3. **能力收敛改为 toolset → `requires` → pin**，删除 per-call 审批叙述；补上"未 pin 的调用在 SQL 层就 `invalid_outcome`"的真实机制（§D4、§D6）。
4. **时间线改为"增量发现 + `host_effect` 刷新 active"**，删除每轮从 cursor 0 重读全部 effect 的做法；记录"末页 `next_cursor` 为 NULL"这一坑（§D5、§4.3、§8.12）。
5. **持久环境加 `loaded.json` 九字段 + 启动漂移检测 + `migrations.py` 零迁移注册表**；`--init` 只创建，不假设 `load_stage` 幂等（§4.1）。
6. **新增 `sessions.py`/`turns.jsonl`、历史注入、`/resume <run_id> <token>`、`/close`**；修掉"刷新=失忆"与 `/resume` 自相矛盾（§4.5.1、§8）。
7. **`bash` 非零退出改为成功 value + `exit_code`**，同步 §4.4 渲染映射；UI 文本不再从 output 重新序列化，而是直接取 outcome 里的 `content`（host 的 `canonical_json` fallback 仍在，但 v2 不依赖它）（§12.5、§4.4）。
8. **敏感路径默认拒绝 + `.v24/**` 虚拟只读挂载**（spill/skills 不复制、不建 symlink、不依赖 OS mount）（§D6、§4.6、§12.6）。
9. **512 completion 上限记为已知限制**：UI 在 `start.input` 显式设 512（adapter 默认 256，不再依赖默认值）；新增 `write.append`，技能教小步修改，README 写明（§4.6、§11、§13 W12）。
10. **里程碑重排为 W9 → M1–M5**，风险表删 v1 行并补 manifest `\x`、per-scope registry 等行，开放问题改写为命名里程碑 W10–W13（W13 覆盖真实 provider 的 `interaction`，§10、§11、§13）。

### 第二轮定向修正（6 处）

先记三个**已核实**的代码事实（不再写成"待验证"）：

- `v24/host/tool_pages.py:58-76` 的 `_check_safe_domain` 只检查整数是否 safe / key 是否 str，**不拒绝 U+0000**；
- `v24/host/deepseek.py:508-510`：`finish in ("length","aborted","insufficient_system_resource","other",None)` → `_unknown("finish_<x>")`，长度截断是 **unknown → run 终止**，不是"截断成 final"；
- `v24/s13/test_vectors.py:105` 是固定三元组，第 4 个 renderer 不破坏它；但 `test_contracts.py:25-26` 的 `renderers.json` 键集是**严格相等**、还固定了设计文档 SHA，这两处必须进 W9 spike。

对应的 6 处改动：

11. **NUL 从正例改反例，并证明 durable 链路干净**：`text.plain.nul` 在 page 层 `invalid_tool_output`、renderer 层 `render_failed`；`_text` 与 `_check_text` 各显式拒 `\x00`；artifact 共享区写死出口（文件内容直读 → `binary_file`、搜索类跳过并计数、`bash` 替换 U+FFFD，spill 与 text 同源）；既有 3 个 renderer 的 NUL golden 一字节不动；gate 新增 `bash printf 'a\0b'` 的 durable 场景（不变量 23）与 §8.25（§12.3、§12.4、§12.9、§4.7、§6.1、§8）。
12. **工具文本不再被 UI 二次截断**：tool step output 逐字节等于 `join_content(...)`，`failed`/`unknown` 也完整；2000 字符帽只用于 `model · tools (n)` 的 args 摘要、`run · …` 说明与错误 reason；gate 新增大文本逐字节场景（§4.4、§6.1-16）。
13. **跨进程 `rehydrate` + scope 生命周期**：binding 持久化 `realm`/`workspace_root`(realpath)/`toolset`；新增 `AgentRuntime.rehydrate` 五步（重建 plugin、回填 install/fiber 缓存、对 DB 回读行跑断言 3、路径或 toolset 不一致 → `catalog_changed` 只回放、**不得重发 install**）；`/resume` 的 running/waiting 先 rehydrate；`close()` 不 close scope；scope 只由 `/close`、容量回收、`--reset` 销毁；新增不变量 24（§4.3、§4.5、§4.5.1、§13）。
14. **W9 前置检查扩到全树 + spike 先于向量**：前置 grep 覆盖 `RENDERERS.entries`/`len(RENDERERS)`/`BUILTIN_PAGE_CONTRACTS`/`v24.fs.`/`render.manifest`/`test_contracts`/设计文档 SHA；顺序写死为"先加 registry 第 4 条 → 跑 13 条 gate → 记录计数/键集/循环失败 → 按白名单修 → 再写向量"；结论：`renderers.json` 键集与设计文档 SHA 都**不允许追加**，`render.manifest.text` 落 `text_plain_v1.json`；Node 缺失记 `toolchain absent`、W9 状态 `passed-with-unverified`；W9 记录声明这是 ABI v1 加性修订、设计文档正文不改、差异记 ledger 一条（§12.7、§12.8、§12.9、§7.1、§10 W9）。
15. **预算适配算法 + 512 的正确表述**：40960 适配 = 先 2000 行/32768 字节（`read` head、`bash` tail）再循环缩短到 `compact_json(value) ≤ 40960−SPILL_RESERVE`；把旧的"超限会被截短成 final"说法拆成 `build()` 的 clamp（无害）与 provider `finish_reason="length"` → `_unknown("finish_length")`（整轮失败）；`write` 大内容不是被截断而是本轮失败，主缓解是 `write.append` + 小步；`MAX_SAFE_ARGS_BYTES` 单一常量取代 1.5KB，页脚/README 写"超限本轮失败"（§2.4、§4.2、§4.6、§4.7、§11、§13 W12）。
16. **让 digest 断言真的能失败 + 两处一致性**：断言 1 降级为辅助，断言 3 改为对 `host_scope_installs`/`host_install_fibers` 的 **DB 回读行**、每 scope 每族都跑；新增负控制（artifact 改一字节 → `lookup_install` 空；manifest `realm` 改一字符 → `AdapterNotFound`）；§8.7 的 `respond` 去掉 `driving_generation`；`ScriptedUiAdapter` 统一落 `fake.py` 并进 M1 文件列表（§3 A2、§4.3、§6.1-6、§8.7、§10 M1）。

## D-UI-6 · Authorized M1 install ACL and immutable audit exception

User authorization (2026-11-01): M1 may add `v24_admin` only to the public `v24.install(uuid,uuid,bytea,bytea,text)` EXECUTE GRANT in `v24/sql/50_permissions.sql`; the interpreter already authorizes admin. Preserve all 27 SQL statements. Update only the S1 admin exposed set/remove its install-42501 negative, and S9 admin exposed set/count 26→27/positive install privilege assertion. Use the public wrapper; never construct `command_install` in UI code.

The authorized audit files are `v24/s13/test_wiring.py`, `v24/cordis/dp4/test_closeout.py`, and DP5/DP6 `test_boundaries.py`. Retain every original BASE and full scope, all 12 SQL hashes (update only permissions), S13's 12 frozen paths, whole-module renderer AST stripping exactly five W9 additions, and `checks=6`. No skips or rebaseline. Relative to DP5/DP6 BASE `57e2c1e`, the exact six modified paths must be permissions SQL, S1 `test_g1.py`, S9 `test_g8.py`, and the three immutable historical READMEs below. Require status M for all six, reject missing deltas or a seventh path. First three must equal raw BASE bytes transformed by unique approved literal substitutions; all other frozen paths remain unchanged.

| Historical path (never edit) | Immutable source commit | Blob | SHA256 |
|---|---|---|---|
| `v24/s9/README.md` | `f3c48a1fc11567e6f7e6bd422eb97fac3c3a29a9` | `3ac204b4ef399091e6cc2aa43765c8b22eeca981` | `0a3c64ddb0e4997d287de81b5c93582cb97320bcb18416c18f7e54fcd318551b` |
| `v24/s10/README.md` | `d8029b73e230d68c4a3817fa14a95c72151f4c02` | `b37b5fe03ab43d09565d3a17a08d1c6677cdeb02` | `a25595bf64d05a649313ba9a48b1e8f1c1c385a365330799be2a126787610ae3` |
| `v24/s11/README.md` | `d13391d27f9c7363906282af4cea4160c5aa97a8` | `2fb92cdcdee994ad030a2b9046b4d8fc5cb267b4` | `dc9e0e575d3cb2061eff286ae5fefa3d83b2bf8a2d36cae200c4eca484262063` |

All source commits are ancestors of pre-M1 `9ba0b782797c5c2c421f6355f01d0047d1955b23`; current README bytes equal that HEAD. The earlier `0189029` pins and five-path assumption were false and are superseded by these exact pins. Negative controls must reject an extra byte, SQL admin removal/PUBLIC/second-line mutation, the old S1 admin-denied block, old S9 count/negative assertion, README mutation, and a seventh changed path.

A dedicated `v24/ui/d_ui_6_acl.py` (`--check`/`--apply` only) may preserve the existing environment: recognize only exact preupgrade, ACL-upgraded/metadata-old, or completed states; hold `.uidata/lock` for apply; validate database `agent_v24_ui`, server identity, database OID and fingerprint; execute only the target admin GRANT and atomically rebind permissions `file_digests` plus `sql_manifest_digest` in `loaded.json`. Test disposable first, then existing check/apply/check. No reset, `load_stage`, full replay, or ordinary migration; `--migrate` remains unsupported/2. These plan/ledger/audit/ACL/helper paths are explicit exceptions to the original M1 whitelist; no host/load/design changes.

Factual correction to A2/§6: `PluginRegistry.lookup_install` raises `AdapterNotFound('adapter_not_approved')` on mismatch; it never returns None. Test both artifact and manifest mismatch accordingly. UI RPC commits any successfully returned domain envelope (including rejection), rolls back Python/SQL exceptions, and leaves the connection IDLE.

## Post-approval correction (2026-11-02)

本节是追加更正，不重写 §12.7/§12.8 的正文；两节原文保留为当时的批准文本，最终权威是 [W9 execution record](../reviews/v24-tool-plugin-abi-w9-text-plain-2026-11-02.md)。

- **§12.7 漏项。** 允许改文件清单没有 `v24/s13/test_wiring.py`。该文件的 `scope_audit()` 在 `frozen` 元组里写了 `"v24/host/renderers.py"` 并执行 `git diff --exit-code c8c4bd0 -- …`，所以第 4 个 renderer 一进工作树，W9 的 13 条 gate 就必然在 `test_wiring` 上失败。这是漏项，不是 §12.7 有意禁止。
- **§12.8 命中表漏项。** 该表只枚举 `RENDERERS.entries`/`len(RENDERERS)`/`BUILTIN_PAGE_CONTRACTS`/`v24.fs.`/`render.manifest`/design SHA 六类符号，而这条命中把 `renderers.py` 写成 `frozen` 路径元组的字符串元素，不含任何符号；它只在 spike 后的重跑中以 `CalledProcessError` 暴露。§12.8 的 grep 口径因此不足。
- **授权。** 用户批准把 `v24/s13/test_wiring.py` 纳入 W9 范围；追加的 W9 record 是该决定的权威记录，本节摘要不替代它。
- **窄修订曾是放松，已被取代。** 最初的窄修订只钉住 `_GOLDEN` 字典字面量与旧 3 条 `_BUILTIN_SPECS` tuple，`_read`/`_list`/`_search` 函数体、`_decimal`、`_validate_result`、`RendererRegistry`、`RENDERERS` 与两个 digest 函数因此失去逐字节保护——这是覆盖面的放松，不是加强。2026-11-02 的 follow-up 用**整模块 AST 等价**取代它：deepcopy 当前 AST，恰好剥离 5 个已记录的 W9 加性节点（`_TEXT_KEYS`、`_TEXT_STATUS`、`_text`、`_GOLDEN["text"]`、`_BUILTIN_SPECS` 中首元素为 `v24.text.plain` 的 tuple），每个剥离必须恰好命中一次，余下 AST 必须与 `c8c4bd0` 完全相等；不等则抛出带 `difflib.unified_diff` 的 `AssertionError`。
- **不变项。** 其余 12 条冻结路径仍要求整文件相等（`v24/b0`、`v24/s10`、`v24/s11`、`v24/load.py`、`canonical.py`、`descriptor.py`、`tool_schema.py`、`tool_results.py`、`line_json.py`、`journal.py`、`db.py`、`process_io.py`）；`v24/s13/vectors` 下只允许 `text_plain_v1.json` 一个新文件；`checks=6` 与 `[scope] passed base=c8c4bd0 checks=6` marker 不变；`BASE` 仍是 `c8c4bd0`，不重新基线化。
- **无设计/SHA/SQL 变更。** `docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md` 正文未改，`DESIGN_SHA256` 仍 `778b13a4df78f47987626bbe466b70ebada95fe939565253749b7e6105991a2d`；`v24/sql/` 相对 `c8c4bd0` 零 diff。follow-up 只改 `v24/s13/test_wiring.py` 与五份文档（本计划、`v24/s13/README.md`、W9 record、conformance matrix、deviation ledger）。
- **未来 preflight 的硬要求。** 不能只 grep 符号。必须（a）对**每个计划内路径**做一次路径 grep，覆盖 `frozen`/`git diff --exit-code`/`git show BASE` 这类把路径当字符串的审计；（b）读出并核对所有 `git diff --exit-code`/`git show BASE` 审计的实际范围，而不是只看它们出现在文件里。否则整文件冻结审计会再次从命中表里消失。
