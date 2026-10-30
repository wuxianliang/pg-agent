# v13 DP2 实现 L4 验收评审（envelope / judgment cache）

> 评审者：父级 Loop Orchestrate 的 L4 验收代行。`context_builder` `response_type=review` 跑通三路 Oracle（gpt-5.6-sol / grok-4.6 / claude-fable-5），verdict 分歧为 FAIL vs PASS-with-notes；本报告以 plan 原文 + `6f8714a` 源码独立核验为准，不采信未复核的 Oracle 推断。
> 被审对象：commit `6f8714a`（`v13: add judgment envelope and decision cache`，+3158/−0）vs 父提交 `9ed1e96`。
> 评审权威：`docs/plans/v13-dp2-judgment-envelope-plan-2026-09-20.md`（1814 行；§3 SQL 草案、§4 A–E 断言表、γ/γ'、B13 驱动序列、收尾工件节）。
> 已采信外部事实（未在本环境复跑）：envelope **214** check + DP1 四 gate 复跑，exit 0。
> 先例：`docs/reviews/` **无** v13 DP1 实现级 L4。最近实现级口径取 v10/v8 L4（无 P0 即正确性达标；P1 分「阻断 / 不阻断」）。本 DP 验收另开 `PASS-with-notes` 档，对应「语义交付成立、承重断言可证伪、测试保真有缺口」。
> 评审日：2026-09-22。

## Verdict：**PASS-with-notes** —— 0×P0 / 2×P1（测试保真，不阻断） / 8×P2

父循环 **可以开 DP3**。不给无 notes 的 PASS：B13 段 3 与 C1 方向对照未达 plan 字面强度。不给 FAIL：SQL 与 §3 草案等价或更严；γ/γ' 承重断言真实可证伪；五条实现偏差全部 ACCEPT。

Oracle 1 两条 SQL「P1」（父版本直接 INSERT `frozen`、`v_landed` 非 ROW_COUNT）**驳回**：两者均与 plan §3 草案逐字同构，属计划既有近似，不是本提交引入的实现缺陷。

---

## 1. 实现方 5 项偏差 — 逐项裁定

| # | 偏差 | 裁定 | 是否记台账 | 理由 |
|---|---|---|---|---|
| 1 | `NULLIF(v_t->'criteria','null'::jsonb)` | **ACCEPT** | README 已记；正式 ledger 不强制 | 见下 |
| 2 | `tools.kind` 限定 | **ACCEPT** | 建议 README 补一行；不建 docs ledger | 见下 |
| 3 | `timeout_ms` 空串 `NULLIF` | **ACCEPT** | 同上 | 见下 |
| 4 | `SET LOCAL` 代 `set_config(...,true)` | **ACCEPT** | README 已记 | 见下 |
| 5 | β/γ' 用 `q->'criteria'` | **ACCEPT** | 建议 README 补一行 | 见下 |

**台账口径**（plan §4 收尾，约 L1632）：v13 的 conformance-matrix / deviation-ledger **DP1 未建制**，收尾 = `load.py` + stage README；是否建制属父 loop。本 commit 零 `docs/` 改动 **不违规**。`v13/load.py:22` 纯末尾追加 + `STAGE_THROUGH["envelope"]=5` 符合收尾。建议把 #2/#3/#5 补进 `v13/envelope/README.md`「台账」节，与 #1/#4 对齐。

### #1 `NULLIF(criteria,'null'::jsonb)` — ACCEPT

- **plan**：§3.4 needed 草案写 `criteria := v_t->'criteria'`；A1 要求 param/stated 的 question/criteria 为 SQL NULL；A2 要求 `criteria='null'::jsonb` 拒（`v13_jt_criteria_not_json_null`）。
- **实现**：`v13/envelope/v13_envelope.sql:366,383,401,418` 四处固定族 `NULLIF(v_t->'criteria','null'::jsonb)`。模板 jsonb 经 `jsonb_build_object('criteria', t.criteria)`（同文件 needed 头部 `v_tmpl` 聚合）——SQL NULL 落成 json `null`，`->` 取回的不是 SQL NULL。
- **等价性**：若不 NULLIF，noul 族经 `v13_question_wire` ELSE 枝送出显式 `"criteria":null`，与「NULL 省键」和 typesafe 拒显式 null 冲突。列卫 `:64-66` 封写入面。是草案潜伏缺陷的正确修复，保 A1 / 不变量 2。

