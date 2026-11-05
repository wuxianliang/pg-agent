# v24 六动词会话控制面设计（核验与修订版）

| 项 | 值 |
|---|---|
| 日期 | 2026-11-05 |
| 状态 | **Adopted（2026-11-05）**；五项决策已定稿，S0 按本文件实施；设计未实施前不提交运行时代码 |
| 关系 | 取代 `v24-session-control-plane-2026-11-05.md` 与 `v24-session-control-api-2026-11-05.md` 中与本文件冲突的断言；不替代 API 字段表 |
| 范围 | `v24` host/UI 会话层；对冻结内核 `v24/sql/**` 只提出接口要求 |
| 依据 | 调查 `v24-pi-repoprompt-session-turn-run-mapping-2026-11-05.md`；本文件 §2 的逐条代码核查；RepoPrompt-CE 当前源码 |
| 核查方式 | 静态代码阅读 + 三路独立探查；**未运行**数据库、provider、既有 gate。文中“可行”是代码级可行性，不是运行时验收 |

## 0. 结论

### 0.1 判定摘要

1. **方向成立。** “会话门面 + run 仍是唯一执行主体 + 不建 turns 表 + provider 原文留在 journal”这四条主张有代码与规格支撑。六动词可以在宿主层实现，S0 不改 `v24/sql/**` 是成立的。
2. **草案的 RepoPrompt 对照有两处硬伤。** `already_terminal` 与 `run_started` 在 RepoPrompt-CE 当前源码中**不存在**：前者是 v24 草案自造的错误码，后者是 v24 草案自造的 wake reason。把二者写成“RepoPrompt 行为”不成立。RepoPrompt 的终态 `cancel` 是直接拒绝并抛 `invalidParams`/denial，不返回结构化 `already_terminal`；`wait` 的 `WakeReason` 只有 `instructionDelivered` / `steeringRequested` 两种。
3. **草案对 v24 读面的估计过于乐观。** `v24.poll` 没有 event cursor：它总是返回该 run 的**最早** 64 条事件，不接受 `after_event_seq`；`v24.wait_check` 才支持 `after_event_seq`。因此 API 的 `poll` + `cursor.event_seq` 分页不能按草案映射实现。
4. **草案对 counter 的估计不成立。** `user_turn_no` 不能由 `v24/ui` 的 `seq` 派生：该 `seq` 是**进程全局**、与请求 key 生成共用、重启归零，且当前 `respond` 也会追加 turn；`turns.jsonl` 每会话只留 200 条，且没有 turn 类型字段，无法事后区分 start/steer/respond。`run_no`/`counters.runs` 也不能由 `bindings` 派生（同样 200 条上限），而 `host_runs` 返回的 `run_projection` **不含 `parent_run_id`**，S0 无法区分 spawn 子 run。
5. **S1 不是“改一列 + 加一个索引”。** `v24/sql` 的 12 个文件哈希被 **dp4、dp5、dp6 三套 gate** 同时锁定；dp5/dp6 还要求相对 `57e2c1e` 的 diff 恰好是 6 个已批准路径，`v24/load.py` 与 `v24/s1..s12` 被 byte-lock；`v24/ui/env.py` 在 schema 漂移时直接 `schema_drift`，且没有可用的 DB migration executor。S1 需要一次显式的 frozen-baseline 决策，而不是普通的规格修订。
6. **S0 的“会话门面”可行，但必须先定三件事**：服务放在哪里（UI 还是 transport-neutral）、谁驱动活动 run、以及 waiting `steer` 与 worker 结算的竞态如何加锁。三者不定，S0 会在实现时变成“能 start 但不会推进”或“偶发丢交互”。
7. **`already_terminal` / `run_started` 可以作为 v24 自己的合同保留**，但必须标注为 v24-local，不得再写成 RepoPrompt parity；`respond` 不产生 user turn 也应标注为 v24 策略（RepoPrompt 的 `.instruction` 交互例外会追加 user turn）。

### 0.2 必须修正的断言（按严重度）

| # | 草案断言 | 判定 | 修正 |
|---|---|---|---|
| 1 | `poll` 支持 `cursor.event_seq` 之后最多 64 条 | **错** | `v24.poll` 只有 `after_revision`，events 恒为最早 64 条；要按 seq 分页必须走 `v24.wait_check`，或 v1 不做 event 分页 |
| 2 | `user_turn_no` 由 `ui.seq` 派生 | **错** | 用会话级持久计数器；`seq` 是全局/交错/重启归零，且 respond 也写 turn |
| 3 | `run_no`/`counters.runs` 由 bindings 派生 | **错** | 持久计数器；bindings 截断 200；`host_runs` 无 `parent_run_id` |
| 4 | `budget.tokens` 可为 null（不限） | **错** | `v24.start` 对出现的每个 budget key 都要求 number；“不限”要**省略** tokens，不能传 null |
| 5 | budget 字段均非负即可 | **错** | `steps`/`wall_ms` 必须 ≥1；上限 steps 256、tool_calls 1024、tokens 1e12、wall 86400000 |
| 6 | `start` 可指定 `model` / `toolset` | **部分错** | 当前 host 模型固定 `deepseek-flash`，UI toolset 固定；S0 只能“必须匹配宿主”，不能按 session 切换 |
| 7 | `respond` 在 S0 全模式可用 | **错** | 当前 real 模式明确 `waiting_unsupported`；S0 respond 实际是 fake/scripted-only，除非扩展 real adapter |
| 8 | `steer` waiting 先拒绝即可 | **不充分** | 内核 `v24.steer` 会把 `interaction` 置空；仅“先读后写”有竞态，必须与 driver 共用 per-run 锁，或接受 S0 的已知丢失窗口 |
| 9 | `cancel` 终态返回 `already_terminal` 是 RepoPrompt 行为 | **错** | RepoPrompt 无此码；v24 可保留该码，但不得称 parity |
| 10 | `wait` 的 `run_started` 是 RepoPrompt wake reason | **错** | RepoPrompt 无此 reason；v24-local |
| 11 | `respond` 不产生 user turn 是 RepoPrompt 行为 | **不精确** | RepoPrompt 的 `.instruction` 交互会追加 user turn；v24 的“respond 不加 user_turn_no”是自定策略 |
| 12 | S1 `runs.session_id` 可 `SET NOT NULL` | **不可行** | spawn 子 run 与父 run 同 scope 且可并发；子 run 必须 NULL 或独立 session，否则部分唯一索引冲突 |
| 13 | S1 迁移“每个旧 scope 一个 session” | **错** | 应按 `sessions.json` 的 conversation/bindings 迁移；scope 可含多个逻辑会话与 spawn 子 run |
| 14 | 回滚“关闭开关，旧代码读 v1 字段” | **错** | v1 `SessionStore.load()` 对 `format_version != 1` 直接 quarantine；回滚必须恢复 `.v1.bak` |
| 15 | S1 只需“规格修订批准” | **严重低估** | 需同时改 dp4/dp5/dp6 的 12 文件哈希与 D-UI-6 六路径审计；`init_env` 会 schema_drift；`s14/test_g12.py` 不存在 |

### 0.3 保留的结论

- 会话是分组与控制门面，不是第二个执行状态机；`runs` 仍是唯一执行主体。
- 不建 `turns` 表、不建 `run_attempts` 表、不建可写 `session.status`。
- 四种 turn 口径必须分开命名；对外必须带限定名。
- `parent_run_id` 只表达谱系，不表达投递；子代理结果必须走显式 tool outcome 或显式 steer，并带幂等键。
- provider 原文以 host journal 为权威，DB 只存语义投影与提交顺序。
- 六动词 API 的 wire shape（`v`/`op`/`ok`/`disposition`/`session_id`/`run_id`/`snapshot`/`cursor`/`error`）可以保留；需要修正的是字段语义与映射，不是信封。

### 0.4 五项裁决（2026-11-05，规范性）

评审 §5 的五项决策已经两条 Oracle lane 独立裁决并由协调者合并，完整记录见
[`v24-session-control-decision-record-2026-11-05.md`](../reviews/v24-session-control-decision-record-2026-11-05.md)。本文件以下修订均以该记录为准；与该记录冲突的旧段落作废。

| # | 决策 | 结论 |
|---|---|---|
| 1 | 服务与驱动 | 采用 transport-neutral `v24/session/`；S0 交付 Python 进程内 API + Chainlit UI，MCP/HTTP reserved；单 owner 线程 + 单执行线程（并发 1），不是多 driver/并发 4 |
| 2 | 宿主命令账本 | 持久 start 索引 + per-command receipt；两相位 `intent/completed` + `owner_epoch`；deferred 冻结首次响应；每 session 保留 256 条 completed receipt |
| 3 | 交互安全 | 共享串行域落在 owner 线程；`prepare/execute/finish` 拆分；per-run 锁只在无法搬回 owner 的 settle 路径使用，锁序 `run → DB`，不跨 provider 持有 |
| 4 | 读合同 | S0 禁 poll 增量分页；poll 可推进到已返回前缀最大 seq；wait 无 cursor 先取高水位；per-session cursor 映射 + winner 轮转；`run_started` 按 run_id 不同判定；cursor 增加 `session_revision` |
| 5 | v2 数据政策 | `format_version=2`；legacy 计数近似并标注；`.v1.bak` + `.prev`；回滚前归档 v2 增量；损坏整体 fail-closed；撤回“单会话损坏不影响其他会话” |

**三条不可协商边界**：S0 收口时 `v24/sql/**`、`v24/load.py`、`v24/host/deepseek.py` 的 diff 必须为空；MCP/HTTP 不是 S0 合同；provider 执行串行，控制入口不阻塞。

## 1. 核查范围与方法

### 1.1 证据等级

| 等级 | 含义 | 本文件用法 |
|---|---|---|
| E1 | 直接读到的代码行 | 所有 `file:line` 断言 |
| E2 | 由 E1 推导的调用路径 | 如“poll 不能按 event_seq 分页” |
| E3 | 规格/计划文字 | 只用于说明意图，不作为实现事实 |
| E4 | 未运行 | 所有 gate、DB、provider 行为 |

本文件没有 E4 之外的运行时证据。凡写“会/不会”的地方，都是 E1/E2；凡涉及并发时序的地方，标注为“需运行时 gate 验证”。

### 1.2 未验证事项

- 没有执行 `v24/s1`、`v24/s3`、`v24/s4`、`v24/cordis/dp4..dp6`、`v24/ui` 任一 gate。
- 没有启动嵌入式 PostgreSQL，没有调用 `v24.start`/`v24.steer`/`v24.respond`。
- 没有真实 provider 调用；没有验证 RepoPrompt 的 UI 行为，只读其 Swift 源码。
- 没有验证 `v24/s14/test_g12.py`（该目录不存在）。

## 2. 事实基线

### 2.1 v24 的对象模型

- 冻结内核共十张表；执行主体是 `v24.runs`，没有 `sessions` 表，也没有 `turns` 表。`runs` 的字段包括 `run_id/scope_id/parent_run_id/spawn_key/status/epoch_no/registration_generation/turn_no/driving_generation/remaining_*/interaction/pending_steer/result/revision/ended_at`（`v24/sql/10_schema.sql:25-61`）。
- `status` 闭集：`running/waiting/completed/failed/cancelled/blocked_unknown`；`c_runs_terminal` 规定终态与 `ended_at IS NOT NULL` 等价；`c_runs_waiting` 规定 `waiting` 与 `interaction IS NOT NULL` 等价（`v24/sql/10_schema.sql:50-57`）。
- `v24.events.seq` 是**每个 entity 内**的序号，不是全局 offset：`u_events_cursor UNIQUE (entity_type, entity_id, seq)`（`v24/sql/10_schema.sql:231-244`）。
- `v24.requests` 的主键是 `(principal_id, request_key)`，key 长度 1..512；`host_request` 返回 `request_bytes_base64`、`request_digest_hex`、`response`、`kind`（`v24/sql/10_schema.sql:248-260`；`v24/sql/49_host_reads.sql:550-580`）。
- `scope` 是能力/归属作用域，不是 conversation；UI 目前把一个 conversation 映射到一个 scope（`v24/ui/app.py:302-306`）。
- provider 原文由 host journal 按 run 保存；DB 只存语义投影与提交顺序。`HostWorker._history()` 从 journal 重放 assistant/tool 消息（`v24/host/worker.py:1194-1236`）。

