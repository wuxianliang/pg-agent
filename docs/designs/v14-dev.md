# PG 原生 Pi 对标 Coding Agent（v14）开发规范

> 状态：草稿第 1 版，待 oracle 对抗评审。冻结标准：评审至 0 P0 / 0 P1（沿用 v8/v10 冻结惯例，最多 3 轮）。
> 撰写日期：2026-09-28。工作分支：`v14-dev`。
> 效力：本文件只冻结设计，不实现；不改变 v8 / v10 / v13 已冻结面；与既有文档的合同关系见 §2。
> 上游裁决：`prompt-exports/loop-orchestrate-v14-runs.md`（父循环台账，轮 0 合并 9177ab5 后切出 v14-dev）。
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
| 判断 | 进程内模型调用 | SQL 面 `v13_needed_judgments` 发起，回答落 judgment 记录 |
| 载体 | TUI（进程内终端 UI） | 可丢弃窗口（Chainlit / 脚本 / psql 三壳等价） |
| 崩溃语义 | 进程死即会话死 | kill 载体 → resume → 终态不变（gate 实证） |

仿的是：工具集形状（write/edit/bash/glob/grep）、REPL 对话体验、基准任务成绩。不仿的是：进程内循环、进程内事实源、TUI 耦合。检查：设计评审对照本表；G3 双壳/可弃 gate。

### 0.3 Chainlit 使用约束

**V14-ARCH-3**〔P0〕Chainlit handler 只允许两种动作：**submit**（把用户输入经 SQL 命令提交进库）与 **observe**（LISTEN 事件流 → 渲染）。UI 历史从 events 表重建；Chainlit 会话内存不得成为事实源（INV-6）。检查：source gate 静态扫描 handler 模块（见 V14-HARN-6）。

**V14-ARCH-4**〔P0〕明示反模式：禁止照抄 Chainlit 官方教程把 agent 循环写进 `@cl.on_message` handler（在 handler 里调 LLM、跑工具、维护对话状态）。handler 内出现任何 beat 驱动、模型调用、工具分派即红。检查：source gate 断言 handler 模块不 import 判断面/工具执行模块。

### 0.4 对标面定义

**V14-ARCH-5**〔P1〕对标成立的三件事：① 工具面覆盖 pi coding agent 常用集（read/write/edit/bash/glob/grep）；② REPL 体验：Chainlit 窗口可对话驱动、可断线重连、历史完整；③ 基准：§5 任务套件上产出 v14 vs pi 对照报告。不承诺 TUI 视觉复刻、不承诺 pi 插件生态兼容。检查：G3/G5 gate 与对照报告。

## 1. 不可妥协的不变量（V14-INV-1..6）

> 本节原文照录父循环裁决，是全部后续条款的上位约束。任何 stage 设计、实现、gate 与本节冲突即无效。

**V14-INV-1 判断零外置**〔P0〕一切决策（下一步做什么、何时结束、调用什么工具、是否需要模型判断）由 SQL 面产出（advance / needed_judgments）；LLM 调用只是判断请求的数据面——问题由 SQL 面拼装、回答落 judgment 记录。harness 与 UI 不做任何策略决策。检查：G3 source gate（harness 模块无决策分支，见 INV-5）+ 既有 v13 判断面 gate 回归。

**V14-INV-2 beat 序列是数据**〔P0〕beat 序列（judge/parse/advance/claim/tool/llm/finish 一类的拍结构）是库内数据，不是代码控制流。advance 决定下一步，harness 仅执行。先例：`v13/pi_parity/test_pi_parity.py` 的 `GOLDEN_SEQUENCE`（canonical phases）与 `v13/read_tools/test_read_tools.py` / `v13/pi_ports/test_pi_ports.py` 的 ring 驱动。检查：G3 gate 断言 beat 拍落 events 表且驱动模块无硬编码序列分支。

**V14-INV-3 会话可弃**〔P0〕kill harness → 重启 resume → 终态不变。会话的全部事实在库内；载体死亡不丢失、不改变任何已落库事实，resume 后从库内状态继续走到与「不杀」相同的终态。检查：G3 杀进程续跑实证 gate（写死为 gate，非演示）。

