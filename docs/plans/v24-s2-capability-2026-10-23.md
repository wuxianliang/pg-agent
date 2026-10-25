# v24 S2 能力面：Deep plan

日期：2026-10-23。状态：**S2 已实施并结项**。本文件保留计划正文；实际交付、实跑退出码与未覆盖项见 §1 进度、`docs/reviews/v24-conformance-matrix-2026-10-23.md`、`docs/reviews/v24-deviation-ledger-2026-10-23.md` 与 `v24/s2/README.md`。S2 = fiber/episode/slot/pin 的真实能力面 + `resolve` + `fiber_control` + child install admission + 叶子 `dispose`，自有 gate **G3a**。

## Goal

让「已激活 episode + 唯一 slot + activation pin」成为 S3 的 `start` 可以直接消费的真实能力面：`v24.resolve` 按 leaf-first realm 路由返回 live slot；`v24.fiber_control` 经 `advance` 完成 on/off/retry 的有界 reconcile（episode E1→E2、贡献 slot、activation pin、withdraw/release）；child `install` 在 G 内校验并固定 owner episode 身份；`v24.dispose` 完成叶子 install 的 `dispose_pending → host_release → disposed`。G3a 全绿，且 S1 的 G1 回归不破。

## Background

### 上游权威（只读）

- 设计稿 `docs/designs/v24-pg-agent-2026-10-22.md`（652 行）。S2 的设计范围＝§3.4（L205–207）、§6.2 child admission（L323–329）、§6.3（L331–339）、§6.4（L341–347）、§6.5（L349–355）、§6.7 叶子 dispose（L365–369）、§9 的 G3（L437）；`resolve` 签名在附录 B.3 L544 与 A.2 L623；wrapper/错误闭集见 B.3（L533–556）与 B.5（L588–606）。
- pre-plan `docs/plans/v24-pre-plan-2026-10-23.md:112–127`（S2 阶段卡）：发布合同＝`resolve` 行形状与 live predicate、activation pin 身份、episode E1→E2、control CAS/reconcile、withdraw/release、leaf dispose、child install 的历史 owner 身份；明确不做 owner 级联/scope close（S5）、run pin 与 start（S3）、loop provider adapter（S4）。
- 合同表 `v24-pre-plan-2026-10-23.md:203–204`：**C8** `resolve` 行形状 + live predicate；**C9** episode 身份 + activation/run pin XOR + E1→E2。二者在本计划冻结，S3–S5 消费。
- 阶段分解 `docs/analysis/v24-stage-decomposition-2026-10-23.md:22,37–42,68`：S2 的范围、G3a 子门、以及「S2 只能证明 activation-pin 半部，run-pin 归 G3b」。

### S2 必须冻结的开放项

- **O5（已由 S1 冻结，S2 实证）**：`u_episodes_ident (fiber_id,episode_id)` 非延迟；`u_episodes_open` 与 `u_slots_live` 是 partial unique index，同事务顺序敏感；E1→E2 必须「先关旧代 → 插新代 → 再切 `current_episode_id`」。S1 `test_ddl.py` 的 `[order] close/release before replacement succeeds` 已实测。
- **O6（S2 裁决）**：`fiber_control(action=retry)` 的目标、`failure_seq` 清理、CAS/no-op、未知资源门槛、唯一 reconcile；不得同时重试 install prepare。裁决见 §4.13 D-S2-3。
- **C8/C9**：`resolve` 的精确返回列与 live 谓词；episode 身份、activation pin、E1→E2 的写序。

### Oracle 裁决（chat `untitled-chat-513DAB`，2026-10-23）

| # | 问题 | 裁决 |
|---|---|---|
| 1 | reconcile 驱动 | **A**：`fiber_control` 同一次 advance 内执行有界阶段；成功则 `fiber_reconcile=succeeded`；屏障未清则保持 ready、`disposition='deferred'`、零领域写；多阶段排空归 S5/S6 |
| 2 | retry 语义 | **A**：只清已记录失败；无失败时幂等；不干预 `installs.state` |
| 3 | resolve 形状/live | **A**：严格 B.3 六列；provider fiber 由 slot 关联得到；live 用完整谓词 |
| 4 | E1→E2 与 activation pin | **A**：无屏障 leaf 的退役/撤回/解 pin/关闭可原子完成；屏障预检保证 deferred 零写 |
| 5 | dispose 遇未排空义务 | **A**：先持久化 `dispose_pending` 并阻断新增义务；条件满足才发 `host_release`；S5 继续排空 |
| 6 | inspect 边界 | **A**：S2 只做 `host_release success → disposed`；`preparing`/`prepare_unknown` 留 `dispose_pending`，inspect 收敛归 S5，G3a 显式标未验证 |

### S1 的既有实现基线（S2 直接消费）

- `v24.advance` 唯一写口；G=`pg_advisory_xact_lock(24,1)` 首锁；闭包发现→全序加锁→解释器→delta 校验→写入。
- 十表与约束：`episodes`（含 `u_episodes_ident`、`u_episodes_open`）、`fibers`（`current_episode_id`、`want_on`、`control_seq`、`failure_seq/failure`、`next_contribution_seq`）、`slots`（`u_slots_live (realm,key) WHERE released_at IS NULL`）、`pins`（activation/run XOR、生成列 `consumer_id`）、`installs`（`u_installs_ident`、`i_installs_owner`）。
- 解释器：`interpret_command` 只实现 `command_scope_control` 与 `command_install`（root）；`command_fiber_control`/`command_dispose` 是抛 `0A000` 的显式接缝。`interpret_settlement` 只实现 `host_prepare`。`validate_and_apply_delta` 只实现 scope 与 install 足迹。
- `install` 解释器当前对 `owner_fiber_id IS NOT NULL` **一律 W0 `invalid_args`**（child admission 在 S1 故意缺席）。
- ACL：`v24_owner` 拥有对象；三个协议角色零表权；四个纯 helper + `advance`/`scope_control`/`install` 授 EXECUTE。
- G1 门禁：`v24/s1/test_g1.py` 断言「`prosecdef=true` 恰为 `{advance}`」「PUBLIC 无 EXECUTE」「每函数 owner=`v24_owner`」「`UPDATE v24.effects` 只出现在 advance 与具名 INVOKER helper」。

### 仓库既有约定（S2 沿用）

- PostgreSQL 18.4（pgembed），psycopg2，Python 3.12；测试是独立脚本，退出码 0 = 通过；不联网；Fake-only。
- **S1 不得被破坏**：S2 落地后 `load.py`、`setup_db.py --self-check`、`test_ddl.py`、`test_g1.py` 必须仍退出 0。S1 的门禁断言只能按新函数集合**收紧/对齐**，不得删除或放宽。
- 一个 stage 一次提交；收尾工件（矩阵、台账、`v24/s2/README.md`）齐备才提交。

## 1. 执行索引

| 项 | 内容 |
|---|---|
| Goal | 见上 |
| Done when | G3a 全部具名断言实跑退出 0；S1 四个 gate 回归退出 0；S2 收尾工件就位 |
| Key files | `v24/sql/45_capability.sql`（新）、`v24/sql/50_permissions.sql`（追加授权）、`v24/load.py`（追加 45）、`v24/s2/test_g3a.py`（新）、`v24/s2/README.md`（新）、`v24/s1/test_g1.py`（最小回归对齐） |
| Dependencies | S1 全部交付；O5 已冻结；本文件的 C8/C9 与 O6 裁决 |
| Size | L（新解释器 3 个 + 读函数 1 个 + 闭包扩展 + gate） |

