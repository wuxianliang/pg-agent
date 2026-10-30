# v13 DP10 —— 多语言原生工具（Swift + Python read_file）计划

> 状态：草稿 v2（2026-09-23；已回填 Phase 6 设计评审 `docs/reviews/v13-dp10-plan-critique-2026-09-23.md` 的 7 P0/12 P1/17 P2）。编号**暂定 dp10**（dp9 计划已提交 `af8e23d`；dp10 全库无冲突）。
> 设计输入（冻结禁改）：`docs/investigations/v13-multilang-tool-call-test-2026-09-23.md`（F1–F22 + 实机矩阵 + 双路 Oracle 终裁）。
> 评审输入：`docs/reviews/v13-dp10-plan-critique-2026-09-23.md`（载重 spot-check 全部实跑；v2 已吸收其全部 P0/P1 与可取 P2）。
> 基座：v13 DP1–DP8 已交付（14 个 SQL stage，`v13/load.py:16-32` 现仍 14 项）；**DP9 实现在途未提交**（工作区 `M v13/load.py` 增 `mgraph:15`、未跟踪 `v13/mgraph/`）——DP10 不碰不回退这些在途改动；`v13/demo/` gitignored（`.gitignore:32`），本 plan 不依赖它。
> 撰写注记：context_builder 通道当日三连 MCPToolExecutionCancelledError，按仓库先例降级为主会话直撰；偏差记录于附录A D6。
> 用户裁决输入（2026-09-23）：选型 read_file 已确认；工具必须 **pg-agent 原生**（Swift 实现 + Python 重写版，双双被 agent 调用且效果一致）。Phase 5 四项终裁：自有 Swift 脚本且**不做 RP-CE oracle**；行 JSON 线协议；M1/M2 两笔；默认 gate 含 Swift。
> 惯例参照：`v13-dp1-two-phase-advance-plan`（§0/§1/§4/§5 骨架权威）、`v13-dp8-periphery-p1`（§1.3 裁决格式）、`v13-dp9-memory-graph`（§0 按里程碑执行索引）；仓库约定 `AGENTS.md`。

## §0 执行索引

| 里程碑 | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| **M1 契约与双实现** | read_file 契约的 Swift + Python 双实现离线锁定等价（无 DB） | `uv run python v13/multilang/test_multilang.py --contract` exit 0（A/B 两组全绿；swift 工具链缺失 → exit 2 not_run） | `v13/multilang/{__init__.py, read_file_port.py, read_file_swift.swift, swift_tool.py, fixtures/{hello.txt,crlf.txt}, .gitattributes 追加一行, test_multilang.py(--contract 段)}` | swift 工具链（Xcode CLT）；无 PG、无 repoprompt-ce | ~450 行（swift ~170 + py 口岸 ~130 + 桥 ~70 + 测试矩阵 ~120） |
| **M2 v13 集成与收尾** | 双原生工具经 v13 agent 环调用并证明效果相同；stage 收尾合规 | `uv run python v13/multilang/test_multilang.py`（全量）exit 0；14 个既有 stage gate 复跑达 E4 基线；按 AGENTS.md 提交推送 | `v13/multilang/{setup_db.py, test_multilang.py(全量段), README.md}`、根 `THIRD_PARTY_NOTICES.md` | M1；pgembed PG（root `server.py`） | ~550 行（setup ~70 + mini-hub/mock ~280 + 断言 ~150 + README ~90） |

提交切分：M1、M2 各一笔（`v13: add multilang read_file contract ports (swift + python)` / `v13: add multilang native tools gate on v13 agent loop (dp10)`）。禁止合并为一笔（AGENTS.md 里程碑纪律）；也禁止把口岸矩阵与 Swift 直测拆开提交（无 Swift 对照的矩阵只是在复述自己的假设）。

## §1 定位与边界

### 1.1 版图位置

- DP1–DP8 交付了 v13 两相环、工具目录、effect 账本与上下文平面；**多语言 worker 侧至今零交付**：tutorial `docs/tutorials/v13/chapters/08-multi-language-harness.md` §8.4 G6 是愿景断言集（claim 侧过滤/lease 接管等多数未实现），§8.5 练习 3（「加第三种 handler：只 INSERT 目录行 + 起进程，零 SQL 文件改动」）从未被 plan 化。**DP10 = 练习 3 的正式交付**：首个 tracked 零 SQL 文件 stage。
- DP10 不动 SQL 层、不动 DP1–DP8 任何 gate 断言；只新增 `v13/multilang/` stage 目录 + 根 `THIRD_PARTY_NOTICES.md` + `.gitattributes` 一行（fixture 字节保真）。
- 与 DP9（计划已提交、实现 in-flight：工作区 `M v13/load.py` 的 `mgraph:15` 与未跟踪 `v13/mgraph/`）**代码零交集但共享工作区**：E2 自查按「无可归因于本 stage 的改动」判定，**禁止 `git checkout`/`git restore` 任何既有文件**（会静默回滚 DP9 在途工作）。
- 与 v13.1 workbench plane 计划无交集（那边才考虑 `handler='duck'` 新 worker 族）。

### 1.2 上游契约消费清单（逐条可回查；行号经评审实测校准）

