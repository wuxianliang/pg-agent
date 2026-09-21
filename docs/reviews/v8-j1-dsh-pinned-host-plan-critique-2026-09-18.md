# V8 J1 计划审查：v8-j1-dsh-pinned-host-plan-2026-09-17

审查日期：2026-09-18。一次有界设计审查，仅评审、不实施、不改计划、不运行 DSH。

## Context / Scope

- 被审计划：`docs/plans/v8-j1-dsh-pinned-host-plan-2026-09-17.md`（1311 行，全文已读）。
- 保留基线：`prompt-exports/oracle-plan-2026-09-17-210745-v8-j1-dsh-pinned-hos-8d77.md` 中 "Generated Plan" 之后的计划正文（L136–L1407，全文已读）；prompt/selection 回显不算基线。
- 已确认约束（不复议）：J1 官方 memory-only 新建会话（无 PG、无任何 SessionPersistence）；准备阶段显式下载精确工具/锁定依赖、运行期禁网络；built CLI 硬准出不可降级；J1 仅认证 macOS。J0 提交 `11c600c` 已完成。严格只做 J1。
- spot-check 范围（沿计划命名接缝，均实读源码，不漫游）：DSH `0d1f5000…`（本地 clean master 已核对 HEAD 一致）的根 `package.json`/`tsdown.config.ts`、`apps/cli/tsdown.config.ts`、`apps/cli/src/profile-boot.ts`、`packages/bundle/headless/{cordis.patch.yml,src/index.ts,src/startup.ts}`、`packages/boot/cmdline/src/index.ts`、`packages/boot/app-boot/{package.json,src/index.ts,src/profile.ts}`、`packages/core/{agent-loop,session,agent,tools,agent-default-model}`、`packages/llm/llm/src/index.ts`；pg-agent 的 `v8/compat/p0c_report.py`、`v8/compat/test_compat.py:1320–1330`、`v8/compat/pinned_host_manifest.json`、`v8/regression/run_baseline.py:60–135`。

## 已核实成立的关键断言（不重复列入 Findings）

- 父级四处纠正全部与源码一致：根 tsdown host workspace 确含 `apps/desktop`/`apps/desktop-host`（`tsdown.config.ts:19–21`）；headless patch 的三个 `!!js` 绑定存在（`packages/bundle/headless/cordis.patch.yml:29–31`）；`appReady.onReady` 是同步 void listener、boot 提交后 commit、迟注册立即回调（`packages/boot/cmdline/src/index.ts:44–53`；`apps/cli/src/profile-boot.ts:48–69`）；headless runner 只 `await ctx.get('loader')?.await()`、不等 appReady（`packages/bundle/headless/src/index.ts:310–312`）；`test_compat.py:1323–1326` 断言确为 unresolved 非空 + 三结论 false，无固定六项计数。
- memory-only 前提成立：`createStoredSession` 无 `sessionPersistence` 返回 undefined、`resume` 无后端抛错（`packages/core/agent-loop/src/index.ts:729–737,857–862`）；`sessions.flush` 无持久化监听时收集零回调、返回 false 不抛错（`packages/core/session/src/index.ts:1177–1194`）——headless runner 的 `await sessions.flush(...)` 在 memory-only 下安全。
- `DSH_TELEMETRY_DISABLED` 在无 telemetry 行的自定义 profile 下"平凡满足"、不产生 patch、不报错（`apps/cli/src/profile-boot.ts:160–175`）。
- profile-inspector 公共 API 成立：built `@deepseek-ai/dsh-app-boot` 的 `"."` export（`lib/index.js`）re-export `loadProfile`/`composeEntries`/`loadProfileDirectory`（`src/index.ts:32,38,39`），inspector 可从构建面导入，不需 source-plane。
- 矩阵真值成立：`p0c_report.CATALOG` 恰 30 个 Subcase，与计划 §3.8.2 表逐一对应（四个用常量命名：`FORK_DB_ROW`/`SWITCH_DB_ROW`/`MANDATED_NEGATIVE`/`MINIMAL_DUAL_LOOP_SUBCASE`）；`DB="db"`/`REAL="real"`；`DISPATCH_REAL_ROWS` 为 8 行子集，计划"不能仅复制该子集"的警告成立。
- runner 六处差距属实：gate ID 正则 `G\d+[abc]?`、`database_group` 目录推导（compat 必为 `agent_v8_compat`，无法表示 null）、README inventory 正则 `# (G\w+)`、snapshot 仅 `.py/.sql/.json`、`EVIDENCE = v8/compat/evidence/j0`（`run_baseline.py:28,78–128`）。
- 工具链声明属实：`packageManager: pnpm@11.7.0`、engines `^22.19.0 || >=24.0.0`、`build:lib:host` 脚本存在且为 `tsc -b tsconfig.host.json && tsdown --env.DSH_BUILD_FACE host`；CLI override entry 确为 `lib/types/bin.js`（`apps/cli/tsdown.config.ts:10`）。
- 保真核对（export→计划）：逐节比对未发现准确具体内容被删除或弱化；§8 台账声明的各处纠正（desktop 包、三绑定、ready 语义、下载授权、Linux 出范围、G13 断言）与源码和用户决议一致；错误码 20 个、证据五件、W1–W6、30 行矩阵表均完整保留。

