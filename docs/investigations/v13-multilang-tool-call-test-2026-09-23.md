# Investigation: v13 多语言工具调用测试例子 —— RP-CE 工具选型 + Python 移植可行性

日期：2026-09-23
任务来源：用户要求 — 「从 repoprompt-ce 中挑一个适合工具，再实现成 python 版，然后让 agent 调用这两个工具，达到相同的效果」。

## Summary

**结论：可行且机制已齐，只缺一颗可提交的 gate。**

- **选型**：repoprompt-ce 的 **`read_file`（headless 目标）**——约 15 行纯 Foundation、只读无授权门、无 regex/tree-sitter 依赖，且实机 stdio 探针已钉死其契约（换行分隔 JSON-RPC、双重编码 `.text` 信封、1-based/负尾/越界语义、`pathOutsideWorkspace` 围栏）。`get_file_tree`（目录序未定义）与 `file_search`（ICU≠re、移植度~55%，那是一份「分歧展览」报告的题目）主动拒绝。
- **落点**：新 tracked stage `v13/multilang/`，**零新 SQL**（加载停在 envelope、不改 `v13/load.py`、不碰 gitignored 的 `v13/demo/`）；双语言 = 两条 runtime `INSERT INTO tools` 行 + hub `self.tools[handler]` 分派（Python 口岸直调 + Swift 经 headless MCP 子进程）。
- **「agent 调用两个工具」的确切含义**：工具名由**判断平面**的 `tool` choice 选出（criteria=目录名），两个 cycle 各选一个；全仓库无 LLM `tool_calls`——provider 原生 tool-calling 是另一条更大的变更，不在本例范围。
- **「相同效果」的确切含义**：两条 `tool/result` 事件的 `result` 与本地期望切片**三方恒等**（v12 G6 跨语言恒等范式）；`effect_id`/`idempotency_key`/`request_hash` 按构造不同，必须排除。
- **主要难点**：Swift 制品是 macOS 外部依赖（需 exit 2 诚实跳过纪律）；换行类/围栏/双重编码的行为等价需精确口岸；种子 `turn_budget.max_cycles=3` 装不下「双工具+llm+finish」四 cycle（数据翻新到 4）；外部 IO 只能发生在 claim 提交之后、complete 事务之前的缝里。

## 任务背景 / Symptoms

- 目标：为 pg-agent v13 实现一个**多语言工具调用**的测试例子：
  1. 从 repoprompt-ce（Swift）挑一个合适的工具；
  2. 实现其 Python 版本；
  3. 让 agent（v13 执行环 / demo）分别调用 Swift 原版与 Python 版，达到**相同效果**。
- 本报告需回答三件事：**现状**（v13 与 RP-CE 两侧的可依托面）、**难点**（行为等价、Swift 工具的调用通道、v13 不变量约束）、**实施建议**（选型 + 测试形态 + 落地路径）。

## Background / Prior Research

（三个 explore agent 于 2026-09-23 并行调查，原文经本 agent 校核压缩；file:line 均为其报告引用，关键处在 Phase 3/4 复核。）

### B1. RP-CE 工具面与移植性（explore: RP-CE 工具清单）

- **工具目录权威**：`repoprompt-ce/Sources/RepoPromptDomainRuntime/MCPDomainToolCatalog.swift:13-40`（28 个工具名）；schema 以 base64 内嵌于 `MCPDomainCanonicalToolDefinitions.swift:10`，可读契约在 `repoprompt-ce/docs/spec/mcp-domain-canonical-tool-definitions.generated.json`（28 工具，测试逐字节守护）。
- **headless MCP 服务器存在且可被子进程 spawn**：产品 `repoprompt-mcp`（`Package.swift:113,177-183`），`swift build --product repoprompt-mcp` 可构建，随正式 release 发布（`docs/releasing.md:13-22`）。启动方式（`docs/architecture/headless-mcp-runtime.md`）：
  ```bash
  REPOPROMPT_MCP_HEADLESS_PROFILE_DIR=/tmp/rpce-profile \
  REPOPROMPT_MCP_WORKING_DIRS=/abs/repo/path \
  .build/release/repoprompt-mcp --backend headless
  ```
  协议 = MCP over stdio，**换行分隔的 JSON-RPC 帧**（`MCPStdioServerTransport.swift:148-150`）；无鉴权握手；`CallTool` 成功结果为单个 `.text` 内容块的 JSON 字符串（`DirectHeadlessMCPService.swift:596-611`）。
- **权限门槛**：只读工具（`read_file`/`get_file_tree`/`file_search`/`get_code_structure`/`history`）**不设门**；受保护变更类（`file_actions`/`apply_edits`/`manage_selection` 等）默认拒绝，需 DomainMutationPolicy 授权（`MCPDomainProtectedMutationToolProvider.swift:119-166`）。→ 测试选只读工具可绕开全部授权机制。
- **关键告警：headless 二进制跑的是简化实现**（`MCPDomainCanonicalWorkspaceService`，接线于 `DirectHeadlessWorkspaceBackends.swift:650-676`），输出形状与 app 版不同（如 `read_file` headless 返回**裸 JSON 字符串**而非 `ReadFileReply` DTO）。移植契约必须锚定 headless 目标。
- **移植性排名（headless 目标，best→worst）**：
  1. `read_file` ≈99% —— headless 实现仅 ~15 行纯 Foundation（`MCPDomainCanonicalWorkspaceService.swift:171-193`）：UTF-8 解码、按行切、切片、join。无 regex/charset/tree-sitter 依赖。
  2. `get_file_tree` ≈90% —— FileManager.enumerator + 深度钳制（`:155-169,511-534`），但**目录枚举顺序未定义**（需归一化或复刻 dirent 序）。
  3. `file_actions` ≈85% —— 纯 FileManager，但 delete→macOS Trash 语义分歧 + 变更授权。
  4. `file_search` ≈55% —— ICU regex ≠ Python `re`、C wildmatch、locale case folding（`:325-334,556-577`）。
  5. `apply_edits` ≈45% —— 引擎共享且有 golden 测试（`Tests/RepoPromptTests/MCP/ApplyEdits/ApplyEditsCoreRecoveryTests.swift`），但需移植 C 缩进编解码 + UnifiedDiffGenerator。
- 不推荐：`get_code_structure`（tree-sitter 12 语言）、`git`/`manage_worktree`（git CLI）、oracle/agent 类（外部 provider）。

### B2. v13 现状（explore: v13 时间线；修正 memory 过期信息）

- **时间线**：09-21 `0c47a0b`→revert `eebbc37`（清零对）之后，09-22 一天内重落 DP1–DP8（`20cf491` schema → `32d3451` resolve → `7499f5e` advance → `0541a6f` twophase → `6f8714a` envelope → `6179154` manifest → `7b619ab` chunks → `828556f` T0 recall → `312656d` characterize → `e4c5646` filter → `29a8a10` memory → `57e9205` economy → `ac27750` summary → `8c31ccb` DP7 gates），09-23 落 DP8 periphery（`69e5ebb`→`d34e18f`）+ errata（`3d92312`）+ **demo 计划（`aa106b7`，`docs/plans/v13-minimal-agent-loop-demo-2026-09-23.md`）**。工作区干净（仅未跟踪 docs）。
- **工具面已存在**：
  - tools catalog：`tools(name, kind IN ('sql','tool','llm'), handler, param_spec, enabled)` + `v13_tools_meta(revision,...)`，`v13/schema/v13_core.sql:581-698`（guard 拒 `::`、sql handler 签名/波动性校验、revision bump、DDL 事件触发器）；冻结进判断信封 `tools_revision/tools_catalog`（`v13/resolve/v13_resolve.sql:192-256`、`v13/envelope/v13_envelope.sql:426,557-560`）。种子行：`session_stats`(sql) / `send_summary_email`(tool, handler `worker:send_summary_email`)（`v13_core.sql:932-952`）。
  - 分派：`v13/loop/advance.sql:390-487` sql 快路（同事务 EXECUTE）；`:488-513` tool 队列路 —— `v13_enqueue_effect(kind='tool', request={tool,params,handler,tools_revision})` + `v13_send_work`(PGMQ) + `sessions.status='waiting'`；worker 侧 `v13_claim`(`v13_core.sql:266-289`)→进程外 IO→`v13_complete`(`:300+`，双层锁序+fence CAS)。外部 IO 不进事务由结构保证。
  - demo（**gitignored，仅本地**，`.gitignore:32`）：`v13/demo/` ~3.5k 行 Python + `sql/demo_api.sql` + 3 个本地 gate；`driver.py:273-307` worker 按 `request['handler']` 分派 `self.tools[...]`；`shim.py` typesafe→DeepSeek `/chat/completions`；真实 provider 冒烟 `--real-provider-smoke`。
- **缺口**：(a) `v13_claim` 无 `handlers[]` 过滤（任意 worker 认领任意 effect；tutorial ch08 §8.2/8.3 声称有 claim 侧过滤但未实现）；(b) tools 表缺 ch06 描述的 `input_schema`/`mutating`/`timeout_ms` 等列；(c) 四值信封（A15，`result_kind`）零实现；(d) **无已提交的多语言 worker/gate**——tutorial `docs/tutorials/v13/chapters/08-multi-language-harness.md` §8.4 G6（"SQL-only harness contract"，`v13/fakes.py` 双语校验）无 `v13/<stage>` 对应物；§8.5 练习 3 =「加第三个 handler：只 INSERT 目录行 + 起进程，零 SQL 文件改动」——**与本任务意图完全一致**。

### B3. 历史先例与测试约定（explore: 工具调用先例）

- **工具契约最佳先例 = v8 G6**（`v8/tools/` + `v8/loop/runtime.py`）：LLM 返回 tools plan → `build_tool_slots` 派生 slot 级 `effect_id/request_hash` → `seal_batch`（`v8/tools/client.py:100-160`）→ worker 按 kind 分派 → `tool/result` 事件 → 下轮 prompt。grant 模型：每 slot `v_gate_authorize` capability `tool:<name>`（`v8/tools/v8_tools.sql:436-470`）。
- **DeepSeek 现状**：`DeepSeekLLM`（`v8/loop/runtime.py:236-341`）stdlib urllib，**请求体无 `tools=[...]`**（全仓库无 LLM tool_calls 解析）；补齐需 3 处编辑（加 tools 参数、解析 `message.tool_calls` 映射为 `{tool_call_id,tool,arguments}`）。真实 provider gate 先例：`--real-provider-smoke`，无凭据 → `not_run` + exit 2（`v8/compat/test_compat.py:1133-1170`）。
- **测试约定确认**：独立脚本 `uv run python <path>`、exit 0 = pass、`check()` 模式；`setup_db.py` DROP/CREATE + `load_stage`；新增 SQL 须追加 `v8/load.py` 的 `SQL_LOAD_ORDER`（v13 同构于 `v13/load.py:16-31`，14 个 SQL 文件）。
- **子进程先例**：`v7/tests/test_phase1_runtime.py:1015-1060`（`subprocess.run` 第二进程验证 DuckDB 锁）是最接近的多进程测试先例；**全仓库无 JSON-RPC/MCP 测试先例**（仅 docs 提及）。本测试将是第一个。
- **跨语言等价先例**：`v12/queue/test_queue.py` G6 —— SQL `v12_uuid_v5` == Python `uuid5`（同输入同输出的跨语言恒等断言范式）。

