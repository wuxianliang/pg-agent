# v99/core Phase 0

> W6 文档定稿，2026-10-21（文件名日期不变）。只读 pair DE8A 的 R1–R4 已修复，主实现代理确认修正后两条正式 gate 均实际退出 0，包含新增 review fixes 回归。审查前结果与失败历史保留；W7 交付记录以包含本文件的唯一 Phase 0 提交及 `origin/v99` 引用为准。

权威合同：[实施计划](../../docs/plans/v99-core-phase0-2026-10-20.md)。逐项测试证据见[覆盖矩阵](../../docs/reviews/v99-core-phase0-conformance-matrix-2026-10-20.md)，限制、历史缺口和文件集合变更见[偏差台账](../../docs/reviews/v99-core-phase0-deviation-ledger-2026-10-20.md)。W0–W7 是唯一里程碑，W2/W3 局部绿测不能替代完整验收；审查前两命令与失败修正已和计划 §10.7 追加记录核对；这不覆盖本次审查发现的异常路径与实例隔离问题。

## 对象与加载

包路径为 `v99.core`，schema 为 `v99_core`。独立 `load.py` 的 `CORE_SQL_LOAD_ORDER` 当前登记五个真实文件，顺序为：

1. `sql/00_extensions.sql`：隔离 schema 内安装 pgcrypto。
2. `sql/10_schema.sql`：11 张表、25 个索引、7 个业务触发器、固定 Fake 工具 seed。
3. `sql/20_ledger.sql`：lease、effect claim/CAS/pin、human settlement、unknown、wake、唯一 closeout。
4. `sql/30_ce.sql`：六动词、worker projections、receipt 完整 T2、replay。
5. `sql/40_permissions.sql`：宿主权限、PUBLIC 撤权与默认权限。

11 张表为 `core_runs`、`core_epochs`、`core_operations`、`core_effects`、`core_events`、`core_snapshots`、`core_wakes`、`core_effect_pins`、`core_requests`、`core_tools`、`core_meta`。四个支持模块补充原计划文件布局：

| 模块 | 用途与当前状态 |
|---|---|
| `catalog.py` | 独立固定函数名+输入类型 ABI 预期，不从已加载数据库反推；注入同名 overload 必须被检测。 |
| `infrastructure_checks.py` | 冻结的基础设施补充断言：失败工具链/history、ACL/caller/遮蔽、默认权限、历史依赖/宿主SQL、bound claim 与 group 生命周期。独立及审查前结果保留，已随本次修正后完整 gate 再次退出 0。 |
| `contract_checks.py` | protocol 补充断言覆盖 Q1/Q2/Q4/Q6/Q7/Q8/Q11、公开 respond 三 lease 态和 accept driver 拒绝；已随修正后完整 gate 退出 0。 |
| `review_checks.py` | R1–R4 具名回归及 helper 失败退出探针，已接入修正后默认完整 gate 并退出 0；不自行充当独立验收入口。 |

`review_checks.py` 新增四个具名回归函数，覆盖 wait 异常清理、helper 生命周期、FakeHost 实例隔离和 failed tool history。`test_helper_lifecycle()` 在真实 helper 启动前运行；默认 fixture 内依次执行 infra、contract、`review_checks.run_checks(db, test_core)`；fixture 退出后执行 group 生命周期 hook，避免嵌套获取 group 锁。

本里程碑范围共 **17 文件**：`v99/core/` 八个 Python 文件（`__init__.py`、`load.py`、`setup_db.py`、`test_core.py`、`catalog.py`、`infrastructure_checks.py`、`contract_checks.py`、`review_checks.py`）、README、五个 SQL，加本计划及两份 review 工件。范围不包含无关 dirty 文件。

`load_core(conn)` 不提交，拒绝 autocommit；manifest 拒绝缺失、symlink、额外未注册 SQL 和顺序漂移。不导入历史 v8/v13 loader，不追加历史 SQL_LOAD_ORDER，不迁移 v13 数据。

## 接口与事务合同

SQL 调用须带 `v99_core.v99_core_` 前缀。权限分工如下：

