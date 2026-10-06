# v17：SBCL worker（jiti 内核 × v12 表 × postmodern/pgembed）方案

日期：2026-10-06。状态：**设计稿，待评审冻结**，零代码。
调查对象：`v12/`（Jev 进 pgembed 的极简 agent，8 表 5 gate）、
`~/Projects/jiti`（ghuntley/jiti，~2000 行 SBCL 协作式内核）、
`~/Projects/pgembed`（本地打包 PG 18.4，含 pgmq / pg_typesafe）。

---

## 0. 一句话

**v17 = 按路径只读加载 v12 的 7 个 SQL（血统惯例，v12 零修改），
用 SBCL worker 全量替代 Python `QueueWorker`，并把 jiti 的文件 store
移植为 Postgres 表（postmodern 连接 pgembed）——jiti 的「活 image
里长函数」能力由此进入 v12 的 effect 纪律，状态全部落 Postgres。**

分工不变式沿用 v12：**SQL 管算术与顺序，Jev 管语义与判断，LLM 只管
生成，SBCL 管执行与演化。** SBCL worker 是 v12 G6 queue 模式的第二种
worker 实现（第一种是 Python），外加一类 Python 做不到的新 effect：
在持久 Lisp world 里 develop/execute。

## 1. 为什么是 worker，为什么可行（调查结论）

- v12 G6 的 worker 协议**本来就与语言无关**：轮询 pgmq `v12_work`，
  消息 `{"kind":"jev"|"job","id":uuid}` 只是唤醒；答案经
  `v12_record_answers`（'ready' CAS 去重）落库，job 经
  `v12_claim_job`/`v12_complete_job`（fence/lease）落库；
  `v12_requeue_stale()` 从表重建积压。全部是 SQL 函数调用——
  postmodern 直接可调，无需任何 C 扩展。
- jiti 的内核与 store 是**干净分层**：`kernel.lisp`（426 行）只认
  world adapter 接口（snapshot/restore/export/import/managed-state/
  catalogue）和 store 操作（publish/load/list/rollback/append-journal）；
  `store.lisp`（164 行）是唯一碰文件系统的地方。**换掉 store.lisp
  等于把全部状态搬进 Postgres，内核零改动。**
- jiti 的 `CURRENT` 指针原子 rename + fsync 之舞，在 Postgres 里
  **坍缩成一次 COMMIT**（revision INSERT 与指针 CAS 同事务）——
  `publication-error` 的 uncertain 窗口消失，崩溃语义反而变强。
  唯一残留的 unknown 是「commit 后连接断」，那正是 v12 G3 的
  unknown 墙 already 管的。
- jiti 暂停/修复（restart 活栈）**不可持久化**，jiti 自己也如此
  （单 worker 线程持有 dynamic extent）。v17 不试图超越：崩溃即
  checkpoint 恢复 + job unknown。这是明示边界，不是缺陷。

## 2. 环境（由本方案定夺，已实测主机）

主机：macOS arm64，brew 7.0.4 在；**sbcl / nix / devenv 均不在**。
pgembed 18.4 已在 pg-agent uv 环境实测可用（v12 gate 同款运行时）。

| 组件 | 安装 | 说明 |
|---|---|---|
| SBCL | `brew install sbcl` | 不用 jiti 的 nix/devenv（主机没有，不引入）。版本漂移由 revision manifest 里的 `lisp-implementation-version` 钉死（移植 jiti 同款检查），漂移=响亮失败 |
| Quicklisp | 项目本地 `v17/lisp/quicklisp/`（非交互 bootstrap），dist 版本记入 `v17/lisp/quicklisp-lock.txt` | 不装 `~/quicklisp`，不污染宿主 |
| Lisp 依赖 | `postmodern`（纯 Lisp 线协议，无 C FFI）、`dexador`（HTTP→OpenRouter）、`yason`、`babel`、`fiveam`、`check-it` | 与 jiti 选型一致；postmodern 替代 jiti 不需要的 DB 层 |
| OpenSSL | `brew install openssl@3` | dexador/cl+ssl 走 HTTPS 需要；gate 的 `env` 显式导出库路径，不依赖宿主默认 |
| pgembed | 已装 | `setup_db.py` 复用 v12 模式：`pgembed.get_server` + DROP/CREATE `agent_v17_<stage>` |

