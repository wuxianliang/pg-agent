# v13 Phase C §9 复核：Phase B 落地后（2026-09-27）

只取证。未改 `v13/`、未改计划、未 commit。探针库 `agent_v13_pc_recheck`（`load_stage(..., "handoff")` + handoff `setup_db.py` 的 stannum GRANT）。函数锚与错误文案在 `/tmp/v13-pc-recheck/probe.out`（不进仓库）。行号指当前 HEAD 源文件；stage 1–20 SQL 与 `e6a8340` 字节相同，行号未漂。

HEAD `8678ebff879917c1069e88d4abc2cef8cdc761d3`（`8678ebf`，r41 终裁提交）。handoff 提交 `d5b701f` 是其祖先。

## §0 总判定

**GO。**

B1–B14 无一条走进「不符时」。三条开工硬门：

| 硬门 | 结果 |
|---|---|
| r41 已出 | 满足。本 HEAD 即 `docs/plans/v13-phase-c-governance-projections-plan-2026-09-27.md` 终裁提交；裁决在 `docs/reviews/v13-control-plane-oracle-r13-2026-09-27.md` |
| Phase B 全绿 + §9 GO | 满足。26/26 脚本退出码 0；B1–B14 见 §1–§3 |
| RED（L29 cap RAISE）留证 | 满足，记在本报告 §4。stage 29 README 由实施者从 §4 转录；本任务不写 README、不建 `v13/govern` |

### Gate 全绿

命令：仓库根 `uv run python v13/<stage>/test_*.py`，串行。墙钟含 uv 启动与各自 DROP/CREATE/加载。日志 `/tmp/v13-pc-recheck/gates.tsv` 与同目录 `*.log`。开始 `2026-09-27T11:44:16Z`，结束 `2026-09-27T11:48:15Z`。**26/26 脚本退出码 0；25/25 stage 绿。** 脚本耗时合计 237.190 s。任一非 0 则本判定改为 STOP；没有。

stage 15 `mgraph` 两个脚本都跑了。acl/observe/handoff = 23/24/25。