| 身份 | 入口 |
|---|---|
| operator | `start`、`poll`、`wait_check`、`cancel`、`steer`、`respond` |
| reader | `poll`、`wait_check` |
| service | `driver_acquire`、`discover`、`claim_effect`、`worker_history`、`accept_receipt`、`recover_unknown` |

`wait` 由 SQL `wait_check` 与测试宿主 `ce_wait` 组成；函数不阻塞等待。宿主不可裸读写控制表，不获得 ledger、human settlement、publication、closeout 等内部 helper 权限。真实 caller 来自数据库 role；actor 参数只检查目标关系，不构成租户身份。SECURITY DEFINER 固定 `search_path=pg_catalog,v99_core`。Q5 新对象探针曾暴露真实默认权限缺陷：仅 schema 级 REVOKE 无法扣除 PostgreSQL 全局默认 PUBLIC EXECUTE。当前 `40_permissions.sql` 已加入 owner 全局 `ALTER DEFAULT PRIVILEGES REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC`；infra 的新建函数/表/sequence 探针验证未经逐对象 REVOKE 仍不可被宿主访问，该探针已进入审查前退出 0 的默认 gate，缺陷发现和修正事实仍予保留。

Run 是唯一生命周期实体；epoch 是控制连续性，turn 是模型循环编号，operation 是控制/执行准入，effect 才是副作用账本。四种控制 operation 创建即 completed，仅执行 admission 可以 pending。registration/continuity 恒为 1；terminal completed/failed 的 steer 才增加 epoch，turn 跨 epoch 单调。

每个 run 只有一个 driver lease（1–60000ms），没有 effect lease。claim 绑定 FIFO operation，递增 attempt/fence 并写不可变 request/context/catalog/driver pin。active steer 在同 epoch 排队；旧 driving 的 receipt 可结算并归档，但不能发布新 snapshot 或产生旧链 continuation。cancelled 不可通过 steer/respond 复活。

Fake worker 顺序为 acquire/commit → recovery/commit → T1 discover/claim/history/commit → IDLE → Fake IO → IDLE → T2 `accept_receipt`/commit。T2 原子完成 ledger CAS、operation、结果事件、successors、publication/closeout 和 replay journal。未知 SQL 错误（包括非预期 P0001）抛出并回滚；已保留的 result 用同一 receipt 重交，不再执行 IO。

`core_requests` 保存完整协议响应。同 ID 同 digest 返回首次响应，已提交 receipt replay 不再检查新的 lease/pin/catalog 状态；冲突 digest 拒绝。通常业务拒绝零写，绑定错误的 `receipt/mismatch` 和取消后 `receipt/late` 是明确的审计例外，不占用 journal。

human respond/instruction steer 在一个 run 锁事务内 claim+CAS，pin 的 driver_fence 为 NULL，不借用 driver lease。CE interaction 不创建 human effect；worker 不处理 human receipt。respond 的 response 为 `schema_version:1` 加 `response`、非空 `answers` 或 `skip:true` 三者之一。

LLM→FIFO Fake tool→tool result→下一 LLM→final 是唯一正常执行链。唯一工具 `spawn_subsession` 接受 `task` 长度 1–1024 的闭集参数；返回 `adapter=ce-fake-spawn, simulated=true`，不创建子 run。receipt 严格八键，规范化 JSONB UTF-8 上限 1 MiB；具体 DTO、错误闭集以计划 §3.6 为准。

## Unknown、取消与 wait

数据库不保证外部副作用 exactly-once。有效 unknown receipt 或 driver 接管后对旧 fence 的 recovery 会进入 blocked_unknown，不自动重放。真正 unknown 的生命周期出口只有 cancel；无 resolve 入口。已提交但丢 COMMIT 响应应读 journal；未提交且 result 保留时重交原 receipt；result/claim 丢失且无 journal 时才走 takeover/recovery。

唯一 closeout 为 completed/failed 检查无 ready/claimed/unknown、interaction 和 pending admission；cancel 可以封口，但 seal 必须分别列出 cancelled、unsettled claimed、unknown IDs。取消不证明外部 IO 已停止。取消后迟到 receipt 只审计拒绝，后续 recovery 不复活、不改已存 seal/snapshot/wake。

