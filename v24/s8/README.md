# v24 S8 spawn / child run（G7）

> 状态：S8 W1–W3 已实施并结项。G7-A…H（8 条）+ N1–N7（7 条）全部通过；无参数 `uv run python v24/s8/test_g7.py` exit 0，末行恰为 `[passed] v24 S8 W1-W3 G7-A…H + N1-N7: g7_a,g7_b,g7_c,g7_d,g7_e,g7_f,g7_g,g7_h,n1,n2,n3,n4,n5,n6,n7`。既有 9 个 gate 与 S8 gate 共 **10/10** 条命令 exit 0。Oracle chat `028D07` 的 Q1–Q7 全选 A。本文只记录实现、运行方式与证据口径；合同以 [S8 计划](../../docs/plans/v24-s8-spawn-2026-10-24.md) 和[设计稿](../../docs/designs/v24-pg-agent-2026-10-22.md) §5.5/§5.2/附录 C.2/C.6 为准。

## 1. 目的与架构

S8 只补设计 §5.5 的 spawn/child run：模型 outcome 的保留 intent key `agent.spawn` 在**同一次 `advance`** 内原子创建 child。唯一路径：

```text
v24.advance(model effect + outcome)
  -> v24.interpret_model_settlement
       -> C19.0 结构校验 / 保留 key 分流（agent.spawn 不计 tool、不查 pin）
       -> args 校验 + sha256(canonical_json(args))
       -> 查 (parent_run_id, spawn_key)
            absent -> fresh；digest 相同 -> replay；digest 不同 -> spawn_key_conflict W0
       -> 一个 delta：child run + spawn edge + 父 quota + child quota
                      + 可选 owner run pin + child 首 model_call
                      + 父 run_spawned + 子 run_started
  -> v24.validate_and_apply_loop_delta（独立重算 fresh/replay/conflict 后应用）
```

架构约束：

- spawn 全在 `interpret_model_settlement` 内完成，仍在单入口 `advance` 的一次事务里；没有第二个命令、第二个状态机、独立 replay 合同或 escrow 表。
- child 是 `runs` 行（run），不是 fiber/install/slot；owner_fiber 只是资源依赖。
- 无新表/列/索引/视图/函数/DEFINER/GRANT；不改 `runs` schema，只用既有 spawn 三列和 `u_runs_spawn`。
- 错误码闭集只增加第 24 个 `spawn_key_conflict`（W0）；其余 23 码不变。
- 无真实 provider、网络或外部 IO；G7 使用 fixture host，G7-F 静态扫描源码并断言 `v24_fake.journal` 0 行。
- `agent.spawn` 不是 effect、不可 claim；child 首 `model_call` 走 `inserts.effects`，不走 `successors[]`。

## 2. 文件

| 文件 | 作用 |
|---|---|
| `v24/s8/test_g7.py` | G7-A…H + N1–N7 的唯一 gate；复用 S1/S2/S4 的 fixture helper 与 `setup_db()`；无独立 setup_db 脚本。 |
| `v24/sql/30_advance.sql` | 24 码闭集；model claim 的 C17 cause 校验加入 `spawn`；spawn child effect 的确定性 id/parent/run 校验；普通 model claim 的 guard 仍拒绝 `pin_id IS NOT NULL` 的 model_call（含 spawn child 首 model）。 |
| `v24/sql/48_loop.sql` | C19 保留 key 分流；`interpret_model_settlement` 的 spawn admission（args/digest/owner/quota）；child run/edge/quota/独立 run pin/first model/events；child 首 model 写 `pin_id=NULL`，applier 要求该列 NULL 并校验独立 run pin 行；`spawned` response；`validate_and_apply_loop_delta` 的 spawn footprint 与独立 replay/conflict 重算。 |
| `v24/sql/40_interpreters.sql` | 通用 delta 入口 `validate_and_apply_delta` 分派到 loop applier；S8 无需该文件的专属改动（spawn footprint 在 `48_loop.sql` 的 `validate_and_apply_loop_delta`）。 |

- **无新增 SQL 文件**：spawn 并入既有 `48_loop.sql`，未新建 `51` 或 helper SQL 文件。
- `v24/s1/test_g1.py` 随 R7 把错误码列表扩到 24（`len(codes)==24`）；它不是新增 gate。

