# v99/core Phase 0 覆盖矩阵

> W6 文档定稿，2026-10-21（文件名日期保持 2026-10-20）。计划 §10.7 的审查前两条完整命令退出 0、失败历史和只读 pair DE8A 的四项发现均保留；§10.8 已记录 R1–R4 修复及两条正式命令实际退出 0。W7 交付记录以包含本文件的唯一 Phase 0 提交及 `origin/v99` 引用为准。

权威：[计划 §7](../plans/v99-core-phase0-2026-10-20.md)。简称：`T`=`v99/core/test_core.py`，`S`=`setup_db.py`，`C`=`catalog.py`，`I`=`infrastructure_checks.py`，`P`=`contract_checks.py`，`R`=`review_checks.py`，均位于 `v99/core/`。下表保留此前具名断言映射、审查前运行证据及本次修正后的最终结果；R1–R4 另列新增具名回归，结果以 §10.8 真实退出码为准。

`T.state` 比较 runs/epochs/operations/effects/events/snapshots/wakes/requests 全行与关联 pins；`T.zero_write` 同时验证精确拒绝 DTO 及前后 state 相等。`P._database_state` 比较整个临时库上述九类协议表。只比较 revision 的旧测试不记为全状态零写。

## §7 常规分组

| 需求 | 具体函数与关键断言 |
|---|---|
| path/load 独立manifest | `S._self_check` 比较 loaded_files 恰00/10/20/30/40；before schema/relations为空，after schemas恰v99_core、extensions恰pgcrypto@v99_core。`I.test_historical_and_host_static_negatives` 扫实际loader/setup/catalog/SQL/Fake host并对v8/v13/pgmq导入、路径、SQL写负例 |
| catalog闭集 | `T.test_w5_catalog_and_guards` 精确11表/25索引/7触发器集合；`C.assert_function_catalog` 对独立EXPECTED_CORE_SIGNATURES比较函数名+输入类型；注入start(integer)必须ABI drift。ABI不包含返回类型/default闭集 |
| ACL/identity | `S._self_check/_assert_route_acl` 实际LOGIN非super/createdb/createrole、CONNECT真/TEMP假与route签名EXECUTE矩阵；`I.test_all_table_and_private_acl` 全11表七权限均假，三宿主实调SELECT/INSERT/UPDATE/DELETE/TRUNCATE均42501，schema/public CREATE TABLE/FUNCTION、TEMP、CREATE SCHEMA均42501 |
| caller/SET ROLE/遮蔽 | `I.test_set_role_real_caller` 非超级LOGIN降为reader后session_user不变，caller_role=reader，临时授予EXECUTE仍start unauthorized，RESET后成功；`I.test_same_session_shadowing` 同会话设置全部控制表及认证函数pg_temp/public遮蔽，SET LOCAL ROLE operator，poll/start成功；再去掉temp验证public独立遮蔽 |
| PUBLIC/private/default ACL | `T.test_w5_catalog_and_guards` owner/definer search_path/PUBLIC EXECUTE drift=0；`I.test_all_table_and_private_acl` 全core函数角色矩阵及每个私有helper实调42501（STRICT用非NULL参数），service直接publish_snapshot拒绝；`I.test_fresh_object_default_acl` 不逐对象REVOKE的新函数/表/sequence对三宿主实调拒绝，函数PUBLIC EXECUTE为假 |
| start/replay/异常回滚 | `T.test_w3_control_fifo` start精确键、控制/admission UUID不同、revision=1；`P._control_replay_rollback` 注入events INSERT故障后整个库协议状态相等、无request/operation残留，同ID随后成功；四控制replay/冲突均验证状态不变 |
| poll只读/expired/零写 | `P._poll_wait` READ ONLY事务poll/wait成功，未知run和错actor均精确expired，state不变；READ ONLY steer得25006并回滚不留状态；`T.test_w3_validation` 错registration poll expired |
| wait八键/正文/游标 | `T.test_w3_control_fifo` 八键集合/单wake正文；`P._wait_contract` 两steering按first/second FIFO、重复cursor同wake/正文、terminal新epoch正文向旧waiter交付，消费后epoch_advanced，未来epoch invalid_wait_args、错registration expired且state不变、未知run expired、blocked_unknown actionable |
| wait双waiter/丢通知/timeout/零SQL | `T.test_w5_fake_worker_and_wait` 无LISTEN与LISTEN timeout八键；等待中真实pg_notify无关payload被观察但不决定返回，steer持久wake才触发；另一无listener waiter获同wake。非法参数用NoSQLConnection与替换call探针，listen真/假均不得进入SQL；正常返回finally IDLE；异常rollback/保留原异常未被这些正常路径断言证明，见R1。`T.test_closeout_wake` 无listener持久wake仍可读 |
| steer active/terminal/旧链 | `T.test_w3_control_fifo` active epoch1/queued真，旧LLM archived_stale且revision不变，新final completed，completed reopen epoch2/turn3，cancelled steer拒绝；`T.test_w3_instruction_and_old_tools` 两旧tool归档/revision不变/无next_turn、failed reopen epoch2、non-instruction use_respond零写 |
| respond human/ce/one-of/重复消费 | `T.test_w3_respond_and_unknown` human绑定effect/NULL driver pin，CE无human，false/answers成功、respond replay；`T.test_w3_instruction_and_old_tools` human/CE instruction消费后interaction空/turn2，late response零写mismatch；`P._response_contract` 七种合法body（含0/false/skip）与完整非法类型/null/空answers/skip非true/多选/extra/schema_version反例，非法body经真实operator拒绝且state不变 |
| worker T1/IDLE/T2 | `T.FakeHost.step` discover/claim/history→commit→IDLE，第二service bound claim拒绝；Fake前后_idle；`T.test_lease_fifo` 第二owner连接直接见claimed；`T.test_w5_fake_worker_and_wait` fail_t2+lost_commit最终完成且llm.calls=io_count=1 |
| Fake重试边界 | `T.test_w5_fake_worker_and_wait` DefinitelyUnsent一次后成功calls=2；ambiguous calls=1且blocked_unknown；只模拟确定未发/结果不明，不宣称真实transport验证 |
| receipt/fence/pin | `T.test_cas_pin` owner/driver/fence/attempt/context/catalog/request/digest/missing pin拒绝且state相等；`T.test_w3_validation` 公开receipt stale字段零写；`P._public_accept_rejections` 真实service公开accept错owner/旧fence/expired分别driver_required/stale_claim/driver_expired，state相等 |
| receipt闭集/大小 | `T.test_w3_validation` 逐字段缺失/extra、UUID、bool/string/负数/小数/整数溢出、LLM/error/tool args反例zero_write；`T.test_w5_utf8_limit` 多字节前缀规范化恰1048576接受；`P._size_revision` SQL实测多字节receipt恰1048577拒绝且zero_write |
| receipt replay/conflict/mismatch | `T.test_w3_tool_and_atomic_replay` takeover/catalog变更后同receipt响应与state完全相等；`T.test_w3_validation` receipt_conflict零写、绑定错误仅events+1且journal不变、同ID后续合法receipt可用；`P._unknown_wall` unknown原receipt replay零写，新receipt被wall拒绝，改原digest为receipt_conflict |
| 完整T2/未知异常/revision | `T.test_w3_tool_and_atomic_replay` successor工具准入、publication业务拒绝后state相等，未知P0001必须抛出/回滚，移除故障同receipt成功；`P._size_revision` T1提交后第二连接推进snapshot revision但保留driving，accept发布用新revision+1而非T1缓存值 |
| tool顺序/唯一Fake工具/非法零写 | `T.test_w3_tool_and_atomic_replay` task one/two FIFO、最后才next LLM/continuation_from；`T.test_w3_validation` 未知工具/非法task闭集零写；`T.test_w5_fake_worker_and_wait` Fake全链LLM=2/tool=1 |
| 当前工具失败链（失败history另见R4） | `I.test_current_tool_failure_cancels_successors` 三工具中间失败：第一个succeeded/completed，第二failed/completed，第三cancelled/archived/upstream_failed/attempt0；无新admit_turn、无pending，failed seal无unsettled/unknown，discover run_not_running且state不变 |
| worker history/实际消费（成功tool；失败tool缺口见R4） | `I.test_history_projection_and_fake_consumption/_assert_history` 顶层与event键闭集、seq排序唯一、等于数据库五类事件投影且确实滤掉审计、读前后state相等；ConsumingLLM实际断言tool/result、human/responded、跨epoch1/2历史，calls=4/tool=1/IO=5 |
| cancel/unknown/lost-COMMIT | `T.test_unknown_cancel` 三seal数组、claimed保留/fence+1、cancel operation completed、late审计两次不写journal；`T.test_lease_fifo` takeover恢复/重复recovery幂等；`T.test_w3_tool_and_atomic_replay` 已提交journal接管后可读，`T.test_w5_fake_worker_and_wait` result保留重交IO=1，无journal旧claim由recovery转unknown |
| unknown wall/cancel-only | `T.test_unknown_cancel` enqueue/claim/正常closeout/succeeded settle unknown_wall；`P._unknown_wall` respond/steer及新succeeded/failed/unknown receipt全zero_write，原journal replay不变，改digest冲突；`T.test_w3_respond_and_unknown` unknown可cancel且cancel后仍replay原DTO |
| 取消后recovery/closeout | `T.test_unknown_cancel` cancelled保持、seal/snapshot/wake完全不变；`T.test_closeout_wake` pending/ready阻止terminal、interaction阻止closeout；`T.test_cas_pin` completed唯一terminal wake，unknown不能伪装成功 |
| no-network/provider/历史依赖/裸SQL | `T.test_w5_catalog_and_guards` host AST、包内AST、provider/dynamic import/curl/shell反例及AF_INET/AF_INET6拦截；`I.test_historical_and_host_static_negatives` 历史loader/pgmq负例及全部11表SELECT/INSERT/UPDATE/DELETE/TRUNCATE检测，projection调用允许。静态规则不是任意动态Python的完备证明 |
| setup/cleanup | `S._self_check` load_sql=False空catalog、DB/role错误OID拒绝且原对象在、退出后name/OID消失；`S._fixture_failure_checks` loader故障资源不泄露、原body异常对象及cleanup note保留；`I.run_group_lifecycle_checks` 预置group属性/OID/成员保留及异常group fail-closed，详见下表 |