## Investigator Findings

**方法**：pg-agent 侧（v13 SQL + demo Python）由 investigator 逐文件自证；repoprompt-ce 侧由两个 explore probe 侦察、四处 load-bearing 代码点（readFile / successResult / stdio 帧法 / runtime env）抽样复核，另做一次**实机 stdio 探针**（仅 spawn 既有 release 二进制 + `/tmp` 隔离 profile，零 build）。行号以 2026-09-23 工作区为准（v13/demo 为 gitignored 本地副本，他机可能 absent）。

### A. 工作假设逐项裁决

**F1（confirmed）两条 runtime `INSERT INTO tools` 行是正确且足够的机制。**
- tools 表 `kind IN ('sql','tool','llm')`；handler 对 tool/llm 是自由 worker 处理键（仅 enabled 的 sql 行被校验签名/波动度/权限）：`v13/schema/v13_core.sql:579-590`；语法守卫只禁 name / param key 含 `::`（signal 撞行防护）：`v13_core.sql:623-654`。故 `read_file_py` / `read_file_swift` + handler `worker:read_file_py` / `worker:read_file_swift` 合法（`:` 不受限，种子 `worker:send_summary_email` 同款）。
- W6 先例：运行时 `INSERT INTO tools`（`v13/demo/test_demo_loop.py:336-350`，tools_revision bump）→ 用毕 DELETE 恢复 + 断言 revision 再 bump（`:381-391`）。
- param_spec 形状 `{"<key>": {question, stated, options}}`（种子样例 `v13_core.sql:941-952`）；`param::` / `stated::` 信号由 `v13/resolve/v13_resolve.sql:108-117` 生成，param 的 criteria = `options`。
- 目录扩容后 needed = 4 固定 + tool + 4（种子 param/stated）+ 2×2（新工具各 1 参数）= **13 ≤ 32** → 快路单批吸收、慢路不触发（`resolve_fast_path` 种子 `v13_core.sql:752`；W6 计数公式 `9 + 4×N` 同源）。

**F2（confirmed，行号微调）driver `self.tools[handler]` 分派。** `v13/demo/driver.py:117`（`self.tools = dict(tools or {})`）、`:273-307`（`_do_tool`；假设写 264-307，实际 273 起）、`:286-287`（`handler = request.get("handler"); fn = self.tools.get(handler)`）。工具函数入参 `{sid, params, idempotency_key, last_user_text}`（`:293-297`），返回值原样进 `v13_complete(succeeded)` → `tool/result` payload 的 `result` 字段（`v13_core.sql:352-358`）。未知 handler → failed `demo_unknown_handler`（`:288-292`）。即 **Swift 侧 = 一个包装 stdio 客户端的普通 Python 函数**，driver 无感。

**F3（confirmed）工具选择完全在 JUDGMENT 平面，全树无 LLM tool_calls。** `tool` 是 choice 信号，criteria = enabled 目录名 + `none`（`v13_resolve.sql:97-105`）；路由 P4c 要求 intent∈{sql_answer,tool_action} ∧ gate_action pass ∧ tool pass ∧ choice≠none，risk≥2.25 转 human（`v13/loop/advance.sql:110-163`）；排队 request 冻结 `{tool, params, handler, tools_revision}`（`advance.sql:490-513`）。driver 的 generate 注入只产 text；v13 无 tool_calls 解析（v8 侧见 B3，抽检一致）。

**F4（confirmed，实机）Python stdio JSON-RPC 客户端可行** —— 见 F11–F13。

### B. Q1：双工具回合的预算算术

**F5（confirmed）cycle 计数 = 本 turn 的 `turn/route` 事件数。** `v13_cycle_no`：`v13_core.sql:161-166`（`count(*) WHERE type='turn/route' AND seq > last_user_seq`）。预算步 ⑤ 在 ③④ 任何建账之前：`advance.sql:331-332`（`v_cycles >= max_cycles` → human budget_exhausted）；每次 ④ 路由 append 一条 `turn/route`（`advance.sql:387`）。种子 `turn_budget = {"max_cycles": 3}`：`v13_core.sql:753`。

**F6（confirmed，真缺口）双工具回合最小序列需要 4 个 cycle，种子 3 不够：**

```
user/message（锚）
→ parse① → advance(v_cycles=0<3) → turn/route#1 action=tool(read_file_py) → tool effect（身份 cycle=0）→ tool/result A
→ parse② → advance(1<3)   → turn/route#2 tool(read_file_swift) → effect（cycle=1）→ tool/result B
→ parse③ → advance(2<3)   → turn/route#3 llm（compare）        → llm effect（cycle=2）→ llm/message
→ parse④ → advance(3≥3!)  → 预算耗尽 → human(budget_exhausted) → turn/end delivered=false → session failed
```

compare 步骤 = llm 生成（`driver.py:66-93` build_messages 把 tool/result 以 `[tool result] ` 前缀入窗，FakeLLM 类确定性产出即可）；其后 **finish 路由（P0，`advance.sql:126-128`）没有预算可用**——单工具回合恰好 3 cycle（tool/llm/finish）正卡在种子上限。`max_cycles=4` 时第 4 次 advance `v_cycles=3<4` → P0 finish → `turn/end delivered=true`。
**路由每次都回判断面（confirmed）**：`request_hash` 含 ctx（`v13_resolve.sql:130-148`），canonical_state 窗含本 turn 锚定的 tool/result（`:17-40`）→ 每个 tool/result 落地后全部信号哈希漂移、gap 重开（`v13_gap`，`:363-373`）→ 每 cycle 重问全批 13 问。快路（mock）零成本；慢路 judge effect **不耗 cycle**（③ 在 ⑤ 之后，judge effect 不 append turn/route）。

**F7（confirmed）data-only 修复正确且被触发器精确限定。** `v13_policies` PK (name,version) + 部分唯一索引 at-most-one active（`v13_core.sql:701-709`）；`trg_policies_frozen`（`:715-729`）拒 DELETE、拒 name/version/value 改写，唯一许可 UPDATE = 翻 active。顺序约束（先翻后插，否则撞部分唯一索引）：

```sql
UPDATE v13_policies SET active = false WHERE name='turn_budget' AND version=1;
INSERT INTO v13_policies (name, version, value, active) VALUES
  ('turn_budget', 2, '{"max_cycles": 4}'::jsonb, true);
```

### C. Q2：FakeJudge 可驾驶性

**F8（stock 启发式 refuted / 脚本机制 confirmed）原版 FakeJudge 开不出双工具回合。** `forced_llm`（`v13/demo/fakes.py:68-88`）：本 turn 已有 tool/result 且无锚定 llm/message → intent 强制 llm_generate——tool A 结果落地后启发式直奔 llm，永远到不了 tool B（这是防单工具烧预算的有意设计）。
**便宜且有先例的脚本机制 = test-local answer_mock 包装**：`test_demo_loop.py:167-176`（断言 5）`base = json.loads(judge.answer_mock(sid, events)); base["answers"][...] = ...; return json.dumps(base)`。按相位脚本化：数当前 turn 锚定的 tool/result 数（0 → tool=read_file_py；1 → tool=read_file_swift；≥2 → intent=llm_generate），param 信号给单选项 choice。无需改 fakes.py（demo 与 tracked 测试都走注入物）。
**未知信号兜底**（目录扩容后）：choice → `sorted(criteria)[0]`（`fakes.py:143-147`）——param_spec 单选项时兜底恰好选中唯一值；stated → noul 0.9 ≥0.60 pass（参数才进 request，`advance.sql:165-185`）。但 intent/tool 相位仍须脚本，故整体走自定义 mock。

**F9（confirmed）慢路 / 真 DeepSeek 形态。** W6：本地 `fake_judge_server`（`harness.py:230-242`，typesafe 线格式 `{state,questions}`→`{model,answers,usage}`）+ `gap_mock`（`harness.py:174-186`，恰好覆盖当前缺口第一批；缺口空 → None → 走真慢路）+ `judgment_calls` 断言（`test_demo_loop.py:352-366`）。真冒烟：`test_demo_smoke.py --real-provider-smoke`（无 key → exit 2 credentials_absent；R-gen/R-judge/R-full 三子例，docstring :10-36）+ `register_provider` 的 `ALTER DATABASE … SET typesafe.provider='deepseek'`（`v13/demo/setup_db.py:150-172`）+ endpoint 钉值（`:174-205`）；无凭据拒收在开 socket 之前（`deepseek.py:60-66`）。多语言测试默认全 fake/mock——真 DeepSeek 判断是可选加项，非前置。

**F10（adjusted）tracked gate 的判断驱动用 GUC mock，不需要 demo 的 RPC 面。** 先例：`v13/loop/test_loop.py:67-68`（`set_config('typesafe.mock_response', …, true)` 同事务喂 `v13_parse`）+ `:155`（session `SET typesafe.model`）。**envelope stage 陷阱**：加载到 envelope 后 `v13_judgment_envelope` 被替换为 `v13_guc_required('typesafe.provider'/'typesafe.model')`——未设即 V3002（`v13/envelope/v13_envelope.sql:321-327, 495-499`；负例 `v13/envelope/test_envelope.py:686-688`，正例 `:130-131`）。tracked gate 每条连接 session 级 SET 两值即可；超级用户连接**不需要** demo 的 ALTER DATABASE（那是 REST/角色面需求，评审 §2.2）。

### D. Q3：Swift 桥客户端（probe + 抽检 + 实机）

**F11（confirmed，实机）握手与帧法。** `initialize` 由 pinned swift-sdk `Server(strict: true)` 应答（仓库内无自定义 Initialize handler；`DirectHeadlessMCPService.swift:71-79`）。实机（release 1.4.1，2026-09-23）：发送 `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{…}}}` → 返回 `{capabilities, instructions, protocolVersion:"2025-11-25", serverInfo:{name:"RepoPrompt CE", title:"…Headless", version:"1.4.1"}}`；`notifications/initialized` 静默；`tools/list` → 21 个可见工具（目录 28 的 policy 过滤子集），read_file 在列。帧法 = **换行分隔 JSON、无 Content-Length**：读侧按 0x0A 切帧（`MCPStdioServerTransport.swift:150-156`，抽检）、写侧补单个 `\n`（`:213-215`）、入帧上限 16MiB（`:39`）；stdout 无 banner，日志全走 stderr（默认 .warning）。

