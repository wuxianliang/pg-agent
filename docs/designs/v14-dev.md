# PG 原生 Pi 对标 Coding Agent（v14）开发规范

> 状态：草稿第 4 版，待 oracle 终审轮 4（用户批准的最后一轮）。冻结标准：评审至 0 P0 / 0 P1。
> 撰写日期：2026-09-28（第 1 版 `e97f4ce`；第 2 版 `e854e04`；第 3 版 `3af3dc6`）。工作分支：`v14-dev`。
> 修订记录：第 2 版吸收轮 1 双裁（4+3 P0）与父循环两裁决；第 3 版吸收轮 2 双裁（4+5 P0）裁决 A..M；第 4 版吸收轮 3 双裁合并裁决 N1..N20（用户批准加轮 4，终稿预算），全部落正文。
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

### 0.4 对标面定义与差异登记

**V14-ARCH-5**〔P1〕对标成立的三件事：① 工具面覆盖 pi coding agent 常用集（read/write/edit/bash/glob/grep）；② REPL 体验：Chainlit 窗口可对话驱动、可断线重连、历史完整；③ 基准：§5 任务套件上产出 v14 vs pi 对照报告。不承诺 TUI 视觉复刻、不承诺 pi 插件生态兼容。检查：G3/G5 gate 与对照报告。

**V14-ARCH-6**〔P1〕对标差异登记表（对 pi 语义的显式偏差，逐条列出，新增须 bump）：

| 差异点 | pi 语义 | v14 语义 | 理由 |
|---|---|---|---|
| `write` | 覆盖或创建 | **create-only**：目标已存在即拒绝；覆盖一律走 `edit` | mutating 效果可解释性（diff 恒为创建形态，V14-TOOL-2） |

检查：G1 gate（write create-only 负例）；设计评审对照本表。

## 1. 不可妥协的不变量（V14-INV-1..6）

> 本节原文照录父循环裁决，是全部后续条款的上位约束。任何 stage 设计、实现、gate 与本节冲突即无效。

**V14-INV-1 判断零外置（四类提交闭集）**〔P0〕一切决策（下一步做什么、何时结束、调用什么工具、是否需要模型判断）由 SQL 面产出（advance / 判断请求拼装与入队全在库内）；LLM 调用只是判断请求的数据面——问题由 SQL 面拼装、回答落 judgment 记录。**执法语义（四类提交闭集）**：harness 向库内提交的输入只许四类，每类只能调用**已登记 SQL 函数**（v13 既有 + v14 迁移新建），禁止裸 DML、禁止 harness 发 `pg_notify`：

1. **用户文本**（submit 入口）；
2. **审批决定**（approve | deny | reconcile 的标量参数；签名面见 V14-APPR-2/3——不收 session_id/proposal_id/principal/now，会话来自认证连接绑定）；
3. **判断答案**（FakeLLM 与真 provider 的回答文本同形，落 judgment；错误码闭集见 V14-HARN-7）；
4. **工具回执**（统一 envelope：`kind`、`effect_id`、`attempt_id`、`status`、`payload_digest`、`exit_code`（可空；exec 类必填）、`stdout`、`stderr`、`diff`——SQL 验证绑定与状态后落库；driver 仅 opaque 转发，禁止解析回执推导下一步）。**kind 闭集 = `tool | resume_probe`**；tool 回执 **status 闭集 = `succeeded | failed`**；resume_probe 载荷仅 `{path, hash|EMPTY, temp_exists}`，SQL 裁 `settle | replay | unknown`（V14-EFF-3）。**status↔exit_code 映射写死**：exec 类 envelope `exit_code=0 → succeeded`、`exit_code≠0 → failed`；非 exec 类 `exit_code=null`；`payload_digest` 预映像含 `exit_code`。

**无参已登记函数**（`advance` / `next_beat` / `expire_due`）**不是第五类输入**——它们没有参数面；任何新入口的参数面禁判断内容、principal、now、session_id。

人批与模型回答同属外部判断数据面：请求由 SQL 产出、答复落库；harness 不代批、不代答、不拼装。检查：G3 source gate（INV-5 扫描 + import 黑名单 + envelope 仅经登记函数断言）+ 判断面 gate 回归。

**V14-INV-2 beat 序列是数据**〔P0〕beat 序列（judge/parse/advance/claim/tool/llm/finish 一类的拍结构）是库内数据，不是代码控制流。advance 决定下一步，harness 仅执行。先例：`v13/pi_parity/test_pi_parity.py:66` 的 `GOLDEN_SEQUENCE`（canonical phases）与 `v13/read_tools/test_read_tools.py` / `v13/pi_ports/test_pi_ports.py` 的 ring 驱动。**相位定案**：assistant（模型）输出是**显式 canonical phase**（拍结构中的 `llm` 相），不是 `claim kind=llm`——按 pi_parity schema-v2 定案，本条为二选一歧义的落死。检查：G3 gate 断言 beat 拍落 events 表且驱动模块无硬编码序列分支、llm 拍为独立相位。

**V14-INV-3 会话可弃（双命题，适用面受限于 V14-EFF-6）**〔P0〕kill harness → 重启 resume 的可操作承诺收窄为两个命题，分别断言：

- **命题 A（事件面）**：已提交事件的规范化投影（§4.3 算法）在「杀过」与「未杀」两条世界线上一致。
- **命题 B（工作区面）**：工作区终态 = 已提交 diff（成功 tool diff ∪ reconcile/diff，V14-EFF-5）依 `workspace_effect_seq` 全序的确定性重放结果。

**适用面（原句）**：FakeLLM 路径与已提交 receipt 的 provider 路径；bash unknown 未 reconcile 的窗口、provider 未提交 receipt 的窗口除外。bash `unknown` 场景只承诺**终态有定义**（可进人工 reconcile，V14-EFF-5），不承诺「与不杀一致」；未 reconcile 的 unknown 世界线不宣称命题 B。检查：G3 杀进程续跑 gate（两杀点，§6 G3）+ G4 kill gate 按 EFF-6 断言。