| # | 契约 | 出处 |
|---|---|---|
| U1 | tools 目录 DDL+guard+revision bump | `v13/schema/v13_core.sql:579-590, 620-698` |
| U2 | 判断面 `tool` choice（criteria=启用 sql/tool 目录名∪none）+ `param::`/`stated::` 信号；**criteria 必须是 object**（`v13_decisions_choice_shape`） | `v13/resolve/v13_resolve.sql:97-119`；envelope 覆写版 `v13/envelope/v13_envelope.sql:330-460`；CHECK `v13_core.sql:417-419` |
| U3 | P4c tool 入队冻结 `{tool,params,handler,tools_revision}` + `waiting` | `v13/loop/advance.sql:110-163, 488-513` |
| U4 | worker 合同 `v13_claim`/`v13_complete`（fence CAS；**全局 oldest-first、跨 session、无 handlers[] 过滤**）；hub 轮询 effects 表、**忽略 pgmq**（`v13_send_work` 仅唤醒，可丢）；超级用户连接故免 pgmq 授权 | `v13_core.sql:267-372`；`advance.sql:186-190`；调查报告 F19 |
| U5 | 预算步先于建账；cycle=本 turn `turn/route` 计数；种子 `max_cycles=3`；**budget_exhausted → enqueue human → 若 ready 则 send_work+waiting；human 已 succeeded 才落 `turn/end delivered=false`+`failed`+terminal** | `advance.sql:330-355`；`v13_core.sql:161-166, 753` |
| U6 | 策略 append-only（唯一许可 UPDATE=翻 active；部分唯一索引强制「先翻后插」）；`turn_budget` 是**库级 active 行**（非 session 作用域） | `v13_core.sql:701-740` |
| U7 | turn_budget 不在七键探针；**route_policy_version 在七键探针**（session 换策略版本后旧 snap 必 stale）；tools DML 则 bump revision 打 stale | `advance.sql:24-25, 243-253`；`v13_core.sql:681-698` |
| U8 | GUC：envelope stage 要求 `typesafe.provider`+`typesafe.model`（缺 → V3002）；**会话级** `set_config(...,false)`（事务级在 hub 一 RPC 一提交下首次 commit 即弹栈消失）；`mock_response` 每 parse **事务级** `...,true`。注意：`v13/envelope/test_envelope.py:128-131` 的 `guc()` 用事务级——**不要照抄**用于 provider/model；`test_loop.py` 只载 3 文件故从未设 provider | `v13_envelope.sql:321-331`；`v13/loop/test_loop.py:67-68, 155`；`v13/envelope/test_envelope.py:130-131, 686-688` |
| U9 | 快路上限 ≤1×32 问；双工具+param 目录下 needed=13；**现成 mock 助手 `mock_from_needed(cur,sid,**over)`（按当批信号自动生成合法答案，支持覆盖）与 `claim_pinned`**（先 cancel 他行再领）；`test_loop.py:948` 有 main guard，可 `from v13.loop.test_loop import ...` | `v13_core.sql:752`；`v13/loop/test_loop.py:78-87, 111-130, 948` |
| U10 | 外部 IO 不进事务；FS 禁入变更相 → read_file 必须 `kind='tool'` | AGENTS.md 不变量4；`docs/designs/v13-errata-2026-09-21.md` 5.2 |
| U11 | read_file 契约（切片+围栏语义；逐子锚点经评审核验） | `repoprompt-ce/Sources/RepoPromptDomainRuntime/MCPDomainCanonicalWorkspaceService.swift:171-193`（UTF-8 `:178`、切行 `:179`、负尾 `:183-184`、1-based `:186`、越界 `:187`、join `:192`）；`Sources/RepoPromptMCP/DirectHeadlessDomainContext.swift:302-333`（空白拒 `:306`、绝对直用 `:310`、歧义 `:319`、standardize+symlink `:323-326`、围栏 `:328`） |
| U12 | 跨语言恒等断言范式 | `v12/queue/test_queue.py:150-151`（SQL uuid_v5 == Python uuid5） |
| U13 | 子进程+exit code 分类先例 | `v7/tests/test_phase1_runtime.py:1015-1027` |
| U14 | not_run 诚实跳过先例（exit 2 绝不伪装 pass） | `v8/compat/test_compat.py:1133-1170` |
| U15 | stage setup/导入形态；零 SQL 声明先例 | `v13/loop/setup_db.py:16-23`；`v13/loop/test_loop.py:18-23`（`sys.path.insert(0, AGENT_ROOT)`）；`v13/demo/setup_db.py:11-12` |
| U16 | **参数路由需要带行**：`v13_resolve_tool_params` 以 `v13_env_hit('stated::'||tool||'::'||key,'pass')` 为前提；`v_routes` 对 thresholds 是 INNER JOIN（无带行=不命中=参数不进 request=口岸收不到 path）；带行只能加在 **draft** 路由策略版本（`v13_thresholds_insert_guard`）；sessions 只能引用 **frozen** 版本；freeze=draft→frozen 唯一许可 UPDATE；种子顺序=建版本→插带→冻结 | `advance.sql:59-66, 169-182`；`v13_core.sql:449-473, 526-556, 564-577`；种子带 `v13_core.sql:963-984` |
| U17 | Swift 脚本模式实测（评审复核）：trap（越界/force-unwrap）→ 退出码 **-5/133（SIGTRAP）非 1**；`print()` 有缓冲，先 print 后 trap 会**丢帧**；`FileHandle.standardOutput.write` 无缓冲；`subprocess.run(timeout)` 干净回收进程树；脚本模式不在 CWD 留产物 | 评审 A12/C 节实机记录 |

### 1.3 Open Questions 裁决（本节为最终权威）

