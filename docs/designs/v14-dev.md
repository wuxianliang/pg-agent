# PG 原生 Pi 对标 Coding Agent（v14）开发规范

> 状态：草稿第 5 版，待 oracle 终审轮 5。冻结标准：评审至 0 P0 / 0 P1。
> 撰写日期：2026-09-28（第 1 版 `e97f4ce`；第 2 版 `e854e04`；第 3 版 `3af3dc6`；第 4 版 `0ee355f`）。工作分支：`v14-dev`。
> 修订记录：第 2 版吸收轮 1 双裁（4+3 P0）与父循环两裁决；第 3 版吸收轮 2 双裁裁决 A..M；第 4 版吸收轮 3 合并裁决 N1..N20；第 5 版吸收轮 4 合并裁决 R1..R19（条款级补丁：双序键合一、lease fencing、基线判别式决策表、准入合一、投影面拆分），全部落正文。
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

仿的是：工具集形状（read/write/edit/bash/glob/grep）、REPL 对话体验、基准任务成绩。不仿的是：进程内循环、进程内事实源、TUI 耦合。检查：设计评审对照本表；G3 双壳/可弃 gate。

### 0.3 Chainlit 使用约束

**V14-ARCH-3**〔P0〕Chainlit handler 只允许两种动作：**submit**（把用户输入经既有 SQL 命令入口提交进库）与 **observe**（LISTEN 事件流 → 渲染）。UI 历史从 events 表重建；Chainlit 会话内存不得成为事实源（INV-6）。审批动作在 UI 上也只是向 SQL 批准命令提交标量（approver 身份由 DB 得出，见 V14-APPR-6）。检查：source gate 静态扫描 handler 模块（V14-HARN-6）。

**V14-ARCH-4**〔P0〕明示反模式：禁止照抄 Chainlit 官方教程把 agent 循环写进 `@cl.on_message` handler（在 handler 里调 LLM、跑工具、维护对话状态、代批代答）。handler 内出现任何 beat 驱动、模型调用、工具分派、判断拼装即红。检查：source gate 断言 handler 模块 import 黑名单（V14-HARN-6）。

### 0.4 对标面定义、差异登记与威胁模型

**V14-ARCH-5**〔P1〕对标成立的三件事：① 工具面覆盖 pi coding agent 常用集（read/write/edit/bash/glob/grep）；② REPL 体验：Chainlit 窗口可对话驱动、可断线重连、历史完整；③ 基准：§5 任务套件上产出 v14 vs pi 对照报告。不承诺 TUI 视觉复刻、不承诺 pi 插件生态兼容。检查：G3/G5 gate 与对照报告。

**V14-ARCH-6**〔P1〕对标差异登记表（对 pi 语义的显式偏差，逐条列出，新增须 bump）：

| 差异点 | pi 语义 | v14 语义 | 理由 |
|---|---|---|---|
| `write` | 覆盖或创建 | **create-only**：目标已存在即拒绝；覆盖一律走 `edit` | mutating 效果可解释性（diff 恒为创建形态，V14-TOOL-2） |
| 审批门控 | 工具调用无审批环，权限在进程内裁量 | **write/edit = grant 门控**（未命中 grant 准入拒绝，无逐次人批）；**exec mutating（含 bash）= 逐次人批** | mutating 效果治理（V14-APPR；产品语义裁决 V14-TOOL-6） |

检查：G1 gate（write create-only 负例 + 准入两分支夹具）；设计评审对照本表。

**V14-ARCH-7**〔P1〕威胁模型（写死）：载体（carrier）= **trusted-but-crashable**——可崩溃、不可恶意。执法面：worker 能力合同（INV-5）+ SQL 结构性验证回执绑定与映射（INV-1 第 4 类）；resume_probe 观测由**受信 worker** 产出（V14-EFF-3）。对抗性载体（伪造回执/恶意观测）的完整性加固 = §9 范围外。检查：设计评审对照本条；G1/G3 gate 的回执验证断言。

## 1. 不可妥协的不变量（V14-INV-1..6）

> 本节原文照录父循环裁决，是全部后续条款的上位约束。任何 stage 设计、实现、gate 与本节冲突即无效。

**V14-INV-1 判断零外置（四类提交闭集）**〔P0〕一切决策（下一步做什么、何时结束、调用什么工具、是否需要模型判断）由 SQL 面产出（advance / 判断请求拼装与入队全在库内）；LLM 调用只是判断请求的数据面——问题由 SQL 面拼装、回答落 judgment 记录。**执法语义（四类提交闭集）**：harness 向库内提交的输入只许四类，每类只能调用**已登记 SQL 函数**（v13 既有 + v14 迁移新建），禁止裸 DML、禁止 harness 发 `pg_notify`：

1. **用户文本**（submit 入口）；
2. **审批决定**（approve | deny | reconcile 的标量参数；签名面见 V14-APPR-2/3/6——不收 session_id/proposal_id/principal/now，会话来自认证连接绑定）；
3. **判断答案**（FakeLLM 与真 provider 的回答文本同形，落 judgment；错误码闭集与乘积表见 V14-HARN-7 / V14-EFF-6）；
4. **工具回执**（统一 envelope：`kind`、`effect_id`、`attempt_id`、`fencing_gen`（执行时的 lease fencing generation；与 effect 当前代不一致 → **拒绝落库、状态不变**，V14-EFF-2）、`status`、`exit_code`、`payload_digest`、`stdout`、`stderr`、`diff`——SQL 验证绑定与状态后落库；driver 仅 opaque 转发，禁止解析回执推导下一步）。**kind 闭集 = `tool | resume_probe`**；tool 回执 **status 闭集 = `succeeded | failed`**；**status↔exit_code 映射写死**：exec 类 `exit_code=0 → succeeded`、`exit_code≠0 → failed`、`exit_code` 必填；非 exec 类 `exit_code=null`。**payload_digest 预映像 = `kind/effect_id/attempt_id/status/exit_code/diff_digest`**（status 已按 exit_code 规范化；不含 volatile；diff_digest 定义见 V14-TOOL-2）。resume_probe 载荷 = per-path 全观测 `{exists, file_type, mode, sha256}` + 临时文件内容摘要/类型/mode（受信 worker 产，V14-EFF-3）。

**无参已登记函数**（`advance` / `next_beat` / `expire_due`）**不是第五类输入**——它们没有参数面；任何新入口的参数面禁判断内容、principal、now、session_id。

人批与模型回答同属外部判断数据面：请求由 SQL 产出、答复落库；harness 不代批、不代答、不拼装。检查：G3 source gate（INV-5 扫描 + import 黑名单 + envelope 仅经登记函数断言）+ 判断面 gate 回归。

**V14-INV-2 beat 序列是数据**〔P0〕beat 序列（judge/parse/advance/claim/tool/llm/finish 一类的拍结构）是库内数据，不是代码控制流。advance 决定下一步，harness 仅执行。先例：`v13/pi_parity/test_pi_parity.py:66` 的 `GOLDEN_SEQUENCE`（canonical phases）与 `v13/read_tools/test_read_tools.py` / `v13/pi_ports/test_pi_ports.py` 的 ring 驱动。**相位定案**：assistant（模型）输出是**显式 canonical phase**（拍结构中的 `llm` 相），不是 `claim kind=llm`——按 pi_parity schema-v2 定案，本条为二选一歧义的落死。检查：G3 gate 断言 beat 拍落 events 表且驱动模块无硬编码序列分支、llm 拍为独立相位。

**V14-INV-3 会话可弃（双命题，适用面受限于 V14-EFF-6）**〔P0〕kill harness → 重启 resume 的可操作承诺收窄为两个命题，分别断言：

- **命题 A（事件面，独立语义子流）**：已提交事件的**A 子流**（允许 kind 闭集 = 用户提交 / judgment 终态 / proposal 终态 / tool/result / effect 终态 / reconcile/diff；**resume_probe、attempt、lease reclaim 不入 A**）的规范化投影在「杀过」与「未杀」两条世界线上一致。G3 窗 1 断言子流逐行相等 + `tool/result` 规范 diff 与 `workspace_effect_seq` 相同。**A 允许表是〔P0〕比较面，偏差台账不能扩**（V14-HARN-4）。
- **命题 B（工作区面）**：工作区终态 = **会话创建时冻结的 workspace tree hash** 起，按 `workspace_effect_seq` 升序折叠「成功 tool diff ∪ reconcile/diff」（V14-EFF-4/5）的确定性结果。

