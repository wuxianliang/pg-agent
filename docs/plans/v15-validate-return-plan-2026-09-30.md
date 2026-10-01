# D1：ValidateReturn / ReturnType 移植 v15: Plan

## Goal

把 jaz 的 `ReturnType` / `ValidateReturn` 两个 return 校验 hook 移植到 v15：在 `repl_exec/complete` 相位把 `exec_result` 改写从唯一的 return→continue 扩为 **return→continue ∨ return→raise**（jaz 的容忍→升级语义），提供 `max_failures` 跨迭代计数（复用 `hook_counters`）、per-invoke 校验 handler 注册（复用 hook 登记机器），交付一个新 stage 的 SQL + gate + 规格修订 rev 10（§9.4/§4.9/§13 尾追加/§18），十道既有 gate 保持全绿。

## 用户裁决（2026-09-30，Mid-flow 检查点）

1. **交付形态：开新 stage 11**（`v15/return_hooks/` 独立目录 + gate + README + 专属库；helper 放 stage 11、return_type handler 与 hook_defs 注册按 §18 留 govern；加载序十→十一）。
2. **return_type 类型面：封闭类型 DSL**（O2 轨的 jsonb 规格对象文法，替代 O1 轨的 jsonpath 谓词——见 §Design 的 spec 文法节，已并入）。
3. **ValidateReturn：注册式协议**（用户经 `v15_register_hook` 登记自己的 handler；不预插 builtin 行——O1/O2 两轨共识，主 agent 裁定）。

## Background

### jaz 参考行为（探查实证，`~/Projects/jaz/src/jaz/hooks/builtin/return_hooks.py`）

- **两级检查 + 身份跳过**：`on_repl_exec_complete` 每轮检查（`ReturnType:288-342`、`ValidateReturn:482-522`）；`on_invoke_complete` 终态兜底（同一 Return 对象已过则不重跑，`:346/:351`、`:467`）。v15 无进程内对象身份，快照即数据库行，天然免疫——兜底层在 v15 对应「`invoke/complete` 相位」，但其 io 只有 `{outcome}`（`v15_govern.sql:131`），读不到 return_value；v15 的 `repl_exec/complete` 才是唯一可校验点。
- **max_failures 容忍**：`count > max_failures` 才升级为 `ModifyExecResult(Raise)`（`ReturnType:295-311`、`ValidateReturn:493-498`）；否则降级 `Continue(output=summarize(exc), exception=exc)` 让 agent 继续工作；`None`=永不升级；负数构造期拒绝。计数 per-invoke 累计（`_failures` dict）。
- **ReturnType 构造期探针 fail-fast**（`:81-109`，sentinel 过 `is_bearable`）：坏 hint 在构造期抛 `TypeError` 而非等 agent 干完一轮。v15 对应：安装期（`invoke_hooks_optional_guard` 触发器）校验 config 里的类型规格形状，坏规格 P1524 拒绝安装。
- **ValidateReturn 异常原样透传**（`:496-503` 注释）：validator 的异常对象自己拥有消息，不包装。

### v15 移植挂点（探查实证）

**exec_result 通道扩语义（不需要新效应名）**：
- `modify_exec_result` 已在 `repl_exec/complete` 允许表（`v15_govern.sql:104`）；预留名五个不含它。
- 唯一改写句（spec §9.4:1915）：「本版唯一合法的修改是把候选 return 改成 continue，且 return_value 与 error 都是 JSON null」——扩为 return→continue（原语义，budget_forcing 唯一出口）∨ return→raise（`error` 携带 `{code,message}`，`return_value` JSON null）。
- 代码闸门两处：`v15_govern.sql:291-304`（`v15_govern_check_return` 硬编码 `result_kind='continue'`）+ `v15_loop.sql:853-876`（`v15_finish_exec` 消费分支；return→raise 需走既有 raise 终态分支 `:917-953` 的写入面：`invokes.error`/`failed`/清租约/`repl_history(repl_exception)`/`repl_exec+invoke exit failed`/DROP SCHEMA/§4.8 子送达——全部现成）。
- `invokes.return_value` 由 `jaz_return` 在语句事务内写入（`v15_namespace.sql:316-320`），complete 相位 hook 经快照 `{io,return_value}` 可读（`v15_govern.sql:1082` + io 键白名单 `:128` 含 `return_value`；budget_forcing 已用同路径读 result_kind/capture）。

**计数机器**：`hook_counters(invoke_id, counter_key, n, revision)`（schema:398-404）；budget_forcing 先例——键 `budget_forcing:<ordinal>`、增量在 `v15_finish_exec` 接受改写时（`v15_loop.sql:665-705`，消息 id 正则 `^budget_forcing:[0-9]+:[0-9]+$` 硬编码）、complete 相位不 bump（gate 已锁）。**泛化缺口**：`v15_loop_accept_forcing` 的消息 id 正则只认 budget_forcing——新 hook 的拒绝消息需要自己的计数键与正则或参数化。

**hook 注册机器完整同构先例**：`hook_defs` + `hook_defs_shape_guard` 触发器（owner=`v15_hook_<key>`、search_path=pg_catalog、STABLE、SECURITY DEFINER、digest）+ `v15_register_hook(p_hook_key, p_fn, p_baseline_required)`（govern:515-554，EXECUTE 授 owner+bootstrap）+ gate 夹具 `install_hook`（test_govern.py:159-196，含全部拒绝用例 :746-830）。**关键**：`invoke_hooks_optional_guard`（govern:413-509）按 hook_key 逐个枚举、**无 ELSE**——新 hook_key 静默通过（config 只查 object 形状）；config 键白名单需为新 hook 加一个 ELSIF 分支（穷举硬约束，多键 P1524）。
- 可选 hook 全套工件清单（context_window_warning 样板）：handler CREATE + ALTER OWNER + REVOKE×2 + GRANT v15_owner + hook_defs INSERT + setup_db 角色清单 + spec §10.2 段 + §18「只许出现在 govern 文件」。
- **§18 硬约束**：五个可选 hook 的 CREATE 与 hook_defs 插入只许 govern 文件（spec:2410）；`v15_on_phase` 函数体只许 schema 桩 + govern CREATE OR REPLACE——**新 hook 的 dispatch 分支落在 govern 文件的 `v15_on_phase` 体内，不改签名 oid**。

**错误码窗口**：P1540–P1548 空 9 个号；尾追加须同步**两张映射**（`v15_govern_known_code` 的 govern 原建体 + provider REPLACE 体，`v15_loop_sqlstate` 的 CASE）——`v15_io_sqlstate` **不动**（`V15_RAISE→P1529` 先例：loop 层码只进 loop CASE；评审 Q4）+ spec §0.19/§13/§18 同 commit。rev 9（provider）先例完整（文档头修订句、§13 加行、§18 点名、矩阵/台账行）。

**hook abort 码闭集**：hook 返回的 abort 码只有 {IO_EXHAUSTED, BUDGET_EXHAUSTED, RECURSION_EXCEEDED, ITERATION_EXCEEDED} 可原样入 `invokes.error`，其余归一 `V15_HOOK_ABORT`——**return→raise 的 error.code 若由 hook 携带，属 validator 自造码，将走归一或需新码**（设计要点）。

** jaz 对应缺口（不移植）**：`ValidateREPLCode`（执行前 veto，属另一效应 SupplyExecResult 预留名）不在 D1 范围。

# Summary

本计划在现有 v15 hook、`exec_result` 改写、`hook_counters` 与 hook 注册机器上做一次**定向扩展**：新增 `return_type` 内建 hook 与 `validate_return` 注册式 validator hook，允许 `repl_exec/complete` 将候选 `return` 改写为 `continue` 或带 `V15_VALIDATION_FAILED` 的 `raise`；校验失败的容忍次数按 invoke 与 hook ordinal 存入既有 `hook_counters`，并把 `budget_forcing` 的计数接受逻辑泛化。v15 不新增表、不改变 `v15_on_phase` 签名或 oid、不实现无法由现有 `{outcome}` 载体支持的 `invoke/complete` 值校验；新增 SQL helper 与 gate 放入末尾 stage 11，hook handler 的 CREATE、权限、`hook_defs` 注册仍全部留在 govern 文件。新增错误码采用尾追加 `P1540 / V15_VALIDATION_FAILED`，并同步三张 SQLSTATE/known-code 映射、rev 10 规格、偏差台账、覆盖矩阵与 README。

---

# Current-state analysis

## 1. 现有加载、所有权与 stage 边界

当前 v15 的合运行时由十个 SQL 文件累计加载，顺序以 schema、namespace、config、protocol、repl、io、loop、tree、govern、provider 结束；`files_through()` 始终取前缀。[**直接观察**：`pg-agent/v15/load.py:14-31`]

因此 D1 不能把新 SQL 插入 govern 或 provider 之前，否则会改变已有 stage 的前缀含义。新 SQL 必须作为第 11 项追加；`files_through("govern")` 仍必须只返回前 9 个文件，完整合运行时才包含第 11 个文件。[**推断**：由现有累计加载规则与 §18 冻结协议共同决定；依据 `v15/load.py:14-31`、`docs/designs/v15-jaz-dev.md:2380-2428`。]

现有 hook 状态已经有完整的持久化承载：

