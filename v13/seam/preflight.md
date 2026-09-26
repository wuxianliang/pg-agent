# v13 Phase A 前置核查（§3.1）— 2026-09-26

只核查，未写 SQL。探针库 `agent_v13_preflight`（stage 20 全量加载后的 `pg_get_functiondef`）。全文存档在 `/tmp/v13-preflight/`（不进仓库）。行号均指该存档，不是 control/spawn/fanout/triage 源文件行号。

**总判定：STOP-D11。不开工写 `v13_seam.sql`。**

| 判定点 | 结果 |
|---|---|
| §3.1.5 预绿 | **GO**（四门退出码 0） |
| §3.1.2 证伪清单 | **GO**（四项形状仍在） |
| §3.1.7 D11 括号证据 | **STOP-D11**（两臂 `turn/route` payload 均无 `effect_id` / `logical_turn_id`） |

停工后按计划禁用：无事件 index-0 行数计数、未在本探针证得的 payload 过滤、时间戳 / UUID / xmin / 快照可见性替代。本报告不提供这些兜底。

---

## 0. 方法

- 仓库根 `/Users/wxl/Projects/pg-agent`。非交互 shell，未 `source ~/.zshrc`。
- 预绿命令即计划点名的四个脚本（各脚本自调 `setup_db()`，自库）。耗时 = 进程墙钟（含 uv 启动与 DROP/CREATE/加载）。
- 探针脚本 `/tmp/v13_preflight_probe.py`（不进仓库）：模仿 `v13/triage/setup_db.py` 的 `DROP DATABASE IF EXISTS … WITH (FORCE)` + `CREATE DATABASE` + `load_stage(s, DB, "triage")`。`STAGE_THROUGH["triage"]=20`，20 个 SQL 均 `[loaded] OK`。随后套了 triage 的 stannum GRANT（不影响函数体）。
- 六函数各恰一份 `pg_proc`（无 overload）。

---

## 1. 预绿（§3.1.5）— GO

stage 17–20 = control / spawn / fanout / triage（`v13/load.py` `STAGE_THROUGH`）。

| stage | 命令 | 开始 (UTC) | 退出码 | 耗时 (s) | 日志尾 |
|---|---|---|---|---|---|
| 17 control | `uv run python v13/control/test_control.py` | 2026-09-26T15:50:47Z | **0** | 6.393 | `PASS stage 17 gates` |
| 18 spawn | `uv run python v13/spawn/test_spawn.py` | 2026-09-26T15:50:54Z | **0** | 4.105 | `PASS stage 18 gates` |
| 19 fanout | `uv run python v13/fanout/test_fanout.py` | 2026-09-26T15:50:58Z | **0** | 3.640 | `[done] fanout` |
| 20 triage | `uv run python v13/triage/test_triage.py` | 2026-09-26T15:51:02Z | **0** | 2.306 | `[done] triage` |

日志：`/tmp/v13-preflight/{control,spawn,fanout,triage}.log`。无红，不 STOP。

---

## 2. 活体取证

库 `agent_v13_preflight`。全文：

| 函数 | regprocedure | 波动 | secdef | 字节 | 存档 |
|---|---|---|---|---|---|
| `v13_harness_tail_gap` | `(uuid,uuid)` | v | f | 1320 | `/tmp/v13-preflight/v13_harness_tail_gap_uuid_uuid.sql` |
| `v13_cap_human_answered` | `(uuid,uuid)` | s | f | 998 | `/tmp/v13-preflight/v13_cap_human_answered_uuid_uuid.sql` |
| `v13_closeout` | `(uuid,text,text,boolean)` | v | f | 8946 | `/tmp/v13-preflight/v13_closeout_uuid_text_text_boolean.sql` |
| `v13_advance` | `(uuid,jsonb)` | v | f | 21380 | `/tmp/v13-preflight/v13_advance_uuid_jsonb.sql` |
| `v13_complete` | `(uuid,integer,bigint,text,jsonb)` | v | f | 8421 | `/tmp/v13-preflight/v13_complete_uuid_integer_bigint_text_jsonb.sql` |
| `v13_resolve_unknown` | `(uuid,text,jsonb)` | v | f | 3159 | `/tmp/v13-preflight/v13_resolve_unknown_uuid_text_jsonb.sql` |