**适用面（原句）**：FakeLLM 路径与已提交 receipt 的 provider 路径；bash unknown 未 reconcile 的窗口、provider 未提交 receipt 的窗口除外。bash `unknown` 场景只承诺**终态有定义**（可进人工 reconcile，V14-EFF-5），不承诺「与不杀一致」；未 reconcile 的 unknown 世界线不宣称命题 B。检查：G3 杀进程续跑 gate（两杀点，§6 G3）+ G4 kill gate 按 EFF-6 断言。

**V14-INV-4 双壳等价**〔P0〕Chainlit 驱动与脚本驱动同输入 → 同 events 流逐字节一致。比较面与投影算法**写死于 §4.3（V14-HARN-4）**：库内唯一 canonical 投影函数、代理键 allowlist、volatile 键表、服务端比较；**双壳用 §4.3 全流**（两壳无杀点，与 INV-3 命题 A 的子流是两个不同比较面）。比较面新增排除项不属于已冻结类别时必须 bump 本规范——偏差台账无权松动 P0 比较面。检查：G3 双壳等价 gate。

**V14-INV-5 harness 决策点计数进 gate（按文件上限）**〔P0〕harness 的「薄」用决策点计数量化并进 gate。**口径（闭集）**：ast 扫描，计数节点闭集 = `If` / `For` / `While` / `Match` / `ExceptHandler` / `IfExp` / 推导式 `if`；`BoolOp` 不计。**扫描集**：`v14/harness/**/*.py`（排除 `tests/`、`workers/` 子树）∪ `v14/provider/**/*.py`（排除 `tests/`）。**上限（按文件，现在冻结）**：`v14/harness/driver.py` ≤ 15；`v14/harness/handler.py` ≤ 5；`v14/harness/` 同目录其余文件（除 `tests/`、`workers/`、`provider/`）合计 0——**新增 harness 文件须 bump 本规范**。provider 文件不设数值上限，但执行能力闭集（见下）。**import 前缀黑名单（写死）**：`litellm`、`v13.govern`、`v14.govern`、`v14.tools`、`v14.exec`、`v14.provider`——harness 内（driver/handler 及同目录）一律禁止 import。**worker 能力协议**（豁免边界 = 经 `run_line_json` 拉起的子进程）：单 effect 单进程、禁开 DB 连接、禁 import 模型 SDK、禁写声明路径外、退出即终；回传仅 stdout/stderr/exit code/diff。**provider 进程能力闭集**（`v14/provider/`）：可 import litellm；禁开 DB 连接、禁 beat 循环、禁写工作区；回答由 driver 按 INV-1 第 3 类提交。检查：G3 `test_thin.py`（per-file 计数 + 黑名单 + 两类能力协议）；G4 provider 能力 gate。

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

1. **载体**：在 `docs/designs/v13-tool-ports.md` 原文档**就地 bump** 版本号至 `v13/tool-port-contract-2` 并追加 v2 条款（mutating 语义 / diff 协议 / 审批 hook / 闭集命令执行器）。**v1 条款字节不动**（旧 ID 保留原文，新义务一律用新 ID 追加）。
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

## 3. 效果协议、工具面与执行面（G1/G2 冻结面）

### 3.1 效果协议（V14-EFF，G1 起生效，全部 stage 共用）

**V14-EFF-1 效果状态机（六态闭集 + 出生三分 + 转移表写死）**〔P0〕effect 态闭集 = `planned | claimed | started | succeeded | failed | unknown`（**无** approved/reconciled 态；批准语义在 proposal 上，V14-APPR；reconcile 是动作不是态）。**出生三分**：

- **mutating**（write/edit、mutating exec 动词）：与 proposal 批准**同事务** INSERT 即 `planned`（proposal 来源见 V14-TOOL-6 准入合一）；被拒/超时的**不建 effect 行**；**mutating 无 attempt 行**。
- **read-only**（glob/grep 及 `workspace_mode=read_only` 动词）：**无 proposal**，SQL INSERT `planned` **同事务自动 `claimed`**（提交态 = claimed）；**不取 apply 锁、不分配 workspace_effect_seq**；`started` 无 receipt 时 SQL **再开至多 1 次 attempt（同一 effect 保持 `started`）**，仍无则走 `attempt_exhausted` 路径（同 provider，下行）。
- **provider**：**无 proposal、无锁、无 seq**；`start_attempt` 由 SQL 执行——**同事务插 effect=`started` + attempt 1**；attempt 2 **不换 effect 行**；第 3 次需求**不插 attempt 行** → `failed(attempt_exhausted)` + `effect/failed/sql` 终态证据事件**入投影**（V14-EFF-6）。
- **边界**：v13 既有 read 口岸保持 v13 语义，**不建 v14 effect**。

转移表：

| 转移 | 条件与方式 |
|---|---|
| → `planned` / `planned+claimed` / `started` | 按出生三分（上行） |
| `planned` → `claimed` | 单条条件 UPDATE：proposal=approved、effective_now 未过 expires_at、grant 未撤销未过期（APPR-5）、workspace 基线匹配；**同事务** proposal → `consumed`。**claim 谓词失败拆互斥三行（决策表，写死）**：① 时间过期（now≥expires_at）→ 同事务 effect→`failed`、proposal→**`expired`**、释放名额；② grant 撤销/过期 → 同事务 effect→`failed`、proposal→`expired`（**独立审计 kind**）+ 释放名额（此时无 IO，V14-APPR-5 检查点①）；③ 基线不符 → **走判别式**（V14-EFF-5）：stale→`failed(stale)` 不 degraded；degraded→`failed`（未 IO）/`unknown`（已 IO）。**过期终态名单一选死 = expired** |
| `claimed` → `started` | **与「允许开始外部 IO」合并为一条条件更新（lease fencing）**：`WHERE state=claimed AND lease_owner=当前执行者 AND lease_until>effective_now`；**0 行更新 → 禁止任何外部 IO**（V14-EFF-2） |
| `started` → `succeeded \| failed` | 仅当带 receipt（INV-1 第 4 类 envelope；fencing 代验证通过）；receipt 接受谓词见 V14-EFF-3/TOOL-4 |
| `started` → `failed(attempt_exhausted)` | **SQL 侧终结转移**（provider 与 read-only 同一路径）：attempt_count=2 且第 3 次需求到达（provider）或再开 attempt 后仍无 receipt（read-only）时由 SQL 幂等生成；产生 kind=`effect/failed/sql` 终态证据事件且**入投影** |
| `started`（resume，无 receipt） | 按出生类分流：exec → `unknown` 禁自动重试（EFF-5）；write/edit → resume_probe 三分法（EFF-3）；provider → 不进 unknown，按错误码乘积表（EFF-6）；read-only → 再开至多 1 次 attempt |
| `unknown` → `succeeded \| failed` | 仅 reconcile SQL（EFF-5），单胜者 CAS |

检查：G1 起各 gate 断言合法转移集（非法转移负例）+ 决策表三行 + 劲竭终结事件。

**V14-EFF-2 intent 行、效果身份与 lease fencing（终版）**〔P0〕任何 **v14 effect** 的外部 IO 发生前，effect intent 行必须已提交入库（intent 事件位置仅表「IO 前日志已提交」，**不定义序**）；**效果身份 = `effect_id`（唯一）**。**范围边界**：proposal preflight read（V14-TOOL-3 ①）**不属于 effect IO**——只读、受读 lease 保护、不建 effect；apply 阶段以 EFF-3 锁内重算基线为准。claim 带 `lease_owner` / `lease_until`（now 取 V14-APPR-3 的 effective_now）与 **fencing generation**（每次 lease 变更 +1）。**fencing 规则（写死）**：