### 2.2 v24 六动词的真实合同

| 动词 | 真实签名/前置 | 关键行为 | 错误码（内核） |
|---|---|---|---|
| `start` | `(scope_id, owner_fiber_id, input, budget, request_key)`；`request_key` 1..512；budget 必须含 `steps`/`tool_calls`，出现的 key 只能是 `steps/tool_calls/tokens/wall_ms` 且都必须是 number；`steps` 1..256、`tool_calls` 0..1024、`tokens` ≤1e12、`wall_ms` 1..86400000 | 不检查“同 scope 是否已有活动 run”；创建 run 时 `epoch_no=1`、`driving_generation=1`、`turn_no=0`、`revision=1`；发 `run_started` + `model_call_requested`；预算 `steps` 预扣 1 | `invalid_args/unauthorized/scope_closed/provider_unavailable/dependency_unresolved/budget_exceeded/retry_with_closure` |
| `poll` | `(run_id, after_revision default 0)` | 返回 `run` 投影（23 个 key）、`revision`、`changed = revision > after_revision`、`events` = 该 run **最早** 64 条（无 `after_event_seq`） | `not_found_or_denied` |
| `wait_check` | `(run_id, registration_generation, epoch, after_event_seq)` | 返回 `run` 投影、`events = seq > after_event_seq` 的最多 64 条；`wake.reason` 只可能是 `terminal/interaction/epoch/event/none`；不比较 `revision` | `not_found_or_denied/registration_stale` |
| `cancel` | `(run_id, expected_generation, request_key)`；generation **非空** | 四个终态（含 `blocked_unknown`）一律 `already_terminal`；同 key 重放原响应 | `invalid_args/unauthorized/already_terminal/stale_generation` |
| `steer` | `(run_id, expected_generation, instruction, request_key)`；generation **非空**；instruction 1..8192 | `completed/failed/cancelled` → `already_terminal`；`blocked_unknown` → `blocked_unknown`；**`waiting` 不拒绝**：会把 `interaction` 置空、epoch/generation +1，通常 status 改 `running`（预算耗尽时 `sealed` → `completed`）；`pending_steer` 单槽，`has_claimed` 时覆盖旧值 | `invalid_args/unauthorized/already_terminal/blocked_unknown/stale_generation` |
| `respond` | `(run_id, interaction_id, response object, expected_generation, request_key)`；generation **非空**；response 必须是 object | `waiting` 且 interaction_id 精确匹配才消费；否则 `interaction_mismatch`；`blocked_unknown` → `blocked_unknown`；`completed/failed/cancelled` → `already_terminal` | `invalid_args/unauthorized/already_terminal/blocked_unknown/interaction_mismatch/stale_generation` |

证据：`v24/sql/47_verbs.sql:33-70`（poll）、`:73-92`（cancel）、`:94-144`（wait_check）、`:147-169`（steer）、`:172-195`（respond）、`:198-224`（start）；`v24/sql/40_interpreters.sql:2526-2532`（steer 终态）、`:2580-2588`（steer 清 interaction）、`:2671-2683`（respond 优先级）、`:2790-2815`（budget 校验）、`:2812-2832`（scope/fiber 检查，无活动 run 检查）。

#### 2.2.1 `start` 的 budget 细节

- `budget` 必须含 `steps` 和 `tool_calls`；`tokens`/`wall_ms` 可省略。
- 出现的每个 key 都必须是 JSON number，且字符串匹配 `^[0-9]+$`。因此 `tokens: null` 会返回 `invalid_args`，不是“不限”。
- `steps` 与 `wall_ms` 为 0 会返回 `invalid_args`；`tool_calls` 可以为 0。
- 超上限不是 `invalid_args`，而是 `budget_exceeded`（`v24/sql/40_interpreters.sql:2790-2815`）。
- `v24/ui/control.py:167-175` 的默认 budget 是 `{"steps":24,"tool_calls":24,"tokens":20000,"wall_ms":600000}`（`v24/ui/catalog.py:32`），与 API 草案一致；但 API 的“null 表示不限”不成立。

#### 2.2.2 `poll` 与 `wait_check` 的 event 能力

- `v24.poll` 的 events 子查询是 `ORDER BY seq LIMIT 64`，没有 `seq > after` 条件；`after_revision` 只影响 `changed`（`v24/sql/47_verbs.sql:50-70`）。
- `v24.wait_check` 的 events 子查询有 `seq > p_after_event_seq`（`v24/sql/47_verbs.sql:120-129`）。
- 因此：**按 event_seq 增量读只能走 `wait_check`**。S0 若坚持不改 SQL，`poll.include_events` 的“after cursor”语义必须改为：先 `v24.poll` 取快照/`changed`，再 `v24.wait_check(..., after_event_seq)` 取增量；或 v1 直接不做 event 分页。
- 新客户端不带 cursor 的 `poll` 只能看到最早 64 条，不是最近 64 条；这是内核行为，不是 API 可以“组合”出来的，除非另加读函数（S0 不允许）或改为 `wait_check(..., after_event_seq=0)`（同样最早 64 条）。

#### 2.2.3 `steer` 对 `waiting` 的真实行为

`v24.interpret_steer` 在非终态、generation 匹配后，直接构造 `run_set`：

```
epoch_no = current_run.epoch_no + 1
driving_generation = current_run.driving_generation + 1
interaction = NULL
status = sealed ? completed : running
pending_steer = has_claimed ? {...} : NULL
```

（`sealed` 由预算是否还允许下一轮决定；预算耗尽时 `steer` 不会继续跑，而是封口为 `completed`。）

证据：`v24/sql/40_interpreters.sql:2570-2600`。这意味着：

- 会话层**必须**在调用 `v24.steer` 前拒绝 `waiting`，否则用户的待回答问题会被静默丢掉。
- 仅靠“先 poll 看到 waiting，再拒绝”不够：在 poll 与 steer 之间，worker 可能把 run 从 running 推进到 waiting（模型结算产生 interaction），随后 steer 会把新 interaction 清掉。S0 需要与 driver 共用 per-run 锁，或明确接受这个丢失窗口（不推荐）。
- 该行为不是 kernel bug：run 级 `steer` 的语义是“打断当前执行并插入指令”，它有权清 interaction；会话级“等待输入时改用 respond”是门面策略。

### 2.3 v24 读面的真实能力

| 读面 | 能力 | 缺口 |
|---|---|---|
| `v24.poll` | run 投影 23 key、revision、changed、最早 64 events | 无 `after_event_seq`；无 session 字段 |
| `v24.wait_check` | run 投影、after_event_seq 增量 events、wake reason | 无 revision 比较；无 session/run_started |
| `v24.host_runs` | 按 scope 分页 run，items 是 `run_projection` | **不含 `parent_run_id`/`spawn_key`**，S0 无法区分 spawn 子 run |
| `v24.host_run_effects` | 按 run 分页 effect | 不是 event 读；不能替代 event cursor |
| `v24.host_request` | 按 `(principal, request_key)` 查原始请求/响应 | 无 kind 过滤；key 1..512 |
| `v24.events` 直读 | 有 `(entity_type, entity_id, seq)` 索引 | S0 不改 SQL，不能新增读函数 |

证据：`v24/sql/49_host_reads.sql:76-127`（host_runs）、`:209-288`（host_run_effects）、`:550-580`（host_request）；`v24/sql/47_verbs.sql:14-31`（run_projection 的 23 个字段）。

### 2.4 v24 UI/host 的真实状态

| 事实 | 证据 | 设计影响 |
|---|---|---|
| `SessionStore` 是 v1；`load()` 对 `format_version != 1` 直接 quarantine | `v24/ui/sessions.py:14`、`:77` | 草案“旧代码读 v1 字段”式回滚不成立；必须恢复 `.v1.bak` |
| 每个 conversation 的 bindings 只保留最近 200 条 | `v24/ui/sessions.py:195-200` | `run_no`/`counters.runs` 不能由 bindings 精确派生 |
| 每个 conversation 的 turn 只保留最近 200 条 | `v24/ui/sessions.py:175-200` | `user_turn_no` 不能由 turns 精确派生 |
| `app.seq` 是进程全局；`key()` 与 `_turn()` 共用它；重启归零 | `v24/ui/app.py:131`、`:216-219`、`:333-335` | `seq` 不是 per-session 序号，且有请求 key 造成的空洞 |
| `answer()` 成功后会 `_turn()`，即当前 UI 的 respond 会追加 user turn | `v24/ui/app.py:458-466` | 草案“respond 不变”是行为变更，不是现状 |
| real 模式 `answer()` 直接 `waiting_unsupported`，不调 respond | `v24/ui/app.py:446-449` | S0 respond 实际是 fake/scripted-only |
| 普通文本在终态 run 上走“同 scope 新 run”，不是 `steer`；`_steer` 在终态只提示 `already_terminal` | `v24/ui/app.py:383-430`、`:425-430` | 草案的“终态 steer 同 session 新 run”需要改 UI 入口 |
| `AgentRuntime.cancel/steer/respond` 总是读当前 generation，调用方无法传 CAS | `v24/ui/control.py:221-225` | API 的 `expected_generation` 可选语义要在 service 层显式实现，不能复用这些 helper |
| `SessionStore` 有 owner-thread 检查；`app` 在 hub thread 上调 store | `v24/ui/sessions.py:63-65`；`v24/ui/app.py:204-206` | `wait` 不能在 hub thread 同步睡眠；需要投递/异步 |
| `host/deepseek.py` 对 `start/spawn` 只接受 `system`/`user` 消息 | `v24/host/deepseek.py:261-293` | S0 seed 只能是 system 历史块；完整 transcript seed 是 M7 |
| `v24/ui/migrations.py` 是空注册表，未 import；不迁移 DB | `v24/ui/migrations.py:13-22` | S1 没有现成 DB migration executor |
| `v24/ui/env.py` 对 SQL/function/column 指纹漂移直接 `schema_drift` | `v24/ui/env.py:184-189` | S1 加列后，现有 scratch DB 必须先迁移或重建 |

### 2.5 RepoPrompt-CE 的真实语义

| 断言 | 判定 | 证据/说明 |
|---|---|---|
| `start` 总是新建 session，非空 `session_id` 被拒绝 | **成立** | `AgentRunMCPToolService.swift:496-499`；`normalizedString` 会 trim，空白 tolerated |
| `poll/wait/cancel/steer/respond` 以 `session_id` 寻址 | **成立** | 五个入口都走 `resolveControlSessionID`；无 `run_id` 控制参数（`AgentRunMCPToolService.swift:3486-3530`） |
| 终态 session 的 `steer` 在同一 session 内开新 run | **成立** | `runState.isActive` 为 false 时走 `withMCPRunEpochTransition(.steering)` → `mcpDispatchInstruction(allowStartingRun:true)` → `.startedRun`（`AgentRunMCPToolService.swift:1567`、`:1583-1590`；`AgentModeViewModel.swift:13401`、`:13442`） |
| `steer` 在 waiting 时拒绝，提示用 `respond` | **基本成立，有例外** | `mcpPendingInteraction` 且 kind != `.instruction` 时抛 “Use agent_run.respond instead”（`AgentModeViewModel.swift:13348-13353`）；`.instruction` 的 waiting continuation 允许 steer |
| `respond` 需要精确 `interaction_id`，错误 id 被拒 | **成立** | `AgentModeViewModel.swift:13535-13541`；错误 id 不落任何响应 |
| `respond` 不产生 user turn | **不精确** | 普通 question/approval/permissions/elicitation 不产生；`.instruction` 会走 `submitUserTurn`，追加 `.user` turn（`AgentModeViewModel.swift:13535-13568`） |
| 终态 `cancel` 返回 `already_terminal` | **不成立** | 全仓 `already_terminal` 0 次；终态 cancel 在 `AgentRunMCPToolService.swift:1371-1372` 抛 `invalidParams`，或在 active-run guard `:1349` 抛 denial；不返回结构化码/快照 |
| `wait` 有 `run_started` wake reason | **不成立** | RepoPrompt `WakeReason` 只有 `instructionDelivered` / `steeringRequested`（`Sources/RepoPromptDomainRuntime/DomainAgentRunSessionStore.swift:160-163`；用法：`AgentModeViewModel.swift:8495`、`:8559`；`AgentRunMCPToolService.swift:2057`）；新 run 对外表现为 `.epochAdvanced` → `superseded` 或静默 re-cursor |
| `start` 默认等待（`detach=false`） | **成立** | `let detach = parseBool(args["detach"]) ?? false`（`AgentRunMCPToolService.swift:501`），默认进入 wait/timeout 路径 |
| `session_id` 跨 run 稳定；run 是内部执行身份 | **成立** | session 快照携带稳定 `sessionID` + 可选 `runID`；每次 run/attempt 是新 epoch |