**裁决1（Swift 实现形态）：pg-agent 自有单文件 Swift 脚本；RP-CE 关系止于「契约出处 + 归属注记」，不做 oracle。**
依据：用户 2026-09-23 澄清 + Phase 5 终裁。Swift 脚本模式实测可用（`swift file.swift` 顶层代码直跑，无 SPM/无 .build 残留；冷启动 0.2–2.2s 视模块缓存（首跑建底最慢），热 ~0.19s）。两实现的忠实性由 A/B 组矩阵（swift↔python 双向对照）+ 文件头归属注记（U11 file:line）+ 附录C 证据链背书。**契约不对称显式声明**：线协议单 `root` 字段——Swift 侧是单 root 子集；多 root/歧义分支只存在于 Python 口岸单测（A13），两实现 API 面的不对等是设计决定而非疏漏。

**裁决2（Swift 工具线协议）：极简行 JSON，每调用 spawn；无缓冲写帧 + 完整退出码映射。**
契约（两端共有，写入 README 与两文件头）：
- 请求：stdin 单行紧凑 JSON `{"root":"<绝对路径>","path":"<相对或绝对>","start_line":<int|null>,"limit":<int|null>}`；
- 成功：stdout 单行 JSON `{"ok":true,"result":"<文本>"}`，exit 0；文件正文含换行由 JSON 字符串转义保证帧仍单行；
- 工具错误：`{"ok":false,"error":"<taxonomy>","message":"<任意>"}`，exit 3；**空/全空白 stdin 帧 = `invalid_params`/exit 3**（两端一致，不留分歧空间）；
- 协议/内部错误：exit 1（含：坏 JSON、自身异常）；**桥侧规则：退出码 ∉{0,3} 或读不到帧（EOF）一律归协议错误**——Swift 运行时 trap 实测退出码为 -5/133（U17），必须被兜住；
- Swift 脚本**必须**整体 `do/catch` 包裹 + 用 `FileHandle.standardOutput.write`（无缓冲）发帧（`print()` 有缓冲，先发帧后 trap 会丢帧，U17 实测）；
- 错误分类法（taxonomy）两实现同集：`invalid_params`（缺 path/空白/NUL）、`path_outside_workspace`（围栏）、`read_failed`（IO/非 UTF-8/目录）。
依据：pg-agent 拥有协议两端，MCP 握手是纯开销；每调用 spawn 免握手免生命周期管理（热 0.19s ≪ LEASE_MS）。明确不做 Swift 侧 MCP server 化。

**裁决3（里程碑切分）：M1 契约与双实现（`--contract` gate，无 DB）/ M2 v13 集成与收尾（默认全量 gate）。**
依据：换行类/幻影尾/围栏是全 plan 最易错层，先在无 DB 环境锁死（M1 的 B 组已含 swift==python 等价）；M2 才引入 v13 相位 mock、路由策略 v2 与预算翻新复杂度。两笔提交合 AGENTS.md 里程碑纪律。

**裁决4（预算负例形态与编排）：轻量 A0，且 A0 排在 turn_budget 翻新之前。**
`turn_budget` 是库级 active 行（U6）——「独立短 session」拿不回 max_cycles=3，故 gate 编排必须是：**基线断言（=3）→ A0（种子预算下跑红路）→ 翻新（断言=4）→ 幸福路径**；不做「翻回 v1 再翻回 v2」的往返。
A0 正确序列（对齐 U5 真实语义，修正 v1 草案的错误断言集）：tool→tool→llm 三路由 → advance#4 预算步 enqueue human（reason=`budget_exhausted`）→ 返回 `waiting`（human ready）→ hub **认领并以 succeeded 结算 human** → parse+advance#5 → 预算步复验 human 已 succeeded → `turn/end delivered=false reason=budget_exhausted` + `sessions.status='failed'` + `terminal`。断言含中间态（advance#4 返回 waiting、human effect 的 request.reason）与终态；先例 `v13/loop/test_loop.py:428-437`（M3-7）只断言到 waiting+reason，本 gate 走到终态。
「仅数据断言」异议（调查报告 Oracle2）存档附录A D4；实施噪声大可降级（记偏差台账）。

**裁决5（默认 gate 与 Swift 的关系）：默认 gate 含 Swift 断言；缺工具链 exit 2。**
主命题=「两个原生工具都被 agent 调用」，Swift 侧不可选。swift 工具链缺失 → `[SKIP] not_run/toolchain_absent` → exit 2（U14）；里程碑绿=作者机（macOS，Apple Swift 6.3.2）exit 0 留证。备选「`--with-swift` opt-in」存档附录A D5。

**裁决6（参数路由路线）：走全保真——新建路由策略版本 `('default',2)`，保住「判断面选文件」。**
机制（U16）：INSERT `v13_route_policies('default',2)`（draft）→ **逐行复制** `('default',1)` 全部种子带 → 追加 4 行新带（`param::read_file_py::path`、`stated::read_file_py::path`、`param::read_file_swift::path`、`stated::read_file_swift::path`，均 `[0.60,Infinity)→pass`，镜像种子 `v13_core.sql:972-975` 形状）→ UPDATE state='frozen' → A0 与幸福路径的 session 在**任何 parse 之前**指定 `route_policy_version=2`（七键探针项，U7；sessions 引用 frozen 版本的 guard 在 `v13_core.sql:547-556`）。全部是数据 DML，零 SQL 文件。
被否备选：把 `path` 从 param_spec 拿掉（信号 13→11、口岸读固定 fixture）——机器更少但**静默削弱示例**（丢了「判断面选文件」这层），存档附录A D8。

