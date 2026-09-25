# v13 控制面 P1–P4 实施计划（stages 17–20）· 2026-09-26

> 状态：计划。本轮零 SQL、零 commit。Oracle review 见文末「审查修订」。
> 裁决源（唯一）：`docs/reviews/v13-control-plane-oracle-r3-2026-09-26.md` §0–§3。R3 替代迁移报告 §6 倾向与 §4.1 清回目标句；D1–D3 / A15–A21 不重开。
> 分期源：`docs/analysis/v13-control-plane-migration-2026-09-25.md` §5。与 R3 字面冲突时取 R3，不得改裁。
> 冻结检查 L1：`uv run python v13/<stage>/test_*.py` 退出码 0。不得削弱、跳过、xfail 或替换。
> 本轮范围外：`v13/` 代码、stage 1–16 文件字节、`demo_v13/`、commit/push、R2/R3 条文。

## 0. 里程碑索引

依赖序 P1→P2→P3→P4。一期 = 一个 stage = 一次按路径 commit + push（AGENTS.md）。本计划轮不提交。

| 期 | stage | 目录（约定） | 硬依赖 | 新 gate |
|---|---|---|---|---|
| P1 | 17 | `v13/control/`（R3 §2 已点名） | 无（不依赖 D4） | `uv run python v13/control/test_control.py` |
| P2 | 18 | `v13/spawn/`（R3 §3 已点名） | P1 closeout | `uv run python v13/spawn/test_spawn.py` |
| P3 | 19 | `v13/fanout/`（**计划约定**，R3/§5 未给目录名） | P1 单会话 cancel + P2 树 | `uv run python v13/fanout/test_fanout.py` |
| P4 | 20 | `v13/triage/`（**计划约定**，R3/§5 未给目录名） | 不得早于 18；实施序排在 P3 后以免 `SQL_LOAD_ORDER` 争用 | `uv run python v13/triage/test_triage.py` |

目录名不是裁决。若控制器在 P3/P4 开工前指定别的目录，只改路径与 `STAGE_THROUGH` 键，不改条文。

每期完成判据（缺一不可，然后才 commit）：

1. 该期 `test_*.py` 退出码 0。
2. 回归：stage 1–16 加已交付新 stage 的全部 `test_*.py` 退出码 0。
3. `v13/load.py` 的 `SQL_LOAD_ORDER` 与 `STAGE_THROUGH` 只在末尾追加。
4. 覆盖矩阵、偏差台账、该 stage `README.md` 已更新（见 §7）。
5. `git add` 按路径；禁止 `git add -A` / `git add .`；禁止 force-push；禁止 `--no-verify`。

## 1. 前置核实

结论先行：五项均有实读或实跑证据。**未触发** R3 §5 的停工例（`spawn_kind` NOT NULL 无根值；advance 今天不写 status）。`pg_jsonschema` 可装。基线 16 stage 全绿。不因此 blocked。

### 1.1 `CREATE EXTENSION pg_jsonschema` — 可装，不挡 P1

探针（2026-09-26，与 gate 同一 `server.get_server()`，`PGDATA=/Users/wxl/Projects/pg-agent/.pgdata`）：

- 安装树有 `pg_jsonschema.control`、`pg_jsonschema--0.3.4.sql`、`pg_jsonschema.dylib`（`pgembed` `pginstall`）。
- `pg_available_extensions`：`pg_jsonschema` default_version `0.3.4`，探针前 `postgres` 库 `installed_version` 为空。
- 临时库 `agent_v13_extprobe` 上 `CREATE EXTENSION pg_jsonschema` 成功；`pg_extension.extversion = 0.3.4`。
- 探针库已 `DROP`（复查 `datname='agent_v13_extprobe'` 为 0 行）。

P1 用法（R3 §2 前置 + C4，不新裁）：`v13_control.sql` 的唯一事务内 `CREATE EXTENSION IF NOT EXISTS pg_jsonschema`。只服务 A15 `harness_result`。human 回答校验用函数内谓词，**禁止**用 pg_jsonschema 替代（C4）。装不上时停工，禁止临时 CHECK 顶替。本次探针已成功，P1 不再把「扩展缺失」当未知数；gate 仍须断言扩展在目标库存在，失败即红。

### 1.2 `v13_advance` 与 unknown 阻塞分支 — 今天**写** status，不是 §5 停工例

