# v24 六动词会话控制设计审查（Stage 2）

| 项 | 值 |
|---|---|
| 日期 | 2026-11-05 |
| 范围 | 未实施、未提交的 S0/S1 设计集；只读设计审查，不重复 Stage 1 的逐条代码审计 |
| 输入 | Stage 1 pair 审计、核验修订设计、落地计划、API 合同、原稿 |
| 方法 | 文档间语义闭包、权威链与可实施性判断；未运行 gate/setup_db/数据库/provider/网络，未改代码或 Git 状态 |
| 证据限制 | 代码行为仅引用 Stage 1 与核验版的静态证据，未独立复核；所有并发、恢复和 gate 运行时结果均为**未验证** |

## 1. 结论

**判定：修订后可批准；不需要重做对象模型，但当前文本不能直接批准 S0-M1 开工。**

批准前必须完成两件事：一是拍板本报告 §5 的五项 S0 决策，二是按 §7 最小修改计划与 API 的规范性段落。

不要求在 S0 前完成 S1 的 DDL、迁移执行器或 frozen-baseline bump；相反，S1 必须另走独立治理批准。

核心原因不是 pair 已列的某个底层事实仍有争议，而是修订版尚未闭合三个上层合同：宿主命令恰好一次、跨会话/跨 run 的 cursor、starting 与拒绝结果的可恢复语义。

“不能先改代码再补这些合同”，因为它们决定 `sessions.json` v2 的记录形状、服务线程归属和 API v1 wire shape，事后修改会成为迁移或协议破坏。

pair 的事实修正总体可信，但其“恢复 `.v1.bak`”只解决旧二进制可读性，并不自动构成无损回滚；其共享串行域要求则方向正确，完整实现不必全部前移到 M1。

本报告将问题分为两类：**设计缺陷**是合同本身矛盾、缺字段或缺状态/恢复规则；**计划遗漏**是修订版已有答案、计划却未吸收或仍写旧答案。

## 2. 设计合理性判定

### 2.1 对象模型：成立，边界也基本正确

- session 只承担身份、归属、解析与控制改写，run 继续独占预算、effect、generation、revision 与终态，这不会形成两个执行权威（`docs/designs/v24-session-control-design-verified-2026-11-05.md:418-424`）。
- 不建 `turns`/`session_status` 表合理；但“不建表”不能推导为“不需要宿主持久命令账本”，后者是文件格式与恢复协议问题（`docs/designs/v24-session-control-design-verified-2026-11-05.md:433-452`）。
- `state=starting/active/closed` 作为宿主生命周期可以保留，公开 `status` 从 run 派生也可以保留；两者必须在 starting 已提交但未 bind 时按 run 证据恢复，而不能只信文件状态（`docs/designs/v24-session-control-design-verified-2026-11-05.md:454-480`）。
- S0 以最近 bindings 解析 current run，在“同时至多一个活动 run”不变量成立时自洽；启动发现多活动时必须 fail-closed，不能自动挑选一个继续写（`docs/designs/v24-session-control-design-verified-2026-11-05.md:466-480`）。
- 顶层 run 计数与 spawn 子 run 分离、`session_id` 在 S1 保持 nullable，避免把谱系误当会话成员，方向正确（`docs/designs/v24-session-control-design-verified-2026-11-05.md:320-345`）。
- S0 不改 SQL 仍可作为目标，但仅限单宿主进程；跨进程 JSON 锁、advisory lock 或直接绕过 service 均不在安全承诺内（`docs/designs/v24-session-control-design-verified-2026-11-05.md:610-616`）。

### 2.2 设计缺陷 D1：run request journal 不能单独证明会话命令恰好一次

核验版要求所有写先查 `host_request` 并 replay 原响应，但 Session 记录只有单个 `pending_start`，没有完成后的 start 索引、各写动词的客户端 digest、原始会话 envelope 或本地提交阶段（`docs/designs/v24-session-control-design-verified-2026-11-05.md:435-452`、`:591-600`）。

