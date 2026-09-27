# v13 分层控制面路线图全量验收（2026-09-27）

只取证、只成文。未改 `v13/`、未改计划、未改矩阵/台账、**未 commit**。

HEAD `b74f60eab69c890cd0745b9a813e089e35a492e7`（`b74f60e`）。验收合同 = `docs/plans/v13-layered-control-roadmap-2026-09-26.md` 三条 Phase 验收句、每期收尾（:237）、R4 对象面、红线 §5、parity 定位（:267，不是 gate）。

串行日志在本机临时目录，不进仓库。目录快照库 `agent_v13_accept_audit`（`load_stage(..., "triage")` 后逐文件加载 21–29）。

## §0 总判定

**GO。**

全量回归合同要求 30 脚本退出码全 0。决定性证据是空闲复跑：开始 `2026-09-27T15:54:46Z`，结束 `2026-09-27T15:59:52Z`，墙钟 **306.426 s**，**30/30 退出码 0**。见 §1。未降阈值。

满载首轮（`15:35:20Z`–`15:42:26Z`，并行探针同机）stage 11 L1 单红一次。隔离诊断与本次空闲全量复跑均绿。那次红不涂掉，也不改判。注记在 §1.1。

| 面 | 结果 |
|---|---|
| 全量回归合同（30 脚本串行全 0） | **满足。** 空闲复跑 30/30 退出码 0。满载首轮单红见 §1.1，不改判 |
| stage 21–29 自身 gate | 两轮退出码均 0 |
| 代码交付面 | A/B/C、加载序 29、止于 govern，已在 HEAD |
| R4 对象面（21–29） | 快照：public 表集合与列集合相对 stage 20 **零增量**。零新增 VIEW、零物化 |
| 红线（1–20 字节 / 加载序只追加 / 台账号） | 成立。见 §5 |
| 第四务真 worker | 仍是黄。假 worker 合同绿 |

矩阵第 85 行的 30 脚本全绿，由 §1 空闲复跑复现。满载首轮没有复现，已记 §1.1。

## §1 全量回归

决定性串行：仓库根 `uv run python v13/<stage>/test_*.py`，空闲机器、无并行 gate，未 `source ~/.zshrc`。开始 `2026-09-27T15:54:46Z`，结束 `2026-09-27T15:59:52Z`。墙钟 **306.426 s**。**30/30 退出码 0。**

stage 15 `mgraph` 两个脚本都跑了。读工具 `v13/read_tools/test_read_tools.py` 不在加载序，不在这 30 个里。

