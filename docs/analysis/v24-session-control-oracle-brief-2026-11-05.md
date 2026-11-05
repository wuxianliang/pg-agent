# Oracle 上下文包：pg-agent v24 六动词会话控制（S0 五项决策）

> 用途：在 S0-M1 开工前，请 Oracle 对评审报告 §5 的五项决策逐项裁决并给出理由。
> 本文是事实、选项与冲突的压缩，不预设立场；所有引用均可回查仓库文档。

## 1. 这个项目是什么

**pg-agent** 是一个单仓库、按版本迭代的 agent runtime 工程（`v1` … `v24`，另有 `v99` 草稿）。早期版本分别验证过 DuckDB 侧运行时、原生生命周期、provider 适配等；**v24 是当前主线**。

v24 的形态是 **PostgreSQL-native agent kernel**：

- **冻结 SQL 内核**（`v24/sql/**`）：10 张表，`v24.runs` 是唯一执行主体；`start/poll/wait_check/cancel/steer/respond` 六个动词目前都是 **run 级**（以 `run_id` 寻址）。
- **Python host**（`v24/host/`）：`AgentRuntime`、`HostWorker`、journal、adapter；provider 原文只进 host journal，DB 只存语义投影与提交顺序。
- **Chainlit UI**（`v24/ui/`）：当前唯一前端；`conversation` 只是 `sessions.json` 里的 bindings，不是稳定控制面。
- **工具/技能插件**：read/write/exec、skills、spawn 子 run 等。

正在设计的工作：把六动词从 run 级升级为 **session 级**（类似 RepoPrompt 的 `agent_run`），让客户端只持 `session_id` 就能完成 `start → poll/wait → steer → respond → cancel` 全生命周期。

两条路线：

- **S0 Host façade**：session 元数据留在宿主 `sessions.json` v2，`session_id → scope` 一对一，`SessionService` 在宿主实现，**不改冻结 SQL**。
- **S1 Kernel anchor**：`runs` 增加不可变 `session_id` + 每 session 至多一个未终态 run 的部分唯一索引；需要 **frozen-baseline bump**（dp4/dp5/dp6 的 12 文件哈希 + D-UI-6 六路径审计），另走独立治理批准。

工程约束（来自 `AGENTS.md` 与既有 gate 纪律）：

- 外部 IO 一律不进 DB 事务；provider 原文不进 DB。
- 测试是独立脚本（`uv run python ...`，退出码 0 = 通过），不是 pytest。
- S0 gate 全部使用 Fake/Scripted adapter，不打开真实 provider 网络。
- 不静默截断、不静默丢弃；失败要可恢复、可诊断。
- 每里程碑测试全绿后按路径提交，不 `git add -A`，不提交私有数据。
- S0 承诺只覆盖**单宿主进程**；跨进程 JSON 锁、advisory lock、多主机不在承诺内。

## 2. 文档与权威链

| 文档 | 角色 |
|---|---|
| `docs/investigations/v24-pi-repoprompt-session-turn-run-mapping-2026-11-05.md` | 调查：RepoPrompt / pi 的 session-turn-run 映射 |
| `docs/designs/v24-session-control-plane-2026-11-05.md` | 原稿；事实断言已被修正，降为历史参考 |
| `docs/designs/v24-session-control-api-2026-11-05.md` | API v1 合同；字段表可用，但多处语义待修订 |
| `docs/designs/v24-session-control-design-verified-2026-11-05.md` | **核验修订版**；当前权威设计 |
| `docs/plans/v24-session-control-plan-2026-11-05.md` | S0-M1..M4 / S1-M5 落地计划；部分内容未吸收修订版 |
| `docs/reviews/v24-session-control-design-review-2026-11-05.md` | Stage 2 评审；§5 即本次五项决策，§7 是最小修改集 |

