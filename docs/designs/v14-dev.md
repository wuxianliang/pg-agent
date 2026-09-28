# PG 原生 Pi 对标 Coding Agent（v14）开发规范

> 状态：草稿第 6 版，待 oracle 终审轮 6。冻结标准：评审至 0 P0 / 0 P1。
> 撰写日期：2026-09-28（第 1 版 `e97f4ce`；第 2 版 `e854e04`；第 3 版 `3af3dc6`；第 4 版 `0ee355f`；第 5 版 `b5ee119`）。工作分支：`v14-dev`。
> 修订记录：第 2 版吸收轮 1 双裁（4+3 P0）与父循环两裁决；第 3 版吸收轮 2 双裁裁决 A..M；第 4 版吸收轮 3 合并裁决 N1..N20；第 5 版吸收轮 4 合并裁决 R1..R19（条款级补丁：双序键合一、lease fencing、基线判别式决策表、准入合一、投影面拆分），全部落正文。第 6 版吸收轮 5 合并裁决 S1..S17（纯谓词判别式、出生边统一、两阶段 reconcile、digest 字节语法），全部落正文。第 6 版不自含自身哈希。
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

仿的是：工具集形状（read/write/edit/exec/glob/grep；exec 目录恰 {run-test, build}，不是 pi bash）、REPL 对话体验、基准任务成绩。不仿的是：进程内循环、进程内事实源、TUI 耦合。检查：设计评审对照本表；G3 双壳/可弃 gate。

### 0.3 Chainlit 使用约束

**V14-ARCH-3**〔P0〕Chainlit handler 只允许两种动作：**submit**（把用户输入经既有 SQL 命令入口提交进库）与 **observe**（LISTEN 事件流 → 渲染）。UI 历史从 events 表重建；Chainlit 会话内存不得成为事实源（INV-6）。审批动作在 UI 上也只是向 SQL 批准命令提交标量（approver 身份由 DB 得出，见 V14-APPR-6）。检查：source gate 静态扫描 handler 模块（V14-HARN-6）。

**V14-ARCH-4**〔P0〕明示反模式：禁止照抄 Chainlit 官方教程把 agent 循环写进 `@cl.on_message` handler（在 handler 里调 LLM、跑工具、维护对话状态、代批代答）。handler 内出现任何 beat 驱动、模型调用、工具分派、判断拼装即红。检查：source gate 断言 handler 模块 import 黑名单（V14-HARN-6）。

### 0.4 对标面定义、差异登记与威胁模型

**V14-ARCH-5**〔P1〕对标成立的三件事：① 工具面覆盖 read/write/edit/exec/glob/grep（exec 目录恰 {run-test, build}；**不宣称覆盖 pi bash**，重大偏差见 V14-ARCH-6）；② REPL 体验：Chainlit 窗口可对话驱动、可断线重连、历史完整；③ 基准：§5 任务套件上产出 v14 vs pi 对照报告。不承诺 TUI 视觉复刻、不承诺 pi 插件生态兼容。检查：G3/G5 gate 与对照报告。

**V14-ARCH-6**〔P1〕对标差异登记表（对 pi 语义的显式偏差，逐条列出，新增须 bump）：

| 差异点 | pi 语义 | v14 语义 | 理由 |
|---|---|---|---|
| `write` | 覆盖或创建 | **create-only**：目标已存在即拒绝；覆盖一律走 `edit` | mutating 效果可解释性（diff 恒为创建形态，V14-TOOL-2） |
| 审批门控 | 工具调用无审批环，权限在进程内裁量 | **write/edit = grant 门控**（未命中 grant 准入拒绝，无逐次人批）；**exec mutating（目录 {run-test, build} 中 `workspace_mode=mutating`）= 逐次人批** | mutating 效果治理（V14-APPR；产品语义裁决 V14-TOOL-6） |
| 无任意 shell | pi 有 bash（任意 shell 字符串） | **无 bash**；exec = 闭集命令执行器，目录恰 {run-test, build}，禁止 `shell=True` / `sh -c` | **对 pi 的重大偏差**（§9.4；V14-TOOL-4）。基准报告必须单列本行，不得把 exec 成绩记为 bash 覆盖（V14-BENCH-4） |

检查：G1 gate（write create-only 负例 + 准入两分支夹具）；设计评审对照本表。

**V14-ARCH-7**〔P1〕威胁模型（写死）：载体（carrier）= **trusted-but-crashable**——可崩溃、不可恶意。执法面：worker 能力合同（INV-5）+ SQL 结构性验证回执绑定与映射（INV-1 第 4 类）；resume_probe 观测由**受信 worker** 产出（V14-EFF-3）。对抗性载体（伪造回执/恶意观测）的完整性加固 = §9 范围外。检查：设计评审对照本条；G1/G3 gate 的回执验证断言。

## 1. 不可妥协的不变量（V14-INV-1..6）

> 本节原文照录父循环裁决，是全部后续条款的上位约束。任何 stage 设计、实现、gate 与本节冲突即无效。

**V14-INV-1 判断零外置（四类提交闭集）**〔P0〕一切决策（下一步做什么、何时结束、调用什么工具、是否需要模型判断）由 SQL 面产出（advance / 判断请求拼装与入队全在库内）；LLM 调用只是判断请求的数据面——问题由 SQL 面拼装、回答落 judgment 记录。**执法语义（四类提交闭集）**：harness 向库内提交的输入只许四类，每类只能调用**已登记 SQL 函数**（v13 既有 + v14 迁移新建），禁止裸 DML、禁止 harness 发 `pg_notify`：

1. **用户文本**（submit 入口）；
2. **审批决定**（approve | deny | reconcile 的标量参数；签名面见 V14-APPR-2/3/6——不收 session_id/proposal_id/principal/now，会话来自认证连接绑定）；
3. **判断答案**（FakeLLM 与真 provider 的回答文本同形，落 judgment；错误码闭集与乘积表见 V14-HARN-7 / V14-EFF-6）；
4. **工具回执**（统一 envelope：`kind`、`effect_id`、`attempt_id`、`request_id`、`fencing_gen`（执行时的 lease fencing generation；与所绑 effect 或 observation request 的当前代不一致 → **拒绝落库、状态不变**，V14-EFF-2）、`status`、`exit_code`、`payload_digest`、`stdout`、`stderr`、`diff`——SQL 验证绑定与状态后落库；driver 仅 opaque 转发，禁止解析回执推导下一步）。**kind 闭集** = `tool | resume_probe | preflight_probe | claim_probe`，外加 `reconcile_probe`（S6 四值是工具/探针通道；S13 的 reconcile 观测同轮并入同一闭集，避免闭集外发明 kind；**+ `request_id` 绑定，不是第五类提交**）。tool 回执 **status 闭集 = `succeeded | failed`**；**status↔exit_code 映射写死**：exec 类 `exit_code=0 → succeeded`、`exit_code≠0 → failed`、`exit_code` 必填；非 exec 类 `exit_code=null`。**attempt_id 绑定（写死）**：mutating 的 tool receipt，`attempt_id` 规范值 = **JSON null**，且 SQL 验证该 effect **无 attempt 行**；read-only 的 tool receipt 与 provider 完成提交的 `attempt_id` **必须非空**且绑定该 effect 的 attempt 行（provider 完成走第 3 类 judgment 提交，不走 tool receipt，V14-EFF-6）。**payload_digest 预映像 = `kind/effect_id/attempt_id/request_id/fencing_gen/status/exit_code/body_digest`**（status 已按 exit_code 规范化；不含 volatile；字节语法见 V14-TOOL-2；tool 类 body_digest = diff_digest，probe 类 body_digest = 全观测规范编码的 sha256，provider 完成预映像 kind 字面 = `judgment`）。probe 载荷 = per-path 全观测 `{exists, file_type, mode, sha256}`（resume_probe 另携带临时文件内容摘要/类型/mode，受信 worker 产，V14-EFF-3）；preflight_probe 不建 effect。

**无参已登记函数**（`advance` / `next_beat` / `expire_due`）**不是第五类输入**——它们没有参数面；任何新入口的参数面禁判断内容、principal、now、session_id。

人批与模型回答同属外部判断数据面：请求由 SQL 产出、答复落库；harness 不代批、不代答、不拼装。检查：G3 source gate（INV-5 扫描 + import 黑名单 + envelope 仅经登记函数断言）+ 判断面 gate 回归。

**V14-INV-2 beat 序列是数据**〔P0〕beat 序列（judge/parse/advance/claim/tool/llm/finish 一类的拍结构）是库内数据，不是代码控制流。advance 决定下一步，harness 仅执行。先例：`v13/pi_parity/test_pi_parity.py:66` 的 `GOLDEN_SEQUENCE`（canonical phases）与 `v13/read_tools/test_read_tools.py` / `v13/pi_ports/test_pi_ports.py` 的 ring 驱动。**相位定案**：assistant（模型）输出是**显式 canonical phase**（拍结构中的 `llm` 相），不是 `claim kind=llm`——按 pi_parity schema-v2 定案，本条为二选一歧义的落死。检查：G3 gate 断言 beat 拍落 events 表且驱动模块无硬编码序列分支、llm 拍为独立相位。

**V14-INV-3 会话可弃（双命题，适用面受限于 V14-EFF-6）**〔P0〕kill harness → 重启 resume 的可操作承诺收窄为两个命题，分别断言：

- **命题 A（事件面，独立语义子流）**：已提交事件的**A 子流**（字面 kind 白名单写死于 V14-HARN-4：`effect/failed/sql` 入 effect 终态；proposal 只收 `consumed` / `denied` / `expired`；beat、grant 变更、`resume_probe` / `preflight_probe` / `claim_probe` / `reconcile_probe`、attempt、lease reclaim **不入 A**；增 kind 须 bump）的规范化投影在「杀过」与「未杀」两条世界线上一致。G3 窗 1 断言子流逐行相等 + `tool/result` 规范 diff 与 `workspace_effect_seq` 相同。**A 允许表是〔P0〕比较面，偏差台账不能扩**（V14-HARN-4）。
- **命题 B（工作区面）**：工作区终态 = **会话创建时冻结的 workspace tree hash** 起，按 `workspace_effect_seq` 升序折叠「成功 tool diff ∪ reconcile/diff」（V14-EFF-4/5）的确定性结果。reconcile SQL 成功后，折叠**含该 seq 的 reconcile/diff**；只排除 reconcile 前的 unknown 前缀。

