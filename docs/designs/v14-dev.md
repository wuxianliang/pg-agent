# PG 原生 Pi 对标 Coding Agent（v14）开发规范

> 状态：草稿第 2 版，待 oracle 对抗评审轮 2。冻结标准：评审至 0 P0 / 0 P1（最多 3 轮，余 2 轮）。
> 撰写日期：2026-09-28（第 1 版同日，`e97f4ce`）。工作分支：`v14-dev`。
> 修订记录：第 2 版吸收 oracle 轮 1 双裁结论（4+3 P0，判定不能冻结）与父循环对两处 oracle 分歧的裁决（合同 v2 载体=就地 bump；bash=闭集命令执行器）。修订对照见附录 B。
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
| 崩溃语义 | 进程死即会话死 | kill 载体 → resume → 终态有定义且可实证（INV-3 双命题） |

仿的是：工具集形状（read/write/edit/bash/glob/grep）、REPL 对话体验、基准任务成绩。不仿的是：进程内循环、进程内事实源、TUI 耦合。检查：设计评审对照本表；G3 双壳/可弃 gate。

### 0.3 Chainlit 使用约束

**V14-ARCH-3**〔P0〕Chainlit handler 只允许两种动作：**submit**（把用户输入经既有 SQL 命令入口提交进库）与 **observe**（LISTEN 事件流 → 渲染）。UI 历史从 events 表重建；Chainlit 会话内存不得成为事实源（INV-6）。审批动作在 UI 上也只是向 SQL 批准命令提交标量（approver 身份由 DB 得出，见 V14-APPR-6）。检查：source gate 静态扫描 handler 模块（V14-HARN-6）。

**V14-ARCH-4**〔P0〕明示反模式：禁止照抄 Chainlit 官方教程把 agent 循环写进 `@cl.on_message` handler（在 handler 里调 LLM、跑工具、维护对话状态、代批代答）。handler 内出现任何 beat 驱动、模型调用、工具分派、判断拼装即红。检查：source gate 断言 handler 模块 import 黑名单（V14-HARN-6）。

### 0.4 对标面定义

**V14-ARCH-5**〔P1〕对标成立的三件事：① 工具面覆盖 pi coding agent 常用集（read/write/edit/bash/glob/grep）；② REPL 体验：Chainlit 窗口可对话驱动、可断线重连、历史完整；③ 基准：§5 任务套件上产出 v14 vs pi 对照报告。不承诺 TUI 视觉复刻、不承诺 pi 插件生态兼容。检查：G3/G5 gate 与对照报告。

## 1. 不可妥协的不变量（V14-INV-1..6）

> 本节原文照录父循环裁决，是全部后续条款的上位约束。任何 stage 设计、实现、gate 与本节冲突即无效。

**V14-INV-1 判断零外置**〔P0〕一切决策（下一步做什么、何时结束、调用什么工具、是否需要模型判断）由 SQL 面产出（advance / 判断请求拼装与入队全在库内）；LLM 调用只是判断请求的数据面——问题由 SQL 面拼装、回答落 judgment 记录。**执法语义（闭集）**：events 与判断请求只由 SQL 构造；harness 只向既有 SQL 入口提交标量——用户文本、审批决定、脚本化答案，仅此三类。人批与模型回答同属外部判断数据面：请求由 SQL 产出、答复落库；harness 不代批、不代答、不拼装。检查：G3 source gate（INV-5 扫描 + import 黑名单）+ 判断面 gate 回归。

**V14-INV-2 beat 序列是数据**〔P0〕beat 序列（judge/parse/advance/claim/tool/llm/finish 一类的拍结构）是库内数据，不是代码控制流。advance 决定下一步，harness 仅执行。先例：`v13/pi_parity/test_pi_parity.py:66` 的 `GOLDEN_SEQUENCE`（canonical phases）与 `v13/read_tools/test_read_tools.py` / `v13/pi_ports/test_pi_ports.py` 的 ring 驱动。检查：G3 gate 断言 beat 拍落 events 表且驱动模块无硬编码序列分支。

**V14-INV-3 会话可弃（双命题）**〔P0〕kill harness → 重启 resume 的可操作承诺收窄为两个命题，分别断言：

- **命题 A（事件面）**：已提交事件的规范化投影（§4.3 算法）在「杀过」与「未杀」两条世界线上一致。
- **命题 B（工作区面）**：工作区终态 = 已提交 diff 依 effect 全序的确定性重放结果（V14-EFF-3）。

