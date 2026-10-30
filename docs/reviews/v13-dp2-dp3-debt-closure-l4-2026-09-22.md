# v13 DP2/DP3 债务闭合 L4 复审

> 评审者：父级 Loop Orchestrate 的 L4 闭合复审代行。`context_builder` `response_type=review` 本轮取消；按上轮先例降级：以 §4 修复权威 + plan §4 F/G 原文 + 两提交源码独立核验为准，不采信未复核的 Oracle 推断。管道故障记入 §6。
> 被审对象（turn 6 两提交，**不做全量重审**）：
> 1. `a4cec9d` `v13: grant judgment_calls SELECT to resolve for RETURNING batches`（2 files +1/−2）
> 2. `5231fff` `v13: close dp3 F4/F6 snapshot gates and G8/G9 provenance chain`（2 files +503/−69）
> 修复权威：`docs/reviews/v13-dp2-fix-dp3-impl-l4-review-2026-09-22.md` §4（P1×3 + P2×8）。
> plan 原文：`docs/plans/v13-dp3-manifest-skeleton-plan-2026-09-20.md` §4 F/G（L1516–1544）。
> 已采信外部事实（控制器独立核，本评审不复跑）：六 gate 全绿 exit 0；`v13_envelope.sql:993` 已是 `GRANT SELECT, INSERT`；E1 临时 GRANT 已删；G8 `lrow is not None` fail-fast；diff 范围 = 4 文件。
> 评审日：2026-09-22。

## Verdict

| 提交 | Verdict | 一句话 |
|---|---|---|
| **a4cec9d** | **PASS** | P1-B CLOSED。catalog 与 cache 同形；E1 无临时 GRANT。README 台账未同步属文档残留，不重开 P1 |
| **5231fff** | **PASS** | P1-A / P1-C 与 §4 强制 P2 全 CLOSED。F4/F6 承重断言可红；G8/G9 else 枝已删。可选 P2 两项跳过可接受 |

**dp2 干净收口：** **是**（机制授权形状已进 catalog；测试面 E1 不再靠 gate 内 GRANT）。
**dp3 干净收口：** **是**（F4 整组在场且不可被 F6 顶替；F6(i) 恰集 + (ii)(iii) 双枝；G8/G9 承重链无跳过枝；§4 强制 P2 全清）。
**父循环可否开 DP4（chunks）：可以开。** 无未闭合 P1；无新削弱升格。不把 envelope README 过期台账写成阻断。

---

## 1. 提交 A · `a4cec9d`（P1-B）

权威 §4 项 1：`GRANT SELECT, INSERT ON judgment_calls TO v13_resolve`；删 E1 临时 GRANT；无 GRANT 复跑 E1。

| 检查 | 裁定 | 证据 |
|---|---|---|
| ACL 对齐 cache | **CLOSED** | `v13_envelope.sql:992` cache = `GRANT SELECT, INSERT … TO v13_resolve`；`:993` calls 现同形（`a4cec9d` 将 `GRANT INSERT` 扩为 `SELECT, INSERT`） |
| 无临时 GRANT | **CLOSED** | `test_envelope.py` E1 缺口路径（`:1932-1948`）在 `connect_as(v13_resolve_login)` 前 **零** `GRANT SELECT ON judgment_calls`。`file_search` 确认测试文件内该 GRANT 子串 = 0 |
| 撤 SELECT 会红 | **CLOSED** | E1 走真 `v13_resolve_judgments`（INVOKER + `INSERT … RETURNING call_id`）。无 SELECT → 42501，`E1: resolve_login gapped resolve ran`（`:1942`）与随后 `judgment_calls` 计数增长（`:1947-1948`）必红。不是台账空话 |

**残留（不重开 P1-B）：** `v13/envelope/README.md:53-57` 仍写「GRANT 仅 INSERT / E1 临时 GRANT / SQL 文件未改」。本提交未改 README。文档与 catalog 分叉，记 P2 文档债，机制已闭合。

---

## 2. 提交 B · `5231fff`（P1-A / P1-C + P2）