现文 `v13/loop/advance.sql`：

- 签名：`v13_advance(p_sid uuid, p_snap jsonb) RETURNS text`（约 L200；目录复核见 1.4 附）。
- unknown 阻塞分支（L261–264）在 `effects.status IN ('ready','claimed','unknown')` 时执行 `UPDATE sessions SET status='waiting'`，然后 `RETURN 'waiting'`。注释写明 unknown 也阻塞。
- 同函数另有多处 `UPDATE sessions SET status`（`waiting`/`failed`/`completed`，L292 起）。那些不是这条 unknown 阻塞分支。

R3 适用分支（不改裁）：

- 「今天不写 status → 不加写者、只加回归断言」**不适用**（今天写了）。
- 换体合同适用：「unknown 阻塞分支不得写 `sessions.status`」（写了会被双射触发器拒）。新体这条分支只 `RETURN 'waiting'`，删掉 L263 那种写者。
- 不加漂移修理、不改步 0 stale（C2 / 继承条款）。其他分支的 status 写只按 R3 点名的新增行为改（A15、审批、steer）；不借本次换体重写未点名语义。
- 换体用 stage 17 `CREATE OR REPLACE`，**不改** `advance.sql` 字节。stage 1–16 前缀测试仍跑旧体。

### 1.3 `v13/load.py` 不是 stage 单事务 — stage 17 必须自包 `BEGIN`/`COMMIT`

证据：

- `run_psql`（`v13/load.py:61-70`）调用 `psql`，无 `-1` / `--single-transaction`。
- `load_stage`（L73-84）每个 SQL 文件一次 `psql`，把文件全文当脚本。
- psql 默认逐语句 autocommit，除非脚本自带 `BEGIN`/`COMMIT`。
- 自带一对（或多对）`BEGIN`/`COMMIT` 的文件：envelope、manifest、chunks、recall、characterize、filter、memory、economy、summary、periphery、mgraph（六对）、mgraph_assembly。
- 无文件级 `BEGIN`：`schema/v13_core.sql`、`resolve/v13_resolve.sql`、`loop/advance.sql`、`twophase/v13_twophase.sql`（各文件开头实读）。

因此 R3 C3 的条件成立：stage 17 **必须**在 `v13_control.sql` 内显式包一对 `BEGIN`/`COMMIT`，且全文件只一对（不要学 mgraph 拆成多事务）。回填、断言、触发器、函数换体、扩展创建都在这一对里面。这是 C3 已写的分支，不是证伪。

### 1.4 `v13_fork` 签名与 `spawn_kind` 可空性 — 未证伪

SQL：

- `v13_fork(p_parent uuid, p_cutoff bigint, p_kind text, p_overrides jsonb DEFAULT NULL) RETURNS uuid`（`v13/periphery/v13_periphery.sql:311-314`）。
- `ALTER TABLE sessions ADD COLUMN spawn_kind text CHECK (spawn_kind IN ('exact_replay','recompute','fresh_fork'))`（L44-45）。无 `NOT NULL`、无 `DEFAULT`。`schema/` 内零 `spawn_kind`。

目录（基线绿之后的 `agent_v13_periphery`，同一嵌入式实例）：

- `is_nullable = YES`，`column_default` 空，`attnotnull = f`。
- CHECK 为三值 `ANY`，不禁 NULL（CHECK 对 NULL 为通过）。
- 根行：`parent_session_id IS NULL AND spawn_kind IS NULL` 24 行；根行非空 `spawn_kind` 0 行。

R3 §5 停工例「`spawn_kind` NOT NULL 无根值」**未发生**。P2 `v13_open_session` 可按已裁形状插根行且不写 `spawn_kind`（保持 NULL）。P1 不改 periphery 文件、不换 `v13_fork`。

附：stage 16 库上的换体签名（实施时不得改）：

| 函数 | 现加载末次定义 | 签名 → 结果 | 本期动作 |
|---|---|---|---|
| `v13_advance` | `v13/loop/advance.sql` | `(uuid, jsonb) → text` | P1 `OR REPLACE`；不改旧文件 |
| `v13_complete` | `v13/schema/v13_core.sql:300`（全树仅此一处 `CREATE`） | `(uuid, int, bigint, text, jsonb) → text` | P1 `OR REPLACE`；签名不变 |
| `v13_requeue_stale` | 初定义 `twophase` L33；末次体 `v13/mgraph/v13_mgraph.sql:2665` | `() → jsonb` | P1 `OR REPLACE`；签名与返回键/计数不变 |
| `v13_fork` | `v13/periphery/v13_periphery.sql:311` | `(uuid, bigint, text, jsonb) → uuid` | P1 不动；P2 与新函数同属主，不改此文件 |