bash `unknown` 场景（started 无 receipt）只承诺**终态有定义**（effect 停在 unknown 并可进人工 reconcile，V14-EFF-5），**不承诺**「与不杀一致」——该承诺与命题 A/B 分开表述、分开断言，禁止合并成一句「终态不变」。检查：G3 杀进程续跑 gate（SIGKILL 进程组、两杀点窗口，见 §6 G3）。

**V14-INV-4 双壳等价**〔P0〕Chainlit 驱动与脚本驱动同输入 → 同 events 流逐字节一致。比较面与投影算法**写死于 §4.3（V14-HARN-4）**：按 seq 排序、代理键保结构 alpha-替换、时间类列按冻结键名表归一、服务端 jsonb::text 比较。比较面新增排除项不属于上述类别时必须 bump 本规范——偏差台账无权松动 P0 比较面。检查：G3 双壳等价 gate。

**V14-INV-5 harness 决策点计数进 gate**〔P0〕harness 的「薄」用决策点计数量化并进 gate。**口径（闭集）**：对 `v14/harness/**/*.py`（排除 `tests/` 与 `workers/` 子树）做 ast 扫描，计数节点闭集 = `If` / `For` / `While` / `Match` / `ExceptHandler` / `IfExp` / 推导式 `if`；`BoolOp` 不计。**上限（现在冻结）**：driver 模块 ≤ 15，handler 模块 ≤ 5；改上限须 bump 本规范。**workers 豁免**按包路径 + 能力协议界定：worker（经 `run_line_json` 拉起的子进程）禁止 import 判断编排 / advance / govern 面，回传仅 stdout/stderr/exit code/diff，豁免不延伸到 harness 进程内代码。检查：G3 静态扫描 gate（ast 计数 + 包路径豁免边界 + import 黑名单）。

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

- G1 工具目录加 mutating 语义（§2.3 合同 v2）即「工具/插件世代」问题的 v14 承接面：目录行版本化、request 创建时绑定 `contract_version` + generation、旧请求 handler 冻结语义（先例 TP-CAT-2）必须保持。
- G2 权限与审批环落在 v13 既有 `v13/govern/`（`v13_govern.sql` + gate）之上：govern 人批由 **v14 新函数调用既有入口**实现，不改 `v13/**/*.sql`；如确需动 v13 冻结面，一律走独立内核变更流程（§2.3 路径）。

检查：G1/G2 source gate（对 v13 冻结面零 diff，除内核变更提交）；设计评审对照本条。

### 2.3 口岸合同 v1 → v2 bump（载体已裁：就地 bump）

**V14-SUP-3**〔P0〕v14 工具面扩展遵守 `docs/designs/v13-tool-ports.md` 的合同纪律：现行版本 `v13/tool-port-contract-1`（该文档 L5：改变行为必须同一提交 bump 版本号；已发布条款 ID 禁止复用；废止保留 ID）。**TP-CAT-4**（该文档 L48）明文：新口岸确需改 schema 或加列（含 `input_schema` / `mutating` / `allowlist` / `timeout_ms` / `consumes` / `produces`）时，必须拆成**独立内核变更**并 bump 合同版本，禁止夹带在口岸提交里。

v2 bump 走法（父循环已裁）：

1. **载体**：在 `docs/designs/v13-tool-ports.md` 原文档**就地 bump** 版本号至 `v13/tool-port-contract-2` 并追加 v2 条款（mutating 语义 / diff 协议 / 审批 hook / 闭集命令执行器）。**v1 条款字节不动**（不可变性由条款 ID 纪律满足：旧 ID 保留原文，新义务一律用新 ID 追加）。
2. **混合世代语义（v2 正文必写）**：v2 发布前已排队/已创建的 v1 请求仍走 v1 handler，禁止降级、禁止重解析为 v2 语义；request 创建时绑定 `contract_version` + generation，分派按该绑定执行。
3. **schema 落点（已裁）**：v14 累计迁移——`ADD COLUMN mutating boolean NOT NULL DEFAULT false` 等列以 v14 拥有的迁移 SQL 进入累计加载序列；`v13/**/*.sql` 历史 SQL 零改动。
4. **同笔义务**：内核变更提交（K，见 §6 G1）内同时包含合同 bump 文档、迁移 SQL、允许名单（哪些新列/新口岸被 v2 授权）；既有全量 gate 复跑绿。
5. **条款延续**：v2 完整继承 TP-INV-1..15 与 TP-WIRE / TP-FS / TP-GATE / TP-ADMIT 既有条款；新增面按 TP-ADMIT-1 十项准入清单同等标准补齐。

检查：G1 gate 断言 contract-2 版本号已 bump、v1 条款字节零改动、混合世代条款存在；E4 回归。

