# PG 原生 Pi 对标 Coding Agent（v14）开发规范

> 状态：核心面第 16 版冻结。台账提交标识 = 落地本声明的提交哈希；正文不嵌入该哈希，避免自指。exec 面不在本冻结，见 `docs/designs/v14.1-exec.md`。
>
> **冻结声明**：边界 = 核心面条款。不含 `v14.1-exec` 裁定循环。任意 shell/bash、闭集 exec、exec 人批、`{run-test,build}`、exec×write 同锁不在承诺。slow-build 保持 SKIP。P0 比较面以当版 HARN-4 为准：INV-4 全流、命题 A 允许表、`reconcile/diff` 不入 A、库内唯一投影函数。P0 台账无权松动；仅 P1 可登记让步。后续跟进（P2，不阻挡冻结）：`io_performed` 谓词收口进实现与 G1；金向量以预映像 hex 为权威，勘误只改表值、不改语义；本声明写回正文不构成解冻。HARN-7 检查行已改为五码三行，不再列入跟进。
> 撰写日期：2026-09-28（第 1 版 `e97f4ce`；第 2 版 `e854e04`；第 3 版 `3af3dc6`；第 4 版 `0ee355f`；第 5 版 `b5ee119`；第 6 版 `abeb6d3`；第 7 版 `928fe62`；第 8 版 `c30e87e`；第 9 版 `5778bbb`；第 10 版 `d225285`；第 11 版 `3d416ab`；第 12 版 `b89def4`；第 13 版 `3bbba86`；第 14 版 `f8fd1a3`；第 15 版 `198a441`）。工作分支：`v14-dev`。
> 修订记录：第 2 版吸收轮 1 双裁（4+3 P0）与父循环两裁决；第 3 版吸收轮 2 双裁裁决 A..M；第 4 版吸收轮 3 合并裁决 N1..N20；第 5 版吸收轮 4 合并裁决 R1..R19（条款级补丁：双序键合一、lease fencing、基线判别式决策表、准入合一、投影面拆分），全部落正文。第 6 版吸收轮 5 合并裁决 S1..S17（纯谓词判别式、出生边统一、两阶段 reconcile、digest 字节语法），全部落正文。第 7 版把 exec 面拆到 v14.1-exec 骨架，并吸收轮 6 核心面裁决 T1..T5。第 8 版吸收轮 7 合并裁决 U1..U20。第 9 版吸收轮 8 合并裁决 V1..V16。第 10 版吸收轮 9 合并裁决 W1..W15。第 11 版吸收轮 10 合并裁决 X1..X19。第 12 版吸收轮 11 合并裁决 Y1..Y13。第 13 版吸收轮 12 合并裁决 Z1..Z11。第 14 版吸收轮 13 合并裁决 AA1..AA8。第 15 版吸收轮 14 合并裁决 BB1..BB9。第 16 版吸收轮 15 微修 CC1..CC4，并冻结核心面。第 16 版不自含自身哈希。
> 效力：本文件只冻结设计，不实现；不改变 v8 / v10 / v13 已冻结面；与既有文档的合同关系见 §2。
> 上游裁决：`prompt-exports/loop-orchestrate-v14-runs.md`（父循环台账）。
> 评审分级：条款与 gate 标注〔P0〕（冻结后不可让步，违反即红）或〔P1〕（重要，偏差须登记偏差台账后方可让步）。

## 0. 定位与架构

### 0.1 一句话定位

**V14-ARCH-1**〔P0〕v14 交付一个「住在 Postgres 里的 pi 对标 coding agent」：判断（judgment）、循环（beat 序列）、治理（审批/预算/权限）、记忆（events/trace）全部 SQL-resident，底座为 pgembed + 既有 v13 内核面。harness 是可丢弃的薄载体；对标对象是 pi 的产品面（工具集、REPL 体验、基准成绩），不是 pi 的架构面。检查：§1 不变量逐条 gate；§6 各期 gate。

### 0.2 v14 不是 pi 的移植

**V14-ARCH-2**〔P0〕架构对照（冻结，禁止漂移）：

| 维度 | pi | v14 |
|---|---|---|
| agent 本体 | 进程即 agent（Node 进程内 loop） | DB 即 agent（beat/advance 落库，进程只是执行器） |
| 会话事实源 | 进程内 session 状态 + 持久化层 | events 表（只追加），一切历史从表重建 |
| 判断 | 进程内模型调用 | SQL 面发起判断请求，回答落 judgment 记录 |
| 载体 | TUI（进程内终端 UI） | 可丢弃窗口（Chainlit / 脚本 / psql 三壳等价） |
| 崩溃语义 | 进程死即会话死 | kill 载体 → resume → 终态有定义且可实证（INV-3 双命题，适用面见 V14-EFF-6） |

仿的是：工具集形状（read/write/edit/glob/grep；exec 不在本核心冻结，见 v14.1-exec）、REPL 对话体验、基准任务成绩。不仿的是：进程内循环、进程内事实源、TUI 耦合。检查：设计评审对照本表；G3 双壳/可弃 gate。

### 0.3 Chainlit 使用约束

**V14-ARCH-3**〔P0〕Chainlit handler 只允许两种动作：**submit**（把用户输入经既有 SQL 命令入口提交进库）与 **observe**（LISTEN 事件流 → 渲染）。UI 历史从 events 表重建；Chainlit 会话内存不得成为事实源（INV-6）。审批动作在 UI 上也只是向 SQL 批准命令提交标量（approver 身份由 DB 得出，见 V14-APPR-6）。检查：source gate 静态扫描 handler 模块（V14-HARN-6）。

**V14-ARCH-4**〔P0〕明示反模式：禁止照抄 Chainlit 官方教程把 agent 循环写进 `@cl.on_message` handler（在 handler 里调 LLM、跑工具、维护对话状态、代批代答）。handler 内出现任何 beat 驱动、模型调用、工具分派、判断拼装即红。检查：source gate 断言 handler 模块 import 黑名单（V14-HARN-6）。

### 0.4 对标面定义、差异登记与威胁模型

**V14-ARCH-5**〔P1〕对标成立的三件事：① 工具面覆盖 read/write/edit/glob/grep（**不含 exec**；exec 与 pi bash 的差距见 V14-ARCH-6 与 v14.1-exec）；② REPL 体验：Chainlit 窗口可对话驱动、可断线重连、历史完整；③ 基准：§5 任务套件上产出 v14 vs pi 对照报告。不承诺 TUI 视觉复刻、不承诺 pi 插件生态兼容。检查：G3/G5 gate 与对照报告。

**V14-ARCH-6**〔P1〕对标差异登记表（对 pi 语义的显式偏差，逐条列出，新增须 bump）：

| 差异点 | pi 语义 | v14 语义 | 理由 |
|---|---|---|---|
| `write` | 覆盖或创建 | **create-only**：目标已存在即拒绝；覆盖一律走 `edit` | mutating 效果可解释性（diff 恒为创建形态，V14-TOOL-2） |
| 审批门控 | 工具调用无审批环，权限在进程内裁量 | **write/edit = grant 门控**（未命中 grant 准入拒绝，无逐次人批）。exec mutating 的逐次人批不在本核心面 | mutating 效果治理（V14-APPR；V14-TOOL-6）。exec 人批见 v14.1 |
| 无任意 shell | pi 有 bash（任意 shell 字符串） | **无 bash、无 shell**。闭集 exec 目录不在本冻结承诺，待 v14.1 裁定 | **对 pi 的重大偏差**（§9.4）。核心面基准不得把缺席记为 bash 覆盖 |

检查：G1 gate（write create-only 负例 + 准入两分支夹具）；设计评审对照本表。

**V14-ARCH-7**〔P1〕威胁模型（写死）：载体（carrier）= **trusted-but-crashable**——可崩溃、不可恶意。执法面：worker 能力合同（INV-5）+ SQL 结构性验证回执绑定与映射（INV-1 第 4 类）；resume_probe 观测由**受信 worker** 产出（V14-EFF-3）。对抗性载体（伪造回执/恶意观测）的完整性加固 = §9 范围外。检查：设计评审对照本条；G1/G3 gate 的回执验证断言。

## 1. 不可妥协的不变量（V14-INV-1..6）

> 本节原文照录父循环裁决，是全部后续条款的上位约束。任何 stage 设计、实现、gate 与本节冲突即无效。

**V14-INV-1 判断零外置（四类提交闭集）**〔P0〕一切决策（下一步做什么、何时结束、调用什么工具、是否需要模型判断）由 SQL 面产出（advance / 判断请求拼装与入队全在库内）；LLM 调用只是判断请求的数据面——问题由 SQL 面拼装、回答落 judgment 记录。**执法语义（四类提交闭集）**：harness 向库内提交的输入只许四类，每类只能调用**已登记 SQL 函数**（v13 既有 + v14 迁移新建），禁止裸 DML、禁止 harness 发 `pg_notify`：

1. **用户文本**（submit 入口）；
2. **审批决定**（approve | deny | reconcile 的标量参数；签名面见 V14-APPR-2/3/6——不收 session_id/proposal_id/principal/now，会话来自认证连接绑定）。requested 的 expire 属 v14.1 入口；核心无 requested 对象，无行为缺口；
3. **判断答案**（FakeLLM 与真 provider 的回答文本同形，落 judgment；错误码闭集与乘积表见 V14-HARN-7 / V14-EFF-6）；
4. **工具回执**（统一 envelope：`kind`、`effect_id`、`attempt_id`、`request_id`、`fencing_gen`（执行时的 lease fencing generation；与所绑 effect 或 observation request 的当前代不一致 → **拒绝落库、状态不变**，V14-EFF-2）、`status`、`exit_code`、`payload_digest`、`stdout`、`stderr`、`diff`——SQL 验证绑定与状态后落库；driver 仅 opaque 转发，禁止解析回执推导下一步）。**kind 闭集** = `tool | resume_probe | preflight_probe | claim_probe | reconcile_probe | session_baseline | cleanup`（+ `request_id` 绑定，不是第五类提交；`cleanup` 见 EFF-3）。tool 回执 **status 闭集 = `succeeded | failed`**；**`exit_code=null` 只用于 write/edit 与各 probe**。read-only tool receipt 的 `exit_code` 是十进制整数，成功 = `0`（黄金向量 V-rcpt-ro 保持）。exec 映射见 v14.1。**attempt_id 绑定（写死）**：mutating 的 tool receipt，`attempt_id` 规范值 = **JSON null**，且 SQL 验证该 effect **无 attempt 行**；read-only 的 tool receipt 与 provider 完成提交的 `attempt_id` **必须非空**且绑定该 effect 的 attempt 行（provider 完成走第 3 类 judgment 提交，不走 tool receipt，V14-EFF-6）。**payload_digest 绑定实际用于判断的 typed body**（mutating 只绑 `observation_digest`，diff 固定省略）。预映像 = `kind/effect_id/attempt_id/request_id/fencing_gen/status/exit_code/body_digest`。`token_id` 不入预映像。（status 已按 exit_code 规范化；不含 volatile；字节语法见 V14-TOOL-2；mutating tool 的 `body_digest` = `observation_digest` = 全观测记录字节 sha256 的 64 hex（diff 固定省略；worker 仍提交 diff 且与 proposal 不一致 → 拒绝）。probe = 目标路径观测的 sha256。SQL 从提交的 typed body 重算。禁止「可同时含 diff_digest」的总括。`session_baseline`：body = 按路径字节序的全观测串联，`effect_id=null`，`attempt_id=null`，`request_id` 非空，`exit_code=0`；无法观测 = request 失败，不伪装。`cleanup`：body = 单记录 `temp_state`（`absent|removed|out_of_bounds`）+ `0x0A`，`effect_id` 非空，`attempt_id=null`，`exit_code=0` 只表示 request 已处理。另有向量：proposal/diff 不变而观测变 → digest 必变，provider 完成预映像 kind 字面 = `judgment`）。probe 载荷 = per-path 全观测 `{exists, file_type, mode, sha256}`（resume_probe 另携带临时文件内容摘要/类型/mode，受信 worker 产，V14-EFF-3）；preflight_probe 不建 effect。

**无参已登记函数**（`advance` / `next_beat` / `expire_due`）**不是第五类输入**——它们没有参数面；任何新入口的参数面禁判断内容、principal、now、session_id。

人批与模型回答同属外部判断数据面：请求由 SQL 产出、答复落库；harness 不代批、不代答、不拼装。检查：G3 source gate（INV-5 扫描 + import 黑名单 + envelope 仅经登记函数断言）+ 判断面 gate 回归。

**V14-INV-2 beat 序列是数据**〔P0〕beat 序列（judge/parse/advance/claim/tool/llm/finish 一类的拍结构）是库内数据，不是代码控制流。advance 决定下一步，harness 仅执行。先例：`v13/pi_parity/test_pi_parity.py:66` 的 `GOLDEN_SEQUENCE`（canonical phases）与 `v13/read_tools/test_read_tools.py` / `v13/pi_ports/test_pi_ports.py` 的 ring 驱动。**相位定案**：assistant（模型）输出是**显式 canonical phase**（拍结构中的 `llm` 相），不是 `claim kind=llm`——按 pi_parity schema-v2 定案，本条为二选一歧义的落死。检查：G3 gate 断言 beat 拍落 events 表且驱动模块无硬编码序列分支、llm 拍为独立相位。

**V14-INV-3 会话可弃（双命题，适用面受限于 V14-EFF-6）**〔P0〕kill harness → 重启 resume 的可操作承诺收窄为两个命题，分别断言：

- **命题 A（事件面，独立语义子流）**：已提交事件的**A 子流**（字面 kind 白名单写死于 V14-HARN-4：`effect/terminal`（`terminal_reason=attempt_exhausted`）入 effect 终态；proposal 只收 `consumed` / `denied` / `expired`；beat、grant 变更、`resume_probe` / `preflight_probe` / `claim_probe` / `reconcile_probe`、attempt、lease reclaim **不入 A**；增 kind 须 bump）的规范化投影在「杀过」与「未杀」两条世界线上一致。G3 窗 1 断言子流逐行相等 + `tool/result` 规范 diff 与 `workspace_effect_seq` 相同。**A 允许表是〔P0〕比较面，偏差台账不能扩**（V14-HARN-4）。
- **命题 B（工作区面）**：工作区终态 = 会话创建时持久化的 **per-path 初始全观测** 起，按 `workspace_effect_seq` 升序折叠「成功 tool/result diff ∪ reconcile/diff」（`expected`，V14-EFF-5）。tree hash 只做同一性校验，不是折叠基底。reconcile SQL 成功后，折叠含该 seq 的 reconcile/diff；只排除 reconcile 前的 unknown 前缀。

**适用面**：FakeLLM 路径与已提交 judgment 的 provider 路径；write/edit 的 unknown 未 reconcile 窗口、provider 未提交 judgment 的窗口除外。**命题 A 只断言窗 1 与从未置位过 `degraded_effect_id` 的路径；failed+degraded 在 reconcile CAS 成功后只断言命题 B。reconcile/diff 仅进全流比较面，命题 A 永不纳入**。曾经置位过的世界线，清空后只恢复命题 B，不与从未 degraded 的世界线做 A。`degraded_effect_id IS NOT NULL` 的世界线（unknown 或 failed+degraded）都不宣称命题 B。reconcile CAS 成功后 B 恢复，折叠含该 seq 的 reconcile/diff。`failed(stale)` 与 `attempt_exhausted` 不设 degraded，保持可比较。exec 走 reconcile 时只恢复 B、不恢复 A 的原句见 `docs/designs/v14.1-exec.md`，不在本核心面。检查：G3 杀进程续跑 gate（write/edit，不依赖 exec）+ G4 kill gate 按 EFF-6 断言。