## 3. G7 窗口 A–H

| ID | seeded 场景 | 决定性断言 | 证据 tag |
|---|---|---|---|
| **G7-A** | 真实 `v24.start` 得到 parent run 与 claimed model；一次 `agent.spawn`。另起 fixture，在 child run insert / child effect insert / parent quota update 三处各注入一次故障。 | 同一 advance 内创建 child run、三列 spawn edge、扣父 quota、写 child 初始 quota、可选 owner pin、child 首 `model_call`、父 `run_spawned` + 子 `run_started`；任一故障 → 十表快照逐字节相等，model effect 仍 claimed。 | `[G7-A]` |
| **G7-B** | 第一次 spawn 后 steer parent 得到新的 model effect，用同 key/同 args 再结算；随后对同一 model effect 同字节再 `advance`。 | 新 parent outcome 返回 `replayed:true`、同一个 child/effect；child/effect/`run_spawned` 各 1；grant 只扣一次；精确 receipt replay 返回冻结信封 `{v:1,disposition:'replay',effect_id,emitted:[],revision:0,claim:null}`，零写。 | `[G7-B]` |
| **G7-C** | 第一次 spawn 后，新 parent outcome 使用同一个 `spawn_key`、不同 `input` bytes，且 `request_key` 不同。 | 返回第 24 码 `spawn_key_conflict` W0；十表快照逐字节相等；model effect 仍 claimed；child/effect 计数不变。 | `[G7-C]` |
| **G7-D** | finite parent（tokens 5000，usage 0，grant 300）；NULL parent/child；finite parent + child null；steps/wall 超父 remaining。 | finite 的一次运行示例：`grant=300 reserve=300 child_remaining=0`、`tokens_before=904 tokens_after=4700`、`wall_elapsed=22 wall_after=592978`（`wall_elapsed` / `wall_after` 随 `now()` 变化，不当作固定值）；固定断言是 `v_tokens = Q_parent_after + grant` 与 `Q_parent_before - elapsed = Q_parent_after + child_wall`。NULL 不做 tokens 算术；finite+NULL `invalid_outcome`；超 steps/wall `budget_exceeded` 且父行 byte-equal；重放不二次扣。 | `[G7-D finite]`、`[G7-D NULL]`、`[G7-D]` |
| **G7-E** | ownerless spawn；spawn 前后 `fibers/installs/slots/episodes` 计数。 | 四个计数不变；child 无 fiber、无 episode pin、无 run pin；child 是 run。 | `[G7-E]` |
| **G7-F** | 对 `30_advance.sql`/`40_interpreters.sql`/`48_loop.sql` 与 `v24/s8/*.py` 做静态扫描；closed catalog 与 `v24_fake.journal` 前后计数。 | 无新 table/column/index/view/extension；无 `http`/`dblink`/`pg_sleep`/`socket` 或网络 import；journal 0→0；`u_runs_spawn` 存在。 | `[G7-F]` |
| **G7-G** | 真实 spawn 创建带 owner pair 的 child；child 首 model 是 `cause='spawn'` 的 spawn-shaped row（`pin_id=NULL`，`no_replay`），owner run pin 是独立 `pins` 行。经 `v24.advance` 的公共 claim 路径得到 `attempt/fence=1/1`，过期 lease 后调用真实 `v24.command_recover`。 | `claimed(lease_expired) → unknown`；`attempt/fence 1/1` 保留；child `running → blocked_unknown`；`ended_at` 设置；spawn edge、child/effect 计数、父 quota 不变；独立 run pin 由 recovery 释放；唯一新增 effect 是 `command_recover` 行。 | `[G7-G]` |
| **G7-H** | 五类 W0：invalid args、budget_exceeded、provider_unavailable、dependency_unresolved、already_terminal。 | 每类十表快照逐字节相等；model effect 仍 claimed；无 child/edge/quota 差/successor effect。 | `[G7-H]` |

### 3.1 G7-G recovery details

