# Investigation: repoprompt-ce 功能逐步当作 Swift 工具迁移到 pg-agent 的策略

> 日期：2026-09-27。模式：深调查（只读源码与既有裁决，结论落本文，不改运行时代码）。
> 问题：pg-agent 已经能接受 Swift 语言工具。如何进一步把 repoprompt-ce **逐步**迁进 pg-agent，而不是再移植一台运行时。

## Summary

迁移单位不是 MCP 工具名，也不是 app。单位是：**一个确定性、无会话态的 headless 原语**，包成一次性子进程，走已经落地的行 JSON 口岸，注册为 `kind='tool'` / `handler='worker:…'`，在 `v13_claim` 提交之后、`v13_complete` 开启之前执行。状态、可见性、授权、循环留在 PostgreSQL。

控制面动词已经换体到 stage 17–28，不要用 Swift 再包一层 `agent_run`。进一步迁移的缺口是文件与上下文平面的 worker。模型今天不能经判断面交自由路径；下一刀应是**系统派生的**名字列举（可选加 git tip），不是把 `file_search` / `apply_edits` 原样注册成模型可调用工具。经 Phase 4 两路 Oracle 裁决：环上名字列举被否，**下一正式里程碑是文件平面 R0a**，名字列举只做纯离线探针。见 `## Oracle Synthesis`。Phase 5（同日第三轮，三路 Oracle）补裁模块级 Swift 复用机制与逐模块重建表，见文末 `## Phase 5`。

## Oracle Synthesis（Phase 4 裁决，取代下方草稿的 S1 环提议）

两路 Oracle（grokBuild / grok-4.7-build-fast-xhigh，codex / gpt-5.6-sol）独立收敛到同一条策略。**下文「分期」里把环上 S1（驱动器在 ring 里列目录、把文本放进 `tool/result`）当作下一刀的草稿提议被两路一致否决**；以本节为准。

### 收敛结论

1. **迁移单位是「窄而无状态的物理 execute 单元」，不是 MCP 工具名，也不是 app。** 四条住所：
   - 权威在事件 / 策略行 / 已冻结 artifact → SQL 投影或事件折叠（不碰 Swift）。
   - 字节未冻结、必须碰活的 FS / git / 解析器 → 一次性 `kind='tool'` worker（系统 enqueue，request 携带已授权路径与冻结策略版本，settle 写收据/指针）。
   - 字节已冻结、模型要看 → `kind='sql'` 快路只读已冻结行。
   - 控制动词 / 进程寿命 / grant / journal / link / UI / MCP → 沿用已裁的换体或永不建。
2. **逻辑 effect 名 ≠ 物理 handler 名。** 例如逻辑 effect `corpus_bootstrap` 的物理 handler 可以是 `worker:enumerate_names_swift_v1`；逻辑 effect `file_search`（R1 的 `search_hits` 合同）的物理引擎可以是 `worker:file_search_icu_v1`。这样实现可替换，PG 里的产品语义不动，也化解了 `file_search` 名字碰撞。
3. **下一正式里程碑是 R0a**（文件平面立项），不是环上 S1。顺序锁死为可行性 v2 §8：R0a → R0b → R1a(`names_prior`) → R1b → R1c → R6。
4. **S1 只许做纯离线探针**：不注册 `tools` 行、不调 `v13_claim`/`v13_complete`、不写 events/artifacts、不进模型上下文，只在 fixture 上验证 root 围栏 / symlink / 隐藏文件 / 稳定排序 / 跨语言等价。它是给将来 R1a worker 备实现的 M1 形状，不叫 `get_file_tree`/`full_tree`/`corpus_bootstrap`。
5. **环上 S1 被否决的理由（三条活体机制，不是风格）：**
   - 普通 tool 成功结算会**自动追加 `tool/result`**（`v13/fanout/v13_fanout.sql` 的 `v13_complete`；`v13/seam/v13_seam.sql`）。该事件进本 turn 判断窗，模型下一拍 parse 就看见目录文本。所以「只是放进 effect result、不当身份」并不能阻止它出镜——违反 I-file-3 的路径出境门（秘密路径不得进 tree/快路/manifest）。
   - 缺少 I-file-6 的 `v13_file_vetoes` 单源与 population 分列，无法证明 deselect 不被加回、untracked 不越权、dirty 不混排。
   - read_tools 幸福路径是「若干 tool route + llm + finish」；发现与 llm 同回合违反 I-file-7 冷启动「唯一 effect、无 LLM」。
6. **护栏（唯一一条）：Swift 只交回证据，PostgreSQL 决定这些字节是什么、以及模型能不能看见。** 任何新端口提案必须答出四问，缺一不开工：①谁 enqueue（系统还是模型）；②参数来自闭合 choice 还是 PG 派生；③输出由哪个 PG settle 写成什么 receipt/artifact；④崩溃结算 `failed` 还是 `unknown`。
7. **受保护变异族（`file_actions`/`apply_edits` 的授权+journal 包装）维持永不建**（F20/F28）。物理写盘子集现在不开工；将来只迁移「PG 授权 → claim → Swift 只执行物理写 → PG 按 fence 结算」的后半段，且必须走 `v13_resolve_unknown`。

### 与草稿的分歧登记

| 草稿（本文「分期」节） | 裁决 |
|---|---|
| 下一刀 = S1 环上名字列举 | **被否。** 下一刀 = R0a；S1 降为纯离线探针（`分期` 节的 S1 环部分作废，离线部分保留） |
| 大库（CodeMap/ApplyEdits）以后链 reprompt-ce 库做成 CLI（「落点定义」第 5 条） | **维持为 S4 提议，不是已裁。** R6 的 G-file-secret / G-ctx1-file / G-file-id 绿之后才谈；不给 tree-sitter 在 pg-agent 重写，不加宽 `read_duck` |
| `get_code_structure` 引擎（CodeMapCore vs 加宽 read_duck）| 未裁；R0–R6 不依赖它 |

### 事实修正（Oracle 1 的一处口径错）

Oracle 1 称「控制面动词已换体到 `v13/load.py` 的 `govern`（加载序第 29 项）」。以活体为准：**`v13/load.py` 现为 28 项，末项 `v13/attention/v13_attention.sql`，无 `govern`**（本调查已直接读 `v13/load.py` 与 `v13/` 目录树核对；`v13/` 下不存在 `govern/` 目录）。stage 29 `govern`（`goal/stopped|resumed` 等）只在 `docs/plans/v13-phase-c-governance-projections-plan-2026-09-27.md` 中规划，未进加载序。pair 的 Investigator Findings §3 正确，Oracle 1 该句不采信。

## 落点定义

「当作 Swift 工具」成立，当且仅当下面六条同时成立：

