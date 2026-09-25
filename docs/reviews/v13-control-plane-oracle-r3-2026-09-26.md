# v13 控制面 Oracle R3 终裁记录（D4–D6 + 收敛点 C1–C5）

- 日期：2026-09-26。触发：迁移调查报告 `docs/analysis/v13-control-plane-migration-2026-09-25.md` §6 提出的 D4–D6 待裁。
- 轮次：R3 第 1 轮（三车道：grokBuild grok-4.7-build-fast-xhigh / openCode grok-4.7 / codex gpt-5.6-sol@xhigh）→ 主裁决三车道一致、5 个实施细节冲突 → R3 第 2 轮对抗收敛（grokBuild + codex 全文）→ 控制器合并残留分叉。
- 地位：本文与 R2（`v13-control-plane-oracle-r2-2026-09-21.md`）同级；D1–D3/A15–A21 不重开。R3 只替代迁移报告 §6 的「倾向」文字与 §4.1 的清回目标句。

## §0 主裁决总表

| 裁决点 | Verdict | 落地 |
|---|---|---|
| D4 根会话 INSERT 入口 | **A**：新增 `v13_open_session`，sessions 生产写入口闭集 = {open, fork, spawn_subsession}；**否决 GUC 令牌**，纯权限执法 + current_user 触发器带 | P2 / stage 18 |
| D5 blocked_unknown 生产者 | **A 修订**：所有把 effect 写成 `unknown` 的生产者（a2 + `v13_complete` unknown 出口 + P3 将来的 mutating 中断）同事务抬会话墙；双向不变量由延迟约束触发器执法；resolve 清回 **ready**（有人类待答时 waiting） | P1 / stage 17 |
| D6 审批载荷 v1 | **A 收口**：最小闭集 + 严格 one-of 通道 + 未知键拒绝；`human/responded` 事件携带正文 | P1 / stage 17 |

## §1 收敛点终裁（C1–C5 + D4 机制）

### C1 · resolve 清回目标 → `ready`（带一条例外）
两车道一致取 ready：`waiting` 在 R2 §1.2 是「会话等外部」，resolve 不入队不泊车，下一格 advance 才是泊车权威；粘性 cancel 由该次 advance 消费。
**条文**：`v13_resolve_unknown` 关闭该会话最后一条 unknown 且 status='blocked_unknown' 时：若存在 `kind='human' AND status IN ('ready','claimed')` 的 effect → `waiting`；否则 → `ready`。仍有其他 unknown → 保持 `blocked_unknown`。终态会话 resolve 只动 effect 不动 status。cancel/complete/requeue/`v13_append_event` 的 user/message 复位一律不清 `blocked_unknown`。（human 例外为 grokBuild 第 2 轮补充，codex 无异议基础上的投影准确性收口。）

### C2 · closeout 前置与漂移 → 计数权威 + 延迟双射触发器 + status 保险带
两车道均裁：**放弃 advance 步 0 漂移修复**（它是第二个写者）；用两个 `DEFERRABLE INITIALLY DEFERRED` constraint trigger 执法非终态会话的提交态双射 `EXISTS(effect unknown) ⇔ session blocked_unknown`（effects 侧覆盖 INSERT/DELETE/UPDATE OF status|session_id，sessions 侧覆盖 INSERT/UPDATE OF status，共享一个只 RAISE 不改行的函数）。
**条文（合并裁定）**：closeout 顺序 = ①已终态先短路重放已有 `session/*` 事件（不查计数）；②三个计数前置 `active=0 AND unknown=0 AND pending human=0`；③保险带 `status<>'blocked_unknown'`。双射触发器保证 ②③ 在非终态会话上等价，③ 仅防触发器被禁用/迁移漂移（fail-closed 带层，永不误伤）。终态会话允许 unknown 残留（双射只约束非终态）；任何生产者不得把终态改成 blocked_unknown。部分索引 `effects(session_id) WHERE status='unknown'` 支撑触发器/计数/回填。
（分叉记录：grokBuild 主张仅计数权威、不要 ③；codex 主张双前置。控制器取 codex 的带层 + grokBuild 的重放短路先行与终态残留许可——合并后两者同时成立，grokBuild 对「③ 会死锁」的担忧被双射触发器消除：非终态下 count=0 且标签在的状态不可提交。）

### C3 · stage 17 装载存量 → 幂等回填 + 断言，终态残留容忍
两车道一致方向（受限甲）。**条文**：安装单事务内顺序 = ①回填 `status IN ('ready','waiting') 且存在 unknown` → `blocked_unknown`（幂等，RAISE NOTICE 行数，不写事件）；②断言不存在「blocked_unknown 且零 unknown」与「ready|waiting 且有 unknown」，违例 RAISE 附 session_id 列表中止安装；③`completed|failed|cancelled` 且有 unknown = 仅 NOTICE、不改行（终态残留容忍，grokBuild 案；codex 案为安装失败——控制器取容忍，理由：终态残留只可能来自旧表示、closeout 重放路径已短路，失败会阻断采用）；④`DROP TRIGGER IF EXISTS` 后建两个延迟约束触发器；⑤回填→断言→触发器→函数换体**必须同一事务原子提交**（先挂触发器再换函数会出现「旧 complete 写 unknown 不抬墙被触发器拒」的窗口）。若 `v13/load.py` 非 stage 单事务，须为 stage 17 显式包裹 BEGIN/COMMIT。

### C4 · 响应通道 → 严格 one-of，未知键拒绝
两车道一致裁 one-of（放弃「至少其一」：双通道并存会产生第二事实源，v1 无已裁的谁为准）。
**条文**：`kind='human' AND p_status='succeeded'` 的 complete，在既有终态 replay / CAS/fence 检查**之后**校验：`schema_version` 必须为 JSON 数字 1；`interaction_ref` 必须文本且与冻结 request 里的 ref **字节相等**（不等 → RAISE，消息含提交值与当前值，行与事件零变化；request 无 ref 也拒）；恰一有效通道——`response` 为 btrim 非空 string 或非 null number/boolean（false/0 是合法回答，禁 truthiness）XOR `answers` 为 ≥1 键 object XOR `skip` 为 JSON true；`skip=false` ≡ 缺席不占通道；空串/`{}`/数组/object 型 response/字符串型 skip = 非法存在，优先于互斥计数拒绝；**未知额外键拒绝**（闭集；分叉记录：grokBuild 第 2 轮主张忽略不授权，控制器按仓库 fail-closed 文化取 codex 拒绝案，grokBuild 意见存档）。校验失败 = RAISE 事务回滚（调用方协议错误，不烧 attempt/fence 结算出口，不写 human/responded，不把 effect 打成 failed——与 llm 空文本降级分开）。三种合法通道都按 succeeded 结算；skip 不记 failed。校验用函数内谓词（分叉记录：codex 主张复用 pg_jsonschema；控制器取 grokBuild 案——pg_jsonschema 仅服务 A15 harness_result，human 回答的 RAISE 文案格式是硬需求，谓词实现确定性更高）。