**V14-INV-4 双壳等价**〔P0〕Chainlit 驱动与脚本驱动同输入 → 同 events 流逐字节一致。比较面与投影算法**写死于 §4.3（V14-HARN-4）**：库内唯一 canonical 投影函数、代理键 allowlist、volatile 键表、服务端比较。比较面新增排除项不属于已冻结类别时必须 bump 本规范——偏差台账无权松动 P0 比较面。检查：G3 双壳等价 gate。

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

- **mutating**（write/edit、mutating bash 动词）：与 proposal 批准**同事务** INSERT 即 `planned`；proposal 被 deny/expire 的**不建 effect 行**。
- **read-only**（glob/grep 及 `workspace_mode=read_only` 动词）：**无 proposal**，SQL INSERT `planned` **同事务自动 `claimed`**；**不取 apply 锁、不分配 workspace_effect_seq**；`started` 无 receipt 时 SQL **至多再开 1 次 attempt**，仍无则 `failed`。
- **provider**：无 proposal、无锁、无 seq，attempt 语义全走 V14-EFF-6。
- **边界**：v13 既有 read 口岸保持 v13 语义，**不建 v14 effect**。

转移表：

| 转移 | 条件与方式 |
|---|---|
| → `planned` / `planned+claimed` | 按出生三分（上行） |
| `planned` → `claimed` | 单条条件 UPDATE：proposal=approved、effective_now 未过 expires_at、workspace 基线匹配；**同事务** proposal → `consumed`。**claim 谓词失败（含 approved 后 now≥expires_at 的过期悬挂）**：同事务 effect → `failed`、proposal → **`expired`**（过期终态名单一选死）、释放 mutating 名额（V14-APPR-4）、不 rename |
| `claimed` → `started` | 外部 IO 前**单独提交**（先例 TP-HUB-2）；锁生命周期见 V14-EFF-4 |
| `started` → `succeeded \| failed` | 仅当带 receipt（INV-1 第 4 类 envelope；resume_probe 裁决见 EFF-3） |
| `started` → `failed(attempt_exhausted)` | **SQL 侧终结转移**：attempt_count=2 且第 3 次需求到达时由 SQL 幂等生成；产生 kind=`effect/failed/sql` 终态证据事件且**入投影**（V14-EFF-6） |
| `started`（resume，无 receipt） | 按出生类分流：bash → `unknown` 禁自动重试（EFF-5）；write/edit → 三分法（EFF-3）；provider → 不进 unknown，新记 attempt（EFF-6）；read-only → 至多再开 1 次 attempt 仍无则 `failed` |
| `unknown` → `succeeded \| failed` | 仅 reconcile SQL（EFF-5） |

检查：G1 起各 gate 断言合法转移集（非法转移负例）+ 过期悬挂路径 + 劲竭终结事件。

**V14-EFF-2 intent 行、效果键与 claim lease**〔P0〕任何 **v14 effect** 的外部 IO 发生前，effect intent 行必须已提交入库（v13 既有口岸不在本条范围，见 EFF-1 出生三分边界）；**全序键 = intent 事件的 `(session_id, seq)`**（效果身份与顺序锚点）。claim 带 `lease_owner` / `lease_until`（now 取 V14-APPR-3 的 effective_now）。**lease 过期语义（写死）**：`claimed` 且过期 → **仍为 `claimed`**，仅 CAS 改 `lease_owner` / `lease_until`（reclaim）；proposal 保持 `consumed`；seq 不变；**禁新建 effect 行**。检查：G1 gate（intent 先于 IO、lease 过期 CAS reclaim 正/负例、reclaim 不新建行）。

**V14-EFF-3 write/edit 原子写与 resume 三分法（终版顺序）**〔P0〕apply 顺序写死：**取锁 → 锁内重算全部受影响路径基线 → 任一不匹配 = stale/fail 禁 rename → 写临时文件 → fsync 临时文件 → rename → fsync 父目录 → 校验目标态（exists/hash/mode；该校验不替代锁内基线校验，两者都在）→ 才许提交 receipt**。临时文件命名规范与残留清理在 G1 实现冻结；**目标为 symlink 一律拒绝**。resume 三分法（`started` 无 receipt 时，由 **resume_probe**（INV-1 第 4 类，kind=`resume_probe`）驱动：driver opaque 提交观测 `{path, hash|EMPTY, temp_exists}`，SQL 裁决）：

1. 目标哈希 = 目标态 → **结算原 effect，不重放**（case1）；
2. 目标哈希 = 基线（文件不存在时用**冻结哨兵 `EMPTY`**）→ 从临时文件重放（case2）；
3. 都不是 → `unknown`，**禁止覆盖**（case3）。

**多路径一次性分类（整 effect 粒度）**：任一 path = case3 → **整 effect `unknown`**，不再 rename 其余 path；全 case1 → 不重放、结算 `succeeded`；仅 case1+case2 → 只重放 case2 后结算 `succeeded`；**禁逐路径各自 succeeded**。成功后提交 `tool/result`（含 diff 载荷，V14-TOOL-2）。检查：G3 窗 1 杀点 gate；G1 原子写正/负例（symlink 拒绝、父目录 fsync、残留清理、多路径三分各形态）。

**V14-EFF-4 workspace 全序、排他 apply 锁与屏障**〔P0〕每个 workspace 有 `workspace_id`。**排他锁**：会话级 advisory 锁（`pg_advisory_lock(workspace_id)` 类）；在 claim 阶段取得，**生命周期跨 `claimed→started` 的 COMMIT，直至 apply 结束或会话死**；所有受控 writer（write/edit、mutating bash 动词）用同一把锁（锁覆盖外部进程运行期间——受控 writer 串行是设计语义，V14-TOOL-4）。持锁期间**重算受影响路径基线**，任一不匹配按 V14-EFF-5 判别式处置，禁止 rename。**workspace_effect_seq**：在 claim 的已提交事务内分配，不可变（resume/reconcile 复用原 seq，不重排）；INV-3 命题 B 的重放全序 = `workspace_effect_seq` 升序。**workspace 屏障**：存在未终态 `started`/`unknown` effect 时，**禁止更高 seq 的 mutating effect**（跨 session 执法）；lease reclaim 不绕过屏障；`unknown` 即标 workspace **blocked**（并按 EFF-5 判别式可能进 degraded）。**外部写入检测**：受控面外的写入一经检测到，按 EFF-5 判别式进 degraded，拒绝后续 mutating effect 直到 reconcile。检查：G1 gate（锁争用/屏障跨 session/reclaim 不绕屏障/degraded 负例）+ G3 命题 B 断言。