### 工项

| # | 工项 | 交付 | Done when | 文件 | 依赖 | 规模 |
|---|---|---|---|---|---|---|
| W1 | 能力面骨架 + `resolve` | 新 SQL 文件、loader 追加、`resolve` 读函数、catalog/ACL 基线 | `resolve` 六列、输入序、live 谓词；未知 key 返回 `live=false`；`state()` 前后零写；STABLE/INVOKER | `45_capability.sql`、`load.py`、`test_g3a.py` | — | M |
| W2 | 闭包、claim、delta 基础设施 | 闭包 CTE 扩展（fiber/install 子图、resolved slots）、`fiber_reconcile` 不可 claim、唯一 reconcile 部分索引、successor 可生于 succeeded、既存 reconcile 可被 settle | 闭包不足 `retry_with_closure` 零写；`fiber_reconcile` claim 得 `invalid_args`；每 fiber ≤1 未结算 reconcile；闭包锁在解释器之前；settle 的 applier 校验就位（行为证据由 W4 的产生者提供，本阶段不伪造） | `30_advance.sql`、`40_interpreters.sql`、`45_capability.sql`、`test_g3a.py` | W1 | M |
| W3 | fiber 实例 + child install admission | `install` 为每个 install 建一个 inactive fiber；`interpret_install` 接受 owner，校验并固定历史身份 | 每个 install 恰一条 deterministic fiber；owner active/want_on/current 时写两列；disposed/owner_closing/install_not_ready 各得对应 W1；E2 切换后旧行 FK 不变 | `45_capability.sql`、`test_g3a.py` | W2 | M |
| W4 | `fiber_control` on + activation | wrapper、CAS/action 分派、resolve 依赖、episode/slot/pin 写入、失败原子性、retry | 空 inject 可激活；有 requires 时 pin 精确；缺依赖 `dependency_unresolved` 且无 episode/slot/pin；`provide_conflict`；retry 行为 | `45_capability.sql`、`test_g3a.py` | W3 | L |
| W5 | off / withdraw / release / E1→E2 | 两阶段退役；activation pin 屏障；deferred 语义；二次 on 得 E2 | 屏障时 slot withdrawn 未 released、episode retiring、effect 仍 ready；解除后 closed；E2 epoch+1 且旧行保留 | `45_capability.sql`、`test_g3a.py` | W4 | L |
| W6 | leaf `dispose` + `host_release` | `dispose` wrapper/解释器、`host_release` 结算、inspect 边界 | installed→dispose_pending→disposed；重放幂等；新 key `already_terminal`；有活 fiber/child 时不下发 host_release；prepare_unknown 不前进 | `45_capability.sql`、`test_g3a.py` | W5 | L |
| W7 | G3a 全绿 + 收尾 | 全部断言、S1 回归对齐、矩阵/台账/README | 五个 gate（S1 四个 + G3a）退出 0；收尾工件就位 | 上述 + `docs/reviews/*` | W6 | M |

**实施顺序**：W1 → W2 → W3 → W4 → W5 → W6 → W7，严格串行。每步 Done when 有一条不绿即停。

**进度（2026-10-23）**：**W1–W7 已完成并由编排方实跑验证；S2 结项。**

- W1：`v24/sql/45_capability.sql` 的 `resolve`（STABLE/INVOKER、六列、leaf-first、无 fallback）；`load.py` 与 `setup_db.py` 的 canonical 列表追加 45；`50_permissions.sql` 授权三角色。
- W2：`30_advance.sql` 扩闭包（installs→fibers/installs/effects、episodes→slots/pins、fibers→reconcile effects、resolve seeds）与 512 上限；claim 排除 `fiber_reconcile`；`40_interpreters.sql` 的 applier 支持 `settle[]`、born-settled successor、归属列与 `command_fiber_control` footprint；`u_effects_reconcile` 部分唯一索引。
- S1 对齐（只增不减）：`setup_db.py` 的 canonical 期望 7 文件；`test_g1.py` 的 G1-A 允许 `validate_and_apply_delta` 含 `UPDATE v24.effects`（仍 INVOKER、无授权），ACL 期望集合加 `resolve`。
- 实跑：五门（load、setup self-check、test_ddl、test_g1、test_g3a）退出码均为 **0**。
- W2 的 settle/born-settled 行为证据由 W4 的产生者提供；`test_g3a.py` 不伪造解释器。
- W3：`interpret_install` 接受 owner（JSON null 视为 root）；每个新 install 同事务创建一条 deterministic inactive fiber（`md5(install_id::text || ':fiber')`，`want_on=false`、`current_episode_id=NULL`）；child admission 依次判 `already_terminal`/`install_not_ready`/`owner_closing`，`owner_episode_id` 由 `current_episode_id` 推导；不存在的 owner 在闭包发现前 W0 `invalid_args`；owner 列与 fiber 行的写由 applier 复核。
- W3 实跑：`test_g3a.py` 的 G3a-J 覆盖 root 单 fiber、replay/identity reuse 不增 fiber、child 固定 `(owner_fiber_id,owner_episode_id)`、E1→E2 后旧行不变、disposed/不接纳/无 active episode/不存在 owner 四类拒绝的原子性。
- W4：新增 `v24.fiber_control` wrapper（INVOKER）、`interpret_fiber_control` 与 `command_fiber_control` 足迹；CAS 用 `stale_generation`；on/retry 执行一次有界 activation（episode → slots → activation pins → 切 current → settle/born-settle reconcile）；失败写 `failure_seq/failure` 并以 W1 receipt 收束；off 是 W5 的 durable-intent seam（ready reconcile + deferred，不动 episode）。同时实现 `check_policy` v1（`equals` 路径谓词）与 install admission 的 requires/provides 形状校验。
- W4 实跑：空 inject 激活、replay/no-op/CAS/retry-noop、依赖失败→补 provider→retry 成功并 pin、policy=false、provide_conflict；`fiber_control` 的 INVOKER/无写静态断言。
- W5：off 两阶段机。阶段 A：`active→retiring`、`retire_started_at=now()`、本代 slots `withdrawn_at=now()`；阶段 B（屏障已清时同一 advance 内完成）：释放本代 consumer pins（`released_by_effect`=reconcile id）、slots `released_at`、episode `closed+closed_at`、fiber `current_episode_id=NULL`，settle/born-settle reconcile。屏障 = 任一外部 activation pin 仍引用本代 slot / 任一 child install 未 disposed / 本 install 有未结算的 host_prepare/host_release；命中则阶段 A 提交、阶段 B 零写、`deferred`。applier 增加 episodes/slots/pins 的 update 校验与应用；事件校验允许引用本 fiber 的既存行。
- W5 实跑：A pin B 的 slot → B off `deferred`（slot withdrawn 未 released、episode retiring、reconcile ready）；A off 释放 pin；B 再 off 完成 release/close/E1 清空；B 再 on 得 epoch+1 的 E2，E1 与旧 pin 行保留。
- W6：`v24.dispose` wrapper + `interpret_dispose`；`dispose_pending` 持久意图，义务（episodes closed/current NULL、slots released、child installs disposed、无未结算 host effect）满足后写自有 fiber 墓碑并下发确定性 `host_release`（`md5(command_effect_id||':host_release:0')`，reservation `v24:host_release:<effect_id>`）；`preparing`/`prepare_unknown` 停在 `dispose_pending`，inspect 收敛留 S5；`disposed` 的新 key 返回 `already_terminal`。`interpret_settlement` 增加 `host_release`：success → `disposed+disposed_at` + `install_disposed`，failure/unknown → 保持 `dispose_pending`；`dispose_pending` 期间的 host_prepare receipt 一律 `receipt_conflict`。
- W6 实跑：释放后继与 reservation、成功 dispos、同 key replay、新 key terminal、active fiber 阻塞→off→二次 dispose、`prepare_unknown` 停住、release failure 不写 disposed、preparing 被 dispose 后拒收 host_prepare。
- W7：矩阵扩为 S1+S2（G3a-A…L，G3 父行标「部分：G3a 绿」，G3b 未验证/S3）；台账补 D-S2-1…11 与「G3 子门拆分/S1 对齐」非偏差声明；`v24/s2/README.md` 定稿；五个 gate 全跑。
- 最终实跑：`load.py`、`setup_db.py --self-check`、`test_ddl.py`、`test_g1.py`、`test_g3a.py` 退出码均为 **0**。

