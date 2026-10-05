# v13 unattended_continuation 授权增补计划（2026-10-01）

**状态：候选计划，待父复审接受。未实现，未跑任何 gate。本文不是运行时证据，不冒充 exit_0。**

本计划是 R1-M3 §9.5 父决定条款的载体：「父若要把该项改成 `exit_0`，必须在接受函里写明，不能靠实现者推断」（`docs/plans/v13-long-loop-phase-c-r1-m3-plan-2026-10-01.md` §9 第 5 条）。2026-10-01 用户指令「把 unattended_continuation 从 expected_nonzero 转为授权实施」即该父决定。父已另裁三事（本文 §3 D0）：

1. **旧 gate 不动**（裁决 A）：`v13/goal_supervisor/test_goal_supervisor.py` 末尾的 `SystemExit("v13: supervisor: ask_user")` 原样保留；授权以**新增独立脚本 + 矩阵新增行**表达，形状对齐 Phase A 真实 provider 先例（fake gate 负例保留 + 授权验收分行；先例的行名是 `real_authorized_exit_0`，本计划的新行名是 `unattended_authorized_exit_0`，见 D4 与 §6.4）。
2. **轮数预算 = 2**：授权循环至多 2 轮，与 Phase C §4.8 种子 `supervisor_max_ticks = 2` 同值。
3. **`load.py` 冻结 = 追加式正向证明**：相对 `fb295ac` 只允许新增行 + 表尾顺序谓词，不钉 blob。

本计划不重开 Phase 0/A/B/C/R0/R1-M3/Phase D 计划正文，不替换 `v13_advance`，不给 `load.py` 增键，不调用真实 provider。

## 1. 授权关系与合同边界

「转 exit_0」在本仓库有三层互相锁定的事实，本计划逐层处理：

1. **机器事实**：tick 从不 `ask_user`。`GoalSupervisor.tick` 只有三种出口——正常 report、`SupervisorFail("v13: supervisor: unpaid_remaining")`、普通 `RuntimeError`（max_ticks / open transaction）（`v13/goal_supervisor/driver.py:174-268`）。非零只来自 gate 进程尾部三行（`v13/goal_supervisor/test_goal_supervisor.py:939-941`：`print("[FAIL] unattended_continuation:", ASK_USER)` → `print(ASK_USER)` → `raise SystemExit(ASK_USER)`）。它是「授权缺口仍开」的声明，不是机器缺功能。因此授权转换**不需要也不允许改 tick 十步序、`settle_once` 或任何 SQL**。
2. **计划事实**：R1-M3 §9.5 用父决定锁住这一项（用户指令已给）；Phase C §4.7 允许声称上限仍写「不得声称人可以离开生产终端」——本计划不解除该句。
3. **文档事实**：矩阵 `goal_supervisor gate` 行与 M3 小节 `unattended_continuation` 行均为 `expected_nonzero`（`docs/reviews/v13-long-loop-phase-c-conformance-matrix-2026-09-29.md`）；按裁决 A，这些行**逐字保留为历史证据**，授权以新行表达。

本父决定**只打开**一件事：Fake 夹具下、独立授权脚本（`V13_UNATTENDED_AUTHORIZATION=1` 门控）的 exit 0 验收，及矩阵/台账/README 对应新行。

本父决定**不打开**：R1-M3 §9.1–§9.4 与 §9.6；Reopen §6 七要件重做（已由 R1/M3 实现）；Phase C §1 第二份 `v13_advance`；Phase 0 T2 无人值守 skip；T1.4 无人值守 `plan_commit`；T7/Phase C §4.11 PC-4（重开须另写计划并贴加载后 gate 全文哈希）；V11/auto-wake；真实 provider；Phase D 多 goal 公平/全局并发帽/多日 soak；「人可以离开生产终端」。Phase D 计划 §1 禁止 Phase D 编辑 `v13/goal_supervisor/**`——那是 D 的约束，不禁止本父决定改验收脚本。

## 2. 活体基线与预存红线

### 2.1 基线

| 对象 | 值 |
|---|---|
| HEAD | `78e77c7`（`v13: add fair claim driver and bounded multi-root soak`） |
| M3 实现提交 | `05a1687`；R1 = `93a49cd`（`test_goal_supervisor.py:40` 常量 `R1`）；R0 = `a2cabf1` |
| 冻结基线对象 | `fb295ac6c7459bb98dac57e37883af549d2d8a4c` |
| 工作区 | 无已跟踪改动；未跟踪文件（含 `prompt-exports/`、调查稿）一律不入库 |

实现第一步（零产品改动）：`git rev-parse HEAD` 核对、`git cat-file -e fb295ac^{commit}` / `78e77c7^{commit}` / `93a49cd^{commit}` 三者存在、`git hash-object` 记录 §5 表中关键文件哈希、读 `v13/load.py` 的 `STAGE_THROUGH` 尾部（须为 `goal_supervise: 38` 后接 `fair_claim: 39`）。任一不符即停。

### 2.2 预存红线（规划期已亲验的推断，开工须实跑确认）

`r0_source_scope()`（`v13/plan_arm/test_plan_arm.py:327` 起）是活体冻结中心，被 `plan_arm`/`frontier_gap`/`goal_supervise`/`goal_supervisor` 四个 gate 调用。规划期已核验两条与 HEAD 冲突：

1. `extra <= {v13/goal_supervisor/ 前缀}`——`git ls-files v13` 现含 `v13/fair_claim/**`（`b761d9c`）与 `v13/fair_driver/**`（`78e77c7`），断言红。
2. `protected` 逐字节相等含 `v13/load.py`——现为 39 stages（`fair_claim` 两处追加），相对 `fb295ac` 的 38 项不再逐字节相等，断言红。
3. 连带：`test_goal_supervisor.py::test_stage_bytes` 要求 `git diff R1 -- v13/load.py` 为空，`fair_claim` 在 R1 之后追加，断言红。

已核验的 diff 形状：`git diff fb295ac -- v13/load.py` 恰为两个 hunk、纯 `+` 行（`SQL_LOAD_ORDER` 表尾 `fair_claim` 一行 + `STAGE_THROUGH` `"fair_claim": 39` 一行）。归因是 Phase D 的合法追加，不是运行时回归。开工按 §6.1 实跑 13 条基线逐条记录退出码/库名/失败断言名；失败集合若不是上述冻结红（其它断言红），停，不把它们算进「预存冻结红」，按 `AGENTS.md`「Record existing failures separately」原样记台账。

### 2.3 冻结放宽的唯一定点形状（裁决：追加式；第二轮复审收紧为「已知文件字节钉 + 规范形态穷尽」）

`r0_source_scope` 在 `fb295ac` **不存在**（已核验 `git show fb295ac:v13/plan_arm/test_plan_arm.py | grep -c "def r0_source_scope"` = 0），是 R0 期新增函数，**不在自身 AST 冻结集内，可直接修改**；AST 冻结约束的是 `fb295ac` 时已存在的函数（`test_stage_bytes` 除外；`main`/`run` 只允许追加 `r[01]_*()` 调用行）。定点扩展（第二轮复审发现：纯前缀放行不保护既有文件内容、纯「无删除行」仍放行两表之外的任意纯插入——两者都必须有机械证明）：

