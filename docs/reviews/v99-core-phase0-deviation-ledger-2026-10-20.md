# v99/core Phase 0 偏差台账

> W6 文档定稿，2026-10-21（文件名日期保持 2026-10-20）。§10.7 两条完整命令退出 0、失败历史与 DE8A 发现保留；§10.8 记录 R1–R4 修复后两条正式命令实际退出 0。W7 交付记录以包含本文件的唯一 Phase 0 提交及 `origin/v99` 引用为准。

权威：[实施计划](../plans/v99-core-phase0-2026-10-20.md)。具体断言与缺口编号见[覆盖矩阵](v99-core-phase0-conformance-matrix-2026-10-20.md)。范围边界与测试覆盖状态已核对当前冻结源码及计划 §10.8 最终执行记录。

## 计划明确的范围边界

| ID | 边界/取舍 | 当前合同及影响 | 后续范围 |
|---|---|---|---|
| B01 | Fake-only | FakeLLM/FakeTool，不调用provider/API key/业务网络；spawn_subsession只返回ce-fake-spawn模拟结果，不创建子run或调用native handler | 真实provider、工具与外部副作用验证另立阶段 |
| B02 | 无goal/quota/完整registry/workflow | 仅run/epoch/operation/effect、固定工具目录及revision；不导入v13/v15运行时、历史loader或pgmq；无parent/child/approval调度 | 完整治理与工作流不属于Phase 0 |
| B03 | 无exactly-once | 仅本地effect CAS、receipt journal去重、fence失效检测；数据库无法证明外部请求是否执行。cancel seal不意味着外部IO停止或成功 | 外部幂等键/证据与provider合同需另验证 |
| B04 | 真unknown cancel-only | 有效unknown或takeover recovery后进入blocked_unknown；无resolve函数、自动重放或隐藏人工成功入口；poll/wait和已提交replay仍可用 | 基于外部证据的resolution为Phase 1 |
| B05 | 最小driver接管 | 一个run lease+effect attempt/fence，无第二effect lease；Fake测试覆盖获租/过期/旧fence恢复，无生产daemon、自动重启或运维接管编排 | 不宣称生产takeover已交付 |
| B06 | 无生产retention | events/wakes/requests/pins保留至整个临时库删除，无TTL/reaper/生产归档/在线压缩；history全量不分页 | 不能承诺无限期生产运行或有界历史开销 |
| B07 | 身份是职责角色 | 真实caller按数据库role验证，actor只核对NULL或目标run；service为受信宿主，driver字符串不是凭据 | 无principal/租户授权体系 |
| B08 | generation简化 | registration/continuity恒1；UUID不复用，无重新注册、owner_generation、origin或superseded控制语义；terminal steer加epoch | 不虚构无producer的generation/transition |
| B09 | 临时库生命周期 | fixture创建独立库/LOGIN，按name+OID清理；不迁移v13数据，不改历史loader | 生产部署、迁移与备份恢复不在本阶段 |
| B10 | 本机数据库IO | 只允许pgembed实际绝对Unix socket；libpq为必要本地基础设施。Python socket guard只证明Python层，C层本地性依赖严格DSN校验 | 不把monkeypatch称为libpq网络拦截证明 |
| B11 | NOTIFY非状态源 | wakes/snapshot是事实，通知仅提示，wait为短事务轮询、独立cursor与deadline | 无生产reader服务或通知可靠交付保证 |

以上是计划已有裁决，不是为回避红测而新增的例外。

## 实施资源与验证方式变化