**V14-INV-4 双壳等价**〔P0〕Chainlit 驱动与脚本驱动同输入 → 同 events 流逐字节一致。比较面定义见 V14-HARN-4（规范化投影后逐字节；非确定性列排除清单冻结）。检查：G3 双壳等价 gate。

**V14-INV-5 harness 决策点计数进 gate**〔P0〕harness 的「薄」用决策点计数量化并进 gate：harness 模块的分支决策点（`if/elif/while/for/and/or/三元` 语法节点计数）不得超过冻结上限；上限在 G3 首次实测后钉常数写入 gate，改动上限须 bump 本规范。workers（口岸子进程）豁免——豁免边界 = 经 `run_line_json` 拉起的子进程内部（先例 TP-SUB 系条款）。检查：G3 静态扫描 gate（ast 计数）。

**V14-INV-6 载体即窗口**〔P0〕UI 只 submit + LISTEN 渲染。历史从 events 表重建，Chainlit 会话内存不得成为事实源；刷新、重连、换壳后 UI 呈现完全由库内 events 决定。检查：G3 gate（重连后从表重建渲染断言）+ source gate（V14-ARCH-3/4）。

## 2. 与既有版本的关系（supersede / 继承）

### 2.1 吸收 v8-P0C（DSH 思路）

**V14-SUP-1**〔P0〕v8-P0C（`docs/plans/v8-p0c-compat-host-plan-2026-09-17.md`）的目标是「一个最小 turn 在两个运行时（v8 native loop vs pinned DSH Node host）同合同跑通等价」，其调查已确认 DSH = DeepSeek Harness（该计划 §0.1），并把 §5.2 pre-IO 落盘判定设为 C2 go/no-go。P0C 的 host 接线（C0–C6）至今未交付（G13/G14 已交付的仅是其 host 无关面）。

v14 吸收其思路并改道：

1. **等价证明的承载者换掉**：P0C 想用「接一个外部 host」证明双运行时等价；v14 用 INV-4 双壳等价（Chainlit vs 脚本，同 events 流）+ INV-3 会话可弃承担同类证明义务，不再引入 DSH host。
2. **DeepSeek 身份降维**：DeepSeek 从「被兼容的 harness 上游」变为 G4 的判断面 provider（经既有 litellm 依赖调 DeepSeek API），与 v13 既有 FakeLLM/scripted judge 形成同一 judgment 合同的两个实现。
3. **§5.2 pre-IO 落盘问题在 v14 语境的对应物**：v14 的外部 IO（工具执行、模型调用）天然不在数据库事务内（v8 不变量 4，AGENTS.md），且 beat 结算先 commit 再执行（先例 TP-HUB-2），落盘先于外部 IO 的义务由 SQL-resident 结构直接满足。

〔P1〕建议随 v14 冻结将 P0C 正式标记 superseded（P0C 计划文件加 tombstone 注记，不改其正文）。此闭合方式交 oracle 轮 1 裁决。检查：设计评审对照本条；G3 gate 承担证明义务。

### 2.2 承接 v10 硬缺口

**V14-SUP-2**〔P0〕v10-dev 冻结（2026-09-16，0 P0/0 P1）时点名的开工硬缺口 = v8 grant 模型 / generation / 插件世代 / P0C。现状核实：grant 模型与 generation 已由 `docs/plans/v8-p1-grant-generation-p0c-plan-2026-09-16.md` 交付（G10–G19b，v8 全量 24 gate 绿，台账至 A141）；P0C 见 §2.1；v10 本体未实现且保持冻结不动。

v14 与 v10 的关系：v14 **不是** v10 的实现，也不回改 v10 规格。G1/G2 在 v13 底座上自然承接残留缺口：

- G1 工具目录加 mutating 语义（§2.3 合同 v2）即「插件/工具世代」问题的 v14 承接面：目录行版本化与旧请求 handler 冻结语义（先例 TP-CAT-2）必须保持。
- G2 权限与审批环落在 v13 既有 `v13/govern/`（`v13_govern.sql` + gate）之上，只增不改；如确需动 v13 冻结面，一律走独立内核变更流程（同 §2.3 路径）。

