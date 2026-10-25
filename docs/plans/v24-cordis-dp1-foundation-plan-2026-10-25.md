# v24 Cordis v2 DP1：基础内核与验收计划

状态：实施中；P0、W1、W2 已实跑通过，W3–W4 待实施。唯一产品规格为 [`cordis-plugin-system-2026-10-25.md`](/Users/wxl/Projects/pg-agent/.claude/worktrees/v99/docs/designs/cordis-plugin-system-2026-10-25.md)。

## 1. Summary

DP1 在 v24 分支上为 Cordis v2 增加一套隔离的基础设施：独立 schema、loader、fixture、八张领域表和两个簿记表，以及与 v24 `advance(uuid,jsonb)` 信封兼容的内核骨架。它实现提交锁、身份认证、请求和 receipt 重放、claim 资格、事务边界、闭集错误码、有限的 delta 足迹校验接缝和有序锁 pass；不实现任何插件生命周期或运行时执行行为。所有新增内容放在 `v24/cordis/`，v24 已有 SQL、loader manifest 和 stage gate 保持不变。

### Goal

为 DP2–DP6 提供独立、可验收的数据库基础，同时保留 v24 已有行为和 gate。

### Done when

1. 实施只发生在 `.claude/worktrees/v99` 的 `v24` worktree，基线提交在实施前核实并记录；主检出不参与施工。
2. v24 的 12 文件 SQL manifest、9 个冻结 SQL 文件和现有 stage gate 均保持不变；实施前后复跑 v24 的 11 条 closeout 命令，并将 `v24/s9/test_g8.py` 作为单独的扩展回归检查记录。
3. `v24/cordis/` 有独立的 canonical-prefix SQL loader、pgembed Unix socket fixture 和精确 catalog 检查。
4. `v24_cordis` schema 中恰有 8 张领域表和 2 张簿记表；表列、外键、唯一索引、检查约束和触发器由独立 DDL gate 验证。
5. `v24_cordis.advance(uuid,jsonb)` 使用兼容的 v24 信封，G 锁、认证、重放、claim、错误处理和 delta 校验接线可独立测试；生命周期 interpreter 在生产定义中明确保持未实现。
6. DP1 专属 gate 覆盖 loader、fixture、DDL 负例、ACL、receipt/replay、claim/屏障 deferred/stale claim、调用方 COMMIT 和回滚，不把任何未实现能力标为通过。
7. conformance matrix、deviation ledger 和 DP1 README 按每个里程碑更新；每个通过的里程碑单独提交并推送至 `origin/v24`。

## 2. Current-state analysis

### 实施环境准备（P0 前置）

施工根目录固定为 `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99`，由该目录执行所有 `uv`、测试与 Git 命令；主 checkout 有用户未提交改动，禁止在其中切换分支、清理或实施。仓库锁定 Python 3.12（`.python-version`）并要求 `>=3.12`；`pyproject.toml` 使用 `uv` lock、`psycopg2-binary`，且通过本地 editable `../pgembed` 与机器本地的 DuckDB wheel 路径。因此实施 agent 必须先检查这两个相对依赖源存在，并确认工作树内 `.venv` 的 owner/路径属于本 worktree 后，再用 `uv sync --locked` 验证锁文件可复现；如果依赖路径或平台 wheel 不可用，先记录环境 blocker，不要升级依赖或重写 lockfile 来绕过。

数据库通过 `v24/s1/setup_db.py` 的私有 `--server-helper` 子进程调用根 `server.py:14-19`，使用该 worktree 的 `.pgdata`，而非系统 Postgres service。“私有 helper”不等于独立集群：同一 worktree 的 gates 串行运行，不手工删除 `.pgdata` 或停止其他进程使用的服务。helper 启动失败、超时、测试取消均进入 finally：只清理已记录且再次核对 OID/名字/属性的临时库与角色（先 DB、再 LOGIN、最后 NOLOGIN 组），终止并 wait 自己启动的 helper；连接先 rollback/close，不做通配 DROP。cleanup 失败保留精确身份和错误，不吞异常。

运行时 `v24/s1/README.md:78-80` 记载 PostgreSQL 18.4 / psycopg2 2.9.12；这是历史实测。P0 的 Python 命令只复核 Python/psycopg2，现有 v24 self-check 不输出 PG 版本：P0 要通过 fixture 的维护连接只读执行 `SELECT current_setting('server_version'), current_setting('server_version_num')` 并记录；W1 将同一查询固化进 Cordis self-check。要求 PG 18 系列；与历史 patch 版本不同须记录并通过全部 gate，不能冒称本机仍为 18.4。fixture 仅接受活动 Unix socket，拒绝 hostaddr/service/TCP/multi-host；测试库从 `template0` 建立。新 `00_schema.sql` 和 CDP1-E 仿照 `v24/sql/00_schema.sql:4-33` 验证 `pg_catalog.sha256(bytea)`、`pg_catalog.gen_random_uuid()` 为核心可用函数且非 extension 依赖；失败停止，不安装 pgcrypto 绕过。无需真实 provider、人工预建 schema 或长期应用数据库；DP1 不引入外部 IO。

### 当前检出与基线

所附材料给出的基线如下；P0 必须重新验证，尤其要 fetch 后确认远端分支状态。

| 项目 | 已提供的事实 | 实施前验证 |
|---|---|---|
| 实施 worktree | `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99` | `git rev-parse --show-toplevel` |
| 分支与 HEAD | `v24 @ 57e2c1e` | `git branch --show-current`、`git rev-parse HEAD` |
| v24 worktree | tracked 文件干净，存在未跟踪文档，具体集合以实施 P0 的 `git status --short --untracked-files=all` 实测为准 | `git status --short --untracked-files=all` |
| 主检出 | `/Users/wxl/Projects/pg-agent` 的 `main@ab34d69`，有用户修改 | 只读核查；不得切换、清理或在其中施工 |
| 数据库运行环境 | PostgreSQL 18.4、psycopg2 2.9.12（历史实测，P0 复核）、`uv run` | 核对本机 Python/psycopg2 并运行 v24、DP1 fixture 自检 |
| 目标推送分支 | `origin/v24` | `git fetch origin` 后核对跟踪关系 |

P0 记录 `57e2c1e` 为预期基线。实现预算沿用设计稿 §10.1：8 个领域 SQL 文件（一表一文件）、领域 DDL ≤900 行、advance 与 helpers ≤1200 行、B=16；超过行预算须简化实现或回到规格重裁；拆私有 helper 只改善结构，全部 helper 仍计入总预算，不得靠挪文件规避。DP1 不创建第二 scheduler，仅为后续单宿主公平扫描预留 effect/fiber 数据合同。若 HEAD、分支或 worktree 状态与预期不同，先审查差异再施工，不要覆盖现有未跟踪文档。

v24 的 `SQL_LOAD_ORDER` 是 12 个 SQL 文件的 canonical prefix：

```text
00_schema.sql
10_schema.sql
20_triggers.sql
30_advance.sql
40_interpreters.sql
45_capability.sql
46_cleanup.sql
47_verbs.sql
48_loop.sql
49_recovery.sql
49_host_reads.sql
50_permissions.sql
```

其中 9 个冻结 SQL 是 `10_schema.sql`、`20_triggers.sql`、`30_advance.sql`、`40_interpreters.sql`、`45_capability.sql`、`46_cleanup.sql`、`47_verbs.sql`、`48_loop.sql`、`49_recovery.sql`。P0 和最终验收都记录 SHA-256；对冻结 SQL 运行 `git diff --exit-code`，并验证 12 文件 manifest 仍与当前 v24 loader 相同。计划中的所有 Cordis SQL 只登记进新 loader，绝不追加到 `v24/load.py`。

### 可复用架构与 DP1 边界

`v24/sql/30_advance.sql:85-172,239-289,317-320,882-900` 提供值得复用的协议合同：outcome 信封、`session_user` 身份、`pg_advisory_xact_lock(24,1)`、command request 幂等、terminal receipt 优先于 claim token 检查、attempt/fence/owner 资格、B=16、闭集错误和调用方负责 COMMIT。它绝不执行外部 IO。`v24/load.py:10-23,31-66` 的 canonical prefix、symlink/未登记 SQL 拒绝和事务内不 COMMIT 的做法，是 Cordis loader 的环境先例。

