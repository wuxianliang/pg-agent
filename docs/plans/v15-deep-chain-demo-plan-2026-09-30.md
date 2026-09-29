# v15 更深链 demo（B：depth 5–8 + far-recall + 上下文告警）: Plan

## Goal

把 `demo_v15/` 驱动从写死的 depth-3 echo relay 扩展为两阶段场景：**B1 参数化深链**（hops 5–8，验证 §0.2 在长链上仍成立）；**B2 far-recall**（根持大事实清单且**不向下转发**，叶凭 root uuid 用 `jaz.prior_history` 检索并回报——论文 StuLife 的 prev_history-by-reference 模式），同时在根上以真实上下文压力触发 `context_window_warning` hook。真实模型预算沿用三次 note 迭代机制；十道 v15 gate 不受影响（demo 全在 gitignored 树内）。

## Background

### 关键实测发现（改变设计前提的两条）

1. **深链每跳上下文不增长**（探查实证）：子 invoke 的 `llm_messages` 从零开始（`worker._child_seed` 只透传 child_inputs，`worker.py:519-534`、`v15_tree.sql:41-54` 排除 input 行）——每跳 base 恒 ≈ 2598 字符（system 1855 + seed:inputs 743/744），14 份报告实测零增长。「链深→压力→告警→prior_history」的因果链**不成立**；上下文压力只在**单 invoke 多迭代**内累积（小 `max_invoke_input_length=4000` 实测推演：iteration 2 起观测塌成 MARKER、inputs 被腰斩，iteration 3 起 `V15_VALUE_INVALID` 中止——单 invoke 只能撑 2 次调用）。
2. **`jaz.prior_history` 无长度上限、绕过 base 截断**（`v15_namespace.sql:389-431`：无 LIMIT/left/char_length 检查，`llm_response`/`repl_output` 全文返回）——孙子凭 root uuid 一次 SQL 可拉回全部原文。这是 far-recall 的正确机制：**事实落在根的 repl_history 里**（根的 bind 语句 1:1 嵌入 note——note 多长 assistant 就多长，847 字符实测；或 `jaz.print` 进 `repl_output`），叶检索即可拿全文。

### hook 安装与协议覆盖（探查实证，一条路走通）

- demo 库（`load_stage(...,"provider")`）加载时**已建好**五个可选 hook 的 `hook_defs` 行（`v15_govern.sql:1578-1618`，`context_window_warning` 在 `:1614-1616`）与 handler 体（`:867-913`）；角色由 setup 的 `HOOK_ROLES` 建。
- **安装路径**：`v15_add_layer(p_layer_id, p_scope_id, p_ordinal, 'plain', NULL, NULL, <protocol jsonb>, NULL, '[{"hook_key":"context_window_warning","config":{"ratio":R}}]'::jsonb)`（`v15_config.sql:470-479`）——**同一层可同时携带 protocol 覆盖与 extra_hooks**（`kind='plain'` 无互斥限制，`:521-527`）。open 时 `v15_loop_install_hooks`（`v15_loop.sql:188-208`）按 `channel='propagating'` 安装；ordinal 4 可预测（govern 占 0–3）。元素形状闭合：`{hook_key, config}`（`v15_check_extra_hooks` 只校验元素形状；`config` 的 ratio 约束在 `invoke_hooks_optional_guard` 触发器、安装期生效——评审 C3）。
- **协议覆盖**：整对象替换，三键必给（`max_invoke_input_length`/`truncation_prefix_ratio`/`max_repl_output_length`，posint + (0,1) number，`v15_config.sql:45-97`）。**硬下限**：`render_system(True,[])=1855` 字符——`max_invoke_input_length < 1855` 必然 `V15_VALUE_INVALID` 中止（`v15_io.sql:1139-1158`，system 永不截断）。
- **告警语义**：`input_chars >= floor(折叠后 max_invoke_input_length × ratio)` 才发（`v15_govern.sql:883-892`，只在 `llm_query/send`，瞬态消息只进 request 不进 llm_messages，两套正文按 recursion_available 二选一）。

### 驱动硬编码点（探查实证，file:line）

- `task.py:30` `ROOT_HOPS=3`（唯一深度常量）；`:58` `validate_hops` 只认 3；`:23-26` CEILINGS `max_iterations:4/max_depth:4`（**真深度墙是 max_depth 不是池**）；`:84-87` `child_role` 两档死代码（depth>3 出现「role=leaf 但 hops>1」矛盾）；root_inputs 四 binding **无 root uuid**（far-recall 硬缺口；uuid 在 `drive.py:260` 于 root_inputs **之后**生成）；`FORBIDDEN` 不含 `prior_history`（可教叶检索）。
- `script.py:44-49/52-58` 固定 3/4 条剧本（hops 手写在调用点）；`:39-41` `leaf_reply` 返回字面量（far-recall 需加 prior_history 语句 + 事实返回）。
- `assert_e2e.py`：depth-3 硬编码在 `:347-351`（expected_by_depth）、`:860-892`（两个 chain 函数 3-tuple）、`:608-612`（relay_shape len==3）、`:547`（over_delegation >3 误判合法深链）、`:346`（expected_return 全链全等 `{"seal","hops":1}`——far-recall 下要重定义）；**可复用**（深度无关）：two/attempt_ok/iter_ok/event_ok/var_ok（`:439-464`）、`_mission_gap`（`:803-844` 自联结逐级 hops-1）、`_deepest_ok`（`:905-935` 由 max(depth) 驱动）、`mentions_var` 型文本匹配（`:52-54`，prior_history 证据挂点：叶 statements.sql 原文含 `jaz.prior_history`——digest 约束不可抵赖）；**`prior_history` 在分类器里是合法 plain 语句**（`split_sql.py` 白名单不含，无专属标记位，只能靠 s.sql 文本证）。
- **失败分类缺口**：叶不检索仍 `tail_ok`（纯漏报）；叶传非祖先 uuid → `V15_HISTORY_SCOPE`/P1510 不在 `pick_class`（漏到 harness_bug 或误入 dialect）；需新增 `far_recall_missed` 类。
- `test_harness.py:39` fixture 签名 `(note,seal)` 无 depth 参数；`:95` bounds 的 hops_invalid 依赖只认 3；`drive.py:224/238` run() 收 hops 不外传；`:485-486` CLI `expect_calls` 写死 3/1。
- `db.py` **零改动**（池 32 覆盖 depth 8：fake 8 次、real 上限 16 次；ceilings 经 `drive.py:104` 注入）。

### 上下文数字速查（实测）

| 量 | 值 |
|---|---|
| `render_system(True,[])` | 1855 字符（protocol 覆盖硬下限） |
| NOTE_V1 | 692 字符（inputs 里 694） |
| 每跳 seed:inputs | ≈743/744（四 binding） |
| bind 形态 assistant | 847 字符（note 1:1 嵌入） |
| leaf assistant | 69 字符 |
| observation（无 print 时） | 0 |
| 折叠阈值 | `floor(folded_max_invoke_input_length × ratio)` |

# v15 更深链 demo（B1 参数化深链 + B2 far-recall / 上下文告警）: Plan

`demo_v15/**` 仍被整目录 gitignore；本文的 file:line 来自尾委托计划与 Background 的探查，行号漂移以符号名对上号。Background 的实测是本文的已测前提。

## 1. Summary

把 gitignored 的 `demo_v15/` 从写死的 depth-3 echo relay 扩成同一驱动里的两个场景，**不改 `v15/**`，不改 `db.py`，不放宽池 32 次 / `$2`，不 force-add**。**B1 `chain`**：`--hops N`（3–8，里程碑真连为 8）证明 §0.2 的尾形式在整条链的每一环上成立；角色只有 `root` / `mid` / `leaf` 三值，多个中继都叫 `mid`。**B2 `recall`**：根的第一次回复只 `jaz.print` 事实正文，从而在挂起之前写入已结束的 `repl_history`；事实与 token **不进入**子 input；叶在唯一的 `return` 表达式里调用 `jaz.prior_history(root_id)` 抽出 `token=` 后的 16 位十六进制并回报。上下文告警只压在根的**第二次** LLM 调用上：同一 plain 层用 `v15_add_layer` 盖上 protocol（`max_invoke_input_length=9000`）和 `context_window_warning`（`ratio=0.5`，阈值 4500），使 print 那次低于阈值、委托那次落入 `[4500, 9000]`，中/叶保持在 4500 之下。`tail_ok` 仍是结构谓词；召回与告警在 fake 上是硬失败，在 real 上沿用 relay 的软失败，`DEMO_STRICT=1` 升硬。每个场景各有三次 note 预算。

## 2. Current-state analysis

### 2.1 深度 3 驱动（现状，实现时打开 gitignored 树核对）

尾委托计划已经把驱动定死，M2 于 2026-09-29 以 `NOTE_V1`、`calls_used=3`、`tail_ok relay_ok` 跑通（`docs/plans/v15-demo-tail-delegation-plan-2026-09-29.md` Run record）。本计划沿用那份驱动的进程模型，只改场景数据与断言：