## 2. 定位与边界

### 2.1 在设计稿中的位置

S2 是「能力」层，不碰六动词：它建立 episode/pin/slot 的事实与解析，供 S3 的 `start` 在 G 内固化 run pin。S2 完成后：

- `resolve` 可被 S3 的 start 与 SDK 只读消费；
- `fiber_control(on)` 可把 installed install 激活成 active episode，并持有 activation pin；
- child install 可把 owner 的不可变 `(fiber_id,episode_id)` 固定下来；
- `dispose` 可释放叶子 install 的引用并走 `host_release`。

### 2.2 发布合同（后续阶段消费）

| 合同 | 内容 | 消费者 |
|---|---|---|
| **C8 resolve** | `v24.resolve(uuid,text[]) → TABLE(key,slot_id,provider_episode_id,descriptor,descriptor_digest,live)`；leaf-first realm；live 谓词见 §4.1 | S3 start、S6 resolve 扫描、SDK |
| **C9 episode/pin** | `episodes(fiber_id,episode_id)` 不可变身份；activation pin 的 `consumer_episode_id`+`consumer_epoch`；E1 关闭→E2 插入→切 current；provider slot 固定 | S3 run pin、S4 settlement、S5 排空 |
| **C10 control** | `fiber_control` 的 CAS 码、reconcile effect 形状、no-op/retry 语义、deferred 语义 | S3（start 前置 on）、S5（多阶段驱动） |
| **C11 dispose/host_release** | `dispose_pending` 的持久意图、release reservation、host_release 成功→disposed | S5 完整闭包、S6 recovery |

### 2.3 明确不做

- 不做 run pin、`start`、run 状态机（S3）；G3a 只证明 activation-pin 半部，run-pin 半部标未验证。
- 不做 owner 级联、scope close、完整 dispose 闭包、递归 children 屏障（S5）。
- 不做 `inspect_resource` 的收敛（S5）；S2 只把它作为 `dispose` 的前置门槛并显式标未验证。
- 不做 `check_policy` 的任意谓词语言；只支持一个封闭的 v1 形状（§4.6.3）。
- 不做 loop、model/tool、预算、spawn、seal（S3/S4）。
- 不做 provider 切换的「等待新 provider 出现」调度；只保证旧 slot 真正 release 前新 slot 不能占用同 realm/key（唯一索引已保证）。

## 3. 设计 § → 工项 → gate 映射

| 设计锚 | 内容 | 工项 | G3a 断言 |
|---|---|---|---|
| §3.4 L205–207 | realm 路由、空 inject、withdraw/release、activation 失败无半行 | W1、W4、W5 | G3a-A/C/D/E/F |
| §6.2 L323–329 | child install admission、owner 身份、`install_not_ready`/`already_terminal` | W3 | G3a-J |
| §6.3 L331–339 | on/off/retry、CAS、唯一 reconcile、有界阶段、deferred | W4、W5 | G3a-B/H/I |
| §6.4 L341–347 | 最小 episode、activation pin 不可替代 | W4 | G3a-B/C/F |
| §6.5 L349–355 | resolve、硬依赖、realm/key、pin 语义、withdraw/release | W1、W4、W5 | G3a-A/C/F |
| §6.7 L365–369 | leaf dispose、host_release、inspect 门槛 | W6 | G3a-K |
| §9 L437 | G3a 的四条 done-when + 负例 | 全部 | G3a-A…L |
| App A.2 L623 / B.3 L544 | `resolve` 六列签名 | W1 | G3a-A |
| App B.3 L533–556 | wrapper 形状、错误闭集 | W3、W4、W6 | G3a-J/K |
| App B.5 L588–606 | 幂等/重放/CAS/no-op | W4、W5、W6 | G3a-H/I/K |

## 4. DDL 与函数草案

### 4.0 文件与加载顺序

新增一个 SQL 文件，插在 `40_interpreters.sql` 与 `50_permissions.sql` 之间：

```text
00_schema → 10_schema → 20_triggers → 30_advance → 40_interpreters
→ 45_capability → 50_permissions
```

`v24/load.py` 的 `SQL_LOAD_ORDER` 与 canonical 列表追加 `45_capability.sql`。`50_permissions.sql` 必须仍是最后：它的 fail-closed `DO` 块在全部函数存在后检查 owner/`search_path`/PUBLIC。

`45_capability.sql` 放 `resolve`、`fiber_control`/`dispose` wrapper 与部分索引。**闭包 CTE 与 delta applier 的扩展直接改 `30_advance.sql` / `40_interpreters.sql`**：这两处是数百行的既有函数，若在 45 里 `CREATE OR REPLACE` 整段复制，会让同一函数存在两份定义并长期漂移；直接改的 git diff 更小、更可审。`50_permissions.sql` 追加新函数的 EXECUTE 与 fail-closed 断言。记 D-S2-11。

### 4.1 `resolve`

```sql
CREATE FUNCTION v24.resolve(p_scope_id uuid, p_keys text[])
RETURNS TABLE(key text, slot_id uuid, provider_episode_id uuid,
              descriptor jsonb, descriptor_digest bytea, live boolean)
LANGUAGE sql STABLE SECURITY INVOKER
SET search_path = pg_catalog, v24
AS $$ ... $$;
```

**返回形状冻结为 B.3 的六列**，不增列；provider fiber 由 `slots.fiber_id` 关联获得。输入顺序用 `unnest(p_keys) WITH ORDINALITY` 保留；每个 key 恰一行，未解析时 `live=false` 且其余列为 NULL。

**realm 路由**（leaf-first，不 fallback）：

```sql
WITH RECURSIVE chain AS (
  SELECT s.scope_id, s.parent_id, s.route_path, s.realm_routes, s.default_realm
  FROM v24.scopes s WHERE s.scope_id = p_scope_id
  UNION ALL
  SELECT p.scope_id, p.parent_id, p.route_path, p.realm_routes, p.default_realm
  FROM v24.scopes p JOIN chain c ON p.scope_id = c.parent_id
)
SELECT realm_routes->>k AS realm
FROM chain
WHERE realm_routes ? k
ORDER BY cardinality(route_path) DESC, scope_id
LIMIT 1;                     -- 无显式项时再取最深非空 default_realm
```