### #2 `tools.kind` 限定 — ACCEPT

- **实现**：`v13_envelope.sql:426` `tools.kind IN ('sql','tool')`。`RETURNS TABLE(..., kind text, ...)` 使裸 `kind` 指 OUT 参数。
- **等价性**：查询集合不变。DP1 `v13_resolve.sql` 旧体已同样限定。无此限定会 `42702`，needed 不可加载。零行为分叉。

### #3 `timeout_ms` 空串 `NULLIF` — ACCEPT

- **plan**：§3.4 envelope `'timeout_ms', current_setting('typesafe.timeout_ms', true)`（可空串）；A9 快照非空 GUC。
- **实现**：信封 `:546` `NULLIF(current_setting(...),'')`；calls 落行 `:741,:776,:790` `NULLIF(p_env->>'timeout_ms','')::int`。
- **等价性**：GUC 空串 `::int` 会 `22P02`。空串规范成 SQL NULL =「未声明」，与 A9 / 可空列一致。

### #4 `SET LOCAL` 代 `set_config` — ACCEPT

- **plan**：§1.2 契约 5 / 不变量 8 / §3.6：ask 前 `set_config('typesafe.timeout_ms', 冻结值, true)`。
- **实现**：`v13_envelope.sql:720-721` `EXECUTE format('SET LOCAL typesafe.timeout_ms = %L', p_env->>'timeout_ms')`。`%L` 字面量转义。
- **禁令来源**：DP1 G-ctx1-5(b)（`v13/twophase/test_twophase.py:143-147`；plan `v13-dp1-two-phase-advance-plan-2026-09-20.md`）对 `v13/**/*.sql` 剥注释后禁 `mock_response` **与** `set_config` 子串，且禁改 dp1 测试。
- **等价性**：`SET LOCAL` 与 `set_config(..., true)` 同为事务局部；ask 与消费在同一函数同一事务。`SET LOCAL` 不含 `set_config` 子串 → DP1 扫描不红（与五 gate 复跑绿一致）。`mock_response` 扫描独立仍在（envelope E5 扩到全树 SQL）。生产安全意图（防 mock 泄漏源文）**未被绕过**。载体级语法偏差。

### #5 `q->'criteria'` — ACCEPT

- **plan**：§3.6 β 草案一度 `q->>'criteria'`（text）；C4 回读要求 jsonb 同源。
- **实现**：consult / β / γ' 均 `q->'criteria'`（`:662,:769,:797`）。`v13_validate_answer(text,jsonb,jsonb)` 第三参是 jsonb；`->>` 产 text，调用面要隐式/显式往返。
- **等价性**：纠偏而非放水。与 C4「实参回读自 payload」同向。

---

## 2. 测试断言强度审计

对照 dp1「测试层静默削弱」标准。214 check 相对 plan §0「约 36 断言」是族/角色/信号展开，不是空转。

### 2.1 承重件：通过

**γ/γ' read-back（plan 承重；删 γ' 会红）**

- fixture 真实预置污染 cache：`test_envelope.py:1248-1257` 用信封经 `v13_judgment_hash` 预算 hash，answer `{"noul": 2}`（对 noul [0,1] 非法）。
- **段 1**（`:1258-1279`）：真 `v13_parse`。断言 `failed=false`（混合批有落行）、`remaining>0`、gap 含 `gate_action`、**该 signal decisions=0**、succeeded calls=1、cache 仍为 `"2"`。
- **段 2**（`:1281-1308`）：真 `v13_advance` → `claim_pinned`（内部 `v13_claim`，`v13/schema/v13_core.sql:267`）→ 真 `v13_resolve_judgments(env,1)` → `readback_rejects==1` ∧ `failed is True` → 真 `v13_complete(...,'failed')`。污染 decisions 仍 0。
- **反事实**：删 γ' 的 `IF NOT v_valid: CONTINUE`（`v13_envelope.sql:821-824`）→ read-back 把 noul=2 写入 decisions → 段 1「zero polluted decisions」与段 2「still zero」必红。consult 站 γ 若删 → 污染行会 `'cached'` 直落，同断言红。两站独立承重。不是 covered-by-X。

**毒化零 ask**

