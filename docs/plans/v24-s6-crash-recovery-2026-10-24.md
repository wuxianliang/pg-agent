# v24 S6 崩溃恢复：Deep plan

- 状态：**planned；Oracle-approved（chat 028D07）；未实现**。本文件只冻结 S6 合同；不修改 `v24/**` 产品代码或测试。R6.1 的设计稿/pre-plan 同步见设计稿 C.5 与本文件 §8。S6 的自有 gate 为 **G5**。
- 工作树：`/Users/wxl/Projects/pg-agent/.claude/worktrees/v99`，branch `v24`，HEAD `9701c2e`（R6 文档同步后的基线；S1–S5 已实现，G1–G4 已由 S5 收口记录为绿）。
- 上游权威：`docs/designs/v24-pg-agent-2026-10-22.md`（§8 L406–421 十行崩溃矩阵、§9 L429–441 G5、§9.1 L442–449 重启证据、§10.2 L464–473 显式债务、§B.3 L533–557、§B.4 L558–581、§B.5 L582–608、附录 C.1 L658–678、C.3 L708–718、C.4 L719–730、C.5 L732–754）；`docs/plans/v24-pre-plan-2026-10-23.md`（§3 S6 卡 L168–180、§4 C14 L226、§8 O11 L367、§7.2 L301–309、§7.3 L313–315）；`prompt-exports/loop-orchestrate-v24-s6-s7-runs.md`（R6 裁决与预算）。
- 与 S5 的关系：S5 已冻结清理闭包与 `disposed`/`closed_at`/`resource_quiesced_at` 的写者；S6 只消费这些事实，不重开清理语义、不新增表、不新增错误码。
- 阅读导引：先读 §2 的边界与 §3 的映射表，确认 S6 只做“崩溃后重启收敛”；§4 是本文的承重面（两个函数、一个 kind、一个解释器、精确 delta 与 ACL）；§5 是 G5 十窗口与负例；§6 是独立 OS 子进程 harness；§7–§9 是施工、风险/分歧与验收清单。任何与设计稿不一致处集中在 §8，且均给出可替换的精确文本，不在正文静默改规格。

---

## 1. 执行索引

| 项 | 内容 |
|---|---|
| Goal | 用设计 §8 的十个崩溃窗口证明：进程在任意边界被 `SIGKILL`（K4 为 SQL 错误注入）后，重启只用 `resolve(scope,keys)` + 未结算 effect 扫描 + 唯一 `command_recover(scope)` 入口收敛；`replay_safe` 只重投、`no_replay` 只转 unknown、`manual` 只报告；恢复没有自己的表/队列/lease/cursor，没有第二 claim 路径，没有第二状态机。 |
| Done when | 1. `v24/s6/test_g5.py` 的 **K1–K10 恰为十条**，每条是独立 OS 子进程在具名边界被 `SIGKILL`（K4 为 fixture-only SQL 错误注入），重启由**新的** `recover_worker.py` 进程完成，退出码 0；十条与 §8 十行一一对应，无跳过、无合并、无改名。2. 既有 8 个 gate 串行实跑全部退出 0：`v24/load.py`、`v24/s1/setup_db.py --self-check`、`v24/s1/test_ddl.py`、`v24/s1/test_g1.py`、`v24/s2/test_g3a.py`、`v24/s3/test_g2.py`、`v24/s4/test_g2b.py`、`v24/s5/test_g4.py`。3. `recoverable_effects` 是只读 `SECURITY DEFINER`、`STABLE`、零 DML、固定 `search_path`、固定返回列、按 `(lease_until,effect_id)` 定序、`LIMIT` 上限 16；`command_recover` 是 `SECURITY INVOKER` wrapper、无表权、恰好一次 `advance`。4. `command_recover` 一次请求/一条 receipt；同 key 同 bytes replay，同 key 异 bytes `request_conflict`；一次 sweep 至多 16 个动作、一个 delta、一个事务。5. `replay_safe` 回到 `ready` 且保留 attempt/fence；`no_replay` 结算 unknown 并完成 run/pin/预算/interaction 收敛；`manual` 不进入扫描、不消耗 16 上界。6. K4 的中间错误由 `v24_fake` 触发器注入并回滚，十表 diff 为空，产品 SQL 零改动。7. 矩阵/台账/`v24/s6/README.md` 更新；W4 一次里程碑提交（S6 只有一个里程碑）。 |
| Key files | **NEW** `v24/sql/49_recovery.sql`（`recoverable_effects`、`interpret_recover`、`unknown_wall_delta`、`command_recover`）；`v24/sql/10_schema.sql`（kind CHECK + events entity CHECK）；`v24/sql/30_advance.sql`（command body kind allowlist、candidate closure seed）；`v24/sql/40_interpreters.sql`（dispatcher、`command_recover` footprint/applier）；`v24/sql/50_permissions.sql`（两个 GRANT、DEFINER allowlist、wrapper contract）；`v24/load.py` + `v24/s1/setup_db.py`（插入 49）；`v24/s1/test_g1.py`（G1-A 重述）；`v24/s3/test_g2.py` / `v24/s4/test_g2b.py`（command kind 数组 8→9）；**NEW** `v24/s6/{README.md,g5_support.py,crash_worker.py,recover_worker.py,fake_crash_host.py,test_g5.py}`；`docs/reviews/v24-conformance-matrix-2026-10-23.md`、`docs/reviews/v24-deviation-ledger-2026-10-23.md`。 |
| Dependencies | S1：`advance` 单入口、`G` 与锁序、request/receipt/replay 优先级、`error_v1` 23 码、`c_effects_*` 约束（`10_schema.sql:94–108`）、`30_advance.sql:282–287` 的 token CAS。S2：install/fiber/episode/slot/pin 与 `resolve`。S3：run/generation/`run_pin_release_set`（`48_loop.sql:86–103`）。S4：`interpret_model_settlement`/`interpret_tool_settlement` 的 unknown wall（`48_loop.sql:543–576`、`1061–1098`）。S5：`dispose_pending`/`disposed`/`closed_at`/`resource_quiesced_at` 与 `install_disposed_ok`/`scope_closable`（`46_cleanup.sql`）。S6 不依赖 S8/S7。 |
| Size | L：4 个 W；预计新增 SQL 约 380–450 行，harness 约 800–1000 行，测试改动约 100 行；一个新增 SQL 文件。 |
| 迁移 | **无数据迁移**。DDL delta 只有两条 CHECK 重写（不新增列/表/索引）：`c_effects_kind` 加入 `command_recover`；`c_events_entity` 加入 `effect`。新函数 4 个、新 SQL 文件 1 个、loader 顺序 48→49→50。`ALTER TABLE ... DROP/ADD CONSTRAINT` 需短暂表锁，放在离线部署窗口；既有行全部满足放宽后的 CHECK，无需回填。**不新增 `claimed_at` 列**（见 D-S6-1）。 |

---

## 2. 定位与边界

### 2.1 S6 在阶段序列中的位置

pre-plan 的顺序是 **S1 → S2 → S3 → S4 → S5 → S6 → S8 → S7**（`v24-pre-plan-2026-10-23.md:30`）。S5 已把清理闭包、owner 级联、scope close 与 dispose 墓碑做完；S6 在 S5 之后、S8（spawn）与 S7（三面并发）之前。S6 不引入新的领域状态，只回答一个问题：

> 当进程在 effect 生命周期的任一提交边界死亡时，重启后的**唯一**收敛路径是什么？

答案必须能被 G5 证伪为：`resolve` + 未结算 effect 扫描 + `command_recover`（C.3）三者，且没有 recovery 表、没有 recovery 自己的 claim/lease/cursor、没有第二状态机（设计 §1.1 L18、§8 末段 L421、§10.1 L462）。

### 2.2 S5 已经冻结、S6 只消费的事实

| 事实 | 写者/位置 | S6 的用法 |
|---|---|---|
| `effects.status ∈ {ready,claimed,succeeded,failed,unknown,cancelled}`；`claimed` iff `claim_owner`/`lease_until` 非空 | `10_schema.sql:94,104` | 恢复只把 `claimed` 且过期的行作为候选；reset 时清两列即满足 CHECK |
| `fence <= attempt_no`；command kind 的 `attempt_no = 0` | `10_schema.sql:105,107` | reset 保留 attempt/fence，下一次普通 claim 递增二者（`30_advance.sql:843`） |
| `replay_policy ∈ {no_replay,replay_safe,manual}` | `10_schema.sql:99` | 恢复**只按行上的 policy 分流**，绝不采信调用方输入 |
| 结算 CAS：必须是 `claimed` 且 token 的 attempt/fence/owner 全等；终态同 digest 返回 replay，异 digest 返回 `receipt_conflict` | `30_advance.sql:269–288` | 旧 token 在 reset 后失效（`stale_claim`）；unknown 后迟到 receipt 只能是 replay/`receipt_conflict`，不得改写首次 receipt |
| claim 的过期语义：host kinds 过期后重新 claim（attempt+1/fence+1）；`model_call`/`tool_call` 过期返回 `stale_claim` 且零写 | `30_advance.sql:836–849` | S6 **不**在 recovery 里 claim；reset 后由这条既有路径重投；no_replay 永不走回 claim |
| install 三态与宿主 receipt | `40_interpreters.sql:3489–3510` | host_prepare unknown → `prepare_unknown`；host_release unknown 保持 `dispose_pending`；inspect 不置 quiesced |
| `resource_quiesced_at` 只由 success/failure 回执或 inspect known/absent 置位 | `40_interpreters.sql:3911–3912`、S5 C25 | recovery-unknown 不置位；unknown 继续挡 pin/dispose/close |
| `run_pin_release_set` 只释放 terminal run 且不被 `ready|claimed` 或 `unknown AND quiesced IS NULL` 引用的 pin | `48_loop.sql:86–103` | no_replay 的 run 收敛复用该谓词；tool unknown 传 `NULL` 让 settling effect 自己挡 pin |
| `loop_sealable`/`run_blocked_unknown` 的既有语义 | `48_loop.sql:59–82`、`543–576`、`1061–1098` | recovery-unknown 的 run 侧形状必须与之等价（W3 控制对照） |
| `install_disposed_ok`/`scope_closable` 的六条/六类义务 | `46_cleanup.sql` | K8/K9/K10 的“不得提前写 disposed/closed_at”直接复用 |
| G1-A 的 DEFINER allowlist 与可写函数闭集 | `50_permissions.sql:59–61`、`v24/s1/test_g1.py:120–151` | 新增只读 DEFINER 必须同时改两处；`advance` 仍是唯一可写 DEFINER |

### 2.3 S6 的边界（只做崩溃/恢复）

- **做**：过期 `claimed` 的唯一扫描面；`replay_safe` 的 ready 重投；`no_replay` 的 unknown 收敛；`manual` 的报告；K1–K10 的独立进程证据；恢复出处事件与 receipt；G1-A/ACL 的闭集重述。
- **不做**：不把 unknown 洗成 success/failure；不自动重放 `no_replay`；不创建 recovery 表/队列/job/lease/cursor；不新增第二个 claim 路径或第二个状态机；不做 S7 的双连接并发矩阵；不做 S8 的 spawn/child run；不改 S5 的清理偏序；不实现真实多主机接管或外部 exactly-once。
- **不重开**：`advance` 仍是唯一可写 `SECURITY DEFINER`（设计 §2、§B.3 L535–542）；`command_recover` 是 `SECURITY INVOKER`、无表权（C.3 L710）；领域写一律经 `advance`/`validate_and_apply_delta`（C.3 L716）。

### 2.4 本阶段发布/消费的合同

pre-plan 的 **C14**（恢复入口 = resolve + 未结算 effect）与 **O11**（恢复 ABI 与只读发现面）是唯一上游合同；S6 继续 S5 的局部编号，从 **C28** 起，C28–C31 是 C14/O11 的实现级细化，**不改 C1–C16 任何一条**。

| S6 编号 | 上游 | 内容 | 消费方 |
|---|---|---|---|
| C28 只读发现面 | O11、C14 | `recoverable_effects(scope,limit)`：DEFINER/STABLE/零 DML、固定列、`(lease_until,effect_id)` 定序、scope auth、排除 manual、上限 16 | W1、W2、S7 |
| C29 单命令/单 delta | C.3、C14 | `command_recover` 一次 `advance`、kind=`command_recover`、一个 request/receipt、一个 delta 内 ≤16 动作、`has_more` 仅提示 | W2、S7 |
| C30 replay_safe 重投 | B.4、C.3 | 只把过期 `replay_safe` 行置回 `ready`，清 claim_owner/lease_until，保留 attempt/fence；下一次普通 claim 递增；不建第二 claim 表 | W2、S7 |
| C31 no_replay/manual 收敛 | B.4、B.5、C.3 | no_replay 以原 claim 结算 unknown 并按 kind 完成 run/pin/预算/interaction/install 收敛；manual 只计数、不写、不占 16 上界 | W3、S7 |

**发布/消费**：发布 C28 的返回列与定序、C29 的 request/response 与 `command_recover` kind、C30 的 ready reset、C31 的 unknown receipt/provenance 与 manual 计数；消费 S1 的 `advance`/G/闭包/`error_v1`/receipt、S2 的 `resolve` 与 install 状态、S3 的 run/pin/generation、S4 的 unknown wall 与预算、S5 的 `disposed`/`closed_at`/`resource_quiesced_at`。

### 2.5 “明确不做”清单（逐条可核对）

- 不新增第十一张表、视图或物化视图；不新增 recovery/queue/lease/cursor 列。
- 不新增 `error_v1` 码；23 码闭集不变（`30_advance.sql:23–29`、`test_g1.py:174–181`）。
- 不新增可写 `SECURITY DEFINER`；`advance` 仍是唯一。
- 不让 `command_recover` 直接 `INSERT/UPDATE/DELETE` 十表；它只组装一次 `advance`。
- 不把 `manual` 自动结算；不把 `no_replay` 自动重投；不把 unknown 转成功。
- 不用同进程新建连接冒充重启；不用 `sleep` 猜顺序；不把 `has_more` 落成持久游标。
- 不做 K11 或合并窗口；G5 恰为 K1–K10，一条 §8 行一个。
- 不在本轮改产品代码；本文件是本轮唯一新增（文档）。

---

## 3. 设计 § → 工项 → G5 映射

> 规则：每个设计锚只分配给**一个** W（该 W 对该锚的收口负责）；K 列列出证明它的 G5 窗口。W2/W3 可以有“支持性改动”，但收口责任只有一个，避免同一合同两处冻结。