检查：G1/G2 source gate（对 v13 冻结面零 diff，除非内核变更提交）；设计评审对照本条。

### 2.3 口岸合同 v1 → v2 bump 规则

**V14-SUP-3**〔P0〕v14 工具面扩展遵守 `docs/designs/v13-tool-ports.md` 的合同纪律：现行版本 `v13/tool-port-contract-1`（该文档 L5：改变行为必须同一提交 bump 版本号；已发布条款 ID 禁止复用；废止保留 ID）。**TP-CAT-4**（该文档 L48）明文：新口岸确需改 schema 或加列（含 `input_schema` / `mutating` / `allowlist` / `timeout_ms` / `consumes` / `produces`）时，必须拆成**独立内核变更**并 bump 合同版本，禁止夹带在口岸提交里。

v14 的 v2 bump 走法：

1. **触发点**：G1 的 write/edit 口岸需要 `mutating` 语义与 diff 协议，直接命中 TP-CAT-4 列名清单 → v2 bump 是 G1 的一部分，且是独立内核变更提交。
2. **载体（建议，交 oracle 裁决）**：在 `docs/designs/v13-tool-ports.md` 原文档就地 bump 版本号至 `v13/tool-port-contract-2` 并追加 v2 条款（mutating 语义 / diff 协议 / 审批 hook），符合该文档自身的 bump 规则；v13 原条款不删不改，v2 新条款独立编号。替代方案是另立 `docs/designs/v14-tool-ports-v2.md`——但那样 v1 文档的「同一提交 bump 本版本号」规则落空，故不推荐。
3. **同笔义务**：内核变更提交内同时包含合同 bump、schema 变更（`tools` 目录加列或等效）、既有全量 gate 复跑绿。变更落点（v13 schema SQL 受控扩展 vs v14 自有 stage SQL 累计加载）由 G1 计划裁定，本规范只冻结「同笔、独立、可回归」三义务。
4. **条款延续**：v2 完整继承 TP-INV-1..15 与 TP-WIRE / TP-FS / TP-GATE / TP-ADMIT 既有条款；新增面（mutating / diff / 审批）按 TP-ADMIT-1 十项准入清单的同等标准补齐（闭集错误码、围栏、claim 后 complete 前做 IO、preflight 纪律等）。

检查：G1 gate 断言合同版本已 bump 且 v1 条款零改动；E4 回归。

## 3. 工具面与执行面（G1/G2 冻结面）

### 3.1 write/edit 口岸（G1）

**V14-TOOL-1**〔P0〕write/edit 是 mutating 口岸：结果改变工作区文件系统状态。mutating 工具必须走审批环（§3.3），未获批的 mutating 请求不得产生文件系统效果，且失败/拒绝路径的 events 记录完整（先例：TP-HUB-6 失败不追加 `tool/result` 的纪律在 v2 中对应 mutating 的「拒绝即无效果」断言）。检查：G1 gate（拒绝路径断言工作区字节零变化）。

**V14-TOOL-2**〔P0〕diff 协议：edit 口岸的请求参数与结果必须携带可机器判定的 diff（old/new 成对、或统一 diff 格式），diff 是 events 流的一部分（落 `tool/result` 载荷），供审批环渲染与 gate 断言。格式在合同 v2 条款冻结；禁止「只给最终全文不给 diff」。检查：G1 gate 对 diff 载荷的结构断言。

**V14-TOOL-3**〔P1〕审批 hook：合同 v2 定义审批 hook 条款（何种 mutating 请求触发人审、审批状态机、超时语义）。G1 冻结条款与最小实现，G2 承接 bash 的审批路由。检查：G1 gate 审批状态机断言。

### 3.2 bash/glob/grep 执行面（G2）

**V14-TOOL-4**〔P0〕bash/glob/grep 以口岸形状接入（同 TP-WIRE 线协议与围栏纪律）：bash 是 mutating 高危口岸（强制审批环），glob/grep 是只读口岸（错误闭集、围栏与既有 read 口岸同级）。bash 的围栏（工作区根约束、超时、输出上限）条款在合同 v2 冻结。检查：G2 gate（围栏负例：越界路径/超时/超限输出各至少一条断言）。

