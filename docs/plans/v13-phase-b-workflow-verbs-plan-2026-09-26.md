# v13 Phase B 开发计划：工作流动词闭合（stage 23 acl + stage 24 observe + stage 25 handoff）— R8 终裁版 r9（九轮审核，终轮三通道 APPROVE；可开工）

> 状态：**R8 已裁（2026-09-27）：D7=甲 overload、D16=DEFINER 单写者/无 −1/最小 hash 集/回读先于策略；计划 r9 经九轮审核，终轮三通道 APPROVE——可开工**。开工硬门 = §8：**stage 21/22 均已提交（末笔 f59058d），但「已提交 ≠ Phase A 绿」——开工前实跑 stage 1→22 全部 gate 全绿 + 活体复核（含语句级重定位义务）**。裁决记录：`docs/reviews/v13-control-plane-oracle-r8-2026-09-27.md`；审核轮导出：`prompt-exports/oracle-review-2026-09-27-*.md`（九轮）。批判稿：`docs/reviews/v13-phase-b-plan-critique-2026-09-27.md`（顶部有处置注）。stage 24 无独立 D，但硬依赖 stage 23；stage 23 另一硬前置 = **Phase A 绿**（见 §8）。
> 母计划：`docs/plans/v13-layered-control-roadmap-2026-09-26.md` §2.2/§2.3/§2.4/§3 Phase B（L214–L222）/§4 D7·D16/§5 红线。
> 前序：Phase A 计划现行版（`docs/plans/v13-phase-a-seams-plan-2026-09-26.md`，已经 R6–R12 七轮裁决链演进）；**stage 21 seam 与 stage 22 catalog 均已提交推送（末笔 f59058d）——「Phase A 绿」门在 §8 复核时以实跑确认**；本计划一切「今日锄点」均为写作时点快照，开工前按 §8 重取；R4–R12 裁决记录。
> 硬边界（不重开）：零新表零新列（含物化视图/投影表/概念缓存表，R4）；stage 1–20 SQL 文件字节冻结；events 唯一干预通道；唯一推进函数；R3 链已冻失败模式（终态 `replay`、C4 RAISE、`v13_interruptible` 闭集）；外部 IO 不进事务；gate = 独立可跑脚本退出码 0。索引、只 RAISE 的守卫触发器、开放事件、STABLE/VOLATILE 函数不是新表。

## 0. Goal、交付物与执行索引

**验收读法（路线图 L216）**：动词组闭合 = 观察（含多 id 全量授权）/ 注入 / 应答 / 取消 / 授权 / 交接——注入、应答、取消的动词体已在 stage 17–20，本期补**授权**（F17）、**多目标观察 + 授权后读日志**（F8/F18）、**交接信封**（F29）；F23 已在 Phase A 不重复。

| Stage | 目录 | 交付 | Done when | 依赖 | 规模 |
|---|---|---|---|---|---|
| 23 | `v13/acl/` | `v13_control_operator`、`v13_control_authorized`（+ 通道函数按 §1.1 裁决）；换体/overload `v13_cancel`、`v13_complete`（human 分支） | `test_acl.py` 退出码 0 + 回归 1→22 全绿 + 收尾四件 | **D7 裁决** + Phase A 绿 | 中 |
| 24 | `v13/observe/` | `v13_observe(actor, ids[])`、`v13_session_log(actor, sid[, after_seq])` 两 STABLE 读面 | `test_observe.py` 退出码 0 + 回归 1→23 | stage 23（无独立 D） | 小 |
| 25 | `v13/handoff/` | `handoff_policy` 策略行、`v13_transcript_hash`、`v13_handoff_emit`（体内策略门禁）+ 守卫 + 恰两个部分唯一索引、`v13_extract_handoff` | `test_handoff.py` 退出码 0（含 `SET ROLE v13_route` 真 COMMIT）+ 回归 1→24 全绿 | **D16 裁决（已裁）** + stage 23 | 中 |

全程零新表零新列；`SQL_LOAD_ORDER` 只在末尾追加三项（acl→23、observe→24、handoff→25）；换体/overload 一律以**当时全量加载后的 `pg_get_functiondef` 活体**为底稿（预期 stage 22；Phase A 未落地时对应 stage 也不开工，不存在「底稿=20」的开工路径）。关键文件：三个新 stage 目录各四件 + `v13/load.py` + 台账/矩阵/parity/路线图（见 §9 文件级影响）。

## 1. R8 裁决面（本轮 = 裁决链 R2→R3(a/b/c)→R4→R5→R6(D11 has-event)→R7/R7b(D12 死锁复裁，Phase A 会话) 之后的 **R8**）

**轮名消歧（三次让号后的现状）**：①verdict-R6 = D11 无事件盖章；②verdict-R7/R7b = D12 守卫/写者锁协议死锁复裁（Phase A 会话 stage 21 施工期间消耗）；③残留台账 R6（catalog 缝）已由 R5-D14 吸收。本轮一律写 **Oracle R8（Phase B 动词轮）**，不得简写引歧。

### 1.1 D7 题面与草案（采纳后即 stage 23 规格）

**题面。** 谁能对哪个 `session_id` 调用取消、human 结算、观察、读日志、交接。不加列、不建 link 表；actor 来自服务器不来自工具参数；拒绝不可区分；自答 human 走同一谓词；接入闭集 = {cancel, human complete, observe, session_log, extract_handoff}（**不接** `v13_append_event`/`v13_advance`/`v13_closeout`/`v13_resolve_unknown`/`v13_fork`）。

**真值表（草案；谓词 STABLE、只读 `sessions` + 角色面、不锁行、自身只返布尔不 RAISE）**：

| 类 | 条件 | 结果 |
|---|---|---|
| 行政 | `p_actor IS NULL` 且 `v13_control_operator()` 为真，且 target 行存在 | 真。**不读 `sessions.status`**（终态 cancel 仍走已冻 `replay` 出口——路线图 D7 的「可控任意非终态会话」读作动词有效控制面，不读进谓词；读进谓词会把 R3 冻结的 `replay` 失败模式改成 `session not found`） |
| agent | `p_actor` 非空，actor 行存在，target 行存在，`p_actor <> p_target`，`target.parent_session_id = p_actor` | 真。同样不读 status（终态子会话的日志/交接读取合法） |
| 未解析/拒绝 | 其余一切：actor 空但非 operator、actor 行不存在、target 不存在、自身、孙、祖先、旁系、无关 | 假 |

**operator 带定义（草案）**：`v13_control_operator() RETURNS boolean STABLE` ≡ `EXISTS (SELECT 1 FROM pg_roles WHERE rolname = current_user AND rolsuper)` **或** `pg_has_role(current_user, 'v13_route', 'USAGE')`（`rolsuper` 是列不是函数，可执行 SQL 如上）。用 `USAGE` 不用 `MEMBER`——NOINHERIT 的 `v13_worker` 是 route 成员但不继承其权（preflight §7.2 实证 worker 对 complete 无 EXECUTE），`USAGE` 判定下 worker 不进行政带；`v13_route_login`（route 的 INHERIT 单成员）进带。行政带必须含 route 与超级用户：stage 1–20 冻结测试以 route 身份、不传 actor 调用 cancel/complete，换体后必须原样回绿。

**actor 通道（R8-① 已裁：甲 overload；乙 GUC 不予执行，R8 显式不接受会话级泄漏语义）**：

| 通道 | 形态 | 代价/风险 |
|---|---|---|
| **overload（R8 选定）** | 新 `v13_cancel(p_actor uuid, p_sid uuid)`（唯一正文，活体底稿）+ 旧 `v13_cancel(p_sid)` 换体为薄 wrapper 委托 `actor=NULL`；complete 同理 6 参（actor 前置，`p_result jsonb DEFAULT NULL` 默认参数保持）+ 5 参 wrapper | 六动词 actor 全是参数，无连接状态；正文自身授权（不得只在 wrapper）；6 参正文镜像旧 5 参活体 proacl |
| GUC（已拒存档） | 见 §3.2b（历史方案，不进施工路径） | 乙默认 fail-open（漏设→行政）；会话级泄漏=跨请求冒充——R8 不接受此语义 |

两通道共同规则（不随裁决变）：`p_actor` 非空时**即使当前 principal 是 operator 也只走亲缘**，不自动升行政——operator 要任意目标必须显式 `NULL`；工具 JSON / human result / 事件 payload 里的 `actor` 字段一律不读（gate 用诱饵键证伪）；新函数（observe/log/extract）只吃参数不吃 GUC。

**驱动器合同（写进 stage 23 README；driver 补丁 gitignored 不进里程碑；R8 已拒 GUC——README 不得出现 `v13.control_actor`）**：agent cancel = `v13_cancel(父会话, 子会话)`；agent human complete = 六参且 actor 前置；行政/UI = 旧签名（不传 actor）。

**接入点与锁序**：
- `v13_cancel`（2 参正文）：授权①在 temp 表递归/锁段/`cancel/requested` 发射**之前**；取得树锁并完成 tree-changed 检查后**锁后复验**一次谓词（关 parent_session_id 在检查与锁之间被改的 TOCTOU 窗）；之后树递归/环深度/终态 `replay`/未消费 cancel 幂等/`ready→cancelled` 清扫逐字节保留。授权只对**调用目标**判亲缘：父取消子时孙的 ready effect 沿既有扇出取消（树语义）；actor 直接把孙当 `p_sid` → 谓词假。
- `v13_complete`（6 参正文）：**锁前定位/准入**——dump 在 `:320` 无锁读出 effect 行（**扩列同时取 `session_id, kind`**，列入允许差集）后立即分支：actor 非 NULL 且（无行或 kind≠human）→ 统一文案零写（**不走** dump 的 `unknown effect` 原句）；actor NULL 且无行 → **按带分岔**：operator 真 → dump 原句 `v13: unknown effect %`（旧签名冻结 needle）；operator 假 → 统一文案零写（R8-③：例外只覆盖 operator，无行时无 kind 可判，非 operator 持 EXECUTE 者不得见原句）；actor NULL 且 kind=human → 行政带失败 → 统一文案零写；actor NULL 且 kind≠human → 不调谓词不读通道，字节=dump。该判断在 session/effect 锁（`:321-322`）**之前**，因此也在 stale/replay 返回、cancelled 分支 UPDATE、human 围栏全部之前。**锁后复验**：锁取得后、下一条 plpgsql 语句处重读锁定行的 kind/session_id 重走同一分支表（不得并进 `FOR UPDATE` 同一条 SQL——谓词 STABLE 可能被折叠成锁前结果）。之后 stale/replay、C4 `interaction_ref` fence、one-of 逐字保留。错 ref 仍原 C4 文案（授权在 payload 校验之前）。防 actor API 变通用结算口：actor 非 NULL 且 kind≠human → 统一文案拒绝。
- 现存既有泄漏保持不动（**仅 actor NULL 路径**）：dump 的 `v13: unknown effect` 原句仍在——旧签名冻结 needle；actor 非 NULL 路径不泄（统一文案）。