**适用面（原句）**：FakeLLM 路径与已提交 judgment 的 provider 路径；exec unknown 未 reconcile 的窗口、provider 未提交 judgment 的窗口除外。exec `unknown` 场景在 reconcile 前只承诺**终态有定义**（可进人工 reconcile，V14-EFF-5），不承诺「与不杀一致」；**未 reconcile 的 unknown 世界线不宣称命题 B**；reconcile SQL 成功后命题 B 恢复（折叠含该 reconcile/diff）。检查：G3 杀进程续跑 gate（四钉，§6 G3）+ G4 kill gate 按 EFF-6 断言。

**V14-INV-4 双壳等价**〔P0〕Chainlit 驱动与脚本驱动同输入 → **服务端投影 ::text 逐字节相等**。比较面与投影算法**写死于 §4.3（V14-HARN-4）**：库内唯一 canonical 投影函数、代理键 allowlist、volatile 键表、服务端比较；**双壳用 §4.3 全流**（两壳无杀点，与 INV-3 命题 A 的子流是两个不同比较面）。比较面新增排除项不属于已冻结类别时必须 bump 本规范——偏差台账无权松动 P0 比较面。检查：G3 双壳等价 gate。

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

**V14-EFF-1 效果状态机（六态闭集 + 出生三分 + 转移表写死）**〔P0〕effect 态闭集 = `planned | claimed | started | succeeded | failed | unknown`（**无** approved/reconciled 态；批准语义在 proposal 上，V14-APPR；reconcile 是动作不是态）。**出生三分（三类创建事务均写 `fencing_gen=1`）**：

- **mutating**（write/edit、mutating exec 动词；目录恰 {run-test, build}）：与 proposal 批准**同事务** INSERT 即 `planned`，`fencing_gen=1`（proposal 来源见 V14-TOOL-6 准入合一）；被拒/超时的**不建 effect 行**；**mutating 无 attempt 行**。mutating tool receipt 的 `attempt_id` 规范值 = JSON null，且 SQL 验证无 attempt 行。
- **read-only**（glob/grep 及 `workspace_mode=read_only` 动词）：**无 proposal**，SQL INSERT `planned` **同事务直接 `started` + attempt 1 + `fencing_gen=1`**（**无 claimed 停留**）；**不取 apply 锁、不分配 workspace_effect_seq**；receipt 的 `attempt_id` 必须非空绑定该 attempt。`started` 无 receipt 时 SQL **再开至多 1 次 attempt（同一 effect 保持 `started`）**，仍无则走 `attempt_exhausted` 路径（同 provider，下行）。**read-only reclaim** = 行级 CAS：`state=started ∧ 无 receipt ∧ lease_until≤effective_now`，`fencing_gen+1`，**不要求 workspace 锁**（V14-EFF-2）。
- **provider**：**无 proposal、无锁、无 seq、无 reclaim**；`start_attempt` 由 SQL 执行——**同事务插 effect=`started` + attempt 1 + `fencing_gen=1`**；attempt 2 **不换 effect 行**；第 3 次需求**不插 attempt 行** → `failed(attempt_exhausted)` + `effect/failed/sql` 终态证据事件**入投影**（V14-EFF-6）。完成不走第 4 类 tool receipt。
- **边界**：v13 既有 read 口岸保持 v13 语义，**不建 v14 effect**。

转移表：

| 转移 | 条件与方式 |
|---|---|
| → `planned` / `started` | 按出生三分（上行）。read-only 与 provider **不经过 claimed** |
| `planned` → `claimed` | 仅 mutating。条件 UPDATE：proposal=approved、effective_now 未过 expires_at、grant 未撤销未过期（APPR-5）、workspace 基线匹配（已提交 claim_probe 全观测）。**同事务** proposal→`consumed`、分配 seq（EFF-4）。**失败短路序 ①时间 ②grant ③基线，先命中独占单审计**。后置条件见下表。**本格无「已 IO→unknown」**（`unknown` 只出现在 `started` 之后）。**过期终态名单一选死 = expired** |
| `claimed` → `started` | **仅锁内复算基线匹配之后**（EFF-3：取锁→锁内复算→匹配才本转移→之后才写临时文件）。与「允许开始外部 IO」合并为一条条件更新：`WHERE state=claimed AND lease_owner=当前执行者 AND lease_until>effective_now`；**0 行 → 零外部 IO**。基线不符则**保持 claimed、零外部 IO**，调用点按 explainable 写一次终态（`failed(stale)` 或 degraded 未 IO 的 `failed`），不进入 started |
| `started` → `succeeded \| failed` | **仅 tool 类**且带 receipt（INV-1 第 4 类；fencing 代验证通过；接受谓词 = 与 probe 同一全观测，V14-EFF-3）。provider 不走本行（完成 = 第 3 类 judgment 提交函数内原子动作，V14-EFF-6）。mutating 无 receipt **禁止**本转移 |
| `started` → `failed(attempt_exhausted)` | **SQL 侧终结转移**（provider 与 read-only 同一路径）：attempt_count=2 且第 3 次需求到达（provider）或再开 attempt 后仍无 receipt（read-only）时由 SQL 幂等生成；产生 kind=`effect/failed/sql` 终态证据事件且**入投影**。mutating **无**此边 |
| `started`（resume，无 receipt） | 按出生类分流：exec → `unknown` 禁自动重试，同事务 workspace degraded（EFF-5）；write/edit → resume 分类（EFF-3），**禁止无 receipt 的 started→failed**；provider → 不进 unknown，完成只在 judgment 提交函数内（EFF-6）；read-only → 再开至多 1 次 attempt，或 lease 到期走 read-only reclaim（不要求 workspace 锁） |
| `unknown` 或 `failed`+degraded → `succeeded` / `failed` | 仅两阶段 reconcile（EFF-5）。CAS：`state IN ('unknown','failed') AND workspace degraded`。终态 = 本次 `reconciled_outcome`。不是 effect 行上的一步胜者 CAS |

**claim 失败事务后置条件表（三行，短路序，先命中独占单审计）**：

| 行 | effect | proposal | 名额 | 审计 kind | seq | advisory lock |
|---|---|---|---|---|---|---|
| ① 时间（now≥expires_at） | `failed` | `expired` | 释放 | 时间过期（单审计） | 不分配 | 已取锁则 unlock；专属连接归还 |
| ② grant 撤销/过期（①未命中） | `failed` | `expired` | 释放 | grant 撤销/过期（独立审计 kind，单审计） | 不分配 | 已取锁则 unlock；专属连接归还 |
| ③ 基线不符（①②未命中） | explainable → `failed(stale)` 且不 degraded；非 explainable → `failed` 且 degraded（未 IO）。调用点写一次，判别式不赋终态 | `expired` | 释放 | 基线不符单审计 | stale 不分配；进入 degraded 则本事务分配 | 已取锁则 unlock；专属连接归还 |

一切 pre-apply 终结路径（上表三行，以及锁内复算不符、尚未 started 的终结）均显式 unlock + 归还专属连接。claim 成功不在本表：effect=`claimed`、proposal=`consumed`、名额保持占用、seq 本事务分配、锁跨 COMMIT 持有至 apply 结束（EFF-4）。

检查：G1 起各 gate 断言合法转移集（非法转移负例）+ 后置条件表三行逐列 + 短路单审计 + 基线行 proposal→expired 且释放名额 + pre-apply unlock + 劲竭终结事件 + read-only/provider 无 claimed 停留。

**V14-EFF-2 intent 行、效果身份、观测请求与 lease fencing（终版）**〔P0〕任何 **v14 effect** 的外部 IO 发生前，effect intent 行必须已提交入库（intent 事件位置仅表「IO 前日志已提交」，**不定义序**）；**效果身份 = `effect_id`（唯一）**。**三类 effect 创建事务均写 `fencing_gen=1`**。**范围边界**：proposal preflight read（V14-TOOL-3 ①）**不属于 effect IO**——只读、受读 lease 保护、不建 effect；apply 阶段以 EFF-3 锁内复算基线为准。

**观测请求（SQL 先建、不可变）**：preflight 与 pre-claim baseline probe **各有身份**。worker 任何观测 IO 之前，SQL 已提交 observation request 行（`request_id`、角色 `preflight | claim_baseline | resume | reconcile`、所绑 effect 或读 lease、`fencing_gen`）。worker 不得自造 request。回库走 INV-1 第 4 类，kind = `preflight_probe | claim_probe | resume_probe | reconcile_probe`，**必须绑定 `request_id`**（不是第五类提交）。digest 预映像、fencing 代、投影归类（probe 类不入 A，V14-HARN-4）与失败/超时边同轮冻结：

- fencing：probe receipt 的 `fencing_gen` 必须等于 request 行当前代；绑 effect 时还必须等于该 effect 当前代；不一致 → 拒绝落库、状态不变；
- 失败/超时：request 行终态闭集 = `failed | timeout`（不可变保留）；**effect / proposal 态不变**。preflight 失败 → 不建 proposal、不建 effect、释放读 lease。claim_probe 失败 → effect 保持 `planned`，不 claim、不分配 seq、零外部 IO。resume_probe 失败 → effect 保持 `started`，零 rename，**禁止**无 receipt 的 `started→failed`。reconcile_probe 失败 → 不写 `reconciled_outcome`，token 按 EFF-5 超时边恢复。下一拍可新建 request，旧行不改。

claim 带 `lease_owner` / `lease_until`（now 取 V14-APPR-3 的 effective_now）与 **fencing generation**（初值 1；每次 lease 变更 +1）。read-only 在出生事务写 lease。provider 出生写 `fencing_gen=1`，**无 reclaim**。**fencing 规则（写死）**：

