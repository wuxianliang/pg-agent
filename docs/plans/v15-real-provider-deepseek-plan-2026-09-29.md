# v15 真实 provider 接入（DeepSeek）: Plan

## Goal

把 v15 的 LLM 调用从 FakeLLM 扩展到真实 DeepSeek API：worker 侧新增 provider 适配层（OpenAI 兼容 `/chat/completions`、纯 stdlib HTTP、keyless-by-default），打通 `resolved_config.llm` → 适配器 → `v15_settle_llm` 的 usage/cost 流（含按价目自算成本），并为「provider 确定性失败」补一条规格允许的失败路径；九道既有 gate 保持全绿，真实调用只进 opt-in smoke。

## Background

### v15 现状接线（探索代理 A，file:line）

- 调用点：`v15/worker.py:278`（`Worker._mark_and_settle`，`worker.py:264`）——先 `_run(mark)` 提交 `v15_mark_call_started`（`worker.py:268-273`），断言 `TRANSACTION_STATUS_IDLE`（`worker.py:276-277`），纯 Python 调 `self.fakellm.complete(logical_digest, n, request)`，然后 `worker.py:285-299` 在新事务 `v15_settle_llm`。`_llm`（`worker.py:235`）经 `v15_begin_llm` 拿 `{attempt_id, request, logical_digest, n, action}`。
- FakeLLM 契约：`v15/fake_llm.py:14,17,34`——`complete(logical_digest, n, request) -> {content, prompt_tokens?, cost_usd?}`；无时钟/随机/套接字。
- digest 与记账：`v15/io/v15_io.sql` 两个摘要——`:1161` 是 base 消息摘要、`:1284` 是 `logical_digest = md5(request - attempt_id)`；settle 解析 `prompt_tokens/cost_usd`（`:1466-1484`）并经 `v15_io_pool_release` 入 `cost_used`（`:1486`），`cost_limit` 超限 → 提交类 `V15_BUDGET_EXHAUSTED`（`:1513-1523`）。attempt 终态只有 settled/failed/unknown；`failed` 仅来自回收且 `call_started=false`（§0.6）。
- 配置：`v15/config/v15_config.sql:26-76`——`llm` 组件闭合键集 `{model, temperature, max_output_tokens}`；**运行期无人消费 `llm.model`**（仅测试读）。
- 预算表：`v15/schema/v15_schema.sql:62`（calls/cost 的 used/reserved 四列）。

### DeepSeek API 事实（探索代理 B，官方文档，2026-09-29 核实）

- **模型名**：`deepseek-chat`/`deepseek-reasoner` 已于 2026-07-24 停用；现为 `deepseek-flash`（V4.1-Flash，默认思考）与 `deepseek-v4-pro`。仓库 v8 的默认 `deepseek-chat`（`v8/loop/runtime.py:265` 一带）已失效。
- Endpoint：`https://api.deepseek.com` + `POST /chat/completions`（OpenAI 兼容）或 `/anthropic`；`Authorization: Bearer $DEEPSEEK_API_KEY`。
- 响应扩展：`reasoning_content`；`finish_reason` 增 `insufficient_system_resource`/`aborted`；`thinking`/`reasoning_effort` 参数；思考模式下 `temperature` 无效、`top_p` 仅 0.95–1.0。
- usage：`prompt_tokens`（=hit+miss）、`completion_tokens`（含思考 token，按输出价计费）、`prompt_cache_hit_tokens`/`prompt_cache_miss_tokens`；**无 cost 字段，须按价目自算**。
- 价目（USD/1M tokens，高峰=北京工作日 9–12/14–18 时，空闲=半价）：flash 输入 miss $0.15/$0.30、hit $0.003/$0.006、输出 $0.60/$1.20；v4-pro 输入 miss $0.66/$1.32、输出 $1.98/$3.96。
- **无幂等契约**：无 idempotency key/去重/重放；「已发出未收全」的失败可能已计费，重试可能重复计费。
- 限额是**并发连接数**（flash 2500 / pro 500），超出即 429；不保证 `Retry-After`。10 分钟内未开始推理则服务端断连；非流式有空行保活。
- 错误语义：500/503 官方建议短暂等待后重试；400/401/402/422 为需修复类，不应原样重试。
- 链接：https://api-docs.deepseek.com/quick_start/pricing ；https://api-docs.deepseek.com/api/create-chat-completion ；https://api-docs.deepseek.com/quick_start/rate_limit ；https://api-docs.deepseek.com/updates

### 仓库既有真实 provider 用法（探索代理 C，file:line）

- Key 约定（v8，`v8/loop/runtime.py:261-266`）：`DEEPSEEK_API_KEY` → `OPENAI_API_KEY` 兜底；`OPENAI_API_URI`（默认 `https://api.deepseek.com/v1`）；`OPENAI_MODEL`；**无 key 在开 socket 前抛 RuntimeError（blocked capability）**（`:283-290`）。demo_v13 同约定且 key 只活在 shim 进程环境（`demo_v13/README.md:8,156-160`）。
- HTTP 客户端：v8 用**纯 stdlib urllib**（`v8/loop/runtime.py:304`，无第三方依赖）；v3–v6 曾用 litellm（`v6/kernel_freeze/worker.py:85-95`）。
- 超时/重试先例：v8 单次调用默认 30s、不重试、失败转 `unknown_outcome` 证据（`:300-317`）；v6 手动 3 次退避重试（`v6/kernel_freeze/worker.py:70-101`）。
- 成本先例：v8 只把 `usage` 原样存进 receipt（`:325-341`），从未算钱；v4/v6 有 cost schema 但未接线（`v4/observability_budget/observability_budget.sql:26-38`）。
- Keyless 纪律：gate 默认剥凭据 `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI ... UV_NO_ENV_FILE=1`（uv 会经 `UV_ENV_FILE` 自动注入 .env，`docs/plans/v8-j0-keyless-baseline-report-plan-2026-09-17.md:258`）；非交互 shell 须先 `source ~/.zshrc`（`docs/plans/v13-control-parity-tests-plan-2026-09-26.md:36`）；v8 的 opt-in 真连冒烟模式：`--real-provider-smoke` 缺 key → `not_run/credentials_absent` + exit 2，且有 patch 断言 keyless 路径绝不 live 调用（`v8/compat/test_compat.py:1144-1152,1450-1513`）。

### 与冻结规格的已知张力（计划必须裁决）

1. **provider 确定性失败无 settle 路径**：`call_started=true` 后拿到 401/402/422 等「已知的、不可重试的」失败，规格上只能等租约过期 → unknown → 保守计费 + 重试新 attempt（对 402 余额耗尽会造成循环烧 calls）。需要小的 design revision（新转移或错误码，按 §18 冻结协议随 gate 同 commit）。
2. **`llm` 组件键集闭合**（§8.1 只有 model/temperature/max_output_tokens）：base_url、超时、思考开关等适配器键要么进 keyless 默认+环境变量（不改规格），要么扩键集（design revision）。
3. **成本自算**：settle 只收 `cost_usd` 数字；价目表（含高峰/空闲时段）放 worker 侧版本化文件，缺 usage 时的政策需定（jaz 先例：`jaz/src/jaz/llm/pricing.py` + `model_prices.json`）。
4. **租约 TTL vs 真实延迟**：DeepSeek 10 分钟未开始推理即断连；v8 用 30s 超时。attempt/invoke 租约必须显著大于 HTTP 超时，保证 worker 总能在过期前 settle 或让 reclaim 收 unknown。

## Open Questions（草稿裁决状态）

底稿五个开放问题已由规划轮裁决（见下文「裁决」节）：①确定性失败=三个新 SQL 转移（`v15_provider_reject_unstarted/reject_started/abandon`）+ 尾追加单码 `V15_PROVIDER_REJECTED`/`P1539`，不新增 attempt 状态；②不扩 `llm` 键集，endpoint/key/超时走进程环境与 Worker 构造参数；③缺 usage/无法计价=fail-closed（abandon `unpriced`，绝不以 0 settle）；④本次 allowlist **仅 `deepseek-flash`**（用户裁决 B；v4-pro 留待后续版本按 §18 修订扩入）；⑤冒烟是独立脚本 `smoke.py`，不是 gate flag。

**留给用户定稿的三点（Phase 5 已裁决）**：
- A. 超时档位取基线 **120s / 180s**（HTTP 超时 120 秒、真实 provider Worker 租约 180 秒）。
- B. 本次模型范围**仅 `deepseek-flash`**（v4-pro 不进 allowlist 与价目，后续版本按 §18 修订再扩）。
- C. 接受预算口径「供应商发票 ≥ `cost_used`；`cost_limit` 不管住已扣费但未拿到 usage 的那一次」（unknown 保守计 calls、不保守计钱），写入偏差台账 D28。

---

# v15 真实 provider 接入（DeepSeek）— 可执行计划

本文件裁决 `docs/plans/v15-real-provider-deepseek-plan-2026-09-29.md` 的 Open Questions，并给出 rev 9 的实现级规格。与底稿冲突时以本文为准。不写实现代码。行为权威仍是修订后的 `docs/designs/v15-jaz-dev.md`；本文只规定这次修订要写进规格的句子，以及实现落点。

## Summary

在九个既有 stage 的冻结语义上追加 **stage 10 `v15/provider`**（只加函数，不加表）：worker 在 `v15_mark_call_started` 提交之后、结算事务之前调用一个与 `FakeLLM.complete` 同形的 provider。默认对象仍是 `FakeLLM`。opt-in 的 `DeepSeekProvider` 用标准库 `urllib` 打 DeepSeek `/chat/completions`，模型只允许 `deepseek-flash`（用户裁决 B），key 缺省即拒绝且不开 socket。`llm` 闭合键集不扩大；endpoint、超时、key 走环境变量。成功响应用版本化价目表把 cache hit/miss 与 completion（含思考 token）算成 `cost_usd`，算不出成本就 **不 settle、不记 0**。`call_started = true` 之后的终态仍只有 `settled` 与 `unknown`：传输失败立即 `unknown` 并收回 invoke 以便按 `max_io_attempts` 重试；401/402/422 等确定性失败把 attempt 记成 `unknown`（计 calls、不计 cost）并在同一事务用新码 `V15_PROVIDER_REJECTED`（`P1539`，`fatal = false`）结束 invoke，从而切断 402 的烧 calls 循环。九道既有 gate 保持 keyless；真连只在独立脚本 `v15/provider/smoke.py`。

## Current-state analysis

### 调用链（唯一注入点）

`run_until_quiescent(db_dsn, fakellm, worker_id)` 把 provider 交给 `Worker`。`drive` 在迭代 `pending` 或 `llm` 且没有存活 `leased` attempt 时走 `_llm`：`build_base(snap)` 后调用 `v15_begin_llm`。返回 `proceed` 才进入 `_mark_and_settle`。（observation，`v15/worker.py:235-299`）

`_mark_and_settle` 的顺序是硬边界：（observation，`v15/worker.py:264-299`）

1. `_run(mark)` 提交 `v15_mark_call_started`，`call_started` 从 false 变为 true。
2. 断言连接 `TRANSACTION_STATUS_IDLE`。
3. `self.fakellm.complete(logical_digest, n, request)`。
4. `statement_payload(response["content"])`，再在新事务 `v15_settle_llm`。

