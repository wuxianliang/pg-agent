# v13 长循环 Phase B 计划（2026-09-29）

**状态：合同复审 group `6635A3D8-FFAE-4080-85DE-4838F5890E58`，完成的 grok `new-chat-38F7DF`、codex `new-chat-oracle-2-754385`、kimi `new-chat-oracle-3-2A0A06` 三路均为 P0=0、P1=0。P2 不阻挡接受。未实现。未跑 gate。尚未提交。** 本规划轮没有改 `v13/load.py`，没有改 stage 1–29，没有改已接受的 Phase 0 / Phase A 计划，没有改指纹函数，没有改 fanout SQL，没有调用真实 provider，没有跑下面任何一条 gate。计划合同已被上述复审接受。运行时未实现。不得按本文开工实现，不得宣布产品可用。Fake 退出码 0 不是产品可用，也不是 Phase A 的 `real_authorized_exit_0`。

权威顺序：本轮用户范围；Phase 0 `docs/plans/v13-long-loop-plan-2026-09-28.md` §7 与 §9；已接受的 Phase A 计划 `docs/plans/v13-long-loop-phase-a-plan-2026-09-29.md`（尤其 §3.2、§5.8、§6、§7.5、§7.6、§8）。调查不是权威。冲突时按这个顺序，并在第 2 节点名。

本文只填 Phase B 的空位：工具执行 G1，加上 C2 的子集交付。它不是 Phase A read 注册的再写一遍。父可以退回第 4 节的选择。退回前不得另写一套控制面，不得私自加第二份 `CREATE OR REPLACE v13_advance`。

初稿来自 Oracle group `7541D674-F1D1-4F61-9B98-4FC555D79D9C` 的 grok lane（chat `new-chat-9C1C79`）。那不是接受。codex lane `new-chat-oracle-2-9A4136` 是 provider 402，不是内容分，不是通过。kimi lane `new-chat-oracle-3-5ADF99` 中途截断；它建议把子集放进 `workflow_template` version 2，本文不跟随。pair 按活体重读改了 grok 初稿里会撞活体不变量的几处，见第 4.5 节与证据文档。

重读行记在 `docs/reviews/v13-long-loop-phase-b-plan-evidence-2026-09-29.md`。该文件不是 gate 通过证明。

## 1. 状态

交付物是这一份候选计划。运行时不在本轮。B 仍未审核。C/D 仍是 Phase 0 §9 的未审核占位。本文不启动 Phase C。

Phase A 已经独占的对象，本文不重做，也不替换：

- 子 read 前缀，以及那一份 `CREATE OR REPLACE v13_advance`。它只在 `plan_arm`。Phase B 的新 SQL 与新 Python 不得再出现这个替换。
- `workflow/pointer` 与 `v13_child_pointer`。生产调用者仍只有将来的 `v13/real_chain/chain.py`。Phase B 驱动器不调用它。
- 归档生产者。十二步链的 `done` 不由本期脚本触发。
- `read_file_py` 以及另外三行 read 的装载 DML。不重新 INSERT，不调用 `v13/read_tools/setup_db.py`，不把 `read_tools/` 加进 `SQL_LOAD_ORDER`。
- `workflow_template` version 1。不 UPDATE，不加 version 2。
- `real_chain` 的 `deny_edit_write_bash`。Phase B 用另一份脚本。不编辑 `v13/real_chain/**`，不编辑 `v13/loop_driver/**`。

## 2. 优先级与冲突

1. 本轮用户决定：Phase B 只做工作区工具执行 G1，加上 C2 子集交付。
2. Phase 0 的用户决定与 T0–T7。本文引用，不改写。
3. Phase A 已写死的合同。本文消费，不改写。
4. 第 4 节的 Phase B 选择。父可退回。
5. 调查。与上面冲突则调查作废。

| # | 冲突 | 本文 |
|---|---|---|
| 1 | 调查切片 2 把 human\|reject、口岸合同版本、worktree merge、C5、evidence validator、R5/R6、artifact hash、lease 续租并进 G1 | Phase 0 §7 的 G1 是工作区工具面。这些项不在 Phase B。不建审批引擎，不升 `docs/designs/v13-tool-ports.md` 的版本，不交付 worktree merge，不实现无人值守 skip |
| 2 | 同文件把 explore 读成可成功的只读档，并写缺省 `pair` | Phase 0 T1.5 与 Phase A：explore 维持 RAISE `v13: explore spawn`。缺省不隐式变成 `pair`。Phase B 不新增这个缺省 |
| 3 | `docs/designs/v13-tool-ports.md` TP-ADMIT-1 第 10 条要求新口岸零 SQL、零 `SQL_LOAD_ORDER` | 工作区工具不能进入 `tool/call`，驱动器又不能 INSERT，所以准入必须是新 stage 的具名 SQL。这与该条冲突，以本轮用户要求与 Phase 0 的「PG 是唯一控制语义 owner」为准。实现提交不改该设计文档，不改 `v13/read_tools/**`。适配器不是第五套语言平面 |
| 4 | Phase A §5.8：`allowed_tools` 是首期真链的驱动器允许名单，不是第二套 SQL 门，也不是 Phase B 目录 | Phase B 选择：新政策行拥有本期六个工具的准入。驱动器 Python 不保留第二份名单。这不是改写 §5.8。真链脚本仍然拒绝 edit/write/bash。四个 read 名字不进入这行政策 |
| 5 | 调查里的计划门进 `should_run`、`plan/superseded`、Fake-only 分期、`scheduler/applied`、skip 解卡、64/8、第二状态源、看见 `workflow_id` 就 spawn | 继续按 Phase A §2 作废。Phase B 不碰 |

## 3. 范围

### 3.1 在 B 内

- 工具名 `edit`、`write`、`bash`。只出现在 Phase B 自己的脚本里。
- 模型可见输出的截断，以及 `effects.result` 上的显式 `truncated`。
- 同一规范工作区路径上的文件互斥。不建新表，不加列，不建索引。
- `grep`、`find`、`ls`。它们是工作区表面的只读工具，不是 Phase A 那四行 read 的再注册。
- C2 子集交付：`read_only` 丢掉 write/exec；`workspace_edit` 可以放行 edit/write/bash。explore 继续是失败的 spawn，不是成功的只读代理。

确定性 gate 用进程内 FakeLLM 与进程内适配器。不打开网络。一库一树，一个 goal。除 `not_single_tree` 这一条负例外，测试库不得出现第二棵树。那条负例只能在会回滚的事务里，通过已有具名函数再建一个根；打开者 RAISE `not_single_tree`，零工作区 effect；该事务内没有工作区 IO。回滚之后仍是一棵树。其余夹具保持一棵树。不改 fanout SQL。

### 3.2 不在 B 内

- B3、B4、B5、D1、D2、D3、G3、G4、无人值守 skip、PC-4、多 goal 公平、并发帽、soak、cadence ACK。
- worktree merge、human\|reject 审批引擎、port 合同版本、第二状态源、新表、工作流引擎、v14/v15、外层 wrapper。
- 第二份 `v13_advance`。第二份 `v13_enqueue_effect`。对 `v13_llm_tool_calls` 或 `tool/call` 守卫的加宽。
- 把 edit/write/bash 注册成 `sql` handler。活体 `WHEN 'sql'` 在事务内执行 handler 并立刻写成 `succeeded`（`v13/govern/v13_govern.sql:1090-1124`）。那会把文件系统 IO 放进事务。
- 清掉、续租或标成 `unknown` 的崩溃 `claimed` 行。那是 G4。
- 跨外部 IO 持有 advisory lock，当作第二本账。
- 真实 provider、`V13_REAL_PROVIDER_AUTHORIZATION`、stannum GRANT、请求 JSON 或库内的 API key。
- 修改指纹函数、`judgment_templates`、stage 1–29 字节、已接受的 Phase A 计划。
- 为工作区工具补写 `turn/material_spent`。收据写者仍是 harness。B5 在 Phase C。本期不得声称这次 complete 已经扣了 material。

## 4. Phase B 选择

父可整组退回。退回前实现停。这些选择不是 Phase 0 裁决，也不是对 Phase A 文本的修订。

### 4.1 为什么不走 `tool/call`，也不再替换 advance

活体 `v13_llm_tool_calls`（`v13/spawn/v13_spawn.sql:94-133`）与 `tool/call` 守卫（同文件 `:246-256`）只接受 `spawn_subsession`，args 键只有 `task`。`v13_complete` 在 llm 成功且结果里有 `tool_calls` 时调用该函数（`v13/acl/v13_acl.sql:408-410`），然后写 `tool/call`（`:422-426`）。把 `edit` 放进这个键会 RAISE。加宽这两处就是改 stage 1–29。本文不做。

Phase A 的子 read 能避开这条窄路，是因为它写在那一份 advance 替换的前缀里，并且不写 `tool/call`。那一份替换已经预定给 `plan_arm`。Phase B 若再 `CREATE OR REPLACE v13_advance`，就违反「只有一份」。做不到下列合同就停并 `ASK_USER`，不得加第二份替换来换退出码 0。

因此工作区 effect 的唯一打开者是新 stage 里的 `v13_tool_effect_open`。驱动器 Python 不 `INSERT INTO effects`，不 `INSERT INTO events`。它调用这个函数。函数在锁内决定接受或 RAISE。持久提案是 effect 的 `request`，不是 `tool/call`。

