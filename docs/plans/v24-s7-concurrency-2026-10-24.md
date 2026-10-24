# v24 S7 三面并发矩阵：Deep plan

- 状态：**S7 计划稿；G6 未实现、未运行、未验证**。本文件只冻结施工形状，不宣称 S7/G6 已实现或已绿；G6 的绿必须由未来 `v24/s7/test_g6.py` 的实跑输出产生。
- 工作树：`/Users/wxl/Projects/pg-agent/.claude/worktrees/v99`；branch `v24`；HEAD `90b233e`。S1–S6、S8 已实现；既有 10 个 gate 命令绿（见 §8），G6 是唯一未验收 gate。
- 上游权威：设计稿 §7 L377–405、§9 L429–449、§B.1 L491–518、§B.2 L519–532、附录 C.6 L756–784；pre-plan S7 卡 L194–207、§6.2 L268–272、§7.2 L301–309、§7.3 L313–315。
- 阅读顺序：§2 边界 → §3 映射 → §4 harness 形状（承重） → §5 18 格 + 9 负例 + 5 锁序 → §6/§7 风险与裁决。任何与设计稿不一致处集中在 §6.5/§7，不静默改规格。
- **计数口径（强制）**：设计 §7 表是 **6 个行类型 × 3 个生命周期列 = 18 格**；§9 G6 的“9 条”是 **9 条强制负例**，不是 9 个 §7 行。本计划不新增 §7 行、不改 §9 负例；若有人认为“9 行”另有所指，见 §7 O-S7-1，停手请求设计修订。

---

## 1. 执行索引

| 项 | 内容 |
|---|---|
| Goal | 按设计 §7 的 18 格与 §9 的 9 条强制负例，用**两个真实连接 + 屏障/held-G + `pg_blocking_pids()`** 证明六动词/loop 与 install/activate、deactivate/retire、dispose 三面的两提交序；G6 作为 v24 的阶段总验收收口。 |
| Done when | ① `uv run python v24/s7/test_g6.py` 无参数 exit 0，`G6-A…H` 的 16 条矩阵子断言（A1；B1–B3；C1–C3；D1；E1；F1；G1–G3；H1–H3）、`G6-N1…N9`（9 条）、`G6-L1…L5`（5 条）每个 tag 的结果行恰出现一次，合计 30 条 ID；② 18 格每格都有“既有证据 + S7 动作”落位，无空格；③ 9 条负例全部有双连接证据，能两序的必须两序；④ §6.4 的已知缺口按“断言或显式债务”归类；⑤ 既有 10 个 gate 命令逐条重跑 exit 0，加 G6 为 11/11；⑥ `v24/sql/**` 与 `v24/load.py` 无改动、产品 SQL digest 不变；⑦ `v24/s7/README.md`、conformance matrix、deviation ledger 更新；⑧ 单一里程碑提交留给控制器。 |
| Key files | **NEW** `v24/s7/g6_support.py`（屏障/held-G/快照/证据 helper）、`v24/s7/test_g6.py`（G6 gate）、`v24/s7/README.md`（运行/证据/债务）。**只读复用**：`v24/s1/setup_db.py`、`v24/s2/test_g3a.py`、`v24/s3/test_g2.py`、`v24/s4/test_g2b.py`、`v24/s5/test_g4.py`、`v24/s6/g5_support.py`、`v24/s8/test_g7.py`。**不改** `v24/sql/**`、`v24/load.py`、设计稿、pre-plan。 |
| Dependencies | S1：`advance` 单入口、G=`pg_advisory_xact_lock(24,1)`、B.1 锁向量、request/receipt、ACL。S2：install/fiber/episode/slot/pin 与 activation/run pin。S3：run/generation/interaction/`fiber_control`。S4：model/tool claim/settle、batch barrier、pending_steer、cancel×T2。S5：dispose/close 闭包、owner 级联、`scope_closable`。S6：`command_recover` 与恢复共享合同（本计划只消费，不重测崩溃）。S8/C16：spawn 同事务、`spawn_key_conflict`、owner pair。**G6 不得先于 G7 收口**；S7 不依赖新的产品合同。 |
| Size | M：2 个 W；预计 `g6_support.py` 250–350 行、`test_g6.py` 650–850 行；**0 行产品 SQL**、0 个新 SQL 文件、0 个新错误码。 |

**本文件是 plan only**：不创建 `v24/s7/**` 的任何代码文件，不运行 G6，不 commit/push；本轮唯一新增文件就是本计划。

---

## 2. 定位与边界

### 2.1 S7 在阶段序列中的位置

pre-plan 的顺序是 `S1 → S2 → S3 → S4 → S5 → S6 → S8 → S7`；S8 的 spawn/child-run 与 G7 已实现，S7 是最后一个阶段，G6 是阶段总验收。S7 不新增领域状态，也不重新证明 G1–G5/G7 的串行窗口；它只回答一个问题：

> 当六动词/loop 的写命令与 install/activate、deactivate/retire、dispose 的写命令在**两个真实连接**上以任意顺序提交时，结果是否严格符合 §7 矩阵与 §7.2 的两次提交序规则，且没有死锁、没有锁序外等待、赢家由 G 决定？

G6 的绿必须建立在 G1–G5/G7 已绿之上；G6 红不能通过修改其它 gate 的断言来“修绿”。

### 2.2 发布/消费的合同

| 编号 | 生产 | 内容 | S7 的消费方式 |
|---|---|---|---|
| C-G6-1 | S1 | `advance` 是唯一写口；G 是首锁；B.1 锁向量；ACL/授权前置 | 所有 G6 写都经真实公开 wrapper/`advance`；断言 waiter 先等 G，不在 G 前拿 v24 关系锁 |
| C-G6-2 | S2 | activation pin / run pin XOR；episode 生命周期；slot withdraw/release | start/stop/dispose 格的 pin、slot、episode 字节断言 |
| C-G6-3 | S3 | run 状态机、generation、interaction、`fiber_control` / `cancel` / `steer` / `respond` | 六动词行的真实命令；两序的 generation/CAS 断言 |
| C-G6-4 | S4 | model/tool claim/settle、T1/T2、batch barrier、pending_steer | model/tool advance 格的 T2 两序；响应/成本/后继计数 |
| C-G6-5 | S5 | dispose 闭包、owner 级联、scope close、`disposed`/`closed_at`/`resource_quiesced_at` | dispose/close 格的 tombstone 时机；不重开清理语义 |
| C-G6-6 | S6 | `command_recover`、recovery outcome、无第二状态机 | 只在需要“迟到 receipt 不复活”时消费既有恢复写类；不重测 K1–K10 |
| C-G6-7 | S8/C16 | spawn 同事务、`(parent_run_id,spawn_key)` 唯一、第 24 码 `spawn_key_conflict` | N9 的 same-key/different-bytes 交叉；不重做 G7-A…H |
| C-G6-8 | pre-plan C15 | 双连接 + 屏障 + `pg_blocking_pids()` 的证据格式 | G6 的唯一并发证据形式；`sleep` 与非双连接证据一律无效 |