**V14-TOOL-5**〔P0〕权限落 govern / human route 审批环：mutating 与 bash 请求的授权判定走 SQL 面（v13 既有 `v13/govern/` 面之上扩展），拒批路由到 human route（UI 呈现待审队列；审批动作本身是 SQL 命令，经 events 流留痕）。审批等待不阻塞其他 beat；被拒请求的终态与效果断言同 V14-TOOL-1。检查：G2 gate（审批环全路径：默认拒、人批过、人驳回、超时）。

## 4. harness 与载体（G3/G4 冻结面）

### 4.1 beat driver

**V14-HARN-1**〔P0〕beat driver 从既有 ring 实现提炼为可复用模块（`v14/harness/`）。提炼源（已核实）：`v13/pi_ports/test_pi_ports.py:678` `run_ring(planes)`（多在场平面同会话、mock judgment、events 计数）与 `v13/read_tools/test_read_tools.py:980` `run_ring()`；拍结构锚点 = `v13/pi_parity/test_pi_parity.py` 的 `GOLDEN_SEQUENCE`。提炼不得改动 v13 既有文件（复制提炼，非原地重构）。检查：G3 gate + source gate（v13 零 diff）。

> 注：父循环目标原文写作「test_pi_parity.run_ring」——经核实 `run_ring` 不定义于 pi_parity，实际定义于上述两处；pi_parity 提供的是 normalized schema-v2 trace 与拍结构。本规范按核实结果表述。

**V14-HARN-2**〔P0〕driver 语义：循环 = 「取 beat → 执行该拍的外部动作（若有）→ 落 events → advance」；终态判定在 SQL 面。进程可随时被杀（INV-3）。可选 pg_cron 心跳拉起 driver 属于部署面，不改变语义（beat 推进幂等）。检查：G3 杀进程续跑 gate。

### 4.2 事件流与 LISTEN/NOTIFY

**V14-HARN-3**〔P0〕事件流权威 = events 表（只追加）。观察通道用 PG LISTEN/NOTIFY（先例：`v8/closeout/v8_closeout.sql:121` `pg_notify('v8_wait', ...)`）：NOTIFY 只作唤醒信号，载荷不携带事实（事实一律回表读）。检查：G3 gate（NOTIFY 载荷不含业务事实断言 + 回表断言）。

### 4.3 双壳等价与会话可弃的比较面

**V14-HARN-4**〔P0〕INV-4 的「逐字节一致」可操作定义：比较面 = events 表按 `(session_id, seq)` 排序的规范化投影——排除列冻结为非确定性列清单（时间戳类列；清单在 G3 计划按实际表结构钉死并登记偏差台账），其余列经 canonical JSON 序列化后逐字节比较。两壳跑同输入任务，投影 diff 为空即过。检查：G3 双壳等价 gate。

**V14-HARN-5**〔P0〕psql 自足 demo：存在一条纯 psql 可复现的演示路径（SQL 提交输入、psql `LISTEN` 观察事件流），证明载体无关性。demo 脚本入库（`v14/harness/`），不依赖任何 Python 载体。检查：G3 gate（demo 脚本以 psql 执行、退出 0、事件断言）。

**V14-HARN-6**〔P0〕harness 决策点计数 gate（INV-5 的执行细则）：对 harness 模块源文件做 ast 扫描计数决策点；workers 豁免（豁免边界见 INV-5）。Chainlit handler 模块额外断言：不 import 判断面/工具执行模块（V14-ARCH-3/4）。检查：G3 静态 gate。

### 4.4 真 provider、多轮与 compaction（G4）

**V14-HARN-7**〔P0〕DeepSeek 判断面产品化：真 provider 经既有 litellm 依赖接入，实现与 FakeLLM 同一 judgment 合同（同参数/同落库/同错误闭集）。真 provider 测试分层：确定性层永远用 FakeLLM（外部 IO 不进事务，AGENTS.md / v8 不变量 4）；真 API smoke 层仅在显式提供凭证时跑，缺席时按既有 preflight 纪律输出诚实 `[SKIP]`（退出码语义沿用 TP-GATE-2 先例：断言失败 1 优先于缺席 2，缺席不是通过）。检查：G4 gate。