## G1–G7 必须断言与补充销项

| 分组/要求 | 具体函数与关键断言 |
|---|---|
| G1 错owner/fence/expiry公开结算零写 | `P._public_accept_rejections` 非超级service提交三种拒绝，admin state前后相等；旧owner helper证据仍保留于`T.test_cas_pin/test_lease_fifo` |
| G1 service不可publish/operator不可worker | `I.test_all_table_and_private_acl` service直接publish_snapshot 42501、全函数角色权限矩阵；`T.test_w4_acl` operator实际driver_acquire 42501 |
| G1 human worker receipt拒绝 | `T.test_w3_instruction_and_old_tools` 未journal bogus operation绑定human，invalid_receipt且zero_write |
| G1 公开respond三lease态 | `P._response_contract` owner只准备absent/other_live/expired三lease状态，真实operator respond成功；driver三元组不变、恰一个human NULL driver pin |
| G1 human原子性/并发只消费一次 | `T.test_human_atomic` 第二连接ready/0pin、rollback state相等；`T.test_w5_concurrent_requests` 两respond仅一成功、respond/steer/cancel三竞争最多一次human/responded |
| G2 控制completed/仅执行pending/两个UUID | `P._control_replay_rollback` 四verb均出现且status completed/completed_at非空、控制pending数0、respond后pending仅admit_turn；`T.test_w3_control_fifo` 两UUID不同 |
| G2 FIFO/旧LLM/tool不发布/final/cancel | `T.test_lease_fifo` bound后项不得越过；`T.test_w3_control_fifo/test_w3_instruction_and_old_tools` 旧receipt归档/revision不变、final closeout；`T.test_unknown_cancel` cancel operation仍completed |
| G3 replay/冲突/行数与值 | `T.test_w3_tool_and_atomic_replay` replay DTO相等且整个state不变（覆盖effect/operation/event/wake/revision/journal/pin）；`T.test_w3_validation` digest冲突zero_write |
| G3 八键/非法UUID/溢出/1MiB多字节 | `T.test_w3_validation` bad_receipts循环；`T.test_w5_utf8_limit` exact1048576接受，`P._size_revision` exact1048577拒绝 |
| G3 非法tool/完整T2/IO一次/未知P0001 | `T.test_w3_tool_and_atomic_replay` successor/publication故障state全回滚、未知P0001不吞；`T.test_w5_fake_worker_and_wait` 重交不重IO |
| G3 lost-COMMIT/锁内revision | `T.test_w3_tool_and_atomic_replay` 已提交后过期接管catalog改变仍replay；`P._size_revision` 第二事务推进revision，公开accept正确加1 |
| G4 registration/continuity恒1/epoch/turn | `P._generation_attempts` runs/epochs generation实际值1、tool operation/effect turn=1；`P._wait_contract` initial→steering、generation1、terminal后turn增加；`T.test_w3_control_fifo` active不增epoch/terminal增加 |
| G4 并发attempt_seq/死字段transition | `P._generation_attempts` 三连接barrier steer全成功、count(*)=count(distinct attempt_seq)且>=10；无generation/owner_generation/reason/origin/superseded字段，更新superseded transition得23514，实际transition子集initial/steering |
| G4 wait全部附加合同 | `P._wait_contract` registration过期、未来epoch非法、跨epoch正文、FIFO与重复cursor；八键与多waiter由`T.test_w3_control_fifo/test_w5_fake_worker_and_wait`覆盖 |
| G5 直接unknown/replay/不能新结算 | `T.test_w3_respond_and_unknown` disposition unknown、blocked_unknown、replay原响应；`P._unknown_wall` 新receipt三status均unknown_wall且zero_write |
| G5 丢提交响应三类 | 已提交=`T.test_w3_tool_and_atomic_replay`；result保留未提交=`T.test_w5_fake_worker_and_wait`；无journal旧claim=`T.test_lease_fifo` recovery。仅协议模拟，无真实进程重启证明 |
| G5 wall/cancel-only/seal/取消后恢复 | `P._unknown_wall` respond/steer、新receipt拒绝；`T.test_unknown_cancel` claim/closeout拒绝、三数组、cancel后recovery不改seal/snapshot/wake、不复活 |
| G6 无effect lease/双driver/续租/过期 | `T.test_lease_fifo` lease列无、双driver恰一获租、续租fence不变、过期重获+1、旧结算失败、同run单claimed；`C.assert_function_catalog` claim无lease参数的固定输入ABI |
| G6 缓存discover竞态/接管先恢复 | `I.test_cached_discover_bound_claim` rival提交settle旧head后，缓存旧operation claim not_claimable且state不变，新head仍ready/attempt0/fence0/无pin，不改领；显式新head可claim。`T.test_lease_fifo` 新fence先不能越过旧claim，recovery后unknown_wall |
| G6 lease边界/短时deadline | `T.test_lease_fifo` 0/60001/NULL拒绝，1/60000有效；`T.expire` 2秒总deadline、无SQL sleep |
| G7 空库/catalog/跨run/基数/不可变 | `S._self_check` 跨run effect FK23503、llm附human合法、重复主要/human23505、event/pin/journal UPDATE/DELETE/TRUNCATE23514；精确catalog见T/C。组合引用测试不等于逐个FK均故障注入 |
| G7 notify commit/rollback/无listener/错序提示 | `T.test_closeout_wake` commit前无notify/wake、rollback无wake、commit payload run\|1、UNLISTEN后wake仍在；`T.test_w5_fake_worker_and_wait` 真实无关通知先到，后续steer表状态决定返回，两waiter同cursor可见 |
| G7 角色/SET ROLE/裸表/private/TEMP/CREATE | `I.test_set_role_real_caller/test_same_session_shadowing/test_all_table_and_private_acl/test_fresh_object_default_acl` 提供实际负例与新对象探针，非只catalog检查 |
| G7 Unix DSN/IDLE/可见claim | `S._fixture_failure_checks` 缺host/TCP/localhost/多host/hostaddr/service/错误socket均ValueError；实际socket为正例；`T.FakeHost.step/_idle/test_lease_fifo` Fake前后IDLE与第二连接见claimed |
| G7 meta/目录竞争/pin故障 | `T.test_lease_fifo` claim事务持meta SHARE令目录UPDATE 55P03，commit后可写；`T.test_cas_pin` context/catalog/request/missing pin零写拒绝 |
| G7 setup失败/OID/group/empty/原异常 | `S._fixture_failure_checks/_self_check` 处理loader故障/异常保留/OID/empty；`I.run_group_lifecycle_checks` 预置group `_created_groups={}`、属性OID不变、原成员保留、fixture只临时增加三个成员且退出后全快照相等；仅对本probe创建group注入LOGIN异常，setup拒绝且资源不变。若group均预先存在则不改它们，用新role验证异常group检查器 |
| G7 无provider/历史loader/网络 | `T.test_w5_catalog_and_guards` 运行socket/subprocess guards与包内AST；`I.test_historical_and_host_static_negatives` 增补历史引用与全部宿主控制表静态负例。libpq C层本地性由严格DSN证明 |