**发布**：18 格证据矩阵、9 条负例矩阵、5 条锁序/死锁审计、跨面合同一致性结论；每格“已覆盖/新断言/仅重跑”的明确标注。
**消费**：S1–S5 的领域合同、S6 的恢复写类、S8 的 spawn/quota；不修改 C1–C16 任何一条。

### 2.3 明确不做

- 不新增表、列、索引、视图、函数、SQL 文件、错误码；`error_v1` 保持 24 码闭集，loader 不变。
- 不做推测性产品修复；**若某条 G6 断言证明真实锁序/顺序 bug，先 stop and report first**，由控制器决定是否开设计修订与产品变更；本计划不写投机 SQL。
- 不用 `sleep` 猜顺序；不用单进程线程/同连接两事务冒充并发；不用“命令成功”代替先后证据。
- 不覆盖 §7 未列举的组合；不把 18 格扩成 21 格，也不把 9 条负例改写成 §7 行。
- 不重做 G2b-O/G3b-4/G3b-5/G4-G/G4-P/G7-N1/N2 的完整语义；只做“关键交点”的重跑或新增并发断言。
- 不证明真实 provider/adapter、网络、跨主机 lease、分布式锁、租户沙箱、公平/无饥饿；这些是设计 §10 的边界或显式债务。
- 不把 `poll/wait` 读请求升级为写路径；读请求必须零写、无 G、无 tuple/relation 锁。
- 不创建 `v24/s7/setup_db.py`；复用 S1 的唯一建库/清理入口，避免第二套数据库生命周期。
- 不在本轮 commit/push；单一里程碑提交由控制器执行。

### 2.4 G6-only 边界

G6 **只**回答“三面写命令的两提交序 + 锁序”是否成立；它不重新定义 §6 的清理偏序、不重新定义 §5 的 loop 语义、不重新定义 §8 的崩溃恢复。断言失败时的处置只有三类：

1. **夹具/断言缺陷**：修 `v24/s7/**` 测试，不改产品；同 gate 重跑。
2. **设计缺口/不可判定**：该格标“未验证”，在 §6.4 记为显式债务；不得用更弱断言或 `sleep` 伪造通过。
3. **真实产品锁序/顺序 bug**：**stop and report first**；不写投机修复、不改既有 gate 断言；等控制器裁决。

---

## 3. 设计 § → 里程碑 → G6 映射

| 设计锚 | 内容 | 工项 | G6 |
|---|---|---|---|
| §7 L383–390 | 6 行 × 3 列 = 18 格的两提交序结果 | W1 | G6-A…H 覆盖全部 18 格 |
| §7.1 L381 | `F-off` / `R-cancel` / `T1` / `T2` 的读法；poll/wait 无提交序 | W1 | 全 G6 的术语与断言口径 |
| §7.2 L394–396 | start 与 activate 无 episode 时 start 失败零 run；activate 后 start 成功并 pin | W1 | G6-A1、G6-N1 |
| §7.2 L396 | run pin 与 deactivate 的线性化由 G；不得“检查时未 pin、提交后 pin” | W1/W2 | G6-C2、G6-H2、G6-L2 |
| §7.2 L398 | T2 与 cancel/steer：先落地事实保留，旧 generation 不续链 | W2 | G6-N8、G6-N3 |
| §7.2 L400 | cancel 先/retire 后与 retire 先/cancel 后；pin 保留至 IO 静默 | W2 | G6-N5 |
| §7.2 L402 | owner retire/dispose 与 child install 两序；`owner_closing` 零 child | W2 | G6-N7 |
| §7.2 L404 | respond 与 cancel/steer 的 generation CAS 与赢家 | W2 | G6-N2、G6-N4 |
| §9 L440 | G6 done-when：六动词、install/control/dispose、IO receipt 全受 G；9 条强制负例 | W2 | 全 G6 + N1…N9 |
| §9.1 L444 | 独立 setup + SQL 前置；Fake；两连接 + 屏障 + `pg_blocking_pids()` | W1 | `g6_support.py` 与每个断言 |
| §9.1 L446 | G6 穷举命令间双提交序；最终 status 不够 | W1/W2 | 每格两序 + 表 diff |
| §B.1 L495–509 | G → request → scope → run → effect → install → fiber → episode → slot → pin → event 锁向量 | W1 | G6-L1…L5 的锁向量审计 |
| §B.2 L519–531 | 五个死锁反例与“无 deadlock、无 blocking-pids 环、赢家由 G 决定” | W2 | G6-L1…L5 |
| C.6 L756–784 | spawn 同事务、owner pair、第 24 码 | W2 | G6-N9（只做交点重跑） |
| §10.3 L484–485 | 全序锁无环是最脆弱假设；有死锁或锁后补锁即失败 | W2 | G6-L1…L5 的失败条件 |

---

## 4. DDL/函数草案与 G6 harness 形状

### 4.1 明确声明：没有新 DDL/函数/错误

| 项 | 本计划 | 验收证据 |
|---|---|---|
| 表/列/索引/视图 | **0** | `git diff --exit-code -- v24/sql`；DDL gate 不变 |
| SQL 函数/存储过程 | **0** | `v24/load.py` 的 `SQL_LOAD_ORDER` 不变；无新 `v24/sql/51_*.sql` |
| 错误码 | **0**（保持 24 码闭集） | G1-A 不变；G6 只产生既有码 |
| 产品 SQL 变更 | **0** | `sha256sum v24/sql/*.sql` 前后一致 |
| loader | **不变** | `uv run python v24/load.py` 通过；无未登记文件 |

**唯一例外**：如果某条 G6 断言以两个真实连接稳定复现了真实锁序/顺序 bug，**stop and report first**；在控制器批准设计修订前，不写任何产品 SQL，也不以测试夹具绕过。批准后的修复属于独立修订，必须重跑 11/11，不并入本计划的“证据”。

G6 的“函数草案”因此不是 SQL，而是 **test harness 的可执行形状**：连接、屏障、held-G、快照/diff、证据行。它们全部是测试代码，不进 `v24/sql/**`。

### 4.2 文件与职责

| 文件 | 类型 | 职责 |
|---|---|---|
| `v24/s7/g6_support.py` | **NEW** | 只放并发原语与夹具：`snapshot`/`diff`、`held_g`、`wait_for_g_block`、`assert_no_wait_cycle`、`held_open_then_probe`、`two_orders`、证据格式化。不得含产品语义或 SQL DDL。 |
| `v24/s7/test_g6.py` | **NEW** | G6 gate 本体：`g6_a1()`…`g6_h3()`、`g6_n1()`…`g6_n9()`、`g6_l1()`…`g6_l5()`；`main(argv)` 与 `--only`；末行 `[passed]`。 |
| `v24/s7/README.md` | **NEW** | 运行命令、证据索引、18 格/9 负例映射、未验证/债务清单。 |

选择 `v24/s7/` 而不是塞进 `s4/s5/s8`：① 与 S1–S8 的 stage 目录一致；② G6 是阶段总验收，不能寄生在某个被验收 stage 的测试文件里；③ 不新建 `setup_db.py`，复用 `v24/s1/setup_db.py`，避免第二套建库/清理；④ 只新增 Python 测试，不触碰 loader。