- **`extra` 分流：前缀闭集 → 路径闭集 + 已知文件字节钉**。设 `known = extra ∩ git-ls-tree(78e77c7 -- v13)`（开工时刻已在树上的 fair 两目录全部文件与 `v13/goal_supervisor/` 四文件）、`fresh = extra − known`：
  - `fresh ⊆ {v13/goal_supervisor/accept_unattended.py}`（**分期合同**，不是活体等式：提交②落地谓词时该脚本尚不存在，`fresh` 为空合法；提交③脚本按路径 add 后为一元集合法；任何其它新文件恒拒）。开工时 `extra` 若已含三前缀（`v13/goal_supervisor/`、`v13/fair_claim/`、`v13/fair_driver/`）之外路径：停，不准把该路径加进闭集。
  - `known` 逐文件必须字节等于其 `78e77c7` blob，**例外恰两个**：`v13/goal_supervisor/test_goal_supervisor.py`（AST 追加式，见下）与 `v13/goal_supervisor/README.md`（纯追加：diff 无 `-` 行且无修改行；`## 授权验收` 小节只许追加在文末）。该钉把 `driver.py`、`setup_db.py`、`fair_claim/**`、`fair_driver/**` 全部锁死，与 §5「明确不改」清单机械一致；未来里程碑须动这些文件时同提交改冻结中心（既有纪律）。既有 `readmes` 例外集（`plan_arm`/`frontier_gap`/`goal_supervise`/`loop_driver` 四份 README）保持不动——`v13/plan_arm/README.md` 在提交②的冻结中心描述更新走该例外，属 `protected`，不进 `known`/`fresh` 分流。
  - `test_goal_supervisor.py` 相对 `78e77c7` 的 **AST 追加式**（与 fb295ac 四测试同款纪律）：既有顶层函数源码字节相等，唯一例外 `test_stage_bytes`（提交②把其 load 谓词改为调用 `r1_load_append_ok`）；`run()` 只允许追加 `unattended_*()` 调用行；模块级非函数节点（导入/常量）AST 相等；新增顶层函数自由。**连带设计决定：§4.4 的新扫描不进 `test_static`**（保持字节钉），落成新顶层函数 `unattended_accept_script_scan()`，由 `run()` 追加调用。
- **`v13/load.py` 移出逐字节相等集，改「规范形态穷尽」的对应性追加正向证明**（按裁决不钉 blob）：相对基线的 diff 无 `-` 行（`---` 文件头行不计）；丢掉 `+++`/`---`/`@@` 文件头行后，其余 `+` 行去掉一个前缀 `+` 再去首尾空白，必须**逐行恰为追加项的规范序列化形态**（与活体 diff 对齐——已核验 `git diff fb295ac -- v13/load.py` 实形）：`SQL_LOAD_ORDER` 形 `V13_ROOT / "<stage>" / "<file>.sql",` 或 `STAGE_THROUGH` 形 `"<stage>": <整数>,`——除此之外的任何 `+` 行（`load_stage` 函数体内插入、文件末尾新增函数、任意无关行）都拒绝。两表解析照旧：`SQL_LOAD_ORDER` 等于基线完整序列后仅追加新项、每个追加项的 `v13/<stage>/` 目录必须存在于受跟踪文件集（`git ls-files`）；`STAGE_THROUGH` 追加键与追加项一一对应（两向都拒：键无对应项、项无对应键）、键唯一、编号恰为接续值（跳号、倒退、重复值均拒）、`SQL_LOAD_ORDER` 追加项不得重复同一 SQL 路径；顺序满足 `… workspace_admit < frontier_gap < goal_supervise < fair_claim`。其余 `protected` 文件仍逐字节等于 `fb295ac`。收紧钉的是「允许追加什么」，不是整文件 blob——裁决的「追加式」框架不变。
- **唯一谓词族，不写平行检查**：新函数 `r1_load_append_ok()`（load 子谓词：输入基线 load 文本、当前 load 文本、受跟踪路径集，输出判定）与 `r1_phase_d_prefix_allowance()`（主谓词：extra 分流 + known 字节钉 + fresh 闭集 + test AST + README 纯追加，内部调用 load 子谓词）。`r0_source_scope()`（load 基线 `fb295ac`）与 `test_goal_supervisor.py::test_stage_bytes`（load 基线 `R1` = `93a49cd`）**调用同一个 `r1_load_append_ok`**，各自传入自己的基线文本——不复制第二份实现。所有输入以参数传入（内存数据），不写仓库文件。合成用例闭集（喂变异输入期望拒绝，喂活体形状期望接受）：
  - 路径面：`v13/not_allowed/x.py` 拒；`fresh` 空集收（提交②形状）与恰为 `v13/goal_supervisor/accept_unattended.py` 的一元集收（提交③形状）；`known` 中 `driver.py` / `setup_db.py` / 任一 fair 文件改动一字节拒；`fresh` 出现第二个新文件拒。
  - load 面：活体两行追加收；含 `-` 行拒；`load_stage` 函数体内插入一行拒（插入非规范形态行时由形态穷尽拒；插入**本身符合规范形态**的行时由「`+` 行集合与解析出的追加项一一对应、数量相等」拒）；文件末尾新增顶层函数拒；表尾顺序倒置拒；追加项目录不在受跟踪集拒；`STAGE_THROUGH` 追加键无 `SQL_LOAD_ORDER` 对应项拒；反向（`SQL_LOAD_ORDER` 追加项无键）拒；重复键拒；两表追加数量不等拒；编号跳号拒；编号倒退拒；`STAGE_THROUGH` 两追加键同编号拒；同一 SQL 路径追加两次拒。
  - 文件面：`test_goal_supervisor.py` 既有函数体改一字节拒（`test_stage_bytes` 除外）；`run()` 内删除既有调用行拒；README diff 含 `-` 行或修改行拒。
  沿用 Reopen §4.3「不得用『目录在名单里』替代正向证明」。
- `goal_supervisor` 的 `test_stage_bytes` 中 `git diff R1 -- v13/load.py` 为空一条，改为调用 `r1_load_append_ok`（load 基线 `R1`，追加项须对应受跟踪 `v13/fair_claim/` 目录）。冻结目录相对 `R1` 的空 diff **保留**；开工时若该空 diff 已非空：停。
- R0 哨兵还原、`CREATE OR REPLACE` 次数、`r1_driver_restore`、`r1_freeze_positive_proof`、返回基线串——全部不动。

## 3. 设计裁决