- `claimed→started` = EFF-1 一条条件更新，**且仅在锁内基线匹配之后**，**0 行即零 IO**；
- **mutating reclaim** 仅当 `state=claimed ∧ lease_until≤effective_now ∧ 调用者持该 workspace 的 advisory 锁`；reclaim 使 fencing generation +1，effect **仍为 claimed**、proposal 保持 `consumed`、**禁新建 effect 行**；
- **read-only reclaim** = 行级 CAS：`state=started ∧ 无 receipt ∧ lease_until≤effective_now`，generation +1，**不要求 workspace 锁**；不新建 effect 行、不新开 attempt（新开 attempt 是另一条边，EFF-1）；
- **provider 无 reclaim**；
- **resume_probe 单胜者 CAS**（`WHERE state=started`；败者零 IO）。reconcile 的单胜者是 token CAS，不是 effect 行上的第二套胜者（V14-EFF-5）；
- **receipt 携带 fencing generation**，与 effect 或 request 当前代不一致 → 拒绝落库、状态不变（INV-1 第 4 类）。

检查：G1 gate（intent 先于 IO、创建事务 fencing_gen=1、观测请求先于 probe IO、fencing CAS 0 行零 IO、mutating reclaim 持锁前置、read-only reclaim 不要求 workspace 锁、provider 无 reclaim、probe 失败不改 effect 态、过期 receipt 拒绝）。

**V14-EFF-3 write/edit 原子写与 resume 分类（顺序钉死 + 观测完备）**〔P0〕apply 顺序写死，不得重排：

1. **取锁**（EFF-4；拿不到则结束事务，effect 留 `planned`/`claimed`，零外部 IO）；
2. **锁内复算**全部受影响路径基线。文件观测在锁已持有、DB 事务已关闭时由**新的** claim_probe 完成（不得复用 pre-claim 观测）；比较与状态转移在随后的短事务内。这不违反「外部 IO 不进事务」；
3. **不符** → **保持 `claimed`**（零外部 IO，不写临时文件、不 rename）。调用点按 explainable **写一次**：explainable → `failed(stale)` 且不 degraded；非 explainable → degraded 未 IO 分支（effect `failed`；seq 已在 claim 成功时分配则复用，不第二次分配）。然后 unlock + 归还专属连接。**禁止**为此进入 `started`，**禁止**记 `unknown`（unknown 只在 started 之后）；
4. **基线匹配才** `claimed→started`（EFF-1/2 fencing 条件更新，0 行则零 IO）；
5. **之后才写临时文件** → fsync 临时文件 → rename → fsync 父目录 → 校验目标态（exists/file_type/mode/sha256；该校验不替代锁内基线校验，两者都在）→ 才许提交 receipt。

**started 之后**，mutating 无 receipt **只走** resume_probe / `unknown` / reconcile；**禁止无 receipt 的 `started→failed`**。

临时文件是 **effect 专属**（路径含 `effect_id`，不与其他 effect 共享），存活至 effect 终态。**清理**：SQL 产生幂等 **cleanup beat**；受限 worker（INV-5：单 effect、禁开 DB、禁写声明路径外）确认 effect 已终态后删除该 effect 专属 temp。清理**不改工作区语义**，可重复（temp 已不存在 = 成功）。**目标为 symlink 一律拒绝**。

**resume 分类**（`started` 无 receipt；resume_probe 驱动，SQL 裁决；判别式不赋终态）。per-path 全观测 = `{exists, file_type, mode, sha256}`（symlink 一律拒；文件不存在 = 冻结哨兵 `EMPTY`）。`explainable` 见 EFF-5。case 只描述观测形态，终态由下面的整 effect 分类写一次：

- **case1**：全观测 = 目标态；
- **case2**：全观测 = 基线（含 `EMPTY`）∧ temp 与 proposal diff 的 `new_sha256`/`new_mode` 经验证一致 ∧ **explainable** → 持锁**只做剩余 rename**，**禁记 stale**；
- **case2 非 explainable** → **零 rename**，走 degraded 未 IO 分支（effect `failed`，不记 unknown）。

**无 case3。** 删除「都不是 → 一律 unknown」。

**整 effect 一次分类**（禁逐路径各自 succeeded；终态只写一次）：

1. 任一 path 的目标或已 rename 结果不可解释 → `unknown`（同事务 degraded）。这是 resume 上 unknown 的唯一入口；
2. 否则若任一 path 非 explainable（含 case2 非 explainable）→ 整 effect 走 degraded 未 IO 分支（`failed`，零 rename）；
3. 否则若无任何 path 达目标态 → `failed(stale)`；
4. 否则若全 case1 → 不重放，结算 `succeeded`；
5. 否则若仅 case1+case2 → 只重放 case2 后结算 `succeeded`。

**崩溃续跑（temp 可重建）**：目标仍 = 完整基线 ∧ 该 effect 私有 temp **未用于 rename** → 持锁重跑 explainable 后，**从不可变 proposal payload 幂等重建 temp**，续 case2。**只有目标或已 rename 路径不可解释才 `unknown`**。temp 不存在本身不再直接打 unknown。symlink 仍一律拒、零 rename。

**rename 后失败**：目标态校验失败 / 父目录 fsync 失败 → `unknown`（IO 已发生；同事务 workspace degraded），判别式只读、不赋第二终态，**禁自动再 rename**。

**receipt 接受谓词（写死）**：与 probe 同一全观测——每 path `{exists, file_type, mode, sha256}` **相等**于锁内基线侧预期（不只 `old_sha256`）∧ `exit_code`/`status` 符合 INV-1 映射。**exec 已跑且全观测与锁内基线不一致 → `unknown`，不重试**。成功后提交 `tool/result`（含 diff 载荷，V14-TOOL-2）。

检查：G3 四杀点 +「receipt 提交后杀 driver」cleanup gate；G1 原子写正/负例（symlink 拒绝、父目录 fsync、temp 重建、整 effect 一次分类、无 case3、receipt 全观测负例、无 receipt 的 started→failed 负例）。

**V14-EFF-4 workspace 全序、排他 apply 锁与屏障**〔P0〕每个 workspace 有 `workspace_id`。**排他锁**：会话级 advisory 锁（`pg_try_advisory_lock`，**workspace_id 映射到 v14 专用 bigint namespace**，避免与 v13 既有 advisory 键空间相撞）；在 claim 阶段尝试取得，**拿不到 → 结束当前事务，effect 留 `planned`/`claimed`，下一拍再试**；取得后**生命周期跨 `claimed→started` 的 COMMIT，直至 apply 结束或会话死**；**持锁连接专属于该次 apply，IO 期间不归还连接池**；所有受控 writer（write/edit、mutating exec 动词）用同一把锁（锁覆盖外部进程运行期间——受控 writer 串行是设计语义，V14-TOOL-4）。**advisory 锁仅 mutating 出生类取得**（read-only/provider 无锁）。持锁期间按 EFF-3 复算受影响路径基线，任一不匹配由调用点按 explainable 写一次终态，禁止 rename、禁止进入 started。**workspace_effect_seq 分配点集合恰 = {claim 成功, 进入 degraded}**，二者互斥（同一 effect 只分配一次）、各自发生在**已提交事务**内、**每 workspace 从 1 单调**。未 degraded 的 claim 失败与 `failed(stale)` **不分配**。reconcile/diff **复用已有 seq**，不新分配、不重排。resume 复用原 seq。**「更小 seq」** = 比较开始时冻结的 **candidate horizon**（该 workspace 已提交 seq 的快照）之内、严格小于本 effect seq 的 seq；本 effect 尚无 seq 时 = horizon 内全部已分配 seq。比较中途新提交的 seq 不进入本次 horizon。INV-3 命题 B 的重放全序 = `workspace_effect_seq` 升序（折叠基底 = 会话创建时冻结的 workspace tree hash，INV-3）。**workspace 屏障（只统计 mutating）**：read-only / provider **不计入**屏障，也不被屏障挡住。workspace 存在未终态 **`claimed` / `started` / `unknown` mutating** 时，**不得 claim 新的 mutating**（只许恢复既有：reclaim / resume_probe / reconcile）——封住 claim 成功后、started 前崩溃造成的越序窗。跨 session 执法。lease reclaim 不绕过屏障。`unknown` 只出现在 started 之后；进入 `unknown` 的同事务标 workspace **degraded**（reconcile CAS 要求 degraded，V14-EFF-5）。**外部写入（声明式，两句合一）**：受控面内的检测点 = **入 degraded**（receipt 全观测验证与下一 effect 基线 explainable 判定）；**该检测点之外不给更强保证**（不承诺文件系统级防并发；点外写入不升级为可解释失败，也不承诺与不杀世界线一致）。advisory 锁只覆盖受控 writer。**expire_due（写死）**：仅 DB 时钟、无参数、幂等；requested 到期 → `expired`（不建 effect）；approved+planned 到期 → EFF-1 后置条件表时间行（effect `failed` + proposal `expired` + 释放名额）。检查：G1 gate（try-lock 不可得留态重试/屏障只统计 mutating/未终态 claimed 时禁 claim 新 mutating 的越序负例/reclaim 不绕屏障/seq 分配点恰二且 stale 不分配/horizon 冻结/degraded 负例/expire_due 两分支）+ G3 命题 B 断言。

**V14-EFF-5 exec unknown、degraded 与两阶段 reconcile**〔P0〕exec `started` 无 receipt（超时 kill 或进程被杀）→ `unknown`，**禁止自动重试**；**禁止合成 failed/succeeded receipt**；同事务 workspace **degraded**（否则 reconcile CAS 不可达）。输出超限 = 带 receipt 的 `failed`（不变，TOOL-4；不因超限本身进 degraded）。

**判别式 = 纯谓词，不赋终态（写死）**：