### C5 · human/responded 载荷 → 携带正文（与 tool/result 同构）
两车道一致取甲。**条文**：human 的 succeeded 结算同事务（持同一 session 锁）追加恰一条 `human/responded`：`source_effect_id` 指向该 effect；payload = `{schema_version:1, interaction_ref, skip, response|null, answers|null, origin_user_seq}`（未用通道规范化为 JSON null；origin_user_seq 抄 effect 行原值不重算）；正文同时留 `effects.result`；failed/unknown 不写；重放在终态守卫返回不追加第二条。可见性依据：`v13_recall`/`v13_resolve` 无 effects SELECT，判断投影读 events——只存 hash 会让 human 回答对 recall 不可见。R1.4 的 hash 纪律管 handoff/transcript 出口，不管语义事件（tool/result、llm/message 已存正文）。不授 recall 对 effects 的 SELECT 作补救。

### 附 · D4 执法机制（stage 18）→ 否决 GUC，纯权限 + current_user 带
两车道一致否决 GUC（自定义 GUC 谁能 SET 谁就能 SET LOCAL，纯 SQL 做不成不可伪造能力位；拿得到 INSERT 的角色可自签令牌，gate 会假绿）。
**条文**：`v13_open_session`/`v13_fork`/`v13_spawn_subsession` 同属一个专用 NOLOGIN 属主，SECURITY DEFINER、固定 search_path、REVOKE PUBLIC；三函数与两个业务登录角色均无 `sessions` INSERT（INSERT 权能只随属主身份出现在函数体内）；`BEFORE INSERT` 触发器在 `current_user <> 属主` 时 RAISE 作带层（grokBuild 补充；codex 纯 ACL 案不排斥）。超级用户 `session_replication_role=replica` 为破玻璃边界，不补机制。stage 18 落地时既有直插 sessions 的测试/fixture 改走 `v13_open_session`；stage 17 **不得**提前挂此触发器（否则 1–16 前缀测试直插全红）。

### 继承自 R3 第 1 轮、无争议的条款（一并有效）
- `v13_open_session` 形状：p_spec 只允许 route_policy_name/version 两键，非法键 RAISE 零行；根行 parent/cutoff NULL、status ready、turn_no=0、next_seq=0；不复制 latch、不占 reserved、不取咨询锁、不写出生事件、不接受调用者 session_id；**不注册 tools 行**（不进 VOLATILE 具名例外，不触发 R2 §7 扩员复访；若日后要登记 = 重开 D2）。
- `v13_raise_unknown_wall(p_sid)` 共享 helper：调用方已按 session→effect 持锁；`status IN ('ready','waiting') 且有 unknown` → 置 blocked_unknown；已 blocked 或终态 → 不改；绝不清墙。a1/a1'（judge 回收）不调 helper。
- `v13_requeue_stale` 换体锁序：先无锁收集候选 session_id → 按 session_id 升序 `FOR UPDATE` sessions（**不用 SKIP LOCKED**，要与 complete 串行）→ 谓词 CAS 式重检后 UPDATE effects（等锁期间被 renew/complete 消费的重检跳过不报错）→ a2 实改到的 session 调 helper。返回 jsonb 键与计数保持不变。终态会话的 effect 进墙不 RAISE（不回滚整次清扫）。
- `v13_complete` unknown 出口：UPDATE 后、返回 accepted 前调 helper；judge 显式结算成 unknown 也抬墙；replay/stale/llm 形状降级 failed 不调。
- `v13_cancel`（stage 17 单会话版）：终态 → replay；已有未消费 cancel/requested → replay 不二插；否则追加一条 cancel/requested；本会话 ready effect → cancelled（fence+1，attempt 不动，error 空）；claimed/unknown 不动；**不改 sessions.status**（不清墙、不提前写 cancelled；终态归 A16 closeout）。
- advance 审批分支：`wait_reason=approval` 时，本会话已有 `kind='human' AND status IN ('ready','claimed','unknown')` → RAISE 零新 effect（恰一个）；否则入队 human effect，request 冻结四键 `{schema_version:1, interaction_ref, prompt?, interaction_kind?}`（interaction_kind 开放字符串，路由不读；进 request 即入 effect_id 哈希——同题同 id、改词新 id）。表达式唯一索引 `UNIQUE (session_id, (request->>'interaction_ref')) WHERE kind='human' AND request ? 'interaction_ref'`（同 ref 再问被索引拒，not_happened 后同 request 重挂同 effect_id 不冲突；终态 human 的 ref 会话内耗尽，再问换新 ref）。
- `v13_advance` 换体约束：unknown 阻塞分支不得写 sessions.status（写了会被双射触发器拒）；步 0 水位/stale 行为保持；不加漂移修理。实现前先读现正文——若今天不写 status，则不加写者只加回归断言。
- `blocked_unknown` 在 P2 的语义：非终态（占 reserved 合计、`v13_recover_idle` 排除、不得当 idle 恢复）；准入的非终态定义 = `status NOT IN ('completed','failed','cancelled')`。

## §2 P1（stage 17 `v13/control/`）最终交付清单

前置：`CREATE EXTENSION pg_jsonschema` 探针（装不上即停工，禁临时 CHECK 替代——服务 A15 harness_result 校验）；读 `v13_advance`/`v13_complete`/`v13_requeue_stale`/`load.py` 事务语义与 periphery fork 签名/spawn_kind 可空性。

