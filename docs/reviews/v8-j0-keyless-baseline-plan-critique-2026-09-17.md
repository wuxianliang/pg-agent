# V8 J0 无凭据基线计划：设计批评

**日期**：2026-09-17
**范围**：仅审查 `docs/plans/v8-j0-keyless-baseline-report-plan-2026-09-17.md`（421 行）与其 context_builder 基线 export（807 行，Generated Plan 后部分）。不实施、不改计划、不运行测试。
**用户 Mid-flow 决议**（优先于 export 基线）：
1. 普通 G13 始终 keyless + 显式 `--real-provider-smoke` 缺 key exit 2
2. `compat_contract_passed` 恒 False 保留终签、`passable` 引用严格完整目标
3. Runner 不做 resume（只保留 checkpoint 失败/中断记录，任何恢复全新 fresh run）

**方法**：对 named seam 做 spot-check（`test_compat.py`、`p0c_report.py`、`EXTERNAL_BLOCKED`、`validate_results`、`build_report`、`render`），以代码行为为判据。最多 6 条可执行 finding，按 P0/P1/P2 定级。

---

## 总评

计划在 export 基线上做了三处实质性纠正，均正确：
- 删除 `--resume`，以只读 checkpoint + fresh 全跑替代（§6.3/§11.3）
- `full_target_achieved` 不接受 mandatory blocked（§5.2 vs export §3.2 原式）
- `not_run_reasons` 默认值从 `{}` 改为 `None`（§5.1 vs export §3.2 mutable default）

计划整体不存在阻断级（P0）漏洞。以下 6 条 finding 中无一要求推翻设计或重新排序 W1–W4，但 F1 和 F2 若不在实施前固定接口，可能导致 W3 代码返工。

---

## Finding 1（P1）：G13 安全报告输出接口 (`--report-json`) 未固定——W1/W2→W3 契约缺口

**位置**：计划 §6.4 第 5 段

**问题**：计划写道"G13为runner提供安全结果文件输出选项（**如** `--report-json`）"（重点在"如"），但未 pin：

| 缺失项 | 影响 |
|---|---|
| flag 名称和参数签名 | W3 的 runner 需要知道精确 argv 才能自动附加；`如` 暗示尚未定型 |
| JSON schema 版本与字段子集 | 是完整 `build_report` dict 还是安全子集（去掉 `capability_matrix` 原始 SQL 值等）？ |
| 与 stdout `render()` 输出的关系 | 同时写 JSON 和 stdout？还是 `--report-json` 取代 print？runner 依赖 stdout 的 `[PASS]` 行计数做观测，schema v2 增加 `not_run` 后 render 输出格式也变了 |
| 报告生成失败时的文件状态 | 若 `validate_results` 抛 `ReportError`（即拒收），G13 exit 1，`--report-json` 目标文件不存在或为空；runner 此时如何区分"G13 产品断言失败"和"报告无法生成" |

**代码证据**：当前 `test_compat.py:main()` 无文件输出机制（`print` + `SystemExit` 是唯一出口），`p0c_report.render()` 返回字符串不写文件。因此 `--report-json` 是 W1/W2 的新增工作，但计划只在 W3 §6.4 提及，W1 §4.1/§4.3 和 W2 §5.3 均未列入接口。

**建议**：在 §4.1 或 §5.3 补一段，固定 flag 名/参数/schema/错误行为，并在 §3 work-item 表 W1 的 Key files 中标注此交付项。

---

## Finding 2（P1）：`not_run` 的 requirement × reason 校验矩阵分散，缺集中决策表

**位置**：计划 §5.1、§5.4、§5.5 分散描述

**问题**：`not_run` 是新增结果值，其合法性依赖于 `requirement`（mandatory / optional_smoke）和 `reason`（四值闭合集）的组合。当前 `validate_results` 的检查顺序已经是六步链式 `raise`（first-error-wins），新增 `not_run` 引入至少以下分支：

| requirement | result | reason | 期望行为 |
|---|---|---|---|
| mandatory | 缺失 | — | `MISSING_RESULT`（既有） |
| mandatory | `not_run` | `not_requested` | 结构错误拒收（§5.1："前两者只允许 optional smoke"）|
| mandatory | `not_run` | `credentials_absent` | 同上 |
| mandatory | `not_run` | `execution_interrupted` | 允许，结论 false |
| mandatory | `not_run` | `dependency_unavailable` | 允许，结论 false |
| optional_smoke | `not_run` | `not_requested` | 允许，不影响 keyless 支持面 |
| optional_smoke | `not_run` | `credentials_absent` | 允许 |
| mandatory | `not_run` | reason 缺失或非法 | `INVALID_NOT_RUN_REASON`（§5.4） |

