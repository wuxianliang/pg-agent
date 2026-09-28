# v13 长循环 Phase A 计划证据（2026-09-29）

本文只记录本规划轮为写 `docs/plans/v13-long-loop-phase-a-plan-2026-09-29.md` 而重读的活体行。不是 stage 验收，不是产品绿，不是任何 gate 的通过证明。裁决以 Phase 0 计划为准。本文不改写 Phase 0。

## 1. 命令

本规划轮没有跑 stage gate，没有跑 Phase 0 探针，没有调用真实 provider，没有 `uv run`。

导航命令，退出码均为 0，不是 gate：

- `ls -lt prompt-exports`：列出 Oracle 导出。
- `wc -l` 与 `rg -n "^#{1,3} "`：统计初稿导出的标题。

没有测试输出，没有 `PROBE_OK`，没有退出码可以冒充 stage 通过。

## 2. 本轮重读

行号是本轮 `read_file` 或带行号的内容搜索所见到的。搜索只用来定位，随后能读到的行才写入计划。

| 文件:行 | 读到的事实 | 计划里的用法 |
|---|---|---|
| `v13/load.py:5-6` | 新 SQL 只追加在表尾 | 追加规则 |
| `v13/load.py:17-46` | 29 项，末项 `govern/v13_govern.sql` | 不分配 30+ 假编号 |
| `v13/load.py:48-78` | `STAGE_THROUGH["govern"]=29` | 同上 |
| `v13/load.py:84-111` | `files_through` / `load_stage` 按键截断 | 测试装到计划键，不重排 |
| `v13/schema/v13_core.sql:28-35` | `events.type` 开放词表；`seq` 是事件序 | 新种类不靠改表 CHECK；水位用 `seq` |
| `v13/schema/v13_core.sql:70-78` | `user/message` 增加 `turn_no`，并把 `completed`/`failed` 重置为 `ready`；`cancelled` 不重置 | 指针不用 `user/message`；水位不用 `turn_no` |
| `v13/schema/v13_core.sql:90` | 已有 `digest` | `text_hash` 复用，不加扩展 |
| `v13/schema/v13_core.sql:99-112` | effect kind 闭集五词；status 含 `succeeded`，没有 `completed` | 新臂不发明第六种 kind；归档看 `succeeded` |
| `v13/spawn/v13_spawn.sql:189-198` | `v13_insert_nudge` 只追加 `recover/nudge` | A 的 claim 路径不调用它 |
| `v13/spawn/v13_spawn.sql:255` | spawn task 文本 `char_length > 1024` 则 RAISE | `item_text_cap=1024` 对齐这一行，不是 LoopX |
| `v13/spawn/v13_spawn.sql:285-320` | `v13_open_session` 只认 `route_policy_name` 与 `version`；缺省 name `default`、version `1` | 空 spec 是失败夹具 |
| `v13/spawn/v13_spawn.sql:398-401` | 根沿 `parent_session_id` 上溯；`v_depth > 64` 是深度守卫 | 父列名关闭。64 不挪用为 A3 帽 |
| `v13/spawn/v13_spawn.sql:436-448` | 子会话由 `v13_fork(..., 'fresh_fork', NULL)` 创建；子上写 `spawn/task`；父上写 `child-created` | 驱动器不第二遍 spawn；指针不改 `spawn/task` |
| `v13/spawn/v13_spawn.sql:793` | `children_terminal` 分支起点。CREATE 曾见于 `:783`。没有读完整个函数 | 计划只引用分支起点。并发窗仍未实现 |
| `v13/fanout/v13_fanout.sql:920` | 活体 `v13_fork` 在此 `CREATE OR REPLACE`。后文未见再替换 | 不改这个函数 |
| `v13/fanout/v13_fanout.sql:967-971` | 子行复制父的 `route_policy_name` 与 `route_policy_version`，并写 `parent_session_id` | 根 version 2 则子也是 2。不改 fanout |
| `v13/govern/v13_govern.sql:453-515` | 活体 `v13_recover_idle` 不 INSERT effect，不调用 `v13_advance`；写 nudge；返回 `pending`；stopped 则 `CONTINUE` | 不是 effect 入队者。A 不改造，不消费 |
| `v13/govern/v13_govern.sql:517` | 活体 hint 函数名是 `v13_scheduler_hint` | B1 读它，不新起 hint 函数 |
| `v13/govern/v13_govern.sql:790-829` | spawn 臂：`:805-808` 在 `should_run` 为假时返回 `waiting`；`:814-816` 真分支调用 `v13_spawn_subsession` | 计划门不插入这段。驱动器不调用 spawn 函数 |
| `v13/acl/v13_acl.sql:300-304` | 6 参 `v13_complete`：fence 不一致 `stale`；已终态 `replay` | 不发明额外迟到序号分支 |
| `v13/acl/v13_acl.sql:459-469` | 5 参包装传 `NULL::uuid` | tool/llm complete 走这条，不因此要求 operator |
| `v13/control/v13_control.sql:39-41` | `result_kind` 枚举 `progress|finish|wait|reject`。全库 `v13/**/*.sql` 只有这一处该枚举 | C7 只映射这四值 |
| `v13/triage/v13_triage.sql:198` | `v13_triage_emit` 只允许三种 type | 不是全局事件闭集 |
| `v13/observe/v13_observe.sql:130` | `v13_session_log` 的 CREATE | C3 不替换它 |
| `docs/plans/v13-layered-control-roadmap-2026-09-26.md:71` | F2 提案 `steer/injected`；不新增 `v13_steer` | 不是活体 INSERT。水位不因此关闭 |
| `v13/govern/README.md:1-40` | 指纹排除八词；`run_now` 不是入队许可；driver 未交付 | 不把 `recover/nudge` 或 plan 事件加入排除名单 |
| `v13/control/v13_control.sql:97-99` | `v13_is_harness_tool` 仅 `harness_turn` + `tool` | `read_file_py` 不走 harness schema |
| `v13/acl/v13_acl.sql:381-386` | harness 校验只包在该谓词内 | 同上 |
| `v13/acl/v13_acl.sql:411-418` | 成功 complete 把 `p_result` 写入 `effects.result`，tool 再写 `tool/result` | C4 摘录走这条，不新建 artifact 写者 |
| `v13/control/v13_control.sql:35-64` | schema 在 `content_hash` 之后还有 `signals` 与 `wake`。没有读到 schema 结尾 | 可选键名单保持未决 |
| `v13/acl/v13_acl.sql:408-426` | llm 成功且带 `tool_calls` 时 complete 自己写 `tool/call` | 驱动器不 INSERT 该事件 |
| `v13/spawn/v13_spawn.sql:94-133` | `v13_llm_tool_calls` 只接受 `spawn_subsession` 与 args 键 `task` | 不把 `read_file_py` 送进该函数 |
| `v13/spawn/v13_spawn.sql:246-256` | `tool/call` 守卫同样只接受该名字与该 args 键 | 不改守卫，不持久化 read 为 `tool/call` |