- B2（`:811-813`）：`failed is False and asked_questions == 0`，并断言 decisions/calls/cache 零新增。符合 plan §4 断言纪律（DP1 P1-8）。
- B3 parse / 直调（`:847-848,:866-867`）同样联立。
- E1 resolve_login（`:1829-1831`）毒化全命中亦联立。**B13 poison 变体不合格**，见 P2。

**伪链路（主路径）**

- B13 段 1/2 与 E6 走真 `v13_parse` / `v13_advance` / `v13_claim` / `v13_complete`，不是裸 UPDATE 冒充结算。
- mock 经 `mock_from_needed` 跟现行 kind/criteria，不硬编码 DP1 题文（A8 跟 latest）。
- B10 #45(b) 回退在 README 台账明示，不是隐性放水。

### 2.2 不达标（P1）

**P1-1 B13 段 3 不是 plan 字面 worker 环**

- **plan B13**（约 L1597）：`parse → advance → claim → resolve → complete('failed') → advance → (claim → resolve → complete → advance)*`；段 2 的 claim 轮 **即** 链上第一个 worker call（杜绝 cap+2 读法）。
- **实现**：段 1/2 符合。段 3（`:1318-1351`）每轮先 `parse_trimmed`（内部再进 parse/resolve），仅当 advance 返回 `waiting` 才 claim。段 2 末 `advance(旧 p13)` 未断言结果；complete 追加事件后旧快照 `max_event_seq` 失配 → advance 步 0 返 `stale`（`v13/loop/advance.sql`）。随后快路 parse `failed=true` → advance `'progressed'`，`if a == "waiting"` 在本 fixture **大概率不可达**。`worker_calls` 初值 1（`:1314`），`worker_calls <= cap` 在循环不进时恒真。
- **仍有牙的**：`tot_s <= cap+1` 约束快路付费次数；`abandon` 终态；污染 decisions 终局 0。plan 正文也承认快路 `parse failed → resolve_retry → 同封顶` 是合法有界链。
- **定性**：不是 γ' 被掏空（段 1/2 仍可证伪），但是对 **worker 慢路 ③ 重挂环** 的静默改写。按 dp1 测试保真标准记 **P1**。不因此判整包 FAIL：no-progress(8) 已在段 2 `failed=true` 钉死。

**P1-2 C1 方向对照可误通过**

- **plan C1**：disable 一个 enabled 工具（tools 变）→ parse₃ **`'tool' 重问`**。
- **实现**（`:1478-1506`）：`bool_or(payload->'questions' ? 'tool')` 扫 **该 session 全部历史 calls**。段 1 填满已问过 tool，该值天然 true。另一条件只证明总调用数增加。
- **反事实**：tools 变化后只重问全量投影题、完全不重问窄投影 `tool`，C1 仍绿。G-ctx7 四 Done-when 之一，不能用历史调用顶替。
- 正向半边（messages 变、tools 不变 → tool 不重问 ∧ intent 重问，`:1471-1472`）是强断言。

### 2.3 弱断言（P2，不升 P1）

1. **C2**（`:1513-1516`）：`st_keys == {"tools"} or st_keys <= set(ctx)`。plan 要「恰等于声明」。`<= ctx` 对全量组过宽；窄组 `== {"tools"}` 补了一半；C2 后半 fail-closed RAISE 是真的。
2. **A5**（`:580`）：`star == '{"a": 1, "b": 2}' or '"a"' in star` —— 后枝近重言式。
3. **B11**「answers-not-object」（`:1193`）实际 `answers: {}`，打中的是缺答/空对象，不是 `typeof IS DISTINCT FROM 'object'`。choice-oob / no-confidence / extra-signal 是真形态。
4. **D4**（`:1771`）`check("D1 already showed independent LATERAL")` —— 典型 covered-by-X。
5. **B13 poison**（`:1371-1374`）：`failed is True or asked_questions == 0`；except 枝 `check(..., True)`。主路径 B2 已钉联立，变体放宽。
6. **E1 resolve_login**（`:1822-1831`）：先 superuser `parse_trimmed` 填满，再以 resolve_login 毒化 parse。证明的是缓存命中下 EXECUTE parse，**没有**证明该登录经函数路径 INSERT `judgment_calls`（plan E1 字面）。
7. **claim_pinned**（`:173-181`）对其它 ready 行裸 `UPDATE ... cancelled`。B13/E6 通常一单；定点领取可接受，不是冒充 complete。
8. **214 vs ~36**：粒度膨胀，不是覆盖不足。

