# v24 六动词 Agent 会话控制面设计（Session Control Plane）

> **核验状态（2026-11-05）**：本文件的事实断言已逐条核验，修订版见
> [`v24-session-control-design-verified-2026-11-05.md`](v24-session-control-design-verified-2026-11-05.md)。
> `already_terminal` / `run_started` 是 v24-local 语义，不是 RepoPrompt 的当前码；
> `poll` 的 event cursor、`user_turn_no`、S1 迁移与回滚等断言已在核验版中修正。冲突处以核验版为准。

| 项 | 值 |
|---|---|
| 日期 | 2026-11-05 |
| 状态 | Proposed；设计已成形，尚未实施 |
| 范围 | v24 host/UI 会话层；对冻结内核 `v24/sql/**` 只提出接口要求 |
| 依据 | `docs/investigations/v24-pi-repoprompt-session-turn-run-mapping-2026-11-05.md`；`docs/designs/v24-pg-agent-2026-10-22.md`；`docs/plans/v24-ui-usable-agent-m6-m10-2026-11-04.md`；RepoPrompt `agent_run` 工具合同 |
| 关联文档 | API 合同：`docs/designs/v24-session-control-api-2026-11-05.md`；落地计划：`docs/plans/v24-session-control-plan-2026-11-05.md` |

## 0. 结论（TL;DR）

1. **v24 今天有六个动词，但除 `start` 外都是 run 级的。** `poll/wait/cancel/steer/respond` 以 `run_id` 寻址，`start` 创建 run（`v24/sql/47_verbs.sql:35`、`:73`、`:96`、`:147`、`:172`、`:198`）；UI 的 `conversation` 只是宿主文件里的绑定列表（`v24/ui/sessions.py:132`、`:147`）。
2. **RepoPrompt 的六个动词是 session 级的。** `start` 总是新建 session 并拒绝 `session_id`；其余五个动词以稳定的 `session_id` 寻址；`steer` 在活动 run 上投递，在终态会话上则在**同一会话内开下一个 run**；`respond` 只消费精确的 `interaction_id`。
3. **差距不在执行内核，而在会话门面。** v24 的 run/effect/advance 已经提供预算、控制世代、幂等、迟到结果围栏和恢复；缺的是：稳定会话身份、session → 当前 run 的解析、终态 `steer` 开新 run、会话级 cursor/快照。
4. **推荐三条路线，按风险递增：**
   - **S0 Host façade（现在可做）**：session 元数据留在宿主 `sessions.json` v2，session 与当前 `scope` 一对一，六动词由宿主 `SessionService` 实现；不改冻结 SQL。
   - **S1 Kernel anchor（目标形态）**：在 `runs` 上增加不可变 `session_id` 和“每 session 至多一个未终态 run”的部分唯一索引；六动词仍由宿主实现，但归属与串行性由 DB 兜底。
   - **S2 Session aggregate（以后再说）**：增加 `v24.sessions` 目录表，支持多主机/多用户/会话列表与权限；不把会话状态做成第二状态机。
5. **API 合同在三条路线之间保持不变。** 客户端只认 `session_id` 和六个 `op`；S0 → S1 是存储迁移，不是协议迁移。
6. **不建 `turns` 表，不建 `run_attempts` 表，不把 provider 原文搬进 DB。** 会话是分组与控制门面；run 仍是唯一执行主体；turn 仍是四种派生计数（见 §5.3）。
7. **需要先拍板四件事**：会话锚走 S0→S1 还是直接 S1；`steer` 单槽 latest-wins 还是宿主队列；session 元数据放宿主还是 DB；`cancel-late` 计数规则是否随本设计一起修订（见 §12）。

### 0.1 语义合同（五条，先拍板）

1. **会话是分组，不是执行**：只回答“哪些 run 属于同一会话”“当前哪个 run 是活动的”“用户看到了什么”；预算、状态机、终态、effect 都只在 run/effect。
2. **run 是唯一执行主体**：会话状态必须从 run 派生，不能存一份可写的 `session.status` 与 run 争权威。
3. **turn 是四个派生量，不是一个对象**：`effect_settlement_no` / `model_round_no` / `tool_round_no` / `user_turn_no`，对外必须带限定名。
4. **parent 边不等于投递**：`parent_run_id` 只表达 spawn 谱系；结果回灌必须走显式 tool outcome 或显式 steer，并带由 child run_id 派生的幂等键。
5. **provider 原文不进 DB**：journal 是原文权威，DB 只存语义投影与提交顺序；compaction 的“少显示”与“换上下文”分开描述。

## 1. 问题与证据

### 1.1 v24 当前事实

| 事实 | 证据 | 对会话设计的影响 |
|---|---|---|
| 冻结内核只有 `runs`，没有 session/turn 表 | `v24/sql/10_schema.sql:25`、`:67`；`v24/s1/setup_db.py:534`；`docs/designs/v24-pg-agent-2026-10-22.md:203` | session 不能靠新表“顺便”获得；要么宿主承担，要么显式修订规格 |
| 除 `start` 外，五动词以 run 寻址 | `v24/sql/47_verbs.sql:35`、`:73`、`:96`、`:147`、`:172`、`:198` | 需要 session → 当前 run 的解析层 |
| `start` 只接收 `scope_id/owner_fiber_id/input/budget/request_key` | `v24/sql/47_verbs.sql:198` | 会话身份不在 start 合同内；S0 由宿主先分配再绑定 |
| `run_projection` 不含会话字段 | `v24/sql/47_verbs.sql:14` | 会话快照必须由宿主组合，或 S1 新增读函数 |
| UI conversation 是宿主文件，`conversation:run = 1:N` | `v24/ui/sessions.py:132`、`:147`；调查 A4 | 已有“会话”产品概念，但没有稳定控制面 |
| UI 每个 conversation 一个 scope | `v24/ui/app.py:302`、`:306` | S0 可用 `session_id → scope_id` 一对一映射，但这只是存储捷径，不是语义等价 |
| UI 只在应用层保证“一个会话一个活动 run” | `v24/ui/app.py:383`、`:388` | DB 没有约束；S0 需宿主锁，S1 需部分唯一索引 |
| 终态 `steer` 在 run 级返回 `already_terminal` | `v24/sql/40_interpreters.sql:815` 起的 steer 分支；`docs/designs/v24-pg-agent-2026-10-22.md:253` | 会话级 `steer` 必须在门面层把它改写成“同会话新 run” |
| `pending_steer` 是单槽 | `v24/sql/10_schema.sql:43`；`v24/sql/48_loop.sql:826` | 会话级多次 steer 要么 latest-wins，要么宿主排队；不能假装内核有 inbox |
| 读面已有 host 分页/单 run 读 | `v24/sql/49_host_reads.sql:76`、`:209`、`:550` | S0 可直接复用 `host_runs`、`host_run_effects`、`host_request` |
| 幂等键是 `(principal_id, request_key)`，同键异参数返回 `request_conflict` | `v24/sql/30_advance.sql:247`、`:254`、`:258` | 会话级写动词必须复用这套账本，而不是另造一套 |
| provider 原文只在 host journal | `docs/designs/v24-pg-agent-2026-10-22.md:56`；`v24/host/worker.py:1194` 起 | 会话 transcript 是宿主事实，不是 DB 表 |

