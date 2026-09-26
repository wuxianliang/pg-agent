# v13 Phase B §8 复核：Phase A 落地后（2026-09-27）

只取证。未改 `v13/`、未改计划、未 commit。探针库 `agent_v13_pb_recheck`（`load_stage(..., "catalog")` + catalog `setup_db.py` 的 stannum GRANT）仍在本地 pgembed。函数全文与元数据在 `/tmp/v13-pb-recheck/`（不进仓库）。行号除特别注明外指该目录里的 `pg_get_functiondef` 存档，不是 `v13/fanout/v13_fanout.sql` 源行号。

## §0 总判定

**GO-with-edits。**

不是 STOP。§8.1 A1–A8 全部成立；§8.3 停工子弹无一命中（见 §0.1）。stage 1→22 的 gate 全绿。修订只换锚与一句会被读反的顺序措辞，不改真值表、不改 F8/F17/F18/F29 的返回形状/文案/零写。

实施者在协调者应用 §10 之前，底稿必须是本报告所引 dump，禁止按 `:320`/`:348` 打开 `v13_fanout.sql` 回贴。

### §0.1 §8.3 对照（无 STOP 项）

| §8.3 子弹 | 结果 |
|---|---|
| 活体与草案只差 D12 有无 | D12 **在**。complete 相对 fanout 体的唯一差集就是这一次调用（§4）。按存在性分支继续，不因此改合同。 |
| 签名 / 安全属性 / 异常处理器 / 亲缘列 / hash 形状 / 守卫误伤 | 均符合 A2–A6、A8。不停，不请裁。 |
| Phase A 追加了影响准入语义的换体 | **未发生。** complete 相对 fanout 只在 `RETURN 'accepted'` 前插入 D12 块；cancel 体与 fanout 规范化后相同。worktree request/inline 检查已在 fanout 体内，不是 seam 新守卫。不回 R8。 |
| 同名 overload、`control/handoff` 历史行、新控制角色 | 皆无（§8）。 |
| 修订不得改 F8/F17/F18/F29 形状与零写 | 本报告不改那些合同。§10 只改锚与顺序措辞。 |

### Gate 全绿

命令：仓库根 `uv run python v13/<stage>/test_*.py`，串行。墙钟含 uv 启动与各自 DROP/CREATE/加载。日志 `/tmp/v13-pb-recheck/gates.tsv` 与同目录 `*.log`。开始 `2026-09-26T22:30:45Z`（CST 2026-09-27 06:30）。**23/23 脚本退出码 0；22/22 stage 绿。** 合计 203.567 s。任一非 0 则本判定改为 STOP；没有。

stage 15 `mgraph` 有两个 `test_*.py`，都跑了。