| ID | 裁决 | 不是 | 依据 |
|---|---|---|---|
| D0 | 父三裁决：旧 gate ASK_USER 原样保留（A）；轮数预算 2；load.py 追加式 | 不是把授权塞进旧 gate、不是 8 轮、不是钉 blob | real provider 先例形状；种子纪律；`tail_ok` 先例 |
| D1 | 验收机器 = 新增 env 门控脚本 `v13/goal_supervisor/accept_unattended.py`，不扩展现有 gate | 不是改 `main()` 尾部、不是单进程双形态 | 现有断言（M3 实跑 62 checks）与 ASK_USER 负例必须原样保留（R1-M3 §9.5；矩阵 M3 行）；两形态同进程会互相污染 |
| D2 | 无人值守新增的是**有界 2 轮循环**，只活在授权脚本内 | 不是生产 runner/daemon、不是 `pg_cron`、不是 sleep 循环 | `tick` 从不 ask_user，缺的只是循环驱动；生产循环属另一份计划 |
| D3 | 唤醒策略 = 按轮重读的**轮询**，不消费 wake；V11 保持未读 | 不是解析 wake jsonb、不是订阅 | `v13_wake_is_satisfied_v1` 的 `event` 变体缺 `effect_done` 直接 RAISE（`v13/spawn/v13_spawn.sql:821-824`）；tick 从不调用它（B6 表「本 tick 默认不调用」） |
| D4 | 矩阵**分行**：原 `expected_nonzero` 行逐字保留 + 新增 `## UA 授权增补（2026-10-01）` 小节，行名 `unattended_authorized_exit_0`，状态词只用既有 `not_run`/`exit_0`/`expected_nonzero`；未授权负例行恒为 `expected_nonzero`，不经 `exit_0` | 不是改原行状态、不是新状态词、不是 `real_authorized_exit_0` | Reopen §5.3「不把历史库名、计数、旧函数哈希覆盖成新值」；Phase C 表头「不设 real_authorized_exit_0」原样保留；矩阵文首「退出码 0 才写 exit_0」规则对负例命令天然排斥 |
| D5 | human pending 时循环**等待，绝不 skip** | 不是 `v13_complete(skip)`、不是 cancel、不是改写 status | Phase 0 T2「skip=true 是人工授权动作…不是无人值守权限」；Phase C §4.4「超时不自动写答案」 |
| D6 | `SUPERVISOR_MAX_TICKS = 2` 保持不变，循环每轮**新建** `GoalSupervisor` 实例、每轮恰一次 `tick` | 不放大常量、不新增同义产品常量 | `ticks_used` 是实例级计数（`driver.py:174-176`）；种子注释「soak，不是多日运行」；两套上界互相掩盖 |
| D7 | 授权脚本内建自有夹具与场景断言（`[PASS]`/`[FAIL]` 打印），不 import `test_goal_supervisor` | 不是共用 gate 夹具函数 | 负例纪律：fake gate 永不设授权变量；授权实跑由实现者在收尾时执行一次 |

## 4. 组件设计

### 4.1 `v13/goal_supervisor/accept_unattended.py`（新增，唯一新机器）

**形状完全对齐 `v13/real_chain/accept_real_provider.py`**（仓库唯一授权验收先例）：拆字面环境变量、未授权 `return 2` 固定消息且发生在任何重导入之前、`authorized_main()` 内才建库、`finally` 只 DROP 本次创建的库、可数证据输出。

**授权门**：

- 变量名 `V13_UNATTENDED_AUTHORIZATION`，源码以拼接构造（同 `accept_real_provider.py:17-25` 的 `auth_var()` 手法），判定 `os.environ.get(...) == "1"`。`unset`/`""`/`"0"`/`"true"`/`"yes"` 一律未授权。
- 未授权路径：stdout 恰一行 `v13: unattended continuation not authorized`，退出码 **2**。不 import `psycopg2`/`GoalSupervisor`/`server`（重导入全在 `authorized_main` 内）、不建库、不执行 SQL、不开网络。模块顶层只允许 `os`/`sys`/`pathlib` 级轻导入。
- 无与授权正交的凭据检查：本脚本不读、不打印 API key。扩展缺失、库名冲突、场景失败都是退出码 1，消息与「未授权」分开。

**库生命周期**（独立实现，不调用 `setup_db.main()`、不占 `ll_goal_supervisor_*` 全局 `DB`）：

- 库名 `ll_unattended_accept_<pid>_<token_hex(3)>`；`agent_v13_%` 前缀或 `agent_v13_longloop_p0_probe` 拒绝（退出 1，不建库）；已存在拒绝不 DROP。扩展探针同 `setup_db.probe_extension`（stannum + pg_jsonschema）；缺失退出 1，不换装共享安装。
- **库生命周期两支**（复审 P1 修，消除 preset 与 DROP 证据的矛盾）：
  - **自建支**（默认；矩阵授权行只认这一支）：`CREATE DATABASE` 成功即置 `CREATED=True` → `load_stage(server, db, "goal_supervise")` 装 **stage 38**（不装 `fair_claim`——验收不需要领用函数，本脚本不调 `v13_claim_fair`）→ `finally` 只 DROP 这一只（DROP 前关闭指向它的全部连接），再另起一条到 `postgres` 的连接查 `pg_database` 确认名字消失，否则退出 1；stdout 打 `[dropped] <db>`；`accept_database_dropped` 的 DROP 断言只在这一支适用（preset 支断言名字仍在，§4.3 已按分支写）。进程被杀留孤儿库时不扫前缀、不恢复，操作员手工 DROP 该具体名字。
  - **preset 支**（`V13_UNATTENDED_DB`，形状同 `accept_real_provider.py` 的 `V13_REAL_CHAIN_DB`，加一处收紧）：库必须已存在、不得 `agent_v13_%`、**且库名必须以 `ll_unattended_preset_` 开头**（专用命名空间——本脚本往库内写场景夹具数据，比 real provider 先例更紧，防指向任何非专用库；不满足退出 1 不动该库）、须已装到 stage 38（跳过 CREATE 与 `load_stage`）；`CREATED=False`，成功/失败/异常都**不 DROP**；断言名字仍在；stdout 打 `[kept] <db>`，不打 `[dropped]`。**取证纪律（可执行，不是入口拒绝）**：授权=1 且该变量已设时 preset 支正常可达、可退出 0——**不得**实现成「已设即入口退出 1」（否则 preset 支不可达）；但 `[kept]` 行是「非矩阵证据」的自声明标记：矩阵 `unattended_authorized_exit_0` 行的证据必须来自 `env -u V13_UNATTENDED_DB` 命令形态（§6.2 写死）且 stdout 含 `[dropped]`、不含 `[kept]`；§4.4 断言 `unattended_matrix_row_requires_dropped` 机械核对该纪律落在矩阵与 README 文本上。命名空间是操作者承担的隔离前置条件：脚本证明的是『名字声明为专用』，不证明所有权或空库状态；preset 是调试便利支不作证据，指向风险由操作者自担。

**证据 stdout**（授权进程退出 0 时固定行，便于矩阵抄录）：

```text
authorization 1
rounds_cap 2
provider_calls 0
database <实际库名>
scenarios <每场景 stop_reason / rounds_used / settle_once / advance / receipt 终值>
<§8 固定声称句>
[dropped] <实际库名>（自建支）或 [kept] <实际库名>（preset 支，不作矩阵证据）
```

禁止出现「产品可用」「人可以离开生产终端已经成立」类句子。

### 4.2 有界循环（2 轮）

常量 `UNATTENDED_ACCEPT_ROUNDS = 2` 只放在验收脚本内；`driver.py` 的 `SUPERVISOR_MAX_TICKS` 保持 2。二者同值是故意的：验收轮数不超过 Phase C §4.8 那颗「soak，不是多日运行」的种子。

一轮 = 新建一个 `GoalSupervisor`（自有连接 + 仅供 `settle_once` 的 `LoopDriver`）→ **恰好一次** `tick` → 收集 report 与 `sup.calls`/`sup.settler.calls` → `close()`。禁止同实例二次 tick、`while True`、`time.sleep`、`pg_cron`、`threading`；轮间无墙钟等待。夹具连接与监督连接分开，夹具 commit 后才 tick，夹具不得在 tick 期间持该根行锁。单线程；不复现 gate 的 `pg_blocking_pids` 交错（那两条留在 gate）。

