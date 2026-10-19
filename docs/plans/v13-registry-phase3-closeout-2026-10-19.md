# v13 时空注册面 Phase 3：最终收尾开发计划

> 日期：2026-10-19。执行状态与实际提交/回归结果见 §11；以下正文保留审定计划及规划时点的历史事实。
> 唯一实施范围：最终全回归、跨层证据、部署边界/runbook、教程事实收敛及偏差归档。
> 完成条件包含文档/静态收敛、隔离 PiSwift parity/ports 预验证和独立的两轮完整 51 项；不以历史结果替代本轮证据。

## 1. Goal 与完成标准

在已完成的 Stage 41 注册面和 Phase 2 consumer overlay 上关闭证据与运维文档缺口，形成不依赖会话或 ignored 日志才能读懂的最终交付记录。**不补运行时功能，不补测试行为，不重新设计注册面。**

Done when：

- 在正确的 V99 后继基线上，README/runbook、教程、matrix、ledger、设计与前两阶段计划的当前状态一致；历史 RED 和历史交接记录保留。
- 全部已装载对象、claim/pin/completion/freshness/投影/ACL/锁序都有明确来源和证据等级；20 项 replacement 文档计数纠正，现有代码闭集不变。
- precommit 与主提交 A 的 postcommit 各自从 #1 严格串行执行完整 51 项，49 项 exit 0、#17/#18 预期 exit 1/2，每项 trace bytes/mode 恢复，无拼接历史结果。
- 一个 Phase 3 收尾里程碑内，A 为主文档提交，B 为 postcommit 证据追加；二者各自在完成后立即提交、立即推送到核对后的 `origin/v99`。B 只改结果文档，经 docs-only 差异核验后不启动第三轮 51 项。
- 永久最终报告记载两次序列的实际结果、基线、限制、失败历史和提交 A 的身份；B 的实际 hash 与最终 push 成功由只读交付回执报告，不预填、不为自引用创建 C。

**禁止项**：新增或修改 SQL、运行时行为、claim/context 字段、测试逻辑、ACL、guard、loader；新增生产 worker/框架 DB parity、TTL/GC、CE generation 映射、profile/prompt 消费者。发现真实 Phase 2 缺陷时阻断并回交独立修复，不用收尾文档将红洗绿。依据：V99 `docs/plans/v13-registry-phase2-2026-10-18.md:338`。

## 2. Background：两阶段现状

### 2.1 基线、分支及交付位置

本文除特别标明外，所有 `file:line` 相对 **V99 = `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99`**，引用行号固定于 `93d05f1`，执行时按符号复核。

2026-10-19 只读检查所得：

| 位置/提交 | 事实与边界 |
|---|---|
| 主工作区 `/Users/wxl/Projects/pg-agent` | main/`7db3526`，43 个 modified、大量 untracked，无 `v13/registry`。此处设计仍为早期版本。本计划按用户要求写在此处 `docs/plans/`，不在此重建注册面或执行回归。 |
| V99 | `v99@93d05f1`，本地 tracking ref `origin/v99` 同值；tracked tree 干净，仅未跟踪 `docs/reviews/v13-registry-stage41-plan-review-2026-10-17.md`。未 fetch，tracking ref 不等于实时远端证明。 |
| `69e118d` / `5be562d` | Phase 1 注册面实现 / postcommit 证据提交。 |
| `937a864` / `93d05f1` | Phase 2 消费面实现 / postcommit 文档提交。不能再把文档 follow-up 称为未提交。 |

上述提交链由 `git log -6 --oneline --decorate`、`git show --stat 93d05f1`、`git status --short --branch` 核实。后续执行先定位 V99 后继工作树，将本审定计划携入该分支同路径；**不合并 main，不推 main**。根 AGENTS 的测试、逐路径暂存、立即提交推送、禁强推等纪律不变；目标分支采用 Phase 2 已确定的 V99 交付线（其计划 `:337`），不是在脏 main 上执行 `git push origin main`。

V99 的 Stage 40 ce_run 已收口（`683ea0e`/`60805fc`/`cbf65cf`）；loader 是 fair_claim/39 → ce_run/40 → registry/41。不得将主树设计的“ce_run 未提交/W4 红/44 项”历史陈述当作当前 V99 事实。

### 2.2 证据等级及既有结果

| 等级 | 使用规则 |
|---|---|
| DIRECT | 指定 gate/receipt 对特定场景有真实观测。历史 DIRECT 必须注明提交与运行轮次，不等于本轮实跑。 |
| STATIC | 指定源码、静态调用点或对象闭集直接支持；历史 loaded catalog 与本轮源码检查须分开。 |
| INFERRED | 由源码和相邻测试推导，无该组合场景的独立断言；不能改写成 DIRECT。 |
| NOT CLAIMED | 没有交付/不在验收范围，不能用相邻证明替代。 |
| NOT RUN | 本轮尚未执行或中断后未执行；不是 PASS，不虚构退出码。 |

| 已有阶段 | 已核对的历史证据 |
|---|---|
| Phase 1 | `69e118d` 后 50 项，48×exit 0 加预期 exit 1/2；registry 16/16 groups、481 checks。原收据 `prompt-exports/w4-registry-postcommit-p1-20261018/results.json`，摘要 `prompt-exports/w4-registry-final-report-20261018.md:8`；计划 W4 `docs/plans/v13-registry-stage41-2026-10-17.md:29`。 |
| Phase 2 precommit | 隔离离线序列完整 51 项，951.81 秒。收据 `prompt-exports/w5-phase2-offline51-20261019/results.json`；README `:472` 起。 |
| Phase 2 postcommit | 在实现 `937a864` 上完整 51 项，49×0、#17=1、#18=2；所有行 `valid=true`、`trace_restored=true`，911.44 秒。registry 16/16 groups、485 checks，consumer 289。收据 `prompt-exports/w5-phase2-postcommit-20261019/results.json`；README `:567` 起、Phase2 plan `:43` 起。 |

历史 481 与当前 485 属不同测试版本；不得互换。trace SHA-256 为 `3496c6a4c98937a009fed3144d0cdcac84dd1e788fd2854769cc9aca705d933a`，mode `0644`。历史时长不是未来性能阈值。本轮仅阅读现状/证据，没有重跑 gate。原收据被忽略、不能永久依赖；最终报告需自包含。具体断言定位见下表，不能把receipt的valid当作所有主张均有独立覆盖：

| 主张 | 现有探针/断言入口与等级 |
|---|---|
| prefix/loader/闭集 | `test_registry.py:234` native_load_untouched、`:288` native_plan_arm_closed_set；STATIC及历史gate。 |
| 确定性/as_of/依赖/ACL/tools | `test_registry.py:462`、`:503`、`:523`、`:607`、`:857`，历史DIRECT；16组入口`:881`。 |
| claim/complete/global-fair身份 | `test_consumer.py:104`起相应接口探针；ACL closure `:952`起，历史DIRECT限其中已列用例。 |
| freshness/judge身份 | `test_consumer.py:504` native_freshness，真实register在`:524`；历史DIRECT。 |
| superseded控制投影 | `test_consumer.py:207` native_w4_projection使用直接clock bump，及`:760`后actual spawn/plan-signal用例；历史DIRECT但不冒充真实register/retire组合。 |
| worker合同 | `test_consumer.py:634` native_worker_protocol，仅内联fake adapter模型的历史DIRECT；非生产driver保护。 |
| claim函数内部40001 / spawn_owner调用先42501 | SQL `:822`与`:809`的STATIC读码推断，无针对该异常的独立实调断言；不得标DIRECT。 |

