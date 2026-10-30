# v13 DP2 修复闭合 + DP3 实现 L4 验收评审

> 评审者：父级 Loop Orchestrate 的 L4 验收代行。`context_builder` `response_type=review` 三路 Oracle：gpt-5.6-sol 完成（FAIL/P0）、claude-fable-5 完成（PASS / PASS-with-notes）、grok-4.6 **provider_error 失败**（`malformed modern model config option: model`）。按循环先例降级：以 plan 原文 + 两提交源码独立核验为准，不采信未复核的 Oracle 推断；管道故障记入 §7。
> 被审对象：
> 1. `18f840b` `v13: tighten dp2 gate fidelity per L4 review (B13 worker loop, C1 delta)`（2 files +183/−70）
> 2. `6179154` `v13: add manifest skeleton and three-epoch freeze`（6 files +2631/−0）
> 评审权威：`docs/reviews/v13-dp2-impl-l4-review-2026-09-22.md` §5（18f840b 修复清单）；`docs/plans/v13-dp3-manifest-skeleton-plan-2026-09-20.md` §1.3/§3/§4/附A/v2 修订 L1660–1775（6179154）。
> 已采信外部事实（控制器独立复跑，本评审不复跑）：六 gate 全绿（schema/resolve/loop/twophase/envelope/manifest，manifest **323** PASS）exit 0；两提交已推 origin/main。
> 先例：上轮 dp2 L4 = **PASS-with-notes**（0 P0 / 2 P1 测试保真不阻断 / 8 P2），无 P0 即正确性达标，P1 分阻断/不阻断，可开下一 DP。
> 评审日：2026-09-22。

## Verdict

| 提交 | Verdict | 一句话 |
|---|---|---|
| **18f840b** | **PASS-with-notes** | §5 P1×2 + P2×7 测试清单全 CLOSED；E1 测试面 GRANT **可接受**（本提交 mandate=测试保真、SQL 未改、README 已台账）。生产 `judgment_calls` INSERT-only vs `RETURNING` 需 SELECT 记 **P1 残留**（属 `6f8714a` SQL，上轮 L4 漏扫），不把本提交打 FAIL |
| **6179154** | **PASS-with-notes** | 0×P0 / 2×P1（测试保真，不阻断）/ 8×P2。SQL 与 §3 草案逐节同构；6 项自报偏差 5 ACCEPT + 1 ACCEPT-with-notes；F4 以 F6 顶替 **不成立** |

**dp2 是否干净收口：** 测试面 **是**（上轮 2 P1 + 7 强制 P2 全清）。机制授权形状 **否**——`v13_envelope.sql:993` 对 `v13_resolve` 仅 INSERT，付费批 `INSERT … RETURNING call_id` 在 `v13_resolve_login` 下会 42501（fail-closed）。不阻塞开 dp4，但 dp4 开工前应一行 catalog 收口。

**父循环可否开 DP4（chunks）：可以开。** 不给无 notes 的 PASS：F4 整组缺席、G8/G9 有跳过承重链的 else 枝。不给 FAIL：无 P0；SQL 机制面与 plan §3 同构（含 settle 终态走 complete 判 replay，见下驳回）；装箱/epoch/lander/V3003/锁序/七键 token 均在场且可证伪。

Oracle 1 将 E1 GRANT 升 P0、将 settle 终态重入与活动策略锁升实现 P1 → **驳回**（见 §3.1 / §7）。

---

## 1. 任务 1 · `18f840b`：dp2 L4 §5 修复清单逐项闭合

权威 = 上轮报告 §5。本提交只改 `v13/envelope/test_envelope.py` + `README.md`，dp2 SQL 不在 diff 内。

### P1-1 B13 段 3 worker 环 — **CLOSED**

对照 §5 项 1 四要求（`test_envelope.py:1353-1413`）：