API 又要求把 `host_request.request_bytes` 与“本次规范字节”比较，而 §7.4 的规范字节是 session 级请求；run 级 RPC bytes 与该 session envelope 不是同一对象（`docs/designs/v24-session-control-api-2026-11-05.md:754-771`、`:773-789`）。

**推断：** DB 已提交、bind/counter/turn 尚未落盘时崩溃，重试即使命中 run receipt，也无法同时保证原 session 响应和宿主副作用恰好一次。

**推断：** start 完成后清掉唯一 `pending_start` 时，不带 session_id 的同 key 重试无法可靠定位旧 session；全局 `(principal, request_key)` 查询与按 session 派生 run key 之间缺一段持久索引。

这是 S0-M1 的记录格式和提交协议缺陷，不是给 M3 增加几条重放测试就能补的计划遗漏。

最低设计答案应包含：持久 start 索引、按 session/op/key 的命令记录、客户端 canonical digest、原 envelope、本地阶段标记，以及 lease 接管后的防旧 owner 写回规则。

run receipt 是恢复证据，不是宿主本地提交的替代；bind、counter、turn 和完成标记必须能以同一 command id 重入。

### 2.3 设计缺陷 D2：幂等键作用域与“零写拒绝”未统一

API 一处把 `(principal_id, request_key)` 说成幂等键，另一处允许不同 session/op 复用 client key，并用 session+op+hash 派生实际 key（`docs/designs/v24-session-control-api-2026-11-05.md:18-24`、`:740-764`）。

计划测试 #29 也明确要求同一 client key 先后用于 start 与终态 steer 时两次都 committed，因此对外合同必须明确作用域，而不能继续写全局唯一（`docs/plans/v24-session-control-plan-2026-11-05.md:380`）。

waiting steer 与错误 interaction 明确声称 run 级零写，终态 cancel/respond 也没有 run 业务提交；若宿主同样不写拒绝 receipt，则“同 key 永远返回原响应”与“之后状态变化重新分派”不能同时成立（`docs/designs/v24-session-control-api-2026-11-05.md:552-562`、`:630-652`、`:701-712`）。

**推断：** starting cancel 在没有 run 可写时连 run journal 都没有，重启后尤其无法 replay 原清理结果（`docs/designs/v24-session-control-api-2026-11-05.md:552-562`）。

应选择“宿主也持久化拒绝 receipt，零写仅指 run/effect/request 不变”，或把 replay 承诺明确限定为 committed/deferred；本审查建议前者，避免同一 key 随状态漂移。

### 2.4 设计缺陷 D3：单 cursor 不能表达多会话 wait

API 的多会话 wait 接收一组 `session_ids`，却仍只有一个含单个 `session_id/run_id/event_seq` 的 cursor；响应也只给 winner 的一个 cursor（`docs/designs/v24-session-control-api-2026-11-05.md:138-161`、`:434-449`、`:483-501`）。

**推断：** 对其他 session 来说，这个 cursor 要么不匹配而被当成无 cursor，要么覆盖不了各自的 run/event/interaction 读位置；重复 winner、跳过事件或饥饿都无法仅靠“第一个 interesting”排除。

计划把多会话 wait 放到 M4，却没有要求修改 wire shape（`docs/plans/v24-session-control-plan-2026-11-05.md:222-245`）。

这是 pair 漏判的 API 设计缺陷；应在 v1 定稿时改成每 session cursor 映射/列表，并定义缺项、未知项和 winner 返回后的保留规则。

### 2.5 设计缺陷 D4：选 `wait_check` 并不会自动闭合 poll/cursor

核验版允许 poll 组合 `wait_check`，也允许 v1 禁增量分页，但尚未择一（`docs/designs/v24-session-control-design-verified-2026-11-05.md:553-561`）。

若走组合路线，还缺四条规则：`include_events=false` 时 event_seq 不得越过最后实际返回的事件；run_id 改变时用新 run 的注册代/epoch 并从 0 重置；stale 后的重置值须符合 Cursor schema；无 cursor“从现在开始”须能取得高水位。