Fixture 用真实 spawn 路径创建 owner-pinned child；child 首 model 的 `pin_id` 为 NULL，因此 claim 走真实公共 `v24.advance` 路径（`attempt_no=1`、`fence=1`，owner 为 service login），不再 seed claim。随后把 `lease_until` 置为过期；收敛本身只走真实公共 `v24.command_recover`。下表是最终 no-arg 运行的一次观测值：其中的 UUID、digest、时间与 quota 均来自该次 fixture，换父 run 会变化；只有语义、计数与守恒口径是稳定断言。

| 项 | recovery 前 | recovery 后 |
|---|---|---|
| child run id | `2a2d0546-5c5d-92a1-850e-b154060409ba` | 相同 |
| child 首 model effect id | `f3f9ce0c-c4c4-1e0e-83d9-b956b97c7e4a` | 相同 |
| child model `pin_id` | `NULL`（claim 前即 NULL，claim 后仍 NULL） | `NULL` |
| child model status | `claimed`（公共 claim，lease 已过期） | `unknown` |
| child model `lease_until` | `2026-10-24T21:35:08.877164+08:00`（已过期，`lease_until < now()` 为 true） | `NULL` |
| child model attempt/fence | `1/1` | `1/1`（保留） |
| child model claim token | `{attempt:1,fence:1,owner:'v24_s1_27595_868544b06003_service'}` | `outcome.claim` 同 token；`claim_owner` 为 `NULL` |
| child model outcome | — | `class='unknown'`、`observed='unknown'`、`reason='lease_expired'`、`recovery.effect_id` = 该 effect id |
| child run status | `running` | `blocked_unknown` |
| child run `ended_at` | `NULL` | 设置（`2026-10-24T21:35:09.877879+08:00`） |
| child run `interaction` | `NULL` | `NULL` |
| child run `pending_steer` | seeded `{instruction:'queued before recovery',generation:1,epoch:0}` | `NULL` |
| child run pin（独立 `pins` 行） | `pin_id=8a3039ec-ee58-4740-8090-1390642bd448`，live；不在 `effects.pin_id` 上 | released；`released_by_effect` = child model effect id |
| spawn edge `parent_run_id` / `spawn_key` / `spawn_request_digest` | `0073c2f0-fd13-456a-bab7-c609cc51b844` / `child-g` / `aa6ab6a94ee4daaddc09e8ca0a1d4977829d148bc13571fbb3243c3489bf732e` | 三项均相同 |
| child runs / child model-call effects | 1 / 1 | 1 / 1 |
| 全部 `effects` 行 | 45 | 46（仅新增 `command_recover` command 行） |
| `run_spawned` / `run_started` events | 1 / 1 | 1 / 1 |
| parent quota（steps/tokens/tool_calls/wall_ms） | `2 / 604 / 2 / 594980` | 相同；整行 parent run byte-equal |

`v24.command_recover` 恰好应用一个动作：`{effect_id='f3f9ce0c…', kind='model_call', replay_policy='no_replay', action='settle_unknown', reason='lease_expired', attempt_no=1, fence=1, run_id='2a2d0546…', install_id=NULL}`；`candidates=[<该 effect>]`、`manual_debt=0`、`has_more=false`。恢复复用 S6 的 `unknown_wall_delta`，没有新增 recovery 路径或修复。

## 4. N1–N7

| # | 场景 | 断言 | 写类 |
|---|---|---|---|
| **N1** | 两个真实连接、同一 effect/同字节、Barrier(2)。 | 恰一个 child；败者被 `G` 串行挡住（`pg_blocking_pids` 证据）并按冻结信封 replay；grant 只扣一次。 | W1/W0 |
| **N2** | 两个真实连接、同 key/异 bytes。 | 恰一个 committed child；败者因同一 model effect/receipt 收到 `receipt_conflict`（G 串行，无半状态）；之后新的 parent outcome 用败者 bytes 到达 `spawn_key_conflict` W0。 | W0 |
| **N3** | 对 cancelled/terminal parent spawn。 | `already_terminal` W0；无 child；model effect 仍 claimed。 | W0 |
| **N4** | child steps 超过 parent remaining。 | `budget_exceeded` W0；parent run 行 byte-equal；无 child。 | W0 |
| **N5** | owner-pin spawn 在 child run / quota update / child effect 插入注入故障。 | 全回滚：child、pin、quota、events 均无；model effect 仍 claimed。 | W0 |
| **N6** | 同 request_key/同字节连续两次 `advance`。 | 两次都是逐字节相同的冻结 replay envelope；十表不变；一个 child、一次 grant 扣减。 | W1/W0 |
| **N7** | owner-pin spawn 全流程计数。 | `fibers/installs/slots/episodes` 不增删；child 是 run，带 owner pair 与一个 run pin，绝不是 fiber/install。 | 静态 |