**live 谓词**（冻结）：

```sql
s.released_at IS NULL
AND s.withdrawn_at IS NULL
AND e.state = 'active'
AND f.disposed_at IS NULL
AND sc.close_requested_at IS NULL
```

其中 `s`=slot、`e`=provider episode、`f`=provider fiber、`sc`=provider fiber 的 scope。`u_slots_live (realm,key) WHERE released_at IS NULL` 保证至多一条；withdrawn 仍占唯一键但不 live。

**边界**：`p_keys IS NULL` → 空集；数组长度 > 256 → `22023 invalid_parameter_value`（读函数不返回 JSON 错误封套）；NULL/空字符串 key → `live=false`；`p_scope_id` 不存在 → 全部 `live=false`（不泄漏存在性）。函数不写任何表。

### 4.2 闭包发现扩展（W2）

`advance` 的 closure CTE 目前从 effects/scopes/runs/installs/fibers/episodes/slots/pins 展开，并已把 command payload 的 `fiber_id`/`install_id` 作为种子。S2 追加四类边，**全部在加锁之前**：

| 新边 | 用途 |
|---|---|
| `installs → fibers`（`fibers.install_id`） | dispose/on 需要锁本 install 的所有 fiber |
| `installs → installs`（`owner_fiber_id/owner_episode_id` 相等） | dispose 需要枚举 child installs（历史身份，不读 current 指针） |
| `installs → effects`（`effects.request->>'install_id'`） | dispose 需要锁未结算的 host_prepare/host_release |
| `episodes → slots`（`slots.episode_id`） | off 需要锁本代全部贡献 slot |
| `episodes → pins`（`pins.consumer_episode_id`） | off 需要看到引用本 episode 的 activation pin |
| `fibers → effects`（`effects.fiber_id`，仅 `kind='fiber_reconcile'`） | 续驱时 `settle[]` 的目标必须在闭包内并被 `FOR UPDATE` |

另加两条**命令专用种子**：

- `command_fiber_control` 且 `payload.action='on'`：读该 fiber 的 install.requires，用 §4.1 同一路由/live 谓词做一次**不加锁**的 resolve，把命中的 `slots` 加入闭包；slots 的既有展开会带出 provider fiber/episode，pins 的既有展开会带出既有 pin。
- `command_dispose`：从 `install_id` 出发走上面三条 install 边。

**闭包大小上限**：实体总数 > 512 ⇒ `retry_with_closure` 零写（防止无界子树遍历，§2.5）。解释器在已锁行上复算 resolve；若 live slot 集合与闭包不一致（新增/消失/换行）⇒ `retry_with_closure` 零写，不得持锁补锁。

### 4.3 claim 资格（W2）

`advance` 的 claim 分支当前只排除 command kind 与 terminal。S2 增加：**内部 kind 不可 claim**。

```sql
IF v_effect.kind IN ('fiber_reconcile') THEN
  RETURN v24.error_v1('invalid_args');
END IF;
```

理由：`fiber_reconcile` 是 DB-only 工作项，没有外部 IO、没有 host claim；允许 claim 会产生第二个 lifecycle 队列。`host_release`/`inspect_resource` 仍是可 claim 的 host kind。

**唯一未结算 reconcile**（部分唯一索引，追加在 45）：

```sql
CREATE UNIQUE INDEX u_effects_reconcile ON v24.effects (fiber_id)
  WHERE kind = 'fiber_reconcile' AND status IN ('ready','claimed');
```

### 4.4 reconcile effect 的创建与结算（W2）

S2 需要 `fiber_reconcile` 在同一次 advance 内「创建并结算一个阶段」，并在续驱时结算**同一条** ready effect。现有 delta 的 `successors` 只能生为 `ready`，且不能更新既有 effect，因此扩展两个封闭键：

**新 effect（born-settled successor）**：

```json
{"effect_id": uuid, "ordinal": 0, "kind": "fiber_reconcile",
 "fiber_id": uuid, "request": {...}, "status": "succeeded", "outcome": {...}}
```

**既有 effect（settle）**：

```json
{"settle": [{"effect_id": uuid, "status": "succeeded", "outcome": {...}}]}
```

规则：

- `successors[].status` 省略 ⇒ `ready`（S1 行为不变）；`succeeded` 仅允许 `kind='fiber_reconcile'`，且必须带 `outcome`；
- `fiber_id` 仅 `fiber_reconcile` 可带且必带（`u_effects_reconcile` 的索引键）；其他 kind 携带 ⇒ `invalid_outcome`；
- `settle[]` 的每项 targets 必须在闭包内、`kind='fiber_reconcile'`、`status='ready'`；否则 `invalid_outcome` 零写；
- 同一 delta 不得对同一 effect 既 insert 又 settle；
- applier 插入 born-settled 行时写 `settled_at=now()`；`settle[]` 更新 `status/outcome/settled_at`，不新建行；
- applier 对非 `fiber_reconcile` 的 settle ⇒ `invalid_outcome` 零写；
- **W1 错误 delta**：`{write:true, error:{...}, effect:{scope_id, fiber_id}}`——applier 在错误分支写归属列、status 固定 `failed`，不得让 `effect.status` 覆盖 `failed`；
- 这是 S1 计划 §4.14.4 delta 形状的 S2 增量，记 D-S2-1、D-S2-9、D-S2-10。

### 4.5 `fiber_control` wrapper

```sql
CREATE FUNCTION v24.fiber_control(p_fiber_id uuid, p_action text,
  p_expected_control_seq bigint, p_request_key text) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER
SET search_path = pg_catalog, v24
AS $$ ... $$;
```

只构造 outcome 并委托 `advance`：`kind='command_fiber_control'`，payload `{fiber_id,action,expected_control_seq}`，`canonical_bytes=base64(canonical_json(payload))`，`effect_id=effect_id_for(principal_id(session_user),p_request_key,'command_fiber_control')`。本地只做 `p_action ∈ {on,off,retry}`、`p_expected_control_seq >= 0`、`p_request_key` 长度 1..512 的快速检查；完整 CAS/授权由 advance 重做。

### 4.6 解释器 `command_fiber_control`（W4）

#### 4.6.1 CAS 与 action 分派

1. 锁内读 `fibers`；不存在 ⇒ W0 `invalid_args`。
2. `p_expected_control_seq <> fiber.control_seq` ⇒ **W1 `stale_generation`**（D-S2-2）。
3. `action` 闭集外 ⇒ W0 `invalid_args`。
4. 目标与当前状态已完全一致 ⇒ committed、零领域差异、不新建 reconcile（no-op receipt 仍写 request/effect）。
5. 否则 `control_seq+1`，写 `want_on`（on→true，off→false，retry 保持），并产生唯一 `fiber_reconcile`。

**no-op 的精确定义**：

- on：`want_on=true` ∧ `current_episode_id IS NOT NULL` ∧ 该 episode `state='active'` ∧ 无未结算 reconcile；
- off：`want_on=false` ∧ `current_episode_id IS NULL` ∧ 无未结算 reconcile；
- retry：`failure_seq IS NULL`（无失败可重试）⇒ no-op。

**未结算 reconcile 存在时**：同向命令（on/on、off/off）**继续驱动一个阶段**，而不是 no-op；异向命令只更新 `want_on/control_seq`（目标反转），不新建第二个 reconcile。这条是 S2 的驱动口径（D-S2-3）：设计 §6.3 的「目标已一致则幂等」解释为「目标已**完成**」，retiring/ready 不算完成。