`sessions.status` CHECK 已含 `blocked_unknown`（`v13/schema/v13_core.sql:14-15`）。P1 不 `ALTER` 该 CHECK（那会改 stage 1 文件）。

### 1.5 现有 16 stage 测试清单与 gate 粒度

每个 stage 一个 `test_*.py` + 一个 `setup_db.py` + 一个 `README.md`。测试自调用 `setup_db()`（`DROP/CREATE` 本 stage 库，`load_stage` 只加载到本 stage）。粒度 = 一个 stage 一份场景脚本，不是 pytest 单函数。命令均为仓库根 `uv run python v13/<dir>/test_<dir>.py`，退出码 0 = 过。

| # | 目录 | 脚本 | 模块 docstring 粒度 |
|---|---|---|---|
| 1 | `schema` | `test_schema.py` | M1：core slice + scaffolding。97 `check(` |
| 2 | `resolve` | `test_resolve.py` | M2：parse / resolve_judgments / envelope |
| 3 | `loop` | `test_loop.py` | M3：`v13_advance` 五步 |
| 4 | `twophase` | `test_twophase.py` | M4：G-ctx1 + G-ctx8 parse-phase + 慢路 |
| 5 | `envelope` | `test_envelope.py` | DP2：judgment envelope & decision cache（含 G-ctx7） |
| 6 | `manifest` | `test_manifest.py` | DP3：manifest skeleton / freshness / 三 epoch（含 G-ctx9） |
| 7 | `chunks` | `test_chunks.py` | DP4：chunks projection & span assembly |
| 8 | `recall` | `test_recall.py` | DP5：T0 tsvector recall + TINQL + envelope/assemble |
| 9 | `characterize` | `test_characterize.py` | DP5：stannum characterize + T0 definition swap |
| 10 | `filter` | `test_filter.py` | DP6 M1：existence-Noul + Score + 跨会话复用。组 A–H |
| 11 | `memory` | `test_memory.py` | DP6 M2：transcript verbatim + watermark。组 I–N |
| 12 | `economy` | `test_economy.py` | DP7 M1：定价/分位/G-ctx6/花费闸。组 A–H |
| 13 | `summary` | `test_summary.py` | DP7 M2：summary effect 面 + assembly v3 |
| 14 | `periphery` | `test_periphery.py` | DP8：latch/render/fork/shadow/intent。组 A–I。130 checks |
| 15 | `mgraph` | `test_mgraph.py` | DP9：G-mg 组 A + 写/重建组。278 `check(` |
| 16 | `mgraph_assembly` | `test_mgraph_assembly.py` | B2 组 J：assembly wiring。W1–W3 |

新 stage 沿用此粒度：一目录一 `test_*.py`，组名用 R3/§5 已点名的 gate，不拆成 pytest。

### 1.6 基线回归（stage 1–16）— 全绿，不挡后续

实跑窗口：2026-09-25T16:39:50Z–16:42:03Z（UTC；本地 2026-09-26）。仓库根逐个 `uv run python v13/<dir>/test_<dir>.py`。日志在进程临时目录，不入库。16 个日志无 `FAIL` 行。

| stage | 目录 | 退出码 | 秒 | 日志尾 |
|---|---|---|---|---|
| 1 | schema | 0 | 2 | `[M1 schema] ALL PASS` |
| 2 | resolve | 0 | 6 | `[M2 resolve] ALL PASS` |
| 3 | loop | 0 | 10 | `[M3 loop] ALL PASS` |
| 4 | twophase | 0 | 7 | `[M4 twophase] ALL PASS` |
| 5 | envelope | 0 | 8 | `[envelope] ALL PASS` |
| 6 | manifest | 0 | 7 | `[manifest] ALL PASS` |
| 7 | chunks | 0 | 10 | `ALL PASS` |
| 8 | recall | 0 | 10 | `ALL PASS` |
| 9 | characterize | 0 | 7 | `ALL PASS` |
| 10 | filter | 0 | 14 | `ALL PASS` |
| 11 | memory | 0 | 7 | `ALL PASS` |
| 12 | economy | 0 | 8 | `ALL PASS` |
| 13 | summary | 0 | 8 | `ALL PASS` |
| 14 | periphery | 0 | 7 | `ALL PASS (130 checks)` |
| 15 | mgraph | 0 | 14 | groups A+D+E+F+G+H: `ALL GREEN` |
| 16 | mgraph_assembly | 0 | 8 | `ALL J GREEN` |

