# v15 更深链 demo 计划评审：基线保留度 + 代码核对（2026-09-30）

对象：`docs/plans/v15-deep-chain-demo-plan-2026-09-30.md`（下称「计划」）。
基线：`prompt-exports/oracle-plan-2026-09-30-010755-b-deeper-chain-demo-5e80.md` 第一条 oracle lane（grok `b-deeper-chain-demo-plan-70FD8C`，导出文件 L157–L708，下称「基线」）。其余两条 lane 仅作上下文。
用户已拍板三项（B2 真连 hops=5、每场景独立 3 次 note、告警 real 默认软）视为既定基线，不在评审范围。

方法：逐行 diff 计划与基线；对计划/基线引用的每个承重 file:line 打开实际代码核对；对四条可运行论断（分类器 ×2、sizer、事件可读性）用真实代码实测（`uv run python`，`v15.protocol.split_sql` 与 `v15.protocol.render_prompt`）。行号漂移以符号对上号（计划自身约定）。

---

## 1. 基线保留度（覆盖项 1）

**结论：计划是基线的逐字保留，没有丢失任何实现承重内容。**

- 逐行比对：基线全部非空行中，仅两行未在计划中出现——基线开头的过渡句（「本文补全 … 实现第一步是打开那些文件，用符号名对上号」）与 §3.1 标题原样。前者被计划开头的等价短句 + §6 步骤 1（读盘核对）完全覆盖；后者是**追加**了用户三项拍板注记，不是删改。
- 裁决表 1–9、note 全文、sizer 全部不等式、Plan A/B 全部 SQL 样本、30 类失败优先级、六项 harness 期望、Run record 模板、实现期核对表——全部逐字在档。
- 因此第 1 类问题（丢失/弱化/泛化）：**无发现**。以下问题全部属于「两边共有」或「引用偏差」。

## 2. file:line 与引用核对（覆盖项 2）

### 2.1 核对为准确的引用（抽样全部命中，漂移 ≤2 行）

| 计划引用 | 实测 | 判定 |
|---|---|---|
| `task.py:30` ROOT_HOPS=3；`:23-26` CEILINGS 4/4/2/30000；`:58` validate_hops 只认 3；`:84-87` child_role 两档 | :30 / :22-27（条目 :23-26）/ :57 / :84 | ✓（漂移 ≤1） |
| 四 binding 无 root uuid；FORBIDDEN 无 `prior_history`；`child_payload` 现为 4 键 | task.py:72-82 / :19 / :90-91 | ✓ |
| `script.py:44-49/52-58` 固定 3/4 条剧本；`:39-41` leaf_reply 字面量 | :44-49 / :52-58 / :39-41 | ✓ 精确 |
| `drive.py:260` uuid 在 root_inputs 之后 | 调用 :239，uuid :262 | ✓（漂移 2） |
| `drive.py:485-486` expect_calls 写死 3/1 | :484-485 `expect_calls=3` / `expect_root=1`（fake 分支） | ✓（"3/1"=calls/root，属实） |
| `drive.py:224/238` run() 收 hops 不外传；`:104` ceilings 注入 | run 签名 :217-228（hops 缺省 ROOT_HOPS，仅校验不转发）；open 调用 :98-112 | ✓ |
| `test_harness.py:39` fixture；`:95` bounds hops_invalid | :39 / :91（用例 :97） | ✓（`:39` 精确；`(note,seal)` 实指 replies_fn 形参，措辞略糊但实质对） |
| `assert_e2e.py` ：`:346` expected_return、`:347-351` expected_by_depth、`:546-547` over_delegation>3、`:608-612` relay_shape len==3、`:860-892` 两个 depth==3 链函数（:871/:891）、`:803-844` _mission_gap（:804）、`:905-935` _deepest_ok（:904）、`:52-54` mentions_var（:50） | 全部命中 | ✓（漂移 ≤2） |
| `v15_namespace.sql:389-431` jaz.prior_history：uuid 单参、四列、无 LIMIT/无长度裁剪、祖先游走 P1510、只读 repl_history | :389-428 | ✓（漂移 3） |
| `v15_config.sql:470-479` v15_add_layer 9 参 | :470-480，签名 `(layer_id, scope_id, ordinal, kind, llm, repl, protocol, depth_map, extra_hooks)`；计划 §3.3 的 9 槽调用形态（protocol 第 7 槽、extra_hooks 第 9 槽）与签名逐槽对上 | ✓ |
| `:45-97` protocol 三键校验 | v15_check_component protocol 分支：三键白名单 + posint/(0,1) | ✓ |
| `v15_govern.sql:867-913` handler、`:883-892` 阈值、`:1578-1618`/`:1614-1616` hook_defs（含 context_window_warning） | :867-912 / 阈值 :891 / VALUES 块 :1577-1616 | ✓ |
| `v15_loop.sql:547` v15_loop_snapshot 无树/attempt 计数/事件/repl_history | :547 精确；快照确含 statements/messages/bindings，不含上述四者 | ✓ 精确 |
| `v15_loop.sql:188-208` install_hooks 装载顺序 | extra_hooks 循环 :194-212，baseline 先装、plain 层按 ordinal 后装、`channel='propagating'` | ✓ |
| `worker.py:519-534` _child_seed 只透传 child_inputs | :519-536；子 system 按子深度重渲染，父 input 不复制；`_SCOPED_KINDS={scope,var,tool}`（render_prompt.py:49）不含 input | ✓ |
| `v15_tree.sql:41-54` bind_context 排除 input 行 | WHERE `kind='scope' OR (kind='tool' AND provenance='scope')` 在 :40-57 | ✓ |
| `v15_io.sql:1139-1158` 超限在 send 之前终态 | char_length 累计至 :1138，`IF v_chars > v_limit` 终态在 :1155-1162，enter/send 事件在 :1189 之后——钩子确实不会跑 | ✓（同函数，漂移个位数） |
| flash profile baseline_hooks='[]'（ordinal 4 的前提） | support.py:23 传 `'[]'::jsonb` | ✓ |
| `v15_next_runnable` 按 `root_invoke_id, depth DESC, invoke_id` | v15_schema.sql:905 逐字 | ✓ |