| stage | 脚本 | 开始 (UTC) | 退出码 | 耗时 (s) | 日志尾 |
|---|---|---|---|---|---|
| 1 schema | `v13/schema/test_schema.py` | 2026-09-26T22:30:45Z | 0 | 2.026 | `[M1 schema] ALL PASS` |
| 2 resolve | `v13/resolve/test_resolve.py` | 2026-09-26T22:30:47Z | 0 | 6.559 | `[M2 resolve] ALL PASS` |
| 3 loop | `v13/loop/test_loop.py` | 2026-09-26T22:30:53Z | 0 | 9.981 | `[M3 loop] ALL PASS` |
| 4 twophase | `v13/twophase/test_twophase.py` | 2026-09-26T22:31:03Z | 0 | 6.547 | `[M4 twophase] ALL PASS` |
| 5 envelope | `v13/envelope/test_envelope.py` | 2026-09-26T22:31:10Z | 0 | 8.141 | `[envelope] ALL PASS` |
| 6 manifest | `v13/manifest/test_manifest.py` | 2026-09-26T22:31:18Z | 0 | 7.564 | `[manifest] ALL PASS` |
| 7 chunks | `v13/chunks/test_chunks.py` | 2026-09-26T22:31:25Z | 0 | 9.725 | `ALL PASS` |
| 8 recall | `v13/recall/test_recall.py` | 2026-09-26T22:31:35Z | 0 | 10.487 | `ALL PASS` |
| 9 characterize | `v13/characterize/test_characterize.py` | 2026-09-26T22:31:46Z | 0 | 7.214 | `ALL PASS` |
| 10 filter | `v13/filter/test_filter.py` | 2026-09-26T22:31:53Z | 0 | 26.936 | `ALL PASS` |
| 11 memory | `v13/memory/test_memory.py` | 2026-09-26T22:32:20Z | 0 | 7.989 | `ALL PASS` |
| 12 economy | `v13/economy/test_economy.py` | 2026-09-26T22:32:28Z | 0 | 9.751 | `ALL PASS` |
| 13 summary | `v13/summary/test_summary.py` | 2026-09-26T22:32:38Z | 0 | 11.184 | `ALL PASS` |
| 14 periphery | `v13/periphery/test_periphery.py` | 2026-09-26T22:32:49Z | 0 | 7.371 | `ALL PASS (130 checks)` |
| 15 mgraph | `v13/mgraph/test_mgraph.py` | 2026-09-26T22:32:56Z | 0 | 34.313 | `[mgraph M1+M2+M3+M4+v2-V1+V2] groups A+D+E+F+G+H: ALL GREEN` |
| 15 mgraph | `v13/mgraph/test_stannum_usage.py` | 2026-09-26T22:33:30Z | 0 | 7.062 | `ALL PASS (71)` |
| 16 mgraph_assembly | `v13/mgraph_assembly/test_mgraph_assembly.py` | 2026-09-26T22:33:38Z | 0 | 11.808 | `ALL J GREEN (W1: J1-J3; W2: J4-J7; W3: J8-J9)` |
| 17 control | `v13/control/test_control.py` | 2026-09-26T22:33:49Z | 0 | 4.592 | `[PASS] stage 17 gates` |
| 18 spawn | `v13/spawn/test_spawn.py` | 2026-09-26T22:33:54Z | 0 | 1.901 | `[PASS] stage 18 gates` |
| 19 fanout | `v13/fanout/test_fanout.py` | 2026-09-26T22:33:56Z | 0 | 2.213 | `[done] fanout` |
| 20 triage | `v13/triage/test_triage.py` | 2026-09-26T22:33:58Z | 0 | 1.926 | `[done] triage` |
| 21 seam | `v13/seam/test_seam.py` | 2026-09-26T22:34:00Z | 0 | 5.006 | `[PASS] stage 21 gates` |
| 22 catalog | `v13/catalog/test_catalog.py` | 2026-09-26T22:34:05Z | 0 | 3.271 | `[catalog] ALL PASS` |

## §1 加载序

`v13/load.py:16-38` `SQL_LOAD_ORDER` 长度 **22**。末两项：`v13/seam/v13_seam.sql`、`v13/catalog/v13_catalog.sql`。

`v13/load.py:41-64` `STAGE_THROUGH`：`seam=21`、`catalog=22`。与计划 A1 一致。没有「底稿=20」路径。

HEAD `b229d67`（Phase B 计划终稿提交）的祖先含 `f59058d`。`git diff f59058d..HEAD -- v13/` 为空。`f59058d` 自身只改 `v13/catalog/README.md`（+3/−1）；catalog SQL 在 `7200317` 起、R9–R12 在 `433f6f9`…`40b67a6`、seam 在 `e925ebe`。

## §2 Gate

见 §0 表。seam/catalog 测试文件都在，未停在 §8.2 步 2。

## §3 探针库与 dump

方法同 `v13/seam/preflight.md` §0：`DROP DATABASE IF EXISTS agent_v13_pb_recheck WITH (FORCE)` + `CREATE DATABASE` + `load_stage(s, DB, "catalog")`。22 个 SQL 均 `[loaded] OK`。随后套 catalog `setup_db.py:16-23` 的 stannum GRANT。脚本 `/tmp/v13_pb_recheck_probe.py`。

| 对象 | 存档 | 字节 |
|---|---|---|
| `v13_cancel(uuid)` | `/tmp/v13-pb-recheck/v13_cancel_uuid.sql` | 3203 |
| `v13_complete(uuid,integer,bigint,text,jsonb)` | `.../v13_complete_uuid_integer_bigint_text_jsonb.sql` | 8599 |
| `v13_append_event(uuid,uuid,text,jsonb,uuid)` | `.../v13_append_event_uuid_uuid_text_jsonb_uuid.sql` | 1703 |
| `v13_state_hash(uuid)` | `.../v13_state_hash_uuid.sql` | 1847 |
| `v13_policy(text)` | `.../v13_policy_text.sql` | 341 |
| `v13_record_worktree_released(uuid,uuid)` | `.../v13_record_worktree_released_uuid_uuid.sql` | 1275 |
| `v13_worktree_state(uuid)` | `.../v13_worktree_state_uuid.sql` | 687 |
| `v13_tools_catalog_frozen()` | `.../v13_tools_catalog_frozen_.sql` | 3088 |
| 元数据 | `.../func_meta.tsv` | — |
| events 触发器 | `.../events_triggers.tsv` | — |