此后每期回归以此表为基线行。基线红才停；本次不红。

### 1.7 C3 装载顺序的计划读法（不改裁）

R3 C3 箭头：单事务内 ①回填 `ready|waiting` 且存在 unknown → `blocked_unknown`（幂等，`RAISE NOTICE` 行数，不写事件）→ ②断言不存在「`blocked_unknown` 且零 unknown」与「`ready|waiting` 且有 unknown」，违例 `RAISE` 附 `session_id` 并中止 → ③`completed|failed|cancelled` 且有 unknown 只 `NOTICE` 不改行 → ④`DROP TRIGGER IF EXISTS` 后建两个 `DEFERRABLE INITIALLY DEFERRED` 约束触发器 → ⑤回填→断言→触发器→函数换体必须同一事务提交。

括号句「先挂触发器再换函数会出现旧 complete 写 unknown 不抬墙被触发器拒的窗口」：本计划读成**原子性理由**（该顺序若拆成两次已提交事务就会出现窗口），不是另一套相反的语句序。实施按箭头，全放在一对 `BEGIN`/`COMMIT` 里。触发器是延迟的，提交时函数体已经换完。

若审查认定括号句是独立禁令、与箭头冲突，则本节作废，P1 不得开工，回来改 R3，不在实施里选边。

## 2. 每期都适用的约束

- 新 SQL 只追加 `SQL_LOAD_ORDER` 末尾。对既有函数只在新文件 `CREATE OR REPLACE`。stage 1–16 文件字节不动，含测试与 README。
- 测试用 Fake / 库内夹具，不调真实 provider（AGENTS.md 不变量 4）。
- `v13/load.py` 的 `files_through` 按 `STAGE_THROUGH` 截断。stage 1–16 测试看不到 17+ 的换体与触发器。不要为了让旧测试「跟上新语义」去改它们。
- P2 的 `BEFORE INSERT` 触发器只出现在 stage 18 文件。stage 1–16 测试文件保持字节不动：它们按前缀加载，库里没有 stage 18 的 INSERT 触发器，也没有 `v13_open_session`，文件里的直插仍然合法。stage 18 落地时，加载路径包含 stage 18 及以后的既有测试与 fixture，凡直插 `sessions` 的都改走 `v13_open_session`；同期新测试也只走 `v13_open_session`。若这些既有 fixture 的源码在 stage 1–16 文件里、不能改字节，则在 stage 18+ 测试里用适配层替换建会话路径，不得在已加载 stage 18 的库上继续 `INSERT sessions`。做不到就停下来报告，不改 1–16 文件，也不改 R3。
- 新函数：`REVOKE` PUBLIC 后 `GRANT v13_route`；不授 `v13_resolve`（R3 §2 交付清单第 11 项）。P2 的三入口另属专用 NOLOGIN 属主（R3 附 D4），不在 P1 提前做。
- 事件 `type` 零 DDL（开放词表）。不要建 `v13_agent_run`、不要建 quota 表、不要建 `passive_posthoc`（迁移 §6「明确不新裁」；R3 未重开）。
- 外部 IO 不进事务。P3 的 FS effect 只登记，不在 SQL 事务里碰文件系统。
- 撞上需改 R2/R3 的冲突：停，报告，不自行换裁。

## 3. P1 · stage 17 `v13/control/`

### 3.1 目标

单会话控制动词：unknown 墙与双射、D6 审批载荷、A16 无子会话 closeout、单会话粘性 cancel、`v13_advance` 换体（A15 + 审批恰一个 human + unknown 分支不写 status）。不做 spawn、唯一写路径、扇出、worktree、triage、quota 新事件、demo 接线。

### 3.2 交付物

新文件（不改 1–16）：