交付（单文件 `v13_control.sql` 单事务原子加载）：
1. 部分索引 `effects(session_id) WHERE status='unknown'`
2. `v13_raise_unknown_wall` helper
3. 换体 `v13_requeue_stale`（锁序 + a2 抬墙，签名/返回键不变）
4. 换体 `v13_complete`（unknown 出口抬墙 + D6 human 校验 + human/responded，签名不变）
5. `v13_resolve_unknown`（effect 半边按报告 §4.1 + C1 清回）
6. A16 无子会话 closeout（三事件 + 收据 + C2 前置顺序 + 重放短路 + 同事务 + 不二次扣预算）
7. `v13_cancel`（单会话粘性）
8. 换体 `v13_advance`（A15 四值/wait 词表/wake/material spend 校验 + 审批分支恰一个 human + unknown 阻塞不写 status + steer 断言：claimed 期间 request 不变）
9. D6 校验谓词 + human ref 表达式唯一索引
10. C3 回填→断言→双延迟约束触发器（DROP IF EXISTS + CREATE）
11. GRANT/REVOKE（新函数 REVOKE PUBLIC 后 GRANT v13_route；不授 v13_resolve）
12. `v13/control/test_control.py`：G-ctx10-delivery（+interaction_kind/delivery_kind 轴）/wait-lexicon（+approval 恰一 human）/wake/spend、G-ctx10-approval-payload（C4 决策表逐行）、G-ctx10-approval-ref（mismatch 带 current=、fence stale、replay 不泄露通道错误、耗尽 ref 再入队拒）、G-wall-session-status、G-resolve-clears-overlay（含 human 例外 → waiting）、G-cancel-does-not-unwall、G-closeout-unknown-authority（计数权威 + 重放短路 + 终态残留可重放）、G-user-message-keeps-wall、G-wall-no-parent-write、双射触发器正负例（单边改提交必败、真实 COMMIT）、锁序并发压测（complete/requeue/renew 无死锁）、SET ROLE v13_recall 可读 human/responded 且不能 SELECT effects；再加 stage 1–16 全量回归（前缀加载语义不变、1–16 文件字节不动）。

## §3 P2（stage 18 `v13/spawn/`）增量
D4 整包（v13_open_session + 专用属主 + 两角色/登录 + BEFORE INSERT current_user 触发器 + 直插测试改走 open）与 A17（tools 行 spawn_subsession + guard VOLATILE 具名例外 + DEFINER + 两参咨询锁准入 + reserved 聚合查询不加列）、`v_goal_tree(root)`、`v13_recover_idle`（排除墙/blocked_unknown；「子齐父未验收」+未消费 repair/replan）；子 closeout 事务内零父事件。gate：G-spawn-unique-writer（三函数名单 + 运行角色直插拒 + 误授 INSERT 无令牌仍拒）、G-open-session-shape、G-sql-write-closed、G-spawn-fanout、G-ctx1-spawn、双根互不占预算、墙上子会话仍计入非终态合计。

## §4 少数意见存档（复访触发）
- grokBuild C4：未知键「忽略不授权」而非拒绝——若未来出现合法的注释性键需求再复访。
- codex C2：无（已并入）；codex C3：终态+unknown 残留应安装失败——若出现终态残留引发真实事故再收紧。
- codex D6：human 校验复用 pg_jsonschema——若谓词实现出现维护负担再统一。
- grokBuild C2：不要 closeout status 保险带——若保险带在某个合法路径误伤（理论上双射触发器下不应发生）再摘除。

## §5 证据等级
R3 全部裁决基于 selection 事实源：迁移报告（源码级卷宗锚点）+ R2 条文 + v13_core.sql/v13_twophase.sql 现文。`v13_advance`/`v13_economy`/periphery 的具体函数体未在 selection 中，涉及它们的条款均为「换体必须遵守的合同」而非对现正文的描述——stage 17 实施第一步必须先读现文核对，若被证伪（如 advance 今天不写 status、spawn_kind NOT NULL 无根值），停下来按证据修订 R3 对应句，不得自行换裁决。

---

## §6 R3a 补裁（2026-09-26 第二轮：wake 机器形状 + logical_turn_id 住所 + material ≤1）

- 触发：P1 实施轮（Loop Turn 2）双车道 oracle 一致 STOP——A15 两处「语义已裁、机器形状未裁」。本节并入 R3，与 §1–§5 同效；R2 的 A15 四值/wait 词表/审批两段不重开。
- 轮次：R3a 第 1 轮三车道（grokBuild/codex 全文 + openCode 校验）→ 8 处实施级分叉由控制器按「fail-closed、R1 键表最小扩员、设计稿原文对齐、receipt 与 effect 分离（迁移报告 §4/卷宗 C 要点②）」合并，少数意见存档 §6.7。

### 6.1 权威落点与判别（合并裁定：codex 案）

- `harness_result` 就是 harness effect 结算时 `v13_complete(p_result)` 的**顶层对象**（不设嵌套包装键），accepted 后原样存 `effects.result`；advance 读权威 = `effects.result->>'result_kind'`；`tool/result` 等语义事件只是投影。
- **判别器在 request 侧（服务器权威）**：凡 `effects.request` 带有 §6.3 的 `logical_turn_id`+`continuation_index` 对的 tool effect 即 harness effect，其 succeeded 结算的 `p_result` 必须通过 `harness_result/v1` 校验，否则 RAISE（协议错误，零写入不烧 attempt/fence，与 R3 C4 同类）。普通结果（无该 request 对）不进本套校验，行为不变。
- **P1 harness effect 只允许 `kind='tool'`**；`judge|human|context_refresh|llm` 的 request 出现该对、或其 p_result 形似 harness_result → RAISE。
- `harness_result/v1` 顶层闭集（R1 八键 + R3a 两键，`additionalProperties:false`）：`result_kind`、`wait_reason`、`delivery_kind`、`harness_session_ref`、`resume_token`、`interaction_id`、`partial`、`content_hash`（sha256 小写 hex 数组，1..32，元素唯一）、**`wake`**、**`signals`**。`logical_turn_id`/`continuation_index`/`interaction_ref`/`schema_version`/`prompt`/`interaction_kind` 禁止出现在结果里（出现即未知键 RAISE）。schema 文档住策略行 `harness_result_schema`（version 1，jsonb，active），`pg_jsonschema` 消费；交叉矩阵放同一 schema 的 if/then，SQL 只留 schema 表达不了的部分。

### 6.2 W · wake 机器形状