`explainable := fold(该 effect 冻结基线, horizon 内更小 seq 的成功 tool diff ∪ reconcile/diff) = 该 path 全观测`

折叠按 seq 升序；「更小 seq」与 horizon 见 EFF-4。全观测 = `{exists, file_type, mode, sha256}`（不存在 = 冻结哨兵 `EMPTY`）。**终态只由调用点写一次**；本谓词不写 effect 态、不写 degraded。调用点 = EFF-1 基线行、EFF-3 锁内复算不符、EFF-3 整 effect 分类。`failed(stale)` 只由调用点在「全 explainable 且无 path 达目标态」时写入，不是本谓词的副作用。

**进入 degraded**（调用点写入）：若该 effect 尚未分配 seq，同事务分配（分配点见 EFF-4）。已有 seq 则复用，不第二次分配。mutating 进入 `unknown` 的同事务标 workspace degraded。

**degraded 唯一出口 = 两阶段 reconcile**（不是 effect 上的一步 CAS）：

1. **reconciliation request/claim 行**。选择谓词 = 本会话唯一 mutating effect 满足 `state=unknown OR (state=failed AND workspace degraded)`。命中非唯一即拒绝（同 APPR-2）。approver 经 INV-1 第 2 类提交（不收 session_id / proposal_id / principal / now；principal 规则同 APPR-6）。
2. **approver SQL 原子取 token**（列名 `token_id`；单胜者）：插入 claim 行并签发 token。已有未过期 token → 后者失败、零 IO。
3. **token 持有者启动 probe**：SQL 先建 observation request，回执 kind=`reconcile_probe`（第 4 类，不是第五类提交）。
4. **probe receipt 绑 token + fencing_gen + request_id**；不一致 → 拒绝落库、状态不变。
5. **SQL CAS** 写 `reconciled_outcome` + observed 全观测 + 不可变 reconcile/diff（TOOL-2 字段格式，**seq 复用原 effect**）：`WHERE state IN ('unknown','failed') AND workspace degraded AND token 匹配 AND fencing 匹配`。0 行 → 零更新。清 degraded。**终态 = 本次 `reconciled_outcome`**（`succeeded` 或 `failed`）。observed 由受信 SQL/worker 读取校验，**禁调用方提交哈希**。
6. **「已 IO / 未 IO」只决定 `reconciled_outcome` 的默认建议，不决定匹配**（匹配只看 CAS 谓词与全观测；建议可被 approver 覆盖，覆盖留痕）。

进入 unknown 同事务 degraded 之后，选择谓词与 CAS 的状态条件等价于 `workspace degraded AND state IN ('unknown','failed')`。`failed(stale)` 与 `attempt_exhausted`（未 degraded）不可被选中。CAS 另加 token/fencing 匹配。

**重复 / 超时 / 进程死亡（写死）**：

- 重复取 token：单胜者，败者零 IO、不启动第二 probe；
- token 超时：token 失效，effect 保持原态（`unknown` 或 `failed` 且 degraded），不写 outcome，允许重新取 token；
- 进程死亡且 probe receipt 未回：视同超时，新 token 持有者重跑 probe；
- 进程死亡但 receipt 已回且 token/fencing 仍匹配、CAS 尚未成功：恢复者**不得另开 probe**，只许把该 receipt 提交进 CAS；
- CAS 已成功后再提交：零更新（迟到）。

此后基线 = 该 per-path observed 全观测。后续 fold 用 reconcile/diff，不用调用方哈希。reconcile 留痕 events（先例目录 `v8/reconcile/`）。

**命题 B**：重放输入 = 成功 tool diff ∪ reconcile/diff，按 seq 升序（折叠基底见 EFF-4）。**未 reconcile 的 unknown 世界线不宣称命题 B**。reconcile SQL 成功后命题 B 恢复，折叠**含该 seq 的 reconcile/diff**；只排除 reconcile 前的 unknown 前缀。provider 行只引 EFF-6：不取锁、不分配 seq、**永不进 unknown**；其「新 judgment 世代」是**独立动作（新 judgment_id），非本条 reconcile**。

检查：G1 两阶段正/负例（非唯一拒绝、重复 token 零 IO、超时恢复、死亡后不双 probe、CAS 谓词、已 IO/未 IO 不决定匹配）+ G3 窗 2（reconcile SQL 成功后命题 B，折叠含该 seq reconcile/diff）。

**V14-EFF-6 provider at-least-once 与错误码乘积表（完成闭集）**〔P0〕provider effect 出生边见 EFF-1（start_attempt 同事务插 `started`+attempt 1+`fencing_gen=1`；**无 reclaim**；attempt 2 不换 effect 行；第 3 次需求不插行 → `failed(attempt_exhausted)`，attempt 行数保持 2）。attempt 事件**不属** INV-4 与 INV-3-A 任何比较面（投影按 kind 丢弃，V14-HARN-4）。

**provider 完成 = INV-1 第 3 类 judgment 提交函数内的原子动作**（同一事务，缺一不可）：校验 attempt（`attempt_id` 非空绑定、`fencing_gen` 一致、attempt 未消耗）→ 写 judgment 或错误 judgment → 消耗 attempt → 按乘积表改 effect。**不是**第 4 类 tool receipt。EFF-1「`started→succeeded|failed` 仅 tool 类且带 receipt」**不覆盖 provider**。**迟到提交零更新**（attempt 已消耗、effect 已终态、fencing 不一致、或已 `attempt_exhausted` → 不写 judgment、不改 effect、不消耗第二次）。

**错误码乘积表（写死，五行均在上述同一事务内落地）**：

| 错误码 | judgment | attempt | effect |
|---|---|---|---|
| `ok` | 写一代成功 judgment | 消耗 attempt | `succeeded` |
| `timeout` / `transport_error` | 不写成功 judgment | 记已用 attempt | 保持 `started`（未达 2 可再 start_attempt） |
| `content_invalid` / `budget_exceeded` | 写错误 judgment 行（**唯一终结边**） | 停止 | `failed` |

第 3 次需求 → `attempt_exhausted`（不经上表的错误 judgment 行；不插 attempt 行）。`content_invalid` / `budget_exceeded` **不得**另开一条 `started→failed` 边绕过错误 judgment 行。

**INV-3 命题 A/B 等价仅适用于 FakeLLM 路径与已提交 judgment 的 provider 路径**；G4 kill gate 不得把 provider 未提交 judgment 窗口宣称为 A/B 等价。检查：G4 gate（提交函数原子性：校验→写 judgment→消耗 attempt→改 effect 同事务；迟到零更新；乘积表五行逐行断言；attempt 上限；failed 的终结边只有错误 judgment 行；attempt 行数=2；第 3 次不插行；独立 judgment 世代断言）。

### 3.2 write/edit 口岸（G1）

**V14-TOOL-1**〔P0〕write/edit 是 mutating 口岸：结果改变工作区文件系统状态，**准入走 grant 门控（V14-APPR-5 / TOOL-6 准入合一）**：命中 grant → 建已 approved proposal + 插 `planned` effect；未命中 grant → **准入拒绝，零 proposal 零 effect**（无逐次人批，产品语义登记 §0 V14-ARCH-6）。**write 语义 = create-only**：目标已存在即拒绝；覆盖一律走 edit。**edit 语义 = replace-existing**：提案构建要求**目标存在且非 symlink**，否则拒绝不建 effect（与 write create-only 配对）。检查：G1 gate（准入两分支 + write create-only 负例 + edit 目标缺失/symlink 拒绝 + 拒绝路径工作区字节零变化）。

**V14-TOOL-2 diff 协议（单格式 + 规范编码终版）**〔P0〕diff 只有一种格式：每 path 记 `{old_exists, old_sha256, old_mode, new_exists, new_sha256, new_mode, payload 编码}`——payload 编码 = 文本 utf8 / 二进制 base64；覆盖创建（old_exists=false）、删除（new_exists=false）、二进制、symlink 拒绝策略。**禁止** old/new 成对与 unified diff 二选一的旧措辞。write 的 diff = old 全空（old_exists=false）。**字节语法（digest 权威，写死）**：diff_digest、全观测 body 与 payload_digest 的预映像都是 UTF-8 字节串（无 BOM），在送入 jsonb **之前**计算，**不用 `jsonb::text`**。sha256 落库与比较用小写十六进制 64 字符。

共用词法：记录分隔 = `0x0A`，每条记录以它结束（含最后一条），无 `0x0D`。字段分隔 = `0x1F`。字段内禁止裸 `0x1F` / `0x0A`。**NULL** = 四字节 `null`（`6e 75 6c 6c`），无引号。**空串** = 零长度字段（相邻分隔符）。二者不得互换。存在位 = 单字节 `0` 或 `1`。整数 = 十进制 ASCII、无前导零、无正号；零 = `0`；负数 exit_code 允许前导 `-`。**mode** = 八进制定宽 4 位、前导零（`0644`、`0755`），只编码权限低 12 位；缺失 = `null`，禁止用 `0000` 代替缺失；不定宽（`644`）必须拒绝。sha256 字段 = 小写十六进制 64 字符，缺失 = `null`。file_type 闭集 = `file | dir | absent`（symlink 不编码，一律拒绝）。