**停止规则**（按序命中即停；规则中的「未付」一律读 `report["unpaid"]`——tick 开头、结算**前**的快照（`driver.py:193-196`）；tick 后只读的 `unpaid_after` 仅作证据记录，不参与停止判定。只有快照读法与 §4.3 场景自洽：结算轮快照非空 → 不命中安静规则 → 开下一轮观察）

1. `tick` 抛 `SupervisorFail` 且消息恰为 `UNPAID_REMAINING` → `stop_reason = "unpaid_remaining"`（期望该失败的三场景中，观察到该失败才算断言通过）。
2. 其它异常 → 打印异常类型与消息，退出 1，`finally` 仍 DROP；不转换成 `waiting`。
3. `report["word"] == "skipped_failed"` → `stop_reason = "skipped_failed"`，不再开下一轮。
4. `report["word"] ∈ TERMINAL_STATUS` → `stop_reason = "terminal"`。
5. `word == "waiting"` 且 human 列表非空且未付（本轮 `report["unpaid"]` 快照）为空 → human 挂起：未到第 2 轮则继续；已到上界 → `stop_reason = "human_pending"`，`final_word = "waiting"`，**退出码 0**（D5：等待即合法终局）。
6. `word == "waiting"` 且未付空且 human 空 → `stop_reason = "stable_waiting"`。
7. 2 轮用尽未命中 3–6 → `stop_reason = "round_cap"`：仅在「场景期望早停却没停」时出现，该场景判失败、退出 1。human 场景期望的是第 5 条在上界处停。

`stop_reason` 闭集：`{stable_waiting, human_pending, skipped_failed, terminal, unpaid_remaining, round_cap}`。不发明 B1 的 `wait`/`user_action`/`provider`/`stopping`。

**轮次轨迹注**：finish 第 1 轮结算后同轮 `report["word"]` 仍为 `waiting`（tick 入口读的 status 不再重读），`terminal` 只出现在第 2 轮新实例重读后；progress+human 第 1 轮快照非空，规则 5/6 均不命中，靠「未命中则进入下一轮」进入第 2 轮，第 2 轮快照已空且 human 仍在才在上界命中规则 5——两轮都要实际 tick。

每轮记录：`word`、`settle_word`、`request_stop_consumed`、该轮 `settle_once` 计数（须 ≤1）、该轮 `v13_advance` 计数（须 ≤1）、tick 后只读的 `unpaid_after` id 列表、human effect 的 status 列表、`wake_calls`（须恒 0）。每轮结束连接必须 IDLE。`wait` 结果的 harness 不是未付候选（谓词只认 `progress`/`finish`）：循环看到它走安静或 human 路径，不等 `not_before`、不解析 wake jsonb（D3 有意降级）。

**两类已记录的既有 tick 行为**（不改、不新增早退）：(a) ambiguous-hold 根在循环里归 `stable_waiting`——tick 对 hold 返回 `waiting`，循环不 accept/recover，等待即观察；(b) finish 第 1 轮结算后 tick 仍继续执行 `v13_recover_idle` 与只读投影（`driver.py:240-258`，该写对已终态会话是既有良性行为，M3 断言已覆盖），循环不因此判失败。

**错误与边界**：

| 情况 | 行为 | 恢复/约束 |
|---|---|---|
| 未授权 | 退出 2 固定消息，零库 | 显式设变量为 `1` |
| 扩展缺失 / 库名已存在 | 退出 1，不建库/不动原库 | 补扩展（不换装共享 stannum）；不 DROP 他人库 |
| 场景断言失败 | 退出 1 打 `[FAIL]` 名，finally DROP 本库 | 修夹具或停；禁止改 exit 0 |
| `unpaid_remaining` 出现在期望它的三场景 | 该断言通过，根保持未付，库最终 DROP | 不把 tick 改成返回 waiting |
| `unpaid_remaining` 出现在其它场景 | 退出 1 | 停；不改 `v13_advance` 消化 unknown/cancel/stale |
| `max_ticks` | 退出 1 | 保持每轮新实例、每轮一 tick；禁止放大常量 |
| 死锁/timeout/其它 DB 错 | 退出 1 原异常文本，事务回滚、连接 close、库 DROP | 不 `except` 成 `waiting` |
| human 挂到第 2 轮 | 退出 0 带 `human_pending` | 不 skip、不 complete、不 cancel |
| 安静根 | 第 1 轮即 `stable_waiting`，退出 0 | 不凑满 2 轮 |
| 第二轮重复结算 | 断言失败（收据必须仍 1） | 幂等由 SQL 承担 |
| 空/单候选举例 | 空未付空 human 空 hold → 第 1 轮 stable_waiting；恰一候选 → 结算后复读清空 | `lease_effect_id` 循环内恒不传（不调 `v13_goal_lease_once`；gate 的 `no_lease_loop` 仍覆盖传入路径） |

### 4.3 场景与断言（授权脚本内，`[PASS]`/`[FAIL]` 打印，任一 FAIL 退出 1）

夹具私有构造（不 import gate）：`route_policy_name=default, version=2` 开根 → `user/message` → `v13_submit_override(intent=direct)` → `v13_enqueue_effect` → 领取形 `UPDATE` 只出现在夹具函数 → 5 参 `v13_complete`。监督进程路径不出现该 `UPDATE`；禁四类裸 `INSERT INTO effects|events|sessions|artifacts`；源码不出现 `turn/material_spent` 字面（计数用 SQL 参数拼接，同 gate `spent()` 手法）。