`INSERT INTO artifacts` 在 `v13/acl`、`v13/seam`、`v13/control`、`v13/govern` 的 SQL 里没有命中。这不是「全库没有 artifact 写者」的证明。计划因此不新造 artifact 写者。`tool/result` 的 `NEW.type` 守卫在 `v13/**/*.sql` 中没有命中。

## 3. 本轮未读

不得把下列各项写成已核：

- V11 变体。
- 席位常数。除了看见 `spawn.sql:401` 的深度 64 并不挪用之外，没有读到 8。
- `v13_advance` 在 `:790-829` 之外的完整正文，以及完整返回词闭集。Phase 0 点名的臂行号没有逐臂重开。
- `v13_spawn_owner` 的 CREATE 正文。只见到 `ALTER FUNCTION ... OWNER` 的搜索命中，没有读 CREATE。
- chunks 是否纳入 `plan/committed`、`todo/delta`、`workflow/pointer`。
- 生产非超级用户是否满足 `v13_control_operator()`。
- stopped 生命周期上的 `user/message` 是否被拒绝。`append_event` 的 status 重置已读，stopped 守卫未读。
- `v13/read_tools/test_read_tools.py` 的 `TOOL_ROWS`、`NEW_BANDS`、`BASELINE_TOOLS` 原文。形状沿用 Phase 0 §5，实现时必须重读。
- tool complete 对非 harness 工具的结果 jsonb 是否仍会拒绝某些键。已读的是 harness 谓词与 `effects.result` 赋值，不是「任意 jsonb 都成功」。
- `steer/injected` 的活体 INSERT。父审核搜索 `v13/` 没有找到写入者。本文件不把它标成已关闭。
- `harness_result_schema` 的完整属性表。`:35-64` 只证明名单不止先前那七个可选键。
- fourth-duty 这个词是否出现在 `v13_advance` 正文。
- `v13_transcript_hash` 的函数体。README 提到名字，本文不调用它。