| # | stage | 脚本 | 开始 (UTC) | 退出码 | 耗时 (s) | 日志尾 |
|---|---|---|---|---:|---:|---|
| 1 | schema | `v13/schema/test_schema.py` | 2026-09-27T15:54:46Z | 0 | 2.261 | `[M1 schema] ALL PASS` |
| 2 | resolve | `v13/resolve/test_resolve.py` | 2026-09-27T15:54:48Z | 0 | 6.747 | `[M2 resolve] ALL PASS` |
| 3 | loop | `v13/loop/test_loop.py` | 2026-09-27T15:54:55Z | 0 | 10.570 | `[M3 loop] ALL PASS` |
| 4 | twophase | `v13/twophase/test_twophase.py` | 2026-09-27T15:55:05Z | 0 | 6.811 | `[M4 twophase] ALL PASS` |
| 5 | envelope | `v13/envelope/test_envelope.py` | 2026-09-27T15:55:12Z | 0 | 8.677 | `[envelope] ALL PASS` |
| 6 | manifest | `v13/manifest/test_manifest.py` | 2026-09-27T15:55:21Z | 0 | 8.914 | `[manifest] ALL PASS` |
| 7 | chunks | `v13/chunks/test_chunks.py` | 2026-09-27T15:55:30Z | 0 | 10.012 | `ALL PASS` |
| 8 | recall | `v13/recall/test_recall.py` | 2026-09-27T15:55:40Z | 0 | 11.500 | `ALL PASS` |
| 9 | characterize | `v13/characterize/test_characterize.py` | 2026-09-27T15:55:51Z | 0 | 7.537 | `ALL PASS` |
| 10 | filter | `v13/filter/test_filter.py` | 2026-09-27T15:55:59Z | 0 | 28.087 | `ALL PASS` |
| 11 | memory | `v13/memory/test_memory.py` | 2026-09-27T15:56:27Z | 0 | 8.279 | `ALL PASS` |
| 12 | economy | `v13/economy/test_economy.py` | 2026-09-27T15:56:35Z | 0 | 10.370 | `ALL PASS` |
| 13 | summary | `v13/summary/test_summary.py` | 2026-09-27T15:56:46Z | 0 | 11.999 | `ALL PASS` |
| 14 | periphery | `v13/periphery/test_periphery.py` | 2026-09-27T15:56:58Z | 0 | 7.874 | `ALL PASS (130 checks)` |
| 15 | mgraph | `v13/mgraph/test_mgraph.py` | 2026-09-27T15:57:06Z | 0 | 39.696 | `[mgraph M1+M2+M3+M4+v2-V1+V2] groups A+D+E+F+G+H: ALL GREEN` |
| 15 | mgraph | `v13/mgraph/test_stannum_usage.py` | 2026-09-27T15:57:45Z | 0 | 7.553 | `ALL PASS (71)` |
| 16 | mgraph_assembly | `v13/mgraph_assembly/test_mgraph_assembly.py` | 2026-09-27T15:57:53Z | 0 | 12.317 | `ALL J GREEN (W1: J1-J3; W2: J4-J7; W3: J8-J9)` |
| 17 | control | `v13/control/test_control.py` | 2026-09-27T15:58:05Z | 0 | 5.133 | `[PASS] stage 17 gates` |
| 18 | spawn | `v13/spawn/test_spawn.py` | 2026-09-27T15:58:10Z | 0 | 2.092 | `[PASS] stage 18 gates` |
| 19 | fanout | `v13/fanout/test_fanout.py` | 2026-09-27T15:58:12Z | 0 | 2.468 | `[done] fanout` |
| 20 | triage | `v13/triage/test_triage.py` | 2026-09-27T15:58:15Z | 0 | 2.512 | `[done] triage` |
| 21 | seam | `v13/seam/test_seam.py` | 2026-09-27T15:58:17Z | 0 | 5.991 | `[PASS] stage 21 gates` |
| 22 | catalog | `v13/catalog/test_catalog.py` | 2026-09-27T15:58:23Z | 0 | 4.228 | `[catalog] ALL PASS` |
| 23 | acl | `v13/acl/test_acl.py` | 2026-09-27T15:58:27Z | 0 | 2.665 | `[acl] ALL PASS (197)` |
| 24 | observe | `v13/observe/test_observe.py` | 2026-09-27T15:58:30Z | 0 | 2.119 | `[observe] ALL PASS (147)` |
| 25 | handoff | `v13/handoff/test_handoff.py` | 2026-09-27T15:58:32Z | 0 | 2.435 | `[handoff] ALL PASS (240)` |
| 26 | should_run | `v13/should_run/test_should_run.py` | 2026-09-27T15:58:35Z | 0 | 2.541 | `[should_run] ALL PASS (194)` |
| 27 | quota_window | `v13/quota_window/test_quota_window.py` | 2026-09-27T15:58:37Z | 0 | 68.597 | `[quota_window] ALL PASS (226)` |
| 28 | attention | `v13/attention/test_attention.py` | 2026-09-27T15:59:46Z | 0 | 3.079 | `[attention] ALL PASS (156)` |
| 29 | govern | `v13/govern/test_govern.py` | 2026-09-27T15:59:49Z | 0 | 3.348 | `[govern] ALL PASS (228)` |

### 1.1 时延敏感注记（不改判）

stage 11 L1 是 wall-clock p99 时延界，不是投影/召回语义。源文 `v13/memory/test_memory.py:600-603`：

```python
med_base = sorted(base_p99s)[1]
med_loaded = sorted(loaded_p99s)[1]
bound = max(med_base * 1.25, med_base + 0.5)
check("L1: p99 loaded <= max(x1.25, +0.5ms)",
      med_loaded <= bound, (med_base, med_loaded, bound))
```

满载串行（`2026-09-27T15:35:20Z`–`15:42:26Z`，墙钟 426.417 s，并行探针同机）单红一次：退出码 1，13.177 s。基线三轮 p99 `[1.447, 1.909, 4.264]` ms，中位 **1.909**；负载中位 **8.037**；界 **2.409**。K4 及之前功能断言同次日志为 PASS。

隔离诊断复跑退出码 0：L1 中位 base=0.105 ms、loaded=0.251 ms、界=0.605 ms。未单独记墙钟。

本节空闲全量复跑 memory 退出码 0，8.279 s，`ALL PASS`。L1 中位 base=0.125 ms、loaded=0.218 ms、界=0.625 ms。