## 3. 效果协议、工具面与执行面（G1/G2 冻结面）

### 3.1 效果协议（V14-EFF，G1 起生效，全部 stage 共用）

**V14-EFF-1**〔P0〕外部效果（文件写入、命令执行、provider 调用）统一状态机：`planned → approved → claimed → started → succeeded | failed | unknown → reconciled`。每个效果有稳定 `effect_id`；重试、resume、reconcile 复用同一 ID，禁止换 ID 重放。检查：G1 起各 gate 断言状态机合法转移集。

**V14-EFF-2**〔P0〕IO 前提交 intent 行：任何外部 IO 发生前，效果行（intent）必须已提交入库；该行是幂等键——同一 effect 再次执行以「行已存在 + 状态」判定续跑或重放，不凭进程内存。检查：G1 gate（intent 先于 IO 的断言，先例 TP-HUB-2 结算顺序纪律）。

**V14-EFF-3**〔P0〕write/edit 的原子写与幂等重放：临时文件写入 → fsync → rename → 基线哈希校验。resume 时若目标文件哈希已等于该 effect 的目标态，**结算原 effect，不重放写入**。工作区终态 = 已提交 diff 依 effect 全序的确定性重放（INV-3 命题 B 的构造基础）。成功后提交 `tool/result`（含 diff 载荷，V14-TOOL-2）。检查：G3 窗 1 杀点 gate；G1 原子写正/负例。

**V14-EFF-4**〔P0〕provider 调用记 attempt：每次真实模型调用记 attempt 行（request 指纹、时长、结果）；kill 后重发可能产生重复计费——这是**已声明的语义**，不是缺陷；attempt 行如实记录（economy 记账见 V14-HARN-9）。检查：G4 gate（attempt 行断言，含重复 attempt 场景）。

**V14-EFF-5**〔P0〕bash `started` 无 receipt → `unknown`：resume 后无法判定 IO 是否已发生的 bash 效果停在 unknown，**禁止自动重试**，进人工 reconcile（SQL 命令裁决 succeeded/failed，留痕 events；先例目录 `v8/reconcile/`）。检查：G3 窗 2 杀点 gate（unknown + reconcile 路径走通）。

### 3.2 write/edit 口岸（G1）

**V14-TOOL-1**〔P0〕write/edit 是 mutating 口岸：结果改变工作区文件系统状态。mutating 请求必须走审批环（§3.4）且经 V14-EFF 效果协议执行；未获批的 mutating 请求不得产生文件系统效果，拒绝路径 events 记录完整。检查：G1 gate（拒绝路径断言工作区字节零变化）。

**V14-TOOL-2**〔P0〕diff 协议：edit 口岸的请求参数与结果必须携带可机器判定的 diff（old/new 成对或统一 diff 格式），diff 是 events 流的一部分（落 `tool/result` 载荷），供审批环渲染、INV-3 命题 B 重放与 gate 断言。格式在合同 v2 条款冻结；禁止「只给最终全文不给 diff」。检查：G1 gate 对 diff 载荷的结构断言。

**V14-TOOL-3**〔P0〕write/edit 执行拆三步，各守 claim 纪律：① **只读 proposal 构建**（读工作区、算 diff 与基线哈希；构建过程持只读 claim，提交 proposal 后释放）；② **审批等待**（不持任何 claim，V14-APPR-4）；③ **apply**（claim effect → 原子写（V14-EFF-3）→ complete）。检查：G1 gate 三步各断言 claim 生命周期。

### 3.3 审批协议（V14-APPR，G1 交付状态机与批准命令；G2 只加 bash 策略）

**V14-APPR-1**〔P0〕proposal 不可变、一次构建。proposal 摘要（被批准的对象）字段冻结：合同版本、generation、工具名、完整参数、cwd、受控环境标识、workspace 基线哈希、规范化 diff（mutating 类）、有效期（expires_at）。检查：G1 gate 摘要字段完备性断言。

**V14-APPR-2**〔P0〕批准只批摘要（哈希锚定），单次消费；执行 claim 时 CAS 重验（摘要哈希一致、状态 approved、未过期、workspace 基线仍匹配）。任一不符即拒绝执行并留痕。检查：G1 gate（重放/篡改/基线漂移负例）。

**V14-APPR-3**〔P0〕状态机 `requested → approved | denied | expired`，终态不可逆。超时判定用**注入 now**（SQL 参数/会话变量），禁止读客户端时钟。检查：G1 gate 全转移断言（含注入时钟过期）。