默认 parity 跳过 `node_modules` 平面，未启用 `PI_PARITY_REQUIRE_ALL`；不存在 all-plane、真实 provider 或多语言 worker 接 DB 的验收主张。fake adapter 验收不等于生产 worker 已接入，现有 fair_driver/loop_driver/框架 driver 未被本线改成 strict adapter。链环防御只有静态证明，32 层 cap 有运行覆盖；不伪造不可达环运行证据。

### 2.3 Phase 1：实际注册面，不复述过时设计

- `v13/registry/v13_registry.sql:1` 至 `:603` 为冻结前缀；`:604` 是 overlay sentinel。三表：registrations、global singleton clock、scope meta；八函数及 ACL 在此前缀。hash：`e5222e1499001f3a734292d8456d2b431fcfcd2a5862952bfcc38137caee34d4`，锁于 `setup_db.py:82`。
- 全局 clock 为历史寻址与 freshness 真相，scope meta 只作诊断、可落后。clock 缺 seed 报错，不回退 0。注册/退役各分配一个 revision，半开区间 `[from,to)`；`already_live`/`not_live` 零写、不分配 revision。写锁序 clock → meta → sessions（append_event）→ registrations，先事件后行，事务要短、无外部 IO/等待。READ COMMITTED 同键竞争等待后可返回 already_live；REPEATABLE READ 可安全报 40001。见 SQL `:159`、`:297`、`:341`、README `:35`。
- scope 上行 nearest shadowing、32 行/重复 UUID 截断；服务按依赖闭包解析，missing/cycle 入 unresolved 不 RAISE。context 十键、数组稳定排序、provenance 覆盖用户同名键；hash 含 unresolved/tools_revision。负 revision 报错，0 为空注册面，未来 revision clamp。`prompt_section` 保留 object 开放形状。见 SQL `:413`、README `:60`。
- tools 只有当前快照：旧/零 registry revision 也带当前 tools 与 tools_revision。因此不可声称 `(scope,rev)` 冻结完整 tools；缓存须 `(scope_id,context_revision,tools_revision)`。
- route 写、recall+route 读，resolve/worker/PUBLIC 不读注册面；NULL actor 使用真实调用身份/SET ROLE，显式 actor 按 self/direct parent 授权，EXECUTE 是外层边界。未知/越权用 canonical empty context，合法未注册 scope 保留真实身份和 tools。见 SQL `:581`、README `:98`。
- tool_profile 仅数据，无当前消费者；interruptible 仍函数优先，未来 profile 消费另案。policy/tools/thresholds 不迁移。

### 2.4 Phase 2：现有接口及数据流

`v13/registry/v13_registry.sql:604` 后同文件 Stage 42 sentinel overlay；loader 仍41项（`v13/load.py:58`、`:102`），不是第42个 loader entry。新增两表、11函数签名、一个 events capture trigger；**替换20个既有定义**（`setup_db.py:52`），不是 README `:163` 的21。

| 接口 | 当前 as-built 契约 |
|---|---|
| global claim | `v13_claim(p_worker text,p_lease_ms integer DEFAULT 60000)`；精确六键 `{effect_id,attempt_no,fence,kind,request,context_revision}`。普通宿主使用 route。 |
| fair claim | 上述六键加 root_session_id；owner-only，route 为42501。Stage39 prefix gate继续SIX，overlay gate独立证明SEVEN，不改冻结测试凑文案。 |
| CE claim | 原七键并行面，不接 registry pin，不调用/替换 CE 函数。 |
| completion | 旧五参无actor wrapper不变；六参有actor定义已替换并计入20；新增strict七参全required、零默认。common/包装保持INVOKER，防止current_user授权变成owner绕过。 |
| freshness | probe八键、envelope21键；snap只投影给定envelope，不另读clock；advance第八键比对，缺键stale；effect_envelope剔除registry_revision，逻辑judge身份不漂移。 |
| pin/mapping | `(effect_id,attempt_no)` 主键及exact fence约束，pin存scope/context_revision/tools_revision；事件mapping按 `(session_id,event_seq)` 指向exact attempt/fence，不改业务payload。 |

运行链（SQL `:608`、`:669`、`:702`、`:822`、`:1308`、`:1324`）：

1. 源码契约（STATIC）：claim先读双fence，CAS effect，写不可变pin，再读双fence；发现变化抛40001，CAS和pin回滚。现有测试没有直接触发函数内部40001；不能以adapter rollback代替这项实测。
2. 测试内联fake adapter模型/未来worker合同（不是当前生产driver）从IDLE开始，在route/global或owner/fair身份下claim，exact lookup pin，再以claim revision钉版读取context，使用三元缓存键；核对context.tools_revision与pin，并在提交前复核双fence，变化则rollback。
3. 该测试模型在claim提交、连接回IDLE后才做fake IO；completion另开事务用七参strict overload。不把此协议验收写成新生产driver。现有fair_driver/loop_driver未实现这段额外复核，旧五/六参completion的require_pin=false不做strict pin核对；不能声称这些生产路径已经具备模型的全部保护。
4. strict先检查attempt/fence，不匹配stale；token匹配后NULL/负revision为22023，missing exact pin为P0001，revision不匹配stale；terminal exact token可replay；旧但exact pin仍可accepted。
5. events AFTER INSERT capture对有pin的source effect记录exact attempt/fence。guard/FK失败必须连event、序号、settlement和mapping一并回滚。业务payload保持tool/call四键、repair/replan单schema_version、human/responded六键，不塞context_revision。
6. current投影比较pin与当前global registry clock、tools_revision；有pin历史但缺失/畸形mapping返回false，无pin历史的legacy/CE/synthetic仍eligible。历史事件保留，当前控制证据按superseded排除。

读取注册事件会推进scope session的session_version/max_event_seq，在途advance stale重解析是安全特性；global clock也使不相关scope的旧pin/advance失效，是明确成本。fence并发令牌不被registry revision吸收。

### 2.5 有效对象、ACL与锁证据索引

下表是最终报告必须逐行核对的20 replacement与实际过滤落点，不用“更新所有调用方”代替：

| 有效对象 | 原最终来源 / overlay位置与核对重点 |
|---|---|
| v13_claim / v13_claim_fair | fanout / fair_claim；overlay `:822`、`:878`，CAS+pin+双fence复核 |
| 六参 v13_complete | ACL；`:1070`起common、`:1298`六参delegation，五参wrapper不动，`:1308`新strict |
| v13_probe / v13_judgment_envelope | manifest / filter；`:1324`、`:1341`，同statement双fence与8/21键 |
| v13_snap_of / v13_effect_envelope | resolve / envelope；`:1457`、`:1475`，纯投影/剔除水位 |
| v13_advance | 最终plan_arm而非早期fanout/triage；`:1483`；tool-call聚合、predecessor、repair/material/approval/wake选择前过滤 |
| v13_route | loop；`:2069`，finish机器事件过滤且保留origin_user_seq |
| v13_canonical_state | resolve；`:2111`，只过滤当前turn机器消息，保留历史审计 |
| v13_parse | economy；`:2130`，过滤effect-backed resolve/failed，synthetic失败仍计数 |
| v13_cap_answer_anchor / v13_cap_human_answered | seam；`:2155`、`:2228`，human event/effect/anchor，answered委托过滤后的anchor |
| v13_harness_tail_gap / v13_tail_gap_cap_exempt | seam；`:2301`、`:2237`，effect及signal证据 |
| v13_triage_fold_reason / v13_triage_block_explore_spawn | triage；`:2335`、`:2370`，signal/cap-human/tool-call |
| v13_closeout | spawn；`:2388`，repair/replan/material/wake/approval receipt |
| v13_recover_idle / v13_scheduler_hint | govern；`:2595`、`:2659`，signal/fingerprint/nudge/unconsumed tool-call |