- `hook_defs` 保存全局 handler oid、owner、digest、`baseline_required`。
- `invoke_hooks` 保存每个 invoke 的 ordinal、channel、config、state。
- `hook_counters` 保存 `(invoke_id, counter_key, n, revision)`，正好可承载每个 invoke 的验证失败次数。[**直接观察**：`pg-agent/v15/schema/v15_schema.sql:365-404`]
- handler 的注册与运行时 digest/owner/权限检查已经由 `v15_register_hook`、shape trigger 和 dispatcher 复用。[**直接观察**：`pg-agent/v15/govern/v15_govern.sql:515-554`；`pg-agent/v15/govern/test_govern.py:746-830`]

D1 不增加表、不增加列，也不改变这些表的主键或生命周期。

## 2. 返回值从模型到 hook 的完整链路

模型执行 `jaz."return"(value)` 时，`jaz_return` 在当前语句事务中写入 `invokes.return_value`，但不直接将 invoke 置为终态；`jaz."raise"` 则写入 `invokes.error`，错误码固定为 `V15_RAISE/P1529`。[**直接观察**：`pg-agent/v15/namespace/v15_namespace.sql:284-374`]

`v15_finish_exec` 随后：

1. 锁定 invoke 并确认 lease/fence/执行状态；
2. 根据已完成语句确定候选 `return`、`raise` 或 `continue`；
3. 组装 `repl_exec/complete` 的 `io`；
4. 先写 `repl_exec/complete` 事件，再调用 `v15_on_phase`；
5. 消费 dispatcher 返回的 `exec_result`；
6. 选择 return、raise 或 continue 终态分支。[**直接观察**：`pg-agent/v15/loop/v15_loop.sql:708-876`]

当前 `exec_result` 消费点只接受一种改写：候选 `return`、空 capture，被改成 `continue`，且 `return_value` 与 `error` 必须是 JSON `null`；接受后清除 `invokes.return_value`，调用 `v15_loop_accept_forcing`，再进入 continue 分支。[**直接观察**：`pg-agent/v15/loop/v15_loop.sql:853-876`]

因此现有数据流是：

```text
jaz."return"
  → invokes.return_value
  → v15_finish_exec 生成 repl_exec/complete io
  → v15_on_phase
  → hook handler 按 oid 执行
  → v15_govern_check_return
  → 同阶段效应合成与落地
  → v15_finish_exec 消费 exec_result
  → iteration / invokes / repl_history / span exit
```

D1 应扩展这条已有链路，不应在 `jaz_return` 中加入 validator 逻辑；这样 return API、REPL 执行器和 hook 仍保持职责分离。[**推断**：由现有 `jaz_return` 只写候选值、`v15_finish_exec` 统一消费结果的分工得出；依据 `v15_namespace.sql:284-327`、`v15_loop.sql:708-876`。]

## 3. 当前 dispatcher 与快照能力

`v15_on_phase` 是唯一 dispatcher。它按 `invoke_hooks` 的 ordinal 顺序读取 handler oid，按 oid 解析 schema/name 后调用，不按 hook key 写分支；handler 看到的快照包含：

- 当前 phase 的 `io`；
- `resolved_config`；
- 四项治理 ceiling；
- `recursion_available`；
- blackboard；
- `counters`；
- 当前 hook 的 `self` 信息；
- 所有 hook 的摘要列表。[**直接观察**：`pg-agent/v15/govern/v15_govern.sql:1063-1200`]

因此：

- `return_type` 不需要新的 dispatcher 分支；
- `validate_return_<name>` 不需要新的 dispatcher 分支；
- 两者都能从 `self.config` 读取 `max_failures`；
- 两者都能从 `io.return_value` 读取候选值；
- 两者都能从 `counters` 读取本 hook 当前计数。

这也是选择“两个 hook family + 泛型 handler 调度”而不是修改 `v15_on_phase` 添加 key 分支的原因。[**推断**：由 dispatcher 已按 oid 泛型执行、快照已暴露 config/counters 得出；依据 `v15_govern.sql:1063-1200`。]

当前 `repl_exec/complete` 的允许效应已经包含 `modify_exec_result`，因此不需要新增效应名。[**直接观察**：`pg-agent/v15/govern/v15_govern.sql:78-107`]

## 4. v15 能校验的位置与 jaz 两级检查的差异

当前 phase io 白名单中：

- `repl_exec/complete` 包含 `capture`、`error`、`result_kind`、`return_value`；
- `invoke/complete` 和 `invoke/exit` 只有 `outcome`。[**直接观察**：`pg-agent/v15/govern/v15_govern.sql:110-131`]

因此 `repl_exec/complete` 是 v15 唯一能够读取候选 return value 的 hook phase。`invoke/complete` 无法实现 jaz `InvokeComplete` 的值级 backstop；给它增加 `return_value` 会改变冻结的 phase 信封与事件协议，不能作为 D1 的隐式补丁。[**推断**：依据 phase io 键闭集和 `v15_on_phase` 的 exact-key 校验；依据 `v15_govern.sql:110-131`、`v15_govern.sql:~990-1040`。]

jaz 的 `ReturnType` / `ValidateReturn` 在 `REPLExecComplete` 检查，在 `InvokeComplete` 再检查，并用 Python 对象 identity 避免同一个已通过的结果重复校验；失败次数与对象状态保存在进程内字典中。[**直接观察**：`jaz/src/jaz/hooks/builtin/return_hooks.py:288-351`、`jaz/src/jaz/hooks/builtin/return_hooks.py:443-522`]

v15 没有进程内 result object identity，也不应新增 worker 内存状态。D1 的等价物确定为：

- **语义校验层**：仅在 `repl_exec/complete` 读取数据库快照中的候选 return value；
- **机械终态 backstop**：`v15_finish_exec` 只接受经 `v15_govern_check_return` 认可的 return→continue/raise 形状，并负责写入最终 `invokes.error`、历史与 exit 事件；
- **不做第二次 predicate/type evaluation**：`invoke/complete` 继续只做 blackboard/生命周期 hook；
- **不做 identity skip**：同一次校验不会在另一个 phase 重跑，因此没有重复调用问题。

这是一项有意的 v15 偏差，而不是遗漏。[**推断**：由 v15 phase 载体不含 return value、数据库行是权威状态得出；依据 `v15_govern.sql:110-131`、`v15/schema/v15_schema.sql:377-404`、`jaz/return_hooks.py:288-351`。]

## 5. 当前效应校验与计数限制

`v15_govern_check_return` 当前对 `exec_result` 硬编码要求：

- `result_kind = continue`；
- `return_value = JSON null`；
- `error = JSON null`；
- 候选 phase 是 `repl_exec/complete`；
- 候选 result kind 是 `return`；
- capture 是空字符串。[**直接观察**：`pg-agent/v15/govern/v15_govern.sql:291-304`]

`budget_forcing` 是现有唯一 return→continue 样板：handler 生成 `budget_forcing:<ordinal>:<n>` 消息，dispatcher 在 complete phase 不 bump，`v15_finish_exec` 接受后再调用 `v15_loop_accept_forcing` 增加计数。[**直接观察**：`pg-agent/v15/govern/v15_govern.sql:~790-850`、`pg-agent/v15/loop/v15_loop.sql:665-705`；`pg-agent/v15/govern/test_govern.py:983-1033`]

D1 必须保留这个时序，否则会破坏已有 gate 对“complete 不 bump、finish 接受后 bump”的断言。

---

# Design

## 1. 已裁决的总体方案

| 决策面 | D1 裁决 |
|---|---|
| hook 数量 | 两个 hook family：内建 `return_type`；注册式 `validate_return` / `validate_return_<suffix>` |
| ReturnType DSL | 封闭 jsonb 类型规格对象（五形态文法，§2.1）；不移植 Python `TypeForm`、beartype 或 jsonpath（用户裁决 2） |
| ValidateReturn handler | 用户通过既有 `v15_register_hook` 注册 `(jsonb) returns jsonb` 的 SQL/plpgsql handler；handler 使用新增 helper 生成统一效应 |
| 容忍语义 | `count < max_failures` 时 return→continue；继续次数达到上限后下一次 return→raise |
| 无上限 | `max_failures = JSON null` 表示永不因该 hook 升级 |
| 终态错误码 | 新增 `V15_VALIDATION_FAILED / P1540` |
| abort 关系 | P1540 只用于 `exec_result.error.code`；若错误地放入 abort.error，仍按现有规则归一为 `V15_HOOK_ABORT/P1538` |
| 校验 phase | 仅 `repl_exec/complete`；`llm_query/enter` 仅由 `return_type` 注入提示 |
| 计数 | 复用 `hook_counters`，counter key 为 `<hook_key>:<ordinal>` |
| 计数落点 | 仅在 `v15_finish_exec` 接受 return→continue 后 bump |
| 新 stage | `return_hooks` 作为 SQL_LOAD_ORDER 第 11 项 |
| dispatcher | 不添加 per-hook-key dispatch 分支；保持按 oid 泛型调用 |
| schema | 不新增表、列、索引或迁移 |

选择新错误码而不是复用 `V15_RAISE`，因为 `V15_RAISE/P1529` 已表示模型主动调用 `jaz."raise"`；复用会使框架拒绝 return 与模型显式 raise 在观测上不可区分。[**直接观察**：`jaz_raise` 固定写入 `V15_RAISE/P1529`，`v15_finish_exec` 的 raise 分支直接消费 `invokes.error`，见 `v15_namespace.sql:329-374`、`v15_loop.sql:917-953`。**推断**：因此需要 P1540 区分框架验证终态。]

## 2. Hook config 契约与安装期校验

### 2.1 `return_type`（封闭类型 DSL，用户裁决 2）

`invoke_hooks.config` 必须是对象，且键集合**恰好**为：