**V14-APPR-4**〔P0〕等待期不持 claim：审批等待不占用 beat 前进位、不持 effect claim；批准后重新走 V14-EFF claim。检查：G1 gate（等待期 beat 推进断言）。

**V14-APPR-5**〔P0〕授权分层：会话级 grant 可覆盖 write/edit（grant 行记录世代与合同版本，绑定 proposal 模式范围）；bash 与一切例外走**逐次人批，默认拒**。检查：G1/G2 gate（grant 命中/越界各负例）。

**V14-APPR-6**〔P0〕approver principal 由 DB 身份得出（连接/角色身份映射），写 events；客户端自报身份禁止。检查：G1 gate（principal 来源断言 + 自报负例）。

**V14-APPR-7**〔P0〕测试纪律：禁止直改审批状态表；approve/deny/expire 与 reconcile 一律走产品 SQL 命令。检查：G1 起全部审批相关 gate（source 断言无裸 DML 进审批表）。

### 3.4 bash/glob/grep 执行面（G2，bash=闭集命令执行器）

**V14-TOOL-4**〔P0〕bash 口岸默认为**闭集命令执行器**：枚举动词目录（固定命令集，如 run-test / build 一类），每个动词的 argv 模板与参数约束是合同 v2 的数据（库内目录行）；参数受合同约束（类型/取值域/长度），任意 shell 表达式**不是**输入面。加动词 = 合同面变更（走 §2.3 纪律）。任意 shell 整体移出 v14 范围（§9），待真隔离机制（容器级）存在的后续版本再开。围栏（工作区根约束、超时、输出上限）条款在合同 v2 冻结。检查：G2 gate（动词目录闭集、参数域负例、围栏负例：越界/超时/超限各至少一条）。

**V14-TOOL-5**〔P0〕glob/grep 是只读口岸：错误闭集、围栏与既有 read 口岸同级（TP-WIRE / TP-FS 纪律），无审批环。检查：G2 gate（闭集与围栏负例）。

**V14-TOOL-6**〔P0〕权限落 govern / human route：bash（mutating 高危）逐次人批默认拒（V14-APPR-5）；审批请求与决定经 SQL 面留痕；human route 待审队列可被第二壳观察（UI 只是渲染，V14-ARCH-3）。检查：G2 gate（审批环四路径：默认拒/批过/驳回/超时）。

## 4. harness 与载体（G3/G4 冻结面）

### 4.1 beat driver

**V14-HARN-1**〔P0〕beat driver 从既有 ring 实现提炼为可复用模块（`v14/harness/`）。提炼源（已核实）：`v13/pi_ports/test_pi_ports.py:678` `run_ring(planes)`（多在场平面同会话、mock judgment、events 计数）与 `v13/read_tools/test_read_tools.py:980` `run_ring()`；拍结构锚点 = `v13/pi_parity/test_pi_parity.py:66` `GOLDEN_SEQUENCE`。提炼不得改动 v13 既有文件（复制提炼，非原地重构）。检查：G3 gate + source gate（v13 零 diff）。

> 注：父循环轮 1 目标原文写作「test_pi_parity.run_ring」——经核实 `run_ring` 不定义于 pi_parity，实际定义于上述两处；pi_parity 提供的是 normalized schema-v2 trace 与拍结构。本规范按核实结果表述。

**V14-HARN-2**〔P0〕driver 语义：循环 = 「取 beat → 执行该拍的外部动作（若有）→ 落 events → advance」；终态判定在 SQL 面；外部动作执行前后守 V14-EFF 纪律。进程可随时被杀（INV-3）；可选 pg_cron 心跳拉起 driver 属于部署面，不改变语义（beat 推进幂等）。检查：G3 杀进程续跑 gate。

### 4.2 事件流与 LISTEN/NOTIFY（通道 v14_wake）

**V14-HARN-3**〔P0〕事件流权威 = events 表（只追加）。观察通道定名 **`v14_wake`**（不复用 v8 的 `v8_wait`；`v8/closeout/v8_closeout.sql:121` 仅证 NOTIFY 机制先例）。**payload 闭集 = `{session_id, seq 高水位}`**——NOTIFY 只作唤醒信号与高水位提示，不携带业务事实，事实一律回表读。观察连接是**独立 autocommit 连接**（与 driver 业务连接分离）。**补读算法（写死）**：醒来 → 读 `seq > last_seq` 的 events 按 seq 升序 → 处理 → 推进 last_seq → 循环直至空集；last_seq 只前进；通知丢失或合并不产生遗漏（回表是唯一事实源）。**负例（gate 必测）**：① 通知合并（同通道多条 NOTIFY 一次醒来，回表读全）；② 断线插入（观察连接中断重连后从 last_seq 回补，不漏不重）。检查：G3 `test_listen.py`（含两负例）。