- `v13/control/v13_control.sql` — 一对 `BEGIN`/`COMMIT`
- `v13/control/setup_db.py` — `DB=agent_v13_control`，`STAGE=control`，模式同 `v13/schema/setup_db.py`
- `v13/control/test_control.py`
- `v13/control/README.md`
- `v13/load.py` 末尾追加 `control/v13_control.sql`，`STAGE_THROUGH["control"]=17`

`v13_control.sql` 清单（R3 §2，顺序服从 §1.7）：

1. `CREATE EXTENSION IF NOT EXISTS pg_jsonschema`
2. 部分索引 `effects(session_id) WHERE status='unknown'`
3. `v13_raise_unknown_wall(p_sid)`：调用方已按 session→effect 持锁；`ready|waiting` 且有 unknown → `blocked_unknown`；已 blocked 或终态不改；绝不清墙。a1/a1' 不调。
4. `OR REPLACE v13_requeue_stale()`：先无锁收集候选 → 按 `session_id` 升序 `FOR UPDATE` sessions（不用 `SKIP LOCKED`）→ 谓词重检后更新 effects → a2 实改到的 session 调 helper。返回 jsonb 键与计数不变。终态 effect 进墙不 `RAISE`。
5. `OR REPLACE v13_complete(...)`：签名不变。unknown 出口在 `UPDATE` 后、返回 accepted 前调 helper；judge 显式结算成 unknown 也抬墙；replay/stale/llm 形状降级 failed 不调。human succeeded 走 C4/C5（见下）。
6. `v13_resolve_unknown`：effect 半边按 R3 对 §4.1 的替代 + C1。关闭该会话最后一条 unknown 且 `status='blocked_unknown'` 时：存在 `kind='human' AND status IN ('ready','claimed')` → `waiting`，否则 `ready`。仍有其他 unknown → 保持 `blocked_unknown`。终态 resolve 只动 effect 不动 status。
7. A16 无子会话 closeout：三事件 + 收据；顺序 = ①已终态先短路重放已有 `session/*`（不查计数）② `active=0 AND unknown=0 AND pending human=0` ③ `status<>'blocked_unknown'`。同事务。不二次扣预算。终态允许 unknown 残留。任何生产者不得把终态改成 `blocked_unknown`。
8. `v13_cancel` 单会话：终态 → replay；已有未消费 `cancel/requested` → replay 不二插；否则追加一条。本会话 ready effect → cancelled（fence+1，attempt 不动，error 空）。claimed/unknown 不动。**不改 `sessions.status`**。
9. `OR REPLACE v13_advance`：A15 四值 / wait 词表 / wake / material spend（schema 字面消费 R2 A15 与 R2 L17–72 已裁，不在本计划发明字段；对不上就停）。`wait_reason=approval` 时本会话已有 `kind='human' AND status IN ('ready','claimed','unknown')` → `RAISE` 零新 effect，否则入队 human，request 冻结四键 `{schema_version:1, interaction_ref, prompt?, interaction_kind?}`。unknown 阻塞分支不写 status。claimed 期间 request 不变（steer）。步 0 stale 保持。
10. D6 谓词 + 表达式唯一索引 `UNIQUE (session_id, (request->>'interaction_ref')) WHERE kind='human' AND request ? 'interaction_ref'`。
11. C4：`kind='human' AND p_status='succeeded'`，在终态 replay / CAS/fence **之后**校验。`schema_version` JSON 数字 1；`interaction_ref` 文本且与冻结 request 字节相等（不等则 `RAISE`，消息含提交值与当前值，行与事件零变化；request 无 ref 也拒）。恰一通道：`response`（btrim 非空 string，或非 null number/boolean；false/0 合法）XOR `answers`（≥1 键 object）XOR `skip` JSON true。`skip=false` 视为缺席。空串 / `{}` / 数组 / object 型 response / 字符串型 skip = 非法存在，优先于互斥计数拒绝。未知键拒绝。失败 = `RAISE` 回滚，不烧 attempt/fence，不写 `human/responded`，不把 effect 打成 failed。三种合法通道都按 succeeded 结算；skip 不记 failed。
12. C5：同事务、同一 session 锁，恰一条 `human/responded`。payload = `{schema_version:1, interaction_ref, skip, response|null, answers|null, origin_user_seq}`。未用通道为 JSON null。`origin_user_seq` 抄 effect 行，不重算。正文同时留 `effects.result`。failed/unknown 不写。终态守卫重放不追加第二条。不授 recall 对 effects 的 `SELECT`。
13. `GRANT`/`REVOKE` 如 §2。
14. cancel / complete / requeue / `v13_append_event` 的 user/message 复位一律不清 `blocked_unknown`。