| stage | 脚本 | 开始 (UTC) | 退出码 | 耗时 (s) | 日志尾 |
|---|---|---|---|---|---|
| 1 schema | `v13/schema/test_schema.py` | 2026-09-27T11:44:16Z | 0 | 2.090 | `[M1 schema] ALL PASS` |
| 2 resolve | `v13/resolve/test_resolve.py` | 2026-09-27T11:44:18Z | 0 | 6.686 | `[M2 resolve] ALL PASS` |
| 3 loop | `v13/loop/test_loop.py` | 2026-09-27T11:44:25Z | 0 | 10.042 | `[M3 loop] ALL PASS` |
| 4 twophase | `v13/twophase/test_twophase.py` | 2026-09-27T11:44:35Z | 0 | 6.558 | `[M4 twophase] ALL PASS` |
| 5 envelope | `v13/envelope/test_envelope.py` | 2026-09-27T11:44:42Z | 0 | 8.540 | `[envelope] ALL PASS` |
| 6 manifest | `v13/manifest/test_manifest.py` | 2026-09-27T11:44:50Z | 0 | 12.754 | `[manifest] ALL PASS` |
| 7 chunks | `v13/chunks/test_chunks.py` | 2026-09-27T11:45:03Z | 0 | 10.272 | `ALL PASS` |
| 8 recall | `v13/recall/test_recall.py` | 2026-09-27T11:45:13Z | 0 | 11.866 | `ALL PASS` |
| 9 characterize | `v13/characterize/test_characterize.py` | 2026-09-27T11:45:25Z | 0 | 7.752 | `ALL PASS` |
| 10 filter | `v13/filter/test_filter.py` | 2026-09-27T11:45:33Z | 0 | 29.957 | `ALL PASS` |
| 11 memory | `v13/memory/test_memory.py` | 2026-09-27T11:46:03Z | 0 | 8.594 | `ALL PASS` |
| 12 economy | `v13/economy/test_economy.py` | 2026-09-27T11:46:12Z | 0 | 10.191 | `ALL PASS` |
| 13 summary | `v13/summary/test_summary.py` | 2026-09-27T11:46:22Z | 0 | 12.025 | `ALL PASS` |
| 14 periphery | `v13/periphery/test_periphery.py` | 2026-09-27T11:46:34Z | 0 | 7.976 | `ALL PASS (130 checks)` |
| 15 mgraph | `v13/mgraph/test_mgraph.py` | 2026-09-27T11:46:42Z | 0 | 37.849 | `[mgraph M1+M2+M3+M4+v2-V1+V2] groups A+D+E+F+G+H: ALL GREEN` |
| 15 mgraph | `v13/mgraph/test_stannum_usage.py` | 2026-09-27T11:47:20Z | 0 | 7.643 | `ALL PASS (71)` |
| 16 mgraph_assembly | `v13/mgraph_assembly/test_mgraph_assembly.py` | 2026-09-27T11:47:28Z | 0 | 13.121 | `ALL J GREEN (W1: J1-J3; W2: J4-J7; W3: J8-J9)` |
| 17 control | `v13/control/test_control.py` | 2026-09-27T11:47:41Z | 0 | 6.681 | `[PASS] stage 17 gates` |
| 18 spawn | `v13/spawn/test_spawn.py` | 2026-09-27T11:47:48Z | 0 | 3.231 | `[PASS] stage 18 gates` |
| 19 fanout | `v13/fanout/test_fanout.py` | 2026-09-27T11:47:51Z | 0 | 2.558 | `[done] fanout` |
| 20 triage | `v13/triage/test_triage.py` | 2026-09-27T11:47:54Z | 0 | 2.788 | `[done] triage` |
| 21 seam | `v13/seam/test_seam.py` | 2026-09-27T11:47:57Z | 0 | 7.244 | `[PASS] stage 21 gates` |
| 22 catalog | `v13/catalog/test_catalog.py` | 2026-09-27T11:48:04Z | 0 | 3.644 | `[catalog] ALL PASS` |
| 23 acl | `v13/acl/test_acl.py` | 2026-09-27T11:48:08Z | 0 | 2.665 | `[acl] ALL PASS (197)` |
| 24 observe | `v13/observe/test_observe.py` | 2026-09-27T11:48:10Z | 0 | 2.030 | `[observe] ALL PASS (147)` |
| 25 handoff | `v13/handoff/test_handoff.py` | 2026-09-27T11:48:12Z | 0 | 2.433 | `[handoff] ALL PASS (240)` |

## §1 B1–B5

### B1 加载序 25，handoff 已提交且 1→25 绿 — 成立

`v13/load.py:17-42` `SQL_LOAD_ORDER` 长度 **25**。末三项 `acl` / `observe` / `handoff`。`v13/load.py:45-71` `STAGE_THROUGH`：`acl=23`、`observe=24`、`handoff=25`。

四件齐：`v13/handoff/{v13_handoff.sql,setup_db.py,test_handoff.py,README.md}`，提交 `d5b701f`（`v13: add handoff receipt event`），是 HEAD 祖先。gate 见 §0。

写作时证据（计划 §9 表：handoff 已注册未提交，已提交末笔 = observe `7b0e53c`）已被落地取代。这是 B1 **期望**，不是不符。`7b0e53c` 与 `d33eed9` 仍是祖先。

### B2 cancel 正文 + 包装 — 成立

探针各恰 1 个 overload。

| 身份 | owner | prosecdef | provolatile | proconfig | 体 |
|---|---|---|---|---|---|
| `v13_cancel(p_actor uuid, p_sid uuid)` | postgres | false | v | `search_path=pg_catalog, public` | 正文。源 `v13/acl/v13_acl.sql:121` |
| `v13_cancel(p_sid uuid)` | postgres | false | v | 无 | 包装。prosrc 为 `RETURN v13_cancel(NULL::uuid, p_sid);`。源 `v13/acl/v13_acl.sql:236-241` |

无 `EXCEPTION WHEN`（`position=0`）。签名与「2 参正文、1 参 `actor=NULL` 包装」一致。不停。

### B3 complete 六参正文 + 五参包装 — 成立