- 顶层键名 `wake`；object；null/数组/字符串拒绝；对象闭集未知键拒绝；判别键 `kind` 四值**严格 one-of**（该 kind 必填键齐、其余三类键全缺），不支持 AND/OR 组合（需要多条件=上游聚合成一个事件再用 event 变体）。
- 四变体：
  - `{kind:'event', event_type}`：字符串 1..128，`^[A-Za-z0-9_./:-]+$`，大小写敏感，值域=events 开放词表精确 type（无 glob/前缀/正则）。满足=同会话存在 `type=event_type` 且 `seq` **严格大于本 settle 批次尾 seq**（批次尾=同 `source_effect_id` 的 effect_done/tool/result/llm/message/repair:required/replan:required 中最大 seq）的事件——settle 前旧事件与同 settle 自产事件都不满足；缺 `effect_done` = 账本损坏 RAISE。比较用绑定参数，禁拼接动态 SQL。
  - `{kind:'not_before', at}`：RFC3339 字符串，必须带 `Z` 或 `±HH:MM` 时区（禁 epoch 数字）；满足=`clock_timestamp() >= at::timestamptz`（DB 时钟权威；过去时刻合法，立即满足）。
  - `{kind:'artifact', content_hash}`：单个 64 位小写 hex sha256（禁数组/带 kind）。满足=`EXISTS(artifacts WHERE content_hash=…)` **全局内容地址**（不按会话收窄）+ `produced_by` 连接 effect 仍 succeeded 作 belt。
  - `{kind:'children_terminal', child_session_ids}`：**非空唯一 canonical 小写 uuid 数组**，语义=ALL（单个子也用长度 1 数组）。**P1 的 complete 在 schema 通过后仍 RAISE**（稳定子串 `children_terminal requires stage 18`，零变化）；P2 启用评估：每个 id 必须存在且 `parent_session_id`=本会话直接子、status ∈ 终态三值（`blocked_unknown` 非终态），缺失/非直接子/重复 RAISE。
- **矩阵**（禁止=键必须缺席，显式 null 同非法）：`progress`：wait_reason/wake/interaction_id 禁、signals 可缺席；`finish`/`reject`：三者全禁、signals 禁；`wait`+`approval`：`wake` **禁止**（唤醒器=且仅=随后那枚 human 的成功结算）、`interaction_id` 必填非空 1..256；`wait`+`evidence|quota`：`wake` 必填（四变体之一）、`interaction_id` 禁。`delivery_kind='USER_ACTION_REQUIRED'` ⇒ 必须 wait+approval+interaction_id 存在+wake 缺席；其它 delivery_kind 值（1..64 或缺席）一律收下路由不读。
- 审批关联链：advance 把 harness_result 的 `interaction_id` **逐字节复制**为 human request 的 `interaction_ref`（human 四键 request 不变、不加第五键）；对 succeeded approval harness 结果建会话作用域表达式唯一索引 `(session_id, result->>'interaction_id')`（仅覆盖带 request 逻辑对且 wait+approval 的行），human 结算后 advance 凭 `(session, interaction_ref)` 精确连回唯一 harness effect 读逻辑对——0 行或多行=账本损坏 RAISE，禁按 recency 挑选。
- **判定深度**：complete 只做形状/矩阵/格式/child 拒收，**不评估条件是否已满足**（wait 的正常状态就是未满足）。评估唯一在 advance（会话锁内、任何新 effect 入队与 ⑤ 扣减之前）：未满足→零写入、`sessions.status` 置 `waiting`、返回既有词 `'waiting'`（无新返回词；纯时间等待无人调 advance 时保持 waiting，活性靠驱动重调——P1 无扫地僧，P2 `v13_recover_idle` 把「存在未观察 evidence/quota wait」排除出 idle 是 P2 合同）；满足→同事务先追加恰一条 `wake/satisfied`（`source_effect_id`=等待 effect；payload 只含 `{effect_id, wake_kind}`，**不复制 logical_turn_id**）再继续路由。`wake/satisfied` 对同一 source 至多一条（部分唯一索引执法）；approval 全程零 wake/satisfied。

### 6.3 L · logical_turn_id 住所与读路径（两车道一致：codex 案）

- 「request artifact」= **`effects.request` jsonb 顶层**（非 artifacts 行——artifacts 的 `produced_by` 须已 succeeded、无 session_id，时序与连接键都不成立）。`logical_turn_id`（canonical 小写 uuid 文本，36 字符）与 `continuation_index`（JSON 整数，0..2147483647）**成对存在或成对缺席**；只许出现在 harness tool request；两者随整份 request 进 `v13_effect_id` 哈希（同请求同 id，改字即新 effect）。
- **唯一写者=advance**（入队前盖章；模型参数带同名键服务器覆盖）：①新 logical turn（本 user turn 首枚 harness、或前驱是已计 material 的 progress、或被封顶/`interaction_kind∈{material_cap,repair_cap,replan_cap}` 的 human 已答）→ 新 uuid、index=0；②续传（前驱=wait 恢复〔approval 经 interaction 链找回；evidence/quota 在 wake/satisfied 同格续〕或 progress+同批 signals 零 material）→ 沿用前驱 request 的 id、index=前驱+1；③`finish`/`reject` 不续传。运输重试=同 request 同 effect 不新行。
- 缺失/非法（缺键、单边、类型错、非 canonical、index 溢出）→ **双层 fail-closed**：complete 在 succeeded 结算前 RAISE（稳定子串 `logical_turn_id required`）；advance 消费前再校验（防绕过）。禁自动补 id、禁按 recency 推断、禁降级 failed/human/reject。回显到结果=未知键 RAISE。

### 6.4 S · material ≤1 计数公式（合并裁定：codex 收据案）