### 2.1 P1-A · F4(i–iii) 语句快照 — **CLOSED**

plan L1523：A 调 `v13_assemble_manifest` 期间 B commit 新 decision → A 不含该行 **且 token.dec 不含之**；A 提交后重调含之。

实现（`test_manifest.py:1328-1378`）：

1. 记 `dec_before = (v13_context_required->>'dec')`。
2. `CANON_PAUSE_SQL`（`:321-`）把 `v13_canonical_state` 换成 `PERFORM pg_advisory_xact_lock` 后再读 messages；测试连接持有 `879041`。
3. 线程 A 调真 `v13_assemble_manifest`；`wait_box_lock` 等到 A 的 pid `wait_event_type='Lock'`（或 `pg_locks.granted=false`）。
4. 连接 B `insert_complete_decision` + **commit**（真 answered 行，`:309-318`）。
5. 解锁 → A 返回。断言 `required_revision.dec == dec_before`（`:1368-1370`）。
6. 还原函数后重调：`dec == dec_before + 1`（`:1376-1378`）。

**快照泄漏会红吗？会。** 承重面是 token.dec，不是 judgments。`v13_assemble_manifest` 是单条 `LANGUAGE sql STABLE`（`v13_manifest.sql:500-525`，`tok` CTE 调 `v13_context_required`，`dec = count(*) … answer IS NOT NULL`）。B 的 commit 发生在 A 语句已起飞之后（advisory 等待可证）。若该语句看见新行，`dec_a == dec_before` 红；若重调仍看不见，`dec_before + 1` 红。两侧夹击，不是恒真。

**重言（不升 NOT-CLOSED）：** `judgments omit concurrent decision`（`:1372-1373`）在骨架消费集恒 `[]` 下对任意 decision_id 都绿。plan「A 返回不含该行」的可证伪半边是 token.dec，与上轮「骨架 judgments 恒空」一致。

### 2.2 P1-A · F4(iv) 窗口封闭 — **CLOSED**（实证锁等待，非计时猜测）

plan L1523 (iv)：A 持 settle 锁序期间 B `v13_append_event(llm/message)` **阻塞于 sessions 行锁**；A 提交后 `v13_context_fresh=false`。

实现（`:1381-1431`）：

- A 显式 `sessions … FOR UPDATE` → `v13_tools_meta` → 三策略活动行 `ORDER BY name FOR UPDATE`（与 settle `:756-761` 同序），然后才 `v13_refresh_context`。
- B 线程真调 `v13_append_event`。
- `check("F4(iv): B blocked on sessions lock", wait_box_lock(cur, box_b4))`（`:1419`）。
- A settle `'accepted'` → commit → B 得 `seq` → `v13_context_fresh is False`。

**阻塞探测不是 sleep。** `wait_lock`（`:273-283`）轮询 `pg_stat_activity.wait_event_type == 'Lock'`；`wait_box_lock`（`:286-299`）还查 `pg_locks WHERE pid=… AND NOT granted`。超时返回 `False` → 断言红。8s 是等待上限，不是「睡一会儿就算过」。

**未钉 relation 名：** `pg_stat_activity` 只证 `Lock`，没有 `relation = sessions`。sessions 归属由前置 `FOR UPDATE` + `append_event` 必锁 sessions 的形状推断。比「计时猜测」强，比「`pg_locks` join `pg_class.relname='sessions'`」弱一档。不因此 NOT-CLOSED——plan 的可观察结果（B 在 A 提交前不得 `seq`、提交后 fresh=false）两头都钉死。

与 plan「逐句复演 settle」的差：A 先手持三层行锁再调窄入口，而不是逐步跑 assemble→complete→blob→指针。锁面相同（超用户直调不改锁序），可接受。

### 2.3 P1-A · F6 — **CLOSED**