**V14-INV-4 双壳等价**〔P0〕Chainlit 驱动与脚本驱动同输入 → **服务端投影 ::text 逐字节相等**。比较面与投影算法**写死于 §4.3（V14-HARN-4）**：库内唯一 canonical 投影函数（`reconcile/diff` 不得进入 A 投影）、代理键 allowlist、volatile 键表、服务端比较；**双壳用 §4.3 全流**（两壳无杀点，与 INV-3 命题 A 的子流是两个不同比较面）。比较面新增排除项不属于已冻结类别时必须 bump 本规范——偏差台账无权松动 P0 比较面。检查：G3 双壳等价 gate。

**V14-INV-5 harness 决策点计数进 gate（按文件上限）**〔P0〕harness 的「薄」用决策点计数量化并进 gate。**口径（闭集）**：ast 扫描，计数节点闭集 = `If` / `For` / `While` / `Match` / `ExceptHandler` / `IfExp` / 推导式 `if`；`BoolOp` 不计。**扫描集**：`v14/harness/**/*.py`（排除 `tests/`、`workers/` 子树）∪ `v14/provider/**/*.py`（排除 `tests/`）。**上限（按文件，现在冻结）**：`v14/harness/driver.py` ≤ 15；`v14/harness/handler.py` ≤ 5；`v14/harness/` 同目录其余文件（除 `tests/`、`workers/`、`provider/`）合计 0——**新增 harness 文件须 bump 本规范**。provider 文件不设数值上限，但执行能力闭集（见下）。**import 前缀黑名单（写死）**：`litellm`、`v13.govern`、`v14.govern`、`v14.tools`、`v14.exec`、`v14.provider`——harness 内（driver/handler 及同目录）一律禁止 import。**worker 能力协议**（豁免边界 = 经 `run_line_json` 拉起的子进程）：单 effect 单进程、禁开 DB 连接、禁 import 模型 SDK、禁写声明路径外、退出即终；回传仅 stdout/stderr/exit code，以及按 kind 的 typed body。baseline worker 同属能力闭集：no-follow 全量观测，禁写、禁 DB。temp 根在 workspace 根外；投影在绝对路径检查之前，把 temp 根前缀换成稳定字面量 `$tmp`（不是代理键）。替换后仍残留 workspace 外绝对路径才 gate 失败。glob/grep/baseline 不枚举 `$tmp`。声明路径 = 该 effect 的 workspace 目标路径 ∪ 该 effect 专属 temp；cleanup worker 只许删该 temp。driver 不得改写 SQL 交出的 payload 字节。**provider 进程能力闭集**（`v14/provider/`）：可 import litellm；禁开 DB 连接、禁 beat 循环、禁写工作区；回答由 driver 按 INV-1 第 3 类提交。检查：G3 `test_thin.py`（per-file 计数 + 黑名单 + 两类能力协议）；G4 provider 能力 gate。

**V14-INV-6 载体即窗口**〔P0〕UI 只 submit + LISTEN 渲染。历史从 events 表重建，Chainlit 会话内存不得成为事实源；刷新、重连、换壳后 UI 呈现完全由库内 events 决定。检查：G3 gate（重连后从表重建渲染断言）+ source gate（V14-ARCH-3/4）。

## 2. 与既有版本的关系（supersede / 退役 / 继承）

### 2.1 v8-P0C 的解除（retire）

**V14-SUP-1**〔P0〕v8-P0C（`docs/plans/v8-p0c-compat-host-plan-2026-09-17.md`）的目标是「一个最小 turn 在两个运行时（v8 native loop vs pinned DSH Node host）同合同跑通等价」；其调查已确认 DSH = DeepSeek Harness（该计划 §0.1），并把 §5.2 pre-IO 落盘判定设为 C2 go/no-go。P0C 的 host 接线（C0–C6）至今未完成。

v14 冻结时将 P0C **解除/退役**（retire），并做三件事写死：

1. **tombstone**：P0C 计划文件头部加退役注记（不改其正文）——C0–C6 未完成即退役；退役不是交付。
2. **义务未转移**：P0C 的「双运行时（native vs DSH host）等价」目标不迁移给任何 v14 stage。v14 的 INV-3 双命题与 INV-4 双壳等价是 v14 自身的验收面，不承担、也不替代 P0C 的义务。
3. **DSH host 路线关闭**：不再作为任何 stage 的依赖或后备路径。DeepSeek 在 v14 中的唯一身份是 G4 判断面 provider（经既有 litellm 依赖调 API），与 DSH host 无关。

检查：设计评审对照本条；P0C 计划 tombstone 随 v14 冻结提交落笔。

### 2.2 承接父循环台账识别的 v10 硬缺口

**V14-SUP-2**〔P0〕「硬缺口」措辞依父循环裁决更正为：**父循环台账在 v10 冻结后识别的硬缺口**（`prompt-exports/loop-orchestrate-v14-runs.md:7`：「v10 硬缺口（grant 模型/插件世代）在 G1/G2 自然承接」）——该清单不是 v10-dev 原文措辞。现状核实：grant 模型与 generation 已由 `docs/plans/v8-p1-grant-generation-p0c-plan-2026-09-16.md` 交付（G10–G19b，v8 全量 24 gate 绿，`v8/README.md:9`）；P0C 见 §2.1（退役）；v10 本体未实现且保持冻结不动。

v14 与 v10 的关系：v14 **不是** v10 的实现，也不回改 v10 规格。G1/G2 在 v13 底座上承接残留缺口：

- G1 工具目录加 mutating 语义（§2.3 合同 v2）即「工具/插件世代」问题的 v14 承接面：目录行版本化、request 创建时绑定 `contract_version` + generation（§2.3 回填机制）、旧请求 handler 冻结语义（先例 TP-CAT-2）必须保持。
- G2 权限与审批环落在 v13 既有 `v13/govern/`（`v13_govern.sql` + gate）之上：govern 人批由 **v14 新函数调用既有入口**实现，不改 `v13/**/*.sql`；如确需动 v13 冻结面，一律走独立内核变更流程（§2.3 路径）。

检查：G1/G2 source gate（对 v13 冻结面零 diff，除内核变更提交）；设计评审对照本条。

### 2.3 口岸合同 v1 → v2 bump（就地 bump + 回填机制）

**V14-SUP-3**〔P0〕v14 工具面扩展遵守 `docs/designs/v13-tool-ports.md` 的合同纪律：现行版本 `v13/tool-port-contract-1`（该文档 L5：改变行为必须同一提交 bump 版本号；已发布条款 ID 禁止复用；废止保留 ID）。**TP-CAT-4**（该文档 L48）明文：新口岸确需改 schema 或加列（含 `input_schema` / `mutating` / `allowlist` / `timeout_ms` / `consumes` / `produces`）时，必须拆成**独立内核变更**并 bump 合同版本，禁止夹带在口岸提交里。

v2 bump 走法（父循环已裁）：

1. **载体**：在 `docs/designs/v13-tool-ports.md` 原文档**就地 bump** 版本号至 `v13/tool-port-contract-2` 并追加 v2 条款（mutating 语义 / diff 协议 / 审批 hook）。**闭集命令执行器不在核心 v2**，移到 v14.1。**v1 条款字节不动**（旧 ID 保留原文，新义务一律用新 ID 追加）。
2. **混合世代与回填机制（写死）**：
   - 迁移列：`contract_version text NOT NULL DEFAULT 'v13/tool-port-contract-1'`；`generation` NOT NULL，默认取 v13 世代常量；既有 request 行按此回填。
   - v14 trigger/wrapper 承接双入口：旧入口创建的 request 从绑定 generation 回填 v1；v2 入口同事务写 v2 + 当前 generation。
   - **无法解析绑定即拒绝创建**，禁止隐式降级、禁止重解析旧请求为新语义。
   - gate 覆盖两条路径：v2 发布前排队的 v1 请求（仍走 v1 handler）+ v2 发布后新建的 v2 请求。
3. **版本头预检（已核实）**：v13 gate 对该文档只有 `isfile`（`v13/read_tools/test_read_tools.py:1998`，G2）与 README 路径/条款 ID 针（`:1728`，E3 needle 列表），**不解析文档版本头**——K 提交 bump 版本号不触碰 v13 断言；K 提交仍须同笔复跑 E4 全量实证。若实现期发现任何读取版本头的断言，先把「文档版本」与「v13 运行时常量」拆开再 bump。
4. **schema 落点（已裁）**：v14 累计迁移——`ADD COLUMN mutating boolean NOT NULL DEFAULT false` 等列以 v14 拥有的迁移 SQL 进入累计加载序列；`v13/**/*.sql` 历史 SQL 零改动。
5. **同笔义务**：内核变更提交（K，见 §6 G1）内同时包含合同 bump 文档、迁移 SQL、允许名单（哪些新列/新口岸被 v2 授权）；既有全量 gate 复跑绿。
6. **条款延续**：v2 完整继承 TP-INV-1..15 与 TP-WIRE / TP-FS / TP-GATE / TP-ADMIT 既有条款；新增面按 TP-ADMIT-1 十项准入清单同等标准补齐。

检查：G1 `test_contract_v2.py` 断言 contract-2 已 bump、v1 条款字节零改动、回填两路径、无隐式降级负例；E4 回归。

## 3. 效果协议与工具面（G1 冻结面；exec 见 v14.1）

### 3.1 效果协议（V14-EFF，G1 起生效，全部 stage 共用）

**V14-EFF-1 效果状态机（六态闭集 + 出生三分 + 转移表写死）**〔P0〕effect 态闭集 = `planned | claimed | started | succeeded | failed | unknown`（**无** approved/reconciled 态；批准语义在 proposal 上，V14-APPR；reconcile 是动作不是态）。**出生三分（三类创建事务均写 `fencing_gen=1`）**：

- **mutating**（write/edit；**不含 exec**）：与 proposal 批准**同事务** INSERT 即 `planned`，`fencing_gen=1`，**此时无 lease**（owner/until 空）。claim 成功只填 owner/until，**代际保持 1**。升代点见 EFF-2（仅 claim 后强制 1→2，以及 owner 变更）。首次 `claimed→started` 要求 `fencing_gen≥2`（无 reclaim 的快乐路径恰为 2；reclaim 后可更高）。被拒/超时不建 effect 行；**无 attempt 行**。mutating receipt 的 `attempt_id` = JSON null，且 SQL 验证无 attempt 行。receipt/probe 的 `fencing_gen` 必须等于当前代。
- **read-only**（glob/grep）：**无 proposal**，SQL INSERT `planned` **同事务直接 `started` + attempt 1 + `fencing_gen=1`**（无 claimed 停留、无锁、无 seq）。**五步优先级（一次主转移，不是五条并列边）**：① 当前 attempt 有未入账 receipt → 原子处理一次。`ok` / `output_limit` / `bad_input` 在①落终态后停止。仅 `io_error` 标记已处理、消耗 attempt、保持 `started`，本拍继续向下。② effect 已终态 → 返回。③ 已消耗**且 lease 有效**：行数=1 → 开 attempt 2（新 attempt 初始化自己的 lease）；行数=2 → `attempt_exhausted`（两 attempt 均已消耗且①未使终态），`effect/terminal` + `terminal_reason=attempt_exhausted`，不设 `degraded_effect_id`。④ lease 到期 → 只 reclaim（`fencing_gen+1`，不消耗、不开 attempt），不限是否已消耗。consumed 且到期落④，下一拍 lease 有效后再走③。⑤ 未消耗且 lease 有效 → 重派同 attempt、同 fencing。失败 receipt 保留；处理幂等键；重复 receipt 零更新。超限不截断成成功。
- **provider**：**无 proposal、无锁、无 seq、无 reclaim**；`start_attempt` 同事务插 `started` + attempt 1 + `fencing_gen=1`。同 effect **至多一个未消耗 attempt**。下一 `start_attempt` 仅当 `started` ∧ 该 attempt 已消耗 ∧ 行数<2（不换 effect、fencing 不变）。行数=2 且都已消耗 → 不插行，同事务 `attempt_exhausted`。driver 每次消耗后必须再调 `start_attempt`，由 SQL 决定插入或终结（EFF-6）。
- **边界**：v13 既有 read 口岸保持 v13 语义，**不建 v14 effect**。

转移表：

| 转移 | 条件与方式 |
|---|---|
| → `planned` / `started` | 按出生三分（上行）。read-only 与 provider **不经过 claimed** |
| `planned` → `claimed` | 仅 mutating。条件 UPDATE：proposal=approved、effective_now 未过 expires_at、grant 未撤销未过期（APPR-5）、`degraded_effect_id IS NULL`、proposal `old_*` = `expected`（EFF-5，不重叠 diff）。**同事务** proposal→`consumed`、分配 seq（每个 effect 至多一次，EFF-4）。**失败短路序 ①时间 ②grant ③symlink ④基线，先命中独占一条 `claim/audit`（`payload.reason` ∈ {time, grant, symlink, baseline}），禁并行 kind**。后置条件见下表。**本格无「已 IO→unknown」**。**过期终态名单一选死 = expired** |
| `claimed` → `started` | 仍为 claimed 时先跑四诊断，命中都不得转 started：① lease 失配 → 不改状态、走 reclaim；② 时间/grant → `failed`，proposal 保持 consumed，seq 保留，unlock，零 rename；③ symlink → `failed(stale)`，不进 degraded；④ 基线失败 → stale 或 failed+degraded（非 symlink），proposal 保持 consumed。四者都不命中 ∧ 代际≥2 ∧ 当代 probe 已成功 → 才执行 started UPDATE。成功谓词与四诊断写成同一 WHERE：`state=claimed AND lease_owner=当前执行者 AND lease_until>effective_now AND fencing_gen≥2 AND grant 未撤销未过期 AND expires_at>effective_now AND 非 symlink AND 基线匹配 AND 当代 probe 已成功`。该 UPDATE 的 0 行才零 IO、不改状态。claim 成功后 grant 撤销 → effect `failed`，proposal **保持 consumed**（无 expired 出边），不发 tool/result，seq 保留，unlock。started 之后撤销按 APPR-5 检查点②，不回滚 IO |
| `started` → `succeeded` | 分类第①支（fsync 通过）+ 第③支复验谓词命中 + 与分类互斥的 mutating receipt 成功边（`status=succeeded` 且全观测=目标态 ∧ `exit_code=null`）。diff 取自 proposal。`status=failed` 拒绝落库，保持 started，走分类 |
| `started` → `unknown` | 已 started 的 symlink 臂 + 第①支 fsync 失败 + 第②支（含第③支复验不等）。同事务 degraded，零再 rename |
| `started` → `failed`+degraded | 第④支其余无 IO：观测≠expected，或 =expected 但 pending 不成立，或无 IO 但已=目标态。零 rename。唯一 mutating `started→failed` |
| read-only 完成 | `ok`/`0`→succeeded；`output_limit`/`1` 与 `bad_input`/`2`→failed，不 degraded；`io_error`/`3` 保持 started |
| provider 完成 | 乘积表三行另列。`attempt_exhausted` 保持现有行，不写错误 judgment |
| `started` → `started` | read-only 五步序第 ⑤：未消耗且 lease 有效，重派同 attempt、同 fencing。provider：未消耗才可重派；消耗后禁重派 |
| `started` 保持，开 attempt 2 | read-only 五步序第 ③：已消耗且 lease 有效且行数=1。新 attempt 初始化自己的 lease |
| `started` → `failed(attempt_exhausted)` | provider：行数=2 且都已消耗。read-only：五步序第 ③（已消耗、lease 有效、行数=2、①未使终态）。kind=`effect/terminal`，`terminal_reason=attempt_exhausted`，入投影，不设 degraded。mutating **无**此边 |
| `started`（resume，无 receipt） | write/edit 的无 receipt 终态**只有**分类四支（EFF-3）。**禁止** attempt_exhausted、裸 `status=failed`、第二条 SQL 边把 started 打成 failed。provider 不进 unknown。read-only 走五步序，不走分类 |
| `unknown` 或 `failed`+degraded → `succeeded` / `failed` | 仅两阶段 reconcile（EFF-5）。选择与 CAS 只绑 `degraded_effect_id`。成功则清 degraded 并写 `reconciled_at`，无论 outcome |