**拒绝文案（草案）**：agent 路径与「非 operator 且 actor 空」一律 `RAISE 'v13: session not found'`（不插值 uuid、不设自定义 SQLSTATE、谓词自身不 RAISE）；operator 且 actor 空且会话不存在：**保留活体原句 `v13: unknown session %`**（从 dump 原样抄，冻结测试 needle 仍中）；新动词（observe/log/extract）无历史包袱：mutating 面（extract）授权失败统一 `v13: session not found`；读面（observe/log）授权失败**零行不 RAISE**（避免用异常区分「不存在」与「无亲缘」）。

**威胁模型（写进 README）**：工具参数不可信；持有 route/超级用户连接的驱动器可信。谓词是动词里的控制流不是 RLS；route 今天就能直接 `UPDATE effects`，本期不把表权限重划升级。SQL 证明的是：动词不读工具参数；伪造 JSON actor 不改变结果；亲缘按 `parent_session_id` 执法；DB 只验带与亲缘、**不证 actor 的网络来源**（要 DB 独立证明须先裁 principal-to-session 绑定机制——零新列零 link 表约束下不假装已证明，进台账）。

**生产绑定状态（防假绿，同 R5 第四务 🟡 纪律）**：SQL gate 绿只证明「调用方传了 actor 时合同成立」；仓库内无可提交 driver 会走 agent 路径（`demo_v13/` gitignored）。README 两格：谓词+换体+`test_acl.py` 绿 = **合同已证明**；仓库内驱动器在 agent 路径传 actor = **未交付**——Phase B 验收句不得写「F17 已在生产路径生效」。

**替代项（只供裁决否决草案；否决则停工改计划，实施者不得当场选）**：

| 编号 | 替代 | 草案为何不选 |
|---|---|---|
| D7-alt-strong | operator 只含 rolsuper+新建 `v13_operator`；route 无 actor 即拒 | 失败关闭更好，但打红全部「以 route 身份不传 actor」的冻结测试（文件字节冻结不可改） |
| D7-alt-status | 谓词拒绝终态 | 把 R3 已冻的终态 cancel `replay` 改成 `session not found`，且阻断终态子会话的日志/交接读取 |
| D7-alt-guc | GUC 通道为草案 | **R8 已拒**（会话级泄漏语义不被接受）；§3.2b 仅作历史存档 |
| D7-alt-self-read | 读面允许看自身、写面不允许 | 路线图写四动词同一谓词；采纳则另增读谓词，observe/log 规格作废重写 |
| D7-alt-definer | cancel/complete 改 SECURITY DEFINER 收紧表权限 | 改 prosecdef 且体内 `current_user` 变属主，operator 带判定失真 |
| D7-alt-band-literal | 行政带 = 字面集 `{v13_route, v13_route_login, rolsuper}` | 与 `pg_has_role(USAGE)` 等效但成冻结名单；新登录角色要改代码。若 R8 偏爱字面集，机械替换即可 |

### 1.2 D16 题面与草案（采纳后即 stage 25 规格）

**题面。** 信封四键的取值语义、`transcript_hash` 材料、`up_to_seq` 时点与值域、重复 extract 幂等性、`handoff_policy` 键集、写口架构，以及 **R4:23「生命周期写面 = 开放事件 + 唯一折叠函数」× 路线图 §2.4「交接无读面函数，收据即事件」的张力**。

**R4 张力裁定建议（草案）**：交接是**不可变追加收据**，不是可翻转的当前态（对比 L32 stop/resume——其折叠函数留在 stage 29 `v13_goal_lifecycle`）。R8 须明文把 F29 记录为对 R4 生命周期条款的**非生命周期收据澄清**；唯一承诺函数 = `v13_transcript_hash(sid, up_to_seq)`（守卫与写者同调、advance 永不调用）；不新增 `v13_latest_handoff`/`v13_handoff_state`/全局 VIEW。裁决若要公开 fold，必须在正文**点名函数名**并同轮改路线图 §2.4——没点名就不加。

**信封（键集恰四键，roadmap D16 字面）**：

| 键 | 取值（草案） |
|---|---|
| `schema_version` | JSON 数字 1 |
| `delivery_id` | 本次交付 `gen_random_uuid()` 小写文本（不是 effect id、不由 hash 派生） |
| `transcript_hash` | `v13_transcript_hash(p_sid, p_up_to_seq)` 的 64 位小写 hex |
| `up_to_seq` | JSON 整数 ≥ 0，必须是已存在非 handoff 事件的 seq（R8-⑤ 已裁：无 −1；`v13_transcript_hash` 亦拒负 cutoff；`v13_session_log` 的 `p_after_seq=-1` 从头语义独立合法不受影响） |

事件写在**目标会话**上；`source_effect_id` NULL；不写父会话、不 `INSERT` 子会话、不调 `v13_fork`、不写 `artifacts`、不产 XML、不水合文件、不升第二 transcript（R1.4）。

**窗口与材料（R8-⑥ 已裁：最小四元组；codex 增折 event_id/turn_no 已否——改字段集须另裁升版本 v1→v2）**：hash 材料是该会话 `seq <= up_to_seq` 且 **`type <> 'control/handoff'`** 的全部事件（收据自身排除，防自激）；**规范字节式（函数与 gate 各写一次；gate 禁靠调用 `v13_transcript_hash` 自己凑期望值）**：

```sql
encode(digest(
  jsonb_build_array(
    'v1', p_sid::text, to_jsonb(p_up_to_seq),
    coalesce(jsonb_agg(jsonb_build_array(
      e.seq, e.type, e.payload_hash,
      coalesce(e.source_effect_id::text, '')) ORDER BY e.seq),
      '[]'::jsonb)
  )::text,
  'sha256'), 'hex')
-- 聚合范围：session_id = p_sid AND seq <= p_up_to_seq AND type <> 'control/handoff'
```

不含 `at`/`event_id`/`turn_no`/payload 原文/effects/策略/probe——不复用 `v13_state_hash`（那份折叠 effects/route policy/probe）。`payload_hash` 列不存在或 `events` 可 UPDATE/DELETE payload → 停工报事实（§2 探针），禁改折 `payload::text`。未知会话：`v13_transcript_hash` RAISE 活体形 `v13: unknown session %`（非授权边界；空前缀不由本函数写收据，`handoff empty` 只在 extract）。`p_up_to_seq` NULL → 持锁后**最新非 handoff 事件的 seq**（无 → `v13: handoff empty` 零写）；非 NULL 必须是已存在的非 handoff 事件的 seq；大于 max、负数、指向 handoff 收据、空会话传 0 → `v13: handoff watermark`，零写。四键无 `from_seq`，窗口必须**整段前缀**（与源合同「最近 N 条」不同是四键约束下的换体，进台账）。写入 canonical：`up_to_seq` 用 `to_jsonb(v_seq::bigint)` 使 `payload->>'up_to_seq'` 与 `v_seq::text` 逐字相等。

**幂等性（R8 确认用户拍板：身份去重）**：收据身份 = `(session_id, up_to_seq, transcript_hash)`；同身份重放**返回原 payload、零新事件**；新的非 handoff 事件出现后 NULL cutoff 得新身份、追加新收据；显式旧 cutoff 永远返回旧收据（依赖前缀不可变——§2 探针钉 events payload 不可 UPDATE/DELETE）。**锁内回读必须用与索引/守卫同一套 canonical 文本表达式**（`payload->>'up_to_seq'`、`payload->>'transcript_hash'`），禁 `::bigint` 数值比较或另一套规范化——回读写错时唯一索引命中裸 `23505`，**定义为实现 bug 不是可接受竞态**；extract 体内无 EXCEPTION，**禁止用 EXCEPTION 把 `23505` 收成「返回旧收据」**。配套**恰两个**部分唯一索引（固定，不再可选）：`ux_events_handoff_delivery ON events((payload->>'delivery_id')) WHERE type='control/handoff'`（全局 delivery 唯一）+ `ux_events_handoff_snapshot ON events(session_id, (payload->>'up_to_seq'), (payload->>'transcript_hash')) WHERE type='control/handoff'`（快照身份唯一）。「每次新收据」grok 案 = **已拒历史项**，无施工效力。

**`handoff_policy` 策略行（草案）**：`v13_policies` 一行 `('handoff_policy', 1, '{"schema_version":1,"enabled":true}', true)`，只消费 `enabled`。缺行/键集不对/类型错 → `v13: handoff policy`（**不借道 `v13_policy()`**——它的缺行文案是 `v13: no active policy row for % (seed lost?)` 且把策略名泄进错误；extract 直读 `v13_policies` 用自己的文案）；多条 active 在 `ux_v13_policies_one_active` 建好后不可达（防御性保留判定）；`enabled=false` → `v13: handoff disabled`；任一失败在 emit 之前、零写。**不设** `max_transcript_items`/`max_tool_args_characters`/`max_events`（本 stage 不产 XML 不截断——截断参数会制造第二份正文；hash 是 O(E) 重算，v13 量级无缓存对象，规模真到需摘要表须先答 R4 例外四问）。替代键集（已被用户拍板否决，仅供 R8 复议）：grok `{schema_version,enabled,allow_empty:false,max_events:1000}` vs fable `{...,max_transcript_items:200,max_tool_args_characters:2000,allow_file_contents:false}`。