1. **段 2 `complete('failed')` 后新快照推进。** 段 2 末不再用旧 `p13` 调 advance。新增 `with_current_probe`（`:248-254`）经真 `v13_probe` 刷新七键后 `v13_advance`，断言 `== "waiting"`（`"B13 s3: rehang waiting"`）。`advance.sql:219-255` 步 0 旧快照必 `'stale'`；新探针是 ③ 重挂的可达输入。
2. **循环内无 `parse_trimmed`。** 环体（`:1364-1392`）仅 `effect ready` → `claim_pinned` → `v13_resolve_judgments` → `complete('failed')` →（`worker_calls < cap` 时）`with_current_probe` + `v13_advance`。零 parse。
3. **真 claim→resolve→complete→advance 环。** 每轮断言 effect `'ready'` / `failed=true` / `readback_rejects==1` / complete `'accepted'` / advance `'waiting'`。环前一次严格 `'waiting'` 承担 cap=2 时环内不走 advance 的重挂面（`advance.sql:357-383` ③）。
4. **`worker_calls` 在环不转时会红。** 初值 1（段 2 = 链上第一 worker call），环内 `+=1`，尾断言 `>= 2`（`:1403`）与 `<= cap`（`:1404`）。环零迭代 → `>=2` 红。另保留 `succeeded <= cap+1`、污染 decisions=0、abandon。

反事实：删 γ' `IF NOT v_valid: CONTINUE`（`v13_envelope.sql:821-824`）→ `readback_rejects==1` 红；删 ③ 重挂 → 环首 `effect ready` 或环前 `'waiting'` 红。**不是恒真环。**

### P1-2 C1 新增 calls 含 tool 重问 — **CLOSED**

disable 前 `ids_before_dis` 记 call_id 集（`:1528`）；之后只检查差集 `new_calls`：`len>0` 且 `any("tool" in (qs or {}))`（`:1552-1556`）。反事实：tools 变后只重问全量投影、不重问窄投影 `tool` → `"C1: new calls re-ask tool"` 红。正向半边（messages 变 tools 不变）原样保留。满足 §5 项 2 字面。

### P2 #3–#9 — 全项 CLOSED

| # | 项 | 裁定 | 证据 |
|---|---|---|---|
| 3 | C2 恰集 | **CLOSED** | 按 `projection_key` 分流：tools 组 `== {"tools"}`，`*` 组 `== set(ctx)`，未知 pkey `expected=None` 必红（`:1558-1577`） |
| 4 | A5 删重言后枝 | **CLOSED** | `star == '{"a": 1, "b": 2}'` 单条件（`:588`）；`or '"a"' in star` 已删 |
| 5 | B11 真非 object | **CLOSED** | `beta_non_object("answers-array",[0])` / `("answers-scalar",1)`（`:1203-1240`）。双出口（RAISE 含 answers/object **或** `failed=true`+`failed_validation`+V3001）+ 零 decisions/零 cache。空对象形态改名 `empty-answers` 如实标注。双出口是 β 契约的两种合法失败态，不升未闭合 |
| 6 | D4 独立 | **CLOSED** | 独立构造 default v7（`[0,∞)→reject`）→ `d4_ca ≠ d4_sa` 双非空（`:1828-1846`）；`covered-by-X` 已删 |
| 7 | B13 poison 联立 | **CLOSED** | `failed is False and asked_questions == 0`（`:1425`）；无 try/except、无 `check(True)`；另 cached-only ∧ 零 cache ∧ 零 calls |
| 8 | E1 函数路径 INSERT | **CLOSED**（GRANT 见特别裁定） | `v13_resolve_login` 直连有缺口 `v13_resolve_judgments`，断言 `judgment_calls` 计数增长（`:1922-1950`） |
| 9 | README #2/#3/#5 | **CLOSED** | `v13/envelope/README.md:47-54` 三行与 #1/#4 同形制 |

### 特别裁定：E1 gate 内临时 `GRANT SELECT ON judgment_calls`

事实三角：

1. catalog：`GRANT INSERT ON judgment_calls TO v13_resolve`（`v13_envelope.sql:993`）；cache 同文件 `:992` 是 `SELECT, INSERT`。
2. 函数：成功路径 `INSERT … RETURNING call_id INTO v_call`（`:783-795`）。PG：`RETURNING` 需要被返回列的 SELECT。`v13_resolve_judgments` 为 INVOKER（非 DEFINER）。
3. gate：E1 缺口路径前 `GRANT SELECT ON judgment_calls TO v13_resolve`（`test_envelope.py:1935`）；README `:54-57` 明示「SQL 文件未改（本轮只收测试保真）」。

