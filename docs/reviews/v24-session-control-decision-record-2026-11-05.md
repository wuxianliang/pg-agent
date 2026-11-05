# v24 会话控制五项决策记录（2026-11-05）

> 本记录是 S0-M1 的开工依据。它把 2026-11-05 评审 §5 的五项决策、两条 Oracle lane 的
> 裁决与协调者的合并结论固定为规范性文本。设计、API、计划中与本记录冲突的段落以本记录为准。

| 项 | 值 |
|---|---|
| 日期 | 2026-11-05 |
| 状态 | **已采纳（Adopted）**；S0 按本记录实施 |
| 输入 | `docs/reviews/v24-session-control-design-review-2026-11-05.md` §5/§8；`docs/analysis/v24-session-control-oracle-brief-2026-11-05.md`；两条 Oracle lane（claude-opus-5-5、gpt-6.1-sol-xhigh）的独立裁决 |
| 输出 | 五项裁决 + 未决项默认值 + 可实施边界 |
| 采纳方式 | 用户于 2026-11-05 明确指示「按照决策继续推进」；本记录据此视为产品/API/数据/runtime 四类 owner 的统一实施授权。实施中若发现边界冲突，修订本记录，不得回到评审前的二选一 |
| 相关文件 | 设计：`v24-session-control-design-verified-2026-11-05.md`；API：`v24-session-control-api-2026-11-05.md`；计划：`docs/plans/v24-session-control-plan-2026-11-05.md` |

## 0. 总裁决

**S0-M1 现在可以开工**，不需要等待 S1、MCP 或 HTTP 设计批准；但必须遵守以下三条不可协商的边界：

1. **S0 不改冻结内核**：`v24/sql/**`、`v24/load.py`、`v24/host/deepseek.py` 在 S0 收口时 diff 必须为空。S1 的 `runs.session_id` 与部分唯一索引另走 frozen-baseline bump。
2. **S0 的交付面是 Python 进程内 API + Chainlit UI**；MCP/HTTP 标为 reserved，现有 `v24.ui.real` CLI smoke 保持可运行，但不构成通用 CLI 合同。
3. **执行串行、控制不阻塞**：单 owner 线程持有 store/runtime/roster/waiter；单执行线程按并发 1 跑 adapter/tool；任何锁都不得包住 provider 调用。会话“独立”指控制入口互不阻塞与 roster 有界公平推进，不是 provider 并发。

## 1. 决策 1：服务与驱动

**裁决：修改后批准方案 A（transport-neutral `v24/session/`）。**

- 新增 `v24/session/{service,store,driver,wire,types}.py`。`SessionService` 只依赖 runtime protocol，不 import Chainlit，不 import `v24.ui`。
- S0 交付范围：Python 进程内 API + Chainlit UI。MCP/HTTP 为 reserved；不实现 MCP server，不做通用 CLI 合同。
- M1 不强制整体搬迁 `AgentRuntime`；由组合根注入现有 runtime，headless gate 注入 fake runtime。
- 线程模型（修正两条 Oracle lane 的“多 driver/并发 4”）：
  - `session-owner`：拥有 `SessionStore`、runtime、roster、waiter；执行所有控制与 finish/settle。
  - `session-exec`：只做 adapter/tool IO，并发 1；不碰 store/DB/journal。
  - 调用方 `wait` 线程：短读 + 退避/条件变量，不占 owner。
- `app.tick` 退出“唯一驱动者”地位；UI 只作为 adapter 调用 service。M1 可以先保留 UI 旧路径，但新 gate 必须能在不启动 Chainlit 的情况下跑完整生命周期。
- Gate 必须包含静态 import 检查（`v24/session` 不 import `chainlit`/`v24.ui`）与 headless 全生命周期。

**为什么拒绝多 driver / 并发 4**：`v24/host/worker.py:3` 明确“One process, at most one in-flight effect”，`run_once()` 每轮只 claim 一个 effect；`v24/ui/control.py:39` 的 `AgentRuntime` 是单写者。多开 worker 或并发 provider 会破坏 journal 单写者与单 in-flight 不变量。

**残余风险**：runtime 生命周期从 UI 转到 service，异常关闭/重建要覆盖。M1 用注入 + headless gate 锁住；UI 全量切换在 M4。

## 2. 决策 2：宿主命令账本

**裁决：修改后批准方案 A。持久 start 索引 + per-command receipt；两相位 `intent/completed` + `owner_epoch` 围栏；deferred 冻结首次响应；每 session 保留 256 条 completed receipt。**

- `v24.requests` 是 run 级 RPC 账本（`v24/sql/49_host_reads.sql:550-579`），不能与含 `session_id/cursor/snapshot` 的 session envelope 比较字节，必须另建宿主账本。
- receipt 至少包含：
  `command_id`、`principal_id`、`session_id`、`op`、完整 client key 哈希、RFC 8785 canonical digest、normalized request、`resolved_variant`/`target_run_id`、`run_request_key`/digest、`phase`、`outcome`、`original_envelope`、`owner_epoch`。