**F12（confirmed，实机）结果信封是双重编码的 JSON 字符串。** `successResult`（`DirectHeadlessMCPService.swift:594-605`，抽检）：域结果经 `JSONEncoder([.sortedKeys, .withoutEscapingSlashes])` 序列化后放进**单个 `.text` content block**。read_file 的域结果是 JSON 字符串（文件文本），故实机 `content[0].text` = `'"line one\\nline two\\nline three\\n"'`——客户端 `json.loads` 一次得原文。**工具失败 ≠ JSON-RPC error**：`errorResult`（`:607-612`）= `isError:true` + `.text` 消息；`tools/call` 的 catch 把一切异常（含 invalidParams）折进该形态（`:341-366`）。实机：越界路径 → `isError:true, text='pathOutsideWorkspace("../../etc/hosts")'`（enum case 的 `String(describing:)` 形态——**不是** probe 引用的友好文案 "Path is outside the bound workspace roots: …"；error 文本按不透明处理，或 Python 侧复刻观测格式）。stdin 关闭 → 干净退出（exit 0，terminal=.stdinEOF）。

**F13（confirmed）env 契约与本地状态。** `REPOPROMPT_MCP_WORKING_DIRS` 以 `:` 分隔、绝对路径、须存在且规范化后唯一（`DirectHeadlessRuntimeConfiguration.swift:70-72` 抽检 + `:83-110` probe）。`REPOPROMPT_MCP_HEADLESS_PROFILE_DIR` **仅在 profile≠default 时硬性要求**（`:31-38` 抽检；对 B1 措辞的修正）——但**隔离必须显式设置**，否则回落 `~/Library/Application Support/RepoPrompt CE`（真实用户 profile，`:55-69`）；显式 profile dir + 非空 working dirs ⇒ isolated bootstrap（`:18-20`）。本地状态（2026-09-23）：`.build/release/repoprompt-mcp` 存在（52.8MB，09-18 构建）+ debug 版；`swift 6.3.2`（target macosx26.0）。**仓库内没有任何端到端 stdio 驱动**（Swift 侧只有 in-process 测试 `Tests/RepoPromptTests/MCP/DirectHeadlessOracleGroupTests.swift:1749-1761`；`Scripts/conductor.py` 只用 app 后端结构化 CLI；CI 只 `swift build --product repoprompt-mcp`，`.github/workflows/ci.yml:80`）——本测试将是第一个。实施期构建命令：`cd repoprompt-ce && swift build --product repoprompt-mcp -c release`。

### E. Q4：read_file headless 语义（移植契约）

**F14（confirmed verbatim + 实机）切片语义。** `Sources/RepoPromptDomainRuntime/MCPDomainCanonicalWorkspaceService.swift:170-193`（逐行抽检）：
- 严格 UTF-8 读全文（`:178`）；`components(separatedBy: .newlines)` 切行（`:179`）；
- `start_line` **1-based**（`max(0, start-1)`，`:186`——0 与 1 同效）；负值 = 末 |start| 行、**limit 被忽略**（`:183-184`）；越界 start → 返回 `""` 非 error（`:187`）；limit≤0 → 空串（`:188`）；缺省 → 全文（`:190`）；非整数 start/limit 被静默忽略（`Value.intValue` nil）；
- 重 join 恒 `"\n"`（`:192`）——行终止符被有损归一。
实机全部复现：`(start_line=2, limit=2)` → `"line two\nline three"`；`start_line=-1`（文件尾有换行）→ `""`（**幻影尾元素**：`"a\nb\n"` 切成 3 元素）；`start_line=99` → `""`。
错误形态：缺 path → invalidParams "missing path"（`:174-176`）；越界 → pathOutsideWorkspace；空文件 → `""` 非 error；缺文件/目录 → 原生 Foundation NSError 经 isError 文本浮出（无结构化形状）。
**headless 切片路径零测试覆盖**（probe 全树检索；仅 `MCPDomainReadToolProviderTests.swift:117-124` 覆盖 missing-path 文案）——本 gate 同时是它的第一个行为锁。

**F15（confirmed）resolvePath 契约。** `Sources/RepoPromptMCP/DirectHeadlessDomainContext.swift:302-333`（逐行抽检）：NUL → 拒；空白 → 拒；绝对路径直用；**单 root 时相对路径 = root+path（不做存在性检查）**；多 root 须恰存在一处否则 "ambiguous"；`standardizedFileURL` + `resolvingSymlinksInPath`（含叶子）后按 `root.path` 前缀围栏。root 由上游先规范化（symlink 解析后）——Python 口岸必须同样 `os.path.realpath` root，否则 /var→/private/var 类假阳性。单 root + 相对 path 的 fixture 形态把多 root/绝对路径分支留在口岸单测。

**F16（confirmed + 移植方案）换行分裂危险真实，但可精确移植。** Swift `CharacterSet.newlines` = U+000A–U+000D（含 VT/FF）、U+0085、U+2028、U+2029；`components(separatedBy:)` 按每个字符独立切 → `"a\r\nb"` → `["a","","b"]`。Python `split('\n')` 得 `["a\r","b"]`、`splitlines()` 得 `["a","b"]`——**都不是**等价口岸。精确口岸 = `re.split(r"[\n\r\v\f\x85  ]", text)`（与 Swift 同语义：逐字符切、保留幻影空元素、尾换行产空尾元素），join `"\n"`。fixture 纪律：主等价用例用纯 LF ASCII（两种语言天然一致）；CRLF/尾换行用例保留为**等价断言**（口岸按 re.split 移植后双侧同得 `"a\n\nb"` / 空尾元素），README 记录「朴素 `split('\n')` 会在 \r-only/VT/FF/NEL/LS/PS 上分歧」。

### F. Q5：测试落点

**F17（recommendation：方案 a）新 tracked stage `v13/multilang/`，零新 SQL。**
- `.gitignore:32` = `/v13/demo/`（"never push"）——gate 不能住 demo；tracked 代码也不能 import `v13.demo.*`（fresh clone 上 absent）。
- `v13/load.py` 不要求 stage 有自己的 SQL：`STAGE_THROUGH` 固定 1–14（`:34-50`），新 stage 的 setup 直接 `load_stage(server, db, 'envelope')`（demo 先例 `v13/demo/setup_db.py:33`——plan 裁决加载停在 envelope）。tracked stage 形状先例：`v13/loop/{__init__.py, README.md, setup_db.py, test_loop.py}`（setup = DROP/CREATE + load_stage + run_probes，`v13/loop/setup_db.py:18-27`）。
- 否决 (b) 部分反忽略 demo：违反 demo 计划「本地副本、永不提交」的既定裁决，且拖 Chainlit/PostgREST 依赖入 tracked 面；否决 (c) demo-local：不是 gate（无里程碑证据力、他人不可复跑）。可选补充：在 `v13/demo/test_demo_loop.py` 加 W7 双工具用例作开发期烟囱，但里程碑证据以 tracked gate 为准。
- AGENTS.md 合规：`uv run python v13/multilang/test_multilang.py` 退出码 0 = 通过；无新 SQL → 无 `v13/load.py` 改动；stage README + 计划/评审台账按里程碑规则更新。

### G. Q6：等价断言

**F18（confirmed）比较面与排除面。** `tool/result` payload = `{tool, result, origin_user_seq}` + provenance effect_id（`v13_core.sql:352-358`）。**可断言相等**：`payload->'result'`（两侧都是我们控制的 worker 返回值——Swift 侧 = `json.loads(content[0].text)`，Python 侧 = 口岸直接返回）＋ 与本地期望切片的三方一致（v12 G6 范式：跨语言同输入同输出恒等，`v12/queue/test_queue.py:148-152`）。**构造性差异（必须排除）**：`effect_id` / `request_hash` / `idempotency_key`（uuid5 材料含 cycle 与 request 哈希，`v13_core.sql:175-183`——request 含 tool/handler 必不同）、`tool_name`、`request.{tool,handler}`、`created_at`、事件 `seq`、payload `tool` 名；llm/message 文本（窗内含不同 tool 名）。`tools_revision` 两侧同 turn 同目录快照——**可**断言相等。JSON 语义比较（psycopg2 取回即 str/dict），不做字节比较。

### H. Q7：风险登记核验

**F19（confirmed；superuser gate 可免）PGMQ 授权。** 评审 §2.1 阻断：`pgmq.send` 非 SECURITY DEFINER，`v13_route` 需 `USAGE ON SCHEMA pgmq` + `INSERT,SELECT,UPDATE ON pgmq.q_v13_work`（demo 落地 `v13/demo/setup_db.py:88-90` + 实机探针 `probe_send_work` `:244-277`）。但 tracked gate 以超级用户连接跑 advance（`v13/loop/test_loop.py:151-153` 先例；评审自注「M3 的工具用例是超级用户跑的」）→ 授权不适用。只有复刻 demo 的角色纪律（route_login 面上跑）才需要。

**F20（confirmed）子进程生命周期。** `LEASE_MS=180000`（`v13/demo/settings.py:25`）≫ 握手+读（实机亚秒级，热二进制）。推荐：**惰性单例客户端**——首次 Swift 分派时 spawn（此刻 claim 事务已提交、complete 事务未开，零打开事务），复用于后续调用，gate 收尾 stdin 关闭 + wait + `/tmp` profile 清理；stderr → DEVNULL 或排水线程（默认 .warning 量小，仍防管道写满死锁）。外部 IO 不进事务由结构保证（port 一调用一事务纪律，`v13/demo/port_pg.py:9-27`；tracked mini-hub 同形：commit after claim → subprocess → complete 事务）。

**F21（confirmed）二进制缺失的优雅跳过。** 先例 `v8/compat/test_compat.py:1132-1170`（not_run / credentials_absent → **exit 2**，绝不伪装 pass；demo smoke 同款语义）。gate 形态：探测 release→debug 两路径皆无 → 打印 `[SKIP] not_run/binary_absent` → exit 2；swift toolchain 缺失同理。绝不在 gate 内 `swift build`。

**F22（confirmed）其余小项。** (i) 每批 13 问 ≤ 32，快路单批，无 judge 慢路 effect；(ii) mini-hub 自带 tick 上限（mirror `MAX_TICKS=16`，`settings.py:27`）；(iii) mock 下 `SELECT typesafe_last_request()` 可钉判断线格式（评审 §2.3），调试批次时有用；(iv) tools INSERT/DELETE 使 revision bump——每相位重新 parse，在途信封弃批天然成立。

### 推荐测试设计草图

**文件（全部新 tracked，`v13/multilang/`）**：
- `__init__.py`、`README.md`（gate 命令、二进制前置、exit 2 语义、换行移植注记）
- `setup_db.py`：DB `agent_v13_multilang`；`load_stage('envelope')` + `run_probes`（照抄 `v13/loop/setup_db.py` 形状）
- `fixtures/hello.txt`（LF ASCII 4 行，带尾换行）+ `fixtures/crlf.txt`（可选）+ `fixtures/empty.txt`
- `read_file_port.py`：Swift readFile + resolvePath 的 Python 口岸（`re.split` 换行类、1-based/负尾/limit 钳制、越界 `""`、realpath root + 前缀围栏、严格 UTF-8）
- `mcp_client.py`：极小 stdio 客户端（spawn → initialize(protocolVersion "2025-11-25") → initialized → tools/list → tools/call；`json.loads(content[0].text)`；`isError` → 异常；stdin 关闭收尾）
- `test_multilang.py`：gate 主体