## Findings（按负载排序，共 8 条）

### F1（P1）headless-runner 的真实启动依赖是软读服务，closure 判据"以 required injection 为准"不充分，缺失时静默 no-op

- 位置：计划 §3.5.2（L421–431，尤其 L431"完整集合以该 pin 的 required injection 为准"）；§2.3/§7 只引用了 `headless/src/index.ts:309–312` 的 loader await。
- 依据：`packages/bundle/headless/src/index.ts:313–317` —— `run()` 在 loader await 之后用 `ctx.get('agents')`/`ctx.get('agentDefaultModel')`/`ctx.get('sessions')` 软读取三个服务，任一 undefined 即 **静默 return**：不抛错、不调用 `io.exit`。而 headless-runner 条目的 `inject` 仅声明 `[headlessStartup]`（`cordis.patch.yml:27`）。`agents`/`sessions`/`tools` 分别由 `packages/core/agent/src/index.ts:256`、`packages/core/session/src/index.ts:936`、`packages/core/tools/src/index.ts:829` 以 Service 提供。
- 问题：按计划的闭包算法（根集合 + required injection 递归），headless-runner 不会拉入 agents/agentDefaultModel/sessions 的提供者——它们不是任何根条目的 required injection。产出的 profile 可通过全部静态核验，运行时 runner 静默返回、无人请求 exit，进程挂到 60s 超时，被误诊为 `TIMEOUT` 而非 profile 缺陷。这会改变 W1 的闭包算法输入。
- 修复建议：§3.5.2 闭包判据改为 "required injection ∪ headless-runner 文档化软读服务（agents、agentDefaultModel、sessions；可选 fs）"，并在 §3.11.B 增加负向自检"闭包缺任一软读服务的 profile 必须在静态核验或专项检查中被拒"，同时把"软读缺失→静默 no-op→超时"列为 §5.2 已知失败模式。

### F2（P1）模型选择通路未固定：`agentDefaultModel` 条目及其 config、llm 注册挂接完全缺席