计划文字覆盖了每一行，但分散在三个小节，且与六主 code 的执行优先序叠加。实施者需要自行合成这张表并决定它在 `validate_results` 中插入的位置（在 fail-class 2 之前？之后？）。如果 mandatory + `not_run` + `not_requested` 被 MISSING_RESULT 的 `runnable` 集合逻辑先过滤掉（因为 `not_run` 在 `results` 中是有值的，不会触发"缺失"），则需要独立的新检查才能拒收它。

**建议**：在 §5.4 用一张类似上表的集中决策矩阵替代散文描述，并明确其检查插入位于 illegal-value 检查之后、fail-class 2（缺失）之前。

---

## Finding 3（P2）：当前 fail-class 5 测试向量实际触发 fail-class 4——计划诊断正确但可标记更显式

**位置**：计划 §2 Background 表最后两行 + §5.5 向量 5

**代码证据**：

```python
# test_compat.py:1270-1274 — 当前 FC5 测试
sync_matrix = compat.matrix_blocked(conn, "sync_before_io", "supported")
p0c_report.build_report(rigged, sync_matrix,
                        external_blocked=frozenset(EXTERNAL_BLOCKED))
```

`EXTERNAL_BLOCKED`（test 侧 6 项，keyless 路径加第 7 项）始终包含 `blocked:all-real-io-subcases`。`effective_blocked()` 对此展开为全部 REAL 行 blocked。因此 `rigged["c1-real-retry-single-batch"] = "passed"` 命中的是"blocked REAL passed" → **FC4**，而非"无 real loop 的 REAL passed" → FC5。当前测试只 `except ReportError` 不检查 code，故通过但未证明目标规则。

计划 §2 已诊断（"部分用例会被更早 missing/block 条件抢先"）且 §5.5 向量 5 正确修复（"清除all-real-io外部原因"），但未在向量 5 的说明中显式标注"此为当前假阳性的修复"。

**影响**：不阻断设计。向实施者确认此处需要从 `external_blocked` 中精确移除 `blocked:all-real-io-subcases`（保留其余 5–6 项），否则同一 preemption 问题会重现。

**建议**：在 §5.5 向量 5 注释中添加一句 "当前测试因 EXTERNAL_BLOCKED 含 ② 而实际触发 FC4，此处以移除 ② 修复"。

---

## Finding 4（P2）：Runner 对 G13 失败场景下报告获取的降级路径未描述

**位置**：计划 §6.3 步骤 5 + §6.4

**问题**：Runner 证据模型包含"G13实际报告的安全结构与三个结论"。获取路径是 `--report-json`。但以下场景中该文件不存在或不完整：

1. **G13 产品断言失败（exit 1）**：`validate_results` 抛 `ReportError` 时 `build_report` 未完成，JSON 未写。
2. **G13 被 runner timeout 杀死**：进程组终止后 JSON 可能为空/截断。
3. **G13 的 setup_db 失败**：甚至未进入测试函数。

计划 §6.3.5 说"attempt 结果并原子替换 checkpoint"，§6.3.6 说"单脚本失败可以继续收集后续脚本诊断"。但对 G13 专属的报告文件缺失，runner 应该：
- 仅记录 exit code + stdout hash（不试图解析报告），还是
- 将此视为 runner 级 schema 错误？

**建议**：在 §6.4 G13 报告获取段明确：当 `--report-json` 目标文件缺失或 JSON 无效时，runner 记录 `g13_report: null` + 失败原因，不将此升级为 runner 自身的前置错误（exit 2）。证据中"三个结论"字段标为 unavailable 而非 false。

---

## Finding 5（P2）：`RESULTS` 模块级可变状态的清理时机与 `test_fake_provider` 分离后的注册路径

**位置**：计划 §4.1 第 5 段 + §4.4 最后一条

**代码证据**：

```python
# test_compat.py:70
RESULTS: dict[str, str] = {}
```

当前 `RESULTS` 和 `EXTERNAL_BLOCKED` 是模块级可变 dict/set。`test_deepseek()` 在凭据存在时登记两项（`c12-db-real-provider-protocol`、`c12-db-fake-suite`），keyless 时只登记 `partial` 并 add blocked 源。