## Q1–Q12 销项索引

Q1–Q12 已逐项映射并由默认入口调用；计划§10.7保留审查前完整退出0，§10.8记录修正后两条正式命令于2026-10-21均退出0。以下具名断言是当前核对范围，不把它们推广为真实provider、生产进程树或libpq C层的证明。

| 原缺口 | 新增具名证据 | 历史基线与当前结果 |
|---|---|---|
| Q1 poll READ ONLY/expired/零写 | `P._poll_wait` | 审查前源码已核读；独立0且审查前默认完整gate 0；修正后默认完整gate 0 |
| Q2 wait FIFO/重复cursor/跨epoch/future/unknown | `P._wait_contract`；T现有timeout/双waiter/真实错通知 | 同上 |
| Q3 失败链/history消费 | `I.test_current_tool_failure_cancels_successors`、`I.test_history_projection_and_fake_consumption` | 审查前源码已核读；独立guards下0且审查前默认完整gate 0；修正后默认完整gate 0 |
| Q4 完整response one-of | `P._response_contract` | 独立0且审查前默认完整gate 0；修正后默认完整gate 0 |
| Q5 caller/遮蔽/private/默认ACL/CREATE | `I.test_set_role_real_caller`、`test_same_session_shadowing`、`test_all_table_and_private_acl`、`test_fresh_object_default_acl` | 审查前默认完整gate 0；修正后默认完整gate 0；保留真实默认PUBLIC EXECUTE缺陷及owner全局默认REVOKE修正事实 |
| Q6 四控制状态/replay/rollback | `P._control_replay_rollback` | 独立0且审查前默认完整gate 0；修正后默认完整gate 0 |
| Q7 exact+1/锁内revision | `P._size_revision` | 同上 |
| Q8 unknown公开拒绝矩阵 | `P._unknown_wall` | 同上 |
| Q9 预置group保护/异常拒绝 | `I.run_group_lifecycle_checks`（fixture外） | 审查前默认完整gate 0；修正后默认完整gate 0；保留对原先存在group不做故障变异的分支限制 |
| Q10 历史依赖/全部表SQL负例 | `I.test_historical_and_host_static_negatives` | 审查前默认完整gate 0；修正后默认完整gate 0，非动态Python完备性证明 |
| Q11 generation/turn/并发attempt/死字段 | `P._generation_attempts` | 独立0且审查前默认完整gate 0；修正后默认完整gate 0 |
| Q12 缓存discover后bound claim | `I.test_cached_discover_bound_claim` | 独立0且审查前默认完整gate 0；修正后默认完整gate 0 |