该文件字节在 Phase A 冻结点之后零改动（§5）。同日早间复核亦绿（`2026-09-27T11:46:03Z`，8.594 s）。不降标准：满载单红仍记下。隔离与空闲复跑均绿，故不改判。

## §2 三条 Phase 验收句

子句用本轮已绿脚本里的断言名 + 行号。不重跑单断言。memory 红不进入这三句的 gate 集合。

### 2.1 Phase A — 成立（第四务只到合同，不关闭 R4）

路线图验收读法：续传不再被已答 cap 卡死；首次成功 release 写 `worktree/released`、latch 仍 `prepared`、`v13_worktree_state` 折叠 `released`；第四务有驱动合同；`children_terminal` 能走完 advance；parse 能看见具名 sql 工具。

本轮 `v13/seam/test_seam.py` 退出码 0，尾 `[PASS] stage 21 gates`。`v13/catalog/test_catalog.py` 退出码 0，尾 `[catalog] ALL PASS`。

| 子句 | 断言 | 位置 | 本轮 |
|---|---|---|---|
| 续传不再被已答 cap 卡死 | `W1/G11 advance after finish does not raise`；`W1 closeout completed` | `v13/seam/test_seam.py:673`、`:675` | seam 绿 |
| 首次成功 release 写 `worktree/released` | `one released event` | `v13/seam/test_seam.py:810` | seam 绿 |
| latch 仍 `prepared` | `latch row still prepared` | `v13/seam/test_seam.py:814` | seam 绿 |
| `v13_worktree_state` 折叠 `released` | `projection released` | `v13/seam/test_seam.py:812` | seam 绿 |
| `children_terminal` 走完 advance | `children_terminal unsatisfied parks`；`children_terminal satisfied continues index+1` | `v13/seam/test_seam.py:749`、`:760` | seam 绿 |
| parse 看见具名 sql 工具 | `P1 base route catalog RED`；`P2 base parse reaches catalog RED`；`G catalog green and spawn exempt`；`post resolve parse green` | `v13/catalog/test_catalog.py:121`、`:126`、`:476`、`:710` | catalog 绿 |
| 第四务有驱动合同 | `fourth_duty`（假 worker） | `v13/catalog/test_catalog.py:308` | 合同绿。真接线不是 ✅，见 §7.4 |

### 2.2 Phase B — 成立（合同绿，驱动器未交付）

验收读法：动词组闭合 = 观察（含多 id 全量授权）/ 注入 / 应答 / 取消 / 授权 / 交接。

没有一条检查名叫「route 非超户六动词」。总验收是 `v13/handoff/test_handoff.py:1026` `run_six`，`:1043` `SET ROLE v13_route`，`:1086` 打印 `observe=ok log=ok inject=ok respond=ok cancel=ok authorized=ok extract=ok`。本轮 handoff 退出码 0，尾 `[handoff] ALL PASS (240)`。矩阵第 61 行记同一句。

| 动词 | 断言 | 位置 | 本轮 |
|---|---|---|---|
| 授权 | `six authorized` | `v13/handoff/test_handoff.py:1045` | handoff 绿 |
| 观察 | `six observe`；`six session_log` | `:1047`、`:1049` | handoff 绿 |
| 观察（多 id 全量授权） | `mixed zero {label}` | `v13/observe/test_observe.py:420` | observe 绿（147） |
| 注入 | `six inject`；`six inject kept` | `v13/handoff/test_handoff.py:1053`、`:1068` | handoff 绿 |
| 应答 | `six respond`；`six respond kept` | `:1058`、`:1073` | handoff 绿 |
| 取消 | `six cancel`；`six cancel kept` | `:1060`、`:1075` | handoff 绿 |
| 交接 | `six extract`；`six extract kept` | `:1062`、`:1079` | handoff 绿 |

注入/应答/取消的动词体在 stage 17–20；本轮 control/spawn/fanout/triage 退出码均 0。授权、多目标观察、交接的闭合证据是上表，不是那四个旧脚本单独构成的。

### 2.3 Phase C — 成立（性质 gate 绿；残留不因此闭合）

验收读法：自动推进有唯一门 / 资格可从窗口重算且 ≠ 奖励 / 可停可复且停 ≠ cancel ≠ 删行 / 注意力与调度提示无副作用。