N1/N2 的并发证据由 `serialized_race` 采集：`[G7-N1-lock]` / `[G7-N2-lock]` 记录持有 `G` 的 pid、被挡 pid、`pg_blocking_pids` 与未授予的 advisory lock；`[G7-N1]` / `[G7-N2]` 各出现一次，不用 sleep 猜序。

## 5. 命令与预期输出

```bash
# 父门口径：G7-A…H + N1–N7 各恰好一次
uv run python v24/s8/test_g7.py

# 增量检查点（不是第十条 gate）
uv run python v24/s8/test_g7.py --only g7_g
uv run python v24/s8/test_g7.py --only g7_a,g7_d,n1,n2
```

- **数据库**：`main()` 内 `with server_helper_scope(), setup_db() as db:`；每次创建唯一临时库并按 loader 顺序加载全部 SQL，退出时 `DROP DATABASE ... WITH (FORCE)`。没有 `v24/s8/setup_db.py`，也不需要手工建库。
- **增量检查点**：`--only g7_g` 在最终树上 exit 0（不是第十条 gate，不计入 10/10）；其 G7-G 证据来自公共 claim 路径，不是 seeded claim。
- **网络**：G7-F 扫描 SQL 的 `http`/`dblink`/`pg_sleep`/`socket` 与 `v24/s8/*.py` 的 `socket`/`http`/`urllib`/`requests`/`httpx`/`aiohttp` import；不使用真实 provider。
- **期望**：exit 0；每个 `[G7-A]`…`[G7-H]`、`[G7-N1]`…`[G7-N7]` 各恰好一次；G7-D 另有 `[G7-D finite]` / `[G7-D NULL]` 子证据；N1/N2 另有 `[G7-N1-lock]` / `[G7-N2-lock]` 各一次。
- **末行**：无参数运行时恰为 `[passed] v24 S8 W1-W3 G7-A…H + N1-N7: g7_a,g7_b,g7_c,g7_d,g7_e,g7_f,g7_g,g7_h,n1,n2,n3,n4,n5,n6,n7`。

最终回归的十条命令：

| # | 命令 | exit | 末行 |
|---|---|---|---|
| 0 | `uv run python v24/s8/test_g7.py` | 0 | `[passed] v24 S8 W1-W3 G7-A…H + N1-N7: g7_a,g7_b,g7_c,g7_d,g7_e,g7_f,g7_g,g7_h,n1,n2,n3,n4,n5,n6,n7` |
| 1 | `uv run python v24/load.py` | 0 | `[passed] v24 loader self-check` |
| 2 | `uv run python v24/s1/setup_db.py --self-check` | 0 | `[passed] v24/s1 setup self-check` |
| 3 | `uv run python v24/s1/test_ddl.py` | 0 | `[passed] v24 W2 G1-O owner DDL probes (no advance/ACL/lifecycle claim)` |
| 4 | `uv run python v24/s1/test_g1.py` | 0 | `[passed] v24 G1 kernel, commands, claim, locks, host_prepare settlement and ACL` |
| 5 | `uv run python v24/s2/test_g3a.py` | 0 | `[passed] v24 S2 W1-W6: resolve, infra, admission, activation, deactivation, dispose` |
| 6 | `uv run python v24/s3/test_g2.py` | 0 | `[passed] v24 S3 W1-W7: read surface + start + poll/wait_check + cancel + steer + respond (G2a-0/1/2/3/4/5/6/7/8/10/11; G3b-1..5; claimed/unknown settlement release reserved S4)` |
| 7 | `uv run python v24/s4/test_g2b.py` | 0 | `[passed] v24 S4 W1-W6` |
| 8 | `uv run python v24/s5/test_g4.py` | 0 | `[passed] v24 S5 W1-W4` |
| 9 | `uv run python v24/s6/test_g5.py` | 0 | `[passed] v24 S6 W1-W4` |