**测试面 GRANT：可接受。** 18f840b mandate = §5 测试保真；项 8 只要求「该角色路径 INSERT judgment_calls」。改 SQL 授权形状会偏离当时 dp2 plan §3 ACL 字面，属 erratum 而非本提交范围。台账如实，无静默。

**应进 SQL。** `v13_resolve_login` 生产付费批（README 运维纪律 5）在现 catalog 下 `INSERT … RETURNING` → 42501。fail-closed、零数据损坏，故 **不升 P0**（上轮 L4 已认证 SQL「无 P0」；本提交未改 SQL）。记 **P1-B 残留**：dp4 开工前 `GRANT SELECT, INSERT ON judgment_calls TO v13_resolve`（对齐 cache `:992`），并删 gate 内临时 GRANT 复跑 E1。次选：先 `v_call := gen_random_uuid()` 再 INSERT，保持 INSERT-only。

Oracle 1 以本 GRANT 判 18f840b **FAIL/P0** → **驳回**：问题不在本提交引入，测试 mandate 已闭环且台账在档。

---

## 2. 任务 2 · `6179154`：dp3 全面验收

权威 = plan §1.3（L52–162）/ §3（L211–1464）/ §4（L1471–1552）/ v2 修订（L1660–1775）。实现 = `v13/manifest/v13_manifest.sql`（947 行）+ `test_manifest.py`（1618 行）+ README/setup + `v13/load.py` 末尾追加。

### 2.1 SQL 对 §3 忠实度

结论：**逐节同构。无实现引入的机制 P0/P1。** plan「16 函数」为草案口径；G7 纸面口径 = **18 新建 + 3 OR REPLACE = 21**（`:302`），与源文一致。按函数名对号，不按「16」这个过时总数。

| plan 面 | impl 锚点 | 结论 |
|---|---|---|
| §3.1 表/守卫/epoch | `:3-160` | `v13_goals` FK+自证 CHECK+append-only；`goal_project` DEFINER+钉 search_path；回填幂等；artifacts 自证+部分唯一；produced_by succeeded 守卫；**ptr 守卫 INSERT+UPDATE**（`:101-121`）；epoch 双列+fill（悬挂 V3002、NULL→pre-bind）；UPDATE epoch 无条件拒（`:150-157`） |
| §3.2 三策略+七键+fresh | `:162-209` | 种子三行字面一致；`v13_context_required` 七键 **含 gen_ver**、三族缺行 RAISE；`v13_context_fresh` OR REPLACE 仅换比较体 |
| §3.3 latch/identity/V3003/defaults | `:213-496` | latch stub `'-none-'`；identity 材料=generation 策略行（非 typesafe GUC）；**validate 七层键集恰等 + `IN (…) IS NOT TRUE` 封 null + 全量 `USING ERRCODE='V3003'`**；defaults_check 键集/词表/三态 |
| §3.4 装箱 | `:498-687` | **pre_skip** `invalid_override`（值越表→不进装箱、eff_priority 回退 def）；**四值 prank First=1/Normal=2/Never=3/LastResort=4**（`:560-565`）；packed **`run_incl` 含自身**（`ROWS … CURRENT ROW`）且 `pre_skip IS NULL`；Never/disabled 不进装箱；churn 首版 0；jud 消费 complete-only（`answer IS NOT NULL AND status IN ('answered','cached')`）反向收集（骨架恒空）；mode identity 基 |
| §3.5 lander+settle | `:689-828` | 双 lander + refresh 均 DEFINER+钉 search_path；artifact_land **仅 kind='context'**；blob **内容寻址 ON CONFLICT DO NOTHING** + succeeded belt；settle：advisory 无锁读 → kind/session → **fence belt**（claimed 且令牌不符→stale；**终态不过 belt、走 complete 判 replay**——与草案 L1171–1176 **逐字同构**）→ **锁序 sessions→tools_meta→三策略活动行 `ORDER BY name`**（`:756-761`）→ 策略形状+**defaults_check 接线** → assemble NULL → validate → **inline 超限先于 complete** → complete CAS → 非 accepted 零写早退 → blob 冻结+**drift belt V3003** → land → result 补挂 → token **单源**写指针（`v_manifest->'required_revision'`） |
| §3.6 墓碑 | `:830-913` | probe 仅 goal_hash 换 `v13_goal_hash`；envelope 19 键从 live 复制，仅 goal_hash 换源，DP2 `NULLIF(timeout_ms)` 原样保留 |
| §3.7 replay+ACL | `:915-946` | replay `\|\|` 覆盖二键；REVOKE PUBLIC 18 件；读面授三角色；refresh+validate 仅 route；**双 lander/goal_project 零运行角色**；defaults_check 不授；表级 SELECT goals/artifacts |