| 身份 | prosecdef | provolatile | proconfig |
|---|---|---|---|
| `v13_complete(p_actor uuid, p_effect uuid, p_attempt integer, p_fence bigint, p_status text, p_result jsonb)` | false | v | `search_path=pg_catalog, public` |
| `v13_complete(p_effect uuid, p_attempt integer, p_fence bigint, p_status text, p_result jsonb)` | false | v | 无 |

源：正文 `v13/acl/v13_acl.sql:245`；包装 `v13/acl/v13_acl.sql:459-466`，体为 `RETURN v13_complete(NULL::uuid, ...)`。

D12 仍在：正文 prosrc 含 `v13_record_worktree_released`，源 `v13/acl/v13_acl.sql:473`。

无吞异常：两 overload 的 `EXCEPTION WHEN` position 均为 0。正文里的 `EXCEPTION` 只出现在 `RAISE EXCEPTION`（position 318），不是处理器。prosecdef 均为 false。不符条件（DEFINER 或吞 `session not found`）未触发。

proacl（`aclexplode`）两 overload 的 EXECUTE 受让方均为 `postgres`（属主）、`v13_route`、`v13_spawn_owner`。无 PUBLIC。route 在。源授权块 `v13/acl/v13_acl.sql:475-478`。

### B4 operator / authorized — 成立

均在库。`v13_control_operator()` STABLE，prosrc 含 `pg_has_role(current_user, 'v13_route', 'USAGE')`（position 159），不含 `MEMBER`。源 `v13/acl/v13_acl.sql:74-85`。`v13_control_authorized(uuid, uuid)` 在，源 `:90`。EXECUTE 授 `v13_route` 与 `v13_spawn_owner`。

### B5 handoff_policy — 成立

活动行：`handoff_policy` version 1，`{"enabled": true, "schema_version": 1}`。源种子 `v13/handoff/v13_handoff.sql:108-109`。缺行条件未触发。

同库活动策略名含 `triage`（`{"duty_cycle": 1}`，源 `v13/triage/v13_triage.sql:4`）与 `spawn_budget` version 1（`max_nonterminal=8, max_depth=4, max_fanout=8`，源 `v13/spawn/v13_spawn.sql:24-25`）。`should_run` 行数 0。

## §2 B6–B10

### B6 handoff 函数、守卫、恰两个部分唯一索引 — 成立

| 对象 | 探针 | 源 |
|---|---|---|
| `v13_extract_handoff(uuid, uuid, bigint)` | INVOKER，owner postgres，VOLATILE，`search_path=pg_catalog, public` | `v13/handoff/v13_handoff.sql:280` |
| `v13_handoff_emit(uuid, jsonb)` | **prosecdef=true**，owner **`v13_handoff_owner`**，VOLATILE，同 search_path | `:151`，`ALTER OWNER` `:211` |
| `v13_transcript_hash(uuid, bigint)` | INVOKER，STABLE，同 search_path | `:110` |
| `v13_handoff_event_guard()` | INVOKER，VOLATILE | 守卫函数；触发器 `trg_handoff_guard` WHEN `new.type = 'control/handoff'` |

`v13_handoff_owner`：`NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS`，成员数 0。

handoff 部分唯一索引恰两个（`pg_get_indexdef`）：

- `ux_events_handoff_delivery`：`(payload ->> 'delivery_id')` WHERE `type = 'control/handoff'`
- `ux_events_handoff_snapshot`：`(session_id, payload ->> 'up_to_seq', payload ->> 'transcript_hash')` WHERE `type = 'control/handoff'`

源 `v13/handoff/v13_handoff.sql:272-278`。events 上另有更早 stage 的部分唯一索引（`ux_events_child_created` 等），不是 handoff 的那两个。缺一条件未触发。

### B7 政策读取与同身份回读序 — 成立（按 B 计划 §5.3，不是两函数都回读）

extract prosrc：`RETURN v_prev` position **1309**，`v13: handoff policy` position **1474**。回读在策略检查之前。无 `EXCEPTION`。源控制流 `v13/handoff/v13_handoff.sql:280` 起（授权 → 锁 → watermark → hash → 同身份回读 → 策略 → emit）。

emit prosrc：`v13_policies` position **88**，`v13_append_event` position **855**，无 `RETURN v_prev`，无 `EXCEPTION`。策略门在 append 之前。同身份直调不是函数内回读；B 计划 §5.3 规定撞 `ux_events_handoff_snapshot` 裸 23505。与已落地合同一致，不停工请裁。