- 位置：计划 §3.6（fake 固定 `j1-fake`/`j1-fixed`）、§3.5（profile 三文件）、§4 文件清单、§3.4.4 待核点——均无相应条目。
- 依据：headless runner 用 `defaultModel.currentSelection()` 决定 agent 的 provider/model（`packages/bundle/headless/src/index.ts:332–334`）；该服务由 `@deepseek-ai/dsh-agent-default-model` 组合条目提供，**无 settings 也可用，但 Config 必填 `provider`/`model`**（`packages/core/agent-default-model/src/index.ts:63–78`）；adapter 挂接是 `ctx.llm.registerAdapter(providers, adapter)`（`packages/llm/llm/src/index.ts:199,390`），llm 服务为 `super(ctx,'llm')` 的 LlmRuntime。
- 问题：计划固定了 fake 的 provider/model 与"不匹配拒绝"，却从未说明 selection 如何指向 fake：profile patch 里必须有 `agent-default-model` 条目且 config 为 `{provider:"j1-fake", model:"j1-fixed"}`，否则要么闭包缺 `agentDefaultModel`（触发 F1 的静默返回），要么 selection 指向不存在的默认值、`resolveModel` 拒绝、smoke 失败。fixture 侧 `registerAdapter` 的注册签名也不在 §3.4.4 必核清单（清单只列了 dsh-tools/dsh-cmdline）。
- 修复建议：§3.5.2 预期核心集合明确加入 `agent-default-model`（含固定 config，进入 allowlist 与 profile lock）；§3.4.4 待核点补 `LlmRuntime.registerAdapter` 的 providers/disposer 语义；§3.6 说明 fake adapter 经 `ctx.llm.registerAdapter(["j1-fake"], …)` 注册且 disposer 由 fixture 持有。

### F3（P2）官方 headless patch 实际含第四处 `!!js`（tools.mode），"从官方 patch 取条目"与"仅允许三个 `!!js`"存在实施陷阱

- 位置：计划 §3.5.1（L417–418"条目的实际 name/export subpath 从该 pin 的官方 headless patch 取得"）与 §3.5.4（L464"唯一允许的 `!!js` 是……三个固定绑定"）。
- 依据：`packages/bundle/headless/cordis.patch.yml:15–18` —— `tools` 条目 config 为 `mode: !!js process.env.DSH_TOOLS_MODE`，与三绑定同在一份官方 patch。J1 闭包几乎必然需要 tools 条目（`j1_noop` 经 `ctx.tools.register` 注册，`tools.register()` 见 `packages/core/tools/src/index.ts:1043`）。
- 问题：实施者按 §3.5.1 从同一官方 patch 取 tools 条目会带入第四个 `!!js`，被 §3.5.4 规则拒绝；省略该 config 是正确做法（求值本就是 undefined→默认），但计划没写，属于两条规则间未闭合的缝。
- 修复建议：§3.5.1 加一句：官方 headless patch 中另有 `tools.mode` 的 `!!js`（读 `DSH_TOOLS_MODE`），J1 的 tools 条目**不携带**该 config；该表达式列入已知排除，不进入三绑定允许集。

### F4（P2）owner_gate 单一主责规则与 §3.8.2 表格全为斜线双值自相矛盾

- 位置：计划 §3.8.1 字段表（L674：owner_gate"单一主要验收责任 gate：G13 或 J2–J7；跨 gate 回归另用 `verification_gates` 数组列出，不能用斜线字符串代替责任"）对照 §3.8.2 表（L684–717）"去向"列几乎全为 `J3/J4`、`J5/J7`、`G13/J7` 等斜线值。
- 问题：计划自己禁止用斜线字符串表达责任，紧接着的最低 leaf 集合表却全部用斜线且未指明哪个是 owner。30 行 × owner 分配被留给实施者裁量，恰是 §1.2"其他接口与数据设计不再交给实施者自行选择"要消除的。这是实质未决，会影响 W4 验收（"catalog 全量对应"检查以什么为准）。
- 修复建议：表格拆成 owner_gate / verification_gates 两列，或在表前明确约定"斜线首项为 owner_gate，其余进 verification_gates"；两种任选其一，但必须落在计划正文。

### F5（P2）source snapshot 新增排除目录用裸名匹配，可能让被测源静默逃出漂移检测