### 2.2 引用偏差（唯一一处实质错位）

**C3｜ratio 配置校验的位置被归错函数。** 计划 Background 与 §2.4 称「`v15_check_extra_hooks`，config 只允许 ratio 键、number、(0,1]」。实测（v15_config.sql:219-277）：`v15_check_extra_hooks` 只校验元素形状（`{hook_key, config}` 两键、hook_key 为串且存在于 `hook_defs`）——**不含任何 ratio 约束**。ratio-only / number / (0,1] 的校验在 `invoke_hooks_optional_guard` 触发器（v15_govern.sql:495-505 的 `context_window_warning` 分支），在 **hook 安装时**（即根 `open_root` 跑 `v15_loop_install_hooks` 时）才执行，不在 `v15_add_layer` 时。后果：约束本身存在且 `ratio=0.5` 合法，demo 不会踩；但若配错值，失败面是 `open_failed`（安装期 P1524）而非层插入期——§3.3 的排障路径与 §6 步骤 1 的「打开 v15_check_extra_hooks」核对项按现文会查错地方。建议把该句的落点改标为 govern 触发器（或两处都提）。

其余未发现错误引用。

## 3. 四条专项论断的实测（覆盖项 2/3 的核心）

### 3.1 (d) 分类器实测：Plan A 全部通过——「Plan A/B 赌局」已解，落在 Plan A

用真实 `v15.protocol.split_sql`（先 `split_sql` 再逐片 `classify_statement`，与 worker 执行路径一致）实测计划 §3.5 的全部样本：

| 语句 | kind | reject |
|---|---|---|
| `SELECT jaz.bind_invoke('down', '<5键json>'::jsonb)` | bind_invoke | 空 |
| `SELECT jaz."return"(jaz.var('down'))` | return | 空 |
| chain 叶 `SELECT jaz."return"('{"seal":..,"hops":1}'::jsonb)` | return | 空 |
| **`SELECT jaz.print((jaz.var('facts') #>> '{}'))`** | **print** | **空** |
| **recall 叶 Plan A（return 内嵌标量子查询 + `jaz.prior_history('<uuid>'::uuid)` + LIKE/ORDER/LIMIT）** | **return** | **空** |
| Plan B `jaz.assign('tok', to_jsonb(<同子查询>))` | assign | 空 |
| Plan B `return(... jaz.var('tok') #>> '{}')` | return | 空 |
| `SELECT 1`（fixture 4 前置） | plain | 空 |

代码解释：`_match_one_arg`（split_sql.py:429-436）对 return/print 只查「非空、无深度 0 逗号、非纯括号」，**从不调用 `_arg_has_write`**——该函数只在 `_match_two_arg` 的 bind_invoke 分支（:459）被调用。计划 §3.5 的条件句「`_match_one_arg` 若对 return/print 的参数调用了 `_arg_has_write` … 进入 Plan B」的前提**被代码否定**：任意单参表达式（含嵌套括号、`#>>`、标量子查询、字符串字面量里的正则）都被接受，只要外层调用括号配平到句尾（`_call_end` 匹配最外层，多一层包裹括号无碍，实测 print 句即证）。