**写口架构（R8-④ 已裁：DEFINER 单写者）**：`v13_handoff_emit(p_sid, p_payload)` SECURITY DEFINER、`OWNER TO v13_handoff_owner`（新角色，属性恰 `NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS` 且无可 `SET ROLE` 到它的成员关系；已存在则安装时断言属性与 membership，不符 RAISE `v13: handoff baseline`，禁止复用脏角色）。**emit 体内策略门禁**：`v13_append_event` 之前用与 extract 相同规则读 `v13_policies`（同文案 `v13: handoff policy`/`v13: handoff disabled`，零写）——只在 extract 查策略则持 EXECUTE 的 route 可在 `enabled=false` 时直写收据。自举 GRANT（**闭包里的 digest 只授、只断言 `to_regprocedure('digest(text,text)')`——`digest(bytea,text)` 不授不断言、裸名 digest 禁用（42725）、任一 to_regprocedure 为 NULL 则停工禁改授 bytea 重载；安装后 DO 对闭包每个 OID 用 `aclexplode(coalesce(proacl, acldefault('f', proowner)))` 证明存在 `grantee='v13_handoff_owner' ∧ privilege_type='EXECUTE'`，`has_function_privilege` 不能单独当通过条件**）：`USAGE ON SCHEMA public`（另 CREATE 见 §5.2 步 2） + `SELECT,UPDATE ON sessions` + `SELECT,INSERT ON events` + `SELECT ON effects` + `SELECT ON v13_policies` + EXECUTE **精确签名**：`v13_append_event(uuid,uuid,text,jsonb,uuid)`/`v13_assert_unknown_wall(uuid)`/`v13_json_keys(jsonb)`/`v13_json_int_ok(jsonb,int)`/`v13_canonical_uuid(text)`/`v13_transcript_hash(uuid,bigint)`（步 5 后补授）/`digest(text,text)`/`pg_catalog.gen_random_uuid()`——F19 教训：属主前置授予放任何 emit 测试之前；**schema-qual 硬断言**：emit/hash/守卫/extract 正文统一 `public.*`/`pg_catalog.*` 限定名，源码 gate 拒未限定的业务表/helper/digest/UUID 调用。**点火事实**：`v13_append_event` 的 UPDATE 恒给 `sessions.status` 赋值（即使值不变）→ `UPDATE OF status` 的 unknown wall 触发器对每条 `control/handoff` 点火（点火≠改值）；DEFINER 成功路径依赖属主 wall 闭包，缺权失败模式是提交期 42501 而非 `v13: handoff writer`；带 `blocked_unknown` 会话上若 wall 对该赋值 RAISE → 停工报事实（§2 探针），禁改 stage 1–20 wall。**属主生命周期**：只由 stage 25 创建；GRANT 以安装后 DO 为闭包；未来若另裁废 DEFINER，角色保留不用不 DROP（集群级对象跨库存在）。**route→emit 直调处置（R8-④ 条件 3）**：`v13_handoff_emit`/`v13_transcript_hash` 是**受信 route 内部 helper 不是 actor 授权入口**——D7 的 actor 合同只承诺 `v13_extract_handoff`；route 直调 emit 在受信威胁模型内可接受，行为已定义（同身份 → 快照唯一索引拒；新身份 → 合法新收据），记台账一行；不授 PUBLIC/worker/recall/resolve。守卫 `v13_handoff_event_guard` **INVOKER** + BEFORE INSERT `WHEN NEW.type='control/handoff'`，只 RAISE 不改行，检查序：`current_user ≠ v13_handoff_owner → 'v13: handoff writer'`；**`NEW.source_effect_id IS NOT NULL → RAISE 'v13: handoff source'`（收据无 effect 源——信封合同要求 NULL，非空即拒）**；键集恰四键（jsonb 不保序，禁「键序错」负例）；`schema_version` JSON 整数 1；`delivery_id` canonical uuid；`transcript_hash` `^[0-9a-f]{64}$`；`up_to_seq` ≥ 0 整数且等于本会话某行 `type <> 'control/handoff'` 的 seq（存在性谓词，禁缩成 `0 ≤ n ≤ max(seq)` 数值区间；失败 → `v13: handoff watermark`）；`v13_transcript_hash` 重算逐字相等 → `v13: handoff hash`。`v13_extract_handoff(p_actor, p_sid, p_up_to_seq bigint DEFAULT NULL) RETURNS jsonb` **INVOKER VOLATILE**（保持 D7 的 current_user），**控制流（R8 三轮：回读先于策略——同身份重放不因 policy 禁用/畸形而断，幂等合同优先）**：授权（未锁未写先判）→ `sessions FOR UPDATE` → **锁后复验授权** → 解析 watermark → 计算 hash → **同身份回读：存在则立即返回原 payload（零新事件、`next_seq` 不变，不查策略）**→ 读策略（缺行/形状错 → `v13: handoff policy`；disabled → `v13: handoff disabled`；只管新写入）→ `gen_random_uuid` → `v13_handoff_emit`（emit 内策略门禁管所有新写入与 route 直调）→ 返回四键 jsonb；体内无 EXCEPTION。codex 带案（无 DEFINER/角色、守卫查控制带、历史行按守卫核对）**已拒**；历史行处置维持「有任何 `control/handoff` 行即 RAISE `v13: handoff baseline` 列 session/seq，不回填不修史」。

**`state_hash` 方向**：`control/handoff` 不在排除名单（preflight §7.1 实证名单仅三 `session/*`）→ 首写收据 `h_after <> h_before`；**幂等重放前后 `state_hash` 相同**（零新事件）；不 `CREATE OR REPLACE v13_state_hash`、不加排除名单（加了会把方向断言测绿）。若开工探针发现活体变白名单且不含该 type → 停工报事实。

**边界**：extract 不改 `sessions.status`/`turn_no`；终态会话允许交接（日志还在）；`blocked_unknown` 墙不动；`v13_session_log`（stage 24）可自然读回 `control/handoff` 行。

### 1.3 stage 24 定形（无独立 D，本文件定死；R8 已定形）

**`v13_observe(p_actor uuid, p_ids uuid[])`** STABLE INVOKER，返回列序固定：
`ordinal int, session_id uuid, parent_session_id uuid, status text, spawn_kind text, is_terminal bool, turn_no int, last_event_seq bigint, last_event_type text, pending_human bool, cancel_pending bool`
- `is_terminal` := `status IN ('completed','failed','cancelled')`（闭集从活体 `v_goal_tree` 抄，不一致则停，禁另造第三套终态字）；`last_event_seq` 无事件 −1、`last_event_type` 相应 NULL；`pending_human`/`cancel_pending` 由活体函数适配（§2 探针表），不重写其 SQL。全部新函数（含 authorized/transcript_hash/extract/守卫）一律 `SET search_path = pg_catalog, public`。
- 控制流必须 plpgsql 多段，**禁一条带 join 的 SQL 函数**（规划器可能先碰 events）：①参数段——NULL 数组/空数组 → return 零行；数组含 NULL 元素 → `v13: observe id`；重复 → `v13: observe duplicate`（参数合同错误发生在授权前，文案不含任何会话存在性）；②授权段——按输入序逐 id 调谓词，任一假 → return 零行（**不 RAISE**），此段**不查 events 也不读 `parent_session_id`（亲缘只活在谓词）**；③快照段——才读 sessions（含 `parent_session_id`/`spawn_kind` 作为**已授权行的输出列**）与 events 末 seq/type 并调两个布尔适配。
- 不设数组长度上限（驱动器可信；魔法上限拒绝合法大批观察）；无 waiter/`pg_sleep`/`LISTEN`；单元素数组与多元素同形；输出序 = 输入序（`ordinal` 从 1 起）。「第一个 interesting 胜」由驱动器在返回行上选（看 status/pending/terminal/watermark）再重入——这是 poll 不是队列；并发新事件可能在下一次调用才可见（STABLE 单调用快照）。快照段调用的 pending/cancel 适配函数若对已授权会话 RAISE，错误原样传播（调用方已获授权可见该会话）；它们不得出现在授权循环内。

**`v13_session_log(p_actor uuid, p_sid uuid, p_after_seq bigint DEFAULT NULL)`** STABLE INVOKER，返回 `seq bigint, event_id uuid, type text, turn_no int, payload jsonb, payload_hash text, source_effect_id uuid, at timestamptz`，seq 升序。**游标形状检查在谓词之前**（`< -1` → `v13: session log cursor`；参数合同不依赖会话存在，同 observe 的重复/NULL 元素位——放谓词后会制造「未授权+非法游标零行 vs 已授权+非法游标 RAISE」的存在性神谕）；NULL/−1 从头。谓词假 → **零行不 RAISE**（与未授权/未知同形，不以行数区分存在性）。**不 join effects**（recall 有无 effects SELECT 不影响本函数）；默认第三参使路线图的两参调用成立。

**GRANT**：两函数 `REVOKE PUBLIC` → 只 GRANT `v13_route`（route_login 经成员获得）。**不授 recall**（避免把「先授权」做成人人可执行入口；recall 本有 events 表级 SELECT，不收回、README 不宣称已被谓词封死）；不授 worker/resolve/spawn_owner。

### 1.4 裁决纪律（R8 已裁，2026-09-27）

六题全部落裁（记录：`docs/reviews/v13-control-plane-oracle-r8-2026-09-27.md`）：①通道=**甲 overload**（乙 GUC 拒，会话级泄漏语义不被接受）；②C15 采纳状态中立（否决 D7-alt-status）；③例外成立（operator+空 actor+缺会话保留活体 needle，含 complete 的 `unknown effect` 孪生例外）；④写口=**DEFINER 单写者**（codex 带案拒；route→emit 直调=受信内部 helper，行为已定义）；⑤空前缀=**无 −1**（空会话 NULL → `v13: handoff empty` 零写）；⑥hash 字段集=**最小四元组 v1**（codex 增折 event_id/turn_no 否，改须另裁升 v2）。裁决与计划冲突处以裁决为准；不一致处已按 r2–r9 逐轮折入（九轮审核，终轮三通道 APPROVE）。裁决合并前 `v13/acl|observe|handoff` 目录不应出现。

## 2. 探针证据底座（开工当天重取，不从本文件回贴函数体）

底稿 = **当时** `files_through` 最后一 stage（预期 22）全量加载库的 `pg_get_functiondef`。今日锚（stage 20 活体，preflight 已存档）仅供理解：

| 对象 | 今日锚 | 实施时要确认的性质 |
|---|---|---|
| `v13_cancel(uuid)` | fanout:153（temp 树/环深度 64/终态 `replay`/`cancel/requested`/`ready→cancelled`） | 标记串仍在（`v13: goal tree cycle/depth`、`v13: cancel tree changed`、`RETURN 'replay'`）；identity 仍单 uuid；INVOKER |
| `v13_complete(uuid,int,bigint,text,jsonb)` | fanout:305（stale/replay 前置→cancelled 阶梯→human C4 fence/one-of→写） | 标记串仍在（`v13: unknown effect`、`v13: human channel one-of`、`v13: human interaction_ref mismatch`、`v13: cancel not pending`）；**无会把异常收成 unknown/replay/stale 的 EXCEPTION**；INVOKER；proacl = {postgres, v13_route, v13_spawn_owner}（preflight §7.2） |
| `v13_append_event(uuid,uuid,text,jsonb,uuid)` | schema:62-91 | 签名不变；本期不换体 |
| `v13_state_hash(uuid)` | control:362 起（排除名单 :376-390） | 仍是排除名单（名单仅三 `session/*`）；本期不换体 |
| `sessions.parent_session_id` | schema | 列仍在、类型 uuid |
| `v13_pending_human` / advance 引用的 cancel 谓词 | control:121（今日即 boolean）/ 活体 advance（今日 `v13_unconsumed_cancel`） | 见适配表（uuid 分支留作停工探针，非今日事实） |
| `v13_canonical_uuid`/`v13_json_keys`/`v13_json_int_ok` | control | 见适配表 |
| 活体 advance 对未知事件 type 的行为 | 今日只读 `llm/message`\|`tool/result`（loop/advance.sql:126），开放 type 被滤掉不 RAISE | 若活体对未知 type RAISE → 停（防未来封闭词表无声打红 advance） |
| 带 `blocked_unknown` 的会话上 owner 经 emit 写合法收据 | wall 对 status 赋值点火（见 §1.2 点火事实） | 若 wall RAISE → 停工报事实，禁改 stage 1–20 wall |
| `events` 的 payload/payload_hash 不可变性 | append-only 触发器 + 列无 UPDATE 路径 | 若 UPDATE/DELETE payload 能成功 → 停（身份去重的「旧 cutoff 永远旧收据」依赖前缀不可变） |
| `sessions.spawn_kind`/`turn_no` 列存在（observe 输出列） | v_goal_tree 已返回 spawn_kind | 列不在 → 停或删列，不造第三套 |
| spawn_owner 的 EXECUTE 来源 | preflight §7.2（proacl={postgres,v13_route,v13_spawn_owner}；来源=spawn.sql:1735 GRANT ALL FUNCTIONS + OR REPLACE 保留，非 fanout GRANT 块） | cancel 大概率同有，以当日 proacl 为准，不预写死 |
| `v13_json_keys` 返回序 | control:102-106（ORDER BY k） | 已定字母序——探针复核而非预期 |
| Phase A 产物（已落，末笔 f59058d） | stage 21/22 | `v13_record_worktree_released`/`v13_worktree_state`/catalog 换体均已提交——complete 底稿含 D12 写者调用，以当日 dump 为准（R9–R12 裁决链已改 catalog 形状） |