**V14-EFF-5 bash unknown、degraded 判别式与人工 reconcile**〔P0〕bash `started` 无 receipt（超时 kill 或进程被杀）→ `unknown`，**禁止自动重试**；**禁止合成 failed/succeeded receipt**；输出超限 = 带 receipt 的 `failed`（不变，TOOL-4）。

**degraded 判别式（写死）**：锁内基线不符时——观测哈希可被某更小 seq 的已提交受控 diff 解释 → effect `failed(stale)`，workspace **不 degraded**；解释不了 → workspace **degraded**（本次未 rename 则 effect `failed`；已 IO 则 `unknown`）。

**degraded 唯一出口** = 与 unknown reconcile **同一 reconcile SQL**（principal 规则同 V14-APPR-6）：追加不可变 **reconcile/diff**（同一 TOOL-2 六字段格式，seq 复用原 effect）、清 degraded、此后基线 = 该 per-path 观测态；**observed 态由受信 SQL/worker 读取校验，禁调用方提交哈希**。`unknown → succeeded|failed` 仅经此 SQL：写 `reconciled_outcome` + `observed_hash`，后续 effect 基线改用 `observed_hash`。reconcile 决定走 INV-1 第 2 类提交，留痕 events（先例目录 `v8/reconcile/`）。

**命题 B 重放输入** = 成功 tool diff ∪ reconcile/diff，按 seq 升序；**未 reconcile 的 unknown 世界线不宣称命题 B**。provider 行只引 EFF-6：不取锁、不分配 seq、不进 unknown。检查：G3 窗 2 杀点 gate（unknown + reconcile + observed_hash 生效断言）+ G1 判别式两分支正/负例。

**V14-EFF-6 provider at-least-once 与 INV-3 适用面**〔P0〕provider effect `started` 无 receipt：**不转 unknown**——`start_attempt` 由 **SQL 执行**；at-least-once 现实语义（重复计费是已声明语义）；**同一 effect 最多 2 次 attempt**。**第 3 次需求到达**：SQL **不插第 3 条 attempt 行**、effect → `failed(attempt_exhausted)`（EFF-1 SQL 侧终结转移，幂等）、**attempt 行数保持 2**（G4 断言）。attempt 事件**不属** INV-4 规范化投影比较面（投影按 kind 丢弃 attempt 事件，V14-HARN-4）。显式 reconcile provider effect 产生**新 judgment 世代**，不承诺与未杀世界线投影一致。**INV-3 命题 A/B 等价仅适用于 FakeLLM 路径与已提交 receipt 的 provider 路径**；G4 kill gate 不得把 provider 未提交 receipt 窗口宣称为 A/B 等价。检查：G4 gate（attempt 上限/failed/attempt 行数=2/第 3 次不插行/新 judgment 世代断言）。

### 3.2 write/edit 口岸（G1）

**V14-TOOL-1**〔P0〕write/edit 是 mutating 口岸：结果改变工作区文件系统状态。mutating 请求必须走审批环（§3.3）且经 V14-EFF 效果协议执行；未获批的 mutating 请求不得产生文件系统效果，拒绝路径 events 记录完整（deny/expire 不建 effect 行，EFF-1）。**write 语义 = create-only**：目标已存在即拒绝（对 pi write 语义的显式偏差，登记 §0 V14-ARCH-6）；覆盖一律走 edit。检查：G1 gate（拒绝路径断言工作区字节零变化 + write create-only 负例）。

**V14-TOOL-2 diff 协议（单格式 + 规范编码终版）**〔P0〕diff 只有一种格式：每 path 记 `{old_exists, old_sha256, new_exists, new_sha256, mode, payload 编码}`——payload 编码 = 文本 utf8 / 二进制 base64；覆盖创建（old_exists=false）、删除（new_exists=false）、二进制、symlink 拒绝策略。**禁止** old/new 成对与 unified diff 二选一的旧措辞。write 的 diff = old 全空（old_exists=false）。**规范编码（写死）**：路径按**相对路径字节序**排序；缺失哈希 = **JSON null**；payload 含 NUL 或非法 UTF-8 → base64，否则 utf8；键序 = 本条字段序；**payload_digest = 该规范 jsonb 的 sha256（预映像不含 volatile 键）**。diff 是 events 流的一部分（落 `tool/result` 载荷），供审批渲染、INV-3 命题 B 重放与 gate 断言。检查：G1 gate 对 diff 载荷结构断言（含创建/删除/二进制/symlink 负例 + 规范编码逐项：排序/null/base64 判定/digest 预映像）。

**V14-TOOL-3**〔P0〕write/edit 执行拆三步，各守 claim 纪律：① **只读 proposal 构建（三段式）**：短事务登记只读 lease 并提交 → **事务外**读文件 → 新事务写 proposal 释放 lease（**文件 IO 永不在打开的 DB 事务内**，v8 不变量 4）；② **审批等待**（游标停 `await_approval`，不持任何 claim，V14-APPR-4）；③ **apply**（取 workspace 排他锁（EFF-4）→ claim effect → 原子写（EFF-3）→ complete）。grant 命中已 approved 的请求跳过等待直入 claim（V14-APPR-5）。检查：G1 gate 三步各断言 claim 生命周期与三段构建顺序。

### 3.3 审批协议（V14-APPR，G1 交付状态机与批准命令；G2 只加 bash 策略）

**V14-APPR-1**〔P0〕proposal 不可变、一次构建。proposal 摘要（被批准的对象）字段冻结：合同版本、generation、工具名、完整参数、cwd、受控环境标识、workspace 基线哈希、规范化 diff（mutating 类）、有效期（expires_at）、**可空 `grant_id`（命中 grant 时，入摘要哈希）**。检查：G1 gate 摘要字段完备性断言（含 grant_id 入哈希）。