```text
{
  "spec": <jsonb 规格对象>,
  "max_failures": <JSON null or [0, 2147483647] 整数>
}
```

**spec 文法**（对象，恰好一种形态；exact-keys 判定键集）：

| 形态 | 键 | 含义 |
|---|---|---|
| 标量 | 只有 `type`，值 `any`/`null`/`string`/`number`/`boolean` | `jsonb_typeof` 相等；`any` 接受任何 jsonb 含 JSON `null` |
| 数组 | 恰好 `type=array` + `items`（递归 spec） | 每元素匹配 `items`；空数组通过 |
| 对象 | 恰好 `type=object` + `required`（字符串数组）+ `properties`（对象，值为 spec） | 见下 |
| 联合 | 只有 `anyOf`，非空数组 1..8，元素是 spec | 任一分支匹配即通过 |
| 枚举 | 只有 `enum`，非空数组 | 与任一元素 jsonb 相等即通过 |

对象规则：`required` 名字两两不同且都在 `properties`；`properties` 中不在 `required` 的键是可选键（值里缺该键则通过，有则按 spec 查）；值里多余键允许（开放对象）；键名 `^[A-Za-z_][A-Za-z0-9_]{0,62}$`（消息路径单义限制，记入偏差 D32）；嵌套深度 ≤ 8（根为 1）。数字不区分整数与浮点（`jsonb` 的 `number` 是一种——相对 beartype `int` 的有意差别，D32）。

**安装期 fail-fast**（对应 jaz 构造期探针）：`invoke_hooks_optional_guard` 新增 `return_type` ELSIF，用 `v15_return_spec_valid(spec)` 做形状校验；非法 spec（多余键、坏形态、深度超限、坏键名、`anyOf` 超 8、`max_failures` 非法）安装期抛 `V15_VALUE_INVALID/P1524`，不等模型跑一轮。

**运行期匹配**：`v15_return_spec_fault(value, spec) returns text`——匹配返回 SQL NULL；否则返回不带前缀的失败文字；spec 非法时返回 `config spec invalid`（不抛异常）。fail-closed：运行期任何错误按校验失败处理。

**render(spec)**（消息用，稳定渲染）：标量=type 词；数组=`array of <render(items)>`；对象=`object {` + required 按序 `<key>: <render>` + 可选键按 UTF-8 字节序 `<key>?: <render>` + `}`；anyOf=`anyOf (<render> | <render>)`；enum=`enum (<elem::text>, ...)`。

**失败文字**（路径从 `$` 起）：根类型不符=`Expected <render(root)>. Got jsonb <typeof>.`；深层=`Expected <render(node)> at <path>. Got jsonb <typeof>.`（与冻结示例 3 同语序——评审 3a）；缺必填键=`Expected <render(root)>. Missing key <path>.`（path 如 `$.n`、`$[0]`）；anyOf 全败/enum 不符用根模板配整棵 render。enum 通过性按 jsonb 数值相等（`enum:[1]` 匹配 `1.0`）、展示按 `elem::text` 字形——§10.2 写明。handler 前缀 `[v15 return_type] `（一个空格）；continue 消息与 raise 的 `error.message` 同一整句。

冻结示例（gate 与规格 §10.2 逐字相同）：

```text
spec {"type":"string"}，值 1：
[v15 return_type] Expected string. Got jsonb number.
spec {"type":"object","required":["n"],"properties":{"n":{"type":"number"}}}，值 {}：
[v15 return_type] Expected object {n: number}. Missing key $.n.
同 spec，值 {"n":"x"}：
[v15 return_type] Expected number at $.n. Got jsonb string.
spec {"anyOf":[{"type":"string"},{"type":"null"}]}，值 1：
[v15 return_type] Expected anyOf (string | null). Got jsonb number.
spec {"type":"object","required":["x"],"properties":{"x":{"anyOf":[{"type":"string"},{"type":"null"}]}}}，值 {"x":1}：
[v15 return_type] Expected anyOf (string | null). Got jsonb number.
```

**两只内核辅助函数**（owner `v15_owner`、STABLE、SECURITY INVOKER、search_path=pg_catalog、REVOKE PUBLIC、`GRANT EXECUTE` 给 `v15_owner` 与 `v15_hook_return_type`——hook 运行时 current_user 是 hook owner，漏授会让调用抛错、异常隔离把非法 return 当通过）：`v15_return_spec_valid(jsonb) returns boolean`（只走形状）、`v15_return_spec_fault(jsonb, jsonb) returns text`。两函数**放 govern 文件**（评审 Q2 裁决：optional_guard 的 ELSIF 在 stage-9 前缀库的 INSERT/UPDATE 时即要调用 `v15_return_spec_valid`，放 stage 11 会留晚绑定赌注；它们是内核辅助函数而非 hook handler，不违反 §18）。辅助函数体不进 handler 摘要（摘要只盖 hook 自身 proacl）。

### 2.2 `validate_return` 与 `validate_return_<suffix>`

为了支持多个不同 validator，D1 定义一个 hook key family：

- 精确 key `validate_return`；
- 或匹配 `validate_return_<suffix>`，其中完整 key 仍必须满足既有 `hook_defs.hook_key` 名称正则；
- 每个 key 对应自己的 `v15_hook_<key>` owner role、handler oid、digest 与 ordinal；
- 允许多个 validator 同时安装在一个 invoke 中；
- 每个 validator 的计数按自己的 full hook key 与 ordinal 隔离。

config 键集合必须恰好为：

```text
{
  "max_failures": <JSON null or non-negative integer>
}
```

校验规则与 `return_type.max_failures` 完全相同。此 family 只能以 `propagating` 或 `local` channel 安装，不允许 baseline channel。安装期坏 config 抛 `P1524`；handler 本身不符合既有登记 shape 抛 `P1537`。[**直接观察**：现有 optional guard 在非 baseline channel 上校验 config，且 key 分支没有 ELSE；`v15_govern.sql:413-509`。**推断**：新 family 应加入同一 ELSIF 链，不另建第二套触发器。]

### 2.3 handler 的 ValidateReturn 协议

用户注册的 validator handler 仍必须符合既有 `(jsonb) returns jsonb`、`STABLE`、`SECURITY DEFINER`、`search_path=pg_catalog` 与 owner/digest/ACL 合同。[**直接观察**：`v15/govern/test_govern.py:159-196`、`v15/govern/v15_govern.sql:515-554`]

handler 应按以下协议工作：

1. `span/phase` 不是 `repl_exec/complete` 时返回 `proceed`；
2. `io.result_kind` 不是 `return` 时返回 `proceed`；
3. 对 `io.return_value` 执行自己的 SQL predicate；
4. 通过时返回 `proceed`；
5. 拒绝时调用新增的统一 helper，传入：
   - 当前 snapshot；
   - `valid=false`；
   - validator 自己生成的原始错误消息文本。

handler 不应通过直接 `RAISE` 表示“值不合法”。非 baseline handler 的异常在现有 dispatcher 中会被隔离、审计并继续，而不会成为 validation rejection。[**直接观察**：`v15_govern.sql:1131-1180`。**设计结论**：validator 应捕获自己的 SQL 异常并将 `SQLERRM` 作为 message 传给 helper；这样保留文本而不改变现有 handler 异常隔离合同。]

### 2.4 统一 validation helper

stage 11 新增内部 helper：

```text
v15_return_validation_effect(
    p_snapshot jsonb,
    p_valid boolean,
    p_message text
) returns jsonb
```

其职责：

- 非 `repl_exec/complete`、非 return 候选或 `p_valid=true` 时返回 `proceed`；
- 从 `self.config.max_failures` 读取上限；
- 从 `counters` 读取当前 `<hook_key>:<ordinal>`；
- `p_message` 必须是非 null 文本，长度不超过 1024；
- 当前计数小于 max，或 max 为 null：
  - 返回 `exec_result.result_kind = continue`；
  - `return_value` 与 `error` 为 JSON null；
  - 添加一条持久 user message；
  - message id 为 `<hook_key>:<ordinal>:<n>`；
  - `n` 为当前计数，不是增加后的计数；
- 当前计数已达到 max：
  - 返回 `exec_result.result_kind = raise`；
  - `return_value = JSON null`；
  - `error = {"code":"V15_VALIDATION_FAILED","message":<原始消息>}`；
  - 不产生 counted message，因此不 bump counter。

该 helper 不写表、不修改 counter、不调用外部 I/O；它只生成 dispatcher 已有闭集中的返回对象。counter 只由终态接受函数落地，保证 handler 仍然是纯效应生产者。[**直接观察**：现有 handler 只返回效应，dispatcher 负责落地，见 `v15_govern.sql:1345-1516`。**推断**：统一 helper 能避免 ReturnType 与多个 ValidateReturn handler 各自复制计数/效应形状逻辑。]

## 3. `return_type` handler 行为

### 3.1 首次提示

`return_type` handler 在 `span=llm_query, phase=enter, iteration=0, next_attempt_n=1` 时返回一条持久 user message，message id 固定格式 `return_type:prompt:<ordinal>`（不参与计数），正文含 `render(spec)` 的声明（冻结示例：`[v15 return_type] The return value must match this jsonb spec: object {n: number}`）。走现有 `enter_messages → send → persistent_hook llm_messages` 路径；`next_attempt_n > 1` 不再生成（防固定 id 撞 llm_messages）。

### 3.2 return 检查