- 幂等作用域：`(principal, session, public_op, key_hash)`。`start` 另用 `start_index` 按 `(principal, key_hash)` 定位已完成命令。
- `steer_active` / `steer_new_run` 首次分派后固定；重试不得按当前状态改派，否则同 key 会随状态漂移。
- 写顺序：
  1. 查 receipt；
  2. 预检（授权、状态、CAS、预算）；
  3. 写 `intent`（`start` 同时 mint session + `start_index`）；
  4. 调内核 RPC；
  5. 追加 typed turn；
  6. 一次原子 replace 写 bind/counter/receipt `completed`。
- 拒绝结果也写 receipt；“零写”只指 run/effect/request 不变。
- deferred 是冻结的首次响应：同 key 重放返回同一 deferred，不得第二次变成 committed。暂时错误保持 `intent`；永久错误（`invalid_args`/`budget_exceeded`/`unauthorized`/`scope_closed`）记 `rejected`。
- 恢复：`intent` 存在时按 `run_request_key` 查 `host_request`；命中则补完本地提交，未命中才允许同 key 重试。`owner_epoch` 递增围栏，S0 不用时间 lease（单进程，崩溃后没有旧线程可写回）。
- receipt 保留 256 条 completed；超过后同 key 视为新命令。`start_index` 不随 receipt 淘汰。API 必须写明这个 replay 窗口。
- `turns.jsonl` 带 `command_id` / `store_generation`，读取按 `command_id` 去重；`respond` 不加 `user_turn_no`。

**残余风险**：256 条窗口是 API 参数；账本含用户请求和历史响应，必须 0600 且禁止提交。

## 3. 决策 3：交互安全

**裁决：修改后批准方案 A，但把“共享串行域”落在 owner 线程，而不是一把全局锁。**

- 单 owner 线程串行执行所有控制与 settle/finish；单执行线程（并发 1）只跑 provider/tool；任何锁都不得包住 provider 调用。
- `HostWorker.run_once` 拆成：
  - `prepare`（owner）：claim effect、写 journal；
  - `execute`（exec）：只调用 adapter/tool，不碰 DB/journal；
  - `finish`（owner）：settle、generation/late 规则。
- roster 在 owner 上轮转所有活动 scope；每轮每 run 最多推进一个短阶段；控制入口不被 provider 阻塞。
- waiting-steer 的竞态由 owner 线程天然互斥解决：`SessionService.steer` 的预检与内核写在 owner；driver 出 interaction 的 settle 也在 owner。若某个 settle/recover/reconcile 暂时无法搬回 owner，才使用 per-run 锁，锁序固定 `run → DB`，不得反向申请，不得跨 provider 持有。
- Gate：
  - adapter 被 barrier 阻塞时，另一个会话的 `start/steer/poll/cancel` 仍能在 1 秒内返回；
  - 在“steer 预检后、内核写前”插入 interaction settle，验证两种顺序都不会清除已提交 interaction；
  - 同一 barrier 覆盖 recover/reconcile。
- 明确不做：跨进程锁、advisory lock、多主机。

**残余风险**：`prepare/execute/finish` 拆分是 S0 最大实现风险，尤其 adapter 生命周期与 finished 未 settle 的恢复。

## 4. 决策 4：读合同

**裁决：修改后批准方案 A。S0 禁 poll 增量分页；poll 成功后可把 cursor 推进到已返回前缀最大 seq；wait 无 cursor 先取高水位；多会话用 per-session cursor 映射 + winner 轮转；`run_started` 优先于同 run 判断；cursor 增加 `session_revision`。**

- Cursor 字段固定为：
  `{session_id, run_id, run_revision, event_seq (int ≥0), registration_generation, epoch_no, generation, interaction_id|null, user_turn_no, session_revision}`；禁止 `event_seq=null`。
- `poll`：
  - `include_events=true` 返回当前 run 最早 64 条，不做 `after_event_seq` 增量分页；
  - 同 run 时 `event_seq=max(in.event_seq, prefix_max)`；`include_events=false` 时不变；换 run 时重置为 0；
  - `poll` 不写 store、不消费 wake、不增加 revision。
- `wait`：
  - 无 cursor 先分页调用 `wait_check` 取高水位，再开始正常等待（等价“从现在开始”，不是从 0 重放）；
  - `include_events=false` 不产生 event 唤醒、不推进 `event_seq`；
  - `event_seq` 只推进到实际返回的最后一条；
  - `run_started` 的判据改为“当前 run_id 与 cursor.run_id 不同”，覆盖“R1 终态 → steer 出 R2 → R2 在下一次 wait 前也终态”的窗口；同 run 的下一次 wait 再报 `terminal`。
- 多会话：请求 `session_ids + cursors`；响应保留 winner + `pending_session_ids`，新增完整 `cursors` 映射，只更新 winner 的 cursor；按 principal 轮转 winner，避免 sticky terminal 饿死其他 session。
- 未决项默认值：
  - `registration_stale` 映射为 `epoch` + 新快照 + `event_seq=0` 的重置 cursor，不新增第八种 wake；
  - unknown session 单会话整请求 `not_found_or_denied`；多会话逐项 `ok:false`；
  - `all_terminal` 是布尔标志，不新增 wake reason；
  - revision-only 默认不唤醒；正超时到期时返回快照并带 `changed=true`，避免忙等；
  - `include_events=false` 不推进 event cursor。