### 1.2 RepoPrompt 的六动词语义（对照基准）

以下行为来自 `agent_run` 工具合同与其运行实现，作为本设计的“像 RepoPrompt”判据：

1. `start` 总是新建 session/tab，显式传 `session_id` 会被拒绝；继续已有会话要用 `steer`。
2. `poll` 以 `session_id` 或 `session_ids` 读取当前快照；纯读。
3. `wait` 以 `session_id` 等待“有意义的”状态：终态、等待输入、事件、控制世代变化；超时不是错误；等待游标由调用方携带。
4. `cancel` 只对活动 run 有效；终态返回 `already_terminal`，不删除会话。
5. `steer` 对活动 run 投递指令；对已终态会话，**在同一 session 内启动下一个 run**；对等待输入的会话，应改用 `respond`。
6. `respond` 用 `session_id + interaction_id` 精确消费当前交互；不产生新的用户 turn。
7. `session_id` 跨多个 run 稳定；run 是内部执行身份，客户端不需要持有 `run_id`。

### 1.3 真正缺的是什么

不是第七个动词，也不是一张 `sessions` 表，而是四件事：

- **稳定会话身份**：一个客户端可以长期持有、跨 run、跨重启的 `session_id`。
- **会话到当前 run 的解析**：每次控制都要回答“这个会话现在有没有活动 run；如果没有，最后一个 run 是什么状态”。
- **会话级语义改写**：`steer` 在终态开新 run、在 waiting 拒绝、在 `blocked_unknown` 拒绝；`cancel` 只取消活动 run；`respond` 只答当前交互。
- **会话级读模型**：快照、cursor、wake reason，把 run 投影组合成客户端可轮询/等待的对象。

这四件事都可以在不改 run/effect 权威的前提下实现。

## 2. 目标与非目标

### 2.1 目标

1. 对外只暴露一个稳定 `session_id`；除 `start` 创建它以外，其余五个动词都以它寻址，终态 `steer` 的续接也用它。
2. 行为与 RepoPrompt 的六动词在以下点上一致：
   - `start` 拒绝 `session_id`；
   - `poll/wait` 纯读、cursor 由客户端持有；
   - `cancel` 只作用于活动 run；
   - `steer` 在终态会话上开新 run；
   - `respond` 精确匹配 `interaction_id`；
   - `session_id` 跨 run 稳定。
3. 会话层可崩溃恢复：重启后能重新解析当前 run、等待中的交互、终态结果；不重开终态 run。
4. 同一会话至多一个活动 run；不同会话可以独立控制（执行并发是另一个维度）。
5. 保留 v24 的既有不变量：单一 `advance`、effect 结算权威、request journal 幂等、unknown wall、provider 原文不进 DB。
6. S0 不改冻结 SQL；S1 的 schema 变更必须作为显式规格修订，不得偷偷塞进现有文件。

### 2.2 非目标

- 不做 RepoPrompt 的完整产品面：worktree 管理、模型目录、任务标签、handoff、pin、cleanup、多租户。
- 不做会话树/fork/clone（先保留 `parent_session_id` 字段，不实现）。
- 不建 `turns` 表、`run_attempts` 表、`session_status` 表。
- 不把 provider 的 assistant/tool 原文写入 DB；会话 transcript 仍归宿主。
- 不改变 run 级六动词的现有语义；会话级是门面，不是替换。
- 不在本设计里解决多执行器/多用户并发；只定义控制面合同和 S0 的单进程边界。
- 不把 `scope` 正式改名为 `session`；S0 的 `session → scope` 只是实现映射。

## 3. 设计原则

1. **会话是分组，不是执行。** 会话只回答“哪些 run 属于同一会话”“当前哪个 run 是活动的”“用户看到了什么”；预算、状态机、终态、effect 都只在 run/effect。
2. **run 仍是唯一执行主体。** 会话状态必须从 run 派生，不能存一份可写的 `session.status` 与 run 争权威。
3. **六个动词是控制面，不是执行面。** `poll/wait` 是纯读；四个写动词必须落到既有 `advance`/request journal 或在其外层做可重放的会话命令。
4. **四种 turn 必须分开命名。** `effect_settlement_no`、`model_round_no`、`tool_round_no`、`user_turn_no` 不能互相冒充；对外文档禁止裸用 `turn`。
5. **一个会话一个活动 run。** 这是控制面的串行性，不是执行器的全局串行性；不同会话可以并行。
6. **幂等先于 CAS，CAS 先于业务。** 同 `(principal, request_key)` 先回放；不同 payload 冲突；然后才检查 `expected_run_id/expected_generation`；最后才改状态。
7. **等待不持事务/会话锁。** `wait` 只能“短读 → 提交/释放锁 → 睡眠/监听 → 短读”，不能在 provider 调用或长睡眠期间持连接事务或 session 锁。
8. **失败关闭。** 未授权、未知会话、未知 run 统一 `not_found_or_denied`；`blocked_unknown` 不自动续跑；`waiting` 不被 `steer` 静默清掉。
9. **冻结内核优先。** S0 不碰 `v24/sql/**`；S1 的每一处 schema/函数改动都要有规格修订、迁移和 gate。
10. **API 稳定，存储可换。** 三条路线共用同一份六动词合同；客户端不因 S0→S1 改变。

## 4. 三条合理路线

### 4.1 路线 S0：Host façade（宿主门面）

```text
MCP / UI / CLI
      │  start|poll|wait|cancel|steer|respond  (session_id)
      ▼
SessionService (v24/ui/session_service.py)
      ├─ SessionStore v2   sessions.json + turns/transcript
      ├─ RunControl        v24.start / poll / wait_check / cancel / steer / respond
      ├─ HostDB            host_runs / host_run_effects / host_request
      └─ HostWorker        run_once / journal / recovery
      ▼
冻结 v24 SQL（不改）
```

**形状**