**V14-APPR-2 批准与消费（谓词定位 + 单次消费 + 竞争审计）**〔P0〕批准只批摘要（哈希锚定）。**批准输入禁止携带代理键字面量**（proposal_id、session_id 等）：approve/deny/expire/reconcile **不收 session_id / proposal_id / principal / now**，目标用谓词选（如「本会话唯一 requested proposal」，会话来自**认证连接绑定**），命中非唯一即拒绝。**条件更新写死**：approve/deny/expire 用 `WHERE state=requested` 条件更新，胜负各写**竞争胜负审计事件**。消费：`planned→claimed` 与 `proposal approved→consumed` 同事务单次消费（EFF-1）；执行 claim 时 CAS 重验（摘要哈希一致、状态、未过期、workspace 基线仍匹配、grant 未撤销未过期（APPR-5）），任一不符即拒绝并留痕（过期悬挂处置见 EFF-1）。检查：G1 gate（谓词定位非唯一负例/重放/篡改/基线漂移负例/竞争胜负审计事件断言）。

**V14-APPR-3 effective_now（DB 时钟；test-only 注入）**〔P0〕生产 approve/deny/expire/reconcile **不接受调用方 now、不读调用方可写会话变量**；effective_now 来自 DB 时钟。仅**测试专用角色**经隔离 test-only 入口注入 now。所有 CAS 用同一 effective_now 在同事务检查 `expires_at`。检查：G1 gate（生产入口无 now 参数 source 断言 + test-only 注入正例 + 共享 CAS 时钟断言）。

**V14-APPR-4 等待与串行（单名额在请求创建时执法）**〔P0〕proposal 状态机 `requested → approved | denied | expired`（三择终态）+ `approved → consumed`（与 effect claim 同事务）+ `approved → expired`（claim 谓词失败时，EFF-1 过期悬挂；expired 为过期终态**唯一**落点）。超时判定用 APPR-3 的 effective_now。等待期游标停 `await_approval`：不持 claim、不占 beat 前进位；批准后重新走 V14-EFF claim。**mutating 单名额执法时点 = 请求创建时**：已存在 requested proposal、未消费 approved proposal、或未终态 mutating effect → 新 mutating 请求**拒绝并留痕**（per-session 部分唯一索引或等价 SQL 约束实现，写死为「存在未终态 proposal 时禁止创建第二个」）。deny/过期/失败路径**释放名额**。检查：G1 gate（创建时拒绝负例/名额释放/等待期 beat 推进）。

**V14-APPR-5 grant 字段全集与命中规则（终版）**〔P0〕grant 行字段冻结：`grant_id / granting_principal / session_id / workspace_id / tool_set / argument_schema / cwd 根 / contract_version / generation / issued_at / expires_at / revoked_at`。**tool_set 含 bash → 拒绝签发**（bash 逐次人批，不接受 grant）。**grant 命中 = 请求创建事务内的内部动作**（非独立入口）：命中即在同事务生成不可变 proposal 并由 SQL 转 `approved`（principal 记录 = granting_principal），EXECUTE 权限对 harness 与 service role 一律 REVOKE；approve/deny/expire/revoke 全部 REVOKE FROM service role。每次命中仍单次消费（APPR-2）；命中已 approved 的请求游标跳过 `await_approval` 直入 claim。**命中合取（写死）**：工具名 ∈ tool_set ∧ 每受影响相对路径匹配 glob ∧ cwd 在 grant 根下 ∧ workspace_id/session_id/contract_version/generation 相等 ∧ 未撤销未过期 ∧ 非路径标量过 argument_schema；**正文/diff/哈希不参与比较**。**claim 时同事务重验** grant revoked_at + expires：已撤销 → effect `failed`、释放名额，**不回滚已 started 的 IO**（其终态走 EFF-5 判别式）。模式闭集 = 工具名 + 相对路径 glob。签发/撤销/越界负例进 `test_approval`。检查：G1 gate（字段完备/签发/撤销/越界/bash 拒签发/命中合取逐项/内部动作 + REVOKE 断言/claim 时重验两分支/跳过等待直入 claim）。

**V14-APPR-6 principal（DB 认证，fail closed）**〔P0〕审批函数**不接受 principal 参数**。生产路径须有与实际 approver 一一对应的 **DB 认证 principal**；共享 service role 不得执行审批（APPR-5 的 REVOKE 面是执法手段）；无法映射即 fail closed（拒绝并留痕）。Chainlit 部署的身份映射 = 受信连接 / 角色属性。principal 写 events。检查：G1 gate（principal 映射断言 + service role 拒绝 + 无法映射 fail-closed 负例）。

**V14-APPR-7 测试纪律**〔P0〕禁止直改审批/effect 状态表；approve/deny/expire/reconcile 一律走产品 SQL 命令；时钟注入仅经 APPR-3 的 test-only 入口。检查：G1 起全部审批相关 gate（source 断言无裸 DML）。

### 3.4 bash/glob/grep 执行面（G2，bash=闭集命令执行器）

**V14-TOOL-4 闭集命令执行器（进程边界封死）**〔P0〕执行方式 = `execve(动词目录固定可执行文件绝对路径 + 版本摘要, argv 数组)`——禁止 `shell=True`、禁止 `sh -c`、禁止任何字符串拼接执行。**verb executable = digest 校验的受信二进制，禁脚本、禁 shebang**；verb 本体与其子进程树禁调 shell/解释器（source gate 扫 `sh -c` / `bash -c` / `shell=True` / `os.system` / `os.popen` / `create_subprocess_shell`）。argv 段只有两种：目录固定字面量，或**类型化参数**（enum / int / bool / 相对路径闭集；路径拒绝对路径、`..`、NUL）。**execve 的 envp = 闭集**（空或合同点名键），禁止继承调用方环境。每个 verb 声明 `workspace_mode`：`read_only` | `mutating`；**未声明 workspace_mode 即拒绝执行**。**mutating 动词与 write/edit 共享同一把 apply 锁与同一状态图**（EFF-4；锁覆盖外部进程运行期间——受控 writer 串行是设计语义）；started 前锁内基线重算；seq 在 claim 已提交事务分配；receipt 丢失 → `unknown` 阻塞 workspace（EFF-5）。**路径解析**：从 workspace root dirfd 逐级 no-follow（openat/renameat、`RESOLVE_BENEATH` 语义），任一父分量是 symlink 即拒。**超时 kill 整个进程组**。**初始动词目录恰 = {run-test, build}**（目录内容进合同 v2 附录作为数据）。围栏：工作区根约束、超时、输出上限——**输出超限 = effect failed，不是截断成功**。必测负例：参数含 shell 元字符时子进程 argv 逐字节等于该值且被拒或仅作字面量；**verb 内部重解释 argv；父目录 symlink 越界；检查后替换（TOCTOU）竞态**；**bash×write 并发/kill/基线漂移**。加动词 = 合同面变更（§2.3）。任意 shell 整体移出 v14 范围（§9）。检查：G2 gate（上述全部正/负例；source 断言）。