**claim 事务后置条件表（只覆盖尚未 consume 的 `planned→claimed`；屏障行在四失败行之前；失败行仍短路，先命中独占一条 `claim/audit`，`payload.reason` ∈ {time, grant, symlink, baseline}）**：

| 行 | effect | proposal | 名额 | 审计 kind | seq | advisory lock |
|---|---|---|---|---|---|---|
| 屏障（`degraded_effect_id` 非 NULL，或其他未终态 claimed/started/unknown mutating） | 保持 `planned` | 保持 `approved` | 不变 | 不写失败审计 | 不分配 | 0 行更新；已取锁则 unlock 并归还；下拍再试 |
| ① 时间（now≥expires_at） | `failed` | `expired` | 释放 | 时间过期（单审计） | 不分配 | 已取锁则 unlock；专属连接归还 |
| ② grant 撤销/过期（①未命中） | `failed` | `expired` | 释放 | `claim/audit` reason=grant（单审计） | 不分配 | 已取锁则 unlock；专属连接归还 |
| ③ symlink（①②未命中；目标或任一父分量） | `failed(stale)`，不进 degraded。已 consume 的锁内复算见转移格③ | `expired` | 释放 | `claim/audit` reason=symlink | 不分配 | unlock 归还 |
| ④ 基线不符（①②③未命中；只接收非 symlink 观测；`expired` 只在本相位） | explainable 且 `old_*`≠`expected` → `failed(stale)`，不 degraded，不发 tool/result；非 explainable → `failed` 且 degraded（未 IO，同事务写 `io_performed=false`）。调用点写一次 | `expired` | 释放 | `claim/audit` reason=baseline（单审计） | stale 不分配；进入 degraded 且该 effect 尚无 seq 则本事务分配一次 | 已取锁则 unlock；专属连接归还 |

一切 pre-apply 终结路径（上表四条失败行，以及锁内复算不符、尚未 started 的终结）均显式 unlock + 归还专属连接。claim 成功不在本表：effect=`claimed`、proposal=`consumed`、名额保持占用、seq 本事务分配、锁跨 COMMIT 持有至 apply 结束（EFF-4）。

检查：G1 起各 gate 断言合法转移集（非法转移负例）+ 后置条件表屏障+四短路行逐列 + 短路单审计 + 基线行 proposal→expired 且释放名额 + pre-apply unlock + `attempt_exhausted` 的 `effect/terminal` + read-only/provider 无 claimed 停留 + `expire_due` 四类 CAS（probe/cleanup/token/baseline）。

**V14-EFF-2 intent 行、效果身份、观测请求与 lease fencing（终版）**〔P0〕任何 **v14 effect** 的外部 IO 发生前，effect intent 行必须已提交入库（intent 事件位置仅表「IO 前日志已提交」，**不定义序**）；**效果身份 = `effect_id`（唯一）**。**三类 effect 创建事务均写 `fencing_gen=1`**。**范围边界**：proposal preflight read（V14-TOOL-3 ①）**不属于 effect IO**——只读、受读 lease 保护、不建 effect；apply 阶段以 EFF-3 锁内复算基线为准。

**观测请求（SQL 先建、不可变）**：preflight 与 pre-claim baseline probe **各有身份**。worker 任何观测 IO 之前，SQL 已提交 observation request 行（`request_id`、角色 `preflight | claim_baseline | resume | reconcile | session_baseline`、所绑 effect 或读 lease、`fencing_gen`）。worker 不得自造 request。回库走 INV-1 第 4 类，kind = `preflight_probe | claim_probe | resume_probe | reconcile_probe`，**必须绑定 `request_id`**（不是第五类提交）。digest 预映像、fencing 代、投影归类（probe 类不入 A，V14-HARN-4）与失败/超时边同轮冻结：

- fencing：probe receipt 的 `fencing_gen` 必须等于 request 行当前代；绑 effect 时还必须等于该 effect 当前代；不一致 → 拒绝落库、状态不变；
- **probe request 状态闭集**：`pending → succeeded | failed | timeout | superseded`，以及 `succeeded → superseded`。`superseded` 不可提交 receipt，不可驱动 effect。成功 receipt 同事务原子记下不可变 body。重复成功 = 幂等零更新。`failed` / `timeout` 之后的迟到成功 **拒绝**。timeout 只有 DB 时钟入口。
- 失败/超时 **不改 effect / proposal 态**。preflight 失败 → 不建 proposal、不建 effect、释放读 lease。pre-claim 的 claim_probe 失败 → effect 保持 `planned`，不分配 seq。**锁内 claim_probe 失败 → 保持 `claimed`**（不回 `planned`，seq 与 proposal 不动，锁继续持有，下一拍新建 request）。claim/resume probe 已 `succeeded` **且** `request.fencing_gen=effect.fencing_gen` **且** 当前 lease owner 有效 → 下一拍禁新观测 IO，只用已提交 body。代际变化则旧 request 为 superseded，必须建当前代新 request，旧 body 不得驱动 started。复验有自己的 request：SQL 在授权 rename 之前插入本代、绑定该 effect 的复验 request（第 4 类，role=resume），同事务把同 effect 同代既有 resume request 标 `superseded`。同 role 只取最新 succeeded request。worker 只交这一条 receipt。fencing 与 `state=started` 都匹配 ∧ receipt 已落库 ∧ CAS 未完成 → 禁再插、只送 CAS。fencing 不匹配 → 该次提交按 INV-1 拒绝落库（不算「已回」），旧 request 标 `superseded`，仅 `state=started` 时插当前代新 request。`state≠started` 不新建、不进分类。resume_probe 失败 → 保持 `started`，零 rename。reconcile_probe 失败 → 不写 outcome，token 按 EFF-5 超时边恢复。

claim 带 `lease_owner` / `lease_until`（now 取 V14-APPR-3 的 effective_now）与 **fencing generation**（初值 1；升代点按下文写死，不含同 owner 的 TTL 刷新）。read-only 在出生事务写 lease。provider 出生写 `fencing_gen=1`，**无 reclaim**。**fencing 规则（写死）**：

- `claimed→started` = EFF-1 一条条件更新，**且仅在 renew 之后、锁内基线匹配之后**，**仅 started UPDATE 的 0 行才零 IO**；
- **mutating renew/reclaim** = 单条 SQL，`WHERE state=claimed ∧ (lease_owner=当前执行者 OR lease_until≤effective_now)`。0 行不改状态。`claimed→started` 的判定顺序以 EFF-1 该格为准：四诊断先于 started UPDATE；① lease 失配不改 effect 状态、走锁内 reclaim；②③④ 按 EFF-1 对应规则终结。四者命中均不得执行 started UPDATE。该 UPDATE 的 0 行才零 IO、不改状态。**只在两处升代**：claim 后强制 1→2，以及 lease **owner 变更**。同一 owner 的纯 TTL 刷新不升代，不失效当前代已成功 probe。`claimed→started` 在「当前代 probe 已成功 ∧ owner 仍是该执行者」时，先做不升代 TTL 刷新再转移。probe timeout 短于剩余 TTL；超时后迟到成功仍拒。
- **read-only reclaim** = 行级 CAS：`state=started ∧ 当前 attempt 无未入账 receipt ∧ lease_until≤effective_now`，同事务续租 + `fencing_gen+1`，不新开 attempt，不要求 workspace 锁。attempt 2 不是这条边；
- **provider 无 reclaim**；
- **resume_probe 单胜者 CAS**（`WHERE state=started`；败者零 IO）。reconcile 的单胜者是 token CAS，不是 effect 行上的第二套胜者（V14-EFF-5）；
- **receipt 携带 fencing generation**，与 effect 或 request 当前代不一致 → 拒绝落库、状态不变（INV-1 第 4 类）。

检查：G1 gate（intent 先于 IO、创建事务 fencing_gen=1、观测请求先于 probe IO、claimed→started 仅 started UPDATE 的 0 行才不改状态、mutating reclaim 持锁前置、read-only reclaim 不要求 workspace 锁、provider 无 reclaim、probe 失败不改 effect 态、过期 receipt 拒绝）。

**V14-EFF-3 write/edit 原子写与 resume 分类（顺序钉死 + 观测完备）**〔P0〕apply 顺序写死，不得重排：

1. **取锁**。拿不到则结束事务，effect 留 `planned`/`claimed`，零外部 IO。
2. **pre-claim probe**（代际 1）。outstanding probe 期间**禁 renew**。
3. **claim 成功**：填 owner/until，代际仍 1，proposal→`consumed`，分配 seq（至多一次）。
4. **同一条 renew SQL** 把代际升到 2，保持 `claimed`。
5. **按代际 2 新建锁内 claim_probe**。禁复用 pre-claim body。
6. **不符** → 终态（explainable 漂移 → `failed(stale)` 不 degraded；symlink 见 EFF-5 例外；其余非 explainable → `failed`+degraded）。proposal **保持 consumed**，seq 复用，unlock，不发 tool/result。proposal 到期或 grant 撤销/到期 → effect `failed`，proposal 保持 consumed，seq 保留，释放锁与连接。lease 失效或 owner 不匹配 → 零 IO，走既有恢复，不误写终态。基线失败走 stale/degraded。未 started 不得进 resume 分类。G1 必测「锁内 probe 期间到期」。
7. **符合才** `claimed→started`（要求代际 ≥2）。之后才写临时文件。
死于 `claimed` 的唯一恢复序：① `try_lock` 0 行则下拍保持 claimed；② 调与快乐路径同一条 renew/reclaim SQL。`fencing_gen=1` 必定升到 2；此后只有 owner 变更再升，同 owner 且代际已 ≥2 只刷 TTL；③ 当前代已有 succeeded 且 `request.fencing_gen=effect.fencing_gen` 的 claim_probe → 禁新观测、复用 body。代际已变 → 旧 request 标 `superseded` 并新建。旧 request 已 failed 或 timeout → 按当前代新建。禁无锁 probe。代际 1 的 pre-claim body 升到 2 后不得驱动 started。

**started 之后**，mutating 无合法 succeeded receipt 时终态只来自分类四支。窄禁令保留：禁 `attempt_exhausted`、裸 `status=failed`、分类外 SQL 边。

临时文件是 **effect 专属**（路径含 `effect_id`），存活至 effect 终态。**清理**（kind=`cleanup`，第 4 类，不是第五类提交）：SQL 先建 cleanup request（`pending`）。受限 worker 确认 effect 已终态后删该 effect 专属 temp。`failed`/`timeout` 后按 effect 唯一键建新 cleanup request，同时至多一个未完成。重试上限 = 3。达上限后停止重建，cleanup-debt 仍在（release evidence 事件，kind=`cleanup/debt`，入 HARN-4 总表），工作区字节不变。supervisor = driver。cleanup receipt 恰三体：`temp_state`∈{absent, removed, out_of_bounds}；absent|removed → `succeeded`，out_of_bounds → `failed`；`exit_code` 恒 0，表示 request 已处理。worker 侧删除崩溃或其他条件不走 failed receipt，由 `expire_due`→timeout 重建。不引入新 exit_code。只改 request 行，**不改 effect、不改工作区语义**。重复 = 幂等零更新。timeout 只走 DB 时钟。gate 覆盖重复、失败、receipt 提交后杀 driver、越界。

**resume 分类是无 receipt 终态的唯一来源。** 有合法 succeeded receipt 则不分类。mutating 在 `started` 且无合法 succeeded receipt 时，终态只来自下面四支。**唯一** `started→failed` 是第 4 支。`failed(stale)` 仍只用于未 started 的漂移。IO 证据 = 本 effect 已执行 rename，或目标 inode 已换成该 temp。**「目标 ≠ expected」单独不构成 IO 证据。**path 集合基数恰 1（TOOL-1）。`expected` 见 EFF-5。

每 path 三分：

- **done**：观测 = 目标态；
- **pending**：观测 = `expected` ∧（temp 与 proposal 的 `new_sha256`/`new_mode` 可验证，或 temp 未用于 rename 且可从不可变 proposal payload 幂等重建）；
- **unexplained**：其余。

整 effect：

**symlink 前置臂**（优先，不进四支）：目标或任一父分量是 symlink。未 started → `failed(stale)`，零 rename，不设 degraded。已 started → `unknown`+degraded，零再 rename。

有序四支（IO 证据 = 本 effect 已 rename，或目标 inode 已换成该 temp；目标 ≠ expected 单独不是 IO 证据）：

1. 有 IO 证据 ∧ 观测 = 目标态 → 补 fsync 与验证。通过才 `succeeded`+`tool/result`，不重放。失败 → `unknown`+degraded，零再 rename。
2. 有 IO 证据 ∧ 观测 ≠ 目标态 → `unknown`+degraded，零再 rename。pending 臂 rename 后复验失败走这里，禁写 tool/result。
3. 无 IO 证据 ∧ 观测 = `expected` ∧ 全部 path 满足 pending ∧ 未 rename → 事务外重建或沿用 temp、fsync、rename、fsync 父目录、复验。复验输入 = `request_id` + 当前 `fencing_gen` + 复验全观测。SQL 谓词加「全观测 = 目标态」。不等 → 不写 tool/result，改走第②支。复验 0 行按三款先命中：1) `state=started` ∧ fencing 匹配 ∧ 全观测=目标态 → `succeeded`+`tool/result`（diff 取自 proposal）；2) `state=started` ∧ fencing 匹配 ∧ 观测≠目标态 → 第②支 `unknown`+degraded，不写 tool/result；3) `state≠started` → effect 0 行、不新建 request、**不进 resume 分类**。fencing 不匹配不走第 3 款，按 EFF-2：拒绝落库、旧 request 标 `superseded`、仅 started 时建当前代新 request。
4. **其余无 IO**（含观测 ≠ `expected`，以及观测 = `expected` 但 pending 不成立，以及无 IO 但观测已 = 目标态）→ `failed`+degraded，零 rename。这是唯一 mutating `started→failed`。成功支必须同时具备 IO 证据。

**不写 `failed(stale)`。** `failed(stale)` 只用于尚未 started 的基线漂移。删除「无 path 达目标态即 stale」。

**symlink 与父目录 symlink 同一分流**：提案构建与锁内复算对每个前缀分量 no-follow。目标或任一父分量是 symlink：尚未 started → `failed(stale)` 拒绝，零 rename，不 degraded；started 之后 → `unknown`+degraded，零再 rename。

**fsync 失败**：不依赖不可恢复的历史失败信息。恢复协议 = 目标态匹配后仍补做必要的 fsync 与验证，再定 `succeeded` 或 `unknown`。gate 覆盖「目标字节正确但父目录 fsync 报错」，含进程死后恢复。

**write/edit receipt 只收 `succeeded`**：全观测等于目标态 ∧ `exit_code=null` → 同事务 `succeeded` + `tool/result`（diff 取自 proposal，worker 的 diff **固定省略**；若仍提交且 `diff_digest` 与 proposal 不一致 → 拒绝落库、状态不变）。`status=failed` 拒绝落库，保持 `started`，走分类。claim/apply 拍由 SQL 交出不可变 payload 字节，driver 原样转发；改写即违反 INV-5。

检查：G3 write/edit 三缝 + cleanup gate；G1 正/负例（apply 前 symlink = failed(stale) 不 degraded；started 后 symlink = unknown+degraded；pending 重建 temp；分类与 receipt 互斥；read-only 不用全观测谓词）。