- **signals 机器形状**：`signals` 可缺席；存在则数组 1..2、unique、元素仅 `'repair/required'`/`'replan/required'` 精确串；`finish`/`reject` 禁携带。complete 接受时按固定顺序（repair 先 replan 后）各追加恰一条同名事件（`source_effect_id`=本 effect，payload 只带版本标识**不复制逻辑对**）；replay 不二写。同会话同 source 同 type 至多一条（部分唯一索引）。
- **「同批」**= 同一次被接受的 harness result 及该 complete 据其 `signals` 以同一 `source_effect_id` 原子追加的事件集——不是同 turn_no/同事务/recency。advance 消费时断言 `result.signals` 与该 source 的信号事件集**完全相等**，不等=账本损坏 RAISE。
- **material 候选谓词**：`status='succeeded' AND kind='tool' AND request 带合法逻辑对 AND result 过 v1 校验 AND (result_kind='finish' OR (result_kind='progress' AND 不存在该 source 的 repair/replan 事件))`。wait/reject/带 signal 的 progress/failed/unknown/cancelled/非 harness=零 material。`finish` 即使旁路存在信号事件也计（complete 本应拒绝 finish+signals）。
- **收据模型（receipt 与 effect 分离）**：「一次 material」的权威行=事件 `turn/material_spent`（`source_effect_id`=被 ⑤ 消费的 effect；payload 不复制逻辑对）。`material_count(session, ltid) = count(turn/material_spent 事件 JOIN source effect WHERE effect.session_id=session AND effect.request.logical_turn_id=ltid)`。不直接数 succeeded effect（succeeded ≠ 已被 ⑤ 消费）。
- **advance ⑤ 执法**（会话锁内、既有预算扣减前）：非候选跳过；候选查同 session+ltid 既有收据——0 条→执行**既有** ⑤ 扣减（收据与扣减同事务，首次消费追加恰一条 `turn/material_spent`）；1 条且 source=本 effect→advance 重放，跳过二次扣减/收据；1 条且 source=其他 effect 或 >1 条→**fail-loud RAISE**（零二次扣减、零收据、会话保持进入前状态，已 succeeded 的第二 effect 留审计——控制面身份错误不得伪装成业务分支）。任一步失败扣减与收据一起回滚。
- **DDL belt**：`turn/material_spent` 对同 source 至多一条的部分唯一索引 + 专用 INSERT 触发器（先锁 session 行→校验 source 存在/同 session/succeeded/是候选→经 source request 查该 ltid 无其他收据→只 RAISE 不代扣；封 raw events INSERT 绕路）；`events(source_effect_id, type)` 支持索引；harness request 逻辑对的会话作用域表达式索引（join 查询用）。
- **与 turn_no/预算**：material spend = advance ⑤ 那一次**既有**预算变化的 per-logical-turn 幂等收据；若活体 economy 用 `turn_no` 表达该 charge，首次收据与该次 `turn_no` 更新同事务。R3a 不授权 complete/spawn/wake/resolve/closeout 新增任何 `turn_no` 写；closeout 只抄已提交值。`turn_budget.max_cycles` 继续管同 user message 路由环（两上限叠用）。实施前必读 ⑤ 现文：若 ⑤ 已写 `turn_no`，停下按迁移报告 §8 报告，不绑不删。

### 6.5 P1（stage 17）清单增补（叠加 R3 §2）

新增交付：`harness_result_schema`+`harness_fold_cap` 不落（cap 归 P4 thresholds）；`v13_validate_harness_result_v1`（同步，失败 RAISE）；`v13_wake_is_satisfied_v1(sid, effect, wake)`（STABLE 只读，P1 对 children_terminal RAISE unsupported）；`v13_material_spent_guard` 触发器；上述索引（wake/satisfied 唯一、signals 唯一、material 唯一、interaction_id 唯一、逻辑对表达式、source+type 支持索引；`content_hash` 无索引时可补非唯一）；换体 `v13_complete`（顺序：定位+锁→token→stale/replay→R3 human 校验→llm 降级→harness v1+request 对+矩阵+signals 投影+child 拒收→写终态→effect_done/tool/result→R3 抬墙→提交；一切协议 RAISE 在写行前）；换体 `v13_advance`（步 0 水位→墙前置→定位待消费 succeeded harness→wait 分流〔approval=human；evidence/quota=wake 评估→waiting/wake:satisfied〕→signals 投影断言→material 收据检查+⑤→逻辑对续传/新建→既有 route/closeout）。
安装期存量断言（叠加 R3 C3）：不存在形似 A15 已成功结果而 request 缺逻辑对的行；不存在单边逻辑对；不存在重复 succeeded approval interaction_id；不存在 signals 与事件集不一致；不存在 `turn/material_spent` 旧事件。禁自动回填逻辑 id。
gate 增补：G-ctx10-wake 扩（四变体正例+混变体/未知键/null/空串/非 RFC3339/大写 hash/空重复 child 数组负例；approval 带 wake 拒；USER_ACTION 矩阵；event 的批次尾 seq 锚；artifact 全局命中+belt；not_before 时区等价/过去时刻；children_terminal P1 拒收；重复 advance 恰一条 wake/satisfied；stale/replay 先于 schema 错误）；新 G-ctx10-logical-turn（首对 uuid/0；重试同 id；wait/零 material 续传 +1；material 后新 uuid/0；finish/reject 不续；request hash 随对变；缺/单边/非 canonical 双层拒；approval 经链找回唯一源）；G-ctx10-spend 扩（finish/progress 无 signal 计 1；+signal 零计；同 source 重放不重扣；不同 source 同 ltid 第二笔 RAISE 且总收据=1；closeout/complete/spawn/resolve 零收据零扣）。
设计文档同步：`v13-context-on-pg.md` §6.8/A15 合同区追加 wake schema/矩阵/signals/逻辑对/收据公式，§10 gate 列表扩三名；标注 children_terminal P1 拒收、P1 唤醒者=驱动重调、P2 启用评估与 recover_idle 排除项。

### 6.6 实施前置（叠加 R3 §5）

必读活体：完整加载 1–16 后的 `v13_advance`（签名/返回类型/⑤是否写 turn_no）、`v13_complete`、**活体 `v13_requeue_stale`（在 mgraph 换体，a1 覆盖 judge+mgraph_consolidate——换体以 mgraph 正文为底，禁从 twophase 旧体回退）**；`pg_jsonschema` 对 oneOf/if:then/pattern/format:date-time 的支持探针（fixture 实测，失败停工不降级）。R1 八键的既有值类型逐字复用，禁 stage 17 重新解释。

### 6.7 少数意见存档（复访触发）

- grokBuild：嵌套 `p_result.harness_result` 包装键 + `candidate_kind` 兄弟键——若未来需要普通结果与 harness 结果在同一 effect 混装再复访。
- grokBuild：harness effect 允许 `kind='llm'`（跳过 llm 降级不写 llm/message）——若 harness 实际经 llm effect 驱动且 tool-only 挡住真实用法，schema v2 扩。
- grokBuild：child 变体单 uuid `{kind:'child_terminal', child_session_id}`——已被数组 ALL 案覆盖，仅命名留档。
- grokBuild：approval 行携带 `interaction_ref`/`prompt`/`interaction_kind`——与 R1 interaction_id 复用案冲突，若 v1 审批题面需要 harness 传 prompt 再开 schema v2。
- grokBuild：material 超限不 RAISE 改入队 `interaction_kind='material_cap'` human、`harness_fold_cap` 策略行 {repair:3,replan:3}——超限 human 案被否（身份错误不得伪装业务分支）；**fold/repair 次数 cap 本身是 R2「超限 repair 走 human/reject」的既有语义，归 P4 thresholds 带（G-triage/路由表）实施**，P1 不落。
- grokBuild：wake 未满足不动 status、返回新词 `wake_pending`、收据名 `wake/observed`——被设计稿 §10「waiting 的会话 wake 前零自动推进」+ 既有返回词 `waiting` 对齐案否。
- grokBuild：`fold` 键名与短名元素——被 `signals` 精确事件名案否（免名映射层）。