不变量：变更形态仅 OR REPLACE×3 / ADD COLUMN×4 / 新触发器；`v13_advance`/`v13_complete`/enqueue 零触碰；零外部 IO；无 `set_config`/`mock_response` 子串；BEGIN/COMMIT 包裹。

**驳回 Oracle 1 两条 SQL「P1」：**

1. **终态重入非幂等。** 草案 L1171–1176 明文「终态行不过此 belt，走完整流程由 complete 判 replay」。F5(i) 已断言再调返 `'replay'` 且 artifacts 不增（`test_manifest.py:1238-1244`）。策略事后变非法导致重入 RAISE 是草案同一顺序的推论，不是实现偏离。
2. **活动策略行非稳定互斥。** 实现锁谓词与草案 L1178–1186 同构。READ COMMITTED 谓词重检是 plan OQ3「锁行即定版」已接受的近似；实证面归 F6(iii)（测试缺口，见 2.3），不是 SQL 偏离。

### 2.2 §4 断言强度（A–G）

fixture 纪律：parse 走真 `v13_parse`（mock 仅 typesafe GUC）；settle 走真 `v13_claim`+`v13_refresh_context`；策略走真 INSERT+翻 active；② 走真 advance（`hang_refresh`）。无手拼 manifest 注入（B5 直调 validate = plan 明文纯函数面）。**无伪链路。**

| 组 | 在场且可红 | 缺口（分级见 §4） |
|---|---|---|
| A1–A8 | 投影/自证/回填；三 fixture 字节相等；probe 七键相对；信封 19 键；token 七键含 gen_ver；straggler sem 动 history 哈希不变；ready llm → ① waiting ∧ 零 refresh | A5 request `or "goal_hash" in req5` 后枝过宽（P2）；A5 第二 advance 集合略宽 |
| B1–B7 | 10 键恰等+零时间戳；三段 9 键+词表+est 公式；query_side；judgments=[]+complete 谓词源码扫描；~30 负向 V3003；identity 换源正负；defaults 接线经真 settle V3003 | `fails_with` 对 pgcode 用 OR（P2）；B5 `check(..., True)` 合法正向通过后标记 |
| C1–C6 | 全 applied+序；v2a–v2d 恰集（含差 1 与 budget=0 首段可 skip）；Never 不占预算；disabled；churn；invalid_override 双层 | C2 未显式断言 applied est 运行和≤budget（恰集+定序已蕴含，P2） |
| D1–D4 | replay `\|\|` 二键+body=inline−replay；recompute 两形态只读；generation bump → mode=fresh+prior+identity 变；两调字节相等 | D1/F1「新 decision」用 `parse()` 且注释 may no-op，未断言 decisions 计数增加（P2）；D3 经 `parse_settle`（见偏差③） |
| E1–E4 | UPDATE epoch 词表内/外全拒；模板回填+NULL→pre-bind；后补答 epoch 不动；显式 post-execute 忽略 | E3 直 `UPDATE answer`，未走 B9 预置 open→mock 填链（P2） |
| F1–F6 | F1 冻结+append-only；F2 stale 零 effect；F3 canary 不泄漏；F5(i)(ii)+除零 V3003+complete failed；F6(i) settle∥settle 零 40P01 | **F4 整组缺席（P1）**；F6 仅 (i)，断言放宽（P1）；F5(iii) 未驱 attempts_exhausted 终局（P2） |
| G1–G10 | append-only+claimed 拒+自证+指针三负向；inline 超限 V3003∧仍 claimed∧零 artifacts；悬挂 V3002；owner 分离+route INSERT 拒+resolve 无 refresh；route_login 真 settle；G6/G7 加载；G10 旧 blob 字节+新哈希并存+零变化零新 blob | G1 缺两次零变化 `inline-'replay'` 对照（P2）；G1 随机 uuid `fails_with` needle 空串（偏差⑤）；G2 effect_done 查询未 fetch（P2）；G4 非完整 18 件×三角色矩阵（P2）；**G8/G9 `if lrow` else 可跳过承重链（P1）**；G10 增长用 `>` 非恰等变化段数（P2） |