**裁决7（两个既有红 gate 的处置）：E4 回归基线=12 必绿 + 2 个已知根因豁免。**
今日实跑（评审）：14 个 stage gate 中 12 绿；`v13/envelope`、`v13/twophase` 红，根因同一：两者的源码扫描断言（`test_envelope.py:2133-2135` 拒 `mock_response`；`test_twophase.py:143-147` 拒 `mock_response`+`set_config`）扫 `v13/**/*.sql` 时**把 gitignored 的 `v13/demo/sql/demo_api.sql`（`:122,135` 有 `PERFORM set_config('typesafe.mock_response',...)`）也扫进去**。fresh clone 上无 demo 树则两 gate 绿——这是既有缺陷（对 gitignored 目录做断言），非 DP10 造成。处置：E4 要求 14 gate 复跑，12 个必绿；envelope/twophase **要么绿、要么红且失败输出恰为上述已知扫描断言**（gate 内核对失败 check 标签匹配该模式）；任何其他失败 → 停。README 偏差台账留痕 + 建议上游修复（扫描范围收窄到 `git ls-files`）作为 dp10 外的独立小修（需用户另行授权，本 plan 不做）。绝不把红说成绿。

### 1.4 本 plan 对后续发布的契约

- stage `v13/multilang/` 存在；gate 命令两形态：`--contract`（M1）/ 默认全量（M2）。
- handler 约定：`worker:read_file_py` / `worker:read_file_swift`；目录名 `read_file_py`/`read_file_swift`。
- 行 JSON 线协议 + 三值 taxonomy（裁决2）为共同契约，后续加语言（ch08 练习 3 的 node 例）沿用。
- fixtures `hello.txt`/`crlf.txt` 为契约工件（`.gitattributes` 保 CRLF 字节）；`nonutf8` 与 symlink root 由 gate 在临时目录生成（不提交任何二进制）。
- 根 `THIRD_PARTY_NOTICES.md`：Apache-2.0 §4(a)-(b) 合规——覆盖文件清单（`read_file_port.py`/`read_file_swift.swift`）、上游项目名/仓库 URL/本地 checkout 版本（1.4.1）、显式 "ported & modified" 声明与出处 file:line、许可证全文副本；放仓库根（全仓单一入口，镜像 RP-CE 自身惯例）。

### 1.5 不变量（违反即设计背离）

1. **继承 DP1–DP7 全部不变量**（本 plan 零 SQL 文件改动即零触碰）。
2. **零 SQL 文件改动**：`SQL_LOAD_ORDER` 零追加、`v13/**/*.sql` 零 diff。运行时 SQL 允许清单（ exhaustive）：tools INSERT×2/DELETE×2；路由策略 v2 的 INSERT（版本行+14 复制带+4 新带）与 freeze UPDATE；`turn_budget` 翻新（UPDATE active=false + INSERT v2）；session 行的 `route_policy_version` 指定；GUC `set_config`；`v13_*` RPC 调用；effects/decisions/sessions 的常规读写。`setup_db.py` docstring 显式声明（首个 tracked 零 SQL stage）。
3. **单 hub、严格顺序、完全排空**：唯一 Python mini-hub 调 `v13_claim`（U4 全局 oldest-first 跨 session——A0 与幸福路径**严格先后**且各自把 effect 清到终态，杜绝跨 session 错领；若出现他 session 未排空行，用 `claim_pinned` 习语先 cancel 再领）。Swift 脚本不接触 DB。hub 单线程，一次一个 effect。
4. **外部 IO 时序**：spawn swift/读 stdout 只发生在 claim 事务已提交之后、complete 事务开启之前（hub 一 RPC 一事务）。
5. **目录/策略变更后新 session**：tools INSERT 后、路由策略 freeze 后，新 session 且首次 parse 前设 `route_policy_version=2`；不复用旧 snap。
6. **fixture 纪律**：主 fixture 纯 LF ASCII（期望值=文件正文）；CRLF 期望值=逐字符切分后重连结果（`alpha\r\nbeta\r\n` → **`alpha\n\nbeta\n\n`**，5 元素双幻影尾）；空文件/非 UTF-8 只做等价或分类断言；错误只比分类不比文案。幻影尾规则：LF 尾 → N+1 段；CRLF 尾每行多一个空段（2 行 CRLF 文件 → 5 段）。
7. **tools 文案全 ASCII**：description/question/stated/options 键值均 `\x20-\x7E`；**options 必须是 object 且键=选项 choice**（U2 CHECK；数组会在 parse 阶段延迟爆雷）。
8. **gate 诚实性与字节纪律**：缺 swift 工具链 exit 2；不在 gate 内 `swift build`；**不提交任何二进制**（nonutf8/symlink fixture 由 gate 生成；`.gitattributes` 一行保 crlf.txt 字节）；hub 有 tick 硬上限（16，超限响亮失败而非挂住）；PG 连接中断（`psycopg2.OperationalError`）→ 清晰错误信息退出 1，不留半开状态（setup 的 `DROP DATABASE ... WITH (FORCE)` 天然容忍上次残留）。

## §2 输入 § 映射

| 输入 | 落点 |
|---|---|
| 调查报告 F1–F7（机制+预算算术） | §1.2 U1–U7、§4 C 组、裁决4 |
| 调查报告 F8–F10（FakeJudge 不可驾驶/GUC mock/V3002） | §4 C4、§5 R6、U8 |
| 调查报告 F11–F13（RP-CE 实机） | 附录C 证据索引（oracle 已裁不做） |
| 调查报告 F14–F16（契约/围栏/换行口岸） | U11、§4 A/B 组、不变量6 |
| 调查报告 F17–F18（落点/比较面） | §0、§4 D 组 |
| 调查报告 F19–F22（PGMQ/子进程/exit 2/tick 上限） | U4、裁决5、不变量8 |
| 评审 P0-A1..A5/B1-B2/A6-A12（实测） | 裁决4/6/7、§3、§4 全组、U2/U5/U8/U9/U16/U17、不变量3/5/6/7/8、E2/E4 |
| demo 计划+评审 | 停在 envelope 的加载裁决、会话级 GUC 教训 |
| tutorial ch06/ch08 | §6 |
| errata 5.2 | 不变量4 |
| DP8/DP9/DP2 家法 | 骨架、§4 表形态、§7.10 措辞（DP2 挂起先例） |