## 4. 与 Phase 0 的关系

没有发现需要停笔的 Phase 0 内部矛盾。调查与 Phase 0 的冲突写在计划第 2 节，本文不跟随调查。

本轮没有改 Phase 0 计划，没有改 Phase 0 证据，没有改 `v13/`，没有改 `v13/load.py`。

## 5. 审核尝试

不是内容通过。

- 初稿 group `9B15EE78-B66C-4178-B793-FB8F6B7328B7`，chat `new-chat-A4CA8A`。导出 `prompt-exports/oracle-plan-2026-09-29-004628-new-chat-a4ca8a-94a8.md`。pair 修订的是主 lane，没有并入另外两份草稿。
- 审核 group `36846D6A-1670-4ABC-A4BA-DADEE9D98E4F`。包内没有本计划文件。导出 `prompt-exports/oracle-review-2026-09-29-005521-new-chat-f6d6eb-eb4b.md`。
- 续审 group `2C209810-0932-49FC-8D64-4C0ED3F307CB`，chat `new-chat-E1F8AE`。主 lane 声明 unread，无计数。lane 2 额度 402。lane 3 空响应。导出 `prompt-exports/oracle-review-2026-09-29-010119-new-chat-e1f8ae-a41e.md`。

选择缓存对本计划文件一直报 0 token，刷新未完成。因此不能把上述审核写成 P0=0 或 P1=0。

父组 `E232EF04-1D97-4BFD-9132-EBEC4A627FD3` 的内容分不是本规划轮跑出来的 gate。grok lane P0=0 P1=8 P2=5。kimi lane P0=0 P1=2 P2=3。codex lane 额度 402，不是通过。

父组 `5E9D44CE-3B36-47C2-A576-D225D54D45D1` 也不是通过。grok `new-chat-1D56EE`：P0=0 P1=4 P2=5。kimi `new-chat-oracle-3-5F5282`：P0=0 P1=1 P2=0。codex 再次 402。

父组 `1B4EAC94-AFF2-421E-A6F6-666864E93852` 也不是通过。grok `new-chat-47572A`：P0=0 P1=1 P2=0。kimi `new-chat-oracle-3-3F904F`：P0=0 P1=0 P2=2。codex 再次 402。本修订只改这两份候选文件。没有跑 gate，没有调用 provider，没有提交。

本修订重读：`v13/acl/v13_acl.sql:408-426`（llm 成功且带 `tool_calls` 时 complete 自己写 `tool/call`）；`v13/spawn/v13_spawn.sql:94-133` 与 `:246-256`（`v13_llm_tool_calls` 与 `tool/call` 守卫只接受 `spawn_subsession` / `task`）。没有把 `read_file_py` 写成共享 `tool/call` 类。

父组 `73A027A0-7DDE-48E0-91B6-0EF73AE24516` 不是通过。只有 grok `new-chat-F65F63` 完成：P0=0 P1=1 P2=2。codex 402，kimi 无内容。

合同复审 group `E4759295-BD50-405C-8E6E-D0D5367BD73D`：grok `new-chat-9AA744` P0=0 P1=0 P2=4；kimi `new-chat-oracle-3-817924` P0=0 P1=0 P2=2。codex 402 不是内容分。本修订只改 P2 措辞，不改合同。没有跑 gate，没有调用 provider，没有提交。