**V14-TOOL-5**〔P0〕glob/grep 是只读口岸：**输入、结果与错误码闭集**，围栏与既有 read 口岸同级（TP-WIRE / TP-FS 纪律），无审批环；effect 走 EFF-1 出生三分的 read-only 分支（无 proposal、自动 claimed、无锁无 seq、至多 1 次重试）。检查：G2 gate（闭集与围栏负例 + read-only 出生路径断言）。

**V14-TOOL-6**〔P0〕权限落 govern / human route，**四条审批路径拆死**：① **默认拒**——未签发 grant 的非 bash mutating 请求在**准入时拒绝，不建 proposal**；② **批过**——proposal → `approved`（人批或 grant 命中转 approved）；③ **驳回**——显式 deny → `denied`；④ **超时**——无人动作到 expires_at → `expired`。bash（mutating）**总是建 requested proposal、不自动批**（无人动作到 expires_at → expired；显式 deny → denied）。审批请求与决定经 SQL 面留痕；human route 待审队列可被第二壳观察（UI 只是渲染，V14-ARCH-3）。检查：G2 gate（四路径 events 与文件系统效果断言）。

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

### 4.3 双壳等价：比较面与投影算法（库内 canonical，写死）

**V14-HARN-4**〔P0〕INV-4 的完整算法：

1. **同输入协议**：两壳各自**新会话、新工作区**，喂同输入序列；输入含批准——批准作为 SQL 命令序列经 **govern 入口**提交，无旁路（V14-APPR-7）；**双壳使用同一测试 principal**；两 principal 越权负例另行单测（不进等价 gate）。
2. **同入口**：两壳驱动**同一组 SQL 入口**（submit / approve / …）；seq 由 SQL 分配，客户端不造序。
3. **canonical 投影（库内唯一函数）**：投影函数在**库内**实现（递归 jsonb 遍历），禁止客户端拼串。归一规则：
   - **代理键 allowlist（写死）**：`session_id / event_id / effect_id / judgment_id / proposal_id / attempt_id / grant_id / workspace_id` 及递归出现的同值——按首次出现顺序替换为 `$s1 / $e1 / $j1 / $w1 …`，同值同替换、跨行一致；
   - **volatile metadata 键表（与时间分开，写死）**：`ts / wall_time / created_at / pid / lsn / expires_at / started_at / finished_at / duration_ms / elapsed_ms / lease_until / lease_owner / issued_at / revoked_at` → 类型占位符；
   - **workspace 根 → `$ws`**；事件内文件路径一律以**相对根形式**存储；
   - **attempt 事件按 kind 丢弃**（不属投影比较面，EFF-6）；
   - **封闭性执法**：投影中出现未列名的 `*_at / *_ms / *_until / *_pid / *_lsn`、**timestamptz 型标量**、绝对路径、未识别 uuid → **gate 失败**，新增类别必须 bump 本规范（偏差台账无权松动）。**uuid 规则仅作用于整个 jsonb 标量值 = uuid 形**（对 stdout/stderr/diff 等文本载荷不做子串扫描）；**字符串先做 `$ws` 前缀替换，替换后仍残留绝对路径才失败**；
   - **比较（写死）**：每流按 `(session_id, seq)` **ORDER BY seq** 后投影 `::text`，逐行相等（服务端执行）。
4. 批准输入禁携带代理键字面量（V14-APPR-2）。

检查：G3 `test_dual_shell.py`。

**V14-HARN-5**〔P0〕psql demo 收窄为 **submit/observe demo**：一条纯 psql 路径演示「SQL 命令提交输入 + `LISTEN v14_wake` 观察事件流」，证明载体无关性；不宣称「全程 psql 驱动 agent 完成 mutating 任务」。demo 脚本入库（`v14/harness/`）。检查：G3 gate（psql 执行 demo 退出 0 + 事件断言）。

**V14-HARN-6**〔P0〕harness 薄度执法（INV-1/INV-5 的 gate 细则）：per-file 决策点计数（INV-5 上限表）；import 前缀黑名单（INV-5 六前缀）；worker 与 provider 能力协议断言（INV-5）。检查：G3 `test_thin.py`；G4 provider 能力 gate。

### 4.4 真 provider、多轮与 compaction（G4）

**V14-HARN-7**〔P0〕DeepSeek 判断面产品化：provider 调用放 **`v14/provider/` 独立进程**——可 import litellm，禁开 DB 连接、禁 beat 循环、禁写工作区（INV-5 能力闭集）；回答由 driver 按 INV-1 第 3 类提交；与 FakeLLM 实现同一 judgment 合同（同参数/同落库/同错误闭集）；调用经 V14-EFF-6 attempt 记账（start_attempt 由 SQL 执行；第 3 次需求不插行、effect→failed、attempt 行数保持 2）。**判断错误码闭集（写死）**：`ok | timeout | transport_error | content_invalid | budget_exceeded`——FakeLLM 与 provider 同表映射，**不得各自增码**，增码须 bump 本规范。测试分层：确定性层永远 FakeLLM（外部 IO 不进事务，AGENTS.md / v8 不变量 4）；真 API smoke 属 release evidence（§6 分类）。检查：G4 gate（能力闭集 + attempt 断言 + 错误码闭集断言）+ release evidence 工件。

**V14-HARN-8**〔P0〕多轮：跨 turn 的会话连续性（上下文携带、目标推进、终态收敛）由库内状态承担，harness 重启不丢轮次。检查：G4 多轮 gate（含一次中途 kill 续跑，断言按 EFF-6 适用面）。