- 调用链不变。`run_until_quiescent` 一次扫完整棵树；子先于恢复后的父（`v15_next_runnable` 按 `root_invoke_id, depth DESC, invoke_id`）。父在 `bind_invoke` 与下一条 `jaz.var` 之间不再 `v15_begin_llm`。这就是 §0.2，深度加长不改变这个转移。
- `db.py` 已负责幂等角色、只删己库、`load_stage(..., "provider")` 十文件、`seed_flash_profile`、插池、worker / 超管连接、`--drop-only`。池上限来自 `task.py` 的常量（32 / `2.00`）。Background 写明池 32 覆盖 depth 8 的正常路径。**本计划对 `db.py` 零改。**
- `support.open_invoke` 与 `support.py` 不改。demo 自己的 `open_root` 继续用 `FLASH_SCOPE`。
- 断言走超管直查。`v15_loop_snapshot`（`v15/loop/v15_loop.sql:547`）没有树、attempt 计数、事件、`repl_history`。`llm_attempts` / `llm_requests` 无 SELECT grant。
- 硬编码点（Background，实现时按符号重找）：`task.py` 的 `ROOT_HOPS=3`、`validate_hops` 只认 3、ceilings `max_iterations=4` / `max_depth=4`、`child_role` 的 root→mid / 否则 leaf、四 binding 无 root uuid；`drive.py` 在 `root_inputs` 之后才生成 uuid；`script.py` 的 3/4 条固定剧本与字面量 `leaf_reply`；`assert_e2e.py` 的 `expected_by_depth`、两个 3-tuple chain 函数、`relay_shape` 长度 3、`over_delegation > 3`、全链 `return_value` 等于 `{"seal","hops":1}`；`test_harness.py` fixture 签名 `(note, seal)`；`drive.py` 的 `expect_calls` 写死 3/1。
- 可原样复用的断言：`tail_ok` 里「绑定点取那条 `done` 的 `bind_invoke` 的 `(iteration, stmt_index)`、该迭代恰好两句、更早的 `continue` 允许、该迭代恰好一条 `settled`、`jaz.var` jsonb 等于子 `return_value`、suspend 的 `seq` 小于 deliver、两者之间无 `repl_exec/exit`」。`_mission_gap`（父 hops−1）与 `_deepest_ok`（由 `max(depth)` 驱动）也是深度无关的。

`max_depth=4` 是 demo ceiling，不是清单。清单单例是 `max_iterations=10, max_depth=8, max_io_attempts=3, max_statement_ms=30000`（`v15/schema/v15_schema.sql` 的 `governance_manifest` 种子行；Background 与调查 §B 均记 `max_depth=8` 为硬顶）。调用方天花板只能收紧，放宽是 `P1505`。等于清单值是 `min` 的不动点，允许。

### 2.2 每跳上下文为何不能用来触发告警

直接观察：`Worker._child_seed`（`v15/worker.py:519-531`）只把 child jsonb 的键追加为 `kind=input`，系统提示用子深度重渲染。`v15_tree_bind_context` 返回给种子逻辑的 bindings 只有父的 `scope` 与 `provenance=scope` 的 tool（`v15/tree/v15_tree.sql` 函数 `v15_tree_bind_context`）。父的 `input` 不复制。`render_system` 的 scoped 块只列入 `scope` / `var` / `tool`（`v15/protocol/render_prompt.py` 的 `_SCOPED_KINDS`），input 的值只出现在 `render_inputs` / `v15_loop_compose_inputs`（`v15/loop/v15_loop.sql` 函数 `v15_loop_compose_inputs`，按 `value::text`、名字 UTF-8 字节序）。

推论（依据上面三条）：链深不增加下一跳的 base。Background 的实测（每跳约 2598 = system 1855 + seed 743/744，14 份报告零增长）与此一致。B1 的成功标准是 §0.2 逐环成立，不是「越深越接近窗口」。告警压力只能源于**某一个 invoke 自己的** system + seed:inputs + 已写入的 `llm_messages`。

`render_system(True, [])` = 1855 是 protocol 覆盖的硬下限：`v15_begin_llm` 在 `input_chars > max_invoke_input_length` 时于 send 之前以 `V15_VALUE_INVALID` 终态返回（Background 指向 `v15/io/v15_io.sql:1139-1158`）。system 永不截断（`truncate_base` 只动 observation，然后才动第一条 input；`v15/protocol/render_prompt.py` 的 `truncate_base`）。

### 2.3 prior_history 看得见什么，以及何时才看得见

契约（直接观察）：`HISTORY_TEXT`（`v15/protocol/render_prompt.py:29-37`）写明 `jaz.prior_history(invoke_id)` 的列是 `iteration, llm_response, repl_output, repl_exception`，对自身或祖先返回，其他 id 失败。矩阵第 9 行：无关 id、后代与 NULL 为 `P1510` / `V15_HISTORY_SCOPE`；无历史行时是空表。Background 指向实现 `v15/namespace/v15_namespace.sql:389-431`：无 `LIMIT`、无 `left` / `char_length` 裁剪，`llm_response` 与 `repl_output` 全文返回。D19：截断只作用于送进模型的 base；`repl_history.repl_output` 保存全文。

时序（推论；依据是下面两条直接观察）：

- 直接观察：`v15_finish_exec` 在 `return`、`raise`、`continue` 三条终态分支里才 `INSERT` `v15.repl_history`。`continue` 分支把 `capture` 写成 `repl_output`，把该轮 assistant 写成 `llm_response`，然后插入 `iteration+1` 的 `pending` 行并把 invoke 置回 `runnable`。矩阵 §0.27 / 第 59 行：当前轮不在 `repl_history`，finish 之后才入历史。
- 直接观察：`v15_suspend_for_child` 把父迭代与 invoke 收成 `suspended`、写 `op=suspend`、建子，函数体内没有对 `repl_history` 的插入。子出生时，父的**当前**迭代仍是 suspended，不是 done。

因此叶在执行期间，经 `prior_history(root_id)` 只能读到根上**已经 finish 的更早迭代**。根若只有一轮「`bind_invoke` + `return`」，这轮 assistant（即便 1:1 嵌着 note 或事实，Background 实测 bind 形态 assistant 847 字符）要等根的 `return` 跑完才进入 `repl_history`，而那时叶早已返回。Open Question 1 里「借 bind 语句嵌入、零额外迭代」这条，和上述时序对不上。事实载体必须是根的**更早一次已结束迭代**。

`jaz.print` 把 text 按调用顺序拼进 `capture`（矩阵第 14、29 行）。只有 print、没有 return/raise 的成功迭代，`v15_finish_exec` 走 `continue`：`repl_output = capture`。这就是 B2 的载体。同一迭代里既 print 又 return，capture 非空时 `jaz."return"` 抛 `P1515`（矩阵第 11、31 行）。print 与委托必须分成两轮。

`jaz.var` 能读 `input`（矩阵第 14 行）。根可以 `jaz.print((jaz.var('facts') #>> '{}'))`，不必把事实正文贴进 SQL 字面量。`#>> '{}'` 对 jsonb 字符串取出不带 JSON 引号的文本。执行后 `repl_output` 等于事实正文；`llm_response` 只是这句短 SQL。叶读 `repl_output`，不依赖 assistant 里嵌了正文。

### 2.4 告警钩子的唯一安装路径与触发窗口

直接观察，与 Background 一致：

- `context_window_warning` 已在 `hook_defs` 中，handler 在 `v15/govern/v15_govern.sql` 函数 `context_window_warning`。非 `llm_query/send` 直接 proceed。`input_chars < floor(max_invoke_input_length * ratio)` 时 proceed；否则追加一条 `persistent=false`、`id=context_window_warning` 的 user 消息。`recursion_available` 为真时正文含两句尾委托与 `jaz.prior_history`；为假时是不含 `bind_invoke` 的叶子变体。
- `v15_on_phase` 的 send 路径把 `persistent=false` 的消息留在 request 里，不插入 `llm_messages`（同函数 send 分支里对 `persistent` 的跳过）。矩阵第 79 行已在 gate 里锁「警告不入 `llm_messages`」。demo 要证明的是真栈上这条瞬态消息确实出现在 `llm_attempts.request`。
- `input_chars` 在 `v15_begin_llm` 里按 **hook 追加之前** 的 base 做 `char_length` 求和。瞬态警告本身不计入阈值，也不计入超限判断。超限（`>` limit）发生在 enter/send 之前，invoke 以 `V15_VALUE_INVALID` 终态，钩子不会跑。能告警的窗口是闭区间 `[floor(L * ratio), L]`。
- 安装：`v15_loop_install_hooks` 先占 ordinal 0–3（四只治理钩子），再装 profile 的 `baseline_hooks`，再按层 ordinal 把 plain 层的 `extra_hooks` 装成 `channel=propagating`（`v15/loop/v15_loop.sql` 函数 `v15_loop_install_hooks`；Background 记 `:188-208`）。flash profile 的 `baseline_hooks` 是 `'[]'`（尾委托计划 §2）。因此该可选钩子在根上的 ordinal 为 4。
- 子不重读层。`v15_tree_install_child_hooks` 复制父身上 `channel=propagating` 的行（config 照抄，`state='{}'`），local 不复制。这与 D12 一致。层必须在 **open 根之前** 提交，钩子才会出现在根上并传给每一跳。
- plain 层可以同时带 protocol 对象与 `extra_hooks`（Background：`v15/config/v15_config.sql:470-479` 与 `:521-527`）。protocol 是整对象替换，三键必填：`max_invoke_input_length`、`truncation_prefix_ratio`、`max_repl_output_length`（`:45-97`：长度是正整数，ratio 是 (0,1) 的 number）。钩子 config 只允许 `ratio`、number、(0,1]——该校验在 `invoke_hooks_optional_guard` 触发器（`v15_govern.sql:495-505`，**安装期**即 `open_root` 装 hooks 时）生效，不在 `v15_add_layer` 时；配错值的失败面是 `open_failed`（评审 C3 实证）。