`drive` 若看见 `call_started = true` 且不是本进程刚提交的那一次 mark，直接 return，不调用 provider、也不 settle。（observation，`v15/worker.py` 中 `attempt["call_started"]` 分支；与 §4.12 一致，`docs/designs/v15-jaz-dev.md:1200-1450`）

因此换 provider **不改** claim / begin / mark / exec 的控制流。要改的是：`complete` 的异常分类、mark 之前的本地拒绝，以及这两类结果对应的新 SQL 转移。`FakeLLM` 的 `KeyError` 必须仍不 settle。（observation，`v15/fake_llm.py` 模块文档与 `complete`）

### attempt 终态与记账

`llm_attempts` 的 CHECK：`failed` 要求 `NOT call_started AND NOT calls_charged`；`unknown` 与 `settled` 要求 `call_started AND calls_charged`。（observation，`v15/schema/v15_schema.sql` 的 `llm_attempts_failed` / `llm_attempts_unknown` / `llm_attempts_settled`）

§0.6：调用一旦开始，终态只允许 `settled` 或 `unknown`；`failed` 只允许出现在尚未开始的 attempt 上。回收不插入新 attempt、不调用 `v15_on_phase`、不调用 provider。（observation，`docs/designs/v15-jaz-dev.md:1-262` 不变量 6；`v15/io/v15_io.sql` 的 `v15_reclaim_expired`）

记账只有三条，实现在 `v15_io_pool_release`：（observation，§4.5.4，`docs/designs/v15-jaz-dev.md:1040-1150`；`v15/io/v15_io.sql` 的 `v15_io_pool_release` 与 `v15_reclaim_expired`）

| 事件 | calls | cost |
|---|---|---|
| settle（调用已发生） | `calls_reserved -= reserved_calls`，`calls_used += reserved_calls` | `cost_reserved -= reserved_cost`，`cost_used += cost_usd` |
| unknown（已 `call_started`） | 预留转入 `calls_used` | 只释放 `cost_reserved`，`cost_used` 不动 |
| failed（未 `call_started`） | 只释放预留 | 只释放预留 |

`unknown` 之后的新 attempt 必须再走 claim → `v15_begin_llm` 重试分支 → mark。重试复制上一行的 `reserved_calls` / `reserved_cost` 与 messages，`logical_digest` 不变，`n+1`，受 `max_io_attempts` 限制，超出则提交类 `V15_IO_EXHAUSTED`（`fatal = false`），不插入越限行。（observation，`v15/io/v15_io.sql` 的 `v15_begin_llm` 重试分支与 IO 耗尽分支；`v15/io/test_io.py` 的 `test_retry_and_exhaust`）

**推论（E26）。** 若 402 只靠「不 settle、等租约、回收成 unknown」，每次都会 `calls_used += reserved_calls`，然后重试分支再打一次，直到 `V15_IO_EXHAUSTED`。操作者看到的码是 IO 耗尽，不是余额耗尽。支撑：上述 CHECK、unknown 记账、begin 的 `n+1` 与 `max_io_attempts`。

**推论（E27）。** 「本进程记住 402 不再重试」不能成立。§0.3：进程内存不是可恢复状态。崩溃后的新进程只会看到 `unknown` 或仍 `leased` 的 attempt，然后 begin 重试。停止重试必须写在已提交的 invoke 终态上。

回收还有一条对超时设计很重要的事实：本事务刚刚终结的 attempt 所属 invoke，即使 invoke 自己的 `lease_until` 未到，也会被收回（`v_id = ANY (v_terminated)`）。（observation，`v15/io/v15_io.sql` 的 `v15_reclaim_expired` 候选过滤）

### settle 入参

`p_response` 必须是含字符串 `content` 的对象。`prompt_tokens` 缺省 0；出现时 `jsonb` 类型为 number，文本匹配 `^[0-9]+$`，且 `<= 2147483647`；**JSON null 也被接受并落回 0**（评审 F2：这是既有 SQL 的宽松面，不改）。`cost_usd` 缺省 0；出现时为 number 且 `>= 0`；null 同理。不符是回滚类 `V15_VALUE_INVALID`。未知键没有被拒绝。适配器自己维持更严的 fail-closed 规则。（observation，`v15/io/v15_io.sql` 的 `v15_settle_llm`；底稿指向 `:1466-1523`）

列类型是 `prompt_tokens int`、`cost_usd numeric`。（observation，`v15/schema/v15_schema.sql` 的 `llm_attempts`）因此适配器不得把 `10.0` 这种带小数点的 token 文本送进 settle，也不得用二进制 float 的科学计数法去赌 `prompt_tokens` 的正则。`cost_usd` 走 PostgreSQL 对 jsonb 数字的解析，可以用十进制文本拼进 JSON，避免 `Decimal` 被 `json.dumps` 变成 float。

`cost_limit` 非空且结算后 `cost_used > cost_limit`：attempt 保持 `settled`，invoke 提交类 `V15_BUDGET_EXHAUSTED`，`fatal = true`。（observation，同函数后半；§4.5.3）预留默认是 `reserved_calls = 1`、`reserved_cost = 0`，除非 phase 返回 budget。（observation，`v15_begin_llm` 的 `v_calls := 1; v_cost := 0` 分支）真实调用的钱是在 settle 时入账，不是在预留时锁死。这是既有语义，本次不改。

### 配置断点

`v15_check_component('llm', …)` 的允许键恰好是 `model`、`temperature`、`max_output_tokens`。其他键 `V15_VALUE_INVALID`。（observation，`v15/config/v15_config.sql` 的 `v15_check_component`）折叠结果在 open 时写入 `invokes.resolved_config`，之后不重折。（observation，§0.16、§8.1–§8.2，`docs/designs/v15-jaz-dev.md:1600-1700`）

种子 profile 是 `{"model":"fake"}`。（observation，`v15/config/v15_config.sql` 末尾 `v15_register_profile`）`build_base` 只读 `snap["resolved_config"]["protocol"]`，不读 `llm`。（observation，`v15/worker.py` 的 `build_base`）底稿「运行期无人消费 `llm.model`」与这段代码一致。

`logical_digest = md5((request - attempt_id)::text)`，request 只有 `attempt_id` 与 `messages`。模型名不在 digest 里。（observation，`v15_begin_llm`；底稿 `:1161,1284`）所以换 `llm.model` 不会改变 digest，适配器必须另从 snapshot 取模型，不能从 digest 或 request 推断。

### 租约时钟

`LEASE = "30 seconds"` 只在 `Worker.claim` → `v15_claim` 使用。（observation，`v15/worker.py:18` 与 `claim`）attempt 的 `lease_until` **复制** begin 当时的 invoke `lease_until`，不是 `clock_timestamp() + 超时`。（observation，`v15_begin_llm` 两处 `INSERT` 的 `v_inv.lease_until`）settle 要求 invoke 租约未过期。（observation，§4.5.3）

`_begin` 里的 `statement_timeout = '30s'` 是转移函数的 SQL 背书，与 HTTP 无关。（observation，`v15/worker.py` 的 `_begin`）模型语句超时来自 `v15_prepare_statement` 返回的 `timeout_ms`，另有一条连接 `pg_cancel_backend`。（observation，`v15/worker.py` 的 `_execute_one` / `_cancel`；§4.6.2）

**推论（E25）。** begin + mark + HTTP + settle 必须落在同一次 claim 的租约窗口内。HTTP 超时 ≥ 租约时，慢成功无法 settle，只能变成 unknown，重试可能在没有幂等键的情况下再计一次费。支撑：E 段三条 observation，加上底稿「DeepSeek 无幂等、10 分钟未开始推理即断连」。

`test_io.py` 自己的 `LEASE = "10 minutes"`，不读 worker 常量。（observation，`v15/io/test_io.py`）改 worker 默认租约不必改 stage 6 的直接 SQL 调用；会改变所有 `run_until_quiescent` 的租约长度。FakeLLM 路径必须保持 30 秒，避免把 crash-recovery 窗口从 30 秒放宽到数分钟。

### 既有 gate 对 FakeLLM 的源码约束

`test_io.py` 读取 `v15/fake_llm.py` 源码，断言 import 行不含 `socket`、`random`、`time`、`urllib`、`http`。（observation，`v15/io/test_io.py` 的 `test_fake_and_worker`）真实客户端必须是另一个模块。`fake_llm.py` 不能长出网络 import。

### 加载与「合运行时」

`SQL_LOAD_ORDER` 九个文件，`files_through` 取前缀。（observation，`v15/load.py`）§15：stage 1 之后可以加函数、视图、授权、目录种子 DML，以及点名的 `CREATE OR REPLACE`；**不得再增加表**。加表才需要新 stage；不加表也可以新 stage，用来让前缀 gate 的 SQL 字节保持不变。（observation，`docs/designs/v15-jaz-dev.md` §15）

`v15/README.md` 与 `v15/govern/README.md` 写明九个文件加载后的 `agent_v15_govern` 才是合运行时。stage 10 落地后这两句会变成假话，必须改。

§18：`v15_on_phase` 与四个治理 handler 的函数体只允许出现在 `v15/schema/v15_schema.sql` 与 `v15/govern/v15_govern.sql`。错误码只许从 `P1539` 尾追加，硬顶 `P1548`，不得预占。（observation，§13、§18）

### 先例（只借鉴形状，不建立依赖）

v8 `DeepSeekLLM`：`urllib.request`；key 为 `DEEPSEEK_API_KEY` 再回退 `OPENAI_API_KEY`；base 为 `OPENAI_API_URI`，默认 `https://api.deepseek.com/v1`；无 key 在 `urlopen` 之前 `RuntimeError`；默认超时 30 秒、不重试；传输异常返回 `unknown_outcome`；usage 原样进 receipt，不算钱；默认模型 `deepseek-chat`。（observation，`v8/loop/runtime.py:230-360`；底稿指出该模型名已于 2026-07-24 停用）

v8 冒烟：默认不构造适配器；`--real-provider-smoke` 且无凭据 → `not_run/credentials_absent`、退出码 2、不调用 `generate`；已开始的失败保持 `failed`；keyless 用 patch 让构造或 `urlopen` 直接 `AssertionError`。（observation，`v8/compat/test_compat.py:1130-1530`）

jaz `compute_cost`：未知模型返回 `None`，不是 0。文档写明静默 0 会让 `cost_budget` 失效。（observation，`jaz/src/jaz/llm/pricing.py` 的 `compute_cost` 与文件头 `TODO(#1027)`）`model_prices.json` 不入选，且过滤集只有 openai/anthropic，不能当 DeepSeek 价目来源。jaz `_handle_error_response` 把 401/403/404/429/400 分成不同异常，并把 “could not parse the json body” 的 400 当成可重试 `APIError`。（observation，`jaz/src/jaz/llm/openai.py` 的 `_handle_error_response`）

v15 **不得** import v8 或 jaz。§0.1 禁止改 v8/v13。新客户端放在 `v15/provider/`。

### 阻塞点