反事实抽查：删 epoch 冻结 → E1 红；删 defaults 接线 → B7 settle 负向红；装箱改不含自身 → C2 v2b 差 1 红；identity 改读 typesafe GUC → B6 负向红；blob 不落 → G10 ② 红。

### 2.3 F4 以 F6 settle∥settle 顶替？— **不成立**

plan §4 F 组（L1516–1535）：

- **F4** = 语句快照原子性（装配期间并发 decision 提交对 A 不可见）+ **(iv) settle 窗口封闭**（并发 `append_event` 阻塞于 sessions 行锁，提交后 fresh=false）。
- **F6** = 锁序/CAS：(i) settle∥settle 恰一 accepted 另一 replay；(ii) settle∥complete；(iii) settle∥策略翻版。

实现：F 组从 F3 跳到 F5（`test_manifest.py:1228`）；**无任何 F4 断言**。F6 仅 (i) 两线程同 `(attempt,fence)`；结果条件（`:1301-1303`）

```text
vals == {"accepted","replay"} or vals == {"accepted"} or "accepted" in vals
```

容忍双 accepted 与「另一方任意非 40P01」。性质不同：**F6(i) 证串行化零死锁，不证 MVCC 同快照，也不证窗口封闭。** 不得 covered-by。

风险：最高危对（settle∥settle）已跑且测试绿；锁序与草案同构，complete 仍 sessions→effect（DP1 已核实）。故 **P1 不阻断**——与上轮 B13「环字面未达但仍 PASS-with-notes」同口径。

### 2.4 六项自报偏差

| # | 偏差 | 裁定 | 证据 |
|---|---|---|---|
| ① | validator 去掉草案 `DECLARE k` | **ACCEPT** | 草案 §3.3 ~L602 `DECLARE … k text`；impl `:251` 无 k。k 仅聚合别名，DECLARE 后与 `jsonb_object_keys(…) k` 42702。删未用变量，零语义分叉 |
| ② | 墓碑二 envelope 从 live 复制 | **ACCEPT** | plan §3.6 L1278–1396 明文「从 `v13_envelope.sql` 原文复制、仅换 goal_hash」。impl `:846-913` 对 live `:495-565` 19 键+`NULLIF(timeout_ms)` 保留 |
| ③ | 第二次 refresh 用 nonce enqueue | **ACCEPT-with-notes** | `parse_settle`（`:252-270`）仅当 `hang_refresh` 找不到 ready `context_refresh` 才 `enqueue … nonce`。零变化再 settle 时 ② 结构性不可达（effect 身份含 request-hash），nonce 是真 enqueue 非 mock。A5 首 settle / D3 generation bump 仍先走 `hang_refresh`。注记：A5 request 后枝（`:449`）会让 nonce 形态也绿——收紧见 P2，不因此 REJECT 整条 helper |
| ④ | DEFINER settle 后 recycle 连接 | **ACCEPT** | 测试卫生（提交+重建连接），零语义；G4 SET ROLE 后即 recycle |
| ⑤ | G1 kind 守卫先拒 | **ACCEPT** | ptr 守卫 BEFORE INSERT OR UPDATE（`:101-121`）：随机 uuid 的 `SELECT kind` 得 NULL → kind 不符先于 FK。blob→kind、随机 uuid 均 fail-closed。标签写「FK rejected」+ 空 needle（`:1400`）过宽，P2 标签债，行为 ACCEPT |
| ⑥ | v2 file 立法不进本 DP SQL | **ACCEPT** | v2 修订 L1660–1680「只立法/不改 SQL 字面/不 invent 新里程碑」。validator 扩 file 分支是上线 file 时义务。README `:33-37` 台账在档 |