路径 = 相对 workspace 根的原始字节，禁止绝对路径、禁止 `..`、禁止以 `/` 开头、禁止 NUL。排序键 = 原始字节 memcmp，**禁止** Unicode 码点序与 NFC/NFD。合法 UTF-8 路径写入字段时 = JSON 字符串（含引号；RFC 8259：`"` 与 `\` 及 U+0000–U+001F 转义；`/` 不转义；非 ASCII **原样 UTF-8**，不写 `\uXXXX`；控制字符优先 `\b \f \n \r \t`，其余 `\u00` + 两位小写十六进制，与 `json.dumps(s, ensure_ascii=False)` 的字符串字节一致）。非法 UTF-8 路径不得进 JSON 字符串，字段 = `b64:` + base64(原始字节)。

payload 标签：`utf8:` + JSON 字符串（合法 UTF-8 且不含 NUL；空内容 = `utf8:""`）；`b64:` + base64（含 NUL、非法 UTF-8、或声明为二进制）。删除（`new_exists=0`）时 payload = `null`，且 new_sha256 / new_mode = `null`。base64 = RFC 4648 标准字母表 `A–Z a–z 0–9 + /`，`=` 填充到 4 的倍数，无换行，禁止 URL-safe。

**diff 记录字段序**（一条 path 一行，按路径原始字节升序）：`path, old_exists, old_sha256, old_mode, new_exists, new_sha256, new_mode, payload`。**全观测记录字段序**：`path, exists, file_type, mode, sha256`。**payload_digest 预映像**（单行）：`kind, effect_id, attempt_id, request_id, fencing_gen, status, exit_code, body_digest`。mutating tool：`attempt_id` 与 `request_id` 均为 `null`（不是空串），body_digest = diff_digest 的 64 hex。read-only tool：`attempt_id` 非空，`request_id` = `null`。probe：`request_id` 非空；preflight 的 `effect_id` 允许 `null`；body_digest = 全观测记录字节的 sha256 的 64 hex。provider 完成预映像 kind 字面 = `judgment`，`attempt_id` 非空，不走 tool receipt。stdout/stderr **不进** digest 预映像；事件规范编码里空 stdout = 零长度字段，缺失 stdout = `null`。

**黄金向量集**（字节即权威；下表 sha256 由本语法生成，G1 digest gate 必须重算并逐项相等，不得另写第二套语法）。固定替身：effect `00000000-0000-4000-8000-000000000001`、attempt `…0002`、request `…0003`；body 占位 = 空串 sha256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`。

| id | 覆盖 | sha256 |
|---|---|---|
| V-null | 双侧不存在，哈希/mode/payload 全 `null` | `76dc8cf099b211fd73d51fbabdf1679d29d33f0550aff4b7e2daba98ee80c3fb` |
| V-empty | 创建空文件，mode `0644`，payload `utf8:""` | `1c25e45d20dafb98b107d9dec18819e783875fe99d6ce484364bd16374afd7aa` |
| V-uni | 路径与文本均为 `文`（UTF-8 `e6 96 87`，不 `\u` 转义），mode `0644` | `99d94f892b6fc495d63a1c7fc483fdcbeb3bdf53cea50235ecda0a13ce8a543a` |
| V-quote | 文本字节 `5c 22`（反斜杠、引号）；payload 字段十六进制 = `757466383a225c5c5c2222` | `ec54cdb8767f323e618c06554a5f9c9b784add76a2f8449fad6aa74becc01b0e` |
| V-nul | payload 含 `00` → `b64:AA==`，不得 `utf8:` | `7607f0af9619b89fad2131319eb95a0e57f5e3e013e3fb1b7158522a3dcfa1e8` |
| V-bin | 非法 UTF-8 `ff` → `b64:/w==` | `449d933a7977b26a5c71ef7da898eef671a7115a0396536131fbdf5f6eefdaf9` |
| V-del | 删除（old 为字节 `x`，new_* 与 payload = `null`） | `2aa4fdd375667cf23a75ddcffdd50ecd43bcf6b63c8aef05d83ebbe9ebc4b8b4` |
| V-multi | 输入序 `b` 然后 `a`；规范字节必须 `a` 行在前，`b` 行 mode `0755` | `51a96087860c8b66d5b85b4f8b70f21f316e4c55a7ec5e3af20c5d5b82176107` |
| V-mode | mode `0755` 合法；`644` 拒绝 | `6f8ca1a7ec7cec7d64436d910577f3ca712f8d6d55b3cfd6448f7112aa0fe114` |
| V-stdout | 空 stdout（零长度字段）后接 null 字段，预映像 hex `1f6e756c6c0a`；空串 ≠ `null` | `545538c936e17a843ff37671afe8d5d7cb7a8c4574c2443c60adc4d45635ab66` |
| V-rcpt-tool | mutating tool：`attempt_id` 与 `request_id` 均为 `null` | `099c357c9b4e04a22ec9e39ed5096fdd3c03718d08c8c3c2362cb5842a08e808` |
| V-rcpt-ro | read-only tool：`attempt_id` 非空，`request_id` = `null`，exit_code `0` | `dc882981d9a45f57f75244fb36ac2c03043340a0f0f34cce08505c000bcf9da5` |
| V-rcpt-pre | preflight_probe：`effect_id` = `null`，`request_id` 非空 | `e58e1063246a55c09d8ba378eedb1bc0ade69c038ca8672cbf3c24e5612027ea` |
| V-rcpt-claim | claim_probe：`effect_id` 与 `request_id` 均非空，`attempt_id` = `null` | `9b7847e05a291bdf8f42ad9d16182b1233b5622b205fe894d1d73d7a589bdd03` |
| V-rcpt-resume | resume_probe：同上 nullable | `3caf9703cf07f53b13c8b50afe5c03dbe530bdd1df7a438d63672e10b10369bd` |
| V-rcpt-recon | reconcile_probe：同上 nullable | `fe7faa71ae19f4c935f5ac5d2bfced6f9ec7e2816a02df540f5695ab6387a148` |
| V-rcpt-prov | provider 完成 kind=`judgment`：`attempt_id` 非空，`request_id` = `null` | `974fef1368e6d444aa15c656adac8b5565c50ac8691d0d1b01f802d00deef70a` |

diff 是 events 流的一部分（落 `tool/result` 载荷），供审批渲染、INV-3 命题 B 重放与 gate 断言。检查：G1 gate 对 diff 载荷结构断言（含创建/删除/二进制/symlink 负例 + 上表黄金向量逐项 sha256 + mode 不定宽拒绝 + 空 stdout ≠ null）。

**V14-TOOL-3**〔P0〕write/edit 执行拆三步：① **提案构建（三段式）**：短事务登记只读 lease **并创建不可变 preflight observation request** 后提交 → **事务外** worker 读文件并提交 `preflight_probe`（绑定 `request_id`）→ 新事务写 proposal 释放 lease（**文件 IO 永不在打开的 DB 事务内**，v8 不变量 4；preflight read 不属 effect IO，EFF-2）；② **等待（仅 requested 才存在）**：`await_approval` 仅存在于 exec mutating 的 requested proposal（exec mutating 人批，TOOL-6）；write/edit 无等待相（grant 命中即 approved 直入 claim）；等待期游标停 `await_approval`，不持任何 claim（V14-APPR-4）；③ **claim/apply**（取 workspace 排他锁（EFF-4）→ pre-claim `claim_probe` → claim effect → 锁内另建 claim_probe 复算（EFF-3）→ 原子写 → complete）。检查：G1 gate 三步各断言 claim 生命周期、preflight/claim_probe 请求先于 IO、三段构建顺序。

### 3.3 审批协议（V14-APPR，G1 交付状态机与批准命令；G2 只加 exec 策略）

**V14-APPR-1**〔P0〕proposal 不可变、一次构建。**摘要双型（写死）**：write/edit 摘要 = 合同版本、generation、工具名、完整参数、cwd、受控环境标识、workspace 基线哈希、**规范化 diff**、有效期（expires_at）、可空 `grant_id`（入摘要哈希；比较面不直接比该哈希字节，按 V14-HARN-4 派生字段表 canonicalize 后重算）；**exec 摘要 = verb + 类型化 argv + envp 闭集 + cwd + 基线哈希 + 有效期（diff 仅在事后 `tool/result`，不入 exec 摘要）**。检查：G1 gate 摘要双型完备性断言。

**V14-APPR-2 批准与消费（谓词定位 + 单次消费 + 竞争审计）**〔P0〕批准只批摘要（哈希锚定）。**批准输入禁止携带代理键字面量**（proposal_id、session_id 等）：approve/deny/expire/reconcile **不收 session_id / proposal_id / principal / now**，目标用谓词选（如「本会话唯一 requested proposal」，会话来自**认证连接绑定**），命中非唯一即拒绝。**条件更新写死**：approve/deny/expire 用 `WHERE state=requested` 条件更新，胜负各写**竞争胜负审计事件**。消费：`planned→claimed` 与 `proposal approved→consumed` 同事务单次消费（EFF-1 后置条件表）；执行 claim 时 CAS 重验（摘要哈希一致、状态、未过期、workspace 基线仍匹配、grant 未撤销未过期（APPR-5）），任一不符即按 EFF-1 后置条件表处置并留痕。检查：G1 gate（谓词定位非唯一负例/重放/篡改/基线漂移负例/竞争胜负审计事件断言）。

**V14-APPR-3 effective_now（DB 时钟；test-only 注入）**〔P0〕生产 approve/deny/expire/reconcile **不接受调用方 now、不读调用方可写会话变量**；effective_now 来自 DB 时钟。仅**测试专用角色**经隔离 test-only 入口注入 now。所有 CAS 用同一 effective_now 在同事务检查 `expires_at`。检查：G1 gate（生产入口无 now 参数 source 断言 + test-only 注入正例 + 共享 CAS 时钟断言）。

**V14-APPR-4 等待与串行（单名额在请求创建时执法）**〔P0〕proposal 状态机：**`approved` 是显式非终态**。出边：`requested → approved | denied | expired`；`approved → consumed`（与 effect claim 同事务）；`approved → expired`（claim 谓词失败/到期时，EFF-1 后置条件表；expired 为过期终态**唯一**落点）。**终态闭集 = `denied | expired | consumed`**（approved 不是终态，不得写成三择终态）。超时判定用 APPR-3 的 effective_now（expire_due 见 EFF-4）。等待期游标停 `await_approval`：不持 claim、不占 beat 前进位；批准后重新走 V14-EFF claim。**mutating 单名额执法时点 = 请求创建时**，执法句以三条件为准：**已存在 requested proposal、未消费 approved proposal、或未终态 mutating effect** → 新 mutating 请求拒绝并留痕。不得把三条件缩写成「仅存在未终态 proposal」。deny/过期/失败路径**释放名额**。检查：G1 gate（创建时三条件拒绝负例/名额释放/等待期 beat 推进/approved 非终态）。