---

## §7 R3b 补裁（2026-09-26 第三轮：harness 生产侧 H + A16 收据机器形状 + P1 完备性扫掠）

- 触发：P1 第二轮 STOP（Turn 3）——①活体零 harness 概念，R3a 判别器缺生产侧入口；②A16 收据五字段无 JSON 键/算法。本轮三块裁完两车道均判 **GO**：P1 不应再因「语义已裁、机器形状未裁」停工。
- 全文（两车道完整裁决）：`docs/reviews/v13-control-plane-oracle-r3b-full-2026-09-26.md`；本节为操作条文精炼，冲突处以本节+全文 grokBuild 案为准，codex 差异记 §7.4。D4–D6/A15–A21/R3/R3a 不重开。

### 7.1 H · harness 生产侧（A 案：具名目录行）

- **种子 tools 行**：`name='harness_turn'`, `kind='tool'`, `handler='worker:harness_turn'`, `param_spec='{}'`, `enabled=true`，description 纯 ASCII。`kind=tool` 不进 v13_tools_guard/A17 VOLATILE 例外；外部 IO 失败语义=现有 a2。单源谓词 `v13_is_harness_tool(p_name,p_kind)`（IMMUTABLE，函数体内唯一一次字面量）；扩员=改函数+设计修订+gate 同发。
- **request 六键闭集**（仅此行，jsonb_build_object 顺序固定）：`{tool:'harness_turn', params:{}, handler:<信封冻结>, tools_revision:<信封整数>, logical_turn_id:<小写 uuid 36>, continuation_index:<int 0..2^31-1>}`；缺一/多一/单边/类型错/非 canonical RAISE 零行；params 内出现逻辑键同样 RAISE。普通 tool 维持四键，逻辑键必缺。身份照旧 v13_effect_id（六键进哈希）。
- **盖章点**：仅 v13_advance，已持 session 锁、调 v13_enqueue_effect 之前；route 保持 STABLE 不生 uuid；enqueue 不发明 id 只做拒收带（顶层见逻辑对任一键⇒必须成对合法且 p_kind='tool' 且 v13_is_harness_tool，否则 RAISE `v13: logical_turn_id required`）；complete 加带层（harness 而 request 无对、或有对而非 harness → RAISE 同子串；有对则 p_result 必过 v1）。sql 快路臂路由到 harness_turn → RAISE（配置错误）。
- **前驱查询** `v13_harness_predecessor(p_sid)→uuid`：本 user turn（origin_user_seq=v13_last_user_seq）内 kind=tool、harness 名、request 对合法；排序=events.source_effect_id 上 max(seq) DESC NULLS LAST → created_at DESC → effect_id DESC，LIMIT 1。零行=本 user turn 无 harness。断链（更老 succeeded 无后继）RAISE `v13: harness tail gap`，禁挑最近掩盖。
- **盖章模式表**（grokBuild §3.H）：无前驱→new(uuid,idx0)；failed/cancelled→retry(原样抄对，同 effect_id 重挂)；succeeded progress 且有 material 收据→new；succeeded progress 且同批 signals 且无收据→continue(抄 id，idx+1，溢出 RAISE)；signals 与收据同存→账本损坏 RAISE；succeeded wait 且已满足（approval:human succeeded；evidence/quota:本事务已写/将写 wake/satisfied）→continue；finish/reject→不盖章走 closeout，再入队 RAISE；unknown/ready/claimed→不可达（①或墙已返）。cap human 已答→new（读规则，P1 不生产）。
- **续传义务（grokBuild 案，续传不经 route）**：continue 模式由 advance 锁内直接入队下一枚 harness，不调 v13_route；入队前追加一条 turn/route，payload 恰 `{action:'tool', reason:'harness_continuation', tool:'harness_turn', params:{}}`（v13_cycle_no 继续计次；action 仍在六词闭集）。new（含首枚与 material 后）必须经现有 route（action=tool 且目录名通过单源谓词才盖章）；retry 同样只在 route 再选中时发生。续传入队后行已 failed/cancelled（attempt 封顶）→不 send_work，走 closeout failed（turn_end_reason='harness_attempts'）。
- harness 共用 effect_attempt_cap.tool=3，不加策略行。
- gate（并入 G-ctx10-logical-turn）：首枚六键闭集 idx0 uuid canonical；ready/claimed 期间二次 advance 零新行返 waiting；failed 后同 route 再入队同 effect_id fence+1 两键不变；material 后 route 再选中新 uuid idx0；wait/progress+signal 后不经判断可出 index+1 且有 reason=harness_continuation 的 turn/route；普通 tool/judge/llm/human 带任一逻辑键 enqueue RAISE；send_summary_email 的 result 含 result_kind 也不 closeout 不盖章；直 enqueue 缺对/单边 RAISE。

### 7.2 A16 · closeout 收据机器形状