推论：B1 不插这一层，沿用 flash 已能跑通 depth-3 的 protocol（M2 已证明小 base 放得下）。B2 才插层。层在 scope 上，子按同一 scope 重折，于是整棵树共用收紧后的 `L`，中/叶靠「base 仍小于阈值」而不是靠「没装钩子」来保持沉默。断言要看到叶上**有**钩子行、**没有**瞬态消息。

### 2.5 分类器与失败码的缺口

`split_sql` / `classify_statement` 是方言分类权威（`v15/protocol/split_sql.py`）。`jaz.prior_history` 不在五式白名单里，含它的语句要么是 `plain`，要么嵌在 `return` / `print` / `assign` 的参数表达式里。证据只能是 `statements.sql` 原文（Background 已说明 digest 不能代替这段文本）。

`V15_HISTORY_SCOPE` / `P1510` 今天会从 `pick_class` 漏下去，落到 `dialect_reject` 或 `harness_bug`。叶不调用 `prior_history` 时结构上仍可 `tail_ok`。这两处是本计划要补的分类，不是新的 SQLSTATE。不预占错误码，不改 `v15_govern_known_code`。

## 3. Design

### 3.1 裁决（替换原 Open Questions；用户 2026-09-30 复核确认 4/6/2 三项基线：B2 真连 hops=5、note 预算每场景独立 3 次、告警 real 默认软）

| # | 裁决 |
|---|---|
| 1 事实载体 | B2 根的 **iteration 0** 恰好一句 `SELECT jaz.print((jaz.var('facts') #>> '{}'));`，finish 为 `continue`。事实正文落在该行 `repl_history.repl_output`。iteration 1 才是尾两句，child jsonb **不含** `facts`。叶读已结束的祖先历史，不读根的当前挂起轮。 |
| 2 告警位 | 只要求根的**委托那次**（iteration 1）告警。print 那次（iteration 0）的 `input_chars` 保持在阈值之下，避免冻结警告正文里的「立刻两句委托」盖过 print-first 规则。中/叶不告警。不靠把 `L` 压到 4000 去制造第三轮 `V15_VALUE_INVALID`。 |
| 3 角色与返回值 | 角色三值：`hops == N` → `root`；`hops == 1` → `leaf`；其余 → `mid`。B1 每节点 `return_value` jsonb 等于 `{"seal":"<根 seal>","hops":1}`。B2 每节点等于 `{"seal":"<根 seal>","hops":1,"token":"<16 hex>"}`（尾委托把叶的对象原样向上交）。 |
| 4 深度档 | ceilings 固定 `max_depth=8`（等于清单，不改清单行）。`--hops`：`chain` 允许 3–8，默认 **8**；`recall` 允许 5–8，默认 **5**。真连里程碑：B1 为 hops=8，B2 为 hops=5。fake 必须先绿：chain 3、5、8 与 recall 5。hops=9 在开库前拒绝。 |

补充裁决（实现不得再选）：

| # | 裁决 |
|---|---|
| 5 场景入口 | `--scenario chain\|recall`，默认 `chain`。两次独立 `drive` 进程、两座库。没有 `--scenario both`。 |
| 6 note 预算 | **每个场景各自**三次「`DEMO_MODE=real` 且至少一次 `complete`」的全链。`credentials_absent`、preflight 失败、`lease_skip`、每个场景一次纯 `provider_uncertain` 重跑、`finish_length` 的 4096 应急，都不计。某一场景用尽或未证明，仍跑另一场景。 |
| 7 池 | `calls_limit=32`、`cost_limit=2.00` 不变。不装 `budget_pool` 钩子。正常路径 B1 为 N 次，B2 为 N+1 次。 |
| 8 发布 | 本计划不 `git add -f`。发布仍由 `docs/plans/v15-publish-demo-driver-plan-2026-09-29.md` 在 B 的证据回填之后执行，并按 B 之后的 stdout / `calls_used` / 行数重测基线。 |
| 9 规格 | 不改 `render_prompt.py`、不改警告正文、不改 §6.5。模型对冻结英文的稳定误读只写进该次报告的 §18 节。 |

B1 真连取 hops=8，是因为前提 1 已说明每跳 token 不随深度增长，8 次调用相对 M2 的 $0.001257786 / 3 次仍是厘元级，而清单顶正好在 depth 8 把叶的 `recursion_available` 收成 false。B2 真连取 hops=5：召回与告警都是根/叶性质，hops=5 仍有三个 `mid`，叶在 depth 5 < 8，委托教学还在；depth-8 叶看不到教学的情况由 B1 fake/real 覆盖。

### 3.2 任务、输入与 note

两套 note 都是一段英文、无换行、仅可打印 ASCII、无 `;` `' ` `"` `\`、无子串 `jaz.bind_invoke` 与 `jaz."return"`、长度 ≤ 1500。绑定名仍是 `down`（不在保留字表，也不是 input 名；送达时插入 `kind=var`，尾委托计划评审 (a) 已闭合）。`show_in_prompt` 必须是 JSON `true`。

`role_for(hops_left, root_hops)`：

- `hops_left == root_hops` → `root`
- `hops_left == 1` → `leaf`
- 否则 → `mid`

子的 hops 为父 hops−1，子角色用同一函数。N=3 时链仍是 root → mid → leaf。N=8 时 depth 2–7 都是 `mid`。

**根 inputs（`kind=input`，`provenance=explicit`，无 `tool_id`）**

| name | chain | recall | jsonb |
|---|---|---|---|
| `hops` | N | N | number |
| `role` | `root` | `root` | string |
| `seal` | `secrets.token_hex(3)` | 同左 | string，`^[0-9a-f]{6}$` |
| `note` | `NOTE_CHAIN_V1` | `NOTE_RECALL_V1` | string |
| `root_id` | 根 uuid 文本 | 同左 | string |
| `facts` | 不出现 | 见下 | string |

uuid 在组装 inputs **之前**生成。这是对 `drive.py` 现顺序（Background：uuid 在 `root_inputs` 之后）的修正。

子对象（两个场景相同，recall 的根也一样）的键恰好是 `note, hops, role, seal, root_id`。`facts` 只存在于根的 binding。

**`NOTE_CHAIN_V1`（规范措辞；实现时 `len` 后若超过 1500，只删形容词，规则句保留）：**

```text
Copy this note to the child unchanged as the note input. The quotes around a value are syntax and are not part of the value. You are the hop given by role. hops counts the hops left, including you. seal is the leaf seal. root_id is the root invoke id. Pass seal, root_id, and this note down unchanged. When hops is greater than 1, delegate to one child bound as down and return that child result unchanged. The child input object must have note (this same text), hops (your hops minus one), role (leaf when the child hops is 1, otherwise mid), seal (unchanged), and root_id (unchanged). When hops is 1, do not delegate. Return a JSON object with keys seal and hops, using your seal and hops 1. A literal JSON return while hops is greater than 1 is wrong. No markdown. No prose.
```

**`NOTE_RECALL_V1`：**

```text
Copy this note to the child unchanged as the note input. The quotes around a value are syntax and are not part of the value. You are the hop given by role. hops counts the hops left, including you. seal is the leaf seal. root_id is the root invoke id. facts exists only on the root. Never copy facts into a child. Pass seal, root_id, and this note down unchanged. When role is root and hops is greater than 1, the first reply is only a print of the facts text and the next reply delegates. When role is mid and hops is greater than 1, delegate on the first reply and do not read ancestor history. Delegate to one child bound as down and return that child result unchanged. The child object has only note, hops set to your hops minus one, role set to leaf when the child hops is 1 and otherwise mid, seal, and root_id. When hops is 1, do not delegate. Read the finished history of root_id with jaz.prior_history and return a JSON object with keys seal, hops, and token. Use your seal, hops 1, and the 16 hex digits after token= in that history text. Do not invent the token. No markdown. No prose.
```

启动期短语自检（缺一则 `note_invalid`，退出码 2，不建库）：两份 note 都含 `down`、`root_id`、`No markdown`、`No prose`；chain 另含 `keys seal and hops`；recall 另含 `jaz.prior_history`、`facts`、`token=`。`token=` 是说明提取位置的固定前缀，不是那颗随机 token。

旧 `NOTE_V1` 的角色句（「root 的子是 mid，否则是 leaf」）退役。hops=3 回归使用 `NOTE_CHAIN_V1`，角色序列与旧任务相同。

**事实正文**

`token = secrets.token_hex(8)`（16 位小写十六进制）。正文 `token=<token> ` + `p` * `n`。字母表只有 `token=`、hex、一个空格、以及 `p`。无引号、无分号、无换行。binding 的值是这个正文的 **jsonb 字符串**。`value::text` 会带 JSON 引号；`#>> '{}'` 打出来的 `repl_output` 是不带引号的正文。泄漏检查搜的是那颗 hex token，不搜前缀 `token=`（note 里就有这个前缀，而且 note 会原样下传）。