活体旁证：父会话对子会话 `v13_extract_handoff` 返回恰四键 `delivery_id, schema_version, transcript_hash, up_to_seq`。

### B8 state_hash 排除名单仍只三个 session/* — 成立

源 `v13/control/v13_control.sql:377` 与 `:390`，两处均为 `type NOT IN ('session/completed', 'session/failed', 'session/cancelled')`。Phase B 未换体（`git diff e6a8340..HEAD -- v13/control` 空；handoff SQL 无 `CREATE OR REPLACE FUNCTION v13_state_hash`）。

探针 prosrc：三词在，`control/handoff` / `goal/stopped` / `goal/resumed` 都不在（position −1）。

`control/handoff` **会进** hash，这是预期，不是扩排除名单。同一子会话 extract 前后：

- before `0307f1b3850778516c4497b0b3fabca74f55b12c457a0ce0c5f897b129bcdc54`
- after `4333d4ac8662bc25eb7c47b2fb2006acad543d848a159db3aa257b0b0602d825`
- `hash_changed=true`，`control/handoff` 行数 1

R8 C16（台账）：交接是收据不是可翻转当前态，不进 `v13_state_hash` 排除名单；F31 只把 `control/handoff` 排除出 `v13_transcript_hash`。不符条件（排除名单已含 `control/handoff` 或 `goal/*`）未触发。

### B9 advance 未被 Phase B 换体 — 成立

`v13/acl`、`v13/observe`、`v13/handoff` 的 SQL 无 `CREATE FUNCTION` / `CREATE OR REPLACE` `v13_advance`。`git diff e6a8340..HEAD -- v13/triage` 空。

活体 `v13_advance(uuid, jsonb)`：owner postgres，prosecdef false，VOLATILE，**无 proconfig**（与计划观察「triage 体无 SET search_path」一致）。prosrc 含：

- `v13_bind_worktree_from_prepare`（源 `v13/triage/v13_triage.sql:593`）
- `v13_triage_block_explore_spawn`（调用 `:643`）
- `v13_spawn_subsession`（调用 `:648`）
- `v13_triage_prework`（调用 `:800`）
- `spawn batch-dispatched`（源 `:881`、`:910`）

不含 `v13_should_run`，不含 `spawn budget cap`（cap RAISE 仍在 `v13_spawn_subsession` 里，不在 advance 里）。准入序仍是 explore 守卫 → spawn 批次 → 其后才 prework。相对顺序未被 Phase B 改掉。不停。

`v13_recover_idle()` 活体含 `v13_triage_hold_blocks_recover` 与 `SKIP LOCKED`。源 `v13/triage/v13_triage.sql:1186`，duty 跳过 `:1213`。stage 23–25 未换体。

### B10 events.at / append-only / policies 冻结 — 成立

- `events.at`：`timestamp with time zone NOT NULL DEFAULT now()`。源 `v13/schema/v13_core.sql:40`。`at` 列上索引数 0。
- `trg_events_append_only`：`BEFORE DELETE OR UPDATE`，无 WHEN。源 `:51-59`。
- `trg_policies_frozen`：`BEFORE DELETE OR UPDATE` on `v13_policies`。源 `:715-729`。探针内 `set_budget` 走 INSERT inactive + 双 UPDATE 翻 active，与冻结触发器放行 active 翻转一致。

events 上非内部触发器 8 个。WHEN 闭集没有 `goal/stopped` 或 `goal/resumed`（全库触发器定义命中数 0）。triage 守卫 WHEN 是 `goal/override`、`triage/hold`、`explore/completed`，不是停/复。

## §3 B11–B14

### B11 无 goal/stopped|resumed 历史行 — 成立

探针 `SELECT count(*) FROM events WHERE type IN ('goal/stopped','goal/resumed')` = **0**。未用 `LIKE 'goal/%'`（库中守卫认的是 `goal/override`，不是停/复）。baseline 污染条件未触发。

### B12 route 词表无 spawn；spawn 仍 RAISE cap — 成立