| 性质 | 关键断言 | 位置 | 本轮 |
|---|---|---|---|
| 唯一门（L26） | `duty 0 effect count` | `v13/should_run/test_should_run.py:550` | should_run 绿（194） |
| 窗口重算且 ≠ 奖励（L6+L37+L38） | `missing quota writes nothing` | `v13/quota_window/test_quota_window.py:421` | quota_window 绿（226） |
| 停 ≠ cancel ≠ 删行（L32） | `stop no cancel` | `v13/govern/test_govern.py:396` | govern 绿（228） |
| 注意力/提示无副作用（L5+L21） | `two calls zero events`；`cron.job absent` | `v13/attention/test_attention.py:393`、`:564` | attention 绿（156） |

「不超售已闭合」**不得**从本句推出。复活窗口断言是 `revive raises cap`（`v13/govern/test_govern.py:1463`），台账 PC-8 明文不标闭合。

## §3 每期收尾（路线图 :237）

条款：该 stage `test_*.py` 退出码 0；回归此前全部 gate；`SQL_LOAD_ORDER` 只追加；覆盖矩阵、偏差台账、该 stage `README.md` 已更新。

工件在仓库里齐：

- 加载序 29，只追加。见 §5.2。
- stage 21–29 各有 `README.md`（seam / catalog / acl / observe / handoff / should_run / quota_window / attention / govern）。
- 矩阵 `docs/reviews/v13-control-plane-conformance-matrix-2026-09-26.md` 行 49–85 覆盖 Phase A/B/C，状态格都是实跑 ✅（各 stage 自己的日期记录，不是本轮）。
- 台账 Phase A/B/C 段已有 F23–F31、C15–C18、PC-1–PC-8。见 §5.3。

空闲复跑（§1）30/30 退出码 0，复现矩阵第 85 行。满载首轮没有，见 §1.1。收尾工件齐。

## §4 架构审计（R4）

探针：新建 `agent_v13_accept_audit`，`load_stage` 至 triage（20），快照 public `pg_class` / `pg_attribute` / 索引 / 触发器 / 函数 / `v13_policies` / `v13_%` 角色；再按 `SQL_LOAD_ORDER[20:]` 九个文件逐个 `psql` 加载并记增量。

stage 20 基线：关系 31（`r` 29 + `v` 2）、列 250、索引 66、触发器 47、public 函数 346、策略行 35。既有 VIEW：`v13_template_latest`、`v_routes`。无 `relkind=m`。

九文件加载后：

| 核对 | 结果 |
|---|---|
| public 表集合（relkind `r`）相对 stage 20 | **空增量** |
| 列（表名, attnum, 名, 类型, NOT NULL） | **增量 0**（基线 250） |
| 新增 VIEW / 物化 | **无**。两 VIEW 仍是 stage 20 那两个 |
| 新表 / 新列 | **无** |

stage 20 表名（29，加载 21–29 后不变）：`artifacts`、`chunks`、`decisions`、`effects`、`events`、`judgment_cache`、`judgment_calls`、`judgment_templates`、`latches`、`memory_consolidations`、`memory_links`、`memory_nodes`、`memory_rounds`、`memory_walks`、`sessions`、`thresholds`、`tools`、`transcript_chunks`、`v13_canary_docs`、`v13_chunks_meta`、`v13_goals`、`v13_judgment_template_versions`、`v13_mgraph_meta`、`v13_policies`、`v13_pricing`、`v13_remote_sqlstates`、`v13_route_policies`、`v13_sources`、`v13_tools_meta`。

`worktree/released`、`control/handoff`、`goal/stopped` 不在任何 CHECK 约束正文里。开放事件，不是新类型表。

### 4.1 部分唯一索引（恰 3 个）

相对 stage 20 新出现的 UNIQUE 部分索引只有这三个：

| 名 | 定义（活体 `pg_get_indexdef`） | 文件 |
|---|---|---|
| `ux_events_worktree_released` | `events (session_id, (payload->>'binding_artifact_id')) WHERE type='worktree/released'` | seam |
| `ux_events_handoff_delivery` | `events ((payload->>'delivery_id')) WHERE type='control/handoff'` | handoff |
| `ux_events_handoff_snapshot` | `events (session_id, (payload->>'up_to_seq'), (payload->>'transcript_hash')) WHERE type='control/handoff'` | handoff |