明确不做：sessions `INSERT` 触发器、`v13_open_session`、`v13_spawn_subsession`、`v_goal_tree`、`v13_recover_idle`、cancel 扇出、worktree、triage。

### 3.3 Gate

脚本：`v13/control/test_control.py`。命令：`uv run python v13/control/test_control.py`。退出码 0 才算过。断言名必须出现在输出里（沿用现有 `check("名", ...)`），至少：

- G-ctx10-delivery（含 `interaction_kind` / `delivery_kind` 轴：乱填 `delivery_kind` 不改变是否建 effect）
- wait-lexicon（含 approval 恰一 human）
- wake（缺 wake 则拒且零事件）
- spend（同 logical turn material ≤1；progress+repair 零 spend）
- G-ctx10-approval-payload（C4 决策表逐行，含 false/0、空串、`{}`、未知键、双通道）
- G-ctx10-approval-ref（mismatch 消息带 current=；fence stale；replay 不泄露通道错误；耗尽 ref 再入队拒）
- G-wall-session-status
- G-resolve-clears-overlay（含 human 例外 → waiting；G4：只有 `v13_resolve_unknown` 能离开 unknown）
- G-cancel-does-not-unwall
- G-closeout-unknown-authority（计数权威 + 重放短路 + 终态残留可重放；回滚则无 `session/completed`；二次 closeout 不追加第二条终结事件）
- G-user-message-keeps-wall
- G-wall-no-parent-write
- 双射触发器正负例：单边改后真实 `COMMIT` 必败（不要只测函数内 `RAISE`）
- 锁序并发：complete / requeue / renew 无死锁
- `SET ROLE v13_recall` 可读 `human/responded`，且不能 `SELECT effects`
- 审批全程 `sessions.status` 无审批词
- 扩展存在：`pg_extension` 有 `pg_jsonschema`

回归：§1.6 的 16 个命令再跑，退出码全部 0。前缀加载语义不变。

### 3.4 验收判据

§3.3 全绿，且 §7 三件工件已按 P1 行更新，然后按路径 commit + push。提交信息形如 `v13: add control-plane stage 17`。

### 3.5 依赖

无 D4。不读 §6 倾向 A「P1 不要抢跑写 blocked_unknown」——该句已被 R3 D5 替代。清回目标用 C1（`ready`，human 例外 `waiting`），不用迁移 §4.1 旧句。

## 4. P2 · stage 18 `v13/spawn/`

### 4.1 目标

D4 整包 + A17 spawn + 目标树 + `v13_recover_idle`。子终态走 P1 closeout，不新增 status。

### 4.2 交付物

- `v13/spawn/v13_spawn.sql`（一对 `BEGIN`/`COMMIT`）
- `v13/spawn/setup_db.py`（`DB=agent_v13_spawn`，`STAGE=spawn`）
- `v13/spawn/test_spawn.py`
- `v13/spawn/README.md`
- `SQL_LOAD_ORDER` / `STAGE_THROUGH["spawn"]=18` 只追加

内容（R3 §3 + §1 附 D4 + 继承条款，不超出）：

- `v13_open_session`：`p_spec` 只允许 `route_policy_name` / `version`，非法键 `RAISE` 零行。根行 parent/cutoff NULL、`status=ready`、`turn_no=0`、`next_seq=0`。不复制 latch、不占 reserved、不取咨询锁、不写出生事件、不接受调用者 `session_id`、**不注册 tools 行**。不写 `spawn_kind`（可空，§1.4）。
- `v13_fork` / `v13_open_session` / `v13_spawn_subsession` 同一专用 NOLOGIN 属主，`SECURITY DEFINER`，固定 `search_path`，`REVOKE` PUBLIC。三函数与两个业务登录角色均无 `sessions` INSERT。`BEFORE INSERT` 触发器：`current_user <> 属主` 则 `RAISE`。否决 GUC。超级用户 `session_replication_role=replica` 不补机制。
- `tools` 行 `spawn_subsession`，`kind=sql`，`mutating=false`。guard 换体的例外条件用 R2 §2.2 已有程序，不许「有 write_targets 就放行」。不进 VOLATILE 具名例外的扩员若要登记 tools = 重开 D2，本计划不重开。
- `v13_spawn_subsession`：DEFINER；两参咨询锁只在准入路径；准入是查询聚合（非终态子孙 `max_turns` 之和 + requested ≤ 剩余），**不加 `sessions.reserved` 列**。
- `v_goal_tree(root)`。
- `v13_recover_idle`：排除墙 / `blocked_unknown`。含「子齐父未验收」与未消费 repair/replan。子 closeout 事务内零父事件。
- `blocked_unknown` 在 P2 是非终态：占 reserved 合计、`v13_recover_idle` 排除、不得当 idle 恢复。非终态定义 = `status NOT IN ('completed','failed','cancelled')`。
- 会话出生：加载路径含 stage 18 及以后的既有测试、fixture 与本期新测试，凡直插 `sessions` 的都走 `v13_open_session`（§2）。stage 1–16 文件仍不改。