元数据：`/tmp/v13-preflight/func_meta.tsv`。要点见以下各节摘录。

---

## 3. 证伪清单（§3.1.2）— GO

四项均仍符合计划 §2 锚点。不 STOP。

### 3.1 tail_gap 两臂 — 在，形状符合

`v13_harness_tail_gap` 活体：`kind=tool` + `v13_is_harness_tool` + `origin_user_seq = v13_last_user_seq(p_sid)` + `status=succeeded` + `effect_id IS DISTINCT FROM p_keep`，然后：

- 臂 progress：`result_kind=progress` 且存在 `repair/required` 或 `replan/required`
- 臂 wait：`result_kind=wait`
- 后继：同 `logical_turn_id` 且 `continuation_index = 候选 + 1` 的 harness 不存在
- RAISE 原文案 `v13: harness tail gap`

全库 `prosrc` 含 `v13_harness_tail_gap` 的只有 `v13_advance`（只 PERFORM，无第二份函数体）。

### 3.2 cap 谓词两臂 — 在，形状符合

`v13_cap_human_answered`：STABLE sql，`search_path=pg_catalog, public`。

- 臂 (a) L7–14：`interaction_kind IN ('material_cap','repair_cap','replan_cap')` 且 `human/responded.seq >` 前驱 `effect_done` 的 `max(seq)`（无则 `> -1`）
- 臂 (b) L15–20：`reason IN ('repair_cap','replan_cap')` 且 `NOT (request ? 'interaction_kind')`，无 seq 锚

与计划 §2「臂 (a) 三 cap + responded.seq > 前驱 effect_done.seq；臂 (b) legacy `{reason:repair_cap|replan_cap}` 无 seq 锚」一致。`material_cap` 不在臂 (b)，与锚点一致。

### 3.3 latch_fire adopt + V3008 — released fire 仍是静默空操作

`v13_latch_fire` L18–21：已有行则 `RETURN v_existing`（adopt），不 UPDATE、不插第二行。L29–31 `INSERT … ON CONFLICT (session_id, name) DO NOTHING` 后再回读。

结构层：

- PK `latches_pkey (session_id, name)` — 二次 INSERT 被拒
- `trg_latches_immutable` BEFORE DELETE OR UPDATE、`trg_latches_no_truncate` BEFORE TRUNCATE，函数 `v13_latches_guard` RAISE `v13: latches are INSERT-once`，`ERRCODE = 'V3008'`

已有 worktree 行后再 fire `released`：adopt 回读旧值，零写。仍是静默空操作。

### 3.4 catalog 仍是 `is VOLATILE` 拒绝

`v13_tools_catalog_frozen` L34–37：`kind='sql' AND enabled` 且 `provolatile NOT IN ('i','s')` 时 RAISE `'v13: sql tool % handler % is VOLATILE (need IMMUTABLE/STABLE)'`。子串 `is VOLATILE` 在。

### 3.5 `v13_interruptible` 闭集未变

```sql
SELECT CASE p_name
  WHEN 'fanout_required' THEN 'required'
  WHEN 'fanout_best_effort' THEN 'best_effort'
  ELSE 'unsupported'
END
```

两具名 + ELSE=`unsupported`。空名 / NULL 走 ELSE。

---

## 4. closeout ③ 形状（§3.1.3）— (C)

**结论：(C) 只查最新一条 harness。不调 `v13_harness_tail_gap`（直接、间接都没有）。**

「续传未还」= `v_owed` → RAISE `v13: closeout continuation owed`（活体 L119–161）。不是 `v_material` / `v_wake` / `v_appr`（那三条是 unpaid material / wake pending / approval pending，全表扫描，不是 ③）。

predecessor（`v13_harness_predecessor`）是 `LIMIT 1`：