### 4.3 连接、隔离与夹具

- 入口：`with server_helper_scope(), setup_db() as db:`；`owner = db.connect()`，`SET ROLE v24_owner` 后 commit；`service = db.connect("service")`、`admin = db.connect("admin")` 用 LOGIN 角色；观察者 `observer = db.connect()`，`autocommit=True`。
- 每个断言一个全新 realm/scope/run/install；不复用上一断言的 domain 行；每个断言在 `finally` 关闭自己打开的连接，`owner` 最后 `_assert_closed_catalog(owner)`。
- 参与者连接**一线程一连接**；写事务在返回 response 后**不 commit**，保持 G 的 transaction-scoped 锁；观察者只读 `pg_stat_activity`/`pg_locks`/`pg_blocking_pids()`。
- 所有写都走真实公开 wrapper（`v24.start`/`cancel`/`steer`/`respond`/`fiber_control`/`dispose`/`scope_control`/`advance`），不直接 DML 产品表；seed 只在 owner 侧、且只用于构造初始状态。
- `install_no_network()`/`restore_no_network()` 复用 `v24/s4/test_g2b.py` 的 socket guard；G6 不开网络、不调 provider、不写文件。
- 每个断言先做**前置不变量**：目标 install/fiber/episode/slot/pin/run 的初始状态逐列断言；再做两序；再做提交后的最终 diff。没有“前置不成立但继续跑”的分支。

### 4.4 屏障/held-G API（精确形状）

| helper | 来源/签名 | 行为与证据 |
|---|---|---|
| `concurrent_actions(participants, tag, timeout=10)` | 复用 `v24/s4/test_g2b.py` | 两线程同一 `threading.Barrier(2)`；各自 commit；返回 `{label: response}`。用于两个都提交的对称竞争。 |
| `serialized_race(db, participants, tag, deadline_seconds=10)` | 复用 `v24/s4/test_g2b.py` | 两线程同一 Barrier；先返回者保持事务、G 仍持有；观察者用 `pg_blocking_pids()` + 未授予 advisory `pg_locks` 证明后者在等 G；`release` 后两者 commit；返回 `(winner, response, results, evidence)`。 |
| `ordered_advance_race(db, first, second, tag, deadline_seconds=10)` | 复用 `v24/s4/test_g2b.py` | `first` 先跑并返回（不 commit，G 保持）；`second` 后跑，必须阻塞在 G；证据同上；用于“指定第一序”的格。 |
| `held_g(conn)` | **NEW** `g6_support` | `SELECT pg_advisory_xact_lock(24,1)`；用于显式占 G 的对照/负例；返回 pid。 |
| `wait_for_g_block(observer, holder_pid, waiter_pid, tag, deadline=10.0)` | **NEW** | 轮询 `pg_blocking_pids(waiter_pid)` 与 `pg_locks(locktype='advisory', NOT granted)`，**不使用 sleep**；断言 `holder_pid = ANY(blockers)`、`ungranted_advisory >= 1`、holder `pg_stat_activity.state='idle in transaction'`、waiter 线程仍存活；返回 `{holder_pid, waiter_pid, blocking_pids, ungranted_advisory}`。 |
| `assert_no_wait_cycle(observer, pids, tag)` | **NEW** | 读 `pg_blocking_pids()` 建 wait-for 图（两节点），DFS 断言无环；同时断言 waiter 在获得 G 前没有任何 granted 的 `v24` 关系锁/行锁；失败即“锁后补锁/反序”。 |
| `held_open_then_probe(conn_writer, writer_action, reader_conn, reader_action, tag)` | **NEW** | writer 执行并返回（不 commit，G 保持）；主线程在第二连接跑 poll/wait 读；断言 `pg_blocking_pids(reader_pid)='{}'`、reader 无 advisory/tuple/relation 写锁、reader 前后十表快照相等；然后释放 writer。专用于 poll/wait 三个读格。 |
| `two_orders(db, first, second, tag)` | **NEW** | 对可交换的两序依次调用 `ordered_advance_race(db, ...)`，输出 `order=first->second` 与 `order=second->first` 两条证据；任一序未产生预期的 G 阻塞即 fail，不跳过、不采样替代。 |

G 的精确身份（`classid=24,objid=1,objsubid=2`）与 advisory wait 已由 **G1-L1/L2**（`v24/s1/test_g1.py`，`[G1-L1/L2 / Done 8]`）证明；G6 不重复该断言，只在 L1–L5 复用其 `pg_locks` 查询形状并加“关系锁/环”检查。

### 4.5 夹具复用表

| 夹具/helper | 来源 | G6 用途 |
|---|---|---|
| `loop_fixture`、`start`、`cancel`、`steer`、`respond`、`claim_effect`、`settle`、`advance`、`read`、`run_row`、`effect_row` | `v24/s4/test_g2b.py` | 六动词/loop 的真实命令与行读取；start/claim/T2 的 response/receipt |
| `pin_barrier_fixture`、`barrier_start`、`barrier_off`、`assert_barrier_state`、`dispose_and_settle` | `v24/s3/test_g2.py` | start/off/dispose 的 install/fiber/episode/slot/pin 初始状态与 tombstone 推进 |
| `start_tool_run`、`settle_tool_batch`、`produce_waiting_interaction`、`pending_steer_*` | `v24/s4/test_g2b.py` | tool batch、waiting interaction、pending_steer 的交叉夹具 |
| `installed_fixture`、`prepare_unknown_fixture`、`new_child_scope`、`admit_install`、`close_scope`、`scope_row`、`scope_closable`、`dispose`、`settle_release` | `v24/s5/test_g4.py` | N6 的 installed/prepare_unknown；N7 的跨 scope child install；dispose/close 状态 |
| `make_parent`、`spawn_args`、`_spawn_outcome`、`child_counts`、`next_parent_model` | `v24/s8/test_g7.py` | N9 的 spawn 同 key 同/异 bytes 交点；只复用 fixture，不复制 G7-A…H |
| `g5_snapshot`、`snapshot_diff`、`fingerprint` | `v24/s6/g5_support.py` | 十表全列全行快照、W0/W1 diff、zero-write sha；`g6_support` 把它们暴露为 `snapshot()`/`diff()` 两个薄包装，不复制实现 |

### 4.6 证据行格式

每次“第一序 + 第二序”至少打印一行；同一 tag 的结果行只出现一次，附加证据用 `-lock`/`-zero`/`order2` 后缀，不重复计数。

```text
[G6-<ID>] holder=<role:pid> waiter=<role:pid> blocking_pids=<{pid,...}> ungranted_advisory=<n> order=<first->second> diff=<table:+added/~changed/-removed,...> assert=<一句话可证伪结论>
[G6-<ID>-zero] sha=<十表 fingerprint> diff=zero-ten-tables assert=<W0 零写>
[G6-<ID>-lock] wait_graph=<pid->{blockers}> cycle=false advisory_only=true winner=<first|G>
```

示例（未来实跑时才允许出现真实 pid/哈希）：