## 布局、集成与运行证据

`catalog.py` 是独立 ABI 预期资源；新增 `infrastructure_checks.py`、`contract_checks.py`、`review_checks.py` 是测试支持模块，均超出计划原始文件清单，已在偏差台账记录。17 文件范围为 v99/core 八个 Python、README、五个 SQL，加计划与两份 review 工件。三个支持模块接收活跃 T 模块参数，复用 helper 而不反向导入 test_core；`R.test_helper_lifecycle()` 在真实 helper 启动前运行，`R.run_checks(db,T)` 在 fixture 内运行。

当前`run_full`在父进程`unix_only_socket_guard(), subprocess_guard(), server_helper_scope()`内运行`R.test_helper_lifecycle()`、W2/W3/W4/W5、`I.run_checks(db,T)`、`P.run_checks(db,T)`和`R.run_checks(db,T)`；fixture退出后运行`I.run_group_lifecycle_checks(T)`，避免生命周期 advisory lock 嵌套。显式 helper 收尾成功后才打印 passed。

`setup_db.py`以`uv run python v99/core/setup_db.py --server-helper`启动常驻 helper；子进程持 pgembed handle，输出 JSON uri/socket/port 后等待 stdin EOF。父进程以单调 deadline 读端点、校验活进程、严格 Unix DSN、实际 socket 文件与 port；`_close_server_helper` 关闭 stdin 后执行 wait→进程组 TERM→wait→KILL→wait，未 reap 保留句柄供重试，强制终止/非零退出/清理错误使 gate 非零。`server_helper_scope` 在完整 gate 内显式收尾；atexit 是 guard 外后备，不证明整棵进程树受 Python guard 约束。