**V14-HARN-9**〔P0〕compaction **只追加**：compact 产生新 summary 事件，旧事件一律保留；事实完整 = 可重放 compact 前全部历史（沿用 v8 compact 语义，`docs/designs/v8-dev.md` §3.3；触发与产物落库）。economy 只记判断行 provider usage **整数**（input/output tokens 等），不记派生指标。检查：G4 gate（compact 后重放断言 + economy 整数记账断言）。

## 5. 基准对标（G5 冻结面）

### 5.1 任务形状

**V14-BENCH-1**〔P0〕借 PiG 任务形状（已核实：`PiG/evals/tasks/<name>/task.toml`，字段 `prompt` / `check`（shell 判定命令）/ `protected`（禁改文件）+ `files/`（任务工作区）），四任务：`add-json-flag` / `fix-off-by-one` / `rename-function` / `slow-build`。借用形状（v14 自建镜像目录），不依赖 PiG 仓库运行时；判定 = `check` 命令退出 0 且 `protected` 文件字节不变；**`check` 只由评测器执行，不经 agent 的 bash 面**（防判定面与工具面混淆）。检查：G5 gate。

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

范围：合同 v2 bump 与回填（§2.3）+ 效果协议（§3.1 全部，含出生三分、过期悬挂、lease reclaim、degraded 判别式）+ write/edit 口岸与三步执行（§3.2，write=create-only）+ diff 单格式与规范编码（V14-TOOL-2）+ 审批协议全套（§3.3，含 grant 字段全集与命中合取；自 G2 原计划**移入**）。
提交集合（枚举，见 V14-PROC-3）：**K**（内核提交：合同 bump 文档 + v14 迁移 SQL（含 contract_version/generation 回填列）+ 允许名单）→ **S**（实现提交：口岸、目录行、gate）。
gate 验收（写死）：
- 〔P0〕`v14/tools/test_tools_v2.py`（required）exit 0：EFF-1 转移表全路径（含出生三分 mutating 分支、过期悬挂 effect→failed+proposal→expired、SQL 侧劲竭终结事件）+ 非法转移负例；intent 先于 IO；lease CAS reclaim（仍 claimed、proposal 保持 consumed、seq 不变、禁新建行）；workspace 排他锁/屏障跨 session/reclaim 不绕屏障；write/edit 幸福路径 diff 单格式与规范编码逐项断言（字节序排序/null/base64 判定/payload_digest 预映像；创建/删除/二进制/symlink 拒绝）；多路径三分一次性分类（全 case1 / 1+2 / 含 case3 三形态）；三步执行 claim 生命周期与三段构建（文件 IO 不在打开事务内）；write create-only 负例；拒绝路径工作区字节零变化。
- 〔P0〕`v14/tools/test_approval.py`（required）exit 0：V14-APPR-1..7 全断言（摘要字段含 grant_id 入哈希/谓词定位非唯一负例/WHERE state=requested 条件更新与竞争胜负审计/单次消费 CAS/状态机含 approved→consumed 与 approved→expired/生产无 now 参数 + test-only 注入/请求创建时单名额执法与释放/等待期不持 claim/grant 字段全集 + 签发/撤销/越界 + bash 拒签发 + 命中合取逐项 + 内部动作 EXECUTE REVOKE（harness 与 service role）+ claim 时重验 revoked/expires 两分支 + 命中跳过等待直入 claim/principal 映射 fail-closed + service role 拒绝/无裸 DML）。
- 〔P0〕`v14/tools/test_contract_v2.py`（required）exit 0：contract-2 已 bump；v1 条款字节零改动；回填列默认值与既有 request 回填；v1 排队请求走 v1 handler + v2 新建请求两路径；无法解析绑定拒绝创建负例；`v13/**/*.sql` 零 diff。
- 〔P0〕v13 全量零回归（E4，required）。

### G2 执行面（只加 bash 策略与执行口岸）

范围：闭集命令执行器 bash（§3.4，进程边界封死）+ glob/grep 只读口岸（read-only 出生分支）+ govern/human route 审批环接线（四路径拆死；审批状态机已在 G1）。
gate 验收（写死）：
- 〔P0〕`v14/exec/test_exec.py`（required）exit 0：execve/无 shell（source 断言含六模式扫描：`sh -c`/`bash -c`/`shell=True`/`os.system`/`os.popen`/`create_subprocess_shell`）；verb executable digest 校验受信二进制（禁脚本/shebang）；envp 闭集（禁继承）；目录恰 = {run-test, build}；workspace_mode 声明执法（未声明拒绝）；类型化参数域负例；shell 元字符 argv 逐字节负例；verb 内部重解释 argv 负例；父目录 symlink 越界负例（no-follow/dirfd/RESOLVE_BENEATH 语义）；检查后替换（TOCTOU）竞态负例；超时 kill 整个进程组；glob/grep 输入/结果/错误码闭集与围栏负例 + read-only 出生路径（自动 claimed、无锁无 seq、至多 1 次重试 failed）；bash 围栏（越界/超时/超限=failed）负例；**bash mutating 与 write 共享锁/状态图：bash×write 并发、kill（receipt 丢失→unknown 阻塞）、基线漂移三组测试**。
- 〔P0〕`v14/exec/test_govern_route.py`（required）exit 0：四条审批路径拆死（准入拒绝不建 proposal / approved / denied / expired；bash 总是建 requested 不自动批）、审批命令经 SQL 面、留痕 events、human route 队列可由第二壳观察。
- 〔P0〕v13 全量零回归（E4）+ G1 gate 复跑绿。

### G3 harness MVP

