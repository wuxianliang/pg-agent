# v24 稳健收尾、真实 Provider 与多语言插件测试：Plan

## Goal

在不改变 v24 冻结内核语义（唯一写口 `v24.advance`、十表、24 码、无第二 claim/queue/recovery 状态机）的前提下，先把 v24 从「内核已验收」推进到「host 可执行」：补齐协议合法的 host 只读工作发现面、用对抗性用例收敛内核稳定性证据（含真实 host 才会暴露的闭包增长与租约极限），再以 opt-in 非 gate 脚本完成真实 DeepSeek provider 验证，最后用 v24 原语承载一个最小多语言插件（Python + 至少一个第二语言）的 install → activate → tool → dispose 测试。真实网络 IO 不进 gate；产品 SQL 变更仅限 Oracle 批准的 host 只读面修订，且必须同步 `v24/load.py` 的 `CANONICAL_ORDER`/`SQL_LOAD_ORDER` 与 `v24/s1/setup_db.py:750-766` 的期望元组。

## Done when

1. **M-H**：`v24/sql/49_host_reads.sql` + ACL/loader/`expected_canonical` 四处原子落地；`uv run python v24/s9/test_g8.py` 无参数 exit 0（含闭包实测与 D-S6-12/D-S8-7 补测）；11 条既有 gate 仍全 exit 0；`git diff --exit-code` 对九个冻结内核 SQL 文件为空。
2. **M-R**：`v24/host/**` 落地；`uv run python v24/s10/test_g9.py`（脚本化 transport，无网络）exit 0；`env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI UV_NO_ENV_FILE=1 uv run python -m v24.host.smoke --real-provider-smoke` 打印 `credentials_absent` 退出 2。
3. **M-P**：`uv run python v24/s11/test_g10.py`（Python 全生命周期，真实本地子进程、无网络）exit 0；`uv run python v24/s11/test_node.py --node` 有 Node 时 exit 0、无 Node 时打印 `[SKIP] not_run/toolchain_absent` 退出 2（**不算通过**）。
4. 三个里程碑各自一次提交（`M-H` → `M-R` → `M-P`），按路径逐项 add、不 force、不碰 main；每个里程碑提交前，既有 11 条 closeout 与该里程碑的 extension check 全部实跑绿。
5. 收尾工件更新：`docs/reviews/v24-conformance-matrix-2026-10-23.md`、`docs/reviews/v24-deviation-ledger-2026-10-23.md`、`v24/s9|s10|s11/README.md`、`v24/s7/README.md`（保留历史 11/11，追加新 closeout 段）。
6. 未满足以上任一条即不得宣称对应里程碑完成；`retry_with_closure` 在必需流程出现即停止 R/P 验收并另开内核设计修订。

## Execution index

| # | 工作项 | Goal | Done when | Key files | 依赖 | Size |
|---|---|---|---|---|---|---|
| M-H-1 | 基线与 pre-G 披露 | 固定 HEAD/工作区/冻结 SQL 摘要，登记 `advance` 在取 G 前读 `v24.fibers` 的披露 | 11 条既有 gate 全绿；披露写入台账 | `docs/reviews/v24-deviation-ledger-2026-10-23.md` | 无 | S |
| M-H-2 | host 只读 SQL 面 | 9 个 STABLE DEFINER 只读函数 + 1 个内部授权 helper，替代 owner 表直读 | 四处注册原子落地；loader/setup 自检过 | `v24/sql/49_host_reads.sql`、`50_permissions.sql`、`v24/load.py`、`v24/s1/setup_db.py` | M-H-1 | M |
| M-H-3 | G8 对抗性 extension check | 授权矩阵、读面正确性、闭包增长实测、租约/G/恢复对抗、D-S6-12/D-S8-7 补测 | `uv run python v24/s9/test_g8.py` exit 0 | `v24/s9/{test_g8.py,h_support.py,README.md}` | M-H-2 | L |
| M-R-1 | host 包骨架 + durable journal | 单线程 worker、SQLite/JSONL journal、有界进程执行器 | Fake executor 下三个崩溃边界不重复 IO | `v24/host/{__init__,db,worker,journal,process_io}.py` | M-H-3 | L |
| M-R-2 | v24 DeepSeek adapter | 复用 v15 DB-free 件，自建序列化/解析/映射/租约 | 映射表全部有用例；`timeout_s ≤ 239`；零 reserve 不外呼 | `v24/host/deepseek.py` | M-R-1 | M |
| M-R-3 | G9 脚本化 provider extension check | ScriptTransport 证明映射/unknown/lease/崩溃边界 | `uv run python v24/s10/test_g9.py` exit 0 | `v24/s10/{test_g9.py,README.md}` | M-R-2 | L |
| M-R-4 | opt-in 真实 provider 冒烟 | `credentials_absent`/`not_requested` 纪律 + 全链真实一次 | 无 key exit 2；有 key 手工验收并留证 | `v24/host/smoke.py`、`v24/s10/README.md` | M-R-3 | S |
| M-P-1 | approved adapter registry + line-JSON 派发 | digest 精确匹配 → 固定 argv；一帧协议与错误映射 | digest 不匹配零 spawn；坏帧/超时 → unknown 且已 reap | `v24/host/{plugins,registry,line_json}.py` | M-R-1 | M |
| M-P-2 | 两个参考插件 + G10 Python 生命周期 extension check | Python + Node 同合同插件；install→…→dispose 全链 | `uv run python v24/s11/test_g10.py` exit 0 | `v24/s11/{plugins/echo.py,plugins/echo.js,plugin_fixtures.py,test_g10.py,test_node.py,README.md}` | M-P-1 | L |
| M-P-3 | 多语言 opt-in 验收 | 同一 run 先 Python 后 Node 再 final；缺 Node exit 2 | Node 实际 exit 0 留证；Python extension check 绿不算多语言完成 | `v24/host/plugin_smoke.py` | M-P-2 | S |

## Background

> 证据基线：worktree `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99`（branch `v24`，HEAD `d8155f4`）。主检出（`main`，`ab34d69`）**不含 `v24/`**，一切 v24 事实以 worktree 为准。

### 1. v24 已完成面与验收基线

- S1–S8 / G1–G7 全部完成；G6 **30/30**（16 矩阵体 + N1–N9 负例 + L1–L5 锁序审计 = 30 个 ID，覆盖 18 格矩阵）；closeout **11/11**（10 既有 gate + G6）；错误码 **24 个有生产者 / 0 个未产生**；`v24/sql/**` 与 `v24/load.py` 在 S7 零 diff；里程碑 `d8155f4 v24: add concurrency matrix (G6)` 已推送 `origin/v24`（0/0）；`v24/` 无未提交改动。
- 十张表：`scopes/runs/effects/pins/episodes/fibers/slots/installs/events/requests`；唯一写口 `v24.advance(effect_id, outcome)`；G = `pg_advisory_xact_lock(24,1)` 首锁；`model_call.pin_id` 必须为 NULL，只有 `tool_call` 消费 pin（D-S8-12）。
- 证据全部是 Fake：`v24/s1/fake_host.py`、`v24/s4/fake_llm.py`、`v24/s6/{fake_crash_host,crash_worker,recover_worker}.py`；gate 用 `install_no_network()` 主动禁用 socket（`v24/s4/test_g2b.py:68-79`）。
- pre-plan §9 明确「不连接真实 provider/网络；不在数据库事务内做外部 IO」；设计 §9.1 要求所有 gate 适配器为 Fake。真实 provider 是 pre-plan 之外的新范围，不是漏掉的阶段。

### 2. Host ↔ DB 协议的承重契约（本次核对到的精确形状）

- Host 以 `v24_service` LOGIN 连接。协议角色**零表权限**（`v24/sql/50_permissions.sql:6-7`），只 EXECUTE 白名单 **18 个函数**（`:15-56`）；`install` 连 `v24_admin` 都不可执行（`:27-28`）。
- `run_owner` / `run_projection` 是 DEFINER 但**没有任何角色的 EXECUTE 授权**，只能从 `poll`/`wait_check` 内部到达（`47_verbs.sql:48,53,111,119`）。
- 执行一个 effect：读 `effects.request` → `advance(effect_id,{v:1,class:'claim',claim:null,body:{lease_ms}})` → **COMMIT 且连接 idle** → 事务外 IO → `advance(effect_id,{v:1,class:'success|failure|unknown',claim:<token>,body:{kind,result}})` → COMMIT。claim token 恰为 `{attempt,fence,owner}`，`owner` 来自 `session_user`（`30_advance.sql:891-895`）。
- **model_call request 精确闭集**（`48_loop.sql:411-456`）：`{v,cause,run_id,epoch_no,generation,reserve:{tokens},digests:{policy,schema,toolset}}` + 按 cause 追加 `input`+`budget`｜`input`+`instruction`｜`response`+`origin_effect_id`｜`input`+`batch_digest`+`state`｜`input`+`spawn_key`+`parent_run_id`；cause ∈ `start|steer|respond|continuation|spawn`。`input` 是**不透明 JSON，DB 不渲染 prompt**；`reserve.tokens ≤ 4096`（`loop_policy`，`48_loop.sql:10-13`）。
- **model result 精确闭集与互斥**（`48_loop.sql:281-399`）：`{text?,tool_calls?[{key,args}],interaction?{schema_digest,prompt_digest,payload},final?{text},usage?{tokens,wall_ms}}`；`tool_calls ⊥ final`、`tools ⊥ interaction`、`spawn ⊥ {interaction,final}`；`usage.tokens > reserve.tokens` → 超预算拒绝（`:582-583`）；非 spawn 最多 16 条 tool_calls，`agent.spawn` 最多 1 条且必须单独。
- **对话 transcript 不在 DB**：两条 continuation 后继都把 `state` 写成 `'{}'`（`48_loop.sql:1183,1586`），`batch_digest` 只是该批 tool effect id 排序串的 sha256（`:1554-1559`）；result 闭集**没有** `reasoning_content`，而 `interaction` 与 tools 互斥 ⇒ host 无法把思考过程随工具回合一起落库。**host 必须自持 per-run durable journal**（消息 + `reasoning_content` + 工具结果 + provider response id）。
- 工具结果恰为 `{status:'ok'|'error', output:object, usage?:{wall_ms}}`（`48_loop.sql:1369-1405`）。
- claim/lease：live lease 再 claim 返回 `deferred` 且无 token；`model_call`/`tool_call` 过期 lease 只返回 `stale_claim`，不产生第二 attempt；host kinds（`host_prepare`/`host_release`/`inspect_resource`）过期可 re-claim，`attempt/fence+1`，旧 token 变 `stale_claim`（`30_advance.sql:882-895`）。**没有续租/延期**；`lease_ms` 必填且上限 **300000 ms（5 分钟）**（`:174-182`）。
- `model_call`/`tool_call` 固定 `replay_policy='no_replay'`；过期后由 `command_recover` 转 `unknown`，不能自动重打（`48_loop.sql:930,1133,1178,1581,1639`；`49_recovery.sql:18-31`）。
- cancel 不撤销 live claim：只写 `cancel_requested` 并 bump `driving_generation`；迟到 success/failure 记 fact/cost、发 `late=true` 事件，但**不发布 successor**（`40_interpreters.sql:2427-2459`；`48_loop.sql:817-845`）。
- `unknown` 是 loop 终态：run → `blocked_unknown`（CHECK 终结，不可复活），pin 保留，`resource_quiesced_at=NULL`，不退 token（`48_loop.sql:848-857,2928-2933`；`10_schema.sql:50,54`）。
- **结算不检查 `lease_until`**，只查 `status='claimed'` + 精确 `attempt/fence/owner`（`30_advance.sql:284-289`）⇒ 过期本身不废除晚到回执的合法性。

### 3. 关键缺口一：没有协议合法的 host 工作发现 / 请求读取面

今天一个真实 host 需要的读取**全部无路径**：