`n` 由 §3.4 的 sizer 每次开跑前算，不写死。note 变长就重算。

**Ceilings（两场景、全部合法 hops 相同）**

`max_iterations=4`，`max_depth=8`，`max_io_attempts=2`，`max_statement_ms=30000`。

- 每跳 happy path：chain 为 1 轮；recall 的根为 2 轮（print + 尾），其余为 1 轮。4 轮仍允许一次坏 `continue` 再尾委托。
- depth 8 出生时 `recursion_available = (8 < 8)` 为 false，`governance_depth` 在 `depth = max` 时同样关闭递归。叶靠 note 的 `hops=1` 停止，不靠教学文本。hops≤7 的叶仍看得到 `TAIL_DELEGATION`。
- `p_system` 仍是 `render_system(recursion_available=True, bindings=[])`。worker 每次 attempt 会按当时的 bindings 重渲染；open 时还没有 var。
- `p_user` 与 `p_child_user` 继续是死参，传 NULL。

**期望链（chain，N=hops）**

| depth | role | hops 输入 | 回复 |
|---|---|---|---|
| 1 | root | N | 两句：`bind_invoke('down', {note, hops:N-1, role, seal, root_id})` 然后 `return(jaz.var('down'))` |
| 2 .. N-1 | mid | N-depth+1 | 同上，hops 再减 1；child hops=1 时 role=`leaf`，否则 `mid` |
| N | leaf | 1 | 一句 `return`，对象 `{"seal","hops":1}`，无子 |

**期望链（recall）** 在上表的根上插入 iteration 0 的单句 print；根的尾委托改到 iteration 1，child 对象仍是那五个键。叶的一句 `return` 用 §3.5 的标量子查询抽出 token。全程 `return_value` 都是三键对象。

### 3.3 钩子与 protocol 层（只在 recall，不进 db.py）

在 **超级用户**连接上、`seed_flash_profile` 与池行已 commit 之后、`open_root` 之前，调用已有的 `v15_add_layer`。参数顺序以 `v15/config/v15_config.sql` 里该函数的签名为准（Background 给出的调用形态是 `p_layer_id, p_scope_id, p_ordinal, 'plain', NULL, NULL, protocol, NULL, extra_hooks`）。签名若与这 9 个槽不一致，按函数定义对齐，**不改 SQL**。优先照 `v15/config/test_config.py` 里已有的调用写法，包括 digest 若由函数自己算就不要在 Python 里重算。

- `scope_id = FLASH_SCOPE`
- `layer_id` 新 uuid
- `ordinal = coalesce(max(ordinal)+1, 0)`，范围是该 scope 已有 `config_layers`
- `kind = plain`
- llm、repl、`depth_map` 均为 SQL NULL（只盖 protocol 与 hooks）
- protocol：

```text
max_invoke_input_length: 9000
truncation_prefix_ratio: 0.5
max_repl_output_length: 4500
```

长度用 JSON 整数。`0.5` 同时满足 protocol ratio 的 (0,1) 与钩子 ratio 的 (0,1]。

- extra_hooks：恰好一个元素 `{hook_key: "context_window_warning", config: {ratio: 0.5}}`。阈值 `floor(9000 * 0.5) = 4500`。

然后 commit，再在 worker 连接上 `open_root`。chain 场景不调用此函数。每跑一次都是先删库后建库，不存在「层插两次」。

超级用户没有 `EXECUTE` 时停，`failure_class=open_failed`，不新增 `GRANT`（与尾委托计划 3.9 同一纪律）。`hook_defs` 里缺少 `context_window_warning` 同样算 `open_failed`：provider 阶段加载 govern 文件时就会插入该行；缺了说明库不是十文件合运行时。

装好后的不变量（recall fixture 要查）：

- 每个树节点都有一条 `hook_key=context_window_warning`、`channel=propagating`、`config={"ratio":0.5}` 的 `invoke_hooks`。根与子的 ordinal 都是 4（baseline 0–3，profile baseline 为空，只有这一只 propagating）。
- 折叠后的 `resolved_config.protocol.max_invoke_input_length` 为 9000。
- chain 场景下整库 `hook_key=context_window_warning` 的 `invoke_hooks` 行数为 0。

### 3.4 事实长度算法

告警比较的是 worker 送进 `v15_begin_llm` 的 base 的字符数（ASCII 下 Python `len` 与 `char_length` 相同；note 自检已限制为可打印 ASCII）。system 对「无 scope/var/tool」的调用是 `render_system(True, [])`，记为 `S`。实现时重测 `S`，必须仍是 1855；不是 1855 就停（说明渲染器变了，本计划不允许跟着改 demo 去凑）。

记号：

- `fixed` = 根的 iteration 0 在事实正文长度为 0 时的 `input_chars` 估计值（system + 按 `v15_loop_compose_inputs` 拼出的 seed，facts 值为空 JSON 字符串 `""`）。
- `B = 24 + n` = 正文 `token=<16 hex> ` + `p`*n 的长度。seed 里 facts 的 `value::text` 比正文多一对 JSON 引号；这对引号算在 `fixed` 里，不算在 `B` 里。实现时用一次数据库对照：`SELECT to_jsonb(%s::text)::text` 与 `json.dumps` 对这个字母表必须一致，然后 Python 侧就用这份文本估长度。
- `print_sql` = §3.5 那句 print 的精确字符串。`obs = B`（`#>> '{}'` 打出正文）。
- `iter0 = fixed + B`
- `iter1 = iter0 + len(print_sql) + obs = fixed + len(print_sql) + 2B`

选**最小**的 `n >= 0`，使：

- `iter0 <= 4300`（print 那次低于 4500，留 200）
- `iter1 >= 4700`（委托那次高于 4500，留 200）
- `iter1 <= 8000`（低于 `L=9000`，留 1000 给定长的真模型 SQL）

无解则停，把 `fixed`、`S`、note 长度打进 stderr，退出码 2，stdout `facts_unsized`，不建库。处理是缩短 recall note，而不是先去改 `L`。`fixed` 必须 `< 3900` 才可能有解（由 `B <= 4300-fixed` 与 `2B >= 4700-fixed-len(print_sql)` 推出，`print_sql` 约百字符量级）。note 上限 1500 就是为了把 `fixed` 留在这个区间里。

另外一条开跑前估计：非根第一跳 `S_child + seed_child + 200 < 4500`。`S_child` 用 `render_system(True, [])` 作上界（`recursion_available=false` 时 system 更短）。不满足则 `note_invalid`，退出码 2。这样第三次 note 加长时，不会把中/叶推进告警带。

说明性数字（不是闸）：`fixed=3400`、`B=724`（`n=700`）时 `iter0=4124`，`print_sql≈80` 时 `iter1=4928`。实现以实测 `fixed` 为准。

跑完后的硬闸（fake recall，读 `invoke_events` 里 `span=llm_query, phase=send` 的 payload `input_chars`，该键在 `v15_begin_llm` 的 send io 里）：

- 根 iteration 0 `< 4500`
- 根的绑定迭代 `>= 4500` 且 `<= 9000`
- 每个非根 send `< 4500`
- 所有 `llm_messages.content` 都不含 `\n[v15 truncated]\n`

越界是 `harness_bug`（sizer 与 `char_length` 不一致），先修 sizer 再谈 note。real 也记录这些数字；real 上根绑定迭代低于 4500 则 `warning_missed`，非根 `>= 4500` 则 `unexpected_warning`。这两类**不消耗** note 次数：下一跑只重算 `n` 或把 note 收回 1500 以内。

真模型若把整段正文贴进 print 的 SQL，assistant 变长，`iter1` 约再加一个 `B`。在 `B<=900` 的上界附近，`iter1` 仍落在 8000 的垫子里。若仍然冲破 9000，分类走 §3.6 的 `context_overflow_*`，不放宽 `L`。

### 3.5 Fake 剧本

`OrderedScript` 的契约不变：按调用顺序吐 `content`，`cost_usd` 用 int `0`，队列空抛专用异常（fake 里算 `harness_bug`）。无 `preflight`、无 `timeout_s`。

SQL 单引号按 `'` → `''` 嵌入。本计划的 note、seal、uuid、事实正文都不含单引号，嵌入是恒等。

**Plan A（默认，先过分类器再进库）**

chain 的每一跳非叶，以及 recall 的根 iteration 1 与每个 mid，都是两句：

```text
SELECT jaz.bind_invoke('down', '<json>'::jsonb);
SELECT jaz."return"(jaz.var('down'));
```

`<json>` 的键恰好 `note, hops, role, seal, root_id`，hops 为数字，role 为 `role_for(hops-1, N)`。

chain 的叶：

```text
SELECT jaz."return"('{"seal":"<seal>","hops":1}'::jsonb);
```

recall 根 iteration 0：

```text
SELECT jaz.print((jaz.var('facts') #>> '{}'));
```

recall 的叶（一句，参数表达式在执行期读历史）：