| 设计锚 | 内容 | 工项（唯一） | G5 K IDs |
|---|---|---|---|
| §8 L410 / C.1 K1 | command 请求已发出、COMMIT 前；无 command/request/effect 行可见；不得扫描预先提交的 command 行 | W1 | K1 |
| §8 L411 / C.1 K2 | claim COMMIT 后、IO 前；只有 `replay_safe` 可在过期后重投，否则 unknown；不得凭 lease 过期推定未执行 | W2 | K2 |
| §8 L412 / C.1 K3 | IO 完成、advance 前；同原 effect/token 重交原 outcome；无可信 receipt → unknown+obligation，不建第二 effect | W3（W2 提供 host 变体） | K3 |
| §8 L413 / C.1 K4 | advance 中途错误；单事务回滚，无领域半写/无 successor；重交原 outcome，唯一约束挡重复，不可重新 IO | W4 | K4 |
| §8 L414 / C.1 K5 | advance 已 COMMIT、应答丢失；相同 request 键/bytes replay 首次 response，不重复预算/事件/effect | W4 | K5 |
| §8 L415 / C.1 K6 | provider withdrawn、fiber 未清理；run terminal 不释放被 claimed/unknown-unquiesced 引用的 pin；不得级联 delete | W3 | K6 |
| §8 L416 / C.1 K7 | 子 fiber 已清理、父未清理；从未结算 effect 继续，或 resolve 后提交下一个控制 effect | W3 | K7 |
| §8 L417 / C.1 K8 | host_prepare IO/receipt 窗口；install 已 preparing，`fiber_control(on)` 拒绝；inspect 证明静默前不可激活 | W2 | K8 |
| §8 L418 / C.1 K9 | scope close/prepare_unknown；无 inspect 永远 closing，install 到 disposed 且无责任后方可 closed | W3 | K9 |
| §8 L419 / C.1 K10 | host CAS release 后、DB receipt 前；同 reservation inspect/reconcile；无幂等 CAS 则保留 debt 并阻 dispose | W2 | K10 |
| §8 L421 | 恢复入口唯一为 `resolve` + 未结算 effect 并重交；定时扫描不得拥有 job state/claim/lease；未知业务与未知资源分开 | W1 | K1–K10 的入口断言 |
| §9 L439 | G5：10 个 kill 点（§8 十行）重启后仅扫描 resolve 与未结算 effect 可收敛；幂等 response 相同 | W4 | K1–K10 |
| §9.1 L446 | G5 的重启证据 = 每个 kill 点独立 OS 子进程 + 持久 journal；同进程新建连接不算 | W4 | K1–K10 的 harness |
| §10.2 D1 L466 | 外部 effect 可信度依赖受信 host + durable journal + fake crash gate；丢 receipt 且无查询 → unknown | W4 | K3/K5/K10 的 journal 证据 |
| §10.2 D2 L468 | Host CAS 与 PG 无原子事务；稳定 reservation、幂等 CAS、inspect/reconcile；否则保留 debt 阻 dispose | W2 | K10 |
| §10.2 D4 L472 | cancel 不保证停止已发外呼；保留 claimed/cancel_requested/迟到事实/unknown | W3 | K3（cancel-late 变体） |
| §B.3 L535–542 | `advance` 唯一写函数；EXECUTE 只授受信 service role；调用者不得直接写十表 | W2 | K1/K5 的零写 |
| §B.3 L544–546 | `resolve`/`poll`/`wait_check` 的只读形状；无权对象统一 `not_found_or_denied` | W1 | K1 的读面 |
| §B.3 L548–552 | 四个写 verb wrapper 无表权、只调 advance；helper 校验不是持久裁决 | W2 | K5 |
| §B.3 L554–556 | 23 码闭集；可恢复错误零写；有效 command 的失败作为 receipt 原子记录 | W2 | 全部负例 |
| §B.4 L560–562 | attempt/fence 单调；claim_owner=session_user；lease 只用于判断何时 inspect/unknown/reclaim，不是“未执行”证明 | W2 | K2/K3 |
| §B.4 L564–566 | 一个最终 outcome；同 digest replay，异 digest `receipt_conflict`；late outcome 不能发布 successor | W3 | K3 的 late receipt |
| §B.4 L568–576 | replay_safe 是 adapter 版本绑定声明；no_replay 过期直接 unknown；manual 需治理命令；model 供应商默认 manual/no_replay | W3 | K2/K3 |
| §B.4 L578–580 | host reservation 由 advance 确定性绑定 effect_id；host journal 以 reservation 唯一；inspect 只清资源、不改业务 outcome | W2 | K8/K10 |
| §B.5 L584–588 | command 不存在→settled；successor 不存在→ready；外部 ready→claimed→succeeded/failed/unknown | W2 | K2/K5 |
| §B.5 L590–592 | ready 可转 cancelled；claimed 只能标 cancel_requested，需原结果/inspect/unknown 收束；失败分无写与 failed receipt | W3 | K3 |
| 附录 C.1 L660–677 | K1–K10 十行表与负面证据规则（不得扫描预提交 command、不得以 lease 推定未执行、不得第二 effect、unknown 不转成功/不自动续链） | W4 | K1–K10 |
| 附录 C.3 L710–717 | `command_recover` INVOKER/无表权；`recoverable_effects` 只读 DEFINER；G 下发现、policy 分流、≤16、has_more 提示、event+receipt 出处、无第二状态机 | W2 | K2/K5/K8/K10 |
| 附录 C.4 L721–730 | R6 四裁决：10 kill 点、S6→S8→S7、command_recover、独立进程证据 | W4 | 计划级 |

---

## 4. 函数与 DDL 草案

### 4.0 文件、加载顺序与 DDL delta

`v24/sql/49_recovery.sql`（**NEW**）承载四个对象：`recoverable_effects`（只读 DEFINER）、`unknown_wall_delta`（纯 helper，INVOKER/STABLE）、`interpret_recover`（INVOKER）、`command_recover`（INVOKER wrapper）。加载顺序固定为：

```text
00 → 10 → 20 → 30 → 40 → 45 → 46 → 47 → 48 → 49_recovery → 50
```

`v24/load.py` 的 `CANONICAL_ORDER`/`SQL_LOAD_ORDER` 与 `v24/s1/setup_db.py:_self_check` 的 `expected_canonical` 同步插入 `"49_recovery.sql"`；loader 的“未登记文件即拒绝”与“canonical prefix”规则不变。`50_permissions.sql` 仍是最后，保证 fail-closed `DO` 块在全部函数存在后检查 owner/`search_path`/PUBLIC。

仓库内直接改 `10_schema.sql` 的两条 CHECK（每个 gate 都是新库）；已部署库的等价迁移是：

```sql
ALTER TABLE v24.effects DROP CONSTRAINT c_effects_kind;
ALTER TABLE v24.effects ADD CONSTRAINT c_effects_kind CHECK (kind IN (
  'command_start','command_cancel','command_steer','command_respond',
  'command_install','command_fiber_control','command_dispose','command_scope_control',
  'command_recover',
  'model_call','tool_call','host_prepare','host_release','inspect_resource','fiber_reconcile'));

ALTER TABLE v24.events DROP CONSTRAINT c_events_entity;
ALTER TABLE v24.events ADD CONSTRAINT c_events_entity CHECK (
  entity_type IN ('scope','run','fiber','episode','slot','install','pin','request','effect'));
```

不新增列、表、索引或数据回填。`command_recover` 是 command kind，因此 `c_effects_command_claim`（`10_schema.sql:107`）要求其 `attempt_no=0`；通用 command 插入路径（`40_interpreters.sql:2196–2202`）默认 attempt 0，满足。`events.entity_type='effect'` 只用于 recovery 的逐 action 出处事件（§4.5）；`events` 的 append-only 触发器不变。

**kind 闭集的完整接线**（CC-1）：`10_schema.sql` 的 CHECK、设计 §3.1.3/附录 A.1 的闭集文本、`30_advance.sql:186–188` 的 command kind allowlist、`40_interpreters.sql:42–66` 的 dispatcher、`validate_and_apply_delta` 的 footprint、`50_permissions.sql` 的 wrapper contract、`test_g1.py` 的 wrapper 元组、`test_g2.py`/`test_g2b.py` 的 command kind 数组。`chat_tool_v1` 的 schema digest **不变**：新 kind 是协议命令，不进入模型输入/输出 schema（设计 §5.4 的三枚 digest 只覆盖 policy/schema/toolset）。

### 4.1 `v24.recoverable_effects`：唯一的只读发现面

```sql
CREATE FUNCTION v24.recoverable_effects(p_scope uuid, p_limit integer DEFAULT 16)
RETURNS TABLE(
  effect_id     uuid,
  kind          text,
  replay_policy text,
  attempt_no    bigint,
  fence         bigint,
  claim_owner   text,
  lease_until   timestamptz
)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, v24
AS $$
  -- Read-only discovery: claimed rows whose lease is already past, oldest
  -- expiry first, then effect UUID bytes.  Scope authorization uses the real
  -- session login, never a caller argument.  NULL or sub-1 limits yield no
  -- rows; a limit above sixteen is capped at sixteen.
  SELECT e.effect_id, e.kind, e.replay_policy, e.attempt_no, e.fence,
         e.claim_owner, e.lease_until
    FROM v24.effects e
    JOIN v24.scopes  s ON s.scope_id = e.scope_id
   WHERE e.scope_id = p_scope
     AND e.status = 'claimed'
     AND e.lease_until <= now()
     AND e.kind IN ('host_prepare','host_release','inspect_resource',
                    'model_call','tool_call')
     AND e.replay_policy <> 'manual'
     AND (s.owner_principal = v24.principal_id(session_user)
          OR pg_catalog.pg_has_role(session_user, 'v24_admin', 'USAGE'))
   ORDER BY e.lease_until, e.effect_id
   LIMIT greatest(least(coalesce(p_limit, 0), 16), 0)
$$;
```

| 语义 | 冻结值 | 理由 |
|---|---|---|
| 安全属性 | `SECURITY DEFINER`，owner `v24_owner`，`STABLE`，零 DML，`SET search_path = pg_catalog, v24`，无动态 SQL，无 caller 表名/列名 | C.3 L711；G1-A 读 DEFINER 闭集 |
| 返回列 | 恰 7 列（上表）；不返回 `request`/`outcome`/`run_id`/`install_id` | 最小读面；调用方只需要 id + 出处字段；payload 由 `interpret_recover` 在 G 下读 |
| 候选集 | `status='claimed' AND lease_until <= now()`；kind 闭集 5 个；`replay_policy <> 'manual'` | 设计 §8 L411/L412、C.3 L711；manual 不进扫描（D-S6-3） |
| 定序 | `ORDER BY lease_until, effect_id` | **`effects` 没有 `claimed_at` 列**（`10_schema.sql:67–109` 只有 `created_at`/`settled_at`/`lease_until`）；最早到期优先 + UUID 升序是确定全序，零 DDL（D-S6-1） |
| `p_limit` | `NULL`/`<1` → 0 行；`1..16` → 该值；`>16` → 16 | 防御式 clamp；公开 wrapper 对同样输入返回 `invalid_args`（§4.2），两层行为都定义 |
| scope auth | `scopes.owner_principal = principal_id(session_user)` 或 `pg_has_role(session_user,'v24_admin','USAGE')`；不匹配返回 0 行 | 不泄露 scope 存在性；权威裁决在 `advance`（D-S6-6） |
| 禁用词 | 函数体与注释不得出现 `insert`/`update`/`delete`/`pg_advisory*` 任一单词 | `50_permissions.sql:94–98` 的 regex 扫描 `prosrc`，**注释也算**；G1-A 同样扫描 `pg_get_functiondef` |

**关于 `claimed_at` 的显式裁决（D-S6-1）**：C.3 L711 的“确定序 `(claimed_at, effect_id)`”引用了一个不存在的列。本计划**不**新增 `claimed_at`（那会改十表数据模型并触发设计修订），改用 `(lease_until, effect_id)`：租约到期越早越先处理，同一 `lease_until` 用 UUID 字节序打破平局；这是一个确定全序，且与“过期 claim 优先”语义一致。`created_at` 不能替代：它是 effect 创建时间，不是 claim 时间。精确替换文本见 §8 D-S6-1。

### 4.2 `v24.command_recover`：一次 `advance` 的 INVOKER wrapper

#### 4.2.1 签名与函数体

> 设计 C.3 写的是 `command_recover(p_scope, p_limit DEFAULT 16)`；本计划必须再加 `p_request_key` 才能有 request/receipt。PostgreSQL 不允许“有默认值的参数后面再跟无默认值参数”，因此冻结为 `(p_scope uuid, p_request_key text, p_limit integer DEFAULT 16)`。这是 D-S6-5，不改变语义，只修正可执行签名。

```sql
CREATE FUNCTION v24.command_recover(
  p_scope uuid,
  p_request_key text,
  p_limit integer DEFAULT 16
) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER
SET search_path = pg_catalog, v24
AS $$
DECLARE
  v_candidates jsonb;
  v_payload    jsonb;
  v_effect_id  uuid;
BEGIN
  -- Local shape only.  Authorization, epoch, and replay are advance's job.
  IF p_scope IS NULL
     OR p_request_key IS NULL
     OR length(p_request_key) NOT BETWEEN 1 AND 512
     OR p_limit IS NULL OR p_limit < 1 OR p_limit > 16 THEN
    RETURN v24.error_v1('invalid_args');
  END IF;

  -- Advisory pre-read: the frozen hint.  It is deliberately NOT part of
  -- canonical_bytes (see CC-2); the interpreter re-discovers under G.
  SELECT coalesce(jsonb_agg(to_jsonb(r.effect_id) ORDER BY r.effect_id), '[]'::jsonb)
    INTO v_candidates
    FROM v24.recoverable_effects(p_scope, p_limit) AS r;

  v_payload := jsonb_build_object('v', 1, 'scope_id', p_scope, 'limit', p_limit);
  v_effect_id := v24.effect_id_for(
    v24.principal_id(session_user), p_request_key, 'command_recover');

  RETURN v24.advance(
    v_effect_id,
    jsonb_build_object(
      'v', 1, 'class', 'command', 'claim', NULL,
      'body', jsonb_build_object(
        'op', 'admit_and_apply',
        'kind', 'command_recover',
        'request_key', p_request_key,
        'payload', v_payload,
        'candidates', v_candidates,
        'canonical_bytes',
          encode(convert_to(v24.canonical_json(v_payload), 'UTF8'), 'base64'))));
END;
$$;
```

wrapper 的性质：`SECURITY INVOKER`、无表权、恰好一次 `v24.advance(` 调用、无 `INSERT INTO`/`UPDATE v24.`/`DELETE FROM`/`pg_advisory_xact_lock`、无 `SECURITY DEFINER`。`recoverable_effects` 是它唯一的表读入口；它不读 `requests`/`effects` 来“猜”上次响应。

#### 4.2.2 request 的规范字节、digest 与 effect id

| 项 | 冻结值 |
|---|---|
| payload | `{"v":1,"scope_id":"<uuid>","limit":<1..16>}`（`jsonb_build_object`，键序由 jsonb 规范输出） |
| canonical bytes | `convert_to(v24.canonical_json(payload),'UTF8')`；`v24.canonical_json` 是 `jsonb::text`（`30_advance.sql:4–6`） |
| request digest | `sha256(canonical_bytes)`，由 `advance`/applier 计算（`40:1834–1835`），wrapper 不预计算 |
| effect id | `v24.effect_id_for(principal_id(session_user), p_request_key, 'command_recover')` = `substr(sha256(principal||':command_recover:'||request_key),1,32)::uuid`（`30_advance.sql:12–17`） |
| body.candidates | 由 `recoverable_effects` 得到、按 `effect_id` 升序、去重、≤16 的 UUID 字符串数组；**不进入 canonical_bytes/digest** |
| 为什么 candidates 不进 digest | 如果候选集进 digest，commit 丢应答后重试会重新发现“空集”，得到不同 bytes，`advance` 在 `30:252–260` 直接返回 `request_conflict`，**wrapper 自己的重试永远无法 replay**；这会把 K5 类“commit 后应答丢失”变成 S6 的自身缺陷（CC-2、D-S6-9） |
| candidates 的地位 | 与 `receipt_key` 同类：传输/审计元数据，不参与匹配（`30:121–122,270–271` 的先例）；同 key 不同 candidates 仍 replay 首次 response，因为请求决策（scope+limit）相同 |

#### 4.2.3 一次 `advance` 的架构裁决（CC-1）

C.3 L710–712 的字面写法是“先 `recoverable_effects` 发现候选，再把**每个** recovery 动作经 `advance` 提交”，即 N 次 `advance`。本计划冻结为**一次** `advance`，理由是可证伪的三条：