| 需要的读取 | 参照证据 | 今日阻塞 |
|---|---|---|
| 枚举 scope 内 `ready` effect（id/kind/request/run/pin/epoch） | owner 夹具 SQL `SELECT effect_id FROM v24.effects … status='ready'`（`s5/test_g4.py:151`）；索引 `i_effects_ready`（`10_schema.sql:113`） | 无函数；`recoverable_effects` 只筛 `claimed AND lease_until<=now()`（`49_recovery.sql:26-27`）；表 SELECT 被 REVOKE |
| 读某个 effect 的 `request` | `s1/fake_host.py:36`、`s6/fake_crash_host.py:80-84`、`s4/test_g2b.py:103,277-278` | 无函数；claim 信封不含 request（`30:891-895`）；`recoverable_effects` 7 列不含它（`49:5-13`） |
| 读 install 行 / `installs.state` / `install_id` | `s6/recover_worker.py:267-269,285-287` | 无函数；`install()` 只做准入（`40:4113`） |
| 读 `fibers.fiber_id`/`control_seq` 以恢复激活 | `s6/recover_worker.py:289-293,397-401` | 无函数；`fiber_control` 要求两者作为入参（`45:132-147`） |
| 列出一个 run 的 effects（哪个 model/tool ready） | 结算 `emitted[]` 是唯一 id 来源（`40:423-427`），重启即失 | `poll` 只回 run+events（`47:54-68`）；`run_projection` 只有 run（`47:18-28`） |
| 读已提交 request/receipt 字节做比对 | `s6/recover_worker.py:150-157` 读 `v24.requests.request_bytes` | 无函数；重放只在校验调用方重投相同字节（`30:254-263`） |
| 发现有哪些 scope / 自己拥有哪些 | 重启后 scope id 由 env 注入（`s6/recover_worker.py:252`；`s6/test_g5.py:497`） | 无函数；`resolve`/`recoverable_effects`/`command_recover` 都要求调用方给 scope |
| 读自己 claim 的活租约/状态 | 只有按 scope 的过期探测（`49:26-27`） | 无 per-effect 状态读、无 renew 操作 |

**授权缺口不只是缺函数**：`poll`/`wait_check` 拒绝非 `run_owner`（`command_start` 的 requester）且非 admin 的调用（`47:45-51,111-114`）；`recoverable_effects`/`command_recover` 只允许 scope owner 或 `v24_admin`（`49:31-32,298-302`）。⇒ host 重启后连 poll 自己创建的 run 都要靠 `run_owner` 身份；发现 ready effect 完全无路。这是真实 provider 之前的第一个设计修订点，不是测试夹具问题。

ACL 闭合使「开表读」不可行：`REVOKE ALL … FROM PUBLIC, v24_admin, v24_service, v24_operator`（`50:6-7`）；DEFINER 白名单恰 7 个、只授权 5 个（`:66`）；ACL gate 禁止任何其他 DEFINER 体含 `insert|update|delete|pg_advisory*`（`:100-105`）。

### 4. 关键缺口二：内核稳定性极限（真实 host 才会暴露）

- **G 的杀伤半径**：`pg_advisory_xact_lock(24,1)` 在 shape 校验与认证之后、读任何 v24 表之前拿（`30:246-247`），xact 级，常量键无 scope/run 分量。持有它做外部 IO 会阻塞**所有** claim、settle、六动词命令与 `command_recover`（恢复也走 `advance`，`49:232`）。不拿 G 的只有 `poll`/`wait_check`/`resolve`/`recoverable_effects`。全库无 `lock_timeout`/`statement_timeout`，advisory lock 也无超时参数——挂死的 host 后端会一直持 G 直到事务结束或 PG 杀后端。「claim 后 COMMIT 再 IO」只是部署规则（设计 §1.5:78），SQL 不阻止 `BEGIN; advance(claim); <IO>; advance(settle); COMMIT`。
- **每次 claim 的闭包遍历**：无锁递归 CTE 发现（`30:320-527`，含 install→该 install 历史全部 host effect 的边 `:410-413`、episode→pins `:462-472`、命令 payload 引用 `:497-503`）→ 8 条有序 `FOR UPDATE`（`scopes→runs→effects→installs→fibers→episodes→slots→pins`，`:553-570`）→ 每 id `EXISTS` 探测（`:535-551`）。闭包 > 512 → `retry_with_closure`，**零写入**（`:529-533`）；无 `SKIP LOCKED`/`NOWAIT`；一次一个 effect，无批量原语。
- **闭包单调增长（真实风险）**：effects/pins 从不删除（`10_schema.sql` 无 DELETE，events 只追加），install→effects 边把该 install 历史上所有 `host_prepare`/`host_release`/`inspect_resource` 拉进闭包 ⇒ 长寿 install 的每次 claim 闭包只增不减，直到 512 上限让该 install 的每次 claim 变成**永久** `retry_with_closure`。多语言插件测试每次 activate/dispose 都产生 host effect，是这条风险的正撞口；必须先测量再决定是否需要设计修订。
- **恢复无自动化**：无 job/queue/cursor/恢复表、无 `NOTIFY`/`LISTEN`、无 reclaim 触发器（`v24/s6/README.md:93`）。`command_recover` 一次 sweep ≤ 16 行、按冻结提示行处理、`has_more` 只是提示（`49:224-245,319-327,414-433`）；`manual` 行计 `manual_debt` 不占 16 行额度。
- **provider 死掉后的 model_call**：一直 `claimed`；live lease 期间再 claim 得 `deferred`，过期得 `stale_claim`（永不可再 claim），只能 `command_recover` 转 `unknown`；之后迟到回执 → `receipt_conflict`（远端可能已执行，设计 §B.4）。
- **租约 vs 真实 provider 延迟**：`lease_ms` 上限 5 分钟，而 DeepSeek `timeout_s` 可到 600s、thinking 模式长输出更久。但结算不查 `lease_until` ⇒ 在「单受信 host + 不自行 sweep」下慢调用仍能收口；一旦 host 自建 sweep（D3 活性要求），必须排除自己在飞的 effect，否则会把自己的 `model_call` 打成 `unknown`。另注意：`command_recover` 的 wrapper **自行发现候选**，调用方无法通过预过滤 `recoverable_effects` 的返回值来避开在飞项（`49:178-245`）⇒ 只能靠「串行执行 + 有在飞项时完全不 sweep」。
- **unknown 无 inspect 收敛路径**：`inspect_resource` 只针对 `host_prepare`/`host_release`（`40:3599`）；tool unknown 的 pin 与 `resource_quiesced_at IS NULL` 会一直参与 seal/dispose/close 屏障（`48:86-103`；`46:258-266,334-339`），scope 可能无限期无法关闭。
- claim 授权只按角色不按 run ownership：任何 `v24_service` 成员可 claim 任意可 claim effect（`30:50-52,575-580`）；v1 依赖单受信 host（设计 §1.5:52）。
- **已披露的实现与设计措辞不一致**：`30_advance.sql:205-213` 在 `command_install` 且 `owner_fiber_id` 非空时，会先做一次 `NOT EXISTS (SELECT 1 FROM v24.fibers …)` 才在 `:247` 取 G。设计 §B.1 的「G 是第一把显式锁、读任何 v24 表之前」在该窄路径上不成立。源码注释自陈 fibers 永不删除故无竞态；本计划**不修改该冻结代码**，只在台账登记披露，并把 §10.3「全序锁无环」的证伪口径按此更正。

### 5. v15 真实 DeepSeek 可复用件与耦合面

- **可原样复用（零 DB/SQL import）**：`v15/provider/errors.py`、`v15/provider/pricing.py`、`v15/provider/deepseek.py` 的 HTTP/解析/计费部分（`deepseek.py:16-17`）。
- `DeepSeekProvider(api_key=None, base_url=None, timeout_s=120, transport=None, clock=None)`（`deepseek.py:272-293`）：key 解析 `DEEPSEEK_API_KEY` → `OPENAI_API_KEY` → `""`（`:281-282`）；base 默认 `https://api.deepseek.com/v1`（`:283-284`）；allowlist 仅 `deepseek-flash`（`:19`）；`preflight` 返回 `credentials_absent/model_missing/model_not_allowlisted/endpoint_rejected` 四态且从不抛（`:300-313`）。
- `complete(logical_digest,n,request,llm_config)` 丢弃前两个参数（`:316`），只发 `{model,messages,stream:false,max_tokens?}`（`:332-336`），消息角色仅接受 `system/user/assistant` 且 `content` 必须 str（`:323-331`）；返回 `{content,prompt_tokens,cost_usd,provider:{…}}`，**没有** `text/tool_calls/interaction/final/usage`，`provider` 里有 `reasoning_chars` 但没有 `reasoning_content` 原文。
- `StdlibTransport`（`:88-128`）：proxy off、不跟随 redirect（3xx 交回分类器判 `ProviderUncertain`）、64 KiB chunk、10 MiB cap、绝对单调 deadline；注意 `complete()` 的 deadline 原点用真实 `time.monotonic()`（`:341`），注入假 clock 不移动它。
- **不可提升**：`v15/worker.py` 是 v15 SQL 的 RPC 客户端（约 30 处 `SELECT v15.v15_*()`），且 import `v15.fake_tool`/`v15.protocol.render_prompt`/`split_sql`；`v15/provider/v15_provider.sql` 只加函数不加表，但读写 `v15.llm_attempts/llm_requests/iterations/invokes/budget_pools`。
- 可复用的纪律：`_assert_idle()` 在 HTTP 前强制无开事务（`worker.py:536-538,598`）；租约 ≥ timeout + 60（`:250-254,548-561`）；无 key → `credentials_absent` 退出 2 且不构造 adapter；key 只在环境变量，**不进 `.env` 或数据库**（`demo_v15/README.md:25`）；真实 socket 只允许两个入口且当时无开事务（`AGENTS.md:73-75`）。

### 6. DeepSeek API 当前事实（2026-10-24 外部核查）

- `deepseek-flash` 是**真实模型 id**（`DeepSeek-V4.1-Flash-1017`），与仓库 allowlist 一致；`deepseek-chat`/`deepseek-reasoner` 已于 2026-07-24 停用；`deepseek-v4-pro` 仍在列表但官方同月新闻称「逐步淘汰」，非长期稳定选项。
- **工具调用两模型均支持（含 thinking 模式）**：`tools` 仅 `type:"function"`，名字唯一且 ≤128 字符 `[A-Za-z0-9_-]`；响应 `finish_reason="tool_calls"`，`message.tool_calls[].function.arguments` 是 **JSON 字符串**（需解析，可能非法）；工具结果以 `{"role":"tool","tool_call_id":…,"content":…}` 回传。
- **thinking 模式默认开启（effort high）**：`tool_choice:"required"` 与指名强制在 thinking 模式返回 **HTTP 400**（需先 `{"thinking":{"type":"disabled"}}` 或 `reasoning_effort:"none"`）；带 `tools` 时必须回传**所有**历史轮的 `reasoning_content`，否则 400。⇒ 与 §2 的 transcript 结论互相加强：host 必须自持含 `reasoning_content` 的完整消息史。
- 上下文 **1M** tokens；`max_tokens` 1–393216，未设时默认 8K（非思考）/64K（思考）/128K（`reasoning_effort:"max"`）；限流是按账号**并发**（flash 2500 / v4-pro 500），无公开 RPM/TPM；推理 10 分钟未启动服务端断连；`stream:false` 受支持。
- OpenAI 兼容（`base_url=https://api.deepseek.com`，官方示例用 `openai` SDK）；`frequency_penalty`/`presence_penalty` 已弃用，thinking 模式忽略 `temperature`；**当前文档页未提及 `/v1` 别名**——仓库默认 base 需在实现时复核。`parallel_tool_calls` 无文档，按不支持处理；`strict` 模式仍是 beta（`/beta`）。

### 7. v13 多语言与插件的真实状态（下阶段重要参考）