poll/wait 读 snapshot/wakes；NOTIFY 只是可丢的提示。wait 固定八键，无顶层 ok；steering 正文放 snapshot.steering_message。每个 waiter 独立推进 wake cursor。`ce_wait` 使用短读事务、单调 deadline，等待前结束事务，当前 finally 对未关闭连接先 rollback 非 IDLE 事务，再 UNLISTEN/commit 并检查 IDLE；清理失败会再次尝试 rollback，有原异常时把清理失败记为 note，保留原异常。R1 的 SQL 与 LISTEN 初始化异常回归已随完整 gate 通过。`contract_checks._wait_contract` 已补齐 FIFO/重复 cursor、跨 epoch 正文、未来 epoch、epoch_advanced、错 registration 和 blocked_unknown actionable 的直接断言；这些断言随审查前默认完整 gate 退出 0；新增异常清理证据见 review_checks.test_wait_exception_cleanup，不把原正常路径证据代替异常回归。

## 执行与真实证据状态

在本工作树根运行；脚本创建并 DROP/CREATE 自己的唯一临时库，结束按数据库/角色 name+OID 精确清理。不要复用生产库。

```bash
uv run python v99/core/setup_db.py --self-check
uv run python v99/core/test_core.py
```

无参数 `setup_db.py` 等同 self-check。`--w2-only`、`--w3-only` 仅供局部诊断，不能替代上述两条完整命令。

| 证据 | 当前记录 |
|---|---|
| W0–W3 | 计划 §10.1–10.6 已记录局部真实退出码 0；保留此前失败与修正历史 |
| W4/W5 首次默认 gate | 协调交接记录曾退出 0，但抽查发现 guard/函数签名等覆盖缺口，该结果不作为最终验收 |
| infra 独立运行 | 协调者确认冻结版在运行时 guards 下退出 0；不等于主默认完整 gate 已通过 |
| contract 独立运行 | 协调者确认冻结版独立退出 0，token/tok 已修；Q1/Q2/Q4/Q6/Q7/Q8/Q11 的源码断言缺口已按矩阵销项 |
| 主集成历史失败 | 首个 fixture 直接触发 pgembed `postgres --version` 被 psql/uv 白名单拦截；短命 `uv run server.py uri` 又会在 handle 释放后使 socket 消失。最终改为常驻 setup helper，未放宽父进程白名单 |
| 审查前两条完整 gate | 计划 §10.7 实际退出码均为 **0**；随后 DE8A 发现 R1–R4，该历史不替代修正后复验 |
| `uv run python v99/core/setup_db.py --self-check` | **2026-10-21 修正后实际退出码 0**，主实现代理最终实跑交接 |
| `uv run python v99/core/test_core.py` | **2026-10-21 修正后实际退出码 0**，包含 review fixes 回归及显式 helper 收尾，主实现代理最终实跑交接 |
| 整体审查 | 同 chat 两次 Oracle 尝试因 interactive inactivity watchdog 失败，无实质结论；随后只读 pair 会话 DE8A 完成首次实质审查，发现四项问题 |
| 本 W6 | 仅整理三文档并核对主代理最终交接；未跑数据库 gate、未 stage/commit/push，未另发审查 |

当前 `run_full` 在 `unix_only_socket_guard(), subprocess_guard(), server_helper_scope()` 内运行 helper 生命周期探针、W2/W3/W4/W5、infra/contract/review 回归和 fixture 外 group 生命周期检查；完整 passed 文案在作用域退出、显式 helper 收尾成功后才打印。setup 自检也由 `server_helper_scope()` 包裹。