**V14-HARN-8**〔P0〕多轮：跨 turn 的会话连续性（上下文携带、目标推进、终态收敛）由库内状态承担，harness 重启不丢轮次。检查：G4 多轮 gate（含一次中途 kill 的多轮续跑）。

**V14-HARN-9**〔P1〕compaction 接线沿用 v8 既有 compact 语义（`docs/designs/v8-dev.md` §3.3），触发与产物落库；成本计量接 v13 既有 `v13/economy/` 面（token 用量 → economy 记录）。检查：G4 gate（compaction 后会话事实完整 + economy 记账断言）。

## 5. 基准对标（G5 冻结面）

### 5.1 任务形状

**V14-BENCH-1**〔P0〕借 PiG 任务形状（已核实：`PiG/evals/tasks/<name>/task.toml`，字段 `prompt` / `check`（shell 判定命令）/ `protected`（禁改文件）+ `files/`（任务工作区）），四任务：`add-json-flag` / `fix-off-by-one` / `rename-function` / `slow-build`。借用形状（v14 自建镜像目录），不依赖 PiG 仓库运行时；判定 = `check` 命令退出 0 且 `protected` 文件字节不变。检查：G5 gate。

**V14-BENCH-2**〔P1〕多轮任务：v14 自造至少 1 个多轮任务（形状字段在 v14 任务目录冻结：多轮 = ≥2 个依序 prompt，前轮产物进后轮工作区）。具体任务集在 G5 计划冻结，本规范只冻结形状义务。检查：G5 gate。

### 5.2 两层评测

**V14-BENCH-3**〔P0〕评测两层：① FakeLLM 确定性层——脚本化判断驱动全部任务，结果可复现（gate 化，进回归）；② 真 LLM smoke 层——DeepSeek 实跑小样本，仅报告不 gate（凭证缺席即整层跳过，纪律同 V14-HARN-7）。检查：G5 gate（①层 exit 0；②层产出报告工件）。

### 5.3 对照报告

**V14-BENCH-4**〔P0〕复用 pi_parity 归一 trace 基建做 v14 vs pi 对照：归一 schema-v2 trace、canonical phases、drivers（`v13/pi_parity/` 既有 `pig_driver` / `piswift_driver` 与 pi 侧驱动）产出各方 trace，v14 侧新增同格式 trace 生成器。对照报告（工件入库 `v14/bench/`）至少含：任务通过率、拍数/工具调用数、token 成本、events 流形状对照。检查：G5 gate（trace 格式一致性断言 + 报告工件存在且字段齐全）。

**V14-BENCH-5**〔P1〕对照结论的表述边界：报告如实呈现差异，不宣称全面胜出；未跑面（如某驱动缺席）按 `[SKIP]` 纪律明示。检查：评审对照。

## 6. 分期与验收（G1..G5，gate 写死）

> 运行纪律（全部 stage）：测试是独立可跑脚本，`UV_FROZEN=1 uv run python v14/<stage>/test_<name>.py`，退出 0 = 通过（UV_FROZEN 先例：TP-GATE-4）。每 stage 的 `setup_db.py` DROP/CREATE 自己的库（命名 `agent_v14_<stage>`），并按 `v8/load.py` 式累计加载全部已注册 SQL。**每期收尾必须同时绿**：本期全部新 gate + v13 既有全量零回归（`v13/read_tools/test_read_tools.py` 无旗标全量含 E4，退出 0）+ v14 已交付 stage 的回归 sweep（G3 起提供 `v14/regression`，镜像 E4 的发现-串行-零容忍纪律）。

### G1 工具面 v2