```text
[G6-N1a] holder=service:41231 waiter=admin:41237 blocking_pids={41231} ungranted_advisory=1 order=start->dispose diff=runs:+0/~1,pins:+1/~0,effects:+1/~0 assert=start pin blocks dispose; dispose pending, not disposed
[G6-N1b] holder=admin:41244 waiter=service:41251 blocking_pids={41244} ungranted_advisory=1 order=dispose->start diff=runs:+0,installs:+0/~1,effects:+1/~0 assert=disposed tombstone first; start provider_unavailable W1, zero run
```

`diff` 由 `snapshot_diff(before, after)` 压缩：`+a/~c/-r` 分别是 added/changed/removed 行数；W0 用 `[G6-X-zero] sha=...`，不列每表 0 行。`holder`/`waiter` 统一 `role:backend_pid`；`blocking_pids` 打印 `pg_blocking_pids(waiter)` 的原始数组。poll/wait 读格（B1–B3）把 writer 记为 `holder`、reader 记为 `waiter`，并断言 `blocking_pids={}`（读者不取 G），这是该格的“无等待”证据而不是省略证据。两序负例把 tag 拆成 `<ID>a`/`<ID>b`（如 `G6-N1a`/`G6-N1b`、`G6-N6a`/`G6-N6b`），每个子 tag 恰一次；`--only` 名仍是 `g6_n1`/`g6_n6`。

### 4.7 命令与增量检查

```bash
# 全量 G6（唯一 gate 命令；仓库根）
uv run python v24/s7/test_g6.py

# W1 增量检查点（不是 gate，不计入 11/11；不得替代全量）
uv run python v24/s7/test_g6.py --only g6_a1,g6_n1,g6_b1
```

`main(argv)` 用 `argparse` 接受 `--only` 逗号分隔的 assertion 名；默认顺序执行全部 `G6-A…H`、`N1…N9`、`L1…L5`。退出码 0 当且仅当所有选中断言通过且每个 tag 恰一次；末行固定为：

```text
[passed] v24 S7 W1-W2 G6-A…H + N1-N9 + L1-L5: g6_a1,...,g6_h3,g6_n1,...,g6_n9,g6_l1,...,g6_l5
```

### 4.8 “无产品变更”机械守卫

- 测试前后各跑一次 `git diff --exit-code -- v24/sql v24/load.py`；非空即 fail。
- `sha256sum v24/sql/*.sql` 与运行前一致；`v24/load.py` 的 `SQL_LOAD_ORDER` 不含 `s7` 或 `51`。
- `grep -R "time.sleep\|sleep(" v24/s7/` 必须无命中；`grep -R "socket"` 只允许复用 `test_g2b` 的 guard。
- 任一既有 gate 红：先判断是否本轮 docs-only / test-only 改动导致；不是则按仓库规则停手，不把既有红算成 G6 的失败来“修”。

---

## 5. G6 断言与负例

### 5.1 18 格矩阵（6 行 × 3 列）

“既有证据”只写实际存在的 gate/test ID；“S7 动作”只允许 `新断言` 或 `仅重跑交点`。若某格无法确定性构造，不写测试，标设计缺口（不是第三种动作）。

| # | §7 格 | 设计预期（压缩） | 既有证据（精确 ID） | S7 动作 |
|---:|---|---|---|---|
| 1 | start × install/activate | start 先则 pin 已激活 episode；activate 后则 resolve 新 episode；未激活不能 bind | `G2a-3`（no_episode → `provider_unavailable` W1，零 run）；`G3b-4`（start 后 run pin 绑已激活 episode） | **新** G6-A1（activate/start 两序） |
| 2 | start × deactivate/retire | start 先则 pin 挡 release；retire 先则拒新 run、已有 run 排空 | `G3b-4`（顺序同形）；`G3b-5`（两连接、start/off 两序，`pg_blocking_pids`） | **仅重跑交点**：G3b-5 是权威；closeout 重跑 `v24/s3/test_g2.py`，不再写 G6 体 |
| 3 | start × dispose | start 先阻 dispose；dispose 先则墓碑，start 拒绝 | `G3b-4`（顺序：start→off→dispose deferred；off/dispose 先→start `provider_unavailable`） | **新** G6-N1（强制负例；两序 + held-G） |
| 4 | poll/wait × install/activate | 读已提交状态；不触发激活 | `G2a-4`（poll 无 G/tuple、十表零写）；无 activation 交叉 | **新** G6-B1（held-G 下 poll/wait） |
| 5 | poll/wait × deactivate/retire | 可观察 withdrawn/retiring/blocker；不帮清理 | `G2a-5`（wait_check 只读、零写）；无 retire 交叉 | **新** G6-B2 |
| 6 | poll/wait × dispose | 可观察 dispose_pending/disposed；不延长引用 | `G2a-4`/`G2a-5`；无 dispose 交叉 | **新** G6-B3 |
| 7 | cancel × install/activate | cancel 只关 run；不改 activation pin | `G3b-1 phase 2`（cancel 后 off 才释放 slot/episode）；`G3b-2`（claimed 引用保留 run pin）；activation pin 字节不变未单独断言 | **新** G6-C1（cancel 与同 activation 上的新 start 两序） |
| 8 | cancel × deactivate/retire | cancel 先 seal run 但保留被 claimed/unknown effect 引用的 pin；retire 等静默 | `G2b-O`（cancel×T2 两序）；`G3b-4`（顺序 cancel/off）；无 concurrent cancel/off | **新** G6-C2 + **G6-N5**（late receipt） |
| 9 | cancel × dispose | cancel 不替代 dispose；dispose 等全部 run pin | `G3b-4`（顺序 cancel/off→dispose）；`G4-P`（dispose 等义务）；无 concurrent | **新** G6-C3 |
| 10 | steer × install/activate | 不改配置 pin；terminal run 一律 `already_terminal` | `G2a-7`（steer 不动 pins/claimed token；terminal 序）；`G2b-P`（pending steer 不造第二个 model） | **新** G6-D1 + **G6-N3**（terminal steer） |
| 11 | steer × deactivate/retire | active steer 先则旧 pin 排空；retire 先则仍沿旧 pin；pending_steer 不生成第二个 model_call | `G2b-P`（claimed tool 延迟 steer、latest wins、settle 只消费最新）；无 retire 交叉 | **新** G6-E1 + **G6-N4**（steer/withdraw） |
| 12 | steer × dispose | 对话连续性不复活 disposed fiber；权限撤销另发 revoke | 无 | **新** G6-F1 |
| 13 | respond × install/activate | 只在原 run interaction 精确消费；不换 plugin | `G2b-H`（interaction 生产/replay）；`G2b-I`（respond chain/mismatch W1）；`G2a-8`（respond contract）；无 activation 交叉 | **新** G6-G1 |
| 14 | respond × deactivate/retire | respond 先生成旧 pin continuation；retire 先则 interaction 仍可答且 run 排空 | `G2b-I`；无 retire 交叉 | **新** G6-G2 + **G6-N2**（respond/cancel） |
| 15 | respond × dispose | dispose 不取消有效交互；run owner/授权撤销可 fence | 无 | **新** G6-G3 |
| 16 | model/tool advance × install/activate | 先提交按冻结 pin 执行；激活后 resolve 新绑定；spawn intent 同事务建 child/quota/首 model | `G2b-A/B/C/D/E/F`（model/tool claim/settle/batch、两连接 claim race）；`G7-A/B`（spawn 同 advance）；无 activation 交叉 | **新** G6-H1 + **G6-N9**（spawn 交点重跑） |
| 17 | model/tool advance × deactivate/retire | T2 先按当时 generation；retire 先迟到结果仍记事实/成本、旧 generation 不续链；pin 等静默 | `G3b-1/2/3`（run pin 挡 off、claimed pin 保留、withdrawn start）；`G2b-O`（T2/cancel，不是 retire） | **新** G6-H2 + **G6-N5** |
| 18 | model/tool advance × dispose | 外部结果不复活 install；未结算 effect/资源债务挡 dispose | `G4-P`（dispose 义务）；`G4-M`（unsettled release 挡 close）；`G3b-4`（dispose 先） | **新** G6-H3 |

