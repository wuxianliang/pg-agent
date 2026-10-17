# v13 Stage 40 `ce_run` 六动词计划评审（critique）

| 项 | 值 |
|---|---|
| 日期 | 2026-10-15 |
| 评审对象 | `docs/plans/v13-ce-run-six-verbs-2026-10-15.md`（下称「计划」） |
| 基线 | `prompt-exports/oracle-plan-2026-10-15-164431-v13-ce-oracle-a3effd-66ce.md` 的 **Generated Plan 响应**（下称「导出」；其前的组合 prompt 与选文件清单仅作上下文，不作计划内容） |
| 范围纪律 | 仅覆盖五类：① 导出中有实现承载力但计划缺失/弱化/泛化的内容；② 欠规约接缝、未决实质决策、矛盾、引用错误、缺失依赖；③ 被代码证伪/任务不要求/有更简命名替代的细节（附精确修正与理由）；④ 双方均缺席的 ownership/lifecycle/failure/cancellation/testability 问题；⑤ 答案会实质改变设计或实施顺序的问题 |
| 实查接缝 | 唯一点查：桥接函数本体——`v13/acl/v13_acl.sql`（`v13_control_authorized` :90-119、`v13_cancel` :121-234、`v13_complete` :245-471）与 `v13/schema/v13_core.sql`（`v13_append_event` :62-93、`v13_effect_id` :175-182、`v13_enqueue_effect` :210-264、`v13_claim` :267-297、授权矩阵 :854-898）。下引行号均来自该次实读 |

---

## 1. 导出中有实现承载力、但计划缺失 / 弱化 / 泛化的内容

1.1 **steer 的终态复活分支整条丢失。** 导出在 `v13_ce_run_steer` 与 Errors 两处明确：terminal/inactive run 同样要求 `expected_epoch` 精确匹配，随后创建 ordinal+1 的 steering epoch、清除旧 interaction、恢复 running（「terminal run poll 返回终态；cancel 为 replay；steer 才允许新 epoch」）。计划的 steer 契约只对 `('running','waiting_for_input')` 定义 interaction 拦截，对 `completed`/`failed`/`cancelled` 下 steer 的行为完全未规定。这是六动词语义的一整条分支，直接决定 steer 的分支结构与测试矩阵。

1.2 **respond 的非 human 分支与回答回流丢失。** 导出：「若不是 human effect，仅将 answer 写入 CE operation，后续 worker 使用该 operation 输入」。计划 respond 第 5 条只覆盖 human effect 结算；对 approval/question 等非 human interaction，answer 如何进入下一轮 LLM 输入、由谁准入后续 turn，计划无一字。叠加 §4.3（respond 后无人入队新 effect），respond 完成后 run 停在 `running` 但队列中无可领取 effect——停摆。

1.3 **human 通道结果契约被弱化成一个未定义变量。** 导出保留「human result 必须符合既有 `interaction_ref`/one-of 校验」；计划只剩 `v13_complete(NULL::uuid, ..., 'succeeded', v_human_result)`，而 `v_human_result` 全文未定义。实查（`v13_acl.sql:330-372`）：`kind='human'` 且 request 含 `interaction_ref` 时，`p_result` 必须满足 `schema_version=1`、`interaction_ref` 与 effect.request 精确一致、`response`/`answers`/`skip` 恰好其一，否则 `RAISE`。这不是可省的内部细节——respond 的实现与测试必须构造该形状，否则调用即异常。

1.4 **`v13_ce_admit_operation` 的锁序与返回形状被截断。** 导出明确「锁顺序：run → epoch → operation → effect」且「返回 operation、effect、attempt/fence 初始信息」；计划的 admit 契约锁序止于 `v13_ce_epochs`，亦不返回 attempt/fence。Worker T1b 领取所需令牌的来源因此欠规约。

1.5 **`v13_ce_publish_snapshot` 的幂等/防回退规则丢失。** 导出：「相同 revision/request 重放返回原结果；更低 revision 不覆盖」。计划的 publish 签名连 `request_id` 参数都没有，三条状态分支均无重放语义；T2 已提交但响应丢失后的 worker 重试会重复推进 revision、重复写 wake 行。

