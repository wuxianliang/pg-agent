# v13 长循环 Phase B 计划证据（2026-09-29）

本文只记录本规划轮为写 `docs/plans/v13-long-loop-phase-b-plan-2026-09-29.md` 而重读的活体行。不是 stage 验收，不是产品绿，不是任何 gate 的通过证明。裁决以 Phase 0 计划为准。本文不改写 Phase 0，也不改写已接受的 Phase A 计划。

## 1. 命令

本规划轮没有跑 stage gate，没有跑 Phase 0 探针，没有调用真实 provider，没有 `uv run`，没有 `UV_FROZEN=1`。

没有测试输出，没有退出码可以冒充 stage 通过。计划第 5 节的两条命令都没有跑。

导航是 RepoPrompt 的只读搜索与按行读取。那些调用不是 gate。

## 2. 本轮重读

行号是本轮读到的。搜索只用来定位，随后能读到的行才写入计划。没读完的函数不写成已核。

| 文件:行 | 读到的事实 | 计划里的用法 |
|---|---|---|
| `v13/spawn/v13_spawn.sql:94-133` | `v13_llm_tool_calls` 只接受对象键 `args`、`id`、`name`；名字必须是 `spawn_subsession`；args 键必须只有 `task`。否则 RAISE `v13: tool_calls shape` | 不把 edit/write/bash 送进该函数，不改这几行 |
| `v13/spawn/v13_spawn.sql:246-256` | `tool/call` 守卫同样只接受 `spawn_subsession` 与 args 键 `task`，任务长度 1 到 1024 | 不改守卫，不持久化工作区工具为 `tool/call` |
| `v13/acl/v13_acl.sql:408-426` | llm 成功且 `p_result` 含 `tool_calls` 时调用 `v13_llm_tool_calls`，成功后写 `tool/call`。tool 成功时 `:415-418` 写 `tool/result` | 工作区提案不得放进 `tool_calls`。`tool/result` 是既有写入，不新增种类 |
| `v13/acl/v13_acl.sql:381-386` | harness 校验包在 `v13_is_harness_tool` 内。本轮没有重读谓词体 | 工作区工具不得标成 `harness_turn`。谓词体沿用 Phase A 证据，本轮不另称已读 |
| `v13/schema/v13_core.sql:99-112` | effect kind 闭集是 `judge|tool|llm|context_refresh|human`。status 含 `ready`、`claimed`、`succeeded`、`failed`、`unknown`、`cancelled`。没有 `completed` | 打开者使用已有 `tool`。不发明第六种 kind |
| `v13/schema/v13_core.sql:210-264` | 较早的 `v13_enqueue_effect` 在策略缺 kind 时 RAISE；插入时不写 status；不写 `tool/call`；不调用 `v13_send_work` | 计划要求实现确认加载后的正文仍是 control 版的这一形状。本文不替换该函数 |
| `v13/control/v13_control.sql:902-939` | control 版 `CREATE OR REPLACE`。先查未消费 cancel 与 harness 请求，再按同一身份去重。插入同样不写 status，不写 `tool/call`，不调用 `v13_send_work` | 打开者调用这一份，不复制，不替换 |
| `v13/schema/v13_core.sql:267-294` | `v13_claim` 只更新 `status='ready'` 的一行，全局池，`SKIP LOCKED`。注释写明 claim 是 `attempt_no` 的唯一递增点，并同时 `fence=fence+1` | 打开者不调用它，不在自己的 UPDATE 里递增 `attempt_no` 或 `fence` |
| `v13/schema/v13_core.sql:297-306` | 5 参 `v13_complete(p_effect, p_attempt, p_fence, p_status, p_result)` 的函数头。函数体没有读完 | 不得把这一头写成已经核对过的「显式 NULL actor」包装。那条包装 Phase A 指向 acl `:459-469`，本轮未读 |
| `v13/govern/v13_govern.sql:1090-1124` | `WHEN 'sql'` 在事务内 `EXECUTE` handler，并把 effect 写成 `succeeded` 或 `failed`，成功时写 `tool/result` | 不把 edit/write/bash 注册成 sql handler |
| `v13/govern/v13_govern.sql:1137-1168` | `WHEN 'tool'` 调用 `v13_enqueue_effect` 后调用 `v13_send_work`，会话改为 `waiting`，返回 `waiting`。选择条件在 `:1137` 之前，本轮没有读到那一段 | 不得声称已经 `claimed` 的行不会进入这臂。那是开工重读 |
| `v13/govern/v13_govern.sql:764-773` | 这段在 `v13_unconsumed_cancel` 分支内。存在 `claimed` 行时把会话留在 `waiting` 并返回。它不取消 `claimed` 行 | 不得把 `:773` 写成「任何 claimed 行都挡住 advance」或 `WHEN 'tool'` 的过滤器 |
| `v13/read_tools/README.md:62` | `head -c` 仍是 51200。同一段还写到 `1.0MB` 的格式化 | 结果文本帽用 51200。不是文件字节帽。实现时必须重读；本轮读到的就是这个数 |
| `docs/designs/v13-tool-ports.md:208-221` | TP-ADMIT-1 第 10 条要求新口岸零 SQL、零 `SQL_LOAD_ORDER`、零受保护路径改动 | 与本期具名 SQL 冲突。计划第 2 节点名，不改这份设计文档 |
| `v13/**/*.sql` 搜索 `NEW.type = 'tool/result'` | 零命中 | 不是「complete 一定接受任意 jsonb」的证明。计划因此保留 ASK_USER 停点 |