未发现：主路径 `check(True)` 顶替；用裸 UPDATE 代替 B13 的 complete；mock 写死题文而忽略模板翻新。

---

## 3. SQL 机制面扫描

权威 = plan §3.1–§3.9 / §1.5。**无 P0。无实现引入的机制 P1。**

| 检查面 | 锚点 | 结论 |
|---|---|---|
| BEGIN/COMMIT 单事务 | `v13_envelope.sql:1` / `:996` | 通过 |
| 物理顺序 = 文档顺序 | 父表→内容+guard→calls/cache→ALTER decisions→构建器→DROP 三件→needed/envelope/snapshot→OR REPLACE 五件→shadow→种子→ACL | 通过 |
| freeze / insert_guard / 零内容行 freeze 拒 | `:28-55` UPDATE 唯一 draft→frozen 且 EXISTS 内容行；`:99-134` 内容 INSERT 持父行 `FOR UPDATE` 且须 draft；A2 覆盖 | 通过（plan 同构） |
| INSERT∥freeze 串行化 | insert_guard `FOR UPDATE`；A2 线程测 | 通过 |
| `criteria='null'::jsonb` 拒 | `:64-66` + A2 | 通过 |
| request_hash 七参含 signal | `:569-577`；材料经 `v13_judgment_material`；B14 七参=五参 | 通过 |
| calls / decisions provenance 五列、无 usage 列 | calls `:151-168` 有 usage；decisions ALTER `:203-211` 五列 + pair CHECK；B7 目录 | 通过 |
| canonical first-wins / write-once / γ/γ' | cache 触发器 `:196-201`；`ON CONFLICT DO NOTHING` `:809`；read-back `:810-824` | 通过 |
| consult / 分组 / no-progress(8) | `:668-850`；`v_landed` 批前清零、FOR 内 +1、批尾 `=0 → failed` | 通过（计数口径见下「驳回」） |
| shadow 对照形 + `template_compat` 版本绑定 | `:854-921`；资格四件；`e->>1 = template_version::text`；零 `typesafe_ask` | 通过 |
| 分片哈希：执法机械 + 种子 `["*"]` | `v13_project_state`；种子 `:923-961` 七族全 `["*"]` | 通过 |
| ACL 真末尾、零前向引用 | `:963-995` 后即 COMMIT；DROP+CREATE 三件重授；OR REPLACE 五件不重授 | 通过 |
| 纸面加载 | 测试 `:334-340` BEGIN/COMMIT、`$$` 偶数、新 CREATE FUNCTION 名唯一 | 通过（未钉 54 条顶层，不升缺陷） |
| v2 file-Noul / F1 | 七族种子无 file-Noul；csh 仍 `digest(needed::text)` `:548-550` | 本 DP 不改字面，合规 |

**驳回 Oracle 1 的两条 SQL P1（记录以免父循环误采）**

1. **父版本直接 INSERT `frozen`**：表 CHECK 允许 `'frozen'`，守卫只挂 `BEFORE UPDATE OR DELETE`（`:53-55`）。**plan §3.1 约 L164 同一形态**；DP1 `v13_route_policies_guard`（`v13_core.sql:479-481`）同构。A2 覆盖的是 UPDATE 路径「零内容行 freeze ✗」，不是 INSERT 初态。作者期超权 INSERT 可造死版本，属计划/DP1 既有边，**不是本提交偏离**。可作后续硬化（BEFORE INSERT 强制 draft），不记本轮 P1。
2. **`v_landed += 1` 非 ROW_COUNT**：与 plan §3.6 L1266-1269 **逐字相同**。gap 命中条件是 `answer IS NOT NULL AND status IN ('answered','cached')`（`v13_resolve.sql:372-373`）。resolve 正常路径写入 `'answered'/'cached'`；`answer-once` 在 NULL→非 NULL 时把 status 打成 `'answered'`。要绕过需预置 `answer IS NOT NULL ∧ status ∉ {answered,cached}` 的脏行——非生产 resolve 产出。不记实现 P1。

有意偏离（§1 已 ACCEPT）：needed `NULLIF` criteria、`SET LOCAL`、timeout 空串、β 增 answers 对象/批外 signal 检查（相对 DP1 加严）。

---

## 4. 发现摘要

**P0：0**

**P1：2**（测试保真，不阻断语义交付 / 不开 dp3 的理由不成立）