**证伪即停（不发明兜底；下列之外走各节授权分支）**：
1. cancel/complete 的 identity arguments、prosecdef、provolatile 与上表不符。
2. complete 出现把 `v13: session not found` 或 `23505` 收成 `stale/replay/unknown` 的 EXCEPTION 处理器。
3. `pg_has_role('v13_worker','v13_route','USAGE')` 在 `SET ROLE v13_worker` 下为真（行政带被 worker 污染——若真，D7-alt-band-literal 字面集成为唯一可行带定义，回 R8 确认）。
4. `parent_session_id` 列缺失/改名。
5. 已存在名为 `v13_control_authorized`/`v13_control_operator`/`v13_observe`/`v13_session_log`/`v13_extract_handoff`/`v13_transcript_hash`/`v13_handoff_emit` 的函数或 overload。
6. 已存在 `type='control/handoff'` 历史行（开放词表，stage 25 前可能已有手工行）——**有任何历史行就 RAISE `v13: handoff baseline` 列出 session/seq，不回填不修史**（R8-④ 已选 DEFINER，无「按守卫核对放行」分支）。
7. `v13_policies` 冻结触发器拒绝 `handoff_policy` INSERT → 停，原样记 RAISE，不改 stage 1–20 触发器。
8. **spawn_owner 冻结依赖 grep**：全仓检索 stage 1–20 **测试文件**里 `SET ROLE v13_spawn_owner` 后跟 `v13_cancel(` 或 human `v13_complete(` 的用例——判定=「成功期望」（历代死体文件里的同名调用不算）；若存在，stage 23 停工记台账（band 加 spawn_owner 须回 R8；不得顺手加）。
9. 加载序末尾不是已绿的 catalog（22），又没有台账书面弃权 → 不追加 acl（防把 23 编成 21）。
10. grep `len(SQL_LOAD_ORDER)` / `== 20` 类长度断言（J3/X1 同款）：发现写死 `== 20` 分路处置——断言在可改的公共 loader/helper（v13/load.py 自身或后 stage 文件）→ 按既有 X1 句式放宽（`>= 16` 精神）；在**冻结的 stage 1–20 测试文件**内 → 停并请明确例外，不在 Phase B 顺手改历史测试。
11. 带 `blocked_unknown` 的会话上 owner 经 emit 写合法收据：wall 对 status 赋值点火（§1.2 点火事实），若 RAISE → 停工报事实，禁改 stage 1–20 wall。
12. `events` 的 payload/payload_hash 不可变性：UPDATE/DELETE payload 若能成功 → 停（身份去重的「旧 cutoff 永远旧收据」依赖前缀不可变）。

**允许的适配（不是证伪，按探针落笔并写进该 stage README）**：

| 探针 | 适配 |
|---|---|
| `v13_pending_human` 返回 boolean | observe 直接用 |
| 返回 uuid/一行 | `pending_human := (调用结果 IS NOT NULL)` |
| 不存在或类型无法作存在性判断 | 停，报 `pg_get_function_result`，不重写 human 查询 |
| 活体 advance 引用 `v13_unconsumed_cancel` 或 `v13_cancel_pending` | observe 的 `cancel_pending` 用 advance 源码里出现的那个；两个都在用 `v13_unconsumed_cancel`；适配规则同 pending |
| `v13_json_keys` 对四键对象的返回序 | 守卫用这次探针的序（预期字母序 `delivery_id, schema_version, transcript_hash, up_to_seq`） |
| `v13_json_int_ok('-1'::jsonb, -1)` 为假 | `schema_version` 仍用该函数；`up_to_seq` 本地判断（**R8 四轮 canonical 规则，存储后 jsonb 表示上判**）：值转 numeric → `numeric = trunc(numeric)` → `0 ≤ numeric ≤ 9223372036854775807` → 值的 jsonb 文本 = `numeric::bigint::text` → 才允许转 bigint。**`1.0` 存储后可观察（jsonb 保留小数 scale，`1.0::jsonb::text='1.0'≠'1'`）——是负例不是归一化例外（夹具见 §5.3）**；指数拼写若已归一成 canonical 文本则按存储值放行；超大整数不得泄 `numeric out of range`（22003） |
| `v13_canonical_uuid(gen_random_uuid()::text)` 为假 | 停，不自写第二套 uuid 正则 |
| 活体 complete 含 `v13_record_worktree_released` | 6 参正文保留恰这一次调用（Phase A 产物） |
| 不含 | 不在 stage 23 补 D12 |
| 旧 5 参 complete 的实际 proacl | 6 参正文按此镜像授予（+谓词），wrapper 不 42501 |

探针放各 stage `test_*.py` 开头或一次性 psql，失败即非 0 退出，不进换体段。

## 3. Stage 23 `v13/acl/`

### 3.1 实施前置（写 SQL 之前）

1. **停工闸**：R8-D7 已裁 + Phase A 绿（§8 复核走完）+ 加载序以 catalog 结尾。
2. 当日 dump：`v13_cancel`、`v13_complete`（+§2 全表探针）。
3. §2 证伪清单逐条跑；spawn_owner grep（第 8 条）必做。

### 3.2 SQL 语句序（`v13/acl/v13_acl.sql`，单事务；R8-① 已选本 overload 形态——§3.2b 为已拒存档不执行）

1. DO 安装前断言：证伪清单的安装期子集（列在、旧签名各恰一个、新名/overload 不存在、worker USAGE 为假、cancel/complete 标记串还在）。失败 RAISE `v13: acl baseline`。
2. `CREATE FUNCTION v13_control_operator() RETURNS boolean LANGUAGE plpgsql STABLE SET search_path=pg_catalog,public`——体只查 `pg_roles`/`pg_has_role`。
3. `CREATE FUNCTION v13_control_authorized(p_actor uuid, p_target uuid) RETURNS boolean` 同规格——真值表唯一家；一次查询取 target 的 `parent_session_id`（无行即假），actor 非空再查 actor 行存在；不读 status、不 `current_setting`、不锁行。
4. `CREATE FUNCTION v13_cancel(p_actor uuid, p_sid uuid) RETURNS text`——**唯一取消正文**，底稿 = dump；文本差只有：DECLARE 增 `v_actor`；函数最前加准入段（actor 非空 → 谓词假 RAISE 统一文案；actor 空 → operator 假 RAISE 统一文案、target 缺失保留 dump 的 `unknown session` 原句）；树锁 + tree-changed 检查后**锁后复验**谓词（actor 非空才需要）；其后字节 = dump。
5. `CREATE OR REPLACE v13_cancel(p_sid uuid) RETURNS text`——薄 wrapper：`RETURN v13_cancel(NULL::uuid, p_sid)`。不保留第二份递归实现。
6. `CREATE FUNCTION v13_complete(p_actor uuid, p_effect uuid, p_attempt int, p_fence bigint, p_status text, p_result jsonb DEFAULT NULL) RETURNS text`——**唯一结算正文**，底稿 = dump；文本差只有四段：①**锁前定位查询扩列**——dump 初始无锁 SELECT 从单列 `session_id` 扩为同时取 `session_id, kind`（否则锁前分支无法判 kind；列入允许差集）；②锁前定位/准入分支（dump 无锁读出后立即，按 §1.1 分支表：actor 非 NULL 无行或 kind≠human → 统一文案；**actor NULL 无行 → operator 真 → dump 原句、operator 假 → 统一文案**；actor NULL kind=human 带败 → 统一文案；actor NULL kind≠human 字节=dump）；③`unknown effect` 段的 actor/带分支（不改原句本身）；④锁取得后下一条语句的锁后复验（重读锁定行的 kind/session_id 重走分支表；不得并进 `FOR UPDATE` 同一条 SQL）。全部位于 stale/replay 之前、任何写之前。D12 调用（若 dump 有）保持位置与异常语义；其余字节 = dump。
7. `CREATE OR REPLACE v13_complete(p_effect uuid, p_attempt int, p_fence bigint, p_status text, p_result jsonb DEFAULT NULL)` 五参 wrapper：委托 `actor=NULL`；**默认参数逐字保持**（`p_result jsonb DEFAULT NULL`——identity arguments 不含默认值，漏写则既有四实参调用变函数不存在=API 回归）；wrapper 体为纯委托（只含 `RETURN v13_complete(NULL::uuid, ...)`）。比对而不仅 identity：`pg_get_function_arguments`（含默认）、`pronargdefaults`、provolatile/prosecdef/proconfig/parallel/strict 逐项与活体相同。
8. `REVOKE EXECUTE ... FROM PUBLIC` 只对新函数（operator/authorized/2 参 cancel/6 参 complete）。**禁对换体函数 `REVOKE ALL`**（OR REPLACE 保留原 ACL）。
9. GRANT：operator/authorized/2 参 cancel/6 参 complete → `v13_route` + **旧签名活体 proacl 的其他真实调用方**（预期 `v13_spawn_owner`，以当日 proacl 为准——缺它则其调用 wrapper 时 42501 而非统一拒绝，且 stage 17–20 冻结正例会红）；不授 worker/resolve/recall/PUBLIC。
10. `COMMENT ON FUNCTION` 各一行。无表/视图/触发器/GUC 数据库级定义。

步骤 4+5、6+7+8+9 各自必须在同一安装事务内完成（不留无正文或无权限的窗口）。`v13/acl/setup_db.py`（DB=`agent_v13_acl`，照 stage 20 惯例含扩展探针）+ `test_acl.py` + `README.md`。

### 3.2b 已拒方案存档：GUC 通道（R8-① 裁定 overload 当选；乙的会话级泄漏语义被显式不接受）

本段不进施工路径，仅供历史对照与未来复议时参考。