1. 一次调用一个子进程。不长驻，不做 MCP server，不要求 RepoPrompt app 在跑。
2. stdin 一行 JSON，stdout 一行 JSON，换行结尾。退出码只认 `0`（成功）、`3`（工具错误）、其余为协议错误。
3. `tools` 行是 `kind='tool'`，`handler` 是开放处理键（先例 `worker:read_file_swift`）。hub 只按冻结的 `request.handler` 分派。
4. 活的读盘 / git / 写盘不进 `v13_advance` 事务。
5. 小契约在 pg-agent 内重写并锁等价。大库（CodeMap、ApplyEdits）以后可以链 repoprompt-ce 的库做成一次性 CLI，但仍由 hub 按路径 spawn，不 `import` app，不 spawn `repoprompt-mcp`。
6. 缺 `swift` 或约定二进制：打印 `not_run/toolchain_absent`，退出 2。不得伪装通过。

不成立的读法：把 `DirectHeadlessMCPService` 或 `RepoPromptExecutable`（它只是 `RepoPromptApplication.main()`）当成 pg-agent 的工具宿主。read-tools D5 已拒：Swift MCP server、长驻 daemon、`--with-swift` 可选。

## 已有口岸（冻结，不要重开）

`v13/read_tools/` 已证明环能吃 Swift：

| name | handler | 执行 |
|---|---|---|
| `read_file_swift` | `worker:read_file_swift` | `swift read_file_swift.swift` |
| `read_file_py` | `worker:read_file_py` | 进程内 |
| `read_pi` | `worker:read_pi` | `node read_pi.mjs` |
| `read_duck` | `worker:read_duck` | 独立 venv |

目录行只在库 `agent_v13_read_tools` 运行时 INSERT/DELETE。零 SQL 文件、零 `SQL_LOAD_ORDER` 追加。headless `read_file` 是单 root、显式 `root`、纯字符串；不是 app 窗口版（10MB、二进制探测、选区副作用、`offset` 别名）。

判断面墙（read-tools D3，本策略不重开）：`param_spec.options` 必须是闭合对象，判断面发的是 choice。自由 `path` / `query` 进 Noul 要改 schema。环上的 mock 只能选 fixture。`../`、绝对路径、换行类只在直接调口岸时测。

因此「把 MCP 工具原样注册，让模型传任意路径」不是下一步。那条路和已裁判断面冲突。

## 三桶

依据：`MCPDomainToolCatalog` 的工具名；分层路线图 13 补齐 / 29 换体 / 29 永不建；可行性 v2 的七条 I-file；read-tools D1–D10。不重开这些裁决。

### A. 可以变成 worker

确定性、无会话态、IO 在进程里、真相不在进程里。

| RP-CE | 下一形态 | 何时 | 不做 |
|---|---|---|---|
| `read_file` | 已落地 headless 子集 | 已完成 | 不扩成窗口版 |
| 名字列举 / `get_file_tree` 的 names-only | 系统 effect 的 worker。结果是 effect result，不是文件身份 | 下一刀 | 不把 JSON 当成 `workspace_files`；秘密路径的出境门在 PG settle，不在 Swift 进程的「可见选择」 |
| `git` 的 status/diff/log/show/blame | `worker:git_read`，显式 root，不展开 `~` | 名字列举绿之后 | 不搬 `manage_worktree` 的 10 个 op |
| `file_search` | 可行性 v2 的发现 effect。`max_hits≤200`，命中秘密路径只回计数 | R1，不在判断面放开之前当模型工具 | 不是 T0；不是 sql 快路 |
| `worktree_prepare/merge/release` | 目录行已在 `v13/fanout/v13_fanout.sql`（`worker:worktree_*`）。缺的是 worker 实现 | 文件收据立法之后 | 不建第二套 worktree 状态机。list/bind/select/unbind 不进工具环 |
| `get_code_structure` | 链 `RepoPromptCodeMapCore` 的一次性 CLI | R0/R1 绿之后 | 不在 pg-agent 重写 tree-sitter |
| `apply_edits` / `file_actions` | 链 `RepoPromptDomainRuntime` 的变异 worker | 最后。写盘可能已落地 → `unknown`，绝不自动重执行 | 不在 advance 事务里写盘；无 `write_grant` 不开工 |

### B. 语义留在 PG，Swift 不拥有这份状态

| RP-CE | 已有或已裁落点 | 禁止 |
|---|---|---|
| `manage_selection` | 事件折叠 + `v13_file_vetoes`（I-file-6） | Swift 进程内 selection |
| `prompt` | 策略行 / artifact | app prompt store |
| `workspace_context` | R6：收集平面先于接线存在，渲染只读已冻结 hash | 用 Swift 现扫仓库来「拼上下文」 |
| `manage_workspaces` / `bind_context` | R0 的 `workspaces` + `sessions.ws_id`。动态三表后置（可行性 v2 §6） | 搬 RP-CE workspace manager |
| `context_builder` | 就是 parse + file effect + recall 这条循环 | Swift 里再套一个发现 agent |
| `oracle_*` | `kind='llm'` effect | Swift oracle client |
| `ask_user` | human `v13_complete` | 新交互表 |
| `agent_run` / `agent_manage` / `agent_session_link` | start/steer/cancel/respond 已换体。stage 23–25 是授权、观察、交接 | `v13_agent_run`、link 表、墓碑删除 |
| `history` | 读 events。交接只存 hash（F29） | XML transcript、frontier 表 |

### C. 永不迁

App UI、窗口、标签、Sparkle、音频、MCP transport、交互式 command runner。进程生命周期（F5/F16/F24–F26）、墓碑删除（F19）、grant 经纪人（F20/F21）、oversight link（F30）。LoopX 文件六层与相位机。长驻 daemon。把 `decisions.epoch` 当成 run generation。

`SQL_LOAD_ORDER` 现已收到 `attention`（stage 28）。控制面补齐的主体在库里。stage 29（`goal/stopped|resumed` 等）未进加载序，那是控制面尾项，不是 Swift 工具线。两条线不要并进同一次提交。

## 分期

依赖序不可跳。一刀一个里程碑。离线契约绿了才进环。进环仍不改 `v13/**/*.sql`，直到单独立项打开 R0。

### S0 · 口岸纪律

已落地。新工具复用，不重写协议：一帧、退出码、`protocol_error`、单 root、显式 `root`、NUL 与逃逸 = `path_outside_workspace`、IO 出事务、缺工具链退出 2。

读失败 `complete failed`，不 `unknown`。写盘才可能 `unknown`。本地读要么读到了要么没读到。

### S1 · 系统派生的名字列举

下一刀。不改判断面，不加表，不让模型选路径。

- 离线：Swift 与 Python 在同一 fixture 上列出相对路径，排序稳定，单 root 围栏与 `read_file` 相同。
- 环：驱动器（不是模型）在 claim 之后调用 worker，`complete succeeded` 把文本放进 effect result。
- 红线：结果不是文件身份，不 UPSERT 指针，不翻 `bootstrap_done`，不建 LLM effect。秘密路径出现在**模型可见**投影里即红；S1 可以先不建投影，那就断言「没有任何 file 可见面读这个 result」。
- 可选同刀或下一刀：`git_tip` 只返回 `git_head` 字符串。同样不写 `workspace_git_tips`（那张表属于 R0）。

这一刀证明口岸能承载发现，不证明文件平面已立法。

### S2 · 只读 git worker