## §3 表/函数 DDL 与 SQL 草案

**无新 SQL 文件。** 运行时 SQL 全集（供评审核对；顺序敏感）：
```sql
-- ① 目录（options 必须是 object、键=选项 choice=相对路径——U2 CHECK）
INSERT INTO tools (name, description, kind, handler, param_spec, enabled) VALUES
 ('read_file_py',    'read a file (python native port)', 'tool', 'worker:read_file_py',
  '{"path": {"question": "which file", "stated": "user named the file",
    "options": {"hello.txt": "the fixture file to read"}}}'::jsonb, true),
 ('read_file_swift', 'read a file (swift native port)',  'tool', 'worker:read_file_swift',
  '{"path": {"question": "which file", "stated": "user named the file",
    "options": {"hello.txt": "the fixture file to read"}}}'::jsonb, true);
-- ② 路由策略 v2（裁决6；draft→复制→加带→freeze，镜像种子顺序 v13_core.sql:959-984）
INSERT INTO v13_route_policies (policy_name, policy_version) VALUES ('default', 2);
INSERT INTO thresholds (policy_name, policy_version, signal, band_no, lo, hi, action)
  SELECT 'default', 2, signal, band_no, lo, hi, action FROM thresholds
   WHERE policy_name='default' AND policy_version=1;      -- 逐行复制全部种子带
INSERT INTO thresholds (policy_name, policy_version, signal, band_no, lo, hi, action) VALUES
 ('default',2,'param::read_file_py::path',          1,0.60,'Infinity','pass'),
 ('default',2,'stated::read_file_py::path',         1,0.60,'Infinity','pass'),
 ('default',2,'param::read_file_swift::path',       1,0.60,'Infinity','pass'),
 ('default',2,'stated::read_file_swift::path',      1,0.60,'Infinity','pass');
UPDATE v13_route_policies SET state='frozen'
 WHERE policy_name='default' AND policy_version=2;
-- ③ A0 之后、幸福路径之前：预算翻新（顺序由部分唯一索引强制）
UPDATE v13_policies SET active = false WHERE name='turn_budget' AND version=1;
INSERT INTO v13_policies (name, version, value, active) VALUES
 ('turn_budget', 2, '{"max_cycles": 4}'::jsonb, true);
-- ④ session 指定（任何 parse 之前；七键探针项）：INSERT/UPDATE sessions 的
--    route_policy_name='default', route_policy_version=2（guard 要求 frozen）
-- ⑤ GUC：SET typesafe.provider='fake' / typesafe.model='fake-judge'（会话级）；
--    每 parse 前事务级 set_config('typesafe.mock_response', <批答案>, true)
-- ⑥ 用毕恢复：DELETE 两行 tools；断言 count(*)==INSERT 前捕获值（种子=2）、
--    revision 再 bump。策略 v2/v1 与 turn_budget v2 留库（库随 setup 重建）。
```

## §4 里程碑与 gate

断言纪律：`check(label, cond, detail)` 风格（`v13/loop/test_loop.py:25` 附近）；gate=独立脚本 exit 0=通过；每条断言可独立判红绿。

### M1：契约与双实现（gate：`uv run python v13/multilang/test_multilang.py --contract`）

文件：`v13/multilang/{__init__.py, read_file_port.py, read_file_swift.swift, swift_tool.py, fixtures/hello.txt（4 行 LF ASCII 带尾换行）, fixtures/crlf.txt（字节 `alpha\r\nbeta\r\n`）, test_multilang.py(--contract 段)}`；`.gitattributes` 追加 `v13/multilang/fixtures/crlf.txt -text`；`nonutf8.bin`（`FF FE 78`）与 symlink root fixture 由 gate 在 tmpdir 生成。两实现文件头带归属注记（U11 出处 + Apache-2.0 + 见根 THIRD_PARTY_NOTICES.md）。

**A 组 · Python 口岸矩阵（无 DB、无子进程）**

| # | 断言 | 对应 |
|---|---|---|
| A1 | 全文读=文件正文（LF fixture） | U11 缺省分支 |
| A2 | `start_line=2,limit=2` → 第 2–3 行 | 1-based |
| A3 | `start_line=0` ≡ `1` | `max(0,start-1)` |
| A4 | `start_line=-1` → `""`（LF 尾幻影段）；`-2` → 末 2 行且 limit 被忽略 | 负尾 |
| A5 | `start_line=99` → `""` 非 error | 越界 guard |
| A6 | `limit=0` → `""`；空文件 → `""` | `max(0,limit)` |
| A7 | CRLF fixture 全文 → **`alpha\n\nbeta\n\n`**（5 元素、双幻影尾） | 不变量6 |
| A8 | 缺 path/空白 → `invalid_params`；`../../etc/hosts` → `path_outside_workspace`；nonutf8 → `read_failed` | taxonomy |
| A9 | 绝对路径（root 内）直用；多 root 歧义分支符合 U11（tmpdir 双 root 单测） | resolvePath |
| A10 | root 先 `realpath` 再围栏（tmpdir symlink root fixture：root 为符号链接、目标内文件可读、逃逸仍拒） | symlink 围栏 |