| 阻塞 | 原因 |
|---|---|
| 不能把已开始的 attempt 标成 `failed` | CHECK 与 §0.6 |
| 不能在适配器里对 429/500 做多次 HTTP 再记一次 `reserved_calls` | 一次 attempt 对应一份预留；无幂等，内部重试会少计 calls、多计供应商账单 |
| 不能把 base_url / timeout / thinking 塞进 `llm` | `v15_check_component` 会 `P1524`，且 key 会进 `resolved_config` |
| 不能让 gate 构造会读 env 并连网的对象 | §0.0、AGENTS.md、`test_io` 的 import 扫描 |
| 不能改 `v15_on_phase` 的位置或签名 | §0.28、§18 |
| `prompt_tokens` 不能钳位 | 钳位是少报；settle 的正则与 int4 上限会拒绝非法值，适配器应在进 SQL 前转为 abandon |

NUL：§0.18 / §4.5.3 要求 worker 在进 SQL 前把每个 NUL 换成六字符 `\u0000`，整段成为 `V15_VALUE_INVALID` 的合成失败语句。`test_io.py` 已通过 `split_sql("has\x00nul")` 断言替换与 `reject_code`。（observation，`v15/io/test_io.py` 的 `test_statements`）`statement_payload` 调用 `split_sql`。（observation，`v15/worker.py`）`_mark_and_settle` 把 `response` 原样 `Json(...)` 送进 settle。FakeLLM 测试在登记前已经换成替换后的文本，所以这条缝还没被 worker 打到。真实 JSON 的 `\u0000` 会被 `json.loads` 还原成 NUL，PostgreSQL `text`/`jsonb` 会拒。这是 worker 的必补缝，不是新码。

## Design

### 冻结条款处置

| 条款 | 处置 |
|---|---|
| §1 把「真实 provider」列为不在本版；§15「FakeLLM 只有 `v15/fake_llm.py`」；§0.0 / §15 测试不得开 socket | **需修订（rev 9）**。真实 provider 成为 worker 侧 opt-in I/O。gate（`v15/**/test_*.py`）仍只用 FakeLLM、不得开 socket。`smoke.py` 不是 gate |
| §0.4 事务内禁止外部 I/O | **遵守**。适配器只在 mark 已提交且 `TRANSACTION_STATUS_IDLE` 之后调用。任何 SQL 函数不调用它 |
| §0.6 / 终态 CHECK | **遵守终态三值，需修订「谁可以写入 unknown」**。仍禁止 `call_started = true` 的 `failed`。新增转移把已开始的失败写成 `unknown`（记账与回收相同），而不是新 status |
| §0.21 / §11.3 保守记账 | **遵守**。已开始的拒绝与 abandon 走 unknown 公式；未开始的本地拒绝走 failed 公式。不新增池列 |
| §8.1 `llm` 键集 | **遵守，不扩键**。见下文「键集」 |
| §13 / §18 错误码 | **需修订，尾追加一行**。`V15_PROVIDER_REJECTED` / `P1539`。不预占 `P1540`–`P1548` |
| §0.0 + AGENTS.md keyless | **遵守 gate，需修订 AGENTS 一句**。唯一允许真实 socket 的入口是 `v15/provider/smoke.py --real-provider-smoke`，且当时无打开的事务 |
| §15 加载与里程碑 | **需修订 stage 表与合运行时定义**。`SQL_LOAD_ORDER` 只在末尾加 `v15/provider/v15_provider.sql`。一个里程碑一次提交 |
| §11.5 不能用配置关掉 baseline | **遵守**。不新增 GUC、不新增 `hooks_disabled`、provider 不绕过 `v15_on_phase` |
| 环境基线 PG 18.4，`server_version_num = 180004` | **不涉及**。不改版本断言 |

不触碰：`v15_on_phase` 与四个治理 handler 的函数体位置、21 张表、`v15_settle_llm` 的签名与成功路径、FakeLLM 的 `(logical_digest, n)` 脚本语义。

### 裁决（底稿五个问题 + 额外点）

1. **确定性失败：新转移，不走「短租约空等 unknown」。** 已开始的 4xx 用 `v15_provider_reject_started`：attempt → `unknown`（计 1 次 call、不计 cost），invoke 提交类 `V15_PROVIDER_REJECTED`，`fatal = false`，不插入下一 attempt。未开 socket 的本地拒绝用 `v15_provider_reject_unstarted`：不 mark，attempt → `failed`（不计 call），同一 invoke 终态码。传输失败用 `v15_provider_abandon`：attempt → `unknown`（同样计 call），**不**结束 invoke，同事务做与回收相同的 invoke 收回，使下一轮可以重试，而不干等租约。理由：E26、E27；短租约方案在 402 上仍会打满 `max_io_attempts`。
2. **不扩展 `llm` 键集。** `model` / `temperature` / `max_output_tokens` 仍是唯一三键。key、base URL、HTTP 超时、租约是进程环境与 `Worker` 构造参数，不进 `resolved_config`，避免 key 被折叠进 `config_digest`。（jaz `OpenAILLM` 已把 key 挡在序列化配置之外，同一理由。）
3. **缺 usage：fail-closed。** 价目在 `v15/provider/pricing.py` 的版本化字面量，不运行时拉网，不引用 jaz JSON。`compute_cost` 对「无法计价」返回 `None`。适配器把 `None` 变成 abandon `unpriced`，**不得**以 `cost_usd = 0` settle。字段齐全且全是 0 token 时，成本才是真正的 `Decimal('0')`。理由：jaz 对未知模型返回 `None`，并写明 0 会废掉预算上限。（observation，`jaz/src/jaz/llm/pricing.py`）
4. **本次仅 `deepseek-flash`；冒烟只打 flash。**（用户裁决）`v4-pro` 不在 allowlist：`preflight` 直接 `model_not_allowlisted`，价目表只有 flash 两档。后续版本扩入 pro 时须按 §18 同一修订写入官方价（含 cache-hit 档）与规格句子；禁止在本次实现里预留 pro 分支或猜测价格。
5. **冒烟是独立脚本，不是九道 gate 里的 flag。** `v15/provider/smoke.py`。gate 文件即使误传 `--real-provider-smoke` 也不读这个 flag。退出码对齐 v8：无 flag → 0（`not_requested`）；有 flag 无 key → 2（`credentials_absent`，且 `complete` 未被调用）；开打后失败 → 1，禁止降级成 `not_run`。

额外裁决：

- **新增 stage 10，不加表。** 收据不建 `provider_receipts`。最小分类进 `invoke_events` 审计 payload；成功时的 usage 作为 `llm_attempts.response` 的额外键（settle 不拒绝未知键）。加表会违反 §15「不得再增加表」，也会把供应商正文带进新的权威行。
- **不改 `v15_on_phase`。** provider 不是 hook。
- **`prompt_tokens` 越界：abandon `usage_invalid`，不钳位、不 settle。** 2^31−1 token 不是预期流量，是畸形 usage。钳位会少报。
- **NUL：** `statement_payload` 继续对原始 `content` 调用 `split_sql`（已有合成失败路径）。另把送入 `p_response` 的 `content` 做同样的六字符替换。先替换再切分是错的：替换后的正文可以被当成普通 SQL 切开，丢失 `V15_VALUE_INVALID`。实现第一步读 `v15/protocol/split_sql.py` 核对；只有与 `test_io` 的 NUL 断言不一致时才改切分器，并重跑 stage 4 与 stage 6。
- **适配器内不做 HTTP 重试。** 一次 attempt 一次 `urlopen`。429/500 走 abandon，由 `max_io_attempts` 限制后续 attempt。这与 v8「不重试、失败即 unknown」一致；v15 的重试单位是 attempt 行，不是同一次 socket 循环。worker 在 abandon **提交之后**、会话空闲时，若 `http_status = 429` 固定睡 1 秒（不读 `Retry-After`——DeepSeek 不保证提供，且传输层已不返回头；评审 F4）。睡眠是**本进程尽力节流**，不是速率协调：invoke 已回 `runnable`，另一 worker 可能立即接手（评审 F9）。
- **`reasoning_content` 丢弃，不进入 `content`，不写入 `llm_messages`。** 思考文本不是程序，写进去会被当成 SQL。审计只可带 `reasoning_chars`（整数），不带正文。
- **`finish_reason`：** 见下方分类表。`insufficient_system_resource` 与 `aborted` 即使 HTTP 200 也不 settle。
- **思考模式默认开着的 allowlist 模型不发送 `temperature` 与 `top_p`。** 折叠进 `resolved_config` 的 `temperature` 保持原样，只是不上线。不新增 thinking 开关。`max_output_tokens` 若存在，映射为线协议字段 `max_tokens`。

### 为什么不是更小的补丁，也不是大重构

只换 `Worker` 里的对象、不加重 SQL，挡不住 402：E27。只把租约改到 10 秒会让慢成功无法 settle（E25），并且仍烧 calls（E26）。把 DeepSeek 塞进 `FakeLLM` 会破坏 `test_io` 的 import 扫描，也会让 gate 持有连网类型。

新 stage 而不是把函数追加进 `v15_io.sql`：**前缀 stage 1–9 的 SQL 文件字节保持不动**（共享的 `worker.py`/`fake_llm.py` 在 M2 会改，九道回归照跑——评审 F11 措辞修正）。stage 10 用 `CREATE OR REPLACE` 只扩展映射函数的一个分支。不抽新的 provider 框架、不引入第二套循环、不改 settle 签名。

### 组件

#### 1. 错误类型 — `v15/provider/errors.py`

模块种类：库内异常，无 I/O。`v15/provider/__init__.py` 只写文档字符串，**不得** import `deepseek` 或 `urllib`。worker 只 import 本模块，因此九道 gate 加载 worker 时不会加载 HTTP 客户端。

三个类型，都带只含分类、不含正文与 key 的 `detail: dict`：

- `ProviderPreflight` — mark 之前。worker 调 `v15_provider_reject_unstarted`。
- `ProviderRejected` — 已 mark、确定性失败。worker 调 `v15_provider_reject_started`。
- `ProviderUncertain` — 已 mark、结果不明。worker 调 `v15_provider_abandon`。

`detail` 的键在 Python 侧就凑齐，SQL 再拒多余键。异常的 `str` 只能是稳定类名，不得内嵌 key、Authorization、响应体或提示词。

#### 2. 适配器 — `v15/provider/deepseek.py`

种类：普通类，不是 `FakeLLM` 子类。FakeLLM 继续无时钟、无随机、无 socket。两者只在 `complete` 的位置参数上对齐。

构造：

```text
DeepSeekProvider(
  api_key: str | None = None,
  base_url: str | None = None,
  timeout_s: float = 120.0,
  transport: Transport | None = None,
  clock: Callable[[], datetime] | None = None,
)
```

- `api_key`：参数，否则 `DEEPSEEK_API_KEY`，否则 `OPENAI_API_KEY`，否则 `""`。构造时允许读 env。**不**在 import 时读，**不**开 socket。
- `base_url`：参数，否则 `OPENAI_API_URI`，否则 `https://api.deepseek.com/v1`，去掉末尾 `/`。
- `timeout_s` 默认 120。必须 `> 0` 且 `< 600`（留在 DeepSeek 10 分钟服务端切断之下）。
- `transport` 默认是下面的 stdlib 传输。测试注入替身。
- `clock` 默认 `lambda: datetime.now(ZoneInfo("Asia/Shanghai"))`。计价用响应返回后的这一下，不用请求开始时间。