```sql
ORDER BY (SELECT max(ev.seq) FROM events ev
           WHERE ev.session_id = e.session_id
             AND ev.source_effect_id = e.effect_id) DESC NULLS LAST,
         e.created_at DESC, e.effect_id DESC
LIMIT 1
```

`v_owed` 只读这一行：succeeded，且（progress+repair/replan，或 wait/approval 已有匹配 human，或 wait/evidence|quota 已有 `wake/satisfied`），且不存在同 `logical_turn_id` 的 index+1。

计划 §3.4 对 (C) 的处置：不改 closeout，禁再放宽。本核查不改裁决。

附带事实（不升格为 B，不 STOP）：`NULLS LAST` 使无事件的新 index-0 不会赢过已有事件的旧 harness。predecessor 仍是旧 progress+signal 行时，`v_owed` 仍可为真，非逃逸 closeout 仍 RAISE `continuation owed`。R5「最新已是新回合 finish/reject → ③ 已放过」只在 predecessor 已经是那条新回合时成立，不是本排序下的恒真。

---

## 5. PERFORM 位置（§3.1.4）

会话锁：`v13_advance` L18 `PERFORM 1 FROM sessions … FOR UPDATE`。函数内无 `COMMIT`。以下调用都在该锁段内。

三处 `PERFORM v13_harness_tail_gap`：

| # | 行 | 相对位置 | p_keep |
|---|---|---|---|
| 1 | L106 | **在** cap（L190 `v13_cap_human_answered`）**之前**，**在** continue 入队（L227）**之前** | 当时 predecessor |
| 2 | L328 | 失败/cancelled 重试臂，**在**该臂入队（L329）**之前**；该臂 `turn/route` 在入队**之后**（L330） | 该 failed/cancelled predecessor |
| 3 | L400 | **铸新格**臂（`WHEN 'tool'` 且 harness），**在** index-0 `v13_enqueue_effect`（L408）**之前**；同一次调用的 cap 已在 L190 决定过（`v_cap_new` 为真才落到这条臂）。共享 `turn/route` 在 L343，也在入队前 | L392 重读的 predecessor |

**被取代链会不会在盖章行插入前被算进 gap：不会。计划授权的那一次 PERFORM 搬移：不需要。**

理由：铸新格插入前，predecessor 就是被取代的那条 harness。L106 与 L400 都把该 `effect_id` 当作 `p_keep`。活体 EXISTS 有 `e.effect_id IS DISTINCT FROM p_keep`，该链不是 gap 候选。新行在 L408 才插入；即便已插入，原后继条件也只认同 `logical_turn_id` 的 index+1，新回合 index-0 不充当后继。所以「铸新格在盖章插入前把被取代链算进 gap」不成立。

更早的、不是 predecessor 的独立断链会在 L106（cap 之前）和 L400（插入之前）被算进 gap 并 RAISE。那不是被取代链；计划要求更早独立断链仍 RAISE。不据此搬移。

与 §3.6 字面的关系（报事实，不改裁）：铸新格调用点确实仍在插入前 `PERFORM tail_gap`。§3.6 括号若只看「调用在插入前」会走向第 7 步；§3.1.4 的搬移条件是「被取代链被算进 gap」。活体 p_keep 排除使后者为假。本核查不把「调用在前」自行改裁成必须搬移。

附带：求值器已接。predecessor 的 wait/evidence|quota 臂 L153 调用 `v13_wake_is_satisfied_v1`。§3.6 不因此另写 SQL；也不改变上面的搬移结论。

---

## 6. §3.1.7 两问 — ① GO / ② STOP-D11

### ① 两指定臂都在 enqueue 前同锁段写 `turn/route` — 成立

- **continue**（L207–236）：L217–219 写 `turn/route`，L227 `v13_enqueue_effect`。同锁段（L18 的 session `FOR UPDATE`，无 COMMIT）。
- **new 经 route**（L343 + L387–408）：L343 `PERFORM v13_append_event(..., 'turn/route', v_route)`，L408 才入队。同锁段。

第三臂（不是这两问的对象，记下以免混用）：failed/cancelled 重试 L329 先入队，L330 才写 `turn/route`。顺序与 ① 相反。payload 仍是 `v_route`，同样没有下面的指向字段。

