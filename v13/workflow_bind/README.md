# v13 workflow_bind

Phase A 第五段。交付 C1 政策行与解析器、C2 合同、C3 一条 `workflow/pointer`。不交付工具子集，不改 explore 的 RAISE，不交付 G1。不依赖计划臂派发。不证明产品角色。Fake 退出码 0 不是产品可用。

开工门重读了 `v13/spawn/v13_spawn.sql`：子会话上写的是 `spawn/task`（`:441`），不是 `user/message`。指针按 §5.5 另写一条。本目录不改 spawn SQL。

## C1

`v13_policies` 新行 `name=workflow_template`，`version=1`，`active`。`v13_workflow_resolve(text, int)` 是 STABLE。按 name 与 version 取冻结 value；缺失 RAISE `v13: workflow resolve: missing`；非 active RAISE `v13: workflow resolve: inactive`；闭集不符 RAISE `v13: workflow resolve: canonical`。零写，不写回政策行。

返回值是 jsonb 对象，恰好四键 `assertion`、`assembly`、`judgment`、`workflow`，每键一段非空文本。不拼成一行 `SYSTEM_PROMPT`。唯一生产调用者是将来的 `v13/real_chain/chain.py`。不进 `loop_driver` 允许名单。

四段正文不得含 `skip`、`workflow_id`、`plan/committed`、`INSERT`。gate 扫这四段正文，不扫键名。`judgment` 只是文本，不是可执行门。

## C2

合同在同一条政策行，不另建表。子集交付不在本行。子集在 Phase B。

| 字段 | 冻结值 |
|---|---|
| labels | `["read_only"]`。标签留在政策里，不写进 tools 目录，不选择端点 |
| allowed_tools | `read_pi`、`read_file_swift`、`read_file_py`、`read_duck`。这是真链驱动器允许名单，不是目录交付 |
| parent_tools | `spawn_subsession`。交给活体 spawn 臂，不是本目录的停点 |
| chain | `first_real_chain` |

`read_only` 不改变 explore 的 RAISE。本目录不 `UPDATE tools`，不碰 `read_tools/`，不把这四个名字插进 `tools`。

## C3

`v13_child_pointer(p_child uuid, p_parent uuid, p_root uuid, p_todo uuid, p_up_to_seq bigint) RETURNS uuid`。返回已存储的 `event_id`。

载荷闭集：`schema_version`（1）、`parent_session_id`、`root_session_id`、`todo_id`、`up_to_seq`。不含父事件正文，不含整份 plan canonical。部分唯一索引 `ux_events_workflow_pointer` 保证每个子会话至多一条。守卫在本文件，不进 plan 写者的触发器。

首次写入时，子会话已 stopped，或 status 为 `completed`/`failed`/`cancelled`，RAISE、零写。同载荷重放不走提前返回：再 INSERT，由 `unique_violation` 处理器读回已存储的 `event_id`，零新事件。异载荷在 INSERT 之前 RAISE `replay_conflict`、零写。父必须等于子行 `parent_session_id`，根必须等于上溯结果，否则 `not_child`。

生产调用者不在本目录。`plan_arm` 不调用。`loop_driver` 允许名单不含它。测试把该函数当被测单元直接调用。不改 `v13_session_log`。

## 断言名

`judgment_templates_untouched`；`resolve_v1`；`label_does_not_open_explore`；`no_tool_flag_update`；`one_pointer`；`pointer_not_transcript`；`session_log_unchanged`；`root_waterline_unchanged`。

超级用户夹具不是产品角色证明。
