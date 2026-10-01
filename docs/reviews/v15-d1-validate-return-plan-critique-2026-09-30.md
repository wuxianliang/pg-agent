# D1 ValidateReturn / ReturnType 计划评审：fold 一致性 + 代码核对

- 评审对象：`docs/plans/v15-validate-return-plan-2026-09-30.md`（1246 行，含 2026-09-30 三项用户裁决的 fold）。
- 基线：`prompt-exports/oracle-plan-2026-09-30-123309-v15-main-87ba86-3eef.md` 的 FIRST lane（codex，`# Summary`→`# Implementation order`，行 151–1367）；grok（### Oracle 2）与 cursor（### Oracle 3）为异议上下文。
- 方法：通读三轨 + 计划全文；对承重 file:line 与机制断言逐条对照 `v15/govern/v15_govern.sql`、`v15/loop/v15_loop.sql`、`v15/io/v15_io.sql`、`v15/repl/v15_repl.sql`、`v15/provider/v15_provider.sql`、`v15/schema/v15_schema.sql`、`v15/load.py`、`v15/*/setup_db.py`、`v15/govern/test_govern.py`、`v15/provider/test_provider.py`、`~/Projects/jaz/.../return_hooks.py` 与规格 `docs/designs/v15-jaz-dev.md`。行号以当前工作树为准（按符号核对，行号漂移已容忍）。
- 结论：三项裁决本身已正确落形（新 stage 11、封闭 DSL 替换 jsonpath、注册式协议），基线的实施顺序/边界表/映射细节/迁移节基本完整存活；但 fold 留下 6 处 jsonpath 残迹（含裁决表自相矛盾），且丢掉了两条异议轨各自独立证成的关键实现事实（P1535 活锁、setup 角色引导），另有一处会让 stage 9 gate 直接红灯的遗漏。分级如下。

---

## 1. 基线内容经 fold 后的存活性

**存活（已核对）**：实施顺序 13 步与基线一一对应（第 7/8 步的 jsonpath 措辞已换 DSL helper）；错误/边界表整体存活且 DSL 行已替换；三张映射、迁移/回滚节、§18 清单、gate 断言面、AGENTS 提交流程均未弱化。基线 New-interfaces 的 `v15_return_jsonpath_matches`/`v15_return_validate_jsonpath` 已等价替换为 `v15_return_spec_valid`/`v15_return_spec_fault`；基线「安装期代表性 probe」换成「形状校验 fail-fast」，语义等价成立。

**未存活——jsonpath 残迹（违反「除历史注记外不得残留」的 fold 完整性要求）**：

| 计划行 | 残迹 | 性质 |
|---|---|---|
| :165（Design §1 裁决表） | 「ReturnType DSL \| JSONB 值上的 PostgreSQL JSONPath 布尔谓词」 | **直接与用户裁决 2 矛盾**——决策表本身还在裁 jsonpath |
| :594（边界表） | 「JSONB null return value 可被 JSONPath predicate 正常匹配」 | 应改为按 spec 的 `null`/`any`/`anyOf` 形态匹配 |
| :797（README 清单） | 「ReturnType JSONPath」 | 应为封闭类型 DSL |
| :826（D31 台账内容） | 「v15 使用 JSONPath predicate，不移植 Python beartype/TypeForm」 | D31 若照此写入规格 §14 即与 §10.2 的 DSL 文法冲突 |
| :1196（实施顺序第 8 步） | 「加 complete-only JSONPath validation」 | 应为 spec_fault |
| :1208（第 10 步） | 「修复所有 …JSONPath… 问题」 | 同上 |

:10（用户裁决 2 括注）是唯一合法历史注记。这 6 处会让「规格 rev 10、D31、README、gate 冻结文案」四处互相打架，实现者无从逐字冻结。

**从异议轨丢失的承重内容（fold 只取了 O2 的 DSL 文法，没取其代码实证）**——见 §2/§3 的 F1、F2、F3。

## 2. 接缝、矛盾与引用错误