| 断言名 | 场景与期望 |
|---|---|
| `accept_quiet_stable_waiting` | 只有根无未付：`stable_waiting`，`rounds_used=1`，`settle_once=0`，`v13_advance=0` |
| `accept_progress_second_round_quiet` | 未付 `progress`：第 1 轮 `settle_once=1`/`advance=1`/该 effect 收据 0→1；第 2 轮未付空、双计数 0、收据仍 1；`stable_waiting`，`rounds_used=2` |
| `accept_finish_observed_next_round` | 未付 `finish`：第 1 轮 `advance=1`、收据 1；第 2 轮 `sessions.status` 必须 `completed`、`word`=该 status、`settle_once=0`、`terminal`。第 2 轮不是 `completed` 即停，不改期望迁就 |
| `accept_human_pending_no_skip` | 未付 `progress` + human `ready`，每轮 `request_stop=True`：两轮 `word=waiting`；第 1 轮结算一次收据 +1、human 仍 `ready`；第 2 轮 `settle_once=0`；两轮 `request_stop_consumed=false`；`goal/stopped` 计数 0；human 未被 complete/skip/cancel、status 不变 `unknown/succeeded/failed`；`human_pending`，`rounds_used=2`，退出 0 |
| `accept_round_cap_stops` | 同上夹具观测：`rounds_used` 恰 2，不开第 3 轮 |
| `accept_human_unknown_no_skip` | 无未付；human 置 `unknown`、session `blocked_unknown`：两轮 `settle_once=0`、`waiting`、human 仍 `unknown`；`human_pending`（不是 `unpaid_remaining`） |
| `accept_skipped_failed_stops_round` | 先 `v13_goal_stop`（断言返回载荷 `schema_version=1`）再把 harness `result.failed` 写成 JSON `false`、`request_stop=True`：`rounds_used=1`、`skipped_failed`、advance 0、收据 0、`resolve/failed` 不变、calls 无 `v13_goal_lease_once`/`v13_recover_idle`/`v13_replan_gap_insert`/`v13_goal_stop`、`request_stop_consumed=false` |
| `accept_unpaid_remaining_unknown` | gate 同款 unknown 墙夹具（未付 + human claimed 置 `unknown`、session `blocked_unknown`）：`unpaid_remaining`、消息恰 `UNPAID_REMAINING`、收据 0、候选仍在；该轮 `settle_once=1`，advance 次数按该轮 `settler.calls` 实际计数断言（收据 0 不推出 advance 0） |
| `accept_unpaid_remaining_cancel` | 未付后 `v13_cancel(sid)`：同上期望（`settle_once=1`、advance 按实际计数） |
| `accept_unpaid_remaining_stale` | 该轮 settler 设 `_r1_before_advance` 钩子内再 `v13_submit_override`（同 gate stale 夹具）：同上期望（`settle_once=1`、advance 按实际计数）；钩子只设在该轮新实例 |
| `accept_one_settle_once_per_round` | 逐轮 `settle_once` ≤1 且等于该场景期望 |
| `accept_at_most_one_advance_per_round` | 逐轮 `v13_advance` ≤1 且等于期望 |
| `accept_no_real_provider` | 每轮 `getattr(sup.settler, "llm", None) is None`；输出 `provider_calls 0` |
| `accept_database_dropped` | 按分支断言：自建支 DROP 后 `pg_database` 无该名且 stdout 含 `[dropped]`；preset 支名字仍在且 stdout 含 `[kept]`（不 DROP，该支不作矩阵证据） |
| `accept_claim_ceiling_sentence` | stdout 含 §8 固定声称句 |

`unpaid_remaining` 三场景是「观察到失败才算通过」：授权不把 tick 失败改成成功 report；tick 未抛该消息则对应断言失败、退出 1。human 场景退出 0——父允许的声称就是「人不回答时保持 waiting、不 skip，且授权进程可 exit 0」；报告必须写出 `human_pending`，禁止只打成功不写挂起原因。

### 4.4 既有 gate 的负例与静态断言（`test_goal_supervisor.py`，`main()` 尾部不动）

该文件**不在** `r0_source_scope` 的 fb295ac AST 冻结集（四份冻结测试是 plan_arm/frontier_gap/goal_supervise/loop_driver），但按 §2.3 新增**相对 `78e77c7` 的 AST 追加式**：既有顶层函数字节钉（唯一例外 `test_stage_bytes`）、`run()` 只追加 `unattended_*()` 调用行、新顶层函数自由（沿既有 snake_case 描述风格）；`main()` 尾部三行与既有断言（M3 实跑 62 checks）逐字保留。

| 断言名（gate 侧） | 内容 |
|---|---|
| `unattended_script_refuses` | 子进程**复制环境后先弹出该变量**再套三态（缺变量/`"0"`/`"invalid"`，防实现者 shell 已导出 `1` 被继承），均退出 2；stdout 去首尾空白后恰一行固定消息；不含 `authorization 1`、不含 `[ready]`；未建库 |
| `unattended_script_head_has_no_network` | 以 `def authorized_main` 切开的头部不含 `urllib`/`socket`/`requests`/`http.client`/`openai`/`anthropic`/`deepseek`，亦不含 `psycopg2`/`server`/`GoalSupervisor`/`v13.load`（重导入只在 `authorized_main` 内） |
| `unattended_fake_gate_does_not_set_authorization` | `test_goal_supervisor.py` 源码不把该变量设为 `1`；仍含 `ASK_USER = "v13: supervisor: ask_user"` 与 `raise SystemExit(ASK_USER)` |
| `unattended_prior_asserts_retained` | 既有 `check(` 标签集合仍完整出现（快照钉在实现时，含 `settle_once_not_run_turn`、`named_entry_is_settle_once`、`unattended_not_claimed_by_loop_alone`、`fake_hop_persists_then_observed`、`stopped_failed_snap_no_advance`、`skipped_failed_safe_return_no_lease_recover_replan`、`waiting_with_unpaid_remaining_is_failure`、`human_wait_no_skip`、`request_stop_not_consumed_on_human_wait`、`stop_advance_interleave_stop_wins` 等全部既有标签） |
| `accept_script_no_wake_token` | `accept_unattended.py` 源码不含 `v13_wake_is_satisfied_v1` |
| `accept_script_no_sleep_no_cron` | 该源码不含 `time.sleep`、`while True`、`pg_cron`、`threading` |
| `accept_script_no_provider_tokens` | 该源码不含 `openai`/`anthropic`/`deepseek`/`requests` |
| `accept_script_round_cap_is_two` | 源码含 `UNATTENDED_ACCEPT_ROUNDS = 2`；`driver.py` 仍含 `SUPERVISOR_MAX_TICKS = 2` |
| `accept_script_under_goal_supervisor_prefix` | 路径恰为 `v13/goal_supervisor/accept_unattended.py` |
| `unauthorized_never_fills_authorized_row` | 矩阵纪律：负例断言永不填 `unattended_authorized_exit_0` 行；该行只在实际授权命令退出 0、库已 DROP、证据齐全后才从 `not_run` 转 `exit_0` |
| `unattended_matrix_row_requires_dropped` | 矩阵 UA 小节：授权行命令列含 `env -u V13_UNATTENDED_DB`；证据列含具体标记 `[dropped] ll_unattended_accept_` 且不含具体标记 `[kept] ll_unattended_preset_`——**按带库名的具体标记检查，不做裸 `[kept]` token 子串**（避免命中『不含 [kept]』说明文字自反误判）；README 授权验收节含同款 `env -u` 命令。时序：矩阵/README 先更新、gate 断言后验（§7/§10 已排定该顺序）；被禁的具体 preset 标记只作为该断言源码里的检查针，**不写入矩阵/README 正文**（§6.4 模板已不含该字面量，否则自反） |

新增顶层扫描函数 `unattended_accept_script_scan()` 对 `accept_unattended.py` 做 **AST 调用位置扫描**（不是正则 token 扫描：ast.parse 后按 Call 节点归类其所属函数，字符串提及与注释不构成调用；`test_static` 本身不动，保持 §2.3 字节钉），**「执行」与「提及」分开**（避免扫描否定计划自己要求的观测）：