1. **一个 request/receipt**：N 次 `advance` 会产生 N 条 command effect 与 N 条 request 行（`40:2196–2204` 每次 command 都插入一对），无法满足“一次 sweep 一个 request/receipt”的验收；即使调用方把 N 次调用包在同一事务里，request 行仍是 N 条，`has_more`/sweep 级出处也没有唯一承载者。
2. **逐 action 的 recovery 出处**：一次 `advance` 的 `p_effect_id` 是唯一的 recovery `request_key` 归属；每个 action 的 `effect` 事件可以写 `effect_id=<target>`、payload 带 `recovery_effect_id=<command>`，出处闭合。N 次调用下每个 action 属于不同 command，sweep 级 `candidates/applied/skipped/has_more` 无处原子记录。
3. **`replay_safe` 回 `ready` 与 receipt 同事务**：reset 必须与“本次 sweep 的 receipt/事件”同事务提交（N2）；一次 delta 才能保证“要么整个 sweep 的 ≤16 个 reset/unknown 一起可见，要么全回滚”。N 次调用若分事务提交，崩溃在中间会留下半 sweep 且没有 sweep receipt。

因此新增 kind `command_recover`，由 `interpret_recover` 在 `advance` 的 G 内重发现并返回**一个** delta。这是 CC-1，Oracle 已 ACCEPT（chat 028D07，§8.3）；§8.4 的 fallback 仅为历史备选。

**历史备选（未采用；CC-1 已批准）**：若 CC-1 被否决，只能退回 N 次 `advance`。它精确地失败于：① 不是一个 request/receipt（N 条 request，违反 C.3 L714 的“一个有界事务”下的单命令语义与本计划的 Done when 4）；② 没有 sweep 级 `has_more`/`candidates` 的原子出处；③ `replay_safe` 的 `ready` reset 无法与“sweep receipt”同事务，崩溃在 N 次之间会留下无 receipt 的 reset。结论：fallback 不满足 S6 验收；CC-1 已批准（028D07），本计划不实现该路径。

#### 4.2.4 response JSON

```json
{
  "v": 1,
  "disposition": "committed",
  "effect_id": "<command_recover effect id>",
  "emitted": [],
  "revision": 0,
  "claim": null,
  "recovery": {
    "scope_id": "<uuid>",
    "limit": 16,
    "candidates": ["<uuid>", "..."],
    "applied": [
      {"effect_id": "<uuid>", "kind": "host_prepare", "replay_policy": "replay_safe",
       "action": "reset_ready", "reason": "lease_expired",
       "attempt_no": 2, "fence": 2, "run_id": null, "install_id": "<uuid>"}
    ],
    "skipped": [
      {"effect_id": "<uuid>", "reason": "not_claimed"}
    ],
    "manual_debt": 0,
    "has_more": false
  }
}
```

- `applied[].action ∈ {reset_ready, settle_unknown}`；`reason ∈ {lease_expired, cancel_requested, install_not_preparing, state_mismatch}`。
- `skipped[].reason ∈ {not_claimed, not_expired, manual, kind_unsupported, state_mismatch}`；`manual` 不会出现在 `candidates`（被发现面排除），此分支只是防御。
- `emitted` 恒为 `[]`：recovery 不发 successor（无第二 effect）；`revision` 恒 0（命令 effect 自身）。
- `manual_debt` 是 scope 内 `claimed` 且过期但 `replay_policy='manual'` 的计数；只读计数，不写、不占 16 上界、不影响 `has_more`。
- `has_more = EXISTS(同 scope 内非 manual、claimed、lease_until<=now()、且 effect_id 不在本次 applied 的集合)`；它是**本次调用的返回提示**，不是游标/队列/状态（§5 负例 N9）。
- 同 key 同 bytes 的 replay 由 `advance` 在 `30:255–260` 直接返回 `requests.response`，逐字节相同；同 key 不同 `scope_id`/`limit` 返回 `request_conflict`（W0）。同 key 不同 `candidates` 仍 replay（CC-2）。

### 4.3 `v24.interpret_recover`：G 下的唯一恢复解释器

`interpret_recover` 是 `SECURITY INVOKER`、`SET search_path = pg_catalog, v24`、无表权的解释器；它只读输入、返回 delta，不直接更新表（设计 §2.3 第 5 步、§B.5）。它由 `interpret_command` 的 dispatcher 在 `command_scope_control` 分支之前调用。

#### 4.3.1 执行顺序（固定，不得交换）

1. **形状/admission**：`body.kind='command_recover'`；`payload` 恰为 `{v,scope_id,limit}`；`candidates` 是 ≤16 个 UUID 字符串、去重、按 UUID 升序；`limit` 1..16。任一不符 → `{write:false,error:invalid_args}`（W0，不建 command effect/request）。
2. **scope 认证**：`SELECT * FROM v24.scopes WHERE scope_id = payload.scope_id FOR UPDATE`；不存在，或 `owner_principal <> principal_id(session_user)` 且非 `v24_admin` → `{write:false,error:not_found_or_denied}`（W0）。这条在 G 内，且先于任何目标行写。
3. **锁/重发现**：`advance` 的 closure 已按 `body.candidates` 锁住候选 effect 及其 scope/run/install/fiber/episode/pin（§4.6.1）；本函数对 `effect_id = ANY(candidates)` 且 `scope_id = p_scope` 的行再读一次，按 `(lease_until, effect_id)` 排序。**权威集合是这次 G 下重读**，不是 wrapper 的 hint：hint 中已结算/未过期的行被 `skipped:not_claimed`；hint 之外新过期的行本次**不处理**，只让 `has_more=true`，留给下一个 key。
4. **按行分类**：只读 `effects.replay_policy`/`effects.kind`/`effects.cancel_requested`/install 投影，绝不读调用方传入的 policy/action。
5. **应用**：`reset_ready` 或 `settle_unknown`；每个动作写一条 `effect` 事件；no_replay 的 run 侧动作由 `unknown_wall_delta` 生成；host_prepare 的 install 投影在同 delta 写。
6. **汇总**：`manual_debt`、`has_more`、`applied`、`skipped`；返回一个 delta（`domain.update` 的 `effects/runs/pins/installs`、`effect`=command effect、`request.response`、`events`、`successors=[]`、无 `settle`）。

#### 4.3.2 函数形状

```sql
CREATE FUNCTION v24.interpret_recover(p_effect_id uuid, p_principal uuid,
  p_outcome jsonb, p_closure jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER
SET search_path = pg_catalog, v24
AS $$
DECLARE
  v_body     jsonb := p_outcome->'body';
  v_payload  jsonb := v_body->'payload';
  v_scope    v24.scopes%ROWTYPE;
  v_limit    int;
  v_cand     uuid[];
  v_e        v24.effects%ROWTYPE;
  v_action   text;
  v_reason   text;
  v_effects  jsonb := '[]'::jsonb; v_runs jsonb := '[]'::jsonb;
  v_pins     jsonb := '[]'::jsonb; v_installs jsonb := '[]'::jsonb;
  v_events   jsonb := '[]'::jsonb; v_applied jsonb := '[]'::jsonb;
  v_skipped  jsonb := '[]'::jsonb;
  v_manual   int := 0; v_more boolean := false;
  v_frag     jsonb; v_response jsonb; v_rows int := 0;
BEGIN
  IF v_body->>'kind' IS DISTINCT FROM 'command_recover'
     OR jsonb_typeof(v_payload) IS DISTINCT FROM 'object'
     OR NOT (v_payload ?& ARRAY['v','scope_id','limit'])
     OR EXISTS (SELECT 1 FROM jsonb_object_keys(v_payload) k
                 WHERE k NOT IN ('v','scope_id','limit'))
     OR (v_payload->>'v') IS DISTINCT FROM '1' THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_args'));
  END IF;
  BEGIN
    v_limit := (v_payload->>'limit')::int;
    SELECT * INTO v_scope FROM v24.scopes
      WHERE scope_id = (v_payload->>'scope_id')::uuid FOR UPDATE;
  EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_args'));
  END;
  IF NOT FOUND OR (v_scope.owner_principal IS DISTINCT FROM p_principal
                   AND NOT pg_catalog.pg_has_role(session_user,'v24_admin','USAGE')) THEN
    RETURN jsonb_build_object('write',false,'error',
      v24.error_v1('not_found_or_denied'));
  END IF;
  IF v_limit NOT BETWEEN 1 AND 16
     OR jsonb_typeof(v_body->'candidates') IS DISTINCT FROM 'array'
     OR jsonb_array_length(v_body->'candidates') > v_limit THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_args'));
  END IF;
  BEGIN
    v_cand := ARRAY(SELECT value::uuid
                      FROM jsonb_array_elements_text(v_body->'candidates') value);
  EXCEPTION WHEN invalid_text_representation THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_args'));
  END;
  IF cardinality(v_cand) <> (SELECT count(DISTINCT x) FROM unnest(v_cand) x)
     OR v_cand <> (SELECT array_agg(x ORDER BY x) FROM unnest(v_cand) x) THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_args'));
  END IF;

  FOR v_e IN
    SELECT e.* FROM v24.effects e
     WHERE e.effect_id = ANY(v_cand) AND e.scope_id = v_scope.scope_id
     ORDER BY e.lease_until, e.effect_id
     FOR UPDATE
  LOOP
    IF v_e.status <> 'claimed' OR v_e.lease_until > now() THEN
      v_skipped := v_skipped || jsonb_build_array(jsonb_build_object(
        'effect_id',v_e.effect_id,'reason','not_claimed'));
      CONTINUE;
    END IF;
    IF v_e.replay_policy = 'manual' THEN
      v_skipped := v_skipped || jsonb_build_array(jsonb_build_object(
        'effect_id',v_e.effect_id,'reason','manual'));
      CONTINUE;
    END IF;
    IF v_e.kind NOT IN ('host_prepare','host_release','inspect_resource',
                        'model_call','tool_call') THEN
      v_skipped := v_skipped || jsonb_build_array(jsonb_build_object(
        'effect_id',v_e.effect_id,'reason','kind_unsupported'));
      CONTINUE;
    END IF;

    v_action := NULL; v_reason := NULL;
    IF v_e.cancel_requested THEN
      v_action := 'settle_unknown'; v_reason := 'cancel_requested';
    ELSIF v_e.replay_policy = 'replay_safe' AND v_e.kind = 'host_prepare' THEN
      IF EXISTS (SELECT 1 FROM v24.installs i
                  WHERE i.install_id = (v_e.request->>'install_id')::uuid
                    AND i.state = 'preparing') THEN
        v_action := 'reset_ready'; v_reason := 'lease_expired';
      ELSE
        v_action := 'settle_unknown'; v_reason := 'install_not_preparing';
      END IF;
    ELSIF v_e.replay_policy = 'replay_safe' AND v_e.kind = 'host_release' THEN
      IF EXISTS (SELECT 1 FROM v24.installs i
                  WHERE i.install_id = (v_e.request->>'install_id')::uuid
                    AND i.state = 'dispose_pending') THEN
        v_action := 'reset_ready'; v_reason := 'lease_expired';
      ELSE
        v_action := 'settle_unknown'; v_reason := 'state_mismatch';
      END IF;
    ELSIF v_e.replay_policy = 'replay_safe' AND v_e.kind = 'inspect_resource' THEN
      v_action := 'reset_ready'; v_reason := 'lease_expired';
    ELSIF v_e.replay_policy = 'no_replay'
          AND v_e.kind IN ('model_call','tool_call') THEN
      v_action := 'settle_unknown'; v_reason := 'lease_expired';
    ELSE
      v_skipped := v_skipped || jsonb_build_array(jsonb_build_object(
        'effect_id',v_e.effect_id,'reason','kind_unsupported'));
      CONTINUE;
    END IF;

    IF v_action = 'reset_ready' THEN
      v_effects := v_effects || jsonb_build_array(jsonb_build_object(
        'key',jsonb_build_object('effect_id',v_e.effect_id),
        'set',jsonb_build_object('status','ready',
                                 'claim_owner',NULL,'lease_until',NULL)));
      v_events := v_events || jsonb_build_array(jsonb_build_object(
        'entity_type','effect','entity_id',v_e.effect_id,
        'event_kind','effect_recovered_replay',
        'payload',jsonb_build_object(
          'effect_id',v_e.effect_id,'kind',v_e.kind,
          'replay_policy',v_e.replay_policy,'action','reset_ready',
          'reason',v_reason,'attempt_no',v_e.attempt_no,'fence',v_e.fence,
          'claim_owner',v_e.claim_owner,'recovery_effect_id',p_effect_id,
          'recovery_request_key',v_body->>'request_key')));
    ELSE
      v_frag := v24.unknown_wall_delta(v_e.effect_id, v_reason);
      IF v_frag ? 'error' THEN
        RETURN jsonb_build_object('write',false,'error',v_frag->'error');
      END IF;
      v_effects := v_effects || (v_frag->'effects');
      v_runs := v_runs || coalesce(v_frag->'runs','[]'::jsonb);
      v_pins := v_pins || coalesce(v_frag->'pins','[]'::jsonb);
      v_installs := v_installs || coalesce(v_frag->'installs','[]'::jsonb);
      v_events := v_events || (v_frag->'events');
    END IF;
    v_applied := v_applied || jsonb_build_array(jsonb_build_object(
      'effect_id',v_e.effect_id,'kind',v_e.kind,
      'replay_policy',v_e.replay_policy,'action',v_action,'reason',v_reason,
      'attempt_no',v_e.attempt_no,'fence',v_e.fence,
      'run_id',v_e.run_id,
      'install_id',(v_e.request->>'install_id')::uuid));
    v_rows := v_rows + 1;
    IF v_rows >= 16 THEN EXIT; END IF;
  END LOOP;

  SELECT count(*) INTO v_manual FROM v24.effects e
   WHERE e.scope_id = v_scope.scope_id AND e.status = 'claimed'
     AND e.lease_until <= now() AND e.replay_policy = 'manual'
     AND e.kind IN ('host_prepare','host_release','inspect_resource',
                    'model_call','tool_call');
  SELECT EXISTS (
    SELECT 1 FROM v24.effects e
     WHERE e.scope_id = v_scope.scope_id AND e.status = 'claimed'
       AND e.lease_until <= now() AND e.replay_policy <> 'manual'
       AND e.kind IN ('host_prepare','host_release','inspect_resource',
                      'model_call','tool_call')
       AND e.effect_id <> ALL (coalesce(
             ARRAY(SELECT (a->>'effect_id')::uuid
                     FROM jsonb_array_elements(v_applied) a), '{}'::uuid[])))
    INTO v_more;

  -- The applier rejects duplicate (entity_type,entity_id,event_kind); keep the
  -- first occurrence in deterministic order.
  SELECT coalesce(jsonb_agg(ev ORDER BY ord),'[]'::jsonb) INTO v_events
    FROM (SELECT DISTINCT ON (e->>'entity_type',e->>'entity_id',e->>'event_kind')
                 e AS ev, ord
            FROM jsonb_array_elements(v_events) WITH ORDINALITY t(e,ord)
           ORDER BY e->>'entity_type',e->>'entity_id',e->>'event_kind',ord) d;

  v_response := jsonb_build_object(
    'v',1,'disposition','committed','effect_id',p_effect_id,
    'emitted','[]'::jsonb,'revision',0,'claim',NULL,
    'recovery',jsonb_build_object(
      'scope_id',v_scope.scope_id,'limit',v_limit,
      'candidates',v_body->'candidates',
      'applied',v_applied,'skipped',v_skipped,
      'manual_debt',v_manual,'has_more',v_more));

  RETURN jsonb_build_object(
    'write',true,
    'domain',jsonb_build_object('update',jsonb_build_object(
      'effects',v_effects,'runs',v_runs,'pins',v_pins,'installs',v_installs)),
    'effect',jsonb_build_object('status','succeeded','outcome',p_outcome),
    'request',jsonb_build_object('response',v_response),
    'events',v_events,
    'successors','[]'::jsonb);
END;
$$;
```