**reconcile effect 的身份与归属列**：

```text
首次创建：effect_id = md5(command_effect_id::text || ':fiber_reconcile:0')::uuid
续驱：复用闭包内 status='ready' 的那一条，不重新派生、不新建
command effect（含 W1 错误分支）：scope_id = fiber.scope_id, fiber_id = p_fiber_id
reconcile effect：scope_id = fiber.scope_id, fiber_id = p_fiber_id,
                  episode_id = 本阶段涉及的新 episode（activation 时）
```

`effect` 补丁因此扩展 `{scope_id, fiber_id, episode_id}` 三个可选列（D-S2-10）；applier 必须验证它们与已锁对象一致（`scope_id = fibers.scope_id`、`fiber_id = p_fiber_id`），不一致 ⇒ `invalid_outcome` 零写。这样 W1 失败 receipt 也带正确的 fiber 归属，闭包与审计不依赖 request jsonb。

#### 4.6.2 activation（on）

前置按下列次序判定（任一失败 ⇒ **W1 稳定失败 receipt**，并写 `fibers.failure_seq=control_seq`、`fibers.failure={code,detail}`；fiber 保持 `want_on=true`、`current_episode_id=NULL`）：

| 次序 | 条件 | 码 |
|---:|---|---|
| 1 | fiber.disposed_at IS NOT NULL | `already_terminal` |
| 2 | install.state <> 'installed' | `install_not_ready` |
| 3 | scope.close_requested_at IS NOT NULL | `scope_closed` |
| 4 | 任一 require 无 live slot，或 check_policy=false | `dependency_unresolved` |
| 5 | 任一 provide 的 `(realm,key)` 已有 live slot | `provide_conflict` |

**成功写序**（O5，严格）：

```text
1. INSERT episode E2 (epoch = coalesce(max(epoch),0)+1, state='active',
   activation_effect = reconcile_effect_id, opened_at=now())
2. INSERT slots (每个 provides[] 一项，contribution_seq = next_contribution_seq++)
3. INSERT activation pins (每个 require 一项)
4. UPDATE fibers SET current_episode_id=E2
5. reconcile effect → succeeded；events
```

E1 已关闭时 `u_episodes_open` 允许 E2；E1 未关闭时**不得**插 E2（partial unique 立即 `23505`），必须先走 §4.6.3 的 off 阶段。

activation pin 形状：

```json
{"consumer_type":"activation","consumer_episode_id":E2,
 "consumer_epoch":E2.epoch,"key":require.key,
 "slot_id":resolved.slot_id,"provider_fiber_id":slot.fiber_id,
 "provider_episode_id":slot.episode_id,
 "descriptor_digest":slot.descriptor_digest,
 "created_by_effect":reconcile_effect_id}
```

slot 形状：每个 `provides[]` 项 `{realm,key,descriptor}`；`descriptor_digest=sha256(convert_to(canonical_json(descriptor),'UTF8'))`；`contribution_seq` 从 `fibers.next_contribution_seq` 起逐项 +1；`episode_id=E2`、`fiber_id=F`。

#### 4.6.3 deactivation（off）

**阶段 A（同一次 advance）**：

```text
episode.state: active → retiring, retire_started_at=now()
slots: withdrawn_at=now() WHERE episode_id=E AND released_at IS NULL
```

**阶段 B（同一次 advance，若屏障已清）**：

```text
释放本 episode 的 activation pins（released_by_effect=reconcile_id, released_at=now()）
释放本 episode 的 slots（released_at=now()）
episode.state='closed', closed_at=now()
fibers.current_episode_id=NULL
```

**阶段 B 的屏障**（任一存在 ⇒ `disposition='deferred'`，reconcile 保持 ready，**零阶段 B 写**）：

- 任一 `pins.provider_episode_id = E AND released_at IS NULL`（别的 consumer 还引用本 episode 的 slot）；
- 任一 run pin（`consumer_run_id` 非空）——S2 无 run，恒无；
- 任一 child install 的 `(owner_fiber_id=F, owner_episode_id=E)` 尚未 `disposed`；
- 任一 `host_prepare`/`host_release` effect 引用本 install 尚未结算。

阶段 A 已提交、阶段 B 被屏障挡住时，返回 `deferred`——这是「下一个阶段无副作用」，不是「整个命令无写」。矩阵与 README 必须这样写，不得宣称零写。

#### 4.6.4 retry（O6）

- `failure_seq IS NULL` ⇒ no-op committed；
- 否则清 `failure_seq/failure`、`control_seq+1`，按当前 `want_on` 产生唯一 reconcile；若 `want_on=false`，归到 off 的阶段机；
- **绝不**改 `installs.state`、不重建 `host_prepare`、不重置 reservation；prepare retry 属于 `install` 面，S5 处理。

### 4.7 fiber 实例 + child install admission（W3）

**fiber 行的创建者（设计未明说，S2 冻结）**：`install` admission 为每个新 install 创建**恰一个** inactive fiber：

```text
fiber_id        = md5(install_id::text || ':fiber')::uuid
install_id      = 新 install
scope_id        = install.scope_id
owner_fiber_id  = install.owner_fiber_id（root 为 NULL）
owner_episode_id= install.owner_episode_id（root 为 NULL）
want_on=false, control_seq=0, current_episode_id=NULL,
next_contribution_seq=0, created_by_effect=install command effect
```

理由：设计 §6.1「install 完成不表示 fiber active」与 §3.1.6「fiber 是作用域中的组件实例」要求 fiber 在激活前已存在；`fiber_control` 的入参只有 `fiber_id`，无法自行创建。fiber_id 确定性派生，客户端可从 install_id 重算，无需改 `emitted` ABI（S1 的 `install_settlement_w5` 断言 `emitted` 长度不变）。记 D-S2-7。

`interpret_install` 当前对 `owner_fiber_id IS NOT NULL` 直接 W0 `invalid_args`。S2 改为：

| 检查（G 内、已锁 owner fiber/episode） | 失败码 | 写类 |
|---|---|---|
| owner fiber 不存在 | `invalid_args` | W0 |
| `disposed_at IS NOT NULL` | `already_terminal` | W1 |
| `want_on=false` | `owner_closing` | W1 |
| `current_episode_id IS NULL` 或该 episode `state <> 'active'` | `install_not_ready` | W1 |
| scope 已 close | `scope_closed` | W1（S1 已有） |

成功时 `owner_episode_id = fiber.current_episode_id`，两列与 install 行同一事务写入；复合 FK 指向 `episodes(fiber_id,episode_id)`，**不引用** `fibers.current_episode_id`。E2 切换后旧 install 的两个 owner 列保持不变。child 的 fiber 实例继承同一对 owner 列。

不要求 `install.scope_id = owner_fiber.scope_id`：child 可落在 owner scope 的子 scope；scope 关闭的排空由 owner 身份枚举，不靠 scope 相等（D-S2-4）。

### 4.8 `dispose` + `host_release`（W6）

```sql
CREATE FUNCTION v24.dispose(p_install_id uuid, p_request_key text) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER
SET search_path = pg_catalog, v24;
```

`kind='command_dispose'`，payload `{install_id}`，effect_id 由 `(principal,request_key,'command_dispose')` 派生。

解释器规则：