op 闭集 `status|diff|log|show|blame`。显式 root。不展开 `~`。判断面仍不收自由 revspec；环上只跑闭合 fixture。自由 rev 只在直接调口岸时测。

### S3 · 文件平面立法（可行性 v2，不要改范围）

这才是「进体系」。顺序已写在可行性 v2 §8，此处不重开：

1. R0a：`workspaces`、收据、指针、tips、veto、七不变量。零 FS。
2. R0b：`v13_visible_tools` 单源。
3. R1a：`corpus_bootstrap(mode=names_prior)` + 白皮书。worker 换掉 FakeFs。冷启动 waiting，同时 LLM effect = 0。
4. R1b：`file_search` + `file_register`。search 与 register 同 turn 即红。hits>32 分 turn。
5. R6：manifest 只读已冻结 hash。exact replay 不发 FS effect。

Swift 在这里只替换 worker。身份仍是 `(ws_id, canonical_path, content_hash)`。stat 不是身份。

### S4 · 重库 CLI

放行：S3 的 G-file-secret、G-ctx1-file、G-file-id 已绿。

在 repoprompt-ce 增加**新的**一次性可执行目标，链接 `RepoPromptCodeMapCore`，然后才是 `RepoPromptDomainRuntime`。协议仍是一行 JSON。hub 用绝对路径 spawn。二进制缺失 → 退出 2。归属写进 `THIRD_PARTY_NOTICES.md`。

`apply_edits` / `file_actions` 额外门：`write_grant` 已立法；部分写入后崩溃走 `v13_resolve_unknown`，绝不自动重执行；settle 写收据。无这些门，编辑工具会绕过注册门，不开工。

### S5 · worktree worker

填已有的 `worker:worktree_prepare|merge|release`。latch 与 `worktree/released` 仍由 PG 写。不移植 `manage_worktree` 的 list/bind/select/unbind/continue/abort 词表。

## 调用形状（避免走错）

今天模型选工具 = 判断面 choice + 闭合 options。文件平面的正路不是放宽这个面，而是：

```text
SQL 从已冻结收据 / search_hits / 白皮书派生 paths[]（≤32）
→ enqueue effect，request 里带着已授权路径与冻结策略版本
→ claim 提交
→ worker 只执行这份 request
→ complete
→ fenced settle 写收据与指针
→ 模型经 recall / render 看见 artifact，不看见 live FS
```

预演路（S1/S2）用闭合 fixture，证明 worker 等价。正路（S3）路径由 SQL 派生。两条不要合成一个里程碑，也不要在 S1 改 `v13_needed_judgments`。

## 红线（撞上即停）

1. 不建 `v13_agent_run`，不建第二推进函数。
2. 不 spawn `repoprompt-mcp`，不长驻 Swift 进程。
3. 外部 IO 不进事务。SQL 不杀进程。
4. stage 1–20 文件字节冻结。新 SQL 只在 R0 立项后追加 `SQL_LOAD_ORDER`。
5. 零新表是默认。文件平面两张收据表是可行性 v2 D1 已裁的例外，不是本策略新开的。未开 R0 之前不准偷建。
6. 读失败不进 unknown 墙。写失败才可能 unknown。
7. 一刀一提交。按路径 `git add`。禁止 `git add -A`。禁止 force-push。
8. 动态 workspace 三表维持后置。放行条件仍是可行性 v2 §6，一条不减。

## Root Cause

问题不是「pg-agent 还不会跑 Swift」。口岸已经能跑。卡住进一步迁移的是单位选错：若按 MCP 工具名逐个注册，会把 app 的会话态、判断面闭集、以及「读盘不是 sql 快路」三件事同时撞破。正确单位是无状态 worker；身份与出境在 PG。

## Recommendations

_（已按 Oracle Synthesis 修订；草稿原「下一刀 = 环上 S1」被两路 Oracle 否决。）_

1. **下一正式里程碑 = R0a**，范围抄 `docs/analysis/repoprompt-native-on-v13-feasibility-v2-2026-09-21.md` §2.1/§8.1（`workspaces` + `sessions.ws_id`/`files_cutoff` + append-only `file_receipts` + `workspace_files` 指针 + `workspace_git_tips` + `file_vetoes` 折叠 + I-file-1..7 立法与 gate）。零 FS。R0 是**唯一**打开「新增收据表/列」的立项入口；未拍板前不准建表、不准加列。
2. 名字列举**只做纯离线探针**（无 `tools` 行、无环、无 events/artifacts、不进上下文），证明 root 围栏 / symlink / 稳定排序 / Swift↔Python 等价，并给 R1a 的 worker 备实现。**不做环上 S1。**
3. R0b（`v13_visible_tools` / `v13_visible_files` 单源）紧随 R0a；R1a `corpus_bootstrap(mode='names_prior')` 用真 worker 替换 FakeFs 且冷启动 LLM effect=0；`full_tree` 独立提交、默认关。
4. `file_search`、`get_code_structure`、`apply_edits` / `file_actions` 都不进 R0–R1。`file_search` 公共逻辑名留给 R1 的 `search_hits` 账本；RP-CE 的 ICU `searchFiles` 只作 versioned 物理 handler（`worker:file_search_icu_v1`），不注册第二个模型可见的 `file_search`。
5. 控制面（含未落地的 stage 29 `govern`）与 Swift 工具线分开提交，不互相夹带。
6. 重库 CLI（CodeMap / ApplyEdits）放到 R6 的 G-file-secret / G-ctx1-file / G-file-id 全绿之后；在那之前不在 pg-agent 复制 `RepoPromptCodeMapCore`，也不加宽 `read_duck` 冒充跨文件 CodeMap。

## Preventive Measures

- 新工具计划必须写明：谁 enqueue（系统还是模型）、params 是否闭合、结果算不算身份、崩溃进 failed 还是 unknown。四项缺一项不开工。
- 禁止把 `RepoPromptExecutable` 或 headless MCP service 写进 hub 的 argv。
- 模型可见面若直接读 worker stdout 而不是收据投影，gate 即红。
- 缺工具链退出 2 的先例保持：先跑绿再退出 2 不算通过。

## Investigator Findings

上文「落点定义 / 三桶 / 分期」是草稿提议。本节只记活体与已裁平面能支撑的结论。草稿把未建表写成已有落点、或把未裁顺序写成下一刀的地方，下面点名，不代裁。

**能支撑的策略句：** 迁移单位不是 28 个 MCP 名，也不是 app。已落地的 Swift 工具是一条窄合同（§1）。28 个里只有 `read_file` 按该合同落地，行名是 `read_file_swift`。控制动词已有换体的不重迁。app / oracle / link 不建 Swift 行。文件收集平面的规定形态是可行性 v2 的 R0/R1/R6，v13 里还没建。排名上的下一格 `get_file_tree` 没有开工许可。

不准改写的两套平面：`docs/analysis/repoprompt-native-on-v13-feasibility-v2-2026-09-21.md` 的 I-file-1…7 与 R0/R1/R6；`docs/plans/v13-layered-control-roadmap-2026-09-26.md:17-23` 的 13 补齐 / 29 换体 / 29 永不建（裁决在 `docs/reviews/v13-control-plane-parity-rpce-loopx-2026-09-26.md`）。