| ID | 一句话 |
|---|---|
| P1-1 | B13 段 3 每轮夹 `parse_trimmed`，worker `(claim→resolve→complete→advance)*` 在本 fixture 基本不可达；`worker_calls<=cap` 近恒真。 |
| P1-2 | C1 方向对照用全历史 `bool_or(... ? 'tool')`，tools 变化即使不重问 tool 也可绿。 |

**P2：8** — C2 全量组用子集；A5 byte-equal 后退路；B11 not-object 实为空对象；D4 covered-by-X；B13 poison 未联立；E1 resolve_login 只走缓存命中；README 台账缺 #2/#3/#5；claim_pinned 裸 cancel 其它 ready。

---

## 5. 修复清单

### P1（建议本轮或 dp3 开工前收口；不阻塞开 dp3）

1. **B13 段 3**（`test_envelope.py` ~L1318）：段 2 `complete('failed')` 后用**新快照**（或 DP1 ③ 同 ID 重挂所需的 advance 输入）推进，循环内禁止 `parse_trimmed`；每轮断言 effect 状态 / claim / `failed=true` / `readback_rejects==1` / complete / advance。若现状态机下该链不可达：先写 plan erratum，不得由测试改成快路。`worker_calls` 须在「循环真的多轮 claim」时才有判别力。
2. **C1 方向对照**（同文件 ~L1498）：记录 disable 前的 `call_id` 集，断言**新增** calls 中至少一条 `payload.questions` 含 `tool`。

### P2（可随手或并入 README / 后续 gate）

3. C2：逐组 `set(state) == 声明 projection`（`*` → `set(ctx)`）。
4. A5：删 `or '"a"' in star`。
5. B11：加真正非 object（数组/标量）一条。
6. D4：独立构造 current≠shadow 的两列，或删重言式 check。
7. B13 poison：改回 `failed=false ∧ asked_questions=0` 联立（与 B2 同纪律）；except 枝不得 `check(True)`。
8. E1：resolve_login 直连走有缺口的 `v13_resolve_judgments`，断言该角色路径 INSERT `judgment_calls`。
9. README 台账补 #2 `tools.kind`、#3 timeout `NULLIF`、#5 `q->'criteria'`。
10. （可选硬化，非本 DP 债）父版本 `BEFORE INSERT` 强制 `draft` 且 `frozen_at IS NULL`。

### 明确不修

- #45(b) 声明超时走 V3001：保持 README 台账；升回条件沿用 `v13/resolve/README.md`。不要把 `failed_timeout` 当本库已用真 57014 问责的面。
- 不要求本 commit 补 `docs/reviews/*-deviation-ledger-*`。

---

## 6. 父循环可否开 DP3

**可以开。** DP3 消费面已在库内：

- envelope 键 `templates` / `needed` / `groups` / `timeout_ms` / `budget`（`v13_envelope.sql:537-548`）
- `judgment_calls.call_id` 作为调用锚（`:151`，resolve 落行 `:783`）
- `v13_shadow_reroute` 只承担 shadow；exact replay 仍归 DP3（plan §1.4 / README 纪律 3）
- `v13_parse` 出口七键未改（B2/B8）

开 DP3 时建议顺手 P1-1/P1-2 与 README 台账三行。#45(b) 升回前不要把 `failed_timeout` 当生产已验证面。

---

## 7. 方法与 Oracle 分歧处置

| 来源 | verdict | 本报告处置 |
|---|---|---|
| Oracle 1（gpt-5.6-sol） | FAIL（4 P1：INSERT frozen、v_landed、B13、C1） | 采纳 B13/C1 为测试 P1；**驳回** INSERT frozen 与 v_landed（plan 同构） |
| Oracle 2（grok-4.6） | PASS-with-notes，开 DP3 | 总裁决对齐；其 B10/C2 降为 P2 或已知回退 |
| Oracle 3（claude-fable-5） | PASS-with-notes，0 P1，开 DP3 | 过宽：B13 段 3 与 C1 方向对照未达 dp1 保真标准 |

独立核验：通读 plan §3/§4 承重段、`v13_envelope.sql` 全文关键块、`test_envelope.py` A2/B2/B3/B10/B11/B13/C1/C2/E1/E5、DP1 gap/claim/complete/route_policies_guard、G-ctx1-5(b) 扫描门。