**F1（P0，活锁）：raise 与 continue 的 exec_result 冲突被计划固化成 P1535。**
代码事实：`v15_on_phase` 的合成是「相等合并，不等即 `P1535`」（`v15_govern.sql:1278-1280`）；回滚类错误使阶段事务整体回滚、worker 整段重试（规格 ：1930 一带），且 `invoke_hooks` 有 BEFORE DELETE/UPDATE 守卫（`v15_schema.sql:539-566`，P1532），open invoke 上的 hook 行拆不掉。`budget_forcing` 是默认演示 hook：当预算耗尽 forcing 发 `continue`、同时 `return_type` 计数已到 cap 发 `raise` 时，同一 `repl_exec/complete` 稳定 P1535 → 回滚 → 重试 → 永久冲突，invoke 停在 leased。计划 §9.5 修订清单写「不同 exec_result 仍 P1535」、边界表写「两个 validator 返回不同 exec_result \| P1535，阶段回滚」，均未识别该组合。**O2 与 O3 各自独立设计了解法**（O2：raise 压过 continue + 过滤输家的 continue 消息；O3：`v15_loop_prefer_exec` 判定函数），fold 全部丢弃。必须在动工前裁决：采纳 raise-wins 合成（并写进 §9.5 修订句），或证明 budget_forcing 与 return_type 在同一 invoke 上不可能同时各自发效应（现有代码下证不出来）。

**F2（P0，gate 红灯）：stage 9/10 的 setup 角色清单缺 `v15_hook_return_type`。**
代码事实：`HOOK_ROLES` 是**按 stage 复制**的元组（`v15/govern/setup_db.py:18-27`、`v15/provider/setup_db.py:17-`、`v15/schema/setup_db.py:17-`），每次 setup 先删光 `v15_hook_*` 角色再按本 stage 清单重建。计划把 handler CREATE/`ALTER … OWNER TO v15_hook_return_type`/hook_defs INSERT 放进 govern 文件（stage 9 加载），却只在**新增的** `v15/return_hooks/setup_db.py` 里建角色——stage 9 自己的 bootstrap 没有该角色，govern SQL 加载即 `role "v15_hook_return_type" does not exist`，九道前置 gate 直接红。计划的 File-by-file「Modify」清单**没有** `v15/govern/setup_db.py` 与 `v15/provider/setup_db.py`。O2 明确指出此点（「在会加载 govern SQL 的引导段加入…govern 与 provider」）。修复：两个 setup 的 HOOK_ROLES 各加一行。

**F3（P1，落库错值）：return→raise 分支漏了 `v_inv.error` 内存赋值。**
代码事实：现有 raise 终态分支写 `repl_history.repl_exception = v_inv.error`（`v15_loop.sql:931-937`），且该分支的 `UPDATE invokes` **不写 error 列**（模型 raise 时 `jaz_raise` 已先写）。计划 §5 只说「把规范化 error 写入 `invokes.error`（表）；将 v_kind 改为 raise」——不提 `v_inv.error := v_err`。照写则历史行记上候选 return 时代的旧值（SQL NULL），与计划自己的结果清单「`repl_history.repl_exception` 为 P1540 error」矛盾。O3 逐句抓到了这一点（「只改表、不改变量，历史行会记上候选阶段的旧 error」）。§5 第 3 步必须补一行赋值（`v_inv.return_value` 同理，continue 分支今天就同时改表和变量，`v15_loop.sql:869`）。

**F4（P1，gate 红灯）：`test_provider.py:206` 的「provider is last SQL」断言会被第 11 项打破。**
代码事实：`check("provider is last SQL", SQL_LOAD_ORDER[-1].name == "v15_provider.sql")`（`v15/provider/test_provider.py:206`）。追加 return_hooks 后该断言必红。计划的 provider gate 修订节只说「保持 stage 10 的 load-order 断言为十文件」，未点名这条 `-1` 断言要改成 `files_through("provider")[-1]`（`len(provider)==10` 与 `ends at provider` 两条存活，`govern prefix nine files` 存活）。修订清单需补。