另有 **2 个非唯一**部分索引，不混进上一表：`ix_events_material_spent_at`（quota_window，`events (session_id, at) WHERE type='turn/material_spent'`）、`ix_events_goal_lifecycle`（govern，`events (session_id, seq DESC) WHERE type IN ('goal/stopped','goal/resumed')`）。它们是索引，不是表/列/VIEW。D15 允许 events 上的部分索引；不把它们说成「唯一索引恰 5 个」。

### 4.2 守卫触发器（4）

| 名 | 活体 |
|---|---|
| `trg_v13_seam_event_guard` | BEFORE INSERT ON events WHEN `type='worktree/released'` → `v13_seam_event_guard()` |
| `trg_handoff_guard` | BEFORE INSERT ON events WHEN `type='control/handoff'` → `v13_handoff_event_guard()` |
| `trg_material_time_honest` | BEFORE INSERT ON events WHEN `type='turn/material_spent'` → `v13_material_time_honest()` |
| `trg_v13_goal_event_guard` | BEFORE INSERT ON events WHEN `type IN ('goal/stopped','goal/resumed')` → `v13_goal_event_guard()` |

### 4.3 角色

`v13/handoff/v13_handoff.sql:57` `CREATE ROLE v13_handoff_owner`。加载后 `v13_handoff_emit` 的 owner 是该角色，`prosecdef=true`，`provolatile=v`。

本探针 **没有**看到新角色行：串行 gate 已经在集群里留下 `v13_handoff_owner`（以及既有 `v13_recall` / `v13_resolve` / `v13_route` / `v13_spawn_owner` / `v13_triage_owner` / `v13_worker` 与两个 login）。不能用这次快照证明「本进程执行了 CREATE ROLE」。能证明的是：handoff 加载成功，且 emit 属主是该角色。没有第二个新角色名出现在 21–29 的增量里。

### 4.4 策略行增量

| name | version | 加载后 active |
|---|---:|---|
| `handoff_policy` | 1 | true（handoff 新建） |
| `should_run` | 1 | false（should_run 插入后，quota_window 翻掉） |
| `should_run` | 2 | false（quota_window 插入后，govern 翻掉） |
| `should_run` | 3 | true（govern 新建） |
| `capabilities` | 1 | true |
| `quota_window` | 1 | true |

### 4.5 逐文件对象面

「新函数」= 相对前一文件的新 `(proname, 参数身份)`。`vol` 是活体 `provolatile`（`s`=STABLE，`v`=VOLATILE）。同签名 `CREATE OR REPLACE` 不出现在新身份里，另行列出。行号是源文件，已对过 `CREATE OR REPLACE` / `CREATE ROLE`。

| stage | 文件 | 新身份（活体） | 同签名换体（源） | 写面 / 其他 |
|---|---|---|---|---|
| 21 | `v13/seam/v13_seam.sql` | `v13_cap_answer_anchor` s；`v13_tail_gap_cap_exempt` s；`v13_worktree_state` s；`v13_record_worktree_released` v；`v13_seam_event_guard` v | `v13_cap_human_answered` :167；`v13_harness_tail_gap` :240；`v13_complete` 五参 :409；`v13_resolve_unknown` :590 | 事件 `worktree/released`；唯一索引 + 守卫。零表零列 |
| 22 | `v13/catalog/v13_catalog.sql` | 无 | `v13_tools_catalog_frozen` :3 | 零新关系、零索引、零触发器、零策略行 |
| 23 | `v13/acl/v13_acl.sql` | `v13_control_operator` s；`v13_control_authorized` s；`v13_cancel(uuid,uuid)` v；`v13_complete` 六参 v | `v13_cancel(uuid)` :236；`v13_complete` 五参 :459 | 函数体内 `CREATE TEMP TABLE` :144，`ON COMMIT DROP`，**未**进 public `pg_class` |
| 24 | `v13/observe/v13_observe.sql` | `v13_observe` s；`v13_session_log` s | 无 | 只读。零写面对象 |
| 25 | `v13/handoff/v13_handoff.sql` | `v13_transcript_hash` s；`v13_handoff_emit` v SECURITY DEFINER owner=`v13_handoff_owner`；`v13_handoff_event_guard` v；`v13_extract_handoff` v | 无 | 事件 `control/handoff`；两唯一索引；守卫；`handoff_policy` v1；角色见 §4.3 |
| 26 | `v13/should_run/v13_should_run.sql` | `v13_policy_share` v SECURITY DEFINER owner=`v13_spawn_owner`；`v13_should_run` s；`v13_should_run_gate` s | `v13_triage_prework` :212；`v13_advance` :258 | `should_run` v1 |
| 27 | `v13/quota_window/v13_quota_window.sql` | `v13_quota_eligible` s；`v13_missing_capabilities` s；`v13_material_time_honest` v | `v13_should_run_gate` :216（身份已在 26，本文件不记新身份） | `quota_window` v1、`capabilities` v1；`should_run` v2 并翻 v1；非唯一索引 + 时间守卫 |
| 28 | `v13/attention/v13_attention.sql` | `v13_spawn_budget_snapshot` s；`v13_attention` s；`v13_scheduler_hint` s | 无 | 零事件类型、零策略 INSERT、零索引 |
| 29 | `v13/govern/v13_govern.sql` | `v13_goal_fingerprint` s；`v13_goal_fold` s；`v13_goal_lifecycle` s；`v13_goal_event_guard` v；`v13_goal_stop` v；`v13_goal_resume` v；`v13_spawn_batch_allowed` v SECURITY DEFINER owner=`v13_spawn_owner` | `v13_should_run_gate` :361；`v13_recover_idle` :453；`v13_scheduler_hint` :517；`v13_advance` :720。`v13_attention` 同签名重建，增量里不是新身份 | 事件 `goal/stopped`、`goal/resumed`；非唯一索引 + 守卫；`should_run` v3 并翻 v2 |