| ID | 相对计划变化 | 理由/可见证据 | 状态与限制 |
|---|---|---|---|
| D01 | 新增 `v99/core/catalog.py`，超出计划 §4 原始文件清单 | 独立硬编码 EXPECTED_CORE_SIGNATURES，`assert_function_catalog` 用pg_proc输入参数签名集合比对，排除pgcrypto成员；setup自检与默认gate共用。`test_w5_catalog_and_guards` 注入同名start(integer)必须触发ABI drift | W4/W5支持资源；须纳入最终文件集合说明。只覆盖函数名+输入类型ABI，不宣称返回类型/default/所有函数属性闭集 |
| D02 | 常驻 uv setup helper 与进程 guard 边界 | `_server_and_base_dsn` 在父 guards 内以 `uv run python v99/core/setup_db.py --server-helper` 启动常驻子进程；子进程持 pgembed handle 并输出 JSON uri/socket/port，再等 stdin EOF。父进程以单调 deadline 读端点、校验活进程/严格 Unix DSN/实际 socket 与 port；`_close_server_helper` 有界 wait→TERM→wait→KILL→wait，未 reap 保留句柄可重试，清理失败使 gate 非零。 | 父进程只准 psql/uv basename、禁 shell/executable override，未扩白名单。Python monkeypatch 不跨子进程、不覆盖 libpq C socket；helper/uv/pgembed 内部启动不受同一父 guard 证明。libpq 本地性靠严格 DSN 与实际 socket/port。显式 `server_helper_scope` 收尾在完整 gate 父 guards 内；atexit 是 guard 外后备，不能宣称整棵进程树全程受 guard。R2 已由 `review_checks.test_helper_lifecycle` 覆盖，修正后两条完整 gate 于2026-10-21均退出0。 |
| D03 | 网络、历史依赖与宿主SQL静态检测 | T包内AST保留provider/socket/subprocess/dynamic import负例，仅豁免test_core.py的socket/subprocess及setup_db.py的subprocess精确import，仍检查调用；I.test_historical_and_host_static_negatives增补v8/v13/pgmq导入/路径/SQL负例及全部11控制表DML检测，projection调用为允许正例 | Q10原缺口已补；静态规则仍不是任意动态Python程序的完备证明 |
| D04 | 保留 `--w2-only` / `--w3-only` 诊断入口 | 局部owner测试便于回归；默认`run_full`顺序执行W2/W3与非超级用户Fake/ACL等组 | 两个局部入口不代表最终gate，不以局部退出0替代两条完整验收命令 |
| D05 | 新增 `v99/core/infrastructure_checks.py`，超出原计划文件清单 | 冻结补充模块，具名 test 覆盖 Q3/Q5/Q10/Q12；`run_group_lifecycle_checks` 覆盖 Q9。接收活跃 test_core 模块参数以复用 helper，避免反向导入 | 协调者确认 guards 下独立退出0；run_checks 在 fixture 内，group 生命周期 hook 在 fixture 外，不能嵌套固定 group 锁。已接入修正后默认完整 gate 0 |
| D06 | 新增 `v99/core/contract_checks.py`，超出原计划文件清单 | 冻结补充模块，run_checks 调用 `_poll_wait/_wait_contract/_response_contract/_control_replay_rollback/_size_revision/_public_accept_rejections/_unknown_wall/_generation_attempts`，覆盖 Q1/Q2/Q4/Q6/Q7/Q8/Q11 及 G1 公开入口合同 | 协调者确认独立退出0、token/tok已修；模块不自建默认 gate，已集成主 fixture，父 guards 下修正后默认完整 gate 0 |
| D07 | 修正真实新函数默认 PUBLIC EXECUTE 缺陷 | `I.test_fresh_object_default_acl` 暴露仅 schema 默认 REVOKE 不能扣除 PostgreSQL 全局 PUBLIC EXECUTE；40 现加入 owner 全局 `ALTER DEFAULT PRIVILEGES REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC` | infra 独立通过；保留缺陷发现和修正事实。不是获准放宽 ACL 的偏差；修正后两条正式完整 gate 于2026-10-21均退出0 |

本里程碑共 **17 文件**：`v99/core/` 八个 Python（含 catalog 与三个检查支持模块）、README、五个 SQL，加计划和两份 review 工件；不包含无关 dirty 文件。

| 新增资源 | 原计划外支持文件与集成 |
|---|---|
| D08 `v99/core/review_checks.py` | R1–R4 四个具名回归；`test_helper_lifecycle` 在真实 helper 启动前，其他三项由 `run_checks` 在主 fixture 内执行，均处于父 guards 与 `server_helper_scope` 内；修正后默认完整 gate 0。 |

## 原覆盖缺口销项