**引用错误（P2）**：
- Background 引「spec §9.4:1930」——:1930 是回滚类分节句；「本版唯一合法的修改是把候选 return 改成 continue」实际在 **:1915**。
- 引「§18 … v15-jaz-dev.md:2380-2428」——§18 实际是 **:2405-2428**；2380-2404 是级联删除/事件触发器内容（Background 的「（govern:2410）」按规格行号可解析，但 `v15_govern.sql` 全文只有 1618 行，记法有歧义，建议写成 `spec:2410`）。
- 其余承重引用**核对通过**：`v15_govern_check_return` continue-only 硬编码确在 :291-304；`invoke_hooks_optional_guard` :413 起、ELSIF 链无 ELSE、未知 key 只查 config object、且 **baseline channel → P1524 是既有闸门**（:437-439，计划 gate 断言与现状一致）；`v15_register_hook` :515；budget_forcing 消息 id :841；快照 `self` 含 `hook_key/ordinal/channel/config/state`（:1152-1159）；`counters` 是 `object_agg(counter_key, n)`（:1097-1100）；`v15_loop_accept_forcing` :665-705 与消费点 :853-876、raise 分支 :917-955；`v15_loop_sqlstate` 确为 `coalesce(repl, io, CASE)` 且 `V15_RAISE→P1529` 只在 loop CASE；provider `v15_io_sqlstate` 无 `V15_RAISE`、known_code 两份函数体（govern :1 CREATE / provider :23 REPLACE）；`load.py` 十项；`hook_defs.hook_key ~ '^[a-z][a-z0-9_]{0,53}$'`（无冒号，三段 id 解析单义）；`llm_messages UNIQUE(invoke_id, message_id)`；`v15_io_deliver_child` 对 failed+非 fatal 走 `v15_repl_deliver_nonfatal`，**无子码白名单**（§4.8 送达主张成立）；jaz 各行号（:81-109/:288-342/:295-311/:346/:493-498）抽查吻合。

## 3. 代码反驳或更简设计取代的计划细节

**(a) 封闭 DSL 文法内部一致性**——一处硬矛盾：
- 失败文字模板：深层 = `Expected <render(node)>. Got jsonb <typeof> at <path>.`；而冻结示例 3 是 `Expected number at $.n. Got jsonb string.`——**`at <path>` 的位置两者相反**。二选一必须改，否则「gate 逐字断言冻结示例」与「规格 §10.2 抄模板」必有一个对不上。该矛盾继承自 O2 原文，fold 未修。
- 次要：`enum` 的 render 用 `<elem::text>`，jsonb 数字保形（`1.0` 打印 `1.0`），且 jsonb 相等按数值比较（`enum:[1]` 匹配 `1.0`）——通过性按数值、展示按字形，属可接受但应在 §10.2 写明；`{"type":"any"}` 永不产生 fault（含 JSON null），但 **SQL NULL 根值**（脏数据路径）的 fault 文字未定义——`jsonb_typeof(NULL)` 为 SQL NULL，「Got jsonb <typeof>.」会渲染成空段，需指定（建议 fail-closed 固定句）。
- 其余文法自洽：五形态 exact-keys 互斥、对象开放语义、键名 `^[A-Za-z_][A-Za-z0-9_]{0,62}$`、深度 ≤8、anyOf 1..8 均可由 `v15_govern_exact_keys`（govern :204，存在）+ 递归实现；冻结示例 1/2/4 与模板一致（示例 2 的 `object {n: number}` 与 render 规则相符）。

**(b) stage-9 前缀加载可行性（PL/pgSQL 晚绑定）**——主张**成立**：guard 与 handler 均为 PL/pgSQL，CREATE 期只做语法检查、被调函数运行期解析；stage 9 不安装 return_type 故不触发调用。但真正的 stage-9 阻塞不是晚绑定而是 F2（角色）与 shape guard（handler CREATE 同文件先行，已满足）。**更简设计在桌上**：O2 把两只 spec helper 直接放 govern（「内核辅助函数而非 hook handler，不违反 §18」），stage 11 只留 effect builder——一步到位消除晚绑定赌注与降级方案分支；计划的降级方案（helper 提前入 govern）与之等价，建议直接裁决而不是留待实测。