1.6 **测试覆盖矩阵被替换为悬空引用。** 导出为 `test_ce_run.py` 列了 16 条具名覆盖项（含 `native_load_untouched`、`native_plan_arm_closed_set`、`native_frozen_driver_bytes` 冻结断言及 claimed/unknown 与 archive 分离等运行时探针）。计划 §5.1.3 写「全部静态与运行时门禁探针（详见 §8）」，但 §8 只有实施顺序与验证命令，没有任何探针清单——引用错误与内容丢失并存。

1.7 **setup_db 防护细节丢失。** 导出要求：拒绝已存在同名库、拒绝 `agent_v13_` 前缀、检查 `stannum`/`pg_jsonschema` 等既有扩展。计划 §5.1.2 只剩库名模式与 DROP 清理。

1.8 **tools 行 / sql-route 裁决规则丢失。** 导出明确「不加入 tools 行，除非实现明确需要 SQL route；若加入，必须在本文件内定义独立 CE tool whitelist，不复活 `controller` policy」（与 prompt 关键发现 6 的 stage-41 先例研究要求呼应）。计划全文未触及六动词是否需要经 tools 表/sql-route 可达（另见 §2.9 与 §5.2）。

1.9 **风险与运维条目丢失。** 导出列有：(a) 数据库须从 Stage 39/40 全量重建、无增量回滚；(b) 旧调用方须迁移到 `v13_ce_run_*`、不提供兼容别名；(c) ce_* 与 sessions/effects 双事实的显式清理义务；(d) 单一推进入口前提（`LoopDriver.run` / `RealChain.serve` / `GoalSupervisor.tick` 须由部署侧禁用）；(e) worker 取消语义（不撤销已提交 T1；operation 留 pending/claimed 按租约或显式 cancel 处理）。计划 §7 均未保留。

1.10 **小但实现承载的两条丢失**：`ce_wait` 的返回键闭集（导出固定 `schema_version, reason, snapshot, registration_generation, epoch_ordinal, continuity_generation, interaction` 七键）；「payload 超界复用既有 JSON shape/size 限制，拒绝写入」的边界条目。

1.11 **可复用接缝清单少了 `driver.py`。** 导出与 prompt relationships 均点明 `LoopDriver` 的四层组装、事务外 IO、Fake 测试模式及「claim/IO/complete/settlement 形状」是薄 Worker 应回显的样板；计划 §3.2 接缝清单未列 `driver.py`，§4.4 从零描述 `CeWorker`，失去了与既有已验证形状的逐点对照。

---

## 2. 欠规约接缝 / 未决实质决策 / 矛盾 / 引用错误 / 缺失依赖

2.1 **`SECURITY INVOKER` 与「状态转换仅经函数完成」自相矛盾，且 ce_* 五表的授权矩阵缺席。** 计划 §4.1 声称表对 PUBLIC/`v13_worker` 收回写权限、「所有状态转换仅通过授权给 `v13_route` 的 PL/pgSQL 函数完成」；但 §4.2 给动词标注 `SECURITY INVOKER`。INVOKER 函数读/写 ce_* 表要求**调用角色对表本身**持 SELECT/INSERT/UPDATE——`v13_core.sql:854-870` 正是因此给 `v13_route` 授了 sessions/events/effects 的表级权限。计划从未给出 ce_* 五表的表级 GRANT：照字面实现，`v13_route` 调 `v13_ce_run_poll` 即 permission denied；若补授表级写权，「仅经函数」即刻失效。二者必居其一：改 `SECURITY DEFINER`（表全收回、函数属主执行），或改 INVOKER + 表级授权并删除「仅经函数」表述。同类缺失依赖：`v13_core.sql:866` 只授了 `events, effects` 的 INSERT、`:870` 授 `sessions, effects` 的 UPDATE——**`sessions` 的 INSERT 并未授给 `v13_route`**，而 start 第 4 条要直插 `public.sessions`；INVOKER 下该语句对 `v13_route` 必然失败，须核实既有 stage 是否另有授权或改走 `v13_plan_commit_entry`。此外门禁测试以哪个角色/连接执行也未指定——若以超级用户连接，全部授权缺口被掩盖，ACL 探针失去意义。