1. `CREATE FUNCTION v13_control_actor() RETURNS uuid`，STABLE INVOKER，`search_path=pg_catalog,public`：`current_setting('v13.control_actor', true)` 空白/未设 → NULL；否则 `btrim` 后交 `v13_canonical_uuid`——非法 → RAISE `v13: session not found`（不暴露 `invalid input syntax`）；合法 → `::uuid`。
2. `CREATE OR REPLACE v13_cancel(p_sid uuid)`（旧签名，无 overload）：dump 底稿 + 函数最前 `v_actor := v13_control_actor()` + §1.1 准入（行政路径保留 `unknown session` 原句）+ 树锁后锁内复验。文本差只有这两段。
3. `CREATE OR REPLACE v13_complete(五参)`（旧签名，无 overload）：dump 底稿 + §3.2 第 6 步同款三段差（锁前定位/准入、`unknown effect` 段 actor 分支、锁后复验）；`v_actor := v13_control_actor()` 只在 human 分支读——**非 human 不读 GUC**（非法 GUC + 非 human complete 仍成功，正例钉住）。
4. `REVOKE EXECUTE ... FROM PUBLIC` 只对三新函数（operator/actor/authorized）；cancel/complete 保原 ACL。
5. GRANT 三新函数 → `v13_route`（+镜像 spawn_owner 按旧 proacl——乙案无新 overload 可授）。
6. gate 差异：agent 用例全部 `set_config('v13.control_actor', <sid>::text, true)`（SET LOCAL 形态）；新增两条——非法 GUC + 非 human complete 仍成功（GUC 不被读）；同连接第二事务不重设 GUC → 行为按事务局部语义（SET LOCAL 泄漏检测）。驱动器合同：agent 路径同事务 `SET LOCAL`，行政路径不设；README 记会话级泄漏后果（见 §1.1 乙行）。

### 3.3 状态流（要点）

- 行政：route/超户、不传 actor → 与今日逐字节同行为（终态 `replay`、非终态 `accepted` 扇出）。
- agent：父会话 actor + 直接子 → 通过；自身/孙/无关/不存在/actor 不存在 → 统一文案异常、零写（事务终止，事件数与 effect 状态回调用前）。
- human：授权在 C4/one-of 之前——未授权者看不到 `human interaction_ref mismatch`；通过后错 ref 仍走原 C4 文案。
- 并发：谓词无锁；TOCTOU 由锁后复验关闭；cancel 后半锁序保持 dump（先按 session_id 锁树再按 effect_id 锁 effect）。
- GUC 通道：R8 未选，不执行（§3.2b 仅历史存档）；若未来另裁启用，驱动器合同强制 `SET LOCAL` 且会话级泄漏语义须另行显式接受。

### 3.4 Gate（`uv run python v13/acl/test_acl.py`，退出码 0）

夹具：父 P、子 C（parent=P）、孙 G（parent=C）均 ready；无关 U；human effect 在指定会话（claimed、request 含 `interaction_ref`、fence/attempt 取自行内）；成功应答 payload 抄 stage 17/19 已绿用例。

**谓词矩阵**：route+NULL+存在目标真；route+父 actor+直接子真；self/孙/兄弟/无关/未知 target/未知 actor 假；直接子已终态仍真（状态中立）；resolve/recall/worker/PUBLIC 无 EXECUTE（42501）；超户维护路径真；`pg_get_functiondef(authorized)` 不读 JSON/effect request/event payload。**operator 传了 actor 也不升行政（R8 增）**：`SET ROLE v13_route` 调 2 参 cancel、p_actor 为无关已存在会话（或自身）→ `v13: session not found` 零写；超户调 6 参 complete、actor 非空且目标为 tool effect → 同文案零 effect_done。**overload 解析与默认参数**：既有 1 参 cancel / 5 参 complete 调用仍解析旧签名（6 参不 shadow 5 参）；既有 4 实参 complete 调用（靠 p_result 默认）仍成功。

**cancel 接入**：直接父 2 参调用 accepted、`cancel/requested` 恰一条、孙 ready effect 沿扇出 cancelled（授权只判调用目标）；`SET ROLE v13_route` 旧 1 参调用保持 stage 22 正例（行政）；终态直接子仍 `replay`；同一未消费 cancel 不写第二条；工具参数伪 actor 不改变绑定参数。

**human complete 接入**：父 actor 成功应答子的 human；self/祖/无关/未知 actor 同一文案、effect 仍 claimed、零 `effect_done`/`human/responded`；actor-aware overload 对非 human 拒绝且零写（**负例加严：actor 路径对 tool effect 调 complete(cancelled) → 统一文案零写，不得先写 effect_done**——钉准入在 :348 写之前非 :355 围栏处）；operator 经旧 5 参仍能完成 human；错 `interaction_ref` 仍原 C4 文案且零写（授权通过后）；stale/replay/fence 行为不变（但**未授权者看不到 stale/replay**——负例：未授权 + 已终态 effect → 统一文案非 replay）；Phase A 写者（若在）经旧 5 参非 human complete 仍触发既有事件（证 6 参正文未回滚 D12）。

**负例（消息逐字全等，跨用例不含被测 uuid；`fails_with`+SAVEPOINT）**：self/孙/U/不存在 uuid/不存在 actor/空 actor 非 operator 六类文案全等；**6 参、actor=已存在父会话、effect id 不存在 → 统一文案，SQLERRM 不含 `unknown effect` 不含该 uuid，零写**（钉锁前分支不走原句）；**`SET ROLE v13_spawn_owner` + 旧 5 参 + 不存在 effect → 统一文案零写**（非 operator 持 EXECUTE 者不得见原句；spawn_owner 不存在时换任一当日 proacl 内非 operator 角色，均无则改源码断言）；超户无 actor 未知 sid → needle 仍是活体 `unknown session`（不是 session not found）；human 自答（actor=该 effect 会话）+ payload 另放伪造 `actor` 键 → 同为统一文案（授权在键集检查前）；未授权对已终态 human 再 complete → 统一文案（不是 replay/stale）；父直接调孙 → G 零写；`SET ROLE v13_worker` → 对 operator/authorized 两函数 `has_function_privilege(...) = 假`、直调 42501（worker 是 NOINHERIT 成员不带来 EXECUTE——「worker 不进行政带」的否定证据以 `pg_has_role('v13_worker','v13_route','USAGE') = 假` 为准，§2 证伪 3 同源）；cancel/complete 同 42501；recall 仍不能 SELECT effects。

**非 human 不误套谓词（R8 二轮；三轮夹具加严）**：对照夹具是**超户旧 5 参能够写完的 tool effect**（dump 成功词 + `effect_done`）；当日 proacl 内存在非 operator 且持 complete EXECUTE 的角色（预期 `v13_spawn_owner`）→ 该角色同一夹具的返回词与 `effect_done` 条数与超户相同；**双边同为 `stale`/`replay` 不算通过**（误套谓词只在超户会写完、spawn_owner 会被收成 `session not found` 时暴露）；该角色对该夹具 42501 时改源码断言（`actor IS NULL AND kind <> 'human'` 的锁前与锁后都不调 `v13_control_authorized`/`v13_control_operator`）并记台账。

**并发（COMMIT 日程，cancel 与 complete 各一套；二轮加严——A 回滚的旧日程证不了复验）**：连接 A 开事务把目标 `parent_session_id` 从授权父 P 改为无关 U（未提交、持 sessions 行锁）→ 连接 B 以 actor=P 调用（锁前谓词见旧提交态 P，随后阻塞在 sessions 锁）→ 观测确认 B 已阻塞（`pg_locks`）→ A **COMMIT** → B 醒后必须由锁后复验得 `v13: session not found`，零事件零 effect 变化；控制日程：A ROLLBACK（或不改 parent）→ B 同调用成功。**cancel 半边用 2 参 cancel；complete 半边必须用 6 参 + kind=human 的 effect，且 fence/attempt/`interaction_ref`/one-of payload 与同夹具超户成功应答完全相同**（kind≠human 的 6 参在取锁前就以统一文案返回，`pg_locks` 等不到阻塞；human payload 空着则 ROLLBACK 对照会停在 C4）——A ROLLBACK 后 B 的返回词与 `human/responded` 与超户成功路径相同。两动词各自跑完才钉住两个正文的复验。

**源码断言**：2 参 cancel 相对 dump 的差集只有准入段+复验段；6 参 complete 差集 = 锁前扩列+定位/准入分支 + `unknown effect` 段的 actor/带分支 + 锁后复验段；**旧 wrapper 体为纯委托（只含 `RETURN v13_cancel(NULL::uuid, p_sid)` / `RETURN v13_complete(NULL::uuid, ...)`，grep 防第二份实现）**；**2 参 cancel、6 参 complete 与两个 wrapper 的 prosrc 不出现 `v13.control_actor`、不调用 `current_setting`**（R8-①已拒 GUC 的 stage 23 面）；dump 留测试进程可比较位置（不写进仓库）；`pg_get_function_identity_arguments` 与换体前记录逐项相同（含旧签名），另比 `pg_get_function_arguments`/`pronargdefaults`；authorized prosrc 无 `current_setting`/`request`/`status`/`payload`；operator prosrc 含 `USAGE` 无 `MEMBER`；`v13_route` 字面量只在 operator 函数体；新文件无 `CREATE TABLE/VIEW/ALTER TABLE/LISTEN/pg_terminate_backend`；D12 符号存在性断言（`to_regprocedure('v13_record_worktree_released(uuid,uuid)')` 非空 ⇔ 6 参源码含该名恰一次）；`has_function_privilege`：新函数对 route/（spawn_owner 按镜像）真、对 PUBLIC/worker/recall/resolve 假。

**回归**：stage 1→当时加载序末项全部 `test_*.py` 退出码 0（Phase A 在则含 seam/catalog）。

### 3.5 收尾

`SQL_LOAD_ORDER` 追加 acl→23；`STAGE_THROUGH["acl"]=23`。覆盖矩阵 stage 23 行（正负例各一行，提交时必须实跑 ✅）。台账（**F27 起——F24=R6、F25=R7/R7b、F26=R9（D14 断言 B 复裁，Phase A stage 22 已占）均已被占用；实施时以台账实际下一空号为准**）：F27 actor 通道与信任边界（overload；DB 只验带+亲缘，来源由服务端绑定）；F28 生产绑定两格（合同已证明/驱动器未交付）；C15 D7「非终态」读作动词有效控制面不进谓词（终态 `replay` 保持）；**③ 例外（含 parity F17 字面冲突）**：operator 且 actor 空且目标无行保留活体 `v13: unknown session %`（cancel）/`v13: unknown effect %`（complete），agent 路径与非 operator 空 actor 一律 `v13: session not found`——台账一行。

## 4. Stage 24 `v13/observe/`

### 4.1 前置

重读已安装 `v13_control_authorized`（identity/返回类型）+ §2 pending/cancel 探针。谓词缺失或形状不符 → 停。不换体 stage 23 函数。

### 4.2 SQL 序（`v13/observe/v13_observe.sql`，单事务）

1. DO：谓词 identity 为 `p_actor uuid, p_target uuid`；pending/cancel 选定函数可按适配表成布尔。
2. `CREATE FUNCTION v13_observe(...)` §1.3 规格（plpgsql 多段：参数段→授权段不查 events→快照段）。
3. `CREATE FUNCTION v13_session_log(...)` §1.3 规格。
4. `REVOKE ... FROM PUBLIC` 两函数；GRANT 只 `v13_route`。
5. COMMENT。无触发器/策略行/索引。

### 4.3 Gate（`uv run python v13/observe/test_observe.py`）