`v13_route(uuid, jsonb)` prosrc 不含 `spawn`。返回 action 字面量：`finish`、`reject`、`human`、`sql`、`tool`、`llm`。源 `v13/loop/advance.sql:110-164`。从未被后 stage `CREATE OR REPLACE`。

`v13_spawn_subsession` prosecdef true，owner `v13_spawn_owner`。prosrc 仍含三条文案：`v13: spawn budget fanout`、`v13: spawn budget depth`、`v13: spawn budget cap`。源 `v13/spawn/v13_spawn.sql:417-426` 与复检 `:457`。活体 RAISE 见 §4。L29 的 RED 成立，不停。

### B13 stage 1–20 哈希与 Phase B 复核基线一致 — 成立

基线取 `e6a8340`（`v13: align Phase B plan with Phase A as-built state per section 8 recheck`）。该提交之后、HEAD 之前，stage 1–20 的 20 个 SQL 文件 sha256 全部相等（mismatch 0）。`e6a8340..HEAD -- v13/load.py` 只追加 acl/observe/handoff 三行路径和三个 `STAGE_THROUGH` 键（+6）。

| 文件 | sha256 |
|---|---|
| `v13/schema/v13_core.sql` | `0514533c11a1394ee65e7cb9597b48791e32a742b1ee5c4c6d0bac9dcd42e695` |
| `v13/resolve/v13_resolve.sql` | `badaa6e8c925b1d013fc6f64620c97723131c215216c2b5f37d0e22d4bb7531b` |
| `v13/loop/advance.sql` | `e7c40c006c19228ddd76deaf16a343fd36f875f9c71d5bf9c1a554e2d4d2c81f` |
| `v13/twophase/v13_twophase.sql` | `978ea40d42a37d135c5fd98adade42e27f4a37f8bd07e91f7714201bbaf7c321` |
| `v13/envelope/v13_envelope.sql` | `d9286ceb6c4fff70f9d3e2a7eefa95685c9e3400ef1bbc193e27634dcf64d6b1` |
| `v13/manifest/v13_manifest.sql` | `2620ea4c365985a2ebc72a564046c25f727c309cd7a51b1b7a9316780f5a3c60` |
| `v13/chunks/v13_chunks.sql` | `6b4963c07bbc2e54342850dd43faafff7e0e50f15d3096ff31184b54516fe0ba` |
| `v13/recall/v13_recall.sql` | `982ea218015de48b8227701c3d97451e617d2d9f4a2ac23f77d3e5057898e4f8` |
| `v13/characterize/v13_characterize.sql` | `5ce565607fed0fd75d64987cd9d7e1b32e8143cc9d1526dcb3870e6149f035af` |
| `v13/filter/v13_filter.sql` | `416aadea5750158830bc48e359741edffb83ac2ee85335bb6629cd47948ca371` |
| `v13/memory/v13_memory.sql` | `296f63e07456bcab4da2d506d8bcba472029e0e72e1f8d57a2080d7a42843432` |
| `v13/economy/v13_economy.sql` | `494091769d27a93a66e6b817fdf2c11f54db8227f93ff61bfebf99f620d26647` |
| `v13/summary/v13_summary.sql` | `6486017b51e3cba3e051e8e89529d8d5db4cf3e349caa9a5c10194f5a2631158` |
| `v13/periphery/v13_periphery.sql` | `dbfa6ab032045933e7469ac027f10325fd1dd03290d026c673830e9261635247` |
| `v13/mgraph/v13_mgraph.sql` | `cb1ac2dc722f2ec9d8ca1aba73f41a38e55cb1465575fbe50af246f5638537ae` |
| `v13/mgraph_assembly/v13_mgraph_assembly.sql` | `7a2c9eed256da0268e7dd078f9dd2b363bf24b90bf4e8130f2d631f7218d2134` |
| `v13/control/v13_control.sql` | `7d843ad572029649a8abb7e6820fa5656eccaaee9622c88788f95d909226dff9` |
| `v13/spawn/v13_spawn.sql` | `6ce550d5ebb8178a4f8f8e901582e75f0d76e774269e6059554c03c73b72998a` |
| `v13/fanout/v13_fanout.sql` | `3441369b941131247820913d5a8038c515f381a0ffebe7f28f406f0a0c1ce936` |
| `v13/triage/v13_triage.sql` | `3d0f359096e63c136db83964726f00619ca20bf771f4ef01ee2425a4e60f516a` |