`v24/s1/setup_db.py:28-68,267-299,529-550`、`test_ddl.py` 和 `test_g1.py` 提供 Unix socket DSN 校验、临时数据库精确清理、owner/应用角色分离、catalog 闭集断言、savepoint 负例、全状态快照比较和 `pg_locks` 锁证据的模式。Cordis fixture 应镜像这些纪律，但不可导入 v24 fixture 并继承其 schema、角色名、manifest 或 catalog 语义。

`v24/sql/30_advance.sql:55-83` 的早期 interpreter/delta definitions 是 `0A000` seam；canonical loader 随后加载 `v24/sql/40_interpreters.sql`（见 `v24/load.py`）替换为实际实现，且 `v24/s1/README.md:55-67` 记录了 S1 settlement 实现。因此 DP1 只定义 Cordis 自己的 seam，不把 v24 当作未实现骨架，也不复制 v24 的 lifecycle 实现。

设计稿 `docs/designs/cordis-plugin-system-2026-10-25.md:43-51`（§1.2）明确 `events` 和 `requests` 是簿记表而非领域表；DP1 保留二者，因为 request 行承担首次 response 与命令 replay，event 行承担 append-only 可观测记录。它们不计入八张领域表预算。

### 实施策略

采用隔离新增，不重构 v24。Cordis 的八表模型、事件/请求簿记和生命周期均有独立语义；迁移 v24 的旧表或修改 v24 的 `advance` 会把两套生命周期耦合起来，并违反设计稿 §12.3。因此复用的是协议合同和 fixture 纪律，新增的是 Cordis schema 和内核接线。

## 3. Design

### 固定决策与开放项裁决

| 事项 | DP1 固定决策 |
|---|---|
| 目录前缀 | `v24/cordis/`；DP1 测试、fixture、README 放在 `v24/cordis/dp1/` |
| schema | 独立 schema `v24_cordis`，不在 `v24` schema 下建对象 |
| 角色 | 每个 fixture 创建独立、带随机后缀的 `v24_cordis_<pid>_<hex12>_{owner,admin,service,operator}` NOLOGIN 组角色，以及 `<database>_{owner,admin,service,operator}` LOGIN 角色；按 OID 和属性精确清理 |
| advance ABI | 新建 `v24_cordis.advance(uuid,jsonb)`，遵循 v24 的外部 ABI 和事务合同；不调用 `v24.advance`，不复制其 SQL 函数体 |
| 事件与请求 | 两张簿记表 `events`、`requests` 随 DP1 创建；总表数 10，其中领域表恰为 8 |
| 解释器行为 | `interpret_command`、`interpret_settlement` 在生产 SQL 中以明确的 `0A000` seam 结束；只在专用 disposable receipt-probe 数据库中替换 interpreter/barrier seam，替换本身独立 COMMIT；保留另一份 production fixture，最后比较原库函数 hash 并断言两个 interpreter 仍抛 `0A000`；真实 delta applier 不替换 |
| claim 列形状 | 使用 `attempt`、`fence`、`claim_owner`、`lease_until` 表达 v24 的 `{attempt,fence,owner}` claim。附录 A 的 `token uuid` 与 §3.1/v24 ABI 不一致；按 Oracle-adjudicated 2026-10-25 裁决，DP1 不创建独立 token 列，也不发明 token 替代列，偏差记录在 deviation ledger |
| 闭包上限 | 锁闭包最多 512 个不同 typed lock target，超限返回 `retry_with_closure` 且零写。此上限是 DP1 的有界锁实现约束，不增加新领域语义 |
| 锁顺序 | `G` 后按 `scopes → runs → effects → installs → fibers → episodes → contributions → pins` 获取行锁；同一表按 UUID 升序，scopes 例外先按 parent-depth 再 UUID。依设计稿 §3.2，目标 request/effect 行属于 replay target lock 阶段，必须先于 closure；replay 未命中后才锁其余领域 closure |
| ABI 细节 | 保留 v24 outcome 信封、response envelope、body ≤ 1 MiB、深度 ≤ 32、递归对象键总数 ≤ 200、lease 1–300000 ms、B=16 和现有 24 个错误码 |

Oracle-adjudicated 2026-10-25：采用 replay-first 锁序、三元 claim ABI、活 lease 返回 `stale_claim`、512 closure 护栏及八张领域表一表一 SQL 文件；512、host_io合同JSON字段、DP1 revision=0、DP2基本dispose范围和推送分支属于显式实现/范围/流程假设，分别在 Risks and migration 与 P0 中可复核。

### Goal 对应的架构与数据模型

schema/loader/fixture 分离，SQL loader 使用独立 canonical order。遵从设计稿 §10.1 的 8 个领域 SQL 文件预算（每张领域表一个文件）；额外文件承载簿记表、循环 FK、触发器、advance 与 ACL：

```text
00_schema.sql
10_installs.sql
11_scopes.sql
12_fibers.sql
13_episodes.sql
14_contributions.sql
15_pins.sql
16_runs.sql
17_effects.sql
18_events.sql
19_requests.sql
20_relations.sql
30_triggers.sql
40_advance.sql
50_permissions.sql
```

`SQL_LOAD_ORDER` 只能是 `CANONICAL_ORDER` 的连续前缀；不得以 glob 加载，不得接受 symlink、目录伪装或未登记 SQL。`00` 创建 `v24_cordis`；`10`–`17` 各自创建一张领域表及局部约束/索引；`18`、`19` 各建一张簿记表；`20` 在表均存在后创建完整跨表 FK（含 owner/current-episode、consumer-run 及延迟 effect 引用）；`30` 放 append-only/不可变/跨行 epoch 守卫；`40` 放 helper 与唯一写入口；`50` 收尾 ACL。每个里程碑只登记并加载已交付文件的连续前缀。

八张领域表采用设计稿 §4.2–§4.3 和附录 A 的承重形状：

| 表 | DP1 列形状与责任 | 关键约束 |
|---|---|---|
| `installs` | `id, scope_id, owner_fiber_id, owner_episode_id, identity, version, manifest, artifact_digest, contracts, policy_ref, overlay, state, created_at`；保存不可变插件声明和安装状态 | `UNIQUE(scope_id,identity,version)`；manifest object 内含 `requires[]`、`provides[]`、`priority` 与 check；`artifact_digest` 为 sha256；`contracts` 保存 ABI/handler digest/replay 权利；owner 两列同空/同非空；复合外键 `(owner_fiber_id,owner_episode_id)` 指向 `episodes(fiber_id,id)`；state 闭集为 `preparing/installed/prepare_failed/prepare_unknown/dispose_pending/disposed`；声明身份不可变触发器。不得另增与 manifest 重复的 `priority` 列 |
| `scopes` | `id, parent_id, realm_overrides, intercept, closed_at`；保存父子路由关系及 JSON 配置 | parent_id 自引用 FK；`realm_overrides`、`intercept` 须为 JSON object；`closed_at` 单调且 closed scope 不复开；parent 链由约束触发器拒绝环；route depth 从 parent 链推导，不加 `route_path` 列；DP1 不实现解析、intercept 或 overlay 合并 |
| `fibers` | `id, install_id, owner_id, owner_episode_id, scope_id, want_on, control_seq, current_episode_id, retire_started_at, failure, dispose_requested_at, disposed_at` | owner CHECK 明确为 `(owner_id IS NULL) = (owner_episode_id IS NULL)` 且 `owner_id IS DISTINCT FROM id`；`owner_id` 自 FK 与 `(owner_id,owner_episode_id)` 历史 episode 复合 FK；`current_episode_id` 通过 `(id,current_episode_id)` 复合 FK 指向 `episodes(fiber_id,id)` 固定当前身份；dispose 墓碑不可复活；`control_seq >= 0` |
| `episodes` | `id, fiber_id, epoch, state, committed_view, iterator, opened_at, closed_at, outcome`；保存 θ、冻结 ω 和 iterator | `UNIQUE(fiber_id,epoch)`、`UNIQUE(fiber_id,id)`；`UNIQUE(fiber_id) WHERE closed_at IS NULL`；state 为 `reloading/active/closing`，outcome 为 `ok/error/divert/retire`；JSON 列须为 object |
| `contributions` | `id, fiber_id, episode_id, seq, kind, realm, key, descriptor, prev_contribution_id, inverse, contract_version, withdrawn_at, released_at` | 复合 FK `(fiber_id,episode_id)` 指向 `episodes(fiber_id,id)`；`UNIQUE(fiber_id,episode_id,seq)`；kind 为 `service/listener/cell/reservation/child`；inverse 只接受 `delete_row/restore_prev/release_reservation/dispose_child` 或显式 `unknown`（须带 debt 描述）；`released_at IS NOT NULL` 时必须有 `withdrawn_at IS NOT NULL` 且 release 不早于 withdraw；service `(realm,key)` partial unique 到 `released_at IS NULL`；listener `(fiber_id,episode_id,descriptor->>event,descriptor->>listener_id)` partial unique |
| `pins` | `id, consumer_fiber_id, consumer_episode_id, consumer_run_id, key, contribution_id, provider_epoch, created_at, released_at` | fiber/episode 与 run 消费者严格 XOR；`(consumer_fiber_id,consumer_episode_id,key)` 与 `(consumer_run_id,key)` 分别设 `WHERE released_at IS NULL` partial unique；consumer fiber/episode 复合 FK，`consumer_run_id → runs(id)` FK；`contribution_id` FK；provider-epoch 延迟约束触发器要求 contribution episode 的 epoch 与 frozen `provider_epoch` 相同；partial index `(contribution_id) WHERE released_at IS NULL` |
| `runs` | `id, owner_fiber_id, owner_episode_id, scope_id, parent_run_id, spawn_key, state, remaining_steps, ended_at, result` | owner 两列按设计稿均为 NOT NULL 并复合 FK 到 episode；`remaining_steps >= 0`；`UNIQUE(parent_run_id,spawn_key) WHERE spawn_key IS NOT NULL`；DP1 不推进 run |
| `effects` | `id, parent_id, ordinal, fiber_id, episode_id, run_id, kind, status, input, request_actor, claim_owner, attempt, fence, lease_until, outcome, settled_at` | kind 为 `command_install/command_reconcile/command_dispose/dispatch/listener_call/model_call/tool_call/run_start/host_io`，status 为 `ready/claimed/succeeded/failed/unknown/cancelled`；parent/ordinal 同空同非空，`UNIQUE(parent_id,ordinal)`、ordinal 0–15；B=16；attempt/fence 用 bigint、非负、`fence <= attempt` 且更新单调；outcome 非空当且仅当 succeeded/failed/unknown；settled_at 非空当且仅当 succeeded/failed/unknown/cancelled；claimed 必有 owner/lease，其他状态两列均 NULL；`model_call` 按 `run_id`、`command_reconcile` 按 `fiber_id` partial unique（仅 ready/claimed）；不可变 input/身份触发器 |