`repl_exec/complete` 且 `io.result_kind=return` 且 `io.capture=''`：调 `v15_return_spec_fault(io.return_value, self.config.spec)`；返回 SQL NULL → proceed；返回失败文字 → 调 `v15_return_validation_effect(snapshot, valid=false, message=<前缀+失败文字>)`。其他 phase proceed。错误文本描述 spec 而非 Python 类型名（v15 值域是 jsonb，无 TypeForm 等价物——D31/D32）。

## 4. `v15_govern_check_return` 的效应扩展

保持函数签名不变：

```text
v15_govern_check_return(
    p_span text,
    p_phase text,
    p_io jsonb,
    p_ret jsonb
) returns void
```

仅扩展 `exec_result` 分支：

### 4.1 仍然允许的 return→continue

条件保持现有语义：

- phase 是 `repl_exec/complete`；
- `p_io.result_kind = return`；
- `p_io.capture = ''`；
- `exec_result.result_kind = continue`；
- `exec_result.return_value = JSON null`；
- `exec_result.error = JSON null`。

### 4.2 新增允许的 return→raise

新增唯一合法的终态改写：

- phase 是 `repl_exec/complete`；
- `p_io.result_kind = return`；
- `p_io.capture = ''`；
- `exec_result.result_kind = raise`；
- `exec_result.return_value = JSON null`；
- `exec_result.error` 恰好包含 `code`、`message`；
- `error.code` 必须严格为 `V15_VALIDATION_FAILED`；
- `error.message` 必须是文本，长度不超过 1024。

其他 `return→raise` 错误码、`raise→continue`、`continue→return`、非空 capture 改写、非 null return value、缺失 error，均抛 `V15_INVALID_EFFECT/P1506`。

这使 P1540 只能通过 validation result-transform 产生，不能被任意 hook 当作通用 abort 码使用。

## 5. `v15_finish_exec` 的 return→raise 消费

保持函数签名不变：

```text
v15_finish_exec(
    p_invoke_id uuid,
    p_fence bigint,
    p_owner text
) returns void
```

现有 return→continue 分支保留不变。新增分支必须在 dispatcher 返回后、现有 return 终态分支之前执行：

1. 检查 `v_ret.exec_result.result_kind`；
2. 若为 `continue`，执行现有清除 return value、接受消息、进入 continue 分支的流程；
3. 若为 `raise`：
   - 将 `v_ret.exec_result.error.code/message` 通过 `v15_loop_error` 规范化成 `{sqlstate,code,message}`；
   - 在同一事务内把 `invokes.return_value` 清为 SQL NULL，**并同步 `v_inv.return_value := NULL`**（评审 F3：raise 分支写 `repl_history.repl_exception = v_inv.error` 读的是内存变量 loop:931-937——只改表不改变量会把历史行写成 NULL）；
   - 把规范化 error 写入 `invokes.error` **并同步 `v_inv.error := v_err`**（同一 F3）；
   - 将局部 `v_kind` 改为 `raise`；
   - 不调用 counter acceptance helper；
   - 继续复用现有 raise 终态分支。

复用现有 raise 分支意味着：

- 当前 iteration `result_kind='raise'`；
- `repl_history.repl_exception` 为 P1540 error；
- `repl_history.repl_output=''`；
- invoke `status='failed'`、`fatal=false`；
- 清 lease；
- 写 `repl_exec/exit failed`；
- 写 `invoke/exit failed`；
- 不写 `invoke/complete`；
- 删除 scratch；
- 有父 invoke 时沿现有 §4.8 子送达路径传递，父语句错误仍为 `V15_CHILD_ERROR/P1528`，子 invoke 的原始 P1540 保留。[**直接观察**：现有 raise 分支的完整落点在 `v15_loop.sql:917-953`；子送达规范在 `docs/designs/v15-jaz-dev.md:1252-1300`。]

关键约束：return→raise 不是 abort。它必须先完成 `repl_exec/complete` 的正常 dispatcher 调用，再由 finish 将候选 return 转换为现有 raise 终态；不得返回 `action='abort'`，也不得进入 §9.5 abort 归一化。

## 6. 两级检查的 v15 等价物与明确缺口

### 6.1 v15 实际保留的 backstop

`v15_finish_exec` 是机械 backstop：

- 不允许未经 `v15_govern_check_return` 认可的 exec result 进入终态；
- 不允许 `return→raise` 缺少 P1540 error；
- 统一补充 `sqlstate`；
- 统一执行历史、终态、scratch 清理和子送达。

### 6.2 明确不实现的部分

不在 `invoke/complete` 重新运行 ReturnType/ValidateReturn：

- 该 phase io 只有 `{outcome}`；
- 没有候选 return value；
- 没有 Python object identity；
- 给 phase 增加值载体会改变 §9.1 信封和所有已有 exact-key gate。

这项缺口必须写入 rev 10 的偏差记录，不得在计划或实现中暗示 v15 仍有 jaz 意义上的第二次 predicate 调用。

## 7. 计数泛化方案

### 7.1 counter key

统一使用：

```text
counter_key = <hook_key> || ':' || <ordinal>
```

示例：

```text
budget_forcing:4
return_type:4
validate_return_quality:7
```

计数仍按 `(invoke_id, counter_key)` 隔离；父 invoke、子 invoke、不同 ordinal 不共享。`hook_counters` 的 `n` 是已接受的 recoverable validation 次数，不是当前 phase 中 handler 试图拒绝的次数。[**直接观察**：`hook_counters` schema 在 `v15/schema/v15_schema.sql:398-404`；现有 budget forcing 的 counter 生命周期在 `v15/loop/v15_loop.sql:665-705`。]

### 7.2 helper 改名与否

**不改名（评审 5 裁决）**：`v15_loop_accept_forcing(p_invoke_id, p_iteration, p_stmt, p_messages)` 名字保留，仅函数体内放宽 id 解析（三段式、钉死数字段、白名单 family）。评审已证实唯一生产调用点（`v15_loop.sql:866`）、无任何 Python 引用；改名只剩 GRANT 行与规格 §4.9 提及的文档成本，两轨共识均选不改。

### 7.3 新消息 ID 解析

由只匹配：

```text
^budget_forcing:[0-9]+:[0-9]+$
```

改为解析三段：

```text
^(<hook_key>):([0-9]+):([0-9]+)$（第 2/3 段钉死数字——`return_type:prompt:<ordinal>` 等非计数 id 不进解析也不抛 P1516，坏 id 跳过；cast 溢出同理跳过）
```

实现约束：

1. `<hook_key>` 必须满足已有 hook key 文法；
2. 只接受以下计数 hook：
   - `budget_forcing`；
   - `return_type`；
   - `validate_return`；
   - 以 `validate_return_` 开头的 key；
3. `(invoke_id, ordinal)` 必须存在，且关联的 `hook_defs.hook_key` 必须等于消息中的 `<hook_key>`；
4. 同一 `p_messages` 中同一 message id 只 bump 一次；
5. upsert `hook_counters.n + 1`，并增加 counter revision；
6. 只有至少一个 counted message 被接受时，才增加该 statement revision。（原「n 必须等于库值」约束已删——见上文裁决。）

任一已识别消息的 ordinal、key 或 n 不匹配时，抛 `V15_INVALID_TRANSITION/P1523`；无法匹配的普通消息不参与计数。比旧正则更严格：阻止跨 invoke 与不存在的 (hook_key, ordinal) 的计数（评审 3c：同 invoke 跨 hook 伪造拦不住——快照把全 invoke counters 发给每个 handler；彻底堵死需 emission 归因，留作后续）。**n 相等校验（约束 4）删除**（O2/O3 共识裁决：今天 accept_forcing 不比对 n（:683-696），系统性发错 n 的 handler 会因回滚类错误永久卡死——与 F1 同族的卡死面；放弃后与既有 forcing 行为逐字节对齐）。

### 7.4 计数时序

- `repl_exec/complete` dispatcher 不 bump；
- `v15_finish_exec` 在 return→continue 被正式接受后 bump；
- return→raise 不 bump；
- finish 事务回滚时 counter 与 statement revision 一起回滚；
- 下一迭代快照读取已提交的新 n；
- `max_failures=null` 仍递增计数，只是不触发 cap；
- bigint 达到最大值时，accept helper fail-closed 为 `V15_VALUE_INVALID/P1524`，不允许溢出。

### 7.5 与现有 budget_forcing 的兼容性

`budget_forcing:<ordinal>:<n>` 的 ID、`n` 的“加一前值”、complete 不 bump、finish 后 bump 全部保持不变。[**直接观察**：`v15/govern/test_govern.py:983-1033`。]

---

# API and interface changes

## Modified internal interfaces

| 接口 | 修改 |
|---|---|
| `v15_govern_check_return(text,text,jsonb,jsonb)` | 签名不变；`exec_result` 从只允许 continue 扩为允许 validation return→raise |
| `v15_finish_exec(uuid,bigint,text)` | 签名不变；新增 return→raise 消费与 `invokes.error` 写入 |
| `v15_loop_sqlstate(text)` | 签名不变；增加 `V15_VALIDATION_FAILED -> P1540` |
| `v15_io_sqlstate(text)` | **不动**（裁决 Q4：P1540 由 loop 层产生，io 层永不见；循 `V15_RAISE→P1529` 先例） |
| `v15_govern_known_code(text)` | 签名不变；provider 文件中增加 P1540 code |
| `v15_loop_accept_forcing(...)` | 名字与签名不变；体内放宽 id 解析为泛化三段式（评审裁决：不改名） |

## New internal interfaces