**V14-APPR-5 grant 字段全集与命中规则（终版）**〔P0〕grant 行字段冻结：`grant_id / granting_principal / session_id / workspace_id / tool_set / argument_schema / cwd 根 / contract_version / generation / issued_at / expires_at / revoked_at`。**grant 行除 `revoked_at` 空→非空外禁 UPDATE**。**拒签谓词（写死）= `workspace_mode=mutating` 的 exec（动词目录恰 {run-test, build} 内一切 mutating 动词；无名为 bash 的动词）一律拒签且总建 requested——按 workspace_mode 判，勿按工具名字符串特判**。**grant 命中 = 请求创建事务内的内部动作**（非独立入口）：命中即在同事务生成不可变 proposal 并由 SQL 转 `approved`（principal 记录 = granting_principal），EXECUTE 权限对 harness 与 service role 一律 REVOKE；每次命中仍单次消费（APPR-2）；命中已 approved 的请求直入 claim（无等待相，TOOL-3）。**命中合取（写死）**：工具名 ∈ tool_set ∧ 每受影响相对路径匹配 glob ∧ cwd 在 grant 根下 ∧ workspace_id/session_id/contract_version/generation 相等 ∧ 未撤销未过期 ∧ 非路径标量过 argument_schema；**正文/diff/哈希不参与比较**。**两检查点（写死）**：① claim CAS 时见撤销/过期 → EFF-1 后置条件表 grant 行（**此时无 IO**）；② **receipt 接受时见撤销 → 不回滚已 started 的 IO**，终态按 receipt/EFF-5。模式闭集 = 工具名 + 相对路径 glob。签发/撤销/越界负例进 `test_approval`。检查：G1 gate（字段完备/签发/撤销/越界/mutating-exec 拒签（按 workspace_mode，不按工具名字符串）/命中合取逐项/内部动作 + REVOKE 断言/两检查点分支/命中直入 claim/grant 行禁 UPDATE 除 revoked_at）。

**V14-APPR-6 principal 与签发封死（DB 认证，fail closed）**〔P0〕审批/签发/撤销函数**不接受 principal 参数**（issue_grant/revoke_grant 亦不收 session_id/now/proposal_id；`granting_principal` 取当前认证 principal）。**权限封死（写死）**：`issue_grant / revoke_grant / approve / deny / expire / reconcile` 全部 **REVOKE FROM PUBLIC** + 从 harness 与 service role REVOKE，**EXECUTE 仅授认证 approver 角色**。生产路径须有与实际 approver 一一对应的 **DB 认证 principal**；共享 service role 不得执行审批；无法映射即 fail closed（拒绝并留痕）。**会话绑定 = 认证时写连接不可变属性**；审批/签发不读调用方可写 GUC。Chainlit 部署的身份映射 = 受信连接 / 角色属性。principal 写 events。检查：G1 gate（principal 映射断言 + REVOKE FROM PUBLIC 断言 + service role 拒绝 + 无法映射 fail-closed 负例 + 签发参数面断言）。

**V14-APPR-7 测试纪律**〔P0〕禁止直改审批/effect 状态表；approve/deny/expire/reconcile 一律走产品 SQL 命令；时钟注入仅经 APPR-3 的 test-only 入口。检查：G1 起全部审批相关 gate（source 断言无裸 DML）。

### 3.4 exec/glob/grep 执行面（G2，exec=闭集命令执行器）

**V14-TOOL-4 闭集命令执行器（进程边界封死）**〔P0〕执行方式 = `execve(动词目录固定可执行文件绝对路径 + 版本摘要, argv 数组)`——禁止 `shell=True`、禁止 `sh -c`、禁止任何字符串拼接执行。**verb executable = digest 校验的受信二进制，禁脚本、禁 shebang**；verb 本体与其子进程树禁调 shell/解释器（source gate 扫 `sh -c` / `bash -c` / `shell=True` / `os.system` / `os.popen` / `create_subprocess_shell`）。argv 段只有两种：目录固定字面量，或**类型化参数**（enum / int / bool / 相对路径闭集；路径拒绝对路径、`..`、NUL）。**execve 的 envp = 闭集**（空或合同点名键），禁止继承调用方环境。每个 verb 声明 `workspace_mode`：`read_only` | `mutating`；**未声明 workspace_mode 即拒绝执行**。**动词目录初始裁决（进合同 v2 附录）**：`run-test = read_only`、`build = mutating`；目录恰 = {run-test, build}。**mutating 动词与 write/edit 共享同一把 apply 锁与同一状态图**（EFF-4；锁覆盖外部进程运行期间——受控 writer 串行是设计语义）；started 前锁内基线重算；seq 在 claim 已提交事务分配；receipt 丢失 → `unknown` 阻塞 workspace（EFF-5）；**exec 已跑且全观测 `{exists,file_type,mode,sha256}` 与锁内基线不一致 → `unknown`，不重试**（与 EFF-3 receipt 接受谓词同一相等，不只 hash）。**路径解析**：从 workspace root dirfd 逐级 no-follow（openat/renameat、`RESOLVE_BENEATH` 语义），任一父分量是 symlink 即拒。**超时 kill 整个进程组**。围栏：工作区根约束、超时、输出上限——**输出超限 = effect failed，不是截断成功**。必测负例：参数含 shell 元字符时子进程 argv 逐字节等于该值且被拒或仅作字面量；**verb 内部重解释 argv；父目录 symlink 越界；检查后替换（TOCTOU）竞态**；**exec×write 并发/kill/基线漂移**。加动词 = 合同面变更（§2.3）。任意 shell 整体移出 v14 范围（§9）。检查：G2 gate（上述全部正/负例；source 断言）。

**V14-TOOL-5**〔P0〕glob/grep 是只读口岸：**输入、结果与错误码闭集**，围栏与既有 read 口岸同级（TP-WIRE / TP-FS 纪律），无审批环；effect 走 EFF-1 出生三分的 read-only 分支（无 proposal、同事务 started+attempt 1+fencing_gen=1、无 claimed 停留、无锁无 seq、至多 1 次再开 attempt、reclaim 不要求 workspace 锁）。检查：G2 gate（闭集与围栏负例 + read-only 出生路径断言）。

**V14-TOOL-6 准入合一与四路径（产品语义裁决）**〔P0〕**单一准入路径**：

- **exec mutating（目录 {run-test, build} 中 `workspace_mode=mutating` 的动词；无 bash）**：**总建 `requested` proposal，不自动批**（逐次人批；无人动作到 expires_at → `expired`；显式 deny → `denied`；不收 grant，APPR-5 拒签谓词）。
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
   - **代理键 allowlist（写死，本版 bump 为十类，各自独立前缀）**：`session_id→$s`、`event_id→$ev`、`effect_id→$ef`、`judgment_id→$j`、`proposal_id→$p`、`attempt_id→$at`、`grant_id→$g`、`workspace_id→$w`、`request_id→$rq`、`token_id→$tk` 及递归出现的同值——按首次出现顺序编号（`$s1/$ev3/…`），同值同替换、跨行一致；再增须再 bump；
   - **volatile metadata 键表（与时间分开，写死）**：`ts / wall_time / created_at / pid / lsn / expires_at / started_at / finished_at / duration_ms / elapsed_ms / lease_until / lease_owner / issued_at / revoked_at / effective_now / fencing_gen` → 类型占位符（`fencing_gen` 在杀/不杀世界线可分叉，比较面用占位符；单调与 CAS 由独立 fencing gate 断言）；
   - **workspace 根 → `$ws`**；事件内文件路径一律以**相对根形式**存储；
   - **attempt 事件按 kind 丢弃**（不属任何比较面，EFF-6）；`workspace_effect_seq` 每 workspace 从 1 单调、同构操作两壳同值 → **原样入比较面（不替换）**；
   - **派生字段表（对 A 与 INV-4 两比较面都生效，写死）**：含代理 ID 的哈希必须二择一，未列入者不得入任一比较面，新增须 bump。`payload_digest` = **排除 + 独立 digest gate 验证**（G1，含 TOOL-2 黄金向量）。proposal 摘要哈希与 approval 摘要哈希（含 `grant_id` 等代理 ID）= **canonicalize 输入重算**（按本条代理键替换后重算再比较，不比较原始哈希字节）。`diff_digest` 预映像不含代理 ID（TOOL-2）→ 原样入比较面；若实现期发现预映像含代理 ID，必须改为 canonicalize 重算，不得静默排除；
   - **封闭性执法（字符串模式，写死）**：键不在 volatile 表的标量值匹配 RFC3339 时间串或纯数字 epoch、或未列名的 `*_at / *_ms / *_until / *_pid / *_lsn`、**timestamptz 型标量**、绝对路径、未识别 uuid → **gate 失败**，新增类别必须 bump 本规范（偏差台账无权松动）。**uuid 规则仅作用于整个 jsonb 标量值 = uuid 形**（对 stdout/stderr/diff 等文本载荷不做子串扫描）；**字符串先做 `$ws` 前缀替换，替换后仍残留绝对路径才失败**；digest 规范化用显式保序文本编码（V14-TOOL-2），不经 jsonb::text；
   - **比较（写死）**：每流按 `(session_id, seq)` **ORDER BY seq** 后投影 `::text` 逐字节相等（逐行，服务端执行）。
4. **两个比较面**：**INV-4 双壳等价**用 §4.3 全流（两壳无杀点；比较 = 服务端投影 `::text` 逐字节相等）。**INV-3 命题 A**用独立语义子流。**A 面字面 kind 白名单（〔P0〕，增 kind 须 bump）**：入 A = 用户提交、judgment 终态、proposal 终态仅 `consumed` / `denied` / `expired`（`requested` / `approved` 不入）、`tool/result`、effect 终态（含字面 `effect/failed/sql`）、`reconcile/diff`。不入 A = beat 事件、grant 变更、`resume_probe` / `preflight_probe` / `claim_probe` / `reconcile_probe`、attempt、lease reclaim。probe 类入 INV-4 全流（事实事件），不入 A。**A 允许表是〔P0〕比较面，偏差台账不能扩**。批准输入禁携带代理键字面量（V14-APPR-2）。

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