两个簿记表不计入领域表预算：

| 表 | DP1 列形状与责任 | 关键约束 |
|---|---|---|
| `requests` | `principal_id, request_key, kind, request_bytes, request_digest, effect_id, response, created_at`（沿用 v24 首次 response/replay 形状） | `(principal_id,request_key)` 主键；`effect_id` unique；指向 `effects(id)` 的 FK 为 `DEFERRABLE INITIALLY DEFERRED`；canonical bytes/digest 由 advance 校验 |
| `events` | `event_id, effect_id, seq, entity_type, entity_id, event_kind, payload`（按设计附录 A；时间戳如后续需要，须先更新规格） | entity cursor 唯一 `(entity_type,entity_id,seq)`；同 effect/entity/kind 唯一；指向 effect 的 FK 延迟检查；UPDATE/DELETE/TRUNCATE 均由 statement trigger 拒绝；seq 在 G 内按 entity 取 `max+1` |

表名/列名遵从附录 A：episode identity 列名为 `episodes.id`，不是 prose 中的 `episode_id`；这是把 §4.2 的说明名按附录 A 实际 DDL 统一为列名 `id`；所有历史 episode 复合引用目标是 `(fiber_id,id)`。`runs.owner_fiber_id` 与 `owner_episode_id` 在草图中均 `NOT NULL`，不得按 v24 nullable owner pair 放宽。`10`–`19` 表文件只创建表、列、单行 CHECK、主键与局部索引；因为 canonical order 中 `installs` 先于 `scopes`、`fibers` 先于 `episodes`，跨表 FK 全放进最后创建的 `20_relations.sql`。该文件包括 scope parent、install scope/owner、fiber install/scope/owner/current-episode、episode fiber、contribution episode/previous-contribution、pin consumer-episode/consumer-run/contribution、run scope/parent/owner-episode、effect parent/run/fiber-episode，以及 request/event→effect 的延迟 FK。episodes 的 `(fiber_id,id)` UNIQUE 是所有历史 episode 复合引用的目标；refs 不得指向可变 current projection。引用 `effects` 的 request/event FK 使用延迟检查，以便同事务内闭合。跨行 pin provider epoch 不使用 CHECK 子查询，使用延迟约束触发器和 advance 复验。

DP1 为 current 指针增加双向变更覆盖的 deferred constraint trigger：无论更新 `fibers.current_episode_id` 还是关闭目标 `episodes`，COMMIT 时 current 必须为 NULL 或指向同 fiber 的 open episode。历史 owner 引用允许指向已关闭的旧 episode，不套用 current 的 open 检查。取消的运行时转换留给后续阶段：规格只准 ready→cancelled，DP1 不实现 cancel 命令，仅 owner-seed cancelled 行，验证其 outcome=NULL、settled_at 非空及 settlement 返回 `receipt_conflict`；不把此负例当作完整取消状态机证明。

附录 A 的 `effects.resource_quiesced_at` 在 DP1 暂不建：§1.2 明确不继承其 unknown 结算细节，本阶段没有资源静默生产者或消费者；DP6 如需要，须补合同、迁移与 gate，不能以 lease 到期推断资源已静默。该推迟与省略 `token uuid` 均登记 ledger。表列类型、NOT NULL/default 以附录 A 为基线，除本计划显式修正外不弱化；例如 installs.created_at 保留 `timestamptz NOT NULL DEFAULT now()`。

### 内核接口与提交路径

新增 `v24_cordis.advance(p_effect_id uuid, p_outcome jsonb) RETURNS jsonb`，`SECURITY DEFINER`、固定 `search_path=pg_catalog,v24_cordis`，函数不 COMMIT、不做 IO。签名和外部 outcome/response 采用 v24 的精确形状：

```text
outcome: {v:1, class, claim, body, receipt_key?}
response: {v:1, disposition, effect_id, emitted, revision, claim}
```

外层必填 `v/class/claim/body`，可选 `receipt_key`；response 是六字段，勿沿用设计稿把五字段 outcome 称作“六键”的计数笔误。DP1 `revision=0`，不提供 freshness 语义、不加 revision/receipt-response 列。Oracle-adjudicated 2026-10-25：command replay **原样返回首次 requests.response**，包括其 `disposition=committed`；非 command terminal replay 构造 `{v:1, disposition:replay, effect_id, emitted:[], revision:0, claim:null}`。

command body 固定为 `{op,kind,request_key,canonical_bytes,payload}` 精确键集；`op=admit_and_apply`，kind 只接受 `command_install/command_reconcile/command_dispose`，request_key 长度 1–512，payload 必须 object。`canonical_json(payload)=payload::jsonb::text`（PostgreSQL 表示，非 RFC/JCS），canonical_bytes 为该 UTF-8 的 base64，解码字节必须精确相等，digest 为 `sha256(bytes)`。`principal_id=md5(session_user::text)::uuid`；`effect_id_for` 为 `sha256(UTF8(principal::text || ':' || kind || ':' || request_key))` 前 32 个 hex 转 UUID，与 `v24/sql/30_advance.sql:4-17` 相同，helper 为新 schema 独立实现。W3 使用下列由独立 Python hashlib/base64 算出的固定 golden vectors，不能只比较 helper 自身结果：login=`cordis_vector_service` 的 principal=`5dac475d-3b76-12b3-59c5-c8abcdabea0e`；kind=`command_install`、key=`dp1-vector-1` 派生 effect=`becfa4ba-9941-f073-26ad-ec08ef8cae3b`；payload `{}` 的 canonical base64=`e30=`、sha256=`44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a`；嵌套 payload 的 canonical text=`{"a": {"x": "你好"}, "z": [1, true]}`，base64=`eyJhIjogeyJ4IjogIuS9oOWlvSJ9LCAieiI6IFsxLCB0cnVlXX0=`、sha256=`729a79256ffe193cbf67b726a6394f0206323acc11f1ca7ee1388f61bd1a7761`。同 principal/key 的 request 必须同时匹配 stored kind、effect_id、bytes、digest 才 replay；任何不同均 `request_conflict`，错误派生 effect id 仍更早报 `effect_id_conflict`。