> 结论：草案 §1.2 的第 1、2、5 条基本成立；第 3 条的“控制世代/事件 wake”是对 RepoPrompt 的抽象，不是其原名词；第 4 条的 `already_terminal` 是误植；第 6 条的“不产生 user turn”应加 `.instruction` 例外；第 7 条成立。§8 对标矩阵应把“RepoPrompt”列与“v24 目标”列分开，不能把 v24 自造码写进前一列。

### 2.6 冻结 SQL 与 gate 的真实约束

| 约束 | 证据 | 对 S0/S1 的影响 |
|---|---|---|
| 12 个 `v24/sql` 文件整文件 SHA-256 被硬编码 | `v24/cordis/dp4/test_closeout.py:35-48`；dp5 `test_boundaries.py:591-593`；dp6 `test_boundaries.py:859-861` | S1 改 `10_schema.sql` 会同时打破三套 gate；S0 不碰 SQL 则不受影响 |
| D-UI-6 要求相对 `57e2c1e` 的 diff 恰好是 6 个已批准路径 | dp5/dp6 的 D-UI-6 审计（`v24/cordis/dp5/test_boundaries.py`、`dp6/test_boundaries.py`） | 改 `v24/load.py`、`v24/sql`、`v24/s1..s12` 都需更新 byte-lock/替换表，不是普通 gate 更新 |
| `v24/load.py` 只接受 12 个 canonical 文件的有序前缀；出现未注册 SQL 文件即 `ValueError` | `v24/load.py:40-63` | 新增第 13 个 SQL 文件会打破 `test_ui_gate.py:1700` 的 `len(SQL_LOAD_ORDER)==12`，并触发 D-UI-6 |
| `v24/ui/env.py` 对 SQL/function/column 指纹漂移直接 `schema_drift` | `v24/ui/env.py:184-189` | S1 加列后，现有 scratch DB 不能直接 `init_env`；需 pre-init 迁移或重建 |
| `v24/s1/test_ddl.py` 的 partial unique index 闭集只覆盖 `episodes/slots/pins` | `v24/s1/test_ddl.py:179-185` | 加 `runs` 列/索引**本身**不会打破该断言；但若新增索引断言或编辑该文件，会触发 D-UI-6 |
| `run_projection` 的 23 个 key 是冻结 S3 C14 投影 | `v24/sql/47_verbs.sql:14-31`；`v24/s3/test_g2.py:24-27`、`:101`、`:192`、`:259`；`v24/s4/test_g2b.py:669-677` | `session_id` 不应进 `run_projection`；S1 用独立 session 读函数 |
| SECURITY DEFINER 函数有 load-time allowlist + 测试闭集 | `v24/sql/50_permissions.sql:82-91`；`v24/s1/test_g1.py:120-124`、`:803-811` | S1 新增读函数需同时改 allowlist 与 `test_g1.py`（后者在 byte-lock 内） |
| `v24/ui/migrations.py` 为空、未使用；没有 DB migration 框架 | `v24/ui/migrations.py:13-22` | S1 回填没有执行器；需新脚本，且在 `init_env` 之前运行或重置 DB |
| `v24/s14/test_g12.py` 不存在；`s14` 目录不存在 | tree | 计划的 S1 gate 清单有一条空命令 |
| `v24/ui/test_ui_gate.py` 断言 `deepseek.py` 运行中哈希不变 | `v24/ui/test_ui_gate.py:1695-1697`、`:1772` | S0 不应改 `deepseek.py`；M7 seed 扩展会触发该 gate |

#### 2.6.1 S1 的真实成本

S1 的 schema 改动本身很小：`runs` 加一列 + 一个部分唯一索引，`test_ddl.py` 的现有闭集不检查 `runs` 的 partial index，所以不会因“多一个索引”而红。真正的成本在治理面：

1. `10_schema.sql` 是 12 个冻结文件之一；改它必须更新 **dp4、dp5、dp6 三份** `FROZEN` 字典。
2. D-UI-6 的“恰好 6 个 M 路径”不包含 `10_schema.sql`；必须显式修改 dp5/dp6 的审计基线/替换表。
3. `v24/load.py` 不能改（byte-lock）；因此 S1 **不能**通过“新增 SQL 文件”绕过，只能在 `10_schema.sql`/`47_verbs.sql`/`49_host_reads.sql` 等既有文件里改，并承担 1、2。
4. `run_projection`/`poll`/`wait_check` 不要加 `session_id`；否则 `v24/s3/test_g2.py`（4 处）和 `v24/s4/test_g2b.py`（3 处）的投影断言红。S1 用独立的 `host_session_*` 读函数。
5. 新 DEFINER 读函数会触发 `50_permissions.sql` 的 allowlist、`v24/s1/test_g1.py` 的两处闭集；`test_g1.py` 在 byte-lock 内，改动需要 dp5/dp6 的替换表。
6. `init_env` 的 `schema_drift` 意味着迁移必须在它之前跑，或重置 scratch DB；没有现成 migration runner。
7. `v24/ui/d_ui_6_acl.py:70` 硬编码 `50_permissions.sql` 的 digest；任何 permissions 改动都会让它报 `permissions_source_drift`。

> **判定：S1 在当前冻结基线下不可按“普通规格修订”落地。** 它需要一次明确的 baseline bump（三套 hash + D-UI-6 + `load.py`/test 闭集）。这不是 S0 的工作；S0 应把 S1 当作“需要单独治理批准的下一版本”，而不是 M5 的自然延伸。

## 3. 设计判定

### 3.1 方向正确的部分

1. **会话门面而非第二状态机**：`runs` 的 status/epoch/generation/turn_no/revision 已经是执行事实；会话层只做归属、解析、快照、控制改写。这与 v24 的现有不变量一致。
2. **不建 turns 表**：四种 turn 口径确实不能合并；`v24` 的 `turn_no` 是 effect settlement，UI 的 turn 是请求边界，RepoPrompt 的 transcript turn 是用户可见正文。建一张表会制造第二真相源。
3. **provider 原文不进 DB**：journal 已经是 run 级原文权威；DB 只存投影。把 transcript 搬进 DB 会与 journal 的 dispatch/settle 语义打架。
4. **parent 边不等于投递**：v24 的 `parent_run_id` 只用于 spawn 谱系；子 run 的结果回灌必须走 tool outcome 或显式 steer。这个评审规则是正确的。
5. **S0 不改 SQL 的路线**：`v24.poll`/`wait_check`/`host_request`/`host_runs` 足以支撑一个单进程 UI 门面；S1 再解决 DB 归属。这个排序正确。

### 3.2 不成立或需要限定的断言

| 草案位置 | 断言 | 判定 | 修订 |
|---|---|---|---|
| plane §1.2.4 | RepoPrompt 终态 cancel 返回 `already_terminal` | 错 | 改为“v24-local 错误码；RepoPrompt 当前无此码” |
| plane §1.2.6 / §8 | RepoPrompt respond 不产生 user turn | 不精确 | 加 `.instruction` 例外；v24 自己规定 respond 不加 `user_turn_no` |
| plane §1.2.3 / API §5.3 | wait 的 `run_started` wake | 错（作为 parity） | 标注 v24-local；RepoPrompt 只有 instructionDelivered/steeringRequested |
| plane §1.1 表 | `poll` events 可按 cursor 分页 | 错 | `poll` 无 event cursor；用 `wait_check` 或 v1 不分页 |
| plane §5.3 | `user_turn_no` 由 `seq` 派生 | 错 | 会话级持久计数器 |
| plane §5.2 / API §4.5 | `counters.runs` 可由 bindings 派生 | 错 | 持久计数器；bindings 截断 200 |
| API §2.5 | `tokens: null` 表示不限 | 错 | 省略 tokens；null 会被 `invalid_args` |
| API §2.5 | budget 均非负 | 错 | steps/wall ≥1；有上限 |
| API §5.1 | `model` 可指定已注册 ModelSpec | 错 | 当前 host 固定 `deepseek-flash`；S0 只能“必须匹配” |
| API §5.1 | `toolset` 可按 session 选 | 部分错 | 当前 UI 固定 toolset；S0 只能“必须匹配” |
| API §5.6 | respond 不需要 `expected_generation` | 不完整 | 内核需要；service 读当前 generation，客户端无 CAS |
| API §5.4 | cancel 的 `expected_generation` 可选 | 不完整 | 内核必填；service 填充，CAS 只作为门面参数 |
| API §5.5 | steer 的 `expected_generation` 可选 | 不完整 | 同上；且不能解决 waiting 竞态 |
| API §5.6 | respond 终态 `already_terminal` | 不完整 | `blocked_unknown` 内核返回 `blocked_unknown`；需映射 |
| plane §7.1 / §7.3 | 先分配 session 再写意图 vs 先查 pending_start | 内部矛盾 | 统一为“先查/写意图，再 mint session_id” |
| plane §7.9 / plan §7.2 | 关闭开关，旧代码读 v1 字段 | 错 | v1 strict quarantine；回滚恢复 `.v1.bak` |
| plane §4.2 / plan §3 | S1 每 scope 一个 session | 错 | 按 conversation bindings 迁移；spawn 子 run 单独处理 |
| plane §4.2 | S1 可 `SET NOT NULL` | 不可行 | 子 run 必须 NULL 或独立 session；建议保持 nullable |
| plane §4.1 | 服务先放 `v24/ui`，S1 再提升 | 需限定 | 若目标是 MCP/CLI，S0 就必须 transport-neutral；否则 S0 只是 UI facade |
| plane §5.2 | active_run_id 缓存可信 | 不充分 | 读时按 bindings/DB 重算；缓存只作提示 |

### 3.3 设计层面的硬缺陷与修正

#### D1. `poll` 的 event cursor

**问题**：API §5.2 说 `include_events` 在 `cursor.event_seq` 之后返回最多 64 条。`v24.poll` 没有 `after_event_seq`，它恒返回最早 64 条；一旦 run 的事件超过 64 条，cursor 之后的事件永远读不到。

**修正（S0，不改 SQL；2026-11-05 裁决 D4）**：

- **S0 明确禁止 poll 增量分页。** `poll` 的 `include_events=true` 只返回当前 run 的**最早 64 条**，不按 `cursor.event_seq` 取窗口；`v24.poll` 没有 `after_event_seq`，不把 `wait_check` 伪装成 poll 分页。
- `poll` 返回成功后，把 cursor 的 `event_seq` 推进到“已返回事件前缀的最大 seq”（不超过 `max(in.event_seq, prefix_max)`）；`include_events=false` 时不变；换 run 时重置为 0。这不跳事件，只消除 1–64 的重复回放。
- 需要“从上次读位置继续”的客户端使用 `wait`；`wait` 只把 `event_seq` 推进到**实际返回的最后一条**事件，不越过未返回事件。
- 新客户端无 cursor 时，`poll` 返回最早 64 条；文档必须写明这是能力边界，不是“最近窗口”。