| 接口 | 所有者 | 用途 |
|---|---|---|
| `v15_return_spec_valid(jsonb) returns boolean` | **govern 文件**（内核辅助，非 hook handler） | spec 形状校验（安装期 fail-fast，对应 jaz 构造期探针；optional_guard stage-9 即调用） |
| `v15_return_spec_fault(jsonb,jsonb) returns text` | **govern 文件**（同上） | 运行期匹配：通过返回 NULL，失败返回失败文字（fail-closed） |
| `v15_return_validation_effect(jsonb,boolean,text) returns jsonb` | stage 11 helper | 统一生成 continue/raise result-transform |
| `v15.return_type(jsonb) returns jsonb` | `v15_hook_return_type` | 内建 ReturnType handler |
| `v15.validate_return*` handlers | 用户注册 | 自定义 ValidateReturn；仍由 `v15_register_hook` 登记 |

## Call sites requiring updates

- `v15_finish_exec`：调用新 `v15_loop_accept_hook_messages`。
- `v15_loop.sql` 的 owner/revoke/grant 清单：无函数名变更（裁决不改名）。
- 所有现有 budget forcing gate：不得改变调用行为，只需改为验证新泛化 helper 仍支持原 ID。
- `v15/provider/test_provider.py`：增加 P1540 映射与 known-code 断言。
- 新 `v15/return_hooks/test_return_hooks.py`：覆盖新接口。
- `v15_on_phase` 的调用者不改签名、不改 oid；不新增 per-hook-key 分支。[**直接观察**：已有 dispatcher 为按 oid 泛型调用，`v15/govern.sql:1131-1180`。]

---

# Persistence and serialization

## Schema

不修改：

- `v15.hook_defs`；
- `v15.invoke_hooks`；
- `v15.hook_counters`；
- `v15.invokes`；
- `v15.iterations`；
- `v15.repl_history`；
- `v15.invoke_events`。

`max_failures`、`spec`（封闭 DSL）和 validator config 直接存入已有 `invoke_hooks.config` JSONB；counter 使用已有 `hook_counters`。这是复用现有状态模型，不引入平行 persistence path。[**直接观察**：`v15/schema/v15_schema.sql:377-404`。]

## New persisted values

- `invoke_hooks.config`：
  - `return_type`: `spec` + `max_failures`；
  - `validate_return*`: `max_failures`。
- `hook_counters.counter_key`：
  - `return_type:<ordinal>`；
  - `validate_return[_suffix]:<ordinal>`。
- `llm_messages`：
  - 首次 ReturnType 提示；
  - recoverable validation message。
- `repl_history.repl_exception` 与 `invokes.error`：
  - 只在 cap 触发的 return→raise 路径写入 `V15_VALIDATION_FAILED/P1540`。

## Migration and rollback

D1 面向 v15 的重建式 stage 加载；现有 setup 会删除并重建 `agent_v15_*` 数据库，因此不设计在线 schema migration。[**直接观察**：`docs/designs/v15-jaz-dev.md:1-45` 规定 stage setup 重建数据库；`AGENTS.md:41-73` 规定独立 stage gate。]

新代码读取旧 invoke 时：

- 没有新 hook row 时行为不变；
- 没有新 counter key 时按 0 处理；
- 旧 config 不受影响。

旧代码读取 D1 写入的数据不保证兼容：

- 旧 `v15_govern_known_code` 不认识 P1540；
- 旧 handler/dispatcher 不认识 return→raise；
- 旧 stage 不一定能解析新 `hook_defs` row。

因此 rollback 只允许在干净数据库上重新加载旧十 stage；不得在已经产生 P1540 error 或新 hook row 的同一数据库上热回滚。

---

# Error handling and edge cases

| 情况 | 行为 |
|---|---|
| `max_failures = 0` | 第一次 rejected return 直接生成 return→raise/P1540 |
| `max_failures = 2` | 第 1、2 次 return→continue；第 3 次 return→raise |
| `max_failures = null` | 永不由该 hook 升级，但每次 recoverable rejection 仍递增 counter |
| JSONB `null` return value | 按 spec 的 `null`/`any`/`anyOf` 分支匹配；SQL NULL 根值（脏数据路径）fault 固定句 `Expected <render(root)>. Got SQL NULL.`（fail-closed） |
| SQL NULL return value | 正常 `jaz."return"` 已拒绝；若脏数据进入 finish，validator fail-closed，finish 不得提交不合法 transform |
| 已打印后 return | `jaz_return` 已先以 P1515 拒绝；D1 不放宽 capture 非空条件 |
| spec 非法（坏形态/深度/键名/anyOf 长度） | hook config INSERT/UPDATE 以 P1524 拒绝（`v15_return_spec_valid`），不等模型运行一轮后才失败 |
| spec 运行期错误 | `v15_return_spec_fault` fail-closed 返回失败文字，按 validation rejection 处理 |
| validator handler 抛异常 | 沿用 optional non-baseline handler exception audit；不算 validation rejection、不 bump counter |
| validator 返回未知键 | P1516，阶段回滚 |
| validator 返回 abort/P1540 | P1540 不是保留 abort code，按现有规则归一为 P1538 |
| `budget_forcing`(continue) 与 `return_type`/validator(raise) 同相位各发 exec_result | **raise 压过 continue**（本计划裁决，防 P1535 活锁）：合成取 raise，输家 continue 的本相位持久消息被丢弃（不落地、不计数）；无 raise 时多个相等 exec_result 照旧合并。原「不同即 P1535」仅适用于两个不等且无 raise 的 continue（理论上不出现——continue 形状唯一）。该规则写进 §9.5 修订 |
| 两个 validator 返回相同 exec_result、不同 message id | 合法，两个 counter 分别在 finish 接受后递增 |
| duplicate validation message id | dispatcher 的 message 合成冲突规则或 finish 的 duplicate 检查阻止重复 bump |
| stale worker 重复 finish | 既有 fence/lease 校验阻止，counter 不会重复增加 |
| 子 invoke cap 失败 | 子保留 P1540；父绑定语句用 P1528，沿用现有 child delivery |
| `invoke/complete` handler | 只会看到 outcome；新 validation handler必须返回 proceed，不进行值校验 |
| handler 返回 `return→raise` 但 error 缺失/错误码错误 | P1506，阶段回滚，不写 invoke 终态 |
| counter overflow | P1524，整个 finish 事务回滚，不产生部分计数 |

---

# File-by-file impact

## 本计划文件（自指说明）

本文件即实现规格的执行入口（含裁决、接口、gate、文件影响与实施顺序）；不再另建 implementation-plan 文件。Run record 于各里程碑完成后追加。

## Modify: `v15/govern/v15_govern.sql`

修改性质：**扩判定 + 新增内建 handler + 新增 config 分支 + hook seed 扩展**。

具体改动：

1. `invoke_hooks_optional_guard`：
   - 新增 `return_type` ELSIF；
   - 新增 `validate_return` / `validate_return_%` ELSIF；
   - 严格校验 exact key set；
   - 校验 `max_failures`；
   - 调用 govern 内的 `v15_return_spec_valid`（封闭 DSL 形状校验）；
   - 保持未知 hook key 的现有“只要求 config object”行为，不添加总 ELSE。
2. `v15_govern_check_return`：
   - 保持签名；
   - 放行 return→raise/P1540；
   - 保持 return→continue 的全部旧限制；
   - 拒绝其他 result transform。
3. 新增 `v15.return_type(jsonb)`：
   - CREATE 必须位于 govern 文件；
   - owner 为 `v15_hook_return_type`；
   - 只在 `llm_query/enter` 首次 attempt 注入提示；
   - 在 `repl_exec/complete` 调 spec_fault helper 与 validation effect helper；
   - 其他 phase proceed。
4. `v15_on_phase`：
   - 不添加 return_type/validate_return dispatch 分支；
   - 保持泛型 oid 调用；
   - 仅允许其现有通用合成逻辑消费新的 `exec_result` 形状。
5. handler 权限：
   - `ALTER FUNCTION`、`REVOKE ALL`、`GRANT v15_owner`；
   - 按 §18 保证 CREATE、权限和 hook_defs INSERT 只在 govern 文件。
6. `hook_defs` seed：
   - 插入 `return_type`，`baseline_required=false`；
   - 不为 `validate_return*` 插入固定 seed；这些由 `v15_register_hook` 登记。

现有 handler CREATE、权限和五个 hook seed 已集中在本文件。[**直接观察**：`v15/govern/v15_govern.sql:1517-1618`。]

## Modify: `v15/govern/setup_db.py` 与 `v15/provider/setup_db.py`

**评审 F2（P0）**：`HOOK_ROLES` 是按 stage 复制的元组（govern:18-27、provider:17-），每次 setup 先删光 `v15_hook_*` 再按本 stage 清单重建。govern SQL（stage 9 加载）现在含 `ALTER FUNCTION ... OWNER TO v15_hook_return_type`——两个 setup 的 `HOOK_ROLES` 各加一行 `'v15_hook_return_type'`，否则 stage 9 加载即 role-not-exist、九道前置 gate 全红。`v15/schema/setup_db.py` 不需要（schema 阶段还没有 handler CREATE）。

## Modify: `v15/loop/v15_loop.sql`

修改性质：**尾部映射扩展 + 内部计数函数替换 + finish 分支扩展**。

具体改动：

1. `v15_loop_sqlstate` 增加 P1540 映射。
2. `v15_loop_accept_forcing` 体内放宽（不改名、参数不变）：
   - 泛化 ID 解析（三段式、数字段钉死）；
   - hook/ordinal 存在性校验与 counter upsert；
   - 保留 budget_forcing 旧行为（n 不比对）。