public 下 `v13_cancel` / `v13_complete` 各恰 1 个 overload。元数据全文见附录 A。

events 上非内部触发器 7 个（活体 `pg_get_triggerdef`）：

| tgname | 定义要点 |
|---|---|
| `trg_events_append_only` | BEFORE DELETE OR UPDATE，无 WHEN |
| `trg_events_goal` | AFTER INSERT WHEN `new.type = 'user/message'` |
| `trg_v13_control_event_guard` | BEFORE INSERT WHEN type ∈ {wake/satisfied, repair/required, replan/required, turn/material_spent, human/responded, unknown_resolved, session/completed, session/failed, session/cancelled, cancel/requested} |
| `trg_v13_material_spent_guard` | BEFORE INSERT WHEN `type = 'turn/material_spent'` |
| `trg_v13_seam_event_guard` | BEFORE INSERT WHEN `type = 'worktree/released'` |
| `trg_v13_spawn_event_guard` | BEFORE INSERT WHEN type ∈ {spawn/task, child-created, tool/call, recover/nudge} |
| `trg_v13_triage_event_guard` | BEFORE INSERT WHEN type ∈ {goal/override, triage/hold, explore/completed} |

## §4 语句级重定位

共享前缀的文件偏移：`v13/fanout/v13_fanout.sql` 的 `v13_complete` 自 `:305` 起，dump L1 = 该 CREATE。前缀语句 `fanout行 = dump行 + 304`。D12 插在函数尾，不移动前缀。

`v13_cancel`：fanout 体与 dump 体去空白后 **相等**（探针脚本外的一次性 diff）。Phase A 未换体。

`v13_complete`：相对 fanout 体，strip 后 **唯一差集** 是 dump L173–177（D12 IF + PERFORM）。无其他插入、无重排。

### 4.1 `v13_complete` 锚（dump）

无锁读出 **单列 `session_id`，不含 kind**。`unknown effect` RAISE 在双锁 **之后**。无 `EXCEPTION WHEN` 处理器（全文只有 `RAISE EXCEPTION`）。无 DEFINER。

| 语句 | dump 行 | 活体原文（缩） | fanout.sql 历史行 |
|---|---|---|---|
| 无锁读出 | L16 | `SELECT session_id INTO v_sid FROM effects WHERE effect_id = p_effect;` | :320 |
| session 锁 | L17 | `PERFORM 1 FROM sessions WHERE session_id = v_sid FOR UPDATE;` | :321 |
| effect 锁 | L18 | `SELECT * INTO v_row FROM effects WHERE effect_id = p_effect FOR UPDATE;` | :322 |
| unknown effect RAISE | L19–21 | `IF NOT FOUND THEN RAISE EXCEPTION 'v13: unknown effect %', p_effect;` | :323–325 |
| stale 返回（attempt/fence） | L22–23 | `RETURN 'stale';` | :326–327（:326 是比较，返回在下一行） |
| replay 返回 | L25–26 | `RETURN 'replay';` | :329–330 |
| stale 返回（非 claimed） | L28–29 | `RETURN 'stale';` | — |
| cancelled UPDATE（写） | L45–47 | `SET status = 'cancelled', result = NULL, error = NULL` | :349–351。计划所引 **:348 是上一行 `END IF`，不是写** |
| cancelled 分支结束 | L50–51 | `RETURN 'accepted'; END IF;` | :354–355。**:355 是 `END IF`，不是围栏** |
| human 围栏 | L52 | `IF v_row.kind = 'human' AND p_status = 'succeeded' AND v_row.request ? 'interaction_ref'` | :356 |
| one-of | L93 | `RAISE EXCEPTION 'v13: human channel one-of';` | — |
| D12 调用 | L173–176 | `IF v_outcome = 'succeeded' AND v_row.kind = 'tool' AND v_row.tool_name = 'worktree_release' THEN PERFORM v13_record_worktree_released(v_sid, p_effect);` | fanout **无**此块 |