**流程**：
1. `setup_db.build` → 超级用户连接，session `SET typesafe.provider='fake'; SET typesafe.model='fake-judge'`
2. （负例，推荐）种子 max_cycles=3 下先跑双工具 session → 断言 `turn/end delivered=false reason=budget_exhausted`、status=failed（演示算术缺口）
3. 策略翻新 v2（F7 的两行 SQL）
4. runtime INSERT 两条 tools 行（param_spec 单选项 `path → hello.txt`；description/question/options 全 ASCII，满足 decisions 的 ASCII CHECK）→ 断言 revision bump
5. spawn Swift 客户端（`REPOPROMPT_MCP_WORKING_DIRS` = fixtures 目录 realpath、`REPOPROMPT_MCP_HEADLESS_PROFILE_DIR` = /tmp 隔离）→ initialize → tools/list 断言 read_file 在列
6. session + user message（"read hello.txt with both engines and compare"）
7. mini-hub 循环（parse[相位 mock 覆盖当批 13 问] → advance → claim → dispatch → complete）：cycle0 `tool/read_file_py`（口岸直调）→ cycle1 `tool/read_file_swift`（stdio）→ cycle2 llm（确定性 generate）→ advance → finish
8. 断言组：
   - A1 `turn/end delivered=true answered`；status=completed
   - A2 恰 4 条 `turn/route`；actions = [tool, tool, llm, finish]；tools = [read_file_py, read_file_swift]
   - A3 两条 `tool/result`：`payload->'result'` py == swift == 本地期望切片（三方恒等）
   - A4 两个 tool effects succeeded；`request.handler` 各归各；两 effect `tools_revision` 相等；`idempotency_key` 互异
   - A5 llm/message 锚定本 turn 且非空（确定性 compare 文本）
   - A6 无未决 effects；`v13_policy('turn_budget')->>'max_cycles' = '4'`
   - A7 decisions 中 `tool` 信号 ≥3 个不同 request_hash（每相位一代 ctx）
   - A8（envelope 面）`judgment_calls` ≥ 4（每 parse 一批）
   - 口岸单测矩阵（纯 Python 无 DB）：全文 / 1-based / 负尾 / limit 钳 / 越界 `""` / limit0 `""` / start0≡1 / 幻影尾元素 / CRLF 等价 / 空文件；Swift 侧同矩阵抽 3 点经 stdio 复核（含 tail(-1)→`""` 与 outside-roots isError）
9. 收尾：stdin 关闭 + wait + exit 0 断言；/tmp profile 清理

**难度登记（高→低）**：
1. **Swift 二进制可得性/可移植性**——硬外部依赖；exit 2 跳过保诚实，但意味着他机/CI 默认 not_run；缓解：README 记构建命令，里程碑实跑留证。
2. **换行/字符集纪律**——`re.split` 类口岸 + LF ASCII 主 fixture 后骤降；CRLF 用例转为等价断言。
3. **判断相位脚本**——自定义 mock 按相位覆盖 13 问；模式已有（answer_mock_5 / gap_mock），中低难度。
4. **预算翻新**——两行 SQL + 顺序约束，平凡。
5. **stdio 客户端鲁棒性**——帧法极简；stderr 排水 + 超时护栏即可。
6. **构造性差异簿记**——排除面清单见 F18，照单断言。
7. **多 root/绝对路径口岸分支**——单 root fixture 让主线无感，留口岸单测。

**未验证/存疑清单**：
- `protocolVersion` 字面量 "2025-11-25" 来自 fixtures + 本机实机（1.4.1）；SDK 升级可能改版——客户端不硬断言版本号，回读服务端值即可。
- `CharacterSet.newlines` 的 U+000A–U+000D 区间（含 VT/FF）依 Apple 文档，未跑 Swift 运行时逐字符验证；`re.split` 口岸在 LF/CRLF 主路径已实机对齐。
- 目录路径读取的错误文本（原生 NSError 形状）未实机取样；不对 error 文本做字节级断言即可规避。
- `v13/demo/test_demo_shim.py` 未细读（shim 内部线程模型），与本设计无载重关系。
- v13/demo 为 gitignored 本地副本：其行号以 2026-09-23 本机状态为准；设计已不依赖对 demo 的任何 import。

### I. 第二轮独立复核（2026-09-23 午后；逐文件自证 + 独立实机探针 + 双 explore probe）

**方法**：对上列 F1–F22 做独立重验。pg-agent 侧（v13 SQL 全部载重函数、loop/envelope 测试、demo 当日 12:16–14:19 文件）与 repoprompt-ce 侧全部载重代码点由本调查人逐行重读；另做一次**独立实机 stdio 探针**（spawn 既有 release 二进制 1.4.1；`REPOPROMPT_MCP_WORKING_DIRS=/tmp/mlt_probe_wd` + `REPOPROMPT_MCP_HEADLESS_PROFILE_DIR=/tmp/mlt_probe_profile` 隔离；initialize → initialized → tools/list → 15 例 read_file 矩阵 → stdin 关闭；零 build / 零 PG / 零 git）；两个 explore probe 分别交叉验证「Swift 切分/编码语义与测试覆盖面」「headless MCP 握手契约（文档 × 测试）」。**总裁决：F1–F22 全部成立（3 处行号勘误、2 处语义精确化），主假设可执行，无翻案项。**

#### I.1 F 系列复核总表

| F | 裁决 | 独立证据锚点（本调查人亲验） |
|---|---|---|
| F1 | confirmed | tools 表/守卫 `v13_core.sql:581-596`；`::` 禁令 + 仅校验 enabled sql 行 `:631-688`；revision bump `:706-712`；种子行 `:936-958`；W6 运行时 INSERT `test_demo_loop.py:336-340`、DELETE 恢复 `:377-381`、needed 公式 `9+4N` `:344`。needed=13 复算成立（4 固定+tool+4 种子参数+2×2） |
| F2 | confirmed | `driver.py:117`（tools dict）、`:211`（_dispatch 按 kind）、`:273-311`（_do_tool）、`:286-287`（`handler=request.get("handler"); fn=self.tools.get(handler)`）、`:288-292`（unknown → failed `demo_unknown_handler`）、`:293-297`（入参形状）。Swift 侧=包装 stdio 的普通 Python 函数，driver 无感 |
| F3 | confirmed | `resolve.sql:92-105`（tool 信号 criteria=enabled 目录+none）、`:108-125`（param::/stated:: 生成）；`advance.sql:111-163` v13_route P4c 全条件；`:486-513` 队列路 request 冻结 `{tool,params,handler,tools_revision}`（`:504`） |
| F5 | confirmed | `v13_core.sql:161-166` v13_cycle_no；预算步⑤ `advance.sql:332-334`（`v_cycles >= v_max` → human budget_exhausted），先于③（`:366+`）④（`:386`）；turn/route 事件 `:387`；种子 max_cycles=3 `v13_core.sql:753` |
| F6 | confirmed | 双工具 4-cycle 算术成立：cycle3 时 v_cycles=3≥3 → 预算分支（human effect 入队，需 hub 按 `_do_human` 结算 succeeded 后再一次 parse+advance 才落 turn/end failed——demo 断言5 `test_demo_loop.py:166-186` 已走通同构路径：3×low_intent_confidence + budget_exhausted → terminal failed/delivered=false/零未决）。canonical_state 窗含锚定 tool/result `resolve.sql:26-31`；request_hash 含 ctx `:130-148`；v13_gap `:363` |
| F7 | confirmed | `v13_core.sql:697-707`（PK+部分唯一 active）、`:715-729`（trg_policies_frozen：拒 DELETE、拒 name/version/value 改写、唯一许可翻 active）。先翻后插顺序约束成立 |
| F8 | confirmed+精确化 | `fakes.py:68-84` forced_llm（tool_seen ∧ ¬llm_seen → llm_generate，双工具 B 永不可达）；`:145` 未知 choice 兜底 `sorted(criteria)[0]`；test-local 包装先例 `test_demo_loop.py:167-176`。精确化见 N8 |
| F9 | confirmed（行号勘误 E2） | `harness.py:174-189` gap_mock、`:198-242` fake_judge_server；`test_demo_loop.py:352-366` judgment_calls 断言；凭据拒收现位于 `deepseek.py:71-72`（开 socket 前） |
| F10 | confirmed | `v13_envelope.sql:322-332` v13_guc_required（V3002）、`:495-499` runtime CTE 读 provider/model；正例 `test_envelope.py:128-130`（guc() 助手 set_config 两值）、负例 `:686-688`；`test_loop.py:67-68` set_mock、`:155` SET model |
| F11 | confirmed | 帧法亲验（`MCPStdioServerTransport.swift:144-156` 入帧按 0x0A 切/空帧跳、`:213-215` 出帧补单 `\n`、`:43` 16MiB 上限）；`DirectHeadlessMCPService.swift:72-79` Server(strict:true)；实机 initialize/initialized(静默)/tools/list 21 工具 read_file 在列/exit 0 |
| F12 | confirmed | `DirectHeadlessMCPService.swift:596-604` successResult（`[.sortedKeys,.withoutEscapingSlashes]` → 单 .text 块）；`:607-613` errorResult；`:341-366` catch 折叠。实机双重编码确认（见 N1/N3） |
| F13 | confirmed（行号微移 E3） | `DirectHeadlessRuntimeConfiguration.swift:18-20`（isolated=显式 profile∧非空 working dirs）、`:34-38`（profile≠default 才硬性要求 profile dir）、`:54-71`（否则回落 `~/Library/Application Support/RepoPrompt CE`）、`:82-86`（`:` 分隔）+ `:88-110`（绝对/存在/规范化去重）。二进制存在：release 52.8MB（09-18 16:55）+ debug 67MB（09-18 00:52），本日 ls 亲验 |
| F14 | confirmed（跨度勘误 E4） | `MCPDomainCanonicalWorkspaceService.swift:171-193` 逐行亲验：missing path invalidParams `:174-176`、strict UTF-8 `:178`、`.newlines` 切 `:179`、负尾忽略 limit `:183-184`、1-based `:186`、越界 `""` `:187`、`max(0,limit??count)` `:188`、join `"\n"` `:192`。实机 15 例全中（N1） |
| F15 | confirmed | `DirectHeadlessDomainContext.swift:302-333`：NUL/空白拒、绝对直用、单 root append（无存在性检查）、多 root 恰一存在否则 ambiguous、standardize+resolveSymlinks 后前缀围栏 `:331-334`；root 在 `:88-110` 已规范化（Python 口岸须 realpath root）。实机 outside → `pathOutsideWorkspace("../../etc/hosts")` |
| F16 | confirmed+精确化 | 见 N1/E5 |
| F17 | confirmed | `.gitignore:32`（恰第 32 行 `/v13/demo/`）；`v13/load.py:16-49`（14 SQL、STAGE_THROUGH 1-14，无新 SQL 则零改动）；`v13/loop/setup_db.py:18-27` 形状（DROP/CREATE+load_stage+run_probes）；demo 先例 `v13/demo/setup_db.py:34` STAGE="envelope" |
| F18 | confirmed | tool/result payload `v13_core.sql:369-371`（`{tool,result,origin_user_seq}`）；effect 身份含 cycle+request 哈希 `:175-183`。v12 G6 范式亲验 `v12/queue/test_queue.py:148-152` |
| F19 | confirmed | `v13/demo/setup_db.py:87-90`（GRANT INSERT sessions / USAGE pgmq / INSERT,SELECT,UPDATE q_v13_work 给 v13_route——因 pgmq.send 非 SECURITY DEFINER）；超级用户 gate 不适用 |
| F20 | confirmed | `settings.py:25` LEASE_MS=180000、`:27` MAX_TICKS=16（当日文件仍准）；`port_pg.py:1-19` 一调用一事务纪律 |
| F21 | confirmed | `v8/compat/test_compat.py:1131-1170`：not_run（not_requested / credentials_absent）→ exit 2，不伪装 pass |
| F22 | confirmed | 13≤32 单批；MAX_TICKS=16 足够双工具回合（≈9-10 tick）；`typesafe_last_request` 钉线格式可用 |