**V14-EFF-4 workspace 全序、排他 apply 锁与屏障**〔P0〕每个 workspace 有 `workspace_id`。**排他锁**：会话级 advisory 锁（`pg_try_advisory_lock`，**键 = `hashtextextended(workspace_id::text, 0)` 低 56 位 OR `(0x14<<56)`**。v13 不得占用高 8 位=`0x14` 的键。同连接同 key 的 lock 计数只许 0 或 1，已持有则禁再 try_lock。worker 崩溃时 supervisor 关闭持锁连接，锁自动释放；禁其他连接强制 unlock）；在 claim 阶段尝试取得，**拿不到 → 结束当前事务，effect 留 `planned`/`claimed`，下一拍再试**；取得后**生命周期跨 `claimed→started` 的 COMMIT，直至 apply 结束或会话死**；**持锁连接专属于该次 apply，IO 期间不归还连接池**；所有受控 writer（核心面 = write/edit）用同一把锁。exec 是否同锁见 v14.1，不在本冻结。**advisory 锁仅 mutating 与 **session_baseline 初始化**取得（read-only/provider 无锁）。持锁期间按 EFF-3 复算受影响路径基线，任一不匹配由调用点按 explainable 写一次终态，禁止 rename、禁止进入 started。**workspace_effect_seq**：每个 effect **至多分配一次**。分配点集合恰 = {claim 成功, 进入 degraded}，互斥；claim 成功后再进 degraded **复用原 seq，不二次分配**。未 degraded 的 claim 失败与 `failed(stale)` 不分配。reconcile/diff 与 resume 复用已有 seq。**horizon** = 比较开始时冻结的已提交 seq 快照。**session_baseline 是 workspace advisory lock 的合法持有者**（「锁仅 mutating」的显式例外）。初始化连接按 apply 同纪律持锁：锁内短事务先检查无 claimed/started mutating 且 `degraded_effect_id IS NULL`。不满足立刻 unlock，**不开始扫描**。满足才冻结 `W=max(workspace_effect_seq)`（无行则 0）并提交 → 扫描期间屏障拒绝该 workspace 的新 mutating claim → worker 事务外 no-follow 扫根下路径全集 → 激活条件 = 本连接持锁 ∧ `max(seq)=W` ∧ **无 claimed/started mutating** ∧ `degraded_effect_id IS NULL`。满足才写 snapshot + `workspace_seq_at_session_create=W` + 会话置可用 → unlock。不满足 → **立刻 unlock**（禁持锁等待），request 保持 `pending`，会话保持 `initializing`，旧 request 迟到成功不激活。`try_lock` 失败与锁丢失分开记。retry 有当前 request/generation CAS。snapshot 列出全部现存路径；未列出的合法路径规范解释为四元组 absent；无法观测 → baseline 失败，不伪装 absent。tree hash 只做同一性校验。命题 B 的重放全序 = `workspace_effect_seq` 升序，折叠函数只有 `expected`（EFF-5）。**workspace 屏障（只统计 mutating，含 degraded）**：`degraded_effect_id IS NOT NULL`，或存在未终态 `claimed` / `started` / `unknown` mutating 时，**不得 claim 新的 mutating**（只许恢复既有）。degraded 期间新 mutating **请求可创建，不可 claim**。lease reclaim 不绕过屏障。进入 `unknown` 的同事务 CAS 设置 `degraded_effect_id`（EFF-5）。**外部写入（声明式，两句合一）**：受控面内的检测点 = **入 degraded**（receipt 全观测验证与下一 effect 基线 explainable 判定）；**该检测点之外不给更强保证**（不承诺文件系统级防并发；点外写入不升级为可解释失败，也不承诺与不杀世界线一致）。advisory 锁只覆盖受控 writer。**expire_due（写死）**：仅 DB 时钟、无参数、幂等；扩展同一 `expire_due()`：probe request 到期 pending→timeout；cleanup request 到期 pending→timeout 且 retry 计数递增；reconcile token 到期 active→expired；baseline request 到期 pending→timeout，会话保持 initializing。均 DB 时钟 + CAS。迟到 receipt 拒绝。timeout 后按既有规则可重建。proposal 到期走 claim 时间行，`expire_due` 不改 proposal。requested 到期 → `expired`（不建 effect）；degraded 期间不终结其他 approved+planned；清除后到期才走时间行（effect `failed` + proposal `expired` + 释放名额）。检查：G1 gate（try-lock 不可得留态重试/屏障只统计 mutating/未终态 claimed 时禁 claim 新 mutating 的越序负例/reclaim 不绕屏障/seq 分配点恰二且 stale 不分配/horizon 冻结/degraded 负例/expire_due 四类 CAS（probe/cleanup/token/baseline））+ G3 命题 B 断言。

**V14-EFF-5 fold、degraded 单主与两阶段 reconcile**〔P0〕全文只有一个折叠函数，调用点不得另写第二套。reconcile/diff 仅进全流比较面，命题 A 永不纳入：

`expected(path, at_seq) = fold(会话初始 per-path 全观测, {成功 tool/result diff ∪ reconcile/diff | workspace_seq_at_session_create < s ≤ horizon ∧ (at_seq 已分配 → s < at_seq)})`

按 s 升序。**禁止用 `proposal.old_*` 当折叠基底。** `baseline_workspace_effect_seq` 只记录冻结当时的 horizon：冻结时 `old_*` 必须等于该 horizon 下的 `expected`；claim 时用**新 horizon 重算** `expected` 再比，不把旧 `old_*` 当成基底。增量缓存仅当缓存字节已等于绝对 `expected` 时，才允许从缓存继续折叠。回归：会话创建后已有成功 effect，再建 proposal，必须用新 horizon 重算。全观测耦合见 TOOL-2（U20）。

**fold 应用**：初始 map 无该 path = `{exists:0, file_type:absent, mode:null, sha256:null}`。按 s 升序，每条 diff 只改自己的 path。应用前 `old_*` 必须等于当前四元组，否则日志损坏、gate 失败。应用后取 `new_*`。`new_file_type=file` 时 payload 哈希必须 = `new_sha256`。dir 的 sha256=`null`、payload=`null`，mode=lstat 低 12 位。成功 `tool/result` 的 file_type 只许 `file|dir|absent`。probe body 可记 `symlink|other`。**清 degraded 的 reconcile/diff `new_*` 只许 `file|dir|absent`**。观测仍是 symlink/other → CAS 匹配失败，不写 reconcile/diff、不清 degraded、不写 `reconciled_at`。这是 CAS 函数内的独立分支：effect 行 0 更新；同事务失败 request（`reason=unsupported`）、失效 token、允许重新取 token。通用「0 行零更新」只用于 token/fencing 不匹配与迟到成功。路径变成 file/dir/absent 之前，新 probe 仍走此失败边。explainable 与命题 B 比较四元组。

**symlink 分流优先于**「非 explainable → degraded」：未 started = `failed(stale)`，零 rename，不 degraded；started 后 = `unknown`+degraded，零再 rename。

`explainable := 观测四元组 = expected(path, at_seq)`。谓词不写终态。**explainable 且 proposal `old_*` ≠ expected → `failed(stale)`，不 degraded，不发 tool/result**。该句只用于尚未 started 的基线漂移，不用于 resume 分类。非 explainable 的未 started 漂移 → `failed`+degraded（未 IO）。

reconcile/diff 的 `old_*` = 该 seq 的 `expected`，`new_*` = 受信观测；fold 到该 seq = observed。

**degraded 单主**：workspace.`degraded_effect_id` 从 NULL 起步。进入 degraded 的同事务 CAS：`SET degraded_effect_id = 本 effect_id WHERE degraded_effect_id IS NULL`。CAS 0 行 → 本 effect 不得进入 degraded、不得 claim。若该 effect 尚无 seq，同事务分配一次；已有 seq 则复用。mutating claim CAS 另加 `degraded_effect_id IS NULL`。

**degraded 唯一出口 = 两阶段 reconcile**（不是 effect 上的一步 CAS）：

1. **reconciliation request/claim 行**。选择谓词只认 `effect_id = degraded_effect_id`（不再按「本会话唯一 unknown 或 failed」扫描）。token、request、probe receipt、CAS **全部绑定该 effect**。approver 经 INV-1 第 2 类提交（不收 session_id / proposal_id / principal / now；principal 规则同 APPR-6）。
2. **approver SQL 原子取 token**（写入 reconcile observation request 行；单胜者）。approver 函数**只返回 `token_id` 标量**，不收 outcome。CAS 函数收 `request_id` + 可选 outcome。闭集只有 `succeeded` 与 `failed`。省略则 SQL 按全观测填默认。显式值必须属闭集。`unknown`、`failed(stale)`、`attempt_exhausted` 与其他字符串一律拒绝，且不更新任何行、不写 events。覆盖合法值时写 `reconcile/audit`。driver 原样传递 token。receipt 只带 `request_id`；CAS 用 request 反查 token。`token_id` 不入 digest。已有未过期 token → 后者失败、零 IO。
3. **调度已建 request**。取 token 的事务已经创建唯一 reconcile observation request，本步**禁止再 INSERT**。`next_beat` 返回已存 `request_id`。一 token 至多一 request；一 degraded effect 同时至多一个未过期 request。
4. **probe receipt 绑 token + fencing_gen + request_id**；不一致 → 拒绝落库、状态不变。
5. **SQL CAS** 写 `reconciled_outcome` + observed 全观测 + 不可变 reconcile/diff（`old_*`=`expected`，`new_*`=受信观测，seq 复用）+ `reconciled_at`：`WHERE effect_id = degraded_effect_id AND token 匹配 AND fencing 匹配`。0 行三款：token/fencing 不匹配或迟到成功 → 纯零更新；`file_type`∈{symlink, other} → unsupported 副作用；outcome 字面量出闭集 → 纯零更新、不写 events、token 保持。**无论 outcome，CAS 成功都清 `degraded_effect_id` 并写下 `reconciled_at`**，禁止以后再选中这条历史 failed。终态 = 本次 `reconciled_outcome`。observed 由受信 worker 读取，禁调用方提交哈希。
6. **判定顺序写死**：① token/fencing 校验；② 如显式提供 outcome，先校验闭集，非法值纯零更新（不写 events、token 保持、不动 request）；③ file_type 校验（`symlink|other` → unsupported：effect 0 更新，request 定为 failed、`reason=unsupported`，token 失效）；④ outcome 省略时才按 `io_performed` 填默认（true→`succeeded`，false→`failed`）；⑤ 成功 CAS。进入 degraded 的同一事务写 `io_performed`，默认函数只读该列。建议不由是否等于目标决定。交叉负例：unsupported file_type × 非法显式 outcome → request/token/effect/events 均不变（非法参数先拦）。

`failed(stale)` 与 `attempt_exhausted` 不设 `degraded_effect_id`，不可被 reconcile 选中。历史已清 degraded 的 failed 也不可再选。

**重复 / 超时 / 进程死亡（写死）**：

- 重复取 token：单胜者，败者零 IO、不启动第二 probe；
- token 超时：token 失效，effect 保持原态（`unknown` 或 `failed` 且 degraded），不写 outcome，允许重新取 token；
- 进程死亡且 probe receipt 未回：视同超时，新 token 持有者重跑 probe；
- 进程死亡但 receipt 已回且 token/fencing 仍匹配、CAS 尚未成功：恢复者**不得另开 probe**，只许把该 receipt 提交进 CAS；
- CAS 已成功后再提交：零更新（迟到）。

此后基线 = 该 per-path observed 全观测。后续 fold 用 reconcile/diff，不用调用方哈希。reconcile 留痕 events（先例目录 `v8/reconcile/`）。

**命题 B**：重放输入 = 成功 tool diff ∪ reconcile/diff，按 seq 升序（折叠基底见 EFF-4）。**未 reconcile 的 unknown 世界线不宣称命题 B**。reconcile SQL 成功后命题 B 恢复，折叠**含该 seq 的 reconcile/diff**；只排除 reconcile 前的 unknown 前缀。provider 行只引 EFF-6：不取锁、不分配 seq、**永不进 unknown**；其「新 judgment 世代」是**独立动作（新 judgment_id），非本条 reconcile**。

检查：G1 两阶段正/负例（非唯一拒绝、重复 token 零 IO、超时恢复、死亡后不双 probe、CAS 谓词、默认函数顺序与闭集）+ G3 窗 2（reconcile SQL 成功后命题 B，折叠含该 seq reconcile/diff）。

**V14-EFF-6 provider at-least-once 与错误码乘积表（完成闭集）**〔P0〕provider effect 出生边见 EFF-1（start_attempt 同事务插 `started`+attempt 1+`fencing_gen=1`；**无 reclaim**；attempt 2 不换 effect 行；第 3 次需求不插行 → `failed(attempt_exhausted)`，attempt 行数保持 2）。attempt 事件**不属** INV-4 与 INV-3-A 任何比较面（投影按 kind 丢弃，V14-HARN-4）。

**provider 完成 = INV-1 第 3 类 judgment 提交函数内的原子动作**（同一事务，缺一不可）：校验 attempt（`attempt_id` 非空绑定、`fencing_gen` 一致、attempt 未消耗）→ 写 judgment 或错误 judgment → 消耗 attempt → 按乘积表改 effect。**不是**第 4 类 tool receipt。未消费的 attempt 可 `started→started` 重派（同一 attempt、同一 fencing）；首个提交消费，其余零更新。**迟到提交零更新**（attempt 已消耗、effect 已终态、fencing 不一致、或已 `attempt_exhausted`）。

**错误码乘积表（写死，五码三行，均在上述同一事务内落地）**：

| 错误码 | judgment | attempt | effect |
|---|---|---|---|
| `ok` | 写成功 judgment | 消耗 | `succeeded` |
| `timeout` / `transport_error` | 不写成功 judgment | 消耗该 attempt | 保持 `started` |
| `content_invalid` / `budget_exceeded` | 写错误 judgment（这些错误码写入错误 judgment 的唯一边） | 消耗 | `failed` |

effect 已 `succeeded`/`failed` 时 `start_attempt` 幂等零更新。仅 `started` ∧ 当前 attempt 已消耗 ∧ 行数<2 才插入。行数=2 且都已消耗才 `attempt_exhausted`（`effect/terminal`，`terminal_reason=attempt_exhausted`，不写错误 judgment）。`content_invalid` / `budget_exceeded` 的 failed 终结边必须且只能由错误 judgment 产生。`attempt_exhausted` 是独立 `effect/terminal` 终结边，不写 judgment。禁第三支。消耗后禁重派；迟到 ok 零更新。

**INV-3 命题 A/B 等价仅适用于 FakeLLM 路径与已提交 judgment 的 provider 路径**；G4 kill gate 不得把 provider 未提交 judgment 窗口宣称为 A/B 等价。检查：G4 gate（提交函数原子性：校验→写 judgment→消耗 attempt→改 effect 同事务；迟到零更新；五码三行断言；attempt 上限；failed 的终结边只有错误 judgment 行；attempt 行数=2；第 3 次不插行；独立 judgment 世代断言）。

### 3.2 write/edit 口岸（G1）

**V14-TOOL-1**〔P0〕write/edit 是 mutating 口岸。schema 与提案都写明 `affected_paths` **基数恰为 1**；多路径 proposal **拒绝**，不建 effect。diff 编码底层仍允许多记录格式（TOOL-2），但核心产品入口不用。准入走 grant：命中 → 已 approved proposal + `planned`；未命中 → 拒绝，零 proposal 零 effect。**write = create-only**；**edit = replace-existing**，目标须存在且非 symlink，父分量也不得是 symlink（EFF-3）。检查：G1（准入两分支 + 多路径拒绝 + create-only + symlink/父分量拒绝）。

**V14-TOOL-2 diff 协议（单格式 + 规范编码终版）**〔P0〕diff 只有一种格式：每 path 记 `{old_exists, old_file_type, old_sha256, old_mode, new_exists, new_file_type, new_sha256, new_mode, payload 编码}`——payload 编码 = 文本 utf8 / 二进制 base64；覆盖创建（old_exists=false）、删除（new_exists=false）、二进制、symlink 拒绝策略。**禁止** old/new 成对与 unified diff 二选一的旧措辞。write 的 diff = old 全空（old_exists=false）。**字节语法（digest 权威，写死）**：diff_digest、全观测 body 与 payload_digest 的预映像都是 UTF-8 字节串（无 BOM），在送入 jsonb **之前**计算，**不用 `jsonb::text`**。sha256 落库与比较用小写十六进制 64 字符。