#### D2. `user_turn_no`

**问题**：`ui.seq` 是全局、与请求 key 共用、重启归零；`answer()` 也写 turn；`turns.jsonl` 每会话只留 200 条且无类型字段。草案的“由 seq 派生”会得到错值。

**修正**：

- `sessions.json` v2 的 session 记录增加持久 `user_turn_no`。
- `start` 成功 +1；`steer` 成功（同 run 或新 run）+1；`respond` 不变；`cancel/poll/wait` 不变；重放不变。
- 旧 v1 会话迁移：无法精确还原（answer 与 steer 都是 turn 行，且旧 seq 有空洞）。建议 `user_turn_no = len(turns for conversation)`，并在文档中标注“legacy overcount by answered interactions”；或从 0 开始作为 v2-only 计数，历史展示继续用 turns。二者选一，不能声称精确迁移。`len(turns)` 同时受每会话 200 条上限，超过 200 的会话会 undercount；legacy 值只能是近似。
- `ui.seq` 继续只作进程内 request-key 唯一性来源，不再进入 turn 语义。

#### D3. `run_no` / `counters.runs`

**问题**：bindings 只留 200 条；`host_runs` 返回的 `run_projection` 不含 `parent_run_id`，S0 无法区分 spawn 子 run。草案的“由 bindings 派生”在 200 条后失真。

**修正**：

- `sessions.json` v2 持久 `run_no`；`start` 成功 = 1；终态 `steer` 新 run +1；同 run `steer` 不变；重放不变。
- 旧 v1 迁移：`run_no = len(bindings)`，并标注 200 条上限的 legacy 误差；不要从 `host_runs` 数，因为会把 spawn 子 run 算进来。
- `counters.runs` 与 `run_no` 分开：`runs` 可包含历史/子 run 的统计口径要在 API 中写清；S0 建议 `runs = run_no`，只计宿主创建的顶层 run。
- S1 若有 `session_id`，可用 `count(runs WHERE session_id=... AND parent_run_id IS NULL)` 精确化；但这需要独立读函数，不能改 `run_projection`。

#### D4. budget 语义

**修正**：

- `tokens` 省略表示不限；传 `null` 会 `invalid_args`。
- `steps` ≥1，`wall_ms` ≥1；`tool_calls` ≥0。
- 上限：steps 256、tool_calls 1024、tokens 1e12、wall_ms 86400000；超限 `budget_exceeded`。
- S0 默认 budget 用 `v24/ui/catalog.py:32` 的 24/24/20000/600000。

#### D5. `model` / `toolset` / `workspace_root`

**问题**：当前 host 模型固定 `deepseek-flash`（`v24/host/deepseek.py:39`）；UI 的 toolset 在构造时固定，`AgentRuntime.families()` 使用 `self.toolset`；`workspace_root` 由 `env` 固定。API 的 `model` “已注册 ModelSpec”没有实现基础。

**修正（S0）**：

- `model` 字段保留为“display/metadata”，但必须等于宿主模型；不匹配返回 `catalog_changed` 或 `invalid_args`。
- `toolset` 必须等于宿主 toolset；不做 per-session 动态安装（那是 P1）。
- `workspace_root` 必须等于宿主 workspace；否则 `workspace_mismatch`。
- 若产品确实需要 per-session model/toolset，移到 S1/P1，并先做 registry/dynamic install 设计；不要把它塞进 S0 合同。

#### D6. waiting `steer` 的竞态

**问题**：`v24.steer` 在 waiting 上会清 interaction；会话层“先 poll 再拒绝”不是原子的。

**修正（S0；2026-11-05 裁决 D3，取代 per-run 锁作为主方案）**：

- **共享串行域落在 owner 线程，而不是一把全局锁。** 单 owner 线程串行执行所有控制（start/steer/respond/cancel）与 settle/finish；单执行线程（并发 1）只跑 provider/tool；任何锁都不得包住 provider 调用。
- `HostWorker.run_once` 拆为 `prepare`（owner：claim + journal）/ `execute`（exec：只调 adapter/tool，不碰 DB/journal）/ `finish`（owner：settle + generation/late 规则）。
- `steer` 的预检与内核写都在 owner；driver 出 interaction 的 settle 也在 owner，因此天然互斥，没有“先 poll 再拒绝”的竞态窗口。
- 只有在某个 settle/recover/reconcile **暂时无法**搬回 owner 时，才用 per-run `threading.Lock`；锁序固定 `run → DB`，不得反向申请，不得跨 provider 持有。
- S0 明确“单宿主进程”；多进程/多客户端需要 S1 的 SQL 前置条件（如 `expected_status`）。
- 验收必须用 barrier 在“steer 预检后、内核写前”插入 interaction settle，并覆盖 recover/reconcile，而不是只测静态 waiting。

#### D7. `respond` 的 error map 与 real 模式

**问题**：内核 `v24.respond` 对 `blocked_unknown` 返回 `blocked_unknown`，不是 `already_terminal`；API §5.6 的错误表没有 `blocked_unknown`，但 §5.6 规则说“终态 already_terminal”。此外，当前 real 模式不产生 interaction，`answer()` 直接 `waiting_unsupported`。

**修正**：

- 门面把 `blocked_unknown` 统一映射为 `already_terminal`（带 `details.status="blocked_unknown"`），或把 `blocked_unknown` 加入 respond 错误表；二选一，不能遗漏。注意内核 `blocked_unknown` 返回 `write:false`，而 `completed/failed/cancelled` 返回 `write:true`；映射时不要伪造 `write=true`，也不要在前者写 request journal，否则重试语义会分叉。
- S0 的 `respond` 明确为 fake/scripted-only；real 模式固定返回 `waiting_unsupported`（2026-11-05 裁决，不再保留“或 capability_unavailable”），不构造 adapter、不开 DB、零 run 写，不要声称六动词在 real 全可用。
- 若要 real respond，先在 `DeepSeekAdapter`/toolset 中实现 interaction 产出与 response 消费；这是独立里程碑，不属于 S0 门面。

#### D8. S1 的 spawn / NOT NULL / 一活动 run

**问题**：spawn 子 run 与父 run 同 scope（子 run 对象在 `v24/sql/48_loop.sql:785-808` 直接写 `scope_id = r.scope_id`；校验在 `:2218-2224`；插入在 `:2880`），且父 run 在子 run 运行期间通常仍是 `running`（或等待 tool outcome）。若子 run 继承父的 `session_id`，`UNIQUE (session_id) WHERE ended_at IS NULL` 立刻冲突；若 `SET NOT NULL`，子 run 又必须有一个 session。

**修正（S1）**：

- `runs.session_id` **保持 nullable**。
- 只有宿主创建/续接的顶层 run 写 `session_id`；spawn 子 run 保持 `NULL`（不继承）。
- 部分唯一索引写成 `UNIQUE (session_id) WHERE session_id IS NOT NULL AND ended_at IS NULL`；NULL 行不参与。
- `session` 的成员查询显式 `WHERE session_id = ...`；子 run 不在六动词的会话成员内，只是执行子节点。
- 如果产品要求“子代理也是会话”，则子 run 必须获得**自己的** session_id（不是父的），并在 spawn 响应/管理面里暴露；这是另一个设计，不应与 S1 混在一起。
- 不要 `SET NOT NULL`；否则 `INSERT INTO v24.runs SELECT * FROM jsonb_populate_record(...)` 的 spawn 路径、`start` 校验、迁移回填都要改，成本远大于收益。

#### D9. S1 迁移按 scope 是错的

**问题**：`scope` 可以包含多个逻辑会话的 run（内核不禁止），也可以包含 spawn 子 run；`sessions.json` 才是 conversation 的权威。草案/计划的“每个旧 scope 一个 session，回填该 scope 所有 run”会把不同会话合并，或把父子 run 放进同一 session。

**修正（S1）**：

1. 以 `sessions.json` 的 conversation 为单位分配 `session_id`（可复用 `conversation_id`）。
2. 对每个 conversation 的 bindings：把对应 `run_id` 的 `session_id` 回填；若同一 run 被两个 conversation 绑定，迁移失败。
3. `parent_run_id IS NOT NULL` 的 run 不回填，保持 NULL。
4. 不在任何 binding 中的顶层 run：要么建 synthetic session，要么保持 NULL 并标记 legacy；不要按 scope 合并。
5. 每个 session 的 bindings 中若 >1 个非终态 run，迁移失败并人工处理。
6. 迁移脚本必须在 `init_env` 之前运行，或显式重置 scratch DB；没有现成 migration runner。
7. 迁移后校验：`count(runs WHERE session_id IS NOT NULL AND ended_at IS NULL GROUP BY session_id) <= 1`。

#### D10. 回滚

**问题**：v1 `SessionStore.load()` 对 `format_version != 1` 直接 quarantine；草案的“关闭开关 + 旧代码读 v1 字段”不成立。

**修正（S0；2026-11-05 裁决 D5，已定稿）**：

- 采用 `format_version=2`；旧代码不能读 v2，回滚必须恢复 `.v1.bak`，不能让旧代码“忽略新字段”。
- `sessions.json` 与 `turns.jsonl` 写 `.v1.bak`（0600）；每次原子替换保留 `.prev`；回滚前先把 v2 增量归档（sessions/turns/transcript/journal，0700/0600），再恢复 `.v1.bak`；不覆盖归档、不做自动双向合并。
- 特性开关只控制新入口，不改变 v2 文件格式；开关关闭时，新代码仍要能读 v2。
- 损坏 JSON/版本/必要结构 → 整体 fail-closed，保留原件并给诊断；不自动建空 store，也不声称“单会话损坏不影响其他会话”。

#### D11. 服务放置与驱动

**问题**：草案把 `SessionService` 放 `v24/ui`，但又说 MCP/UI/CLI 共用；`v24/ui` 的 `SessionStore` 有 owner-thread 检查，`app` 在 hub thread 上调 store；`wait` 不能阻塞 hub。当前 `app.tick` 是唯一驱动 run 的循环；如果 service 在 CLI/MCP 里被调用，没有 driver，run 不会推进。

**修正（S0；2026-11-05 裁决 D1，已定稿）**：

- **采用方案 A：`v24/session/`。** `SessionService` 只依赖 runtime protocol，不 import Chainlit 或 `v24.ui`；UI/CLI/MCP 都只是 adapter。
- **S0 交付范围**：Python 进程内 API + Chainlit UI。MCP/HTTP 标为 reserved，不实现 MCP server，不做通用 CLI 合同；现有 `v24.ui.real` CLI smoke 保持可运行。
- 线程模型：`session-owner`（store/runtime/roster/waiter、控制与 finish）+ `session-exec`（adapter/tool，并发 1）+ 调用方 wait 线程。`wait` 不得在 owner 上同步睡眠。
- `start` 只完成准入，不驱动首轮；service 自己的 driver 循环推进 roster；`app.tick` 退出“唯一驱动者”地位，M4 完成 UI 全量切换。
- 若将来产品改选 UI-only，必须同步删除 API 的 MCP/CLI 承诺并降级本设计；不得文档声称 transport-neutral、实现却依赖 hub 线程。

#### D12. `active_run_id` 缓存

**问题**：草案 §5.2 的 `session_status` 先看 `active_run_id`，再看 `last_run_id`；如果 `active_run_id` 指向已终态 run，而 bindings 里还有更新的活动 run，会误报 terminal。

**修正**：

- 每次快照从 bindings（或 S1 的 `runs WHERE session_id`）按创建时间倒序找**第一个非终态** run；找不到再用最后一个 run 的状态。
- `active_run_id` 只作为提示/索引，不参与权威判定；写入时更新，读时重算。
- 若 bindings 被截断 200，仍能保证“最新的活动 run 在 bindings 里”（bindings 保留最近的），但更早的活动 run 可能被截断；S0 应把“同时至多一个活动 run”作为不变量，避免依赖截断数据。

#### D13. `already_terminal` / `run_started` 的定位