Python guards只约束父进程：AF_UNIX白名单、进程executable basename为psql/uv、禁shell/executable override。不跨进程继承，不拦截libpq C层调用；helper/uv/pgembed内部执行不等于受同一monkeypatch验证。libpq本地性由严格DSN/实际socket与port证据支持，helper的atexit收尾在run_full guard上下文退出后执行。静态扫描仅精确允许setup_db.py的subprocess import，仍检查其字面量uv启动调用；不把它描述为整个setup文件免检。

| 运行/修正事实 | 证据与结论 |
|---|---|
| W0–W3局部命令 | 计划§10已有真实退出码0及此前失败；不代表最终完整gate |
| W4/W5首次默认gate曾0 | 抽查随后发现guard/签名等缺口，不作为最终验收 |
| infra独立运行 | 协调者确认冻结模块在完整运行时guards下退出0；本W6未代跑 |
| contract独立运行 | 协调者确认冻结模块独立退出0，token/tok已修；本W6已重读实际tok使用，不推导为完整gate0 |
| 默认权限修正 | Q5新对象测试引出真实缺陷；40新增owner全局默认REVOKE，不再只用schema级REVOKE；保留发现/修正事实 |
| 主集成历史失败 | 首个fixture直接触发pgembed `postgres --version`被psql/uv白名单拦截；短命`uv run server.py uri`释放handle又使socket消失。最终常驻setup helper保留handle，父白名单未扩大 |
| `uv run python v99/core/setup_db.py --self-check` | **2026-10-21 修正后实际退出码0**，计划§10.8记录，含 review fixes 与 helper 显式收尾 |
| `uv run python v99/core/test_core.py` | **2026-10-21 修正后实际退出码0**，计划§10.8记录，含 Q1–Q12、R1–R4、guards 与 fixture 外 group lifecycle hook |
| 整体review | Oracle同chat两次interactive inactivity watchdog失败，无实质结论；随后只读pair DE8A完成首次实质审查，发现下列四项问题 |