同轮还读了已接受的 Phase 0 计划 §5、§7、§9，以及 Phase A 计划 §3、§5.8、§6、§7、§8。那些是计划文本，不是活体行。调查 G1 行在 `docs/investigations/v13-long-loop-workflow-borrowing-gap-2026-09-28.md:199-210`。调查不是权威。

四个计划中的新函数名 `v13_workspace_policy`、`v13_tool_effect_open`、`v13_tool_result_accept`、`workspace_tool_subset` 在 `v13/` 与 `docs/` 搜索为零命中。这只说明本轮没搜到，不是产品库已核对。

## 3. 本轮未读

不得把下列各项写成已核：

- `v13_advance` 在 `:790-829` 与 `:1090-1168` 之外的完整正文，以及它如何选择 `WHEN 'tool'`。
- `v13_send_work` 的函数体。
- `v13_recover_idle` 与 requeue 是否回收 `lease_until = infinity` 的 `claimed` 行。Phase A 证据读过 recover_idle 不 INSERT effect。本轮没有重读该函数。
- acl `:459-469` 的 5 参包装。计划只引用 Phase A 已接受的句子，并要求实现重读。
- `v13_complete` 对非 harness 工具结果 jsonb 的全部拒绝条件。
- effect 状态触发器，以及 `claimed` 且 `attempt_no=0` 是否被拒绝。
- `v13_plan_gate` 的函数体。它是 Phase A 计划中的名字，活体里还没有。
- `v13_reject_bad_harness_request` 的触发条件。
- `tools` 表对 handler 为空的行是否允许 complete。
- human_pending 的活体谓词全文。计划里的三状态句子是开工前的句子，不是已核对的活体谓词。
- V11、席位常数、产品角色、stannum、`v13_spawn_owner` 的 CREATE。
- `v13/read_tools/test_read_tools.py` 的 `TOOL_ROWS` 原文。本轮只读到 README 与目录。形状仍按 Phase 0 §5 与 Phase A：实现时重读，本期不重插那四行。

## 4. 与已接受计划的关系

没有发现需要改写 Phase 0 或 Phase A 的内部矛盾。调查与这两份计划的冲突写在 Phase B 计划第 2 节，本文不跟随调查。

本轮没有改 Phase 0 计划，没有改 Phase 0 证据，没有改 Phase A 计划，没有改 Phase A 证据，没有改 `v13/`，没有改 `v13/load.py`。

Oracle 初稿 group `7541D674-F1D1-4F61-9B98-4FC555D79D9C`。grok chat `new-chat-9C1C79` 完成了一份草稿。codex chat `new-chat-oracle-2-9A4136` 返回 provider 402。那不是内容分，不是 P0=0，不是 P1=0。kimi chat `new-chat-oracle-3-5ADF99` 的输出在设计节截断。它建议的 `workflow_template` version 2 没有写入计划。导出路径 `prompt-exports/oracle-plan-2026-09-29-041923-new-chat-9c1c79-a8fd.md` 只是本地溯源，不是接受条件。