**(c) 计数泛化的 ID 解析安全约束**——声称「可阻止任意 handler 伪造其他 invoke 或其他 ordinal 的 counter」**言过其实**：快照把本 invoke 的**全部** counters 发给**每个** handler（:1097-1100），ordinal 3 的 handler 能读到 `budget_forcing:5` 的当前 n 并伪造合法三元组 id——约束 3（ordinal↔hook_key 存在）与约束 4（n 相等）都拦不住同 invoke 跨 hook 伪造。真正堵死需要 emission 归因（合成时按「本相位发出该消息的 hook」核对 hook_key），O2/O3 也没做——计划应改口径为「阻止跨 invoke 与不存在的 ordinal」，或补归因设计。另：约束 4（n 与库值相等，否则 P1523）是**新行为**——今天 `v15_loop_accept_forcing` 不比对 n（:683-696 只认形状就 +1）；对 budget_forcing 兼容（handler 恒发加一前值），但任何 handler 系统性发错 n 会让 finish 永久回滚（hook 行拆不掉，同 F1 家族的卡死面），计划应把它作为有意识的收紧写明并配 gate。
- 解析细节缺口：三段 id 的第 2/3 段**必须钉死 `[0-9]+`**（否则 `return_type:prompt:<ordinal>` 的第二段 "prompt" 会在宽松实现里触发 cast 异常→P1516 毁掉 finish）；O2 明确「坏 id 跳过不让 finish 变 P1516」，计划只给了 `^(<hook_key>):(<ordinal>):(<n>)$` 抽象形。int4 溢出段同理。

**(d) `v15_loop_accept_forcing` 唯一生产调用点**——**核实为真**：全仓唯一调用在 `v15_loop.sql:866`（`v15_finish_exec` 体内），无任何 `*.py` 直接引用；改名安全。保留意见（O2/O3 共识）：不改名更省——名字不入任何 API 面，改名牵动 GRANT 行与规格 §4.9 的函数名提及；计划已把改名成本列全（owner/revoke/grant 清单），两可，但「避免两套计数路径」的理由对改名/不改名同样成立。

## 4. 基线与计划都缺的需求/边界