command/claim 的外层 claim 必须 JSON null。claim body 精确为 `{lease_ms}`，整数 1–300000；settlement claim 恰为 `{attempt,fence,owner}`，attempt/fence 为非负整数且 ≤9223372036854775807、owner 长度 1–63，不能先窄 cast 再处理溢出。缺字段、额外 command body/claim body/settlement claim 字段、base64 非法、非 canonical bytes 均 preflight `invalid_args` 且零写；settlement body 必须 object，遵守通用大小/深度/键数及 unknown 禁止执行后继的限制，生命周期专属字段语义留给后续 interpreter。

internal helper 的职责如下，均不作为写入旁路公开：

- `principal_id(session_user)`、`role_allowed(session_user,class,kind,action)`：身份来源是 `session_user`，不采信 `current_user`、GUC 或 body 自报主体。
- `effect_id_for(principal,request_key,kind)`：命令身份确定性生成。
- `error_v1(code,detail)`：只允许现有 24 个错误码。
- `interpret_command(...)`、`interpret_settlement(...)`：DP1 明确 `0A000` 的生命周期 seam。
- `validate_delta(...)`：DP1 只验证闭合 JSON/delta envelope、允许字段与数量上限、inverse op 闭集形状、successor ordinal/B=16，以及拒绝任何非空领域 mutation；不开放通用动态 SQL。真实 owner/confinement、owner-provider 联合 DAG 与清理 closure 证明属于后续 interpreter gate，DP1 不宣称已验证。测试 helper 可在 rollback-only probe 中验证 16/17 successor 数量边界，但不写领域行。
- `validate_and_apply_delta(...)`：先调用校验，再进入 empty-domain delta 的真实 receipt 写入路径；它是已实现的 production helper，不抛统一 `0A000`，不能在 gate 中替换。仅两个生命周期 interpreters 是未实现 seam。

DP1 delta 采用闭合对象 `{domain,receipt,events,successors}`：domain 和 successors 在可提交路径必须是空数组；receipt 精确为 `{status}`：command 只允许 `succeeded`，service settlement 必须与已验证 outcome.class 对应（success→succeeded、failure→failed、unknown→unknown）；它不携带另一个 outcome body，权威 receipt 从当前已验证 p_outcome 派生。不接受 SQL、表名、caller 自报 principal 或 arbitrary rows。events 是有限数组（DP1 probe 至多一条），只允许 `entity_type/entity_id/event_kind/payload`；event id/seq、effect id、principal、response 由真实 applier 生成。command applier 在同事务创建终态 command effect、写 effects.outcome/settled_at、requests 首次 response 和 event；settlement applier 更新已 claimed effect 的 outcome/status/settled_at、清 owner/lease，保留 attempt/fence，并追加 event。domain→effect/receipt→request→events→successors 的总序不变；DP1 首尾 domain/successors 无写，禁止靠测试替身直接写 requests 绕过 effect FK。完整验证后才首写，非空 domain 或实际 successor 应用返回 `invalid_outcome`（detail reason=`dp1_empty_domain_only`）且零写。结构层的 16/17、ordinal、inverse 检查可单独探针，但不承诺执行。

一次调用的数据与事务流：

1. 调用方以 `READ COMMITTED` 开启短事务。`advance` 在任何业务表读取/锁定前检查 envelope 必填字段、class、claim 形状、body ≤1 MiB、嵌套深度 ≤32、对象键总数 ≤200，以及 `unknown` 不携带 `successors/intents`；纯参数预检零写。
2. 获取事务级 `G=pg_advisory_xact_lock(24,1)`，这是首个显式应用锁；然后使用 `session_user` 计算 principal 并执行 `role_allowed`。
3. **replay target 锁和判定先于 closure**：command 先验证派生 `effect_id`，再锁 `(principal_id,request_key)` request 行并比较 canonical bytes；非 command 锁目标 effect。命令同 key 且 kind/effect_id/bytes/digest 全匹配返回首次 `requests.response`；其中任一冲突=`request_conflict`。非 command terminal receipt 两侧都排除可选 transport `receipt_key` 后比较；同 receipt=`replay`，冲突=`receipt_conflict`。错误 effect id 优先于 request replay/conflict；这些路径零写且不扫描/锁无关 closure。此序列按 Oracle-adjudicated 2026-10-25 裁决和设计稿 §3.2。
4. 仅 replay 未命中才无锁发现最多 512 个去重 typed closure 目标；再做一次 closure 行锁 pass。先前取得的目标 request/effect 锁是规格要求的 replay identity lock，不重新排序；本 pass 按 `scopes` parent-depth 再 UUID，随后 `runs/effects/installs/fibers/episodes/contributions/pins` 各表 UUID 序。缺失引用、超限或锁后 closure drift 均 fail closed，返回 `retry_with_closure`；不得在持部分锁后补锁。发现时在第 513 个不同 typed target 即停止，不能先物化无界递归结果再 count；父链环 fail closed。512 是 v24 兼容护栏，不是 Cordis 产品预算；产品 successor 上限为 B=16。request identity 行不计入 closure，append-only events 不进入 closure。
5. 锁后复验 closure、target/claim eligibility、协议预算与 delta 结构，不宣称实现生命周期 owner/run budget。claim 只对 DP1 fixture 预置 `host_io` effect 开放，不调用外部 host：ready 经静态合同 admission 后可 claim，已过期 claimed 必须再满足下文的显式 replay 权利才可重领，成功时递增 `attempt/fence` 并写 owner/lease；未过期 claim 再 claim 返回 `stale_claim` 且 detail `{"reason":"claim_busy"}`、零写。lease 到期本身不撤销旧 token，只有成功重领才使其 stale。lease 范围 1–300000 ms。`deferred` 只用于 DB barrier 未满足：返回 null claim、零写；函数返回后由调用方立即 COMMIT/ROLLBACK 结束当前事务并释放 G，不在函数内 COMMIT，也不持锁轮询。DP1 用 private barrier seam 验证该事务合同，不声称实现生命周期屏障。
6. 外部 `success/failure/unknown` 先比较 terminal receipt，再校验三元 claim；production `interpret_settlement` 继续抛 `0A000`，不写 run/pin/reducer/successor。`unknown` body 拒绝 `successors/intents`。同一原 token 在过期但未被替代时仍可提交可信 receipt。
7. command 调用 `interpret_command`。真实持久化 receipt gate 同时建立 production fixture 与 disposable probe DB，均来自 canonical loader，记录两个 interpreter 的 `pg_get_functiondef`/hash。仅在 probe DB 替换 no-op domain interpreter，并独立 COMMIT；另一连接确认替换已可见。真实 applier 保持原定义；首次 command 将 effect/outcome、request response、event 同事务 COMMIT 后关闭连接，新连接同请求必须逐字段返回首次 response，effects/requests/events/successors 计数不增加。fault-after-write 在 effect/request 已写之后抛异常，rollback 后十表快照完全相同。settlement 同样提交替身与首次 terminal receipt，再用新连接验证 receipt_key 改变仍 replay、错误 token 不压过 replay、冲突 receipt 零写、过期但未重领的原 token 首次结果仍可 COMMIT。最后按 OID drop probe DB，重读原 production DB 的函数 hash 并调用两个 interpreter，确认仍为 `0A000`；不靠第三库重建替代原库未变证明。
8. delta 先完整校验后才应用。DP1 仅接受 empty domain mutation；结构 helper 在 rollback-only test 中证明 16 successor accepted shape / 17 rejected、ordinal/unique/inverse-op 限制，不会提交真实 successor。SQL 异常传播并由调用方事务回滚；函数本身不捕获后继续。
9. `advance` 返回后由调用方 `COMMIT`。若后续宿主需外部 IO，必须确认 claim 已提交且连接 `IDLE` 才能执行；DP1 不实现 driver 或 IO。

### host_io 合同绑定与重领资格

Oracle-adjudicated 2026-10-25：保留已裁决的过期重领，但补入规格 §11 的显式 replay 资格。下列 JSON 路径是 **DP1 接缝形状假设**：`installs.contracts.host_io={contract_version,handler_digest,replay:{repeat,concurrent}}`，version 为非空字符串，digest 为小写 SHA-256 hex64；replay 两项为 boolean，缺失按 false。冻结的 `effects.input.contract` 仅保存 version/digest，不复制调用方授权。install 合同及 effect input 创建后不可变，沿 `effects.fiber_id → fibers.install_id → installs.contracts` 解析；这些引用链必须纳入首次 closure 发现与锁后复验，禁止为合同补锁。