pair 相对 grok 草稿改了的要点，避免把未读句子写成事实：

- 不在打开者里递增 `attempt_no` 或 `fence`。
- 不把 `v13/govern/v13_govern.sql:773` 写成通用派发过滤器。
- 打开者在 `v13_plan_gate` 为假时拒绝，避免无计划仍创建 effect。
- 不把子集放进 `workflow_template` version 2。
- 路径帽、argv 帽、find 深度不用 32 冒充 A3 库存帽，也不写未读席位常数 8 或 64。计划里写成父可退回的 4、4、4。
- bash 动词收成 `mkdir`、`rm`、`cp`、`mv`。不把 `diff`、`stat`、`wc` 放进 exec 名字下面再声称只读标签可以借用。
- 写明本期不写 `turn/material_spent`，不声称配额已扣。

这些是计划选择，不是已跑测试。

## 5. 审核尝试

选择里后来有本计划与本证据，但两次 review 的 Oracle 上下文仍只有 Phase 0 与 Phase A。那两次没有内容分。

| group | 结果 |
|---|---|
| `7541D674-F1D1-4F61-9B98-4FC555D79D9C` | 初稿。grok `new-chat-9C1C79` 完成。codex `new-chat-oracle-2-9A4136` 是 402。kimi `new-chat-oracle-3-5ADF99` 截断 |
| `1DD4FE5E-88C5-44F7-9C6B-C123C07460C3` | 未评分。文件不在上下文。codex 402 |
| `58480F84-6C96-40A6-BE87-0E25B90A5C7E` | 未评分。文件不在上下文。codex 402 |
| `3A7B0D9A-1E40-473C-89D2-A045ED9129F2` | 对消息里的合同摘要评分，不是对选择中的全文。grok `new-chat-26C712`：P0=0，P1=4。kimi `new-chat-oracle-3-E98486`：P0=0，P1=3。codex `new-chat-oracle-2-1A5D7C` 是 402，不是内容分 |

402 不是 P0=0，不是 P1=0，不是通过。本文件不把冻结检查写成已过。

摘要里已经在全文中的句子，没有再改成另一套。写进计划的处置：

- 打开者在 `v13_should_run` 为假时零写。不把这写成拒绝一切 advance，不因此调用结算 advance。
- 成功接受之后不调用结算 advance 去写 `turn/material_spent`。那是 B5。父若要求收据，停。
- 驱动器 Python 禁止 `UPDATE effects` 与 `UPDATE events`。
- `lease_until` 用已有列，不 `ALTER`。
- 同一棵树先锁根，用来串起检查再插入。
- 工作区 effect 不绑 todo，不归档。绑定若要求改 advance，停。
- `symlink_escape` 与 `workspace_not_repo` 的通过条件写进断言括号。

父复审必须读计划全文。摘要评分不是全文通过。

## 6. 父复审后的文本修补

group `CB5A3F78-D8C7-4E39-A232-051926355190` 不是接受。本轮没有调用 Oracle，没有跑 gate，没有调用 provider，没有提交。只改了本证据与 Phase B 计划。

为第 5 项重读了活体 `should_run`，不是 gate：

| 文件:行 | 读到的事实 | 计划里的用法 |
|---|---|---|
| `v13/should_run/v13_should_run.sql:121-193` | `v13_should_run_gate` 的闭集 id 是 `human_pending`、`unknown_wall`、`unconsumed_cancel`、`duty_cycle`。`effect=block` 时才返回该 id | 存在未 stopped、非终态也可为假的 block，所以不删 `should_run` token |
| `v13/should_run/v13_should_run.sql:185-188` | `duty_cycle` 只在 `v13_triage_duty()=0` 且 effect 为 `block` 时返回 | 计划禁止用 `duty_cycle=0` 当夹具，也不新增 block id |
| `v13/should_run/v13_should_run.sql:195-201` | `v13_should_run(uuid)` 在 gate 返回 NULL 时为真 | 打开者只对根调用这个签名。不是这个签名就停 |
| `v13/should_run/v13_should_run.sql:207-209` | 种子里前三个 id 是 `block`，`duty_cycle` 是 `shadow` | 种子下 `duty_cycle` 不会单独让 `v13_should_run` 为假 |