当前建议的 `event_seq=null` 没有进入 API 类型合同，也没有定义下一次 `wait_check` 如何解释（`docs/designs/v24-session-control-design-verified-2026-11-05.md:547-561`）。

**推断：** 若快照 cursor 在未返回 events 时前进，客户端随后请求 events 会永久跳过未读事件；若换 run 仍带旧注册代，则只会反复 stale。

因此 pair ①的“二选一”是必要条件，不是完整设计；本审查建议 S0 禁 poll 增量分页，把 event_seq 的推进限定在 wait 的已返回事件之后。

### 2.6 设计缺陷 D5：wake 在“新 run 已终态”窗口有空洞

核验版的 terminal 要求 current run 与 cursor 同 run，而 run_started 又要求当前存在不同的**活动** run（`docs/designs/v24-session-control-design-verified-2026-11-05.md:563-575`）。

**推断：** cursor 指向 R1 时，R1 终态后经 steer 创建 R2，且 R2 在下一次 wait 前也已终态；current_run 返回 R2，terminal 因 run_id 不同不成立，run_started 因 R2 非活动也不成立，最终只能 timeout。

API 的“current run_id 不同即 run_started”反而没有这个空洞，二者必须统一为后者，并让 terminal 在下一次同 run wait 接管（`docs/designs/v24-session-control-api-2026-11-05.md:469-481`）。

这是竞态语义推导，运行时**未验证**；但合同文本本身已足以判定需要修正。

### 2.7 状态机与错误分类：主干闭合，边界尚未闭合

- completed/failed/cancelled 只能由 steer 开新 run，blocked_unknown 不自动重开，waiting 只能 respond 或 cancel，主干合理（`docs/designs/v24-session-control-design-verified-2026-11-05.md:454-464`、`:504-527`）。
- starting 必须区分 pre-dispatch、DB committed 未 bind、本地完成未持久化；cancel 不能一律“清 scope”，应先查 run receipt，再决定取消 run 或仅清理宿主意图（`docs/designs/v24-session-control-design-verified-2026-11-05.md:493-502`）。
- idle 下 respond 是 `not_waiting` 还是 `already_terminal`、starting cancel 最终是 cancelled 还是 closed，文本未给唯一答案（`docs/designs/v24-session-control-api-2026-11-05.md:552-562`、`:701-712`）。
- start 的永久参数/预算错误不应与可接管 transient failure 一样长期留 starting/deferred；需按阶段定义 rejected 与 deferred（`docs/designs/v24-session-control-api-2026-11-05.md:346-356`）。
- real respond 的 `waiting_unsupported`/`capability_unavailable` 仍二选一，且二者都不在 API 错误总表，不能交给实现者自由挑选（`docs/designs/v24-session-control-design-verified-2026-11-05.md:521-527`；`docs/designs/v24-session-control-api-2026-11-05.md:714-738`）。
- `retry_with_closure` 与 `unauthorized` 已在核验版 delta 要求补入 API，正文却仍缺失；必须明确透传、映射为 `not_found_or_denied`，或定义门面清理语义（`docs/designs/v24-session-control-design-verified-2026-11-05.md:652-659`；`docs/designs/v24-session-control-api-2026-11-05.md:356`）。

### 2.8 parity 标注：核验版可用，API/原稿不能继续充当对等规范

核验版已把 `already_terminal`、`run_started`、respond 不计 user turn、waiting steer 全拒绝分别标为 v24-local 或更严格策略，这足以纠正 parity 主张（`docs/designs/v24-session-control-design-verified-2026-11-05.md:625-640`）。

API 的 wake 映射仍列未经验证的 RepoPrompt `terminal/event/snapshot` 名称，并把 `superseded` 映射到本地 `run_started`，没有标 v24-local（`docs/designs/v24-session-control-api-2026-11-05.md:835-844`）。

原稿仍保留旧 parity 断言，虽顶部有“以核验版为准”，计划却仍把原稿列为配套总体设计，权威链不够清楚（`docs/designs/v24-session-control-plane-2026-11-05.md:56-66`；`docs/plans/v24-session-control-plan-2026-11-05.md:13`）。