### 1. 「当作 Swift 工具」产出什么、不产出什么

先例是 `v13/read_tools/`，不是把 `MCPDomainCanonicalWorkspaceService.readFile` 原文搬进来。`read_file_swift.swift:1-5` 写明来源是 `:171-193` 与 `DirectHeadlessDomainContext.swift:302-333` 的单 root 子集，并写明 “Not the app-window read_file”。

产出：

- pg-agent 内的自有 CLI。不 spawn `repoprompt-mcp`，不 spawn `pi`，不做 MCP server（`docs/plans/v13-native-read-tools-2026-09-27.md` D1/D5）。
- 一行一帧 JSON。成功 `{"ok":true,"result":"<string>"}` 退出码 0；工具错误 `{"ok":false,"error","message"}` 退出码 3；其余退出码 1。Swift 用 `FileHandle` 加单个 `0x0A`，不用 `print`（`v13/read_tools/README.md:22-32`，`read_file_swift.swift:13-20`）。`bridge.py:40-79` 把退出码不在 `{0,3}`、EOF、旗标不一致收成 `ProtocolError`。
- `tools` 一行：`kind='tool'`，`handler='worker:<name>'`。列只有 `name, description, kind, handler, param_spec, enabled`（`v13/schema/v13_core.sql:581-590`）。`description` 必须 ASCII。名字与 param 键不得含 `::`。
- 行只在隔离库 `agent_v13_read_tools` 运行时 INSERT/DELETE。不改 `v13/**/*.sql`，不追加 `SQL_LOAD_ORDER`（`README.md:107-116`，`test_read_tools.py:541-544`）。
- IO 在 `v13_claim` 已提交、`v13_complete` 未开启之间。hub 只按冻结的 `request.handler` 分派（`test_read_tools.py:596-612`）。读失败是 `complete failed`，不是 `unknown`。
- `param_spec.options` 闭合。环上的 mock 只选广告过的选项（计划 D3）。

不产出：

- 不是目录名 `read_file` 的行，不是 `ReadFileReply`、10MB 帽、二进制探测、选区副作用、`offset` 别名（`README.md:34-36`）。headless 原文用 `components(separatedBy: .newlines)` 并走多 root adapter（`MCPDomainCanonicalWorkspaceService.swift:171-193`）；落地合同是显式换行类加单个 `root`（`README.md:38-42`）。
- 不是 core 种子，不是新 stage。活体 `SQL_LOAD_ORDER` 28 项，末项 `v13/attention/v13_attention.sql`（`v13/load.py:18-47`），没有 `read_tools`。
- 不是 app 窗口。`MCPDomainCanonicalWorkspaceService` 只拥有 workspace 族（selection / tree / read / search / context / prompt，`:89-376`），不是 28 工具全集。
- `12806c4` / `019ddc5` / `2dbc2ca` 都没改 `docs/reviews/` 的 conformance matrix 或 deviation ledger。偏差在 stage README。

上文「落点定义」第 5 条（大库以后链 repoprompt-ce 做成 CLI）不是这三次提交建立的事实，是草稿。read_tools 的事实是代码住在 pg-agent（D1）。

### 2. 28 工具落点

目录是 `MCPDomainToolCatalog.entries`（`MCPDomainToolCatalog.swift:220-323`），28 名。排名取 `docs/investigations/v13-multilang-tool-call-test-2026-09-23.md:40-46`。该文对 `read_file` / `get_file_tree` 的行号仍与活体一致。`file_search` 的 `:325-334,556-577` 已漂移；活体 `NSRegularExpression` 在 `MCPDomainCanonicalWorkspaceService.swift:205` 与 `:559-570`。

`CHANGE-FORM` 只用于 v13 已有等价物。规定了但没建的，不叫换体。