### 4.3 双壳等价：比较面与投影算法（写死）

**V14-HARN-4**〔P0〕INV-4 的完整算法：

1. **同输入协议**：两壳各自**新会话、新工作区**，喂同输入序列；输入含批准——批准作为 SQL 命令序列经 **govern 入口**提交，无旁路（不直改表，V14-APPR-7）。
2. **同入口**：两壳驱动**同一组 SQL 入口**（submit / approve / …）；seq 由 SQL 分配，客户端不造序。
3. **投影**：events 按 `(session_id, seq)` 排序 → **代理键保结构 alpha-替换**（会话/事件/effect/judgment 等主键与外键列按首次出现顺序映射为 `$s1/$e1/$j1…`，同值同替换、跨行一致）→ **时间类列与固定键名表归一**（键名表冻结：`ts` / `wall_time` / `created_at` / `pid` / `lsn`，值替换为类型占位符）。
4. **比较**：服务端比较——两投影的 `jsonb_build_object(...)::text` 逐行相等（在库内执行，非客户端字符串拼装）。
5. **比较面封闭性**：新增排除项不属于「代理键 / 时间类键名表」两类时，**必须 bump 本规范**；偏差台账无权松动本 P0 比较面。

检查：G3 `test_dual_shell.py`。

**V14-HARN-5**〔P0〕psql demo 收窄为 **submit/observe demo**：一条纯 psql 路径演示「SQL 命令提交输入 + `LISTEN v14_wake` 观察事件流」，证明载体无关性；不宣称「全程 psql 驱动 agent 完成 mutating 任务」。demo 脚本入库（`v14/harness/`）。检查：G3 gate（psql 执行 demo 退出 0 + 事件断言）。

**V14-HARN-6**〔P0〕harness 薄度执法（INV-1/INV-5 的 gate 细则）：扫描 `v14/harness/**/*.py`（排除 `tests/`、`workers/`）；决策点计数按 INV-5 闭集与上限；**import 黑名单**：判断编排模块、工具实现模块、litellm、目录策略模块——handler/driver 一律不得 import。worker 能力协议按 INV-5（禁 import 判断/advance/govern 面；回传仅 stdout/stderr/exit/diff）。检查：G3 `test_thin.py`。

### 4.4 真 provider、多轮与 compaction（G4）

**V14-HARN-7**〔P0〕DeepSeek 判断面产品化：真 provider 经既有 litellm 依赖接入，与 FakeLLM 实现同一 judgment 合同（同参数/同落库/同错误闭集）；调用经 V14-EFF-4 attempt 记账。测试分层：确定性层永远 FakeLLM（外部 IO 不进事务，AGENTS.md / v8 不变量 4）；真 API smoke 属 release evidence（§6 分类）。检查：G4 gate + release evidence 工件。

**V14-HARN-8**〔P0〕多轮：跨 turn 的会话连续性（上下文携带、目标推进、终态收敛）由库内状态承担，harness 重启不丢轮次。检查：G4 多轮 gate（含一次中途 kill 的多轮续跑）。

**V14-HARN-9**〔P0〕compaction **只追加**：compact 产生新 summary 事件，旧事件一律保留；事实完整 = 可重放 compact 前全部历史（沿用 v8 compact 语义，`docs/designs/v8-dev.md` §3.3；触发与产物落库）。economy 只记判断行 provider usage **整数**（input/output tokens 等），不记派生指标。检查：G4 gate（compact 后重放断言 + economy 整数记账断言）。

## 5. 基准对标（G5 冻结面）

### 5.1 任务形状

**V14-BENCH-1**〔P0〕借 PiG 任务形状（已核实：`PiG/evals/tasks/<name>/task.toml`，字段 `prompt` / `check`（shell 判定命令）/ `protected`（禁改文件）+ `files/`（任务工作区）），四任务：`add-json-flag` / `fix-off-by-one` / `rename-function` / `slow-build`。借用形状（v14 自建镜像目录），不依赖 PiG 仓库运行时；判定 = `check` 命令退出 0 且 `protected` 文件字节不变。检查：G5 gate。

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