```text
SELECT jaz."return"(jsonb_build_object(
  'seal', '<seal>',
  'hops', 1,
  'token', (
    SELECT substring(h.repl_output from 'token=([0-9a-f]{16})')
    FROM jaz.prior_history('<root-uuid>'::uuid) AS h
    WHERE h.repl_output LIKE '%token=%'
    ORDER BY h.iteration
    LIMIT 1
  )
));
```

`WHERE` 让根上更早的无 token 的 `continue`（若有）不挡住 print 那一行。happy path 下根只有 iteration 0 这一行已结束历史，过滤前后结果相同。

调用顺序就是 LLM 顺序（子在父回复之前不存在；worker 会把子树跑完再恢复父，但父的尾回复已经发出，不会再有第二次父调用）：

| 场景 | 队列 |
|---|---|
| chain | depth 1 .. N 各一条，共 N |
| recall | 根 print，根尾，depth 2 .. N，共 N+1 |
| chain 的 continue-then-tail（仅 harness） | 根先 `SELECT 1;`，再接 chain 队列，共 N+1 |

开跑前纯 Python 闸（不连库）：**先 `split_sql` 切分、再对每片 `classify_statement`**——直接喂含结尾分号的原文会全数假触发 `V15_INVOKE_FORM`（评审 E1 实证）。闸 = `for piece in split_sql(reply): assert classify_statement(piece).reject_code is None`，且 print 片 kind=print、return 片 kind=return、bind 片 kind=bind_invoke。**评审已实测 Plan A 全绿**（print 句、含标量子查询的叶 return、Plan B assign 全过——`_match_one_arg` 从不调 `_arg_has_write`，该函数只在 bind_invoke 分支用）：Plan B 降级为纯文档保险路径，不预写双份 fixture 期望，Run record 锁 Plan A（评审 §3.1 实测表抄入草稿）。（评审实证：`_match_one_arg`（`split_sql.py:429-436`）从不调 `_arg_has_write`，只有 bind_invoke 分支调——该条件句前提已被代码否定，Plan A 一次通过。）分类器本身不改。

**Plan B（仅当 Plan A 的叶语句被分类器拒绝，或 recall fixture 里该语句以 `V15_INVOKE_FORM` 失败时）**

叶变成两轮。iteration 0 是 `jaz.assign('tok', to_jsonb(<与 Plan A 相同的标量子查询>))`，finish 为 `continue`。iteration 1 是 `return(jsonb_build_object(..., 'token', jaz.var('tok') #>> '{}'))`。召回证据改为：叶的**全部**语句文本里出现 `jaz.prior_history` 与根 uuid，不要求它们落在最后一句。`calls_used` 的 recall 期望从 N+1 改为 N+2。`max_iterations=4` 仍覆盖。assign 语句若同样被 `_arg_has_write` 拒绝：停下，把分类结果写入本计划 Run record，不改 `split_sql.py`，不改用 scratch 表。那是产品缺陷里程碑（尾委托计划 §3.5 的纪律：FakeLLM 复现进 `v15/**/test_*.py`，十道 gate 绿了再单独提交）。

### 3.6 断言与失败类

超管、worker 已关闭、单线程、无第二写入者。比较 jsonb 用 SQL `jsonb =`。

**`structural_tail_ok`（两场景都硬）** 保持尾委托计划的 13 条，只把「恰好 3 个节点」从结构谓词里拿掉（那是 relay 的事）。绑定点动态取 `kind=bind_invoke AND status=done AND child_invoke_id IS NOT NULL` 的那一行的迭代，不假设它是 iteration 0。recall 的根上，这一行必须是 iteration 1；iteration 0 是 `result_kind=continue`、恰好一条 `done` 的 `print`、没有 `bind_invoke`。最深节点无子、完成迭代是 `return`。链上存在 depth 1..N 的父指针。其余（一条 settled、`max(n)` 等于它、var 相等、suspend/deliver 之间无 `repl_exec/exit`、无 running/suspended/leased/pending/runnable、无 fatal、`seq` 连续、scratch 已删）不变。

**Relay（chain 与 recall；fake 硬，real 软，`DEMO_STRICT=1` 硬）**

- 节点数恰好 N，每个有子的节点恰好一个子。
- depth d 的 input：`hops = N-d+1`；`role` 符合 `role_for`；`seal` 与根 seal 相同；`note` 与本跑 note 相同；`root_id` 文本等于根 `invoke_id`。
- chain：每节点 `return_value` 等于 `{"seal": <根 seal>, "hops": 1}`。
- recall：每节点 `return_value` 等于 `{"seal": <根 seal>, "hops": 1, "token": <token>}`。
- `over_delegation`：节点数 > N，或任一节点多于一个子。
- fake chain happy：`calls_used = N`，`cost_used = 0`。continue-then-tail：根 attempt 总数 2，绑定迭代 settled 仍为 1，`calls_used = N+1`。
- fake recall Plan A：`calls_used = N+1`。
- real：每条 settled attempt 的 `prompt_tokens >= 1` 且 `cost_usd > 0`，否则 `cost_missing`。

**`recall_ok`（仅 recall；chain 上恒为真且不查这些谓词）**

1. 根 iteration 0 的 `repl_history.repl_output` 含 `token=<token>`。
2. 叶的语句文本（Plan A：那一句；Plan B：全部语句）含 `jaz.prior_history` 与根 uuid 的规范文本。
3. mid 节点的语句文本不含 `jaz.prior_history`；根豁免自读（根读自身 uuid 的 prior_history 合法——警告正文恰好向根推销它，全禁会把循警告提示的正向行为误判失败；mid_prior_history flag 相应收窄为 mid。裁决：评审 Q1 取选项 b）。
4. 非根节点没有名为 `facts` 的 binding；它们的 `seed:inputs` 与全部 binding `value::text` 都不含那颗 hex token。
5. 根的绑定迭代上，settled attempt 的 `request.messages` 里有 `message_id = context_window_warning`（或等价的 `kind=transient_hook` 且 content 以 `[v15 context_window_warning]` 开头），正文含 `jaz.prior_history` 与 `jaz.bind_invoke`（非叶变体）。
6. `llm_messages` 里没有 `message_id = context_window_warning`。
7. 非根 attempt 的 request 里该 `message_id` 出现次数为 0。
8. §3.4 的 `input_chars` 三闸。

`relay_ok` 与 `recall_ok` 分开：值相等但叶没调用函数，是 `prior_history_absent`；值相等且历史里没有 token，是 `history_not_stored`。16 hex 猜中的概率忽略不计，仍然以 SQL 文本为证据。

**结果 dict** 在尾委托计划的形状上增加：`scenario`、`hops`、`recall_ok`、`recall_flags`、`warning_ok`。`nodes[].inputs` 增加 `root_id`；`facts` 只在根上非空。`warning` 记录根各次 send 的 `input_chars`、非根最大值、根尾是否带警告、非根警告条数。`failure_class` 在 `outcome=tail_ok` 时为空。

**`outcome=tail_ok` 的定义：** `structural_tail_ok`，并且当前模式下所有**硬**的 relay/recall 闸都过。fake 与 `DEMO_STRICT=1` 下 relay 或 recall 失败会把 outcome 收成 `fail`。real 且非 strict：结构过了就是 `tail_ok`，`relay_ok` / `recall_ok` 可以为假，退出码 0。

**stdout**

| 条件 | 行 | 码 |
|---|---|---|
| chain，tail 且 relay 都过 | `tail_ok relay_ok` | 0 |
| recall，tail、relay、recall 都过 | `tail_ok relay_ok recall_ok` | 0 |
| real 非 strict，结构过、relay 或 recall 软失败 | `tail_ok relay_soft_fail` 或 `tail_ok recall_soft_fail`（recall 软失败优先写 recall） | 0 |
| 结构失败或硬闸失败 | `fail <failure_class>` | 1 |
| real 无 key | `credentials_absent` | 2 |
| 模式 / hops / scenario / note / seal / facts_unsized | 对应单词一行 | 2 |

摘要行不打印 `return_value`、token、key。报告路径可以在第二行。

**失败类优先级**（第一个成立的获胜；flags 无论谁获胜都写全）：

1. `driver_cap`
2. `interrupted`
3. `open_failed`
4. `provider_rejected`
5. `lease_skip`
6. `budget_cap`
7. `iteration_ceiling`
8. `recursion_ceiling`
9. `provider_uncertain`
10. `child_error`
11. `bind_name_collision`
12. `print_and_return`
13. `history_scope` — 任一语句或 invoke 的 code 为 `V15_HISTORY_SCOPE` 或 sqlstate `P1510`
14. `root_id_literal_mismatch` — 语句 sql 含 `jaz.prior_history`，sqlstate 为 `22P02`，或文本里的 uuid 字面量不等于根 id
15. `context_overflow_pasted` — 根 error 为 `V15_VALUE_INVALID`，根有已结束的 continue 迭代，无子，且该 continue 的 assistant 长度 > 500
16. `context_overflow_budget` — 同形，assistant 长度 ≤ 500
17. `no_delegation`
18. `shallow_chain` — 有子但 `max(depth) < N`，或没有 depth N
19. `bad_tail_shape`
20. `markdown_fence`
21. `unquoted_return`
22. `prose_or_empty`
23. `dialect_reject` — 其余 `V15_DIALECT` / `V15_DDL` / `V15_VALUE_INVALID`
24. `mission_not_forwarded` — 子缺 `note` / `root_id`，或 hops 不是父 hops−1，或 role 不符合 `role_for`
25. `facts_leaked`
26. `far_recall_missed` — 仅 recall，且叶已在 depth N：无 `prior_history` 文本，或 token 不等，或根历史无 token
27. `warning_missed` — 仅 recall，结构已过，根绑定迭代的 request 无警告
28. `unexpected_warning` — 非根 request 出现警告，或 chain 场景出现该钩子行
29. `cost_missing`
30. `harness_bug`