共用词法：记录分隔 = `0x0A`，每条记录以它结束（含最后一条），无 `0x0D`。字段分隔 = `0x1F`。字段内禁止裸 `0x1F` / `0x0A`。**NULL** = 四字节 `null`（`6e 75 6c 6c`），无引号。**空串** = 零长度字段（相邻分隔符）。二者不得互换。存在位 = 单字节 `0` 或 `1`。整数 = 十进制 ASCII、无前导零、无正号；零 = `0`；负数 exit_code 允许前导 `-`。**mode** = 八进制定宽 4 位、前导零（`0644`、`0755`），只编码权限低 12 位；缺失 = `null`，禁止用 `0000` 代替缺失；不定宽（`644`）必须拒绝。sha256 字段 = 小写十六进制 64 字符，缺失 = `null`。file_type 闭集 = `file | dir | absent | symlink | other`。成功目标只用前三个；`symlink|other` 只出现在观测 body。

路径 = 相对 workspace 根的原始字节，禁止绝对路径、禁止 `..`、禁止以 `/` 开头、禁止 NUL。排序键 = 原始字节 memcmp，**禁止** Unicode 码点序与 NFC/NFD。合法 UTF-8 路径写入字段时 = JSON 字符串（含引号；RFC 8259：`"` 与 `\` 及 U+0000–U+001F 转义；`/` 不转义；非 ASCII **原样 UTF-8**，不写 `\uXXXX`；控制字符优先 `\b \f \n \r \t`，其余 `\u00` + 两位小写十六进制，与 `json.dumps(s, ensure_ascii=False)` 的字符串字节一致）。非法 UTF-8 路径不得进 JSON 字符串，字段 = `b64:` + base64(原始字节)。

payload 标签：`utf8:` + JSON 字符串（合法 UTF-8 且不含 NUL；空内容 = `utf8:""`）；`b64:` + base64（含 NUL、非法 UTF-8、或声明为二进制）。删除（`new_exists=0`）时 payload = `null`，且 new_sha256 / new_mode = `null`。base64 = RFC 4648 标准字母表 `A–Z a–z 0–9 + /`，`=` 填充到 4 的倍数，无换行，禁止 URL-safe。

**diff 记录字段序**（一条 path 一行，按路径原始字节升序）：`path, old_exists, old_file_type, old_sha256, old_mode, new_exists, new_file_type, new_sha256, new_mode, payload`。**exists/file_type 耦合**：`exists=0` ⟺ `file_type=absent` ∧ mode/sha256=`null`；成功目标的 `exists=1` ⟺ `file_type∈{file,dir}`。观测可另编码 `symlink|other`（`exists=1`），但不得作为 succeeded 目标，也不等于无法观测。**全观测记录字段序**：`path, exists, file_type, mode, sha256`。**payload_digest 预映像**（单行）：`kind, effect_id, attempt_id, request_id, fencing_gen, status, exit_code, body_digest`。mutating tool：`attempt_id` 与 `request_id` 均为 `null`（不是空串），body_digest = observation_digest（全观测记录字节的 sha256）。worker 提交的 diff 只做与 proposal 的一致性校验，不一致则拒绝落库。read-only tool：`attempt_id` 非空，`request_id` = `null`。probe：`request_id` 非空；preflight 的 `effect_id` 允许 `null`；body_digest = 全观测记录字节的 sha256 的 64 hex。provider 完成预映像 kind 字面 = `judgment`，`attempt_id` 非空，不走 tool receipt。stdout/stderr **不进** digest 预映像；事件规范编码里空 stdout = 零长度字段，缺失 stdout = `null`。

**黄金向量集**（字节即权威。gate **先断言连接后预映像 hex，再断言 sha256**。下表给字段；hex 在表后代码块。不得另写第二套语法）。固定替身：effect `00000000-0000-4000-8000-000000000001`、attempt `…0002`、request `…0003`；body 占位 = 空串 sha256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`。

| id | 覆盖 | sha256 |
|---|---|---|
| V-null | 双侧不存在，哈希/mode/payload 全 `null` | `0f68968c21f6e3b28699bd86d7f74c632176fb24efbe096b1fd8fc426f63f905` |
| V-empty | 创建空文件，mode `0644`，payload `utf8:""` | `8a3997e8a205d20c6488ae8532fe5d4811769a4c6c5780efc9f1da5f80b74b2a` |
| V-uni | 路径与文本均为 `文`（UTF-8 `e6 96 87`，不 `\u` 转义），mode `0644` | `bbe881c317b4b803a2902f6144fa8d2dde26d5e6f202468e36b9e43842975c09` |
| V-quote | 文本字节 `5c 22`（反斜杠、引号）；payload 字段十六进制 = `757466383a225c5c5c2222` | `d738bac029b4e8aae1064e96247b790b0136e1fbb5ee4c02e27e7623adaffd0e` |
| V-nul | payload 含 `00` → `b64:AA==`，不得 `utf8:` | `da2a4ab4061657dd57a382a77cad0c6995c07cb241f92b7566b7229f3b2e8dbf` |
| V-bin | 非法 UTF-8 `ff` → `b64:/w==` | `4ae55c4b611f85983397c84fad28f42055d6bf2c680ddfa24ec587f7f98227c2` |
| V-del | 删除（old 为字节 `x`，new_* 与 payload = `null`） | `a9e0ea5801dad7fa650274a5adf6e90130d639a12592c15fda152156517a287a` |
| V-multi | 输入序 `b` 然后 `a`；规范字节必须 `a` 行在前，`b` 行 mode `0755` | `c44925dad6dc9429cb7e1c856b08d0f11e8c87d5af16d7e9cdb9fa37497765b3` |
| V-mode | mode `0755` 合法；`644` 拒绝 | `a9369501b26a63b47e8963ffb3417e77708338ac2657e2fcf910a3029b215bb5` |
| V-stdout | 空 stdout（零长度字段）后接 null 字段，预映像 hex `1f6e756c6c0a`；空串 ≠ `null` | `545538c936e17a843ff37671afe8d5d7cb7a8c4574c2443c60adc4d45635ab66` |
| V-rcpt-tool | mutating tool：`attempt_id` 与 `request_id` 均为 `null`；`fencing_gen=1` 是语法替身，不是可达代际 | `099c357c9b4e04a22ec9e39ed5096fdd3c03718d08c8c3c2362cb5842a08e808` |
| V-rcpt-baseline | kind=`session_baseline`；effect_id=null；attempt_id=null；request 非空；fencing_gen=1；status=succeeded；exit_code=0；body=空 snapshot | `9eb16397959971efa55d8db7dd46ad79ea0e30c3005aa56f198d0da786847ab0` |
| V-rcpt-cleanup-absent | kind=`cleanup`；effect 非空；attempt_id=null；request 非空；fencing_gen=2；status=succeeded；exit_code=0；body=`absent`+0x0A | `7a9112c895f39420b152e169a25deb630d7597faed05d988dbb5d36837d1819a` |
| V-rcpt-cleanup-removed | kind=`cleanup`；effect 非空；attempt_id=null；request 非空；fencing_gen=2；status=succeeded；exit_code=0；body=`removed`+0x0A | `84b80c344fa74ddf2fe608e756ffa19966e87c37a371e272c5c42f972bc74425` |
| V-rcpt-cleanup-oob | kind=`cleanup`；effect 非空；attempt_id=null；request 非空；fencing_gen=2；status=failed；exit_code=0；body=`out_of_bounds`+0x0A | `fcc2a370d038e9d8471ad4f8a830dee7819b643aeceebf8f11aedff733931fa7` |
| V-rcpt-ro | read-only tool：`attempt_id` 非空，`request_id` = `null`，exit_code `0` | `dc882981d9a45f57f75244fb36ac2c03043340a0f0f34cce08505c000bcf9da5` |
| V-rcpt-pre | preflight_probe：`effect_id` = `null`，`request_id` 非空 | `e58e1063246a55c09d8ba378eedb1bc0ade69c038ca8672cbf3c24e5612027ea` |
| V-rcpt-claim | claim_probe：`effect_id` 与 `request_id` 均非空，`attempt_id` = `null` | `9b7847e05a291bdf8f42ad9d16182b1233b5622b205fe894d1d73d7a589bdd03` |
| V-rcpt-resume | resume_probe：同上 nullable | `3caf9703cf07f53b13c8b50afe5c03dbe530bdd1df7a438d63672e10b10369bd` |
| V-rcpt-recon | reconcile_probe：同上 nullable | `fe7faa71ae19f4c935f5ac5d2bfced6f9ec7e2816a02df540f5695ab6387a148` |
| V-rcpt-prov | provider 完成 kind=`judgment`：`attempt_id` 非空，`request_id` = `null` | `974fef1368e6d444aa15c656adac8b5565c50ac8691d0d1b01f802d00deef70a` |

预映像 hex（连接后字节，含结尾 `0a`）：

```
V-null 2261221f301f616273656e741f6e756c6c1f6e756c6c1f301f616273656e741f6e756c6c1f6e756c6c1f6e756c6c0a
V-empty 2261221f301f616273656e741f6e756c6c1f6e756c6c1f311f66696c651f653362306334343239386663316331343961666266346338393936666239323432376165343165343634396239333463613439353939316237383532623835351f303634341f757466383a22220a
V-uni 22e69687221f301f616273656e741f6e756c6c1f6e756c6c1f311f66696c651f333637376566373762313537346431363264376332646336366463633238616436343463366561643733336332366562393531333233333535376665396162381f303634341f757466383a22e69687220a
V-quote 2261221f301f616273656e741f6e756c6c1f6e756c6c1f311f66696c651f316164303730626232383562633066643736323532323538346365353032656661323437343964363733343835373333326139323838303463323930376161621f303634341f757466383a225c5c5c22220a
V-nul 2261221f301f616273656e741f6e756c6c1f6e756c6c1f311f66696c651f366533343062396366666233376139383963613534346536626237383061326337383930316433666233333733383736383531316133303631376166613031641f303634341f6236343a41413d3d0a
V-bin 2261221f301f616273656e741f6e756c6c1f6e756c6c1f311f66696c651f613831303061653661613139343064306236363362623331636434363631343265626264626435313837313331623932643933383138393837383332656238391f303634341f6236343a2f773d3d0a
V-del 2261221f311f66696c651f326437313136343262373236623034343031363237636139666261633332663563383533306662313930336363346462303232353837313739323161343838311f303634341f301f616273656e741f6e756c6c1f6e756c6c1f6e756c6c0a
V-multi 2261221f301f616273656e741f6e756c6c1f6e756c6c1f311f66696c651f653362306334343239386663316331343961666266346338393936666239323432376165343165343634396239333463613439353939316237383532623835351f303634341f757466383a22220a2262221f301f616273656e741f6e756c6c1f6e756c6c1f311f66696c651f653362306334343239386663316331343961666266346338393936666239323432376165343165343634396239333463613439353939316237383532623835351f303735351f757466383a22220a
V-mode 2261221f301f616273656e741f6e756c6c1f6e756c6c1f311f66696c651f653362306334343239386663316331343961666266346338393936666239323432376165343165343634396239333463613439353939316237383532623835351f303735351f757466383a22220a
V-stdout 1f6e756c6c0a
V-rcpt-tool 746f6f6c1f30303030303030302d303030302d343030302d383030302d3030303030303030303030311f6e756c6c1f6e756c6c1f311f7375636365656465641f6e756c6c1f653362306334343239386663316331343961666266346338393936666239323432376165343165343634396239333463613439353939316237383532623835350a
V-rcpt-ro 746f6f6c1f30303030303030302d303030302d343030302d383030302d3030303030303030303030311f30303030303030302d303030302d343030302d383030302d3030303030303030303030321f6e756c6c1f311f7375636365656465641f301f653362306334343239386663316331343961666266346338393936666239323432376165343165343634396239333463613439353939316237383532623835350a
V-rcpt-pre 707265666c696768745f70726f62651f6e756c6c1f6e756c6c1f30303030303030302d303030302d343030302d383030302d3030303030303030303030331f311f7375636365656465641f6e756c6c1f653362306334343239386663316331343961666266346338393936666239323432376165343165343634396239333463613439353939316237383532623835350a
V-rcpt-claim 636c61696d5f70726f62651f30303030303030302d303030302d343030302d383030302d3030303030303030303030311f6e756c6c1f30303030303030302d303030302d343030302d383030302d3030303030303030303030331f311f7375636365656465641f6e756c6c1f653362306334343239386663316331343961666266346338393936666239323432376165343165343634396239333463613439353939316237383532623835350a
V-rcpt-resume 726573756d655f70726f62651f30303030303030302d303030302d343030302d383030302d3030303030303030303030311f6e756c6c1f30303030303030302d303030302d343030302d383030302d3030303030303030303030331f311f7375636365656465641f6e756c6c1f653362306334343239386663316331343961666266346338393936666239323432376165343165343634396239333463613439353939316237383532623835350a
V-rcpt-recon 7265636f6e63696c655f70726f62651f30303030303030302d303030302d343030302d383030302d3030303030303030303030311f6e756c6c1f30303030303030302d303030302d343030302d383030302d3030303030303030303030331f311f7375636365656465641f6e756c6c1f653362306334343239386663316331343961666266346338393936666239323432376165343165343634396239333463613439353939316237383532623835350a
V-rcpt-prov 6a7564676d656e741f30303030303030302d303030302d343030302d383030302d3030303030303030303030311f30303030303030302d303030302d343030302d383030302d3030303030303030303030321f6e756c6c1f311f7375636365656465641f6e756c6c1f653362306334343239386663316331343961666266346338393936666239323432376165343165343634396239333463613439353939316237383532623835350a
V-rcpt-baseline 73657373696f6e5f626173656c696e651f6e756c6c1f6e756c6c1f30303030303030302d303030302d343030302d383030302d3030303030303030303030331f311f7375636365656465641f301f653362306334343239386663316331343961666266346338393936666239323432376165343165343634396239333463613439353939316237383532623835350a
V-rcpt-cleanup-absent 636c65616e75701f30303030303030302d303030302d343030302d383030302d3030303030303030303030311f6e756c6c1f30303030303030302d303030302d343030302d383030302d3030303030303030303030331f321f7375636365656465641f301f373932356433653961393631336130393365356562343035346233326161333964653931306432623033626137653830343663336234353530623864653165340a
V-rcpt-cleanup-removed 636c65616e75701f30303030303030302d303030302d343030302d383030302d3030303030303030303030311f6e756c6c1f30303030303030302d303030302d343030302d383030302d3030303030303030303030331f321f7375636365656465641f301f366239353734336637333339653061666631366331643162396634353337313166666364633366656439623637383761663236346639363031633465323936310a
V-rcpt-cleanup-oob 636c65616e75701f30303030303030302d303030302d343030302d383030302d3030303030303030303030311f6e756c6c1f30303030303030302d303030302d343030302d383030302d3030303030303030303030331f321f6661696c65641f301f666132633034663833623565353335386362346163346164323666303663333735353661646535653564343637616166643033306436323865663330373162630a
```

diff 是 events 流的一部分（落 `tool/result` 载荷），供审批渲染与 `expected` 重放。检查：G1 gate 先断言上列 hex，再断言 sha256；mode 不定宽拒绝；空 stdout ≠ null。

**V14-TOOL-3**〔P0〕write/edit 执行拆三步：① **提案构建（三段式）**：短事务登记只读 lease **并创建不可变 preflight observation request** 后提交 → **事务外** worker 读文件并提交 `preflight_probe`（绑定 `request_id`）→ 新事务写 proposal 释放 lease（**文件 IO 永不在打开的 DB 事务内**，v8 不变量 4；preflight read 不属 effect IO，EFF-2）；② **等待（仅 requested 才存在）**：`await_approval` 仅存在于 exec mutating 的 requested proposal（exec mutating 人批，TOOL-6）；write/edit 无等待相（grant 命中即 approved 直入 claim）；等待期游标停 `await_approval`，不持任何 claim（V14-APPR-4）；③ **claim/apply**（取 workspace 排他锁（EFF-4）→ pre-claim `claim_probe` → claim effect → 锁内另建 claim_probe 复算（EFF-3）→ 原子写 → complete）。检查：G1 gate 三步各断言 claim 生命周期、preflight/claim_probe 请求先于 IO、三段构建顺序。