**当前状态：全部未实施、未提交。** `v24/ui/sessions.py` 仍是 `VERSION = 1`；`v24/ui/session_service.py` 不存在；`v24/session/` 不存在。

## 3. 裁决必须尊重的硬事实（F1–F10）

**F1 单执行器线程。** `v24/ui/app.py:122-125` 明确：每个方法、构造和 close 都在同一个 executor 线程执行；一个 provider 调用最长 120 秒，会排队该前端的所有 session 命令（`v24/ui/README.md` 的 real 入口说明）。

**F2 驱动归属。** `app.tick` 是当前唯一推进 run 的循环；如果 `SessionService` 被 CLI/MCP 调用而没有 driver，run 不会推进。`wait` 也不能在 owner 线程上同步睡眠。

**F3 v1 store 的硬回滚边界。** `v24/ui/sessions.py:77` 对 `format_version != 1` 直接 quarantine。因此“关闭开关，让旧代码读 v1 字段”**不成立**；v2 回滚只能恢复 `.v1.bak`，而恢复备份会丢掉升级后新增的 session/turn。

**F4 run 级账本不是 session 账本。** `v24.requests` 的主键是 `(principal_id, request_key)`；`host_request` 返回 `request_bytes_base64`、`request_digest_hex`、`response`、`kind`。但它是 **run 级 RPC** 的账本；session 级 envelope（含 `session_id`、`cursor`、`snapshot`）与它不是同一对象，不能直接比较字节。

**F5 读面没有 event cursor。** `v24.poll` 恒返回该 run **最早** 64 条事件，不接受 `after_event_seq`；`v24.wait_check` 支持 `after_event_seq`，但只比较 `epoch`、不比较 `revision`；`v24.events.seq` 是 **per-entity** 序号，换 run 会从 1 重新开始。

**F6 waiting steer 的竞态。** 内核 `v24.steer` 在 `waiting` 上会清空 `interaction`；会话层“先 poll 再拒绝”不是原子的。`pending_steer` 是单槽。

**F7 计数只能持久化。** `ui.seq` 是进程全局、与 request key 共用、重启归零，且 `respond` 也写 turn；`turns.jsonl` 每会话只留 200 条且无 turn 类型；`bindings` 也只留 200 条；`host_runs` 的 `run_projection` 不含 `parent_run_id`。因此 `user_turn_no` / `run_no` 不能从现有文件派生，只能持久计数并接受 legacy 近似。

**F8 S1 不是“改一列加一索引”。** `v24/sql` 的 12 个文件哈希被 dp4/dp5/dp6 三套 gate 同时锁定；`v24/load.py` 与 `v24/s1..s12` 被 byte-lock；`v24/ui/env.py` 在 schema 漂移时直接 `schema_drift`；没有可用的 DB migration executor；`v24/s14/test_g12.py` 不存在。

**F9 没有 v24 MCP server。** 当前只有 Chainlit UI 与 `v24.ui.real` 的 CLI smoke；API 文档里的 “Python / MCP / 可选 HTTP” 中，MCP 与 HTTP 是**未来承诺**，不是已实现传输。

**F10 单进程边界。** S0 只承诺单宿主进程；`sessions.json` 的跨进程丢更新、advisory lock、多客户端并发都不在安全承诺内。

## 4. 五项决策（评审 §5 原文 + 问题空间）

### 决策 1：服务与驱动

**评审原文：** “为保留现有 Python/MCP/CLI 合同，S0 采用 transport-neutral `SessionService`、单 owner store、后台 driver roster 和异步 wait；若产品改选 UI-only，必须同步删除其他传输承诺。”

**问题：** 计划 M1 的文件表固定写 `v24/ui/session_service.py`，并改 `app.py`；API 又声称 Python/MCP/CLI 共用。但 F1/F2/F9 表明：UI 是单 executor 线程、没有 MCP server、CLI 只是 smoke。把 service 放在 `v24/ui` 却声称 transport-neutral，会在实现时退化成“UI 专用、且 wait 阻塞 hub”。

