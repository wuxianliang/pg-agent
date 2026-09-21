# V8 × 本地 DeepSeek Harness 对比与 V10 开工联合计划

日期：2026-09-17。状态：调查后实施计划草案；已做一次Oracle计划审查与修订后review（`new-chat-29253A`，review快照`2026-09-17/1457`），结论为未发现阻断性计划漏洞；三项非阻断建议已落实。未实施本计划 gate，未证明 DSH sync_before_io 或 v10 wire gate。该review不是规格L4或运行准出。本文不修改冻结规格，不把源码可接入推断写成运行通过。

## 1. 目标、效力与证据

### 1.1 两个目标，不混用完成口径

- **目标 A（V8 对比）**：官方 DSH loop 经 pg-agent adapter 使用 v8 控制面和唯一事件真相，与 Native 在同一 fixture、假 provider 和 canonicalizer 下得到相同 observable trace；按 v8 §5.2 完整报告数据库层/真实 I/O 层及能力差异。正常单 turn 只是首个闭环，不替代恢复/取消/权限/世代等验收。
- **目标 B（V10 可开发）**：完成 v10 §2.5/§7.1 接入产物；初始化、generation 指针、manifest、权限、冻结 payload 的代码接合有唯一答案；不要求先实现 v10 的 persona/artifact/Plan/Bind/Feedback/POML 才准许开发它们。
- 本计划不重分 v10 P0–P3；仅先补接入并验证可行性。V10 的完整 assembly/render conformance、性能 spike 和产品发布验收仍在对应阶段执行。
- 权威：`docs/designs/v8-dev.md`、`docs/designs/v10-dev.md`、后者轮 6 L4 终裁。`v8-p0c-compat-host-plan-2026-09-17.md` 是参考草案，其中旧 npm 发布线、持久化九方法与五条新增事件等结论须以本地 pin 重新核对；本文不编辑或宣布历史文件整体作废。

### 1.2 已核实基线

| 项目 | 调查证据 |
|---|---|
| pg-agent | HEAD `2b0edf64638872ab06157e5968186e6a814b571f`，本地 origin/main 同值；未重新 fetch，不宣称远端实时状态 |
| 本地 DSH | `/Users/wxl/Projects/deepseek-harness`，干净 `master`，commit `0d1f50007f9bca3f52b06e1c3074fa14d5fb0720` |
| DSH 包/工具声明 | 根 `package.json`：0.1.6-alpha.1，`packageManager=pnpm@11.7.0`，Node `^22.19.0 || >=24.0.0`；本机 Node v24.13.1 |
| DSH 锁文件 | `pnpm-lock.yaml` SHA256 `ca131858949bd12b2acfc227b1af7dfa3c8d65e74b234824d5c741e6421010a1` |
| 本地构建状态 | node_modules 目录存在，但调查时 `.bin/vitest`、`.bin/tsx` 及所查 agent-loop/session-persistence 的 lib 不存在；没有据此宣布安装/构建/测试通过 |
| PG 基线 | 本轮此前实跑：PostgreSQL 18.4，pgembed 0.3.0rc2；满足 v8 最低 PG15，未认证其他 PG 主版本 |
| V10 正文 | 1098 行，SHA256 `1bfe744c1c90358813dbeefb66b7e85e0a0e70933c3a3fa0de0f6d41f895a445`，与轮 6 L4 通过版一致 |
| V8 实跑 | 2026-09-17 调查串行复跑 24 脚本，23 exit0、compat exit1；无 provider 凭据，无真实模型调用。compat 单独复现同错 |

实跑原始日志位于调查机器临时目录 `/var/folders/s7/nqsvqzc17pz9bh_71pfc2nv40000gn/T/v10-readiness-20260917-5h_l_5hd/`，单独复现 `/tmp/v10-readiness-compat-rerun-20260917.log`。这些不是可移植归档；J0 必须重新生成并保存脱敏报告、命令/版本/退出码与日志摘要，不能以临时路径充当永久准出证据。

主要数据库依赖已交付且上述实跑通过：G10 授权、G11 世代、G12 双门/cohort、G14 并发、G15 drain、G16 audit、G17 compact、G18 switch/fork、G19a assemble、G19b reconcile 结果/收尾。不得沿旧 README 的陈旧 LATER 再安排整套重做；也不得仅据各 stage 测试通过宣称全加载集的每种集成都已验证。