### 4.3 Gate

`uv run python v13/spawn/test_spawn.py` 退出码 0。输出中至少：

- G-spawn-unique-writer（三函数名单 + 运行角色直插拒 + 误授 INSERT 仍无令牌可直插）
- G-open-session-shape
- G-sql-write-closed
- G-spawn-fanout（N 个 tool_call 要么 N 子要么零子）
- G-ctx1-spawn（持锁毫秒级；超限改函数，不改回队列）
- 双根互不占预算
- 墙上子会话仍计入非终态合计
- 并发 sibling 无超售；spawn 前后父 `turn_no` 不变
- 子 closeout 后一次 recover 把父扫进验收，第二次零新 effect

回归：stage 1–17 全部 `test_*.py` 退出码 0。

### 4.4 验收与依赖

工件 §7 的 P2 行。提交形如 `v13: add control-plane stage 18`。依赖 P1 closeout。不在 P2 做 cancel 扇出、worktree、triage。

## 5. P3 · stage 19 `v13/fanout/`

### 5.1 目标

cancel 同事务扇出 + A19 worktree。R1.14：任何 mutating 外部 harness 启用前必须完成本期。本计划不启用 harness。

目录名是约定（§0）。SQL 文件 `v13/fanout/v13_fanout.sql`，测试 `test_fanout.py`，库名 `agent_v13_fanout`，`STAGE_THROUGH["fanout"]=19`。

### 5.2 交付物（迁移 §5 P3 字面 + R3 D5 对 mutating 中断的一句）

- `allowlist.interruptible ∈ {required, best_effort, unsupported}`，零新列。
- `v13_cancel` 换体为同事务扇出：祖先优先，同层 `session_id` 升序。P1 单会话行为对无子会话保持。终态子孙零扇出。
- fake 第四务 = A18 worker 控制订阅（迁移报告 §2 / R2 A18 已裁，不在本计划发明订阅协议）。测试 fake 实现，不调真实 provider。
- A19：latch + `worktree_binding` artifact。prepare/merge/release = FS effect（事务内只登记，不碰 FS）。子不复制 binding。无 binding 拒 claim。prefix identity 默认排除 worktree。
- mutating 中断若把 effect 写成 unknown，同事务调已有 `v13_raise_unknown_wall`（R3 D5）。cancel 不能改掉该 unknown。
- SQL 文本不得出现 `pg_terminate_backend`。

G6 的 ch08 断言清单不在 R3 §0–§3。P3 实施第一步读 ch08 / R2 已列 G6，把断言写进 `test_fanout.py`。若 ch08 与 R3 D5（mutating 中断抬墙、cancel 不改 unknown）冲突，停，不改裁。本计划不发明 G6 新条。

### 5.3 Gate 与判据

`uv run python v13/fanout/test_fanout.py` 退出码 0，外加 stage 1–18 回归。输出至少覆盖：

- required：收到 `cancel/requested` 后 settle cancelled
- unsupported：跑完被粘性吸收
- mutating 中断 settle unknown，且 cancel 不能改掉它；会话墙被抬起
- 无 binding：零执行
- 终态子孙：零扇出
- 源码扫描：无 `pg_terminate_backend`

### 5.4 验收

工件 §7 P3 行。提交形如 `v13: add control-plane stage 19`。依赖 P1+P2。

## 6. P4 · stage 20 `v13/triage/`

### 6.1 目标