结论：parity 不是重做理由；应把核验版+修订后的 API 设为唯一规范，原稿降为历史调查，不再作为实现依据。

## 3. 一致性与残留冲突

下表只列会影响实现或验收的残留，不重列 pair 的 15 条事实核验。

| ID | 残留位置 | 冲突/过时内容 | 分类与处理 |
|---|---|---|---|
| C1 | `docs/plans/v24-session-control-plan-2026-11-05.md:13`、`:385-393` | 配套与文件影响仍指向原稿/API，未把核验版列为权威 | 计划遗漏；改权威链，原稿标历史 |
| C2 | `docs/plans/v24-session-control-plan-2026-11-05.md:81-84` vs `docs/designs/v24-session-control-design-verified-2026-11-05.md:493-502` | M1 仍是先分配 session 后 scope/install，没有先查/写 pending_start、lease 与完成索引 | 计划遗漏；改 M1 顺序与字段 |
| C3 | `docs/designs/v24-session-control-design-verified-2026-11-05.md:402-404` vs `:486`、`:673` | D15 仍写 S0 调 `v24.start(session_id=...)`，后文才明确 S0 不传、S1 宿主必传 | 核验版自身残句；D15 标 S1-only |
| C4 | `docs/plans/v24-session-control-plan-2026-11-05.md:82`、`:389` vs `docs/designs/v24-session-control-design-verified-2026-11-05.md:357-366`、`:602-616` | 计划固定 `v24/ui` 且未指定 driver，修订版要求 transport-neutral 或明确降级 UI-only | 未决架构决策，不是单纯漏字 |
| C5 | `docs/plans/v24-session-control-plan-2026-11-05.md:20-25`、`:491` | DoD 要会话独立控制，风险表却接受单执行器阻塞多会话；执行串行与控制/驱动饿死被混为一谈 | 计划内部矛盾；只接受 provider 执行串行，不接受 roster 不推进 |
| C6 | `docs/designs/v24-session-control-api-2026-11-05.md:163-170`、`:317-327` vs `docs/designs/v24-session-control-design-verified-2026-11-05.md:278-296` | API 正文仍允许 tokens:null、steps/wall=0，model 仍写可选 ModelSpec，未写上限与宿主 toolset 匹配 | API 未同步；按 D4/D5 改正文和示例 |
| C7 | `docs/designs/v24-session-control-api-2026-11-05.md:154-160`、`:473-479` vs `docs/designs/v24-session-control-design-verified-2026-11-05.md:569-575` | API 仍把 revision-only/generation-only 都归为 event/epoch，run_started 条件也与核验版不同 | 两份规范冲突；按 §2.5/§2.6 统一 |
| C8 | `docs/designs/v24-session-control-api-2026-11-05.md:648` vs `docs/designs/v24-session-control-design-verified-2026-11-05.md:88`、`:516` | 终态 steer 新 run 的 driving_generation 一处写从 0，一处写从 1 | API 明确错误；改为 1 并加合同向量 |
| C9 | `docs/designs/v24-session-control-design-verified-2026-11-05.md:593-598` vs `docs/designs/v24-session-control-api-2026-11-05.md:744-764` | 活动 steer 内部 op 分别叫 `steer_active` 与 `steer` | 合同未同步；固定一种，建议 `steer_active` |
| C10 | `docs/designs/v24-session-control-api-2026-11-05.md:654-683` vs `docs/designs/v24-session-control-design-verified-2026-11-05.md:386-394` | respond 请求仍无 expected_generation，却声明可能 stale_generation | API 漏字段；补可选 CAS 与服务填当前值 |
| C11 | `docs/plans/v24-session-control-plan-2026-11-05.md:174-211` vs `docs/designs/v24-session-control-design-verified-2026-11-05.md:310-318`、`:491` | M3 未限定 real respond 能力拒绝，统一成功表述超过 S0 能力 | 计划遗漏；DoD/M3/矩阵同步限定 |
| C12 | `docs/plans/v24-session-control-plan-2026-11-05.md:115`、`:260-264`、`:470-474` vs `docs/designs/v24-session-control-design-verified-2026-11-05.md:347-355`、`:697-708` | “关开关+旧代码读 v1 字段”仍在 M1、M4、回滚章节三处出现 | 计划未吸收且互相矛盾；统一回滚协议 |
| C13 | `docs/plans/v24-session-control-plan-2026-11-05.md:30-33`、`:274-310` vs `docs/designs/v24-session-control-design-verified-2026-11-05.md:663-695` | S1 仍按 scope 回填所有 run、start session_id 可选、允许新增 SQL/load.py，未落实子 run NULL 与宿主必传 | S1 计划旧稿；现在标错，详细实施可延后 |
| C14 | `docs/plans/v24-session-control-plan-2026-11-05.md:14`、`:44`、`:66`、`:331` vs `docs/designs/v24-session-control-design-verified-2026-11-05.md:680-695` | 页首承认 frozen-baseline bump，正文仍多处只写普通规格修订且只点 DP4 | 计划遗漏；统一为独立批准并覆盖 DP4/DP5/DP6 |
| C15 | `docs/plans/v24-session-control-plan-2026-11-05.md:495-505` vs `docs/designs/v24-session-control-api-2026-11-05.md:962-973` | cancel 终态形状、start 默认等待、公开命名已在 API 定稿，计划仍列待拍板 | 计划过期；删除已决项，保留真正未决项 |
| C16 | `docs/plans/v24-session-control-plan-2026-11-05.md:247` vs `prompt-exports/v24-session-control-pair-audit-2026-11-05.md:66` | 计划要求整个 sessions.json 损坏不影响其他会话，Stage 1 指出当前整体 quarantine 不能支持该承诺 | 验收承诺无设计支撑；改全局 fail-closed 或另做记录级隔离设计 |
| C17 | `docs/designs/v24-session-control-api-2026-11-05.md:284-292` vs `docs/designs/v24-session-control-design-verified-2026-11-05.md:581-587` | API 仍把 effect_settlement_no 写成严格结算数，未保留 cancel-late 例外或改名 run_turn_no | API 未同步；S0 标注例外，统一计数规则可延 S1 |
| C18 | `docs/plans/v24-session-control-plan-2026-11-05.md:114`、`:264`、`:404-410` vs `docs/designs/v24-session-control-design-verified-2026-11-05.md:723-729`、`:756-762` | S0 diff 验收只锁 SQL，漏掉 load.py 与 deepseek.py | 计划遗漏；收口 diff 三者都必须为空 |