**V14-BENCH-4**〔P0〕复用 pi_parity 归一 trace 基建做 v14 vs pi 对照：归一 schema-v2 trace、canonical phases、drivers（`v13/pi_parity/` 既有 `pig_driver` / `piswift_driver` 与 pi 侧驱动）产出各方 trace，v14 侧新增同格式 trace 生成器。报告（工件入库 `v14/bench/`）至少含：任务通过率、拍数/工具调用数、token 成本、events 流形状对照，并**单列** ARCH-6「无任意 shell」：exec 目录恰 {run-test, build}，不得把该成绩记为 pi bash 覆盖或 bash 通过率。检查：G5 gate（trace 格式一致性断言 + 报告工件存在且字段齐全）。

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

范围：合同 v2 bump 与回填（§2.3）+ 效果协议（§3.1 全部：出生统一、fencing 初值、claim 后置条件表、纯谓词判别式、屏障含越序、两阶段 reconcile、expire_due）+ write/edit 口岸与准入合一（§3.2）+ diff 单格式与规范编码（V14-TOOL-2）+ 审批协议全套（§3.3，含 grant 命中合取与签发封死）。
提交集合（枚举，见 V14-PROC-3）：**K**（内核提交：合同 bump 文档 + v14 迁移 SQL（含 contract_version/generation 回填列）+ 允许名单）→ **S**（实现提交：口岸、目录行、gate）。
gate 验收（写死）：
- 〔P0〕`v14/tools/test_tools_v2.py`（required）exit 0：EFF-1 转移表全路径 + **后置条件表三行逐列**（短路序 ①时间 ②grant ③基线，先命中独占单审计；基线行 proposal→expired 且释放名额；pre-apply unlock+归还专属连接；planned→claimed 无已 IO→unknown）+ 非法转移负例；intent 先于 IO；**出生统一**（三类创建事务 fencing_gen=1；read-only 同事务 started+attempt 1、无 claimed 停留；provider 无 reclaim；mutating receipt attempt_id=JSON null 且无 attempt 行；read-only receipt attempt_id 非空绑定；read-only reclaim 不要求 workspace 锁）；**fencing**（claimed→started 仅基线匹配后、0 行零 IO、mutating reclaim 持锁前置 + generation 递增、probe 败者零 IO、过期 receipt 拒绝落库）；try-lock 不可得留态重试；**屏障只统计 mutating** + 未终态 claimed/started/unknown 时禁 claim 新 mutating（越序负例）+ reclaim 不绕屏障；seq 分配点恰 {claim 成功, 进入 degraded}，stale 不分配，horizon 冻结；write/edit 幸福路径 diff 单格式与字节语法逐项（排序/null 与空串区分/base64 alphabet+padding/mode 定宽/黄金向量 sha256；创建/删除/二进制/symlink 拒绝）；resume 分类无 case3、整 effect 一次分类、temp 可从 proposal payload 重建；receipt 接受谓词 = 全观测相等负例；started 后无 receipt 禁止 started→failed；write create-only + edit 目标存在非 symlink；**准入两分支夹具**（write/edit 未命中 grant 拒绝不建行；grant 命中直入 claim）；拒绝路径工作区字节零变化；**两阶段 reconcile**（选择谓词、token 单胜者、重复/超时/进程死亡、CAS 含 workspace degraded、已 IO/未 IO 不决定匹配）；观测请求先于 probe IO、probe 失败不改 effect 态；**独立 digest 正确性 gate**（payload_digest/diff_digest 预映像 + TOOL-2 黄金向量，与两比较面分离）。
- 〔P0〕`v14/tools/test_approval.py`（required）exit 0：V14-APPR-1..7 全断言（**摘要双型**（write/edit 含 diff；exec=verb+argv+envp）/谓词定位非唯一负例/WHERE state=requested 条件更新与竞争胜负审计/单次消费 CAS/状态机含 approved→consumed 与 approved→expired/生产无 now 参数 + test-only 注入/请求创建时单名额执法与释放/等待断言**用 exec requested 夹具**（write/edit 无等待相）/grant 字段全集 + 签发/撤销/越界 + **mutating-exec 拒签（按 workspace_mode，不按工具名字符串）** + 命中合取逐项 + 内部动作 EXECUTE REVOKE（harness 与 service role）+ **两检查点**（claim CAS 见撤销零 IO；receipt 接受见撤销不回滚 IO）+ 命中直入 claim/**REVOKE FROM PUBLIC 全函数面** + 签发不收 principal/session_id/now/proposal_id + grant 行禁 UPDATE 除 revoked_at/principal 映射 fail-closed/无裸 DML/approved 为显式非终态/名额执法以三条件为准不得缩写成仅未终态 proposal）。
- 〔P0〕`v14/tools/test_contract_v2.py`（required）exit 0：contract-2 已 bump；v1 条款字节零改动；回填列默认值与既有 request 回填；v1 排队请求走 v1 handler + v2 新建请求两路径；无法解析绑定拒绝创建负例；`v13/**/*.sql` 零 diff。
- 〔P0〕v13 全量零回归（E4，required）。

### G2 执行面（只加 exec 策略与执行口岸）

范围：闭集命令执行器（§3.4，进程边界封死 + 目录模式裁决）+ glob/grep 只读口岸（read-only 出生分支）+ govern/human route 审批环接线（四路径拆死；审批状态机已在 G1）。
gate 验收（写死）：
- 〔P0〕`v14/exec/test_exec.py`（required）exit 0：execve/无 shell（source 断言含六模式扫描）；verb executable digest 校验受信二进制（禁脚本/shebang）；envp 闭集（禁继承）；目录恰 = {run-test, build} 且 **run-test=read_only / build=mutating 模式断言**；workspace_mode 声明执法；类型化参数域负例；shell 元字符 argv 逐字节负例；verb 内部重解释 argv 负例；父目录 symlink 越界负例（no-follow/dirfd/RESOLVE_BENEATH）；TOCTOU 竞态负例；超时 kill 整个进程组；glob/grep 闭集与围栏负例 + read-only 出生路径（同事务 started+attempt 1、无 claimed 停留、reclaim 不要求 workspace 锁）；exec 围栏（越界/超时/超限=failed）负例；**exec mutating 与 write 共享锁/状态图：exec×write 并发、kill（receipt 丢失→unknown 阻塞）、基线漂移三组测试**；exec 已跑且全观测与锁内基线不一致→unknown 不重试。
- 〔P0〕`v14/exec/test_govern_route.py`（required）exit 0：四条审批路径拆死（write/edit 未命中 grant 准入拒绝零 proposal 零 effect；exec mutating 总建 requested→人批 approved；denied；expired）、审批命令经 SQL 面、留痕 events、human route 队列可由第二壳观察。
- 〔P0〕v13 全量零回归（E4）+ G1 gate 复跑绿。

### G3 harness MVP

范围：beat driver 提炼（§4.1）+ Chainlit 窗 + `v14_wake` LISTEN/NOTIFY 终版（§4.2）+ psql submit/observe demo（§4.3）+ 双壳等价 + 会话可弃（两杀点）+ 薄度执法。
gate 验收（写死）：
- 〔P0〕`v14/harness/test_resume.py`（required）exit 0：**SIGKILL 进程组**实证杀（非模拟），杀点为**确定性测试缝**，四钉写死：① 窗 1 = temp 已 fsync 且 rename 未发生；② started 之后、temp 创建之前；③ temp 部分写入；④ 窗 2 = 子进程 `execve` 之后、receipt 之前，reconcile SQL 成功后断言命题 B。进程组只含 driver 与其 worker/provider 子进程；数据库进程与测试控制器在组外。窗 1 与杀点 ②③ → resume_probe + EFF-3 分类（目标仍为完整基线且 temp 未用于 rename 时从 proposal payload 重建 temp 续 case2；只有目标或已 rename 路径不可解释才 unknown）+ **命题 A 子流断言**（A 字面白名单逐行相等 + `tool/result` 规范 diff 与 `workspace_effect_seq` 相同）+ 命题 B 断言。窗 2 → unknown + 两阶段 reconcile 走通；**reconcile SQL 成功后断言命题 B**（折叠含该 seq 的 reconcile/diff），只排除 reconcile 前的 unknown 前缀。另钉 **cleanup gate**：receipt 已提交后杀 driver、cleanup beat 未执行；resume 后幂等 cleanup beat 清掉 effect 专属 temp，工作区字节不变。
- 〔P0〕`v14/harness/test_dual_shell.py`（required）exit 0：两壳（脚本壳 + Chainlit 壳——经 Chainlit 无头测试模式驱动**真实 handler 模块**，禁止为 gate 另写假 handler；同一测试 principal）按 V14-HARN-4 算法比较（§4.3 **全流**、ORDER BY seq 后服务端投影 ::text 逐字节相等；两比较面均按派生字段表（payload_digest 排除、摘要哈希 canonicalize 重算）；A 面只收 HARN-4 字面白名单；workspace_effect_seq 原样入面），封闭性执法含新增键与 timestamptz 标量；两 principal 越权负例另测。**夹具义务：exec 输出用冻结字节**（build/run-test 的 stdout/stderr 预先固化）。
- 〔P0〕`v14/harness/test_thin.py`（required）exit 0：per-file 决策点计数（INV-5 上限表：driver ≤15 / handler ≤5 / 其余合计 0）+ import 前缀黑名单（六前缀）+ worker/provider 能力协议。
- 〔P0〕`v14/harness/test_listen.py`（required）exit 0：v14_wake 同事务 notify、payload 闭集、独立 autocommit 连接、初始补读、补读循环、四负例（通知合并/断线插入/查询-订阅间隙/重连无后续通知）、重连后 UI 历史从 events 重建。
- 〔P0〕psql submit/observe demo 脚本执行 exit 0。
- 〔P0〕Chainlit 依赖进入 `pyproject.toml` 与 `uv.lock` 更新同笔，且当笔全量回归绿；v13 E4 复跑绿。
- 〔P0〕`v14/regression/` sweep 上线（发现 `v14` 下全部 `test_*.py` 串行，required 零容忍、probe 照 skip 语义）。

### G4 真 provider

范围：DeepSeek 判断面产品化（provider 进程分离）+ 多轮 + compaction 只追加 + economy 整数记账（§4.4）。
gate 验收（写死）：
- 〔P0〕`v14/provider/test_deepseek.py`（required，FakeLLM 确定性部分）exit 0：同 judgment 合同双实现断言；provider 进程能力闭集（可 litellm，禁 DB/beat/写盘）；attempt 记账（start_attempt 同事务插 started+attempt 1+fencing_gen=1、无 reclaim；attempt 2 不换 effect 行；**第 3 次需求不插 attempt 行、effect→failed(attempt_exhausted)、attempt 行数保持 2**）；**完成 = 第 3 类 judgment 提交函数内原子动作**（同事务：校验 attempt→写 judgment 或错误 judgment→消耗 attempt→按乘积表改 effect；迟到提交零更新）；**错误码乘积表五行逐行断言**（ok 不带 tool receipt；content_invalid/budget_exceeded 的唯一终结边 = 错误 judgment 行）；`effect/failed/sql` 终态证据事件入投影；投影按 kind 丢弃 attempt 事件；判断错误码闭集五值同表映射、FakeLLM 与 provider 不得各增码；reconcile=独立动作（新 judgment_id）非 EFF-5 reconcile。
- 〔P0〕多轮 gate（required）exit 0：≥2 轮会话含一次中途 kill 续跑，断言按 V14-EFF-6 适用面（不宣称未提交 judgment 窗口 A/B 等价）。
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
4. **不做任意 shell 执行**：G2 exec 是闭集命令执行器（execve + 枚举动词 + 类型化参数 + 受信二进制 + 进程边界封死），目录恰 {run-test, build}；**无 bash**。这是对 pi 的重大偏差，登记于 V14-ARCH-6，基准报告不得把 exec 记为 bash 覆盖。任意 shell 待后续版本有真隔离机制（容器级）再开。
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

## 附录 B. 轮 5 → 轮 6 修订对照（oracle 双裁合并裁决 S1..S17 落点）

| # | 轮 5 裁决项（S） | 轮 6 落点 |
|---|---|---|
| S1 | 判别式改纯谓词 | V14-EFF-5：`explainable := fold(冻结基线, horizon 内更小 seq 的成功 tool diff ∪ reconcile/diff) = 全观测`；终态只由调用点写一次，谓词不赋终态。V14-EFF-3：case2 = 全观测=基线含 EMPTY ∧ temp 与 new_sha256/new_mode 一致 ∧ explainable → 持锁只做剩余 rename、禁记 stale；case2 非 explainable → 零 rename、degraded 未 IO。删 case3 与「一律 unknown」。整 effect 一次分类：任一 path 非 explainable → degraded；目标或已 rename 路径不可解释才 unknown；无 path 达目标态且全 explainable → failed(stale)；全 case1 → succeeded；仅 1+2 → 只重放 case2 后 succeeded |
| S2 | degraded 出口 | V14-EFF-5：reconcile CAS = `state IN ('unknown','failed') AND workspace degraded`；追加 reconcile/diff + 受信全观测、清 degraded、终态=本次 reconciled_outcome。已 IO/未 IO 只决定 reconciled_outcome 默认建议，不决定匹配 |
| S3 | seq 唯一分配点 | V14-EFF-4：分配点集合恰 = {claim 成功, 进入 degraded}，互斥、各自已提交事务、从 1 单调。未 degraded 的 claim 失败与 failed(stale) 不分配。reconcile/diff 复用已有 seq。「更小 seq」= 比较时冻结的 candidate horizon |
| S4 | fencing 初值与出生统一 | V14-EFF-1/2：三类创建事务均写 fencing_gen=1。read-only 出生 = INSERT planned 同事务直接 started+attempt 1（无 claimed 停留）。provider start_attempt 同事务 started+attempt 1+fencing_gen=1，无 reclaim。read-only reclaim = 行级 CAS（state=started ∧ 无 receipt ∧ lease_until≤now，generation+1，不要求 workspace 锁）。mutating receipt attempt_id 规范值=JSON null 且 SQL 验证无 attempt 行；read-only/provider 完成提交 attempt_id 必须非空绑定。比较面 volatile 表补 fencing_gen（杀/不杀可分叉） |
| S5 | apply 顺序钉死 | V14-EFF-3：取锁→锁内复算基线→不符则保持 claimed（零外部 IO）按 explainable 落 failed(stale) 或 degraded/failed→基线匹配才 claimed→started→之后才写临时文件。started 后 mutating 无 receipt 只走 resume_probe/unknown/reconcile，禁无 receipt 的 started→failed |
| S6 | probe 回库通道 | V14-INV-1 / EFF-2：SQL 先建不可变 observation request（preflight 与 pre-claim baseline probe 各有身份）。第 4 类 kind = tool / resume_probe / preflight_probe / claim_probe，外加 reconcile_probe（S13 同轮并入，仍是第 4 类，不是第五类提交）+ request_id 绑定。digest 预映像、fencing、投影归类（probe 不入 A、入全流）、失败/超时边（request 终态 failed/timeout，effect/proposal 态不变）同轮冻结 |
| S7 | provider 完成闭集化 | V14-EFF-6：provider 完成 = 第 3 类 judgment 提交函数内原子动作（同事务：校验 attempt→写 judgment/错误 judgment→消耗 attempt→按乘积表改 effect）。EFF-1「仅当带 receipt」只限定 tool 类。content_invalid/budget_exceeded → failed，唯一终结边 = 错误 judgment 行。第 3 次需求 → attempt_exhausted。迟到提交零更新。INV-3 适用面改为已提交 judgment |
| S8 | write/edit crash 窗 | V14-EFF-3：目标仍=完整基线 ∧ effect 私有 temp 未用于 rename → 持锁重跑 explainable 后从不可变 proposal payload 幂等重建 temp，续 case2。只有目标或已 rename 路径不可解释才 unknown。G3 四钉：窗 1=temp 已 fsync 且 rename 未发生；started 后 temp 创建前；temp 部分写入；窗 2=reconcile SQL 成功后断言命题 B（折叠含该 seq reconcile/diff），只排除 reconcile 前的 unknown 前缀 |
| S9 | 屏障与越序 | V14-EFF-4：屏障只统计 mutating。workspace 有未终态 claimed/started/unknown mutating 时不 claim 新 mutating（只许恢复既有），封 claim 后 started 前崩溃越序窗。V14-EFF-1：claim 失败短路序 ①时间 ②grant ③基线，先命中独占单审计。planned→claimed 删「已 IO→unknown」；unknown 只出现在 started 之后 |
| S10 | claim 后置条件表 | V14-EFF-1：三行扩展为完整事务后置条件表（effect/proposal/名额/审计 kind/seq/advisory lock disposition）。基线行明确 proposal→expired + 释放名额。一切 pre-apply 终结路径显式 unlock + 归还专属连接 |
| S11 | receipt 全观测 | V14-EFF-3 / TOOL-4：接受谓词与 probe 同一全观测 {exists,file_type,mode,sha256} 相等。exec 已跑且全观测与锁内基线不一致 → unknown，不重试 |
| S12 | A 面 wire kind + 派生字段表 | V14-HARN-4：A 字面 kind 白名单（effect/failed/sql 入 effect 终态；proposal 只收 consumed/denied/expired；beat/grant 变更/resume_probe/preflight_probe/claim_probe/reconcile_probe/attempt/lease reclaim 不入；增 kind 须 bump）。派生字段表对 A 与 INV-4 都生效：payload_digest=排除+独立 gate；proposal/approval 摘要哈希=canonicalize 输入重算。allowlist bump 加 request_id/token_id |
| S13 | reconcile 两阶段 | V14-EFF-5：reconciliation request/claim 行；approver SQL 原子取 token（单胜者）→ token 持有者启动 probe → probe receipt 绑 token/fencing → SQL CAS 写 reconciled_outcome+observed+reconcile/diff。重复/超时/进程死亡恢复边写死。选择谓词 = 本会话唯一 unknown 或（failed 且 workspace degraded）mutating effect |
| S14 | digest 字节语法 | V14-TOOL-2：完整 byte grammar（JSON 转义/Unicode 原样/非法 UTF-8 走 b64、mode 八进制定宽 4、payload 标签 utf8: 与 b64:、RFC 4648 base64+padding、0x1F/0x0A 分隔、NULL=四字节 null 与空串区分）+ 黄金向量集（空值/Unicode/反斜杠引号/NUL/二进制/删除/多路径/mode/空 stdout/每 receipt 类 nullable） |
| S15 | exec 命名统一 | 全文工具面对标口径改为 exec，目录恰 {run-test, build}。从「pi bash 覆盖」对比口径移除（ARCH-2/5）。ARCH-6 登记「无任意 shell」为对 pi 的重大偏差。BENCH-4 与 §9.4 报告口径同步。source 扫描里的 bash -c 禁令保留 |
| S16 | temp 清理责任 | V14-EFF-3：SQL 产生幂等 cleanup beat；受限 worker 确认 effect 终态后清 effect 专属 temp；不改工作区语义、可重复。G3「receipt 提交后杀 driver」cleanup gate |
| S17 | 杂项 | INV-4 首句改为服务端投影 ::text 逐字节相等。APPR-4 状态机补出态 approved（非终态；终态闭集=denied/expired/consumed）；名额执法句以三条件为准。EFF-4 外部写入两句合一（受控面检测点=degraded，点外不给更强保证）。文件头第 5 版基线 = `b5ee119`；第 6 版不自含自身哈希 |