A20 triage。10a 不依赖树，但 R2 §9 禁止 10b 早于 spawn，故不得早于 stage 18。与 P3 不并行。null 树字段不点火。

目录约定：`v13/triage/v13_triage.sql`，`test_triage.py`，库名 `agent_v13_triage`，`STAGE_THROUGH["triage"]=20`。

### 6.2 交付物（迁移 §5 P4 字面）

- 消费 `goal/override`（ch01 已登记；不新造事件类型）。
- 阶梯 1–7（R2 §3.2；实施时读该节，不在本计划重写阶梯）。
- explore = 同会话 llm + 只读，不占 depth/reserved。
- Jev 只产 `Choice{direct,decompose,human}`。

### 6.3 Gate 与判据

`uv run python v13/triage/test_triage.py` 退出码 0，外加 stage 1–19 回归。已点名 gate：

- G-triage-action-closed（`thresholds.action` 仍六值）
- G-triage-explore-depth
- G-triage-evidence-hash
- G-triage-10a-null-tree（null 树不点火）

判据：override 打穿预算 → 零 child + human；已探索仍 review → human；根上无 Jev 证据不得 SQL-direct。

### 6.4 验收

工件 §7 P4 行。提交形如 `v13: add control-plane stage 20`。硬依赖 P2；实施序在 P3 之后。

## 7. 收尾工件

v13 尚无控制面覆盖矩阵与偏差台账（`docs/reviews/` 仅有 v8 的同名体例）。P1 创建，其后每期只追加，不另起文件。

| 工件 | 路径 | 每期做什么 |
|---|---|---|
| 加载序 | `v13/load.py` | 末尾追加一项 `SQL_LOAD_ORDER` + 一项 `STAGE_THROUGH` |
| 覆盖矩阵 | `docs/reviews/v13-control-plane-conformance-matrix-2026-09-26.md` | P1 创建。行 = 本期 gate 名 → 测试脚本路径 → 状态。对照 R3 §2/§3 与迁移 §5，不对照一份新发明的规格 |
| 偏差台账 | `docs/reviews/v13-control-plane-deviation-ledger-2026-09-26.md` | P1 创建。无偏差就写「本期无偏差」。有偏差必须是已暴露的实现差，不是预写的许可 |
| README | `v13/<stage>/README.md` | 本期目标、gate 命令、退出码约定、不做清单 |

矩阵列：`# | 条文（R3/§5 锚点）| 状态 | 测试落点 | 缺口`。状态只用 ✅ / 🟡 / ❌。不要把未跑的回归写成绿。

## 8. 开工建议

前置五项与基线均未 blocked。C3 按 §1.7 读法可实施（审查未判冲突）。**建议下一轮开始 P1，不要并行 P2–P4。**

## 9. 审查修订

第一轮 `ask_oracle` mode=review（2026-09-26，导出 `prompt-exports/oracle-review-2026-09-26-005416-new-chat-018660-836c.md`）。三车道里两车道报告计划正文未进选区，故 gate 命令与里程碑条款未逐句核对；能核对的三点结论如下，已按必须修订改过本文：

- C3：箭头 = 安装事务内语句序，括号句 = 拆交易时的失败窗口，不是另一套顺序。不冲突，P1 不必停工。§1.7 保留。
- stage 19/20 目录名 `fanout` / `triage` 标成计划约定，可接受。不冒充裁决。
- P2 必须修订（已改 §2 与 §4.2）：不得把「既有直插改走 open」收成「只适用于新测试」。stage 1–16 文件仍不改；加载路径含 stage 18+ 的既有测试与 fixture 也要改走 `v13_open_session`。源码在 1–16 文件里的，用 stage 18+ 适配层替换建会话路径；做不到则停，不改裁、不改旧文件。

第二轮 review（导出 `prompt-exports/oracle-review-2026-09-26-010535-new-chat-ec6eab-dc1e.md`）复述了修订后的适配层原句。主车道结论：**无必须修订**。gate 命令可照跑；R3 §2/§3 已点名 gate 都在名单里；P3「G6 不发明、冲突则停」可接受；里程碑符合 AGENTS.md。一车道建议把 `wait-lexicon`/`wake`/`spend` 改成 `G-ctx10-` 前缀。不采纳：R3 §2 原文是 `G-ctx10-delivery/wait-lexicon/wake/spend`，前缀不重复。