**恰一次。** `PERFORM v13_record_worktree_released` 在 complete dump 只出现在 L176。`v13_resolve_unknown` 里另有一次（`v13/seam/v13_seam.sql:638`），不在 complete 体内。

**R7 两语句形不在 complete 里。** 在被调函数 dump：L26–28 `PERFORM 1 FROM latches ... FOR UPDATE;` 与 L36–39 `PERFORM v13_append_event(...)` 是两条独立语句，中间隔 L29–35 `IF EXISTS ... RETURN`。没有并成一条 SQL。换体不得把这两句搬进 complete，也不得把 L176 前移。

**replay/stale 仍在一切新写者之前：成立。** stale/replay 返回在 L23/L26/L29。其后第一处写是既有 cancelled UPDATE（L45）。Phase A 新写者只有 L176 的 D12，在这三处返回之后、最终 `RETURN 'accepted'`（L178）之前。cancelled 早退（L50）不调用 D12。complete 体内没有别的 `v13_record_worktree_released`。

锁后复验的合法插入点 = L18 与 L22 之间（今日就是 L19–21）。锁前准入的合法插入点 = L16 与 L17 之间。两处都在任何写之前。

### 4.2 `v13_cancel` 锚（dump）

| 语句 | dump 行 | 活体原文（缩） |
|---|---|---|
| 存在性 / `unknown session` | L10–12 | `IF NOT EXISTS (...) THEN RAISE EXCEPTION 'v13: unknown session %', p_sid;` |
| temp + 递归 | L13–31 | `CREATE TEMP TABLE ... v13_fanout_cancel_tree` + `WITH RECURSIVE tree` |
| 环 | L32–39 | `RAISE EXCEPTION 'v13: goal tree cycle';` |
| 深度 | L40–49 | `RAISE EXCEPTION 'v13: goal tree depth';`（`t.depth = 64`） |
| 树锁 | L50–57 | `FOR UPDATE OF s` |
| tree-changed | L58–65 | `RAISE EXCEPTION 'v13: cancel tree changed';` |
| 终态 replay | L66–69 | `IF v_st IN ('completed', 'failed', 'cancelled') THEN RETURN 'replay';` |
| effect 锁 | L74–82 | `FOR UPDATE OF e` |
| `cancel/requested` + ready→cancelled | L89–96 | `PERFORM v13_append_event(..., 'cancel/requested', ...)` 然后 `SET status = 'cancelled' ... status = 'ready'` |

标记串 `v13: goal tree cycle`、`v13: cancel tree changed`、`RETURN 'replay'`、`v13: goal tree depth` 都在。identity 仍单 uuid。INVOKER。无 EXCEPTION 处理器。无 D12。

锁后复验应插在 L65 与 L66 之间（tree-changed 之后、replay 之前）。树递归在锁 **前**。计划 §1.1「之后树递归/环深度…逐字节保留」若读成「复验之后才是递归」，与活体序相反。见 §10-2。

## §5 spawn_owner 冻结依赖

**结论：不存在。**

检索 `v13/**/test_*.py`（stage 1–22，含 seam/catalog；不含 `.claude/worktrees`，不含 gitignored demo）：

- 字面 `SET ROLE v13_spawn_owner`：**0 命中**。
- `SET LOCAL ROLE v13_spawn_owner` 只在 `v13/spawn/test_spawn.py:426` 与 `:436`。两处都是关 `trg_sessions_fork_cols_immutable` 后 INSERT/UPDATE `sessions` 造环或深链，然后 `RESET ROLE`，再以失败期望调 `v_goal_tree`。**没有** `v13_cancel(` 或 `v13_complete(`。
- `v13/catalog/test_catalog.py:189` 只在 SQL 里过滤 `rolname = 'v13_spawn_owner'`，不是 `SET ROLE` 后的成功调用。

因此 §2 证伪 8 不触发。不得把 spawn_owner 加进行政带。

探针库 `SET ROLE v13_spawn_owner` 后：`pg_has_role(current_user, 'v13_route', 'USAGE')` = **false**，`MEMBER` = **false**。cancel/complete 的 proacl 仍含它（附录 A）——它持 EXECUTE，但不是 operator。与 §3.4「非 operator 持 EXECUTE」夹具一致。