```text
preflight(llm_config: dict) -> dict | None
```

同步，无 I/O，无异常穿越 socket。返回 `None` 表示可以 mark。否则返回 unstarted 的 `detail`（worker 不把它当成已开始的调用）。

闭合原因：

| 条件 | class |
|---|---|
| `api_key == ""` | `credentials_absent` |
| `llm_config` 不是对象，或 `model` 缺失 / 不是非空字符串 | `model_missing` |
| `model` 不在 `{deepseek-flash}` | `model_not_allowlisted` |
| URL scheme 不是 `https`，或 host 为空 | `endpoint_rejected` |

`deepseek-chat`、`deepseek-reasoner`、`fake` 都走 `model_not_allowlisted`。这是预检，发生在 mark 之前，所以不计 `calls_used`。

```text
complete(logical_digest: str, n: int, request: dict, llm_config: dict | None = None) -> dict
```

`FakeLLM.complete` 增加可选第四参 `llm_config=None` 并忽略它。位置调用（`test_io.py`）不变。真实适配器 **使用** `llm_config`，忽略 digest 与 `n`（它们是 SQL 的重试身份，不是线协议字段；不发送 Idempotency-Key）。

`llm_config is None` 视为 `model_missing`，但是 **已 mark 之后** 的编程错误：抛 `ProviderRejected`，class `request_invalid`。worker 只有在 `preflight` 返回 `None` 之后才会 mark，正常路径不会撞上。

成功返回的 dict：

```text
{
  "content": str,             # 原始 message.content，NUL 可仍在；worker 负责替换
  "prompt_tokens": int,       # 必须是 int，不是 float
  "cost_usd": Decimal,        # >= 0；worker 按十进制文本写入 jsonb
  "provider": { ... }         # 见下，可选但本适配器总是带
}
```

`provider` 闭集：`id`（仅当匹配 `^[A-Za-z0-9_-]{1,80}$`）、`model`（响应里的模型名字符串，截断到 80，否则省略）、`finish_reason`（字符串或 JSON null）、`usage`（下面四个整数）、`pricing_revision`（与价目常量相同）、`peak`（bool）、`priced_at`（计价时刻的 ISO-8601 字符串，评审 F1）、`reasoning_chars`（int，无思考则为 0）。**所有进入该 dict 的字符串先做 NUL→六字符 `\u0000` 替换并剔除控制字符**（评审 F1：metadata 里的 NUL 同样会炸 jsonb 结算）；不得包含 `reasoning_content` 文本、原始 body、请求头。

线协议 body（UTF-8 JSON）：

```text
{
  "model": <llm_config.model>,
  "messages": [{"role", "content"} ...],  # 按 request.messages 原顺序，丢掉 seq/message_id/kind
  "stream": false
}
```

`max_output_tokens` 存在且为 `>= 1` 的整数时加 `max_tokens`——`v15_jsonb_posint` 接受 `10.0` 这类整值 float（`v15_config.sql:1-21`），worker 在读取 `llm` 配置时把整值 number 归一成 Python `int`，不得因类型静默丢弃已通过校验的上限（评审 F10）。**不**发送 `temperature`、`top_p`、`thinking`、`reasoning_effort`。messages 的 role 不是 `system`/`user`/`assistant`，或 content 不是字符串：`ProviderRejected` / `request_invalid`（同一份 messages 会被重试复制，再打也是 400）。

传输：

```text
post(url: str, body: bytes, headers: dict, deadline: float) -> tuple[int, bytes]
```

`deadline` 是**单调时钟绝对时刻**（见下「总期限」）。默认实现：`urllib.request`，`ProxyHandler({})` 不走环境代理（避免把 `Authorization` 交给环境代理），自定义 redirect handler **不跟随** 3xx（301/302/303/307/308 原样作为响应状态返回）；`HTTPError`（4xx/5xx）被捕获并转成 `(status, body)` 正常返回，不作为异常穿越。读取用分块循环（`resp.read(65536)`），每块后查单调钟，超过 `deadline` 即 `resp.close()` 并按超时处理；累计读取上限 10 MiB，超限同样关闭并按超时处理。`TimeoutError`、`urllib.error.URLError`、`OSError`、不完整读取 → `ProviderUncertain` class `transport`、`http_status` JSON null。异常与日志不得携带 URL 用户信息、头或响应体。

**gate 的断网点是传输边界本身**：patch/替换 `DeepSeekProvider` 的默认传输函数（或其 opener 构造），而不是 `urllib.request.urlopen`——私建 opener 经 `OpenerDirector.open` 分发，不经 `urlopen`；只罩 `urlopen` 是假阴性（评审 F4）。proxy/redirect 行为在注入传输上断言 opener 配置（`ProxyHandler({})`、无 redirect 跟随）。

HTTP 分类（worker 政策；SQL 用范围兜住，避免合法分类被 `P1524` 打回滚而把 attempt 留在 `leased`）：

| 结果 | 动作 | detail.class | http_status / finish_reason |
|---|---|---|---|
| 无响应、超时、断连、body 不是 JSON | abandon | `transport` | status 空；若已有 3xx 则把该状态放进 http_status |
| 3xx（不跟随重定向） | abandon | `http_status` | 该码 |
| 2xx 但非 200（如 201/204） | abandon | `finish_reason` | 字面量 `other` |
| 408、429 | abandon | `http_status` | 该码 |
| 500–599 | abandon | `http_status` | 该码 |
| 400 且 error.message 小写后含 `could not parse the json body` | abandon | `transport` | 400 |
| 400–499，除 408 与 429，以及上面的瞬态 400 | reject | `http_status` | 该码；**状态先行**——body 不是 JSON 也不影响按状态分类（HTML 错误页照常 reject） |
| HTTP 200，`finish_reason = content_filter` | reject | `finish_reason` | `content_filter`，http_status 空 |
| HTTP 200，`finish_reason` 为 `insufficient_system_resource` 或 `aborted` | abandon | `finish_reason` | 该字符串 |
| HTTP 200，`content` 不是字符串（含 JSON null、缺 choices、只有 `reasoning_content`）或 choices/usage 结构畸形（非对象、非数组） | abandon | `finish_reason` 若原因未知则用字面量 `other` | 不把思考文本当 content；结构校验先于任何键索引 |
| HTTP 200，响应 `model` 存在且 ≠ 请求的 `deepseek-flash` | reject | `finish_reason` | 字面量 `model_mismatch` | 计价身份破坏，确定性拒绝 |
| HTTP 200，`content` 是字符串（含 `""`），`finish_reason` 为 `stop`、`length`、缺失，或其他不在上表的值 | 进入 usage 计价；`length` 照样 settle，截断 SQL 由既有「散文 → continue」处理 | | |
| usage 缺字段、类型不对（**Python `bool` 是 `int` 子类，必须显式排除**）、hit+miss ≠ prompt_tokens、任一计数 `< 0`、`prompt_tokens` 或 completion `> 2147483647`、非整数、cost 计算结果非有限 Decimal | abandon | `usage_invalid` | |
| `compute_cost` 返回 `None` | abandon | `unpriced` | |
| 计价成功 | 返回成功 dict | | |

空字符串 `content` 是成功：§4.11 空消息消耗一次迭代。不要把空串改成 uncertain。

`content_filter` 即使带了字符串也不 settle，避免把过滤残留当程序执行。

冒烟若发现 flash 经常「`content` 为 null、答案只在 `reasoning_content`」，**停**，不要偷偷把思考文本拼进 `content`。那是另一次规格修订。

#### 3. 价目 — `v15/provider/pricing.py`

```text
PRICING_REVISION = "deepseek-2026-09-29"
compute_cost(model, *, prompt_cache_miss_tokens, prompt_cache_hit_tokens,
             completion_tokens, at: datetime) -> Decimal | None
```

`None` = 无法计价。不要用 0 表示未知。纯函数：无 I/O、无全局时钟。`at` 必须是 aware；naive → `None`。

发布价（USD / 1M tokens），来自底稿，空闲 = 高峰的一半。存成 `Decimal(每百万价格) / Decimal(1000000)`，禁止 float 费率。

| model | 档 | miss / 1M | hit / 1M | output / 1M |
|---|---|---|---|---|
| `deepseek-flash` | 空闲 | 0.14 不对，是 **0.15** | **0.003** | **0.60** |
| `deepseek-flash` | 高峰 | **0.30** | **0.006** | **1.20** |

flash 的 0.15/0.30 一对里，较小者是空闲（底稿「空闲=半价」）。`deepseek-v4-pro` 不在价目表（用户裁决 B）：`compute_cost` 对它返回 `None`（未知模型），`preflight` 在更早处已以 `model_not_allowlisted` 拒绝。

高峰（实现假设，M2 必须用 https://api-docs.deepseek.com/quick_start/pricing 核对边界分钟）：`Asia/Shanghai` 的周一至周五，本地时间半开区间 `[09:00, 12:00)` 与 `[14:00, 18:00)`。周末不是高峰。**不**内置国务院节假日日历：假日若落在周一至周五，按高峰计价，方向是多报成本，`cost_limit` 仍安全。官方若把 12:00 或 18:00 算进高峰，同一提交里改不等式和规格句子，不另开行为。

```text
cost = miss * miss_rate(peak) + hit * hit_rate(peak) + completion * output_rate(peak)
```

结果 `quantize(Decimal("0.000000000001"), ROUND_HALF_UP)`。全 0 token 且费率存在 → `Decimal("0")`。没有 cache-creation 附加费；底稿没有这项，不要发明。completion 含思考 token，全部按输出价，不单列。

与 jaz `compute_cost` 的差异是故意的：这里没有 service tier、没有长上下文 overage、缓存桶是 hit/miss 而不是 creation/read，未知是 `None` 而不是让调用方把缺省当 0。

#### 4. SQL 转移 — `v15/provider/v15_provider.sql`

三个 `SECURITY DEFINER`、owner `v15_owner`、`SET search_path = pg_catalog`。体内禁止 `SET ROLE` / `RESET ROLE` / `SET SESSION AUTHORIZATION`。`EXECUTE` 只授 `v15_worker`，`REVOKE ALL FROM PUBLIC`。不 `GRANT` 给 `v15_repl`。

签名：

```text
v15_provider_reject_unstarted(
  p_attempt_id uuid, p_attempt_fence bigint,
  p_invoke_fence bigint, p_owner text, p_class text
) returns void

v15_provider_reject_started(
  p_attempt_id uuid, p_attempt_fence bigint,
  p_invoke_fence bigint, p_owner text, p_detail jsonb
) returns void

v15_provider_abandon(
  p_attempt_id uuid, p_attempt_fence bigint,
  p_invoke_fence bigint, p_owner text, p_detail jsonb
) returns void
```

共用前置，顺序照 `v15_settle_llm`，不自造锁：

