# v13 workspace_admit

Phase B 第一段。交付 C2 子集政策行、工作区 effect 打开者、结果接受、路径互斥扫描、截断形状校验。无文件系统，无 provider，无第二份 `v13_advance`。不证明产品角色。不证明 material 已扣。Fake 退出码 0 不是产品可用。

## 种子

`workspace_tool_subset` version 1，`active`。不存在则 INSERT；已存在且 jsonb 相等则跳过；不相等或非 active 则装载 RAISE，不 UPDATE。不碰 `workflow_template`。

| 键 | 值 |
|---|---|
| `schema_version` | 1 |
| `result_text_cap_bytes` | 51200。重读 `v13/read_tools/README.md:62`，`head -c` 仍是 51200。结果文本帽，不是文件字节帽 |
| `paths_cap` | 4 |
| `argv_len_cap` | 4 |
| `find_depth_cap` | 4 |
| `tool_open_attempts` | 2 |
| `bash_verbs` | 字节序 `cp`、`mkdir`、`mv`、`rm` |
| `labels.read_only.admits` | `find`、`grep`、`ls` |
| `labels.workspace_edit.admits` | `bash`、`edit`、`find`、`grep`、`ls`、`write` |

四个 read 名字与 `spawn_subsession` 不进这行。打开者见到它们 RAISE `not_this_opener`。政策 value 子串不含 `explore`、`pair`、四个 read 名字、`spawn_subsession`。零 `tools` DML。新 SQL 与 `setup_db.py` 都不写 stannum GRANT。`paths` 是否已排序用 `COLLATE "C"` 比字节序，打开者不重排。段别名用 `v13_workspace_casefold`：`lower` 加上长展开（`ß`/`ẞ`→`ss`，`İ`，ﬀ–ﬄ），不是 `realpath`。`argv[0]` 只豁免下标 1；后面的元素即使文本等于动词也必须在 `paths` 里。`paths` 与 `argv` 的元素必须是字符串。允许名单用肯定成员判断，NULL 项拒绝。`byte_length` 按 `numeric` 信任，不收成 `int`。

## 开工重读

| 项 | 结论 |
|---|---|
| effect CHECK | `v13/schema/v13_core.sql:112-113` 允许 `ready`→`claimed`。不写 `tool/call` |
| `claimed` 且 `attempt_no=0` | 5 参 `v13_complete` 只比对 attempt/fence，不拒 0。打开者不递增 |
| `v13_recover_idle` | 加载后是 `v13/govern/v13_govern.sql:453-532`。跳过仍有 `ready`/`claimed`/`unknown` 的会话，不看 `lease_until`，不回收 `claimed` |
| `v13_requeue_stale` | 加载后是 `v13/control/v13_control.sql:1079`。只回收 `lease_until < clock_timestamp()` 的 `claimed`。`infinity` 不被回收 |
| 租约 | 因此第 14 步写 `lease_until = infinity`。不是续租，不是 G4 |
| `v13_enqueue_effect` | 加载后是 `v13/control/v13_control.sql:902`。不写 status（默认 `ready`），不写 `tool/call`，不调 `v13_send_work`。`effect_attempt_cap` v3 含 `tool` |
| 51200 | `v13/read_tools/README.md:62` 仍是 51200。函数体不另写这个数，从政策读 |
| 5 参 complete | `v13/acl/v13_acl.sql:459-469` 委托 `v13_complete(NULL::uuid, ...)` |
| tool 结果键 | 非 harness 的 tool 成功原样写入 `effects.result` 并追加 `tool/result`。不拒 §4.9 闭集 |
| `v13_plan_current` | `v13/plan_contract/v13_plan_contract.sql:316`。空则 `no_plan`。不调 `v13_plan_gate` |
| tools 行 | 四个 read 行已在，本 stage 零 DML，行不变 |
| `v13_should_run` | `(uuid) RETURNS boolean`。只对根调用 |
| `v13_effect_id` | `(uuid, text, jsonb)`。身份含完整请求哈希，不忽略 `attempt_key`、`paths`、`payload` |
| `WHEN 'tool'` | 见下。台账 PB-1、PB-3 |
| human_pending | `v13_pending_human` 在 `v13/control/v13_control.sql:121-128`：`kind='human'` 且 status 属于 `ready`、`claimed`，不含 `unknown`。实现与断言以活体为准。台账 PB-2 |
| stopped | `v13_goal_lifecycle` 读 `v13_goal_fold` 最后一条 `goal/stopped`（`v13/govern/v13_govern.sql:113-121`、`:129-136`） |
| material | 本 stage 不写 `turn/material_spent`，不声称配额已扣 |
| 产品角色 | 超级用户夹具不是证明。新函数 `REVOKE ALL FROM PUBLIC`。不写 stannum GRANT |

NUL 不能进入 jsonb/text。打开者不调用 `chr(0)`。反斜杠仍拒绝。

## advance_does_not_dispatch_tool

通过条件是 P ∧ C ∧ S，缺一不是退出码 0。裸 `waiting` 与「进不了臂」本身都不是通过。不替换 `v13_advance`。台账 PB-1。

- P：恰好一条工作区 tool effect 已 `claimed`，无其他 `ready`/`claimed`。一次 `v13_advance` 返回 `waiting`，会话 `waiting`，该行仍是原 id 且仍 `claimed`，effect 行集不变，`v13_send_work` 的 pgmq 写入为空。打开者可执行，不插行。
- C：同一前奏在保存点回滚后分叉，不打开该行。同一次 advance 必须与 P 可区分（返回词、新 effect、或 send_work 写入）。禁止先跑 P 再改行当 C。
- S：`pg_get_functiondef` 上，`status IN ('ready','claimed')` 且返回 `waiting` 的门在 `WHEN 'tool'` 之前；函数体内 `v13_enqueue_effect` / `v13_send_work` 首次出现晚于该门；测试前后 `v13_advance` 的 oid 不变。S 单独不是通过。

行号基线（台账 PB-3）：被测函数是 `v13/plan_arm/v13_plan_arm.sql`。臂前门 `:399-402`。`WHEN 'tool'` `:749`。该臂内 enqueue `:764-776`。`v13/govern/v13_govern.sql:785-788` 不是被测函数。计划引用的 govern `:764-773` 是书写时旧行号。

## 函数

- `v13_workspace_policy()` STABLE。零写。
- `v13_tool_effect_open(uuid, uuid, text, text, text[], jsonb)`。调活体 `v13_enqueue_effect` 后把该行标成 `claimed`，不递增 `attempt_no` / `fence`。不调 `v13_advance`、`v13_complete`、`v13_plan_commit_entry`、`v13_plan_gate`。
- `v13_tool_result_accept(uuid, integer, bigint, text, jsonb)`。先锁会话再锁 effect，然后调 5 参 `v13_complete`。51200 只从政策读取，不在函数体写死。超帽文本不切短。

`path_distinct_ab` 用 `v13_fork` 建同一棵树的子会话，因为 `ux_v13_effects_single_active` 使同一会话不能有两条 `ready`/`claimed`。扫描仍是库内、不按 `session_id` 过滤。

## Gate

`UV_FROZEN=1 uv run python v13/workspace_admit/test_workspace_admit.py`

断言名按计划 §5.1。另有夹具旁证，不另起声称。