范围：合同 v2 bump（§2.3）+ write/edit 口岸 + mutating 语义 / diff 协议 / 审批 hook 条款（§3.1）。
交付：合同 bump 提交（独立内核变更，三义务见 V14-SUP-3）；`v14/tools/`（口岸、目录行、gate）。
gate 验收（写死）：
- 〔P0〕`v14/tools/test_tools_v2.py` exit 0：write/edit 幸福路径落 events 含 diff 载荷；拒绝路径工作区字节零变化；审批 hook 状态机全转移；闭集错误码不串平面。
- 〔P0〕合同断言：`v13/tool-port-contract-2` 版本号已 bump、v1 条款零改动、v2 新条款带「检查」行。
- 〔P0〕v13 全量零回归（E4）；source gate：除内核变更提交外对 v13 冻结面零 diff。

### G2 执行面

范围：bash/glob/grep 口岸 + 权限落 govern / human route 审批环（§3.2）。
gate 验收（写死）：
- 〔P0〕`v14/exec/test_exec.py` exit 0：glob/grep 只读口岸闭集与围栏负例；bash 围栏（越界/超时/超限）负例；审批环四路径（默认拒/批过/驳回/超时）events 与文件系统效果断言。
- 〔P0〕`v14/exec/test_govern_route.py` exit 0：审批命令经 SQL 面、留痕 events、human route 队列可由第二壳观察。
- 〔P0〕v13 全量零回归（E4）+ G1 gate 复跑绿。

### G3 harness MVP

范围：beat driver 提炼（§4.1）+ Chainlit 窗 + LISTEN/NOTIFY + psql 自足 demo + 双壳等价 + 会话可弃 + 决策点计数。
gate 验收（写死）：
- 〔P0〕`v14/harness/test_resume.py` exit 0：跑至中途 kill 进程（实证杀进程，非模拟）→ resume → 终态与不杀对照组一致。
- 〔P0〕`v14/harness/test_dual_shell.py` exit 0：Chainlit 驱动与脚本驱动同输入 → events 规范化投影逐字节一致（V14-HARN-4 比较面）。
- 〔P0〕`v14/harness/test_thin.py` exit 0：决策点计数 ≤ 冻结上限；handler 模块 import 黑名单断言。
- 〔P0〕`v14/harness/test_listen.py` exit 0：NOTIFY 唤醒 + 回表；重连后 UI 历史从 events 重建。
- 〔P0〕psql demo 脚本执行 exit 0。
- 〔P0〕Chainlit 依赖进入 `pyproject.toml` 的提交与 `uv.lock` 更新同笔，且全量回归同笔绿；v13 E4 复跑绿。
- 〔P1〕`v14/regression/` sweep 上线（发现 `v14` 下全部 `test_*.py` 串行零容忍）。

### G4 真 provider

范围：DeepSeek 判断面产品化 + 多轮 + compaction + economy（§4.4）。
gate 验收（写死）：
- 〔P0〕`v14/provider/test_deepseek.py`（FakeLLM 确定性部分）exit 0：同 judgment 合同双实现断言。
- 〔P0〕多轮 gate：≥2 轮会话含一次中途 kill 续跑，终态一致。
- 〔P0〕compaction/economy gate：compact 后会话事实完整、token 记账落 economy 面。
- 〔P1〕真 API smoke：有凭证时跑小样本并产出成本报告；无凭证输出 `[SKIP]`（缺席非通过）。

### G5 基准对标

范围：任务套件 + 两层评测 + 对照报告（§5）。
gate 验收（写死）：
- 〔P0〕`v14/bench/test_bench.py` exit 0：四任务 FakeLLM 层全判定（check 命令 + protected 字节不变）；多轮任务至少 1 个。
- 〔P0〕trace 一致性 gate：v14 trace 与 pi_parity schema-v2 格式断言一致。
- 〔P0〕对照报告工件存在且字段齐全（V14-BENCH-4 清单）。
- 〔P1〕真 LLM smoke 层报告。

## 7. 环境

**V14-ENV-1**〔P0〕数据库与扩展：pgembed 0.3.0rc2 / PostgreSQL 18.4（父循环台账环境事实）。pgembed 以 editable 源安装自 sibling `../pgembed`（`pyproject.toml` `[tool.uv.sources]`）；duckdb 本地 wheel 来自 sibling `../duckdb-python-pgagent`（v13 read_duck 口岸用）。检查：preflight 断言版本。