### 3.3 审批协议（V14-APPR，G1 交付；exec 人批不在本核心面）

**V14-APPR-1**〔P0〕proposal 不可变、一次构建。**核心摘要只冻结 write/edit**：合同版本、generation、工具名、完整参数、cwd、受控环境标识、冻结 horizon 下的 expected、规范化 diff、expires_at、可空 `grant_id`（比较面按 HARN-4 重算）。exec 不得复用此摘要或 grant 路径（摘要在 v14.1）。`requested`/approve/deny 保留 schema，无核心产品入口，G1 不测。检查：G1 gate 摘要双型完备性断言。

**V14-APPR-2 批准与消费（谓词定位 + 单次消费 + 竞争审计）**〔P0〕批准只批摘要（哈希锚定）。**批准输入禁止携带代理键字面量**（proposal_id、session_id 等）：approve/deny/expire/reconcile **不收 session_id / proposal_id / principal / now**，目标用谓词选（如「本会话唯一 requested proposal」，会话来自**认证连接绑定**），命中非唯一即拒绝。**条件更新写死**：approve/deny/expire 用 `WHERE state=requested` 条件更新，胜负各写一条 `approval/audit`（`payload.reason` ∈ win/loss）。消费：`planned→claimed` 与 `proposal approved→consumed` 同事务单次消费（EFF-1 后置条件表）；执行 claim 时 CAS 重验（摘要哈希一致、状态、未过期、workspace 基线仍匹配、grant 未撤销未过期（APPR-5）），任一不符即按 EFF-1 后置条件表处置并留痕。检查：G1（谓词定位非唯一负例、摘要篡改、claim CAS 重验；requested 动态审计移 v14.1）。

**V14-APPR-3 effective_now（DB 时钟；test-only 注入）**〔P0〕生产 approve/deny/expire/reconcile **不接受调用方 now、不读调用方可写会话变量**；effective_now 来自 DB 时钟。仅**测试专用角色**经隔离 test-only 入口注入 now。所有 CAS 用同一 effective_now 在同事务检查 `expires_at`。检查：G1 gate（生产入口无 now 参数 source 断言 + test-only 注入正例 + 共享 CAS 时钟断言）。

**V14-APPR-4 等待与串行（单名额在请求创建时执法）**〔P0〕proposal 状态机：**`approved` 是显式非终态**。出边：`requested → approved | denied | expired`；`approved → consumed`（与 effect claim 同事务）；`approved → expired`（claim 谓词失败/到期时，EFF-1 后置条件表；expired 为过期终态**唯一**落点）。**终态闭集 = `denied | expired | consumed`**（approved 不是终态，不得写成三择终态）。超时判定用 APPR-3 的 effective_now（expire_due 见 EFF-4）。等待期游标停 `await_approval`：不持 claim、不占 beat 前进位；批准后重新走 V14-EFF claim。**mutating 单名额执法时点 = 请求创建时**，执法句以三条件为准：已存在 requested proposal、未消费 approved proposal、或未终态 mutating effect **且其 effect_id ≠ 当前 `degraded_effect_id`**。degraded 期间至多一个排队 approved+planned。claim 仍靠屏障。创建路径对同一 workspace 用 `pg_try_advisory_xact_lock`，键 = `hashtextextended(workspace_id::text, 0)` 低 56 位 OR `(0x15<<56)`。不得复用 `0x14`。v13 不得占用高 8 位=`0x15` 的键。三条件检查与插入都在事务级锁内，锁随 COMMIT 释放，函数体内不调 unlock。失败不插入、不留锁。apply 与 session_baseline 继续只用 `0x14` 会话级锁，跨 COMMIT。事务级 `0x15` 不算进该集合。同 workspace 至多一个 requested/approved proposal，且至多一个 id ≠ `degraded_effect_id` 的未终态 mutating。deny/过期/失败路径**释放名额**。检查：G1（创建三条件、名额释放、approved 非终态）。requested 等待动态移 v14.1。

**V14-APPR-5 grant 字段全集与命中规则（终版）**〔P0〕grant 行字段冻结：`grant_id / granting_principal / session_id / workspace_id / tool_set / argument_schema / cwd 根 / contract_version / generation / issued_at / expires_at / revoked_at`。**grant 行除 `revoked_at` 空→非空外禁 UPDATE**。**核心面 grant 不覆盖 exec**。mutating exec 的拒签与 requested 人批见 v14.1。核心面 write/edit 未命中 grant = 准入拒绝，零 proposal。**grant 命中 = 请求创建事务内的内部动作**（非独立入口）：命中即在同事务生成不可变 proposal 并由 SQL 转 `approved`（principal 记录 = granting_principal），EXECUTE 权限对 harness 与 service role 一律 REVOKE；每次命中仍单次消费（APPR-2）；命中已 approved 的请求直入 claim（无等待相，TOOL-3）。**命中合取（写死）**：工具名 ∈ tool_set ∧ 每受影响相对路径匹配 glob ∧ cwd 在 grant 根下 ∧ workspace_id/session_id/contract_version/generation 相等 ∧ 未撤销未过期 ∧ 非路径标量过 argument_schema；**正文/diff/哈希不参与比较**。**两检查点（写死）**：① 只覆盖 `planned→claimed` 的 CAS（后置条件表 grant 行：proposal `expired`、不分配 seq、零 IO）。已 consumed 且仍 claimed 的撤权走 EFF-1 转移格第②行（proposal 保持 consumed、seq 保留）；② **receipt 接受时见撤销 → 不回滚已 started 的 IO**，终态按 receipt/EFF-5。模式闭集 = 工具名 + 相对路径 glob。签发/撤销/越界负例进 `test_approval`。检查：G1 gate（字段完备/签发/撤销/越界/核心面不测 exec 拒签/命中合取逐项/内部动作 + REVOKE 断言/两检查点分支/命中直入 claim/grant 行禁 UPDATE 除 revoked_at）。

**V14-APPR-6 principal 与签发封死（DB 认证，fail closed）**〔P0〕审批/签发/撤销函数**不接受 principal 参数**（issue_grant/revoke_grant 亦不收 session_id/now/proposal_id；`granting_principal` 取当前认证 principal）。**权限封死（写死）**：`issue_grant / revoke_grant / approve / deny / expire / reconcile` 全部 **REVOKE FROM PUBLIC** + 从 harness 与 service role REVOKE，**EXECUTE 仅授认证 approver 角色**。生产路径须有与实际 approver 一一对应的 **DB 认证 principal**；共享 service role 不得执行审批；无法映射即 fail closed（拒绝并留痕）。**会话绑定 = 认证时写连接不可变属性**；审批/签发不读调用方可写 GUC。Chainlit 部署的身份映射 = 受信连接 / 角色属性。principal 写 events。检查：G1 gate（principal 映射断言 + REVOKE FROM PUBLIC 断言 + service role 拒绝 + 无法映射 fail-closed 负例 + 签发参数面断言）。

**V14-APPR-7 测试纪律**〔P0〕禁止直改审批/effect 状态表。核心 G1 只测 enum/schema 兼容、权限封死、write/edit grant 路径与 reconcile。approve/deny 的竞争动态、requested 状态机动态路径移到 v14.1，核心不测。时钟注入仅经 test-only 入口。

### 3.4 glob/grep（G1 出生分支；exec 不在本核心面）

**V14-TOOL-4**〔移出〕exec 闭集命令执行器、动词目录、mutating/read-only exec、exec×write 并发，整体移到 `docs/designs/v14.1-exec.md`（种子 V141-SEED-TOOL-4）。本核心面**无** exec 实现义务，**无** `{run-test, build}` 冻结目录。任意 shell 仍然不做（§9）。原句保留在 v14.1 骨架，避免六轮裁定丢失。


**V14-TOOL-5**〔P0〕glob/grep 只读口岸。`V14_RO_OUTPUT_CAP = 65536`。错误码只由 `exit_code` 区分，禁用 stdout 文本：`ok`→succeeded/`0`；`output_limit`→failed/`1`；`bad_input`→failed/`2`；`io_error`：消耗 attempt、保持 started，`exit_code=3` 只是 receipt 编码，不是 effect 终态。`output_limit`/`bad_input` 不产独立事件 kind，UI 由 judgment 转述。超限不截断成成功。attempt 2 的 fencing 继承 effect 当前代，不另升。调度走 EFF-1 五步优先级。检查：G1 五步序 + exit_code 映射。

**V14-TOOL-6 准入合一与四路径（产品语义裁决）**〔P0〕**单一准入路径**：

- **exec mutating**：不在本核心面。requested 人批、拒签谓词、动词目录见 v14.1-exec（V141-SEED-ADMIT / V141-SEED-R11）。核心面不建 exec proposal。
- **write/edit**：命中 grant → 建已 `approved` proposal + 插 `planned` effect（同事务，直入 claim）；**未命中 grant → 准入拒绝，零 proposal 零 effect（无逐次人批）**。

核心面路径：① **默认拒** = write/edit 未命中 grant（准入拒绝不建行）；② **grant 命中** = 已 approved proposal + planned effect，直入 claim。人批的 requested / denied / expired 路径属于 exec，见 v14.1；状态机仍保留，G1 夹具不覆盖 exec requested。检查：G1 gate（准入两分支 + 工作区字节）。

## 4. harness 与载体（G3/G4 冻结面）

### 4.1 beat driver

**V14-HARN-1**〔P0〕beat driver 从既有 ring 实现提炼为可复用模块（`v14/harness/`）。提炼源（已核实）：`v13/pi_ports/test_pi_ports.py:678` `run_ring(planes)`（多在场平面同会话、mock judgment、events 计数）与 `v13/read_tools/test_read_tools.py:980` `run_ring()`；拍结构锚点 = `v13/pi_parity/test_pi_parity.py:66` `GOLDEN_SEQUENCE`。提炼不得改动 v13 既有文件（复制提炼，非原地重构）。检查：G3 gate + source gate（v13 零 diff）。

> 注：父循环轮 1 目标原文写作「test_pi_parity.run_ring」——经核实 `run_ring` 不定义于 pi_parity，实际定义于上述两处；pi_parity 提供的是 normalized schema-v2 trace 与拍结构。本规范按核实结果表述。

**V14-HARN-2**〔P0〕driver 语义：循环 = 「取 beat → 执行该拍的外部动作（若有）→ 落 events → advance」；终态判定在 SQL 面；外部动作执行前后守 V14-EFF 纪律；worker/provider 以子进程拉起（INV-5 能力协议）。进程可随时被杀（INV-3）；可选 pg_cron 心跳拉起 driver 属于部署面，不改变语义（beat 推进幂等）。检查：G3 杀进程续跑 gate。

### 4.2 事件流与 LISTEN/NOTIFY（通道 v14_wake，终版算法）

**V14-HARN-3**〔P0〕事件流权威 = events 表（只追加）。通知通道 **`v14_wake`**：`pg_notify` 由**插入 event 的同事务**发出（SQL 侧），**harness 禁止自行 NOTIFY**。观察者算法（写死）：

1. 在**独立 autocommit 连接**上执行 `LISTEN v14_wake` 并 commit（完成订阅）；
2. 从 `last_seq`（初始为 0/游标起点）做**初始补读**；
3. 此后通知**仅作唤醒**：醒来即重查 `(session_id, seq) > last_seq` 的 events 按 seq 升序处理；
4. 渲染按 `(session_id, seq)` **幂等**；**成功处理才推进 last_seq**（last_seq 只前进）；
5. 通知丢失/合并不产生遗漏——回表是唯一事实源。

payload 闭集 = `{session_id, seq 高水位}`，不携带业务事实。**负例（gate 必测）**：① 通知合并（多条 NOTIFY 一次醒来，回表读全）；② 断线插入（重连后从 last_seq 回补不漏不重）；③ 查询-订阅间隙（LISTEN commit 前产生的事件由初始补读覆盖）；④ 重连后无后续通知（静默期靠 last_seq 状态判定完备性，不依赖新通知）。检查：G3 `test_listen.py`（含四负例）。

### 4.3 双壳等价与命题 A：比较面与投影算法（库内 canonical，写死）

**V14-HARN-4**〔P0〕两个比较面共用一套投影算法：

1. **同输入协议**：两壳各自**新会话、新工作区**，喂同输入序列；输入含批准——批准作为 SQL 命令序列经 **govern 入口**提交，无旁路（V14-APPR-7）；**双壳使用同一测试 principal**；**整场景共用同一个 test-only `effective_now`**；两 principal 越权负例另行单测（不进等价 gate）。不依赖 exec 输出。
2. **同入口**：两壳驱动**同一组 SQL 入口**（submit / approve / …）；seq 由 SQL 分配，客户端不造序。
3. **canonical 投影（库内唯一函数）**：投影函数在**库内**实现（递归 jsonb 遍历），禁止客户端拼串。**遍历序冻结 = jsonb 自身键序、数组从左到右**。归一规则：
   - **代理键 allowlist（写死，十个前缀、十一个键名）**：`session_id→$s`、`event_id→$ev`、`effect_id→$ef`、`judgment_id→$j`、`proposal_id→$p`、`attempt_id→$at`、`grant_id→$g`、`workspace_id→$w`、`request_id→$rq`、`token_id→$tk`、`degraded_effect_id→$ef` 及递归出现的同值——替换两遍：先收集 allowlist 值，再替换全部同值出现。同值同替换、跨行一致。`degraded_effect_id` 与 `effect_id` 同值必须得到同一个 `$efN`。
   - **volatile metadata 键表（与时间分开，写死）**：`ts / wall_time / created_at / pid / lsn / expires_at / started_at / finished_at / duration_ms / elapsed_ms / lease_until / lease_owner / issued_at / revoked_at / effective_now / fencing_gen` → 类型占位符（`fencing_gen` 在杀/不杀世界线可分叉，比较面用占位符；单调与 CAS 由独立 fencing gate 断言）；
   - temp 根前缀 → `$tmp`（字面量，非代理键），在 `$ws` 替换之前做。然后 **workspace 根 → `$ws`**。两替换后仍残留 workspace 外绝对路径才 gate 失败。事件内文件路径一律以相对根形式存储。
   - **attempt 事件按 kind 丢弃**（不属任何比较面，EFF-6）；`workspace_effect_seq` 每 workspace 从 1 单调、同构操作两壳同值 → **原样入比较面（不替换）**；
   - **派生字段表（对 A 与 INV-4 两比较面都生效，写死）**：含代理 ID 的哈希必须二择一，未列入者不得入任一比较面，新增须 bump。`payload_digest` = **排除 + 独立 digest gate 验证**（G1，含 TOOL-2 黄金向量）。proposal 摘要哈希与 approval 摘要哈希（含 `grant_id` 等代理 ID）= **canonicalize 输入重算**：代理键替换 + volatile 占位 + `$ws` 替换之后再哈希，不比较原始哈希字节。`diff_digest` 预映像不含代理 ID（TOOL-2）→ 原样入比较面；若实现期发现预映像含代理 ID，必须改为 canonicalize 重算，不得静默排除；
   - **封闭性执法（字符串模式，写死）**：epoch 只匹配：整个标量是 RFC3339 文本，或键名匹配 `*_at` / `*_ms` / `*_until` / `*_pid` / `*_lsn`，或十进制整数 ≥ 1000000000。**原样保留**：`workspace_effect_seq`、`exit_code`、`mode`、judgment usage 的 token 整数、status 枚举。timestamptz 型标量、绝对路径、未识别 uuid → **gate 失败**，新增类别必须 bump 本规范（偏差台账无权松动）。**uuid 规则仅作用于整个 jsonb 标量值 = uuid 形**（对 stdout/stderr/diff 等文本载荷不做子串扫描）；**字符串先做 `$ws` 前缀替换，替换后仍残留绝对路径才失败**；digest 规范化用显式保序文本编码（V14-TOOL-2），不经 jsonb::text；
   - **比较（写死）**：每流按 `(session_id, seq)` **ORDER BY seq** 后投影 `::text` 逐字节相等（逐行，服务端执行）。