#### I.2 新增发现（N 系列）

**N1（实机）read_file 15 例矩阵——Python 口岸的参照表**。fixture：hello.txt=`line one\nline two\nline three\n`、crlf.txt=`a\r\nb\r\n`、empty.txt=``、nonl.txt=`x`、ls2028.txt=`a b\n`（均在 /tmp 工作根）。实机结果（content[0].text 经一次 json.loads 后）：

| 用例 | 实机输出 | 备注 |
|---|---|---|
| start_line=2,limit=2 | `line two\nline three` | |
| 全文 | `line one\nline two\nline three\n` | 尾换行保留在文本里 |
| start_line=-1 | `""` | **幻影尾元素**：末元素是空串 |
| start_line=-2 | `line three\n` | suffix 含幻影空元素 |
| start_line=99 | `""` | 越界非 error |
| limit=0 | `""` | |
| start_line=0 | 全文 | 0≡1 |
| crlf.txt 全文 | `a\n\nb\n\n` | **每个 CR 与 LF 各切一次：尾部两个幻影空元素**（4 字节文件 → 5 元素） |
| empty.txt | `""` | 空文件非 error |
| nonl.txt | `x` | 末行无换行无幻影 |
| ls2028.txt | `a\nb\n` | **U+2028 按 newlines 切分实机确认** |
| start_line="abc" | 全文 | 非整数被静默忽略（intValue nil） |
| nope.txt | isError + 原生 NSError 全文 | `Error Domain=NSCocoaErrorDomain Code=260 …` |
| ../../etc/hosts | isError `pathOutsideWorkspace("../../etc/hosts")` | enum case 的 String(describing:) |
| 缺 path | isError `[-32602] Invalid params: missing path` | MCPError 描述形态 |

三种错误均为 `isError:true` 单 text 块、**非 JSON-RPC error**（与 F12 一致）。断言纪律：只断 isError 与稳定前缀，不字节断言 NSError 文本。**精确口岸 = `re.split(r"[\n\r\v\f\x85  ]", text)` + join `"\n"`**——re.split 逐字符切、保留连续分隔产生的空分量与尾部分量，与 `components(separatedBy: CharacterSet.newlines)` 同构；朴素 `split('\n')`（`\r` 残留）与 `splitlines()`（CRLF 合并、丢弃尾空）都不等价。

**N2（实机）protocolVersion 是回显不是定值**。本探针发 `"2025-03-26"` 得回 `"2025-03-26"`；前次调查人发 `"2025-11-25"` 得同值回显——pinned swift-sdk（`Package.swift:21`，revision 85dec2f）接受多版本并回显客户端请求。客户端发送任一受支持版本、**回读服务端值即可，不硬断言字面量**（F11 的建议据此从「谨慎」升级为「已证实不必要」）。仓库内测试字面量仅 `2025-11-25`（`MCPExportWatchdogIntegrationTests.swift:3152`、`PersistentMCPResponseDeliveryTests.swift:85`）。

**N3（实机+代码）CLI 旗标面**。`--backend` 解析在 `Sources/RepoPromptMCP/main.swift:2574-2594`（默认 `app` `:2566-2567`——**必须显式 `--backend headless`**；非法值 exit 2）；headless 分派 `:3685-3687`；interactive/exec 旗标与非 app backend 互斥 `:2887-2890`。另有 `--tool-timeout <s>`（`:2596-2610`，0=禁用 CLI 侧超时）可作 gate 的额外护栏（可选）。

**N4（probe）headless read_file 切片零测试覆盖——三重确认**。`MCPDomainReadToolProviderTests.swift` 4 个测试全走 stub backend（`:23`），不触 readFile；`DirectHeadlessOracleGroupTests.swift` 无 read_file；全树唯一 `start_line` 测试是无关的 fixture parser。本 gate 是该路径的第一个行为锁（加固 F14 的判断）。

**N5（probe）app 版与 headless 版 read_file 行为分歧清单（移植契约必须锚定 headless 的实证）**：
- 切分器不同：app 用手写 `splitContentPreservingAllLineEndings`（`StringExtensions.swift:345-386`），**只认 `\r\n`/`\r`/`\n`**，不切 VT/FF/NEL/LS/PS；headless 用 `CharacterSet.newlines`（切全部）。
- 参数校验不同：app 对 `start_line=0`、负 start+limit 抛 invalidParams（`WorkspaceInteractiveReadCache.swift:74-78`）；headless 静默接受（0≡1、负尾）。
- 越界返回不同：app 返回带 `totalLines/firstLine/lastLine/message` 的 ReadFileReply；headless 返回裸 `""`。
- `offset` 别名：`MCPToolArgsNormalizer.swift:399` 白名单接受，但 headless 后端只读 `start_line`/`limit`（`:180-181`）——**接受后被忽略**。gate 的 README 应记录「不要用 offset」。

**N6（probe）仓库内无任何测试 spawn `repoprompt-mcp --backend headless` 二进制**。`docs/architecture/headless-mcp-runtime.md` 所称 direct process tests 在 `Tests/` 无对应物（唯一 in-process 近似 `DirectHeadlessOracleGroupTests.swift:1750`）；唯一完整 initialize→tools/call 往返测试走 **app 代理 Unix socket**（`MCPExportWatchdogIntegrationTests.swift:3149-3197`，帧法同为 LF 行分隔）。本 gate 是全仓库第一个 headless 二进制端到端 stdio 驱动（加固 F13）。

**N7（tracked 注入面）新 gate 不需要 demo 任何代码，也不需要自造 mock 生成器**。`v13/loop/test_loop.py` 自带：`mock_from_needed(cur, sid, **over)`（`:108-125`——按 `v13_needed_judgments` 当批信号自动生成合法答案 + 相位覆盖，天然处理目录扩容的新信号）、`parse`（`:127-130`）、`claim_pinned`（`:78-86`——先取消其他 ready 行再领目标，保证单 worker 确定性领取）、M3-11 P4c 工具路由完整配方（`:382-400`：intent=tool_action + tool=<name> + risk=0.5 + param/stated 覆盖）、M3-5 队列路断言（`:419-427`：advance=waiting、request 含 handler+tools_revision）、M3-7 预算负例（`:428-437`：手工补 3 条 turn/route 后 advance → human budget_exhausted）。双工具相位脚本 = 每相位一次 `parse(cur, sid, intent=…tool_action, tool=…read_file_py|read_file_swift, …)`，比 demo 的 answer_mock 包装更直接。

**N8（精确化 F8）demo 侧扩容目录必须包装 answer_mock**。`fakes.FakeJudge.answer_mock`（`fakes.py:164-171`）只喂 `sorted(SEED_SIGNAL_KINDS.items())`（9 信号，`:21-31`）——目录扩容后的 `param::read_file_py::path` 等新信号**不在答案集里**，而 mock/线响应必须恰覆盖当批信号（多/少 → V3001 整批拒，`fakes.py:246-251` 契约注释）。W6 的 `gap_mock`（按 `v13_gap` 当批生成）与断言5 的 test-local 包装是仅有的两个先例。tracked 面 `mock_from_needed` 无此问题（N7）。

**N9 demo 双 handler 呈现现状**。`app.py:207-208` 目前只挂 `tools=fakes.DEFAULT_TOOLS`（单 handler，`fakes.py:252`）。双 handler 共存 = 构造两键 dict `{"worker:read_file_py": fn_py, "worker:read_file_swift": fn_swift}` 传 `Driver(tools=...)`（`driver.py:117`）+ 运行时 INSERT 两条 tools 行（W6 形态）——driver/app 对「同名工具两实现」无任何特殊感知，分派键就是 handler 字符串。

**N10 ASCII CHECK 的三处精确归属**。`tools.description`（`v13_core.sql:583`，`^[\x20-\x7E]+$`）；`decisions.question`（`:398-399`，可打印 ASCII 且非空白）；`decisions.criteria` 即 options 表（`:422-423` `v13_decisions_criteria_ascii`，键与描述都受限）。新工具的 description/question/options 键与描述必须纯可打印 ASCII（选项键 `hello.txt` 天然满足）；param_spec 的 stated 文本进 question 同样受限。

#### I.3 勘误表（对 B1/B2/B3 与 F 系列）

- **E1（B1 + 任务描述）**：transport 文件路径写作 `Sources/RepoPromptMCP/Transports/MCPStdioServerTransport.swift`——实际**无 Transports/ 子目录**，正确路径 `Sources/RepoPromptMCP/MCPStdioServerTransport.swift`。
- **E2（F9）**：deepseek.py 凭据拒收现位于 `:71-72`（原引 60-66；文件当日 13:56 改动）。内容不变：开 socket 前抛 `NO_CREDENTIAL_MESSAGE`。
- **E3（F13）**：DirectHeadlessRuntimeConfiguration 行号微移——profile≠default 硬性检查 `:34-38`、回落真实 profile `:54-71`、WORKING_DIRS split `:82-86`、校验 `:88-110`。结论全部成立。
- **E4（F14/F12）**：readFile 精确跨度 `:171-193`（grep 钉死）；errorResult `:607-613`。
- **E5（F16）**：CRLF 例补充——`"a\r\nb"`（串中）→ `["a","","b"]` 正确，但**CRLF 结尾的文件尾产生两个幻影空元素**（N1 实机：`a\r\nb\r\n` → `a\n\nb\n\n`）。口岸单测矩阵须含此用例。
- **E6（B2）**：`_do_tool` 实际 `driver.py:273-311`（原引 273-307）；F2 已自行修正，无实质问题。
- **E7（F1 措辞）**：「decisions 的 ASCII CHECK」归属成立，精确锚点见 N10。
- **E8（任务 file_map）**：`Sources/RepoPromptExecutable` 不是 repoprompt-mcp 入口——产品入口是 `Sources/RepoPromptMCP/main.swift`（见 N3）。
- **E9（B3 补充）**：demo 的 `deepseek.py`（当前版）同样**无 `tools=[...]` 参数**（请求体仅 model/messages/stream/temperature/response_format，`:76-87`）——B3 关于 v8 runtime 的结论在 demo 侧同样成立；工具选择完全在判断平面（shim 的 judge system prompt 强制 `{"answers":{...}}`，`shim.py:60-67`；tool 动作=判断面 choice 信号答案）。