- `session_id` 由宿主生成；`SessionStore` 记录 `session_id`、`principal_id`、`scope_id`、`realm`、`workspace_root`、`toolset`、`model`、`name`、`created_at`、`updated_at`、`bindings[]`、`active_run_id`（派生缓存）、`counters`。
- 当前实现里一个 conversation 恰好一个 scope（`v24/ui/app.py:302`、`:306`），所以 S0 用 `session_id → scope_id` 一对一。**这是存储映射，不是语义等价**；门面之外的代码不得把 `scope_id` 当 `session_id` 使用。
- 六个动词在 `SessionService` 中实现；内部仍调用 run 级 RPC。S0 先放 `v24/ui/session_service.py` 以贴近现有 Chainlit 生命周期；S1 可提升为 `v24/host/session_service.py`，公开合同不变。
- 会话快照 = `SessionStore` 元数据 + `v24.poll(run_id)` + `host_run_effects` 的 cursor/计数。
- `wait` 在宿主内用短读 + 条件变量/退避；跨进程时退化为短轮询，P1 再接 `LISTEN/NOTIFY`。
- 幂等复用 `v24.requests`：会话级 key 派生为稳定的 run 级 key；重放先用 `v24.host_request` 读原响应（`v24/sql/49_host_reads.sql:550`），再决定是否调用。
- “一个会话一个活动 run”由 `SessionService` 的 per-session 锁 + 每次写前重读保证。**S0 只支持单宿主进程**：用 `threading.Lock` + `atomic_json`；不要用“多个进程共享 `sessions.json` + advisory lock”冒充安全，advisory lock 防不了 JSON 丢更新。要多进程，先把 session 元数据迁到 DB（S2）。
- **线程纪律**：`SessionStore` 的 I/O 仍固定在 hub thread（`v24/ui/sessions.py` 的 `_check` 会拒绝跨线程）；worker/provider 线程只能通过队列/回调唤醒 `wait`，不能直接写 session 文件。`SessionService` 的公开方法必须在 hub thread 调用，或显式投递到 hub。`wait` 本身不能在 hub thread 同步睡眠，否则会卡住所有会话；用 async/后台线程等待，服务只提供短读 + 条件变量。

**优点**

- 零 SQL/schema 变更，不触碰冻结哈希和现有 gate。
- 可以最快交付，先验证六动词语义和 UI 迁移。
- 失败可回滚：删掉新服务、保留 `sessions.json` v1 读取即可。
- 与 M6–M10 的 `SessionStore v2`/`TranscriptStore` 方向一致。

**缺点**

- DB 不能回答“哪些 run 属于同一会话”；只能通过宿主文件。
- `scope` 与 `session` 一对一，是临时耦合；未来要拆。
- 跨进程/多主机时，宿主锁不能防止绕过 `SessionService` 的直接 `v24.start`；一个会话多活动 run 只能靠纪律。
- `wait` 跨 run 的可见性弱；新 run 由 `steer` 的调用方自己知道，其他 waiter 需要重新 poll。
- 会话目录、列表、权限仍以宿主文件为准，不适合多用户。

**适用**

- 现在；单用户、loopback、单宿主进程；先落地 API 与测试。

### 4.2 路线 S1：Kernel session anchor（内核会话锚）

```text
runs
  + session_id uuid NULL          -- 不可变；首次 start 铸造，后续 run 沿用
  + i_runs_session(session_id, created_at)
  + u_runs_session_active(session_id) WHERE ended_at IS NULL
```

**形状**

- **命名**：调查的方案 A 用 `runs.conversation_id`；本文公开 API 用 `session_id`。为避免两套 id 名，S1 列名建议直接用 `session_id`；若实现坚持 `conversation_id`，只允许在存储层出现，API/文档仍映射为 `session_id`，不得双名混用。
- `v24.start` 增加可选 `p_session_id`（或 `input.session_id`）；为空时由宿主/内核生成新 session；非空时校验该 session 的既有 run 与 `scope_id/principal` 一致。
- `session_id` 只由首个 run 插入；后续 `UPDATE runs` 不得改它。用解释器白名单/列级 trigger 或权限保证“不可变”，不能只靠约定。
- 首个 run 创建会话成员关系；后续 run 只能追加到同一 `session_id`，不能换 scope/principal。
- 新增只读函数：
  - `v24.host_session_runs(p_session, cursor, limit)`：按 created_at 分页；
  - `v24.host_session_snapshot(p_session)`：组合当前/最后 run；
  - 可选 `v24.poll_session(p_session, p_after)` / `v24.wait_session_check(...)`。
- 六个动词仍由宿主 `SessionService` 实现；区别是 `resolve session → run`、`one active` 和归属检查由 DB 兜底。
- 会话元数据仍可留在 `sessions.json`（名称、模型、workspace），DB 只存成员关系；这样不会引入第二状态机。
- 迁移：对现有每个 `scope` 生成一个 `session_id`（确定性或随机），把该 scope 下所有 run 回填；若一个 scope 已有多个未终态 run，迁移必须失败并人工处理，不能静默选一个。回填完成后可 `SET NOT NULL`；若保留 NULL 兼容旧行，所有读路径必须显式处理 legacy，不能把 NULL 当新会话。
- 规格修订：`v24/sql/10_schema.sql` 是十表闭集；加列/索引也要更新 `docs/designs/v24-pg-agent-2026-10-22.md`、`v24/load.py` 的加载清单（若新增文件）、Cordis DP4 哈希门禁和 `v24/s1/test_ddl.py` 的闭集断言。

**优点**

- DB 能回答会话成员、当前活动 run、归属；崩溃恢复和多进程控制有硬约束。
- 仍然没有 `sessions` 表、没有 `turns` 表、没有第二状态机。
- 会话级 `steer` 的“终态开新 run”可以在一个 DB 事务里做 CAS，避免宿主竞态。
- 与调查建议的“方案 A：`runs.conversation_id`”一致，只是命名用 `session_id`。

**缺点**

- 必须动冻结 SQL 和解释器：`command_start` 的 delta 用 `jsonb_populate_record(NULL::v24.runs, ...)` 做精确 JSON 相等校验（`v24/sql/40_interpreters.sql:633`、`:652`），加列会波及 start 校验、模型摘要、测试向量。
- 部分唯一索引要求“每个 session 至多一个未终态 run”；现有数据/并发路径必须先把所有 run 收敛。
- `session_id` 的授权模型要明确：它不是 capability；仍需 `principal/scope` 检查。
- 迁移和回滚成本高于 S0。

**适用**

- S0 验证 API 后；需要多进程/多主机控制、或希望 DB 成为会话归属权威时。

### 4.3 路线 S2：Session aggregate / catalog（会话目录）