worker 启动：gate 用 `sbcl --non-interactive --load quicklisp/setup.lisp
--eval '(asdf:load-system "v17/worker")' --eval '(v17-worker:main)'`
（PGURI 走环境变量，凭据不落盘）；生产可选
`sb-ext:save-lisp-and-die` 出 core 加速冷启动——非 gate 要求。

### 2.1 环境实测结果（2026-10-06，已跑通握手）

SBCL 2.6.9 + 项目本地 quicklisp 已装好；postmodern→pgembed 冒烟全绿
（select/jsonb 双向/pgmq create-send-read-archive/advisory lock）。
四条实测教训，实现必须遵守：

1. `postmodern:connect` **不**设 `*database*`——一律
   `postmodern:with-connection` 包 worker 主循环（动态绑定天然按线程
   隔离，契合每 world 线程一条连接）。
2. quicklisp load 与对已载入包的符号引用**不得同处一个顶层 form**
   （READ 在 EVAL 前）：`--script` 文件里 quickload 单独成 form。
3. pgmq 函数有重载（42725 歧义）：参数一律显式 cast，
   如 `pgmq.archive($1::text, $2::bigint)`。
4. pgembed server 寿命 = 持有它的 Python 进程（atexit 回收，`-h ""`
   仅 unix socket，socket 在数据目录）。gate 模式：Python 父进程
   get_server → fork sbcl 子进程（env 传 `PGSOCKETDIR`/`PGDATABASE`）
   → 断言 → 退出。注意本机 `/tmp/.s.PGSQL.5432` 属于别的实例，
   连接一律走 socket dir 不认端口。

## 3. 新增 SQL 面（v17 自己的 2 个文件，末尾追加）

`v17/load.py`：`SQL_LOAD_ORDER = [v12 的 7 个文件（按相对路径只读引用）]
+ v17/store/v17_store.sql + v17/world/v17_world.sql`。v12 的 8 张表与
全部函数**零修改**。

### 3.1 `v17_store.sql` —— jiti 文件 store 的表化（4 张表）

| jiti 文件工件 | v17 表 | 备注 |
|---|---|---|
| revision 目录 + `manifest.sexp` + `world.sexp` | `lisp_revisions(revision_id uuid PK, world_id, seq int, parent_id uuid NULL, state_text text, manifest jsonb, sbcl_version text, rollback_source uuid NULL, created_at)` | `state_text` 即 `*print-readably*` 的 world 状态（数据 + defun 源码），与 jiti `world.sexp` 同构 |
| `CURRENT` 文件 + rename | `lisp_current(world_id PK, revision_id REFERENCES, updated_at)` | 指针 CAS 与 revision INSERT **同事务**，jiti 的两阶段 fsync 消失 |
| `events.sexp` journal | `lisp_journal(world_id, seq int, operation_id text, generation int, event jsonb, created_at)` | seq 每 world 无洞：advisory lock 下 `max(seq)+1`（对齐 v12 events 纪律） |
| （jiti 无对应物） | `lisp_worlds(world_id uuid PK, name text UNIQUE, package_name text, created_at)` | world 注册表 |

函数：`v17_publish_revision(world, state_text, manifest) → uuid`
（INSERT + CURRENT CAS 一体，供 worker 在**单个事务**里与
`v12_complete_job` 一起提交）；`v17_load_revision(world[, rev])`；
`v17_list_revisions(world)`（移植 jiti 的祖先链/序号连续性校验）；
`v17_append_journal(...)`；`v17_recover_operations(world)`
（running→interrupted 折叠，移植 `recover-operations`）。

**所有权**：jiti 的 `ownership-lock`（进程内 mutex）升级为
`pg_advisory_xact_lock(hashtext(world_id))`——跨进程单主，崩溃自动
释放。同一 world 的 job 序列化经 worker 内 mailbox（jiti 同构）。