两pin表owner-only（含列级权限），无PUBLIC/worker/resolve/recall/route/spawn_owner直接表权。新增helper固定search_path，除completion相关INVOKER外为owner DEFINER。窄EXECUTE如下（README `:227`）：

| Helper | route | recall | resolve | spawn_owner |
|---|---|---|---|---|
| fences | 是 | 是 | 是 | 否 |
| pin insert / exact lookup | 是 | 否 | 否 | 否 |
| pin matches | 是 | 否 | 否 | 是 |
| event_current | 是 | 是 | 是 | 是 |
| effect_current | 是 | 否 | 是 | 否 |
| strict/common completion | 是 | 否 | 否 | 是 |
| registry context | 是 | 是 | 否 | 否 |

worker/PUBLIC均不获上述EXECUTE。recall的canonical读链、spawn_owner的fork→prefix_identity→canonical_state只获event_current，不获effect_current/表权。fair owner身份不能偷换为route。

锁证据须从现有consumer gate与收据提取：backend精确PID、pg_blocking_pids、ungranted pg_locks，而非sleep时间。writer持clock等待scope session时，其他scope claim/pin不反向等clock；completion先session后effect；fair advisory13002→root→child，effect NOWAIT冲突返回NULL、不留CAS/pin。mapping失败注入证明原子性。govern历史观察器已用真实updater PID和transaction-lock等待作两处窄修正，由r0_source_scope字节钉住，Phase3不再修改。见README `:252` Lock Evidence and Review、consumer现有探针。

## 3. Oracle 裁决与实施选择

### 3.1 裁决记录

2026-10-19通过 `context_builder(plan)` 取得完整草稿，随后同一Oracle会话 `v13-时空注册表收尾开发计划-B3B005` 作有界补充裁决。首次follow-up遭interactive inactivity watchdog终结、assistant消息为空；缩减selection后唯一一次有界重试成功。下面为成功响应的结论，不是新增实跑。

| 问题 | 裁决、理由及边界 |
|---|---|
| 20 vs 21 replacement | **接受文档纠错**：20为setup闭集；新签名另计。改README/matrix，不改allowlist。若loaded实际changed超集则Phase2缺陷阻断。 |
| spawn_owner latent ACL/API不一致 | **当前接受风险，不声称入口可成功执行**：保留global claim EXECUTE，但无fences/pin_insert权，直接调用先在fences处42501，发生在CAS之前。NOLOGIN不证明不可达；给定调用图无生产caller（STATIC）：spawn_owner拥有的三个DEFINER为fork/open_session/spawn_subsession，spawn SQL无claim引用，已见SET LOCAL ROLE点是一次性自检。G0还需查loaded pg_proc中owner=spawn_owner且prosecdef的prosrc，以及SQL/Python中角色切换/动态调用点；不能以文本无匹配证明任意动态SQL不可达。普通宿主claim身份是route，不是“唯一有EXECUTE者”。若发现SET ROLE或DEFINER链可达caller，立即回交Phase2，Phase3不补授权/撤权/测试。 |
| claim复核到COMMIT窗口 | **接受快照复核+superseded投影收敛，拒绝严格commit瞬时一致主张**：claim不锁clock，二次读之后writer仍可提交；adapter复核只缩窄窗口。exact旧pin可结算，后续新快照current投影排除。不能保证外部IO总用最新版，也不撤销已执行IO。现有直接覆盖仅复核前变化→rollback，复核后窗口为STATIC/INFERRED。 |
| 注册/退役后的claim翻转组合覆盖 | **接受INFERRED留档，不补Phase3测试**：真实register影响probe/envelope/advance有直接覆盖，projection有clock变化测试；没有“真实register/retire→后续claim新revision且旧pin current失效”的独立组合断言。推论限定writer已提交、后续读取得新快照、成功claim。`pin_matches`只匹配历史exact pin revision，不读clock，不会因此翻false；event_current/effect_current才是失效投影。 |

依据：`setup_db.py:52`、SQL `:702`、`:746`、`:756`、`:809`、`:822`；`test_consumer.py:504`、`:634`、`:952`。真实可达缺陷或直接证据矛盾仍阻断，不因Oracle接受范围而豁免测试红。

### 3.2 方案选择与拒绝的替代

- **现有README承载runbook**，不在registry目录新增文件。该目录现有五文件闭集被`test_registry.py:234`及plan_arm守卫锁定；另建RUNBOOK.md会逼迫改guard，超范围。
- **side-table锚保持原样**，不向payload加revision。后者破坏control/spawn精确键守卫，且不能替代attempt/fence级映射。
- **全局clock与当前tools双fence保持原样**，不改scope-local、不补tools历史轴；这是已接受实现，不从早期设计倒退重做。
- **两次完整序列、A/B文档提交闭环**：只precommit缺提交态证据；先提交再跑并预填绿违反规则。B只追加A实测结果及文档事实，docs-only验证终结自引用循环。A和B各自立即push，不积压。
- **单一收尾里程碑**：下文G0–G6只是内部工作项，不是独立stage/gate里程碑；各项不创建零碎提交。主提交A与证据追加B按上述边界处理。
- **main整合后置**：本计划不决定v99与main历史如何合流。发现远端分叉或执行基线改变先停，不能用merge/force/reset消除差异。

## 4. 运维与文档规格

### 4.1 Runbook支持面

只写入 `v13/registry/README.md`，**支持全新隔离库安装演练与只读核验，不支持现存生产库在线升级/降级**。当前SQL不是migration工具；测试setup会DROP/CREATE测试库，绝不用于生产。Phase3不新增部署脚本，不实际部署生产库。

runbook必须说明：

1. 记录批准commit、目标隔离库/cluster、owner和数据库角色；确认现有extension前提、public CREATE及TEMPORARY边界。安装顺序唯一来源为`v13/load.py`的41项`SQL_LOAD_ORDER`；`load.load_stage`（`v13/load.py:125`）与`setup_db._registry_sql_parts`（`:209`）是现有装载/分段机制，不可对未知既有库盲跑。仅在明确可丢弃隔离环境按受控装载流程演练，避免角色/数据库名冲突。loader和setup的调用方式先对照符号，不杜撰生产CLI。
2. anchor使用既有`v13_open_session`，先查loaded参数类型、默认值、EXECUTE和返回值契约；对照`test_consumer.py:507`已验证jsonb调用。用批准的owner/route入口创建无parent的root session，记录实际返回UUID和运维责任人；不固定UUID、不直接INSERT sessions、不新建seed schema。不得把任意独立根session说成所有现有session的自动祖先；继承仍依parent链。
3. 只读健康核验：prefix hash、loader41项、3表8函数前缀、2表11新签名20replacement及events capture trigger；clock/tools seed；loaded pg_proc的regprocedure、owner、prosecdef、proconfig/search_path、volatility、pronargdefaults与ACL。用已授权身份读context十键/hash、probe八键、envelope21键，确认anchor身份及修订。无pin表直读权限的角色不临时扩权。
4. 健康异常记录SQLSTATE、commit、调用身份、事务状态、scope/effect/attempt/fence、双revision、event标识，不手工补写、修改或删除pin/mapping，不绕immutable trigger；不重放已完成IO。superseded exact effect可能已succeeded且IO已发生，但输出被后续投影排除；不会自动requeue，Phase3不提供重发或补偿手段。
5. 现存生产库要求升级/回退时**停写、保全备份和append-only审计，停线另提迁移设计**；禁止DROP生产库、盲删pin/mapping/events、反复重跑完整SQL。Stage1–40重建只可在隔离环境验证，不能称为现有数据可恢复的生产回滚。后续迁移设计若恢复函数，必须取Stage1–40各对象最后有效定义，而非schema/Stage1早期版本；须处理capturing trigger、FK、历史pin和旧worker兼容后才能支持在线回退。本计划不声称已演练该流程。