范围：beat driver 提炼（§4.1）+ Chainlit 窗 + `v14_wake` LISTEN/NOTIFY 终版（§4.2）+ psql submit/observe demo（§4.3）+ 双壳等价 + 会话可弃（两杀点）+ 薄度执法。
gate 验收（写死）：
- 〔P0〕`v14/harness/test_resume.py`（required）exit 0：**SIGKILL 进程组**实证杀（非模拟），杀点为**确定性测试缝**：窗 1 = 阻塞在已提交 `started`、rename 之前；窗 2 = 阻塞在子进程 `execve` 之后、receipt 之前。进程组只含 driver 与其 worker/provider 子进程；数据库进程与测试控制器在组外。窗 1 → resume_probe 提交 + 三分法（V14-EFF-3）+ 命题 A/B 断言；窗 2 → unknown + 人工 reconcile 走通（V14-EFF-5，只断言终态有定义）。
- 〔P0〕`v14/harness/test_dual_shell.py`（required）exit 0：两壳（脚本壳 + Chainlit 壳——经 Chainlit 无头测试模式驱动**真实 handler 模块**，禁止为 gate 另写假 handler；同一测试 principal）按 V14-HARN-4 算法比较（ORDER BY seq 后投影 ::text 逐行相等），封闭性执法含新增键与 timestamptz 标量；两 principal 越权负例另测。
- 〔P0〕`v14/harness/test_thin.py`（required）exit 0：per-file 决策点计数（INV-5 上限表：driver ≤15 / handler ≤5 / 其余合计 0）+ import 前缀黑名单（六前缀）+ worker/provider 能力协议。
- 〔P0〕`v14/harness/test_listen.py`（required）exit 0：v14_wake 同事务 notify、payload 闭集、独立 autocommit 连接、初始补读、补读循环、四负例（通知合并/断线插入/查询-订阅间隙/重连无后续通知）、重连后 UI 历史从 events 重建。
- 〔P0〕psql submit/observe demo 脚本执行 exit 0。
- 〔P0〕Chainlit 依赖进入 `pyproject.toml` 与 `uv.lock` 更新同笔，且当笔全量回归绿；v13 E4 复跑绿。
- 〔P0〕`v14/regression/` sweep 上线（发现 `v14` 下全部 `test_*.py` 串行，required 零容忍、probe 照 skip 语义）。

### G4 真 provider

范围：DeepSeek 判断面产品化（provider 进程分离）+ 多轮 + compaction 只追加 + economy 整数记账（§4.4）。
gate 验收（写死）：
- 〔P0〕`v14/provider/test_deepseek.py`（required，FakeLLM 确定性部分）exit 0：同 judgment 合同双实现断言；provider 进程能力闭集（可 litellm，禁 DB/beat/写盘）；attempt 记账——**第 3 次无 receipt 不插 attempt 行、effect→failed(attempt_exhausted)、attempt 行数保持 2**；`effect/failed/sql` 终态证据事件入投影；投影按 kind 丢弃 attempt 事件；判断错误码闭集五值同表映射、FakeLLM 与 provider 不得各增码；reconcile 产生新 judgment 世代。
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

**V14-PROC-1**〔P0〕gate 文化沿用并按 §6.0 三分类执行：gate 脚本独立可跑；偏差台账（`docs/reviews/v14-deviation-ledger-*.md`，自 G1 开立）登记一切对本文〔P1〕条款的让步——〔P0〕条款（含 INV-4 比较面）台账无权松动；覆盖矩阵按 stage 更新（`docs/reviews/v14-conformance-matrix-*.md`）。

**V14-PROC-2**〔P0〕oracle 对抗审核：spec 冻结 = 本文经 oracle 审至 0 P0 / 0 P1（父循环职责）；实现期每轮代码修改走 oracle 审核（双 oracle 模式沿用）。

**V14-PROC-3**〔P0〕逐里程碑提交推送：一 stage 一里程碑，里程碑的**提交集合在 stage 计划中枚举**（如 G1 = 内核提交 K + 实现提交 S，有序、逐个按路径 add）；测试全绿 + 收尾工件更新后提交；分支纪律遵循父循环台账（`v14-dev` 推送为加法允许面；合并回 main 须父循环终审 + 用户确认；禁止 force-push）。计划文件惯例：每 stage 开工时立 `docs/plans/v14-<stage>-<日期>.md`（本规范 §6 即其骨架，不预建空壳）。

**V14-PROC-4**〔P0〕收尾工件清单（每里程碑）：新 SQL 进 v14 迁移加载序列（V14-GATE-K）、覆盖矩阵、偏差台账、stage README、（涉依赖时）`pyproject.toml` + `uv.lock` 同笔。

**V14-PROC-5**〔P0〕规格原文权威：对标 pi 的行为疑问以 pi / PiG / PiSwift 仓库实际代码为准（引用须 file:line）；v8/v10/v13 已冻结条款以各自文档为准；本文与它们冲突时，按 §2 的关系裁决，冲突未裁决前按更严者执行。

## 9. 明确不做

1. 不做 pi 的进程模型 / TUI 复刻；不兼容 pi 插件生态与其 session 文件格式。
2. 不实现 v10 内核规格；不回改 v8 / v10 / v13 冻结面（内核变更流程除外，§2.3）。
3. 不引入 DSH Node host；P0C 按退役处理（§2.1），义务不转移。
4. **不做任意 shell 执行**：G2 bash 是闭集命令执行器（execve + 枚举动词 + 类型化参数 + 受信二进制 + 进程边界封死）；任意 shell 待后续版本有真隔离机制（容器级）再开。
5. 不在数据库事务内做任何外部 IO（v8 不变量 4，全文有效）。
6. 不做 UI 富交互（只 submit + LISTEN 渲染；审批呈现之外的 UI 状态机一律不做）。
7. 不做多 agent 编排 / RSI / 生态面（v8 P2/P3 范畴）。
8. 不预建空计划壳；不为「看起来完整」冻结未核实引用。

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

## 附录 B. 轮 3 → 轮 4 修订对照（oracle 双裁合并裁决 N1..N20 落点）