## 4. pair 建议裁决表

| # | 裁决 | 理由与落地边界 |
|---|---|---|
| ① poll 分页必须走 wait_check 或禁分页 | **接受** | 这是能力边界而非优化项；建议 S0 选择禁 poll 增量分页，若选 wait_check，必须同时补 §2.5 的推进、换 run、stale、高水位规则，不能只改内部调用名（`prompt-exports/v24-session-control-pair-audit-2026-11-05.md:15`）。 |
| ② respond 在 S0 限定 fake/scripted-only | **接受** | 限定的是 S0 可用能力，不是从六动词删除 respond；real 必须固定能力错误并零 run 写，DoD 不得暗示 real 全生命周期成功，也不新增真实 provider gate（`prompt-exports/v24-session-control-pair-audit-2026-11-05.md:21`、`:71`）。 |
| ③ waiting-steer 在 S0 用共享串行域 | **接受** | 已知丢 interaction 窗口与 waiting steer 零写/不静默丢弃的 DoD 直接冲突；可用 per-run 锁或等价单 owner 串行调度，但必须覆盖 steer、driver settle、reconcile、recover，而非只包预检（`prompt-exports/v24-session-control-pair-audit-2026-11-05.md:22`、`:38`）。 |
| ④ 回滚必须恢复 `.v1.bak` | **部分接受** | 保留 format_version=2 时恢复备份是旧代码可读的必要条件，但直接恢复会隔离/丢失升级后新数据；必须先拍板 v2 增量导出/只读保留/双写降级政策，不能把“有备份”等同“可回滚”；若另选 v1 兼容可选字段则不必恢复备份，但那是另一项明确设计决策（`prompt-exports/v24-session-control-pair-audit-2026-11-05.md:28`、`:40`；`docs/designs/v24-session-control-design-verified-2026-11-05.md:347-355`）。 |
| ⑤ S1 独立批准 frozen-baseline bump | **接受** | 这是治理前置，不是 S0 的技术阻塞；S0 不依赖 S1 字段，S1 批准件需一次覆盖哈希、D-UI-6、权限闭集、迁移执行与回滚，不得拆成顺手加列（`prompt-exports/v24-session-control-pair-audit-2026-11-05.md:29`、`:42`）。 |