- 位置：计划 §3.10 source snapshot（L892–898：排除 `node_modules`、`lib`、`dist`、`cache`、`.cache`、`evidence`…）。
- 依据：现有 `source_snapshot` 的排除是按 `rel.parts` 成员匹配（`run_baseline.py:121`），即路径中**任意一段**命中即整树排除。计划沿用该机制新增裸名 `lib`/`dist`/`cache`。
- 问题：J1 自己的 TS 源在 `v8/compat/host/src/`，暂无冲突；但任何未来叫 `lib` 的**源**目录（例如 profile 模板内 `plugins/lib`、fixture 布局调整）会被静默排除，"源与产物无漂移"准出义务对其失明。另外 `.lock` 后缀新增未指明对象：pg-agent 仓内 `uv.lock` 已单列，`prepare.lock` 在 `.pgdata`（不进快照），该扩展当前是空集或含义不明。
- 修复建议：排除限定为具体相对路径前缀（如 `v8/compat/host/**/lib/` 仅当其为声明的产物目录），或保守方案：在 §3.11.E 增加负向自检"仓内新增名为 lib/dist 的**非产物**源目录必须进入 snapshot"；`.lock` 写明针对哪个文件或删去。

### F6（P2）准备产物的生命周期与磁盘所有权未定义；多个合格 preparation 并存时 gate 的选择规则缺失

- 位置：计划 §3.3（布局 L293–306、`DSH_SOURCE_ROOT` L306–307）、§3.4.3 缓存规则（L372–379）。
- 问题：每次重新准备产生新 preparation ID（独立 clone + pnpm-store + node_modules + build-home，GB 级），失败目录保留 `preparation-report.json`——但计划没有任何保留/清理/淘汰策略：谁可以删、何时可删、失败目录中 source/node_modules 是否可回收、`.pgdata/dsh-j1` 无上限增长。同时当多个**合格** preparation 并存（同 pin 重新准备后旧目录仍合格）时，gate 只校验 `DSH_SOURCE_ROOT` 指向"某个合格 preparation"，证据里如何区分/记录选择、旧合格 preparation 是否永久可用，均未写。这是双方（export 与计划）都遗漏的所有权/生命周期项。
- 修复建议：§3.3 增补：(a) 保留策略——仅允许人工清理整个 preparation 目录、清理不影响已封存证据（证据含 preparation-id 与产物 hash，可事后审计）；(b) 并存规则——gate 报告记录所用 preparation-id 与 ready.json hash，同 pin 多个合格 preparation 均可用但须逐次记录；(c) 失败目录允许在保留 report 后整目录删除。

### F7（P3）"六项现有 external blocked host 事实"计数与源码常量（七项）不符

- 位置：计划 §3.2.3（L233"六项现有 external blocked host 事实不解除"）。
- 依据：`p0c_report.py:114–122` `EXTERNAL_BLOCKED` 是**七**项（①–⑦），⑦ `blocked:real-provider-credentials` 是仅诊断的 credentials 源。
- 问题：若计划有意排除⑦（credentials 不是 host 事实），"六项"勉强可辩，但这正是本轮刚纠正过的"固定计数"类错误的残留形态（G13 无六项 unresolved 计数）；裸计数在源码演进后必然腐化。J1 不改 `p0c_report.py`，该约束本可以直接引用常量而免于计数。
- 修复建议：改为"`EXTERNAL_BLOCKED` 全部现有条目（当前 ①–⑦）不解除"，或明确写"①–⑥ host 事实 + ⑦ credentials 诊断源均保留"，不用裸数字。

### F8（P3）240 秒 gate 预算未分账：负向"中断／超时用例"若复用 60s smoke 超时将挤占预算且失败会被误诊