- `claimed→started` = 上表一条条件更新，**0 行即零 IO**；
- **reclaim** 仅当 `state=claimed ∧ lease_until≤effective_now ∧ 调用者持该 workspace 的 advisory 锁`；reclaim 使 fencing generation +1，effect **仍为 claimed**、proposal 保持 `consumed`、**禁新建 effect 行**；
- **resume_probe 与 reconcile 均单胜者 CAS**（`WHERE state=started` / `WHERE state=unknown`；败者零 IO）；
- **receipt 携带 fencing generation**，与 effect 当前代不一致 → 拒绝落库、状态不变（INV-1 第 4 类）。

检查：G1 gate（intent 先于 IO、fencing CAS 0 行零 IO、reclaim 持锁前置 + generation 递增、probe/reconcile 败者零 IO、过期 receipt 拒绝）。

**V14-EFF-3 write/edit 原子写与 resume 三分法（终版顺序 + 观测完备）**〔P0〕apply 顺序写死：**取锁 → 锁内重算全部受影响路径基线 → 任一不匹配 = 调判别式（EFF-5）禁 rename → 写临时文件 → fsync 临时文件 → rename → fsync 父目录 → 校验目标态（exists/hash/mode；该校验不替代锁内基线校验，两者都在）→ 才许提交 receipt**。临时文件**存活至 effect 终态，清理仅在 receipt 提交或 reconcile 完成后**；**目标为 symlink 一律拒绝**。

**resume_probe 观测（完备集，写死）**：per-path 观测 = `{exists, file_type, mode, sha256}`（symlink 一律拒）；另携带临时文件内容摘要/类型/mode（受信 worker 产）。resume 三分法（`started` 无 receipt 时，resume_probe 驱动，SQL 裁决；**case1/2 比较条件按全观测写死，非仅 hash**）：

1. 全观测 = 目标态 → **结算原 effect，不重放**（case1）；
2. 全观测 = 基线（文件不存在时用**冻结哨兵 `EMPTY`**）∧ 临时文件与 proposal diff 的 `new_sha256`/`new_mode` **经验证一致** → **持 workspace advisory 锁 + 先跑判别式 + 只做剩余 rename** 完成重放（case2）；
3. 都不是 → `unknown`，**禁止覆盖**（case3 = **调判别式，判别式之外禁记 stale**）。

**probe 异常短路**：temp 不存在或任一路径 symlink → **整 effect `unknown`、零 rename**。**rename 后失败**：目标态校验失败 / 父目录 fsync 失败 → `unknown`（IO 已发生）再跑判别式，**禁自动再 rename**。**多路径一次性分类（整 effect 粒度）**：任一 path = case3 → 整 effect `unknown`，不再 rename 其余 path；全 case1 → 不重放、结算 `succeeded`；仅 case1+case2 → 只重放 case2 后结算 `succeeded`；**禁逐路径各自 succeeded**。**receipt 接受谓词（写死）**：每 path `old_sha256` 等于锁内基线 ∧ `exit_code`/`status` 符合 INV-1 映射。成功后提交 `tool/result`（含 diff 载荷，V14-TOOL-2）。检查：G3 窗 1 杀点 gate；G1 原子写正/负例（symlink 拒绝、父目录 fsync、temp 生命周期、多路径三分各形态、receipt 接受谓词负例）。

**V14-EFF-4 workspace 全序、排他 apply 锁与屏障**〔P0〕每个 workspace 有 `workspace_id`。**排他锁**：会话级 advisory 锁（`pg_try_advisory_lock`，**workspace_id 映射到 v14 专用 bigint namespace**，避免与 v13 既有 advisory 键空间相撞）；在 claim 阶段尝试取得，**拿不到 → 结束当前事务，effect 留 `planned`/`claimed`，下一拍再试**；取得后**生命周期跨 `claimed→started` 的 COMMIT，直至 apply 结束或会话死**；**持锁连接专属于该次 apply，IO 期间不归还连接池**；所有受控 writer（write/edit、mutating exec 动词）用同一把锁（锁覆盖外部进程运行期间——受控 writer 串行是设计语义，V14-TOOL-4）。**advisory 锁仅 mutating 出生类取得**（read-only/provider 无锁）。持锁期间**重算受影响路径基线**，任一不匹配按 V14-EFF-5 判别式处置，禁止 rename。**workspace_effect_seq**：仅 **mutating 且 claim 成功**的 effect 拥有；在 claim 的已提交事务内分配；**每 workspace 从 1 单调**；不可变（resume/reconcile 复用原 seq，不重排）；INV-3 命题 B 的重放全序 = `workspace_effect_seq` 升序（折叠基底 = 会话创建时冻结的 workspace tree hash，INV-3）。**workspace 屏障（量化）**：workspace 存在未终态 `started`/`unknown` effect 时，**其他 mutating effect 一律不得 claim/apply/reclaim**（跨 session 执法）；**更低 seq 已 claimed 者保持 `claimed`，等其终态后再判别**；lease reclaim 不绕过屏障；`unknown` 即标 workspace **blocked**（并按 EFF-5 判别式可能进 degraded）。**外部写入（声明式，写死前提）**：workspace 在 apply 期间**无受控面外写入是前置条件**——违反 = 未定义行为；检测点 = receipt 验证与下一 effect 基线判别式（入 degraded）；**不承诺文件系统级防并发，只在受控面内防（advisory 锁）**。**expire_due（写死）**：仅 DB 时钟、无参数、幂等；requested 到期 → `expired`（不建 effect）；approved+planned 到期 → EFF-1 决策表时间行（effect `failed` + proposal `expired` + 释放名额）。检查：G1 gate（try-lock 不可得留态重试/屏障跨 session/更低 seq 保持 claimed/reclaim 不绕屏障/degraded 负例/expire_due 两分支）+ G3 命题 B 断言。

**V14-EFF-5 bash unknown、degraded 判别式与人工 reconcile**〔P0〕exec `started` 无 receipt（超时 kill 或进程被杀）→ `unknown`，**禁止自动重试**；**禁止合成 failed/succeeded receipt**；输出超限 = 带 receipt 的 `failed`（不变，TOOL-4）。

**判别式（可计算谓词，写死）**：从该 effect 冻结的 per-path 基线起，按 seq 升序折叠**全部更小 seq 的成功 tool diff ∪ reconcile/diff**；每条路径折叠结果与观测相等 → effect `failed(stale)`，workspace **不 degraded**；任一不等 → workspace **degraded**（本次未 rename 则 effect `failed`；已 IO 则 `unknown`）。**进 degraded 的转移若未分配 seq 则同事务分配**。判别式是 stale 的**唯一**记名途径（EFF-3 case3 同此）。

**degraded 唯一出口** = 与 unknown reconcile **同一 reconcile SQL**（principal 规则同 V14-APPR-6，单胜者 CAS）：追加不可变 **reconcile/diff**（同一 TOOL-2 字段格式，seq 复用原 effect）、清 degraded、此后基线 = 该 per-path 观测态；**observed 态由受信 SQL/worker 读取校验，禁调用方提交哈希**。`unknown → succeeded|failed` 仅经此 SQL：写 `reconciled_outcome` + `observed_hash`，后续 effect 基线改用 `observed_hash`。reconcile 决定走 INV-1 第 2 类提交，留痕 events（先例目录 `v8/reconcile/`）。

**命题 B 重放输入** = 成功 tool diff ∪ reconcile/diff，按 seq 升序（折叠基底见 EFF-4）；**未 reconcile 的 unknown 世界线不宣称命题 B**。provider 行只引 EFF-6：不取锁、不分配 seq、**永不进 unknown**；其「新 judgment 世代」是**独立动作（新 judgment_id），非本条 reconcile**。检查：G3 窗 2 杀点 gate（unknown + reconcile + observed_hash 生效断言）+ G1 判别式两分支正/负例（stale 可解释/degraded 不可解释）。