- 父 actor `[C]`：一行，列与实际 status/turn_no/parent 一致；无事件 `last_event_seq=-1`、type NULL。
- `[C,另一直接子]`：两行、序=输入序、ordinal 连续。
- `[C,U]`/`[C,G]`/`[P]`（自身）/`[不存在]`/自身与子混装：零行且无异常（混合数组不泄露真子存在——**单测后续 `[C]` 仍一行**证是隐藏非不可观察）。
- 空数组、NULL 数组：零行；重复 id：`v13: observe duplicate` 零行；NULL 元素：`v13: observe id`。
- 行政 NULL actor 超户：可观察 U 与 P；**抗环境噪声例（替代原 GUC 用例）**：先 `set_config('v13.observe.probe', 'x', true)`（任意不被读取的会话变量）再以参数调用 → 结果仍按参数——证 observe 只吃参数不吃任何环境变量。
- session_log：**未授权且游标 `< -1` → RAISE `v13: session log cursor`，与已授权同游标文案逐字相同、不含 uuid，不是零行**（证明形状检查在谓词前）；未授权且游标 NULL/合法 → 零行无异常；授权后行集 = `SELECT` 同列 `ORDER BY seq` 逐行相等；`p_after_seq`=max 零行；−1 与 NULL 全文；追加事件后 watermark 精确前移；两次无写调用字节等价。
源码断言：**`v13_observe` 与 `v13_session_log` 的 prosrc 不出现 `v13.control_actor`、不调用 `current_setting`；同句覆盖当时 `to_regprocedure` 能解析到的 stage 23 函数（operator/authorized/2 参 cancel/6 参 complete/两 wrapper）——解析不到的 stage 25 名字跳过，不得把空 regprocedure 判失败**；两函数 `provolatile='s'`、无 `LISTEN`/`pg_sleep`/`CREATE TABLE`。**`v13_session_log` prosrc 无 `parent_session_id`、无 `JOIN effects`；`v13_observe` 授权段不读 `parent_session_id`（亲缘只出现在谓词调用里），快照段把该列作已授权行的输出列——observe 整段 prosrc 出现该列名是合规，禁再断言「observe prosrc 无 parent_session_id」**。
- 权限：route 真；PUBLIC/recall/worker/resolve/spawn_owner 假；**必有一条 `SET ROLE v13_route` 成功路径**（超户绿不算数）。
- 回归：1→24。

### 4.4 收尾

加载序 observe→24；矩阵 F8 全有或全无/F18 先授权再读/空数组/游标/权限行；台账 F29（读面拒绝=零行不 RAISE，与 cancel 的 RAISE 并存——旧动词保 needle、新读面避免异常区分存在性）；README（列契约、无 waiter、驱动器重入合同）；parity F8/F18 标已补（进「改变」桶注记）。提交 `v13: add authorized observe and session log`；回退 revert。

## 5. Stage 25 `v13/handoff/`

### 5.1 前置

§2 D16 探针全做；`v13_state_hash` 仍是排除名单才继续；策略 INSERT 探针（证伪第 7 条）；`control/handoff` 零历史行断言（证伪第 6 条）。**schema CREATE 探针在角色创建之后（§5.2 步 2 内）执行**——首装时角色尚不存在，探针不得前置（R8 六轮）。

### 5.2 SQL 序（`v13/handoff/v13_handoff.sql`，单事务；R8-④ 已选 DEFINER——本节是唯一施工序，无替代分支）