ready 首次 claim 检查静态 owner 链/合同引用形状/version/digest 精确匹配，绑定缺失或不匹配=`invalid_args` 零写；不要求 replay 为 true，也不加载或验证真实 adapter。expired claimed 重领要求 repeat/concurrent **同时为 true**；缺失、不合法、不匹配或不足授权=`blocked_unknown` 零写，不写 status=unknown，不递增 attempt/fence，不剥夺原 token 的接纳资格。缺失的领域引用或 closure 漂移优先按 `retry_with_closure` 处理。不得从 read_only、幂等 key 或 lease 到期推断重投权利：旧外呼可能仍在执行。DP2 admission 生成此冻结引用并拒绝无所需 replay 权利的外部写能力；DP1 仅 seed 允许/禁止两种合同，不实现 adapter/恢复系统。

### 错误、并发与 ACL

DP1 沿用 v24 的 24 码闭集。活 lease claim-busy 映射到 `stale_claim` 与 detail `{"reason":"claim_busy"}`；这是相对 v24 活 lease `deferred` 行为的显式兼容偏离，deviation ledger 标记来源与影响。DP1 不新增错误码。闭集为：`invalid_args`、`unauthorized`、`not_found_or_denied`、`request_conflict`、`effect_id_conflict`、`receipt_conflict`、`stale_generation`、`registration_stale`、`already_terminal`、`owner_closing`、`install_not_ready`、`interaction_mismatch`、`provider_unavailable`、`scope_closed`、`dependency_unresolved`、`provide_conflict`、`install_identity_conflict`、`budget_exceeded`、`invalid_outcome`、`stale_claim`、`cleanup_cycle`、`retry_with_closure`、`blocked_unknown`、`spawn_key_conflict`。

DP1 仅为实际实现的协议边界提供生产者；未实现 lifecycle 的错误码在 matrix 标为“保留，DP1 无生产者”，不得标成已覆盖。闭集以外的 code 由 `error_v1` 拒绝。形状/权限/冲突错误为稳定 JSON 且零写；`0A000` 是明确的未实现 seam，不伪装成协议错误码。

fixture 维护 superuser 创建随机组与 LOGIN、template0 临时库，只向本库 owner group 授 CREATE；owner LOGIN 连接后 `SET ROLE <family_owner>`，在同一事务加载。schema 和全部对象因此归该 NOLOGIN owner group，默认函数 EXECUTE 撤权也针对该 current_user。库名固定 `v24_cordis_dp1_<pid>_<hex12>`（PID 十进制、hex 恰12小写位），角色族为 `v24_cordis_<pid>_<hex12>_*`；创建/清理均检查标识符长度≤63、精确名字/OID、非 superuser/CREATEDB/CREATEROLE/REPLICATION/BYPASSRLS，并验证 LOGIN 只属对应组。维护连接不作为协议 caller。

数据库写访问只授予 Cordis owner group 和 `advance` 的 SECURITY DEFINER 执行上下文。随机 role family 不能在 SQL 中硬编码 `v24_admin` 等固定角色名；ACL migration 与 `role_allowed` 从 `pg_namespace.nspowner` 获取经精确命名规则验证的 owner（并核对 `pg_proc.proowner`），推导三个确切 sibling 名称，核验 OID、NOLOGIN/安全属性与 membership；GRANT/REVOKE 用经核验并 quote 的标识符，OID 用于身份校验和清理，不做前缀模糊授权。caller principal 始终取 `session_user`，`current_user` 只可作为安全的 function-owner/family 发现来源。admin/service/operator 只获得 schema USAGE 与精确 `advance` EXECUTE，不获得 table DML/SELECT；PUBLIC 无 schema/table/function privilege。内核内部依 `role_allowed` 区分 command 与 service-only claim/settlement（DP1 claim 仅限预置 `host_io`）；owner DML 只用于 fixture seed 和 DDL 负例。只有 `advance` 是 SECURITY DEFINER writer，任何其他 DEFINER 只能只读且不公开。

role×class 矩阵固定：同 family 的 admin/service/operator 均可提交三类 lifecycle command（production 命中 interpreter 时仍 0A000）；仅 service 可对 DP1 host_io 提交 claim/success/failure/unknown；其余组合均 false。owner 不是协议角色，seed 用直接 DML。另建不同 suffix 的 A/B fixture，临时授 A login 对 B.advance EXECUTE 后，认证仍须拒绝跨 family。SQL 不硬编码旧 `v24_admin` 等名字。CDP1-E 断言 schema owner OID；CDP1-K 断言函数 owner、固定 search_path、DEFINER 集合、精确 EXECUTE/PUBLIC/表权限。

### DP1 与 DP2–DP6 边界

| 归属 | 能力 |
|---|---|
| DP1 | 独立环境、八张领域表、簿记表、约束/触发器、advance 协议骨架、G/身份/replay/claim/闭集错误/delta 验证接缝/有序锁 pass、DP1 gate |
| DP2 | install/admission、scope 声明后果；P0–P4 成功的 begin/iter/finish 与 contribution append；包含 L-Begin 所需最小 resolve、requires/check/provider 准入、同事务冻结 committed_view/创建带 provider_epoch 的 activation pins/更新 current；无活义务的基本 dispose（范围假设） |
| DP3 | 完整 live/失效传播、L-Divert/L-Raise、leave/unload、withdraw/release、inverse、activation/run pin release 与 drain 屏障；已激活实例 dispose 清理；不做全宿主扫描与崩溃恢复 |
| DP4 | run 创建与推进、`chat_tool` reducer、model/tool settlement、pin 使用、预算与终止状态 |
| DP5 | contribution 的 listener 注册、dispatch/listener_call、五种模式、intercept/overlay 合并及事件 refinement gate |
| DP6 | 宿主公平扫描、设计稿 §11 崩溃恢复矩阵各边界、未知资源对账、dispose 子树完整收敛、upgrade/HMR 的带排空版本切换 |

Oracle-adjudicated 2026-10-25（按评审新提供的 §10.3 S2/S3 明确证据修正初次分工）：DP2 遇 target drift、注册失败或 resolve 不满足时抛 `0A000` 并整笔回滚，不写 closing/divert/error/withdrawn_at 或部分 cleanup；这些分支与 accumulator 清理在 DP3 验收。基本 dispose 必须查实无 open episode、活 pin、未排空 run、未释放 contribution、child/host 义务；不能只看 current=NULL，install 墓碑还须检查全部所属实例。历史终态行保留。DP2 激活成功不等于安全卸载、屏障或恢复通过。

所有 DP1 已建表列和闭集值均只是数据合同，不表示对应运行时行为已实现。DP1 gate 对 typed structural validator 的 shape/B/closed-inverse 拒绝做局部证明；不能以空 delta 结果声称完成 owner/provider 联合 DAG、live、屏障、实际 inverse 或进度/恢复证明。

### DP1 gate 与强制负例

DP1 gate 使用独立命名 `CDP1-E`（环境/loader）、`CDP1-D`（DDL）、`CDP1-K`（内核协议）；不得称其为 Cordis 完整 G1–G4，也不得以其绿色冒充 v24 closeout。

| Gate | 必须具名断言 |
|---|---|
| `CDP1-E` | canonical prefix 正确；拒绝非 prefix、active/inactive symlink、未登记 SQL、目录伪装；fixture 强制 pgembed Unix socket，拒绝 TCP、hostaddr、service、多 host/port；单事务 load 后事务仍打开；schema/table/view/extension catalog 精确匹配；数据库/角色按 OID 清理 |
| `CDP1-D` | schema 恰有 8 domain + `events`/`requests` 两表、0 view、0 extension；owner、FK、partial unique、复合 episode FK、延迟 FK、append-only/immutable trigger 均满足合同（24 错误码闭集由 W3 的 CDP1-K 验证） |
| `CDP1-K` | G=(24,1) 在任何业务行锁前；envelope shape preflight 无业务读/锁/写；有效命令 effect id；同 request 同 bytes replay 首 response；同 key 异 bytes、错误 effect id 零写；terminal receipt 在 token/lease 校验前 replay；receipt 冲突零写；claim ready/活 lease claim-busy/expired lease/旧 token；调用方 rollback 撤销 claim；未提交 claim 不可见；协议角色 ACL；异常注入后全表快照一致；超 512 闭包和超过 B=16 的 successor 被拒；生产 interpreter 明确返回 `0A000` |