## DE8A 新增审查问题与修正后验收（2026-10-21）

Oracle 失败尝试没有实质审查结论；实质整体审查已由只读 pair DE8A 完成。以下保留发现及实际修复后的具名回归；两条正式命令均已由主实现代理于 2026-10-21 实际退出 0。

| 项 | 发现及对应旧映射的限制 | 修正后具名断言与证据 |
|---|---|---|
| R1 ce_wait异常清理 | SQL/LISTEN 异常路径保留原异常并清理事务/监听 | `R.test_wait_exception_cleanup`：listen=False/True 的 22012、LISTEN 后注入异常均断言原 pgcode、连接 IDLE、无 listening channel；清理失败仅作 note。**完整 gate 0，异常替身路径非所有真实进程故障穷举。** |
| R2 helper超时回收 | helper 超时终止、句柄保留和清理错误传播 | `R.test_helper_lifecycle`：EOF 回收、TERM→KILL 三次 wait、未 reap 保留句柄可重试、启动/scope 原异常保留 note、uv 子探针清理失败 exit 1。**完整 gate 0；主要为 process/pipe 替身，不夸大真实进程树证明。** |
| R3 FakeHost实例driver隔离 | 每个 FakeHost 使用独立 driver，旧租约不能被另一实例冒用 | `R.test_fakehost_restart`：UUID driver 不同；有效 lease 时第二实例 driver_required 且零写/IDLE；过期接管 fence+1、旧 claim unknown、pin=1、无重复 Fake IO。**完整 gate 0。** |
| R4 failed tool history | failed tool/result 进入 history 且不产生 successor | `R.test_failed_tool_result_history`：当前失败链 history 含 tool/result error、后项 cancelled/upstream_failed；steer 后旧失败 archived_stale，下一 LLM 实际消费 error，恰一 failure event。**完整 gate 0。** |

R1–R4 均已由上述具名回归覆盖，并随两条正式完整命令于 2026-10-21 实际退出 0；这不扩张 Python guard 至子进程/libpq C 层，也不把替身测试称为真实进程树穷举。

本批 W6 未跑数据库 gate，仅核读源码与主代理交接；未改源码/计划、未另审、未另派、未 stage/commit/push。W7 交付记录以包含本文件的唯一 Phase 0 提交及 `origin/v99` 引用为准。Fake-only、unknown cancel-only、非exactly-once、无生产retention与进程/C层证据边界继续有效。