#### I.4 必答六问的复核后回答

**Q1 read_file Swift 精确语义**：见 F14/F15/F16 + N1/N5。切分 `CharacterSet.newlines`（U+000A–U+000D 含 VT/FF、U+0085、U+2028、U+2029，逐字符独立切、保留空分量与尾分量）；start 1-based（0≡1）、负=末 |start| 行且 limit 被忽略、越界/limit≤0 → `""`、缺省全文、非整数静默忽略；join 恒 `"\n"`。编码：域结果（JSON 字符串）经 `JSONEncoder([.sortedKeys,.withoutEscapingSlashes])` 放进**单个 .text 块** → `content[0].text` 是**双重编码的 JSON 字符串字面量**，客户端 `json.loads` 一次得原文（N1 实机）。Python 等价写法：`re.split` 类口岸（N1）+ `json.dumps(..., ensure_ascii=False)`（语义比较面无关外层转义；**若做字节比较则必须 ensure_ascii=False**——Swift JSONEncoder 不转义非 ASCII，而 json.dumps 默认转义）。分歧风险清单：CRLF 双幻影（E5）、U+2028/2029 切分（N1 实机）、`split('\n')`/`splitlines()` 陷阱（N1）、`offset` 别名（N5）、app/headless 分歧（N5）。

**Q2 headless 子进程契约**：启动 `REPOPROMPT_MCP_WORKING_DIRS=<abs>[:…] REPOPROMPT_MCP_HEADLESS_PROFILE_DIR=<abs> .build/release/repoprompt-mcp --backend headless`（必须显式 headless，N3；profile dir 隔离必设，F13）。握手：`initialize`（params `{protocolVersion, capabilities:{}, clientInfo}`）→ 读回显（N2）→ `notifications/initialized`（静默；带不带 `params:{}` 均可——实机不带、测试带，`MCPExportWatchdogIntegrationTests.swift:3232-3237`）→ 可选 `tools/list` → `tools/call`（params `{name, arguments}`）。帧=换行分隔 JSON、无 Content-Length（入 0x0A 切 `MCPStdioServerTransport.swift:144-156`、出补 `\n` `:213-215`、入帧上限 16MiB `:43`）。错误=isError text 非 JSON-RPC error（N3）。二进制已存在（F13/I.1）。缺失降级先例=not_run/exit 2（F21）。

**Q3 v13 gate 流**：M3-5/M3-11 复用点见 N7；v13_route 工具名校验=信封冻结 `tools_catalog` 查 kind/enabled（`advance.sql:141-146`，未收录/disabled → human tool_unavailable）；tool 队列路 request 冻结四元组（`:486-513`）；claim/complete 契约（`v13_core.sql:267-289`/`300+`）。**落点裁决：新建 tracked `v13/multilang/`，零新 SQL、gate 内直接 INSERT 两条 tools 行（DML，W6 先例）**；`v13/load.py` 不动（F17）；不 import demo（gitignored，`.gitignore:32`）。教程 ch08 §8.4 G6 原文（`08-multi-language-harness.md:79-94`）与 §8.5 练习3（`:96-103`：「用 tools.handler 加第三种 handler，只 INSERT 目录行 + 起进程，跑通一个 turn。改了几个 SQL 文件？应为零」）**与本 gate 形态逐字对齐**——本 gate 即练习3 的兑现（以真 Swift 进程替 fake）。注：§8.4 G6 列出的「双 handler 同队列各领各的」依赖 claim 侧 handlers[] 过滤，v13_claim 未实现（B2 缺口确认）——单 hub 分派形态下不受影响，README 记为已知偏差。

**Q4 demo 现状（当日文件重验）**：driver 分派（F2/N9）；request/response 形状（`:293-297` 入参、返回值原样进 tool/result 的 result）；tool/result 事件由 `v13_complete` 落（`v13_core.sql:369-371`）；judge/parse：fake=answer_mock 注入（`driver.py:158-161` 区域）/slow=gap_mock+fake_judge_server（F9）、real=shim（`shim.py:60-67` JSON-only judge prompt）；**deepseek.py 无 tools=[...]（E9）**；双 handler 呈现=N9。demo 文件清单（14:19 时点）：app/chainlit.md/check_w34/contract/deepseek/driver/fakes/harness/port_pg/port_rest/probe_rest_gucs/probe_rest_port/pyproject/README/settings/sql/test_demo_loop/test_demo_shim/test_demo_smoke/uv.lock。

**Q5 难点与风险**：全部经 F19–F22 + N1–N6 复核成立。补充：(i) stderr 排水（默认 .warning 量小仍须防管道写满）；(ii) `--tool-timeout` 旗标可选护栏（N3）；(iii) `protocolVersion` 回读不硬断言（N2）；(iv) error 文本不字节断言（N3）；(v) 口岸 root 必须 `os.path.realpath`（F15——`/var`→`/private/var` 类假阳性）；(vi) demo 14:19 仍在演进——gate 不依赖 demo 任何 import 后此风险归零（F17）。

**Q6 裁决与路径**：见 I.5。

#### I.5 最终裁决与实施清单

**选型：read_file**（维持 F 草图）。理由加权：语义面 15 行纯 Foundation（`:171-193`）、零外部依赖、输出确定（get_file_tree 的 FileManager.enumerator 目录序未定义是硬风险，B1 排名第 2 的代价）；只读免授权（`isProtectedFamily` 名单 `MCPDomainProtectedMutationToolProvider.swift:115-121` 不含 read_file——亲验）；且其 headless 切片路径**零测试覆盖**（N4），本 gate 同时补上第一个行为锁，证据价值双份。

**Gate 形态（终版）**：tracked `v13/multilang/`：
- `__init__.py` / `README.md`（gate 命令、二进制前置与构建命令、exit 2 语义、app/headless 分歧与 offset 注意、换行口岸注记）
- `setup_db.py`：DB `agent_v13_multilang`，`load_stage('envelope')` + `run_probes`（照抄 `v13/loop/setup_db.py:18-27`；envelope 足够——本 gate 不需要 characterize 及以后）
- `fixtures/`：hello.txt（LF ASCII 4 行带尾换行）、crlf.txt、empty.txt、nonl.txt、ls2028.txt（可选）
- `read_file_port.py`：Swift readFile+resolvePath 口岸（`re.split` 换行类、1-based/负尾/limit 钳/越界 `""`、realpath root+前缀围栏、严格 UTF-8）
- `mcp_client.py`：极小 stdio 客户端（spawn→initialize→initialized→tools/list→tools/call；`json.loads(content[0].text)`；isError→异常；stdin 关闭+wait 收尾；stderr 排水；懒 spawn 单例——首次 Swift 分派时启动，claim 事务已提交、complete 事务未开）
- `test_multilang.py`：gate 主体。默认全跑 Swift 侧；`--no-swift-mcp` 跳过；二进制/toolchain 缺失 → `[SKIP] not_run/binary_absent` + **exit 2**（F21 先例；探测 release→debug 两路径）

**流程（对 F 草图的修正版）**：
1. setup → 超级用户连接，`SET typesafe.provider='mock'; SET typesafe.model='jev-mock'`（F10；`test_envelope.py:128-130` 形态）
2. 负例：种子 max_cycles=3 下双工具 session（相位 mock：py→swift→llm）→ 断言 turn/end delivered=false reason=budget_exhausted、status=failed、零未决（断言5 形态 `test_demo_loop.py:166-186`；human effect 由 hub `_do_human` 式结算后再一轮 parse+advance 收尾）
3. 策略翻新 v2（F7 两行 SQL，先翻后插）
4. INSERT 两条 tools 行（`read_file_py`/`read_file_swift`，handler `worker:read_file_py`/`worker:read_file_swift`，param_spec 单参数 `path` 单选项，全 ASCII——N10）→ 断言 revision bump；用毕 DELETE 恢复 + 再 bump（W6 形态）
5. Swift 客户端懒 spawn（env 围栏=fixtures realpath + /tmp profile）→ tools/list 断言 read_file 在列
6. 正例 session：mini-hub 循环（相位 mock 用 `mock_from_needed` 形态 + `claim_pinned` 确定性领取，N7）：cycle0 tool/read_file_py（口岸直调）→ cycle1 tool/read_file_swift（stdio）→ cycle2 llm（确定性 generate）→ cycle3 finish
7. 断言组 A1–A8 照 F 草图（比较面=`payload->'result'` 三方恒等：py==swift==本地期望切片，v12 G6 范式；排除面照 F18：effect_id/request_hash/idempotency_key/tool_name/request.{tool,handler}/seq/created_at/llm 文本）
8. 口岸单测矩阵（纯 Python）：N1 表全 15 例（不含 DB）；Swift 侧同矩阵经 stdio 抽验（含 tail(-1)→`""`、outside isError、CRLF 双幻影）
9. 收尾：stdin 关闭 + wait + exit 0 断言；/tmp profile 清理；恢复 tools 目录

**demo 可见示例（可选加项）**：`app.py` 的 `Driver(...)` 构造处（`:207-208`）扩为双 handler dict + 启动时 INSERT 两条 tools 行 + FakeJudge answer_mock 包装（N8）——非里程碑证据面，仅本地烟囱；提交版 gate 不依赖它。

#### I.6 未验证清单的消解与残余

- `protocolVersion` 字面量：**已解**（N2 回显；客户端回读）。
- `CharacterSet.newlines` 集合：U+2028 切分已实机确认（N1）；VT/FF/NEL/LS/PS 未逐字符实机——但 `re.split` 口岸类与 Swift 语义同构，风险收敛到口岸单测（可后续用 /tmp fixture + 二进制逐字符抽验补证）。
- 目录路径 NSError 文本：已取样（N3），按「不字节断言」纪律规避。
- `v13/demo/test_demo_shim.py` 内部线程模型：维持不读（与本设计无载重关系）。
- 残余：CI/他机默认 not_run（二进制缺失）——README 记构建命令 `cd repoprompt-ce && swift build --product repoprompt-mcp -c release`，里程碑本机实跑留证。

## Investigation Log

- **2026-09-23 Phase 1（本 agent）**：任务分诊；校正过期 memory（v13 已于 09-22/23 重落 DP1–DP8 + demo 计划 `aa106b7`，非「零开工」）；建报告骨架。
- **Phase 1.5（3×explore 并行）**：RP-CE 工具清单与移植性（B1）、v13 时间线与工具面（B2）、历史工具调用/测试先例（B3）。
- **Phase 2（context_builder）**：29 文件选区（~102k tokens）+ 架构摘要；其 Oracle 双 lane 当时 provider 报错。
- **Phase 3（pair investigator，opus[1m]）**：v13 SQL/demo 逐文件自证 F1–F22 + 设计草图 + 难度登记；含对既有 release 二进制的**实机 stdio 探针**（隔离 profile、零 build）。
- **Phase 4（Oracle 双 lane：grok-4.6@xhigh / grok-4.7-build）**：选型、测试形态、里程碑、遗漏难点四问终裁（两 lane 全文存于会话记录；分歧仲裁见下节「裁决与分歧」）。
- **Phase 5（本 agent）**：抽查四个承重锚点全部核实——`v13_core.sql:753`（turn_budget 种子=3）、`advance.sql:330-337`（预算步⑤先于③④建账）、`MCPDomainCanonicalWorkspaceService.swift:171-193`（readFile 切片语义逐行一致）、`v13/loop/test_loop.py:67-68`（GUC mock 先例）；落终稿。