补充具名断言：

- DDL：current 合法/跨 fiber/已关闭 episode 三例；E1 关闭且 E2 打开后，历史 owner 仍引用 E1 正例；逐个覆盖 installs/fibers/contributions/pins/runs/effects 的跨 episode 错配。runs owner 双 NULL/单 NULL 均拒；悬空 consumer_run pin 拒绝。effects 的六状态×outcome/settled_at 真值表、非 claimed 残留 owner/lease、parent/ordinal 半空均拒。
- replay-first：request/terminal receipt 关联 closure 超过512时仍 replay/conflict，不触发 discovery；通过 test-only discovery counter 和锁竞争证明不扫描、不等待无关 closure。非 replay 512可接受、513即停止拒绝；typed 去重、缺失引用、锁后 drift 零写。锁证据分别覆盖 G→replay target 与剩余 pass，不能拿 UUID 总排序覆盖 replay 例外。
- claim：允许/禁止两种合同的首次 claim，repeat/concurrent 双真才过期重领；缺失或单项授权不足、绑定版本/digest 不匹配、合同不可变守卫。禁止重领 COMMIT 后快照不变且原 token 仍可通过 probe 提交；成功重领后旧 token 才 stale。活 lease 同 owner/不同 owner 都为精确 `stale_claim/claim_busy`。
- committed probe：替身 COMMIT 对另一连接可见；首 receipt COMMIT 后关连接、新连接重放；同 key/payload 不同 kind 为 request_conflict；fault-after-write 实际发生在 effect/request 写入之后。原 production 库 hash 与 0A000 不变。barrier probe deferred/null claim 与十表零写；结束事务后第二连接可取得 G，不持锁轮询。
- 预算：CDP1-E 硬编码断言完整15项 canonical tuple 及10–17与八表映射；CDP1-D 保守累计10–17、20、30全部物理行（含空行/注释）≤900，18/19簿记单列；CDP1-K 累计40_advance.sql 全部物理行（含全部 helper）≤1200。W4复核并写 matrix，不能移动代码到预算外隐藏超支；DP6完成时再复核最终预算。

强制负例包括：相同 request 重交、同键异字节、派生 effect id 不符、旧 attempt/fence/owner、active lease 重 claim、被取消 effect 的 settlement、unknown 携执行后继、闭集错误码外值、任何非空领域 delta（合法/非法 owner 形状均因 empty-only 边界拒绝，不声称已实现 owner 规则）、16 条之外的 successor、partial unique 冲突、episode 多 open、跨 fiber/episode FK 不匹配、pin consumer XOR 违例、provider epoch 不一致、释放早于撤销、延迟 FK 在 COMMIT 时缺 effect、events UPDATE/DELETE/TRUNCATE、协议角色直接 DML。每项必须断言 SQLSTATE/约束名或错误 JSON，并以提交后全库快照证明零写；不得用仅断言最终状态的弱证据。

### 分阶段 fixture 与门禁

W1 的 `test_environment.py` 既独立验证仅含 `00_schema.sql` 的空 schema fixture，也验证当前 `SQL_LOAD_ORDER` 对应的 catalog；W2 后后者应恰有 10 表。空 schema probe 使用临时复制的 canonical prefix 目录，不改真实 loader/manifest，避免最终全套运行时把新表误判成环境污染。catalog 排除 PostgreSQL 内建 schema 和 template0 自带 `public`/plpgsql，要求 application schema 恰 `{v24_cordis}`、无 application view/materialized view/额外 extension；不是声称整个 PostgreSQL 集群没有任何内建 extension。

每阶段重跑所有已经存在的 DP1 脚本：W1 跑 loader/self-check/environment；W2 累加 DDL；W3 累加 kernel/ACL，W4 全量重跑。W2 不调用 W3 才创建的 `error_v1`。W1 的 `00_schema.sql` 即撤销 PUBLIC schema 权限并为 owner 设置默认函数 EXECUTE 撤权；W3 将 `40_advance.sql` 与 `50_permissions.sql` 同一事务加载，避免持久化一个未授权收尾的 SECURITY DEFINER 函数。Oracle 的阶段建议把 ACL 放 W4，因 W3 必须具备可真实登录调用及拒绝裸 DML 的完整协议 gate，在此将 ACL 合并 W3；不改变裁决的架构或 manifest 顺序。

### 执行索引

| # | 工作项 | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|---|
| W1 | 基线与隔离环境 | 固定 worktree、HEAD、manifest、冻结 SQL 哈希；建立 Cordis 独立 loader/fixture | v24 11 条 closeout 及单列 s9 扩展实跑记录齐全；CDP1-E 通过；新 schema catalog 空态闭集 | `v24/cordis/load.py`、`v24/cordis/sql/00_schema.sql`、`v24/cordis/dp1/setup_db.py`、`test_environment.py`、DP1 README/matrix/ledger | 无 | M |
| W2 | 八表与簿记 DDL | 每张领域表单独 SQL 文件，建簿记表、约束、复合/延迟 FK、索引和保护触发器 | CDP1-D 的正负例全通过；表数恰 10 | `v24/cordis/sql/10_installs.sql`–`19_requests.sql`、`20_relations.sql`、`30_triggers.sql`、`v24/cordis/dp1/test_ddl.py` | W1 | L |
| W3 | advance 兼容内核与 ACL | 建立 G、身份、replay-first、claim、错误闭集、有序 closure pass、delta seam 与最后加载的 ACL | CDP1-K 协议子集全通过；只允许空领域 delta；生命周期生产 handler 保持 `0A000`；dedicated committed receipt probe 被销毁后，原 production 库函数 hash 不变且两个 interpreter 仍为 `0A000` | `v24/cordis/sql/40_advance.sql`、`50_permissions.sql`、`test_kernel.py` | W2 | L |
| W4 | DP1 closeout | 复核隔离、冻结 SQL 和 v24 基线；收尾工件定稿 | 最终 v24 11 条命令及单列 s9 扩展全 exit 0；冻结 diff 为空；CDP1-E/D/K 全绿并逐项记录 | `v24/cordis/dp1/README.md`、matrix、ledger、DP1 计划 | W1–W3 | M |

### 验证命令与收尾工件

以下命令从 v24 worktree 根目录执行。基线核验必须在首次源码变更前进行：

```bash
pwd -P
test "$(pwd -P)" = "/Users/wxl/Projects/pg-agent/.claude/worktrees/v99"
git rev-parse --show-toplevel
git branch --show-current
git rev-parse HEAD
git status --short --untracked-files=all
git fetch origin
git rev-list --left-right --count origin/v24...v24
git branch -vv
git rev-parse --abbrev-ref --symbolic-full-name '@{u}'
uname -s
uname -m
uv --version
# .venv 不存在时，先用 uv venv --python 3.12 .venv 在本 worktree 创建；
# 若存在且以下检查失败，停止，不让 uv sync 修改别的环境。
test -d .venv && test ! -L .venv
test "$(cd .venv && pwd -P)" = "$(pwd -P)/.venv"
test "$(stat -f '%Su' .venv)" = "$(id -un)"
test -e ../pgembed
test -e ../duckdb-python-pgagent/dist-special-g1/duckdb-1.6.0.dev366+ga1f0ab1911-cp312-cp312-macosx_26_0_arm64.whl
# 上述 wheel 为 cp312 / macOS 26.0 arm64；uname 不符须先解决平台依赖。
# 两个相对依赖当前是工作树旁的 symlink，核对真实目标属于预期项目源。
readlink ../pgembed
readlink ../duckdb-python-pgagent
uv sync --locked
uv run python -c "import sys, psycopg2; print(sys.executable); print(sys.version); print(psycopg2.__version__)"
uv run python -c "from v24.load import CANONICAL_ORDER, SQL_LOAD_ORDER; assert len(SQL_LOAD_ORDER) == 12 and SQL_LOAD_ORDER == CANONICAL_ORDER[:12]; print('\n'.join(SQL_LOAD_ORDER))"
```

P0 还要通过现有私有 helper 的维护连接查询实际 PostgreSQL 版本（只读，不创建应用数据库），finally 必须关闭连接并回收 helper；W1 的 Cordis self-check 固化同一查询：