3. `v15_finish_exec`：
   - 在现有 exec_result 消费段增加 return→raise；
   - 将 effect error 规范化成 `v15_loop_error`；
   - 清除 `return_value` 并写 `invokes.error`；
   - 复用已有 raise 分支；
   - return→continue 继续调用 `v15_loop_accept_forcing`（体内已泛化）。
4. owner/revoke/grant 清单更新为新函数名。
5. 不修改 `v15_finish_exec` 公共签名、不新增终态分支之外的 worker API。

现有 return/raise/continue 三分支和 raise 终态实现分别位于 `v15_loop.sql:708-876`、`v15_loop.sql:917-1024`。[**直接观察**：这些区段是 D1 唯一需要扩展的 loop 落点。]

## Modify: `v15/provider/v15_provider.sql`

修改性质：**错误码映射尾追加**。

仅允许改 §18 指定的两个 `CREATE OR REPLACE`：

1. `v15_io_sqlstate(text)`：
   - 追加 `V15_VALIDATION_FAILED -> P1540`；
   - 保留所有旧映射。
2. `v15_govern_known_code(text)`：**两份函数体都改**（govern 原建体 :1-46 + provider REPLACE 体 :23-）——govern 前缀库也识别新码；provider 替换体必须是 govern 名单的超集（漏写会把新码盖掉，评审 4.7）。
3. `v15_io_sqlstate` **不动**（评审 Q4 裁决：`V15_RAISE→P1529` 先例只在 loop CASE 不在 io 映射；P1540 由 loop 层的 `v15_loop_error` 产生、经 `v15_loop_sqlstate` 解析，io 层永不见它；「三张映射」口径改为两张——loop CASE + known_code 两体）。

不得在 provider 文件中 CREATE/REPLACE `v15_on_phase`、治理 handler 或新 hook handler。现有 provider 文件承担这两张映射，且 §18 已限定其可改范围。[**直接观察**：`pg-agent/v15/provider/v15_provider.sql:1-47`、`docs/designs/v15-jaz-dev.md:2380-2428`。]

## New: `v15/return_hooks/v15_return_hooks.sql`

修改性质：**新增 stage 11 helper SQL**。

只放不属于 hook handler CREATE/注册、且不被 stage-9 前缀库引用的 helper（评审 Q2 裁决后缩小）：

- validation effect builder（`v15_return_validation_effect`——只被 hook handler 运行期调用，而 handler 在 stage 11 加载前的库中已注册但不会被安装/调用，故 builder 晚绑定安全）；

（`v15_return_spec_valid`/`v15_return_spec_fault` **移入 govern 文件**：optional_guard 的 ELSIF 分支在 stage-9 前缀库的 INSERT/UPDATE 时即要调用它们。）
- helper 的 owner、revoke、grant。

不得在该文件：

- CREATE `v15.return_type`；
- INSERT `hook_defs`；
- CREATE/REPLACE `v15_on_phase`；
- CREATE 五个既有治理 handler；
- 创建 `validate_return*` 用户 handler。

原因是 §18 只允许 govern 文件承载 optional hook handler CREATE 与 hook_defs 插入；新 stage 只承载可复用 helper 与新 gate 所需的末端 SQL。[**直接观察**：`docs/designs/v15-jaz-dev.md:2380-2428`。**推断**：helper 不属于 handler 注册工件，因此可以放在新 stage；其函数在 stage 11 完整加载后才被新 hook 使用。]

## Modify: `v15/load.py`

修改性质：**尾追加**。

- `SQL_LOAD_ORDER` 在 provider 之后追加 `v15/return_hooks/v15_return_hooks.sql`；
- `STAGE_THROUGH` 增加 `"return_hooks": 11`；
- 不调整前十项顺序；
- 保证 `files_through("govern")` 仍返回前九项，`files_through("provider")` 仍返回前十项。

## New: `v15/return_hooks/test_return_hooks.py`

修改性质：**新增 stage 11 gate**。

必须使用 FakeLLM，不开网络。覆盖：

1. 完整 load order 长度为 11、末项是 return_hooks；
2. `v15_on_phase` 仍只有一个 oid，既有 oid 未改变；
3. ReturnType config 合法/非法形状；
4. 封闭 DSL spec 形状校验 fail-fast（`v15_return_spec_valid`：坏形态/深度/键名/anyOf 长度/max_failures 全 P1524）；
5. ValidateReturn family key 与 config；
6. ReturnType 首次提示只生成一次；
7. ReturnType invalid return→continue；
8. `max_failures=0` 首次直接 return→raise/P1540；
9. `max_failures=1` 两次 recovery/cap 的累计语义；
10. `max_failures=null` 永不 cap；
11. validation message 在 complete 前不 bump counter；
12. finish 接受后 counter bump，message id 使用加一前 n；
13. `budget_forcing` 旧 counter 行为不变；
14. return→raise 写 `invokes.error`、`repl_history.repl_exception`、failed exits，不写 invoke/complete；
15. 子 invoke P1540 送达父时父语句仍为 P1528；
16. validator handler exception 仍走 audit isolation；
17. abort 中携带 P1540 时归一成 P1538；
18. `invoke/complete` 无 return value，不执行第二次 validator；
19. stale/duplicate finish 不重复 bump；
20. helper 对非法 message key/ordinal/n fail-closed。

## New or modify: stage bootstrap

### New: `v15/return_hooks/setup_db.py`

- 按现有 stage setup 模式创建 `agent_v15_return_hooks`；
- 复用现有 server、角色重建和 `load_stage` 机制；
- stage 参数必须为 `return_hooks`；
- 角色初始化中加入 `v15_hook_return_type`；
- 不创建固定 `validate_return_*` 角色，测试和部署时由注册者按实际 key 创建对应 `NOLOGIN` owner role。

如果现有 setup bootstrap 已有共享参数化函数，则新 wrapper 只调用该函数，不复制数据库重建逻辑。该点须先核对 `v15/govern/setup_db.py` 的实际导出接口；验证方式是运行 stage 11 setup 并确认十一个 SQL 文件按顺序加载。

## Modify: `v15/govern/test_govern.py`

修改性质：**回归断言增强**。

- 保留所有现有十 stage 语义；
- 在 `test_warnings_and_forcing` 或独立回归函数中增加断言：
  - budget forcing 仍用旧 ID；
  - complete phase 不 bump；
  - finish 接受后仍只 bump 一次；
- 不把 D1 的完整 ReturnType/ValidateReturn gate 放进 stage 9，因为 stage 9 前缀不含 stage 11 helper。

## Modify: `v15/provider/test_provider.py`

修改性质：**错误码表扩展回归**。

- 将 `V15_VALIDATION_FAILED/P1540` 加入 provider 映射断言；
- 增加 known-code 可识别断言；
- 保持 provider 无网络边界；
- stage 10 load-order 断言改写：`test_provider.py:206` 的 `SQL_LOAD_ORDER[-1] == provider` 必红（评审 F4）——改为 `files_through("provider")` 长度 10 且末项 provider；stage 11 gate 单独断言完整列表 11 项。

## Modify: existing README files

修改性质：**文档数字与 stage 说明更新**。

至少更新：

- `v15/README.md`；
- `v15/provider/README.md`；
- 所有仍写“十个文件”或“十道 stage”的早期 v15 stage README；
- 新增 `v15/return_hooks/README.md`，说明：
  - stage 11；
  - 只在完整合运行时验证；
  - FakeLLM gate；
  - ReturnType 封闭类型 DSL（五形态）；
  - ValidateReturn 注册式 handler；
  - 不新增 schema 表。

实现前用仓库搜索确认哪些 README 仍包含旧数字；只修改实际命中的文件，避免无关文档变更。

## Modify: `docs/designs/v15-jaz-dev.md`

修改性质：**规格 rev 10；必须与实现、gate、§14 同一提交**。

详见下一节规格修订清单。

## Modify: `docs/reviews/v15-conformance-matrix-2026-09-29.md`

修改性质：**覆盖矩阵追加 stage 11 与 D1 行**。

- load order 从十项变为十一项；
- 现有 stage 1–10 行保持；
- “五个可选 hook”改为“现有五个治理 hook + 两个 return-validation hook family”；
- 新增 stage 11 表；
- §0.12、§4.9、§9.4、§10.2、§13、§14 的相关矩阵行同步；
- 不写未经实跑的 PASS；先写待验证状态，实跑后再更新。

## Modify: `docs/reviews/v15-deviation-ledger-2026-09-29.md`

修改性质：**新增 V15-D31，并修订 optional-hook 汇总句**。

V15-D31 必须记录：

- v15 使用封闭 jsonb 类型规格 DSL（五形态），不移植 Python beartype/TypeForm，也不用 jsonpath 谓词；
- ValidateReturn 使用注册式 SQL handler，不携带 Python exception object；
- v15 只有 `repl_exec/complete` 值校验，没有 jaz `InvokeComplete` 第二次 predicate；
- recoverable rejection 通过持久 hook message + return→continue 表达；
- terminal rejection 通过 return→raise/P1540 表达；
- P1540 不是 abort retain code。

## 本计划文件

- 本文件随各里程碑追加 Run record；Background 与已裁决节不改写。

---

# Specification revision checklist: rev 10

以下修改必须在同一个规格 commit 中完成，并与受影响 gate、§14 台账同行。

## 文档头

- `rev 9` 改为 `rev 10`；
- 在修订说明中追加 D1：
  - 新增 `return_type` 与 `validate_return*`；
  - `exec_result` 支持 return→raise；
  - 新增 P1540；
  - stage 11 追加；
  - `v15_on_phase` 签名/oid 不变。