- **v13 没有 plugin plane**：`plugin` 在 `v13/**/*.sql`、`v13/**/*.py` 零命中；registry `kind` 闭集 `service|tool_profile|prompt_section`（`v13/registry/v13_registry.sql:8`）。「multilingual plugin plane」只有三份 **untracked** 设计文档（2026-10-20），明确写「零代码 / 零 gate 运行」。
- 真实的多语言面是 **line-JSON tool ports**：共用桥 `v13/read_tools/bridge.py:43-80`（`run_line_json`，exit 0/3/1，单帧），契约 `docs/designs/v13-tool-ports.md:71-90`。平面：in-process Python（无 wire，永远跑）、Node 移植版、Swift 移植版、DuckDB/Python、pi/Node、PiG/Go、PiSwift/Swift。实测：`pi_ports` **302 PASS**、`read_tools --contract` **237 PASS**（`docs/reviews/v13-pi-ports-trilingual-2026-09-28.md:11-12`）；缺工具链 → `[SKIP] not_run/toolchain_absent` 退出 **2，不算通过**（`v13/pi_ports/README.md:13`）。
- `tools` 表六列 `(name,description,kind,handler,param_spec,enabled)`（`v13/schema/v13_core.sql:581-593`），契约禁止加列（TP-CAT-4）。生产只执行 `kind='sql'`（`v13/triage/v13_triage.sql:912,920`）；`kind='tool'|'llm'` 只把 handler 字符串塞进 effect request 发 pgmq，**name→进程的 dispatch 只存在于测试字典**（`v13/read_tools/test_read_tools.py:952-973`；`v13/pi_ports/test_pi_ports.py:622`）。
- registry 有 revision 半开区间与 **bigint** as_of（`v13_registry.sql:413,477-482`），无时间戳 as_of；pin 是 `(effect,attempt,fence)→(context_revision,tools_revision)` 的**不可变冻结**，有 BEFORE UPDATE/DELETE 拒绝、无 release（`:608-644`）。
- **v13 桥的已知不足**（影响 P 段复用方式）：`run_line_json` 读第一行后忽略后续输出，且一次性捕获 stdout，不足以承担本次的输出边界检查（`v13/read_tools/bridge.py:43-80`）⇒ P 段自建 `line_json.py`，沿用帧契约而非直接调用该桥。
- **v8 先例**（`v8/plugin/v8_plugin.sql:38-140`）：`plugin_specs`/`plugin_implementations`/`generations`/`generation_members` + 生命周期函数，全 SQL 侧；`locus` 只是 `text NOT NULL` 无 CHECK（`:77`）；没有进程 spawn、没有 artifact loader、没有 runtime lease/epoch。**v99** 设计过 Python persistent + Node one-shot + SQL 的 G01–G23，Oracle **Not ready**（8 个 P1），从未实现；v24 明确不继承 v13/v99 ABI（`docs/designs/cordis-plugin-core-2026-10-22.md` §8）。
- **v24 可承载 plugin 的原语已存在**：`installs`（`identity/version/manifest/manifest_digest/artifact_digest/adapter_digest/state`，`10_schema.sql:202-225`）、`fibers.install_id`（`:163`）、`episodes.epoch`（`:148-160`）、`slots`、`pins`（可 release：`48_loop.sql:86-104,2968-2971`）、`host_prepare`/`host_release`/`inspect_resource`。缺的是：registry revision/as_of、scope-name shadowing、global tool catalog、context_revision、approved process-adapter registry、per-language argv。

### 8. Gate / 收尾工件约定（新工作必须遵守）

- **唯一共享夹具** `v24/s1/setup_db.py`（各 stage gate 只 import 它，如 `v24/s8/test_g7.py:25-36`）：拒绝 TCP/多主机 DSN，只接 pgembed Unix socket（`:52-68`）；私有 helper 子进程起库（`:222-248`）；唯一库名 `v24_s1_<pid>_<12hex>`（`:590-597`）；以 `v24_owner` 单事务 `load_stage` 并断言连接仍 `INTRANS`（`:645-666`）；校验闭合目录（恰十表、无视图、无扩展，`:503-552`）。
- **SQL 注册三处**：`v24/load.py` 的 `CANONICAL_ORDER`（`:9-21`）与 `SQL_LOAD_ORDER`（`:23-35`，要求为前者非空规范前缀，`:44-49`），以及 `v24/s1/setup_db.py:750-766` 的硬编码期望元组（`assert CANONICAL_ORDER == expected_canonical`，`:764`）。`v24/sql/` 下任何未注册 `.sql` 都会让 `validate_manifest()` 抛 `unregistered v24 SQL file(s)`（`:51-60`）。现有 11 个文件，`50_permissions.sql` 必须最后（`v24/s1/README.md:14`）⇒ 新只读函数应作为新文件插在 `49` 与 `50` 之间。
- **无网络守卫三种形态**：s4 monkeypatch `install_no_network`（`test_g2b.py:68-79`，`:2886/:2919`，并自断言 `fake_llm` 源码无网络 import `:733-740`）；s6 静态 import 扫描（`test_g5.py:69-86`，在夹具前调用）；s8 复用/扩展（`test_g7.py:866-877`）。s1/s2/s3/s5 **无** socket 守卫（s1 靠 `fake_host.py:29-33` 的 IDLE 断言）。
- **退出码**：v24 gate 只回 `0`/`1`（无 `return 2`）；`2 = SKIP/toolchain_absent` 或 `credentials_absent` 是 v13/v15 约定（`v13/read_tools/README.md:18`；`v15/provider/README.md:18`）。
- **closeout 11 条命令**清单在 `v24/s7/README.md:210-226`；`--only` 明确不算 gate（`v24/s6/README.md:66`）。
- **收尾工件**（`AGENTS.md:27-31`）：新 SQL 进 loader → 更新 `docs/reviews/v24-conformance-matrix-2026-10-23.md` → 更新 `docs/reviews/v24-deviation-ledger-2026-10-23.md` → 更新对应 stage `README.md` → 按路径逐项 `git add` → commit → push。工作区长期并存其他版本未跟踪 docs，**MUST NOT `git add -A`**。

### 9. 必须遵守的约束与残余债务

- 唯一写口 `advance`；G 首锁；十表；24 码；不得新增第二 claim/queue/recovery 状态机；不得让 `advance` 承载策略分支。
- 外部 IO 一律在事务外；任何 gate 不得开 socket/HTTP；真实入口必须是 opt-in 脚本，调用时无打开事务。
- 插件是声明式的：host 批准的 adapter id + digest，DB 不执行 artifact SQL/argv；`plugin_install()` 不得成为第二状态机。
- v13/v99 代码与 gate 保持原样；旧 green 不是新证明；v13 历史 SQL bytes 冻结。
- 里程碑一次提交、按路径 add、不 force、不碰 main。
- 残余债务：D-S7-2（无 starvation/fairness）、D-S6-12（无 closed-scope 非空 recovery fixture）、D-S8-7（无 multi-spawn/mixed fixture）；设计 D1（host 信任）、D2（CAS 原子性）、D3（scheduler/活性）、D4（cancel 不能停远端）。

## Approach

**总纲：内核只做一次性、可 additive 的只读面扩展；执行策略全部放到新 host 层。** 不重构 v24、不动十表/写口/锁序/错误码/recovery 状态机。三个里程碑顺序固定：M-H（host 可执行面 + 内核稳定性证据）→ M-R（host worker + DeepSeek adapter + 脚本化 extension check + opt-in 冒烟）→ M-P（approved adapter registry + 多语言插件生命周期）。若闭包实测在必需流程触顶，停止 R/P 验收并另开内核设计修订，不在本计划内顺手改内核。

### Oracle 裁决记录（2026-10-25，用户授权 Oracle 代裁）

| # | 决策 | 裁决 | 一句话依据 | 置信度 | 推翻条件 |
|---|---|---|---|---|---|
| 1 | host 读面 ABI | **A**：九个公开函数 + 内部 helper，统一 jsonb 信封，保留独立 `host_run_effects` | `poll`/`wait_check` 已确立闭信封与 `not_found_or_denied` 语义；当前 work 面与 run 全历史是两种 status 过滤，折叠会让一个 ABI 承担两种查询语义 | 高 | G8 证明 jsonb 无法稳定冻结列名/类型/分页断言，或出现必须依赖编译期列类型的调用方 |
| 2 | 非法 tool arguments / 未知工具名 / 缺 tool call id | **A：`failure`**（最小 result `{text:null,usage}`，无 `tool_calls`/`final`） | HTTP 已完成且**没有任何工具被执行**，远端无副作用、成本可核实；这不是「无法判定远端是否执行」的 unknown | 高 | 实测出现工具已在远端执行后才返回畸形调用，或内核 failure 分支发布不可接受的 successor / 不退预算 |
| 3 | 真实 provider 执行模型 | **A：进程内 HTTP**（复用 v15 `StdlibTransport`，不引入 provider 子进程） | transport 已提供绝对 deadline、10 MiB cap、不跟随 redirect；杀子进程并不能消除「请求是否已到达远端」的歧义（D1/D4 已披露） | 高 | 对抗测试证明进程内 transport 能越过总 deadline、遗留不可回收资源，或出现「key 不得与 DB 凭据同进程」的硬要求 |
| 4 | 闭包操作阈值 | **A：合并阶梯** ≤128 进 R/P / 384 预警 / 448 停止增长并留证 / 512 内核边界（480 并入 448） | 512 只是零写入硬边界，install→历史 host effect 边与对象不删除使闭包单调增长，硬失败前需要可操作的预警与停止线 | 中高（待 G8-C1/C2 实测基线与斜率） | 实测表明必需固定用例无法保持 ≤128，或 448 相对实测斜率不足以在触 512 前安全停止 |
| 5 | 三条新检查是否进入 closeout 清单（11/11 → 14/14） | **B：保留已冻结的 11/11**；G8/G9/G10 定位为**各里程碑必跑的 extension check**，必须实跑并在 matrix/ledger/README 记录「通过 / 失败 / 未运行」三态，但不改历史 closeout 数字、不称 closeout gate | 11/11 是已冻结并发布的验收基线；改写它是发布政策变更而非工程必然。**这是范围/口径决策**：三个 Oracle 中两个取保守默认 B，一个取 A 但自标为部分范围决策且置信度仅中 | 高（对「属于范围决策」的判断） | 用户或发布负责人明确批准重基线为 14/14，并接受此后每个里程碑都必须实跑三条的维护成本——那时只需改文档口径 |

裁决 5 的**可翻转性**：本计划按 B 落稿；若用户要 A，改动仅限文档（closeout 清单、矩阵、README 加一节），代码与测试不变。裁决 1–4 的落实条件已写进对应章节（G8 逐函数断言信封/字段闭集/类型/游标/空集；G9-D 钉死 run 终态与 token 退还；保留外呼前全连接 IDLE 断言；阈值不得把 G8 判红）。

### 已纠正的草稿错误（相对 pre-plan 阶段的认识）

| # | 草稿说法 | 纠正 | 依据 |
|---|---|---|---|
| 1 | host 只读面「推荐直接 GRANT 给 `v24_service`、全安装范围」 | 改为 **scope-owner-or-admin** 授权，与 `recoverable_effects` 现有规则一致；admin 可发现/读全部 scope，service/operator 只能读自己拥有的 scope；部署上 host 用 admin/owner 连接做发现与恢复、用 `v24_service` 连接做 claim/settle | `49_recovery.sql:26-32,298-302`；`47_verbs.sql:45-51,111-114` |
| 2 | 真实 provider 测试「推荐保持非 gate」 | 分层：**脚本化 transport 的映射/unknown/lease/崩溃测试成为各里程碑必跑的 extension check**（设计 §9.1 允许 Fake 适配器，无网络），**真实网络与第二语言广度保持 opt-in**（`credentials_absent`/`toolchain_absent` → exit 2，不算通过） | `docs/designs/v24-pg-agent-2026-10-22.md:442-448`；`AGENTS.md:73-75` |
| 3 | 「`max_tokens ≤ 4096` 即可保证不超预算」 | 错：`max_tokens` 只限制 completion，DB 校验的是上报的**总** usage。改用「保守准入估计（messages/tools 的 UTF-8 JSON 字节 + framing 余量）定 `max_tokens` + 原样上报真实 usage」，超 reserve 由内核转 semantic unknown | `48_loop.sql:568-600`；`v15/provider/deepseek.py:332-336` |
| 4 | 「每次 activate 都产生 host effect，闭包线性增长」 | 需实测而非预设：`fiber_control` 是纯 DB 命令，没有宿主进程回调；要测实际新增对象数与斜率 | `45_capability.sql:130-155`；`30_advance.sql:318-527` |
| 5 | 「G 是读任何 v24 表之前的第一把锁」 | 窄路径不成立：`command_install` 的 owner 存在性检查先读 `v24.fibers` 才取 G。登记披露，不改冻结代码 | `30_advance.sql:205-213` vs `:247` |
| 6 | 插件测试「缺 toolchain 时 SKIP/exit 2」即可 | 保持 exit 2 口径，但**明确 P 段多语言未完成**：Python extension check 绿不等于多语言完成；最终验收必须同时留三份证据——G10 Python 通过、`test_node.py --node` 显式 exit 0、以及 `plugin_smoke.py --multilingual-smoke` 的同一 run 双语全链 | `v13/pi_ports/README.md:13`；`v13/read_tools/README.md:18` |