```bash
uv run python - <<'PY'
import psycopg2
from v24.s1.setup_db import _server_and_base_dsn, _close_server_helper
conn = None
try:
    _, params = _server_and_base_dsn()
    conn = psycopg2.connect(dbname='postgres', **params)
    with conn.cursor() as cur:
        cur.execute("SELECT current_setting('server_version'), current_setting('server_version_num')")
        print(cur.fetchone())
    conn.rollback()
finally:
    if conn is not None:
        conn.close()
    _close_server_helper()
PY
```

P0 记录以下 12 个 SQL 文件的原始 SHA-256 到 conformance matrix，不在计划中编造哈希：

```bash
shasum -a 256 \
  v24/sql/00_schema.sql v24/sql/10_schema.sql v24/sql/20_triggers.sql \
  v24/sql/30_advance.sql v24/sql/40_interpreters.sql v24/sql/45_capability.sql \
  v24/sql/46_cleanup.sql v24/sql/47_verbs.sql v24/sql/48_loop.sql \
  v24/sql/49_recovery.sql v24/sql/49_host_reads.sql v24/sql/50_permissions.sql
```

先对 v24 loader、SQL 和既有 stage 目录执行预期 exit 0 的完整 diff：

```bash
git diff --exit-code 57e2c1e -- \
  v24/load.py v24/sql v24/s1 v24/s2 v24/s3 v24/s4 v24/s5 \
  v24/s6 v24/s7 v24/s8 v24/s9 v24/s10 v24/s11 v24/s12
```

此外，以此独立冻结核验明确 9 个冻结 SQL：

```bash
git diff --exit-code 57e2c1e -- \
  v24/sql/10_schema.sql v24/sql/20_triggers.sql v24/sql/30_advance.sql \
  v24/sql/40_interpreters.sql v24/sql/45_capability.sql v24/sql/46_cleanup.sql \
  v24/sql/47_verbs.sql v24/sql/48_loop.sql v24/sql/49_recovery.sql
```

最终再检查 v24 loader、全部 12 个 manifest SQL、v24 stage gate 均未变更；重跑 SHA-256 并与 P0 记录逐项比较。未跟踪文件不由 `git diff` 覆盖，必须用 `git status --short --untracked-files=all` 检查。

P0 和 W4 都按以下顺序实跑全部 11 条 v24 closeout，逐条记录真实退出码；另运行 `uv run python v24/s9/test_g8.py` 并单独记录（它是 s9 扩展 gate，不计入冻结 11 条），不得将历史结果写成本轮结果：

```bash
uv run python v24/load.py
uv run python v24/s1/setup_db.py --self-check
uv run python v24/s1/test_ddl.py
uv run python v24/s1/test_g1.py
uv run python v24/s2/test_g3a.py
uv run python v24/s3/test_g2.py
uv run python v24/s4/test_g2b.py
uv run python v24/s5/test_g4.py
uv run python v24/s6/test_g5.py
uv run python v24/s8/test_g7.py
uv run python v24/s7/test_g6.py
```

DP1 各工作项的独立 gate 命令：

```bash
uv run python v24/cordis/load.py
uv run python v24/cordis/dp1/setup_db.py --self-check
uv run python v24/cordis/dp1/test_environment.py
uv run python v24/cordis/dp1/test_ddl.py
uv run python v24/cordis/dp1/test_kernel.py
```

每个里程碑更新：

- `v24/cordis/dp1/README.md`：权威规格、表/函数合同、精确 gate 命令和本轮实跑退出码。
- `docs/reviews/cordis-v2-dp1-conformance-matrix-2026-10-25.md`：逐断言记录 producer、验证命令、退出码、覆盖边界；包含 12 个 v24 SQL 哈希、冻结文件 diff、v24 gate 运行记录。
- `docs/reviews/cordis-v2-dp1-deviation-ledger-2026-10-25.md`：追加记录 ABI/附录字段差异、实现偏离、测试缺陷与修正；不删除历史失败。
- 本计划：更新每个里程碑状态，不把计划写成已实施。

## 4. File-by-file impact

| 文件 | 状态与改动 | 原因与依赖 |
|---|---|---|
| `docs/plans/v24-cordis-dp1-foundation-plan-2026-10-25.md` | 修改 scaffold 为本计划，记录固定裁决、gate、边界和验证清单 | W1 前计划须可执行；与首个里程碑的 README/matrix/ledger 一起按路径提交 |
| `v24/cordis/load.py` | 新增独立 canonical-prefix loader、拒绝探针、事务内执行且不 COMMIT | W1 建立；不得改 `v24/load.py` |
| `v24/cordis/sql/00_schema.sql` | 新建 `v24_cordis` schema，固定 owner 和 schema 权限初态 | W1 先加载，W2–W3 依赖 |
| `v24/cordis/sql/10_installs.sql`–`17_effects.sql` | 各自新建一张领域表及局部约束/索引 | W2；八文件恰对应设计稿领域 SQL 预算 |
| `v24/cordis/sql/18_events.sql`、`19_requests.sql` | 新建两张簿记表；request 保存首次 response，event append-only | W2；不计领域表预算 |
| `v24/cordis/sql/20_relations.sql` | 新建完整跨表关系：owner/current-episode、consumer-run 等 FK，以及 request/event→effect 延迟 FK | W2；基础表全部创建后加载 |
| `v24/cordis/sql/30_triggers.sql` | 新建 append-only events、不可变身份、scope parent 无环、current 必须 open 及 pin epoch 延迟校验触发器 | W2；与 relations 同一 DDL gate |
| `v24/cordis/sql/40_advance.sql` | 新建 `advance(uuid,jsonb)`、identity/error helper、replay-first、bounded lock closure、interpreter/delta seam | W3 依赖完整 DDL；所有 application writer 仅此入口 |
| `v24/cordis/sql/50_permissions.sql` | 新建 schema/object ACL、精确 advance grants、PUBLIC 撤权和 fail-closed catalog 检查 | W3 最后加载；只授予随机角色族 |
| `v24/cordis/dp1/setup_db.py` | 新建 pgembed socket-only fixture、随机 NOLOGIN/LOGIN 角色族、临时库/角色 OID 跟踪、严格清理和 catalog 检查 | W1 起可跑空 schema 自检；W2 后扩展预期表集 |
| `v24/cordis/dp1/test_environment.py` | 新增 loader/DSN/事务边界/空态 catalog 自检 | W1 gate |
| `v24/cordis/dp1/test_ddl.py` | 新增 DDL 正负例、FK 与 partial unique、延迟约束和触发器 gate | W2 gate |
| `v24/cordis/dp1/test_kernel.py` | 新增 ACL、G/锁序、durable command/terminal replay、claim/barrier-deferred、empty delta 与 rollback tests；probe DB 专用并销毁 | W3 gate |
| `v24/cordis/dp1/README.md` | 新增 DP1 实施记录和独立命令 | W1 创建，后续里程碑逐项更新 |
| `docs/reviews/cordis-v2-dp1-conformance-matrix-2026-10-25.md` | 新增覆盖矩阵，区分已测、未实现、N/A 和基线证据 | W1 创建；每个 gate 后更新 |
| `docs/reviews/cordis-v2-dp1-deviation-ledger-2026-10-25.md` | 新增偏差台账，追加 schema/ABI 取舍与 gate 发现 | W1 创建；每个里程碑追加 |

以下文件显式不修改：`v24/load.py`、`v24/sql/**`、`v24/s1` 至 `v24/s12` 的既有 gate 与 README。尤其不修改 v24 12 文件 manifest 或 9 个冻结 SQL。DP1 不新建 FakeHost/journal，因为没有外部 IO。

## 5. Risks and migration

DP1 明确不是 Cordis v2 全部 G1：只交付设计稿 §10.2 G1 中 receipt/rollback 子集，以及环境/DDL/ACL 和协议 seam gate。绿色状态只记作 `CDP1-E/D/K`，不得写成完整 G1–G4 通过。设计稿 §10.2 的 G3 文字称“七处”，而 §11 崩溃矩阵实际有八个 kill-boundary 行；DP1 不执行该矩阵，DP6 必须按设计稿 §11 行数和案例逐项核对，不能沿用“七处”摘要漏测。

DP1 只新增 schema、fixture 和计划/评审文档，不迁移 v24 数据，不更改任何 v24 ABI，也不把 Cordis 表加载进 v24 schema。测试数据库是一次性临时库，部署/生产数据不在 DP1 范围内。