`v13_enqueue_effect` 不写事件。`v13_append_event` 按入参原样存 payload；两臂调用都省略第 5 参 `p_source_effect`（默认 NULL）。事件列 `source_effect_id` 也不是指向字段。计划要的是 payload 字段，不用此列替代。

### ② 指向字段 — 无。STOP-D11

两臂实际写入的 `turn/route` payload 键集：

**continue**（L217–219 原文）：

```sql
jsonb_build_object('action', 'tool', 'reason', 'harness_continuation',
                   'tool', 'harness_turn', 'params', '{}'::jsonb)
```

键集：`action`, `reason`, `tool`, `params`。无 `effect_id`。无 `logical_turn_id`。`logical_turn_id` 只出现在随后的 effect request（L225），不在本事件 payload。

**new**（L343 写入 `v_route`）。到达 harness 铸新格时 `action='tool'`。`v13_triage_after_route` 只改写 `action='sql' AND tool='spawn_subsession'`，tool 臂原样返回 `p_route`。`v13_route` 对该臂的返回原文：

```sql
RETURN jsonb_build_object('action','tool','reason','side_effect_tool',
                          'tool', v_tool, 'params', v_params);
```

键集：`action`, `reason`, `tool`, `params`。无 `effect_id`。无 `logical_turn_id`。铸新格的 `logical_turn_id` 在 L406 `gen_random_uuid()` 才生成，晚于 L343 的事件写入，且不回写进已插入的 `turn/route`。`effect_id` 由 `v13_enqueue_effect` → `v13_effect_id` 从含该新 uuid 的 request 派生，同样晚于事件写入，不可能已在 payload 里。

`reason` 能分开两臂（`harness_continuation` vs `side_effect_tool`），但不是 `effect_id` / `logical_turn_id`，也不能唯一指向被入队行。计划禁止把未证得的 payload 过滤当兜底。本报告不采用。

**② 无字段，且不能靠该字段分开两臂。STOP-D11。**

---

## 7. D12 辅助事实

### 7.1 `v13_state_hash` — 不是白名单；§3.2 第 13b 步不触发

事件折叠是排除名单，出现两次（L19 `max(seq)`，L32 events 聚合）：

```sql
AND type NOT IN ('session/completed', 'session/failed', 'session/cancelled')
```

其余类型全部进入 hash。`worktree/released` 不在排除名单里，不换体也会被折进。第 13b 步（仅当活体是白名单才换体）不触发。

### 7.2 `v13_complete` / `v13_resolve_unknown` — 都不是 SECURITY DEFINER

| | prosecdef | volatile | owner | proconfig | proacl |
|---|---|---|---|---|---|
| `v13_complete` | false（INVOKER） | v | postgres | （空） | `{postgres=X/postgres,v13_route=X/postgres,v13_spawn_owner=X/postgres}` |
| `v13_resolve_unknown` | false（INVOKER） | v | postgres | （空） | 同上 |

`has_function_privilege`：`v13_route` 真；`v13_worker`、`v13_resolve`、`v13_recall` 假。`v13_worker` 是 `v13_route` 与 `v13_resolve` 的成员，但 `rolinherit=false`，成员关系不带来 EXECUTE。

§3.7 GRANT 闭包必须以这份活体 ACL 为准。活体调用方 EXECUTE 在 `v13_route` 与 `v13_spawn_owner`，不在 `v13_worker` / `v13_resolve`。

### 7.3 EXCEPTION 块 — 两者都没有会把异常收成 unknown/replay/stale 的处理器

- `v13_complete`：无 `EXCEPTION` 子句。`replay` / `stale` 是写状态之前的提前 `RETURN`（L23 fence/attempt → `stale`；L26 已终态 → `replay`；L29 非 claimed → `stale`）。status 写入在 L133 `UPDATE effects SET status = v_outcome`。无处理器可把 `23505` 或 `v13: worktree released` 收成 unknown/replay/stale。
- `v13_resolve_unknown`：无 `EXCEPTION` 子句。confirmed 在 L48 `UPDATE … status='succeeded'`，随后 L56 写 `unknown_resolved`。直线可加，不需要重排控制流。§3.5「无法直线加上则停工」的形状前提不成立（这不是 STOP）。