| 子项 | 裁定 | 证据 |
|---|---|---|
| (i) 恰 `{"accepted","replay"}` | **CLOSED** | `:1503-1504` `vals == {"accepted", "replay"}`。旧放宽 `or vals == {"accepted"} or "accepted" in vals` 已删。双 accepted / 单 accepted / 40P01 均红 |
| (ii) settle∥complete 双赢 | **CLOSED** | 两线程真 `v13_refresh_context` ∥ `v13_complete(…,'failed')`（`:1506-1574`）。零 40P01；`accepted ∈ vals ∧ vals ⊆ {accepted,replay,stale}`。**A 赢**（`status=succeeded`）：artifact+pointer 且 B `== 'replay'`。**B 赢**（`failed`）：零 artifacts 且 A ∈ {replay,stale}。其它终态 `check(…, False, st_ii)` 立即红。首检单独放过 `{accepted}`，双 accepted 会在分枝红（B 赢要求 A 非 accepted / A 赢要求 B 恰 replay） |
| (iii) 策略翻版 | **CLOSED** | A 在 assemble 内被 `CANON_PAUSE` 挡住（已持策略行锁）→ B `FOR UPDATE` 活动 assemble 行 + `bump_policy` → `wait_box_lock` 证 B 阻塞（`:1634`）→ 解锁后 A `'accepted'`、落地 `assemble_version == old_asm`（`:1647-1648`）→ `fresh=false`（`:1650`）。与用户闭合口径「策略翻版 fresh=false」一致；旧版一致是加码 |

### 2.4 P1-C · G8/G9 — **CLOSED**

| 项 | 裁定 | 证据 |
|---|---|---|
| G8 else 已删 | **CLOSED** | `5231fff` 删 `if lrow: … else: check(… a8 == "waiting")`。现 `check("G8: llm effect ready", lrow is not None, a8)`（`:1884`）无 ready 立即红，后续 `lrow[0]` 不可跳过 |
| G8 provenance | **CLOSED** | complete 的 `p_result` 带活动 `context_artifact_id` → `llm/message` payload 含该键（`:1899`）且 `effect.result` 同（`:1902`）。与 plan G8「p_result∥origin 通道」同型 |
| G9 terminal | **CLOSED** | 旧 `a9 in ("terminal","waiting","progressed")` 已删。现链：llm complete → ② waiting → post-llm settle → advance **`== "terminal"`**（`:1934` / `:1888`）。无 llm ready 同样 `l9 is not None` fail-fast |
| G9 末 history + 零 cycle | **CLOSED** | 终态后再 `parse_settle`；blob `inline::text` 同时含 `"llm/message"` 与 `"done"`（`:1963-1964`）。`turn/route` 计数对照，refresh 后不增（`:1967`）。旧 `hist` 死变量已换成真 blob 正文 |

### 2.5 P2（§4 项 4–7）逐项

| §4 | 项 | 裁定 | 证据 |
|---|---|---|---|
| 4 | A5 删 request 后枝 | **CLOSED** | `:517-518` 仅 `set(req5) == {"goal_hash"}`。`or "goal_hash" in req5` 已删 |
| 4 | `fails_with` +pgcode 必须 SQLSTATE | **CLOSED** | `:63-66`：`if pgcode: ok = exc.pgcode == pgcode`，不再 OR 消息。删 `USING ERRCODE` 会红 |
| 5 | D1 先增 decision 再字节不变 | **CLOSED** | `:1050-1061`：计数 `n_d1+1` 后 `v13_replay` 字节相等 |
| 5 | F1 同上 | **CLOSED** | `:1253-1263`：`insert_complete_decision` → `n_f1+1` → M₁ inline 冻结 |
| 5 | E3 预置 open→mock 填 | **CLOSED** | `:1188-1210`：手插 `status='open'` → `set_mock` + 真 `v13_parse` → `filled3 and st3=='answered'` 且 epoch 不变。直 `UPDATE answer` 已删 |
| 6 | G1 `inline-'replay'` 对照 | **CLOSED** | `:1714-1731` 两次零变化 settle，`minus_replay(ctx_rows[-2]) == minus_replay(ctx_rows[-1])` |
| 6 | G1 指针 NULL / 随机 uuid | **CLOSED** | NULL 现 `fetchone()[0] is None`（`:1706`），旧 `check(..., True)` 已删。随机 uuid needle 从空串改为 `"kind"`（守卫先于 FK，偏差⑤） |
| 6 | G2 fetch effect_done=0 | **CLOSED** | `:1749-1753`：`count(effect_done)==0` 且 `result is None`（旧查询未 fetch） |
| 6 | G4 触发器 PUBLIC + OR REPLACE 三件 | **CLOSED** | `:1822-1837`：7 个触发器函数 PUBLIC EXECUTE=false；`v13_context_fresh` / `v13_probe` / `v13_judgment_envelope` PUBLIC=false 且 route 仍有 EXECUTE |
| 7 | G10 新增 blob=变化段数 | **CLOSED** | `:2012-2026` `nblob2 - nblob == changed`，旧 `>` 已删。零变化再 settle 不增 |
| 7 | README 偏差①–⑤ + 回退两处 | **CLOSED** | `v13/manifest/README.md` 台账现 ①–⑥；回退改为 `SQL_LOAD_ORDER` 末项 **与** `STAGE_THROUGH['manifest']` |