**B 组 · Swift 直测（spawn `swift`，行 JSON）**

| # | 断言 | 对应 |
|---|---|---|
| B0 | `swift --version` 失败 → `[SKIP] not_run/toolchain_absent` → exit 2 | 裁决5 |
| B1 | hello.txt 全文：swift == python 口岸 == 文件正文 | 裁决1 |
| B2 | 切片三点：`(2,2)` / `(-1)`→`""` / `(99)`→`""` 与口岸同值 | A2/A4/A5 |
| B3 | CRLF 与口岸同值（`alpha\n\nbeta\n\n`） | A7 |
| B4 | 错误三态 taxonomy 与口岸一致，失败不交正文；**空 stdin 帧 → `invalid_params`/exit 3** | 裁决2 |
| B5 | exit code 语义：ok:true→0、工具错误→3；**喂垃圾字节/立刻关 stdin → 桥归协议错误（不挂住）** | 裁决2、U17 |
| B6 | 单次调用 wall time < 10s（性能护栏；实测 0.19–2.2s） | U17 |

### M2：v13 集成与收尾（gate：`uv run python v13/multilang/test_multilang.py`）

新增文件：`setup_db.py`（库 `agent_v13_multilang`；照 `v13/loop/setup_db.py:16-23`：`get_server()`→DROP/CREATE（WITH FORCE）→`load_stage(server, db, "envelope")`→`run_probes`；docstring 零 SQL 声明）、`test_multilang.py` 全量段（C/D/E 组）、`README.md`、根 `THIRD_PARTY_NOTICES.md`。

**C 组 · v13 双工具环**（hub 习语：`from v13.loop.test_loop import mock_from_needed`（U9，main guard 保证可导入）+ 相位覆盖；hub 严格顺序、tick 上限 16、每 advance 带 `SET LOCAL lock_timeout='250ms', statement_timeout='5s'`）

| # | 断言 | 对应 |
|---|---|---|
| C1 | GUC 双断言：(i) 正例——会话级 provider/model 就位后主路径跑通；(ii) 负例——provider 置空复现 V3002（`test_envelope.py:686-688` 形态） | U8 |
| C2 | 基线数据断言：active `turn_budget`=`{"max_cycles":3}` | U6 |
| C3 | 路由策略 v2 建成（§3 ②）：复制带行数=种子带行数、4 新带在列、state=frozen、session 指定 v2 成功 | 裁决6、U16 |
| C4 | INSERT 两行 tools → revision 上升；此后不再改 tools | U1 |
| C5 | **A0 预算负例**（裁决4 序列；session=v2 策略、种子预算、双 handler 均 Python 口岸）：advance#4 → `waiting` + human effect（`kind='human'`，`request.reason='budget_exhausted'`，ready）；hub 结算 human succeeded；parse+advance#5 → `terminal`；事件含 `turn/end delivered=false reason=budget_exhausted`；`sessions.status='failed'`；无 tool 类未决 | U5、裁决4 |
| C6 | 预算翻新（§3 ③）→ `v13_policy('turn_budget')->>'max_cycles'='4'` | U6 |
| C7 | 幸福路径（fresh session、策略 v2、预算 4、user message）恰 4 条 `turn/route`：actions=[tool,tool,llm,finish]、tools=[read_file_py, read_file_swift]；每 parse 后 `remaining=0` | U3/U5 |
| C8 | 每工具 cycle：advance→`waiting`→claim→按 `request.handler` 分派（py=口岸直调；swift=`swift_tool` 桥，事务外）→complete succeeded→`tool/result` 落账；**request.params 含 `{"path":"hello.txt"}`**（参数路由经 stated 带命中——C3 的存在意义） | U3/U4/U16 |
| C9 | llm 相位：确定性非空文本（FakeLLM 纪律）→ `llm/message` 锚定 → 第 4 次 advance P0 finish | `advance.sql` P0 |

**相位 mock 覆盖表**（`mock_from_needed` 默认值之上必须显式覆盖的载重值；对照种子带 `v13_core.sql:963-981` 与 M3-11 配方 `test_loop.py:382-397`）：`intent` choice=`tool_action` conf 0.9（pass 带 0.75）；`gate_action` **noul=0.9**（pass 带 0.75；`mock_from_needed` 的 noul 默认 0.1 会 FAIL——必须覆盖）；`gate_off_topic` noul=0.1（reject 带 0.75 之下，默认即对）；`risk` score=0（reject 带 2.25 之下）；`tool` choice 按相位（0→`read_file_py`、1→`read_file_swift`、≥2→`none`+intent=`llm_generate`）conf 0.9；`stated::read_file_*::path` noul=0.9（带 0.60）；`param::read_file_*::path` choice=`hello.txt`（**选项键**）。种子邮件 tone/audience 由 `mock_from_needed` 默认合法覆盖。

**D 组 · 等价与构造性差异**

| # | 断言 | 对应 |
|---|---|---|
| D1 | 两条 `tool/result` 的 `payload->'result'` 三方恒等：swift == python == 本地期望切片（JSON 语义比较） | 裁决1、U12 |
| D2 | 两个 tool effect 均 `succeeded`；`request.handler` 各归各；`request.params` 相同（`{"path":"hello.txt"}`） | U4 |
| D3 | 两 effect `tools_revision` 相同、`origin_user_seq` 相同 | U3 |
| D4 | 构造性差异簿记：`effect_id`/`request_hash`/`idempotency_key` 互异不可比；**effect_id 由 SQL 单源生成、与实现语言无关** | U4、§6 |
| D5 | 无未决 effect；`tool` 信号在 decisions ≥3 个不同 `request_hash` | U2/U7 |
| D6 | `judgment_calls` **== 4**（每 parse 一批，恰好） | U8 |