## §6 A1–A8

| # | 结果 | 事实 |
|---|---|---|
| A1 | 成立 | 末尾 seam=21、catalog=22，且 §0 gate 全绿。可从 23 追加。 |
| A2 | 成立 | cancel 未换体（§4.2；与 fanout 体规范化相等）。标记串在。INVOKER。identity `(uuid)`。 |
| A3 | 成立 | complete 恰一次 D12（dump L176）。两语句形在被调函数，不在 complete。`prosecdef=false`。无吞异常 `EXCEPTION`。签名仍 `(uuid,integer,bigint,text,jsonb)`。 |
| A4 | 成立 | `v13_state_hash` dump L19 与 L32：`type NOT IN ('session/completed', 'session/failed', 'session/cancelled')`。排除名单，恰这三项。不是白名单。`control/handoff` 不在名单里。 |
| A5 | 成立 | `sessions.parent_session_id` uuid，可空。同在：`spawn_kind text`、`turn_no int`、`status text`。 |
| A6 | 成立 | `control/handoff` 不在 stage 17 WHEN，也不在 seam WHEN，也不在 spawn/triage/goal/material 的 WHEN。append-only 只拦 UPDATE/DELETE。`events.type` 无词表 CHECK（只有 NOT NULL）。部分唯一索引的 WHERE 都不含 `control/handoff`。不会误伤。 |
| A7 | 成立（无收缩） | Phase A 未再停工。底稿 = stage 22 dump，不是「stage 17–20 绿」。 |
| A8 | 成立 | `v13_record_worktree_released` acl = postgres + `v13_route` + `v13_spawn_owner`。无 worker/resolve/PUBLIC。GRANT 源在 `v13/seam/v13_seam.sql:677-678`，**不是计划写的 :687**（文件止于 682）。`v13_worktree_state` 只授 route（A8 未要求 spawn_owner）。 |

适配（不是证伪，供 stage 24，不要求改计划）：`v13_pending_human(uuid)` 与 `v13_unconsumed_cancel(uuid)` / `v13_cancel_pending(uuid)` 都返回 boolean。后两者体相同。observe 的 `cancel_pending` 用 `v13_unconsumed_cancel`（计划允许表已如此写）。

未跑、不构成停工：`blocked_unknown` 上经 emit 写收据（emit 尚不存在，属 stage 25 开工探针）；带行的 events UPDATE（空库，触发器定义已见，未插行去点着它）。

## §7 字节冻结

`git status --short -- v13/schema v13/resolve v13/loop v13/twophase v13/envelope v13/manifest v13/chunks v13/recall v13/characterize v13/filter v13/memory v13/economy v13/summary v13/periphery v13/mgraph v13/mgraph_assembly v13/control v13/spawn v13/fanout v13/triage`：**空**。

工作区其它未跟踪文件（docs 调查稿、`uv.lock` 已修改）不在这些路径上。stage 1–20 SQL 无未提交改动。冻结未破。

## §8 §2 证伪静态项

探针 SQL 结果：

| 项 | 结果 |
|---|---|
| 五新名 / 七新名 | `v13_control_authorized`、`v13_control_operator`、`v13_observe`、`v13_session_log`、`v13_extract_handoff`、`v13_transcript_hash`、`v13_handoff_emit` 在非 catalog schema 的 `pg_proc` 中 **0 行** |
| `type='control/handoff'` | public 里带 `type` 列的表只有 `events`，`count(*)=0` |
| `handoff_policy` | `v13_policies` 无此 name（现名 35 个，不含它） |
| worker USAGE | `SET ROLE v13_worker` 后 `current_user=v13_worker`。`pg_has_role('v13_worker','v13_route','USAGE')` = **false**；`pg_has_role(current_user,'v13_route','USAGE')` = **false**；`pg_has_role('v13_route','USAGE')` = **false**。证伪 3 不触发 |
| 冻结触发器对 INSERT | `trg_policies_frozen` 是 BEFORE DELETE OR UPDATE，不拦 INSERT。`INSERT ('handoff_policy', 1, '{"schema_version":1,"enabled":true}', true)` **成功**（RETURNING 一行），`ROLLBACK` 后 count=0。证伪 7 不触发 |
| 台账下一空号 | `docs/reviews/v13-control-plane-deviation-ledger-2026-09-26.md` 末行是 F26（:125）。F27 未占用。F21 历史空号，不改计划的「F27 起」。F22 在台账里出现两次（:99 与 :124），既有事实，本复核不重编号 |
| 长度断言 | `v13/` 内 `len(SQL_LOAD_ORDER)` 只在 `v13/mgraph_assembly/test_mgraph_assembly.py:375`：`len(SQL_LOAD_ORDER) >= 16`（冻结测试，已是 X1 放宽式）。无 `== 20`。loader `v13/load.py` 无长度断言。证伪 10 不触发，Phase B 不得改这条冻结断言 |