**V14-EFF-6 provider at-least-once 与错误码乘积表**〔P0〕provider effect 出生边见 EFF-1（start_attempt 同事务插 `started`+attempt 1；attempt 2 不换 effect 行；第 3 次需求不插行 → `failed(attempt_exhausted)`，attempt 行数保持 2）。attempt 事件**不属** INV-4 与 INV-3-A 任何比较面（投影按 kind 丢弃，V14-HARN-4）。**错误码乘积表（写死）**：

| 错误码 | judgment | attempt | effect |
|---|---|---|---|
| `ok` | 写一代成功 judgment | 消耗 attempt | `succeeded`（带 receipt） |
| `timeout` / `transport_error` | 不写成功 judgment | 记已用 attempt | 保持 `started`（未达 2 可再 start_attempt） |
| `content_invalid` / `budget_exceeded` | 写错误 judgment 行 | 停止 | `failed` |

**INV-3 命题 A/B 等价仅适用于 FakeLLM 路径与已提交 receipt 的 provider 路径**；G4 kill gate 不得把 provider 未提交 receipt 窗口宣称为 A/B 等价。检查：G4 gate（乘积表五行逐行断言/attempt 上限/failed/attempt 行数=2/第 3 次不插行/独立 judgment 世代断言）。

### 3.2 write/edit 口岸（G1）

**V14-TOOL-1**〔P0〕write/edit 是 mutating 口岸：结果改变工作区文件系统状态，**准入走 grant 门控（V14-APPR-5 / TOOL-6 准入合一）**：命中 grant → 建已 approved proposal + 插 `planned` effect；未命中 grant → **准入拒绝，零 proposal 零 effect**（无逐次人批，产品语义登记 §0 V14-ARCH-6）。**write 语义 = create-only**：目标已存在即拒绝；覆盖一律走 edit。**edit 语义 = replace-existing**：提案构建要求**目标存在且非 symlink**，否则拒绝不建 effect（与 write create-only 配对）。检查：G1 gate（准入两分支 + write create-only 负例 + edit 目标缺失/symlink 拒绝 + 拒绝路径工作区字节零变化）。

**V14-TOOL-2 diff 协议（单格式 + 规范编码终版）**〔P0〕diff 只有一种格式：每 path 记 `{old_exists, old_sha256, old_mode, new_exists, new_sha256, new_mode, payload 编码}`——payload 编码 = 文本 utf8 / 二进制 base64；覆盖创建（old_exists=false）、删除（new_exists=false）、二进制、symlink 拒绝策略。**禁止** old/new 成对与 unified diff 二选一的旧措辞。write 的 diff = old 全空（old_exists=false）。**规范编码（写死）**：路径按**相对路径字节序**排序；缺失哈希 = **JSON null**；payload 含 NUL 或非法 UTF-8 → base64，否则 utf8；**diff_digest = 该字段集保序规范 UTF-8 文本编码（字段序、紧凑分隔、缺失哈希=null）的 sha256，在送入 jsonb 之前计算（不用 `jsonb::text`）**。diff 是 events 流的一部分（落 `tool/result` 载荷），供审批渲染、INV-3 命题 B 重放与 gate 断言。检查：G1 gate 对 diff 载荷结构断言（含创建/删除/二进制/symlink 负例 + 规范编码逐项：排序/null/base64 判定/diff_digest 预映像）。

**V14-TOOL-3**〔P0〕write/edit 执行拆三步：① **提案构建（三段式）**：短事务登记只读 lease 并提交 → **事务外**读文件 → 新事务写 proposal 释放 lease（**文件 IO 永不在打开的 DB 事务内**，v8 不变量 4；preflight read 不属 effect IO，EFF-2）；② **等待（仅 requested 才存在）**：`await_approval` 仅存在于 exec mutating 的 requested proposal（bash 人批，TOOL-6）；write/edit 无等待相（grant 命中即 approved 直入 claim）；等待期游标停 `await_approval`，不持任何 claim（V14-APPR-4）；③ **claim/apply**（取 workspace 排他锁（EFF-4）→ claim effect → 原子写（EFF-3）→ complete）。检查：G1 gate 三步各断言 claim 生命周期与三段构建顺序。

### 3.3 审批协议（V14-APPR，G1 交付状态机与批准命令；G2 只加 exec 策略）

**V14-APPR-1**〔P0〕proposal 不可变、一次构建。**摘要双型（写死）**：write/edit 摘要 = 合同版本、generation、工具名、完整参数、cwd、受控环境标识、workspace 基线哈希、**规范化 diff**、有效期（expires_at）、可空 `grant_id`（入摘要哈希）；**exec 摘要 = verb + 类型化 argv + envp 闭集 + cwd + 基线哈希 + 有效期（diff 仅在事后 `tool/result`，不入 exec 摘要）**。检查：G1 gate 摘要双型完备性断言。

**V14-APPR-2 批准与消费（谓词定位 + 单次消费 + 竞争审计）**〔P0〕批准只批摘要（哈希锚定）。**批准输入禁止携带代理键字面量**（proposal_id、session_id 等）：approve/deny/expire/reconcile **不收 session_id / proposal_id / principal / now**，目标用谓词选（如「本会话唯一 requested proposal」，会话来自**认证连接绑定**），命中非唯一即拒绝。**条件更新写死**：approve/deny/expire 用 `WHERE state=requested` 条件更新，胜负各写**竞争胜负审计事件**。消费：`planned→claimed` 与 `proposal approved→consumed` 同事务单次消费（EFF-1 决策表）；执行 claim 时 CAS 重验（摘要哈希一致、状态、未过期、workspace 基线仍匹配、grant 未撤销未过期（APPR-5）），任一不符即按 EFF-1 决策表处置并留痕。检查：G1 gate（谓词定位非唯一负例/重放/篡改/基线漂移负例/竞争胜负审计事件断言）。

**V14-APPR-3 effective_now（DB 时钟；test-only 注入）**〔P0〕生产 approve/deny/expire/reconcile **不接受调用方 now、不读调用方可写会话变量**；effective_now 来自 DB 时钟。仅**测试专用角色**经隔离 test-only 入口注入 now。所有 CAS 用同一 effective_now 在同事务检查 `expires_at`。检查：G1 gate（生产入口无 now 参数 source 断言 + test-only 注入正例 + 共享 CAS 时钟断言）。

**V14-APPR-4 等待与串行（单名额在请求创建时执法）**〔P0〕proposal 状态机 `requested → approved | denied | expired`（三择终态）+ `approved → consumed`（与 effect claim 同事务）+ `approved → expired`（claim 谓词失败/到期时，EFF-1 决策表；expired 为过期终态**唯一**落点）。超时判定用 APPR-3 的 effective_now（expire_due 见 EFF-4）。等待期游标停 `await_approval`：不持 claim、不占 beat 前进位；批准后重新走 V14-EFF claim。**mutating 单名额执法时点 = 请求创建时**：已存在 requested proposal、未消费 approved proposal、或未终态 mutating effect → 新 mutating 请求**拒绝并留痕**（写死为「存在未终态 proposal 时禁止创建第二个」）。deny/过期/失败路径**释放名额**。检查：G1 gate（创建时拒绝负例/名额释放/等待期 beat 推进）。

**V14-APPR-5 grant 字段全集与命中规则（终版）**〔P0〕grant 行字段冻结：`grant_id / granting_principal / session_id / workspace_id / tool_set / argument_schema / cwd 根 / contract_version / generation / issued_at / expires_at / revoked_at`。**grant 行除 `revoked_at` 空→非空外禁 UPDATE**。**拒签谓词（写死）= `workspace_mode=mutating` 的 exec（bash 及动词目录内一切 mutating 动词）一律拒签且总建 requested——按 workspace_mode 判，勿只字符串等于 "bash"**。**grant 命中 = 请求创建事务内的内部动作**（非独立入口）：命中即在同事务生成不可变 proposal 并由 SQL 转 `approved`（principal 记录 = granting_principal），EXECUTE 权限对 harness 与 service role 一律 REVOKE；每次命中仍单次消费（APPR-2）；命中已 approved 的请求直入 claim（无等待相，TOOL-3）。**命中合取（写死）**：工具名 ∈ tool_set ∧ 每受影响相对路径匹配 glob ∧ cwd 在 grant 根下 ∧ workspace_id/session_id/contract_version/generation 相等 ∧ 未撤销未过期 ∧ 非路径标量过 argument_schema；**正文/diff/哈希不参与比较**。**两检查点（写死）**：① claim CAS 时见撤销/过期 → EFF-1 决策表 grant 行（**此时无 IO**）；② **receipt 接受时见撤销 → 不回滚已 started 的 IO**，终态按 receipt/EFF-5。模式闭集 = 工具名 + 相对路径 glob。签发/撤销/越界负例进 `test_approval`。检查：G1 gate（字段完备/签发/撤销/越界/mutating-exec 拒签（含目录内非 bash mutating 动词）/命中合取逐项/内部动作 + REVOKE 断言/两检查点分支/命中直入 claim/grant 行禁 UPDATE 除 revoked_at）。