`far_recall_missed` 的 flag 再分成 `prior_history_absent`、`token_mismatch`、`history_not_stored`、mid_prior_history，便于改 note，但 `failure_class` 用上面这个名字。

**note 可改的类**（计入该场景的三次）：`no_delegation`、`shallow_chain`、`over_delegation`、`mission_not_forwarded`、`bad_tail_shape`、`markdown_fence`、`unquoted_return`、`prose_or_empty`、`print_and_return`、`bind_name_collision`、`history_scope`、`root_id_literal_mismatch`、`far_recall_missed`、`facts_leaked`、`context_overflow_pasted`，以及「模型写了 DO/ALTER/事务控制」的 `dialect_reject`。

**不消耗 note 次数：** `warning_missed`、`unexpected_warning`、`context_overflow_budget`、`facts_unsized`（修 sizer / note 长度上限 / 确认 `L`）、`lease_skip`（只许加大 demo 租约，公式仍是 timeout+60，预定仍是 240）、`driver_cap`、`budget_cap`（不提高 32 / `$2`）、`provider_rejected`、`finish_length`（与尾委托计划相同：demo 库内对已有 flash profile `v15_update_profile`，`max_output_tokens=4096`，不动 `support.py`）。

冻结尾两句被分类器拒绝，或合法尾两句在真栈上拆坏租约 / Decimal / 送达：停止 note 循环，按产品缺陷另开里程碑。本计划没有那个修复步骤。

三次用尽仍是「按冻结英文的一种可读误解」：报告里写 §18 提案（哪一段冻结原文、输出类别、最小改动句、至少要重跑 `v15/protocol/test_protocol.py`）。不改渲染器，不改设计文档，不预占错误码。`tail_ok` 一旦达到就停止该场景，不为了 `relay_ok` / `recall_ok` 把剩余次数花掉。

### 3.7 驱动控制流

主线程串行。不新起 worker，不新起线程。语句取消仍用 worker 里已有的 daemon `Timer`。断言发生在 `run_until_quiescent` 返回之后。

`drive` 顶层仍然禁止 import `v15.provider.deepseek`。只在 real 且 key 已确认之后，在函数内部 import。`DeepSeekProvider(base_url="https://api.deepseek.com/v1")`，`timeout_s` 保持 120，租约 real `"240 seconds"`、fake `"30 seconds"`。key 判定、无 key 在 `get_server` 之前返回、已开打之后的异常不降级成退出码 2，均与尾委托计划相同。AGENTS 两入口已经就位，本计划不改 AGENTS。

参数顺序：先解析 CLI（`--scenario`、`--hops`、`--drop-only`），再读 `DEMO_MODE`，再查 key。非法 hops / scenario / note / seal 在建库前退出码 2。`--drop-only` 仍只删 `agent_demo_v15`。

`run(env, *, scenario, hops) -> int` 是 harness 的进程内入口。`main` 只做解析然后调用它。fake 的 `calls_used` 自检放在 `run` 里：与 §3.6 的期望不符则 `harness_bug`，禁止进入 real。real 不把 `calls_used != N` 当成失败（允许 unknown 重试，flag `extra_unknown_attempts`）。删掉写死的 `expect_calls` 3/1。

主路径在尾委托计划的 10 步上只插一件事：recall 在 open 之前 commit 层。`open_root` 的 inputs 改为 §3.2 的五键或六键。`KeyboardInterrupt` 仍是 `interrupted`、留库、退出码 1。成功删库，除非 `DEMO_KEEP_DB=1`。失败留库并打印 `--drop-only`，以及「下一道 v15 gate 的 setup 会在删完 `agent_v15_*` 之后死于 `DROP ROLE v15_owner`」。

报告（`report.py`）增加场景、hops、`recall_ok`、`recall_flags`、各次 `input_chars`、token、facts 正文长度与前 80 字符。擦除规则不变：环境里的 key 子串、`Authorization`、`reasoning`、`provider.id`、完整 messages、DSN 都不落盘。成本句继续引用 D28。

### 3.8 Harness

库名仍是 `agent_demo_v15_harness`，每个 fixture 整库重建，结束必删。不碰 `agent_v15_*`。keyless 仍是子进程：`sys.executable`，环境去掉 `DEEPSEEK_API_KEY`、`OPENAI_API_KEY`、`OPENAI_API_URI`、`OPENAI_MODEL`、`UV_ENV_FILE`，并设 `UV_NO_ENV_FILE=1`、`DEMO_MODE=real`。期望退出码 2、stdout `credentials_absent`、两库都不存在。

| # | 场景 | 期望 |
|---|---|---|
| 1 | chain hops=3 happy | `tail_ok`、`relay_ok`、`calls_used=3`、角色 root/mid/leaf、无 `context_window_warning` 行。这是旧证明的回归 |
| 2 | chain hops=5 happy | `calls_used=5`；depth 2、3、4 的 role 都是 `mid`；叶 `recursion_available=true` |
| 3 | chain hops=8 happy | `calls_used=8`；叶 depth=8 且 `recursion_available=false`；`return_value` 仍是 seal 对象 |
| 4 | chain hops=5，根先 `SELECT 1` | 根 attempt 总数 2；绑定迭代 settled=1 且该迭代不是 0；`calls_used=6` |
| 5 | recall hops=5 Plan A | `calls_used=6`；`recall_ok`；根 iteration 0 是 print/continue；绑定在 iteration 1；叶 SQL 含函数名与根 uuid；非根 seed 不含 token；警告只在根的绑定迭代；`llm_messages` 无该 id；`input_chars` 落在 §3.4 的闸内 |
| 6 | 纯函数 | hops 2 与 9、scenario `nope`、含分号的 note：退出码 2，且 `pg_database` 无 demo 库。sizer 在一个假 `fixed` 上能找到 `n`，在 `fixed=4000` 上拒绝 |

（Plan B 已被评审实测排除——若未来分类器变更导致 Plan A 失败，按 §3.5 的 Plan B 文档路径另行处理，本表不预写。）

默认无参 `DEMO_MODE=fake` 等于 chain hops=8，stdout `tail_ok relay_ok`，`calls_used=8`。这是发布计划将来要重测的基线，不再是 3。

### 3.9 真连预算

M2 的单价是推论基线：三次调用 $0.001257786，约每调用 $0.0004（`docs/plans/v15-demo-tail-delegation-plan-2026-09-29.md` Run record，直接观察该金额与 `calls_used=3`）。B1 hops=8 约 $0.004。B2 根的两次 prompt 在 4k–6k 字符，仍远低于池 `$2` 与 32 次。前提 1 推翻了调查 §B「深度 8 因上下文逐层增长而 ×3–5」的估计；那个估计留在调查正文里当历史，不在本计划里采用。

每个场景最多三次计费全链，外加该场景一次不计次的 `provider_uncertain` 整库重跑。授权的 profile 应急仍是 demo 库内 `max_output_tokens=4096`。本计划授权的「为了写计划而调用」次数是 0；实现时代码路径才允许按上表打真模型。

成功标准：

- B1：退出码 0，stdout 以 `tail_ok` 开头，hops=8。`relay_soft_fail` 算里程碑通过。
- B2：退出码 0，stdout 以 `tail_ok` 开头，hops=5。`recall_soft_fail` 算里程碑通过。
- 未证明也进入证据回填，结果栏写 `未证明` 与 `failure_class`。

### 3.10 并发、错误与边界

驱动不把 open、层插入、run、assert 放进同一个未提交事务。层插入自己 commit；`open_root` 自己 commit；断言连接在 run 之后才打开。provider 调用点的空闲事务由 worker `_assert_idle` 保证。

`OrderedScript` 耗尽、`KeyError`：fake 为 `harness_bug`。real 的 `ProviderRejected` / `ProviderUncertain` 由 worker 写入既有码，驱动只读行。

边界：空 note、note 超 1500、含禁字符或禁子串、seal 不匹配、token 不匹配 `^[0-9a-f]{16}$`、hops 越界、sizer 无解：退出码 2，不建库。recall 的根 inputs 缺 `facts` 同样在开根前拒绝。

事件序：`invoke_events` 触发器拒绝跳号与更新。崩溃留下的是最后一次已提交转移；类为 `interrupted`。下一跑是新库新 uuid 新 token。

重复或乱序的 LLM 完成：fake 队列只按调用次数前进，不按 digest。真模型一次 attempt 一次 HTTP，适配器不内部重试（D28）。与场景设计无关，驱动不新做幂等。

## 4. File-by-file impact

### 跟踪文件