### M-H：host 只读工作发现面（`v24/sql/49_host_reads.sql`）

**新文件位置**：`49_recovery.sql` 之后、`50_permissions.sql` 之前。所有公开函数统一约定：

- `STABLE SECURITY DEFINER`、`SET search_path = pg_catalog, v24`；不取 G、不写表、不调 `advance`、无动态 SQL、禁止 `SELECT *` 作为公开投影。
- 只返回已提交数据；单次调用只有一个 MVCC snapshot，跨页不保证一致快照。
- 授权失败统一返回 `not_found_or_denied`（与 `poll` 闭读信封同形，不泄露存在性）；参数形状错误返回 `invalid_args`；空结果成功返回空数组/零行，不抛异常。
- **返回信封冻结**：列表函数统一 `{"v":1,"items":[…],"limit":<effective>,"has_more":<bool>,"next_cursor":<obj|null>}`；point 函数（`host_effect`/`host_request`）返回 `{"v":1,"effect":{…}}` / `{"v":1,"request":{…}}`；`next_cursor` 的形状按函数固定（scope/install/fiber/pin 用 `{"<id_col>":…}`，run/effect 用 `{"created_at":…,"<id_col>":…}`）。每个 item 的键集合是闭集，G8 逐函数断言成功信封、拒绝信封、键闭集、JSON 类型、游标与空集行为——这是选择 jsonb 而非 `RETURNS TABLE` 后必须补回的编译期约束。
- 原始 `request`/`outcome` **不脱敏**：tool args 与 model input 就是执行输入，脱敏会使 host 无法执行；审计隔离靠 `host_*` 独立 GRANT 与 scope 授权，不另建脱敏副本。

**九个公开函数**（另加一个不 GRANT 给协议角色的内部 helper `host_scope_allowed(p_scope uuid)` 集中授权条件，避免九个函数复制规则；它仍计入 DEFINER allowlist）：

| 函数 | 关键参数 | 用途与返回要点 |
|---|---|---|
| `host_scopes` | `p_scope uuid DEFAULT NULL, p_after uuid, p_limit int DEFAULT 64` | `NULL` 列全部可见 scope 按 `scope_id`；非 NULL 只返回该 scope，不可见即拒。item：`scope_id,parent_id,root_id,owner_principal,close_requested_at,closed_at`；含 closing/closed 供重启发现 |
| `host_runs` | `p_scope, p_after_created_at, p_after_run_id, p_limit` | 该 scope 全部 run，item 直接复用 `run_projection(run_id)` 的完整投影（不复制字段清单），解决重启后只有 `emitted[]` 的问题 |
| `host_effects` | `p_scope, p_after_created_at, p_after_effect_id, p_limit` | 当前 work 面：仅 `status IN ('ready','claimed')` 且 kind ∈ 五种外部 kind；item 含原始 request、当前 claim token、lease、cancel flag；不含 command/settled 历史 |
| `host_run_effects` | `p_run, p_after_created_at, p_after_effect_id, p_limit` | 该 run 全部 `model_call`/`tool_call`（含已结算历史），用于重建 turn/batch/tool 结果与识别 ready successor |
| `host_effect` | `p_effect uuid` | point lookup；claim 后重读 committed request/token/lease、settle 前对账；只允许五种外部 kind |
| `host_scope_installs` | `p_scope, p_after, p_limit` | 全状态 install 行：`identity,version,manifest,manifest_digest,requires,provides,artifact_digest,adapter_digest,state,dispose_effect,disposed_at`；三个 digest 统一输出小写 hex |
| `host_install_fibers` | `p_install, p_after, p_limit` | `fiber_id,control_seq,current_episode_id,want_on,…`，提供 `fiber_control` 所需的两个入参，替代 owner 直读 |
| `host_run_pins` | `p_run, p_after, p_limit` | `consumer_type='run'` 的 pin + slot descriptor + digest + `released_at`（含派生 `provider_install_id`，见下）；host 只把未释放 pin 当当前 model tools。**必需**：`resolve` 返回「现在可解析的 slot」，不能替代 run 启动时冻结的 pin |
| `host_request` | `p_request_key text` | 只读**当前 principal** 的 request（固定 `principal_id(session_user)`，无 principal 参数，admin 也不绕过）：`request_bytes_base64`、`request_digest_hex`、`response`、`effect_id`；用于 lost-response 重试前比对 canonical bytes |

**公共 item 键闭集（G8 逐项断言，缺一即失败）**：

- `effect` item（`host_effects`/`host_run_effects`/`host_effect` 共用）：`effect_id, parent_effect_id, ordinal, scope_id, run_id, fiber_id, episode_id, pin_id, epoch_no, generation, kind, status, replay_policy, attempt_no, fence, claim_owner, cancel_requested, request, outcome, lease_until, resource_quiesced_at, created_at, settled_at`。**`parent_effect_id` 与 `ordinal` 是承重列**：工具回执按「parent model effect + ordinal」关联（见 M-P），continuation 身份也依赖 parent/最大 ordinal 关系（`48_loop.sql:512-523`），缺了它们 `host_run_effects` 无法支撑本计划自己的 journal 重建规则。
- `install` item 追加 `owner_principal, created_by_effect`（表里存在，`10_schema.sql:211-219`），便于 host 解释授权归属。
- `host_run_pins` item 必须含派生列 `provider_install_id`（`pins.provider_fiber_id → fibers.install_id`，`10_schema.sql:125,163`）：`ApprovedAdapterRegistry.lookup` 的匹配键是 install 的 `(identity,version,manifest_digest,artifact_digest,adapter_digest)`，没有这一列 host 就无法从 pin 定位该查哪个 install；反向按 install 扫 fiber 更贵，不作默认。

**分页约定**：`p_limit` 为 `NULL`/负数按 0、>64 截为 64、默认 64（与 recovery「调用方不能放大扫描」同风格）；取 `effective_limit+1` 行判 `has_more`；游标为严格 `(created_at,id) > (after_created_at,after_id)`；`next_cursor` 仅在本页最后一行之后确有下一行时返回；host 每轮空闲后从 NULL 游标重新全扫，重复项按 effect/run/install id 去重——分页不是持久 cursor，扫描期落在 cursor 之前的新行下轮可见。

**分页边界冻结**：① `limit=0` 返回 `items=[]`、`has_more=false`、`next_cursor=null`（没有「最后一行」可构造游标）；② 时间游标参数必须**成对**为 NULL 或成对非 NULL，否则 `invalid_args`；③ UUID-only 游标函数用 `id > after_id`；④ 单页内 `has_more` 为真时 `next_cursor` 必非空，为假时必为空。

**ACL 与加载器（必须同一原子步骤完成）**：九个公开函数 `GRANT EXECUTE` 给 `v24_admin, v24_service, v24_operator`；`host_scope_allowed` 不公开 GRANT；DEFINER 数组 7→17；授权入口 18→27。**`50_permissions.sql` 的 `prosrc` 正则扫描包含注释**，因此新文件的函数体与注释都不得出现 `insert`/`update`/`delete`/`pg_advisory*` 等词，说明性文字放到函数体外。**DEFINER 白名单必须保持按 `proname` 排序**：`50_permissions.sql:63` 用 `array_agg(p.proname::text ORDER BY p.proname)` 与冻结元组逐一比较，新增 10 个 DEFINER 要按名字插进正确位置，不能追加在尾部。

### M-H：G8 对抗性 extension check（`v24/s9/`）

新入口 `uv run python v24/s9/test_g8.py`（无参数跑全部用例，退出码仅 0/1，`--only` 只作增量检查点不计 closeout）；只 import 共享夹具与既有 helpers，**不另建 `setup_db.py`**。

**只读面用例**

| ID | 覆盖 | 必须断言 |
|---|---|---|
| `G8-H1` | `host_scopes` | owner 只见自有 scope；admin 全见；显式指定非 owner scope → `not_found_or_denied`；closing/closed 均可发现；UUID 分页、limit 0/负数/>64、空集 |
| `G8-H2` | `host_runs` | item 与 `run_projection` 完全相同；`(created_at,run_id)` 严格排序；跨页无重复；非 owner service 拒绝；空 scope 返回空列表 |
| `G8-H3` | `host_effects` | 只含 ready/claimed 的五 kind；原始 request 与 owner fixture 逐字节等值；command/settled 不泄漏；claim token、lease、cancel flag 正确 |
| `G8-H4` | `host_run_effects` | model/tool 全历史可见；batch 顺序稳定；其他 run 不可见；错误信封 |
| `G8-H5` | `host_effect` | claim 后另一 committed 连接读到同 token/request；不存在与非 owner 不可区分；settled outcome 可读 |
| `G8-H6` | `host_scope_installs` | 全状态、manifest、requires/provides、三个 digest 的小写 hex、state/dispose 字段精确 |
| `G8-H7` | `host_install_fibers` | `fiber_id/control_seq/current_episode_id` 与公共 `fiber_control` 后的 committed 状态一致 |
| `G8-H8` | `host_run_pins` | descriptor 与 slot 一致、digest 与 pin 一致、release 后仍可读但 host 可识别；非 owner 拒绝 |
| `G8-H9` | `host_request` | base64 解码等于 canonical bytes；`response` 等于首次 response；其他 principal 被拒；重放不增行 |
| `G8-H10` | ACL/只读共性 | 17 个 DEFINER 名精确（按 `proname` 排序）、27 个 GRANT 语句、逐角色 EXECUTE 集合精确（**admin 26 / service 27 / operator 27**）、`host_scope_allowed` 无 GRANT、admin 仍被拒 `install`、全部 STABLE/固定 search_path/无 PUBLIC/协议角色仍零表权；直接查 `pg_proc.prosrc` 应用同一禁词正则（防注释漂移）；每个 scoped 函数都有非 owner service 拒绝断言；调用前后十表 fingerprint 不变，reader 无 advisory lock、不进 `pg_blocking_pids` |
| `G8-H11` | held-G 读 | 另一事务持 G 且有未提交变更时，九个读函数仍能完成且只看到已提交 snapshot；写调用仍受 G 串行 |
| `G8-H12` | 分页与并发 | 多页扫描无静态数据遗漏/重复；并发插入落在 cursor 前时下一轮可发现；状态改变造成重复时 worker 不重复执行 |
| `G8-H13` | 未脱敏 `request` 的页尺寸 | 以每项约 1 MiB 的 ASCII model `input` 夹具测量 64 项页；D1 已由 `v24-post-closeout-followup-2026-10-25.md` 收口：保持 64 项。67,107,712 B 仅为该夹具序列化尺寸，不是字节/内存上限；advance 的 1 MiB outcome body 校验不约束 request |

**闭包增长实测（`G8-C1`/`G8-C2`）**——fixture-only closure probe，**不向产品 SQL 增加测量函数**。`30_advance.sql:320-527` 是 `advance` 函数体内的一段，引用 PL/pgSQL 变量 `p_effect_id`、`v_class`、`v_body`（赋值在 `:126-128`）并以 `SELECT … INTO v_closure` 结束，**不能整段原样拷贝成可执行 SQL**。因此 probe 必须二选一并在 README 写明选了哪个：(a) fixture 自有的 PL/pgSQL probe，复刻这些声明与赋值后返回 `v_closure`；(b) 精确参数化重写，把 effect/class/body 作为入参并去掉 `INTO`。无论哪种，源守卫必须哈希**完整提取段**（不只是 install→effects 边），内核闭包源码变化时守卫失败要求人工同步，而不是继续拿旧公式作证；真正的语义 oracle 仍是真实 `advance` 的 512/513 行为。定义 `H` = 目标 install 上除当前 claim 目标外的历史 host effect 数，`C(H)` = 同一递归 CTE 后八类实体去重总数，`M(H)=512-C(H)`。