| 工具 | 落点 | 锚 | 排名 |
|---|---|---|---|
| `read_file` | PORT-AS-TOOL（已落地，窄合同） | 行名 `read_file_swift`，`test_read_tools.py:542`；`read_file_swift.swift:1-5` | ≈99%，`:171-193` |
| `get_file_tree` | NEEDS-DECISION | `renderFileTree` `:155-169`；`treeLines` `:511-534` 不排序。v13 零 `get_file_tree` / `full_tree` / `corpus_bootstrap`。R1 的 `full_tree` 是 `corpus_bootstrap` 的默认关模式（可行性 v2 `:98-102,:218`） | ≈90%，序未定义 |
| `file_search` | NEEDS-DECISION | `searchFiles` `:195`，ICU `:205`。v13 零此名。R1 已占用这个名字，产出是 `search_hits` 账本，不是扫盘（可行性 v2 `:98`） | ≈55% |
| `get_code_structure` | NEEDS-DECISION | `inspectCodeStructure` `:124`，`import RepoPromptCodeMapCore`，`CodeMapSyntaxEngine`。`read_duck` 只渲染单文件 outline（`read_duck_port.py:152-171`），不是跨文件签名 | 不推荐 |
| `file_actions` | NEEDS-DECISION | 受保护且 durable（`MCPDomainProtectedMutationToolProvider.swift:116-120,:320-322`）。v13 无此名。F20/F28 否掉授权包装；物理子集未裁 | ≈85%，Trash+授权 |
| `apply_edits` | NEEDS-DECISION | 同上，durable。引擎在 `ApplyEditsEngine.swift`。F28 不建 journal（parity 表 F28；迁移 §4） | ≈45% |
| `manage_selection` | NEEDS-DECISION | 受保护，非 durable（`:129-133`）。headless `mutateSelection` `:89`。I-file-6 的 `v13_file_vetoes` 只出现在可行性 v2 `:47,:76`，v13 SQL 零命中。上文 B 桶把它写成已有落点，不成立 | 不在五名内 |
| `prompt` | NEEDS-DECISION | durable。`accessPrompt` `:376` 读写 adapter 快照，不是文件。v13 零此名 | 不在排名 |
| `workspace_context` | NEEDS-DECISION | durable（export/select_preset）。`renderWorkspaceContext` `:336`。R6 规定 manifest 渲染，v13 零 `bootstrap_done`。R6 不是本工具的决议 | 不在排名 |
| `bind_context` | NEEDS-DECISION | 仅 `op=bind` 受保护（`:148`）。application scope（catalog `:221-224`）。CanonicalWorkspaceService 无此函数 | 不在排名 |
| `manage_workspaces` | NEEDS-DECISION | 受保护的是 switch/create/hide/…（`:150-154`）。无 headless FS 函数。不是 R0a 的 workspaces 列 | 不在排名 |
| `manage_worktree` | CHANGE-FORM | 三行 `worktree_prepare/merge/release`，`kind='tool'`，`worker:worktree_*`（`v13/fanout/v13_fanout.sql:1062-1068`）。`v13_record_worktree_released` 由 acl 的 `v13_complete` 调用（`v13/acl/v13_acl.sql:454`）。检索无 worker 实现，只有目录行与测试里的 handler 字符串。F22 改变、F23 的 `worktree/released` 已写。git add/remove 余项见 §6 | 不推荐（git CLI） |
| `git` | NEEDS-DECISION | catalog `:278-281`，op=status/diff/log/show/blame。v13 无 git status/diff 工具。与 latch 不是同一合同。上文 S2 把它排成第二刀，证据未闭合 | 不推荐 |
| `app_settings` | NEVER-BUILD | application 偏好（catalog `:220`）。无 headless FS 体。不在 13 条补齐里 | 不在排名 |
| `oracle_utils` | NEVER-BUILD | D1 禁止 spawn app/MCP。v13 无 oracle 会话 | 不推荐 |
| `ask_oracle` | NEVER-BUILD | 同上 | 不推荐 |
| `oracle_send` | NEVER-BUILD | 同上 | 不推荐 |
| `oracle_chat_log` | NEVER-BUILD | 同上。不是 `events` | 不推荐 |
| `context_builder` | NEVER-BUILD | 发现 agent（catalog `:286`）。收集效果的规定形态是 R0/R1/R6，不是这个 agent | 不推荐 |
| `ask_user` | CHANGE-FORM | v13 零 `ask_user`。human 通道：`v13_pending_human(uuid)` 被 observe 前置当已有函数引用（`v13/observe/v13_observe.sql:17`）；结算是 `v13_complete`。F11/F27 已裁换体。迁移 §2.2 respond：不建新表 | 不在排名 |
| `agent_explore` | NEEDS-DECISION | op=start/poll/wait/cancel（catalog `:287-290`）。`spawn_subsession` 是 `kind='sql'` 的子会话批量出生（`v13/spawn/v13_spawn.sql:318,:1757-1760`），不是只读 explore child。迁移 §2.2 禁止 `v13_agent_run(op)`；v13 零 `v13_agent_run` | 不推荐 |
| `agent_run` | CHANGE-FORM | 不建 `v13_agent_run`（迁移 `:84,:304`）。活体 `v13_open_session` `v13/spawn/v13_spawn.sql:285`，`v13_cancel` `v13/fanout/v13_fanout.sql:153` 与 `v13/acl/v13_acl.sql:121`。poll/wait 不建 waiter（F7 改变；F8 落成 `v13_observe`） | 不推荐 |
| `agent_manage` | CHANGE-FORM | `v13_control_authorized` `v13/acl/v13_acl.sql:90`，`v13_observe` `v13/observe/v13_observe.sql:43`，`v13_session_log` `:130`，`v13_extract_handoff` `v13/handoff/v13_handoff.sql:280`。`cleanup_sessions` 永不建（F19，路线图 `:88`） | 不推荐 |
| `agent_session_link` | NEVER-BUILD | F30。v13 零此名。迁移 §2.2：不建 send 账本 | 不在排名 |
| `history` | NEEDS-DECISION | 只读、不设门（多语言调查 `:38`）。近邻是单会话 `v13_session_log`，以及 chunks 上的 `v13_recall`（`v13/recall/v13_recall.sql:121`）。都不是跨 workspace history。上文 B 桶写成「读 events」过宽 | 不在五名内 |
| `share_thoughts` | NEVER-BUILD | catalog `:312`。v13 零此名。不在 13 条补齐。不是 FS 原语 | 不在排名 |
| `set_status` | NEVER-BUILD | catalog `:313`。v13 零此名 | 不在排名 |
| `wait_for_next_user_instruction` | CHANGE-FORM | 回合边界是 advance 的 finish 加 human wait（`v13_pending_human` 见上；迁移 §2.1）。v13 零此工具名 | 不在排名 |

受保护族闭集就是 8 个：`manage_selection`, `prompt`, `workspace_context`, `bind_context`, `manage_workspaces`, `file_actions`, `apply_edits`, `manage_worktree`（`:116-120`）。durable 五名：`file_actions`, `apply_edits`, `manage_worktree`, `prompt`, `workspace_context`（`:320-322`）。F20 不建 grant，F28 不建 journal：包装层是 NEVER-BUILD。包装下的物理操作，除 worktree 三动词已换体外，未裁。

### 3. v13 没有 tree / file_search / code-structure

在 `v13/` 检索 `get_file_tree`、`file_search`、`get_code_structure`、`file_register`、`search_hits`、`full_tree`、`codemap`、`v13_visible_files`、`v13_visible_tools`、`bootstrap_done`、`corpus_bootstrap`、`v13_file_vetoes`：零命中。`os.walk` / `scandir` / `listdir` 亦零命中。唯一的 `FileManager` 是 `read_file_swift.swift:62` 的 `fileExists`，不是列目录。

近邻不是等价物：

- `v13/mgraph/v13_mgraph.sql:4-5` 是 `memory_nodes` / `memory_links`。
- `v13_recall`（`v13/recall/v13_recall.sql:121`）搜已摄入 chunks，不是工作区文件。
- `v13/catalog/` 编目 SQL 函数。
- `read_duck` 是单文件 `parse_ast` → `ast_to_blocks_from` → `duck_blocks_validate` → `duck_blocks_to_text`（`read_duck_port.py:152-171`）。options 闭合为 `fib.py`（`test_read_tools.py:533-539`）。

`SQL_LOAD_ORDER` 28 项，末项 attention（`v13/load.py:18-47`）。`v13/read_tools/README.md` P2 的「24 项、末项 observe」已过期。stage 29 `govern`（`goal/stopped|resumed`）在 `docs/plans/v13-phase-c-governance-projections-plan-2026-09-27.md` 里，不在 `load.py`。上文说它未进加载序，与 `load.py` 一致。

### 4. read_file 之后的顺序

没有下一项已经具备开工条件。要同时满足：符合 §1、不改写 R0/R1/R6、不改写控制面裁决、不把未裁问题当成已裁。过完这四条，剩余 27 个都停着。

依赖序（条件，不是决议）：

1. 已完成：围栏 + 行 JSON 桥 + 闭合选项 + 隔离库零 SQL。`read_duck` 说明下一格的形状是另一个合同的兄弟行，不是把 `read_file` 加宽。证据：`019ddc5` 然后 `2dbc2ca`，与 `fb24ea5` → `12806c4` 同构。
2. 排名下一格是 `get_file_tree`（≈90%，无 regex、无 tree-sitter，可复用围栏和桥）。它不依赖 search 或 codemap。它依赖未裁的角色划分：渲染字符串 ≠ R1 `full_tree`，也 ≠ 模型可见的发现工具。`treeLines` 不排序。I-file-1/3/5 禁止把未注册、无 hash、无 secret 门的目录列表当成模型可见语料。D3 禁止判断面收自由 path。上文 S1（系统派生的名字列举、结果不当文件身份、不翻 `bootstrap_done`）与这些红线兼容，但它把「R1a 之前做一口预演」写成了下一刀。可行性 v2 `:208-216` 把 `names_prior` 放在 R0 之后。这两套顺序都还开着。本节不选。
3. `file_search` 不得接着自动开工。名字已被 R1 占用，引擎是 ICU（`:205`），排名 ≈55%。即便要内容搜索原语，也不能注册成 `file_search`，也不能产出 `search_hits`（可行性 v2 `:93-98`，handler 规定为 `fs`）。
4. `get_code_structure` 依赖走查加解析器。`CodeMapSyntaxEngine` 与加宽 `read_duck` 未选。上文 S4「链 CodeMapCore、不在 pg-agent 重写 tree-sitter」是提议，不是活体结论。排名原文写 tree-sitter；活体 import 的是 `RepoPromptCodeMapCore`。语言个数本次未重数。
5. `file_actions` / `apply_edits` 依赖一套 v13 明确不建的授权（F20、F28）。`write_grant` 在可行性 v2 是 R0 留列，v13 未建。上文把它排到最后，与「现在不开工」兼容，但不关闭「要不要建」。
6. `git` 不因排名进入 Swift 序列（不推荐）。上文 S2 未被证据闭合。`manage_worktree` 的三动词已换体；缺 worker 实现是事实（只有 `v13_fanout.sql:1062-1068` 的目录行），填 worker 与移植 MCP 词表不是同一件事。
7. oracle / agent 不进入这条序列。`agent_run` 六 op 的顺序是路线图。控制面补齐已加载到 attention（`load.py` 末项）。