4. **两个比较面**：**INV-4 双壳等价**用 §4.3 全流。**INV-3 命题 A**用下表允许行。**字面 kind 总表（〔P0〕，表外 kind 禁止写 events；状态谓词只读事件不可变 payload；compact 触发器 = 已提交事件的纯函数）**：

| kind | 状态谓词 | A | 全流 |
|---|---|---|---|
| `user/submit` | 已提交 | 入 | 入 |
| `judgment` | judgment 行已落（含错误 judgment） | 入 | 入 |
| `proposal` | `consumed` / `denied` / `expired` | 入 | 入 |
| `proposal` | `requested` / `approved` | 不入 | 入 |
| `tool/result` | `succeeded` | 入 | 入 |
| `effect/terminal` | 终态，`terminal_reason=attempt_exhausted` | 入 | 入 |
| `reconcile/diff` | CAS 成功。仅进全流比较面，命题 A 永不纳入 | 不入 | 入 |
| `reconcile/audit` | token 签发 / 超时 / CAS 零更新 / approver 覆盖 outcome | 不入 | 入 |
| `summary` | compact 已落 | 入 | 入 |
| `beat` | 任意 | 不入 | 入 |
| `grant` | 任意 | 不入 | 入 |
| `preflight_probe` / `claim_probe` / `resume_probe` / `reconcile_probe` | request 已终态 | 不入 | 入 |
| `session_baseline` | request 已终态 | 不入 | 入 |
| `cleanup` | `pending` / `succeeded` / `failed` / `timeout` | 不入 | 入 |
| `cleanup/debt` | 达重试上限仍未清掉 | 不入 | 入 |
| `claim/audit` | `payload.reason` ∈ {time, grant, symlink, baseline}；仅 time/grant/symlink/baseline 四短路行每次恰一条；屏障 0 行不写 | 不入 | 入 |
| `approval/audit` | `payload.reason` ∈ win/loss | 不入 | 入 |
| `attempt` | 任意 | 不入 | 不入 |
| `lease/reclaim` | 任意 | 不入 | 不入 |

事件表的 outer `seq` **只用于 ORDER BY，不写入投影文本**。`workspace_effect_seq` 仍原样入比较面。摘要重算输入 = 代理键替换 + volatile 占位 + `$ws` 替换，**然后再哈希**。批准输入禁携带代理键字面量（V14-APPR-2）。

检查：G3 `test_dual_shell.py`（全流）+ `test_resume.py` 窗 1（A 子流 + tool/result 规范 diff 与 workspace_effect_seq 相同断言）。

**V14-HARN-5**〔P0〕psql demo 收窄为 **submit/observe demo**：一条纯 psql 路径演示「SQL 命令提交输入 + `LISTEN v14_wake` 观察事件流」，证明载体无关性；不宣称「全程 psql 驱动 agent 完成 mutating 任务」。demo 脚本入库（`v14/harness/`）。检查：G3 gate（psql 执行 demo 退出 0 + 事件断言）。

**V14-HARN-6**〔P0〕harness 薄度执法（INV-1/INV-5 的 gate 细则）：per-file 决策点计数（INV-5 上限表）；import 前缀黑名单（INV-5 六前缀）；worker 与 provider 能力协议断言（INV-5）。检查：G3 `test_thin.py`；G4 provider 能力 gate。

### 4.4 真 provider、多轮与 compaction（G4）

**V14-HARN-7**〔P0〕DeepSeek 判断面产品化：provider 调用放 **`v14/provider/` 独立进程**——可 import litellm，禁开 DB 连接、禁 beat 循环、禁写工作区（INV-5 能力闭集）；回答由 driver 按 INV-1 第 3 类提交；与 FakeLLM 实现同一 judgment 合同（同参数/同落库/同错误闭集）；调用经 V14-EFF-6 attempt 记账与**错误码乘积表**。**判断错误码闭集（写死）**：`ok | timeout | transport_error | content_invalid | budget_exceeded`——FakeLLM 与 provider 同表映射，**不得各自增码**，增码须 bump 本规范。测试分层：确定性层永远 FakeLLM（外部 IO 不进事务，AGENTS.md / v8 不变量 4）；真 API smoke 属 release evidence（§6 分类）。检查：G4 gate（能力闭集 + 乘积表五码三行 + 错误码闭集断言）+ release evidence 工件。

**V14-HARN-8**〔P0〕多轮：跨 turn 的会话连续性（上下文携带、目标推进、终态收敛）由库内状态承担，harness 重启不丢轮次。检查：G4 多轮 gate（含一次中途 kill 续跑，断言按 EFF-6 适用面）。

**V14-HARN-9**〔P0〕compaction **只追加**。触发与 summary 字节只允许是 INV-3 命题 A 投影（或写死的稳定子集）的纯函数。probe、beat、attempt、lease、fencing、volatile 时间**不得**影响 summary。旧事件一律保留。economy 只记判断行 provider usage **整数**（input/output tokens 等），不记派生指标。检查：G4 gate（compact 后重放断言 + economy 整数记账断言）。

## 5. 基准对标（G5 冻结面）

### 5.1 任务形状

**V14-BENCH-1**〔P0〕借 PiG 任务形状（已核实：`PiG/evals/tasks/<name>/task.toml`，字段 `prompt` / `check`（shell 判定命令）/ `protected`（禁改文件）+ `files/`（任务工作区）），三任务：`add-json-flag` / `fix-off-by-one` / `rename-function`。`slow-build` 移到 v14.1 交付后补，不在本核心 G5。借用形状（v14 自建镜像目录），不依赖 PiG 仓库运行时；判定 = `check` 命令退出 0 且 `protected` 文件字节不变；**`check` 只由评测器执行，不经 agent 工具面**（防判定面与工具面混淆）。检查：G5 gate。

**V14-BENCH-2**〔P0〕多轮任务：v14 自造**至少 1 个**多轮任务（多轮 = ≥2 个依序 prompt，前轮产物进后轮工作区；形状字段在 v14 任务目录冻结）。具体任务清单由 G5 计划列出，但「≥1 个多轮」是本规范 P0 义务，G5 不得豁免。检查：G5 gate。

### 5.2 两层评测（plumbing / live）

**V14-BENCH-3**〔P0〕评测两层：**plumbing 层**——FakeLLM 脚本化判断驱动全部任务，结果可复现，gate 化（required，进零容忍 sweep）；**live 层**——真模型实跑对照（release evidence，§6 分类）；无凭证时 live 层按 SKIP 键处理（不参与 exit 0 判定，但缺席必须如实呈报）。检查：G5 gate（plumbing exit 0；live 层工件或 SKIP 呈报）。

### 5.3 对照报告

**V14-BENCH-4**〔P0〕复用 pi_parity 归一 trace 基建做 v14 vs pi 对照：归一 schema-v2 trace、canonical phases、drivers（`v13/pi_parity/` 既有 `pig_driver` / `piswift_driver` 与 pi 侧驱动）产出各方 trace，v14 侧新增同格式 trace 生成器。报告（工件入库 `v14/bench/`）至少含：任务通过率、拍数/工具调用数、token 成本、events 流形状对照，并**单列** ARCH-6「无任意 shell」：核心面无 exec、无 bash，不得把缺席记为 bash 覆盖。`slow-build` 标 SKIP 直至 v14.1。检查：G5 gate（trace 格式一致性断言 + 报告工件存在且字段齐全）。

**V14-BENCH-5**〔P1〕对照结论的表述边界：报告如实呈现差异，不宣称全面胜出；未跑面按 SKIP 纪律明示。检查：评审对照。

## 6. 分期与验收（G1..G5，gate 写死）

### 6.0 gate 三分类（全部 stage 适用）

**V14-GATE-C**〔P0〕gate 三分类与聚合：

| 类 | 退出码 | 语义 |
|---|---|---|
| **required** | 只 0/1 | 全 0 才算 stage 完成；进零容忍回归 sweep |
| **optional probes** | 0/1/2 | 2 = skipped（环境缺席）；skipped 不进零容忍 sweep，但缺席必须如实输出（先例 TP-GATE-2） |
| **release evidence** | 本地可 skip | 里程碑**关闭前**须有一次真工件入库（见 G4/G5） |

聚合算法：断言失败（1）优先于缺席（2）；先例 TP-GATE-2/3。检查：各 stage gate runner 实现三分类并断言聚合算法。

**V14-GATE-K**〔P0〕加载与迁移纪律：v14 stage 库 = v13 现行累计加载 + v14 迁移（**不加载 v8 SQL**）；每 stage `setup_db.py` DROP/CREATE 自己的库（`agent_v14_<stage>`）。检查：各 stage setup 断言加载清单。

> 运行纪律（全部 stage）：`UV_FROZEN=1 uv run python v14/<stage>/test_<name>.py`，退出语义按 §6.0 分类。每期收尾必须同时绿：本期全部 required gate + v13 既有全量零回归（`v13/read_tools/test_read_tools.py` 无旗标全量含 E4，退出 0）+ v14 已交付 stage 的回归 sweep（G3 起提供 `v14/regression`，镜像 E4 的发现-串行-零容忍纪律，只扫 required）。

### G1 工具面 v2（内核提交 K + 实现提交 S）