- `G8-C1`（斜率）：`H=0,1,2,4,8,16,32` 各采样，断言**相邻实测采样对之间**斜率为 1（即每个采样点都实测 `C(H)`，不断言未测量的 `H-1`；若跳过某档就同时断言该档的 `C`），新历史 effect 不引入额外未去重实体；每采样点用 service 真实 `advance(claim)` 后 rollback，`C(H)≤512` 必须返回 committed token 且不执行任何 IO。不做耗时断言。
- 大样本构造方式：用**少量公共路径历史 + owner seed 的已结算同形行**（只引用同一 scope/install，不引入新 run/episode/pin/parent 边）把 `H` 推到边界附近；仅靠公共执行无法在合理时间内构造过界 fixture，禁止用 owner 插入冒充公共路径证据。
- `G8-C2`（精确边界）：按实测基线 `B=C(0)` 构造 `H_ok=512-B`（`C=512`，普通 claim 成功）与 `H_bad=513-B`（返回 `retry_with_closure`，十表逐字节不变、无 token、重试仍拒）。输出实际 `B,H_ok,H_bad` 与余量；**不把「512 个 host effect」误写成通用阈值**。
- 操作阈值阶梯（本次验证用，不是数据库新策略；512 才是内核边界）：进入 R/P 固定用例前相关闭包 **≤128**；**384** 报告余量预警；**448**（余量不足 64）停止继续增长并保留证据；必需流程任一普通 claim 返回 `retry_with_closure` 或公共路径稳定永久 `retry_with_closure` ⇒ **停止 R/P 发布验收，另开设计修订**。禁止通过删历史、绕过 `advance`、提高 512 或增加第二条 claim 路径「修复」。
- 两个必须同时成立的口径：① **闭包是在 G 之下、所有写者串行化后计算的**，因此返回 `retry_with_closure` 是真实信号（越界或悬空引用），不是瞬时锁冲突，记录时必须带上闭包大小；② **阈值是里程碑停止规则，不是 gate 断言**——阈值被触发不得把 G8 判红，G8 只断言内核事实（斜率与 512/513 精确边界），512/513 的构造只允许发生在隔离的 C2 fixture-only 实验里。
- 公共路径增长实验：正常 install/prepare、连续 32 次 `fiber_control(on/off)`、既有 unknown→新 key inspect 分支按 1/8/16/32 次推进，记录 host effect、reconcile effect、episode、pin 数与每次 claim/每条生命周期命令的闭包，分别列出斜率；无法继续生成 inspect 时记录实际返回，**禁止用 owner 插入补成「公共路径证据」**。

**其余对抗性与债务用例**

| ID | 场景与断言 |
|---|---|
| `G8-L1` | `lease_ms=1` 与 `300000` 可 claim；0、负数、300001、非整数均 `invalid_args` 且零写 |
| `G8-L2` | live lease 再 claim → `deferred`/`claim:null`；model/tool 过期 → `stale_claim` 且 attempt/fence 不变；host kind 过期 re-claim 使 attempt/fence+1、旧 token 失效 |
| `G8-L3` | 过期但尚未 sweep 的原 token late settlement 仍被接受；先 `command_recover` 转 unknown 后迟到 receipt 走既有冲突路径，不能复活 run |
| `G8-R1` | 不发命令时过期 claim 状态不自动变化；一次 sweep ≤16；第 17 行只体现 `has_more`；`manual` 只计 `manual_debt`；catalog 无 queue/job/cursor 对象 |
| `G8-D1a` | **补 D-S6-12 的本体**：owner seed 一个**已关闭 scope + 真实过期、已 claim、非 manual 的候选 effect**（台账 `docs/reviews/v24-deviation-ledger-2026-10-23.md:168,406` 缺的正是「closed-scope 非空候选」这一状态，不是「无候选 noop」）；跑 `command_recover` 并断言其精确 applied/terminal 效果，且不复活 scope/install/fiber/run。若该合成 fixture 被有意拒绝，**D-S6-12 保持开启**，不得记作已补 |
| `G8-D1b` | 附加：经公共生命周期关闭一个有 install/effect 历史的非空 scope 后执行恢复；断言无候选时仅记录 recovery command/request，不复活 scope/install/fiber/run；明确这是合成 fixture，不声称公共 API 必然产生该状态 |
| `G8-D2` | 补 D-S8-7：两个 `agent.spawn`、spawn+普通 tool、spawn+`final`、spawn+`interaction` 四种组合均 `invalid_outcome`、十表零写、原 claim 不变；同 key 后续合法 spawn 不被污染 |
| `G8-W1` | worker 事务超时配置、IO 前两连接 IDLE 前置、以及「存在在飞工作时完全不 sweep」 |

**无网络三重守卫**：夹具前对 `v24/s9/*.py` 做 s6 风格静态 import 扫描；测试期间 s4 风格 `socket.connect`/`create_connection` monkeypatch；扫描 `49_host_reads.sql` 的 `http|dblink|pg_sleep|socket` 与 DDL 关键词，并确认目录仍恰十表、无视图、无扩展。

Starvation/fairness **不写通过用例**：D-S7-2 原样保留，README 明确本计划没有活性证明。

### M-R：host worker 与 durable journal（`v24/host/`）

**组件**：

| 文件 | 职责 |
|---|---|
| `v24/host/db.py` | `HostDB`：同步 RPC 封装九个读函数 + `claim/settle/recover` 调既有写入口；所有方法返回前 commit 或 rollback |
| `v24/host/worker.py` | `HostWorker`：`run_once(scope) -> progress`、`run_until_idle(scope, max_rounds)`；单线程、最多一个在飞 effect |
| `v24/host/journal.py` | `HostJournal`：持久化执行边界、完整请求/响应、transcript 与 settlement；单写者 |
| `v24/host/process_io.py` | 有界进程执行器：固定 argv、输入/输出有界、deadline 到期杀进程组并 reap。**仅插件路径使用**（provider 走进程内 HTTP，见 Approach 裁决 3） |
| `v24/host/deepseek.py` | v24 专用 DeepSeek 序列化/解析/映射/租约 |

**身份分工**：`control_conn` 用 admin 或 scope owner（九个读函数 + `command_recover`），`service_conn` 用 `v24_service`（claim/settle）——与当前「claim/settle 仅允许 service」一致，不为读取放宽写侧。生产 host 禁止 owner 表直读，work 来源只有九个读函数与 `recoverable_effects`。

**会话设置**（客户端会话级，不改数据库默认值）：`READ COMMITTED`、`statement_timeout=30s`、`lock_timeout=5s`、`idle_in_transaction_session_timeout=5s`。`statement_timeout` 不能终止已 idle-in-transaction 的后端，故必须同时设 idle 超时。每个外部操作前断言所有 host 连接 `TRANSACTION_STATUS_IDLE`。

**扫描与恢复算法**（每轮）：① 先重交 journal 已有完整结果、DB 仍显示相同 `claimed attempt/fence/owner` 的 settlement；② 无在飞操作时按 scope 轮转分页发现；③ 对有过期候选的 scope 调一次 `command_recover(…,16)`，本轮最多一次 sweep；④ 发现 ready 的五种外部 effect，先 host 资源操作后 model/tool，同类按 effect UUID；⑤ 取快照并验证 journal/registry，claim、commit、复查 token 与剩余租约；⑥ 执行一次外部操作、持久化完整结果、settlement；⑦ 扫描耗尽返回 idle。**不能先过滤 `recoverable_effects` 再认为 `command_recover` 会避开在飞项**（wrapper 自行发现候选，`49:178-245`），本版以串行执行 + 「有在飞项时完全不 sweep」解决，不改 recovery ABI。

**重启对账规则**：

| 最后持久证据 | 行为 |
|---|---|
| 无 `dispatch_started` | 重读数据库资格；满足原 token、租约与前置条件才可开始 |
| 有 started、无 finished | **不再次执行** model/tool。若 lease 仍 live：隔离该操作（不重发、不 sweep），等其自然到期或由管理命令处理；lease 已过期：经既有 `command_recover` 收敛为 unknown。**与 `G9-J3` 保持一致，不得在重启时立即打成 unknown** |
| 有 finished、未确认 settlement | 重交保存的同一 outcome，绝不再次外呼 |
| 数据库已终结 | 对比 outcome；一致则确认，冲突则停止该 effect 并保留证据 |
| replay_safe 资源操作跨崩溃 | 按 reservation 查 journal/资源证据；结果不确定报 unknown，交既有 inspect 路径 |

**journal 格式**：host 私有目录（`0700`）/文件（`0600`），启动 POSIX 文件锁防同目录第二 writer（**不是**数据库租约或跨主机接管协议）；追加 JSONL，每条含 `v,seq,event_type,effect_id,run_id?,request_digest,claim?,payload`；`event_type` 闭集 `command_prepared|command_committed|effect_prepared|dispatch_started|dispatch_finished|settlement_committed`；`dispatch_finished.payload` 含原始 provider/tool 响应、完整映射结果与待提交 outcome；执行前与结果产生后均 fsync，首次创建文件后同步目录；末尾残缺记录按未完成执行处理，内部损坏则停止该 journal 的执行。规则：request/result 用 canonical JSON，写入后读回比对；**API key、Authorization header、DSN 不写入 journal 或日志**；journal 不保存 ready 队列/recovery plan/与 DB 并列的领域状态，effect 是否可 claim/settle 永远以 PostgreSQL 为准；未知 journal version 直接失败，不静默清空。

**实现备选（未采用）**：SQLite 单文件 + `runs/messages/operations/metadata` 四表同样满足上述全部要求。选 JSONL 的理由是依赖更少、可人工审计，且「单写者 + fsync + 未知版本即失败」不依赖存储引擎；若实施时改用 SQLite，上述规则必须逐条保持不变。

### M-R：v24 DeepSeek adapter（`v24/host/deepseek.py`）

**复用但不修改**：`v15.provider.deepseek.StdlibTransport`、`ProviderRejected`/`ProviderUncertain`/`detail`、`compute_cost`/`is_peak`/`PRICING_REVISION`。**不复用** `_classify`、`DeepSeekProvider.complete`、`v15.worker`——v24 自建消息/tools 序列化、响应解析与 v24 映射（v15 只接受 `system/user/assistant` 且 `content` 必须 str，`deepseek.py:323-331`）。deadline 与注入 transport 用同一单调时钟。

**固定约束**：model 仅 `deepseek-flash`；`0 < timeout_s ≤ 239`（为 claim 提交与剩余租约检查留余量）；每次请求 `stream:false`；**不使用** `tool_choice:"required"`（thinking 模式 400）；不发送未文档化的 `parallel_tool_calls`；真实入口固定官方 HTTPS 根 `https://api.deepseek.com`，不读 `OPENAI_API_URI`，不自动尝试 `/v1` 后重发。

**host 输入方言**（DB `input` 仍不透明，host v1 只解释可选键，其余原样留作业务数据）：`{messages:[{role:"system|user",content}], max_output_tokens, requires}`。首个 start/spawn model 用 `messages` 初始化 journal，缺失或形状不合法是**未开始外部 IO 的 failure**。continuation/steer/respond **不从 DB `state` 重建消息**（`state` 恒为 `{}`），而从 journal 读；steer instruction 与 respond response 作为新 user message 追加。

**tool descriptor 与命名映射**：live run pin 的 descriptor host 方言为 `{v:1, tool:{description, parameters:{type:"object"}}}`；provider 侧工具名用确定性安全映射（sanitized/truncated key + `_` + sha256 短前缀），完整映射随该 model operation 写入 journal，response 只通过映射还原 v24 pin key；未知名、映射碰撞、缺参数 object 都不送 DB。`agent.spawn` 与 `interaction` **不在 R 段暴露为真实 provider 工具**（其 DB 合同继续由 G7/G8 Fake 证据覆盖）。