计划 §4.1 说"main() 每次运行重置本模块 RESULTS/not_run_reasons 与本次 external 原因"。但 `test_fake_provider()` 分离后，其登记的 `c12-db-fake-suite=passed` 必须写入 RESULTS 才能被 `test_reporter()` 读到。计划未明确：

- `test_fake_provider()` 直接写 `RESULTS["c12-db-fake-suite"]`？（当前位于 `test_deepseek` 内部，迁移后仍可行，但 fake 函数与模块全局耦合）
- 还是 fake 函数返回结果、由 `main()` 统一注册？（更干净但需要 main 知道 key 名）

§4.4 验证项"连续两次 main/test 运行不复用上一轮结果"要求 `RESULTS.clear()` 在 `main()` 入口执行。但 `EXTERNAL_BLOCKED` 是 set 且初始值含 6 项——clear 后需要重新填充初始值，否则报告器的 allowlist 校验会拒收合法来源。计划应明确 `EXTERNAL_BLOCKED` 的重置目标是初始 6 项集合而非空集。

**建议**：在 §4.1 接口段补充 `main()` 入口的重置逻辑：`RESULTS = {}`、`EXTERNAL_BLOCKED = {初始6项}`（或改为不可变初始集合 + 每次构造新的 working set）。

---

## Finding 6（P2）：Export 基线 `compat_contract_passable` 改为 `full_target_achieved.passed` 别名的单调性声称不成立——计划已纠正但措辞可更明确

**位置**：计划 §5.3 第 5–6 行 + §10.3 纠正记录末段

**问题**：Export 基线 §3.2 写道：

> `compat_contract_passable` 不再使用忽略 partial 的旧公式，改为同一保守值。此为语义收紧，不会产生错误的 false→true。

计划 §10.3 末段正确反驳：

> 基线把两个 legacy 布尔改为新 alias 却称"只收紧、不可能 False→True"，与原 passed 恒 False 冲突

但实际的非单调性更精确：当前 `passable = not unresolved and failed==0 and blocked==0`。新 `full_target_achieved` 要求额外的 `support_surface=true` 和 `dual_loop=true`，因此在理论上更严格。然而新 `full_target` 对 blocked 的门槛是"无 **mandatory** blocked"（§5.2），而旧公式是"blocked==0"（含 optional）。若未来 optional_smoke 行恰好被 matrix blocked 且无其他 blocker，旧公式 `passable=false` 而新 `full_target` 忽略 optional blocked 可能为 true（前提是其他条件全满足）。

在 J0 当前状态下这无实际影响（dual_loop 恒 false → full_target 恒 false）。但当后续 J 阶段推进时，"optional blocked 不阻断 full_target" 的语义差异应在 §5.3 兼容策略中显式标注，避免实施者简单地写 `passable = conclusions["full_target_achieved"]["passed"]` 而认为方向永远更保守。

**建议**：在 §5.3 `passable` 别名段加一句："在 optional_smoke 行被 matrix blocked 的极端情况下，新公式可能比旧公式更宽松；当前状态不触发（dual_loop=false），但别名赋值应附带 schema_version 断言。"

---

## 结论

| Finding | 级别 | 阻断？ | 类别 |
|---|---|---|---|
| F1 `--report-json` 接口未固定 | P1 | 否，但影响 W3 实现节奏 | 接口缺口 |
| F2 `not_run` 校验决策表缺失 | P1 | 否，但增加实施错误风险 | 细节遗漏 |
| F3 FC5 假阳性修复标注 | P2 | 否 | 代码反驳补充 |
| F4 Runner 对 G13 报告缺失的降级 | P2 | 否 | 失败路径遗漏 |
| F5 `RESULTS`/`EXTERNAL_BLOCKED` 重置 | P2 | 否 | 生命周期细节 |
| F6 `passable` 别名非单调性 | P2 | 否 | 接口语义精确性 |

**无阻断计划漏洞。** 两条 P1 建议在实施 W1/W2 前固定（文字补丁，不需要重新排序工作项）。四条 P2 可在实施中落实。计划的三项用户决议（keyless 默认、passed 恒 False、无 resume）已正确嵌入各节，与 export 基线的冲突均已显式纠正。24 脚本清单（§6.2）与 `v8/README.md` 当前 24 行入口一一对应，gate_id/脚本路径/DB组均无错漏。