pair 的过度前置：把共享串行域的全部实现与 recover/reconcile 验收都作为 M1 独立完成项并非必要；M1 必须确定 owner、锁序和禁绕过规则，完整 waiting-race 最迟在开放 SessionService.steer 的 M3 前完成（`prompt-exports/v24-session-control-pair-audit-2026-11-05.md:38`）。

pair 的漏判：多会话 wait 单 cursor、host receipt 与 session envelope 不同构、host-only starting cancel 的 replay、新 run 已终态时 wake 空洞，均不是其 15 条事实修正能覆盖的设计问题。

pair 的回滚建议还存在一个反向风险：只恢复 `.v1.bak` 而不处理 v2 新增会话/turn，会把“兼容回滚”变成未声明的数据回退，必须在计划中显式承认并由人批准。

## 5. S0-M1 开工前必须定稿的五项决策

1. **服务与驱动：** 为保留现有 Python/MCP/CLI 合同，S0 采用 transport-neutral `SessionService`、单 owner store、后台 driver roster 和异步 wait；若产品改选 UI-only，必须同步删除其他传输承诺（`docs/designs/v24-session-control-api-2026-11-05.md:11-14`）。
2. **宿主命令账本：** 批准持久 start 索引与 per-command receipt/digest/original-envelope/phase/lease-fencing 协议，run receipt 只用于恢复，所有宿主副作用按 command id 恰好一次，并明确 receipt 保留期与 replay 范围（`docs/designs/v24-session-control-design-verified-2026-11-05.md:591-600`）。
3. **交互安全：** 批准单进程共享串行域且禁止已知 waiting-steer 丢失窗口，M1 定 owner/锁序，M3 前覆盖全部 settle/recover/reconcile 入口（`docs/designs/v24-session-control-design-verified-2026-11-05.md:298-308`）。
4. **读合同：** 建议批准“S0 poll 不做增量 event 分页、wait 只推进到最后返回事件、换 run/stale 从 0 重建、多会话 wait 使用 per-session cursor 映射、run_started 覆盖新 run 已终态”这一整组规则（`docs/designs/v24-session-control-design-verified-2026-11-05.md:529-577`）。
5. **v2 数据政策：** 批准 legacy counter 的近似口径、回滚时 `.v1.bak` 与 v2 新增数据的保存/导出规则，以及损坏文件是整体 fail-closed 还是记录级隔离，禁止只写“可回滚”（`docs/designs/v24-session-control-design-verified-2026-11-05.md:256-275`、`:697-708`）。

real respond 不再单列为架构悬念：按 pair ②在 S0 固定为 fake/scripted-only，real 能力码由 API owner 在下述未决项中一次性选定。

## 6. 可延后到 S1 的事项