本轨道不准替代的产品序仍是 R0 → R1a → R1b → R6。`full_tree` 独立提交、默认关（可行性 v2 `:218`）。这些在 v13 都还没建（§3）。

### 5. 每个端口要遵守的清单

从 `v13/read_tools/README.md`、`test_read_tools.py`、`12806c4` / `019ddc5` / `2dbc2ca` 抽出。三笔都没碰 `docs/reviews/` 的矩阵或台账：`12806c4` 只改 README / `setup_db.py` / `test_read_tools.py`；`019ddc5` 加口岸、fixture、`duck_bringup.py`、`THIRD_PARTY_NOTICES.md`、`.gitignore`；`2dbc2ca` 只改 README 与测试。零 SQL 端口不走 AGENTS.md 的「追加 `SQL_LOAD_ORDER` + 更新矩阵」。那套只在真正新增 SQL stage 时生效。

1. 一里程碑一提交。契约绿了再进环（`fb24ea5` 与 `12806c4`；`019ddc5` 与 `2dbc2ca`）。
2. Gate：`uv run python v13/read_tools/test_read_tools.py --contract` 与无旗标。退出码 0 才是通过。工具链缺失在 `setup_db` 之前打印 `[SKIP] not_run/toolchain_absent` 并退出 2。退出 2 不是通过。断言失败退出 1（`README.md:7-16`）。
3. 帧与退出码按 §1。桥不读第二帧（`bridge.py:40-79`）。
4. 行只在会被 DROP 的隔离库里 INSERT/DELETE。零 `v13/**/*.sql`，零 `SQL_LOAD_ORDER`，零 core 种子（`README.md:107-116`）。加一种 handler 的答案是零 SQL 文件（`:128`）。
5. `description` ASCII；name / param 键无 `::`。不加 `input_schema` / `mutating` / `timeout_ms`。
6. options 闭合。自由 path 是判断面变更，read 计划明确不做（D3）。
7. IO 在 claim 之后、complete 之前。读失败 `complete failed`，绝不 `unknown`（D7）。写盘才可能 `unknown`；那不是 read 合同。
8. 单 root，realpath 前缀，不展开 `~`。NUL / `../` / 根外绝对路径是 `path_outside_workspace`（D4/D9/D10）。
9. 复制 v1 带，再追加每个新参数的 `param::` 与 `stated::`，`band_no=1, lo=0.60, hi=Infinity, action=pass`。预算只在该库翻（`README.md:120-124`；`test_read_tools.py:546-555`）。INSERT 前后自测 needed，不写死种子个数，且不超过 `batch_questions`（种子 32）。
10. hub 按冻结 `request.handler` 分派，不查活 `tools` 表。
11. `load_stage(..., 'seam')` 是 read_tools 的选择。seam 仍是第 21 项；acl 会再替换 `v13_complete`（`v13/acl/v13_acl.sql:454` 调用 `v13_record_worktree_released`）。新端口若需要活体 complete，不得盲抄停在 seam。不要抄 README P2 的加载计数。
12. 偏差写进该 stage README。不改 SQL 去修 triage 多发的 `triage` choice；环上用 `v13_submit_override`（`README.md:136-140`）。
13. 兄弟回归按当时的 `SQL_LOAD_ORDER` 重测。README 的 23 路径表不含后来的 acl/observe/handoff/should_run/quota_window/attention，不要复制。
14. 搬运上游正文则改根 `THIRD_PARTY_NOTICES.md`（`019ddc5` 改过；`read_file_swift.swift:1-5` 有头注）。
15. 字节敏感 fixture 用 `.gitattributes` 的 `-text`（`README.md:206` 起）。
16. 不得夹带 F20 grant、F28 journal、F30 link 表、或 `v13_agent_run`。

### 6. 未裁（本节不决议）

1. **`file_search` 名字碰撞。** R1 effect（可行性 v2 `:93-98`）与 RP-CE `searchFiles`（`:195-207`）同名不同合同。两边都还没在 v13 落地。
2. **`get_file_tree` 的角色，以及要不要在 R0 之前做一口名字列举。** 上文 S1 选了「系统派生、不当身份」的预演。可行性 v2 把 `names_prior` 放在 R0 之后。证据只排除「模型可调用的开放目录工具」。不排除、也不强制 S1。
3. **`get_code_structure` 的引擎。** `CodeMapSyntaxEngine` 对加宽 `read_duck`。上文 S4 的「链库」不是决议。
4. **8 个受保护工具里，包装以下的物理子集。** journal 与 grant 已经 NEVER-BUILD（F20、F28），这不是新裁决。未裁的是：没有这层包装时，`file_actions` / `apply_edits` 要不要成为 `kind='tool'`；`manage_selection` 对未建的 I-file-6 veto 函数；`prompt` / `workspace_context` 的 adapter 状态对未建的 R6；`bind_context` / `manage_workspaces` 没有 CanonicalWorkspaceService 函数可包。`manage_worktree` 三动词不在此项里重开。填 `worker:worktree_*` 的实现与移植 list/bind/select 词表，仍是两件事。
5. **`git`。** status/diff/log/show/blame，以及 git worktree add/remove，都不是已有的三行 latch。排名不推荐用 Swift 再包一层 git。要不要 worker，未裁。
6. **`history`。** `v13_session_log` 与 `v13_recall` 都不是它。要不要跨会话检索未裁。形状不该是 Swift FS 工具。
7. **`agent_explore`。** `spawn_subsession` 不是只读子 agent。禁止 `v13_agent_run(op)` 没有决定「永远不要 explore child」。
8. **新端口的 `load_stage` 截止点。** read_tools 停在 seam 不是 28 stage 的通用规则。本节不规定全局截止点。

---

## Phase 5 · 模块级原生重建与 Swift 复用裁决（2026-09-27 第三轮）

> 问题：repoprompt-ce 各工具模块如何在 pg-agent 体系中原生重建（多语言 worker、非 MCP、Swift 直接复用）。三路 Oracle 独立收敛（grok-4.7-build-fast-xhigh plan；gpt-5.6-sol xhigh；群组第三路，聚合时标签丢失、内容完整）。本节不重开 Phase 4 已裁；冲突处按下方 Supersede 登记执行。