C 的提交仍不得改这些路径。本复核没有改。

### B14 夹具帮手在 — 成立

不新造第二套信封。开工写 stage 26 README 时用这些名字：

| 用途 | 帮手 | 位置 |
|---|---|---|
| user message | `prefix` | `v13/triage/test_triage.py:65` |
| snap | `snap_of` | `v13/triage/test_triage.py:71` |
| advance | `advance` | `v13/triage/test_triage.py:79` |
| explore tool/call 完成 | 内联 `v13_complete` + `tool_calls` | `v13/triage/test_triage.py:312-315` |
| harness 前驱请求 | `harness_request` | `v13/seam/test_seam.py:82`（stage 21，晚于 triage） |

同形 `open_session` / `prefix` / `snap_of` / `claim_complete` 也在 `v13/spawn/test_spawn.py:62-116`。seam 的 `enqueue`（`:90` 一带）是 harness effect 的入队帮手。找不到的停工条件未触发。

### 新名不存在

`to_regprocedure` 均为 NULL：`v13_should_run(uuid)`、`v13_should_run_gate(uuid)`、`v13_quota_eligible(uuid)`、`v13_missing_capabilities(uuid)`、`v13_attention(uuid,integer)`、`v13_scheduler_hint(uuid)`、`v13_goal_lifecycle(uuid)`、`v13_goal_stop(uuid,text)`、`v13_goal_resume(uuid,text)`、`v13_goal_fingerprint(uuid)`、`v13_spawn_batch_allowed(uuid,integer)`、`v13_spawn_budget_snapshot(uuid,integer,uuid)`、`v13_policy_share()`。

`v13_observe(uuid, uuid[])` 与 `v13_session_log(uuid, uuid, bigint)` 在库，STABLE，`search_path=pg_catalog, public`，EXECUTE 授 `v13_route`。

正向对照（默认 `max_nonterminal=8`，非 explore，一条未认领 `tool/call`）：`v13_advance` 返回 `progressed`，子会话 1，占用 1。夹具能走到 spawn，不是形状错误。

## §4 RED（L29）留证

时点 HEAD `8678ebff879917c1069e88d4abc2cef8cdc761d3`。库 `agent_v13_pc_recheck`，加载序止于 handoff（stage 28 尚不存在；advance 仍是 triage 末代，见 B9）。计划 §1.5 写「stage 28 库」；本复核按开工门槛在 handoff 全量库复现，行为相同。

先把 `spawn_budget` 翻到 version 2 active：`{"max_nonterminal":1,"max_depth":4,"max_fanout":8}`（INSERT inactive + 灭 v1 + 点亮 v2）。占用到顶 = 已有 1 个非终态子会话。

### 4.1 直调 — `v13: spawn budget cap`

```sql
SELECT v13_spawn_subsession(%s, %s::jsonb);
-- spec: {"schema_version":1,"children":[{"tool_call_id":"over","task":"nope"}]}
```

调用前 `v13_spawn_occupancy=1`，`max_nonterminal=1`。

- SQLSTATE `P0001`
- message_primary **`v13: spawn budget cap`**
- context：`PL/pgSQL function v13_spawn_subsession(uuid,jsonb) line 108 at RAISE`
- SAVEPOINT 回滚后占用仍为 1，子会话仍为 1

源文案 `v13/spawn/v13_spawn.sql:426`（前置）与 `:457`（复检）。探针堆栈落在函数 line 108，是前置比较，不是插入后复检。

### 4.2 路由 / advance 非 explore 批量路径 — 仍选 spawn，同一文案

这是「到顶时路由仍选 spawn 导致 cap RAISE」的红基线。route 返回词表没有 spawn 动作（B12）；spawn 走 advance 批量路径（`v13/triage/v13_triage.sql:644-648`），派发前无占用预检。

夹具：占用已是 1；`v13_complete` 一条 llm 结果，`tool_calls` id `tc_cap`，effect `request.route` 无 `reason`（不是 explore）。`v13_advance(sid, snap)`，snap 在把 `context_active_revision` 设为 `v13_context_required` 之后取。