**V14-APPR-6 principal 与签发封死（DB 认证，fail closed）**〔P0〕审批/签发/撤销函数**不接受 principal 参数**（issue_grant/revoke_grant 亦不收 session_id/now/proposal_id；`granting_principal` 取当前认证 principal）。**权限封死（写死）**：`issue_grant / revoke_grant / approve / deny / expire / reconcile` 全部 **REVOKE FROM PUBLIC** + 从 harness 与 service role REVOKE，**EXECUTE 仅授认证 approver 角色**。生产路径须有与实际 approver 一一对应的 **DB 认证 principal**；共享 service role 不得执行审批；无法映射即 fail closed（拒绝并留痕）。**会话绑定 = 认证时写连接不可变属性**；审批/签发不读调用方可写 GUC。Chainlit 部署的身份映射 = 受信连接 / 角色属性。principal 写 events。检查：G1 gate（principal 映射断言 + REVOKE FROM PUBLIC 断言 + service role 拒绝 + 无法映射 fail-closed 负例 + 签发参数面断言）。

**V14-APPR-7 测试纪律**〔P0〕禁止直改审批/effect 状态表；approve/deny/expire/reconcile 一律走产品 SQL 命令；时钟注入仅经 APPR-3 的 test-only 入口。检查：G1 起全部审批相关 gate（source 断言无裸 DML）。

### 3.4 bash/glob/grep 执行面（G2，exec=闭集命令执行器）

**V14-TOOL-4 闭集命令执行器（进程边界封死）**〔P0〕执行方式 = `execve(动词目录固定可执行文件绝对路径 + 版本摘要, argv 数组)`——禁止 `shell=True`、禁止 `sh -c`、禁止任何字符串拼接执行。**verb executable = digest 校验的受信二进制，禁脚本、禁 shebang**；verb 本体与其子进程树禁调 shell/解释器（source gate 扫 `sh -c` / `bash -c` / `shell=True` / `os.system` / `os.popen` / `create_subprocess_shell`）。argv 段只有两种：目录固定字面量，或**类型化参数**（enum / int / bool / 相对路径闭集；路径拒绝对路径、`..`、NUL）。**execve 的 envp = 闭集**（空或合同点名键），禁止继承调用方环境。每个 verb 声明 `workspace_mode`：`read_only` | `mutating`；**未声明 workspace_mode 即拒绝执行**。**动词目录初始裁决（进合同 v2 附录）**：`run-test = read_only`、`build = mutating`；目录恰 = {run-test, build}。**mutating 动词与 write/edit 共享同一把 apply 锁与同一状态图**（EFF-4；锁覆盖外部进程运行期间——受控 writer 串行是设计语义）；started 前锁内基线重算；seq 在 claim 已提交事务分配；receipt 丢失 → `unknown` 阻塞 workspace（EFF-5）；**exec 已跑且 receipt 接受谓词（EFF-3）不一致 → `unknown` 不重试**。**路径解析**：从 workspace root dirfd 逐级 no-follow（openat/renameat、`RESOLVE_BENEATH` 语义），任一父分量是 symlink 即拒。**超时 kill 整个进程组**。围栏：工作区根约束、超时、输出上限——**输出超限 = effect failed，不是截断成功**。必测负例：参数含 shell 元字符时子进程 argv 逐字节等于该值且被拒或仅作字面量；**verb 内部重解释 argv；父目录 symlink 越界；检查后替换（TOCTOU）竞态**；**exec×write 并发/kill/基线漂移**。加动词 = 合同面变更（§2.3）。任意 shell 整体移出 v14 范围（§9）。检查：G2 gate（上述全部正/负例；source 断言）。

**V14-TOOL-5**〔P0〕glob/grep 是只读口岸：**输入、结果与错误码闭集**，围栏与既有 read 口岸同级（TP-WIRE / TP-FS 纪律），无审批环；effect 走 EFF-1 出生三分的 read-only 分支（无 proposal、提交态 claimed、无锁无 seq、至多 1 次再开 attempt）。检查：G2 gate（闭集与围栏负例 + read-only 出生路径断言）。

**V14-TOOL-6 准入合一与四路径（产品语义裁决）**〔P0〕**单一准入路径**：

- **exec mutating（bash 及动词目录内 mutating 动词）**：**总建 `requested` proposal，不自动批**（逐次人批；无人动作到 expires_at → `expired`；显式 deny → `denied`；不收 grant，APPR-5 拒签谓词）。
- **write/edit**：命中 grant → 建已 `approved` proposal + 插 `planned` effect（同事务，直入 claim）；**未命中 grant → 准入拒绝，零 proposal 零 effect（无逐次人批）**。

四路径拆死：① **默认拒** = write/edit 未命中 grant（准入拒绝不建行）；② **批过** = exec requested → `approved`（人批）；③ **驳回** = 显式 deny → `denied`；④ **超时** = 到期 → `expired`。审批请求与决定经 SQL 面留痕；human route 待审队列可被第二壳观察（UI 只是渲染，V14-ARCH-3）。检查：G2 gate（四路径 events 与文件系统效果断言 + G1 准入两分支回归）。

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

1. **同输入协议**：两壳各自**新会话、新工作区**，喂同输入序列；输入含批准——批准作为 SQL 命令序列经 **govern 入口**提交，无旁路（V14-APPR-7）；**双壳使用同一测试 principal**；两 principal 越权负例另行单测（不进等价 gate）。
2. **同入口**：两壳驱动**同一组 SQL 入口**（submit / approve / …）；seq 由 SQL 分配，客户端不造序。
3. **canonical 投影（库内唯一函数）**：投影函数在**库内**实现（递归 jsonb 遍历），禁止客户端拼串。**遍历序冻结 = jsonb 自身键序、数组从左到右**。归一规则：
   - **代理键 allowlist（写死，八类各自独立前缀）**：`session_id→$s`、`event_id→$ev`、`effect_id→$ef`、`judgment_id→$j`、`proposal_id→$p`、`attempt_id→$at`、`grant_id→$g`、`workspace_id→$w` 及递归出现的同值——按首次出现顺序编号（`$s1/$ev3/…`），同值同替换、跨行一致；
   - **volatile metadata 键表（与时间分开，写死）**：`ts / wall_time / created_at / pid / lsn / expires_at / started_at / finished_at / duration_ms / elapsed_ms / lease_until / lease_owner / issued_at / revoked_at / effective_now` → 类型占位符；
   - **workspace 根 → `$ws`**；事件内文件路径一律以**相对根形式**存储；
   - **attempt 事件按 kind 丢弃**（不属任何比较面，EFF-6）；**`payload_digest` 是派生字段，从双壳比较面排除**（其正确性由独立 digest gate 断言，G1）；`workspace_effect_seq` 每 workspace 从 1 单调、同构操作两壳同值 → **原样入比较面（不替换）**；
   - **封闭性执法（字符串模式，写死）**：键不在 volatile 表的标量值匹配 RFC3339 时间串或纯数字 epoch、或未列名的 `*_at / *_ms / *_until / *_pid / *_lsn`、**timestamptz 型标量**、绝对路径、未识别 uuid → **gate 失败**，新增类别必须 bump 本规范（偏差台账无权松动）。**uuid 规则仅作用于整个 jsonb 标量值 = uuid 形**（对 stdout/stderr/diff 等文本载荷不做子串扫描）；**字符串先做 `$ws` 前缀替换，替换后仍残留绝对路径才失败**；digest 规范化用显式保序文本编码（V14-TOOL-2），不经 jsonb::text；
   - **比较（写死）**：每流按 `(session_id, seq)` **ORDER BY seq** 后投影 `::text`，逐行相等（服务端执行）。