### 4.2 教程事实收敛

| 文件与旧意图位置 | 必须写成的as-built事实 |
|---|---|
| ch08 `08-multi-language-harness.md:21`、`:51`、`:110`、`:128`；ch02 `02-effect-ledger.md:63`；ch03 `03-queue-as-wakeup.md:55` | claim只收worker/lease，无handlers[]参数或相应过滤。区分global六键/fair七键/CE独立七键、owner与route身份；不能把概念性worker循环当生产接线。 |
| ch08 `:28`、`:66`；ch06 `06-tool-catalog.md:21`；ch12 `12-intervention.md:56` | 现行tools六列name/description/kind/handler/param_spec/enabled，无allowlist/interruptible列。interruptible是硬编码函数，profile尚无消费者；函数优先/未来覆盖面不是现在已生效的override。 |
| ch08 `:72`、`:102`；ch06 schema段 | 普通目录新增只影响已实现handler/catalog行为；新增工具若需改变interruptible/worktree名单还需独立SQL变更，不能“零SQL文件练习”宣称只INSERT即可。input_schema/allowlist/mutating/consumes/produces不是现行tools列；mutating已有spawn metadata，unknown墙和worktree latch仍是既有机制，不经registry重实现。 |
| 全部涉及章节 | 优先直接纠正可执行例子，必要时保留标注的历史意图。不改无关教学内容，不承诺生产worker、全语言DB parity、真实provider或profile/prompt消费者已交付。 |

### 4.3 跨层最终报告与偏差归档

新建 `docs/reviews/v13-registry-phase3-closeout-2026-10-19.md`，必须包含：

- 基线/提交链、当前阶段结论、完整两轮manifest实际状态/退出码/关键checks/时长、trace原末hash和mode、每行恢复状态；历史失败和未跑不能补算。
- §2.5每个有效对象/被覆盖来源/过滤位置表、schema/pin/event mapping、全ACL矩阵、claim三面与completion overload、freshness与judge identity链、锁屏障和原子性证据，含loaded catalog来源与gate探针名。
- Oracle四项裁决与STATIC/INFERRED/DIRECT区分；未交付、接受成本和需要回交Phase2的条件。
- precommit receipt来源、A提交身份、A上postcommit receipt身份、两次序列不混合；ignored原始材料路径和缺失时限制。无需粘贴源文件、原始日志、全部catalog dump。
- README/matrix/ledger/教程修改索引、部署支持范围；A/B提交规则。B只可记载已经发生的A push，不能预填B自身hash/push成功；最终只读交付回执补B及远端事实，不再为报告自身创建提交。

matrix新增独立Phase3区段，不能覆盖旧Stage42 goal_workflow或Stage41/42原记录。ledger使用`P3R-*`命名空间：计数纠错、latent ACL、claim窗口、组合覆盖缺口、部署限制、环境/skip与证据寿命分别可查。保留S42R-9/10的RED、S42R-11/12的成功轮次，修正顶部当前状态但不抹历史。

## 5. File-by-File Impact

所有实施路径均在V99；本轮只写主工作区计划及有界评审工件。

| 文件 | 允许变化 / 提交归属 |
|---|---|
| 主树与V99 `docs/plans/v13-registry-phase3-closeout-2026-10-19.md` | 主树是本轮交付；执行前审定版携入V99，A纳入。不把main其它脏文件带入。B只能更新§11执行记录。 |
| 主树与V99 `docs/reviews/v13-registry-phase3-plan-critique-2026-10-19.md` | 本次有界规划评审工件，执行前连同计划携入，A按明确路径纳入并核查内容；不等于被排除的Stage41旧review。B不改。 |
| `v13/registry/README.md` | 计数21→20、当前状态、runbook、接口保证/证据等级、两轮结果。A主内容，B仅结果追加。 |
| `docs/reviews/v13-control-plane-conformance-matrix-2026-09-26.md` | Stage41 `:188`、Phase2 `:249`及`:318`附近过时pending纠正；增Phase3当前行和真实覆盖；A/B按证据时间更新。 |
| `docs/reviews/v13-control-plane-deviation-ledger-2026-09-26.md` | 保留历史S41R/S42R；`:287`附近当前pending纠正，增P3R处置和限制；A/B。 |
| `docs/plans/v13-registry-stage41-2026-10-17.md` | `:6`顶部与`:29`W4完成证据对齐，保留历史步骤；A。 |
| `docs/plans/v13-registry-phase2-2026-10-18.md` | `:5`、执行记录及`:324`历史父协调交接加当前结论，明确93d05f1已完成证据提交，不改历史红；A。 |
| `docs/designs/v13-spacetime-registry-2026-10-17.md` | 在§11第6项教程收敛处加当前状态及Phase3引用，不新造重号§11.6，不覆盖设计正文或已实施errata；A。 |
| `docs/tutorials/v13/chapters/08-multi-language-harness.md` | §4.2列明的签名、字段、扩展练习、身份、协议范围；A。 |
| 同目录 `06-tool-catalog.md`、`02-effect-ledger.md`、`03-queue-as-wakeup.md`、`12-intervention.md` | 仅相关as-built字段/签名注记和示例；A。 |
| `docs/reviews/v13-registry-phase3-closeout-2026-10-19.md` | 新最终报告，A写precommit/待postcommit，B写A上真实postcommit及证据闭环；不得提前声称B推送。 |

禁止改变任何可执行面，包括`v13/**/*.sql`、`v13/**/*.py`、`v13/load.py`、CE/driver/manifest/lock文件；registry目录保留五文件：README.md、v13_registry.sql、setup_db.py、test_registry.py、test_consumer.py。不新增该目录文件。未跟踪Stage41 review先前明确排除（w4 final report `:48`），本轮不顺手提交；最终报告用自包含处置摘要而非依赖它。禁止提交prompt-exports、runner/wrapper、缓存、.DS_Store、.spike-flock或凭据。

## 6. 验证与运行规范

### 6.1 基线及静态preflight

以下为**未来执行命令**，不是本轮运行记录：

```bash
V99_ROOT=/Users/wxl/Projects/pg-agent/.claude/worktrees/v99
cd "$V99_ROOT"
git status --short --branch
git rev-parse HEAD
git branch --show-current
git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}'
git remote get-url origin
git fetch origin
# 比较HEAD与origin/v99，远端前进/分叉先处理，不等回归结束才发现。
git diff --check
```