| 文件 | 变更 | 为何 | 依赖 |
|---|---|---|---|
| `docs/plans/v15-deep-chain-demo-plan-2026-09-30.md` | 保留 Goal / Background / References；用 §3.1 替换 Open Questions；写入本文；跑完后补 Run record | 决策跟仓库走 | 无代码依赖 |
| `docs/reviews/v15-conformance-matrix-2026-09-29.md` | `## Demo evidence（不是 gate）` 下追加行，不进 10.x，不打 ✅，不改 2026-09-29 那一行 | 证据落点 | 至少一次 real 结束或三次用尽 |
| `docs/reviews/v15-deviation-ledger-2026-09-29.md` | `## Demo` 现有两句保留，再追加一句：更深链 demo 不新增 V15-D，不修改渲染器、切分器、worker、provider、namespace | 台账明确无新偏差 | 与矩阵同一次提交 |
| `docs/investigations/v15-next-steps-survey-2026-09-29.md` | 只在 §B 末尾加状态句，不改该节原文（其中「上下文逐层增长」已被 Background 推翻，但那是调查当时的估计） | 排期活文档能看见 B 的执行状态 | 与矩阵同一次提交 |

矩阵新行（两行，按实况填结果）：

```text
| <UTC 日期> CHAIN hops=8 | DEMO_MODE=real deepseek-flash lease 240s | tail_ok relay_ok 或 未证明 <class> | gitignore 的 demo_v15/reports/ | 链长 N=8 时每一环的绑定迭代恰好两句且下一条 return 读到子 var；该迭代恰好一条 settled；suspend 与 deliver 之间无 repl_exec/exit。十道 gate 不导入该驱动。 |
| <UTC 日期> RECALL hops=5 | 同上 | tail_ok recall_ok 或 未证明 <class> | 同上 | 根 iteration 0 的 repl_output 持有 token；子 input 无 facts；叶语句含 jaz.prior_history(根 uuid)；根绑定迭代的 request 含瞬态 context_window_warning，且该行不在 llm_messages。 |
```

调查状态句在执行前先写成「计划已写入 `docs/plans/v15-deep-chain-demo-plan-2026-09-30.md`」；M3 改成「已执行」或「未证明」，并指向 Run record。

### 明确不改

`db.py`；`v15/**`（含 `render_prompt.py`、`split_sql.py`、`worker.py`、`support.py`、全部 SQL）；`server.py`；根 `pyproject.toml`；`uv.lock`；`AGENTS.md`；`v15/README.md`；`v15/provider/README.md`；`docs/designs/v15-jaz-dev.md`；清单行；池上限；`CAP`。不新增 `SQL_LOAD_ORDER`。不安装 `budget_pool`。

### 只存在于忽略目录的文件

| 文件 | 变更 | 为何 | 依赖 |
|---|---|---|---|
| `task.py` | 删除只认 3 的 `validate_hops` 与二元 `child_role`。新增 `role_for`、`NOTE_CHAIN_V1`、`NOTE_RECALL_V1`、`NOTE_MAX=1500`、短语/字符自检、`ceilings()` 恒为 4/8/2/30000、`root_inputs(...)` 含 `root_id`、`child_payload(...)`、`build_facts(note) -> (token, body, n)`。池常量保持 32 与 `2.00` | 裁决 1–4、7 | 先读现文件，确认池常量确被 `db.py` import；若上限字面量写在 `db.py` 里，仍不改 `db.py`，因为数字不变 |
| `script.py` | `happy_chain(note, seal, hops, root_id)`、`happy_recall(... , token)`、`continue_then_tail(...)`。`leaf_reply` 不再返回与 hops 无关的单一字面量 | §3.5 | task 的 `role_for` 与 `child_payload`；分类器闸通过之后才允许被 drive 调用 |
| `assert_e2e.py` | 参数化 N 与 scenario；绑定迭代不写死 0；新增 recall / warning / `history_scope` / overflow 类；结果 dict 新字段。复用 `_mission_gap`、`_deepest_ok`、attempt/var/event 查询 | §3.6 | 静止库；`split_sql.classify_statement` |
| `drive.py` | CLI；uuid 先于 inputs；`run(...)`；recall 才 `install_recall_layer`；租约与 key 政策不动；删掉 `expect_calls` 3/1 | §3.3、§3.7 | task、script、assert、report。`v15_add_layer` 签名核对之后才写调用 |
| `report.py` | 场景、hops、recall、input_chars、token、facts 前 80 字符。擦除逻辑不动 | 人读证据 | 结果 dict |
| `test_harness.py` | §3.8 的六项。fixture 签名带 hops / scenario | 锁住参数化与召回 | drive.`run` |
| `README.md` | 默认命令等于 chain hops=8；写出 `--scenario recall --hops 5`；退出码新行；hops 合法区间；留库与 gate 的旧警告保留 | 操作者入口 | 无 |

`install_recall_layer` 放在 `drive.py`（或 `task.py` 若只拼 jsonb、由 drive 执行 SQL）。不放进 `db.py`。

## 5. Risks and migration

无新表、无新错误码、无清单迁移。回退是停掉 drive、`--drop-only`、还原本计划与 M3 的文档提交。`agent_v15_*` 与十道 gate 的合同不变。demo 源码从未入库，本地回退就是工作区文件。

| 风险 | 表现 | 处理 |
|---|---|---|
| 根的尾两句被当成事实载体 | 叶的 `prior_history` 空表，token 为 null | 以 §2.3 的 finish 时序为准；根必须先有一轮已提交的 print |
| 警告正文促使根在第一轮就委托 | 无 continue 历史，`history_not_stored` | 阈值把警告放在第二轮。仍发生则改 recall note，计入三次 |
| 警告正文促使根在第二轮「读历史直接 return」跳过委托 | 根 hops>1 时无子，`no_delegation`/`shallow_chain` | 预期失败模式（评审 E3）：警告先讲 prior_history 再讲两句委托。失败类可观测，note 改法是强调「root must delegate, history is for the leaf」
| print 与 return 写在同一轮 | `print_and_return` | note 写明第一轮只有 print |
| 模型把事实贴进 child jsonb | `facts_leaked`，即使 token 碰巧对 | 硬失败（fake / strict）。note 强调 facts 只在根上 |
| 中继也调用 `prior_history` | 结构仍可能 `tail_ok`，mid_prior_history | recall 失败。note 写明 mid 不读祖先历史 |
| 叶把引号抄进 uuid | `22P02`，`root_id_literal_mismatch` | note 已有「引号不是值的一部分」 |
| sizer 与 `char_length` 差一档 | fake 的 `input_chars` 闸失败 | `harness_bug`，修估计，不改钩子 |
| note 第三次长进告警带 | 非根 `unexpected_warning` | 长度帽 1500 + 开跑前 `nonroot+200 < 4500`；不消耗 note 次数 |
| hops=8 的模型在每跳上耗尽 4 轮 | 约 32 次调用，`budget_cap` 或 `iteration_ceiling` | 不提高池。`iteration_ceiling` 才改 note |
| 分类器拒绝 return 内的子查询 | Plan A 的纯 Python 闸失败 | Plan B。Plan B 再失败则停止并单独立项，不改 `split_sql.py` |
| 默认 fake 从 `calls_used=3` 变成 8 | 发布计划里的写作期参考值过期 | 发布计划已要求按 B 完成后的实测重做基线。README 写明新默认 |
| 留着 `agent_demo_v15` 去跑 gate | `DROP ROLE v15_owner` 失败 | 成功路径删库；失败路径打印 `--drop-only` |
| 为让模型通过去改冻结提示或警告正文 | 证据变成另一份规格 | 本计划没有这个步骤 |

## 6. Implementation order

一步失败就停。1–2 不连库。3 之前 `db.py` 的字节保持与现在一致（忽略目录里用文件校验和自查）。任何一步发现必须改 `v15/**`：停下，另开里程碑，先用 FakeLLM 写进既有 gate，不和本计划的文档提交混在一起。

1. **读盘核对（只读）。** 打开 `demo_v15/{task,script,assert_e2e,drive,test_harness,report,db,README}.py`。打开 `v15/namespace/v15_namespace.sql` 里 `jaz.prior_history`（Background 的 `:389-431`）：确认参数是 uuid、返回列与 `HISTORY_TEXT` 一致、函数体没有 `LIMIT` / 长度裁剪。打开 `v15_add_layer` 的真实签名与 `v15_check_extra_hooks`（后者只校验元素形状；ratio 约束在 `invoke_hooks_optional_guard` 触发器，§2.4 已改标）。重测 `len(render_system(recursion_available=True, bindings=[]))`。确认 `db.py` 从 `task.py` 读池常量而不是另写一套数字。任一不符：先改本计划的对应槽位（调用形态、列名），不改运行时。
2. **`task.py` 纯函数。** `role_for`、两份 note、自检、ceilings、`child_payload`、sizer。用 `python -c` 检查：N=3/5/8 的角色序列；N=2 与 N=9 拒绝；两份 note 过自检且 `len<=1500`；在一个假定 `fixed=3400` 上 sizer 有解，在 `fixed=4000` 上无解。Done when：这些检查退出码 0，且尚未建库。
3. **`script.py` + 分类器闸。** 生成 chain N=8、recall N=5、continue-then-tail N=5 的队列，长度分别为 8、6、6。闸先 `split_sql` 再逐片 `classify_statement`（§3.5，E1），拒绝码为空且 kind 符合。**评审已实测全绿——Plan A 锁定**，Run record 草稿抄入评审 §3.1 实测表；Plan B 不再预写双份期望。Done when：闸退出码 0。此步与第 4 步原子。
4. **`assert_e2e.py`、`drive.py`、`report.py` 的 chain。** 先做 hops=3，再 hops=5，再 hops=8。命令形态：