#### 4.3.3 delta 键、上限与事件

| 项 | 冻结值 | 理由 |
|---|---|---|
| `domain.insert` | 恒 `{}` | recovery 不建新领域行；唯一新行是 command effect 自身（applier 统一插入） |
| `domain.update.effects` | ≤16 行；列只允许 `status,claim_owner,lease_until,outcome,settled_at` | reset 只清两列；unknown 写 receipt/settled_at；不得改 attempt/fence/request/request_digest/kind |
| `domain.update.runs` | ≤16 行；列只允许 `status,turn_no,remaining_steps,remaining_tokens,remaining_tool_calls,remaining_wall_ms,interaction,pending_steer,close_intent,result,revision,ended_at,updated_at` | 与 `interpret_model_settlement`/`interpret_tool_settlement` 的 unknown 分支同列（`48:913–929`、`1355–1372`） |
| `domain.update.pins` | ≤16 行；列只允许 `released_at,released_by_effect` | `run_pin_release_set` 的输出形状（`48:89–93`） |
| `domain.update.installs` | ≤16 行；列只允许 `state,disposed_at` | host_prepare unknown → `prepare_unknown`；host_release known/absent 的 disposed 由后续 settlement 完成，不在 recovery 里越权 |
| `events` | ≤64；entity_type ∈ `effect|run|install|scope`；同 `(entity_type,entity_id,event_kind)` 不重复 | applier 的既有去重校验（`40:589–593`）；逐 action `effect` 事件 + 每 run 最多一条 unknown 事件 |
| `successors` | 恒 `[]` | 恢复不发布业务后继（设计 §8 L412、C.3 L715） |
| `settle` | 禁止出现 | `settle` 只用于 `fiber_reconcile`（`40:2225–2234`），recovery 不用 |
| updates 总上限 | **64**（16 effects + 16 runs + 16 pins + 16 installs） | 现有非 cancel/steer 的 16 上限是给单类写的；recovery 需要四类行，64 仍是有界且可逐类断言（§4.6.2） |
| events 去重 | 同 entity/kind 只保留首个（按 `(lease_until,effect_id)` 序） | 同一 sweep 只有一个 writer effect，多个 tool 同 run 的 `tool_call_unknown` 会撞 `(effect_id,entity_type,entity_id,event_kind)`；effect 级事件仍逐 action 保留 |

### 4.4 `replay_safe` 的精确处置：只回 `ready`，不 claim、不 re-IO

| kind | install 投影（G 下判） | action | 下一次普通 claim 后 | settlement 端点 |
|---|---|---|---|---|
| `host_prepare` | `preparing` | `reset_ready` | attempt+1/fence+1；adapter 用同一 reservation 重投 | success→`installed`；failure→`prepare_failed`；unknown→`prepare_unknown`（`40:3489–3495`） |
| `host_prepare` | `prepare_unknown`/`installed`/`dispose_pending` | `settle_unknown`（`install_not_preparing`） | 不 claim、不 IO | effect=unknown；install 不变；资源债留给 S5 的 inspect/dispose |
| `host_release` | `dispose_pending` | `reset_ready` | attempt+1/fence+1；同 reservation | success→`disposed`；failure/unknown→保持 `dispose_pending`（`40:3498–3510`） |
| `host_release` | 其他状态 | `settle_unknown`（`state_mismatch`） | 不 claim、不 IO | effect=unknown；install 不变 |
| `inspect_resource` | 目标仍 `unknown` 且 `resource_quiesced_at IS NULL` | `reset_ready` | attempt+1/fence+1；同 reservation | known/absent→C25 矩阵；unknown→不置 quiesced（`40:3444–3488`） |
| 任一 host kind | `cancel_requested=true` | `settle_unknown`（`cancel_requested`） | 不 claim、不 IO | 保持取消/资源债；不把 unknown 洗成成功（B.5 L590） |

**为什么 reset 保留 attempt/fence**：

1. `advance` 的 claim 路径只在该路径内递增（`30:843`）。recovery 若自己递增，就成了第二个 claim 写者，违反“唯一 claim 路径”（设计 §1.1 L18、§B.4 L560）。
2. reset 只清 `claim_owner`/`lease_until`，旧 claim 的 `attempt_no/fence` 仍与 host journal 的记录对应；K3 的“同 token 重交”在 sweep 之前仍可正常结算。若 recovery 立即 bump，旧 token 会更早失效，host 的迟到 receipt 只能变成 `stale_claim`/`receipt_conflict`，缩小了 K3 的合法窗口。
3. 下一个普通 claim 会做 `attempt+1/fence+1`，旧 token 在那一刻起必然 `stale_claim`；这是既有的“新 attempt 实际替代旧 claim 才递增 fence”语义（§B.4 L560）。
4. reset **不**写 `resource_quiesced_at`：reset 不是静默证明；unknown 资源继续挡 pin/dispose/close（S5 谓词）。

**不重复 IO 的证明（gate 断言）**：

- `FakeHost.prepare` 以 `payload->>'reservation'` 查 `v24_fake.journal`；命中即返回首次结果，**不再插入第二行**（`v24/s1/fake_host.py:43–49`）。S6 的 `fake_crash_host.release()/inspect()` 复制同一查找-复用逻辑。
- reset 后的第一次 claim 使用新的 attempt/fence，但 reservation 仍绑定同一个 `effect_id`（B.4 L578）；host journal 的 `UNIQUE(effect_id,attempt,fence)` 加 reservation 查询共同证明：同一 reservation 只有一行外部动作。
- gate 断言 `SELECT count(*) FROM v24_fake.journal WHERE payload->>'reservation'=<r>` 在 reset 前后都为 1；并断言 host 侧 JSONL 中同一 reservation 只有一条 `started` 且 `finished` 只出现一次。
- 旧 token 的迟到 settlement 在 reset 后返回 `stale_claim` 且十表零写（`30:282–287`）；这不是“丢失事实”，而是“该 token 不再是当前资格”，host 的 receipt 仍在 journal 里，下一次 claim 的 replay_safe 调用会复用它。

### 4.5 `no_replay` 的精确处置：unknown + run/pin/预算/interaction/install 收敛

#### 4.5.1 `v24.unknown_wall_delta`（纯 helper）

```sql
CREATE FUNCTION v24.unknown_wall_delta(p_effect_id uuid, p_reason text)
RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY INVOKER
SET search_path = pg_catalog, v24
AS $$
DECLARE
  e v24.effects%ROWTYPE;
  r v24.runs%ROWTYPE;
  v_status text;
  v_close jsonb;
  v_result jsonb;
  v_events jsonb := '[]'::jsonb;
  v_pins jsonb := '[]'::jsonb;
  v_outcome jsonb;
  v_late boolean;
  v_installs jsonb := '[]'::jsonb;
  v_interaction jsonb;
  v_pending jsonb;
  v_ended timestamptz;
  v_turn bigint;
  v_revision bigint;
BEGIN
  SELECT * INTO e FROM v24.effects WHERE effect_id = p_effect_id;
  IF NOT FOUND OR e.kind NOT IN ('model_call','tool_call',
                                 'host_prepare','host_release','inspect_resource')
     OR e.status <> 'claimed' THEN
    RETURN jsonb_build_object('error',v24.error_v1('invalid_outcome'));
  END IF;

  v_outcome := jsonb_build_object(
    'v',1,'class','unknown',
    'claim',jsonb_build_object('attempt',e.attempt_no,'fence',e.fence,
                               'owner',e.claim_owner),
    'body',jsonb_build_object('kind',e.kind,
      'result',jsonb_build_object('v',1,'observed','unknown',
        'reason',p_reason,
        'recovery',jsonb_build_object('effect_id',e.effect_id,
          'attempt_no',e.attempt_no,'fence',e.fence))));

  IF e.kind IN ('host_prepare','host_release','inspect_resource') THEN
    IF e.kind = 'host_prepare'
       AND EXISTS (SELECT 1 FROM v24.installs i
                    WHERE i.install_id = (e.request->>'install_id')::uuid
                      AND i.state = 'preparing') THEN
      v_installs := jsonb_build_array(jsonb_build_object(
        'key',jsonb_build_object('install_id',(e.request->>'install_id')::uuid),
        'set',jsonb_build_object('state','prepare_unknown')));
    END IF;
    RETURN jsonb_build_object(
      'effects',jsonb_build_array(jsonb_build_object(
        'key',jsonb_build_object('effect_id',e.effect_id),
        'set',jsonb_build_object('status','unknown','outcome',v_outcome,
                                 'settled_at',now(),'claim_owner',NULL,
                                 'lease_until',NULL))),
      'runs','[]'::jsonb,'pins','[]'::jsonb,'installs',v_installs,
      'events',jsonb_build_array(jsonb_build_object(
        'entity_type','effect','entity_id',e.effect_id,
        'event_kind','effect_recovered_unknown',
        'payload',jsonb_build_object('effect_id',e.effect_id,'kind',e.kind,
          'replay_policy',e.replay_policy,'action','settle_unknown',
          'reason',p_reason,'attempt_no',e.attempt_no,'fence',e.fence,
          'recovery_effect_id',NULL))));
  END IF;

  SELECT * INTO r FROM v24.runs WHERE run_id = e.run_id;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('error',v24.error_v1('invalid_outcome'));
  END IF;
  v_late := r.status = 'cancelled' AND e.cancel_requested;

  IF v_late THEN
    v_status := r.status;
    v_close := r.close_intent;
    v_result := r.result;
    -- cancel-late preserves the cancel seal byte-for-byte: no interaction/
    -- pending_steer clear, no ended_at rewrite, no revision/turn bump.
    v_interaction := r.interaction;
    v_pending := r.pending_steer;
    v_ended := r.ended_at;
    v_turn := r.turn_no;
    v_revision := r.revision;
    v_pins := v24.run_pin_release_set(e.run_id, NULL, r.status, p_effect_id);
    v_events := jsonb_build_array(jsonb_build_object(
      'entity_type','run','entity_id',e.run_id,
      'event_kind',CASE e.kind WHEN 'model_call' THEN 'model_call_unknown'
                              ELSE 'tool_call_unknown' END,
      'payload',jsonb_build_object('run_id',e.run_id,'effect_id',e.effect_id,
        'reason',p_reason,'late',true)));
  ELSE
    v_status := 'blocked_unknown';
    v_close := jsonb_build_object('kind','unknown','reason',p_reason,
                                  'effect_id',e.effect_id);
    v_result := jsonb_build_object('v',1,'close_reason','unknown',
                                   'turn_no',r.turn_no + 1);
    v_interaction := NULL;
    v_pending := NULL;
    v_ended := now();
    v_turn := r.turn_no + 1;
    v_revision := r.revision + 1;
    v_pins := v24.run_pin_release_set(
      e.run_id,
      CASE e.kind WHEN 'model_call' THEN p_effect_id ELSE NULL END,
      'blocked_unknown', p_effect_id);
    v_events := jsonb_build_array(
      jsonb_build_object('entity_type','run','entity_id',e.run_id,
        'event_kind',CASE e.kind WHEN 'model_call' THEN 'model_call_unknown'
                                ELSE 'tool_call_unknown' END,
        'payload',jsonb_build_object('run_id',e.run_id,'effect_id',e.effect_id,
          'reason',p_reason)),
      jsonb_build_object('entity_type','run','entity_id',e.run_id,
        'event_kind','run_blocked_unknown',
        'payload',jsonb_build_object('run_id',e.run_id,'reason',p_reason,
          'effect_id',e.effect_id)));
  END IF;

  RETURN jsonb_build_object(
    'effects',jsonb_build_array(jsonb_build_object(
      'key',jsonb_build_object('effect_id',e.effect_id),
      'set',jsonb_build_object('status','unknown','outcome',v_outcome,
                               'settled_at',now(),'claim_owner',NULL,
                               'lease_until',NULL))),
    'runs',jsonb_build_array(jsonb_build_object(
      'key',jsonb_build_object('run_id',e.run_id),
      'set',jsonb_build_object(
        'status',v_status,
        'turn_no',v_turn,
        'remaining_steps',r.remaining_steps,
        'remaining_tokens',r.remaining_tokens,
        'remaining_tool_calls',r.remaining_tool_calls,
        'remaining_wall_ms',greatest(0, r.remaining_wall_ms -
          coalesce((extract(epoch from (now()-e.created_at))*1000)::bigint,0)),
        'interaction',v_interaction,'pending_steer',v_pending,
        'close_intent',v_close,'result',v_result,
        'revision',v_revision,'ended_at',v_ended,'updated_at',now()))),
    'pins',v_pins,'installs',v_installs,'events',v_events);
END;
$$;
```

#### 4.5.2 语义表

| 项 | 冻结值 | 依据/证据 |
|---|---|---|
| 适用 kind | `model_call`/`tool_call`（`no_replay`）；host kinds 仅在 `cancel_requested` 或 install 投影不匹配时 | B.4 L570、L574–576；host kinds 默认 `replay_safe` |
| effect | `status='unknown'`，`outcome`=合成 receipt（含原 attempt/fence/owner + `reason`），`settled_at=now()`，`claim_owner/lease_until=NULL`，`resource_quiesced_at` 保持 NULL | B.4 L564；`c_effects_claim_ck`/`c_effects_settled` |
| run（正常） | `status='blocked_unknown'`；`interaction=NULL`；`pending_steer=NULL`；`close_intent={kind:'unknown',reason,effect_id}`；`result={v:1,close_reason:'unknown',turn_no:N+1}`；`ended_at=now()`；`revision+1`；`turn_no+1`；remaining_* 不变 | 与 `48:543–576`、`1061–1098` 的 unknown wall 同形 |
| run（cancel-late） | 保留 `cancelled` seal、`close_intent`、`result`、`interaction`、`pending_steer`、`ended_at`；只把 effect 结 unknown；不写 `run_blocked_unknown` | S4 的 cancel-late（`48:512–542`、`1062–1078`）；D4 L472 |
| 预算 | **不退款**；`remaining_steps/tokens/tool_calls` 原值；`remaining_wall_ms` 只按已用 wall 时间单调减 | §5.2 L277、`48:498–507` |
| pin | model：`run_pin_release_set(run, effect_id, 'blocked_unknown', effect_id)`；tool：第二参传 `NULL`，让正在结算的 tool effect 自己挡 pin；unknown 未静默前不得释放被它引用的 pin | `48:86–103`、`551`、`1089`；§3.2 L189 |
| interaction/steer | 清 `interaction`/`pending_steer`；不自动续链 | §5.3 L287、§4.6 L251 |
| close_intent/result/ended_at/revision | 见上；`revision+1` 供 poll 观察 | S3 C10 |
| 事件 | 每 action 一条 `effect_recovered_unknown`（entity=effect）；每 run 最多一条 `model_call_unknown`/`tool_call_unknown` + 一条 `run_blocked_unknown`（同 sweep 内去重） | `events` 唯一键；§5 负例 |
| 不建第二 effect | 只更新原 effect；`successors=[]`；effect 计数只 +1（command effect 自身） | §8 L412、C.3 L715 |

#### 4.5.3 复用还是抽取：冻结选择与等价证明

**冻结选择：抽取 `unknown_wall_delta`，但 W3 不改 S4 的两个 settlement 函数**（避免在 S6 里重写 `interpret_model_settlement`/`interpret_tool_settlement` 的 800+ 行）。`interpret_recover` 调 helper；S4 的原分支保持原样。等价性用**控制对照**证明，而不是口头声明：