---

## 8. 未做

未改任何既有文件。未写 `v13_seam.sql`。未 commit。未进 `repoprompt-ce` / `loopx`。探针脚本与函数全文只在 `/tmp`。探针库 `agent_v13_preflight` 仍在本地 pgembed，未 DROP。

---

## 9. R6 后续状态（2026-09-27，追加不改写）

原 **STOP-D11** 是 R5 四/五轮条文（指向性 payload 探针字段）下的有效结论，探针事实（§6）不改写。Oracle R6（`docs/reviews/v13-control-plane-oracle-r6-2026-09-27.md`）裁定：该无事件分支整体删除，D11 条件 4 只认「新回合自身事件 `source_effect_id = effect_id` 且 `seq >` 匹配类 anchor」；不补指向键、不改 R3a §7.1、不搬 PERFORM、不改 closeout（③=(C) 维持）。STOP-D11 就该分支解除，stage 21 按 Phase A 计划 r6 开工。

---

## 10. R7 后续状态（2026-09-27，追加不改写）

§9 的 R6 解除不受影响。stage 21 施工期实测发现 R5 二/三轮的守卫锁协议（守卫与写者同锁 latch 行、守卫在持锁事务内重锁）在 PG18 稳定死锁：tuple lock 无同事务重入豁免，持有者重入请求排到等待者之后成环（40P01；NOWAIT/SKIP LOCKED/FOR SHARE 均不解除）。Oracle R7（`docs/reviews/v13-control-plane-oracle-r7-2026-09-27.md`）2:1 裁定候选①：**守卫改全程无锁 MVCC 校验**（latch INSERT-once 使 binding 不可变，无锁读无陈旧），写者保持 latch `FOR UPDATE` 并遵守「两条独立语句」规则（锁与事件重查分句，防 READ COMMITTED 语句快照打出 23505）。残留=无锁旁路直插在写者窗口先提交→写者 23505 整笔回滚：生产不可达，接受（F25）。本文 §1–§7 的 GO 不改写。

---

## 11. R7b 后续状态（2026-09-27，追加不改写）

§9/§10 不受影响。R7 守卫无锁落地后的残余 40P01 来自 R7 日程自身的测试锁序倒置（A 只持 latch → INSERT 的 events.session_id 外键 KEY SHARE 等 B 的 sessions FOR UPDATE，B 又等 A 的 latch）；生产恒 sessions→latch（外键由自持锁即时满足），无此环。Oracle R7b（`docs/reviews/v13-control-plane-oracle-r7b-2026-09-27.md`）三通道一致：日程改 A 按生产序先 sessions 后 latch 再 INSERT，等待观测移至 sessions 行（pg_blocking_pids + B 对 A xid 的 transactionid ShareLock granted=false + wait_event='transactionid' 三项同断，且须在 A 仅持 sessions 锁时采到）。本文 §1–§7 的 GO 与 R7 裁定不改写。

---

## 12. R9 后续状态（2026-09-27，追加不改写；编号注：R8 被并行 Phase B 线占用）

§9–§11 不受影响。stage 22 RED 基线 P1–P7 全过后，R5 断言 B（v_qual 限定名代入 writer_ok）触发预授权停工：活体 writer_ok 是「split_part 剥 schema 取裸名 + 闭集等值」，限定名+身份参数代入 false。Oracle R9（`docs/reviews/v13-control-plane-oracle-r9-2026-09-27.md`）三通道一致选①裸名同域绑定：两谓词入参改回行内裸 v_handler（与 guard 同参），防 shadow 改由断言 B′（to_regprocedure(裸名‖v_oid 参数表) NULL-safe 比对 v_oid，catalog 自身固定 search_path 域内）承担；裸名形状检查先于谓词；断言 A 保留为 frozen 自洽；P8a–P8d 为新硬前置。零函数改动。本文 GO 与 R6/R7/R7b 裁定不改写。