范围：合同 v2 bump（§2.3）+ 效果协议（§3.1）+ write/edit 口岸与三步执行（§3.2）+ diff 协议（V14-TOOL-2）+ 审批状态机/principal/SQL 批准命令（§3.3 全部，自 G2 原计划**移入**）。
提交集合（枚举，见 V14-PROC-3）：**K**（内核提交：合同 bump 文档 + v14 迁移 SQL + 允许名单）→ **S**（实现提交：口岸、目录行、gate）。
gate 验收（写死）：
- 〔P0〕`v14/tools/test_tools_v2.py`（required）exit 0：write/edit 幸福路径落 events 含 diff 载荷；三步执行各 claim 生命周期；拒绝路径工作区字节零变化；EFF 状态机合法转移集；intent 先于 IO。
- 〔P0〕`v14/tools/test_approval.py`（required）exit 0：V14-APPR-1..7 全断言（摘要字段/单次消费 CAS/状态机全转移含注入时钟过期/等待期不持 claim/grant 分层/principal 来源/无裸 DML）。
- 〔P0〕`v14/tools/test_contract_v2.py`（required）exit 0：contract-2 版本号已 bump；v1 条款字节零改动；混合世代条款存在；迁移含 `mutating` 列；`v13/**/*.sql` 零 diff。
- 〔P0〕v13 全量零回归（E4，required）。

### G2 执行面（只加 bash 策略与执行口岸）

范围：闭集命令执行器 bash（§3.4）+ glob/grep 只读口岸 + govern/human route 审批环接线（审批状态机已在 G1）。
gate 验收（写死）：
- 〔P0〕`v14/exec/test_exec.py`（required）exit 0：动词目录闭集与参数域负例；glob/grep 闭集与围栏负例；bash 围栏（越界/超时/超限）负例；审批四路径（默认拒/批过/驳回/超时）events 与文件系统效果断言。
- 〔P0〕`v14/exec/test_govern_route.py`（required）exit 0：审批命令经 SQL 面、留痕 events、human route 队列可由第二壳观察。
- 〔P0〕v13 全量零回归（E4）+ G1 gate 复跑绿。

### G3 harness MVP

范围：beat driver 提炼（§4.1）+ Chainlit 窗 + `v14_wake` LISTEN/NOTIFY（§4.2）+ psql submit/observe demo（§4.3）+ 双壳等价 + 会话可弃（两杀点）+ 薄度执法。
gate 验收（写死）：
- 〔P0〕`v14/harness/test_resume.py`（required）exit 0：**SIGKILL 进程组**实证杀（非模拟），两杀点窗口各覆盖——窗 1：write intent 已提交、rename 未发生 → resume → 幂等结算（V14-EFF-3）+ 命题 A/B 断言；窗 2：bash IO 中途 → resume → unknown + 人工 reconcile 走通（V14-EFF-5，只断言终态有定义）。
- 〔P0〕`v14/harness/test_dual_shell.py`（required）exit 0：两壳（脚本壳 + Chainlit 壳——经 Chainlit 无头测试模式驱动**真实 handler 模块**，禁止为 gate 另写假 handler）按 V14-HARN-4 算法比较，逐行相等。
- 〔P0〕`v14/harness/test_thin.py`（required）exit 0：决策点计数（INV-5 闭集与上限）+ import 黑名单 + worker 能力协议。
- 〔P0〕`v14/harness/test_listen.py`（required）exit 0：v14_wake payload 闭集、独立 autocommit 连接、补读循环、通知合并与断线插入两负例、重连后 UI 历史从 events 重建。
- 〔P0〕psql submit/observe demo 脚本执行 exit 0。
- 〔P0〕Chainlit 依赖进入 `pyproject.toml` 与 `uv.lock` 更新同笔，且当笔全量回归绿；v13 E4 复跑绿。
- 〔P0〕`v14/regression/` sweep 上线（发现 `v14` 下全部 `test_*.py` 串行，required 零容忍、probe 照 skip 语义）。

### G4 真 provider

范围：DeepSeek 判断面产品化 + 多轮 + compaction 只追加 + economy 整数记账（§4.4）。
gate 验收（写死）：
- 〔P0〕`v14/provider/test_deepseek.py`（required，FakeLLM 确定性部分）exit 0：同 judgment 合同双实现断言；attempt 记账含重复 attempt 场景。
- 〔P0〕多轮 gate（required）exit 0：≥2 轮会话含一次中途 kill 续跑，命题 A/B 断言。
- 〔P0〕compaction/economy gate（required）exit 0：compact 后可重放 compact 前全部历史；判断行 usage 整数记账。
- 〔P0〕**release evidence**：里程碑关闭前有一次真 DeepSeek smoke 工件入库——含模型 ID、usage、错误映射，且**无密钥**入库。
- 〔P1〕真 API smoke 脚本（optional probe 语义：无凭证 = 2，如实呈报）。

### G5 基准对标