- **禁执行**（全文件不得出现 SQL/调用执行）：裸 `INSERT INTO` effects/events/sessions/artifacts、`pg_cron`、API key 字段名；`v13_advance`、`v13_harness_settle`、`run_turn`、`serve`、`v13_plan_writer`、`v13_wake_is_satisfied_v1`、`v13_claim_fair`。
- **可执行**：夹具函数与 stale 钩子（`_r1_before_advance` 内的 `v13_submit_override`——该调用发生在 `settle_once` 途中，放不进开跑前夹具，单列）可执行 `v13_open_session`、`v13_submit_override`、`v13_enqueue_effect`、`v13_complete`、`v13_goal_stop`、`v13_cancel`、`v13_append_event`、`v13_probe`，以及**夹具专用 UPDATE 形状**（沿用 gate 夹具原文，只许出现在夹具函数内）：领取形 `UPDATE`（claim 五字段）、`UPDATE effects SET result = result || …::jsonb WHERE effect_id=…`（skipped_failed 写 `{"failed": false}`）、`UPDATE effects SET status='unknown' WHERE effect_id=…`、`UPDATE sessions SET status=… WHERE session_id=…`（`blocked_unknown`）、`UPDATE effects SET status='claimed', lease_owner=…, lease_until='infinity' WHERE effect_id=…`（`fixture_unpaid` 的 human claimed 分支——三字段 infinity 租约，与 `settle()` 的五字段领取形不同，单列）；循环体对监督机只调 `GoalSupervisor.tick`/`close`（观测 SELECT 不算调用监督机）。
- **取证只读面**：`v13_unpaid_harness_turn`（`unpaid_after` 与「候选仍在」判定，该名已在 `driver.py` 的 `ALLOWED_V13` 内）+ 对 `sessions`/`effects`/`events` 的只读 SELECT（收据、`goal/stopped`、`resolve/failed` 计数，同 gate `spent()` 手法）+ `pg_database`/`pg_available_extensions` 生命周期查询。
- **断言可提及调用名**用于统计 `GoalSupervisor.calls`/`settler.calls`（如逐轮 `v13_advance` 计数；`wake_calls` 定义为调用名集合不含 `wake_is_satisfied`）；`skipped_failed` 场景的「calls 无 `v13_goal_lease_once`/`v13_recover_idle`/`v13_replan_gap_insert`/`v13_goal_stop`」仅指该轮 `GoalSupervisor.calls`，夹具事先执行的 `v13_goal_stop` 另计。

`driver.py` 的 `ALLOWED_V13` 15 项不动（不因「不调用 wake」而删 `v13_wake_is_satisfied_v1`）。

### 4.5 `r0_source_scope()` 定点扩展（提交②，详见 §2.3）

### 4.6 `v13/goal_supervisor/README.md`

`## B6` 表逐行逐字保留（`test_static` 按固定 `need` 列表逐行解析；`fourth-duty` 行继续含 `v13/plan_arm/v13_plan_arm.sql:332-804`）。

`## Gate` 段保留原义：该 gate 在其它断言通过后发出 `v13: supervisor: ask_user`，该非零是 `unattended_continuation` 的**历史接受形态**；矩阵 `goal_supervisor gate` 行不得写成 `exit_0`。其后新增 `## 授权验收`：命令与变量名（含 `env -u V13_UNATTENDED_DB` 取证形态与 `[dropped]`/`[kept]` 证据标记、preset 专用命名空间）、未授权退出 2 固定消息、授权退出 0 只代表 §8 声称句、循环在验收脚本内不在 `GoalSupervisor` 内、`SUPERVISOR_MAX_TICKS` 仍 2、V11 未读且脚本不调 wake 函数、无人值守 skip 与 `plan_commit` 仍未授权。B6「监督进程允许」列不写「循环 tick」——循环不是 `driver.py` 职责。

## 5. 文件级影响

| 文件 | 动作 | 内容 | 依赖 |
|---|---|---|---|
| `docs/plans/v13-unattended-continuation-authorization-plan-2026-10-01.md` | 本文件 | 父决定载体 | 无 |
| `v13/plan_arm/test_plan_arm.py` | 改 | §2.3：`r0_source_scope` 前缀闭集 + load 追加式 + 新函数 `r1_phase_d_prefix_allowance`（从 `r0_source_scope` 体内调用） | 提交②；四 gate 依赖 |
| `v13/plan_arm/README.md` | 改 | 冻结中心描述更新（三前缀 + 对应性追加式 + 正向失败证明） | 提交② |
| `v13/goal_supervisor/test_goal_supervisor.py` | 改 | §4.4 十一条 gate 侧断言 + `run()` 追加调用 + 新顶层扫描函数 `unattended_accept_script_scan`（`test_static` 不动，保持 §2.3 字节钉）；提交②只改 `test_stage_bytes` 的 R1-load 谓词为调用 `r1_load_append_ok`，提交③再加断言 | 提交②先落冻结修复 |
| `v13/goal_supervisor/accept_unattended.py` | 新增 | §4.1–§4.3 | 依赖前缀放行（M3 已放行 `v13/goal_supervisor/`） |
| `v13/goal_supervisor/README.md` | 改 | §4.6 | 断言名钉死后 |
| `docs/reviews/v13-long-loop-phase-c-conformance-matrix-2026-09-29.md` | 改 | §6.4 新小节；历史行逐字保留 | 提交③实跑后 |
| `docs/reviews/v13-long-loop-phase-c-deviation-ledger-2026-09-29.md` | 改 | §6.5 新段 + 预存红线归因（提交②记） | 同上 |

明确不改：`v13/goal_supervisor/driver.py`、`v13/goal_supervisor/setup_db.py`、`v13/loop_driver/**`、`v13/plan_arm/v13_plan_arm.sql`、`v13/goal_supervise/**`、`v13/frontier_gap/**`、`v13/load.py`（零字节变化）、`v13/real_chain/**`、`v13/fair_claim/**`、`v13/fair_driver/**`、`v13/spawn/v13_spawn.sql`、stage 1–39 既有 SQL、历史计划、`uv.lock`、`AGENTS.md`（其中 `extra` 内文件已由 §2.3 字节钉到 `78e77c7` 机械保护）。

## 6. 验收与命令

### 6.1 开工基线（13 条，零改动实跑，逐条记录退出码/库名/checks 数/失败断言名）

十条回归（§6.3 所列十 gate）+ `goal_supervisor` gate + `fair_claim` + `fair_driver`。预期四 gate 冻结红（§2.2）；fair 两 gate 应绿（Phase D 已交付）；其余应绿。`evidence_good_ref` 若因环境缺 `v13_artifact_land` 使 `goal_supervise` 非零：停，不删正例（M2 README 记录的具名写者）。

### 6.2 gate 与授权命令

```bash
# 既有 gate：接受形态不变——其它断言通过后 SystemExit('v13: supervisor: ask_user') 非零
UV_FROZEN=1 uv run python v13/goal_supervisor/test_goal_supervisor.py

# 未授权负例（三态：缺变量 / =0 / =invalid，均退出 2 固定消息零库）
UV_FROZEN=1 uv run python v13/goal_supervisor/accept_unattended.py

# 授权验收（实现者在提交③收尾执行一次；env -u 显式清掉 preset 变量——矩阵授权行只认自建支；
# 退出 0 + §4.1 证据 stdout + stdout 含 [dropped] 不含 [kept] + 库已 DROP）
env -u V13_UNATTENDED_DB V13_UNATTENDED_AUTHORIZATION=1 UV_FROZEN=1 \
  uv run python v13/goal_supervisor/accept_unattended.py
```

授权命令禁止放进 fake gate 的子进程；fake gate 只跑未授权子进程。`unattended_authorized_exit_0` 行初稿 `not_run`，实跑退出 0 后才改 `exit_0`，同提交完成「先跑再改矩阵再暂存」。

### 6.3 回归合同