`v13_policy` dump L10 文案仍是 `v13: no active policy row for % (seed lost?)`。extract 不借道它的理由仍在。

`events.payload_hash` 列在（`v13/schema/v13_core.sql:38`）。本复核未做 UPDATE/DELETE 点火。

## §9 R9–R12 对 Phase B 的外溢

四份记录都不改 D7/D16，也不换 cancel/complete 的准入。

- **R9**（`docs/reviews/v13-control-plane-oracle-r9-2026-09-27.md`）：D14 断言 B 改裸名同域 B′；`v_qual` 不喂谓词。活体 catalog dump L37–44 已落地（形状检查、`v_bind := v_handler || v_arglist`、`IS NOT DISTINCT FROM`）。
- **R10**：三函数 proconfig NULL = 形态 H；换体不得加 SET。活体 `v13_tools_catalog_frozen` / `v13_named_sql_writer` / `v13_spawn_writer_ok` 的 proconfig **皆空**。
- **R11**：投毒先撞全库 proname 计数 `ambiguous across schemas`。活体 dump L24–27 仍是该 RAISE。
- **R12**：臂 D 改真行 `is VOLATILE`；谓词调用必须 schema 限定。活体 dump L42、L44 是 `public.v13_named_sql_writer` / `public.v13_spawn_writer_ok`。

对 §1.1 / §2：**无假设破坏，不要求改真值表。** catalog 换体形状是 proconfig NULL + 裸名同域 B′，不是「给 catalog 钉了 search_path」。GRANT 面：`v13_tools_catalog_frozen` 授 recall/resolve/route/spawn_owner；Phase B 不换这个函数，不得顺手 REVOKE。新函数自己的 `SET search_path = pg_catalog, public`（§1.3）与 R10「禁止给 catalog 加 SET」不冲突——对象不同。B′ 不进入 cancel/complete/authorized。

## §10 r10 修订建议清单

供协调者直接 apply。不改四动词合同。

### 10.1 计划 §1.1（约 L51）与 §3.2 步 6

**原句（§1.1）：** `dump 在 `:320` 无锁读出 effect 行（**扩列同时取 `session_id, kind`**，列入允许差集）后立即分支`

**建议改为：** `活体 dump L16 无锁读出（今日单列 `SELECT session_id INTO v_sid FROM effects WHERE effect_id = p_effect`，不含 kind；**扩列同时取 `session_id, kind`**，列入允许差集）后立即分支`

**原句（§1.1）：** `该判断在 session/effect 锁（`:321-322`）**之前**，因此也在 stale/replay 返回、cancelled 分支 UPDATE、human 围栏全部之前。`

**建议改为：** `该判断在 session 锁（dump L17）与 effect 锁（dump L18）**之前**，因此也在 stale（L23、L29）/replay（L26）返回、cancelled UPDATE（L45–47）、human 围栏（L52）全部之前。今日 `unknown effect` RAISE 在锁后 L19–21，不是无锁读出的一部分。锁前「无行」分支是新增，不得把 L20 当成锁前锚，也不得删除 L19–21：锁后复验插在 L18 与 L22 之间，并在该段做 actor/带分支（不改原句 `v13: unknown effect %`）。`

**原句（§3.2 步 6，锚的那半）：** `①**锁前定位查询扩列**——dump 初始无锁 SELECT 从单列 `session_id` 扩为同时取 `session_id, kind``

**建议改为：** `①**锁前定位查询扩列**——dump L16 无锁 SELECT 从单列 `session_id` 扩为同时取 `session_id, kind``，并在同一步末加：`③/④ 的锚是 L18 与 L22 之间（今日 L19–21），不是 L16 与 L17 之间。`