**Provider → v24 映射**（`wall_ms` 为一次 complete 的单调耗时，`tokens = prompt_tokens + completion_tokens`）：adapter 内部记录 `ProviderReply`，字段闭集为 `finish_kind, content, tool_calls, prompt_tokens, completion_tokens, wall_ms, reasoning_content, response_id, provider_metadata`——它只进 journal，不直接写 DB。

| Provider 结果 | v24 outcome |
|---|---|
| `finish_reason='tool_calls'`，1–16 条合法 tool_calls | `success`，result 含按 provider 顺序的 `tool_calls:[{key,args}]` + `usage`；content 为字符串时可同时放 `text` |
| `finish_reason='stop'`，无 tool_calls，content 为 string | `success`，`final:{text:content}` + `usage` |
| `finish_reason='length'`（及 aborted/未知 finish） | `unknown`，result 仅含可验证 `usage`；**不把截断文本当 final**，不自动续写 |
| 合法响应但 arguments 不是 JSON object / 工具名未知 / 缺 tool call id | **`failure`**，用实际 usage；不创建 tool successor。最小合法 result 形状为 `{"text":null,"usage":{"tokens":<真实值>,"wall_ms":<真实值>}}`，**不得含 `tool_calls` 或 `final`**；原始 provider 响应、原因、response id 与 reasoning 只写 journal。同一路径还覆盖：>16 条 tool_calls、`finish_reason='tool_calls'` 但零条合法调用、provider 工具名映射碰撞、**重复的 provider tool-call id**。**host 不得把内核会判 W0 `invalid_outcome` 的东西送给内核**——那会让 claim 保持 live 而既不执行也不收口 |
| preflight 失败、lease 不足、本地 request 形状错误且尚未 HTTP | `failure`，tokens=0，transport 调用次数必须为 0 |
| 明确 rejected（400/content_filter） | `failure`；无自动重试 |
| timeout、5xx、429、3xx、连接中断、无法信任的 usage/响应结构 | `unknown`；不重发请求 |
| 响应 envelope 自相矛盾（`finish_reason` 与 message 内容不一致等） | `unknown`：响应整体不可信，不能按任一分支解释；不重发请求 |
| `tokens > reserve.tokens` | 保留映射后的 success/failure 与**真实** usage，由内核转 semantic unknown；host 不私自截断 tokens |

`reasoning_content`、provider response id、pricing/cost 元数据全写 journal，不放进 result。下一轮带 tools 的请求必须回传 journal 中所有历史 assistant reasoning 与 tool message；缺失时**不得静默删除历史**，应失败并停止该 run 的后续 provider 调用。

**Token 与租约**：真实请求要求 `reserve.tokens > 0`，零 reserve 不外呼；默认 completion cap 256、配置上限 512；发送前按完整 messages/tools 的 UTF-8 JSON 字节数加 256 framing 余量做保守准入估计，从 reserve 扣除估计后定 `max_tokens`（该估计不宣称是 DeepSeek tokenizer 的形式化上界）；响应真实 `prompt_tokens+completion_tokens` 原样上报。租约 `lease_ms = min((ceil(timeout_s)+60)*1000, 300000)`；HTTP 前用 `host_effect` 重读 committed lease，要求 `remaining_lease_ms ≥ timeout_s*1000 + 5000`，不足则不发送 HTTP、提交未开始 failure，**不自动重新 claim 或续租**。外部 IO 超过 lease 后，只要尚未被 sweep，原 token 的 late receipt 仍可提交（host 串行结构保证本进程不会同时 sweep 自己）。
- **deadline 不是硬上界（必须登记为披露）**：`StdlibTransport.post` 在打开连接时用「剩余时间」设置一次 socket timeout（`v15/provider/deepseek.py:106-110`），`read_bounded` 只在每次读前后检查 deadline（`:71,83`）——慢速滴灌响应可超出约 2× `timeout_s`，DNS 解析也不被 socket timeout 覆盖。这不影响正确性（结算不查 `lease_until`、host 不在飞时不 sweep、挂死 host 经 journal 收敛为 unknown），只影响活性：因此「剩余租约 ≥ timeout + 5s」是**启发式前置检查，不是边界保证**，写入偏差台账。

### M-R：G9 脚本化 provider extension check 与 opt-in 入口

`uv run python v24/s10/test_g9.py`（建议以 `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI UV_NO_ENV_FILE=1` 前缀运行）。transport 是测试内 `ScriptTransport`，按脚本返回 `(status,raw)` 或抛异常，并记录 body/header/call count；patch v15 `build_opener` 与 `urllib.request.urlopen` 为 `AssertionError`（默认构造真实 opener 也算失败）；静态扫描 `v24/s10/*.py` 并断言 worker/journal 不 import 网络库；退出码 0/1。

| ID | 核心断言 |
|---|---|
| `G9-A` | messages/tools/`max_tokens` 序列化；安全工具名可逆；不发送 `required` tool_choice；assistant reasoning、tool_call_id、tool response 全历史进入下一请求 |
| `G9-B` | stop→`final`；tokens=两部分之和；真实 kernel settlement 后 run completed；response id/reasoning 只在 journal |
| `G9-C` | 两个 tool_calls 保序并形成一个 batch；工具结果后恰有一个 continuation model；无第二个未结算 model |
| `G9-D` | 非法 arguments / 未知工具名 / 缺 tool call id / **重复 provider tool-call id** → `failure`、零 tool effect、无第二次 HTTP；**互相矛盾的 finish/message 组合**（如 `finish_reason` 与 message 内容不一致）→ `unknown`（响应不可信）；畸形 provider envelope → `unknown`。每条路径断言 run 终态、token 处理与 HTTP 次数精确 |
| `G9-E` | length→unknown→`blocked_unknown`、不退 tokens、无自动续写；over-reserve 由内核转 semantic unknown |
| `G9-F` | preflight/400/timeout/429/5xx/3xx 分类正确；每条异常路径的 HTTP 次数、outcome class、run 终态与预算精确 |
| `G9-L` | `timeout_s>239` 拒绝；`lease=timeout+60`；剩余 lease 不足时零 HTTP；IO 前两个连接必须 IDLE；人为打开事务时不得进入 transport |
| `G9-J1` | HTTP 完成、journal 已落结果、settle 前模拟进程崩溃；重启零新增 HTTP，同 token 提交同一 receipt |
| `G9-J2` | 重启先恢复 unknown 后，旧 journal 结果不能复活 run 或产生 successor |
| `G9-J3` | HTTP 已发出但无 durable result：重启不重发；到期后 recover→unknown |
| `G9-R` | run/recover 只经九个读函数与 `command_recover`；无 recovery 表/queue；有界轮次不构成自动公平性承诺 |

**opt-in 入口** `uv run python -m v24.host.smoke`（非 gate）：无 flag → `not_requested` 退出 0，不构造 adapter、不开库；`--real-provider-smoke` 无 key → `credentials_absent` 退出 2，不构造 adapter、不开库；有 key → 建 disposable v24 fixture（host 只用协议 LOGIN，owner 仅建库与核验证据），执行一次固定短文本 `start → 真实 model → final`；已开始网络后失败 → 退出 1，**不降级为 SKIP**；stdout 仅打印 endpoint host、model、effect/run id、usage、finish 与结论，不打印 prompt、content、reasoning、key 或 Authorization；key 只从 `DEEPSEEK_API_KEY`/`OPENAI_API_KEY` 读，不落 `.env`/DB/journal/argv；成功删除私有 journal，失败保留路径（仍受 0600 保护）。e2e 用无 tools 的确定提示，避免把「模型是否自愿调用工具」当验收条件。`/v1` 路径、thinking+tools 历史要求与当前模型可用性经该入口实测复核；若官方端点拒绝当前 base，只改 v24 adapter 配置，不改 v15 文件。

### M-P：最小多语言插件（`v24/s11/`）

**Approved adapter registry**（`v24/host/registry.py`）：不可变 `ApprovedAdapter(adapter_id, language, identity, version, manifest_digest, artifact_digest, adapter_digest, descriptor_digest, argv, cwd, environment_allowlist, tool_key, description, parameters, timeout_ms, stdout_limit, stderr_limit)`，由启动代码构造后只读。匹配键是 install 已有的 `(identity, version, manifest_digest, artifact_digest, adapter_digest)`；匹配后才得到固定 `adapter_id/language/argv/cwd`。**argv 只来自 registry**，不从 manifest、tool args、descriptor 或模型输出拼接，不调 shell；无匹配、digest 不符、路径不是预期常规文件都在 spawn 前拒绝。不新增 manifest 顶层键、SQL 列或 revision registry——利用现有不可变 identity/digest 字段即可证明「host 批准的字节与 adapter」。

**`descriptor_digest` 必须被执法**：spawn 前要求批准项的 descriptor 规范字节/digest 与**该 run pin 冻结的** `descriptor`/`descriptor_digest` 相等，不等则**在创建进程前**拒绝。否则 registry 条目可以描述与冻结 pin 不同的工具字节/schema 却通过全部既有 digest 检查。G10 相应地拆成三个独立负例（artifact digest 不匹配 / adapter digest 不匹配 / descriptor digest 不匹配），各断言零 spawn，而不是一条笼统的「digest 不匹配」。

**生命周期边界**（显式固定，不引入隐藏步骤）：

```text
install
  → host_prepare：验证批准的字节、建立 reservation 证据
  → installed
  → fiber_control(on)：DB 发布 episode/slot（无事务外回调，不 spawn 常驻进程）
  → start(requires=[tool key])
  → Fake model 发出 tool call
  → host_run_pins 读取冻结 descriptor
  → spawn invoke + settle tool
  → Fake continuation model 返回 final
  → fiber_control(off)
  → dispose
  → spawn host_release，必要时 inspect
  → install disposed、episodes closed、slots/pins released
  → scope close 收敛
```

模型继续用 Fake，P 段不引入真实 provider 变量。

**进程协议与错误映射**（`v24/host/line_json.py`，沿用 v13 帧契约而非直接调用其桥）：one-shot 子进程、无 shell、argv 数组、固定 cwd、最小环境、每次调用独立 reaping；请求一帧 JSON（`v:1`、operation、reservation、args）；成功帧 `{"ok":true,"result":"<含 JSON object 的字符串>"}` exit 0；已知工具错误 `{"ok":false,"error","message"}` exit 3；stdout 上限 64 KiB、stderr 上限 16 KiB、默认 deadline 5s，超限或超时终止进程组并 reap，stderr 不进普通日志。

| 插件结果 | tool_call receipt |
|---|---|
| exit 0，result 解码为 object | `success` + `{status:"ok",output:{…},usage:{wall_ms}}` |
| exit 3 | `failure` + `{status:"error",output:{code,message}}` |
| spawn 前 registry/路径/参数失败 | 未开始 failure，零进程 |
| spawn 后 timeout/EOF/坏帧/第二帧/输出超限/异常退出 | `unknown`，不自动重试 no_replay tool |

prepare/release/inspect 沿用既有 host effect 结果形状（以 `v24/s6/fake_crash_host.py:74-190` 与对应 interpreter 为可执行规范），不创造第二套 lifecycle receipt；幂等键用 effect 中既有 reservation。工具回执按 **parent model effect + ordinal** 关联（不按 key）；工具 key 可重复但 provider tool-call id 必须唯一，乱序完成时按原调用顺序构造 provider tool 消息。unknown tool 保持现有 pin/资源屏障：P 段负例必须断言 dispose 尚未完成，**不新增强制释放或 unknown→success 路径**。

**两个参考插件**：`v24/s11/plugins/echo.py` 与 `v24/s11/plugins/echo.js` 实现相同幂等操作（prepare 校验 reservation；invoke 返回 `{"echo":args,"language":"python|node"}`；release 幂等成功；inspect 按 reservation 报告既有观测）。`plugin_fixtures.py` 计算 artifact SHA256、生成现有格式 manifest、构造两个 registry entry，测试断言 registry digest 与实际文件一致。Python 与 Node 各走完整链路，而不是只测 echo 进程。