## 结论：现状 / 难点 / 选型判定

### 现状

**v13 已给出来的**（file:line 均经 investigator 核实 + 本 agent 抽查）：

- 两相环：`v13_parse`（无会话锁，快路 ≤1×32 问）→ `v13_advance`（`FOR UPDATE`，七键探针 stale 检查，P0–P5 路由）。
- **工具目录是数据**：`tools(name, kind∈{sql,tool,llm}, handler, param_spec, enabled)`（`v13_core.sql:579-590`）；DML 经 `trg_tools_bump` 推 `tools_revision`；信封冻结 `tools_revision+tools_catalog`；路由/参数/handler 只读冻结面。运行时 `INSERT INTO tools` 有 M3-3/M3-15/demo W6 三重先例，**零 SQL 文件改动**（tutorial ch08 §8.5 练习 3 与本任务同构）。
- `kind='tool'` → `v13_enqueue_effect(request={tool,params,handler,tools_revision})`（handler 在 enqueue 时冻结）+ pgmq 唤醒 + `waiting`；worker 合同 `v13_claim`→进程外 IO→`v13_complete`（fence CAS）。
- **工具选择全在判断平面**：`tool` choice 信号 criteria=启用目录名∪none（`v13_resolve.sql:97-105`）；全树无 `tools=[...]`、无 `message.tool_calls` 解析。
- 策略版本化：`v13_policies` append-only，`turn_budget` 可「翻 active+INSERT v2」数据式上调；且 `turn_budget` **不在**七键探针里，翻新不打 stale 在途 snap（会打 stale 的是 tools 的 INSERT）。
- 先例：v12 G6 跨语言恒等（SQL uuid_v5 == Python uuid5）、v7 `subprocess.run` 第二进程、v8 `--real-provider-smoke` exit 2 纪律；**全仓库无 MCP/JSON-RPC 测试先例——本 gate 将是第一个**。

**v13 明确没给的**：`v13_claim` 无 `handlers[]` 过滤（教程写了、SQL 未实现；双语隔离只住在 hub 的 handler 查找）；tools 表无 ch06 的 `input_schema/mutating/timeout_ms` 等列；A15 四值 `result_kind` 零实现；无已提交的多语言 worker/gate；`v13/demo/`（含 driver.py 的 `self.tools[handler]` 扩展点）gitignored，tracked 代码不可 import。

**RP-CE 已给出来的**：`repoprompt-mcp --backend headless`（`swift build --product repoprompt-mcp -c release` 可构建；本机 release 1.4.1 + Swift 6.3.2 已在位）；stdio 换行分隔 JSON-RPC 无鉴权；只读工具无变更门；实机验证：initialize→`protocolVersion "2025-11-25"`、`tools/list` 可见 21 个（28 的 policy 过滤子集）、`read_file` 成功结果为**双重编码** `.text`（`json.loads` 一次得原文）、失败走 `isError:true`（越界 → `pathOutsideWorkspace("…")` 枚举字面量，非友好文案）、stdin 关闭干净退出。隔离必须显式 `REPOPROMPT_MCP_HEADLESS_PROFILE_DIR`（否则回落用户真实 `~/Library/Application Support/RepoPrompt CE`）+ 绝对已存在的 `REPOPROMPT_MCP_WORKING_DIRS`（`:` 分隔）。

### 难点（按实施风险排序）

1. **Swift 制品是 macOS 外部依赖（最高优先级政策碰撞）**：无二进制/无工具链机器（Linux CI、fresh clone）上 Swift 三方恒等不可跑。诚实的 `not_run/binary_absent → exit 2` 与 AGENTS.md「全 gate 绿才许提交」不能压在同一条默认命令上——必须把 Swift 侧做成 opt-in（见建议），里程碑绿 = 有二进制机器上的 exit 0 留证。gate 内禁止 `swift build`。
2. **行为等价不是字节平凡**：换行类（Swift `components(separatedBy:.newlines)` 逐字符切 U+000A–U+000D/U+0085/U+2028/U+2029，`"a\r\nb"`→`["a","","b"]`；Python `splitlines()`/`split("\n")` 均不等价，精确口岸 = `re.split(r"[\n\r\v\f\x85  ]", text)`）；幻影尾元素（`"a\nb\n"` 切 3 段，`start_line=-1` → `""`）；`start_line=0≡1`；越界/limit≤0 → `""` 非 error；严格 UTF-8；root 先 `realpath` 再前缀围栏（/var→/private/var）；双重编码信封。主 fixture 用纯 LF ASCII 后骤降；CRLF 转为等价断言；**错误只比分类不比文案**（Swift 是 `isError` 文本/NSError，Python 是异常，形态按构造不同）。
3. **预算算术**：cycle=本 turn `turn/route` 条数，预算步⑤先于③④建账（`advance.sql:330-337`）；双工具闭环最小 4 cycle（tool→tool→llm→finish），种子 3 必 `budget_exhausted→failed`；修复=两行 SQL 数据翻新（先 `active=false` 再 INSERT v2，顺序由部分唯一索引强制）。
4. **v13 不变量纪律**：外部 IO 只能在 claim 提交之后、complete 事务之前（hub 一 RPC 一事务）；FS 禁入变更相（errata 5.2 → `read_file` 必须是 `kind='tool'`，不能做 sql 快路）；单 session 单活跃 effect（complete 后再 parse/advance）；tools INSERT 后必须**新开 session**（revision bump→在途信封 stale，且 canonical_state 含工具→全部 request_hash 漂移→每相位 13 问整批重问）。
5. **判断相位脚本**：stock FakeJudge 的 `forced_llm` 会在首件 tool/result 后强制 llm——**开不出双工具回合**（有意设计）；须按相位自定义 mock（数本 turn 锚定 tool/result 条数：0→py、1→swift、≥2→llm）；`stated::…::path` noul 必须 ≥0.60 否则参数被省略（两侧都读不到文件）；种子邮件工具的 4 个 param/stated 每批也要给合法答案否则 `remaining>0` 卡死。
6. **stdio 客户端细节**：紧凑单行 JSON+`\n`（pretty-print 会被 0x0A 切碎）；`notifications/initialized` 无响应不可读；stderr 必须 DEVNULL/排水（防管道写满死锁）；`protocolVersion` 回读不硬断言；读超时→`complete(failed)`，**不做**「让 Swift 晚结算断言 stale」的练习（tool 租约过期→`unknown` 墙，无恢复路）。
7. **比较面簿记**：可比 = `result` 的 JSON 语义值 + `origin_user_seq` + 两侧 `tools_revision`；必异 = effect 身份列/`request_hash`/`idempotency_key`/handler 名/事件 seq/payload 里的 tool 名；llm 文本非空即可（空文本被降级 `llm_result_shape` 不写 `llm/message`，P0 永不触发——llm 步省不掉）。

### 选型判定

**采用：headless `read_file`。** 依据：验收句是「相同效果」，可比的是同输入同输出，不是「两种语言在哪里必然分歧」；read_file 契约短且实机已钉死，跨语言纪律（换行类/幻影尾/围栏/双重编码）已足够撑起「多语言」命题——多语言点本身落在 v13 的同一目录行+同一 claim→IO→complete 合同上。参数只暴露 `path`（单选项键即路径值）；`start_line/limit` 的等价放口岸矩阵 + 4 点 stdio 抽检，不进判断平面（三条参数全进 param_spec 会多 8 个信号、逼 mock 选行号，对命题无增量）。

**拒绝**：`get_file_tree`（`FileManager.enumerator` 目录序未定义，测试会变成在测排序包装）；`file_search`（ICU≠re/wildmatch/locale folding，移植度~55%，那是另一份「分歧展览」报告的题目）；`apply_edits`/`file_actions`（变更授权 + C 缩进编解码/Trash 语义）；把 `read_file` 做成 sql 快路（违 errata 5.2）；复刻 app 版 `ReadFileReply`（契约锚定 headless 裸 JSON 字符串）。

### 裁决与分歧（两路 Oracle 仲裁记录）

两路 Oracle 在选型、落点、GUC mock、三方恒等、exit 2 纪律上完全一致。两处分歧由本 agent 仲裁：

1. **预算负例是否整段进 gate**：Oracle1 主张轻量 A0（双 handler 均走 Python 口岸、无 Swift 依赖、可与正例共用目录 INSERT）；Oracle2 主张降为两条数据断言（翻新前 active=3/翻新后=4，理由：预算墙归属 `v13/loop` gate，整段 session 冗余）。**仲裁：纳入轻量 A0**——它锁定本 gate 自身的前置算术（防止后人把策略改回 3 后主路径「莫名」红），成本仅一个短 session，且在无 Swift 机器上随默认命令一起绿；同时采纳 Oracle2 的两条数据断言作为 A0 的一部分。若实施中发现 A0 噪声大，允许降级为纯数据断言（二选一，报告两案并陈）。
2. **里程碑切分**：Oracle1 三段（M1 口岸矩阵→M2 stage+opt-in MCP→M3 可选）；Oracle2 单笔实现提交（「没有 stdio 抽检的 Python 矩阵只是在复述自己的假设」，故口岸与抽检不可拆两笔）。**仲裁：合并为「文档一笔 + 实现一笔」**（Oracle2），但吸收 Oracle1 的关键洞察——默认命令必须无 Swift 也可 exit 0（仓库自有先例：`--real-provider-smoke` 就是 opt-in 子测试），Swift 三方恒等走 `--with-mcp` 开关；里程碑绿 = 作者机 `--with-mcp` exit 0 留证。
3. **握手时机**（次要分歧）：Oracle1 惰性 spawn（首次 Swift 分派时）；Oracle2 会话前握手（spawn+initialize+tools/list 先于任何 claim，handler 只做 `tools/call`；握手失败时不留 claimed effect）。**采纳 Oracle2**。

## Recommendations（实施建议）

### 1. 落地包（全部新 tracked，`v13/multilang/`）

`__init__.py`、`README.md`（gate 命令、二进制前置与构建命令、exit 2 语义、换行口岸注记）、`setup_db.py`（库 `agent_v13_multilang`，照 `v13/loop/setup_db.py` 形状：DROP/CREATE→`load_stage(server, db, "envelope")`→`run_probes`）、`read_file_port.py`（Swift readFile+resolvePath 的 Python 口岸）、`mcp_client.py`（极小 stdio 客户端）、`fixtures/hello.txt`（LF ASCII 带尾换行）+ `fixtures/crlf.txt` + `fixtures/empty.txt`、`test_read_file_port.py`（口岸矩阵，无 DB 无子进程）、`test_multilang.py`（gate 主体）。**`v13/load.py` 与全部 `v13/**/*.sql` 零 diff；不 import `v13.demo`；不引入 `demo_*` RPC 面，直调 `v13_parse/v13_advance/v13_claim/v13_complete`。**