```text
v24.sessions
  session_id PK, principal_id, scope_id, name, created_at, closed_at, archived, metadata jsonb
v24.runs.session_id FK
```

**形状**

- 会话成为 DB 对象，支持列表、搜索、归档、权限、审计；`status` 仍不落列，而是读时从 run 派生。
- 可增加 `parent_session_id` 支持 fork/树（先不做）。
- 六动词不变；`poll`/`wait` 可以走 DB 读函数，减少宿主组合。

**优点**

- 最接近 RepoPrompt 的 session 产品面；多用户/多主机友好。
- 会话目录、名称、归档、清理有统一权威。

**缺点**

- 第十一张表 + 规格修订；如果再加 `status`/`active_run_id` 就会变成第二状态机，必须克制。
- 与 `sessions.json` 形成双写/迁移问题；需要明确“谁是权威”。
- 对当前单用户 loopback 没有直接收益。

**适用**

- 出现多用户、会话目录、审计、跨主机恢复需求时；当前只作为演进方向，不作为第一落地。

### 4.4 路线对比

| 维度 | S0 Host façade | S1 Kernel anchor | S2 Session catalog |
|---|---|---|---|
| SQL/schema 变更 | 无 | 加列 + 索引 + 读函数 | 加表 + 列 + 读函数 |
| 冻结哈希影响 | 无 | 有，需要规格修订 | 有，需要规格修订 |
| DB 能回答会话归属 | 否 | 是 | 是 |
| 一会话一活动 run 的硬约束 | 宿主锁 | 部分唯一索引 | 部分唯一索引 + 目录 |
| 多进程/多主机 | 弱 | 中 | 强 |
| 六动词 API 稳定 | 是 | 是 | 是 |
| 实施成本 | 低 | 中高 | 高 |
| 回滚 | 容易 | 需要迁移回滚 | 最难 |
| 适合阶段 | 现在 | 目标形态 | 产品化以后 |

**建议：S0 先落地，API 按 S1 设计；S1 在规格修订获批后做；S2 只在出现明确产品需求时做。** 不要把 S0 的 `scope` 耦合写进公开合同，也不要把 S2 的 `sessions` 表提前塞进 S0。

## 5. 目标对象模型

### 5.1 对象

| 对象 | 身份 | 职责 | 不是什么 |
|---|---|---|---|
| Session | `session_id`，稳定 UUID | 分组、控制门面、用户可见的会话 | 不是预算/状态机/effect 所有者 |
| Run | `run_id`，现有 | 一次可恢复执行；预算、控制世代、终态 | 不是会话；一个会话可有 N 个 run |
| User turn | `(session_id, user_turn_no)` | 用户请求边界（start/steer） | 不是 `runs.turn_no`；respond 不产生 |
| Interaction | `interaction_id = source_model_effect_id` | 模型请求人工输入 | 不是 run；不是 turn |
| Effect | `effect_id` | model/tool 的结算事实 | 不是会话事件 |
| Transcript entry | `entry_id`，宿主 | 用户可见消息/工具结果 | 不是 DB 表；不是 provider 原文的唯一副本 |
| Cursor | `(session_id, run_id, run_revision, event_seq, registration_generation, epoch_no, generation, interaction_id)` | 客户端自己的读位置；`interaction_id` 防止同一交互反复唤醒 | 不是消费标记；不是全局 offset |

### 5.2 基数

| 关系 | 基数 | 强制方式 |
|---|---|---|
| session : run | `1:N`；同时至多 1 个非终态 | S0 宿主锁；S1 部分唯一索引 |
| run : effect | `1:N` | 现有 `effects.run_id` |
| run : user turn | `1:N`（start + 若干 steer） | 宿主 transcript/counters |
| session : user turn | `1:N` | 同上 |
| run : interaction | `0..1` 当前 | 现有 `runs.interaction` |
| session : transcript entry | `1:N` | 宿主 append-only |
| parent run : child run | `1:N`；(parent, spawn_key) 唯一 | 现有 `u_runs_spawn`；**不等于会话成员** |

### 5.3 四种计数（命名纪律）

| 名称 | 定义 | 归属 | 用途 |
|---|---|---|---|
| `effect_settlement_no` | 当前 run 内首次提交的 business effect 结算数；model/tool 各 +1 | `runs.turn_no` | 内核/审计；不能当 UI 轮数 |
| `model_round_no` | 以一次模型响应为中心的轮次 | 从 model effect 派生 | 模型调用统计 |
| `tool_round_no` | 已准入的工具批次数 | 从 tool batch/effect 派生 | 工具统计 |
| `user_turn_no` | 已提交的用户请求边界；start/steer +1，respond 不 +1 | 宿主 counters | 会话 UI、列表、上限 |

`session_turn_no` 不是第五种计数；如果产品需要“第几轮对话”，用 `user_turn_no`。对外文档和 API 禁止裸用 `turn`。

**与调查第 1 步的关系**：调查建议先做只读 `host_run_ledger`（每 effect 一行，输出四计数 + `late` + `generation`），它零 schema 变更但会新增 SQL 函数。本文的 S0 为了不碰冻结 SQL，先只保证 `effect_settlement_no`（`runs.turn_no`）与 `user_turn_no`（宿主），`model_round_no`/`tool_round_no` 返回 `null`；S1-M5 前先补只读 ledger，再谈 `runs.session_id`。不要把“四个计数”伪装成已经全有。

### 5.4 会话状态派生

不存 `sessions.status`。每次快照按以下顺序派生：

```text
if session.setup_incomplete:                  status = "starting"
elif session.active_run_id is not null:
    status = run.status                       # running | waiting | terminal
elif session.last_run_id is not null:
    status = last_run.status                  # completed | failed | cancelled | blocked_unknown
else:
    status = "idle"
```

公开状态枚举：

```text
starting | running | waiting_for_input | completed | failed | cancelled | blocked_unknown | idle | closed
```

映射：

- 内核 `run.status = waiting` → 公开 `waiting_for_input`；`snapshot.run.status` 保留 `waiting`。
- `active = status in (running, waiting_for_input)`。
- `terminal = status in (completed, failed, cancelled, blocked_unknown)`。
- `closed` 只由管理面设置，不由六个动词产生。

### 5.5 会话快照（摘要）

完整 schema 见 API 合同文档；这里只列骨架：