2.2 **迟到回执不结算在途 claimed effect → 会话必然被 unknown 墙锁死。** accept_receipt 分支 D（`archived_stale`）只归档 operation 行，不触碰其 claimed effect；§4.4 又要求 worker 收到 `archived_stale` 后 commit 并停止。该 claimed effect 租约到期 → `v13_requeue_stale` 转入 `unknown` → 之后唯一拦阻点是 steer 第 6 条的会话级检查，该 session 的 steer 永远返回 `unknown_wall`，且本里程碑没有任何 resolve 出口。「steer 期间旧 epoch 在途 IO 稍后进入 T2」正是计划 §3.1/§6.1 自述必须幸存的 canonical 竞态，当前契约使其必然砖化。分支 C（closed 行）反而写了「安全结算或清理」——既含糊又与 D 不一致。修正方向：归档 operation 的**同一 T2 内**用在途 worker 携来的真实 `(attempt_no, fence, result)` 调 `v13_complete` 结算底层 effect（外部副作用确实发生，结算是记账而非伪装），CE 层仍返回 `archived_stale`。

2.3 **steer 延迟绑定的触发者不存在。** steer 第 7 条：有在途 `claimed` effect 时新 steer operation 的 `effect_id` 暂置 NULL，「待在途 claimed effect 在 T2 归档并释放单活跃槽位后由 `v13_ce_admit_operation` 入队」。但归档回执的接收方（旧分支 worker）被 §4.4 要求停止推进，没有任何组件被指定在此刻调用 `admit_operation`。结果：新 epoch 的 steer operation 永久 pending、`effect_id` NULL、run 停 `running`、waiter 挂到超时。必须具名触发点（最自然：accept_receipt 归档/结算分支在释放槽位的同一 T2 内绑定并入队，见 §5.4）。

2.4 **分支 F 的「此时绑定」与 T1→IO→T2 流程矛盾。** 对 `effect_id IS NULL` 的排队 `admit_tool`，分支 F 在 T2 回执时才创建并立即结算 effect——即工具 IO 期间根本不存在 effect 行：无租约、无 claimed 墙保护（§6.1 崩溃档位 2 不适用）、单活跃槽位在 IO 期间空闲（另一并发准入可插入新 effect）。这同时违背 admit 契约自述的「严格遵守 `ux_v13_effects_single_active`」与 §6.1 的崩溃叙事；且「无 effect 的 pending operation」崩溃后 `v13_requeue_stale` 看不见、operation 表又无租约列（见 §4.1），彻底不可恢复。

2.5 **steering wake 的 `epoch_ordinal` 归属未指定，`interrupted_by_steering` 可能结构性不可达。** steer 第 12 条写 wake 未注明用旧还是新 epoch ordinal；wait_check 第 5 条按调用方旧游标 `(p_run_id, p_registration, p_epoch)` 查最新 wake。若 steer 以新 epoch ordinal 写 wake，旧游标永远查不到它，等待者只能拿到 `epoch_advanced` 而非 §3.1 引用 CE 语义明确要求的 `interrupted_by_steering`（含 `origin_run_id = caller` 时的正文抑制）。须指定：打断 wake 的 `epoch_ordinal` = 被打断的旧 epoch，并写明跨多个 epoch 时的查找规则。

2.6 **cancel 不写 `sessions.status`，且 `v13_cancel` 的两处真实语义未被认领。** 实查：`v13_cancel`（`v13_acl.sql:121-234`）只追加 `cancel/requested` 事件（:223-226）并取消整棵子树的 ready effects（:227-230），**不 UPDATE `sessions.status`**（v13 侧的 `cancelled` 由 advance 消费 cancel/requested 后落）。CE 路径不跑 advance，故计划 cancel 后 `sessions.status` 恒为 `'ready'`、`cancel/requested` 永远不被消费——与 publish_snapshot 第 3 条会把 sessions 置 completed/failed 终态明显不对称，双事实就此分叉。另两处未认领：(a) `v13_cancel` 沿 `parent_session_id` 递归取消**整棵后代子树**（:151-231）——CE cancel 是否应级联子 run，计划未表态；(b) 会话已终态时它返回 `'replay'` 且一个 effect 也不取消（:200-203）。