Q1–Q12 原稿的具体断言缺口已映射；下表保留 §10.7 独立与审查前默认入口退出0历史。§10.8 修正后默认完整入口再次全部退出0，含新增 R1–R4 回归；销项不是范围豁免。

| 编号 | 已补齐的具名证据 | 证据状态 |
|---|---|---|
| Q1–Q2 | P._poll_wait、P._wait_contract：READ ONLY/expired/state不变、FIFO/重复cursor、跨epoch正文、future/advanced/unknown actionable | 独立0；审查前默认集成gate 0 |
| Q3 | I.test_current_tool_failure_cancels_successors精确三工具状态/无continuation；I.test_history_projection_and_fake_consumption实际LLM消费tool/human及跨epochhistory | infra guards下独立0，审查前默认gate 0 |
| Q4/G1 | P._response_contract：公开operator七种合法body、全非法类型/空值/one-of；三lease态不改变driver三元组并写NULL driver pin；P._public_accept_rejections公开service错owner/fence/expiry零写 | contract独立0，审查前默认gate 0 |
| Q5 | I.test_set_role_real_caller/test_same_session_shadowing/test_all_table_and_private_acl/test_fresh_object_default_acl：真实降权、同会话pg_temp/public遮蔽、全表/私有helper/CREATE、无逐对象REVOKE新对象拒绝 | infra guards下独立0，审查前默认gate 0；默认权限曾真实失败并已修，保留历史 |
| Q6 | P._control_replay_rollback：start故障全库协议状态回滚、四控制replay/conflict零写、全部controls completed+completed_at | contract独立0，审查前默认gate 0 |
| Q7 | P._size_revision：SQL实测多字节1048577拒绝零写；第二事务推进revision且driving不变，accept正确发布R+1 | contract独立0，审查前默认gate 0，与原恰1MiB接受配对 |
| Q8 | P._unknown_wall：respond/steer/新三status receipt零写wall，原receipt replay不变、改digest冲突 | contract独立0，审查前默认gate 0 |
| Q9 | I.run_group_lifecycle_checks：预置group属性/OID/成员快照保留，异常LOGIN group拒绝且资源不变 | infra guards下独立0，审查前默认gate 0；若固定group已存在，不变异它们，另建role测异常validator；hook在fixture外 |
| Q10 | I.test_historical_and_host_static_negatives：实际文件扫描、历史Python/SQL负例、11表DML负例、projection允许正例 | infra guards下独立0，审查前默认gate 0；不夸大动态语言检测能力 |
| Q11 | P._generation_attempts：generation值1、tool turn1、三连接并发steer的attempt_seq计数唯一、无死字段、非法superseded transition23514 | contract独立0，审查前默认gate 0 |
| Q12 | I.test_cached_discover_bound_claim：rival提交消费旧head后缓存claim拒绝且state不变；新head仍ready/attempt0/fence0/无pin，不被改领 | infra guards下独立0，审查前默认gate 0 |

§10.7 审查前入口包含两个模块与 fixture 外 group 生命周期 hook，两条完整命令曾实际退出0。后续 DE8A 发现 R1–R4，现已修复并按 §10.8 重新完整复验0；W7 交付记录以包含本文件的唯一 Phase 0 提交及 `origin/v99` 引用为准，不宣称真实 provider/生产能力。

## DE8A 实质审查发现与修正后验收（2026-10-21）

Oracle同chat的两次调用因interactive inactivity watchdog失败，没有实质结论；后续只读pair DE8A已完成实质整体审查。以下四项是实现缺陷，不是既有范围边界，不允许用§10.7正常gate0销项。B368 已完成修复；下表记录实际具名回归与完整 gate 结果，不扩张测试边界。