**修正**：

- 保留 `already_terminal` 作为 v24 门面的错误码：它比 RepoPrompt 的 `invalidParams` 更适合客户端对账；但文档必须写“v24-local, not RepoPrompt parity”。
- 保留 `run_started` 作为 v24 门面的 wake reason：它解决“另一个客户端开了新 run”的可见性；但文档必须写“v24-local；RepoPrompt 用 epochAdvanced/superseded，不是这个名字”。
- 不要在用“像 RepoPrompt”作为验收判据的地方引用这两个码；验收应看“客户端是否能正确对账/继续”，而不是名字。

#### D14. `respond` 的 `expected_generation`

**问题**：API §5.6 的请求字段没有 `expected_generation`，但内核 `v24.respond` 必填。门面若每次读当前 generation，可能与客户端看到的快照不同；若客户端想 CAS，又没有字段。

**修正**：

- 请求增加可选 `expected_generation`；不传时门面读当前 generation（best-effort），传时严格 CAS。
- 错误 `stale_generation` 已在 API 表中；把它加入 §5.6 的“可能返回”说明。
- 同理 `cancel`/`steer` 的 `expected_generation` 是“可选但门面必填内核参数”，API 要写清。

#### D15. `start` 的 session_id 生成与 run key

**问题**：草案说“session_id 为空时由宿主/内核生成”；但 run key 派生是 `s:session_id:op:hash(client_key)`，如果 session_id 由内核在 `v24.start` 里生成，宿主在调用前没有它，无法派生稳定 key。两者矛盾。

**修正（S0 宿主路径；`v24.start(session_id)` 部分标 S1-only）**：

- **S0（已实施口径）**：宿主总是先 mint `session_id`，用它在宿主账本中写 `start_index` 与派生 run key，再调**当前签名**的 `v24.start`（不传 session_id，不改冻结 SQL）；`session_id` 只存在于宿主 v2 store。
- **S1-only（本计划不实施）**：`v24.start` 增加可选 `p_session_id`；宿主路径总是传非空；kernel 对 NULL 只允许内部 spawn。
- 这样 S0 崩溃后能靠 `host_request(run_key)` 找回 `run_id`，`session_id` 也已写入 `start_index`；不依赖内核返回 session_id。

#### D16. `start` intent 的恢复与围栏

**问题**：草案说“同 key 重试从失败点继续”，但没有说崩溃的 start 意图何时可被接管。若一个线程在写意图后死掉，后续同 key 请求会看到 `starting` 却无人推进。

**修正（S0；2026-11-05 裁决 D2，取代时间 lease）**：

- 采用两相位 `intent / completed` + 递增 `owner_epoch` 围栏，不使用时间 lease。
- `intent` 记录 `owner_epoch`、`command_id`、session_id、run key、normalized request 与 digest；写入后同 key 请求看到 `intent` 返回 `deferred`（首次响应冻结）。
- 恢复：按 `run_request_key` 查 `host_request`；命中则补完本地 bind/counter/turn/receipt，未命中才允许同 key 重试。
- `owner_epoch` 只用于拒绝旧 owner 的迟到写；S0 单进程，崩溃后没有旧线程可写回，不引入时钟边界。
- 清理路径必须可重入，且不重复 `v24.start`（同 run key 由 request journal 兜底）。

## 4. 修订后的设计

### 4.1 语义合同（五条，修订）

1. **会话是分组，不是执行**：只回答“哪些 run 属于同一会话”“当前哪个 run 是活动的”“用户看到了什么”。预算、状态机、终态、effect 只在 run/effect。
2. **run 是唯一执行主体**：会话状态从 run 派生，不存可写 `session.status`；`session.state` 只表达 `starting/active/closed` 的宿主生命周期，不表达 run 的完成/失败。
3. **turn 是四个派生量**：`effect_settlement_no`（建议对外叫 `run_turn_no`，并注明 late-settlement 例外）/`model_round_no`/`tool_round_no`/`user_turn_no`；对外必须带限定名。
4. **parent 边不等于投递**：`parent_run_id` 只表达 spawn 谱系；结果回灌必须走显式 tool outcome 或显式 steer，并带由 child run_id 派生的幂等键。
5. **provider 原文不进 DB**：journal 是原文权威，DB 只存语义投影与提交顺序；compaction 的“少显示”与“换上下文”分开描述。

补充两条 v24-local 约定：

6. `already_terminal` 是 v24 门面的错误码，不是 RepoPrompt 的码；用于 cancel/respond 的终态对账。
7. `run_started` 是 v24 门面的 wake reason，不是 RepoPrompt 的 `WakeReason`；用于“另一个客户端开了新 run”的可见性。

### 4.2 对象模型与状态派生

#### 4.2.1 Session 记录（`sessions.json` v2）

| 字段 | 说明 |
|---|---|
| `session_id` | 稳定 UUID；S0 可等于旧 `conversation_id` |
| `name` | 显示名；默认 message 前 40 字 |
| `state` | `starting / active / closed`（宿主生命周期，不是 run 状态） |
| `scope_id` | 当前 scope；S0 与 session 一对一 |
| `realm` | UI realm |
| `workspace_root` | 必须等于宿主 workspace |
| `toolset` | 必须等于宿主 toolset |
| `model` | 显示/校验用；当前固定 `deepseek-flash` |
| `bindings[]` | `{scope_id, run_id, at, realm, workspace_root, toolset, catalog_digest, mode, limits_digest}`；只保留最近 200 条；顶层 `workspace_root/toolset/model` 是当前默认，binding 保留历史运行的环境指纹 |
| `active_run_id` | 提示缓存；读时重算 |
| `run_no` | 持久计数器；顶层 run 数 |
| `user_turn_no` | 持久计数器；start/steer |
| `counter_origin` | `native_v2 / legacy_approx`；legacy 迁移时显式标记 |
| `session_revision` | 纯宿主变化的观察计数；starting→active/closed、计数/绑定变化时递增 |
| `owner_principal_id` | 会话 owner；未授权 principal 一律 `not_found_or_denied` |
| `start_index` | `(principal, key_hash) → {session_id, run_key, command_id, phase}`；不随 receipt 淘汰 |
| `receipts[]` | 每命令 `{command_id, op, key_hash, digest, normalized_request, resolved_variant, target_run_id, run_request_key, phase, outcome, original_envelope, owner_epoch, at}`；completed 保留 256 条 |
| `pending_intent` | 当前未完成的 start intent；含 `owner_epoch`、run key、payload digest；不再使用时间 lease |
| `created_at/updated_at` | 时间 |
| `resume_token_hash` | 兼容旧 `/resume` |
| `setup_incomplete` | 兼容旧 UI |

#### 4.2.2 公开状态

| 公开 `status` | 来源 | 可执行动词 |
|---|---|---|
| `starting` | `state=starting` 或首个 run 未 bind | `poll/wait/cancel`（清理） |
| `running` | 当前/最后 run `running` | `poll/wait/cancel/steer` |
| `waiting_for_input` | 当前 run `waiting` | `poll/wait/cancel/respond` |
| `completed/failed/cancelled` | 最后 run 对应终态 | `poll/wait/steer`（新 run） |
| `blocked_unknown` | 最后 run `blocked_unknown` | `poll/wait`（steer 拒绝） |
| `idle` | 有 session 无 run | `poll/wait/steer`（新 run） |
| `closed` | 管理面关闭 | 只读 |

#### 4.2.3 活动 run 解析（权威算法）

```text
def current_run(session):
    runs = sorted(session.bindings, key=at, reverse=True)  # 或 S1: runs by created_at desc
    for r in runs:
        view = poll(r.run_id)
        if view.status not in TERMINAL:
            return view
    return poll(runs[0].run_id) if runs else None
```

- 不先信 `active_run_id`；它只用于快速路径，且必须用 view 复核。
- bindings 被截断 200 时，最新的活动 run 一定在保留窗口内（按时间倒序保留）；更早的活动 run 不应存在（“同时至多一个活动 run”不变量）。
- S1 用 `runs WHERE session_id=? ORDER BY created_at DESC` 替代 bindings。

### 4.3 六动词（修订）

| 动词 | v24 内部落点 | 关键修正 |
|---|---|---|
| `start` | 宿主 mint session → 写 start_index/intent → scope/install → `v24.start` → bind → turn | S0 不把 `session_id` 传进 v24（S1 才加参数）；`model/toolset/workspace` 必须匹配；budget 省略 tokens 表示不限 |
| `poll` | `v24.poll` + session store | **S0 不做 event 增量分页**；events 返回最早 64 条；成功后可把 cursor 推至已返回前缀最大 seq |
| `wait` | 短读 + `v24.wait_check` + 条件变量/退避 | `run_started` 是门面比较 run_id；`event` 以 event_seq 为准；revision 仅作 changed 提示 |
| `cancel` | `v24.cancel`，门面填 generation | 终态（含 blocked_unknown）→ `already_terminal`；starting → 清理 |
| `steer` | 活动 → `v24.steer`；终态 → `v24.start` 同 scope；waiting/blocked → 拒绝 | 在 owner 串行域内执行；`steer_active`/`steer_new_run` 首次分派后固定；`pending_steer` 单槽返回 `superseded`；终态新 run `run_no+1` |
| `respond` | `v24.respond`，门面填 generation | blocked_unknown → `already_terminal`；real 固定 `waiting_unsupported`；不加 `user_turn_no` |

#### 4.3.1 `start` 的创建顺序（修订）

1. 在 owner 线程查 `start_index` 与 receipt；命中则按 `phase/outcome` 返回原响应（`replay`）或 `deferred`（首次响应冻结）。
2. 查 `host_request(run_key)`：若已提交而本地 `intent` 未完成，直接补完 bind/counter/turn/receipt。
3. mint `session_id`；写 `pending_intent`（`owner_epoch`、`command_id`、run key、normalized request/digest），同时写 `start_index`。
4. 创建/恢复 scope；安装工具（可重入）。
5. 派生 run key：`s:<session_id>:start:<sha256(client_key)[:32]>`。
6. 调**当前签名**的 `v24.start`（S0 不传 session_id，不改冻结 SQL）；失败保留 `intent`，同 key 可按 `host_request` 结果重试。
7. 成功：bind run；`user_turn_no+1`；`run_no=1`；追加 typed turn；一次原子 replace 写 `receipt.phase=completed`、清 intent、更新 `start_index.phase`；返回快照。
8. 崩溃恢复：`intent` → `host_request(run_key)` 找 `run_id` → 补完本地提交；找不到才重试 `v24.start`。`owner_epoch` 拒绝旧 owner 的迟到写。

#### 4.3.2 `steer` 的分派（修订）

| 状态 | 行为 | 响应 |
|---|---|---|
| `running` | `v24.steer`（同 run） | `started=false`；`queued` 反映 `pending_steer`；`superseded` 反映覆盖 |
| `waiting_for_input` | 拒绝 | `interaction_pending`；零写 |
| `completed/failed/cancelled` | 同 session `v24.start` | `started=true`；新 run；`run_no+1`；`user_turn_no+1` |
| `blocked_unknown` | 拒绝 | `blocked_unknown`；零写 |
| `starting` | 拒绝 | `setup_incomplete` / `session_busy` |
| `idle` | 同 session `v24.start` | `started=true` |
| `closed` | 拒绝 | `session_closed` |

- 终态 `steer` 的 `expected_run_id` 校验旧 run；新 run 的 generation 从 1 开始。
- 同 key 重放：先查 receipt 的 `(principal, session, public_op, key_hash)`；`resolved_variant` 首次分派后固定为 `steer_active` 或 `steer_new_run`，重试不得按当前状态改派；两者都不命中才执行。
- `pending_steer` 单槽：覆盖前读旧 `pending_steer`，返回 `superseded=true`；不要静默丢。
- `v24.steer` 的 `expected_generation` 由门面读当前值；若客户端传了 `expected_generation`，先比较再调用。
- 预检、内核写、driver settle 都在 owner 串行域；waiting 拒绝是零写（只写一条 `rejected` receipt，run/effect/request 不变）。