主要风险是 Cordis 附录 A 的 `token uuid` 与 §3.1 的三元 claim 说明不一致。Oracle-adjudicated 2026-10-25 选用 `{attempt,fence,owner}` 兼容 ABI，不新建 `token` 列或替代字段；deviation ledger 记录草图差异与影响。若未来外部 ABI 明确要求独立 opaque token，需通过规格修订和 ABI 版本迁移重新规划。

第二项风险是 DP1 空 delta 只证明接线和拒绝边界。它不证明 owner/provider 联合 DAG、真实清理 closure、pin/live 屏障、LIFO inverse 或 DP2–DP6 收敛；这些在后续 gate 验收。512 closure cap 是采用 v24 有界锁惯例的 Oracle 兼容性假设，不属于产品规格预算；若 DP2 显示实际 closure 超限，需先调整预算和 gate，再实现生命周期，不能静默放宽。活 lease claim-busy 返回 `stale_claim` 而不是 v24 的 `deferred`，也是明确记录的兼容偏离。

若任一 gate 失败，停在该里程碑，不提交或进入下一里程碑。若里程碑已推送后发现缺陷，使用前向 revert/fix commit 并推送 `origin/v24`；不 reset、不 force-push。推送拒绝时先 fetch 并审查差异；无法安全整合时停止并请求用户裁决。

## 6. Implementation order

1. **P0：环境与基线检查点，不单独提交。** 在指定 v24 worktree 逐项执行“实施环境准备”和“验证命令”：核对路径/HEAD/用户文件/upstream、`.venv` 实际归属、本地 pgembed/DuckDB 源及 wheel 平台、`uv sync --locked`、Python/psycopg2 和维护连接 PG 版本；串行使用 worktree `.pgdata` helper，按精确 OID 清理临时库/角色并回收 helper。记录12文件 manifest/哈希和冻结 diff；运行完整11条 v24 closeout **及单列 `uv run python v24/s9/test_g8.py`**（记录23/23具名ID及退出码）。基线红、依赖缺失或分支异常先查明，不开始W1；全部证据归入W1 matrix/ledger。
2. **W1：独立 loader 与 fixture。** 新建 `v24/cordis/` 目录、`00_schema.sql`、loader、DP1 fixture 和环境 gate；application catalog 只允许 `v24_cordis` schema、0 domain tables、0 application views、无新增 extension；内建 public/plpgsql 按前述规则排除。运行 `load.py`、fixture self-check 和环境 gate。通过后更新 README、conformance matrix、deviation ledger，按路径逐项 `git add`，单独 commit 并推送 `origin/v24`。
3. **W2：DDL 与约束。** 添加 `10_installs.sql`–`19_requests.sql`、`20_relations.sql`、`30_triggers.sql`，将 loader prefix 扩至 DDL 完整前缀；实现表结构和所有上述约束。逐个运行 DDL 正例/负例，并检查 catalog 恰为 8+2 张表。通过后更新 README/matrix/ledger，单独 commit 并推送 `origin/v24`。
4. **W3：内核与 ACL gate。** 添加 `40_advance.sql` 和最后加载的 `50_permissions.sql`，扩展 manifest；实现 G、认证、replay-first、闭集错误、claim/barrier seam、有序锁 pass、512 closure 护栏、B=16 检查、空 delta 验证路径和 `0A000` interpreter seam。运行 `test_kernel.py` 以及当前已存在的全部 DP1 gates。通过后更新收尾工件，单独 commit 并推送 `origin/v24`。
5. **W4：DP1 closeout。** 重跑 11 条 v24 closeout 与单列的 s9 扩展 gate；复跑冻结 SQL diff、12 文件哈希、manifest、v24 目录状态和三个 DP1 gate；将真实退出码、未覆盖项和差异写入 matrix/ledger/README。确认 `v24` 代码和既有 gate 无变更后，单独提交 closeout 工件并推送 `origin/v24`。

每个 W 都严格执行“当前全部 gate 实跑全绿→更新 loader/README/matrix/ledger→按具体路径暂存→检查 staged→commit→push”，任何一步失败即停；P0 本身不是独立里程碑。以下为实施时模板，具体源码路径按该 W 的 Key files 逐个列出，不暂存无关未跟踪文档：

```bash
git status --short --untracked-files=all
# git add <该 W 新增/修改的具体源码文件> <该 W README/matrix/ledger具体路径>
git diff --cached --name-status
git diff --cached --check
git diff --cached
# 逐文件确认不含凭据后再提交，<摘要>替换为本里程碑祈使句。
git commit -m "v24: <摘要>"
git push origin v24
```

不得 `git add -A`/`git add .`、跳 hook/`--no-verify`、提交凭据或 force-push。上游经P0核对不是origin/v24时先停止发布，不能照抄主检出的 `git push origin main`。远端先行须 fetch 审查，只有能安全整合当前 v24 分支时才 rebase；不覆盖任何用户改动，无法安全整合按仓库规则询问。任何 gate 未运行、未绿或只有历史记录时，README/matrix 明确标为未验证。计划编写时未执行以上命令；实施进展和实跑证据见本计划状态及 DP1 README/matrix/ledger。

### 静态评审与基线保真记录

2026-10-25 已完成一次有界设计评审，报告见 [DP1 critique](/Users/wxl/Projects/pg-agent/.claude/worktrees/v99/docs/reviews/v24-cordis-dp1-foundation-plan-critique-2026-10-25.md)。报告针对修订前 hash/行号，本文已吸收有代码/规格依据的问题；它不是实施 gate 或本轮测试记录。

相对 context_builder 基线的实质修正均保留原因：五文件合并方案改为八张领域表各一文件的15项manifest（§10.1）；closure-before-replay 改为 replay-first（§3.2）；活lease deferred改stale_claim（deferred仅屏障）；runs owner可空改NOT NULL（附录A）；current本地键改`(id,current_episode_id)`并补consumer_run FK；token列服从三元ABI；rollback-only receipt证明改为双库、跨连接真实COMMIT；完整owner/DAG验证改成empty-only安全边界并把运行时证明移交DP2/DP3。events.created_at 不沿用export，因为附录A未要求、游标无需该列；resource_quiesced_at未知资源细节按§1.2明确推迟，installs.created_at保留。保留了原export的全部适用环境/模型/ACL/错误/锁/负例/工项/文件/风险/收尾结构，未把详细要求压成“添加测试”。

Oracle补充裁决包含显式repeat+concurrent重领权利、revision=0和DP2激活依赖；评审新提出§10.3施工切片后，再以该证据将divert/raise归DP3。评审建议的replay_policy字符串和stale_claim/replay_not_allowed未采用，因Oracle依据§11裁决为双boolean授权及blocked_unknown；不得同时留下两套合同。移交项逐个进入实施matrix，不以静态评审代替验收。

## Open questions

无待用户裁决的产品级问题。Oracle 已裁决的工程选择与偏好假设见“固定决策与开放项裁决”及“Risks and migration”；推送 `origin/v24` 需在 P0 重新确认 upstream。若 upstream 与当前记录不符，暂停发布并按仓库协作约定处理，不自动改推 `main`。

## References

- 唯一产品规格：[Cordis v2 设计稿](/Users/wxl/Projects/pg-agent/.claude/worktrees/v99/docs/designs/cordis-plugin-system-2026-10-25.md)，重点 §1.2–§1.3、§3、§4、§10、§12.3、附录 A–B。
- 协议/数据模型对照：[v24 设计稿](/Users/wxl/Projects/pg-agent/.claude/worktrees/v99/docs/designs/v24-pg-agent-2026-10-22.md) §2–§3、§6。
- 代码证据：`v24/load.py:10-66`；`v24/sql/10_schema.sql:67-300`、`30_advance.sql:85-900`、`40_interpreters.sql:1-70`、`50_permissions.sql`；`v24/s1/setup_db.py:28-68,267-299,529-550`、`test_ddl.py`、`test_g1.py` 和 `README.md:5-33,55-80`。
- 环境与历史门禁证据：根 `pyproject.toml`、`uv.lock`、`.python-version`、`AGENTS.md`；计划/验收模板 `docs/plans/v24-s1-kernel-2026-10-23.md`、`docs/plans/v24-post-closeout-followup-2026-10-25.md`；v24 matrix/deviation ledger 与 s2–s12 README/gates。
- 外部文档：无；DP1 只依赖仓库内产品规格和现有环境/协议实现。