**选项：**

- **A. transport-neutral**：`v24/session/service.py`（或 `v24/host/session_service.py`），注入 `AgentRuntime` 接口；`SessionStore` 由 service 自己的线程拥有；service 跑单一 driver（或复用 `AgentRuntime.tick` 的 roster）；UI/CLI/MCP 都是 adapter；`wait` 异步/可中断。成本：M1 文件表要改，driver 归属与线程模型要一次定清。
- **B. UI-only**：保留 `v24/ui/session_service.py`；S0 只承诺 UI，删除 API 的 MCP/CLI/HTTP 承诺，并把 M4 的 “UI migration” 之外的多前端项删掉。成本：以后做 MCP 要迁移 service；API v1 若已对外则构成协议范围变更。
- **C. 折中**：接口定义放 neutral 模块，实现先放 UI 并依赖 hub。评审已明确反对：文档会声称 neutral，实际却受 hub 线程约束。

**评审倾向：** A（若近期要 MCP/CLI）；否则 B 并显式降级。
**关键张力：** 决定 1 直接决定 2/3 的代码落点、store 线程归属和 driver 由谁运行。

### 决策 2：宿主命令账本

**评审原文：** “批准持久 start 索引与 per-command receipt/digest/original-envelope/phase/lease-fencing 协议，run receipt 只用于恢复，所有宿主副作用按 command id 恰好一次，并明确 receipt 保留期与 replay 范围。”

**问题：** 当前 Session 记录只有单个 `pending_start`：

- `start` 成功后清掉唯一 `pending_start`，不带 `session_id` 的同 key 重试无法定位旧 session；全局 `(principal, request_key)` 查询与按 session 派生 run key 之间缺持久索引。
- DB 已提交、bind/counter/turn 尚未落盘时崩溃，重试即使命中 run receipt，也无法同时保证原 session 响应和宿主副作用恰好一次。
- API 要求比较 `host_request.request_bytes` 与“本次规范字节”，但 §7.4 的规范字节是 session 级请求，run 级 RPC bytes 与它不是同一对象（F4）。
- waiting steer、错误 interaction、终态 cancel/respond 声称“run 级零写”；若宿主也不写拒绝 receipt，则“同 key 永远返回原响应”与“之后状态变化重新分派”不能同时成立。starting cancel 在没有 run 可写时连 run journal 都没有，重启后无法 replay 清理结果。

**选项：**

- **A. 全账本**：持久 start 索引 + per-command receipt `{command_id, session_id, op, client_key_hash, canonical_digest, original_envelope, phase, lease/fencing}`；bind、counter、turn、完成标记都能以同一 command id 重入；run receipt 只作恢复证据；明确 receipt 保留期、replay 范围（committed/deferred/拒绝）与旧 owner 被 lease 接管后的写回禁止规则。
- **B. 最小账本**：保留 `pending_start` + 派生 run key；只承诺 committed 结果 replay，拒绝结果不 replay，并在 API 明确“同 key 可能随状态重新分派”；接受 start 完成后的定位缺口。成本：文档承诺缩水，但 M1 轻。
- **C. 把账本放进 DB**（S1 新表/新 SQL）：违反 S0 冻结内核，当前不可选。

**评审倾向：** A。
**关键张力：** 账本记录什么，取决于决策 4 的 cursor 形状（原响应必须含 cursor）和决策 3 的锁内副作用边界。

### 决策 3：交互安全

**评审原文：** “批准单进程共享串行域且禁止已知 waiting-steer 丢失窗口，M1 定 owner/锁序，M3 前覆盖全部 settle/recover/reconcile 入口。”