### 5.2 G6-A…H（矩阵覆盖，8 组 16 条）

**G6-A（start × 三列）**
- `A1` activate/start 两序：自建单个 install/fiber B（`seed_install` + `seed_fiber`，`want_on=true`、`current_episode_id=NULL`、无 activation pin；即 G2a-3 的 `no_episode` 前置）。序 1：`fiber_control(on)` 先返回并持有 G；start 随后阻塞，`wait_for_g_block` 证明；释放后 start committed，run pin 指向 B episode。序 2：start 先（无可用 episode）→ `provider_unavailable` W1 零 run；再 on；再 start → committed。断言：start `runs +1`、`pins +1`、`effects +2`（command_start + model_call）、`events +2`、`requests +1`；on 另加 `pins +1`（activation）；start 不改 activation pin、slot 未 release。
- `N1`（矩阵格 3，不另设 A2）：start/dispose 两序；见 N1；证据 tag 用 `G6-N1a/b`，不重复打印。
- 格 2（start×retire）不设 G6 body：`G3b-5` 是权威，closeout 重跑 `v24/s3/test_g2.py` 即“仅重跑交点”。

**G6-B（poll/wait × 三列）**
- `B1` poll/wait × activate：run1 已绑 A 的 episode；writer 执行 `fiber_control(on)` 激活 B 并保持事务（G 持有）；reader 第二连接跑 `poll(run,0)` 与 `wait_check(run,generation,epoch,0)`。断言 `pg_blocking_pids(reader)='{}'`、reader 无 advisory/tuple/relation 锁、十表快照相等；reader 读到的是 writer 提交前的旧 `want_on/current_episode`；writer commit 后 reader 才看到新 episode；reader 不产生 pin/activation。
- `B2` poll/wait × off：writer `fiber_control(off)` 返回但未 commit；reader 读旧状态；commit 后读 `slot.withdrawn_at NOT NULL, released_at NULL`、`episode.state='retiring'`；reader 不 close episode、不 release slot、不延长 pin。
- `B3` poll/wait × dispose：writer `dispose` 返回但未 commit；reader 读旧 install 状态；commit 后读 `dispose_pending`；reader 不写 `disposed_at`、不产生 `host_release`；run pin 不被读请求续期。
- 三条都用 `held_open_then_probe`；若某条 reader 实际阻塞在 G（`pg_blocking_pids` 非空），该格判设计缺口/实现 bug，不用 sleep 或重试掩盖。

**G6-C（cancel × 三列）**
- `C1` cancel × activate：run1 在激活 B 上运行；序 1 cancel(run1) 先（持 G），start(run2) 后阻塞；序 2 start(run2) 先，cancel 后。两序断言：activation pin 行逐字节不变；run1 pin 按 claimed/unknown 条件释放；run2 pin 指向同一 B episode；B slot 不 release；`runs` 净 +1（run2）-0（run1 仅状态变）。
- `C2` cancel × retire：run1 有 claimed model（pin）。序 1 cancel 先 → pin 保留、off deferred；settle T2 → pin release、off committed。序 2 off 先 → slot withdrawn、pin 保留；cancel → pin 仍保留；settle → release；off 完成。断言 slot `released_at` 不早于 pin `released_at`。
- `C3` cancel × dispose：序 1 cancel → off → dispose（host_release）→ settle → disposed；序 2 dispose 先（`dispose_pending`，不 tombstone）→ cancel → off → 新 key dispose → settle → disposed。断言任何序下 `installs.disposed_at` 都不早于 run pin 清零。

**G6-D（steer × install）**
- `D1` steer/start 两序：run1 waiting/claimed tool；conn1 steer，conn2 start(run2) 同一 activation。两序断言 activation pin 不变、steer 不新增 model_call、run2 绑同一 episode、`pending_steer` 或已消费状态符合 generation。
- `N3` terminal steer：final T2 在 conn1 先提交（run completed，G 持有）；conn2 steer 阻塞；释放后 `already_terminal` **W1**（+1 failed command effect/request，domain 零写，零新 model）。这是 9 负例之一。

**G6-E（steer × retire）**
- `E1` steer/off 两序：run1 有 claimed tool（pin）。序 1 steer 先 → `pending_steer`，off deferred；settle tool → 恰一个 `cause='steer'` model；pin release；off 完成。序 2 off 先 → withdrawn/retiring，steer 仍沿旧 pin；settle → 恰一个 model；off 完成。断言 `model_call` 计数不增加第二个、`slot.released_at` 不早于 pin release。
- `N4` steer/withdraw：序 2 的强制负例标签；额外断言 `withdrawn_at NOT NULL` 后 steer 不 resolve 新 slot、不生成第二个 model_call、旧 pin 仍被引用。

**G6-F（steer × dispose）**
- `F1` 两序：序 1 steer 先（pending on claimed tool）→ dispose deferred；settle → model；run terminal；dispose → disposed。序 2 dispose 先（对已 terminal run 的 install，G 持有）→ steer 阻塞；释放后 `already_terminal` W1，`disposed_at` 不变，无新 model/pin 复活。断言“disposed fiber 不被对话连续性复活”。

**G6-G（respond × 三列）**
- `G1` respond/start 两序：run1 waiting interaction；conn1 respond，conn2 start(run2)。两序断言 respond 只消费原 interaction、activation pin 不变、run2 绑同一 episode、respond 的 continuation 不被 run2 影响。
- `G2` respond/off 两序：序 1 respond 先 → 旧 pin continuation；off deferred 到 run 排空/pin release。序 2 off 先 → interaction 仍可答；respond committed；run 排空；off 完成。断言 slot 不提前 release、respond 不创建第二个 interaction。
- `G3` respond/dispose 两序：序 1 respond → continuation；dispose deferred 到 run terminal。序 2 dispose 先（terminal run）→ respond `already_terminal` W1，interaction 不复活，`disposed_at` 不变。
- `N2` respond/cancel：两序；respond 先 → 下一 model effect ready，cancel 随后取消 ready successor；cancel 先 → respond `already_terminal` W1；一赢家由 G 决定，零第二个 successor。