1. `v15_repl_require_worker()`。
2. 由 attempt 找到 invoke；参数空、owner 长度不在 1..200 → `P1524`。
3. `v15_repl_lock(invoke)`，再 `FOR UPDATE` attempt。
4. status 已是 `unknown` / `failed` / `settled` → **先** `V15_ATTEMPT_NOT_SETTLEABLE`（`P1502`），不看栅栏。（§4.13）
5. 栅栏不符 → `P1501`。owner / 租约 / invoke 不是 `leased` → `P1523`（`v15_repl_check_holder`）。
6. unstarted 要求 `call_started = false`；另两个要求 `call_started = true`。相反 → `P1523`。
7. 迭代 status 必须是 `llm`。否则 `P1523`（防止在 exec 窗口误用）。

`p_class` / `p_detail` 非法 → `P1524`，整笔回滚，attempt 仍 `leased`。这是 worker bug，不是 provider 结果。

`p_detail` 键恰好 `class`、`http_status`、`finish_reason`。多键或少键 → `P1524`。

- reject_started：`class = http_status` 且 `http_status` 为 400..499 且不是 408/429，`finish_reason` 为 JSON null；或 `class = finish_reason` 且值恰好 `content_filter`，`http_status` 为 JSON null；或 `class = request_invalid` 且另两键为 JSON null。
- abandon：`class = transport` 且 `finish_reason` 为 null，`http_status` 为 null 或 3xx 或 400；或 `class = http_status` 且状态是 400、408、429 或 500..599，`finish_reason` 为 null；或 `class = finish_reason` 且值属于 `{insufficient_system_resource, aborted, other}`，`http_status` 为 null；或 `class` 属于 `{unpriced, usage_invalid}` 且另两键为 null。
- unstarted 的 `p_class` 属于 `{credentials_absent, model_not_allowlisted, model_missing, endpoint_rejected}`。

**unstarted 写入（一个事务）：**

1. `v15_io_pool_release(pool, reserved_calls, reserved_cost, false, 0)`。用行上存放的预留量，不写死 1 与 0。
2. attempt → `failed`，`calls_charged` 保持 false，清空 attempt 租约，`response` 保持 NULL。这满足 `llm_attempts_failed`。
3. `llm_requests.status → exhausted`。
4. 审计 `{"op":"provider_rejected","attempt_id","class","call_started":false}`。
5. `v15_io_terminal(invoke, iteration, 'V15_PROVIDER_REJECTED', false, attempt_id)`。

**started reject 写入：**

1. `v15_io_pool_release(..., charge_calls true, cost delta 0)` — unknown 公式。
2. attempt → `unknown`，`calls_charged = true`，清空 attempt 租约，`response` 保持 NULL。不得写助手消息，不得插 `statements`。
3. request → `exhausted`。
4. 审计同上但 `call_started: true`，并带 `http_status` 与 `finish_reason`（null 用 JSON null）。
5. 同一个 `v15_io_terminal(..., 'V15_PROVIDER_REJECTED', false, ...)`。

不写 `llm_query/retry`。这次不是「以后还会 begin」。`v15_io_terminal` → `v15_io_close_self` 会把迭代收成 `done`/`continue`、写 `repl_history`（尚无助手消息则 `llm_response = ''`）、invoke `failed`、`fatal = false`、关 `llm_query`（outcome `failed`）、关 invoke span、`DROP SCHEMA … CASCADE`。有父则走已有的 §4.8：父语句 `V15_CHILD_ERROR`，子行保留 `V15_PROVIDER_REJECTED`。不要在新函数里重写送达。

**abandon 写入：**

1. 与 started reject 相同的池释放与 attempt → `unknown`。
2. **不**把 request 改成 `exhausted`，**不**调用 `v15_io_terminal`，**不**调用 `v15_on_phase`（对齐 §4.10）。
3. `llm_query/retry`，payload 在既有三键之外加嵌套对象，避免改掉回收路径已经写死的形状：

```text
{
  "old_attempt_id": <uuid>,
  "old_status": "unknown",
  "new_attempt_id": null,
  "provider": { "class", "http_status", "finish_reason" }
}
```

4. 然后调用已有的 `v15_io_reclaim_invoke(invoke)`。此时没有存活 `leased` attempt，迭代在 `llm`、没有 `running` 语句，该函数把 fence `+ 1`、status `runnable`、清空 invoke 租约，并写 `lease_reclaimed`。不要再手动 bump 一次。span 保持打开，直到后来的 settle 或 `V15_IO_EXHAUSTED`。

`v15_io_error` / `v15_io_terminal` 依赖 `v15_io_sqlstate` 的 CASE。stage 10 **`CREATE OR REPLACE`** 这个函数，只加：

```text
WHEN 'V15_PROVIDER_REJECTED' THEN 'P1539'
```

签名不变，oid 保持。不要 `DROP FUNCTION`。prefix 到 govern 的库看不到这支，stage 6 行为不变。

**实现期补充（M1 交互裁决）**：`v15_govern_known_code`（govern SQL）的已知码白名单止于 P1538——hook 返回 `V15_PROVIDER_REJECTED` 会在归一之前被 `P1506` 拒绝，rev 9 的「hook 带回此码仍归一 `V15_HOOK_ABORT`」句子无法成立。stage 10 在 `v15_provider.sql` 里 `CREATE OR REPLACE v15_govern_known_code`，仅追加 `V15_PROVIDER_REJECTED`（签名/oid 不变，不动 govern 文件）；§18 的替换点授权清单与 `v15_io_sqlstate` 并列加入这一处；gate 增加归一回归用例（测试 hook 返回 P1539 码 → 合成为 `V15_HOOK_ABORT` 提交，不因 P1506 被拒）。

实现时必读（不读不准写 SQL）：

- `v15_repl_sqlstate` 与 `v15_repl_deliver_nonfatal`（多半在 `v15/repl/v15_repl.sql`）。若送达或 fatal 展开用 CASE 白名单校验子码，在 **`v15_provider.sql` 里 `CREATE OR REPLACE` 那个小映射**，加入 `V15_PROVIDER_REJECTED` → `P1539`。不要改 repl 文件本身，否则 stage 5 的源文件变化会搅进前缀审查。若非 fatal 送达写死父码 `V15_CHILD_ERROR`、不查子码映射，则不要替换。
- `v15_on_phase` 的 exit 路径（`v15/govern/v15_govern.sql`）。规格要求 exit 只许黑板写。确认它 **不会**再动 `budget_pools`。若会第二次释放，reject 会在 `v15_io_pool_release` 上 `P1523` 整笔回滚。那样就只保留 terminal 内部的那一次释放，本函数不提前释放。以读到的 govern 正文为准。
- `v15_repl_close_span` 对未打开的 span。`v15_io_close_self` 今天已经对 `repl_exec` 无条件调用（迭代上限路径），因此应当是 no-op。若不是，reject 不得复制一份会报错的关闭，应先修 close_span 的 no-op 语义（那是既有 IO 终态路径的 bug，单独在本次提交里修，并给 stage 6 加一条「未打开的 repl_exec 关闭不抛」若还没有）。

错误对象 message 维持既有 helper 的空串（`v15_io_close_self` 现构 `v15_io_error(p_code, '')`，IO SQL:180；本 stage 不改 helper）。分类细节只进审计事件 payload（`class` / `http_status` / `finish_reason`）。gate 断言 `sqlstate = P1539`、`code = V15_PROVIDER_REJECTED`、`fatal = false`、`error.message = ''`，并断言审计行携带分类三键。不为消息传播扩展 `v15_io_terminal` / `v15_io_close_self` 签名（评审 F3 采纳小方案 1）。

exit phase 若返回 abort，既有 `v15_io_exit_query` 抛 `V15_INVALID_EFFECT`，整笔 reject 回滚，attempt 仍 `leased`。这与今天 `V15_IO_EXHAUSTED` 的 exit 规则相同，不要为了「一定写上拒绝」而跳过 `v15_on_phase`。恢复仍靠租约到期后的 `v15_reclaim_expired`（它不调 phase）。规格里写明这条残留：坏的 exit hook 可以把确定性拒绝退回到 unknown-再试。不在本次修 hook 代数。

#### 5. worker 接线 — `v15/worker.py`

`run_until_quiescent(db_dsn, fakellm, worker_id, *, lease: str = "30 seconds")`。`Worker` 保存该值。`claim` 使用 `self.lease`，不再读模块常量当唯一来源。模块级 `LEASE` 保留为默认值的名字。既有位置参数调用不变。`_mark_and_settle` 的三处调用点（`worker.py:215`、`:237`、`:262`——评审 F2 确认共三处而非两处）都传入 `snap["resolved_config"]["llm"]`；`:215` 的早分支若与 `drive` 冗余，可在同一提交里显式删除并保留覆盖。

（已删除 `exec_enabled`——评审 F8：暂停态留下可执行语句的 leased invoke，后续任何 worker 都会回收并执行；冒烟改为适配器-only，见 §7。）

`_mark_and_settle(invoke_id, fence, attempt, llm_config)`。两处调用点（`_llm` 与 `drive` 里「leased 且尚未 call_started」）都传入 `snap["resolved_config"]["llm"]`。

顺序：

```text
if provider 有 preflight:
    detail = preflight(llm_config)
    if detail is not None:
        _run(v15_provider_reject_unstarted(...))   # 不 mark
        return
_run(mark)
assert IDLE
try:
    response = provider.complete(digest, n, request, llm_config)
except ProviderRejected as exc:
    assert IDLE
    _run(v15_provider_reject_started(..., exc.detail))
    return
except ProviderUncertain as exc:
    assert IDLE
    _run(v15_provider_abandon(..., exc.detail))
    # 仅此时、且事务已提交之后：429 的有界 sleep
    return
except ProviderPreflight:
    raise   # 已 mark 之后出现就是编程错误，不 settle、不 abandon
# FakeLLM KeyError 继续向上抛，不 abandon、不 settle

raw = response["content"]
payload = statement_payload(raw)          # 原始 NUL，交给 split_sql
sql_content = raw.replace("\x00", "\\u0000")
# cost_usd 若是 Decimal：把其余字段 json.dumps 后，把 cost 以十进制字符串
# 拼进 JSON 文本，再 ::jsonb 交给 settle。int/float 的 FakeLLM 路径仍走 Json(dict)。
_run(settle)
```

`drive` 开头「别人留下的 `call_started = true`」仍直接 return。新异常处理只发生在 **本进程刚刚 mark 成功** 的那一次 `_mark_and_settle` 里。

abandon/reject 的 SQL 若得到 `P1502`：不再 settle、不再打 provider。下一轮扫描会看到回收或拒绝已经留下的状态。`40001`/`40P01` 仍由 `_run` 整段重试 **SQL**，不重放 HTTP。

settle 成功之后的执行循环不改。

真实 driver（冒烟与将来的手工运行）构造：

```text
DeepSeekProvider(timeout_s=120)
Worker(..., lease="180 seconds")   # 仅手工全链运行；冒烟不进 DB
```

构造时断言租约秒数 `>= timeout_s + 60`。60 秒是 mark 前后 SQL 与 settle 的余量，不是新的规格常数进 `governance_manifest`。FakeLLM 默认仍是租约 30 秒、无 HTTP。