- frozen-baseline bump 的具体批准 diff、三套 FROZEN 哈希、D-UI-6 替换表与权限闭集更新，只需现在在计划中列为独立前置（`docs/designs/v24-session-control-design-verified-2026-11-05.md:680-695`）。
- `runs.session_id` 的最终 DDL、独立读函数名称/签名和 pre-init migration 脚本实现，可延后；nullable、子 run NULL、按 conversation/bindings 迁移这些纠错现在就要写对（`docs/designs/v24-session-control-design-verified-2026-11-05.md:663-689`）。
- 未绑定顶层旧 run 是 synthetic session 还是 NULL+legacy，可在 S1 迁移批准时拍板，但不得退回按 scope 合并（`docs/designs/v24-session-control-design-verified-2026-11-05.md:337-345`）。
- cancel-late 统一计数规则、model/tool ledger 的最终算法可延后；S0 只需保留 late 例外或改名，不得声称四计数已完整（`docs/designs/v24-session-control-design-verified-2026-11-05.md:581-589`）。
- `s14/test_g12.py` 是新建还是并入既有 gate 可在 S1 批准件决定；当前只能称拟新增，不能计为既有通过项（`docs/plans/v24-session-control-plan-2026-11-05.md:444-458`）。
- per-session model/toolset 动态切换、完整 transcript seed、多进程/多主机控制不属于 S0，也不必借 S1 顺带完成（`docs/designs/v24-session-control-design-verified-2026-11-05.md:287-296`、`:618-623`）。

## 7. 计划必须修改的最小集合

### 7.1 §0 DoD、§1 约束、§2 策略

- 在 §0.1 把全生命周期承诺限定为 fake/scripted respond，并加入宿主 counter/turn/original envelope 恰好一次、waiting 无已知丢失窗口、多会话独立推进和 cursor 语义闭包。
- 把“既有/全部 v24 gate 全绿”绑定到 §6 的固定清单；没有 inventory 的泛称不能作为可验收 DoD（`docs/plans/v24-session-control-plan-2026-11-05.md:20-26`、`:420-458`）。
- 在 §0.2/§2 把 S1 统一改成“独立 frozen-baseline bump 批准后启动”，并删除按 scope 迁移与新 SQL/load.py 绕行的暗示。
- §2 的流程图无需重画，只需在 M1 标注 service owner+driver，在 M3 标注共享串行域，在 M4 标注完整宿主恢复与回滚数据政策。

### 7.2 §3 S0-M1

- 先按本报告 §5 第 1 项决定文件落点；若 transport-neutral，更新 M1 文件表和计划 §5 文件影响，不保留 `v24/ui/session_service.py` 的既定实现口径。
- 在 store 字段中补 principal/owner、持久计数、start 完成索引、命令 receipts、pending_start lease/phase/fencing，并规定先查/写意图再 mint session。
- 把 budget 四边界、tokens 省略、model/toolset/workspace 宿主匹配、start replay/conflict、原 envelope 恢复写入 M1 验收。
- 在 M1 明确 poll 是否禁增量分页；不得同时保留两种可选实现让 gate 自行解释。
- 把“迁移前后可回滚”改成本报告 §5 第 5 项批准的具体流程，不再以“不删除旧文件”作为充分条件（`docs/plans/v24-session-control-plan-2026-11-05.md:112-120`）。

### 7.3 §3 S0-M2

- 把“六种 wake”改成七种，并为 revision-only、generation-only、registration_stale、新 run 已终态分别给出唯一 reason/changed/cursor 结果（`docs/plans/v24-session-control-plan-2026-11-05.md:124-166`）。
- 指定 wait 不阻塞 store owner、不持锁/DB 事务睡眠；指定 session/run/advance 锁序以及 driver 让出规则。
- starting cancel 增加“先恢复 run receipt，再取消 run 或清理本地意图”的分支及 host-only replay，不允许直接删 scope。
- 共享串行域在此建立并接入 driver；M3 再增加确定性 waiting-steer barrier 验收即可。

### 7.4 §3 S0-M3

- 固定 `steer_active`/`steer_new_run` 内部 key 名、客户端 key 作用域、respond expected_generation、blocked_unknown 映射和 real 能力错误。
- waiting steer 的预检、run 调用与 driver/reconcile/recover settle 必须进入同一串行域；验收用 barrier 在“预检后、steer 前”插入 interaction，而非只测静态 waiting。
- 幂等验收从“没有第二个 run”扩到每个写动词的同 key 异 payload、跨状态/重启 replay，以及 DB committed 后 bind/counter/turn/receipt 各断点。
- real 分支只验固定 capability 拒绝与零 run 写；成功 respond 分支只用 fake/scripted，不新增 provider 入口。