**E 组 · 收尾与回归**

| # | 断言 | 对应 |
|---|---|---|
| E1 | 目录恢复：DELETE 两行 → `count(*)==`INSERT 前捕获值（种子=2）→ revision 再 bump | W6 习语（`v13/demo/test_demo_loop.py:377-383`，demo 为本地副本仅引形态） |
| E2 | 工作区自查：**本 stage 无可归因改动**——对 `v13/load.py` 做前后快照 diff，唯一允许差异=既有 DP9 在途 `mgraph` 行；`v13/**/*.sql`、`.gitignore` 零 diff；**禁止 checkout/restore 任何既有文件** | 裁决7、§1.1 |
| E3 | README 落盘（内容清单见下） | 家法收尾 |
| E4 | 提交前回归：14 个 stage gate 逐个复跑（schema/resolve/loop/twophase/envelope/manifest/chunks/recall/characterize/filter/memory/economy/summary/periphery，以各 stage README 命令为准）；**12 必绿；envelope/twophase 绿或红且失败恰为已知 demo 扫描根因（核对失败 check 标签）；其他任何失败 → 停** | 裁决7 |
| E5 | 提交：按路径 `git add v13/multilang/__init__.py ... THIRD_PARTY_NOTICES.md .gitattributes`（逐项，禁 `-A`）→ `git status` 复查（不卷 `v13/mgraph/`、`v13/load.py` 等 DP9 在途物；无密钥类文件）→ `git commit -m "v13: add multilang native tools gate on v13 agent loop (dp10)"` → `git push origin main`（不 force） | AGENTS.md |

**README 内容清单**：交付面；前置（macOS+Xcode CLT、swift 工具链探测方式）；两形态 gate 命令与 exit 2 语义；线协议契约全文（裁决2）；换行口岸注记（`re.split` 类、幻影尾、禁 `splitlines`）；**契约锚定=headless 裸字符串、不支持 `offset`、刻意未移植清单（worktree_scope/ReadFileReply DTO/多 root）**；Swift 单 root 子集的显式契约不对称；「与 plan 的实施偏差」台账（初始列：A0 降级选项、E4 豁免记录）；教程映射（练习 3 答案=零 SQL 文件）；未来加 SQL 的语言移植会撞 envelope/twophase 源码扫描的预警。

**逐文件影响与实施顺序**：`read_file_port.py` → `read_file_swift.swift` → `swift_tool.py` → fixtures+`.gitattributes` → `test_multilang.py` A/B 段（M1 绿→提交①）→ `setup_db.py` → `test_multilang.py` C/D/E 段 → `README.md`+`THIRD_PARTY_NOTICES.md` → 14 gate 回归 → 提交②。既有文件仅 `.gitattributes` 追加一行；其余全部新增。

## §5 风险与回退

| # | 风险 | 缓解 | 回退 |
|---|---|---|---|
| R1 | swift 工具链缺失/macOS-only vs 默认 gate | 裁决5：默认含 Swift、缺失 exit 2；README 记前置+作者机留证 | 附录A D5 备选（`--with-swift`） |
| R2 | swift/py 口岸行为分歧 | A/B 组双向锁；实施期可手动对照 repoprompt-ce 本尊作开发参考（不作 gate 断言） | 分歧即红，修实现不修断言 |
| R3 | 判断相位/V3001 整批拒 | 用现成 `mock_from_needed`（信号集由 `v13_needed_judgments` 推导，加参自动跟随）+相位覆盖表；每 parse 断言 remaining=0 | 卡住打印 `typesafe_last_request()` 调试 |
| R4 | 目录/策略 DML 后 stale/错领 | 不变量3/5：fresh session、先指定策略 v2 再 parse、严格排空；`claim_pinned` 兜底 | — |
| R5 | 子进程生命周期 | 每调用 spawn+`subprocess.run(capture_output=True, timeout=30)`（实测干净回收进程树）；stdout 单行；stderr 由 capture 排水；退出码∉{0,3}/无帧=协议错误 | 超时→complete failed（不做晚结算练习） |
| R6 | GUC 陷阱 | 会话级 provider/model（`...,false`）+事务级 mock（`...,true`）固定搭配；C1 负例把陷阱变测试；README 警告勿照抄 `guc()` 的事务级 | — |
| R7 | envelope 加载边界演进 | 只依赖 `load_stage('envelope')` 前缀稳定性；README 记依赖声明 | — |
| R8 | Apache-2.0 归属遗漏 | 文件头注记 + 根 `THIRD_PARTY_NOTICES.md`（§1.4 规格）；E 组自查 | — |
| R9 | 两个既有红 gate 阻断 M2 提交 | 裁决7：E4 基线=12 必绿+已知根因豁免（核对失败模式）；README 留痕；上游修复另行授权 | 若用户不认豁免 → 停下问用户（AGENTS.md 分歧停下） |
| R10 | DP9 在途工作被误伤 | E2 快照 diff 判定+禁 checkout/restore；E5 按路径 add 不卷 `v13/mgraph/`、`v13/load.py` | — |

## §6 教程映射（正文零改动）