**对执行的影响**：§6 步骤 3 的分类器闸预期一次通过；Plan B 成为（便宜的）死路径保险；fixture 5 的 Plan-B 期望分支与 Run record 的「Plan A 或 Plan B」可提前锁为 Plan A。这不是计划缺陷，但计划把一个已可判定的问题留成待验——建议在实现前把本表写进 Run record 草稿，省掉「就地换 Plan B 复测」的分支准备。

### 3.2 (a) §3.4 sizer 数学：成立，且 B 上界有显式论证

质疑点：`truncate_base`（render_prompt.py:134-163）第一步就把**所有 observation 截到 `max_repl_output_length`**（recall 层为 4500），若 B>4500，`obs=B` 失真、`iter1=fixed+len(print_sql)+2B` 不再成立。

实测/推演结论：**该情形在 sizer 自身约束下不可达。**

- 解必须满足 `iter0 = fixed + B ≤ 4300`，而 `fixed ≥ S + 最小 seed = 1855 + 877 = 2732`（1855 已实测，见 §3.5；877 为四/五键空 facts seed 的最小构成，note 至少含必带短语），故任何可行解 `B ≤ 4300 − fixed ≤ 1568 < 4500`——observation 永不触发截断，`obs = B` 精确。
- `obs = B` 还依赖 observation 内容无包装：`jaz_print`（namespace:161-184）是 `capture := capture || line` 裸拼接，`v15_finish_exec` continue 分支（loop:979-1001）把 capture 原文写入 `iter:N:observation`——无前缀无分隔符，实测成立。
- input 侧截断同样不可达：`iter1 ≤ 8000 < L=9000`，truncate_base 第三段（削第一条 input）不触发。
- 用计划规范 note 实测：`len(NOTE_CHAIN_V1)=777`、`len(NOTE_RECALL_V1)=1096`（均 ≤1500，无禁字符/禁子串，短语自检项全在）；recall 侧 `fixed=3061`，B 可行窗 `[780,1239]`；计划示例 `fixed=3400, B=724 → iter0=4124, iter1≈4928` 算术复核无误。计划「fixed 必须 <3900 才可能有解」是按 `print_sql≈0` 的保守界（真界为 `3900+len(print_sql)`，实测 print_sql=45 字符），方向保守、无害。
- fixture 6 的两个 sizer 用例（fixed=3400 有解 / fixed=4000 拒绝）复核：3400 → B∈[610,900] 有解；4000 → B∈[310,300] 空，拒绝。一致。

一处无害的 footnote：`v15_begin_llm` 的重试路径（io:1065）对**已存 request**（含追加过的钩子消息）重算 input_chars——happy path 无重试，不影响 sizer；仅当 recall 真跑中出现 attempt 重试时，该次事件的 input_chars 不再等于「仅 base」，读数时须知。

### 3.3 (b) `invoke_events` send payload 携带 `input_chars` 且事后可读：成立

`v15_begin_llm` 在跑 send 钩子**之前**就写事件（io:1223-1229）：`v15_repl_event(invoke, 'span','llm_query','send', NULL, v_send_io, fence)`，`v_send_io` 按契约必含 `input_chars`（govern 的 `v15_govern_io_keys('llm_query','send')` 强制五键，缺一 P1516）；`v15_repl_event`（repl:162-193）把 payload 原样 INSERT 进 `invoke_events`。无论钩子结果如何，事后可查。计划 §3.4 的硬闸数据源成立。

附带证实：瞬态警告确实落进 `llm_attempts.request`——`v_final = base + enter_msgs + send_msgs`（io:1240-1243）整包写入 request，`v15_io_append_hook_messages`（io:281-348）给瞬态消息打 `kind='transient_hook'`、`message_id='context_window_warning'`。recall_ok #5 的主数据源存在，且其两个备选判别式（message_id / kind+前缀）**同时**在档；计划「实现期核对」里「没有该键则改数据源到 send 事件」的兜底是死路径（可留作保险，不必执行）。

### 3.4 (c) §2.3 时序论断：逐条与代码一致