十条回归（§6.3 所列十 gate：plan_contract/plan_read/plan_arm/loop_driver/workflow_bind/real_chain/workspace_admit/workspace_exec/frontier_gap/goal_supervise）+ `goal_supervisor` gate + `fair_claim` + `fair_driver`（两 fair gate 的 `test_*.py` 入口已跟踪存在，无需 not_applicable 分支）。

### 6.4 矩阵新增行（M3 小节之后，独立小节；以下为**跑后**形态——初稿 `unattended_authorized_exit_0` 与「预存红线修复」两行状态写 `not_run`，实跑退出 0 后才改 `exit_0`；负例行按其命令语义恒为 `expected_nonzero`）

```markdown
## UA 授权增补（2026-10-01）

| UA 项目 | 命令/库 | 实际证据 | 状态 |
|---|---|---|---|
| `unattended_authorized_exit_0` | env -u V13_UNATTENDED_DB V13_UNATTENDED_AUTHORIZATION=1 UV_FROZEN=1 uv run python v13/goal_supervisor/accept_unattended.py | 退出码 0；库 ll_unattended_accept_<…>（跑完已 DROP）；stdout 标记 `[dropped] <实际库名>`（该格整格不得出现 preset 标记字面量——禁标只作 gate 断言的针，见 §4.4）；rounds_cap 2、provider_calls 0、各场景 stop_reason/收据计数；§8 声称句 | exit_0 |
| UA 未授权负例 | UV_FROZEN=1 uv run python v13/goal_supervisor/accept_unattended.py（三态经 gate 断言） | 退出 2 固定消息；零库；零 provider import；fake gate 永不设变量——退出 2 是该命令的接受形态 | expected_nonzero |
| UA 预存红线修复 | §6.1 十三条修复前后两轮 | 四 gate 冻结断言红→绿，归因 Phase D 追加；十条回归 + fair 两 gate 修复后全 exit 0 | exit_0 |
```

`goal_supervisor gate` 主行与 M3 三行逐字保留（含 `expected_nonzero` 与旧库名/62 checks）。Phase C 表头「不设 `real_authorized_exit_0`」原样保留——新行不是那个词。历史 PC-C/R0/R1/M3 节不改数字。

### 6.5 台账新增段

`## UA 授权增补偏差与边界（2026-10-01）`：父决定记录（R1-M3 §9.5 由 2026-10-01 指令满足；三裁决 A/2/追加式）；预存红线逐条实跑归因；冻结放宽定点形状（三前缀 + load 追加式 + 正向失败证明）；循环边界（2 轮、每轮新实例、六类 stop_reason、human 不 skip、`unpaid_remaining` 仍失败、不消费 wake）；仍禁止清单（§8）。

## 7. 提交边界与顺序（严格按 AGENTS.md：测试全绿 → 收尾工件 → 按路径 add → commit → push）

1. **提交① 计划文档**：只 add 本文件。不冒充运行时 gate。
2. **提交② 预存红线修复**（仅当 §6.1 确认红；若四 gate 实跑全绿则跳过并在台账点名「推断被推翻」）：`v13/plan_arm/test_plan_arm.py`、`v13/goal_supervisor/test_goal_supervisor.py`（仅 `test_stage_bytes` 的 load 谓词）、`v13/plan_arm/README.md`（冻结中心描述）、`docs/reviews/v13-long-loop-phase-c-deviation-ledger-2026-09-29.md`（红线归因段）。要求：四 gate 冻结断言转绿 + 十条回归 + fair 两 gate 全 exit 0 + `goal_supervisor` 仍 ASK_USER 形态。若 `frontier_gap`/`goal_supervise` 有自身 `stage_bytes` 变红且失败行不是 `r0_source_scope`：停，不顺手改。
3. **提交③ 授权机器 + 收尾**：`v13/goal_supervisor/accept_unattended.py`、`v13/goal_supervisor/test_goal_supervisor.py`、`v13/goal_supervisor/README.md`、两个 review 文件。顺序：新增脚本 → gate 断言 → 未授权三态实跑 → 授权实跑 → **矩阵/台账/README 更新（含 `[dropped]` 具体标记证据）→ 原 gate 复跑**（ASK_USER 形态，N 增加；`unattended_matrix_row_requires_dropped` 此时后验绿——矩阵文本已先于 gate 复跑就位）→ 十条回归 → 按路径 add → staged 复查 → commit → push。提交③不得在提交②推送前开始（否则授权脚本失败与预存红混淆）。

每笔 `git diff --cached --name-only` 必须恰等于该笔允许路径。禁止 `git add -A`/`git add .`、`--no-verify`、force-push、`reset --hard`；暂存区不得出现未跟踪调查、`prompt-exports/`、停放草稿（`prompt-exports/phase-c-m3-parked-2026-10-01/`）、`uv.lock`、凭据。提交信息沿 `<版本>: <祈使句>`：`v13: record unattended continuation authorization plan` / `v13: allow phase-d paths in the v13 source freeze` / `v13: add authorized fake unattended acceptance`。

## 8. 允许声称与仍禁止

**授权脚本退出 0 之后**，README/矩阵新行/stdout 使用的声称句固定为：

> 单 goal、DB owner/superuser、Fake 夹具、轮数上界 2、无真实 provider：授权脚本可以 exit 0；人不回答时保持 waiting 且不 skip。这不是人可以离开生产终端。

可同时说的只有：结算仍走 `LoopDriver.settle_once`；`skipped_failed` 仍安全早退；unknown/cancel/stale 未付仍使 tick 失败，消息仍 `v13: supervisor: unpaid_remaining`；现有 gate 仍以 `v13: supervisor: ask_user` 结束。

**仍禁止写成已成立**：人可以离开生产终端（本父决定未写这句；无守护进程、无唤醒闭环、轮数上界 2、human 挂起只是报告）；产品角色/EXECUTE 闭合（夹具仍 DB owner/superuser，`execute_vs_control_operator_separated` 不改）；真实 provider、`V13_REAL_PROVIDER_AUTHORIZATION`、任何网络调用；PC-4/goal 级配额/无人值守多 spawn 预算（重开须另计划贴 gate 全文哈希）；V11 已读/auto-wake 已闭合/wake 已被消费；多 goal 公平、全局并发帽、多日 soak（Phase D 目录被放行只表示在树上，不表示本验收覆盖）；无人值守 skip（T2）；无人值守 `plan_commit`（T1.4，脚本不调 `v13_plan_writer`）；unknown/cancel/stale 墙已被 `v13_advance` 消化；exactly-once 通知/outbox/送达保证；现有 `goal_supervisor` gate 是 `exit_0`；把 `SUPERVISOR_MAX_TICKS = 2` 读成运行时长达标；授权脚本成功等同生产可用。

## 9. 停止条件