**V14-ENV-2**〔P0〕UV_FROZEN：全部 gate 命令带 `UV_FROZEN=1`（先例 TP-GATE-4：未冻结的 `uv run` 会改写 `uv.lock`）。依赖变更（Chainlit 于 G3、其余按需）只在对应里程碑提交内发生，与 `uv.lock` 同笔，且当笔全量回归绿。检查：各 stage gate + source 断言 `uv.lock` 无计划外 diff。

**V14-ENV-3**〔P0〕sibling checkout 知情项（v14 文档责任）：全量回归依赖本机 sibling checkout——`/Users/wxl/Projects/pi`、`PiG`、`PiSwift`（`v13/pi_parity/test_pi_parity.py` 以绝对路径引用，缺席时诚实 `[SKIP]`）、`../pgembed`、`../duckdb-python-pgagent`（duck 口岸 pin 与 wheel）、sitting_duck（TP-SNAP-1 pin）。v14 的 README（首个 stage 落盘时）必须记录：他机克隆须知情上述 sibling 布局，缺席面按既有 preflight 纪律降级（缺席不是失败，也不是通过）。检查：`v14/README.md` 存在且含 sibling 清单（G1 收尾工件）。

**V14-ENV-4**〔P1〕v14 不引入新的数据库外部依赖；Chainlit 是唯一计划新增 Python 依赖。检查：pyproject diff 评审。

## 8. 流程与评审

**V14-PROC-1**〔P0〕gate 文化沿用：gate 脚本独立可跑（退出码语义沿用既有纪律：断言失败 1 > 缺席 2 > 通过 0；不重试不豁免不缓存）；偏差台账（`docs/reviews/v14-deviation-ledger-*.md`，自 G1 开立）登记一切对本文的让步；覆盖矩阵按 stage 更新（`docs/reviews/v14-conformance-matrix-*.md`）。

**V14-PROC-2**〔P0〕oracle 对抗审核：spec 冻结 = 本文经 oracle 审至 0 P0 / 0 P1（最多 3 轮，父循环职责）；实现期每轮代码修改走 oracle 审核（双 oracle 模式沿用）。

**V14-PROC-3**〔P0〕逐里程碑提交推送：一 stage（G1..G5）一里程碑一提交；测试全绿 + 收尾工件更新后按路径 `git add` 提交；分支纪律遵循父循环台账（`v14-dev` 推送为加法允许面；合并回 main 须父循环终审 + 用户确认；禁止 force-push）。计划文件惯例：每 stage 开工时立 `docs/plans/v14-<stage>-<日期>.md`（本规范 §6 即其骨架，不预建空壳）。

**V14-PROC-4**〔P0〕收尾工件清单（每里程碑）：新 SQL 进加载序列（累计加载纪律）、覆盖矩阵、偏差台账、stage README、（涉依赖时）`pyproject.toml` + `uv.lock` 同笔。

**V14-PROC-5**〔P0〕规格原文权威：对标 pi 的行为疑问以 pi / PiG / PiSwift 仓库实际代码为准（引用须 file:line）；v8/v10/v13 已冻结条款以各自文档为准；本文与它们冲突时，按 §2 的 supersede 关系裁决，冲突未裁决前按更严者执行。

## 9. 明确不做

1. 不做 pi 的进程模型 / TUI 复刻；不兼容 pi 插件生态与其 session 文件格式。
2. 不实现 v10 内核规格；不回改 v8 / v10 / v13 冻结面（内核变更流程除外，§2.3）。
3. 不引入 DSH Node host（P0C 改道，§2.1）。
4. 不在数据库事务内做任何外部 IO（v8 不变量 4，全文有效）。
5. 不做 UI 富交互（只 submit + LISTEN 渲染；审批之外的 UI 状态机一律不做）。
6. 不做多 agent 编排 / RSI / 生态面（v8 P2/P3 范畴）。
7. 不预建空计划壳；不为「看起来完整」冻结未核实引用。

## 附录 A. 引用核实表（2026-09-28 逐条实查）