## 6. Spawn schema

合同正文见计划 §4.1–§4.5；下面只压缩实现使用的形状，不新增规则。

### 6.1 `agent.spawn` intent

`args` 的精确键集（多/少一个都 `invalid_outcome` W0）：

```json
{
  "v": 1,
  "spawn_key": "1..128 chars",
  "input": { "...": "child first model input" },
  "scope_id": "<uuid>",
  "budget": {
    "steps": 1,
    "tokens": 1000,
    "tool_calls": 1,
    "wall_ms": 60000
  },
  "owner_fiber_id": "<uuid>",
  "owner_episode_id": "<uuid>"
}
```

`owner_fiber_id` / `owner_episode_id` 是可选的成对键；省略时 child 为 ownerless。

| 字段 | 规则 |
|---|---|
| `v` | `1`。 |
| `spawn_key` | 长度 1..128，字符集 `[A-Za-z0-9._:-]`；同一 parent run 内唯一。 |
| `input` | object；作为 child 首 model 输入，进入 canonical bytes/digest。 |
| `scope_id` | 必须等于 parent run 的 `scope_id`；v1 不做跨 scope spawn。 |
| `budget` | 四字段全必填；`steps`/`tool_calls`/`wall_ms` 为正整数；`tokens` 为正整数或 JSON null，null 仅当 parent `remaining_tokens IS NULL`。 |
| `owner_fiber_id` / `owner_episode_id` | 可选，但必须同时有或同时无；有则满足 §7 的 owner 检查。 |
| digest | `spawn_request_digest = sha256(canonical_json(args))`；包含 `spawn_key`，所以同 key 异 bytes 必然 digest 不同。 |

约束：

- 一个 model outcome 至多 **1** 个 `agent.spawn`（v1，D-S8-7）；多于 1 个 `invalid_outcome` W0。
- `agent.spawn` 必须只含 `{key,args}`，不计入 `max_tool_calls`、不进入 pin 成员检查。
- 不得与普通 tool、`final` 或 `interaction` 混用；混用 `invalid_outcome` W0。
- 结构/语义错误在任何 DML 前返回；model effect 保持 claimed，host 可用原 token 重交修正后的 outcome。

### 6.2 child run / quota / first model

| 项 | 值 |
|---|---|
| `run_id` | `md5(parent_run_id::text || ':spawn:' || spawn_key)::uuid`。 |
| `scope_id` | parent run 的 `scope_id`。 |
| `parent_run_id` / `spawn_key` / `spawn_request_digest` | 三列共同承载 spawn edge；由 `u_runs_spawn` 保证 `(parent_run_id,spawn_key)` 唯一。 |
| owner | 可选；有 owner pair 时 `owner_fiber_id`/`owner_episode_id` 落 child 行；无则为 NULL。 |
| `status` | `running`。 |
| `epoch_no` / `registration_generation` / `turn_no` / `driving_generation` / `revision` | `0 / 1 / 0 / 0 / 0`；`ended_at` 为 NULL。 |
| `remaining_steps` / `remaining_tool_calls` / `remaining_wall_ms` | child 初始 quota（`budget` 对应字段）。 |
| `remaining_tokens` | `grant - v24.model_reserve(grant)`；`grant = budget.tokens`，grant NULL → NULL。 |
| `created_at` / `updated_at` | `now()`。 |
| child 首 `model_call` | `effect_id = md5(child_run_id::text || ':model_call:0')::uuid`；`parent_effect_id` = 本次结算的父 model effect；`ordinal=0`；`kind='model_call'`；`status='ready'`；`run_id=child`；`fiber_id`/`episode_id` = 可选 owner pair；`epoch_no=0`；`generation=0`；`pin_id` **恒为 `NULL`**（`model_call` 从不绑定 `effects.pin_id`；owner run pin 是独立 `pins` 行）；`replay_policy='no_replay'`。 |

child 首 model 的 `request` 为 C17 兼容 + `cause='spawn'`：