21–29 的持久化增量停在：函数、开放事件 type、策略行、上列索引、一个既有/本文件声明的角色、四枚守卫触发器。没有新表、新列、新 VIEW、物化视图。

## §5 红线

### 5.1 stage 1–20 字节

冻结点取 seam 引入提交的父：`e925ebe`（`v13: add seam stage...`）的父 `3f29dac62084a5d3ac6da2ca27acac4c3cdac358`。

`git diff --stat 3f29dac HEAD --` stage 1–20 的 20 个 SQL 与 20 个目录：**空**。`git log 3f29dac..HEAD --` 这些目录：**无提交**。

这是「Phase A 开工之后零改动」，不是「每个文件自出生提交起再没被 1–20 内部后段碰过」。例如 `v13_core.sql` 末笔是 loop 提交 `7499f5e`，`v13_spawn.sql` / `v13_triage.sql` 末笔是 `cd4adb2`（stage 18–20 helper grant）。那些提交都在冻结点之前。

### 5.2 加载序只追加

`git show 3f29dac:v13/load.py` 的 `SQL_LOAD_ORDER` **20** 项，与 HEAD 前 20 项逐字相同。HEAD **29** 项，序号连续，追加 seam…govern。`v13/load.py` 相对冻结点 `+18` 行，无删除。`STAGE_THROUGH`：`schema=1` … `govern=29`（`v13/load.py:45-75`）。

### 5.3 台账号

`docs/reviews/v13-control-plane-deviation-ledger-2026-09-26.md`：

- F23–F31：行 120–135，无空洞、无重复。
- C15–C18：行 139–141、149。C18 排在 PC-2 之后，编号无空洞无重复。
- PC-1–PC-8：行 147–155，无空洞无重复。

范围外如实记一笔：F22 出现两次（:99 热修潜在缝，:124 Phase A catalog 缝关闭行）。不是 F23–F31 的空洞。台账 F22 是 catalog 缝，不是 parity 的 worktree F22（路线图 :237、:252）。

### 5.4 覆盖矩阵

`docs/reviews/v13-control-plane-conformance-matrix-2026-09-26.md` 行 1–48 覆盖 stage 1–20（含回归行），行 49–85 覆盖 21–29。各行状态格为实跑 ✅，测试格带日期与退出码。行齐。

行 85 写「stage 1–29 回归 … 30 脚本 … 退出码均 0」。§1 空闲复跑复现该结果。满载首轮没有，见 §1.1。

## §6 裁决链与 D1–D16

R13b / R13c 没有独立文件。R13b 在 `docs/reviews/v13-control-plane-oracle-r13-2026-09-27.md:34`。R13c 在同文件 `:62`。