2.7 **底层函数返回值/异常到 CE 结构化结果的映射缺失。** `v13_complete` 返回 `'accepted'/'replay'/'stale'`（:300-308），并对 human 通道、形状校验等 `RAISE`；`v13_cancel` 返回 `'accepted'/'replay'`，对 unknown session / goal tree cycle / depth / tree-changed `RAISE`。计划九个函数均未规定这些返回值与异常如何映射为结构化 disposition（`'stale'` 是否并入 `archived_stale`？`RAISE` 是吞掉转 `{"ok":false}` 还是放任回滚？）。注意底层 `RAISE` 会回滚整个 T1/T2——与计划「归档后绝不 RAISE」的铁律在同一函数调用链上直接相碰，必须写明捕获/不捕获的边界。

2.8 **unknown 墙检查不对称，且计划对 enqueue 墙的表述被代码证伪。** 计划 §3.2 称 `v13_enqueue_effect` 带「unknown 墙阻断（:246-247）」；实查该 `RAISE` 仅在**同身份** effect 已 unknown 时触发（:227-248 的身份分支）。CE 每个 operation 的 request 不同 → 身份不同 → 该墙在 CE 路径几乎永不触发。计划只在 steer 第 6 条加了会话级 unknown 检查，`start` 与 `admit_operation` 没有——崩溃留下 unknown 的 session 仍可被 start/admit 继续入队。需统一：凡调用 enqueue 的动词先做会话级 unknown 检查，或显式声明「steer 是唯一恢复入口」并给出理由。