**总期限与剩余租约（评审 F5）**：`timeout_s` 是**单调总期限**（默认 120 秒），不是 per-blocking-op 超时——分块读取循环逐块检查单调钟（`time.monotonic()`），到点关闭响应并按 `transport` 超时处理；慢滴流响应不会突破总期限。worker 在调用 provider 之前检查 `lease_until - now >= timeout_s + 60s`，不足则不发起调用（attempt 留待租约到期回收）；该检查在每次 `_run` SQL 重试之后、HTTP 之前重新做。gate 用注入的单调钟与分块 reader 断言：延迟头、滴流体、pre-HTTP 延迟、迟到返回，均以关闭+abandon 收束，不真睡 120 秒。

三只时钟，写进 `v15/worker.py` 模块注释与 `v15/provider/README.md`：

| 时钟 | 值 | 管什么 |
|---|---|---|
| `_begin` 的 `statement_timeout` | 30s | 转移 SQL。与 HTTP 无关，不加大 |
| FakeLLM `lease` | 30s | 崩溃后回收。gate 保持 |
| 真实 HTTP `timeout_s` | 120s | 客户端放弃。早于服务端约 10 分钟的「未开始推理即断连」 |
| 真实 `lease` | 180s | 必须盖住 HTTP + settle。慢成功仍能 settle；崩溃恢复从 30s 变为 180s，只在真实 provider 的 Worker 上 |

不确定窗口被接受：客户端 120s 超时之时，服务端可能已经开始计费。attempt 记 unknown，计 calls、不计 cost。供应商发票可以高于 `cost_used`。不发送幂等键（API 没有这个契约，发了是假的）。

**同质 provider 前置（评审 F9）**：一个 `agent_v15_*` 库的 worker 池必须同质（全 FakeLLM 或全同一个真实 provider）——默认 profile `model=fake` 会被 DeepSeek worker 以 `model_not_allowlisted` 终态拒绝，反之 FakeLLM worker 会对真实 invoke 抛 KeyError 后留下已 mark 的 attempt。此前置写进 `v15/provider/README.md` 与规格 §4.5.5 一句话；不引入路由框架，不做 model-aware claim（留待真实需求）。
**取消与迟到矩阵（评审 F9）**：同一已 mark 的 attempt 永不重发 HTTP；迟到结果只能落到 `P1502`（已终态）或 `P1501`（旧栅栏）并被丢弃；`_run` 只重试 SQL（40001/40P01），不重放 HTTP；worker 退出路径（正常与异常）关闭传输响应与 DB 连接。endpoint/key 在崩溃恢复的两次 attempt 之间允许不同（环境级配置），不持久化任何秘密。

#### 6. 数据流 `llm.model` → 线协议

```text
config_profiles.llm.model
  → v15_resolve_config（键集仍由 v15_check_component 执法）
  → invokes.resolved_config / config_digest（open 时冻结）
  → v15_loop_snapshot 的 resolved_config
  → Worker 读 snap["resolved_config"]["llm"]
  → preflight allowlist
  → complete() 的 JSON "model"
```

种子 profile `00000000-0000-4000-8000-0000000000a1` 保持 `fake`。冒烟与真实运行注册 **另一份** profile，不 `UPDATE` 种子。否则所有「不覆盖配置」的 gate 会改语义。

代码实证（评审 F2）：`v15_loop_snapshot`（`v15/loop/v15_loop.sql:583-591`）原样传出整块 `resolved_config`，`llm` 已可用——**无需任何 snapshot 改动**；worker 侧的配置流测试照写。

`temperature` 留在冻结配置里供人读，适配器丢弃。这是相对 jaz（jaz 会把 temperature 放进请求）的偏差，记 V15-D27。

#### 7. 测试形态

**Gate** `v15/provider/test_provider.py`：`uv run python v15/provider/test_provider.py`，退出码 0。`main` 的第一件事：从 `os.environ` 删除 `DEEPSEEK_API_KEY`、`OPENAI_API_KEY`、`OPENAI_API_URI`、`OPENAI_MODEL`。然后把 `urllib.request.urlopen` patch 成 `AssertionError("network")`。patch 不得替换 `socket`（会弄坏本机 Postgres）。纯计价测试放在 `setup_db()` **之前**。

文档中的包装（uv 会在进程启动前注入 `.env`，所以进程内 pop 之外还要写进 README）：

```bash
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL \
  UV_NO_ENV_FILE=1 \
  uv run python v15/provider/test_provider.py
```

九道既有 gate 也用同一包装重跑。gate 进程内的 pop + `urlopen` patch 是 provider gate 的硬断言；包装是仓库纪律。

Hermetic 用例（每条都断言 `urlopen` 未被默认传输调用；注入的 transport 计数另计）：

计价（无 DB）：

- 周一 10:00、13:00、12:00、18:00、周六 10:00 的 `Asia/Shanghai` aware 时间，高峰判定与上表一致。12:00 与 18:00 按当前半开假设是空闲；若官方页相反，改测试与函数一起提交。
- flash：miss=1_000_000、hit=0、completion=0、空闲 → `Decimal("0.15")` 量化后的精确值。hit 与 output 各做一条精确值。
- hit+miss 与 prompt 不一致不在价目函数里做（适配器做）；价目函数只接收三个计数。
- `deepseek-v4-pro` → `None`（不在价目表；与未知模型同路）。
- 未知模型 → `None`。naive datetime → `None`。

SQL，超级用户 seed + `v15_worker` 调用，池非空：

- unstarted `credentials_absent`：不 mark。attempt `failed`，`call_started` false，`calls_charged` false，`calls_used = 0`，预留回到 0。invoke `failed`，`fatal` false，`error.sqlstate = P1539`，`error.code = V15_PROVIDER_REJECTED`，message 为稳定拼写。无 `kind = assistant` 的 `llm_messages`。scratch schema 不存在。`llm_query` 有 enter、send、exit `failed`，无 `complete`。
- started HTTP 402：transport 被调用 1 次。attempt `unknown`，`calls_charged` true，`calls_used = 1`，`cost_used = 0`，`response` NULL。invoke 同上 P1539。再 `run_until_quiescent` 也不会第二次调用 transport（invoke 已终态，扫描不返回它）。
- started HTTP 401、422、404、403、400（普通）与 499：同 402 的终态形状。400 瞬态 “could not parse the json body” 走 abandon，invoke 回到 `runnable`，不是 P1539。
- `content_filter`：reject，即使 content 非空；库里没有这段 content。
- timeout / `URLError` / 503 / 429：attempt `unknown`，`calls_used = 1`，invoke `runnable`，fence 比 claim 之后再加 1，`llm_query` span 仍 open，retry 事件 `new_attempt_id` 为 JSON null 且含 `provider.class`。无助手消息。
- `max_io_attempts = 1`，第一次 transport 失败 abandon，再次 begin 得到 `V15_IO_EXHAUSTED`，transport 次数仍为 1，没有 `n = 2` 的行。
- 脚本：第一次 transport 失败，第二次返回可计价 200。`calls_used = 2`，`cost_used` 等于第二次的成本，第一次的成本不在 `cost_used` 里。第二行 `settled`。
- usage 缺 `prompt_cache_hit_tokens`、或 prompt_tokens = 2147483648、或 hit+miss 不一致：abandon `usage_invalid` 或 `unpriced`，无助手行，`cost_used = 0`。
- HTTP 200、content `""`、usage 全 0：settle，`cost_usd = 0`，`prompt_tokens = 0`，语句 0 条，迭代可被后续 finish 走空消息。本 gate 可以只断言 attempt `settled` 与 content `""`，不必跑 finish（stage 7 已证明空消息）。
- 对 unknown 或 failed 的 attempt 再 reject/abandon/settle：`P1502`，转录不变。旧 fence：`P1501`。
- 子 invoke：父 bind-wait，子在 llm 窗口被 402 reject。子 error 为 `V15_PROVIDER_REJECTED`；父语句 `V15_CHILD_ERROR`；父不是 `aborted`（`fatal = false`）。形状必须满足 `v15_repl_assert_bind_wait`，不允许为了测试改助手。
- 额外键的 `p_detail`：`P1524`，attempt 仍 `leased` 且 `call_started` 仍为调用前的值。
- 三个新入口的 ACL/身份（评审 F10）：`v15_repl` 与非 worker `session_user` 调用 → `42501`/`P1522`；错误 owner、过期租约 → `P1523`；`p_class` 不在闭合集 → `P1524`。
- 存储预留量记账（评审 F10）：`reserved_calls = 3`、`reserved_cost = 0.5` 的 attempt 走 started reject 与 abandon，池的释放/入账按行上存储值，不写死 1/0。
- FakeLLM + `run_until_quiescent` 在 provider 库上仍能把一条 `SELECT jaz."return"(...)` 跑到 `completed`（防 worker 回归）。provider 库已加载 loop/tree/govern，这条用 FakeLLM，不用 DeepSeek 类。
- worker NUL：FakeLLM content 含 `\x00`。settle 后的 `response->>'content'` 与语句 `sql` 含六字符序列且不含 NUL，语句 `failed` / `V15_VALUE_INVALID`，attempt `settled`。
- 线协议：注入 transport 捕获 body。`deepseek-flash` 的 JSON 无 `temperature`、无 `top_p`、`stream` 为 false；`max_output_tokens` 变成 `max_tokens`；messages 顺序与 request 一致且无 `message_id`。
- keyless：`DeepSeekProvider()` 在已 pop 的 env 下 `preflight` 返回 `credentials_absent`，transport 计数 0；断言 patch 的是传输边界而非 `urlopen`（见 F4）。
- 凭证优先级（评审 F1）：显式参数 > `DEEPSEEK_API_KEY` > `OPENAI_API_KEY` > `""`；`base_url` 显式参数 > `OPENAI_API_URI` > 默认。三段都有 hermetic 断言；并断言 **import 时不读 env**（构造时才读）。
- 冒烟辅助函数：`smoke.main([])` → 0 且不构造会调 `complete` 的路径；`main(["--real-provider-smoke"])` 在无 key 时 → 2，`complete` 未被调用。用 v8 那种 `side_effect=AssertionError` 罩住默认传输。

**冒烟** `v15/provider/smoke.py`（不要命名成 `test_*.py`）：