- 位置：计划 §3.7.3（L626–628：smoke 60s、runner 外层 240s、2s 关闭窗口）与 §3.11.D（L969–979：正向 smoke + sandbox 自检 + 负向 profile + 统计拒收 + 中断/超时用例 + 前后 hash + 清理确认，全在一个 `test_host_pin.py` 进程内）。
- 问题：单个 gate 内至少 3–4 次 built CLI 启动（正向、负向 profile、中断用例、超时用例）+ 前后两次 DSH 工作树/产物摘要 + sandbox 自检。若超时负向用例直接复用 60s 超时，单项即吃掉 1/4 预算；总和逼近 240s 时外层 runner 以 TIMEOUT 杀整 gate，把"预算不足"误诊为 J1 失败，且违背"每项只有一次 attempt"下的可重复性。
- 修复建议：§3.11.D 规定中断/超时负向用例使用用例级短超时（内部固定常量，如 ≤5s，不开放为 CLI 参数）；§3.7.3 给各阶段粗预算（核验/自检/正向/负向合计留出安全边际），实施后在人读报告记录实测时长。

## 结论

计划相对 export 基线是净改进：四处父级纠正全部经源码证实，保真台账（§8）未发现准确内容被删或弱化，矩阵 30 ID、runner 六差距、memory-only 前提、telemetry 开关、inspector 公共 API 等负载断言全部核实成立。**但 F1+F2 必须在实施 W1 前解决**：二者同根（headless-runner 的真实依赖不在 required injection 里），直接决定最小闭包算法的输入和 profile 三文件的内容，不改则静态核验全绿的 profile 可能运行期静默挂起。F3–F6 是实施陷阱与未决所有权，宜在计划文本层面收口；F7–F8 是措辞与预算精度问题，不阻塞开工。所有修复均不扩大 J1 范围、不触碰 J2/J4/J5、不降低任何既有验证义务。

## 父级核验与处理记录（2026-09-18）

本节为原审查的后续处置，不改写上文被审快照，也不声称第二轮独立复审。

| Finding | 核验与处理 |
|---|---|
| F1 | **部分前提被源码反驳**：`packages/bundle/headless/src/index.ts:38–39` 明确 `export const inject = ['agentDefaultModel', 'agents', 'sessions']`，并非没有 required 声明；`agent-loop/src/index.ts:359` 也有 static inject。接受补强为闭包必须同时核 entry/module/class 声明和实际消费，并增加缺服务的 preflight/ready 拒收；不采纳“源码未声明”的结论。 |
| F2 | 接受。计划显式固定 agent-default-model 的 provider/model、agent-loop agents=[]、fake registerAdapter 的 route/disposer、tools output schema/render 和错误 selection 负向。 |
| F3 | 接受。J1 tools.mode 固定 native，官方 patch 的 env 表达式明确排除；仅允许 headless task/sessionId/json 三绑定。 |
| F4 | 接受。矩阵表明确首项为 owner，其余为 verification_gates，JSON 禁止斜线字符串。 |
| F5 | 接受。生成物全在 .pgdata；不新增全局 lib/dist/cache 排除，新增同名源目录必须入快照的自检；.lock 用途明确。 |
| F6 | 接受。DSH_SOURCE_ROOT 精确选择、报告记录 preparation_id/ready hash；共享/独占锁互斥；人工整目录回收前封存安全准备报告，历史证据保留。 |
| F7 | **计数纠错前提不成立**：`test_compat.py:87–104` 的 INITIAL_EXTERNAL_BLOCKED 正是①–⑥六项当前 host 事实；reporter允许全集另含⑦诊断源。计划进一步点名两集合，不把⑦自动注入 keyless。 |
| F8 | 接受。总内部预算210秒、外层240秒；负向倒计时从状态标记后开始且≤5秒，静态拒收不额外启动CLI，报告记录阶段时长。 |

父级另补：全部运行期 Node 工具纳入禁网络策略；版本化 runtime 闭包摘要含依赖/资源而非仅 CLI；先清理确认再封存 passed；--report-json 不删除旧目标，使用私有 invocation_id 防错配；read_j1 校验必填 checks、claims 与 artifact 引用，cleanup_unconfirmed 停后续。均为原安全/证据要求的具体化，无范围扩张。最终 fidelity 依计划 §8 台账核对，保留所有适用基线义务；Linux 实现仅因用户明确缩小平台范围而删除。