- **函数** `v13_closeout(p_sid uuid, p_outcome text, p_reason text, p_attempts_exhausted boolean DEFAULT false) → jsonb`；p_outcome∈三终态；锁序：调用方已持锁则重入否则自锁；只授 v13_route；不是推进函数（不 parse/route/enqueue/外部 IO）。换体后 advance 各终态臂（route finish/reject、abandon、budget、context_refresh 封顶、judge attempt 封顶、harness_finish/reject/attempts、approval_exhausted、cancel 封印）全部改调它，禁止平行直写 status/turn:end。
- **收据=事件顶层 payload**（不嵌套），三型 payload 键集相同（type+sessions.status+turn_end_reason 取值不同）。同事务、改 status 之前另写一条与今天同形的 turn/end（completed→delivered:true；failed|cancelled→delivered:false；仅 attempts 耗尽时多 attempts_exhausted:true，该键不进收据）。
- **收据键闭集**：`{schema_version:1, origin_user_seq:<int, codex 并入>, spent:{turn_no,cycle_no,max_cycles,material_count}（四键 JSON 整数≥0；material_count=本会话 turn/material_spent 事件条数跨 user turn 累计）, produced_hashes:[64 位小写 hex 升序去重，可空数组], children:[]（P1 恒空数组禁 null；EXISTS 子会话时任何 outcome RAISE `v13: closeout children require stage 18`）, unconsumed:{repair_effect_ids,replan_effect_ids,material_effect_ids,wake_pending_effect_ids,approval_pending_effect_ids}（五键都在，升序去重小写 uuid 数组；谓词见全文：repair/replan=事件 source 全集不减法；material=候选无收据；wake_pending=wait+evidence|quota 无 wake/satisfied；approval_pending=wait+approval 无 succeeded 对应 human）, state_hash, turn_end_reason:<1..128 [A-Za-z0-9_./:-]+>}`。未知键 RAISE。
- **produced_hashes 算法**：artifacts 有 content_hash+produced_by → DISTINCT content_hash JOIN effects(session,succeeded) 升序；两列不存在→退化沿 context_active_artifact 的 replay.prior_artifact_id 链（深度≤64）收集 manifest sections[].content_hash，且 wake artifact 变体求值时 RAISE（与 children_terminal 同手法）；都无则 []，closeout 仍成功。
- **预算终态同事务=冻结投影**：活体 ⑤ 只读 v13_cycle_no 不写 turn_no、无可扣余额列——closeout 禁止 turn_no 任何赋值、禁止写 turn/material_spent、禁改策略；只把 spent 对象写进印章。completed/非逃生 failed 上还有未付 material 候选 → RAISE 不补记。
- **前置矩阵**：①已终态短路（不查计数；恰一条 session/<status> 返回已存 payload 原文；零条 RAISE missing seal；多条 RAISE duplicate seal；outcome 不一致 RAISE）。②公共前置（RAISE `v13: closeout precondition` 带稳定尾词）：active（ready|claimed 且 kind<>'human'）=0；unknown=0；v13_pending_human(=kind human AND status IN ready,claimed，与 C1 清回共用)=假；status<>'blocked_unknown'；无子会话。③严格前置（completed 及 failed∈{harness_reject,injection_veto 等 route 否决}）：material/wake_pending/approval_pending 三数组全空且「续传未还」为假（最新 harness=progress+signals 或已满足 wait 且无同 logical_turn_id index+1 后继）——即**未满足的 evidence/quota wait 不能完成也不能 harness_reject 收场，但可被 cancel 或预算逃生收场且收据可见**。④逃生前置（cancelled 及 failed∈{budget_exhausted,resolve_budget,judge_attempts,context_refresh,harness_attempts,approval_exhausted}）：③四项不挡，数组实填。
- **写序**：前置→算 spent/produced/children/unconsumed/turn_end_reason→turn/end→算 state_hash（此刻 turn/end 已在、印章未在）→印章事件（source_effect_id 空）→UPDATE status（不碰 turn_no/next_seq/策略/effect）。任一步 RAISE 整笔回滚。
- **state_hash 算法**：输入= jsonb 数组 ::text 再 sha256 小写 hex（禁 jsonb_pretty/row::text；标量先转 text）：`['v1', [session_id,turn_no,route_policy_name,route_policy_version,goal_hash,tools_revision,candidate_generation_revision,排除三印章 type 后的 max(seq)（无则 '-1'）], [effects 按 effect_id 文本升序，每行 [effect_id,kind,status,attempt_no,fence,tool_name 或 '',request_hash,origin_user_seq]], [非印章事件按 seq 升序，每行 [seq,type,payload_hash,source_effect_id 或 '']]]`。印章三 type 不进第四段；status/next_seq 不进。合同=印章里存的那一串：gate 在 closeout 返回前重算必等、requeue 前的事务重算必等，requeue 后不再要求（终态 effect 可进墙改 status）。
- 二次调用：零 INSERT/UPDATE，返回第一次 payload（jsonb 相等不重建）；advance 仍返 terminal，无新词。

### 7.3 C · 完备性扫掠裁定（全文 §3.C 逐项表为谁）