- 同一 fixture 建两个结构相同的 run/effect（同 scope、同 budget、同 pin、同 attempt/fence、同 kind），一个走正常 `advance(class='unknown', token)`，一个走 `command_recover`；
- 对比归一化投影：`runs` 除 `updated_at` 外全列逐字节相等；`pins` 的 released 集合相等；`effects` 的 `status/resource_quiesced_at/claim_owner/lease_until` 相等（`outcome` 的 `recovery`/`reason` 字段允许不同，这是出处）；事件 `(entity_type,event_kind)` 多重集相等，payload 去掉 `reason`/`recovery_effect_id` 后相等；
- 控制对照在 W3 的 `test_g5.py` 内运行（不新增 G5 窗口，只作为 K3 的子断言），并在 S4 的 G2b-O/G2b-T 回归中保持既断言语义不变。
- **fallback**：若控制对照失败且定位为 helper 与 S4 逻辑漂移，则 W3 改为让 S4 的两个 unknown 分支也调用 `unknown_wall_delta`，然后重跑 `v24/s4/test_g2b.py`；这是代码重构，不是规格变更。若重构仍红，停手报告，不降低对照标准。

#### 4.5.4 `manual`：只报告，不自动恢复

- `recoverable_effects` 的 `replay_policy <> 'manual'` 把 manual 排除在候选之外，因此它**不消耗** 16 上界，也不会让 `has_more` 永远为真（§5 N9）。
- `interpret_recover` 仍防御式统计 `manual_debt`：scope 内 claimed+过期+manual 的计数；不写行、不发事件、不进入 `applied`。
- 治理路径不在 S6：manual 的“是否接受已有外部结果/保留 blocked”由显式治理命令决定（B.4 L572）；S6 只保证它不会被自动洗白、也不会被遗忘在 `has_more` 里。
- 若 manual 行让 scope 的 `scope_closable`/`install_disposed_ok` 永远为 false，这是 S5 的显式债务（unknown/claimed 挡关闭），不是 S6 的 bug；K9 会断言 `closed_at` 保持 NULL。

#### 4.5.5 迟到 receipt 与 `receipt_conflict`

- recovery 把 no_replay effect 结为 unknown 后，原 host 若带着旧 token 和成功 outcome 回来：`advance` 先在 `30:272–278` 命中终态分支，digest 不同 → `receipt_conflict`；digest 相同（理论上只有原样重交同一 unknown receipt）→ `replay`。**未知永不改写成 success**。
- `receipt_conflict` 的 `detail` 保持 `{}`（既有 gate 的精确 JSON 断言：`test_g2b.py:626,849`、`test_g4.py:1258`）；B.4 的“host journal 引用”由 host 侧 JSONL 以 `(effect_id,attempt,fence,reservation)` 记录，gate 在断言时把它作为证据路径打印，而不是塞进 DB 错误 detail。这样既不破坏 8 个既有 gate，也不丢出处（D-S6-7）。
- 旧 token 在 `replay_safe` reset 后回来：`status='ready'` 不满足 `30:282` 的 `status='claimed'`，返回 `stale_claim` 且零写；host journal 仍保留 receipt，下一次 claim 会复用同一 reservation（§4.4）。

### 4.6 接线：`30_advance.sql`、`40_interpreters.sql`、`50_permissions.sql`

#### 4.6.1 candidate closure seed（`30_advance.sql`）

`advance` 的闭包发现（`30:318–506`）只从 `payload` 的引用字段取种子；`candidates` 在 `body` 里，必须显式加入，否则 `interpret_recover` 会写未锁行。新增一个 UNION 分支：

```sql
      UNION ALL
      -- S6: the frozen recovery hint is a lock seed, never a lock instruction
      -- supplied by the caller as SQL.  Only effect ids; the rest of the
      -- closure expands from the effect rows.
      SELECT 'effects'::text, cand.value::uuid
        FROM jsonb_array_elements_text(
               coalesce(v_body->'candidates','[]'::jsonb)) AS cand(value)
       WHERE v_class = 'command'
         AND v_body->>'kind' = 'command_recover'
         AND c.entity_type = 'effects' AND c.entity_id = p_effect_id
```

`advance` 的 body kind allowlist（`30:186–188`）增加 `'command_recover'`；shape 校验仍是“五个必需键 + payload 是 object”，`candidates` 是额外键，不改变既有 `canonical_bytes = canonical_json(payload)` 校验（`30:200–202`）。闭包 512 行上限（`30:508–512`）与 `retry_with_closure` 规则不变；候选 effect 不存在时走既有 existence 检查（`30:514–530`）返回 `retry_with_closure`（W0），不发生部分写。

#### 4.6.2 footprint 与 applier（`40_interpreters.sql`）

`validate_and_apply_delta` 的指挥链增加：

```sql
  ELSIF kind = 'command_recover' THEN
    IF inserts <> '{}'::jsonb
       OR EXISTS (SELECT 1 FROM jsonb_object_keys(updates) x
                   WHERE x NOT IN ('effects','runs','pins','installs'))
       OR coalesce(p_delta->'successors','[]'::jsonb) <> '[]'::jsonb
       OR p_delta ? 'settle' THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
```

上限改为：

```sql
     OR (SELECT coalesce(sum(jsonb_array_length(value)),0) FROM jsonb_each(updates)) >
        (CASE WHEN kind IN ('command_cancel','command_steer') THEN 512
              WHEN kind = 'command_recover' THEN 64
              ELSE 16 END)
```

applier 增加一个 `IF kind = 'command_recover' THEN ... END IF;` 分支（放在 `command_dispose` 分支之后、通用 `effects` 插入之前），对四类行逐条 `UPDATE` 并做三件事：

1. 逐行校验键在 `p_closure` 对应的数组里（`effects`/`runs`/`pins`/`installs`），否则 `invalid_outcome` 回滚；
2. 逐列白名单（同 §4.3.3 的表）；`effects` 行只允许 `status,claim_owner,lease_until,outcome,settled_at`，且 `WHERE effect_id=... AND status='claimed' AND lease_until <= now()`；不满足即 `RAISE EXCEPTION ... ERRCODE='40001'`（G 串行下不应发生，作为防御）；
3. 输出 `emitted` 仍为空；command effect/request 由既有通用插入（`40:2196–2204`）完成，`response` 取 `p_delta->'request'->'response'`（`40:1836–1840`）。

`40:589–593` 的“同 entity/kind 事件不得重复”保持不变；`interpret_recover` 在返回前已去重（§4.3.2）。

#### 4.6.3 `50_permissions.sql` 的三处精确改动

```sql
-- 1) 只读发现面：与 resolve/poll/wait_check 同一 ACL 面
GRANT EXECUTE ON FUNCTION v24.recoverable_effects(uuid, integer)
  TO v24_admin, v24_service, v24_operator;
-- 2) 恢复命令入口
GRANT EXECUTE ON FUNCTION v24.command_recover(uuid, text, integer)
  TO v24_admin, v24_service, v24_operator;
-- 3) DEFINER allowlist 数组（原 50:60）加入 'recoverable_effects'
     IS DISTINCT FROM ARRAY['advance','poll','recoverable_effects','resolve',
                            'run_owner','run_projection','wait_check']::text[]
```

并把 `50:86` 的 write-verb 形状检查元组扩为 `('start','cancel','steer','respond','command_recover')`（仍是 `NOT prosecdef`、固定 `search_path`、三角色都有 EXECUTE）。`recoverable_effects` 的 `prosecdef=true` 会进入 `50:94–98` 的只读 DEFINER 检查：必须 `provolatile='s'`，且 `prosrc` 不含 `insert|update|delete|pg_advisory*`（注释也算）。

### 4.7 既有 gate 的精确重述（不削弱）

#### 4.7.1 G1-A（`v24/s1/test_g1.py:113–185`）

现状（逐字）：

```python
read_definers = {"resolve", "run_owner", "run_projection", "poll", "wait_check"}
assert {n for n, r in functions.items() if r[0]} == {"advance"} | read_definers
...
for wrapper in ("scope_control", "install", "start", "cancel", "steer", "respond"):
    assert not functions[wrapper][0], wrapper
    body = functions[wrapper][3]
    assert "v24.advance(" in body, wrapper
    for write in ("INSERT INTO", "UPDATE v24.", "DELETE FROM", "pg_advisory_xact_lock"):
        assert write not in body, (wrapper, write)
```

S6 的**精确**改动（只增不减）：

```python
read_definers = {"resolve", "run_owner", "run_projection", "poll", "wait_check",
                 "recoverable_effects"}
assert {n for n, r in functions.items() if r[0]} == {"advance"} | read_definers
...
for wrapper in ("scope_control", "install", "start", "cancel", "steer", "respond",
                "command_recover"):
    assert not functions[wrapper][0], wrapper
    body = functions[wrapper][3]
    assert "v24.advance(" in body, wrapper
    for write in ("INSERT INTO", "UPDATE v24.", "DELETE FROM", "pg_advisory_xact_lock"):
        assert write not in body, (wrapper, write)
```

同时保留：`"UPDATE v24.effects"` 的 allowlist 仍只有 `advance` + 三个 applier（`command_recover`/`interpret_recover` 不得出现该字面量）；`pg_advisory_xact_lock` 仍只有 `advance`；`advance` 的锁序与 `PERFORM pg_advisory_xact_lock` 首锁断言不变。`recoverable_effects` 的 `pg_get_functiondef` 会进入 `read_definers` 循环，因此其函数体/注释不得含四个禁用词（`test_g1.py:123–128` 与 `50:94–98` 双重扫描）。

#### 4.7.2 G2a-11 / G2b-C（command kind 数组）

现状：`v24/s3/test_g2.py:611–613` 与 `v24/s4/test_g2b.py:51–53,380–381` 的 `COMMAND_KINDS`/`command_kinds` 是 8 项且断言 `len == 8`。S6 的精确改动：加入 `"command_recover"`，长度断言 8→9，循环仍对每个 kind 断言“claim 为 `invalid_args` + 十表快照相等”。这是**扩大覆盖**，不是放宽；`claimable_kinds()` 仍是 5 项（`48:55–57`），不能因为新增 command kind 而改变。

#### 4.7.3 `test_ddl.py`

在 `test_ddl.py:269–271` 的 command claim 循环加入 `"command_recover"`（`attempt_no=1` 必须被 `c_effects_command_claim` 拒绝）；新增一条正向：`kind='command_recover'` 且 `attempt_no=0` 可插入；`events.entity_type='effect'` 可插入，`'bogus'` 仍被 `c_events_entity` 拒绝。不新增表/视图断言。

---

## 5. G5 断言：K1–K10（恰十窗口）

### 5.1 十窗口表

> **硬约束**：K1–K10 与设计 §8 L410–419 的十行一一对应，不增不减、不合并、不改名。K1、K2、K3、K5、K6、K7、K8、K9、K10 是独立 OS 子进程在具名边界 `SIGKILL`；K4 是 fixture-only SQL 错误注入。每行都断言“重启后只做 resolve + 未结算 effect 扫描 + `command_recover`”，且打印 `[G5-Kn]` 与证据路径。

| ID | §8 行 / 边界 | 杀死/注入方法 | 重启前已提交事实 | 重启收敛动作 | 禁止项 | 证据 |
|---|---|---|---|---|---|---|
| **K1** | L410：command 请求已发出、advance COMMIT 前 | 子进程开事务、调用 `advance`、在 `COMMIT` 前向 READY 管道写一行并阻塞在 go 管道；父进程 `SIGKILL` | 无 command/request/effect 行可见（未提交事务随 backend 死亡回滚） | 新 `recover_worker.py` 用**同 effect_id/request_key/bytes** 重交同一条 command（`command_recover` 或普通命令）；只成功一次 | 不得扫描“预先提交的 command 行”推断执行；不得因为看不到行就换 key | `[G5-K1]` + 子/父/worker 三个 PID + `requests/effects` 计数 0→1 + 十表快照 |
| **K2** | L411：claim COMMIT 后、IO 前 | 子进程 claim 两个 effect（`host_prepare` replay_safe、`model_call` no_replay），COMMIT，READY，阻塞；父 SIGKILL | 两个 effect 均 `claimed`，attempt/fence/owner/lease 已提交；未发生任何 host IO | worker 调 `command_recover`：`host_prepare` 回 `ready`（attempt/fence 保留），`model_call` 转 unknown；随后只对 `host_prepare` 走普通 claim（attempt+1/fence+1）+ FakeHost 重投 | 不得凭 lease 过期推定未执行；不得对 `model_call` 走 claim/重放；不得建第二 effect | JSONL 无 model IO line；`host_prepare` reservation 计数 1；`model_call` unknown、run `blocked_unknown`；DB `v24_fake.journal` 只 1 行 |
| **K3** | L412：IO 完成、advance 前 | 子进程 claim+COMMIT；对 `host_prepare` 执行 FakeHost（写 JSONL+DB journal），对 `model_call` 不写 receipt；READY；父 SIGKILL | DB 仍 `claimed`；host journal 有 `host_prepare` 的完整 receipt；`model_call` 无 receipt | ① `host_prepare`：`command_recover` 回 ready → 普通 claim 新 token → FakeHost 以同一 reservation 返回首次结果 → settle success；② `model_call`：`command_recover` 转 unknown；③ 迟到 success 在 unknown 后重交 → `receipt_conflict` W0 | 不得重新执行 IO（reservation 计数必须 1）；不得把 unknown 改成功；不得为“隐藏重试”建第二 effect；不得跳过 ① 的原始 receipt | JSONL 与 `v24_fake.journal` 的 reservation/attempt/fence 行；`model_call` 的 `receipt_conflict` 与十表快照；`host_prepare` 最终 `installed` |
| **K4** | L413：advance 中途错误 | **SQL 错误注入**：`CREATE FUNCTION v24_fake.raise_k4()` + `CREATE TRIGGER k4_inject BEFORE INSERT ON v24.requests ...`；子进程跑同一条 command，捕获 `P0001`，`ROLLBACK`，READY/退出；父删 trigger 后由 worker 重交原 outcome | 事务已回滚：无领域半写、无 successor、无 request/effect 行可见 | worker 重交原可信 outcome；唯一约束挡重复；只成功一次 | 不可重新 IO；不可在 aborted 事务里继续；trigger 不得留在产品库 | 十表快照前后逐字节相等；`requests/effects` 0；删 trigger 后重交恰 1 条；trigger 只存在于 `v24_fake` 函数 + 测试期 trigger |
| **K5** | L414：advance 已 COMMIT、应答丢失 | 子进程执行 `command_recover` 到 COMMIT，**不序列化 response**，只发 `COMMITTED`，阻塞；父 SIGKILL | request/effect/receipt/events 已提交；客户端未见 response | 新 worker 用同 key+bytes 重放：`advance` 在 `30:255–260` 返回首次 response；再跑一次仍逐字节相同 | 不得重复预算/事件/effect/successor；不得把“应答丢失”当失败再执行一次 sweep | 两次 replay 的 response JSON 逐字节相等；request/effect 计数 1；sweep 事件 1；十表快照只在第一次变化 |
| **K6** | L415：provider withdrawn、fiber 未清理 | 子进程提交 withdraw（`fiber_control(off)`/desired-off 的 retire 起点）与 run terminal，READY 后父 SIGKILL，**不**完成 slot release/pin 释放 | slot 不可新 resolve；旧 pins、episode（retiring）仍在；可能有 claimed/unknown-unquiesced 引用 | worker 先 `resolve(scope,keys)`，再对未结算 `fiber_reconcile`/`host_release` 用新 key 推进；pin 只在回执确认静默或 inspect 置 quiesced 后释放 | 不得级联 delete；不得因 run terminal 提前释放 pin；不得跳过 resolve 直接清 slot | `resolve` 行（live=false/withdrawn）；pin 行仍 live；episode retiring；journal 显示 retire 继续；`closed_at/disposed_at` 未被提前写 |
| **K7** | L416：子 fiber 已清理、父未清理 | 子进程提交 child 的 `disposed` + slot release + episode closed，父 episode 仍 retiring、父贡献未 release；READY 后父 SIGKILL | 子墓碑已提交；父 episode retiring、父 slot/pin 未清 | worker `resolve` + 从未结算 effect 继续；若 effect 已结算，resolve 发现剩余差异后再提交下一个控制 effect（新 key） | 不得重做子 dispose；不得跳父 episode 直接 release；不得删历史 owner 边 | 子 `disposed_at` 不变；父 episode 从 retiring→closed；父 slot release 晚于子 disposed；owner 复合键仍指向旧 episode |
| **K8** | L417：host_prepare IO/receipt 窗口 | 子进程 install=`preparing`、host_prepare claimed，FakeHost 写 journal，READY 后父 SIGKILL（receipt 未提交） | install `preparing`；host_prepare `claimed`；journal 有 prepare receipt | worker ① 先断言 `fiber_control(on)` 被拒 `install_not_ready` W0；② `command_recover` 把 host_prepare 回 ready；③ 普通 claim + FakeHost 同 reservation 返回首次结果；④ settle success→`installed`；⑤ 再 `fiber_control(on)` 才可激活 | 不得在 `preparing`/`prepare_unknown` 激活；unknown 时不得越过 inspect；不得重新 prepare 第二份制品 | `fiber_control(on)` 的 W0 快照；install 状态 `preparing→installed`；reservation 计数 1；journal 行 attempt/fence |
| **K9** | L418：scope close/prepare_unknown | 子进程写 `close_requested_at`、install `prepare_unknown`、host_prepare unknown，READY 后父 SIGKILL；不 inspect | scope closing；install `prepare_unknown`；host effect unknown、`resource_quiesced_at IS NULL` | worker `resolve` + `command_recover`（该 scope 无 claimed 则 noop）+ 新 key close：barrier `pending.installs>0`、`closed_at` NULL；inspect known/absent 后 dispose；再 close 才 `closed_at` | 不得无 inspect 写 `closed_at`；不得把 `prepare_unknown` 当 disposed；不得把 unknown 洗成成功 | `close_requested_at` 非空、`closed_at` NULL；`scope_closable` false；inspect 后 install disposed；最终 `closed_at` 与 `scope_closed` 恰 1 |
| **K10** | L419：host CAS release 后、DB receipt 前 | 子进程 install=`dispose_pending`、host_release claimed，fake release 写 JSONL/DB journal（表示 CAS 已释放），READY 后父 SIGKILL；DB 未结算 | `dispose_pending`；host_release `claimed`；journal 记 `release` 结果 | worker `command_recover` 把 release 回 ready；普通 claim 新 token；fake release 以同 reservation 返回首次结果；settle success→`disposed`；若 receipt 丢失则同 reservation inspect，绝不发第二条 release | 不得再发第二条 release；不得直接写 `disposed`；不得把“CAS 可能已变”当已释放 | release reservation 计数 1；inspect 的 `target_reservation` 与原 release 逐字节相同；`disposed` 只在 success/inspect known 后 |