| 轮 | 裁什么 | 记录 |
|---|---|---|
| R2 | D1 四值 `result_kind`；D2 `kind=sql` + 具名 VOLATILE 例外，否路径 B；D3 triage 10a/10b | `docs/reviews/v13-control-plane-oracle-r2-2026-09-21.md` |
| R3 | D4 `v13_open_session`；D5 unknown 墙 + resolve 清回 ready；D6 同文件 §0（本轮摘录停在 D5 行，不代写 D6 句） | `docs/reviews/v13-control-plane-oracle-r3-2026-09-26.md` |
| R3b | 补裁：D4–D6 不重开；H / A16 / P1 机器形状。开篇是导出头，标题在 :14 | `docs/reviews/v13-control-plane-oracle-r3b-full-2026-09-26.md` |
| R3c | 全文导出，开篇同为导出头。本轮未摘正文标题，不代写裁定句 | `docs/reviews/v13-control-plane-oracle-r3c-full-2026-09-26.md` |
| R4 | 立场 A：函数/事件/策略行；零新表零列；13/29/29 不变 | `docs/reviews/v13-control-plane-oracle-r4-2026-09-26.md` |
| R5 | D11–D14 + 第四务落点；D13 不移植；真接线天花板黄 | `docs/reviews/v13-control-plane-oracle-r5-2026-09-26.md` |
| R6 | D11 删无事件盖章分支；自身 post-anchor 事件即盖章 | `docs/reviews/v13-control-plane-oracle-r6-2026-09-27.md` |
| R7 | D12 守卫改无锁 MVCC；写者仍 latch `FOR UPDATE` + 两条语句 | `docs/reviews/v13-control-plane-oracle-r7-2026-09-27.md` |
| R7b | 并发日程改生产序 sessions→latch | `docs/reviews/v13-control-plane-oracle-r7b-2026-09-27.md` |
| R8 | D7 甲 overload；C15 状态中立；D16 四键 + DEFINER 单写者 | `docs/reviews/v13-control-plane-oracle-r8-2026-09-27.md` |
| R9 | D14 断言 B′ 裸名同域 | `docs/reviews/v13-control-plane-oracle-r9-2026-09-27.md` |
| R10 | P8a 同域二选一，活体形态 H，换体保持 NULL | `docs/reviews/v13-control-plane-oracle-r10-2026-09-27.md` |
| R11 | 投毒矩阵按全库 proname 解析层重排 | `docs/reviews/v13-control-plane-oracle-r11-2026-09-27.md` |
| R12 | 夹具 3 臂 D 改真行 fail-closed；限定证明改源码断言 + 臂 E | `docs/reviews/v13-control-plane-oracle-r12-2026-09-27.md` |
| R13 | D10-A/B、D15、L29、小题①–⑩；五行锁范围外的翻版竞态留残留 | `docs/reviews/v13-control-plane-oracle-r13-2026-09-27.md` |
| R13b | 小题③查 operator；小题⑥保留 `resolve/failed` 预检 | 同上 :34 |
| R13c | `current_setting` 差集断言；审计臂分阶段；不装新 parent 守卫（既有 fork-cols 执法） | 同上 :62；计划修订提交 `610263f` / `055f88d` |

| D | 状态 | 轮 |
|---|---|---|
| D1 | 已裁 | R2 |
| D2 | 已裁（用户拍板 A） | R2 |
| D3 | 已裁 | R2 |
| D4 | 已裁 | R3 |
| D5 | 已裁 | R3 |
| D6 | 已裁（同 R3 §0；本轮未摘该行原文） | R3 |
| D7 | 已裁 | R8。路线图 :245 |
| D8 | 已裁 | R4。路线图 :246 |
| D9 | 已裁公式；种子/计次残留 = PC-3/PC-4 | R4；台账 :150–151 |
| D10 | 已裁 | R13。路线图写作时仍标「是/不开工就停」，后被 R13 收口 |
| D11 | 已裁 | R5+R6 |
| D12 | 已裁；锁协议后经 R7/R7b | R5，R7，R7b |
| D13 | 已裁，零 SQL | R5。台账 F23 |
| D14 | 已裁；绑定式后经 R9–R12 | R5，R9–R12 |
| D15 | 已裁 | R13 |
| D16 | 已裁 | R8 |

D1–D6 路线图 :239 声明不重开。本表不重开它们。

## §7 残留（不粉饰）

### 7.1 点名六条