### 3.2 `v17_world.sql` —— world 操作进入 effect 总线

**不加新 pgmq 消息 kind、不加新表。** world 操作就是 job：

- `tools.handler = 'lisp:<函数名>'` → tool 路由到 world 求值器；
- `jobs.kind = 'lisp_eval'`：payload `{"world":<id>,"source":"..."}`
  （execute，可 preview）；
- `jobs.kind = 'lisp_develop'`：payload `{"world":<id>,"source":"...",
  "goals":["(= (twice 2) 4)",...],"invariants":["...",...]}`——
  goals/invariants 是 caller 供给的可执行检查（jiti 验收合同移植：
  未过 goal 允许安全中间进展，违反 invariant 拒绝并恢复 checkpoint）。

## 4. SBCL 侧结构（`v17/lisp/`）

```
v17/lisp/
  v17.asd            系统定义（serial，对齐 jiti 分层）
  src/kernel.lisp    jiti kernel 移植：world/session/attempt/checkpoint/
                     condition-loop/mailbox/generation 防陈旧（重写，见 §7）
  src/pgstore.lisp   store 接口的 postmodern 实现（替换 store.lisp）
  src/pgmq.lisp      pgmq.read/archive/set_vt 轮询协议
  src/jev.lisp       dexador → OpenRouter /api/alpha/decisions；
                     请求对象直接取 v12_request_payload 的 JSON
  src/llm.lisp       LLM effect（jiti openai.lisp 思路，Responses API）
  src/worker.lisp    main loop：pump 移植（语义逐条对齐 queue_worker.py）
  tests/*.lisp       fiveam 单元套件（store/form 校验/mailbox）
```

worker 主循环语义**逐条对齐** `v12/queue_worker.py`（VT=180s、
RETRY_VT=2s、MAX_READ_CT=5、瞬时失败 set_vt 重投、确定性失败置
failed + archive、'ready' CAS 去重、stale 唤醒直接 archive）。
差异只有 job 执行分支多一条 `lisp:` 路径：

```
claim(fence/lease) → 取 world 所有权 advisory lock → mailbox 投递
→ world 线程 attempt()：checkpoint → eval → goals/invariants
→ 成功：同一 DB 事务 [v17_publish_revision + v12_complete_job] COMMIT
→ 失败：restore checkpoint + v12_complete_job('failed')
→ 崩溃：lease 过期 → 他 worker reclaim；effect_id 幂等保证可见效果至多一次
→ 已做外部副作用后崩溃：unknown 墙（v12 G3 原样）
```

## 5. Stage / Gate（gate 全绿才可提交，逐 stage 末尾追加）

约定同 v12：`uv run python v17/<stage>/test_<stage>.py` 退出码 0 = 过；
`setup_db.py` DROP/CREATE `agent_v17_<stage>` 库。Python gate 负责
编排：起 pgembed、载 SQL、fork SBCL worker 子进程、断言库内状态。