### 2. 工具目录行与判断驱动

- 两条 `kind='tool'` 行：`read_file_py`/handler `worker:read_file_py`、`read_file_swift`/handler `worker:read_file_swift`；`param_spec` 单键 `path`、单选项**键=相对路径** `hello.txt`（`v13_resolve_tool_params` 取的是 choice 键不是描述句）；description/question/stated/options **全 ASCII**（`tools.description ~ '^[\x20-\x7E]+$'` CHECK；判断题面进 decisions 同样避非 ASCII）。
- 判断驱动 = 会话级 GUC mock（`v13/loop/test_loop.py:67-68` 先例）：`SET typesafe.provider='fake'`/`SET typesafe.model='fake-judge'` **会话级**（`set_config(...,false)`；事务级对 provider 静默丢值→V3002）；`typesafe.mock_response` 每次 parse **前同事务** `set_config(...,true)` 写满 13 问（含种子邮件 tone/audience；intent/gate_action/tool confidence 0.9、`gate_off_topic` noul 0.1、`risk` score 0、两个新工具 `stated::…::path` 0.9）；相位只看本 turn 锚定 tool/result 条数（0→`tool=read_file_py`；1→`tool=read_file_swift`；≥2→`intent=llm_generate`+`tool=none`）。每次 parse 后断言 `remaining=0`。不实现 judge 慢路、不抄 FakeJudge HTTP 面。

### 3. gate 顺序（`test_multilang.py`）

1. setup（超级用户）；GUC 就位。
2. 数据断言：active `turn_budget`=3 → 翻新（先 `UPDATE active=false` 再 `INSERT v2 {"max_cycles":4}`）→ 断言=4。
3. `INSERT` 两行 tools；断言 `tools_revision` 上升；**此后不再改 tools**，目录变更后一律新开 session。
4. （A0 轻量预算负例）种子策略未翻新前或独立短 session：双 handler 均走 Python 口岸跑双工具 turn → 断言 `turn/end delivered=false reason=budget_exhausted`、status=failed、无未决 effect（见裁决 1；可与步骤 2 合并编排）。
5. **会话前握手**（`--with-mcp` 模式）：spawn `repoprompt-mcp --backend headless`（env：`REPOPROMPT_MCP_HEADLESS_PROFILE_DIR=<tmp>`、`REPOPROMPT_MCP_WORKING_DIRS=<fixtures realpath>`）→ `initialize`（回读 protocolVersion，不硬断言）→ `notifications/initialized`（不读响应）→ `tools/list`（只断言 `read_file` 在列，实机 21≠28）；完成 4 点 stdio 抽检：LF 全文三方相等、`start_line=-1`→`""`、CRLF 与口岸同值、越界路径 `isError` 含 `pathOutsideWorkspace`。
6. 新 session + user message（如 "read hello.txt with both engines and compare"）；mini-hub 循环：每相位写 mock→commit parse（断言 remaining=0）→advance（`SET LOCAL lock_timeout='250ms'`, `statement_timeout='5s'`）→`waiting` 则 commit claim→按 `request.handler` 分派（py=口岸纯函数；swift=已握手子进程 `tools/call`，读超时→`complete(failed)`）→commit complete；llm 相位用确定性非空文本；tick 上限 8–16（绑定约束是 max_cycles）。
7. 断言组：`turn/end delivered=true` 且 status=completed；恰 4 条 `turn/route`=[tool,tool,llm,finish]、tools=[read_file_py,read_file_swift]；两条 `tool/result` 的 `result` **三方恒等**（py==swift==本地期望切片）；两 effect succeeded、`tools_revision` 相同、handler/`idempotency_key` 不同；`origin_user_seq` 相同；无未决 effect；`tool` 信号 ≥3 个不同 `request_hash`。
8. `finally`：关 stdin→wait→断言子进程 exit 0→删 tmp profile。

### 4. 命令形态（政策碰撞的解法）

- **默认** `uv run python v13/multilang/test_multilang.py` = 口岸矩阵 + A0 + **双 handler 均走 Python 口岸**的完整 v13 环（锁 cycle 算术/判断相位/目录机制/v13 半边等价）——**任何机器 exit 0，无 Swift 依赖**，满足 AGENTS.md「全 gate 绿」。
- **`--with-mcp`**（或 env `REPOPROMPT_MCP`）= 追加 Swift 三方恒等 + 4 抽检；缺二进制/工具链 → `[SKIP] not_run/binary_absent` → **exit 2**（v8 `--real-provider-smoke` 同款语义，绝不伪装 pass）。有二进制而不一致 → exit 1。
- 里程碑绿的定义 = 作者机（本机已有 release 1.4.1）`--with-mcp` exit 0，日期与命令写进 stage README；gate 内禁止 `swift build`，构建命令只写 README（`cd repoprompt-ce && swift build --product repoprompt-mcp -c release`）。

### 5. 里程碑

- **本次提交**：本调查报告（纯文档）。
- **下一次提交（唯一实现里程碑）**：`v13/multilang/` 整包（口岸+客户端+矩阵+4 stdio 抽检+PG gate+README）——口岸矩阵与 stdio 抽检**不拆两笔**（没有 Swift 对照的 Python 矩阵只是在复述自己的假设）；全绿后按 AGENTS.md 提交推送。
- **明确不做/后置**：真 DeepSeek judge 冒烟（要在 tracked 树重做 shim，且低置信走 human，不增加多语言信息量）；demo W7 烟囱（gitignored，仅开发期）；ch08 练习 2「晚结算断言 stale」（tool 过期→unknown 墙）；claim 侧 `handlers[]` 过滤补实现（另一项工作，本 gate 单 hub 单认领者即可）。若后续做多语言扩展，可另立 investigation。

### 6. 后续自然延伸（非本例范围，仅记录）

- `v13_claim` 加 `handlers[]` 过滤（兑现 tutorial ch08 §8.2 承诺）后，Swift 侧才可能升级为独立认领 worker；
- provider 原生 `tool_calls`（改 shim/typesafe 面，v8 侧需 3 处编辑的同构工作）；
- A15 四值 `result_kind` 落地后，「工具失败→wait 重试」才有表达位。

## Preventive Measures

- **提交前 diff 自查**：`v13/load.py`、`v13/**/*.sql`、`.gitignore` 零改动；无 `v13/demo/` 下文件；tracked 代码不 import `v13.demo`。
- **profile 隔离是安全边界**：启动命令永远带 `REPOPROMPT_MCP_HEADLESS_PROFILE_DIR` 指向临时目录并测完删除——漏设会写进用户真实 `~/Library/Application Support/RepoPrompt CE`。
- **hub 事务切点写死**：parse/advance/claim/complete 各自提交；`tools/call` 时连接上无未提交事务；单线程单认领者，Swift 二进制不调 `v13_claim`。
- **口岸纪律**：禁 `splitlines()`/`split("\n")` 充当口岸（前者吞 `\r\n` 还多切 U+001C–U+001E）；用 `re.split` 同字符集逐字符切 + `"\n"` join；CRLF 期望值 = 切分后重连结果，不用原始字节；文件头注明契约锚定 headless 字符串而非 `ReadFileReply`/spec 里的 `worktree_scope`。
- **跨语言断言纪律**：错误只比分类（isError/异常）不比文案；`protocolVersion` 回读不硬断言；`tools/list` 不断言 28；`effect_id`/身份列不进等价断言；llm 文本非空即可。
- **不测清单**（写进 README 防后人「补全」）：16MiB 帧上限、VT/FF/NEL 逐字符运行时验证（CRLF 抽检覆盖主分歧）、多 root/绝对路径分支（留口岸单测）、NSError 原文、ch08 练习 2 晚结算。
- **exit 语义**：无二进制 exit 2 不算绿也不伪装；有二进制不一致 exit 1；不把 exit 2 收编成 exit 0。
- **目录变更后新开 session**；每相位重新 parse；不拿旧 snap 跨 INSERT。
- **stderr 永不接未阅读管道**；请求帧单行紧凑 JSON；`initialized` 后不读。


---

## K. 第三轮终审补遗（2026-09-23 晚；对 §3/§4 的增量修正，实施前必读）

本节来自另一会话的独立 Oracle 终审（grok-4.7-build-fast）+ 编排者亲证（`v13_core.sql:583` 的 tools.description ASCII CHECK 在 INSERT 时执法、`:692-694` 的 `trg_tools_bump` 为行级触发）。终稿主体已含该轮结论；以下为终稿未覆盖、实施时会咬人的增量：

1. **`v13_complete` 的 `p_result` 必须 `json.dumps(text)`（一次）**。`hello.txt` 正文非合法 JSON，裸文本绑 jsonb 直接解析失败；内容恰为 `true`/`42`/`{...}` 时少这层会静默存成错误 JSON 型——顺手断言 `jsonb_typeof(effects.result) = 'string'`。fixture 禁 U+0000（Swift 能读进 String、jsonb 拒 `\u0000`，会在 complete 才炸）。
2. **§3 步骤 2/3/4 顺序须重排为：INSERT tools → A0 负例 → 翻新 turn_budget → 正例**。按编号顺序（先翻新后 A0）负例永远撞不到墙（max=4 下双工具回合正常完成而非 budget_exhausted）；A0 又必须在 INSERT 之后（`tool` choice 的 criteria 需两工具名已入目录）。即：GUC 就位 → INSERT 两行（断言 Δrevision=**2**——行级触发、两条 INSERT 各 bump 一次，勿写死 +1、勿断言绝对值）→ A0（budget=3 仍 active）→ 翻新 v2 → 握手 → 正例新 session。
3. **A0/负例的收尾多一轮**：第 4 次 advance 只入队 `kind='human'`（返回 waiting，**尚无 turn/end**）；hub 必须认领并结算该 human effect（`v13_complete(succeeded)`）后，再一轮 parse+advance 才见 `turn/end delivered=false / budget_exhausted / failed`——mini-hub 分派循环要有 `kind=='human'` 分支，否则该行停在 claimed，session 收不住。
4. **翻新两句放同一事务**：先 `UPDATE … SET active=false`（断言 rowcount=1）再 INSERT v2；两句之间库内暂无 active 行，其间不 parse/advance。正例勿复用负例 session。
5. **provider/model GUC 字面量以现役 `v13/envelope/test_envelope.py` 的 guc() 助手为准**——本报告正文 §2 用 `fake/fake-judge`、I.5 用 `mock/jev-mock`，两套并存，实施时照抄现役测试，勿照抄报告。
6. **（可选 canary，仅 --with-mcp）**：金样加一行幸存非 ASCII（如 `café/a"b\\c`，文件名保持 ASCII 避开 N10 的 decisions CHECK），断言 `content[0].text == json.dumps(expected, ensure_ascii=False)`——锁「斜杠不转义 + 非 ASCII 原样 UTF-8」；**不做**整帧字节比较（整帧键序由 MCP SDK 编码 `CallTool.Result` 决定，非 `JSONEncoder(.sortedKeys)` 段，会脆）。