### 2.6 明确不做的可选 P2 — **ACCEPT skip**

§4 项 8 原文「（可选）B11 非 object 取消 RAISE 逃逸枝」。上轮已裁定双出口是 β 契约两种合法失败态，不升未闭合。

envelope `mock_from_needed` 冗余双 update 同属上轮「可选 / 顺手未清」，不在本两提交 mandate 内。

两项跳过 **可接受**，不挡收口、不挡开 dp4。

### 2.7 新削弱扫描

| 现象 | 升格？ | 说明 |
|---|---|---|
| F4 judgments 不含并发行 | 否 | 骨架恒 `[]`，重言。承重面 token.dec 可红 |
| F4(iv)/F6(iii) 锁等待未钉 `relname` | 否 | `wait_event_type='Lock'` + `pg_locks.granted=false` 是实证；超时即红 |
| F6(ii) 首检 ⊆ {accepted,replay,stale} | 否 | 双 accepted 由 succeeded/failed 分枝钉死 |
| envelope README 过期 GRANT 叙述 | 否（P2 文档） | 不改 catalog 结论 |
| F5(iii) attempts_exhausted / C2 预算和 / D4 单造 | 否 | **不在 §4 清单**，本轮不重开 |
| 恒真 `check(..., True)` / sleep 顶替锁等待 | **未发现** | G1 NULL 与 G8/G9 else 已删；并发门用 `pg_stat_activity`/`pg_locks` |

---

## 3. 给父循环

| 问 | 答 |
|---|---|
| P1-B | **CLOSED** |
| P1-A F4(i–iii) | **CLOSED**（泄漏会红） |
| P1-A F4(iv) | **CLOSED**（`Lock` 等待实证，非计时） |
| P1-A F6(i)(ii)(iii) | **CLOSED** |
| P1-C G8/G9 | **CLOSED** |
| §4 强制 P2 | **全 CLOSED** |
| 可选 P2 跳过 | **ACCEPT** |
| 新削弱升格 | **无** |
| dp2 干净收口？ | **是** |
| dp3 干净收口？ | **是** |
| 可否开 dp4？ | **可以。** 零未闭合 P1 |

建议（非阻断）：顺手改 `v13/envelope/README.md` 台账，删「仅 INSERT / 临时 GRANT」段，与 `:993` 对齐。

---

## 4. 方法

通读上轮 §4 与 plan F/G L1516–1544；`git show a4cec9d` 全文；`git show 5231fff` 的 README + `test_manifest.py` hunk；现文件 `v13_envelope.sql:988-994`、`test_envelope.py` E1、`test_manifest.py` `fails_with`/`wait_*`/`CANON_PAUSE_SQL`/F4/F5/F6/G1/G2/G4/G8/G9/G10；`v13_assemble_manifest` 的 `tok`/`cs` CTE。未复跑测试。

---

## 6. 管道

`context_builder` `response_type=review` 本轮 **取消**（MCP `MCPToolExecutionCancelledError`）。不重试、不采信空结果。与上轮 grok `provider_error` 同口径降级：独立源码核验即本报告。