1. DO 安装前：无 `control/handoff` 历史行（有 → RAISE `v13: handoff baseline` 列 session/seq，不回填不修史）；`handoff_policy` name 未占用。
2. DO `CREATE ROLE v13_handoff_owner`（属性恰 `NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS`、无成员；已存在则断言属性与 membership，不符 RAISE `v13: handoff baseline`）。**创建后立即以该角色 OID 检查 `CREATE ON SCHEMA public`（PG15+ ALTER OWNER 前置）——不足则幂等 `GRANT CREATE ON SCHEMA public TO v13_handoff_owner` 并断言生效；CREATE 保留为运行期权限（角色 NOLOGIN 零暴露）并纳入步 12 直接 ACL 断言**。
3. 属主自举 GRANT **只授当时已存在的对象**（**digest 只授 `digest(text,text)`、`pg_catalog.gen_random_uuid()` 显式授——均与步 12 同句，bytea 载不授**）：`USAGE ON SCHEMA public` + `SELECT,UPDATE ON sessions` + `SELECT,INSERT ON events` + `SELECT ON effects` + `SELECT ON v13_policies` + `EXECUTE v13_append_event(uuid,uuid,text,jsonb,uuid)/v13_assert_unknown_wall(uuid)/v13_json_keys(jsonb)/v13_json_int_ok(jsonb,int)/v13_canonical_uuid(text)/digest(text,text)/pg_catalog.gen_random_uuid()`（`v13_transcript_hash` 尚未建，步 5 后补授）。另探针 `has_table_privilege('v13_route','v13_policies','SELECT')`（extract 以 route 身份直读 policies——schema 既有授权应已满足，不足则幂等补授并记台账）。
4. INSERT 策略种子 `('handoff_policy',1,'{"schema_version":1,"enabled":true}',true)`（INSERT 不被 `v13_policies_frozen` 拦——它只拦 DELETE 与 name/version/**value** 改写；`active` 翻转是注释写明的唯一合法 UPDATE）。
5. `CREATE FUNCTION v13_transcript_hash(p_sid uuid, p_up_to_seq bigint) RETURNS text STABLE SET search_path = pg_catalog, public`——材料 §1.2 规范字节式（拒负 cutoff；排除 handoff；不含 at/event_id/payload 原文）；未知会话 RAISE 活体形 `v13: unknown session %`（非授权边界）。**创建后立即 `GRANT EXECUTE ON FUNCTION v13_transcript_hash(uuid,bigint) TO v13_handoff_owner`**（精确签名）。
6. `CREATE FUNCTION v13_handoff_emit(p_sid uuid, p_payload jsonb) RETURNS bigint SECURITY DEFINER SET search_path = pg_catalog, public` → `ALTER OWNER TO v13_handoff_owner`。**体先按 §1.2 与 extract 同一套规则读 `v13_policies`**（`v13: handoff policy`/`v13: handoff disabled`，任一失败零写且在 append 之前）；通过后唯一写调用是 `public.v13_append_event(p_sid, pg_catalog.gen_random_uuid(), 'control/handoff', p_payload, NULL)`。信封形状只由守卫查，emit 不另写一套校验。
7. `CREATE FUNCTION v13_handoff_event_guard() RETURNS trigger` **INVOKER SET search_path = pg_catalog, public**，WHEN `NEW.type='control/handoff'`，检查序 §1.2 全部八项（只 RAISE 不改行）。
8. `CREATE TRIGGER trg_handoff_guard BEFORE INSERT ON events FOR EACH ROW WHEN (NEW.type='control/handoff')`。不改 stage 17/20/21 守卫。
9. 两个部分唯一索引（§1.2；表达式与守卫同一套 canonical 文本）。这是守卫之后的最后一层不是竞态解；emit 不写 `ON CONFLICT`。
10. `CREATE FUNCTION v13_extract_handoff(p_actor uuid, p_sid uuid, p_up_to_seq bigint DEFAULT NULL) RETURNS jsonb VOLATILE INVOKER SET search_path = pg_catalog, public`——§1.2 控制流（授权→锁→复验→watermark→hash→**同身份回读（存在即返原 payload，先于策略）**→策略→delivery→emit；无 EXCEPTION）。
11. `REVOKE EXECUTE ... FROM PUBLIC`：transcript_hash/emit/extract/守卫。GRANT transcript_hash → `v13_route`+`v13_handoff_owner`；emit/extract → `v13_route`。不授 worker/recall/resolve/spawn_owner。
12. DO 安装后（**与 §1.2 同一张清单，缺一项即安装失败；断言先于任何 route 真 COMMIT**）：①**直接 ACL 证明（非有效权限）**——对每个已解析函数 OID 检 `aclexplode(coalesce(proacl, acldefault('f', proowner)))` 存在 `grantee='v13_handoff_owner'::regrole AND privilege_type='EXECUTE'`（`has_function_privilege` 只作运行时有效闭包副证，PUBLIC 默认会掩漏授）；schema/表同理查 `nspacl`/`relacl` 直接项（含保留的 `CREATE ON SCHEMA public`）；②EXECUTE 清单含 `to_regprocedure('pg_catalog.gen_random_uuid()')` 与 `to_regprocedure('digest(text,text)')` 的 OID（**规范字节式第一参是 `jsonb::text` → 只授/只断言 text/text 这一载；`digest(bytea,text)` 不授不断言；裸名 `digest` 禁用（解析期 42725）；任一 to_regprocedure 为 NULL → 停工报事实，禁改授 bytea 重载**）；③属性断言：emit `proowner=v13_handoff_owner ∧ prosecdef=true`；hash/守卫/extract `prosecdef=false`；四函数 `proconfig` 都含 `search_path=pg_catalog, public`。
13. COMMENT。

### 5.3 Gate（`uv run python v13/handoff/test_handoff.py`）

**必含一条 `SET ROLE v13_route` 后真正 COMMIT 的成功 extract**（超户绕过不算，F19 教训；route 是 NOLOGIN 用超户 SET ROLE 合法）。

**授权先于读取**：unauthorized + 非法 cutoff 只得 `v13: session not found`；unauthorized + disabled/malformed policy 环境仍只得授权错误；self/孙/无关/未知四类同文案同 SQLSTATE 零事件。

**收据形状**：首次返回恰四键；事件 payload 与返回值逐字相等；`source_effect_id` NULL；`up_to_seq` 指向调用前非 handoff 事件、收据 seq 严格更大；hash 小写 64 hex；sessions 行数/parent 关系/artifacts 行数不变；无 `forked` 事件；父会话事件数不变；子会话数不变（不 fork）。

**cutoff/hash**：NULL 选最新非 handoff seq；**空会话（无任何非 handoff 事件）NULL cutoff → `v13: handoff empty`，事件数与 `sessions.next_seq` 不变；同一空会话显式 0 → `v13: handoff watermark`，同样零写（两条文案不得互换）**；负数/缺失 seq/指向 handoff/大于 max → `v13: handoff watermark`；**直调 `v13_transcript_hash(sid, -1)` 被拒**；终态事件含在 hash 中；**材料独立重算**（gate 按 §1.2 规范字节式自行 digest，禁调 helper 自证）；同账本快照重复调 helper 稳定。

**幂等与并发（R8 已裁身份去重，唯一活规格）**：无业务新事件时重复 NULL 调用返回同 `delivery_id`、事件数仍 1、`state_hash` 不变；新增非 handoff 事件后 NULL 调用得第二 delivery；此后显式旧 cutoff 返回第一份；**policy 禁用/畸形下同身份重放仍返回原 payload、零新事件、`next_seq` 不变（回读先于策略）；新 identity 在 disabled 下 → `v13: handoff disabled`**；双连接同时提取同 snapshot——第二连接堵 session 行锁、醒后返回同 payload、总事件 1；**两索引正交夹具（R8 三轮）**：重用已有 `delivery_id` + 不同合法 `(sid,up_to_seq,hash)` → 23505 且约束名 = `ux_events_handoff_delivery`；同 `(sid,up_to_seq,hash)` + 新 canonical `delivery_id` → 23505 且约束名 = `ux_events_handoff_snapshot`（route→emit 同身份直调亦须用新 delivery_id 才证命中快照索引）；`pg_index`/`pg_get_indexdef` 断言恰两索引、表达式/谓词/唯一属性逐项匹配计划。

**守卫负例（R8 二轮：以属主身份直插，否则全部停在首项 `handoff writer` 系统性假绿）**：payload/hash/watermark/source 类负例在 `SET LOCAL ROLE v13_handoff_owner` 后直接 INSERT，逐例断言**精确文案或 SQLSTATE**（非「有异常」）；缺键/多键（jsonb 不保序，无「键序错」负例）；`schema_version` 字符串 `"1"`；非 canonical delivery；hash 非 64hex；hash 与前缀不符 → `v13: handoff hash`；watermark 无对应 seq/指向 handoff/**非整数 `1.5`（夹具：该会话已有非 handoff `seq=2`，键集恰四键且余三键合法，hash=cutoff 2 前缀的规范字节式，唯一非法字段 `up_to_seq=1.5`，与「缺口 seq」分列）**/**存储后 `1.0`（夹具同构：`seq=1` 存在、hash=seq=1 前缀规范式、材料 cutoff 为整数 1，唯一非法=存储文本 `'1.0'`——`1.0=trunc(1.0)` 在 numeric 上成立，只有文本等式一步能拒它）**/**`9223372036854775808`（bigint 溢出，期 `handoff watermark` 不泄 22003）**；`up_to_seq` 失败文案统一 `v13: handoff watermark`（§1.2 守卫同文）；`source_effect_id` 非 NULL（→ 精确文案 `v13: handoff source`）；重复 delivery/快照身份 → 23505（正交夹具见幂等组）。**唯 route 直接 `v13_append_event` 写 `control/handoff` 的旁路用例**期待 `v13: handoff writer` 零行。

**route→emit 直调（行为已定义，R8-④）**：`SET ROLE v13_route` 直调 emit 写合法信封 → 成功落收据（受信内部 helper）；同身份再直调 → 快照唯一索引拒（裸 23505，route 自担）；`enabled=false` 时直调 emit → `v13: handoff disabled` 零事件（emit 内策略门禁）。

**策略**：SAVEPOINT 内 INSERT v2 `('handoff_policy',2,'{"schema_version":1,"enabled":false}',false)` → **两条有序 UPDATE**（先把 v1 `active` 置假、再把 v2 置真——同一条 UPDATE 先点亮 v2 会撞非 DEFERRABLE 的 `ux_v13_policies_one_active`，失败模式是裸 23505 不是 `handoff disabled`）→ `v13: handoff disabled` → ROLLBACK 恢复种子。禁 UPDATE 种子 value；无跳过分支。**零 active 行（R8 四轮恢复——UPDATE 置 v1 inactive 即可构造，无需 DELETE）**：SAVEPOINT 内把 v1 `active=false` 不插新版 → 既有 identity 的 extract 仍返原 payload 零写（回读先于策略）→ 新 identity 经 extract 得精确 `v13: handoff policy` → route→emit 新写入同得 `handoff policy` → 全部失败路径事件数与 `next_seq` 不变 → ROLLBACK。**形状负例**（extract 与 route→emit 各至少一次；物理 DELETE 不测——种子被 `v13_policies_frozen` 拦；可执行形状=多键与 `enabled` 类型错，构造 = INSERT 新版本 `active=false` + 两条有序 UPDATE 切换）→ `v13: handoff policy`、零事件。

**取消/超时（测试专用阻塞触发器法）**：测试库临时安装仅针对 `control/handoff` 的 test-only BEFORE INSERT 阻塞触发器；append 已更新 session、后端阻塞在 INSERT 时客户端 cancel；验证整笔事务回滚（events 行数与 `sessions.next_seq` 回到调用前）；结束后回滚该测试对象。仅比较终态不足以证明取消发生在写入之后（授权阶段超时同结果）。

**state_hash 方向**：首写收据前后 `h_before <> h_after`；幂等重放前后相同；不换体不进排除名单。

**源码**：`v13/handoff/*.sql` 无 `v13_fork`/`INSERT INTO sessions`/`INSERT INTO artifacts`/xml（大小写不敏感）/`pg_read_file`/`LISTEN`/`pg_terminate_backend`/`CREATE VIEW`/`ON CONFLICT`/`CREATE OR REPLACE FUNCTION v13_state_hash`/`CREATE OR REPLACE FUNCTION v13_advance`；**emit prosrc 含 `v13_policies`（策略门禁在源码层钉住）；`v13_extract_handoff` 与 `v13_handoff_emit` 的 prosrc 不含 `EXCEPTION`（同身份重放只经由锁内 canonical 文本回读返回原 payload）**；**四函数（hash/emit/守卫/extract）prosrc 不出现 `v13.control_actor`、不调用 `current_setting`**；**schema-qual 硬断言：四函数对 `events`/`sessions`/`effects`/`v13_policies`、对 `v13_append_event`/`v13_transcript_hash`/`v13_json_keys`/`v13_json_int_ok`/`v13_canonical_uuid`、对 `digest` 与 `gen_random_uuid` 的调用都带 `public.` 或 `pg_catalog.` 限定（§1.2 的 jsonb_build_array 块只约束 digest 入参字节，不是 prosrc 逐字模板）**；emit DEFINER、守卫不是；extract 调 authorized+emit 且授权在 `FOR UPDATE` 之前。

**回归**：1→25。

### 5.4 收尾

加载序 handoff→25；矩阵（先授权再写、恰一条/幂等按裁决、无 XML、父事件数不变、不插子会话、hash 可复核、state_hash 方向、route 真 COMMIT、守卫负例、F19 属主自举）；台账 F30（前缀窗口非源尾窗——四键重算所要求）+ F31（收据排除出 transcript 材料——防自激；含 route→emit 直调=受信内部 helper 行为已定义）+ C16（R4:23 非生命周期收据澄清，R8 明文）；

## 6. 全局红线（每 stage 收尾检查）

1. 零新表零新列（含物化视图/投影表/概念缓存表）；新索引只 stage 25 **恰两个**部分唯一索引（R8 固定，非可选）。
2. stage 1–20 文件字节不动；Phase A 文件（seam/catalog）本期也不改。换体/overload 底稿 = 当日活体 dump；差集只有 §3.2 指明的块；换体前后签名/owner/security/search_path/GRANT 逐项比对。
3. events 仍是唯一干预通道；交接唯一写函数 = `v13_handoff_emit`（受信 route 可直调——「唯一写函数」非「唯一可调用者」，§1.2 route→emit 处置）。
4. 外部 IO 不进事务；本三期函数不读文件、不杀后端、不听通知。
5. 读面不授权：observe 返回真值只表示「可以再读」，不是已执行/已允许 cancel。
6. watermark 只用 `events.seq`；不拿 `duty_cycle`/`decisions.epoch`/`turn_no` 当交接水位。
7. gate 全绿才 commit：该 stage 退出码 0 + 回归此前全部 stage；按路径 add；禁 `git add -A`/force-push/`--no-verify`；一 stage 一提交一推送（AGENTS.md）。
8. 超户绿不算数的路径：stage 24/25 至少各一条 `SET ROLE v13_route` 成功 COMMIT；stage 23 agent 用例必须走 2 参 cancel 与 6 参 complete（R8 已拒 GUC，无别的形态）。
9. 每期收尾架构审计（R4）：无概念性控制表/物化投影/影子状态源；新读面是函数；新写面归既有事件/策略/具名函数路径；无第二份亲缘判断（亲缘只活在谓词）、无第二份 transcript hash。

## 7. 假绿对照（实施时逐条自检）

| # | 假绿样子 | 钉死手段 |
|---|---|---|
| 1 | 只跑超户不传 actor，亲缘从未执行 | agent 用例强制真通道；operator/agent 各有断言 |
| 2 | 只在 wrapper 授权、canonical overload 可绕过 | overload 正文自身授权（§3.4 源码 diff 断言差集含准入段；wrapper 体为纯委托 grep） |
| 3 | 授权写在 append 之后，异常仍留 cancel 事件 | 负例比较事件数与 effect.status |
| 4 | observe 一条 SQL join，未授权 id 仍读到事件 | 规定 plpgsql 多段；混合数组零行而单 id 有行 |
| 5 | self 与孙文案不同或带 uuid | 跨用例字符串全等且不含 uuid |
| 6 | human 只在 succeeded 检查，自答用 failed 绕过 | kind=human 全 status 先授权；未授权看不到 replay/stale |
| 7 | 非空 actor 被忽略成行政（operator 传了 actor 仍行政放行） | §3.4 operator+actor gate（route 2 参 cancel 无关 actor → 拒；超户 6 参 complete actor+tool effect → 拒）；非法 uuid 文本在参数类型边界被拒 |
| 8 | 工具 JSON 的 actor 被读 | 谓词源码无 request；伪造键用例仍统一文案 |
| 9 | 孙被当「树内即可」 | 直接 `v13_cancel(G)` 零写；`v13_cancel(C)` 仍扇出 |
| 10 | worker 因 MEMBER 变 operator | USAGE 探针（`pg_has_role('v13_worker','v13_route','USAGE')=假`）；worker 对 operator/authorized 无 EXECUTE（42501） |
| 11 | 换体从 fanout 文件回贴，丢 Phase A 改动 | 只许相对当日 dump 插块；D12 符号存在性断言 |
| 12 | complete EXCEPTION 把统一文案收成 stale | 前置证伪；负例见该文案 |
| 13 | observe 未授权 RAISE 被当「失败」通过 | 零行用例断言无异常 |
| 14 | session_log join effects 且授 recall | 列清单无 effect 字段；不 GRANT recall；recall 42501 |
| 15 | 幂等做成 no-op 使「恰一条」永真 / 每次新收据 spam 重试 | 按 R8 身份去重单一规格断言（重复 NULL 同 delivery 事件数 1；新事件后第二 delivery） |
| 16 | hash 把自己收据算进去，NULL cutoff 永不稳定 | 材料排除 handoff；显式旧 cutoff hash 相等 |
| 17 | 为满足 R4 建 VIEW 或 `v13_latest_handoff` | 草案不加；源码断言无 VIEW；裁决点名才加 |
| 18 | 把 handoff 写进 state_hash 排除名单图安稳 | 方向断言 `h_after ≠ h_before`；禁换 state_hash |
| 19 | 超户 extract 绿、route COMMIT 时属主 42501 | route 真 COMMIT 必测；安装后 DO 查 F19 式 GRANT |
| 20 | 引入 max_events/allow_empty/静默截断等种子未定义的限流，或对空会话写收据 | 极简键集无超限概念；源码/gate 断言：消费任何限额键、截断前缀、或空会话写出收据 = 失败 |
| 21 | 交接顺便 fork/写父会话 | 父事件数与子会话数不变；源码无 v13_fork |
| 22 | 改了 cancel 返回词表 | 失败=异常；成功仍只 accepted/replay |
| 23 | `REVOKE ALL` 换体函数使 route 丢 complete | 明文禁止；回归 stage 17–20 作第二道 |
| 24 | 6 参正文漏镜像旧 proacl → wrapper 内 42501 | 按活体 proacl 镜像 + has_function_privilege 断言 |
| 25 | 锁内回读用另一套表达式，索引命中裸 `23505` 被当竞态放行 | §1.2 回读同套 canonical 文本；gate 断言双连接重放返回原 payload 而非异常；禁 EXCEPTION 吞 `23505` |
| 26 | route 直调 emit 绕过 extract 的授权/策略面被当漏洞或被静默 | §1.2 route→emit 直调处置（受信内部 helper，行为已定义）+ gate 三断言（成功/同身份 23505/disabled 拒） |
| 27 | 6 参 wrapper 丢默认参数，既有 4 实参调用变函数不存在 | §3.2 步 7 默认参数逐字保持 + pg_get_function_arguments/proargdefaults 比对 + 旧 4 实参调用 gate |

## 8. Phase A 落地后复核指导（stage 23 硬前置；Phase A 收尾后、写 stage 23 SQL 前执行）

> 写作时基线：**stage 21（e925ebe，R7/R7b）与 stage 22（7200317 起，R9–R12 D14 断言链）均已提交——complete 活体已含 D12 写者调用、catalog 已换体；Phase A 余下的是验收收尾**。本节不是一次性快照而是每次开工前的强制刷新（实跑 stage 1→22 全部 gate）。本节结果写成台账一段，不改 F17 四动词合同。

### 8.1 绑定假设表

| # | Phase B 假设 | 写作时证据 | 不符时 |
|---|---|---|---|
| A1 | 加载序可末尾出现 seam=21、catalog=22，Phase B 从 23 追加 | load.py 末两项 = seam=21、catalog=22，均已提交（末笔 f59058d） | 末尾不是已绿 catalog 又无台账弃权 → 不追加 acl（§2 证伪 9；「已提交」以实跑绿为准） |
| A2 | `v13_cancel` 不被 Phase A 换体 | Phase A 换体名单无 cancel | 以 dump 为准；标记串缺失 → 停 |
| A3 | `v13_complete` 已含一次 D12 写者调用（R7 两语句形）；签名/INVOKER/无吞异常 EXCEPTION 不变 | stage 21 e925ebe + R7/R7b | 出现 DEFINER 或吞异常处理器 → 停工请裁；D12 调用按当日 dump 保留恰一次（两语句形不重排） |
| A4 | state_hash 仍是排除名单 | preflight §7.1 | 变白名单且不含 handoff → stage 25 停工报事实 |
| A5 | 亲缘列仍是 `parent_session_id` | schema | 列没了 → 停，不另找 link |
| A6 | 事件守卫可并列，无需改 stage 17 WHEN 列表 | control 守卫按 type 过滤；seam 守卫今日 WHEN type='worktree/released' 不误伤 | `control/handoff` 被 stage 17 **或 seam（或未来任一）守卫**误伤 → 停，报 WHEN 列表，不改既有文件 |
| A7 | Phase A 范围收缩（若再停工）只改底稿形状不改四动词合同 | R6 §5；Phase A §7 | 不把「Phase A 绿」改写成「stage 17–20 绿」；书面弃权须点名「stage 23 底稿 = stage N dump」 |
| A8 | R6 的 GRANT 闭包修正已落（record_worktree_released→route+spawn_owner；禁 worker/resolve/PUBLIC） | R6 §4；seam 已提交（f59058d），`v13_seam.sql:687` 的 GRANT（route+spawn_owner）已在库；以当日活体 ACL 为准 | 不符 → 停，对账 R6 |

### 8.2 复核步骤

1. 读 `load.py` 的 `SQL_LOAD_ORDER`/`STAGE_THROUGH`，记长度与末两项。
2. 实跑 stage 1→22 全部 gate（seam/catalog 测试文件不存在 = Phase A 未绿 = 停在这一步）。
3. stage 22 全量库上 dump：`v13_cancel`/`v13_complete`/`v13_append_event`/`v13_state_hash`/`v13_policy` + Phase A 新函数（`v13_record_worktree_released`/`v13_worktree_state`）+ events 上全部 guard trigger；逐函数记 owner/prosecdef/provolatile/proconfig/identity/ACL；**dump 与元数据存仓库外临时核查目录（不进仓库）**。形状检查含：**replay/stale 仍在一切新写者之前**。**语句级重定位**：本计划所引 `:320`/`:321`/`:326`/`:348`/`:355` 是 fanout 快照行号，不是活体插入点——在 dump 上按**语句**重定位（无锁读出 effect 行、session 锁、effect 锁、`unknown effect` RAISE、stale/replay 返回、cancelled 的 UPDATE、human 围栏、D12 调用位置）后写 SQL；禁按 fanout 行号或 `v13_fanout.sql` 回贴。
4. 全仓检索 `v13_cancel(`/`v13_complete(` 调用点，分四类：生产/gate/历代死体/demo（gitignored）——spawn_owner 依赖 grep 在此出结论。
5. stage 1–20 文件哈希比对，证字节冻结未被破坏。
6. 填 §8.1 对照表；只有「D12 调用在/不在」按分支继续，其余不符走 §8.3。

### 8.3 修订协议

- 活体与本草案只差 D12 调用有无：不改计划，按 §3.2 存在性分支做。
- 差在签名/安全属性/异常处理器/亲缘列/hash 形状/守卫误伤：停工，把 dump 事实写进台账新行请裁（R5 §8「报事实不自行改裁」），实施者不改真值表迁就。
- Phase A 追加了**影响准入语义**的换体（如 complete 内部新守卫）：回 R8 补裁决，不随 Phase B 夹带。
- Phase A 造出同名 overload、`control/handoff` 历史行或新控制角色：接口冲突，停并回 R8 重裁。
- 任何修订不改 F8/F17/F18/F29 的返回形状、文案与零写要求。

## 9. 文件级影响与实施顺序

| 文件 | 动作 | 时机 |
|---|---|---|
| `v13/acl/{v13_acl.sql,setup_db.py,test_acl.py,README.md}` | 新（setup_db 抄 triage 的扩展探针与 stannum GRANT，不是空 setup） | stage 23 原子提交 |
| `v13/observe/{...}` ×4 | 新 | stage 24 |
| `v13/handoff/{...}` ×4 | 新 | stage 25 |
| `v13/load.py` | 末尾追加三项 + `STAGE_THROUGH` 三键 | 与对应 stage 同提交，禁半截序号 |
| `docs/reviews/v13-control-plane-conformance-matrix-*.md` | 每 stage 追加行（不预写 ✅，行号续不重排） | 各 stage |
| `docs/reviews/v13-control-plane-deviation-ledger-*.md` | F27 起追加（**F24=R6、F25=R7/R7b、F26=R9 均已占用**；以实际下一空号为准）+ C15/C16 | 对应事实出现的 stage |
| `docs/reviews/v13-control-plane-parity-rpce-loopx-*.md` | 追加「Phase B 状态」节，不改 2026-09-26 计数表 | 随对应 stage |
| `docs/plans/v13-layered-control-roadmap-*.md` | **仅在 R8 后**把 D7/D16 标已裁 | 与 R8 记录或 stage 25 同提交 |
| `docs/reviews/v13-control-plane-oracle-r8-<date>.md` | R8 裁决记录 | 裁决轮产出 |

不改：`v13/schema|control|spawn|fanout|triage` 及其余 stage 1–20 路径；不新建 `v13/seam` SQL（Phase A 的文件）；`demo_v13/driver.py` 补丁 gitignored 不进里程碑。

**实施顺序**：①R8 裁决（零 SQL，§1 送出；不一致先改本文件）→ ②Phase A 复核（§8，可与①并行）→ ③stage 23（探针→SQL→gate→回归→收尾→原子 commit+push）→ ④stage 24 → ⑤stage 25（R8 未点名 `v13_latest_handoff`，不建该函数——若未来另裁点名则与⑤同提交：STABLE 只读、返回该会话最大 seq 收据四键、无行零行、advance 不调、GRANT 同 extract）→ ⑥Phase B 总验收：`SET ROLE v13_route` 非超户走通六动词（观察=observe/log；注入=既有通道；应答=actor-aware complete；取消=actor-aware cancel；授权=authorized；交接=extract），只汇总已跑 gate，不新增跨 stage 大提交，不把 waiter/XML/水合/驱动器绑定声明为完成。步骤③④⑤之间不插入别的加载序改动；④⑤不并行改 `SQL_LOAD_ORDER` 末尾。

## 10. 不做清单（Phase B 范围外，防夹带）

steer 正文；`closeout/inbox_residual`；`quota/spent|voided`；`material_cap` human 生产；`thresholds.action` ALTER；`v13_operator`/`v13_agent` 新角色（D7-alt-strong 是替代项非草案）；RLS；收回 recall 的 events SELECT；把动词改 DEFINER；waiter/超时列/`LISTEN`/`NOTIFY`/阻塞 poll；多 id 交接跨会话原子批次；link 表/send 账本/审批经纪人/墓碑删除/shutdown/TTL/冷恢复（F5/F16/F19/F20/F21/F24–F26/F30 永不建）；XML/文件水合/artifact 正文/`max_tool_args_characters`/尾窗；Phase C 全部（should-run/配额窗/attention/scheduler hint/goal stop-resume/`v13_goal_lifecycle`）；L29；D10/D15；在本里程碑提交 `demo_v13/driver.py`；编辑 stage 1–20 测试或 SQL。

## 11. References

- 母计划：`docs/plans/v13-layered-control-roadmap-2026-09-26.md`（§2.2/§2.3/§2.4/§3 Phase B L214–222/§4 D7·D16/§5）
- Phase A 计划现行版（r12 链）：`docs/plans/v13-phase-a-seams-plan-2026-09-26.md`；preflight：`v13/seam/preflight.md`
- R4：`docs/reviews/v13-control-plane-oracle-r4-2026-09-26.md`；R5：`.../v13-control-plane-oracle-r5-2026-09-26.md`；R6：`.../v13-control-plane-oracle-r6-2026-09-27.md`（D11 has-event；台账 F24；GRANT 闭包修正）
- parity 裁决：`docs/reviews/v13-control-plane-parity-rpce-loopx-2026-09-26.md`（F8/F17/F18/F29 源合同；:221 测试立场；§6 残留 R6 消歧）
- RP-CE 卷宗（gitignored）：`prompt-exports/parity-rpce-2026-09-26.md`（F17 L119-124/F8 L58-63/F18 L126-128/F29 L200-204 源码与测试锚）
- 台账：`docs/reviews/v13-control-plane-deviation-ledger-2026-09-26.md`；覆盖矩阵：`docs/reviews/v13-control-plane-conformance-matrix-2026-09-26.md`
- 迁移调查：`docs/analysis/v13-control-plane-migration-2026-09-25.md`（§2.2）；工程纪律：`AGENTS.md`