**理由：** `:320`/`:321-322` 是 `v13_fanout.sql` 源行，不是 `pg_get_functiondef` 行。前缀语句还在，但按 fanout 回贴会丢掉 dump L173–177 的 D12。`:326` 是 stale 比较（dump L22），不是写。

### 10.2 计划 §1.1（约 L50）与 §3.2 步 4

**原句（§1.1）：** `取得树锁并完成 tree-changed 检查后**锁后复验**一次谓词（关 parent_session_id 在检查与锁之间被改的 TOCTOU 窗）；之后树递归/环深度/终态 `replay`/未消费 cancel 幂等/`ready→cancelled` 清扫逐字节保留。`

**建议改为：** `取得树锁并完成 tree-changed 检查后**锁后复验**一次谓词（关 parent_session_id 在检查与锁之间被改的 TOCTOU 窗）。活体序禁止重排：存在性/`unknown session`（dump L10–12）→ temp 递归（L13–31）→ 环（L32–39）→ 深度（L40–49）→ 树锁（L50–57）→ tree-changed（L58–65）→ **锁后复验插在此处** → 终态 `replay`（L66–69）→ 未消费 cancel 幂等与 `ready→cancelled`（L83–97）。树递归/环/深度在锁前，不后移，不在复验后再贴一份。`

**原句（§3.2 步 4）：** `树锁 + tree-changed 检查后**锁后复验**谓词（actor 非空才需要）；其后字节 = dump。`

**建议改为：** `树锁（dump L50–57）+ tree-changed（L58–65）之后、终态 replay（L66）之前插锁后复验（actor 非空才需要）；复验之后的字节 = dump 自 L66 起。递归/环/深度保持 L13–49。`

**理由：** cancel 体与 fanout 相同，递归在锁前。字面「之后树递归」会把已冻序倒过来。

### 10.3 计划 §3.4（约 L233）

**原句：** `钉准入在 :348 写之前非 :355 围栏处`

**建议改为：** `钉准入在活体 cancelled UPDATE（dump L45 `SET status = 'cancelled'`）之前，不是 human 围栏（dump L52）处。`v13_fanout.sql:348` 是该 UPDATE 前一行的 `END IF`；`:355` 是 cancelled 分支的 `END IF`（human IF 在 fanout.sql:356 / dump L52）。禁止按这些行号从 `v13/fanout/v13_fanout.sql` 回贴。`

**理由：** 负例要钉的是「cancelled 写之前」，不是一个并不存在的「:348 写」。回贴 fanout 会丢掉 D12。

### 10.4 计划 §3.2 步 6 与步 7 的默认参数

**原句（两处）：** `p_result jsonb DEFAULT NULL`

**建议改为：** `p_result jsonb DEFAULT NULL::jsonb`

步 7 的「逐字保持」括号改为：`与活体 `pg_get_function_arguments` 逐字相同：`p_effect uuid, p_attempt integer, p_fence bigint, p_status text, p_result jsonb DEFAULT NULL::jsonb``。

**理由：** 探针库 `pg_get_function_arguments(v13_complete)` 与 `pg_get_functiondef` 头都是 `DEFAULT NULL::jsonb`，不是裸 `NULL`。步 7 要求含默认的 arguments 比对。

### 10.5 计划 §8.1 A3、A8 证据列

**A3 原句：** `stage 21 e925ebe + R7/R7b`

**建议改为：** `stage 21 e925ebe + R7/R7b。复核：complete dump L176 恰一次 PERFORM；R7 两语句形在 `v13_record_worktree_released` dump L26–28（latch FOR UPDATE）与 L36–39（append），不在 complete 体内。INVOKER；无 EXCEPTION 处理器；proacl={postgres, v13_route, v13_spawn_owner}`

**A8 原句：** ``v13_seam.sql:687` 的 GRANT（route+spawn_owner）已在库`

**建议改为：** ``v13/seam/v13_seam.sql:677-678` 的 GRANT（route+spawn_owner）已在库（文件止于 682，无 687 行）。活体 acl = postgres:EXECUTE, v13_route:EXECUTE, v13_spawn_owner:EXECUTE`

**理由：** A3/A8 命题为真，但证据行号会把人带到不存在的行，或让人在 complete 里找两句写者。