### 命题检验：「Swift 直接利用本来就不难」

**不成立（对 repoprompt-ce 整体）。** 已落地口岸证明的是短合同可以解释模式重写锁等价，没证明可以 `import` ce 的 target。命题只对两个子集成立：

1. Foundation 单文件、解释模式、golden 在 pg-agent（`read_file_swift` 已证，也是短合同上限）。
2. 纯算法 target 的窄链接：`RepoPromptWorkspaceCore`（路径策略）、`RepoPromptCodeMapCore`（跨文件签名——重写 13 个 tree-sitter 语法不可接受，这是唯一明确值得承担依赖重量的复用点）。

阻碍排序（严重度降序）：

1. **DomainRuntime 与 MCP-sdk + 治理代码同 target**（阻断 edit 族；ApplyEdits/Diffing 必须先拆 EditCore 且链接闭包不含 MCP 才有 executable 资格）。
2. **解释→编译模式 = 运营合同变化**（gate 禁 `swift build`、fresh clone 不读 ce 树、二进制定位）——阻断一切链 core 的工具，直到 S4 开门。
3. **library product 未导出**（只阻断 (b)，不阻断 (a)：同包 executable 用 `package` 可见性即可）。
4. **macOS 14 平台锁**（文件平面默认门必须在无该二进制时全绿）。
5. **tree-sitter 定制 fork + 13 语法包**（仅 CodeMap；重量可接受但时点后置）。
6. **跨仓等价**（handler 版本名锁不住渲染字节：两个二进制都自称 v1 输出可不同 → golden 必须进 pg-agent，对活二进制对照只 opt-in）。
7. **Swift 6 语言模式分 target 配置**（主要打在 (b) 与 EditCore 拆分上）。

### 复用机制（三选一裁决，组合非折中）

| 选项 | 裁决 | 边界 |
|---|---|---|
| (c) pg-agent 内单文件重写锁等价 | **默认，现在就适用** | 合同短、Foundation 写得完、literal golden 锁得住 |
| (a) repoprompt-ce 内新增一次性 executable product | **重库唯一合法编译模式，S4 开门后** | 同包 `package` 可见性足够，不导出 library；依赖闭包禁 MCP-sdk/DomainRuntime/App；禁做成 `repoprompt-mcp` 子命令或 `--backend` |
| (b) 导出 library product 供 pg-agent 侧 Swift 包依赖 | **拒绝** | 库 API 是编译期缝；worker 的版本缝必须是 stdin/stdout 合同。main 放 pg-agent、算法留 ce 仍属 (b) |

离开 (c) 须四条同时为真：单文件写不下（须复制 ce 多模块算法）；语义权威是 ce 自己的测试套件而非几十行源码；S4 时点门已开；目标 target 闭包无 MCP/App/治理。

### 运营契约与版本锁

三种调用形：

| 模式 | 适用 | 调用 | 缺件时 |
|---|---|---|---|
| interpret | Class I 口岸里程碑；Class F 的 opt-in 对照 | `swift <pg-agent 内单文件绝对路径>` | Class I：整门退出 2 `not_run/toolchain_absent`。Class F：默认命令必须退出 0 |
| compiled-pinned | S4 开门后的 (a) | 环境变量给绝对路径（如 `REPOPROMPT_CE_BIN_CODEMAP`）；先跑 `[bin,"--version"]` 校验恰好一行 `repoprompt-<tool> <contract-major> <40 位 git 修订>` 再发无旗标 argv+一行 JSON stdin；gate 内禁 `swift build`、禁搜 PATH | 二进制缺失退出 2 `not_run/binary_absent`；`--version` 不符退出 1 |
| forbidden | 其余一切 | library import、gate 内 build、长驻 daemon、MCP | 不实现 |

**Class F**（文件平面，R1a 起）：命题是收据/冷启动/秘密门，默认命令在无 `swift`、无 ce checkout 时必须退出 0；Swift 或 ce 二进制只出现在单独 opt-in 命令上。不把 read_tools 的 D5 抄进 Class F。

版本锁四件套（缺一不得把 opt-in 标绿）：① handler 名含合同代（`worker:codemap_swift_v1`；破坏性变更=新名字，旧的停用不静默替换）；② `--version` 的 git 修订与该次 pg-agent 提交里写下的修订一致；③ golden 期望字节以 literal 提交在 pg-agent，不向 ce 树现算；④ `THIRD_PARTY_NOTICES.md` + stage README 记 product/合同代/ce 修订/golden 标签。同义变体（择一或并用，锁强度等价）：`v13/native_workers/manifest.json` 部署清单（handler/protocol_version/artifact_sha256/ce_commit/resolved_digest/toolchain/min_macos/binary_path；二进制替换但 manifest 不变 = fail-closed）。ce 的 main 前进不得自动改变 pg-agent 默认门；更新 golden 是一次显式 pg-agent 提交。

禁双实现同 `enabled`：`enumerate_names_py` / `enumerate_names_swift` 不得同时 `enabled=true`（否则 needed 把两引擎放进 choice）。

### 逐模块重建裁决表