**问题：** `waiting` 下 `steer` 必须零写拒绝，但内核 `v24.steer` 会清 interaction（F6）；仅“先读后写”有竞态。`wait` 不能持锁/事务睡眠；driver 的 settle、reconcile、recover 也必须进入同一串行域。另一方面，计划风险表接受“单执行器阻塞多会话”，而 DoD 要求“不同会话可独立控制”——二者直接冲突（评审 C5）。

**选项：**

- **A. 单进程共享串行域（按 run 粒度）**：M1 定 owner 与锁序（session → run → advance）；`steer` 与 driver 的 settle 共用 per-run 锁；`wait` 不持锁睡眠；后台 driver roster 保证一个 session 的 provider 调用不冻结其他 session 的控制入口；M3 前把 settle/reconcile/recover 全部纳入，并用 barrier 在“预检后、steer 前”插入 interaction 做确定性验收。
- **B. 仅 per-run 锁包 `steer` + 一次 settle**：实现小，但 reconcile/recover 仍可绕过，waiting race 只修一半；评审认为不充分。
- **C. 接受已知丢失窗口**：在 API/UI 标注“waiting steer 可能丢 interaction”。与“不静默丢弃”的 DoD 冲突，且用户可见。

**评审倾向：** A，但分批：M1 定 owner/锁序，M3 完成 barrier 验收；不要求把全部 recover/reconcile 实现前移到 M1。
**关键张力：** “共享串行域”不能退化成“一把全局锁串行所有 session 的 provider 调用”，否则违反 DoD 的会话独立推进。

### 决策 4：读合同

**评审原文：** “建议批准‘S0 poll 不做增量 event 分页、wait 只推进到最后返回事件、换 run/stale 从 0 重建、多会话 wait 使用 per-session cursor 映射、run_started 覆盖新 run 已终态’这一整组规则。”

**问题：**

- `v24.poll` 没有 `after_event_seq`（F5）；若 cursor 在未返回 events 时前进，客户端会永久跳过未读事件。
- 多会话 `wait` 接收一组 `session_ids`，却只有一个含单 `session_id/run_id/event_seq` 的 cursor；对其他 session 要么不匹配、要么覆盖不了各自的读位置。
- `run_started` 若要求“当前存在不同的**活动** run”，则 cursor 指向 R1、R1 终态后 steer 出 R2、R2 在下一次 wait 前也已终态时，terminal 与 run_started 都不成立，只能 timeout。
- `include_events=false` 时 event_seq 不得越过最后实际返回的事件；换 run 要用新 run 的注册代/epoch 并从 0 重置；stale 后的重置值须符合 Cursor schema；无 cursor“从现在开始”须能取得高水位。

**选项：**

- **A. S0 禁 poll 增量分页**：`poll` 只返回快照 + 最早 64 条 events（文档明确“最早”，不写“最近窗口”）；`wait` 只把 `event_seq` 推进到最后实际返回的事件；多会话 wait 用 **per-session cursor 映射/列表**；`run_started` 以“当前 run_id 与 cursor.run_id 不同”为准，覆盖“新 run 已终态”；换 run/stale 从 0 重建；terminal 在下一次同 run wait 接管。成本：v1 不做分页，客户端拿不到第 65 条以后的历史事件。
- **B. poll 走 wait_check 增量**：保留分页，但必须同时定义四条规则（不返回 events 不推进、换 run 重置、stale 重置、无 cursor 高水位），并把 `event_seq=null` 纳入 API 类型合同。成本高、边界多。
- **C. 多会话 wait 后置**：v1 只承诺单 session wait，显式改计划 M4、DoD 和 API；否则就是交付语义不完整的单 cursor。

**评审倾向：** A。
**关键张力：** 选 A 会缩小 v1 的读能力；选 B 会把 M1/M2 的 cursor 复杂度显著抬高；选 C 是范围变更，必须产品 owner 签字。

### 决策 5：v2 数据政策

**评审原文：** “批准 legacy counter 的近似口径、回滚时 `.v1.bak` 与 v2 新增数据的保存/导出规则，以及损坏文件是整体 fail-closed 还是记录级隔离，禁止只写‘可回滚’。”