```json
{
  "v": 1,
  "session_id": "uuid",
  "name": "fix-parser",
  "status": "running",
  "active": true,
  "terminal": false,
  "created_at": "ISO-8601",
  "updated_at": "ISO-8601",
  "run_no": 2,
  "user_turn_no": 3,
  "current_run": { "run_id": "uuid", "status": "running", "turn_no": 5, "revision": 12, "...": "..." },
  "interaction": null,
  "pending_steer": null,
  "counters": { "runs": 2, "effect_settlement_no": 5, "user_turn_no": 3 },
  "cursor": { "session_id": "uuid", "run_id": "uuid", "run_revision": 12, "event_seq": 34, "registration_generation": 1, "epoch_no": 2, "generation": 3, "interaction_id": null }
}
```

`current_run` 是 `v24.poll` 的 run 投影子集；`last_run`/历史 run 通过会话读接口分页，不塞进每次快照。

## 6. 六动词总览

### 6.1 职责表

| 动词 | 目标 | 读写 | 幂等 | CAS | RepoPrompt 对应行为 | v24 内部落点 |
|---|---|---|---|---|---|---|
| `start` | 新建 session + 首个 run | 写 | `request_key` | 无 | 拒绝 `session_id`；返回 `session_id` | `v24.start` + 会话绑定 |
| `poll` | 读快照 | 读 | 不适用 | 无 | `session_id`/`session_ids`，纯读 | `v24.poll` + 会话元数据 |
| `wait` | 等到有意义状态 | 读 | 不适用 | 无 | cursor + timeout；不消费 | `v24.wait_check` + 宿主等待 |
| `cancel` | 取消活动 run | 写 | `request_key` | `expected_*` 可选 | 只对活动 run；终态 `already_terminal` | `v24.cancel` |
| `steer` | 继续会话 | 写 | `request_key` | `expected_*` 可选 | 活动 → 同 run；终态 → 同 session 新 run；waiting → `interaction_pending` | `v24.steer` 或 `v24.start` |
| `respond` | 回答当前交互 | 写 | `request_key` | `interaction_id` 精确 | `session_id + interaction_id` | `v24.respond` |

### 6.2 公共信封

```json
{
  "v": 1,
  "op": "steer",
  "ok": true,
  "disposition": "committed",
  "session_id": "uuid",
  "run_id": "uuid",
  "snapshot": { "...": "..." },
  "cursor": { "session_id": "uuid", "run_id": "uuid", "run_revision": 12, "event_seq": 34, "registration_generation": 1, "epoch_no": 2, "generation": 3, "interaction_id": null },
  "error": null
}
```

- `disposition`：`committed | replay | deferred | rejected | read`。
- 读动词 `ok=true, disposition="read"`；写动词按提交结果。
- 错误也带 `snapshot`（若存在），便于客户端对账；不带内部异常、SQL、provider 原文。
- `session_id` 在 `start` 成功后必返；后续动词必带。

### 6.3 状态机

```text
                 start
                   │
                   ▼
              starting ──setup fail──▶ starting (setup_incomplete)
                   │ install/start ok
                   ▼
                running ◀──────────────┐
                   │                   │ respond
          ┌────────┼────────┐          │
          ▼        ▼        ▼          │
     waiting_  completed  failed   cancelled
     for_input     │        │          │
          │        └───────┴──────────┘
          │ cancel              steer (terminal)
          ▼                         │
      cancelled ────────────────────┘
          │
          └── steer (terminal) ──▶ running (new run)

     blocked_unknown ── steer ──✗ (reject)
                    └─ cancel ──▶ already_terminal
```

- `start` 只从“无会话”进入 `starting/running`。
- `steer` 是唯一能从终态（`completed/failed/cancelled`）回到 `running` 的动词；`blocked_unknown` 除外。
- `respond` 只从 `waiting_for_input` 回到 `running`。
- `cancel` 只从 `running/waiting_for_input` 到 `cancelled`。
- `poll/wait` 不改变状态。

## 7. 关键语义决定

### 7.1 `start`：只创建，不续接

- 拒绝 `session_id`；错误信息明确“用 `steer` 继续已有会话”。
- 返回 `session_id` 与 `run_id`；`session_id` 是后续唯一控制句柄。
- 创建顺序（S0）：
  1. 分配 `session_id`，写 `state=starting`（含 request key、workspace、toolset、model）；
  2. 创建/恢复 `scope`；
  3. 安装工具（可重入）；
  4. 用派生 run key 调 `v24.start`；
  5. 绑定 run，写首个 user turn，`state=active`；
  6. 返回快照。
- 任一步失败：保留 `starting/setup_incomplete` 会话，返回 `session_id` + 错误；同 key 重试从失败点继续。`cancel` 对 `starting` 执行清理并置 `closed`（管理面也可显式 `session_close`）。
- **幂等**：同一 `request_key` + 同 payload 重放返回同一 `session_id`；不同 payload `request_conflict`。`v24.start` 的 request journal 是最后一道账本（`v24/sql/30_advance.sql:254`）。S0 必须在分配 `session_id` **之前**用宿主级 start 锁 + `pending_start` 按 `(principal, request_key)` 查重放，否则同 key 并发会建出两个会话。
- **默认不阻塞**：S0 的 `start` 只完成准入并返回 `running` 快照；客户端用 `wait` 等首个有意义状态。若 MCP 层需要 RepoPrompt 的“start 等到终态”，在传输层用 `start + wait` 组合实现，不改变内核合同。

### 7.2 `poll`：纯读，不消费

- 单会话：`session_id`；多会话：`session_ids`（S0-M4 用循环实现；S1 用单次读函数）。
- 接受 `cursor`；返回 `changed`、`snapshot`、当前 run 的 `events`（可选，最多 64 条）。
- 不增加 revision、不消费 wake、不写 session 文件（除必要的内存缓存外）。
- 未授权/未知统一 `not_found_or_denied`；不泄露“存在但无权”。
- 会话元数据（name/archived）变化可以返回新快照，但不把 `changed` 绑定到元数据；`changed` 只看 `(run_id, run_revision, event_seq)`。

### 7.3 `wait`：等到“有意义”，不消费

`wake.reason` 枚举与优先级：

| 优先级 | reason | 条件 |
|---|---|---|
| 1 | `terminal` | 当前 run 终态（或会话 `idle`）且 cursor 指向同一 run |
| 2 | `interaction` | 当前 run `waiting`，`interaction_id` 与 `cursor.interaction_id` 不同 |
| 3 | `run_started` | 当前 run_id 与 cursor.run_id 不同（另一客户端 `steer` 开了新 run） |
| 4 | `epoch` | 同一 run 的 `epoch_no`/`driving_generation` 与 cursor 不同 |
| 5 | `event` | `run_revision > cursor.run_revision` 或 `event_seq > cursor.event_seq` |
| 6 | `timeout` | 超时；`ready=false`，快照仍返回 |
| 7 | `none` | `timeout=0` 且无变化；`ready=false` |