这不是第二条循环，也不是工作流引擎。它不写 plan/todo，不调用 `v13_spawn_subsession`，不调用 `v13_send_work`。它可以读 `v13_should_run`，但只用来拒绝本次打开，不制造新的 block id。它只为六个工作区工具名打开 `kind='tool'` 的 effect。

### 4.2 目录与追加

| 顺序 | 目录 | SQL | 键名 |
|---|---|---|---|
| Phase A 尾部之后 | `v13/workspace_admit` | `v13_workspace_admit.sql` | `workspace_admit` |
| 其后，无加载键 | `v13/workspace_exec` | 无 | 不分配 |

Phase A 尾部顺序不变：`plan_contract`、`plan_read`、`plan_arm`、`loop_driver`、`workflow_bind`、`real_chain`。只允许在那时的表尾追加 `workspace_admit`。整数值是实现当时的「当前最大值 + 1」。本文不分配 30、31、32。禁止插到 `real_chain` 前面，禁止重排，禁止插进 1–29。

`workspace_exec` 不制造空 SQL，不占键。它的测试装到 `workspace_admit` 为止。若实现发现它必须有 SQL，停并 `ASK_USER`。不得顺手再替换 `v13_advance`。

本规划轮不改 `v13/load.py`。实现时若 Phase A 六个键还不在表尾，停。Phase B 不代替 Phase A 去补那些键。

依赖，与尾部顺序分开：

- `workspace_admit` 的加载前缀含 1..29 与 Phase A 尾部直到 `real_chain`。`v13_tool_effect_open` 调用活体 `v13_enqueue_effect` 与 Phase A 的 `v13_plan_current`，不调用 `v13_complete`。5 参 `v13_complete` 只由 `v13_tool_result_accept` 调用，在打开者提交并且文件系统 IO 结束之后的另一个事务里。驱动器不调用 `v13_complete`。不调用 `v13_plan_commit_entry`。工作区 effect 不是计划提交。不依赖计划臂去创建工作区 effect。不调用 `v13_plan_gate`：Phase A 没把这个布尔定义成「有当前计划」。
- `workspace_exec` 依赖 `workspace_admit` 已装。不依赖十二步链脚本。

### 4.3 函数

撞上已有同名函数就停，不静默改名。本规划轮在 `v13/` 与 `docs/` 搜索这三个名字，零命中。实现时再搜一次。

| 名字 | 性质 | 作用 |
|---|---|---|
| `v13_workspace_policy()` | STABLE | 读 `workspace_tool_subset` version 1。零写 |
| `v13_tool_effect_open(uuid, uuid, text, text, text[], jsonb)` | VOLATILE | 唯一工作区 effect 打开者。参数是 `p_actor`、`p_session`、`p_label`、`p_workspace_root`、`p_allowed_roots`、`p_request` |
| `v13_tool_result_accept(p_effect_id uuid, p_attempt_no int, p_fence bigint, p_status text, p_result jsonb)` | VOLATILE | 锁行校验后调用 Phase A 点名的 5 参 `v13_complete` |

打开者不调用 `v13_advance`，也不调用 `v13_complete`。5 参 `v13_complete` 只由 `v13_tool_result_accept` 调用，在打开者提交并且文件系统 IO 结束之后的另一个事务里。驱动器不调用 `v13_complete`。

打开者返回闭集不含重试次数。驱动器对外返回可以带 `attempts_used`。返回闭集，与第 4.5 节第 10 步、第 4.11 节同一句：`effect_id`、`attempt_no`、`fence`、`replayed`、`tool`、`status` 每次都在。`result` 只在 `replayed=true` 且 `status=succeeded` 时等于已存储的 `effects.result`，否则为 JSON null。首次打开返回 `replayed=false`、`status=claimed`、`result` 为 JSON null，以及第 14 步更新之后的 `attempt_no` 与 `fence`。只有这一次返回可以跑适配器。`replayed=true` 且 `status=claimed` 是已有行，不授予执行，不跑适配器，不调用接受函数。重放返回已有行，零新行。驱动器不以 SELECT 取得 `status` 或 `result`。

### 4.4 C2 政策

新行，不碰 Phase A 的冻结行：

- `v13_policies.name = workspace_tool_subset`
- `version = 1`
- `active`
- 不存在则 INSERT
- 已存在且 value 的 jsonb 相等则跳过
- 已存在且不相等则装载 RAISE，不 UPDATE
- 不得有目标为 `workflow_template` 的 `UPDATE`

value 闭集，键必须逐个出现，多一个键装载 RAISE：

- `schema_version`：1
- `result_text_cap_bytes`：51200
- `paths_cap`：4
- `argv_len_cap`：4
- `find_depth_cap`：4
- `tool_open_attempts`：2
- `bash_verbs`：字节序数组，恰好 `cp`、`mkdir`、`mv`、`rm`
- `labels`：对象，键恰好 `read_only` 与 `workspace_edit`

`labels.read_only` 与 `labels.workspace_edit` 各自是对象，键恰好 `admits`。`admits` 是字节序数组。

`read_only.admits`：`find`、`grep`、`ls`。

`workspace_edit.admits`：`bash`、`edit`、`find`、`grep`、`ls`、`write`。

幂等跳过用 jsonb 相等。任一层多键、缺键、数组未按字节序，装载 RAISE，不 UPDATE。

禁止子串只扫政策 value，不扫函数正文。value 不得包含 `explore`、`pair`、`read_pi`、`read_file_swift`、`read_file_py`、`read_duck`、`spawn_subsession`。函数正文可以写出 `read_file_py`，以便拒绝再打开它。四个 read 名字留在 Phase A 的 `allowed_tools`。本期不把它们再列进 value，也不为它们打开 effect。打开者见到这四个名字或 `spawn_subsession`，RAISE `not_this_opener`，零写。

51200 来自已读的 `v13/read_tools/README.md:62`：`head -c` 仍是 51200。单位按该行的字节帽使用。实现时重读这一行。不是 51200 就停，不得改用别的数。这是结果文本帽，不是文件字节帽，也不是 A3 的 1024 文本帽。两套帽不要合并。

`paths_cap=4`、`argv_len_cap=4`、`find_depth_cap=4` 是本期种子。数字 4 与 Phase A 已接受的前沿 item 帽同数，但不是那个谓词。不写 8，也不写 64：那两个数是未读的席位常数，本期不拿它们当帽。父可退回这三项。`tool_open_attempts=2` 与 Phase A 规划尝试上限同数，但是进程内重试用的另一件事，不是规划写者的重试。

`bash` 整名属于 exec。`read_only` 拒绝 `bash`，即使动词看起来只读。不把 `diff` 借道放进只读标签。

标签由 `p_label` 传入，且必须等于 `p_request.label`。不等则 RAISE `label_mismatch`，零写。工具是否被允许，只由这行政策决定。驱动器 Python 不得再写一份名单。`p_label` 为 `explore` 时 RAISE `explore_not_a_tool_label`，零 effect，不得映射成 `read_only`。不是 `explore`、`read_only`、`workspace_edit` 的未知标签 RAISE `canonical`，零写。explore spawn 的失败消息仍是 `v13: explore spawn`。本期测试不把这条 RAISE 改成成功。

### 4.5 打开者

这是 Phase B 选择，不是把 T1.4 套到普通 tool complete 上。结果接受仍走 Phase A 已写的 5 参 complete：显式 NULL actor，不因此要求 operator。打开者本身不是 complete。

无人值守打开未授权。打开者的授权只允许 Phase A 规划写者那两类，并且只用于这个函数：显式 `NULL::uuid` 且 `v13_control_operator()` 为真；或非 NULL 且 `v13_control_authorized(actor, target)` 为真。根没有父，所以非 NULL 的根上打开恒拒。显式 NULL 且不是 operator：RAISE `auth`，零写。超级用户夹具不是产品角色证明。产品角色仍未闭合。父若退回这道授权，实现停，不得改成「谁都能打开」。

打开者事务必须是 `READ COMMITTED`。驱动器显式设置这个隔离级别。其它隔离级别在检查与写入之前拒绝，零写，token `v13: workspace open: canonical`。根锁不保证在每一种隔离级别下都能挡住并发准入。目标 effect 写在 `p_session`。测试库里那就是根。沿 `parent_session_id` 找到根。`FOR UPDATE` 先锁根，再锁目标。不新造列。在 `READ COMMITTED` 下，同一棵树的打开者都先锁这一个根。忙行上的 `FOR UPDATE` 只排序已有行的锁。这不是新表，也不是第二把业务锁。

锁内顺序，前一步失败则后面零写。会话终态与 stopped 先于同键重放。这不是 effect 终态。会话已停或会话终态上的重试 RAISE，不返回 `replayed=true`。effect status 为 `succeeded` 时仍返回 `replayed=true`。这与规划写者的重放先于停复不同。父可退回这个顺序。