1. install 不存在 ⇒ W0 `invalid_args`。
2. `state='disposed'`：同 key ⇒ replay；新 key ⇒ W1 `already_terminal`。
3. `state='dispose_pending'`：幂等；若义务已满足且尚无未结算 host_release，下发一个；否则 committed 无 successor。
4. 其他状态：先写 `dispose_pending`（幂等），再检查义务；满足才下发 host_release。
5. `preparing`/`prepare_unknown`：写 `dispose_pending` 后**停住**，不下发 host_release（inspect 未验证，S5 收敛）。
6. 义务：本 install 的所有 episode `state='closed'` 且 `fibers.current_episode_id IS NULL`；slots 全 `released_at IS NOT NULL`；所有 child installs `state='disposed'`（按 owner 历史列枚举）；本 install 相关的 host_prepare/host_release 无未结算 responsibility。
7. 义务满足后，**本 install 自有 fiber 的墓碑由 dispose 自己写**：`UPDATE fibers SET disposed_at=now(), want_on=false WHERE install_id=iid AND disposed_at IS NULL`（`c_fibers_tombstone` 要求 `want_on=false`；activation 失败后 `want_on` 仍为 true，必须一并置 false）。理由：设计未给 fiber 单独的 dispose 动词，而 §6.6 的退出偏序要求 fiber 先于 install dispose；`fiber_control(off)` 必须保留 fiber 以便 E1→E2，因此墓碑只能落在 dispose。child fiber 的级联墓碑归 S5（D-S2-8）。

host_release successor：

```json
{"effect_id": md5(command_effect_id || ':host_release:0')::uuid,
 "ordinal": 0, "kind": "host_release",
 "request": {"install_id": iid,
             "reservation": "v24:host_release:" || <release_effect_id>},
 "status": "ready"}
```

结算：`interpret_settlement` 增加 `host_release` 分支；`validate_and_apply_install_delta` 在 `settling` 时要求 install.state=`dispose_pending`，success ⇒ `state='disposed'`、`disposed_at=now()`、事件 `install_disposed`；failure/unknown ⇒ state 不变，effect 记 failed/unknown（unknown 的 `resource_quiesced_at` 保持 NULL）。dispose_pending 期间到达的 host_prepare receipt ⇒ `receipt_conflict`（W0），不得把 install 拉回 installed。

### 4.9 delta 足迹（W4–W6）

`validate_and_apply_delta` 增加两个 footprint：

| kind | 允许写 |
|---|---|
| `command_fiber_control` | `episodes` insert/update、`fibers` update（current/want_on/failure/next_contribution_seq）、`slots` insert/update、`pins` insert/update、events、successors（唯一 `fiber_reconcile`）、effects update（仅既存 `fiber_reconcile` 的 `settle[]`） |
| `command_dispose` | `installs` update（state/dispose_effect）、`fibers` update（disposed_at）、events、successors（唯一 `host_release`） |

`command_install` 的 footprint 追加 `fibers` insert（inactive 实例）与 `owner_fiber_id/owner_episode_id`（S1 已允许 installs insert）。其他表/目标 ⇒ `invalid_outcome` 零写。所有写仍由 `advance` 的 applier 执行；解释器只返回 delta（R4：advance 不做业务判断）。

### 4.10 错误码：S2 的新生产者

| 码 | 写类 | S2 生产者 |
|---|---|---|
| `stale_generation` | W1 | `fiber_control` CAS 不匹配 |
| `already_terminal` | W1 | 已 disposed 的 fiber / install |
| `install_not_ready` | W1 | `on` 时 install 非 installed；child install 时 owner 无 active episode |
| `owner_closing` | W1 | child install 时 owner `want_on=false` |
| `dependency_unresolved` | W1 | activation 缺 live slot 或 `check_policy=false` |
| `provide_conflict` | W1 | activation 的 `(realm,key)` 已有 live slot |

S2 后仍未产生（7 个）：`not_found_or_denied`、`registration_stale`、`interaction_mismatch`、`provider_unavailable`、`budget_exceeded`、`blocked_unknown`、`cleanup_cycle`。矩阵必须继续分列「已产生/未产生」。

### 4.11 ACL（W7）

- `resolve`：`SECURITY INVOKER`、STABLE；GRANT EXECUTE 给 `v24_admin`/`v24_service`/`v24_operator`；PUBLIC 无。
- `fiber_control`、`dispose`：INVOKER wrapper；GRANT 给三个协议角色（design §4.19：非 create_root 的 command 三角色均可提交）。
- advance 内部矩阵追加：`command_fiber_control`/`command_dispose` 按「非 create_root command」放行三角色；`fiber_reconcile` 无 claim、无 host settlement 授权。
- `50_permissions.sql` 的 fail-closed 块继续断言：每函数 owner=`v24_owner`、DEFINER `search_path`、PUBLIC 无 EXECUTE；S1 的 G1-A 断言按下列方式**对齐而不放宽**：
  - `prosecdef=true` 仍恰为 `{advance}`；
  - 含 `UPDATE v24.effects` 的函数集合从 `{advance, validate_and_apply_install_delta}` 扩为 `{advance, validate_and_apply_install_delta, validate_and_apply_delta}`（`settle[]` 需要更新既存 reconcile）；三者中只有 advance 是 DEFINER，另两个必须 INVOKER 且无任何 EXECUTE 授权；
  - 含 `pg_advisory_xact_lock` 的仍恰为 advance；
  - wrapper 静态检查的列表加上 `fiber_control`/`dispose`（均 INVOKER、体内只调 `v24.advance(`、无写语句）；
  - `resolve` 断言 `provolatile='s'`、`prosecdef=false`。

### 4.12 全序与锁

新行仍走 B.1 的八段全序：scope→run→effect→install→fiber→episode→slot→pin。S2 的写只触及后六段；闭包扩展只增加**实体**，不改变段序。`u_effects_reconcile` 的部分唯一索引在 G 下插入，冲突 ⇒ `23505` 抛错回滚（协议违约，不吞）。

### 4.13 开放项裁决

**O5（已冻结，S2 实证）**：E1→E2 严格「关旧代 → 插新代 → 切 current」；`u_episodes_ident` 非延迟；`u_episodes_open`/`u_slots_live` 同事务顺序敏感。W5 用 G3a-G 实测。

**O6（S2 冻结）**：retry 只清 `failure_seq/failure`、`control_seq+1`、按当前 `want_on` 产生唯一 reconcile；无失败 ⇒ no-op；不碰 `installs.state`（Oracle 2A）。

**D-S2-1** successor born-settled 扩展（§4.4）。
**D-S2-2** fiber CAS 用 `stale_generation`，不新增码。
**D-S2-3** 未结算 reconcile 存在时，同向命令继续驱动一个阶段（§4.6.1）。
**D-S2-4** child install 不要求 scope 与 owner fiber 相等。
**D-S2-5** `check_policy` v1 只支持 `{"v":1,"op":"equals","path":[...],"value":<scalar>}`；其他形状在 install admission 即 `invalid_args`。
**D-S2-6** `dispose` 阻塞时返回 committed + `dispose_pending`（Oracle 5A），不返回 deferred。
**D-S2-7** `install` admission 为每个 install 创建恰一个 inactive fiber，fiber_id=`md5(install_id::text || ':fiber')`；不改 `emitted` ABI。
**D-S2-8** `dispose` 写本 install 自有 fiber 的墓碑；child fiber 墓碑归 S5。
**D-S2-9** delta 增 `settle[]` 键：只结算闭包内既存的 `fiber_reconcile` ready effect，不新建行（续驱需要）。
**D-S2-10** delta 的 `effect` 补丁增可选 `scope_id`/`fiber_id`/`episode_id`，applier 校验与已锁对象一致；用于命令 effect 与 reconcile 的归属列。
**D-S2-11** 闭包与 applier 的扩展直接改 `30_advance.sql` / `40_interpreters.sql`，不在 45 里 `CREATE OR REPLACE` 整段函数；45 只放 `resolve`、wrapper 与索引。