G0先只读检查§6.2的PiSwift路径/worktree/tag/cache/runner，并在fetch后记录远端关系；环境缺失先解决授权前提，再进入G1/G2，不先投入大批文档编辑。记录93d05f1及其后继关系；若分支/HEAD/代码变化与计划不符，先解释并重定基线，不能自动接受任意后继。主树修改不得搬入。推送前`git fetch origin`、核对目标ref与ahead/behind，不能拿旧tracking ref当实时证明。

静态核对并登记来源：prefix SHA-256、三表八函数；loader41项末项registry；Stage42两表/11新增签名/20replacement/一个events capture trigger；前39个SQL、CE byte pins与允许的测试改动闭集；五参wrapper未变/六参替换/strict七参零默认；pin表及列权、函数owner/security/search_path/default/volatility；§2.5有效对象全部落点；registry五文件闭集。另逐项确认pin/event-pin immutable trigger、events capture trigger、ACL矩阵；effect_envelope确实剔除registry_revision，advance第八键存在，loaded全部consumer定义与README表一致。代码/loaded catalog由现有`setup_db.py:209`分段/validator、`test_registry.py:234`和`test_consumer.py:952`现有守卫核验；README文字一致性由执行者人工对照，不声称现有gate逐字检查文档，不添加/放宽断言。`git diff --check`和逐路径差异/凭据审查必须绿。

### 6.2 环境与离线预验证

现有gate测试用独立可跑脚本、local PG、fake provider/tool。setup会DROP/CREATE自身测试库，不能并行共享这些库，禁止指向生产DSN。核对`pyproject.toml`、`uv.lock`及脚本现有PG URI/本地server约定，不用pip/uv更新依赖解决验收。固定`UV_FROZEN=1`，外部IO不在事务。

**规划时已确认环境阻塞**：2026-10-19只读检查发现 `/tmp/pg-agent-w5-PiSwift-v0.87.1/PiSwift` 已不存在，PiSwift的worktree list保留prunable条目；两个隔离manifest和prepare.py仍硬编码此路径。活动checkout与tag/cache仍在，但不足以启动历史完整序列。G0进入BLOCKED_ENV，未来执行者须先向用户申请精确范围：清理这一失效worktree登记并在同路径重建detached v0.87.1、只写外部仓库worktree元数据及隔离目录，不切换/修改活动checkout。可参考已核验的旧`git worktree add --detach <path> v0.87.1`命令；不要无选择地prune其它worktree。批准前只做只读探测，拒绝批准则保留阻塞，不降低51项接受标准。本轮不恢复环境、不执行此操作。

历史成功环境是复用前提，不是要求修改用户当前checkout以匹配旧记录：

- 活动`/Users/wxl/Projects/PiSwift`历史为clean main/`a73c391ce1d891b7b6f8f37a8508f184a31703e3`，前后记录HEAD/status；发生新变化先停线评估，不切换或恢复用户checkout。
- detached `/tmp/pg-agent-w5-PiSwift-v0.87.1/PiSwift`历史为tag v0.87.1/`bfccb32f2d6318b75519b2c1790e7e66e133f5da`，只在隔离副本引用旧SDK。frozen两个Package.swift硬编码活动路径，无现成环境override。
- 旧Package.resolved有25pins，OpenAI pin `4ed3ea99ff9dfd2a760509ddb31020f4b153ef93`已在本地cache；将锁文件放入ignored临时package副本，唯一manifest变化为依赖路径，Sources逐字相同。
- ignored PATH wrapper用真实`/usr/bin/swift --package-path`及`--disable-automatic-resolution --skip-update`；每次核对Sources/原manifest保护，不造binary、不绕gate。runner/wrapper/verify.py必须先实际存在并阅读确认；缺失为BLOCKED_ENV，不假设它们随git发布，也不新建测试替代品。
- 先parity后ports，二者exit0、trace恢复才启动完整序列。不开PI_PARITY_REQUIRE_ALL；node_modules缺失仍如实SKIP。不能声称未知机器零网络或all-plane通过。

在上述已核实环境、V99根目录，使用新label，不覆盖旧receipt：

```bash
export PATH="$PWD/prompt-exports/w5-piswift-compat/bin:$PATH"
export W5_SWIFT_OFFLINE=1 UV_FROZEN=1
uv run python prompt-exports/w5-piswift-compat/preflight.py --label phase3-preflight-20261019-run01
uv run python prompt-exports/w5-piswift-compat/verify.py
```

label示例需先确认未使用；固定命名模式为`phase3-{preflight,precommit,postcommit}-YYYYMMDD-runNN`，每轮递增，runner目录exist_ok=False，绝不覆盖旧证据。preflight失败即停；依赖/工具恢复需另行批准，不改frozen driver、源码、manifest或resolution策略洗绿。历史当前SDK编译失败和旧SDK TLS失败仍是RED历史，不和新成功轮次拼接。

### 6.3 完整51项manifest

每行独立命令为 `UV_FROZEN=1 uv run python <路径与参数>`，严格按序，不并行。来自README `:295`起的完整表：

| # | 路径与参数 | 预期exit |
|---:|---|---:|
| 1 | `v13/acl/test_acl.py` | 0 |
| 2 | `v13/attention/test_attention.py` | 0 |
| 3 | `v13/catalog/test_catalog.py` | 0 |
| 4 | `v13/ce_run/test_ce_run.py` | 0 |
| 5 | `v13/characterize/test_characterize.py` | 0 |
| 6 | `v13/chunks/test_chunks.py` | 0 |
| 7 | `v13/control/test_control.py` | 0 |
| 8 | `v13/economy/test_economy.py` | 0 |
| 9 | `v13/envelope/test_envelope.py` | 0 |
| 10 | `v13/fair_claim/test_fair_claim.py` | 0 |
| 11 | `v13/fair_driver/test_fair_driver.py` | 0 |
| 12 | `v13/fanout/test_fanout.py` | 0 |
| 13 | `v13/filter/test_filter.py` | 0 |
| 14 | `v13/frontier_gap/test_frontier_gap.py` | 0 |
| 15 | `v13/goal_supervise/test_goal_supervise.py` | 0 |
| 16 | `v13/goal_supervisor/test_goal_supervisor.py` | 0 |
| 17 | `v13/goal_supervisor/test_goal_supervisor.py --unattended-continuation` | 1 |
| 18 | `v13/goal_supervisor/test_goal_supervisor.py bad-args` | 2 |
| 19 | `v13/govern/test_govern.py` | 0 |
| 20 | `v13/handoff/test_handoff.py` | 0 |
| 21 | `v13/loop/test_loop.py` | 0 |
| 22 | `v13/loop_driver/test_loop_driver.py` | 0 |
| 23 | `v13/manifest/test_manifest.py` | 0 |
| 24 | `v13/memory/test_memory.py` | 0 |
| 25 | `v13/mgraph/test_mgraph.py` | 0 |
| 26 | `v13/mgraph/test_stannum_usage.py` | 0 |
| 27 | `v13/mgraph_assembly/test_mgraph_assembly.py` | 0 |
| 28 | `v13/observe/test_observe.py` | 0 |
| 29 | `v13/periphery/test_periphery.py` | 0 |
| 30 | `v13/pi_parity/test_pi_parity.py` | 0 |
| 31 | `v13/pi_ports/test_pi_ports.py` | 0 |
| 32 | `v13/plan_arm/test_plan_arm.py` | 0 |
| 33 | `v13/plan_contract/test_plan_contract.py` | 0 |
| 34 | `v13/plan_read/test_plan_read.py` | 0 |
| 35 | `v13/quota_window/test_quota_window.py` | 0 |
| 36 | `v13/read_tools/test_read_tools.py` | 0 |
| 37 | `v13/real_chain/test_real_chain.py` | 0 |
| 38 | `v13/recall/test_recall.py` | 0 |
| 39 | `v13/registry/test_registry.py` | 0 |
| 40 | `v13/resolve/test_resolve.py` | 0 |
| 41 | `v13/schema/test_schema.py` | 0 |
| 42 | `v13/seam/test_seam.py` | 0 |
| 43 | `v13/should_run/test_should_run.py` | 0 |
| 44 | `v13/spawn/test_spawn.py` | 0 |
| 45 | `v13/summary/test_summary.py` | 0 |
| 46 | `v13/triage/test_triage.py` | 0 |
| 47 | `v13/twophase/test_twophase.py` | 0 |
| 48 | `v13/workflow_bind/test_workflow_bind.py` | 0 |
| 49 | `v13/workspace_admit/test_workspace_admit.py` | 0 |
| 50 | `v13/workspace_exec/test_workspace_exec.py` | 0 |
| 51 | `v13/registry/test_consumer.py` | 0 |