| 模块 | 原生形态 | Swift 复用 | 时点 | 四问要点 |
|---|---|---|---|---|
| 系统派生名字列举 | worker 引擎（非模型工具） | **重写锁等价**（解释模式单文件；默认物理引擎 Python `worker:enumerate_names_py_v1`，Swift 只离线对照，不占目录行） | 探针 ∥ R0a；接线 R1a | 系统 enqueue；PG 派生 root+冻结策略版本；settle 写 `file_receipts` 名字收据（可无 content_hash），`p_result` 只有 `schema_version`/`batch_id`/`listed`/`omitted_escape` 计数摘要、零路径零文件名；读失败=failed 非 unknown |
| tree 渲染 | SQL 投影（读已冻结指针） | 不移植 `renderFileTree`/`treeLines`（不排序、含目录、深度裁剪，与名字收据非同一合同） | R6；`full_tree` 独立提交默认关 | 不开端口；树文本进 `tool/result` 即环上 S1，拒绝 |
| 搜索引擎 | R1b `search_hits` 的物理 handler（版本化名） | 按 R1 合同重写；不链 RegexCore（PCRE2≠headless ICU）、不链 DomainRuntime；将来若接受 PCRE2 语义须另编号，不得冒充 RP-CE parity | R1b；对齐 R1 合同的 Python 探针可提前 | 判断面自由字符串另裁前**只许系统 enqueue**；query 来自已落库值或探针 literal；settle 写不可变 `search_hits`（去重、稳定排序、hit_ordinal）；秘密路径只回计数；failed |
| codemap 跨文件签名 | worker 引擎 | **(a) 链 CodeMapCore 的 ce 内 executable**；禁在 pg-agent 重写 tree-sitter、禁复制 target、禁加宽 read_duck 冒充 | S4 门（R6 G-file-secret/G-ctx1-file/G-file-id 全绿）后；本轮不选引擎 | 系统 enqueue；路径来自已注册且 content_hash 非空指针（≤32 批次精神，不搬 MCP 256 上限）；settle 写挂 hash 的 artifact，`tool/result` 只摘要+artifact id；解析失败=failed 不写半份 |
| git 只读 | 无可复用 Swift 库（ce 的 git 是 MCP provider 调 git CLI） | 不适用 | R1c 只做 `git_head` UPSERT 进 `workspace_git_tips`（Python+`git rev-parse` 闭集 argv、显式 `--git-dir`/`-C`、不展开 `~`）；status/diff/log/show/blame 维持未裁不排期（若另裁：Python 包 git、op 闭集、系统 enqueue、结果进 artifact 非 stdout 直读） | tips 失败=failed 不写表；非 unknown |
| edit 物理子集 | 现在不开工 | ApplyEdits/Diffing 须先拆 EditCore（闭包无 MCP）才有 (a) 资格；`write_grant` 未立法则此段不存在；不迁 policy/journal/revalidate/presenter；`operation_id` 仍只是相关 id 非幂等键 | S4 后另裁 | 门开后才生效：系统 enqueue；路径+编辑脚本 hash+期望 content_hash 全 PG 派生；settle 写新 hash 收据+摘要；写盘可能已发生=**unknown**，仅 worker 结构化报「尚未写」才是 failed；只走 `v13_resolve_unknown` 绝不自动重执行 |
| context 族（selection/prompt/workspace_context） | SQL 投影/策略行/artifact | 不移植 mutateSelection/accessPrompt/renderWorkspaceContext（headless prompt 改的是 adapter 快照=app 状态） | R0a 立法→R0b/R6 消费；export 写盘与 edit 同扇门 | 不开端口 |
| binding（manage_workspaces/bind_context） | R0a `workspaces`+`sessions.ws_id`；动态三表后置条件不变 | 无 Swift target | R0a | 不开端口 |
| conversation（agent_*/oracle_*/ask_user/history/…） | 已换体沿用 stage 17–29（含 govern）/永不建 | 不链接 DomainRuntime 的 agent-run/oracle/session-store；history 形状只能是 SQL | 既有 | 不开端口 |

### R0a 期间唯一允许的 Swift 并行线

1. **pg-agent `v13/enumerate_names/`**（新目录、非 stage）：`enumerate_names.py` + `enumerate_names.swift`（只 `import Foundation`，`FileHandle`+单 `0x0A` 发帧不用 `print`）+ `fixtures/`（普通文件/点文件/目录 symlink/逃根文件 symlink/根内文件 symlink）+ `test_enumerate_names.py --contract`（不连 PG、不 `setup_db`）+ `README.md`（写明这不是 get_file_tree、点文件跳过不是秘密门、不进 SQL_LOAD_ORDER）。期望路径列表测试内 literal；禁止拿 Python 输出当 Swift 期望。与 R0a 分两次提交。
2. **ce 仓自己的 PR（非 pg-agent 里程碑）**：拆 `RepoPromptEditCore` + CodeMap executable 骨架与 `--version`；pg-agent 默认命令不调用它。

探针合同写死：相对 POSIX 路径、`/` 分隔、无 `./` 前缀、UTF-8 字节升序去重；只列普通文件不列目录；`.` 开头分量跳过（headless `skipsHiddenFiles` 对齐，**非**秘密门——`secrets.pem` 仍列出，I-file-3 到 R1 的 PG 准入才算）；symlink 目录不下降；根内文件 symlink 只列链接自身相对路径；realpath 逃根整条省略；根不存在/不可读/中途权限错=整次失败不返半份；空根=空数组非错误。

六停条件（任一出现即不再是离线探针，必须停）：`INSERT INTO tools` 或 `SQL_LOAD_ORDER`/`STAGE_THROUGH` 增条目；调 `v13_claim`/`v13_complete`/`v13_parse`/`v13_advance`；stdout 进 `effects.result` 或 `events`；handler 写进 read_tools 的 `HANDLERS` 或驱动器分派表；无旗标默认 gate 依赖 ce checkout 或 `swift build`；新建任何表或列。

R1a 接线细节预告（本轮不写）：`corpus_bootstrap` 行 `enabled=false`（enabled=true 会让此后每个 stage 库 needed 基数变大且模型可选中发现工具，违反 I-file-7）；advance 在 `bootstrap_done=false` 且名字表空时自己 enqueue，handler 用 SQL 字面量不走模型 choice。R1a 开工前用 `pg_get_functiondef` 复核 govern 加载后活体 `v13_complete` 是否仍把整个 `p_result` 放进 `tool/result`（只决定否定断言写法，不决定摘要合同）。

### Supersede 登记（本节对上文）

| 对象 | 处分 |
|---|---|
| 「落点定义」第 5 条泛化句「大库以后链 reprompt-ce 的库做成 CLI」 | **supersede**：链的是 ce 内新 executable 二进制（同包 `package` 可见性），不是 library product，更不是 pg-agent 侧 Swift 包 |
| 「`v13/load.py` 28 项、末项 attention、无 govern」 | **supersede**：活体现为 **29 项、末项 `v13/govern/v13_govern.sql`、`STAGE_THROUGH['govern']=29`**（本轮已实读 `load.py` 核对；read_tools README 的「24 项」同样过时，以后只以 `load.py` 为准）。控制动词仍不重包 Swift；Swift 线不与控制面同提交 |
| 可行性 v2 `file_search` 的「model+system」enqueue | **收窄，不取消 R1b**：判断面自由字符串另裁之前只许系统/PG 派生 enqueue |
| read_tools D5「缺 swift 整门退出 2」 | **不沿用到 Class F**：只约束口岸自身里程碑 |
| Phase 4 其余全部（R0a 下一刀、环上 S1 否决、F20/F28、B/C 桶、四问、不 spawn MCP、零新表） | **维持** |

### 下一刀序列（不动摇 R0a 优先）

1. **R0a**（正式下一里程碑，非 Swift，零 FS，按可行性 v2 §2.1/§8.1）。
2. 名字列举离线探针（允许并行；`uv run python v13/enumerate_names/test_enumerate_names.py --contract` 退出 0 才算绿；缺 swift 整命令退出 2，不得先宣称 Python 半边已过）。
3. R0b（`v13_visible_tools`/`v13_visible_files` 单源）→ R1a（默认 Python 引擎、冷启动 LLM effect=0、`enabled=false`）→ R1b（重写搜索）→ R1c（git tips）。
4. R6 三门绿 → S4 开门 → ce 内 (a) executable（CodeMap 先行；edit 额外须 EditCore 已拆+闭包无 MCP+`write_grant` 已立法）+ pin 四件套/部署 manifest + `THIRD_PARTY_NOTICES.md`。默认 `v13/**/test_*.py` 在二进制缺席时仍退出 0。
5. **永不执行**：(b)、spawn `repoprompt-mcp`、长驻进程、环上注册树文本、控制动词再包 Swift、在 pg-agent 复制 `RepoPromptCodeMapCore`、加宽 `read_duck` 冒充跨文件 CodeMap。