### 10.6 计划 §2 探针表「今日锚」列

**原句（cancel 行）：** `fanout:153（temp 树/环深度 64/终态 `replay`/`cancel/requested`/`ready→cancelled`）`

**建议改为：** `历史源锚 fanout:153。活体底稿 = stage 22 `pg_get_functiondef`（复核报告附录 B），禁止从 `v13_fanout.sql` 回贴`

**原句（complete 行）：** `fanout:305（stale/replay 前置→cancelled 阶梯→human C4 fence/one-of→写）`

**建议改为：** `历史源锚 fanout:305。活体底稿 = stage 22 dump；相对该源体只多尾部一次 D12（dump L176）。禁止回贴`

**理由：** §2 已写「仅供理解 / 不回贴」，但表内仍把 fanout 行号放在「今日锚」。stage 23 的底稿是 dump。

## 附录 A 函数元数据

探针：`pg_proc` ⋈ `aclexplode(coalesce(proacl, acldefault('f', proowner)))`。proconfig 空 = NULL。`prosecdef` 全 false。

| ident | owner | vol | proconfig | identity arguments | acl_exploded |
|---|---|---|---|---|---|
| `v13_append_event(uuid,uuid,text,jsonb,uuid)` | postgres | v | NULL | 5 参，末参默认 NULL | postgres, v13_route, v13_spawn_owner, v13_triage_owner |
| `v13_cancel(uuid)` | postgres | v | NULL | `p_sid uuid` | postgres, v13_route, v13_spawn_owner |
| `v13_complete(uuid,integer,bigint,text,jsonb)` | postgres | v | NULL | 5 参；`p_result jsonb DEFAULT NULL::jsonb` | postgres, v13_route, v13_spawn_owner |
| `v13_state_hash(uuid)` | postgres | s | NULL | `p_sid uuid` | postgres, v13_route, v13_spawn_owner |
| `v13_policy(text)` | postgres | s | NULL | `p_name text` | postgres, v13_resolve, v13_route, v13_recall, v13_spawn_owner |
| `v13_record_worktree_released(uuid,uuid)` | postgres | v | `search_path=pg_catalog, public` | `p_sid uuid, p_effect uuid` | postgres, v13_route, v13_spawn_owner |
| `v13_worktree_state(uuid)` | postgres | s | `search_path=pg_catalog, public` | `p_sid uuid` | postgres, v13_route |
| `v13_tools_catalog_frozen()` | postgres | s | NULL | （无参） | postgres, v13_recall, v13_resolve, v13_route, v13_spawn_owner |
| `v13_pending_human(uuid)` | postgres | s | NULL | `p_sid uuid` → boolean | postgres, v13_route, v13_spawn_owner |
| `v13_unconsumed_cancel(uuid)` | postgres | s | NULL | `p_sid uuid` → boolean | postgres, v13_route, v13_spawn_owner |
| `v13_cancel_pending(uuid)` | postgres | s | NULL | 同 unconsumed | postgres, v13_route, v13_worker |

## 附录 B 语句锚表

dump 根：`/tmp/v13-pb-recheck/`。complete 文件 `v13_complete_uuid_integer_bigint_text_jsonb.sql`。cancel 文件 `v13_cancel_uuid.sql`。

| 计划旧锚 | 实际指什么 | 活体锚 |
|---|---|---|
| fanout.sql:320 | 无锁 `SELECT session_id` | complete L16 |
| fanout.sql:321 | session `FOR UPDATE` | complete L17 |
| fanout.sql:322 | effect `FOR UPDATE` | complete L18 |
| fanout.sql:326 | attempt/fence stale 比较 | complete L22（返回在 L23） |
| fanout.sql:348 | cancelled UPDATE **前一行** `END IF` | complete L44 |
| （写本身） | `SET status = 'cancelled'` | complete L45–47（fanout.sql:349） |
| fanout.sql:355 | cancelled 分支 `END IF` | complete L51 |
| （围栏本身） | human `interaction_ref` IF | complete L52（fanout.sql:356） |
| （无旧锚） | D12 `PERFORM` | complete L176 |
| （无旧锚） | R7 两语句 | writer L26–28 与 L36–39 |
| fanout.sql:153 | cancel CREATE | cancel dump 全文；序见 §4.2 |