- 无 flag：打印一行 `not_requested`，退出 0，不读 key 是否存在（可以读也不调用；为对齐 v8，无 flag 时甚至不构造适配器）。
- 有 flag：构造 `DeepSeekProvider()`。无 key → 打印 `credentials_absent`，退出 2，不调用 `complete`。
- 有 key：**适配器-only**（评审 F8 裁决）：不建库、不 `setup`、不开 invoke——直接用一条固定的本地请求 `{messages:[{role:"user",content:"Reply with exactly: SELECT 1;"}]}` 调 `DeepSeekProvider().complete("<smoke>", 1, request, {"model":"deepseek-flash"})`。DB 结算路径由 provider gate 的 hermetic 用例证明，冒烟只证明真连的请求/usage/计价。
- 断言：恰好一次 HTTP；返回 dict 含 `content`（str）、`prompt_tokens >= 1`、`cost_usd >= 0`（Decimal）、`provider.pricing_revision` 等于常量、`provider.model = deepseek-flash`；**stdout/stderr 不打印** content、reasoning、key、Authorization。失败退出 1，异常信息换成 `real-provider smoke failed`，`raise ... from None` 丢掉响应文本。成功退出 0，只打印 host、模型名、`prompt_tokens`、`cost_usd`、`finish_reason`。
- 手工全链运行（真实 Worker + DB）在 README 记为「支持但不属于冒烟」：`Worker(dsn, DeepSeekProvider(), id, lease="180 seconds")`，运行者自担其库被模型 SQL 写入的后果。
- 不跑 pro。冒烟不是 gate。有 key 时人工跑；无 key 的退出码由 hermetic 用例覆盖。

#### 8. 规格与台账要改的句子

`docs/designs/v15-jaz-dev.md` 头：rev 9。修订说明追加一段：真实 provider 是 worker opt-in；attempt 终态集合不变；新增 `P1539`；`llm` 键集不变。

- §0.0：gate 仍不得开 socket。`v15/provider/smoke.py` 在显式 flag 下可以，且不是合运行时证明。
- §0.6：`unknown` 的写入者除 `v15_reclaim_expired` 外，增加 `v15_provider_abandon` 与 `v15_provider_reject_started`，记账公式相同。`v15_provider_reject_unstarted` 只在 `call_started = false` 时把 attempt 写成 `failed` 并结束 invoke。三种新函数都不调用 provider。abandon 不调用 `v15_on_phase`。两个 reject 走 `v15_io_terminal`。
- §1「不在本版行为内」删除「真实 provider」。补一句：真实 provider 不是 SQL 能力，模型 SQL 仍不能开 socket。
- §4.5 新小节 §4.5.5 写上三函数的前置、写入、事件、与 §4.8 的关系。写明 message 拼写与「exit abort 会回滚拒绝」的残留。
- §8.1 表下追加：endpoint、凭据、HTTP 超时不是 `llm` 的键。`model` 由 worker 选用 allowlist 适配器。`temperature` 可以折叠但不承诺送进每一个适配器。
- §12 / §15 关于 FakeLLM 唯一实现的那句改成：**gate 不开网络**；行为循环类 gate 的唯一 LLM 仍是 `v15/fake_llm.py`；`v15/provider/test_provider.py` 允许以**注入传输**构造 `DeepSeekProvider`（零网络，评审 F10）；`v15/provider/deepseek.py` 的默认传输只被 opt-in 驱动（冒烟/手工）构造。worker 接受带 `complete(logical_digest, n, request, llm_config=None)` 的对象。
- §0.19 的「38 个码、止于 P1538」句子同步改为「39 个码、止于 P1539」（评审 F10：修订清单不得漏改冻结句）。
- §13 加一行：`V15_PROVIDER_REJECTED` | `P1539` | 适配器预检拒绝，或已开始的确定性 provider 拒绝（§4.5.5） | 提交类，`fatal = false`。它 **不**进入 hook abort 可保留闭集；hook 若带回这个码，仍归一成 `V15_HOOK_ABORT`。
- §14 追加，且声明实现不得把它们修回 jaz：
  - **V15-D27.** jaz 会发送 `temperature`。v15 的 DeepSeek allowlist 模型不上送 `temperature` / `top_p`（思考模式默认开启时供应商忽略或拒绝）。值仍留在 `resolved_config`。
  - **V15-D28.** 供应商无幂等。unknown 之后的新 attempt 可能在供应商侧重复计费；`cost_used` 只含已 settle 的自算成本，可以低于发票。
  - **V15-D29.** `reasoning_content` 不是助手程序，不进 `llm_messages.content`。
  - **V15-D30.** 高峰只按上海时区周一至周五的两个半开窗口估算，不含法定节假日；假日可能被估成高峰（多报，不少报）。
- §15 表加第 10 行：`v15/provider` | `v15_provider.sql` | `test_provider.py` | 三转移、计价 fail-closed、keyless、不执行模型 SQL 的冒烟辅助退出码。合运行时改为十个文件都加载。`agent_v15_govern` 降为前缀。里程碑增加 M4（stage 10）：矩阵覆盖新码与 D27–D30，并写明十条 `SQL_LOAD_ORDER`。旧 M1–M3 不重开。
- §18 修订号改为 rev 9。最后一码改为 `P1539`。`P1540`–`P1548` 仍空着。

`docs/reviews/v15-conformance-matrix-2026-09-29.md`（`v15/README.md` 已点名）就地加行，不另开一份矩阵。每行是：不变量或码、`test_provider.py`、断言的是行为。至少包括：gate 不调用 `urlopen`；`P1539` 提交且 `fatal = false` 且无助手消息；started reject 的 `calls_used` 增、`cost_used` 不增、attempt `unknown`；unstarted 不计 call、attempt `failed`；abandon 后 invoke `runnable`、span 仍开、`new_attempt_id` 为 null；缺 usage 不会以 0 settle；wire 上无 temperature；`reasoning_content` 不在助手正文里。

偏差台账：仓库里 `docs/reviews/v15-deviation-ledger-*.md` 若存在，追加 D27–D30；若有多份，改最新一份。若不存在，新建 `docs/reviews/v15-deviation-ledger-2026-09-29.md`，写 D27–D30，并注明 D01–D26 的权威正文仍在规格 §14（不要在本次把 26 行重抄一遍当第二合同）。AGENTS.md 要求台账随里程碑更新，所以「文件不存在」不是跳过的理由。

AGENTS.md「测试用 FakeLLM / FakeTool，不调真实 provider」后加一句窄例外：`v15/**/test_*.py` 仍然如此；唯一真实调用入口是 `v15/provider/smoke.py --real-provider-smoke`，且必须在没有打开的数据库事务时调用。

#### 9. 故意不做的事

- 不引入 litellm、httpx、requests。
- 不把 v8 `DeepSeekLLM` 搬过来（默认模型已退役，且 `generate` 返回的是 EffectResult，不是 v15 的 `{content, prompt_tokens, cost_usd}`）。
- 不在 attempt 上新增 status，不放宽 `failed` 的 CHECK。
- 不把 `cost_usd = 0` 当未知。
- 不在 SQL 里用正则切语句，不在 SQL 里算钱（价目含时区，放进数据库会变成第二种时钟权威）。
- 不把 `statement_timeout` 从 30s 改到 120s。
- 不让 `OPENAI_MODEL` 覆盖已冻结的 `resolved_config.llm.model`。
- 不跟随 HTTP 重定向，不使用环境代理。
- 不在 gate 里 sleep DeepSeek 的 10 分钟。

### 状态流（新分支）

```text
begin 已提交 attempt(leased, call_started=false)
        │
        ├─ preflight 失败
        │     reject_unstarted → attempt failed（不计 call）
        │     invoke failed P1539，scratch 删除，span exit
        │
        └─ mark 提交 call_started=true，连接 IDLE
              │
              ├─ HTTP 成功且可计价 → settle（既有）→ executing
              ├─ 确定性 4xx / content_filter / request_invalid
              │     reject_started → attempt unknown（计 call，不计 cost）
              │     invoke failed P1539
              └─ 超时 / 429 / 5xx / unpriced / usage_invalid
                    abandon → attempt unknown（计 call，不计 cost）
                    invoke runnable，fence+1，span 仍开
                    下一轮 claim → begin n+1，直到 max_io_attempts
```

乱序：对终态 attempt 再调用三函数 → `P1502`，无写入。abandon 与 `v15_reclaim_expired` 并发：一个把行写成 unknown，另一个看到终态后 `P1502` 或跳过；worker 看到 `P1502` 不得再 `complete`。重复 abandon 不是第二次计费，因为第二次不会再执行 release（事务在终态检查处抛出）。

（`exec_enabled` 暂停态已随适配器-only 冒烟一并移除——评审 F8。冒烟不进 DB，不存在暂停态。）

## File-by-file impact

| 文件 | 变更 | 为何 | 顺序 |
|---|---|---|---|
| `docs/designs/v15-jaz-dev.md` | rev 9；§0.0、§0.6、§1、§4.5.5、§8.1、§12、§13 一行、§14 D27–D30、§15 stage 10、§18 | 冻结协议要求规格与 gate 同提交 | M1，与 SQL/gate 原子 |
| `v15/load.py` | `SQL_LOAD_ORDER` 末尾追加 provider SQL；`STAGE_THROUGH["provider"]=10` | 累计加载 | M1。先 grep 测试里对长度 9 的断言 |
| `v15/provider/v15_provider.sql` | 三函数；`CREATE OR REPLACE v15_io_sqlstate`；按需 REPLACE `v15_repl_sqlstate` | 新转移。不加表 | M1 |
| `v15/provider/setup_db.py` | 照 `v15/govern/setup_db.py`（而非 io——评审 F10：govern 前需先建五个可选 hook owner 角色，规格 §15）：DROP 所有 `agent_v15_*`、重建全部角色（含五个 `v15_hook_*`）、`load_stage(..., "provider")`。角色 SQL 不进加载文件 | stage 纪律 | M1 |
| `v15/provider/test_provider.py` | M1 只含 SQL 用例与 keyless 骨架中不依赖适配器的部分；M2 加上传输与 worker；M3 加上 smoke 退出码 | 第十道 gate | 分里程碑追加，每步都全绿 |
| `v15/provider/README.md` | 新。写明前缀 vs 合运行时、三时钟、keyless 命令、冒烟不是 gate | 收尾工件 | M1 创建，M3 补冒烟段 |
| `v15/provider/__init__.py` | 空文档，无 import | 防止 `import v15.provider` 拉起 urllib | M1 |
| `v15/README.md` | 十条加载序；合运行时是 `agent_v15_provider`；`agent_v15_govern` 改为前缀；keyless 包装 | 今天这两句写的是九文件 | M1 |
| `v15/govern/README.md` | 「九个文件才是合运行时」改为 govern 仍是前缀，合运行时在 provider | 同上 | M1 |
| `docs/reviews/v15-conformance-matrix-2026-09-29.md` | 新行 | AGENTS.md | M1 写 SQL 行，M2 补计价与 wire 行 |
| `docs/reviews/v15-deviation-ledger-*.md` | D27–D30 | AGENTS.md | M1 |
| `AGENTS.md` | 一句冒烟例外 | 否则 smoke 违反仓库约定 | M3 |
| `v15/provider/errors.py` | 三个异常 | worker 与适配器解耦 | M2 |
| `v15/provider/pricing.py` | 价目与 `compute_cost` | fail-closed | M2 |
| `v15/provider/deepseek.py` | 适配器与默认传输 | 唯一 socket 实现 | M2 |
| `v15/provider/support.py` | seed / open 辅助，供 gate 与 smoke。无网络 | 避免 smoke import 测试模块 | M2 |
| `v15/fake_llm.py` | `complete` 增加忽略的 `llm_config=None` | 调用点统一。不增加网络 import | M2，与 worker 原子 |
| `v15/worker.py` | lease 参数化；剩余租约前置检查；preflight；三类异常；NUL 替换；Decimal 成本拼进 jsonb；三处 `_mark_and_settle` 调用点接线 | 唯一调用点 | M2 |
| `v15/provider/smoke.py` | opt-in 脚本 | 不是 gate | M3 |
| `v15/io/README.md` | 不改行为。可加一句「真实 provider 不在本 stage」 | 可选，非必须 | 不做也行 |