### 5.2 写类 W0 / W1 / WD 的精确定义

| 类 | 定义 | 用于 |
|---|---|---|
| **W0** | 十表（`scopes,runs,effects,pins,episodes,fibers,slots,installs,events,requests`）的 `g5_snapshot()` 逐字节相等；无新 request/effect/event，无任何列变化 | 认证失败、limit 非法、`request_conflict`、`stale_claim`、迟到 receipt 的 `receipt_conflict`、未授权 scope、无 inspect 的 `closed_at` 负例 |
| **W1** | 除 W0 外，恰新增 **1 条** `kind='command_recover'` 的 command effect + **1 条** request + 该 effect 写出的 sweep/事件；十表中除 `effects/requests/events` 外零行变化 | noop sweep、重复 sweep（新 key）、converged 后的幂等 sweep、unauthorized scope 的“无写”对照（后者是 W0，不是 W1） |
| **WD** | W1 + 恰好 §5.1 期望的 per-action delta（target effect 行、必要的 run/pin/install 行）；无 successor、无第二 effect | K2/K3/K8/K10 的应用型 sweep |

`g5_snapshot(conn)` 的实现：对十表分别 `SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY 主键), '[]')`，返回 `{table: rows}`；比较用 Python `==`（不是只比 count）。`effects.settled_at/updated_at` 等 `now()` 列在 W0 中没有新写，所以可直接比较；WD 中按 §5.1 的具名列断言。

### 5.3 强制负例与零写类别

| # | 负例 | 期望 | 写类 | 绑定 |
|---|---|---|---|---|
| N1 | service 角色对 admin 创建的 scope 调 `command_recover` | `not_found_or_denied`（不泄露存在性） | W0 | K2 |
| N2 | fixture 临时把 `EXECUTE` 授给 probe 登录（否则 PostgreSQL 先以 42501 拒绝，测不到 `role_allowed`），再用该登录调 `advance` 伪造 `command_recover` body | `unauthorized`（`advance` 在 G 前返回）；无 command effect/request | W0 | K1 |
| N3 | `p_limit` 为 `0`/`17`/`NULL` | `invalid_args`（wrapper 本地拒绝）；直接调 `recoverable_effects` 时分别 0 行/16 行/0 行 | W0 | K2 |
| N4 | 预先 seed 一条已结算 `command_recover` effect，扫描不得据此推断执行 | `recoverable_effects` 0 行；新 key sweep 为 noop | W1 | K1 |
| N5 | `model_call` lease 过期但 host 可能已执行 | 只转 unknown；不写 success/failure；不声称“未执行” | WD | K2 |
| N6 | 任何 recovery 动作不得新增第二 effect | effect 计数 = 原 effect + 1 条 command effect；`successors=[]` | WD | K3 |
| N7 | unknown 后迟到 success | `receipt_conflict`；原 unknown receipt 不变 | W0 | K3 |
| N8 | `no_replay` 过期不得自动重投 | 无新 claim、无 IO、effect 仍 unknown、run 不再续链 | WD | K2 |
| N9 | `has_more` 不是 cursor | 无新表/列；limit=1 时 true，接着的新 key 处理剩余后 false；manual-only 时 false | W1/WD | K2 |
| N10 | converged 后重复 sweep | 新 key：W1 noop；同 key+同 bytes：逐字节 replay（零写） | W1 / W0 | K5 |
| N11 | 同 key 不同 bytes（scope/limit 变） | `request_conflict`，零写 | W0 | K5 |
| N12 | reset 后旧 token 再结算 | `stale_claim`，零写；host journal 仍在 | W0 | K3 |
| N13 | manual 过期 claim | `manual_debt+1`；不写、不占 16 上界；`has_more` 不为它永久 true | W1 | K3 |
| N14 | K4 注入后重交 | 十表快照相等；同一 outcome 只成功一次；trigger 已删 | W0→WD | K4 |

**“lease 过期 ⇒ 未执行”禁令**：K2/K3 的断言里没有“因为 lease 过期所以未执行”的推理；`no_replay` 的 receipt 明确写 `observed:'unknown'`，`replay_safe` 的重投依赖 adapter 的 reservation 幂等，而不是时间推断。**“unknown ⇒ 成功”禁令**：K3 的 late success 必须 `receipt_conflict`，K9 的 prepare_unknown 必须等 inspect。**“第二 effect”禁令**：N6 的计数断言覆盖 K2/K3/K8/K10 全部应用型 sweep。

---

## 6. 崩溃 harness 设计（`v24/s6/`）

### 6.1 文件清单

| 文件 | 作用 |
|---|---|
| `v24/s6/README.md` | S6 的对象、入口、gate 命令、窗口表、债务与实测记录（W4 更新） |
| `v24/s6/g5_support.py` | 小工具：`new_scope()`、`seed_claim()`、`g5_snapshot()`、`fingerprint()`、`jsonl_path()`、`read_jsonl()`、`wait_ready()`；不复制 S1–S5 的测试逻辑 |
| `v24/s6/crash_worker.py` | **子进程**：按 `--window` 驱动到具名边界；DSN 从环境变量读；READY 后阻塞；不做恢复 |
| `v24/s6/recover_worker.py` | **新 OS 进程**：开新连接，跑 `resolve` + `command_recover`（K3 先查 host journal 再决定 receipt 重交/unknown），打印 JSON 结果 |
| `v24/s6/fake_crash_host.py` | FakeHost 的 `release()`/`inspect()` 扩展；与 `FakeHost.prepare` 相同的 journal/reservation 复用；文件 + DB 双写 |
| `v24/s6/test_g5.py` | 父进程/监督者：seed、spawn、kill、wait、调用 `recover_worker.py`、断言、cleanup；K1–K10 各一个函数 |

不新增 `v24/s6/setup_db.py`：复用 `v24/s1/setup_db.py` 的 `setup_db()`/`server_helper_scope()`。不新增 socket/网络 import；`test_g5.py` 在 `main()` 外安装与 S4/S5 相同的 `_no_network()` 断言。

### 6.2 三个进程与“重启”的定义

```text
parent --spawn--> crash_worker --READY(pipe)--> parent --SIGKILL--> waitpid
parent --spawn--> recover_worker (fresh OS process, new backend PID) --resolve + command_recover--> parent asserts
```

- **DSN 只走环境变量**（`V24_DSN`/`V24_JOURNAL`/`V24_WINDOW`），不走 argv，避免 `ps` 泄露；worker 启动后只从 env 读。
- **READY 先于 kill**：child 到边界后向继承的写管道写 `READY\n`，然后 `os.read(go_fd,1)` 阻塞；parent 用 `select.select([ready_fd],[],[],30)` 等 READY，读到后 `os.kill(pid,SIGKILL)`，再 `os.waitpid(pid,0)`。**没有 `sleep`**；超时即失败（不是重试）。
- **同一进程新建连接不算重启**：parent 只做 seed/断言；恢复只由 `recover_worker.py` 执行；parent 从不调用 `command_recover` 或 `resolve` 做收敛，也不把 child 的连接传给 worker。worker 的 `pg_backend_pid()` 与 child 的 `pg_backend_pid()` 必须不同（打印并断言）。
- **K1 的“pre-commit”**：child 在 `advance` 返回后、`COMMIT` 前发 READY；parent kill；DB 看不到该事务。**K5 的“commit”**：child 先 `COMMIT` 再发 `COMMITTED`，然后阻塞；parent kill；DB 已提交。
- 收尾：`waitpid` 后 parent 不假设 backend 已消失；它只做 MVCC 读（未提交行本就不可见）或已提交行读，不做 `sleep` 等 backend。`psycopg2` 连接在 child 死后由 OS 关闭，服务端 backend 自行回滚。

### 6.3 窗口模式（child 的具名边界）

| 模式 | child 做到 | READY 时机 | 父进程 kill 后 DB 可见 |
|---|---|---|---|
| `precommit` | 调 `advance`，拿到 response，不 COMMIT | COMMIT 前 | 无 command/request/effect 行 |
| `claimed` | claim 两个 effect（host_prepare/model_call），COMMIT | claim COMMIT 后、IO 前 | 两行 claimed，attempt/fence/lease 已提交 |
| `io_done` | claim+COMMIT；FakeHost.prepare 写 JSONL/DB journal；model 不写 | host IO 后、settle 前 | claimed；host journal 有 receipt |
| `committed` | `command_recover` 到 COMMIT，不读取/不写 response | COMMIT 后 | request/effect/response 已提交 |
| `withdraw` | 提交 withdraw/retire 起点与 run terminal，不等 slot/pin | retire 起点后 | slot withdrawn（非 released）、pin 仍 live |
| `child_cleaned` | child dispose+release+episode closed；父仍 retiring | 子清理后、父清理前 | 子墓碑；父 retiring |
| `prepare_io` | install preparing + host_prepare claim + FakeHost.prepare；receipt 未提交 | prepare IO 后 | preparing + claimed + journal receipt |
| `close_unknown` | close_requested + install prepare_unknown + host_prepare unknown | unknown 提交后 | closing；prepare_unknown；quiesced NULL |
| `release_io` | install dispose_pending + host_release claim + fake release 写 journal | release IO 后 | dispose_pending + claimed + journal release |

### 6.4 持久 journal：文件 + DB 双写

| 事实 | host 侧 JSONL（`fsync`） | DB `v24_fake.journal` | 为什么 |
|---|---|---|---|
| claim 的 attempt/fence/owner | 记录 observed 值 | `effects` 行是权威 | DB 是资格权威；JSONL 用于跨进程对照 |
| reservation | 每条动作一行 | `payload->>'reservation'` 可 JOIN | B.4 L578 要求 reservation 绑定 effect_id |
| 外部动作 started/finished | **必须 fsync** | `result` 列记录结果 | 文件在 DB receipt 丢失时仍能证明 IO 发生过（K3/K10） |
| 外部结果 | 完整 result | `result` jsonb | 文件是 receipt；DB 行可 SQL join |
| recovery 动作 | worker 追加 `recover` 行 | recovery effect/events | 出处与审计 |
| 唯一性 | 同一 `(effect_id,attempt,fence,reservation)` 只一次 | `UNIQUE(effect_id,attempt,fence)`（`setup_db.py:657–665`） | 双写互证；gate 断言 reservation 计数 = 1 |

JSONL 由 `crash_worker.py`/`fake_crash_host.py` 以 `os.open(..., O_APPEND)` + `os.write` + `os.fsync` 追加；每条一行 JSON，含 `ts,pid,window,effect_id,attempt,fence,reservation,op,action,result`。文件路径由 parent 通过 `tempfile.mkdtemp(prefix='v24-s6-g5-')` 生成后放 env；失败时保留并打印，成功时删除（不写入仓库）。DB `v24_fake.journal` 是 fixture 表，随 `setup_db()` 的临时库一起 DROP。

### 6.5 重启与收敛（parent 不亲自恢复）

`recover_worker.py --window Kn` 的固定顺序：

1. 开三个连接：owner（读快照/必要时 inspect 断言）、service（advance）、journal（autocommit，给 fake host）。
2. `SET statement_timeout` 有界；`SELECT pg_backend_pid()` 打印。
3. `resolve(scope, keys)`：keys 从 `installs.requires` 取（≤16），返回 live/withdrawn；这是“只扫描 resolve”的证据。
4. 若 window ∈ {K2,K3,K5,K8,K10}：调 `command_recover(scope, key, limit)`；K3 先读 JSONL：有 host receipt 且 effect 仍 claimed-expired → 先走原 effect/token 的 `advance`（重交原 outcome），否则 `command_recover` 转 unknown；K5 只重放同 key+bytes。
5. 若 window ∈ {K6,K7,K9}：`command_recover`（若有 expired claim）+ 新 key 的 `fiber_control(off)`/`dispose`/`scope_control(close)`，每次一个有限阶段；不递归、不 worker。
6. 对 K2/K8/K10 的 host 动作：新 claim 后用 `fake_crash_host` 以同 reservation 执行；命中已有 journal 就复用首次结果（不再写第二行）。
7. `COMMIT`；把 `{window, backend_pid, resolve, recover_response, host_replayed}` 打到 stdout（JSON 一行）并退出 0。
8. parent 用独立连接断言 §5.1 的行/计数/快照；若 worker 非 0 或 JSON 缺字段，gate 失败。