## §0.0 / stage boundary

把“合运行时只有十个文件”改为十一项；明确 stage 11 仍是前缀 gate，合运行时为 `agent_v15_return_hooks`。

## §0.12 effect algebra

补充：

- `repl_exec/complete` 的 `modify_exec_result` 允许 return→continue 与 return→raise；
- return→raise 只允许 P1540；
- validation result transform 不是 abort；
- counter 仍在 finish 接受后落地。

## §0.19 SQLSTATE

把“39 行、止于 P1539”改为：

- 40 行；
- 最后一行 P1540；
- P1541–P1548 继续保留；
- D1 不预占其他空号。

## §4.8 child delivery

补充：

- 子 invoke 因 validation cap 失败时，子保留 P1540；
- 父绑定语句仍使用 P1528；
- 不将 P1540 改写成 P1529 或 P1538。

## §4.9 `v15_finish_exec`

必须修改以下句子：

1. `exec_result` 唯一合法修改不再是 return→continue，而是：
   - return→continue；
   - return→raise/P1540。
2. return→raise 的 `return_value` 必须 JSON null；
3. finish 在同一事务内清除 `invokes.return_value`、写 `invokes.error`；
4. 随后复用 raise 终态路径；
5. 写 `repl_exec/exit failed` 与 `invoke/exit failed`；
6. 不写 `invoke/complete`；
7. 子 invoke 沿 §4.8 送达；
8. counter acceptance helper 只用于 continue，不用于 raise。
9. 事件表新增“return 被 validation 改写为 raise”一行。

## §9.1 phase io

不改变 `repl_exec/complete` 与 `invoke/complete` 的键集；增加明确说明：

- `repl_exec/complete` 是唯一 return-value validation point；
- `invoke/complete` 不含 return value，不承担第二次 predicate；
- 这是 v15 相对 jaz 的有意偏差。

## §9.2 handler 调用

补充 ValidateReturn handler 约定：

- 注册式 handler 通过 snapshot 读取 return value；
- rejection 应返回统一 validation effect，不应直接抛异常；
- 直接抛异常仍按 optional handler exception audit 处理。

## §9.3 登记

补充：

- `return_type` 是 govern 内建 optional handler；
- `validate_return` 与 `validate_return_<suffix>` 是用户登记 family；
- config 由 `invoke_hooks_optional_guard` 检查；
- handler role 仍必须为 `v15_hook_<key>`。

## §9.4 effect allowlist

把现有 exec_result 形状句改为：

- continue 形式保持现有 JSON null 约束；
- 新增 raise 形式，错误对象 exact keys 为 `code/message`；
- code 必须是 `V15_VALIDATION_FAILED`；
- 只作用于候选 return 且 capture 为空；
- 其他 transform 仍 P1506。

新增一句：P1540 若出现在 `action=abort.error.code` 中，不属于四个保留 abort code，按 §9.5 归一为 P1538。

## §9.5 synthesis

补充：

- 多个 validator 产生相同 exec_result 可合成；
- **raise 压过 continue**：同相位出现 raise 与 continue 时取 raise，输家 continue 的持久消息丢弃（不落 `llm_messages`、不计数）——否则 `budget_forcing`×`return_type` 组合会 P1535 回滚重试永久卡死（评审 F1）；
- 两个不等的 continue 仍 P1535（continue 形状唯一，实际不可达）；
- **cap 时多个 raise 取 ordinal 最小**：两个 validator 都到 cap 且 message 不同时合成最小 ordinal 的那条 raise，其余 raise 的 message 丢弃、不计数、不落 `llm_messages`，终态是 P1540 而不是 P1535；
- validation error 不参加 abort code normalization；
- terminal validation error 的 message 取 effect 内 message，经统一 1024 字符边界处理。

## §9.6 landing order

补充：

- validation recovery message 使用既有 persistent `add_messages`；
- counter 不在 dispatcher 中增加；
- finish 接受 return→continue 后调用泛化 helper；
- helper 对 budget_forcing、return_type、validate_return family 使用同一 message-id 解析。

## §10.2 optional hooks

把“五个可选 hook”改为“现有五个治理 hook 加两个 return-validation hook family”，追加：

### `return_type`

- exact config（`spec` + `max_failures`）；
- 封闭类型 DSL 五形态文法 + render/fault 冻结文字；
- 首次 prompt；
- complete-only validation；
- max_failures 语义；
- P1540 terminal branch。

### `validate_return*`

- 注册方式；
- handler 协议；
- helper 使用方式；
- 每个 invoke/ordinal 独立计数；
- exception 文本传递规则；
- 直接 handler exception 的既有 audit 行为。

### Counter

- key、message id、finish bump 时序；
- max null；
- duplicate/stale/overflow 行为。

## §13 error table

新增：

| code | SQLSTATE | 触发条件 | 分类 |
|---|---|---|---|
| `V15_VALIDATION_FAILED` | `P1540` | validation hook 在容忍次数耗尽后，将候选 return 改写为带 validation error 的 raise | 提交类，`fatal=false` |

同时修改 `V15_INVALID_EFFECT/P1506` 行，把“唯一合法 return→continue”改为“唯一合法的两种 return validation transform”。

## §14 deviation ledger section in design

新增 D31，内容与 `docs/reviews/v15-deviation-ledger-2026-09-29.md` 同步。

## §18 freeze protocol

必须增加：

- SQL_LOAD_ORDER 由十项变为十一项，新增 stage 只能追加；
- 新 stage helper 可放在 stage 11；
- `return_type` handler CREATE、ALTER/REVOKE/GRANT、hook_defs INSERT 仍只允许 govern；
- `validate_return*` 不在 govern 中预创建用户 handler；
- `v15_on_phase` 仍只允许 schema 桩与 govern `CREATE OR REPLACE`，签名/oid 不变；
- provider 文件仍只改两张 mapping；
- P1540 为本 revision 最后一行，P1541–P1548 不预占。

---

# Gate assertion surface

## New stage 11 assertions

新增 `v15/return_hooks/test_return_hooks.py` 覆盖以下行为：

### Config and registration

- 合法 ReturnType config（五种形态各一）可以安装；
- 缺 key、额外 key、坏 spec 形态、深度超 8、坏键名、anyOf 超 8、非法 max、baseline channel 都是 P1524；
- `validate_return` 与 `validate_return_<suffix>` 都能安装；
- bad owner、immutable、wrong path、table privilege 仍是 P1537；
- unknown hook key 的旧 object-only 放行行为不改变；
- `return_type` hook_defs 行的 owner/digest/`baseline_required` 正确。

### ReturnType

- 首次 `llm_query/enter` 返回一条持久 prompt；
- retry 不重复 prompt；
- matching spec 的 return 不产生 effect；
- mismatch 且未达 cap 产生 return→continue（消息含冻结失败文字）；
- mismatch 且达到 cap 产生 return→raise/P1540（error.message 同一整句）；
- spec 非法（`config spec invalid`）按 mismatch 处理；
- JSON null 按 spec 的 `null`/`any`/`anyOf` 分支匹配；
- 冻结示例四条逐字断言。

### ValidateReturn

- 自定义 handler 通过 helper 产生 continue/raise；
- 原始 message 文本进入 recoverable message；
- cap error message 不包装成 `V15_RAISE`；
- handler exception 仍写 audit，不 bump counter；
- 两个 validator 可各自计数；
- 一个 validator valid、另一个 invalid 时只有后者产生 exec_result。

### Finish and persistence

- complete phase 前 counter 为旧值；
- continue 被 finish 接受后 n 加一；
- raise 路径不加一；
- return→raise 后 `invokes.return_value` 为 SQL NULL；
- `invokes.error.code = V15_VALIDATION_FAILED`、sqlstate 为 P1540；
- history 和 exits 符合现有 raise 分支；
- 无 `invoke/complete`；
- scratch 被清理；
- 子送达保留子 P1540、父 P1528。

### Generic counter

- budget_forcing 的既有 message id 仍正确；
- validation message id 按 ordinal/n 计数；
- duplicate id 不重复 bump；
- 不属于 counted family 的 message 不 bump；
- 错 ordinal/n/key 被拒；
- 同一 invoke 不同 validator counter 隔离；
- 不同 invoke counter 隔离。

## Existing gate modifications

### `v15/govern/test_govern.py`

只增加 budget-forcing generic-counter regression；保留原有：

- hook synthesis；
- abort normalization；
- optional exception isolation；
- existing five optional hook behavior。[**直接观察**：现有断言集中在 `v15/govern/test_govern.py:746-830`、`v15/govern/test_govern.py:983-1033`。]

### `v15/provider/test_provider.py`

增加 P1540 的 mapping/known-code 断言；不得引入网络。

### Other gates

schema、namespace、config、protocol、repl、io、loop、tree 不应需要行为修改：

- schema 无新表/列；
- namespace 的 `jaz.return` / `jaz.raise` 不变；
- loop 只在已有 finish 消费点扩展；
- tree 继续复用 child delivery；
- provider 只是追加 mapping。

完整执行仍必须按 schema → namespace → config → protocol → repl → io → loop → tree → govern → provider → return_hooks 顺序运行。现有十道 gate 全部绿是 D1 合入前置条件。[**直接观察**：现有十阶段顺序见 `docs/reviews/v15-conformance-matrix-2026-09-29.md:1-35`；AGENTS gate 纪律见 `AGENTS.md:1-40`。]

---

# Risks and migration