| Stage | Gate | 内容 |
|---|---|---|
| G1 store | `v17/store/test_store.py` | DDL；publish/load/list/rollback；祖先链腐坏检测（序号断、parent 断、环）；**并发发布单赢家**（两连接同事务竞 CAS）；**崩溃无半截 revision**（kill -9 子 SBCL 于 INSERT 后 COMMIT 前 → CURRENT 不动、无孤儿行）；journal append + recover-operations；sbcl 版本不匹配拒绝加载 |
| G2 world | `v17/world/test_world.py` | reference world 跑在 pgstore 上：twice 示例、preview 恢复、出错回 checkpoint、unrecorded defun/fmakunbound 拒绝、**managed-state 跨进程字节一致**（capture 向量入库比对）、catalogue 源码 export→import 后行为相同；内嵌 fiveam 套件在本 gate 内跑 |
| G3 queue | `v17/queue/test_queue.py` | **v12 G6 七场景对 Lisp worker 原样重跑**（瞬时 VT 重投 / 重复唤醒去重 / read_ct≥5 置 failed / requeue_stale 恢复 / LLM+护栏 / 多 turn 不串轮）；**jsonb 往返 canary**（postmodern `$1::jsonb` cast 怪癖早发现）；**跨语言混跑**：Python 与 Lisp worker 同抢一队，CAS 保证不双答 |
| G4 lisptools | `v17/lisptools/test_lisptools.py` | `handler='lisp:...'` job 端到端；崩溃于 claim 后 complete 前 → 租约过期 → 第二 worker reclaim → **可见效果恰好一次**（world 内计数器断言）；unknown 墙：工具在第二连接写哨兵行后自杀 → job unknown → `v12_resolve_unknown` 两路解决 |
| G5 develop | `v17/develop/test_develop.py` | agent 长工具全链路：INSERT 提问 → driver 路由 → mock LLM 产出 defun（lisp_develop job）→ goals 过 → catalogue 可见 → 下一 turn 的 tool job 路由到新 Lisp 函数 → 交付；坏 revision 被 invariant 拒绝 + 恢复；显式 rollback 后函数消失；**杀 worker 换新进程，函数仍可调用**（Postgres 即恢复面） |
| G6 repair | `v17/repair/test_repair.py` | 带 restart 的错误 → condition 菜单经 journal 出栈 → 同 worker 提交 repair form + resume → 原调用完成；崩溃于暂停中 → checkpoint 恢复 + job unknown（断言明示边界，不假装持久化活栈） |

崩溃场景沿用 jiti `tests/crash-child.lisp` 模式：子进程写 pidfile，
Python gate 定点 SIGKILL，再起新 worker 断言恢复路径。

## 6. 与既有版本的关系

- **v12**：7 个 SQL 按路径只读加载（Line B 惯例），零修改；Python
  QueueWorker 保留为参考实现与 G3 混跑对手。
- **v15/v16**：无依赖、不加载其 SQL（不同主题线；v16 目前仅计划稿，
  v17 与之编号相邻但无血统关系——本仓库版本号从不表谱系）。
- **v8 不变量血统**：外部 IO 不进事务（HTTP 全在事务外，只有结果行
  入库）；DB 扫描可恢复（requeue_stale 不动）；FakeX 测试（Lisp
  fake-jev 按 request_hash 键控 + mock LLM，全程离线确定性）；
  append-only、fence/lease、unknown 不盲目重放。

## 7. 风险与开放问题

1. **jiti 无 LICENSE 文件**（仓库根无 LICENSE/COPYING，README 未提）。
   策略：**重写不复制**——内核 426 行、store 164 行，移植的是架构与
   语义（checkpoint/mailbox/generation/验收合同），代码自写。
   开放问题：是否问上游要授权以便日后直接引用。
2. **postmodern jsonb 参数怪癖**：jsonb 一律 SQL 侧 `$1::jsonb`
   显式 cast、返回按 text 收再 yason:parse；G3 canary 先行。
3. **postmodern 连接不可跨线程共享**：每 world 线程各持一条连接；
   单主假设下无需连接池。
4. **brew SBCL 版本浮动**：manifest 版本钉死 = 响亮失败；gate 输出
   记录 `lisp-implementation-version`。
5. **dexador/cl+ssl 在 macOS 的 OpenSSL 路径**：gate env 显式导出，
   不赌宿主默认值。
6. **暂停活栈不可持久化**（§1）：G6 断言崩溃路径，文档明示。
7. 开放问题：jiti 的 controller/chat 层（工具循环本身）是否日后也
   移植 Lisp，让 SBCL 不只是 worker 而是 controller？**v17 不做**——
   状态机留在 SQL（v12 基线不动），controller 仍是 Python driver。
   留作 v18 候选。

## 8. 不做的事（防范围蔓延）

- 不改 v12 任何 SQL/函数/表；不加新 pgmq 消息 kind；
- 不引入 LISTEN/NOTIFY（轮询已够，与 Python worker 对齐）；
- 不持久化 restart 活栈；不做跨 SBCL 版本加载 revision；
- 不移植 jiti 的 terminal/launch/实验层；
- 不在 v17 做 Lisp 侧 controller（§7.7）。