## 2. 本地源码改变了哪些计划前提

以下路径以 DSH 根为基准，行号针对上述 pin，后续升级须重核。

| 源码证据 | 对计划的影响 |
|---|---|
| `packages/session/session-persistence/src/index.ts:111–201`，`handle.ts:59–117` | Service 是 create/open/flush/stat/list；handle 是 read/append/flush/close/asyncDispose。append 只承诺本实例可见，flush 才是 durability barrier；旧九方法不可照抄。PG 可提供更强的提交后 append，但仍需实现 flush/close/ownership |
| `packages/session/session-checkpoint-policy/src/index.ts:29–38,62–81` | LLM 在 `yield* next()` 前 flush，top-level tool 在 next 前 flush，另有 pre-step flush；无 session/nested tool 分支会绕过这些检查。flush 事件前缀不等于 v8 dispatch 已提交；必须有 ledger gate 和覆盖范围限制 |
| `packages/core/agent-loop/src/index.ts:888–911` | resume 先 open(write)/read，再 `interruptedTurnClosers()` 并 append 合成 closers；host 推测的 interrupted 不是 provider 失败/取消证据，不可直接当 v8 repair resolution |
| `packages/core/agent-loop/src/agent.ts:443–463,549–618` | 请求从日志 derive/freeze；失败会记 assistant/attempt 并通过 request-error 决定 continue 重试。每次实际 I/O 的 ledger attempt 必须核定，不能把 Cordis ctx.effect disposer 当 v8 effect_id |
| `packages/core/session/src/known-event-types.ts:22–78`、`docs/architecture.md:85–121` | 有 system/message、assistant/attempt、request/*、llm/retry、PTC 等新词表；实时 chunk 来自 agent/assistant-stream，完整 compact stream 归入最终 message/attempt。映射不能仅补旧计划所列五行 |
| `packages/core/tools/src/index.ts:1471–1513,1539–1571` | pre-execute 之后仍有 ask/guard/cancel，body 另行调用；在 pre-execute 落 dispatch 可能过早且不能凭监听器顺序证明无旁路。最终执行包装必须核 frozen args、授权与 attempt |
| `packages/llm/llm-deepseek/src/protocols/chat-completions/adapter.ts:315–374` | adapter 在 waterfall 下游序列化、执行 request extensions，再 fetch；requestFiles.retry 还能 continue。v8 trace 相等不证明 v10 wire 相等；不能在 seal 后让 stock serializer/extensions 改请求 |
| `docs/architecture.md:41–47`、根 package.json | 官方应用用 dsh CLI/profile，内置包用 workspace/link。默认采用本地 commit 构建的独立固定 checkout，不把 latest/next 或第三方 dsh-postgres-backends peer 冲突作为开工阻塞；外部依赖仍需按锁文件安装 |

已有 keyless 参考：`packages/test-support/loader-smoke/tests/fixtures/cli-mock-llm.ts`（LlmAdapter 注册）、`packages/test-support/llm-mock-server/src/index.ts`（HTTP/SSE mock）、session-persistence 与 storage 各自 `tests/contract.ts`。本轮只读源码，未运行 DSH 测试。

## 3. 总依赖图与准出等级

```text
J0 基线修复 ── J1 pin/构建 ── J2 四项接合探针 ── J4 PG providers ── J5 ledger执行桥 ── J6 最小双loop对比 ── J7 全支持面验收
       └───────────────── J3 compat数据库套件 ──────────────────────────────────────────────────────────────┘
       └──── V0 v10接合裁定/命名/F-08 ─────────────────── V1 固定payload来源门/集成验证 ───────────────────────┐
                                                        J5 ────────────────┘                              ↓
                                                                                         J8 联合准出/正式v10 P0
```

- **现在可做**：本计划审查、J0/J1/V0 的调查与裁定；固定输入的 v10 计算试验（不装正式 schema、不声称正式接入）。
- **J6 完成**：可声明 pinned DSH 最小 turn 已与 Native 对比，但 J7 报告仍需完成，不宣称完整 P0C。
- **J8 完成**：本联合计划的正式 V10 P0 开工门；采用保守口径，依赖完整支持面报告，不从一个正常 turn 的绿推导全面接入。
- 若只希望先开放 Native 子集，必须另作显式范围裁定和报告，不能靠本计划默默降低 §7.1；本计划默认目标是两条线同时达标。
- J2 任一必要接合不成立：停相关路径并报告。禁止为了让主目标通过而 fork 官方 loop、绕授权、把未知当失败重放、以 Python loop 冒充 compat、或发明 capability 第四取值。

## 4. Gate 工作包

下列 `test_*.py` 中未存在者均为拟新增入口；验收是未来义务，不是当前结果。每个 gate 内部须有全部测试命令与依赖表，独立测试库、固定 fixture，退出码 0 仅表示该 gate 的规定断言通过。

### J0 — 修复基线与报告事实（先做，不依赖 DSH）

1. 把 `v8/compat/test_compat.py:1076–1084,1181–1188` 的 fake suite 从凭据分支分离。无凭据也实际执行 fake 断言并登记 `c12-db-fake-suite`；不能直接赋 passed 掩盖漏测。
2. 实跑无凭据 G13；同步当前真实计数，不预设153/155。真实 provider smoke 保持可选，不能成为普通 gate 的通关依赖。测试实际执行命令显式移除 DEEPSEEK_API_KEY/OPENAI_API_KEY/OPENAI_API_URI；不能只靠约定环境为空。
3. 更新 README/Conformance/偏差台账里已被 G10–G19 消解的陈旧缺口；未接线的 compat fixture 不因 Native 测试绿而翻绿。
4. 报告器分开“已声明支持面符合合同”“最小双loop通过”“完整目标达成”；必跑子例 partial/未运行/failed 一律不通过。合法 capability blocked 必须保留，optional 真实 provider 凭据缺失不应阻止 keyless P0C，也不得被篡改成 passed。
5. 无凭据串行跑当前全部24脚本；保存实跑与提交基线证据。后续每新增gate扩入机器可读清单，别继续手算总数。

入口：既有 `uv run python v8/compat/test_compat.py` 与24脚本清单。文件：compat测试/报告器、README/矩阵/台账、新基线报告；不改产品协议。

### J1 — 本地 pin 与可复现官方启动

1. 固定 DSH 完整 commit、源树/锁文件摘要、Node精确版本、pnpm11.7.0、session format、profile合成结果digest；记录adapter/canonicalizer版本和后续构建产物摘要。版本身份改变建新manifest，不原地改不可变记录。
2. 默认 `DSH_SOURCE_ROOT` 指向独立 detached checkout（来源可为本地仓库）；脚本核 commit/dirty/lock，任何不符拒绝。不得修改用户 master，也不依赖未锁定的绝对路径软链。CI须能从记录的git来源取到同commit；安装使用正确cwd与声明pnpm，禁止 legacy-peer-deps/强压peer作为捷径。
3. 按冻结锁文件安装/最小必要构建；外部依赖下载与provider调用不同，安装结果须实际验证。环境诊断发现缺bin/lib即显式报告，不猜已安装。
4. 在独立临时 DSH_HOME、隔离 profile 下通过官方 CLI/Loader 启动真实 agent-loop；只挂 fake model/tool、PG适配所需插件及必需核心，不挂默认真实模型、JSONL/SQLite session backend、自动重试或附带网络任务。
5. 记录 resolved plugin tree，拒绝第二 session persistence/backend；验证启动/关闭与无真实凭据，无意外环境/.env读取导致外调。
6. 发布版本化 `required-support-matrix.json`：按v8 §5.2/§6每条子例标明 mandatory-supported、mandatory-negative-rejection、合同允许的capability-blocked条件、或明确超出本目标（附规范依据）。数据库层必跑不因profile缺能力而免除；profile裁剪不得改分类；J2补齐实际能力证据后锁定矩阵版本及SHA256，J7/J8消费同一份。锁定后改变分类/范围必须生成新版本、记录规范依据并经审查，重跑受影响gate；不覆盖旧报告。目标A至少要求真实loop最小turn、LLM与tool同步派发及取消/unknown对比；降级T0不能让目标A绿。

拟入口：`uv run python v8/compat/test_host_pin.py`。最小 smoke 可参考 DSH loader-smoke，但需按当前pin实际验证命令；不要求跑上游全仓coverage。产物：`v8/compat/evidence/source-pin.json`、profile锁定快照、构建/启动报告。

### J2 — 四项 go/no-go 接合探针（小桥验证，不先建完整产品）

本gate只验证公共seam是否能挂接、阻断、传递冻结值；不验收完整PG provider或真实恢复闭环。拟文件 `v8/compat/probe/{checkpoint-probe,request-probe,resume-probe,event-inventory}.ts` 与 `test_host_probe.py`：PG shim只允许对预建fixture调用既有seal/dispatch及查询，handle探针只记录/拒绝调用并用冻结seed测试。不得在此实现可用的生产SessionPersistence、重建数据库日志、重试分配器或新调度状态；这些归J4/J5。探针断言与fixture留作回归，临时shim不能被产品profile加载。

J2-A可用预建effect和最小dispatch插件观察真实调用入口的提交顺序；J2-C/D只证明可放置恢复门、完整拦截事件和按当前schema重放seed。跨进程持久化重建、真实未知收束与全ledger执行必须在J4/J5完成后重跑，不用J2替代。

**J2-A 持久派发顺序**：LLM和tool各自建立step/slot/attempt，事务提交后才允许外部动作。受控HTTP/SSE mock与独立tool探针在首次动作入口，用**另一DB连接**验证 `dispatch_started`、冻结identity与授权结果。人为阻塞提交时零动作；回滚/撤权/过期fence/取消时零动作；提交后crash只按unknown/recovery处理。Promise先后和打印日志不是提交可见性证明。checkpoint flush和dispatch gate分开断言。

**J2-B 请求来源**：用预先冻结的固定descriptor/wire验证公共 LlmAdapter/service seam是否可原样发送；识别 prepareCall/resolveModel、图片上传、extensions、fallback及内部retry等额外IO。冻结后不允许stock serializer再造wire。推荐独立 `PgLedgerLlmAdapter`，官方loop不改；如调用stock provider，必须证明其最终字节不变且没有未登记副调用，不能仅比较messages。此时不实现v10装配算法。

**J2-C 恢复/重试归属可拦截性**：以固定中断seed触发官方resume，证明公共 `SessionPersistence.open(id,'write')` 可在返回handle之前拒绝/等待合法受控恢复，且拒绝时不publish agent、不调provider；这是实际拦截位置，不要求修改private resumeWith。同时handle.append识别synthetic closer并稳定拒绝不匹配的合成终局，失败后不继续loop。测request-error hook能阻止未经v8分配的retry。真实crash/lease/repair闭环归J5。

**固定恢复流程（J4/J5实施）**：open(write)先按认证上下文查询并锁定v8当前控制态；上下文来自PG受保护principal/driver链，不接受调用者自报session ID充当认证。记录W/S、driver/epoch、owner/fence绑定、有效期/撤销及handle生命周期；每次受控写重验当前授权，close只释放自己仍持有的ownership；仍有unknown、in-flight、有效旧job lease或其他未收束工作时不把可执行write handle交给loop，只走合法recovery/repair/reconcile并返回稳定阻塞/拒绝。经v8收束且可恢复后，read投影已接受的事实；DSH仍提出synthetic closers时，append只能核对并映射已有v8终局/受控receipt，不据host猜测创设终局。无法映射则拒绝整次恢复，不能返回伪closed日志；旧owner的close不得释放新owner。若open门/append门无法阻止继续执行，J2-C为no-go。

**J2-D 日志/序号设计可行性**：DSH逻辑seq从0连续，v8 raw seq含audit/observational且按自身协议分配，不能简单加减1。以含system/header/message/tool结果/attempt的固定seed测官方schema/deriveMessages，捕获实际profile会产的完整词表。J2必须交付逐类型 `event-authority-map`：权威来源/对象、logical seq和唯一键、append幂等receipt、model-visible与否、是否持久/能否从冻结来源重建、对应v8合法入口；无合法承载方式的必要事件直接no-go，不能把问题留给实现者随意补第二日志。真正write→dispose→fresh-process open闭环归J4，不能以seed复放当持久化验收。

输出：四项独立判决、LLM/tool分别的动作证据、挂载/事件/恢复设计、未支持范围。只有全部受支持实际effect路径满足才登记 `sync_before_io`；tools成功不代表LLM成功。switch能力另测，不能由sync推导supported。探针例外只限验证最小真实IO，不在未准入前开展完整真实执行suite。

拟入口：`uv run python v8/compat/test_host_probe.py`；拟产物 `docs/investigations/v8-dsh-preflight-2026-09-17.md`、版本化探针报告。无法用公共seam保持v8合同则停止并提交范围/规范决策，不擅改loop。

### J3 — Compat 数据库生命周期套件（可与J1/J2调查并行）

1. 以 `dsh-compat` 身份调用共享命令，补report catalog中的stale/fence、scan、证据分类、cancel/compact、parallel ordinal、generation、授权/插件直表拒绝、workspace和reducer子例。
2. 将“机制已实现”和“compat fixture已执行”分开；逐项更新implemented与gap，缺哪条测哪条，不复制native报告。
3. 必需hook缺席/超时/错误fail-closed和advisory降级若尚无runtime测试，登记明确去向J7，不以RLS测试替代。
4. 使用独立 `agent_v8_compat_lifecycle`，累计加载**当前完整20 SQL**，不是复用G13截断在18的旧库；测试全部实际入口，明确跨stage集成回归。

拟入口：`uv run python v8/compat/test_lifecycle.py`。实现与文档单独里程碑。

### J4 — PG SessionPersistence 与 storage provider

1. 实现当前service五方法和handle全部操作，write ownership绑定受控身份/fence，read不夺owner；跨handle可见性、flush提交、close幂等、失主/旧owner拒绝符合DSH和v8两边约束。write handle不是新的永久session claim；明确claim随seal释放后handle如何保持非调度访问权，不能混用两种lease。
2. 冻结事件映射全集：区分已挂profile会产的事件、未挂插件事件、未知事件。system/message/request header等影响model的内容必须可从PG受控数据恢复；DSH `ignorable`不豁免v8未知类型audit/fixture失败规则。
3. 按J2已审的event-authority-map实施DSH header/序号映射/可重建log视图，逐对象写唯一键、租户FK、写入口、保留期限。元数据不得保存独立可变effect状态或第二份权威completion结果；可重建的重复内容必须受冻结source引用/字节一致性约束且无独立写入口。必要的model-visible内容若v8无合法来源承载，停止并提出合同接合决议；不能把任意DSH原日志换名metadata持久化。新承载对象作为**独立适配元数据迁移**审查，不向公开append白名单随意加semantic类型。
4. assistant final/tool result/turn end只经completion/repair/内部关闭生成；DSH append重放需复用对应命令receipt，不能另写等价结果。实时stream和嵌入final stream去重、partial/final一致性都须有唯一转换规则。
5. 跑上游pin对应 `packages/session/session-persistence/tests/contract.ts`、`packages/storage/storage/tests/contract.ts` 中适用的provider合同；格式/物理存储专属条款逐项映射，不能跳过结果后宣称全suite通过。storage仅承载非session数据，不另造任务队列/事件真相。
6. 在Loader真实profile执行write→dispose→新进程open→deriveMessages闭环，验证连续逻辑seq与v8来源映射、完整事件重建、没有JSONL/SQLite session回退。任何共享SQL缺陷单独立修复gate，不在适配层绕过。

拟入口：`uv run python v8/compat/test_pg_providers.py`；产物 `host/src/persistence/`、`host/src/storage/`、映射表/权威性审查、必要版本化迁移及contract测试报告。

### J5 — Ledger execution bridge

1. 串起 create/claim→初始decision seal→冻结payload读取→dispatch→事务外LLM→complete→tools seal→按ordinal执行→下一decision/finish。DSH仍执行官方loop，桥接层不变成第二个Python/native调度器。
2. 绑定DSH turn/step/callId与v8 step/effect/attempt；逻辑身份在执行前确定，重复同名同参tool slot仍独立；普通命令ID、对象ID、driver身份及审计域不混用。
3. 实际LLM/tool executor不接受loop随意改的参数，必须核冻结payload与当前授权；host的显示数据不作许可。无receipt的新动作不得从缓存执行。
4. retry只经v8合法分配，禁止DSH provider透明重试绕ledger；所有真实副调用有明确effect归属或禁用。Host local abort不等于provider确认取消，证据不确定必须unknown。
5. 输入/观测公开append、结果ledger facade、resume closer共享repair、quiescing结果reconcile唯一分流；所有路径写受控审计，credential不进入事件/jobs/logs。
6. capability逐个声明：sync与switch独立。声明supported必须证明host排空、旧owner停止与epoch切换，而非仅SQL支持；unsupported须保留强制负向，不自动变为supported。
7. 落实J2固定恢复流程并实测真实进程kill/resume、unknown无证据拒绝继续、合法repair后恢复、有效job lease不接管、旧writer拒绝、retry复用同payload及attempt计数。重跑J2-A/B于产品桥，排除最小shim与完整profile差异。

拟入口：`uv run python v8/compat/test_ledger_bridge.py`；使用J4 provider及完整v8加载集。

### J6 — 最小双运行时对比

- 同一fixture：user→LLM工具决策→两个同名同参slot→反序工具完成→新decision→最终回答→finish；另一个无tool最小turn。
- Native 与官方DSH loop各自执行，使用同一版本化假provider输入/输出向量与固定clock/seed；不要把已有Python FakeLLM包装当compat loop。实际I/O通过loopback假服务/受控工具进程，API key零依赖。
- 用同一Python normalize实现做最终trace裁决；JS只实现适配所必需的canonical编码/键派生并与独立golden核对，不为对比另写宽松normalizer。
- 输出raw事件、控制态、canonical trace、请求和实际动作计数；只允许v8规范定义的portable投影，不能删system/model/tool/id真实内容掩盖差异。
- 提交前/后kill、响应丢失与重复append最小恢复组合；无同逻辑结果双提交，不宣称外部exactly-once。

拟入口：`uv run python v8/compat/test_trace_pair.py`。此gate通过只证明最小闭环，不等于J7/J8完成。

### J7 — 全支持面故障/并发/能力验收

读取J1/J2锁定的required-support-matrix，按v8 §5.2/§6全部条目列fixture/subcase×driver×DB/真实I/O行，不缺条目；任何mandatory-supported行的failed/partial/未运行令J7失败，profile不挂载不能变更其参加义务。至少覆盖：取消×dispatch两序、撤权×dispatch、unknown/repair/reconcile、有效job lease与强制接管、陈旧fence/epoch、gen revoke及in-flight收束、workspace lost与checkpoint、compact/terminal abort、流式不完整/迟到/冲突、重复结果、真实resume、必需hook超时拒绝、插件越权、凭据载体检查。

每个写事务的kill点由独立连接断言全有或全无。真实I/O层必须通过官方loop及实际HTTP/tool边界；只mock方法计数或直接调SQL不能替代。对stream/live事件需专测进程在final settlement前死亡，不能以final嵌入流回放掩盖丢失的实时观测。

T0–T4按明确插件/fixture支持清单验收，不声称覆盖全部DSH生态；当前profile必要的model-visible日志不得以compat-only规避trace比较。PTC/嵌套/后台agent等未准入能力必须在实际调用入口拒绝并测试。

拟入口：`uv run python v8/compat/test_p0c.py`（聚合伞形）及各独立fixture脚本。输出完整capability报告；合法blocked原样保留，failed/partial/未运行不冒充blocked。本计划期望的完整对比目标与降级合同通过分别给结论。

### V0 — V10 接合裁定与安装准备（与DSH路径并行，但不抢共享文件）

| 项目 | 必须落定的答案与验收 |
|---|---|
| epoch/fence初值 | 预定决议V0-D1：v10初始化采用1，与既有v8保持一致；通过针对性规范勘误审批后才实施，记录新指纹与5-I0/5-I1预期。本计划不直接授权改冻结正文；若审批不接受则V0阻塞并重新裁定，实施者不得自己改为0或放松CHECK |
| generation单一指针 | 预定决议V0-D2：v10只认按W的context_generation_pointer；旧catalog_config仅服务隔离的旧v8路径，不双写、不为v10fallback。实施前冻结旧/新调用者域、bootstrap迁移、激活/下线/新装配读路径与权限；必须查明v8 prepare/claim等入口仍读全局指针的位置，抽出受控共用核或提供已授权绑定参数，不能host传generation绕门。共享不可变implementation，不共享active指针；同一工作不能同时受两套active选择管理。该决议与接口映射须审查批准后V1才开始 |
| manifest原子扩展 | v8 G19a五源hash/独立manifest入口不是完整v10 FrozenInputs。明确旧manifest到plan/trace三层的扩展和唯一写入口，捕获/装配/step/slot/attempt/receipt同事务，无先commit manifest再seal |
| 初始化对象/权限 | v10 session扩展、O命令、context_resources和query registry属于P0开发项；先列函数签名/权限/receipt/失败映射，不要求在v8先重做。管理许可与grant不互代 |
| DB版本/命名扫描 | 对v1–v9加载SQL、注册对象、v8/v9规划对象与拟v10物理对象全量扫描schema、表/视图、函数签名、类型、索引/约束、列；输出文件hash/版本/冲突/等价命名及审查结果。动态SQL不能解析的对象标未解析并阻止无条件通过；不在生产库混装各代或删库试错 |
| F-08入口对账 | 每入口：P/R/O分类、调用方、底层函数、envelope/typed key/权限前置/receipt/控制写/失败/重放/crash、目标gate；明确v8复用、v10待实现、需共享修复三种归属 |
| 两保留项 | D4-nit-1在P0 fixture1 golden前澄清互异稳定逻辑键+重复键负向；D1-P2-2继续P2 schema/7-P2前决定，不为了开工强制提前POML实现 |

产物建议：`docs/reviews/v10-entry-readiness-2026-09-17.md`、`docs/reviews/v10-f08-entry-map-2026-09-17.md`、`v10/evidence/name-collision-scan.json`及扫描脚本。未完成的v10功能列未来验收，不作接入失败；已发现的合同矛盾必须先解决。

### V1 — 固定payload来源门与全加载集接合验证

依赖J2-B、J5及V0批准的接合设计。**字节边界沿用v10 §1.2**：canonical_request_bytes是最终provider请求body，不是HTTP报文全集。在最终HTTP发送/loopback接收端捕获body，与ProviderRequest.wire解码后的原字节比较，并核size/hash与完整descriptor既有request_hash关联；方法、endpoint/provider/model及参数目标另作受保护route/policy绑定检查，不擅自改变规范request_hash公式。Authorization等凭据头、允许变化的transport headers不入prompt字节比较，显式列allowlist且不得携带未授权模型参数；SSE响应帧不是请求body。任何影响语义的query/header必须属于已授权policy，不得以transport排除逃逸。

使用测试专用固定ProviderRequest/Bytes，不调用未来v10装配器，验证两个runtime都读取同一受保护payload，真正发送的body逐字节相同、metadata关联正确、host追加prompt/改tools/marker/params均拒且零IO；§1.2 $ref/$defs、普通$键/tagged整数、Unicode/二进制边界分层向量可先做fixture，不把它们当生产Serialize已实现。

这是“transport可以承载v10冻结产物”的前置验证，不是v10完整assembly conformance。真实SQL原子装配和生产serializer在P0实现后必须重新跑同套验收，不能以此替代。

用完整v8加载集验证initialization初值、generation门/指针迁移方案可行性、manifest扩展事务接口和INFRA成功effect保留的接合点。特别说明v8现有`v_infra_closure_effect`会将触发effect置failed_terminal，不能直接拿它实现v10成功completion遇持久sidecar损坏时的“effect仍succeeded、step/session INFRA”；V0接口图须指定保留effect事实的受控聚合/drain路径，真正实现与e1/e4留P0。

拟入口：`uv run python v10/preflight/test_entry_bridge.py`；必要的演示对象仅隔离preflight库，不开放正式v10生产入口。

### J8 — 联合准出与后续 P0 任务书

重新锁定双方commit/lock/profile/adapter/canonicalizer/schema版本；原基线commit不是必须停留的终态。对本计划gate跑完整回归、对未修改DSH源确认pin；归档命名扫描/F-08/偏差/支持清单/实跑日志摘要。

联合证据索引必须逐项包含文件路径、SHA256、产生gate、实际命令/退出码和状态：E01双方source/tool/lock/profile版本；E02累计测试及J0无凭据修复；E03锁定的支持矩阵；E04 J2四探针及J5产品桥复验；E05事件权威映射与PG provider合同/重启；E06双loop原始与canonical trace；E07完整P0C故障/能力报告；E08 V0-D1/D2批准记录及规范指纹；E09全量命名扫描；E10 F-08逐入口表；E11 V1最终body来源门/全加载集接合报告。任一缺失/过期/不适用未解释时不自动GO。给两个独立结论：

1. V8 对比：最小双loop同trace、必跑支持面无failed/partial/未运行，capability blocked符合矩阵；若只达到降级T0则明确目标A未达成，不称P0C完整。
2. V10 接入：§7.1全部必需证据就绪，V0所有接入矛盾关闭，V1来源门可行性通过，支持面有明确结论。若依赖降级影响双运行时承诺，提交用户裁定而非自动GO。

J8通过后生成/冻结v10 P0详细实施计划：数据/权限/O receipt → generation与初始化 → artifacts/query来源 →纯计算核 →原子seal →Feedback统计 →双runtime回归。emergent生产归P0、消费归P1；persona真实发布、spill/ForkPrefix归P1；POML归P2；P3只汇总，不首次补安全。三项性能spike按v10 §7.5时点进入计划，不要求在本联合计划先完成全部产品性能验收。

## 5. 关键实现规则与停止条件

- **唯一权威**：v8 session_events/控制态决定执行结果；DSH重建元数据可持久，但必须有受控唯一写者和与ledger同事务/幂等关联，不另建可独立推进的事件日志。
- **恢复证据**：DSH合成error/aborted、HTTP连接断开、进程退出都不是外部副作用未发生证明；unknown只经v8合法repair/reconcile收束。
- **payload**：v10内容冻结与当前授权独立；在dispatch时重验而不重装；真正body核验在最末发送边界，不靠上游GenerateOptions冻结证明。
- **无隐式范围膨胀**：图片/嵌套工具/PTC/子agent/自动retry等若profile引入，则追加effect归属与验收再开放；否则executor阻断。不因只测顶层tool而声称全部sync。
- **能力声明独立**：sync_before_io不蕴含driver switch supported；不通过构造immutable记录翻转能力，升级需新adapter identity/profile。
- **非绿色停止**：J2必要接合no-go停止对应生产适配；任一gate红不得提交该里程碑为完成；规范矛盾/新增状态边/对旧gate预期的实质改变先单独裁定。
- **无上游侵入默认**：DSH源只读pin，扩展默认在pg-agent；确需上游改动另立变更、遵守其AGENTS、固定新commit后重跑探针，不把本地脏源码当pinned。

## 6. 文件所有权、验证、提交

- J0负责现有compat测试/报告器与事实更新；J1负责pin/bootstrap/profile；J2负责probe和接口设计；J3负责DB lifecycle；J4负责PG providers/元数据迁移；J5负责execution/mapping/recovery；J6/J7负责差分与故障harness；V0负责v10接入工件，V1负责preflight，J8负责联合报告/下一计划。
- `v8/load.py`、schema/共享SQL、compat manifest、README/覆盖矩阵/偏差台账是共享文件，**串行集成**；探索/独立fixture设计可并行，不让多个agent同时改complete_effect、generation、loader。V0扫描可以并行，若双方实现改变被扫描文件，J8必须重新扫描。
- 新stage有独立setup_db和明确加载上界；增加迁移时更新SQL_LOAD_ORDER及全部STAGE_THROUGH，不复制陈旧序号。20是本调查时的加载长度，后续按真实清单而不是硬编码保真。
- 外部IO仅事务外；测试FakeLLM/FakeTool/loopback mock、临时DSH_HOME、禁止真实provider。安装/构建检查按DSH源码规定运行相关检查，不默认全仓test:coverage。
- 每个gate：实际跑本stage全部测试+直接受影响回归；阶段终签跑完整累计gate。更新stage README、loader（如涉及）、Conformance矩阵、偏差台账和版本证据。不可用测试数量不下降代替合同覆盖。
- 按AGENTS：测试全绿→收尾工件→逐路径git add→commit→push origin main，禁add -A/`.`、禁force/跳hook，疑似凭据不提交。每个gate独立提交，不积压。上游独立checkout不推送用户DSH master。
- **当前交付只是本计划草案**：没有运行J0–J8/V0/V1，没有修改代码、v8/v10冻结正文、用户已有P0C草案或DSH源；不触发“已完成实现里程碑”的提交声明。