### 2.5 纸面加载模拟

【直接观察】`v13_manifest.sql` BEGIN 首行 / COMMIT 末行；CREATE FUNCTION 21 = 18 新 + 3 OR REPLACE（名唯一，G7 `:302-305`）；CREATE TRIGGER 7；`$$` 配平（gate 绿+静态计数）；依赖先定义后引用（`goal_hash`→`context_required`→`prefix_identity`→`assemble`→`refresh`；墓碑在新对象之后）；ACL 在 COMMIT 前真末尾、REVOKE 先于 GRANT（`:924-946`）。`v13/load.py:18-33`：`SQL_LOAD_ORDER` 第 6 位纯末尾追加，`STAGE_THROUGH["manifest"]=6`。`setup_db.py` DROP/CREATE `agent_v13_manifest` + `load_stage(..., "manifest")`。DP1–DP2 前缀切片不含本文件（G6）。

README 回退写「删 `v13/load.py` 一行」——实际 `SQL_LOAD_ORDER` + `STAGE_THROUGH` 两处（P2）。

---

## 3. 发现摘要

**P0：0**

**P1：3**（均不阻断开 dp4）

| ID | 归属 | 内容 |
|---|---|---|
| P1-A | 6179154 测试 | F4 整组缺席；F6 仅 (i) 且结果条件放宽。F6 settle∥settle **不能**顶替 F4。plan L1516–1535 |
| P1-B | dp2 SQL 残留（非 18f840b 引入） | `judgment_calls` 对 `v13_resolve` 仅 INSERT，`INSERT … RETURNING` 需 SELECT。生产 `v13_resolve_login` 付费批 42501。18f840b 用测试 GRANT 闭合 E1 断言并台账 |
| P1-C | 6179154 测试 | G8/G9：无 ready llm 时 else 只断言 `waiting` / 宽终态集合，provenance 与 terminal 链可跳过。plan G8/G9 L1538–1544。本次 323 PASS 说明本跑 if 枝走通，else 仍使回归不可红 |

**P2：8**

1. A5 request `set=={goal_hash} or "goal_hash" in req5` 后枝重言（`test_manifest.py:449`）。
2. `fails_with` 对 `pgcode` 用消息 OR SQLSTATE（`:59-72`）——删 `USING ERRCODE` 仍可能绿。
3. F6(i) 结果条件应钉 `{"accepted","replay"}`；F5(iii) 未驱 session failed/turn/end。
4. D1/F1 未断言迟到 decision 行数真增加；E3 直 UPDATE answer。
5. G1 缺两次零变化 `inline-'replay'` 对照；随机 uuid 空 needle；`check(..., True)` 指针 NULL。
6. G2 `effect_done` 查询未 fetch；G4 非 18 件×三角色全矩阵；G9 `hist` 死变量；G10 blob 增长用 `>`。
7. C2 未显式运行和≤budget；D4 并列截断 fixture 未单造。
8. README：dp3 台账只记偏差⑥；回退「一行」应为两处注册；envelope `mock_from_needed` 冗余双 update（`test_envelope.py` ~210，18f840b 顺手未清）。B11 双出口可再钉「无异常」为更严形态（不升未闭合）。

---

## 4. 修复清单

### P1（建议 dp4 开工前或本轮顺手；不阻塞开 dp4）