```json
{"v":1,"cause":"spawn","run_id":"<child>","epoch_no":0,"generation":0,
 "input":{...},"reserve":{"tokens":<v24.model_reserve(grant)>},
 "digests":{"policy":"...","schema":"...","toolset":"..."},
 "spawn_key":"...","parent_run_id":"..."}
```

- `digests.policy`/`digests.schema` 取版本常量；`digests.toolset` 按**预期 run pin** 计算（见 §7）；ownerless child 用空集摘要。
- child 首 model 必须走 `inserts.effects`，不能走 `successors[]`；applier 的 spawn footprint 校验恰好 1 条 child effect、`run_id=child`、`parent_effect_id`=父 model effect、`scope_id`=child scope、`ordinal=0`。
- 事件：父 run `run_spawned`，payload `{child_run_id,spawn_key,child_effect_id,spawn_request_digest}`；child run `run_started`，payload `{run_id,parent_run_id,spawn_key}`。child 首 model 不发 `model_call_created`。
- 响应：model settlement 六键 envelope + 可选 `spawned:[{run_id,spawn_key,child_effect_id,replayed}]`。

quota 守恒（计划 §4.4）：

- steps/tool_calls 对 post-settlement 值检查并扣减 child 初始值，扣后非负。
- wall 用 `v_wall = greatest(0, remaining_wall_ms - elapsed)`，`elapsed = (now() - 父 model effect.created_at)` 的毫秒；守恒 `Q_parent_before - elapsed = Q_parent_after + child_wall`。
- tokens 用 post-C19-refund 的 `v_tokens`；父 finite 且 child grant NULL → `invalid_outcome`；`grant > v_tokens` → `budget_exceeded`；成功后父扣完整 grant，child 行存 `grant - reserve`。child 成功 settlement 只返还 `reserve - usage`，余额为 `grant - usage`，不会出现 `2*grant - usage`。

## 7. Owner pin

有 owner pair 时，child run pin 的物理形状如下。它**不**通过 `effects.pin_id` 绑定：child 首 `model_call` 的 `pin_id` 恒为 `NULL`，run pin 只以独立 `v24.pins` 行存在（按 `consumer_type='run'`、`consumer_run_id=child` 定位）。

| 列 | 值 |
|---|---|
| `consumer_type` | `'run'` |
| `consumer_run_id` | child run id |
| `consumer_episode_id` | `NULL`（`c_pins_xor` 要求） |
| `consumer_epoch` | `owner_episode.epoch` |
| `key` | `'run'` |
| `slot_id` / `provider_episode_id` / `provider_fiber_id` | 取自该 episode 的唯一 live activation pin（provider 三列） |
| `descriptor_digest` | 取自 activation pin 的 digest |
| `created_by_effect` | 父 model effect |
| `released_at` / `released_by_effect` | `NULL` / `NULL`（spawn 后 live） |

检查与边界：

- run pin 与 child 首 model 之间没有 FK 关系：不得把 run pin id 写入 `effects.pin_id`；公共 claim/settlement 的 `pin_id IS NOT NULL` guard 会拒绝这样的 `model_call`。
- `owner_fiber_id` 必须存在、`want_on=true`、`current_episode_id=owner_episode_id`；`owner_episode_id` 必须 `active`；否则 `provider_unavailable` W0。
- 必须存在**恰好一条** live activation pin：`consumer_episode_id=owner_episode_id AND released_at IS NULL`。0 条或 >1 条都 `dependency_unresolved` W0（v1 fail-closed，不任意挑 provider）。
- owner episode 由 child `owner_episode_id` 列与 pin `consumer_epoch` 承载；不得从 run pin 的 `consumer_episode_id` 反推（该列按 XOR 约束为 NULL）。
- `digests.toolset` 按预期 run pin 计算：单元素数组 `[{key:'run',descriptor_digest:<activation pin hex>}]` 的 canonical JSON sha256（与 `model_digests` 同构、同序、同编码）；settlement 后 `v24.model_digests(child)->>'toolset'` 必须与该 request 逐字节相同。
- 无 owner pair：child 的 `owner_fiber_id`/`owner_episode_id` 为 NULL，不建 pin；ownerless child 按 S3 ownerless 规则运行，toolset 用空集摘要。
- `spawn_request_digest` 覆盖 owner pair 两键；不允许只给一个键。