- ch08 §8.5 练习 3 实体化：README 记答案——「改了几个 SQL 文件？零」。**预警同录**：后继者若真加 SQL，会撞 envelope/twophase 的源码扫描（U 裁决7 根因）。
- ch08 §8.6 所引 v12 G6 先例在 D1/D4 复用并 v13 化。
- G6 子断言交付面（其余后置 §7）：✅ 双 handler 同队列由同一 harness 分派、各归各（hub 分派层隔离，非 claim 层 `handlers[]` 过滤——教程愿景 vs U4 现实差异记 README）；✅ effect_id 语言无关（D4）；✅ 失败按同一 taxonomy 落账（B4，非逐字节）。
- ch06「目录是表，可见性是查询」：C4 的 runtime INSERT→revision bump→冻结面读取即实践印证。
- 教程正文零改动；回写 ch08 一句「DP10 已交付练习 3」为可选收尾项（用户裁定，不阻塞）。

## §7 明确不做

1. LLM native tool_calls——工具选择属判断平面，另一条变更线。
2. A15 四值 `result_kind` 信封。
3. ch06 目标目录列（`input_schema`/`mutating`/`timeout_ms`/`allowlist`/`consumes`/`produces`）。
4. claim 侧 `handlers[]` 过滤（tutorial §8.2 的 SQL 承诺）——另立工作。
5. lease 接管/慢结算 stale 练习；op_seq 并行纪律；第四务 cancel；worktree binding。
6. 真 DeepSeek judge / demo W7 烟囱（gitignored）。
7. SPM/`swift build`/提交任何二进制；Swift 工具 MCP server 化。
8. RP-CE 二进制 oracle（`--with-rpce`）/`mcp_client.py`——用户 Phase 5 终裁不做。
9. `file_search`/`get_file_tree`/`apply_edits` 移植（调查报告已裁拒绝理由）。
10. v13 conformance matrix/deviation ledger——**沿用 DP1/DP2 的显式挂起**（`docs/plans/v13-dp2-judgment-envelope-plan-2026-09-20.md:1632,1714`：「是否为 v13 建制评审工件属父 loop 统一决策,不在本 DP 单方引入」）；注意 AGENTS.md 仍把两者列为里程碑前置——这一未解张力在 README 偏差台账记录，不在本 plan 内单方消解。
11. 修复 envelope/twophase 扫描 gate 的上游缺陷（裁决7 只豁免不修复；修复需用户另行授权，越出零 SQL 边界）。

## 附录A · 分歧点清单

| # | 分歧 | 裁决 | 备注 |
|---|---|---|---|
| D1 | Swift 形态 | **自有脚本，无 oracle**（用户 Phase 5 确认） | 契约出处靠 U11 引用+归属注记 |
| D2 | 线协议 | **行 JSON**（用户确认）+ 无缓冲写帧/退出码全集（评审 A12 回填） | MCP 化留后续 |
| D3 | 里程碑 | **M1/M2**（用户确认） | M1 已含 swift↔py 等价 |
| D4 | 预算负例 | 轻量 A0+数据断言（A0 前置于翻新——评审 A3 修正） | 噪声大可降级记台账 |
| D5 | 默认 gate 含 Swift | **默认含**（用户确认） | CI 化再议 |
| D6 | 撰写流程偏差（context_builder 三连故障→直撰） | 直撰 | Phase 6 评审已独立把关 |
| D7 | A0 的 human effect 处置 | hub 结算 succeeded 走完终态（评审 A4 修正 v1 的「留账不认领」） | 与 M3-7 先例对齐并走到 terminal |
| D8 | 参数路由：路由策略 v2 全保真（主案）vs 去 path 简化 | v2 全保真 | 简化案静默丢「判断面选文件」 |
| D9 | envelope/twophase 双红处置 | 12 必绿+已知根因豁免（裁决7） | 上游修复另行授权 |
| D10 | fixture 提交策略 | hello/crlf 提交+`.gitattributes`；nonutf8/symlink gate 内生成 | 不变量8 不破 |

## 附录B · 全教训自检（AGENTS.md 合规清单）

- [ ] gate=独立脚本，`uv run python v13/multilang/test_multilang.py`（`--contract`）退出码 0=通过；同里程碑全部 gate 实跑全绿后才提交；不声称未实跑的通过。
- [ ] 提交前 14 gate 复跑达 E4 基线（12 必绿+2 豁免核对）。
- [ ] `git add` 按路径逐项；`git status` 二次复查；不卷 DP9 在途物（`v13/mgraph/`、`v13/load.py`）；无 `--no-verify`；疑似密钥文件打开确认。
- [ ] 提交信息 `v13: <祈使句摘要>`；push 不 force；被拒→fetch+rebase，分歧停下问用户。
- [ ] 外部 IO 不进事务（不变量4）；FakeLLM/mock 纪律（C9）。
- [ ] 新 SQL 追加 `SQL_LOAD_ORDER`：不适用（零 SQL）——docstring 显式声明。
- [ ] conformance matrix/deviation ledger：不适用（DP2 挂起沿用，§7.10 记张力）。
- [ ] v13 收尾=stage README「与 plan 的实施偏差」台账（E3）。
- [ ] 一个里程碑一次提交。

## 附录C · 证据索引

- 调查报告：`docs/investigations/v13-multilang-tool-call-test-2026-09-23.md`（F1–F22 + 实机矩阵 + 双路 Oracle 终裁；RP-CE 探针记录在此，不进本 plan 交付面）。
- 设计评审：`docs/reviews/v13-dp10-plan-critique-2026-09-23.md`（7 P0/12 P1/17 P2，全部载重 spot-check 实跑；本 v2 已吸收）。
- Phase 2 探针（2026-09-23）：家法/收尾工件/ch08 G6 原文；Swift 脚本模式实测；Apache-2.0 归属惯例；`.gitignore`/pyproject 影响。