- `terminal` 优先于 `event`：终态一定可操作，不应被事件流淹没。
- `interaction` 优先于 `event`：等待输入必须让客户端看到 `interaction_id`。
- `run_started` 优先于 `epoch`/`event`：客户端需要知道句柄换了。
- 多会话：返回第一个 interesting 的 `winner_session_id`；其余放 `pending_session_ids`；全部终态时可一次返回。
- 游标由客户端持有；服务端不记录“已读”。不同 waiter 可各自看到同一事件。
- 不持事务/会话锁等待：短读 → `COMMIT`/释放锁 → 条件变量/退避/`LISTEN` → 短读。`timeout=0` 等价于 poll。
- `registration_generation` 失配：返回 `registration_stale` + 快照；客户端 poll 后重试。不要把 stale 当 not found。

### 7.4 `cancel`：只取消活动 run

- 有活动 run：调 `v24.cancel(run_id, expected_generation, key)`；成功返回 `cancelled` 快照。
- 无活动 run，最后 run 已终态：`already_terminal` + 快照；不删除会话、不改变历史。
- `starting/setup_incomplete`：执行宿主清理（取消/关闭 scope），返回 `cancelled`/`closed`；这是管理动作，但仍可由 `cancel` 触发。
- `blocked_unknown`：视为 terminal；`cancel` 返回 `already_terminal`。若需要“封口 unknown”，用管理面 `session_seal`（P1），不要偷偷把 `cancel` 变成 seal。
- **race**：`cancel` 与 worker 结算并发时，run 级 CAS/`advance` 决定胜负；会话层只负责把结果映射成快照。`expected_run_id/expected_generation` 不匹配 → `stale_generation` + 快照，客户端重试。
- **幂等**：同 key 重放原响应；不同 key 对已终态返回 `already_terminal`。

### 7.5 `steer`：会话继续的唯一入口

按当前状态分派：

| 当前状态 | 行为 | 返回 |
|---|---|---|
| `running` | 调 `v24.steer(run_id, message, key)`；同 run，新 epoch/generation | `started=false, queued=true/false` |
| `waiting_for_input` | **拒绝** `interaction_pending`；提示用 `respond` | 错误 + 快照 |
| `completed/failed/cancelled` | 在同一 session 内用派生 key 调 `v24.start`，seed 来自会话 transcript；新 run | `started=true, run_id=新` |
| `blocked_unknown` | **拒绝** `blocked_unknown`；不自动续跑 | 错误 + 快照 |
| `starting` | 拒绝 `setup_incomplete` 或等待 setup 完成 | 错误 + 快照 |
| `idle`（无 run） | 视为可开新 run（若会话已存在） | `started=true` |

- **终态开新 run 是会话级语义，不是 run 级语义。** 不能把 `v24.steer` 的 `already_terminal` 直接透传给客户端。
- **seed 合同**：新 run 的 `input.messages` 由宿主 `ContextBuilder` 从 transcript 生成；在 adapter 仍只接受 `system|user` 的阶段，先注入 `system` 历史块（M6 计划已有约束），并在文档中标注“完整 transcript seed 依赖 M7”。seed 构造失败时拒绝开新 run（`setup_incomplete`），不能静默用空历史继续。
- **等待输入**：不能沿用 run 级 `steer` 的“清 interaction”行为；会话层必须先拒绝，避免静默丢掉用户问题。
- **单槽 vs 队列**：v24 `pending_steer` 是单槽（`v24/sql/10_schema.sql:43`）。S0 默认 **latest-wins**，返回 `superseded=true` 并提示上一条未送达；若要 RepoPrompt 式多指令排队，P1 在宿主加有界 `steer_queue`，按 generation 边界逐条投递。**不要**在 v1 静默丢弃而不告知。
- **幂等**：同一 `request_key` 重放原结果；终态开新 run 的 key 必须派生稳定，避免重试开两个 run。实现上先用 `v24.host_request` 查原响应，再决定是否调用。
- **race**：`steer` 与 run 终态并发时，以 DB 锁内状态为准；可能“看到 running，提交时已 terminal”，此时会话层回退到“开新 run”路径，但必须保证同 key 只产生一个 run。

### 7.6 `respond`：精确消费当前交互

- 必须带 `session_id` + `interaction_id`；当前 run 必须 `waiting`，且 `runs.interaction.interaction_id` 精确匹配。
- 不匹配：`interaction_mismatch`（零写）+ 快照；无交互：`not_waiting`；终态：`already_terminal`。
- `response` 归一化：
  - v24 内核接受 JSON object；API 同时接受 scalar string，宿主包装为 `{"text": "..."}`；
  - 结构化回答用 `answers`/`content`/`meta` 时，宿主组装为内核 response 对象；
  - 不支持的形状返回 `invalid_response`，不要猜。
- `respond` **不增加** `user_turn_no`；它只追加一条 `responded` 事实/转录 meta。
- 幂等：同 key 重放；不同 key 对已消费 interaction 返回 `interaction_mismatch`，不能二次消费。
- `respond` 后 run 回到 `running`；随后可能进入下一 model effect，客户端用 `wait/poll` 跟踪。

### 7.7 幂等与围栏

- **键**：`(principal_id, request_key)`；request key 1–256 字符；派生 run 级 key 不超过 512。
- **规范字节**：包含 `op`、`session_id`、目标 run、`expected_*`、payload；同键异字节 → `request_conflict`（`v24/sql/30_advance.sql:258`）。
- **派生**：`run_key = "s:" + session_id + ":" + op + ":" + sha256(client_key)[:32]`。确定性、可重放、可审计。`steer` 活动用 `op=steer`，终态开新 run 用 `op=steer_new_run`；两者都查，避免与首个 `start` 的 key 碰撞。
- **顺序**：先 `host_request(run_key)` 查重放；未命中才做 CAS/业务；业务提交时由 `v24.advance` 再查一次，防止并发双写。
- **围栏**：
  - `expected_run_id`：会话层 CAS，防止“以为在 A run，实际已切到 B”。
  - `expected_generation`：run 级 `driving_generation`，防止用旧快照取消/steer/respond。
  - `interaction_id`：respond 的精确围栏。
  - `registration_generation`：wait 的 stale 判定。
- **不要**把 `session_id` 当 capability；授权仍由 principal/scope/role 决定。

### 7.8 并发与“一个会话一个活动 run”