审查前核读的实际启动命令为 `uv run python v99/core/setup_db.py --server-helper`，不是 `uv run server.py uri`。`_server_helper` 在子进程获取并持有 pgembed handle，以 stdout 单行 JSON 返回 uri/socket/port，再阻塞读取 stdin。父进程缓存 helper，60 秒等待端点，校验 helper 存活、严格 Unix DSN、实际 socket 文件与 port 一致；各 fixture 仍独立按 name/OID 清理库和角色。当前 helper 以 `start_new_session=True` 启动；端点按单调 deadline 读取，默认 60 秒、上限 4096 字节。显式 `_close_server_helper(timeout=2)` 先关闭 stdin，随后有界 wait→进程组 TERM→wait→KILL→wait；未 reap 时保留全局句柄，reap 后检查残留进程组。强制终止、非零退出或清理错误都报失败，不能成为 gate 退出 0。`server_helper_scope` 保留主异常并追加清理 note；子 helper 在 finally 清理 pgembed handle、恢复 SIGTERM handler。atexit 仅为后备，后备清理失败明确 `os._exit(1)`。

父默认 gate 的 Python socket guard 拒绝 AF_INET/AF_INET6，subprocess guard 仍只按 executable basename 允许 psql/uv，并拒绝 shell/executable override。monkeypatch 不跨进程继承，不能证明 uv/helper/pgembed 内部子进程或 libpq C 层所有 socket 都被拦截；libpq 本地性证据是严格 DSN 和实际 socket/port 核验。正常 gate 的显式 helper 收尾现在位于父 guards 内；atexit 仍是 guard 作用域外的后备，且子进程与 libpq C 层边界不变，不能称整棵进程树全程受 Python guards 约束。

## DE8A 审查发现与修正后验收（2026-10-21）

Oracle 同 chat 两次 interactive inactivity watchdog 失败、无实质结论；随后只读 pair DE8A 完成实质审查。四项均已按下列具名断言修复并由主实现代理完整实跑验收 0，未另发审查。

| 项 | 审查发现 | 修正后具名回归（完整 gate 0） |
|---|---|---|
| R1 | ce_wait 异常未 rollback/清理遮蔽原异常 | `test_wait_exception_cleanup`：SQL 22012 在 listen 真/假均保留，连接 IDLE、无 listening channel；LISTEN 执行后注入异常仍保留原因并清理。 |
| R2 | helper 超时不终止/丢句柄 | `test_helper_lifecycle`：EOF 正常回收、TERM→KILL/三次 wait、强制清理报失败、未 reap 保留句柄可重试、启动错误与 scope 主异常保留 note、uv 子探针后备清理失败退出 1、helper handle finally 清理。进程状态主要使用替身验证，不夸为整棵真实进程树故障穷举。 |
| R3 | FakeHost 固定 driver ID 破坏实例隔离 | `test_fakehost_restart`：UUID driver 不同，活 lease 的新实例获租拒绝且零写/IDLE；过期接管 fence+1、旧 claim unknown、单 pin、无重复 Fake IO。 |
| R4 | failed tool 缺 tool/result history | `test_failed_tool_result_history`：当前链失败结果可读且后项 cancelled/upstream_failed；旧链失败 archived_stale，下一 driving LLM 实际消费 error，恰一失败结果事件。 |

两条正式命令已在 2026-10-21 修正后实际退出 0，包含 `[review fixes]`；W6仅核读源码及主执行交接，不代跑数据库 gate。W7 交付记录以包含本文件的唯一 Phase 0 提交及 `origin/v99` 引用为准。

## 明确边界

Fake-only，无真实 provider、API key、网络业务 IO、native spawn、goal/quota/完整 registry/workflow、parent/child 调度或 v13/v15 运行时依赖。数据库仅经经过严格验证的本机绝对 Unix socket DSN 连接，拒绝 TCP、hostaddr、多 host、service 和缺省 host。

没有生产级 driver 守护/重启编排、基于外部证据的 unknown resolution、exactly-once 或生产 retention。events/wakes/requests/pins 保留至整个临时数据库删除；无 TTL、reaper、在线压缩、生产归档。history 当前全量、不分页。原 Q1–Q12 的具体断言现已补齐并映射，审查前默认集成曾退出 0；整体实质审查及四项修复后的完整复验已完成，W7 交付记录以包含本文件的唯一 Phase 0 提交及 `origin/v99` 引用为准，上述范围边界继续有效。