**G6-H（model/tool × 三列）**
- `H1` T2/start 两序：run1 claimed model（pin）；conn1 T2 settle，conn2 start(run2)。两序断言 model receipt/成本按 T2 冻结 pin；run2 resolve 当前 episode；无第二个未结算 model；`turn/cost` 只加一次。child 首 `model_call` 的 recovery 由 **G7-G** 覆盖，G6 不重测。
- `H2` T2/off 两序：T2 先 → model succeeded/后继 ready；off deferred 到 pin release。off 先 → slot withdrawn；迟到 T2 仍记 fact/cost，旧 generation 不续链；pin 保留到 quiesced；slot 不提前 release。
- `H3` T2/dispose 两序：T2 先 → 后继 ready；dispose deferred 到未结算 effect/资源债务清零。dispose 先 → `dispose_pending`；迟到 T2 只记 fact/cost，不复活 install，`disposed_at` 在 effect quiesced 后才写。
- `N9` spawn 同 key 异输入：只做交点重跑，见 N9；不复制 G7-A…H。

### 5.3 9 条强制负例（N1…N9）

| ID | 场景（§9 原文） | 两连接 / 两序 | 可证伪断言 | 写类 |
|---|---|---|---|---|
| **N1** | **start/dispose** | `ordered_advance_race` 两序：start 先；dispose 先 | start 先：run pin 挡住 dispose；`dispose` 返回后（committed/deferred 均可）`emitted=[]`、install `dispose_pending`、`disposed_at NULL`；cancel/off/settle 后 dispose 才 disposed。dispose 先：墓碑后 start `provider_unavailable` W1、零 run/pin。两序 `pg_blocking_pids` 证明 waiter 等 G，不等 row lock | start committed / dispose 不 tombstone；反向 start W1 |
| **N2** | **respond/cancel** | `ordered_advance_race` 两序：respond 先；cancel 先 | respond 先：interaction 消费、下一 model ready；cancel 随后取消 ready successor，不覆盖 receipt。cancel 先：respond `already_terminal` W1，零新 model。赢家由 G 决定 | respond committed / cancel committed；反向 W1 |
| **N3** | **terminal steer** | final T2 先（completed，持 G）；steer 后阻塞 | steer 返回 `already_terminal` W1；domain 零写；零新 model；run 结果/`ended_at`/cost 不变 | W1 |
| **N4** | **steer/withdraw** | off 先（withdrawn，持 G）；active steer 后 | steer 仍沿旧 pin；`pending_steer` 生成；claimed model 结算前不生成第二个 model_call；settle 后恰一个 successor；slot 不因 steer 提前 release | steer committed（旧 generation） |
| **N5** | **cancel/retire + late receipt** | cancel 与 off 两序；late T2 在两者之后 | cancel 先：pin 保留；off deferred/withdrawn；late T2 记 fact/cost、无旧 generation successor；pin 在静默后 release；off 完成。off 先：同样 pin 保留至静默；cancel 不自动卸载 owner fiber | cancel committed / off deferred→committed；late T2 committed（无 successor） |
| **N6** | **scope close vs installed/prepare_unknown install** | N6a installed；N6b prepare_unknown；close 与 dispose/inspect 两连接 | N6a：`close` 后 `closed_at NULL`、`scope_closable=false`；install 仍在；install admission `scope_closed` W1；dispose 后才 `closed`。N6b：无 inspect 永远 closing/`closed_at NULL`；inspect absent + release → disposed → closed。不得提前 closed | close committed（deferred）；install W1；dispose committed |
| **N7** | **owner retire vs child install（both orders）** | 跨 scope child install（`new_child_scope` + `admit_install(owner_fiber=...)`）；child-first 与 owner-first 两序，两序各用 held-G | child 先：owner `fiber_control(off)` 与 `dispose` 都必须找到 `installs.owner_fiber_id/owner_episode_id` 的 child（含 preparing/prepare_unknown），不得关闭 owner episode/墓碑；child dispose 后才完成。owner 先：`want_off`（off-first）或 `dispose_pending`（dispose-first）使 child admission 返回 `owner_closing` W1、零 child；两序分别用两连接 held-G 证明 | child committed / owner 不 tombstone（deferred/pending）；反向 W1 |
| **N8** | **T2/cancel** | `ordered_advance_race` 两序；只重跑 G2b-O 的关键交点 | T2 先：receipt/成本/后继保留，cancel 随后取消 ready successor；cancel 先：late T2 只记 fact/cost，零 successor，pin 保留至静默。断言“零第二个 successor、receipt 不被覆盖” | T2 committed / cancel committed；反向 T2 committed 无 successor |
| **N9** | **spawn intent same key different input** | `serialized_race` 两连接同 key 异 canonical bytes；随后新父 outcome 携带败者 bytes | 恰一个 child；败者 `receipt_conflict`（G 串行），不写 quota；新父 outcome 得第 24 码 `spawn_key_conflict` W0，十表逐字节相等，model effect 仍 claimed；child/effect 计数 1，父 grant 只扣一次 | 赢家 committed；败者 W0；24 码 W0 |

### 5.4 §B.2 死锁/锁序负例（L1…L5）

> `cleanup_cycle` 的 DAG 环本身由 G4-E/G4-M-5 覆盖，G6 不重测；这里只测并发锁序的 deadlock-free、无 `pg_blocking_pids` 环、winner=G。

| ID | §B.2 反例 | 两连接证据 | 断言 |
|---|---|---|---|
| **L1** | 反例一：start 锁 fiber、dispose 锁 install，互相等 | N1 两序；`assert_no_wait_cycle` + `wait_for_g_block` | waiter 只等 G（blockers 只有 holder），未先拿 v24 关系锁/行锁；wait graph 无环；winner 由 G 决定；若 waiter 等 row lock 或出现环 → fail |
| **L2** | 反例二：cancel 锁 run 后等 fiber；retire 锁 fiber 后等 run pin | C2/N5；两序 | cancel/off 的 waiter 阻塞在 G，不在 run pin/fiber 行；pin 只在静默后 release；无环 |
| **L3** | 反例三：spawn 先 parent 后 child；cancel child 先 child 后 parent | `make_parent` + spawn 出 child；`cancel(parent)` 与 `cancel(child)` 两序 | 两个 run 在 G 下按 UUID 序取行锁；无 deadlock、无 blocking-pids 环；两 run 均 cancelled；winner 由 G 决定 |
| **L4** | 反例四：两 provider 切换以不同 key 序释放 slot A→B / B→A | 两个 fresh fiber/slot；`fiber_control(off)` A/B 两序 | 第二事务只等 G；slot closure 不在 G 前逐 slot 抢锁；无环；release 顺序由提交序决定，不由调用序决定 |
| **L5** | 反例五：respond 锁 interaction projection，cancel 锁 run 后 interaction | N2；两序 | interaction 不是独立锁对象；waiter 只等 G，没有 interaction 表/行锁；无环；winner 由 G 决定 |

### 5.5 不复制、不弱化、计数