- **S0**：`SessionService` 用 per-session 互斥（进程内 `threading.Lock`），**只支持单宿主进程**；跨进程需先把 session 元数据迁到 DB，不能靠 advisory lock 保护 `sessions.json`。锁顺序：session lock → v24 `advance` G；不得反向。
- **S1**：`u_runs_session_active ON runs(session_id) WHERE ended_at IS NULL` 提供硬约束；会话层仍需 CAS，因为“检查后插入”不是原子。
- **不同会话**：可以并行控制；S0 的单执行器会串行跑 worker，但 `poll/wait/cancel` 不因一个会话的 provider 调用而阻塞（短读）。
- **同一会话的并发 steer**：latest-wins 或队列（§7.5）；两个不同 key 的 steer 不能都成为“当前 pending”，除非有队列。
- **cancel 与 steer 并发**：run 级 `driving_generation` 决定谁赢；会话层返回 `stale_generation` 让客户端对账。

### 7.9 恢复 / resume

- **进程重启**：加载 `sessions.json` v2；对每个 `active` 会话：
  - `current_run.status = running` → 重新 `rehydrate` scope + `drive`；
  - `waiting` → 投影 interaction，不自动 respond；
  - terminal → 标记 idle/terminal，不重开；
  - `starting/setup_incomplete` → 重新执行 setup 或标记只读。
- **`steer` 终态**：新 run 使用 transcript seed；不复制旧 run 的 budget/effect；journal 按新 run 重建。
- **`poll/wait` 重启后**：cursor 仍有效，只要 `(run_id, registration_generation)` 存在；否则返回 `registration_stale`。
- **不重开终态 run**：与现有 `/resume` 语义一致（`v24/ui/app.py:579`、`:601`）。

### 7.10 安全与归属

- 会话属于 `(principal_id, workspace_root)`；`scope` 是能力隔离根。
- 所有动词先授权，再解析 session/run；未知与无权统一 `not_found_or_denied`。
- `session_id` 不是 secret；不要把它当 bearer token。恢复令牌仍走独立 token（现有 `resume_token_hash`）。
- 不把 provider key、DSN、Authorization、prompt 原文放进快照/错误/日志。
- `session_close`/`session_delete` 是管理面，需单独授权；六动词不提供删除。

### 7.11 多会话 `poll/wait`

- `poll(session_ids)`：返回数组，按输入顺序；最多 32 个；未知项逐项 `{session_id, ok:false, error:{code:"not_found_or_denied"}}`，不让一个未知项拖垮整批，也不泄露存在性。
- `wait(session_ids)`：返回第一个 interesting；`winner_session_id`；`pending_session_ids`；`all_terminal` 快捷返回。
- S0 用循环 + 条件变量；S1 可用 DB 读函数一次查询。
- 多会话等待不保证公平；先到先返回。

### 7.12 管理面（不在六动词内）

六个动词只做控制；产品还需要：

| 操作 | 说明 | 阶段 |
|---|---|---|
| `session_list` | 列出会话（name/status/updated_at/workspace） | S0 |
| `session_get` | 读元数据 + transcript 摘要 | S0 |
| `session_rename` | 名称 | S0 |
| `session_transcript` | 分页读 transcript（独立读，不是 `poll`） | S0/P1 |
| `session_close` | 取消活动 run + 关闭 scope | S0 |
| `session_archive` | 只归档元数据，不删 scope | S1 |
| `session_export` | Markdown/JSONL | P1 |
| `session_delete` | 删除元数据/清理 scope，需额外授权 | P2 |

不要在六动词里偷偷加 `list`/`close`/`export`；否则“六动词”名不副实。

## 8. 与 RepoPrompt 的对标矩阵

| 行为 | RepoPrompt | v24 目标 | 差异/备注 |
|---|---|---|---|
| `start` 新建会话 | 是；拒绝 `session_id` | 是 | 错误文案引导 `steer` |
| `session_id` 稳定 | 是 | 是 | S0 宿主、S1 DB 都稳定 |
| `poll` 单/多会话 | 是 | 单会话 S0；多会话 P1 | 快照字段不同，语义同 |
| `wait` cursor/timeout | 是 | 是 | v24 cursor 用 `(session_id, run_id, revision, event_seq, epoch, generation, interaction_id)` |
| `wait` 的 steering 中断 | 有 `steering_requested` | v1 不提供；P1 可加 `epoch`/`steering` wake | 不假装有 |
| `cancel` 只对活动 run | 是 | 是 | 终态 `already_terminal` |
| `steer` 活动 → 同 run | 是 | 是 | `pending_steer` 单槽 |
| `steer` 终态 → 同 session 新 run | 是 | 是 | **本设计的关键 parity** |
| `steer` waiting → 拒绝 | 是（提示 respond） | 是 | 不能沿用 run 级清 interaction |
| `respond` 精确 interaction | 是 | 是 | scalar 归一化为对象 |
| `respond` 不产生 user turn | 是 | 是 | `user_turn_no` 不变 |
| 状态名 | `waiting_for_input` | 公开同；内部 `waiting` | 映射表见 §5.4 |
| `blocked_unknown` | 无同名 | 有 | 终态；`steer` 拒绝 |
| `start` 默认等待 | 是（timeout/detach） | S0 默认不等待；`wait` 组合 | 传输层可模拟 |
| 会话管理 | `agent_manage` | 独立管理面 | 不在六动词内 |
| transcript/log | `get_log` | `session_transcript` | 独立读 |
| 多执行器/子代理 | 是 | 不在本设计 | 先保留接口 |

## 9. 从当前 v24 UI 迁移

### 9.1 `sessions.json` v1 → v2

- `format_version: 1 → 2`；保留旧字段读取兼容。
- `conversation_id` 作为 `session_id` 的别名读取；新写入只写 `session_id`（或双写一段时间）。
- 新增：`state`（`starting|active|closed`）、`model`、`name`、`counters`、`active_run_id`（缓存，读时以 run 为准）、`pending_start`（可重放）、`transcript` 摘要。
- 旧 `bindings` 保留；`active_binding` 继续作为兼容字段；新代码用 `active_run_id` + `v24.poll`。
- 旧 `turns.jsonl` 迁移到 `transcripts/<session_id>.jsonl` 或保留读取；`user_turn_no` 由 `seq` 派生。
- 所有写入仍 `atomic_json`（0600、fsync、rename，`v24/ui/sessions.py:28`）。

### 9.2 UI 命令映射

| 现有入口 | 迁移后 |
|---|---|
| `/new` | `start` |
| 普通文本（空闲） | `steer`（无活动 run 时开新 run） |
| 普通文本（运行中） | `steer`（同 run） |
| `/cancel` | `cancel` |
| AskUser 回答 | `respond` |
| `/resume <run_id>` | 兼容：先解析 run → session，再 `poll`/`steer` |
| `/close` | `session_close`（管理面） |