1. 授权，如上。
2. 数据库里根会话多于一个：RAISE `not_single_tree`，零工作区 effect。根是 `parent_session_id` 为空的会话。这是本期的串行规则。不加 advisory lock，不建表。多根上的路径竞态留在 Phase D。负例只能在会回滚的事务里，由测试文件调用已有具名函数再建一个根；该事务内没有工作区 IO。回滚之后仍是一棵树。
3. 目标或根不存在，或 status 属于 `completed`、`failed`、`cancelled`：RAISE `terminal`。
4. 根或目标已 stopped：RAISE `stopped`。stopped 的事实与 `v13_goal_stop` 使用的是同一个，不新造列。实现时重读并把行号写入 README。对不上就停。
5. human_pending：实现时重读 hint / advance 的活体谓词，把行号写入 README。对不上就停。在重读之前，计划里的句子是：目标上存在 `kind='human'` 且 status 属于 `ready`、`claimed` 或 `unknown` 的 effect，则 RAISE `human_pending`。不 complete 那条 effect，不 skip，不建审批引擎。
6. 调用已有的 `v13_plan_current(根)`。函数不存在就停，不在本期 SQL 里再造一份。返回空则 RAISE `no_plan`，零写。不调用 `v13_plan_gate`。无当前 advancement 计划时不准打开。有计划但没有 selected todo 时仍可打开。父可退回这一步；退回前不得改成静默放行，也不得改去调用 `v13_plan_gate`。
7. 对根调用已有的 `v13_should_run`，不对子会话调用。签名不是一个 uuid 进、布尔出就停，不包新函数。返回假则 RAISE `should_run`，零写。不新增 block id，不用 `duty_cycle=0` 当夹具。本轮重读见证据：种子里 `human_pending`、`unknown_wall`、`unconsumed_cancel` 可以在根未 stopped、也非终态时让它为假，所以这个 token 与断言保留。`duty_cycle` 在种子里是 `shadow`，不拿它充作这次拒绝。这只拒绝本次打开。不因此写收据，不因此调用 `v13_advance`。不改 `should_run` 的政策 version。README 写明：这里不证明 material 已扣。
8. 读 `v13_workspace_policy()`，校验 `p_workspace_root` 与 `p_request`，见第 4.6 节。
9. 用活体 `v13_effect_id(p_session, 'tool', 规范请求)` 计算身份。规范请求由打开者写成，不是模型原文。不复制该函数。
10. 只处理已有行。重放比较的是打开者已经写进 `workspace_root` 的规范请求，不是模型原文。首次打开的返回只写在第 4.3 节和第 14 步。已有该 `effect_id`，且第 3、4 步的会话终态与会话 stopped 已经通过：同行 `tool_name` 与规范请求一致，且 effect status 为 `succeeded` 时，`replayed=true`，`result` 等于已存储的 `effects.result`，零新行。effect status 为 `claimed` 时 `replayed=true`，`result` 为 JSON null，不授予执行，不跑适配器，不调用接受函数。effect status 为 `ready`、`failed`、`cancelled`、`unknown`，或 `tool_name` 不一致：RAISE `effect_exists`，不调用 enqueue 的重挂分支。禁止把失败行弄回 `ready`。会话已停或会话终态上的重试到不了这一步。
11. 任一 status 的另一个 effect 已经使用同一 `attempt_key`：RAISE `effect_exists`，零写。合法复用只有第 10 步那种同一 effect、同 `tool_name`、同请求的重放。先前失败过的 `attempt_key` 配上不同请求，也是这一步，零写。
12. 第 4.7 节的互斥扫描。冲突则 RAISE `path_busy`。
13. 仅当第 10 步确认没有旧行时，调用活体 `v13_enqueue_effect`。实现先确认加载后的那一份仍是 control 版（`v13/control/v13_control.sql:902` 起）：插入时不写 status，表默认 `ready`，不写 `tool/call`，不调用 `v13_send_work`。本文不替换该函数。kind 字面是 `tool`，不是 `sql`。`p_tool` 是六个名字之一。它自己的 cancel 与 attempt-cap 异常原样传播。
14. 同一事务内只更新这一行：`status='claimed'`，`lease_owner='v13_workspace_opener'`，`lease_until` 按第 4.8 节。`WHERE effect_id = 返回值 AND status='ready'`。更新不到恰好一行则 RAISE，整笔回滚。

第 14 步不增加 `attempt_no`，也不增加 `fence`。活体 `v13_claim`（`v13/schema/v13_core.sql:267-294`）的注释写明 claim 是 `attempt_no` 的唯一递增点。本期不调用 `v13_claim`，不替换它，不在打开者里变成第二个递增点。首次打开返回 `replayed=false`、`status=claimed`、`result` 为 JSON null，以及第 14 步更新之后的 `attempt_no` 与 `fence`。只有这一次返回可以跑适配器。重放返回已有行，零新行。新行预期仍是 0 与 0，因为这次更新不递增这两列。若活体 CHECK、触发器或 complete 拒绝「`claimed` 且 `attempt_no=0`」，停并 `ASK_USER`。不得改 `v13_claim`，不得改 core，不得为此再替换 advance。

`v13_enqueue_effect` 的 INSERT 把行锁留到外层事务提交。并发 `v13_claim` 的 `SKIP LOCKED` 在提交前领不走这行。提交后 status 已是 `claimed`，而 `v13_claim` 只选 `ready`。这个句子是锁语义，不是已跑的测试。gate 只证明提交之后的那一次 `v13_claim` 不返回该 id。

打开者零 `tool/call`，零 plan/todo，不调用 `v13_send_work`，不调用 `v13_spawn_subsession`，不调用 `v13_child_pointer`，也不调用 `v13_plan_writer`。工作区 effect 不绑 todo，不归档。它不是 advancement 入队，也不把选中的 todo 改成 `done`。同一请求的再次打开走 `v13_effect_id` 重放。同一路径的另一笔走互斥。若产品要求必须绑定或归档，而那会要求改那一份 advance，停并 `ASK_USER`。不得在打开者里私自绑定。函数本身不 COMMIT。驱动器的这个事务里只有这一次调用，事务内没有文件系统 IO。接受函数提交之后，本期不调用结算 `v13_advance` 去写 `turn/material_spent`。那是 B5，留在 Phase C。父若要求本期必须有收据，停并 `ASK_USER`。驱动器不得 INSERT 该事件，也不得为此替换 advance。

本规划轮读到的 `v13/govern/v13_govern.sql:764-773` 只说明：在 `v13_unconsumed_cancel` 为真的分支里，存在 `claimed` 行会把会话留在 `waiting` 并返回。这不是「任何 `claimed` 行都会挡住 advance」，也不是 `WHEN 'tool'` 的过滤条件。落在这个分支上返回，不是 `advance_does_not_dispatch_tool` 的通过。`WHEN 'tool'`（`:1137-1168`）是否会再次派发已经 `claimed` 的行，本轮没有读完入口条件。实现必须重读并选出确实进入该臂、且该行已是 `claimed` 的一次调用。没有这样的合法单次调用，或该臂派发了 `claimed`、或调用了 `v13_send_work`：停并 `ASK_USER`。不替换 `v13_advance`。不把臂前返回算成退出码 0。

### 4.6 请求形状

`p_request` 是 jsonb。未知键 RAISE，零写。`schema_version` 不是 1 则同样拒绝。jsonb 相等仍是唯一相等运算符。数组序参与相等。调用者给出的 `paths` 必须已按字节序排好且无重复。打开者不替调用者排序，以免改掉 effect 身份。

模型请求的闭集键：`schema_version`、`tool`、`label`、`paths`、`attempt_key`、`payload`。出现 `workspace_root` 则 RAISE `canonical`，零写。工作区根不是模型字段。