- **advance 换体七步总账**（session 锁内）：1 步 0 七键 stale 不修漂移；2 终态→terminal；3 有 unknown 或已是墙：非墙非终态 RAISE `v13: unknown wall drift`（只拒不写回）→未消费 cancel 则 ready 扫成 cancelled（fence+1，attempt 不动，error NULL，租约清空）→**不更新 session**，返 waiting（今天那句覆盖 unknown 的 SET waiting 删除）；4 未消费 cancel 且无 unknown：同清扫→仍有 claimed→置 waiting 返 waiting→无 ready|claimed|unknown→closeout cancelled('cancel')；5 无 cancel 有 ready|claimed→置 waiting 返 waiting；6 本 user turn 有 harness 前驱→消费相（finish/reject 封印不受周期闸阻；未满足 wait 置 waiting 零新 effect；缺审批 human 周期允许则入队否则预算逃生；该续传走续传臂；material 候选写/拒收据不改 turn_no；然后落回旧管线）；7 旧管线（snap.failed 审计/abandon/context 闸/周期闸/judge 缺口/route/各臂；tool 臂才可能 new/retry 盖章；终态臂改 closeout）。无 harness 前驱不进第 6 步。**返回词闭集仍 progressed|waiting|terminal|stale，出现别的词=实现错误应 RAISE**。
- **payload 注册表**（全部恰好键集，未知键 RAISE）：`cancel/requested`={schema_version:1,scope:'session'}；`unknown_resolved`={schema_version:1,effect_id,resolution,evidence_hash}（evidence_hash=digest(evidence::text,'sha256') 不存正文；证据闭集：confirmed={observation:'committed',payload_hash==digest(effects.result::text)}、not_happened={observation:'absent'}、rolled_back={observation:'rolled_back',compensation_ref 1..256}；failed 两支写 effects.error={code:'unknown_resolved',resolution,evidence_hash}，confirmed 清 error；attempt/fence/request/result 都不改〔a2 已 fence+1〕；成功只返 accepted，失败 RAISE）；`turn/material_spent`={schema_version:1,effect_id}；`repair|required`/`replan|required`={schema_version:1}；`wake/satisfied`={effect_id,wake_kind}（wake_kind∈event|not_before|artifact|children_terminal；不加 schema_version）；`steer/injected`={schema_version:1}（P1 不新增生产者，gate G-steer-frozen-request 用 append_event 直写断言 request/hash/status/fence/attempt 不变+旧信封 advance=stale+原令牌 complete 仍 accepted）。
- **C4 应用谓词（兼容线，不加会拒掉 DP1 全部 {reason} human）**：仅当 kind=human 且 succeeded 且 request 含 interaction_ref 时跑 one-of/字节相等/未知键拒；无 ref 的 {reason} human 照旧 succeeded 不写 human/responded。审批 human request 由 advance 写成恰 {schema_version:1,interaction_ref} 两键（interaction_id 逐字节复制；不写 prompt/interaction_kind——harness 结果禁这两键，P1 无题面来源）。
- **v13_wake_is_satisfied_v1 波动性更正**：必须 VOLATILE（not_before 用 clock_timestamp，禁 STABLE 缓存）；只从 advance 调一次，不进索引。
- **requeue 换体追加分叉**：回收臂（租约过期可重放 kind）若会话有未消费 cancel→改 cancelled+fence+1+清租约（attempt 不动 error NULL），不计 reclaimed_ready、不 send_work；返回键集不变。锁序/底稿维持 R3（mgraph 活体，pg_get_functiondef 先取）。
- **enqueue 与 cancel 带**：enqueue 插行/重挂前，会话有未消费 cancel → RAISE `v13: unconsumed cancel/requested`（防直调；advance 正常路径已先行转 cancel 相）。未消费定义=存在 cancel/requested 且 seq>本会话 session/cancelled max(seq)（无则 -1）且非终态。
- **v13_cancel 终化**：终态→replay 且零写入（封印后不扫 effect，防改写 state_hash 那版）；非终态锁后按 effect_id 升序；无未消费则追加一条；已有则不追加但仍扫 ready→cancelled（防 requeue 间隙放回的 judge 逃逸）；claimed|unknown 不动；不改 status。
- **harness_result_schema 策略行**：v13_policies 一行 name='harness_result_schema' version=1 active=true，value 恰 {dialect:'draft-07', schema:<$schema 必须是 draft-07 的 JSON Schema>}；校验函数 v13_validate_harness_result_v1 失败 RAISE `v13: harness_result schema`；扩展入口默认 jsonb_matches_schema，安装第一件事探针真名。Schema 正文=R3a §6.1–6.2 矩阵机械转写（十键 additionalProperties:false、四值 if/then、wake 四变体 oneOf、format:date-time 只用于 wake.at）。SQL 只留 schema 表达不了的部分。
- **三注解键默认**（安装期若在 R1/设计/ch07 找到字面类型则字面赢）：harness_session_ref 1..256、resume_token 1..512、partial boolean；都可缺席禁 null；三键+delivery_kind+content_hash 盲读。
- **新索引**：ix_effects_unknown(session_id)WHERE unknown；ux_events_wake_satisfied(session_id,source_effect_id)WHERE type='wake/satisfied'；ux_events_signal(session_id,source_effect_id,type)WHERE type IN(repair,replan/required)；ux_events_material(session_id,source_effect_id)WHERE type='turn/material_spent'；ix_events_source_type(source_effect_id,type)；ux_effects_approval_interaction(session_id,(result->>'interaction_id'))WHERE succeeded tool 带对 wait+approval；human interaction_ref 唯一（R3 原文）；ix_effects_harness_pair(session_id,(request->>'logical_turn_id'),((request->>'continuation_index')::int))WHERE kind='tool' AND request?'logical_turn_id'。
- **事件守卫触发器** v13_control_event_guard（BEFORE INSERT，WHEN 限九 type：wake/satisfied、repair|required、replan|required、turn/material_spent、human/responded、unknown_resolved、三 session/*、cancel/requested）：只 RAISE（该有 source 的不许空、payload 键集必等注册表）；v13_material_spent_guard 仍只管至多一条+候选资格。两触发器不改行不入队。
- **安装探针 DO**：pg_jsonschema 装不上即败；活动 schema 接受两种时区形式、拒无时区串与 epoch，失败 RAISE `v13: pg_jsonschema draft-07 date-time not enforced` 整笔回滚，禁降级 CHECK。
- **双射触发器**细节（R3 C2/C3 落地）：共享函数只 RAISE；effects 侧 INSERT/DELETE/UPDATE OF status,session_id（两侧都查）；sessions 侧 INSERT/UPDATE OF status；DEFERRABLE INITIALLY DEFERRED；安装序=回填→断言→DROP IF EXISTS→建触发器→**然后才 CREATE OR REPLACE 写 unknown 的函数**（顺序颠倒=旧函数写 unknown 不抬墙被双射打回）。
- **GRANT**：新函数全部 REVOKE PUBLIC 后 GRANT v13_route（含 OR REPLACE 的四个换体函数重执行一次，幂等）；不授 resolve/recall；触发器函数不 GRANT。
- **明确 P1 不做**：closeout/inbox_residual（残留进 unconsumed）；harness finish 验收门=严格前置+result 过 v1（不读 thresholds）；steer 正文；children_terminal 求值；quota/spent·voided；fold cap（P4）；advance 在墙上 claim 仍可领 ready（已知缝不改 v13_claim，closeout 被 active 挡）。
- **风险红线**（全文 §5）：C4 不加应用谓词会拒掉全部 DP1 {reason} human；终态臂改道 closeout 后全量测试若精确计数 turn/end 需改为期待 turn/end+恰一条印章（前缀 1–16 不受影响）；state_hash 非 seal 后活不变量；mgraph 活体若被 twophase 文本覆盖丢 mgraph_consolidate 回收（换体前 pg_get_functiondef）；双 BEGIN 风险（loader 已包事务则去文件内包装保语义）；stage 17 的 INSERT INTO tools 会拨 v13_tools_meta.revision（gate 用相对比较）。

### 7.4 codex 少数意见存档

- 收据含结构化 reason 对象 {code,source_effect_id,request_event_id}（cancelled 的 request_event_id 指向未消费 cancel/requested）——被 turn_end_reason 字符串案否；复访触发：P2+ 需要终结归因细粒度时升 schema_version。
- harness request 第七键 mutating:true（提前冻结 P3 中断语义）——被六键案否（A18 interruptible 是目录 allowlist 键非 request 键）；复访触发：P3 实施若发现需要 per-request 中断档位。
- 续传由 route 驱动（route 再选中 harness_turn 才续）而非 advance 义务——被「续传未还硬拒 completed」+义务案否；复访触发：续传臂在实践中压制 route 判断时。
- 收据 spent 键名 session_turn_no/route_cycles_current_turn——命名差异，采 grokBuild 四键。

### 7.5 GO 判定

两车道均 **GO**：H 生产入口/盖章点/首枚续传重试/隔离、A16 键/哈希/前置/重放、C 表全部 payload 闭集已裁。残留仅安装期事实探针（五项，默认已写死：artifacts 列缺失→manifest 链+artifact wake RAISE；jsonb_matches_schema 真名；R1 三键字面类型；loader 双 BEGIN；mgraph kind 集），**不必再叫 Oracle**，按默认分支继续。