## 8. Replay/conflict semantics

- 查 `(parent_run_id, spawn_key)`：不存在 → fresh；存在且 digest 相同 → replay；存在且 digest 不同 → `spawn_key_conflict` W0。
- 同 `(parent_run_id, spawn_key, digest)` 出现在**新的 parent outcome** 上 → `spawned:[{...,replayed:true}]`，复用同一个 child；不建第二个 child/edge/effect，不二次扣 quota；新 parent model effect 仍按正常规则结算。
- 异 digest → 第 24 码 `spawn_key_conflict` W0，即使 `request_key` 不同；整次 settlement 零领域写，model effect 保持 claimed，host 可重交修正 outcome。
- 同一 model effect + 同 canonical bytes 的 `advance` receipt replay 走 S2/S4 冻结信封 `{v:1,disposition:'replay',effect_id,emitted:[],revision:0,claim:null}`，**不含** `spawned`；重复 replay 逐字节相同且零写。
- applier 从既有 child 行与 outcome args **独立重算** fresh/replay/conflict，不信任 delta 的 `replayed` 标志；replay delta 只允许 parent update + `spawn` echo，不允许 child/quota/effect/event 写。

`spawned` handle 形状：

```json
{"spawned":[{"run_id":"...","spawn_key":"...","child_effect_id":"...","replayed":false}]}
```

## 9. 已知债务与边界

- **无真实 provider/网络**：G7 用 fixture host 与伪造 journal，只证明 spawn 的 DB 合同与幂等；不证明真实 adapter 的幂等或外部 IO 行为。
- **owner pin 的 XOR / `consumer_episode_id=NULL`**：run pin 的 owner episode 由 child 行与 `consumer_epoch` 承载；要求 exactly-one live activation pin；这是 `c_pins_xor` 下的物理映射，不是第二套身份账。
- **N2 的 `receipt_conflict` 与 24 码分开**：两连接同 key 异 bytes 时，`G` 串行让败者在同一 model effect/receipt 上得到 `receipt_conflict`；第 24 码 `spawn_key_conflict` 由之后的新 parent outcome（新 model effect）产生。两者都 W0，但不是同一次冲突。
- **v1 限制**：一个 outcome 至多 1 个 spawn；不与普通 tool/final/interaction 混用；不做跨 scope spawn。扩展需后续版本/设计裁决。
- **D-S8-12（W3 review 修复）**：child 首 `model_call` 曾把独立 owner run pin 写入 `effects.pin_id`，而公共 claim/settlement 的 `pin_id IS NOT NULL` guard 会拒绝任何这样的 `model_call`——这是 W3 review 发现的真实产品缺陷。修复后 child model 的 `pin_id` 恒为 `NULL`，run pin 只作为独立 `pins` 行，G7-G 改走真实公共 claim 路径；guard 仍有意保持严格，后续任何把 pin 绑进 `model_call` 的代码都会在 claim/settlement 被拒。
- **G7-G 的 `interaction` 为 NULL**：`c_runs_waiting` 禁止 running run 带非 NULL `interaction`；测试 seed 非 NULL `pending_steer` 并在 recovery 后断言两列均为 NULL（`pending_steer` 的清除是直接观测）。
- **S8 不证明 G6/S7**：G7 只覆盖 spawn 自身的双连接负例，不是三面并发矩阵；G6 仍归 S7，且 G6 必须消费 G7 证据。

## 10. 链接

- [S8 计划（合同、W1–W3、G7 断言）](../../docs/plans/v24-s8-spawn-2026-10-24.md)
- [G7 测试](test_g7.py)
- [设计稿](../../docs/designs/v24-pg-agent-2026-10-22.md)（§5.5、§5.2、附录 C.2/C.6）
- [覆盖矩阵](../../docs/reviews/v24-conformance-matrix-2026-10-23.md)（G7 行）
- [偏差台账](../../docs/reviews/v24-deviation-ledger-2026-10-23.md)（D-S8-1…12）