4. **两个比较面**：**INV-4 双壳等价**用 §4.3 全流（两壳无杀点）；**INV-3 命题 A**用独立语义子流（允许 kind 闭集见 INV-3；resume_probe/attempt/lease reclaim 不入 A）——**A 允许表是〔P0〕比较面，偏差台账不能扩**。批准输入禁携带代理键字面量（V14-APPR-2）。

检查：G3 `test_dual_shell.py`（全流）+ `test_resume.py` 窗 1（A 子流 + tool/result 规范 diff 与 workspace_effect_seq 相同断言）。

**V14-HARN-5**〔P0〕psql demo 收窄为 **submit/observe demo**：一条纯 psql 路径演示「SQL 命令提交输入 + `LISTEN v14_wake` 观察事件流」，证明载体无关性；不宣称「全程 psql 驱动 agent 完成 mutating 任务」。demo 脚本入库（`v14/harness/`）。检查：G3 gate（psql 执行 demo 退出 0 + 事件断言）。

**V14-HARN-6**〔P0〕harness 薄度执法（INV-1/INV-5 的 gate 细则）：per-file 决策点计数（INV-5 上限表）；import 前缀黑名单（INV-5 六前缀）；worker 与 provider 能力协议断言（INV-5）。检查：G3 `test_thin.py`；G4 provider 能力 gate。

### 4.4 真 provider、多轮与 compaction（G4）

**V14-HARN-7**〔P0〕DeepSeek 判断面产品化：provider 调用放 **`v14/provider/` 独立进程**——可 import litellm，禁开 DB 连接、禁 beat 循环、禁写工作区（INV-5 能力闭集）；回答由 driver 按 INV-1 第 3 类提交；与 FakeLLM 实现同一 judgment 合同（同参数/同落库/同错误闭集）；调用经 V14-EFF-6 attempt 记账与**错误码乘积表**。**判断错误码闭集（写死）**：`ok | timeout | transport_error | content_invalid | budget_exceeded`——FakeLLM 与 provider 同表映射，**不得各自增码**，增码须 bump 本规范。测试分层：确定性层永远 FakeLLM（外部 IO 不进事务，AGENTS.md / v8 不变量 4）；真 API smoke 属 release evidence（§6 分类）。检查：G4 gate（能力闭集 + 乘积表五行 + 错误码闭集断言）+ release evidence 工件。

**V14-HARN-8**〔P0〕多轮：跨 turn 的会话连续性（上下文携带、目标推进、终态收敛）由库内状态承担，harness 重启不丢轮次。检查：G4 多轮 gate（含一次中途 kill 续跑，断言按 EFF-6 适用面）。

**V14-HARN-9**〔P0〕compaction **只追加**：compact 产生新 summary 事件，旧事件一律保留；事实完整 = 可重放 compact 前全部历史（沿用 v8 compact 语义，`docs/designs/v8-dev.md` §3.3；触发与产物落库）。economy 只记判断行 provider usage **整数**（input/output tokens 等），不记派生指标。检查：G4 gate（compact 后重放断言 + economy 整数记账断言）。

## 5. 基准对标（G5 冻结面）

### 5.1 任务形状

**V14-BENCH-1**〔P0〕借 PiG 任务形状（已核实：`PiG/evals/tasks/<name>/task.toml`，字段 `prompt` / `check`（shell 判定命令）/ `protected`（禁改文件）+ `files/`（任务工作区）），四任务：`add-json-flag` / `fix-off-by-one` / `rename-function` / `slow-build`。借用形状（v14 自建镜像目录），不依赖 PiG 仓库运行时；判定 = `check` 命令退出 0 且 `protected` 文件字节不变；**`check` 只由评测器执行，不经 agent 的 exec 面**（防判定面与工具面混淆）。检查：G5 gate。

**V14-BENCH-2**〔P0〕多轮任务：v14 自造**至少 1 个**多轮任务（多轮 = ≥2 个依序 prompt，前轮产物进后轮工作区；形状字段在 v14 任务目录冻结）。具体任务清单由 G5 计划列出，但「≥1 个多轮」是本规范 P0 义务，G5 不得豁免。检查：G5 gate。

### 5.2 两层评测（plumbing / live）

**V14-BENCH-3**〔P0〕评测两层：**plumbing 层**——FakeLLM 脚本化判断驱动全部任务，结果可复现，gate 化（required，进零容忍 sweep）；**live 层**——真模型实跑对照（release evidence，§6 分类）；无凭证时 live 层按 SKIP 键处理（不参与 exit 0 判定，但缺席必须如实呈报）。检查：G5 gate（plumbing exit 0；live 层工件或 SKIP 呈报）。

### 5.3 对照报告

**V14-BENCH-4**〔P0〕复用 pi_parity 归一 trace 基建做 v14 vs pi 对照：归一 schema-v2 trace、canonical phases、drivers（`v13/pi_parity/` 既有 `pig_driver` / `piswift_driver` 与 pi 侧驱动）产出各方 trace，v14 侧新增同格式 trace 生成器。报告（工件入库 `v14/bench/`）至少含：任务通过率、拍数/工具调用数、token 成本、events 流形状对照。检查：G5 gate（trace 格式一致性断言 + 报告工件存在且字段齐全）。

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