- Gate 必须覆盖：>64 条连续 wait 不跳不重；`include_events=false`、换 run、stale 均不越过未返回事件；generation-only/revision-only 各一个合同向量；R2 已终态的 `run_started`；多会话缺项/多项/未知/多个 ready/公平轮转/`all_terminal`。

**残余风险**：v1 客户端拿不到第 65 条以后的历史事件；这是 64 条能力边界，必须在 API 中写明。

## 5. 决策 5：v2 数据政策

**裁决：批准方案 A。`format_version=2`；legacy 计数近似延续并显式标注；`.v1.bak` + `.prev`；回滚前完整归档 v2 增量；损坏整体 fail-closed；撤回“单会话损坏不影响其他会话”。**

- 迁移：
  - `session_id = conversation_id`；
  - `run_no = len(bindings)`；
  - `user_turn_no = len(turns)`；
  - `counter_origin = legacy_approx | native_v2`；
  - `session_revision`、`owner_principal_id` 持久化。
- 备份：`sessions.json`、`turns.jsonl` 写 `.v1.bak`（0600）；每次原子替换保留 `.prev`；迁移失败 quarantine 新产物，不覆盖原件，不自动建空 store。
- 损坏：JSON/版本/必要结构损坏 → 整体 fail-closed，保留原件并给诊断；单 session 多活动 run → 冻结该 session 控制并报不变量错误，不自动挑一个。
- 回滚脚本 `v24/session/rollback.py`：
  1. 停准入/关 service；
  2. 归档 v2 sessions/turns/transcript/journal（0700/0600）；
  3. 恢复 `.v1.bak`；
  4. 校验 v1 可加载；
  5. 不覆盖归档，不做自动双向合并。
- 开关只控制入口；新二进制关开关仍读 v2；旧二进制必须走上述回滚。
- Gate：迁移往返、legacy 标记、损坏 fail-closed、从 `.prev` 恢复、回滚后旧代码可加载且归档完整。

**残余风险**：回滚后升级期间新建的 session/turn 对旧 UI 不可见，只能从归档查看；DB 中已提交 run 不受回滚影响。

## 6. 未决项与默认值

| # | 问题 | 默认值 | 状态 |
|---|---|---|---|
| 1 | `registration_stale` 的 wake 映射 | `epoch` + 新快照 + `event_seq=0` | 已定 |
| 2 | unknown session 的整请求/逐项错误 | 单会话整请求；多会话逐项 | 已定 |
| 3 | `all_terminal` | 布尔标志，不新增 wake | 已定 |
| 4 | revision-only 唤醒 | 默认不唤醒；正超时带 `changed=true` | 已定 |
| 5 | real respond 能力码 | `waiting_unsupported` | 已定 |
| 6 | legacy `user_turn_no` | 近似延续（`len(turns)`）+ `legacy_approx` 标记 | 已定 |
| 7 | 回滚后新数据 | 只读归档，旧 UI 不可见 | 已定 |
| 8 | S1 baseline bump | S0 观察期后独立批准；不阻塞 S0 | 治理项 |
| 9 | `s14/test_g12.py` | 目前不存在；S1 批准件决定新建或并入既有 gate | 治理项 |

## 7. 与三份文档的对应修改

| 文档 | 必须修改 |
|---|---|
| 核验版设计 | 写入本裁决；消除 D1/D6/D10/D11/D16 的二选一；D15 的 `v24.start(session_id)` 标 S1-only；§4.3–4.7/§4.9/§4.11/§5.1/§5.3/§6/附录 B 同步 |
| API | 传输改为「Python 进程内 + Chainlit；MCP/HTTP reserved」；固定 cursor 形状与 per-session 映射；poll 禁增量分页；wait 高水位/winner/`all_terminal`；receipt/deferred/256 窗口；real respond `waiting_unsupported`；错误表去重 |
| 计划 | 替换 M1 文件表为 `v24/session/*`；补 owner/exec 线程、锁序、账本形状、迁移回滚；S0 收口 diff 同时锁 `v24/sql`、`v24/load.py`、`v24/host/deepseek.py`；gate 清单固定并补 s5、s10–s12、Cordis |

## 8. 开工条件核对

- [x] 决策 1：`v24/session/` + Python/UI 范围 + owner/exec 线程
- [x] 决策 2：start 索引 + 两相位 receipt + 256 窗口
- [x] 决策 3：owner 串行域 + prepare/execute/finish
- [x] 决策 4：poll 禁增量分页 + per-session cursor + 高水位
- [x] 决策 5：v2 + `.v1.bak`/`.prev` + 归档回滚 + fail-closed
- [x] 用户实施授权（2026-11-05「按照决策继续推进」）
- [x] 设计/API/计划修订（本记录配套提交）
- [ ] S0-M1 gate 全绿
- [ ] M1 里程碑提交

**结论：S0-M1 可以开工。**