出现任一即停并更新计划复审，不得标绿、删断言或提交绕过：需要改 `settle_once`/`run_turn`/`serve`/`take_exit`/`decide`/R0 收据哨兵/`v13_advance` 任何分支；需要 `load.py` 新键或把 `goal_supervisor` 写成 stage；需要从 Phase A 前缀调 stage 38 helper；需要复制 B1 出口机或包装 `run_turn`；需要恢复停放草稿；需要自动 skip/complete/cancel human；需要调用 `v13_wake_is_satisfied_v1` 或声称 auto-wake；需要 `time.sleep` 决定锁胜者或等 `not_before`；需要用 ASK_USER、exit 0 或授权盖住真实失败；需要把冻结放宽成整个 `v13/` 任意新增或把 load 从追加式放宽成任意 diff；需要把 §2.3 的 known 字节钉、load 规范形态穷尽或 AST 追加式放宽成更弱检查（如退回纯前缀/纯无删除行）；开工实跑的红断言不是 §2.2 描述的冻结失败；`git diff 93a49cd -- <`test_goal_supervisor.py` 的 `frozen` 目录列表> 非空（该列表不含 `v13/load.py` 与 `fair_claim`/`fair_driver`——load 走对应性追加谓词、fair 目录走前缀闭集）；finish 场景第 2 轮 status 不是 `completed`；实现发现必须改 `driver.py` 才能在第 2 轮看见终态或 human；一次性库创建成功但清理无法确认。

## 10. 实施顺序

1. **基线取证（零改动）**：§6.1 十三条 + 基线对象核对 + 文件哈希记录。红集合不是冻结红即停。
2. **提交①**：本计划文件入库。
3. **提交②代码**：`r0_source_scope` 定点扩展 + `goal_supervisor` load 谓词 + 正向失败证明。结束时四 gate 冻结断言绿。
4. **提交②验证**：十条 + fair 两 gate exit 0；`goal_supervisor` ASK_USER 形态；确认 frontier_gap/goal_supervise 无需改自身 `stage_bytes`。写台账红线归因，按路径提交推送。
5. **提交③脚本与负例**：`accept_unattended.py` + gate 断言。先未授权三态（退出 2），再授权实跑；finish 第 2 轮非 `completed` 即停在本步。
6. **提交③收尾**：授权命令 exit 0 的库名/计数/`[dropped]` 具体标记写入矩阵新行 `exit_0`；台账写边界；README 含声称句与硬子串；**然后**原 gate 复跑 ASK_USER 且 N 高于提交②（历史矩阵 62 不改；矩阵/README 已先更新，`unattended_matrix_row_requires_dropped` 后验绿）；十条再绿；按五路径提交推送。

## 11. 保留的背景事实（规划期三路探索 + 亲验，实现时不再推导）

- **tick 解剖**（`driver.py:174-268`）：终态早退 → 未付恰一候选则单次 `settle_once`（多于一即 `unpaid_remaining`）→ `skipped_failed` 安全返回 → 复读未付仍在即失败 → human pending 返回 `waiting` 不消费 `request_stop` → `_maybe_replan`（`omitted_complete` 为真时至多一条 `v13_replan_gap_insert`，`frontier_hash` 原样透传，传输重试 2）→ ambiguous hold 只读 notify/observe → 一次 `v13_goal_lease_once` → 一次 `v13_recover_idle` → hint/should_run/plan_current/selected_todo/notify/observe 只读 → 仅未早退时 `v13_goal_stop`。写路径只四名：`v13_replan_gap_insert`/`v13_goal_lease_once`/`v13_recover_idle`/`v13_goal_stop`；结算写入只在 `settle_once` 内那一次 `v13_advance`。
- **`settle_once`**（`loop_driver/driver.py:467-553`，唯一 R1 哨兵块内）：`READ COMMITTED` → 根 `FOR UPDATE` → 非根拒绝 → lifecycle → `v13_harness_predecessor` → effect `FOR UPDATE` → 未付谓词重读 → T0 `t0_advance_blocked` 命中则 `skipped_failed` → 否则同事务至多一次 `v13_advance` → commit → IDLE 断言。测试钩子 `_r1_after_root_lock`/`_r1_before_advance`。
- **B6 禁令**（`README.md:11-34`）：ambiguous hold 只读；observation 禁代答；notification 只读 DTO；监督进程禁 INSERT effects/events、第二份 advance、`v13_harness_settle`、import `run_turn`；receipt 只经 `settle_once`；actor 禁 agent 身份自 skip；无密钥无文件系统 IO。
- **种子**：`supervisor_max_ticks = 2`（实例级，注释「soak，不是多日运行」）、`replan_transport_retries = 2`（非无界重试）。
- **Reopen §6 七要件已由 R1/M3 实现并断言**，本计划不重做。
- **授权先例**：`V13_REAL_PROVIDER_AUTHORIZATION=1` 未设退出 2 固定消息零网络（`accept_real_provider.py:17-30`）；fake gate 负例 `real_provider_script_refuses`（`test_real_chain.py:100-148`）永不填授权行；phase-A 矩阵 `fake_exit_0`/`real_authorized_exit_0` 分行；`DEMO_MODE=real`（`demo_v15/drive.py:646-652`）与 `--real-provider-smoke`（`v15/provider/smoke.py:21-23`）同构：授权=单一环境变量、与凭据正交、证据行带命令/退出码/一次性库名/可数指标/非声称句。
- **原技术缺口四项**中本计划只关两件：「没有有界外部重入的验收进程」与「gate 缺少授权 exit 0 形态」。唤醒面保持未接线（V11 未读）；human 挂起时循环只等待。
- **wake 函数**（`v13_spawn.sql:784-849`）：`children_terminal`/`event`（缺 `effect_done` RAISE）/`not_before`（`clock_timestamp() >= at`）/`artifact` 四变体 one-of；`tick` 不调用（B6「本 tick 默认不调用」）。

## Open Questions（残余，不阻塞复审）

1. `unattended_prior_asserts_retained` 的标签快照在实现时从活体文件生成并钉进断言——若实现时发现既有标签与本文 §4.4 示例不一致，以活体为准并在台账记录差异（§2.3 的既有函数字节钉已把标签对应的函数体一并钉住，该断言是双保险）。
2. 矩阵 UA 小节表头措辞（「UA 项目」列名）实现时可按既有小节风格微调，行名与状态词不变。

## References

- `docs/plans/v13-long-loop-phase-c-r1-m3-plan-2026-10-01.md`（§9.5 父改条款、§5.2 十步、§6 源码保护、§8 声称上限）
- `docs/plans/v13-long-loop-phase-c-reopen-advance-plan-2026-10-01.md`（§4.3 哨兵与正向证明、§5.3 提交纪律、§6 七要件）
- `docs/plans/v13-long-loop-phase-c-plan-2026-09-29.md`（§4.7 声称上限、§4.8 种子、§4.11 PC-4、§7.3 断言全集）
- `docs/plans/v13-long-loop-plan-2026-09-28.md`（T1.4、T2、T4/C6、T7）
- `docs/plans/v13-long-loop-phase-d-plan-2026-09-29.md`（§1 Phase D 不得编辑目录清单）
- `docs/reviews/v13-long-loop-phase-c-conformance-matrix-2026-09-29.md`、同目录偏差台账
- `v13/goal_supervisor/{driver.py,test_goal_supervisor.py,README.md,setup_db.py}`、`v13/plan_arm/test_plan_arm.py`、`v13/loop_driver/driver.py`、`v13/spawn/v13_spawn.sql:784-849`
- `v13/real_chain/accept_real_provider.py`、`v13/real_chain/test_real_chain.py:100-148`（授权先例三件套）
- `AGENTS.md`（里程碑提交顺序、外部 IO 不进事务、按路径 add）