- `v15_finish_exec` 只在 `return`/`raise`/`continue` 三个终态分支 INSERT `repl_history`（loop:882、:924、:979）；continue 分支同时把该轮 assistant 写为 `llm_response`、capture 写为 `repl_output`，并插 `iteration+1` 的 pending 行。
- `v15_suspend_for_child`（tree:328-513）通体**无任何 repl_history 插入**——挂起轮对 `prior_history` 不可见。
- `jaz.prior_history` 只 SELECT `repl_history WHERE invoke_id=ancestor ORDER BY iteration`——可见集=祖先已 finish 的迭代。B2 时序成立：根 iteration 0（print/continue）先 finish，iteration 1 的 bind 才建子；叶执行时根的 iteration 0 已在历史、iteration 1 挂起不可见。裁决 1 的载体设计与代码行为严丝合缝。
- 同向证实：`jaz_return` 在 capture 非空时抛 `V15_PRINT_AND_RETURN`（P1515，namespace:284+）——print 与 return 必须分轮，与裁决 1 一致。

### 3.5 其余承重数字实测

- `len(render_system(recursion_available=True, bindings=[])) = 1855`（实测，计划硬下限成立）。
- 折叠语义：`v15_resolve_config`（config:544-658）对 plain 层 `protocol` 整对象替换（`acc_protocol := v15_check_component('protocol', layer.protocol)`），子经 `v15_resolve_child_config` 按同 scope 重折——「整树共用 L=9000」与 fixture 不变量「resolved_config.protocol.max_invoke_input_length=9000」成立。flash 缺省 protocol 实为 `{100000, 0.7, 4000}`（support.py:12-16）——chain 场景不插层时 L=100000，加长 note 不会顶到限；Background 的「4000」是探查期的实验覆盖值，计划行文已交代，非缺陷。
- `v15_loop_compose_inputs`：`'inputs:
' || string_agg(name||': '||value::text, E'
' ORDER BY convert_to(name,'UTF8'))`——facts 的 `value::text` 带 JSON 引号、引号计入 fixed、名字按 UTF-8 字节序（facts<hops<note<role<root_id<seal），与 §3.4 的 Python 侧建模约定逐点对上，模型确定性成立。
- 调用序：`v15_next_runnable ORDER BY root_invoke_id, depth DESC, invoke_id`（schema:905）——§3.5 队列（chain N 条；recall 根 print→根尾→depth 2..N 共 N+1 条）与该调度一致（根尾调用发生在 bind 建子之前，子恢复只执行 return 不再调 LLM）。
- 权限面：`jaz.print`/`jaz.var`/`jaz.prior_history` 均 `GRANT EXECUTE TO v15_repl`（namespace:635/637/642）；`down`、`tok`、`facts`、`root_id` 均不在 `_RESERVED_NAMES`（split_sql.py:20-35）。

## 4. 两份文书都缺的东西（覆盖项 4）

**E1｜分类器闸必须「先切分再分类」——计划未写，且做错会假触发 Plan B。** 实测：把带结尾分号的原文直接喂 `classify_statement`，**全部** canonical 语句返回 `plain + V15_INVOKE_FORM`（外层调用括号不再是最后一个 token，canonical 匹配失败后 `_has_control_name` 命中 `jaz."return"`/`jaz.bind_invoke`）。§3.5 的闸（「classify_statement 对 print 句给出 kind=print…」）没有说明输入必须是 `split_sql` 的切片（或先剥掉结尾 `;`）。照字面实现的步骤 3 会在零真实拒绝的情况下翻进 Plan B 并把假阳性写进 Run record。修法一句话：闸 = `for piece in split_sql(reply): assert classify_statement(piece).reject_code is None`。

**E2｜根自读历史的政策空白（recall_ok #3 的边界）。** §3.6 recall_ok 第 3 条「其他节点的语句文本不含 jaz.prior_history」+ `nonleaf_prior_history` 旗标把**根**也当禁区，但 NOTE_RECALL_V1 只禁止 mid 读祖先历史，没有禁止根读自己；而根在 iteration 1 恰好收到 context_window_warning 正文，其第一句就在推销 `jaz.prior_history(invoke_id)`（「Ancestor history is jaz.prior_history(invoke_id)」）。真模型若循警告提示在委托前用 prior_history 自查 facts（relay 与 token 都对），仍判 recall 失败。两份文书都没有讨论「根自读自身 id」是否应豁免。这不影响 fake，但直接影响 real 的 `recall_soft_fail` 概率与第 2/3 次 note 的措辞预算——是实现前应拍板的唯一政策点（见 §6 Q1）。