范围：合同 v2 bump 与回填（§2.3）+ 效果协议（§3.1：单一 `expected`、degraded 单主、resume 三分、renew 续租、cleanup/probe 状态闭集）+ write/edit + glob/grep 只读出生 + 审批（不含 exec 人批）+ diff 字节语法（V14-TOOL-2）。
提交集合（枚举，见 V14-PROC-3）：**K**（内核提交：合同 bump 文档 + v14 迁移 SQL（含 contract_version/generation 回填列）+ 允许名单）→ **S**（实现提交：口岸、目录行、gate）。
gate 验收（写死）：
- 〔P0〕`v14/tools/test_tools_v2.py`（required）exit 0：EFF-1 转移表全路径 + **后置条件表屏障+四短路行逐列**（短路序 ①时间 ②grant ③symlink ④基线，先命中独占一条 `claim/audit`（`payload.reason` ∈ {time, grant, symlink, baseline}），禁并行 kind；基线行 proposal→expired 且释放名额；pre-apply unlock+归还专属连接；planned→claimed 无已 IO→unknown；symlink 两分支正负例）+ 非法转移负例 + `expire_due` 四类 CAS（probe pending→timeout、cleanup pending→timeout、token active→expired、baseline pending→timeout）；intent 先于 IO；**出生统一**（三类创建事务 fencing_gen=1；read-only 同事务 started+attempt 1、无 claimed 停留；provider 无 reclaim；mutating receipt attempt_id=JSON null 且无 attempt 行；read-only receipt attempt_id 非空绑定；read-only lease 到期只 reclaim、不新开 attempt；attempt 2 仅当当前 attempt 已消耗且行数=1，新 attempt 自带 lease）；**fencing**（claimed→started 仅 started UPDATE 的 0 行才不改状态（引 EFF-1 该格）；lease 失配诊断阶段不得终结 effect、不得改 proposal、不得重分配 seq，恢复按 reclaim 规则；创建锁键高 8 位=`0x15`，不得复用 `0x14`；mutating reclaim 持锁前置 + generation 递增、probe 败者零 IO、过期 receipt 拒绝落库）；try-lock 不可得留态重试；**屏障只统计 mutating** + 未终态 claimed/started/unknown 时禁 claim 新 mutating（越序负例）+ reclaim 不绕屏障；seq 分配点恰 {claim 成功, 进入 degraded}，stale 不分配，horizon 冻结；write/edit 幸福路径 diff 单格式与字节语法逐项（排序/null 与空串区分/base64 alphabet+padding/mode 定宽/黄金向量 sha256；创建/删除/二进制/symlink 拒绝）；resume 三分 done/pending/unexplained，pending 含全 pending 时 rename 后写 tool/result；receipt 与分类互斥；write/edit 接受谓词=全观测，read-only 不是；无合法 succeeded receipt 时终态只来自 EFF-3 四支；started→failed 仅第④支；禁 attempt_exhausted、裸 status=failed、分类外 SQL 边；write create-only + edit 目标存在非 symlink；**准入两分支夹具**（write/edit 未命中 grant 拒绝不建行；grant 命中直入 claim）；拒绝路径工作区字节零变化；**两阶段 reconcile**（只绑 degraded_effect_id、CAS 成功写 reconciled_at 并清 degraded、历史 failed 不可重选）；观测请求先于 probe IO、probe 失败不改 effect 态；**独立 digest 正确性 gate**（payload_digest/diff_digest 预映像 + TOOL-2 黄金向量，与两比较面分离）。
- 〔P0〕`v14/tools/test_approval.py`（required）exit 0：V14-APPR-1..7 全断言（**write/edit 摘要字段集**（不含 exec 摘要）/单次消费 CAS/状态机含 approved→consumed 与 approved→expired/生产无 now 参数 + test-only 注入/请求创建时单名额执法与释放/核心面无 exec requested 夹具（write/edit 无等待相；人批夹具不在 G1）/grant 字段全集 + 签发/撤销/越界 + **核心面 grant 不覆盖 exec** + 命中合取逐项 + 内部动作 EXECUTE REVOKE（harness 与 service role）+ **两检查点**（claim CAS 见撤销零 IO；receipt 接受见撤销不回滚 IO）+ 命中直入 claim/**REVOKE FROM PUBLIC 全函数面** + 签发不收 principal/session_id/now/proposal_id + grant 行禁 UPDATE 除 revoked_at/principal 映射 fail-closed/无裸 DML/approved 为显式非终态/名额执法以三条件为准不得缩写成仅未终态 proposal）。
- 〔P0〕`v14/tools/test_contract_v2.py`（required）exit 0：contract-2 已 bump；v1 条款字节零改动；回填列默认值与既有 request 回填；v1 排队请求走 v1 handler + v2 新建请求两路径；无法解析绑定拒绝创建负例；`v13/**/*.sql` 零 diff。
- 〔P0〕同文件另断言：`expected` 全量重放式（禁用 proposal.old_* 当基底；会话创建后已有成功 effect 再建 proposal 须重算）；`session_baseline` 持锁冻结 W，扫描期拒新 claim；「已有 started effect 时建会话」与「未来新路径 create-only」；probe 成功后、状态事务前 kill 再 reclaim 不得用旧 body；claim 屏障行 0 行更新；首次 started 要求 fencing_gen≥2；reclaim 后 ≥3 进 started 为正例；write/edit receipt 只收 succeeded；分类四支（pending 复验失败禁写 tool/result）；`affected_paths` 基数=1 拒绝；read-only 五步序与 `V14_RO_OUTPUT_CAP`；advisory 键高 8 位 `0x14`；degraded 期间 expire_due 不终结排队 approved+planned。
- 〔P0〕v13 全量零回归（E4，required）。

### G2 v14.1-exec 规范裁定与冻结（spec 任务）

范围：裁定并冻结 `docs/designs/v14.1-exec.md`。本 stage **不实现 exec**，不立 `v14/exec/test_exec.py` 为核心 required。glob/grep 已在 G1。
gate 验收（写死）：
- 〔P0〕v14.1-exec 完成自己的裁定循环至 0 P0 / 0 P1。种子 N20、R11、S8-exec、codex P0-4、codex P0-5、gB P0-3 均有落点或显式关闭，不得静默丢失。
- 〔P0〕v14-dev 正文不再把 execve / `{run-test, build}` / exec×write 并发写成核心实现义务。
- 〔P0〕本 stage 若只有文档，不新增 SQL；v13 E4 与 G1 不因文档拆分变红。

### G3 harness MVP

范围：beat driver 提炼（§4.1）+ Chainlit 窗 + `v14_wake` + psql submit/observe demo + 双壳等价 + 会话可弃。**不依赖 exec**；write/edit 即可测 resume 与双壳。
gate 验收（写死）：
- 〔P0〕`v14/harness/test_resume.py`（required）exit 0：**SIGKILL 进程组**实证杀（非模拟），**只用 write/edit**。窗 1 = 四杀点并集：temp 已 fsync 未 rename、started 后 temp 前、temp 部分写入、rename 完成且复验成功但 receipt 前提交前被杀（与下文「另两缝」首条同一场景重述，断言点=不重放）。这四缝终态皆 `succeeded`。命题 A 只断言窗 1 与从未置位过 `degraded_effect_id` 的路径；failed+degraded 在 reconcile CAS 成功后只断言命题 B。reconcile/diff 仅进全流比较面，命题 A 永不纳入。窗 1=3 pending（③）+1 done（①）；窗外=1 复验失败。进程组只含 driver 与其 worker/provider 子进程。三缝走 resume 分类。另两缝：首条与窗 1 第 4 缝同一场景重述，断言点=不重放（rename 已完成、目标复验成功、receipt 提交前 kill → 分类 done、不重放）；rename 后注入复验失败、receipt 前 kill → unknown+degraded → reconcile → 断言命题 B。write/edit 的 failed+degraded 在 reconcile CAS 成功后只断言命题 B（折叠含该 seq 的 reconcile/diff，不入 A）。**cleanup gate**：receipt 或分类写完 tool/result 后杀 driver；resume 后 `cleanup` request 清 temp，temp 不在 = succeeded，工作区字节不变；另覆盖重复、失败、越界。execve 窗不在本 gate。
- 〔P0〕`v14/harness/test_dual_shell.py`（required）exit 0：两壳（脚本壳 + Chainlit 壳——经 Chainlit 无头测试模式驱动**真实 handler 模块**，禁止为 gate 另写假 handler；同一测试 principal）按 V14-HARN-4 算法比较（§4.3 **全流**、ORDER BY seq 后服务端投影 ::text 逐字节相等；两比较面均按派生字段表（payload_digest 排除、摘要哈希 canonicalize 重算）；A 面只收 HARN-4 字面白名单；workspace_effect_seq 原样入面），封闭性执法含新增键与 timestamptz 标量；两 principal 越权负例另测。**不使用 exec 输出夹具**。整场景共用一个 test-only `effective_now`。outer event seq 不入投影。
- 〔P0〕`v14/harness/test_thin.py`（required）exit 0：per-file 决策点计数（INV-5 上限表：driver ≤15 / handler ≤5 / 其余合计 0）+ import 前缀黑名单（六前缀）+ worker/provider 能力协议。
- 〔P0〕`v14/harness/test_listen.py`（required）exit 0：v14_wake 同事务 notify、payload 闭集、独立 autocommit 连接、初始补读、补读循环、四负例（通知合并/断线插入/查询-订阅间隙/重连无后续通知）、重连后 UI 历史从 events 重建。
- 〔P0〕psql submit/observe demo 脚本执行 exit 0。
- 〔P0〕Chainlit 依赖进入 `pyproject.toml` 与 `uv.lock` 更新同笔，且当笔全量回归绿；v13 E4 复跑绿。
- 〔P0〕`v14/regression/` sweep 上线（发现 `v14` 下全部 `test_*.py` 串行，required 零容忍、probe 照 skip 语义）。

### G4 真 provider

范围：DeepSeek 判断面产品化（provider 进程分离）+ 多轮 + compaction 只追加 + economy 整数记账（§4.4）。
gate 验收（写死）：
- 〔P0〕`v14/provider/test_deepseek.py`（required，FakeLLM 确定性部分）exit 0：同 judgment 合同双实现断言；provider 进程能力闭集（可 litellm，禁 DB/beat/写盘）；attempt 记账（start_attempt 同事务插 started+attempt 1+fencing_gen=1、无 reclaim；attempt 2 不换 effect 行；**第 3 次需求不插 attempt 行、effect→failed(attempt_exhausted)、attempt 行数保持 2**）；**完成 = 第 3 类 judgment 提交函数内原子动作**（同事务：校验 attempt→写 judgment 或错误 judgment→消耗 attempt→按乘积表改 effect；消耗后禁重派；driver 每次消耗后再调 start_attempt，SQL 决定插入或 attempt_exhausted）；**乘积表三行消耗语义**（ok 不带 tool receipt；content_invalid/budget_exceeded 的唯一终结边 = 错误 judgment 行）；`effect/terminal`（`terminal_reason=attempt_exhausted`）入投影；投影按 kind 丢弃 attempt 事件；判断错误码闭集五值同表映射、FakeLLM 与 provider 不得各增码；reconcile=独立动作（新 judgment_id）非 EFF-5 reconcile。
- 〔P0〕多轮 gate（required）exit 0：≥2 轮会话含一次中途 kill 续跑，断言按 V14-EFF-6 适用面（不宣称未提交 judgment 窗口 A/B 等价）。
- 〔P0〕compaction/economy gate（required）exit 0：compact 后可重放 compact 前全部历史；判断行 usage 整数记账。
- 〔P0〕**release evidence**：里程碑关闭前有一次真 DeepSeek smoke 工件入库——含模型 ID、usage、错误映射，且**无密钥**入库。
- 〔P1〕真 API smoke 脚本（optional probe 语义：无凭证 = 2，如实呈报）。

### G5 基准对标

范围：任务套件 + plumbing/live 两层 + 对照报告（§5）。
gate 验收（写死）：
- 〔P0〕`v14/bench/test_bench.py`（required）exit 0：三任务（不含 `slow-build`）+ ≥1 多轮任务，plumbing 层全判定（check 由评测器执行、退出 0 + protected 字节不变）。
- 〔P0〕trace 一致性 gate（required）exit 0：v14 trace 与 pi_parity schema-v2 格式断言一致。
- 〔P0〕对照报告工件存在且字段齐全（V14-BENCH-4 清单）。
- 〔P0〕**release evidence**：每个「已完成对照项」至少一对 v14↔pi **实跑**记录，附全链 provenance（固定 commit / 模型 / 参数 / 初始 tree hash）；无凭证面按 SKIP 键呈报，不参与 exit 0。

## 7. 环境

**V14-ENV-1**〔P0〕数据库与扩展：pgembed **`==0.3.0rc2`**（preflight 谓词钉死相等断言；本机实测事实，版本变化须 bump 本条）/ PostgreSQL 18.4。pgembed 以 editable 源安装自 sibling `../pgembed`（`pyproject.toml` `[tool.uv.sources]`）；duckdb 本地 wheel 来自 sibling `../duckdb-python-pgagent`（v13 read_duck 口岸用）。检查：preflight 断言版本相等。

**V14-ENV-2**〔P0〕UV_FROZEN：全部 gate 命令带 `UV_FROZEN=1`（先例 TP-GATE-4：未冻结的 `uv run` 会改写 `uv.lock`）。依赖变更（Chainlit 于 G3、其余按需）只在对应里程碑提交内发生，与 `uv.lock` 同笔，且当笔全量回归绿。检查：各 stage gate + source 断言 `uv.lock` 无计划外 diff。

**V14-ENV-3**〔P0〕sibling checkout 知情项（v14 文档责任）：全量回归依赖本机 sibling checkout——`/Users/wxl/Projects/pi`、`PiG`、`PiSwift`（`v13/pi_parity/test_pi_parity.py` 以绝对路径引用，缺席时诚实 `[SKIP]`）、`../pgembed`、`../duckdb-python-pgagent`、sitting_duck（TP-SNAP-1 pin）。`v14/README.md`（G1 收尾工件）必须记录：他机克隆须知情上述 sibling 布局，缺席面按 §6.0 optional probes 语义降级（缺席不是失败，也不是通过）。检查：`v14/README.md` 存在且含 sibling 清单。

**V14-ENV-4**〔P1〕v14 不引入新的数据库外部依赖；Chainlit 是唯一计划新增 Python 依赖。检查：pyproject diff 评审。

## 8. 流程与评审

**V14-PROC-1**〔P0〕gate 文化沿用并按 §6.0 三分类执行：gate 脚本独立可跑；偏差台账（`docs/reviews/v14-deviation-ledger-*.md`，自 G1 开立）登记一切对本文〔P1〕条款的让步——〔P0〕条款（含 INV-4 比较面与 INV-3-A 允许表）台账无权松动；覆盖矩阵按 stage 更新（`docs/reviews/v14-conformance-matrix-*.md`）。

**V14-PROC-2**〔P0〕oracle 对抗审核：spec 冻结 = 本文经 oracle 审至 0 P0 / 0 P1（父循环职责）；实现期每轮代码修改走 oracle 审核（双 oracle 模式沿用）。

**V14-PROC-3**〔P0〕逐里程碑提交推送：一 stage 一里程碑，里程碑的**提交集合在 stage 计划中枚举**（如 G1 = 内核提交 K + 实现提交 S，有序、逐个按路径 add）；测试全绿 + 收尾工件更新后提交；分支纪律遵循父循环台账（`v14-dev` 推送为加法允许面；合并回 main 须父循环终审 + 用户确认；禁止 force-push）。计划文件惯例：每 stage 开工时立 `docs/plans/v14-<stage>-<日期>.md`（本规范 §6 即其骨架，不预建空壳）。

**V14-PROC-4**〔P0〕收尾工件清单（每里程碑）：新 SQL 进 v14 迁移加载序列（V14-GATE-K）、覆盖矩阵、偏差台账、stage README、（涉依赖时）`pyproject.toml` + `uv.lock` 同笔。

**V14-PROC-5**〔P0〕规格原文权威：对标 pi 的行为疑问以 pi / PiG / PiSwift 仓库实际代码为准（引用须 file:line）；v8/v10/v13 已冻结条款以各自文档为准；本文与它们冲突时，按 §2 的关系裁决，冲突未裁决前按更严者执行。

## 9. 明确不做

1. 不做 pi 的进程模型 / TUI 复刻；不兼容 pi 插件生态与其 session 文件格式。
2. 不实现 v10 内核规格；不回改 v8 / v10 / v13 冻结面（内核变更流程除外，§2.3）。
3. 不引入 DSH Node host；P0C 按退役处理（§2.1），义务不转移。
4. **不做任意 shell，核心面也不实现 exec**。无 shell / 无 bash 的声明保留（ARCH-6）。闭集 exec 目录、tree-diff、多路径 exec 的最终形态 = v14.1 待裁，本冻结不承诺 `{run-test, build}`。任意 shell 仍不做。
5. 不在数据库事务内做任何外部 IO（v8 不变量 4，全文有效）。
6. 不做 UI 富交互（只 submit + LISTEN 渲染；审批呈现之外的 UI 状态机一律不做）。
7. 不做多 agent 编排 / RSI / 生态面（v8 P2/P3 范畴）。
8. 不预建空计划壳；不为「看起来完整」冻结未核实引用。
9. **不做对抗性载体加固**：威胁模型 = trusted-but-crashable（V14-ARCH-7）；防伪造回执/恶意观测的完整性加固范围外。

## 附录 A. 引用核实表（2026-09-28 逐条实查）

| 引用 | 核实结果 |
|---|---|
| `run_ring` 位置 | `v13/pi_ports/test_pi_ports.py:678`（`run_ring(planes)`，多平面同会话）；`v13/read_tools/test_read_tools.py:980`（无参版）。**不在 pi_parity**（父循环轮 1 目标原文有误，已按 V14-HARN-1 修正表述） |
| beat 拍结构 | `v13/pi_parity/test_pi_parity.py:66` `GOLDEN_SEQUENCE`（定义 66–71 行）；完整相位列表 = `judge / parse / advance / claim / tool / llm / finish`；**llm（assistant 输出）是显式 canonical phase，非 claim kind**——pi_parity schema-v2 定案，已落为 INV-2 规范条款 |
| 归一 trace 基建 | `v13/pi_parity/`：normalized schema-v2 trace 落 `traces/pg.jsonl`；`pig_driver/`（Go）、`piswift_driver/`（Swift）重放归一 transcript；工具链缺席诚实 `[SKIP]` |
| E4 | `v13/read_tools/test_read_tools.py:65` 发现命令（`find v13 -name 'test_*.py' -not -path 'v13/read_tools/*'`）；`run_e4` :2019；串行零容忍；UV_FROZEN 见 TP-GATE-4 |
| 口岸合同 | `docs/designs/v13-tool-ports.md` L5 版本 `v13/tool-port-contract-1` + bump 规则；TP-CAT-4 = L48（schema/加列须独立内核变更并 bump）；TP-INV-1..15；TP-ADMIT-1 十项准入 |
| 合同版本头读取（G1 预检） | v13 gate 对该文档仅 `isfile`（`test_read_tools.py:1998`，G2）与 README 路径/条款针（`:1728`，E3 needle：含文档路径与 TP-WIRE-3/TP-FS-5/TP-DUCK-3，**不含版本串**）——不解析版本头，K 提交 bump 不触发 v13 红 |
| beat 结算先例 | TP-HUB-2（complete→accepted→commit 顺序）；TP-HUB-4（tick 计数纪律） |
| v8-P0C | `docs/plans/v8-p0c-compat-host-plan-2026-09-17.md`：§0.1 DSH=DeepSeek Harness；C2=§5.2 go/no-go；host 接线未交付（C0–C6 未完成） |
| v10 硬缺口出处 | 父循环台账 `prompt-exports/loop-orchestrate-v14-runs.md:7`；grant/generation 交付佐证 `v8/README.md:9`（24/24 gate，2026-09-17）；「硬缺口」字面**不在** v10-dev.md 原文 |
| PiG 任务形状 | `PiG/evals/tasks/{add-json-flag,fix-off-by-one,rename-function,slow-build}/task.toml`：`prompt`/`check`/`protected` + `files/`（已抽读 add-json-flag 全文核实字段） |
| NOTIFY 先例 | `v8/closeout/v8_closeout.sql:121`（`pg_notify('v8_wait', …)`）；v14 用独立通道 `v14_wake`，不复用 `v8_wait` |
| reconcile 先例 | `v8/reconcile/`（既有 stage 目录；v14 人工 reconcile 语义援引其先例地位，不加载其 SQL） |
| 环境依赖 | `pyproject.toml`：pgembed editable `../pgembed`（>=0.3.0rc1 声明，本机实装 0.3.0rc2 → ENV-1 钉 `==0.3.0rc2`）、duckdb wheel `../duckdb-python-pgagent`、litellm、streamlit（v6 遗留）；Chainlit 尚未引入 |
| govern/economy 面 | `v13/govern/`、`v13/economy/`、`v13/control/` 均为既有 stage（SQL+gate+README） |
| compaction 语义 | `docs/designs/v8-dev.md` §3.3（seq、cancel、compact、repair） |

## 附录 B. 轮 15 → 轮 16 修订对照（核心面 CC1..CC4）

| # | 裁决 | 第 16 版落点 |
|---|---|---|
| CC1 | HARN-7 检查行 | 「乘积表五行」改为「乘积表五码三行」 |
| CC2 | EFF-2 四支 | ① lease 失配不改状态、走 reclaim；②③④ 才终结。G1 断言失配阶段不终结、不改 proposal、不重分配 seq |
| CC3 | reconcile 顺序 | ①token/fencing ②显式 outcome 闭集 ③file_type ④省略才填默认 ⑤成功 CAS。非法参数先拦 |
| CC4 | P2 | 0x15 保留句与 G1 断言。窗 1 第 4 缝与另两缝首条同场景。删「（Z5）」。第 2 类注明 expire 属 v14.1。转移格第②行。补 out_of_bounds 金向量 |