- 矩阵格 3 与 N1 是同一体（不另设 A2；tag 用 N1a/b）；G6-E1 与 N4 共用体（N4 是序 2 的强制标签）；G6-N8 与 N9 只做 G2b-O/G7-N2 的**交点重跑**，不复制其全部断言。其余 G6 断言必须是新体。
- 既有 10 个 gate 的断言、命令、编号一律不改；G6 只新增 `v24/s7/**` 测试文件。任何“为了让 G6 绿而放宽既有断言”的做法视为失败。
- G6 断言总数：**30 条 ID**（16 条矩阵子断言 + 9 条负例 + 5 条锁序）；其中 3 处标注“仅重跑交点”/同体复用（格 2、N8、N9）：N8/N9 仍有 G6 结果行，格 2 只由 closeout 的 `G3b-5` 重跑覆盖，不在 G6 输出中冒充独立断言。

---

## 6. 风险与回退

### 6.1 风险表

| # | 风险/最弱假设 | 触发信号 | 处置 |
|---|---|---|---|
| R1 | G 覆盖所有受控 mutation 且无锁后补锁（设计 §10.3 最脆弱假设） | L1–L5 出现 row-lock wait、blocking-pids 环、或 waiter 先拿关系锁 | **stop and report first**；不改产品、不改 gate；把复现命令/证据交给控制器 |
| R2 | N7 的 `dispose` 闭包边未扩（D-S5-8 部分落地） | child-first 时 owner 提前 `closed`/墓碑 | 先判“断言/夹具错”还是“真实锁序 bug”；后者 stop/report；前者修 `v24/s7/**` |
| R3 | 跨 scope child install 无现成 fixture（D-S5-10 证据缺口） | `admit_install(owner_fiber=...)` 公共路径拒绝或不可构造 | 若公共 admission 不允许跨 scope，则 N7 降级为“同 scope + 显式债务 D-S7-3”，不得伪造跨 scope |
| R4 | poll/wait 读格无法用 G 阻塞证明（读者不取 G） | `held_open_then_probe` 读到未提交状态或 reader 拿锁 | 该格标“设计缺口/不可判定”，不造 sleep；G6 不绿，报告 |
| R5 | 既有 gate 在本轮 docs-only 期间已红 | 10 命令任一非 0 | 按仓库规则停手；不得把既有红算 G6 失败或改断言 |
| R6 | 导入的测试 helper 在 S1–S8 后续变更中漂移 | import/签名失败或语义变化 | 固定 HEAD `90b233e`；只 import 稳定函数；漂移则先修 fixture 再跑，不复制旧逻辑 |
| R7 | `serialized_race` 采样不到两序 | 只观察到一种 G 获取序 | fail，不跳过；可增加 fresh fixture 重试，但不得用 sleep/事件握手伪造 |
| R8 | prepare_unknown 无 inspect 永远 closing | 测试等待“自动 closed” | 断言 `closed_at NULL` 是正确答案；不得用 inspect 伪造；这属于设计合同，不是超时 |
| R9 | 9 条负例被误解为 9 个 §7 行 | 评审要求新增 3 行 | 停手，引用 §7 表 18 格 + §9 9 负例；走 O-S7-1 设计裁决 |

### 6.2 失败/降级/停手条件

- **断言红且可复现为夹具缺陷**：修 `v24/s7/**` 后同 gate 重跑；不降低断言。
- **断言红且两连接稳定复现产品锁序/顺序 bug**：**stop and report first**；保留完整证据行、`pg_locks`/`pg_blocking_pids` 输出、最小复现命令；不写产品 SQL。
- **某格无法确定性构造**：标“设计缺口/未验证”，在 §6.4 登记 `D-S7-*`；G6 不宣称绿。
- **任一既有 gate 红**：停；先恢复既有 10/10，再谈 G6；不得以“G6 是文档计划”为由忽略。
- **超时/挂起**：用 `statement_timeout` 与有界 deadline；不得用无界等待；超时判 fail，不猜顺序。

### 6.3 回退

- 本计划是 docs-only：回退 = 删除本文件；产品/测试无回退。
- W1/W2 的测试代码若已写入但未收口：`rm -rf v24/s7`（仅测试目录）+ 恢复 README/matrix/ledger 的对应段落；产品 SQL 不受影响。
- 若控制器批准了产品修复：修复必须单独设计修订 + 11/11 重跑；不得混入本计划的“纯证据”提交。
- 不 force-push、不改 `main`、不 `git add -A`；提交只按路径。

### 6.4 已知缺口的归类（断言或显式债务）

| 缺口 | 归类 | 落位/理由 |
|---|---|---|
| D-S5-8 dispose 闭包锁序（dispose 仍走 sibling 边，child 由 `dispose_stage FOR UPDATE` 自行锁） | **G6 断言**，失败则 **D-S7-1** | N7 的 owner/child 两序覆盖闭包时机；G6-C3/H3 覆盖 dispose 与 run/effect 债务；G6-L1/L2 只复核 start/dispose 与 cancel/retire 的锁向量。若无法用两连接确定性构造，登记 `D-S7-1` 显式债务，不写投机修复 |
| 跨 scope child install（D-S5-10 无专用 fixture） | **G6 断言**，不可构造则 **D-S7-3** | N7 用 `new_child_scope` + `admit_install(owner_fiber=...)` 构造跨 scope child；若公共 admission 不允许，降级为显式债务 |
| G3b-4 只有顺序（`start_dispose_orders` 明确 no concurrent-race claim） | **G6 断言** | G6-A1 + N1 用两连接 held-G 补齐；G3b-4 继续作为顺序基线，不重写 |
| 无 starvation/fairness 证明（设计 D3 部署前提） | **显式债务 D-S7-2** | G6 只证安全性与线性化，不证活性/公平；不新增 scheduler/lease；在 README/matrix 明示 |
| G3b-5 只覆盖 start/off，不覆盖 cancel/off | **G6 断言** | G6-C2/N5 补齐；G3b-5 作为 start/retire 的权威，closeout 重跑 |

### 6.5 与设计稿的分歧点清单

- **无规格分歧**。本计划不新增表/列/函数/错误码，不改 §7 行数，不改 §9 负例，不改 §B.1 锁序。
- 计划级偏差（显式）：① G6 以“18 格 + 9 负例”两张矩阵呈现，而不是把 9 负例塞进 §7 表；② 复用 S1–S8 的测试 helper（C15 允许，产品合同不变）；③ 格 2/N8/N9 采用“仅重跑交点”，不复制既有 gate；④ 不计划任何产品 SQL。若评审不接受任一条，停手并改计划，不静默改规格。

---

## 7. 与设计稿的分歧点清单 + 开放决策

> 全部 6 条，均有推荐项；未裁决前按推荐项执行。任何一条被否决都必须停手改计划，不得在实现中静默选择。