范围：合同 v2 bump 与回填（§2.3）+ 效果协议（§3.1 全部：出生三分、fencing、决策表、判别式、屏障、expire_due）+ write/edit 口岸与准入合一（§3.2）+ diff 单格式与规范编码（V14-TOOL-2）+ 审批协议全套（§3.3，含 grant 命中合取与签发封死）。
提交集合（枚举，见 V14-PROC-3）：**K**（内核提交：合同 bump 文档 + v14 迁移 SQL（含 contract_version/generation 回填列）+ 允许名单）→ **S**（实现提交：口岸、目录行、gate）。
gate 验收（写死）：
- 〔P0〕`v14/tools/test_tools_v2.py`（required）exit 0：EFF-1 转移表全路径 + **决策表三互斥行**（时间过期/grant 撤销（独立审计 kind）/基线不符→判别式）+ 非法转移负例；intent 先于 IO；**fencing**（claimed→started 0 行零 IO、reclaim 持锁前置 + generation 递增、probe/reconcile 败者零 IO、过期 receipt 拒绝落库）；try-lock 不可得留态重试；屏障跨 session + 更低 seq 保持 claimed；write/edit 幸福路径 diff 单格式与规范编码逐项（排序/null/base64/diff_digest 预映像；创建/删除/二进制/symlink 拒绝）；resume_probe 全观测（{exists,file_type,mode,sha256}、temp 摘要验证、case1/2 全观测比较）；多路径三分一次性分类；receipt 接受谓词负例；write create-only + edit 目标存在非 symlink；**准入两分支夹具**（write/edit 未命中 grant 拒绝不建行；grant 命中直入 claim）；拒绝路径工作区字节零变化；**独立 digest 正确性 gate**（payload_digest/diff_digest 预映像断言，与双壳比较分离）。
- 〔P0〕`v14/tools/test_approval.py`（required）exit 0：V14-APPR-1..7 全断言（**摘要双型**（write/edit 含 diff；exec=verb+argv+envp）/谓词定位非唯一负例/WHERE state=requested 条件更新与竞争胜负审计/单次消费 CAS/状态机含 approved→consumed 与 approved→expired/生产无 now 参数 + test-only 注入/请求创建时单名额执法与释放/等待断言**用 exec requested 夹具**（write/edit 无等待相）/grant 字段全集 + 签发/撤销/越界 + **mutating-exec 拒签（含目录内非 bash mutating 动词）** + 命中合取逐项 + 内部动作 EXECUTE REVOKE（harness 与 service role）+ **两检查点**（claim CAS 见撤销零 IO；receipt 接受见撤销不回滚 IO）+ 命中直入 claim/**REVOKE FROM PUBLIC 全函数面** + 签发不收 principal/session_id/now/proposal_id + grant 行禁 UPDATE 除 revoked_at/principal 映射 fail-closed/无裸 DML）。
- 〔P0〕`v14/tools/test_contract_v2.py`（required）exit 0：contract-2 已 bump；v1 条款字节零改动；回填列默认值与既有 request 回填；v1 排队请求走 v1 handler + v2 新建请求两路径；无法解析绑定拒绝创建负例；`v13/**/*.sql` 零 diff。
- 〔P0〕v13 全量零回归（E4，required）。

### G2 执行面（只加 exec 策略与执行口岸）

范围：闭集命令执行器（§3.4，进程边界封死 + 目录模式裁决）+ glob/grep 只读口岸（read-only 出生分支）+ govern/human route 审批环接线（四路径拆死；审批状态机已在 G1）。
gate 验收（写死）：
- 〔P0〕`v14/exec/test_exec.py`（required）exit 0：execve/无 shell（source 断言含六模式扫描）；verb executable digest 校验受信二进制（禁脚本/shebang）；envp 闭集（禁继承）；目录恰 = {run-test, build} 且 **run-test=read_only / build=mutating 模式断言**；workspace_mode 声明执法；类型化参数域负例；shell 元字符 argv 逐字节负例；verb 内部重解释 argv 负例；父目录 symlink 越界负例（no-follow/dirfd/RESOLVE_BENEATH）；TOCTOU 竞态负例；超时 kill 整个进程组；glob/grep 闭集与围栏负例 + read-only 出生路径；exec 围栏（越界/超时/超限=failed）负例；**exec mutating 与 write 共享锁/状态图：exec×write 并发、kill（receipt 丢失→unknown 阻塞）、基线漂移三组测试**；exec 已跑且 receipt 谓词不一致→unknown 不重试。
- 〔P0〕`v14/exec/test_govern_route.py`（required）exit 0：四条审批路径拆死（write/edit 未命中 grant 准入拒绝零 proposal 零 effect；exec mutating 总建 requested→人批 approved；denied；expired）、审批命令经 SQL 面、留痕 events、human route 队列可由第二壳观察。
- 〔P0〕v13 全量零回归（E4）+ G1 gate 复跑绿。

### G3 harness MVP

范围：beat driver 提炼（§4.1）+ Chainlit 窗 + `v14_wake` LISTEN/NOTIFY 终版（§4.2）+ psql submit/observe demo（§4.3）+ 双壳等价 + 会话可弃（两杀点）+ 薄度执法。
gate 验收（写死）：
- 〔P0〕`v14/harness/test_resume.py`（required）exit 0：**SIGKILL 进程组**实证杀（非模拟），杀点为**确定性测试缝**：窗 1 = 阻塞在已提交 `started`、rename 之前；窗 2 = 阻塞在子进程 `execve` 之后、receipt 之前。进程组只含 driver 与其 worker/provider 子进程；数据库进程与测试控制器在组外。窗 1 → resume_probe 提交 + 三分法（V14-EFF-3）+ **命题 A 子流断言**（A 允许表逐行相等 + `tool/result` 规范 diff 与 `workspace_effect_seq` 相同）+ 命题 B 断言；窗 2 → unknown + 人工 reconcile 走通（V14-EFF-5，只断言终态有定义）。
- 〔P0〕`v14/harness/test_dual_shell.py`（required）exit 0：两壳（脚本壳 + Chainlit 壳——经 Chainlit 无头测试模式驱动**真实 handler 模块**，禁止为 gate 另写假 handler；同一测试 principal）按 V14-HARN-4 算法比较（§4.3 **全流**、ORDER BY seq 后投影 ::text 逐行相等，payload_digest 排除、workspace_effect_seq 原样入面），封闭性执法含新增键与 timestamptz 标量；两 principal 越权负例另测。**夹具义务：exec 输出用冻结字节**（build/run-test 的 stdout/stderr 预先固化）。
- 〔P0〕`v14/harness/test_thin.py`（required）exit 0：per-file 决策点计数（INV-5 上限表：driver ≤15 / handler ≤5 / 其余合计 0）+ import 前缀黑名单（六前缀）+ worker/provider 能力协议。
- 〔P0〕`v14/harness/test_listen.py`（required）exit 0：v14_wake 同事务 notify、payload 闭集、独立 autocommit 连接、初始补读、补读循环、四负例（通知合并/断线插入/查询-订阅间隙/重连无后续通知）、重连后 UI 历史从 events 重建。
- 〔P0〕psql submit/observe demo 脚本执行 exit 0。
- 〔P0〕Chainlit 依赖进入 `pyproject.toml` 与 `uv.lock` 更新同笔，且当笔全量回归绿；v13 E4 复跑绿。
- 〔P0〕`v14/regression/` sweep 上线（发现 `v14` 下全部 `test_*.py` 串行，required 零容忍、probe 照 skip 语义）。

### G4 真 provider

范围：DeepSeek 判断面产品化（provider 进程分离）+ 多轮 + compaction 只追加 + economy 整数记账（§4.4）。
gate 验收（写死）：
- 〔P0〕`v14/provider/test_deepseek.py`（required，FakeLLM 确定性部分）exit 0：同 judgment 合同双实现断言；provider 进程能力闭集（可 litellm，禁 DB/beat/写盘）；attempt 记账（start_attempt 同事务插 started+attempt 1；attempt 2 不换 effect 行；**第 3 次无 receipt 不插 attempt 行、effect→failed(attempt_exhausted)、attempt 行数保持 2**）；**错误码乘积表五行逐行断言**（ok/timeout/transport_error/content_invalid/budget_exceeded）；`effect/failed/sql` 终态证据事件入投影；投影按 kind 丢弃 attempt 事件；判断错误码闭集五值同表映射、FakeLLM 与 provider 不得各增码；reconcile=独立动作（新 judgment_id）非 EFF-5 reconcile。
- 〔P0〕多轮 gate（required）exit 0：≥2 轮会话含一次中途 kill 续跑，断言按 V14-EFF-6 适用面（不宣称未提交 receipt 窗口 A/B 等价）。
- 〔P0〕compaction/economy gate（required）exit 0：compact 后可重放 compact 前全部历史；判断行 usage 整数记账。
- 〔P0〕**release evidence**：里程碑关闭前有一次真 DeepSeek smoke 工件入库——含模型 ID、usage、错误映射，且**无密钥**入库。
- 〔P1〕真 API smoke 脚本（optional probe 语义：无凭证 = 2，如实呈报）。

### G5 基准对标

范围：任务套件 + plumbing/live 两层 + 对照报告（§5）。
gate 验收（写死）：
- 〔P0〕`v14/bench/test_bench.py`（required）exit 0：四任务 + ≥1 多轮任务，plumbing 层全判定（check 由评测器执行、退出 0 + protected 字节不变）。
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
4. **不做任意 shell 执行**：G2 exec 是闭集命令执行器（execve + 枚举动词 + 类型化参数 + 受信二进制 + 进程边界封死）；任意 shell 待后续版本有真隔离机制（容器级）再开。
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

## 附录 B. 轮 4 → 轮 5 修订对照（oracle 双裁合并裁决 R1..R19 落点）

| # | 轮 4 裁决项（R） | 轮 5 落点 |
|---|---|---|
| R1 | 双序键合一 | V14-EFF-2 删「全序键=intent (session_id,seq)」：效果身份只=effect_id；intent 事件位置仅表「IO 前日志已提交」；EFF-4 工作区重放只按 workspace_effect_seq 升序（仅 mutating 且 claim 成功的 effect 拥有）；INV-3 命题 B 折叠基底=会话创建时冻结的 workspace tree hash |
| R2 | lease fencing 终版 | V14-EFF-1（claimed→started 与「允许开始外部 IO」合并为一条条件更新，0 行→零 IO）+ V14-EFF-2（reclaim 仅 state=claimed ∧ lease_until≤now ∧ 调用者持 workspace advisory 锁；resume_probe/reconcile 均单胜者 CAS 败者零 IO；receipt 携带 fencing generation 不一致→拒绝落库状态不变，INV-1 envelope） |
| R3 | 基线不符三套终态合一 | V14-EFF-1 转移表 planned→claimed 拆互斥三行（时间过期→failed+expired；grant 撤销/过期→failed+expired 独立审计 kind+释放名额；基线不符→判别式）；V14-EFF-5 判别式=可计算谓词（从冻结 per-path 基线按 seq 升序折叠更小 seq 成功 tool diff ∪ reconcile/diff；全等→failed(stale) 不 degraded；任一不等→degraded，未 rename failed/已 IO unknown；进 degraded 未分配 seq 则同事务分配）；EFF-3 case3 改「调判别式，判别式之外禁记 stale」；rename 后目标态校验/父目录 fsync 失败→unknown 再跑判别式禁自动再 rename；APPR-5 拆两检查点（claim CAS 见撤销走 R3 表零 IO；receipt 接受见撤销不回滚 IO 终态按 receipt/EFF-5） |
| R4 | write/edit 准入合一 | V14-TOOL-1（命中 grant→建 approved+插 planned；未命中→准入拒绝零 proposal 零 effect，无逐次人批）+ V14-TOOL-6（单一准入路径：exec mutating 总建 requested；await_approval 仅 requested）+ V14-TOOL-3（三步改「提案构建→仅 requested 才等待→claim/apply」）+ §0 ARCH-6 差异表加「审批门控」行 + G1 夹具（等待断言用 exec requested 夹具；write/edit 夹具盖拒绝不建行+grant 命中直入 claim） |
| R5 | 命题 A 比较面独立 | V14-INV-3 命题 A 改独立语义子流（允许 kind 闭集六类；resume_probe/attempt/lease reclaim 不入 A）+ V14-HARN-4（两比较面：INV-4 双壳用 §4.3 全流、A 用子流；A 允许表是 P0 比较面台账不能扩）+ G3 窗 1 断言（子流逐行相等+tool/result 规范 diff 与 workspace_effect_seq 相同） |
| R6 | grant 签发封死 | V14-APPR-6（issue_grant/revoke_grant/approve/deny/expire/reconcile 全部 REVOKE FROM PUBLIC+从 harness/service role REVOKE，EXECUTE 仅授认证 approver 角色；签发不收 principal/session_id/now/proposal_id，granting_principal 取当前认证 principal；会话绑定=认证时写连接不可变属性，不读调用方可写 GUC）+ V14-APPR-5（grant 行除 revoked_at 空→非空外禁 UPDATE；拒签谓词=workspace_mode=mutating 的 exec 一律拒签且总建 requested，勿只字符串等于 bash） |
| R7 | resume_probe 观测完备 | V14-EFF-3（per-path 观测={exists,file_type,mode,sha256}，symlink 一律拒；resume_probe 携带临时文件内容摘要/类型/mode 受信 worker 产，SQL 验证与 proposal diff new_sha256/new_mode 一致才许 replay；case1/2 比较条件按全观测写死）+ V14-TOOL-2（diff 拆 old_mode/new_mode，字段集七项）+ INV-1 第 4 类载荷定义 |
| R8 | 外部写入 TOCTOU 声明式 | V14-EFF-4（写死前提：workspace apply 期间无受控面外写入是前置条件，违反=未定义行为；检测点=receipt 验证与下一 effect 基线判别式入 degraded；不承诺文件系统级防并发，只在受控面内防） |
| R9 | digest 拆名与比较面 | V14-TOOL-2（diff_digest=字段集保序规范 UTF-8 文本编码的 sha256，送入 jsonb 之前计算，不用 jsonb::text）+ V14-INV-1（payload_digest 预映像=kind/effect_id/attempt_id/status/exit_code/diff_digest，status 已按 exit_code 规范化）+ V14-HARN-4（payload_digest 派生字段从双壳比较面排除，另设独立 digest 正确性 gate；workspace_effect_seq 每 workspace 从 1 单调、同构操作两壳同值、原样入比较面）+ G1 独立 digest gate |
| R10 | provider/read-only 出生边+错误码乘积表 | V14-EFF-1 出生三分细化（provider：start_attempt 同事务插 started+attempt 1、attempt 2 不换 effect 行、第 3 次不插行→failed(attempt_exhausted)+effect/failed/sql 入投影；read-only：提交态=claimed、无 receipt 至多 1 次再开 attempt 同 effect 保持 started、仍无→同一 attempt_exhausted 路径；mutating 无 attempt 行）+ V14-EFF-6 错误码乘积表（ok→judgment 一代+消耗 attempt+succeeded；timeout/transport_error→不写成功 judgment+记已用 attempt+保持 started；content_invalid/budget_exceeded→错误 judgment 行+停止+failed）+ V14-EFF-5（「新 judgment 世代」改名独立动作（新 judgment_id）非 reconcile、永不进 unknown）+ V14-EFF-4（advisory 锁仅 mutating 出生类取得）+ G4 乘积表五行断言 |
| R11 | exec proposal 双摘要型 | V14-APPR-1（write/edit 摘要含规范 diff；exec 摘要=verb+类型化 argv+envp 闭集，diff 仅在事后 tool/result）+ V14-TOOL-4（动词目录裁决 run-test=read_only、build=mutating 进合同附录）+ V14-TOOL-1（edit 提案构建要求目标存在且非 symlink，否则拒绝不建 effect，与 write create-only 配对） |
| R12 | jsonb 可行性 | V14-HARN-4（封闭检查=标量匹配 RFC3339 或纯数字 epoch 且键不在 volatile 表→gate 失败，字符串模式；volatile 表补 effective_now；digest 规范化=显式保序文本编码（R9）；投影遍历序冻结=jsonb 自身键序、数组从左到右） |
| R13 | stdout 确定性 | G3 `test_dual_shell.py` 夹具义务：exec 输出用冻结字节（build/run-test 的 stdout/stderr 预先固化） |
| R14 | 屏障量化+expire_due+锁等待 | V14-EFF-4（屏障量化：存在未终态 started/unknown→其他 mutating 一律不得 claim/apply/reclaim，更低 seq 已 claimed 者保持 claimed 等终态后再判别；取锁=pg_try_advisory_lock 拿不到→结束当前事务留 planned/claimed 下一拍再试；持锁连接专属于该次 apply IO 期间不归还池；expire_due 写死：仅 DB 时钟、无参数、幂等、requested 到期→expired 不建 effect、approved+planned 到期→R3 时间行） |
| R15 | advisory 锁键命名空间 | V14-EFF-4（workspace_id 映射到 v14 专用 bigint namespace，避免与 v13 既有 pg_advisory_lock 键空间相撞） |
| R16 | proposal 预读边界 | V14-EFF-2 范围写明：proposal preflight read 不属于 effect IO（只读、读 lease 保护、不建 effect）；apply 阶段按 EFF-3 重算基线为准 |
| R17 | 威胁模型声明 | §0 新增 V14-ARCH-7：carrier=trusted-but-crashable（可崩溃不可恶意）；worker 合同+SQL 结构性验证回执绑定与映射；resume_probe 观测来自受信 worker；对抗性载体完整性加固=§9 范围外（新增第 9 条） |
| R18 | case2 重放细节 | V14-EFF-3（临时文件存活至 effect 终态、清理仅在 receipt 提交或 reconcile 完成后；probe 发现 temp 不存在或任一路径 symlink→整 effect unknown 零 rename；case2 重放必须持 workspace advisory 锁+先跑判别式+只做剩余 rename；receipt 接受谓词=每 path old_sha256 等于锁内基线 ∧ exit_code/status 符合 INV-1 映射；exec 已跑且不一致→unknown 不重试） |
| R19 | 前缀表完备 | V14-HARN-4 代理键 allowlist：八类 id 各自独立前缀（$s/$ev/$ef/$j/$p/$at/$g/$w），遍历序冻结 |