## 1. 封闭 DSL 的语义边界

`jsonb_typeof` 对六种值的行为、`spec` 递归深度与键名规则的执行、`render`/`fault` 的稳定性必须在 PG 18.4 实例上实测（gate 冻结示例逐字断言即覆盖）；深度 >8 与 anyOf >8 的拒绝、开放对象多余键的放行、可选键缺省的放行都要有正向/反向用例；不根据其他 PostgreSQL 版本文档推断结果。

## 2. stage 9 与 stage 11 的函数依赖顺序

**已由评审 Q2 裁决消除**：`v15_return_spec_valid`/`v15_return_spec_fault` 直接放 govern 文件（optional_guard 的 ELSIF 在 stage-9 前缀库的 INSERT/UPDATE 时即要调用，晚绑定赌注不再存在）；stage 11 只承载 `v15_return_validation_effect`（仅被 hook handler 运行期调用，handler 在 stage-11 未加载的库中已注册但不会安装，晚绑定安全）。gate 仍须实测 stage-9 前缀库加载改后 govern 文件全绿（角色 F2 修复后应过）。

验证方法：

1. 先加载 stage 9，确认既有 govern gate 全绿；
2. 再加载 stage 11；
3. 在完整数据库中安装并实际调用 ReturnType；
4. 若 stage 9 CREATE 阶段即要求 helper 存在，则将 helper 的 CREATE 提前到 govern 文件，但仍保持 handler CREATE/hook_defs INSERT 只在 govern；不得改动 SQL_LOAD_ORDER 前缀顺序。

## 3. 自定义 validator 的异常语义

Python validator 的 exception object identity 无法进入 PostgreSQL。v15 只保留 handler 传入的 message 文本；直接 `RAISE` 会沿用 handler exception audit，而不是自动成为 rejection。

该偏差必须在 §14 和 gate 中明确，避免用户误以为“任意抛出的 SQL exception 都会触发 return validation”。

## 4. 计数一致性

计数由 finish 而不是 dispatcher 更新，能够保证 rollback 不留下计数，但要求 message id 与 snapshot counter 同步。需要重点测试：

- stale worker；
- 重复 finish；
- 同一 message id 重复出现；
- 同一 invoke 的多个 ordinal；
- handler 生成 n 与数据库当前 n 不一致。

## 5. 旧代码 rollback

P1540 和新 `hook_defs` row 不是旧十 stage 的兼容数据。rollback 必须销毁并重建数据库，不允许在生产数据库中只替换 SQL 文件后继续运行。

## 6. 规格与实现不同步

§18 要求规格、gate、§14 同 commit；错误码要求三张映射同 commit。任何只改 SQL、不改规格或矩阵的提交都不满足交付条件。

---

# Implementation order

1. **冻结 D1 裁决与新接口。**
   - 确认两个 hook family；
   - 确认 P1540；
   - 确认 exact config；
   - 确认 stage 11 名称 `return_hooks`；
   - 确认 return→raise 复用现有 raise 终态。
   - 这一步不提交代码。

2. **创建 stage 11 骨架。**
   - 新增 `v15/return_hooks/`；
   - 添加 stage setup、README、测试文件骨架；
   - 添加 helper SQL 文件；
   - 将 SQL 作为 `SQL_LOAD_ORDER` 第 11 项追加；
   - 添加 `STAGE_THROUGH["return_hooks"] = 11`；
   - 确认前十 stage 的 `files_through()` 输出不变。

3. **先实现错误码映射（两张口径，裁决 Q4）。**
   - 修改 loop 的 `v15_loop_sqlstate` CASE；
   - 修改 govern 的 `v15_govern_known_code` 原建体 + provider 的 REPLACE 体（超集）；
   - **`v15_io_sqlstate` 不动**；
   - 用 provider gate 验证 P1540 映射唯一且旧映射不变。
   - 这一步必须与后续 return→raise 消费逻辑一起进入最终原子提交。

4. **泛化计数接受函数。**
   - 将 `v15_loop_accept_forcing` 替换为 `v15_loop_accept_hook_messages`；
   - 更新 owner/revoke/grant；
   - 更新 `v15_finish_exec` 的 continue 调用点；
   - 先只验证 budget_forcing 行为；
   - 跑 loop、tree、govern 既有 gate，确保旧 counter 行为未变。

5. **扩展 govern effect contract。**
   - 修改 `v15_govern_check_return`；
   - 放行严格限定的 return→raise/P1540；
   - 保持所有其他非法 transform 为 P1506；
   - 不改 `v15_on_phase` 签名、oid 或泛型 dispatch 结构。

6. **实现 finish return→raise。**
   - 在 `v15_finish_exec` 的 exec_result 消费区加入新分支；
   - 写 `invokes.error`、清 `return_value`；
   - 复用现有 raise 分支；
   - 补充 P1540 的历史、exit、scratch、child delivery gate；
   - 这一步必须与第 3、4、5 步作为一个 SQL 行为闭环验证。

7. **实现 config guard 与 helper。**
   - 在 `invoke_hooks_optional_guard` 增加两个 config family 分支；
   - 在 govern 中实现 `v15_return_spec_valid`、`v15_return_spec_fault`；在 stage 11 helper 中实现 validation effect builder；
   - 保持未知 hook key 的旧行为；
   - 验证坏 config 均在安装期 P1524。

8. **实现 ReturnType 内建 handler。**
   - 在 govern 文件 CREATE；
   - 加 owner、ACL、digest、hook_defs seed；
   - 加首次 prompt；
   - 加 complete-only spec 校验（调 `v15_return_spec_fault`）；
   - 确认所有 hook CREATE 与 hook_defs INSERT 都在 govern 文件。

9. **实现 ValidateReturn 注册式协议。**
   - 不新增固定 validator handler；
   - 用测试 fixture 创建 `v15_hook_validate_return_<suffix>` role 与 handler；
   - handler 通过 helper 产生统一 result transform；
   - 验证多个 validator、独立 counter、原始 message 文本和异常隔离。

10. **完成新 stage gate。**
    - 实现 `test_return_hooks.py` 的完整断言面；
    - 运行 stage 11 gate；
    - 修复所有 load-order、权限、DSL spec、counter、终态问题；
    - 不把未实跑结果写成 PASS。

11. **同步规格与收尾文档。**
    - `v15-jaz-dev.md` 升 rev 10；
    - 同步 §0、§4.8、§4.9、§9.1–§9.6、§10.2、§13、§14、§18；
    - 更新 deviation ledger D31；
    - 更新 conformance matrix stage 11、P1540、D31 与 optional-hook 数量；
    - 更新 README；
    - 新增完整 D1 plan 文件。
    - 这一步必须与受影响 gate 和 SQL 在同一个里程碑提交中完成；这是 §18 的原子要求。

12. **执行完整验证。**
    - 串行运行十道既有 gate；
    - 运行第十一道 return_hooks gate；
    - 确认 provider 不触网；
    - 检查 `v15_on_phase` oid 未变；
    - 检查 `v15_on_phase` 只出现在 schema 桩与 govern `CREATE OR REPLACE`；
    - 检查新 hook handler CREATE 与 hook_defs INSERT 只出现在 govern；
    - 检查 `P1541–P1548` 没有被预占；
    - 检查工作区无无关文件。

13. **按 AGENTS.md 完成唯一里程碑提交。**
    - `git status`；
    - 按路径逐项 `git add`，禁止 `git add -A`、`git add .`；
    - 再次检查暂存内容；
    - 使用 `<版本>: <祈使句摘要>` 格式提交；
    - 推送到 `origin main`；
    - 不使用 `--no-verify`、force-push 或跳过 gate。[**直接观察**：`AGENTS.md:1-40`。]

---

## References

- 规格：`docs/designs/v15-jaz-dev.md` rev 9（§4.9:1263、§9.4:1915、§10.2、§13、§18）
- jaz 参考：`~/Projects/jaz/src/jaz/hooks/builtin/return_hooks.py`（ReturnType:81-342、ValidateReturn:374-522）
- 调查：`docs/investigations/v15-next-steps-survey-2026-09-29.md` §D1
- rev 9 修订先例：`v15/provider/v15_provider.sql`（映射 CREATE OR REPLACE）+ spec 文档头
- budget_forcing 全链：`v15_govern.sql:841-846`、`v15_loop.sql:665-705/853-872`、`test_govern.py:983-1033`

## Run record

### M1（2026-09-30）

步骤 1–6 已落地：stage 11 骨架、`P1540`（loop CASE + known_code 双体，`v15_io_sqlstate` 不动）、`v15_loop_accept_forcing` 不改名的计数泛化、`v15_govern_check_return` 放行 return→raise、`v15_finish_exec` 消费该分支并同步 `v_inv.return_value` / `v_inv.error`、`v15_on_phase` raise 压过 continue。规格升 rev 10。

### M2（2026-09-30）

步骤 7–10 已落地：govern 内 `v15_return_spec_valid` / `v15_return_spec_fault` / `v15_return_spec_render`，optional guard 的 `return_type` 与 `validate_return*` 分支，内建 `return_type` handler，stage 11 的 `v15_return_validation_effect`，以及 stage 11 完整 gate。`v15_hook_return_type` 与登记式 validator 角色需要 schema `v15` 的 USAGE，否则 helper 调用被异常隔离。十一道 gate 串行退出码 0。

十一道 gate 串行实跑，退出码都是 0：schema、namespace、config、protocol、repl、io、loop、tree、govern、provider、return_hooks。budget_forcing 既有断言未放宽。