- `tool` 是六个名字之一。不在这六个里、也不是四个 read 名字或 `spawn_subsession` 的值，RAISE `canonical`，零写。四个 read 名字与 `spawn_subsession` 仍是 `not_this_opener`。
- `label` 是 `read_only` 或 `workspace_edit`
- `attempt_key` 是小写带连字符的 uuid 文本
- `p_workspace_root` 与 `p_allowed_roots` 是测试夹具配置，不是模型数据，也不是生产根授权。本期不声称一般的生产根已经获准。它必须是允许名单里的一项。`/` 拒绝。仓库根不在测试允许名单里。SQL 只做字符串检查，不做 realpath。通过之后，打开者把这个根写进规范请求的 `workspace_root`，再算 `v13_effect_id`。模型改不了这个键。IO 之前再核对已打开根的 device 与 inode。路径被换掉则 RAISE `escape`，不操作。
- `paths` 长度 1 到 `paths_cap`。每个元素是相对路径：非空，不以 `/` 开头，无空段，无整段等于 `.` 或 `..` 的段，无 `\`，无 NUL，无尾斜杠。任一元素含 `/` 时，其每一级父段也必须已在 `paths` 里。打开者不补。缺了就 RAISE `canonical`，零写。模型请求的路径分量与 payload 操作数不得以 `.v13tmp-` 开头。只有适配器创建的那一个临时文件可以用这个前缀。模型用了就 RAISE `temp_namespace`，零写。
- 规范绝对根由测试配置在事务外提供，打开者只保存这个字符串，不调用 `realpath`。忙扫描不因为两个 `workspace_root` 字符串不同就跳过。比较的是「规范绝对根 + 每个声明的相对段」拼出的整段路径。`/tmp/ws` 加 `sub/file.txt` 与 `/tmp/ws/sub` 加 `file.txt`，若两个根都在允许名单里，是 `path_busy`。不另选「拒绝重叠根」那条规则。
- 列出工作区根本身不在本期。`paths` 禁止整段等于 `.`。
- 打开任何 effect 之前，夹具先核对文件系统的名字相等与数据库字符串比较一致：无大小写折叠，无把不同字符串收成同一个名字的 Unicode 别名。不一致则停，不得把 gate 报成通过。不靠 `realpath` 做这道核对。大小写折叠后段相等、但字符串不等的路径，以及前缀 `.V13TMP-`，都 RAISE `v13: workspace open: canonical`，零写。精确的 `.v13tmp-` 仍是 `temp_namespace`。不靠 `realpath`。

`payload` 按工具闭合：

| 工具 | payload 键 | `paths` 必须已经包含 |
|---|---|---|
| `write` | `path`，`content`（文本），`expected_sha256`（64 位小写 hex，或 JSON null） | 该相对路径 |
| `edit` | `path`，`old`（非空文本），`new`（文本，可空），`expected_sha256`（必须是 hex） | 该相对路径 |
| `bash` | `argv`（字符串数组，长度 1 到 `argv_len_cap`）。可选键 `expected_sha256`。`rm` 以及 `mv`、`cp` 的源操作数必须有它。`mkdir` 与必须尚不存在的目标不要它。其它未知键 RAISE | 声明的操作数，含 `secret.txt` 这种单段名。不预列内部临时名或 `find` 的子路径 |
| `grep` | `pattern`（非空固定字符串，不是正则），`path` | 那个文件，不接受目录 |
| `find` | `path`，可选 `name_fixed`（精确文件名，不是 glob） | 那个目录 |
| `ls` | `path` | 那个目录 |

`expected_sha256` 为 JSON null 只允许 `write` 新建：文件必须尚不存在。已存在的写操作要求整文件哈希匹配。没有追加，没有按偏移的局部写。本计划不设文件字节帽。51200 不得挪用成「写文件时悄悄截短」。需要列级上限才能放下请求时，先重读 `effects.request` 的类型。在父给出数字之前，不得发明文件字节帽。超大请求由活体 jsonb 自己的失败表现出来，不在本期包装成截断。

`bash` 不是系统 shell。`argv[0]` 必须属于政策 `bash_verbs`。政策是唯一名单。Python 里不得再抄一份。下列字面不得作为 `argv[0]`：`bash`、`sh`、`zsh`、`dash`、`python`、`python3`、`perl`、`ruby`、`node`、`env`、`sudo`、`xargs`、`find`、`grep`、`awk`。禁止键 `shell`、`cwd`、`env`、`stdin`、`command`。

`argv` 的每个元素要么是 `argv[0]`，要么精确等于声明的操作数，而该操作数必须已在 `paths` 里，包括 `secret.txt`。未声明的旗标拒绝。没有「其它元素是字面量」这条。`paths` 只列声明的操作目标及其父段，不预列内部路径。

父若要求 `/bin/bash`、`shell=True`、`subprocess` 或任意 execve，本节退回。自由 shell 守不住路径表。实现不得打开 shell 来换退出码 0。

### 4.7 文件互斥

不建表，不加列，不建索引，不把 advisory lock 持有到事务外。

忙行：`kind='tool'`，status 属于 `ready`、`claimed` 或 `unknown`，并且规范请求里有已保存的绝对根。没有这个根的旧 effect 不参与比较，包括 Phase A 的 `read_file_py`，除非实现重读发现它已经带同一键。不因为两个 `workspace_root` 字符串不同就跳过。本期不改 `plan_arm` 去补路径。若必须罩住 `read_file_py`，停并 `ASK_USER`。

比较的是规范绝对根加上每个声明相对段，逐段看前缀或相等。SQL 不调用 `realpath`，不建表。根由测试配置在事务外规范化后传入。`/tmp/ws` 加 `sub/file.txt` 与 `/tmp/ws/sub` 加 `file.txt`，两个根都在允许名单里时 RAISE `path_busy`。这与第 4.6 节是同一条规则，不改成拒绝重叠根。

前缀比较只发生在两个不同 effect 的声明路径之间。同一请求因为父段规则同时带上 `a` 与 `a/b`，不是 `path_busy`。两个 effect 之间，一段是另一段的逐段前缀，或两者相等，才是冲突。`a` 与 `a/b` 冲突。`a` 与 `ab` 不冲突。段本身 `a/b` 与 `a/c` 不是前缀关系。含 `/` 的声明目标必须把每一级父段都放进 `paths`。打开者不补。同一父目录下的两笔不同 effect 会因为父段相等而冲突。这是故意的粗锁。打开任何 effect 之前的名字相等核对见第 4.6 节。不一致则停，不得把 gate 报成通过。不靠 `realpath`。

内部路径不是声明目标，不必预列。`find` 可以走已声明目录的子路径，不跟随符号链接，子路径不必出现在 `paths`。`write` 与 `edit` 可以在已声明的父目录下创建一个临时文件，名字是 `.v13tmp-` 加 `attempt_key`。目标没有父段时，这个名字直接在工作区根下。它必须留在工作区根内，不得含 `..`，不得被模型改名。调用者不必把它写进 `paths`。跨目录 `cp` 仍只把两个父段和两个声明文件放进 `paths`。

扫描在打开者事务内进行，`ORDER BY effect_id`，对命中的忙行 `FOR UPDATE`，避免两个打开者锁序相反。范围是当前库里所有这类行，不按单个 `session_id` 过滤。本期测试库只有一棵树。多 goal 领用是 Phase D，本期不写那条查询。

路径互斥仍只看未终态。`attempt_key` 扫描覆盖一切 status，见第 4.5 节第 11 步。effect 终态 `succeeded`、`failed`、`cancelled` 不占路径。崩溃留下的 `claimed` 继续占路径。打开者不得清它，不得续租，不得把它改成 `unknown`，不得调用 `v13_recover_idle`。

SQL 比较的是字符串。worker 在 IO 时拒绝符号链接，见第 4.9 节。符号链接拒绝不是第二本账。

### 4.8 租约边界

开工重读 `v13_recover_idle` 与会把 `claimed` 收回 `ready` 的 requeue，把行号写入 `workspace_admit` 的 README。

- 若它们只回收 `lease_until` 已过期的 `claimed` 行，则第 14 步把已有列 `lease_until` 写成 `infinity`。该列在 `v13/schema/v13_core.sql` 的 `effects` 表上，本轮读到的窗口是 `:90-119`。不 `ALTER`，不加列。这是初始值，不是周期续租，不是 G4。崩溃行因此不会被这条回收领走，路径继续被挡住。
- 若它们无视租约，或会回收 `infinity` 或 NULL：停并 `ASK_USER`。不得改 stage 1–29，不得在驱动器里循环续租。

本期测试不调用 `v13_recover_idle`。装载本 stage 前后，`v13_recover_idle`、`v13_advance`、`v13_goal_fingerprint`、`v13_enqueue_effect`、`v13_llm_tool_calls` 的函数正文哈希必须相同。

### 4.9 结果、截断、进程内工具

`v13_tool_result_accept(p_effect_id uuid, p_attempt_no int, p_fence bigint, p_status text, p_result jsonb)` 与 complete 在同一事务。锁序与取消写者相同，不改 stage 1–29：先锁会话行，再锁 effect 行。活体 `v13_cancel` 先按 `session_id` 锁会话（`v13/acl/v13_acl.sql:176-186`），再按 `effect_id` 锁 effect（同文件 `:207-214`）。接受函数只锁这一行所属的会话，然后锁这一行。不得先锁 effect。然后在这把锁内调用 `v13_unconsumed_cancel`。为真则 RAISE `v13: workspace result: cancel`，不调用 complete，不把行标成 `succeeded`。这不是驱动器 SELECT。锁序若必须改 `v13_cancel` 才能说出，停并 `ASK_USER`，不把 `cancel_during_io_does_not_succeed` 写成已闭合。本规划轮能按上面两处说出锁序，所以检查放在接受函数里。

行要求 `kind='tool'`，`tool_name` 属于六个名字，`status='claimed'`，`lease_owner='v13_workspace_opener'`，`attempt_no` 与 `fence` 与参数一致。对不上则 RAISE `v13: workspace result: lock_mismatch`，不调用 complete，不把行标成 `succeeded`。

`p_status` 只允许 `succeeded` 或 `failed`。不接受 `unknown`。不接受 skip。通过锁检查之后才调用 Phase A 点名的 5 参 `v13_complete`。实现时重读 `v13/acl/v13_acl.sql:459-469`。与 Phase A 的「5 参即显式 NULL」不一致就停。本规划轮没有重读那 11 行。

`succeeded` 当且仅当 `ok=true` 且 `error_token` 为 JSON null。`failed` 只接受可完成的 worker 闭集：`hash_mismatch`、`exists`、`missing`、`escape`、`not_a_file`、`not_a_dir`、`edit_not_unique`、`bad_utf8`、`io_error`。此时 `ok=false`，且 `p_status=failed`。`error_token` 为 `ambiguous` 则 RAISE `v13: workspace result: ambiguous`，不调用 `v13_complete`。`over_cap`、`flag_inconsistent`、`lock_mismatch`、`cancel` 是接受函数自己的 RAISE，不授权 complete。结果里的 `tool` 必须等于行上的 `tool_name`。其它组合 RAISE，不调用 complete。

结果闭集：`schema_version`（1）、`ok`、`tool`、`truncated`、`depth_limited`、`byte_length`、`text`、`error_token`。`depth_limited` 是布尔。非 `find` 必须为 false。

帽是政策里的 `result_text_cap_bytes`，函数体内不另写一个散落的 51200。

截断谓词：`byte_length` 是完整原始输出的字节长度，SQL 信任它，不重测。`truncated = (byte_length > cap)`。`text` 只保留帽内的 UTF-8 前缀。达到帽之后停止累加 `text`，但继续累计字节数。总字节数大于帽才置 `truncated=true`。恰好等于帽则 `truncated=false` 并完成。`truncated` 为假时，`byte_length` 必须等于 `octet_length(text)`。对不上则 RAISE `flag_inconsistent`，不调用 complete，行保持 `claimed`。`octet_length(text)` 大于帽则 RAISE `over_cap`，不调用 complete，行保持 `claimed`，`result` 不变。SQL 不把超长文本切短后再存。`truncated` 只表示字节截断。对 `find`，完整输出是深度限制之后、字节截断之前的输出。深度帽用 `depth_limited`，不用 `truncated`。短的、因深度停下的 `find` 结果不是 `truncated`。`depth_limited=true` 且 `truncated=true` 只在 `byte_length > cap` 时合法。

空输出是 `text=""`，`byte_length=0`，`truncated=false`。`depth_limited` 独立：`find` 因深度帽停下则为真，即使没有匹配。非 `find` 保持 `depth_limited=false`。

`edit` 与 `write` 的 `text` 是短摘要：路径、写入后的字节数、写入后的 sha256。不是文件正文。文件可以长于 51200 字节。摘要仍必须低于帽。文件字节要么全量落地，要么调用失败且目标保持原字节。不得把文件截成 51200 来冒充成功。

`grep`、`find`、`ls` 的工具输出进 `text`。成功的 `bash` 用空输出形状：`text=""`，`byte_length=0`，`truncated=false`。

活体 complete 在 tool 成功时写 `tool/result`（`v13/acl/v13_acl.sql:415-418`）。那是既有行为。本期不新增事件种类，不把 `tool/result` 加入指纹排除名单，也不为了指纹去绕开 complete。成功之后可以有 `tool/result`，仍然不得有 `tool/call`。

本轮在 `v13/**/*.sql` 搜索 `NEW.type = 'tool/result'`，零命中。这不是「全库没有别的拒绝」的证明。若重读发现 complete 拒绝这组键，停并 `ASK_USER`。不得改 acl，不得改把工具塞进 `tool_calls`，不得 INSERT artifact。

适配器在 `v13/workspace_exec/adapter.py`。驱动器在 `v13/workspace_exec/driver.py`。适配器不做 SQL。驱动器在打开者事务提交之后才调用适配器，调用时连接不在事务中。然后另开事务调用接受函数。

驱动器调用 `v13_workspace_policy()`，把 `bash_verbs` 传给适配器。适配器不做 SQL。

- 工作区根来自测试夹具的 `p_workspace_root` 与 `p_allowed_roots`，不是模型数据，也不是生产根授权。本期不声称一般的生产根已经获准。`/` 拒绝。不在允许名单里的根拒绝，包括仓库根。IO 之前再核对已打开根的 device 与 inode。路径被换掉则 RAISE `escape`，不操作。根必须是目录。任一路径分量是符号链接，包括最后一段，token `escape`。不跟随。实现用 `openat` 加 `O_NOFOLLOW`，或该平台的等价物。拒绝时零字节写入，不把 effect 标成 `succeeded`。`~` 不展开。不声称一般的操作系统锁。
- 适配器可打开的闭集只有三类：`paths` 里声明的项；已声明目录之下、仍在根内、且不是符号链接的 `find` 后代，这些后代不必写进 `paths`；`write` 与 `edit` 的那一个临时文件，名字是 `.v13tmp-` 加 `attempt_key`，位于已声明父目录或工作区根下，不必写进 `paths`，只由适配器创建。绝对路径、`~`、以及根外的任何路径仍然拒绝。
- 三件事分开。PG 路径互斥只串行使用这个打开者的执行者。新目标与禁止覆盖使用平台的独占或不替换原语；目标出现则 `exists`，不覆盖。已有文件的哈希检查不是文件系统 CAS。本期只交付受控夹具：最终 no-follow 再验与突变之间没有协议外写者。`changed_after_admit_does_not_overwrite` 把变化注入在这次最终再验之前，期望 `hash_mismatch` 或 `exists`。再验之后的残余窗口不是 `ambiguous`，也不得让 `edit_replaces_once`、`bash_rm_one_file`、`write_full_bytes` 失败。`ambiguous` 覆盖副作用之后的失败、不确定的结局，或临时文件清理失败。它不要求目标字节未知。父若以后要求抵抗任意协议外写者，停并 `ASK_USER`，不得静默声称 CAS。不声称一般的操作系统锁。
- no-follow 打开之后，`write`、`edit`、`grep`、`rm` 以及 `cp`、`mv` 的源必须是普通文件（`S_ISREG` 或平台等价物）。不是则 `not_a_file`。`find` 与 `ls` 的声明路径本身必须是目录。只有 `mkdir` 检查父目录。需要目录却不是目录则 `not_a_dir`。FIFO、设备、套接字和其它特殊节点在读写之前拒绝。
- `write`：写入之前，若文件已存在且 sha256 不等于 `expected_sha256`，RAISE `hash_mismatch`，字节不变。`expected_sha256` 为 null 时，文件已存在则 `exists`，零字节覆盖。不存在则用 noreplace 安装新文件。安装失败且临时文件已删除：以 `exists` 或 `io_error` 完成 `failed`，目标字节不变。临时文件仍在，或目标命运未知：驱动器返回 `ambiguous`，不调用接受函数。临时文件名含 `attempt_key`，位于同一父目录。删临时文件失败是 `ambiguous`，不调用接受函数，行保持 `claimed`。
- `edit`：`new` 为 JSON null 时，打开者在写入任何 effect 之前 RAISE `v13: workspace open: canonical`，零写。不把这个用例交给接受函数。`new` 为 `""` 是删掉匹配到的子串，不是截断文件。写入之前，若文件 sha256 不等于 `expected_sha256`，RAISE `hash_mismatch`，字节不变。哈希匹配之后才按 UTF-8 找 `old`，出现次数必须是 1。否则 `edit_not_unique`，不写。命中则替换那一次。
- 现有文件不是合法 UTF-8：`edit` 与 `grep` 以 `bad_utf8` 失败，文件字节不变，effect 为 `failed`。
- `mkdir`：路径尚不存在，且父目录已存在。不是递归创建。不要哈希。
- `rm`：恰好一个已存在的文件。不删目录，不递归。删除前 sha256 必须等于 `expected_sha256`。不对则 `hash_mismatch`，字节不变。
- `cp`：恰好两个文件路径。源的 sha256 必须等于 `expected_sha256`。不对则 `hash_mismatch`，两边字节都不变。目标必须尚不存在，不要目标哈希。已存在则 `exists`，不覆盖。
- `mv`：恰好两个路径。源的 sha256 必须等于 `expected_sha256`。不对则 `hash_mismatch`，字节不变。目标必须尚不存在，不要目标哈希。已存在则 `exists`，不覆盖。与 `cp` 同一 token。
- `grep`：只在声明的文件上做固定字符串搜索。不走目录，不用正则。
- `find`：从该目录向下列名字，不跟随符号链接，不执行命令。深度超过 `find_depth_cap` 就停止下探，`depth_limited=true`。这不是 `truncated`。不插 `replan/required`。
- `ls`：只列该目录的一层名字，不读文件内容。

副作用之前、且结局确定的失败：驱动器调用 `v13_tool_result_accept`，`p_status=failed`，`ok=false`，并带一个具体 token。未归类的 IO 是 `io_error`。已归类的仍是 `hash_mismatch`、`exists`、`missing`、`escape`、`not_a_file`、`not_a_dir`、`edit_not_unique`、`bad_utf8`。`edit` 与 `grep` 的非法 UTF-8 是 `bad_utf8` 加 `failed`，不是 `io_error`。副作用之后的失败，或任何不确定的失败，驱动器结局是 `ambiguous`：不调用接受函数，行保持 `claimed`。接受函数不把 `ambiguous` 完成成 `failed`。适配器异常不得逃出这两种结局之一。

`attempt_key` 不得挂到另一个 effect 上，也不得靠重放重新获得执行。同一 effect、同一规范请求、status 为 `claimed` 或 `succeeded`，仍可按第 10 步重放。失败之后的新执行要用新键。驱动器对同一次逻辑调用最多使用 `tool_open_attempts` 个键，然后停。无睡眠。这个计数只在驱动器对外返回里，不在打开者返回闭集里，不插入新事件种类。

夹具由测试显式定界。边界测试可以超过结果文本帽或 `find` 深度帽。没有文件字节帽，不得把夹具文件大小写成必须落在一个不存在的帽里。不新增政策键。`grep`、`find`、`ls` 达到结果帽后停止累加 `text`，继续累计字节数，仅当总字节数大于帽才置 `truncated`。不声称一般的生产执行器已经有界。

崩溃窗口留给 G4，本期不修：IO 已改文件而 complete 尚未提交时，行保持 `claimed`，路径继续被占。驱动器不得发补偿 SQL 去清行。`rm` 或 `mv` 无法区分「已经做成结束态」与「从来没执行」时，驱动器返回 `ambiguous`，不调用接受函数，行保持 `claimed`。

测试的工作区目录由测试在系统临时目录下创建，不得是仓库根，用完删除。不得把仓库当成 `workspace_root`。

### 4.10 错误 token

四类分开，不混用。

打开者 token，前缀 `v13: workspace open:`，零写或零新 effect：`auth`、`stopped`、`terminal`、`human_pending`、`no_plan`、`should_run`、`not_single_tree`、`subset`、`explore_not_a_tool_label`、`not_this_opener`、`canonical`、`payload`、`verb_closed`、`path_busy`、`effect_exists`、`label_mismatch`、`temp_namespace`。`subset` 是已知标签不含该工具。`verb_closed` 是 `argv[0]` 不在 `bash_verbs`。未知标签不是 `explore`、`read_only`、`workspace_edit` 时用 `canonical`。

接受函数自己的 RAISE，前缀 `v13: workspace result:`，不调用 `v13_complete`，行保持 `claimed`，`result` 不变：`canonical`、`over_cap`、`flag_inconsistent`、`lock_mismatch`、`cancel`、`ambiguous`。畸形 `p_result`（未知键、缺键、`schema_version` 不是 1、类型不对）、非法 `p_status`，以及任何其它 `ok` / `error_token` / `p_status` 组合，都是 `canonical`。`flag_inconsistent` 是截断旗与 `byte_length`、帽不一致。`error_token` 为 `ambiguous` 时抬起的就是这个 `ambiguous`。

可完成的 worker token，驱动器以 `p_status=failed`、`ok=false` 交给接受函数：`hash_mismatch`、`exists`、`missing`、`escape`、`not_a_file`、`not_a_dir`、`edit_not_unique`、`bad_utf8`、`io_error`。`missing` 是必须已存在的文件或父目录不存在。`not_a_file` 是写、编辑、grep、rm 或 cp/mv 的源不是普通文件。`not_a_dir` 是 `find` 或 `ls` 的声明路径本身不是目录，或 `mkdir` 的父目录不是目录。未归类的 IO 才是 `io_error`。

驱动器结局、不调用接受函数：`ambiguous`。行保持 `claimed`。

活体异常保持原文，不包装成这些 token。

### 4.11 驱动器允许调用的 SQL

`driver.py` 只允许调用：`v13_workspace_policy`、`v13_tool_effect_open`、`v13_tool_result_accept`。打开者与驱动器都不调用 `v13_plan_gate`。

不调用 `v13_plan_commit_entry`。不调用 `v13_open_session`、`v13_complete`、`v13_enqueue_effect`、`v13_claim`、`v13_advance`、`v13_spawn_subsession`、`v13_child_pointer`、`v13_recover_idle`、`v13_insert_nudge`、`v13_goal_stop`、`v13_goal_resume`、`v13_cancel`、`v13_llm_tool_calls`、`v13_plan_writer`、`v13_plan_gate`。测试文件可以调用活体函数做负例。驱动器路径不可以。

打开者返回闭集不含重试次数。驱动器对外返回可以带 `attempts_used`。返回闭集，与第 4.3 节、第 4.5 节第 10 步同一句：`effect_id`、`attempt_no`、`fence`、`replayed`、`tool`、`status` 每次都在。`result` 只在 `replayed=true` 且 `status=succeeded` 时等于已存储的 `effects.result`，否则为 JSON null。首次打开返回 `replayed=false`、`status=claimed`、`result` 为 JSON null，以及第 14 步更新之后的 `attempt_no` 与 `fence`。只有这一次返回可以跑适配器。`replayed=true` 且 `status=claimed` 是已有行，不授予执行，不跑适配器，不调用接受函数。重放返回已有行，零新行。`replayed=true` 且 `status=succeeded`：交回返回里的 `result`，不调用适配器，不调用接受函数。恢复留在 G4。

打开者事务必须是 `READ COMMITTED`。驱动器显式设置。其它隔离级别由打开者在检查与写入之前拒绝，零写，token `v13: workspace open: canonical`。根锁不保证在每一种隔离级别下都能挡住并发准入。取消检查在接受函数的锁内事务里，不在驱动器 SELECT 里。打开者与驱动器都不取消已 `claimed` 的工作区 effect。测试文件可以在接受之前调用活体 `v13_cancel`。接受函数然后拒绝 `succeeded`。驱动器不 INSERT，不 UPDATE。不调用 `v13_plan_commit_entry`。`workspace_admit` 的 SQL 与 `driver.py` 不得调用 `v13_plan_gate`。静态检查看见调用即非零退出。注释里写出这个名字不算调用。

`static_check` 不因为注释失败，不扫描 `SELECT`，不 SELECT 由断言执行，并且 `driver.py` 的 `v13_` 调用超出允许名单即失败。

测试文件另有一条扫描：不得包含 `INSERT INTO effects`、`INSERT INTO events`、`INSERT INTO sessions`、`INSERT INTO artifacts`。它可以为负例包含 `tool_calls` 这个词。

FakeLLM 的返回值可以含 `workspace_request`。驱动器把它原样交给打开者。不得把它放进 `tool_calls`。本期脚本的驱动器不调用 `v13_advance`，因此不触发 Phase A 的子 read 前缀，也不把十二步链的归档算进本 gate。`workspace_admit` 的测试可以调用一次 `v13_advance`，只为证明那一行没被派发；派发了就停，不替换 advance。

## 5. 分期

本规划轮没有跑本节命令。实现在父接受本文之前不得把这些命令当成开工许可。命令退出码 0 只说明该确定性 gate 通过。Fake 绿不是产品可用。

公共纪律：新建一次性库；名字不得匹配 `agent_v13_%`，不得使用 `agent_v13_longloop_p0_probe`；名字已存在则拒绝并退出，不 DROP；清理只 DROP 本次创建成功的那一个；现有库不得 DROP。先装 1..29 到 govern，再装 Phase A 尾部直到 `real_chain`，再装 `workspace_admit`。不调用 read_tools 的 `setup_db.py`。超级用户不是产品角色证明。新 SQL 不写 stannum GRANT。新函数 `REVOKE EXECUTE FROM PUBLIC`。不 GRANT 给一个被写成已证明的产品角色。

证据：命令、退出码、一次性库名、断言名、相关 effect 计数。断言名按下面的字面写入矩阵。

矩阵与台账是实现里程碑才创建的新文件，不改 Phase A 那两份，不改 Phase 0，不改路线图：

- `docs/reviews/v13-long-loop-phase-b-conformance-matrix-2026-09-29.md`
- `docs/reviews/v13-long-loop-phase-b-deviation-ledger-2026-09-29.md`

矩阵列：条目，目录，允许的声称，证据指针，状态。状态从 `not_run` 起。只有对应 gate 退出码 0 之后，该行才能写成 `exit_0`，并带上命令、退出码与库名。不设 `real_authorized_exit_0`。本文的存在不是证据。

### 5.1 `v13/workspace_admit`

交付：C2 政策行，打开者，结果接受函数，互斥扫描，截断形状校验。无文件系统，无 provider，无 advance 替换。

追溯：C2 子集交付；G1 的准入与互斥合同。不是四个 read 的注册。

依赖：活体 1..29，加上已落地的 Phase A 尾部直到 `real_chain`。不依赖计划臂创建工作区 effect。测试为了 `no_plan` 与放行夹具，可以调用已有 `v13_plan_writer`。那是夹具，不是本期再交付 A1。

Gate：`UV_FROZEN=1 uv run python v13/workspace_admit/test_workspace_admit.py`。本规划轮未跑。

断言：

- `policy_seed_idempotent`
- `workflow_template_v1_unchanged`
- `read_names_absent_from_policy`
- `read_tool_rows_unchanged`
- `read_only_rejects_edit_write_bash`
- `read_only_admits_grep_find_ls`
- `workspace_edit_admits_six`
- `explore_label_rejected`
- `explore_spawn_still_raises`
- `spawn_guard_rejects_edit`
- `not_this_opener_rejects_read_file_py`
- `open_claims_without_increment`（status 为 `claimed`；`attempt_no` 与 `fence` 仍是 enqueue 后的值；零 `tool/call`）
- `claim_skips_claimed_row`
- `advance_does_not_dispatch_tool`（夹具必须是重读证明会进入 `WHEN 'tool'`、且该行已是 `claimed` 的那一次 `v13_advance`。`:764-773` 的 waiting 返回不是通过。进不了这臂，或这臂派发了 `claimed`、或调用了 `v13_send_work`：停并 `ASK_USER`。不替换 `v13_advance`。不把臂前返回算成退出码 0）
- `no_plan_refuses_open`
- `plan_without_selected_todo_still_opens`（`v13_plan_current(根)` 非空，没有 selected todo，仍打开。不调用 `v13_plan_gate`）
- `should_run_false_refuses_open`（对根调用。夹具用种子里已有的 `unknown_wall` 或 `unconsumed_cancel`，不用 `duty_cycle=0`，不新增 block id。零写；不调用 advance；不写收据）
- `not_single_tree`（只在会回滚的事务里，测试文件用已有具名函数再建一个根。打开者 RAISE，零工作区 effect，无工作区 IO。回滚后一棵树。其余夹具不建第二根）
- `path_busy_same_path`
- `path_busy_prefix`
- `path_busy_overlapping_roots`（允许名单里同时有 `/tmp/ws` 与 `/tmp/ws/sub` 时，`sub/file.txt` 与 `file.txt` 是 `path_busy`。不因为根字符串不同就跳过）
- `path_distinct_ab`（段 `a` 与 `ab` 不冲突；段 `ab` 与 `a/b` 也不冲突）
- `parent_segment_not_self_busy`（同一请求同时带 `a` 与 `a/b` 不是 `path_busy`）
- `case_alias_rejected`（UTF-8 casefold 后段相等、字符串不等：`v13: workspace open: canonical`，零写。不靠 `realpath`）
- `temp_prefix_case_rejected`（`.V13TMP-` 用同一打开者 token `canonical`。精确 `.v13tmp-` 仍是 `temp_namespace`）
- `isolation_not_read_committed_rejected`（非 `READ COMMITTED`：`v13: workspace open: canonical`，零写）
- `root_lock_then_path_busy`（两个连接。第一笔持有根锁。第二笔等待。第一笔提交之后，第二笔看见忙行并返回 `path_busy`）
- `result_shape_rejected`（畸形 `p_result`：接受 token `canonical`，行保持 `claimed`，`result` 不变，不调用 complete）
- `bad_status_rejected`（非法 `p_status` 或其它 `ok` / `error_token` / `p_status` 组合：同样是接受 token `canonical`）
- `parent_missing_rejected`（`a/b` 的 `paths` 不含 `a` 则零写）
- `same_parent_blocks`（两笔都声明父段 `a` 时互相挡住）
- `crashed_claim_stays_busy`
- `terminal_releases_path`
- `replay_open_same_fence`
- `effect_exists_no_requeue`
- `failed_attempt_key_different_request_rejected`（任一 status，含先前 `failed`；不同请求；零写。同一 effect 的重放不走这条）
- `unsorted_paths_rejected`
- `result_over_cap_rejected`（接受函数不把超帽文本切短；行保持 `claimed`，`result` 不变）
- `result_cap_minus_one`（原始长度是帽减 1：`truncated=false`，`text` 是全文）
- `result_cap_exact`（恰好等于帽：完成，`truncated=false`）
- `result_cap_plus_one`（帽加 1：`truncated=true`，`text` 只是帽内 UTF-8 前缀，`byte_length` 仍是全长）
- `truncated_flag_consistent`（`truncated = (byte_length > cap)`。`byte_length` 是完整原始长度。`truncated` 为假时 `byte_length = octet_length(text)`）
- `root_actor_rejected`
- `first_open_stopped`
- `first_open_terminal`
- `human_pending_rejected`
- `no_sql_kind`
- `hashes_unmodified`
- `stage_bytes`

`hashes_unmodified` 比较装载本 stage 前后的 `v13_advance`、`v13_goal_fingerprint`、`v13_enqueue_effect`、`v13_llm_tool_calls`、`v13_recover_idle`。`stage_bytes`：相对本提交的父提交，stage 1–29 与 Phase A 计划路径的 diff 为空；`load.py` 只在表尾增加 `workspace_admit`。

测试进程不 INSERT effect 或 event。`live` 类断言用 SQL 调用具名函数。

提交边界：`v13/workspace_admit/`，`v13/load.py` 的这一次表尾追加，两份新评审文件的骨架，本目录 README。README 写下种子、租约重读行号、human_pending 活体行号、`WHEN 'tool'` 的重读结论，以及「未证明产品角色」和「未证明 material 已扣」。

禁止只提交一个不存在的 advance 替换。本目录没有那份替换。

### 5.2 `v13/workspace_exec`

交付：另一份脚本上的 edit、write、bash、grep、find、ls。文件字节失败则保持原样。IO 在事务外。C2 在文件系统上的效果。无加载键。

追溯：G1 的执行面。不是 G2，不是十二步链。

依赖：`workspace_admit` 已装。测试夹具可以先调用 `v13_plan_writer` 写下一条当前 advancement 计划。通过条件是 `v13_plan_current(根)` 非空。不要求 selected todo。不调用 `v13_plan_gate`。不 spawn，不调用 `v13_child_pointer`，不归档。打开任何 effect 之前先核对名字相等，见第 4.6 节。不一致则停，不得把本 gate 报成通过。不靠 `realpath`。

Gate：`UV_FROZEN=1 uv run python v13/workspace_exec/test_workspace_exec.py`。本规划轮未跑。

断言：

- `single_tree`
- `open_session_version_2`（夹具会话的 `sessions.route_policy_version` 是 2。测试文件调用已有 `v13_open_session` 并传入显式 version。不是 `workflow_template` version 2。`driver.py` 不调用 `v13_plan_commit_entry`，也不调用 `v13_open_session`）
- `workspace_not_repo`（根不在测试允许名单，或是 `/`，或是仓库根：拒绝。通过的根是系统临时目录，不是仓库根，也不是 `/`）
- `io_outside_txn`
- `no_advisory_lock_across_io`
- `workspace_request_not_in_tool_calls`
- `write_full_bytes`
- `write_does_not_truncate_file_bytes`
- `write_hash_mismatch_keeps_bytes`
- `edit_hash_mismatch_keeps_bytes`（写入前哈希不符：`hash_mismatch`，字节不变）
- `edit_bad_utf8_keeps_bytes`（`bad_utf8` 加 `failed`，不是 `io_error`；文件不变）
- `edit_not_unique_keeps_bytes`
- `edit_replaces_once`
- `read_only_edit_writes_nothing`
- `bash_rm_one_file`
- `rm_hash_mismatch_keeps_bytes`
- `cp_source_hash_mismatch_keeps_bytes`（目标尚不存在，不要目标哈希）
- `mv_source_hash_mismatch_keeps_bytes`（目标尚不存在，不要目标哈希）
- `mv_target_exists`（token `exists`，与 `cp` 相同，不覆盖）
- `bash_operand_not_in_paths_rejected`（含 `secret.txt`；未声明旗标拒绝）
- `bash_shell_rejected`
- `bash_mkdir_not_recursive`
- `grep_fixed_string_truncates_result`（文件字节不变；worker 把 `text` 切到帽内并置 `truncated=true`；接受函数不再切；超帽文本不入库）
- `find_no_exec`
- `find_depth_limited_not_truncated`（深度限制之后、字节截断之前的输出未超帽时 `truncated=false`）
- `find_empty_depth_limited`（没有匹配，但因深度帽停下：`text=""`，`byte_length=0`，`truncated=false`，`depth_limited=true`）
- `find_traverses_unlisted_child`（子路径不在 `paths` 里仍可列出；不跟随符号链接）
- `temp_under_declared_parent`（临时名是 `.v13tmp-` 加 `attempt_key`，在已声明父目录或工作区根下，不必预列，不得逃出根。只由适配器创建）
- `temp_namespace_rejected`（token `temp_namespace`。目标在工作区根下，其声明路径不是临时名的前缀。A 在最终替换前暂停。B 指向 A 的临时路径，准入拒绝，零新 effect。A 的最终写入仍是请求内容 X）
- `ls_names_only`
- `symlink_escape`（含最后一段的符号链接：不跟随；零字节写入；effect 不是 `succeeded`。做不到这条拒绝则本 gate 不得退出码 0）
- `changed_after_admit_does_not_overwrite`（变化注入在最终 no-follow 再验之前。期望 `hash_mismatch` 或 `exists`。再验之后的残余窗口不是 `ambiguous`，也不得让 `edit_replaces_once`、`bash_rm_one_file`、`write_full_bytes` 失败）
- `special_file_rejected`（FIFO、设备、套接字在读写之前拒绝。需要普通文件却不是时 `not_a_file`。需要目录却不是时 `not_a_dir`）
- `pre_effect_io_error_fails`（未归类、且副作用之前：`failed` 加 `io_error`。已归类的不用这个 token）
- `fixture_bound_only`（测试显式定界。边界测试可以超过结果文本帽或 find 深度帽。不把文件大小写成落在不存在的文件字节帽里。不新增政策键）
- `temp_cleanup_fail_is_ambiguous`（目标字节不变。临时文件清理失败。结局是 `ambiguous`。不调用接受函数。行保持 `claimed`）
- `ambiguous_rm_leaves_claimed`
- `replay_succeeded_does_not_reexecute`（不调用适配器，不调用接受函数，交回已存储的 `effects.result`）
- `cancel_during_io_does_not_succeed`（检查在 `v13_tool_result_accept` 的锁内事务，会话先于 effect。接受前落下的 cancel 不得把行标成 `succeeded`。行已被取消改走则 `lock_mismatch` 或 `cancel` 任一 token 都算通过。锁序必须改 `v13_cancel` 才能说出则本断言是 `ASK_USER` 停点，不得写成已闭合）
- `retry_bound_2`
- `static_check`（匹配调用与语句，不匹配注释。`driver.py` 的 `v13_` 调用超出允许名单即失败）
- `real_chain_deny_unchanged`（不编辑 `v13/real_chain/**`。若 `v13/real_chain/test_real_chain.py` 已存在，它必须仍含 `deny_edit_write_bash`。本测试不把 Phase A gate 算成本 gate 的通过）
- `no_real_provider`
- `no_material_spent_insert`
- `tool_result_without_tool_call`

README 写明：Fake 退出码 0 不是产品可用；本目录不授权无人值守；bash 不是系统 shell；崩溃 `claimed` 行留给 G4；本 gate 不证明 material 收据。

提交边界：`v13/workspace_exec/`，矩阵与台账里本 stage 的行，本目录 README。不含 `load.py`。不含 `v13/real_chain/**`。不含 `uv.lock`。

## 6. 追溯

Phase 0 §7 的归属不改。

| 项 | 归属 | 本计划 |
|---|---|---|
| G1 | B | `workspace_admit` 与 `workspace_exec`。不把 Phase A 的 read 注册计成本期交付 |
| C2 | 合同在 A；子集在 B | 子集在 `workspace_tool_subset`。`workflow_template` v1 不改。explore 仍 RAISE |
| A1–A4、B1、B2、B6、C1、C3、C4、C7、G2 | A | 不重做。打开者只读 `v13_plan_current`，不替换 advance，不调用 `v13_plan_gate` |
| B3 | A 的不做项 | 无目录。C/D 不得重开 |
| B4、B5、D1、D2、D3、G3 | C | 不实现。本期不写 material 收据 |
| C5 | 等待合同；无人值守 skip 未授权 | human_pending 时打开失败。不 skip |
| C6 | C | 不实现。V11 未读 |
| G4 | 单 goal 续租与配额声称在 C；公平与 soak 在 D | 崩溃 `claimed`、续租、不确定窗口不在本期 |
| PC-4 | C 之前不开工 | 不改 `quota_window` |

不得声称：已能自由改代码；explore 已是成功只读；Phase A 的 read 注册是 Phase B 交付；Fake 绿即产品可用；绑定窗已闭合；这次工具 complete 已经扣了 material；无人值守已授权。

## 7. 收尾与提交

实现里程碑才更新第 5 节的矩阵、台账与该 stage README。本规划轮不创建那三份实现收尾，只创建本计划与规划证据。默认不改路线图、Phase 0、Phase A 计划、Phase A 矩阵、Phase A 证据。

提交顺序：`workspace_admit`，然后 `workspace_exec`。每个实现提交都是路径级 add。禁止 `git add -A`。禁止纳入 `uv.lock`、`prompt-exports/`、调查、stage 1–29、Phase A 已有目录、父循环 memory、探针与日志。禁止 force、`reset --hard`、自动 stash、跳 hook。

本规划轮不提交，不推送。父在自己的复审之后才决定发表。

无法只做路径级 add 时停。

## 8. 开工重读与 ASK_USER

实现先做这些重读。任一停点成立：不写绕过代码，不改 stage 1–29，不加第二份 `v13_advance`，不把该 stage 标成 `exit_0`。

| 重读 | 停点 |
|---|---|
| `v13/govern/v13_govern.sql:1137-1168` | 已经 `claimed` 的行仍会被派发，或仍会 `v13_send_work`。标成 `claimed` 就挡不住。停 |
| effect 状态 CHECK 或触发器 | `ready` 到 `claimed` 的更新被拒绝，或该更新会写 `tool/call`。停。不改 core |
| `claimed` 且 `attempt_no=0` | complete 或别的活体谓词拒绝。停。不在打开者里递增 `attempt_no`，不改 `v13_claim` |
| `v13_recover_idle` 与 requeue | 会回收这条 `claimed` 行，包括 `lease_until` 为 `infinity` 的行。停。不续租 |
| 加载后的 `v13_enqueue_effect` | 符号不存在，或写 `tool/call`、调用 `v13_send_work`，或拒绝本期这种普通 jsonb 请求。停。不改 control |
| `v13/read_tools/README.md:62` | 不是 51200。停。不另选数字 |
| `v13/acl/v13_acl.sql:459-469` | 5 参 complete 不是 Phase A 写的显式 NULL actor。停 |
| complete 对 tool 结果的赋值 | 拒绝第 4.9 节的键。停。不改用 artifact INSERT，不改用 `tool_calls` |
| `v13_plan_current` | 加载到 `real_chain` 之后仍不存在。停。不在本期再造一份。不改调用 `v13_plan_gate` 来冒充 |
| `tools` 行或 route band | 没有工具行就无法 complete，或插入行会让活体 advance 把该名字当 `sql` handler 在事务内执行。停。默认零 `tools` DML |
| 任何设计需要再替换 `v13_advance` | 停 |
| 父退回进程内 bash，改要系统 shell | 停。不打开 shell |
| 必须罩住 Phase A `read_file_py` 的路径 | 停。不改 `plan_arm` |
| `v13_should_run` 签名 | 不是一个 uuid 进、布尔出。停。不包新函数。调用目标不是根也停。不新增 block id，不用 `duty_cycle=0` |
| `v13_effect_id` | 不能按 `(p_session, 'tool', p_request)` 调用，或身份忽略 `attempt_key`、`paths`、`payload`。停并 `ASK_USER`。不复制该函数 |
| 唯一一次 `v13_advance` 进不了 `WHEN 'tool'`，或该臂派发已 `claimed` 的行 | 停并 `ASK_USER`。不替换 `v13_advance`。`:764-773` 的返回不是通过 |
| 父要求本期写 material 收据，或工作区 effect 必须绑定 todo | 停。那是 B5 或第二份 advance。驱动器不 INSERT 收据 |

另外保持未决，不得写成已核：产品库名、产品角色、stannum、PC-4、V11、席位常数、stopped 上的 `user/message`、`steer/injected`、`v13_spawn_owner` 的 CREATE、`v13_send_work` 的全文、`WHEN 'tool'` 的选择过滤。本期不依赖未读的席位常数。

## 9. 留给父复审

本文是候选。父复审之后才决定是否接受。实现在那之前不得开工。父复审是必需的。本规划轮没有完成它，也没有把任一 lane 的草稿计数写成通过。

provider 402 不是内容分，不是 P0=0，不是 P1=0。截断的 kimi lane 同样不是通过。

请父决定是否接受下列选择，或退回后重写计划。实现在退回前不得私自换一套：

- 两个目录。只有 `workspace_admit` 追加在 `real_chain` 之后。`workspace_exec` 没有加载键。
- `v13_tool_effect_open` 调用活体 enqueue，并把该行标成 `claimed`，且不递增 `attempt_no` 与 `fence`。
- `v13_tool_result_accept` 包住 5 参 complete。驱动器路径不直接调用 complete。
- 新政策 `workspace_tool_subset` version 1。标签只有 `read_only` 与 `workspace_edit`。不 UPDATE `workflow_template`。不加它的 version 2。
- 六个工具名。四个 read 名字不进这行政策，打开者拒绝再打开它们。
- bash 是进程内闭集动词，名单只在政策 `bash_verbs`：按字节序 `cp`、`mkdir`、`mv`、`rm`。不是自由 shell，也不是 execve。
- 结果文本帽 51200 字节，只作用于 `effects.result.text`，并带 `truncated`。文件字节失败则保持原样。不设文件字节帽。
- 路径帽 4，argv 帽 4，find 深度 4，打开尝试 2。不写未读席位常数 8 或 64。父可退回这组种子。
- 互斥是未终态 tool effect 的库内扫描，逐段前缀，无新表。崩溃 `claimed` 继续占路径。
- 打开者在 `v13_plan_current` 为空时拒绝。没有 selected todo 时，只要当前计划非空，仍可打开。不调用 `v13_plan_gate`。
- `v13_should_run` 只对根调用。种子里已有的 block 可以让它在未 stopped、非终态时为假，所以 token 保留。不用 `duty_cycle=0`，不新增 block id。
- 工作区根是事务外的测试配置，不是模型请求字段。`/` 与允许名单外的根拒绝。重叠的允许根用整段路径比较，不因为字符串不同就跳过，结果是 `path_busy`。
- 不调用 `v13_plan_commit_entry`。`open_session_version_2` 是 `route_policy_version = 2`，不是 `workflow_template` version 2。
- 工作区 effect 不绑 todo，不归档。本期不为它调用结算 advance。
- 打开者在同键重放之前检查会话终态与 stopped。effect status 为 `succeeded` 仍返回 `replayed=true`。这与规划写者的重放先于停复不同。父可退回这个顺序。
- `replayed=true` 且已 `succeeded` 时不重新执行。`claimed` 的重放不授予执行。恢复留在 G4。
- 打开者使用 operator 的 NULL，或直接父的非 NULL。这不改写 T1.4，也不套到普通 tool complete。
- 初始 `lease_until = infinity` 仅在重读证明这样不会被回收时使用。否则 ASK_USER。
- 本期不写 material 收据，不声称配额已扣。

不接受则停。不得在实现里换成另一套控制面。