2.9 **effect 身份碰撞未防。** `v13_effect_id` = f(session, last_user_seq, cycle_no, kind, request 哈希）（:175-182）。start 第 8 条在 request 里嵌了 `operation_id` → 身份唯一；但 `admit_operation` 第 3 条直接把 `p_payload` 当 request——同一 epoch 两个参数相同的 `admit_tool` 会算出同一 `effect_id`，enqueue 幂等返回同一行（:228-229），两个 operation 绑同一 effect，结算相互串扰。须规定 admit 的 effect request 必嵌 `operation_id`（与 start 一致）。

2.10 **T1b 的「或」必须裁决为 scoped claim。** `v13_claim(text,int)` 是**全局**领取（:267-297，无 session 过滤），多 run 并存时会领走别的 run 的 effect。计划写「`v13_claim(...)`（或按 `effect_id` 领取……）」——后者是唯一正确形态，前者应删。

2.11 **start 幂等重放的返回来源不存在。** start 第 2 条承诺「原样返回该次 start 的已提交快照」；但 `v13_ce_snapshots` 是每 run 单行、被后续发布覆盖，start 时点的快照无处可查。须改为：重放返回 operation 行登记的身份元数据 + **当前**快照，或 start 完成时在 `operations.result` 落一份回执副本供重放读取。

2.12 **无写入者的字段与 CHECK 分支。** `status='expired'`、`registration_generation` 递增、`owner_generation` 递增、`transition_kind IN ('related_follow_up','unrelated')`、wake reason `'superseded'`——全部无生产者（六动词不写，计划也无其他路径）。schema 携带了一套无人驱动的连续性/换代机器，wait_check 的 `superseded` 分支结构性不可达。应显式裁决：本里程碑补生产者动词（超出六动词范围），或在契约与 README 中声明这些列/分支为 reserved 留缝、测试按不可达处理。

2.13 **杂项欠规约**：§5.1.2「（或在 `setup_db` 中提供装载入口）」二选一未决；分支 B「校验结果摘要」无存储支撑（`payload_digest` 是请求摘要非结果摘要，应改为 `o.result` 与 `p_result` 等值比较或删除该校验）；publish_snapshot 第 2 条只列 `cancelled`/`expired` 两个拦截终态，run 已 `completed`/`failed` 时的到达行为未规定；`waiting_for_input` 时 `sessions.status` 的映射（`'waiting'`？）未规定，publish 只写了终态映射。

---

## 3. 被代码证伪 / 任务不要求 / 有更简命名替代的细节

3.1 **steer 第 10 条括注被代码证伪。** 计划称 `v13_append_event`「自动将 `completed/failed/cancelled` 会话恢复为 `ready`」。实查：复位仅覆盖 `completed/failed`（`v13_core.sql:79-81`），注释明确「**cancelled 归 ch12（显式 resolve 域）不复位**」（:74-78）。精确修正：删去括注中的 `cancelled`；并据此裁决 steer 是否接受 `cancelled` run——若接受，须显式 `UPDATE sessions.status` 或走 resolve 域；若拒绝，写入 §6.2 错误清单。该修正与 §1.1/§5.1 联动。

3.2 **steer 第 7 条的 `v13_cancel` 调用由更简命名设计完全替代。** 目的只是释放单活跃槽位，但 `v13_cancel` 会：(a) 向本 session 写入 `cancel/requested` 事件——其消费者（`v13_complete` cancelled 分支的 `cancel not pending` 闸 :317-319、control SQL 的 actionable 信号）将看到幻影取消；(b) 级联取消全部子孙 session 的 ready effects——一次 steer 不应波及子 run；(c) 会话终态时 `'replay'` 空转、什么都清不掉。替代：对本 session 直接 `UPDATE effects SET status='cancelled', fence=fence+1, error=NULL, lease_owner=NULL, lease_until=NULL WHERE session_id=p_run_id AND status='ready'`（即 `v13_cancel` :227-230 内语句的单会话版），无事件、无子树、无终态空转。理由：目标语义是「清槽位」而非「请求取消」，应使用与目标语义等大的最小机制。

3.3 **`wait_check` 的 `p_timeout_ms` 参数与 `'waiting'` 返回分支是死设计。** 唯一调用方 `ce_wait` 恒传 0（§4.4 ce_wait 第 3 条），deadline 由 `ce_wait` 本地持有；`'waiting'` 分支（第 6 条后半）因此不可达。更简替代：删除该参数与分支，`wait_check` 收敛为纯判定函数，等待预算全部归 `ce_wait`。导出同样携带此死重，一并裁。

3.4 **§3.2 对 enqueue unknown 墙的接缝表述按 CE 用法证伪**（证据见 §2.8）：接缝清单应改写为「同身份 unknown 重挂阻断；会话级 unknown 需 CE 各动词自查」，否则读者会误以为桥接免费获得会话级墙。

3.5 **分支 B「校验结果摘要」**：无对应存储（见 §2.13），要么改为 `o.result` 等值比较，要么删除该校验——保留一句不可执行的校验比没有更糟。

---

## 4. 计划与导出均缺席的内容（ownership / lifecycle / failure / cancellation / testability）

4.1 **operation 级崩溃恢复整体缺席。** `v13_ce_operations` 无租约/超时列，无恢复扫描；§6.1 崩溃档位 1 称「按既有规则继续」但没有任何「既有规则」指向 CE operation——`v13_claim` 领的是 effect 不是 operation，effect 被另一 worker 领走后由谁把它与 pending operation 重新关联？Worker 重启后的 resume 协议（读哪个 pending 集、按什么序、如何防两个 worker 同驱一 run）双方均未定义。

4.2 **CE 会话与普通 v13 驱动的单入口纪律无执行机制。** 该前提在导出仅存于风险段、计划连风险段都删了（§1.9d）。CE start 直插 `sessions` 行后，该 session 对 `LoopDriver.serve`/`v13_advance` 而言与普通会话无异——一旦另有驱动拾取，双控制面并发推进同一 effects 队列。至少需要一句部署/测试约束（CE 会话专属 worker、测试库内不起 LoopDriver），或一个结构标记（如独立 route_policy 分流）。

4.3 **respond 之后的推进者缺席**（比 §1.2 更根本）：清掉 interaction、置 `running` 之后，没有任何 effect 入队、没有 `admit_turn` 的触发者。导出也仅一句「后续 worker 使用该 operation 输入」。respond 必须自带推进（同事务 admit/enqueue），或明确由 CeWorker 主循环轮询 pending respond operation——后者与 §4.1 的 resume 协议是同一个洞。

4.4 **human effect 的生产者缺席。** respond 第 5 条以「当前挂起 interaction 关联了底层 `kind='human'` 的活跃行」为前提，但 CE 路径没有任何函数入队 human effect；且 `v13_complete` 的 human 通道要求结果回显 request 中的 `interaction_ref`（`v13_acl.sql:343-347`），interaction.id ↔ `interaction_ref` 的对应关系无人建立。裁决项：publish_snapshot 在置 `waiting_for_input` 时同步入队绑定 `interaction_ref` 的 human effect，或声明本里程碑 interaction 为纯 CE 对象并删除 respond 的 human 结算分支（含「ready 先提升为 claimed」这段绕过租约纪律的未规约步骤）。

4.5 **数据生命周期缺席。** `v13_ce_wakes` 每 revision 至少一行、operations 每动作一行、events 只增——无保留/清理策略；导出提到「cleanup 必须显式处理两套事实」但也未设计。临时测试库随 DROP 消失所以门禁不红，但 Stage 40 控制面一旦长期运行即无界膨胀；至少 README 须声明留缝。

4.6 **授权与执行角色矩阵缺席**（承接 §2.1）：门禁以何角色连接、`v13_route` 对 ce_* 五表持什么表级权限、纯读的 poll/wait_check 是否也授 `v13_recall`——全部未定。

4.7 **锁序叠加备注**（实查后降级，非阻断项）：`v13_cancel` 对子树按 `session_id` 序加锁（:181-216），与 CE「先锁 root `sessions` 行」的前置锁叠加后，在现有调用图中未构造出环（子 run 的 T1/T2 不反向锁父行）；但 §2.6/§2.7 揭示的级联语义应在 README 记一笔，防后续改动成环。

4.8 **可测试性接缝缺席**：崩溃注入点（claim 后、T2 前杀 worker 以验证 unknown 墙与 archive 分离）、LISTEN 丢通知的模拟、多 run 并发 steer/cancel 的竞态编排——导出矩阵部分覆盖（§1.6），计划随矩阵一并丢失。

---

## 5. 其答案将实质改变设计或实施顺序的问题

5.1 **steer 是否复活终态 run？** 导出=是，计划=未定。若「是」：cancel 须补 `sessions.status` 终态写入、§3.1 括注修正落地、测试矩阵加终态复活用例；若「否」：导出该分支正式作废，§6.2 增加 `already_terminal` 拒绝。影响 steer、cancel、publish 三个函数与 W3/W4 顺序。

5.2 **六动词是否需要 tools 行 / sql-route 可达？** Stage 41 删除后其 tools 行与 `controller` 路由策略一并消失（导出与 prompt 关键发现 6 均点名此先例）。若需要：v13_ce_run.sql 须携带独立 CE whitelist（不复活 `controller` policy），门禁须加目录断言；若不需要：写明六动词仅宿主直调。影响 W3 的文件内容与测试面。

5.3 **迟到/关闭回执的底层 effect 是否同事务结算？**（§2.2）「是」→ unknown 墙只覆盖真崩溃、`archived_stale` 不再砖化会话；「否」→ 必须给出会话级 unknown 的恢复出口，否则一次 steer-during-IO 即永久锁死。直接决定 accept_receipt 分支 C/D 的形态。

5.4 **延迟绑定与排队 `admit_tool` 的触发点放在哪里？**（§2.3/§2.4）方案甲：accept_receipt 归档/结算分支在同一 T2 内绑定并入队下一条 pending operation——单活跃槽位连续、任何 IO 恒有 claimed+lease 保护，同时消除 §2.3 与 §2.4 整个矛盾族；方案乙：worker 显式二段调用 admit。甲显著更简，但把绑定逻辑收进 SQL；答案改变 accept_receipt 与 CeWorker 两者的结构。

5.5 **连续性机器（`registration_generation`/`owner_generation`/`'expired'`/`related_follow_up`/`unrelated`/`superseded`）：本里程碑补生产者动词，还是声明 reserved 留缝？** 答案决定 wait_check 分支可达性声明、README 措辞与测试断言的存在性。

5.6 **interaction 是纯 CE 对象还是必配底层 human effect？**（§4.4）决定 respond 第 5 条与 publish_snapshot 的形态、human 通道测试是否存在、以及 `interaction_ref` 映射落在哪一层。