**Extension check 分层**：`uv run python v24/s11/test_g10.py` 是 M-P 必跑的 extension check（非 closeout gate，见裁决 5），默认只要求 Python 插件完整生命周期——**真实本地子进程、无网络、退出码 0/1**，覆盖成功、tool error、坏帧→unknown、**artifact / adapter / descriptor 三个 digest 各自不匹配时零 spawn**、descriptor 与冻结 run pin 不一致时零 spawn、dispose 屏障、重复 prepare/release reservation 不重复副作用。它 spawn 真实本地 Python 子进程这一点与设计 §9.1「所有 gate 外部适配器为 Fake」的字面表述存在张力：本地、确定性、无网络，且解释器必然存在，故判为可接受，但**必须在偏差台账登记为一条 §9.1 偏差**（G10 使用真实本地子进程），同时把 Goal 的口径精确为「真实**网络** IO 不进 gate」。`uv run python v24/s11/test_node.py --node` 在 Node 存在时运行同一完整生命周期 exit 0，Node 不存在时打印 `[SKIP] not_run/toolchain_absent planes=node` 退出 **2（不算通过）**，无 flag 打印 `not_requested` 退出 0。**P 段最终验收必须同时保存 G10 Python 通过与 Node 显式 exit 0 两份证据**；不能把 Python extension check 绿解释为「多语言已完成」。Go/Swift/DuckDB 不在本轮范围。

## 实施顺序（九个步骤，任何一步的前置变红即停在该步）

1. **固定基线与披露**：记录 HEAD、工作区、冻结 SQL 摘要与 pre-G 读 `v24.fibers` 披露；先跑既有 11 条 closeout，已有失败先归因，不能算作新检查的失败。
2. **原子落地 H SQL/ACL/注册**：`49_host_reads.sql`、`50_permissions.sql`、两个 loader 元组、`expected_canonical`、`v24/s1/test_g1.py` 的两处精确断言一起改；先跑 loader 与 `setup_db.py --self-check`。
3. **完成 H 对抗性证据**：跑 G8 全部用例（含 C1/C2 闭包实测与 D-S6-12/D-S8-7 补测）；触发阈值或 `retry_with_closure` 即记录并停止 R/P 相关验收。
4. **完成 DB 客户端与 journal**：用 Fake executor 验证每个提交/执行边界，特别是 started 无 finished、finished 未 settle、提交应答丢失三种崩溃窗口。
5. **完成 provider 映射与 G9**：先 ScriptTransport，再接真实 HTTP；整个检查保持无网络。
6. **完成 P Python extension check**：approved registry → prepare → activate → pin → tool → final → off → dispose 全链，加 unknown 阻塞负例。
7. **完成 opt-in 验证**：真实 provider 与 Python+Node 分开跑、分开记录；exit 2 一律未验证，不计通过。
8. **跑完整 closeout 并更新工件**：既有 11/11 复跑，三条 extension check 记录三态，更新 matrix/ledger/各 stage README。
9. **按 M-H / M-R / M-P 分别提交**：每个里程碑提交前确认既有 11/11 全绿且该里程碑 extension check 已实跑；按路径逐项 add、单次 commit、正常 push 到 `v24`；不 force、不碰 main、不用 `git add -A`。

## File-by-file impact

| 文件 | 变更及原因 | 依赖/顺序 |
|---|---|---|
| `v24/sql/49_host_reads.sql` **新增** | 9 个公开只读函数 + 1 个内部授权 helper；替代 owner fixture 表直读 | M-H 第一步，与下列三项原子完成 |
| `v24/sql/50_permissions.sql` | 新 GRANT；DEFINER allowlist 7→17；保持最后加载 | 依赖 `49_host_reads.sql` |
| `v24/load.py` | `CANONICAL_ORDER`/`SQL_LOAD_ORDER` 加入新文件 | 与新 SQL 同步，否则 manifest 拒绝 |
| `v24/s1/setup_db.py` | `expected_canonical` 加新文件；不改十表目录断言 | 与 loader 同步 |
| `v24/s1/test_g1.py` | **扩展** DEFINER 名集与逐角色 EXECUTE 名集两处精确断言（7→17；admin 17→26、service/operator 18→27），保留其余全部行为断言 | 依赖 `49_host_reads.sql` |
| `v24/s9/h_support.py` **新增** | host JSON 解包、闭包 probe、公共 fixture 构造、测试用双身份 LOGIN | 仅复用 s1/s2/s5/s6 helpers |
| `v24/s9/test_g8.py` **新增** | G8-H1…H13、C1/C2、L1–L3、R1、D1a/D1b/D2、W1 | 依赖 H SQL 全部落地 |
| `v24/s9/README.md` **新增** | 命令、证据 ID、闭包实测、starvation/自动化边界 | G8 全绿后定稿 |
| `v24/host/__init__.py`、`db.py`、`worker.py`、`journal.py`、`process_io.py` **新增** | host 包骨架与执行模型 | 依赖 H 读面 |
| `v24/host/deepseek.py` **新增** | v24 专用序列化、映射、租约配置 | 依赖 worker 接口；复用 v15 但不改 v15 |
| `v24/s10/test_g9.py` **新增** | 全 Fake transport 的 provider/worker extension check | 依赖 H/R 全部组件 |
| `v24/host/smoke.py` **新增** | opt-in adapter smoke 与 host e2e | 非 gate；G9 后手工验证 |
| `v24/host/plugin_smoke.py` **新增** | Python+Node **同一 run** 的多语言 opt-in 全链（`--multilingual-smoke`） | 非 gate；M-P 最终验收需实际 exit 0 |
| `AGENTS.md` | 在「真实套接字只允许两个入口」清单中显式追加 `uv run python -m v24.host.smoke --real-provider-smoke`，保留 opt-in/凭据/日志脱敏/无打开事务四项纪律 | M-R-4 交付物；不做静默延伸 |
| `v24/s10/README.md` **新增** | 三种时钟、退出码、日志与 unknown 边界 | R 收尾 |
| `v24/host/registry.py`、`line_json.py`、`plugins.py` **新增** | approved registry、one-shot 派发、错误映射 | 复用 worker 与 v13 帧契约 |
| `v24/s11/plugins/echo.py`、`echo.js`、`plugin_fixtures.py` **新增** | 两个参考插件与 manifest/digest/registry | P |
| `v24/s11/test_g10.py`、`test_node.py` **新增** | Python 全生命周期 extension check + Node opt-in | 依赖 H/R host worker |
| `v24/s11/README.md` **新增** | 多语言命令、SKIP 口径、trusted registry 边界 | P 收尾 |
| `docs/reviews/v24-conformance-matrix-2026-10-23.md` | 追加 G8/G9/G10 的**扩展验证状态列**（通过 / 失败 / 未运行）、真实 provider 与 Node 证据及边界；保留历史 11/11 不变 | 最终收尾 |
| `docs/reviews/v24-deviation-ledger-2026-10-23.md` | 登记：闭包单调增长与操作阈值、lease 上限与 deadline 非硬上界、无公平性（D-S7-2 保留）、host journal 信任（D1 延伸）、真实 provider 非 gate、pre-G 读 `v24.fibers` 披露、jsonb 只读 ABI 选择、非法工具调用归 `failure`、进程内 provider 选择、**G10 使用真实本地子进程的 §9.1 偏差**；关闭 D-S6-12/D-S8-7 证据缺口 | 最终收尾 |
| `v24/s7/README.md` | 保留历史 11/11 与 11 条命令不变，追加「推荐 extension check」段落及三态记录要求 | 不改历史命令、顺序与 G6 编号 |
| 本计划文档 | 记录最终实测值、命令结果与未验证项 | 最终收尾 |

**明确不改**：`v13/**`、`v15/**`、`v99/**`、既有 `v24/sql` 内核文件（除新增 host 文件与 ACL/loader 注册）、既有 G1–G7 的**行为**断言与编号。历史 `s5/test_g4.py`、`s6/recover_worker.py` 等 owner 读取继续作为 fixture 证据保留；新 worker 必须全部经 H 接口。

**两处必须显式改变的既有断言**（不是放宽，是精确同步）：

1. `v24/s1/test_g1.py:120-122` 冻结了 DEFINER 名集（`{"advance"} ∪ {resolve,run_owner,run_projection,poll,wait_check,recoverable_effects}`），`:796-806` 冻结了逐角色 EXECUTE 名集（`admin` 17 个、`service`/`operator` 18 个，`install` 只给非 admin）。新增 9 个公开 host 函数后精确值变为 **admin 26 / service 27 / operator 27**；`v24/sql/50_permissions.sql` **不断言入口总数**（只冻结 DEFINER 元组），所以「18→27」是 GRANT 语句数而非每角色统一值。M-H 必须扩展这两处断言且保留其余全部行为断言。
2. `AGENTS.md:73-75` 的真实套接字入口白名单目前只有 `v15/provider/smoke.py --real-provider-smoke` 与 `demo_v15/drive.py`（`DEMO_MODE=real`）两项。本计划新增第三个入口 `uv run python -m v24.host.smoke --real-provider-smoke`，**必须把 `AGENTS.md` 列为 M-R-4 交付物**并显式追加该入口（保留 opt-in、凭据、日志脱敏、调用时无打开事务四项纪律），否则 M-R-4 无法按本文实施，且不得把新入口当作「既有约定的自然延伸」。

## Risks and migration

**兼容与回滚**：本计划没有表/列/索引迁移，也没有既有持久数据转换；新函数是 additive read API。新代码读未加载 `49_host_reads.sql` 的旧 fixture 库时会在首次读面调用失败，必须由共享 fixture 重建数据库，不能手工补函数。旧 loader 遇到含新 SQL 文件的目录会按设计报 `unregistered v24 SQL file(s)`；回滚必须同时回退新文件、两个 loader 元组、`expected_canonical` 与 ACL，不能只删一个注册项。已创建的临时 DB 直接 DROP 重建即可，无在线生产迁移承诺。journal 是新增本地 v1 格式，回滚代码后保留文件不影响 PostgreSQL，但旧 host 不应读取它，未知版本必须失败而非清除。

| 风险 | 触发信号 | 处置 |
|---|---|---|
| 闭包真实触顶 | 必需流程 `retry_with_closure`，或 C≥448 | 停止 R/P 收尾，保留测量证据，另开设计修订 |
| host 读面泄露其他 scope | 非 owner service 读到 item，或能区分「不存在」与「拒绝」 | G8 失败；不得改成全 service 可读来绕开 |
| 注释触发 ACL 正则 | 加载即 `read-only SECURITY DEFINER drift` | 修改新文件注释/命名；不放宽 ACL 检查 |
| lease 与真实延迟不匹配 | pre-HTTP lease 不足、`length`、过期 unknown | 降 timeout/output；不续租、不自动重发 |
| provider API 漂移 | real smoke 的 endpoint/model/工具合同失败 | 真实入口失败并报告；Fake extension check 不因此改期望 |
| journal 丢失或损坏 | 重启无法判断是否已外呼 | 不从空 DB state 猜历史，不重打不确定外呼；保留现场进 unknown |
| unknown tool 阻塞 dispose | P 负例中 dispose 未完成 | 展示阻塞并保留证据；不承诺自动清理 |
| 单 host 的 admin+service 身份较宽 | 部署只需要一个 LOGIN 同时属两组 | 仅用于受信部署；不作租户或多宿主安全承诺 |
| jsonb ABI 缺编译期列检查 | 调用方依赖稳定 SQL 行描述符 | G8 逐函数断言信封、字段闭集、JSON 类型、游标与空集；不放宽为 `RETURNS TABLE` 除非裁决 1 被推翻 |
| 未脱敏 `request` 的单页尺寸 | request 无已定义的全局字节限额；整轮累积不受单页项数限制 | 后续计划 D1 已决定保持 64 项；G8-H13 的 67,107,712 B 仅为夹具测量，不是响应/内存上限，不脱敏 |
| extension check 未跑即交付（裁决 5-B 的代价） | 11/11 全绿但 G8/G9/G10 未运行 | matrix/ledger/README 必须显式写「未验证」；禁止把 11/11 解读为扩展能力已证明 |
| deadline 非硬上界 | 慢速滴灌响应超出约 2× `timeout_s`、DNS 不被 socket timeout 覆盖 | 登记为活性披露；正确性不依赖它（结算不查 lease、不在飞不 sweep、挂死经 journal 收敛 unknown） |