#### 4.3.3 `respond` 的归一化（修订）

- 当前 run 必须 `waiting`；`interaction_id` 精确匹配；否则 `interaction_mismatch` 零写。
- `blocked_unknown` → `already_terminal` + `details.status="blocked_unknown"`；`completed/failed/cancelled` → `already_terminal`。
- `response` 归一化按 API §5.6；内核要求 object。
- 成功：不加 `user_turn_no`；状态回 `running`；`generation+1`；发 `interaction_responded`。
- real 模式：固定返回 `waiting_unsupported`；不假装可用，不构造 adapter、不开 DB、零 run 写。

### 4.4 Cursor 与 event 合同（修订）

#### 4.4.1 Cursor 字段

```json
{
  "session_id": "uuid",
  "run_id": "uuid",
  "run_revision": 12,
  "event_seq": 34,
  "registration_generation": 1,
  "epoch_no": 2,
  "generation": 3,
  "interaction_id": null,
  "user_turn_no": 3,
  "session_revision": 7
}
```

- `event_seq` 是**当前 run** 的 `v24.events.seq`；换 run 时必须重置为 0（新 run 的 seq 从 1 开始）；禁止 `event_seq=null`。
- `run_revision` 用于 `poll.changed`；`event_seq` 用于 `wait`/增量 events。
- `epoch_no` 对应内核 `runs.epoch_no`；`generation` 对应 `driving_generation`。
- `interaction_id` 是“已上报给客户端的当前交互”，用于避免重复唤醒。
- `user_turn_no` 只用于展示/对账，不驱动 wake。
- `session_revision` 观察纯宿主变化（starting→active/closed、计数/绑定、receipt 阶段）；`generation-only` 变化仍由 `epoch` 处理。

#### 4.4.2 `poll` 的语义（2026-11-05 裁决 D4）

- `changed = (cursor 缺失) or session_id 不匹配 or run_id != cursor.run_id or run_revision != cursor.run_revision or session_revision 变化`；`event_seq` 不是唯一依据。
- `events`：
  - **S0 禁止增量分页**：`include_events=true` 只返回当前 run 的最早 64 条；不按 `cursor.event_seq` 取窗口，也不把 `wait_check` 伪装成 poll 分页。
  - 返回成功后，cursor 的 `event_seq = max(in.event_seq, prefix_max)`；`include_events=false` 时 cursor 不变；换 run 时重置为 0。
  - 若调用方需要“从上次位置继续”，使用 `wait`；`wait` 只推进到实际返回的最后一条。
- `poll` 不写 store、不消费 wake、不增加 revision。
- 若 `poll` 遇到 `registration_stale`，不要让整个只读调用失败：返回新快照、`changed=true`、`event_seq=0` 的重置 cursor（按裁决映射为 `epoch`，不新增第八种 wake）。

#### 4.4.3 `wait` 的 wake 优先级（2026-11-05 裁决 D4）

```text
run_started > terminal > interaction > epoch > event > timeout > none
```

- `run_started`（v24-local）：当前 session 的活动 run_id 与 `cursor.run_id` 不同，**优先检查**；它覆盖“R1 终态 → steer 出 R2 → R2 在下一次 wait 前也终态”的窗口；同 run 的下一次 wait 再报 `terminal`。
- `terminal`：当前 run 终态，且 `run_id == cursor.run_id`；或 session idle/closed。
- `interaction`：当前 run `waiting`，且 `interaction_id != cursor.interaction_id`。
- `epoch`：同 run，`epoch_no` 或 `driving_generation` 变化（`wait_check` 只直接比较 epoch；generation-only 变化也归入 `epoch`）；`registration_stale` 默认映射为 `epoch` + 新快照 + `event_seq=0` 的重置 cursor，不新增第八种 wake。
- `event`：同 run，`event_seq` 前进；`event_seq` 只推进到**实际返回的最后一条**，不越过未返回事件。`include_events=false` 时不会产生 event 唤醒，也不推进 `event_seq`。
- revision-only（`session_revision` / `run_revision` 前进但 `event_seq` 未变）：**默认不唤醒**；正超时到期返回快照并带 `changed=true`，避免忙等。
- `timeout`：到点，`ready=false`。
- `none`：`timeout_ms=0` 且无变化。

**读规则**：

- 无 cursor 的 `wait` 先分页调用 `wait_check` 取当前高水位，再从高水位开始等，等价于“从现在开始”，不是从 0 重放。
- 多会话：请求 `session_ids + cursors`；响应返回一个 winner + `pending_session_ids` + 完整 `cursors` 映射，只更新 winner 的 cursor；按 principal 轮转 winner，避免 sticky terminal 饿死其他 session；`all_terminal` 是布尔标志，不新增 wake reason。
- unknown session：单会话整请求 `not_found_or_denied`；多会话逐项 `ok:false`，不泄露存在性。
- `wait` 不持事务/锁等待；短读 → 释放 → 条件变量/退避 → 短读；`wait` 不占 owner 线程睡眠。

### 4.5 计数（修订）

| 计数 | S0 来源 | S1 来源 | 注意 |
|---|---|---|---|
| `effect_settlement_no` | 当前 run `turn_no` | 同一 | `turn_no` 对 recovery cancel-late 不递增；若要求“首次结算数”严格成立，需统一 late 规则；否则对外叫 `run_turn_no` |
| `model_round_no` | `null` | 只读 ledger | 不要只数 `model_call_settled`；失败/unknown 也是结算。建议数 `model_call_requested` 或 `settled+failed+unknown`，并在文档定义 |
| `tool_round_no` | `null` | 数 `tool_batch_admitted` | 不要数 `tool_batch_completed`：它只在最后一个 live sibling 结算时发（`48_loop.sql:1686-1689` 的 `NOT v_sibling AND NOT v_late`），批内有 late/cancelled 兄弟时可能不发 |
| `user_turn_no` | 持久计数器 | 同一 | start/steer +1；respond 不变；legacy 迁移无法精确 |
| `runs` | 持久计数器 | `count(runs WHERE session_id=... AND parent_run_id IS NULL)` | S0 只计顶层 run；bindings 200 上限 |

`tool_batch_admitted` 是 `48_loop.sql` 在模型结算带工具时发的批次事件（`v24/sql/48_loop.sql:1145`）；`tool_batch_completed` 在最后一个 live sibling 结算时发（`:1689`，条件 `NOT v_sibling AND NOT v_late`），批内有 late/cancelled 兄弟时可能不发。计数用 admitted，避免漏计/延迟。

### 4.6 幂等、恢复与围栏（修订；2026-11-05 裁决 D2）

- 客户端 `request_key` 1..256（API 合同）；内核/`host_request` 1..512。派生 run key 约 78 字符，安全。
- 派生规则：`s:<session_id>:<op>:<sha256(client_key)[:32]>`；`op` 区分 `start / steer_active / steer_new_run / cancel / respond`。
- 幂等作用域：`(principal, session, public_op, key_hash)`；`start` 另用 `start_index` 按 `(principal, key_hash)` 定位已完成命令。
- 同 key 同 payload：返回原响应（`replay`）；同 key 异 payload：`request_conflict`。
- 两相位：`intent` 写入后才调内核；成功后一次原子 replace 写 bind/counter/turn/receipt `completed`；崩溃恢复按 `run_request_key` 查 `host_request`，命中补完、未命中才重试。
- `deferred` 冻结首次响应：同 key 重放同一 deferred，不得第二次变成 committed；永久错误记 `rejected`，暂时错误保持 `intent`。
- `steer_new_run` 的 key 必须与 `steer_active` 分开；`resolved_variant` 首次分派后固定，重试不得按当前状态改派；测试向量 26 已覆盖。
- `respond` 同 key 重放原响应；不同 key 对已消费 interaction → `interaction_mismatch`。
- `cancel` 同 key 重放原响应，即使当前已终态。
- 每 session 保留 256 条 completed receipt；超过后同 key 视为新命令；`start_index` 不淘汰。API 必须写明 replay 窗口。
- 账本含用户请求与历史响应，权限 0600，禁止提交；不把 provider 原文写入账本。

### 4.7 S0 架构（修订）

#### 4.7.1 放置（2026-11-05 裁决 D1，已定稿）

- **采用方案 A：`v24/session/`。** `SessionService` 只依赖 runtime protocol、`SessionStore`、DB；不 import Chainlit 或 `v24.ui`；UI/CLI/MCP 都只是 adapter。
- **S0 交付范围**：Python 进程内 API + Chainlit UI；MCP/HTTP reserved，不实现 MCP server，不做通用 CLI 合同。
- 新增模块：`v24/session/{service,store,driver,wire,types}.py`；M1 由组合根注入现有 `AgentRuntime`，headless gate 注入 fake runtime。
- 不要把“transport-neutral”写成 S0 目标却把服务放回 `v24/ui` 并依赖 hub 线程。

#### 4.7.2 线程与驱动（2026-11-05 裁决 D1+D3）

- 线程：`session-owner`（store/runtime/roster/waiter、控制与 finish）+ `session-exec`（adapter/tool，并发 1）+ 调用方 wait 线程。
- `SessionStore` 由 owner 线程拥有；所有 store I/O 走 owner。
- `wait` 不能在 owner 上同步睡眠；owner 只做毫秒级短读，等待在调用方/waiter 完成。
- `HostWorker.run_once` 拆为 `prepare`（owner：claim + journal）/ `execute`（exec：只调 adapter/tool）/ `finish`（owner：settle + generation/late）；任何锁不得包住 provider 调用。
- roster 在 owner 上轮转所有活动 scope；每轮每 run 最多推进一个短阶段；控制入口不被 provider 阻塞。
- per-run `threading.Lock` 只在某个 settle/recover/reconcile 暂时无法搬回 owner 时使用；锁序固定 `run → DB`，不得反向申请，不得跨 provider 持有。
- `start` 的 `start_index` 查/写与 intent 写在同一 owner 串行域；不要用 advisory lock 掩盖 `sessions.json` 的跨进程丢更新。

#### 4.7.3 能力边界

- `model`/`toolset`/`workspace_root` 必须匹配宿主；不匹配返回 `catalog_changed`/`workspace_mismatch`/`invalid_args`。
- `respond` 在 real 模式固定 `waiting_unsupported`（不构造 adapter、不开 DB、零 run 写）；S0 gate 用 Fake/Scripted。
- `session_transcript` 只返回 `turns.jsonl` 的 user 文本 + run final；没有 assistant/tool 正文；完整 transcript 是 M6/M7。
- 不把 `scope_id`/SQL/provider 原文暴露给客户端。

### 4.8 与 RepoPrompt 的对标（修订）

| 行为 | RepoPrompt 实际 | v24 目标 | 备注 |
|---|---|---|---|
| `start` 新建会话 | 是；拒绝非空 `session_id` | 是 | 一致 |
| `session_id` 稳定 | 是 | 是 | 一致 |
| 五动词 session 寻址 | 是 | 是 | 一致 |
| 终态 `steer` 新 run | 是（epoch transition） | 是（`v24.start` 同 scope） | 机制不同，语义同 |
| waiting `steer` 拒绝 | 是（`.instruction` 例外） | 是（全部拒绝） | v24 更严格；不要声称逐字 parity |
| `respond` 精确 id | 是 | 是 | 一致 |
| `respond` 不加 user turn | 普通交互是；`.instruction` 例外 | 是（v24 策略） | 不是逐字 parity |
| 终态 `cancel` | 拒绝（invalidParams/denial） | `already_terminal` | **v24-local，不是 parity** |
| `wait` 新 run | `epochAdvanced`/`superseded` | `run_started` | **v24-local，不是 parity** |
| `wait` wake 名 | `instructionDelivered`/`steeringRequested` | `terminal/interaction/run_started/epoch/event` | v24 自定；不要假装同名 |
| `start` 默认等待 | 是（detach 默认 false） | S0 默认不等待 | 传输层可组合 `start+wait` |
| 管理面 | `agent_manage`/links | 独立管理面 | 不在六动词 |