## 5. gate G3a：断言与负例

### 5.1 具名断言

| ID | 断言（可证伪） | 证据形式 |
|---|---|---|
| G3a-A | `resolve` 恰六列、输入序；未知 key `live=false`；leaf-first realm；同 key 不同 realm 并存互不遮蔽；withdrawn/released/retiring/closed-scope 均 `live=false` | 返回行逐列断言 + `state()` 前后相等（只读） |
| G3a-B | 空 inject 激活：installed install + `fiber_control(on)` → 一个 active episode、`current_episode_id` 指向它、无 activation pin、无贡献 slot、`fiber_reconcile=succeeded` | 行快照 + effect 计数 + 事件 |
| G3a-C | 有 requires/provides 激活：每个 require 一条 activation pin（consumer_episode/epoch/key/slot/provider 全对）；每个 provide 一条 slot（contribution_seq 连续、descriptor digest 正确） | `pins`/`slots` 逐列断言 |
| G3a-D | 缺依赖 / check=false ⇒ W1 `dependency_unresolved`；**无 episode/slot/pin 半行**；fiber 记 `want_on=true/control_seq+1/failure_seq/failure` 且 `current_episode_id=NULL` | 十表 diff（允许 fibers 的四个控制列与本次 effect/request）+ 计数 |
| G3a-E | `provide_conflict`：同 realm/key 已有 live slot 时激活失败，零 episode/slot/pin | 错误码 + diff |
| G3a-F | **无 run activation pin 挡 release**：A 激活并 pin B 的 slot；B off ⇒ slot `withdrawn_at` 非空但 `released_at` 仍 NULL、episode=`retiring`、同一条 reconcile 仍 ready、`deferred`；A off 释放自己的 activation pin 后，B 用一个新 key 的 off（D-S2-3 续驱）**settle 同一条 reconcile** 完成阶段 B：slot released、episode closed、reconcile 计数不增 | 逐列快照 + 两阶段调用 + reconcile effect_id 前后相等 |
| G3a-G | E1→E2：B 完成 off 后再次 on 得 `epoch=E1.epoch+1` 的 E2；E1 行保留、旧 pin 行保留、`current_episode_id` 切到 E2；无 partial unique 冲突 | 行快照 + 无 `23505` |
| G3a-H | CAS/no-op/replay：错 `expected_control_seq` ⇒ W1 `stale_generation`，除 effects/requests 外零 diff；已完成的 on 再 on（新 key）⇒ committed，除本次 command 的 effect/request 外零 diff、无新 reconcile；同 key 重放 byte-equal 且不新增行 | 错误码 + diff + 返回相等 |
| G3a-I | retry：有 failure ⇒ 清 `failure_seq/failure`、`control_seq+1`、新 reconcile；无 failure ⇒ no-op；`installs.state` 始终不变 | 行快照 |
| G3a-J | fiber 实例 + child install：每个新 install 恰一条 deterministic fiber（`want_on=false`、`current=NULL`、owner 列继承）；owner active/want_on/current 时 child 写两列；disposed/`want_on=false`/无 active episode 分别 `already_terminal`/`owner_closing`/`install_not_ready`；E2 切换后旧 install 的 owner 列不变 | 行快照 + 错误码 |
| G3a-K | leaf dispose：未激活的 installed install → `dispose_pending` + 自有 fiber 墓碑 + host_release successor；host claim + success → `disposed`；有 active episode 或未 disposed child 时停在 dispose_pending、不发 release；同 key replay；新 key `already_terminal`；`prepare_unknown` 停在 dispose_pending | 逐列 + effect 计数 |
| G3a-L | ACL/只读：`resolve` 零写、STABLE、INVOKER；`fiber_control`/`dispose` 为 INVOKER 且体内只调 advance；协议角色 EXECUTE 精确集合；`prosecdef=true` 仍恰为 advance；PUBLIC 无 EXECUTE | catalog + 三角色实调 |

### 5.2 强制负例（§9 L437 对位）

| §9 G3 负例 | 落在 |
|---|---|
| 无 run activation pin 挡 provider release | G3a-F |
| 不同 realm 同 key 可并存 | G3a-A |
| 空 inject 可激活 | G3a-B |
| provider close 先/claim 后与 claim 先/close 后（双 run） | **G3b（S3）**：S2 无 run pin，矩阵标未验证 |
| withdraw 后旧 pin 排空但新 run 失败 | **G3b（S3）**：S2 只证旧 pin 在 withdraw 后仍有效（G3a-F）与新 resolve 看不到 withdrawn（G3a-A） |

### 5.3 证据粒度

- **「零写」分两级**：W0 = 十表全快照相等；W1 = 除 `effects`/`requests` 的本次 command receipt 外零 diff（测试需要 `rejects_with_domain_no_write` 辅助，而不是复用 S1 的 `rejects_without_writes`）。
- 不只看最终 status：activation 断言 effect 唯一结算、episode/slot/pin 行数与关键列、事件数、`next_contribution_seq`。
- `deferred` 必须区分「阶段 A 已提交」与「零写」：G3a-F 逐列给出 `withdrawn_at` 已写、`released_at` 未写的证据。
- 双连接只用于屏障用例（A 的 pin 与 B 的 off），用 `pg_blocking_pids()`/`pg_locks` 证明先后，不用 sleep 猜。
- 未实现/未运行：run-pin 半部、inspect 收敛、owner 级联、完整 dispose 闭包在矩阵显式标「未验证 / 保留 S5」。
- S1 回归：`load.py`、`setup_db.py --self-check`、`test_ddl.py`、`test_g1.py` 全部退出 0；`test_g1.py` 的 ACL 期望集合按新函数对齐（只增不减断言）。

### 5.4 测试夹具

- `v24/s2/test_g3a.py` 复用 `v24/s1/setup_db.py` 的 fixture（唯一库名、template0、OID 清理），新增能力面 seed helper：root scope、installed install、fiber、可选 requires/provides。
- 带 `provides` 的 install 先落 `preparing`；能力面用例必须先用 S1 的 FakeHost 结算 host_prepare 把它推到 `installed`，再做激活。声明式 install（空 provides + 零长 artifact）直接 `installed`。
- 每个断言取干净 fixture；文件可 `uv run python v24/s2/test_g3a.py` 独立跑，退出码 0。
- FakeHost 用于 host_prepare 与 host_release 的 claim→IO journal→settlement；不联网。
- 事件断言用 `entity_type/entity_id/event_kind` 具名集合，不靠计数猜。

## 6. 风险与回退