明确不改：`v15/schema/v15_schema.sql`、`v15/io/v15_io.sql`、`v15/govern/v15_govern.sql`、`v15/config/v15_config.sql`、`v8/**`、`jaz/**`、种子 profile 的 `model=fake`。映射函数的新分支只出现在 `v15_provider.sql` 的 `CREATE OR REPLACE`。

grep 实证（评审 F2）：现有 gate **没有**任何 `len(SQL_LOAD_ORDER)==9` 类断言；无需改旧断言。M1 在 provider gate 里**新增**前缀保持断言：`files_through("govern")` 仍是前 9 个且末项为 govern SQL，完整列表长度为 10 且末项为 provider SQL。

## Risks and migration

- **rev 9 是行为合同变更。** 旧代码没有三函数；新 worker 在 FakeLLM 路径上不调用它们。回滚 = 回到不含 stage 10 的提交。前缀库不依赖新函数。没有表迁移、没有列默认值变更。已存在的 `agent_v15_*` 库会被下一个 `setup_db` 强制 DROP，不存在在线升级。
- **`CREATE OR REPLACE v15_io_sqlstate`** 在只加载到 govern 的库里不发生。全量加载后多一个 CASE 臂，旧码的返回值不变。oid 应保持；provider gate 不必重复 govern 的 `v15_on_phase` oid 仪式，但 SQL 里不得出现对 `v15_on_phase` 或四个治理 handler 的 `CREATE`/`REPLACE`/`DROP`。
- **子送达映射若漏改**，402 拒绝会在 `v15_io_terminal` 里抛 `P1523` 并回滚，attempt 保持 `leased`，worker 若再把异常吃掉就会等租约后重试 402。M1 的子 invoke 用例就是这条风险的闸门。
- **exit hook abort** 会使 reject 回滚。已在 §4.5.5 写明，不假装确定性拒绝不可被坏 hook 撤销。
- **发票可高于 `cost_used`，也可低于**（评审 F6）：unknown 调用漏计使发票偏高（D28）；节假日按高峰估算使 `cost_used` 偏高（D30 重述）。`cost_used` 是估算值，`cost_limit` 是治理闸门不是对账单——文档与 README 都不得写成「预算等于账单」或任何单向不等式保证。
- **pro 不在 allowlist**（用户裁决 B）：`preflight` 即 `model_not_allowlisted`（unstarted，不计 call）。后续扩入须按 §18 与官方价目同修订。
- **180s 租约** 只影响真实 Worker。崩溃后最坏多等 180s 才回收。不要把这个默认写回 `LEASE` 常量。
- **key 泄漏：** 异常与冒烟输出不得带 body。传输禁用代理与重定向。自定义 `OPENAI_API_URI` 仍允许（v8 约定），冒烟只打印 host。非 https 在预检被 `endpoint_rejected`，不计 call。
- **`json.dumps(Decimal)`** 会抛 `TypeError` 或被某人用 `default=float` 变成二进制浮点。worker 必须走「十进制文本嵌入 JSON」；M2 用一条 `cost_usd` 为 `Decimal("0.15")` 的 settle 断言库内 `cost_usd` 与之一致，而不是 `0.149999…`。
- 回滚旧 worker 对新 SQL：新函数无人调用即无影响。回滚新 SQL、留下新 worker：FakeLLM 路径不引用新函数，仍然安全；真实 provider 路径会在调用缺失函数时失败并留下 `call_started` attempt，最终被回收成 unknown。不要只发 worker 不发 SQL。

## Implementation order

每一里程碑：该步测试退出码 0 → 更新该步点名的收尾工件 → `git add` 按路径 → `git status` 确认没有 `.env` → `git commit` → `git push origin main`。禁止 `git add -A`、`--no-verify`、force-push。gate 串行。任一步红就停。

**M1 — 规格 + stage 10 SQL（原子，不可拆）。** 此时还没有适配器。

1. grep `SQL_LOAD_ORDER`、`P1538`、`v15_govern.sql` 在 `v15/**/test_*.py` 与 `docs/reviews/v15-*` 中的硬编码。
2. 读 `v15_repl_sqlstate`、`v15_repl_deliver_nonfatal`、`v15_io_close_self`、govern 里 exit 是否动池。按 Design 决定 REPLACE 哪些映射。
3. 写规格 rev 9、`v15_provider.sql`、`load.py`、`setup_db.py`、`__init__.py`、README 两处、矩阵里 SQL 行、偏差台账 D27–D30（D27–D30 的句子可以先落地；wire 行为在 M2 才有测试，矩阵行在 M2 补「已由测试证明」）。D27 的规格句子在 M1 写上是允许的，但矩阵不要声称 M1 的 gate 证明了「线上无 temperature」。
4. `test_provider.py` 覆盖三函数、`P1501`/`P1502`/`P1524`、402 形状、abandon 后 fence 与 span、子送达、`max_io` 耗尽不插入新行。用直接 SQL 加一个注入用的假结果即可，不必有 HTTP 客户端。
5. 命令：`env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v15/provider/test_provider.py`，退出码 0。再跑 `uv run python v15/io/test_io.py` 与 `uv run python v15/govern/test_govern.py`（govern 会加载 `v15.load`，用来抓住「9 文件」断言）。若 grep 显示 loop/tree 也断言加载长度，一并重跑。
6. `git add`：`docs/designs/v15-jaz-dev.md`、`docs/reviews/v15-conformance-matrix-2026-09-29.md`、实际改到的 ledger 路径、`v15/load.py`、`v15/README.md`、`v15/govern/README.md`、`v15/provider/v15_provider.sql`、`v15/provider/setup_db.py`、`v15/provider/test_provider.py`、`v15/provider/__init__.py`、`v15/provider/README.md`，以及 grep 迫使修改的既有 `test_*.py`。提交信息：`v15: add provider reject and abandon transitions`。

**M2 — 适配器、计价、worker（原子）。** 依赖 M1 的函数已在库里。

1. 读 `v15/protocol/split_sql.py`，确认 NUL 合成失败与 `test_io` 一致。不一致就先修切分器并重跑 `v15/protocol/test_protocol.py` 与 `v15/io/test_io.py`，与 M2 同一提交（不要先交一个红的 stage 4）。
2. 读 `v15_loop_snapshot`。确认 `llm` 在 snapshot 内；否则按 Design REPLACE。
3. 打开官方 pricing 页核对 **flash** 两档价格与 12:00/18:00 边界分钟（抄录进 `pricing.py` 注释；pro 不在本次范围——评审 F11 删除残留的 pro 抄价指令）。
4. 实现 `errors.py`、`pricing.py`、`deepseek.py`、`support.py`；改 `fake_llm.py` 与 `worker.py`；把 hermetic 用例补进 `test_provider.py`；矩阵补 wire / 计价 / NUL / keyless 行。
5. 先跑 provider gate（含 pop 与 `urlopen` patch），退出码 0。再串行重跑全部九道：`schema`、`namespace`、`config`、`protocol`、`repl`、`io`、`loop`、`tree`、`govern`。worker 是共享的，loop/tree/govern 必跑；io 必跑因为它扫描 `fake_llm.py` 的 import。九道都退出码 0，且既有断言一字不放宽。
6. `git add` 仅 M2 路径：`v15/provider/errors.py`、`pricing.py`、`deepseek.py`、`support.py`、`test_provider.py`、`README.md`（若补了时钟段落）、`v15/fake_llm.py`、`v15/worker.py`、矩阵、以及若动过的 `split_sql.py` 与其 gate。不要加入 `.env`。提交信息：`v15: wire DeepSeek adapter behind FakeLLM`。

**M3 — 冒烟脚本与约定例外。**

1. 实现 `smoke.py`。provider gate 增加无 flag 退出 0、有 flag 无 key 退出 2、且 `urlopen` 抛 `AssertionError` 时这两条仍不触网。
2. 更新 `AGENTS.md`、`v15/provider/README.md` 的冒烟段、矩阵一行「冒烟脚本不是 gate」。
3. 重跑 provider gate，退出码 0。本步不改 worker 与 SQL 则不必重跑九道；若 diff 碰到它们，回到 M2 的重跑集合。不要为了让无 key 的环境变绿而去跑真实 HTTP。
4. `git add`：`v15/provider/smoke.py`、`v15/provider/test_provider.py`、`v15/provider/README.md`、`AGENTS.md`、矩阵。提交信息：`v15: add opt-in DeepSeek smoke outside the gates`。

M2 结束时功能已可被手工 `Worker(dsn, DeepSeekProvider(), id, lease="180 seconds")` 使用。M3 只是把这次调用收成可重复的脚本并锁住 keyless。不要把 M1–M3 合成一个提交。

---

## 执行索引

| 工作项 | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| M1 规格修订 + stage 10 SQL | rev 9 落地：三转移 + P1539 + stage 10 追加，gate 全绿 | `env -u ... UV_NO_ENV_FILE=1 uv run python v15/provider/test_provider.py` 退出码 0；io/govern（及 grep 命中的）gate 复跑全绿；规格/矩阵/台账同提交更新 | `docs/designs/v15-jaz-dev.md`、`v15/provider/{v15_provider.sql,setup_db.py,test_provider.py,__init__.py,README.md}`、`v15/load.py`、`v15/README.md`、`v15/govern/README.md`、矩阵、台账 | 无（先行） | 中 |
| M2 适配器 + 计价 + worker | DeepSeekProvider/pricing/errors/support + worker 接线（preflight、三类异常、NUL、Decimal 成本） | provider gate（含 pop env + urlopen patch）退出码 0；九道既有 gate 串行复跑全绿且断言零放宽 | `v15/provider/{errors.py,pricing.py,deepseek.py,support.py}`、`v15/fake_llm.py`、`v15/worker.py`、矩阵 | M1 | 大 |
| M3 冒烟脚本 + 约定例外 | opt-in 真连冒烟与 AGENTS.md 窄例外 | smoke 无 flag→0、有 flag 无 key→2 且不触网（gate 断言）；AGENTS/README/矩阵更新 | `v15/provider/smoke.py`、`AGENTS.md`、`v15/provider/README.md`、矩阵 | M2 | 小 |

## References

- 冻结规格：`docs/designs/v15-jaz-dev.md`（§4.5/§8.1/§12/§13/§17/§18）
- v8 先例：`v8/loop/runtime.py`、`v8/compat/test_compat.py`（keyless 纪律与 opt-in 冒烟）
- jaz 先例：`jaz/src/jaz/llm/pricing.py`、`jaz/src/jaz/llm/model_prices.json`、`jaz/src/jaz/llm/openai.py`
- DeepSeek 官方文档（见 Background 链接）
- v15 实现树：`v15/worker.py`、`v15/fake_llm.py`、`v15/io/`、`v15/config/`