| # | 轮 3 裁决项（N） | 轮 4 落点 |
|---|---|---|
| N1 | 出生三分 | V14-EFF-1 出生三分正文+转移表首行：mutating=批准同事务 planned；read-only=无 proposal、INSERT planned 同事务自动 claimed、不取锁不分配 seq、无 receipt 至多 1 次重试仍无则 failed；provider=无 proposal 无锁无 seq 走 EFF-6；v13 read 不建 v14 effect；EFF-2 措辞改「任何 v14 effect」 |
| N2 | provider 劲竭终态 | V14-EFF-1 转移表新增 SQL 侧终结行 `started→failed(attempt_exhausted)`（attempt_count=2 且第 3 次需求由 SQL 幂等生成、kind=`effect/failed/sql` 终态证据事件入投影）；EFF-6 与 G4 gate 同步 |
| N3 | 过期悬挂 | V14-EFF-1 planned→claimed 行内：claim 谓词失败（含 approved 后 now≥expires_at）→ 同事务 effect→failed、proposal→expired（过期终态名单一选死）、释放名额、不 rename；APPR-4 状态机加 approved→expired |
| N4 | lease reclaim | V14-EFF-2：claimed 且过期仍为 claimed、仅 CAS 改 lease_owner/lease_until、proposal 保持 consumed、seq 不变、禁新建 effect 行 |
| N5 | bash 超时/被杀 | V14-EFF-5：超时 kill 或被杀无 receipt→unknown、禁合成 failed/succeeded receipt；输出超限=带 receipt 的 failed（不变，TOOL-4） |
| N6 | resume_probe | INV-1 第 4 类：kind 闭集=`tool\|resume_probe`、resume_probe 载荷仅 `{path, hash\|EMPTY, temp_exists}`、driver opaque 提交、SQL 裁 settle/replay/unknown；EFF-3 三分法改由 resume_probe 驱动；G3 窗 1 gate 更新 |
| N7 | 原子写顺序终版 | V14-EFF-3：取锁→锁内重算全受影响路径基线→不匹配禁 rename→写临时→fsync 临时→rename→fsync 父目录→校验目标态（exists/hash/mode，与锁内校验并存）→才许 receipt |
| N8 | 多路径一次性分类 | V14-EFF-3：任一 case3→整 effect unknown 不再 rename 其余；全 case1→不重放结算 succeeded；仅 1+2→只重放 case2 后 succeeded；禁逐路径各自 succeeded；G1 gate 加三形态断言 |
| N9 | 锁与屏障 | V14-EFF-4：会话级 advisory 锁（pg_advisory_lock(workspace_id) 类）生命周期跨 claimed→started 的 COMMIT 直至 apply 结束或会话死；屏障=存在未终态 started/unknown 禁更高 seq mutating（跨 session）；reclaim 不绕屏障；unknown 即标 blocked/degraded |
| N10 | proposal 构建三段 | V14-TOOL-3 ①：短事务登记只读 lease 并提交→事务外读文件→新事务写 proposal 释放 lease；文件 IO 永不在打开的 DB 事务内 |
| N11 | degraded 判别式与出口 | V14-EFF-5：判别式（可被更小 seq 受控 diff 解释→failed(stale) 不 degraded；解释不了→degraded，未 rename failed/已 IO unknown）；出口=同一 reconcile SQL（principal 同 APPR-6）、追加不可变 reconcile/diff（TOOL-2 六字段、seq 复用）、清 degraded、基线=per-path 观测态、observed 由受信 SQL/worker 校验禁调用方提交哈希；命题 B 重放输入=成功 tool diff ∪ reconcile/diff；未 reconcile unknown 不宣称 B；provider 只引 EFF-6 |
| N12 | 投影补全 | V14-HARN-4：代理键加 workspace_id（$w1）；volatile 加 lease_until/lease_owner/issued_at/revoked_at；失败模式加 *_until/*_pid/*_lsn 及 timestamptz 型标量；uuid 仅整标量判（stdout/stderr/diff 不子串扫）；字符串先 $ws 替换后残留绝对路径才失败；比较=ORDER BY seq 后投影 ::text |
| N13 | 审批×claim×grant 交点终版 | APPR-4（单名额请求创建时执法+per-session 唯一）、APPR-2（四不收+认证连接绑定+WHERE state=requested+竞争审计）、APPR-5（命中=创建事务内内部动作+EXECUTE REVOKE（harness/service role）+principal=granting_principal+合取写死六项+正文/diff/哈希不参与+bash 拒签发+claim 时重验 revoked/expires 不回滚已 started IO+命中跳过 await_approval）、APPR-1（grant_id 入哈希）、APPR-6（revoke 面 REVOKE） |
| N14 | shell/解释器封到进程边界 | V14-TOOL-4：verb executable=digest 校验受信二进制禁脚本/shebang；verb 与子进程树禁调 shell/解释器（source gate 六模式扫描）；envp 闭集禁继承；超时 kill 整进程组；dirfd 逐级 no-follow（openat/renameat、RESOLVE_BENEATH）任一父分量 symlink 即拒；G2 三负例（重解释 argv/父目录 symlink 越界/TOCTOU） |
| N15 | 四条审批路径拆死 | V14-TOOL-6：默认拒=准入时拒绝不建 proposal（未签发 grant 的非 bash mutating）；批过=approved；驳回=denied；超时=expired；bash 总是建 requested 不自动批 |
| N16 | 闭集收尾 | INV-1（无参 advance/next_beat/expire_due 非第五类+新入口参数面禁判断/principal/now/session_id；envelope kind/status 闭集）、EFF-6（start_attempt 由 SQL 执行、第 3 次不插行、attempt 行数保持 2、投影按 kind 丢弃 attempt 事件）、INV-1 status↔exit_code 映射、HARN-7（判断错误码闭集五值写死：ok/timeout/transport_error/content_invalid/budget_exceeded，不得各增码） |
| N17 | diff 规范编码终版 + write 语义 | V14-TOOL-2：路径相对字节序排序、缺失哈希=JSON null、NUL/非法 UTF-8→base64 否则 utf8、键序=字段序、payload_digest=规范 jsonb sha256（预映像不含 volatile 键）；TOOL-1+ARCH-6：write=create-only（已存在拒绝、覆盖走 edit），登记 §0 对标差异表 |
| N18 | INV-3 适用面句改 | V14-INV-3 原句改：「FakeLLM 路径与已提交 receipt 的 provider 路径；bash unknown 未 reconcile 的窗口、provider 未提交 receipt 的窗口除外」；EFF-5/6 同步（未 reconcile unknown 不宣称命题 B） |
| N19 | envelope 加 exit_code | INV-1 第 4 类：envelope 加 exit_code（可空、exec 类必填）；status↔exit_code 映射写死（0→succeeded、≠0→failed、非 exec null）；payload_digest 预映像含 exit_code |
| N20 | bash mutating 共享 apply 状态图 | V14-TOOL-4：mutating 动词与 write/edit 同锁同状态图（锁覆盖外部进程运行期间=受控 writer 串行是设计语义）、started 前锁内基线重算、seq 在 claim 已提交事务分配、receipt 丢失→unknown 阻塞 workspace；G2 加 bash×write 并发/kill/基线漂移测试 |