1. **return_type 的 channel 与传播语义未指定**（设计节只裁了 validate_return family 的 channel；gate 断言只隐含 baseline→P1524）。传播事实（D12）：propagating 把 hook_def_id+config 复制给子 invoke、ordinal 重编号、`state={}`、**计数不复制**。可观察后果：链上每个装了 return_type 的 invoke 在**各自 iteration 0** 各得一条 prompt（`llm_messages` 按 invoke 隔离、UNIQUE(invoke_id,message_id)，`return_type:prompt:<ordinal>` 不会跨 invoke 相撞——已核实安全）；`max_failures` 是 per-invoke 而非 per-tree（jaz 同为按 invoke 计数，:295-297 dict 以 invoke_id 为键——一致但应写明）。若只裁「prompt 是否每层都发、计数是否每层归零」这两句，实现与 gate 都会各写各的。
2. **`max_failures=null` × 迭代上限**：终态是 `V15_ITERATION_EXCEEDED` 而非任何校验码（O2 边界表有，计划边界表缺）。
3. **`max_failures` 的 int/float 判定**：jsonb 无整数类型，`2.0` 是 number；「非整数拒绝」需要 scale 检查。现成 helper `v15_govern_json_int(jsonb,int,int)`（govern :134）就是干这个的，计划未点名复用（O2 点了）。
4. **enter 注入的落地依赖 io 层接力**：`llm_query/enter` 在 `v15_on_phase` 落地循环前 RETURN（:1408-1409），enter 返回的 messages 由 `v15_io.sql:1186-1192` 接力进 send io 的 `enter_messages`、在 send 分支统一落 `llm_messages`（persistent-only，重复 id P1524）——计划 §3.1 的「enter_messages → send」路径**代码成立**，但引用只指 govern:1345-1516，接力点在 io 文件未提；gate 应断言「prompt 在第一次 complete 前已入 llm_messages」以覆盖这条跨文件接力。
5. **complete 相位的持久消息落地路径未在计划中显式确认**：`repl_exec/complete` 的 recovery message 走 v15_on_phase 尾部通用落地循环（:1477-1505，persistent-only + 重复 P1524）——与 §9.6 一致，但计划只说「添加一条持久 user message」未指明该循环，实现者可能误以为要新落地点。
6. **io_sqlstate 分层**：计划要求 provider 的 `v15_io_sqlstate` 加 `V15_VALIDATION_FAILED→P1540`；最近先例 `V15_RAISE→P1529` **只在 loop CASE、不在 io 映射**（已核实），O2 据此明确不动 io_sqlstate（「避免把 loop 层的码写进 io 层映射」，coalesce 先问 io 再落 CASE，两处同值也冗余）。计划的「三张映射」口径应二选一：跟先例（两张：loop CASE + provider known_code）或写明为何破例。
7. **known_code 的 govern 函数体**：该函数在 govern CREATE、provider REPLACE（两份体）。计划只裁 provider 体；govern 前缀库将不识别新码（对 D1 gate 无害，但 govern/full 两前缀行为分叉未记录）。O2 两份体都改并强调「provider 替换体必须是 govern 名单的超集，漏写会把新码盖掉」——这个覆盖陷阱计划没提。
8. **语句行保持 `kind='return'`/`status='done'`、更大下标 skipped**：return→raise 与模型 raise 的可观察差（O2/O3 都写了，计划 §5 结果清单只写 iteration `result_kind='raise'`，语句级未提）；gate 想断言「语句 kind 仍 return」需要这句依据。

## 5. 会实质改变执行的问题

1. **合成规则**：是否采纳 raise-wins（O2 消息过滤版 / O3 `v15_loop_prefer_exec` 版）？不裁决则 F1 活锁按计划原文必然入库。（影响 §9.5、`v15_on_phase` 修订、gate 断言面。）
2. **helper 归属**：spec helper 直接进 govern（O2，零晚绑定赌注）还是维持 stage 11 + 实测降级路径？影响 F2 的修复面与 stage-9 gate 的写法。
3. **return_type 以哪个 channel 种子化**（propagating/local）？决定 prompt 是否逐层发、子链是否各带一份 max_failures（§4.1）。
4. **`v15_io_sqlstate` 动不动**？决定 provider 文件修订面与 §18 句式（跟 V15_RAISE 先例两张映射，还是三张）。
5. **`v15_loop_accept_forcing` 改名与否**？调用点唯一已证实，改名只剩文档/GRANT 成本；不改名则 §7.2/接口表/API 表三处回改。
6. **n 相等校验（约束 4）保留与否**？保留=新收紧+卡死面 gate；放弃=与今天 forcing 行为逐字节对齐（O2/O3 都选放弃）。
7. **prompt 注入点**：enter（接力已核实可用，与 §9.6 既有句式一致）还是 send（O2，少一跳）？两者 gate 断言面不同。

---

## 附：核对通过清单（免重查）

`check_return` :291-304；guard :413-509（ELSIF 无 ELSE、未知 key object-only、baseline channel P1524 既有）；`register_hook` :515；budget_forcing id :841；`self`/`counters` 快照形状；enter→send 接力 io:1186-1215；complete 持久消息落地 + 重复 id P1524；`accept_forcing` :665-705 唯一调用点 :866；finish 消费 :853-876；raise 分支 :917-955；io 键白名单 ：127-128；allow :104；`hook_key` 文法无冒号；`UNIQUE(invoke_id,message_id)`；`deliver_child` 无子码白名单（failed+非 fatal → `deliver_nonfatal`，父恒 CHILD_ERROR）；P1540–P1548 空号（§18 :2424-2426）；`load.py` 十项/STAGE_THROUGH；jaz 行号抽查；PL/pgSQL 晚绑定主张成立。