### 4.9 API 合同 delta（相对 `v24-session-control-api-2026-11-05.md`）

| API 位置 | 修订 |
|---|---|
| 标题/传输 | 传输改为“Python 进程内 + Chainlit；MCP/HTTP reserved”；删除“MCP 工具 / 可选 HTTP”作为 S0 承诺 |
| §2.4 Cursor | 增加 `session_revision`；`event_seq` 是 per-run 且始终 int；换 run 重置为 0；`user_turn_no` 只展示；`interaction_id` 去重；多会话用 per-session 映射 |
| §2.5 Budget | `tokens` 省略=不限；`steps/wall_ms` ≥1；加最大值；`tokens:null` 非法 |
| §4.1/4.2 | `starting/active/closed` 是宿主 state；公开 status 从 run 派生；`blocked_unknown` 可 cancel 但返回 `already_terminal`；`idle` 定义 |
| §4.3 | `user_turn_no` 持久计数器；start/steer +1；respond 不变；legacy 迁移标注 `legacy_approx` |
| §4.4 | `run_no` 持久；终态 steer +1；同 run steer 不变；重放不变 |
| §4.5 | `counters.runs` 只计顶层 run；`effect_settlement_no` 的 late 例外；`model/tool_round_no` S0 null |
| §5.1 start | `session_id` 由宿主 mint，S0 不传给内核；`model/toolset` 必须匹配；`detach` 默认 true；start 索引/receipt/deferred |
| §5.2 poll | **禁止 event 增量分页**；只返回最早 64 条；成功后 cursor 推至已返回前缀最大 seq；`include_events=false` 不变 |
| §5.3 wait | `run_started` 优先且 v24-local；无 cursor 先取高水位；per-session cursors + winner 轮转；`registration_stale` → `epoch` + `event_seq=0`；revision-only 不唤醒；`all_terminal` 布尔 |
| §5.4 cancel | 内核 generation 必填；服务填充；终态/blocked_unknown → `already_terminal`；starting 清理；同 key 重放冻结 |
| §5.5 steer | owner 串行域；`steer_active`/`steer_new_run` 首次分派固定；waiting 拒绝零 run 写；终态新 run；`superseded` 读旧 pending |
| §5.6 respond | 加 `expected_generation`；blocked_unknown → already_terminal；real 固定 `waiting_unsupported`；不加 user_turn_no |
| §6 错误码 | 标注 `already_terminal`/`run_started`/`interaction_pending`/`not_waiting`/`session_busy` 为 v24-local；`blocked_unknown` 映射；`waiting_unsupported` 单列 |
| §7 幂等 | RFC 8785 canonical digest；完整 key 哈希；两相位 intent/completed + owner_epoch；256 completed receipt；deferred 冻结 |
| §8 映射 | `v24.start` 增加 session_id 标 S1-only；`run_projection` 不加 session_id；S1 用独立读函数 |
| §9 对照 | 不要把 v24-local 码写进 RepoPrompt 列 |
| §10 传输 | 改名为“预留传输绑定”，明确不在 S0 实现 |
| §12 测试向量 | 加 poll 禁分页/前缀推进、waiting race、R2 已终态 run_started、receipt 跨重启、legacy counter、spawn 子 run、S1 migration |

### 4.10 S1 设计（修订）

#### 4.10.1 Schema

- `runs.session_id uuid NULL`；只有宿主创建的顶层 run 写；spawn 子 run 保持 NULL。
- `UNIQUE (session_id) WHERE session_id IS NOT NULL AND ended_at IS NULL`；不要 `SET NOT NULL`。
- `session_id` 不可变：所有 update 白名单不包含它；不要用列级 trigger 增加复杂度（解释器白名单足够）。
- `run_projection` 保持 23 key；不把 `session_id` 塞进去。
- 新增独立读函数（名称示意）：`host_session_snapshot(session_id)`、`host_session_runs(session_id, cursor, limit)`、`poll_session`、`wait_session_check`；这些都要过 `50_permissions.sql` allowlist 与 `test_g1.py` 闭集。
- `host_session_runs` 返回 `parent_run_id`/`session_id`（或明确只返回 `session_id IS NOT NULL` 的顶层 run），避免 S0 的盲区。
- `v24.start` 增加 `p_session_id`；宿主总是传非空；kernel 对 NULL 只允许内部 spawn（不写 session）。
- 迁移后校验：每个 session 至多一个 `ended_at IS NULL` 的 run；同一 run 不被两个 session 引用。

#### 4.10.2 迁移

见 D9。执行器必须是一个独立脚本（例如 `v24/migrations/0002_session_anchor.py`），在 `init_env` 之前运行；或者显式重置 scratch DB。没有现成 `ui/migrations.py` 可用于 DB。

#### 4.10.3 Gate 成本

- 必须更新 `v24/cordis/dp4/test_closeout.py:35-48`、`dp5/test_boundaries.py:591-593`、`dp6/test_boundaries.py:859-861` 的 `FROZEN`。
- 必须更新 dp5/dp6 的 D-UI-6 审计（“恰好 6 个 M 路径”与 `D_UI_6_SUBSTITUTIONS`），把 `v24/sql/10_schema.sql`、`v24/sql/47_verbs.sql`、`v24/sql/49_host_reads.sql`、`v24/sql/50_permissions.sql` 等纳入批准路径。
- `v24/load.py` 不能改；`v24/ui/test_ui_gate.py:1700` 的 12 文件断言不能破；不要新增第 13 个 SQL 文件。
- `v24/s1/test_ddl.py` 的现有闭集不检查 `runs` 的 partial index；如果新增断言，会触发 D-UI-6，需预算。
- `v24/s3/test_g2.py`/`v24/s4/test_g2b.py` 的 `PROJECTION_KEYS` 不变，前提是 `run_projection` 不变。
- `v24/s1/test_g1.py` 在 byte-lock 内；新增读函数必须改它，并更新 dp5/dp6 的替换表。
- `v24/s14/test_g12.py` 不存在；计划中的这条 gate 要删掉或新建（新建不受 byte-lock，因为 s14 不在 `range(1,13)`）。
- `v24/ui/d_ui_6_acl.py:70` 的 `50_permissions.sql` digest 要更新。

#### 4.10.4 判定

S1 不是 S0 的自然下一步；它需要一次 **frozen-baseline bump**。在批准前，S0 不应依赖任何 S1 字段；S0 的 API 合同必须能在“只有 runs、没有 session_id”的情况下工作。

如果完全不能改冻结 SQL，唯一替代是 `run_sessions(run_id, session_id)` 侧表 + 迁移脚本；但它无法在 `v24.start` 内原子写 `session_id`，崩溃窗口需要额外的恢复协议，而且仍要新增读函数/文件并过 gate。它不改变“S1 需要治理批准”的结论，只是换一种代价；本设计不推荐。

### 4.11 迁移与回滚（修订）

- `sessions.json` v1 → v2：
  1. 读 v1；校验 UUID/token/bindings。
  2. 为每个 conversation 分配 `session_id`（可等于 `conversation_id`）。
  3. 迁移 `turns.jsonl` 的 `conversation_id` → `session_id`；保留 `seq` 仅作历史排序，不进入 `user_turn_no`。
  4. 计算 `run_no = len(bindings)`、`user_turn_no = len(turns for conversation)`；标注 legacy 误差。每个 binding 的 `realm/workspace_root/toolset/catalog_digest/mode/limits_digest` 原样保留，供历史展示/seed 判断 `catalog_changed`。
  5. 写 v2；`.v1.bak`（0600）；每次原子替换保留 `.prev`；`counter_origin=legacy_approx`。
  6. 失败 quarantine 新产物，不覆盖原文件，不自动建空 store。
- 回滚（`v24/session/rollback.py`）：停准入/关 service → 归档 v2 sessions/turns/transcript/journal（0700/0600）→ 恢复 `.v1.bak` → 校验 v1 可加载 → 不覆盖归档、不做自动双向合并。不要指望 v1 代码读 v2（`v24/ui/sessions.py:77` 会 quarantine）。
- 损坏：JSON/版本/必要结构损坏 → 整体 fail-closed，保留原件并给诊断；单 session 多活动 run → 冻结该 session 控制并报不变量错误；不得声称“单会话损坏不影响其他会话”。
- 特性开关 `V24_SESSION_API` 只控制入口；v2 格式本身不随开关变化；新二进制关开关仍读 v2。
- S1 回滚：保留 `session_id` 列但停用读写，或按迁移脚本反向删除；不要删除 session 元数据；frozen gate 也要回滚到批准基线。

## 5. 实施约束与 gate

### 5.1 S0 必做 / 不做

**必做**：

- `SessionStore` v2 + 迁移 + `.v1.bak`/`.prev`；持久 `run_no`/`user_turn_no`/`session_revision`；`counter_origin`；`start_index` + 两相位 receipt + `owner_epoch`（不用时间 lease）。
- `v24/session/` transport-neutral `SessionService` + 六动词 + cursor + replay；不 import Chainlit。
- 单 owner 线程 + 单执行线程（并发 1）；`prepare/execute/finish` 拆分；`wait` 不阻塞 owner；per-run 锁只用于无法搬回 owner 的 settle。
- 终态 `steer` 同 scope 新 run；waiting/blocked 拒绝；`respond` 精确 interaction；`steer_active`/`steer_new_run` 首次分派固定。
- 错误映射：`already_terminal`、`interaction_pending`、`not_waiting`、`blocked_unknown`、`stale_generation`、`registration_stale`、`waiting_unsupported`。
- 旧 `/resume <run_id>` 仍可用；`session_id` 别名兼容。

**不做**：

- 不改 `v24/sql/**`、`v24/load.py`、`v24/host/deepseek.py`。
- 不做 per-session model/toolset 切换。
- 不声称 real respond 可用。
- 不做 S1 的 `runs.session_id`/部分唯一索引。
- 不做 MCP server、MCP/HTTP 传输（reserved；实现即范围变更）。

### 5.2 S1 的前置决策

1. Frozen-baseline bump：三套 hash + D-UI-6 六路径 + `load.py`/test 闭集。
2. `session_id` 可空 + spawn 子 run 规则。
3. 迁移数据源：`sessions.json` bindings，不是 scope。
4. 迁移执行器：pre-`init_env` 脚本或 DB reset。
5. 新读函数的 DEFINER allowlist + `test_g1.py` 更新。
6. `run_projection` 不加 `session_id`。
7. `s14/test_g12.py` 删除或新建。
8. 批准后单独提交；不要与 S0 混在一起。

### 5.3 Gate 清单（修订）

S0 固定回归 inventory（每个里程碑按范围跑，M4 收口全跑）：

```bash
uv run python v24/session/test_session_verbs.py          # 新增
uv run python v24/ui/test_ui_gate.py
uv run python v24/ui/test_backend_regressions.py
uv run python v24/ui/test_artifact_regressions.py   # M4
uv run python v24/ui/test_audit_m5.py               # M4
uv run python v24/s4/test_g2b.py                    # M3 loop/steer/respond
uv run python v24/s5/test_g4.py                     # 固定补入
uv run python v24/s7/test_g6.py                     # M2/M3 并发
uv run python v24/s10/test_g9.py                    # 固定补入
uv run python v24/s11/test_g10.py                   # 固定补入
uv run python v24/s12/test_g11.py                   # 固定补入
uv run python v24/cordis/dp4/test_closeout.py       # S0 收口
uv run python v24/cordis/dp5/test_boundaries.py     # S0 收口
uv run python v24/cordis/dp6/test_boundaries.py     # S0 收口
```

S0 收口 diff（必须为空）：

```bash
git diff -- v24/sql v24/load.py v24/host/deepseek.py
uv run python v24/load.py
uv run python v24/s1/setup_db.py --self-check
```

S1（批准后，另加）：