| ID | 发现 | 实际修复与具名证据 | 当前状态 |
|---|---|---|---|
| R1 | ce_wait异常未可靠 rollback，finally 清理可遮蔽原异常 | `review_checks.test_wait_exception_cleanup`：listen=False/True 的 SQL 22012、LISTEN 后注入异常均保留原错误，连接 IDLE 且无 listening channel；清理失败只附 note | 已修复；完整 gate 0。异常替身覆盖不等于所有真实进程故障穷举 |
| R2 | helper超时没有终止子进程且可能失去句柄 | `review_checks.test_helper_lifecycle`：EOF 回收、TERM→KILL/三次 wait、未 reap 保留句柄可重试、启动/scope 原异常 note、uv 子探针清理失败 exit 1 | 已修复；完整 gate 0。主要为 process/pipe 替身，不夸大真实进程树证明 |
| R3 | FakeHost固定driver ID令不同实例共享owner身份 | `review_checks.test_fakehost_restart`：UUID driver 不同；有效 lease 时新实例 driver_required 且零写/IDLE；过期接管 fence+1、旧 claim unknown、pin=1、无重复 Fake IO | 已修复；完整 gate 0 |
| R4 | failed tool没有tool/result history | `review_checks.test_failed_tool_result_history`：当前失败 history 含 tool/result error、后项 cancelled/upstream_failed；steer 后旧失败 archived_stale，下一 LLM 消费 error，恰一 failure event | 已修复；完整 gate 0 |

两条完整命令已于 2026-10-21 实际退出0，并按新增具名断言更新矩阵；原 PUBLIC EXECUTE 发现、启动失败、Q1–Q12 和审查前正常 gate0 历史全部保留。

## 真实执行事实与未完成事项

本轮W6只整理三文档，未运行数据库gate，不修改SQL/Python/计划，不stage/commit/push，不另发Oracle审查或另派代理。实质整体审查已由只读pair DE8A完成。W0–W7仍为唯一Phase 0里程碑。

| 事实 | 记录 |
|---|---|
| W1首次self-check退出1 | epoch插入漏必填generation，修正后局部自检退出0，见计划§10.3 |
| W2首次局部脚本退出1 | PL/pgSQL记录变量e与SQL alias冲突，修正后五组退出0，见§10.5 |
| W3定点/局部脚本曾退出1 | response/effect_id/reason歧义、测试重用request ID、stale catalog期望写死；修正后W3/W2及当时fixture自检退出0，见§10.6 |
| W3收尾扫描首次未执行 | 裸python不在PATH，退出127；改uv run python后trailing_whitespace为0，见§10.6；不把未执行尝试记为通过 |
| W4/W5首次默认gate曾退出0 | 协调交接明确抽查随后发现guard/签名等缺口；不能把首次0描述为最终验收完成 |
| infra/contract独立结果 | 协调者确认两模块分别独立退出0，infra在运行时guards下；W6只读映射、未代跑 |
| 主集成启动历史失败 | 首个fixture在subprocess_guard内触发pgembed postgres --version，被白名单拒绝；短命uv run server.py uri释放handle导致socket消失。最终改常驻setup helper，未扩父进程psql/uv白名单 |
| contract自验修正 | token/tok变量混用已修；独立0后又进入审查前默认gate，保留修正事实 |
| `uv run python v99/core/setup_db.py --self-check` | 2026-10-21 修正后实际退出码 **0**，计划§10.8记录，含 review fixes 与 helper 显式收尾 |
| `uv run python v99/core/test_core.py` | 2026-10-21 修正后实际退出码 **0**，计划§10.8记录，含 Q1–Q12、R1–R4、guards 与 fixture 外 group lifecycle hook |
| 审查修复回归失败历史（2026-10-21） | §10.8：定向会话35291退出1（lease到期探针校准），改为直接注入过期lease后16655退出0；另一进程替身PID触发真实killpg检查 PermissionError，修正模拟PID后77780退出0。随后编译与 guarded review checks 通过；不删除失败或把替身校准误写为新协议缺陷 |
| Oracle尝试 | 同chat两次interactive inactivity watchdog失败，没有实质结论；不是已通过的审查 |
| 实质整体review | 随后只读pair会话DE8A首次实质审查已完成，提出R1–R4；不得继续写“整体review未执行” |
| W6/W7 | 三文档已更新审查状态与最终具名断言；两条正式命令均为0；W7 交付记录以包含本文件的唯一 Phase 0 提交及 `origin/v99` 引用为准 |

历史失败应追加修正结果，不覆盖或删去。原计划早期批次的四文件manifest与owner绿测是当时证据，不能写成当前五文件最终ACL/Fake gate的历史通过证据。无关dirty文件保持任务范围之外。