**问题：**

- legacy `user_turn_no` 无法精确：旧 `seq` 有空洞、`respond` 也写 turn、`turns.jsonl` 每会话 200 条且无类型；`run_no` 同样受 bindings 200 条上限影响（F7）。
- v1 `SessionStore.load()` 对 v2 直接 quarantine（F3）；回滚必须恢复 `.v1.bak`，但这会把升级后新增的 session/turn 隔离/丢失。
- 损坏 `sessions.json` 当前是整体 quarantine；计划却承诺“整个文件损坏不影响其他会话”，Stage 1 指出记录级隔离没有设计支撑。

**选项：**

- **A. v2 + 保守回滚**：迁移时写 `.v1.bak`（0600）；回滚前先导出/只读保留 v2 增量（新 session/turn/transcript），再恢复 `.v1.bak`；legacy 计数用 `len(turns)` / `len(bindings)` 并显式标注近似与 200 上限；损坏文件整体 fail-closed，文档撤回“单会话损坏不影响其他会话”的承诺；回滚写成可执行步骤而不是“关开关”。
- **B. 继续写 `format_version=1` + 可选字段**：旧代码忽略新字段，不需要恢复备份；但削弱显式版本语义，旧代码可能重写文件丢掉新字段；需要团队明确拍板。
- **C. 记录级隔离 + 精确 legacy 计数**：需要新的文件格式/分片/索引设计，超出 S0；精确计数在旧数据上也不可能。

**评审倾向：** A；若业务接受“回滚丢失升级后数据”，必须由数据 owner 书面批准丢失窗口，不能由实现者默认。
**关键张力：** 决策 5 决定决策 2 的 receipt/原 envelope 能否在回滚后重放，也决定决策 4 的 cursor/counter 在 v2 文件中的持久形状。

## 5. 交叉约束（裁决时请一并考虑）

1. **决策 1 是前置**：它决定 2/3 的代码落点、store 线程归属、driver 由谁运行；不先定，M1 的文件表和线程模型会改两遍。
2. **决策 2 与 3 共用边界**：command id 必须覆盖锁内的 bind/counter/turn/settle；账本阶段标记必须能表达“已持锁、未提交”。
3. **决策 2 与 4 共用 envelope**：原响应必须包含 cursor；cursor 形状不定，receipt 的 canonical digest 就没有稳定对象。
4. **决策 4 与 5 共用持久化**：per-session cursor、run_no、user_turn_no 都要写进 v2 文件；回滚政策决定这些字段能否保留。
5. **计划与评审还有一处未收口**：S0 收口 diff 评审要求锁 `v24/sql` + `v24/load.py` + `v24/host/deepseek.py`，计划只锁 SQL（评审 C18）。这不是五项之一，但会影响 M1 验收。

## 6. 请 Oracle 按以下格式输出

对五项中的每一项：

1. **裁决**：批准 / 修改后批准 / 否决；并写明选 A/B/C 中哪个方案（或给出更好的第四方案）。不要用“视情况而定”作为结论；可以给条件，但必须给默认值。
2. **理由**：3–6 条，尽量绑定 F1–F10 或文档事实；说明为什么不选其他选项。
3. **落地边界**：M1/M2/M3 必须写进设计、计划、API 的具体条款；需要的 gate/验收；明确不做什么。
4. **残余风险**：这项裁决留下的风险，以及需要谁（产品/数据/API owner）额外批准。

最后再给：

- 五项之间的顺序/依赖；是否有哪项必须先定。
- 是否有哪项其实已经不是决策（文档已定稿）、或应拆成两项。
- 与评审 §8 六项未决的冲突：哪些可以并入这五项，哪些必须单独拍板。
- **一句话总裁决**：S0-M1 现在能否开工；若不能，缺哪几项签字。