| # | 残留 | 锚 |
|---|---|---|
| 1 | 小题⑨终态兄弟复活超售窗口。不承诺零 RAISE，也不承诺绝对不超售 | 台账 PC-8 :155；R13 :29、:50；矩阵行 81 :102；gate `revive raises cap` `v13/govern/test_govern.py:1463`。README/台账写 `test_revive_race_backstop`，源函数名是 `test_revive_race` |
| 2 | attention 树遍历无界。传 1 仍扫全树；返回行数预算不保遍历成本 | 台账 PC-6 :153；R13 :20、:52 |
| 3 | 非五行策略翻版竞态。`v13_policy_share` 只锁 capabilities / quota_window / should_run / spawn_budget / triage。`turn_budget`、`effect_attempt_cap` 在协议外 | R13 :32、:51 |
| 4 | R4 真 worker 第四务 = 黄。假 worker 合同本轮绿。gitignored 驱动器实跑过，未进仓库 | Phase A 计划 §4.5 :298–309；`v13/catalog/README.md:27-30`；矩阵行 51 :62。本轮未重跑真实 provider，也未把黄改成 ✅ |
| 5 | 驱动器 / UI 未交付。合同绿 ≠ 生产路径已接线 | 台账 F28 :132；矩阵行 52 :68、55 :71、63 :84、79 :99、82 :103；parity :257、:281 |
| 6 | parity 套件 15 组是真实 API 证据，**不是 gate** | 路线图 :267；parity :44（gitignore，不是 stage gate）；parity :281 `demo_v13/parity/parity_all.py` 15/15 退出码 0（HEAD 提交 `b74f60e` 所记，**本轮未重跑**） |

### 7.2 台账另收（不并进上表，以免把已点名的再说一遍）

| ID | 一句 | 锚 |
|---|---|---|
| F24 | D11 无自身事件的 ready/claimed 永不盖章；重泵 (b) `waiting`、零写 | 台账 :121 |
| F25 | 无锁旁路直插可在写者窗口内造成 23505；生产两调用点同经行锁 | 台账 :122 |
| F26 | D14 残留 R-1：同名第二函数到不了深检 | 台账 :125 |
| PC-3 | 松种子 `window_hours=8760` / `allowed=1000000` 不是产品额度 | 台账 :150 |
| PC-4 | `v13_quota_eligible` 只计本会话，不沿树 | 台账 :151 |

F28 并入 §7.1 第 5 条，不重复计数。PC-5（hint ≠ ack、无 cron）、PC-7（fingerprint 不改 `v13_state_hash`）是已接受的设计边界，写在 §8 的禁写句里，不另开「未交付缺口」。

满载首轮 memory L1 单红已由空闲复跑翻绿，不是路线图新缺口，不计入上表。见 §1.1。

## §8 总声明，以及不得写的句子

**交付面：** 路线图 A/B/C 三 Phase 已落地。加载序 29，止于 `v13/govern/v13_govern.sql`。stage 21–29 的 gate 在本轮退出码为 0。对象面没有新表新列新 VIEW 新物化。

**本轮验收合同：** 通过。空闲复跑 30/30 退出码 0。总判定 GO。满载首轮 L1 单红见 §1.1，不改判。

**parity 分桶：** 71 条仍是 **13 补齐 / 29 改变 / 29 永不建**。原文在路线图 :17。parity :270 写明 stage 29 之后「不改上文 2026-09-26 的 13/29/29 计数表」；已补条目进「改变」桶注记，不改标成一模一样。

下列句子 **不得**出现在把本 HEAD 说成验收通过的文字里：

- 「满载首轮也全绿」——那一轮 memory L1 为 1。可写的是：空闲复跑 30/30 退出码 0；满载单红见 §1.1。
- 「不超售已闭合」——PC-8。只可写「无并发复活且非 explore 时不 RAISE」。
- 「F17 已在生产路径生效」——F28。只可写合同已证明、驱动器未交付。
- 「pg_cron 已在生产调度」——PC-5。`cron.job absent` 是「没有注册」，不是「已在调度」。
- 「R4 真 worker 第四务已完成」——计划 §4.5。最高黄。
- 「已配置 24 小时 8 次」——PC-3。
- 「目标已可在 UI 停复」——矩阵行 79。
- 「spawn 函数已不再报 cap」——parity :278。直调仍 RAISE。
- 「parity 套件是 gate」——路线图 :267。15/15 是真实 API 记录，本轮未重跑。

## §9 本轮未做

- 未 commit、未 push、未改矩阵第 85 行。
- 未 `source ~/.zshrc`，未重跑 parity 15 组。
- 未把 memory 诊断复跑写进 §1 的退出码列。
- 未逐段复读 `v13-control-plane-oracle-r3c-full-2026-09-26.md` 的裁定正文，故 §6 不代写该轮一句。
- 未对九个 SQL 文件做 `pg_terminate_backend` 全文扫描；对象面结论来自目录快照，不来自字符串搜索。