没有重读 `WHEN 'tool'` 的入口条件。计划因此不把 `:764-773` 的返回写成 `advance_does_not_dispatch_tool` 的通过，并要求实现重读后才能选定夹具。进不了该臂就 `ASK_USER`，不替换 `v13_advance`。

## 7. 第二轮父复审后的文本修补

group `09912B08-450D-45F4-92D0-FF92AA9D7C59` 不是接受。本轮没有调用 Oracle，没有跑 gate，没有调用 provider，没有提交。

为取消锁序重读了活体 `v13_cancel`，不是 gate：

| 文件:行 | 读到的事实 | 计划里的用法 |
|---|---|---|
| `v13/acl/v13_acl.sql:176-186` | 先按 `session_id` `FOR UPDATE` 会话 | 接受函数先锁会话 |
| `v13/acl/v13_acl.sql:207-214` | 再按 `effect_id` `FOR UPDATE` effect | 然后锁 effect。不改这个函数 |

锁序能从这两处说出，所以取消检查写进 `v13_tool_result_accept`，不改 stage 1–29。若实现发现必须改 `v13_cancel` 才能沿用该序，计划要求停，不把竞态写成已闭合。驱动器不以 SELECT 充当 `status`、`result` 或这道取消检查的来源。

## 8. 第三轮父复审后的文本修补

group `3B661CBF-C5A8-4813-9EFF-2FC335FFF6ED` 不是接受。本轮没有调用 Oracle，没有跑 gate，没有调用 provider，没有提交。没有新的活体行重读。

写进计划的处置：打开者不调用 `v13_complete` 与 `v13_plan_commit_entry`；5 参 complete 只在接受函数的后一事务；`.v13tmp-` 只留给适配器；忙扫描按规范绝对根加相对段比较，不因根字符串不同就跳过；`not_single_tree` 只在回滚事务里造第二根。

## 9. 第四轮父复审后的文本修补

group `3BB74A18-CE83-42D6-B241-1C5F2579B965` 不是接受。本轮没有调用 Oracle，没有跑 gate，没有调用 provider，没有提交。没有新的活体行重读。

写进计划的处置：突变前 no-follow 再验；允许名单只是测试配置，IO 前核对 device 与 inode；特殊节点在读写前拒绝；副作用前是 `io_error`，副作用后不确定是 `ambiguous` 且不交给接受函数当失败；本 gate 只用已有帽内的夹具，不新增政策键。

## 10. 第五轮父复审后的文本修补

group `07A20248-32B7-4851-A22B-D5C1609AD8D2` 不是接受。本轮没有调用 Oracle，没有跑 gate，没有调用 provider，没有提交。没有新的活体行重读。

写进计划的处置：确定的副作用前失败才交给接受函数，并带具体 token；`ambiguous` 不调用接受函数；`byte_length` 是全长，恰好等于帽则 `truncated=false`；空的深度受限 find 仍是 `depth_limited=true`。

## 11. 第六轮父复审后的文本修补

group `BC2EF13C-DC4A-4EB0-9292-62F1003B7777` 不是接受。本轮没有调用 Oracle，没有跑 gate，没有调用 provider，没有提交。没有新的活体行重读。

写进计划的处置：哈希检查不是 CAS，只覆盖受控夹具；名字相等不一致则停；接受函数用 `v13: workspace result: canonical` 拒绝畸形结果。

## 12. 第七轮父复审后的文本修补

group `D8C4093E-0981-4688-867A-44217098AE7E` 不是接受。本轮没有调用 Oracle，没有跑 gate，没有调用 provider，没有提交。没有新的活体行重读。

写进计划的处置：打开者事务必须是 `READ COMMITTED`；`ambiguous` 不要求目标字节未知；JSON null 的 `edit.new` 在打开者拒绝。