| ID | 开放问题 | 推荐选项 | 若否决 |
|---|---|---|---|
| **O-S7-1** | “§7 是 9 行”还是 18 格？ | **设计 §7 表 6×3=18 格为权威；“9”只指 §9 的 9 条强制负例**。不新增 §7 行，不把负例改写成行 | 若确要 9 个 §7 行，先改设计稿并重新裁决；本计划停手，不静默扩成 21 格 |
| **O-S7-2** | 哪些格需要真实产品修复，哪些只做证据？ | **默认全部 evidence-only**；只有 G6 以两个真实连接稳定复现锁序/顺序 bug 时才停手报告；产品修复必须另开设计修订，不在本计划写 SQL | 若要求“先修再证”，拒绝：无证据的修复违反 stop-and-report-first 边界 |
| **O-S7-3** | G6 可否消费既有 G2b/G3b/G4/G7 证据？ | **可以，但只作为“仅重跑交点”**：除格 2 由 closeout 重跑 `G3b-5` 外，G6 必须自己产出结果行；既有 gate 在 closeout 全量重跑；不得复制旧时间戳/旧 pid 冒充新证据 | 若要求每格完全新写，W1 扩大为重复实现，需重新估时；仍不得削弱既有断言 |
| **O-S7-4** | spawn 格的范围？ | **只做同 scope spawn 的 same-key/different-bytes 交点（N9）+ 跨 scope child install（N7，属 install 不属 spawn）**；不做跨 scope spawn | 跨 scope spawn 需新设计/授权合同；本计划不发明 |
| **O-S7-5** | D-S5-8、跨 scope child install、G3b-4 顺序、无 starvation 如何归类？ | **D-S5-8→G6-N7 + G6-C3/H3（L1/L2 复核锁向量；失败则 D-S7-1）；跨 scope child install→G6-N7（不可构造则 D-S7-3）；G3b-4→G6-A1 + N1；无 starvation→D-S7-2 显式债务** | 若要求全部转债务，G6 覆盖不全，不能收口；若要求全部转断言，无 starvation 无法证，需设计修订 |
| **O-S7-6** | 测试文件放 `v24/s7/` 还是并入 s4/s5/s8？ | **新建 `v24/s7/{g6_support.py,test_g6.py,README.md}`**；不新建 `setup_db.py`、不新增 SQL | 若必须并入既有 stage，需说明 G6 的总验收归属；仍不得改既有 gate 的命令/编号 |

**分类补充（硬性）**：D-S5-8 与跨 scope child install 若最终不能确定性构造，必须在 `v24/s7/README.md` 与 deviation ledger 写成 `D-S7-1`/`D-S7-3`，并明确“未验证”，不得用“代码路径成立”代替证据。无 starvation 一律 `D-S7-2`，不因 G6 绿而宣称公平。

---

## 8. 计划级验收与收尾清单（W1/W2）

### 8.1 W1：harness + 18 格中尚未覆盖的部分

- **新建**：`v24/s7/g6_support.py`、`v24/s7/test_g6.py`、`v24/s7/README.md`（README 可先骨架）。
- **实现**：`G6-A1`、`G6-N1`、`G6-B1/B2/B3`、`G6-C1/C2/C3`、`G6-D1`、`G6-E1`、`G6-F1`、`G6-G1/G2/G3`、`G6-H1/H2/H3`；即 18 格矩阵中所有标“新”的格。格 2（start×retire）不写 body，仅由 closeout 重跑 `G3b-5` 覆盖。
- **夹具**：按 §4.5 复用；每个断言 fresh fixture；先前置不变量，再两序，再最终 diff。
- **增量检查**：`uv run python v24/s7/test_g6.py --only g6_a1,g6_n1,g6_b1,g6_c2,g6_h2` 等，exit 0；**不是 gate**，不计入 11/11。
- **W1 Done when**：18 格全部有落位；新断言在 `--only` 下通过；既有 10 个 gate 仍 exit 0；`v24/sql/**` 与 `v24/load.py` diff 为空；无 `sleep`、无 socket。
- **W1 不提交**；不更新 matrix/ledger 的“完成”状态，只可写“W1 checkpoint”。

### 8.2 W2：全量 G6 + 9 负例 + 5 锁序 + 收尾

- **实现**：`G6-N2…N9`、`G6-L1…L5`；把 `G6-N1` 纳入全量；补格 2 的“仅重跑”说明。
- **全量 gate**：`uv run python v24/s7/test_g6.py` exit 0；`G6-A…H`、`N1…N9`、`L1…L5` 每个结果 tag 恰一次；末行 `[passed] v24 S7 W1-W2 ...`。
- **既有 10 命令逐条重跑**（仓库根；顺序不强制，全部 exit 0）：

| # | 命令 | 归属 |
|---:|---|---|
| 1 | `uv run python v24/load.py` | loader/登记 |
| 2 | `uv run python v24/s1/setup_db.py --self-check` | S1 建库自检 |
| 3 | `uv run python v24/s1/test_ddl.py` | S1 DDL |
| 4 | `uv run python v24/s1/test_g1.py` | G1 |
| 5 | `uv run python v24/s2/test_g3a.py` | G3a |
| 6 | `uv run python v24/s3/test_g2.py` | G2a/G3b |
| 7 | `uv run python v24/s4/test_g2b.py` | G2b |
| 8 | `uv run python v24/s5/test_g4.py` | G4 |
| 9 | `uv run python v24/s6/test_g5.py` | G5 |
| 10 | `uv run python v24/s8/test_g7.py` | G7 |

  加上第 11 条 `uv run python v24/s7/test_g6.py`，closeout 为 **11/11 exit 0**。既有 10 条的命令、顺序、断言、编号一律不改；G6 不替代任何一条。
- **收尾工件**：`v24/s7/README.md`（对象/入口/命令/证据索引/债务）；`docs/reviews/v24-conformance-matrix-2026-10-23.md`（G6 从“未验证”改为“完成”，并写 18 格/9 负例/5 锁序的边界）；`docs/reviews/v24-deviation-ledger-2026-10-23.md`（D-S7-1/2/3 与 O-S7-* 的落位）；本计划结项段（只写“计划完成”，不写“已提交/已推送”）。
- **loader 不变**：无新 SQL 文件、无 `SQL_LOAD_ORDER` 变更；`git diff --exit-code -- v24/load.py v24/sql` 为空。
- **单一里程碑提交**：留给控制器；提交信息建议 `v24: add S7 concurrency matrix (G6)`；按路径 `git add`，禁止 `git add -A`；不 force-push、不碰 `main`。
- **W2 不宣称**：不声称真实 provider/网络、跨主机、无饥饿、G5 崩溃窗口；这些边界写入 README。

### 8.3 计划级验收清单

- [ ] 18 格矩阵每格有“既有证据 + S7 动作”，无空格。
- [ ] 9 条负例 N1–N9 全部有双连接/两序证据；能两序的两序。
- [ ] 5 条锁序 L1–L5 全部有 `pg_blocking_pids()`、wait graph 无环、winner=G。
- [ ] 每个 G6 tag 结果行恰一次；末行 `[passed]`。
- [ ] 11/11 gate 命令 exit 0（10 既有 + G6）。
- [ ] `v24/sql/**`、`v24/load.py` diff 为空；无新表/列/函数/错误码。
- [ ] `v24/s7/README.md`、conformance matrix、deviation ledger 更新。
- [ ] D-S7-1/2/3 与 O-S7-* 有明确落位；未验证项显式标“未验证”。
- [ ] 单一里程碑提交留给控制器；本文件不宣称已提交/已推送。