```text
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL \
  UV_NO_ENV_FILE=1 DEMO_MODE=fake \
  uv run python demo_v15/drive.py --scenario chain --hops 8
```

hops=3 与 5 把 `--hops` 换成对应值。Done when：三次都退出码 0，`calls_used` 分别为 3、5、8，hops=8 的叶 `recursion_available=false`，报告在 `demo_v15/reports/`，默认删库。`calls_used` 不对则按尾委托计划 3.9 停（禁止为凑数去装 `budget_pool`）。
5. **recall fake。** `--scenario recall --hops 5`。Done when：退出码 0，stdout `tail_ok relay_ok recall_ok`，`calls_used` 为 6（Plan B 则为 7），§3.4 的 chars 闸与「警告不在 `llm_messages`」成立，非根输入不含 token。
6. **Harness 全集**（§3.8 含 keyless 与非法 hops）。Done when：`uv run python demo_v15/test_harness.py` 在剥掉四枚凭据与 `UV_NO_ENV_FILE=1` 下退出码 0，harness 库已删。
7. **B1 真连。** 每次改 chain note 之前重跑 hops=3 与 hops=8 的 fake。最多三次计费全链，hops=8。成功是 stdout 以 `tail_ok` 开头。`relay_soft_fail` 通过。不改冻结提示。
8. **B2 真连。** 与 B1 的三次分开计数。每次改 recall note 之前重跑 recall fake，并确认 sizer 仍把 print 那次放在 4500 之下。hops=5。`recall_soft_fail` 通过。`warning_missed` 只重算垫子，不计入三次。
9. **证据提交。** 按实况填 Run record、矩阵两行、台账一句、调查 §B 状态句。`git add` 只这四份文档。`git status` 确认没有 `demo_v15/`、没有报告、没有 `.env`。提交说明：`v15: record the deeper-chain demo evidence`。未证明就写未证明。不重跑十道 gate（无 `v15` 的 py/sql 变化）。不把报告正文抄进矩阵。

计划文本自身的提交在实现开始前落地，说明：`v15: plan the deeper-chain demo`。`git add` 只本文件。此时 Run record 可以仍是空模板。

### 执行索引

| 工作项 | Done when | 主要文件 | 依赖 |
|---|---|---|---|
| 读盘核对 | prior_history 无长度上限、`v15_add_layer` 槽位已对齐、`S=1855`、`db.py` 零改 | namespace、config、`render_prompt.py`、`db.py` | 无 |
| task 纯函数 | 角色、note、sizer 的 `python -c` 为 0 | `task.py` | 核对 |
| 分类器闸 | Plan A 或已记录的 Plan B 拒绝码皆空 | `script.py` | task |
| chain fake 3/5/8 | 退出码 0，`calls_used` 3/5/8 | drive、assert、report | 分类器闸 |
| recall fake 5 | `recall_ok`，警告只在根的第二轮 | 同上 + 层插入 | chain fake |
| harness + keyless | 退出码 0；无 key 为 2 且未建库 | `test_harness.py` | 两个 fake |
| B1 real hops=8 | stdout 以 `tail_ok` 开头，或三次用尽 | 环境 key | harness |
| B2 real hops=5 | stdout 以 `tail_ok` 开头，或三次用尽 | 环境 key | B1 的 fake 仍绿；预算独立 |
| 证据回填 | 四份文档提交，无 demo 树混入 | 矩阵、台账、调查、本文件 | real 结束，无论成败 |

### Run record

- 日期：2026-09-29（UTC 实跑；回填 2026-09-30）
- 父提交：`286e02e`
- `render_system(True, [])` 长度：1855（计划 Background；评审 `docs/reviews/v15-deep-chain-demo-plan-critique-2026-09-30.md` §3.2 记已实测。本回填未重测）
- `prior_history` 签名与「无 LIMIT」：已核对，无偏差。`jaz_prior_history(ancestor uuid)` 返回 `iteration, llm_response, repl_output, repl_exception`；函数体无 `LIMIT` / `left` / `char_length`。B2 叶调用读到历史。
- `v15_add_layer` 实参顺序：已按函数定义对齐（`p_layer_id, p_scope_id, p_ordinal, p_kind, p_llm, p_repl, p_protocol, p_depth_map, p_extra_hooks`）。B2 `hook_count=5`，`protocol_limit=9000`。
- Plan A（评审实测锁定；Plan B 为文档保险未用）：锁定，未用 Plan B。实测表：`docs/reviews/v15-deep-chain-demo-plan-critique-2026-09-30.md` §3.1（先 `split_sql` 再 `classify_statement`；Plan A 叶 return 内嵌 `jaz.prior_history` 子查询 kind=`return`、reject 空）。fake recall `calls_used=6`（N+1），不是 Plan B 的 7。
- sizer：`fixed=3061`、`n=774`、`B=797`、预测 iter0=3858 / iter1=4701。fake recall 实测 3858/4701，非根最大 3051。B2 real 根 sends 3858/4697，非根最大 3142。
- fake chain hops=3/5/8：退出码 0，`calls_used` 3/5/8，`tail_ok relay_ok`（NOTE_CHAIN_V1）
- fake recall hops=5：退出码 0，`calls_used=6`，根两次 `input_chars` 3858/4701，非根最大 3051，`recall_ok`，警告只在根绑定迭代
- harness：退出码 0（六 fixture）
- keyless：退出码 2，当时无 demo 库
- B1 real：NOTE_CHAIN_V1，修订 0，预算 0/3，stdout `tail_ok relay_ok`，退出码 0，`failure_class` 无，`calls_used=8`，成本 $0.006382194。八节点；七条 §0.2 边全绿（bind/return 两句、settled=1、max_n=1、var_eq、suspend<deliver 且 repl_exits=0）。depth-8 叶 `recursion_available=false` 完成。每跳 input_chars 2732/2731。报告 `demo_v15/reports/e2e_report-20260929T185451Z.md`（gitignore，不入库）。
- B2 real：NOTE_RECALL_V1，修订 0，预算 0/3（`tail_ok` 即停），stdout `tail_ok recall_soft_fail`，退出码 0，`failure_class` 无，`calls_used=7`（= N+1 的 6 次 + 叶先做了一次只查历史的 `SELECT * FROM jaz.prior_history(...)` 探针迭代、finish 为 continue——报告助手预览第一条即它；非 unknown 重试）。成本 $0.005388552。`recall_ok` 为假：仅 `token_mismatch`——叶调用 `jaz.prior_history(根 uuid)` 读到历史（助手预览），提取子查询搜了 `llm_response`，token 在 `repl_output`（回报 `token=null`，上交后 `relay_flags=relay_value_mismatch`；结构 13 条全真，四条委托边全绿，`facts` 零泄漏）。警告只在根的绑定迭代（`warning_ok=True`，根 sends 3858/4697，非根最大 3142，非根告警 0）。报告 `demo_v15/reports/e2e_report-20260929T185538Z.md`（gitignore，不入库）。
- `DEMO_MODE=real` 有 key 的额外调用：无（无应急 4096，无 uncertain 重跑；不计入三次）。B1+B2 合计 $0.011770746，调用 8+7。
- 十道 gate：未跑（无 `v15` py/sql 变化）
- 发布：未做。交给 `v15-publish-demo-driver-plan`，基线不再是 `calls_used=3`

### 实现期核对

| 事实 | 做法 |
|---|---|
| `jaz.prior_history` 列名与祖先谓词 | 读 `v15/namespace/v15_namespace.sql`。与 `HISTORY_TEXT` 不一致则停 |
| `value::text` 与 `json.dumps` | harness 库里对事实正文跑一次 `to_jsonb(text)::text` |
| request 保留瞬态消息 | 第一只 recall fake 读 `llm_attempts.request`。没有该键则 `warning_missed` 的数据源改到 send 事件 payload 里能证明「钩子返回了消息」的字段，并在 Run record 写明；不改 `v15_settle_llm` |
| 超管可 `EXECUTE v15_add_layer` | 第一只 recall 库上直接做。失败则停，不 `GRANT` |
| 叶 `recursion_available` | hops=8 为 false，hops=5 为 true，读 `invokes.recursion_available` |
| `db.py` 未被修改 | 实现结束时该文件校验和与开工时相同 |

## References

- 前置计划：`docs/plans/v15-demo-tail-delegation-plan-2026-09-29.md`（M0–M3 已执行，驱动现状的权威描述）
- 发布计划（B 完成后执行）：`docs/plans/v15-publish-demo-driver-plan-2026-09-29.md`
- 论文 §4.1（tail-recursive delegation / far recall / prev_history by reference）
- 调查报告 §B：`docs/investigations/v15-next-steps-survey-2026-09-29.md`
- 规格：`docs/designs/v15-jaz-dev.md` §0.2/§0.17/§4.7/§10.2（context_window_warning 两套正文）