| 引用 | 核实结果 |
|---|---|
| `run_ring` 位置 | `v13/pi_ports/test_pi_ports.py:678`（`run_ring(planes)`，多平面同会话）；`v13/read_tools/test_read_tools.py:980`（无参版）。**不在 pi_parity**（父循环目标原文有误，已按 V14-HARN-1 修正表述） |
| beat 拍结构 | `v13/pi_parity/test_pi_parity.py` `GOLDEN_SEQUENCE`（judge/parse/advance/claim/tool ×2 + llm + finish） |
| 归一 trace 基建 | `v13/pi_parity/`：normalized schema-v2 trace 落 `traces/pg.jsonl`；`pig_driver/`（Go）、`piswift_driver/`（Swift）重放归一 transcript；工具链缺席诚实 `[SKIP]` |
| E4 | `v13/read_tools/test_read_tools.py:65` 发现命令（`find v13 -name 'test_*.py' -not -path 'v13/read_tools/*'`）；`run_e4` :2019；串行零容忍；UV_FROZEN 见 TP-GATE-4 |
| 口岸合同 | `docs/designs/v13-tool-ports.md` L5 版本 `v13/tool-port-contract-1` + bump 规则；TP-CAT-4 = L48（schema/加列须独立内核变更并 bump）；TP-INV-1..15；TP-ADMIT-1 十项准入 |
| beat 结算先例 | TP-HUB-2（complete→accepted→commit 顺序）；TP-HUB-4（tick 计数纪律） |
| v8-P0C | `docs/plans/v8-p0c-compat-host-plan-2026-09-17.md`：§0.1 DSH=DeepSeek Harness；C2=§5.2 go/no-go；host 接线未交付 |
| v10 硬缺口 | v10-dev 冻结 2026-09-16（0 P0/0 P1）；grant/generation 已由 `docs/plans/v8-p1-grant-generation-p0c-plan-2026-09-16.md` 交付（G10–G19b）；「硬缺口」字面出自父循环台账/记忆，非 v10-dev 原文 |
| PiG 任务形状 | `PiG/evals/tasks/{add-json-flag,fix-off-by-one,rename-function,slow-build}/task.toml`：`prompt`/`check`/`protected` + `files/`（已抽读 add-json-flag 全文核实字段） |
| NOTIFY 先例 | `v8/closeout/v8_closeout.sql:121`（`pg_notify('v8_wait', …)`） |
| 环境依赖 | `pyproject.toml`：pgembed editable `../pgembed`（>=0.3.0rc1）、duckdb wheel `../duckdb-python-pgagent`、litellm、streamlit（v6 遗留）；Chainlit 尚未引入 |
| govern/economy 面 | `v13/govern/`、`v13/economy/`、`v13/control/` 均为既有 stage（SQL+gate+README） |
| compaction 语义 | `docs/designs/v8-dev.md` §3.3（seq、cancel、compact、repair） |

## 附录 B. 评审焦点（oracle 轮 1 建议聚焦）

1. **run_ring 引用修正**（附录 A 第 1 行）：G3 提炼源表述是否成立。
2. **合同 v2 载体**（V14-SUP-3.2）：就地 bump `v13-tool-ports.md` vs 另立 v14 文档——本稿推荐就地 bump，理由与 TP-CAT-4/L5 规则的自洽性。
3. **P0C 闭合方式**（V14-SUP-1.3）：v14 双壳等价 + 会话可弃是否足以承担 P0C 的等价证明义务并正式 supersede；DSH host 路线就此关闭是否成立。
4. **「逐字节一致」比较面**（V14-HARN-4）：非确定性列排除清单交 G3 钉死是否足够严，还是本稿就应给出列清单。
5. **决策点计数的操作性**（INV-5/V14-HARN-6）：ast 计数口径与 workers 豁免边界。
6. **G5 多轮任务形状**（V14-BENCH-2）：形状义务进 spec、任务集进 G5 计划的切分。
7. **Chainlit 依赖时点**（G3）：引入时点与 uv.lock 同笔纪律是否有更优解。
8. **G1 schema 变更落点**（V14-SUP-3.3）：v13 schema 受控扩展 vs v14 stage SQL 累计加载，留待 G1 计划裁定是否恰当。