范围：任务套件 + plumbing/live 两层 + 对照报告（§5）。
gate 验收（写死）：
- 〔P0〕`v14/bench/test_bench.py`（required）exit 0：四任务 + ≥1 多轮任务，plumbing 层全判定（check 命令退出 0 + protected 字节不变）。
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
4. **不做任意 shell 执行**：G2 bash 是闭集命令执行器（枚举动词 + 合同约束参数）；任意 shell 待后续版本有真隔离机制（容器级）再开。
5. 不在数据库事务内做任何外部 IO（v8 不变量 4，全文有效）。
6. 不做 UI 富交互（只 submit + LISTEN 渲染；审批呈现之外的 UI 状态机一律不做）。
7. 不做多 agent 编排 / RSI / 生态面（v8 P2/P3 范畴）。
8. 不预建空计划壳；不为「看起来完整」冻结未核实引用。

## 附录 A. 引用核实表（2026-09-28 逐条实查）

| 引用 | 核实结果 |
|---|---|
| `run_ring` 位置 | `v13/pi_ports/test_pi_ports.py:678`（`run_ring(planes)`，多平面同会话）；`v13/read_tools/test_read_tools.py:980`（无参版）。**不在 pi_parity**（父循环轮 1 目标原文有误，已按 V14-HARN-1 修正表述） |
| beat 拍结构 | `v13/pi_parity/test_pi_parity.py:66` `GOLDEN_SEQUENCE`（定义 66–71 行）；完整相位列表 = `judge / parse / advance / claim / tool / llm / finish`（两轮 tool 拍各自带工具名，llm/finish 前的 claim 相为 None；oracle P1 注：模型 assistant 输出是独立 canonical phase） |
| 归一 trace 基建 | `v13/pi_parity/`：normalized schema-v2 trace 落 `traces/pg.jsonl`；`pig_driver/`（Go）、`piswift_driver/`（Swift）重放归一 transcript；工具链缺席诚实 `[SKIP]` |
| E4 | `v13/read_tools/test_read_tools.py:65` 发现命令（`find v13 -name 'test_*.py' -not -path 'v13/read_tools/*'`）；`run_e4` :2019；串行零容忍；UV_FROZEN 见 TP-GATE-4 |
| 口岸合同 | `docs/designs/v13-tool-ports.md` L5 版本 `v13/tool-port-contract-1` + bump 规则；TP-CAT-4 = L48（schema/加列须独立内核变更并 bump）；TP-INV-1..15；TP-ADMIT-1 十项准入 |
| beat 结算先例 | TP-HUB-2（complete→accepted→commit 顺序）；TP-HUB-4（tick 计数纪律） |
| v8-P0C | `docs/plans/v8-p0c-compat-host-plan-2026-09-17.md`：§0.1 DSH=DeepSeek Harness；C2=§5.2 go/no-go；host 接线未交付（C0–C6 未完成） |
| v10 硬缺口出处 | 父循环台账 `prompt-exports/loop-orchestrate-v14-runs.md:7`（「v10 硬缺口（grant 模型/插件世代）在 G1/G2 自然承接」）；grant/generation 交付佐证 `v8/README.md:9`（24/24 gate，2026-09-17）；「硬缺口」字面**不在** v10-dev.md 原文 |
| PiG 任务形状 | `PiG/evals/tasks/{add-json-flag,fix-off-by-one,rename-function,slow-build}/task.toml`：`prompt`/`check`/`protected` + `files/`（已抽读 add-json-flag 全文核实字段） |
| NOTIFY 先例 | `v8/closeout/v8_closeout.sql:121`（`pg_notify('v8_wait', …)`）；v14 用独立通道 `v14_wake`，不复用 `v8_wait` |
| reconcile 先例 | `v8/reconcile/`（既有 stage 目录；v14 人工 reconcile 语义援引其先例地位，不加载其 SQL） |
| 环境依赖 | `pyproject.toml`：pgembed editable `../pgembed`（>=0.3.0rc1 声明，本机实装 0.3.0rc2 → ENV-1 钉 `==0.3.0rc2`）、duckdb wheel `../duckdb-python-pgagent`、litellm、streamlit（v6 遗留）；Chainlit 尚未引入 |
| govern/economy 面 | `v13/govern/`、`v13/economy/`、`v13/control/` 均为既有 stage（SQL+gate+README） |
| compaction 语义 | `docs/designs/v8-dev.md` §3.3（seq、cancel、compact、repair） |

## 附录 B. 轮 1 → 轮 2 修订对照（oracle 双裁 4+3 P0 落点）