- 旧 `/resume` 保留一个版本周期；内部改为“按 run 找 session”，不再把 run 当会话。
- `catalog_changed`/`readonly` 行为保留：会话层只读时拒绝写动词，返回 `catalog_changed`。

### 9.3 上线策略

- 特性开关 `V24_SESSION_API`（默认关闭）：新旧路径双读，写仍走旧路径；测试通过后切写。
- 迁移前备份 `sessions.json`/`turns.jsonl`；迁移失败 quarantines，不删除原文件。
- 回滚：关闭开关，旧代码读 v1 字段；新字段可忽略。
- S1 迁移单独做，不复用 S0 的回滚路径。

## 10. 验收摘要

完整矩阵见落地计划；最低验收面：

1. **start → poll → wait → terminal**：得到稳定 `session_id`、`run_id`、final；重放同 key 不新建。
2. **steer 活动**：同 `run_id`，`epoch_no`/`driving_generation` 增加，`user_turn_no + 1`，旧 pending 标记 superseded。
3. **steer 终态**：新 `run_id`，同 `session_id`，`run_no + 1`，`user_turn_no + 1`，seed 含上轮 final。
4. **steer waiting**：`interaction_pending`，零写；`respond` 后才继续。
5. **cancel**：活动 run → `cancelled`；再次 cancel → `already_terminal`；会话仍可 steer。
6. **respond**：精确 id 成功；错误 id `interaction_mismatch` 零写；`user_turn_no` 不变。
7. **wait**：terminal/interaction/event/run_started/timeout 五种 wake；`timeout=0` 不写。
8. **幂等/冲突**：同 key 同 payload replay；同 key 异 payload `request_conflict`。
9. **恢复**：重启后 running 重新驱动、waiting 保留交互、terminal 不重开。
10. **授权**：其他 principal/未知 session 统一 `not_found_or_denied`。
11. **S0 约束**：不新增 SQL 文件、不改 `v24/sql/**`；既有 `v24/s3`、`v24/s4`、`v24/ui` gate 全绿。
12. **S1 追加**：DB 拒绝同 session 第二个未终态 run；迁移后旧 scope 全部可解析。

## 11. 风险与明确不做

### 11.1 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| S0 宿主锁不能防绕过 | 同会话可能两个活动 run | 所有入口只走 `SessionService`；S1 加 DB 约束；启动时扫描并修复 |
| `scope` 与 `session` 耦合 | 未来拆分会迁移 | 公开合同不暴露 `scope`；内部映射层；S1 加 `runs.session_id` |
| 终态 steer 重试开两个 run | 重复执行/计费 | 派生稳定 key + `host_request` 重放 + session 锁 |
| `wait` 跨 run 丢失 | 客户端看不到别的客户端开的新 run | `run_started` wake + 客户端 poll；S1 会话级读 |
| transcript seed 与 adapter 合同不符 | 新 run 丢历史 | 先注入 system 历史块；M7 完整 seed；gate 覆盖 |
| `pending_steer` 单槽丢指令 | 用户以为两条都送达 | 返回 `superseded` 并显示；P1 队列 |
| 单执行器阻塞多会话 | 一个 120s provider call 卡所有会话 | S0 接受；S1/P1 执行器分离；`poll/cancel` 不阻塞 |
| 会话删除/关闭与活动 run 竞争 | 资源泄漏 | 管理面先 cancel，再 close scope；S1 事务化 |
| 快照/错误泄露 prompt/key | 安全 | 统一渲染/脱敏；错误只给 code；gate 扫描 |

### 11.2 明确不做

- 不建 `turns`、`run_attempts`、`session_status`、`session_events` 表。
- 不把 `runs.turn_no` 当 UI 轮数，也不新增 `session.turn_no` 与之竞争。
- 不让 `session_id = run_id`；终态后新输入需要新 run。
- 不用 `scope_id` 作为公开 `session_id`。
- 不从 `parent_run_id` 自动回灌子代理结果。
- 不把 provider 原文、reasoning、tool_call_id 搬进 DB。
- 不在六动词里塞 `list/close/export`。
- 不在 S0 修改冻结 SQL；S1 必须走规格修订。

## 12. 需要拍板

| # | 决策 | 选项 | 建议 |
|---|---|---|---|
| 1 | 会话锚路线 | S0→S1 / 直接 S1 / 只做 S0 | **S0→S1**；先交付可验证的门面 |
| 2 | `steer` 多指令 | 单槽 latest-wins / 宿主有界队列 | **v1 单槽 + 明确 superseded**；队列 P1 |
| 3 | 会话元数据 | `sessions.json` / DB `sessions` 表 | **S0 宿主；S1 仍宿主，S2 再入 DB** |
| 4 | `cancel-late` 计数 | 保守（late 不推进）/ 统一向上（首次 receipt +1） | 调查建议“统一向上”，但需与规格 §5.1 一起修订；**不与 S0 绑定**，S1 前拍板 |
| 5 | 公开命名 | `session_id` / 继续 `conversation_id` | **`session_id` 为公开名**；`conversation_id` 只允许在兼容读取/存储层出现，不进入公开 API |
| 6 | `start` 是否默认等待 | 立即返回 / 等到首个有趣状态 | **立即返回 + `wait` 组合**；MCP 层可封装 |

## 附录 A：六动词 → v24 内部落点

| 会话动词 | S0 宿主实现 | S1 可下推的读/写 | 关键围栏 |
|---|---|---|---|
| `start` | 分配 session → scope/install → `v24.start` → bind | `v24.start(..., session_id)` | request key；scope/fiber |
| `poll` | `v24.poll` + session store | `v24.poll_session` | 无 |
| `wait` | 短读 + `v24.wait_check` + 条件变量 | `v24.wait_session_check` | registration/epoch/event |
| `cancel` | `v24.cancel` | `v24.cancel_session` | expected generation |
| `steer` 活动 | `v24.steer` | `v24.steer_session` | expected generation；pending 单槽 |
| `steer` 终态 | `v24.start`（同 session，派生 key） | `v24.start_session_run` | same-key 只开一个 run |
| `respond` | `v24.respond` | `v24.respond_session` | interaction_id + generation |

## 附录 B：术语

- **Session**：用户可见的会话容器；稳定 `session_id`；跨 run。
- **Run**：一次可恢复执行；现有 `runs` 行。
- **User turn**：用户请求边界；`start`/`steer` 产生；`respond` 不产生。
- **Effect settlement**：model/tool effect 的首次提交结算；`runs.turn_no`。
- **Cursor**：客户端持有的读位置；不是服务端消费标记。
- **Facade**：会话级六动词对 run 级六动词的解析与语义改写层。