### 7.5 §3 S0-M4、§4 矩阵、§7 迁移回滚

- 重启用例必须重建 service/store/adapter/journal/driver，而非只重开 AgentRuntime；覆盖 dispatch_started、finished 未 settle、live/expired lease、unknown 不重放和 detached 多 session 推进。
- 多会话 wait 先落实 per-session cursor wire shape，再写 winner/unknown/all_terminal 用例；当前单 cursor 矩阵不能直接实施。
- §7 回滚同时覆盖 sessions 与 turns/transcript 的 `.v1.bak`、v2 增量保存/导出、恢复后不覆盖证据；损坏文件验收按已选 fail-closed 或记录级隔离实现。
- §4 增加四个合同向量：新 run 已终态的 run_started、include_events=false 不推进 event_seq、同 key 拒绝结果跨重启 replay、两个客户端争同一 terminal steer 仅一个宿主完成记录。
- 若最终仍允许 poll 分页，再增加 >64 不跳不重、跨 run 从 0、stale 重置后续读；若按建议禁分页，则删除旧分页期望而非保留空测试。

### 7.6 §5 文件影响、§6 gate、§8/§9 风险与待拍板

- §5 的权威设计改为核验版+实际修订后的 API，原稿标历史；S0 收口 diff 同时锁 `v24/sql`、`v24/load.py`、`v24/host/deepseek.py`。
- §6 固定完整回归 inventory，至少补上当前清单遗漏的 s5、s10–s12 与 Cordis 范围；S1 明列 dp4/dp5/dp6，s14 只作为拟新增（`prompt-exports/v24-session-control-pair-audit-2026-11-05.md:58-66`）。
- §8 把“接受单执行器阻塞多会话”改为“允许 provider 执行串行，但所有活动 session 都被 roster 推进且控制入口不被 wait/owner 阻塞”。
- §9 删除已定稿的 cancel 形状、start 默认等待、公开命名；保留下节真正需要人决定的范围与数据政策。

## 8. 未决问题（需要人拍板）

1. **S0 是否对 MCP/CLI 作出交付承诺？** 建议保留并采用 transport-neutral；若产品 owner 选择 UI-only，需明确这是范围变更并删 API 传输承诺，而不是实现时静默降级（`docs/designs/v24-session-control-design-verified-2026-11-05.md:782-795`）。
2. **回滚是否允许升级后的新会话/turn 不再被旧 UI 使用？** 建议不允许静默丢失：回滚前导出并只读保留 v2 增量，再恢复 `.v1.bak`；若业务接受数据回退，必须写清丢失窗口并由数据 owner 批准。
3. **legacy `user_turn_no` 是近似延续还是 v2-only 归零？** 建议近似延续并显示 legacy 标记，因两者都无法精确重建；这是用户可见兼容性选择，不应由实现者自行决定（`docs/designs/v24-session-control-design-verified-2026-11-05.md:260-275`）。
4. **real respond 的公开能力码选哪一个？** 建议沿用 `waiting_unsupported` 以减少 UI 映射；API owner 若选 `capability_unavailable`，需同时改 UI 映射和总表，不能保留“或”（`docs/designs/v24-session-control-design-verified-2026-11-05.md:310-318`）。
5. **API v1 是否在本版本承诺多会话 wait？** 建议保留并增加 per-session cursor 映射；若 API owner 决定后置，必须显式修改计划 M4/DoD，不能交付当前语义不完整的单 cursor 版本（`docs/designs/v24-session-control-api-2026-11-05.md:434-501`）。
6. **何时授权准备 S1 baseline-bump 批准件？** 建议 S0 观察期再评审实际 diff；现在只批准“S1 必须独立审批”这一治理原则，不等于批准改冻结 SQL（`docs/designs/v24-session-control-design-verified-2026-11-05.md:691-695`）。

以上未决项均有推荐默认值和明确后果；除这六项外，不应再用“待定”掩盖可直接按本报告修正的文档冲突。