| # | 轮 1 发现（合并表述） | 轮 2 落点 |
|---|---|---|
| 1 | 效果协议缺失（两 oracle P0 合并）：外部效果无状态机/幂等键/原子写/unknown 语义；INV-3 「终态不变」过强 | 新 §3.1 V14-EFF-1..5（状态机/effect_id/intent 幂等键/fsync+rename+基线哈希幂等重放/bash unknown 禁自动重试进人工 reconcile/provider attempt 记账）；INV-3 改双命题 + unknown 只承诺终态有定义；G3 杀点=SIGKILL 进程组两窗（§6 G3） |
| 2 | INV-1/5 执法不可操作（两 oracle P0）：「无策略决策」无闭集、决策点无口径无上限 | INV-1 加执法语义闭集（harness 只提交标量三类；人批/模型回答同属外部判断数据面）；INV-5 口径闭集（7 节点，BoolOp 不计）+ 上限现在冻结（driver≤15 / handler≤5）+ 扫描路径与豁免边界（包路径+能力协议）；V14-HARN-6 import 黑名单 |
| 3 | INV-4 投影算法缺失（两 oracle P0）：「逐字节」无算法、排除清单推给 stage 计划、比较在客户端 | V14-HARN-4 算法五步写死（新会话新工作区同输入含批准走 govern 入口/同 SQL 入口/seq SQL 分配/代理键 alpha-替换+冻结键名表/服务端 jsonb::text 比较）；新增排除项须 bump spec、台账无权松动 |
| 4 | 审批协议不成形（codex P0-3 + grokBuild P1-1 合并，父循环升 G1） | 新 §3.3 V14-APPR-1..7（不可变 proposal 摘要字段冻结/单次消费 CAS 重验/状态机+注入 now/等待期不持 claim/grant 分层 bash 默认拒/principal 由 DB 身份/测试禁裸 DML）；V14-TOOL-3 三步执行；审批状态机+principal+SQL 批准命令移入 G1（G2 只加 bash 策略） |
| 5 | gate 语义与提交面混乱（两 oracle P0/P1）：skip 与失败不分、release 工件无定义、G1 内核/实现混提交、schema 落点未裁 | §6.0 V14-GATE-C 三分类（required 0/1、probe 0/1/2、release evidence 里程碑关闭前须真工件：G4 DeepSeek smoke 含模型 ID/usage/错误映射/无密钥；G5 每完成项一对 v14↔pi 实跑+全链 provenance）+ 聚合断言失败优先；V14-GATE-K 加载=v13 累计+v14 迁移不加载 v8；G1 提交集合=K+S 枚举；schema 落点=v14 累计迁移 ADD COLUMN mutating（V14-SUP-3.3）；PROC-3 改枚举提交集合 |
| 6a | P0C supersede 措辞含混（义务转移暗示） | §2.1 改「解除/退役」：tombstone + 义务未转移 + DSH host 关闭三句写死 |
| 6b | LISTEN/NOTIFY 细节缺失（通道名/payload/补读/负例） | V14-HARN-3：通道 `v14_wake`、payload 闭集 {session_id, seq 高水位}、独立 autocommit 连接、补读算法写死、通知合并/断线插入两负例 |
| 6c | psql demo 过宣称 / Chainlit 壳 gate 载体不明 | V14-HARN-5 收窄 submit/observe；双壳 gate 的 Chainlit 壳=无头测试模式驱动真实 handler |
| 6d | compaction/economy 语义松 | V14-HARN-9 compaction 只追加（可重放 compact 前历史）；economy 只记判断行 provider usage 整数 |
| 6e | G5 层级措辞 / 多轮强度 / 硬缺口出处 / 引用精度 / preflight | V14-BENCH-3 改 plumbing（P0）/live（release evidence，无凭证=SKIP 键不参与 exit 0）；V14-BENCH-2 ≥1 多轮升 P0；V14-SUP-2 改「父循环台账在 v10 冻结后识别」附台账 :7；附录 A 补 GOLDEN_SEQUENCE :66 与完整相位列表；ENV-1 钉 `==0.3.0rc2` |
| 裁-A | 合同 v2 载体（oracle 分歧，父循环裁=就地 bump） | V14-SUP-3.1 就地 bump + v1 条款字节不动 + 新义务新 ID；3.2 混合世代语义（v1 请求走 v1 handler/禁降级/request 绑定 contract_version+generation） |
| 裁-B | bash 安全边界（oracle 分歧，父循环裁=闭集命令执行器） | V14-TOOL-4 闭集动词执行器（argv 模板+参数域为合同数据，加动词=合同变更）；§9.4 任意 shell 移出范围待真隔离机制 |