| 风险 | 最脆弱处 | 缓解 | 停手条件 |
|---|---|---|---|
| R1 闭包不完整 | resolve 在闭包之后才发现新 slot/pin | closure 用同一 resolver 预解析；解释器复算不一致 ⇒ `retry_with_closure` 零写；512 上限 | 任一新引用在加锁后才出现 ⇒ 停工修闭包 |
| R2 阶段机写成状态泥潭 | off 的 A/B 阶段与 deferred | 只允许两个阶段；每阶段原子；屏障预检在写前 | advance 内出现第二套 lifecycle 分支 ⇒ 停工重构 |
| R3 E1→E2 顺序 | partial unique 立即冲突 | O5 顺序 + G3a-G 实测；E1 未关不得插 E2 | 出现 `23505` 或需要 DEFERRABLE ⇒ 回 O5 |
| R4 deferred 被误读为零写 | 阶段 A 已写、阶段 B 未写 | 矩阵/README 明写「deferred 指下一阶段零写」 | 任一断言把 deferred 当全零写 ⇒ 改证据 |
| R5 resolve 泄漏/授权 | 未知 scope/key | `live=false`、不写、不 fallback；三角色 EXECUTE | resolve 出现任何写或跨 realm fallback ⇒ 停工 |
| R6 child 历史身份 | 用 current 指针替代 owner_episode | 复合 FK 固定 `(fiber_id,episode_id)`；G3a-J 断言 E2 后旧行不变 | 任何 child/owner 检查读 current 指针作为历史 ⇒ 停工 |
| R7 S1 回归被放宽 | 新函数集合使 G1 断言过期 | 只对齐集合，不删断言；五个 gate 全跑 | 任一 S1 断言被删除/放宽 ⇒ 停工 |
| R8 dispose 与 prepare 竞态 | dispose_pending 期间 host_prepare 结算 | 结算要求 `installs.state='preparing'`；dispose_pending ⇒ `receipt_conflict` | prepare receipt 把 disposed 拉回 installed ⇒ 停工 |
| R9 fiber 创建改变 S1 行为 | S1 的 install 响应/快照断言 | fiber 不在 `emitted`；S1 gate 只按 before/after diff 断言，不数 fiber；W7 跑全量回归 | 任一 S1 断言因新增 fiber 失败 ⇒ 修 S1 断言或改为 `INSERT ... WHERE NOT EXISTS` 的幂等 |

## 7. 与设计稿的分歧点清单

| # | 分歧 | 设计位置 | 采用 | 理由 |
|---|---|---|---|---|
| D-S2-1 | successor 可生为 `succeeded` | S1 计划 §4.14.4 的 delta 形状只列 ready successor | 仅 `fiber_reconcile` 可 born-settled | 设计要求同一次 advance 结算一个阶段；无内部 settlement ABI |
| D-S2-2 | fiber CAS 用 `stale_generation` | §6.3 只说「验 CAS」，未给码 | `stale_generation` | 闭集内唯一的 CAS 码；不新增协议码 |
| D-S2-3 | 未结算 reconcile 存在时同向命令继续驱动 | §6.3「目标与当前 episode 一致 ⇒ 幂等」 | 解释为「目标已完成」 | 否则 S2 没有合法的多阶段驱动者；S5 接管后仍成立 |
| D-S2-4 | child install 不要求 scope 等于 owner scope | §6.2 未要求 | 允许子 scope | scope 关闭按 owner 身份枚举，不靠 scope 相等 |
| D-S2-5 | `check_policy` v1 封闭谓词 | §3.1.7「封闭、版本化的纯数据谓词」，未给形状 | `{v:1,op:equals,path,value}` | 可执行、可证伪；其他形状在 admission 拒绝 |
| D-S2-6 | dispose 阻塞返回 committed + dispose_pending | §6.7「保持 dispose_pending/closing」 | committed，无 successor | Oracle 5A；deferred 语义留给 reconcile |
| D-S2-7 | install admission 自动创建一个 inactive fiber | 设计未写 fiber 的创建者；§6.1 只说「install 完成不表示 fiber active」 | 每个 install 恰一个，`fiber_id=md5(install_id::text\|\|':fiber')` | `fiber_control` 只收 fiber_id，无法自建；确定性 id 不改 `emitted` ABI |
| D-S2-8 | dispose 写自有 fiber 的墓碑 | §6.7 只说「检查 fibers 已 disposed」 | 由 dispose 在义务满足后写 `disposed_at` | 设计未给 fiber dispose 动词；off 必须保留 fiber 以便 E1→E2；child fiber 归 S5 |
| D-S2-9 | delta 增 `settle[]` 结算既存 reconcile | S1 计划 §4.14.4 只有 insert 型 successor | 只允许 ready `fiber_reconcile` | 续驱必须结算同一条 effect；删除重建会破坏 `u_effects_reconcile` 与审计 |
| D-S2-10 | delta 的 `effect` 补丁可写归属列 | S1 计划 §4.14.4 的 `effect` 只有 status/outcome | 可选 `scope_id`/`fiber_id`/`episode_id`，校验一致 | 否则 W1 失败 receipt 的 scope/fiber 归属为空，闭包与审计退化 |
| D-S2-11 | 闭包/applier 直接改 30/40 | 本计划 §4.0 原写「45 覆盖四个分派函数」 | 45 只放新函数与索引 | 复制数百行函数会产生两份定义并长期漂移；直接改的 diff 更小可审 |

**D 清单是披露机制，不是规格修订。** 若实施发现需要改设计语义，先走设计稿修订 + Oracle 复审，不在本计划内静默改。

## Open Questions

| # | 问题 | 归属 | 触发条件 |
|---|---|---|---|
| Q1 | 多阶段 reconcile 的正式驱动者（扫描/恢复接口） | S5/S6 | S5 定义清理闭包时；S2 只留 ready effect 与阶段 A |
| Q2 | `check_policy` 的完整谓词集与版本升级 | S4/S5 | 出现第二个 reducer/adapter 时 |
| Q3 | run pin 与 activation pin 的双序证据 | S3（G3b） | start 落地后 |
| Q4 | inspect_resource 的收敛路径 | S5 | dispose on prepare_unknown 时 |

## References

- 设计稿：`docs/designs/v24-pg-agent-2026-10-22.md`
- pre-plan：`docs/plans/v24-pre-plan-2026-10-23.md`
- S1 计划/矩阵/台账：`docs/plans/v24-s1-kernel-2026-10-23.md`、`docs/reviews/v24-conformance-matrix-2026-10-23.md`、`docs/reviews/v24-deviation-ledger-2026-10-23.md`
- 阶段分解：`docs/analysis/v24-stage-decomposition-2026-10-23.md`
- 仓库纪律：`AGENTS.md`

## 交付后如何验收

1. 逐项跑并记录退出码：`uv run python v24/load.py`、`v24/s1/setup_db.py --self-check`、`v24/s1/test_ddl.py`、`v24/s1/test_g1.py`、`v24/s2/test_g3a.py`。
2. 检查矩阵：G3 父行标「部分（G3a 绿）」；G3a 每行有具名断言与实跑证据；run-pin 半部与 inspect 显式标未验证。
3. 检查台账：D-S2-1…11 逐条落位；「G3 子门拆分」追加一条非偏差声明。
4. 检查 catalog：仍恰十张 base table；新函数 owner=`v24_owner`、PUBLIC 无 EXECUTE、`prosecdef=true` 仍恰为 advance。
5. 按路径逐项 `git add`（禁用 `git add -A`），提交信息 `v24: add capability plane (resolve, fiber episodes, child install, leaf dispose)`，推送 `v24` 分支。