**同进程新连接不算**：worker 是新 `Popen`；parent 只 spawn/断言；child 的 backend PID、worker 的 backend PID、parent 的 backend PID 三者互不相同。

### 6.6 排序：不用 sleep

- 用 READY/go 双管道 + `select` 做“到达边界”的握手；用 `waitpid` 做“已杀死”的确认；用 COMMIT 边界做“已提交”的确认。
- 不用 `time.sleep`、不用轮询 `pg_stat_activity`、不用 `LISTEN/NOTIFY` 猜顺序。
- `pg_blocking_pids()` **不用于 K1–K10 排序**：这些窗口是单写者顺序，不是并发；S7/G6 才用双连接屏障与 `pg_blocking_pids()`（pre-plan C15）。本 harness 只在失败诊断里打印 `pg_locks`/`pg_stat_activity` 快照，不作为通过条件。
- 每次 spawn 的 `communicate(timeout=30)`/`waitpid` 都有超时；超时即 fail，不重试。

### 6.7 FakeHost / FakeLLM 的复用（无网络/无 socket）

- `crash_worker.py` 直接 import `v24/s1/fake_host.py` 的 `FakeHost`：`prepare(worker_conn, effect_id, token)` 已实现“journal 命中即复用首次结果”、idle 连接检查、reservation 绑定（`fake_host.py:29–69`）。
- `FakeLLM`/`FakeTool`（`v24/s4/fake_llm.py`）是纯 Python、无 socket/文件/随机/sleep；K2/K3 的 `model_call` 结果可用 FakeLLM 的 `complete(request)`，但 **no_replay 的 recovery 不调用它**（只转 unknown）。
- `fake_crash_host.py` 的 `release()`/`inspect()` 复制 `FakeHost.prepare` 的“reservation 查询 → 已有则复用 → 否则写 JSONL + DB journal → 返回结果”结构；不 import `socket`/`http`/`urllib`/`requests`。
- `test_g5.py` 在 `main()` 外断言 `v24/s6/*.py` 不含网络 import，且 Fake 构造不打开 socket。

### 6.8 隔离、清理、运行时与证据

| 项 | 冻结做法 |
|---|---|
| 私有 PG | `with server_helper_scope(): db = setup_db()`；每次 gate 运行一个唯一临时库，结束 `DROP DATABASE ... WITH (FORCE)`（S1 既有逻辑） |
| 每 K 隔离 | 每个 K 用 `scope_control('create_root', ...)` 建独立 scope（唯一 realm/request key）；不共享 run/install/effect；K 间无顺序依赖 |
| 触发器和 fixture | K4 的 `v24_fake.raise_k4()` 与 `k4_inject` trigger 在 `try/finally` 删除；K2/K3 的 lease 过期用 owner 连接 `UPDATE v24.effects SET lease_until = now() - interval '1 second'` 作为 **seeded fixture**（`lease_until` 不在 `t_effects_identity` 的不可变列里，`20_triggers.sql:19–25`），注释标明“seeded expiry / 非公共路径” |
| 清理 | child/worker 在 `finally` 中 kill+waitpid；JSONL 目录成功时删除、失败时保留；DB 由 `setup_db()` 的 `__exit__` 清理；trigger 无论如何都删 |
| 运行时（计划估计，非实测） | K1 ~1s、K2 ~1.5s、K3 ~2s、K4 ~1s、K5 ~1s、K6 ~3s、K7 ~3s、K8 ~2s、K9 ~3s、K10 ~2s；setup ~3s；总计 ~22–28s（不含首次 pgembed 启动） |
| 证据产物 | 每个 K 打印 JSON：`{id, scope_id, child_pid, child_backend_pid, worker_pid, worker_backend_pid, journal_path, snapshot_before_sha256, snapshot_after_sha256, applied, has_more}`；失败时保留 journal 路径与两次快照 |
| 失败即停 | 任一 K 红、任一既有 gate 红、或 trigger/journal 残留：停止，不“重跑一次看看”；修根因后再跑 |

---

## 7. W1–W4

> 每个 W 是**可独立验证的检查点**；S6 只有一个里程碑（pre-plan §3 S6 卡“里程碑 1”），因此 W1–W3 不单独 commit，W4 做唯一一次里程碑提交。每个 W 结束时必须把既有 8 个 gate 跑绿；不是“最后一起跑”。`test_g5.py` 支持 `--only K1,K2` 做增量验证，最终 gate 必须是无参数全量 K1–K10。

**G8（8 个既有 gate，逐条原样）**：

```bash
uv run python v24/load.py
uv run python v24/s1/setup_db.py --self-check
uv run python v24/s1/test_ddl.py
uv run python v24/s1/test_g1.py
uv run python v24/s2/test_g3a.py
uv run python v24/s3/test_g2.py
uv run python v24/s4/test_g2b.py
uv run python v24/s5/test_g4.py
```

以下每个 W 的“必须绿”= **G8 + 该 W 的 `test_g5.py` 选择器**；W4 的最终 gate 用无参数全量 K1–K10。

### W1 只读发现面 + ACL + harness 骨架

| 项 | 内容 |
|---|---|
| Goal | `recoverable_effects` 成为唯一、只读、确定序、带 scope auth 的发现面；G1-A 的 DEFINER 闭集重述完成；harness 骨架（parent/child/worker/管道/kill）可跑通 K1；发现面的零写与边界（NULL/0/17、manual、排序、无第二 claim）有独立断言。 |
| Done when | ① `v24/sql/49_recovery.sql` 只含 `recoverable_effects`（W1 阶段），loader/self-check 顺序 48→49→50；② `50_permissions.sql` 的 allowlist/GRANT 与 `test_g1.py` 的 G1-A 精确重述后，`v24/s1/test_g1.py` 绿；③ 6 条发现面单测通过：`D-1` 只返回 claimed+过期、`D-2` 排序 `(lease_until,effect_id)`、`D-3` NULL/<1/>16 的 0/0/16 行、`D-4` manual 被排除、`D-5` 无权 scope 0 行、`D-6` 调用前后十表快照相等；④ K1 通过（child pre-commit kill → 新 worker 同 key 重交 → 恰一次）；⑤ 既有 8 个 gate 全 0。 |
| Key files | **NEW** `v24/sql/49_recovery.sql`、`v24/load.py`、`v24/s1/setup_db.py`、`v24/sql/50_permissions.sql`、`v24/s1/test_g1.py`、**NEW** `v24/s6/{g5_support.py,crash_worker.py,recover_worker.py,test_g5.py}` |
| Gate mapping | §B.3 L544–546 只读面、C.3 L711 发现面、K1 |
| Dependencies | S1 的 `advance`/G/`error_v1`；S5 的十表与 ACL 收口 |
| Size | M |
| 必须绿 | 8 个既有 gate（load/setup/ddl/g1/g3a/g2/g2b/g4） |
| Commit point | 不 commit；检查点 |

**W1 的发现面单测（写在 `test_g5.py --only K1` 或独立 `discovery_suite()`）**：seed 三条 claimed（过期 host_prepare、未过期 host_release、过期 manual）与一条 succeeded；断言只返回过期 host_prepare；再 seed 两条相同 `lease_until` 的不同 UUID，断言 UUID 升序；直接以 owner 调 `recoverable_effects(scope,NULL/0/17)` 断言 0/0/16 行且十表快照不变；以 service 调 admin scope 断言 0 行。

### W2 `command_recover` + `interpret_recover` + replay_safe 重投

| 项 | 内容 |
|---|---|
| Goal | 新增 `command_recover` kind 与唯一一次 `advance` 的 wrapper；`interpret_recover` 在 G 下重发现、按 policy 分流、在一个 delta 内应用 ≤16 个动作；`replay_safe` 回 `ready` 重投；request/receipt/replay/conflict 冻结；host 窗口 K2/K3(host)/K8/K10 通过。 |
| Done when | ① `10_schema.sql` 两条 CHECK、`30_advance.sql` allowlist + candidate closure seed、`40_interpreters.sql` dispatcher + footprint + applier 完成；② `command_recover` 同 key 同 bytes replay、同 key 异 scope/limit `request_conflict` W0、不同 candidates 同 key 仍 replay；③ `replay_safe` reset 清 `claim_owner/lease_until`、保留 attempt/fence；旧 token `stale_claim` W0；④ K2、K3 的 host 变体、K8、K10 通过；⑤ `test_g1.py`（wrapper 元组 + G1-A）、`test_g2.py`/`test_g2b.py`（command kind 8→9）、`test_ddl.py` 更新后全绿；⑥ 既有 8 个 gate 全 0。 |
| Key files | `v24/sql/10_schema.sql`、`v24/sql/30_advance.sql`、`v24/sql/40_interpreters.sql`、`v24/sql/49_recovery.sql`、`v24/sql/50_permissions.sql`、`v24/s1/test_g1.py`、`v24/s3/test_g2.py`、`v24/s4/test_g2b.py`、`v24/s1/test_ddl.py`、`v24/s6/*` |
| Gate mapping | C.29、C.30、§B.4 L560–564、K2/K8/K10（K3 host 变体支持） |
| Dependencies | W1 |
| Size | L |
| 必须绿 | 8 个既有 gate + `test_g5.py --only K1,K2,K3,K8,K10` |
| Commit point | 不 commit；检查点 |

**W2 的精确 gate 命令**：G8 的 8 条 + `uv run python v24/s6/test_g5.py --only K1,K2,K3,K8,K10`。

### W3 `no_replay` unknown + manual + cancel-late

| 项 | 内容 |
|---|---|
| Goal | `no_replay` 的 model/tool 过期 claim 只转 unknown，并完成 run/pin/预算/interaction/close_intent/result/ended_at/revision 收敛；manual 只计数；cancel-late 保留 cancel seal；K3 的 no_replay 变体、K6、K7、K9 通过。 |
| Done when | ① `unknown_wall_delta` 与 `interpret_recover` 的 settle_unknown 分支完成；② 控制对照：正常 unknown settlement 与 recovery-unknown 的 run/pin/事件归一化后相等（§4.5.3）；③ 预算不退款、interaction/pending_steer 清空、tool pin 由自身挡住、model pin 按 `run_pin_release_set` 释放；④ manual 不写、不占上界、`manual_debt` 正确；⑤ K3 的 model 变体、K6、K7、K9 通过；⑥ 既有 8 个 gate 全 0。 |
| Key files | `v24/sql/49_recovery.sql`、`v24/sql/40_interpreters.sql`（recover footprint/applier 的 runs/pins/installs 列）、`v24/s6/test_g5.py`、`v24/s6/recover_worker.py` |
| Gate mapping | C.31、§B.4 L564–576、§B.5 L590–592、K3/K6/K7/K9 |
| Dependencies | W2 |
| Size | L |
| 必须绿 | 8 个既有 gate + `test_g5.py --only K1,K2,K3,K6,K7,K8,K9,K10` |
| Commit point | 不 commit；检查点 |

**W3 的精确 gate 命令**：同 W2 的 8 条 + `uv run python v24/s6/test_g5.py --only K1,K2,K3,K6,K7,K8,K9,K10`。

### W4 K4/K5 + 全量 G5 + 收尾

| 项 | 内容 |
|---|---|
| Goal | K4（SQL 错误注入）与 K5（commit 后应答丢失）完成；`test_g5.py` 无参数运行 K1–K10 全绿；矩阵/台账/README/load order 收尾；S6 一次里程碑提交。 |
| Done when | ① K4 的 `v24_fake.raise_k4` trigger 注入、回滚、删 trigger、重交一次成功；② K5 的 commit+丢应答+两次 replay 逐字节相同；③ `test_g5.py` 无参数输出 `[G5-K1]`…`[G5-K10]` 与 `[passed] v24 S6 W1-W4`，退出 0；④ 9 个 gate 串行全 0；⑤ 矩阵 G5 行、台账 D-S6-*、`v24/s6/README.md` 更新；⑥ 按路径 `git add`，一次本地里程碑提交（不 push）。 |
| Key files | `v24/s6/test_g5.py`、`v24/s6/README.md`、`docs/reviews/v24-conformance-matrix-2026-10-23.md`、`docs/reviews/v24-deviation-ledger-2026-10-23.md`、本计划 |
| Gate mapping | §9 L439、§9.1 L446、C.1 L660–677、C.4 L721–730 |
| Dependencies | W1–W3 |
| Size | M |
| 必须绿 | 9 个 gate（8 既有 + G5 全量） |
| Commit point | **唯一一次** S6 里程碑提交：`v24: add crash recovery windows and bounded recovery command (G5)`（按路径 add，不 push） |

**W4 的精确 gate 命令**：G8 的 8 条 + `uv run python v24/s6/test_g5.py`（无参数，全量 K1–K10）。

---

## 8. 风险、回退与分歧点

### 8.1 风险表

| # | 风险/最脆弱假设 | 触发 | 失败模式 | 停手/回退 |
|---|---|---|---|---|
| R1（已关闭） | Oracle 否决 CC-1（新 kind + 一次 advance） | §4.2.3 的架构裁决被拒 | 只能退回 N 次 `advance`，无法满足“一个 request/receipt + sweep 级出处 + ready reset 同事务” | **CC-1 已批准（028D07），风险关闭**；历史备选：停手，不实现 N 次 fallback。 |
| R2 | `recoverable_effects` 的注释/函数体出现 `insert|update|delete` | 50 的 fail-closed DO 块或 G1-A 扫描 `prosrc` | `load.py`/`test_g1.py` 直接红，整个 S6 无法提交 | 改注释与函数体，保留只读语义；不豁免 regex、不加白名单例外 |
| R3（已关闭） | `c_events_entity` 加 `effect` 被 Oracle 视为数据模型修订 | §4.0 的 DDL delta | 需要设计稿 §3.1.9 修订或退回“每 sweep 一条聚合事件” | **CC-1b 已批准（028D07），风险关闭**；历史备选：退回聚合事件 + 逐 action receipt（证据降级，需书面接受）。 |
| R4 | `unknown_wall_delta` 与 S4 的 inline unknown 分支漂移 | W3 控制对照失败 | recovery 的 run/pin 结果与正常 settlement 不等价 | 先修 helper；仍不等价则按 §4.5.3 fallback 重构 S4 分支并重跑 G2b；仍红停手 |
| R5 | wrapper 的 candidates 是“发现时”的集合，G 下可能漂移 | 另一个 sweep/正常 settlement 在发现与 advance 之间提交 | 本次 sweep 少处理/跳过；`has_more=true` | 这是设计内的安全行为；响应记录 `skipped`，下一 key 重发现；不用 cursor 修补 |
| R6 | `replay_safe` 的“不重复 IO”依赖 adapter 的 reservation 幂等 | 真实 adapter 不按 reservation 去重 | 第二次 claim 产生第二次外部动作 | v1 只信受信 host + durable journal（D1）；gate 用 FakeHost 证明合同，不证明真实世界；真实 adapter 必须实现 reservation 复用后才能上线 |
| R7 | K6/K7/K9 依赖 S5 的 phase 机 | S5 的 `deactivate_stage`/`dispose_stage`/`scope_closable` 有缺口 | S6 的窗口卡住或提前写 `closed_at`/`disposed` | 先修 S5（它是 S6 的前置）；不得在 S6 里绕开 S5 的谓词 |
| R8 | lease 过期用 owner DML 设置，被质疑“不是真崩溃” | K2/K3 的 seeded expiry | 证据被认为不纯 | seeded expiry 只控制 `lease_until`，不改 status/claim；产品路径仍只读 `lease_until <= now()`；在 README/矩阵标明“seeded fixture，非公共路径” |
| R9 | `SIGKILL` 时 child 恰好已越过边界 | 管道/调度抖动 | K1/K5 的“before/after”不纯 | child 在边界后阻塞在 go 管道，parent 读到 READY 才 kill；超时即 fail，不 sleep 重试；日志打印 child 最后一步 |
| R10 | 既有 gate 因 kind 数组/ACL 变化被误改弱 | W2 的 8→9 与 G1-A 重述 | 覆盖变窄但 gate 仍绿 | 只增不减；对照本计划 §4.7 的逐字 diff；矩阵/台账记录 A-S6-* |