**E3｜警告正文与 print-first 的残余张力只覆盖了一半。** 风险表有「警告促使根在第一轮就委托」（已被裁决 2 的阈值设计消除）；未覆盖的对偶面：iteration 1 上警告先讲 history/prior_history 再讲两句委托，真模型可能改为「读历史并直接 return token」跳过委托（根 hops>1 时这是 no_delegation/浅链）。失败类齐全（no_delegation、shallow_chain 都在），所以可观测，但计划未把它列为预期失败模式——建议在 §5 风险表补一行，避免真跑首次出现时误判为 note 失败方向。

**E4｜harness fixture 5 断言面：数据源全部落实，无缺门。** 逐项核对（均为超管可读）：`input_chars` ← `invoke_events` payload（§3.3）；「根 iteration 0 是 print/continue」← statements.kind + iterations.result_kind；「警告只在根绑定迭代」← `llm_attempts.request->messages` join `llm_requests.iteration`；「llm_messages 无该 id」← persistent=false 双跳过点（govern:1414/:1480）已核实；「非根 seed 不含 token」← bindings.value::text 重排 compose；钩子行与 ordinal=4 ← `invoke_hooks`（baseline 0-3 + profile 空串 + 唯一 propagating，子复制父行，config 照抄——tree:157-228 已核）。唯一提醒：`calls_used=6` 的期望以「警告钩子不改变调用数」为前提——成立（warning 恒 proceed），无需改。

**E5｜一个小的执行细节空缺**：§3.2 说「uuid 在组装 inputs 之前生成」，但 `run()` 现签名里 seal/note/replies/expect_* 都在 `root_inputs` 之前备齐、uuid 生成点在 :262——重排时注意 `root_inputs` 的参数序（seal, note）与新增 root_id/facts 的进参方式计划已定（六键表），无歧义；此条仅提示别把 uuid 生成的时点又挪回 `root_inputs` 调用之后（那是现状 bug，计划已声明修正）。

## 5. 代码推翻 / 冗余 / 可简化项（覆盖项 3）

1. **§3.5 的 `_arg_has_write` 条件句被推翻**（见 §3.1）——不是删除建议：Plan B 作为已验证可过的保险保留是合理的；推翻的是「需要赌」这个前提。执行上可把 Plan B 分支降为纯文档路径（不预写双份 fixture 期望的代码，只留 Run record 字段），减少 §3.8「不要两套同时算过」的表面积。
2. **C3 的 ratio 校验落点错标**（见 §2.2）——改一句引用，不改设计。
3. **「实现期核对」的 request-兜底行是死路径**（见 §3.3）——`llm_attempts.request` 已实证携带瞬态消息；该行可保留（成本为零），但不应再作为「可能要改数据源」的未决项进入 Run record 模板。
4. 未发现「任务不需要」或「更简单设计可整体替代」的承重结构——sizer/分层/两轮载体/失败分类均与代码机制一一咬合，且都是最小侵入（不改 `v15/**`、不改 `db.py`）。按评审纪律，不因具体而建议删减。

## 6. 会实质改变执行的问题（覆盖项 5）

- **Q1（唯一决策级）**：recall_ok #3 / `nonleaf_prior_history` 是否豁免「根读自身 invoke_id 的 prior_history」？（选项：a. 维持全禁——note 需加一句「root 也不读历史」，注意 note 预算与 1500 上限（现 1096，有余量）；b. 豁免根自读——断言改为「mid 节点不含 prior_history，根不含非自身 uuid」。）影响 real 的软失败率与 note 措辞，fake 不受影响。
- **Q2（执行顺序）**：是否把 §3.1 的分类器实测表提前写进 Run record 草稿并锁定 Plan A？（本评审已给出全绿实测；锁 Plan A 可裁掉 Plan B 的双期望分支。）
- **Q3（确认级，可不答）**：sizer 的 `fixed` 以 Python 模型 + 一次性 DB 对照（to_jsonb 引号）为准——compose_inputs 逐字符确定性已核（§3.5），如实现者想再稳一点可改为在 harness 库里直接 `SELECT v15_loop_compose_inputs(...)` 取长（多一次连库，非必需）。

## 附：实测命令与样本

- 分类器/渲染：`uv run python`，`from v15.protocol.split_sql import split_sql, classify_statement`；`from v15.protocol.render_prompt import render_system`（样本为 §3.5 计划原文语句，uuid/seal 以合法字面量代入）。先 `split_sql` 后 `classify_statement`；直接喂含 `;` 原文会全数 `V15_INVOKE_FORM`（E1 的实证）。
- note 长度与 sizer 窗：Python 复算，seed 模型按 `v15_loop_compose_inputs` 逐字符复刻。
- 其余为只读代码核对，file:line 均以本工作树现状为准。