1. **P1-B ACL**（`v13/envelope/v13_envelope.sql:993`）：`GRANT SELECT, INSERT ON judgment_calls TO v13_resolve`；删 E1 临时 GRANT；无 GRANT 复跑 E1。或改 INSERT 不 `RETURNING`。
2. **P1-A F4/F6**（`test_manifest.py` F 组）：补 F4(i–iii) 语句快照 + F4(iv) 窗口封闭（B 阻塞于 Lock 至 A 提交，提交后 fresh=false）；F6 补 (ii) settle∥complete、(iii) settle∥策略翻版；F6(i) 断言改为恰 `{"accepted","replay"}`。
3. **P1-C G8/G9**：无 llm ready **立即失败**；G9 钉 `terminal` + 末 history 含本回合 llm/message + refresh 零 turn/route（后半已有）。

### P2（可随 dp4 或 README）

4. A5 删 request 后枝；`fails_with` 在传入 pgcode 时 **必须** SQLSTATE 相等。
5. D1/F1 先断言新增 complete decision 再查字节不变；E3 改预置 open→mock 填。
6. G1 补 `inline-'replay'` 对照；G2 fetch effect_done=0；G4 补触发器函数 PUBLIC 与 OR REPLACE 三件抽查。
7. G10 钉新增 blob 数=变化段数；manifest README 记偏差①–⑤、回退两处注册。
8. （可选）B11 非 object 取消 RAISE 逃逸枝，只留 `failed=true`+V3001。

### 明确不修 / 已驳回

- settle 终态走完整流程再 complete→replay：plan 同构，不改 SQL。
- 活动策略 `AND active FOR UPDATE`：plan 同构；缺的是 F6(iii) 测试。
- v2 file 立法不进本 DP SQL：ACCEPT，义务在上线 file / DP4 契约行。
- 不要求本两提交补 `docs/reviews/*-deviation-ledger-*`（v13 仍无该建制）。

---

## 5. 任务 3 · 结论（给父循环）

| 问 | 答 |
|---|---|
| `18f840b` | **PASS-with-notes**。§5 修复清单测试项全 CLOSED。E1 测试 GRANT 可接受；生产 SELECT 应进 SQL（P1-B） |
| `6179154` | **PASS-with-notes**。SQL §3 忠实；断言主体可红；F4 顶替不成立（P1-A）；G8/G9 有跳过枝（P1-C） |
| dp2 干净收口？ | **测试面是，机制授权形状否**（P1-B） |
| 可否开 dp4？ | **可以。** 携带 P1-A/B/C；建议开工前先收 P1-B（一行 GRANT） |

---

## 6. 方法与 Oracle 分歧处置

| 来源 | verdict | 本报告处置 |
|---|---|---|
| Oracle 1（gpt-5.6-sol） | 两提交 FAIL；E1 GRANT=P0；settle 重入/策略锁/F4/nonce/G8 为 P1 | 采纳 F4 不可顶替、G8/G9 跳过枝、nonce 后枝过宽为测试债；**驳回** E1 P0（本提交 mandate+fail-closed+上轮已认证 SQL）；**驳回** settle 重入与策略锁为实现 P1（plan 同构） |
| Oracle 2（grok-4.6） | **失败**（provider_error / malformed model config） | 降级：不重试、不采信空结果；记管道故障 |
| Oracle 3（claude-fable-5） | 18f840b PASS / 6179154 PASS-with-notes；可开 dp4；E1 GRANT 可接受 | 总裁决对齐；纠偏：18f840b 改为 PASS-with-notes（P1-B 残留）；F4/F6 与 G8/G9 升为本轮 P1（Oracle 3 已见 F4 但标「不阻断」——本报告同，但写入发现表） |

独立核验：通读上轮 L4 §5、dp3 plan §1.3/§3.4–§3.7/§4 A–G/v2 修订；`git show 18f840b` 全文；`v13_manifest.sql` 表/装箱/validate/settle/ACL；`test_envelope.py` B13/C1/C2/A5/B11/D4/E1；`test_manifest.py` helper/`fails_with`/A5/C2/D1–D3/E3/F1–F6/G1–G10；`advance.sql` ③；envelope ACL `:988-994`。未复跑测试。