```bash
uv run python v24/cordis/dp4/test_closeout.py
uv run python v24/cordis/dp5/test_boundaries.py
uv run python v24/cordis/dp6/test_boundaries.py
uv run python v24/s1/test_ddl.py
uv run python v24/s1/test_g1.py
uv run python v24/s3/test_g2.py
uv run python v24/s4/test_g2b.py
uv run python v24/s6/test_g5.py
uv run python v24/s7/test_g6.py
uv run python v24/s8/test_g7.py
uv run python v24/s9/test_g8.py
```

> 计划的 `v24/s14/test_g12.py` 不存在；不要把它写成必跑 gate，除非先创建。

## 6. 已定与仍需治理的事项

以下事项已由 2026-11-05 五项裁决定稿，不再是二选一：

| # | 事项 | 定稿 |
|---|---|---|
| 1 | S0 服务放置 | `v24/session/`；S0 交付 Python 进程内 API + Chainlit UI；MCP/HTTP reserved |
| 2 | waiting `steer` 竞态 | owner 线程串行域 + `prepare/execute/finish`；per-run 锁仅作局部兜底，锁序 `run → DB` |
| 3 | `already_terminal` / `run_started` | 保留为 v24-local，不称 parity |
| 4 | `user_turn_no` 旧数据 | `len(turns)` 近似 + `legacy_approx` 标记 |
| 5 | `run_no` 旧数据 | `len(bindings)` 近似 + `legacy_approx` 标记 |
| 6 | `respond` real 模式 | 固定 `waiting_unsupported`；fake/scripted 才是 S0 gate |
| 7 | S1 `session_id` nullable | 保持 nullable；spawn 子 run NULL |
| 8 | S1 迁移 | 按 `sessions.json` 的 conversation/bindings，不按 scope |
| 9 | S1 frozen-baseline | 独立批准；S0 观察期后再评审实际 diff |
| 10 | `model`/`toolset` | S0 必须匹配宿主；P1 再做动态 |
| 11 | poll event 分页 | S0 禁止；`event_seq` 只推进到已返回前缀/最后返回事件 |
| 12 | 多会话 wait | per-session cursor 映射 + winner 轮转；`all_terminal` 布尔 |
| 13 | v2 回滚 | `.v1.bak` + `.prev` + 回滚前归档；整体 fail-closed |

仍需治理（不阻塞 S0）：

- S1 的 frozen-baseline bump：三套 hash + D-UI-6 路径 + `load.py`/test 闭集，独立批准后另提交。
- `s14/test_g12.py` 尚不存在；S1 批准件决定新建或并入既有 gate。
- cancel-late 统一计数规则、model/tool ledger 最终算法可延后；S0 只保留 late 例外或改名，不声称四计数已完整。

## 附录 A：核查台账

| # | 断言 | 判定 | 证据 |
|---|---|---|---|
| A1 | v24 只有 runs，没有 session/turns 表 | 成立 | `v24/sql/10_schema.sql:25-61`；`v24/s1/setup_db.py:534` |
| A2 | `turn_no` 是 effect settlement，不是模型回合 | 成立 | `v24/sql/48_loop.sql:588`、`:1411`、`:1988` |
| A3 | `poll` 无 event cursor | 成立 | `v24/sql/47_verbs.sql:50-70` |
| A4 | `wait_check` 支持 after_event_seq | 成立 | `v24/sql/47_verbs.sql:120-129` |
| A5 | `steer` 在 waiting 上清 interaction | 成立 | `v24/sql/40_interpreters.sql:2580-2588` |
| A6 | `steer` 终态返回 already_terminal | 成立 | `v24/sql/40_interpreters.sql:2526-2532` |
| A7 | `respond` 对 blocked_unknown 返回 blocked_unknown | 成立 | `v24/sql/40_interpreters.sql:2671-2683` |
| A8 | `start` 无同 scope 活动 run 检查 | 成立 | `v24/sql/40_interpreters.sql:2812-2832` |
| A9 | budget tokens null 非法 | 成立 | `v24/sql/40_interpreters.sql:2790-2815` |
| A10 | 内核 request_key 1..512 | 成立 | `v24/sql/47_verbs.sql:73-92`、`:147-169`、`:172-195`、`:198-224` |
| A11 | SessionStore v1 strict quarantine | 成立 | `v24/ui/sessions.py:14`、`:77` |
| A12 | bindings/turns 截断 200 | 成立 | `v24/ui/sessions.py:175-200` |
| A13 | `app.seq` 全局且与 key 共用 | 成立 | `v24/ui/app.py:131`、`:216-219`、`:333-335` |
| A14 | UI respond 会写 turn | 成立 | `v24/ui/app.py:458-466` |
| A15 | real 模式 respond unsupported | 成立 | `v24/ui/app.py:446-449` |
| A16 | start/spawn seed 只接受 system/user | 成立 | `v24/host/deepseek.py:261-293` |
| A17 | 12 文件哈希被 dp4/dp5/dp6 锁定 | 成立 | `dp4/test_closeout.py:35-48`；`dp5/test_boundaries.py:591-593`；`dp6/test_boundaries.py:859-861` |
| A18 | D-UI-6 锁 6 个 M 路径 | 成立 | dp5/dp6 审计；`v24/load.py`/`v24/s1..s12` byte-lock |
| A19 | `len(SQL_LOAD_ORDER)==12` | 成立 | `v24/ui/test_ui_gate.py:1700` |
| A20 | `init_env` schema_drift | 成立 | `v24/ui/env.py:184-189` |
| A21 | `ui/migrations.py` 空 | 成立 | `v24/ui/migrations.py:13-22` |
| A22 | `s14/test_g12.py` 不存在 | 成立 | tree |
| A23 | RepoPrompt `already_terminal` 不存在 | 成立 | RepoPrompt `Sources/` 0 次 |
| A24 | RepoPrompt `run_started` 不是 wake reason | 成立 | `Sources/RepoPromptDomainRuntime/DomainAgentRunSessionStore.swift:160-163`；用法 `AgentModeViewModel.swift:8495`、`:8559`；`AgentRunMCPToolService.swift:2057` |
| A25 | RepoPrompt 终态 cancel 抛 invalidParams/denial | 成立 | `AgentRunMCPToolService.swift:1371-1372`、`:1349` |
| A26 | RepoPrompt terminal steer 新 run | 成立 | `AgentRunMCPToolService.swift:1567`、`:1583-1590` |
| A27 | RepoPrompt waiting steer 拒绝（instruction 例外） | 成立 | `AgentModeViewModel.swift:13348-13353` |
| A28 | RepoPrompt respond 精确 id | 成立 | `AgentModeViewModel.swift:13535-13541` |
| A29 | RepoPrompt respond `.instruction` 写 user turn | 成立 | `AgentModeViewModel.swift:13544-13568` |
| A30 | RepoPrompt start 默认 wait | 成立 | `AgentRunMCPToolService.swift:501` |

## 附录 B：对三份草案的具体修改（历史记录）

> 本附录记录 Stage 2 的修正建议，仅作追溯。凡与 [五项链裁决记录](../reviews/v24-session-control-decision-record-2026-11-05.md) 冲突的条目，以裁决为准：lease → `owner_epoch`，共享 per-run 锁 → owner 线程串行域，MCP/HTTP → reserved，poll 分页 → 禁止。

### B.1 `v24-session-control-plane-2026-11-05.md`

| 位置 | 修改 |
|---|---|
| §0 TL;DR 第 2、3 条 | 保留方向；把“RepoPrompt 的六动词”改为“RepoPrompt 的 session 寻址 + v24-local 语义改写” |
| §1.2 第 4、6 条 | 删除 `already_terminal` 的 RepoPrompt 归属；给 respond 加 `.instruction` 例外 |
| §1.2 第 3 条 | 把 `run_started` 标注为 v24-local；RepoPrompt 用 epochAdvanced/superseded |
| §4.2 S1 | `session_id` 保持 nullable；子 run NULL；不要 `SET NOT NULL` |
| §4.2/§5.3 | `user_turn_no`/`run_no` 改为持久计数器；`seq` 只作历史排序 |
| §5.2 状态派生 | active run 从 bindings 重算；不要先信 `active_run_id` |
| §6.1 `poll` | events 走 `wait_check` 或 v1 不分页；`poll` 没有 event cursor |
| §7.1/§7.3 | 统一 start 顺序：先查/写 pending_start，再 mint session_id；加 lease |
| §7.5 | 加 per-run 锁；说明 waiting steer 的非原子风险 |
| §7.9/§9.3 | 回滚恢复 `.v1.bak`；v1 会 quarantine v2 |
| §8 对标矩阵 | 把 v24-local 码从 RepoPrompt 列移出；加 `.instruction` 例外 |
| §10 验收 | 加 event 分页、waiting race、legacy counter、spawn 子 run 的用例 |

### B.2 `v24-session-control-api-2026-11-05.md`

| 位置 | 修改 |
|---|---|
| §2.4 | `event_seq` per-run；换 run 重置；`user_turn_no` 展示用 |
| §2.5 | tokens 省略=不限；steps/wall ≥1；加最大值 |
| §4.3/§4.4 | 持久计数器；legacy 迁移说明 |
| §5.1 | session_id 宿主 mint；model/toolset 必须匹配；错误表加 `retry_with_closure/unauthorized` |
| §5.2 | events 不是 poll 的增量；新客户端最早 64 条 |
| §5.3 | `run_started` v24-local；revision-only 变化由短读兜底 |
| §5.4 | generation 内核必填；blocked_unknown → already_terminal |
| §5.5 | waiting 竞态；expected_generation 门面填充；superseded |
| §5.6 | 加 expected_generation；blocked_unknown → already_terminal；real unsupported |
| §6 | 标注 v24-local 错误码；`blocked_unknown` 映射 |
| §8 | `v24.start` 加 session_id；`run_projection` 不加 |
| §9 | 不把 v24-local 码写成 RepoPrompt 字段 |
| §12 | 加 event 分页、race、legacy、spawn、S1 用例 |

### B.3 `v24-session-control-plan-2026-11-05.md`

| 位置 | 修改 |
|---|---|
| §0.1 S0 DoD | 加“event 分页能力受 poll 限制”“waiting steer 共享锁”“real respond unsupported” |
| §0.2 S1 DoD | 改为“需 frozen-baseline bump”；不要写成普通规格修订 |
| §2 实施策略 | S1-M5 前加“frozen baseline 批准 + migration executor” |
| §3 S0-M1 | start 顺序改为 pending_start → mint session → v24.start；加 lease |
| §3 S0-M2 | wait 的 event 以 event_seq 为准；加 per-run 锁 |
| §3 S0-M3 | waiting steer 共享锁；terminal steer 同 scope 新 run；respond 不加 user_turn_no（v24 策略） |
| §3 S0-M4 | 回滚恢复 `.v1.bak`；legacy counter 说明 |
| §6 gate 清单 | 删除 `v24/s14/test_g12.py` 或先创建；S1 加 dp4/dp5/dp6 |
| §7.1 迁移 | 按 conversation/bindings，不按 scope；子 run 不回填 |
| §7.2 回滚 | 恢复 `.v1.bak`；v1 不能读 v2 |

## 附录 C：术语

- **Session**：用户可见的会话容器；稳定 `session_id`；跨 run；S0 由宿主文件承载，S1 由 `runs.session_id` 锚定。
- **Run**：一次可恢复执行；现有 `runs` 行；唯一执行主体。
- **User turn**：用户请求边界；`start`/`steer` 产生；`respond` 不产生；v24 策略，非 RepoPrompt 逐字 parity。
- **Effect settlement**：model/tool effect 的首次提交结算；`runs.turn_no`；late-settlement 例外见 §4.5。
- **Model round**：以一次模型响应为中心的轮次；S1 ledger；不要只数 successful settlement。
- **Tool round**：已准入的工具批次；数 `tool_batch_admitted`。
- **Cursor**：客户端持有的读位置；不是服务端消费标记。
- **Facade**：会话级六动词对 run 级六动词的解析与语义改写层。
- **v24-local**：v24 门面自定的码/语义，不是 RepoPrompt 的当前行为。