### 8.2 分歧点 D-S6-1…D-S6-12（不编辑设计稿，只呈报）

> 每条给出“设计/附录原文 → 不足 → 推荐 → 精确替换文本”。**裁决：15 项全部 ACCEPT（chat 028D07）；下表 12 条 D-S6 与 §8.3 的 3 条 CC 均为已批准文本，设计稿 C.3 已按此改写。D-S6-2 与 CC-1 是同一裁决的两个编号。**

| ID | 设计/附录原文 | 不足 | 推荐 | 精确建议文本 |
|---|---|---|---|---|
| **D-S6-1**（ACCEPT 028D07） | C.3 L711：“确定序 `(claimed_at, effect_id)`” | `effects` 没有 `claimed_at` 列（`10_schema.sql:67–109` 只有 `created_at/settled_at/lease_until`）；照写会引用不存在的列 | 改用 `(lease_until, effect_id)`；不新增列 | 将 C.3 该句改为：“确定序 `(lease_until, effect_id)`（`effects` 无 `claimed_at`；最早到期优先，UUID 升序打破平局）” |
| **D-S6-2**（ACCEPT 028D07） | C.3 L710–712：“先把每个 recovery 动作经 `advance` 提交” | 字面是 N 次 `advance` = N 条 request/effect，不能“一次 sweep 一个 request/receipt”，也没有 sweep 级 `has_more` 出处 | 一次 `advance` + `command_recover` kind（CC-1） | 将 C.3 调用顺序改为：“`command_recover` 只调用一次 `advance`，outcome 为 `class=command, kind=command_recover`，body 携带冻结候选与 canonical bytes；由 `interpret_recover` 在一个 delta 内应用 ≤16 个动作” |
| **D-S6-3**（ACCEPT 028D07） | C.3 L713：“按 kind 的 `replay_policy` 处理 … replay_safe / no_replay”；未提 manual | manual 若进入扫描会永久占用 16 上界并让 `has_more` 恒 true；自动处理又违反 B.4 L572 | 发现面排除 manual；只报告 `manual_debt`；不写、不占上界 | 在 C.3 分流后加：“`manual` 不进入 `recoverable_effects` 的候选；`command_recover` 只以 `manual_debt` 计数报告，保留为治理债务，不消耗 ≤16 上界” |
| **D-S6-4**（ACCEPT 028D07） | C.3 L713：“`replay_safe` 作为新的 ready attempt …（新 attempt/fence）” | 若 recovery 自己 bump，recovery 就成了第二个 claim 写者；与 §B.4 L560 的“只有新 attempt 实际替代旧 claim 才递增 fence”冲突 | reset 只回 ready、保留 attempt/fence；下一次普通 claim 递增 | 将括号改为：“置回 `ready` 并清 `claim_owner/lease_until`，保留 `attempt_no/fence`；下一次普通 claim 递增二者，recovery 不签发 token” |
| **D-S6-5**（ACCEPT 028D07） | C.3 L710：`command_recover(p_scope, p_limit DEFAULT 16)`；本任务要求再加 `p_request_key` | PostgreSQL 不允许默认参数后跟无默认参数，字面签名不可执行 | `(p_scope uuid, p_request_key text, p_limit integer DEFAULT 16)` | 将签名改为：“`v24.command_recover(p_scope uuid, p_request_key text, p_limit integer DEFAULT 16) RETURNS jsonb`” |
| **D-S6-6**（ACCEPT 028D07） | C.3 L710 只说“scope auth”，未定义谓词 | 无法写 gate，也无法防止越权读；`resolve`/`poll` 的谓词是 run owner，不适用于 scope | `scopes.owner_principal = principal_id(session_user)` 或 `v24_admin`；不匹配 0 行/`not_found_or_denied` | 在 C.3 加：“scope auth = `scopes.owner_principal = principal_id(session_user)` 或 `pg_has_role(session_user,'v24_admin','USAGE')`；不匹配的发现面返回 0 行，`command_recover` 返回 `not_found_or_denied` 且零写” |
| **D-S6-7**（ACCEPT 028D07） | B.4 L566：“记录为 host journal 引用并将 effect 标为 unknown” | `receipt_conflict` 的 DB 错误 detail 恒 `{}`（`30:278`），既有 gate 精确断言 `{"detail":{}}`；DB 无法凭空填 host 路径 | 保持 detail `{}`；host journal 引用由 JSONL 以 `(effect_id,attempt,fence,reservation)` 记录，gate 打印路径 | 在 B.4 加：“`receipt_conflict` 的 `detail` 保持 `{}`；host journal 引用由 adapter/证据面按 effect_id+attempt/fence 记录，不写入错误 JSON” |
| **D-S6-8**（ACCEPT 028D07） | C.3 L714：“`has_more` 只是返回提示，绝不是持久 cursor/queue/job” | 未定义计算口径，容易实现成“本次发现总数>limit”或落库 | `has_more = 同 scope 内非 manual、claimed、过期、且不在本次 applied 的 effect 存在`；每次重算 | 在 C.3 加：“`has_more` = 本次调用后仍存在未处理的非 manual 过期 claim；每次调用重新计算，不持久化” |
| **D-S6-9**（ACCEPT 028D07） | C.3 L710–714 未定义“同 key 在收敛后重放”的语义 | 若候选集进 canonical bytes，commit 丢应答后的重试必然 `request_conflict`；若候选集不进，又要说明同 key 不同候选为何 replay | 候选集只作 `body.candidates`（不进 digest）；同 key 同 `{v,scope_id,limit}` replay；同 key 异 scope/limit `request_conflict`；收敛后重复 sweep 用新 key（W1） | 在 C.3 加：“canonical bytes 只含 `{v,scope_id,limit}`；候选 id 作为 body.candidates 冻结点但不参与 digest；同 key 不同候选仍 replay 首次 response，同 key 不同 scope/limit 为 `request_conflict`；重复 sweep 用新 key” |
| **D-S6-10**（ACCEPT 028D07） | C.3 L711：“`LIMIT <= 16`” | 未定义 `0`/负数/`NULL`/`>16` | 公开 wrapper 对 NULL/<1/>16 返回 `invalid_args` W0；发现面防御式 0/0/16 行 | 在 C.3 加：“`p_limit` 必须 1..16；wrapper 对越界返回 `invalid_args`；发现面对 NULL/<1 返回 0 行、对 >16 截到 16” |
| **D-S6-11**（ACCEPT 028D07） | §3.1.9 L176 的 `entity_type` 未给闭集；`10_schema.sql:241` 实际闭集不含 `effect` | 逐 action 的 recovery 事件没有合法 entity_type；挂到 scope/run 会撞 `(effect_id,entity_type,entity_id,event_kind)` | `c_events_entity` 增加 `effect`；逐 action 事件 entity_id=target effect_id | 在 §3.1.9 加：“`entity_type` 闭集含 `effect`；recovery 的逐 action 出处事件挂 `effect`，sweep 汇总事件挂 `scope`” |
| **D-S6-12**（ACCEPT 028D07） | C.3 未说明 closed scope 上调用 `command_recover` 的行为 | 实现可能误用 `scope_closed` 或拒绝清理债务 | closed scope 允许调用；无候选则 W1 noop；不新增 `scope_closed` 分支 | 在 C.3 加：“`command_recover` 不对 closed scope 新增拒绝；无候选即 noop；不得用 `scope_closed` 阻断恢复” |

### 8.3 需要 Oracle 批准的三个合同变更（CC）

| ID | 变更 | 精确文本 | 历史备选 |
|---|---|---|---|
| **CC-1**（ACCEPT 028D07） | 新增 `command_recover` kind + `events.entity_type='effect'`，并同步设计 §3.1.3/§A.1/§3.1.9、`10_schema.sql`、dispatcher、footprint、`test_ddl`/G2a/G2b、G1-A | §3.1.3/§A.1 的 kind 闭集加 `command_recover`；§3.1.9 的 entity 闭集加 `effect`；其余见 §4.0/§4.7 | 历史备选：停手；不用 N 次 advance 假装满足（D-S6-2） |
| **CC-2**（ACCEPT 028D07） | `body.candidates` 不进 `canonical_bytes`/digest | C.3：“canonical bytes 只含 `{v,scope_id,limit}`；candidates 为 body 元数据，不参与匹配；解释器在 G 下重发现为准” | 历史备选：若坚持候选进 digest，必须同时接受“commit 丢应答后重试返回 `request_conflict`”，并删除 Done when 4 与 K5 的 replay 断言；本计划不建议 |
| **CC-3**（ACCEPT 028D07） | `command_recover` 的 response 在冻结 envelope 外增加 `recovery` 对象 | C.3：“`command_recover` 返回标准 envelope + `recovery:{scope_id,limit,candidates,applied,skipped,manual_debt,has_more}`” | 历史备选：若拒绝，`has_more`/applied 无处返回，只能退化为事件读取（多一次 poll），且 Done when 5 无法直接断言；需重新裁决 |

### 8.4 回退顺序

1. 任一 gate 红 → 先修根因；连续两次修不好 → 停手报告，不带病提交。
2. CC-1 已批准（028D07）；历史备选：若被拒则停，不实现 N 次 fallback。
3. CC-3 已批准（028D07）；历史备选：若被拒则先把 `has_more` 移到 sweep 事件并在 README 声明“需读事件”，再请 Oracle 裁决是否接受降级；不静默删断言。
4. R4 控制对照失败 → helper 修正；仍失败 → 重构 S4 两个 unknown 分支并重跑 G2b；仍失败 → 停。
5. R7（S5 缺口）→ 回到 S5 修谓词/阶段；S6 不绕开。
6. 任何“加一张表/加一个 lease/加一个 claim 路径”的诱惑 → 立即停；这是硬约束，不是实现选择。

---

## 9. 计划级验收清单（逐行可核对）

- [ ] **十窗口**：`test_g5.py` 恰有 K1–K10 十个函数/十条打印，逐条对应设计 §8 L410–419；无 K0/K11、无合并、无改名；K1–K3、K5–K10 都是独立 OS 子进程 + `SIGKILL`，K4 是 fixture-only SQL 错误注入。
- [x] **Oracle 15 项 ACCEPT（CC-1/2/3、D-S6-1…12）已落位计划与设计稿（chat 028D07）。**
- [ ] **重启证据**：每个 K 的恢复由**新** `recover_worker.py` 进程执行；child/worker/parent 的 `pg_backend_pid()` 互不相同；无同进程新连接；无 `sleep` 排序；README 记录该口径。
- [ ] **唯一发现面**：`recoverable_effects` 是 `SECURITY DEFINER`/`STABLE`/零 DML/固定 `search_path`/固定 7 列/`(lease_until,effect_id)`/上限 16/scope auth/排除 manual；其 `prosrc` 与注释不含 `insert|update|delete|pg_advisory*`。
- [ ] **唯一命令**：`command_recover` 是 `SECURITY INVOKER`、无表权、恰好一次 `v24.advance(`、无 `INSERT INTO|UPDATE v24.|DELETE FROM|pg_advisory_xact_lock`；同 key 同 bytes replay，同 key 异 scope/limit `request_conflict`，同 key 异 candidates replay（CC-2）。
- [ ] **一次 request/receipt**：一次 sweep 恰 1 条 `command_recover` effect + 1 条 request + sweep/action 事件；≤16 动作、一个 delta、一个事务；`successors=[]`、无 `settle`、无第二 effect。
- [ ] **replay_safe**：只回 `ready`、清 `claim_owner/lease_until`、保留 attempt/fence；下一次普通 claim 递增；旧 token `stale_claim` W0；reservation 计数 1（不重复 IO）。
- [ ] **no_replay**：只转 unknown；run `blocked_unknown`（或保留 cancel seal）；预算不退款；interaction/pending_steer 清空；model/tool 的 pin 处理分别正确；事件与正常 unknown 分支的控制对照通过。
- [ ] **manual**：不进入候选、不写、不占 16 上界、`manual_debt` 正确、不让 `has_more` 永久 true。
- [ ] **late receipt**：unknown 后 success → `receipt_conflict` W0，首次 receipt 不被覆盖；`detail` 保持 `{}`，host journal 引用由证据面记录（D-S6-7）。
- [ ] **23 码**：`error_v1` 闭集不变；S6 只使用既有码（`invalid_args`/`unauthorized`/`not_found_or_denied`/`request_conflict`/`effect_id_conflict`/`receipt_conflict`/`stale_claim`/`invalid_outcome`/`retry_with_closure`/`blocked_unknown`），不新增码。
- [ ] **十表**：无新表/列/索引/视图/队列/lease/cursor；DDL delta 只有 `c_effects_kind` 与 `c_events_entity` 两条 CHECK；loader 顺序 48→49→50 且三处（load.py 两清单、setup_db self-check）同步。
- [ ] **唯一可写 DEFINER**：`advance` 仍是唯一；`recoverable_effects` 只读；`event/request/effect` 的写入仍经 `advance`/`validate_and_apply_delta`。
- [ ] **G1-A 重述**：`read_definers` 加 `recoverable_effects`；wrapper 元组加 `command_recover` 且含 `v24.advance(`、无四个写词；`UPDATE v24.effects` allowlist 与 `pg_advisory_xact_lock` sole-producer 不变；`test_g1.py` 绿。
- [ ] **G2a/G2b/DDL 重述**：command kind 8→9；`command_recover` claim 被拒（`invalid_args`）；`test_ddl` 的 command claim/事件 entity 正负例；均为扩大覆盖，不是放宽。
- [ ] **K1–K10 证据**：每个 K 有 journal 路径、child/worker PID、十表前后 fingerprint、applied/skipped/has_more；K4 有 trigger 删除与十表 diff 为空；K5 有两次 replay 逐字节相同。
- [ ] **负例**：N1–N14 全有断言与写类（W0/W1/WD）；unauthorized/limit/`request_conflict`/`stale_claim`/`receipt_conflict` 都是 W0；noop/重复 sweep 是 W1；应用型 sweep 是 WD。
- [ ] **W1–W4**：每个 W 的 Done when 与 gate 命令可独立执行；W1–W3 不 commit；W4 一次里程碑提交（不 push）；9 个 gate 全 0。
- [ ] **收尾工件**：`docs/reviews/v24-conformance-matrix-2026-10-23.md` 的 G5 行从“未验证”改为“完成”并链接本计划/`test_g5.py`；`docs/reviews/v24-deviation-ledger-2026-10-23.md` 记录 D-S6-1…12、CC-1…3、A-S6-*；`v24/s6/README.md` 记录窗口表、命令、债务与实测证据。
- [ ] **文档纪律**：本文件是唯一新增；`git status --short` 只显示本文件（工作区其他未跟踪文件为既有线）；不编辑设计稿/pre-plan；不提交/推送；不跑 pytest/网络。

---

> **计划结语**：S6 的成功标准不是“多了一个恢复函数”，而是“恢复被证明为不存在第二个状态机”。K1–K10 的每一条都必须能回答三个问题：崩溃前哪条事实已提交？重启后哪条既有事实允许继续？哪条动作被明确禁止？如果任一 K 的答案需要一张新表、一个 lease、一个 cursor 或第二次 claim，S6 就没有完成，应停手回到设计裁决。