已存在runner的入口：`UV_FROZEN=1 uv run python prompt-exports/w5-phase2-runner.py <unique-receipt-label>`，保留§6.2环境。README也是runner输入：runner按下列正则提取清单（实际来源为ignored `w5-phase2-runner.py:20`），不是任意Markdown表：

```regex
^\| \d+ \| `(v13/[^`]+)` \| ([012]) \|$
```

G1/G3/G5必须保持原51行清单逐字节不变，且不得在README其它位置新增匹配该格式的结果行；结果表用阶段名/更多列避免匹配。B前后按同一正则核对解析出的恰好51项、互异且与§6.3完全一致。README名称在现有guard许可集合内，不代表其清单内容可任意修改。

执行前核对runner确实使用以上51项、预期退出码和现有success/refusal/usage marker；#17 FAIL/ask_user refusal与#18 usage是契约成功，不是漏测。

每行必须记录command、exit、时长、关键输出、valid、trace_restored。runner只验exit/trace及#17/#18 marker，**不核对485/289 checks或外部环境/净树**；执行者在G3/G5完成后人工查看#39/#51原日志SUMMARY，并调用verify.py、记录HEAD/status，未完成这些核对不得仅凭valid=true宣布绿。precommit记录文档脏树的HEAD/status和变更路径，postcommit记录A及前后tracked clean，二者不能混用。每项结束（包括失败/timeout）恢复trace原bytes和mode，比较SHA-256及mode；不得用`git checkout`覆盖未知用户变化。开始时若trace与已知净树基线不同先停。所有51项及pre/post的trace闭环必须能分别复核。#39要求registry16/16、485checks、零independent-case failures；#51 consumer289checks。任何计数漂移先解释，不改测试/预期凑数。read_tools E4内嵌registry/parity/ports为额外证据，不替代外层各行。

runner单项timeout=600秒；TimeoutExpired会经finally恢复trace，但异常穿出、不写该条results.json。发生时执行者按日志/异常记录该项TIMEOUT（无gate退出码）、实测trace状态，其后NOT RUN，不能只看现存results.json误认为该项未启动或把timeout当业务断言失败。不得改runner延时或补测试逻辑以继续本轮。

任一非预期exit、marker失败、timeout或恢复失败立即停，后续标NOT RUN；修复/环境变化经批准后用新label从#1重开，禁止串接多次历史/独立单测算完整绿。

## 7. 操作状态、错误与停止条件

```text
BASELINE_LOCKED -> ORACLE_DECIDED -> DOCS_READY -> STATIC_PREFLIGHT
 -> ENV_PREFLIGHT -> REGRESSION_RUNNING -> PRECOMMIT_GREEN
 -> COMMITTED_A -> PUSHED_A -> POSTCOMMIT_GREEN
 -> COMMITTED_B -> PUSHED_B -> CLOSED
```

ORACLE_DECIDED已有§3.1裁决，执行只核对其代码前提；不自动开启新一轮规划。任何真实反证需记录并停线，不假定Oracle能覆盖红gate。

| 情况 | 真实行为 / 执行动作 |
|---|---|
| branch/HEAD/upstream/代码状态无法解释 | BLOCKED_BASELINE；停止，不混main，不覆盖用户更改。 |
| Oracle裁决前提被新代码/loaded证据反证且无法闭合 | BLOCKED_ORACLE；记录具体冲突，停止宣告完成；若证实运行缺陷转BLOCKED_PHASE2_DEFECT，不凭旧裁决覆盖事实。 |
| 缺clock/tools seed | fences/probe/envelope/claim fail closed P0001，不补0。registry context本身clock缺seed也报错；不混淆未注册scope与配置损坏。 |
| 函数/adapter复核发现双fence变更 | STATIC：函数分支40001/CAS与pin回滚，尚无直接异常探针；历史DIRECT仅测试模型的adapter比较后rollback。不得把两者合算为函数40001已实测；若实际观察到部分写入才按真实缺陷阻断。 |
| 复核后writer提交 | 已接受窗口，pin仍exact；后续current投影可能false。不是撤销IO/自动重试保证。 |
| strict token错误 / revision非法 / 缺pin / revision不匹配 | 依序stale / 22023 / P0001 / stale；不猜latest pin。旧exact仍可accepted，terminal exact可replay。 |
| 手工UPDATE/DELETE pin或mapping | frozen触发器拒绝（SQL `:642`、`:665`），运维不得绕trigger清理历史；Phase3无GC。 |
| mapping capture/FK或immutable guard失败 | event/seq/settlement/mapping事务整体回滚；不得绕trigger手工修历史。出现半写转BLOCKED_PHASE2_DEFECT。 |
| 有pin历史缺mapping或malformed锚 | false不RAISE；无pin历史legacy/CE/synthetic仍eligible，不删audit。 |
| 发现可达spawn_owner claim caller、对象闭集超集、projection真实缺陷 | BLOCKED_PHASE2_DEFECT；另行Phase2修复及其测试/工件/提交，不在Phase3改代码或弱化标准。修复后重新锁基线、全序列，不继承过期绿。 |
| 离线依赖/runner/wrapper缺失、parity/ports预验证红 | BLOCKED_ENV；不启动51、不改依赖策略或外部checkout自救，不把NOT RUN记失败退出码。 |
| 51项任一非预期结果或trace恢复失败 | RED_REGRESSION；失败即停，保留收据，后续NOT RUN。 |
| 仅默认parity node_modules SKIP | 按受限覆盖记录，不声称all-plane，不临时开启strict改变接受标准。 |
| 暂存可执行面、无关文件、ignored证据或疑似凭据 | 停在暂存审查；逐项撤出本轮误加项，不回滚他人修改，不commit，不跳hook。 |
| hook失败 | 修根因后重验；不用--no-verify。 |
| push拒绝/远端变化或分叉 | PUSH_DIVERGED；fetch一次核对差异，不force/reset。无法安全确认线性追加时问用户；不盲rebase含他人工作的分支或改变push目标。 |
| A之后postcommit红 | 不撤销已推A，不提交RED-B、不提交“完成”B（测试红不满足AGENTS提交前提）。原始红/NOT RUN写新ignored receipt与日志，并向用户交付阻塞回执；仓库A永久保持postcommit pending/Phase3未闭环的自洽状态，后续批准恢复后才从#1重跑。此时G6/CLOSED不可达，不用第三提交假装收尾。 |

## 8. 执行索引

G0–G6为同一里程碑内部工作项，Size为相对执行量，不是新增gate编号或工期承诺。

G1显式质量闸：把协议模型写成生产worker保护、把INFERRED/STATIC写成DIRECT、删历史RED、破坏README清单，立即退回修订。G2显式质量闸：报告仅靠ignored收据才能理解、漏manifest/断言指针、把未跑算通过，不得进入G3。

| 工作项 | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| G0 基线与裁决复核 | 定位V99后继、提前探测环境、携入审定计划/评审 | fetch后记录HEAD/upstream/status，缺失PiSwift隔离worktree先获用户批准恢复并复核保护边界，四项裁决前提未被反证，未跟踪review排除，无未知代码漂移 | 本计划、Phase2 plan、setup_db.py:52、SQL:702/822、consumer:504/634/952 | 无 | M |
| G1 文档/runbook/教程 | 纠正事实及运维支持边界 | §4.1/4.2全部落实、pending状态对齐提交链、历史RED保留、五文件闭集不变 | §5全部状态/教程/README/design路径 | G0 | L |
| G2 跨层证据 | 建立永久自包含报告 | §2.5及§4.3逐项可查，证据分级准确，未来结果全为NOT RUN/pending | final report、matrix、ledger、现有SQL/两test只读 | G1 | L |
| G3 静态/环境/precommit51 | 实跑完整受限验收 | 静态preflight+parity→ports+51项全部契约通过、trace闭环，真实结果回写工件 | §6 manifest、README/matrix/ledger/report | G2 | XL |
| G4 提交A并立即推送 | 固化主收尾工件和precommit证据 | 逐路径暂存/凭据审查通过，A提交成功、origin/v99 push成功，tracked clean | §5文档allowlist | G3 | S |
| G5 A上postcommit及B | 证明提交态、追加真实证据 | A净树从#1重跑51通过；B仅允许结果文档且执行面完全相同，commit后立即push成功 | 同manifest；README/matrix/ledger/final report、本计划仅§11执行记录 | PUSHED_A | XL |
| G6 最终只读审计 | 关闭里程碑、交付事实 | HEAD=B、远端核对一致、tracked clean，报告A与两轮收据，向用户回执B hash和push结果；无C/main推送 | git refs/status、永久工件 | PUSHED_B | S |

### 8.1 A：主文档提交

G3全绿后更新收尾工件，再按路径逐项add，提交前两次status及cached diff核对，不用`git add -A`/`git add .`。命令骨架：

```bash
git status --short
git add docs/plans/v13-registry-phase3-closeout-2026-10-19.md
git add v13/registry/README.md
# 其余仅按§5明确路径逐项添加，逐项查看内容/疑似凭据。
git status --short
git diff --cached --name-status
git diff --cached --check
git diff --cached
git commit -m "v13: record registry phase3 closeout evidence"
git fetch origin
# 核对branch=v99、upstream=origin/v99、origin URL及线性追加关系。
git push origin v99
```

A commit/push任一步失败即停，不跑下一步postcommit，不积压到B后推送。fetch后的新远端改变了测试基线时不得继续使用旧绿；需人工确认整合/重新锁定并重验，禁强推。根AGENTS里程碑纪律不因文档only而跳过。

### 8.2 A上postcommit、B证据追加与闭环

- A push成功后，确认HEAD=A、tracked clean，沿用同manifest/环境以新label从#1重跑51；前后HEAD及tracked status、trace、外部checkout保护均记录。不得以docs-only为由省略此轮。
- 全绿后只写实际postcommit结果至README/matrix/ledger/final report；必要时更新本计划§11执行记录，但B不得改教程/runbook行为性内容或任何执行面。A仍有无关内容错误须先评估其是否影响验证，不能偷装入“结果追加”。
- 明确定义执行面为§5白名单文档以外的**全部tracked路径**，另加README的51项清单表及其正则解析结果。比较`git diff A --name-status`与cached path allowlist：B只可README/matrix/ledger/final report结果追加、本计划§11，所有非白名单路径必须无diff；SQL/Python/loader/驱动/依赖/fixture/trace byte和mode相同，README清单字节及解析的51项相同。记录无需第三轮51的理由与已验证A的hash，执行`git diff --check`/cached check。
- 按路径add、status/cached diff/凭据审查、正常hook，提交 `v13: record registry postcommit closeout`，立即核对远端并`git push origin v99`。禁止--no-verify/force/force-with-lease/reset --hard。
- B不能自含自身hash或未来push结果。push后只读`git rev-parse HEAD`、fetch后ref、`git status --short --branch`核对，向用户报告B身份、两次push及最终分支；不为写入这条回执再开C。若远端分叉先停问；任何rebase/合流改变已验证执行面，旧postcommit证据失效，必须重新决定回归而非沿用。

## 9. 风险、后续项与开放问题

已决成本：global blast radius、tools无历史轴、claim复核窗口、latent spawn_owner ACL/API差异、组合场景INFERRED覆盖、append-only pin增长。它们不在Phase3被修复；一旦出现真实可达缺陷按§7回交，不能只记台账就宣告绿。

环境风险：tag/cache/wrapper是本地ignored依赖，不随git发布；缺失时停止，不承诺任意机器复现。主树/V99分离需要执行前携入计划和重新核对分支，main整合仍是后续工作。原始日志可丢失，永久报告必须保留可判读摘要和限制；不得将ignored工具/敏感配置强制add。

明确后续而非收尾交付：生产strict worker、框架pi/pig/piswift DB parity、strict all-plane、真实provider、CE registration_generation映射、profile/prompt消费形状、TTL/GC、生产在线migration/rollback、main合流。规划时没有未决的实质设计取舍，但当时**执行前仍需用户批准恢复已缺失的PiSwift隔离worktree**，见§6.2。该批准及恢复已在§11完成；随后用户授权的独立Stannum升级U亦见§11。外部环境所有权要求不降低51项标准。远端状态变化同样按停止条件处理，不自动猜测。

## 10. 规划基线保真与纠正记录

本计划保留context_builder生成响应的现状、接口/数据流、20项闭集、ACL/锁边界、错误分支、逐文件影响、完整51项、环境/trace保护、状态机、工作项及证据寿命要求。完成一次有界设计评审并处置后，按原生成响应逐项完成Phase7.5保真核对：

| 生成基线内容组 | 保留位置与核对结论 |
|---|---|
| Summary/Goal、main与V99/提交链、历史485/289及51项/trace/skip | §1、§2.1/2.2；明确历史非本轮，补断言位置，无损保留。 |
| current-state、clock/meta/tools/history、claim→pin→IO→complete→投影、ACL/锁 | §2.3–2.5；明确模型与生产路径差异，增加全部具名consumer，修正异常证据等级。 |
| 四项决策/替代/边界 | §3，Oracle真实补充纠正错误假设，所有更改理由见下表。 |
| runbook/anchor/health/error/rollback、教程多章节 | §4；只删未经验证的生产在线迁移承诺，替换为等要求的停写备份/审计保全/后续设计，隔离验证及参数/ACL核验仍明确。 |
| file-by-file及禁改/禁提交 | §5；补本次critic工件携入规则，旧Stage41未跟踪review仍排除。 |
| baseline/static/env、完整manifest、trace/receipt、时长非门槛 | §6；51行与原README逐行核对一致，恢复三项静态条目，补runner真实边界与环境已缺失事实。 |
| 状态机/全部错误/stop、immutable、no-third-loop | §7、§8；G1/G2显式质量闸恢复，新增A已推但postcommit红的精确停止形态。 |
| 每项Goal/Done when/Key files/Dependencies/Size、commit/push、风险/未决 | §8/§9/§11；A/B各立即push，G0前移环境/fetch，未来恢复授权作为执行前置。 |

以下为有依据的纠正，不是为缩短内容删除细节：

| 草稿项 | 纠正及依据 |
|---|---|
| ORACLE_NOT_AVAILABLE/未来再裁决 | 改为§3.1本次真实成功Oracle响应；首次watchdog失败不算结论。 |
| setup replacements在27行 / prefix含604 | replacements从52行；前缀1–603，604为sentinel，按实读代码。 |
| spawn_owner到pin_insert才拒绝 | fences先于CAS，先42501；不能把NOLOGIN等同不可达，按Oracle裁决。 |
| pin_matches因注册变化翻false | 它只读exact历史pin，不读clock；current helpers才随新快照失效，SQL:746/756。 |
| 两个文档里程碑、A/B最后一起push | 单一Phase3内部任务，A/B各立即push，符合AGENTS；B只追加结果，禁止自引用预填push。 |
| 在线应用overlay或恢复Stage1函数即可回退 | 未有验收migration工具，移出支持面；只写隔离库演练/只读核验、停写备份/审计保全/另提迁移。恢复应各对象最后有效定义，不能Stage1早期定义。 |
| 新造§11.6 | 设计现有§11是编号列表，在第6项加状态注记，不制造重复标题。 |
| 活动PiSwift必须倒回a73c391 | a73c391是历史保护基线，当前变化先评估，不覆盖用户checkout。 |
| 直接复用旧PiSwift临时worktree | 评审及父控制器只读复核发现路径缺失/prunable；环境探测前移G0，恢复需用户批准，不悄悄降低验收。 |
| runner valid即可证明全部验收 | 补人工SUMMARY/HEAD/status/verify核对、timeout缺行规则、README清单输入保护；不修改runner或测试。 |
| postcommit红后模糊的“记录” | 明确不提交RED-B：保留ignored红证据与用户阻塞回执，A维持pending；不绕过AGENTS红灯停线规则。 |

## 11. 执行记录

- 当前状态：独立Stannum升级U已提交推送；G0/G1/G2在U上重新核对。历史G3 run01 RED保留；新precommit run02已从#1完整通过（918.90s，49×0及预期1/2，全trace恢复，registry485/consumer289）。A/B未提交，A后postcommit51项仍待运行。
- 原run01基线：2026-10-19 fetch 后 HEAD=`93d05f12090ce4b27b62b1a6f90d3c1b438eab68`、`origin/v99` 同值、ahead/behind 0/0；分支 `v99`，upstream `origin/v99`。独立工作树无变更；无 runtime/test/loader/ACL/trace diff。
- 用户批准恢复隔离 PiSwift worktree。`/tmp/pg-agent-w5-PiSwift-v0.87.1/PiSwift` 为 tag v0.87.1=`bfccb32f2d6318b75519b2c1790e7e66e133f5da` 且 clean；活动 `/Users/wxl/Projects/PiSwift` 仍 clean `a73c391ce1d891b7b6f8f37a8508f184a31703e3`。`phase3-preflight-20261019-run02` parity/ports 均 exit 0，trace 恢复；verify 证明 frozen Sources/manifests 未变。run01 亦保留，未拼接回归序列。
- 实际隔离加载核验：41 项 loader，overlay +2 tables/+11 signatures/20 replacements；三张 prefix tables/八函数校验通过。loaded `spawn_owner` DEFINER 共六个，逐个读 prosrc 未见 claim caller（STATIC，不代表任意动态 SQL 的证明）。pin/mapping immutable 与 events capture trigger 已在实际 catalog 装载确认。测试中创建的隔离 registry database/host roles 已按 setup 生命周期清理。
- G1/G2 工件：README runbook、教程/设计/前两阶段计划、matrix、ledger 与本报告已更新；历史 S42R-9/10 RED 和 S42R-11/12 成功证据保留。完整教程与证据清单已最终静态复读；README/HEAD/§6.3 清单恰好 51 项且逐字一致，git diff --check 通过。
- precommit `phase3-precommit-20261019-run01`：HEAD 前后仍为 `93d05f1`，文档脏树、未暂存；fetch 后 origin/v99 同值。#1-25 契约通过（#17=1/ask_user、#18=2/usage），#26 `test_stannum_usage.py:605` V1 exit 1（预期 0）、6.59s；26 项累计 202.46s。实查 installed/default/library Stannum 均 0.5.1，而 gate 要求 0.4.0；PG 18.4。#27-51 NOT RUN，未继续拼接。全部 26 项 trace 恢复，最终 hash/mode 与 §2.2 相同，PiSwift verify 仍绿。README/matrix/ledger/final report 已保留红灯；不提交/推送，不改 gate/依赖。当时隔离恢复 Stannum 超出 PiSwift 专项授权，已请求批准；随后用户改为授权升级0.5.1（见下条），不沿用原环境恢复方案，也不拼接原绿段。
- 用户授权独立升级Stannum0.5.1，经Oracle计划与实施审查完成U=`16e2d8b682b3b449fa45620805d337a668a6294d`并已推送origin/v99。定向16项与独立upgrade51（908.70s，49×0及预期1/2、全trace恢复、registry485/consumer289、PiSwift verify绿）不替代Phase3两轮。执行基线重新锁定U，HEAD/origin相同0/0；Phase3范围仍仅文档。stash十二文件逐字节恢复，matrix/ledger保留U与P3两组追加，stash仍保留。SQL/运行时/loader/依赖相对U无diff，四项Oracle裁决代码前提未变；新run02从#1开始。
- Phase3 precommit run02 receipt `prompt-exports/phase3-precommit-20261019-run02/` 已通过：51/51 valid、918.90s，49×exit0、#17/#18预期1/2；trace全恢复，registry16/16/485/0，consumer289，PiSwift verify绿。该轮不替代A后postcommit。A仍未提交/推送，postcommit必须在A上从#1重跑。
- B 仅可在本节追加已发生的 A 身份、A 推送及 A 上 postcommit 事实；不写 B 未来 hash/push 结果。

## References

- 根 `AGENTS.md`：测试实跑、收尾工件、逐路径暂存/提交推送与IO纪律。
- V99 `docs/plans/v13-registry-stage41-2026-10-17.md`；`docs/plans/v13-registry-phase2-2026-10-18.md:324`及`:338`。
- V99 `docs/designs/v13-spacetime-registry-2026-10-17.md`；`docs/reviews/v13-registry-phase2-plan-review-2026-10-18.md`。
- V99 `v13/registry/README.md:158`、`:282`、`:472`、`:567`；setup_db.py、test_registry.py、test_consumer.py及v13_registry.sql。
- V99 control-plane conformance matrix/deviation ledger Stage41/Phase2区段；历史原始receipt路径见§2.2，不能作为永久工件唯一依赖。
- Oracle会话 `v13-时空注册表收尾开发计划-B3B005`，2026-10-19规划稿及有界补充裁决；规划评审工件另见 `docs/reviews/v13-registry-phase3-plan-critique-2026-10-19.md`。