- SQLSTATE `P0001`
- message_primary **`v13: spawn budget cap`**
- context：

```text
PL/pgSQL function v13_spawn_subsession(uuid,jsonb) line 108 at RAISE
PL/pgSQL function v13_advance(uuid,jsonb) line 85 at assignment
```

advance 调用了 `v13_spawn_subsession`，异常掀翻该语句。SAVEPOINT / 事务 ROLLBACK 之后：子会话仍 1，`tool/call` id `tc_cap` 仍在，`child-created` 为 0。tool/call 留置是因为整笔回滚，不是跳过。

已提交、可再查的父会话：`15fb1754-dd1e-4d14-8112-6ea5826c0c2d`（库 `agent_v13_pc_recheck`，policy v2 仍 active）。不要把这个库当干净种子。

### 4.3 计划 §1.5 的另一种到顶（占用 0，请求 2 > max 1）

非 explore，两条未认领 `tool/call`，占用 0，`max_nonterminal=1`。advance 同样：

- **`v13: spawn budget cap`**
- context 同 4.2：`v13_spawn_subsession` line 108，由 `v13_advance` line 85 赋值调用

### 4.4 explore 臂今日行为 — 不是 cap RAISE

用户要求走 advance 的 explore 臂。占用同样到顶（1/1），未认领 `tool/call` 的 source effect `request.route.reason='explore'`。advance **先** RAISE，到不了 `v13_spawn_subsession`：

- SQLSTATE `P0001`
- message_primary **`v13: explore spawn`**
- context：

```text
PL/pgSQL function v13_triage_block_explore_spawn(uuid) line 13 at RAISE
SQL statement "SELECT v13_triage_block_explore_spawn(p_sid)"
PL/pgSQL function v13_advance(uuid,jsonb) line 80 at PERFORM
```

源：守卫 `v13/triage/v13_triage.sql:529`，调用在 spawn IF 之外 `:643`，早于 `:648` 的 `v13_spawn_subsession`。子会话数不变。

这不是 L29 红基线失效。L29 要翻的是非 explore 批量路径的 cap RAISE（§4.2 / §4.3）和直调仍 RAISE（§4.1）。explore 误用保持先行 RAISE，与计划 `test_explore_raise_survives_gate` 同向。stage 29 README 必须把三句话分开写：非 explore 到顶今日 RAISE cap；直调今日 RAISE cap；explore 臂今日 RAISE `v13: explore spawn`，不到 cap。

## §5 与计划 §9 的差异清单

没有走进「不符时」的项。下列是写作时证据与当前 HEAD 的差，实施者不要按 r6 时点的「未提交」句施工。

| 项 | 计划写作时 | 本复核 | 是否不符 |
|---|---|---|---|
| B1 handoff | 已注册未提交；已提交末笔 observe `7b0e53c` | `d5b701f` 已提交，1→25 实跑绿 | 否。这是 B1 期望 |
| 探针库 | §1.5 RED 写 stage 28 库 | stage 28 不存在；handoff 全量库，advance 仍是 triage 体 | 否。红基线复现了 |
| B7 emit | 「extract 与 emit 含政策读取，且同身份回读在策略前」 | extract 回读在策略前；emit 只读政策再 append，同身份是索引 23505 | 否。与 B 计划 §5.3 一致 |
| B8 hash | 排除名单只三个 `session/*` | 仍是。`control/handoff` 进入 hash，前后哈希不等 | 否。C16/F31 预期。扩排除名单才会停 |
| B13 并行线 | 「Phase B 只新增 acl/observe/handoff 与 load.py 末三项」 | stage 1–20 SQL 未改。同窗口另有 `v13/read_tools/`（不在 `SQL_LOAD_ORDER`） | 否。不改冻结路径，不进加载序 |
| explore 臂 | L29 RED = cap RAISE | explore 臂到顶先 `v13: explore spawn` | 否。cap RAISE 在非 explore 批量路径与直调上成立 |

未改真值表。stage 26 底稿必须是开工当天的 `pg_get_functiondef`（本报告探针时点的 advance 仍含 `v13_triage_prework` 与 `v13_bind_worktree_from_prepare`），禁止按 fanout/spawn 文件回贴。