**实施前必须核对的三个未展示完整源码的位置**：① install manifest 的精确合法编码（复用现有 `admit_install` 构造并验证安装行三个 digest，不猜新增字段）；② 既有 gate 是否硬编码 DEFINER/EXECUTE 集合（只更新受本次新增接口影响的精确集合，不放宽行为断言）；③ 实际 DeepSeek endpoint、usage/reasoning 返回形状（由 opt-in 实测确认，不支持时失败，不自动重发到别名）。

## Verification

**两层口径必须分开写**（裁决 5-B）：① **正式 closeout** = `v24/s7/README.md:210-226` 冻结的 11 条，每个里程碑提交前必须全绿，数字保持 11/11；② **extension check** = 本计划新增的三条，是各里程碑 done-when 的必要条件，必须实跑并在 matrix/ledger/README 记录「通过 / 失败 / 未运行」三态，但不改历史 closeout 数字、不称 closeout gate。没有运行 extension check 时不得宣称对应扩展已有完整验证证据，也**不得把 11/11 解读为扩展能力已证明**。

**正式 closeout（11 条，顺序见 `v24/s7/README.md:210-226`）**：
```bash
# 既有 11 条（顺序见 v24/s7/README.md:210-226）
uv run python v24/load.py
uv run python v24/s1/setup_db.py --self-check
uv run python v24/s1/test_ddl.py
uv run python v24/s1/test_g1.py
uv run python v24/s2/test_g3a.py
uv run python v24/s3/test_g2.py
uv run python v24/s4/test_g2b.py
uv run python v24/s5/test_g4.py
uv run python v24/s6/test_g5.py
uv run python v24/s8/test_g7.py
uv run python v24/s7/test_g6.py
```

**Extension check（3 条，非 closeout gate；退出码 0 = 通过，1 = 失败；`--only` 只作增量检查点）**：

```bash
uv run python v24/s9/test_g8.py
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL \
  UV_NO_ENV_FILE=1 uv run python v24/s10/test_g9.py
uv run python v24/s11/test_g10.py
```

**Opt-in 命令**（非 gate；`credentials_absent`/`toolchain_absent` → exit 2 不算通过）：

```bash
# 必须打印 credentials_absent，退出 2，不建库
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI \
  UV_NO_ENV_FILE=1 uv run python -m v24.host.smoke --real-provider-smoke

# 有环境变量 key 时：真实 v24 全链一次
UV_NO_ENV_FILE=1 uv run python -m v24.host.smoke --real-provider-smoke

# Python + Node 全链；缺 Node 退出 2
uv run python v24/s11/test_node.py --node

# 同一 run 内 Python → Node → final，两个 install 均 disposed；缺 Node 退出 2
uv run python -m v24.host.plugin_smoke --multilingual-smoke
```

**手工核验**：key 未进入数据库、journal、argv 或输出；外呼开始时所有 DB 控制连接 IDLE；provider 每个 effect 恰一次 HTTP dispatch；多语言冒烟中同一 run 的两个 pin/tool 都被真实调用、Python 先于 Node、两者之后才 final、两个 install 最终均 disposed；unknown 负例如实保留阻塞；没有把无 flag、无 key 或缺 Node 的退出算成通过。

**多语言验收口径（与 M-P-3 绑定）**：`test_node.py --node` 是**独立**的 Node 全生命周期，`plugin_smoke.py --multilingual-smoke` 才是 M-P-3 要求的「同一 run 内 Python → Node → final」。两者都必须留证；只跑前者不证明后者。后者还必须覆盖 Unicode、转义换行、空字符串与工具错误（exit 3）四类输入。

**最终差异检查**：

```bash
git diff --name-only -- v24/sql v24/load.py          # 预期仅 49_host_reads.sql 与 50_permissions.sql、loader 注册行
git diff --exit-code -- v24/sql/10_schema.sql v24/sql/20_triggers.sql \
  v24/sql/30_advance.sql v24/sql/40_interpreters.sql v24/sql/45_capability.sql \
  v24/sql/46_cleanup.sql v24/sql/47_verbs.sql v24/sql/48_loop.sql v24/sql/49_recovery.sql
git diff --exit-code -- v13 v99
git status --short
```

## 最终执行记录（2026-10-24/25）

三个里程碑各自一次提交并已推送到 `origin/v24`：

| 里程碑 | 提交 | 一句话 |
|---|---|---|
| M-H | `e29d3a2` | 九个 host 只读函数 + ACL/loader/G1 同步 + G8 extension check |
| M-R | `2c4ee2d` | host worker、durable journal、DeepSeek adapter、G9、opt-in smoke、`AGENTS.md` 第三入口 |
| M-P | `4e0d3f0` | approved adapter registry、line-JSON 派发、Python/Node 参考插件、G10/test_node/plugin_smoke |

**正式 closeout 不变，仍为 11/11**（每个里程碑提交前均按 `v24/s7/README.md:210-226` 顺序实跑，全部 exit 0）。

**Extension check 三态记录**（非 closeout gate，均在最终树上实跑）：

| 检查 | 结果 | 实测摘要 |
|---|---|---|
| `v24/s9/test_g8.py` | 通过 **23/23** | 闭包 `B=C(0)=3`；`H=0,1,2,4,8,16,32 → C=3,4,5,7,11,19,35`；`H_ok=509 → C=512` 正常 claim，`H_bad=510 → C=513` `retry_with_closure` 零写；H13 最坏页 64 项 × ~1 MiB = **67,107,712 B (64.00 MiB)**，64 上限与不脱敏口径保持不变（不放宽、不脱敏）；ACL 17 DEFINER / 27 GRANT / EXECUTE 26-27-27 |
| `v24/s10/test_g9.py` | 通过 **11/11** | 全 ScriptTransport、零真实套接字；映射/unknown/lease/崩溃窗口与重启对账；`not_requested` → 0，`credentials_absent` → 2 且不建库 |
| `v24/s11/test_g10.py` | 通过 **8/8** | Python 真实本地子进程全生命周期；exit 3 → failure；坏帧 → unknown 且 dispose 屏障保留；artifact/adapter/descriptor 三个独立 digest 负例均零 spawn；重复 prepare/release 幂等 |
| `v24/s11/test_node.py --node` | 通过 exit 0 | Node v24.13.1 独立全生命周期（Unicode / 转义换行 / 空字符串）与 exit 3 映射 |
| `v24/host/plugin_smoke.py --multilingual-smoke` | 通过 exit 0 | 同一 run：Python 成功（Unicode）→ Node 成功（转义换行 + 空字符串）→ Node exit 3 → final；`dispose python=disposed node=disposed scope=closed` |

**债务变化**：D-S6-12 由 `G8-D1a`（closed scope + 真实过期/claimed/非 manual 候选）关闭；D-S8-7 由 `G8-D2`（四种 spawn 混用）关闭；D-S7-2（无 starvation/fairness）**原样保留**。

**新增披露**（详见 `docs/reviews/v24-deviation-ledger-2026-10-23.md`）：jsonb 只读 ABI 的编译期约束由 G8 逐函数断言补回；闭包单调增长与 128/384/448/512 停止阶梯；lease 上限与 `StdlibTransport` deadline 非硬上界（D-MR-10）；进程内 provider 选择；G10 使用真实本地子进程属 §9.1 字面偏差（D-MP-1）；pre-G 读 `v24.fibers` 的窄路径披露；`AGENTS.md` 第三真实套接字入口（D-MR-9）。

**仍未验证 / 不在本轮范围**：真实 `DEEPSEEK_API_KEY` 全链（环境无 key，`--real-provider-smoke` 未以真 key 运行，属 opt-in 且非 gate）；Go/Swift/DuckDB 第二批语言；跨主机 lease、多主机与 fairness（D-S7-2）。上述任一项都不得被 11/11 或三条 extension check 的绿色解释为已验证。

## Open Questions

原 5 条开放决策已由 Oracle 于 2026-10-25 裁决并写入 Approach「Oracle 裁决记录」，此处不再重复。裁决 5（closeout 口径）是范围/验收决策，用户可随时以纯文档改动翻转为 14/14。仍然开放、需要用户或后续修订才能定的是：

1. **模型选择已由后续计划 D3 收口**：v24 固定 `deepseek-flash`，没有运行时 allowlist，也不消费 v15 allowlist；本轮不加模型参数或 `--model`。v4-pro 另需配置、校验与计价合同。上文外部型号/弃用/价格材料仍仅为 2026-10-24 核查记录，不表示本次重新核验。
2. **多语言第二批语言**（Go / Swift / DuckDB）：本轮明确不做（避免扩大交付面）。前置条件是 Node 全链 opt-in 实测 exit 0 且工具链可用性有证据，再按同一 `ApprovedAdapterRegistry` 增加 entry——届时才需要处理 `pi_ports` 的 PiG/PiSwift 夹具依赖（外部 checkout 路径）。
3. **真实 provider 验收的授权**：`--real-provider-smoke` 需要 `DEEPSEEK_API_KEY`（或 `OPENAI_API_KEY`）在环境中。当前 shell 未设置、仓库无 `.env`，因此本计划**不包含任何 live 调用证据**；何时授权实跑由用户决定，跑前按 `AGENTS.md:73-75` 确认当时无打开事务。

## References

- `docs/designs/v24-pg-agent-2026-10-22.md` §1.5, §5, §9.1, §10.1–10.3, 附录 B.1–B.5, 附录 C.1–C.6
- `docs/plans/v24-pre-plan-2026-10-23.md` §8.2, §9
- `docs/plans/v24-s7-concurrency-2026-10-24.md` §4–§8；`docs/plans/v24-s7-handoff-2026-10-24.md`
- `docs/reviews/v24-conformance-matrix-2026-10-23.md` §2.7, §4, §5；`docs/reviews/v24-deviation-ledger-2026-10-23.md` §1.15, §5
- `v24/sql/10_schema.sql`, `20_triggers.sql`, `30_advance.sql`, `40_interpreters.sql`, `45_capability.sql`, `46_cleanup.sql`, `47_verbs.sql`, `48_loop.sql`, `49_recovery.sql`, `50_permissions.sql`
- `v24/load.py`；`v24/s1/setup_db.py`；`v24/s1/fake_host.py`；`v24/s4/fake_llm.py`；`v24/s6/{fake_crash_host,crash_worker,recover_worker}.py`
- `v24/s1/README.md`, `v24/s6/README.md:93`, `v24/s7/README.md:210-226`, `v24/s8/README.md`
- `v15/provider/deepseek.py`, `errors.py`, `pricing.py`, `smoke.py`, `README.md`；`v15/worker.py`；`demo_v15/README.md`
- `v13/read_tools/bridge.py`, `test_read_tools.py`, `README.md`；`v13/pi_ports/test_pi_ports.py`, `README.md`；`v13/registry/v13_registry.sql`；`v13/schema/v13_core.sql`；`docs/designs/v13-tool-ports.md`
- `docs/reviews/v13-pi-ports-trilingual-2026-09-28.md`
- `v8/plugin/v8_plugin.sql:38-140`；`docs/designs/v99-core-native-plugin-plane-2026-10-20.md`（Not ready）；`docs/designs/cordis-plugin-core-2026-10-22.md` §8
- DeepSeek 官方文档（2026-10-24 核查）：[Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing)、[Create Chat Completion](https://api-docs.deepseek.com/api/create-chat-completion)、[Tool Calls guide](https://api-docs.deepseek.com/guides/tool_calls)、[Thinking Mode guide](https://api-docs.deepseek.com/guides/thinking_mode)、[Rate Limit](https://api-docs.deepseek.com/quick_start/rate_limit)、[Change Log](https://api-docs.deepseek.com/updates/)
